"""A synthetically aged store, and the oracle leg 7's retrieval instrument grades against.

This module is the fixture half of issue #789 — the exit instrument ADR-0112 §7
rules leg 7 owes before any lane makes a headroom change to retrieval. It builds
a ``MemoryStore`` population along the three axes ADR-0112 §8 names as the
pressure sources, and it supplies an independent ranking oracle so a measurement
can say *why* a search under-returned rather than only *that* it did.

**The axes.**

* **Live-record count** (:attr:`AgedStoreSpec.live`) — how much a store holds
  after months of use. Retrieval latency is measured against this.
* **Topical-cluster density** (:attr:`AgedStoreSpec.cluster_population`) — how
  many records crowd around one topic. Leg 3's observer mass-produces topically
  clustered ``OBSERVED``/``INFERRED`` records (ADR-0077), and it is crowding
  rather than raw volume that consumes ``search``'s over-fetch budget: a
  candidate is spent on a near neighbour whether or not it is servable.
* **The window-closed proportion** (:attr:`AgedStoreSpec.closed_fraction`) —
  records off the read path but still in the vector index, so they occupy KNN
  candidates and return nothing. There are **two producers** and this module
  plants both, because ADR-0112 §8 records that the pressure now grows with
  reconciliation as well as with correction:

  * :attr:`ClosedBy.SUPERSEDE` — every ``SUPERSEDE`` leaves the retired revision
    behind with its window closed (ADR-0045 §4, §6). A superseded revision is
    planted at its successor's own position, so it lands where the mechanism puts
    it: immediately beside the live record that replaced it.
  * :attr:`ClosedBy.ABSENCE` — ADR-0110 §3 closes an attested record's window
    when a covered reading it should have appeared in did not carry it. Such a
    record is ``EXTERNAL``-sourced with an attestation and a **bounded** window,
    since §3's condition 3 leaves an unbounded record undemotable.

**The oracle.** :meth:`AgedStore.rank` re-ranks the whole planted population in
Python against the same embedder the store was built with, so every measurement
has ground truth: which records are eligible for a query, how many ineligible
ones sit nearer than the last one a caller asked for
(:func:`filtered_neighbours` — the density k-shortfall is a function of), and how
many rows the store's KNN-then-filter arithmetic can serve
(:func:`served_prediction`). The oracle reads ``_RESULT_OVERFETCH`` and
``_VEC_KNN_MAX_K`` from the store module rather than restating them, so a lane
that raises the over-fetch is **re-measured** by this instrument rather than
failed by it.

Everything here is seeded and offline: :class:`ClusteredEmbedder` is a pure
function of the text, so the planted vectors are the stored vectors and the
oracle's ranking is the store's ranking.
"""

from __future__ import annotations

import hashlib
import math
import re
from array import array
from dataclasses import dataclass
from enum import StrEnum
from random import Random
from typing import TYPE_CHECKING, Protocol, cast

from ai_assistant.core.types import (
    Attestation,
    MemoryKind,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
    Validity,
)
from ai_assistant.memory.sqlite_store import _VEC_KNN_MAX_K

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    import pytest

    from ai_assistant.core.protocols import Embedder, MemoryStore
    from ai_assistant.core.types import Embedding, MemoryRecord

#: How many writes go into one ``write_atomic`` batch. Purely a build-time knob:
#: the batch is one transaction, and the store embeds before taking its lock, so
#: a larger batch trades peak memory for fewer commits.
_BATCH = 500

#: Vector width for the instrument's embedder. Wide enough that two topical
#: centroids are near-orthogonal, narrow enough that the largest profile's store
#: stays a manageable size on disk.
DIMENSIONS = 256

#: Non-zero components in a centroid and in a per-record direction. A centroid is
#: built from more of them so it dominates, which is what makes a topic a cluster
#: rather than a label.
_CENTROID_TERMS = 64
_DIRECTION_TERMS = 16

