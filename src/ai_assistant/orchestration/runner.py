"""The stages between a plan and a tool: selection, permission, hand-off (ADR-0037).

:class:`StepRunner` is the join `CLAUDE.md`'s pipeline was missing. Named one
step of a stored plan, it asks the registry which tools advertise that step's
capability, asks the policy whether the one candidate may run, records the
resulting :class:`~ai_assistant.core.types.PermissionDecision` in the audit
trail, and hands
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
- **Both subjects are read from a store, never taken on the caller's word**
  (ADR-0037 §2, §3). The step comes from the plan the execution names, so a
  substituted capability or substituted arguments are unrepresentable rather
  than checked for; and the authority comes from the trail, proved to be the
  record its id names (:meth:`StepRunner._recorded`). This is the only
  constructor of a ``ToolCall`` in the pipeline, which is what closes issue #107
  structurally rather than by discipline.
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
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import AuditError, PermissionDeniedError, PlanningError
from ai_assistant.core.types import (
    ActionRequest,
    ExecutionState,
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

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        ActionPolicy,
        AuditTrail,
        PlanStore,
        ToolRegistry,
    )
    from ai_assistant.core.types import (
        PermissionRuling,
        ToolDefinition,
    )
    from ai_assistant.orchestration.executor import StepExecutor

_log = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


def _detached_request(request: ActionRequest) -> ActionRequest:
    """The copy the policy rules on, so it never holds the one that is executed.

    **This is what keeps ADR-0021 §3's central guarantee true at the seam.**
    ``PermissionRuling`` has no field naming a tool, a payload or a step
    precisely so a policy cannot substitute the subject of the decision it is
    answering about; the ADR calls that absence "the security property, not an
    economy", and says splitting the types "removes the capability rather than
    forbidding it". Handing ``decide`` the very object that is then bound into
    the ``PermissionDecision`` and executed hands the capability straight back:
    ``frozen=True`` refuses ``request.tool = ...`` and does nothing about
    ``request.__dict__`` (ADR-0018 §3), so a policy could rule ``ALLOW`` on a
    harmless declaration and swap in another registered one before returning.
    Everything downstream would then agree with itself — the decision, the
    ``ToolCall`` and the invoker all describe the substitute — and the tool the
    user's policy actually approved would never have run.

    **The timing is the whole of it: the copy is taken before ``decide`` is
    reached, not after it returns.** A copy taken afterwards faithfully preserves
    a substitution already made, which is the same hole one instruction later.

    A policy that keeps its copy and mutates it *later* is then harmless — it
    holds a value nothing reads — so the comparisons that follow (the subject
    check in :meth:`StepRunner._record`, and ``ToolCall``'s own ``authorises``)
    answer about the request that was really ruled on.

    Raises:
        ValueError: If the request does not survive revalidation. Not reachable
            through a value this module has just constructed.
    """
    return ActionRequest.model_validate(request.model_dump())


def _detached_step(step: PlanStep) -> PlanStep:
    """Revalidate and detach the stored step before anything durable names it.

    **The step is read across four awaits** — the registry lookup, the policy's
    ruling, the trail's write and the trail's read — before the first transition
    is computed, and ``PlanStore.get_plan`` does not *contract* a detached
    snapshot the way ``MemoryStore``, ``ToolRegistry`` and ``AuditTrail`` do. A
    conforming store may therefore hand back its own object, and ``frozen=True``
    refuses ``step.id = ...`` while doing nothing about
    ``step.__dict__["id"] = ...`` — a bypass ADR-0018 §3, ADR-0018 §4 and
    ADR-0029 §2 all put inside this repository's threat model rather than
    outside it.

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
            any further await, so an unusable step touches no durable state.
    """
    try:
        return PlanStep.model_validate(step.model_dump())
    except ValidationError as exc:
        msg = "the plan step did not survive revalidation, so it is not the step that was planned"
        raise PlanningError(msg) from exc


def _detached_state(state: ExecutionState) -> ExecutionState:
    """A private copy of the caller's execution state, taken before the first await.

    **Both guards this stage runs on the caller's ``state`` — :meth:`StepRunner._opened`
    reading history from the store, :meth:`StepRunner._check_parked` proving the step
    is genuinely parked — are defeated if the two fields the transitions and the
    executor read from ``state`` can change after those guards pass.** ADR-0037
    §§2 and 4 make the store, not the argument, the authority on what has
    happened, and leave the caller only its CAS token, its ``version``. But
    ``ExecutionState`` is a plain pydantic model (``frozen=True`` is not set), so
    ``state.id`` and ``state.version`` are ordinary mutable attributes, and every
    durable effect — ``_skip``, ``_queue_for_approval`` and the executor's own
    claim — reads them *after* the registry lookup, the policy ruling and the
    trail writes have awaited.

    A caller sharing this object with another task can therefore authenticate
    execution A through both guards and, while an await is suspended, rewrite
    ``state.id`` and ``state.version`` to execution B — a *second* run of the same
    plan, whose matching step is still claimable at its own version. The claim,
    the invocation and the durable record then land on B, driven by a request and
    a decision derived from A: the exact cross-execution substitution
    ``_check_parked`` refuses one branch of, reintroduced through the fields it
    does not own. Reading ``state.id``/``state.version`` off a private snapshot
    the caller has no handle on removes the move rather than checking for it — the
    same reasoning :func:`_detached_step` and
    :func:`~ai_assistant.orchestration.executor._detached` apply to the plan step
    and the tool call, for the two fields left.

    The copy is taken before any await, so the snapshot is the state as the caller
    named it on entry; ``version`` is unchanged by the copy and remains the CAS
    token the store adjudicates.

    Raises:
        PlanningError: If the state does not survive revalidation. Raised before
            any await, so an unusable state touches no durable state.
    """
    try:
        return ExecutionState.model_validate(state.model_dump())
    except ValidationError as exc:
        msg = "the execution state did not survive revalidation, so it is not the one named"
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
        decision: The trail's own copy of the recorded ``CONFIRM``, carried on
            ``AWAITING_CONFIRMATION`` so a driver can render the parked action —
            the tool declaration and the ruling's ``reason`` — **without** a second
            trail read after the step is durably parked (which would be fallible
            work between parking and offering the continuation). It is already in
            hand here: :meth:`StepRunner._record` reads it back before
            :meth:`StepRunner._queue_for_approval` parks. ``None`` on every other
            disposition.
    """

    disposition: Disposition
    state: ExecutionState
    decision_id: str | None = None
    tool_id: str | None = None
    decision: PermissionDecision | None = None


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
        confirmation_ttl: timedelta | None = None,
    ) -> None:
        """Wire the stage from injected contracts.

        ``confirmation_ttl`` is the one setting here that is the deployment's
        rather than the contract's, in the shape ``ThresholdActionPolicy``'s
        thresholds are (ADR-0036 §1): the mechanism lives here because staleness
        enforcement is `orchestration`'s (ADR-0036 §1 declined to give the policy
        a clock), and how long a question stands is a value a deployment sets, not
        one this stage invents. It defaults to ``None`` — no lifetime, the
        behaviour before #243 — so a deployment that has not chosen a duration
        refuses no legitimate answer, which is the failure ADR-0037 §4 named when
        it declined to invent one.

        Raises:
            ValueError: If ``confirmation_ttl`` is set and not strictly positive.
                A zero or negative lifetime would expire every confirmation the
                instant it was recorded, which is a way to make the whole
                confirmation flow unanswerable by misconfiguration rather than a
                lifetime; refused at construction rather than surfacing per
                answer.
        """
        if confirmation_ttl is not None and confirmation_ttl <= timedelta(0):
            msg = f"confirmation_ttl must be strictly positive, got {confirmation_ttl}"
            raise ValueError(msg)
        self._plans = plans
        self._registry = registry
        self._policy = policy
        self._trail = trail
        self._executor = executor
        self._clock = checked_clock(now, owner="StepRunner")
        self._id_factory = id_factory
        self._confirmation_ttl = confirmation_ttl

    async def run(
        self,
        state: ExecutionState,
        step_id: str,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — passed through to the seam, which owns the deadline (ADR-0029 §4)
    ) -> StepDisposition:
        """Select a tool for ``step_id``, rule on it, and run it if allowed.

        The stage order is ADR-0037 §2's and each stage can only use what the one
        before it produced: the policy rules on a request naming a *selected*
        tool, the decision is recorded before any transition is committed, and
        the executor is handed an authority read back out of the trail.

        **The step is read from the plan, not accepted from the caller**
        (ADR-0037 §2). Taking a ``PlanStep`` would let a caller hand over one
        that shares the planned step's id and names a different capability or
        different arguments: the gate would rule on *that* action, the executor
        would run it, and the plan the execution belongs to would still record
        the action nobody performed. Naming the step instead removes the
        substitution rather than checking for it, which is the same move
        ADR-0021 §3 made when it took the subject out of ``PermissionRuling``.

        Args:
            state: The execution as currently stored. Its ``version`` is what the
                first transition is computed against, and its ``plan_id`` is the
                plan the step is read from.
            step_id: Which step of that plan to dispose of. Its ``capability``
                drives selection and its ``parameters`` are what the policy rules
                on — unvalidated against the tool's ``parameters_schema``, which
                ADR-0016 §7 defers.
            timeout: How long the seam may wait, per attempt; passed through to
                the executor. The caller's budget, not the tool's property
                (ADR-0029 §4).

        Returns:
            What became of the step, and the durable state after it.

        Raises:
            AuditError: If the trail would not accept the decision, or does not
                hand back the record of it (:meth:`_recorded`). Raised before any
                claim, so nothing ran and nothing is left ``RUNNING``.
            PlanningError: If the execution's plan is missing, holds no such step
                (:meth:`_planned`), a transition is rejected, the store is stale,
                or the injected clock's reading is not conforming (:meth:`_now`).
            ToolBindingError: From the executor, if the authorised call does not
                survive its own revalidation.
        """
        # Every field a later transition or the executor reads from `state` is
        # taken from this private copy, so a caller sharing the object cannot
        # rewrite the execution out from under the guards (`_detached_state`).
        state = _detached_state(state)
        opened = await self._opened(state)
        step = await self._planned(opened, step_id)
        self._check_pending(opened, step_id)
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
        request = ActionRequest(
            tool=tool, parameters=step.parameters, step_id=step.id, execution_id=state.id
        )
        # The policy rules on its *own* copy, and never on the object that is
        # then bound and executed (`_detached_request`).
        ruling = await self._policy.decide(_detached_request(request))
        decision = await self._record(request, ruling)

        # Branch on the *recorded* ruling, never the policy's own object. The
        # decision deep-copied it (ADR-0021 §1) and the trail then round-tripped
        # it, but the policy still holds the value it returned and the write is
        # an await — so a ruling mutated through `__dict__` while `record` is
        # suspended (ADR-0018 §3) would have an `ALLOW` recorded and a `DENY`
        # committed, leaving `approval_ref` pointing at an authorisation.
        if decision.ruling.outcome is PermissionOutcome.ALLOW:
            return await self._execute(state, step, request, decision, timeout=timeout)

        if decision.ruling.outcome is PermissionOutcome.CONFIRM:
            # A `CONFIRM` is the one outcome that parks the step: it is committed
            # `PENDING → AWAITING_APPROVAL` with `bound_tool`, durably, and
            # `resume` takes the human's answer when it arrives (ADR-0037 §4).
            queued = await self._queue_for_approval(state, step, tool.id)
            return StepDisposition(
                Disposition.AWAITING_CONFIRMATION, queued, decision.id, tool.id, decision=decision
            )
        # A `DENY` is recorded in one commit, straight from `PENDING`
        # (ADR-0037 §5, ADR-0041). The policy refused on its own authority with
        # nobody asked, so the step never queued for an approval — it goes
        # `PENDING → SKIPPED`/`APPROVAL_DENIED`, naming the recorded `DENY`.
        return await self._deny(state, step, decision, tool)

    async def resume(
        self,
        state: ExecutionState,
        step_id: str,
        *,
        confirmation_id: str | None = None,
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

        **A stale confirmation is refused before anything is authored** when a
        ``confirmation_ttl`` was configured (:meth:`_check_fresh`, #243): past its
        lifetime a question is no longer answerable, whichever way the human
        replied. With no lifetime set — the default — no confirmation expires.

        Args:
            state: The execution as currently stored. The step must be parked in
                *it*, awaiting the confirmation's own tool — checked here rather
                than left to the transition graph, which would find the same
                step of a *second* execution of the same plan perfectly claimable
                (:meth:`_check_parked`).
            step_id: The step the confirmation was about, read from the
                execution's plan for :meth:`run`'s reason.
            confirmation_id: The recorded ``CONFIRM``'s id, as returned in the
                :class:`StepDisposition` that parked it — the **in-process** path,
                where the caller still holds it. ``None`` on the **restart** path:
                the ``→ AWAITING_APPROVAL`` transition never stored the id (#242),
                so a reloaded step has none, and the confirmation is recovered
                from the trail by its ``(execution_id, step_id)`` binding instead
                (:meth:`_confirmation_for`, ADR-0044 §3).
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
            AuditError: If the confirmation is absent from the trail, is not the
                record ``confirmation_id`` names (:meth:`_recorded`), if the
                trail refuses the resolving decision, or if it does not hand back
                the record of it.
            PermissionDeniedError: If the named confirmation was not a ``CONFIRM``,
                or is a ``CONFIRM`` about a different step, or one this execution
                is not parked on (:meth:`_check_parked`), or one answered past its
                configured lifetime (:meth:`_check_fresh`); or, on the restart
                path, if the trail holds no pending confirmation for the binding —
                it is already resolved, or the step was never parked
                (:meth:`_confirmation_for`). Refused before anything is authored,
                so a mismatched or stale answer cannot become a recorded decision.
            PlanningError: As :meth:`run`.
        """
        # A private copy for `run`'s reason: `_check_parked` authenticates the
        # stored execution, and the claim must land on the same one, not on a
        # `state` a caller can rewrite mid-await (`_detached_state`).
        state = _detached_state(state)
        opened = await self._opened(state)
        step = await self._planned(opened, step_id)
        confirmed = await self._confirmation_for(state, step.id, confirmation_id)
        if confirmed.ruling.outcome is not PermissionOutcome.CONFIRM:
            msg = (
                f"decision {confirmed.id!r} is a {confirmed.ruling.outcome} and was never "
                "shown as a question, so an answer to it authorises nothing"
            )
            raise PermissionDeniedError(msg)
        if confirmed.step_id != step.id:
            # ADR-0021 §1 binds an approval to the step. Accepting a
            # confirmation authorised for another one would let one step's
            # prompt release a different step's action — the shape the executor
            # refuses at its own boundary, one stage earlier.
            msg = (
                f"decision {confirmed.id!r} confirms a different plan step, so resolving it "
                f"here would release step {step.id!r} on somebody else's answer"
            )
            raise PermissionDeniedError(msg)
        self._check_parked(opened, step, confirmed.tool.id, confirmation_id=confirmed.id)
        self._check_fresh(confirmed)

        request = ActionRequest(
            tool=confirmed.tool, parameters=step.parameters, step_id=step.id, execution_id=state.id
        )
        # Its own copy again, for `run`'s reason: `confirmed.id` is read after
        # this returns, and it is what `resolves` will point at.
        ruling = await self._policy.resolve(confirmed.model_copy(deep=True), approved=approved)
        decision = await self._record(request, ruling, resolves=confirmed.id)
        if decision.ruling.outcome is PermissionOutcome.ALLOW:
            return await self._execute(state, step, request, decision, timeout=timeout)
        return await self._deny(state, step, decision, confirmed.tool)

    async def _confirmation_for(
        self, state: ExecutionState, step_id: str, confirmation_id: str | None
    ) -> PermissionDecision:
        """The ``CONFIRM`` to resolve — named by the caller, or recovered on restart.

        In-process the caller carries the id the parking :class:`StepDisposition`
        returned, and it is loaded and authenticated (:meth:`_recorded`). On the
        restart path there is none — the ``→ AWAITING_APPROVAL`` transition never
        stored it (#242) — so the confirmation is recovered from the trail by its
        ``(execution_id, step_id)`` binding, the query ADR-0044 §3 adds for
        exactly this. The recovery keys on the reloaded execution, so it needs no
        caller-carried id and no ``core`` change. Either way :meth:`resume`'s own
        checks and :meth:`_check_parked` (including that the confirmation's tool
        equals the reloaded step's ``bound_tool``) then run over the result, so
        the restart path is held to the same guarantees as the in-process one.

        Returns ``pending_confirmation``'s result unchanged: ``None`` there means
        the binding is decided or empty, which this turns into the refusal below —
        the trail is never asked to hand back a resolved or absent question.

        Raises:
            AuditError: If an id is given but names no record, or not that record
                (:meth:`_recorded`).
            PermissionDeniedError: On the restart path, if the trail holds no
                pending confirmation for the binding: it is already resolved
                (ADR-0044 §2b/§3), or the step was never parked.
        """
        if confirmation_id is not None:
            return await self._recorded(confirmation_id)
        recovered = await self._trail.pending_confirmation(execution_id=state.id, step_id=step_id)
        if recovered is None:
            msg = (
                f"no confirmation is awaiting an answer for step {step_id!r} of execution "
                f"{state.id!r}: it may already be resolved, or the step was never parked"
            )
            raise PermissionDeniedError(msg)
        return recovered

    # --- the permission stage -------------------------------------------

    def _check_parked(
        self,
        opened: ExecutionState,
        step: PlanStep,
        tool_id: str,
        *,
        confirmation_id: str,
    ) -> None:
        """Require the *stored* execution to hold this step, parked, awaiting this tool.

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

        **The check reads the stored execution, never the caller's ``state``, and
        the difference is not defensive symmetry.** Deferring to the transition
        graph — "a snapshot that disagrees with the store is rejected by the
        commit" — is *false for exactly this move*: if the stored step is
        ``PENDING``, the executor's claim is ``PENDING → RUNNING``, which
        ADR-0014 §4 permits, so a ``state`` forged to read ``AWAITING_APPROVAL``
        would pass this check and then be claimed at its own real version. The
        graph rejects a stale version, not an inconsistent snapshot, and only the
        second is what this guard is for. The caller's ``version`` is still the
        caller's, because that *is* the compare-and-swap's job.

        **What remains is narrow and named** (ADR-0037 §4, #253): two executions
        of one plan, *both* genuinely parked on the same step, are mutually
        substitutable. The trail's single-resolution index still means one
        confirmation authorises one resolution, so the residue is which of two
        identical parked executions proceeds, not whether an unapproved one does.

        Raises:
            PermissionDeniedError: If the step is absent from the stored
                execution, is not ``AWAITING_APPROVAL``, or is bound to a
                different tool.
        """
        parked = opened.step(step.id)
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

    def _check_fresh(self, confirmed: PermissionDecision) -> None:
        """Refuse an answer that arrives past the confirmation's lifetime (#243).

        ADR-0036 §1 declined to put a staleness check in the policy — it needs a
        clock, and ADR-0021 §3 removed the clock from the policy deliberately —
        and concluded a confirmation gone stale "should not be answerable; that
        is `orchestration`'s to enforce". This is that enforcement, and it lives
        here because this stage is the one that both holds a clock and takes the
        answer.

        **Opt-in, and that is the whole of the design's caution.** With no
        ``confirmation_ttl`` configured nothing expires, so a deployment that has
        not decided how long a question stands refuses no legitimate reply — the
        exact hazard ADR-0037 §4 named when it declined to invent a duration at
        the moment an answer arrives. When a lifetime *is* set, the duration is
        the deployment's, read from a construction parameter rather than a rule
        this stage authors, the same division ``ThresholdActionPolicy`` draws
        between its contract-fixed floors and its user-set thresholds.

        **Refused whichever way the human answered.** A stale question is not
        answerable at all, so this runs before ``policy.resolve`` and before any
        record is authored — a late "no" is refused for the same reason a late
        "yes" is, rather than being quietly honoured as a decline. Nothing is
        committed, so the step stays ``AWAITING_APPROVAL``; reclaiming a
        permanently unanswerable park is a separate concern (a plan-level sweep),
        not this stage's to invent here.

        ``decided_at`` is a ``UtcInstant`` and :meth:`_now` returns a guarded
        UTC-aware reading, so the difference is over instants — the comparison is
        well-defined across a DST boundary, which a wall-clock subtraction would
        not be.

        Raises:
            PermissionDeniedError: If a lifetime is configured and this answer
                arrives more than that long after the confirmation was recorded.
            PlanningError: If the injected clock's reading is not conforming
                (:meth:`_now`).
        """
        if self._confirmation_ttl is None:
            return
        age = self._now() - confirmed.decided_at
        if age > self._confirmation_ttl:
            msg = (
                f"decision {confirmed.id!r} was confirmed at {confirmed.decided_at.isoformat()} "
                f"and this answer arrives {age} later, past the {self._confirmation_ttl} a "
                f"confirmation stands, so the question has expired and answers nothing"
            )
            raise PermissionDeniedError(msg)

    async def _record(
        self,
        request: ActionRequest,
        ruling: PermissionRuling,
        *,
        resolves: str | None = None,
    ) -> PermissionDecision:
        """Bind ``ruling`` to ``request``, append it, and return the trail's copy.

        The id and the clock are supplied here because ADR-0021 §3 withholds both
        from the policy — that is what leaves ``decide`` a genuine function of its
        argument, and the monotonicity obligations checkable at all.

        Every branch reaches this, including ``DENY``: ADR-0004 §7 asks for
        reviewability, and a refusal nobody can find a trace of is the half of
        the trail that answers "what did the assistant decline to do".

        **And every branch gets back what the trail holds, not what was written**
        (:meth:`_recorded`). The read-back began as the authorisation path's
        guard, but every outcome puts a decision id into durable state or into a
        caller's hands: a ``DENY`` writes ``approval_ref`` onto the skipped step,
        and a ``CONFIRM`` hands out the id :meth:`resume` will be called with. A
        trail that accepted the write and lost it would leave the first pointing
        at nothing — the dangling ``approval_ref`` ADR-0014 §4 exists to prevent
        — and the second unanswerable forever. Reading back on one branch and
        trusting `record` on the others would have made the guarantee depend on
        which way the policy ruled.

        **What comes back must *equal* what was written — the whole record, not
        its subject.** Comparing the tool, the digest and the step was the
        obvious check and it is the wrong one: it leaves ``ruling`` unexamined,
        so a trail returning a same-subject record with the outcome flipped would
        have this stage act on an answer the policy never gave. A ``DENY`` read
        back as an ``ALLOW`` runs a side-effecting tool the user's policy
        refused; an ``ALLOW`` read back as a ``DENY`` writes a durable refusal
        that never happened. Equality is also the simpler statement of the
        property this whole path exists for — *the trail is holding what was
        decided* — and it is total over the fields, so a field added to
        ``PermissionDecision`` later is covered without anyone remembering to
        extend a list.

        It costs nothing in correctness for a conforming trail: ADR-0021 §4
        requires a decision to survive a ``model_dump(mode="json")`` round trip
        and the shared suite asserts it, which is exactly the claim that the
        stored form reloads equal.

        Leaving it to ``ToolCall`` would not do either. That validator runs
        ``authorises``, which compares the subject and requires an ``ALLOW`` — but
        a ``ToolCall`` only exists on the ``ALLOW`` path, so every check it makes
        is one a refusal or a question never reaches, and the consequences there
        are just as durable: a ``DENY`` skipping the planned step with an
        ``approval_ref`` whose record describes something else, or a ``CONFIRM``
        parking the step while handing back a confirmation about another tool,
        which :meth:`_check_parked` then refuses for ever.

        Raises:
            AuditError: If the trail refused the append — a duplicate id, or a
                ``resolves`` pointer that failed its invariant — or if it does
                not hand back the record under that id (:meth:`_recorded`), or
                hands back one that differs from what was written.
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
        recorded = await self._recorded(decision.id)
        if recorded != decision:
            msg = (
                f"the trail's copy of decision {recorded.id!r} is not the decision that was "
                "recorded, so it is not a record of what happened"
            )
            raise AuditError(msg)
        return recorded

    def _authorised(self, request: ActionRequest, recorded: PermissionDecision) -> ToolCall:
        """Build the call from the trail's copy of the decision (ADR-0037 §3).

        **This is what closes issue #107**, and it closes it by construction: the
        only ``ToolCall`` this pipeline can produce is one built out of a record
        the trail handed back (:meth:`_record`), so the ``approval_ref`` the
        executor pins is necessarily an id that resolves. Checking that ``record``
        did not raise would be weaker — a trail that accepted a write and lost it
        answers ``None``, and a trail whose row no longer validates raises
        ``AuditError`` from ``get`` itself (ADR-0036 §2), so "never recorded" and
        "corrupted" stay distinguishable.

        The round trip is a real comparison rather than a ceremony, and by the
        time this runs most of it has already happened: :meth:`_record`
        established that what came back is the record that id names and that it
        rules on this action. ``ToolCall``'s validator re-runs
        ``PermissionDecision.authorises`` over the same pair anyway — the type's
        own invariant, checked by the type, so the call cannot exist unauthorised
        whatever this method believes.

        Raises:
            AuditError: If the recorded decision does not authorise ``request``.
        """
        try:
            return ToolCall(request=request, decision=recorded)
        except ValidationError as exc:
            msg = (
                f"the trail's copy of decision {recorded.id!r} does not authorise this request, "
                "so it is not a record of what was approved"
            )
            raise AuditError(msg) from exc

    async def _recorded(self, decision_id: str) -> PermissionDecision:
        """Load the decision ``decision_id`` names, and prove it is that one.

        **The identity check is not redundant with what the caller does with the
        result**, and leaving it out is how the guarantee in :meth:`_authorised`
        quietly stops holding. ``AuditTrail.get`` is contracted to answer the
        decision *with* that id, but a store keys the row and serialises the
        record separately (ADR-0036 §2), so a row keyed ``d-1`` whose stored JSON
        carries ``id="d-2"`` round-trips and validates. Everything downstream
        reads ``decision.id``: ``authorises`` compares the subject and not the
        id, ``ToolCall`` would construct, and the executor would commit
        ``approval_ref="d-2"`` — an id that need not be a key in the trail at
        all, which is precisely the "the ``approval_ref`` resolves" property
        issue #107 is about. On the resolution path the same swap would point
        ``resolves`` at a decision nobody was shown.

        Raises:
            AuditError: If the trail holds nothing under ``decision_id``, or
                holds a record that calls itself something else.
        """
        recorded = await self._trail.get(decision_id)
        if recorded is None:
            msg = (
                f"the trail does not hold decision {decision_id!r}, so nothing recorded "
                "authorises this call"
            )
            raise AuditError(msg)
        if recorded.id != decision_id:
            msg = (
                f"the trail answered for decision {decision_id!r} with a record that calls "
                f"itself {recorded.id!r}, so it is not the decision that was asked for"
            )
            raise AuditError(msg)
        return recorded

    # --- the plan --------------------------------------------------------

    async def _opened(self, state: ExecutionState) -> ExecutionState:
        """Load the execution ``state`` names, as the store actually holds it.

        **Everything this stage decides about *what has already happened* reads
        this, not the argument** — which plan the step comes from
        (:meth:`_planned`), whether the step is still to be disposed of
        (:meth:`_check_pending`) and whether it is genuinely parked
        (:meth:`_check_parked`). The caller's ``state`` supplies exactly one
        thing, its ``version``, because that is the compare-and-swap token and
        the store is what adjudicates it.

        Splitting it that way is what makes the two guards honest. A caller's
        ``ExecutionState`` is a value it can build: fields it asserts about the
        past are checkable against the store and are checked, and the one field
        that is a claim about *concurrency* is left to the mechanism designed to
        settle it.

        ``state`` here is already the private snapshot :meth:`run` and
        :meth:`resume` take on entry (:func:`_detached_state`), so the ``id`` this
        loads by and the ``version`` the transitions carry are the ones the caller
        named *before* the first await — not values a shared object could change
        once a guard has passed.

        Raises:
            PlanningError: If the store holds no execution with that id.
        """
        opened = await self._plans.get_execution(state.id)
        if opened is None:
            msg = (
                f"the store holds no execution {state.id!r}, so there is nothing that says "
                "which plan this step belongs to or where it stands"
            )
            raise PlanningError(msg)
        return opened

    def _check_pending(self, opened: ExecutionState, step_id: str) -> None:
        """Require the stored step to be ``PENDING`` before :meth:`run` rules on it.

        **Checked before the policy is asked, because the cost of not checking is
        a decision nobody can use.** Recording precedes every transition
        (ADR-0037 §2), so a ``run`` against a step that is already
        ``AWAITING_APPROVAL`` would consult the policy, append a second
        ``CONFIRM`` to the trail, and only then be refused by the transition
        graph — leaving a decision in a Tier 1 append-only store that was never
        shown to anyone, cannot be resolved (:meth:`_check_parked` binds a
        resolution to the *parked* step's own confirmation), and cannot be
        deleted (ADR-0021 §4 offers no selective erasure). The right answer for
        that step is :meth:`resume`, and this says so.

        ``PENDING`` is the only entry, and ``FAILED`` is deliberately not a
        second one (ADR-0037 §6). ADR-0014 §4 permits ``FAILED → RUNNING`` while
        attempts remain, so an ``ALLOW`` would work and a ``CONFIRM`` or ``DENY``
        would not — the same call succeeding or failing on which way the policy
        ruled. Re-driving a failed step is plan-level work, and this object
        disposes of one step.

        Raises:
            PlanningError: If the step is absent from the stored execution, or is
                not ``PENDING``.
        """
        stored = opened.step(step_id)
        if stored is None:
            msg = f"execution {opened.id!r} has no step {step_id!r}"
            raise PlanningError(msg)
        if stored.status is StepStatus.PENDING:
            return
        if stored.status is StepStatus.AWAITING_APPROVAL:
            msg = (
                f"step {step_id!r} is already awaiting approval; answering it is `resume`'s, "
                "and ruling again would record a decision nobody can use"
            )
            raise PlanningError(msg)
        msg = f"step {step_id!r} is {stored.status}, so there is nothing here left to dispose of"
        raise PlanningError(msg)

    async def _planned(self, opened: ExecutionState, step_id: str) -> PlanStep:
        """Read the step from the plan this execution belongs to (ADR-0037 §2).

        The execution names its plan and the plan owns the steps, so this is the
        one place the capability and the parameters can come from without a
        caller's word for it. Detached on the way out (:func:`_detached_step`), since
        ``PlanStore`` contracts no snapshot.

        ``opened`` is the *stored* execution (:meth:`_opened`), so the plan is
        the one this execution really belongs to: taking ``state.plan_id`` would
        have accepted the association on the caller's word while every write took
        ``state.id``, letting a hand-built state carrying execution A's id with
        execution B's ``plan_id`` have the gate rule on B's step and the claim,
        the invocation and the durable record land on A's.

        Raises:
            PlanningError: If the plan is missing, or holds no such step. Missing
                is not "nothing to do": an execution whose plan has gone is a
                store that cannot say what was meant to happen, and running
                anything under it would be inventing the intent.
        """
        plan = await self._plans.get_plan(opened.plan_id)
        if plan is None:
            msg = (
                f"execution {opened.id!r} names plan {opened.plan_id!r}, which the store does "
                "not hold, so there is nothing that says what this step should do"
            )
            raise PlanningError(msg)
        planned = next((step for step in plan.steps if step.id == step_id), None)
        if planned is None:
            msg = f"plan {plan.id!r} has no step {step_id!r}"
            raise PlanningError(msg)
        return _detached_step(planned)

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

        ``decision`` is already the trail's own copy (:meth:`_record`), and the
        call is built from it before the claim — so a trail that cannot produce
        the authority has stopped the turn *before* the executor touches durable
        state, rather than leaving a step ``RUNNING`` over a decision nobody can
        find (ADR-0037 §3).
        """
        call = self._authorised(request, decision)
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

        Reached from both entry points, over the one edge ADR-0041 made legal
        for either: :meth:`run` skips straight from ``PENDING`` when the policy
        refused outright, and :meth:`resume` from ``AWAITING_APPROVAL`` when a
        human said no. ``approval_ref`` is required on both by ``PlanExecution``,
        which refuses to record a denial without one whichever status it comes
        from — the same insistence ADR-0014 §4 places on the claim, from the
        other side. A ``PENDING`` denial therefore carries no ``bound_tool``:
        nothing was queued for an approval, and the ``approval_ref`` names the
        decision that identifies the tool.
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
