"""The CLI adapter: thin rendering and the converse/resume relay (ADR-0042 §4, §6, §7).

Rendering is checked against captured Rich output; the turn flow is driven against
a real :class:`Engine` assembled from canonical fakes (the adapter cannot tell it
from the production engine — that is the point of the façade). Nothing here builds
the production, model-backed engine, so no network or key is needed.
"""

from __future__ import annotations

import ast
import asyncio
import errno
import re
import shlex
import socket
import sys
from datetime import UTC, datetime, timedelta
from inspect import getsource, isfunction, unwrap
from io import StringIO
from itertools import count, product
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
import typer.main
from cli_open_recorder import wire_recording_opens
from rich.console import Console
from typer.core import TyperGroup
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import (
    ConfigurationError,
    DeferralStoreError,
    GrantError,
    InvalidGrantError,
    MemoryStoreError,
    ModelUnavailableError,
    OversizedValueError,
    PlanningError,
    UngrantableSourceError,
)
from ai_assistant.core.types import (
    ActionPlan,
    AnswerKind,
    AnswerOutcome,
    Attestation,
    Belief,
    BeliefBand,
    BeliefSummary,
    ClassReach,
    Confirmation,
    ConfirmationEgress,
    ContinuationToken,
    CostBasis,
    CurrentContext,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    Disposition,
    EgressDestination,
    EgressSpan,
    Evidence,
    ExecutionState,
    FeedbackEvent,
    FeedbackKind,
    Goal,
    GrantScope,
    HeldNotification,
    Idempotency,
    IngestSummary,
    LearnDecision,
    LearnOutcome,
    MemoryKind,
    MemorySource,
    Message,
    NotificationCandidate,
    NotificationCondition,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
    ObservationReport,
    ObservedProposal,
    OperationConfirmation,
    PlanStep,
    Provenance,
    Question,
    QuestionState,
    QueuedQuestion,
    QueueOutcome,
    QuietWindow,
    ReplyChunk,
    Retirement,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    StepExecution,
    StepFailure,
    StepOutcome,
    StepStatus,
    SuccessorLink,
    TimeOfDay,
    ToolCost,
    ToolDefinition,
    TurnOutcome,
    TurnResult,
    Warrant,
    encodable_text,
)
from ai_assistant.interfaces import cli
from ai_assistant.orchestration import (
    ComposingStage,
    ConnectionOperations,
    ConversationLifecycle,
    Engine,
    GrantOperations,
    HeldSource,
    LearningLoop,
    MemoryWriteStage,
    ObservationStage,
    QuestionStage,
    StepExecutor,
    StepRunner,
)
from ai_assistant.orchestration.upcoming import NOTIFICATION_CLASS
from ai_assistant.readers.calendar import CALENDAR_READER_NAME
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAssistantEngine,
    FakeAuditTrail,
    FakeConnectionProvisioner,
    FakeContextProvider,
    FakeConversationStore,
    FakeDeferralStore,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeModelProvider,
    FakeObserver,
    FakePlanStore,
    FakeSourceGrantStore,
    FakeSourceReadTrail,
    FakeStreamingCompleter,
    FakeToolInvoker,
    FakeTraceRetention,
    FakeTraceSink,
    FakeTranscriptArchive,
    FakeTranscriptArchiveWriter,
    StreamAttempt,
)
from ai_assistant.wire import TransportError
from ai_assistant.wire.address import sun_path_limit

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.types import FrozenJson, MemoryRecord, ShownFile, SourceGrant


AT = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)


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

    Required rather than optional on the façade, like ``questions`` and
    ``observation``: the four grant methods are on the Protocol, so an engine that
    could be built without them is one whose surface is conditionally present. Empty
    ``sources`` is the ordinary deployment — a reader ships disabled, so nothing is
    grantable until one is configured (ADR-0093 §7).
    """
    return GrantOperations(
        store=FakeSourceGrantStore(),
        sources=sources,
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


#: The route the harness's observation stage reports (ADR-0077 §3). In production
#: the composition root supplies it from ``Settings``; here it is fixed so a case
#: can assert the terminal names the route that read the episodes.
OBSERVER_ROUTE = "anthropic:claude-opus-4-8"
PATIENT = timedelta(seconds=30)
CAPABILITY = "send_email"
PARAMETERS = {"to": "someone@example.com"}


def _no_routed_card(_card: OperationConfirmation) -> bool:
    """The routed approver for a turn that is not expected to route (ADR-0197 §7).

    Every case in this file that predates routing drives an ordinary turn, so
    reaching this is a case whose engine started parking a routed operation without
    the case saying what to answer — which would otherwise pass silently on whichever
    of ``True`` or ``False`` a placeholder happened to return. The cases that *do*
    answer a routed card pass their own.
    """
    raise AssertionError("this turn was not expected to park a routed operation")


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=100))
    return buffer


def tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """A declaration ``FakeActionPolicy`` allows outright."""
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
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def confirmable(tool_id: str = "smtp") -> ToolDefinition:
    """A declaration the fake policy confirms: it discloses off-device."""
    return tool(tool_id, discloses=(DataTier.PERSONAL,))


class _OneStepPlanner:
    """Plans one step for the goal it is given (so ``plan.goal_id`` matches)."""

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
    ) -> ActionPlan:
        step = PlanStep(
            id="step-1", intent="send the note", capability=CAPABILITY, parameters=PARAMETERS
        )
        return ActionPlan(
            id=f"{goal.id}-plan",
            goal_id=goal.id,
            steps=(step,),
            created_at=AT,
            rationale="send the note",
        )


async def _succeeds(parameters: object, *, idempotency_key: str | None) -> None:
    """A tool that does nothing and succeeds."""


def _observation(
    conversations: FakeConversationStore, memory: FakeMemoryStore, writes: MemoryWriteStage
) -> ObservationStage:
    """The observation stage over the same stores the rest of the engine holds.

    Wired the way the composition root wires it (ADR-0077 §8): one memory store for
    selection, retrieval and the write path, so a proposal's citations resolve
    against the store its episodes came from.
    """
    return ObservationStage(
        observer=FakeObserver(),
        conversations=conversations,
        memory=memory,
        writes=writes,
        batch_size=20,
        route=OBSERVER_ROUTE,
    )


def _engine(
    *,
    tools: tuple[ToolDefinition, ...] = (),
    policy: FakeActionPolicy | None = None,
    closers: Sequence[Callable[[], Awaitable[None]]] = (),
    composing: ComposingStage | None = None,
) -> Engine:
    """A real ``Engine`` over canonical fakes, driving a one-step plan."""
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    # The seam claims through the **same** trail the runner records rulings into
    # (ADR-0192 §9's wiring clause); a second one would refuse every claim.
    invoker = FakeToolInvoker(
        [(definition, _succeeds) for definition in tools], ledger=trail, gate=trail
    )
    memory = FakeMemoryStore(now=lambda: AT)
    writer = FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=lambda: AT)
    deferrals = FakeDeferralStore(now=lambda: AT)
    writes = MemoryWriteStage(writer=writer, deferrals=deferrals)
    loop = LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=writes,
        planner=_OneStepPlanner(),
        feedback=FakeFeedbackProcessor(),
        now=lambda: AT,
        id_factory=lambda: "g-1",
        # The same object the runner below resolves against (ADR-0211 §3): a
        # loop told one vocabulary while selection resolved against another
        # could plan a step the selecting registry never advertised.
        registry=invoker,
    )
    ids = iter(f"d-{n}" for n in range(1, 50))
    runner = StepRunner(
        plans=plans,
        registry=invoker,
        policy=policy if policy is not None else FakeActionPolicy(),
        trail=trail,
        executor=StepExecutor(plans=plans, registry=invoker, invoker=invoker, now=lambda: AT),
        now=lambda: AT,
        id_factory=lambda: next(ids),
    )
    conversations = FakeConversationStore(now=lambda: AT)
    return Engine(
        composing=composing if composing is not None else _composing(),
        grant_operations=_grant_operations(),
        connection_operations=_connection_operations(),
        loop=loop,
        runner=runner,
        plans=plans,
        trail=trail,
        spend=trail,
        # ADR-0186 §10's read trail. Empty and unwired to any driver here: this
        # module's cases are about what the CLI renders, and the two read
        # operations have no CLI door yet — §9's commands are the decision pair's
        # and the read pair's consumer lane is its own (ADR-0186 §11).
        reads=FakeSourceReadTrail(),
        memory=memory,
        deferrals=deferrals,
        # The narrow deletion seam and its horizon (ADR-0119 §7, §10). Required on
        # the façade, and nothing in this module sweeps: an adapter test is about
        # what the CLI renders, not about the maintenance operation.
        traces=FakeTraceRetention(),
        trace_sink=FakeTraceSink(),
        trace_retention=timedelta(days=365),
        conversations=ConversationLifecycle(
            conversations=conversations,
            memory=memory,
            retention=timedelta(days=30),
            now=lambda: AT,
            archive=FakeTranscriptArchiveWriter(),
            archive_enabled=True,
        ),
        observation=_observation(conversations, memory, writes),
        questions=QuestionStage(writer=writer, deferrals=deferrals, memory=memory, now=lambda: AT),
        closers=closers,
        archive=FakeTranscriptArchive(),
    )


# --- rendering: escaping is the adapter's, per target (ADR-0042 §4) ------


def test_confirmation_render_neutralises_control_sequences_and_markup(output: StringIO) -> None:
    """A parameter value's ANSI escape and Rich markup are shown, not acted on (§4)."""
    confirmation = Confirmation(
        tool_id="smtp",
        tool_description="Send an email.",
        parameters={"body": "wipe\x1b[2Jscreen and [red]shout[/red]"},
        reason="this discloses data off-device",
        token=ContinuationToken(handle="tok"),
        egress=None,
    )
    cli._render_confirmation(confirmation)
    rendered = output.getvalue()

    assert "\x1b[2J" not in rendered  # the raw control sequence was neutralised
    assert "\x1b" not in rendered  # no escape byte at all
    assert "[red]" in rendered  # markup is shown literally, not interpreted as colour
    assert "this discloses data off-device" in rendered  # the ruling reason is surfaced


# --- ADR-0178 §7: the floor an egress confirmation's rendering owes ----------
# One block, kept together so a rebase across another lane's fixture edits in
# this module moves it whole rather than through it.

_EGRESS_IDENTITY = "work@example.com"


def _egress_span(  # noqa: PLR0913 — one keyword per field of the span being built
    argument: str,
    *,
    index: int | None = None,
    extent: int = 5,
    canonical: str | None = None,
    supplied: str | None = None,
    tier: DataTier | None = None,
    provenance: DiscloserProvenance = DiscloserProvenance.SYSTEM_SELECTED,
) -> EgressSpan:
    """One span, with a destination exactly where ``canonical`` is given."""
    destination = (
        None
        if canonical is None
        else EgressDestination(
            protocol=DestinationProtocol.SMTP,
            supplied=supplied if supplied is not None else canonical,
            canonical=canonical,
        )
    )
    return EgressSpan(
        argument=argument,
        index=index,
        provenance=provenance,
        extent=extent,
        tier=tier,
        destination=destination,
    )


def _parameters_for(spans: Sequence[EgressSpan]) -> dict[str, FrozenJson]:
    """The arguments ``spans`` decompose, built so the fixture is a real request.

    ADR-0150 §4 makes the spans the arguments and
    :class:`~ai_assistant.core.types.ActionRequest` refuses a binding that does not
    describe the call's own parameters, so a confirmation whose spans name nothing
    the parameters hold is a shape production cannot reach. ADR-0233 §8 renders each
    span's value *from* ``parameters``, which is what makes the correspondence
    load-bearing here rather than incidental: a fixture that kept a fixed pair of
    arguments would leave every case in this block testing the withheld-card path.

    An occurrence's own supplied form is used where it carries one, because
    :func:`~ai_assistant.core.types._span_defect` refuses a span whose destination
    states a supplied form the argument's value does not hold. Everything else is
    filled to the span's stated extent.
    """
    built: dict[str, FrozenJson] = {}
    indexed: dict[str, dict[int, str]] = {}
    for span in spans:
        occurrence = span.destination
        value = occurrence.supplied if occurrence is not None else "x" * span.extent
        if span.index is None:
            built[span.argument] = value
        else:
            indexed.setdefault(span.argument, {})[span.index] = value
    for argument, elements in indexed.items():
        built[argument] = [elements[index] for index in sorted(elements)]
    return built


def _egress_confirmation(
    *spans: EgressSpan,
    identity: str = _EGRESS_IDENTITY,
    planned_with_external_content: bool = False,
    coverage: SpanCoverage = SpanCoverage.NOT_COVERED,
    parameters: Mapping[str, FrozenJson] | None = None,
) -> Confirmation:
    """A parked egress confirmation carrying ``spans``, over the arguments they name."""
    return Confirmation(
        tool_id="smtp",
        tool_description="Send an email.",
        parameters=_parameters_for(spans) if parameters is None else parameters,
        reason="this discloses data off-device",
        token=ContinuationToken(handle="tok"),
        egress=ConfirmationEgress(
            account_identity=identity,
            spans=spans,
            planned_with_external_content=planned_with_external_content,
            coverage=coverage,
        ),
    )


#: ADR-0181 §6's two arms, spelled here so a reworded renderer fails rather than a
#: test quietly matching a shorter substring of whichever arm it was handed.
_PLANNED_OVER_EXTERNAL: Final = (
    "Planned over: material this assistant selected, which includes a record "
    "marked as resting on recorded external content"
)
_PLANNED_OVER_NOTHING_MARKED: Final = (
    "Planned over: material this assistant selected, in which no record is "
    "marked as resting on recorded external content"
)


def test_an_egress_confirmation_names_the_account_the_set_and_every_occurrence(
    output: StringIO,
) -> None:
    """ADR-0178 §7: the floor, before the user's answer is collected.

    ADR-0148 §8's fourth clause in full — the connected account's identity, the
    canonical destination set in both forms, and the payload description — over
    the mixed binding the clause is hardest on: ``to`` bearing a destination and
    ``body`` not, tested as one case rather than assumed away.
    """
    cli._render_confirmation(
        _egress_confirmation(
            _egress_span("body", extent=5),
            _egress_span(
                "to", canonical="alice@example.org", supplied="Alice@Example.ORG", extent=17
            ),
        )
    )
    rendered = _flowed(output.getvalue())

    assert _EGRESS_IDENTITY in rendered  # the connected account (§8's first noun)
    assert "alice@example.org" in rendered  # the canonical form (§2's second)
    assert "Alice@Example.ORG" in rendered  # the supplied form (§2's first)
    assert "smtp" in rendered  # the protocol the equivalence was computed under
    assert "to" in rendered  # every occurrence, by the argument it was selected by
    assert "body" in rendered
    assert "this discloses data off-device" in rendered  # the ruling's own reason


def test_a_destination_less_occurrence_is_rendered_and_names_no_recipient(
    output: StringIO,
) -> None:
    """ADR-0178 §7: both forms for the occurrences that carry a destination, and those only.

    A span with no destination is still rendered — by its argument, its
    provenance, its extent and its tier — and names no recipient. Dropping it, or
    rendering it as though it named one, would fail the whole-rendering clause in
    the two opposite directions.
    """
    cli._render_confirmation(
        _egress_confirmation(
            _egress_span(
                "body",
                extent=11,
                tier=DataTier.PERSONAL,
                provenance=DiscloserProvenance.USER_AUTHORED,
            )
        )
    )
    rendered = _flowed(output.getvalue())

    assert "body" in rendered
    assert "11 code points" in rendered
    assert "personal" in rendered  # the tier it states
    assert "you composed it" in rendered  # ADR-0146 §1's discloser, not a claim about content
    assert "no destination" in rendered


def test_an_account_only_set_names_the_account_as_the_destination(output: StringIO) -> None:
    """ADR-0178 §7: not "no recipients" — ADR-0148 §2's third clause is the account."""
    cli._render_confirmation(_egress_confirmation(_egress_span("body", extent=5)))
    rendered = _flowed(output.getvalue())

    assert "the connected account" in rendered
    assert rendered.count(_EGRESS_IDENTITY) >= 2  # named as the account and as the destination


def test_one_recipient_named_twice_is_one_set_member_and_two_disclosures(
    output: StringIO,
) -> None:
    """ADR-0150 §10's third clause, which is why the occurrences travel at all.

    A confirmation naming one argument for a member reached by two has understated
    the call, and one showing only the occurrences leaves the user to deduplicate
    in their head. Both are rendered, and the arithmetic is `core`'s.
    """
    confirmation = _egress_confirmation(
        _egress_span("cc", canonical="alice@example.org", supplied="Alice@Example.ORG", extent=17),
        _egress_span("to", canonical="alice@example.org", supplied="alice@example.org", extent=17),
    )
    assert confirmation.egress is not None
    assert len(confirmation.egress.canonical_destination_set) == 1
    cli._render_confirmation(confirmation)
    rendered = _flowed(output.getvalue())

    assert "cc" in rendered
    assert "to" in rendered
    assert "Alice@Example.ORG" in rendered  # the two supplied forms are both shown
    assert "alice@example.org" in rendered


def test_every_occurrence_is_rendered_none_omitted(output: StringIO) -> None:
    """ADR-0178 §7: occurrences are rendered whole, none truncated or hidden."""
    spans = tuple(
        _egress_span("to", index=index, canonical=f"user{index}@example.org", extent=18)
        for index in range(12)
    )
    cli._render_confirmation(_egress_confirmation(*spans))
    rendered = _flowed(output.getvalue())

    for index in range(12):
        assert f"user{index}@example.org" in rendered
        assert f"to[{index}]" in rendered


def test_a_non_egress_confirmation_renders_as_it_did_and_claims_nothing(
    output: StringIO,
) -> None:
    """ADR-0178 §7's last clause: it owes none of the floor and asserts none of it.

    In particular it makes no claim about recipients — neither that there are
    none, nor that the call transmits nothing. ``egress is None`` states that the
    ruling was taken over no egress binding, and nothing more (§4).
    """
    cli._render_confirmation(
        Confirmation(
            tool_id="notes",
            tool_description="Write a note.",
            parameters={"body": "hello"},
            reason="an unknown cost",
            token=ContinuationToken(handle="tok"),
            egress=None,
        )
    )
    rendered = _flowed(output.getvalue())

    assert "Write a note." in rendered
    assert "an unknown cost" in rendered
    for absent in (
        "Account:",
        "Goes to",
        "Describing",
        "the connected account",
        "no destination",
        # ADR-0181 §6's last clause: a confirmation whose `egress` is `None` owes the
        # origin line too, and asserts neither of its arms.
        "Planned over:",
        "external content",
        # ADR-0233 §8's last clause, one axis over: neither the coverage line nor the
        # values block, and no claim in either direction about what it draws on.
        "What it draws on:",
        "What it would send",
        "this assistant stores",
    ):
        assert absent not in rendered


def test_the_new_members_are_neutralised_on_the_way_out(output: StringIO) -> None:
    """ADR-0178 §7: inserted as data, neutralised for this target, like the rest.

    Being derived from a binding relaxes nothing: ``argument`` is a
    caller-influenced key (ADR-0150 §13) and a ``supplied`` form is a string a
    model produced, so both reach the terminal through :func:`cli._safe` exactly
    as ``parameters`` already does.
    """
    cli._render_confirmation(
        _egress_confirmation(
            _egress_span(
                "wipe\x1b[2Jscreen",
                canonical="alice@example.org",
                supplied="[red]shout[/red]",
                extent=17,
            ),
            identity="acct\x1b[2Jname",
        )
    )
    rendered = output.getvalue()

    assert "\x1b" not in rendered  # no escape byte reaches the terminal at all
    assert "[red]" in rendered  # markup is shown literally, not interpreted as colour


def test_a_call_planned_over_external_content_says_so_beside_the_whole_floor(
    output: StringIO,
) -> None:
    """ADR-0181 §10's clause for this lane, in the conjunction it states.

    "A confirmation carrying ``True`` renders the fact **and** every occurrence
    ADR-0178 §7's floor already requires" — so the floor is asserted here rather
    than in a separate case, because §6's sixth clause is precisely that nothing of
    it is suppressed, reordered or de-emphasised on the strength of the new fact. A
    test asserting only that the marker appears would pass a renderer that had
    dropped the recipients to make room for it.
    """
    cli._render_confirmation(
        _egress_confirmation(
            _egress_span("body", extent=5),
            _egress_span(
                "to", canonical="alice@example.org", supplied="Alice@Example.ORG", extent=17
            ),
            planned_with_external_content=True,
        )
    )
    rendered = _flowed(output.getvalue())

    assert _PLANNED_OVER_EXTERNAL in rendered  # §6's first clause, in the True state

    # ...and the whole of ADR-0178 §7's floor, unmoved.
    assert _EGRESS_IDENTITY in rendered  # the connected account
    assert "alice@example.org" in rendered  # the canonical form
    assert "Alice@Example.ORG" in rendered  # the supplied form
    assert "smtp" in rendered  # the protocol the equivalence was computed under
    assert "to" in rendered  # every occurrence, by the argument it was selected by
    assert "body" in rendered
    assert "this discloses data off-device" in rendered  # the ruling's own reason

    # §6's sixth clause is an ordering obligation as well as a membership one: the
    # account and the recipients keep their places, and the new line sits between
    # them rather than displacing either.
    assert rendered.index("Account:") < rendered.index(_PLANNED_OVER_EXTERNAL)
    assert rendered.index(_PLANNED_OVER_EXTERNAL) < rendered.index("Goes to:")
    assert rendered.index("Goes to:") < rendered.index("Describing:")


def test_a_call_no_selected_record_marked_renders_the_fact_too(output: StringIO) -> None:
    """ADR-0181 §6's fourth clause: rendered in **both** states.

    "A fact shown only when it is alarming is a fact a user learns to read as an
    alarm, and its absence as clearance" — and §10 makes the ``False`` case its own
    test in terms, because "a test asserting only that a marker is present when it
    is ``True`` does not satisfy this clause".

    The wording is asserted whole, which is what holds §6's third clause: this arm
    states that no *selected record carried the marker*, and a renderer that had
    shortened it to "no external content" would be issuing the assurance ADR-0181
    §7 says nothing in this corpus can give.
    """
    cli._render_confirmation(
        _egress_confirmation(
            _egress_span("to", canonical="alice@example.org", extent=17),
            planned_with_external_content=False,
        )
    )
    rendered = _flowed(output.getvalue())

    assert _PLANNED_OVER_NOTHING_MARKED in rendered
    assert _EGRESS_IDENTITY in rendered  # beside the floor here too, not instead of it
    assert "alice@example.org" in rendered


def test_neither_arm_names_a_source_a_span_or_a_verdict(output: StringIO) -> None:
    """ADR-0181 §6's second, fifth and sixth clauses, as absences on both arms.

    The clauses bar what a renderer would drift toward, so they are checked as
    absences: no source and no kind of source ("from a source you connected" is
    named in the ADR in terms), no attribution to an argument or a recipient, and
    no detection, score, risk level or claim that the call is malicious.

    The floor names the argument each occurrence was selected by, and ADR-0233 §8's
    block prints that argument's value under the same key, so the span check is
    scoped to the origin line itself rather than to the whole render.
    """
    for planned in (True, False):
        output.truncate(0)
        output.seek(0)
        cli._render_confirmation(
            _egress_confirmation(
                _egress_span("to", canonical="alice@example.org", extent=17),
                planned_with_external_content=planned,
            )
        )
        rendered = _flowed(output.getvalue())
        origin = rendered[rendered.index("Planned over:") :].split("Goes to:")[0]

        for forbidden in (
            "source you connected",
            "connected source",
            "malicious",
            "suspicious",
            "untrusted",
            "risk",
            "warning",
            "attack",
            "injected",
            "unsafe",
        ):
            assert forbidden not in origin.lower(), (planned, forbidden)
        # Never a statement about a span (§6's fifth clause).
        for span_word in ("alice@example.org", "Alice@Example.ORG", "argument", "recipient"):
            assert span_word not in origin, (planned, span_word)


# --- ADR-0233 §8: the floor a content-bearing confirmation owes --------------
# One block, for the reason the ADR-0178 block above gives. The three floors §15
# names — rendering, coverage and control — are asserted over this surface's own
# output, because §9's third condition is discharged by tests over each surface
# and by nothing a component could check at the ruling.

#: The gutter every line of a rendered value carries. Read from the module rather
#: than respelled, because :func:`cli._values_fit_this_terminal` measures against the
#: same constant: a test that carried its own copy would keep passing if the renderer
#: and the width rule drifted apart, which is the pair the constant exists to hold
#: together.
_VALUE_GUTTER: Final = cli._VALUE_GUTTER


def _value_lines(rendered: str) -> list[str]:
    """The rendered value block's lines, gutter stripped, in the order printed."""
    return [
        line[len(_VALUE_GUTTER) :]
        for line in rendered.split("\n")
        if line.startswith(_VALUE_GUTTER)
    ]


def _coverage_slice(rendered: str) -> str:
    """Just the coverage line, flowed — the subject of §8's own per-line clauses."""
    flowed = _flowed(rendered)
    return flowed[flowed.index("What it draws on:") :].split("What it would send")[0]


def test_every_spans_value_is_rendered_whole_before_the_answer(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0233 §8's first two clauses, over the case the ADR is actually about.

    "For every span the ``spans`` tuple carries, that span's own value, taken from
    ``Confirmation.parameters`` under ADR-0150 §4's decomposition" — and rendered
    **before it collects the user's answer**. The ordering is asserted at the moment
    the control is offered rather than by comparing two offsets in a buffer, because
    what §8 requires is that the bytes were on the screen when the question was put.
    """
    body = "Dear Alice,\n\nYou asked me to remind you about June.\n\nBest,\nLeo"
    confirmation = _egress_confirmation(
        _egress_span("body", extent=len(body)),
        _egress_span("to", canonical="alice@example.org", extent=17),
        parameters={"body": body, "to": "alice@example.org"},
    )
    shown: list[str] = []

    def _at_the_prompt(_text: str, *, default: bool = False) -> bool:
        shown.append(output.getvalue())
        return False

    monkeypatch.setattr(typer, "confirm", _at_the_prompt)
    assert cli._prompt_for_approval(confirmation) is False

    assert len(shown) == 1  # one control, offered once
    at_the_prompt = shown[0]
    assert _value_lines(at_the_prompt) == [*body.split("\n"), "alice@example.org"]
    # Keyed by ADR-0150 §4's own pair, so a reader can carry their eye from the
    # description to the value it describes.
    assert "    body:" in at_the_prompt
    assert "    to:" in at_the_prompt


def test_a_value_is_rendered_beside_the_description_and_never_instead_of_it(
    output: StringIO,
) -> None:
    """ADR-0233 §8's fourth clause: ADR-0178 §7's floor is unreduced beneath it.

    Both are on the screen now, which is why §7's sixth clause binds harder than
    before: a surface that merged them would be claiming the description states what
    the value says. So the account, the origin, the set, every occurrence and the
    payload description are all asserted here, in their order, with the values after
    them and before the reason.
    """
    cli._render_confirmation(
        _egress_confirmation(
            _egress_span("body", extent=5),
            _egress_span(
                "to", canonical="alice@example.org", supplied="Alice@Example.ORG", extent=17
            ),
        )
    )
    rendered = _flowed(output.getvalue())

    for kept in (
        _EGRESS_IDENTITY,  # the connected account
        "Planned over:",  # ADR-0181 §6's origin line
        "Goes to:",  # the canonical destination set
        "Describing:",  # the payload description
        "5 code points",  # which still states an extent rather than the text
    ):
        assert kept in rendered
    assert rendered.index("Describing:") < rendered.index("What it draws on:")
    assert rendered.index("What it draws on:") < rendered.index("What it would send, whole:")
    assert rendered.index("What it would send, whole:") < rendered.index("Why:")


def test_an_indexed_span_renders_its_own_element_and_not_the_whole_argument(
    output: StringIO,
) -> None:
    """ADR-0233 §8: "that argument's value's element at ``index``".

    An array-valued argument decomposes into one span per element (ADR-0150 §4), so
    each is shown under its own key. A surface that printed the whole array once
    against the first span would have rendered the second span's value nowhere the
    reader could attribute it.
    """
    cli._render_confirmation(
        _egress_confirmation(
            _egress_span("to", index=0, canonical="alice@example.org", extent=17),
            _egress_span("to", index=1, canonical="bob@example.org", extent=15),
        )
    )
    rendered = output.getvalue()

    assert "    to[0]:" in rendered
    assert "    to[1]:" in rendered
    assert _value_lines(rendered) == ["alice@example.org", "bob@example.org"]


def test_a_long_value_is_neither_truncated_elided_nor_collapsed(output: StringIO) -> None:
    """ADR-0233 §8's second clause, on the value that makes it expensive.

    Not truncated, not elided, not abbreviated, not summarised, not paraphrased and
    not collapsed behind a control the user must operate to see it. Every line of a
    two-hundred-line body is asserted individually rather than by a length, because a
    renderer that kept the first and last twenty would pass a length check on the
    ends and fail this one in the middle.
    """
    body = "\n".join(f"line {number} of the body" for number in range(200))
    cli._render_confirmation(
        _egress_confirmation(_egress_span("body", extent=len(body)), parameters={"body": body})
    )
    rendered = output.getvalue()

    assert _value_lines(rendered) == body.split("\n")
    for elision in ("\u2026", "...", "truncated", "show more", "[dim]+", "and 1"):
        assert elision not in rendered


def test_every_wrapped_continuation_of_a_value_keeps_the_gutter(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0233 §8's second and ninth clauses, on the display line rather than the buffer.

    Rich does not repeat a literal prefix on the continuations it wraps: handed one
    long line it emits the gutter once and puts the remainder at the margin, so a
    body would run past the marker within a line or two and those continuations would
    read as lines this adapter wrote. That is the regression
    :func:`cli._render_content` records an adversarial ``blocker`` for, one renderer
    over, and the wrapping is therefore taken by :func:`cli._render_egress_value`
    rather than left to the console.

    Asserted at a narrow width, over both shapes that wrap — an unbroken run, which
    folds, and ordinary words, which break at spaces — because they take different
    paths through Rich's wrapper. The pieces concatenate back to the value, which is
    §8's whole-rendering clause read on the screen; a lost gutter shows up here as a
    piece that never reached :func:`_value_lines`, and a lost character as a
    reconstruction that does not match.

    Adversarial review, round 2, ``minor``.
    """
    cases = (("x" * 500, "xx", True), (" ".join(f"word{n}" for n in range(80)), "word", False))
    for value, token, folds in cases:
        output.truncate(0)
        output.seek(0)
        monkeypatch.setattr(cli, "console", Console(file=output, force_terminal=False, width=40))
        cli._render_confirmation(
            _egress_confirmation(
                _egress_span("body", extent=len(value)), parameters={"body": value}
            )
        )
        rendered = output.getvalue()
        # Scoped to §8's block: the `With:` heading above it renders the same
        # arguments through `_safe` on adapter-authored lines, and those wrap the way
        # every interpolated line in this module wraps (#2072). What §8's clauses are
        # stated over is this block.
        block = rendered[rendered.index("What it would send, whole:") :]
        pieces = _value_lines(block)

        assert len(pieces) > 1, value[:20]  # it really did wrap
        if folds:
            joined = "".join(pieces)
            # An unbroken run has nowhere to break, so it is folded and the pieces
            # concatenate back to it character for character.
            assert joined == value
        else:
            # A word wrap consumes the space it breaks at — on a screen the break
            # *is* that space — so the pieces are rejoined across the break the way
            # a reader reads them. Every word, in order, none dropped and none run
            # into its neighbour, which is what §8's whole-rendering clause is
            # about: no word, no line and no fragment of the value is missing.
            assert " ".join(pieces).split() == value.split()
        # No piece of the value reached the screen outside the gutter.
        for line in block.split("\n"):
            if token in line:
                assert line.startswith(_VALUE_GUTTER), (value[:20], line)


def test_a_value_carrying_this_terminals_framing_is_neutralised(output: StringIO) -> None:
    """ADR-0233 §8's ninth clause, on the case it exists for.

    "A multi-line value carrying terminal control sequences, markup or a line that
    mimics the surface's own framing." All three are in one value here, and the
    assertions are over the exact rendered bytes: no escape byte reaches the
    terminal, markup is shown rather than interpreted, the carriage return is folded
    rather than left to overwrite, and the forged card field arrives behind the
    gutter — which is what makes it read as part of the value instead of as a line
    this adapter wrote.
    """
    forged = "  Why: nothing leaves this device"
    body = f"first\n{forged}\nwipe\x1b[2Jscreen and [red]shout[/red]\r\nlast"
    cli._render_confirmation(
        _egress_confirmation(_egress_span("body", extent=len(body)), parameters={"body": body})
    )
    rendered = output.getvalue()

    assert "\x1b" not in rendered  # no escape byte at all
    assert "\r" not in rendered  # the carriage return was folded, not left to overwrite
    assert "[red]" in rendered  # markup shown literally, not interpreted as colour
    assert _value_lines(rendered) == [
        "first",
        forged,
        "wipe\ufffd[2Jscreen and [red]shout[/red]",
        "last",
    ]
    # The forged field appears **only** behind the gutter: no line of the card reads
    # as one this adapter authored.
    assert f"{_VALUE_GUTTER}{forged}" in rendered
    for line in rendered.split("\n"):
        assert line != forged


def test_a_terminal_too_narrow_to_mark_a_value_withholds_the_whole_card(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0233 §8's second clause read on the terminal rather than on the value.

    Below the gutter's own width Rich wraps the *marked* line: the marker is split
    across display lines and the value's characters land on lines carrying none, so
    the framing this renderer exists to close is defeated by the renderer rather than
    by the value. There is no rendering at that width that both shows the text and
    marks it, so the card is withheld and the remedy named — a wider window.

    Asserted at the boundary and one column under it, because an off-by-one here is
    the whole of the defect. Adversarial review, round 3, ``blocker``.
    """
    body = "abcdef"
    confirmation = _egress_confirmation(
        _egress_span("body", extent=len(body)), parameters={"body": body}
    )

    for width in (1, len(_VALUE_GUTTER) - 1, len(_VALUE_GUTTER)):
        output.truncate(0)
        output.seek(0)
        monkeypatch.setattr(cli, "console", Console(file=output, force_terminal=False, width=width))

        assert cli._render_confirmation(confirmation) is False, width
        # Squashed rather than flowed: at one column every character is its own line,
        # so the words themselves are what survive and the layout is not the subject.
        rendered = "".join(output.getvalue().split())
        assert "Confirmationwithheld" in rendered, width
        assert "toonarrow" in rendered, width
        assert "Nothingwassentandnothingwasdeclined" in rendered, width
        assert body not in rendered, width  # no character of the value reached the screen


def test_the_narrowest_terminal_that_still_marks_a_value_renders_the_card(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other side of :func:`cli._values_fit_this_terminal`'s boundary.

    One column of value beside the gutter is enough to mark it, so the card is put
    rather than withheld — and every line of the value still carries the marker,
    which is what makes the boundary the right one rather than merely a threshold.
    """
    body = "abcdef"
    monkeypatch.setattr(
        cli, "console", Console(file=output, force_terminal=False, width=len(_VALUE_GUTTER) + 1)
    )

    assert (
        cli._render_confirmation(
            _egress_confirmation(_egress_span("body", extent=len(body)), parameters={"body": body})
        )
        is True
    )
    rendered = output.getvalue()

    assert "Confirmation withheld" not in rendered  # the card was put, not withheld
    # The gutter-carrying lines are the value block and nothing else on the card, so
    # they are the value: one column at a time, all of it, every line marked.
    assert "".join(_value_lines(rendered)) == body


def test_a_value_the_parameters_do_not_locate_withholds_the_whole_card(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0233 §8's second clause: no confirmation at all, and it says so.

    "A surface that cannot render a value whole renders **no** confirmation and says
    so" — because a partial content-bearing confirmation is worse than none, it looks
    like a whole one. The shape is unreachable from a constructed request and
    reachable over the wire, since ``ConfirmationEgress`` re-checks none of the
    binding's structural invariants. No part of the payload is rendered, and no
    control is offered.
    """
    monkeypatch.setattr(
        typer, "confirm", lambda *_a, **_k: pytest.fail("a withheld card offered a control")
    )
    confirmation = _egress_confirmation(
        _egress_span("body", extent=6), parameters={"elsewhere": "secret"}
    )

    assert cli._render_confirmation(confirmation) is False
    assert cli._prompt_for_approval(confirmation) is None

    rendered = output.getvalue()
    assert "Confirmation required" not in rendered
    assert "Confirmation withheld" in rendered
    assert "secret" not in rendered  # no part of the payload, whole or otherwise
    assert "Goes to" not in rendered  # and none of the floor, since there is no card


def test_all_three_coverage_states_render_and_none_is_the_same_sentence(
    output: StringIO,
) -> None:
    """ADR-0233 §8's fifth clause: rendered in **all three** states.

    Total over the enum rather than over the states a lane believes it will meet —
    ``PATH_WITHOUT_MODEL`` is unreachable in a confirmation, because §6 refuses it at
    binding construction, and is rendered anyway for ADR-0181 §6's fourth clause's
    reason: a fact shown only when it is alarming is one a user learns to read as an
    alarm, and its absence as clearance. The iteration is over the enum itself, so a
    fourth member could not be added without failing here.
    """
    sentences: set[str] = set()
    for coverage in SpanCoverage:
        output.truncate(0)
        output.seek(0)
        cli._render_confirmation(
            _egress_confirmation(_egress_span("body", extent=5), coverage=coverage)
        )
        line = _coverage_slice(output.getvalue())
        assert line.strip() != "What it draws on:"  # a state, never a blank
        sentences.add(line)

    assert len(sentences) == len(SpanCoverage) == 3


def test_no_coverage_state_is_an_assurance_a_warning_or_a_verdict(output: StringIO) -> None:
    """ADR-0233 §8's fifth, seventh and eighth clauses, as absences on every arm.

    ``NOT_COVERED`` never says the send is safe or that nothing relates to what the
    user has told this assistant; no arm is a detection, a score, a risk level, a
    recommendation or a claim that the call is malicious; and none names a record, a
    record identifier, an episode, a store-side key, a schema field or a kind of
    source.
    """
    for coverage in SpanCoverage:
        output.truncate(0)
        output.seek(0)
        cli._render_confirmation(
            _egress_confirmation(_egress_span("body", extent=5), coverage=coverage)
        )
        line = _coverage_slice(output.getvalue()).lower()

        for forbidden in (
            "safe",
            "secure",
            "harmless",
            "nothing to worry",
            "risk",
            "warning",
            "malicious",
            "suspicious",
            "untrusted",
            "unsafe",
            "detected",
            "score",
            "recommend",
            "you should",
            # §8: no record identifier, no episode, no store-side key, no field name
            # of any store's schema and no memory. The *verb* "recorded" is not one
            # of those and is what ADR-0181 §6's own line already says — the bar is
            # on naming a thing in a store, not on saying that something was
            # recorded.
            "memory",
            "episode",
            "belief",
            "conversation",
            "field",
            # ...and no kind of source, in the two forms ADR-0181 §6 names in terms.
            "source you connected",
            "connected source",
        ):
            assert forbidden not in line, (coverage, forbidden)


def test_the_coverage_line_is_never_a_claim_about_a_span(output: StringIO) -> None:
    """ADR-0233 §8's sixth clause: not attributed to an argument, a position or a destination.

    The recorded fact is a disjunction over the **call**, so a per-span rendering
    would assert a marker §4 deliberately does not mint. This is ADR-0181 §6's fifth
    clause read one axis over, and it is checked the same way: over a card whose
    floor names two arguments and a recipient, none of which may appear in the line.
    """
    for coverage in SpanCoverage:
        output.truncate(0)
        output.seek(0)
        cli._render_confirmation(
            _egress_confirmation(
                _egress_span("body", extent=5),
                _egress_span("to", canonical="alice@example.org", extent=17),
                coverage=coverage,
            )
        )
        line = _coverage_slice(output.getvalue())

        for span_word in ("body", "alice@example.org", "argument", "recipient", "span", "["):
            assert span_word not in line, (coverage, span_word)


def test_the_coverage_line_is_not_the_origin_line_in_either_direction(
    output: StringIO,
) -> None:
    """ADR-0233 §8's eighth clause: no surface conflates the two.

    "The two answer different questions — where what this call would send came from,
    and whether the material selected into the planning call carried the external
    mark." Both are on the card in every combination, each in its own words: the
    origin line's own vocabulary is absent from the coverage line and the coverage
    line's from the origin line, so neither could be read as a restatement of the
    other.
    """
    for coverage in SpanCoverage:
        for planned in (True, False):
            output.truncate(0)
            output.seek(0)
            cli._render_confirmation(
                _egress_confirmation(
                    _egress_span("body", extent=5),
                    coverage=coverage,
                    planned_with_external_content=planned,
                )
            )
            flowed = _flowed(output.getvalue())
            expected = _PLANNED_OVER_EXTERNAL if planned else _PLANNED_OVER_NOTHING_MARKED
            assert expected in flowed  # ADR-0181 §6's line, unmoved and unreduced
            line = _coverage_slice(flowed)

            for origin_word in ("external content", "selected", "marked as resting"):
                assert origin_word not in line, (coverage, planned, origin_word)
            origin = flowed[flowed.index("Planned over:") :].split("Goes to:")[0]
            for coverage_word in ("draws on", "composed by a model", "stores"):
                assert coverage_word not in origin, (coverage, planned, coverage_word)


def test_the_reveal_is_a_separate_step_from_the_approval(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0233 §8's ninth clause: "no control that both reveals a value and approves it".

    Rendering the card offers nothing to operate — a control raised here would fail —
    and the values are all on the screen before any control exists. So the two acts
    are separable in the only sense this surface can be asked for: reading costs
    nothing and answering is its own act.
    """
    monkeypatch.setattr(
        typer, "confirm", lambda *_a, **_k: pytest.fail("the reveal operated a control")
    )
    body = "the whole body, read before anything is offered"

    assert (
        cli._render_confirmation(
            _egress_confirmation(_egress_span("body", extent=len(body)), parameters={"body": body})
        )
        is True
    )
    assert _value_lines(output.getvalue()) == [body]


def test_the_prompt_takes_no_affirmative_default_and_needs_the_token_typed(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0233 §8's ninth clause: no affirmative default, no lower-effort yes.

    Driven through the real prompt with a scripted standard input, because "the
    default is ``False``" is a claim about what a bare Enter does and only the prompt
    itself can answer it. A blank line declines; the approving token has to be typed.
    """
    confirmation = _egress_confirmation(_egress_span("body", extent=5))

    monkeypatch.setattr("sys.stdin", StringIO("\n"))
    assert cli._prompt_for_approval(confirmation) is False  # a bare Enter is not approval

    monkeypatch.setattr("sys.stdin", StringIO("y\n"))
    assert cli._prompt_for_approval(confirmation) is True  # the token, typed


def test_one_prompt_answers_one_confirmation(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0233 §8's ninth clause: "no control that answers more than one confirmation".

    Two cards, two prompts, and each answered on its own — the second is put after the
    first was answered, so no control reaches past the confirmation it was offered
    for. A surface that had asked once and applied the answer twice would show one
    prompt here.
    """
    answers = iter([True, False])
    asked: list[str] = []

    def _one_at_a_time(_text: str, *, default: bool = False) -> bool:
        asked.append(output.getvalue())
        return next(answers)

    monkeypatch.setattr(typer, "confirm", _one_at_a_time)
    first = _egress_confirmation(_egress_span("body", extent=5))
    second = _egress_confirmation(_egress_span("to", canonical="bob@example.org", extent=15))

    assert cli._prompt_for_approval(first) is True
    assert cli._prompt_for_approval(second) is False
    assert len(asked) == 2
    # The second card was on the screen before its own prompt, and not before the first's.
    assert "bob@example.org" not in asked[0]
    assert "bob@example.org" in asked[1]


def test_yes_answers_a_confirmation_that_carries_no_egress(output: StringIO) -> None:
    """ADR-0233 §8's last clause: a confirmation whose ``egress`` is ``None`` owes none of it.

    ``--yes`` is unchanged there, which is the whole of ADR-0052 §4's and ADR-0073
    §5's idiom: the flag supplies the answer and never the rendering.
    """
    assert (
        cli._assume_yes(
            Confirmation(
                tool_id="notes",
                tool_description="Write a note.",
                parameters={"body": "hello"},
                reason="an unknown cost",
                token=ContinuationToken(handle="tok"),
                egress=None,
            )
        )
        is True
    )
    assert output.getvalue() == ""  # it answers, and says nothing about a floor it owes none of


def test_yes_does_not_answer_an_egress_confirmation_and_declines_nothing(
    output: StringIO,
) -> None:
    """ADR-0233 §8's ninth clause and §9's second condition, on the one control that spans cards.

    §8 bars a control that "answers more than one confirmation" or "pre-selects an
    affirmative answer", and a flag typed before the request existed does both — on
    ``resume`` one ``--yes`` answers every pending card. §9's second condition admits
    a model-composed span only where the ``CONFIRM`` was answered by the user "on
    **that** request", which a standing flag is not.

    ``None`` rather than ``False``: the user refused nothing, so nothing is recorded
    as a refusal, and the step stays parked to be answered on a screen.
    """
    answer = cli._assume_yes(
        _egress_confirmation(
            _egress_span("body", extent=5), coverage=SpanCoverage.MODEL_ON_EVERY_PATH
        )
    )

    assert answer is None
    rendered = _flowed(output.getvalue())
    assert "--yes does not answer this one" in rendered
    assert "Nothing was sent and nothing was declined" in rendered
    # What to do instead, named precisely enough to act on: `assistant resume` alone
    # is the command that just did this, so the flag to drop is named too.
    assert "Answer it with assistant resume, run without --yes." in rendered


async def test_an_unanswered_confirmation_stays_parked_and_exits_nonzero(
    output: StringIO,
) -> None:
    """The driver's half of the two clauses above: no ruling is recorded either way.

    An approver returning ``None`` — a withheld card, or ``--yes`` meeting an egress
    confirmation — leaves the recovered step exactly as it was: ``resume`` is not
    called, so nothing is sent and no ``DENY`` is recorded, and the exit is non-zero
    so a caller cannot read "everything was resolved" off the run.
    """
    engine = _engine(tools=(confirmable(),))
    await engine.converse("send it", timeout=PATIENT)
    engine._parked.clear()

    code = await cli._drive_resume(engine, timeout=PATIENT, approver=lambda _c: None)

    assert code == 1
    rendered = output.getvalue()
    assert "Confirmation required" in rendered  # it was still shown
    assert "Done" not in rendered  # and nothing ran
    assert "Declined" not in rendered  # and nothing was refused
    still_parked = await engine.pending_confirmations()
    assert len(still_parked) == 1  # the step is exactly where it was
    await engine.aclose()


def test_the_cli_mints_no_ruling_and_authorises_nothing(output: StringIO) -> None:
    """ADR-0042 §6, narrowed by ADR-0186 §1 rather than dropped.

    This case used to forbid the *name* ``PermissionDecision`` in this module
    outright, together with ``ActionRequest``, ``EgressBinding`` and ``ToolCall``.
    ADR-0186 §1 promotes two operations that **return**
    ``tuple[PermissionDecision, ...]`` and §9 obliges this module to render what they
    return, so the blanket form is now false: a ruling reaches this adapter the way a
    ``Confirmation`` does, handed over the engine surface, and §7's floor cannot be
    paid without naming the value it is stated over.

    What ADR-0042 §6 actually forbids survives intact, in the two forms it can take.
    **This adapter never mints a ruling**: it constructs no ``PermissionDecision``, no
    binding, and reaches no ``from_request`` — the fabrication ADR-0184 §4 closed the
    last route to. And **it never computes an authorisation**, which is ADR-0186 §8's
    second clause, "no surface computes, displays or implies
    ``PermissionDecision.authorises``".

    Call shapes are what is scanned for rather than bare words, because
    ``_render_decision``'s own docstring cites the bars it is written against, and a
    module forbidden to *name* the rule it obeys is a module whose reasoning has to
    live somewhere else.
    """
    source = getsource(cli)
    for forbidden in ("ActionRequest", "ToolCall", "from_request", "authorises("):
        assert forbidden not in source, f"interfaces/cli.py names {forbidden}"
    for minted in ("PermissionDecision(", "EgressBinding(", "OriginUnrecordedBinding("):
        assert minted not in source, f"interfaces/cli.py constructs {minted}"


def test_a_recorded_ruling_reaches_the_audit_surface_and_nothing_else() -> None:
    """ADR-0178 §5's third clause, pinned where a source scan can no longer pin it.

    §5 builds a ``ConfirmationEgress`` from the recorded decision *in `core`*, so the
    card's facts reach this adapter as a member of ``Confirmation`` and the
    confirmation path never holds a ruling. That used to be guaranteed by the module
    naming no decision at all; since ADR-0186 §9 it has to be guaranteed by **where**
    the decision goes instead.

    So the walk asserts the whole set rather than spot-checking: a decision, or either
    binding it may carry, is annotated on exactly the audit surface's seven functions
    and on no others. An eighth entry — most of all ``_render_confirmation`` or
    ``_prompt_for_approval`` — fails here, which is the route around ADR-0042 §6 that
    ADR-0178 exists to close and that ADR-0186 §8's last clause bars from the other
    direction.

    ``_authorisation_line`` and ``_refuse_a_page_this_surface_cannot_state`` are the
    sixth and seventh, added by ADR-0193 §11: the first renders what authorised an
    ``ALLOW`` from the row alone, the second runs that same dispatch over a page
    before a byte of it is printed, and both therefore take the decision and belong
    on this surface. The set is **extended** rather than relaxed to a superset test,
    because a membership check would stop catching the entry this case exists for.
    """
    holders = {
        name
        for name, member in vars(cli).items()
        if isfunction(member)
        and member.__module__ == cli.__name__
        and any(
            recorded in str(member.__annotations__)
            for recorded in ("PermissionDecision", "EgressBinding", "OriginUnrecordedBinding")
        )
    }
    assert holders == {
        "_authorisation_line",
        "_decisions_artifact",
        "_recorded_origin_line",
        "_render_decision",
        "_refuse_a_page_this_surface_cannot_state",
        "_render_decisions",
        "_render_recorded_egress",
    }


def test_disposition_render_names_the_executed_tool(output: StringIO) -> None:
    """An executed step names the tool that ran (§3)."""
    cli._render_disposition(Disposition.EXECUTED, "smtp")
    assert "smtp" in output.getvalue()


def test_invalid_parameters_renders_a_line_of_its_own(output: StringIO) -> None:
    """A step refused for its arguments says so rather than printing nothing (#1113).

    The defect was silence: ``_render_disposition`` reads its mapping with ``.get``,
    so ADR-0145 §4's new member ended a turn with the CLI saying nothing at all
    about why nothing ran.
    """
    cli._render_disposition(Disposition.INVALID_PARAMETERS, None)
    rendered = _flowed(output.getvalue())

    assert rendered  # something was printed at all — the whole of #1113
    assert "arguments" in rendered  # and it names what was at fault
    # No tool is named: the eligibility filter emptied the candidate set, so there
    # is no "selected tool" and ``tool_id`` is ``None`` (ADR-0144 §7).
    assert "the selected tool" not in rendered


def test_invalid_parameters_render_claims_only_what_both_causes_support(
    output: StringIO,
) -> None:
    """The line is true on the raise path too, not only on the mismatch (ADR-0145 §4, §7).

    One member, two causes: every capable candidate reported violations, or an
    evaluation *raised*. Only the first establishes that the arguments do not fit —
    on the second, §7 says in terms that "a raise establishes no such fact", and the
    arguments may have satisfied every schema. One phrase is printed for both, so it
    has to be the weaker claim; asserting a mismatch would be false half the time,
    which is ``_step_headline``'s ``INDETERMINATE`` hazard one disposition over.
    """
    cli._render_disposition(Disposition.INVALID_PARAMETERS, None)
    rendered = _flowed(output.getvalue())

    assert "not established as acceptable" in rendered
    # The claims the raise path cannot support. Spelled out rather than left to the
    # positive assertion above, because the tempting rewordings are exactly these.
    for overclaim in ("did not fit", "do not fit", "invalid", "rejected", "does not match"):
        assert overclaim not in rendered.lower()


def test_invalid_parameters_render_carries_no_argument_of_its_own(output: StringIO) -> None:
    """The line is a fixed phrase, never a report of the parameters (ADR-0145 §8).

    §8 forbids a rendering from carrying an argument value *or* key, and the
    violations that would name the missed constraint stop at ``orchestration``
    anyway — ``StepOutcome`` has no field for them (#1106). So the same text comes
    out whatever the step's arguments were, which is what this pins.
    """
    cli._render_disposition(Disposition.INVALID_PARAMETERS, None)
    without_tool = output.getvalue()
    output.truncate(0)
    output.seek(0)

    # Even handed a tool id, the line must not start reporting particulars: a
    # rendering that varies with the call is one that can be made to leak.
    cli._render_disposition(Disposition.INVALID_PARAMETERS, "smtp")
    with_tool = output.getvalue()

    assert with_tool == without_tool
    assert "smtp" not in with_tool


def test_every_disposition_but_the_parked_one_renders(output: StringIO) -> None:
    """Only ``AWAITING_CONFIRMATION`` prints nothing, and that one by design.

    The silent fallback is deliberate for the parked step — the confirm flow renders
    it from content the verdict does not carry — but #1113 showed that a fallback
    kept for one member silently absorbs the next one added. This holds the rest of
    the enum to printing something, so a future member fails here instead of in
    front of a user.
    """
    for disposition in Disposition:
        output.truncate(0)
        output.seek(0)
        cli._render_disposition(disposition, "smtp")
        expected_silent = disposition is Disposition.AWAITING_CONFIRMATION
        assert bool(output.getvalue().strip()) is not expected_silent, disposition


def test_error_render_shows_no_traceback(output: StringIO) -> None:
    """An error is a one-line message, not a stack trace."""
    cli._render_error(PlanningError("a turn needs a non-empty utterance"))
    rendered = output.getvalue()
    assert "non-empty utterance" in rendered
    assert "Traceback" not in rendered


# --- the turn flow (ADR-0042 §3, §7) ------------------------------------


async def test_ask_executes_an_allowed_step(output: StringIO) -> None:
    """An allowed step runs and the CLI reports success, exit 0."""
    engine = _engine(tools=(tool(),))
    approved = 0

    def approve(_confirmation: Confirmation) -> bool:
        nonlocal approved
        approved += 1
        return True

    code = await cli._drive_turn(
        engine, "send it", timeout=PATIENT, approver=approve, confirm_operation=_no_routed_card
    )
    assert code == 0
    assert approved == 0  # no confirmation was needed, so the approver was never called
    assert "Done" in output.getvalue()
    await engine.aclose()


async def test_ask_prompts_and_relays_the_token_on_a_confirmation(output: StringIO) -> None:
    """A parked step prompts, and the human's yes relays the opaque token (§4)."""
    engine = _engine(tools=(confirmable(),))
    seen: list[Confirmation] = []

    def approve(confirmation: Confirmation) -> bool:
        seen.append(confirmation)
        return True

    code = await cli._drive_turn(
        engine, "send it", timeout=PATIENT, approver=approve, confirm_operation=_no_routed_card
    )
    assert code == 0
    assert len(seen) == 1  # the adapter was asked to approve exactly one confirmation
    assert isinstance(seen[0].token, ContinuationToken)  # it relayed the opaque token
    assert seen[0].tool_id == "smtp"  # the engine assembled the content to judge
    assert "Done" in output.getvalue()  # after approval the step ran
    await engine.aclose()


async def test_ask_renders_a_refused_confirmation_as_declined(output: StringIO) -> None:
    """Answering no yields a DENY the CLI reports, exit 0 (a valid outcome)."""
    engine = _engine(tools=(confirmable(),))
    code = await cli._drive_turn(
        engine,
        "send it",
        timeout=PATIENT,
        approver=lambda _confirmation: False,
        confirm_operation=_no_routed_card,
    )
    assert code == 0
    assert "Declined" in output.getvalue()
    await engine.aclose()


async def test_ask_surfaces_an_error_with_a_nonzero_exit(output: StringIO) -> None:
    """A blank utterance is a PlanningError the CLI surfaces, exit 1 (§7)."""
    engine = _engine(tools=(tool(),))
    code = await cli._drive_turn(
        engine,
        "   ",
        timeout=PATIENT,
        approver=lambda _confirmation: True,
        confirm_operation=_no_routed_card,
    )
    assert code == 1
    assert "Error" in output.getvalue()
    await engine.aclose()


# --- resume: answering a durably-parked confirmation (ADR-0052) ---------


async def test_resume_reports_nothing_awaiting_when_no_park_exists(output: StringIO) -> None:
    """With no durably-parked confirmation, ``resume`` says so and exits 0."""
    engine = _engine(tools=(confirmable(),))
    code = await cli._drive_resume(engine, timeout=PATIENT, approver=lambda _c: True)
    assert code == 0
    assert "Nothing is awaiting confirmation" in output.getvalue()
    await engine.aclose()


async def test_resume_recovers_a_park_prompts_and_relays_the_token(output: StringIO) -> None:
    """A step parked by an earlier turn is recovered, shown, approved, and run (§1)."""
    engine = _engine(tools=(confirmable(),))
    # Park a confirmation, then drop the in-process token (as a restart would).
    parked = await engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.disposition is Disposition.AWAITING_CONFIRMATION
    engine._parked.clear()

    seen: list[Confirmation] = []

    def approve(confirmation: Confirmation) -> bool:
        seen.append(confirmation)
        return True

    code = await cli._drive_resume(engine, timeout=PATIENT, approver=approve)
    assert code == 0
    assert len(seen) == 1  # the recovered confirmation was presented for judgement
    assert isinstance(seen[0].token, ContinuationToken)  # relayed opaquely
    assert seen[0].tool_id == "smtp"
    rendered = output.getvalue()
    assert "Confirmation required" in rendered  # the action was shown before approval
    assert "smtp" in rendered
    assert "Done" in rendered  # after approval the recovered step ran
    await engine.aclose()


async def test_resume_renders_the_action_even_when_auto_approved(output: StringIO) -> None:
    """A non-interactive (--yes) approver still sees the action rendered first (§4).

    The action and reason are shown by ``_drive_resume`` itself, before the
    approver, so ``--yes`` never runs a recovered action the user never saw.
    """
    engine = _engine(tools=(confirmable(),))
    await engine.converse("send it", timeout=PATIENT)
    engine._parked.clear()

    # An approver that renders nothing itself and blindly approves (as --yes does).
    code = await cli._drive_resume(engine, timeout=PATIENT, approver=lambda _c: True)
    assert code == 0
    rendered = output.getvalue()
    assert "Confirmation required" in rendered  # shown despite no prompt
    assert "smtp" in rendered
    assert "Done" in rendered
    await engine.aclose()


async def test_resume_renders_a_recovered_refusal_as_declined(output: StringIO) -> None:
    """Answering no to a recovered confirmation yields a DENY the CLI reports."""
    engine = _engine(tools=(confirmable(),))
    await engine.converse("send it", timeout=PATIENT)
    engine._parked.clear()

    code = await cli._drive_resume(engine, timeout=PATIENT, approver=lambda _c: False)
    assert code == 0
    assert "Declined" in output.getvalue()
    await engine.aclose()


# --- startup and input error boundaries (ADR-0042 §7) -------------------


async def test_ask_renders_a_config_failure_and_exits_nonzero(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A settings failure at startup is rendered, not dumped as a traceback (§7)."""

    def _bad_settings() -> object:
        msg = "invalid configuration: unknown timezone"
        raise ConfigurationError(msg)

    monkeypatch.setattr(cli, "load_settings", _bad_settings)
    code = await cli._ask("hello", timeout_seconds=1.0, assume_yes=True)
    assert code == 1
    assert "Error" in output.getvalue()
    assert "unknown timezone" in output.getvalue()


async def test_ask_reports_a_closed_door_as_an_instruction_and_exits_nonzero(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No hub, no fallback: an instruction and a non-zero exit (ADR-0084 §9).

    The whole of ruling 3 and ruling 5 at the adapter, and the assertions are
    written so that a fallback could not pass them: the message must name the
    socket it tried *and* how to start the hub, and the exit code must be non-zero.
    An in-process fallback would render a turn and exit ``0``.

    It is driven through the real client against a directory with no socket in it,
    rather than through a stubbed one, so what is exercised is the actual
    ``connect`` failure rather than a test double's idea of it.
    """
    monkeypatch.setattr(cli, "load_settings", lambda: Settings(data_dir=tmp_path))
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    code = await cli._ask("hello", timeout_seconds=1.0, assume_yes=True)
    assert code == 1
    rendered = output.getvalue()
    assert "hub.sock" in rendered
    assert "ai-assistant-hub" in rendered
    assert "not reachable" in rendered


async def test_a_data_directory_too_long_for_the_socket_is_reported_as_itself(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The client gives the hub's own diagnosis rather than a bare errno (#554).

    One setting locates both the data and the door (ADR-0084 §9), so both halves
    reach the same verdict about it. Without this the user reads
    ``AF_UNIX path too long`` out of ``connect`` and has to work out for themselves
    that ``ASSISTANT_DATA_DIR`` is what to move; with it they read the limit, the
    encoded length, and what to do.
    """
    deep = tmp_path
    while len(str(deep).encode()) < sun_path_limit():
        deep = deep / "aaaaaaaaaa"
    monkeypatch.setattr(cli, "load_settings", lambda: Settings(data_dir=deep))
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    code = await cli._ask("hello", timeout_seconds=1.0, assume_yes=True)
    assert code == 1
    rendered = output.getvalue()
    assert "sun_path" in rendered
    assert "ASSISTANT_DATA_DIR" in rendered


@pytest.mark.parametrize("bad", ["inf", "nan", "0", "-1", "1e100", "1e-7"])
def test_ask_rejects_an_unusable_timeout(bad: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-finite, non-positive, overflowing, or sub-resolution --timeout is a usage error.

    **And no client is opened**, which is the half the exit code alone does not say
    (#1970). ``ask`` is the command with the most to build behind it — a hub client
    and a turn — so a refusal that ran after the connection would be paid for on
    every mistyped ``--timeout``, and would still exit 2.
    """
    opened = _wire_recording_opens(monkeypatch, FakeAssistantEngine())

    result = CliRunner().invoke(cli.app, ["ask", "hello", "--timeout", bad])

    assert result.exit_code == 2  # Typer's usage-error code, before the engine is built
    assert opened == []


# --- a failed credential read is not a refused credential (#1940) ------------


class _FailingStdin:
    """A standard input whose descriptor fails at the read (#1940).

    The failure ``_credential_from_stdin``'s bounded ``readline`` is exposed to and
    that no refusal describes: a stream that errors mid-read, a pipe whose peer died
    in a way the platform reports as ``EIO``, a closed stream. It answers with a
    real ``OSError`` rather than a stand-in exception, because the whole question
    the three cases below settle is which ``except`` arm that class lands in.

    ``isatty`` is answered rather than inherited so the same stub serves the hidden
    prompt, whose guard is a question about the terminal and not about the read.
    """

    def __init__(self, *, tty: bool = False) -> None:
        """Create the stub, optionally claiming to be a terminal."""
        self._tty = tty
        self.buffer = self

    def isatty(self) -> bool:
        """Whether ``_prompt_for_credential`` sees a terminal here."""
        return self._tty

    def readline(self, limit: int | None = None) -> bytes:
        """Fail the way a descriptor does, having read nothing."""
        raise OSError(errno.EIO, "Input/output error")


def test_a_credential_read_that_fails_is_not_translated_into_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reader lets an ``OSError`` through as itself, and that is the design.

    Translating it into the ``ValueError`` the three surfaces already catch would
    make this one change instead of three — and would route ``connect`` and
    ``reconnect`` through ``_render_unusable_credential``, whose sentence asserts
    that a credential cannot be used. Nothing was read, so there is no credential to
    say that about, and the renderer's own safety argument is ADR-0125 §6's
    guarantee about the refusal *of a value*, which has nothing to reach here.

    So the class the boundaries branch on is the class the platform raised, and this
    pins the reader against a well-meant later translation.
    """
    monkeypatch.setattr(sys, "stdin", _FailingStdin())

    with pytest.raises(OSError, match="Input/output error"):
        cli._credential_from_stdin()


async def test_connect_renders_a_failed_credential_read_rather_than_a_traceback(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``connect``'s read failure is a rendered line and a non-zero exit (#1940).

    ADR-0042 §7 makes surfacing errors and setting a meaningful exit code the
    adapter's own responsibility, and before this the ``OSError`` walked out of
    ``_drive_connect`` past a boundary that caught only ``ValueError``.

    The two negative assertions are the finding's actual content. Nothing may be
    sent, because the credential never arrived; and the rendering may not be
    ``_render_unusable_credential``'s, because "that credential cannot be used"
    would attribute a descriptor fault to a value nobody read.
    """
    engine = FakeAssistantEngine()
    _wire_recording_opens(monkeypatch, engine)
    monkeypatch.setattr(sys, "stdin", _FailingStdin())

    code = await cli._connect_account("me@example.com", credential_stdin=True)

    assert code == 1
    rendered = _flat(output.getvalue())
    assert "Error:" in rendered
    assert "Input/output error" in rendered
    assert "cannot be used" not in rendered
    assert engine.calls == []


async def test_reconnect_renders_a_failed_credential_read_rather_than_a_traceback(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``reconnect``'s read failure lands the same way, on the same reasoning.

    It is the third surface of #1940's finding and it is asserted separately rather
    than parametrised with ``connect``, because the two boundaries are separate
    code: ADR-0151 §1 refused to fold the operations into one method, and the
    duplication of the arm is the thing a test has to see.
    """
    engine = FakeAssistantEngine()
    _wire_recording_opens(monkeypatch, engine)
    monkeypatch.setattr(sys, "stdin", _FailingStdin())

    code = await cli._reprovision_account(
        "conn-1", identity="me@example.com", credential_stdin=True
    )

    assert code == 1
    rendered = _flat(output.getvalue())
    assert "Error:" in rendered
    assert "Input/output error" in rendered
    assert "cannot be used" not in rendered
    assert engine.calls == []


async def test_device_enrol_renders_a_failed_credential_read_rather_than_a_traceback(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The enrolment boundary catches it too, and it already had the vocabulary.

    ``device enrol`` renders every failure it catches through ``_render_error``, so
    the one message the three surfaces settle on is the one this command was already
    giving for a refused value — no fourth sentence was invented for the case.

    Nothing is wired: the read is the first statement inside the boundary, so a
    failing one is answered before any setting is loaded or any keyring is opened,
    and asserting that requires providing neither.
    """
    monkeypatch.setattr(sys, "stdin", _FailingStdin())

    code = await cli._store_device_enrolment("hub-abcdefgh", cli._credential_from_stdin)

    assert code == 1
    rendered = _flat(output.getvalue())
    assert "Error:" in rendered
    assert "Input/output error" in rendered
    assert "Enrolled" not in rendered


async def test_a_terminal_that_fails_at_the_hidden_prompt_takes_the_same_arm(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other reader's ``OSError`` is the same event and takes the same arm.

    ``_prompt_for_credential`` reaches ``getpass``, which opens the controlling
    terminal and reads from it; neither is guaranteed to succeed, and a container or
    a revoked ``/dev/tty`` produces an ``OSError`` from a reader that never touches
    ``sys.stdin.buffer``. The arm is on the exception's class rather than on which
    reader was chosen, which is what makes one test of that claim enough.

    The terminal is stubbed at ``typer.prompt`` — the read itself — rather than at
    ``_prompt_for_credential``, so the reader's own non-terminal guard still runs and
    the case remains the one where a terminal exists and fails.
    """
    engine = FakeAssistantEngine()
    _wire_recording_opens(monkeypatch, engine)
    monkeypatch.setattr(sys, "stdin", _FailingStdin(tty=True))

    def _no_terminal(*_args: object, **_kwargs: object) -> str:
        raise OSError(errno.ENXIO, "No such device or address")

    monkeypatch.setattr(typer, "prompt", _no_terminal)

    code = await cli._connect_account("me@example.com", credential_stdin=False)

    assert code == 1
    rendered = _flat(output.getvalue())
    assert "Error:" in rendered
    assert "No such device or address" in rendered
    assert "cannot be used" not in rendered
    assert engine.calls == []


# --- learn: the correction leg (ADR-0042 §3, §6) ------------------------


class _RecordingEngine:
    """A stand-in engine that records the feedback it is handed (ADR-0042 §6).

    The adapter cannot tell it from the façade for the one call ``learn`` makes; it
    lets a test assert the exact :class:`~ai_assistant.core.types.FeedbackEvent` the
    command built without folding anything into a real memory store.
    """

    def __init__(self, outcome: LearnOutcome) -> None:
        self._outcome = outcome
        self.events: list[FeedbackEvent] = []

    async def learn(self, event: FeedbackEvent) -> LearnOutcome:
        self.events.append(event)
        return self._outcome

    async def start(self) -> None:
        """The start-up sweeps, which this stand-in has no stores to sweep."""

    async def aclose(self) -> None:
        """Nothing to release: this stand-in owns no resource."""


class _FailingLearnEngine:
    """An engine whose ``learn`` fails, as a broken write path would."""

    async def learn(self, event: FeedbackEvent) -> LearnOutcome:
        msg = "the memory store would not write"
        raise MemoryStoreError(msg)

    async def start(self) -> None:
        """The start-up sweeps, which this stand-in has no stores to sweep."""

    async def aclose(self) -> None:
        """Nothing to release."""


def _stored_outcome() -> LearnOutcome:
    """One stored proposal, the ordinary success shape."""
    return LearnOutcome(
        results=(IngestSummary(decision=LearnDecision.STORED, record_id="rec-1", reason="new"),)
    )


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object) -> None:
    """Point the ``learn`` command's startup at ``engine``.

    The seam is :func:`~ai_assistant.interfaces.cli._open_engine` rather than
    ``build_engine``, because after ADR-0084 §6 the CLI has no composition root to
    reach: it obtains a *client*, and the one function that obtains it is the one
    place a test substitutes.
    """

    async def _open() -> object:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)
    monkeypatch.setattr(cli, "_utcnow", lambda: AT)


def _wire_recording_opens(monkeypatch: pytest.MonkeyPatch, engine: object) -> list[None]:
    """Wire ``engine`` as :func:`_wire` does, and record every open of a client.

    The seam every parse-boundary refusal in this module is actually about.
    ``_wire``'s stub answers with the engine and keeps no record, so a test using
    it can assert the *exit code* of a refusal but not the claim its own name or
    docstring makes — that the refusal landed **before any client was built**
    (ADR-0085 §3c's "before any I/O", #728). A regression that opened the hub,
    probed it, and only then converted a malformed argument into an exit-2 usage
    error would keep every assertion those cases held.

    The observation itself is :func:`cli_open_recorder.wire_recording_opens`, which
    three sibling modules make the same claim through (#1973); this binds it to
    *this* module's wiring. The cases making the claim here are spread the length of
    the module — ``--timeout``, ``learn`` content, ``--kind``, an ``--about-person``,
    ``--limit``, ``--offset`` and ``--band``, a grant's ``source``, a repeated
    ``--scope``, a quiet window, and the id arguments themselves.

    Args:
        monkeypatch: The patcher whose lifetime the substitution follows.
        engine: The engine a client, if one were opened, would be.

    Returns:
        One entry per :func:`~ai_assistant.interfaces.cli._open_engine` awaited.
    """
    return wire_recording_opens(_wire, monkeypatch, engine)


def test_the_open_recorder_sees_the_client_an_accepted_invocation_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The recorder is non-vacuous, which is what makes every ``opened == []`` evidence.

    An absence only says something if the observer would have seen the thing. A
    helper that patched the wrong name, or whose stub a later ``_wire`` overwrote,
    would make every refusal case below pass for a reason unrelated to when the
    refusal happened — and go on passing through exactly the regression #728 is
    about. So one *accepted* invocation is pinned here: it opens a client, and the
    list has to show it.
    """
    opened = _wire_recording_opens(monkeypatch, _RecordingEngine(_stored_outcome()))

    result = CliRunner().invoke(cli.app, ["learn", "--kind", "correction", "hello"])

    assert result.exit_code == 0
    assert opened == [None]


def test_learn_leaves_a_corrections_memory_kind_for_the_engine_to_resolve(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0122 §2: this adapter no longer predicts a correction's record type.

    It used to answer from a fixed table, and the answer was indistinguishable
    downstream from one the user had chosen deliberately — which is #864: every
    correction filed as a semantic fact, and the kind-scoped conflict probe then
    looking only in the drawer the table named. A correction points at a belief that
    already exists, whose record type is a property of *that* belief; naming it here
    is a prediction made at the one layer with no access to the target. Leaving it
    absent is the adapter reporting what it knows, and it is what keeps golden rule 3
    intact — the resolution is business logic and none of it happens in
    ``interfaces/``.
    """
    engine = _RecordingEngine(_stored_outcome())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, ["learn", "--kind", "correction", "the office is in Boston"]
    )
    assert result.exit_code == 0
    assert len(engine.events) == 1
    event = engine.events[0]
    assert event.kind is FeedbackKind.CORRECTION
    assert event.memory_kind is None  # not predicted here (ADR-0122 §2)
    assert event.content == "the office is in Boston"
    assert event.subject is None
    assert event.created_at == AT  # stamped from the injected clock, not hand-rolled
    assert "Learned" in output.getvalue()


def test_the_default_table_no_longer_answers_for_a_correction() -> None:
    """§2 removes the ``CORRECTION`` entry; the table is deliberately not exhaustive.

    Asserted on the table itself as well as through the command, because the comment
    that used to call it "exhaustive over ``FeedbackKind``" is exactly the invitation
    to restore the entry — and restoring it would reinstate #864 while every outcome
    test above still passed on a store that happened to hold a semantic neighbour.
    """
    assert cli._DEFAULT_MEMORY_KIND == {FeedbackKind.PREFERENCE: MemoryKind.PREFERENCE}


def test_learn_builds_a_preference_event_with_a_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--kind preference with --about becomes a PREFERENCE event scoped by subject."""
    engine = _RecordingEngine(_stored_outcome())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, ["learn", "--kind", "preference", "I prefer metric units", "--about", "units"]
    )
    assert result.exit_code == 0
    event = engine.events[0]
    assert event.kind is FeedbackKind.PREFERENCE
    assert event.memory_kind is MemoryKind.PREFERENCE  # defaulted from --kind
    assert event.subject == "units"


def test_learn_states_a_subject_with_about_person(monkeypatch: pytest.MonkeyPatch) -> None:
    """--about-person is the only route a non-owner subject has (ADR-0100 §4, §7).

    Without it, ``assistant learn "Marta prefers window seats"`` constructs
    ``about_person=None``, which §3 reads as *the owner's* — so the field's
    arrival would make a false record of exactly the case it was added for. That
    is why §7 makes the route a precondition of the field rather than a follow-up.
    """
    engine = _RecordingEngine(_stored_outcome())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app,
        ["learn", "--kind", "preference", "Marta prefers window seats", "--about-person", "Marta"],
    )
    assert result.exit_code == 0
    event = engine.events[0]
    assert event.about_person == "Marta"
    assert event.subject is None  # the scope axis, untouched by the person flag


def test_learn_keeps_the_two_about_flags_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    """--about is a scope and --about-person is whom it is about (ADR-0100 §7).

    Given together they land in their own fields. The person flag is spelled long
    precisely because ``--about`` and ``-a`` were already the scope axis's on this
    command, and a second short flag beside ``-a`` is the confusion the ADR spent
    a section avoiding.
    """
    engine = _RecordingEngine(_stored_outcome())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app,
        [
            "learn",
            "--kind",
            "preference",
            "prefers window seats",
            "--about",
            "travel",
            "--about-person",
            "Marta",
        ],
    )
    assert result.exit_code == 0
    event = engine.events[0]
    assert event.subject == "travel"
    assert event.about_person == "Marta"


def test_learn_defaults_to_stating_no_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence is "no subject stated", which is read as the owner's (ADR-0100 §3)."""
    engine = _RecordingEngine(_stored_outcome())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["learn", "--kind", "correction", "the office moved"])

    assert result.exit_code == 0
    assert engine.events[0].about_person is None


def test_learn_passes_a_subject_through_byte_for_byte(monkeypatch: pytest.MonkeyPatch) -> None:
    """The adapter does not tidy a label (ADR-0100 §6).

    Stripping here would store ``"  marta  "`` as ``"marta"``, and §6 keeps a
    label exactly as given precisely so that every later matching rule stays
    available — none can be recovered from labels normalised on the way in.
    """
    engine = _RecordingEngine(_stored_outcome())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, ["learn", "--kind", "correction", "x", "--about-person", "  marta  "]
    )

    assert result.exit_code == 0
    assert engine.events[0].about_person == "  marta  "


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_learn_rejects_a_blank_about_person(blank: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank subject is a usage error, not an uncaught ValidationError (§7).

    ``FeedbackEvent.about_person`` is ``NonBlankEncodableText``, whose refusal is
    a ``ValidationError`` — not an ``AssistantError`` — raised while the event is
    built, which is *before* :func:`_learn_feedback`'s error boundary opens. The
    parse-time callback turns it into a clean exit 2, the shape ``_present_source``
    already uses one command over.

    **And no client is opened** (#1973). "Parse-time" is the whole of the claim
    above — the callback runs while Typer is still binding parameters, before
    ``learn`` has reached its own body — and neither the exit code nor the absent
    exception says so on its own. A client is wired here for the first time so that
    the refusal has one to fail to open.
    """
    opened = _wire_recording_opens(monkeypatch, _RecordingEngine(_stored_outcome()))

    result = CliRunner().invoke(
        cli.app, ["learn", "--kind", "correction", "x", "--about-person", blank]
    )

    assert result.exit_code == 2  # Typer's usage-error code
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert opened == []


def test_learn_rejects_an_unencodable_about_person(monkeypatch: pytest.MonkeyPatch) -> None:
    r"""A lone surrogate reaches argv and no UTF-8 encoder will take it.

    Linux passes argv as bytes and Python decodes it with ``surrogateescape``, so
    ``assistant learn x --about-person $'\xe9'`` arrives as half a character.
    ``EncodableText`` refuses it, and without the parse-time check that refusal
    would land as the same uncaught ``ValidationError`` a blank one would.

    Refused at the same boundary as a blank one, and observed the same way: the
    value never reaches a client, because no client is opened (#1973).
    """
    opened = _wire_recording_opens(monkeypatch, _RecordingEngine(_stored_outcome()))

    result = CliRunner().invoke(
        cli.app, ["learn", "--kind", "correction", "x", "--about-person", "\udce9"]
    )

    assert result.exit_code == 2
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert opened == []


def test_learn_guarded_flag_reaches_the_engine_on_the_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--guarded arrives at the engine as ``FeedbackEvent.guarded`` (ADR-0217 §10).

    The CLI-seam arm §10 owes this lane by name. Every other arm ADR-0217 takes of
    the write-time act starts from a **preconstructed** event, so an adapter that
    accepted the flag and then omitted the member when building the event would
    pass all of them while writing the default placement over an explicit owner
    act — a control silently doing nothing, which is the one failure the route
    exists to prevent. Only an assertion taken from the far side of the adapter
    catches it, which is why this one reads the event the engine was handed.
    """
    engine = _RecordingEngine(_stored_outcome())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, ["learn", "--kind", "correction", "the office moved", "--guarded"]
    )

    assert result.exit_code == 0
    assert engine.events[0].guarded is True


def test_learn_without_the_guarded_flag_states_no_act(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence is ``False``, which ADR-0217 §7 says is not an act of any kind.

    The other half of §10's CLI-seam arm: "the same command without it as one
    carrying the default". The value is the field's default and the adapter sets it
    explicitly, which are the same value — what the arm pins is that leaving the
    flag off does not somehow arrive as an act, so the record keeps ADR-0217 §6's
    default placement and nothing here records that the owner considered guarding
    this belief and declined.
    """
    engine = _RecordingEngine(_stored_outcome())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["learn", "--kind", "correction", "the office moved"])

    assert result.exit_code == 0
    assert engine.events[0].guarded is False


def test_learn_offers_no_flag_that_widens(monkeypatch: pytest.MonkeyPatch) -> None:
    """There is no ``--no-guarded``, because at write there is no widening act.

    ADR-0217 §7: the member "is a narrowing only, and ``False`` is not an act of
    any kind". A ``--no-guarded`` spelled as the flag's negative half would offer
    the owner an act this decision does not give them at write — and would make the
    absent flag look like the *other* half of a choice rather than the absence of
    one. Widening a record the owner has already guarded is §7's ``unguard``, an
    act on a stored record in a lane of its own; it is not reachable from here, so
    the option is a usage error and no event is built.
    """
    engine = _RecordingEngine(_stored_outcome())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, ["learn", "--kind", "correction", "the office moved", "--no-guarded"]
    )

    assert result.exit_code == 2  # Typer's usage-error code
    assert engine.events == []


def test_learn_guarded_leaves_every_other_axis_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """The placement flag composes with the two kinds and the two subjects.

    ``--guarded`` is a fifth axis of one event, not a mode that reinterprets the
    others: given alongside them, each field still carries what its own flag said.
    """
    engine = _RecordingEngine(_stored_outcome())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app,
        [
            "learn",
            "--kind",
            "preference",
            "prefers window seats",
            "--about",
            "travel",
            "--about-person",
            "Marta",
            "--memory-kind",
            "semantic",
            "--guarded",
        ],
    )

    assert result.exit_code == 0
    event = engine.events[0]
    assert event.guarded is True
    assert event.kind is FeedbackKind.PREFERENCE
    assert event.memory_kind is MemoryKind.SEMANTIC
    assert event.subject == "travel"
    assert event.about_person == "Marta"


def test_learn_memory_kind_flag_overrides_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit --memory-kind overrides the default derived from --kind."""
    engine = _RecordingEngine(_stored_outcome())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app,
        ["learn", "--kind", "preference", "call me Al", "--memory-kind", "semantic"],
    )
    assert result.exit_code == 0
    event = engine.events[0]
    assert event.kind is FeedbackKind.PREFERENCE
    assert event.memory_kind is MemoryKind.SEMANTIC  # overridden, not the preference default


def test_learn_memory_kind_flag_pins_a_correction_that_would_otherwise_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§6: the flag keeps its role and acquires a sharper one.

    It was a way to pre-empt a fixed table; it becomes the way to say "I know which
    drawer, do not look" — a stronger guarantee, since it now suppresses a store read
    as well as a default, and the escape hatch §4's best-ranked rule leaves the user.
    The adapter's whole part in that is putting the value on the event; the
    suppression itself is the engine's (``tests/orchestration/test_loop.py``).
    """
    engine = _RecordingEngine(_stored_outcome())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app,
        ["learn", "--kind", "correction", "the office is in Boston", "--memory-kind", "semantic"],
    )
    assert result.exit_code == 0
    event = engine.events[0]
    assert event.kind is FeedbackKind.CORRECTION
    assert event.memory_kind is MemoryKind.SEMANTIC


def test_learn_rejects_an_unknown_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognised --kind is a usage error, before any engine is built.

    The recorded opens are what hold the second half of that sentence (#1970): exit
    2 is equally what a command that connected first and refused afterwards returns.
    """
    opened = _wire_recording_opens(monkeypatch, _RecordingEngine(_stored_outcome()))

    result = CliRunner().invoke(cli.app, ["learn", "--kind", "bogus", "hello"])

    assert result.exit_code == 2  # Typer's usage-error code
    assert opened == []


def test_learn_requires_a_kind() -> None:
    """--kind is required; omitting it is a usage error."""
    result = CliRunner().invoke(cli.app, ["learn", "hello"])
    assert result.exit_code == 2


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_learn_rejects_blank_content(blank: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Whitespace-only content is a usage error, not an uncaught ValidationError (§7).

    ``FeedbackEvent.content`` rejects blank text, and that ``ValidationError`` is not
    an ``AssistantError``; the parse-time callback turns it into a clean usage error
    (exit 2) before any event is constructed, rather than a dumped traceback.

    **No client is opened either** (#1970). ``_learn_feedback`` builds the event
    before it opens one, so today the two claims coincide — which is exactly why the
    second needs an assertion of its own: swap those two statements and every
    assertion this case already held still passes, while a mistyped ``learn`` starts
    costing a hub connection to be told what was typed.
    """
    opened = _wire_recording_opens(monkeypatch, _RecordingEngine(_stored_outcome()))

    result = CliRunner().invoke(cli.app, ["learn", "--kind", "correction", blank])

    assert result.exit_code == 2  # Typer's usage-error code
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert opened == []


def test_learn_surfaces_a_write_failure_with_a_nonzero_exit(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A MemoryStoreError from the write path is rendered, not dumped, exit 1 (§7)."""
    _wire(monkeypatch, _FailingLearnEngine())
    result = CliRunner().invoke(cli.app, ["learn", "--kind", "correction", "x"])
    assert result.exit_code == 1
    rendered = output.getvalue()
    assert "Error" in rendered
    assert "would not write" in rendered


def test_render_learn_lists_each_ruling_with_its_reason(output: StringIO) -> None:
    """Each proposal renders a one-line confirmation naming the ruling and its reason."""
    outcome = LearnOutcome(
        results=(
            IngestSummary(
                decision=LearnDecision.REINFORCED,
                record_id="r1",
                reason="matches an existing memory",
            ),
            IngestSummary(
                decision=LearnDecision.SUPERSEDED, record_id="r2", reason="overturns a prior belief"
            ),
        )
    )
    cli._render_learn(outcome)
    rendered = output.getvalue()
    assert "Reinforced" in rendered
    assert "matches an existing memory" in rendered
    assert "Replaced" in rendered
    assert "overturns a prior belief" in rendered
    assert "2 update(s)" in rendered


def test_render_learn_reports_when_nothing_was_proposed(output: StringIO) -> None:
    """Feedback that folds into no update is reported, not shown as a silent success."""
    cli._render_learn(LearnOutcome(results=()))
    assert "nothing" in output.getvalue().lower()


def test_render_learn_points_a_queued_deferral_at_the_question_it_parked(
    output: StringIO,
) -> None:
    """**Inverted by ADR-0078** (§8 reach 1, §10 item 9), and this is the inversion.

    It used to assert the line "cannot be done from here yet", which was honest: no
    memory-confirmation flow existed, so implying a follow-up would have promised
    something that did not. ADR-0078 builds the flow, which makes that line false for
    the arms it closes — and "leaving an honest message that has become a lie is the
    specific failure ADR-0019 is about".

    So the line now names the question and the verb that answers it. This is the reach
    that closes issue #423's own scenario: the user submits feedback, is told it is
    deferred, and is pointed at the answer.
    """
    outcome = LearnOutcome(
        results=(
            IngestSummary(
                decision=LearnDecision.DEFERRED,
                record_id=None,
                reason="conflicts with a prior assertion",
                queued=QueuedQuestion(
                    outcome=QueueOutcome.QUEUED,
                    question_id="q-7",
                    question_state=QuestionState.OPEN,
                ),
            ),
        )
    )
    cli._render_learn(outcome)
    rendered = " ".join(output.getvalue().split())
    assert "Not stored yet" in rendered
    assert "q-7" in rendered, "the user is pointed at the question, not left guessing"
    assert "assistant questions" in rendered
    assert "cannot be done from here" not in rendered, "that claim is now false"
    assert "0 stored" in rendered  # the header count still excludes it
    assert "conflicts with a prior" in rendered  # the reason is surfaced


def test_render_learn_keeps_the_non_answerable_line_for_a_secret_tier_deferral(
    output: StringIO,
) -> None:
    """And **only** for the arms ADR-0078 closes (§1, §10 item 9).

    A secret-tier deferral is still not answerable: ADR-0004 §3 forbids Tier 0 content
    a durable file, so nothing was queued and there is nothing to answer. It keeps the
    existing line and the existing reason, because "one message covering both outcomes
    would be the same dishonesty arriving from the other side — a user told to go
    answer a question that was never queued".
    """
    outcome = LearnOutcome(
        results=(
            IngestSummary(
                decision=LearnDecision.DEFERRED,
                record_id=None,
                reason="secret-tier data requires explicit user confirmation",
                queued=QueuedQuestion(outcome=QueueOutcome.NOT_QUEUABLE),
            ),
        )
    )
    cli._render_learn(outcome)
    rendered = " ".join(output.getvalue().split())
    assert "cannot be done from here" in rendered
    assert "assistant questions" not in rendered, "there is no question to answer"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (QuestionState.OPEN, "already waiting for your answer"),
        (QuestionState.DECLINED, "already declined"),
        (QuestionState.INTERRUPTED, "was already begun"),
    ],
    ids=["waiting", "declined", "interrupted"],
)
def test_render_learn_says_which_question_stands_in_the_way_and_in_what_state(
    output: StringIO, state: QuestionState, expected: str
) -> None:
    """§7's suppression guidance, per state — and the state is what decides the line.

    "The admission's ``deferral`` says **which and in what state**: for a ``REJECTED``
    row, 'you declined this on <date>; forget that question to be asked again'; for an
    ``APPLYING`` one, §9's first recovery step." Rendering an interrupted answer as an
    answerable follow-up would advertise a question the user cannot act on.
    """
    outcome = LearnOutcome(
        results=(
            IngestSummary(
                decision=LearnDecision.DEFERRED,
                record_id=None,
                reason="conflicts with a prior assertion",
                queued=QueuedQuestion(
                    outcome=QueueOutcome.ALREADY_ASKED,
                    question_id="q-3",
                    question_state=state,
                ),
            ),
        )
    )
    cli._render_learn(outcome)
    rendered = " ".join(output.getvalue().split())
    assert expected in rendered
    assert "q-3" in rendered


def test_render_learn_reports_a_full_queue_rather_than_saying_nothing(
    output: StringIO,
) -> None:
    """§7's refused branch — the one an implementation leaves silent (§10 item 3).

    Nothing raises, so a surface that said nothing here would swallow the correction
    the user just typed. The line names the **queue** rather than a question, because
    there is no question to read: reaching for one is the dereference the admission's
    three-shape validator exists to prevent.
    """
    outcome = LearnOutcome(
        results=(
            IngestSummary(
                decision=LearnDecision.DEFERRED,
                record_id=None,
                reason="conflicts with a prior assertion",
                queued=QueuedQuestion(outcome=QueueOutcome.QUEUE_FULL),
            ),
        )
    )
    cli._render_learn(outcome)
    rendered = " ".join(output.getvalue().split())
    assert "queue is full" in rendered
    assert "assistant questions" in rendered, "and says what to do about it"


def test_render_learn_neutralises_a_reason_for_the_terminal(output: StringIO) -> None:
    """A reason carrying control bytes or markup is neutralised on render (§4)."""
    outcome = LearnOutcome(
        results=(
            IngestSummary(
                decision=LearnDecision.STORED,
                record_id="r1",
                reason="wipe\x1b[2J and [red]shout[/red]",
            ),
        )
    )
    cli._render_learn(outcome)
    rendered = output.getvalue()
    assert "\x1b" not in rendered  # the control sequence was neutralised
    assert "[red]" in rendered  # markup shown literally, not interpreted


async def test_drive_learn_folds_real_feedback_into_memory(output: StringIO) -> None:
    """Against a real engine over fakes, the correction is folded and reported (§3)."""
    engine = _engine()
    event = FeedbackEvent(
        kind=FeedbackKind.CORRECTION,
        memory_kind=MemoryKind.SEMANTIC,
        content="the office is in Boston",
        created_at=AT,
    )
    code = await cli._drive_learn(engine, event)
    assert code == 0
    assert "Learned" in output.getvalue()
    await engine.aclose()


# --- beliefs / forget: the inspection surface (ADR-0073 §4, §5, §7) -----


#: The instant a source says a fact was current — **its** clock, not ours, and
#: deliberately nowhere near ``AT``. ADR-0073 §4's floor is that a surface must not
#: offer our revision time as the source's, and two instants that could be mistaken
#: for each other would let a renderer breach it and still pass (ADR-0092 §3: a
#: ``reported_at`` earlier than ours is the normal case, not an anomaly).
REPORTED_AT: Final = datetime(2026, 3, 2, 8, 30, tzinfo=UTC)

#: What reported an attested record, as the store holds it (ADR-0092 §1).
ATTESTED_BY: Final = Attestation(reported_by="work-calendar", reported_at=REPORTED_AT)


def _belief(  # noqa: PLR0913 — one knob per field a Belief carries; that is the point
    band: BeliefBand = BeliefBand.ASSERTED,
    *,
    belief_id: str = "rec-1",
    content: str = "the office is in Boston",
    confidence: float = 1.0,
    evidence: tuple[Evidence, ...] = (),
    valid_until: datetime | None = None,
    evidence_elided: int = 0,
    attestation: Attestation | None = None,
    rests_on_recorded_external_content: bool = False,
    kind: MemoryKind = MemoryKind.SEMANTIC,
) -> Belief:
    """One projected belief, as the façade hands it to the adapter.

    ``confidence`` is the **presented** number: the engine has already adjusted it
    for lost support (ADR-0077 §6), so a case scripting a tombstone also scripts the
    lowered figure rather than expecting this module to compute one.

    ``attestation`` and ``rests_on_recorded_external_content`` are ADR-0189 §2's two
    fields, and both default to their additive defaults so every case written before
    that ADR still builds the belief it did. They are **independent knobs rather than
    derived from the band**, because §2 adds no cross-field validator to this type and
    the surface must answer for the off-contract state as well as the ruled ones.

    ``kind`` is a knob for the same reason ADR-0223 §5 needs one: a captured episode is
    projected into this listing like anything else, and the row it renders is the one
    that arm is about. It defaults to what every case before that ADR built.
    """
    return Belief(
        id=belief_id,
        band=band,
        kind=kind,
        content=content,
        confidence=confidence,
        evidence=evidence,
        last_updated=AT,
        valid_until=valid_until,
        evidence_elided=evidence_elided,
        attestation=attestation,
        rests_on_recorded_external_content=rests_on_recorded_external_content,
    )


def _summary(  # noqa: PLR0913 — one knob per field a BeliefSummary carries; that is the point
    band: BeliefBand = BeliefBand.ASSERTED,
    *,
    belief_id: str = "rec-1",
    content: str = "the office is in Boston",
    confidence: float = 1.0,
    evidence_count: int = 0,
    lost_evidence: int = 0,
    valid_until: datetime | None = None,
    evidence_elided: int = 0,
    attestation: Attestation | None = None,
    rests_on_recorded_external_content: bool = False,
    kind: MemoryKind = MemoryKind.SEMANTIC,
) -> BeliefSummary:
    """One listing row, as the façade hands it to the adapter (ADR-0085 §4a).

    The counts are **fields** here rather than derived, because the listing type
    carries no citations to derive them from — which is what makes it impossible
    for a page to ship an episode's text.

    It takes the same two ADR-0189 §2 knobs as :func:`_belief`, under the same names,
    which is ADR-0107 §3's ruling made testable: the listing row and the row it links
    to answer the same question or the projection is defective in one place.
    """
    return BeliefSummary(
        id=belief_id,
        band=band,
        kind=kind,
        content=content,
        confidence=confidence,
        evidence_count=evidence_count,
        lost_evidence=lost_evidence,
        last_updated=AT,
        valid_until=valid_until,
        evidence_elided=evidence_elided,
        attestation=attestation,
        rests_on_recorded_external_content=rests_on_recorded_external_content,
    )


def _cited(*contents: str) -> tuple[Evidence, ...]:
    """Citations that still resolve, one per content given."""
    return tuple(Evidence(content=content) for content in contents)


#: One citation that no longer resolves — a tombstone (ADR-0077 §6).
_GONE = Evidence()


def _flat(rendered: str) -> str:
    """Collapse Rich's line wrapping, so an assertion is about words and not width."""
    return " ".join(rendered.split())


class _RecordingBeliefEngine:
    """A stand-in façade recording the inspection calls the commands make."""

    def __init__(self, page: tuple[Belief, ...] = (), *, one: Belief | None = None) -> None:
        self._page = page
        self._one = one
        self.listed: list[tuple[object, object, int, int]] = []
        self.forgotten: list[str] = []

    async def beliefs(
        self,
        *,
        bands: object = None,
        kinds: object = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Belief, ...]:
        self.listed.append((bands, kinds, limit, offset))
        return self._page

    async def belief(self, record_id: str) -> Belief | None:
        return self._one

    async def forget(self, record_id: str) -> bool:
        self.forgotten.append(record_id)
        return True

    async def start(self) -> None:
        """The start-up sweeps, which this stand-in has no stores to sweep."""

    async def aclose(self) -> None:
        """Nothing to release: this stand-in owns no resource."""


def test_render_belief_conveys_everything_the_surface_owes(output: StringIO) -> None:
    """Band, kind, confidence, content, why, revision time and id are all shown (§4)."""
    cli._render_belief(_belief())
    rendered = output.getvalue()
    assert "asserted" in rendered  # the band, stated and not implied by position
    assert "semantic" in rendered
    assert "1.00" in rendered
    assert "the office is in Boston" in rendered
    assert "you told me" in rendered  # why it is held
    assert "2026-07-24 09:00 UTC" in rendered  # when it was last revised
    assert "rec-1" in rendered  # the id ``forget`` takes


def test_render_belief_shows_a_window_end_only_when_one_is_set(output: StringIO) -> None:
    """An open window carries no information; a set end does ("believed until…")."""
    cli._render_belief(_belief())
    assert "Believed until" not in output.getvalue()

    cli._render_belief(_belief(valid_until=datetime(2026, 8, 1, tzinfo=UTC)))
    assert "Believed until" in output.getvalue()
    assert "2026-08-01 00:00 UTC" in output.getvalue()


def test_render_belief_neutralises_engine_supplied_text(output: StringIO) -> None:
    """Content and id carrying control bytes or markup are neutralised (ADR-0042 §4)."""
    cli._render_belief(_belief(content="wipe\x1b[2J and [red]shout[/red]"))
    rendered = output.getvalue()
    assert "\x1b" not in rendered
    assert "[red]" in rendered  # shown literally, not interpreted as colour


def test_why_reports_how_much_evidence_a_derived_belief_rests_on(output: StringIO) -> None:
    """ADR-0073 §4's derived floor, now that ADR-0077 §6 has discharged its gate.

    The citations are counted and — in the listing — reported as a count rather than
    as ids. What has changed is that the surface no longer says it cannot show them:
    it can, and the single-belief view does.
    """
    cli._render_belief(_belief(BeliefBand.DERIVED, confidence=0.62, evidence=_cited("a", "b", "c")))
    rendered = _flat(output.getvalue())
    assert "3 piece(s) of evidence" in rendered
    assert "cannot show you" not in rendered


def test_why_does_not_claim_evidence_a_derived_belief_does_not_have(output: StringIO) -> None:
    """A derived belief with no recorded citation says so rather than implying one."""
    cli._render_belief(_belief(BeliefBand.DERIVED, confidence=0.4))
    rendered = _flat(output.getvalue())
    assert "no supporting evidence was recorded" in rendered
    assert "piece(s) of evidence" not in rendered


def test_why_states_the_elision_ceiling_beside_the_count_it_kept(output: StringIO) -> None:
    """ADR-0107 §5: a floor, a ceiling, and capacity rather than loss.

    The shape is ADR-0086 §4's — "``len(evidence)`` citations shown, and *up to*
    ``evidence_elided`` further episodes supported this belief and are no longer
    carried" — and all three of its parts are pinned, because any one of them
    missing is a different wrong answer:

    * the **floor** is the retained count, still rendered;
    * the **ceiling** reads as *up to*, never as a total, because the number
      double-counts in the two cases ADR-0086 §4 names, and adding it to the floor
      would state a figure no citation corresponds to;
    * it reads as **capacity, not loss** — the episodes may be perfectly intact and
      the line says the reference was dropped, which is ADR-0091 §1's second clause
      and the whole difference between an elision and a tombstone.

    Asserted against the exact number rather than merely against the words "up to",
    per ADR-0107 §8 item 6.
    """
    cli._render_belief(
        _belief(
            BeliefBand.DERIVED,
            confidence=0.62,
            evidence=_cited("a", "b", "c"),
            evidence_elided=900,
        )
    )
    rendered = _flat(output.getvalue())
    assert "3 piece(s) of evidence" in rendered  # the floor
    assert "Up to 900 more piece(s) stood behind it" in rendered  # the ceiling, exact
    assert "those may still exist" in rendered  # capacity…
    assert "they were not lost" in rendered  # …and not loss


def test_why_says_nothing_of_a_ceiling_when_nothing_was_displaced(output: StringIO) -> None:
    """ADR-0107 §5 fires on ``evidence_elided > 0`` and is silent otherwise.

    The counterpart to the case above, and what stops the clause being satisfied by
    a line that always talks about elisions. Every belief in a deployment that has
    never reached ADR-0086 §1's bound is this case, so a stray "up to 0 more" would
    be the ordinary reading rather than the rare one.
    """
    cli._render_belief(_belief(BeliefBand.DERIVED, confidence=0.62, evidence=_cited("a", "b", "c")))
    rendered = _flat(output.getvalue())
    assert "3 piece(s) of evidence" in rendered
    assert "stood behind it" not in rendered
    assert "Up to" not in rendered


def test_why_does_not_tell_an_elided_belief_that_nothing_supports_it(output: StringIO) -> None:
    """ADR-0107 §7's repair, on the sentence it names by name.

    "…but nothing supports it any more" is false for a belief that also elided nine
    hundred citations: ADR-0086 §4 rules that "an elided citation is not unresolved,
    and the belief did not lose support — the record lost the reference", so those
    episodes may be intact and still supporting it. §7 requires the disclosure to
    say **both** that every citation it still carries has gone **and** that up to
    ``evidence_elided`` further ones stood behind it whose fate this surface cannot
    report; all of that is asserted here.

    **The predicate is untouched**, which is asserted directly rather than left to
    the rendering to imply. ``unsupported`` is still ADR-0085 §4a's ``evidence_count
    > 0 and lost_evidence == evidence_count`` on both types: §7 refused to add ``and
    evidence_elided == 0`` to it, because that answers the question with a confident
    ``False`` no better founded than the confident ``True``. The honest repair is at
    the sentence, where "we cannot say" is expressible, and not at a boolean.
    """
    belief = _belief(
        BeliefBand.DERIVED, confidence=0.1, evidence=(_GONE, _GONE), evidence_elided=900
    )
    assert belief.unsupported is True  # the ratified predicate, unchanged

    cli._render_belief(belief)
    rendered = _flat(output.getvalue())
    assert "nothing supports it any more" not in rendered  # the false statement, gone
    assert "none of which still exists" in rendered  # what *is* true is still said
    assert "I still hold it" in rendered  # and it is still held, not retired
    assert "Up to 900 more piece(s) stood behind it" in rendered
    assert "those may still exist" in rendered


def test_why_does_not_claim_no_evidence_was_recorded_when_some_was_displaced(
    output: StringIO,
) -> None:
    """The fourth derived state, which ADR-0107 §7's prohibition also reaches.

    A derived belief carrying no citations *now* but having displaced some is not a
    belief for which "no supporting evidence was recorded": evidence was recorded,
    and the reference to it was dropped. That is the statement §7 forbids on every
    band, in its most absolute form — so this branch is repaired rather than left as
    the one derived state that renders its count and owes no ceiling.
    """
    cli._render_belief(_belief(BeliefBand.DERIVED, confidence=0.4, evidence_elided=12))
    rendered = _flat(output.getvalue())
    assert "no supporting evidence was recorded" not in rendered
    assert "I carry no evidence for it now" in rendered
    assert "Up to 12 more piece(s) stood behind it" in rendered


def test_the_listing_row_states_the_same_ceiling_as_the_single_belief_view(
    output: StringIO,
) -> None:
    """One name, one renderer, one line — on both types (ADR-0107 §3, ADR-0085 §4a).

    ADR-0107 §3 put the field on ``Belief`` as well as ``BeliefSummary`` precisely so
    drilling into a belief cannot *lose* information: ADR-0077 §6 makes the
    single-belief view the fuller answer, and it is the view ``forget`` renders
    before destroying a record. A field on one type only would fork ``_why`` and
    invert that split, so the two lines are asserted to be the same line.
    """
    cli._render_belief_summary(
        _summary(
            BeliefBand.DERIVED,
            confidence=0.35,
            evidence_count=2,
            lost_evidence=1,
            evidence_elided=900,
        )
    )
    rendered = _flat(output.getvalue())
    assert "2 piece(s) of evidence" in rendered
    assert "1 of which no longer exists" in rendered
    assert "Up to 900 more piece(s) stood behind it" in rendered
    assert "Because:" not in rendered, "the listing still ships no citations"


def test_an_elision_is_never_rendered_among_the_citations(output: StringIO) -> None:
    """ADR-0107 §8 item 4: ``_render_evidence`` is not touched, and this is why.

    ``Evidence`` has one nullable field, so a lost citation is one whose content is
    ``None`` — meaning an entry standing for an elision would read as a **tombstone**
    to every reader. That is the conflation ADR-0091 §1's second clause forbids and
    ADR-0086 §4 calls "telling the user their data was lost when it was not". The
    ceiling belongs on the ``Why`` line, so the tombstone count in the citation list
    must not move with the elision.
    """
    cli._render_belief(
        _belief(
            BeliefBand.DERIVED,
            confidence=0.35,
            evidence=(_cited("they asked for metric units")[0], _GONE),
            evidence_elided=900,
        )
    )
    rendered = _flat(output.getvalue())
    assert rendered.count("an item of evidence stood here and is gone") == 1
    assert "Up to 900 more piece(s) stood behind it" in rendered


@pytest.mark.parametrize(
    ("band", "expected"),
    [
        (BeliefBand.ASSERTED, "you told me, and your own word is the whole of it."),
        (
            BeliefBand.ATTESTED,
            "a connected source reported it — work-calendar, neither your word nor my "
            "inference. That source said this was current as of 2026-03-02 08:30 UTC, "
            "on its own clock; 'Last revised' below is when I changed my mind and not "
            "when the source spoke.",
        ),
    ],
)
def test_why_is_unchanged_on_the_bands_that_render_no_count(
    band: BeliefBand, expected: str
) -> None:
    """ADR-0107 §2's band scoping, pinned as a decision rather than an oversight.

    §2 owes the disclosure to ``DERIVED`` alone, because that is the bullet ADR-0073
    §4 put the citation-count floor in: an assertion's warrant is the user's own word
    and "there is nothing further to cite", and the attested floor is about the band,
    the reporting source and whose clock is shown, with no count in it at all. §5
    then requires nothing of a surface that renders no count. So these two lines owe
    no ceiling and gain none.

    **Asserted as full equality against a non-zero elision**, which is what makes it
    a pin: an implementation appending the ceiling unconditionally would still pass a
    mere absence-of-loss-wording check. Together with the parameterised projection
    test in ``tests/orchestration``, this is what stops a later reader "repairing"
    §2's scoping — the field *is* carried on these bands (§3), and choosing not to
    render it is the ruling.

    **ADR-0189 §4 changed the attested line and changed nothing about this ruling.**
    The line names the source and its clock now; it still renders no citation count,
    so it still owes no ceiling, and the equality is what proves the ceiling did not
    creep in beside the new sentence.
    """
    attestation = ATTESTED_BY if band is BeliefBand.ATTESTED else None
    held = _belief(band, confidence=0.9, evidence_elided=900, attestation=attestation)
    listed = _summary(band, confidence=0.9, evidence_elided=900, attestation=attestation)
    assert cli._why(held) == expected
    assert cli._why(listed) == expected


def test_why_marks_an_attested_belief_as_a_source_s_report_not_ours(output: StringIO) -> None:
    """ADR-0073 §4's attested floor: neither the user's word nor our inference.

    And our revision time is not offered as the source's — the line says outright
    that ``Last revised`` is when *we* changed our mind.
    """
    cli._render_belief(_belief(BeliefBand.ATTESTED, confidence=0.9, attestation=ATTESTED_BY))
    rendered = _flat(output.getvalue())
    assert "a connected source reported it" in rendered
    assert "neither your word nor my inference" in rendered
    assert "not when the source spoke" in rendered


# --- ADR-0189 §9: the origin reaches the six rendered surfaces ---------------
#
# Three of §9's six rendering paths are this module's — ``_why``,
# ``_render_retirements`` and ``_render_question`` — and each owes a test over an
# **attested, resolved** subject asserting that *both* ``reported_by`` and
# ``reported_at`` reach the rendered output. §9 says outright that a test asserting
# only that a field is populated, or only that the source is named, does not satisfy
# it, so every one of these reads the console's own bytes.


@pytest.mark.parametrize(
    "render",
    [
        pytest.param(cli._render_belief, id="belief"),
        pytest.param(cli._render_belief_summary, id="summary"),
    ],
)
def test_why_names_the_attesting_source_and_when_that_source_spoke(
    render: Callable[[Any], None], output: StringIO
) -> None:
    """ADR-0189 §9's first surface clause, on ``_why``: the source **and** the instant.

    #1276's limitation is gone. The line used to say the source and the report time
    were recorded and could not be shown here — true while the projection dropped them
    (ADR-0092 §1 makes an ``Attestation`` mandatory on this band, so the *store* always
    held both), and ADR-0189 §2 gave both belief DTOs somewhere to put one.

    **Both halves are asserted because ADR-0073 §4's gate is explicitly both**, and
    ADR-0189 §9 names ``reported_at`` as "the one an implementing lane will drop,
    because the source-naming half is the one everybody is talking about". A lane that
    named the source and left ``Last revised`` as the only instant would satisfy
    ADR-0098 §8's second clause and breach ADR-0073 §4's gate.

    **Run over both DTOs, which is #1517's second finding.** ``_why`` accepts either,
    so an attested ``Belief`` test alone satisfies every named belief path while an
    attested *listing* row renders the old generic explanation — the failure ADR-0107
    §3 already legislated against one field over when it refused both "put the field on
    ``BeliefSummary`` only" and "put it on ``Belief`` only".
    """
    attested = (
        _belief(BeliefBand.ATTESTED, confidence=0.9, attestation=ATTESTED_BY)
        if render is cli._render_belief
        else _summary(BeliefBand.ATTESTED, confidence=0.9, attestation=ATTESTED_BY)
    )
    render(attested)
    rendered = _flat(output.getvalue())
    assert "work-calendar" in rendered, "the reporting source is named"
    assert "2026-03-02 08:30 UTC" in rendered, "and the instant it spoke"


@pytest.mark.parametrize(
    "render",
    [
        pytest.param(cli._render_belief, id="belief"),
        pytest.param(cli._render_belief_summary, id="summary"),
    ],
)
def test_the_attested_line_still_refuses_to_offer_our_clock_as_the_sources(
    render: Callable[[Any], None], output: StringIO
) -> None:
    """ADR-0073 §4's floor, which ADR-0189 §4 restates and the new line makes riskier.

    §4: a surface "renders ``reported_at`` as the **source's** clock and never as this
    system's, and it does not offer ``last_updated`` in its place". ADR-0189's own
    Consequences names the newly-available error — "naming the source while still
    showing our clock as the source's" — so this asserts the two instants are both on
    screen, are different, and are labelled for whose clock each is.
    """
    attested = (
        _belief(BeliefBand.ATTESTED, confidence=0.9, attestation=ATTESTED_BY)
        if render is cli._render_belief
        else _summary(BeliefBand.ATTESTED, confidence=0.9, attestation=ATTESTED_BY)
    )
    render(attested)
    rendered = _flat(output.getvalue())
    assert "on its own clock" in rendered, "the source's instant is labelled as the source's"
    assert "Last revised: 2026-07-24 09:00 UTC" in rendered, "ours is still shown"
    assert "not when the source spoke" in rendered, "and is still declared to be ours"
    assert "2026-03-02" in rendered, "beside a genuinely different instant"


def test_why_reads_the_source_as_a_source_and_never_as_a_person(output: StringIO) -> None:
    """ADR-0189 §4's second clause, ADR-0098 §8's third adopted unchanged.

    A surface "renders the source at **source granularity and no finer** … a surface
    that rendered ``reported_by`` as though it named a person would assert what this
    system does not hold". ADR-0093 §7 forbids deriving a reader's identity from the
    source's location or contents, so the organiser of an invite and the sender of a
    mail are not on the record — and ADR-0098 §8 states the cost of pretending
    otherwise: "a user who reads 'someone sent you' will read the name they are shown
    as that someone".

    Pinned on the apposition rather than on the absence of a name, because there is no
    list of person-words to check against: what makes the value unreadable as a person
    is that it is introduced as a connected source.
    """
    cli._render_belief(
        _belief(
            BeliefBand.ATTESTED,
            confidence=0.9,
            attestation=Attestation(reported_by="alice", reported_at=REPORTED_AT),
        )
    )
    rendered = _flat(output.getvalue())
    assert "a connected source reported it — alice" in rendered
    assert "That source said this was current" in rendered


def test_why_says_what_reached_it_when_an_attested_belief_carries_no_attestation(
    output: StringIO,
) -> None:
    """The off-contract arm, which ADR-0189 §2 leaves constructable on purpose.

    §2 adds **no** cross-field validator to ``Belief``, ``BeliefSummary`` or
    ``Question`` — those are ratified types with construction sites in the tree, and
    ADR-0086 §3's admissibility test refuses a validator that would refuse what already
    works — so the type admits an attested belief with no attestation even though
    ``Provenance``'s own validator means no store can produce one.

    What the line must not do is either of the two available lies: claiming the
    attestation was **not recorded**, which errs in the direction ADR-0073 §4 forgives
    least on the one band whose whole purpose is provenance, or reviving #1276's
    "cannot show them here", which would claim a limit this projection no longer has.
    What is true either way is that this surface was not handed it.
    """
    cli._render_belief(_belief(BeliefBand.ATTESTED, confidence=0.9))
    rendered = _flat(output.getvalue())
    assert "does not name that source or say when it spoke" in rendered
    assert "not recorded" not in rendered
    assert "cannot show them here" not in rendered


@pytest.mark.parametrize(
    "render",
    [
        pytest.param(cli._render_belief, id="belief"),
        pytest.param(cli._render_belief_summary, id="summary"),
    ],
)
def test_why_says_a_derived_warrant_came_from_outside_without_reattributing_the_words(
    render: Callable[[Any], None], output: StringIO
) -> None:
    """#1517's first finding, and ADR-0189 §4's third clause, on ``_why``.

    §9's own matrix has no arm for this: it requires an attested-and-resolved test on
    all six paths and a tombstone test on the two retirement paths, and **nothing that
    exercises the derived arm**. So a renderer could show ``reported_by`` and
    ``reported_at`` correctly everywhere, omit the marker for every ``DERIVED`` record
    with the predicate ``True``, and pass all eight required tests while breaching §4.

    **The second half is the harder one and is why this is one test rather than two.**
    §4 forbids the reach as explicitly as it requires the marker: a surface "does
    **not** present the record's own content as third-party text on that ground: the
    content is a sentence this system's model wrote, and ADR-0098 §1 decides
    externality by the recorded origin of the text". ADR-0098 §7's own round-6 draft
    made exactly that reach and architecture review had to repair it, so the assertion
    that the *words* stay ours is asserted beside the marker rather than trusted.
    """
    outside = (
        _belief(
            BeliefBand.DERIVED,
            confidence=0.35,
            evidence=_cited("their calendar said Lisbon"),
            rests_on_recorded_external_content=True,
        )
        if render is cli._render_belief
        else _summary(
            BeliefBand.DERIVED,
            confidence=0.35,
            evidence_count=1,
            rests_on_recorded_external_content=True,
        )
    )
    render(outside)
    rendered = _flat(output.getvalue())
    assert "came from a connected source rather than from you" in rendered
    assert "still my own sentence" in rendered, "the words are not re-attributed"
    assert "someone else's words" not in rendered


@pytest.mark.parametrize(
    "render",
    [
        pytest.param(cli._render_belief, id="belief"),
        pytest.param(cli._render_belief_summary, id="summary"),
    ],
)
def test_why_says_nothing_about_the_outside_when_the_predicate_is_false(
    render: Callable[[Any], None], output: StringIO
) -> None:
    """The silence is ruled, not an omission (ADR-0098 §5, ADR-0106 §1).

    A ``False`` is *nothing external is recorded in this warrant*, never *nothing
    external influenced it*: text whose recorded origin is not external can still have
    reached a belief — through a plan rationale our own model authored over an
    attacker's sentence — and no field on the record says so. So a surface printing the
    negative would assert what this system does not hold, which ADR-0098 §5 marks as a
    limit and ADR-0106 §1's second clause binds every marker ADR-0189 projects to.
    """
    inside = (
        _belief(BeliefBand.DERIVED, confidence=0.35, evidence=_cited("they said so twice"))
        if render is cli._render_belief
        else _summary(BeliefBand.DERIVED, confidence=0.35, evidence_count=1)
    )
    render(inside)
    rendered = _flat(output.getvalue())
    assert "connected source" not in rendered
    assert "outside" not in rendered
    assert "1 piece(s) of evidence" in rendered, "the rest of the derived line is unchanged"


#: The sentence a stamped **belief** gets, which ADR-0223 §5 forbids on an episode:
#: every clause of it is false of a recorded exchange.
_BELIEF_SENTENCE = "Some of what I worked it out from came from a connected source"

#: The sentence a stamped **episode** gets instead (ADR-0223 §5's second clause).
_EPISODIC_SENTENCE = (
    "Some of the material I had in front of me during this exchange traces back to a "
    "connected source"
)


@pytest.mark.parametrize(
    "render",
    [
        pytest.param(cli._render_belief, id="belief"),
        pytest.param(cli._render_belief_summary, id="summary"),
    ],
)
def test_a_stamped_episode_gets_the_episodic_arm_and_never_the_belief_sentence(
    render: Callable[[Any], None], output: StringIO
) -> None:
    """ADR-0223 §5's second clause, on the CLI half of §10's eighth test.

    Once ADR-0223 §1 stamps the mark on a captured episode the predicate is ``True``
    of a record the belief sentence is false of in every clause: "the system did not
    work the episode out, there is nothing it worked it out *from* — ``evidence`` is
    empty by ADR-0074 §4 — and the episode's warrant is that it happened, which is
    entirely this system's own".

    So the arm is asserted in both directions. The episodic sentence is present, and
    the belief sentence is asserted **absent** — a listing that appended both, or that
    kept the old one for a kind nobody thought about, is the failure §5 exists to
    prevent and a presence-only check would pass it.

    **And the content is not re-attributed**, which §5 carries over from ADR-0189 §4
    unchanged: no part of the episode is presented as a source's words. The record
    stays this system's own account of the exchange, which is what ADR-0074 §4 makes
    it — "the terminal citation: the thing other records cite".
    """
    stamped = (
        _belief(
            BeliefBand.DERIVED,
            kind=MemoryKind.EPISODIC,
            content="you asked where the office is; I answered Boston",
            rests_on_recorded_external_content=True,
        )
        if render is cli._render_belief
        else _summary(
            BeliefBand.DERIVED,
            kind=MemoryKind.EPISODIC,
            content="you asked where the office is; I answered Boston",
            rests_on_recorded_external_content=True,
        )
    )
    render(stamped)
    rendered = _flat(output.getvalue())
    assert _EPISODIC_SENTENCE in rendered
    assert "the record above is still my own account of what was said" in rendered
    assert _BELIEF_SENTENCE not in rendered, "the belief sentence is false of an episode"
    assert "warrant" not in rendered, "an episode's warrant is not a derivation to describe"
    assert "someone else's words" not in rendered


@pytest.mark.parametrize(
    "render",
    [
        pytest.param(cli._render_belief, id="belief"),
        pytest.param(cli._render_belief_summary, id="summary"),
    ],
)
def test_an_unstamped_episodes_row_is_the_episodic_line_and_nothing_more(
    render: Callable[[Any], None], output: StringIO
) -> None:
    """The no-drift half of ADR-0223 §10's eighth test, re-pinned to a moved baseline.

    §10's eighth test asked that "an unstamped episode's row is byte-identical to
    today's", and this case is what asserted it. **That pin was the stamp lane's
    no-drift guard, not a ratification of the sentence it happened to pin**, and this
    case is re-pointed at the line #1891 gives the row rather than deleted:

    * §10's numbered list is introduced as "the representative-input tests this
      decision owes", and — unlike the three clauses above it in that section — carries
      no ``> **Normative.**`` marker. It is the evidence ADR-0223 owes, and the
      evidence it owed was that a lane adding an arm for *stamped* episodes left the
      other arm where it found it.
    * ADR-0223 §5 says in terms what it thought of the sentence it was pinning: the
      belief line on an episode is "a pre-existing oddity of rendering an episode
      through a belief renderer", which appending the external sentence would turn
      "into a claim". §5 declines to repair the oddity — it does not bless it, and an
      ADR that calls a line an oddity has not decided that line is correct.
    * §10's third normative clause forbids discharging either arm "by suppressing the
      fact". Nothing here suppresses it: the stamped row keeps ADR-0223 §5's sentence,
      character for character, and the head sentence in front of it is the one thing
      §5 left to the surface (ADR-0189 §4 "states what a surface conveys and leaves the
      wording to it"; ADR-0072 §6 says the same).

    So the property this case now holds is the same property, over the new baseline:
    an episode nothing external reached says the episodic line **and only** the
    episodic line, with no trace of the arm that belongs to a stamped row. Asserted as
    the exact ``Why`` line rather than as an absence, for the reason it always was — an
    arm that appended a sentence with the marker missing from it would pass every
    absence check here.
    """
    unstamped = (
        _belief(BeliefBand.DERIVED, kind=MemoryKind.EPISODIC)
        if render is cli._render_belief
        else _summary(BeliefBand.DERIVED, kind=MemoryKind.EPISODIC)
    )
    render(unstamped)
    rendered = _flat(output.getvalue())
    assert (
        "Why: this records an exchange that happened — I captured it at the time, so "
        "there was nothing to work out and nothing to weigh. The line above files it "
        "among my beliefs because that is where a captured turn sits, and the "
        "confidence there is a standing figure rather than a measure of doubt that it "
        "happened. Last revised:"
    ) in rendered
    assert "connected source" not in rendered
    assert "traces back" not in rendered, "and the silence is silence, not the episodic arm"
    assert "I worked it out" not in rendered, "the derived line is false of a recorded turn"


@pytest.mark.parametrize(
    "render",
    [
        pytest.param(cli._render_belief, id="belief"),
        pytest.param(cli._render_belief_summary, id="summary"),
    ],
)
def test_an_episode_is_explained_as_a_record_and_never_as_a_derivation(
    render: Callable[[Any], None], output: StringIO
) -> None:
    """#1891: an episode's ``Why`` is that it happened (ADR-0075 §2).

    A captured turn carries ``OBSERVED`` provenance, so ``band_of`` files it in the
    ``DERIVED`` band and it used to be explained by the derived line — "I worked it
    out, and no supporting evidence was recorded". ADR-0075 §2 is what that
    contradicts: recording an exchange "is true because it happened, a policy has
    nothing to weigh". So the row says it was recorded, says nothing was worked out,
    and does not offer the empty evidence list as a deficiency — ADR-0074 §4 leaves an
    episode's ``evidence`` empty **by decision**.

    Asserted in both directions, because a line that added an honest sentence and kept
    the false one would pass a presence-only check.
    """
    render(
        _belief(BeliefBand.DERIVED, kind=MemoryKind.EPISODIC)
        if render is cli._render_belief
        else _summary(BeliefBand.DERIVED, kind=MemoryKind.EPISODIC)
    )
    rendered = _flat(output.getvalue())

    assert "this records an exchange that happened" in rendered
    assert "I captured it at the time" in rendered
    assert "I worked it out" not in rendered
    assert "no supporting evidence was recorded" not in rendered, (
        "an empty evidence list is ADR-0074 §4's decision, not a shortfall to report"
    )


@pytest.mark.parametrize(
    "render",
    [
        pytest.param(cli._render_belief, id="belief"),
        pytest.param(cli._render_belief_summary, id="summary"),
    ],
)
def test_an_episodes_row_still_carries_its_band_and_confidence_and_says_what_they_are(
    render: Callable[[Any], None], output: StringIO
) -> None:
    """#1891's open display question, answered: the heading stays and the line explains it.

    ADR-0073 §4 requires **every** row to convey its band — "never omitted, never
    implied by position alone" — and its confidence, and grants no kind an exemption;
    ADR-0072 §6 rules the same of anything rendered as a belief. So the fix for the
    belief vocabulary is not to drop the two fields but to stop the row implying that
    the 0.90 is how sure this system is that the conversation took place: ADR-0074 §4
    sets it at capture and documents it as standing rather than certainty.

    Pinned as *both* halves. The header is asserted present because a later lane
    reading only the ``Why`` line might take it for dead weight, and the sentence that
    disarms it is asserted present because the header without it is exactly what #1891
    reported.
    """
    render(
        _belief(BeliefBand.DERIVED, kind=MemoryKind.EPISODIC, confidence=0.9)
        if render is cli._render_belief
        else _summary(BeliefBand.DERIVED, kind=MemoryKind.EPISODIC, confidence=0.9)
    )
    rendered = _flat(output.getvalue())

    assert "derived · episodic · confidence 0.90" in rendered
    assert "the confidence there is a standing figure rather than a measure of doubt" in (rendered)


def test_a_derived_belief_of_another_kind_keeps_the_line_it_had(output: StringIO) -> None:
    """The episodic arm is a branch off the derived one, never a replacement.

    ADR-0073 §4's derived floor — the band, the citation count, and never a warrant
    the surface cannot show — is untouched for the three kinds that are beliefs, and a
    fifth ``MemoryKind`` added to ``core`` would take the belief line rather than
    silently inheriting an episode's. Pinned on ``PROCEDURAL`` because the semantic
    case is what every other case in this file renders.
    """
    cli._render_belief_summary(_summary(BeliefBand.DERIVED, kind=MemoryKind.PROCEDURAL))
    rendered = _flat(output.getvalue())

    assert "Why: I worked it out, and no supporting evidence was recorded." in rendered
    assert "this records an exchange that happened" not in rendered


def test_a_stamped_belief_of_another_kind_is_left_on_the_belief_sentence(
    output: StringIO,
) -> None:
    """The arm is an addition, not a redirection (ADR-0223 §5, ADR-0189 §4 unnarrowed).

    §5's first clause is explicit that ADR-0189 §4's third clause is "not narrowed,
    exempted or conditioned" — so the three non-episodic kinds keep the sentence they
    had, and a fifth ``MemoryKind`` added to ``core`` would take it too rather than
    silently losing the disclosure. Pinned on ``PROCEDURAL`` because the semantic case
    is the one every other test in this file already renders.
    """
    cli._render_belief_summary(
        _summary(
            BeliefBand.DERIVED,
            kind=MemoryKind.PROCEDURAL,
            evidence_count=1,
            rests_on_recorded_external_content=True,
        )
    )
    rendered = _flat(output.getvalue())
    assert _BELIEF_SENTENCE in rendered
    assert _EPISODIC_SENTENCE not in rendered


async def test_beliefs_listed_by_episodic_kind_carry_the_episodic_arm(
    output: StringIO,
) -> None:
    """ADR-0223 §10's eighth test, driven the way the documented command drives it.

    ``assistant beliefs --kind episodic`` is documented in this module as the way to
    "see captured conversation turns", and §5's chain runs from there: the façade
    lists what it holds, ``_render_beliefs`` renders each row, and ``_why`` reaches
    ``_why_derived`` because a captured episode's provenance is ``OBSERVED`` and
    ``band_of`` puts that in the ``DERIVED`` band.

    Both rows are listed in one call so the two sentences are asserted against **one**
    rendering: an arm keyed on the kind is only worth anything if the row beside it is
    unaffected, and a per-case assertion would not show that.

    The stamped episode is constructed here rather than captured, which is what makes
    this lane independent of the one landing ADR-0223 §1's stamp: the field exists on
    ``Provenance`` today, the projection carries it kind-blind by §5's first clause,
    and this surface has to answer for the row whether or not a producer writes one
    yet.
    """
    engine = FakeAssistantEngine()
    engine.beliefs_held["ep-1"] = _belief(
        BeliefBand.DERIVED,
        belief_id="ep-1",
        kind=MemoryKind.EPISODIC,
        content="you asked where the office is; I answered Boston",
        rests_on_recorded_external_content=True,
    )
    engine.beliefs_held["ep-2"] = _belief(
        BeliefBand.DERIVED,
        belief_id="ep-2",
        kind=MemoryKind.EPISODIC,
        content="you asked what time it was; I answered half past two",
    )

    code = await cli._drive_beliefs(
        engine, bands=None, kinds=[MemoryKind.EPISODIC], limit=50, offset=0
    )

    assert code == 0
    rendered = _flat(output.getvalue())
    assert rendered.count(_EPISODIC_SENTENCE) == 1, "the stamped row, and only it"
    assert _BELIEF_SENTENCE not in rendered
    assert "ep-2" in rendered, "and the unstamped episode is listed beside it, unchanged"


def test_an_episodes_two_lines_are_two_lines(output: StringIO) -> None:
    """#1890: the break inside a captured turn is a break, not ``\ufffd``.

    ``_exchange_of`` writes an episode as "The user asked: …" and "The assistant's
    plan: …" separated by a newline, and this row rendered that newline as the
    replacement character — :func:`~ai_assistant.interfaces.cli._safe` replaces it by
    default, which is #1336's fix reaching a value it was never aimed at. The content
    is the one field of the row printed as a block of its own, which is the carve-out
    :func:`~ai_assistant.interfaces.cli._safe_prose` exists for.

    Read off the **raw** buffer rather than through ``_flat``, because the line
    structure is the whole subject and flattening it would assert nothing.
    """
    cli._render_belief_summary(
        _summary(
            BeliefBand.DERIVED,
            kind=MemoryKind.EPISODIC,
            content="The user asked: where is the office?\nThe assistant's plan: answer directly.",
        )
    )
    rendered = output.getvalue()

    assert "\ufffd" not in rendered
    assert "  │ The user asked: where is the office?\n" in rendered
    assert "  │ The assistant's plan: answer directly.\n" in rendered, (
        "and both lines sit behind the gutter, so neither can be read as a field of the row"
    )


def test_a_break_in_a_records_content_cannot_forge_one_of_the_rows_own_fields(
    output: StringIO,
) -> None:
    """ADR-0042 §4's threat, arriving without a control character.

    :data:`~ai_assistant.core.types.EncodableText` asks only that a value be writable,
    so **any** kind's content may carry a newline — and printed as plain indented
    lines, ``fact\nWhy: …\nid: …`` is three fields of this row in the reader's own
    vocabulary, forged by a value the engine carried verbatim. It is the hole #1890's
    fix would open if it merely stopped replacing the break, and adversarial review
    found it on round 1.

    The gutter is what closes it: every line of a multi-line content is behind a
    marker no line this adapter writes ever carries, so a forged label arrives visibly
    inside the record's text. Asserted in both directions — the bare field line is
    **absent**, the marked one is present — because a check for the marker alone would
    pass a renderer that printed the line twice.
    """
    cli._render_belief_summary(
        _summary(content="the office is in Boston\nWhy: you told me this\nid: rec-9")
    )
    rendered = output.getvalue()

    assert "\n  Why: you told me this" not in rendered
    assert "\n  id: rec-9" not in rendered
    assert "  │ Why: you told me this\n" in rendered
    assert "  │ id: rec-9\n" in rendered
    assert rendered.count("  id: rec-1\n") == 1, "and the row's own id is still its own"


def test_the_gutter_reaches_the_lines_the_console_wraps_for_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The marker's promise is about display lines, not about logical ones.

    Rich does not repeat a literal prefix on the continuations it wraps: handed one
    long line it emits the gutter once and puts the remainder at the margin, so a
    crafted ``… Why: forged`` becomes a second display line the marker never reached —
    the whole defence, undone by a long enough content. Adversarial review, round 2,
    ``blocker``.

    Driven at a **40-column** console, because the default this file renders at hides
    the case: nothing short enough to fit ever wraps, which is exactly how the first
    round of cases missed it.
    """
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=40))

    cli._render_belief_summary(
        _summary(content="the office is in Boston\n" + "x " * 18 + "Why: forged")
    )
    lines = buffer.getvalue().splitlines()

    forged = [one for one in lines if "Why: forged" in one]
    assert forged, "the crafted text reached the screen at all"
    assert all(one.startswith("  │ ") for one in forged), (
        "and every display line it landed on carries the gutter"
    )
    assert len([one for one in lines if one.startswith("  │ ")]) > 2, (
        "the content really did wrap, so the case is exercising what it claims to"
    )


def test_a_single_line_content_is_printed_exactly_as_it_always_was(output: StringIO) -> None:
    """The marker is bought only by the value that creates the risk.

    One line cannot forge a second, so a content with no break in it takes none of
    this: it renders the row every other case in this file renders, unchanged. Pinned
    because the alternative — marking every content on the surface — is a change to
    every row this system has ever printed, made for a hazard that is not present.
    """
    cli._render_belief_summary(_summary())
    rendered = output.getvalue()

    assert "\n  the office is in Boston\n" in rendered
    assert "│" not in rendered


def test_a_carriage_return_in_a_records_content_is_a_break_and_not_a_scribble(
    output: StringIO,
) -> None:
    """The ``\r`` half of the same fix, settled the way #1336 settled it.

    A carriage return *is* a character this terminal acts on — it returns the cursor
    to column zero, so what follows overwrites what came before, which is ADR-0042
    §4's threat in its purest form. Replacing it would leave the half-fixed rendering
    #1336 records; normalising ``\r\n`` and a lone ``\r`` to ``\n`` removes the
    character that overwrites *and* yields the break the producer meant.
    """
    cli._render_belief_summary(
        _summary(BeliefBand.DERIVED, kind=MemoryKind.EPISODIC, content="first\r\nsecond\rthird")
    )
    rendered = output.getvalue()

    assert "\r" not in rendered
    assert "\ufffd" not in rendered
    assert "  │ first\n  │ second\n  │ third\n" in rendered


def test_markup_split_across_a_break_in_a_records_content_is_still_escaped(
    output: StringIO,
) -> None:
    """The break is content; Rich markup is still neutralised (ADR-0042 §4).

    Rich's tag pattern matches across a newline, so ``[red\nbold]`` survives per-line
    escaping intact and is then consumed as markup — a value that reaches the screen
    *emptied* of what it said. The escape is therefore taken over the whole value and
    the split comes after it, which this case is what proves: both halves of the tag
    are still on the screen and neither was interpreted.
    """
    cli._render_belief_summary(
        _summary(BeliefBand.DERIVED, kind=MemoryKind.EPISODIC, content="[red\nbold] hello")
    )
    rendered = output.getvalue()

    assert "[red" in rendered
    assert "bold] hello" in rendered


def test_render_beliefs_reports_an_empty_page_plainly(output: StringIO) -> None:
    """Nothing matching is said, not shown as an empty success."""
    cli._render_beliefs((), limit=50, offset=0)
    assert "No live belief matches" in output.getvalue()


def test_render_beliefs_offers_the_next_page_without_claiming_a_total(
    output: StringIO,
) -> None:
    """A full page names the offset that would fetch the next; no count is shown (§7)."""
    cli._render_beliefs((_summary(belief_id="a"), _summary(belief_id="b")), limit=2, offset=4)
    rendered = _flat(output.getvalue())
    assert "--offset 6" in rendered
    assert "there may be more" in rendered


def test_render_beliefs_does_not_offer_a_next_page_for_a_short_one(output: StringIO) -> None:
    """A page shorter than the limit is the end of the enumeration."""
    cli._render_beliefs((_summary(),), limit=50, offset=0)
    assert "--offset" not in output.getvalue()


@pytest.mark.parametrize(
    ("band", "expected"),
    [
        (BeliefBand.ASSERTED, "permanent"),
        (BeliefBand.DERIVED, "may reach it again"),
        (BeliefBand.ATTESTED, "may bring it back"),
    ],
)
def test_forget_prompt_warns_by_band_because_the_consequence_differs(
    band: BeliefBand, expected: str, output: StringIO
) -> None:
    """A deletion is represented as neither more final than it is nor less (§5)."""
    confidence = 1.0 if band is BeliefBand.ASSERTED else 0.5
    cli._render_forget_prompt(_belief(band, confidence=confidence))
    assert expected in _flat(output.getvalue())


def test_forget_prompt_shows_the_belief_and_scopes_the_consent(output: StringIO) -> None:
    """It renders what is about to go, and says what agreeing actually covers (§5, §6)."""
    cli._render_forget_prompt(_belief())
    rendered = _flat(output.getvalue())
    assert "the office is in Boston" in rendered  # shown before it can be destroyed
    assert "rec-1" in rendered
    assert "not even in an export" in rendered  # destroyed, not retired (§6)
    assert "learn --kind correction" in rendered  # the route that keeps it instead
    assert "when you answer" in rendered  # consent is to the id, not to these bytes


async def test_drive_beliefs_lists_what_the_engine_holds(output: StringIO) -> None:
    """Against a real engine over fakes, a stored belief is listed with its band."""
    engine = _engine()
    await engine.learn(
        FeedbackEvent(
            kind=FeedbackKind.CORRECTION,
            memory_kind=MemoryKind.SEMANTIC,
            content="the office is in Boston",
            created_at=AT,
        )
    )
    code = await cli._drive_beliefs(engine, bands=None, kinds=None, limit=50, offset=0)
    assert code == 0
    rendered = output.getvalue()
    assert "the office is in Boston" in rendered
    assert "asserted" in rendered  # what the user said lands in their own band
    await engine.aclose()


async def test_drive_beliefs_surfaces_a_read_failure_with_a_nonzero_exit(
    output: StringIO,
) -> None:
    """A MemoryStoreError from the read is rendered, not dumped, exit 1 (ADR-0042 §7)."""

    class _FailingEngine:
        async def beliefs(self, **_kwargs: object) -> tuple[Belief, ...]:
            msg = "the memory store would not read"
            raise MemoryStoreError(msg)

    code = await cli._drive_beliefs(
        _FailingEngine(),  # type: ignore[arg-type]  # the adapter needs only this call
        bands=None,
        kinds=None,
        limit=50,
        offset=0,
    )
    assert code == 1
    assert "would not read" in output.getvalue()


async def test_drive_forget_shows_the_belief_before_it_asks(output: StringIO) -> None:
    """Show, then confirm: the approver never runs before the render (§5)."""
    engine = _RecordingBeliefEngine(one=_belief())
    shown_before_asking = False

    def approve(_belief_shown: Belief) -> bool:
        nonlocal shown_before_asking
        shown_before_asking = "the office is in Boston" in output.getvalue()
        return True

    code = await cli._drive_forget(engine, "rec-1", confirm=approve)  # type: ignore[arg-type]
    assert code == 0
    assert shown_before_asking
    assert engine.forgotten == ["rec-1"]
    assert "Forgotten" in output.getvalue()


async def test_drive_forget_destroys_nothing_when_the_answer_is_no(output: StringIO) -> None:
    """A refusal is a valid outcome: nothing is deleted and the exit code is 0."""
    engine = _RecordingBeliefEngine(one=_belief())
    code = await cli._drive_forget(engine, "rec-1", confirm=lambda _b: False)  # type: ignore[arg-type]
    assert code == 0
    assert engine.forgotten == []
    assert "Left alone" in output.getvalue()


async def test_drive_forget_declines_an_id_naming_no_live_belief(output: StringIO) -> None:
    """A retired or unknown id is declined rather than deleted blind, exit 1 (§5)."""
    engine = _RecordingBeliefEngine(one=None)
    asked = False

    def approve(_belief_shown: Belief) -> bool:
        nonlocal asked
        asked = True
        return True

    code = await cli._drive_forget(engine, "gone", confirm=approve)  # type: ignore[arg-type]
    assert code == 1
    assert asked is False  # nothing was shown, so nothing could be consented to
    assert engine.forgotten == []
    assert "No live belief has the id" in _flat(output.getvalue())


async def test_drive_forget_reports_a_belief_that_vanished_before_the_delete(
    output: StringIO,
) -> None:
    """``forget`` returning False is rendered and mapped to a non-zero exit (§7)."""

    class _VanishingEngine(_RecordingBeliefEngine):
        async def forget(self, record_id: str) -> bool:
            self.forgotten.append(record_id)
            return False

    engine = _VanishingEngine(one=_belief())
    code = await cli._drive_forget(engine, "rec-1", confirm=lambda _b: True)  # type: ignore[arg-type]
    assert code == 1
    assert "already gone" in output.getvalue()


async def test_drive_forget_end_to_end_against_a_real_engine(output: StringIO) -> None:
    """A belief the engine holds is shown, agreed to, and gone from the listing (§5)."""
    engine = _engine()
    await engine.learn(
        FeedbackEvent(
            kind=FeedbackKind.CORRECTION,
            memory_kind=MemoryKind.SEMANTIC,
            content="the office is in Boston",
            created_at=AT,
        )
    )
    page = await engine.beliefs()
    assert len(page) == 1

    code = await cli._drive_forget(engine, page[0].id, confirm=lambda _b: True)
    assert code == 0
    assert "Forgotten" in output.getvalue()
    assert await engine.beliefs() == ()
    await engine.aclose()


def test_beliefs_command_relays_its_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated --band/--kind reach the façade; --limit/--offset are relayed as given."""
    engine = _RecordingBeliefEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app,
        [
            "beliefs",
            "--band",
            "derived",
            "--band",
            "attested",
            "--kind",
            "semantic",
            "--limit",
            "5",
            "--offset",
            "10",
        ],
    )
    assert result.exit_code == 0
    assert engine.listed == [
        ([BeliefBand.DERIVED, BeliefBand.ATTESTED], [MemoryKind.SEMANTIC], 5, 10)
    ]


def test_beliefs_command_asks_for_every_band_but_excludes_episodes_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An absent ``--band`` means "every"; an absent ``--kind`` means "every belief".

    Two different defaults, on purpose. ``--band`` absent is "every band", because
    an empty filter would select nothing (ADR-0073 §1). ``--kind`` absent is every
    kind **except** ``EPISODIC`` (ADR-0074 §6): this command answers "what do you
    believe about me", and an episode is the evidence a belief is made of rather
    than a belief — so left kind-blind it would print a transcript through the
    surface leg 1 built to be readable, the moment capture started writing turns.
    """
    engine = _RecordingBeliefEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["beliefs"])
    assert result.exit_code == 0
    assert engine.listed == [
        (None, [MemoryKind.SEMANTIC, MemoryKind.PREFERENCE, MemoryKind.PROCEDURAL], 50, 0)
    ]


def test_beliefs_command_still_lists_episodes_when_they_are_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0074 §6: the default narrows the listing; it does not remove the surface."""
    engine = _RecordingBeliefEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["beliefs", "--kind", "episodic"])
    assert result.exit_code == 0
    assert engine.listed == [(None, [MemoryKind.EPISODIC], 50, 0)]


@pytest.mark.parametrize("bad", ["-1", str(2**63)])
def test_beliefs_command_rejects_a_page_the_store_would_refuse(
    bad: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An out-of-range --limit is a usage error, not an uncaught ValueError (§2, §7).

    ``list_beliefs`` raises ``ValueError`` outside ``[0, 2**63)``, and a ``ValueError``
    is not an ``AssistantError``, so it would escape the command's error boundary as
    a traceback. The parse-time check turns it into exit code 2 before any engine is
    built — and the recorded opens are what say the last four words are still true
    (#1970), since the refusal the parse-time check replaced was raised by the store,
    on the far side of a client.
    """
    opened = _wire_recording_opens(monkeypatch, FakeAssistantEngine())

    for flag in ("--limit", "--offset"):
        result = CliRunner().invoke(cli.app, ["beliefs", flag, bad])
        assert result.exit_code == 2, flag
        assert result.exception is None or isinstance(result.exception, SystemExit), flag
        assert opened == [], flag


def test_beliefs_command_rejects_an_unknown_band(monkeypatch: pytest.MonkeyPatch) -> None:
    """A band outside the ratified vocabulary is a usage error, before any engine.

    Typer resolves the enum during parsing, so nothing about this refusal needs a
    hub — and the recorded opens say so rather than leaving it to be inferred
    (#1970).
    """
    opened = _wire_recording_opens(monkeypatch, FakeAssistantEngine())

    result = CliRunner().invoke(cli.app, ["beliefs", "--band", "guessed"])

    assert result.exit_code == 2
    assert opened == []


def test_forget_command_renders_before_acting_under_yes(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--yes`` skips the question, not the rendering (ADR-0073 §5, ADR-0052 §4)."""
    engine = _RecordingBeliefEngine(one=_belief())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["forget", "rec-1", "--yes"])
    assert result.exit_code == 0
    assert engine.forgotten == ["rec-1"]
    rendered = _flat(output.getvalue())
    assert "the office is in Boston" in rendered  # the belief was still displayed
    assert "About to forget" in rendered


def test_forget_command_defaults_to_keeping_the_belief(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare Enter at the prompt does not destroy anything: the default is no."""
    engine = _RecordingBeliefEngine(one=_belief())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["forget", "rec-1"], input="\n")
    assert result.exit_code == 0
    assert engine.forgotten == []
    assert "Left alone" in output.getvalue()


# --- conversations: continuity, the listing, and the deletion (ADR-0074) ---


def _conversation_engine(
    *, composing: ComposingStage | None = None
) -> tuple[Engine, FakeConversationStore]:
    """A real ``Engine`` over canonical fakes, plus the conversation index behind it.

    The store is handed back so a case can assert what capture actually recorded,
    rather than inferring it from what the terminal printed. Unlike :func:`_engine`
    this one mints a fresh goal id per turn, so it is the one a case driving *two*
    turns has to use.
    """
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    # The seam claims through the **same** trail the runner records rulings into
    # (ADR-0192 §9's wiring clause); a second one would refuse every claim.
    invoker = FakeToolInvoker([], ledger=trail, gate=trail)
    memory = FakeMemoryStore(now=lambda: AT)
    writer = FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=lambda: AT)
    deferrals = FakeDeferralStore(now=lambda: AT)
    writes = MemoryWriteStage(writer=writer, deferrals=deferrals)
    goals = iter(f"g-{n}" for n in range(1, 20))
    loop = LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=writes,
        planner=_NoStepPlanner(),
        feedback=FakeFeedbackProcessor(),
        now=lambda: AT,
        id_factory=lambda: next(goals),
        # The same object the runner below resolves against (ADR-0211 §3): a
        # loop told one vocabulary while selection resolved against another
        # could plan a step the selecting registry never advertised.
        registry=invoker,
    )
    runner = StepRunner(
        plans=plans,
        registry=invoker,
        policy=FakeActionPolicy(),
        trail=trail,
        executor=StepExecutor(plans=plans, registry=invoker, invoker=invoker, now=lambda: AT),
        now=lambda: AT,
        id_factory=lambda: "d-1",
    )
    conversations = FakeConversationStore(now=lambda: AT)
    engine = Engine(
        composing=composing if composing is not None else _composing(),
        grant_operations=_grant_operations(),
        connection_operations=_connection_operations(),
        loop=loop,
        runner=runner,
        plans=plans,
        trail=trail,
        spend=trail,
        # ADR-0186 §10's read trail, on the sibling builder's terms above.
        reads=FakeSourceReadTrail(),
        memory=memory,
        deferrals=deferrals,
        # The narrow deletion seam and its horizon (ADR-0119 §7, §10). Required on
        # the façade, and nothing in this module sweeps: an adapter test is about
        # what the CLI renders, not about the maintenance operation.
        traces=FakeTraceRetention(),
        trace_sink=FakeTraceSink(),
        trace_retention=timedelta(days=365),
        conversations=ConversationLifecycle(
            conversations=conversations,
            memory=memory,
            retention=timedelta(days=30),
            now=lambda: AT,
            archive=FakeTranscriptArchiveWriter(),
            archive_enabled=True,
        ),
        observation=_observation(conversations, memory, writes),
        questions=QuestionStage(writer=writer, deferrals=deferrals, memory=memory, now=lambda: AT),
        archive=FakeTranscriptArchive(),
    )
    return engine, conversations


class _NoStepPlanner:
    """A planner that ends a turn at an empty plan, so no tool is needed."""

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
    ) -> ActionPlan:
        return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(), created_at=AT)


async def test_ask_names_the_conversation_it_ran_under(output: StringIO) -> None:
    """§2: the id is what a stateless client keeps, so the surface has to print it."""
    engine, conversations = _conversation_engine()

    code = await cli._drive_turn(
        engine,
        "hello",
        timeout=timedelta(seconds=5),
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )

    assert code == 0
    listed = await conversations.recent()
    assert len(listed) == 1
    rendered = output.getvalue()
    assert "Conversation:" in rendered
    assert listed[0].id in rendered
    assert "--conversation" in rendered, "the surface says how to continue it"


async def test_ask_continues_the_conversation_it_is_given(output: StringIO) -> None:
    """§10: continuation is an option on ``ask``, never a second meaning for ``resume``."""
    engine, conversations = _conversation_engine()
    await cli._drive_turn(
        engine,
        "hello",
        timeout=timedelta(seconds=5),
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )
    existing = (await conversations.recent())[0].id

    code = await cli._drive_turn(
        engine,
        "again",
        timeout=timedelta(seconds=5),
        approver=lambda _c: True,
        conversation_id=existing,
        confirm_operation=_no_routed_card,
    )

    assert code == 0
    assert len(await conversations.recent()) == 1, "no second conversation was started"
    assert [turn.ordinal for turn in await conversations.turns(existing)] == [1, 2]
    assert existing in output.getvalue()


async def test_ask_reports_an_unknown_conversation_rather_than_starting_one(
    output: StringIO,
) -> None:
    """§1: a typo must not quietly land the continuation somewhere unfindable."""
    engine, conversations = _conversation_engine()

    code = await cli._drive_turn(
        engine,
        "hello",
        timeout=timedelta(seconds=5),
        approver=lambda _c: True,
        conversation_id="nobody",
        confirm_operation=_no_routed_card,
    )

    assert code == cli._EXIT_ERROR
    assert "Error" in output.getvalue()
    assert await conversations.recent() == []


# --- the composed answer, beside the account and never in place of it --------
# ADR-0170 §6's rendering floor and §8's neutralisation, plus §10's
# contradictory-provider test, which needs both the outcome and the rendered
# account and so lives here rather than in ``tests/orchestration``.


def _answering(reply: str, *deltas: str) -> ComposingStage:
    """A composing stage that answers ``reply`` however the turn is driven.

    Both seams are scripted to the same answer, because ``assistant ask`` drives the
    streaming one (ADR-0173 §4) and ``resume`` drives the other, and a test asserting
    on the prose must not depend on which. ``deltas`` says where the stream breaks;
    omitted, it yields the whole answer as one chunk.
    """
    return ComposingStage(
        model=FakeModelProvider(reply),
        streaming=FakeStreamingCompleter.yielding(*(deltas or (reply,))),
    )


async def test_ask_prints_the_composed_answer(output: StringIO) -> None:
    """Milestone 17's exit shape, as a user sees it: the assistant answers."""
    engine = _engine(tools=(tool(),), composing=_answering("You prefer hiking."))

    code = await cli._drive_turn(
        engine,
        "what do you know about me?",
        timeout=PATIENT,
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )

    assert code == 0
    assert "You prefer hiking." in output.getvalue()
    await engine.aclose()


async def test_the_answer_is_rendered_in_addition_to_the_step_account(
    output: StringIO,
) -> None:
    """§6: "in addition to the step account it renders today, never instead of it".

    ADR-0084 §8's rule binds unchanged, and #531's exit code with it: the plan
    listing, the disposition line and the process exit code are all still produced.
    """
    engine = _engine(tools=(tool(),), composing=_answering("You prefer hiking."))

    code = await cli._drive_turn(
        engine,
        "send it",
        timeout=PATIENT,
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )

    rendered = output.getvalue()
    assert "You prefer hiking." in rendered
    assert "Done" in rendered  # the disposition line survived the answer
    assert "Plan:" in rendered  # and so did the plan listing
    assert code == 0
    await engine.aclose()


async def test_the_step_account_is_unchanged_by_a_reply_that_contradicts_it(
    output: StringIO,
) -> None:
    """§6 and §10: the deterministic account is the assertion, and the reply is not.

    A cooperating fake cannot distinguish a design whose guarantee is *structural*
    from one whose guarantee is a hope about the prompt, so this one deliberately
    contradicts the record. It claims an action the step account records as
    ``NO_CAPABLE_TOOL`` and again as ``DENIED``; what is asserted is that the
    outcome's disposition and the rendered account are unchanged by what it says.
    Nothing about the design *stops* a model saying it — §5 is explicit that no
    clause of ADR-0170 is a guarantee about model output — and what §6 buys is that
    the truth is on screen next to the prose whatever the prose says.
    """
    lie = "I sent the email. It has been delivered."
    for policy, expected in (
        (None, "No tool is available"),
        (FakeActionPolicy(deny_at=RiskLevel.LOW), "Declined"),
    ):
        engine = _engine(
            tools=() if policy is None else (tool(),),
            policy=policy,
            composing=_answering(lie),
        )
        outcome = await engine.converse("send it", timeout=PATIENT)

        assert outcome.reply == lie
        assert outcome.step is not None
        assert outcome.step.disposition is (
            Disposition.NO_CAPABLE_TOOL if policy is None else Disposition.DENIED
        )

        output.truncate(0)
        output.seek(0)
        cli._render_turn(outcome)
        rendered = output.getvalue()
        assert lie in rendered  # the prose is shown...
        assert expected in rendered  # ...and contradicted on the same screen
        await engine.aclose()


async def test_a_degraded_composition_is_stated_and_the_account_still_rendered(
    output: StringIO,
) -> None:
    """§6: "never as a silent turn, and never as a failure of the step".

    A turn that acted and then could not describe it still tells the user what was
    done, in the same words it would have used before ADR-0170 existed; the only
    thing missing is the prose that was going to sit above them.

    This is ADR-0173 §6's *second* shape driven over the streaming entry: the attempt
    fails having published nothing, so nothing was committed and the outcome carries
    ``reply`` ``None`` beside the flag, exactly as ``converse`` would have.
    """

    def refuse(_messages: Sequence[Message]) -> str:
        msg = "the route is exhausted"
        raise ModelUnavailableError(msg)

    engine = _engine(
        tools=(tool(),),
        composing=ComposingStage(
            model=FakeModelProvider(refuse),
            streaming=FakeStreamingCompleter(script=(StreamAttempt(fails=True),)),
        ),
    )

    code = await cli._drive_turn(
        engine,
        "send it",
        timeout=PATIENT,
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )

    rendered = output.getvalue()
    assert "no answer could be composed" in rendered
    assert "Done" in rendered  # the account it carries, rendered as it always was
    assert code == 0  # and not reported as a failure of the step
    await engine.aclose()


async def test_a_composed_answer_is_neutralised_for_the_terminal(output: StringIO) -> None:
    """§8: engine-supplied text goes through ``_safe``, as a policy's reason does.

    A reply is model output rendered in the assistant's own voice, so Rich markup
    inside it is a control sequence this terminal would otherwise interpret
    (ADR-0042 §4). Driven through a real turn rather than a hand-built outcome,
    because ADR-0170 §4 makes an answer on a turn-less outcome unconstructible —
    which is the invariant working, not an obstacle to route around.
    """
    hostile = "[bold red]not markup[/] \x1b[31m"
    engine = _engine(tools=(tool(),), composing=_answering(hostile))
    outcome = await engine.converse("send it", timeout=PATIENT)
    output.truncate(0)
    output.seek(0)

    cli._render_reply(outcome)

    rendered = output.getvalue()
    assert outcome.reply == hostile  # the engine carries it verbatim...
    assert "not markup" in rendered  # ...and the adapter escapes it on render
    assert "\x1b[31m" not in rendered
    await engine.aclose()


async def test_a_multi_paragraph_answer_keeps_the_breaks_it_was_written_with(
    output: StringIO,
) -> None:
    """The defect QA run #1334 found on every multi-paragraph answer (#1336).

    ``_safe`` replaces every non-printable character but ``\\t`` and space, and
    ``"\\n".isprintable()`` is ``False`` — so a reply's paragraph breaks reached the
    screen as ``deep work.��One caveat``. Asserted as the *absence* of the
    replacement character together with the presence of a blank line, because either
    half alone passes on the wrong rendering: a run that ate the breaks silently
    would have no ``�`` either.
    """
    answer = "Blocked for deep work.\n\nOne caveat worth being straight about."
    engine = _engine(tools=(tool(),), composing=_answering(answer))
    outcome = await engine.converse("send it", timeout=PATIENT)
    output.truncate(0)
    output.seek(0)

    cli._render_reply(outcome)

    rendered = output.getvalue()
    assert "�" not in rendered, "the breaks are content, not characters to neutralise"
    assert "Blocked for deep work.\n\nOne caveat" in rendered
    await engine.aclose()


@pytest.mark.parametrize("ending", ["\r\n", "\r", "\n"], ids=["crlf", "cr", "lf"])
async def test_a_reply_written_with_any_line_ending_renders_as_one_break(
    output: StringIO, ending: str
) -> None:
    """A ``\\r`` must neither reach the terminal nor cost the break it was part of.

    A carriage return is a character a terminal acts on — it returns the cursor to
    column 0, so what follows overwrites what preceded — which is ADR-0042 §4's
    threat and the reason ``_safe`` replaces it. But a model emitting CRLF is not
    attacking anything, and replacing the ``\\r`` alone leaves ``�`` sitting at every
    break: #1336 half-fixed. All three endings therefore render the same way.
    """
    engine = _engine(tools=(tool(),), composing=_answering(f"First.{ending}Second."))
    outcome = await engine.converse("send it", timeout=PATIENT)
    output.truncate(0)
    output.seek(0)

    cli._render_reply(outcome)

    rendered = output.getvalue()
    assert "\r" not in rendered, "the character a terminal would act on never reaches it"
    assert "�" not in rendered
    assert "First.\nSecond." in rendered
    await engine.aclose()


async def test_the_newline_carve_out_neutralises_every_other_control_character(
    output: StringIO,
) -> None:
    """Only the break is spared; §4's obligation is otherwise discharged whole.

    The pairing is the point: an answer carrying both a legitimate paragraph break
    and an ANSI escape must keep the first and lose the second, so neither a helper
    that neutralised nothing nor the old one that neutralised everything passes.
    """
    engine = _engine(tools=(tool(),), composing=_answering("First.\n\x1b[2JSecond.\x07"))
    outcome = await engine.converse("send it", timeout=PATIENT)
    output.truncate(0)
    output.seek(0)

    cli._render_reply(outcome)

    rendered = output.getvalue()
    assert "\x1b" not in rendered
    assert "\x07" not in rendered
    assert rendered.count("�") == 2, "the escape and the bell, and nothing else"
    assert "First.\n" in rendered
    await engine.aclose()


async def test_rich_markup_split_across_a_break_is_shown_and_not_consumed(
    output: StringIO,
) -> None:
    """Escaping the whole value, rather than line by line, is load-bearing.

    Rich's tag pattern matches across a newline, so ``[red\\nbold]`` is markup to the
    renderer while each of its halves alone is not. A multi-line helper built by
    neutralising each line and joining with ``\\n`` would therefore hand Rich a tag
    it consumes — the reply reaching the screen *emptied* of what it said, which is
    a worse failure than the ``�`` this fix is for and one that looks like nothing
    went wrong.
    """
    engine = _engine(tools=(tool(),), composing=_answering("[red\nbold]still here"))
    outcome = await engine.converse("send it", timeout=PATIENT)
    output.truncate(0)
    output.seek(0)

    cli._render_reply(outcome)

    rendered = output.getvalue()
    assert "still here" in rendered
    assert "[red" in rendered, "shown as text, not consumed as a style"
    assert "bold]" in rendered
    await engine.aclose()


def test_a_value_sharing_a_line_with_the_adapters_own_text_still_loses_its_newline() -> None:
    """The default stays as it was, because eating the break is what it is for (#1336).

    Every surface but the reply interpolates a value into a line this adapter wrote,
    where a newline lets the value forge a second line indistinguishable from the
    CLI's own — ``_safe``'s reason for replacing it, and untouched by the reply's
    carve-out. Pinned against ``_safe`` directly rather than one calling surface,
    since it is the shared default that the carve-out could regress.
    """
    forged = "harmless\n  [dim]Why:[/] fabricated"

    assert cli._safe(forged) == "harmless�  \\[dim]Why:\\[/] fabricated"
    assert "\n" not in cli._safe(forged)


# --- the streamed answer (ADR-0173 §10) --------------------------------------
# §14 assigns §10 to this lane: chunks neutralised over the accumulation, the
# terminal frame's account rendered whether or not chunks were, and §6's fourth
# shape rendered as an incomplete answer rather than a silent one.


#: A split that satisfies §14's "chosen so that neither chunk alone would be
#: neutralised": Rich escapes only a *complete* tag, so each half passes
#: ``_safe_prose`` untouched and the join is live markup.
SPLIT_TAG = ("Answer: [/dim", "] and the rest.")


def _rendered_whole(text: str) -> str:
    """What one write of the whole neutralised answer puts on a console."""
    buffer = StringIO()
    Console(file=buffer, force_terminal=False, width=100).print(
        cli._safe_prose(text), end="", soft_wrap=True, highlight=False
    )
    return buffer.getvalue()


class _ScriptedStream(FakeAssistantEngine):
    """An engine whose stream is scripted frame by frame, splits included.

    ``FakeAssistantEngine`` derives its chunks from the outcome's own reply and cuts
    them at word boundaries, which is what keeps it honest for every other consumer
    — and is exactly what a test of §10's boundary clause cannot use, because the
    boundary has to fall inside a markup token. This subclass scripts the frames
    instead, so a disagreement §3 forbids and a split §10 forbids evading are both
    reachable from a test.
    """

    def __init__(
        self,
        *chunks: str,
        outcome: TurnOutcome | None = None,
        terminal: bool = True,
        stall: asyncio.Event | None = None,
    ) -> None:
        """Script one stream.

        Args:
            chunks: The chunk texts to yield, in order.
            outcome: The terminal outcome, or ``None`` to derive one whose ``reply``
                is the join of ``chunks`` — the agreement §3 describes.
            terminal: Whether to yield the outcome at all. ``False`` is the shape
                §4 says cannot happen, which the adapter still has to survive.
            stall: Waited on after the first chunk, so a reader can be interrupted
                mid-answer.
        """
        super().__init__()
        self._chunks = chunks
        self._outcome = outcome
        self._terminal = terminal
        self._stall = stall
        self.stalled = asyncio.Event()
        self.closed = False
        self.timeouts: list[timedelta] = []

    def converse_streaming(
        self,
        utterance: str,
        *,
        timeout: timedelta,
        conversation_id: str | None = None,
    ) -> AsyncIterator[ReplyChunk | TurnOutcome]:
        """Yield the scripted frames, recording that the iterator was closed."""
        self.timeouts.append(timeout)
        self.calls.append(
            ("converse_streaming", {"utterance": utterance, "conversation_id": conversation_id})
        )
        return self._scripted(utterance, conversation_id)

    async def _scripted(
        self, utterance: str, conversation_id: str | None
    ) -> AsyncIterator[ReplyChunk | TurnOutcome]:
        """The frames themselves, closing over ``self`` so the exit is observable."""
        try:
            for index, text in enumerate(self._chunks):
                yield ReplyChunk(text=text)
                if index == 0 and self._stall is not None:
                    self.stalled.set()
                    await self._stall.wait()
            if self._terminal:
                yield self._outcome or _outcome_replying("".join(self._chunks), conversation_id)
        finally:
            self.closed = True


def _outcome_replying(
    reply: str | None, conversation_id: str | None = None, *, degraded: bool = False
) -> TurnOutcome:
    """A turn-carrying outcome with ``reply``, which is the only shape that admits one."""
    return TurnOutcome(
        turn=TurnResult(
            goal=Goal(
                id="g-1",
                statement="say something",
                provenance=Provenance(
                    source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
                ),
                created_at=AT,
            ),
            context=CurrentContext(
                now=AT,
                time_of_day=TimeOfDay.AFTERNOON,
                is_weekend=False,
                within_working_hours=True,
            ),
            memories=(),
            plan=ActionPlan(
                id="g-1-plan",
                goal_id="g-1",
                steps=(),
                created_at=AT,
                rationale="nothing to do",
            ),
        ),
        conversation_id=conversation_id,
        reply=reply,
        reply_degraded=degraded,
    )


def test_the_split_this_lane_pins_is_one_neither_half_would_be_neutralised_at() -> None:
    """§14 makes the *choice* of split part of the obligation, so it is asserted.

    Without this the boundary test rots into a tautology the moment someone picks a
    tidier split: a tag that is escaped in either half proves nothing about the join.
    Rich escapes a complete tag and only a complete tag, which is what makes
    ``[/dim`` plus ``]`` the adversarial shape rather than merely an awkward one.
    """
    first, second = SPLIT_TAG

    assert cli._safe_prose(first) == first, "neither chunk alone is neutralised..."
    assert cli._safe_prose(second) == second
    assert cli._safe_prose(first + second) == "Answer: \\[/dim] and the rest."  # ...but the join is


async def test_a_markup_token_split_across_a_chunk_boundary_carries_no_live_markup(
    output: StringIO,
) -> None:
    """§10's boundary clause, pinned as §14 words it.

    The chunks arrive already split at the token, so an adapter neutralising each as
    it comes writes ``[/dim`` and ``]`` — nothing either call would refuse — and puts
    live markup on the screen. Neutralising the *accumulation* writes ``\\[/dim]``,
    which Rich renders as text.

    The assertion is made twice over, because either half alone is satisfied by the
    wrong implementation: the tag is present **as text** (a consumed tag would leave
    the buffer without it), and the whole stream renders byte-identically to one
    write of the whole neutralised answer — which a per-chunk implementation cannot
    do, since ``_safe_prose(a) + _safe_prose(b)`` is not ``_safe_prose(a + b)`` here.
    """
    engine = _ScriptedStream(*SPLIT_TAG)

    code = await cli._drive_turn(
        engine,
        "say it",
        timeout=PATIENT,
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )

    rendered = output.getvalue()
    assert code == 0
    assert "Answer: [/dim] and the rest." in rendered, "shown as text, not consumed as a style"
    assert rendered.startswith(_rendered_whole("".join(SPLIT_TAG)))


@pytest.mark.parametrize(
    "text",
    [
        "Answer: [/dim] and on.",
        "A backslash \\[dim] and on.",
        "Two lines\r\nand a second.",
        "An escape \x1b[2J and a bell \x07.",
        "[red\nbold]still here",
    ],
    ids=["tag", "backslash", "crlf", "control", "tag-across-a-break"],
)
async def test_every_split_of_an_answer_renders_it_the_way_one_write_would(
    output: StringIO, text: str
) -> None:
    """The property under §10's clause, asserted over *every* boundary in the text.

    §10 does not say "escape carefully near brackets", it says neutralisation is
    applied to what the adapter accumulated — and the observable form of that is
    that where the producer chose to cut cannot change a single byte of what is
    rendered. Driven over each split in turn, so a hold-back rule that happens to
    work for the one boundary a hand-written case picked does not pass.
    """
    expected = _rendered_whole(text)
    for cut in range(1, len(text)):
        chunks = [part for part in (text[:cut], text[cut:]) if part.strip()]
        engine = _ScriptedStream(*chunks, outcome=_outcome_replying(text))
        output.truncate(0)
        output.seek(0)

        await cli._drive_turn(
            engine,
            "say it",
            timeout=PATIENT,
            approver=lambda _c: True,
            confirm_operation=_no_routed_card,
        )

        assert output.getvalue().startswith(expected), f"split at {cut}"


def test_the_settled_prefix_is_one_no_later_text_can_revise() -> None:
    """What ``_StreamedReply`` writes early it must never need back (ADR-0173 §10).

    Two properties, brute-forced over an alphabet of exactly the characters that
    make neutralisation depend on what follows. Together they are what licenses
    writing before the answer is complete: the neutralisation of a settled prefix is
    a prefix of the neutralisation of the whole, and the settled prefix only grows —
    so the delta between two of them is always text that has not been shown and will
    never be contradicted.
    """
    alphabet = ("[", "]", "\\", "/", "d", "\r", "\n", "1", "@", "A", "#")
    for length in range(1, 5):
        for combination in product(alphabet, repeat=length):
            whole = "".join(combination)
            grown = ""
            for cut in range(len(whole) + 1):
                settled = cli._settled_prefix(whole[:cut])
                assert cli._safe_prose(whole).startswith(cli._safe_prose(settled)), whole
                assert settled.startswith(grown), whole
                grown = settled


async def test_a_bracket_that_can_never_be_markup_does_not_stall_the_stream(
    output: StringIO,
) -> None:
    """Holding back is a cost, so it is paid only where the escaping could still move.

    Rich's escaper and its parser share one character class, so ``[1`` and
    ``[Options`` are text under both however the answer continues — and an adapter
    that held every unclosed ``[`` would stop rendering an ordinary answer at the
    first bracket and resume only at the terminal frame, which is the streaming this
    path exists to do. Asserted against ``_StreamedReply`` rather than a whole turn
    because what is at issue is what is on screen *before* the answer ends.
    """
    running = cli._StreamedReply()

    running.take(ReplyChunk(text="Options [1 and then"))
    running.take(ReplyChunk(text=" a good deal more prose"))

    assert "a good deal more prose" in output.getvalue()


def test_a_bracket_that_could_still_open_a_tag_is_held_until_it_settles(
    output: StringIO,
) -> None:
    """The other side of the same rule, which the case above would pass without.

    A relaxation that stopped holding brackets altogether renders progressively too,
    and evades §10 exactly as the per-chunk implementation does. So the tag-shaped
    bracket must still be off the screen while it is unclosed, and reach it escaped
    once the ``]`` arrives.
    """
    running = cli._StreamedReply()

    running.take(ReplyChunk(text="Options [dim and then"))
    assert "[dim" not in output.getvalue(), "it could still become a tag"

    running.take(ReplyChunk(text=" more]"))
    assert "Options [dim and then more]" in output.getvalue()


async def test_the_step_account_is_rendered_whether_or_not_chunks_were(
    output: StringIO,
) -> None:
    """§10's third clause, on a real turn: the account survives the stream.

    ADR-0170 §6's floor is unchanged by streaming, so the plan listing, the
    disposition line and #531's exit code are all still produced beside an answer
    that arrived in pieces.
    """
    engine = _engine(tools=(tool(),), composing=_answering("Sent it.", "Sent ", "it."))

    code = await cli._drive_turn(
        engine,
        "send it",
        timeout=PATIENT,
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )

    rendered = output.getvalue()
    assert code == 0
    assert "Sent it." in rendered
    assert "Plan:" in rendered
    assert "Done" in rendered
    await engine.aclose()


async def test_an_answer_that_began_and_did_not_finish_is_shown_and_called_incomplete(
    output: StringIO,
) -> None:
    """ADR-0173 §6's fourth shape, rendered as §10's last clause obliges.

    The stream publishes a chunk and *then* fails, which is past §5's commit
    boundary, so the outcome carries the text actually yielded beside the flag. Three
    things are owed at once and the shape before this lane produced none of them: the
    prose the user has already read is not discarded, the answer is *said* to be
    incomplete, and the step account is rendered as the record of a step that
    succeeded — never as a failure of it.
    """
    engine = _engine(
        tools=(tool(),),
        composing=ComposingStage(
            model=FakeModelProvider("unused"),
            streaming=FakeStreamingCompleter(
                script=(StreamAttempt(deltas=("I sent the note",), fails=True),)
            ),
        ),
    )

    code = await cli._drive_turn(
        engine,
        "send it",
        timeout=PATIENT,
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )

    rendered = output.getvalue()
    assert code == 0, "a composition that stopped is not a failure of the step (§10)"
    assert "I sent the note" in rendered, "prose already read is not taken back (§6)"
    assert "incomplete" in rendered
    assert "no answer could be composed" not in rendered, "that is the shape one along"
    assert "Done" in rendered
    await engine.aclose()


def test_the_fourth_shape_is_rendered_the_same_way_off_a_one_result_call(
    output: StringIO,
) -> None:
    """The shared renderer, not just the streaming path, reads four shapes off two values.

    ``_render_reply`` is what ``resume`` renders through as well, and it previously
    returned on ``reply_degraded`` without looking at ``reply`` — so the fourth shape
    would have printed "no answer could be composed" over an answer that was right
    there. Pinned here against the renderer directly, because that is the seam the
    defect was at.
    """
    cli._render_reply(_outcome_replying("Half an ans", degraded=True))

    rendered = output.getvalue()
    assert "Half an ans" in rendered
    assert "incomplete" in rendered


async def test_the_terminal_reply_is_the_answer_where_the_chunks_disagree(
    output: StringIO,
) -> None:
    """§3: "no implementation treats an accumulated chunk sequence as the record".

    A hub whose chunks and terminal ``reply`` disagree cannot be left with the chunks
    standing as what the assistant said. The prose is already on screen and cannot be
    recalled, so the adapter disowns it in words and prints the authoritative answer
    after it — which is the only move available that does not make the wire's value
    lose to a rendering of it.
    """
    engine = _ScriptedStream("You should ", "resign.", outcome=_outcome_replying("Take a walk."))

    code = await cli._drive_turn(
        engine,
        "advise me",
        timeout=PATIENT,
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )

    rendered = output.getvalue()
    assert code == 0
    assert "Take a walk." in rendered
    assert "did not confirm the text above" in rendered
    assert rendered.index("You should resign.") < rendered.index("Take a walk.")


async def test_ask_streams_the_conversation_it_is_told_to_continue(
    output: StringIO,
) -> None:
    """Milestone 18's exit shape: a streamed answer, resumed mid-conversation, from the CLI.

    ADR-0173 §8 carries resume identically — the same argument, the same
    ``UnknownConversationError``, the same route to the composing stage — so what
    this asserts is that the adapter relays it on the *streaming* entry and that the
    second turn runs under the conversation the first one minted rather than a fresh
    one.
    """
    engine, conversations = _conversation_engine(
        composing=_answering("Still here.", "Still ", "here.")
    )

    first = await cli._drive_turn(
        engine,
        "hello",
        timeout=PATIENT,
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )
    assert "Still here." in output.getvalue(), "the opening turn streamed its answer"
    opened = (await conversations.recent())[0].id
    output.truncate(0)
    output.seek(0)

    second = await cli._drive_turn(
        engine,
        "and again",
        timeout=PATIENT,
        approver=lambda _c: True,
        conversation_id=opened,
        confirm_operation=_no_routed_card,
    )

    rendered = output.getvalue()
    assert (first, second) == (0, 0)
    assert "Still here." in rendered, "the resumed turn streamed its answer too"
    assert opened in rendered, "and ran under the conversation it was given"
    assert len(await conversations.recent()) == 1, "no second conversation was started"
    assert [turn.ordinal for turn in await conversations.turns(opened)] == [1, 2]
    await engine.aclose()


async def test_ask_drives_the_streaming_entry_and_relays_its_budget_unchanged() -> None:
    """§4 takes exactly ``converse``'s arguments, and ``--timeout`` is still the turn's.

    Asserted on the call rather than on the rendering, because a lane that streamed
    the answer while quietly dropping the caller's deadline would look identical on
    screen.
    """
    engine = _ScriptedStream("done")

    await cli._drive_turn(
        engine,
        "say it",
        timeout=PATIENT,
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )

    assert engine.timeouts == [PATIENT]
    assert [call[0] for call in engine.calls] == ["converse_streaming"]


async def test_reading_to_the_terminal_frame_closes_the_iterator(output: StringIO) -> None:
    """§4 makes closing the caller's obligation, and it is what hangs the connection up.

    The adapter stops at the terminal frame rather than reading on, so the iterator
    is left unfinished on purpose — which means the close has to be the adapter's
    doing. Asserted against the generator's own exit rather than against "no error
    was raised", since abandoning it raises nothing either.
    """
    engine = _ScriptedStream("all ", "done")

    await cli._drive_turn(
        engine,
        "say it",
        timeout=PATIENT,
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )

    assert engine.closed


async def test_an_interrupted_stream_still_closes_the_iterator(output: StringIO) -> None:
    """Ctrl-C mid-answer hangs the connection up rather than leaking it.

    A ``KeyboardInterrupt`` under ``asyncio.run`` cancels the task running the turn,
    so what the adapter has to survive is a cancellation arriving between two chunks.
    ADR-0173 §9 is why this is only about the socket: the *turn* is not abandoned —
    the hub runs it to completion and captures it — but the connection is the
    adapter's to give back.
    """
    stall = asyncio.Event()
    engine = _ScriptedStream("half an ", "answer", stall=stall)
    turn = asyncio.create_task(
        cli._drive_turn(
            engine,
            "say it",
            timeout=PATIENT,
            approver=lambda _c: True,
            confirm_operation=_no_routed_card,
        )
    )
    await engine.stalled.wait()

    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn

    assert engine.closed, "the connection is hung up, not left to a generator nobody finished"
    assert "half an " in output.getvalue(), "and what had arrived was already on screen"


async def test_an_interrupted_stream_closes_the_line_it_was_writing(output: StringIO) -> None:
    """The other half of the same Ctrl-C, and the one the owner sees (#1352).

    A streamed answer is written with no line ending, because the parts arrive
    mid-sentence and the next chunk continues the line (ADR-0173 §10). Only
    ``_end_line`` closes it, and a cancellation took neither path that called one:
    ``asyncio.CancelledError`` is a ``BaseException``, so it went past the handler
    that catches an :class:`AssistantError` with the line still open and the owner's
    next shell prompt landed on the end of half a sentence.

    Cosmetic and client-side alone. ADR-0173 §9 rules the turn is not abandoned
    hub-side by any of this, and the cancellation itself still propagates unchanged —
    which the ``raises`` below is asserting as much as the test above it is.
    """
    engine = _ScriptedStream("half an ", "answer", stall=asyncio.Event())
    turn = asyncio.create_task(
        cli._drive_turn(
            engine,
            "say it",
            timeout=PATIENT,
            approver=lambda _c: True,
            confirm_operation=_no_routed_card,
        )
    )
    await engine.stalled.wait()

    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn

    rendered = output.getvalue()
    assert "half an " in rendered
    assert rendered.endswith("\n"), "the line the answer was on is closed, not left open"


async def test_a_stream_that_ends_without_an_outcome_is_reported_not_invented(
    output: StringIO,
) -> None:
    """§4's "always present unless the call raises", met by a producer that broke it.

    Neither implementation of the method can end this way — both read to a terminal
    frame or fail loudly — so what is pinned is that the adapter says so and exits
    non-zero rather than fabricating an outcome or letting a traceback out
    (ADR-0042 §7).
    """
    engine = _ScriptedStream("half an answer", terminal=False)

    code = await cli._drive_turn(
        engine,
        "say it",
        timeout=PATIENT,
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )

    rendered = output.getvalue()
    assert code == 1
    assert "ended without a result" in rendered
    assert "Traceback" not in rendered
    assert rendered.index("half an answer") < rendered.index("ended without a result")


def test_an_outcome_owing_no_answer_renders_nothing_for_it(output: StringIO) -> None:
    """§4's other two ``None`` shapes print no reply line and no degraded notice."""
    cli._render_reply(TurnOutcome(turn=None, step=None))

    assert output.getvalue() == ""


def test_a_degraded_capture_is_reported_beside_the_degraded_memory_note(
    output: StringIO,
) -> None:
    """§9 item 6: the answer is the answer, and the user is told it went unrecorded."""
    cli._render_turn(
        TurnOutcome(turn=None, step=None, conversation_id="c-1", capture_degraded=True)
    )

    rendered = output.getvalue()
    assert "not recorded" in rendered
    assert "history" in rendered


def test_the_conversation_footer_is_silent_when_nothing_resolved(output: StringIO) -> None:
    """A recovered resumption whose park predates capture has no id to offer (§3)."""
    cli._render_conversation_footer(TurnOutcome(turn=None, step=None, conversation_id=None))

    assert output.getvalue() == ""


async def test_the_conversations_listing_shows_what_a_person_chooses_from(
    output: StringIO,
) -> None:
    """§2: the id, when it started, and when it was last active."""
    engine, conversations = _conversation_engine()
    await cli._drive_turn(
        engine,
        "hello",
        timeout=timedelta(seconds=5),
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )
    started = (await conversations.recent())[0]

    code = await cli._drive_conversations(engine, limit=50, offset=0)

    assert code == 0
    rendered = output.getvalue()
    assert started.id in rendered
    assert "Last active" in rendered


async def test_the_conversations_listing_says_so_when_there_are_none(output: StringIO) -> None:
    """An empty listing is an answer, not a blank screen."""
    engine, _ = _conversation_engine()

    assert await cli._drive_conversations(engine, limit=50, offset=0) == 0
    assert "No conversations yet" in output.getvalue()


async def test_the_conversations_listing_never_shows_a_deleted_conversation(
    output: StringIO,
) -> None:
    """§8: not because this surface filters, but because the stamp hides it."""
    engine, conversations = _conversation_engine()
    await cli._drive_turn(
        engine,
        "hello",
        timeout=timedelta(seconds=5),
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )
    stamped = (await conversations.recent())[0].id
    assert await conversations.stamp_deleted(stamped) is True
    output.truncate(0)
    output.seek(0)

    await cli._drive_conversations(engine, limit=50, offset=0)

    assert stamped not in output.getvalue()
    assert "No conversations yet" in output.getvalue()


async def test_forget_conversation_shows_the_count_and_span_before_destroying(
    output: StringIO,
) -> None:
    """§8: the ceremony is the count and span, not every turn — what a person can judge."""
    engine, conversations = _conversation_engine()
    await cli._drive_turn(
        engine,
        "hello",
        timeout=timedelta(seconds=5),
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )
    existing = (await conversations.recent())[0].id
    await cli._drive_turn(
        engine,
        "again",
        timeout=timedelta(seconds=5),
        approver=lambda _c: True,
        conversation_id=existing,
        confirm_operation=_no_routed_card,
    )
    output.truncate(0)
    output.seek(0)

    code = await cli._drive_forget_conversation(engine, existing, confirm=lambda _digest: True)

    assert code == 0
    rendered = output.getvalue()
    assert "About to forget this conversation" in rendered
    assert "Turns recorded:" in rendered
    assert "2" in rendered
    assert "Forgotten." in rendered
    assert await conversations.get(existing) is None


async def test_forget_conversation_leaves_it_alone_when_the_answer_is_no(
    output: StringIO,
) -> None:
    """A refusal is a valid outcome, and it exits 0 — nothing went wrong."""
    engine, conversations = _conversation_engine()
    await cli._drive_turn(
        engine,
        "hello",
        timeout=timedelta(seconds=5),
        approver=lambda _c: True,
        confirm_operation=_no_routed_card,
    )
    existing = (await conversations.recent())[0].id

    code = await cli._drive_forget_conversation(engine, existing, confirm=lambda _digest: False)

    assert code == 0
    assert "Left alone" in output.getvalue()
    assert await conversations.get(existing) is not None


async def test_forget_conversation_declines_an_id_it_cannot_show(output: StringIO) -> None:
    """Unknown, deleted, or reclaimed all look the same here, on purpose.

    A surface that distinguished them would report on conversations it is meant to
    have forgotten.
    """
    engine, _ = _conversation_engine()

    code = await cli._drive_forget_conversation(engine, "nobody", confirm=lambda _digest: True)

    assert code == cli._EXIT_ERROR
    assert "No conversation has the id" in output.getvalue()


# --- observe: the accumulation surface (ADR-0077 §8, §9.8) ---------------


#: The citations behind the default scripted proposal, resolved.
_TWO_EPISODES = _cited("they asked for metric", "they asked for metric again")


def _proposal(
    *,
    decision: LearnDecision | None = LearnDecision.STORED,
    record_id: str | None = "rec-9",
    content: str = "the user prefers metric units",
    reason: str = "fake: configured decision",
    evidence: tuple[Evidence, ...] = _TWO_EPISODES,
) -> ObservedProposal:
    """One entry of an observation report, as the stage builds it.

    ``evidence`` defaults to two resolved citations, because a proposal citing
    nothing is not a shape a conforming observer can produce (ADR-0077 §5's floor is
    a minimum of one, two for an ``INFERRED`` belief).
    """
    return ObservedProposal(
        content=content,
        kind=MemoryKind.SEMANTIC,
        step=MemorySource.OBSERVED,
        confidence=0.6,
        rationale="they said so twice",
        decision=decision,
        record_id=record_id,
        reason=reason,
        evidence=evidence,
    )


class _RecordingObserveEngine:
    """A stand-in façade recording the observation calls the command makes."""

    def __init__(self, report: ObservationReport) -> None:
        self._report = report
        self.observed: list[str | None] = []

    async def observe(self, conversation_id: str | None = None) -> ObservationReport:
        self.observed.append(conversation_id)
        return self._report

    async def start(self) -> None:
        """The start-up sweeps, which this stand-in has no stores to sweep."""

    async def aclose(self) -> None:
        """Nothing to release: this stand-in owns no resource."""


class _FailingObserveEngine(_RecordingObserveEngine):
    """A façade whose observation fails, so the boundary is exercised."""

    def __init__(self) -> None:
        super().__init__(ObservationReport())

    async def observe(self, conversation_id: str | None = None) -> ObservationReport:
        self.observed.append(conversation_id)
        msg = "memory is unavailable"
        raise MemoryStoreError(msg)


def _observed_report(**overrides: object) -> ObservationReport:
    """A report over one conversation, with one stored belief unless overridden."""
    fields: dict[str, object] = {
        "proposals": (_proposal(),),
        "route": OBSERVER_ROUTE,
        "conversation_id": "conv-1",
        "episodes_read": 3,
    }
    fields.update(overrides)
    return ObservationReport(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def test_observe_names_what_was_read_and_which_model_read_it(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0013 §6's owed reporting, on the call where it matters most (ADR-0077 §3).

    The user chooses when their transcript is read, and the surface tells them which
    provider read it — a stronger form of consent than a setting.
    """
    engine = _RecordingObserveEngine(_observed_report())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["observe"])

    assert result.exit_code == 0
    rendered = " ".join(output.getvalue().split())
    assert "3 episode(s)" in rendered
    assert "conv-1" in rendered
    assert OBSERVER_ROUTE in rendered
    assert engine.observed == [None], "no id means the engine's own selector"


def test_observe_relays_the_conversation_it_was_given(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The id is relayed untouched: whether it names a conversation is the engine's."""
    engine = _RecordingObserveEngine(_observed_report(conversation_id="conv-2"))
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["observe", "conv-2"])

    assert result.exit_code == 0
    assert engine.observed == ["conv-2"]


def test_observe_shows_each_belief_with_its_step_evidence_and_ruling(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Everything the surface owes: what was proposed, on what, and what became of it.

    The **epistemic step** leads rather than the band, because every observed
    proposal is derived and ``observed`` versus ``inferred`` is the informative half
    (ADR-0072 §3). The id is shown so the belief is immediately inspectable with
    ``assistant beliefs`` and destroyable with ``assistant forget``.
    """
    _wire(monkeypatch, _RecordingObserveEngine(_observed_report()))

    result = CliRunner().invoke(cli.app, ["observe"])

    assert result.exit_code == 0
    rendered = " ".join(output.getvalue().split())
    assert "observed" in rendered
    assert "semantic" in rendered
    assert "0.60" in rendered
    assert "2 episode(s)" in rendered
    assert "the user prefers metric units" in rendered
    assert "they said so twice" in rendered
    assert "Stored a new memory." in rendered
    assert "rec-9" in rendered
    assert "assistant beliefs" in rendered


def test_observe_renders_a_deferral_in_full_and_claims_nothing_about_the_queue(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Inverted by ADR-0078**, and inverted to *silence* rather than a new promise.

    It used to say the proposal was "gone when this command ends", which was true —
    nothing recorded one (ADR-0077 §4, #423). The write stage now parks it, so that
    sentence became a lie and had to go (ADR-0019).

    **Nothing replaces it**, because there is nothing further this adapter can
    honestly say. An observer's refusals stay at the observing stage "and no further"
    (ADR-0078 §7), so ``ObservationReport`` deliberately does not carry the admission,
    and every candidate replacement is a claim about state it does not hold: "go
    answer it" is false when the queue refused it, and "the queue was full" is false
    when the question was parked on a later page, answered, or lapsed. The ruling line
    says the one thing true on every branch — nothing was stored, an answer is owed.

    The candidate, its evidence and the policy's reason are still rendered in full,
    for ADR-0077 §4's reason and one ADR-0078 does not remove: resolving
    ``Provenance.evidence`` into readable text is #431's open half, so this is still
    the only place a deferred proposal's *warrant* is shown.
    """
    report = _observed_report(
        proposals=(
            _proposal(
                decision=LearnDecision.DEFERRED,
                record_id=None,
                content="the user works from Lisbon",
                reason="fake: an inference never silently overrides an assertion",
            ),
        )
    )
    _wire(monkeypatch, _RecordingObserveEngine(report))

    result = CliRunner().invoke(cli.app, ["observe"])

    assert result.exit_code == 0
    # Flattened: Rich wraps at the console width, so a long reason spans lines.
    rendered = " ".join(output.getvalue().split())
    assert "the user works from Lisbon" in rendered  # the candidate, not just a ruling
    assert "an inference never silently overrides an assertion" in rendered
    assert "Not stored — it needs your answer" in rendered
    assert "gone when this command ends" not in rendered, "that claim is false since ADR-0078"
    # Every claim about *what became of the question* is absent, because the report
    # does not carry it and each one is false on some branch.
    assert "assistant questions" not in rendered, "it may not be on that list"
    assert "queue was full" not in rendered, "and it may not have been"
    assert "go answer" not in rendered


def test_observe_reports_a_proposal_the_write_path_refused_for_lost_evidence(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A drop is reported, never omitted (ADR-0077 §5).

    No ruling was sought, so no ruling is claimed: the line says the belief was not
    stored and why, rather than showing a decision nobody made.
    """
    report = _observed_report(
        proposals=(
            _proposal(
                decision=None,
                record_id=None,
                # The stage's own words for a drop: no ruling was sought, so there is
                # no policy reason to relay (ADR-0077 §5).
                reason=(
                    "the evidence it cited went away between selection and the write, "
                    "so nothing was stored"
                ),
            ),
        ),
        dropped_unsupported=1,
    )
    _wire(monkeypatch, _RecordingObserveEngine(report))

    result = CliRunner().invoke(cli.app, ["observe"])

    assert result.exit_code == 0
    rendered = " ".join(output.getvalue().split())
    assert "Not stored" in rendered
    assert "the evidence it cited went away" in rendered


def test_observe_reports_what_was_thrown_away(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silence must not read as "there was nothing to learn" (ADR-0022 §3, ADR-0077 §4).

    The three counts stay apart because they answer different questions: what the
    producer could not use, what it dropped to stay inside its bound, and what the
    write path refused for evidence that had gone.
    """
    report = _observed_report(discarded_unusable=2, discarded_over_limit=1, dropped_unsupported=3)
    _wire(monkeypatch, _RecordingObserveEngine(report))

    result = CliRunner().invoke(cli.app, ["observe"])

    assert result.exit_code == 0
    rendered = " ".join(output.getvalue().split())
    assert "Discarded 6" in rendered
    assert "2 unusable" in rendered
    assert "1 over the per-pass limit" in rendered
    assert "3 whose evidence went away" in rendered


def test_observe_says_so_when_the_batch_justified_no_belief(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pass that proposed nothing is a normal outcome, reported as one (ADR-0022 §4)."""
    _wire(monkeypatch, _RecordingObserveEngine(_observed_report(proposals=())))

    result = CliRunner().invoke(cli.app, ["observe"])

    assert result.exit_code == 0
    assert "Nothing in them was worth believing" in output.getvalue()


def test_observe_does_not_claim_a_route_when_no_model_was_asked(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A window whose episodes have all gone reaches no provider (ADR-0077 §9.7).

    Printing a route here would claim a read that never happened — the one thing §3's
    reporting exists to make truthful.
    """
    report = ObservationReport(conversation_id="conv-1", route=None)
    _wire(monkeypatch, _RecordingObserveEngine(report))

    result = CliRunner().invoke(cli.app, ["observe"])

    assert result.exit_code == 0
    rendered = " ".join(output.getvalue().split())
    assert OBSERVER_ROUTE not in rendered
    assert "Nothing to observe" in rendered
    assert "no model was asked" in rendered


def test_observe_with_nothing_to_observe_at_all_says_so(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty store points the user at the command that fills it."""
    _wire(monkeypatch, _RecordingObserveEngine(ObservationReport()))

    result = CliRunner().invoke(cli.app, ["observe"])

    assert result.exit_code == 0
    assert "No conversation to observe" in output.getvalue()


def test_observe_renders_a_failure_rather_than_a_traceback(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One error boundary spans every stage, mapping to a non-zero code (ADR-0042 §7)."""
    _wire(monkeypatch, _FailingObserveEngine())

    result = CliRunner().invoke(cli.app, ["observe"])

    assert result.exit_code == cli._EXIT_ERROR
    assert "Error" in output.getvalue()
    assert "memory is unavailable" in output.getvalue()


async def test_an_observed_belief_is_immediately_inspectable(output: StringIO) -> None:
    """End to end over a real engine: observe, then read it back (ADR-0077 §9.8).

    The claim the surface makes — "see them with ``assistant beliefs``" — asserted
    rather than promised, over the same store the observation wrote to. The
    provenance a reader gets is the derived band, so ``beliefs`` shows the belief
    with the standing it was formed at.
    """
    engine, conversations = _conversation_engine()
    try:
        await cli._drive_turn(
            engine,
            "hello",
            timeout=timedelta(seconds=5),
            approver=lambda _c: True,
            confirm_operation=_no_routed_card,
        )
        conversation = (await conversations.recent())[0].id

        assert await cli._drive_observe(engine, conversation) == 0
        assert "1 belief(s) proposed" in output.getvalue()

        assert await cli._drive_beliefs(engine, bands=None, kinds=None, limit=50, offset=0) == 0
    finally:
        await engine.aclose()

    rendered = output.getvalue()
    assert "derived" in rendered, "an observed belief reads back in the derived band"


# --- lost evidence, rendered (ADR-0077 §6, §9.8) ------------------------


def test_the_listing_reports_lost_support_as_a_count_and_a_lowered_confidence(
    output: StringIO,
) -> None:
    """The listing resolves *existence*: counts and the adjusted number (ADR-0077 §6).

    Printing every citation for a fifty-belief page would bury the listing; what the
    user needs there is that support has gone and that the confidence reflects it.
    """
    cli._render_belief_summary(
        _summary(BeliefBand.DERIVED, confidence=0.35, evidence_count=2, lost_evidence=1)
    )
    rendered = _flat(output.getvalue())
    assert "2 piece(s) of evidence" in rendered
    assert "1 of which no longer exists" in rendered
    assert "confidence 0.35" in rendered
    assert "Because:" not in rendered, "the listing does not print the citations themselves"


def test_the_single_belief_view_shows_surviving_evidence_and_tombstones_the_rest(
    output: StringIO,
) -> None:
    """A lost citation is an explicit tombstone — never an id, never a gap (§6).

    ADR-0073 §4's floor, kept where the user is about to act on the belief: the
    tombstone says an item stood here and is gone, and deliberately does not say what
    it was, nor whether it was deleted or merely expired.
    """
    cli._render_belief(
        _belief(
            BeliefBand.DERIVED,
            confidence=0.35,
            evidence=(_cited("they asked for metric units")[0], _GONE),
        )
    )
    rendered = _flat(output.getvalue())
    assert "they asked for metric units" in rendered
    assert "an item of evidence stood here and is gone" in rendered
    assert "ep-" not in rendered, "no citation id reaches the terminal"


def test_a_belief_with_no_support_left_says_so_and_says_it_is_still_held(
    output: StringIO,
) -> None:
    """The all-unsupported state is named, and named as *held* (ADR-0077 §6).

    It is not auto-retired, so a line implying the assistant had dropped it would
    misdescribe what the user can still do with it — assert it themselves, or forget
    it.
    """
    cli._render_belief(_belief(BeliefBand.DERIVED, confidence=0.1, evidence=(_GONE, _GONE)))
    rendered = _flat(output.getvalue())
    assert "none of which still exists" in rendered
    assert "I still hold it" in rendered
    assert "nothing supports it any more" in rendered


def test_the_forget_prompt_shows_the_warrant_the_user_is_judging(output: StringIO) -> None:
    """Show-then-confirm includes the evidence, tombstones and all (ADR-0073 §5, §6)."""
    cli._render_forget_prompt(
        _belief(
            BeliefBand.DERIVED,
            confidence=0.35,
            evidence=(_cited("they asked for metric units")[0], _GONE),
        )
    )
    rendered = _flat(output.getvalue())
    assert "About to forget this belief" in rendered
    assert "they asked for metric units" in rendered
    assert "an item of evidence stood here and is gone" in rendered


async def test_an_observed_belief_reads_back_with_the_episodes_behind_it(
    output: StringIO,
) -> None:
    """End to end: observe, then read the belief's own evidence back (ADR-0077 §6, §9.8).

    The claim the ``observe`` surface makes — that what it stored is immediately
    inspectable — asserted against the citations, not merely the row. This is
    ADR-0073 §4's gate discharged: a derived belief now reaches the user with the
    warrant it was formed from.
    """
    engine, conversations = _conversation_engine()
    try:
        await cli._drive_turn(
            engine,
            "hello",
            timeout=timedelta(seconds=5),
            approver=lambda _c: True,
            confirm_operation=_no_routed_card,
        )
        conversation = (await conversations.recent())[0].id
        assert await cli._drive_observe(engine, conversation) == 0

        # The command's own default: every kind except episodic, because an episode
        # is the evidence a belief is made of rather than a belief (ADR-0074 §6).
        page = await engine.beliefs(kinds=list(cli._DEFAULT_BELIEF_KINDS))
        assert len(page) == 1
        assert page[0].band is BeliefBand.DERIVED
        assert page[0].evidence_count >= 1
        assert page[0].lost_evidence == 0
        assert page[0].unsupported is False

        # The listing carries no citations at all (ADR-0085 §4a), so the warrant
        # comes from the single-belief view — which is the split being exercised.
        detail = await engine.belief(page[0].id)
        assert detail is not None
        cli._render_belief(detail)
    finally:
        await engine.aclose()

    assert "Because:" in output.getvalue()


def test_a_deferral_shows_the_episodes_it_rests_on(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0077 §4: a reported deferral carries the candidate, **its citations**, the reason.

    The citations have to be *here* because nothing persists a deferred proposal —
    there is no later belief-detail view through which its warrant could ever be
    inspected, so a count would be the last word on a belief the user is being asked
    to act on. Resolved content, never an id (ADR-0073 §4's floor).
    """
    report = _observed_report(
        proposals=(
            _proposal(
                decision=LearnDecision.DEFERRED,
                record_id=None,
                content="the user works from Lisbon",
                reason="fake: an inference never silently overrides an assertion",
                evidence=_cited("I'm in Lisbon this month", "the Lisbon office again"),
            ),
        )
    )
    _wire(monkeypatch, _RecordingObserveEngine(report))

    result = CliRunner().invoke(cli.app, ["observe"])

    assert result.exit_code == 0
    rendered = _flat(output.getvalue())
    assert "I'm in Lisbon this month" in rendered
    assert "the Lisbon office again" in rendered
    assert "rec-" not in rendered, "no citation id reaches the terminal"


def test_a_dropped_proposal_tombstones_the_evidence_that_went_away(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The citation that vanished is why nothing was stored, so it is shown as gone.

    Echoing the copy still sitting in the pass's batch would print back content the
    user may have just destroyed with ``forget-conversation``; dropping it would hide
    a citation, which ADR-0073 §4's floor forbids. A tombstone is the only honest
    third option.
    """
    report = _observed_report(
        proposals=(
            _proposal(
                decision=None,
                record_id=None,
                reason="the evidence it cited went away between selection and the write",
                evidence=(_cited("a surviving episode")[0], _GONE),
            ),
        ),
        dropped_unsupported=1,
    )
    _wire(monkeypatch, _RecordingObserveEngine(report))

    result = CliRunner().invoke(cli.app, ["observe"])

    assert result.exit_code == 0
    rendered = _flat(output.getvalue())
    assert "a surviving episode" in rendered
    assert "an episode stood here and is gone" in rendered


def test_a_stored_belief_points_at_its_own_view_rather_than_reprinting_the_transcript(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A kept belief has a later detail view; a deferral does not — hence the split.

    Printing every episode behind every accepted belief would reprint the transcript
    the observation was distilled *from*, which is the opposite of what a summary is
    for. The id and ``assistant beliefs`` are the route to the warrant instead.
    """
    _wire(monkeypatch, _RecordingObserveEngine(_observed_report()))

    result = CliRunner().invoke(cli.app, ["observe"])

    assert result.exit_code == 0
    rendered = _flat(output.getvalue())
    assert "they asked for metric" not in rendered, "a stored belief does not reprint its episodes"
    assert "rec-9" in rendered
    assert "assistant beliefs" in rendered


# --- the deferred-question surface (ADR-0078 §8, §9) ----------------------


class _QuestionEngine:
    """A stand-in façade over two fixed question lists and one answer."""

    def __init__(
        self,
        *,
        waiting: tuple[Question, ...] = (),
        stranded: tuple[Question, ...] = (),
        answer: AnswerOutcome | None = None,
        forgotten: bool = True,
    ) -> None:
        self._waiting = waiting
        self._stranded = stranded
        self._answer = answer
        self._forgotten = forgotten
        self.answered: list[tuple[str, bool]] = []
        self.disposed: list[str] = []

    async def questions(self, *, limit: int = 50, offset: int = 0) -> tuple[Question, ...]:
        """The answerable page, ignoring paging (the façade's own contract covers it)."""
        return self._waiting

    async def interrupted_questions(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[Question, ...]:
        """The interrupted page, which is a *separate* read all the way to here."""
        return self._stranded

    async def answer(self, question_id: str, *, accept: bool) -> AnswerOutcome:
        """Record the relayed answer and return the scripted outcome."""
        self.answered.append((question_id, accept))
        assert self._answer is not None
        return self._answer

    async def forget_question(self, question_id: str) -> bool:
        """Record the disposal and report whether anything was there."""
        self.disposed.append(question_id)
        return self._forgotten

    async def start(self) -> None:
        """The start-up sweeps, which this stand-in has no stores to sweep."""

    async def aclose(self) -> None:
        """Nothing to release: this stand-in owns no resource."""


def _question(  # noqa: PLR0913 — one knob per field a Question carries; that is the point
    question_id: str = "q-1",
    *,
    state: QuestionState = QuestionState.OPEN,
    retires: tuple[Retirement, ...] = (),
    successor: SuccessorLink | None = None,
    band: BeliefBand = BeliefBand.ASSERTED,
    attestation: Attestation | None = None,
    rests_on_recorded_external_content: bool = False,
) -> Question:
    """One deferred question, as the façade hands it to the adapter.

    ``band``, ``attestation`` and ``rests_on_recorded_external_content`` all describe
    the **proposal** — the record that would be written if the question were accepted —
    on the same reading ``band`` already had here, and describe no entry in ``retires``
    (ADR-0189 §2). Each retirement answers for itself through :func:`_retired`.
    """
    return Question(
        id=question_id,
        state=state,
        content="the user works from Lisbon",
        kind=MemoryKind.SEMANTIC,
        band=band,
        rationale="they said so",
        reason="contradicts a prior user assertion",
        retires=retires,
        asked_at=AT,
        expires_at=AT,
        successor=successor,
        attestation=attestation,
        rests_on_recorded_external_content=rests_on_recorded_external_content,
    )


def _retired(
    record_id: str = "live-1",
    *,
    content: str | None = "the user works from Madrid",
    band: BeliefBand = BeliefBand.ASSERTED,
    attestation: Attestation | None = None,
    rests_on_recorded_external_content: bool = False,
) -> Retirement:
    """One record accepting would retire, with the whole warrant or none of it.

    ``content=None`` yields the tombstone ADR-0045 §6 produces and ADR-0189 §2 ties to
    it: the store hid a closed window, so ``warrant`` is ``None`` too. Every other call
    builds a whole warrant, because a warrant that exists is always whole (ADR-0189 §3)
    and ``Warrant``'s own band-keyed validator refuses every combination the band
    forecloses.
    """
    if content is None:
        return Retirement(record_id=record_id, content=None, warrant=None)
    return Retirement(
        record_id=record_id,
        content=encodable_text(content),
        warrant=Warrant(
            band=band,
            rests_on_recorded_external_content=(
                True if band is BeliefBand.ATTESTED else rests_on_recorded_external_content
            ),
            attestation=attestation,
        ),
    )


def test_questions_renders_the_question_the_band_it_would_enter_and_what_it_retires(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Everything ADR-0078 §8 requires per question, and the band as a **conditional**.

    A pending question is not a belief of any band (§1): ``band_of`` applied to its
    proposal says only where the record *would* land if accepted, so the surface must
    not word it as something held. And what accepting would retire is the exact scope
    the answer authorises, not decoration — a conflict retired since the question was
    asked renders as *no longer held* rather than being omitted.
    """
    engine = _QuestionEngine(
        waiting=(
            _question(
                retires=(
                    Retirement(record_id="live-1", content="the user works from Madrid"),
                    Retirement(record_id="gone-1", content=None),
                ),
            ),
        )
    )
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["questions"])

    assert result.exit_code == 0
    rendered = " ".join(output.getvalue().split())
    assert "q-1" in rendered
    assert "the user works from Lisbon" in rendered
    assert "Would be held as" in rendered, "a conditional, never a belief held"
    assert "not held yet" in rendered
    assert "contradicts a prior user assertion" in rendered, "why the user is being asked"
    assert "the user works from Madrid" in rendered, "resolved to content, not an id alone"
    assert "no longer held" in rendered, "and one that has gone says so"
    assert "assistant answer q-1" in rendered


# --- ADR-0189 §9 on the two question renderers ------------------------------


def test_a_retirement_names_the_source_that_reported_it_and_when_it_spoke(
    output: StringIO,
) -> None:
    """ADR-0189 §9's first surface clause, on ``_render_retirements``.

    The attested-and-resolved arm of the required matrix: both ``reported_by`` **and**
    ``reported_at`` reach the rendered output. §9 is explicit that a test asserting
    only that a field is populated, or only that the source is named, does not satisfy
    it, so both are read off the console's own bytes.
    """
    cli._render_retirements(
        _question(retires=(_retired("live-1", band=BeliefBand.ATTESTED, attestation=ATTESTED_BY),))
    )
    rendered = _flat(output.getvalue())
    assert "work-calendar" in rendered, "the reporting source is named"
    assert "2026-03-02 08:30 UTC" in rendered, "and the instant it spoke"
    assert "on that source's own clock" in rendered


def test_an_attested_retirement_is_presented_as_somebody_elses_words(
    output: StringIO,
) -> None:
    """#673 closed: ADR-0098 §7's first clause, satisfiable for the first time.

    Before ``Retirement.warrant`` existed this list rendered attacker-authorable
    calendar text under *"Accepting would retire:"* with **no origin marker at all** —
    the span safely rendered and silently unattributed, on the screen where the user is
    deciding. ADR-0098 §7 names that as what escalation must not become: "Escalating to
    the user is not a mitigation if the escalation is where the attacker's sentence is
    read as ours."

    ADR-0189 §4 makes the presentation conditional on the band, and the marker leads
    the content rather than trailing it: a marker read *after* the sentence it
    qualifies has already let that sentence land as ours.
    """
    cli._render_retirements(
        _question(
            retires=(
                _retired(
                    "live-1",
                    content="dinner with the board on Thursday",
                    band=BeliefBand.ATTESTED,
                    attestation=ATTESTED_BY,
                ),
            )
        )
    )
    rendered = _flat(output.getvalue())
    marker = rendered.index("someone else's words")
    assert marker < rendered.index("dinner with the board"), "the marker leads the span"
    assert "These are not my words and not yours" in rendered


@pytest.mark.parametrize(
    ("band", "marker", "note"),
    [
        pytest.param(
            BeliefBand.ASSERTED,
            "your own words",
            "You told me this",
            id="asserted",
        ),
        pytest.param(
            BeliefBand.DERIVED,
            "my own inference",
            "these are my words rather than a source's",
            id="derived",
        ),
    ],
)
def test_a_retirement_that_is_not_attested_is_never_presented_as_third_party(
    band: BeliefBand, marker: str, note: str, output: StringIO
) -> None:
    """ADR-0189 §4's fifth clause, and the mistake it was written to stop recurring.

    "Where ``retirement.warrant`` is present and its band is ``ASSERTED`` or
    ``DERIVED``, the ``content`` is **not** third-party and no surface presents it as
    such: an asserted retirement is the user's own word (ADR-0038 §1a) and a derived
    one is this system's own sentence."

    An earlier draft of ADR-0189 ruled the third-party presentation unconditionally, so
    a retirement of the user's own assertion would have been rendered as somebody
    else's words and a retirement of this system's own inference likewise; architecture
    review found it on round 3. The band inside the warrant is what tells the three
    apart, and this is the pin that keeps them apart.
    """
    cli._render_retirements(_question(retires=(_retired("live-1", band=band),)))
    rendered = _flat(output.getvalue())
    assert marker in rendered
    assert note in rendered
    assert "someone else's words" not in rendered
    assert "work-calendar" not in rendered, "and no source is named where none reported it"


def test_a_derived_retirement_says_its_warrant_came_from_outside(output: StringIO) -> None:
    """#1517's first finding, on the retirement path (ADR-0189 §4's third clause).

    §4 names the access path for this projection explicitly, because an earlier draft
    did not: the two facts are read "from
    ``retirement.warrant.rests_on_recorded_external_content`` beside
    ``retirement.warrant.band`` on a ``Retirement``" — ``Retirement`` carries neither of
    its own, so a clause naming them bare was not implementable, and adversarial review
    found that on round 3.

    The content stays this system's own sentence on this arm, exactly as it does on the
    belief line: §4 forbids presenting it as third-party text on the strength of the
    predicate.
    """
    cli._render_retirements(
        _question(
            retires=(
                _retired(
                    "live-1",
                    band=BeliefBand.DERIVED,
                    rests_on_recorded_external_content=True,
                ),
            )
        )
    )
    rendered = _flat(output.getvalue())
    assert "came from a connected source rather than from you" in rendered
    assert "my own inference" in rendered, "the words are still ours"
    assert "someone else's words" not in rendered


def test_an_unresolved_retirement_renders_no_band_no_origin_and_no_source(
    output: StringIO,
) -> None:
    """ADR-0189 §9's tombstone clause, over the two retirement paths' CLI half.

    §4: where the warrant is ``None`` the retired record no longer resolves —
    ``content`` is ``None`` too — "and the surface renders it as *no longer held* … and
    asserts nothing about its band, its origin or its source. It renders no third state
    as ``False`` and no absence as a value."

    **This is a second test rather than a clause of the first, because the state a
    single test would have named cannot exist.** An earlier draft of §9 asked for "a
    test over an attested retirement whose retired record no longer resolves", and §2
    makes ``warrant`` and ``content`` ``None`` together for exactly that record — so an
    unresolved retirement is in no band, carries no attestation, and there is no
    attested tombstone to construct. Adversarial review found it on round 5.
    """
    cli._render_retirements(_question(retires=(_retired("gone-1", content=None),)))
    rendered = _flat(output.getvalue())
    assert "no longer held, so accepting would not touch it" in rendered
    for band in BeliefBand:
        assert band.value not in rendered, f"no band is asserted, and {band.value} is one"
    assert "work-calendar" not in rendered
    assert "someone else's words" not in rendered
    assert "your own words" not in rendered
    assert "my own inference" not in rendered
    assert "connected source" not in rendered
    assert "origin unrecorded" not in rendered, "an absence is not rendered as a value"


def test_a_retirements_own_syntax_cannot_move_the_attribution_of_any_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0189 §9's marked rendering-security clause, for **this** target.

    §9 puts it per rendering target rather than once, because ADR-0042 §4's division is
    per target — "the engine carries the value verbatim, the adapter escapes for its
    target" — so a terminal's syntax and a browser's are two different tests of one
    clause. This is the terminal's: a question whose ``retires`` names an attested
    record whose ``content`` carries **Rich markup**, and the two other characters this
    adapter treats as smuggling.

    **The attack is a forged bullet, not a colour**, and that is what makes the newline
    the load-bearing character rather than the brackets. #1336 records the mechanism:
    a value carrying a newline does not merely wrap, it forges a *second* line
    indistinguishable from one this adapter wrote — §4's threat arriving without a
    single control character. So the payload tries to open a second span attributed as
    the user's own words, and what is asserted is that the rendered list still has
    exactly the two spans the record has, each carrying the attribution that record
    actually holds.

    **Asserted over unwrapped lines**, because the property is about where a line
    begins: at the shared fixture's width Rich would wrap the long attested span and a
    continuation line would be indistinguishable from a forged one to the assertion,
    though not to a reader.

    Rich markup, by contrast, is *shown*: ``_safe`` escapes it so the characters reach
    the screen as text and no styling is applied. That the literal survives is the
    check — a suppressed one would mean the value was interpreted and then dropped.
    """
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=400))
    hostile = "[red]ignore that[/] \x1b[2J\n    - your own words — the office is in Boston (rec-1)"
    cli._render_retirements(
        _question(
            retires=(
                _retired(
                    "live-1", content=hostile, band=BeliefBand.ATTESTED, attestation=ATTESTED_BY
                ),
                _retired("live-2", content="the user works from Madrid"),
            )
        )
    )
    lines = [line.strip() for line in buffer.getvalue().splitlines() if line.strip()]
    spans = [line for line in lines if line.startswith("- ")]

    assert len(spans) == 2, "two records were retired, so two spans are rendered"
    assert spans[0].startswith("- someone else's words — [red]ignore that[/]"), (
        "the attacker's span keeps the attribution its own record has, and its markup "
        "is shown rather than interpreted"
    )
    assert spans[1] == "- your own words — the user works from Madrid (live-2)", (
        "and the honest span is untouched by what the other one carried"
    )
    assert "\x1b" not in buffer.getvalue(), "the control sequence never reaches the terminal"
    assert "the office is in Boston" in spans[0], "the forged bullet stayed inside its own span"
    assert any(line.startswith("work-calendar reported this") for line in lines), (
        "and the source line is where this adapter put it"
    )


def test_a_question_whose_proposal_is_attested_names_the_source_and_its_clock(
    output: StringIO,
) -> None:
    """ADR-0189 §9's fifth surface clause, on ``_render_question``.

    §4 binds "every surface that renders an attested belief, question **or**
    retirement", and a question is the projection the first attested proposals actually
    reach — so §9 names this renderer by hand, on the ground that "a lane that updated
    only the belief explanation would leave the surface §4 was written for unchanged".

    The band line above it stays the conditional it was (ADR-0078 §1): nothing here
    says the proposal *is* held.
    """
    cli._render_question(_question(band=BeliefBand.ATTESTED, attestation=ATTESTED_BY))
    rendered = _flat(output.getvalue())
    assert "work-calendar" in rendered, "the reporting source is named"
    assert "2026-03-02 08:30 UTC" in rendered, "and the instant it spoke"
    assert "on that source's own clock" in rendered
    assert "not held yet" in rendered, "and it is still a conditional"


def test_a_question_whose_proposal_rests_on_outside_content_says_so(
    output: StringIO,
) -> None:
    """#1517's first finding on the question path (ADR-0189 §4's third clause).

    #746's trap named: ``Question.band`` reads ``DERIVED`` for a tainted consolidation,
    which is correct as what the field documents and misleading as a statement about
    warrant, since ``DERIVED`` is glossed as "we worked it out". A surface rendering
    only the band tells the user this is the assistant's own inference at the moment it
    is not entirely — and the structured field is what lets this line exist at all,
    rather than a sentence a client has to parse.
    """
    cli._render_question(
        _question(band=BeliefBand.DERIVED, rests_on_recorded_external_content=True)
    )
    rendered = _flat(output.getvalue())
    assert "came from a connected source rather than from you" in rendered
    assert "someone else's words" not in rendered


@pytest.mark.parametrize(
    "band",
    [
        pytest.param(BeliefBand.ASSERTED, id="asserted"),
        pytest.param(BeliefBand.DERIVED, id="derived"),
    ],
)
def test_an_attestation_outside_the_attested_band_promotes_no_proposal(
    band: BeliefBand, output: StringIO
) -> None:
    """ADR-0072 §4: nothing acquires the standing of a band it is not in by decorating.

    ADR-0189 §2 adds no cross-field validator to ``Question`` — those are ratified types
    with construction sites in the tree, and ADR-0086 §3's admissibility test refuses a
    validator that would refuse what already works — so ``Question(band=ASSERTED,
    attestation=…)`` is model-valid and reaches this surface.

    A renderer keyed on the attestation's **presence** would then introduce the user's
    own word as a connected source's report, which is exactly the laundering ADR-0072 §4
    names one type over: classification is keyed on the source and never on a
    decoration, so "an attestation on an ``INFERRED`` record would be the same
    laundering by a different field — a derived guess wearing a citation to a system
    that never reported it". The band is the classifier, and this keeps it the
    classifier here.
    """
    cli._render_question(_question(band=band, attestation=ATTESTED_BY))
    rendered = _flat(output.getvalue())
    assert "work-calendar" not in rendered
    assert "connected source reported it" not in rendered
    assert f"Would be held as: {band.value}" in rendered, "and the band is unchanged"


def test_an_attested_proposal_with_no_attestation_says_what_reached_it(
    output: StringIO,
) -> None:
    """The off-contract arm on this path, answered as ``_why`` answers its own.

    Constructable for the same reason, and it must draw neither of the two available
    lies: claiming the attestation was **not recorded**, which errs in the direction
    ADR-0073 §4 forgives least on the one band whose whole purpose is provenance, or
    saying nothing at all — which would leave the attested arm silent on the very
    surface ADR-0189 §9 names to stop that.
    """
    cli._render_question(_question(band=BeliefBand.ATTESTED))
    rendered = _flat(output.getvalue())
    assert "does not name that source or say when it spoke" in rendered
    assert "not recorded" not in rendered


def test_a_questions_own_origin_never_answers_for_what_it_would_retire(
    output: StringIO,
) -> None:
    """ADR-0189 §2's fourth clause, which is the one a renderer would run together.

    "On ``Question``, both fields describe the **proposal** … and describe no entry in
    ``retires``. Each entry in ``retires`` answers for itself through its own
    ``warrant``." The case that makes it concrete is the ordinary one #673 describes: a
    user's own assertion, which the policy defers, retiring an attested calendar line.
    The proposal is ``ASSERTED`` with no attestation; the retirement is ``ATTESTED``
    with one — so the source is named exactly once, against the retirement, and the
    proposal is not decorated with a report it never had.
    """
    cli._render_question(
        _question(retires=(_retired("live-1", band=BeliefBand.ATTESTED, attestation=ATTESTED_BY),))
    )
    rendered = _flat(output.getvalue())
    assert "Where it came from:" not in rendered, "an asserted proposal has no origin line"
    assert rendered.count("work-calendar") == 1, "the source is named against the retirement"
    assert "someone else's words" in rendered
    assert "Would be held as: asserted" in rendered, "and the proposal is still the user's"


def test_questions_says_nothing_is_waiting_when_both_lists_are_empty(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty surface says so rather than printing an empty heading."""
    _wire(monkeypatch, _QuestionEngine())

    result = CliRunner().invoke(cli.app, ["questions"])

    assert result.exit_code == 0
    assert "Nothing is waiting" in output.getvalue()


def test_questions_keeps_the_interrupted_list_separate_and_offers_no_retry(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8's two enumerations stay separate, and §9's rendering is the honest one.

    An interrupted question is **not answerable**, so it must not be offered beside the
    ones that are. What it says is that an answer was begun and its outcome is not
    recorded — the actual epistemic situation — plus §9's two recovery steps in order.
    There is deliberately **no verb that claims to retry an apply**: the system does not
    know whether the write landed, and a verb implying it does would be the one
    dishonest line on this surface.
    """
    engine = _QuestionEngine(
        waiting=(_question("q-open"),),
        stranded=(_question("q-stuck", state=QuestionState.INTERRUPTED),),
    )
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["questions"])

    assert result.exit_code == 0
    rendered = " ".join(output.getvalue().split())
    assert "1 question(s) waiting" in rendered
    assert "1 interrupted answer(s)" in rendered, "a separate section, not one merged list"
    assert "outcome was never recorded" in rendered
    assert "nothing to retry" in rendered
    assert "assistant forget-question q-stuck" in rendered, "step 1, named"
    assert "assistant learn" in rendered, "step 2, named"
    assert "assistant answer q-stuck" not in rendered, "an interrupted question is not answerable"
    assert "assistant answer q-open" in rendered, "the answerable one still is"


def test_a_pasted_question_hint_names_the_question_it_was_printed_for(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both hints on this surface have to survive being pasted (#984).

    ``Identifier`` strips a question id but does not forbid an interior space, so an
    unquoted hint for ``q 1`` renders a *valid* command against the wrong argument:
    ``assistant answer q 1 --accept`` answers ``q``. That is a wrong action rather
    than an error, which is what makes it worth a test — ``_safe`` answers a different
    question (Rich markup and control characters) and cannot catch it.

    Asserted by parsing each line the way a shell would rather than by matching quote
    characters, so it holds whichever quoting form ``shlex`` picks.
    """
    engine = _QuestionEngine(
        waiting=(_question("q 1"),),
        stranded=(_question("q 2", state=QuestionState.INTERRUPTED),),
    )
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, ["questions"]).exit_code == 0

    rendered = _flowed(output.getvalue())
    assert _pasted(rendered, "assistant answer", "--accept") == ["assistant", "answer", "q 1"]
    assert _pasted(rendered, "assistant forget-question", "2. Check") == [
        "assistant",
        "forget-question",
        "q 2",
    ]


@pytest.mark.parametrize("unshowable", ["\n", "\t"], ids=["replaced", "expanded"])
def test_a_question_hint_is_withheld_where_showing_it_would_change_what_it_says(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, unshowable: str
) -> None:
    """Quoting settles where an argument ends, not whether it survives being shown.

    Two ways a value fails to reach the screen intact, and the hint has to go for both.
    ``_safe`` **replaces** a character a terminal must not be handed, so an id carrying
    a newline renders as ``q�1``; Rich **expands** a tab, which ``_safe`` deliberately
    keeps, so an id tabbed in the middle renders with spaces. Either way the line is
    perfectly quoted
    and names a question that does not exist — the failure quoting was added to prevent,
    arriving one step later and looking like a working instruction rather than a
    mistake (#1013).

    The question still renders and both recovery steps keep their numbers: what is
    withheld is the copyable command, and the replacement says so rather than leaving a
    gap the reader has to notice. Asserted as the *absence of an offered argument*
    rather than against one mangled spelling, so one case can cover both mechanisms.
    """
    _wire(
        monkeypatch,
        _QuestionEngine(
            waiting=(_question(f"q{unshowable}1"),),
            stranded=(_question(f"q{unshowable}2", state=QuestionState.INTERRUPTED),),
        ),
    )

    assert CliRunner().invoke(cli.app, ["questions"]).exit_code == 0

    rendered = _flowed(output.getvalue())
    assert "the user works from Lisbon" in rendered, "the question itself still renders"
    assert "2. Check" in rendered, "the second recovery step keeps its number"
    assert rendered.count("cannot show") == 2, "one per withheld hint, not one for the page"
    assert "assistant answer '" not in rendered, "no argument is offered at all"
    assert "assistant forget-question '" not in rendered


def test_the_follow_up_hint_is_withheld_where_the_successors_id_cannot_be_shown(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The re-deferral line still names the successor; only its command goes (#1013).

    Naming it is ADR-0078 §9's requirement and does not depend on the id being
    copyable — a user who cannot paste the command still needs to know their answer
    raised a question. So the two renderings part company here: the name stays and the
    offer goes, which is the same split the quoting case makes for the opposite reason.
    """
    _wire(
        monkeypatch,
        _QuestionEngine(
            answer=AnswerOutcome(
                kind=AnswerKind.REDEFERRED,
                question_id="q-1",
                successor=SuccessorLink(id="q\n2", state=QuestionState.OPEN),
            )
        ),
    )

    assert CliRunner().invoke(cli.app, ["answer", "q-1", "--accept"]).exit_code == 0

    rendered = _flowed(output.getvalue())
    assert "Here is the follow-up" in rendered, "the successor is still named"
    assert "cannot show" in rendered
    assert "assistant answer " + shlex.quote("q�2") not in rendered


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (QuestionState.OPEN, "which is waiting"),
        (QuestionState.DECLINED, "already declined"),
        (QuestionState.INTERRUPTED, "another interrupted answer"),
        (QuestionState.APPLIED, "since settled"),
    ],
    ids=["waiting", "declined", "interrupted", "settled"],
)
def test_questions_renders_a_stranded_parents_successor_by_that_rows_own_state(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, state: QuestionState, expected: str
) -> None:
    """§9's cancellation residue, rendered honestly per state.

    Where the parent already names a successor — a cancellation caught after the
    re-deferral admitted one — "the surface shows that row too, rendered by its own
    state: a ``PENDING`` one is the question their answer raised and they can go answer
    it; a ``REJECTED`` or ``APPLYING`` one is not, and says what it needs instead."
    Naming it without its state would advertise something the user cannot act on.
    """
    engine = _QuestionEngine(
        stranded=(
            _question(
                "q-stuck",
                state=QuestionState.INTERRUPTED,
                successor=SuccessorLink(id="q-next", state=state),
            ),
        )
    )
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["questions"])

    assert result.exit_code == 0
    rendered = " ".join(output.getvalue().split())
    assert "q-next" in rendered
    assert expected in rendered


def test_questions_reports_a_read_failure_with_a_nonzero_exit(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One error boundary per command, mapped to an exit code (ADR-0042 §7)."""

    class _Failing(_QuestionEngine):
        async def questions(self, *, limit: int = 50, offset: int = 0) -> tuple[Question, ...]:
            msg = "the queue would not open"
            raise DeferralStoreError(msg)

    _wire(monkeypatch, _Failing())

    result = CliRunner().invoke(cli.app, ["questions"])

    assert result.exit_code == 1
    assert "would not open" in output.getvalue()


@pytest.mark.parametrize(
    ("flag", "accept"), [("--accept", True), ("--reject", False)], ids=["accept", "reject"]
)
def test_answer_relays_the_binary_choice_untouched(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, flag: str, accept: bool
) -> None:
    """The adapter conveys consent and authors nothing (ADR-0042 §6, ADR-0078 §8).

    Binary on purpose: an amendment is a new proposal and ``learn`` already is one, so
    a free-text answer here would be a second correction path wearing a confirmation's
    clothes.
    """
    engine = _QuestionEngine(
        answer=AnswerOutcome(kind=AnswerKind.APPLIED, question_id="q-1", record_id="rec-9")
        if accept
        else AnswerOutcome(kind=AnswerKind.REJECTED, question_id="q-1")
    )
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["answer", "q-1", flag])

    assert result.exit_code == 0
    assert engine.answered == [("q-1", accept)]


def test_answer_requires_an_explicit_choice() -> None:
    """Neither flag is a usage error: there is no default answer to a question."""
    result = CliRunner().invoke(cli.app, ["answer", "q-1"])

    assert result.exit_code == 2


def test_answer_renders_an_applied_correction_with_the_record_it_left_live(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exit test's last mile, at the surface."""
    _wire(
        monkeypatch,
        _QuestionEngine(
            answer=AnswerOutcome(kind=AnswerKind.APPLIED, question_id="q-1", record_id="rec-9")
        ),
    )

    result = CliRunner().invoke(cli.app, ["answer", "q-1", "--accept"])

    assert result.exit_code == 0
    rendered = " ".join(output.getvalue().split())
    assert "Applied" in rendered
    assert "rec-9" in rendered


def test_answer_renders_a_re_deferral_as_a_completed_answer_with_the_next_question(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8: rendering a re-deferral as a failure "would be the same lie in a smaller place".

    The answer *was* used — it raised a successor — so the user is handed the next
    question rather than told their answer went nowhere.
    """
    _wire(
        monkeypatch,
        _QuestionEngine(
            answer=AnswerOutcome(
                kind=AnswerKind.REDEFERRED,
                question_id="q-1",
                successor=SuccessorLink(id="q-2", state=QuestionState.OPEN),
            )
        ),
    )

    result = CliRunner().invoke(cli.app, ["answer", "q-1", "--accept"])

    assert result.exit_code == 0
    rendered = " ".join(output.getvalue().split())
    assert "Your answer was used" in rendered
    assert "Here is the follow-up" in rendered
    assert "q-2" in rendered


def test_the_follow_up_is_named_plainly_and_offered_quoted(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One id, two renderings, and only the copyable one is quoted (#984).

    The re-deferral line both *names* the successor and *offers* a command for it.
    The name is read, so it is shown as the id is; the command is pasted, so it is
    shown as a shell would need it. Quoting the name too would have the user reading
    quote characters as part of an id they may go and type somewhere else.
    """
    _wire(
        monkeypatch,
        _QuestionEngine(
            answer=AnswerOutcome(
                kind=AnswerKind.REDEFERRED,
                question_id="q-1",
                successor=SuccessorLink(id="q 2", state=QuestionState.OPEN),
            )
        ),
    )

    assert CliRunner().invoke(cli.app, ["answer", "q-1", "--accept"]).exit_code == 0

    rendered = _flowed(output.getvalue())
    assert "Here is the follow-up: q 2 " in rendered, "named as the id reads"
    assert _pasted(rendered, "assistant answer", "--accept") == ["assistant", "answer", "q 2"]


def test_answer_says_no_follow_up_could_be_queued_rather_than_naming_one(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one sentence ADR-0078 cannot write, refused at the surface (§9).

    "Saying 're-deferred' there would claim a question was asked when none was." The
    queue was full and this admission had no exemption to spend, so the line names the
    queue.
    """
    _wire(
        monkeypatch,
        _QuestionEngine(
            answer=AnswerOutcome(
                kind=AnswerKind.REDEFERRED,
                question_id="q-1",
                successor=None,
                successor_refused=True,
                disposed=True,
            )
        ),
    )

    result = CliRunner().invoke(cli.app, ["answer", "q-1", "--accept"])

    assert result.exit_code == 0
    rendered = " ".join(output.getvalue().split())
    assert "queue is full" in rendered
    assert "could not put the follow-up" in rendered
    assert "destroyed while your answer was being applied" in rendered


def test_answer_reports_a_stale_answer_without_calling_the_user_slow(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6: ``STALE`` is not a lapsed deadline, and the line must not read as one."""
    _wire(
        monkeypatch, _QuestionEngine(answer=AnswerOutcome(kind=AnswerKind.STALE, question_id="q-1"))
    )

    result = CliRunner().invoke(cli.app, ["answer", "q-1", "--accept"])

    assert result.exit_code == 0
    rendered = " ".join(output.getvalue().split())
    assert "no longer applies" in rendered
    assert "too slow" not in rendered


def test_answer_reports_a_question_that_is_not_open_with_a_nonzero_exit(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An id naming nothing open is reported and mapped to an exit code (§7)."""
    _wire(
        monkeypatch,
        _QuestionEngine(answer=AnswerOutcome(kind=AnswerKind.NOT_OPEN, question_id="q-1")),
    )

    result = CliRunner().invoke(cli.app, ["answer", "q-1", "--accept"])

    assert result.exit_code == 1
    assert "not open" in output.getvalue()


def test_forget_question_destroys_it_and_says_what_it_does_not_undo(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9's first recovery step, and the honest half of what it does not do.

    Destroying the question does not undo a memory write an interrupted answer may
    already have made — and the surface cannot say whether one landed, so it points at
    ``beliefs`` rather than guessing.
    """
    engine = _QuestionEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["forget-question", "q-1"])

    assert result.exit_code == 0
    assert engine.disposed == ["q-1"]
    rendered = " ".join(output.getvalue().split())
    assert "Forgotten" in rendered
    assert "assistant beliefs" in rendered
    assert "cannot tell you whether that write landed" in rendered


def test_forget_question_reports_an_id_naming_nothing_with_a_nonzero_exit(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``False`` is rendered and mapped to an exit code, as ``forget`` does (§7)."""
    _wire(monkeypatch, _QuestionEngine(forgotten=False))

    result = CliRunner().invoke(cli.app, ["forget-question", "q-1"])

    assert result.exit_code == 1
    assert "Nothing to forget" in _flowed(output.getvalue())


# --- the disposition is the gate's verdict, not the outcome (#531) ----------


def _driven(status: StepStatus) -> StepOutcome:
    """One executed step whose own record carries ``status``.

    Built directly rather than driven through a turn because the point is the
    *renderer*: #531's defect was an adapter reading ``disposition`` and discarding
    ``state``, and what has to be pinned is that every non-successful status the
    record can carry is rendered as one.
    """
    failure = None if status is StepStatus.SUCCEEDED else StepFailure(message="the tool raised")
    return StepOutcome(
        disposition=Disposition.EXECUTED,
        step_id="step-1",
        tool_id="smtp",
        state=ExecutionState(
            id="exec-1",
            plan_id="plan-1",
            updated_at=AT,
            steps=(
                StepExecution(
                    step_id="step-1",
                    status=status,
                    attempts=1,
                    bound_tool="smtp",
                    approval_ref="decision-1",
                    started_at=AT,
                    finished_at=AT,
                    failure=failure,
                ),
            ),
        ),
    )


def test_a_step_refused_for_its_arguments_renders_from_the_disposition(
    output: StringIO,
) -> None:
    """``_render_step`` reaches the verdict for a step whose record says nothing (#1113).

    The sibling of the cases below, taken from the other end. There the disposition
    is ``EXECUTED`` and the *record* is what has to be read; here the step was
    refused before anything was committed, so ADR-0145 §4 leaves it ``PENDING`` with
    no ``bound_tool``, no ``approval_ref`` and no ``failure`` — the record has
    nothing to say and the verdict is the whole of the news. Built directly rather
    than driven through a turn for ``_driven``'s reason, and because what makes the
    runner return this disposition is ``orchestration``'s contract, pinned in
    ``tests/orchestration/test_runner.py`` where it belongs.
    """
    refused = StepOutcome(
        disposition=Disposition.INVALID_PARAMETERS,
        step_id="step-1",
        # ``None`` by construction: ADR-0144 §7's eligibility filter emptied the
        # candidate set, so no tool was ever bound to the step.
        tool_id=None,
        state=ExecutionState(
            id="exec-1",
            plan_id="plan-1",
            updated_at=AT,
            steps=(StepExecution(step_id="step-1", status=StepStatus.PENDING),),
        ),
    )

    # ``False`` is the existing reading of every non-``EXECUTED`` disposition and is
    # not this change's to revisit: the turn did not fail, it declined to act.
    assert cli._render_step(refused) is False
    rendered = _flowed(output.getvalue())
    assert "not established as acceptable" in rendered
    assert "Done" not in rendered


def test_an_executed_step_that_succeeded_reads_as_done(output: StringIO) -> None:
    """The discriminating half: success still renders success and still exits 0."""
    assert cli._render_step(_driven(StepStatus.SUCCEEDED)) is False
    assert "Done" in output.getvalue()


@pytest.mark.parametrize(
    ("status", "headline"),
    [(StepStatus.FAILED, "Failed"), (StepStatus.INDETERMINATE, "Unresolved")],
)
def test_every_non_successful_status_reads_as_one(
    output: StringIO, status: StepStatus, headline: str
) -> None:
    """ADR-0084 §8: the named step's ``status`` is the outcome, not the disposition.

    **Both** of ``core/types.py``'s ``_FAILURE_STATUSES`` are covered, and that is
    the point of parametrising rather than testing ``FAILED`` alone: a renderer
    written as "not ``FAILED`` means done" reproduces #531 exactly one status over —
    on ``INDETERMINATE``, which ADR-0014 §4 makes durable *because* it must be
    resolved explicitly and where the tool may in fact have acted.

    They are told apart rather than flattened: "failed" says the call finished
    badly, "unresolved" says nobody knows whether it took effect.
    """
    assert cli._render_step(_driven(status)) is True
    rendered = output.getvalue()
    assert headline in rendered
    assert "the tool raised" in rendered
    assert "Done" not in rendered


# --- the grant surface (ADR-0102 §1, §6, §9) --------------------------------
# Two of these clauses are the *client's* and are unenforceable from the hub's
# side (ADR-0098 §5): §6's disclosure-before-grant, and §9's rule about what a
# revocation may be said to have done. ADR-0102 §12's client lane owes exactly
# these tests, and they can live nowhere else.


def _granting_engine(*, location: str | None = "/srv/calendar.ics") -> FakeAssistantEngine:
    """A fake hub holding one grantable source, granted by nothing yet."""
    engine = FakeAssistantEngine()
    engine.hold_source("calendar", location=location)
    return engine


def test_sources_lists_each_source_with_where_it_reads_from(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0097 §9: a client offers a choice among declared identities.

    And the location is rendered, because this response is the only place it exists
    (ADR-0102 §6) — a listing that hid it would leave the user choosing between
    names with nothing to judge.
    """
    _wire(monkeypatch, _granting_engine())

    result = CliRunner().invoke(cli.app, ["sources"])
    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "calendar" in rendered
    assert "/srv/calendar.ics" in rendered
    assert "not granted" in rendered


def test_grant_renders_the_location_before_it_asks(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0102 §6's third clause, and **the ordering is the whole of it**.

    "A client renders ``location`` to the user, and takes an explicit act from the
    user, **before** it sends ``grant``." A client that prompted first and rendered
    the path afterwards would satisfy every "the path appears somewhere" check and
    breach the clause outright — the user would be answering about a source they
    had not been shown, which is the uninformed grant ADR-0097 §9a exists to
    prevent.

    So the console is read **at the moment the confirmation is requested**, from
    inside the approver itself, rather than after the command has returned. That is
    the only vantage point from which "before" is observable at all: nothing on the
    wire distinguishes the two orders (ADR-0098 §5), and neither does the final
    output.
    """
    engine = _granting_engine()
    _wire(monkeypatch, engine)
    seen_at_prompt: list[str] = []

    def _watching(_source: object) -> bool:
        seen_at_prompt.append(output.getvalue())
        return False

    monkeypatch.setattr(cli, "_confirm_grant", _watching)
    result = CliRunner().invoke(cli.app, ["grant", "calendar", "--scope", "facet"])

    assert result.exit_code == 0
    assert len(seen_at_prompt) == 1, "the user must be asked exactly once"
    assert "/srv/calendar.ics" in seen_at_prompt[0]
    # And the refusal is honoured: nothing is sent at all.
    assert not [call for call in engine.calls if call[0] == "grant"]
    assert not engine.grants_recorded


def test_a_blank_source_is_a_usage_error_and_never_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0042 §7: an adapter maps every failure to a controlled exit code.

    ``NonBlankEncodableText`` refuses a blank ``source`` with a ``ValueError``,
    which is **not** an :class:`AssistantError` — so without a parse-time refusal it
    escapes the command's error boundary as an uncaught traceback. ``revoke`` is the
    case that reached the client at all: ``grant`` enumerates first and happens to
    report the value as unofferable, which is the right answer by accident of
    ordering rather than by a rule, so both are pinned here.

    Exit code 2, because it is a usage error caught before any client is built —
    the treatment ``--limit`` and blank ``learn`` content already get. **And that
    second clause is asserted rather than asserted-about** (#1970): ``grant``'s
    right answer here is right "by accident of ordering rather than by a rule", as
    above, and an ordering is the one thing an exit code cannot show.
    """
    opened = _wire_recording_opens(monkeypatch, _granting_engine())

    assert CliRunner().invoke(cli.app, ["revoke", "   "]).exit_code == 2
    assert CliRunner().invoke(cli.app, ["grant", "   ", "--scope", "facet"]).exit_code == 2
    assert opened == []


def test_a_repeated_scope_is_a_usage_error_and_never_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0097 §10 spells a duplicated scope as a refusal, not something to fold away.

    Both the client and the engine raise ``ValueError`` for it, which is again not
    an :class:`AssistantError`, so ``--scope facet --scope facet`` escaped as a
    traceback for the same reason a blank source did.

    **Refused at the parse boundary, which is asserted rather than asserted-about**
    (#1973): ``_distinct_scope`` is a Typer callback, and the two places that would
    otherwise raise are both *past* a client — so a refusal that had drifted behind
    the open would be answering the same argument with the same exit code, from the
    far side of the I/O this one precedes.
    """
    opened = _wire_recording_opens(monkeypatch, _granting_engine())

    result = CliRunner().invoke(
        cli.app, ["grant", "calendar", "--scope", "facet", "--scope", "facet", "--yes"]
    )
    assert result.exit_code == 2
    assert opened == []


def test_a_source_with_no_utf8_encoding_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r"""ADR-0102 §6's encoding hazard, one argument over from the path it names.

    Linux passes argv as bytes and Python decodes it with ``surrogateescape``, so
    ``assistant revoke $'\xe9'`` arrives as a lone surrogate — a value
    ``EncodableText`` refuses and ADR-0087's encoder has no form for. Refused at the
    parse boundary, so it is a usage error rather than the uncaught ``ValueError``
    the client would otherwise raise past the command's error boundary.

    **The refusal does not echo the value**, which is both ADR-0097 §9's rule about
    a caller-supplied source and a practical necessity: the process may not be able
    to write it down at all.

    **And "at the parse boundary" is observed rather than named** (#1973), for the
    reason the blank-source case one over states: ``grant`` reaches the right answer
    for a bad source partly by accident of ordering, so where the refusal falls
    relative to the client is exactly what wants pinning.
    """
    opened = _wire_recording_opens(monkeypatch, _granting_engine())
    unwritable = "\udce9"

    result = CliRunner().invoke(cli.app, ["revoke", unwritable])
    assert result.exit_code == 2
    assert unwritable not in result.output
    assert CliRunner().invoke(cli.app, ["grant", unwritable, "--scope", "facet"]).exit_code == 2
    assert opened == []


def test_the_source_reaches_the_hub_exactly_as_it_was_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0102 §2: the adapter refuses a blank source and **normalises nothing**.

    The refusal above is a parse-time callback, and a callback is exactly where an
    author reaches for ``.strip()``. Doing so would make ``revoke " calendar "``
    arrive at the hub as ``calendar`` and *match* a held reader, where ADR-0097 §10
    requires it be refused rather than matched — §2's substitutability failure,
    arriving one layer further out than the annotation it was argued about.
    """
    engine = _granting_engine()
    _wire(monkeypatch, engine)

    CliRunner().invoke(cli.app, ["revoke", "  calendar  "])
    assert [call for call in engine.calls if call[0] == "revoke"] == [
        ("revoke", {"source": "  calendar  "})
    ]


def test_grant_records_the_grant_once_the_user_agrees(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The discriminating half: the refusal above is about the answer, not the flow."""
    engine = _granting_engine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, ["grant", "calendar", "--scope", "facet", "--scope", "ingest"], input="y\n"
    )
    assert result.exit_code == 0
    assert [record.scope for record in engine.grants_recorded] == [
        (GrantScope.FACET, GrantScope.INGEST)
    ]
    assert "Granted" in output.getvalue()


def test_a_pasted_revoke_hint_withdraws_the_source_it_was_printed_for(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both revoke hints have to survive being pasted (#984).

    A source name with an interior space is admissible rather than exotic: ADR-0102 §2
    keeps a reader's declared name byte-exact precisely because it is compared without
    normalisation, and ``NonBlankEncodableText`` never normalises. Unquoted, the hint
    for ``my calendar`` reads as ``assistant revoke my calendar`` — a valid command
    that revokes ``my``, with ``calendar`` left over.

    Both hints are exercised in one run because the second only exists after the
    first: granting once produces the confirmation's hint, and granting again finds
    the source already granted and produces the prompt's. Each sentence wraps its
    command in quotes of its own, so the slice each assertion reads back closes at
    that closing quote.
    """
    engine = FakeAssistantEngine()
    engine.hold_source("my calendar", location="/srv/calendar.ics")
    _wire(monkeypatch, engine)

    granted = CliRunner().invoke(cli.app, ["grant", "my calendar", "--scope", "facet"], input="y\n")
    assert granted.exit_code == 0
    confirmation = _flowed(output.getvalue())
    assert "Granted." in confirmation
    assert _pasted(confirmation, "assistant revoke", "'.") == ["assistant", "revoke", "my calendar"]

    already = len(output.getvalue())
    again = CliRunner().invoke(cli.app, ["grant", "my calendar", "--scope", "facet"], input="n\n")
    assert again.exit_code == 0
    prompt = _flowed(output.getvalue()[already:])
    assert "It is already granted" in prompt
    assert _pasted(prompt, "assistant revoke", "'.") == ["assistant", "revoke", "my calendar"]


@pytest.mark.parametrize("unshowable", ["\n", "\t"], ids=["replaced", "expanded"])
def test_a_revoke_hint_is_withheld_where_the_source_name_cannot_be_shown(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, unshowable: str
) -> None:
    """A declared name a terminal cannot show costs the hint, not the grant (#1013).

    ADR-0102 §4 admits any declared identity equal to its own ``strip()`` that validates
    as an ``Identifier``, and neither an interior newline nor an interior tab is
    stripped — so both names below are enumerated and grantable, and both reach the
    screen as a *different* source: the newline is replaced by ``_safe`` and the tab is
    expanded by Rich.

    The act still happens and is still recorded byte-exact; what goes is the line
    offering to undo it. Which is the point of separating the two — an unshowable name
    must not become an ungrantable one.
    """
    named = f"my{unshowable}calendar"
    engine = FakeAssistantEngine()
    engine.hold_source(named, location="/srv/calendar.ics")
    _wire(monkeypatch, engine)

    granted = CliRunner().invoke(cli.app, ["grant", named, "--scope", "facet"], input="y\n")
    assert granted.exit_code == 0
    assert [record.source for record in engine.grants_recorded] == [named], (
        "the grant is recorded byte-exact; only the printed hint is affected"
    )
    confirmation = _flowed(output.getvalue())
    assert "Granted." in confirmation
    assert "cannot show" in confirmation
    assert "assistant revoke '" not in confirmation, "no argument is offered at all"

    already = len(output.getvalue())
    again = CliRunner().invoke(cli.app, ["grant", named, "--scope", "facet"], input="n\n")
    assert again.exit_code == 0
    prompt = _flowed(output.getvalue()[already:])
    assert "It is already granted" in prompt
    assert "cannot show" in prompt
    assert "assistant revoke '" not in prompt


def test_every_scope_the_enum_offers_is_accepted_and_rendered_in_words(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0133 §6: the surface may not offer fewer uses than the vocabulary has.

    "No lane may suppress the member from that surface while it is in the enum: an
    option that silently refuses a member of its own type, or a help string
    enumerating two of three uses, is a surface disagreeing with the vocabulary."

    Written over ``GrantScope`` rather than per member, so it is the *offer* that
    is asserted rather than today's three names — a member added without a phrase
    fails here as well as at the type check, and a member accepted by the option
    but rendered as nothing cannot pass at all.

    **Both halves matter and neither implies the other.** The value must reach the
    hub as the user's chosen scope, and the confirmation must say what that scope
    allows *in words*: ADR-0102 §6 shows the user what they are consenting to
    before it is recorded, and a phrase that silently rendered empty would ask
    them to agree to a blank. That is why the rendered text is asserted to be
    non-trivial rather than merely present.
    """
    for use in GrantScope:
        engine = _granting_engine()
        _wire(monkeypatch, engine)

        result = CliRunner().invoke(cli.app, ["grant", "calendar", "--scope", use.value, "--yes"])

        assert result.exit_code == 0, use
        assert [record.scope for record in engine.grants_recorded] == [(use,)], use
        rendered = output.getvalue()
        assert cli._scope_phrase([use]) in rendered, use
        assert len(cli._scope_phrase([use])) > len(use.value), use


def test_the_scope_options_help_names_every_use_the_enum_carries(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0133 §6 again, on the surface a user reads *before* choosing.

    The confirmation above is shown once a scope has been named; this is what
    tells them the scope exists at all. A help string enumerating two of three
    uses leaves the third undiscoverable while the option happily accepts it,
    which is the "surface disagreeing with the vocabulary" §6 forbids — and it is
    the failure the type checker cannot see, because the help is a string.
    """
    _wire(monkeypatch, _granting_engine())

    result = CliRunner().invoke(cli.app, ["grant", "--help"])

    assert result.exit_code == 0
    rendered = " ".join(result.output.split())
    for use in GrantScope:
        assert f"'{use.value}'" in rendered, use


def test_yes_supplies_the_answer_and_never_the_rendering(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0073 §5's rule, applied to consent for a *read* rather than a deletion.

    A non-interactive approval must not connect a source the user never saw: `--yes`
    answers the question, and ADR-0102 §6's disclosure happens either way. This is
    the case a "skip the prompt" flag gets wrong by skipping the render with it.
    """
    _wire(monkeypatch, _granting_engine())

    result = CliRunner().invoke(cli.app, ["grant", "calendar", "--scope", "facet", "--yes"])
    assert result.exit_code == 0
    assert "/srv/calendar.ics" in output.getvalue()


def test_a_source_the_enumeration_does_not_carry_is_never_granted(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0102 §6: "a client that cannot show the user the location does not send grant".

    The hub would refuse this call anyway — that is §4, and the shared conformance
    suite holds it. What is asserted here is the *client's* half: nothing is sent at
    all, so the rule holds for the case where the hub's refusal is not what stops
    it — a reader whose configured location has no UTF-8 encoding, which is absent
    from the enumeration for a reason the client cannot see and must not guess at.
    """
    engine = _granting_engine()
    # Held, and **not grantable**: its configured location has no UTF-8 encoding, so
    # the hub omits it from the enumeration (ADR-0102 §6). That is the real cause
    # rather than a name nobody holds, and it is the one the client cannot see: from
    # here "absent" is all there is, which is why §6 fails closed rather than asking
    # the client to reason about why.
    engine.hold_source("notes", location="/srv/\udce9notes.md")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["grant", "notes", "--scope", "facet", "--yes"])
    assert result.exit_code == 1
    assert not [call for call in engine.calls if call[0] == "grant"]
    rendered = output.getvalue()
    assert "cannot offer" in rendered
    assert "calendar" in rendered  # the remedy is the list, not an echo
    assert "/srv/" not in rendered  # and never the path it could not show


def test_a_source_with_no_configured_location_says_so_and_is_still_grantable(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0102 §6: ``None`` means nothing is configured, so the obligation is vacuous.

    Said plainly rather than rendered as a blank, because "reads from:" followed by
    nothing is the shape a user reads as a bug — and this is the case a client must
    distinguish from a source that is absent altogether.
    """
    engine = _granting_engine(location=None)
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["grant", "calendar", "--scope", "facet", "--yes"])
    assert result.exit_code == 0
    assert "no configured location" in output.getvalue()
    assert len(engine.grants_recorded) == 1


def test_revoke_neither_prompts_nor_enumerates_first(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0102 §4: nothing may stand between the user and their remedy.

    **No prompt**, because revoking destroys nothing and is not the ceremony
    ADR-0073 §5 requires of a deletion. **No enumeration**, because that would
    reintroduce client-side exactly the admission check §4 removed — and would fail
    for the one case the removal exists for: a grant whose reader has since been
    unconfigured, which is unrevokable the moment anything checks.
    """
    engine = _granting_engine()
    engine.hold_grant("calendar", scope=[GrantScope.FACET])
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["revoke", "calendar"])
    assert result.exit_code == 0
    assert [call[0] for call in engine.calls] == ["revoke"]
    assert "Withdrawn" in output.getvalue()


def test_revoke_never_claims_to_have_stopped_a_read(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0102 §9, and the sentence a person writes is the one being refused.

    "Your calendar is no longer being read" overclaims: ADR-0097 §5a guarantees
    every read is authorised at the instant it *starts*, and a read already running
    completes on a worker nothing can stop. What is true is that no further read
    starts and nothing a running read produces is used, and the corpus explicitly
    declines to promise more — so the client may not either.
    """
    engine = _granting_engine()
    engine.hold_grant("calendar", scope=[GrantScope.FACET])
    _wire(monkeypatch, engine)

    CliRunner().invoke(cli.app, ["revoke", "calendar"])
    rendered = output.getvalue().lower()
    assert "no further read" in rendered
    assert "still running" in rendered
    assert "no longer being read" not in rendered


def test_revoking_what_is_not_granted_says_so_without_claiming_anything_about_reads(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0102 §9: ``None`` is not silence about reads either.

    It means the source had no live grant at the moment the operation ran, and says
    nothing about what was or was not happening — so "nothing was happening" would
    invent the same overclaim from the other side.
    """
    _wire(monkeypatch, _granting_engine())

    result = CliRunner().invoke(cli.app, ["revoke", "calendar"])
    assert result.exit_code == 1
    rendered = output.getvalue().lower()
    assert "nothing to withdraw" in rendered
    assert "nothing was happening" not in rendered


def test_grants_lists_both_acts_and_points_liveness_elsewhere(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0097 §6 and ADR-0102 §3.

    Both acts are on the record because revoking is an **append**, and the listing
    must not be read as a standing: ADR-0097 §4 permits a revocation timestamped
    before the grant it revokes, so a page ordered by ``decided_at`` can put the two
    out of order. Pointing elsewhere is what keeps that a display oddity rather than
    a wrong answer, and ADR-0139 §3's last clause is why the pointer is now
    ``assistant granted``: ``sources`` answers what *may* be granted, so it misses a
    live grant on a source the hub holds no reader for — exactly the record a reader
    of this page most needs to be sent to.
    """
    engine = _granting_engine()
    granted = engine.hold_grant("calendar", scope=[GrantScope.FACET])
    engine.hold_grant("calendar", scope=[GrantScope.FACET], revokes=granted.id)
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["grants"])
    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "granted" in rendered
    assert "withdrew" in rendered
    assert "assistant granted" in rendered


def test_a_non_positive_grants_limit_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0102 §10: the store requires a strictly positive limit.

    Caught at Typer's parse boundary, so it is exit code 2 rather than a
    ``ValueError`` escaping the command's error boundary as a traceback — the same
    treatment ``--limit 0`` gets nowhere else on this surface, because nowhere else
    is 0 illegal.
    """
    _wire(monkeypatch, _granting_engine())

    result = CliRunner().invoke(cli.app, ["grants", "--limit", "0"])
    assert result.exit_code == 2


# --- what is authorised, and amending it (ADR-0139 §3, §4, §5) ---------------
# ADR-0139's client lane. Every case below is deterministic rather than a timing
# test, which is worth saying because "lose the response" and "cancel mid-call"
# both read like flakes: the scripted engine below *records* the act and then
# raises, which is the stub-hub shape one layer in — the ADR's own note that "what
# is being tested throughout is the client's report, not the socket".


class _ScriptedGrantEngine(FakeAssistantEngine):
    """A hub whose grant acts can be made to fail in each way ADR-0139 §4 names.

    Three arms, because three outcomes have to be reachable and the canonical fake
    reaches only two on its own. ``commit_then_lose`` is the one that could not be
    written any other way: the record lands and the answer does not, which is
    ADR-0085 §8e's residual (#570) and the whole reason the third outcome exists.

    A fourth arm, ``standing_raises``, covers the **read** rather than an act: the
    canonical fake answers ``standing_grants`` from its recorded history and has no
    way to refuse, so the branch ``_drive_standing`` keeps for a store fault and an
    oversized set was reachable from no test at all (#1047).
    """

    def __init__(self) -> None:
        """Create the engine with nothing scripted."""
        super().__init__()
        #: Raised instead of answering ``revoke``, after nothing has been recorded.
        self.revoke_raises: BaseException | None = None
        #: Raised instead of answering ``standing_grants``, having read nothing.
        self.standing_raises: BaseException | None = None
        #: Raised instead of answering ``grant``.
        self.grant_raises: BaseException | None = None
        #: Whether ``grant`` records its grant *before* raising — the hub having
        #: committed and the client having lost the answer.
        self.commit_then_lose = False
        #: Run on the hub once ``revoke`` has done its work, which is where a
        #: **second connected client**'s act lands: between our two calls, on the
        #: hub's side, exactly as ADR-0102 §5 says two clients may.
        self.after_revoke: Callable[[], None] | None = None

    async def standing_grants(self) -> tuple[SourceGrant, ...]:
        """Answer the live set, or refuse it — never answer it partly.

        The call is recorded before the refusal, so a case can tell "asked and was
        refused" from "never asked", which is the difference between the client
        rendering an error and the client having quietly skipped the read.
        """
        if self.standing_raises is not None:
            self.calls.append(("standing_grants", {}))
            raise self.standing_raises
        return await super().standing_grants()

    async def revoke(self, source: str) -> SourceGrant | None:
        """Withdraw, or raise what was scripted before touching anything."""
        if self.revoke_raises is not None:
            self.calls.append(("revoke", {"source": source}))
            raise self.revoke_raises
        withdrawn = await super().revoke(source)
        if self.after_revoke is not None:
            self.after_revoke()
        return withdrawn

    async def grant(self, source: str, *, scope: Sequence[GrantScope]) -> SourceGrant:
        """Record and answer, record and lose the answer, or refuse outright."""
        if self.grant_raises is not None:
            self.calls.append(("grant", {"source": source}))
            if self.commit_then_lose:
                self.hold_grant(source, scope=scope)
            raise self.grant_raises
        return await super().grant(source, scope=scope)


def _amendable_engine() -> _ScriptedGrantEngine:
    """A hub holding one grantable source, already granted for one use."""
    engine = _ScriptedGrantEngine()
    engine.hold_source("calendar", location="/srv/calendar.ics")
    engine.hold_grant("calendar", scope=[GrantScope.FACET, GrantScope.INGEST])
    return engine


def test_granted_lists_a_grant_whose_source_the_hub_no_longer_holds(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §1 and §3: the set is presented whole, from the store.

    The whole point of the command in one case. ``journal`` has a live grant and no
    held reader — an operator unset its path — so it is absent from
    ``grantable_sources`` and was reported by nothing. A client that annotated this
    list against the enumeration, or dropped what the enumeration did not carry,
    would hide it again, so the assertion is that **one** call goes out and the
    unheld source is in what comes back.
    """
    engine = _granting_engine()
    engine.hold_grant("journal", scope=[GrantScope.INGEST])
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["granted"])
    assert result.exit_code == 0
    assert [call[0] for call in engine.calls] == ["standing_grants"]
    rendered = output.getvalue()
    assert "journal" in rendered
    assert "durably remembering what it says" in rendered


def test_granted_renders_exactly_the_uses_a_grant_names(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §3's third clause, which is the half a well-meaning view gets wrong.

    A ``FACET``-only grant renders as ``FACET`` and **nothing else**: adding the
    members it leaves out — greyed out, or listed as not yet allowed — presents the
    user's decision as a half-filled form, which is a nudge toward a wider grant on
    the one surface whose subject is what they actually decided. The whole
    vocabulary belongs in the *choice* context, which is ``--scope``'s help, and
    that is asserted separately below.
    """
    engine = _granting_engine()
    engine.hold_grant("calendar", scope=[GrantScope.FACET])
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["granted"])
    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "looking at it while answering" in rendered
    assert "durably remembering" not in rendered
    assert "raise things with you unprompted" not in rendered


def test_granted_says_nothing_about_configuration_or_about_reads(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §3's fourth clause and §6's second.

    "Your calendar is not being read" is the sentence a person writes and it is a
    true sentence about the wrong axis — the source's *configuration* state
    presented where consent is being decided, which ADR-0093 §7 exists to keep
    apart. So no configured location appears here at all, and nothing claims a read
    happened or did not. Both are asserted negatively because both are what an
    author adds when the list looks sparse.
    """
    engine = _granting_engine()
    engine.hold_grant("calendar", scope=[GrantScope.FACET])
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["granted"])
    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "/srv/calendar.ics" not in rendered
    assert "not being read" not in rendered
    assert "last read" not in rendered


def test_granted_on_an_empty_store_offers_nothing_as_already_granted(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty set is an answer, and it is not the other question's answer.

    ADR-0139 §3 forbids presenting a standing grant as a source the user may grant;
    the mirror error on an empty set is to fill the space with the grantable list,
    which would answer "what may I grant" under a heading that asked something else.
    Pointing at the command that does answer it is the whole of what is offered.
    """
    _wire(monkeypatch, _granting_engine())

    result = CliRunner().invoke(cli.app, ["granted"])
    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "have not granted anything" in rendered
    assert "assistant sources" in rendered
    assert "calendar" not in rendered


def test_granted_reports_a_store_that_could_not_answer_and_lists_nothing(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read that failed is a failure, not an empty authorization set (#1047).

    ``GrantError`` is the store fault, and ADR-0097 §5a's "a driver that cannot get
    an answer fails closed" is stated on the error itself because the tempting
    reading is the other one. Here the tempting reading has a second face: a client
    that caught the refusal and fell through to the renderer would print the empty
    set's wording — telling a user who authorises three sources that they have
    authorised none, on the one surface whose subject is what they decided.
    """
    engine = _amendable_engine()
    engine.standing_raises = GrantError("the grant store could not be opened")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["granted"])

    assert result.exit_code == 1
    rendered = output.getvalue()
    assert "the grant store could not be opened" in rendered
    assert "have not granted anything" not in rendered
    assert "calendar" not in rendered
    assert [call[0] for call in engine.calls] == ["standing_grants"]


def test_granted_reports_a_set_too_large_to_carry_rather_than_a_page_of_it(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §2's refusal has to survive as far as the terminal (#1047).

    The clause is that a frame too small for the live set reaches the user as a
    **refusal**, never as an empty or partial list, because "a page of what you
    authorise reads as complete while omitting an authorisation". The engine half
    is pinned against all three implementations by the shared conformance suite
    (``test_standing_grants_refuses_an_oversized_set_rather_than_truncating_it``);
    what had no test is the last hop, where a client that swallowed
    ``OversizedValueError`` would invert the clause exactly — and would invert it
    with a green suite, because the exit code is not what is wrong in that world.

    So the assertion that carries this case is the **absence** of the empty-set
    wording, not the presence of the exit code.
    """
    engine = _amendable_engine()
    engine.standing_raises = OversizedValueError(
        "the live set does not fit in one frame",
        limit=65024,
        size=70112,
    )
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["granted"])

    assert result.exit_code == 1
    rendered = output.getvalue()
    assert "does not fit in one frame" in rendered
    assert "have not granted anything" not in rendered
    assert "calendar" not in rendered
    assert [call[0] for call in engine.calls] == ["standing_grants"]


def test_amend_renders_the_location_before_it_asks_and_before_it_revokes(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §5 over ADR-0102 §6, and §4's sixth clause in the same case.

    Two orderings are asserted at once and both are the point. The **location** is
    on screen when the question is asked, because the granting half of an amendment
    is a ``grant`` and §6's disclosure applies to it unchanged — an amendment is
    exactly where a client author reasons that the user already consented and skips
    it. And **nothing has been withdrawn** at that moment: a surface that revoked
    first and then asked would put the interactive part of the flow inside the
    ungranted window, so a user who hesitates has withdrawn their grant by starting
    to think.

    Read from inside the approver, which is the only vantage point from which
    "before" is observable at all.
    """
    engine = _amendable_engine()
    _wire(monkeypatch, engine)
    seen: list[tuple[str, list[str]]] = []

    def approve(source: object) -> bool:
        seen.append((output.getvalue(), [call[0] for call in engine.calls]))
        return True

    monkeypatch.setattr(cli, "_confirm_amendment", approve)

    result = CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify"])
    assert result.exit_code == 0
    assert len(seen) == 1
    at_prompt, calls_so_far = seen[0]
    assert "/srv/calendar.ics" in at_prompt
    assert "revoke" not in calls_so_far
    assert "grant" not in calls_so_far


def test_amend_issues_the_two_acts_in_order_and_reports_each(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §4's first two clauses: two acts, two records, two reports.

    No compound operation is sent — ADR-0102 §1 refuses one and §4 re-refuses it —
    and the state between them is reported rather than hidden, which is the reason
    the composition is the client's in the first place. The closing statement of
    what the source is now allowed comes from ``standing_grants``, never from
    either act's return value (§4's third clause).
    """
    engine = _amendable_engine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify", "--yes"])
    assert result.exit_code == 0
    assert [call[0] for call in engine.calls] == [
        "grantable_sources",
        "revoke",
        "grant",
        "standing_grants",
    ]
    rendered = output.getvalue()
    assert "withdrawal landed" in rendered
    assert "grant landed" in rendered
    assert "raise things with you unprompted" in rendered


def test_amend_reports_a_refused_grant_as_failed_and_reads_the_state(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §4's second and third clauses, on the branch that is *known*.

    A hub that answered with a refusal wrote nothing, so the act is known not to
    have landed — and that is still not a statement about the **source**. The user
    is in the state the whole section exists for: their grant is gone and the new
    one did not arrive, and being told so is what makes it recoverable in one
    command.
    """
    engine = _amendable_engine()
    engine.grant_raises = UngrantableSourceError("no source by that name can be granted")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify", "--yes"])
    assert result.exit_code == 1
    assert [call[0] for call in engine.calls] == [
        "grantable_sources",
        "revoke",
        "grant",
        "standing_grants",
    ]
    rendered = output.getvalue()
    assert "known not to have landed" in rendered
    assert "allowed nothing" in rendered  # read, not inferred


def test_amend_states_the_source_from_the_re_read_when_another_client_raced_it(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §4's third clause, on the case that makes the inference false.

    An earlier draft of that ADR said a grant known not to have landed means the
    source is ungranted. It does not: ADR-0102 §5 lets two clients be connected at
    once and makes the store the arbiter, so an ``InvalidGrantError`` is raised
    *because another client's grant is live* — and "the source is now ungranted" is
    false in the one case that produced the refusal.

    Here the other client's grant is already in the store when ours is refused, so
    a client reasoning from the refusal says the wrong thing and a client that reads
    says the right one.
    """
    engine = _amendable_engine()
    engine.grant_raises = InvalidGrantError("the source already has a live grant")

    # The competing act lands **between** our two calls, which is the only placement
    # that produces the case: earlier and our own revocation withdraws it again.
    def another_client_grants() -> None:
        engine.hold_grant("calendar", scope=[GrantScope.INGEST])

    engine.after_revoke = another_client_grants
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify", "--yes"])
    assert result.exit_code == 1
    rendered = output.getvalue()
    assert "known not to have landed" in rendered
    assert "durably remembering what it says" in rendered
    assert "nothing is granted on it" not in rendered


def test_amend_reports_a_lost_grant_response_as_not_known(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §4's second clause, and the outcome a two-outcome report cannot say.

    The hub commits the record and the answer is lost on the way back — ADR-0085
    §8e's residual, tracked as #570. "It failed" is false and "it worked" is
    unknowable, so the honest report is that the outcome is not known, and the
    re-read is what resolves it. The re-read is asserted to find the grant, because
    a report that said "not known" and then stopped would leave the user exactly
    where the clause is trying to get them out of.
    """
    engine = _amendable_engine()
    engine.grant_raises = TransportError("the hub closed the connection")
    engine.commit_then_lose = True
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify", "--yes"])
    assert result.exit_code == 1
    rendered = output.getvalue()
    assert "not known" in rendered
    assert "known not to have landed" not in rendered
    assert "raise things with you unprompted" in rendered  # the committed grant, read back


def test_amend_sends_no_grant_when_the_revocations_outcome_is_not_known(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §4's fourth clause: stop, and resolve by reading rather than writing.

    A client whose revocation is unresolved could send the grant anyway and reason
    backwards — refused means the revocation did not land, accepted means it did.
    That is the inference the third clause forbids and for the same reason: a
    refusal is equally consistent with another client having granted in between. One
    read settles it; a second write does not.
    """
    engine = _amendable_engine()
    engine.revoke_raises = TransportError("the hub closed the connection")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify", "--yes"])
    assert result.exit_code == 1
    assert [call[0] for call in engine.calls] == [
        "grantable_sources",
        "revoke",
        "standing_grants",
    ]
    rendered = output.getvalue()
    assert "not known" in rendered
    assert "sent no new grant" in rendered


@pytest.mark.parametrize("act", ["revoke", "grant"])
def test_a_cancelled_amendment_reports_the_act_starts_nothing_and_propagates(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, act: str
) -> None:
    """ADR-0139 §4's fifth clause, written once per act as §8 requires.

    Three assertions rather than one, because the clause has three limbs and the
    natural implementations breach a different one each. ``CancelledError`` is a
    ``BaseException``, so an ``except Exception`` around the two calls does not see
    it and the client exits reporting nothing — the limb the **report** covers.
    Catching it and carrying on to print leaves a task the caller believes it
    cancelled, which ADR-0060 forbids — the limb the **propagation** covers. And
    reaching for the state in order to report it is the same breach by a kinder
    route: ADR-0060 permits deferring a cancellation only while a method makes its
    resources safe, and a read performed to present a state is not that — the limb
    **no further call** covers.
    """
    engine = _amendable_engine()
    setattr(engine, f"{act}_raises", asyncio.CancelledError())
    _wire(monkeypatch, engine)

    # It reaches the caller rather than being reported and swallowed. ``CliRunner``
    # catches ``Exception`` and nothing wider, so a ``BaseException`` arriving here
    # *is* the propagation ADR-0060 requires — and a client that caught it in order
    # to print would fail this line rather than the ones below.
    with pytest.raises(asyncio.CancelledError):
        CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify", "--yes"])

    assert "standing_grants" not in [call[0] for call in engine.calls]
    rendered = output.getvalue()
    assert "not known" in rendered
    assert "not read what" in rendered


def test_amend_is_refused_for_a_source_the_enumeration_does_not_carry(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §5: a client that cannot show the location does not send ``grant``.

    And therefore does not revoke either, because revoking here would leave the
    user strictly worse off than not running the command: the old grant gone and
    no new one possible. The remedy is named instead — ``revoke`` applies no
    admission check (ADR-0102 §4), so the user's whole remedy is untouched by a
    source having stopped being offered.
    """
    engine = _ScriptedGrantEngine()
    engine.hold_source("calendar", location="/srv/calendar.ics")
    engine.hold_grant("journal", scope=[GrantScope.INGEST])
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["amend", "journal", "--scope", "facet", "--yes"])
    assert result.exit_code == 1
    assert [call[0] for call in engine.calls] == ["grantable_sources"]
    rendered = output.getvalue()
    assert "cannot amend" in rendered
    assert "assistant revoke journal" in rendered


def test_the_amend_scope_option_names_every_use_the_type_admits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0139 §3's second clause, over ADR-0133 §6's CLI obligation.

    Wherever a surface offers, enumerates or explains the uses a user may choose
    among, it carries **every** member of ``GrantScope``, named in words. An
    amendment is a choice context, and a help string enumerating two of three uses
    is a surface disagreeing with the vocabulary — deciding on the user's behalf
    what they may permit, which is what ADR-0097 §8 forbids.
    """
    _wire(monkeypatch, _amendable_engine())

    result = CliRunner().invoke(cli.app, ["amend", "--help"])
    assert result.exit_code == 0
    help_text = re.sub(r"\s+", " ", result.output)
    assert "facet" in help_text
    assert "ingest" in help_text
    assert "notify" in help_text


# --- id arguments refuse at the parse boundary (ADR-0042 §7, ADR-0085 §3c) ---
# ADR-0085 §3c binds *every* engine implementation to ``Identifier`` validation
# "before any I/O", and its refusal is a ``ValueError`` — neither an
# ``AssistantError`` nor a ``TransportError``, so on each parameter below it escaped
# the command's error boundary as a traceback with exit 1 (#705). The subject here is
# ``FakeAssistantEngine`` rather than a permissive stand-in precisely because the fake
# enforces that clause through the same ``orchestration.payloads.identifier`` a hub
# client does: these cases reproduce the traceback, they do not merely assert a nicer
# exit code against a double that would have accepted anything.


def _id_invocations(value: str) -> tuple[tuple[str, list[str]], ...]:
    """Every parameter on this surface that carries an identifier, invoked with ``value``.

    Six, not the five #705 enumerates: ``observe``'s is an *optional positional*, so
    it reads like a flagless default rather than an id and was missed. Named so a
    failure says which command failed.
    """
    return (
        ("forget", ["forget", value, "--yes"]),
        ("answer", ["answer", value, "--accept"]),
        ("forget-question", ["forget-question", value]),
        ("forget-conversation", ["forget-conversation", value, "--yes"]),
        ("observe", ["observe", value]),
        ("ask --conversation", ["ask", "hello", "--conversation", value, "--yes"]),
        ("dismiss", ["dismiss", value]),
        ("forget-notification", ["forget-notification", value]),
        # `tune --class` is the second id-shaped parameter spelled without an `_id`
        # suffix, so the walk below cannot see it and this list is where it is held
        # — the residual that walk's own docstring names.
        ("tune --class", ["tune", "--class", value, "--reach", "interrupt"]),
    )


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_every_id_argument_refuses_a_blank_before_any_client_is_built(
    blank: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blank id is a usage error (exit 2), never a traceback (ADR-0042 §7).

    ``_non_blank`` rejects it with a ``ValueError``, which every implementation
    raises before any I/O — so it arrives *inside* the command's
    ``except (AssistantError, TransportError)`` boundary and is caught by neither.
    Refusing during Typer's parameter parsing makes it a usage error instead, the
    treatment blank ``learn`` content and a blank ``source`` already get.

    **And no client is opened**, which is the half this case's name promised and did
    not check (#728). Exit 2 alone is passed by a refusal that first built a client
    and probed the hub; the recorded opens are what say the refusal happened at the
    parse boundary, where ADR-0085 §3c's "before any I/O" puts it.
    """
    opened = _wire_recording_opens(monkeypatch, FakeAssistantEngine())

    for name, argv in _id_invocations(blank):
        result = CliRunner().invoke(cli.app, argv)
        assert result.exit_code == 2, name
        assert result.exception is None or isinstance(result.exception, SystemExit), name
        assert opened == [], name


def test_every_id_argument_refuses_a_value_with_no_utf8_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r"""A lone surrogate is refused at the parse boundary, and is not echoed back.

    Linux passes argv as bytes and Python decodes it with ``surrogateescape``, so
    ``assistant forget $'\xe9'`` arrives as half a character — a value
    ``EncodableText`` refuses and ADR-0087's encoder has no form for. Without the
    callback that refusal lands as the same uncaught ``ValueError`` a blank does.

    **The message does not echo the value**, which is a practical necessity rather
    than a policy borrowed from ``_present_source``: a value with no UTF-8 encoding
    is one this process may not be able to write down, so reporting the fault would
    fail the same way the fault does.

    **And, as with a blank, no client is opened** (#728): the value has no UTF-8
    encoding, so a command that reached the hub with it would have to write it down
    somewhere on the way — which is the failure, not the report of it.
    """
    opened = _wire_recording_opens(monkeypatch, FakeAssistantEngine())
    unwritable = "\udce9"

    for name, argv in _id_invocations(unwritable):
        result = CliRunner().invoke(cli.app, argv)
        assert result.exit_code == 2, name
        assert unwritable not in result.output, name
        assert opened == [], name


def test_an_id_is_stripped_before_it_is_looked_up_or_reported(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0085 §3c normalises an identity argument; this adapter does it too.

    The asymmetry with ``_present_source`` is the decision rather than an
    inconsistency. §3c makes stripping *contractual* for an identity argument,
    because "optional normalisation on an identity argument is worse than none: it
    makes the answer to ``belief(" rec-1 ")`` a property of which implementation you
    are holding" — where ADR-0102 §2 keeps a grant's ``source`` byte-exact so a name
    differing only by surrounding whitespace is refused rather than matched.

    Doing it here rather than leaving it to the implementation is what keeps the
    report honest: the id this module holds is the one it prints back, so an
    adapter that relayed ``"  no-such  "`` would report the lookup against a string
    the engine never used.
    """
    _wire(monkeypatch, FakeAssistantEngine())

    result = CliRunner().invoke(cli.app, ["forget", "  no-such  ", "--yes"])

    assert result.exit_code == 1  # an id naming no live belief, not a usage error
    assert "the id no-such." in output.getvalue()


def test_an_omitted_optional_id_still_means_no_conversation_was_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``None`` is the "no conversation named" state and must survive the callback.

    The one thing ``_present_optional_id`` must not do is turn an absent id into a
    blank one — which would make ``assistant observe`` refuse itself, and
    ``assistant ask`` unable to start a conversation at all.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, ["observe"]).exit_code == 0
    assert CliRunner().invoke(cli.app, ["ask", "hello", "--yes"]).exit_code == 0
    assert [call for call in engine.calls if call[0] == "observe"] == [
        ("observe", {"conversation_id": None})
    ]
    streamed = [call for call in engine.calls if call[0] == "converse_streaming"]
    assert [call[1]["conversation_id"] for call in streamed] == [None]


def test_every_id_parameter_on_the_surface_carries_an_id_callback() -> None:
    """The obligation is stated over the app rather than over a list someone kept.

    #705 happened because five parameters were given a bare ``typer.Argument`` and
    nothing said a sixth existed. Walking the registered commands closes both halves
    of that: a parameter that loses its callback fails here rather than in a user's
    terminal, and a *seventh* fails too — deliberately, because the list
    :func:`_id_invocations` keeps is the one that goes stale, and this is what sends
    its author to it.

    **It catches the naming convention this surface follows, not every conceivable
    parameter.** An id spelled without an ``_id`` suffix — as ``ask``'s
    ``--conversation`` is — has to be recognised by name here, and a second such
    spelling would slip the walk. That residual is why the behavioural cases above
    enumerate the six explicitly rather than deriving them from this.
    """
    group = typer.main.get_command(cli.app)
    assert isinstance(group, TyperGroup)
    id_callbacks = {cli._present_id, cli._present_optional_id}

    # Typer wraps a parameter callback in a click-shaped adapter, so the function
    # itself is reached through ``__wrapped__`` rather than compared directly. A
    # parameter with no callback at all — #705's state — unwraps to nothing and is
    # recorded as False rather than skipped.
    carried = {
        f"{name}:{param.name}": param.callback is not None
        and unwrap(param.callback) in id_callbacks
        for name, command in sorted(group.commands.items())
        for param in command.params
        if str(param.name).endswith("_id") or param.name == "conversation"
    }

    # Asserted as a mapping rather than with `all(...)`, so a failure names the
    # parameter that is missing its callback instead of reporting `False`.
    assert carried == {
        "answer:question_id": True,
        "ask:conversation": True,
        "dismiss:notification_id": True,
        "forget:belief_id": True,
        "forget-conversation:conversation_id": True,
        "forget-notification:notification_id": True,
        "forget-question:question_id": True,
        "observe:conversation_id": True,
    }


# --- the notification surface (ADR-0130 §6, §7, §9) -------------------------
# The five operations §9 ratifies, and the door #979 found missing: every clause
# below was implemented and conformance-tested on the contract, and none of it
# was reachable, so the tuning act §6 requires of the user could not be performed
# and — every class defaulting to `hold` — nothing could ever interrupt.


def _flowed(rendered: str) -> str:
    """Rich wraps at the fixture's console width, so an assertion reads the flowed text.

    A command line printed as a hint is exactly the sort of string that straddles a
    wrap, and a test matching only what fits on one line pins the console width
    rather than the message.
    """
    return " ".join(rendered.split())


def _pasted(rendered: str, start: str, until: str) -> list[str]:
    """One printed command hint, read back the way a shell would read it (#984).

    The check every quoting case here wants: not "are there quote characters", which
    would pin whichever form ``shlex.quote`` happens to pick, but "does pasting this
    line name the thing it was printed for". A hint whose argument is unquoted parses
    into *more* words than it should, which is the failure — a valid command against
    the wrong argument rather than an error.

    Bounded at both ends rather than run to the end of the buffer, because the flowed
    text that follows a hint is prose: an apostrophe in it would leave ``shlex`` with
    an unterminated quote and fail every test for the wrong reason.

    Args:
        rendered: The console text, already flowed by :func:`_flowed`.
        start: The first word of the hint, where the slice opens.
        until: The first text after the hint, where the slice closes.

    Returns:
        The hint's words, as a shell would split them.
    """
    opened = rendered.index(start)
    return shlex.split(rendered[opened : rendered.index(until, opened)])


def _candidate(**overrides: object) -> NotificationCandidate:
    """A producer's proposal, with the fields a surface renders already set."""
    fields: dict[str, object] = {
        "candidate_key": "key-1",
        "producer": "calendar-upcoming",
        "notification_class": "upcoming_event",
        "summary": "Standup starts in ten minutes",
        "noticed_at": AT,
        "confidence": 0.9,
        "sensitivity": DataTier.PERSONAL,
    }
    return NotificationCandidate(**(fields | overrides))  # type: ignore[arg-type]


def _held(**overrides: object) -> HeldNotification:
    """A record held because its class is not set to interrupt — #979's own case.

    **The candidate declares an expiry, and that is not decoration.** ADR-0130 §5
    makes declaring one the whole of the escalation test, so a record with none fails
    ``PERISHABLE`` as well and the engine could never produce a failed set of
    ``(REACH_INTERRUPT,)`` alone. Building the fixture without an expiry made every
    case here a state no policy emits — and hid the one where the reach hint is a
    promise nothing can keep (:func:`_perishing`'s sibling below).

    ``reconsider_at`` stays ``None`` and that *is* the point of the example: reach is
    not a condition time resolves, so this record cannot free itself and the user's
    act is the only thing that moves it.
    """
    fields: dict[str, object] = {
        "id": "ntf-1",
        "candidate": _candidate(expires_at=AT + timedelta(hours=1)),
        "kind": NotificationDispositionKind.HOLD,
        "reason": NotificationCondition.REACH_INTERRUPT,
        "failed": (NotificationCondition.REACH_INTERRUPT,),
        "ruled_at": AT,
        "admitted_at": AT,
        "retention": timedelta(days=7),
    }
    return HeldNotification(**(fields | overrides))  # type: ignore[arg-type]


def _never_urgent(**overrides: object) -> HeldNotification:
    """The state an engine actually emits for a candidate that declares no expiry.

    Two failing conditions in ``INTERRUPT_CONDITIONS`` order, ``PERISHABLE`` first and
    therefore the reason — verified against ``FakeNotificationPolicy``, which is the
    conformance-tested ruling. No reach setting removes the first of them (§5, §6).
    """
    fields: dict[str, object] = {
        "candidate": _candidate(expires_at=None),
        "reason": NotificationCondition.PERISHABLE,
        "failed": (
            NotificationCondition.PERISHABLE,
            NotificationCondition.REACH_INTERRUPT,
        ),
    }
    return _held(**(fields | overrides))


def test_a_held_notification_renders_what_it_says_and_what_it_belongs_to(
    output: StringIO,
) -> None:
    """ADR-0130 §7: the explicit enumeration is the only way a held record reaches a user.

    So it has to carry everything the act needs: the words the producer wrote, the
    class ``assistant tune`` takes, and the id the two disposing verbs take. A
    listing missing the class is the one #978 drove around with a throwaway wire
    driver, because there was nothing on screen to type.
    """
    cli._render_notifications((_held(),), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "ntf-1" in rendered
    assert "Standup starts in ten minutes" in rendered
    assert "upcoming_event" in rendered
    assert "calendar-upcoming" in rendered


def test_a_hold_is_explained_by_its_whole_failed_set_and_not_by_its_reason_alone(
    output: StringIO,
) -> None:
    """ADR-0130 §5: ``reason`` is the failed set's *first* member, not its only one.

    A record held behind a quiet window whose budget is also spent has two answers
    to "why did you not tell me?", and both are things the user would have to
    change. Rendering the first alone is a true answer arranged into a misleading
    one — the same failure §6 names when it makes the setting-change rule read the
    whole set rather than the recorded first reason.
    """
    cli._render_notifications(
        (
            _held(
                reason=NotificationCondition.QUIET_WINDOW,
                failed=(NotificationCondition.QUIET_WINDOW, NotificationCondition.BUDGET),
                reconsider_at=AT + timedelta(hours=2),
            ),
        ),
        now=AT,
        limit=50,
        offset=0,
    )

    rendered = _flowed(output.getvalue())
    assert "quiet hours" in rendered
    assert "budget" in rendered


def test_an_expired_record_is_still_listed_and_renders_as_expired(output: StringIO) -> None:
    """ADR-0130 §7: expiry ends a notification's actionability and **deletes nothing**.

    So the record stays enumerable — and the listing has to say which side of that
    line it is on, because "renders as expired" is the clause and no field on the
    record answers it. What the surface supplies is the clock reading; the boundary
    itself is ``NotificationCandidate.is_perishable_at``'s, spelled once in ``core``
    so a policy, a store and a listing cannot disagree about it.

    Both halves are asserted: the row is present (a listing that hid it would breach
    "stays enumerable"), and it is marked (a listing that showed only the timestamp
    would leave a person reading a live-looking notification about a moment that has
    gone — which is the state #978 found the record sitting in).
    """
    long_past = AT - timedelta(days=400)
    cli._render_notifications(
        (
            _held(
                candidate=_candidate(
                    noticed_at=long_past - timedelta(hours=1), expires_at=long_past
                )
            ),
        ),
        now=AT,
        limit=50,
        offset=0,
    )

    rendered = _flowed(output.getvalue())
    assert "ntf-1" in rendered
    assert "Expired" in rendered
    assert cli._when(long_past) in rendered


def test_a_record_whose_moment_is_still_ahead_is_not_called_expired(output: StringIO) -> None:
    """The other side of the same boundary, at the instant §5 fixes it.

    ``is_perishable_at`` is half-open in the direction §5 states — **at**
    ``expires_at`` the candidate has perished — so a record judged one moment before
    its expiry is live and one judged at it is not. Pinning both sides is what stops
    an off-by-one that would label every notification expired the moment it arrives.
    """
    expires = AT + timedelta(minutes=10)
    live = _held(candidate=_candidate(expires_at=expires))

    cli._render_notifications((live,), now=AT, limit=50, offset=0)
    ahead = _flowed(output.getvalue())

    assert "Expires:" in ahead
    assert "Expired" not in ahead


def test_an_expired_record_is_offered_no_act_because_the_engine_would_decline_it(
    output: StringIO,
) -> None:
    """ADR-0130 §7 makes expiry one of the three ways actionability ends.

    ``dismiss_notification`` answers ``False`` for an expired record, so a hint beside
    one is a surface promising what the engine will not do. The check asks the record
    (``is_actionable_at``) rather than reading the two stamps: a version testing only
    ``dismissed_at`` and ``dropped_at`` passes every other case here and fails exactly
    this one.
    """
    long_past = AT - timedelta(days=400)
    cli._render_notifications(
        (
            _held(
                candidate=_candidate(
                    noticed_at=long_past - timedelta(hours=1), expires_at=long_past
                )
            ),
        ),
        now=AT,
        limit=50,
        offset=0,
    )

    rendered = _flowed(output.getvalue())
    assert "assistant dismiss" not in rendered
    assert "assistant tune --class" not in rendered


@pytest.mark.parametrize(
    ("name", "overrides"),
    [
        ("dismissed", {"dismissed_at": AT + timedelta(minutes=5)}),
        (
            "ruled out",
            {
                "kind": NotificationDispositionKind.DROP,
                "reason": NotificationCondition.REACH_OFF,
                "failed": (),
                "dropped_at": AT + timedelta(minutes=5),
            },
        ),
    ],
)
def test_a_stamped_cessation_ends_the_offer_whatever_this_devices_clock_reads(
    name: str, overrides: dict[str, object], output: StringIO
) -> None:
    """A client behind the hub must not offer an act on a record the hub already closed.

    Dismissal and a reconsideration's ``DROP`` are **persisted**: the hub stamped
    them, so that they happened is not something this device's clock has a view on.
    Judging them against the local reading — which one ``is_actionable_at(now)`` call
    for all three limbs would do — makes a client running five minutes behind render
    the "Dismissed:" stamp *and*, two lines under it, offer ``assistant dismiss``,
    which the engine answers ``False`` for.

    The stamps here are deliberately **after** ``now``, which is exactly the skew this
    is about and a state the equal-timestamp cases elsewhere cannot reach.
    """
    cli._render_notifications((_held(**overrides),), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "ntf-1" in rendered, name
    assert "assistant dismiss" not in rendered, name
    assert "assistant tune --class" not in rendered, name


def test_a_pasted_hint_sets_the_class_it_names_even_when_that_class_has_a_space(
    output: StringIO,
) -> None:
    """A hint meant to be pasted has to survive being pasted.

    Neither ``Identifier`` nor ``NonBlankEncodableText`` forbids an interior space, so
    an unquoted hint for a class named ``calendar upcoming`` reads as a *valid*
    command that sets a different class — a wrong action, not an error. ``_safe``
    answers a different question (Rich markup and control characters), so quoting
    happens first and the escaped text is the quoted form.

    Asserted by parsing the rendered line the way a shell would, rather than by
    matching quote characters, so it holds whichever quoting form ``shlex`` picks.
    """
    spaced = _held(id="ntf 1", candidate=_candidate(notification_class="calendar upcoming"))

    cli._render_notifications((spaced,), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    dismiss = shlex.split(rendered[rendered.index("assistant dismiss") :].split("  ")[0])
    assert dismiss[:3] == ["assistant", "dismiss", "ntf 1"]
    tune = shlex.split(rendered[rendered.index("assistant tune") :])
    assert tune[:5] == ["assistant", "tune", "--class", "calendar upcoming", "--reach"]


def test_a_long_command_hint_is_not_folded_at_the_console_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1023: Rich folds by inserting a real newline, so a folded hint pastes as two.

    Rich wraps at the console's width by writing an actual line break into the
    output rather than leaving the terminal to fold the line, so at a narrow width
    ``assistant dismiss <long id>`` arrives on screen as ``assistant dismiss`` and
    then the id — and copying it runs a dismissal with no argument followed by the
    id as a command of its own. Where the argument is quoted the break lands *inside*
    the quotes instead, and the command then names a value with a newline in it.
    Nothing bounds these values: ``Identifier`` and ``NonBlankEncodableText`` require
    non-blankness and encodability and nothing else.

    Read off the **raw** buffer at a deliberately narrow width, because
    :func:`_flowed` re-joins wrapped output and a test written through it cannot see
    this at any width. The prose is asserted in the same breath and in the opposite
    direction: what is turned off is the wrapping of the lines carrying commands, not
    the console's wrapping, and a fix that stopped wrapping everything would pass a
    test that only looked at the hint.
    """
    width = 40
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=width))
    identifier = f"ntf-{'a' * 60}"

    cli._render_notifications((_held(id=identifier),), now=AT, limit=50, offset=0)

    lines = buffer.getvalue().splitlines()
    hints = [line for line in lines if "assistant " in line]
    assert [shlex.split(line[line.index("assistant ") :]) for line in hints] == [
        ["assistant", "dismiss", identifier],
        ["assistant", "tune", "--class", "upcoming_event", "--reach", "interrupt"],
    ], "each hint is one whole line, and pastes as the one command it names"
    assert max(len(line) for line in lines if line not in hints) <= width, (
        "the prose around them still wraps to the console"
    )


def test_the_hint_printer_leaves_the_line_for_the_terminal_to_fold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The decision #1023 asks to be taken once, asserted where it is taken.

    Twelve sites print a copyable command and all of them go through
    :func:`~ai_assistant.interfaces.cli._print_hint`; this is what that function
    promises them. ``soft_wrap`` rather than an ``overflow`` or ``crop`` setting is
    the load-bearing half — those **truncate** a line too long for the console, which
    would turn a command that pastes wrongly into one that pastes silently short, and
    a truncated hint is the one failure mode worse than a folded one.
    """
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=20))
    line = "assistant dismiss " + "x" * 200

    cli._print_hint(line)

    assert buffer.getvalue() == f"{line}\n", "neither folded nor truncated"


def test_every_renderer_that_builds_a_command_prints_it_through_the_hint_printer() -> None:
    """The other half of #1023's "deciding once", which no rendering case can reach.

    Twelve prints carry a copyable command and the two cases above exercise two of
    them; a lane that reverted any of the other ten to a bare ``console.print``
    would leave both of them green and would restore the fold on that surface. So
    the routing is asserted structurally instead, over the module's own syntax
    tree — the only vantage point from which "every site" is a statement rather
    than a list somebody keeps up to date.

    The rule is read off what a function *does* rather than off a roster of names:
    a renderer that composes a shell argument (:func:`~ai_assistant.interfaces.cli
    ._argument`) or a reference hint and then prints anything at all is offering a
    command to copy, and has to offer it unfolded. :func:`~ai_assistant.interfaces
    .cli._reference_hint` composes one and prints nothing, so it is not a renderer
    and is excluded by that same test rather than by an exemption.

    It cannot see a renderer that prints the *prose around* a hint through
    ``console.print`` — which is correct, and is what those calls are for — so the
    two rendering cases above stay the pin on what reaches the buffer.
    """
    source = Path(cli.__file__).read_text(encoding="utf-8")

    def _called(node: ast.AST) -> set[str]:
        names: set[str] = set()
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            called = inner.func
            if isinstance(called, ast.Name):
                names.add(called.id)
            elif isinstance(called, ast.Attribute) and isinstance(called.value, ast.Name):
                names.add(f"{called.value.id}.{called.attr}")
        return names

    unfolded: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        calls = _called(node)
        composes = {"_argument", "_reference_hint"} & calls
        prints = {"console.print", "_print_hint"} & calls
        if composes and prints and "_print_hint" not in calls:
            unfolded.append(f"{node.name} (line {node.lineno})")

    assert not unfolded, f"builds a command and prints it folded: {unfolded}"


def test_a_candidate_with_no_expiry_says_why_that_makes_it_unurgent(output: StringIO) -> None:
    """ADR-0130 §5: declaring an expiry **is** the escalation test.

    A candidate that commits to no moment fails ``PERISHABLE``, which is why it is
    held rather than dropped and why no setting can make it due. Rendering the
    absence as a blank would leave the user tuning a class that was never going to
    interrupt whatever they set.
    """
    cli._render_notifications((_never_urgent(),), now=AT, limit=50, offset=0)

    assert "never" in _flowed(output.getvalue())


def test_a_record_no_setting_can_free_is_not_offered_a_reach_raise(
    output: StringIO,
) -> None:
    """ADR-0130 §6: "a record whose set holds only the expiry condition is reached by
    no setting", and §5 is why.

    The engine's own ruling for a candidate with no expiry fails ``PERISHABLE`` *and*
    ``REACH_INTERRUPT``, so a hint reading only the second offers a raise that re-arms
    the record, runs a reconsideration, and re-holds it on the condition nothing can
    remove — an interruption promised and never delivered, which is #979's failure
    wearing the opposite face.

    What is offered instead: dismissal, the lowering act (which still does something),
    and the reason in words, because a user who performed the act and heard nothing
    would reasonably conclude the act had failed.
    """
    cli._render_notifications((_never_urgent(),), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "assistant dismiss ntf-1" in rendered
    assert "--reach interrupt" not in rendered
    assert "assistant tune --class upcoming_event --reach off" in rendered
    assert "No reach setting can make this one interrupt" in rendered


def test_a_record_held_behind_its_reach_is_offered_the_raise_that_frees_it(
    output: StringIO,
) -> None:
    """ADR-0130 §6: the two acts a surface rendering one should offer, in one step.

    Which direction to offer is read off the failed set: this record is held by the
    user's own reach setting, so raising that class is the act that changes its
    outcome. Offering ``--reach off`` here would be a correct-looking suggestion
    that does the opposite of what the person reading it wants.
    """
    cli._render_notifications((_held(),), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "assistant dismiss ntf-1" in rendered
    assert "assistant tune --class upcoming_event --reach interrupt" in rendered


def test_a_record_that_is_already_allowed_through_is_offered_the_lowering_act(
    output: StringIO,
) -> None:
    """§6 names *lowering* as the second act, and an ``INTERRUPT`` is where it applies.

    Nothing about this record's reach is holding it back, so "raise the class" would
    suggest a change with no effect; what a person reading an interruption may want
    is to stop that class reaching them.
    """
    cli._render_notifications(
        (
            _held(
                kind=NotificationDispositionKind.INTERRUPT,
                reason=NotificationCondition.BUDGET,
                failed=(),
            ),
        ),
        now=AT,
        limit=50,
        offset=0,
    )

    rendered = _flowed(output.getvalue())
    assert "assistant tune --class upcoming_event --reach off" in rendered
    assert "--reach interrupt" not in rendered


@pytest.mark.parametrize(
    ("name", "overrides"),
    [
        (
            "dropped",
            {
                "kind": NotificationDispositionKind.DROP,
                "reason": NotificationCondition.REACH_OFF,
                "failed": (),
                "dropped_at": AT,
            },
        ),
        ("dismissed", {"dismissed_at": AT}),
    ],
)
def test_a_record_that_can_no_longer_act_is_offered_no_act(
    name: str, overrides: dict[str, object], output: StringIO
) -> None:
    """A surface may not offer a verb the engine will decline (ADR-0130 §7).

    Both states are still *enumerated* — a dismissal is not a deletion and a DROP
    leaves the record readable — so the row is rendered either way. What is withheld
    is the invitation: ``dismiss`` on either returns ``False``, and printing it
    beside the record would advertise an act that does nothing.
    """
    cli._render_notifications((_held(**overrides),), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "ntf-1" in rendered, name
    assert "assistant dismiss" not in rendered, name
    assert "assistant tune --class" not in rendered, name


def test_an_empty_listing_names_the_chain_that_arms_unprompted_contact(
    output: StringIO,
) -> None:
    """#979 and #981 meet here: nothing held is the state an unarmed hub sits in.

    Out of the box every class holds, so an empty page is both the ordinary first-day
    state and what an operator sees when one link of the arming chain is missing —
    and it is the one moment they are certainly looking. Saying only "nothing here"
    would leave them where #978 was, reading ADR bodies to find the acts.
    """
    cli._render_notifications((), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "assistant tune --help" in rendered
    assert "assistant notification-settings" in rendered


def test_a_hint_is_withheld_where_showing_it_would_change_what_it_says(
    output: StringIO,
) -> None:
    """A wrong command is worse than no command, and quoting alone does not stop one.

    ``_safe`` **replaces** a character a terminal must not be handed, so a class
    carrying a newline renders as ``calendar\ufffdupcoming`` — inside correct shell
    quotes, and naming a class that does not exist. That is the exact failure quoting
    was added to prevent, arriving one step later and looking like a working
    instruction rather than a mistake.

    The record still renders: what is withheld is the copyable line, and the
    replacement says so rather than leaving a gap the reader has to notice.
    """
    unshowable = _held(candidate=_candidate(notification_class="calendar\nupcoming"))

    cli._render_notifications((unshowable,), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "Standup starts in ten minutes" in rendered
    assert "assistant tune --class" not in rendered
    assert "assistant dismiss ntf-1" not in rendered
    assert "cannot show" in rendered


def test_a_tab_is_uncopyable_even_though_safe_keeps_it(output: StringIO) -> None:
    """``_safe`` is not the only lossy step between a value and the screen (#1013).

    A tab is the case the "ask ``_safe`` itself" construction misses: ``_safe`` keeps it
    on purpose — a tab inside displayed prose is legitimate, and replacing it would
    corrupt what a producer wrote — but **Rich expands it to the next tab stop** when it
    renders, before any terminal is involved. So a hint carrying one is displayed
    correctly quoted and naming a different value, which is precisely the failure
    ``_is_pasteable`` exists to catch.

    The expansion is read off Rich rather than asserted from this docstring, and the
    consequence is stated as a round trip: what is on screen, split as a shell splits
    it, is not the value it was printed for.
    """
    tabbed = "my\tcalendar"
    assert cli._safe(tabbed) == tabbed, "_safe keeps it, which is why asking _safe is not enough"

    cli.console.print(shlex.quote(tabbed))

    shown = output.getvalue().rstrip("\n")
    assert "\t" not in shown, "Rich expanded it on the way to the screen"
    assert shlex.split(shown) != [tabbed], "so reading the screen back names something else"
    assert not cli._is_pasteable(tabbed)


def test_tune_sends_a_class_byte_for_byte_so_the_listing_round_trips(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``NonBlankEncodableText`` preserves surrounding whitespace, and ``reach_for``
    compares exactly — so normalising here would guarantee the unreachable setting it
    looks like it prevents.

    A producer may declare ``" upcoming_event "``; a record carries it and the listing
    prints it. Were ``--class`` to strip, the row written would be for
    ``"upcoming_event"``, the record would stay governed by the padded name, and the
    class the user was looking at could not be tuned at all — the failure ADR-0102 §2
    keeps a grant's ``source`` byte-exact to avoid, one argument over.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, ["tune", "--class", " upcoming_event ", "--reach", "interrupt"]
    )

    assert result.exit_code == 0
    written = _written(engine)
    assert [row.notification_class for row in written.reaches] == [" upcoming_event "]
    assert written.reach_for(" upcoming_event ") is NotificationReach.INTERRUPT
    # And it is emphatically *not* the stripped name, which governs nothing here.
    assert written.reach_for("upcoming_event") is NotificationReach.HOLD


@pytest.mark.parametrize(
    ("name", "limit", "offset"),
    [("a zero limit", 0, 0), ("a page past the end", 50, 100)],
)
def test_an_empty_page_that_proves_nothing_does_not_claim_the_store_is_empty(
    name: str, limit: int, offset: int, output: StringIO
) -> None:
    """An empty *page* and an empty store are different claims, and only one is checkable.

    ``--limit 0`` is accepted here exactly as it is on every other listing — the
    engine refuses only outside ``[0, 2**63)`` — and it returns nothing whatever the
    store holds; so does any offset past the end. Answering either with "I am holding
    nothing for you" is a confident false absence, and it is worse on this surface
    than on the others, because the same message goes on to explain how to arm a
    thing that may already be armed.
    """
    cli._render_notifications((), now=AT, limit=limit, offset=offset)

    rendered = _flowed(output.getvalue())
    assert "holding nothing" not in rendered, name
    assert "assistant tune --help" not in rendered, name
    assert "this page" in rendered, name


def test_notifications_relays_the_page_and_renders_what_the_engine_returned(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0042 §6: the adapter relays the paging arguments and renders the result.

    It re-filters nothing and re-orders nothing — membership and order are the
    store's contract (ADR-0130 §7, oldest first).
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["notifications", "--limit", "5", "--offset", "2"])

    assert result.exit_code == 0
    assert [call for call in engine.calls if call[0] == "notifications"] == [
        ("notifications", {"limit": 5, "offset": 2})
    ]


def test_a_full_page_of_notifications_offers_the_next_offset(output: StringIO) -> None:
    """No total is available, so "is there more" is answered by asking (ADR-0130 §7).

    The belief, conversation and question listings all answer it this way; a count
    here would be a number nothing on the contract can supply.
    """
    cli._render_notifications((_held(),), now=AT, limit=1, offset=0)

    assert "--offset 1" in _flowed(output.getvalue())


@pytest.mark.parametrize("bad", ["-1", "9223372036854775808"])
def test_a_notification_page_outside_the_stores_range_is_a_usage_error(
    bad: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0042 §7: the engine refuses these with ``ValueError``, not ``AssistantError``.

    So without a parse-time refusal it escapes the command's error boundary as a
    traceback with no controlled exit code — the treatment ``beliefs`` and
    ``conversations`` already give the same argument.
    """
    _wire(monkeypatch, FakeAssistantEngine())

    for flag in ("--limit", "--offset"):
        result = CliRunner().invoke(cli.app, ["notifications", flag, bad])
        assert result.exit_code == 2, flag
        assert result.exception is None or isinstance(result.exception, SystemExit), flag


def test_dismiss_relays_the_id_and_says_the_record_survives(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §9: a dismissal is not a deletion, and the wording is load-bearing.

    What ends is actionability — which frees a slot under the cap at once and stops
    the key suppressing duplicates, so the same fact recurring afterwards is a new
    candidate. A message reading "destroyed" would misstate all three.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    held = asyncio.run(_admit(engine))

    # Padded, so the strip `_present_id` performs is exercised on the way through:
    # the engine is asked about the id the user meant, not about the spaces.
    result = CliRunner().invoke(cli.app, ["dismiss", f"  {held}  "])

    assert result.exit_code == 0
    rendered = _flowed(output.getvalue())
    assert "Dismissed" in rendered
    assert "still there" in rendered
    assert "forget-notification" in rendered


def test_dismiss_reports_nothing_outstanding_without_guessing_which_state(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``False`` covers four states and the façade returns one boolean (ADR-0130 §9).

    No such id, and one already dismissed, expired or dropped, are indistinguishable
    from here. Naming one of them would be a diagnosis this process cannot make —
    ``_render_no_such_source`` declines the same guess for the same reason.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["dismiss", "ntf-missing"])

    assert result.exit_code == 1
    assert "Nothing to dismiss" in _flowed(output.getvalue())
    assert [call for call in engine.calls if call[0] == "dismiss_notification"] == [
        ("dismiss_notification", {"notification_id": "ntf-missing"})
    ]


def test_forget_notification_says_the_same_thing_can_be_raised_again(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §8: the record is what stops a cursorless producer re-raising a fact.

    Destroying it therefore has a consequence a user should be told about rather
    than discover — re-noticing is the *normal* case, and the record is the whole of
    what makes it safe.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    held = asyncio.run(_admit(engine))

    result = CliRunner().invoke(cli.app, ["forget-notification", held])

    assert result.exit_code == 0
    rendered = _flowed(output.getvalue())
    assert "Forgotten" in rendered
    assert "no export" in rendered


def test_forget_notification_reports_an_id_that_names_nothing(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shape ``forget_question`` takes, exit code included (ADR-0130 §9)."""
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["forget-notification", "ntf-missing"])

    assert result.exit_code == 1
    assert "Nothing to forget" in _flowed(output.getvalue())


def test_neither_disposing_verb_asks_a_question_before_it_acts(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0130 §9 puts the delete "in the shape ``forget_question`` takes", and that
    shape has no ceremony.

    ADR-0073 §5 requires show-then-confirm before destroying a **belief**; a
    notification is not one, any more than a question is — nothing is being
    un-believed, and ``assistant notifications`` has already rendered the record
    together with both verbs. A dismissal destroys nothing at all.

    Pinned by driving both with **no** ``--yes`` and no interactive input: a command
    that grew a prompt would hang or abort here instead of acting.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    def _never(*_args: object, **_kwargs: object) -> bool:
        message = "a disposing verb on this surface asks nothing"
        raise AssertionError(message)

    monkeypatch.setattr(typer, "confirm", _never)
    for argv in (["dismiss", "ntf-1"], ["forget-notification", "ntf-1"]):
        result = CliRunner().invoke(cli.app, argv)
        assert result.exception is None or isinstance(result.exception, SystemExit), argv
        assert result.exit_code == 1, argv


def test_notification_settings_renders_all_three_from_an_empty_store(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §6: every standing setting has a shipped default, so an empty store
    is a working policy.

    All three are therefore shown whether or not the user has touched any — and the
    **default reach is named beside the classes**, because it governs every class no
    row mentions, which on a fresh installation is all of them. Rendering only what
    was set would present "I have decided nothing" as "nothing governs this", which
    is precisely the misreading that leaves someone waiting for an interruption that
    was never going to come.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["notification-settings"])

    assert result.exit_code == 0
    rendered = _flowed(output.getvalue())
    assert "hold" in rendered
    assert "every other class" in rendered
    assert "none" in rendered  # no quiet windows
    assert "3 per 24 hours" in rendered


async def _admit(engine: FakeAssistantEngine) -> str:
    """Put one held record in the fake's store and return the id it minted."""
    ruling = await engine.notification_store.admit(_candidate(), policy=engine.notification_policy)
    assert ruling.notification_id is not None
    engine.calls.clear()
    return ruling.notification_id


def _seeded() -> NotificationPreferences:
    """Standing settings with something on every axis, so a write can lose one."""
    return NotificationPreferences(
        reaches=(
            ClassReach(notification_class="upcoming_event", reach=NotificationReach.HOLD),
            ClassReach(notification_class="inbox", reach=NotificationReach.OFF),
        ),
        quiet_windows=(QuietWindow(start=22 * 60, end=7 * 60),),
        interruption_budget=5,
        budget_window=timedelta(hours=12),
    )


def _written(engine: FakeAssistantEngine) -> NotificationPreferences:
    """The value the last ``set_notification_preferences`` carried."""
    sent = [call for call in engine.calls if call[0] == "set_notification_preferences"]
    assert len(sent) == 1, sent
    value = sent[0][1]["preferences"]
    assert isinstance(value, NotificationPreferences)
    return value


async def _seed(engine: FakeAssistantEngine) -> None:
    """Put :func:`_seeded` into the fake's store."""
    await engine.notification_store.set_preferences(_seeded())


def test_tune_reads_adjusts_and_writes_back_leaving_every_other_axis_alone(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §6, and the flow ``set_notification_preferences`` prescribes in terms.

    The surface writes the **whole** value, so a command that sent only what the user
    named would silently discard their quiet hours and their budget the first time
    they raised a class. That is not a hypothetical: raising a class is the one act
    §6 requires of every user, so it is the act most likely to be performed by
    someone who has already tuned the other two.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    asyncio.run(_seed(engine))

    result = CliRunner().invoke(
        cli.app, ["tune", "--class", "upcoming_event", "--reach", "interrupt"]
    )

    assert result.exit_code == 0
    written = _written(engine)
    assert written.reach_for("upcoming_event") is NotificationReach.INTERRUPT
    assert written.reach_for("inbox") is NotificationReach.OFF
    assert written.quiet_windows == _seeded().quiet_windows
    assert written.interruption_budget == 5
    assert written.budget_window == timedelta(hours=12)


def test_tune_replaces_a_classs_row_rather_than_adding_a_second(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``NotificationPreferences`` refuses two rows for one class, and this is why.

    A second row would make the setting's meaning depend on which the reader looks at
    first — so an ``off`` might silently not hold. Substituting rather than appending
    keeps that refusal unreachable from here rather than merely unlikely; the type
    would raise, but at a point where the user has already been told what would
    happen.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    asyncio.run(_seed(engine))

    result = CliRunner().invoke(cli.app, ["tune", "--class", "inbox", "--reach", "hold"])

    assert result.exit_code == 0
    written = _written(engine)
    assert [row.notification_class for row in written.reaches].count("inbox") == 1
    assert written.reach_for("inbox") is NotificationReach.HOLD


def test_repeating_quiet_window_replaces_the_whole_set(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one legible reading of a repeated flag against a whole-value write.

    "Add to what is there" and "these are now the windows" cannot both be true of one
    flag, and the second is what a user typing two windows means. It also gives the
    only way to *shrink* the set to more than one member.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    asyncio.run(_seed(engine))

    result = CliRunner().invoke(
        cli.app,
        ["tune", "--quiet-window", "23:00-06:30", "--quiet-window", "13:00-14:00"],
    )

    assert result.exit_code == 0
    assert _written(engine).quiet_windows == (
        QuietWindow(start=23 * 60, end=6 * 60 + 30),
        QuietWindow(start=13 * 60, end=14 * 60),
    )


def test_no_quiet_windows_removes_every_one(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repeated flag cannot express the empty set, so the empty case needs a name."""
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    asyncio.run(_seed(engine))

    result = CliRunner().invoke(cli.app, ["tune", "--no-quiet-windows"])

    assert result.exit_code == 0
    assert _written(engine).quiet_windows == ()


def test_a_quiet_window_may_cross_midnight_and_is_read_as_local(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §6: the overnight case is expressed directly, not as two rows.

    And the endpoints carry no zone and cannot: quiet windows are read in
    ``Settings.timezone`` and no second timezone source is introduced, which the
    parse refuses to smuggle one past.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, ["tune", "--quiet-window", "22:00-07:00"]).exit_code == 0
    assert _written(engine).quiet_windows == (QuietWindow(start=22 * 60, end=7 * 60),)


@pytest.mark.parametrize(
    "spec",
    [
        "22:00",
        "22:00-",
        "not-a-time",
        "22:00-22:00",
        "22:00+01:00-07:00",
        "25:00-07:00",
        # Accepted by `time.fromisoformat` and then **silently truncated** by
        # `minute_of_day`, which is the one input that would otherwise be taken and
        # acted on differently — a window asked for at 22:00:59 and set at 22:00.
        "22:00:59-07:00",
        "22:00-07:00:30",
    ],
)
def test_an_unparseable_quiet_window_is_a_usage_error_before_any_client_is_built(
    spec: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0042 §7: every refusal on this path is a ``ValueError``, which the command's
    ``except (AssistantError, TransportError)`` boundary does not catch.

    Eight shapes, and each is a different refusal rather than a variation on one: no
    separator, an empty endpoint, unparseable text, the equal endpoints
    ``QuietWindow`` declines as unreadable, a zoned endpoint ADR-0130 §6 forbids, an
    hour outside the day, and — on either side — an endpoint finer than the minute
    the setting holds.

    **The last pair is the one a lenient parser would swallow.**
    ``time.fromisoformat`` takes ``22:00:59`` and ``minute_of_day`` truncates it by
    design, so without the grammar check the user asks for one window and is given
    another 59 seconds wide of it, with nothing said. Every one becomes exit code 2,
    and none reaches a hub.

    **"None reaches a hub" is two claims, and the calls list only carries one.** An
    engine with no ``set_notification_preferences`` call recorded is also what a
    command that opened a client, held it, and refused afterwards would leave — so
    the recorded opens are what make this case's own name true (#1970).
    """
    engine = FakeAssistantEngine()
    opened = _wire_recording_opens(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["tune", "--quiet-window", spec])

    assert result.exit_code == 2
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert not [call for call in engine.calls if call[0] == "set_notification_preferences"]
    assert opened == []


def test_tune_sets_the_interruption_budget_and_accepts_zero(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §6: zero is a legible "never interrupt" rather than a defect.

    So the floor is 0 and not 1 — the opposite of the grant record's ``--limit``,
    whose floor **is** 1. A parse-time refusal copied from that argument would take
    away the one way to say "not right now, at all" without turning every class off
    one by one.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, ["tune", "--budget", "0"]).exit_code == 0
    assert _written(engine).interruption_budget == 0
    assert "never interrupt" in _flowed(output.getvalue())


@pytest.mark.parametrize("bad", ["-1", "9223372036854775808"])
def test_a_budget_the_type_would_refuse_is_a_usage_error(
    bad: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``NotificationPreferences`` bounds it in ``[0, 2**63)`` with a ``ValidationError``.

    Which is not an :class:`AssistantError`, so it would escape the command's error
    boundary — ``_page_argument``'s case exactly, one field over.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["tune", "--budget", bad])

    assert result.exit_code == 2
    assert not [call for call in engine.calls if call[0] == "set_notification_preferences"]


@pytest.mark.parametrize(
    ("name", "argv"),
    [
        ("class without reach", ["tune", "--class", "upcoming_event"]),
        ("reach without class", ["tune", "--reach", "interrupt"]),
        (
            "both quiet-window forms",
            ["tune", "--quiet-window", "22:00-07:00", "--no-quiet-windows"],
        ),
        ("nothing at all", ["tune"]),
    ],
)
def test_tune_refuses_a_request_it_cannot_read_and_sends_nothing(
    name: str, argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three refusals, each decidable from what was typed, and none costing a round trip.

    ``--class`` and ``--reach`` are one setting: either alone names half of "this
    class may reach me this far", and supplying the other half would be this adapter
    deciding what the user permitted (ADR-0097 §8's posture, ADR-0042 §6's boundary).
    The two quiet-window forms contradict each other, and a precedence rule is a
    decision the user cannot see in what they typed.

    **An invocation naming nothing is refused rather than treated as a no-op**, and
    that one is not cosmetic: ADR-0130 §6 has the write stamp a reconsideration
    instant onto every held record the change could reach, so "write back exactly
    what I read" would re-arm the store with nothing to show for it.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, argv)

    assert result.exit_code == 2, name
    assert result.exception is None or isinstance(result.exception, SystemExit), name
    assert not [call for call in engine.calls if call[0] == "set_notification_preferences"], name


def test_tune_renders_the_settings_the_store_handed_back(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What is shown is what is in force, not what was sent (ADR-0130 §6).

    The two can differ — the surface has no version token and no conflict detection,
    so a racing writer's value is what a later read returns — and echoing the request
    would tell the user their edit stuck when it may not have.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    async def _returning_something_else(
        _self: object, _preferences: NotificationPreferences
    ) -> NotificationPreferences:
        return NotificationPreferences(
            reaches=(ClassReach(notification_class="somebody_elses", reach=NotificationReach.OFF),)
        )

    monkeypatch.setattr(
        type(engine), "set_notification_preferences", _returning_something_else, raising=True
    )

    result = CliRunner().invoke(
        cli.app, ["tune", "--class", "upcoming_event", "--reach", "interrupt"]
    )

    assert result.exit_code == 0
    rendered = _flowed(output.getvalue())
    assert "somebody_elses" in rendered
    assert "upcoming_event" not in rendered


def test_raising_a_class_says_it_reaches_what_is_already_held(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §6: a setting change re-rules what is already held, and that is the
    whole reason the act works.

    Reach is not a condition time resolves, so a record held at ``hold`` carries no
    due instant and would otherwise sit there until it expired — "the user raises the
    class, agrees to be interrupted, and is not". A surface silent about it invites
    exactly that misreading.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    CliRunner().invoke(cli.app, ["tune", "--class", "upcoming_event", "--reach", "interrupt"])

    rendered = _flowed(output.getvalue())
    assert "looked at again" in rendered
    # **Due, not done.** §6 stamps `reconsider_at` and stops — "the existing job picks
    # them up on its next run", and §5 makes that floor a floor. The record is still
    # HOLD as this prints, so a message in the past tense would have the user read the
    # silence that follows as the act having failed.
    assert "due to be" in rendered
    assert "next sweep" in rendered
    # **And the promise is qualified**, because reach is not the only condition (§5):
    # a held record that named no moment it stops mattering re-holds on PERISHABLE,
    # so an unqualified "can now reach you" would mislead in the other direction.
    assert "stays held" in rendered


def test_turning_a_class_off_says_what_it_reaches_and_what_it_does_not(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §6: ``off`` runs the other way and stops at held records.

    It reaches **every** actionable held record of the class, whatever it was held
    for — "never tell me this" is about what is waiting as well as what comes next —
    and it reaches nothing already ruled ``INTERRUPT``, because whether contact
    handed to a channel can be recalled is the delivery seam's question and not this
    ADR's. Both halves are said, because a message giving only the first would read
    as a promise to unsend.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    CliRunner().invoke(cli.app, ["tune", "--class", "upcoming_event", "--reach", "off"])

    rendered = _flowed(output.getvalue())
    assert "already holding" in rendered
    assert "recalled" in rendered
    # `off` is deferred by the same clause and says so: §6 makes every actionable held
    # record *due* at the instant of the write, and the ruling is the sweep's.
    assert "due to be ruled out" in rendered
    assert "next sweep" in rendered


@pytest.mark.parametrize("reach", ["interrupt", "off"])
def test_restating_the_reach_already_in_force_announces_no_re_arming(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, reach: str
) -> None:
    """ADR-0130 §6 re-arms on a *removed* condition, so a repeat re-arms nothing (#985).

    §6 stamps ``reconsider_at`` on held records whose failed-condition set holds "a
    condition that change could remove". Where the class already reaches that far the
    write removes nothing, so a record held only on ``QUIET_WINDOW`` or ``BUDGET`` sits
    exactly where it was — and the re-arming sentence would be a claim about the store
    that is false. The user who repeats the command is told what is true instead.

    Two invocations rather than a scripted read, so the "already" is one the surface's
    own first write established.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    argv = ["tune", "--class", "upcoming_event", "--reach", reach]

    assert CliRunner().invoke(cli.app, argv).exit_code == 0
    first = _flowed(output.getvalue())
    assert "already holding" in first, "the transition still announces the re-arming"

    repeated = len(output.getvalue())
    assert CliRunner().invoke(cli.app, argv).exit_code == 0

    again = _flowed(output.getvalue()[repeated:])
    assert "Tuned." in again, "the write still happens and the settings are still shown"
    assert "already reaching you exactly that far in the settings I read" in again
    # And the claim it replaces is gone rather than merely softened: the two sentences
    # that promise a sweep are the whole of what #985 says must not be printed here.
    assert "due to be" not in again
    assert "next sweep" not in again
    # **And what replaces it claims nothing about the store.** ``current`` is a
    # pre-write read taken under a contract with no version token (#1019), so a second
    # client can write between the read and the write and make any statement about held
    # records wrong. The two things this process knows for certain are what its own read
    # held and what it therefore asked for, and those are the only two it states.
    assert "I am already holding" not in again
    assert "re-considered" not in again


def test_lowering_a_class_to_hold_announces_nothing_either_way(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``hold`` is the silent one, and it is silent whether or not it moved (#985).

    Lowering a class can only *add* a failed condition, never remove one, so §6 re-arms
    nothing on account of it and there is no consequence to announce. Which makes it
    the case that distinguishes "announce what changed" from "announce whether
    anything changed": a surface reporting the second would print a no-op notice here,
    for a write whose reach genuinely did move.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    assert (
        CliRunner()
        .invoke(cli.app, ["tune", "--class", "upcoming_event", "--reach", "interrupt"])
        .exit_code
        == 0
    )
    lowered = len(output.getvalue())
    assert (
        CliRunner()
        .invoke(cli.app, ["tune", "--class", "upcoming_event", "--reach", "hold"])
        .exit_code
        == 0
    )

    rendered = _flowed(output.getvalue()[lowered:])
    assert "Tuned." in rendered
    assert "already reaching you" not in rendered
    assert "next sweep" not in rendered


def test_tuning_only_the_budget_says_nothing_about_any_class_reach(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invocation naming no class makes no claim about a class (#985).

    ``--class`` and ``--reach`` are one setting given together or not at all, so a
    budget-only write has no reach to compare against and no sentence to print. Pinned
    because the no-op notice is reached by an *absence* of change, which is exactly the
    condition a call that changed no reach at all also satisfies.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, ["tune", "--budget", "2"]).exit_code == 0

    rendered = _flowed(output.getvalue())
    assert "Tuned." in rendered
    assert "already reaching you" not in rendered
    assert "next sweep" not in rendered


def test_every_condition_a_ruling_can_name_has_a_phrase() -> None:
    """A ruling explained with a missing clause answers "why not?" with silence.

    Totality is held by ``assert_never`` at type-check time; this pins that the
    phrases are also *distinct*, which the type check cannot see — two conditions
    sharing wording would render a ruling that names the wrong one.
    """
    phrases = [cli._condition_phrase(condition) for condition in NotificationCondition]

    assert len(set(phrases)) == len(list(NotificationCondition))
    assert all(phrase.strip() for phrase in phrases)


def test_every_reach_level_has_a_distinct_phrase() -> None:
    """The same obligation on the settings rendering (ADR-0130 §6)."""
    phrases = [cli._reach_phrase(reach) for reach in NotificationReach]

    assert len(set(phrases)) == len(list(NotificationReach))


#: Rich's SGR colour sequences, which appear in help output only where colour is
#: enabled — which the terminal decides, so it differs between a developer's shell
#: and CI (#983). Stripped before any assertion about help text, together with the
#: panel's box-drawing borders, so what is matched is the *words* rather than a
#: rendering that a `TERM` or a `FORCE_COLOR` can change underneath it.
_SGR = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _help_text(rendered: str) -> str:
    """Help output as flowing words: no colour, no borders, no wrapping."""
    return " ".join(_SGR.sub("", rendered).replace("\u2502", " ").split())


def test_the_arming_acts_in_tunes_help_name_what_the_code_actually_calls_them() -> None:
    """#981: PR #977's body recorded ``assistant grant --source calendar``, which does
    not exist, and the next operator copies the record.

    So the record is pinned against the code it describes rather than kept by hand:
    the source name comes from the reader's own declared identity, the class from the
    producer that declares it, and the environment variable from ``Settings``' prefix
    and field name. A rename that leaves the help behind fails here instead of in
    somebody's terminal a year later.

    The imports reach into two subsystems, which a **test** may do and this module
    may not (golden rule 3, and ``lint-imports`` enforces it on ``interfaces``) —
    which is exactly why the help carries literals and this carries the check.
    """
    result = CliRunner().invoke(cli.app, ["tune", "--help"])
    assert result.exit_code == 0
    rendered = _help_text(result.output)

    prefix = Settings.model_config["env_prefix"]
    assert f"{prefix}calendar_upcoming_interval".upper() in rendered
    assert f"assistant grant {CALENDAR_READER_NAME} --scope notify" in rendered
    assert f"assistant tune --class {NOTIFICATION_CLASS} --reach interrupt" in rendered
    # The wrong form is named as wrong, so a reader copying from here cannot take it.
    assert "there is no --source option" in rendered
    # And the duration is given in the form the parser accepts; '15' is refused.
    assert "'PT15M'" in rendered


def test_the_notification_commands_reach_exactly_the_five_operations_adr_0130_ratifies(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0130 §9 enumerates five, and this surface adds no sixth.

    Driving all five and reading back the engine calls is what makes "thin" checkable
    rather than asserted: a command that grew a second call — a listing that fetched
    the settings to decide a hint, say — would be this adapter composing behaviour
    the contract did not put on one operation, and it would show up here as an extra
    name.

    ``next_notification`` is deliberately absent: it is the *device's* door
    (ADR-0131), polled by a spoke, and putting it on a person's command line would
    let a human consume the delivery a device is owed.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    for argv in (
        ["notifications"],
        ["dismiss", "ntf-1"],
        ["forget-notification", "ntf-1"],
        ["notification-settings"],
        ["tune", "--budget", "2"],
    ):
        CliRunner().invoke(cli.app, argv)

    assert [name for name, _ in engine.calls] == [
        "notifications",
        "dismiss_notification",
        "forget_notification",
        "notification_preferences",
        # `tune` is the read-adjust-write the contract prescribes, so it is two.
        "notification_preferences",
        "set_notification_preferences",
    ]


@pytest.mark.integration
def test_a_gateway_whose_port_is_taken_renders_one_line_rather_than_a_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, output: StringIO
) -> None:
    """#1436: the bind failure a stranger hits at step 6 of the first-run guide.

    ``asyncio.start_server`` raises a plain ``OSError``, which is neither an
    ``AssistantError`` nor a ``TransportError`` — so it used to escape
    :func:`cli._serve_gateway`'s boundary and reach the terminal as about a hundred
    lines of Rich traceback with the one useful sentence at the bottom. That is the
    failure ADR-0042 §7 exists to prevent: a fault "is rendered, not dumped".

    The gateway is right to raise it raw (``server.py``: "the raw errno
    distinguishes a stay-down fault from a transient one"), so the errno's own text
    is carried into the rendered line rather than replaced by it — which is also
    where the *address* comes from, since this adapter cannot tell which of the two
    listeners refused.
    """
    monkeypatch.setenv("ASSISTANT_DATA_DIR", str(tmp_path))
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = int(held.getsockname()[1])
        monkeypatch.setenv("ASSISTANT_GATEWAY_PORT", str(port))

        result = CliRunner().invoke(cli.app, ["gateway"])

    # Unwrapped before it is read: the console wraps at its width, so a phrase this
    # case is about can arrive with a newline through the middle of it.
    rendered = " ".join(output.getvalue().split())

    assert result.exit_code == 1
    assert "Traceback" not in rendered
    assert f"could not bind port {port}" in rendered
    assert "127.0.0.1" in rendered  # the address, from the errno's own text
    assert "in use" in rendered
    assert "ASSISTANT_GATEWAY_PORT" in rendered
    # The value printed a moment earlier went with the process, and #1436 records
    # that a reader otherwise has no way to tell.
    assert "already dead" in rendered


def test_a_start_failure_that_is_not_a_taken_port_claims_no_port_and_no_remedy() -> None:
    """Every other errno gets the kernel's refusal and nothing made up on top of it.

    The boundary is wide because it has to be — ``run_gateway`` reads the front-end
    bundle off the installed distribution and may stat an overlay agent's socket
    before either listener binds, and the remote listener probes an *ephemeral* port
    before it goes near ``gateway_port``. Adversarial review found on the first round
    that calling all of those "could not bind port 8422" points an operator at the
    wrong subsystem and at a setting that is not the cause. Narrowing the catch takes
    a distinction only ``interfaces/gateway/server.py`` can draw, so the claim is
    narrowed instead: the port and its remedy belong to ``EADDRINUSE`` alone.
    """
    refused = cli._gateway_did_not_start(
        OSError(errno.EIO, "input/output error"), port=8422, probes_an_address=False
    )

    assert "could not start" in str(refused)
    assert "operating system's own refusal" in str(refused)
    assert "8422" not in str(refused)
    assert "ASSISTANT_GATEWAY_PORT" not in str(refused)
    # The half that is true whatever failed: nothing is serving, and the value the
    # gateway printed before it tried to bind went with the process (#1436).
    assert "already dead" in str(refused)


def test_a_taken_address_is_pinned_on_the_port_only_where_nothing_else_could_be_it() -> None:
    """``EADDRINUSE`` is not always ``gateway_port``, and the flat claim is conditional.

    ``start_remote`` probes the configured overlay address by binding an *ephemeral*
    port, and an exhausted ephemeral range raises ``EADDRINUSE`` — on a gateway whose
    loopback listener has already bound ``gateway_port`` successfully, since ``serve``
    binds that one first. Adversarial review found on the second round that the flat
    claim sends that operator to free a port that is not the problem.

    The probe exists only where a remote listener is configured, and that is a fact
    this adapter holds. So without one the flat claim is sound — which is every reader
    of ``docs/guide/first-run.md`` — and with one the message stops naming a single
    port as the cause.
    """
    taken = OSError(errno.EADDRINUSE, "address already in use")

    alone = str(cli._gateway_did_not_start(taken, port=8422, probes_an_address=False))
    with_overlay = str(cli._gateway_did_not_start(taken, port=8422, probes_an_address=True))

    assert "could not bind port 8422" in alone
    assert "ASSISTANT_GATEWAY_REMOTE_ADDRESS" not in alone

    assert "could not bind port 8422" not in with_overlay
    assert "could not bind an address it needed" in with_overlay
    # Both settings named, because either listener could be the one holding it, and
    # the ephemeral case named as the one that is about neither.
    assert "ASSISTANT_GATEWAY_PORT" in with_overlay
    assert "ASSISTANT_GATEWAY_REMOTE_ADDRESS" in with_overlay
    assert "ephemeral port" in with_overlay


def test_a_pre_bind_failure_is_rendered_without_being_called_a_bind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, output: StringIO
) -> None:
    """The same boundary, driven end to end on the half that is not about the port.

    ``run_gateway`` reads the front-end bundle off the installed distribution before
    either listener starts, so an unreadable installation arrives at this adapter as
    an ``OSError`` indistinguishable from a bind — the case adversarial review raised
    against the first draft. It still has to be rendered rather than dumped, and it
    still has to exit non-zero; what it must not do is send the operator to
    ``ASSISTANT_GATEWAY_PORT``.
    """
    monkeypatch.setenv("ASSISTANT_DATA_DIR", str(tmp_path))

    async def unreadable(**_kwargs: object) -> None:
        """Fail the way a bundle read off a broken installation would."""
        raise OSError(errno.EIO, "input/output error")

    monkeypatch.setattr(cli, "run_gateway", unreadable)

    result = CliRunner().invoke(cli.app, ["gateway"])
    rendered = " ".join(output.getvalue().split())

    assert result.exit_code == 1
    assert "Traceback" not in rendered
    assert "could not start" in rendered
    assert "input/output error" in rendered
    assert "ASSISTANT_GATEWAY_PORT" not in rendered