#: The only forms :meth:`ClusteredEmbedder._parse` accepts. Anchored and fully
#: numeric, so an ordinary word in a record's tail cannot be read as a topic.
_TOPIC_TOKEN = re.compile(r"t\d+")
_POSITION_TOKEN = re.compile(r"p\d+")

#: The topic ``AgedStoreSpec.closed_concentration`` piles retired records into —
#: the "well-corrected topic" ADR-0112 §8 describes, the one whose queries meet
#: the filtered nearer neighbours while the rest of the store looks healthy.
HOT_TOPIC = 0


def _as_stored(vector: Sequence[float]) -> tuple[float, ...]:
    """Round a vector to the ``float32`` precision ``sqlite-vec`` actually stores.

    ``sqlite_vec.serialize_float32`` narrows every component on the way in, so an
    oracle ranking ``float64`` components would be ranking vectors the store does
    not hold. Rounding here removes the larger half of the disagreement between
    the two rankings; what remains is accumulation order, which is why the
    instrument allows one row of slack at the candidate-budget boundary rather
    than none.
    """
    return tuple(array("f", vector))


def _terms(salt: str, key: str, count: int, width: int) -> tuple[tuple[int, float], ...]:
    """Derive ``count`` signed unit components from ``key``, deterministically.

    ``width`` is the caller's vector width and not :data:`DIMENSIONS`: reading the
    module constant here would place components outside any embedder built at a
    different width, which is an ``IndexError`` at embed time rather than a wrong
    answer, but only because the vector is a list.
    """
    digest = hashlib.shake_256(f"{salt}:{key}".encode()).digest(count * 3)
    return tuple(
        (
            int.from_bytes(digest[offset : offset + 2], "big") % width,
            1.0 if digest[offset + 2] & 1 else -1.0,
        )
        for offset in range(0, count * 3, 3)
    )


