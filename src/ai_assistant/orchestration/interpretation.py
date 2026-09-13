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

**ADR-0253 adds two acts to this module, and both are the same act this module already
performed.** §7 gives a :class:`~ai_assistant.core.types.GoalElement` an ``id`` and an
``applicability``, and ``orchestration`` *"mints the id, once, at the instant the element
is first recorded"* — which is here, one line from where its ground is resolved, so that
the two members §7 stamps together are stamped together. §9 then has the loop take each
:attr:`~ai_assistant.core.types.StepCondition.about` and each
:attr:`~ai_assistant.core.types.PlanInterpretation.settles` *"for its own"* and replace
the **condition label** it came back carrying with the id that label resolves to
(:func:`substituted_plan`). It is the same resolution the paragraphs above describe, over
a fourth value: a planner names a position in a sequence it was rendered or returned, and
this package supplies the name of the thing named. No identifier crosses the seam in
either direction, in either act.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    MAX_APPLICABILITY_VALUES,
    EvidenceApplicability,
    GoalElement,
    GoalInterpretation,
    Ground,
    ProposedElement,
)
from ai_assistant.orchestration.reads import resolve_label

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping, Sequence
    from datetime import datetime

    from ai_assistant.core.types import (
        ActionPlan,
        Goal,
        GoalEvidence,
        MemoryRecord,
        PlanInterpretation,
        PlanStep,
        ProposedUnderstanding,
    )

__all__ = [
    "CONDITIONS_LETTER",
    "CONSTRAINTS_LETTER",
    "CRITERIA_LETTER",
    "EVIDENCE_LETTER",
    "RecordedUnderstanding",
    "recorded_revision",
    "resolved_evidence_row",
    "resolved_ordinal",
    "substituted_plan",
]

#: ADR-0249 §9's three label letters, one per tuple of the brief. They are the whole of
#: what keeps the three label spaces apart: a ``retains`` naming an element of another
#: tuple "resolves to nothing", so ``C1`` and ``S1`` are different elements.
CONSTRAINTS_LETTER: Final = "C"
CRITERIA_LETTER: Final = "S"
CONDITIONS_LETTER: Final = "D"

#: ADR-0252 §10's fourth label space, over the ``evidence`` sequence ADR-0249 §7 put on
#: the same seam: "the label of the digest at 1-based index *n* of ``Planner.plan``'s
#: ``evidence`` sequence is the ASCII string ``E`` followed by *n* in decimal with no
#: padding".
#:
#: **The prefix rather than a second field, because the label space is already per
#: sequence and the planner already knows which one it read** (§10). A
#: ``ProposedElement.evidence_label`` carries either an ``M`` label or an ``E`` label
#: and **gains no field**: a second field would let a planner emit both and the loop
#: choose, which is the "two carriers for one fact" defect, where the prefix makes the
#: two spaces mutually exclusive at the value.
#:
#: It sits here, beside the three ADR-0249 §9 added, because this is where a label is
#: parsed: :func:`resolved_ordinal` is the one parser for all four, and "a second parser
#: for one rule is a second place to get the padding, the digit class and the bound
#: wrong".
EVIDENCE_LETTER: Final = "E"

#: The label form, per letter: the letter followed by a 1-based decimal ordinal with no
#: padding, **bounded in width** — the same form
#: :data:`~ai_assistant.orchestration.reads.resolve_label` matches an ``M`` label by, one
#: sequence over. The bound is what keeps an unresolvable label from *failing* the turn:
#: a model-supplied string is bounded by nothing, ``int()`` refuses one past CPython's
#: own digit limit with a ``ValueError``, and §7 has every label outside the shown set
#: "dropped … silently and without failing the turn". No brief has 10**9 elements, so
#: nothing resolvable is refused by it.
#:
#: ``[0-9]`` and not a shorthand digit class, which is
#: :data:`~ai_assistant.orchestration.reads.resolve_label`'s own reason: the shorthand
#: admits every Unicode decimal digit, and a label the renderer could not have produced
#: is not a label this side resolves.
_ORDINAL: Final = re.compile(r"[1-9][0-9]{0,8}")


