"""The phases' thin path end to end through the engine, over fakes (ADR-0309 §2:6, §3, §4).

With the opt-in set, a message the chat's reader takes in runs ADR-0309 §3's table:
the conversation, the windows and understanding as today, then planning, authorizing,
acting with digesting beside it, and planning again where a call brought something.
The phases write the activation's messages into the conversation as it runs, and the
episode freezes with its rounds, labels, digests and messages. With the opt-in unset,
today's path answers as it always has.

The five cases are the brief's: a quick question in one round, a search digested and
answered in a second, a remember, a booking that comes back *needs you*, and a stop
mid-task.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import AT, Harness, NoStepPlanner
from test_loop_search import _ACCOUNT, _CONFIGURED_SEARCH
from understanding_support import understanding_stage

from ai_assistant.core.errors import ConfigurationError, ConversationStoreError
from ai_assistant.core.types import (
    ActivationStop,
    CapabilityEffect,
    CapabilityResult,
    ChatDevice,
    ControllerRule,
    ControllerStage,
    CostBasis,
    DataTier,
    DeviceAccess,
    DigestOutcome,
    EgressBinding,
    EpisodicMemory,
    Idempotency,
    LabelKind,
    MessageAuthor,
    PermissionOutcome,
    PermissionRuling,
    ProcessingReason,
    ProposedCall,
    Reversibility,
    RiskLevel,
    RoundResponse,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.orchestration.acting import ActingStage, OwnRecordsByCapability
from ai_assistant.orchestration.authorizer import AuthorizingStage
from ai_assistant.orchestration.chat import COULDNT_FINISH, ChatWriter
from ai_assistant.orchestration.payloads import DEFAULT_MAX_PAYLOAD_BYTES
from ai_assistant.orchestration.phase_path import MessageWriter, PhasePath, PhaseTools
from ai_assistant.orchestration.remembering import REMEMBER, RememberCalls, remembered_record_id
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    FakeEgressBinder,
    FakeMemoryPolicy,
    FakeMemoryWriter,
    FakeModelProvider,
    FakeRecipientGrantStore,
    FakeStoryStore,
    FakeToolCallingCompleter,
    FakeWebSearcher,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import ActionPolicy, EgressBinder
    from ai_assistant.core.types import (
        ActionRequest,
        Message,
        MessageReceipt,
        NewMessage,
        OfferedTool,
        PermissionDecision,
    )

_PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)

#: How long a case waits for the reader to settle before it fails, rather than hangs.
_SETTLE: Final = 5.0

#: A booking in the world: not safe to repeat, its outcome can be unknown, high risk.
_BOOK: Final = ToolDefinition(
    id="book",
    capability="book",
    description="Book a table for a date.",
    risk_level=RiskLevel.HIGH,
    reversibility=Reversibility.RECOVERABLE,
    side_effecting=True,
    reads=(DataTier.PERSONAL,),
    writes=(DataTier.PERSONAL,),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
    effect=CapabilityEffect.WORLD,
    leaves_hub=True,
    result=CapabilityResult.NO_OUTSIDE_TEXT,
    outcome_can_be_unknown=True,
    safe_to_repeat=False,
    parameters_schema={
        "type": "object",
        "properties": {"date": {"type": "string"}},
        "required": ["date"],
        "additionalProperties": False,
    },
)

_CAPABILITIES: Final = ("web_search", "remember", "book")

#: A digest answering from the one record it read, by the label local to the call.
_DIGESTED: Final = json.dumps({"evidence": [{"text": "It opens at nine.", "source": "D1"}]})


class _Policy:
    """The thin path's test policy: a call in the world needs you, and nothing else does.

    The canonical fake asks about every disclosure and every unknown cost, which a
    search is; a test hub's policy allows the configured search (ADR-0247 §3).
    """

    def __init__(self) -> None:
        self.requests: list[ActionRequest] = []

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        self.requests.append(request)
        if request.tool.effect is CapabilityEffect.WORLD:
            return PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="test: the world")
        return PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="test: allowed")

    async def resolve(self, confirmed: PermissionDecision, *, approved: bool) -> PermissionRuling:
        del confirmed, approved
        msg = "the phases resume nothing (ADR-0306 §4:8)"
        raise AssertionError(msg)


class _GatedCompleter(FakeToolCallingCompleter):
    """A scripted completer whose round ``gated`` answers only once its gate opens."""

    def __init__(self, *responses: RoundResponse, gated: int) -> None:
        queue = list(responses)

        def next_response(
            _messages: Sequence[Message], _tools: Sequence[OfferedTool]
        ) -> RoundResponse:
            return queue.pop(0)

        super().__init__(response=next_response)
        self._gated = gated
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()

    async def respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        if len(self.calls) + 1 == self._gated:
            self.entered.set()
            await self.gate.wait()
        return await super().respond(messages, tools, model=model)


def _phases(  # noqa: PLR0913 — one knob per seam a case varies
    completer: FakeToolCallingCompleter,
    *,
    digests: FakeModelProvider | None = None,
    searcher: FakeWebSearcher | None = None,
    policy: ActionPolicy | None = None,
    binder: EgressBinder | None = None,
    registered_search: frozenset[str] = frozenset(),
    writer: MessageWriter | None = None,
) -> Callable[[Harness], PhasePath]:
    """The thin path as the composition root builds it, over the harness's own stores."""

    def build(harness: Harness) -> PhasePath:
        tools = PhaseTools(
            registry=harness.invoker,
            invoker=harness.invoker,
            own_records=(REMEMBER,),
            searcher=searcher,
            search_query="query",
        )
        memory_writer = FakeMemoryWriter(
            store=harness.memory, policy=FakeMemoryPolicy(), now=lambda: AT
        )
        return PhasePath(
            completer=completer,
            provider=digests if digests is not None else FakeModelProvider(reply=_DIGESTED),
            authorizing=AuthorizingStage(
                registry=tools,
                policy=policy if policy is not None else _Policy(),
                memory_policy=FakeMemoryPolicy(),
                trail=harness.trail,
                stories=FakeStoryStore(now=lambda: AT),
                memory=harness.memory,
                binder=binder,
                registered_search=registered_search,
                now=lambda: AT,
            ),
            acting=ActingStage(
                plans=harness.plans,
                invoker=tools,
                own_records=OwnRecordsByCapability(
                    {"remember": RememberCalls(writer=memory_writer, now=lambda: AT)}
                ),
                timeout=timedelta(seconds=5),
                now=lambda: AT,
            ),
            tools=tools,
            plans=harness.plans,
            writer=(
                ChatWriter(
                    conversations=harness.conversation_store,
                    max_payload_bytes=DEFAULT_MAX_PAYLOAD_BYTES,
                )
                if writer is None
                else writer
            ),
            capabilities=_CAPABILITIES,
            round_limit=3,
            round_wait=timedelta(seconds=5),
            excerpt_chars=2000,
            part_chars=4000,
            now=lambda: AT,
        )

    return build