class ClusteredEmbedder:
    """A deterministic embedder that places each text near its topic's centroid.

    **Why not** ``HashingEmbedder``. It is a bag of words, so across a population
    drawn from one modest vocabulary its cosine distances take only a handful of
    distinct values and most records sit *exactly* equidistant from a query. A
    KNN's choice within a tie block is arbitrary, so no oracle can say which
    candidates the store spent its budget on — and an instrument that cannot
    predict its subject cannot attribute a shortfall to anything. Real sentence
    embeddings do not produce ties like that, so for this measurement the bespoke
    embedder is the *more* faithful stand-in, not the less.

    **The text is read as structure, not prose.** A ``t<n>`` token selects the
    topical centroid, a ``p<n>`` token selects the record's own direction inside
    that cluster, and the whole text adds a much smaller nudge. That is what lets
    the fixture put a superseded revision exactly where ``SUPERSEDE`` leaves one —
    same topic, same position, one nudge from its successor — rather than hoping a
    word overlap lands it there. A text with no ``p`` token (a query) takes its
    direction from the text itself.

    Vectors are unit length, so ``vec0``'s cosine distance is ``1 - dot`` and the
    oracle can compute it with one :func:`math.sumprod`.
    """

    def __init__(self, *, dimensions: int = DIMENSIONS, spread: float = 1.0) -> None:
        """Initialise the embedder.

        Args:
            dimensions: Vector width. Floored at :data:`_CENTROID_TERMS`, because
                a centroid drawn from that many components cannot be a *direction*
                in fewer buckets than it has terms — it collapses onto the ones it
                shares, and at the extreme every component of every vector lands
                in the same bucket, where a centroid and a position can cancel to
                the zero vector a cosine KNN has no answer for.
            spread: How far a record sits from its topic's centroid. Larger
                spreads loosen every cluster at once; it is the geometric half of
                the density axis, the other half being records per cluster.

        Raises:
            ValueError: If ``dimensions`` is below the floor or ``spread`` is
                negative.
        """
        # `spread < 0.0` is false for both a NaN and an infinity, so the finite
        # check is what actually refuses them; an infinite spread normalises to a
        # vector of NaNs, which ranks against nothing and fails no comparison.
        if dimensions < _CENTROID_TERMS or not math.isfinite(spread) or spread < 0.0:
            msg = (
                f"dimensions must be >= {_CENTROID_TERMS} and spread a finite value >= 0, "
                f"got {dimensions} and {spread}"
            )
            raise ValueError(msg)
        self._dimensions = dimensions
        self._spread = spread
        #: A nudge small enough that two texts sharing a position stay adjacent,
        #: and large enough to separate them well above ``float32`` resolution.
        self._nudge = 0.01
        self._centroids: dict[str, tuple[tuple[int, float], ...]] = {}

    @property
    def model_id(self) -> str:
        """A stable identifier for this embedder's (non-semantic) scheme."""
        return f"clustered-{self._dimensions}-{self._spread}"

    @property
    def dimensions(self) -> int:
        """The fixed length of the vectors this embedder produces."""
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        """Embed a batch of texts, returning one vector per input, in order."""
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        topic, position = self._parse(text)
        width = self._dimensions
        vector = [0.0] * width
        if topic not in self._centroids:
            self._centroids[topic] = _terms("centroid", topic, _CENTROID_TERMS, width)
        for index, sign in self._centroids[topic]:
            vector[index] += sign
        for index, sign in _terms("position", position, _DIRECTION_TERMS, width):
            vector[index] += sign * self._spread
        for index, sign in _terms("nudge", text, _DIRECTION_TERMS, width):
            vector[index] += sign * self._nudge
        norm = math.sqrt(math.sumprod(vector, vector))
        if norm == 0.0:
            # Reachable only where the width is small enough for the three
            # contributions to land in the same buckets and cancel. The width
            # floor makes it unreachable in practice; refusing rather than
            # returning the zero vector is what keeps that a *fact* instead of an
            # assumption, since a zero vector silently voids every distance the
            # oracle and the KNN compute from it.
            msg = f"embedding for {text!r} cancelled to the zero vector at width {width}"
            raise ValueError(msg)
        return [value / norm for value in vector]

    def _parse(self, text: str) -> tuple[str, str]:
        """Read the topic and position tokens, recognising only their complete forms.

        A prefix test let any later word beginning with ``t`` or ``p`` override
        them: ``"t1 p5 tail"`` read its topic as ``tail``, so records planted into
        different topics but ending in the same ordinary word would have shared a
        centroid and quietly collapsed the very density axis they were planted to
        vary. The planted tails (``u``/``a``/``s`` plus digits) never triggered it,
        which is why no measurement was wrong — and why nothing caught it either.
        The first match wins, so a stray token is inert rather than authoritative.
        """
        topic = ""
        position = ""
        for token in text.split():
            if not topic and _TOPIC_TOKEN.fullmatch(token):
                topic = token
            elif not position and _POSITION_TOKEN.fullmatch(token):
                position = token
        return topic, position or text


def _closed_count(live: int, closed_fraction: float) -> int:
    """Window-closed records accompanying ``live`` at ``closed_fraction`` of the whole.

    One owner for the derivation, so :meth:`AgedStoreSpec.sized` searches for a
    live count using exactly the arithmetic :attr:`AgedStoreSpec.closed` will
    later apply, rather than a second copy of it that could drift.
    """
    return round(live * closed_fraction / (1.0 - closed_fraction))


class ClosedBy(StrEnum):
    """Which producer closed a planted record's validity window."""

    SUPERSEDE = "supersede"
    ABSENCE = "absence"


