"""The phases end to end through the engine, over fakes (ADR-0309 §2:6, §3, §4).

A message the chat's reader takes in runs ADR-0309 §3's table:
the conversation, the windows and understanding as today, then planning, authorizing,
acting with digesting beside it, and planning again where a call brought something.
The phases write the activation's messages into the conversation as it runs, and the
episode freezes with its rounds, labels, digests and messages.

The five cases are the brief's: a quick question in one round, a search digested and
answered in a second, a remember, a booking that comes back *needs you*, and a stop
mid-task.

An event ``receive`` admits runs the same table as one activation whose place takes no
message (ADR-0313 §4:3-§4:5): nothing is written for it, its result says only how it
ended, and one that cannot finish or is stopped returns that rather than raising.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import pytest
from channel_receiver_contract import event_input
from exchange_support import reported, shown_text
from story_support import episode
from structlog.testing import capture_logs
from structured_support import structured
from test_activation_state import _admitted
from test_authorizer import _ACTIVATION, _episode
from test_engine import AT, Harness
from test_planning import _episode as _past_episode
from test_planning import _recorded_trigger, _understanding
from understanding_support import (
    EXCERPT_CHARS,
    STATED_PROPOSAL,
    TextAsStructured,
    recall_stage,
    understanding_stage,
)

from ai_assistant.core.errors import (
    ConfigurationError,
    ConversationStoreError,
    MemoryStoreError,
    ModelError,
    ModelTimeoutError,
    OversizedValueError,
    PlanningError,
)
from ai_assistant.core.types import (
    ActivationDigest,
    ActivationEffect,
    ActivationEnding,
    ActivationRecall,
    ActivationStop,
    AskedCall,
    Attestation,
    BeliefBand,
    BoundAccount,
    CallOutcomeKind,
    CanonicalDestination,
    CapabilityEffect,
    CapabilityResult,
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    ChatDevice,
    ControllerRule,
    ControllerStage,
    CostBasis,
    DataTier,
    DestinationProtocol,
    DeviceAccess,
    DiagnosticKind,
    DiagnosticSource,
    DigestOutcome,
    EgressBinding,
    EpisodicMemory,
    EvidenceItem,
    Idempotency,
    InformationalEventResult,
    LabelKind,
    Memory,
    MemoryKind,
    MemorySource,
    MessageAuthor,
    NewMessage,
    PermissionOutcome,
    PermissionRuling,
    PlacementReach,
    PlacementSetter,
    PlanningLabel,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    ProposedCall,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    Reversibility,
    RiskLevel,
    RoundResponse,
    StageOutcome,
    StoryActor,
    StoryChange,
    StoryEffectState,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    StorySummaryDraft,
    StorySummaryLine,
    SupportHolder,
    TextChannelPayload,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    TranscriptMessage,
    UserMessage,
    band_of,
    parties_are_outside,
)
from ai_assistant.orchestration.acting import ActingStage, OwnRecordsByCapability
from ai_assistant.orchestration.authorizer import AuthorizingStage, Verdict
from ai_assistant.orchestration.chat import COULDNT_FINISH, ChatWriter, couldnt_finish
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.digesting import DIGESTING_PROMPT
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply, UnboundedAudienceSupply
from ai_assistant.orchestration.episode_lookups import EpisodeLookUpReads
from ai_assistant.orchestration.lookups import (
    LOOK_UP_CAPABILITIES,
    LOOK_UP_LABEL_ARGUMENTS,
    LOOK_UPS,
    LookUps,
    searched_ids,
)
from ai_assistant.orchestration.payloads import DEFAULT_MAX_PAYLOAD_BYTES
from ai_assistant.orchestration.phase_path import (
    EVENT_DESCRIPTION,
    MessageWriter,
    PhasePath,
    PhaseTools,
    PhaseWorking,
    StoryReads,
)
from ai_assistant.orchestration.planning import PLANNING_PROMPT, PlannedRound
from ai_assistant.orchestration.recall import Recalled
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE, CandidateCalls
from ai_assistant.orchestration.story_calls import (
    STORY_CALL_CAPABILITIES,
    STORY_CALLS,
    STORY_LABEL_ARGUMENTS,
    StoryCalls,
)
from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage
from ai_assistant.orchestration.story_tidy_up import STORY_TIDY_UP_PROMPT, StoryTidyUp
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    AskedIn,
    Fetched,
    TranscriptWindow,
    UnderstandingStage,
    WindowsStage,
    WrittenBy,
)
from ai_assistant.permissions.policy import (
    ConfiguredForecastDestination,
    ConfiguredSearchDestination,
    ThresholdActionPolicy,
)
from ai_assistant.testing import (
    FakeConversationStore,
    FakeDiagnosticSink,
    FakeEgressBinder,
    FakeForecaster,
    FakeMemoryStore,
    FakeModelProvider,
    FakeStoryStore,
    FakeToolCallingCompleter,
    FakeWebSearcher,
    default_prompt,
)
from ai_assistant.testing.forecasting import (
    DEFAULT_FORECAST_LATITUDE,
    DEFAULT_FORECAST_ORIGIN,
    DEFAULT_FORECAST_REPORTED_AT,
)
from ai_assistant.testing.memories import memory as memory_record
from ai_assistant.testing.memories import (
    remembered_support,
    said_support,
    sourced_support,
)
from ai_assistant.testing.parties import OWNERS_WORDS, UNIDENTIFIED_WORDS
from ai_assistant.testing.searching import DEFAULT_SEARCH_ORIGIN

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.protocols import ActionPolicy, EgressBinder
    from ai_assistant.core.types import (
        ActionRequest,
        ActivationUnderstanding,
        MemorySearchResult,
        Message,
        MessageReceipt,
        OfferedTool,
        PermissionDecision,
        PlanningExchange,
    )
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.story_links import Candidates
    from ai_assistant.orchestration.understanding import Windows

_PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)

#: How long a case waits for the reader to settle before it fails, rather than hangs.
_SETTLE: Final = 5.0

#: The connected account the fake searcher's origin is registered against.
_ACCOUNT: Final = BoundAccount(identity="search@example.com", reference="search-account")

#: What this deployment is configured with, as ADR-0247 §2 hands it to the policy: the
#: connection reference the search is registered against and the canonical destination
#: set its origin canonicalises to. Equal by construction to what the binder registers
#: for :data:`_ACCOUNT`, which is what makes a search here one *at the configured
#: provider* (§1).
_CONFIGURED_SEARCH: Final = ConfiguredSearchDestination(
    reference=_ACCOUNT.reference,
    destinations=frozenset(
        {
            CanonicalDestination(
                protocol=DestinationProtocol.HTTPS, canonical=f"{DEFAULT_SEARCH_ORIGIN}:443"
            )
        }
    ),
)

#: The keyless connection the fake forecaster's origin is registered against (ADR-0325).
_FORECAST_ACCOUNT: Final = BoundAccount(identity="Open-Meteo", reference="forecast-account")

#: The forecast destination this deployment is configured with (ADR-0260 §6), equal by
#: construction to what the binder registers for :data:`_FORECAST_ACCOUNT`.
_CONFIGURED_FORECAST: Final = ConfiguredForecastDestination(
    reference=_FORECAST_ACCOUNT.reference,
    destinations=frozenset(
        {
            CanonicalDestination(
                protocol=DestinationProtocol.HTTPS, canonical=f"{DEFAULT_FORECAST_ORIGIN}:443"
            )
        }
    ),
)

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
            _exchange: PlanningExchange, _tools: Sequence[OfferedTool]
        ) -> RoundResponse:
            return queue.pop(0)

        super().__init__(response=next_response)
        self._gated = gated
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        if len(self.calls) + 1 == self._gated:
            self.entered.set()
            await self.gate.wait()
        return await super().respond(exchange, tools, model=model)


def _phases(  # noqa: PLR0913 — one knob per seam a case varies
    completer: FakeToolCallingCompleter,
    *,
    digests: FakeModelProvider | None = None,
    searcher: FakeWebSearcher | None = None,
    forecaster: FakeForecaster | None = None,
    policy: ActionPolicy | None = None,
    binder: EgressBinder | None = None,
    registered_search: frozenset[str] = frozenset(),
    registered_forecast: frozenset[str] = frozenset(),
    writer: MessageWriter | None = None,
    wrap: Callable[[ChatWriter], MessageWriter] | None = None,
    recall_digest_wait: timedelta = timedelta(seconds=5),
    stories: FakeStoryStore | None = None,
    capabilities: Sequence[str] = _CAPABILITIES,
    tidy_up: Callable[[Harness], StoryTidyUp] | None = None,
    story_calls: bool = False,
    look_ups: bool = False,
    episode_look_ups: bool = False,
    diagnostics: FakeDiagnosticSink | None = None,
    path: type[PhasePath] = PhasePath,
    authorizing: type[AuthorizingStage] = AuthorizingStage,
) -> Callable[[Harness], PhasePath]:
    """The thin path as the composition root builds it, over the harness's own stores.

    ``stories`` wires the story views (ADR-0307 §6:1) over that story store, and
    ``capabilities`` names the capabilities planning is offered. ``story_calls`` offers
    planning's story calls too, over that store and the harness's memory store, with
    the tidy-up ``tidy_up`` builds, as the composition root wires them (ADR-0300 §10).
    ``look_ups`` offers planning's look-ups (ADR-0307 §6:6), over the harness's memory
    store and the story views' reads, as the composition root wires them, and with
    ``episode_look_ups`` the episode look-ups too (ADR-0358 §7-§10), over the harness's
    memory, story and conversation stores, every score kept. ``path`` and
    ``authorizing`` are the classes built, which a case may vary.
    """

    def build(harness: Harness) -> PhasePath:
        calls = (
            StoryCalls(
                stories=stories,
                memory=harness.memory,
                tidy_up=None if tidy_up is None else tidy_up(harness),
            )
            if story_calls and stories is not None
            else None
        )
        reads = (
            None
            if stories is None
            else StoryReads(
                stories=stories,
                memory=harness.memory,
                plans=harness.plans,
                short_views=StoryCandidates(
                    stories=stories, memory=harness.memory, limit=5, lines=3, notes=2, episodes=2
                ),
                episodes=3,
            )
        )
        episode_reads = (
            EpisodeLookUpReads(
                memory=harness.memory,
                stories=stories,
                conversations=harness.conversation_store,
                threshold=0.0,
                limit=6,
                search_page=3,
                history_page=10,
                full_page=20,
                excerpt_chars=500,
            )
            if episode_look_ups
            else None
        )
        looking = (
            LookUps(memory=harness.memory, views=reads, search_limit=5, episodes=episode_reads)
            if look_ups
            else None
        )
        tools = PhaseTools(
            registry=harness.invoker,
            invoker=harness.invoker,
            own_records=(
                REMEMBER_CANDIDATE,
                *(STORY_CALLS if calls is not None else ()),
                *(LOOK_UPS if looking is not None else ()),
            ),
            searcher=searcher,
            forecaster=forecaster,
            search_query="query",
        )
        # ADR-0329 §4:1: a candidate's lookup, over the same store.
        similar = LookUps(memory=harness.memory, views=reads, search_limit=5)
        chat = ChatWriter(
            conversations=harness.conversation_store, max_payload_bytes=DEFAULT_MAX_PAYLOAD_BYTES
        )
        place: MessageWriter = chat if wrap is None else wrap(chat)
        return path(
            planning_prompt=default_prompt(PLANNING_PROMPT),
            digesting_prompt=default_prompt(DIGESTING_PROMPT),
            completer=completer,
            provider=structured(
                digests if digests is not None else FakeModelProvider(reply=_DIGESTED)
            ),
            authorizing=authorizing(
                registry=tools,
                policy=policy if policy is not None else _Policy(),
                trail=harness.trail,
                stories=(
                    stories
                    if calls is not None and stories is not None
                    else FakeStoryStore(now=lambda: AT)
                ),
                memory=harness.memory,
                binder=binder,
                registered_search=registered_search,
                registered_forecast=registered_forecast,
                now=lambda: AT,
                diagnostics=diagnostics,
            ),
            acting=ActingStage(
                plans=harness.plans,
                invoker=tools,
                own_records=OwnRecordsByCapability(
                    {
                        "remember": CandidateCalls(similar=similar, limit=5),
                        **(
                            dict.fromkeys(STORY_CALL_CAPABILITIES, calls)
                            if calls is not None
                            else {}
                        ),
                        **(
                            dict.fromkeys(LOOK_UP_CAPABILITIES, looking)
                            if looking is not None
                            else {}
                        ),
                    }
                ),
                timeout=timedelta(seconds=5),
                now=lambda: AT,
            ),
            tools=tools,
            plans=harness.plans,
            writer=place if writer is None else writer,
            capabilities=(
                *capabilities,
                *(STORY_CALL_CAPABILITIES if calls is not None else ()),
                *(LOOK_UP_CAPABILITIES if looking is not None else ()),
            ),
            label_arguments={
                **(STORY_LABEL_ARGUMENTS if calls is not None else {}),
                **(LOOK_UP_LABEL_ARGUMENTS if looking is not None else {}),
            },
            story_calls=calls,
            look_ups=looking,
            round_limit=3,
            round_wait=timedelta(seconds=5),
            excerpt_chars=2000,
            part_chars=4000,
            memory=harness.memory,
            recall_cap=6,
            recall_digest_wait=recall_digest_wait,
            story_reads=reads,
            now=lambda: AT,
            diagnostics=diagnostics,
        )

    return build


def _harness(completer: FakeToolCallingCompleter, **knobs: Any) -> Harness:
    return Harness(
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


def _remember(call_id: str, fact: str) -> ProposedCall:
    """A ``remember`` recording a candidate resting on the input (ADR-0329 §3:1)."""
    return _call(call_id, "remember", fact=fact, why="worth keeping", rests_on_input=True)


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
    # Read outside content, so the episode says so; and the search returned records a
    # channel of unbounded audience withholds, so it is placed for the owner alone
    # (ADR-0309 §5:10).
    assert episode.provenance.derived_from_external
    assert episode.placement.reach is PlacementReach.OWNER
    assert episode.placement.set_by is PlacementSetter.DERIVED
    record = episode.processing_record
    assert record is not None
    (digest,) = record.digests
    assert digest.outcome is DigestOutcome.ANSWERED
    assert digest.question == "when it opens"
    assert [(one.text, one.source) for one in digest.evidence] == [("It opens at nine.", "R1")]
    assert [(one.label, one.kind) for one in record.labels] == [("R1", LabelKind.RESULT)]
    # The second round was shown the evidence under the result's label, never the
    # raw result: in the report on the first round's call (ADR-0356 §5:4).
    (shown_search,) = reported(completer.calls[1], 0)
    assert shown_search["evidence"][0]["digest_of"] == "R1"
    assert "Open daily" not in shown_text(completer.calls[1])
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
        policy=ThresholdActionPolicy(configured_search=_CONFIGURED_SEARCH),
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


async def test_a_forecast_pull_is_digested_under_the_hubs_attribution_then_answered() -> None:
    """ADR-0324 §5, §2:3-§2:4, §3, §9: the weather pull, end to end through the phases.

    Planning is offered the forecast read with no argument but the *looking for*; the hub
    fills the origin and the coordinate from the forecaster's proposal; the answer
    reaches planning only as a digest's evidence, the digest given the channel and the
    author as the hub's attribution; and the activation has read outside content.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "forecast_read", looking_for="rain tomorrow"),)),
        RoundResponse(text="No rain tomorrow."),
    )
    digests = FakeModelProvider(reply=_DIGESTED)
    forecaster = FakeForecaster()
    harness = _harness(
        completer,
        digests=digests,
        forecaster=forecaster,
        capabilities=(*_CAPABILITIES, "forecast_read"),
    )
    conversation = await _conversation(harness)

    await _say(harness, conversation, "will it rain tomorrow?")
    episode = await _settled(harness, conversation)

    assert _said(await _messages(harness, conversation))[-1] == (
        MessageAuthor.ASSISTANT,
        "No rain tomorrow.",
    )
    # Offered with none of its arguments: the place never crosses the planning seam.
    (offered,) = [one for one in completer.calls[0].tools if one.name == "forecast_read"]
    schema = offered.model_dump()["parameters"]
    assert set(schema["properties"]) == {"looking_for"}
    assert schema["required"] == ["looking_for"]
    # Sent to `Forecaster.read` with exactly the arguments its proposal names.
    (read,) = forecaster.read_calls
    proposal = await forecaster.request()
    assert proposal is not None
    assert read.request.parameters == proposal.parameters
    assert read.request.parameters["origin"] == DEFAULT_FORECAST_ORIGIN
    assert read.request.parameters["latitude"] == DEFAULT_FORECAST_LATITUDE
    # The digest read the forecast as quoted data under the hub's attribution.
    (digest_call,) = digests.calls
    document = json.loads(digest_call.messages[1].content)
    (record,) = document["records"]
    assert record["from"].startswith("outside content: the weather channel")
    assert '"fake forecast"' in record["from"]
    assert "a service, the forecast provider, claimed" in record["from"]
    assert DEFAULT_FORECAST_REPORTED_AT.isoformat() in record["from"]
    assert "2026-09-05" in record["text"]
    assert "2026-09-05" not in record["from"]
    # Planning saw evidence under the result's label, never the forecast itself.
    shown = shown_text(completer.calls[1])
    (forecast,) = reported(completer.calls[1], 0)
    assert forecast["evidence"][0]["digest_of"] == "R1"
    assert "2026-09-05" not in shown
    # The pull marks the activation (§9:1), and the records it returned were held by
    # it, so the episode is placed for the owner alone (ADR-0309 §5:10).
    assert episode.provenance.derived_from_external
    assert episode.placement.reach is PlacementReach.OWNER
    assert episode.placement.set_by is PlacementSetter.DERIVED
    assert episode.processing_record is not None
    (digest,) = episode.processing_record.digests
    assert digest.outcome is DigestOutcome.ANSWERED
    assert digest.question == "rain tomorrow"


