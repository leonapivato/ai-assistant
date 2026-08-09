"""Reading the stream: the walk, the attribution index, and ADR-0120 §2's tests.

Everything here is about deciding what a single trace *is* — eligible, malformed,
counter-inconsistent, attributed to a user seam or to a machine one — and about
the one thing that cannot be decided from a single trace: which operation caused
a write.

**Two passes, because an operation trace lands after the writes it encloses**
(ADR-0120 §3). "An ``OPERATION`` trace is emitted *after* the work it wraps, so
every ``MEMORY_WRITE`` it encloses precedes it in insertion order. A single
forward pass therefore meets writes before their operation." §3 leaves the number
of passes open and fixes only the answer; this takes the second walk, which is
well defined because the store is append-only and the walk resumes from the floor.
The hub is stopped while the tool runs (§9), so the two passes see the same
stream.

**The walk is the only member of the contract this package's reader touches**
(§9). No emit, no purge, no resolution of an id against another store (§10).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    TraceKind,
    TraceRecordSet,
    TraceRef,
)
from ai_assistant.evaluation._vocabulary import (
    CANDIDATES,
    COUNT_KEYS,
    DECISION_KEYS,
    EXCLUSION_KEYS,
    FETCH_K,
    LIMIT,
    MACHINE_SEAMS,
    RETRIEVAL_COUNT_KEYS,
    RETURNED,
    USER_SEAMS,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping
    from datetime import datetime, timedelta

    from ai_assistant.core.protocols import TraceStore
    from ai_assistant.core.types import EvaluationTrace, TraceMetricValue


class SeamClass(StrEnum):
    """Which of ADR-0120 §3's two seam sets an operation's seam is on.

    A third answer — *unclassified* — is the absence of a member rather than a
    member, because §3 makes it a count the report states and names, never a
    bucket a measure is computed over.
    """

    USER = "user"
    MACHINE = "machine"


#: How many traces one :meth:`~ai_assistant.core.protocols.TraceStore.walk` call
#: asks for. A read of numbers and ids over a stopped hub, so the figure trades
#: nothing an operator can feel; it is here rather than a parameter because §9
#: gives the tool no tuning surface.
CHUNK: Final = 512


async def walk(store: TraceStore) -> AsyncIterator[tuple[int, EvaluationTrace]]:
    """Yield every retained trace with its ordinal in the store's insertion order.

    The ordinal is what ADR-0120 §1's ``t ≺ u`` is decided on: "the order
    :meth:`TraceStore.walk` returns and the only total order the stream has".
    It is derived from the enumeration rather than from the opaque
    :class:`~ai_assistant.core.types.TracePosition`, which ADR-0114 §2 forbids a
    caller to parse, order or compare.

    The loop stops on an **empty** chunk rather than on a short one. A short chunk
    means "nothing further is present yet" and never "this walk is over", and
    while the hub is stopped the two coincide — costing one extra query to say so
    with the contract's own words instead of an assumption about writers.

    Args:
        store: The trace store, offline and unwritten-to.

    Yields:
        ``(ordinal, trace)`` pairs, ordinals counting from zero.
    """
    position = None
    ordinal = 0
    while True:
        chunk = await store.walk(after=position, limit=CHUNK)
        if not chunk.traces:
            return
        for trace in chunk.traces:
            yield ordinal, trace
            ordinal += 1
        position = chunk.position


@dataclass(frozen=True, slots=True)
class Configuration:
    """One ``CONFIGURATION`` trace, as ADR-0120 §8 reads it.

    Attributes:
        occurred_at: When the hub started.
        changed: Whether this trace's metric mapping differs from that of the
            preceding ``CONFIGURATION`` trace in the stream. The first one in the
            stream has no predecessor to differ from and is ``False``: it
            partitions nothing, because there is no earlier configuration for the
            window to have been under.
        gap: The interval from the preceding trace **of any kind** in the
            retained stream, or ``None`` where there is none. §8 states it as an
            *upper bound* on how long the hub was not running, never as the
            downtime itself.
    """

    occurred_at: datetime
    changed: bool
    gap: timedelta | None


@dataclass(frozen=True, slots=True)
class Extent:
    """What the retained stream spans, and where its last append landed.

    Attributes:
        oldest: The earliest ``occurred_at`` retained. ADR-0120 §8 refuses a
            window that starts before it.
        newest: The latest ``occurred_at`` retained.
        last: The ``occurred_at`` of the **last trace in insertion order**, which
            is the instant §4's settling condition names. It is at or before
            :attr:`newest` by construction, so testing the settling against it
            satisfies §4's clause exactly and is never weaker than §8's, which
            names the newest instead. Where the two differ — a slow sink landing
            an earlier instant last — the stricter of the two is the one that
            withholds a figure, which is the direction every other clause of this
            ADR takes.
        traces: How many traces the walk saw.
    """

    oldest: datetime
    newest: datetime
    last: datetime
    traces: int


@dataclass(frozen=True, slots=True)
class Index:
    """What one pass over the whole stream establishes about it.

    Attributes:
        extent: The stream's span, or ``None`` when the stream is empty.
        seam_of: Correlation identifier to the seam of the **unique**
            ``OPERATION`` trace carrying it. A correlation carried by two
            operation traces has no unique one and is absent, which leaves the
            writes under it unattributed — the conservative reading of §3's
            "the unique ``OPERATION`` trace".
        configurations: Every ``CONFIGURATION`` trace in the retained stream, in
            insertion order.
    """

    extent: Extent | None
    seam_of: Mapping[str, str]
    configurations: tuple[Configuration, ...]


async def index(store: TraceStore) -> Index:
    """Walk the whole stream once and build what the second pass needs.

    Attribution is resolved over the **whole retained stream and not over the
    window** (§3): "a write inside the window whose operation trace falls outside
    it is attributed normally". So is the configuration history, because §8
    partitions on a diff against the preceding configuration trace whether or not
    that one is inside the window.

    Args:
        store: The trace store.

    Returns:
        The index.

    Raises:
        TraceStoreError: If the store cannot be read.
    """
    builder = _IndexBuilder()
    async for _, trace in walk(store):
        builder.add(trace)
    return builder.build()


class _IndexBuilder:
    """Accumulates :class:`Index` across the first pass."""

    def __init__(self) -> None:
        self._oldest: datetime | None = None
        self._newest: datetime | None = None
        self._last: datetime | None = None
        self._traces = 0
        #: ``None`` marks a correlation carried by more than one operation trace.
        self._seams: dict[str, str | None] = {}
        self._configurations: list[Configuration] = []
        self._previous: datetime | None = None
        self._previous_metrics: Mapping[str, TraceMetricValue] | None = None

    def add(self, trace: EvaluationTrace) -> None:
        """Fold one trace into the accumulators."""
        self._traces += 1
        instant = trace.occurred_at
        self._oldest = instant if self._oldest is None else min(self._oldest, instant)
        self._newest = instant if self._newest is None else max(self._newest, instant)
        self._last = instant
        if trace.kind is TraceKind.OPERATION:
            self._record_operation(trace)
        elif trace.kind is TraceKind.CONFIGURATION:
            self._record_configuration(trace)
        self._previous = instant

    def _record_operation(self, trace: EvaluationTrace) -> None:
        """Bind this operation's correlation to its seam, or mark it non-unique."""
        correlation = trace.refs.get(TraceRef.CORRELATION)
        if correlation is None:
            return
        self._seams[correlation] = None if correlation in self._seams else trace.seam

    def _record_configuration(self, trace: EvaluationTrace) -> None:
        """Record the startup stamp, and whether it moved the effective figures."""
        metrics = dict(trace.metrics)
        changed = self._previous_metrics is not None and metrics != self._previous_metrics
        gap = None if self._previous is None else trace.occurred_at - self._previous
        self._configurations.append(
            Configuration(occurred_at=trace.occurred_at, changed=changed, gap=gap)
        )
        self._previous_metrics = metrics

    def build(self) -> Index:
        """Freeze the accumulators."""
        extent = None
        if self._oldest is not None and self._newest is not None and self._last is not None:
            extent = Extent(
                oldest=self._oldest,
                newest=self._newest,
                last=self._last,
                traces=self._traces,
            )
        return Index(
            extent=extent,
            seam_of={key: seam for key, seam in self._seams.items() if seam is not None},
            configurations=tuple(self._configurations),
        )


