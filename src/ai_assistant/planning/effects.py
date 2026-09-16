"""The effect-claim decision, stated once for every store in this package.

ADR-0259 §2 fixes what :meth:`~ai_assistant.core.protocols.PlanStore.claim_effect`
answers as a **total** function of three facts — the stored status of the step the
goal's row names, whether that step is this one, and whether the row's key is this
call's key — and §9 fixes the five limbs a satisfaction's claim condition has. Both
are written here rather than in each store, for the reason
:mod:`ai_assistant.planning.goals` gives of its own refusals: two statements of one
rule are two places for it to drift, and the store's own job is the indivisible step
the decision is taken inside, not the decision.

The canonical fake in :mod:`ai_assistant.testing` re-implements this rather than
importing it, which is the whole point of a conformance suite: the shared arms are
what stop the two drifting, not a shared module the fake would have to reach the
subsystem it stands in for to use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    EffectClaim,
    EffectKey,
    EffectOutcome,
    EffectRecord,
    StepStatus,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ai_assistant.core.types import ActionPlan, FrozenJsonValue

#: The two statuses ADR-0014 §4 calls indistinguishable — "a crash between a tool's
#: side effect and the commit of ``RUNNING → SUCCEEDED`` … cannot, from planning's
#: vantage point, be distinguished from a crash before the effect". Calling either
#: ``COMPLETED`` would assert what nobody knows and calling it ``HELD`` would invite a
#: caller to wait for a step that may never move, so ``UNCERTAIN`` is the honest
#: member and the one R45 asks to be preserved.
_UNCERTAIN_STATUSES = frozenset({StepStatus.RUNNING, StepStatus.INDETERMINATE})

#: The two entry statuses §2 takes the claim at, and therefore the only two §9's fifth
#: limb admits as the source of a satisfaction.
_SATISFIABLE_STATUSES = frozenset({StepStatus.PENDING, StepStatus.AWAITING_APPROVAL})


@dataclass(frozen=True, slots=True)
class BorrowedAct:
    """What a store writes onto a step it is satisfying (ADR-0259 §9).

    Both values are the **store's** and never the caller's: ``output`` is copied from
    the holder row the store has just verified, and ``finished_at`` is read from the
    store's own injected clock — "a value the caller never supplies cannot be
    mis-stated", which is what makes §2's reuse identity mechanical rather than
    advisory. The tracker receives this rather than reading its own clock, because the
    tracker's clock is injectable independently of the store's and §9 names the store's.

    Attributes:
        output: The holder's own ``output``.
        finished_at: The instant the satisfaction landed, from the store's clock.
    """

    output: FrozenJsonValue
    finished_at: datetime


@dataclass(frozen=True, slots=True)
class EffectHolder:
    """The row a goal already holds for one intended action, as a store reads it.

    Attributes:
        execution_id: The execution the row names.
        step_id: That execution's step.
        key: The key the row was taken under.
        status: The **stored** status of the step the row names, which is what §2's
            second limb is decided over.
        superseded: Whether a stored plan names the holder's plan in its
            ``supersedes``. **The store decides this itself**, from the holder's
            execution's plan and the plans it holds, inside the same indivisible step
            as the write; ``orchestration`` neither computes it nor asks for it.
    """

    execution_id: str
    step_id: str
    key: EffectKey
    status: StepStatus
    superseded: bool


@dataclass(frozen=True, slots=True)
class ClaimDecision:
    """What a store must answer and whether it must write (ADR-0259 §2).

    Attributes:
        outcome: The answer, carrying the holder on ``COMPLETED`` and on no other.
        writes: Whether the row is written — a first claim, or a re-point onto a dead
            holder, which **re-keys** it. Every other answer writes nothing, which is
            what leaves ``claimed_at`` and ``targets_revision`` exactly as they stand.
    """

    outcome: EffectOutcome
    writes: bool


def decide_claim(  # noqa: PLR0911 — one return per row of ADR-0259 §2's second limb, so the totality that clause claims is visible; collapsing them would hide it
    *, holder: EffectHolder | None, execution_id: str, step_id: str, effect_key: EffectKey
) -> ClaimDecision:
    """Answer one claim, totally, over ADR-0259 §2's three facts.

    Every one of :class:`~ai_assistant.core.types.StepStatus`'s seven members, crossed
    with whether the row's key equals this call's key and with whether the row names
    this step, has exactly one answer here, and no input is left undecided.

    The ``SUCCEEDED`` pair is the Sunday case: equal keys answer ``COMPLETED`` and
    unequal keys ``COMPLETED_OTHERWISE``, and **neither writes**. ``RUNNING`` and
    ``INDETERMINATE`` answer ``UNCERTAIN`` **whether or not the keys are equal**,
    because what is uncertain is whether this intended action was performed at all,
    and a differently-argued call under an action that may already have been performed
    is the one thing a modify-before-replace investigation must not be started from.

    Args:
        holder: The row the goal holds for this intended action, or ``None``.
        execution_id: The execution claiming.
        step_id: Its step.
        effect_key: The key of the authorised call about to be dispatched.

    Returns:
        The answer and whether the row must be written.
    """
    if holder is None:
        return ClaimDecision(outcome=EffectOutcome(claim=EffectClaim.CLAIMED), writes=True)

    same_key = holder.key == effect_key
    same_step = (holder.execution_id, holder.step_id) == (execution_id, step_id)

    if holder.status is StepStatus.SUCCEEDED:
        if same_key:
            return ClaimDecision(
                outcome=EffectOutcome(
                    claim=EffectClaim.COMPLETED,
                    execution_id=holder.execution_id,
                    step_id=holder.step_id,
                ),
                writes=False,
            )
        return ClaimDecision(
            outcome=EffectOutcome(claim=EffectClaim.COMPLETED_OTHERWISE), writes=False
        )

    if holder.status in _UNCERTAIN_STATUSES:
        return ClaimDecision(outcome=EffectOutcome(claim=EffectClaim.UNCERTAIN), writes=False)

    if holder.status is StepStatus.SKIPPED:
        return ClaimDecision(outcome=EffectOutcome(claim=EffectClaim.CLAIMED), writes=True)

    if holder.status is StepStatus.FAILED and holder.superseded:
        return ClaimDecision(outcome=EffectOutcome(claim=EffectClaim.CLAIMED), writes=True)

    # The three statuses under which the holder may still dispatch. Its own retry
    # re-claims its own key and nothing else does, so the exemption is stated over
    # `(execution_id, step_id)` **and** the key: a row whose key moved after its call
    # was constructed is ADR-0018's threat model rather than a fresh intent, and
    # re-keying to it would hand the mutated call the claim the authorised one holds.
    if same_step and same_key:
        return ClaimDecision(outcome=EffectOutcome(claim=EffectClaim.CLAIMED), writes=False)
    return ClaimDecision(outcome=EffectOutcome(claim=EffectClaim.HELD), writes=False)


def refuse_an_unscopable_claim(
    *, execution_id: str, step_id: str, known: bool, is_a_step: bool, intended_action: str | None
) -> str:
    """Refuse a claim whose row could not be scoped, and return the action it is.

    The three refusals are the store's because only there are they atomic, and each
    **writes nothing**: no row is written that :meth:`PlanStore.export`'s closure could
    not satisfy, and a later claim always finds a holder whose status it can read. The
    third is ADR-0265 §4's window closed at the store rather than trusted to close
    itself — every plan written before that decision carries ``None`` on every step, so
    a side-effecting step of such a plan stalls rather than dispatching, and **no lane
    invents an intended action for a stored plan** to lift the stall.

    Args:
        execution_id: The execution the claim names.
        step_id: The step it names.
        known: Whether an execution with that id is stored.
        is_a_step: Whether ``step_id`` names a step of **that** execution.
        intended_action: The stored step's ``intended_action``, or ``None``.

    Returns:
        The intended action the row is scoped to, once every refusal has passed.

    Raises:
        PlanningError: On any of the three.
    """
    if not known:
        msg = f"unknown execution {execution_id}"
        raise PlanningError(msg)
    if not is_a_step:
        msg = f"execution {execution_id} has no step {step_id}"
        raise PlanningError(msg)
    if intended_action is None:
        msg = (
            f"step {step_id} of execution {execution_id} names no intended action, so an "
            "effect claim has nothing to scope a row to (ADR-0259 §2, ADR-0265 §4)"
        )
        raise PlanningError(msg)
    return intended_action


def satisfaction_marks(
    *, step_id: str, named: str | None, borrowed_step: str | None
) -> tuple[str, str]:
    """The pair ADR-0259 §9's limbs are verified against, refusing a dissolved one.

    ``StepTransition``'s validator requires the trio whole and the store's guard reads
    ``satisfied_by_execution`` alone — but the transition stays the **caller's** object
    for as long as the call is queued, and ``frozen=True`` does nothing about
    ``__dict__`` (ADR-0018 §3). A caller that nulls ``satisfied_by_step`` after the call
    is queued therefore reaches the five limbs with half a pair, which is a shape the
    condition cannot be decided in at all. §9 fixes the answer for every such shape: the
    **non-stale** ``PlanningError`` ADR-0255 §3 fixes for its own conjuncts, because no
    re-read makes an absent mark present — and a refusal rather than an ``assert``,
    which ``python -O`` removes and which is not a value the contract states.

    Args:
        step_id: The step being satisfied.
        named: ``satisfied_by_execution``, as the store reads it.
        borrowed_step: ``satisfied_by_step``, as the store reads it.

    Returns:
        The pair, once both are known to be present.

    Raises:
        PlanningError: If either mark is absent.
    """
    if named is None or borrowed_step is None:
        msg = (
            f"step {step_id} names a satisfaction whose marks are not whole: "
            "satisfied_by_execution and satisfied_by_step are verified together, and a "
            "transition that lost one after the call was queued is refused rather than "
            "committed against half a pair"
        )
        raise PlanningError(msg)
    return named, borrowed_step


def refuse_an_unsatisfiable_borrowing(  # noqa: PLR0913 — one keyword per limb of §9's five-limbed condition; bundling them would mint a type whose only reader is this refusal
    *,
    step_id: str,
    same_goal: bool,
    borrowed_status: StepStatus | None,
    holder_names_it: bool,
    key_matches: bool,
    source_status: StepStatus,
) -> None:
    """Refuse a satisfaction that fails any limb of ADR-0259 §9's claim condition.

    Its five limbs, in order: the named execution is an execution of **this step's own
    goal**; the named step is a step **of that execution** and stands ``SUCCEEDED``;
    the goal's effect row for the target step's intended action **names that execution
    and step as its holder**; that row's ``key`` equals ``satisfied_by_key``; and the
    **stored source status is ``PENDING`` or ``AWAITING_APPROVAL``**. The fourth is
    what closes the same-action, different-arguments case the Sunday booking makes.

    It refuses on a :class:`~ai_assistant.core.errors.PlanningError` that is **not** a
    ``StaleExecutionError``, and for ADR-0255 §3's reason: no re-read makes one goal's
    execution another's, one key another, or a run that happened one that did not.

    Args:
        step_id: The step being satisfied.
        same_goal: Whether the named execution is stored **and** belongs to this
            step's own goal.
        borrowed_status: The named step's stored status, or ``None`` where the named
            execution does not carry that step at all.
        holder_names_it: Whether the goal's row for this step's intended action names
            the named execution and step as its holder.
        key_matches: Whether that row's key equals ``satisfied_by_key``.
        source_status: The stored status of the step being satisfied.

    Raises:
        PlanningError: On any of the five.
    """
    if not same_goal:
        msg = (
            f"step {step_id} names a borrowed execution this store does not hold, or "
            "one that belongs to another goal"
        )
        raise PlanningError(msg)
    if borrowed_status is None:
        msg = f"step {step_id} names a borrowed step that is not a step of that execution"
        raise PlanningError(msg)
    if borrowed_status is not StepStatus.SUCCEEDED:
        msg = (
            f"step {step_id} cannot be satisfied from a step standing {borrowed_status}: "
            "only a SUCCEEDED act has been performed"
        )
        raise PlanningError(msg)
    if not holder_names_it:
        msg = (
            f"step {step_id} names a borrowed act this goal's effect row does not hold: "
            "a satisfaction is verified against the row, never asserted by its caller"
        )
        raise PlanningError(msg)
    if not key_matches:
        msg = (
            f"step {step_id} names a satisfied_by_key that is not the effect row's key: "
            "the act was performed with different arguments (ADR-0259 §2)"
        )
        raise PlanningError(msg)
    if source_status not in _SATISFIABLE_STATUSES:
        msg = (
            f"step {step_id} stands {source_status}, so it has already run and cannot be "
            "satisfied by an effect its goal completed earlier"
        )
        raise PlanningError(msg)


def claiming_revision(plan: ActionPlan) -> int:
    """The revision ADR-0259 §9 records on a row the claiming ``plan`` takes.

    ``ActionPlan.targets_revision`` is ``None`` only on a plan ``save_plan`` would
    refuse, so a claiming plan always carries one and the field needs no absent case
    — but a store reads a value rather than asserting one, so the impossible shape is
    a refusal here rather than a ``None`` reaching a ``ge=1`` field.

    Args:
        plan: The plan the claiming execution runs.

    Returns:
        The revision it targets.

    Raises:
        PlanningError: If the plan names none.
    """
    if plan.targets_revision is None:  # pragma: no cover — save_plan refuses such a plan
        msg = f"plan {plan.id} targets no revision, so an effect claim has none to record"
        raise PlanningError(msg)
    return plan.targets_revision


def detached(record: EffectRecord) -> EffectRecord:
    """Rebuild ``record`` as a validated, **detached** :class:`EffectRecord`.

    ADR-0014 §5 has a ``PlanStore`` copy every record in and out, and pydantic passes an
    already-valid model instance through without copying — so a row built from a
    caller's :class:`~ai_assistant.core.types.EffectKey` holds **that object**, and
    ``object.__setattr__`` on it (or on a key reached through an exported row) would
    rewrite the identity ADR-0259 §2's at-most-once claim is decided over. ``frozen=True``
    refuses the assignment and does nothing about ``key.__dict__``, which ADR-0018 §3
    puts inside the threat model.

    A dump-and-revalidate rather than ``model_copy(deep=True)``, for
    :func:`~ai_assistant.planning.goals.revalidated_goal`'s reason: it is the snapshot
    *and* the guard against persisting a record whose validators a mutation has already
    been walked past. **Taken through the class rather than the instance**, for
    :func:`detached_key`'s reason: a ``model_dump`` entry in the instance's ``__dict__``
    shadows the method, and the same bypass that reaches the fields reaches the
    serializer that reads them.

    Args:
        record: The row to store or to hand out.

    Returns:
        A detached copy, nested key included.

    Raises:
        PlanningError: If the record does not survive its own validators.
    """
    try:
        return EffectRecord.model_validate(EffectRecord.model_dump(record))
    except ValidationError as exc:
        msg = f"effect row for goal {record.goal_id} is not a valid record: {exc}"
        raise PlanningError(msg) from exc


def detached_key(key: EffectKey) -> EffectKey:
    """Rebuild ``key`` as a validated, detached :class:`EffectKey`.

    **Taken at the entry of every** ``claim_effect``, before the row is looked up, so
    the **one** value the answer is decided by and the one persisted are the same
    snapshot. Pydantic passes an already-valid model instance through without copying,
    and ``frozen=True`` does nothing about ``key.__dict__`` — ADR-0018 §3's own bypass —
    so without this a key mutated *before* the call is both compared as the mutated
    value and written into the durable row, which is how a store comes to hold an
    ``EffectKey`` its own validators would refuse and to fail every later read of it.

    ADR-0021 §4's posture, one seam over: the construction-time check catches the honest
    mistake, and re-validating at the boundary is what holds against a deliberate one.

    **The dump is taken through the class and not through the instance**, which is the
    same bypass one level up: ``model_dump`` is a plain method, so an instance
    ``__dict__`` entry of that name shadows it, and ``key.model_dump()`` would then hand
    this function whatever the caller wanted validated — a *different* valid key, stored
    while the call the caller dispatched carries the original. ``EffectKey.model_dump``
    is looked up on the class, so no instance entry reaches it, and a subclass carrying
    extra state is refused by ``extra="forbid"`` rather than silently narrowed.

    Args:
        key: The key the caller handed in.

    Returns:
        A detached copy, compared and stored in place of the caller's.

    Raises:
        PlanningError: If the key does not survive its own validators, in which case
            **nothing is written** — a claim is refused rather than a malformed row
            persisted.
    """
    try:
        return EffectKey.model_validate(EffectKey.model_dump(key))
    except ValidationError as exc:
        msg = f"the effect key this claim was taken under is not a valid key: {exc}"
        raise PlanningError(msg) from exc
