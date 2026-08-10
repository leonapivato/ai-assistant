"""The store-health census ADR-0129 defines: what the store holds at one instant.

**A census, not a measure** (§1). Every figure here is a count, a proportion of
counts, or a distribution of per-record quantities, taken over the memory store's
records as they stand at one instant ``T``. None is a rate over a window of
events, none is a measure of ADR-0120, and neither family may be substituted for
the other: a census looks at no future, so it needs no settling, and it has no
denominator drawn from a lossy stream. What it has instead is the property that
makes it worth building — the present state of a store is the accumulated residue
of every event since it was created, including events before any retained trace.

**``T`` is the instant this tool reads its own clock**, once per run, used for
every figure in it. It is not an operator parameter: the store keeps no history,
so classifying its *current* contents against a past instant would count a record
inserted since — which did not exist at ``T`` — while missing one deleted since,
which did. An implementation that needs a fixed ``T`` injects the clock.

**It reads the store's storage, not the store's read API**, and that is inherited
rather than chosen (§5). No ``MemoryStore`` member returns the population §3
counts: ``get``, ``search`` and ``walk_records`` each apply the lifecycle
predicate, and ``export`` applies its retention half, so the unpurged expired rows
this census exists to show are visible to the store's *writer* and to none of its
readers. Nor does any member return an embedding — and after ADR-0128 §1 no record
failing the validity window is even a ``search`` candidate, so a concentration
figure computed through ``search`` would report zero on every store in every
state.

**Nothing is embedded and no model is consulted** (§2). Every vector read here was
written by an earlier ingest or re-embed, so ADR-0104 §4's cloud refusal has no
question to answer: this tool sends nothing anywhere.

**It writes nothing** (§4). The connection is opened read-only, which makes that
mechanical rather than a promise — including ADR-0114's named walk cursors, which
a diagnostic that reached for ``walk_records`` and then called ``advance_walk``
would silently consume on behalf of whatever job owns the name.

**No figure carries a threshold, a target or a verdict, and none arms anything**
(§6). These figures are for an operator to read and rule on; the #824 re-ruling
took apart the last instrument that existed to fire something.

**The report prints no identifier and no content** (§7). Counts, proportions,
distributions, instants, ``kind`` and ``BeliefBand`` labels, and the run's stated
parameters — no record id, no ``about_person`` label, no content, and no embedding
or component of one. An embedding is a lossy projection of the content that
produced it, which is why it is named separately from the content rule.
"""

from __future__ import annotations

import hashlib
import heapq
import math
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import sqlite_vec

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import BeliefBand, band_of
from ai_assistant.memory.sqlite_store import _ADAPTER, _VEC_KNN_MAX_K

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import MemoryRecord

type _Format = Callable[[float], str]
"""How one figure of a :class:`Spread` is rendered — a decimal, or a duration."""

type _Row = tuple[Any, ...]
"""One row as ``sqlite3`` hands it over.

The driver types every column ``Any``, so naming that here keeps the alias honest
rather than asserting a shape the driver does not promise — the same reading
:mod:`ai_assistant.memory.reembed` takes of the same driver.
"""

__all__ = [
    "DEFAULT_K",
    "DEFAULT_SAMPLE",
    "StoreHealthReader",
    "StoreHealthReport",
]

#: How many candidate records a run samples for the concentration figure unless
#: the operator says otherwise. A default rather than a required argument because
#: — unlike ADR-0120 §1's settling period, which is *part of* its measure — this
#: number only decides how precisely the distribution is estimated, and the report
#: states which value was used either way (§3). What is actually useful is an
#: operating question the first real store will answer (§9).
DEFAULT_SAMPLE: Final = 500

#: How many nearest neighbours each sampled record's density is taken over.
DEFAULT_K: Final = 10

#: The largest ``k`` this tool can accept. §3 requires a positive integer and puts
#: no ceiling on it; the *backend* does, and a neighbourhood of ``k`` needs
#: ``k + 1`` from the KNN because the sampled record is its own nearest neighbour.
#: Refused up front rather than left to surface as a ``sqlite3`` error from the
#: middle of a run that has already taken the instance lock.
MAX_K: Final = _VEC_KNN_MAX_K - 1

#: How many rowids one ``IN`` list binds at a time.
_BIND_CHUNK: Final = 500

_ABSENT: Final = (
    "there is no memory store in this deployment's data directory yet, so there is "
    "nothing to take a census of. Nothing was created."
)
_EMPTY: Final = "the memory store holds no record. No figure is stated."
_UNDEFINED: Final = "undefined (the population is empty)"


