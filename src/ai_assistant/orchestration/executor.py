"""The executor half of the tool-invocation contract (ADR-0029 §8).

:class:`StepExecutor` is the pipeline's ``execute`` stage: it claims a plan step,
runs one authorised :class:`~ai_assistant.core.types.ToolCall` through an
injected :class:`~ai_assistant.core.protocols.ToolInvoker`, and commits what came
back. Everything it knows about tools it learns through two Protocols —
``ToolRegistry`` and ``ToolInvoker`` — so nothing here imports `tools/`
(CLAUDE.md golden rule 1), and the interrupted-call rule it needs is
:attr:`~ai_assistant.core.types.ToolDefinition.interrupted_outcome`, in ``core``,
rather than a second copy of a safety-critical classification (ADR-0031 §1).

Three rules shape the whole module and are worth stating before the code:

- **The claim precedes the call** (ADR-0014 §4). The ``→ RUNNING`` transition is
  committed before ``invoke`` is reached, so the compare-and-swap in ADR-0014 §5
  is what stops two workers acting. Everything that can go wrong afterwards
  therefore goes wrong against a step that is already durably ``RUNNING``, which
  is why every exit path here commits something.
- **Retry is scheduled only from a ``ToolResult``, never from an exception**
  (ADR-0029 §8). Nothing durable distinguishes the ``FAILED`` a
  ``ToolBindingError`` produces from a retryable one — ``StepExecution.error`` is
  an unstructured string — so "never retried" is a property of this loop's
  shape rather than something the transition graph enforces.
- **Classification reads the registry's declaration, captured before the call**
  (ADR-0029 §4). Never ``call.request.tool``, which a ``__dict__`` write could
  flip to read-only mid-flight and turn a possible side effect into
  certainly-nothing-happened.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PlanningError, RetriesExhaustedError, ToolBindingError
from ai_assistant.core.types import (
    Idempotency,
    StepStatus,
    StepTransition,
    ToolOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import PlanStore, ToolInvoker, ToolRegistry
    from ai_assistant.core.types import (
        ExecutionState,
        FrozenJsonValue,
        ToolCall,
        ToolDefinition,
        ToolResult,
    )

_log = structlog.get_logger(__name__)

#: Total over :class:`ToolOutcome`, so the result mapping needs no default
#: branch and a member added later raises rather than acquiring a status nobody
#: chose — the shape ``ToolFailureKind.retryable`` uses for the same reason.
_STATUS_BY_OUTCOME: Mapping[ToolOutcome, StepStatus] = {
    ToolOutcome.SUCCEEDED: StepStatus.SUCCEEDED,
    ToolOutcome.FAILED: StepStatus.FAILED,
    ToolOutcome.INDETERMINATE: StepStatus.INDETERMINATE,
}

#: What a seam rejection records. Authored here rather than taken from the
#: exception: ``StepExecution.error`` is Tier 2 operator text bound for a log,
#: and a ``ToolBindingError``'s own message interpolates identifiers off an
#: untrusted call (ADR-0029 §3, ADR-0004 §5).
_REFUSED = (
    "the invoker refused the call before the tool ran: it is not the call that was authorised"
)

#: What a cancelled call records on the ``FAILED`` branch. ``INDETERMINATE``
#: records nothing, because ``StepTransition`` accepts ``error`` only for
#: ``FAILED``; that a cancelled step carries no durable diagnostic is #208.
_CANCELLED = "the invocation was cancelled before it completed"

#: What a claim closed before the tool could be reached records. ``FAILED``
#: rather than ``INDETERMINATE`` for §8's reason: nothing happened, and
#: ``INDETERMINATE`` is the state whose whole meaning is ignorance.
_UNSTARTED = "the executing task was cancelled after the claim and before the tool was reached"

#: Stands in when a non-``SUCCEEDED`` result somehow carries no failure.
#: ``ToolResult``'s own validator makes that unconstructable; this exists so the
#: mapping stays total against a value tampered past ``frozen=True``.
_UNEXPLAINED = "the tool reported a failure with nothing in it"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _checked_timeout(timeout: object) -> timedelta:
    """Refuse a deadline *before* the claim is committed (ADR-0029 §4, §8).

    Not a second copy of the seam's guard, and the difference between them is
    what each is protecting. ``invoke`` checks the value to protect the
    **callable** — the annotation is not the enforcement, and
    ``asyncio.timeout(None)`` is no deadline at all in the one method whose
    contract is that there is always one. This checks it to protect the
    **claim**.

    The claim precedes the call, so a ``ValueError`` raised inside ``invoke``
    would arrive *after* the step is durably ``RUNNING``, and stranding it there
    has recovery record ``INDETERMINATE`` — "we cannot tell whether it acted" —
    about a call whose coroutine that same guard guarantees was never created.
    That is the stranding §8 spells out for ``ToolBindingError``, reached through
    the other exception ``invoke`` is contracted to raise before the tool is
    touched. Refusing here means no durable state is touched at all, which is
    better than committing an honest ``FAILED`` after the fact.

    Raises:
        ValueError: If ``timeout`` is not a strictly positive ``timedelta``.
    """
    if not isinstance(timeout, timedelta):
        msg = f"timeout must be a timedelta, got {type(timeout).__name__}"
        raise ValueError(msg)
    if timeout <= timedelta(0):
        msg = f"timeout must be strictly positive, got {timeout}"
        raise ValueError(msg)
    return timeout


class StepExecutor:
    """Runs one claimed plan step through the invocation seam (ADR-0029 §8).

    Args:
        plans: Durable planning state. Every transition this executor makes goes
            through :meth:`~ai_assistant.core.protocols.PlanStore.commit_transition`,
            which is the only write path and the compare-and-swap the claim
            depends on.
        registry: Where the *trusted* declaration comes from. Read once, before
            the call, because the seam's binding checks all run before the
            callable starts and nothing re-examines a declaration afterwards.
        invoker: The seam. **The composition root must inject one object as both
            ``registry`` and ``invoker``** (ADR-0029 §8): no Protocol can enforce
            it, and two genuinely different bindings under one id is the wiring
            ADR-0016 §7 calls unrecoverable.
        now: Clock used to measure the idempotency window; injectable so retry
            tests are deterministic. Guarded by
            :func:`~ai_assistant.core.clock.checked_clock`, and a non-conforming
            reading is treated as *the window has lapsed* rather than raised —
            see :meth:`_window_is_open`.
    """

    def __init__(
        self,
        *,
        plans: PlanStore,
        registry: ToolRegistry,
        invoker: ToolInvoker,
        now: Clock = _utcnow,
    ) -> None:
        """Wire the executor from injected contracts."""
        self._plans = plans
        self._registry = registry
        self._invoker = invoker
        self._clock = checked_clock(now, owner="StepExecutor")

    async def execute(
        self,
        state: ExecutionState,
        *,
        step_id: str,
        call: ToolCall,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4)
    ) -> ExecutionState:
        """Claim ``step_id``, run ``call``, and commit the outcome.

        Retries while ADR-0029 §5 permits one — the failure kind is retryable
        **and** repeating is safe — re-claiming the step each time, which is what
        spends an attempt against the tracker's ceiling.

        Args:
            state: The execution as currently stored. Its ``version`` is what the
                first claim is computed against.
            step_id: Which step to run.
            call: The authorised call. Its ``request.tool.id`` becomes
                ``bound_tool`` and its ``decision.id`` becomes ``approval_ref``,
                so the durable record describes the call that actually ran
                (ADR-0029 §8).
            timeout: How long the seam may wait, per attempt. The caller's
                budget, not the tool's property (ADR-0029 §4).

        Returns:
            The execution state after the last transition this executor
            committed.

        Raises:
            CancelledError: If the executing task is cancelled from outside. The
                step is committed first and the cancellation then propagates,
                because swallowing it would break structured concurrency and
                shutdown. What is committed depends on where the cancellation
                landed: during the invocation, the interrupted-call
                classification (:meth:`_commit_through_cancellation`); during a
                terminal write, the outcome already established, since by then
                the answer is known and discarding it would have recovery report
                ignorance over it (:meth:`_finish`).
            PlanningError: If a transition is rejected or the store is stale.
            ValueError: If ``timeout`` is not a strictly positive ``timedelta``.
                Checked **before** the claim, so a deadline the seam would
                refuse never leaves a step durably ``RUNNING``
                (:func:`_checked_timeout`).
        """
        _checked_timeout(timeout)
        trusted = await self._registry.get(call.request.tool.id)

        state = await self._claim(state, step_id, call)
        # Read *after* the claim, because ADR-0029 §5 measures from "the first
        # attempt of this call" — a slow `commit_transition` is not part of the
        # window, and counting it could consume one before the tool was reached.
        started = self._reading()
        while True:
            try:
                result = await self._invoker.invoke(call, timeout=timeout)
            except ToolBindingError:
                return await self._refuse(state, step_id)
            except asyncio.CancelledError:
                await self._commit_through_cancellation(state, step_id, _interrupted(trusted))
                raise

            state = await self._record(state, step_id, result)
            if not self._may_retry(result, trusted, started):
                return state
            try:
                state = await self._claim(state, step_id, call)
            except RetriesExhaustedError:
                # The ceiling is the tracker's (ADR-0014 §4), and hitting it is
                # an ordinary end to this loop rather than a fault: the step is
                # already durably FAILED with the reason the tool gave.
                _log.info("step_retries_exhausted", step_id=step_id)
                return state

    # --- the transitions ------------------------------------------------

    async def _claim(self, state: ExecutionState, step_id: str, call: ToolCall) -> ExecutionState:
        """Commit the ``→ RUNNING`` claim that must precede the call.

        ``bound_tool`` and ``approval_ref`` are pinned to the call being made,
        which is what makes the durable record a description of what ran rather
        than of what was planned (ADR-0029 §8).

        **A claim that lands into a cancellation is closed, not left standing.**
        The claim is a write like any other, so a cancellation can arrive while
        it is in flight — and this one lands *before* the tool is reachable. A
        durable ``RUNNING`` there is the worst available record: recovery reads
        it as ``INDETERMINATE``, "we cannot tell whether it acted", about a call
        that provably never started. So the write goes through the same shield
        idiom, and a claim known to have landed is resolved ``FAILED`` — nothing
        happened, which is what §8 says of the other pre-invocation exit — before
        the cancellation is allowed to leave.

        Raises:
            CancelledError: If the executing task was cancelled while the claim
                was in flight. Raised after the step has been closed.
            PlanningError: If the store rejected the claim.
        """
        claimed, cancelled = await self._commit_shielded(
            StepTransition(
                execution_id=state.id,
                step_id=step_id,
                to_status=StepStatus.RUNNING,
                expected_version=state.version,
                bound_tool=call.request.tool.id,
                approval_ref=call.decision.id,
            )
        )
        if not cancelled:
            return claimed

        try:
            await self._commit_shielded(
                self._closing(claimed, step_id, StepStatus.FAILED, error=_UNSTARTED)
            )
        except PlanningError:
            _log.warning("executor_unstarted_close_failed", step_id=step_id, exc_info=True)
        msg = f"step {step_id!r} was claimed and closed unstarted; its task was cancelled"
        raise asyncio.CancelledError(msg)

    async def _refuse(self, state: ExecutionState, step_id: str) -> ExecutionState:
        """Commit ``RUNNING → FAILED`` for a seam rejection, and schedule nothing.

        The claim precedes the call, so a ``ToolBindingError`` arrives after the
        step is durably ``RUNNING``. Letting it propagate uncommitted would
        strand the step until recovery, which would record ``INDETERMINATE`` —
        "we cannot tell whether it acted" — about a call that provably never
        reached the callable, and that is the one thing ``INDETERMINATE`` must
        not be used for.

        Returning from here rather than falling into the retry decision is the
        whole mechanism for "never retried": ADR-0029 §5's conjuncts read
        ``result.failure.kind``, and an exception produces no result to read.
        """
        return await self._finish(state, step_id, StepStatus.FAILED, error=_REFUSED)

    async def _record(
        self, state: ExecutionState, step_id: str, result: ToolResult
    ) -> ExecutionState:
        """Commit what the seam returned — a total mapping over ``ToolOutcome``.

        ``SUCCEEDED`` carries the output, ``FAILED`` the failure's message, and
        ``INDETERMINATE`` neither: ADR-0014 §4's transition reserved for recovery
        is now reachable from a live deadline expiry too, and it takes no payload
        (#208).
        """
        status = _STATUS_BY_OUTCOME[result.outcome]
        if status is StepStatus.SUCCEEDED:
            return await self._finish(state, step_id, status, output=result.output)
        if status is StepStatus.FAILED:
            failure = result.failure
            message = _UNEXPLAINED if failure is None else failure.message
            return await self._finish(state, step_id, status, error=message)
        return await self._finish(state, step_id, status)

    async def _finish(
        self,
        state: ExecutionState,
        step_id: str,
        status: StepStatus,
        *,
        output: FrozenJsonValue = None,
        error: str | None = None,
    ) -> ExecutionState:
        """Commit a terminal transition for the claimed step, through the shield.

        Through the same idiom the cancellation path uses, and for the same
        reason rather than for symmetry. The claim precedes the call, so by the
        time this runs the tool has been reached and its outcome is *known*. A
        cancellation landing on this ``await`` would abandon the write and leave
        the step ``RUNNING``, and recovery would then record ``INDETERMINATE`` —
        "we cannot tell whether it acted" — over an answer the executor was
        holding, discarding a ``SUCCEEDED`` result's output with it. The whole
        write path is therefore cancellation-aware, not just the handler's.

        Raises:
            CancelledError: If the executing task was cancelled while this write
                was in flight. Raised **after** the write has landed, so the
                cancellation still propagates and shutdown still works, which is
                the same order ADR-0029 §4 requires of the handler's commit.
            PlanningError: If the store rejected the transition.
        """
        committed, cancelled = await self._commit_shielded(
            self._closing(state, step_id, status, output=output, error=error)
        )
        if cancelled:
            msg = f"step {step_id!r} was committed {status}; its executing task was cancelled"
            raise asyncio.CancelledError(msg)
        return committed

    def _closing(
        self,
        state: ExecutionState,
        step_id: str,
        status: StepStatus,
        *,
        output: FrozenJsonValue = None,
        error: str | None = None,
    ) -> StepTransition:
        """Build the terminal transition without committing it."""
        return StepTransition(
            execution_id=state.id,
            step_id=step_id,
            to_status=status,
            expected_version=state.version,
            output=output,
            error=error,
        )

    # --- cancellation ---------------------------------------------------

    async def _commit_shielded(self, transition: StepTransition) -> tuple[ExecutionState, bool]:
        """Land ``transition`` even through a cancellation (ADR-0029 §4).

        **Shielding alone is not enough, and this is the part that looks done and
        is not.** ``asyncio.shield`` protects the inner task, not the ``await`` of
        it: a ``cancel()`` — a shutdown that has stopped waiting politely — raises
        here immediately while the commit is still in flight, and a caller that
        re-raised there would re-raise *before* the write landed, leaving the step
        ``RUNNING`` with no record of the outcome just established. So the rule is
        the whole idiom: keep the commit as a task, wait on it through the shield,
        **absorb any further cancellations while it is still running**, and let
        the caller re-raise only once it has completed.

        Even that is not a guarantee — the process can still be killed between the
        outcome and the write, and there ADR-0014 §4's answer is unchanged:
        recovery finds a durable ``RUNNING`` and records ``INDETERMINATE``.

        **An absorbed cancellation outranks the write's own failure.** Absorbing
        one is a promise to re-raise it, and letting a ``PlanningError`` out
        instead would break that promise at the one moment it matters: the
        caller's ``except PlanningError`` would handle a store fault while the
        task it belongs to quietly kept running, having had its teardown
        swallowed. The store fault is logged and the cancellation is what leaves.

        Returns:
            The committed state, and whether any cancellation was absorbed —
            which the caller owes a re-raise for.

        Raises:
            CancelledError: If a cancellation was absorbed and the commit then
                failed, so there is no state to return and a promise to keep.
            PlanningError: If the commit failed with nothing absorbed.
        """
        commit = asyncio.ensure_future(self._plans.commit_transition(transition))
        cancelled = False
        while True:
            try:
                return await asyncio.shield(commit), cancelled
            except asyncio.CancelledError:
                if commit.done():
                    # Nothing left to protect: the commit itself is over.
                    raise
                # Absorbed deliberately. The caller re-raises once the write has
                # landed, so the cancellation still propagates.
                cancelled = True
                _log.debug("executor_absorbed_cancellation_mid_commit")
            except PlanningError:
                if not cancelled:
                    raise
                _log.warning("executor_commit_failed_after_absorbing", exc_info=True)
                msg = "the commit failed; the cancellation of the executing task still stands"
                raise asyncio.CancelledError(msg) from None

    async def _commit_through_cancellation(
        self, state: ExecutionState, step_id: str, outcome: ToolOutcome
    ) -> None:
        """Land the interrupted-call classification, for a cancelled invocation.

        A failure of the commit itself is logged rather than raised, because the
        cancellation is what the caller must see: replacing it with a
        ``PlanningError`` would strand a shutdown mid-teardown. The absorbed-flag
        is ignored for the same reason — the caller re-raises unconditionally.
        """
        status = _STATUS_BY_OUTCOME[outcome]
        error = _CANCELLED if status is StepStatus.FAILED else None
        try:
            await self._commit_shielded(self._closing(state, step_id, status, error=error))
        except PlanningError:
            _log.warning("executor_cancellation_commit_failed", step_id=step_id, exc_info=True)

    # --- the retry decision (ADR-0029 §5) -------------------------------

    def _may_retry(
        self, result: ToolResult, trusted: ToolDefinition | None, started: datetime | None
    ) -> bool:
        """Whether ADR-0029 §5's two conjuncts both hold.

        Both, never either: ``retryable`` says a repeat could plausibly succeed,
        and it says nothing about whether repeating is *safe*. An executor
        reading it alone would double a charge on the first ``TIMED_OUT`` send it
        saw.
        """
        if result.outcome is not ToolOutcome.FAILED:
            # An INDETERMINATE outcome is outside automatic retry by ADR-0014 §4,
            # and this does not relax it.
            return False
        failure = result.failure
        if failure is None or not failure.kind.retryable:
            return False
        return self._repeat_is_safe(trusted, started)

    def _repeat_is_safe(self, trusted: ToolDefinition | None, started: datetime | None) -> bool:
        """Whether repeating this call cannot act twice (ADR-0029 §5).

        Read from the registry's declaration for the same reason the interrupted
        rule is. A tool the registry does not know is refused a retry outright:
        with no trusted declaration there is nothing to establish safety from,
        and the fail-closed direction is a retry not taken.
        """
        if trusted is None:
            return False
        if not trusted.side_effecting or trusted.idempotency is Idempotency.NATURAL:
            return True
        if trusted.idempotency is not Idempotency.KEYED:
            # An `Idempotency.NONE` side-effecting tool is never auto-retried,
            # whatever the failure kind.
            return False
        window = trusted.idempotency_window
        return window is not None and self._window_is_open(started, window)

    def _window_is_open(self, started: datetime | None, window: timedelta) -> bool:
        """Whether the idempotency window has not yet elapsed — fail-closed.

        Past the window "the tool is free to act again" (ADR-0016 §4) and the
        retry stops being a retry, so the executor stops retrying.

        **Measuring an elapsed duration needs a clock the system does not have.**
        ADR-0026 §7 is explicit that ``Clock`` produces wall-clock instants and
        that measuring across a DST transition or an NTP step is a different
        contract it should not be stretched to. So the rule is made fail-closed
        instead: any reading that is **not a positive elapsed duration** — a step
        backwards, a jump past the window, a reading the guard refuses — is
        treated as *the window has lapsed*. Declining to retry costs a
        recoverable error surfaced to the user; retrying outside a lapsed window
        costs a duplicated side effect. A monotonic clock seam is the proper fix
        and is #171, deferred by ADR-0029 §5 itself.
        """
        if started is None:
            return False
        now = self._reading()
        if now is None:
            return False
        elapsed = now - started
        if elapsed <= timedelta(0):
            return False
        return elapsed < window

    def _reading(self) -> datetime | None:
        """The clock's reading, or ``None`` if there is no usable one.

        ``None`` rather than a raised ``PlanningError``, and the asymmetry with
        ``LearningLoop`` is deliberate: this clock is read *only* to measure the
        idempotency window, where ADR-0029 §5 already prescribes what an unusable
        measurement means — the window has lapsed, and the retry is not taken.
        Every reading here happens between the claim and a resolution, so letting
        one out would leave a step durably ``RUNNING`` over a measurement whose
        whole design is to degrade toward retrying less.

        **Any ``Exception``, not only a non-conforming reading.** ADR-0026 §2 is
        explicit that an exception raised by the clock callable *itself*
        propagates unwrapped, so ``ClockReadingError`` is not the whole of what
        can arrive: an injected clock reading a provider can raise anything at
        all. ADR-0026 §4 leaves the failure policy to each subsystem's own
        boundary, and this boundary's policy is §5's. ``BaseException`` still
        propagates — a ``CancelledError`` here is a teardown, not a bad reading.

        The exception's *type* is logged and never its text: a clock wrapping a
        provider can quote a URL or a credential, and this line is bound for a
        log the key-based redactor cannot see into (ADR-0004 §5).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            _log.warning(
                "executor_clock_unusable_window_treated_as_lapsed",
                error_type=type(exc).__name__,
            )
        except Exception as exc:
            # Broad deliberately: §5's measurement fails closed whatever broke,
            # and the alternative is a step left RUNNING over a clock.
            _log.warning(
                "executor_clock_raised_window_treated_as_lapsed",
                error_type=type(exc).__name__,
            )
        return None


def _interrupted(trusted: ToolDefinition | None) -> ToolOutcome:
    """What an interrupted call of ``trusted`` means (ADR-0029 §4).

    Delegates wholly to
    :attr:`~ai_assistant.core.types.ToolDefinition.interrupted_outcome`, the one
    copy of the rule (ADR-0031 §1). An unknown declaration is ``INDETERMINATE``:
    with nothing trusted to classify from, the honest answer is the ignorant one,
    and ``FAILED`` would record a possible side effect as
    certainly-nothing-happened.
    """
    return ToolOutcome.INDETERMINATE if trusted is None else trusted.interrupted_outcome


__all__ = ["StepExecutor"]
