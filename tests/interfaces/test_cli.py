"""The CLI adapter: thin rendering and the converse/resume relay (ADR-0042 §4, §6, §7).

Rendering is checked against captured Rich output; the turn flow is driven against
a real :class:`Engine` assembled from canonical fakes (the adapter cannot tell it
from the production engine — that is the point of the façade). Nothing here builds
the production, model-backed engine, so no network or key is needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import TYPE_CHECKING

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError, MemoryStoreError, PlanningError
from ai_assistant.core.types import (
    ActionPlan,
    BeliefBand,
    CostBasis,
    DataTier,
    FeedbackEvent,
    FeedbackKind,
    Idempotency,
    MemoryKind,
    PlanStep,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.interfaces import cli
from ai_assistant.orchestration import (
    Belief,
    Confirmation,
    ContinuationToken,
    Disposition,
    Engine,
    IngestSummary,
    LearnDecision,
    LearningLoop,
    LearnOutcome,
    StepExecutor,
    StepRunner,
)
from ai_assistant.testing import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeContextProvider,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakePlanStore,
    FakeToolInvoker,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ai_assistant.core.types import CurrentContext, Goal, MemoryRecord

AT = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
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
    loop = LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writer=writer,
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
    return Engine(
        loop=loop, runner=runner, plans=plans, trail=trail, memory=memory, closers=closers
    )


# --- rendering: escaping is the adapter's, per target (ADR-0042 §4) ------


def test_confirmation_render_neutralises_control_sequences_and_markup(output: StringIO) -> None:
    """A parameter value's ANSI escape and Rich markup are shown, not acted on (§4)."""
    confirmation = Confirmation(
        tool_id="smtp",
        tool_description="Send an email.",
        parameters={"body": "wipe\x1b[2Jscreen and [red]shout[/red]"},
        reason="this discloses data off-device",
        token=ContinuationToken("tok"),
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


async def test_ask_renders_a_build_failure_and_exits_nonzero(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A composition-root failure is caught by the same boundary (§7)."""
    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)

    def _bad_build(_settings: object) -> object:
        msg = "could not open the store"
        raise MemoryStoreError(msg)

    monkeypatch.setattr(cli, "build_engine", _bad_build)
    code = await cli._ask("hello", timeout_seconds=1.0, assume_yes=True)
    assert code == 1
    assert "could not open the store" in output.getvalue()


@pytest.mark.parametrize("bad", ["inf", "nan", "0", "-1", "1e100", "1e-7"])
def test_ask_rejects_an_unusable_timeout(bad: str) -> None:
    """A non-finite, non-positive, overflowing, or sub-resolution --timeout is a usage error."""
    result = CliRunner().invoke(cli.app, ["ask", "hello", "--timeout", bad])
    assert result.exit_code == 2  # Typer's usage-error code, before the engine is built


# --- shutdown-failure boundary (ADR-0042 §2, §7) ------------------------


async def _failing_closer() -> None:
    """A closer that fails, as a broken owned resource would."""
    msg = "the store would not close"
    raise RuntimeError(msg)


async def test_close_reports_a_failing_closer_as_nonzero(output: StringIO) -> None:
    """``aclose`` raises an ExceptionGroup on a closer failure; the cause is shown, exit 1."""
    engine = _engine(closers=(_failing_closer,))
    code = await cli._close(engine)
    assert code == cli._EXIT_ERROR
    rendered = output.getvalue()
    assert "Error" in rendered
    # The contained cause is surfaced, not just the ExceptionGroup summary.
    assert "the store would not close" in rendered


async def test_a_shutdown_failure_after_a_good_turn_still_exits_nonzero(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A turn can succeed yet the process fail to shut down cleanly — that is exit 1 (§7)."""
    engine = _engine(tools=(tool(),), closers=(_failing_closer,))
    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "build_engine", lambda _settings: engine)

    code = await cli._ask("send it", timeout_seconds=1.0, assume_yes=True)
    assert code == 1  # the step ran, but the failed close downgrades the exit code
    rendered = output.getvalue()
    assert "Done" in rendered  # the turn's success was still reported
    assert "Error" in rendered  # and so was the shutdown failure


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

    async def aclose(self) -> None:
        """Nothing to release: this stand-in owns no resource."""


class _FailingLearnEngine:
    """An engine whose ``learn`` fails, as a broken write path would."""

    async def learn(self, event: FeedbackEvent) -> LearnOutcome:
        msg = "the memory store would not write"
        raise MemoryStoreError(msg)

    async def aclose(self) -> None:
        """Nothing to release."""


def _stored_outcome() -> LearnOutcome:
    """One stored proposal, the ordinary success shape."""
    return LearnOutcome(
        results=(IngestSummary(decision=LearnDecision.STORED, record_id="rec-1", reason="new"),)
    )


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object) -> None:
    """Point the ``learn`` command's startup at ``engine`` with valid settings."""
    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "build_engine", lambda _settings: engine)
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
            IngestSummary(LearnDecision.REINFORCED, "r1", "matches an existing memory"),
            IngestSummary(LearnDecision.SUPERSEDED, "r2", "overturns a prior belief"),
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


