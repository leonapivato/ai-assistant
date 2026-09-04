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

- **Selection runs the unique least severe candidate whose schema the arguments
  fit** (ADR-0144, ADR-0145 §2). ADR-0016 §5 refused to rank, ADR-0016 §7
  deferred ranking here, and ADR-0037 §1 declined to invent it — ``candidates[0]``
  is a ranking by *name*. ADR-0144 is that rule arriving (#241) and
  :mod:`ai_assistant.orchestration.selection` holds it. Two filters bind before
  it: argument fit removes a candidate whose ``parameters_schema`` the step's
  parameters violate (ADR-0144 §7), and an evaluation that *raises* refuses the
  step outright (ADR-0145 §7). What survives is ordered, and only a genuine tie
  under the whole key still leaves the step ``PENDING`` (ADR-0144 §6).
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
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    AuditError,
    EgressBindingError,
    PermissionDeniedError,
    PlanningError,
    UngrantableActError,
)
from ai_assistant.core.types import (
    ActionRequest,
    CarriedProvenance,
    CoverageUnrecordedBinding,
    Disposition,
    EgressBinding,
    ExecutionState,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    PlanStep,
    SkipReason,
    StepStatus,
    StepTransition,
    ToolCall,
)
from ai_assistant.orchestration.capability_alias import resolve_capability
from ai_assistant.orchestration.selection import Preference, eligible_candidates, select

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        ActionPolicy,
        AuditTrail,
        EgressBinder,
        PlanStore,
        ToolRegistry,
    )
    from ai_assistant.core.types import (
        BoundEgressCall,
        FrozenJsonMapping,
        ParameterViolation,
        PermissionRuling,
        ToolDefinition,
    )
    from ai_assistant.orchestration.executor import StepExecutor
    from ai_assistant.orchestration.origin import SelectionOrigin

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


def _requested(
    tool: ToolDefinition,
    step: PlanStep,
    state: ExecutionState,
    bound: BoundEgressCall | None,
) -> ActionRequest:
    """Build the request from what the binding seam returned, never from what was retained.

    ADR-0152 §1: the caller builds its ``ActionRequest`` from the returned
    :class:`~ai_assistant.core.types.BoundEgressCall`'s ``tool``, ``parameters``
    and ``binding``, and **never** from objects it held across the call. The seam
    derives from copies it detached before its one awaited read, so a runner that
    kept its own would hand the policy a request the seam never described — the
    mismatched pair ADR-0152 §1 says must not exist, reachable through a mutation
    landed during that suspension.

    This is called with no ``await`` between it and the seam returning, which is
    what keeps the residual obligation one clause on one site rather than a rule
    about an object's whole lifetime.

    Where ``bound`` is ``None`` the request is built exactly as it was before this
    seam existed — the tool and the parameters this stage already holds, with
    ``egress_binding=None`` (ADR-0152 §8). There is no binding, so there is no pair
    to hold together and no divergence to falsify anything.

    Args:
        tool: The selected or confirmed definition, used only on the ``None`` path.
        step: The plan step, for its id and its parameters on the ``None`` path.
        state: The execution, for its id.
        bound: What the seam returned, or ``None``.

    Returns:
        The request the policy will rule on.
    """
    if bound is None:
        return ActionRequest(
            tool=tool, parameters=step.parameters, step_id=step.id, execution_id=state.id
        )
    return ActionRequest(
        tool=bound.tool,
        parameters=bound.parameters,
        step_id=step.id,
        execution_id=state.id,
        egress_binding=bound.binding,
    )


@dataclass(frozen=True, slots=True)
class EstablishingAnswer:
    """The two records a standing recipient grant is transcribed from (ADR-0235 §2).

    Carried out of :meth:`StepRunner.resume` on the one path that collected an
    establishing act, so the engine can build the grant with
    :meth:`~ai_assistant.core.types.RecipientGrant.established_from` and record it.
    Both are the **trail's own copies** — the confirmation this stage read back and
    the resolving decision it recorded and read back — so nothing downstream
    transcribes a subject from a value a caller supplied.

    **The engine and not this stage performs the act**, because ADR-0235 §12 puts
    the ``RecipientGrantStore``'s whole face on ``Engine`` and nowhere else. What
    this stage owes is the pair, the two refusals that must fire before any ruling
    is sought (ADR-0235 §1's expiry, §2's binding), and the guarantee that
    ``answer`` carries the very instant the expiry was compared against.

    An `orchestration`-local dataclass and **not** promoted surface, exactly as
    :class:`StepDisposition` is: no public method returns it and no promoted field
    reaches it, so ADR-0085 §5's walk never gets to it.

    Attributes:
        confirmed: The recorded ``CONFIRM`` the answer rode, read back from the
            trail.
        answer: The resolving decision this stage recorded, read back from the
            trail. Its ruling is the policy's and may be a ``DENY``: what became of
            the standing request is the engine's to report (ADR-0235 §6), and this
            stage draws no conclusion from it.
    """

    confirmed: PermissionDecision
    answer: PermissionDecision


