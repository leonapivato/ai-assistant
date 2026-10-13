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
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_activation_state import _admitted
from test_authorizer import _ACTIVATION, _episode
from test_engine import AT, Harness, NoStepPlanner
from test_loop_search import _ACCOUNT, _CONFIGURED_SEARCH
from test_planning import _episode as _past_episode
from understanding_support import recall_stage, understanding_stage

from ai_assistant.core.errors import (
    ConfigurationError,
    ConversationStoreError,
    MemoryStoreError,
    ModelTimeoutError,
    PlanningError,
)
from ai_assistant.core.types import (
    ActivationDigest,
    ActivationEffect,
    ActivationEnding,
    ActivationRecall,
    ActivationStop,
    Attestation,
    BeliefBand,
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
    EvidenceItem,
    Idempotency,
    InputOrigin,
    LabelKind,
    MemoryKind,
    MemorySource,
    MessageAuthor,
    NewMessage,
    PermissionOutcome,
    PermissionRuling,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    ProposedCall,
    Provenance,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    Reversibility,
    RiskLevel,
    RoundResponse,
    SemanticMemory,
    StageOutcome,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.orchestration.acting import ActingStage, OwnRecordsByCapability
from ai_assistant.orchestration.authorizer import AuthorizingStage
from ai_assistant.orchestration.chat import COULDNT_FINISH, ChatWriter, couldnt_finish
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.payloads import DEFAULT_MAX_PAYLOAD_BYTES
from ai_assistant.orchestration.phase_path import (
    MessageWriter,
    PhasePath,
    PhaseTools,
    PhaseWorking,
)
from ai_assistant.orchestration.recall import Recalled
from ai_assistant.orchestration.remembering import REMEMBER, RememberCalls, remembered_record_id
from ai_assistant.orchestration.understanding import Fetched, TranscriptWindow, WindowsStage
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    FakeEgressBinder,
    FakeMemoryPolicy,
    FakeMemoryStore,
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
        ActivationUnderstanding,
        MemorySearchResult,
        Message,
        MessageReceipt,
        OfferedTool,
        PermissionDecision,
    )
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.understanding import Windows

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
    wrap: Callable[[ChatWriter], MessageWriter] | None = None,
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
        chat = ChatWriter(
            conversations=harness.conversation_store, max_payload_bytes=DEFAULT_MAX_PAYLOAD_BYTES
        )
        place: MessageWriter = chat if wrap is None else wrap(chat)
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
            writer=place if writer is None else writer,
            capabilities=_CAPABILITIES,
            round_limit=3,
            round_wait=timedelta(seconds=5),
            excerpt_chars=2000,
            part_chars=4000,
            memory=harness.memory,
            recall_cap=6,
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


