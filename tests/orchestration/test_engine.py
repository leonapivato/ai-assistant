"""The engine façade an adapter drives (ADR-0042 §1, §3, §4).

What is exercised here is only what the façade *composes*: that one call runs a
turn and drives its step, that a parked confirmation comes back as
engine-assembled content plus an opaque token, that relaying the token resumes the
exact step, and that shutdown drains in-flight work before closing owned
resources. Every collaborator is a canonical fake from ``ai_assistant.testing`` or
one of this package's own stage objects, so nothing here imports a subsystem
concrete (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

import pytest
from pydantic import SecretStr

from ai_assistant.core.errors import (
    DeferralStoreError,
    MemoryStoreError,
    OversizedValueError,
    TraceStoreError,
)
from ai_assistant.core.protocols import (
    ActionPolicy,
    AuditTrail,
    AuthorizationResolution,
    CoverageAnswers,
    InvocationLedger,
    RecipientGrantStore,
    SpeechSynthesizer,
    SpeechTranscriber,
    SpendGate,
    SpendLedger,
)
from ai_assistant.core.types import (
    ActionPlan,
    AnswerKind,
    AssociationVerdict,
    Attestation,
    BeliefBand,
    BeliefSummary,
    CanonicalDestination,
    CostBasis,
    DataTier,
    DestinationProtocol,
    EpisodicMemory,
    Evidence,
    EvidenceDigest,
    FeedbackEvent,
    FeedbackKind,
    GoalAssociation,
    GoalBrief,
    Idempotency,
    MemoryDecisionKind,
    MemoryKind,
    MemorySource,
    PlannerOutput,
    PlanStep,
    ProposedAction,
    Provenance,
    ProvisioningState,
    QuestionState,
    ReadAskOutcome,
    Reversibility,
    RiskLevel,
    SemanticMemory,
    ToolCost,
    ToolDefinition,
    TraceOutcome,
    Validity,
    band_of,
    rests_on_recorded_external_content,
    secret_value,
)
from ai_assistant.orchestration import (
    AuthorizationOperations,
    ComposingStage,
    ConnectionOperations,
    ConversationLifecycle,
    DestinationTrustOperations,
    Engine,
    ForecastServicer,
    GrantOperations,
    HeldSource,
    MemoryWriteStage,
    QuestionStage,
    RecipientGrantOperations,
    RoutingStage,
    SearchFooting,
    SearchServicer,
    StepExecutor,
    StepRunner,
    belief_from_record,
    belief_summary_from_record,
    presented_confidence,
)
from ai_assistant.orchestration import engine as engine_module
from ai_assistant.orchestration.consolidation import ConsolidationReport
from ai_assistant.orchestration.engine import ENGINE_SHUTTING_DOWN, DrainPhase
from ai_assistant.orchestration.loop import LearningLoop
from ai_assistant.orchestration.parked_reads import ParkedReadOperations
from ai_assistant.orchestration.payloads import DEFAULT_MAX_PAYLOAD_BYTES
from ai_assistant.orchestration.speech import DEFAULT_MAX_SPOKEN_AUDIO_BYTES
from ai_assistant.orchestration.stories import DEFAULT_STORY_SUMMARY_VIEW_NOTES
from ai_assistant.orchestration.understanding import RecentEpisodes, WindowsStage
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    DEFAULT_SEARCH_ORIGIN,
    FakeActionPolicy,
    FakeAuditTrail,
    FakeConnectionProvisioner,
    FakeContextProvider,
    FakeConversationStore,
    FakeDeferralStore,
    FakeDestinationTrustStore,
    FakeEgressBinder,
    FakeFeedbackProcessor,
    FakeGoalAssociator,
    FakeGoalAuthorizationStore,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeModelProvider,
    FakeParkedReads,
    FakePlanStore,
    FakeRecipientGrantStore,
    FakeSourceGrantStore,
    FakeSourceReadTrail,
    FakeSpeechSynthesizer,
    FakeSpeechTranscriber,
    FakeStreamingCompleter,
    FakeToolInvoker,
    FakeTraceRetention,
    FakeTraceSink,
    evaluation_trace,
    with_phase_declaration,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        DiagnosticSink,
        EgressBinder,
        SourceReadTrail,
        StoryStore,
    )
    from ai_assistant.core.types import (
        CurrentContext,
        EvaluationTrace,
        FrozenJson,
        MemoryRecord,
        ShownFile,
    )
    from ai_assistant.orchestration.delivery import DeliveryOutbox
    from ai_assistant.orchestration.informational_events import InformationalEventStage
    from ai_assistant.orchestration.matters_pass import MattersPass
    from ai_assistant.orchestration.phase_path import PhasePath
    from ai_assistant.orchestration.recall import RecallStage
    from ai_assistant.orchestration.reconciling import ReconciliationStage
    from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage
    from ai_assistant.orchestration.understanding import UnderstandingStage
    from ai_assistant.testing.invoker import FakeToolImplementation


def _goal_ids(prefix: str) -> Callable[[], str]:
    """Distinct identifiers, ``<prefix>-1`` first (ADR-0249 §12).

    ``save_goal`` is the opening write alone since ADR-0249 §12, so a loop wired with a
    *constant* factory would refuse its second turn: a goal per turn needs an id per
    turn, which is what production's ``uuid4`` already gives it. The first value is
    unchanged, so a single-turn case reads exactly what it read before.
    """
    count = 0

    def factory() -> str:
        nonlocal count
        count += 1
        return f"{prefix}-{count}"

    return factory


AT = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)


class ConsumingTrail(AuditTrail, InvocationLedger, SpendGate, SpendLedger, Protocol):
    """Both faces of the **one** audit object (ADR-0192 §2).

    The composition root wires a single store as ``AuditTrail``,
    ``InvocationLedger`` and ``InvocationCompleter``, handing each consumer the
    face its job needs. A harness that wires the runner and the seam has to name
    both at once — the runner records rulings through the trail, the seam claims
    through the ledger, the seam is **admitted** through the gate, and they must
    be the same object or every claim is refused and the ceiling is decided over
    rows a second holder cannot see (ADR-0194 §5).
    Declared here for the reason ``InvocableToolRegistry`` is declared in the
    invoker suite: a variable annotated with one Protocol does not statically
    satisfy the other, and a cast would hide the very identity being asserted.
    """


def _composing() -> ComposingStage:
    """The terminal composing stage every engine now takes (ADR-0170 §2).

    Wired to a cooperating fake provider, which is all these tests need: what the
    composed answer *says*, and what the engine does when composing it fails, are
    pinned in ``tests/orchestration/test_composing.py`` and
    ``tests/orchestration/test_engine_composing.py``.
    """
    return ComposingStage(model=FakeModelProvider(), streaming=FakeStreamingCompleter())


def _grant_ids() -> Callable[[], str]:
    """Ids that differ per call, so a second record is never a duplicate."""
    numbers = count(1)
    return lambda: f"grant-{next(numbers)}"


def _grant_operations(sources: Sequence[HeldSource] = ()) -> GrantOperations:
    """The grant collaborator every ``Engine`` needs (ADR-0102 §7).

    Required rather than optional on the façade, like ``questions``: the four grant
    methods are on the Protocol, so an engine that could be built without them is one
    whose surface is conditionally present. Empty
    ``sources`` is the ordinary deployment — a reader ships disabled, so nothing is
    grantable until one is configured (ADR-0093 §7).
    """
    return GrantOperations(
        store=FakeSourceGrantStore(),
        sources=sources,
        id_factory=_grant_ids(),
        clock=lambda: AT,
    )


def _trust_ids() -> Callable[[], str]:
    """Deterministic ids for the trust records an ``Engine`` mints under test."""
    counter = count(1)
    return lambda: f"trust-{next(counter)}"


def _destination_trust_operations(
    *,
    store: FakeDestinationTrustStore | None = None,
    trail: AuditTrail | None = None,
) -> DestinationTrustOperations:
    """The destination-trust collaborator every ``Engine`` needs (ADR-0242 §2).

    Required rather than optional on the façade, on ``_recipient_grant_operations``'
    reason exactly: the three methods are on the Protocol, so an engine that could be
    built without them is one whose surface is conditionally present. Both seams
    default to fresh fakes — an empty trust store and a trail nothing has been
    recorded to — which is what a case not about the trust act wants.
    """
    return DestinationTrustOperations(
        store=FakeDestinationTrustStore() if store is None else store,
        trail=FakeAuditTrail() if trail is None else trail,
        id_factory=_trust_ids(),
        clock=lambda: AT,
    )


def _recipient_grant_operations(
    *,
    store: RecipientGrantStore | None = None,
    trail: AuditTrail | None = None,
    policy: ActionPolicy | None = None,
) -> RecipientGrantOperations:
    """The recipient-grant collaborator every ``Engine`` needs (ADR-0235 §4).

    Required rather than optional on the façade, on ``grant_operations``' argument:
    the five methods are on the Protocol, so an engine that could be built without
    them is one whose surface is conditionally present. The three seams default to
    fresh fakes, which is the shape almost every case here wants — a store with
    nothing in it, a trail nothing has been recorded to, and a policy that allows.
    """
    return RecipientGrantOperations(
        store=FakeRecipientGrantStore() if store is None else store,
        trail=FakeAuditTrail() if trail is None else trail,
        policy=FakeActionPolicy() if policy is None else policy,
        id_factory=_grant_ids(),
        clock=lambda: AT,
    )


def _connection_operations() -> ConnectionOperations:
    """The connection collaborator every ``Engine`` needs (ADR-0151 §10).

    Required rather than optional on the façade, on ``_grant_operations``' reason
    exactly: the five connection methods are on the Protocol, so an engine that
    could be built without them is one whose surface is conditionally present. The
    canonical fake is the subject, so a case that wants a live record, a pending
    one, or a keyring that raises scripts it through the provisioner's own switches
    rather than through a second double.
    """
    return ConnectionOperations(provisioner=FakeConnectionProvisioner())


#: Long enough that the fakes' instant tools finish inside it anywhere.
PATIENT = timedelta(seconds=30)

#: The episodic horizon the harness's capture stage stamps with (ADR-0074 §7).
RETENTION = timedelta(days=30)

#: The trace horizon the harness's maintenance operation sweeps against
#: (ADR-0119 §10). Deliberately *not* ``RETENTION``: the two are different
#: settings over different tiers, and a shared value would let a sweep against
#: the wrong one pass.
TRACE_RETENTION = timedelta(days=365)

#: ADR-0197 §7's routed-park lifetime, as ``Settings`` defaults it. Named here so a
#: case that advances the injected clock past it names one figure rather than two.
ROUTED_TTL = timedelta(minutes=15)

#: ADR-0250 §8's default, restated here so a case that pins a deadline reads the same
#: figure the composition root passes.
GOAL_QUESTION_TTL = timedelta(hours=72)

#: The engine's own default outstanding-confirmation ceiling, restated so a case that
#: wants backpressure can lower it without every other case naming a number.
DEFAULT_MAX_OUTSTANDING = 1024

CAPABILITY = "send_email"
PARAMETERS = {"to": "someone@example.com"}

#: The connected account an egress park in this module is bound to.
EGRESS_REFERENCE = "conn-0001"
EGRESS_IDENTITY = "work@example.com"
EGRESS_ENDPOINT = "test://endpoint/one"

#: A schema declaring ``to`` a destination-bearing argument, in ADR-0152 §3's two
#: keywords. It is what makes ``FakeEgressBinder`` derive a real binding for
#: :data:`PARAMETERS` rather than answer ``None``, so an egress park here is the
#: seam's own output and not a fixture's idea of one.
EGRESS_SCHEMA: Mapping[str, FrozenJson] = {
    "type": "object",
    "properties": {
        "to": {
            "type": "string",
            "x-egress-destination": "smtp",
            "x-egress-tier": "personal",
        }
    },
    "additionalProperties": False,
}


def tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """A declaration ``FakeActionPolicy`` allows outright (mirrors test_runner)."""
    fields: dict[str, object] = {
        "id": tool_id,
        "capability": CAPABILITY,
        "description": "Send an email.",
        "risk_level": RiskLevel.LOW,
        "reversibility": Reversibility.REVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NATURAL,
    }
    fields.update(overrides)
    return ToolDefinition(**with_phase_declaration(fields))  # type: ignore[arg-type]  # heterogeneous test kwargs


def confirmable(tool_id: str = "smtp") -> ToolDefinition:
    """A declaration the fake policy confirms: it discloses off-device."""
    return tool(tool_id, discloses=(DataTier.PERSONAL,))


def egress_confirmable(tool_id: str = "smtp") -> ToolDefinition:
    """A confirmable declaration whose ``to`` argument names a recipient.

    The same tool the fake policy confirms, plus ADR-0152 §3's schema keywords, so
    a runner holding a :class:`FakeEgressBinder` binds the call and the recorded
    ``CONFIRM`` carries an ``egress_binding``.
    """
    return tool(tool_id, discloses=(DataTier.PERSONAL,), parameters_schema=EGRESS_SCHEMA)


def bound_binder(tool_definition: ToolDefinition) -> FakeEgressBinder:
    """A binder holding ``tool_definition`` against one active connected account."""
    binder = FakeEgressBinder()
    binder.register_egress(
        tool_definition,
        reference=EGRESS_REFERENCE,
        identity=EGRESS_IDENTITY,
        transport_endpoint=EGRESS_ENDPOINT,
    )
    return binder


def plan_id(goal_id: str, ordinal: int) -> str:
    """The id a test planner mints for the ``ordinal``-th call of one turn.

    **Distinct per call, because ADR-0014 §2's "re-planning produces a *new*
    ``ActionPlan`` with a new ``id``" now binds within a turn** (ADR-0228 §3): a turn
    may call ``Planner.plan`` twice, both plans are persisted, and
    ``PlanStore.save_plan`` refuses a ``supersedes`` naming the saving plan's own id
    (ADR-0228 §5). A planner minting one id twice is non-conforming, and would fail
    its consumer for the planner's own defect.

    **The first call keeps the id these planners have always minted**, so nothing that
    named it moves.

    Args:
        goal_id: The goal the plan is for.
        ordinal: Which call of this turn, 1-based.

    Returns:
        The plan id.
    """
    return f"{goal_id}-plan" if ordinal == 1 else f"{goal_id}-plan-{ordinal}"


class OneStepPlanner:
    """A ``Planner`` that plans exactly one step **for the goal it is given**.

    Building the plan from the passed goal is what keeps ``plan.goal_id`` equal to
    the id the loop minted, so the façade's ``save_plan`` finds its goal. Structurally
    implements :class:`~ai_assistant.core.protocols.Planner`.

    **Its plan id is per call** (:func:`plan_id`). ``_calls`` is a class-level default
    that the first call shadows with an instance attribute, so every subclass keeps
    working whether or not it calls ``super().__init__()``.
    """

    _calls: int = 0

    def __init__(
        self,
        *,
        capability: str = CAPABILITY,
        parameters: Mapping[str, object] | None = None,
    ) -> None:
        self._capability = capability
        # Overridable so a case can drive a *shape* of arguments — a long
        # destination-bearing key naming a many-element array, for ADR-0178 §9's
        # expansion — without a second planner class.
        self._parameters = PARAMETERS if parameters is None else parameters

    async def plan(  # noqa: PLR0913 — the Planner Protocol's own parameter list; ADR-0230 §3 and ADR-0240 §7 each add one
        self,
        goal: GoalBrief,
        *,
        utterance: str,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
        read_outcomes: Sequence[ReadAskOutcome] = (),
        evidence: Sequence[EvidenceDigest] = (),
    ) -> PlannerOutput:
        # **One act proposed per call, and the step names it** (ADR-0265 §4). Every
        # declaration these cases drive is `side_effecting`, and ADR-0259 §2 refuses to
        # dispatch such a step whose plan cannot say which act it is an attempt at. A
        # *fresh* act each turn rather than the goal's existing one, because that is what
        # keeps a second turn over one goal a second dispatch: two acts the user asked
        # for, which is §2's own reading of "book another one just like it". A case about
        # the **reuse** — one act, two turns — says so, and
        # `test_engine_effect_claim.py` is where it says it.
        label = f"A{len(goal.actions) + 1}"
        step = PlanStep(
            id="step-1",
            intent="send the note",
            capability=self._capability,
            parameters=self._parameters,  # type: ignore[arg-type]  # heterogeneous test arguments
            intended_action=label,
        )
        self._calls += 1
        return PlannerOutput(
            actions=(ProposedAction(intent="send the note"),),
            plan=ActionPlan(
                id=plan_id(goal.goal_id, self._calls),
                goal_id=goal.goal_id,
                steps=(step,),
                created_at=AT,
            ),
        )


class NoStepPlanner:
    """A ``Planner`` that ends a turn at an empty plan.

    Its plan id is per call, for :class:`OneStepPlanner`'s reason (:func:`plan_id`).
    """

    _calls: int = 0

    async def plan(  # noqa: PLR0913 — the Planner Protocol's own parameter list; ADR-0230 §3 and ADR-0240 §7 each add one
        self,
        goal: GoalBrief,
        *,
        utterance: str,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
        read_outcomes: Sequence[ReadAskOutcome] = (),
        evidence: Sequence[EvidenceDigest] = (),
    ) -> PlannerOutput:
        self._calls += 1
        return PlannerOutput(
            plan=ActionPlan(
                id=plan_id(goal.goal_id, self._calls), goal_id=goal.goal_id, steps=(), created_at=AT
            )
        )


class RecordingBeliefStore(FakeMemoryStore):
    """A store that records the arguments each ``list_beliefs`` call reached it with.

    Lets a test assert the *relay* — that the façade passes the filters and the page
    through untouched, and that what arrives is a snapshot rather than the caller's
    own sequence — without inferring it from which records came back.
    """

    def __init__(self, *, now: Callable[[], datetime]) -> None:
        super().__init__(now=now)
        self.calls: list[
            tuple[Sequence[BeliefBand] | None, Sequence[MemoryKind] | None, int, int]
        ] = []

    async def list_beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        self.calls.append((bands, kinds, limit, offset))
        return await super().list_beliefs(bands=bands, kinds=kinds, limit=limit, offset=offset)


class _Default:
    """The sentinel that tells "the harness picks one" from an explicit ``None``.

    ADR-0200 lets an engine be built with **no** speech seams — a deployment with
    no models — and refuses one built with exactly one of the two. A default of
    ``None`` would make both of those shapes unreachable from this harness, so
    ``None`` is passed through literally and this is what "unspecified" looks like.
    """


_DEFAULT: Final = _Default()


#: The canonical destination set a search of this harness's deployment binds to
#: (ADR-0238 §2, §5). ``tools/web_search.py`` declares the ``origin`` argument
#: ``x-egress-destination: "https"``, so a search binding's spans carry exactly this one
#: destination and ``EgressBinding.canonical_destination_set`` answers exactly this
#: tuple — which ``tests/app/test_search_destinations.py`` asserts against a binding the
#: real seam derived rather than leaving as a claim here.
SEARCH_DESTINATIONS: Final = (
    CanonicalDestination(
        protocol=DestinationProtocol.HTTPS, canonical=f"{DEFAULT_SEARCH_ORIGIN}:443"
    ),
)


class Harness:
    """A wired :class:`Engine` and the fakes behind it, for assertions."""

    def __init__(  # noqa: PLR0913 — one knob per fake; that is what a harness is
        self,
        *,
        planner: object | None = None,
        # ADR-0250 §4's seam, so a case can script what the association decided. The
        # default is `FRESH` — "the turn opens a new goal" — which is exactly what
        # every turn did before ADR-0250 §19's M3, so a case that says nothing about
        # association is unchanged by it. The **fake's** own default is `UNDECIDED`
        # (§4's decline), which is right for a double and wrong for a harness whose
        # cases are about something else.
        associator: FakeGoalAssociator | None = None,
        context: FakeContextProvider | None = None,
        composing: ComposingStage | None = None,
        informational_events: InformationalEventStage | None = None,
        tools: tuple[ToolDefinition, ...] = (),
        policy: FakeActionPolicy | None = None,
        recipient_grants: RecipientGrantStore | None = None,
        memory: FakeMemoryStore | None = None,
        conversation_store: FakeConversationStore | None = None,
        # ADR-0238's remaining knob. `destination_trust` empty is `origin/main`'s
        # state and ADR-0238's own exit note. It no longer decides a search's standing
        # — ADR-0247 §1 takes that from the registration — and the per-conversation
        # call bound it used to sit beside is removed entire (ADR-0247 §5).
        destination_trust: FakeDestinationTrustStore | None = None,
        closers: Sequence[object] = (),
        loop_id_factory: Callable[[], str] | None = None,
        feedback: object | None = None,
        # ADR-0230 §3's seam, so an engine-level case can drive a turn that **fetches**
        # — which is what §14 item 10 needs and what no loop-level case can reach: the
        # stamp it asserts is on a *captured episode*, and the consequence it asserts
        # is a *later* turn's egress ruling. `None` is the default and is every other
        # case's deployment: no root configured, so no file is nameable.
        fetcher: object | None = None,
        # ADR-0231 §17's Lane 5 seam, so an engine-level case can drive a turn that
        # **searches** — which is what §18 item 2 needs and what no loop-level case can
        # reach: the stamp it asserts is on a *captured episode*, and the consequence
        # it asserts is a *later* turn's egress ruling. `None` is the default and is
        # every other case's deployment: no search account connected, so §13's
        # disposition for any `WEB_SEARCH` ask is `NOT_CONFIGURED`.
        search: SearchServicer | None = None,
        # ADR-0260 §12's L3 seam, so an engine-level case can drive a turn that reads a
        # **forecast** — which is what §13's arm (h) needs and what no loop-level case
        # can reach: the field it asserts is on the `TurnOutcome`, and the statement
        # beside it is assembled at the capture point. `None` is the default and is
        # every other case's deployment: no forecast provider configured, so §8's
        # disposition for any `FORECAST_READ` ask is `NOT_CONFIGURED`.
        forecast: ForecastServicer | None = None,
        # ADR-0254 §20's Lane 1 and Lane 3 seams, wired **together or not at all**: the
        # writer that proposes a row (`StepRunner`) and the reader that renders it
        # (`AuthorizationOperations`) are given the **same** store, which is what makes
        # "the confirmation shows what the answer would establish" a property of the
        # wiring rather than of two tables that happen to agree.
        #
        # `None` is the default and is every other case's deployment: no store wired, so
        # `_propose` writes nothing, every `Confirmation` carries `authorization` `None`,
        # the listing answers empty and the revocation answers `NO_SUCH_AUTHORIZATION` —
        # which is exactly what is true of a deployment holding no rows. A case that
        # wires one therefore changes no other case's behaviour.
        authorizations: FakeGoalAuthorizationStore | None = None,
        # ADR-0262 §3's one new collaborator, which the composition root gives the engine
        # as the **third face** of the store above (ADR-0254 §16) — so the default here
        # is that same object, and an engine wired with no store resolves no row and
        # leaves every criterion `unestablished`, which is that deployment's own truth.
        #
        # **The override exists because the comparison's operands and the path that
        # writes them are two different lanes' subjects.** ADR-0254 §20 drives the
        # establishment end to end; a case about §4's limbs needs the row the comparison
        # reads to be a fact it chose, not one it had to establish first.
        resolution: AuthorizationResolution | None = None,
        coverage_answers: CoverageAnswers | None = None,
        # ADR-0256 §1's third rung, which `StepRunner` reads when an act names no
        # instant and the goal carries no deadline. Only a case wiring `authorizations`
        # can reach it.
        episode_retention: timedelta | None = None,
        # ADR-0244 §18's Lane 1 seam, so an engine-level case can drive a **parked**
        # read end to end — which is the only level it can be driven at: the question is
        # assembled at the capture point, the answer runs through `resume`, and the
        # continuation is a turn. `None` is the default and is the deployment this lane
        # ships: no store wired, so no servicing writes a park and §1's third clause is
        # the whole of what every `CONFIRM` then is. A case wiring one passes the **same
        # object** to the `SearchServicer` it builds, which is ADR-0244 §18's
        # one-instance obligation held by the case rather than by this harness.
        parked_reads: FakeParkedReads | None = None,
        queue_limit: int = 50,
        drain_timeout: timedelta | None = None,
        traces: FakeTraceRetention | None = None,
        trace_sink: FakeTraceSink | None = None,
        trace_retention: timedelta | None = TRACE_RETENTION,
        binder: EgressBinder | None = None,
        plans: FakePlanStore | None = None,
        tool_handler: FakeToolImplementation | None = None,
        trail: ConsumingTrail | None = None,
        reads: SourceReadTrail | None = None,
        routing: RoutingStage | None = None,
        # ADR-0276's understanding stage, wired as the composition root wires it with
        # §7's version bound beside it. `None` is every other case's deployment: no
        # stage, so every capture records `not_reached` exactly as before step 3.
        understanding: UnderstandingStage | None = None,
        understanding_version_limit: int | None = 8,
        # ADR-0282's windows stage. `None` wires one over this harness's store wherever
        # understanding is wired, as the composition root does.
        windows: WindowsStage | None = None,
        # ADR-0281's recall stage. `None` is every other case's deployment: no recall,
        # so every pass runs exactly as it did before recall was wired.
        recall: RecallStage | None = None,
        # ADR-0300 §6's story store, candidates and story-links stage. `None` is every
        # other case's deployment: no story is read or written, and no stories section
        # is rendered, so every pass runs exactly as it did before §6 was built.
        stories: StoryStore | None = None,
        story_candidates: StoryCandidates | None = None,
        story_links: StoryLinksStage | None = None,
        # ADR-0303 §10:2's bound on the story summary view's notes.
        story_summary_notes: int = DEFAULT_STORY_SUMMARY_VIEW_NOTES,
        # ADR-0300 §9:3's matters pass. `None` is every other case's deployment:
        # `decide_story_flags` refuses, and nothing else reads it.
        matters_pass: MattersPass | None = None,
        # ADR-0259 §4's turn-start pass and §3's check, wired **together or not at
        # all** — one object holds both. `None` is the default and is every other
        # case's deployment: no stage wired, so no goal's residual is repaired and the
        # pipeline is exactly what it was before that decision, which is why a case
        # that wires one changes no other case's behaviour.
        reconciliation: ReconciliationStage | None = None,
        transcriber: SpeechTranscriber | None | _Default = _DEFAULT,
        synthesizer: SpeechSynthesizer | None | _Default = _DEFAULT,
        speakable_attested_sources: frozenset[str] = frozenset(),
        max_spoken_audio_bytes: int = DEFAULT_MAX_SPOKEN_AUDIO_BYTES,
        routed_confirmation_ttl: timedelta = ROUTED_TTL,
        # ADR-0250 §8's one `Settings` field, so a case can pin the deadline it
        # computes and the figure the engine refuses at construction.
        goal_question_ttl: timedelta = GOAL_QUESTION_TTL,
        max_outstanding_confirmations: int = DEFAULT_MAX_OUTSTANDING,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        notification_outbox: DeliveryOutbox | None = None,
        now: Clock | None = None,
        id_factory: Callable[[], str] | None = None,
        epoch_factory: Callable[[], str] | None = None,
        # ADR-0293 §6's reader, which runs every activation through the phases (ADR-0309
        # §2:6), so it is wired only beside them. `None`, the default, is on wherever
        # `phases` is given and off otherwise: a case holding the medium alone, or a
        # surface no activation reaches, builds no phases.
        chat_reader: bool | None = None,
        # ADR-0309 §2:6's phases, built over this harness's own stores once they exist.
        # `None` builds none: no activation runs, so a case that drives one wires them.
        phases: Callable[[Harness], PhasePath] | None = None,
        # ADR-0314 §4:4's sink, which the controller of every pass writes through.
        # `None` is every other case's deployment: the diagnostic record off.
        diagnostics: DiagnosticSink | None = None,
    ) -> None:
        # ADR-0197's knobs. The recorder lives on the *stage* (§9), so a case that wants
        # to read the rows builds its own ``RoutingStage(model=…, recorder=…)`` and keeps
        # the recorder; there is nothing for this harness to hold. Every other case in
        # this module gets no stage at all, which is the deployment the pipeline had
        # before ADR-0197 and is why they are unaffected by it.
        self.routing = routing
        self.reconciliation = reconciliation
        # ADR-0200's two seams, wired **together** or not at all — the engine refuses
        # half a pipeline. Defaulted to the canonical fakes so every spoken case in
        # this suite has a subject, and kept on the harness so a case can read what
        # reached each seam, arm a failure, or narrow a `formats` set.
        self.transcriber: SpeechTranscriber | None = (
            FakeSpeechTranscriber() if isinstance(transcriber, _Default) else transcriber
        )
        self.synthesizer: SpeechSynthesizer | None = (
            FakeSpeechSynthesizer() if isinstance(synthesizer, _Default) else synthesizer
        )
        # The **injected** clock (ADR-0009), settable so ADR-0197 §7's lifetime is
        # pinned by advancing it rather than by waiting: "a test advances it rather
        # than waits", and a case that reclaimed a slot before resuming would pass
        # against an implementation whose expiry is only ever noticed by housekeeping.
        self.clock: Clock = (lambda: AT) if now is None else now
        # A knob for the same reason ``trail`` is one below: ADR-0249 §6 makes the six
        # phases "six observable transitions", and three of a turn's six are commits a
        # case can only see by holding the store that took them. The default stays the
        # canonical fake, which is what every other case here wants.
        self.plans = FakePlanStore(now=lambda: AT) if plans is None else plans
        # ``trail`` is a knob because the audit surface's own reader cases need a
        # store that holds **bytes**: ADR-0184 §10 puts the origin-unrecorded row's
        # read half in each implementation's own tests, "because it is a property of
        # a store that persists a serialised payload and rebuilds it, and a fake
        # holding objects has no bytes for a shared case to seed". The default stays
        # the canonical fake, which is what every other case here wants.
        self.trail: ConsumingTrail = FakeAuditTrail() if trail is None else trail
        # One object as both registry and invoker, as ADR-0029 §8 requires.
        # The seam claims through the **same** trail the runner records rulings
        # into (ADR-0192 §9's wiring clause); a second one would refuse every claim.
        # A knob for the same reason ``plans`` is one: ADR-0249 §5 makes ``ANSWERED``
        # assert that **no step failed**, and a case about that needs a tool that fails
        # rather than the one that succeeds. The default is unchanged.
        self.invoker = FakeToolInvoker(
            [
                (definition, _succeeds if tool_handler is None else tool_handler)
                for definition in tools
            ],
            ledger=self.trail,
            gate=self.trail,
        )
        self.policy = policy if policy is not None else FakeActionPolicy()
        self.memory = memory if memory is not None else FakeMemoryStore(now=lambda: AT)
        # The capture/lifecycle stage over the *same* memory store, as the
        # composition root wires it (ADR-0074 §9). Kept on the harness so a test can
        # read what capture actually recorded, and so a second façade over the same
        # durable state shares one stage.
        # A knob for the same reason ``memory`` is one: ADR-0074 §9's store faults and
        # ADR-0205 §3's refusals are properties of what the *store* does, and a case
        # about one needs a store it can arm or count. The default is the canonical
        # fake, which is what every other case here wants.
        self.conversation_store = (
            FakeConversationStore(now=lambda: AT)
            if conversation_store is None
            else conversation_store
        )
        #: ADR-0238 §14's store, and ADR-0242 §4's: **the caller's where one was given**,
        #: so the engine's three trust operations and the search footing below hold the
        #: *same* object. A second assignment here would leave a case's seeded records
        #: and armed faults reaching the servicing site and never the engine — the two
        #: halves of one journey looking at two stores.
        self.destination_trust = (
            FakeDestinationTrustStore() if destination_trust is None else destination_trust
        )
        self.conversations = ConversationLifecycle(
            conversations=self.conversation_store,
            memory=self.memory,
            retention=RETENTION,
            now=lambda: AT,
        )
        self.ids = iter(f"d-{n}" for n in range(1, 100))
        self.handles = iter(f"tok-{n}" for n in range(1, 100))
        # Kept on the harness so a test can read what reached the loop.
        self.feedback = feedback if feedback is not None else FakeFeedbackProcessor()
        self.policy_for_writer = FakeMemoryPolicy()

        writer = FakeMemoryWriter(store=self.memory, policy=self.policy_for_writer, now=lambda: AT)
        # **One** write stage over that writer and one deferral queue, shared by every
        # producer's stage, as the composition root wires it (ADR-0078 §3). Both are
        # kept on the harness: a test reads back what was parked, and the question
        # surface answers it.
        self.deferrals = FakeDeferralStore(now=lambda: AT, queue_limit=queue_limit)
        self.writes = MemoryWriteStage(writer=writer, deferrals=self.deferrals)
        self.questions = QuestionStage(
            writer=writer, deferrals=self.deferrals, memory=self.memory, now=lambda: AT
        )
        # ADR-0185 §5's trail. **A whole trail rather than the bare recorder, since
        # ADR-0186 §10.** The
        # engine now holds the wide seam as well, and the composition root passes
        # *one* object into all four positions — narrowed to `SourceReadRecorder` at
        # each driver, whole at the façade. `FakeSourceReadTrail` satisfies both
        # Protocols structurally, which is ADR-0185 §4's arrangement modelled in the
        # double; a harness holding two objects here would let `recent_reads` answer
        # about a store the drivers never wrote to, which is precisely the wiring
        # mistake no type can catch.
        #
        # A knob for ``trail``'s reason, one store over: the read surface's own cases
        # need a **durable** trail, because the order ``export_reads`` reverses comes
        # from the store's ``ORDER BY`` rather than from a Python list, and a fake
        # cannot exhibit a wrong one.
        self.reads: SourceReadTrail = FakeSourceReadTrail() if reads is None else reads
        self.loop = loop = LearningLoop(
            # A knob because ADR-0204 §8's sixth case needs a *placed* facet in the
            # turn's supply — the calendar — to show that a facet ADR-0199 §3 places
            # leaves the stamp `False`, and the default context carries none at all.
            context=FakeContextProvider() if context is None else context,
            memory=self.memory,
            writes=self.writes,
            planner=planner if planner is not None else OneStepPlanner(),  # type: ignore[arg-type]
            feedback=self.feedback,  # type: ignore[arg-type]
            now=lambda: AT,
            id_factory=loop_id_factory if loop_id_factory is not None else _goal_ids("g"),
            # The same object the runner below resolves against (ADR-0211 §3):
            # a loop told one vocabulary while selection resolved against another
            # could plan a step the selecting registry never advertised.
            registry=self.invoker,
            fetcher=fetcher,  # type: ignore[arg-type]  # the harness's own heterogeneous knobs
            search=search,
            # ADR-0260 §7: the one servicing site, handed the one forecast servicer.
            # The composition root wires it into that site and into nothing else, and
            # this harness holds it nowhere else either.
            forecast=forecast,
            # ADR-0247 §1: the registration fact wired into the one servicing path,
            # in place of the trust store ADR-0238 §14 put there — over the **same**
            # `ConversationStore` the capture stage holds, because §8 rests the
            # increment's atomicity on that one object's per-conversation exclusion.
            #
            # **Derived from the searcher and not offered as a knob**, which is the
            # composition root's own arithmetic: `app/composition.py` builds the
            # servicer and reads `registered` from the same two `Settings` fields, so a
            # harness wiring a servicer *is* a deployment holding a registration and
            # one wiring none is not. A knob would let a case arrange a deployment that
            # cannot exist.
            footing=lambda conversation_id: SearchFooting(
                conversation_id=conversation_id,
                registered=search is not None,
            ),
        )
        runner = StepRunner(
            plans=self.plans,
            registry=self.invoker,
            policy=self.policy,
            trail=self.trail,
            executor=StepExecutor(
                plans=self.plans, registry=self.invoker, invoker=self.invoker, now=lambda: AT
            ),
            now=lambda: AT,
            id_factory=lambda: next(self.ids),
            # The egress binding seam (ADR-0152 §1), wired only where a case needs
            # a *bound* call: without one ``bind`` answers ``None`` and every
            # request carries ``egress_binding=None``, which is the ordinary
            # non-egress shape almost every case here is about.
            binder=binder,
            # ADR-0254 §15's single writer of an `Authorization`, over the store this
            # harness also hands the reader below.
            authorizations=authorizations,
            # Condition 6's **one** implementation (ADR-0270 §1), so what a proposal
            # here is refused or allowed by is the real comparison and not a
            # configuration. `ThresholdActionPolicy` holding no `GoalQuotes` answers
            # unmet for every `MONEY` member, which is the fail-closed direction and
            # the shape of this harness — no goal here states a bound ADR-0266 §4
            # reads, so every coverage the writer puts to it is empty. A case that needs the answer
            # controlled, counted or faulted passes `FakeCoverageAnswers` instead.
            coverage_answers=(
                ThresholdActionPolicy() if coverage_answers is None else coverage_answers
            ),
            episode_retention=episode_retention,
        )
        # The trace store's *deletion* seam, and only that: ADR-0119 §7 gives the
        # engine the purge and withholds the walk, so the harness hands it a
        # ``FakeTraceRetention`` rather than the whole store — a fake that could
        # walk would let a test assert a reach the production wiring does not have.
        self.traces = traces if traces is not None else FakeTraceRetention()
        # The trace store's *append* seam, and only that (ADR-0119 §7): the engine
        # emits its own ``OPERATION`` trace through a ``FakeTraceSink``, which can
        # be appended to and cannot be walked. Separate from ``traces`` above
        # because the capabilities are separate — the production wiring narrows one
        # object twice, and a harness handing over one fake for both would let a
        # case assert a reach the engine does not have.
        self.trace_sink = trace_sink if trace_sink is not None else FakeTraceSink()
        self.trace_retention = trace_retention
        # The terminal composing stage (ADR-0170 §2), overridable so a case can
        # script what the composer does — refuse, come back blank, or contradict
        # the step account — without a second harness.
        self.composing = composing if composing is not None else _composing()
        #: The recipient-grant store the five ADR-0235 §7 operations read and write,
        #: held here so a case can seed it, put it at its ceiling, or make its writes
        #: fail — the states the establishing act's carrier is about.
        self.recipient_grants: RecipientGrantStore = (
            FakeRecipientGrantStore() if recipient_grants is None else recipient_grants
        )
        #: ADR-0244 §3's store, kept so a case can read the park a servicing wrote, seed
        #: one, or arm its writes to fail — the three states ADR-0244 §1's third clause
        #: and §19's arms are about.
        self.parked_reads = parked_reads
        #: The operations the engine reaches it through (ADR-0244 §5, §6, §11), over the
        #: **same** conversation index the capture stage holds: §6's clause 2 reads the
        #: conversation from it (ADR-0247 §6), and a second store over the same rows
        #: could answer about a conversation this one never began.
        self.parked_read_operations = ParkedReadOperations(
            store=parked_reads,
            conversations=self.conversation_store,
            search=search,
            clock=self.clock,
        )
        self.associator = (
            FakeGoalAssociator(answer=GoalAssociation(verdict=AssociationVerdict.FRESH))
            if associator is None
            else associator
        )
        self.engine = Engine(
            informational_events=informational_events,
            associator=self.associator,
            composing=self.composing,
            grant_operations=_grant_operations(),
            # The harness's **own** trail and policy, so the act this surface performs
            # is recorded where every other ruling is and ruled on by the same gate
            # (ADR-0235 §3). A second trail here would let a case establish a grant
            # from a confirmation `recent_decisions` cannot see.
            recipient_grant_operations=RecipientGrantOperations(
                store=self.recipient_grants,
                trail=self.trail,
                policy=self.policy,
                id_factory=lambda: next(self.ids),
                clock=self.clock,
                # ADR-0244 §5's eighth condition, decided through the **same**
                # operations the engine answers a park through — so a case that parks a
                # read and then asks `grantable_decisions` sees one store and not two.
                parked_reads=self.parked_read_operations,
            ),
            # The harness's own trail again (ADR-0242 §1): the trust act reads the
            # decision it rides from the trail every other operation here records to,
            # so a case cannot trust a decision `recent_decisions` cannot see.
            destination_trust_operations=DestinationTrustOperations(
                store=self.destination_trust,
                trail=self.trail,
                id_factory=_trust_ids(),
                clock=lambda: AT,
            ),
            connection_operations=_connection_operations(),
            # ADR-0254 §11's read side, over the **same** store the runner writes
            # through and the **same** plan store the goal's statement is read from.
            authorization_operations=(
                None
                if authorizations is None
                else AuthorizationOperations(
                    authorizations=authorizations, plans=self.plans, now=self.clock
                )
            ),
            # ADR-0262 §3's read seam, narrowed at the engine's own annotation to
            # `resolve(id)` and nothing else — the same object the runner writes
            # through unless a case named another.
            authorizations=authorizations if resolution is None else resolution,
            loop=loop,
            runner=runner,
            reconciliation=reconciliation,
            plans=self.plans,
            trail=self.trail,
            spend=self.trail,
            reads=self.reads,
            memory=self.memory,
            deferrals=self.deferrals,
            traces=self.traces,
            trace_sink=self.trace_sink,
            trace_retention=trace_retention,
            conversations=self.conversations,
            questions=self.questions,
            closers=tuple(closers),  # type: ignore[arg-type]
            id_factory=(lambda: next(self.handles)) if id_factory is None else id_factory,
            # The handle epoch (#1644), a knob so a restart case can hand two engines
            # two epochs it chose rather than two real UUIDs and the hope they differ.
            # Defaulted per harness instance, so two harnesses are two engines.
            epoch_factory=(lambda: "epoch") if epoch_factory is None else epoch_factory,
            routing=self.routing,
            understanding=understanding,
            understanding_version_limit=understanding_version_limit,
            windows=(
                WindowsStage(episodes=RecentEpisodes(memory=self.memory, limit=10))
                if windows is None and understanding is not None
                else windows
            ),
            recall=recall,
            stories=stories,
            story_summary_notes=story_summary_notes,
            story_candidates=story_candidates,
            story_links=story_links,
            matters_pass=matters_pass,
            # ADR-0244 §5, §6, §11: the enumeration, the answer and the cancellation,
            # over the store above. Wired unconditionally, exactly as the composition
            # root wires the operations object — what varies by deployment is the
            # *store* behind it, which is `None` here unless a case wired one.
            parked_reads=self.parked_read_operations,
            transcriber=self.transcriber,
            synthesizer=self.synthesizer,
            speakable_attested_sources=speakable_attested_sources,
            max_spoken_audio_bytes=max_spoken_audio_bytes,
            routed_confirmation_ttl=routed_confirmation_ttl,
            goal_question_ttl=goal_question_ttl,
            max_outstanding_confirmations=max_outstanding_confirmations,
            # ADR-0085 §8c's contract limit, a knob so a case can put a *result* over
            # it cheaply — which is the only way ADR-0200 §4's fourth degradation and
            # its one-step re-measure are reachable at all.
            max_payload_bytes=max_payload_bytes,
            # The whole harness runs at one instant unless a case moves it, so the
            # horizon the sweep measures back from is a figure a case can name
            # (ADR-0119 §10) — and ADR-0197 §7's routed-park lifetime is a figure a
            # case can *advance* past.
            now=self.clock,
            drain_timeout=drain_timeout,
            # ADR-0131 §3's durable delivery queue. ``None`` by default, which is the
            # in-process deployment that serves no poll — and a knob because an
            # *absence* is only assertable against an outbox that would have recorded
            # the call: ADR-0207's park cases pin that the spoken path acquired no
            # edge to it, which a subject holding no outbox at all cannot show.
            notification_outbox=notification_outbox,
            chat_reader=phases is not None if chat_reader is None else chat_reader,
            phases=None if phases is None else phases(self),
            diagnostics=diagnostics,
        )


async def _succeeds(parameters: object, *, idempotency_key: str | None) -> None:
    """A tool that does nothing and succeeds."""


# --- durable recovery of a parked confirmation (ADR-0052) ---------------


def _fresh_facade(harness: Harness) -> Engine:
    """A new ``Engine`` over ``harness``'s durable state, with an empty in-process table.

    The fakes are the same instances, so plan/execution state and the audit trail
    persist — this stands in for a restarted process whose ``_parked`` table starts
    empty (ADR-0052 §1). It reuses the harness's stage objects, which already hold
    the same ``plans`` and ``trail``.
    """
    return Engine(
        chat_reader=False,
        associator=FakeGoalAssociator(answer=GoalAssociation(verdict=AssociationVerdict.FRESH)),
        composing=_composing(),
        grant_operations=_grant_operations(),
        recipient_grant_operations=_recipient_grant_operations(),
        destination_trust_operations=_destination_trust_operations(),
        connection_operations=_connection_operations(),
        # ADR-0254 §11's recovery clause needs this across the restart: "A restart
        # between the question and the answer recovers the row and renders the same
        # projection", which a facade holding no read side could not do.
        authorization_operations=harness.engine._authorization_operations,
        loop=harness.engine._loop,
        runner=harness.engine._runner,
        plans=harness.plans,
        trail=harness.trail,
        spend=harness.trail,
        reads=harness.reads,
        memory=harness.memory,
        deferrals=harness.deferrals,
        traces=harness.traces,
        trace_sink=harness.trace_sink,
        trace_retention=harness.trace_retention,
        conversations=harness.conversations,
        questions=harness.questions,
        id_factory=lambda: next(harness.handles),
    )


async def test_aclose_is_idempotent() -> None:
    """A second close drains nothing and closes nothing again."""
    calls: list[str] = []

    async def close() -> None:
        calls.append("closed")

    harness = Harness(closers=(close,))
    await harness.engine.aclose()
    await harness.engine.aclose()
    assert calls == ["closed"]


async def test_calls_are_refused_once_shutdown_has_begun() -> None:
    """After aclose no new work is accepted (§2 stops accepting)."""
    harness = Harness(tools=(tool(),))
    await harness.engine.aclose()
    with pytest.raises(RuntimeError, match="shutting down"):
        await harness.engine.beliefs()


# --- the two-phase drain (ADR-0083 §4) ---------------------------------


async def test_a_drain_with_nothing_in_flight_closes_at_once() -> None:
    """The ordinary case: an idle hub does not wait out its budget to stop."""
    closed = asyncio.Event()

    async def close() -> None:
        closed.set()

    harness = Harness(closers=(close,), drain_timeout=timedelta(seconds=30))

    await asyncio.wait_for(harness.engine.aclose(), timeout=5)

    assert closed.is_set()


async def test_the_drain_records_which_phase_it_ended_in() -> None:
    """The engine says how it shut down, so the hub can report it (#559).

    ADR-0083 §4 leaves phase B's await **unbounded**, which is why "which phase" is
    the field an operator reads first: it is also "was this bounded at all". The
    engine is the only layer that can answer — the hub sees one ``aclose()`` — so it
    records the answer as it goes.

    Its companion below asserts the other direction, because a property that only
    ever reports the happy value is indistinguishable from a constant. A drain that
    quiesced must **not** claim work was cancelled, and vice versa. They are two
    tests rather than one only because narrowing a property across two ``is``
    assertions makes the second unreachable to the type checker.
    """
    harness = Harness(drain_timeout=timedelta(seconds=30))
    # Read into locals rather than asserted on the property twice: narrowing the
    # member expression would make the second comparison unreachable to mypy while
    # leaving the test just as true.
    before = harness.engine.drain_phase

    await harness.engine.aclose()
    after = harness.engine.drain_phase

    assert before is DrainPhase.NOT_RUN
    assert after is DrainPhase.QUIESCED


# --- the maintenance surface (ADR-0083 §8) -----------------------------


def _counting_purges(harness: Harness, *, records: int, questions: int) -> dict[str, int]:
    """Replace both stores' sweeps with counters, on the very instances wired in.

    The *semantics* of each sweep — which rows are past their deadline, and the two
    anchors ADR-0078 §2 gives the deferral queue — belong to the stores and are held
    to their Protocols by the shared conformance suites. What is unproven anywhere
    else, and is the whole of ADR-0078 §10 item 8, is that **one** façade operation
    reaches **both** of them and reports each count as its own. Distinct return
    values are what make the second half checkable: equal ones would pass for an
    implementation that swept one store twice.
    """
    calls = {"records": 0, "questions": 0}

    async def purge_memory() -> int:
        calls["records"] += 1
        return records

    async def purge_questions() -> int:
        calls["questions"] += 1
        return questions

    harness.memory.purge_expired = purge_memory  # type: ignore[method-assign]
    harness.deferrals.purge = purge_questions  # type: ignore[method-assign]
    return calls


async def test_the_purge_sweeps_both_tier_one_stores_and_reports_each_count() -> None:
    """ADR-0083 §8's maintenance surface, and ADR-0078 §10 item 8 taken literally.

    One façade operation over **two** stores, because the deferral queue's purge "is
    wired wherever ``purge_expired`` is wired and inherits the same fate", and
    "inventing a second sweeping mechanism for one store would be the thing that has
    to be undone at leg 5". A version that swept only memory would satisfy the name
    and leave ADR-0078 §1's exposure cap unkept for exactly the rows that hold the
    user's own words.
    """
    harness = Harness()
    calls = _counting_purges(harness, records=3, questions=2)

    report = await harness.engine.purge_expired()

    assert (report.records, report.questions) == (3, 2)
    assert calls == {"records": 1, "questions": 1}


async def test_the_purge_reaches_the_same_deferral_queue_the_question_surface_answers() -> None:
    """One queue, or the sweep reclaims rows nobody can see (ADR-0078 §1, §3).

    A composition-root single-instance obligation no type can state, of the same
    shape as ``plans`` and ``trail``. Wired to a second queue, ``purge_expired``
    would report a cap kept while the rows the user's own questions live in kept
    growing.
    """
    harness = Harness()

    assert harness.engine._deferrals is harness.deferrals
    assert harness.engine._deferrals is harness.questions._deferrals
    assert harness.engine._deferrals is harness.writes._deferrals


async def test_the_purge_is_drained_before_shutdown_closes_resources() -> None:
    """It is a public method, so it is tracked — which is what closes §8's race.

    ADR-0083 §8's whole argument for a scheduler living *above* the composition root
    rests on this: "``Engine._tracked`` wraps every public method, so a job whose
    body is ``engine.<operation>()`` has its underlying store work in ``_inflight``
    already, and the drain waits for it exactly as it waits for a ``converse``."
    Untracked, the sweep would be a store call racing the ``close()`` that follows.

    **The closer records what it saw**, rather than the test merely looking at a
    moment: a bare "not closed yet" assertion after one loop turn passes for an
    untracked sweep too, because the drain task has not been scheduled by then. The
    only claim that holds regardless of how many turns elapse is the closer's own —
    *was the sweep still gated when I ran?*
    """
    entered = asyncio.Event()
    release = asyncio.Event()
    closed = asyncio.Event()
    closed_while_sweeping = False

    async def close() -> None:
        nonlocal closed_while_sweeping
        closed_while_sweeping = not release.is_set()
        closed.set()

    async def gated_purge() -> int:
        entered.set()
        await release.wait()
        return 0

    harness = Harness(closers=(close,))
    harness.memory.purge_expired = gated_purge  # type: ignore[method-assign]

    sweeping = asyncio.ensure_future(harness.engine.purge_expired())
    await entered.wait()
    closing = asyncio.ensure_future(harness.engine.aclose())
    # Several turns, so the drain task is scheduled and runs as far as it can. An
    # untracked sweep would let it reach the closers here.
    for _ in range(5):
        await asyncio.sleep(0)

    assert not closed.is_set(), "a resource was closed while a sweep was still running"
    release.set()
    await sweeping
    await closing
    assert closed.is_set()
    assert closed_while_sweeping is False


async def test_the_purge_is_refused_once_shutdown_has_begun() -> None:
    """The refusal the scheduler reads as *stop* rather than as a job failure (§8).

    Its message is the shared constant, so the scheduler's recognition of it cannot
    drift from what is raised here — two spellings of one message is a seam that
    fails silently, leaving the scheduler retrying against an engine that will never
    accept work again.
    """
    harness = Harness()
    await harness.engine.aclose()

    with pytest.raises(RuntimeError) as raised:
        await harness.engine.purge_expired()

    assert str(raised.value) == ENGINE_SHUTTING_DOWN


async def test_a_failing_memory_sweep_does_not_reach_the_deferral_sweep() -> None:
    """Nothing sequences the two, so a half-done sweep must not report success.

    The next tick simply re-runs both — a missed sweep is never a correctness bug
    (ADR-0007 §2) — and swallowing the first failure to reach the second would claim
    a sweep that half happened. The scheduler logs the failure and retries (§7).
    """
    harness = Harness()
    calls = _counting_purges(harness, records=0, questions=0)

    async def refuses() -> int:
        msg = "the memory store is unreadable"
        raise MemoryStoreError(msg)

    harness.memory.purge_expired = refuses  # type: ignore[method-assign]

    with pytest.raises(MemoryStoreError):
        await harness.engine.purge_expired()

    assert calls["questions"] == 0


# --- the trace horizon, swept by that same operation (ADR-0119 §10) -----


def _aged(days: int) -> EvaluationTrace:
    """A trace stamped ``days`` before the harness's instant."""
    return evaluation_trace("engine", occurred_at=AT - timedelta(days=days))


async def test_the_purge_sweeps_the_trace_store_as_its_third_call() -> None:
    """ADR-0119 §10 taken literally, and ADR-0078 §10 item 8 reaching a third store.

    "ADR-0083 §7's retention-purge row already calls two purges through one
    ``Engine`` maintenance operation; the trace purge becomes the third call behind
    that same operation." So the claim is not merely that traces get swept — it is
    that *this* operation sweeps them, with no new job, no new interval and no new
    store surface on the scheduler.

    The horizon is ``now - trace_retention`` and the bound is **strict**: the
    contract says "a trace whose ``occurred_at`` is strictly before it is deleted;
    one at the instant is kept". Asserted with a trace exactly on the horizon,
    because an off-by-one there is invisible against any other fixture — every
    plausible implementation deletes the 400-day-old one.
    """
    traces = FakeTraceRetention()
    horizon = _aged(365)
    recent = _aged(1)
    traces.hold(_aged(400), horizon, recent)
    harness = Harness(traces=traces)

    report = await harness.engine.purge_expired()

    assert report.traces == 1
    assert traces.recorded == (horizon, recent)


async def test_a_keep_forever_horizon_does_not_call_the_trace_sweep_at_all() -> None:
    """``None`` means keep forever, so the sweep is skipped — not called with a floor.

    ADR-0119 §10: the horizon is "an optional duration… where ``None`` means 'keep
    forever'". A floor passed to ``purge_before`` would delete nothing *today* and
    would be a horizon the moment somebody computed it from a different instant, so
    the distinction has to be that no call is made.

    Proven by scripting the seam to raise on any purge: a test that only inspected
    the count would pass for an implementation that swept against
    ``datetime.min``, since that deletes nothing either.
    """
    traces = FakeTraceRetention()
    traces.hold(_aged(4000))
    traces.fail_purge()
    harness = Harness(traces=traces, trace_retention=None)

    report = await harness.engine.purge_expired()

    assert report.traces is None, "None says 'not swept', where 0 would say 'swept, found nothing'"
    assert len(traces.recorded) == 1


async def test_a_horizon_longer_than_the_calendar_deletes_nothing_instead_of_failing() -> None:
    """Accepted configuration must not break the operation it configures.

    ``Settings`` refuses a trace horizon only for being non-finite or non-positive
    (ADR-0119 §10), so ``P999999998D`` loads — three orders of magnitude past the
    calendar. Subtracting one of those from any real clock reading overflows, and it
    would overflow *inside* the maintenance operation, after both Tier 1 sweeps had
    run, on every tick: a retention job that never completes because a setting asked
    for more history than there are dates.

    Saturating is not a guess about intent. A horizon nothing can predate deletes
    nothing, which is what the setting asked for — and it stays distinguishable from
    "keep forever", which does not call the sweep at all.
    """
    traces = FakeTraceRetention()
    ancient = _aged(4000)
    traces.hold(ancient)
    harness = Harness(traces=traces, trace_retention=timedelta.max)

    report = await harness.engine.purge_expired()

    assert report.traces == 0, "0 says 'swept, deleted nothing', where None would say 'not swept'"
    assert traces.recorded == (ancient,)


async def test_a_clock_at_the_start_of_the_calendar_does_not_break_the_sweep() -> None:
    """The other end of the same arithmetic, and the reason the guard is a comparison.

    ``checked_clock`` accepts any reading a day clear of ``datetime.min``
    (ADR-0026 §3's localization margin), so a clock there is a *conforming* clock —
    and the ordinary 365-day horizon underflows against it. An implementation that
    guarded only the huge-``timedelta`` case would still fail here, which is why the
    guard compares the gap rather than special-casing a value.
    """
    traces = FakeTraceRetention()
    ancient = _aged(4000)
    traces.hold(ancient)
    harness = Harness(traces=traces)
    facade = Engine(
        chat_reader=False,
        associator=FakeGoalAssociator(answer=GoalAssociation(verdict=AssociationVerdict.FRESH)),
        composing=_composing(),
        grant_operations=_grant_operations(),
        recipient_grant_operations=_recipient_grant_operations(),
        destination_trust_operations=_destination_trust_operations(),
        connection_operations=_connection_operations(),
        loop=harness.engine._loop,
        runner=harness.engine._runner,
        plans=harness.plans,
        trail=harness.trail,
        spend=harness.trail,
        reads=harness.reads,
        memory=harness.memory,
        deferrals=harness.deferrals,
        traces=harness.traces,
        trace_sink=harness.trace_sink,
        trace_retention=harness.trace_retention,
        conversations=harness.conversations,
        questions=harness.questions,
        now=lambda: datetime.min.replace(tzinfo=UTC) + timedelta(days=1),
    )

    report = await facade.purge_expired()

    assert report.traces == 0
    assert traces.recorded == (ancient,)


async def test_a_failing_deferral_sweep_does_not_reach_the_trace_sweep() -> None:
    """The third call inherits the second's fate, for the second's own reason.

    Nothing sequences the three, so the next tick re-runs all of them; swallowing a
    Tier 1 failure to reach the trace store would report a sweep that half happened,
    and would do it in the direction that matters least — the trace horizon is a
    disk-space policy, where the deferral queue's is ADR-0078 §1's exposure cap.
    """
    traces = FakeTraceRetention()
    traces.hold(_aged(400))
    harness = Harness(traces=traces)

    async def refuses() -> int:
        msg = "the deferral queue is unreadable"
        raise DeferralStoreError(msg)

    harness.deferrals.purge = refuses  # type: ignore[method-assign]

    with pytest.raises(DeferralStoreError):
        await harness.engine.purge_expired()

    assert len(traces.recorded) == 1


async def test_a_failing_trace_sweep_reaches_the_caller() -> None:
    """Unlike an emission failure, a purge failure is loud (ADR-0119 §5, §7).

    §5 subordinates the instrument to the work being observed — "no trace-store
    failure reaches the caller" — but a sweep is not the work being observed, and
    the contract says so where it lives: "a purge that silently did nothing would
    let a store grow without bound behind a horizon an operator believes is
    enforced". The scheduler logs the failure and retries on the next tick.
    """
    traces = FakeTraceRetention()
    traces.fail_purge()
    harness = Harness(traces=traces)
    calls = _counting_purges(harness, records=1, questions=1)

    with pytest.raises(TraceStoreError):
        await harness.engine.purge_expired()

    # The two Tier 1 sweeps ran and are not undone: the next tick re-runs all three.
    assert calls == {"records": 1, "questions": 1}


def test_the_engine_never_reads_a_trace_back() -> None:
    """ADR-0119 §7's third clause, at the first component that holds a trace seam.

    "No component of the request pipeline… holds a seam carrying the walk, and none
    reads a trace back." The type is the guarantee — ``TraceRetention`` has no
    ``walk`` — but the type is erased at runtime and the composition root hands over
    an object that *does*, so a call added here would work perfectly and be caught
    by nothing. What the clause protects is the instrument's independence: a
    pipeline that consults its own telemetry is measuring a system that includes the
    instrument, and leg 8's whole question becomes circular.

    Read out of the source rather than exercised, for the sweep guard's reason: a
    runtime test could only show that the operations it happened to call do not
    walk.
    """
    source = Path(engine_module.__file__).read_text(encoding="utf-8")
    walks = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "walk"
    ]

    assert walks == [], "the engine reads a trace back, which ADR-0119 §7 forbids"