@dataclass(frozen=True, slots=True)
class StepDisposition:
    """What one pass of :class:`StepRunner` did with a step (ADR-0037 §4).

    A frozen dataclass in `orchestration` and **not** on the promoted surface: it
    is a *stage* type no public method returns and no promoted field reaches, so
    ADR-0085 §5's walk never gets to it and §6c leaves it exactly where it is.
    :class:`~ai_assistant.core.types.StepOutcome` is what the engine hands a client
    instead, richer by the confirmation content a bare tool id cannot convey.

    Attributes:
        disposition: Which outcome happened.
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
        tied_candidates: The ids of the candidates that tied under the whole
            ordering, on ``AMBIGUOUS_CAPABILITY``, and empty on every other
            disposition (ADR-0144 §6). **They stop here.** ADR-0144 §6 puts them
            on this dataclass precisely because it *"crosses no subsystem
            boundary"* (ADR-0037 §4), decides no route by which they reach an
            interface, and forbids inventing one:
            :class:`~ai_assistant.core.types.StepOutcome` is the public carrier
            and has no field for them, which is a ``core`` change with its own
            ADR (#1103). Until then they reach a log line and the operator, whose
            recovery is a preference sequence naming one of them (#1101).
        violations: What the arguments missed, on the ``INVALID_PARAMETERS``
            disposition ADR-0145 §4 reaches by its **first** cause — every capable
            candidate reported violations, so the eligibility filter emptied the
            set. Empty on its **second** cause, an evaluation that raised, which
            §7 requires to report none; and empty on every other disposition.
            Orchestration-local for ``tied_candidates``' reason: carrying them to
            a client is an additive wire change with its own Tier question, which
            ADR-0145 §14 files as #1106.
        establishing: The pair a standing recipient grant would be transcribed from,
            on the one path that collected an establishing act — a
            :meth:`StepRunner.resume` carrying ``remember_recipients_until`` beside
            ``approved=True`` that reached a recorded answer (ADR-0235 §2). ``None``
            everywhere else, including on a ``resume`` that collected the act and
            was refused before any ruling was sought, which raises instead.
    """

    disposition: Disposition
    state: ExecutionState
    decision_id: str | None = None
    tool_id: str | None = None
    decision: PermissionDecision | None = None
    tied_candidates: tuple[str, ...] = ()
    violations: tuple[ParameterViolation, ...] = ()
    establishing: EstablishingAnswer | None = None