async def _settled(
    harness: Harness, conversation: str, *, seeded: frozenset[str] = frozenset()
) -> EpisodicMemory:
    """Wait for the activation to end and its episode to freeze, then read it.

    ``seeded`` names the frozen episodes a case stored beforehand, which are not it.
    """
    deadline = asyncio.get_running_loop().time() + _SETTLE
    while True:
        state = await harness.engine.conversation(conversation)
        episodes = [
            one
            for one in await harness.memory.export()
            if isinstance(one, EpisodicMemory)
            and one.id not in seeded
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


async def _last_ended(harness: Harness, conversation: str) -> ActivationEnding | None:
    """How the conversation's current state says its last activation ended (§8:3)."""
    digest = await harness.engine.conversation(conversation)
    assert digest is not None
    return digest.state.last_ended


def _classified(episode: EpisodicMemory) -> tuple[ProcessingStatus | None, object]:
    record = episode.processing_record
    assert record is not None
    return record.status, record.reason


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
    # It answered, so the state says done (ADR-0293 §8:3).
    assert _classified(episode) == (ProcessingStatus.COMPLETED, ProcessingReason.RETURNED)
    assert await _last_ended(harness, conversation) is ActivationEnding.DONE


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
    # A stop is no failure: the state tells it apart, and never as couldn't finish
    # (ADR-0295 §3:4, ADR-0297 §4).
    assert _classified(episode) == (ProcessingStatus.INTERRUPTED, ProcessingReason.STOPPED)
    assert await _last_ended(harness, conversation) is ActivationEnding.STOPPED


# --- a message the place did not take ----------------------------------------------------


class _Gone:
    """A place's writer whose conversation is gone: nothing is recorded."""

    def fitted(self, conversation_id: str, message: NewMessage) -> NewMessage:
        del conversation_id
        return message

    async def send(self, conversation_id: str, message: NewMessage) -> MessageReceipt | None:
        del conversation_id, message
        return None


class _Broken:
    """A place's writer whose store fails: whether it recorded the message is unknown."""

    def fitted(self, conversation_id: str, message: NewMessage) -> NewMessage:
        del conversation_id
        return message

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

    effects = await harness.plans.activation_effects([episode.id.removeprefix("activation:")])
    # The round's message, then the *couldn't finish* an activation that wrote nothing
    # owes (ADR-0293 §9:1), which the place took no better.
    assert [one.round is None for one in effects] == [False, True]
    assert all(one.outcome is outcome and one.position is None for one in effects)
    assert all((one.reason is not None) is reason for one in effects)
    assert episode.outcome is None


class _FailsOnce:
    """A place's writer whose first write raises what no store does: a fault."""

    def __init__(self, writer: ChatWriter) -> None:
        self._writer = writer
        self._failed = False

    def fitted(self, conversation_id: str, message: NewMessage) -> NewMessage:
        return self._writer.fitted(conversation_id, message)

    async def send(self, conversation_id: str, message: NewMessage) -> MessageReceipt | None:
        if not self._failed:
            self._failed = True
            msg = "the writer broke"
            raise RuntimeError(msg)
        return await self._writer.send(conversation_id, message)


async def test_a_message_that_fails_beside_a_remember_still_lists_what_was_remembered() -> None:
    """ADR-0293 §9:1: *couldn't finish* lists the effects the records say happened.

    The remember beside the failing message finished, so it is listed, though the step
    it ran in ended ``failed``; the message's own record is finished unknown.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            text="I'll remember that.",
            calls=(_call("c1", "remember", statement="The user likes green tea."),),
        )
    )
    harness = _harness(completer, wrap=_FailsOnce)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "remember I like green tea")
    episode = await _settled(harness, conversation)

    expected = couldnt_finish(("the tool remember ran",)).text
    assert _said(await _messages(harness, conversation))[1:] == [
        (MessageAuthor.ASSISTANT, expected)
    ]
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.STAGE_FAILED)
    effects = await harness.plans.activation_effects([episode.id.removeprefix("activation:")])
    (message,) = [one for one in effects if one.capability is None and one.round is not None]
    assert message.outcome is ToolOutcome.INDETERMINATE
    assert episode.outcome == expected


class _Cuts:
    """A place's writer that fits every message to its first five characters."""

    def __init__(self, writer: ChatWriter) -> None:
        self._writer = writer

    def fitted(self, conversation_id: str, message: NewMessage) -> NewMessage:
        del conversation_id
        return message.model_copy(update={"text": message.text[:5], "cut_off": True})

    async def send(self, conversation_id: str, message: NewMessage) -> MessageReceipt | None:
        return await self._writer.send(conversation_id, message)


async def test_the_outcome_keeps_the_text_the_place_holds() -> None:
    """ADR-0307 §10: the messages written, as the conversation holds them."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="Hello, how can I help?"))
    harness = _harness(completer, wrap=_Cuts)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "hi")
    episode = await _settled(harness, conversation)

    assert _said(await _messages(harness, conversation))[1:] == [(MessageAuthor.ASSISTANT, "Hello")]
    assert episode.outcome == "Hello"


async def test_two_results_digested_side_by_side_are_both_kept() -> None:
    """ADR-0286 §3:4, ADR-0308 §5:2: two digests recorded at once both reach the episode."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call("c1", "web_search", query="museum hours", looking_for="when it opens"),
                _call("c2", "web_search", query="museum prices", looking_for="what it costs"),
            )
        ),
        RoundResponse(text="It opens at nine."),
    )
    searcher = FakeWebSearcher(results=("Open daily from 9:00 to 17:00.",))
    harness = _harness(completer, searcher=searcher)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when does the museum open, and what does it cost?")
    episode = await _settled(harness, conversation)

    assert len(searcher.searched) == 2
    record = episode.processing_record
    assert record is not None
    assert sorted(one.question for one in record.digests) == ["what it costs", "when it opens"]
    assert episode.outcome == "It opens at nine."