async def test_a_non_positive_confirmation_ceiling_is_refused() -> None:
    """The ceiling must be positive — zero would refuse to drive any step at all."""
    harness = Harness()
    with pytest.raises(ValueError, match="must be positive"):
        Engine(
            chat_reader=False,
            associator=FakeGoalAssociator(answer=GoalAssociation(verdict=AssociationVerdict.FRESH)),
            composing=_composing(),
            grant_operations=_grant_operations(),
            recipient_grant_operations=_recipient_grant_operations(),
            destination_trust_operations=_destination_trust_operations(),
            connection_operations=_connection_operations(),
            loop=harness.engine._loop,
            runner=harness.engine._runner,
            plans=harness.plans,
            trail=harness.trail,
            spend=harness.trail,
            reads=harness.reads,
            memory=harness.memory,
            deferrals=harness.deferrals,
            traces=harness.traces,
            trace_sink=harness.trace_sink,
            trace_retention=harness.trace_retention,
            conversations=harness.conversations,
            questions=harness.questions,
            max_outstanding_confirmations=0,
        )


@pytest.mark.parametrize("bad", [True, 1.5, "2"])
async def test_a_non_integer_confirmation_ceiling_is_refused(bad: object) -> None:
    """A bool, float or string ceiling is a TypeError, not a surprising limit."""
    harness = Harness()
    with pytest.raises(TypeError, match="must be an integer"):
        Engine(
            chat_reader=False,
            associator=FakeGoalAssociator(answer=GoalAssociation(verdict=AssociationVerdict.FRESH)),
            composing=_composing(),
            grant_operations=_grant_operations(),
            recipient_grant_operations=_recipient_grant_operations(),
            destination_trust_operations=_destination_trust_operations(),
            connection_operations=_connection_operations(),
            loop=harness.engine._loop,
            runner=harness.engine._runner,
            plans=harness.plans,
            trail=harness.trail,
            spend=harness.trail,
            reads=harness.reads,
            memory=harness.memory,
            deferrals=harness.deferrals,
            traces=harness.traces,
            trace_sink=harness.trace_sink,
            trace_retention=harness.trace_retention,
            conversations=harness.conversations,
            questions=harness.questions,
            max_outstanding_confirmations=bad,  # type: ignore[arg-type]  # the point of the test
        )