async def test_without_a_forecaster_planning_is_not_offered_the_weather_pull() -> None:
    """ADR-0324 §5:4: offered only where a forecaster is configured."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="I can't check that."))
    harness = _harness(completer, capabilities=(*_CAPABILITIES, "forecast_read"))
    conversation = await _conversation(harness)

    await _say(harness, conversation, "will it rain tomorrow?")
    await _settled(harness, conversation)

    assert all(one.name != "forecast_read" for one in completer.calls[0].tools)


async def _configured_forecast_run(*, registered: bool) -> tuple[Harness, FakeForecaster, str]:
    """One forecast read and an answer, under the real policy over a configured forecast.

    The deployment's own ``ThresholdActionPolicy`` over its configured forecast provider,
    and a binding seam holding the forecast read against the keyless connection;
    ``registered`` is whether authorizing is told it is the deployment's forecast read.
    """
    # A free provider states its cost as zero (ADR-0344 §7:3), so the unknown-cost
    # floor does not bind (ADR-0236 §4).
    forecaster = FakeForecaster(cost_per_call=Decimal(0), cost_currency="USD")
    proposal = await forecaster.request()
    assert proposal is not None
    binder = FakeEgressBinder()
    binder.register_egress(
        proposal.tool,
        reference=_FORECAST_ACCOUNT.reference,
        identity=_FORECAST_ACCOUNT.identity,
    )
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "forecast_read", looking_for="rain"),)),
        RoundResponse(text="No rain."),
    )
    harness = _harness(
        completer,
        forecaster=forecaster,
        policy=ThresholdActionPolicy(configured_forecast=_CONFIGURED_FORECAST),
        binder=binder,
        registered_forecast=frozenset({str(proposal.tool.id)}) if registered else frozenset(),
        capabilities=(*_CAPABILITIES, "forecast_read"),
    )
    conversation = await _conversation(harness)
    await _say(harness, conversation, "will it rain?")
    await _settled(harness, conversation)
    return harness, forecaster, str(proposal.tool.id)


async def test_the_real_policy_allows_the_configured_forecast_with_no_grant() -> None:
    """ADR-0324 §5:7, ADR-0260 §6: checked as every call is, on its configured route.

    Authorizing writes ``forecast_reach`` for the deployment's forecast read, so the
    policy's configured-provider route allows it, and no grant is asked for.
    """
    harness, forecaster, forecast_id = await _configured_forecast_run(registered=True)

    assert len(forecaster.read_calls) == 1
    decisions = [one for one in await harness.trail.recent(limit=10) if one.tool.id == forecast_id]
    assert [one.ruling.outcome for one in decisions] == [PermissionOutcome.ALLOW]
    (binding,) = [one.egress_binding for one in decisions]
    assert isinstance(binding, EgressBinding)
    assert binding.forecast_reach
    assert not binding.closed_loop


async def test_without_the_registration_the_real_policy_does_not_run_the_forecast() -> None:
    """No ``forecast_reach``, so the configured route is never reached and nothing is sent."""
    harness, forecaster, forecast_id = await _configured_forecast_run(registered=False)

    assert forecaster.read_calls == []
    decisions = [one for one in await harness.trail.recent(limit=10) if one.tool.id == forecast_id]
    assert decisions
    assert all(one.ruling.outcome is not PermissionOutcome.ALLOW for one in decisions)


async def test_a_remember_records_a_candidate_through_the_assistants_own_records() -> None:
    """ADR-0306 §3:2-§3:3, ADR-0329 §3:3: claimed, run directly, and no memory is written.

    It brings another round (ADR-0315 §2:1); that round, with nothing new to say, writes
    no message (§4:2) and makes no call, so the activation ends after it.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            text="I'll remember that.",
            calls=(_remember("c1", "The user likes green tea."),),
        ),
        RoundResponse(),
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
    # A candidate is the call joined to its effect record; it writes no memory (§3:3).
    assert [one for one in await harness.memory.export() if isinstance(one, Memory)] == []
    # Done: a second round, shown it done, and then the end.
    assert episode.processing_record is not None
    assert len(episode.processing_record.rounds) == 2
    (call,) = reported(completer.calls[1], 0)
    assert call["outcome"] == "done"
    assert _stages(episode)[-2:] == [
        (ControllerStage.PLANNING, ControllerRule.ROUND_DUE),
        (ControllerStage.END, ControllerRule.NOTHING_DUE),
    ]


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
    # The second round was shown the call as needing the user. Until the glue hands
    # planning the request authorizing ruled on, it cannot be asked about (ADR-0321
    # §2:10).
    (call,) = reported(completer.calls[1], 0)
    assert call["outcome"].startswith("needs the user")
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
    assert state.state.activation_ids
    assert await harness.engine.stop_activation(state.state.activation_ids[-1]) is (
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
    # The round's message, then the *couldn't finish* an activation whose last message
    # did not come back done owes (ADR-0317 §3:4), which the place took no better.
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
    """ADR-0317 §3:1: *couldn't finish* lists the effects the records say happened.

    The remember beside the failing message finished, so it is listed, though the step
    it ran in ended ``failed``; the message's own record is finished unknown.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            text="I'll remember that.",
            calls=(_remember("c1", "The user likes green tea."),),
        )
    )
    harness = _harness(completer, wrap=_FailsOnce)
    conversation = await _conversation(harness)

    # The failed activation's log carries its traceback, whose rendering can outlast the
    # wait below on a loaded machine; captured, it is not rendered.
    with capture_logs():
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


async def test_the_round_limit_writes_couldnt_finish_after_earlier_messages() -> None:
    """ADR-0307 §3:7, §8:4: a loop of refused calls is ended by the round limit."""
    # Each round's call carries its own id: a work's exchange holds each id once
    # (ADR-0356 §13), as a provider mints them.
    refused = [RoundResponse(text="Trying.", calls=(_call(f"c{n}", "nowhere"),)) for n in (1, 2, 3)]
    completer = FakeToolCallingCompleter.scripted(*refused)
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
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        del exchange, tools, model
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
    """ADR-0317 §3:4: its last message did not come back done, and none came after it."""
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


def _remembered(memory_id: str, source: MemorySource, fact: str) -> Memory:
    """A memory in the band ``source`` names (ADR-0328 §12), dated ``AT``.

    ``EXTERNAL`` is a source support from the mail reader, which rests on outside
    content; ``USER_ASSERTED`` the user's own message; anything else a remember call.
    """
    match band_of(source):
        case BeliefBand.ASSERTED:
            support = said_support(when=AT, added_at=AT)
        case BeliefBand.ATTESTED:
            support = sourced_support(
                Attestation(reported_by="mail", reported_at=AT), when=AT, added_at=AT
            )
        case BeliefBand.DERIVED:
            support = remembered_support(when=AT, added_at=AT)
    return memory_record(memory_id, fact, support)


#: A digest that found nothing answering its question: an answer, with no evidence.
_NOTHING_DIGESTED: Final = json.dumps({"evidence": []})


async def _recalling_harness(
    completer: FakeToolCallingCompleter,
    memory: FakeMemoryStore | None = None,
    *,
    digests: FakeModelProvider | None = None,
    extra: Sequence[Memory] = (),
    reply: Mapping[str, object] | None = None,
) -> tuple[Harness, FakeModelProvider]:
    """A test hub with recall wired, its store holding what the second run finds.

    ``digests`` answers recall's digest of the outside fact the second run finds, and of
    any outside fact in ``extra``; by default it finds nothing answering. ``reply`` is
    understanding's, by default its reading alone.
    """
    store = memory if memory is not None else FakeMemoryStore(now=lambda: AT)
    noted = PlanningRound(
        id="round:past", recorded_at=AT, text="Booked it for Friday.", notes="they prefer mornings"
    )
    past = _past_episode("activation:past", rounds=(noted,)).model_copy(
        update={"content": f"{_DENTIST} booked for Friday"}
    )
    records: tuple[EpisodicMemory | Memory, ...] = (
        past,
        _remembered("said", MemorySource.USER_ASSERTED, f"{_DENTIST} with Dr Rao"),
        _remembered("reported", MemorySource.EXTERNAL, f"{_DENTIST} moved to 3pm"),
        *extra,
    )
    for record in records:
        await store.add(record)
    understanding = FakeModelProvider(
        reply=json.dumps(reply if reply is not None else {"understanding": _DENTIST})
    )
    harness = Harness(
        understanding=understanding_stage(model=understanding),
        tools=(_BOOK,),
        memory=store,
        windows=WindowsStage(episodes=_no_episode_window),
        recall=recall_stage(store),
        phases=_phases(
            completer,
            digests=digests if digests is not None else FakeModelProvider(reply=_NOTHING_DIGESTED),
        ),
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
        # The fact a source reported goes to recall's digest (ADR-0308 §4:4).
        (ControllerStage.DIGESTING, ControllerRule.RECALL_UNDIGESTED),
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
    request = completer.calls[0].exchange.briefing
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


class _Searched(FakeMemoryStore):
    """A store that keeps every query it was searched with, in order."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.queries: list[str] = []

    async def search(self, query: str, **kwargs: Any) -> MemorySearchResult:
        self.queries.append(query)
        return await super().search(query, **kwargs)


async def test_the_second_run_searches_the_meaning_then_each_unclear_points_gap() -> None:
    """ADR-0353 §14:3: the second run is cued by the meaning and each gap, in that order."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="It is on Friday."))
    store = _Searched(now=lambda: AT)
    reply = {
        "understanding": _DENTIST,
        "unclear": [
            {"gap": "which dentist", "readings": ["Dr Rao"]},
            {"gap": "which week", "readings": ["this week", "next week"]},
        ],
    }
    harness, _ = await _recalling_harness(completer, store, reply=reply)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when?")
    episode = await _settled(harness, conversation, seeded=frozenset({"activation:past"}))

    record = episode.processing_record
    assert record is not None
    second = record.recall_second_run
    assert second is not None
    assert second.cues == (RecallCue.UNDERSTOOD_MEANING, RecallCue.UNDERSTOOD_GAP)
    first_run = store.queries.index(_DENTIST)
    searched = list(dict.fromkeys(store.queries[first_run:]))
    assert searched == [_DENTIST, "which dentist", "which week"]


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
    assert json.loads(completer.calls[0].exchange.briefing)["recalled"] == []
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
    recalled = json.loads(completer.calls[0].exchange.briefing)["recalled"]
    assert [one["label"] for one in recalled] == ["M1", "E1"]
    assert recalled[0]["fact"] == f"{_DENTIST} with Dr Rao"


# --- ADR-0308 §4:4-§4:6, ADR-0309 §3's row 7: recall's digest -------------------------------

#: A fact a source reported that the input's own words find: the first run keeps it.
_RAO_CALLED: Final = _remembered("rao-call", MemorySource.EXTERNAL, "Rao office: bring a referral")
#: What recall's digest answers, by the local label of the second run's reported fact,
#: and an item naming a label the call never showed.
_RECALL_DIGESTED: Final = json.dumps(
    {
        "evidence": [
            {"text": "The appointment is at three now.", "source": "D2"},
            {"text": "Made up.", "source": "D7"},
        ]
    }
)


async def test_both_runs_outside_records_go_into_one_digest_answering_the_meaning() -> None:
    """ADR-0308 §4:4-§4:6, §4:15, §5: one digest, before the first round, read as evidence.

    The input's words keep the user's fact and one a source reported; understanding's
    reading keeps the past episode and another reported fact. Both reported facts go into
    one digest answering the meaning, after the second run and before planning, which is
    shown its evidence under the record's own label and never the facts themselves.
    """
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="Dr Rao, at three."))
    digests = FakeModelProvider(reply=_RECALL_DIGESTED)
    harness, understanding = await _recalling_harness(
        completer, digests=digests, extra=(_RAO_CALLED,)
    )
    conversation = await _conversation(harness)

    await _say(harness, conversation, "Rao")
    episode = await _settled(harness, conversation, seeded=frozenset({"activation:past"}))

    # Row 7 after the second run's row, once, and the first round waits for it (§4:6).
    assert _stages(episode)[4:7] == [
        (ControllerStage.RECALL, ControllerRule.UNDERSTOOD_NOT_RECALLED),
        (ControllerStage.DIGESTING, ControllerRule.RECALL_UNDIGESTED),
        (ControllerStage.PLANNING, ControllerRule.FIRST_ROUND_DUE),
    ]
    assert [stage for stage, _ in _stages(episode)].count(ControllerStage.DIGESTING) == 1
    record = episode.processing_record
    assert record is not None
    assert record.recall is not None
    assert [item.id for item in record.recall.items] == ["said", "rao-call"]

    # One call over both runs' outside records, the first run's first, answering the
    # meaning (§4:4), each attributed by the hub as outside content (§4:7).
    (call,) = digests.calls
    document = json.loads(call.messages[-1].content)
    assert document["question"] == _DENTIST
    assert [(one["label"], one["text"]) for one in document["records"]] == [
        ("D1", "Rao office: bring a referral"),
        ("D2", f"{_DENTIST} moved to 3pm"),
    ]
    assert all(one["from"].startswith("outside content") for one in document["records"])

    # Recorded as recall's digest; the item naming D7 is dropped (§4:14), and the kept
    # item's source is the record's own label (§4:15), taken as the item was recorded.
    assert record.digests == (
        ActivationDigest(
            result=None,
            question=_DENTIST,
            outcome=DigestOutcome.ANSWERED,
            evidence=(EvidenceItem(text="The appointment is at three now.", source="M1"),),
            recorded_at=AT,
        ),
    )
    labels = {one.id: one.label for one in record.labels}
    assert labels["reported"] == "M1"
    assert "rao-call" not in labels

    # Planning is shown the evidence as outside content under that label, and neither
    # reported fact (§3:3, §4:13, §5:5).
    request = completer.calls[0].exchange.briefing
    (shown,) = json.loads(request)["evidence"]
    assert shown["digest_of"] == "the outside memories recall found"
    (item,) = shown["digest"]["evidence"]
    assert (item["text"], item["source"]) == ("The appointment is at three now.", "M1")
    assert "outside_content" in item
    assert "moved to 3pm" not in request
    assert "referral" not in request
    assert [one["label"] for one in json.loads(request)["recalled"]] == ["M2", "E1"]

    # Reading it counts as having read digested evidence (§5:4): the round's notes are
    # marked, and the episode rests on outside content.
    (planning_round,) = record.rounds
    assert planning_round.notes_marked
    assert episode.provenance.derived_from_external
    assert len(understanding.calls) == 1


async def test_a_failed_recall_digest_tells_planning_it_could_not_read_and_shows_nothing() -> None:
    """ADR-0308 §4:11-§4:13: recorded with no evidence, tolerated, and planning goes on."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="It is on Friday."))
    digests = FakeModelProvider(reply="not json")
    harness, _ = await _recalling_harness(completer, digests=digests)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when?")
    episode = await _settled(harness, conversation, seeded=frozenset({"activation:past"}))

    record = episode.processing_record
    assert record is not None
    (digest,) = record.digests
    assert (digest.result, digest.outcome, digest.evidence) == (None, DigestOutcome.FAILED, ())
    digesting = [one for one in record.stages if one.stage is ControllerStage.DIGESTING]
    assert [(one.due, one.outcome) for one in digesting] == [
        (ControllerRule.RECALL_UNDIGESTED, StageOutcome.FAILED)
    ]
    request = completer.calls[0].exchange.briefing
    (shown,) = json.loads(request)["evidence"]
    assert shown["digest_of"] == "the outside memories recall found"
    assert shown["digest"].startswith("could not be read")
    assert "moved to 3pm" not in request
    assert "reported" not in {one.id for one in record.labels}
    assert _said(await _messages(harness, conversation))[-1] == (
        MessageAuthor.ASSISTANT,
        "It is on Friday.",
    )


async def test_no_recall_digest_is_due_where_neither_run_kept_an_outside_record() -> None:
    """§4:5: row 7 answers only where a run kept a memory record whose source is outside."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="Dr Rao."))
    digests = FakeModelProvider(reply=_RECALL_DIGESTED)
    store = FakeMemoryStore(now=lambda: AT)
    harness, _ = await _recalling_harness(completer, store, digests=digests)
    await store.delete("reported")
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when?")
    episode = await _settled(harness, conversation, seeded=frozenset({"activation:past"}))

    assert ControllerStage.DIGESTING not in {stage for stage, _ in _stages(episode)}
    assert digests.calls == []
    assert episode.processing_record is not None
    assert episode.processing_record.digests == ()


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
    story_candidates: Candidates | None = None


def _begun(path: PhasePath) -> PhaseWorking:
    return path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel("c1"), messages=()),
        conversation_id="c1",
        trigger=_recorded_trigger(),
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


class _SlowProvider(FakeModelProvider):
    """A digest provider that answers only after ``delay`` seconds."""

    def __init__(self, delay: float) -> None:
        super().__init__(reply=_NOTHING_DIGESTED)
        self._delay = delay

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        await asyncio.sleep(self._delay)
        return await super().complete(messages, model=model)


class _FetchFails(FakeMemoryStore):
    """A store whose fetch by id fails."""

    async def get_many(self, ids: Sequence[str]) -> dict[str, Any]:
        del ids
        msg = "the store is down"
        raise MemoryStoreError(msg)


@dataclass(frozen=True)
class _RecallDigest:
    """Recall's digest due on its own: the second run decided, one outside fact kept."""

    working: PhaseWorking
    given: _Given
    digesting: Any
    memory: FakeMemoryStore


async def _recall_digest(
    *,
    store: FakeMemoryStore | None = None,
    digests: FakeModelProvider | None = None,
    wait: timedelta = timedelta(seconds=5),
) -> _RecallDigest:
    completer = FakeToolCallingCompleter()
    memory = store if store is not None else FakeMemoryStore(now=lambda: AT)
    await memory.add(_remembered("reported", MemorySource.EXTERNAL, f"{_DENTIST} moved to 3pm"))
    harness = Harness(
        understanding=understanding_stage(),
        tools=(_BOOK,),
        memory=memory,
    )
    path = _phases(completer, digests=digests, recall_digest_wait=wait)(harness)
    working = _begun(path)
    working.second_recall = _found("activation:past")
    working.recall_outside = ("reported",)
    given = _Given(
        deadline=asyncio.get_running_loop().time() + _SETTLE,
        phases=working,
        understanding=_understanding(meaning=_DENTIST),
    )
    (digesting,) = [one for one in path.stages() if one.name is ControllerStage.DIGESTING]
    return _RecallDigest(working=working, given=given, digesting=digesting, memory=memory)


async def test_recall_digest_reads_the_held_ids_and_is_decided_once() -> None:
    """ADR-0308 §4:4, ADR-0282 §2:7: fetched by id, what came back held, and decided."""
    digests = FakeModelProvider(reply=_RECALL_DIGESTED.replace("D2", "D1"))
    case = await _recall_digest(digests=digests)
    working = case.working

    result = await case.digesting.run(case.given)

    assert result.outcome is StageOutcome.DONE
    assert working.recall_digested
    assert working.recall_digest_fetch is not None
    assert working.recall_digest_fetch.fetched == ("reported",)
    (digest,) = working.digests
    assert digest.result is None
    assert digest.evidence == (EvidenceItem(text="The appointment is at three now.", source="M1"),)
    (evidence,) = working.evidence
    assert evidence.result_id is None
    assert [(one.source_kind, one.source_id) for one in evidence.items] == [
        (LabelKind.MEMORY, "reported")
    ]
    # Reading it counts as having read digested evidence (§5:4), which authorizing's
    # working record carries as its digests.
    assert working.read_outside_content


async def test_a_recall_digest_whose_records_are_gone_reads_nothing_and_records_nothing() -> None:
    """ADR-0282 §2:6: an id with no record is not an error, and no call is made for none."""
    digests = FakeModelProvider(reply=_RECALL_DIGESTED)
    case = await _recall_digest(digests=digests)
    working = case.working
    working.recall_outside = ("forgotten",)

    result = await case.digesting.run(case.given)

    assert result.outcome is StageOutcome.DONE
    assert working.recall_digested
    assert working.recall_digest_fetch is not None
    assert working.recall_digest_fetch.missing == ("forgotten",)
    assert (working.digests, working.evidence, digests.calls) == ([], [], [])
    assert not working.read_outside_content


async def test_a_recall_record_no_longer_outside_is_not_digested() -> None:
    """§3:3: a record whose current version is not outside is shown by its fact instead."""
    digests = FakeModelProvider(reply=_RECALL_DIGESTED)
    case = await _recall_digest(digests=digests)
    await case.memory.add(_remembered("said", MemorySource.USER_ASSERTED, "the user's own"))
    case.working.recall_outside = ("said",)

    result = await case.digesting.run(case.given)

    assert result.outcome is StageOutcome.DONE
    assert case.working.recall_digested
    assert (case.working.digests, digests.calls) == ([], [])


async def test_a_recall_digest_whose_fetch_fails_is_recorded_failed_and_tolerated() -> None:
    """§4:12-§4:13: the records could not be read, so planning is told so and goes on."""
    digests = FakeModelProvider(reply=_RECALL_DIGESTED)
    case = await _recall_digest(store=_FetchFails(now=lambda: AT), digests=digests)
    working = case.working

    result = await case.digesting.run(case.given)

    assert (result.outcome, result.tolerated) == (StageOutcome.FAILED, True)
    assert working.recall_digested
    (digest,) = working.digests
    assert (digest.result, digest.outcome, digest.evidence) == (None, DigestOutcome.FAILED, ())
    (evidence,) = working.evidence
    assert (evidence.result_id, evidence.answered, evidence.items) == (None, False, ())
    assert digests.calls == []
    assert not working.read_outside_content


async def test_a_recall_digest_past_its_deadline_is_recorded_failed_and_timed_out() -> None:
    """§4:11: the deadline bounding recall's digest passing first fails it, tolerated."""
    case = await _recall_digest(
        digests=_SlowProvider(delay=_SETTLE), wait=timedelta(milliseconds=50)
    )

    result = await case.digesting.run(case.given)

    assert (result.outcome, result.tolerated) == (StageOutcome.TIMED_OUT, True)
    assert isinstance(result.error, ModelTimeoutError)
    (digest,) = case.working.digests
    assert digest.outcome is DigestOutcome.FAILED
    assert case.working.recall_digested


async def test_once_recall_digest_is_decided_digesting_reads_the_rounds_results() -> None:
    """ADR-0309 §3:3: the one digesting stage runs a round's digests once recall's is done."""
    case = await _recall_digest()
    case.working.recall_digest_decided = True
    case.working.planned(
        PlannedRound(round=PlanningRound(id="r1", recorded_at=AT), labels=(), recorded=True)
    )
    case.working.step(AT, timedelta(seconds=5)).held.put_nowait(None)

    result = await case.digesting.run(case.given)

    assert result.outcome is StageOutcome.DONE
    assert case.working.digests == []
    assert case.working.recall_digest_fetch is None


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
        RoundResponse(calls=(_call("c1", "book", date="2026-10-12"),), text="a note")
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
        (shown,) = json.loads(call.exchange.briefing)["recalled"]
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
        trigger=_recorded_trigger(),
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
    """ADR-0317 §3:1: the fixed message is owed whatever the effect history's store says."""
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

    shown = json.loads(completer.calls[1].exchange.briefing)["place_window"]
    assert [one["text"] for one in shown] == ["old", "Old reply.", "hi", "Hello!", "again"]
    old_item, old_reply, taken, wrote, _input = shown
    assert "episode" in old_item
    assert "episode" not in old_reply
    assert taken["episode"] == wrote["episode"] != old_item["episode"]
    # The first activation's episode is the one its message's effect record names.
    (effect,) = await harness.plans.activation_effects([first.id.removeprefix("activation:")])
    assert effect.position == 4


async def test_planning_is_shown_an_earlier_exchange_once_with_its_notes() -> None:
    """ADR-0276 §3, read with ADR-0307 §5:6 and §6:1 (#2951), end to end.

    The second message's planning is shown the first exchange as its two messages in
    the place window, under the first activation's episode label, and that episode in
    the episode window by its label and its notes, its texts said to be in the window.
    The round's notes are its text (ADR-0356 §7:2), so they repeat the message's words.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(text="Hello!"),
        RoundResponse(text="Again."),
    )
    harness = _harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "hi")
    await _settled(harness, conversation)
    again = UserMessage(device_id=_PHONE.device_id, message_id="m-2", text="again")
    await harness.engine.write_message(conversation, message=again)
    await _all_settled(harness, conversation, 2)

    rendered = completer.calls[1].exchange.briefing
    sent = json.loads(rendered)
    taken, wrote, _input = sent["place_window"]
    assert (taken["text"], wrote["text"]) == ("hi", "Hello!")
    (episode,) = sent["episode_window"]
    assert taken["episode"] == wrote["episode"] == episode["label"]
    in_place = "shown in the place window under this label, not repeated here"
    assert (episode["input"], episode["response"]) == (in_place, in_place)
    assert episode["rounds"] == [{"message": in_place, "notes": "Hello!"}]
    # Once as the place window's message, and once as the round's notes, which are its
    # text (ADR-0356 §7:2): the episode window never repeats the message itself.
    assert rendered.count('"Hello!"') == 2


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

    assert await path.written("c1", [_ACTIVATION], [2, 3, 5]) == {
        2: WrittenBy(activation_id=_ACTIVATION, round="round:1")
    }
    assert await path.written("c1", [], [2]) == {}
    assert await path.written("c1", ["activation-unknown"], [2]) == {}


async def test_the_writers_read_marks_a_question_by_its_own_activations_round() -> None:
    """ADR-0322 §4:1-§4:3: a round's id names it only within its activation.

    Two activations each wrote a message from a round of one id. Only B's round asked,
    so only B's message is a question, with the parts B's episode's projection marks.
    """
    completer = FakeToolCallingCompleter.scripted()
    harness = _harness(completer)
    path = _phases(completer)(harness)
    asked = tuple(AskedCall(part=part, tool=_BOOK, values={"date": "Friday"}) for part in (1, 2))
    rounds = {
        "act-a": PlanningRound(id="round:1", recorded_at=AT, text="Looking into it."),
        "act-b": PlanningRound(id="round:1", recorded_at=AT, text="Shall I?", asked=asked),
    }
    for position, (activation_id, planned) in enumerate(rounds.items(), start=2):
        stored = episode(activation_id)
        processing = stored.processing_record
        assert processing is not None
        await harness.memory.add(
            stored.model_copy(
                update={"processing_record": processing.model_copy(update={"rounds": (planned,)})}
            )
        )
        effect = ActivationEffect(
            id=f"e-{activation_id}",
            activation_id=activation_id,
            round="round:1",
            place="conversation:c1",
            claimed_at=AT,
        )
        await harness.plans.claim_activation_effect(effect, match=None)
        await harness.plans.finish_activation_effect(
            effect.id, ToolOutcome.SUCCEEDED, position=position
        )

    assert await path.written("c1", ["act-a", "act-b"], [2, 3]) == {
        2: WrittenBy(activation_id="act-a", round="round:1"),
        3: WrittenBy(
            activation_id="act-b",
            asked=AskedIn(round="round:1", parts=(1, 2)),
            round="round:1",
        ),
    }


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


# --- the story views (ADR-0307 §6:1, §6:3-§6:4) -------------------------------------------


async def _story_harness(
    completer: FakeToolCallingCompleter, *, outside: bool = False
) -> tuple[Harness, FakeStoryStore, str]:
    """A test hub with the stories wired, an earlier activation in a story with a summary.

    The earlier episode is in the episode window, so its story is understanding's one
    candidate, ``S1``, and understanding links the activation into it. The story holds a
    note written since its summary, and a booking the earlier activation made.
    """
    stories = FakeStoryStore(now=lambda: AT)
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(_past_episode("activation:past"))
    trip = (
        await stories.create(
            [StoryMember(kind=StoryMemberKind.ACTIVATION, id="past")], actor=StoryActor.OWNER
        )
    ).story_id
    assert trip is not None
    state = await stories.current_summary(trip)
    assert state is not None
    await stories.write_summary(
        trip,
        StorySummaryDraft(
            lines=(StorySummaryLine(text="A camping trip to Riverside."),),
            took_in_episodes=state.pending_episodes,
            outside=outside,
        ),
        as_of=state.as_of,
    )
    await stories.append_note(trip, "Next: check the dog policy.", author=StoryNoteAuthor.OWNER)
    understanding = FakeModelProvider(
        reply=json.dumps({"understanding": "the user asks about the trip"} | {"belongs_to": ["S1"]})
    )
    harness = Harness(
        understanding=understanding_stage(model=understanding),
        tools=(_BOOK,),
        memory=memory,
        stories=stories,
        story_candidates=StoryCandidates(
            stories=stories, memory=memory, limit=5, lines=3, notes=2, episodes=2
        ),
        story_links=StoryLinksStage(stories=stories),
        phases=_phases(completer, stories=stories),
    )
    effect = ActivationEffect(
        id="effect:past",
        activation_id="past",
        round="round:past",
        capability="book",
        values_digest="0" * 64,
        decision_id="decision:past",
        claimed_at=AT,
    )
    await harness.plans.claim_activation_effect(effect, match=None)
    await harness.plans.finish_activation_effect("effect:past", ToolOutcome.SUCCEEDED)
    return harness, stories, trip


async def test_an_activation_in_a_story_is_shown_its_story_and_labels_what_it_saw() -> None:
    """ADR-0307 §6:1, §5: B4b's path with the activation linked into a story.

    Understanding links the activation into the earlier activation's story; planning is
    then shown that story's summary, the note newer than it, when it was tidied and the
    count, where its matter stands with the booking done, and its latest episode, each
    under a label recorded with the episode.
    """
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="It is at Riverside."))
    harness, stories, trip = await _story_harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "where is the trip?")
    episode = await _settled(harness, conversation, seeded=frozenset({"activation:past"}))

    record = episode.processing_record
    assert record is not None
    assert (ControllerStage.STORY_LINKS, ControllerRule.STORY_LINKS_UNRECORDED) in _stages(episode)
    linked = StoryMember(kind=StoryMemberKind.ACTIVATION, id=record.activation_id)
    assert [one.story_id for one in await stories.stories_of(linked)] == [trip]

    request = json.loads(completer.calls[0].exchange.briefing)
    (shown,) = request["stories"]
    labels = {one.label: (one.kind, one.id) for one in record.labels}
    assert labels[shown["label"]] == (LabelKind.STORY, trip)
    assert shown["summary"] == ["A camping trip to Riverside."]
    assert shown["last_tidied"] == AT.isoformat()
    # The note, and this activation, linked since the summary was written.
    assert shown["changes_since_tidied"] == 2
    (note,) = shown["notes_since_tidied"]
    assert note["text"] == "Next: check the dog policy."
    assert labels[note["label"]][0] is LabelKind.NOTE
    (done,) = shown["where_it_stands"]["done"]
    assert done["state"] == "done"
    assert labels[done["episode"]] == (LabelKind.EPISODE, "activation:past")
    (latest,) = shown["latest_episodes"]
    assert latest["label"] == done["episode"]
    # Nothing of the story was outside content, so the round read none.
    assert not record.rounds[0].notes_marked


async def test_a_marked_story_summary_reaches_the_first_ruling() -> None:
    """ADR-0303 §3:6, ADR-0306 §4:5-§4:6: a marked summary is outside content read.

    The activation's own episode is clean, and a summary carries no label authorizing
    could look up, so only the working set says outside content was read: it reaches
    the first round's ruling.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "book", date="2026-10-12"),))
    )
    harness = _harness(completer)
    await harness.memory.add(_episode())
    stories = FakeStoryStore(now=lambda: AT)
    trip = (
        await stories.create(
            [StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)],
            actor=StoryActor.OWNER,
        )
    ).story_id
    assert trip is not None
    state = await stories.current_summary(trip)
    assert state is not None
    await stories.write_summary(
        trip,
        StorySummaryDraft(lines=(StorySummaryLine(text="A reply came."),), outside=True),
        as_of=state.as_of,
    )
    path = _phases(completer, stories=stories)(harness)
    working = _begun(path)
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)
    stages = {one.name: one for one in path.stages()}

    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE

    request = json.loads(completer.calls[0].exchange.briefing)
    assert request["stories"][0]["summary"] == ["A reply came."]
    assert working.fetched_outside
    decided = working.latest.authorization
    assert decided is not None
    assert decided.read_outside_content