def _harness(completer: FakeToolCallingCompleter, **knobs: Any) -> Harness:
    return Harness(
        planner=NoStepPlanner(),
        understanding=understanding_stage(),
        tools=(_BOOK,),
        phases=_phases(completer, **knobs),
    )


async def _conversation(harness: Harness) -> str:
    await harness.engine.set_my_devices([_PHONE])
    return (await harness.engine.start_conversation()).id


async def _say(harness: Harness, conversation: str, text: str) -> None:
    message = UserMessage(device_id=_PHONE.device_id, message_id="m-1", text=text)
    await harness.engine.write_message(conversation, message=message)


async def _messages(harness: Harness, conversation: str) -> list[TranscriptMessage]:
    page = await harness.conversation_store.transcript(conversation, limit=100)
    assert page is not None
    return [one for one in page.entries if isinstance(one, TranscriptMessage)]


async def _settled(harness: Harness, conversation: str) -> EpisodicMemory:
    """Wait for the activation to end and its episode to freeze, then read it."""
    deadline = asyncio.get_running_loop().time() + _SETTLE
    while True:
        state = await harness.engine.conversation(conversation)
        episodes = [
            one
            for one in await harness.memory.export()
            if isinstance(one, EpisodicMemory)
            and one.processing_record is not None
            and not one.processing_record.is_open
        ]
        if state is not None and not state.state.working and episodes:
            (episode,) = episodes
            return episode
        if asyncio.get_running_loop().time() > deadline:
            msg = "the activation never settled"
            raise AssertionError(msg)
        await asyncio.sleep(0.001)