def resolved_ordinal(label: str, letter: str, length: int) -> int | None:
    """Resolve one brief label to a 0-based index of its own tuple, or to nothing (§9).

    **Every way of being outside the shown set lands here alike**: a label of another
    tuple's letter, a string that does not match the form — a **zero-padded** ordinal
    included, which :data:`_ORDINAL`'s leading ``[1-9]`` refuses because ADR-0249 §9
    spells the scheme as the letter "followed by *n* in decimal with **no padding**" —
    an ordinal below 1, an ordinal beyond the tuple's length, and an ordinal of more
    digits than any shown set could have. Each resolves to nothing, and the retaining
    element is then dropped —
    silently, exactly as ADR-0226 §3 drops an ``M`` label outside the shown set. **None
    of them fails the turn**, which is why the last is tested before the conversion
    rather than after it: a model-supplied string is not bounded by anything, and
    ``int()`` refuses one past CPython's digit limit.

    **It is public because ADR-0250 §3 and §7 spell the same scheme over two more
    sequences** — a candidacy's ``G`` labels and a proposal's own ``C``/``S``/``D``
    labels — and a second parser for one rule is a second place to get the padding, the
    digit class and the bound wrong. One function, one refusal, three call sites.

    Args:
        label: What the planner or the associator named. Model-supplied text, treated as
            a label and never as an identifier (ADR-0228 §8).
        letter: The letter of the sequence the label is read over.
        length: How many elements that sequence holds.

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


def resolved_evidence_row(label: str | None, evidence: Sequence[GoalEvidence]) -> str | None:
    """Resolve an ``E`` label to the id of the row it names, or to nothing (ADR-0252 §10).

    **The planner names an evidence row by label, never by identifier**, and the scheme
    is ADR-0226 §3's applied to a fourth sequence in the shape ADR-0249 §9 applied it
    to three: the label of the digest at 1-based index *n* of ``Planner.plan``'s
    ``evidence`` sequence is :data:`EVIDENCE_LETTER` followed by *n* in decimal with no
    padding. Both sides derive it from the sequence they hold, neither consults the
    other, and **no label survives the call that rendered it**.

    **A row id is stamped by ``orchestration`` and never parsed out of model output**:
    the digest carries no row id (ADR-0249 §10), the label is an ordinal, and the loop
    stamps the id of the row **it itself labelled**. So this resolves over the very
    sequence the call was handed, and a caller passing a different one would be
    labelling a different history.

    **A label of neither form, an *n* below 1 or beyond the sequence's length, and an
    ``E`` label naming a row the store no longer holds each resolve to nothing** — and
    the element is then dropped silently, which is ADR-0249 §7's disposal binding
    unchanged over one more way to fail to resolve. The third case needs no test of its
    own: a row ADR-0252 §13's elision dropped is not in the history the call was handed,
    so every ordinal past its end resolves to nothing like any other.

    Args:
        label: What the planner named, or ``None``. Model-supplied text, treated as a
            label and never as an identifier (ADR-0228 §8).
        evidence: The rows the ``evidence`` sequence of **that call** was projected
            from, in ADR-0252 §12's total order.

    Returns:
        The row's identifier, or ``None``.
    """
    if not label:
        return None
    index = resolved_ordinal(label, EVIDENCE_LETTER, len(evidence))
    return None if index is None else evidence[index].id


@dataclass(frozen=True, slots=True)
class _Identity:
    """What ADR-0253 §7 adds to a **newly recorded** element, carried as one value.

    Both members are ``orchestration``'s and neither crosses the seam as itself: the
    planner writes four axes and ``orchestration`` composes the region
    (:func:`_applicability_of`), and no identifier is rendered to a model or accepted
    from one (ADR-0228 §8). They travel together because they are stamped together, at
    the one instant §7 names — *"once, at the instant the element is first recorded"*.

    Attributes:
        id: The element's durable name, minted here and **not** re-minted by a later
            revision that retains it.
        applicability: What the element is about, or ``None`` where it applied no axis.
    """

    id: str
    applicability: EvidenceApplicability | None


def _applicability_of(proposed: ProposedElement) -> EvidenceApplicability | None:
    """Compose ADR-0253 §7's applicability from what the planner proposed, or nothing.

    **"The planner proposes the applicability and ``orchestration`` records it"** (§7),
    from the four axes :class:`~ai_assistant.core.types.ProposedElement` carries on its
    new-element shape, *"under ADR-0252 §2's own validator"*. A **retaining** element
    never reaches here: it carries ``retains`` and nothing else, and its applicability
    travels in the copy retention makes.

    **Declaring nothing and declaring something malformed are two different states, and
    only the first records an absent applicability** (§7). An element proposing **no
    axis at all** is recorded with ``applicability`` absent — a legal element imposing
    no coverage requirement (ADR-0252 §6 test 1). Every shape §7 names as *not
    composing* an ``EvidenceApplicability`` — an empty sequence axis, a window with both
    ends unset, a window whose ``end`` is not after its ``start`` — is refused **before**
    this function ever sees it: the two window cases by ``TimeWindow``'s own validator
    at the planning seam, the empty axis by ``ProposedElement``'s. So nothing here
    records a malformed requirement as no requirement, which is the widening §7 exists
    to refuse.

    **An axis longer than** :data:`~ai_assistant.core.types.MAX_APPLICABILITY_VALUES`
    **keeps the first values and advances** ``elided``, which is ADR-0252 §2's own
    composition rule for that bound rather than a disposal invented here —
    ``EvidenceApplicability``'s validator names it in terms, *"a composition that would
    exceed it keeps the first … and advances this region's elided"*. It is the one
    over-long case §7's enumeration does not reach, and the count is the disclosure
    ADR-0086 §4 asks for.

    Args:
        proposed: The new element the planner stated.

    Returns:
        The region, or ``None`` where the element applied no axis at all.
    """
    axes = (proposed.participants, proposed.topics, proposed.about_person)
    if proposed.window is None and all(values is None for values in axes):
        return None
    participants, topics, about_person = (_capped(values) for values in axes)
    return EvidenceApplicability(
        window=proposed.window,
        participants=participants[0],
        topics=topics[0],
        about_person=about_person[0],
        elided=participants[1] + topics[1] + about_person[1],
    )


def _capped[T](values: tuple[T, ...] | None) -> tuple[tuple[T, ...] | None, int]:
    """Keep at most :data:`MAX_APPLICABILITY_VALUES` of one axis, and count the rest.

    Args:
        values: One label axis as the planner stated it, or ``None``.

    Returns:
        The axis to record, and how many values it dropped.
    """
    if values is None or len(values) <= MAX_APPLICABILITY_VALUES:
        return values, 0
    return values[:MAX_APPLICABILITY_VALUES], len(values) - MAX_APPLICABILITY_VALUES


def _from_evidence(  # noqa: PLR0913 — the text, §7's identity, and one parameter per sequence a label may resolve against; collapsing any pair would hide which rule decided
    text: str,
    *,
    identity: _Identity,
    label: str | None,
    supply: Sequence[MemoryRecord],
    minted: Collection[str],
    evidence: Sequence[GoalEvidence],
) -> GoalElement | None:
    """Stamp a ``FROM_EVIDENCE`` element from whichever label space it names (§10).

    **The prefix is the whole of what decides which sequence is resolved against**
    (ADR-0252 §10): ``M`` against the ``memories`` passed on that call, ``E`` against
    the ``evidence`` passed on that call. The element carries **exactly one** of
    ``evidence_id`` and ``evidence_row_id``, which its own validator enforces — so the
    two spaces are mutually exclusive at the value as well as at the label.

    A label of neither form resolves to nothing on the ``M`` path, exactly as it did
    before this fourth space existed, and the element is dropped.

    Args:
        text: What the element says.
        identity: ADR-0253 §7's two members, stamped on whichever shape resolves.
        label: The label the planner named, or ``None``.
        supply: The sequence the loop passed the planner on this call.
        minted: The ids of the records this turn's searches minted.
        evidence: The rows this call's ``evidence`` sequence was projected from.

    Returns:
        The element to record, or ``None`` where its ground resolved to nothing.
    """
    if label is not None and label.startswith(EVIDENCE_LETTER):
        row_id = resolved_evidence_row(label, evidence)
        if row_id is None:
            return None
        return GoalElement(
            text=text,
            ground=Ground.FROM_EVIDENCE,
            evidence_row_id=row_id,
            id=identity.id,
            applicability=identity.applicability,
        )
    evidence_id = _resolved_record(label, supply, minted)
    if evidence_id is None:
        return None
    return GoalElement(
        text=text,
        ground=Ground.FROM_EVIDENCE,
        evidence_id=evidence_id,
        id=identity.id,
        applicability=identity.applicability,
    )


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


def _resolved_element(  # noqa: PLR0913 — one parameter per thing a ground is resolved against, and one return per way a ground resolves or fails to; collapsing either would hide which rule decided
    proposed: ProposedElement,
    *,
    letter: str,
    current: Sequence[GoalElement],
    utterance: str,
    supply: Sequence[MemoryRecord],
    minted: Collection[str],
    evidence: Sequence[GoalEvidence],
    id_factory: Callable[[], str],
) -> GoalElement | None:
    """Resolve one proposed element, or drop it (§7).

    A **retaining** element names a label of this tuple and is copied **whole and
    unchanged** — "its ``text``, its ``ground``, its ``evidence_id`` and its ``span``
    exactly as the earlier revision recorded them". A **new** element carries its own
    ground and is resolved by the two rules above. Anything that resolves to nothing is
    dropped from the recorded revision, silently and without failing the turn.

    **ADR-0253 §7's identity is minted here and only here**, because here is where an
    element is *first recorded*. A retained element is copied whole, so its ``id`` and
    its ``applicability`` travel in that copy and are **not** re-minted — which is what
    makes the id a durable name for a proposition rather than for a revision. A
    **restated** element reaches the ``new`` branch and is minted a different one,
    "because a revision that restates a proposition has stated a different one".

    **The id is minted before the ground is resolved, and a dropped element spends
    one.** Nothing reads an element id as an ordinal, a count or a position — it is an
    opaque durable name — so a spent value costs nothing, where minting *after* the
    resolution would put the one call that may fail between the two members §7 stamps
    together.

    Args:
        proposed: What the planner returned for this position.
        letter: The label letter of the tuple this element sits in.
        current: That same tuple of the goal's **current** interpretation.
        utterance: This turn's own request.
        supply: The sequence the loop passed the planner on this call.
        minted: The ids of the records this turn's searches minted.
        evidence: The rows this call's ``evidence`` sequence was projected from
            (ADR-0252 §10).
        id_factory: Mints a new element's ``id`` (§7).

    Returns:
        The element to record, or ``None`` where it is dropped.
    """
    if proposed.retains is not None:
        index = resolved_ordinal(proposed.retains, letter, len(current))
        return None if index is None else current[index]
    # A new element: `ProposedElement`'s validator refused every shape but the three a
    # ground admits, so both values below are present on anything that constructed.
    # The narrowing is what mypy needs and is not a second refusal.
    text, ground = proposed.text, proposed.ground
    if text is None or ground is None:  # pragma: no cover — the validator admits no such value
        return None
    identity = _Identity(id=id_factory(), applicability=_applicability_of(proposed))
    if ground is Ground.FROM_EVIDENCE:
        return _from_evidence(
            text,
            identity=identity,
            label=proposed.evidence_label,
            supply=supply,
            minted=minted,
            evidence=evidence,
        )
    if ground is Ground.USER_STATED:
        span = _resolved_span(proposed.span, utterance)
        if span is None:
            return None
        return GoalElement(
            text=text,
            ground=ground,
            span=span,
            id=identity.id,
            applicability=identity.applicability,
        )
    return GoalElement(
        text=text, ground=ground, id=identity.id, applicability=identity.applicability
    )


def _resolved_group(  # noqa: PLR0913 — the tuple, its letter, and the same values `_resolved_element` resolves against, threaded once per element
    proposed: Sequence[ProposedElement],
    *,
    letter: str,
    current: Sequence[GoalElement],
    utterance: str,
    supply: Sequence[MemoryRecord],
    minted: Collection[str],
    evidence: Sequence[GoalEvidence],
    id_factory: Callable[[], str],
) -> tuple[GoalElement | None, ...]:
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
        evidence: The rows this call's ``evidence`` sequence was projected from
            (ADR-0252 §10).
        id_factory: Mints each new element's ``id`` (ADR-0253 §7).

    **One entry per *proposed* position, and a dropped element is a ``None``** rather
    than an absence. ADR-0250 §7 resolves a raised question's subject to "the position it
    names in the ``ProposedUnderstanding``'s own tuple", and then reads the text of "the
    ``GoalElement`` **that position produced**" — so a caller that only saw the surviving
    elements could not tell which proposed position each came from, and would drop a
    valid question because a **sibling**'s ground failed. The caller that wants the
    recorded tuple filters; the caller that wants the correspondence reads it.

    Returns:
        One entry per proposed element, in the order the planner stated them: the
        element to record, or ``None`` where its ground did not resolve.
    """
    return tuple(
        _resolved_element(
            element,
            letter=letter,
            current=current,
            utterance=utterance,
            supply=supply,
            minted=minted,
            evidence=evidence,
            id_factory=id_factory,
        )
        for element in proposed
    )