@pytest.mark.parametrize("unusable", [float("nan"), float("inf"), 1.5, True, 0, -1])
async def test_a_payload_limit_that_could_not_bind_is_refused_at_construction(
    unusable: object,
) -> None:
    """ADR-0085 §8c's limit is guarded where it is injected, like its two siblings.

    ``Settings`` refuses a bad ``hub_max_frame_bytes`` at load and the composition
    root derives this argument from it, so no shipped path reaches here — but this is
    a **constructor** argument on a class tests and future roots build directly, and
    the failure is the silent kind: ``float("nan")`` compares ``False`` against every
    ``>``, so an engine built with one would measure every argument and every result
    against a ceiling nothing can exceed while reporting health. A limit that cannot
    bind is not a laxer limit but an absent one, and this one is absent across the
    *whole* promoted surface rather than one method of it (#1686).

    ``True`` earns its place twice over: it is an ``int`` subclass a flag would slip
    through as, and as a limit it is one byte, which no envelope fits inside.
    """
    with pytest.raises((TypeError, ValueError), match="max_payload_bytes"):
        Harness(max_payload_bytes=unusable)  # type: ignore[arg-type]  # the point of the test


async def test_an_int_subclass_that_answers_its_own_comparisons_is_refused_as_a_limit() -> None:
    """The guard allowlists the exact ``int``, which is what closes the class.

    A denylist naming ``bool`` closes one case of it. This is the case that leaves the
    limit *non-binding* rather than merely wrong, and it is reachable with two dunder
    overrides: ``__lt__`` walks the value through the positivity check on the way in,
    and — because Python gives a **subclass's** reflected comparison priority over the
    left operand's own — ``__gt__`` then answers every ``size > limit`` this engine
    performs. The result is ADR-0085 §8c's limit present in the constructor and absent
    everywhere it is measured against, with the engine reporting health throughout,
    which is exactly the failure this guard exists to prevent.
    """

    class _NonBinding(int):
        def __lt__(self, other: object) -> bool:
            return False

        def __gt__(self, other: object) -> bool:
            return False

    with pytest.raises(TypeError, match="max_payload_bytes must be an integer"):
        Harness(max_payload_bytes=_NonBinding(0))