def _utcnow() -> datetime:
    """The default clock, wrapped by :func:`checked_clock` wherever it is injected."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Share:
    """A count and the population it is a proportion of.

    §1 makes every proportion **undefined** over an empty population, and states
    that it is undefined rather than stating a figure or a zero — so this carries
    both counts and refuses to produce a value, which is what keeps the
    distinction alive all the way to the page. The reasoning is ADR-0120 §1's and
    it transfers whole: a zero asserts a proportion that was measured to be zero,
    an omitted line asserts nothing and is read as zero anyway, and an empty
    population is reachable in ordinary operation.

    Attributes:
        count: The count on top.
        total: The population it is a share of.
    """

    count: int
    total: int

    @property
    def defined(self) -> bool:
        """Whether the population was non-empty."""
        return self.total > 0

    @property
    def value(self) -> float | None:
        """The proportion, or ``None`` over an empty population."""
        return self.count / self.total if self.defined else None

    def rendered(self) -> str:
        """The proportion and its two counts, or the statement standing in for it."""
        value = self.value
        if value is None:
            return f"{_UNDEFINED}  ({self.count} of 0)"
        return f"{value:.4f}  ({self.count} of {self.total})"


@dataclass(frozen=True, slots=True)
class Spread:
    """A distribution of per-record quantities, summarised.

    Summarised rather than listed because the per-record figures run to thousands
    of lines on a real store — and because a *mean alone* is the figure #799's
    finding specifically rules out: an evenly-aged store and a store with a few
    catastrophically crowded topics can share a mean, and the difference between
    them is the whole question. The quartiles are here for the same reason the
    distribution is: a heavy right tail is what topic-concentrated closure looks
    like, and it is invisible in a centre.

    Attributes:
        count: How many observations the summary is over.
        minimum: The smallest, or ``None`` over an empty population.
        lower_quartile: The 25th percentile, under the same condition.
        median: The middle, under the same condition.
        upper_quartile: The 75th percentile, under the same condition.
        maximum: The largest, under the same condition.
        mean: The arithmetic mean, under the same condition.
    """

    count: int
    minimum: float | None
    lower_quartile: float | None
    median: float | None
    upper_quartile: float | None
    maximum: float | None
    mean: float | None

    @classmethod
    def over(cls, sample: Sequence[float]) -> Spread:
        """Summarise ``sample``, which may be empty.

        Args:
            sample: The observations.

        Returns:
            The summary; every figure is ``None`` over an empty sample, which §1
            makes undefined rather than zero.
        """
        if not sample:
            return cls(
                count=0,
                minimum=None,
                lower_quartile=None,
                median=None,
                upper_quartile=None,
                maximum=None,
                mean=None,
            )
        ordered = sorted(sample)
        return cls(
            count=len(ordered),
            minimum=ordered[0],
            lower_quartile=_percentile(ordered, 0.25),
            median=_percentile(ordered, 0.5),
            upper_quartile=_percentile(ordered, 0.75),
            maximum=ordered[-1],
            mean=statistics.fmean(ordered),
        )

    @property
    def defined(self) -> bool:
        """Whether the population was non-empty."""
        return self.count > 0

    def rendered(self, *, places: int = 4) -> str:
        """The summary on one line, or the statement that the population is empty.

        Args:
            places: How many decimal places each figure carries.

        Returns:
            The line.
        """
        return self._rendered(lambda value: f"{value:.{places}f}")

    def rendered_intervals(self) -> str:
        """The same summary, read as durations in seconds."""
        return self._rendered(lambda value: str(timedelta(seconds=round(value))))

    def _rendered(self, form: _Format) -> str:
        """Render every figure through ``form``, or say the population is empty."""
        figures = (
            ("min", self.minimum),
            ("p25", self.lower_quartile),
            ("median", self.median),
            ("p75", self.upper_quartile),
            ("max", self.maximum),
            ("mean", self.mean),
        )
        if not self.defined or any(figure is None for _, figure in figures):
            return _UNDEFINED
        stated = "  ".join(
            f"{label} {form(figure)}" for label, figure in figures if figure is not None
        )
        return f"n={self.count}  {stated}"


@dataclass(frozen=True, slots=True)
class Census:
    """§3's closure census over one population: the total and the four counts.

    Liveness and expiry are separate axes and a record may be both, so these four
    do not partition the total and their proportions are not obliged to sum to
    one. A window that is closed *and* not yet open is admissible too, which is
    why retired and not-yet-live are counted apart rather than derived from each
    other.

    Attributes:
        total: Every record in the population.
        live: ``Validity.live_at(T)`` holds.
        retired: ``valid_until`` is set and at or before ``T``.
        not_yet_live: ``valid_from`` is set and after ``T``.
        expired: ``expires_at`` is set and at or before ``T`` — a row
            ``purge_expired`` has not yet removed, which is still a row in the
            scan, in the backup and in a re-embed.
    """

    total: int
    live: int
    retired: int
    not_yet_live: int
    expired: int

    @property
    def live_share(self) -> Share:
        """The live count as a proportion of the total."""
        return Share(count=self.live, total=self.total)

    @property
    def retired_share(self) -> Share:
        """The retired count as a proportion of the total."""
        return Share(count=self.retired, total=self.total)

    @property
    def not_yet_live_share(self) -> Share:
        """The not-yet-live count as a proportion of the total."""
        return Share(count=self.not_yet_live, total=self.total)

    @property
    def expired_share(self) -> Share:
        """The expired count as a proportion of the total."""
        return Share(count=self.expired, total=self.total)


@dataclass(frozen=True, slots=True)
class BandFill:
    """§3's band fill for one :class:`~ai_assistant.core.types.BeliefBand`.

    Taken as ``band_of`` of the record's ``provenance.source``, which is `core`'s
    own total function over the single classifier ADR-0072 §4 keeps — so the
    census and the store cannot disagree about which band a record is in.

    Attributes:
        band: The band.
        live: Records of the census population live at ``T``.
        not_live: The rest of them.
    """

    band: BeliefBand
    live: int
    not_live: int

    @property
    def total(self) -> int:
        """Every record of the census population in this band."""
        return self.live + self.not_live


@dataclass(frozen=True, slots=True)
class Concentration:
    """§3's neighbourhood closure density distribution, and what it is read against.

    Each evaluated record's density is the count of its ``k`` nearest neighbours —
    by the store's own distance metric, among the whole candidate set, excluding
    the record itself, live or not — that are **not** live at ``T``, divided by
    ``k``. :attr:`not_live` is the null it is read against: if closure were spread
    evenly through the geometry, a live record's neighbourhood would contain
    non-live records at about the candidate set's own proportion. The null is
    approximate by construction — a neighbourhood excludes the sampled record and
    is drawn from ``k`` nearest rather than uniformly — so the figure is a
    comparison and never a test statistic, which is what §6 requires of it anyway.

    Attributes:
        k: The neighbourhood size, the same for every sampled record in the run.
        requested: The sample size asked for.
        candidates: Every census record the store holds a vector for. The
            neighbourhood is drawn from this set, so it is what the ``k + 1``
            domain rule is stated over.
        sample: How many candidates were actually selected — the whole candidate
            set where it is smaller than what was asked for.
        evaluated: Those of them live at ``T``. A number much below
            :attr:`sample` is a store whose vector-bearing records are mostly
            retired, which is the census's finding arriving a second time.
        density: The distribution over the evaluated sample.
        not_live: The proportion of the candidate set not live at ``T``.
    """

    k: int
    requested: int
    candidates: int
    sample: int
    evaluated: int
    density: Spread
    not_live: Share

    @property
    def defined(self) -> bool:
        """Whether the candidate set holds at least ``k + 1`` records.

        A domain rule, not §1's empty-population rule, and the two do not overlap:
        a store holding one live vector-bearing record supplies an evaluated
        sample of *one*, whose single neighbourhood is empty because the record
        itself is excluded. Every reading of that case is wrong — ``0 ÷ k`` reports
        "no closure nearby" from a store with no neighbourhood at all, and dropping
        the record silently shrinks a sample whose size the report has stated. The
        condition is uniform across records, so one store-wide test settles it and
        the figure is either taken over full neighbourhoods or not taken.
        """
        return self.candidates >= self.k + 1


@dataclass(frozen=True, slots=True)
class StoreHealthReport:
    """One run of the census: either a statement about the store, or the figures.

    Attributes:
        statement: Why no figure was computed — the store's file does not exist,
            or it holds no record — or ``None``. Neither is a failure: a
            deployment that has never run the hub has written nothing, and
            opening a database to discover that would create the very thing being
            asked about.
        read_at: ``T``, the instant the tool read its own clock, or ``None``
            alongside a statement.
        census: §3's closure census store-wide, or ``None``.
        by_kind: The same census decomposed by ``kind``, in label order.
        without_vector: How many census records the store holds no vector for.
            Stated separately from every other count because a record with no
            vector enters the census, the closure age and the band fill and leaves
            the density figure's population — so this is what lets a reader tell
            "the geometry is healthy" from "the geometry was mostly not read".
        concentration: §3's density distribution, or ``None``.
        closure_age: Over every record retired at ``T``, the interval in seconds
            from its ``valid_until`` to ``T``. A store whose retirements are all
            recent is being actively corrected; one whose retirements are old has
            settled. Not a correction *count*: no field links a retired record to
            the record that replaced it, so a per-belief lineage is not computable
            from the store and is not invented here.
        bands: §3's band fill, in band order.
    """

    statement: str | None = None
    read_at: datetime | None = None
    census: Census | None = None
    by_kind: tuple[tuple[str, Census], ...] = ()
    without_vector: int = 0
    concentration: Concentration | None = None
    closure_age: Spread | None = None
    bands: tuple[BandFill, ...] = ()

    def render(self) -> str:
        """The whole report as text the entry point prints.

        §9 leaves the output format to this lane. §7 bounds its content, and the
        bound is why no store path appears below: the clause enumerates what the
        output carries, and a path is not among the counts, proportions,
        distributions, instants, labels and stated parameters it lists. The entry
        point, which owns §4's contention diagnostic, is where an operator is told
        which file was read.

        Returns:
            The report, without a trailing newline.
        """
        if self.statement is not None:
            return self.statement
        if self.census is None or self.concentration is None or self.closure_age is None:
            # Unreachable: the three travel together out of `_figures`. Stated as
            # a refusal rather than an assertion because a half-built report is a
            # thing to report, not to crash on.
            return "the census did not complete and no figure is stated."
        return "\n".join(
            [
                *self._heading(),
                "",
                *_census_lines(self.census, self.by_kind, self.without_vector),
                "",
                *_concentration_lines(self.concentration),
                "",
                *_age_lines(self.closure_age),
                "",
                *_band_lines(self.bands),
            ]
        )

    def _heading(self) -> list[str]:
        """``T``, the run's parameters, and what the numbers are not."""
        parameters = (
            f"sample {self.concentration.requested}, k {self.concentration.k}"
            if self.concentration is not None
            else "none"
        )
        return [
            f"store health census at {self.read_at:%Y-%m-%dT%H:%M:%S%z}  ({parameters})",
            "every figure is a count of the store's state at that instant (ADR-0129). None is",
            "a rate over a window and none is a measure of ADR-0120, so none of them may be",
            "read beside one as though the two were the same kind of number. None carries a",
            "threshold, a target or a verdict.",
        ]


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    """The nearest-rank ``fraction`` percentile of a sorted, non-empty sample.

    Nearest-rank rather than interpolated, so every figure the report states is a
    value some record actually took, and so all three quantiles come from one
    rule. ``statistics.quantiles`` interpolates and needs two points, which would
    leave the quartiles undefined on a single-observation sample while the median
    beside them was not.

    **``ceil(fraction * n) - 1``, and the obvious ``int(fraction * n)`` is wrong**
    — ``tests/memory/test_aged_store_retrieval.py``'s own ``_percentile`` records
    the failure it produced: at 20 observations a reported "p95" came out as the
    largest one, which overstates the tail and makes the figure something other
    than what it is labelled. Overstating a tail is exactly the direction this
    report must not err in, since the tail is the concentration signal.

    Args:
        ordered: The sample, sorted ascending and non-empty.
        fraction: Where in it to read, in ``[0, 1]``.

    Returns:
        The observation at that rank.
    """
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _census_lines(
    census: Census, by_kind: Sequence[tuple[str, Census]], without_vector: int
) -> list[str]:
    """The closure census, store-wide and by kind."""
    lines = [
        "census — every record physically present, whatever its lifecycle state",
        f"  records                        {census.total}",
        f"  live at T                      {census.live_share.rendered()}",
        f"  retired at T                   {census.retired_share.rendered()}",
        f"  not yet live at T              {census.not_yet_live_share.rendered()}",
        f"  expired at T, not yet purged   {census.expired_share.rendered()}",
        f"  no vector stored               {without_vector}",
        "  by kind                        total / live / retired / not-yet-live / expired",
    ]
    lines += [
        f"    {kind:<28} {part.total} / {part.live} / {part.retired}"
        f" / {part.not_yet_live} / {part.expired}"
        for kind, part in by_kind
    ]
    return lines