def is_count(value: TraceMetricValue) -> bool:
    """Whether ``value`` is a count ADR-0120 §2 admits.

    "A non-negative integer that is not a ``bool``." ``bool`` is excluded by name
    because it *is* an ``int`` in Python, "so a ``True`` slipping into a count
    would satisfy an integrality test while meaning something else entirely".

    Args:
        value: The metric value as stored.

    Returns:
        Whether it may be read as a count.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_malformed(trace: EvaluationTrace) -> bool:
    """Whether ADR-0120 §2 puts this trace outside every population.

    Two conditions, and both are named rather than assumed away. A trace carrying
    a **strict, non-empty subset** of the six decision keys reports rulings it
    cannot account for; a trace carrying any count key as a fractional, negative
    or boolean value carries a value no emitter in this tree can write, "so the
    record it sits on is not one to trust for anything".

    Args:
        trace: The trace.

    Returns:
        Whether it is malformed.
    """
    present = sum(1 for key in DECISION_KEYS if key in trace.metrics)
    if 0 < present < len(DECISION_KEYS):
        return True
    return any(key in trace.metrics and not is_count(trace.metrics[key]) for key in COUNT_KEYS)


def counts(trace: EvaluationTrace, keys: tuple[str, ...]) -> dict[str, int] | None:
    """Every key's value as an ``int``, or ``None`` when one is missing.

    Callers reach this only for traces :func:`is_malformed` already cleared, so a
    present key is a valid count and the narrowing cast is sound.

    Args:
        trace: The trace.
        keys: The keys that must all be present.

    Returns:
        The values, or ``None`` if any key is absent.
    """
    if any(key not in trace.metrics for key in keys):
        return None
    return {key: int(trace.metrics[key]) for key in keys}


def is_counter_inconsistent(read: Mapping[str, int]) -> bool:
    """Whether ADR-0120 §2's five joint conditions fail on a retrieval's counts.

    Each of the eight counts "can be individually valid and jointly impossible",
    and §7 divides by a difference of two of them. The partition equality is
    asserted only where ``returned < limit``, because ``_search_sync``'s filter
    loop breaks the moment the page fills — on a read that filled it the counters
    describe the prefix the loop examined and are not a partition (§2, §7).

    Args:
        read: The eight counts, as :func:`counts` returned them.

    Returns:
        Whether the trace leaves §7's population.
    """
    if read[LIMIT] <= 0 or read[FETCH_K] <= 0:
        return True
    if read[RETURNED] > read[CANDIDATES] or read[CANDIDATES] > read[FETCH_K]:
        return True
    if read[RETURNED] >= read[LIMIT]:
        return False
    partitioned = read[RETURNED] + sum(read[key] for key in EXCLUSION_KEYS)
    return partitioned != read[CANDIDATES]


def retrieval_counts(trace: EvaluationTrace) -> dict[str, int] | None:
    """The eight counts §7 reads, or ``None`` when the trace carries fewer.

    Args:
        trace: A ``RETRIEVAL`` trace already cleared by :func:`is_malformed`.

    Returns:
        The counts, or ``None``.
    """
    return counts(trace, RETRIEVAL_COUNT_KEYS)


def joinable(trace: EvaluationTrace, key: TraceRecordSet) -> tuple[str, ...] | None:
    """The ids under ``key``, or ``None`` where this trace may not be joined on it.

    ADR-0120 §2: a set is joinable exactly when it is present and **not
    truncated** — ``total == len(ids)``. "A truncated set excludes its trace from
    a population joining on that set and from no other", so this is asked per set
    rather than per trace.

    Args:
        trace: The trace.
        key: Which disposition's ids are wanted.

    Returns:
        The ids, or ``None`` when the set is absent or truncated.
    """
    recorded = trace.records.get(key)
    if recorded is None or recorded.total != len(recorded.ids):
        return None
    return tuple(recorded.ids)


def truncates_a_joined_set(trace: EvaluationTrace) -> bool:
    """Whether a set this ADR joins on is present on ``trace`` and truncated.

    The three joined sets are ``RETURNED`` (§4's surfacings) and ``SUPERSEDED``
    and ``RETIRED`` (§4's candidates). ``WRITTEN`` and ``REINFORCED`` are read by
    no join — §4 is explicit that a supersession's freshly-minted ``WRITTEN`` id
    "is not an overturn and must not be counted" — so a truncation there costs
    nothing and is not reported as an exclusion.

    Args:
        trace: The trace.

    Returns:
        Whether §2 excluded it from a population for truncation.
    """
    joined = (TraceRecordSet.RETURNED, TraceRecordSet.SUPERSEDED, TraceRecordSet.RETIRED)
    return any(
        (recorded := trace.records.get(key)) is not None and recorded.total != len(recorded.ids)
        for key in joined
    )


def attribution(trace: EvaluationTrace, seam_of: Mapping[str, str]) -> str | None:
    """The seam of the operation that caused this write, or ``None``.

    ADR-0120 §3: "A write whose ``refs`` lacks ``CORRELATION``, or whose
    correlation matches no retained ``OPERATION`` trace, is **unattributed**."

    Args:
        trace: A ``MEMORY_WRITE`` trace.
        seam_of: The first pass's correlation-to-seam index.

    Returns:
        The causing operation's seam label, or ``None`` when unattributed.
    """
    correlation = trace.refs.get(TraceRef.CORRELATION)
    if correlation is None:
        return None
    return seam_of.get(correlation)


def classify(seam: str) -> SeamClass | None:
    """Which of §3's two seam sets ``seam`` is on, or ``None`` for neither.

    Args:
        seam: The causing operation's seam label.

    Returns:
        The set, or ``None`` when the seam is on neither and the write is
        therefore unclassified.
    """
    if seam in USER_SEAMS:
        return SeamClass.USER
    if seam in MACHINE_SEAMS:
        return SeamClass.MACHINE
    return None