async def test_a_knob_that_cannot_describe_itself_still_gets_the_documented_refusal() -> None:
    """The diagnostic must not be able to destroy the diagnosis.

    The refusal interpolates the offending value, so a value whose ``__repr__`` raises
    would replace the documented ``TypeError`` with whatever that ``__repr__`` threw —
    raised from inside the ``raise`` that reports it, which is the shape
    ``core.types.describe_untrusted`` exists to close and which this guard reaches for
    rather than restating.
    """

    class _Unspeakable:
        def __repr__(self) -> str:
            msg = "this value refuses to describe itself"
            raise RuntimeError(msg)

    with pytest.raises(TypeError, match="max_payload_bytes must be an integer"):
        Harness(max_payload_bytes=_Unspeakable())  # type: ignore[arg-type]  # the point of the test


async def test_aclose_sweeps_remaining_closers_when_one_is_cancelled() -> None:
    """A cancelled closer still lets the rest release, then propagates (§2)."""
    closed: list[str] = []

    async def close_a() -> None:
        closed.append("a")
        raise asyncio.CancelledError

    async def close_b() -> None:
        closed.append("b")

    harness = Harness(closers=(close_a, close_b))
    with pytest.raises(asyncio.CancelledError):
        await harness.engine.aclose()
    assert closed == ["a", "b"]  # b released despite a's cancellation