async def test_an_outside_episode_of_an_inherited_story_is_outside_content_read() -> None:
    """ADR-0303 §3:1-§3:2: an episode whose input came from outside, shown in a story view.

    Its provenance carries no mark and it holds no digest; only its origin says it rests
    on outside content, and the working set counts it before the first round.
    """
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="ok"))
    harness = _harness(completer)
    await harness.memory.add(_episode())
    await harness.memory.add(_past_episode("activation:report", parties=UNIDENTIFIED_WORDS))
    stories = FakeStoryStore(now=lambda: AT)
    trip = (
        await stories.create(
            [StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)], actor=StoryActor.OWNER
        )
    ).story_id
    assert trip is not None
    await stories.create(
        [
            StoryMember(kind=StoryMemberKind.ACTIVATION, id="report"),
            StoryMember(kind=StoryMemberKind.STORY, id=trip),
        ],
        actor=StoryActor.OWNER,
    )
    path = _phases(completer, stories=stories)(harness)
    working = _begun(path)
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)
    (planning,) = [one for one in path.stages() if one.name is ControllerStage.PLANNING]

    assert (await planning.run(given)).outcome is StageOutcome.DONE

    (shown,) = json.loads(completer.calls[0].exchange.briefing)["stories"]
    (parent,) = shown["part_of"]
    assert parent["latest_episodes"][0]["input"] == "an outside report, not shown"
    assert working.fetched_outside
    assert working.latest.planned.round.notes_marked