def _said(written: Sequence[TranscriptMessage]) -> list[tuple[MessageAuthor, str]]:
    return [(one.author, one.text) for one in written]


def _stages(episode: EpisodicMemory) -> list[tuple[ControllerStage, ControllerRule]]:
    assert episode.processing_record is not None
    return [(one.stage, one.due) for one in episode.processing_record.stages]


def _call(call_id: str, name: str, **arguments: object) -> ProposedCall:
    return ProposedCall(call_id=call_id, name=name, arguments=arguments)  # type: ignore[arg-type]  # JSON values


# --- the five cases ---------------------------------------------------------------------


async def test_a_quick_question_is_answered_in_one_round() -> None:
    """ADR-0307 §2, §3:1, §8:1: one round, its text written, and the activation ends."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="Hello! How can I help?"))
    harness = _harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "hi")
    episode = await _settled(harness, conversation)

    assert _said(await _messages(harness, conversation)) == [
        (MessageAuthor.USER, "hi"),
        (MessageAuthor.ASSISTANT, "Hello! How can I help?"),
    ]
    assert _stages(episode) == [
        (ControllerStage.BEGIN_CONVERSATION, ControllerRule.CONVERSATION_UNRESOLVED),
        (ControllerStage.WINDOWS, ControllerRule.WINDOWS_UNASSEMBLED),
        (ControllerStage.UNDERSTANDING, ControllerRule.NOT_UNDERSTOOD),
        (ControllerStage.PLANNING, ControllerRule.FIRST_ROUND_DUE),
        (ControllerStage.AUTHORIZING, ControllerRule.ROUND_UNAUTHORIZED),
        (ControllerStage.ACTING, ControllerRule.ROUND_AUTHORIZED),
        (ControllerStage.END, ControllerRule.NOTHING_DUE),
    ]
    assert episode.processing_record is not None
    (planning_round,) = episode.processing_record.rounds
    assert planning_round.text == "Hello! How can I help?"
    assert episode.outcome == "Hello! How can I help?"
    # ADR-0306 §5:3-§5:5: the message is claimed, then finished with its position.
    (effect,) = await harness.plans.activation_effects([episode.id.removeprefix("activation:")])
    assert effect.round == planning_round.id
    assert effect.outcome is ToolOutcome.SUCCEEDED
    assert effect.position == 2
    assert effect.place == f"conversation:{conversation}"
    # No old-path stage ran.
    ran = {stage for stage, _ in _stages(episode)}
    assert not ran & {ControllerStage.ASSOCIATE_GOAL, ControllerStage.COMPOSE}


async def test_a_search_is_digested_then_answered_in_a_second_round() -> None:
    """ADR-0308 §4, ADR-0309 §3:3: the search's result reaches planning as evidence."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            text="Let me look that up.",
            calls=(_call("c1", "web_search", query="museum hours", looking_for="when it opens"),),
        ),
        RoundResponse(text="It opens at nine."),
    )
    searcher = FakeWebSearcher(results=("Open daily from 9:00 to 17:00.",))
    harness = _harness(completer, searcher=searcher)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when does the museum open?")
    episode = await _settled(harness, conversation)

    assert _said(await _messages(harness, conversation))[1:] == [
        (MessageAuthor.ASSISTANT, "Let me look that up."),
        (MessageAuthor.ASSISTANT, "It opens at nine."),
    ]
    # Planning was offered the search without the origin the hub fills, and the
    # searcher's own proposal filled it.
    (offered,) = [one for one in completer.calls[0].tools if one.name == "web_search"]
    schema = offered.model_dump()["parameters"]
    assert "origin" not in schema["properties"]
    assert "looking_for" in schema["required"]
    (searched,) = searcher.searched
    assert searched.request.parameters["origin"] == "https://search.example.com"
    assert searched.request.parameters["query"] == "museum hours"
    # The first round's step ran acting with digesting beside it, each its own entry;
    # the second round, with no call, ran acting alone and ended the activation.
    assert _stages(episode)[3:] == [
        (ControllerStage.PLANNING, ControllerRule.FIRST_ROUND_DUE),
        (ControllerStage.AUTHORIZING, ControllerRule.ROUND_UNAUTHORIZED),
        (ControllerStage.ACTING, ControllerRule.ROUND_AUTHORIZED),
        (ControllerStage.DIGESTING, ControllerRule.ROUND_AUTHORIZED),
        (ControllerStage.PLANNING, ControllerRule.ROUND_DUE),
        (ControllerStage.AUTHORIZING, ControllerRule.ROUND_UNAUTHORIZED),
        (ControllerStage.ACTING, ControllerRule.ROUND_AUTHORIZED),
        (ControllerStage.END, ControllerRule.NOTHING_DUE),
    ]
    # Read outside content, so the episode says so; the thin path places it for the
    # owner alone (ADR-0309 §5:10 left to a later lane).
    assert episode.provenance.derived_from_external
    record = episode.processing_record
    assert record is not None
    (digest,) = record.digests
    assert digest.outcome is DigestOutcome.ANSWERED
    assert digest.question == "when it opens"
    assert [(one.text, one.source) for one in digest.evidence] == [("It opens at nine.", "R1")]
    assert [(one.label, one.kind) for one in record.labels] == [("R1", LabelKind.RESULT)]
    # The second round was shown the evidence under the result's label, never the
    # raw result.
    shown = json.loads(completer.calls[1].messages[1].content)
    assert shown["evidence"][0]["digest_of"] == "R1"
    assert "Open daily" not in completer.calls[1].messages[1].content
    assert episode.outcome == "Let me look that up.\n\nIt opens at nine."