def _concentration_lines(concentration: Concentration) -> list[str]:
    """The density distribution, or the statement that its domain is not met."""
    lines = [
        "neighbourhood closure density — the share of each live sampled record's k",
        "nearest neighbours, among every record the store holds a vector for, that is",
        "not live at T",
        f"  candidate set                  {concentration.candidates}",
        f"  k                              {concentration.k}",
    ]
    if not concentration.defined:
        lines.append(
            f"  density                        undefined: the candidate set holds "
            f"{concentration.candidates} records and a neighbourhood of {concentration.k} "
            f"needs {concentration.k + 1}"
        )
        return lines
    lines += [
        f"  sample                         {concentration.sample} (asked for "
        f"{concentration.requested})",
        f"  evaluated sample               {concentration.evaluated}",
        f"  density                        {concentration.density.rendered()}",
        f"  candidate set not live at T    {concentration.not_live.rendered()}",
        "    — the value the distribution sits on if closure is spread evenly rather",
        "      than concentrated. Approximate, and a comparison rather than a test.",
    ]
    return lines


def _age_lines(closure_age: Spread) -> list[str]:
    """The closure-age distribution, over every record retired at ``T``."""
    return [
        "closure age — from each retired record's valid_until to T",
        f"  age                            {closure_age.rendered_intervals()}",
    ]


