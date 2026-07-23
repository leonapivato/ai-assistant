"""Command-line interface — the first adapter onto the engine (ADR-0042 §7).

Kept intentionally thin (golden rule 3, ADR-0042 §6): it parses input into an
utterance, obtains the façade from the composition root, drives one turn with
``converse``/``resume``, renders the final :class:`~ai_assistant.orchestration.TurnOutcome`
with Rich, relays the **opaque** continuation token on a confirmation, and closes
the façade on exit. It authors no permission ruling, plans nothing, selects no
tool, and touches no subsystem directly — all of that is the engine's, reached
only through the façade (ADR-0042 §6). Registered as the ``assistant`` console
script in ``pyproject.toml``.

v1 renders the *final* state of each call; streaming is deferred (ADR-0042 §5).
"""

from __future__ import annotations

import asyncio
import math
from datetime import timedelta
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.markup import escape

from ai_assistant import __version__
from ai_assistant.app import build_engine
from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import AssistantError
from ai_assistant.core.logging import configure_logging
from ai_assistant.orchestration import Disposition

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.orchestration import Confirmation, Engine, TurnOutcome

app = typer.Typer(
    name="assistant",
    help="A model-agnostic AI operating system — deeply personalized assistant.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

#: Exit codes (ADR-0042 §7: "setting a meaningful exit code").
_EXIT_OK = 0
_EXIT_ERROR = 1


@app.callback()
def main() -> None:
    """Root command group. Keeps subcommands addressable by name.

    Deliberately does no configuration work: loading settings can fail, and a
    failure here would escape as an uncaught traceback with no controlled exit
    code. Each command that needs settings loads them inside its own error
    boundary instead (ADR-0042 §7), so a bad ``ASSISTANT_*`` value is rendered,
    not dumped.
    """


@app.command()
def version() -> None:
    """Print the installed version."""
    console.print(f"ai-assistant [bold cyan]{__version__}[/]")


def _positive_finite_seconds(value: float) -> float:
    """Reject a ``--timeout`` that is not a usable number of seconds.

    Runs during Typer's parameter parsing, so an invalid value is a normal usage
    error (exit code 2) rather than an ``OverflowError`` from ``timedelta`` or a
    non-positive budget the executor would later refuse mid-run. Rejected: a
    non-finite value (``inf``/``nan``), a non-positive one, and a finite value too
    large to be a ``timedelta`` (e.g. ``1e100``) — the last checked by constructing
    it here, so ``_ask`` can build the same duration without overflowing.
    """
    if not math.isfinite(value) or value <= 0:
        msg = "must be a positive, finite number of seconds"
        raise typer.BadParameter(msg)
    try:
        duration = timedelta(seconds=value)
    except OverflowError as exc:
        msg = "is too large to be a duration"
        raise typer.BadParameter(msg) from exc
    # A positive value below timedelta's microsecond resolution (e.g. 1e-7) rounds
    # to zero — a deadline the executor refuses. Reject it as invalid input, not a
    # mid-run ValueError.
    if duration <= timedelta(0):
        msg = "is too small to be a usable deadline"
        raise typer.BadParameter(msg)
    return value


@app.command()
def ask(
    utterance: str = typer.Argument(..., help="What you want the assistant to do."),
    timeout_seconds: float = typer.Option(
        60.0,
        "--timeout",
        callback=_positive_finite_seconds,
        help="Per-attempt deadline for the engine's work, in seconds (positive).",
    ),
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Approve any confirmation without prompting."
    ),
) -> None:
    """Run one turn: plan it, drive its step, and render what happened.

    If the engine parks a step for confirmation, the prompt shows the action and
    the policy's reason; answering relays the opaque token back to the engine.
    """
    code = asyncio.run(_ask(utterance, timeout_seconds=timeout_seconds, assume_yes=yes))
    raise typer.Exit(code)


async def _ask(utterance: str, *, timeout_seconds: float, assume_yes: bool) -> int:
    """Load settings, build the engine, drive one turn, and close it (ADR-0042 §2, §7).

    One error boundary spans **every** stage that can fail — loading settings,
    configuring logging, constructing the engine, driving the turn, and shutting
    down — so any :class:`AssistantError` is rendered and mapped to a non-zero exit
    code rather than escaping as a traceback (§7). Returns the process exit code.
    The composition root owns constructing the façade; this adapter owns closing it.
    """
    timeout = timedelta(seconds=timeout_seconds)  # already validated positive + finite
    approver: Callable[[Confirmation], bool] = (
        (lambda _confirmation: True) if assume_yes else _prompt_for_approval
    )
    try:
        settings = load_settings()
        configure_logging(settings)
        engine = build_engine(settings)
    except AssistantError as exc:
        _render_error(exc)
        return _EXIT_ERROR

    try:
        code = await _drive_turn(engine, utterance, timeout=timeout, approver=approver)
    finally:
        shutdown_code = await _close(engine)
    # A failure closing an owned resource is itself a failure to report (§7): the
    # turn may have succeeded, but the process did not shut down cleanly.
    return max(code, shutdown_code)