async def _configured_search_run(*, registered: bool) -> tuple[Harness, FakeWebSearcher, str]:
    """Two searches and an answer, under the real policy over a configured search.

    The deployment's own ``ThresholdActionPolicy`` over its configured search, and a
    binding seam holding the search against the connected account; ``registered`` is
    whether authorizing is told the search is the deployment's registered one.
    """
    searcher = FakeWebSearcher(
        results=("Open daily from 9:00 to 17:00.",),
        cost_per_call=Decimal("0.005"),
        cost_currency="USD",
    )
    proposal = await searcher.request("probe")
    assert proposal is not None
    binder = FakeEgressBinder()
    binder.register_egress(proposal.tool, reference=_ACCOUNT.reference, identity=_ACCOUNT.identity)
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(_call("c1", "web_search", query="museum hours", looking_for="opening"),)
        ),
        RoundResponse(
            calls=(_call("c2", "web_search", query="museum prices", looking_for="price"),)
        ),
        RoundResponse(text="It opens at nine."),
    )
    harness = _harness(
        completer,
        searcher=searcher,
        policy=ThresholdActionPolicy(
            grants=FakeRecipientGrantStore(now=lambda: AT), configured_search=_CONFIGURED_SEARCH
        ),
        binder=binder,
        registered_search=frozenset({str(proposal.tool.id)}) if registered else frozenset(),
    )
    conversation = await _conversation(harness)
    await _say(harness, conversation, "when does the museum open, and what does it cost?")
    await _settled(harness, conversation)
    return harness, searcher, str(proposal.tool.id)


async def test_the_real_policy_allows_the_configured_search_after_outside_content() -> None:
    """ADR-0306 §4:4, ADR-0247 §2-§4: the configured provider's route reaches the phases.

    Authorizing writes ``closed_loop`` for the registered search as the old path does,
    so the first search is allowed, and so is the second, planned after the first's
    digest had been read: ADR-0247 §3's exception holds in an activation that has read
    outside content.
    """
    harness, searcher, search_id = await _configured_search_run(registered=True)

    assert len(searcher.searched) == 2, "both searches were allowed and ran"
    decisions = [one for one in await harness.trail.recent(limit=10) if one.tool.id == search_id]
    assert [one.ruling.outcome for one in decisions] == [PermissionOutcome.ALLOW] * 2
    bindings = [one.egress_binding for one in decisions]
    assert all(isinstance(one, EgressBinding) and one.closed_loop for one in bindings)
    # One of the two was planned after the activation had read outside content.
    outside = sorted(
        isinstance(one, EgressBinding) and one.planned_with_external_content for one in bindings
    )
    assert outside == [False, True]


