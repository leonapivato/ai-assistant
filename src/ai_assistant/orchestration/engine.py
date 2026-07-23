"""The engine façade an interface adapter drives (ADR-0042 §1, §3, §4).

:class:`Engine` is the single, concrete surface `interfaces/` depends on. It is
**not** a Protocol (ADR-0042 §1): there is one orchestration engine and one class
of consumer, so a contract modelling substitutability would encode a
substitutability that does not exist, and pay a triad's cost for it. The stage
objects — :class:`~ai_assistant.orchestration.loop.LearningLoop` and
:class:`~ai_assistant.orchestration.runner.StepRunner` — become collaborators the
façade *composes*, addressable to the adapter only through the façade's own
methods (ADR-0042 §1). Sequencing them is the orchestration this package owns; an
adapter doing it would pull pipeline logic into `interfaces/` (ADR-0042
Alternatives).

Two call shapes, mirroring the two the engine already has (ADR-0042 §3):

* :meth:`Engine.converse` runs one turn and drives the step it produces;
* :meth:`Engine.resume` answers a parked confirmation and continues that step.

Both return a :class:`TurnOutcome` — one result in, one result out. What the
adapter may and may not do with it is ADR-0042 §6: it renders the content,
collects the human's yes/no, and relays an **opaque** :class:`ContinuationToken`;
it never authors a permission outcome, and it never inspects the token.

**Scope today.** ``respond`` "still ends at the plan" and the multi-step
plan-driving stage — ordering, dependencies and cancellation across a plan's
steps — is "the next slice" (`loop.py`). So a turn drives **at most one** step,
the plan's first, through the already-built :class:`StepRunner`; the rest await
that stage. This is the transitional reach ADR-0042 §3 names when it says
per-attempt and per-request coincide "today", and §7's "the CLI's reach grows
with the engine's". The *contract* — these signatures and DTOs — is fixed now, so
the adapter is not rewritten as those stages land.

Nothing concrete is imported: every collaborator arrives by injection and is seen
only through its Protocol or through this package's own stage objects (CLAUDE.md
golden rule 1). The wiring that constructs the concrete subsystems is the
composition root's, a separate package (ADR-0042 §2).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.errors import PlanningError
from ai_assistant.orchestration.runner import Disposition

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import timedelta

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import ExecutionState, FrozenJsonMapping
    from ai_assistant.orchestration.loop import LearningLoop, TurnResult
    from ai_assistant.orchestration.runner import StepDisposition, StepRunner

_log = structlog.get_logger(__name__)


def _uuid() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class ContinuationToken:
    """An opaque handle to a parked step (ADR-0042 §4).

    The adapter stores this and relays it back on :meth:`Engine.resume`. It
    **must not** interpret, construct, or re-derive its contents: an adapter that
    branched on the token to decide allow/deny would be authoring a permission
    outcome in `interfaces/`, exactly what ADR-0042 §4 forbids. The ``handle`` is
    deliberately meaningless outside the :class:`Engine` instance that minted it —
    it names an entry in that instance's private table, nothing more.

    **Lifetime is process-scoped.** The table lives in the engine object, so a
    handle does not survive a restart. Making the continuation durable across a
    restart is a separate concern ADR-0042's Revisit-if clause ties to #242; until
    then a token is valid only within the process (and the ``Engine``) that
    produced it.
    """

    handle: str


@dataclass(frozen=True, slots=True)
class Confirmation:
    """What a person needs to judge a parked action (ADR-0042 §4).

    The engine assembles this because the adapter may not read the audit trail or
    a ``PermissionDecision`` to recover it (ADR-0042 §6). The values are carried
    **as data, not pre-formatted**: "safe" is target-specific — a parameter value
    holding an ANSI escape or Rich markup is valid data a terminal would interpret
    as a control sequence, but an HTTP front end encodes differently — so escaping
    is each adapter's own job on render (ADR-0042 §4).

    Attributes:
        tool_id: The selected tool's id, human-readable and shown to the user.
        tool_description: What the tool does, from the declaration ruled on.
        parameters: The arguments it would run with, as structured data.
        reason: The recorded ``CONFIRM`` ruling's own ``reason`` — the policy's
            explanation of *why* confirmation is required (an off-device
            disclosure, an unknown cost). Not optional: ``PermissionRuling.reason``
            is "text shown to the user at the moment they decide", so a prompt
            omitting it would drop what the user most needs (ADR-0042 §4).
        token: The opaque continuation to relay back on :meth:`Engine.resume`.
    """

    tool_id: str
    tool_description: str
    parameters: FrozenJsonMapping
    reason: str
    token: ContinuationToken


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """What became of the one step a turn drove (ADR-0042 §3, §4).

    Richer than the raw stage :class:`~ai_assistant.orchestration.runner.StepDisposition`,
    which carries only ``state``, ``decision_id`` and ``tool_id`` — a bare tool id
    is not enough for a human to judge "send email to X" (ADR-0042 §4). This is
    the concrete reason the façade returns its own result type rather than a raw
    stage DTO (ADR-0042 §1).

    Attributes:
        disposition: Which of the five outcomes the step reached.
        state: The durable execution state after the last transition committed.
        tool_id: The tool selected, or ``None`` where none was.
        confirmation: Present **iff** ``disposition`` is
            :attr:`~ai_assistant.orchestration.runner.Disposition.AWAITING_CONFIRMATION`
            — the content and token the adapter renders and relays.
    """

    disposition: Disposition
    state: ExecutionState
    tool_id: str | None = None
    confirmation: Confirmation | None = None


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    """One unit of what a call produced (ADR-0042 §3).

    A frozen dataclass in `orchestration`, like
    :class:`~ai_assistant.orchestration.loop.TurnResult` and
    :class:`~ai_assistant.orchestration.runner.StepDisposition`, for their reason:
    it crosses no *subsystem* boundary, only `interfaces`, which already depends
    on this package. It graduates to ``core`` on the day a subsystem needs to
    receive one (ADR-0042 §1).

    Attributes:
        turn: The turn's goal, context, retrieved memories, plan, and — obliged to
            be surfaced, not swallowed — whether retrieval degraded
            (:attr:`~ai_assistant.orchestration.loop.TurnResult.memory_degraded`).
        step: The disposition of the step the engine drove, or ``None`` when the
            plan had no step to drive. On a resumption this is the resolved step.
    """

    turn: TurnResult
    step: StepOutcome | None = None


@dataclass(frozen=True, slots=True)
class _Parked:
    """The private state one continuation token names (never seen by an adapter)."""

    turn: TurnResult
    execution_id: str
    step_id: str
    confirmation_id: str


class Engine:
    """The concrete façade an interface adapter drives (ADR-0042 §1).

    Composes the engine's stage objects behind two calls and one shutdown path.
    It is handed the stage objects and the ``PlanStore`` — the same instance its
    ``runner`` was wired with — by the composition root, the one layer licensed to
    construct concretes (ADR-0042 §2).
    """

    def __init__(
        self,
        *,
        loop: LearningLoop,
        runner: StepRunner,
        plans: PlanStore,
        closers: Sequence[Callable[[], Awaitable[None]]] = (),
        id_factory: Callable[[], str] = _uuid,
    ) -> None:
        """Wire the façade from injected collaborators.

        **``plans`` must be the very instance ``runner`` holds.** No type can say
        so, so it is a composition-root obligation (ADR-0042 §2, the same shape as
        ADR-0028 §4's writer/store rule): the façade persists the turn's plan and
        starts the execution it drives through ``plans``, and reloads it through
        ``plans`` to resume, so a façade wired to a *second* store would drive and
        resume nothing while reporting success. The parked step's confirmation
        content rides back on the runner's own disposition
        (:attr:`~ai_assistant.orchestration.runner.StepDisposition.decision`), so
        the façade needs no audit-trail handle of its own.

        Args:
            loop: The turn stage. :meth:`converse` calls its ``respond``.
            runner: The single-step stage (selection, permission, execution). Its
                ``registry``, ``policy``, ``plans`` and ``trail`` are already
                wired; the façade adds only ``plans`` for the reads a driver needs
                around it.
            plans: Durable planning state — the same instance ``runner`` holds.
                The façade persists the turn's goal and plan and starts the
                execution it drives, and reloads it to resume.
            closers: The resources the façade owns, as async close callables, in
                the order :meth:`aclose` must run them. The composition root hands
                these over so the façade is the defined owner that releases every
                connection on shutdown (ADR-0042 §2). Empty when the façade owns
                nothing (its collaborators are all in-memory).
            id_factory: Supplies opaque continuation-token handles; injectable so
                a test can assert a stable handle.
        """
        self._loop = loop
        self._runner = runner
        self._plans = plans
        self._closers = tuple(closers)
        self._id_factory = id_factory
        self._parked: dict[str, _Parked] = {}
        self._inflight: set[asyncio.Task[TurnOutcome]] = set()
        self._closing = False
        self._shutdown: asyncio.Task[None] | None = None

    async def converse(self, utterance: str, *, timeout: timedelta) -> TurnOutcome:  # noqa: ASYNC109 — the caller's budget, threaded to the seam which owns the deadline (ADR-0029 §4)
        """Run one turn and drive the step it produces (ADR-0042 §3).

        The adapter passes the user's raw utterance — unrewritten; intent is the
        engine's, not the adapter's (ADR-0042 §3). The turn is planned, then its
        **first** step is driven through :class:`StepRunner`; a multi-step plan
        has only that step driven today, the rest awaiting the plan-driving stage
        (module docstring).

        Args:
            utterance: What the user said, passed through untouched.
            timeout: The **per-attempt** budget (ADR-0029 §4, ADR-0042 §3),
                keyword-only and required — the contract has no spelling for
                "forever". Threaded to the executor for the one authorised call a
                driven step makes. It is *not* an overall wall-clock deadline for a
                multi-step request; that is a follow-on decided with the
                plan-driving stage (ADR-0042 §3).

        Returns:
            The turn's result and the disposition of the step it drove — including
            a parked confirmation to render and relay (ADR-0042 §4). ``step`` is
            ``None`` when the plan had no step.

        Raises:
            RuntimeError: If the engine is shutting down (:meth:`aclose` has been
                entered), so no new work is accepted.
            PlanningError: If the utterance is blank, a transition is rejected, or
                a clock reading is non-conforming — as the stages raise.
            ContextError: If context assembly failed outright.
            AuditError: If the trail would not accept or hand back a decision.
            ToolBindingError: If an authorised call fails its own revalidation.
        """
        self._reject_if_closing()
        return await self._tracked(self._converse(utterance, timeout=timeout))

    async def resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, threaded to the seam (ADR-0029 §4)
    ) -> TurnOutcome:
        """Answer a parked confirmation and continue its step (ADR-0042 §3, §4).

        The adapter relays the opaque ``token`` and the human's yes/no; it does
        **not** author the outcome. ``ActionPolicy.resolve`` — inside
        `permissions`, reached through the engine — is what turns ``approved`` into
        an ``ALLOW`` or ``DENY``, and only ``approved=False → DENY`` is guaranteed:
        ``approved=True`` may still be refused by the policy (ADR-0042 §4). The
        adapter conveys consent; the policy rules; the engine records and executes.

        Args:
            token: The opaque continuation the parking :meth:`converse` returned.
                Its contents are the engine's; the adapter never inspects them.
            approved: The human's answer. ``True`` conveys consent, which the
                policy may still refuse; ``False`` is a decision that yields
                ``DENY``.
            timeout: The per-attempt budget, as :meth:`converse`.

        Returns:
            The resumed turn: the parked turn's own result, and the step's
            resolved disposition (``EXECUTED`` or ``DENIED``).

        Raises:
            RuntimeError: If the engine is shutting down.
            PlanningError: If ``token`` names no parked step this engine holds — a
                token from a previous process, or one already resolved and evicted
                (its lifetime is process-scoped; ADR-0042 §4, the Revisit-if clause
                ties durable resume to #242).
            PermissionDeniedError: If the recorded decision is not a ``CONFIRM``
                about this parked step (``StepRunner`` refuses it).
            AuditError, ToolBindingError: As the stages raise.
        """
        self._reject_if_closing()
        return await self._tracked(self._resume(token, approved=approved, timeout=timeout))

    async def aclose(self) -> None:
        """Stop accepting work, drain what is in flight, then close owned resources.

        The shutdown path ADR-0042 §2 requires of a long-lived owner. It is
        **ordered, not abrupt**, because the concrete stores are connection-owning
        and each ``close()`` closes its connection directly without serialising
        against an in-flight operation — so nothing below the façade prevents a
        ``close()`` racing a store call still touching the connection; that
        ordering has to be the façade's (ADR-0042 §2).

        So this (a) stops accepting new calls, then (b) awaits every tracked
        operation to quiescence before closing. The tracking is of the underlying
        work itself, not merely the public call: a client cancelling its own
        ``converse()`` mid-call abandons the awaiting coroutine but not the work it
        started, which keeps using the connection a subsequent ``close()`` would
        shut. Each public call therefore runs as a **shielded** task this engine
        holds a reference to, so cancelling the caller leaves the underlying task
        running and tracked, and this drain still awaits it. Only then are the
        owned resources closed, in the order the composition root handed them.

        **The drain-and-close is one memoised task, and every caller awaits it
        shielded.** So cancelling *this* ``aclose`` — not only a ``converse`` —
        cannot abandon the closures half-done: the shutdown task keeps running to
        completion, and a subsequent ``aclose`` awaits the same task rather than
        returning early over resources that were never closed (ADR-0042 §2). This
        is what makes ``aclose`` idempotent *and* cancellation-safe; the closers
        run exactly once.
        """
        self._closing = True  # stop accepting new work at once (§2)
        if self._shutdown is None:
            self._shutdown = asyncio.ensure_future(self._drain_and_close())
        await asyncio.shield(self._shutdown)

    async def _drain_and_close(self) -> None:
        """Await every tracked operation, then close owned resources in order.

        The body of shutdown, run as one retained task so no caller's cancellation
        can leave it half-done (:meth:`aclose`). Draining is *awaiting*, never
        cancelling (ADR-0042 §2): a tracked task orphaned by a cancelled call is
        still using a connection ``close()`` would shut, so it is waited out first.

        **Every closer is attempted, even after one fails — including on
        cancellation.** ADR-0042 §2 requires the façade to release *every* owned
        connection on shutdown, so a closer that raises, or is cancelled (a
        ``CancelledError``, which is a ``BaseException`` and not an ``Exception``),
        must not skip the ones after it — a leaked connection is the exact failure
        the ordered close exists to prevent. Ordinary failures are collected and
        re-raised together once every resource has had its close attempted; a
        cancellation is re-raised after the same best-effort sweep, so it still
        propagates but not before the remaining resources are released.

        Raises:
            CancelledError: If closing a resource was cancelled. Re-raised after
                every remaining closer has been attempted.
            ExceptionGroup: If one or more closers raised (and none was cancelled).
                Every closer was still attempted; the group carries each failure.
        """
        if self._inflight:
            await asyncio.gather(*tuple(self._inflight), return_exceptions=True)
        errors: list[Exception] = []
        cancelled: asyncio.CancelledError | None = None
        for close in self._closers:
            try:
                await close()
            except asyncio.CancelledError as exc:  # sweep the rest, then propagate
                cancelled = exc
            except Exception as exc:  # every resource must still get its close attempt
                errors.append(exc)
        if cancelled is not None:
            if errors:
                _log.error(
                    "resource_close_failed_during_shutdown_cancellation",
                    failures=[str(exc) for exc in errors],
                )
            raise cancelled
        if errors:
            raise ExceptionGroup("one or more resources failed to close on shutdown", errors)

    async def _tracked(self, coro: Awaitable[TurnOutcome]) -> TurnOutcome:
        """Run ``coro`` as a tracked, shielded task, so shutdown can drain it.

        The task is what :meth:`aclose` awaits, and the shield is what keeps the
        underlying work alive when the *caller* cancels: a cancelled
        ``converse()``/``resume()`` abandons this await, but the task keeps running
        and stays tracked until it finishes, which is what lets the drain wait for
        work a cancelled call orphaned (ADR-0042 §2). The public methods reject a
        closing engine *before* building ``coro`` (:meth:`_reject_if_closing`), so
        this never receives work it must throw away un-awaited.
        """
        task: asyncio.Task[TurnOutcome] = asyncio.ensure_future(coro)
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        return await asyncio.shield(task)

    def _reject_if_closing(self) -> None:
        """Refuse new work once shutdown has begun (ADR-0042 §2 stops accepting).

        Raises:
            RuntimeError: If :meth:`aclose` has been entered.
        """
        if self._closing:
            msg = "the engine is shutting down and is not accepting new work"
            raise RuntimeError(msg)

    def _mint_handle(self) -> str:
        """Return a continuation handle not already naming a parked step.

        The injected factory supplies the opacity; the engine supplies the
        *uniqueness*. A factory that repeats a handle is disambiguated with a
        suffix rather than trusted or refused, so two parked steps never share a
        handle and neither is stranded — the loop is bounded by the number of
        parked steps. Called from :meth:`_converse` *before* the runner can park,
        so a raising factory fails with no durable state yet committed.
        """
        handle = self._id_factory()
        suffix = 0
        while handle in self._parked:
            suffix += 1
            handle = f"{self._id_factory()}#{suffix}"
        return handle

    async def _converse(self, utterance: str, *, timeout: timedelta) -> TurnOutcome:  # noqa: ASYNC109 — threaded through to the seam (ADR-0029 §4)
        """Plan the turn, persist it, then drive its first step if it has one."""
        turn = await self._loop.respond(utterance)
        self._check_plan_is_for_goal(turn)
        # Persist the goal and plan for *every* turn, before branching on whether
        # there is a step to drive: the plan is an auditable record of what the
        # system decided (ADR-0014 §2), and a no-action decision is a decision.
        await self._plans.save_goal(turn.goal)
        await self._plans.save_plan(turn.plan)
        if not turn.plan.steps:
            return TurnOutcome(turn=turn)
        first = turn.plan.steps[0]
        state = await self._plans.start_execution(turn.plan.id)
        # Mint the continuation handle *before* the runner can park the step, so a
        # raising or malformed id factory fails here — with no durable state yet —
        # rather than after `run` has committed AWAITING_APPROVAL, which would
        # strand a parked step with no token ever offered (ADR-0042 §4; #287). The
        # handle is a cheap string; if the step is not parked it is simply unused.
        handle = self._mint_handle()
        disposition = await self._runner.run(state, first.id, timeout=timeout)
        step = self._step_outcome(turn, disposition, handle=handle)
        return TurnOutcome(turn=turn, step=step)

    def _check_plan_is_for_goal(self, turn: TurnResult) -> None:
        """Refuse a plan that was not built for this turn's goal (ADR-0037 §2 in spirit).

        The pipeline reads its subjects from the store, not the caller's word, so a
        substituted subject is refused rather than checked for. Here the façade is
        the caller of the store, so it makes the one check no lower stage can: a
        conforming ``Planner`` returns a plan for the goal it was handed
        (``plan.goal_id == goal.id``), but a faulty or stale one could return an
        *already persisted* plan for a **previous** goal — which ``save_plan``
        would accept (its goal exists) and ``start_execution`` would then drive,
        executing actions planned for a different objective than the utterance.

        Raises:
            PlanningError: If the plan's ``goal_id`` is not this turn's goal.
        """
        if turn.plan.goal_id != turn.goal.id:
            msg = (
                f"the planner returned a plan for goal {turn.plan.goal_id!r}, not this turn's "
                f"goal {turn.goal.id!r}; driving it would execute actions planned for a "
                "different objective"
            )
            raise PlanningError(msg)

    async def _resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — threaded through to the seam (ADR-0029 §4)
    ) -> TurnOutcome:
        """Reload the parked execution and continue its step."""
        parked = self._parked.get(token.handle)
        if parked is None:
            msg = (
                "this token names no step awaiting confirmation in this engine; it may be "
                "from an earlier run of the process, or already resolved"
            )
            raise PlanningError(msg)
        state = await self._plans.get_execution(parked.execution_id)
        if state is None:
            msg = f"the store no longer holds execution {parked.execution_id!r} for this token"
            raise PlanningError(msg)
        disposition = await self._runner.resume(
            state,
            parked.step_id,
            confirmation_id=parked.confirmation_id,
            approved=approved,
            timeout=timeout,
        )
        # A resolving disposition is EXECUTED or DENIED, never AWAITING_CONFIRMATION,
        # so no new handle is needed here.
        step = self._step_outcome(parked.turn, disposition, handle=None)
        # Resolved once: a second answer would be refused by the trail's
        # single-resolution index anyway; evicting keeps the table bounded and
        # turns a replay into a clean "unknown token" (ADR-0042 §4).
        self._parked.pop(token.handle, None)
        return TurnOutcome(turn=parked.turn, step=step)

    def _step_outcome(
        self, turn: TurnResult, disposition: StepDisposition, *, handle: str | None
    ) -> StepOutcome:
        """Wrap a raw stage disposition, enriching a parked step (ADR-0042 §4).

        ``handle`` is the continuation handle minted *before* the runner could park
        (:meth:`_converse`); it is consumed only on the parked branch, and is
        ``None`` where no park is possible (a resumption).
        """
        confirmation: Confirmation | None = None
        if disposition.disposition is Disposition.AWAITING_CONFIRMATION:
            if handle is None:  # pragma: no cover — _converse pre-mints before any park
                # Only a resumption passes None, and a resolving disposition is never
                # AWAITING_CONFIRMATION, so reaching here would be an internal fault.
                msg = "a parked step reached rendering without a pre-minted continuation handle"
                raise PlanningError(msg)
            confirmation = self._confirmation(turn, disposition, handle)
        return StepOutcome(
            disposition=disposition.disposition,
            state=disposition.state,
            tool_id=disposition.tool_id,
            confirmation=confirmation,
        )

    def _confirmation(
        self, turn: TurnResult, disposition: StepDisposition, handle: str
    ) -> Confirmation:
        """Assemble the confirmation content around a pre-minted token (ADR-0042 §4).

        The tool declaration and the ruling ``reason`` come from the **recorded**
        ``CONFIRM`` the runner already read back and carried on its disposition
        (:attr:`~ai_assistant.orchestration.runner.StepDisposition.decision`) — the
        decision the user is being shown, which the adapter may not read itself
        (ADR-0042 §6). And ``handle`` was minted before the runner parked
        (:meth:`_converse`). So **no fallible work remains between parking the step
        and offering its token**: everything that could raise — reading the
        decision, calling the id factory — happened before ``run`` committed
        AWAITING_APPROVAL, so a parked step is never stranded without a continuation
        (#287). The parameters are the driven step's own, carried as data for the
        adapter to escape per target (ADR-0042 §4).
        """
        recorded = disposition.decision
        if recorded is None:  # pragma: no cover — StepRunner always sets it on this branch
            # A runner-contract violation, not caller input: a parked CONFIRM must
            # carry its decision so the step is resumable without a fallible re-read.
            msg = "a parked confirmation carries no recorded decision, so it cannot be rendered"
            raise PlanningError(msg)
        self._parked[handle] = _Parked(
            turn=turn,
            execution_id=disposition.state.id,
            step_id=turn.plan.steps[0].id,
            confirmation_id=recorded.id,
        )
        return Confirmation(
            tool_id=recorded.tool.id,
            tool_description=recorded.tool.description,
            parameters=turn.plan.steps[0].parameters,
            reason=recorded.ruling.reason,
            token=ContinuationToken(handle),
        )


__all__ = [
    "Confirmation",
    "ContinuationToken",
    "Engine",
    "StepOutcome",
    "TurnOutcome",
]