async def test_a_later_round_is_handed_the_story_views_its_work_was_first_shown() -> None:
    """ADR-0356 §5:2, §5:6: a later round is handed the first round's briefing, byte for byte.

    It once re-rendered the stories as they stood for each round (ADR-0307 §6:1); a work's
    exchange is appended to and never re-rendered, so a note written meanwhile by someone
    else is not in the second round's request.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(text="one", calls=(_call("c1", "remember", fact="likes lakes"),)),
        RoundResponse(text="two"),
    )
    harness = _harness(completer)
    await harness.memory.add(_episode())
    stories = FakeStoryStore(now=lambda: AT)
    trip = (
        await stories.create(
            [StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)],
            actor=StoryActor.OWNER,
        )
    ).story_id
    assert trip is not None
    path = _phases(completer, stories=stories)(harness)
    working = _begun(path)
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)
    stages = {one.name: one for one in path.stages()}

    assert (await stages[ControllerStage.PLANNING].run(given)).outcome is StageOutcome.DONE
    await stories.append_note(trip, "Written meanwhile.", author=StoryNoteAuthor.OWNER)
    assert (await stages[ControllerStage.PLANNING].run(given)).outcome is StageOutcome.DONE

    first, second = completer.calls
    assert json.loads(first.exchange.briefing)["stories"][0]["notes_since_tidied"] == "none"
    assert second.exchange.briefing == first.exchange.briefing
    assert "Written meanwhile." not in shown_text(second)


# --- what counts as outside content read, under the real policy (#2875, #2876) ----------

#: A read that leaves the hub and changes nothing, which the real policy allows where the
#: activation has read no outside content, and which the stand-in otherwise sends to the
#: user (ADR-0306 §4:4).
_LOOKUP: Final = ToolDefinition(
    id="lookup",
    capability="lookup",
    description="Look up the weather for a place.",
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=False,
    reads=(),
    writes=(),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NATURAL,
    effect=CapabilityEffect.NONE,
    leaves_hub=True,
    result=CapabilityResult.NO_OUTSIDE_TEXT,
    outcome_can_be_unknown=False,
    safe_to_repeat=True,
    parameters_schema={
        "type": "object",
        "properties": {"place": {"type": "string"}},
        "required": ["place"],
        "additionalProperties": False,
    },
)


def _real_policy() -> ThresholdActionPolicy:
    """The deployment's own policy, as B4b's end-to-end case builds it."""
    return ThresholdActionPolicy(configured_search=_CONFIGURED_SEARCH)


async def _planned_and_authorized(
    completer: FakeToolCallingCompleter,
    *,
    memory: FakeMemoryStore,
    stories: FakeStoryStore | None = None,
    understanding_fetch: Fetched | None = None,
    recalled: Recalled | None = None,
) -> PhaseWorking:
    """One round planned and authorized under the real policy, the lookup offered."""
    harness = Harness(
        understanding=understanding_stage(),
        tools=(_BOOK, _LOOKUP),
        memory=memory,
    )
    await memory.add(_episode())
    path = _phases(
        completer,
        policy=_real_policy(),
        stories=stories,
        capabilities=(*_CAPABILITIES, "lookup"),
    )(harness)
    working = _begun(path)
    given = _Given(
        deadline=asyncio.get_running_loop().time() + _SETTLE,
        phases=working,
        understanding_fetch=understanding_fetch,
        recalled=recalled,
    )
    stages = {one.name: one for one in path.stages()}
    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE
    return working


def _look_and_remember() -> FakeToolCallingCompleter:
    return FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call("c1", "lookup", place="Riverside"),
                _remember("c2", "The user prefers the morning."),
            ),
            text="checking the weather",
        )
    )


@pytest.mark.parametrize(
    ("note", "verdict"),
    [
        pytest.param(None, Verdict.ALLOWED, id="no-note"),
        pytest.param(StoryNoteAuthor.OWNER, Verdict.ALLOWED, id="the-owners-unmarked-note"),
        pytest.param(StoryNoteAuthor.PLANNING, Verdict.NEEDS_YOU, id="a-marked-note"),
    ],
)
async def test_a_story_note_counts_as_outside_content_by_its_mark(
    note: StoryNoteAuthor | None, verdict: Verdict
) -> None:
    """#2875, ADR-0306 §4:5, ADR-0303 §3:1: a marked note is read; the owner's is not.

    An activation shown only the owner's note has a call that leaves the hub allowed
    exactly as without the note, and records its candidate unmarked (ADR-0106 §1); one
    shown a marked note has the call come back *needs you*, and the candidate, which
    passes no ``MemoryPolicy`` (ADR-0329 §5:6), recorded marked.
    """
    stories = FakeStoryStore(now=lambda: AT)
    trip = (
        await stories.create(
            [StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)],
            actor=StoryActor.OWNER,
        )
    ).story_id
    assert trip is not None
    if note is StoryNoteAuthor.OWNER:
        await stories.append_note(trip, "I prefer the morning.", author=note)
    elif note is StoryNoteAuthor.PLANNING:
        await stories.append_note(
            trip, "The email said it moved.", author=note, written_during="past", outside=True
        )
    completer = _look_and_remember()

    working = await _planned_and_authorized(
        completer, memory=FakeMemoryStore(now=lambda: AT), stories=stories
    )

    shown = json.loads(completer.calls[0].exchange.briefing)["stories"][0]
    if note is not None:
        # Shown under its label, which authorizing reads the mark of.
        (shown_note,) = shown["notes_since_tidied"]
        assert shown_note["label"] == "N1"
    decided = working.latest.authorization
    assert decided is not None
    assert [one.verdict for one in decided.verdicts] == [verdict, Verdict.ALLOWED]
    marked = verdict is Verdict.NEEDS_YOU
    assert decided.read_outside_content is marked
    assert working.latest.planned.round.notes_marked is marked
    remembered = decided.allowed[-1]
    assert remembered.call.request.parameters["rests_on_outside_content"] is marked


def _from_outside(episode_id: str) -> EpisodicMemory:
    """A frozen episode whose input came from outside, its provenance unmarked (#2876)."""
    record = _past_episode(episode_id, parties=UNIDENTIFIED_WORDS)
    assert not record.provenance.derived_from_external
    return record


async def test_an_outside_episode_in_the_episode_window_marks_the_rounds_notes() -> None:
    """#2876, ADR-0303 §3:2, ADR-0307 §4:3: the notes are marked, and authorizing agrees."""
    report = _from_outside("activation:report")
    working = await _planned_and_authorized(
        _look_and_remember(),
        memory=FakeMemoryStore(now=lambda: AT),
        understanding_fetch=Fetched(episodes=(report,), recalled=(), fetched=(), missing=()),
    )

    assert working.fetched_outside
    assert working.latest.planned.round.notes_marked
    decided = working.latest.authorization
    assert decided is not None
    assert decided.read_outside_content
    assert [one.verdict for one in decided.verdicts] == [Verdict.NEEDS_YOU, Verdict.ALLOWED]
    (remembered,) = decided.allowed
    assert remembered.call.request.parameters["rests_on_outside_content"] is True


async def test_an_outside_episode_recall_found_marks_the_rounds_notes() -> None:
    """#2876: recall's found episodes are counted as the episode window's are."""
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(_from_outside("activation:report"))
    working = await _planned_and_authorized(
        _look_and_remember(), memory=memory, recalled=_found("activation:report")
    )

    assert working.found is not None
    assert working.found.fetched == ("activation:report",)
    assert working.fetched_outside
    assert working.latest.planned.round.notes_marked
    decided = working.latest.authorization
    assert decided is not None
    assert decided.read_outside_content
    assert [one.verdict for one in decided.verdicts] == [Verdict.NEEDS_YOU, Verdict.ALLOWED]
    (remembered,) = decided.allowed
    assert remembered.call.request.parameters["rests_on_outside_content"] is True


# --- planning's story calls that write (ADR-0300 §10, ADR-0303 §9) ---------------------


class _GatedTidyUp(FakeModelProvider):
    """A tidy-up's provider whose one completion answers only once its gate opens."""

    def __init__(self) -> None:
        super().__init__(reply=json.dumps({"lines": ["A camping trip to Riverside."]}))
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        self.entered.set()
        await self.gate.wait()
        return await super().complete(messages, model=model)


def _tidy_up(
    stories: FakeStoryStore, provider: FakeModelProvider
) -> Callable[[Harness], StoryTidyUp]:
    def build(harness: Harness) -> StoryTidyUp:
        return StoryTidyUp(
            model=structured(provider),
            stories=stories,
            memory=harness.memory,
            excerpt_chars=200,
            other_stories=0,
            decisions=0,
            budget=timedelta(seconds=_SETTLE),
            threshold=0.0,
            prompt=default_prompt(STORY_TIDY_UP_PROMPT),
        )

    return build


async def _the_story(stories: FakeStoryStore, activation_id: str) -> str:
    """The one story ``activation_id`` belongs to."""
    member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)
    (header,) = await stories.stories_of(member)
    return str(header.story_id)


