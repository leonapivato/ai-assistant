"""The CLI adapter: thin rendering and the converse/resume relay (ADR-0042 §4, §6, §7).

Rendering is checked against captured Rich output; the turn flow is driven against
a real :class:`Engine` assembled from canonical fakes (the adapter cannot tell it
from the production engine — that is the point of the façade). Nothing here builds
the production, model-backed engine, so no network or key is needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from inspect import unwrap
from io import StringIO
from itertools import count
from typing import TYPE_CHECKING

import pytest
import typer.main
from rich.console import Console
from typer.core import TyperGroup
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import (
    ConfigurationError,
    DeferralStoreError,
    MemoryStoreError,
    PlanningError,
)
from ai_assistant.core.types import (
    ActionPlan,
    AnswerKind,
    AnswerOutcome,
    Belief,
    BeliefBand,
    BeliefSummary,
    Confirmation,
    ContinuationToken,
    CostBasis,
    DataTier,
    Disposition,
    Evidence,
    ExecutionState,
    FeedbackEvent,
    FeedbackKind,
    GrantScope,
    Idempotency,
    IngestSummary,
    LearnDecision,
    LearnOutcome,
    MemoryKind,
    MemorySource,
    ObservationReport,
    ObservedProposal,
    PlanStep,
    Question,
    QuestionState,
    QueuedQuestion,
    QueueOutcome,
    Retirement,
    Reversibility,
    RiskLevel,
    StepExecution,
    StepFailure,
    StepOutcome,
    StepStatus,
    SuccessorLink,
    ToolCost,
    ToolDefinition,
    TurnOutcome,
)
from ai_assistant.interfaces import cli
from ai_assistant.orchestration import (
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
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAssistantEngine,
    FakeAuditTrail,
    FakeContextProvider,
    FakeConversationStore,
    FakeDeferralStore,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeObserver,
    FakePlanStore,
    FakeSourceGrantStore,
    FakeToolInvoker,
)
from ai_assistant.wire.address import sun_path_limit

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from pathlib import Path

    from ai_assistant.core.types import CurrentContext, Goal, MemoryRecord

AT = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)


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


#: The route the harness's observation stage reports (ADR-0077 §3). In production
#: the composition root supplies it from ``Settings``; here it is fixed so a case
#: can assert the terminal names the route that read the episodes.
OBSERVER_ROUTE = "anthropic:claude-opus-4-8"
PATIENT = timedelta(seconds=30)
CAPABILITY = "send_email"
PARAMETERS = {"to": "someone@example.com"}


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
) -> Engine:
    """A real ``Engine`` over canonical fakes, driving a one-step plan."""
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    invoker = FakeToolInvoker([(definition, _succeeds) for definition in tools])
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
        grant_operations=_grant_operations(),
        loop=loop,
        runner=runner,
        plans=plans,
        trail=trail,
        memory=memory,
        deferrals=deferrals,
        conversations=ConversationLifecycle(
            conversations=conversations,
            memory=memory,
            retention=timedelta(days=30),
            now=lambda: AT,
        ),
        observation=_observation(conversations, memory, writes),
        questions=QuestionStage(writer=writer, deferrals=deferrals, memory=memory, now=lambda: AT),
        closers=closers,
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
    )
    cli._render_confirmation(confirmation)
    rendered = output.getvalue()

    assert "\x1b[2J" not in rendered  # the raw control sequence was neutralised
    assert "\x1b" not in rendered  # no escape byte at all
    assert "[red]" in rendered  # markup is shown literally, not interpreted as colour
    assert "this discloses data off-device" in rendered  # the ruling reason is surfaced


def test_disposition_render_names_the_executed_tool(output: StringIO) -> None:
    """An executed step names the tool that ran (§3)."""
    cli._render_disposition(Disposition.EXECUTED, "smtp")
    assert "smtp" in output.getvalue()


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

    code = await cli._drive_turn(engine, "send it", timeout=PATIENT, approver=approve)
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

    code = await cli._drive_turn(engine, "send it", timeout=PATIENT, approver=approve)
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
        engine, "send it", timeout=PATIENT, approver=lambda _confirmation: False
    )
    assert code == 0
    assert "Declined" in output.getvalue()
    await engine.aclose()


async def test_ask_surfaces_an_error_with_a_nonzero_exit(output: StringIO) -> None:
    """A blank utterance is a PlanningError the CLI surfaces, exit 1 (§7)."""
    engine = _engine(tools=(tool(),))
    code = await cli._drive_turn(
        engine, "   ", timeout=PATIENT, approver=lambda _confirmation: True
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
def test_ask_rejects_an_unusable_timeout(bad: str) -> None:
    """A non-finite, non-positive, overflowing, or sub-resolution --timeout is a usage error."""
    result = CliRunner().invoke(cli.app, ["ask", "hello", "--timeout", bad])
    assert result.exit_code == 2  # Typer's usage-error code, before the engine is built


# --- learn: the correction leg (roadmap leg 1; ADR-0042 §3, §6) ---------


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


def test_learn_builds_a_correction_event_and_defaults_the_memory_kind(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--kind correction becomes a CORRECTION event defaulting to a semantic fact."""
    engine = _RecordingEngine(_stored_outcome())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, ["learn", "--kind", "correction", "the office is in Boston"]
    )
    assert result.exit_code == 0
    assert len(engine.events) == 1
    event = engine.events[0]
    assert event.kind is FeedbackKind.CORRECTION
    assert event.memory_kind is MemoryKind.SEMANTIC  # defaulted from --kind
    assert event.content == "the office is in Boston"
    assert event.subject is None
    assert event.created_at == AT  # stamped from the injected clock, not hand-rolled
    assert "Learned" in output.getvalue()


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
def test_learn_rejects_a_blank_about_person(blank: str) -> None:
    """A blank subject is a usage error, not an uncaught ValidationError (§7).

    ``FeedbackEvent.about_person`` is ``NonBlankEncodableText``, whose refusal is
    a ``ValidationError`` — not an ``AssistantError`` — raised while the event is
    built, which is *before* :func:`_learn_feedback`'s error boundary opens. The
    parse-time callback turns it into a clean exit 2, the shape ``_present_source``
    already uses one command over.
    """
    result = CliRunner().invoke(
        cli.app, ["learn", "--kind", "correction", "x", "--about-person", blank]
    )

    assert result.exit_code == 2  # Typer's usage-error code
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_learn_rejects_an_unencodable_about_person() -> None:
    r"""A lone surrogate reaches argv and no UTF-8 encoder will take it.

    Linux passes argv as bytes and Python decodes it with ``surrogateescape``, so
    ``assistant learn x --about-person $'\xe9'`` arrives as half a character.
    ``EncodableText`` refuses it, and without the parse-time check that refusal
    would land as the same uncaught ``ValidationError`` a blank one would.
    """
    result = CliRunner().invoke(
        cli.app, ["learn", "--kind", "correction", "x", "--about-person", "\udce9"]
    )

    assert result.exit_code == 2
    assert result.exception is None or isinstance(result.exception, SystemExit)


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


