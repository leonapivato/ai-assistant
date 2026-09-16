"""What a servicing established about a goal, composed and projected (ADR-0252).

This module is ADR-0252 §17's **I2** in one place: the loop's half of the durable
evidence record, beside the contract, the store and the migration I1 landed.

**Four things live here and nothing else.** §3's composition — ``requested`` from
the *typed* part of an ask and the ``supported`` regions from the records the ask
returned; §8's six-limb refresh test, whose result is the ``supersedes`` set a
``record_evidence`` carries; §11's projection of one goal's history into the
``EvidenceDigest`` sequence ``Planner.plan`` is handed; and §10's ``E`` label
space over that same sequence.

**What is deliberately not here.** §6's four sufficiency tests live in
:mod:`ai_assistant.orchestration.effects` beside the one caller the tree has for
them — ADR-0259 §2's reuse conditions, checked where the effect claim is taken —
and §7's conflict predicate still has none. What this module keeps of §6 is the
**instant** its recency test is evaluated at, :func:`effective_instant`, because
§8 limb 6 is stated over that same instant and two statements of one rule are two
places for it to drift. §9's invalidation *predicate* is likewise absent: its two operands are a
declared applicability no type in the tree carries, and §9 states that until that
lands ``GoalRevision.invalidates`` is empty on every revision. Both are named in
:mod:`ai_assistant.orchestration` rather than stubbed, because a stub is a place
a later lane reads a decision out of.

**Nothing here holds a store** (ADR-0249 §11). Every function is pure over the
values a caller already holds: the loop composes and stamps, and
:class:`~ai_assistant.orchestration.engine.Engine` writes at the persistence
boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    MAX_APPLICABILITY_VALUES,
    MAX_EVIDENCE_RECORDS,
    MAX_SUPPORTED_REGIONS,
    EpisodicMemory,
    EvidenceApplicability,
    EvidenceBasis,
    EvidenceDigest,
    EvidenceStanding,
    GoalEvidence,
    ReadAsk,
    ReadKind,
    ReadOutcomeKind,
    TimeWindow,
    evidence_order,
    support_covers_support,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from ai_assistant.core.types import MemoryRecord, ReportedExtent


#: The three :class:`ReadKind` members whose records **resolve in the owner's own**
#: ``MemoryStore``, and whose rows therefore *name* them (ADR-0252 §1). A
#: ``SIGHTED_QUERY`` is a relevance selection over that store, a ``CITATION_HOP`` is
#: ADR-0208 §1's "records the turn already names, fetched by identifier", and a
#: ``STRUCTURED_READ`` is ADR-0240 §1's structured filter over it.
#:
#: **The split is by where the record lives and not by which ADR minted it.** The two
#: absent members each mint a record for one turn that "resolves in no store"
#: (ADR-0231 §16, ADR-0230 §10), so their rows carry ``records`` empty and the count
#: stands alone — which is ADR-0086 §4's shape reached "because the ids would not
#: resolve rather than because they are the payload".
DURABLE_KINDS: Final[frozenset[ReadKind]] = frozenset(
    {ReadKind.SIGHTED_QUERY, ReadKind.CITATION_HOP, ReadKind.STRUCTURED_READ}
)

#: ADR-0252 §5's **affirmative** partition of :class:`ReadOutcomeKind`, on the
#: ``READ_OUTCOME`` basis: the three members that state the source **answered with
#: records**. The other four — ``EMPTY``, ``REFUSED``, ``FAILED`` and ``EXPIRED`` —
#: each state that no record came back at all, and **a non-answering row satisfies
#: nothing** and refreshes nothing (§8 limb 5).
#:
#: **``DUPLICATE`` is answering**, and §5 makes that a correction rather than a
#: nicety: a duplicated-out ask returned records, the regions composed from them
#: support exactly what those records said, and whether the supply already held them
#: is a fact about *this turn's supply*. Reading it the other way left a new goal
#: whose one relevant record initial retrieval had already supplied unable ever to
#: obtain sufficient evidence.
#:
#: **It is a partition of a closed vocabulary and reads no count** (§5): not
#: ``returned``, not ``admitted``, and not a judgement about relevance, quality or
#: usefulness. A ``TRUNCATED`` over an answer that returned no record is kept out by
#: the coverage test, which sees ``supported`` empty, and needs no arithmetic here.
ANSWERING: Final[frozenset[ReadOutcomeKind]] = frozenset(
    {
        ReadOutcomeKind.RETURNED_RECORDS,
        ReadOutcomeKind.DUPLICATE,
        ReadOutcomeKind.TRUNCATED,
    }
)


def _blank(value: str) -> bool:
    """Whether a copied label value is blank, tested without touching it.

    ADR-0252 §2: "A blank value on a returned record contributes nothing to its
    region and advances that region's ``elided``" — it is **dropped, never stripped,
    never case-folded and never repaired**. This is the test the target annotation
    :data:`~ai_assistant.core.types.NonBlankEncodableText` applies, read here so the
    value is refused rather than mended: ADR-0096 §2's "a faithful copy takes the
    type of the field it copies, and may tighten only in ways that reject".

    Args:
        value: The record's own value, untouched.

    Returns:
        Whether the target annotation would refuse it.
    """
    return not value.strip()


def _axis(values: Sequence[str]) -> tuple[tuple[str, ...], int]:
    """One label axis of one region, bounded and disclosed (ADR-0252 §2).

    Blank values are dropped and each advances the count; the surviving values keep
    the record's own order and bytes; and a composition that would exceed
    :data:`~ai_assistant.core.types.MAX_APPLICABILITY_VALUES` **keeps the first 32 in
    the order the source produced them** and advances the count by the rest.

    **Every truncation narrows and none widens**, which is why they are admissible at
    all: a dropped value makes ``supported`` cover less, so it satisfies fewer
    conditions and supersedes fewer rows. ADR-0086 §4's refusal of *silent* truncation
    is discharged by the count this returns beside the values.

    Args:
        values: The record's own values for this axis, in its own order.

    Returns:
        The axis's values and how many this composition dropped.
    """
    kept = tuple(value for value in values if not _blank(value))
    elided = len(values) - len(kept)
    if len(kept) > MAX_APPLICABILITY_VALUES:
        elided += len(kept) - MAX_APPLICABILITY_VALUES
        kept = kept[:MAX_APPLICABILITY_VALUES]
    return kept, elided


def _window(extent: ReportedExtent | None) -> tuple[TimeWindow | None, int]:
    """The window axis of one region, applied only where a source declared one (§3).

    **The axis is applied where the record's** ``Provenance.attestation`` **carries a**
    :class:`~ai_assistant.core.types.ReportedExtent` **and nowhere else.** That extent
    is ADR-0117 §2's "reporting source's own statement about the thing it reported",
    and ADR-0252 has no better authority for what a source covered. Where the record
    carries no attestation, or one whose ``extent`` is ``None``, the axis is not
    applied and nothing is elided — nothing was declined.

    **Where the declared interval cannot be expressed as a**
    :class:`~ai_assistant.core.types.TimeWindow` — both ends unset, or ends that are
    not strictly ordered — **the axis is not applied and the region's ``elided``
    advances by one.** No bound the source did not state is substituted, no end is
    invented, none is clamped to a retention horizon, and no window is widened to make
    one constructible.

    **An unbounded extent is declined rather than carried, which is the fail-closed
    direction** (§3). A both-ends-unset extent is the most permissive claim a source
    can make and an applicability has no spelling for it; declining makes the region
    cover **no** applied window where carrying it as unbounded would make it cover
    **every** one.

    **A record's** ``Validity`` **is never read here**, on any kind, under any
    fallback: ADR-0117 §2 keeps the three subjects apart — "a ``Validity`` is our
    window on a belief we hold, a ``ReadCoverage`` is a claim about the read we
    performed, and an extent is the source's claim about where the reported entry
    lies". A weather record stored on Saturday with ``valid_from`` set and no extent
    would otherwise have supported every later date off a persistence timestamp no
    source said anything with.

    Args:
        extent: The attestation's declared interval, or ``None``.

    Returns:
        The window to apply, or ``None``, and 1 where an extent was declared and
        declined.
    """
    if extent is None:
        return None, 0
    try:
        return TimeWindow(start=extent.extends_from, end=extent.extends_until), 0
    except ValueError:
        return None, 1


def region_of(record: MemoryRecord) -> EvidenceApplicability | None:
    """Compose one region from one returned record, or nothing (ADR-0252 §3).

    **One region per record and never one per ask**, composed from that record's own
    values and **never from the ask**: ``participants`` from an
    :class:`~ai_assistant.core.types.EpisodicMemory`'s own ``participants``,
    ``topics`` from the record's ``topics``, ``about_person`` from its
    ``about_person`` — which is one value and reaches the axis as a one-member tuple —
    and ``window`` by :func:`_window`.

    **A record carrying no applied axis contributes no region** (§3), which is the
    clause that makes today's ``WEB_SEARCH`` and ``LOCAL_FILE`` rows carry
    ``supported`` empty: ADR-0231 §16's minted search record and ADR-0230 §5's minted
    fetch record each carry "``topics`` is empty, ``about_person`` is ``None``" and
    ``extent`` ``None``. Such a row records durably that the source was asked and what
    became of the ask, and is evidence that nothing is so.

    **A record's** ``occurred_at`` **is not a declaration of coverage** (§3). An
    episode's is an *instant*, ``TimeWindow`` is an interval that states at least one
    end, and manufacturing ``[t, t + e)`` would invent a bound — which is exactly the
    assertion ADR-0237 §7 forbids. So an episodic read supports what its episodes were
    **about** and **whom** they involved, and supports no period at all.

    Args:
        record: One record the ask returned, before ADR-0226 §7's deduplication.

    Returns:
        The region, or ``None`` where the record applied no axis.
    """
    attestation = record.provenance.attestation
    window, elided = _window(None if attestation is None else attestation.extent)
    participants: tuple[str, ...] = ()
    if isinstance(record, EpisodicMemory):
        participants, dropped = _axis(record.participants)
        elided += dropped
    topics, dropped = _axis(record.topics)
    elided += dropped
    about: tuple[str, ...] = ()
    if record.about_person is not None:
        about, dropped = _axis((record.about_person,))
        elided += dropped
    if window is None and not participants and not topics and not about:
        return None
    return EvidenceApplicability(
        window=window,
        participants=participants or None,
        topics=topics or None,
        about_person=about or None,
        elided=elided,
    )


def supported_of(
    records: Sequence[MemoryRecord],
) -> tuple[tuple[EvidenceApplicability, ...], int]:
    """Compose a row's ``supported`` from the records the ask returned (§2, §3).

    One region per record, in the order the servicing produced them, and **no lane
    merges two regions**, unions their label axes, spans their windows, or replaces
    the tuple by its enclosing interval: an aggregate asserts the *conjunction* of
    what several records said, where the records only ever said their own parts.

    A composition that would exceed
    :data:`~ai_assistant.core.types.MAX_SUPPORTED_REGIONS` keeps the first 32 regions
    and advances the row's ``supported_elided`` by the rest, which is the same
    fail-closed narrowing :func:`_axis` performs one level down.

    Args:
        records: The records the ask returned, **before** ADR-0226 §7's deduplication.

    Returns:
        The regions and how many this composition dropped.
    """
    regions = tuple(
        region for region in (region_of(record) for record in records) if region is not None
    )
    elided = 0
    if len(regions) > MAX_SUPPORTED_REGIONS:
        elided = len(regions) - MAX_SUPPORTED_REGIONS
        regions = regions[:MAX_SUPPORTED_REGIONS]
    return regions, elided


def requested_of(ask: ReadAsk) -> EvidenceApplicability | None:
    """Compose a row's ``requested`` from the *typed* part of the ask (§3).

    **One kind of five produces a ``requested``, and that is the rule working rather
    than a gap.** A ``STRUCTURED_READ``'s four axes are carried across **byte for
    byte** into one region, and an ask carrying a ``query`` beside its structure
    contributes the structure alone. Every other kind is **absent**, each on a clause
    of the corpus rather than as an omission to repair:

    * **``SIGHTED_QUERY``** — the ask's only argument is a composed query, which
      ADR-0228 §11 rules "a model completion with no recorded origin" that "no lane …
      treats as evidence of anything". Copying one into a durable row and rendering it
      back to the planner is exactly treating it as evidence of what was asked.
    * **``CITATION_HOP``** and **``LOCAL_FILE``** — each ask's only argument is a
      label, and ADR-0249 §9 states the consequence in terms: "no label survives that
      call, and none is persisted as a reference". A ``LOCAL_FILE`` entry resolves to a
      path besides, and a durable row is a worse place for one than an audit is.
    * **``WEB_SEARCH``** — **necessarily** absent: ADR-0231 §1 gives the ask "no
      field", which is "the whole safety mechanism and a property of the type".

    **``requested`` comes from the ask and ``supported`` from the records**, and the
    asymmetry is structural rather than a rule to remember: they are written from two
    different objects at two different moments, so no implementation can fill the
    second from the first by accident.

    Args:
        ask: The ask the planner emitted, byte for byte.

    Returns:
        The region the ask named, or ``None`` where it has no typed part.
    """
    structure = ask.structure
    if ask.kind is not ReadKind.STRUCTURED_READ or structure is None:
        return None
    return EvidenceApplicability(
        window=structure.window,
        participants=structure.participants,
        topics=structure.topics,
        about_person=structure.about_person,
    )


def as_of_of(kind: ReadKind, records: Sequence[MemoryRecord]) -> datetime | None:
    """The instant **the source itself declares** for this reading, or nothing (§4).

    ADR-0096 §2's field with ADR-0096 §2's meaning, and that section's prohibition
    binds verbatim: it "may never be filled from the filesystem, from the clock, from
    ``read_at``, or from one entry's stamp applied to the rest". So it is taken from
    the records' own attestations and from nothing else — a ``WEB_SEARCH``'s minted
    records carry the response's declared instant there (ADR-0231 §16), and the
    owner's own store-written beliefs and episodes declare no reading-level instant
    and leave it absent.

    **The earliest and not the latest, because the row states one instant for a set**
    (§4). A row composed from three records the source reported at three moments
    speaks for the picture as of the oldest of them; taking the newest would let one
    fresh record make two stale ones look current.

    **A ``LOCAL_FILE`` row carries it absent, and that is an exception stated rather
    than an oversight.** ADR-0230 §5 sets a fetched record's ``reported_at`` to "the
    instant the file was read", so the generic rule would fill this with the value
    ``read_at`` already carries — and a row carrying it twice would be
    indistinguishable, on inspection, from one that filled ``as_of`` **from**
    ``read_at``. The two are one event on that producer's own argument, and §6's
    recency test reads ``as_of`` where present and ``read_at`` otherwise, so the
    instant it evaluates is the same either way.

    Args:
        kind: What was read.
        records: The records the ask returned.

    Returns:
        The earliest declared instant, or ``None``.
    """
    if kind is ReadKind.LOCAL_FILE:
        return None
    declared = [
        record.provenance.attestation.reported_at
        for record in records
        if record.provenance.attestation is not None
    ]
    return min(declared) if declared else None


def records_of(kind: ReadKind, records: Sequence[MemoryRecord]) -> tuple[str, ...]:
    """Which record identifiers the row names (ADR-0252 §1).

    **Durable kinds name and ephemeral kinds count.** A ``SIGHTED_QUERY``, a
    ``CITATION_HOP`` and a ``STRUCTURED_READ`` each read the owner's own
    ``MemoryStore``, so every record they return is store-resident and is named. A
    ``WEB_SEARCH`` and a ``LOCAL_FILE`` each mint a record for one turn that "resolves
    in no store" (ADR-0231 §16, ADR-0230 §10), so their rows carry this **empty** and
    ``returned`` stands alone: a durable row naming either would state a warrant it
    cannot show.

    A row whose ask returned more than
    :data:`~ai_assistant.core.types.MAX_EVIDENCE_RECORDS` keeps the **first 32** in
    the order the servicing produced them, and ``returned`` continues to carry the
    true count — so the truncation needs no second counter, because the figure that
    discloses it is the field beside it.

    Args:
        kind: What was read.
        records: The records the ask returned.

    Returns:
        The identifiers, or an empty tuple on an ephemeral kind.
    """
    if kind not in DURABLE_KINDS:
        return ()
    return tuple(record.id for record in records[:MAX_EVIDENCE_RECORDS])


def composed_row(  # noqa: PLR0913 — one parameter per thing a row is composed from: the two identifiers it belongs to, its own minted id, the servicing's typed outcome, the records that outcome returned, the count only the servicing holds, and the clock's instant; none is derivable from another
    *,
    row_id: str,
    goal_id: str,
    attempt_id: str,
    ask: ReadAsk,
    outcome: ReadOutcomeKind,
    records: Sequence[MemoryRecord],
    admitted: int,
    read_at: datetime,
) -> GoalEvidence:
    """Compose one ``READ_OUTCOME`` row from one outcome entry (ADR-0252 §14).

    **A completed servicing produces exactly one row per ask it reached that produced
    an outcome entry**, and "the member the entry carries decides the row's ``verdict``
    and decides nothing about whether the row is written": ``EMPTY``, ``DUPLICATE``,
    ``TRUNCATED``, ``REFUSED``, ``FAILED`` and ``EXPIRED`` are each recorded, with
    ``supported`` empty where no record came back. An ask in ADR-0251 §2's classifier
    case 1 produces no entry and therefore reaches this function not at all.

    **``orchestration`` writes every value and no model writes any of them** (§14):
    the id from the injected id factory, the instant from the injected clock, the
    applicabilities from the typed outcome, and the verdict from the closed vocabulary
    the classifier reached. A model sentence is never composed into ``requested``, into
    ``supported``, into ``verdict`` or into any field, and **no row is recorded on
    account of one**.

    **``source`` is absent on every row this decision's producers write** (§1). The
    five ``ReadKind`` members each name their own source, and the one shape that would
    carry a finer identity is a ``Reader``'s ``SourceReading.source``, whose producer
    is not built here. No lane fills it with a provider name, a host, an address, a
    path, a ``Settings`` field name or a credential identity.

    **The row is born ``STANDING``.** The two terminal members are marks a later write
    applies — a supersession rides on ``record_evidence`` and an invalidation on
    ``record_interpretation`` — and no member of ``PlanStore`` marks a row on its own.

    Args:
        row_id: The id the loop's injected factory minted for this row.
        goal_id: The goal whose history it belongs to.
        attempt_id: The attempt that recorded it.
        ask: The ask the planner emitted, byte for byte.
        outcome: What the classifier decided became of it (ADR-0251 §2).
        records: The records the ask returned, **before** ADR-0226 §7's deduplication.
        admitted: How many of those the supply did not already hold, which is
            ADR-0226 §9's ``new``.
        read_at: The instant this system performed the read, from the injected clock.

    Returns:
        The row to persist.
    """
    supported, supported_elided = supported_of(records)
    return GoalEvidence(
        id=row_id,
        goal_id=goal_id,
        attempt_id=attempt_id,
        basis=EvidenceBasis.READ_OUTCOME,
        read_kind=ask.kind,
        requested=requested_of(ask),
        supported=supported,
        supported_elided=supported_elided,
        read_at=read_at,
        as_of=as_of_of(ask.kind, records),
        records=records_of(ask.kind, records),
        returned=len(records),
        admitted=admitted,
        verdict=outcome.value,
        standing=EvidenceStanding.STANDING,
    )


def effective_instant(row: GoalEvidence) -> datetime:
    """A row's **effective instant**: its ``as_of`` where declared, else ``read_at``.

    ADR-0252 §8 limb 6 is stated over this instant and not over ``read_at`` alone,
    because it is the instant §6's recency test actually evaluates. Round 2 made the
    difference concrete: ``E`` read at 10:00 declaring ``as_of`` 09:59 and ``L`` read
    at 10:05 declaring ``as_of`` 08:00, otherwise matching and covering. On ``read_at``
    alone ``L`` supersedes ``E``, and a step requiring evidence read within fifteen
    minutes loses the row that satisfied it. **A supersession may never regress the
    effective recency instant.**

    Args:
        row: The row to key.

    Returns:
        The instant its recency is decided by.
    """
    return row.read_at if row.as_of is None else row.as_of


def affirmative(row: GoalEvidence) -> bool:
    """Whether a row's verdict is **affirmative** in ADR-0252 §5's sense.

    **Answering on the ``READ_OUTCOME`` basis**: one of the three members of
    :data:`ANSWERING`, which state that the source answered with records. The other
    four each state that no record came back at all, and a non-answering row satisfies
    nothing and refreshes nothing — which is the limb that protects the user, because
    without it "asking again and getting nothing" would silently retire the answer we
    had. The asymmetry is #2096 item 8's one level down: **a later read may confirm and
    displace, and may never retire by failing.**

    **Settling on the ``INTERPRETATION`` basis, which this tree cannot yet decide, so
    the answer is ``False``.** §5 fixes settling as "any member of its
    ``declaration``'s enumeration **other than** the does-not-settle member that
    enumeration always carries" — and which enumeration it is, and which member that
    is, are A5's and A7's. Nothing in the tree carries either, so the test is not
    evaluable and this function declines rather than guessing. **That costs nothing
    reachable**: §14 rules that no lane of ADR-0252 produces an ``INTERPRETATION`` row
    and §17 repeats it for both lanes, so no such row exists on any tree this function
    runs on; and declining is §8 limb 5's own fail-closed direction, which retires
    nothing. The lane that lands the vocabulary lands this limb with it (#2333).

    Args:
        row: The row to classify.

    Returns:
        Whether its verdict is affirmative.
    """
    if row.basis is not EvidenceBasis.READ_OUTCOME:
        return False
    return any(row.verdict == member.value for member in ANSWERING)


def refreshes(later: GoalEvidence, earlier: GoalEvidence) -> bool:
    """Whether ``later`` refreshes ``earlier``, on all six of §8's limbs.

    This is the owner's **correction 1** as a predicate — "Refreshed evidence needs
    supersession rules, so retained historical disagreements do not permanently block
    progress" — and **all six limbs must hold**:

    1. ``earlier`` is ``STANDING``;
    2. the two bases are equal;
    3. ``read_kind``, ``source`` and ``declaration`` are each equal, **absent counting
       as equal to absent and never to a present value** — which is what "the same
       source" means in this system, since every kind names its own source and
       ``source`` is absent on every row these producers write;
    4. both ``supported`` tuples are **non-empty** and ``later``'s **covers**
       ``earlier``'s;
    5. ``later``'s verdict is **affirmative**;
    6. ``later``'s **effective instant** is **strictly later** than ``earlier``'s.

    **Limb 4 is coverage and not overlap, and the difference is a user's evidence
    quietly disappearing.** A fresh read of Saturday *overlaps* a standing row
    supporting the whole week, and letting it supersede would retire the week row and
    take its Sunday support with it. Coverage runs the other way and only the other
    way: **a refresh may only retire what it can itself account for.**

    **Strictly later and not merely *not earlier*, because equal instants made the
    relation symmetric** — two rows sharing an effective instant each satisfied *not
    earlier than* the other, so which one superseded depended on the order a conforming
    implementation happened to evaluate them in. Strictness makes it a strict partial
    order and costs only the case of two readings the clock cannot tell apart, where
    leaving both standing is the honest record.

    **A row of a different goal is not tested here**: the store refuses one outright
    (§12), and :func:`refresh_set` is only ever handed one goal's history.

    Args:
        later: The row being written.
        earlier: A row of the same goal already in the history.

    Returns:
        Whether the earlier row is refreshed and therefore superseded.
    """
    return (
        earlier.standing is EvidenceStanding.STANDING
        and later.basis is earlier.basis
        and later.read_kind is earlier.read_kind
        and later.source == earlier.source
        and later.declaration == earlier.declaration
        and bool(later.supported)
        and support_covers_support(later.supported, earlier=earlier.supported)
        and affirmative(later)
        and effective_instant(later) > effective_instant(earlier)
    )


def refresh_set(row: GoalEvidence, history: Sequence[GoalEvidence]) -> tuple[str, ...]:
    """Which rows of this goal's history ``row`` refreshes (ADR-0252 §8, §12).

    **The predicate is ``orchestration``'s and the atomicity is the store's, and the
    split is deliberate** (§12): the loop computes *which* rows a new row refreshes and
    the store applies the marks it is given, because "a store that evaluated the refresh
    test would be a second place the rule lives, and the first conforming implementation
    to read it differently would be right in one of them".

    The result is ``record_evidence``'s ``supersedes`` argument, which marks each named
    row ``SUPERSEDED`` with ``superseded_by`` set to this row's id **in the same
    indivisible write** that appends it.

    **The row being written is never in the result.** §12 refuses a ``supersedes``
    naming it, and :func:`refreshes` would in any case fail limb 6 against itself.

    Args:
        row: The row being written.
        history: That goal's rows, in any order.

    Returns:
        The ids to supersede, in the order the history gave them.
    """
    return tuple(
        earlier.id for earlier in history if earlier.id != row.id and refreshes(row, earlier)
    )


def _instant(value: datetime | None) -> str:
    """One end of a rendered window: an ISO-8601 UTC instant, or nothing (§11).

    "A window's ends render as ISO-8601 UTC instants and an **unset end as the absence
    of that end**" — so an unbounded side renders as the empty slot it is rather than
    as a word, a sentinel or an invented bound. Both instants are already
    :data:`~ai_assistant.core.types.UtcInstant`, so the rendering states the offset the
    value carries and converts nothing.

    Args:
        value: The end, or ``None`` where it is unset.

    Returns:
        The instant, or the empty string.
    """
    return "" if value is None else value.isoformat()


def _counted(value: str) -> str:
    r"""One label value, rendered so that its own bytes can carry any delimiter.

    **The count is what makes the rendering unambiguous, and it is what lets the value
    stay byte for byte.** ADR-0252 §11 requires both at once — label values render
    "**byte for byte** in the order the region holds them", and a ``supported`` renders
    its regions "each delimited from the next … so that a reader can tell two regions
    from one" — and a bare delimiter cannot give both. Every label axis here carries
    **model-reachable text**: ``participants`` and ``about_person`` are
    :data:`~ai_assistant.core.types.NonBlankEncodableText`, which admits commas,
    semicolons, parentheses and newlines, and a ``TopicLabel`` admits every one of
    those but the newline (ADR-0213 §3 constrains case, length and whitespace runs and
    nothing else). So a value is free to *contain* the separators, and one region
    holding ``"x) (topics=y"`` would otherwise render exactly as two regions holding
    ``"x"`` and ``"y"`` — a **manufactured conjunction** arriving at the seam through
    the rendering, which is the failure §2's regions exist to prevent and §11 restates
    at the projection.

    The form is the netstring's, taken whole rather than invented: the value's **UTF-8
    byte length**, a colon, then the value's own bytes, unaltered. Escaping was the
    alternative and is refused: an escape rewrites the value, so ``"a,b"`` and
    ``"a\\,b"`` would reach the planner as one string, and §11's *byte for byte* would
    be false of exactly the values that need it.

    Args:
        value: The record's own value, untouched.

    Returns:
        Its counted rendering.
    """
    return f"{len(value.encode())}:{value}"


def rendered_region(region: EvidenceApplicability) -> str:
    """Render one region, deterministically and by field name (ADR-0252 §11).

    "An ``EvidenceApplicability`` renders as its **applied** axes in the model's own
    field order — window, participants, topics, about_person — each named by its field
    name; unapplied axes are omitted; … label values render **byte for byte** in the
    order the region holds them; and a non-zero ``elided`` renders as a count."

    **The region is delimited by parentheses and every label value is length-counted
    (**:func:`_counted`**), so that a reader can tell two regions from one whatever the
    values contain.** §11 requires regions to stay distinguishable on the seam, and the
    reason is stated there: a rendering that concatenated two regions' axes would show
    the planner one applicability spanning both, which is the manufactured conjunction
    §2 exists to prevent — arriving at the model, where it would be *worse*, because a
    model is exactly the reader that will reason from it. A delimiter alone does not
    give that, because the values are model-reachable text and may carry the delimiter.

    The window's ends and ``elided`` need no count: an
    :data:`~ai_assistant.core.types.UtcInstant` renders as ISO-8601 and a count as
    digits, neither of which a producer can put a delimiter into.

    **No model writes this rendering, no lane substitutes a prose summary for it, and
    no lane makes it configurable** (§11).

    Args:
        region: One applied region.

    Returns:
        Its rendering.
    """
    axes: list[str] = []
    if region.window is not None:
        axes.append(f"window=[{_instant(region.window.start)}, {_instant(region.window.end)})")
    for name, values in (
        ("participants", region.participants),
        ("topics", region.topics),
        ("about_person", region.about_person),
    ):
        if values is not None:
            axes.append(f"{name}={','.join(_counted(value) for value in values)}")
    if region.elided:
        axes.append(f"elided={region.elided}")
    return f"({'; '.join(axes)})"


def rendered_support(regions: Sequence[EvidenceApplicability], elided: int) -> str | None:
    """Render a ``supported`` tuple, or nothing where it is empty (§11).

    "A ``supported`` tuple renders as its regions **in order, each delimited from the
    next** … and a non-zero ``supported_elided`` renders as a count beside them."

    **An empty ``supported`` renders as an absent digest member**, which is what makes
    ADR-0249 §10's "an absent ``supported`` supports nothing" legible on the seam — a
    planner handed an empty rendering would have to be told, separately, that the empty
    string means *nothing was established*.

    Args:
        regions: The row's regions, in the order the servicing produced them.
        elided: How many the composition dropped.

    Returns:
        The rendering, or ``None`` where there are no regions.
    """
    if not regions:
        return None
    rendered = " ".join(rendered_region(region) for region in regions)
    return f"{rendered} supported_elided={elided}" if elided else rendered


def digest_of(row: GoalEvidence) -> EvidenceDigest:
    """Project one row into what the planner is told about it (ADR-0252 §11).

    Its six members are ADR-0249 §10's and this decision adds none: ``requested`` and
    ``supported`` are the rendering above, ``read_at``, ``as_of`` and ``standing`` are
    the row's own, and ``verdict`` is the row's ``verdict``.

    **The digest carries no identifier of any kind** — no evidence row id, no memory
    id, no snippet, no title and no address — and nor does it carry ``basis``,
    ``read_kind``, ``source``, ``declaration``, ``records``, ``returned``,
    ``admitted``, ``inapplicable_at_revision``, ``superseded_by``, or the row's goal or
    attempt. Those are the row's and the loop's, and the containment is a property of
    the type: "an implementation that rendered every field of every value it was
    handed, logged them all, or returned them, discloses none of those, because there
    is none on the value to disclose."

    **The planner is not told which rows satisfy anything.** No member says
    *sufficient*, *usable*, *fresh*, *covering* or *satisfied*; §6's four tests are
    evaluated by code at dispatch and their result crosses no seam.

    Args:
        row: The row to project.

    Returns:
        Its digest.
    """
    return EvidenceDigest(
        requested=None if row.requested is None else rendered_region(row.requested),
        supported=rendered_support(row.supported, row.supported_elided),
        read_at=row.read_at,
        as_of=row.as_of,
        verdict=row.verdict,
        standing=row.standing,
    )


def ordered_history(rows: Sequence[GoalEvidence]) -> tuple[GoalEvidence, ...]:
    """One goal's rows in §12's **total** order — ``read_at``, then ``id`` (§11, §12).

    ``evidence_of`` returns them in this order contractually, and this restates the key
    rather than the rule: it is the order the ``E`` label is an ordinal into, so a
    caller holding rows from anywhere else labels them the same way the store would.

    Args:
        rows: That goal's rows, in any order.

    Returns:
        The same rows, oldest first, ties broken by ``id`` ascending.
    """
    return tuple(sorted(rows, key=evidence_order))


def digests(rows: Sequence[GoalEvidence]) -> tuple[EvidenceDigest, ...]:
    """The ``evidence`` sequence ``Planner.plan`` is handed (ADR-0252 §11).

    **One ``EvidenceDigest`` per row of that goal's history the store holds**, in
    §12's total order, projected by ``orchestration`` alone.

    **Every row is projected, ``INAPPLICABLE`` and ``SUPERSEDED`` ones included**, and
    the digest's ``standing`` is what says which. ADR-0249 §10 put the member there for
    exactly this — "so that refreshed evidence has a way to state that it displaces an
    older disagreement rather than standing beside it forever" — and a sequence
    filtered to ``STANDING`` would make the member constant and the sentence false.

    **The sequence is bounded by construction and needs no second bound**: at most
    :data:`~ai_assistant.core.types.MAX_GOAL_EVIDENCE` rows exist per goal, and the
    elision that keeps it so is disclosed on ``EvidenceHistory.elided`` rather than
    being silent. So no lane truncates here and none reports a second count here.

    Args:
        rows: That goal's rows, in any order.

    Returns:
        The digests, in the order the ``E`` labels are ordinals into.
    """
    return tuple(digest_of(row) for row in ordered_history(rows))
