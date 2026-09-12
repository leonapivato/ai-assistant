"""Resolve a planner's proposed understanding into a recorded revision (ADR-0249 §7).

**`orchestration` refuses a ground it cannot resolve**, and this module is where that
refusal lives. A :class:`~ai_assistant.core.types.ProposedUnderstanding` crosses the
planning seam carrying *labels* and *spans* — never a record identifier, in either
direction (ADR-0228 §8) — and what is recorded is a
:class:`~ai_assistant.core.types.GoalInterpretation` carrying the identifiers and spans
**this package** resolved them to.

Four rules carry the decision, and each is stated once here rather than at a call site.

- **Two kinds resolve and no others** (§7). A ``FROM_EVIDENCE`` ground's
  ``evidence_label`` resolves by ADR-0226 §3's labelling scheme, unchanged — the label
  of the record at 1-based index *n* of the ``memories`` sequence passed **on that
  call** — and the stamped ``evidence_id`` is the identifier of the record the loop
  itself labelled. A ``USER_STATED`` ground's ``span`` resolves by checking it is a span
  of the turn's own request. ``INFERRED`` takes no argument and needs no resolution.
- **A label naming a record that resolves in no store does not resolve here either**
  (§7). A search-minted record "is not a citation target and not a durable reference …
  its ``id`` is minted for one turn … and resolves in no store" (ADR-0231 §16), so a
  ``FROM_EVIDENCE`` element naming one is dropped exactly as an out-of-range label is:
  a durable record grounded on an identifier nothing can retrieve states a warrant it
  cannot show.
- **An element whose ground does not resolve is dropped, silently and without failing
  the turn** (§7), exactly as ADR-0226 §3 drops a label outside the shown set. **The
  outcome is not** — "an outcome whose ground does not resolve is recorded as
  ``INFERRED`` with neither argument rather than dropped, because a revision without an
  outcome is not a revision at all".
- **Retention copies forward whole and is not restatement** (§7). A ``retains`` value
  is a label of the :class:`~ai_assistant.core.types.GoalBrief` this call received; it
  resolves to that element of the **current** interpretation and is copied into the new
  revision with its ``text``, its ``ground``, its ``evidence_id`` and its ``span``
  exactly as the earlier revision recorded them. A retained *outcome* passes through no
  resolution at all — nothing crosses the seam to resolve, and the ground copied
  forward is one an earlier revision already resolved or §12 derived.

**The label scheme is derived here and never imported from `planning`.** ADR-0249 §9
fixes it — ``C`` then *n* over ``constraints``, ``S`` then *n* over ``criteria``,
``D`` then *n* over ``conditions``, 1-based and unpadded — and makes it "the same on
both sides of the seam", with "both sides deriving the label from the brief they hold
and neither consulting the other". That is ADR-0226 §3's own construction one sequence over, and it
is why :func:`~ai_assistant.orchestration.reads.resolve_label` writes its own three
lines rather than importing `planning`'s renderer: golden rule 1 forbids the import, and
no mapping, table or identifier crosses the two packages.

**The label space is per tuple** (§7, §9). A ``retains`` naming an element of a tuple
other than the one the retaining element sits in "resolves to nothing", so ``C1`` and
``S1`` are different elements and never the same one seen twice — which is exactly why
the letter is a parameter of the resolution rather than three near-identical bodies.

**Nothing here stamps a phase, a revision number, a ``raised_by`` or a ``recorded_at``
from a model's output.** Those are ``orchestration``'s under §6's writer clause, and a
:class:`~ai_assistant.core.types.ProposedUnderstanding` has no field one could arrive
on: the containment is a property of the type (L1), and this module then supplies each
from values the loop holds.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    GoalElement,
    GoalInterpretation,
    Ground,
    ProposedElement,
)
from ai_assistant.orchestration.reads import resolve_label

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from datetime import datetime

    from ai_assistant.core.types import (
        Goal,
        MemoryRecord,
        ProposedUnderstanding,
    )

__all__ = ["CONDITIONS_LETTER", "CONSTRAINTS_LETTER", "CRITERIA_LETTER", "recorded_revision"]

#: ADR-0249 §9's three label letters, one per tuple of the brief. They are the whole of
#: what keeps the three label spaces apart: a ``retains`` naming an element of another
#: tuple "resolves to nothing", so ``C1`` and ``S1`` are different elements.
CONSTRAINTS_LETTER: Final = "C"
CRITERIA_LETTER: Final = "S"
CONDITIONS_LETTER: Final = "D"

#: The label form, per letter: the letter followed by a 1-based decimal ordinal with no
#: padding. ``[0-9]`` and not a shorthand digit class, which is
#: :data:`~ai_assistant.orchestration.reads.resolve_label`'s own reason: the shorthand
#: admits every Unicode decimal digit, and a label the renderer could not have produced
#: is not a label this side resolves.
_ORDINAL: Final = re.compile(r"[1-9][0-9]*")


def _resolved_ordinal(label: str, letter: str, length: int) -> int | None:
    """Resolve one brief label to a 0-based index of its own tuple, or to nothing (§9).

    **Every way of being outside the shown set lands here alike**: a label of another
    tuple's letter, a string that does not match the form, an ordinal below 1, and an
    ordinal beyond the tuple's length. Each resolves to nothing, and the retaining
    element is then dropped — silently, exactly as ADR-0226 §3 drops an ``M`` label
    outside the shown set.

    Args:
        label: What the planner named. Model-supplied text, treated as a label and
            never as an identifier (ADR-0228 §8).
        letter: The letter of the tuple the retaining element sits in.
        length: How many elements that tuple of the **current** interpretation holds.

    Returns:
        The 0-based index, or ``None``.
    """
    if not label.startswith(letter) or _ORDINAL.fullmatch(label[len(letter) :]) is None:
        return None
    ordinal = int(label[len(letter) :])
    return None if ordinal > length else ordinal - 1


def _resolved_record(
    label: str | None, supply: Sequence[MemoryRecord], minted: Collection[str]
) -> str | None:
    """Resolve a ``FROM_EVIDENCE`` label to the id of a **durable** record (§7).

    ADR-0226 §3's scheme, unchanged: the label of the record at 1-based index *n* of the
    ``memories`` sequence passed **on that call**. Two populations resolve to nothing —
    a label outside the shown set, and a label naming a record this turn's own search
    minted, which ADR-0231 §16 rules "resolves in no store". Recording the second would
    state a warrant no later reader could reach, which is the refusal §7 takes in terms.

    Args:
        label: The ``M`` label the planner named, or ``None``.
        supply: The sequence the loop passed the planner on this call.
        minted: The ids of the records this turn's ``WEB_SEARCH`` servicings minted.

    Returns:
        The record's identifier, or ``None`` where nothing durable resolves.
    """
    if not label:
        return None
    record = resolve_label(label, supply)
    if record is None or record.id in minted:
        return None
    return record.id


def _resolved_span(span: str | None, utterance: str) -> str | None:
    """Resolve a ``USER_STATED`` span against the turn's own request (§7).

    "A ``USER_STATED`` element's ``span`` is resolved by checking it is a span of the
    turn's own request (``TurnResult.utterance``, ADR-0248 §1); the stamped
    ``GoalElement.span`` is that span." The check is buildable only because ADR-0248 put
    the request on the turn: before it there was no value on the turn to check a span
    against that was not itself the goal.

    **A blank span resolves to nothing**, and that is the same refusal rather than a
    second one. :data:`~ai_assistant.core.types.EncodableText` admits the empty string,
    which is a span of *every* request and warrants nothing at all — so a ground resting
    on one is a ground this module could not resolve to anything the user said, which is
    exactly what §7 drops.

    Args:
        span: What the planner quoted, or ``None``.
        utterance: This turn's own request, as ADR-0248 §1 carries it.

    Returns:
        The span, or ``None``.
    """
    if not span or span not in utterance:
        return None
    return span


def _resolved_element(  # noqa: PLR0913, PLR0911 — one parameter per thing a ground is resolved against, and one return per way a ground resolves or fails to; collapsing either would hide which rule decided
    proposed: ProposedElement,
    *,
    letter: str,
    current: Sequence[GoalElement],
    utterance: str,
    supply: Sequence[MemoryRecord],
    minted: Collection[str],
) -> GoalElement | None:
    """Resolve one proposed element, or drop it (§7).

    A **retaining** element names a label of this tuple and is copied **whole and
    unchanged** — "its ``text``, its ``ground``, its ``evidence_id`` and its ``span``
    exactly as the earlier revision recorded them". A **new** element carries its own
    ground and is resolved by the two rules above. Anything that resolves to nothing is
    dropped from the recorded revision, silently and without failing the turn.

    Args:
        proposed: What the planner returned for this position.
        letter: The label letter of the tuple this element sits in.
        current: That same tuple of the goal's **current** interpretation.
        utterance: This turn's own request.
        supply: The sequence the loop passed the planner on this call.
        minted: The ids of the records this turn's searches minted.

    Returns:
        The element to record, or ``None`` where it is dropped.
    """
    if proposed.retains is not None:
        index = _resolved_ordinal(proposed.retains, letter, len(current))
        return None if index is None else current[index]
    # A new element: `ProposedElement`'s validator refused every shape but the three a
    # ground admits, so both values below are present on anything that constructed.
    # The narrowing is what mypy needs and is not a second refusal.
    text, ground = proposed.text, proposed.ground
    if text is None or ground is None:  # pragma: no cover — the validator admits no such value
        return None
    if ground is Ground.FROM_EVIDENCE:
        evidence_id = _resolved_record(proposed.evidence_label, supply, minted)
        if evidence_id is None:
            return None
        return GoalElement(text=text, ground=ground, evidence_id=evidence_id)
    if ground is Ground.USER_STATED:
        span = _resolved_span(proposed.span, utterance)
        if span is None:
            return None
        return GoalElement(text=text, ground=ground, span=span)
    return GoalElement(text=text, ground=ground)


def _resolved_group(  # noqa: PLR0913 — the tuple, its letter, and the same values `_resolved_element` resolves against, threaded once per element
    proposed: Sequence[ProposedElement],
    *,
    letter: str,
    current: Sequence[GoalElement],
    utterance: str,
    supply: Sequence[MemoryRecord],
    minted: Collection[str],
) -> tuple[GoalElement, ...]:
    """Resolve one tuple of proposed elements, dropping what does not resolve (§7).

    **A revision states its elements in full, and omission is removal** (§7): an element
    of the current interpretation this sequence neither retains nor replaces is simply
    not in the result, because the result is built from what was proposed and from
    nothing else. There is no delete member and no partial-update shape.

    Args:
        proposed: The elements the planner stated for this tuple, in its own order.
        letter: This tuple's label letter.
        current: This tuple of the goal's current interpretation.
        utterance: This turn's own request.
        supply: The sequence the loop passed the planner on this call.
        minted: The ids of the records this turn's searches minted.

    Returns:
        The elements to record, in the order the planner stated them.
    """
    resolved = (
        _resolved_element(
            element,
            letter=letter,
            current=current,
            utterance=utterance,
            supply=supply,
            minted=minted,
        )
        for element in proposed
    )
    return tuple(element for element in resolved if element is not None)


def recorded_revision(  # noqa: PLR0913 — the goal, what the planner proposed, and one parameter per thing a ground is resolved against plus the two values §6 reserves to `orchestration`; every one is a distinct fact and a bundle would mint a type for an argument list
    goal: Goal,
    understanding: ProposedUnderstanding,
    *,
    utterance: str,
    supply: Sequence[MemoryRecord],
    minted: Collection[str] = (),
    recorded_at: datetime,
    raised_by: str,
) -> GoalInterpretation:
    """Resolve ``understanding`` into the revision that follows ``goal``'s current one.

    **The provenance is this package's and never the model's** (§6's writer clause).
    ``revision`` is minted one greater than the goal's current one, ``recorded_at`` and
    ``raised_by`` are the caller's — a planner envelope carries no field any of the
    three could arrive on, so a value a model wrote is discarded structurally rather
    than by a rule someone remembered.

    **The outcome is retained or restated, and is never dropped** (§7). On a retained
    outcome the current interpretation's ``outcome``, ``outcome_ground``,
    ``outcome_evidence_id`` and ``outcome_span`` are copied forward **byte for byte** —
    including a ``USER_STATED`` ground whose span is absent because ADR-0249 §12
    migrated the row it came from. On a restated one whose ground does not resolve, the
    outcome is recorded ``INFERRED`` with neither argument: "a revision without an
    outcome is not a revision at all".

    **Recording a revision does not move the attempt's phase** (§6). It advances the
    goal's ``version``, which is what §8's stale-target rule keys on, and leaves the
    attempt where it stood.

    Args:
        goal: The goal as the loop now holds it. Its **current** interpretation is what
            a ``retains`` label and a retained outcome resolve against.
        understanding: What the planner proposed on this call.
        utterance: This turn's own request, against which a ``USER_STATED`` span is
            checked (ADR-0248 §1).
        supply: The ``memories`` sequence passed the planner **on that call**, which is
            ADR-0226 §3's label space — and ADR-0228 §8 binds that clause per call, so
            the same label may name different records on a turn's two calls.
        minted: The ids of the records this turn's ``WEB_SEARCH`` servicings minted,
            which resolve in no store (ADR-0231 §16). Empty on a turn that searched
            nothing, which is every turn on a deployment with no search wired.
        recorded_at: This turn's instant.
        raised_by: The turn whose message caused this revision. Required and
            undefaulted: §1 forbids writing ``None`` into it on a value
            ``orchestration`` authors, and a default would let a call site forget it.

    Returns:
        The revision to append. It is not appended here: what a caller does with it —
        an in-memory append on a goal this turn opened, a ``record_interpretation``
        under §12's compare-and-swap on one the store already holds — is the caller's,
        and this function holds only the resolution.
    """
    current = goal.interpretation[-1]
    if understanding.retains_outcome:
        outcome, ground = current.outcome, current.outcome_ground
        evidence_id, span = current.outcome_evidence_id, current.outcome_span
    else:
        # `ProposedUnderstanding`'s validator admits only a fully stated outcome on
        # this branch, so both values are present; the narrowing is mypy's and is not a
        # second refusal.
        stated, declared = understanding.outcome, understanding.outcome_ground
        if (
            stated is None or declared is None
        ):  # pragma: no cover — the validator admits no such value
            stated, declared = current.outcome, Ground.INFERRED
        outcome, ground = stated, declared
        evidence_id = _resolved_record(understanding.outcome_evidence_label, supply, minted)
        span = _resolved_span(understanding.outcome_span, utterance)
        unresolved = (ground is Ground.FROM_EVIDENCE and evidence_id is None) or (
            ground is Ground.USER_STATED and span is None
        )
        if unresolved:
            # §7: recorded `INFERRED` with neither argument rather than dropped.
            ground, evidence_id, span = Ground.INFERRED, None, None
    groups = (
        (CONSTRAINTS_LETTER, understanding.constraints, current.constraints),
        (CRITERIA_LETTER, understanding.criteria, current.criteria),
        (CONDITIONS_LETTER, understanding.conditions, current.conditions),
    )
    resolved = tuple(
        _resolved_group(
            proposed,
            letter=letter,
            current=held,
            utterance=utterance,
            supply=supply,
            minted=minted,
        )
        for letter, proposed, held in groups
    )
    return GoalInterpretation(
        revision=current.revision + 1,
        outcome=outcome,
        outcome_ground=ground,
        outcome_evidence_id=evidence_id,
        outcome_span=span,
        constraints=resolved[0],
        criteria=resolved[1],
        conditions=resolved[2],
        recorded_at=recorded_at,
        raised_by=raised_by,
    )