# --- feedback, as the loop folds it (ADR-0022) ------------------------------


def feedback(
    *,
    kind: FeedbackKind = FeedbackKind.CORRECTION,
    memory_kind: MemoryKind = MemoryKind.SEMANTIC,
    content: str = "the office is in Boston",
    subject: str | None = None,
) -> FeedbackEvent:
    """A ``FeedbackEvent`` the fakes fold into memory."""
    return FeedbackEvent(
        kind=kind,
        memory_kind=memory_kind,
        content=content,
        subject=subject,
        created_at=AT,
    )


# --- the belief inspection surface (ADR-0073 §4, §5, §7) ----------------


def _record(  # noqa: PLR0913 — one knob per field a Belief carries; that is the point
    record_id: str,
    *,
    source: MemorySource = MemorySource.USER_ASSERTED,
    confidence: float = 1.0,
    evidence: tuple[str, ...] = (),
    last_updated: datetime = AT,
    valid_until: datetime | None = None,
    content: str = "the office is in Boston",
    score: float | None = None,
    evidence_elided: int = 0,
    derived_from_external: bool = False,
) -> SemanticMemory:
    """A stored semantic record, with every field the projection reads addressable.

    The attestation is still *not* a knob, and since ADR-0189 §2 the reason has
    changed rather than gone: the projection now reads it, but the `ATTESTED` band is
    unconstructable without one (ADR-0092 §1) and no case here needs a *different*
    one, so it is supplied from the band rather than from a keyword nobody would
    vary. Keyed on `band_of` so a `MemorySource` added into that band later needs no
    edit here.

    ``derived_from_external`` **is** a knob, because it is the one input the origin
    predicate has that the band does not decide (ADR-0106 §2) — and because a record
    carrying it outside the `DERIVED` band is exactly what tells a projection reading
    the field apart from one calling the function.
    """
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        score=score,
        validity=Validity(valid_until=valid_until),
        provenance=Provenance(
            source=source,
            confidence=confidence,
            evidence=evidence,
            evidence_elided=evidence_elided,
            last_updated=last_updated,
            derived_from_external=derived_from_external,
            attestation=(
                Attestation(reported_by="calendar:work", reported_at=AT)
                if band_of(source) is BeliefBand.ATTESTED
                else None
            ),
        ),
    )


@pytest.mark.parametrize(
    ("source", "band"),
    [
        (MemorySource.USER_ASSERTED, BeliefBand.ASSERTED),
        (MemorySource.OBSERVED, BeliefBand.DERIVED),
        (MemorySource.INFERRED, BeliefBand.DERIVED),
        (MemorySource.EXTERNAL, BeliefBand.ATTESTED),
    ],
)
def test_from_record_applies_the_band_projection_in_the_engine(
    source: MemorySource, band: BeliefBand
) -> None:
    """Every source is classified here, once, so no adapter ever has to (ADR-0073 §7)."""
    confidence = 1.0 if source is MemorySource.USER_ASSERTED else 0.4
    belief = belief_from_record(_record("rec-1", source=source, confidence=confidence))
    assert belief.band is band
    assert belief.confidence == confidence


def test_from_record_carries_exactly_what_the_surface_must_convey() -> None:
    """The DTO carries ADR-0073 §4's fields: id, band, kind, content, confidence, times."""
    until = datetime(2026, 8, 1, tzinfo=UTC)
    belief = belief_from_record(
        _record(
            "rec-1",
            source=MemorySource.INFERRED,
            confidence=0.62,
            evidence=("episode-1", "episode-2"),
            valid_until=until,
        )
    )
    assert belief.id == "rec-1"
    assert belief.kind is MemoryKind.SEMANTIC
    assert belief.content == "the office is in Boston"
    assert belief.last_updated == AT
    assert belief.valid_until == until


def test_from_record_carries_resolved_evidence_and_never_ids() -> None:
    """ADR-0073 §4's derived floor, made structural: the citations do not leave here.

    A citation the surface cannot render as evidence is never rendered *as* evidence
    — "not as a reassuring id, not silently dropped". ADR-0077 §6 discharged the gate
    on *resolving* them, so what the DTO now carries is readable content or an
    explicit tombstone; what it still never carries is an id, which is what stops an
    adapter passing one off as the warrant.
    """
    belief = belief_from_record(
        _record("rec-1", source=MemorySource.INFERRED, confidence=0.5, evidence=("ep-1", "ep-2")),
        (Evidence(content="they said so"), Evidence()),
    )
    assert belief.evidence_count == 2
    assert belief.lost_evidence == 1
    assert "ep-1" not in str(belief)  # no citation id is reachable from the DTO at all


@pytest.mark.parametrize(
    ("source", "band"),
    [
        (MemorySource.USER_ASSERTED, BeliefBand.ASSERTED),
        (MemorySource.INFERRED, BeliefBand.DERIVED),
        (MemorySource.EXTERNAL, BeliefBand.ATTESTED),
    ],
)
def test_both_projections_carry_the_stored_elision_on_every_band(
    source: MemorySource, band: BeliefBand
) -> None:
    """ADR-0107 §3: the field is carried on **every** band, at both sites.

    Parameterised over all three bands rather than over the one whose *rendering*
    ADR-0107 §2 discusses, and §8 item 6 says why in as many words: naming only the
    discussed bands "would leave the third free to be projected as ``0`` by an
    implementation that wrongly coupled the field to §2's rendering scope, with
    every other test here still passing". §2 scopes a disclosure obligation; §3
    scopes the field, and it scopes it to everything. "A projection never zeroes,
    clamps or omits it by band" is a checked claim here rather than a stated one.

    The value is non-default at every assertion, per §8 item 6's governing rule: at
    the default ``0`` this would pass whether the number is carried or silently
    dropped, which is a test that cannot fail and therefore is not one.
    """
    confidence = 1.0 if source is MemorySource.USER_ASSERTED else 0.5
    record = _record(
        "rec-1", source=source, confidence=confidence, evidence=("ep-1",), evidence_elided=900
    )

    belief = belief_from_record(record, (Evidence(content="they said so"),))
    assert belief.band is band
    assert belief.evidence_elided == 900

    summary = belief_summary_from_record(record, cited=1, resolved=1)
    assert summary.band is band
    assert summary.evidence_elided == 900


def test_neither_projection_clamps_the_elision_to_the_citations_it_kept() -> None:
    """ADR-0107 §8 item 2: no rounding, no clamping, no recomputation.

    The two shapes a clamp would "fix" are both legitimate, and both are asserted
    here: an elision far above the retained count, and a non-zero elision over an
    empty tuple. ``evidence_elided`` counts displacements over the record's whole
    history and is an upper bound over a *different population* than the retained
    citations (ADR-0086 §4), so neither shape is a contradiction — and a projection
    clamping to ``evidence_count`` would resolve ADR-0086 §4's deliberate
    imprecision, in the wrong direction, on the one screen that exists to answer
    "why do you believe that?".
    """
    many = _record(
        "rec-1",
        source=MemorySource.INFERRED,
        confidence=0.5,
        evidence=("ep-1",),
        evidence_elided=900,
    )
    belief = belief_from_record(many, (Evidence(content="they said so"),))
    assert belief.evidence_count == 1
    assert belief.evidence_elided == 900  # not clamped to 1, and not zeroed
    assert belief_summary_from_record(many, cited=1, resolved=1).evidence_elided == 900

    # Nothing carried, something displaced: the belief cites nothing *now*, and how
    # much it stopped carrying is still the honest answer rather than an anomaly.
    empty = _record("rec-2", source=MemorySource.INFERRED, confidence=0.5, evidence_elided=7)
    projected = belief_from_record(empty)
    assert projected.evidence_count == 0
    assert projected.evidence_elided == 7
    assert belief_summary_from_record(empty, cited=0, resolved=0).evidence_elided == 7


def test_the_elision_is_not_fed_into_the_presented_confidence() -> None:
    """ADR-0107 §8 item 3, on ADR-0086 §4's ground: it would invert the signal.

    Feeding elisions into :func:`presented_confidence` "would lower a belief's
    presented confidence because the system worked". Two records identical but for
    the elision must present one confidence — and the elided one must still report
    its exact count, or this passes by the field having been dropped rather than by
    it having been kept out of the arithmetic.
    """
    citations = (Evidence(content="they said so"), Evidence())
    plain = _record("rec-1", source=MemorySource.INFERRED, confidence=0.8, evidence=("a", "b"))
    elided = _record(
        "rec-2",
        source=MemorySource.INFERRED,
        confidence=0.8,
        evidence=("a", "b"),
        evidence_elided=900,
    )

    assert belief_from_record(elided, citations).confidence == pytest.approx(
        belief_from_record(plain, citations).confidence
    )
    assert belief_from_record(elided, citations).evidence_elided == 900
    assert belief_summary_from_record(elided, cited=2, resolved=1).confidence == pytest.approx(
        belief_summary_from_record(plain, cited=2, resolved=1).confidence
    )
    assert belief_summary_from_record(elided, cited=2, resolved=1).evidence_elided == 900


def test_from_record_drops_the_relevance_score() -> None:
    """Nothing was ranked on this path, so no score is carried (ADR-0073 §2, §7)."""
    belief = belief_from_record(_record("rec-1", score=0.93))
    assert not hasattr(belief, "score")


# --- the origin of what a projection shows (ADR-0189 §1, §2) ------------


@pytest.mark.parametrize(
    ("source", "derived_from_external", "rests"),
    [
        (MemorySource.USER_ASSERTED, False, False),
        (MemorySource.OBSERVED, False, False),
        (MemorySource.INFERRED, False, False),
        (MemorySource.OBSERVED, True, True),
        (MemorySource.INFERRED, True, True),
        (MemorySource.EXTERNAL, False, True),
    ],
)
def test_both_projections_carry_the_predicate_s_own_answer(
    source: MemorySource, derived_from_external: bool, rests: bool
) -> None:
    """ADR-0189 §2: the value is `rests_on_recorded_external_content`'s, computed here.

    Every arm of ADR-0106 §2's two-part predicate, on both projections: `ATTESTED`
    is true by the band alone, `ASSERTED` is false by ADR-0098 §1 whatever the field
    says, and `DERIVED` is the one case the flag decides — which is the case the
    field exists for (#746).

    Asserted against the function rather than against a transcribed truth table, so
    that a projection and the predicate cannot drift apart in a later edit without
    this failing.
    """
    confidence = 1.0 if source is MemorySource.USER_ASSERTED else 0.4
    record = _record(
        "rec-1",
        source=source,
        confidence=confidence,
        derived_from_external=derived_from_external,
    )

    assert rests_on_recorded_external_content(record.provenance) is rests
    assert belief_from_record(record).rests_on_recorded_external_content is rests
    summary = belief_summary_from_record(record, cited=0, resolved=0)
    assert summary.rests_on_recorded_external_content is rests


def test_a_user_s_own_assertion_never_rests_on_external_content_however_the_record_is_flagged() -> (
    None
):
    """The one case that tells the function apart from the field (ADR-0106 §2, §7).

    ADR-0106 §7 forbids a band-keyed validator on `derived_from_external`, so a
    `USER_ASSERTED` provenance carrying `True` stays constructible — malformed rather
    than adversarial. The predicate is band-guarded and answers `False`; a projection
    that read the field directly would report the user's own utterance as resting on
    recorded external content, which ADR-0098 §1 forbids in principle "however it was
    composed".

    This is the assertion that fails the day someone writes
    ``provenance.derived_from_external`` at either site, and nothing else here does.
    """
    flagged = _record("rec-1", source=MemorySource.USER_ASSERTED, derived_from_external=True)

    assert flagged.provenance.derived_from_external is True, "the record really carries it"
    assert belief_from_record(flagged).rests_on_recorded_external_content is False
    assert (
        belief_summary_from_record(flagged, cited=0, resolved=0).rests_on_recorded_external_content
        is False
    )