_STARTED: Final = RoundResponse(
    text="I'll keep track of the trip.",
    calls=(_call("c1", "start_story", notes=["A camping trip to Riverside."]),),
)


async def test_a_story_is_started_and_then_noted_end_to_end() -> None:
    """ADR-0300 §10:2-§10:3, ADR-0303 §9:3: a start, then a note on it by its label.

    The start holds this activation and its first note, under an effect record since it
    is not safe to repeat (ADR-0306 §5:3); the next round is shown the new story under
    ``S1`` and notes on it, and the note is planning's, written during this activation
    and unmarked, since nothing it read was outside content.

    The two steps complete with nothing asked for (ADR-0315 §2:1): the start brings the
    round that notes on the story, and the note brings a third, which has nothing to say
    or do, so the activation ends after it.
    """
    completer = FakeToolCallingCompleter.scripted(
        _STARTED,
        RoundResponse(
            calls=(
                _call("c2", "note_story", story="S1", note="Waiting on the campground's reply."),
            )
        ),
        RoundResponse(),
    )
    stories = FakeStoryStore(now=lambda: AT)
    harness = _harness(completer, stories=stories, story_calls=True)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "help me plan a camping trip to Riverside")
    episode = await _settled(harness, conversation)

    record = episode.processing_record
    assert record is not None
    activation = record.activation_id
    story = await _the_story(stories, activation)
    page = await stories.notes(story)
    assert page is not None
    assert [(one.text, one.author, one.written_during, one.outside) for one in page.notes] == [
        ("A camping trip to Riverside.", StoryNoteAuthor.PLANNING, activation, False),
        ("Waiting on the campground's reply.", StoryNoteAuthor.PLANNING, activation, False),
    ]
    # The second round was shown the new story under the label it then named, in the
    # start's result (ADR-0356 §5:4).
    (started,) = reported(completer.calls[1], 0)
    (shown,) = started["stories"]
    assert shown["label"] == "S1"
    assert [one["text"] for one in shown["notes_since_tidied"]] == ["A camping trip to Riverside."]
    assert (LabelKind.STORY, story) in {(one.kind, one.id) for one in record.labels}
    # The start is claimed under an effect record; the note, safe to repeat, is not.
    effects = await harness.plans.activation_effects([activation])
    assert [(one.capability, one.outcome) for one in effects if one.capability] == [
        ("start_story", ToolOutcome.SUCCEEDED)
    ]
    assert _stages(episode)[-5:] == [
        (ControllerStage.PLANNING, ControllerRule.ROUND_DUE),
        (ControllerStage.AUTHORIZING, ControllerRule.ROUND_UNAUTHORIZED),
        (ControllerStage.ACTING, ControllerRule.ROUND_AUTHORIZED),
        (ControllerStage.PLANNING, ControllerRule.ROUND_DUE),
        (ControllerStage.END, ControllerRule.NOTHING_DUE),
    ]
    assert len(record.rounds) == 3
    assert _said(await _messages(harness, conversation))[1:] == [
        (MessageAuthor.ASSISTANT, "I'll keep track of the trip.")
    ]


async def test_a_tidy_up_brings_no_round_and_nothing_waits_for_it() -> None:
    """ADR-0307 §7, §8:1, ADR-0306 §3:3: neither a next round nor the activation's end
    waits for a tidy-up, and it runs to its end after the activation has ended.

    The second round's only call tidies the story just started, and asks for no round,
    so the activation ends after it while the tidy-up's completion is still held. Once
    released, the tidy-up writes the story's version log, and the episode records none
    of it (§7:1).
    """
    provider = _GatedTidyUp()
    completer = FakeToolCallingCompleter.scripted(
        _STARTED, RoundResponse(calls=(_call("c2", "tidy_story", story="S1"),))
    )
    stories = FakeStoryStore(now=lambda: AT)
    harness = _harness(
        completer, stories=stories, story_calls=True, tidy_up=_tidy_up(stories, provider)
    )
    conversation = await _conversation(harness)

    await _say(harness, conversation, "help me plan a camping trip to Riverside")
    episode = await _settled(harness, conversation)
    await asyncio.wait_for(provider.entered.wait(), _SETTLE)

    record = episode.processing_record
    assert record is not None
    story = await _the_story(stories, record.activation_id)
    # Ended with the tidy-up still out: two rounds, and no third.
    assert len(completer.calls) == 2
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.NOTHING_DUE)
    assert not provider.gate.is_set()
    held = await stories.current_summary(story)
    assert held is not None
    assert held.summary is None

    provider.gate.set()
    deadline = asyncio.get_running_loop().time() + _SETTLE
    while (state := await stories.current_summary(story)) is None or state.summary is None:
        assert asyncio.get_running_loop().time() < deadline, "the tidy-up never ran to its end"
        await asyncio.sleep(0.001)
    assert [line.text for line in state.summary.lines] == ["A camping trip to Riverside."]
    versions = await stories.summary_versions(story)
    assert versions is not None
    assert len(versions.versions) == 1
    # Its outcome is the story's, not the episode's: no acting record of it, no effect.
    effects = await harness.plans.activation_effects([record.activation_id])
    assert {one.capability for one in effects if one.capability} == {"start_story"}


@pytest.mark.parametrize(
    ("name", "brings"),
    [
        pytest.param("tidy_story", False, id="a-tidy-up-brings-none"),
        pytest.param("note_story", True, id="any-other-refused-call-brings-one"),
    ],
)
async def test_a_refused_tidy_up_still_brings_no_round(name: str, *, brings: bool) -> None:
    """ADR-0307 §7:1 over §5:3: a tidy-up never brings a round, even refused whole.

    A label planning was never shown refuses the call whole, before authorizing; a
    refused note brings a round to say so, and a refused tidy-up does not.
    """
    arguments: dict[str, Any] = {"story": "S9"}
    if name == "note_story":
        arguments["note"] = "noted"
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", name, **arguments),))
    )
    harness = _harness(completer)
    await harness.memory.add(_episode())
    stories = FakeStoryStore(now=lambda: AT)
    path = _phases(completer, stories=stories, story_calls=True)(harness)
    working = _begun(path)
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)
    stages = {one.name: one for one in path.stages()}

    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE

    (refused,) = working.latest.planned.refused
    assert refused.reason == "'S9' names nothing you were shown"
    assert working.latest_has_calls
    assert working.latest_calls_beyond_tidy_ups is brings