async def test_without_the_registration_the_real_policy_sends_the_search_to_the_user() -> None:
    """What the hook fixes: no ``closed_loop``, so ADR-0247 §2's route is never reached
    and the disclosure floor rules every phases search *needs you*."""
    harness, searcher, search_id = await _configured_search_run(registered=False)

    assert searcher.searched == []
    decisions = [one for one in await harness.trail.recent(limit=10) if one.tool.id == search_id]
    assert decisions
    assert all(one.ruling.outcome is PermissionOutcome.CONFIRM for one in decisions)


async def test_a_remember_is_written_once_through_the_assistants_own_records() -> None:
    """ADR-0306 §3:2-§3:3: remembering is claimed, run directly and ends the round."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            text="I'll remember that.",
            calls=(_call("c1", "remember", statement="The user likes green tea."),),
        )
    )
    harness = _harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "remember I like green tea")
    episode = await _settled(harness, conversation)

    assert _said(await _messages(harness, conversation))[1:] == [
        (MessageAuthor.ASSISTANT, "I'll remember that."),
    ]
    effects = await harness.plans.activation_effects([episode.id.removeprefix("activation:")])
    (remembered,) = [one for one in effects if one.capability == "remember"]
    assert remembered.outcome is ToolOutcome.SUCCEEDED
    written = await harness.memory.get(remembered_record_id(remembered.id))
    assert written is not None
    assert written.content == "The user likes green tea."
    assert written.provenance.evidence == (episode.id,)
    # Done, no result, unmarked: one round and the end.
    assert episode.processing_record is not None
    assert len(episode.processing_record.rounds) == 1
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.NOTHING_DUE)


async def test_a_booking_that_needs_you_is_answered_cannot_be_done_yet() -> None:
    """ADR-0306 §4:8, ADR-0307 §9:4: a confirm runs nothing, and the next round says so."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "book", date="2026-10-12"),)),
        RoundResponse(text="I can't book that yet: it needs you, and that isn't possible yet."),
    )
    harness = _harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "book a table for tomorrow")
    episode = await _settled(harness, conversation)

    assert _said(await _messages(harness, conversation))[1:] == [
        (
            MessageAuthor.ASSISTANT,
            "I can't book that yet: it needs you, and that isn't possible yet.",
        ),
    ]
    # The second round was shown the call as needing the user.
    shown = json.loads(completer.calls[1].messages[1].content)
    (call,) = shown["rounds"][0]["calls"]
    assert call["outcome"].startswith("needs the user: it cannot be done yet")
    # Nothing ran: no effect record for the booking, and the invoker was not reached.
    effects = await harness.plans.activation_effects([episode.id.removeprefix("activation:")])
    assert all(one.capability is None for one in effects)
    assert harness.invoker.invocations == []
    # The first round wrote no message: its text was empty (ADR-0307 §3:2).
    assert episode.processing_record is not None
    assert episode.processing_record.rounds[0].text == ""


async def test_a_stop_mid_task_ends_after_the_current_round_and_writes_nothing_more() -> None:
    """ADR-0297 §4, ADR-0307 §8:5: a stop lands after the current step."""
    completer = _GatedCompleter(
        RoundResponse(
            text="Let me look that up.",
            calls=(_call("c1", "web_search", query="museum hours", looking_for="when it opens"),),
        ),
        RoundResponse(text="It opens at nine."),
        gated=2,
    )
    harness = _harness(completer, searcher=FakeWebSearcher())
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when does the museum open?")
    await asyncio.wait_for(completer.entered.wait(), _SETTLE)
    state = await harness.engine.conversation(conversation)
    assert state is not None
    assert state.state.activation_id is not None
    assert await harness.engine.stop_activation(state.state.activation_id) is (
        ActivationStop.STOPPED
    )
    completer.gate.set()
    episode = await _settled(harness, conversation)

    assert _said(await _messages(harness, conversation))[1:] == [
        (MessageAuthor.ASSISTANT, "Let me look that up."),
    ]
    assert episode.processing_record is not None
    assert episode.processing_record.reason is ProcessingReason.STOPPED
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.STOPPED)
    assert episode.outcome == "Let me look that up."