def test_render_learn_marks_a_deferred_ruling_as_not_stored(output: StringIO) -> None:
    """An ASK_USER ruling wrote nothing and has no confirmation flow — say so honestly.

    The CLI must not imply a follow-up that does not exist (memory decisions are not
    what ``assistant resume`` recovers; #422 review): the line names it as not stored
    and does not promise it can be confirmed.
    """
    outcome = LearnOutcome(
        results=(IngestSummary(LearnDecision.DEFERRED, None, "conflicts with a prior assertion"),)
    )
    cli._render_learn(outcome)
    rendered = output.getvalue()
    assert "Not stored" in rendered
    assert "0 stored" in rendered  # the header count excludes it
    assert "conflicts with a prior" in rendered  # the reason is surfaced (Rich may wrap it)


def test_render_learn_neutralises_a_reason_for_the_terminal(output: StringIO) -> None:
    """A reason carrying control bytes or markup is neutralised on render (§4)."""
    outcome = LearnOutcome(
        results=(IngestSummary(LearnDecision.STORED, "r1", "wipe\x1b[2J and [red]shout[/red]"),)
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
    evidence_count: int = 0,
    valid_until: datetime | None = None,
) -> Belief:
    """One projected belief, as the façade hands it to the adapter."""
    return Belief(
        id=belief_id,
        band=band,
        kind=MemoryKind.SEMANTIC,
        content=content,
        confidence=confidence,
        evidence_count=evidence_count,
        last_updated=AT,
        valid_until=valid_until,
    )


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


def test_why_reports_derived_evidence_as_a_count_and_says_it_cannot_be_shown(
    output: StringIO,
) -> None:
    """ADR-0073 §4's derived floor: the citations are counted, and named as unshowable.

    A citation this surface cannot render as evidence is never rendered *as*
    evidence and never silently dropped. The count says the warrant exists; the
    wording says it cannot be displayed yet.
    """
    cli._render_belief(_belief(BeliefBand.DERIVED, confidence=0.62, evidence_count=3))
    rendered = _flat(output.getvalue())
    assert "3 piece(s) of evidence" in rendered
    assert "which I cannot show you yet" in rendered


def test_why_does_not_claim_evidence_a_derived_belief_does_not_have(output: StringIO) -> None:
    """A derived belief with no recorded citation says so rather than implying one."""
    cli._render_belief(_belief(BeliefBand.DERIVED, confidence=0.4, evidence_count=0))
    rendered = _flat(output.getvalue())
    assert "no supporting evidence was recorded" in rendered
    assert "piece(s) of evidence" not in rendered


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


def test_render_beliefs_reports_an_empty_page_plainly(output: StringIO) -> None:
    """Nothing matching is said, not shown as an empty success."""
    cli._render_beliefs((), limit=50, offset=0)
    assert "No live belief matches" in output.getvalue()


def test_render_beliefs_offers_the_next_page_without_claiming_a_total(
    output: StringIO,
) -> None:
    """A full page names the offset that would fetch the next; no count is shown (§7)."""
    cli._render_beliefs((_belief(belief_id="a"), _belief(belief_id="b")), limit=2, offset=4)
    rendered = _flat(output.getvalue())
    assert "--offset 6" in rendered
    assert "there may be more" in rendered


def test_render_beliefs_does_not_offer_a_next_page_for_a_short_one(output: StringIO) -> None:
    """A page shorter than the limit is the end of the enumeration."""
    cli._render_beliefs((_belief(),), limit=50, offset=0)
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


def test_beliefs_command_asks_for_every_band_when_no_filter_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An absent repeatable flag means "every", not the empty filter that selects none."""
    engine = _RecordingBeliefEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["beliefs"])
    assert result.exit_code == 0
    assert engine.listed == [(None, None, 50, 0)]


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