def test_both_projections_carry_the_attestation_whole() -> None:
    """ADR-0189 §2: the `Attestation` as stored, not two scalars beside it.

    Both halves ADR-0073 §4's gate asks for — what reported it and when that source
    said so — reach the surface as one object, so the half-states ADR-0092 §2 made
    unconstructable on the record's side of the seam stay unconstructable on the
    surface's. Identity is asserted rather than field equality: a projection that
    rebuilt an `Attestation` from two scalars would pass a field-by-field check while
    dropping `extent`, which ADR-0189 §2 rules rides along.
    """
    attested = _record("rec-1", source=MemorySource.EXTERNAL, confidence=0.7)
    stored = attested.provenance.attestation
    assert stored is not None

    belief = belief_from_record(attested)
    summary = belief_summary_from_record(attested, cited=0, resolved=0)

    assert belief.attestation is stored
    assert summary.attestation is stored
    assert belief.attestation.reported_by == "calendar:work"
    assert belief.attestation.reported_at == AT


def test_an_unattested_belief_carries_no_attestation_on_either_projection() -> None:
    """Present exactly where the band is `ATTESTED`, which the record already decides.

    ADR-0189 §2 adds no cross-field validator to either projection and does not need
    one: `Provenance` carries an attestation exactly in that band (ADR-0092 §1), so
    the projection carrying it as stored inherits the invariant. What would break it
    is a projection *manufacturing* one, so the absence is pinned rather than assumed.
    """
    for source in (MemorySource.USER_ASSERTED, MemorySource.OBSERVED, MemorySource.INFERRED):
        confidence = 1.0 if source is MemorySource.USER_ASSERTED else 0.4
        record = _record("rec-1", source=source, confidence=confidence)
        assert belief_from_record(record).attestation is None
        assert belief_summary_from_record(record, cited=0, resolved=0).attestation is None


def test_the_listing_and_the_detail_view_agree_about_the_origin() -> None:
    """The listing discloses a belief's origin exactly as the detail view does.

    ADR-0085 §4a's split is about *citations* — the listing carries counts where the
    detail carries content — and provenance is on neither side of it. This is ADR-0107
    §8 item 5's argument one field pair over: a listing that disclosed less than the
    view it is drilled into would make two reads of one record disagree about a fact
    neither of them computes.
    """
    attested = _record("rec-1", source=MemorySource.EXTERNAL, confidence=0.7)
    tainted = _record(
        "rec-2", source=MemorySource.INFERRED, confidence=0.5, derived_from_external=True
    )

    for record in (attested, tainted):
        belief = belief_from_record(record)
        summary = belief_summary_from_record(record, cited=0, resolved=0)
        assert summary.attestation == belief.attestation
        assert (
            summary.rests_on_recorded_external_content is belief.rests_on_recorded_external_content
        )


async def test_beliefs_lists_what_memory_holds_in_the_store_s_own_order() -> None:
    """The façade relays the enumeration and projects each record (ADR-0073 §1, §7)."""
    harness = Harness()
    await harness.memory.add(_record("older", last_updated=AT - timedelta(days=1)))
    await harness.memory.add(_record("newer", last_updated=AT))

    page = await harness.engine.beliefs()
    assert [summary.id for summary in page] == ["newer", "older"]  # the store's order, unchanged
    # The listing ships summaries, not beliefs (ADR-0085 §4a): a `BeliefSummary` has
    # no field a citation's content could occupy, so no page can carry the corpus.
    assert all(isinstance(summary, BeliefSummary) for summary in page)
    assert all(not hasattr(summary, "evidence") for summary in page)
    assert page[0].band is BeliefBand.ASSERTED


async def test_beliefs_returns_an_empty_page_when_nothing_matches() -> None:
    """An empty store is an empty tuple, not an error."""
    harness = Harness()
    assert await harness.engine.beliefs() == ()


async def test_beliefs_relays_every_filter_and_the_bounded_default_page() -> None:
    """Filters and paging reach the store verbatim; the default limit is stated (§2)."""
    harness = Harness(memory=RecordingBeliefStore(now=lambda: AT))
    store = harness.memory
    assert isinstance(store, RecordingBeliefStore)

    await harness.engine.beliefs()
    await harness.engine.beliefs(
        bands=[BeliefBand.DERIVED], kinds=[MemoryKind.SEMANTIC], limit=2, offset=7
    )
    assert store.calls == [
        # No filters, and the bounded default page starting from the beginning (§2).
        (None, None, 50, 0),
        # Every filter and both paging arguments, relayed exactly as given.
        ((BeliefBand.DERIVED,), (MemoryKind.SEMANTIC,), 2, 7),
    ]


async def test_beliefs_selects_nothing_for_an_explicitly_empty_filter() -> None:
    """An empty sequence is relayed as itself — it selects nothing, unlike None (§1)."""
    harness = Harness(memory=RecordingBeliefStore(now=lambda: AT))
    store = harness.memory
    assert isinstance(store, RecordingBeliefStore)
    await harness.engine.beliefs(bands=[], kinds=[])
    assert store.calls[-1] == ((), (), 50, 0)


async def test_beliefs_snapshots_its_filters_so_a_caller_cannot_change_the_page() -> None:
    """The filters are materialised before the awaiting task reads them (ADR-0065).

    The mutation lands **mid-flight** — while the store is suspended inside
    ``list_beliefs``, before it has read the sequence it was handed — and not after
    the call returned. That is the difference between proving snapshot *isolation*
    and proving *when* the snapshot was taken, which is what ADR-0065 §3's discharge
    is about.

    Mutating afterwards instead does catch a façade that relays the caller's list
    verbatim — but only by accident of this seam: the recorder happens to keep the
    raw object, and a ``list`` never equals a ``tuple``. Let the recorder normalise
    its capture on entry, an unremarkable thing for a recorder to do, and the
    after-the-fact form goes green against a façade that materialises nothing, while
    this form still fails. A property that rests on the recorder's choice of
    representation is not the property the docstring claims, so it is asserted where
    no later copy can rescue it: after the store already holds the argument.

    The gated-collaborator idiom is the one
    ``test_learn_is_drained_before_shutdown_closes_resources`` uses.
    ``RecordingBeliefStore`` is the seam, subclassed so it reads its own ``bands``
    argument *after* the release — standing in for a store that observes its input
    late, which is the only kind of store that can tell the two façades apart.
    """
    entered = asyncio.Event()
    release = asyncio.Event()

    class GatedBeliefStore(RecordingBeliefStore):
        """Holds ``list_beliefs`` open, then reads ``bands`` only once released."""

        #: ``bands`` as it read after resuming, or ``None`` if it was given none.
        observed_on_resume: tuple[BeliefBand, ...] | None = None

        async def list_beliefs(
            self,
            *,
            bands: Sequence[BeliefBand] | None = None,
            kinds: Sequence[MemoryKind] | None = None,
            limit: int = 50,
            offset: int = 0,
        ) -> list[MemoryRecord]:
            entered.set()
            await release.wait()
            self.observed_on_resume = None if bands is None else tuple(bands)
            return await super().list_beliefs(bands=bands, kinds=kinds, limit=limit, offset=offset)

    store = GatedBeliefStore(now=lambda: AT)
    harness = Harness(memory=store)

    bands = [BeliefBand.ASSERTED]
    call = asyncio.ensure_future(harness.engine.beliefs(bands=bands))
    await entered.wait()

    bands.append(BeliefBand.DERIVED)  # the caller mutates while the read is in flight
    release.set()
    await call

    # One coherent snapshot: what the store was handed and what it read on resuming
    # are both the filter as it stood when the call was made, not as the caller left
    # it. The second assertion is the original after-the-fact property, kept — it is
    # implied here but costs nothing and names the weaker half explicitly.
    assert store.observed_on_resume == (BeliefBand.ASSERTED,)
    assert store.calls[-1][0] == (BeliefBand.ASSERTED,)


async def test_beliefs_relays_an_out_of_range_page_refusal() -> None:
    """The store refuses rather than clamps, and the façade does not swallow it (§2)."""
    harness = Harness()
    with pytest.raises(ValueError, match="limit"):
        await harness.engine.beliefs(limit=-1)


async def test_belief_reads_the_one_a_deletion_is_about_to_destroy() -> None:
    """The single read show-then-confirm needs, projected like any other (§5, §7)."""
    harness = Harness()
    await harness.memory.add(_record("rec-1", source=MemorySource.EXTERNAL, confidence=0.8))
    belief = await harness.engine.belief("rec-1")
    assert belief is not None
    assert belief.id == "rec-1"
    assert belief.band is BeliefBand.ATTESTED


async def test_belief_is_none_for_an_id_no_live_record_has() -> None:
    """Unknown, and — because ``get`` is live-only — retired, both read as None (§5)."""
    harness = Harness()
    assert await harness.engine.belief("nothing") is None
    retired = _record("retired", valid_until=AT - timedelta(days=1))
    await harness.memory.add(retired)
    assert await harness.engine.belief("retired") is None


async def test_forget_destroys_the_record_and_reports_that_it_did() -> None:
    """``forget`` is ``MemoryStore.delete``, relayed (ADR-0073 §5)."""
    harness = Harness()
    await harness.memory.add(_record("rec-1"))
    assert await harness.engine.forget("rec-1") is True
    assert await harness.engine.belief("rec-1") is None
    assert await harness.engine.beliefs() == ()


async def test_forget_reports_false_for_an_id_no_record_has() -> None:
    """ "No such belief" is a return value the adapter renders, not an error (§7)."""
    harness = Harness()
    assert await harness.engine.forget("nothing") is False


@pytest.mark.parametrize("band", list(BeliefBand))
async def test_forget_refuses_no_band(band: BeliefBand) -> None:
    """The store grows no band-conditional refusal: a data right is unconditional (§5).

    ADR-0004 §6 gives the user an unconditional right to delete their data, so a
    belief is destroyed whatever band the system itself put it in. The asymmetry
    between the bands lives in what the user is told before answering, not in what
    the deletion will do.
    """
    source = {
        BeliefBand.ASSERTED: MemorySource.USER_ASSERTED,
        BeliefBand.DERIVED: MemorySource.INFERRED,
        BeliefBand.ATTESTED: MemorySource.EXTERNAL,
    }[band]
    confidence = 1.0 if band is BeliefBand.ASSERTED else 0.5
    harness = Harness()
    await harness.memory.add(_record("rec-1", source=source, confidence=confidence))
    shown = await harness.engine.belief("rec-1")
    assert shown is not None
    assert shown.band is band
    assert await harness.engine.forget("rec-1") is True


async def test_forget_leaves_nothing_behind_not_even_in_an_export() -> None:
    """Forgetting destroys; a correction would have retired and kept it (ADR-0073 §6)."""
    harness = Harness()
    await harness.memory.add(_record("rec-1"))
    await harness.engine.forget("rec-1")
    assert await harness.memory.export() == []


@pytest.mark.parametrize("call", ["beliefs", "belief", "forget", "episodes", "episode_chunk"])
async def test_the_inspection_surface_is_refused_once_shutdown_has_begun(call: str) -> None:
    """After aclose, no inspection call is accepted either (ADR-0042 §2)."""
    harness = Harness()
    await harness.engine.aclose()
    calls: dict[str, Callable[[], Awaitable[object]]] = {
        "episodes": harness.engine.episodes,
        "episode_chunk": lambda: harness.engine.episode_chunk(""),
        "beliefs": harness.engine.beliefs,
        "belief": lambda: harness.engine.belief("rec-1"),
        "forget": lambda: harness.engine.forget("rec-1"),
    }
    with pytest.raises(RuntimeError, match="shutting down"):
        await calls[call]()


async def test_forget_is_drained_before_shutdown_closes_resources() -> None:
    """A deletion touches the connection-owning store, so aclose waits for it (§2)."""
    release = asyncio.Event()
    entered = asyncio.Event()
    closed = asyncio.Event()
    closed_while_inflight = False

    class GatedDeleteStore(FakeMemoryStore):
        async def delete(self, record_id: str) -> bool:
            entered.set()
            await release.wait()
            return await super().delete(record_id)

    async def close() -> None:
        nonlocal closed_while_inflight
        closed_while_inflight = not release.is_set()
        closed.set()

    harness = Harness(memory=GatedDeleteStore(now=lambda: AT), closers=(close,))
    call = asyncio.ensure_future(harness.engine.forget("rec-1"))
    await entered.wait()

    closing = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.sleep(0)  # let aclose reach its drain
    assert not closed.is_set()  # the store is not closed while the deletion is in flight

    release.set()
    await call
    await closing
    assert closed.is_set()
    assert closed_while_inflight is False


# --- conversations: capture, continuity and the façade (ADR-0074 §2, §3, §5) --