# --- the ends that write *couldn't finish* ----------------------------------------------


async def test_an_activation_that_writes_nothing_writes_couldnt_finish() -> None:
    """ADR-0293 §9:1: a round with no text and no call ends having written nothing."""
    harness = _harness(FakeToolCallingCompleter.scripted(RoundResponse()))
    conversation = await _conversation(harness)

    await _say(harness, conversation, "hi")
    episode = await _settled(harness, conversation)

    assert _said(await _messages(harness, conversation))[1:] == [
        (MessageAuthor.ASSISTANT, COULDNT_FINISH)
    ]
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.NOTHING_DUE)
    assert episode.outcome == COULDNT_FINISH
    # It could not finish, and the state says so beside the message (ADR-0293 §8:3).
    assert _classified(episode) == (ProcessingStatus.FAILED, ProcessingReason.PROCESSING_FAILED)
    assert await _last_ended(harness, conversation) is ActivationEnding.COULDNT_FINISH


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
    # Ended by the round limit, not done: the state reads couldn't finish (#2855).
    assert _classified(episode) == (ProcessingStatus.FAILED, ProcessingReason.PROCESSING_FAILED)
    assert await _last_ended(harness, conversation) is ActivationEnding.COULDNT_FINISH


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
    assert await _last_ended(harness, conversation) is ActivationEnding.COULDNT_FINISH


class _TimesOut(FakeToolCallingCompleter):
    """A completer whose round meets the activation's deadline: a classified timeout."""

    async def respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        del messages, tools, model
        msg = "the activation's deadline passed"
        raise ModelTimeoutError(msg)


async def test_a_deadline_ending_writes_couldnt_finish_and_the_state_says_so() -> None:
    """ADR-0307 §3:7, ADR-0293 §8:3: a deadline ends it, and it could not finish."""
    harness = _harness(_TimesOut())
    conversation = await _conversation(harness)

    await _say(harness, conversation, "hi")
    episode = await _settled(harness, conversation)

    assert _said(await _messages(harness, conversation))[1:] == [
        (MessageAuthor.ASSISTANT, COULDNT_FINISH)
    ]
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.STAGE_TIMED_OUT)
    assert _classified(episode) == (ProcessingStatus.FAILED, ProcessingReason.TIMEOUT)
    assert await _last_ended(harness, conversation) is ActivationEnding.COULDNT_FINISH


async def test_an_activation_whose_every_message_the_place_refused_reads_couldnt_finish() -> None:
    """ADR-0293 §9:1: every message gone is an activation that wrote nothing."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="Hello."))
    harness = _harness(completer, writer=_Gone())
    conversation = await _conversation(harness)

    await _say(harness, conversation, "hi")
    episode = await _settled(harness, conversation)

    assert episode.outcome is None
    assert _classified(episode) == (ProcessingStatus.FAILED, ProcessingReason.PROCESSING_FAILED)
    assert await _last_ended(harness, conversation) is ActivationEnding.COULDNT_FINISH


# --- ADR-0308 §2-§3: recall's second run, and what planning is shown of its finds ----------

#: What understanding makes of "when?": a reading that names what the input did not.
_DENTIST: Final = "dentist appointment Elm Street"


async def _no_episode_window(_: frozenset[str]) -> tuple[EpisodicMemory, ...]:
    """An episode selector that selects nothing, so recall alone brings an episode."""
    return ()


class _DownForTheReading(FakeMemoryStore):
    """A store whose search fails for understanding's reading, and answers otherwise."""

    async def search(self, query: str, **kwargs: Any) -> MemorySearchResult:
        if query == _DENTIST:
            msg = "the store is down"
            raise MemoryStoreError(msg)
        return await super().search(query, **kwargs)


def _remembered(memory_id: str, source: MemorySource, fact: str) -> SemanticMemory:
    return SemanticMemory(
        id=memory_id,
        content=fact,
        fact=fact,
        provenance=Provenance(
            source=source,
            confidence=1.0 if source is MemorySource.USER_ASSERTED else 0.8,
            last_updated=AT,
            attestation=(
                Attestation(reported_by="mail", reported_at=AT)
                if source is MemorySource.EXTERNAL
                else None
            ),
        ),
    )