def _band_lines(bands: Sequence[BandFill]) -> list[str]:
    """The band fill, one line per band."""
    return [
        "band fill — the census population by the band its provenance source places it in",
        *(f"  {band.band.value:<30} live {band.live} / not live {band.not_live}" for band in bands),
    ]


class StoreHealthReader:
    """The census's mechanism: open the store read-only, count, close (ADR-0129 §5).

    Shaped after :class:`~ai_assistant.memory.reembed.Reembedder`, which §5 names
    as the exact precedent — an offline tool living in ``memory/``, reading the
    same schema, built by the composition root and driven by an entry point in
    ``service/``. This one is strictly simpler than the tool it copies:
    ``build_reembedder`` exists partly to hold ADR-0104 §4's cloud refusal, and
    this reader has nothing to refuse because it embeds nothing.

    The composition root constructs it
    (:func:`~ai_assistant.app.build_store_health_reader`), because ``service`` may
    not name a ``memory`` type and this package may not import ``service``.
    """

    def __init__(self, *, store: Path, now: Clock = _utcnow) -> None:
        """Point the reader at a memory store.

        Args:
            store: ``<data_dir>/memory.db``. Not opened here: a reader that opened
                it on construction would create an empty database as a side effect
                of a deployment that has never run the hub asking what is in it.
            now: The clock ``T`` is read from, once per run (§1). Injected rather
                than exposed as an option, which is the corpus's standing pattern
                (`core/clock.py`) and the only way a test can fix ``T`` — §1 gives
                the tool no ``T`` parameter to pass, because the store keeps no
                history for a past ``T`` to be a census of.
        """
        self._store = Path(store)
        self._now = checked_clock(now, owner="StoreHealthReader")

    @property
    def store(self) -> Path:
        """Where the memory store is, whether or not it exists yet."""
        return self._store

    def report(self, *, sample: int = DEFAULT_SAMPLE, k: int = DEFAULT_K) -> StoreHealthReport:
        """Take the census.

        Synchronous, unlike its two sibling offline tools, because there is
        nothing here to await: the trace reader's mechanism goes through
        ``TraceStore.walk`` and the re-embedder awaits an ``Embedder``, while this
        one issues SQL against a file and consults nothing else. An ``async def``
        with no ``await`` in it would claim a concurrency this has no use for.

        Args:
            sample: How many candidate records the concentration figure is taken
                over. Stated on the report (§3).
            k: The neighbourhood size. Stated on the report (§3).

        Returns:
            The figures, or the statement standing in for them over an absent or
            empty store.

        Raises:
            MemoryStoreError: If ``sample`` or ``k`` is outside its domain, or the
                store cannot be opened or read.
        """
        _require_domain(sample=sample, k=k)
        if not self._store.is_file():
            # §4: not a failure, and opening the database to find out would create
            # the very thing being asked about.
            return StoreHealthReport(statement=_ABSENT)
        # Read once, before anything is opened, and used for every figure below.
        read_at = self._now()
        conn = _connect(self._store)
        try:
            return _figures(conn, read_at=read_at, sample=sample, k=k)
        finally:
            conn.close()