@pytest.mark.parametrize(
    "parties",
    [pytest.param(OWNERS_WORDS, id="owners"), pytest.param(UNIDENTIFIED_WORDS, id="outside")],
)
async def test_a_note_is_marked_where_the_activation_read_outside_content(
    parties: tuple[SupportHolder, ...],
) -> None:
    """ADR-0300 §4:2, ADR-0303 §3:1, §9:3: by the hub's record of what was read.

    The activation's trigger came from outside, which its record says (ADR-0306 §4:5),
    so authorizing fills the note's mark from it; the note's own words decide nothing.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "note_story", story="S1", note="The reply said Sunday."),))
    )
    harness = _harness(completer)
    await harness.memory.add(_episode(parties=parties))
    stories = FakeStoryStore(now=lambda: AT)
    trip = (
        await stories.create(
            [StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)], actor=StoryActor.OWNER
        )
    ).story_id
    assert trip is not None
    path = _phases(completer, stories=stories, story_calls=True)(harness)
    working = path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel("c1"), messages=()),
        conversation_id="c1",
        trigger=_recorded_trigger(parties),
        owner_records=True,
    )
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)
    stages = {one.name: one for one in path.stages()}

    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING, ControllerStage.ACTING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE

    page = await stories.notes(trip)
    assert page is not None
    (note,) = page.notes
    assert note.text == "The reply said Sunday."
    assert note.outside is parties_are_outside(parties)


async def test_on_a_pass_that_may_not_show_the_owners_records_planning_still_writes() -> None:
    """ADR-0307 §6:5: planning can still write notes and change stories on such a pass."""
    completer = FakeToolCallingCompleter.scripted(_STARTED)
    harness = _harness(completer)
    await harness.memory.add(_episode())
    stories = FakeStoryStore(now=lambda: AT)
    path = _phases(completer, stories=stories, story_calls=True)(harness)
    working = path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel("c1"), messages=()),
        conversation_id="c1",
        trigger=_recorded_trigger(),
        owner_records=False,
    )
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)
    stages = {one.name: one for one in path.stages()}

    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING, ControllerStage.ACTING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE

    offered = {one.name for one in completer.calls[0].tools}
    assert set(STORY_CALL_CAPABILITIES) <= offered
    story = await _the_story(stories, _ACTIVATION)
    page = await stories.notes(story)
    assert page is not None
    assert [one.text for one in page.notes] == ["A camping trip to Riverside."]


async def test_a_note_is_moved_between_stories_by_its_label_end_to_end() -> None:
    """ADR-0303 §9:1, §9:4, ADR-0307 §5:5: a move carries the note named by its N label.

    The first round starts a story with two first notes, the second starts another, and
    the third moves the second note of the first story onto the other, naming the stories
    by ``S`` label and the note by the ``N`` label it was shown under.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            text="I'll keep track of the trip.",
            calls=(
                _call(
                    "c1",
                    "start_story",
                    notes=["A camping trip to Riverside.", "The dog's paperwork is open."],
                ),
            ),
        ),
        RoundResponse(
            calls=(_call("c2", "start_story", notes=["The dog's vet visit."]),),
        ),
        RoundResponse(calls=(_call("c3", "move_story", story="S1", to="S2", notes=["N2"]),)),
    )
    stories = FakeStoryStore(now=lambda: AT)
    harness = _harness(completer, stories=stories, story_calls=True)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "help me plan a camping trip to Riverside")
    episode = await _settled(harness, conversation)

    record = episode.processing_record
    assert record is not None
    member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=record.activation_id)
    texts: dict[str, list[str]] = {}
    for header in await stories.stories_of(member):
        page = await stories.notes(str(header.story_id))
        assert page is not None
        texts[str(header.story_id)] = [one.text for one in page.notes]
    assert sorted(texts.values()) == [
        ["A camping trip to Riverside."],
        ["The dog's paperwork is open.", "The dog's vet visit."],
    ]
    (trip,) = [story for story, notes in texts.items() if "A camping trip" in notes[0]]
    log = await stories.log(trip)
    assert log is not None
    (moved_out,) = [line for line in log.lines if line.change is StoryChange.NOTE_MOVED_OUT]
    assert (moved_out.actor, moved_out.trigger) == (StoryActor.PLANNING, record.activation_id)
    (labelled,) = [one for one in record.labels if one.label == "N2"]
    assert labelled.kind is LabelKind.NOTE


async def _labelled_stories(
    stories: FakeStoryStore,
) -> tuple[str, str, int, int, tuple[PlanningLabel, ...]]:
    """Two stories holding this activation, a note on each, and their recorded labels."""
    own = StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)
    other = StoryMember(kind=StoryMemberKind.ACTIVATION, id="act-other")
    made = [await stories.create([own, other], actor=StoryActor.OWNER) for _ in range(2)]
    trip, dog = (str(one.story_id) for one in made)
    notes = [
        await stories.append_note(story, text, author=StoryNoteAuthor.OWNER)
        for story, text in ((trip, "On the trip."), (dog, "On the dog."))
    ]
    on_trip, on_dog = (int(one.note.note_id) for one in notes if one.note is not None)
    labels = (
        PlanningLabel(label="S1", kind=LabelKind.STORY, id=trip),
        PlanningLabel(label="S2", kind=LabelKind.STORY, id=dog),
        PlanningLabel(label="N1", kind=LabelKind.NOTE, id=str(on_trip)),
        PlanningLabel(label="N2", kind=LabelKind.NOTE, id=str(on_dog)),
        PlanningLabel(label="E1", kind=LabelKind.EPISODE, id="activation:act-other"),
    )
    return trip, dog, on_trip, on_dog, labels


async def _stages_over(
    completer: FakeToolCallingCompleter, stories: FakeStoryStore, *, owner_records: bool
) -> tuple[PhaseWorking, dict[ControllerStage, Any]]:
    harness = _harness(completer)
    await harness.memory.add(_episode())
    await harness.memory.add(_episode("activation:act-other"))
    path = _phases(completer, stories=stories, story_calls=True)(harness)
    *_, labels = await _labelled_stories(stories)
    working = path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel("c1"), messages=()),
        conversation_id="c1",
        trigger=_recorded_trigger(),
        owner_records=owner_records,
        labels=labels,
    )
    return working, {one.name: one for one in path.stages()}


async def test_the_hub_refuses_a_move_naming_a_note_not_held_before_authorizing() -> None:
    """ADR-0307 §5:3-§5:4: refused whole with the reason, as the stories stand then."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call("c1", "move_story", story="S1", to="S2", notes=["N1", "N2"]),
                _call("c2", "move_story", story="S1", to="S2", episodes=["E1"]),
            )
        )
    )
    stories = FakeStoryStore(now=lambda: AT)
    working, stages = await _stages_over(completer, stories, owner_records=True)
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)

    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING, ControllerStage.ACTING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE

    planned = working.latest.planned
    assert [one.call.call_id for one in planned.calls] == ["c2"]
    (refused,) = planned.refused
    assert refused.call.call_id == "c1"
    assert refused.reason == "N2 is not on the story it would leave, so nothing was moved"
    trip, dog = (
        str(one.story_id)
        for one in await stories.stories_of(
            StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)
        )
    )
    # Nothing of the refused call ran; the members-only move beside it did.
    for story in (trip, dog):
        page = await stories.notes(story)
        assert page is not None
        assert len(page.notes) == 1
    holders = await stories.stories_of(StoryMember(kind=StoryMemberKind.ACTIVATION, id="act-other"))
    assert len(holders) == 1


async def test_on_an_owner_only_pass_a_move_naming_notes_is_refused_and_members_move() -> None:
    """ADR-0307 §6:5: a move or a split carries members only there; refused, not stripped."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call("c1", "move_story", story="S1", to="S2", notes=["N1"]),
                _call("c2", "split_story", story="S1", episodes=["E1"]),
            )
        )
    )
    stories = FakeStoryStore(now=lambda: AT)
    working, stages = await _stages_over(completer, stories, owner_records=False)
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)

    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING, ControllerStage.ACTING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE

    planned = working.latest.planned
    (refused,) = planned.refused
    assert refused.call.call_id == "c1"
    assert refused.reason.startswith("on this pass a move or a split carries members only")
    holders = await stories.stories_of(StoryMember(kind=StoryMemberKind.ACTIVATION, id="act-other"))
    assert len(holders) == 2  # the split took it into a story of its own


# --- an engine with no phases wired ------------------------------------------------------


async def test_the_story_standing_command_lists_what_was_done() -> None:
    """ADR-0300 §8:1: the owner's story-standing command reads the effect records.

    Where a matter stands lists what was done, from the plan store the engine holds,
    unknown first, then not done, then done; an engine with no phases wired reads it too.
    """
    stories = FakeStoryStore(now=lambda: AT)
    harness = Harness(stories=stories)
    await harness.memory.add(_past_episode("activation:past"))
    trip = (
        await stories.create(
            [StoryMember(kind=StoryMemberKind.ACTIVATION, id="past")], actor=StoryActor.OWNER
        )
    ).story_id
    assert trip is not None
    for effect_id, outcome in (("e1", ToolOutcome.SUCCEEDED), ("e2", ToolOutcome.FAILED)):
        effect = ActivationEffect(
            id=effect_id,
            activation_id="past",
            round="round:past",
            capability="book",
            values_digest="0" * 64,
            decision_id=f"decision:{effect_id}",
            claimed_at=AT,
        )
        await harness.plans.claim_activation_effect(effect, match=None)
        await harness.plans.finish_activation_effect(effect_id, outcome)

    standing = await harness.engine.story_standing(trip)

    assert standing is not None
    assert [(one.activation_id, one.state) for one in standing.done] == [
        ("past", StoryEffectState.NOT_DONE),
        ("past", StoryEffectState.DONE),
    ]


# --- planning's look-ups (ADR-0307 §6:6, ADR-0308 §6) -----------------------------------------

#: A digest reading a memory search's one outside record, by the label local to the call.
_SEARCH_DIGESTED: Final = json.dumps(
    {"evidence": [{"text": "The appointment moved to three.", "source": "D1"}]}
)
_UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())


async def _searching_harness(
    completer: FakeToolCallingCompleter,
    *records: Memory,
    digests: FakeModelProvider | None = None,
) -> Harness:
    """A test hub offering the look-ups, its memory holding ``records``."""
    store = FakeMemoryStore(now=lambda: AT)
    for record in records:
        await store.add(record)
    return Harness(
        understanding=understanding_stage(),
        tools=(_BOOK,),
        memory=store,
        phases=_phases(
            completer,
            digests=digests if digests is not None else FakeModelProvider(reply=_SEARCH_DIGESTED),
            look_ups=True,
        ),
    )


_SAID: Final = _remembered("said", MemorySource.USER_ASSERTED, f"{_DENTIST} with Dr Rao")
_REPORTED: Final = _remembered("reported", MemorySource.EXTERNAL, f"{_DENTIST} moved to 3pm")


async def test_a_memory_search_and_a_follow_up_reach_planning_by_label_and_digest() -> None:
    """ADR-0307 §6:6, ADR-0308 §6:2, §6:6-§6:7, end to end.

    Planning searches its memory: the user's fact comes back under its own M label, and
    the fact a source reported is held by id and read by a digest answering the call's
    *looking for*, never shown. It then follows up on that result by its R label with a
    new question: the result as held is read again against it, under the same label,
    and the answer is written from both digests.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            text="Let me check.",
            calls=(_call("c1", "search_memory", query="dentist", looking_for="when it is"),),
        ),
        RoundResponse(calls=(_call("c2", "follow_up", result="R1", looking_for="what moved"),)),
        RoundResponse(text="It is at three, with Dr Rao."),
    )
    digests = FakeModelProvider(reply=_SEARCH_DIGESTED)
    harness = await _searching_harness(completer, _SAID, _REPORTED, digests=digests)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when is the dentist?")
    episode = await _settled(harness, conversation, seeded=frozenset({"said", "reported"}))

    assert _said(await _messages(harness, conversation))[1:] == [
        (MessageAuthor.ASSISTANT, "Let me check."),
        (MessageAuthor.ASSISTANT, "It is at three, with Dr Rao."),
    ]
    # Both look-ups ran acting with digesting beside it; the third round ended it.
    assert _stages(episode)[3:] == [
        (ControllerStage.PLANNING, ControllerRule.FIRST_ROUND_DUE),
        (ControllerStage.AUTHORIZING, ControllerRule.ROUND_UNAUTHORIZED),
        (ControllerStage.ACTING, ControllerRule.ROUND_AUTHORIZED),
        (ControllerStage.DIGESTING, ControllerRule.ROUND_AUTHORIZED),
        (ControllerStage.PLANNING, ControllerRule.ROUND_DUE),
        (ControllerStage.AUTHORIZING, ControllerRule.ROUND_UNAUTHORIZED),
        (ControllerStage.ACTING, ControllerRule.ROUND_AUTHORIZED),
        (ControllerStage.DIGESTING, ControllerRule.ROUND_AUTHORIZED),
        (ControllerStage.PLANNING, ControllerRule.ROUND_DUE),
        (ControllerStage.AUTHORIZING, ControllerRule.ROUND_UNAUTHORIZED),
        (ControllerStage.ACTING, ControllerRule.ROUND_AUTHORIZED),
        (ControllerStage.END, ControllerRule.NOTHING_DUE),
    ]

    # Two digests of the one held result, each reading the outside fact fetched by id,
    # each answering its own question (§4:3, §6:7).
    asked = [json.loads(call.messages[-1].content) for call in digests.calls]
    assert [one["question"] for one in asked] == ["when it is", "what moved"]
    for one in asked:
        assert [(row["label"], row["text"]) for row in one["records"]] == [
            ("D1", f"{_DENTIST} moved to 3pm")
        ]
    record = episode.processing_record
    assert record is not None
    assert [(one.result, one.question, one.outcome) for one in record.digests] == [
        ("R1", "when it is", DigestOutcome.ANSWERED),
        ("R1", "what moved", DigestOutcome.ANSWERED),
    ]
    assert all(
        one.evidence == (EvidenceItem(text="The appointment moved to three.", source="M1"),)
        for one in record.digests
    )
    labels = {one.label: (one.kind, one.id) for one in record.labels}
    assert labels["M1"] == (LabelKind.MEMORY, "reported")
    assert labels["M2"] == (LabelKind.MEMORY, "said")
    assert labels["R1"][0] is LabelKind.RESULT

    # The second round: the user's fact under its own label, the outside one only as
    # evidence, never its text (ADR-0307 §9:2).
    second = shown_text(completer.calls[1])
    (search,) = reported(completer.calls[1], 0)
    assert search["result"]["label"] == "R1"
    value = search["result"]["value"]
    assert [(one["label"], one["fact"]) for one in value["remembered"]] == [
        ("M2", f"{_DENTIST} with Dr Rao")
    ]
    assert value["resting_on_outside_content"] == "read for you by a digest, under evidence"
    assert "moved to 3pm" not in second
    (evidence,) = search["evidence"]
    assert (evidence["digest_of"], evidence["looking_for"]) == ("R1", "when it is")

    # The third: the follow-up's result is the result it named, under the same label,
    # and its digest is told apart by its question.
    (follow_up,) = reported(completer.calls[2], 1)
    assert follow_up["result"] == {
        "label": "R1",
        "value": "read for you by a digest, under evidence",
    }
    # Each digest is shown once, in the report on the call that brought it (ADR-0356
    # §5:6): the search's in the second round's report, the follow-up's in the third's.
    (searched,) = reported(completer.calls[2], 0)
    assert [(one["digest_of"], one["looking_for"]) for one in searched["evidence"]] == [
        ("R1", "when it is")
    ]
    assert [(one["digest_of"], one["looking_for"]) for one in follow_up["evidence"]] == [
        ("R1", "what moved")
    ]
    # Read digested evidence, so the episode rests on outside content (§5:4).
    assert episode.provenance.derived_from_external


async def test_a_follow_up_naming_a_result_with_nothing_held_comes_back_not_done() -> None:
    """ADR-0308 §6:7: a search that found nothing outside holds nothing to ask again."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            text="Let me check.",
            calls=(_call("c1", "search_memory", query="dentist", looking_for="when it is"),),
        ),
        RoundResponse(calls=(_call("c2", "follow_up", result="R1", looking_for="what moved"),)),
        RoundResponse(text="It is with Dr Rao."),
    )
    digests = FakeModelProvider(reply=_SEARCH_DIGESTED)
    harness = await _searching_harness(completer, _SAID, digests=digests)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when is the dentist?")
    episode = await _settled(harness, conversation, seeded=frozenset({"said"}))

    (follow_up,) = reported(completer.calls[2], 1)
    assert follow_up["outcome"].startswith("not done")
    assert "nothing is held" in follow_up["outcome"]
    assert "result" not in follow_up
    assert digests.calls == []
    record = episode.processing_record
    assert record is not None
    assert record.digests == ()


