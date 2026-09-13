"""Applying ADR-0249 §12's two commands to a stored record.

The goal half of what :mod:`ai_assistant.planning.execution` is for steps: one
statement of what appending an interpretation revision, committing an attempt
transition, settling a question and marking an evidence row *do*, so the two conforming
``PlanStore`` implementations in this package cannot drift on it. ADR-0049's own note
for the transition graph is the precedent —
"the ADR-0014 §4 transition graph is authoritative in exactly one place and the two
stores cannot drift on it" — applied to the two writes ADR-0249 §12 adds.

The canonical fake in :mod:`ai_assistant.testing.planning` deliberately does **not**
import this module, for the reason that module states: a consumer's tests would then
pull in the very subsystem the fake stands in for. The shared conformance suite is
what holds the two statements honest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import IllegalTransitionError, PlanningError
from ai_assistant.core.types import (
    MAX_ASSOCIATION_CANDIDATES,
    MAX_GOAL_INTERPRETATIONS,
    TERMINAL_ATTEMPT_STATES,
    AttemptPhase,
    EvidenceStanding,
    Goal,
    GoalAttempt,
    GoalCandidates,
    GoalEvidence,
    GoalQuestion,
    GoalQuestionDisposition,
    GoalRevision,
    Identifier,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ai_assistant.core.types import (
        AttemptTransition,
        GoalInterpretation,
        GoalStatus,
        UtcInstant,
    )

#: ADR-0249 §6's order, read off the declaration rather than restated: "within one
#: attempt, ``phase`` advances in that order and never moves backwards".
_PHASE_ORDER: Final[dict[AttemptPhase, int]] = {
    phase: index for index, phase in enumerate(AttemptPhase)
}


def bounded(goal: Goal) -> Goal:
    """Hold ``goal``'s history to ADR-0249 §2's bound, disclosing what it drops.

    §2 states the bound over **the write**, not over one member: "a goal whose sequence
    would exceed it drops its **oldest** element on the write that would exceed it, and
    the **current** interpretation is never dropped". So both writes take it —
    :meth:`PlanStore.save_goal`, which is the opening write, and
    :meth:`PlanStore.record_interpretation`, which is every later one — and a store
    that applied it to only the second would accept an oversized history at the door
    and enforce the bound on nothing.

    **The elision is disclosed and never silent**, on ADR-0086 §4's own ground: a goal
    reporting fewer revisions than happened "answers the question *when did the
    system's understanding change, and why* falsely". A write that drops *k* elements
    advances ``interpretation_elided`` by *k*.

    Args:
        goal: The goal as it would be written.

    Returns:
        The goal itself where the bound is not exceeded — a copy that changes no field
        is a copy for nothing — and a trimmed one where it is.
    """
    dropped = max(0, len(goal.interpretation) - MAX_GOAL_INTERPRETATIONS)
    if not dropped:
        return goal
    return goal.model_copy(
        update={
            "interpretation": goal.interpretation[dropped:],
            "interpretation_elided": goal.interpretation_elided + dropped,
        }
    )


def appended(goal: Goal, interpretation: GoalInterpretation) -> Goal:
    """Append one revision to ``goal``, eliding the oldest if it must (§1, §2).

    The revision must be **one greater** than the goal's current one (§1), the
    **current** interpretation is never dropped (§2), and a write that drops *k*
    elements advances ``interpretation_elided`` by *k* — silent truncation is not
    available, on ADR-0086 §4's own ground. ``version`` advances by one because this
    is a mutation of the goal (§1).

    Args:
        goal: The goal as stored.
        interpretation: The revision to append.

    Returns:
        The goal as it stands after the append.

    Raises:
        PlanningError: If the revision does not follow the goal's current one.
    """
    current = goal.interpretation[-1]
    if interpretation.revision != current.revision + 1:
        msg = (
            f"goal {goal.id} is at revision {current.revision}, so the next revision is "
            f"{current.revision + 1} and not {interpretation.revision}: a goal's "
            f"interpretation is append-only and each revision is one greater than the "
            f"one before it (ADR-0249 §1)"
        )
        raise PlanningError(msg)
    return bounded(
        goal.model_copy(
            update={
                "interpretation": (*goal.interpretation, interpretation),
                "version": goal.version + 1,
            }
        )
    )


def _revalidated(goal: Goal, *, what: str) -> Goal:
    """Re-run ``Goal``'s validators over a goal built by ``model_copy`` (ADR-0023 §2).

    That section is explicit about why this exists: "``model_copy(update=...)`` skips
    validators (a pydantic property no type can close), so the invariant holds *at the
    validation boundary*, and **a write that reaches past it must re-validate**. That
    mechanism already exists — ``planning/execution.py:72`` re-validates after
    ``model_copy`` for exactly this reason."

    It is load-bearing for both of this module's stamps and not merely tidy. A naive
    or unconvertible ``at`` reaching :func:`engaged` would otherwise be **committed**,
    and a SQLite store would then fail to decode its own row on the next
    ``get_goal`` — a record the type is supposed to make impossible, persisted, with
    the fault surfacing at a reader that did nothing wrong.

    Args:
        goal: The goal as ``model_copy`` built it.
        what: What the caller was doing, for the refusal message.

    Returns:
        The goal, validated.

    Raises:
        PlanningError: If the rebuilt goal is not one ``Goal`` admits.
    """
    try:
        return Goal.model_validate(goal.model_dump())
    except ValidationError as exc:
        msg = f"{what} would leave goal {goal.id} in a shape Goal refuses: {exc}"
        raise PlanningError(msg) from exc


def engaged(goal: Goal, *, at: UtcInstant, conversation_id: str) -> Goal:
    """Stamp ``goal``'s engagement and advance its version (ADR-0250 §1, §9).

    The **one** place either engagement field is written, so the two conforming stores
    in this package cannot drift on §1's "exactly one writer" clause. It writes
    **nothing else**: not the status, not the interpretation, not the attempt — and
    :attr:`Goal.conversation_id` is **never rewritten**, because that stays the
    conversation the goal was opened in (ADR-0249 §1's provenance clause).

    **The result is revalidated** (ADR-0023 §2, :func:`_revalidated`), because both
    values a caller supplies here reach past ``model_copy``'s validators: ``at`` is a
    :data:`~ai_assistant.core.types.UtcInstant` and ``conversation_id`` an
    :data:`~ai_assistant.core.types.Identifier`, and neither is checked by the
    annotation alone in process.

    Args:
        goal: The goal as stored.
        at: The engagement instant.
        conversation_id: The conversation the engaging turn ran under.

    Returns:
        The goal as it stands after the stamp, with ``at`` normalised to UTC.

    Raises:
        PlanningError: If ``at`` is not a conforming instant, or ``conversation_id``
            is blank or has no UTF-8 encoding.
    """
    return _revalidated(
        goal.model_copy(
            update={
                "last_engaged_at": at,
                "last_engaged_in": conversation_id,
                "version": goal.version + 1,
            }
        ),
        what="the engagement stamp",
    )


def with_status(goal: Goal, *, status: GoalStatus) -> Goal:
    """Move ``goal``'s status and advance its version (ADR-0250 §9).

    The goal's **only** status-mutation route, stated once for both stores. It writes
    **nothing else**: not the engagement stamp, not the interpretation, not the
    attempt. **No member of the vocabulary is refused here**, because A10 and A3 write
    ``ACHIEVED`` and ``BLOCKED`` through this same route and "a store that refused a
    member would be a second place the vocabulary is decided" — which act may write
    which member is the caller's rule.

    Revalidated for :func:`engaged`'s reason. The status is a closed enumeration and a
    caller reaching past the annotation with something else is the shape this catches.

    Args:
        goal: The goal as stored.
        status: The status to write.

    Returns:
        The goal as it stands after the move.

    Raises:
        PlanningError: If ``status`` is not a :class:`GoalStatus`.
    """
    return _revalidated(
        goal.model_copy(update={"status": status, "version": goal.version + 1}),
        what="the status move",
    )


def capped(goals: Iterable[Goal], *, limit: int) -> GoalCandidates:
    """Order a candidate set by ADR-0250 §1's key and hold it to ``limit`` (§2).

    The order is ``last_engaged_at`` **descending** with the ``goal_id`` **ascending**
    as the tie-break, and a goal carrying **no** instant sorts **after** every goal
    that carries one. ADR-0074 §2's reason binds: "some total order must be named or
    two implementations answer the same page differently", and two goals engaged in
    the same instant is reachable because a migrated pair carries no instant at all.

    **The absent instant sorts last rather than first, and that is the conservative
    direction**: sorting it first would make the oldest, least-touched objective in
    the store the focused goal of every conversation that holds one.

    Args:
        goals: The whole membership of the set, in any order.
        limit: The most candidates to return, held down to
            :data:`~ai_assistant.core.types.MAX_ASSOCIATION_CANDIDATES` where a caller
            asks for more — §2 fixes that ceiling and no caller raises it.

    Returns:
        The capped set, with ``elided`` counting what the truncation dropped.

    Raises:
        PlanningError: If ``limit`` is not positive.
    """
    if limit < 1:
        msg = f"a candidate set is read with a positive limit and not {limit} (ADR-0250 §9)"
        raise PlanningError(msg)
    # §2 fixes the ceiling at `MAX_ASSOCIATION_CANDIDATES` and the type enforces it, so
    # a caller asking for more gets the cap rather than a raw `ValidationError` out of
    # the store: "truncated to MAX_ASSOCIATION_CANDIDATES, and carrying the count of
    # goals the truncation dropped". `elided` is then counted against what was actually
    # returned, so it stays the true remainder whichever bound applied.
    taken = min(limit, MAX_ASSOCIATION_CANDIDATES)
    held = list(goals)
    # **Ordered by comparing the instants themselves, never a float of them.**
    # `datetime.timestamp()` is a float of seconds, and two instants a microsecond
    # apart compare *equal* as floats from about 2262 onward — which would hand the
    # `goal_id` tie-break a pair §1 does not tie, and §1 states that tie-break for
    # equal instants alone. Two passes over a stable sort rather than one composite
    # key, because the instant descends while the id ascends and no single key
    # expresses both without arithmetic on a datetime.
    carrying = [(goal.last_engaged_at, goal) for goal in held if goal.last_engaged_at is not None]
    carrying.sort(key=lambda pair: pair[1].id)
    carrying.sort(key=lambda pair: pair[0], reverse=True)
    absent = sorted((goal for goal in held if goal.last_engaged_at is None), key=lambda one: one.id)
    ordered = [goal for _, goal in carrying] + absent
    return GoalCandidates(goals=tuple(ordered[:taken]), elided=max(0, len(ordered) - taken))


def settled(
    question: GoalQuestion, *, disposition: GoalQuestionDisposition, at: UtcInstant
) -> GoalQuestion:
    """Settle ``question``, clearing its content in the same step (ADR-0250 §8).

    "A settled question keeps its facts and loses its content": ``text`` and ``about``
    are cleared **in the same step that moves the disposition**, and no implementation
    retains a copy, a digest, a snapshot or an archive of either. ``goal_id`` and
    ``attempt_id`` survive, so a late answer still reaches the goal (§11).

    Args:
        question: The open question as stored.
        disposition: The terminal member to write.
        at: The settlement instant.

    Returns:
        The question as it stands after the settlement.

    Raises:
        PlanningError: If ``disposition`` is ``OPEN``, which settles nothing.
    """
    if disposition is GoalQuestionDisposition.OPEN:
        msg = (
            "settle_question moves an OPEN question to a terminal member: OPEN settles "
            "nothing and no disposition is inferred from silence (ADR-0250 §9, §12)"
        )
        raise PlanningError(msg)
    settled_question = question.model_copy(
        update={"disposition": disposition, "settled_at": at, "text": None, "about": None}
    )
    try:
        return GoalQuestion.model_validate(settled_question.model_dump())
    except ValidationError as exc:
        # ADR-0023 §2: `model_copy(update=...)` skips validators, so `at` reaches past
        # them. A naive settlement instant committed here would be a question the store
        # could write and then fail to decode — see `_revalidated` above, whose
        # reasoning this is, over the other record this module stamps.
        msg = f"the settlement would leave question {question.id} in a shape it refuses: {exc}"
        raise PlanningError(msg) from exc


def revalidated_revision(revision: GoalRevision) -> GoalRevision:
    """Rebuild ``revision`` as a validated, detached :class:`GoalRevision`, or refuse it.

    **A snapshot is not enough here, and that is the whole reason this exists.**
    ``tuple(revision.invalidates)`` reads the field once, which closes the one-shot
    iterator hole — but the field is annotated ``tuple[Identifier, ...]`` and
    ``model_copy(update=...)`` **skips validators** (ADR-0023 §2: "a pydantic property no
    type can close"), so a caller can also put a **string** there. ``tuple("ev1")`` is
    ``("e", "v", "1")``: three ids that are not the one the caller named, and where those
    happen to exist the store would mark them and leave ``ev1`` standing — a revision
    that invalidated the wrong rows and reported nothing.

    Revalidating turns every such shape into a ``PlanningError`` at the write, before
    anything is appended, which is §2's "a write that reaches past it must re-validate"
    read over the command rather than over the record. The validated value's
    ``invalidates`` is a real tuple, so the caller's container is no longer read at all.

    Args:
        revision: The command as the caller handed it in.

    Returns:
        The command, revalidated and detached.

    Raises:
        PlanningError: If it does not satisfy its own model.
    """
    try:
        return GoalRevision.model_validate(revision.model_dump())
    except ValidationError as exc:
        subject = getattr(revision, "goal_id", "<no goal>")
        msg = f"the revision for goal {subject!r} is not a valid command: {exc}"
        raise PlanningError(msg) from exc


def revalidated_evidence(row: GoalEvidence) -> GoalEvidence:
    """Rebuild ``row`` as a validated, detached :class:`GoalEvidence`, or refuse it.

    **The one place a caller-supplied evidence row is checked before a store keeps it**,
    so the conforming implementations cannot disagree about which rows
    :meth:`~ai_assistant.core.protocols.PlanStore.record_evidence` admits. ADR-0023 §2
    is the ground and its words are the reason: "``model_copy(update=...)`` skips
    validators (a pydantic property no type can close), so the invariant holds *at the
    validation boundary*, and **a write that reaches past it must re-validate**" — and a
    caller holding a stored row can reach past them, so a row copied to ``SUPERSEDED``
    with no ``superseded_by`` arrives here as a value ADR-0252 §1's fourth axis says is
    not constructible.

    That matters more for this record than for the four the stores already take as
    given, because §1's fourth axis is the whole of what makes ADR-0252's correction 1
    auditable: "retained historical disagreements do not permanently block progress" is
    only checkable if **every retirement names what did it**. A half-marked row admitted
    here would be one the history could never explain.

    Rebuilt as ``GoalEvidence`` specifically, so a subclass's extra fields are refused by
    ``extra="forbid"`` rather than silently dropped — :func:`_revalidated`'s own move.

    Args:
        row: The row as the caller handed it in.

    Returns:
        The row, revalidated and detached.

    Raises:
        PlanningError: If it does not satisfy its own model.
    """
    try:
        return GoalEvidence.model_validate(row.model_dump())
    except ValidationError as exc:
        # getattr, not row.id: a `model_construct`'d instance may carry no id at all,
        # and reading one while composing the message would leak an `AttributeError`
        # past this helper's `PlanningError` boundary (`_revalidated_goal`'s lesson).
        subject = getattr(row, "id", "<no id>")
        msg = f"evidence row {subject!r} is not a valid record and will not be stored: {exc}"
        raise PlanningError(msg) from exc


#: The shape a caller's set of row ids has to have before a store acts on it. Declared
#: once, beside :func:`revalidated_row_ids`, so the element rule is ``Identifier``'s own
#: rather than a second spelling of it.
_ROW_IDS: Final[TypeAdapter[tuple[Identifier, ...]]] = TypeAdapter(tuple[Identifier, ...])


def revalidated_row_ids(named: Sequence[str], *, what: str) -> tuple[Identifier, ...]:
    """Snapshot a caller's set of evidence row ids as a validated tuple, or refuse it.

    The ``supersedes`` counterpart of :func:`revalidated_revision`'s work on
    ``GoalRevision.invalidates``, and it exists for the identical reason, one level out:
    a **parameter** annotated ``Sequence[str]`` has no validator at all, so nothing
    between the caller and the store checks what arrived.

    **A bare string is the case that forces this.** ``str`` satisfies
    ``Sequence[str]``, and ``tuple("ev1")`` is ``("e", "v", "1")`` — three ids the
    caller never named. Where rows ``e``, ``v`` and ``1`` happen to be standing under
    the same goal, a store would irreversibly supersede all three and leave ``ev1``
    itself **standing**, reporting nothing: ADR-0252 §12 obliges a store to mark the
    rows the caller named, and marking three others while answering success is the
    failure mode §1's fourth axis exists to make impossible. ``bytes`` is refused beside
    it, for the same reason in another spelling.

    Snapshotting is the other half, and it is ``core.protocols``' second standing
    obligation (ADR-0065 §1): "a ``Sequence`` argument is a container the caller may
    still be holding". Taking the tuple **once**, on the coroutine's first executed
    line, is what stops a one-shot iterator being drained by the refusal pass and found
    empty by the marking pass, and what stops a caller appending to a list while the
    write is in flight.

    Args:
        named: The ids as the caller handed them in.
        what: What the ids are for, as the tail of "the ids to {what}" in the message.

    Returns:
        The ids, validated and detached, in the order given.

    Raises:
        PlanningError: If the argument is not a container of identifiers.
    """
    if isinstance(named, str | bytes):
        msg = (
            f"the ids to {what} were given as {named!r}, a single string rather than a "
            f"container of ids: its characters are not the ids you named (ADR-0252 §12)"
        )
        raise PlanningError(msg)
    try:
        return _ROW_IDS.validate_python(named)
    except ValidationError as exc:
        msg = f"the ids to {what} are not a container of identifiers: {exc}"
        raise PlanningError(msg) from exc


def superseded(row: GoalEvidence, *, by: str) -> GoalEvidence:
    """``row`` marked ``SUPERSEDED``, naming the row that displaced it (ADR-0252 §8).

    "A row that refreshes an earlier row supersedes it: the earlier row's ``standing``
    becomes ``SUPERSEDED`` and its ``superseded_by`` names ``L``" — and **the mark and
    its argument travel together or the value does not construct** (§1), so the two are
    written in one ``model_copy`` and revalidated together.

    **Supersession never un-marks** (§8): a row that is ``SUPERSEDED`` is never returned
    to ``STANDING``, by a later revision, by a later refresh, by the deletion of the row
    that displaced it, or by any other route. ADR-0252 §12's three refusals — the row is
    not this goal's, is not ``STANDING``, or is the row being written — are the
    **store's** and run before this. **Which** rows a new row refreshes is
    ``orchestration``'s six-limb test and neither this function's nor the store's.

    Args:
        row: The ``STANDING`` row being displaced.
        by: The id of the row that refreshed it.

    Returns:
        The row as it stands after the mark.

    Raises:
        PlanningError: If the marked row is not a shape ``GoalEvidence`` admits.
    """
    return _marked(row, {"standing": EvidenceStanding.SUPERSEDED, "superseded_by": by})


def invalidated(row: GoalEvidence, *, at_revision: int) -> GoalEvidence:
    """``row`` marked ``INAPPLICABLE`` against a revision (ADR-0252 §9).

    **Invalidation is a marking and never a deletion**: the row is kept with its
    applicabilities, its instants, its verdict and its references intact, it is still
    exported, still reachable through ``get_evidence`` and ``evidence_of``, and still in
    the digest the planner sees. **What changes is exactly one field**, plus the
    argument that field's mark travels with.

    **Invalidation never un-marks** (§9): a later revision that restores the old
    requirement does not return the row to ``STANDING`` — it is read again or it is not
    used — because un-marking would make a goal's evidence state depend on the **order**
    of its revisions rather than on what is known. **Which** rows a revision invalidates
    is ``orchestration``'s predicate, keyed on ``supported`` and never on ``requested``.

    Args:
        row: The ``STANDING`` row the revision no longer covers.
        at_revision: The revision being appended, which did it.

    Returns:
        The row as it stands after the mark.

    Raises:
        PlanningError: If the marked row is not a shape ``GoalEvidence`` admits.
    """
    return _marked(
        row,
        {
            "standing": EvidenceStanding.INAPPLICABLE,
            "inapplicable_at_revision": at_revision,
        },
    )


def _marked(row: GoalEvidence, mark: dict[str, object]) -> GoalEvidence:
    """Apply one mark to ``row`` and revalidate it (ADR-0023 §2).

    Stated once for both marks, for :func:`_revalidated`'s reason in that section's own
    words: "``model_copy(update=...)`` skips validators (a pydantic property no type can
    close), so the invariant holds *at the validation boundary*, and **a write that
    reaches past it must re-validate**". What it re-validates here is ADR-0252 §1's
    fourth axis — that a row's standing and the argument beside it agree — over a value
    no constructor built.

    Args:
        row: The row being marked.
        mark: The standing and its one argument.

    Returns:
        The marked row.

    Raises:
        PlanningError: If the result is not a shape ``GoalEvidence`` admits.
    """
    try:
        return GoalEvidence.model_validate(row.model_copy(update=mark).model_dump())
    except ValidationError as exc:
        msg = f"the mark would leave evidence row {row.id} in a shape it refuses: {exc}"
        raise PlanningError(msg) from exc


def advanced(attempt: GoalAttempt, transition: AttemptTransition) -> GoalAttempt:
    """Apply one transition to ``attempt`` and return the result (§5, §6, §12).

    Every absent member leaves its field unchanged; an ``add_*`` member appends its
    identifier, and one the tuple already holds is **ignored** rather than duplicated
    or refused. The phase never moves backwards, no transition leaves a terminal
    state, and neither effort counter is ever reduced.

    Args:
        attempt: The attempt as stored.
        transition: The command to apply.

    Returns:
        The attempt as it stands after the transition.

    Raises:
        IllegalTransitionError: If the move would take the phase backwards or move a
            terminal attempt to another state.
        PlanningError: If an effort counter would be reduced, or the result is not a
            shape ADR-0249 §5 admits.
    """
    state = attempt.state if transition.to_state is None else transition.to_state
    if attempt.state in TERMINAL_ATTEMPT_STATES and state is not attempt.state:
        msg = (
            f"attempt {attempt.id} is {attempt.state.value} and no transition leaves a "
            f"terminal member (ADR-0249 §5)"
        )
        raise IllegalTransitionError(msg)
    phase = attempt.phase if transition.to_phase is None else transition.to_phase
    if _PHASE_ORDER[phase] < _PHASE_ORDER[attempt.phase]:
        msg = (
            f"attempt {attempt.id} stands at {attempt.phase.value} and a phase advances "
            f"in ADR-0249 §6's order and never moves backwards: {phase.value} is earlier"
        )
        raise IllegalTransitionError(msg)
    effort = attempt.effort
    if transition.planner_calls is not None or transition.working is not None:
        calls = (
            effort.planner_calls if transition.planner_calls is None else transition.planner_calls
        )
        working = effort.working if transition.working is None else transition.working
        if calls < effort.planner_calls or working < effort.working:
            msg = (
                f"attempt {attempt.id}'s effort is monotonically non-decreasing and no "
                f"implementation subtracts from it (ADR-0249 §5)"
            )
            raise PlanningError(msg)
        effort = effort.model_copy(update={"planner_calls": calls, "working": working})
    try:
        return GoalAttempt(
            id=attempt.id,
            goal_id=attempt.goal_id,
            opened_at=attempt.opened_at,
            phase=phase,
            state=state,
            outcome=attempt.outcome if transition.outcome is None else transition.outcome,
            effort=effort,
            plan_ids=_appended_id(attempt.plan_ids, transition.add_plan_id),
            execution_ids=_appended_id(attempt.execution_ids, transition.add_execution_id),
            authorization_ids=_appended_id(
                attempt.authorization_ids, transition.add_authorization_id
            ),
            ended_at=attempt.ended_at if transition.ended_at is None else transition.ended_at,
            version=attempt.version + 1,
        )
    except ValidationError as exc:
        msg = (
            f"the transition would leave attempt {attempt.id} in a shape ADR-0249 §5 refuses: {exc}"
        )
        raise PlanningError(msg) from exc


def _appended_id(held: tuple[str, ...], addition: str | None) -> tuple[str, ...]:
    """Append ``addition`` unless the tuple already holds it (ADR-0249 §12).

    Args:
        held: The identifiers already on the attempt, in order.
        addition: The identifier to append, or ``None``.

    Returns:
        The tuple with ``addition`` at its end, or unchanged where it was absent or
        already held — "an identifier the tuple already holds is ignored rather than
        duplicated or refused".
    """
    if addition is None or addition in held:
        return held
    return (*held, addition)