class StepRunner:
    """Selects a tool for a step, gates it, and runs it (ADR-0037).

    Args:
        plans: Durable planning state. Every transition this object makes goes
            through :meth:`~ai_assistant.core.protocols.PlanStore.commit_transition`,
            the same compare-and-swap the executor's claim depends on.
        registry: Asked which tools advertise a step's capability. It does not
            choose (ADR-0016 §5); this object does, by ADR-0144's fixed rule and
            not by anything the registry's ``id`` ordering says.
        policy: The gate ADR-0004 §7 requires in front of every side-effecting
            call. It rules; it does not record (ADR-0021 §3).
        trail: Where every ruling is recorded, and — crucially — where the
            authority handed to the executor is read back from (ADR-0037 §3).
        executor: The ``execute`` stage. This package's own object rather than a
            Protocol, because it is not another subsystem: golden rule 1 governs
            what crosses a package boundary, and nothing here does.
        binder: The egress binding seam (ADR-0152 §1), consulted after selection
            and before the ``ActionRequest`` is built, and again after a parked
            confirmation is authenticated and before the request is rebuilt. It
            answers what the call would transmit and to whom, which is
            integration-specific knowledge living in `tools/` — so it is reached
            through its Protocol and never through an injected concrete.
            ``None``, the default, is the behaviour before ADR-0152 exactly:
            every request is built with ``egress_binding=None``. That is not a
            gap left open, because ``ai_assistant.tools.egress`` is approved and
            **undesignated** (ADR-0017 §2) and no tool is registered at it, so a
            runner without a binder cannot reach an egress call to leave unbound;
            the composition root wires the one implementation when there is
            something to bind.
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
        binder: EgressBinder | None = None,
        now: Clock = _utcnow,
        id_factory: Callable[[], str] = _uuid,
        confirmation_ttl: timedelta | None = None,
        tool_preference: Sequence[str] = (),
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

        It applies at **ask** time (ADR-0059 §1): the duration is turned into a
        deadline on the record when the ``CONFIRM`` is written (:meth:`_deadline`)
        rather than recomputed when an answer arrives, so a question is answered
        under the lifetime it was asked under and a later change to this setting
        leaves already-parked confirmations alone.

        ``tool_preference`` is the other one, and it is ADR-0144 §4's preference
        sequence: the ordered tool ids that break a tie **key 6 has reached** —
        that is, between candidates the severity block and latency have already
        found equal. It can never promote a candidate over one keys 1 through 5
        prefer, and this stage exposes no other route by which a caller may
        influence which candidate is chosen. **It is configuration and never
        consent** (ADR-0144 §4): nothing in it grants, authorises or relaxes any
        permission outcome, and whichever candidate it picks is ruled on against
        its own declaration before anything runs (ADR-0016 §3).

        The sequence is **snapshotted and validated here, and never re-read**
        (:class:`~ai_assistant.orchestration.selection.Preference`). A
        mutation the caller makes to what it passed — before, between or during a
        selection — changes no later selection, which is what keeps §1's
        order-independence true and the duplicate check a check that stays
        checked. The cost is stated rather than smoothed over: a *changed*
        preference reaches only a newly constructed stage, so recovering a tie by
        naming one of the tied ids means building this object again — in practice
        the next process life (ADR-0144 §5), which is already true of the
        registry ADR-0016 §6 rebuilds each run.

        Raises:
            ValueError: If ``confirmation_ttl`` is set and not strictly positive.
                A zero or negative lifetime would expire every confirmation the
                instant it was recorded, which is a way to make the whole
                confirmation flow unanswerable by misconfiguration rather than a
                lifetime; refused at construction rather than surfacing per
                answer. Or if ``tool_preference`` names any tool more than once
                (ADR-0144 §4).
        """
        if confirmation_ttl is not None and confirmation_ttl <= timedelta(0):
            msg = f"confirmation_ttl must be strictly positive, got {confirmation_ttl}"
            raise ValueError(msg)
        self._preference = Preference(tool_preference)
        self._plans = plans
        self._registry = registry
        self._policy = policy
        self._trail = trail
        self._executor = executor
        self._binder = binder
        self._clock = checked_clock(now, owner="StepRunner")
        self._id_factory = id_factory
        self._confirmation_ttl = confirmation_ttl

    async def run(
        self,
        state: ExecutionState,
        step_id: str,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — passed through to the seam, which owns the deadline (ADR-0029 §4)
        origin: SelectionOrigin,
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
                on — checked against each capable candidate's
                ``parameters_schema`` **before** any ruling is requested
                (ADR-0145 §2), so a policy never rules on a call no tool could
                perform.
            timeout: How long the seam may wait, per attempt; passed through to
                the executor. The caller's budget, not the tool's property
                (ADR-0029 §4).
            origin: What the material this system selected into the model call
                whose output produced this step rests on (ADR-0181 §2, §4), and
                what that supply makes of the call under ADR-0155 §3's partition
                (ADR-0233 §4, §5) — **both** stamped onto the carrier :meth:`_bound`
                hands the egress seam, and read there and nowhere else.
                **Required with no default**, for the reason ADR-0181 §3 and
                ADR-0233 §4 each give their ``core`` field: the safe-looking
                defaults are "nothing external was selected" and "nothing is
                covered", which are claims about a selection the defaulting caller
                never made, and a lane that never wired a selection through would
                get both for free. A caller that genuinely selected nothing passes
                :data:`~ai_assistant.orchestration.origin.NOTHING_EXTERNAL`, in
                code a reviewer can see.

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
        capability = await self._resolve_capability(step)
        candidates = await self._registry.find(capability)
        if not candidates:
            skipped = await self._skip(state, step, SkipReason.NO_CAPABLE_TOOL)
            return StepDisposition(Disposition.NO_CAPABLE_TOOL, skipped)
        chosen = self._select(state, step, capability, candidates)
        if isinstance(chosen, StepDisposition):
            # The selection stage declined, and every way it can commits nothing:
            # the step is still `PENDING` and the turn ends here (ADR-0144 §6,
            # ADR-0145 §4).
            return chosen

        tool = chosen
        try:
            bound = await self._bound(tool, step.parameters, origin)
        except EgressBindingError:
            # ADR-0152 §9: the seam refused, so the call cannot be completed. It
            # commits nothing -- no ruling requested, no audit record written, no
            # claim made -- and the step stays `PENDING` at its stored version,
            # which is `INVALID_PARAMETERS`' shape one stage on. A
            # `ConnectionStoreError` is deliberately *not* caught: a store that
            # could not be read asserts nothing about the call, and reporting it
            # as unbindable would write a falsehood into a returned value.
            _log.info("egress_unbindable", step_id=step.id, tool_id=tool.id)
            return StepDisposition(Disposition.EGRESS_UNBINDABLE, state)
        # No `await` sits between the seam returning and this construction, so
        # nothing interleaves on the one event loop and the copies it handed back
        # cannot be reached or replaced before the request is built (ADR-0152 §1).
        request = _requested(tool, step, state, bound)
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

    async def resume(  # noqa: PLR0913 — the execution, the step, the confirmation, the answer, the budget, and ADR-0235 §2's one instant; each is a distinct fact about the act
        self,
        state: ExecutionState,
        step_id: str,
        *,
        confirmation_id: str | None = None,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — passed through to the seam, which owns the deadline (ADR-0029 §4)
        remember_recipients_until: datetime | None = None,
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

        **A stale confirmation is refused before anything is authored** when the
        record carries a deadline (:meth:`_check_fresh`, #243, ADR-0059 §1): past
        its ``expires_at`` a question is no longer answerable, whichever way the
        human replied. A confirmation recorded without one — no
        ``confirmation_ttl`` was configured when it was *asked*, or the record
        predates ADR-0059 — does not expire; the live setting is never applied to
        a record that carries no deadline.

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
            remember_recipients_until: The instant the user asked the call's
                recipients be remembered until, or ``None`` — the default and the
                ordinary case — where they asked for nothing standing (ADR-0235
                §2). Honoured **only** beside ``approved=True``; supplied beside a
                declining answer it establishes nothing and changes nothing else,
                so the ``DENY`` is recorded exactly as it is today and ADR-0042
                §4's guarantee is preserved whole.

        Returns:
            ``EXECUTED`` or ``DENIED``, and the durable state after it. A
            resolving ruling can be nothing else: ``ActionPolicy.resolve`` may
            not return ``CONFIRM``, and a resolving decision that was one is
            unconstructable (``PermissionDecision``'s own validator). Where an
            establishing act was collected and an answer was recorded, the
            disposition also carries the :class:`EstablishingAnswer` pair the grant
            is transcribed from; the engine performs the act and reports what became
            of it (ADR-0235 §6).

        Raises:
            UngrantableActError: If ``remember_recipients_until`` was supplied
                beside ``approved=True`` and the act may not ride this confirmation
                (:meth:`_check_establishable`), or if the instant is not strictly
                after the one that would stamp the answer (ADR-0235 §1). Raised
                **before any ruling is sought**, in the shape this method already
                uses for a binding it may not resume, so nothing is written and the
                step stays parked and answerable without the argument.
            AuditError: If the confirmation is absent from the trail, is not the
                record ``confirmation_id`` names (:meth:`_recorded`), if the
                trail refuses the resolving decision, or if it does not hand back
                the record of it.
            PermissionDeniedError: If the named confirmation was not a ``CONFIRM``,
                or is a ``CONFIRM`` about a different step, or one this execution
                is not parked on (:meth:`_check_parked`), or one answered past the
                deadline fixed on it when it was asked (:meth:`_check_fresh`); or
                one recording an egress call whose origin was never recorded, which
                is unanswerable (ADR-0184 §8); or,
                on the restart
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
        # **The establishing act's own two refusals, before every other one that can
        # still record an answer** (ADR-0235 §1, §2). They run ahead of the two
        # binding refusals below because §12 requires all four shapes those refuse —
        # ``None``, an origin-unrecorded binding, a coverage-unrecorded one, and an
        # ``EgressBinding`` planned over external content — to reach a caller that
        # supplied the argument as ``UngrantableActError``, which is the act's own
        # refusal, rather than as the ``PermissionDeniedError`` a resume without the
        # argument would meet. Both fire before any ruling is sought, so nothing is
        # written and the step stays durably parked and answerable.
        establishing_at: datetime | None = None
        if remember_recipients_until is not None and approved:
            self._check_establishable(confirmed)
            establishing_at = self._establishing_instant(remember_recipients_until)
        approved_binding = confirmed.egress_binding
        if isinstance(approved_binding, OriginUnrecordedBinding):
            # ADR-0184 §8's fourth clause: narrow the union and refuse rather than
            # assume the case away. Such a decision records a call whose origin was
            # never recorded, so ADR-0181 §5's second clause leaves no route by
            # which any authorisation covers it and `EgressBinder.rebind` must
            # never receive one (ADR-0184 §8). `pending_confirmation` already
            # refuses to offer such a park, so the recovery path cannot arrive
            # here; the in-process path can, because `_recorded` reads the trail's
            # `get`, which since ADR-0184 §5 returns the row as history rather than
            # raising. Refused by this seam's own existing name, before any ruling
            # is sought, so nothing is written and the step stays parked.
            msg = (
                f"decision {confirmed.id!r} records an egress call whose origin was never "
                f"recorded, so it cannot be resumed: the question it asked is unanswerable"
            )
            raise PermissionDeniedError(msg)
        if isinstance(approved_binding, CoverageUnrecordedBinding):
            # ADR-0184 §8's fourth clause applied one epoch on (ADR-0233 §14):
            # narrow the union and refuse rather than assume the case away. Such a
            # decision records a call whose coverage was never recorded, so nothing
            # says which of ADR-0155 §3's two prohibitions governs what it would
            # carry and `EgressBinder.rebind` must never receive one. The origin
            # guard above does not catch this epoch — such a row **has**
            # `planned_with_external_content`, so it falls straight past that
            # `isinstance` — which is why the refusal is written rather than
            # inherited. `pending_confirmation` already refuses to offer such a
            # park, so the recovery path cannot arrive here; the in-process path
            # can, because `_recorded` reads the trail's `get`, which returns the
            # row as history rather than raising (ADR-0184 §5). Refused by this
            # seam's own existing name, before any ruling is sought, so nothing is
            # written and the step stays parked.
            msg = (
                f"decision {confirmed.id!r} records an egress call whose coverage was never "
                f"recorded, so it cannot be resumed: the question it asked is unanswerable"
            )
            raise PermissionDeniedError(msg)

        try:
            bound = await self._rebound(confirmed.tool, step.parameters, approved_binding)
        except EgressBindingError:
            # ADR-0152 §7: the binding derived for this resumed call is not the
            # one that was approved, or the reference went `PENDING` while the
            # question stood. Refused *before* the resolving ruling is sought, so
            # no second decision is recorded -- ADR-0148 §1's direction of moving
            # facts earlier, and the check that runs one stage ahead of the
            # callable's own four-way refusal at transmission (ADR-0148 §6).
            _log.info("egress_unbindable_on_resume", step_id=step.id, tool_id=confirmed.tool.id)
            return StepDisposition(Disposition.EGRESS_UNBINDABLE, state)
        request = _requested(confirmed.tool, step, state, bound)
        # Its own copy again, for `run`'s reason: `confirmed.id` is read after
        # this returns, and it is what `resolves` will point at.
        ruling = await self._policy.resolve(confirmed.model_copy(deep=True), approved=approved)
        decision = await self._record(request, ruling, resolves=confirmed.id, at=establishing_at)
        if decision.ruling.outcome is PermissionOutcome.ALLOW:
            disposition = await self._execute(state, step, request, decision, timeout=timeout)
        else:
            disposition = await self._deny(state, step, decision, confirmed.tool)
        if establishing_at is None:
            return disposition
        # An answer **was** recorded, so what became of the standing request is a
        # thing the engine reports on the outcome rather than a raise (ADR-0235 §6).
        # The pair travels whatever the ruling: a policy ``DENY`` on an approving
        # answer is `DECLINED` there, and only the engine holds the store that could
        # say anything more.
        return replace(
            disposition, establishing=EstablishingAnswer(confirmed=confirmed, answer=decision)
        )

    def _check_establishable(self, confirmed: PermissionDecision) -> None:
        """Refuse an establishing act on a binding it may not ride (ADR-0235 §2).

        The same two conditions ADR-0235 §3 places on the recorded population, on
        the held one, and refused **before any ruling is sought** so nothing is
        written and the step stays parked and answerable without the argument.

        **All four shapes reach one refusal, and the ``None`` arm is the one a
        roster would omit** — it is the arm that would otherwise record an ``ALLOW``
        and send the call before
        :meth:`~ai_assistant.core.types.RecipientGrant.established_from` refused a
        binding that is not there.

        Args:
            confirmed: The recorded ``CONFIRM`` the answer would ride.

        Raises:
            UngrantableActError: If the confirmation's ``egress_binding`` is not an
                :class:`~ai_assistant.core.types.EgressBinding`, or is one carrying
                ``planned_with_external_content``.
        """
        binding = confirmed.egress_binding
        if not isinstance(binding, EgressBinding):
            msg = (
                f"decision {confirmed.id!r} records no egress call whose recipients could be "
                f"made standing, so this answer cannot establish a recipient grant; the "
                f"confirmation is unaffected and may still be answered (ADR-0235 §2)"
            )
            raise UngrantableActError(msg)
        if binding.planned_with_external_content:
            msg = (
                f"decision {confirmed.id!r} records a call planned over external content; a "
                f"user answering such a confirmation may approve the call, and may not in "
                f"that act make its recipients standing (ADR-0193 §2, §4; ADR-0235 §2)"
            )
            raise UngrantableActError(msg)

    def _establishing_instant(self, remember_recipients_until: datetime) -> datetime:
        """Read the clock once, and refuse an expiry that is not strictly after it.

        ADR-0235 §1: the instant compared against is **the one this stage will stamp
        on the answer**, chosen once here and used for both, because two clock reads
        admit an expiry that passes the check and fails
        :meth:`~ai_assistant.core.types.RecipientGrant.established_from`'s
        constructor — which is the failure the clause exists to remove rather than
        to narrow. So this reading is threaded into :meth:`_record` as ``at`` and no
        second reading is taken between here and the append.

        Refused **here** rather than at the constructor for the reason §1 gives: an
        operation that did not check would record the answer and only then meet a
        construction refusal, leaving a decision in the trail, no grant, and a user
        told nothing they could act on.

        Args:
            remember_recipients_until: The instant the user chose.

        Returns:
            The clock reading the answer will carry.

        Raises:
            UngrantableActError: If the chosen instant is at or before that reading.
                The message **names the instant it was compared against**.
            PlanningError: If the injected clock's reading is not a conforming one.
        """
        decided_at = self._now()
        if remember_recipients_until <= decided_at:
            msg = (
                f"a standing recipient grant expires strictly after the answer that "
                f"establishes it; {remember_recipients_until.isoformat()} is at or before "
                f"{decided_at.isoformat()}, the instant this answer would carry, so nothing "
                f"was recorded and the confirmation may still be answered (ADR-0235 §1)"
            )
            raise UngrantableActError(msg)
        return decided_at

    async def _bound(
        self, tool: ToolDefinition, parameters: FrozenJsonMapping, origin: SelectionOrigin, /
    ) -> BoundEgressCall | None:
        """Ask the binding seam what this call's egress binding is (ADR-0152 §1, §10).

        Reached **after** selection and **before** the ``ActionRequest`` is built,
        which is ADR-0148 §1's earliness: the request the policy rules on must
        already carry the whole binding, and every part of it is
        integration-specific knowledge living in `tools/`, which this package may
        reach only through a Protocol (golden rule 1).

        ``None`` comes back for a call that is not an egress call — no connected
        account is bound to the tool and its schema declares neither keyword — and
        for a deployment that has wired no binder at all. The two are the same
        answer here on purpose: today nothing is registered at the egress seam,
        which stays approved and undesignated (ADR-0017 §2), so a runner built
        without one cannot reach an egress call to leave unbound. The composition
        root wires the one implementation when there is something to bind.

        The carrier's ``spans`` mapping is **empty**, and that is ADR-0152 §5's
        named residue rather than an omission: nothing in this tree records a
        *span's* origin, so every span the seam describes today is
        ``SYSTEM_SELECTED`` — the fail-closed answer ADR-0146 §2 requires, and an
        under-statement of what a user typed. ADR-0181 closes that residue in one
        direction only: it records a **call-level** origin and no span-level one, so
        no span becomes ``USER_AUTHORED`` by anything here and ADR-0154's
        condition-13 limit stands exactly as attested. The mapping is passed
        deliberately rather than defaulted, which is why
        :class:`~ai_assistant.core.types.CarriedProvenance` has no default for it.

        **``planned_with_external_content`` and ``coverage`` are both the caller's
        ``origin``, unchanged** (ADR-0181 §3, §4; ADR-0233 §4, §5). They are stamped
        here, before the request reaches the seam, and this is the only place either
        is written on the ``bind`` path. Nothing is derived for them, nothing merged
        into them, and no value a model, a tool, a declaration or a plan emitted is
        consulted: a producer's claim has no code path by which to have an effect,
        which is what makes ADR-0181 §4's and ADR-0233 §5's discard-not-merge total
        rather than a rule to remember. The resuming path does not come through here
        at all — :meth:`_rebound` transcribes both from the approved binding instead
        (ADR-0181 §3's fifth clause, ADR-0233 §4's sixth).

        **``coverage`` is computed and not stated, which is ADR-0233 §15's whole
        assignment to this lane.** ADR-0233 §5 puts the computation on "the component
        that composed the call's arguments", and this package is it: it chose the
        records the planner was shown, and
        :meth:`~ai_assistant.orchestration.origin.SelectionOrigin.over` decides from
        that selection which of ADR-0155 §3's two prohibitions governs what the call
        would carry. A supply drawn from this system's stores makes the arguments
        covered content every covered path of which runs through the planner's model
        call — ``MODEL_ON_EVERY_PATH``; an empty supply makes them covered by nothing
        — ``NOT_COVERED``. Neither is a constant here: this method reads the answer
        the composing pass computed and writes it through, so a change in what the
        pass selected changes what the binding records.

        Returns:
            The derived binding beside the detached call, or ``None``.

        Raises:
            EgressBindingError: If the seam refused the call.
            ConnectionStoreError: If the connection record could not be read.
                Propagated out of this stage unconverted (ADR-0152 §9), which has
                committed nothing at that point.
        """
        if self._binder is None:
            return None
        return await self._binder.bind(
            tool,
            parameters=parameters,
            provenance=CarriedProvenance(
                spans={},
                planned_with_external_content=origin.planned_with_external_content,
                # ADR-0233 §5, §15: the caller's `origin` again, unchanged. It is
                # **computed** over the very selections the boolean above is
                # computed over, on the one pass, by the component that composed
                # what the model was shown — never a constant, never inferred here,
                # and never read off the payload (`SelectionOrigin.over`).
                coverage=origin.coverage,
            ),
        )

    async def _rebound(
        self, tool: ToolDefinition, parameters: FrozenJsonMapping, approved: EgressBinding | None
    ) -> BoundEgressCall | None:
        """Re-derive a resuming call's binding and check it against what was approved.

        ADR-0037 §4 rebuilds the request from the confirmation's own embedded
        definition and the step's parameters; ADR-0148 §1 requires that request to
        carry the whole binding before ``resolve`` too, and nothing before ADR-0152
        compared the rebuilt binding against the one the parked confirmation
        carries.

        The provenance is **not** passed here and is taken from ``approved``
        inside the seam (ADR-0152 §7). A ``rebind`` handed a fresh, empty carrier
        would describe every span as ``SYSTEM_SELECTED`` and refuse every resumed
        call whose user typed anything.

        **Nor is a ``SelectionOrigin``, and for the same reason one field over**
        (ADR-0181 §3's fifth and sixth clauses, which narrow ADR-0152 §7's count
        from exactly one to exactly two). The fact is about a selection made before
        the confirmation was parked — plausibly before a restart, on a path where
        no turn survives at all (ADR-0052 §3) — so there is no selection set here to
        recompute it from. The seam transcribes ``planned_with_external_content``
        from ``approved``; a member that re-derived it would answer ``False``,
        compare unequal to every approved binding carrying ``True``, and refuse
        every resumed egress call planned over external material, which is precisely
        the call the user was asked about and approved.

        Returns:
            The **derived** binding beside the detached call, or ``None``.

        Raises:
            EgressBindingError: If the seam refused the call.
            ConnectionStoreError: If the connection record could not be read.
        """
        if self._binder is None:
            return None
        return await self._binder.rebind(tool, parameters=parameters, approved=approved)

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

        **The deadline is read off the record, never recomputed here (ADR-0059
        §1).** The lifetime was fixed when the question was asked, as
        ``decided_at + confirmation_ttl`` frozen onto ``expires_at``
        (:meth:`_deadline`), so all that is left at answer time is the single
        comparison ``_now() > confirmed.expires_at``. The ``>`` is the specified
        boundary: ``expires_at`` is the **last answerable instant**, so an answer
        arriving exactly at it is accepted and one strictly after it is refused
        — the behaviour the ``age > confirmation_ttl`` bound it replaces also
        had, and ADR-0044's "a fast confirmation at a coarse clock resolution is
        real" is the same point.

        **``expires_at is None`` means no lifetime, uniformly, and that is the
        whole of the design's caution.** A record carries no deadline when the
        deployment configured no ``confirmation_ttl`` at ask time, when the
        deadline was not representable (:meth:`_deadline`), or when the record
        predates ADR-0059 — and all three read the same way here: the question
        does not expire. There is deliberately **no answer-time recompute**
        against the *live* ``self._confirmation_ttl``, which is what keeps
        ``None`` unambiguous; recomputing would make it mean two contradictory
        things at once ("explicitly unbounded" and "needs the live ttl"), since a
        deployment with no lifetime records ``None`` too. ADR-0059
        §Consequences states the one cost — a confirmation parked *before* the
        upgrade and answered after it loses the best-effort bound it would once
        have been checked against — as a bounded, deliberate migration
        limitation in the safe direction, not a silent strip. The *policy* (the
        duration, and whether any lifetime applies) stays the deployment's
        construction parameter, the same division ``ThresholdActionPolicy`` draws
        between its contract-fixed floors and its user-set thresholds; what
        changed is only that it is read at ask time rather than here.

        **Refused whichever way the human answered.** Once past the lifetime a
        question is treated as no longer answerable, so this runs before
        ``policy.resolve`` and before any record is authored — a late "no" is
        refused for the same reason a late "yes" is, rather than being quietly
        honoured as a decline. Nothing is committed, so the step stays
        ``AWAITING_APPROVAL``; reclaiming a permanently unanswerable park is a
        separate concern (a plan-level sweep), not this stage's to invent here.

        **Durable across a restart; still a wall-clock bound across a
        correction.** The anchor is one ``UtcInstant`` on the record rather than
        a difference of two live readings, so a restart neither loses the
        deadline nor re-derives it — the half of #277 ADR-0059 §1 states it
        closes, and what makes a *later* ``confirmation_ttl`` change leave
        already-asked questions on the lifetime they were promised. Against a
        clock *correction* it is no better, and the ADR does not claim
        otherwise: because ``expires_at == decided_at + ttl``, this comparison
        and the subtraction it replaces re-open on the identical condition, so
        any backward correction carrying ``_now()`` back across the deadline
        makes an expired confirmation answerable again. The failure direction
        stays the safe one — an approval the user genuinely gave is honoured
        late, never an action performed without one, and the trail's
        single-resolution index still binds one approval to one resolution.
        Immunity would need a *monotonic* component, which ADR-0059
        §Alternatives rejects as a record field (it is defined only within one
        process and resets across the restart the deadline must survive) and
        defers to an optional process-local layer here (#277).

        Raises:
            PermissionDeniedError: If the confirmation carries a deadline and
                this answer arrives strictly after it.
            PlanningError: If the injected clock's reading is not conforming
                (:meth:`_now`).
        """
        if confirmed.expires_at is None:
            return
        now = self._now()
        if now > confirmed.expires_at:
            msg = (
                f"decision {confirmed.id!r} was confirmed at {confirmed.decided_at.isoformat()} "
                f"and stood until {confirmed.expires_at.isoformat()}, but this answer arrives at "
                f"{now.isoformat()}, so the question has expired and answers nothing"
            )
            raise PermissionDeniedError(msg)

    async def _record(
        self,
        request: ActionRequest,
        ruling: PermissionRuling,
        *,
        resolves: str | None = None,
        at: datetime | None = None,
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

        **This is where a confirmation's lifetime is fixed** (:meth:`_deadline`,
        ADR-0059 §1). The deadline belongs to the question at the moment it is
        asked, so it is derived here from the same clock reading that stamps
        ``decided_at`` and frozen onto the record; :meth:`_check_fresh` then only
        compares against it. The deadline is the *recorder's* to supply — the
        deployment's lifetime, not a fact the policy authored — which is why
        ``from_request`` takes it as a parameter rather than transcribing it,
        and why the policy stays clock-free (ADR-0036 §1, ADR-0021 §3).

        **``at`` is the one caller-supplied reading and it exists for ADR-0235 §1.**
        An establishing act compares the user's chosen expiry against *the instant
        this answer will carry*, and §1 forbids a second clock read between that
        comparison and this append — "two reads admit an expiry that passes the
        check and fails the constructor". So :meth:`resume` reads the clock once,
        refuses there, and hands the same reading down. It is this stage's own
        guarded reading either way (:meth:`_establishing_instant`), never a value
        that reached the engine from a client, and ``None`` — every other call —
        reads the clock here exactly as before.

        Args:
            request: The action ruled on.
            ruling: What the policy said about it.
            resolves: The recorded ``CONFIRM`` this decision answers, if any.
            at: The reading to stamp, where a caller has already taken and used one
                (ADR-0235 §1); ``None`` to read the clock here.

        Raises:
            AuditError: If the trail refused the append — a duplicate id, or a
                ``resolves`` pointer that failed its invariant — or if it does
                not hand back the record under that id (:meth:`_recorded`), or
                hands back one that differs from what was written.
            PlanningError: If the injected clock's reading is not conforming.
        """
        # One clock reading, used for both the stamp and the deadline derived
        # from it: two reads could put `expires_at` a tick off `decided_at + ttl`
        # and make the record describe a lifetime nobody configured.
        decided_at = self._now() if at is None else at
        decision = PermissionDecision.from_request(
            request,
            ruling,
            id=self._id_factory(),
            decided_at=decided_at,
            resolves=resolves,
            expires_at=self._deadline(ruling, decided_at),
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

    def _deadline(self, ruling: PermissionRuling, decided_at: datetime) -> datetime | None:
        """The instant past which this ruling, if a ``CONFIRM``, stops being answerable.

        ADR-0059 §1's ask-time half: the deployment's ``confirmation_ttl`` is a
        *duration*, and what the record carries is the **instant derived from it
        once**, ``decided_at + confirmation_ttl``. Storing the derived fact
        rather than the policy is what reconciles the field with ADR-0044
        §Alternatives' refusal to put "the deadline" on the record — a question
        asked under a one-hour lifetime *is* a question that expires at a
        specific instant, and that instant is a property of the question. The
        duration itself stays here, a construction parameter, and is read at this
        moment only.

        **``None`` on every other outcome, and that is a construction
        requirement, not tidiness.** ``PermissionDecision`` permits ``expires_at``
        only on a ``CONFIRM`` — a lifetime is a property of an open question, and
        an ``ALLOW``, a ``DENY`` or a resolving ruling carries none — so passing a
        deadline alongside any other outcome would raise at construction rather
        than record anything. The resolving path reaches here too (``resolve``
        may not return ``CONFIRM``), and it is this check that leaves its record
        deadline-free.

        **An unrepresentable deadline is recorded as no lifetime, not raised.**
        Both operands reach the edge of representability — the ADR-0026 clock
        admits a reading within a day of ``datetime.max``, and
        ``confirmation_ttl`` is any strictly-positive ``timedelta`` — so the sum
        can raise a bare ``OverflowError``, which is neither an ``AssistantError``
        nor a specified refusal. ADR-0059 §1 fixes one outcome for it: treat it
        exactly as "no lifetime". That is the safe direction (a question that
        would have expired only at the end of representable time is, for every
        practical purpose, one that does not expire) and it keeps ``None`` a
        single meaning, where the alternatives — failing the ask, or clamping to
        ``datetime.max`` — would either lose a legitimate confirmation to
        arithmetic or record a deadline nobody configured.

        Args:
            ruling: What the policy said; only a ``CONFIRM`` may carry a deadline.
            decided_at: The reading that stamps the record, so that the deadline
                is derived from the same instant it is anchored to.

        Returns:
            The deadline, or ``None`` when the deployment set no lifetime, the
            ruling is not a ``CONFIRM``, or the sum is not representable.
        """
        if self._confirmation_ttl is None or ruling.outcome is not PermissionOutcome.CONFIRM:
            return None
        try:
            return decided_at + self._confirmation_ttl
        except OverflowError:
            _log.warning(
                "confirmation_deadline_unrepresentable",
                decided_at=decided_at.isoformat(),
                confirmation_ttl=str(self._confirmation_ttl),
            )
            return None

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

    def _select(
        self,
        state: ExecutionState,
        step: PlanStep,
        capability: str,
        candidates: Sequence[ToolDefinition],
        /,
    ) -> ToolDefinition | StepDisposition:
        """The selection stage: filter on argument fit, then run the rule (ADR-0144).

        Three refusals and one selection, in the order ADR-0144 §7 and ADR-0145
        §2 jointly fix. **All three refusals commit nothing** — no ruling is
        requested, no audit record is written, no claim is made, and the step
        stays ``PENDING`` — which is why they can be decided here, synchronously,
        before the first collaborator downstream of ``find`` is touched.

        1. **An evaluation that raised refuses the step** (ADR-0145 §7), not
           merely the candidate that raised: ADR-0144 §7's ineligibility clause is
           about a candidate whose schema the parameters *do not satisfy*, and a
           raise establishes no such fact, so ranking the remainder would be
           selecting under an unknown. Nothing about the exception but its **type**
           is logged or carried — its ``str()``, ``args``, ``__cause__`` and
           ``__notes__`` all carry the instance fragments the walk was holding, and
           a schema that raises on demand would otherwise be the one path on which
           an untrusted document makes the argument values arrive in a log
           (ADR-0145 §7, §8).
        2. **The fit filter emptying the set is** ``INVALID_PARAMETERS`` **and not
           a** ``SkipReason`` (ADR-0145 §4). The tools were capable and the
           arguments were not, so ``NO_CAPABLE_TOOL`` would be a falsehood written
           into durable state — what ADR-0014 §4's legal-skip table exists to
           prevent — and ``PENDING`` is already the truth, the state a re-plan with
           corrected arguments can still run the step from.
        3. **A tie under the whole key is** ``AMBIGUOUS_CAPABILITY``, narrowed to
           exactly that residue (ADR-0144 §6). What it now means is stronger than
           what it meant: the tied candidates are equal on every axis ADR-0021 §5
           constrains a policy over, plus cost basis and latency, and the
           deployment named none of them — a question the ordering has no further
           ground to answer and the *user* does. Nothing was committed, so a later
           ``run`` against the still-``PENDING`` step selects afresh (ADR-0144 §5).

        **The fit filter binds before any ordering key**, which is the whole of
        ADR-0144 §7's clause: a fit term folded into the ordering would let a
        well-declared candidate that cannot accept the arguments outrank one that
        can, which is a ranking answering a question about eligibility.

        Args:
            state: The private snapshot, returned unchanged on every refusal —
                nothing here commits, so there is no later state to report.
            step: The step being disposed of; its ``parameters`` are what each
                candidate's schema is evaluated against, unmodified.
            capability: The resolved capability, for the log record only.
            candidates: What ``find`` returned, non-empty.

        Returns:
            The selected declaration, or the disposition that ends the turn.
        """
        fit = eligible_candidates(step.parameters, candidates)
        if fit.failure is not None:
            _log.warning(
                "step_parameter_evaluation_failed",
                step_id=step.id,
                capability=capability,
                candidates=len(candidates),
                error_type=fit.failure,
            )
            return StepDisposition(Disposition.INVALID_PARAMETERS, state)
        if not fit.eligible:
            _log.info(
                "step_parameters_invalid",
                step_id=step.id,
                capability=capability,
                candidates=len(candidates),
                violations=len(fit.violations),
            )
            return StepDisposition(Disposition.INVALID_PARAMETERS, state, violations=fit.violations)
        selection = select(fit.eligible, self._preference)
        if selection.tool is None:
            _log.info(
                "step_capability_ambiguous",
                step_id=step.id,
                capability=capability,
                candidates=len(fit.eligible),
                tied=selection.tied,
            )
            return StepDisposition(
                Disposition.AMBIGUOUS_CAPABILITY, state, tied_candidates=selection.tied
            )
        return selection.tool

    async def _resolve_capability(self, step: PlanStep) -> str:
        """Map the step's capability onto an advertised one before selection (ADR-0053).

        The planner emits capability strings from an open vocabulary and is blind
        to the tool set (ADR-0014 §2), so a synonym of an advertised capability —
        ``get_time`` for ``report_current_time`` — would otherwise select nothing
        and skip the step ``NO_CAPABLE_TOOL`` (#296). This resolves a *known*
        synonym, or a case/separator variant, onto the advertised name, using the
        registry as the authority on the vocabulary (``capabilities()``).

        **It never guesses a capability onto a tool.** :func:`resolve_capability`
        rewrites only onto a name the registry currently advertises, and returns
        the step's own string unchanged for anything it does not recognise — so an
        unknown capability still reaches ``find`` verbatim and is still reported
        ``NO_CAPABLE_TOOL`` honestly. A rewrite does not weaken the selection rule
        either: it changes which capability is looked up, and ADR-0144's ordering
        — with the fit filter ahead of it — still runs over whatever ``find``
        returns.

        This is a pure normalisation over the injected registry — no new
        collaborator, so it needs no composition wiring.
        """
        advertised = await self._registry.capabilities()
        resolved = resolve_capability(step.capability, advertised)
        if resolved != step.capability:
            _log.info(
                "step_capability_aliased",
                step_id=step.id,
                emitted=step.capability,
                resolved=resolved,
            )
        return resolved

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