async def test_a_search_applies_the_audience_predicate_at_the_search_and_at_the_fetch() -> None:
    """ADR-0282 §2:8: an id enters only once admitted, and each fetch applies it again.

    On an unbounded audience, a fact about someone else and a fact from a source it may
    not hear are not kept by the search; a fact that became about someone else before
    planning's fetch is refused there, recorded missing and shown to no round.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(_call("c1", "search_memory", query="dentist", looking_for="when it is"),)
        ),
        RoundResponse(text="ok"),
    )
    later = _remembered("later", MemorySource.USER_ASSERTED, f"{_DENTIST} reminder")
    harness = await _searching_harness(completer)
    for record in (
        _SAID,
        _REPORTED,
        later,
        _SAID.model_copy(update={"id": "about-sam", "subjects": ("Sam",)}),
    ):
        await harness.memory.add(record)
    path = _phases(completer, look_ups=True)(harness)
    working = path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel("c1"), messages=()),
        conversation_id="c1",
        trigger=_recorded_trigger(),
        owner_records=False,
    )
    given = _Given(
        deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working, supply=_UNBOUNDED
    )
    stages = {one.name: one for one in path.stages()}
    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING, ControllerStage.ACTING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE

    # At the search: neither the fact about Sam nor the one a source reported is kept,
    # shown or held.
    (acted,) = working.acted_rounds()
    (one,) = acted.calls
    assert sorted(searched_ids(one.output)) == ["later", "said"]
    assert len(working.held) == 0

    # At the fetch: the fact now about someone else is refused, and recorded missing.
    await harness.memory.add(later.model_copy(update={"subjects": ("Sam",)}))
    assert (await stages[ControllerStage.PLANNING].run(given)).outcome is StageOutcome.DONE
    assert one.result_id is not None
    assert [record.id for record in working.searched[one.result_id]] == ["said"]
    (fetched,) = working.search_fetches
    assert fetched.missing == ("later",)
    request = completer.calls[1].exchange.briefing
    assert "reminder" not in request


async def _page_read(
    *, outside: bool, owner_records: bool = True, supply: TurnSupply = _BOUNDED
) -> tuple[PhaseWorking, _Given, dict[ControllerStage, Any], FakeToolCallingCompleter, str]:
    """A pass shown story ``S1`` by an earlier round, planning reading its full view.

    The story holds a note planning wrote, marked where ``outside``. The activation's own
    episode is clean, so only what the read shows can say outside content was read.
    """
    stories = FakeStoryStore(now=lambda: AT)
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "read_story", story="S1"),)),
        RoundResponse(text="Saturday."),
    )
    harness = _harness(completer)
    await harness.memory.add(_episode())
    await harness.memory.add(_past_episode("activation:past"))
    trip = (
        await stories.create(
            [StoryMember(kind=StoryMemberKind.ACTIVATION, id="past")], actor=StoryActor.OWNER
        )
    ).story_id
    assert trip is not None
    await stories.append_note(
        trip,
        "The venue says Saturday.",
        author=StoryNoteAuthor.PLANNING,
        written_during="past",
        outside=outside,
    )
    path = _phases(completer, stories=stories, look_ups=True)(harness)
    working = path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel("c1"), messages=()),
        conversation_id="c1",
        trigger=_recorded_trigger(),
        owner_records=owner_records,
        labels=(PlanningLabel(label="S1", kind=LabelKind.STORY, id=trip),),
    )
    given = _Given(
        deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working, supply=supply
    )
    stages: dict[ControllerStage, Any] = {one.name: one for one in path.stages()}
    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING, ControllerStage.ACTING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE
    return working, given, stages, completer, trip


@pytest.mark.parametrize("outside", [True, False], ids=["marked", "unmarked"])
async def test_a_storys_full_view_is_read_and_its_marks_counted(outside: bool) -> None:
    """ADR-0300 §10:6, ADR-0307 §6:6: a story read's view, its marked line read.

    The view is read under the pass's audience when the call runs and held under the
    call's result; the next round is shown it under that result's label, and its marked
    note marks the round's notes and reaches the ruling, through the note's held mark.
    """
    working, given, stages, completer, trip = await _page_read(outside=outside)

    (view,) = working.pages.values()
    assert view.story_id == trip
    (note,) = view.notes
    assert working.notes[note.note_id] == note
    assert working.fetched_outside is outside

    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE
    (read,) = reported(completer.calls[1], 0)
    assert read["result"]["label"] == "R1"
    shown = read["result"]["value"]
    assert shown["label"] == "S1"
    (line,) = shown["notes_since_tidied"]
    assert line["text"] == "The venue says Saturday."
    assert ("outside_content" in line) is outside
    assert working.latest.planned.round.notes_marked is outside
    decided = working.latest.authorization
    assert decided is not None
    assert decided.read_outside_content is outside


async def test_a_storys_full_view_follows_the_owner_only_placement() -> None:
    """ADR-0307 §6:4: on a pass that may not show the owner's records, no note is shown."""
    working, given, stages, completer, _ = await _page_read(
        outside=True, owner_records=False, supply=_UNBOUNDED
    )

    (view,) = working.pages.values()
    assert view.notes == ()
    assert view.notes_withheld
    assert working.notes == {}
    assert (await stages[ControllerStage.PLANNING].run(given)).outcome is StageOutcome.DONE
    shown = reported(completer.calls[1], 0)[0]["result"]["value"]
    assert "notes_since_tidied" not in shown
    assert "The venue says Saturday." not in shown_text(completer.calls[1])


async def test_a_story_read_naming_a_story_never_shown_is_refused_whole() -> None:
    """ADR-0307 §5:3: a label planning was never shown runs nothing."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "read_story", story="S9"),)),
        RoundResponse(text="ok"),
    )
    harness = _harness(completer, stories=FakeStoryStore(now=lambda: AT), look_ups=True)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "what about the trip?")
    await _settled(harness, conversation)

    (read,) = reported(completer.calls[1], 0)
    assert read["outcome"].startswith("refused")
    assert "S9" in read["outcome"]


async def test_a_tidy_up_naming_a_story_never_shown_beside_a_look_up_is_refused_and_recorded() -> (
    None
):
    """ADR-0356 §5:3, §8:6, §14:9: a tidy-up refused before it ran is reported and recorded
    refused with its reason, as the look-up beside it is, each by its call."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call("c1", "tidy_story", story="S9"),
                _call("c2", "read_story", story="S9"),
            )
        ),
        RoundResponse(text="ok"),
    )
    harness = _harness(
        completer, stories=FakeStoryStore(now=lambda: AT), story_calls=True, look_ups=True
    )
    conversation = await _conversation(harness)

    await _say(harness, conversation, "tidy the trip")
    episode = await _settled(harness, conversation)

    tidied, read = reported(completer.calls[1], 0)
    for one in (tidied, read):
        assert one["outcome"].startswith("refused")
        assert "S9" in one["outcome"]
    record = episode.processing_record
    assert record is not None
    entries = {one.call_id: one for one in record.call_records}
    assert set(entries) == {"c1", "c2"}
    for entry in entries.values():
        assert entry.outcome is CallOutcomeKind.REFUSED
        assert entry.reason is not None
        assert "S9" in entry.reason
    assert entries["c1"].capability == "tidy_story"


class _GatedWrites(FakeConversationStore):
    """The chat's store, holding the assistant's message ``words`` until released."""

    def __init__(self, words: str) -> None:
        super().__init__(now=lambda: AT)
        self._words = words
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def append_message(self, conversation_id: str, message: NewMessage) -> MessageReceipt:
        if message.author is MessageAuthor.ASSISTANT and message.text == self._words:
            self.entered.set()
            await self.release.wait()
        return await super().append_message(conversation_id, message)


async def test_a_tidy_ups_entry_is_stored_as_it_starts_while_its_sibling_is_pending() -> None:
    """ADR-0356 §8:6, §14:9: a tidy-up that starts has its entry appended when it starts,
    with no outcome, before the round's other calls have ended."""
    completer = FakeToolCallingCompleter.scripted(
        _STARTED,
        RoundResponse(
            calls=(
                _call("c2", "tidy_story", story="S1"),
                _call("c3", "text", to="the user", words="Tidying."),
            )
        ),
        RoundResponse(),
    )
    stories = FakeStoryStore(now=lambda: AT)
    writes = _GatedWrites("Tidying.")
    harness = Harness(
        understanding=understanding_stage(),
        tools=(_BOOK,),
        phases=_phases(completer, stories=stories, story_calls=True),
        conversation_store=writes,
    )
    conversation = await _conversation(harness)

    await _say(harness, conversation, "help me plan a camping trip to Riverside")
    await asyncio.wait_for(writes.entered.wait(), _SETTLE)

    async def tidy_entry_stored() -> bool:
        for one in await harness.memory.export():
            record = one.processing_record if isinstance(one, EpisodicMemory) else None
            if record is not None and record.is_open:
                return any(
                    entry.call_id == "c2" and entry.outcome is None for entry in record.call_records
                )
        return False

    try:
        deadline = asyncio.get_running_loop().time() + _SETTLE
        while not await tidy_entry_stored():
            assert asyncio.get_running_loop().time() < deadline, "never stored as it started"
            await asyncio.sleep(0.001)
        stored = [
            one
            for one in await harness.memory.export()
            if isinstance(one, EpisodicMemory)
            and one.processing_record is not None
            and one.processing_record.is_open
        ]
        assert stored
        open_record = stored[0].processing_record
        assert open_record is not None
        assert "c3" not in {entry.call_id for entry in open_record.call_records}
    finally:
        writes.release.set()
    episode = await _settled(harness, conversation)
    record = episode.processing_record
    assert record is not None
    entries = {one.call_id: one for one in record.call_records}
    assert entries["c2"].outcome is None
    assert entries["c3"].outcome is CallOutcomeKind.DONE


def test_the_phases_are_wired_only_beside_understanding() -> None:
    with pytest.raises(ConfigurationError, match="only beside both"):
        Harness(phases=_phases(FakeToolCallingCompleter()))


# --- ADR-0314: the diagnostic record of one activation, end to end ------------------------