async def test_engine_start_consumes_the_stamped_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0076 §3: every conformance clause can pass against a method **nothing calls**.

    So this asserts the wiring rather than the store: engine start-up reaches the
    enumeration ADR-0076 added, which is the only way a deletion a previous run left
    unfinished is ever rediscovered.
    """
    harness = Harness(planner=NoStepPlanner())
    calls: list[str | None] = []
    original = harness.conversation_store.stamped_conversation_ids

    async def _spy(*, limit: int | None = None, after_id: str | None = None) -> list[str]:
        calls.append(after_id)
        return await original(limit=limit, after_id=after_id)

    monkeypatch.setattr(harness.conversation_store, "stamped_conversation_ids", _spy)

    await harness.engine.start()

    assert calls == [None], "start-up walked the tombstones exactly once, from the beginning"


# --- lost evidence: tombstones and presented confidence (ADR-0077 §6) ----


#: A derived belief's stored confidence, comfortably above the presentation floor.
_STORED = 0.6


async def _derived_with_two_episodes(harness: Harness) -> None:
    """Store a derived belief citing two episodes that both resolve."""
    await harness.memory.add(_episode_record("ep-1", "they asked for metric units"))
    await harness.memory.add(_episode_record("ep-2", "they asked again in metric"))
    await harness.memory.add(
        _record(
            "rec-1",
            source=MemorySource.INFERRED,
            confidence=_STORED,
            evidence=("ep-1", "ep-2"),
            content="the user prefers metric units",
        )
    )


def _episode_record(
    episode_id: str, content: str, *, expires_at: datetime | None = None
) -> EpisodicMemory:
    """One captured episode, optionally with a retention deadline already passed."""
    return EpisodicMemory(
        id=episode_id,
        content=content,
        occurred_at=AT,
        expires_at=expires_at,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )


async def test_a_belief_whose_evidence_all_resolves_shows_the_stored_confidence() -> None:
    """Nothing lost, nothing adjusted — the baseline the degradation is measured from."""
    harness = Harness()
    await _derived_with_two_episodes(harness)

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.confidence == _STORED
    assert belief.evidence_count == 2
    assert belief.lost_evidence == 0
    assert belief.unsupported is False
    assert [item.content for item in belief.evidence] == [
        "they asked for metric units",
        "they asked again in metric",
    ]


async def test_a_deleted_citation_becomes_a_tombstone_without_touching_the_record() -> None:
    """The rendering changes; the stored record does not (ADR-0077 §6).

    The byte-identity assertion is what catches an implementation that "fixed" the
    record instead of the rendering — the record graph is frozen (ADR-0068), and
    losing evidence is not the producer changing its mind.
    """
    harness = Harness()
    await _derived_with_two_episodes(harness)
    before = await harness.memory.get("rec-1")
    assert before is not None

    assert await harness.memory.delete("ep-1") is True
    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.lost_evidence == 1
    assert belief.evidence[0].lost is True
    assert belief.evidence[0].content is None  # never the id, never a silent gap
    assert belief.evidence[1].content == "they asked again in metric"
    assert belief.confidence < _STORED  # presented, and strictly lower
    # The record is untouched, and an export still carries the citation as written.
    assert await harness.memory.get("rec-1") == before
    exported = {record.id: record for record in await harness.memory.export()}
    assert exported["rec-1"].provenance.evidence == ("ep-1", "ep-2")
    assert exported["rec-1"].provenance.confidence == _STORED


async def test_an_expired_citation_renders_exactly_as_a_deleted_one() -> None:
    """Expiry is the *commoner* loss and has no event to hook (ADR-0077 §6).

    Pinned deliberately: an implementation that hooked deletion only would pass every
    deletion test above and silently leave every expired citation dangling, which is
    §6's decisive argument against eager rewriting.
    """
    harness = Harness()
    await harness.memory.add(
        _episode_record("ep-1", "they asked for metric units", expires_at=AT - timedelta(days=1))
    )
    await harness.memory.add(_episode_record("ep-2", "they asked again in metric"))
    await harness.memory.add(
        _record(
            "rec-1", source=MemorySource.INFERRED, confidence=_STORED, evidence=("ep-1", "ep-2")
        )
    )

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.lost_evidence == 1
    assert belief.evidence[0].content is None
    assert belief.confidence < _STORED


async def test_a_belief_whose_evidence_is_all_gone_is_held_at_its_effective_floor() -> None:
    """Marked, answerable, still live — **not** retired (ADR-0077 §6).

    Auto-retiring would be the cascade under a softer name: it destroys a belief that
    may be perfectly true, and makes deleting an old conversation silently undo an
    accumulation the user never asked to lose.
    """
    harness = Harness()
    await _derived_with_two_episodes(harness)
    await harness.memory.delete("ep-1")
    await harness.memory.delete("ep-2")

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.unsupported is True
    assert belief.lost_evidence == 2
    assert belief.confidence == pytest.approx(0.1)  # the effective floor, not zero
    # Still live, still listed, and still deletable by the user.
    assert [one.id for one in await harness.engine.beliefs()] == ["rec-1"]
    assert await harness.engine.forget("rec-1") is True


async def test_a_belief_stored_below_the_floor_is_left_where_it_is() -> None:
    """``min(stored, floor)``, not the floor itself — the whole of the edge case (§6).

    ``Provenance.confidence`` permits ``0.0`` and only the observer is bound to a
    positive ladder, so a belief can be stored beneath the floor — where an absolute
    floor and "never above stored" have no value between them at all. The pair with
    the case above is what pins ``min(stored, floor)`` rather than either half of it.
    """
    harness = Harness()
    await harness.memory.add(_episode_record("ep-1", "a thin signal"))
    await harness.memory.add(
        _record("thin", source=MemorySource.INFERRED, confidence=0.05, evidence=("ep-1",))
    )
    await harness.memory.delete("ep-1")

    belief = await harness.engine.belief("thin")

    assert belief is not None
    assert belief.unsupported is True
    assert belief.confidence == 0.05  # unchanged: both bounds collapsed onto the stored value


async def test_the_presented_confidence_falls_strictly_with_each_further_loss() -> None:
    """Monotone above the floor, and bounded by the stored value (ADR-0077 §6).

    Asserted on the function rather than through the store, because the property is
    about the *function*: a pure map from the stored value and how much support
    survives, with no clock and nothing read.
    """
    full = presented_confidence(_STORED, cited=3, resolved=3)
    one_lost = presented_confidence(_STORED, cited=3, resolved=2)
    two_lost = presented_confidence(_STORED, cited=3, resolved=1)
    none_left = presented_confidence(_STORED, cited=3, resolved=0)

    assert full == _STORED
    assert _STORED > one_lost > two_lost > none_left
    assert none_left == pytest.approx(0.1)
    # An assertion cites nothing, and nothing about that is a loss.
    assert presented_confidence(1.0, cited=0, resolved=0) == 1.0


async def test_the_listing_and_the_single_belief_view_agree_on_the_number() -> None:
    """Every surface that states a confidence states the adjusted one (ADR-0077 §6).

    Two surfaces quoting different numbers for one belief would make the disclosure
    rule meaningless, so the adjustment lives in the projection both go through.
    """
    harness = Harness()
    await _derived_with_two_episodes(harness)
    await harness.memory.delete("ep-1")

    listed = await harness.engine.beliefs()
    single = await harness.engine.belief("rec-1")

    assert single is not None
    assert [one.confidence for one in listed if one.id == "rec-1"] == [single.confidence]
    assert single.confidence < _STORED


# --- citations resolve in one batch read (ADR-0086 §6, §8 item 6) --------


class CountingStore(FakeMemoryStore):
    """A store that records which read shape each call took, and with what ids.

    Both counters matter separately. ``_belief`` reads the belief itself through
    ``get`` and §6 is explicit that ``get_many`` "does not replace ``get``", so a
    case that merely counted total reads could not tell the one legitimate single
    from *n* illegitimate ones.
    """

    def __init__(self, *, now: Callable[[], datetime]) -> None:
        super().__init__(now=now)
        self.singles: list[str] = []
        self.batches: list[tuple[str, ...]] = []

    async def get(self, record_id: str) -> MemoryRecord | None:
        self.singles.append(record_id)
        return await super().get(record_id)

    async def get_many(self, record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
        self.batches.append(tuple(record_ids))
        return await super().get_many(record_ids)


class SteppingClock:
    """A clock that advances on every reading **once armed**, so *when* is visible.

    This is what makes §6's snapshot testable from the consumer's side without
    counting calls: a loop of singles reads the clock once per citation and a batch
    reads it once for the record, so a citation whose expiry falls between two steps
    resolves under one and not the other.

    Arming is what makes the case deterministic rather than merely suggestive. A
    clock that stepped from construction would also step for every ``add`` in the
    fixture, so how far it had moved by the read under test would depend on how many
    setup writes happened to precede it — and the case would pass or fail on that
    accident instead of on the batch.
    """

    def __init__(self, *, step: timedelta) -> None:
        self._now = AT
        self._step = step
        self._armed = False

    def arm(self) -> None:
        """Start advancing, from here on."""
        self._armed = True

    def __call__(self) -> datetime:
        now = self._now
        if self._armed:
            self._now += self._step
        return now


async def test_a_beliefs_citations_are_resolved_in_one_batch_read() -> None:
    """§8 item 6: one ``get_many`` per record, not one ``get`` per citation."""
    store = CountingStore(now=lambda: AT)
    harness = Harness(memory=store)
    await _derived_with_two_episodes(harness)
    store.singles.clear()
    store.batches.clear()

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert store.batches == [("ep-1", "ep-2")], "the citations went in one call, in order"
    assert store.singles == ["rec-1"], (
        "the only single read left is the belief's own id — §6 does not replace `get`"
    )


async def test_a_listing_page_batches_once_per_belief_not_once_per_citation() -> None:
    """The listing is the call site §8 item 6's arithmetic is actually about.

    ADR-0085 §4a removed the listing's evidence *payload* and none of its reads, so
    a lane that migrated the single-belief wrapper alone would leave the 50-by-64 path
    on singles while every single-belief test passed. One batch **per belief**, not
    one per page: the beliefs are independent presentations and §8 item 6 says per
    belief.
    """
    store = CountingStore(now=lambda: AT)
    harness = Harness(memory=store)
    await _derived_with_two_episodes(harness)
    await harness.memory.add(_episode_record("ep-3", "they wrote 20 °C"))
    await harness.memory.add(
        _record("rec-2", source=MemorySource.INFERRED, confidence=_STORED, evidence=("ep-3",))
    )
    store.singles.clear()
    store.batches.clear()

    listed = await harness.engine.beliefs()

    assert {"rec-1", "rec-2"} <= {one.id for one in listed}
    assert len(store.batches) == len(listed), "one batch per listed belief, page-wide"
    assert sorted(one for one in store.batches if one) == [("ep-1", "ep-2"), ("ep-3",)]
    assert store.singles == [], "the listing reads through `list_beliefs`, then batches"


async def test_a_belief_citing_nothing_asks_the_store_for_nothing() -> None:
    """§6: an empty argument is a question with an answer, and no round trip.

    Relied on rather than branched around, so this pins that the reliance is real.
    """
    store = CountingStore(now=lambda: AT)
    harness = Harness(memory=store)
    await harness.memory.add(_record("rec-1", evidence=()))
    store.singles.clear()
    store.batches.clear()

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.evidence == ()
    assert store.batches == [()]


async def test_every_citation_of_a_belief_is_judged_at_one_instant() -> None:
    """§6's snapshot, observed from the consumer: one clock reading for the record.

    Pins the *mechanism* and not the values. Armed, the clock steps an hour per read:
    the belief's own ``get`` takes ``AT``, and the citations are read next. ``ep-2``
    expires 90 minutes in, so a loop of singles reads ``ep-1`` at ``AT + 1h`` and
    ``ep-2`` at ``AT + 2h`` and renders a tombstone the record never lost — the
    "belief's rendered count disagrees with its own tombstones" failure §6 names. One
    batch judges both against the single instant the batch was taken, and nothing is
    lost. No call is counted here, deliberately: this is the case that fails if the
    batch is replaced by a loop that returns identical values.
    """
    clock = SteppingClock(step=timedelta(hours=1))
    store = FakeMemoryStore(now=clock)
    harness = Harness(memory=store)
    await store.add(_episode_record("ep-1", "they asked for metric units"))
    await store.add(
        _episode_record("ep-2", "they asked again in metric", expires_at=AT + timedelta(minutes=90))
    )
    await store.add(
        _record(
            "rec-1", source=MemorySource.INFERRED, confidence=_STORED, evidence=("ep-1", "ep-2")
        )
    )
    clock.arm()

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert belief.lost_evidence == 0, (
        "both citations were judged against the batch's one instant, not against one "
        "instant each — a citation cannot expire partway through its own presentation"
    )
    assert [item.content for item in belief.evidence] == [
        "they asked for metric units",
        "they asked again in metric",
    ]


async def test_a_repeated_citation_keeps_a_position_of_its_own() -> None:
    """§6: duplicates collapse in the mapping; the rendering must not lose them.

    The answer is assembled by walking ``provenance.evidence``, so a tuple citing an
    id twice renders two positions. An implementation that iterated the mapping would
    render one, and would be silently short for every belief a fold cited twice.
    """
    harness = Harness()
    await harness.memory.add(_episode_record("ep-1", "they asked for metric units"))
    await harness.memory.add(
        _record(
            "rec-1", source=MemorySource.INFERRED, confidence=_STORED, evidence=("ep-1", "ep-1")
        )
    )

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert [item.content for item in belief.evidence] == [
        "they asked for metric units",
        "they asked for metric units",
    ]
    assert belief.evidence_count == 2
    assert belief.lost_evidence == 0


async def test_the_batch_renders_tombstones_where_the_singles_did() -> None:
    """§6: ``get_many`` never disagrees with ``get``, on any of the three outcomes.

    Absent, expired and not-yet-live in one record, each in a known position, so a
    batch that honoured only some of the read-time axes — or that returned a ``None``
    value where §6 requires an omission — is caught at the position it broke.
    """
    harness = Harness()
    await harness.memory.add(_episode_record("ep-live", "they asked for metric units"))
    await harness.memory.add(
        _episode_record("ep-expired", "old", expires_at=AT - timedelta(days=1))
    )
    await harness.memory.add(
        EpisodicMemory(
            id="ep-future",
            content="not yet",
            occurred_at=AT,
            validity=Validity(valid_from=AT + timedelta(days=1)),
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
        )
    )
    await harness.memory.add(
        _record(
            "rec-1",
            source=MemorySource.INFERRED,
            confidence=_STORED,
            evidence=("ep-live", "ep-expired", "ep-absent", "ep-future"),
        )
    )

    belief = await harness.engine.belief("rec-1")

    assert belief is not None
    assert [item.lost for item in belief.evidence] == [False, True, True, True]
    assert belief.evidence[0].content == "they asked for metric units"
    assert belief.lost_evidence == 3


# --- a refused citation read is an error, never a tombstone (#585) -------


class RefusingCitationStore(FakeMemoryStore):
    """A store that answers everything but the citation batch, **once armed**.

    Armed rather than refusing from construction, because the fixture's own writes
    reach the same store: a store that refused every ``get_many`` would risk failing
    during setup, and the case would be about the harness instead of about the
    projection. ``refuse_after`` then chooses *which* batch refuses, which is what
    lets a listing case put the refusal on a belief that is not the first one.
    """

    def __init__(self, *, now: Callable[[], datetime], refuse_after: int = 0) -> None:
        super().__init__(now=now)
        self._refuse_after = refuse_after
        self._armed = False
        self.batches = 0

    def arm(self) -> None:
        """Start refusing, from the batch after ``refuse_after`` on."""
        self._armed = True

    async def get_many(self, record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
        if not self._armed:
            return await super().get_many(record_ids)
        self.batches += 1
        if self.batches > self._refuse_after:
            msg = "the citation batch cannot be read"
            raise MemoryStoreError(msg)
        return await super().get_many(record_ids)


async def test_belief_propagates_a_store_that_refuses_the_citation_read() -> None:
    """The ``MemoryStoreError`` the docstring declares actually escapes ``belief``.

    What this pins is not the raise but the *alternative*: a projection that caught
    the refusal and rendered the unread citations as tombstones would return a
    perfectly well-formed :class:`~ai_assistant.core.types.Belief`, and a caller
    cannot tell that apart from genuinely lost evidence. A tombstone asserts "this
    evidence is gone" (ADR-0077 §6); a read that failed asserts nothing of the kind,
    and the record graph is frozen (ADR-0068) precisely so that losing evidence stays
    a statement about the world rather than about the store's mood.
    """
    store = RefusingCitationStore(now=lambda: AT)
    harness = Harness(memory=store)
    await _derived_with_two_episodes(harness)
    store.arm()

    with pytest.raises(MemoryStoreError):
        await harness.engine.belief("rec-1")


async def test_beliefs_propagates_rather_than_returning_a_page_it_could_not_resolve() -> None:
    """A page has one chance to swallow the refusal per belief, and takes none of them.

    The refusal is placed on the **second** belief's batch deliberately: a listing
    that resolved each summary independently and kept the ones that succeeded would
    return a one-element page here, which reads to a caller as "that is all the
    beliefs there are" — the same indistinguishability as the tombstone above, one
    level up. Pinned on ``beliefs`` rather than inferred from ``belief`` because
    ``Engine._beliefs`` walks the page itself, so nothing about the single-belief
    path constrains what a partial page would do.
    """
    store = RefusingCitationStore(now=lambda: AT, refuse_after=1)
    harness = Harness(memory=store)
    await _derived_with_two_episodes(harness)
    await harness.memory.add(_episode_record("ep-3", "they wrote 20 °C"))
    await harness.memory.add(
        _record("rec-2", source=MemorySource.INFERRED, confidence=_STORED, evidence=("ep-3",))
    )
    store.arm()

    with pytest.raises(MemoryStoreError):
        await harness.engine.beliefs()

    assert store.batches > 1, "the refusal landed after a belief had already resolved"


# --- the deferred-question surface, through the façade (ADR-0078 §8, §9) ----


async def test_a_parked_deferred_question_is_listed_and_answered_through_the_facade() -> None:
    """The façade's question reach, in one pass (ADR-0078 §8 reach 2).

    The loop parks the question, as any producer that rules ``ASK_USER`` does;
    ``questions`` lists it and ``answer`` commits it. The façade is the only surface
    `interfaces` has (ADR-0042 §1), and ``learn`` no longer reaches it (ADR-0293 §11).
    """
    harness = Harness()
    harness.policy_for_writer.kind = MemoryDecisionKind.ASK_USER

    [written] = await harness.loop.learn(feedback())
    assert written.admission is not None
    assert written.admission.deferral is not None

    [question] = await harness.engine.questions()
    assert question.id == written.admission.deferral.id
    assert question.state is QuestionState.OPEN
    assert await harness.engine.interrupted_questions() == (), "the two reads are disjoint"

    harness.policy_for_writer.kind = MemoryDecisionKind.ACCEPT
    answered = await harness.engine.answer(question.id, accept=True)

    assert answered.kind is AnswerKind.APPLIED
    assert answered.record_id is not None
    assert await harness.engine.belief(answered.record_id) is not None
    assert await harness.engine.questions() == (), "and it is no longer waiting"


async def test_forget_question_relays_the_disposal_and_reports_an_unknown_id() -> None:
    """§9's first recovery step, relayed unconditionally (ADR-0007)."""
    harness = Harness()
    harness.policy_for_writer.kind = MemoryDecisionKind.ASK_USER
    [written] = await harness.loop.learn(feedback())
    assert written.admission is not None
    assert written.admission.deferral is not None
    question_id = written.admission.deferral.id

    assert await harness.engine.forget_question(question_id) is True
    assert await harness.engine.forget_question(question_id) is False
    assert await harness.engine.questions() == ()