@dataclass(frozen=True)
class AgedStoreSpec:
    """The three aging axes, plus the knobs that make a run reproducible.

    Attributes:
        live: How many records are live at the measurement instant.
        topics: How many topical clusters the population spreads across.
        closed_fraction: The share of the **whole** planted population whose
            validity window is closed; ``0.0`` is a store nothing has retired.
        absence_share: Of the closed records, the share closed by ADR-0110 §3's
            absence rule rather than by ``SUPERSEDE``.
        closed_concentration: Of the closed records, the share planted into
            :data:`HOT_TOPIC` rather than dealt round-robin. ``0.0`` retires a
            store evenly; higher values model the case ADR-0112 §8 actually
            describes, where one *well-corrected* topic accumulates the retired
            revisions while the rest of the store does not.
        preference_share: The share of records that are ``PREFERENCE`` rather
            than ``SEMANTIC``, so a ``kinds``-filtered search has something to
            filter out.
        seed: Seeds the kind draw; the same seed plants the same store.
    """

    live: int
    topics: int
    closed_fraction: float = 0.0
    absence_share: float = 0.5
    closed_concentration: float = 0.0
    preference_share: float = 0.5
    seed: int = 789

    def __post_init__(self) -> None:
        """Reject a spec that cannot be planted, rather than planting something else."""
        if self.live < 1 or self.topics < 1:
            msg = f"live and topics must both be >= 1, got {self.live} and {self.topics}"
            raise ValueError(msg)
        for name in ("closed_fraction", "absence_share", "preference_share"):
            value = cast("float", getattr(self, name))
            if not 0.0 <= value < 1.0:
                msg = f"{name} must be in [0.0, 1.0), got {value}"
                raise ValueError(msg)
        if not 0.0 <= self.closed_concentration <= 1.0:
            msg = f"closed_concentration must be in [0.0, 1.0], got {self.closed_concentration}"
            raise ValueError(msg)

    @classmethod
    def sized(  # noqa: PLR0913 — one keyword per axis, which is the point of the constructor
        cls,
        *,
        total: int,
        crowding: int,
        closed_fraction: float,
        closed_concentration: float = 0.0,
        preference_share: float = 0.5,
        seed: int = 789,
    ) -> AgedStoreSpec:
        """Build a spec from the *whole* population rather than from its live part.

        The handle a sweep needs when it varies ``closed_fraction`` while holding
        the KNN's candidate pool still, so the only thing moving between
        configurations is the share of that pool a query cannot be served from.

        Args:
            total: Every planted record, live and window-closed.
            crowding: Records per topical cluster, closed ones included — the
                crowding a query actually meets, since a closed record occupies a
                KNN candidate exactly as a live one does.
            closed_fraction: The share of ``total`` whose window is closed.
            closed_concentration: Passed through.
            preference_share: Passed through.
            seed: Passed through.

        Raises:
            ValueError: If ``total`` or ``crowding`` is below one — ``crowding=0``
                otherwise reached an unwrapped ``ZeroDivisionError`` and a negative
                one silently collapsed the store to a single topic, which is a
                *different* density from the one asked for and would be reported
                under the requested label. Also if the requested combination
                leaves no live record, or if
                the population it yields is not the one asked for. ``closed`` is
                derived from ``live`` and the fraction, so a ``live`` clamped up to
                1 would silently re-inflate ``total`` — a
                ``total=2000, closed_fraction=0.9999`` request became a
                **10,000**-record store, which is exactly the wrong volume to
                report a sweep against. Refusing is the only honest answer,
                because the caller's stated ``total`` cannot be met.
        """
        if total < 1 or crowding < 1:
            msg = f"total and crowding must both be >= 1, got {total} and {crowding}"
            raise ValueError(msg)
        estimate = round(total * (1.0 - closed_fraction))
        if estimate < 1:
            msg = (
                f"a {total}-record population with {closed_fraction} closed leaves no live "
                f"record; raise total or lower closed_fraction"
            )
            raise ValueError(msg)
        # Two roundings compose — `live` from the fraction, `closed` from `live` —
        # so inverting the first one is not enough to land on `total`. Search the
        # live counts either side of the estimate for one whose derivation is
        # exact, and refuse rather than return a near miss under the requested
        # label: at `total=3, closed_fraction=0.5` no live count works, and a
        # 4-record store answering a 3-record request is the wrong volume however
        # small the error.
        live = next(
            (
                candidate
                for candidate in (estimate, estimate - 1, estimate + 1, estimate - 2, estimate + 2)
                if candidate >= 1 and candidate + _closed_count(candidate, closed_fraction) == total
            ),
            None,
        )
        if live is None:
            msg = (
                f"no live count yields exactly {total} records with {closed_fraction} closed; "
                f"the nearest is {estimate} live plus {_closed_count(estimate, closed_fraction)} "
                f"closed"
            )
            raise ValueError(msg)
        return cls(
            live=live,
            topics=max(1, total // crowding),
            closed_fraction=closed_fraction,
            closed_concentration=closed_concentration,
            preference_share=preference_share,
            seed=seed,
        )

    @property
    def cluster_density(self) -> float:
        """Live records per topical cluster."""
        return self.live / self.topics

    @property
    def cluster_population(self) -> float:
        """Records per topical cluster, window-closed ones included."""
        return self.total / self.topics

    @property
    def closed(self) -> int:
        """How many window-closed records the spec's proportion implies."""
        return _closed_count(self.live, self.closed_fraction)

    @property
    def total(self) -> int:
        """Every planted record, live or window-closed — the KNN's candidate pool."""
        return self.live + self.closed


@dataclass(frozen=True)
class Draft:
    """One record's ingredients, held apart from the record so a batch can embed once."""

    record_id: str
    topic: int
    position: int
    tail: str
    kind: MemoryKind
    provenance: Provenance
    validity: Validity
    closed_by: ClosedBy | None

    @property
    def content(self) -> str:
        """The record's canonical text: its topic, its position in that topic, its own tail."""
        return f"t{self.topic} p{self.position} {self.tail}"


@dataclass(frozen=True)
class Planted:
    """One planted record with the vector the store will hold for it."""

    record: MemoryRecord
    vector: tuple[float, ...]
    topic: int
    closed_by: ClosedBy | None


@dataclass(frozen=True)
class Ranked:
    """One record's standing against a query, as the oracle sees it."""

    record_id: str
    distance: float
    eligible: bool


@dataclass(frozen=True)
class Instants:
    """The instants a planted population is dated against.

    Attributes:
        now: The measurement instant; the store's injected clock reads this.
        written: When the system last revised a planted belief.
        closed: Where a closed window ends — strictly before ``now``, so
            :meth:`~ai_assistant.core.types.Validity.live_at` is false.
        opened: Where an absence-closed record's **bounded** window starts, which
            ADR-0110 §3's condition 3 requires it to have.
    """

    now: datetime
    written: datetime
    closed: datetime
    opened: datetime

    def __post_init__(self) -> None:
        """Refuse a timeline on which a record this fixture calls closed is still live.

        The ordering is the fixture's whole premise, and getting it wrong fails
        *silently*: with ``closed`` after ``now``, every record planted as
        ``SUPERSEDE`` or ``ABSENCE`` is still live at the measurement instant, so
        the population reports a window-closed proportion that consumes no KNN
        candidates at all — the instrument would publish a shortfall rate against
        a store that was never aged. Nothing downstream would notice: the census
        counts what was *labelled*, and ``search`` would simply serve rows.

        **Awareness is checked before the ordering, and only so the ordering can
        run.** Comparing a naive instant with an aware one is a ``TypeError`` in
        Python, so deferring the check to ``checked_clock`` and ``UtcInstant`` —
        which own whether an instant is *acceptable*, downstream of here — would
        mean the comparison below raised first, with a message about offsets
        rather than about the timeline. This check makes no judgement those two
        do not; it establishes the precondition its own comparisons need.

        Raises:
            ValueError: If any instant is naive, or if they are not ordered
                ``opened < closed <= now`` with ``written <= now``.
        """
        naive = sorted(
            name
            for name in ("now", "written", "closed", "opened")
            if cast("datetime", getattr(self, name)).tzinfo is None
        )
        if naive:
            msg = f"every instant must be timezone-aware; {', '.join(naive)} is not"
            raise ValueError(msg)
        if not self.opened < self.closed:
            msg = f"opened must precede closed, got {self.opened} and {self.closed}"
            raise ValueError(msg)
        if not self.closed <= self.now:
            msg = (
                f"closed must not be after now ({self.closed} > {self.now}); a window closing "
                f"in the future leaves every 'closed' record live at the measurement instant"
            )
            raise ValueError(msg)
        if not self.written <= self.now:
            msg = f"written must not be after now, got {self.written} and {self.now}"
            raise ValueError(msg)


class _LineWriter(Protocol):
    """The one method this module needs from pytest's terminal reporter."""

    def write_line(self, line: str, **markup: bool) -> None:
        """Write one line straight to the terminal, outside pytest's capture."""


def report(config: pytest.Config, lines: Sequence[str]) -> None:
    """Write measurement rows to the terminal, past pytest's output capture.

    A measurement whose numbers surface only on failure is not an instrument, so
    the rows go to the terminal reporter rather than to ``print``. A session
    running without one (``-p no:terminal``) simply gets no rows.
    """
    writer = cast("_LineWriter | None", config.pluginmanager.get_plugin("terminalreporter"))
    if writer is None:
        return
    for line in lines:
        writer.write_line(line)


def _provenance(*, source: MemorySource, when: datetime, reported_at: datetime) -> Provenance:
    """Build provenance for one planted record, attesting only where the band demands it."""
    attested = source is MemorySource.EXTERNAL
    return Provenance(
        source=source,
        confidence=0.6,
        last_updated=when,
        attestation=(
            Attestation(reported_by="the user's calendar", reported_at=reported_at)
            if attested
            else None
        ),
    )


def _materialise(draft: Draft) -> MemoryRecord:
    """Turn a draft into the typed record its kind calls for."""
    content = draft.content
    if draft.kind is MemoryKind.PREFERENCE:
        return PreferenceMemory(
            id=draft.record_id,
            content=content,
            preference=content,
            provenance=draft.provenance,
            validity=draft.validity,
        )
    return SemanticMemory(
        id=draft.record_id,
        content=content,
        fact=content,
        provenance=draft.provenance,
        validity=draft.validity,
    )


@dataclass(frozen=True)
class AgedStore:
    """A planted population, the instants it is dated against, and the oracle over it."""

    spec: AgedStoreSpec
    instants: Instants
    planted: tuple[Planted, ...]
    embedder: Embedder

    def topic_query(self, topic: int) -> str:
        """The canonical query text for one topical cluster.

        It carries the topic token and no position token, so it lands at the
        cluster's centroid rather than on any planted record.
        """
        return f"t{topic % self.spec.topics} query"

    def census(self) -> dict[str, int]:
        """Count what was actually planted, per producer and per live kind."""
        counts = {
            "total": len(self.planted),
            "live": sum(1 for p in self.planted if p.closed_by is None),
            "closed_supersede": sum(1 for p in self.planted if p.closed_by is ClosedBy.SUPERSEDE),
            "closed_absence": sum(1 for p in self.planted if p.closed_by is ClosedBy.ABSENCE),
        }
        for kind in (MemoryKind.SEMANTIC, MemoryKind.PREFERENCE):
            counts[f"live_{kind.value}"] = sum(
                1 for p in self.planted if p.closed_by is None and p.record.kind == kind.value
            )
        return counts

    async def rank(
        self, query: str, *, kinds: Sequence[MemoryKind] | None = None
    ) -> tuple[Ranked, ...]:
        """Rank every planted record against ``query``, nearest first.

        The oracle the store's answers are graded against: cosine distance over
        the same vectors the store holds, plus the eligibility predicate
        ``search`` applies *after* its KNN — the ``kinds`` filter, retention, and
        both ends of the validity window (ADR-0045 §6).
        """
        wanted = None if kinds is None else frozenset(str(kind) for kind in kinds)
        (raw,) = await self.embedder.embed([query])
        query_vector = _as_stored(raw)
        scored = [
            Ranked(
                record_id=p.record.id,
                distance=1.0 - math.sumprod(query_vector, p.vector),
                eligible=self._eligible(p, wanted),
            )
            for p in self.planted
        ]
        scored.sort(key=lambda entry: (entry.distance, entry.record_id))
        return tuple(scored)

    def _eligible(self, planted: Planted, wanted: frozenset[str] | None) -> bool:
        record = planted.record
        if wanted is not None and record.kind not in wanted:
            return False
        if record.expires_at is not None and record.expires_at <= self.instants.now:
            return False
        return record.validity.live_at(self.instants.now)


def eligible_total(ranked: Sequence[Ranked]) -> int:
    """How many records in the whole population a query is entitled to."""
    return sum(1 for entry in ranked if entry.eligible)


def filtered_neighbours(ranked: Sequence[Ranked], *, limit: int) -> int:
    """Ineligible records ranked nearer than the ``limit``-th eligible one.

    The independent variable the k-shortfall **used to be** a function of, kept
    because it is what says a measurement was taken under pressure rather than on a
    clean store. ``search`` once dropped these *after* the KNN had already spent a
    candidate on each, so this count was what the over-fetch budget competed with;
    since ADR-0128 §1 the KNN never sees them, and the instrument's job is to
    report how high this went while service stayed complete. Where fewer than
    ``limit`` eligible records exist at all, every ineligible record is counted.
    """
    seen = 0
    ineligible = 0
    for entry in ranked:
        if entry.eligible:
            seen += 1
            if seen == limit:
                return ineligible
        else:
            ineligible += 1
    return ineligible


def candidate_budget(limit: int) -> int:
    """The ``fetch_k`` ``SqliteMemoryStore._search_sync`` spends for ``limit``.

    Since ADR-0128 §1 that is ``limit`` itself, clamped to sqlite-vec's ``k``
    ceiling: every candidate the KNN returns is eligible, so there is nothing an
    over-fetch could buy. Read from the store module rather than restated, so a
    lane that moves the ceiling (#411 part 2) re-measures through this instrument
    instead of being failed by it.
    """
    return min(limit, _VEC_KNN_MAX_K)


def served_prediction(ranked: Sequence[Ranked], *, limit: int) -> int:
    """How many rows the store can serve.

    Since ADR-0128 §1 this is the caller's entitlement and nothing else: every
    candidate the KNN returns is eligible, so the store serves the ``limit``
    nearest eligible records, bounded only by how many exist and by its own
    candidate ceiling. A k-shortfall would be this coming out below
    ``min(limit, eligible_total(ranked))`` — which after §1 can only happen at the
    ceiling, where ``search`` also reports ``capped``.

    **It no longer depends on the ranking's arithmetic**, which is why
    ``boundary_is_ambiguous`` is gone with it: the old prediction counted eligible
    survivors inside a candidate prefix, so two records either side of the budget
    could swap under ``float32`` and change the count. The count here is a
    ``min`` of three integers, so the oracle and the store cannot disagree about it
    at all, and a row of slack would only have absolved a real regression. Which
    *records* fill the page is still float-sensitive at the cut, and
    ``_measured_search`` grades that against the eligible ranking's distances.
    """
    return min(limit, eligible_total(ranked), _VEC_KNN_MAX_K)


def _live_drafts(spec: AgedStoreSpec, rng: Random, instants: Instants) -> list[Draft]:
    """Draft the live population, dealt round-robin across the topics."""
    drafts: list[Draft] = []
    for index in range(spec.live):
        preference = rng.random() < spec.preference_share
        drafts.append(
            Draft(
                record_id=f"live-{index}",
                topic=index % spec.topics,
                position=index,
                tail=f"u{index}",
                kind=MemoryKind.PREFERENCE if preference else MemoryKind.SEMANTIC,
                provenance=_provenance(
                    source=MemorySource.INFERRED if preference else MemorySource.OBSERVED,
                    when=instants.written,
                    reported_at=instants.written,
                ),
                validity=Validity(),
                closed_by=None,
            )
        )
    return drafts


def _absence_draft(index: int, topic: int, *, kind: MemoryKind, at: Instants, live: int) -> Draft:
    """One record ADR-0110 §3's absence rule closed: attested, bounded window, own position."""
    return Draft(
        record_id=f"closed-{index}",
        topic=topic,
        position=live + index,
        tail=f"a{index}",
        kind=kind,
        provenance=_provenance(
            source=MemorySource.EXTERNAL, when=at.written, reported_at=at.opened
        ),
        validity=Validity(valid_from=at.opened, valid_until=at.closed),
        closed_by=ClosedBy.ABSENCE,
    )


def _supersede_draft(index: int, successor: Draft, *, kind: MemoryKind, at: Instants) -> Draft:
    """One revision a ``SUPERSEDE`` retired, at the position of the record that replaced it."""
    return Draft(
        record_id=f"closed-{index}",
        topic=successor.topic,
        position=successor.position,
        tail=f"s{index}",
        kind=kind,
        provenance=_provenance(
            source=MemorySource.OBSERVED, when=at.written, reported_at=at.written
        ),
        validity=Validity(valid_until=at.closed),
        closed_by=ClosedBy.SUPERSEDE,
    )


def _closed_drafts(
    spec: AgedStoreSpec, rng: Random, live: Sequence[Draft], instants: Instants
) -> list[Draft]:
    """Draft the window-closed population, split between ADR-0112 §8's two producers.

    A superseded revision takes its successor's topic *and position*, because that
    is where ``SUPERSEDE`` actually leaves one — immediately beside the record that
    replaced it (ADR-0045 §4). An absence-closed record takes a position of its
    own, carries an attestation, and gets the bounded window ADR-0110 §3 requires
    before an absence may close anything.

    ``closed_concentration`` decides *where* rather than *what*, and is drawn per
    record so it stays independent of the producer split: a concentrated record
    lands in :data:`HOT_TOPIC` (a superseded one taking its successor from that
    topic's live records), and the rest are dealt round-robin.
    """
    absences = round(spec.closed * spec.absence_share)
    hot = [draft for draft in live if draft.topic == HOT_TOPIC] or list(live)
    drafts: list[Draft] = []
    for index in range(spec.closed):
        kind = (
            MemoryKind.PREFERENCE if rng.random() < spec.preference_share else MemoryKind.SEMANTIC
        )
        concentrated = rng.random() < spec.closed_concentration
        if index < absences:
            topic = HOT_TOPIC if concentrated else index % spec.topics
            drafts.append(_absence_draft(index, topic, kind=kind, at=instants, live=spec.live))
            continue
        pool = hot if concentrated else live
        drafts.append(_supersede_draft(index, pool[index % len(pool)], kind=kind, at=instants))
    return drafts


async def plant(spec: AgedStoreSpec, *, embedder: Embedder, instants: Instants) -> AgedStore:
    """Build the planted population for ``spec``, embedded but not yet written anywhere."""
    rng = Random(spec.seed)  # noqa: S311 — a reproducible fixture, not a security draw
    live = _live_drafts(spec, rng, instants)
    drafts = [*live, *_closed_drafts(spec, rng, live, instants)]
    vectors = await embedder.embed([draft.content for draft in drafts])
    planted = tuple(
        Planted(
            record=_materialise(draft),
            vector=_as_stored(vector),
            topic=draft.topic,
            closed_by=draft.closed_by,
        )
        for draft, vector in zip(drafts, vectors, strict=True)
    )
    return AgedStore(spec=spec, instants=instants, planted=planted, embedder=embedder)


async def install(store: MemoryStore, aged: AgedStore) -> None:
    """Write a planted population into ``store``, batched into atomic writes."""
    writes = [
        MemoryWrite(record=p.record, mode=MemoryWriteMode.INSERT_IF_ABSENT) for p in aged.planted
    ]
    for start in range(0, len(writes), _BATCH):
        await store.write_atomic(writes[start : start + _BATCH])