async def test_with_the_record_on_each_source_writes_for_the_one_activation() -> None:
    """§4: the controller's steps and each phase's entries, under the activation's id.

    The completer is a fake, which writes no response, so planning's returned entry is
    the real completer's to write and is pinned in ``tests/models``. The glue and
    acting write none (§4:2-§4:3).
    """
    sink = FakeDiagnosticSink()
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(text="Noted.", calls=(_remember("c1", "The user likes tea."),)),
        RoundResponse(),
    )
    harness = Harness(
        understanding=UnderstandingStage(
            model=TextAsStructured(FakeModelProvider(reply=STATED_PROPOSAL)),
            excerpt_chars=EXCERPT_CHARS,
            prompt=default_prompt(UNDERSTANDING_PROMPT),
            diagnostics=sink,
        ),
        tools=(_BOOK,),
        phases=_phases(completer, diagnostics=sink),
        diagnostics=sink,
    )
    conversation = await _conversation(harness)

    await _say(harness, conversation, "remember I like tea")
    episode = await _settled(harness, conversation)

    activation = episode.id.removeprefix("activation:")
    assert {one.activation_id for one in sink.recorded} == {activation}
    assert {one.source for one in sink.recorded} == {
        DiagnosticSource.CONTROLLER,
        DiagnosticSource.UNDERSTANDING,
        DiagnosticSource.PLANNING,
        DiagnosticSource.AUTHORIZING,
    }
    steps = sink.of(DiagnosticSource.CONTROLLER, DiagnosticKind.STEP)
    assert [(one.body["stage"], one.body["due"]) for one in steps] == [
        (stage.value, rule.value) for stage, rule in _stages(episode)
    ]
    assert [one.kind for one in sink.of(DiagnosticSource.UNDERSTANDING)] == [
        DiagnosticKind.GIVEN,
        DiagnosticKind.RETURNED,
    ]
    # Two rounds: the remember brings a second (ADR-0315 §2:1), which has nothing to do.
    assert [one.kind for one in sink.of(DiagnosticSource.PLANNING)] == [
        DiagnosticKind.GIVEN,
        DiagnosticKind.GIVEN,
    ]
    (authorized,) = sink.of(DiagnosticSource.AUTHORIZING)
    assert authorized.model_dump(mode="json")["body"]["calls"][0]["name"] == "remember"


async def test_with_the_record_off_an_activation_writes_nothing() -> None:
    """§2:1: no sink anywhere, and the same activation runs."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="Hello!"))
    harness = _harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "hi")
    episode = await _settled(harness, conversation)

    assert episode.outcome == "Hello!"
    assert harness.engine._diagnostics is None


# --- ADR-0313 §4:3-§4:5: an event through the phases --------------------------------------

#: An event's budget, ample for every case that is not about running out of it.
_EVENT_BUDGET: Final = timedelta(seconds=10)


async def _event(
    harness: Harness,
    *,
    timeout: timedelta = _EVENT_BUDGET,  # noqa: ASYNC109 — the event's budget, handed to receive
) -> tuple[InformationalEventResult, EpisodicMemory]:
    """Receive the shared contract's event, and read the episode it froze."""
    result = await harness.engine.receive(event_input(), reply=None, timeout=timeout)
    return _received(result), await _event_episode(harness, result)


def _received(result: ChannelResult) -> InformationalEventResult:
    assert result.channel == event_input().target
    assert isinstance(result.result, InformationalEventResult)
    # §4:4: how it ended, and nothing it wrote.
    assert set(result.result.model_dump()) == {"kind", "ended"}
    return result.result


async def _event_episode(harness: Harness, result: ChannelResult) -> EpisodicMemory:
    assert result.capture.state == "recorded"
    assert result.capture.episode_id is not None
    episode = await harness.memory.get(result.capture.episode_id)
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert not episode.processing_record.is_open
    return episode


async def _wrote_nothing(harness: Harness, episode: EpisodicMemory) -> None:
    """ADR-0307 §3:8, ADR-0309 §5:6: no message anywhere, and none claimed."""
    assert await harness.conversation_store.recent() == []
    assert episode.outcome is None
    effects = await harness.plans.activation_effects([episode.id.removeprefix("activation:")])
    assert [one for one in effects if one.capability is None] == []


async def test_an_event_runs_the_phases_in_a_place_that_takes_no_message() -> None:
    """§4:3: one activation, its place takes no message, and its text is kept, not written."""
    text = "The thermostat is in eco mode; nothing needs doing."
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text=text))
    harness = _harness(completer)

    result, episode = await _event(harness)

    assert result.ended is ActivationEnding.DONE
    # Authorizing is handed no message, since the place takes none, so with no call
    # allowed nothing is due for acting.
    assert _stages(episode) == [
        (ControllerStage.WINDOWS, ControllerRule.WINDOWS_UNASSEMBLED),
        (ControllerStage.UNDERSTANDING, ControllerRule.NOT_UNDERSTOOD),
        (ControllerStage.PLANNING, ControllerRule.FIRST_ROUND_DUE),
        (ControllerStage.AUTHORIZING, ControllerRule.ROUND_UNAUTHORIZED),
        (ControllerStage.END, ControllerRule.NOTHING_DUE),
    ]
    # Planning is shown that the place takes no message (ADR-0307 §3:8).
    (asked,) = completer.calls
    place = json.loads(asked.exchange.briefing)["place"]
    assert place["takes_message"] is False
    assert place["description"] == EVENT_DESCRIPTION
    assert place["input"].startswith("an outside report")
    # Its text is kept with the episode, as its notes too, and written nowhere.
    record = episode.processing_record
    assert record is not None
    (planning_round,) = record.rounds
    assert (planning_round.text, planning_round.notes) == (text, text)
    assert planning_round.notes_marked
    await _wrote_nothing(harness, episode)
    assert _classified(episode) == (ProcessingStatus.COMPLETED, ProcessingReason.RETURNED)


async def test_an_event_remembers_starts_a_story_and_notes_it() -> None:
    """ADR-0309 §5:5: an event's planning still remembers and keeps its stories.

    The event is an outside report, so the candidate it records is marked as resting on
    outside content (ADR-0329 §3:4). A candidate writes no memory and passes no
    ``MemoryPolicy`` (§5:6), so it is recorded, done, as on any activation: the observer's
    writes carry ADR-0106 §6's floor. The story calls run.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _remember("c1", "The thermostat goes to eco mode at 18:00."),
                _call("c2", "start_story", notes=["The thermostat's schedule."]),
            ),
        ),
        RoundResponse(
            calls=(_call("c3", "note_story", story="S1", note="Eco mode at 18:00 again."),)
        ),
        # The note brings a third round (ADR-0315 §2:1), which has nothing to do.
        RoundResponse(),
    )
    stories = FakeStoryStore(now=lambda: AT)
    harness = _harness(completer, stories=stories, story_calls=True)

    result, episode = await _event(harness)

    assert result.ended is ActivationEnding.DONE
    record = episode.processing_record
    assert record is not None
    activation = record.activation_id
    shown = reported(completer.calls[1], 0)
    assert [one["outcome"].split(":")[0] for one in shown] == ["done", "done"]
    assert [call.name for call in completer.calls[1].exchange.steps[0].response.calls] == [
        "remember",
        "start_story",
    ]
    effects = await harness.plans.activation_effects([activation])
    assert [(one.capability, one.outcome) for one in effects] == [
        ("remember", ToolOutcome.SUCCEEDED),
        ("start_story", ToolOutcome.SUCCEEDED),
    ]
    # The candidate is the call as its round recorded it (ADR-0329 §3:3).
    assert record.rounds[0].calls[0].arguments["fact"] == (
        "The thermostat goes to eco mode at 18:00."
    )
    story = await _the_story(stories, activation)
    page = await stories.notes(story)
    assert page is not None
    # The event is an outside report, so what planning notes from it is marked
    # (ADR-0303 §3:1, ADR-0306 §4:5).
    assert [(one.text, one.author, one.written_during, one.outside) for one in page.notes] == [
        ("The thermostat's schedule.", StoryNoteAuthor.PLANNING, activation, True),
        ("Eco mode at 18:00 again.", StoryNoteAuthor.PLANNING, activation, True),
    ]
    await _wrote_nothing(harness, episode)


async def test_an_event_ended_by_the_round_limit_couldnt_finish() -> None:
    """§4:5: the round limit ends it, it returns *couldn't finish*, and writes nothing."""
    refused = [RoundResponse(text="Trying.", calls=(_call(f"c{n}", "nowhere"),)) for n in (1, 2, 3)]
    harness = _harness(FakeToolCallingCompleter.scripted(*refused))

    result, episode = await _event(harness)

    assert result.ended is ActivationEnding.COULDNT_FINISH
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.ROUND_LIMIT_REACHED)
    assert _classified(episode) == (ProcessingStatus.FAILED, ProcessingReason.PROCESSING_FAILED)
    await _wrote_nothing(harness, episode)


async def test_an_event_that_writes_nothing_is_done() -> None:
    """ADR-0307 §3:8: an event never writes, so writing nothing is no failure to finish."""
    harness = _harness(FakeToolCallingCompleter.scripted(RoundResponse()))

    result, episode = await _event(harness)

    assert result.ended is ActivationEnding.DONE
    assert _classified(episode) == (ProcessingStatus.COMPLETED, ProcessingReason.RETURNED)
    await _wrote_nothing(harness, episode)


class _Fails(FakeToolCallingCompleter):
    """A completer whose round fails: a phase's failure."""

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        del exchange, tools, model
        msg = "the provider failed"
        raise ModelError(msg)


async def test_an_event_whose_phase_fails_couldnt_finish_and_raises_nothing() -> None:
    """§4:5: a phase's failure is a result, and the episode keeps why it ended."""
    harness = _harness(_Fails())

    result, episode = await _event(harness)

    assert result.ended is ActivationEnding.COULDNT_FINISH
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.STAGE_FAILED)
    assert _classified(episode)[0] is ProcessingStatus.FAILED
    await _wrote_nothing(harness, episode)


async def test_an_events_timeout_is_its_budget_and_running_out_couldnt_finish() -> None:
    """§4:5: the event's ``timeout`` bounds its activation; planning outlives it."""
    completer = _GatedCompleter(RoundResponse(text="Too late."), gated=1)
    harness = _harness(completer)

    result, episode = await _event(harness, timeout=timedelta(milliseconds=300))

    assert completer.entered.is_set()
    assert result.ended is ActivationEnding.COULDNT_FINISH
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.STAGE_TIMED_OUT)
    assert _classified(episode) == (ProcessingStatus.FAILED, ProcessingReason.TIMEOUT)
    await _wrote_nothing(harness, episode)


@pytest.mark.parametrize("budget", [timedelta(0), timedelta(seconds=-1)])
async def test_an_event_with_no_budget_couldnt_finish_before_anything_runs(
    budget: timedelta,
) -> None:
    """§4:5: a budget already spent reaches no stage, and is still a result."""
    completer = FakeToolCallingCompleter.scripted()
    harness = _harness(completer)

    result, episode = await _event(harness, timeout=budget)

    assert result.ended is ActivationEnding.COULDNT_FINISH
    assert completer.calls == []
    assert _classified(episode) == (ProcessingStatus.FAILED, ProcessingReason.TIMEOUT)
    record = episode.processing_record
    assert record is not None
    assert record.understanding == ()
    await _wrote_nothing(harness, episode)


async def _running_activation(harness: Harness) -> str:
    """The activation id of the one episode still open, once its admission wrote it."""
    deadline = asyncio.get_running_loop().time() + _SETTLE
    while True:
        for one in await harness.memory.export():
            if (
                isinstance(one, EpisodicMemory)
                and one.processing_record is not None
                and one.processing_record.is_open
            ):
                return one.processing_record.activation_id
        if asyncio.get_running_loop().time() > deadline:
            msg = "no activation was admitted"
            raise AssertionError(msg)
        await asyncio.sleep(0.001)


async def test_a_stopped_event_returns_stopped() -> None:
    """§4:4, ADR-0295 §3:4: a stop lands after the current round, and is a result."""
    completer = _GatedCompleter(
        RoundResponse(
            calls=(_remember("c1", "The thermostat is in eco mode."),),
        ),
        RoundResponse(text="Done."),
        gated=2,
    )
    harness = _harness(completer)

    receiving = asyncio.create_task(
        harness.engine.receive(event_input(), reply=None, timeout=_EVENT_BUDGET)
    )
    await asyncio.wait_for(completer.entered.wait(), _SETTLE)
    stopped = await harness.engine.stop_activation(await _running_activation(harness))
    completer.gate.set()
    received = await asyncio.wait_for(receiving, _SETTLE)

    assert stopped is ActivationStop.STOPPED
    assert _received(received).ended is ActivationEnding.STOPPED
    episode = await _event_episode(harness, received)
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.STOPPED)
    assert _classified(episode) == (ProcessingStatus.INTERRUPTED, ProcessingReason.STOPPED)
    await _wrote_nothing(harness, episode)


#: An event whose arguments are inside a 512-byte bound and whose result, its receipt
#: reserved, is past it: the channel's identity is in both.
_LONG_EVENT: Final = ChannelInput(
    target=ChannelIdentity(channel_type="informational_event", instance_id="e" * 250),
    payload=TextChannelPayload(text="x"),
)


@pytest.mark.parametrize(
    ("completer", "budget"),
    [
        (FakeToolCallingCompleter.scripted(RoundResponse(text="Noted.")), _EVENT_BUDGET),
        (_Fails(), _EVENT_BUDGET),
        (FakeToolCallingCompleter.scripted(), timedelta(0)),
    ],
    ids=["done", "a_phase_failed", "no_budget"],
)
async def test_an_events_result_past_the_output_bound_raises_as_every_result_does(
    completer: FakeToolCallingCompleter, budget: timedelta
) -> None:
    """ADR-0085 §8c: every result is held to the bound, the one built for an end included.

    A result *couldn't finish* builds in place of a failure is measured with its receipt
    as a returned one is, and one too large raises rather than being returned.
    """
    harness = Harness(
        understanding=understanding_stage(),
        tools=(_BOOK,),
        phases=_phases(completer),
        max_payload_bytes=512,
    )

    with pytest.raises(OversizedValueError, match="the result of receive"):
        await harness.engine.receive(_LONG_EVENT, reply=None, timeout=budget)