async def _close(engine: Engine) -> int:
    """Close the façade on exit, reporting a shutdown failure rather than crashing.

    Returns a non-zero code if closing fails, so the caller can fold it into the
    exit status (ADR-0042 §7). Catches ``Exception`` — not just ``AssistantError``
    — because :meth:`Engine.aclose` raises an ``ExceptionGroup`` when an owned
    resource's ``close`` fails; a shutdown fault must be surfaced, not propagated
    as a traceback, and must not be mistaken for success. ``BaseException`` (a
    cancellation, a keyboard interrupt) is left to propagate.
    """
    try:
        await engine.aclose()
    except Exception as exc:  # shutdown must surface any fault, not crash
        _render_error(exc)
        return _EXIT_ERROR
    return _EXIT_OK


async def _drive_turn(
    engine: Engine,
    utterance: str,
    *,
    timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, relayed to the façade (ADR-0029 §4)
    approver: Callable[[Confirmation], bool],
) -> int:
    """Converse, render, and relay a confirmation if the engine parks one.

    A turn drives at most one step today (ADR-0042 §3), so at most one
    confirmation can arise; ``resume`` resolves it to ``EXECUTED`` or ``DENIED``.
    An :class:`AssistantError` from any stage is rendered and mapped to a non-zero
    exit code — the adapter surfaces the failure, it does not swallow it.
    """
    try:
        outcome = await engine.converse(utterance, timeout=timeout)
        _render_turn(outcome)
        step = outcome.step
        if step is not None and step.confirmation is not None:
            approved = approver(step.confirmation)
            resumed = await engine.resume(
                step.confirmation.token, approved=approved, timeout=timeout
            )
            _render_turn(resumed)
    except AssistantError as exc:
        _render_error(exc)
        return _EXIT_ERROR
    return _EXIT_OK


# --- rendering (ADR-0042 §4, §6: escaping is the adapter's, per target) --


def _safe(value: str) -> str:
    r"""Neutralise tool-supplied data for this terminal (ADR-0042 §4).

    "Safe" is target-specific, so the engine carries values verbatim and each
    adapter escapes for its own output. Here that means two things: replace
    non-printable control characters (an ANSI escape like ``\\x1b[2J`` a terminal
    would act on) with the replacement character, and escape Rich markup so a
    value like ``[red]`` is shown, not interpreted.
    """
    cleaned = "".join(ch if ch.isprintable() or ch in "\t " else "�" for ch in value)
    return escape(cleaned)


def _render_turn(outcome: TurnOutcome) -> None:
    """Render one turn's plan, degraded-memory notice, and step disposition."""
    turn = outcome.turn
    if turn.memory_degraded:
        console.print(
            "[yellow]Note:[/] personal memory was unavailable, so this answer is generic."
        )

    plan = turn.plan
    if plan.rationale:
        console.print(f"[bold]Plan:[/] {_safe(plan.rationale)}")
    if not plan.steps:
        console.print("[dim]No action was needed.[/]")
    for index, planned in enumerate(plan.steps, start=1):
        console.print(f"  {index}. {_safe(planned.intent)} [dim]({_safe(planned.capability)})[/]")

    step = outcome.step
    if step is not None and step.confirmation is None:
        _render_disposition(step.disposition, step.tool_id)


def _render_disposition(disposition: Disposition, tool_id: str | None) -> None:
    """Render the outcome of the driven step (ADR-0042 §3)."""
    tool = _safe(tool_id) if tool_id is not None else "the selected tool"
    messages = {
        Disposition.EXECUTED: f"[green]Done.[/] Ran {tool}.",
        Disposition.DENIED: "[red]Declined.[/] The policy did not permit this action.",
        Disposition.NO_CAPABLE_TOOL: "[dim]No tool is available for this step yet.[/]",
        Disposition.AMBIGUOUS_CAPABILITY: "[dim]Several tools could do this; none was chosen.[/]",
    }
    message = messages.get(disposition)
    if message is not None:
        console.print(message)


def _render_confirmation(confirmation: Confirmation) -> None:
    """Render a parked action so a person can judge it (ADR-0042 §4)."""
    console.print("\n[bold yellow]Confirmation required[/]")
    console.print(f"  Tool: {_safe(confirmation.tool_id)} — {_safe(confirmation.tool_description)}")
    if confirmation.parameters:
        console.print("  With:")
        for key, raw in confirmation.parameters.items():
            console.print(f"    {_safe(str(key))} = {_safe(str(raw))}")
    console.print(f"  Why: {_safe(confirmation.reason)}")


def _prompt_for_approval(confirmation: Confirmation) -> bool:
    """Render the confirmation and read the human's yes/no (I/O; ADR-0042 §6)."""
    _render_confirmation(confirmation)
    return typer.confirm("Proceed?", default=False)


def _render_error(exc: Exception) -> None:
    """Render an error for the terminal, without leaking a traceback.

    Accepts any ``Exception`` — an :class:`AssistantError` from a stage, or the
    ``ExceptionGroup`` :meth:`Engine.aclose` raises when an owned resource fails to
    close — and shows the actual cause. For a group that means the **contained**
    messages (recursively), not just the group's summary, so an operator sees
    *which* resource failed, not merely that one did.
    """
    console.print(f"[red]Error:[/] {_safe('; '.join(_leaf_messages(exc)))}")


def _leaf_messages(exc: BaseException) -> list[str]:
    """The messages of ``exc``, flattening a (possibly nested) exception group."""
    if isinstance(exc, BaseExceptionGroup):
        return [message for sub in exc.exceptions for message in _leaf_messages(sub)]
    return [str(exc)]


if __name__ == "__main__":
    app()
