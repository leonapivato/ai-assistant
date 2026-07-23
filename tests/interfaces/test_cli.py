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
    CostBasis,
    DataTier,
    Idempotency,
    PlanStep,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.interfaces import cli
from ai_assistant.orchestration import (
    Confirmation,
    ContinuationToken,
    Disposition,
    Engine,
    LearningLoop,
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
    return Engine(loop=loop, runner=runner, plans=plans, closers=closers)


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