@dataclass(frozen=True, slots=True)
class RecordedUnderstanding:
    """One recorded revision, and which proposed position produced each element (§7).

    ADR-0250 §7 resolves a raised question's subject to **the position it names in the
    ``ProposedUnderstanding``'s own tuple**, and then records the text of *"the
    ``GoalElement`` **that position produced** in the revision this turn recorded"*. So
    the correspondence between a proposal's positions and the revision's is a value the
    caller needs and cannot recompute: ADR-0249 §7's ground resolution drops an element
    whose ground does not resolve, and a caller comparing lengths would drop a question
    about a **surviving** element because a *sibling* failed.

    Attributes:
        revision: The revision to append.
        positions: Per tuple name — ``constraints``, ``criteria``, ``conditions`` — one
            entry per **proposed** position, holding that position's index in the
            recorded tuple, or ``None`` where its ground did not resolve and the element
            is not in the revision at all.
    """

    revision: GoalInterpretation
    positions: Mapping[str, tuple[int | None, ...]]


def recorded_revision(  # noqa: PLR0913 — the goal, what the planner proposed, and one parameter per thing a ground is resolved against plus the two values §6 reserves to `orchestration`; every one is a distinct fact and a bundle would mint a type for an argument list
    goal: Goal,
    understanding: ProposedUnderstanding,
    *,
    utterance: str,
    supply: Sequence[MemoryRecord],
    minted: Collection[str] = (),
    evidence: Sequence[GoalEvidence] = (),
    recorded_at: datetime,
    raised_by: str,
    id_factory: Callable[[], str],
) -> RecordedUnderstanding:
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
        evidence: The rows this call's ``evidence`` sequence was projected from, in
            ADR-0252 §12's total order. An ``E`` label resolves against **this**
            sequence and an ``M`` label against ``supply``, and the prefix is the whole
            of what decides which (ADR-0252 §10). Empty on a goal whose history the
            store holds no row of, which is every goal this turn opened.
        recorded_at: This turn's instant.
        raised_by: The turn whose message caused this revision. Required and
            undefaulted: §1 forbids writing ``None`` into it on a value
            ``orchestration`` authors, and a default would let a call site forget it.
        id_factory: Mints ADR-0253 §7's ``GoalElement.id`` for every element this
            revision records **anew**. Required and undefaulted for ``raised_by``'s
            reason one field over: §7 makes ``orchestration`` the minter, every element
            *"of every revision ``orchestration`` records after this decision carries
            one"*, and an element that quietly took ``None`` would be an element *"named
            by no ``StepCondition`` and settled by no interpretation"* — a condition
            about it could never be satisfied and nothing would say why.

    Returns:
        The revision to append, beside the correspondence ADR-0250 §7 resolves a
        raised question's subject through. It is not appended here: what a caller does
        with it —
        an in-memory append on a goal this turn opened, a ``record_interpretation``
        under §12's compare-and-swap on one the store already holds — is the caller's,
        and this function holds only the resolution.
    """
    current = goal.interpretation[-1]
    if understanding.retains_outcome:
        outcome, ground = current.outcome, current.outcome_ground
        evidence_id, span = current.outcome_evidence_id, current.outcome_span
        # ADR-0252 §10: the outcome's fourth ground argument is copied forward on the
        # same rule as the other three — §7's "byte for byte", which a retained outcome
        # that quietly lost its row reference would break.
        row_id = current.outcome_evidence_row_id
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
        # ADR-0252 §10: `GoalInterpretation` gains `outcome_evidence_row_id` "on the
        # same rule", because ADR-0249 §1 validates the outcome's arguments "as a
        # `GoalElement`'s are" — so the outcome resolves through the same two label
        # spaces an element does, and carries exactly one of the two arguments.
        label = understanding.outcome_evidence_label
        evidence_id, row_id = None, None
        if label is not None and label.startswith(EVIDENCE_LETTER):
            row_id = resolved_evidence_row(label, evidence)
        else:
            evidence_id = _resolved_record(label, supply, minted)
        span = _resolved_span(understanding.outcome_span, utterance)
        unresolved = (
            ground is Ground.FROM_EVIDENCE and evidence_id is None and row_id is None
        ) or (ground is Ground.USER_STATED and span is None)
        if unresolved:
            # §7: recorded `INFERRED` with neither argument rather than dropped.
            ground, evidence_id, row_id, span = Ground.INFERRED, None, None, None
    groups = (
        (
            "constraints",
            CONSTRAINTS_LETTER,
            understanding.constraints,
            current.constraints,
        ),
        ("criteria", CRITERIA_LETTER, understanding.criteria, current.criteria),
        (
            "conditions",
            CONDITIONS_LETTER,
            understanding.conditions,
            current.conditions,
        ),
    )
    resolved = {
        name: _resolved_group(
            proposed,
            letter=letter,
            current=held,
            utterance=utterance,
            supply=supply,
            minted=minted,
            evidence=evidence,
            id_factory=id_factory,
        )
        for name, letter, proposed, held in groups
    }
    kept = {
        name: tuple(one for one in group if one is not None) for name, group in resolved.items()
    }
    return RecordedUnderstanding(
        revision=GoalInterpretation(
            revision=current.revision + 1,
            outcome=outcome,
            outcome_ground=ground,
            outcome_evidence_id=evidence_id,
            outcome_evidence_row_id=row_id,
            outcome_span=span,
            constraints=kept["constraints"],
            criteria=kept["criteria"],
            conditions=kept["conditions"],
            recorded_at=recorded_at,
            raised_by=raised_by,
        ),
        positions={name: _positions(group) for name, group in resolved.items()},
    )


def _positions(group: Sequence[GoalElement | None]) -> tuple[int | None, ...]:
    """Map each proposed position to its index in the recorded tuple, or to nothing.

    Args:
        group: One tuple's per-proposed-position resolution.

    Returns:
        One entry per proposed element: its index among the survivors, or ``None``.
    """
    mapped: list[int | None] = []
    kept = 0
    for element in group:
        if element is None:
            mapped.append(None)
            continue
        mapped.append(kept)
        kept += 1
    return tuple(mapped)


def substituted_plan(  # noqa: PLR0913 — the plan, the goal it targets, and one parameter per sequence a value on it resolves against; every one is a distinct fact and a bundle would mint a type for an argument list
    plan: ActionPlan,
    *,
    goal: Goal,
    understanding: ProposedUnderstanding | None,
    positions: Mapping[str, tuple[int | None, ...]],
    supply: Sequence[MemoryRecord],
    minted: Collection[str],
) -> ActionPlan:
    """Substitute each condition label for an element id, or refuse the plan (§9).

    **"The loop resolves the label, once, and the planner never does"** (ADR-0253 §9).
    Every :attr:`~ai_assistant.core.types.StepCondition.about` and every
    :attr:`~ai_assistant.core.types.PlanInterpretation.settles` the planner returned
    carries a **condition label**; what the store holds is a
    :attr:`~ai_assistant.core.types.GoalElement.id`. This is the one act that turns the
    first into the second, and it is taken **once per plan**, immediately on return,
    after this same call's understanding has been recorded and its element ids minted,
    after ADR-0249 §8's ``targets_revision`` stamp, and before the plan is persisted,
    driven or interpreted.

    **Which sequence a label indexes is decided by the envelope and by nothing else**
    (§9). Where the call returned an ``understanding``, the label indexes **that
    understanding's own ``conditions`` tuple**; where it returned none, it indexes the
    ``GoalBrief.conditions`` the call received — which
    :meth:`~ai_assistant.core.types.GoalBrief.of` projects one-for-one and in order
    from the goal's current revision, so that revision's own tuple is the same
    sequence read without a second projection. *"Exactly one of the two is in force per
    call, and it is always the sequence that describes the revision the plan will
    target."*

    **The correspondence is the loop's own and never a length comparison** (§9): *"a
    proposed element ADR-0249 §7 dropped resolves to nothing rather than to its
    neighbour"*. That is what ``positions`` carries, and it is ADR-0250 §7's argument
    one field over — a caller that indexed the **recorded** tuple would silently point
    every label after a dropped element at its neighbour.

    **The substitution is a resolution and not an authorship** (§9, ADR-0228 §5). The
    planner chose which element each condition is about, by naming a position in a
    sequence it was rendered or returned; what is supplied here is the **name** of the
    thing chosen, which is a value only ``orchestration`` holds because only
    ``orchestration`` mints element ids. Every other field of the plan, of every step
    and of every interpretation is left exactly as the planner returned it.

    **A plan declaring none of the new keys is returned unchanged**, by identity and
    not by a copy: it carries no label to substitute and no ``record`` to check, which
    is what makes ADR-0253 §12's *"It changes no behaviour of a plan that declares none
    of the new keys"* a property of this function rather than a claim about it.

    **Refused before the save, and never repaired** (§9). A label outside the range, a
    value that is not such a label, a label naming a proposed element the loop dropped,
    and a label naming an element carrying no ``id`` each resolve to nothing, and so
    does an interpretation naming a record this call did not pass. The plan is **not**
    handed to ``save_plan``, no step of it is dispatched and no interpretation of it is
    performed. *"No lane drops the condition instead"*, because a step whose condition
    was dropped is a step with fewer requirements than the plan declared — the
    fail-open direction, and the one §1 refuses for a dropped dependency for the same
    reason. **What the refusal then causes is recovery policy and is A7's and A9's.**

    Args:
        plan: The plan this call returned, already stamped (ADR-0249 §8).
        goal: The goal **as it stands after this call's understanding was recorded**,
            so ``interpretation[-1]`` is the revision the plan targets and the one
            whose elements carry the ids substituted in.
        understanding: What this same call proposed, or ``None`` where it proposed no
            change. It is what decides which sequence is in force, and no other value
            does.
        positions: Which position of the recorded tuple each **proposed** position
            produced (:class:`RecordedUnderstanding`), or ``None`` where its ground did
            not resolve. Empty where no understanding was recorded, and unread there.
        supply: The ``memories`` sequence this call was handed, which is ADR-0226 §3's
            label space for this call and the population an interpretation's ``record``
            must name.
        minted: The ids of the records this turn's searches and fetches minted, which
            ADR-0231 §16 rules *"resolves in no store"*.

    Returns:
        The plan with every condition label replaced by the id it resolves to, or the
        plan itself where it named none.

    Raises:
        PlanningError: If any label resolves to nothing, or an interpretation carrying
            a ``record`` names one this call did not pass.
    """
    _refuse_an_unpassed_record(plan, supply=supply, minted=minted)
    labels = frozenset(
        [condition.about for step in plan.steps for condition in step.when]
        + [one.settles for one in plan.interpretations]
    )
    if not labels:
        return plan
    elements = _named_conditions(goal, understanding=understanding, positions=positions)
    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for label in sorted(labels):
        index = resolved_ordinal(label, CONDITIONS_LETTER, len(elements))
        element = None if index is None else elements[index]
        if element is None or element.id is None:
            unresolved.append(label)
        else:
            resolved[label] = element.id
    if unresolved:
        msg = (
            f"plan {plan.id} names {', '.join(unresolved)}, which "
            f"{'resolves' if len(unresolved) == 1 else 'resolve'} to no condition "
            f"element of revision {plan.targets_revision} of goal {plan.goal_id}: a "
            f"label that resolves to nothing refuses the plan, which is neither saved "
            f"nor driven (ADR-0253 §9)"
        )
        raise PlanningError(msg)
    return plan.model_copy(
        update={
            "steps": tuple(_substituted_step(step, resolved) for step in plan.steps),
            "interpretations": tuple(
                _substituted_interpretation(one, resolved) for one in plan.interpretations
            ),
        }
    )


def _named_conditions(
    goal: Goal,
    *,
    understanding: ProposedUnderstanding | None,
    positions: Mapping[str, tuple[int | None, ...]],
) -> tuple[GoalElement | None, ...]:
    """The sequence a ``D`` label indexes on this call, one entry per position (§9).

    Where the call proposed an understanding, the sequence is **that understanding's
    own ``conditions``** and each position holds the element it produced in the
    recorded revision, or ``None`` where ADR-0249 §7 dropped it. Where it proposed
    none, the sequence is the brief's, which ``GoalBrief.of`` projects one-for-one from
    the goal's current revision — so the revision's own tuple is that same sequence
    with nothing dropped and nothing to map.

    Args:
        goal: The goal after this call's understanding, if any, was recorded.
        understanding: What this call proposed, or ``None``.
        positions: The proposal-to-revision correspondence.

    Returns:
        One entry per label position: the element it names, or ``None``.
    """
    recorded = goal.interpretation[-1].conditions
    if understanding is None:
        return recorded
    produced = positions.get("conditions", ())
    return tuple(
        None if kept is None or kept >= len(recorded) else recorded[kept] for kept in produced
    )


def _substituted_step(step: PlanStep, resolved: Mapping[str, str]) -> PlanStep:
    """One step with each of its conditions' ``about`` replaced (§9).

    Args:
        step: The step as the planner returned it.
        resolved: Each label this plan named, and the element id it resolves to.

    Returns:
        The step, or the step itself where it declared no condition.
    """
    if not step.when:
        return step
    return step.model_copy(
        update={
            "when": tuple(
                one.model_copy(update={"about": resolved[one.about]}) for one in step.when
            )
        }
    )


def _substituted_interpretation(
    interpretation: PlanInterpretation, resolved: Mapping[str, str]
) -> PlanInterpretation:
    """One interpretation with its ``settles`` replaced (§9).

    Args:
        interpretation: The interpretation as the planner returned it.
        resolved: Each label this plan named, and the element id it resolves to.

    Returns:
        The interpretation, carrying the element id its label resolved to.
    """
    return interpretation.model_copy(update={"settles": resolved[interpretation.settles]})


def _refuse_an_unpassed_record(
    plan: ActionPlan, *, supply: Sequence[MemoryRecord], minted: Collection[str]
) -> None:
    """Refuse a plan whose interpretation names a record this call did not pass (§9).

    **"For each interpretation that carries a ``record``, the loop verifies it is the
    ``id`` of a record of the ``memories`` sequence **it** passed on that call"** (§8),
    and a plan failing that check *"is refused before it is saved — not persisted, not
    driven, and not interpreted"*. **The loop is the only component that can run it**:
    it holds the sequence, and the ``Planner`` contract renders no identifier and
    accepts none (ADR-0228 §8), so the value on the returned plan is one a conforming
    planner resolved against a sequence this loop handed it — and a non-conforming one
    is exactly what this closes the window on.

    **A record this turn's own search or fetch minted fails the same check**, and this
    is issue #2345's disposal. §8 forbids such a label in terms — *"a label naming a
    record ADR-0231 §1's search or ADR-0230 §5's fetch **minted**"* — on ADR-0252 §1's
    ground that a minted record *"resolves in no store"*, so a durable row naming one
    *"would state a warrant it cannot show"*. §8 spells the disposal as an *extraction
    failure for that envelope*, which is the planning seam's; but **the planner is
    handed no minted set** and can therefore produce no such refusal, so the check has
    no producer there. It is run here instead, and its disposal is §9's — the plan is
    refused before it is saved. The refusing direction is the same and the cost differs
    only in that this one reaches no repair prompt; the ADR text is flagged for a §8
    amendment rather than read as authorising a second disposal on its own.

    **An interpretation carrying a ``reads`` is checked by neither** (§9): *"its input
    is a value this plan will itself produce, and §8's construction rules are the whole
    of what it owes"* — its ``reads.step`` is a step of this plan and the ordering rule
    is ``ActionPlan``'s, both settled at construction.

    Args:
        plan: The plan this call returned.
        supply: The ``memories`` sequence this call was handed.
        minted: The ids of the records this turn's searches and fetches minted.

    Raises:
        PlanningError: If an interpretation names a record outside that sequence, or
            one this turn minted.
    """
    named = [one.record for one in plan.interpretations if one.record is not None]
    if not named:
        return
    durable = frozenset(record.id for record in supply) - frozenset(minted)
    unpassed = sorted(set(named) - durable)
    if unpassed:
        msg = (
            f"plan {plan.id} interprets {', '.join(unpassed)}, which "
            f"{'is' if len(unpassed) == 1 else 'are'} not a durable record of the "
            f"supply this call passed: a minted record resolves in no store, so the "
            f"plan is refused before it is saved (ADR-0253 §8, §9)"
        )
        raise PlanningError(msg)
