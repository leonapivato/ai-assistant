"""Command-line interface — the first adapter onto the engine (ADR-0042 §7).

Kept intentionally thin (golden rule 3, ADR-0042 §6): it parses input into an
utterance, obtains the façade from the composition root, drives one turn with
``converse``/``resume``, renders the final :class:`~ai_assistant.orchestration.TurnOutcome`
with Rich, relays the **opaque** continuation token on a confirmation, and closes
the façade on exit. It authors no permission ruling, plans nothing, selects no
tool, and touches no subsystem directly — all of that is the engine's, reached
only through the façade (ADR-0042 §6). Registered as the ``assistant`` console
script in ``pyproject.toml``.

``beliefs`` and ``forget`` are the belief-inspection surface (ADR-0073 §7): they
render what the engine already computed and destroy what the user names. The
*band* on each row arrives on the DTO — :meth:`~ai_assistant.orchestration.Belief`
is projected in the engine so ADR-0072 §1's classification never lands here — and
this module reads no clock for them and re-filters nothing.

v1 renders the *final* state of each call; streaming is deferred (ADR-0042 §5).
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, assert_never

import typer
from rich.console import Console
from rich.markup import escape

from ai_assistant import __version__
from ai_assistant.app import build_engine
from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import AssistantError
from ai_assistant.core.logging import configure_logging
from ai_assistant.core.types import BeliefBand, FeedbackEvent, FeedbackKind, MemoryKind
from ai_assistant.orchestration import Disposition, LearnDecision

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.orchestration import (
        Belief,
        Confirmation,
        Engine,
        LearnOutcome,
        TurnOutcome,
    )

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

#: How ``--memory-kind`` defaults from ``--kind`` when the user does not give one.
#: Follows ``FeedbackEvent``'s own guidance — "a fact becomes a ``SemanticMemory``,
#: not a preference" — so a correction lands as a semantic fact and a stated
#: preference as a preference. Exhaustive over ``FeedbackKind``.
_DEFAULT_MEMORY_KIND = {
    FeedbackKind.CORRECTION: MemoryKind.SEMANTIC,
    FeedbackKind.PREFERENCE: MemoryKind.PREFERENCE,
}

#: One human-readable line per :class:`~ai_assistant.orchestration.LearnDecision`,
#: rendered under a ``learn`` result. Exhaustive: every member has a message, so a
#: new decision surfaces at type-check time rather than as a missing line.
_LEARN_MESSAGES = {
    LearnDecision.STORED: "Stored a new memory.",
    LearnDecision.REINFORCED: "Reinforced an existing memory.",
    LearnDecision.SUPERSEDED: "Replaced a prior memory.",
    LearnDecision.REJECTED: "Rejected — nothing was stored.",
    # ASK_USER writes nothing, and there is no memory-confirmation flow yet (memory
    # decisions are not what `assistant resume` recovers — that is permission action
    # confirmations, ADR-0052). So say plainly it was not stored and cannot be
    # confirmed from here, rather than implying a follow-up that does not exist (#422
    # review).
    LearnDecision.DEFERRED: "Not stored — this needs review, which cannot be done from here yet.",
    LearnDecision.STORED_TEMPORARILY: "Stored temporarily.",
}


#: One past the largest value ``--limit``/``--offset`` may take, mirroring the range
#: ``MemoryStore.list_beliefs`` refuses outside of (ADR-0073 §2). Checked here at
#: parse time because that refusal is a ``ValueError``, not an ``AssistantError``,
#: so it would escape the command's error boundary as a traceback (see
#: :func:`_page_argument`).
_PAGE_BOUND = 2**63

#: The ``learn`` command's enum-typed options, defined once at module scope. Typer
#: options for an ``Enum`` parameter are hoisted here rather than called inline in
#: the signature, the module-level-singleton form ruff's B008 requires (a plain
#: ``str``/``bool`` option is exempt, an enum-annotated one is not).
_LEARN_KIND_OPTION = typer.Option(
    ..., "--kind", help="Whether this corrects a fact ('correction') or states a preference."
)
_LEARN_MEMORY_KIND_OPTION = typer.Option(
    None,
    "--memory-kind",
    help=(
        "Which typed memory to establish. Defaults from --kind "
        "(correction -> semantic, preference -> preference); set it to override."
    ),
)

#: The ``beliefs`` command's enum-typed filters, hoisted to module scope for the
#: same reason the ``learn`` ones are. Each may be repeated; the values within one
#: flag are a union and the two flags compose by conjunction, which is the façade's
#: own rule relayed unchanged (ADR-0073 §1).
_BELIEFS_BAND_OPTION = typer.Option(
    None,
    "--band",
    help="Only show beliefs in this band (repeatable). Default: every band.",
)
_BELIEFS_KIND_OPTION = typer.Option(
    None,
    "--kind",
    help="Only show beliefs of this memory kind (repeatable). Default: every kind.",
)


def _utcnow() -> datetime:
    """The wall-clock 'now' the ``learn`` command stamps on a ``FeedbackEvent``.

    The same module-level clock convention every subsystem uses
    (``datetime.now(UTC)``); ``FeedbackEvent.created_at`` is a
    :data:`~ai_assistant.core.types.UtcInstant`, so the reading is validated as
    timezone-aware UTC at construction. Named so a test can substitute it for a
    deterministic timestamp.
    """
    return datetime.now(UTC)


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


def _present_content(value: str) -> str:
    """Reject blank ``learn`` content during Typer's parameter parsing.

    ``FeedbackEvent.content`` rejects whitespace-only text with a ``ValidationError``
    (``core/types.py``), which is **not** an :class:`AssistantError`, so constructing
    the event on blank input would escape both of :func:`_learn_feedback`'s error
    boundaries as an uncaught traceback with no controlled exit code — the failure
    ADR-0042 §7 forbids. Catching it here instead makes it a normal usage error
    (exit code 2), before any engine is built, mirroring :func:`_positive_finite_seconds`.
    The value is returned untouched; the event's own validator trims it.
    """
    if not value.strip():
        msg = "must not be blank"
        raise typer.BadParameter(msg)
    return value


def _page_argument(value: int) -> int:
    """Reject a ``--limit``/``--offset`` the store would refuse (ADR-0073 §2).

    ``MemoryStore.list_beliefs`` raises ``ValueError`` for a paging argument outside
    ``[0, 2**63)`` — refused rather than clamped, because a negative one reaches
    SQLite as ``LIMIT -1`` (no limit at all) and an over-wide one raises
    ``OverflowError`` out of the driver. A ``ValueError`` is **not** an
    :class:`AssistantError`, so it would escape :func:`_list_beliefs`'s error
    boundary as an uncaught traceback with no controlled exit code — the failure
    ADR-0042 §7 forbids. Catching it during Typer's parameter parsing makes it a
    normal usage error (exit code 2) before any engine is built, exactly as
    :func:`_present_content` does for blank ``learn`` content.
    """
    if not 0 <= value < _PAGE_BOUND:
        msg = f"must be between 0 and {_PAGE_BOUND - 1}"
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


@app.command()
def resume(
    timeout_seconds: float = typer.Option(
        60.0,
        "--timeout",
        callback=_positive_finite_seconds,
        help="Per-attempt deadline for the engine's work, in seconds (positive).",
    ),
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Approve every pending confirmation without prompting."
    ),
) -> None:
    """Answer confirmations parked by an earlier run — including across a restart.

    A confirmable action from a previous ``ask`` may still be awaiting an answer: it
    was parked durably (ADR-0052) and survives a process exit. This reconstructs
    each such confirmation from stored state, shows the action and the policy's
    reason, and relays the opaque token back to the engine to resolve it.
    """
    code = asyncio.run(_resume_pending(timeout_seconds=timeout_seconds, assume_yes=yes))
    raise typer.Exit(code)


@app.command()
def learn(
    content: str = typer.Argument(
        ..., help="The correction or preference, in your own words.", callback=_present_content
    ),
    kind: FeedbackKind = _LEARN_KIND_OPTION,
    about: str | None = typer.Option(
        None, "--about", "-a", help="Optional scope this feedback is about, e.g. 'units'."
    ),
    memory_kind: MemoryKind | None = _LEARN_MEMORY_KIND_OPTION,
) -> None:
    """Teach the assistant from a correction or a stated preference.

    Turns what you say into a ``FeedbackEvent`` and hands it to the engine, which
    folds it into long-term memory. ``--memory-kind`` defaults from ``--kind`` and
    can be overridden. The result is a short summary of what memory did with it —
    stored, reinforced, or superseded.
    """
    resolved_memory_kind = memory_kind if memory_kind is not None else _DEFAULT_MEMORY_KIND[kind]
    code = asyncio.run(
        _learn_feedback(content, kind=kind, memory_kind=resolved_memory_kind, subject=about)
    )
    raise typer.Exit(code)


@app.command()
def beliefs(
    band: list[BeliefBand] | None = _BELIEFS_BAND_OPTION,
    kind: list[MemoryKind] | None = _BELIEFS_KIND_OPTION,
    limit: int = typer.Option(
        50,
        "--limit",
        callback=_page_argument,
        help="How many beliefs to show at most.",
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        callback=_page_argument,
        help="How many beliefs to skip before the page begins.",
    ),
) -> None:
    """List what the assistant currently believes about you, newest revision first.

    Each belief is shown with the band it is held in, how strongly, why it is held,
    and the id ``assistant forget`` takes. Only *live* beliefs are listed: one the
    assistant has since revised is history, not a belief it holds, and it is
    reachable through a data export rather than here.

    There is no total count — ask for the next page to find out whether there is
    more.
    """
    # An absent repeatable flag arrives as an empty list, which the façade would read
    # as "select nothing" — the deliberate meaning of an *explicitly* empty filter
    # (ADR-0073 §1). A CLI has no way to say that and no reason to, so absent and
    # empty both become None, "every band"/"every kind".
    code = asyncio.run(
        _list_beliefs(bands=band or None, kinds=kind or None, limit=limit, offset=offset)
    )
    raise typer.Exit(code)


@app.command()
def forget(
    belief_id: str = typer.Argument(..., help="The id of the belief to destroy."),
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the prompt. The belief is still shown first."
    ),
) -> None:
    """Destroy one belief, after showing you what it is.

    The belief is rendered — with what forgetting it costs, which differs by band —
    and destroyed only once you agree. ``--yes`` skips the question, not the
    rendering.

    Forgetting **destroys**: nothing is kept, not even in an export. To fix a belief
    rather than lose it, use ``assistant learn --kind correction``, which retires the
    old belief and keeps it on the record.
    """
    code = asyncio.run(_forget_belief(belief_id, assume_yes=yes))
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


async def _resume_pending(*, timeout_seconds: float, assume_yes: bool) -> int:
    """Recover durably-parked confirmations, answer them, and close the engine (ADR-0052).

    The restart-recovery counterpart to :func:`_ask`: it builds the engine over the
    same durable stores an earlier run wrote, asks the façade for the confirmations
    still awaiting an answer, and resolves each. One error boundary spans every
    stage that can fail — loading settings, building the engine, recovering,
    resuming, and shutdown — so an :class:`AssistantError` is rendered and mapped to
    a non-zero exit code rather than escaping (ADR-0042 §7).
    """
    timeout = timedelta(seconds=timeout_seconds)  # already validated positive + finite
    # _drive_resume renders each recovered action itself (below), so the approver
    # only decides yes/no — a bare confirm, not _prompt_for_approval, or the action
    # would be rendered twice interactively.
    approver: Callable[[Confirmation], bool] = (
        (lambda _confirmation: True) if assume_yes else _confirm
    )
    try:
        settings = load_settings()
        configure_logging(settings)
        engine = build_engine(settings)
    except AssistantError as exc:
        _render_error(exc)
        return _EXIT_ERROR

    try:
        code = await _drive_resume(engine, timeout=timeout, approver=approver)
    finally:
        shutdown_code = await _close(engine)
    return max(code, shutdown_code)


async def _learn_feedback(
    content: str, *, kind: FeedbackKind, memory_kind: MemoryKind, subject: str | None
) -> int:
    """Load settings, build the engine, submit the feedback, and close it (ADR-0042 §2, §7).

    The correction-leg counterpart to :func:`_ask`. It builds the
    :class:`~ai_assistant.core.types.FeedbackEvent` from the parsed flags — parsing
    input into the engine's request type is the adapter's own job (ADR-0042 §6) —
    then one error boundary spans every stage that can fail: loading settings,
    configuring logging, constructing the engine, the learn call, and shutdown, so
    an :class:`AssistantError` is rendered and mapped to a non-zero exit code rather
    than escaping (§7). The composition root builds the façade; this adapter closes
    it. Returns the process exit code.
    """
    event = FeedbackEvent(
        kind=kind,
        memory_kind=memory_kind,
        content=content,
        subject=subject,
        created_at=_utcnow(),
    )
    try:
        settings = load_settings()
        configure_logging(settings)
        engine = build_engine(settings)
    except AssistantError as exc:
        _render_error(exc)
        return _EXIT_ERROR

    try:
        code = await _drive_learn(engine, event)
    finally:
        shutdown_code = await _close(engine)
    return max(code, shutdown_code)


async def _list_beliefs(
    *,
    bands: list[BeliefBand] | None,
    kinds: list[MemoryKind] | None,
    limit: int,
    offset: int,
) -> int:
    """Load settings, build the engine, list the beliefs, and close it (ADR-0073 §7).

    The inspection counterpart to :func:`_ask`. One error boundary spans every stage
    that can fail — loading settings, configuring logging, constructing the engine,
    the read, and shutdown — so an :class:`AssistantError` is rendered and mapped to
    a non-zero exit code rather than escaping (ADR-0042 §7). The paging arguments
    were already checked against the store's accepted range at parse time
    (:func:`_page_argument`), so the one failure that is not an ``AssistantError``
    cannot reach here.
    """
    try:
        settings = load_settings()
        configure_logging(settings)
        engine = build_engine(settings)
    except AssistantError as exc:
        _render_error(exc)
        return _EXIT_ERROR

    try:
        code = await _drive_beliefs(engine, bands=bands, kinds=kinds, limit=limit, offset=offset)
    finally:
        shutdown_code = await _close(engine)
    return max(code, shutdown_code)


async def _forget_belief(belief_id: str, *, assume_yes: bool) -> int:
    """Load settings, build the engine, run the deletion ceremony, and close it.

    The deletion counterpart to :func:`_ask`, with the same single error boundary
    (ADR-0042 §7). ``--yes`` supplies the answer but not the rendering: the belief is
    displayed either way, because a person cannot consent to destroying something
    they were not shown and a non-interactive approval must not destroy what the user
    never saw (ADR-0073 §5, ADR-0052 §4).
    """
    confirm: Callable[[Belief], bool] = (lambda _belief: True) if assume_yes else _confirm_forget
    try:
        settings = load_settings()
        configure_logging(settings)
        engine = build_engine(settings)
    except AssistantError as exc:
        _render_error(exc)
        return _EXIT_ERROR

    try:
        code = await _drive_forget(engine, belief_id, confirm=confirm)
    finally:
        shutdown_code = await _close(engine)
    return max(code, shutdown_code)


async def _drive_beliefs(
    engine: Engine,
    *,
    bands: list[BeliefBand] | None,
    kinds: list[MemoryKind] | None,
    limit: int,
    offset: int,
) -> int:
    """Ask the façade for one page of beliefs and render it (ADR-0073 §7).

    The adapter relays the filters and renders what comes back. It re-filters
    nothing, re-orders nothing, reads no clock, and computes no band — the page's
    membership and order are the store's contract and each row's band was projected
    in the engine (ADR-0072 §7, ADR-0073 §7).
    """
    try:
        page = await engine.beliefs(bands=bands, kinds=kinds, limit=limit, offset=offset)
    except AssistantError as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_beliefs(page, limit=limit, offset=offset)
    return _EXIT_OK


async def _drive_forget(
    engine: Engine, belief_id: str, *, confirm: Callable[[Belief], bool]
) -> int:
    """Show the belief, take the answer, and destroy it if the answer is yes.

    Show-then-confirm, in that order (ADR-0073 §5): the render is taken as late as
    it can be — immediately before the question — so the window in which a write can
    land between what was shown and what is destroyed is the human's answering time
    and nothing longer. That window is named rather than closed, and the consent
    collected is consent to forget *the belief that id names*, which is what
    :func:`_render_forget_prompt` says.

    A refusal is a valid outcome and exits 0. An id naming no live belief, and a
    delete that finds nothing left to destroy, are both reported and exit non-zero
    (ADR-0073 §7).
    """
    try:
        belief = await engine.belief(belief_id)
        if belief is None:
            _render_no_such_belief(belief_id)
            return _EXIT_ERROR
        _render_forget_prompt(belief)
        if not confirm(belief):
            console.print("[dim]Left alone. Nothing was forgotten.[/]")
            return _EXIT_OK
        destroyed = await engine.forget(belief.id)
    except AssistantError as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if not destroyed:
        console.print("[yellow]Nothing to forget:[/] that belief was already gone.")
        return _EXIT_ERROR
    console.print("[green]Forgotten.[/] That belief is destroyed — it is in no export.")
    return _EXIT_OK


async def _drive_resume(
    engine: Engine,
    *,
    timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, relayed to the façade (ADR-0029 §4)
    approver: Callable[[Confirmation], bool],
) -> int:
    """Recover the pending confirmations and resolve each one.

    Renders each recovered action so a person can judge it, collects the yes/no,
    and relays the opaque token via ``resume`` — the adapter transports consent, it
    authors no ruling (ADR-0042 §6). Rendering happens here, **before** the
    approver, so the action and the policy's reason are shown whether the answer is
    interactive or supplied by ``--yes`` (ADR-0052 §4): a non-interactive approval
    must not run a recovered action the user never saw. An :class:`AssistantError`
    from any stage is rendered and mapped to a non-zero exit code.
    """
    try:
        pending = await engine.pending_confirmations()
        if not pending:
            console.print("[dim]Nothing is awaiting confirmation.[/]")
            return _EXIT_OK
        for confirmation in pending:
            _render_confirmation(confirmation)
            approved = approver(confirmation)
            resumed = await engine.resume(confirmation.token, approved=approved, timeout=timeout)
            _render_turn(resumed)
    except AssistantError as exc:
        _render_error(exc)
        return _EXIT_ERROR
    return _EXIT_OK


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


async def _drive_learn(engine: Engine, event: FeedbackEvent) -> int:
    """Submit one feedback event and render what memory did with it (ADR-0042 §3, §6).

    The correction leg of the pipeline: the adapter conveys the feedback and renders
    the engine's :class:`~ai_assistant.orchestration.LearnOutcome` summary; it
    authors no memory write and reaches no subsystem (ADR-0042 §6). An
    :class:`AssistantError` from any stage is rendered and mapped to a non-zero exit
    code — the adapter surfaces the failure, it does not swallow it.
    """
    try:
        outcome = await engine.learn(event)
        _render_learn(outcome)
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
    """Render one turn's plan, degraded-memory notice, and step disposition.

    ``outcome.turn`` is ``None`` on a resume driven from a **recovered** park
    (ADR-0052 §3) — a confirmation reconstructed from durable state after a restart
    has no live turn to render — so only the step disposition is shown there. The
    action itself was already shown from the recovered confirmation before the user
    answered.
    """
    turn = outcome.turn
    if turn is not None:
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
            console.print(
                f"  {index}. {_safe(planned.intent)} [dim]({_safe(planned.capability)})[/]"
            )

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


def _render_learn(outcome: LearnOutcome) -> None:
    """Render what one piece of feedback did to memory (ADR-0042 §6).

    A short human-readable confirmation: a header counting the updates memory made,
    then one line per proposal naming the ruling and its reason. The reason is
    engine-supplied data, so it is neutralised for this terminal like any other
    (``_safe``, ADR-0042 §4). Feedback that proposed no update at all is reported as
    such rather than as a silent success.
    """
    if not outcome.results:
        console.print("[dim]Noted — nothing in that needed a memory update.[/]")
        return
    console.print(
        f"[green]Learned.[/] Folded {len(outcome.results)} update(s) into memory "
        f"({outcome.stored} stored)."
    )
    for summary in outcome.results:
        console.print(f"  - {_LEARN_MESSAGES[summary.decision]} [dim]({_safe(summary.reason)})[/]")


def _when(instant: datetime) -> str:
    """Render an instant the engine supplied, in UTC.

    Pure formatting of a value that arrived on the DTO — no clock is read here, and
    none may be (golden rule 3): every time this surface shows is one memory
    recorded, never one this process observed.
    """
    return instant.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _why(belief: Belief) -> str:
    """Why this belief is held — band-dependent (ADR-0073 §4).

    Total over :class:`~ai_assistant.core.types.BeliefBand` and mechanically so: the
    wildcard does nothing but ``assert_never``, so a band added to ``core`` without a
    line here fails the gate rather than rendering an empty reason. The same shape
    ``band_of`` itself uses.

    The answer is complete for one band and owed for two, and the wording keeps
    ADR-0073 §4's two floors:

    * **Derived** — the citations are reported as a *count* and named as not yet
      showable. They are never rendered as evidence, and never silently dropped;
      the ids are not even carried to this module
      (:class:`~ai_assistant.orchestration.Belief` holds only the count), so no
      renderer here can pass one off as the warrant. Resolving them into readable
      evidence is due with the first producer of derived beliefs (#431).
    * **Attested** — it is named as someone else's report, so it reads as neither
      the user's word nor the assistant's inference, and the line says outright that
      ``Last revised`` is the assistant's clock rather than the source's.
    """
    match belief.band:
        case BeliefBand.ASSERTED:
            return "you told me, and your own word is the whole of it."
        case BeliefBand.DERIVED:
            if belief.evidence_count == 0:
                return "I worked it out, and no supporting evidence was recorded."
            return (
                f"I worked it out from {belief.evidence_count} piece(s) of evidence, which "
                "I cannot show you yet."
            )
        case BeliefBand.ATTESTED:
            return (
                "a source you connected reported it — neither your word nor my inference. "
                "Which source, and when it said so, are not recorded, so 'Last revised' "
                "below is when I changed my mind and not when the source spoke."
            )
        case _:  # pragma: no cover - exhaustive
            assert_never(belief.band)


def _forget_warning(band: BeliefBand) -> str:
    """What forgetting a belief in this band costs (ADR-0073 §5).

    The ceremony is uniform in mechanism and asymmetric in message, because the
    consequence is: an assertion is not re-derivable and losing one is unrecoverable
    (ADR-0072 §1, ADR-0038 §2), while a derived or attested belief loses the belief
    and not its origin. The obligation is to represent a deletion as neither more
    final than it is nor less. Total over the bands, like :func:`_why`.
    """
    match band:
        case BeliefBand.ASSERTED:
            return "You told me this. Forgetting it is permanent — nothing can work it out again."
        case BeliefBand.DERIVED:
            return (
                "I worked this out. Forgetting it destroys the belief but not what I "
                "worked it out from, so I may reach it again."
            )
        case BeliefBand.ATTESTED:
            return (
                "A connected source reported this. Forgetting it destroys my copy but "
                "not the source, so a later sync may bring it back."
            )
        case _:  # pragma: no cover - exhaustive
            assert_never(band)


def _render_belief(belief: Belief) -> None:
    """Render one belief with everything ADR-0073 §4 requires it to convey.

    The band leads the row and is never left to be implied by position; confidence,
    kind, the canonical content, why it is held, when the assistant last revised it
    and the id are all shown, as is the end of its validity window where one is set.
    Every listed belief is live, so an *open* window carries no information and is
    not rendered as though it did.

    Engine-supplied text — the content, the id — is neutralised for this terminal
    like any other (``_safe``, ADR-0042 §4). The band and kind are this system's own
    closed vocabularies, not carried data.
    """
    console.print(
        f"\n  [bold cyan]{belief.band.value}[/] · {belief.kind.value} · "
        f"confidence {belief.confidence:.2f}"
    )
    console.print(f"  {_safe(belief.content)}")
    console.print(f"  [dim]Why:[/] {_why(belief)}")
    console.print(f"  [dim]Last revised:[/] {_when(belief.last_updated)}")
    if belief.valid_until is not None:
        console.print(f"  [dim]Believed until:[/] {_when(belief.valid_until)}")
    console.print(f"  [dim]id:[/] {_safe(belief.id)}")


def _render_beliefs(page: tuple[Belief, ...], *, limit: int, offset: int) -> None:
    """Render one page of beliefs (ADR-0073 §7).

    **No total is shown**, and none is available to show: "is there more" is answered
    by asking for the next page, so a full page says so and names the offset that
    would fetch it, rather than implying a count nobody computed.
    """
    if not page:
        console.print("[dim]No live belief matches.[/]")
        return
    console.print(f"[bold]{len(page)} belief(s)[/], most recently revised first.")
    for belief in page:
        _render_belief(belief)
    if limit and len(page) == limit:
        console.print(
            f"\n[dim]That is a full page; there may be more — try --offset {offset + limit}.[/]"
        )


def _render_forget_prompt(belief: Belief) -> None:
    """Show what is about to be destroyed, and what destroying it costs (ADR-0073 §5).

    Three things, in this order, because a person cannot consent to destroying
    something they were not shown (ADR-0042 §4, ADR-0052 §4):

    1. the belief itself, in full;
    2. the band-appropriate warning — what is lost, and what is not;
    3. what the confirmation actually covers. It is consent to forget **the belief
       that id names**, not a guarantee that what is destroyed is byte-for-byte what
       was just rendered: the show and the delete are two calls and the window
       between them is named rather than closed (ADR-0073 §5). And it destroys rather
       than retires, which is the contrast — kept versus destroyed — that a surface
       offering both a correction and a deletion owes (ADR-0073 §6).
    """
    console.print("\n[bold yellow]About to forget this belief[/]")
    _render_belief(belief)
    console.print(f"\n  [yellow]{_forget_warning(belief.band)}[/]")
    console.print(
        "  This destroys the record: nothing of it is kept, not even in an export. "
        "To fix it instead, use [bold]assistant learn --kind correction[/], which "
        "retires the old belief and keeps it on the record."
    )
    console.print(
        "  [dim]You are forgetting whatever belief that id names when you answer, "
        "which may have changed since it was shown.[/]"
    )


def _render_no_such_belief(belief_id: str) -> None:
    """Report an id that names no *live* belief (ADR-0073 §5).

    The read behind this surface is live-only, so an id naming a belief the assistant
    has since revised does not resolve and is declined rather than destroyed —
    deleting what cannot be displayed is exactly what the ceremony forbids. The right
    to erase such a record is not lost; what is missing is a surface for it, which
    belongs with the deferred history view (ADR-0073 §3, §10).
    """
    console.print(
        f"[yellow]No live belief has the id[/] {_safe(belief_id)}. "
        "It may never have existed, or it may have been revised or forgotten already — "
        "this surface shows and destroys only beliefs held right now."
    )


def _confirm_forget(_belief: Belief) -> bool:
    """Read the human's yes/no *without* rendering — the caller already displayed it.

    The counterpart to :func:`_confirm` on the deletion path (I/O; ADR-0042 §6).
    Defaults to **no**: the question is about destroying something irreversibly, so a
    bare Enter must not be the answer that destroys it.
    """
    return typer.confirm("Forget it?", default=False)


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


def _confirm(_confirmation: Confirmation) -> bool:
    """Read the human's yes/no *without* rendering — the caller already displayed it.

    Used by the ``resume`` flow, where :func:`_drive_resume` renders each recovered
    action before prompting, so rendering here too would show it twice (I/O; §6).
    """
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