async def test_the_question_surface_is_refused_while_the_engine_is_shutting_down() -> None:
    """Every façade method rejects new work once ``aclose`` has been entered (§2)."""
    harness = Harness()
    await harness.engine.aclose()

    for call in (
        harness.engine.questions(),
        harness.engine.interrupted_questions(),
        harness.engine.answer("q-1", accept=True),
        harness.engine.forget_question("q-1"),
    ):
        with pytest.raises(RuntimeError, match="shutting down"):
            await call


# --- ADR-0119 §8: one OPERATION trace per call, at one wiring point -----


#: Public ``Engine`` methods that are not an operation and emit nothing.
#:
#: ``aclose`` alone, and it is not an oversight. Shutdown is not work the engine
#: was asked to do — it is the engine ceasing to accept work — and it is the one
#: public method that deliberately does *not* run through ``_tracked``: tracing it
#: would put a trace's append inside the drain that exists to wait for appends,
#: and the ``TraceSink`` may already be closed by the time it returned.
_UNTRACED = frozenset({"aclose"})


class _TrackedScan(ast.NodeVisitor):
    """Collect every ``self._tracked(...)`` call and the method it sits in."""

    def __init__(self) -> None:
        self._scope: list[str] = []
        #: ``(enclosing method, the seam literal or None)`` per call found.
        self.found: list[tuple[str, str | None]] = []
        #: Every ``async def`` inside ``class Engine``, by name.
        self.methods: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if self._scope == ["Engine"]:
            self.methods.append(node.name)
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "_tracked",
            "_activation_task",
        }:
            seam = (
                next((item.value for item in node.keywords if item.arg == "seam"), None)
                if node.func.attr == "_activation_task"
                else node.args[1]
                if len(node.args) > 1
                else None
            )
            if self._scope[-1] in {"_receive", "_streamed"}:
                # ADR-0274: compatibility methods delegate one admission. The
                # private dispatcher uses the projection selected at that entry.
                assert isinstance(seam, ast.Attribute)
                assert seam.attr == "method"
                assert isinstance(seam.value, ast.Name)
                assert seam.value.id == "projection"
            elif self._scope[-1] == "_read_in":
                # ADR-0293 §6: the chat's reader admits its activation from no public
                # call — it is the channel's own spoke — so the seam it is traced under
                # is the reader's, a literal, and is no public operation's.
                assert isinstance(seam, ast.Constant)
                assert seam.value == "chat_reader"
            else:
                literal = seam.value if isinstance(seam, ast.Constant) else None
                self.found.append((self._scope[-1], literal if isinstance(literal, str) else None))
        if isinstance(node.func, ast.Attribute) and node.func.attr == "_receive":
            projection = next(item.value for item in node.keywords if item.arg == "projection")
            assert isinstance(projection, ast.Call)
            assert isinstance(projection.func, ast.Name)
            assert projection.func.id == "ChannelProjection"
            projected_label = projection.args[0]
            assert isinstance(projected_label, ast.Constant)
            assert isinstance(projected_label.value, str)
            self.found.append((self._scope[-1], projected_label.value))
        self.generic_visit(node)


def _tracked_scan() -> _TrackedScan:
    """Parse ``orchestration/engine.py`` and scan it for the wiring point."""
    source = Path(engine_module.__file__).read_text(encoding="utf-8")
    scan = _TrackedScan()
    scan.visit(ast.parse(source, filename=engine_module.__file__))
    return scan


def test_every_public_operation_reaches_the_one_wiring_point_exactly_once() -> None:
    """ADR-0119 §8 and §5's one-crossing rule, held structurally rather than by drill.

    §8 places the envelope at ``_tracked`` precisely because it "already wraps every
    public method" — so the claim that makes the placement sound is that the set of
    public methods and the set of traced ones are the same set. Driving all
    twenty-three through a harness would need twenty-three fixtures and would still
    say nothing about the twenty-fourth somebody adds next month.

    Exactly once, not at least once: "one crossing of a seam produces at most one
    trace" (§5), and a method that reached the wiring point twice would record one
    operation as two — inflating every denominator drawn from the stream.
    """
    scan = _tracked_scan()
    expected = {name for name in scan.methods if not name.startswith("_")} - _UNTRACED
    traced = [method for method, _ in scan.found]

    assert sorted(traced) == sorted(expected), (
        "every public operation is traced once and only public operations are"
    )


def test_each_seam_label_is_the_literal_name_of_its_own_method() -> None:
    """The label a measure filters on is the surface a caller invoked (§2, §3).

    Two properties at once. The label is a **literal constant in the emitting
    module**, which is §2's second clause — anything computed at runtime is a string
    the tier discipline cannot vouch for. And it is the method's own name, so a
    measure grouping by seam is grouping by operation rather than by whatever the
    author of the twenty-fourth method happened to type; a seam that drifted from
    its method would silently merge two operations into one population.
    """
    mislabelled = {method: seam for method, seam in _tracked_scan().found if seam != method}

    assert mislabelled == {}, "each _tracked call passes its own method's name"


async def test_the_maintenance_operation_carries_its_three_counts() -> None:
    """§5's one-crossing rule: the sweep's detail rides on the sweep's own trace.

    "A job with detail the envelope cannot see returns it in the operation's own
    result type, where it becomes metrics on that operation's one trace, rather than
    emitting a second record for the same run."
    """
    traces = FakeTraceRetention()
    traces.hold(_aged(400), _aged(1))
    harness = Harness(traces=traces)

    await harness.engine.purge_expired()

    (trace,) = harness.trace_sink.recorded
    assert trace.seam == "purge_expired"
    assert dict(trace.metrics) == {"records": 0, "questions": 0, "traces": 1}


async def test_a_sweep_that_did_not_run_omits_its_key_rather_than_reporting_zero() -> None:
    """§3's observation rule, on the one metric in this lane that can be unobserved.

    "A metric key appears in a trace only when the quantity it names was
    **observed**. An absent key means *not observed* and never zero." A keep-forever
    horizon does not call the trace sweep at all, so a ``0`` here would report a
    store swept clean by a sweep nobody ran — and would do it on the deployment
    whose whole point is that nothing is deleted.
    """
    harness = Harness(trace_retention=None)

    await harness.engine.purge_expired()

    (trace,) = harness.trace_sink.recorded
    assert "traces" not in trace.metrics
    assert dict(trace.metrics) == {"records": 0, "questions": 0}


def test_a_halted_consolidation_reads_as_incomplete() -> None:
    """ADR-0111 §9's third clause, given ADR-0119 §3's value.

    "A run that halts under §5 without processing its remaining work is recorded as
    a completed run that did not exhaust its work, not as a failure." Recording it
    as ``OK`` makes a job that has stopped making progress invisible; recording it
    as ``FAULT`` makes a queue at its cap indistinguishable from a broken store.

    ``halted`` is carried by the outcome and **not** duplicated as a metric, so the
    two cannot disagree; ``exhausted`` is a different fact and is carried, because a
    run that spent its budget and one that halted are told apart only by the pair.
    """
    halted = engine_module._consolidated(ConsolidationReport(chunks=2, halted=True))
    spent = engine_module._consolidated(ConsolidationReport(chunks=2, exhausted=False))

    assert halted.outcome is TraceOutcome.INCOMPLETE
    assert spent.outcome is TraceOutcome.OK
    assert "halted" not in halted.metrics
    assert halted.metrics["exhausted"] is False
    assert halted.metrics["chunks"] == 2


async def test_a_result_too_large_to_return_records_the_refusal_not_a_success() -> None:
    """The trace and the caller's answer must agree (ADR-0119 §3, §8).

    ``_checked`` measures the *result* against ADR-0084 §4's limit, and it used to
    run one frame outside the traced region — so an operation whose page would not
    fit recorded ``OK`` while its caller received an ``OversizedValueError``. A
    stream in which a refused call is indistinguishable from a served one is the
    lie §5 spends its clauses refusing, arriving through placement instead of
    through I/O.

    The refusal is ``REFUSED`` rather than ``FAULT``: a contract limit answered is
    the system working, and ADR-0084 §4 puts the same limit on the way in.

    Driven through ``standing_grants``, which takes no arguments at all, so a
    one-byte ceiling cannot be tripped by the *argument* check that runs before
    ``_tracked`` — an operation refused there emits nothing at all, which is the
    separate gap #855 carries and not the one this case is about.
    ``pending_confirmations`` drove it until it retired (ADR-0309 §5:1).
    """
    harness = Harness()
    harness.engine._max_payload_bytes = 1

    with pytest.raises(OversizedValueError):
        await harness.engine.standing_grants()

    (trace,) = harness.trace_sink.recorded
    assert trace.seam == "standing_grants"
    assert trace.outcome is TraceOutcome.REFUSED
    assert trace.fault_class == "OversizedValueError"


async def test_a_maintenance_report_is_not_measured_against_the_payload_limit() -> None:
    """``checked`` is per operation, and the four maintenance ones are exempt.

    ADR-0085 §1 fixes the promoted ``AssistantEngine`` surface and none of
    ``start``/``purge_expired``/``consolidate`` is on it: their reports
    go to the hub's scheduler in-process and never cross a wire (ADR-0083 §8). They
    were never measured before this lane and they are not measured now — the flag
    exists so that stays a stated fact rather than an accident of which call site
    happened to be wrapped.
    """
    harness = Harness()
    harness.engine._max_payload_bytes = 1

    report = await harness.engine.purge_expired()

    assert report.traces == 0
    (trace,) = harness.trace_sink.recorded
    assert trace.outcome is TraceOutcome.OK


# --- ADR-0151 §6: the connection surface is not traced -----------------------


async def test_no_connection_operation_is_recorded_in_a_trace() -> None:
    """ADR-0151 §6: "No provisioning act, and no operation on this surface, is
    recorded in a trace (ADR-0141), an ``AuditTrail``, a conversation or a plan."

    **The prohibition is categorical rather than credential-scoped**, and that is
    what makes it easy to get wrong. An ``OPERATION`` trace records the seam, the
    outcome, the elapsed time and the fault class — never an argument — so nothing
    about a credential leaks through one, and an implementation reasoning only
    about disclosure would route these five through ``_tracked``'s default like
    every other method and pass every other test in this lane.

    What §6 forecloses is the **act being recorded at all**, and the reason is
    legible in ADR-0151 §18: a connection record deliberately carries *no instant*
    (ADR-0149 §3), so a trace of ``connect_account`` would reintroduce a
    timestamped record of the owner's act through a different door — which §18
    defers to "the first surface that has to answer 'when did I connect this?'".

    **The control is the load-bearing half.** An engine that emitted no traces at
    all would satisfy the first assertion and break ADR-0119 §8 wholesale, so a
    traced operation runs in the same harness and must still appear.
    """
    harness = Harness()

    record = await harness.engine.connect_account(
        identity="ada@example.com", credential=secret_value(SecretStr("hunter2-secret"))
    )
    await harness.engine.reprovision_account(
        record.reference,
        identity="ada@example.com",
        credential=secret_value(SecretStr("rotated-secret")),
    )
    await harness.engine.disconnect_account(record.reference)
    await harness.engine.connected_accounts()
    await harness.engine.recent_connection_acts()
    # The control: an ordinary read, which ADR-0119 §8 requires to be traced.
    await harness.engine.beliefs()

    seams = [trace.seam for trace in harness.trace_sink.recorded]
    assert seams == ["beliefs"], (
        "ADR-0151 §6 forbids a trace for any operation on the connection surface; "
        f"these were recorded: {seams}"
    )


async def test_the_connection_surface_is_still_drained_though_it_is_not_traced() -> None:
    """ADR-0042 §2 survives ADR-0151 §6, which is the half a suppression can break.

    Suppressing the trace and suppressing the *tracking* are one line apart, and
    only the second is forbidden to be kept: the connection store is
    connection-owning like every other, so an untracked provisioning act would let
    :meth:`~ai_assistant.orchestration.engine.Engine.aclose` close the store out
    from under ADR-0148 §6's three writes.

    Asserted through the drain rather than through an attribute: a call in flight
    when ``aclose`` begins is awaited to completion, so the record it was writing
    is there afterwards.
    """
    harness = Harness()

    running = asyncio.ensure_future(
        harness.engine.connect_account(
            identity="ada@example.com", credential=secret_value(SecretStr("hunter2-secret"))
        )
    )
    await asyncio.sleep(0)
    await harness.engine.aclose()
    record = await running

    assert record.state is ProvisioningState.ACTIVE
    assert [trace.seam for trace in harness.trace_sink.recorded] == []


# --- ADR-0181 §4, §10: the origin the engine computes from its own selection ---
# Kept in one block so a rebase across another lane's edits to this module moves
# it whole rather than through it.


def _external_belief(record_id: str = "rec-external") -> SemanticMemory:
    """A belief in the ``ATTESTED`` band, which is where externality is recorded.

    ``rests_on_recorded_external_content`` is true of it by ``band_of`` alone
    (ADR-0106 §1): the band is reached only through ``MemorySource.EXTERNAL``,
    whose whole meaning is that a connected source reported the belief. Its content
    carries the utterance's terms so the store's lexical search selects it.
    """
    return SemanticMemory(
        id=record_id,
        content="send it to the address in the invite",
        fact="send it to the address in the invite",
        validity=Validity(),
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=0.9,
            last_updated=AT,
            attestation=Attestation(reported_by="calendar:work", reported_at=AT),
        ),
    )


@pytest.mark.parametrize("method", ["episodes", "episode_chunk"])
async def test_episode_inspection_is_drained_before_shutdown(method: str) -> None:
    """The store cannot close while an admitted inspection read still owns it."""
    memory = FakeMemoryStore(now=lambda: AT)
    held = memory.suspend_next_operation()
    closed = asyncio.Event()

    async def close() -> None:
        closed.set()

    harness = Harness(memory=memory, closers=(close,))
    read = asyncio.ensure_future(
        harness.engine.episodes() if method == "episodes" else harness.engine.episode_chunk("")
    )
    try:
        await held.reached()
        closing = asyncio.ensure_future(harness.engine.aclose())
        await asyncio.sleep(0)
        assert not closed.is_set()
        held.release()
        await read
        await closing
        assert closed.is_set()
    finally:
        held.release()
        await harness.engine.aclose()