async def _recalling_harness(
    completer: FakeToolCallingCompleter, memory: FakeMemoryStore | None = None
) -> tuple[Harness, FakeModelProvider]:
    """A test hub with recall wired, its store holding what the second run finds."""
    store = memory if memory is not None else FakeMemoryStore(now=lambda: AT)
    noted = PlanningRound(
        id="round:past", recorded_at=AT, text="Booked it for Friday.", notes="they prefer mornings"
    )
    past = _past_episode("activation:past", rounds=(noted,)).model_copy(
        update={"content": f"{_DENTIST} booked for Friday"}
    )
    for record in (
        past,
        _remembered("said", MemorySource.USER_ASSERTED, f"{_DENTIST} with Dr Rao"),
        _remembered("reported", MemorySource.EXTERNAL, f"{_DENTIST} moved to 3pm"),
    ):
        await store.add(record)
    understanding = FakeModelProvider(
        reply=json.dumps({"meaning": _DENTIST, "meaning_ground": "stated"})
    )
    harness = Harness(
        planner=NoStepPlanner(),
        understanding=understanding_stage(model=understanding),
        tools=(_BOOK,),
        memory=store,
        windows=WindowsStage(episodes=_no_episode_window),
        recall=recall_stage(store),
        phases=_phases(completer),
    )
    return harness, understanding


async def test_a_found_episode_reaches_planning_after_recall_runs_again() -> None:
    """ADR-0308 §2, §3, ADR-0309 §3's row 6: B4b's path with recall's second run.

    The input names nothing recall's first run finds; understanding's reading does, so
    the second run, once understanding has recorded, finds the past episode and two
    remembered facts. Planning is shown the episode by its records and the user's fact,
    never the fact a source reported; understanding ran once and was shown none of it.
    """
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="It is on Friday."))
    harness, understanding = await _recalling_harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when?")
    episode = await _settled(harness, conversation, seeded=frozenset({"activation:past"}))

    assert _stages(episode) == [
        (ControllerStage.BEGIN_CONVERSATION, ControllerRule.CONVERSATION_UNRESOLVED),
        (ControllerStage.WINDOWS, ControllerRule.WINDOWS_UNASSEMBLED),
        (ControllerStage.RECALL, ControllerRule.NOT_RECALLED),
        (ControllerStage.UNDERSTANDING, ControllerRule.NOT_UNDERSTOOD),
        (ControllerStage.RECALL, ControllerRule.UNDERSTOOD_NOT_RECALLED),
        (ControllerStage.PLANNING, ControllerRule.FIRST_ROUND_DUE),
        (ControllerStage.AUTHORIZING, ControllerRule.ROUND_UNAUTHORIZED),
        (ControllerStage.ACTING, ControllerRule.ROUND_AUTHORIZED),
        (ControllerStage.END, ControllerRule.NOTHING_DUE),
    ]
    record = episode.processing_record
    assert record is not None
    assert record.recall is not None
    assert record.recall.outcome is RecallOutcome.NOTHING_FOUND
    second = record.recall_second_run
    assert second is not None
    assert second.outcome is RecallOutcome.FOUND
    assert second.cues == (RecallCue.UNDERSTOOD_MEANING,)
    assert {item.id for item in second.items} == {"activation:past", "said", "reported"}

    # Understanding ran once, and nothing the second run found reached it (§2:8).
    assert len(understanding.calls) == 1
    shown_to_understanding = " ".join(one.content for one in understanding.calls[0].messages)
    assert "Dr Rao" not in shown_to_understanding
    assert "Booked it for Friday." not in shown_to_understanding

    # Planning was shown the episode by its records and the user's fact, and never the
    # fact a source reported (§3:1, §3:3).
    request = completer.calls[0].messages[1].content
    # In band order: the user's fact is asserted, the episode observed.
    found_fact, found_episode = json.loads(request)["recalled"]
    assert found_episode["label"] == "E1"
    assert found_episode["rounds"] == [
        {"message": "Booked it for Friday.", "notes": "they prefer mornings"}
    ]
    assert found_fact["label"] == "M1"
    assert found_fact["fact"] == f"{_DENTIST} with Dr Rao"
    assert "moved to 3pm" not in request
    labels = {(one.label, one.id) for one in record.labels}
    assert {("E1", "activation:past"), ("M1", "said")} <= labels
    assert "reported" not in {one.id for one in record.labels}