def _require_domain(*, sample: int, k: int) -> None:
    """Refuse a run whose parameters no figure could be taken under (§3).

    ``k`` positive is §3's own clause, and its reason is arithmetic: a ``k`` of
    zero makes the denominator zero on every record in every store. The ceiling is
    the backend's rather than the ADR's, and refusing here — before the instance
    lock has bought anything — is what keeps it from surfacing as a ``sqlite3``
    error from the middle of a run.

    Args:
        sample: The requested sample size.
        k: The requested neighbourhood size.

    Raises:
        MemoryStoreError: If either is outside its domain.
    """
    if k < 1:
        msg = f"k must be a positive integer, got {k}: a density over {k} neighbours has no value"
        raise MemoryStoreError(msg)
    if k > MAX_K:
        msg = (
            f"k must be at most {MAX_K}: a neighbourhood of k needs k + 1 from the vector "
            f"index, whose own ceiling is {_VEC_KNN_MAX_K}; got {k}"
        )
        raise MemoryStoreError(msg)
    if sample < 1:
        msg = f"the sample must be at least one record, got {sample}"
        raise MemoryStoreError(msg)


def _connect(store: Path) -> sqlite3.Connection:
    """Open ``store`` **read-only**, with ``sqlite-vec`` loaded.

    Read-only is how §4's second clause is enforced rather than promised: a
    connection that cannot write cannot add, update, delete or purge a record, and
    cannot advance one of ADR-0114's named walk cursors either. It also leaves no
    rollback journal beside the store, so a census cannot be mistaken later for a
    process that died holding the file.

    Args:
        store: The memory store, which must exist.

    Returns:
        The open connection.

    Raises:
        MemoryStoreError: If the store cannot be opened or the vector extension
            cannot be loaded.
    """
    try:
        conn = sqlite3.connect(
            f"{store.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None
        )
    except (sqlite3.Error, OSError, ValueError) as exc:
        msg = f"failed to open {str(store)!r} for reading: {exc}"
        raise MemoryStoreError(msg) from exc
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (sqlite3.Error, OSError) as exc:
        conn.close()
        msg = f"failed to load the vector extension for {str(store)!r}: {exc}"
        raise MemoryStoreError(msg) from exc
    return conn