def test_learn_rejects_an_unknown_kind() -> None:
    """An unrecognised --kind is a usage error, before any engine is built."""
    result = CliRunner().invoke(cli.app, ["learn", "--kind", "bogus", "hello"])
    assert result.exit_code == 2  # Typer's usage-error code


def test_learn_requires_a_kind() -> None:
    """--kind is required; omitting it is a usage error."""
    result = CliRunner().invoke(cli.app, ["learn", "hello"])
    assert result.exit_code == 2


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_learn_rejects_blank_content(blank: str) -> None:
    """Whitespace-only content is a usage error, not an uncaught ValidationError (§7).

    ``FeedbackEvent.content`` rejects blank text, and that ``ValidationError`` is not
    an ``AssistantError``; the parse-time callback turns it into a clean usage error
    (exit 2) before any event is constructed, rather than a dumped traceback.
    """
    result = CliRunner().invoke(cli.app, ["learn", "--kind", "correction", blank])
    assert result.exit_code == 2  # Typer's usage-error code
    assert result.exception is None or isinstance(result.exception, SystemExit)


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


def _belief(  # noqa: PLR0913 — one knob per field a Belief carries; that is the point
    band: BeliefBand = BeliefBand.ASSERTED,
    *,
    belief_id: str = "rec-1",
    content: str = "the office is in Boston",
    confidence: float = 1.0,
    evidence: tuple[Evidence, ...] = (),
    valid_until: datetime | None = None,
    evidence_elided: int = 0,
) -> Belief:
    """One projected belief, as the façade hands it to the adapter.

    ``confidence`` is the **presented** number: the engine has already adjusted it
    for lost support (ADR-0077 §6), so a case scripting a tombstone also scripts the
    lowered figure rather than expecting this module to compute one.
    """
    return Belief(
        id=belief_id,
        band=band,
        kind=MemoryKind.SEMANTIC,
        content=content,
        confidence=confidence,
        evidence=evidence,
        last_updated=AT,
        valid_until=valid_until,
        evidence_elided=evidence_elided,
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
) -> BeliefSummary:
    """One listing row, as the façade hands it to the adapter (ADR-0085 §4a).

    The counts are **fields** here rather than derived, because the listing type
    carries no citations to derive them from — which is what makes it impossible
    for a page to ship an episode's text.
    """
    return BeliefSummary(
        id=belief_id,
        band=band,
        kind=MemoryKind.SEMANTIC,
        content=content,
        confidence=confidence,
        evidence_count=evidence_count,
        lost_evidence=lost_evidence,
        last_updated=AT,
        valid_until=valid_until,
        evidence_elided=evidence_elided,
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
            "a source you connected reported it — neither your word nor my inference. "
            "I recorded which source, and when it said so, but cannot show them here, "
            "so 'Last revised' below is when I changed my mind and not when the "
            "source spoke.",
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
    """
    assert cli._why(_belief(band, confidence=0.9, evidence_elided=900)) == expected
    assert cli._why(_summary(band, confidence=0.9, evidence_elided=900)) == expected


def test_why_marks_an_attested_belief_as_a_source_s_report_not_ours(output: StringIO) -> None:
    """ADR-0073 §4's attested floor: neither the user's word nor our inference.

    And our revision time is not offered as the source's — the line says outright
    that ``Last revised`` is when *we* changed our mind.
    """
    cli._render_belief(_belief(BeliefBand.ATTESTED, confidence=0.9))
    rendered = _flat(output.getvalue())
    assert "a source you connected reported it" in rendered
    assert "neither your word nor my inference" in rendered
    assert "not when the source spoke" in rendered


def test_why_blames_the_surface_for_the_missing_attestation_and_not_the_store(
    output: StringIO,
) -> None:
    """#711: the source and the report time *are* held, and the projection drops them.

    An attested belief carries an ``Attestation`` by construction — ADR-0092 §1's
    validator on :class:`~ai_assistant.core.types.Provenance` makes one mandatory
    exactly on this band — so a line reading "not recorded" tells a user auditing
    what is held about them the inverse of the truth, on the one band whose whole
    purpose is provenance. The honest limit is this surface's: a
    :class:`~ai_assistant.core.types.Belief` has nowhere to put an attestation
    (#568), so the view cannot show what the store kept.

    Pinned as **both halves**, because either alone is satisfiable by a wrong line:
    the claim that the record was made, and the refusal to claim it can be shown
    here. The negative assertion is what stops the old sentence returning under a
    reworded neighbour — nothing else in this suite would notice.
    """
    cli._render_belief(_belief(BeliefBand.ATTESTED, confidence=0.9))
    rendered = _flat(output.getvalue())
    assert "I recorded which source, and when it said so" in rendered
    assert "cannot show them here" in rendered
    assert "not recorded" not in rendered


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
def test_beliefs_command_rejects_a_page_the_store_would_refuse(bad: str) -> None:
    """An out-of-range --limit is a usage error, not an uncaught ValueError (§2, §7).

    ``list_beliefs`` raises ``ValueError`` outside ``[0, 2**63)``, and a ``ValueError``
    is not an ``AssistantError``, so it would escape the command's error boundary as
    a traceback. The parse-time check turns it into exit code 2 before any engine is
    built.
    """
    for flag in ("--limit", "--offset"):
        result = CliRunner().invoke(cli.app, ["beliefs", flag, bad])
        assert result.exit_code == 2
        assert result.exception is None or isinstance(result.exception, SystemExit)


def test_beliefs_command_rejects_an_unknown_band() -> None:
    """A band outside the ratified vocabulary is a usage error, before any engine."""
    result = CliRunner().invoke(cli.app, ["beliefs", "--band", "guessed"])
    assert result.exit_code == 2


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


def _conversation_engine() -> tuple[Engine, FakeConversationStore]:
    """A real ``Engine`` over canonical fakes, plus the conversation index behind it.

    The store is handed back so a case can assert what capture actually recorded,
    rather than inferring it from what the terminal printed.
    """
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    invoker = FakeToolInvoker([])
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
        grant_operations=_grant_operations(),
        loop=loop,
        runner=runner,
        plans=plans,
        trail=trail,
        memory=memory,
        deferrals=deferrals,
        conversations=ConversationLifecycle(
            conversations=conversations,
            memory=memory,
            retention=timedelta(days=30),
            now=lambda: AT,
        ),
        observation=_observation(conversations, memory, writes),
        questions=QuestionStage(writer=writer, deferrals=deferrals, memory=memory, now=lambda: AT),
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
    ) -> ActionPlan:
        return ActionPlan(id=f"{goal.id}-plan", goal_id=goal.id, steps=(), created_at=AT)


async def test_ask_names_the_conversation_it_ran_under(output: StringIO) -> None:
    """§2: the id is what a stateless client keeps, so the surface has to print it."""
    engine, conversations = _conversation_engine()

    code = await cli._drive_turn(
        engine, "hello", timeout=timedelta(seconds=5), approver=lambda _c: True
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
    await cli._drive_turn(engine, "hello", timeout=timedelta(seconds=5), approver=lambda _c: True)
    existing = (await conversations.recent())[0].id

    code = await cli._drive_turn(
        engine,
        "again",
        timeout=timedelta(seconds=5),
        approver=lambda _c: True,
        conversation_id=existing,
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
    )

    assert code == cli._EXIT_ERROR
    assert "Error" in output.getvalue()
    assert await conversations.recent() == []


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
    await cli._drive_turn(engine, "hello", timeout=timedelta(seconds=5), approver=lambda _c: True)
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
    await cli._drive_turn(engine, "hello", timeout=timedelta(seconds=5), approver=lambda _c: True)
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
    await cli._drive_turn(engine, "hello", timeout=timedelta(seconds=5), approver=lambda _c: True)
    existing = (await conversations.recent())[0].id
    await cli._drive_turn(
        engine,
        "again",
        timeout=timedelta(seconds=5),
        approver=lambda _c: True,
        conversation_id=existing,
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
    await cli._drive_turn(engine, "hello", timeout=timedelta(seconds=5), approver=lambda _c: True)
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
            engine, "hello", timeout=timedelta(seconds=5), approver=lambda _c: True
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
            engine, "hello", timeout=timedelta(seconds=5), approver=lambda _c: True
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


def _question(
    question_id: str = "q-1",
    *,
    state: QuestionState = QuestionState.OPEN,
    retires: tuple[Retirement, ...] = (),
    successor: SuccessorLink | None = None,
) -> Question:
    return Question(
        id=question_id,
        state=state,
        content="the user works from Lisbon",
        kind=MemoryKind.SEMANTIC,
        band=BeliefBand.ASSERTED,
        rationale="they said so",
        reason="contradicts a prior user assertion",
        retires=retires,
        asked_at=AT,
        expires_at=AT,
        successor=successor,
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
    assert "Nothing to forget" in output.getvalue()


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
    the treatment ``--limit`` and blank ``learn`` content already get.
    """
    _wire(monkeypatch, _granting_engine())

    assert CliRunner().invoke(cli.app, ["revoke", "   "]).exit_code == 2
    assert CliRunner().invoke(cli.app, ["grant", "   ", "--scope", "facet"]).exit_code == 2


def test_a_repeated_scope_is_a_usage_error_and_never_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0097 §10 spells a duplicated scope as a refusal, not something to fold away.

    Both the client and the engine raise ``ValueError`` for it, which is again not
    an :class:`AssistantError`, so ``--scope facet --scope facet`` escaped as a
    traceback for the same reason a blank source did.
    """
    _wire(monkeypatch, _granting_engine())

    result = CliRunner().invoke(
        cli.app, ["grant", "calendar", "--scope", "facet", "--scope", "facet", "--yes"]
    )
    assert result.exit_code == 2


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
    """
    _wire(monkeypatch, _granting_engine())
    unwritable = "\udce9"

    result = CliRunner().invoke(cli.app, ["revoke", unwritable])
    assert result.exit_code == 2
    assert unwritable not in result.output
    assert CliRunner().invoke(cli.app, ["grant", unwritable, "--scope", "facet"]).exit_code == 2


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
    out of order. Pointing at ``assistant sources`` is what keeps that a display
    oddity rather than a wrong answer.
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
    assert "assistant sources" in rendered


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
    """
    _wire(monkeypatch, FakeAssistantEngine())

    for name, argv in _id_invocations(blank):
        result = CliRunner().invoke(cli.app, argv)
        assert result.exit_code == 2, name
        assert result.exception is None or isinstance(result.exception, SystemExit), name


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
    """
    _wire(monkeypatch, FakeAssistantEngine())
    unwritable = "\udce9"

    for name, argv in _id_invocations(unwritable):
        result = CliRunner().invoke(cli.app, argv)
        assert result.exit_code == 2, name
        assert unwritable not in result.output, name


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
    assert [call[1]["conversation_id"] for call in engine.calls if call[0] == "converse"] == [None]


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
        "forget:belief_id": True,
        "forget-conversation:conversation_id": True,
        "forget-question:question_id": True,
        "observe:conversation_id": True,
    }