async def test_a_failed_second_run_is_recorded_and_planning_goes_on() -> None:
    """ADR-0308 §2:7: failure-tolerant, recorded, and planning runs without its finds."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="I could not check."))
    harness, _ = await _recalling_harness(completer, _DownForTheReading(now=lambda: AT))
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when?")
    episode = await _settled(harness, conversation, seeded=frozenset({"activation:past"}))

    record = episode.processing_record
    assert record is not None
    assert record.recall_second_run is not None
    assert record.recall_second_run.outcome is RecallOutcome.FAILED
    assert _stages(episode)[4:6] == [
        (ControllerStage.RECALL, ControllerRule.UNDERSTOOD_NOT_RECALLED),
        (ControllerStage.PLANNING, ControllerRule.FIRST_ROUND_DUE),
    ]
    assert json.loads(completer.calls[0].messages[1].content)["recalled"] == []
    assert _said(await _messages(harness, conversation))[-1] == (
        MessageAuthor.ASSISTANT,
        "I could not check.",
    )


async def test_what_the_first_run_kept_is_passed_over_and_both_runs_reach_planning() -> None:
    """ADR-0308 §2:3, §3: the second run keeps nothing the first kept; planning sees both."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="Dr Rao, on Friday."))
    harness, understanding = await _recalling_harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "Rao")
    episode = await _settled(harness, conversation, seeded=frozenset({"activation:past"}))

    record = episode.processing_record
    assert record is not None
    assert record.recall is not None
    assert [item.id for item in record.recall.items] == ["said"]
    assert record.recall_second_run is not None
    assert {item.id for item in record.recall_second_run.items} == {
        "activation:past",
        "reported",
    }
    # Understanding was shown the first run's find, and only that (ADR-0281 §7).
    shown_to_understanding = " ".join(one.content for one in understanding.calls[0].messages)
    assert "Dr Rao" in shown_to_understanding
    assert "Booked it for Friday." not in shown_to_understanding
    recalled = json.loads(completer.calls[0].messages[1].content)["recalled"]
    assert [one["label"] for one in recalled] == ["M1", "E1"]
    assert recalled[0]["fact"] == f"{_DENTIST} with Dr Rao"


# --- one stage, apart from the controller ------------------------------------------------


_BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())


@dataclass(frozen=True)
class _Given:
    """A pass's working set as a phase stage reads it (``PhasePass``)."""

    deadline: float
    phases: PhaseWorking
    understanding: ActivationUnderstanding | None = None
    understanding_fetch: Fetched | None = None
    supply: TurnSupply = field(default_factory=lambda: _BOUNDED)
    windows: Windows | None = None
    recalled: Recalled | None = None


def _begun(path: PhasePath) -> PhaseWorking:
    return path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel("c1"), messages=()),
        conversation_id="c1",
        trigger_origin=InputOrigin.USER,
        owner_records=True,
    )


async def test_a_deadline_passing_inside_planning_is_the_classified_timeout() -> None:
    """ADR-0280 §5: a deadline met inside the round is a model timeout, not a fault."""
    completer = _GatedCompleter(RoundResponse(text="late"), gated=1)
    harness = _harness(completer)
    path = _phases(completer)(harness)
    given = _Given(deadline=asyncio.get_running_loop().time() + 0.05, phases=_begun(path))
    (planning,) = [one for one in path.stages() if one.name is ControllerStage.PLANNING]

    result = await planning.run(given)

    assert result.outcome is StageOutcome.TIMED_OUT
    assert isinstance(result.error, ModelTimeoutError)