def _decode(data: object, rowid: object) -> MemoryRecord:
    """Decode one stored record, naming the row when it will not decode.

    The blob is the truth and the derived columns beside it are an index
    (``SqliteMemoryStore._migrate_records``), so every classification here is made
    from the decoded model — ``Validity.live_at`` at ``T``, ``expires_at``, and
    ``band_of`` the provenance source. That is one predicate with one owner rather
    than a second SQL transcription of it that could drift from `core`'s.

    Args:
        data: The stored JSON.
        rowid: Which row it came from, for the diagnostic. Not a record id, and
            never rendered into the report (§7).

    Returns:
        The record.

    Raises:
        MemoryStoreError: If the stored JSON is not a valid record.
    """
    try:
        return _ADAPTER.validate_json(str(data))
    except Exception as exc:
        msg = f"the record stored at row {rowid!r} could not be decoded: {exc}"
        raise MemoryStoreError(msg) from exc


def _query(conn: sqlite3.Connection, sql: str, parameters: Sequence[object] = ()) -> list[_Row]:
    """Run one read, translating a backend failure into this seam's error.

    Args:
        conn: The open connection.
        sql: A statement assembled from module literals only.
        parameters: Bound values.

    Returns:
        The rows.

    Raises:
        MemoryStoreError: If the read fails.
    """
    try:
        return [tuple(row) for row in conn.execute(sql, parameters)]
    except sqlite3.Error as exc:
        msg = f"failed to read the memory store: {exc}"
        raise MemoryStoreError(msg) from exc


def _stream_records(conn: sqlite3.Connection) -> Iterator[tuple[int, str, object]]:
    """Yield every record row in ``rowid`` order, so the store is never materialised.

    A census over a store with months of records must not need the whole store in
    memory at once — which is one of the three things §5 records as wrong with
    computing this figure family through ``MemoryStore.export``.

    Raises:
        MemoryStoreError: If the store cannot be read.
    """
    try:
        for rowid, record_id, data in conn.execute(
            "SELECT rowid, id, data FROM records ORDER BY rowid"
        ):
            yield int(rowid), str(record_id), data
    except sqlite3.Error as exc:
        msg = f"failed to read the memory store's records: {exc}"
        raise MemoryStoreError(msg) from exc


@dataclass(frozen=True, slots=True, order=True)
class _Candidate:
    """One member of the sample, with the key it was selected on.

    Ordered, because ordering a heap of these **is** the selection rule.
    ``digest`` and ``record_id`` lead for that reason; ``record_id`` is unique in
    the schema, so a comparison never reaches the two fields after it and their
    order is never load-bearing.
    """

    digest: bytes
    record_id: str
    rowid: int
    live: bool


