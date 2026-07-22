"""The stages between a plan and a tool: selection, permission, hand-off (ADR-0037).

:class:`StepRunner` is the join `CLAUDE.md`'s pipeline was missing. Given a
:class:`~ai_assistant.core.types.PlanStep` it asks the registry which tools
advertise the step's capability, asks the policy whether the one candidate may
run, records the resulting :class:`~ai_assistant.core.types.PermissionDecision`
in the audit trail, and hands
:class:`~ai_assistant.orchestration.executor.StepExecutor` an authorised
:class:`~ai_assistant.core.types.ToolCall` — or disposes of the step without
running anything, saying durably why.

Four rules shape the module and are worth stating before the code:

- **Selection is defined for exactly one candidate** (ADR-0037 §1). ADR-0016 §5
  refused to rank and ADR-0016 §7 deferred ranking to this stage without giving
  it a rule. Rather than invent one quietly — ``candidates[0]`` is a ranking by
  *name* — several candidates is a refusal that leaves the step ``PENDING``
  (#241).
- **Decide, record, read back, then claim** (ADR-0037 §2). ADR-0014 §4 refuses
  ``→ RUNNING`` without an ``approval_ref`` and requires the claim to precede the
  call, so the decision must exist first; recording after the claim would leave a
  live side effect with nothing in the trail.
- **The authority is the trail's copy, never the one in hand** (ADR-0037 §3).
  This is the only constructor of a ``ToolCall`` in the pipeline and it builds
  one solely out of what :meth:`~ai_assistant.core.protocols.AuditTrail.get`
  returned, which is what closes issue #107 structurally rather than by
  discipline.
- **A ``CONFIRM`` is parked, never answered here** (ADR-0037 §4). The step is
  committed ``AWAITING_APPROVAL`` — durable precisely so a restart preserves it
  (ADR-0014 §4) — and :meth:`StepRunner.resume` takes the human's answer when it
  arrives, against the execution that is actually holding the question
  (:meth:`StepRunner._check_parked`).

Nothing concrete is imported. Five collaborators arrive by injection and are seen
only through their Protocols (CLAUDE.md golden rule 1); the sixth, the executor,
is this package's own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import AuditError, PermissionDeniedError, PlanningError
from ai_assistant.core.types import (
    ActionRequest,
    PermissionDecision,
    PermissionOutcome,
    PlanStep,
    SkipReason,
    StepStatus,
    StepTransition,
    ToolCall,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import timedelta

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        ActionPolicy,
        AuditTrail,
        PlanStore,
        ToolRegistry,
    )
    from ai_assistant.core.types import (
        ExecutionState,
        PermissionRuling,
        ToolDefinition,
    )
    from ai_assistant.orchestration.executor import StepExecutor

_log = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


def _detached(step: PlanStep) -> PlanStep:
    """Revalidate and detach the step before anything durable names it.

    **This stage is handed a caller's object and reads it across four awaits** —
    the registry lookup, the policy's ruling, the trail's write and the trail's
    read — before the first transition is computed. ``frozen=True`` refuses
    ``step.id = ...`` and does nothing about ``step.__dict__["id"] = ...``, and
    ADR-0018 §3, ADR-0018 §4 and ADR-0029 §2 all put that bypass inside this
    repository's threat model rather than outside it.

    Without the snapshot, an id rewritten while the policy is ruling would have
    the decision made about one step and the transition committed against
    another: a second step recorded as denied, or claimed, under an
    ``approval_ref`` naming a decision that was about its neighbour — the durable
    audit association silently wrong in the direction ADR-0014 §4's
    ``approval_ref`` rule exists to make right. The same argument
    :func:`~ai_assistant.orchestration.executor._detached` makes for a
    ``ToolCall``, one stage earlier and about the other half of the pair.

    Raises:
        PlanningError: If the step does not survive revalidation. Raised before
            any await, so an unusable step touches no durable state at all.
    """
    try:
        return PlanStep.model_validate(step.model_dump())
    except ValidationError as exc:
        msg = "the plan step did not survive revalidation, so it is not the step that was planned"
        raise PlanningError(msg) from exc


class Disposition(StrEnum):
    """What became of one plan step at this stage (ADR-0037 §1, §4, §5).

    Five members, and the two that commit nothing are as much a result as the
    three that do: a step this stage declines to act on is a fact its caller has
    to be told, not an error.
    """

    EXECUTED = "executed"
    """The call was authorised and handed to the executor; ``state`` carries the
    outcome the executor committed."""

    DENIED = "denied"
    """The policy refused. The step is ``SKIPPED``/``APPROVAL_DENIED``, naming
    the recorded decision."""

    AWAITING_CONFIRMATION = "awaiting_confirmation"
    """The policy wants a human answer. The step is durably
    ``AWAITING_APPROVAL``; :meth:`StepRunner.resume` continues it."""

    NO_CAPABLE_TOOL = "no_capable_tool"
    """Nothing advertises the step's capability. The step is
    ``SKIPPED``/``NO_CAPABLE_TOOL`` (ADR-0014 §4)."""

    AMBIGUOUS_CAPABILITY = "ambiguous_capability"
    """Several tools advertise it and no rule chooses between them (ADR-0037 §1,
    #241). Nothing is committed and the step stays ``PENDING``."""


@dataclass(frozen=True, slots=True)
class StepDisposition:
    """What one pass of :class:`StepRunner` did with a step (ADR-0037 §4).

    A frozen dataclass in `orchestration` rather than a pydantic model in
    ``core/types.py``, for :class:`~ai_assistant.orchestration.loop.TurnResult`'s
    reason: it crosses no *subsystem* boundary. It graduates to ``core`` on the
    day a subsystem needs to receive one.

    Attributes:
        disposition: Which of the five outcomes happened.
        state: Durable execution state after the last transition this pass
            committed — the caller's ``state`` unchanged where it committed none.
        decision_id: The recorded decision this pass rested on, or ``None`` where
            no decision was reached. On ``AWAITING_CONFIRMATION`` this is the
            id :meth:`StepRunner.resume` needs, and until #242 lands it is the
            only place that id exists outside the trail.
        tool_id: The tool selected, or ``None`` where none was.
    """

    disposition: Disposition
    state: ExecutionState
    decision_id: str | None = None
    tool_id: str | None = None


class StepRunner:
    """Selects a tool for a step, gates it, and runs it (ADR-0037).

    Args:
        plans: Durable planning state. Every transition this object makes goes
            through :meth:`~ai_assistant.core.protocols.PlanStore.commit_transition`,
            the same compare-and-swap the executor's claim depends on.
        registry: Asked which tools advertise a step's capability. It does not
            choose, and neither does this object beyond the single-candidate case
            (ADR-0016 §5, ADR-0037 §1).
        policy: The gate ADR-0004 §7 requires in front of every side-effecting
            call. It rules; it does not record (ADR-0021 §3).
        trail: Where every ruling is recorded, and — crucially — where the
            authority handed to the executor is read back from (ADR-0037 §3).
        executor: The ``execute`` stage. This package's own object rather than a
            Protocol, because it is not another subsystem: golden rule 1 governs
            what crosses a package boundary, and nothing here does.
        now: Clock stamping ``decided_at`` on each decision; injectable so
            recorded decisions are deterministic in tests. Guarded by
            :func:`~ai_assistant.core.clock.checked_clock`, so a non-conforming
            reading is a ``PlanningError`` from the stage that read it,
            `orchestration` having no error of its own (ADR-0026 §4).
        id_factory: Supplies decision ids. Minted rather than derived from the
            step, so a second attempt at a step is a second decision rather than
            a duplicate-id refusal from the trail (ADR-0037 §3).

    **The composition root must inject one object as both ``registry`` and the
    executor's ``invoker``** (ADR-0029 §8). This object holds the registry that
    *selects*; the executor holds the one that *acts*, and two genuinely
    different bindings under one id is the wiring ADR-0016 §7 calls
    unrecoverable.
    """

    def __init__(  # noqa: PLR0913  # one parameter per collaborator; that is the design
        self,
        *,
        plans: PlanStore,
        registry: ToolRegistry,
        policy: ActionPolicy,
        trail: AuditTrail,
        executor: StepExecutor,
        now: Clock = _utcnow,
        id_factory: Callable[[], str] = _uuid,
    ) -> None:
        """Wire the stage from injected contracts."""
        self._plans = plans
        self._registry = registry
        self._policy = policy
        self._trail = trail
        self._executor = executor
        self._clock = checked_clock(now, owner="StepRunner")
        self._id_factory = id_factory

    async def run(
        self,
        state: ExecutionState,
        step: PlanStep,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — passed through to the seam, which owns the deadline (ADR-0029 §4)
    ) -> StepDisposition:
        """Select a tool for ``step``, rule on it, and run it if allowed.

        The stage order is ADR-0037 §2's and each stage can only use what the one
        before it produced: the policy rules on a request naming a *selected*
        tool, the decision is recorded before any transition is committed, and
        the executor is handed an authority read back out of the trail.

        Args:
            state: The execution as currently stored. Its ``version`` is what the
                first transition is computed against.
            step: The step to dispose of. Its ``capability`` drives selection and
                its ``parameters`` are what the policy rules on — unvalidated
                against the tool's ``parameters_schema``, which ADR-0016 §7
                defers.
            timeout: How long the seam may wait, per attempt; passed through to
                the executor. The caller's budget, not the tool's property
                (ADR-0029 §4).

        Returns:
            What became of the step, and the durable state after it.

        Raises:
            AuditError: If the trail would not accept the decision, or does not
                hand back a record of it (:meth:`_authorised`). Raised before any
                claim, so nothing ran and nothing is left ``RUNNING``.
            PlanningError: If a transition is rejected, the store is stale, the
                injected clock's reading is not conforming (:meth:`_now`), or
                ``step`` does not survive revalidation (:func:`_detached`).
            ToolBindingError: From the executor, if the authorised call does not
                survive its own revalidation.
        """
        # One snapshot, taken before the first await, and used for the lookup,
        # the ruling, the record and every transition. See `_detached`: the
        # caller's object is mutable across all of them.
        step = _detached(step)
        candidates = await self._registry.find(step.capability)
        if not candidates:
            skipped = await self._skip(state, step, SkipReason.NO_CAPABLE_TOOL)
            return StepDisposition(Disposition.NO_CAPABLE_TOOL, skipped)
        if len(candidates) > 1:
            # No rule chooses, so nothing is written: `PENDING` is already the
            # truth about this step, and no `SkipReason` would be (ADR-0037 §1).
            _log.info(
                "step_capability_ambiguous",
                step_id=step.id,
                capability=step.capability,
                candidates=len(candidates),
            )
            return StepDisposition(Disposition.AMBIGUOUS_CAPABILITY, state)

        tool = candidates[0]
        request = ActionRequest(tool=tool, parameters=step.parameters, step_id=step.id)
        ruling = await self._policy.decide(request)
        decision = await self._record(request, ruling)

        if ruling.outcome is PermissionOutcome.ALLOW:
            return await self._execute(state, step, request, decision, timeout=timeout)

        # Both remaining outcomes pass through `AWAITING_APPROVAL`. For a
        # `CONFIRM` that is the state's own meaning; for a `DENY` it is the only
        # path ADR-0014 §4 leaves to `APPROVAL_DENIED`, which it refuses from
        # `PENDING` because "a step that was never queued for approval cannot
        # have been denied one" (ADR-0037 §5).
        queued = await self._queue_for_approval(state, step, tool.id)
        if ruling.outcome is PermissionOutcome.CONFIRM:
            return StepDisposition(Disposition.AWAITING_CONFIRMATION, queued, decision.id, tool.id)
        return await self._deny(queued, step, decision, tool)

    async def resume(
        self,
        state: ExecutionState,
        step: PlanStep,
        *,
        confirmation_id: str,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — passed through to the seam, which owns the deadline (ADR-0029 §4)
    ) -> StepDisposition:
        """Answer a parked ``CONFIRM`` and continue the step (ADR-0037 §4).

        The request is rebuilt from the **confirmation's own embedded**
        :class:`~ai_assistant.core.types.ToolDefinition`, never re-resolved
        through the registry: that embedding is why ADR-0021 §1 stores the whole
        declaration, and re-resolving would run whatever the id means now rather
        than what the user was shown (issue #54).

        Nothing here re-checks the resolution invariant, because
        :meth:`~ai_assistant.core.protocols.AuditTrail.record` is the only place
        both records are in hand and enforces it in full — including that the
        subject matches, so a step whose parameters changed between the prompt
        and the answer is refused with ``InvalidResolutionError`` rather than
        executed against arguments nobody approved.

        Args:
            state: The execution as currently stored. ``step`` must be parked in
                *it*, awaiting the confirmation's own tool — checked here rather
                than left to the transition graph, which would find the same
                step of a *second* execution of the same plan perfectly claimable
                (:meth:`_check_parked`).
            step: The step the confirmation was about.
            confirmation_id: The recorded ``CONFIRM``'s id, as returned in the
                :class:`StepDisposition` that parked it. It is carried by the
                caller because the ``→ AWAITING_APPROVAL`` transition does not
                store it (#242).
            approved: The human's answer. Only ``True`` is consent, and the
                policy — not this object — is what turns it into a ruling
                (ADR-0021 §3, ADR-0036 §1).
            timeout: Passed through to the executor, as in :meth:`run`.

        Returns:
            ``EXECUTED`` or ``DENIED``, and the durable state after it. A
            resolving ruling can be nothing else: ``ActionPolicy.resolve`` may
            not return ``CONFIRM``, and a resolving decision that was one is
            unconstructable (``PermissionDecision``'s own validator).

        Raises:
            AuditError: If the confirmation is absent from the trail, if the
                trail refuses the resolving decision, or if it does not hand back
                a record of it.
            PermissionDeniedError: If ``confirmation_id`` names something that
                was not a ``CONFIRM``, or a ``CONFIRM`` about a different step,
                or one this execution is not parked on
                (:meth:`_check_parked`). Refused before anything is authored, so
                a mismatched answer cannot become a recorded decision.
            PlanningError: As :meth:`run`, and if ``step`` does not survive
                revalidation (:func:`_detached`).
        """
        step = _detached(step)
        confirmed = await self._trail.get(confirmation_id)
        if confirmed is None:
            msg = (
                f"the trail holds no decision {confirmation_id!r}, so there is no confirmation "
                "for this answer to resolve"
            )
            raise AuditError(msg)
        if confirmed.ruling.outcome is not PermissionOutcome.CONFIRM:
            msg = (
                f"decision {confirmation_id!r} is a {confirmed.ruling.outcome} and was never "
                "shown as a question, so an answer to it authorises nothing"
            )
            raise PermissionDeniedError(msg)
        if confirmed.step_id != step.id:
            # ADR-0021 §1 binds an approval to the step. Accepting a
            # confirmation authorised for another one would let one step's
            # prompt release a different step's action — the shape the executor
            # refuses at its own boundary, one stage earlier.
            msg = (
                f"decision {confirmation_id!r} confirms a different plan step, so resolving it "
                f"here would release step {step.id!r} on somebody else's answer"
            )
            raise PermissionDeniedError(msg)
        self._check_parked(state, step, confirmed.tool.id, confirmation_id=confirmation_id)

        request = ActionRequest(tool=confirmed.tool, parameters=step.parameters, step_id=step.id)
        ruling = await self._policy.resolve(confirmed, approved=approved)
        decision = await self._record(request, ruling, resolves=confirmed.id)
        if decision.ruling.outcome is PermissionOutcome.ALLOW:
            return await self._execute(state, step, request, decision, timeout=timeout)
        return await self._deny(state, step, decision, confirmed.tool)

    # --- the permission stage -------------------------------------------

    def _check_parked(
        self,
        state: ExecutionState,
        step: PlanStep,
        tool_id: str,
        *,
        confirmation_id: str,
    ) -> None:
        """Require ``state`` to hold *this* step, parked, awaiting *this* tool.

        **The transition graph is not enough, and assuming it was is the hole
        this closes.** ``PlanStore`` opens an execution per ``start_execution``
        call, so one plan can have several, and a confirmation carries no
        execution id — ADR-0021 §1 binds an approval to the tool, the parameters
        and the *step*, and ``ActionRequest`` has no field for anything wider. So
        a confirmation parked in execution A, replayed against execution B where
        the same step is still ``PENDING``, would find ``PENDING → RUNNING``
        perfectly legal and release B's step on an answer given about A's — while
        A stayed parked, still awaiting the question it had already been asked.
        Nothing downstream catches it: the digest, the tool and the step id all
        match, because it is the same step of the same plan.

        Checking the ``bound_tool`` too is not belt-and-braces. It is what makes
        "this parked step is the one that question was asked about" mean
        something when the step is awaiting approval for a *different*
        declaration — the case where the step is in the right status and still
        the wrong subject.

        The check is against the caller's ``state`` because that is the snapshot
        the compare-and-swap is computed against: a ``state`` that disagrees with
        the store is rejected by the transition itself, so the two guards cover
        the two different lies.

        **What remains is narrow and named** (ADR-0037 §4, #253): two executions
        of one plan, *both* parked on the same step, are mutually substitutable.
        The trail's single-resolution index still means one confirmation
        authorises one resolution, so the residue is which of two identical
        parked executions proceeds, not whether an unapproved one does.

        Raises:
            PermissionDeniedError: If the step is absent from ``state``, is not
                ``AWAITING_APPROVAL``, or is bound to a different tool.
        """
        parked = state.step(step.id)
        if parked is None or parked.status is not StepStatus.AWAITING_APPROVAL:
            found = "is not in this execution" if parked is None else f"is {parked.status}"
            msg = (
                f"step {step.id!r} {found}, not awaiting approval, so decision "
                f"{confirmation_id!r} answers no question this execution is holding"
            )
            raise PermissionDeniedError(msg)
        if parked.bound_tool != tool_id:
            msg = (
                f"step {step.id!r} awaits approval for {parked.bound_tool!r}, but decision "
                f"{confirmation_id!r} confirms {tool_id!r}"
            )
            raise PermissionDeniedError(msg)

    async def _record(
        self,
        request: ActionRequest,
        ruling: PermissionRuling,
        *,
        resolves: str | None = None,
    ) -> PermissionDecision:
        """Bind ``ruling`` to ``request`` and append it to the trail.

        The id and the clock are supplied here because ADR-0021 §3 withholds both
        from the policy — that is what leaves ``decide`` a genuine function of its
        argument, and the monotonicity obligations checkable at all.

        Every branch reaches this, including ``DENY``: ADR-0004 §7 asks for
        reviewability, and a refusal nobody can find a trace of is the half of
        the trail that answers "what did the assistant decline to do".

        Raises:
            AuditError: If the trail refused the append — a duplicate id, or a
                ``resolves`` pointer that failed its invariant.
            PlanningError: If the injected clock's reading is not conforming.
        """
        decision = PermissionDecision.from_request(
            request,
            ruling,
            id=self._id_factory(),
            decided_at=self._now(),
            resolves=resolves,
        )
        await self._trail.record(decision)
        return decision

    async def _authorised(self, request: ActionRequest, decision_id: str) -> ToolCall:
        """Build the call from the trail's copy of the decision (ADR-0037 §3).

        **This is what closes issue #107**, and it closes it by construction: the
        only ``ToolCall`` this pipeline can produce is one built out of a record
        the trail handed back, so the ``approval_ref`` the executor pins is
        necessarily an id that resolves. Checking that ``record`` did not raise
        would be weaker — a trail that accepted a write and lost it answers
        ``None`` here, and a trail whose row no longer validates raises
        ``AuditError`` from ``get`` itself (ADR-0036 §2), so "never recorded" and
        "corrupted" stay distinguishable.

        The round trip is a real comparison rather than a ceremony:
        ``ToolCall``'s validator runs ``PermissionDecision.authorises``, so a copy
        that came back describing a different tool, payload or step cannot become
        a call at all.

        Raises:
            AuditError: If the trail holds no such decision, or holds one that
                does not authorise ``request``.
        """
        recorded = await self._trail.get(decision_id)
        if recorded is None:
            msg = (
                f"the trail accepted decision {decision_id!r} and does not hold it, so nothing "
                "recorded authorises this call"
            )
            raise AuditError(msg)
        try:
            return ToolCall(request=request, decision=recorded)
        except ValidationError as exc:
            msg = (
                f"the trail's copy of decision {decision_id!r} does not authorise this request, "
                "so it is not a record of what was approved"
            )
            raise AuditError(msg) from exc

    # --- the dispositions -----------------------------------------------

    async def _execute(
        self,
        state: ExecutionState,
        step: PlanStep,
        request: ActionRequest,
        decision: PermissionDecision,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — passed through to the seam, which owns the deadline (ADR-0029 §4)
    ) -> StepDisposition:
        """Hand the executor an authorised call and report what it committed.

        The call is built first, so a trail that cannot produce the authority
        stops the turn *before* the executor's claim — leaving the step
        untouched, rather than durably ``RUNNING`` over a decision nobody can
        find (ADR-0037 §3).
        """
        call = await self._authorised(request, decision.id)
        ran = await self._executor.execute(state, step_id=step.id, call=call, timeout=timeout)
        return StepDisposition(Disposition.EXECUTED, ran, decision.id, call.decision.tool.id)

    async def _deny(
        self,
        state: ExecutionState,
        step: PlanStep,
        decision: PermissionDecision,
        tool: ToolDefinition,
    ) -> StepDisposition:
        """Skip the step as denied, naming the decision that refused it.

        ``approval_ref`` is required here by ``PlanExecution``, which refuses to
        record a denial without one — the same insistence ADR-0014 §4 places on
        the claim, from the other side.
        """
        skipped = await self._skip(
            state, step, SkipReason.APPROVAL_DENIED, approval_ref=decision.id
        )
        return StepDisposition(Disposition.DENIED, skipped, decision.id, tool.id)

    # --- durable state ---------------------------------------------------

    async def _skip(
        self,
        state: ExecutionState,
        step: PlanStep,
        reason: SkipReason,
        *,
        approval_ref: str | None = None,
    ) -> ExecutionState:
        """Commit ``→ SKIPPED`` for ``step``, through the store's compare-and-swap."""
        return await self._plans.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id=step.id,
                to_status=StepStatus.SKIPPED,
                expected_version=state.version,
                skip_reason=reason,
                approval_ref=approval_ref,
            )
        )

    async def _queue_for_approval(
        self, state: ExecutionState, step: PlanStep, tool_id: str
    ) -> ExecutionState:
        """Commit ``→ AWAITING_APPROVAL``, which needs the tool that would run.

        "Approval is consent to a *specific* action" (ADR-0014 §4), so the
        transition carries ``bound_tool`` and this is reachable only after
        selection has chosen one.
        """
        return await self._plans.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id=step.id,
                to_status=StepStatus.AWAITING_APPROVAL,
                expected_version=state.version,
                bound_tool=tool_id,
            )
        )

    def _now(self) -> datetime:
        """The guarded clock's reading, as the reading stage's own error.

        ``core/errors.py`` defines no error for `orchestration`, so ADR-0026 §4
        gives the failure to the *stage*: this clock is read only while minting a
        decision, and every durable effect this stage has is a plan transition,
        so a non-conforming reading raises the error those already raise.

        Raises:
            PlanningError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise PlanningError(str(exc)) from exc


__all__ = ["Disposition", "StepDisposition", "StepRunner"]