async def test_a_fetched_record_resting_on_outside_content_reaches_the_first_ruling() -> None:
    """ADR-0181 §4, ADR-0306 §4:6: what understanding read is read before any round.

    The activation's own episode is clean and planning is shown no label for the
    recalled record, so only the fetched material says outside content was read.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "book", date="2026-10-12"),))
    )
    harness = _harness(completer)
    await harness.memory.add(_episode())
    path = _phases(completer)(harness)
    fetched = Fetched(
        episodes=None,
        recalled=(_episode("activation:other", derived_from_external=True),),
        fetched=("activation:other",),
        missing=(),
    )
    working = _begun(path)
    given = _Given(
        deadline=asyncio.get_running_loop().time() + _SETTLE,
        phases=working,
        understanding_fetch=fetched,
    )
    stages = {one.name: one for one in path.stages()}

    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE

    assert working.read_outside_content
    decided = working.latest.authorization
    assert decided is not None
    assert decided.read_outside_content


def _found(*episode_ids: str) -> Recalled:
    """A first-run decision keeping ``episode_ids``, as recall records one."""
    items = tuple(
        RecalledItem(
            kind=MemoryKind.EPISODIC,
            id=one,
            excerpt="an earlier episode",
            provenance=RecallProvenance.USER,
            standing=BeliefBand.DERIVED,
            rests_on_recorded_external_content=False,
            found_by=(RecallCue.ACTIVATION_INPUT,),
        )
        for one in episode_ids
    )
    return Recalled(
        ActivationRecall(
            outcome=RecallOutcome.FOUND, cues=(RecallCue.ACTIVATION_INPUT,), items=items
        ),
        scores=tuple(0.9 for _ in items),
    )


async def test_a_found_episode_with_marked_notes_counts_as_the_episode_windows_do() -> None:
    """ADR-0303 §3:6, ADR-0306 §4:5: what the activation read includes what recall found.

    The found episode is clean but for a note it marked, so only planning being shown
    it, under its label, says outside content was read; authorizing counts it from the
    label, as it counts an episode-window episode, and the round's notes are marked.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "book", date="2026-10-12"),), notes="a note")
    )
    harness = _harness(completer)
    await harness.memory.add(_episode())
    marked = PlanningRound(
        id="round:found", recorded_at=AT, notes="from a report", notes_marked=True
    )
    await harness.memory.add(_past_episode("activation:found", rounds=(marked,)))
    path = _phases(completer)(harness)
    working = _begun(path)
    given = _Given(
        deadline=asyncio.get_running_loop().time() + _SETTLE,
        phases=working,
        recalled=_found("activation:found"),
    )
    stages = {one.name: one for one in path.stages()}

    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE

    assert not working.fetched_outside
    assert working.latest.planned.round.notes_marked
    decided = working.latest.authorization
    assert decided is not None
    assert decided.read_outside_content
    assert working.found is not None
    assert working.found.fetched == ("activation:found",)


async def test_a_found_episodes_evidence_reaches_the_ruling_with_no_notes_written() -> None:
    """ADR-0308 §5:4-§5:5, ADR-0306 §4:5: evidence planning is shown is outside content read.

    The found episode's provenance is clean and its rounds carry no marked note; only
    its evidence is outside content, and the round writes no notes to carry a mark, so
    the working set alone says the activation has read it.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "book", date="2026-10-12"),))
    )
    harness = _harness(completer)
    await harness.memory.add(_episode())
    found = _past_episode("activation:found")
    assert found.processing_record is not None
    digest = ActivationDigest(
        result="R1",
        question="when is it",
        outcome=DigestOutcome.ANSWERED,
        evidence=(EvidenceItem(text="The appointment is Friday at 3pm.", source="R1"),),
        recorded_at=AT,
    )
    await harness.memory.add(
        found.model_copy(
            update={
                "processing_record": found.processing_record.model_copy(
                    update={"digests": (digest,)}
                )
            }
        )
    )
    path = _phases(completer)(harness)
    working = _begun(path)
    given = _Given(
        deadline=asyncio.get_running_loop().time() + _SETTLE,
        phases=working,
        recalled=_found("activation:found"),
    )
    stages = {one.name: one for one in path.stages()}

    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE

    assert working.latest.planned.round.notes is None
    assert working.fetched_outside
    decided = working.latest.authorization
    assert decided is not None
    assert decided.read_outside_content


async def test_planning_fetches_what_recall_found_once_for_every_round() -> None:
    """ADR-0282 §2:4-§2:7: one read before the first round, held for the rest."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(text="one"), RoundResponse(text="two")
    )
    harness = _harness(completer)
    await harness.memory.add(_past_episode("activation:found"))
    path = _phases(completer)(harness)
    working = _begun(path)
    given = _Given(
        deadline=asyncio.get_running_loop().time() + _SETTLE,
        phases=working,
        recalled=_found("activation:found", "activation:gone"),
    )
    (planning,) = [one for one in path.stages() if one.name is ControllerStage.PLANNING]

    assert (await planning.run(given)).outcome is StageOutcome.DONE
    held = working.found
    await harness.memory.delete("activation:found")
    assert (await planning.run(given)).outcome is StageOutcome.DONE

    assert working.found is held
    assert held is not None
    assert held.missing == ("activation:gone",)
    for call in completer.calls:
        (shown,) = json.loads(call.messages[1].content)["recalled"]
        assert shown["label"] == "E1"