# --- a message the place did not take ----------------------------------------------------


class _Gone:
    """A place's writer whose conversation is gone: nothing is recorded."""

    async def send(self, conversation_id: str, message: NewMessage) -> MessageReceipt | None:
        del conversation_id, message
        return None


class _Broken:
    """A place's writer whose store fails: whether it recorded the message is unknown."""

    async def send(self, conversation_id: str, message: NewMessage) -> MessageReceipt | None:
        del conversation_id, message
        msg = "the store is down"
        raise ConversationStoreError(msg)


@pytest.mark.parametrize(
    ("writer", "outcome", "reason"),
    [
        (_Gone(), ToolOutcome.FAILED, True),
        (_Broken(), ToolOutcome.INDETERMINATE, False),
    ],
)
async def test_a_message_the_place_did_not_take_is_finished_without_a_position(
    writer: MessageWriter, outcome: ToolOutcome, *, reason: bool
) -> None:
    """ADR-0306 §5:5: a message not done, or unknown, carries no position."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="Hello."))
    harness = _harness(completer, writer=writer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "hi")
    episode = await _settled(harness, conversation)

    (effect,) = await harness.plans.activation_effects([episode.id.removeprefix("activation:")])
    assert effect.outcome is outcome
    assert effect.position is None
    assert (effect.reason is not None) is reason
    assert episode.outcome is None


# --- the ends that write *couldn't finish* ----------------------------------------------


async def test_the_round_limit_writes_couldnt_finish_after_earlier_messages() -> None:
    """ADR-0307 §3:7, §8:4: a loop of refused calls is ended by the round limit."""
    refused = RoundResponse(text="Trying.", calls=(_call("c1", "nowhere"),))
    completer = FakeToolCallingCompleter.scripted(refused, refused, refused)
    harness = _harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "do the impossible")
    episode = await _settled(harness, conversation)

    written = _said(await _messages(harness, conversation))[1:]
    assert written == [
        (MessageAuthor.ASSISTANT, "Trying."),
        (MessageAuthor.ASSISTANT, "Trying."),
        (MessageAuthor.ASSISTANT, "Trying."),
        (MessageAuthor.ASSISTANT, COULDNT_FINISH),
    ]
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.ROUND_LIMIT_REACHED)
    effects = await harness.plans.activation_effects([episode.id.removeprefix("activation:")])
    assert effects[-1].round is None
    assert episode.outcome is not None
    assert episode.outcome.endswith(COULDNT_FINISH)


async def test_a_planning_round_that_fails_writes_couldnt_finish() -> None:
    """ADR-0293 §10:2: a pass that raised ends with the fixed message."""
    harness = _harness(FakeToolCallingCompleter.scripted())
    conversation = await _conversation(harness)

    await _say(harness, conversation, "hi")
    episode = await _settled(harness, conversation)

    assert _said(await _messages(harness, conversation))[1:] == [
        (MessageAuthor.ASSISTANT, COULDNT_FINISH)
    ]
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.STAGE_FAILED)


# --- with the opt-in unset ---------------------------------------------------------------


async def test_with_the_opt_in_unset_todays_path_answers_unchanged() -> None:
    """ADR-0309 §2:6: no phase stage runs, and the compose stage writes the reply."""
    harness = Harness(planner=NoStepPlanner(), understanding=understanding_stage())
    conversation = await _conversation(harness)

    await _say(harness, conversation, "hi")
    episode = await _settled(harness, conversation)

    ran = {stage for stage, _ in _stages(episode)}
    assert ControllerStage.COMPOSE in ran
    assert not ran & {
        ControllerStage.PLANNING,
        ControllerStage.AUTHORIZING,
        ControllerStage.ACTING,
        ControllerStage.DIGESTING,
    }
    assert episode.processing_record is not None
    assert episode.processing_record.rounds == ()


def test_the_phases_are_wired_only_beside_understanding() -> None:
    with pytest.raises(ConfigurationError, match="only beside both"):
        Harness(planner=NoStepPlanner(), phases=_phases(FakeToolCallingCompleter()))