class _Tally:
    """Accumulates every figure's population in one pass over the records."""

    def __init__(self, read_at: datetime, *, sample: int) -> None:
        """Start an empty tally against ``T``."""
        self._at = read_at
        self._sample = sample
        self.total = 0
        self.live = 0
        self.retired = 0
        self.not_yet_live = 0
        self.expired = 0
        self.without_vector = 0
        self.candidates = 0
        self.candidates_not_live = 0
        self.kinds: dict[str, list[int]] = {}
        self.bands: dict[BeliefBand, list[int]] = {}
        self.ages: list[float] = []
        #: A min-heap of at most ``sample`` candidates, so the tally holds the
        #: sample rather than the candidate set. What survives is the ``sample``
        #: **largest** digests — a hash cut, one of the three mechanisms §3 names,
        #: and a deterministic function of the candidate set and the parameters
        #: alone. It cannot depend on ``T``: a sampler drawing from the records
        #: live at ``T`` would change its draw as the day moved, and two censuses
        #: of an unchanged store would then differ for two reasons at once.
        self._heap: list[_Candidate] = []

    def add(self, *, rowid: int, record_id: str, record: MemoryRecord, has_vector: bool) -> None:
        """Fold one record into every population it belongs to."""
        validity = record.validity
        live = validity.live_at(self._at)
        retired = validity.valid_until is not None and validity.valid_until <= self._at
        not_yet = validity.valid_from is not None and validity.valid_from > self._at
        expired = record.expires_at is not None and record.expires_at <= self._at

        self.total += 1
        self.live += live
        self.retired += retired
        self.not_yet_live += not_yet
        self.expired += expired
        counts = self.kinds.setdefault(record.kind, [0, 0, 0, 0, 0])
        for index, flag in enumerate((True, live, retired, not_yet, expired)):
            counts[index] += flag
        band = self.bands.setdefault(band_of(record.provenance.source), [0, 0])
        band[0 if live else 1] += 1
        if retired and validity.valid_until is not None:
            self.ages.append((self._at - validity.valid_until).total_seconds())
        if not has_vector:
            self.without_vector += 1
            return
        self.candidates += 1
        self.candidates_not_live += not live
        self._offer(
            _Candidate(digest=_digest(record_id), record_id=record_id, rowid=rowid, live=live)
        )

    def _offer(self, candidate: _Candidate) -> None:
        """Keep ``candidate`` if it is among the ``sample`` largest digests so far."""
        if len(self._heap) < self._sample:
            heapq.heappush(self._heap, candidate)
        else:
            heapq.heappushpop(self._heap, candidate)

    def sample(self) -> list[_Candidate]:
        """The selected sample, in the deterministic order it was selected by."""
        return sorted(self._heap)

    def census(self) -> Census:
        """§3's closure census store-wide."""
        return Census(
            total=self.total,
            live=self.live,
            retired=self.retired,
            not_yet_live=self.not_yet_live,
            expired=self.expired,
        )

    def by_kind(self) -> tuple[tuple[str, Census], ...]:
        """The same census per ``kind`` label, in label order."""
        return tuple(
            (
                kind,
                Census(
                    total=counts[0],
                    live=counts[1],
                    retired=counts[2],
                    not_yet_live=counts[3],
                    expired=counts[4],
                ),
            )
            for kind, counts in sorted(self.kinds.items())
        )

    def band_fill(self) -> tuple[BandFill, ...]:
        """§3's band fill, in band order and only for the bands present."""
        return tuple(
            BandFill(band=band, live=counts[0], not_live=counts[1])
            for band, counts in sorted(self.bands.items(), key=lambda item: item[0].value)
        )


def _digest(record_id: str) -> bytes:
    """The sampling key for one record id.

    A hash of the id rather than a stride over it, because a stride over sorted
    ids samples whatever the id scheme happens to correlate with — and the ids a
    store holds are minted by several different writers. The hash is
    content-independent of everything but the id, never rendered (§7), and fixed
    for the life of this module: changing it would silently move every sample.
    """
    return hashlib.blake2b(record_id.encode(), digest_size=16).digest()


def _figures(
    conn: sqlite3.Connection, *, read_at: datetime, sample: int, k: int
) -> StoreHealthReport:
    """Read the whole store once and form every figure from it.

    The vector table's ``rowid`` set is held whole and the records are streamed
    past it, which is the asymmetry the two tables allow: the set is one integer
    per vector, where the record stream is the content, the provenance and the
    windows of every belief the store holds. Nothing here materialises the
    latter — one of the three things §5 records as wrong with taking this census
    through ``MemoryStore.export``, which "returns the whole store in a single
    ``list[MemoryRecord]``".
    """
    vectors = {int(rowid) for (rowid,) in _query(conn, "SELECT rowid FROM vec_records")}
    tally = _Tally(read_at, sample=sample)
    for rowid, record_id, data in _stream_records(conn):
        tally.add(
            rowid=rowid,
            record_id=record_id,
            record=_decode(data, rowid),
            has_vector=rowid in vectors,
        )
    if tally.total == 0:
        # §4: a store with nothing in it is a stated output, not a figure of zero
        # and not an exception.
        return StoreHealthReport(statement=_EMPTY)
    return StoreHealthReport(
        read_at=read_at,
        census=tally.census(),
        by_kind=tally.by_kind(),
        without_vector=tally.without_vector,
        concentration=_concentration(conn, tally, read_at=read_at, sample=sample, k=k),
        closure_age=Spread.over(tally.ages),
        bands=tally.band_fill(),
    )