async def test_a_digest_the_state_holds_marks_the_episode_though_the_working_set_lacks_it() -> None:
    """ADR-0308 §5:4: a digest recorded whose append was cancelled still counts.

    Its recorder added it to the state before the append that was cancelled, so the
    working set never had it; the freeze's facts read the state's digests too.
    """
    completer = FakeToolCallingCompleter.scripted()
    harness = _harness(completer)
    path = _phases(completer)(harness)
    working = _begun(path)
    working.messages.append("Hi.")
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)
    state = _admitted()
    answered = ActivationDigest(
        result="R1", question="when", outcome=DigestOutcome.ANSWERED, recorded_at=AT
    )

    async def controlled() -> None:
        state.recorded_digest(answered, ())

    await path.run(given, controlled, state=state)

    assert not working.read_outside_content
    assert state.facts is not None
    assert state.facts.derived_from_external


_UNKNOWN_BOOKING: Final = "the tool book may have run; whether it did is not known"


async def _ended_failing(harness: Harness, completer: FakeToolCallingCompleter) -> str:
    """End a pass on a stage's error, over the effect records already in the store."""
    conversation = await _conversation(harness)
    path = _phases(completer)(harness)
    working = path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel(conversation), messages=()),
        conversation_id=conversation,
        trigger_origin=InputOrigin.USER,
        owner_records=True,
    )
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)

    async def failing() -> None:
        msg = "a stage failed"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="a stage failed"):
        await path.run(given, failing, state=None)
    (*_, last) = await _messages(harness, conversation)
    return last.text


async def _claimed(harness: Harness, effect_id: str, capability: str, outcome: ToolOutcome) -> None:
    effect = ActivationEffect(
        id=effect_id,
        activation_id=_ACTIVATION,
        round="round:1",
        capability=capability,
        values_digest="0" * 64,
        decision_id=f"decision:{effect_id}",
        claimed_at=AT,
    )
    await harness.plans.claim_activation_effect(effect, match=None)
    await harness.plans.finish_activation_effect(effect_id, outcome)


async def test_couldnt_finish_lists_an_unknown_outcome_as_unknown() -> None:
    """ADR-0307 §3:4-§3:5: an unknown outcome is always reported, and never as done.

    Where no later round can report it, *couldn't finish* does.
    """
    completer = FakeToolCallingCompleter.scripted()
    harness = _harness(completer)
    await _claimed(harness, "e1", "remember", ToolOutcome.SUCCEEDED)
    await _claimed(harness, "e2", "book", ToolOutcome.INDETERMINATE)
    await _claimed(harness, "e3", "book", ToolOutcome.FAILED)

    written = await _ended_failing(harness, completer)

    assert written == couldnt_finish(("the tool remember ran", _UNKNOWN_BOOKING)).text


async def test_couldnt_finish_is_written_where_the_effect_records_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0293 §9:1: the fixed message is owed whatever the effect history's store says."""
    completer = FakeToolCallingCompleter.scripted()
    harness = _harness(completer)

    async def unreadable(activation_ids: Sequence[str], /) -> tuple[ActivationEffect, ...]:
        del activation_ids
        msg = "the plan store is down"
        raise PlanningError(msg)

    monkeypatch.setattr(harness.plans, "activation_effects", unreadable)

    assert await _ended_failing(harness, completer) == COULDNT_FINISH


# --- what wrote each message (ADR-0303 §7:1) ---------------------------------------------

_OLD_PATH: Final = "00000000-0000-4000-8000-0000000000d0"


async def _all_settled(harness: Harness, conversation: str, count: int) -> None:
    """Wait for ``count`` activations to end and their episodes to freeze."""
    deadline = asyncio.get_running_loop().time() + _SETTLE
    while True:
        state = await harness.engine.conversation(conversation)
        frozen = [
            one
            for one in await harness.memory.export()
            if isinstance(one, EpisodicMemory)
            and one.processing_record is not None
            and not one.processing_record.is_open
        ]
        if state is not None and not state.state.working and len(frozen) == count:
            return
        if asyncio.get_running_loop().time() > deadline:
            msg = "the activations never settled"
            raise AssertionError(msg)
        await asyncio.sleep(0.001)