def _concentration(
    conn: sqlite3.Connection, tally: _Tally, *, read_at: datetime, sample: int, k: int
) -> Concentration:
    """§3's density distribution over the evaluated sample.

    The sample is selected from the candidate set and the evaluated sample is
    those of its members live at ``T`` — two steps rather than one, because
    drawing from the live records would make the *draw* move with the clock, and
    two censuses of an unchanged store would then differ for two reasons at once:
    the records whose windows lapsed, and the records the sampler happened to
    pick. Drawn this way, a record's closure shows up where it belongs, as one
    member leaving the evaluated sample.
    """
    selected = tally.sample()
    evaluated = [candidate for candidate in selected if candidate.live]
    liveness: dict[int, bool] = {}
    domain_met = tally.candidates >= k + 1
    densities = (
        [
            _density(conn, candidate, read_at=read_at, k=k, liveness=liveness)
            for candidate in evaluated
        ]
        if domain_met
        else []
    )
    return Concentration(
        k=k,
        requested=sample,
        candidates=tally.candidates,
        sample=len(selected),
        evaluated=len(evaluated),
        density=Spread.over(densities),
        not_live=Share(count=tally.candidates_not_live, total=tally.candidates),
    )


def _density(
    conn: sqlite3.Connection,
    candidate: _Candidate,
    *,
    read_at: datetime,
    k: int,
    liveness: dict[int, bool],
) -> float:
    """One record's neighbourhood closure density.

    The record's own stored vector is the query, so nothing is embedded (§2). The
    neighbourhood is drawn from the whole candidate set, which is why the
    ``rowid IN`` clause is there: ``vec_records`` is joined to ``records`` by
    ``rowid`` with no foreign key, so an orphan vector is possible and is not a
    census record. The sampled record itself is excluded, which is why ``k + 1``
    are asked for and one is dropped.

    Raises:
        MemoryStoreError: If the store cannot be read, or the index returns fewer
            neighbours than the candidate count says it holds. §3 admits no
            density taken over fewer than ``k``, so a short neighbourhood is
            reported rather than averaged over.
    """
    rows = _query(conn, "SELECT embedding FROM vec_records WHERE rowid = ?", (candidate.rowid,))
    if not rows:
        msg = f"row {candidate.rowid} lost its vector while the census was being taken"
        raise MemoryStoreError(msg)
    neighbours = _query(
        conn,
        "SELECT v.rowid FROM vec_records v "
        "WHERE v.embedding MATCH ? AND k = ? "
        "AND v.rowid IN (SELECT rowid FROM records) "
        "ORDER BY v.distance",
        (rows[0][0], k + 1),
    )
    others = [int(rowid) for (rowid,) in neighbours if int(rowid) != candidate.rowid][:k]
    if len(others) < k:
        msg = (
            f"the vector index returned {len(others)} neighbours for a record whose candidate "
            f"set holds at least {k + 1}; the store's records and vectors disagree"
        )
        raise MemoryStoreError(msg)
    _load_liveness(conn, others, read_at=read_at, liveness=liveness)
    return sum(1 for rowid in others if not liveness[rowid]) / k


def _load_liveness(
    conn: sqlite3.Connection,
    rowids: Sequence[int],
    *,
    read_at: datetime,
    liveness: dict[int, bool],
) -> None:
    """Fill ``liveness`` for every row of ``rowids`` it does not already hold.

    Cached across the whole run because neighbourhoods overlap heavily in exactly
    the store this figure is looking for — a concentrated topic is a set of records
    that are each other's neighbours.

    Read in chunks because ``k`` may be as large as :data:`MAX_K` and SQLite bounds
    how many parameters one statement may bind. The current bound is far above
    that, so this is insurance against a build with an older one rather than a
    limit anybody will meet.

    Raises:
        MemoryStoreError: If a neighbour's row cannot be read or decoded.
    """
    wanted = sorted({rowid for rowid in rowids if rowid not in liveness})
    for start in range(0, len(wanted), _BIND_CHUNK):
        chunk = wanted[start : start + _BIND_CHUNK]
        # Only a placeholder count is interpolated; every value is bound.
        sql = f"SELECT rowid, data FROM records WHERE rowid IN ({', '.join('?' * len(chunk))})"  # noqa: S608
        for rowid, data in _query(conn, sql, chunk):
            liveness[int(rowid)] = _decode(data, rowid).validity.live_at(read_at)
    missing = [rowid for rowid in wanted if rowid not in liveness]
    if missing:
        msg = f"{len(missing)} neighbours named by the vector index have no record row"
        raise MemoryStoreError(msg)