async def test_a_later_activation_sees_what_an_earlier_one_wrote_under_its_episode() -> None:
    """ADR-0303 §7:1, §7:5, ADR-0306 §5:3, ADR-0307 §5:6.

    The phases' message links to the activation that wrote it, by its effect record,
    and is shown under that activation's episode label, as the message it took in is.
    A message the old path wrote has no effect record and stays not linkable.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(text="Hello!"), RoundResponse(text="Again.")
    )
    harness = _harness(completer)
    conversation = await _conversation(harness)
    store = harness.conversation_store
    # What the old path left: a message it took in, and the reply its adapter wrote.
    old = NewMessage(author=MessageAuthor.USER, text="old", device_id="phone", message_id="m-0")
    await store.append_message(conversation, old)
    await store.take_in(conversation, positions=[1], activation_id=_OLD_PATH)
    await store.append_message(
        conversation, NewMessage(author=MessageAuthor.ASSISTANT, text="Old reply.")
    )

    await _say(harness, conversation, "hi")
    first = await _settled(harness, conversation)
    again = UserMessage(device_id=_PHONE.device_id, message_id="m-2", text="again")
    await harness.engine.write_message(conversation, message=again)
    await _all_settled(harness, conversation, 2)

    shown = json.loads(completer.calls[1].messages[1].content)["place_window"]
    assert [one["text"] for one in shown] == ["old", "Old reply.", "hi", "Hello!", "again"]
    old_item, old_reply, taken, wrote, _input = shown
    assert "episode" in old_item
    assert "episode" not in old_reply
    assert taken["episode"] == wrote["episode"] != old_item["episode"]
    # The first activation's episode is the one its message's effect record names.
    (effect,) = await harness.plans.activation_effects([first.id.removeprefix("activation:")])
    assert effect.position == 4


async def test_the_writers_read_keeps_only_a_message_done_in_the_conversation() -> None:
    """ADR-0306 §5:5: only a message done carries its position, in its own place."""
    completer = FakeToolCallingCompleter.scripted()
    harness = _harness(completer)
    path = _phases(completer)(harness)

    async def claimed(effect: ActivationEffect, outcome: ToolOutcome, **finish: Any) -> None:
        await harness.plans.claim_activation_effect(effect, match=None)
        await harness.plans.finish_activation_effect(effect.id, outcome, **finish)

    def message(effect_id: str, place: str = "conversation:c1") -> ActivationEffect:
        return ActivationEffect(
            id=effect_id, activation_id=_ACTIVATION, round="round:1", place=place, claimed_at=AT
        )

    await claimed(message("e1"), ToolOutcome.SUCCEEDED, position=2)
    await claimed(message("e2", place="conversation:c2"), ToolOutcome.SUCCEEDED, position=3)
    await claimed(message("e3"), ToolOutcome.FAILED, reason="the place took no message")
    await claimed(message("e4"), ToolOutcome.SUCCEEDED, position=9)
    await _claimed(harness, "e5", "remember", ToolOutcome.SUCCEEDED)

    assert await path.written("c1", [_ACTIVATION], [2, 3, 5]) == {2: _ACTIVATION}
    assert await path.written("c1", [], [2]) == {}
    assert await path.written("c1", ["activation-unknown"], [2]) == {}


async def test_the_writers_read_links_nothing_where_the_records_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0303 §7:5: not linkable, the conservative direction; the window still comes."""
    completer = FakeToolCallingCompleter.scripted()
    harness = _harness(completer)
    path = _phases(completer)(harness)

    async def unreadable(activation_ids: Sequence[str], /) -> tuple[ActivationEffect, ...]:
        del activation_ids
        msg = "the plan store is down"
        raise PlanningError(msg)

    monkeypatch.setattr(harness.plans, "activation_effects", unreadable)

    assert await path.written("c1", [_ACTIVATION], [2]) == {}


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
    assert await _last_ended(harness, conversation) is ActivationEnding.DONE


def test_the_phases_are_wired_only_beside_understanding() -> None:
    with pytest.raises(ConfigurationError, match="only beside both"):
        Harness(planner=NoStepPlanner(), phases=_phases(FakeToolCallingCompleter()))
