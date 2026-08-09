"""ADR-0119 §8's two `memory` emitters: what each trace carries, and what it omits.

The omissions are as load-bearing as the contents here, which is why so many cases
assert a key is *absent*. §3's observation rule says "an absent key means *not
observed* and never zero", and §8 spells out why that matters at exactly this
seam: satisfying a "carries" clause with zeros "would make a read that never ran
indistinguishable from one that excluded everything — which is #824's trigger
condition, fabricated".

**Nothing here asks a fake or a conformance suite to emit.** Emission is a
property of the *wired deployment* — §7's required-constructor mechanism — and not
of the ``MemoryStore``/``MemoryWriter`` contracts, which §4 forbids widening for
an observability concern. So the shared suites and the canonical fakes are
untouched, and what is pinned is the two concretes the composition root wires.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import structlog
from pydantic import TypeAdapter

from ai_assistant.core.clock import ClockReadingError
from ai_assistant.core.correlation import correlated_operation
from ai_assistant.core.errors import (
    MemoryStoreError,
    TraceStoreError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.types import (
    Attestation,
    BeliefBand,
    MemoryDecisionKind,
    MemoryKind,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
    ReadCoverage,
    ReportedExtent,
    SemanticMemory,
    SourceReading,
    TraceKind,
    TraceLabel,
    TraceOutcome,
    TraceRecordSet,
    TraceRef,
    Validity,
)
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor, traces
from ai_assistant.memory.ingest import _WRITE_DISPOSITIONS
from ai_assistant.memory.sqlite_store import SqliteMemoryStore
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeMemoryPolicy, FakeTraceSink

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import Embedder, MemoryPolicy, MemoryStore, TraceSink
    from ai_assistant.core.types import Embedding, EvaluationTrace, MemoryRecord

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_SOURCE = "calendar:work"

#: The type a seam label and a metric key both are, so the constants can be
#: checked against ``core``'s own validator rather than against this module's copy.
_LABEL: TypeAdapter[str] = TypeAdapter(TraceLabel)


def _fixed_now() -> datetime:
    return _NOW


def _only(sink: FakeTraceSink, kind: TraceKind) -> EvaluationTrace:
    """The one trace of ``kind`` the sink holds — §5's one-crossing rule, as a test."""
    of_kind = [trace for trace in sink.recorded if trace.kind is kind]
    assert len(of_kind) == 1, f"expected exactly one {kind} trace, got {len(of_kind)}"
    return of_kind[0]


@pytest.fixture
def sink() -> FakeTraceSink:
    """The sink an emitter's test is handed: append only, read back by the test."""
    return FakeTraceSink()


# --- the relevance read -------------------------------------------------------


class _BrokenEmbedder:
    """An embedder that will not answer, so the read faults before it counts anything."""

    @property
    def model_id(self) -> str:
        """The model this would have used, had it worked."""
        return "broken"

    @property
    def dimensions(self) -> int:
        """The width the store records in its meta row."""
        return 64

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        """Raise instead of embedding.

        Args:
            texts: Ignored.

        Raises:
            RuntimeError: Always.
        """
        msg = "provider outage"
        raise RuntimeError(msg)


class _RaisingSink:
    """The sink §7 says cannot exist, which is why §5 says what to do about it."""

    async def emit(self, trace: EvaluationTrace) -> None:
        """Raise instead of appending.

        Args:
            trace: The trace that is lost.

        Raises:
            TraceStoreError: Always.
        """
        msg = "the store is unavailable"
        raise TraceStoreError(msg)


@pytest.fixture
def make_store(tmp_path: Path, sink: FakeTraceSink) -> Iterator[Callable[..., SqliteMemoryStore]]:
    """Build stores over one sink, closed on teardown so temp files release cleanly."""
    created: list[SqliteMemoryStore] = []

    def _make(
        *, embedder: Embedder | None = None, sink_override: TraceSink | None = None
    ) -> SqliteMemoryStore:
        store = SqliteMemoryStore(
            path=tmp_path / "memory.db",
            embedder=embedder if embedder is not None else HashingEmbedder(dimensions=64),
            traces_sink=sink_override if sink_override is not None else sink,
            now=_fixed_now,
        )
        created.append(store)
        return store

    yield _make
    for store in created:
        store.close()


def _semantic(
    record_id: str,
    content: str,
    *,
    expires_at: datetime | None = None,
    validity: Validity | None = None,
    source: MemorySource = MemorySource.INFERRED,
) -> MemoryRecord:
    """A searchable record carrying whichever read-time axis a case is about."""
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        expires_at=expires_at,
        validity=validity if validity is not None else Validity(),
        provenance=Provenance(
            source=source,
            confidence=1.0 if source is MemorySource.USER_ASSERTED else 0.6,
            last_updated=_WHEN,
        ),
    )


async def test_a_completed_read_carries_every_count_section_8_names(
    make_store: Callable[..., SqliteMemoryStore], sink: FakeTraceSink
) -> None:
    """ADR-0119 §8's retrieval clause, over a read that reached all of it.

    One record of each shape the post-KNN pass rejects, so the counts are
    different from one another: a measure reading this trace can tell a window
    closure from an expiry sweep, which is the distinction #824's trigger is
    entirely about and which a single filtered total destroys.
    """
    store = make_store()
    await store.add(_semantic("live", "the weekly planning meeting"))
    await store.add(
        _semantic("expired", "the weekly planning meeting", expires_at=_NOW - timedelta(days=1))
    )
    await store.add(
        _semantic(
            "closed",
            "the weekly planning meeting",
            validity=Validity(valid_until=_NOW - timedelta(days=1)),
        )
    )

    found = await store.search("weekly planning meeting", limit=5)

    assert [record.id for record in found] == ["live"]
    trace = _only(sink, TraceKind.RETRIEVAL)
    assert trace.seam == traces.SEAM_SEARCH
    assert trace.outcome is TraceOutcome.OK
    assert trace.fault_class is None
    assert trace.metrics[traces.LIMIT] == 5
    assert trace.metrics[traces.CANDIDATES] == 3
    assert trace.metrics[traces.RETURNED] == 1
    assert trace.metrics[traces.EXCLUDED_RETENTION] == 1
    assert trace.metrics[traces.EXCLUDED_WINDOW] == 1
    assert trace.metrics[traces.EXCLUDED_KIND] == 0
    assert trace.metrics[traces.EXCLUDED_BAND] == 0
    assert trace.records[TraceRecordSet.RETURNED].ids == ("live",)
    assert trace.records[TraceRecordSet.RETURNED].total == 1


async def test_the_kind_predicate_is_counted_apart_from_the_other_two(
    make_store: Callable[..., SqliteMemoryStore], sink: FakeTraceSink
) -> None:
    """The third of §8's countable predicates, isolated so it cannot borrow a total."""
    store = make_store()
    await store.add(_semantic("fact", "the weekly planning meeting"))
    await store.add(
        PreferenceMemory(
            id="pref",
            content="the weekly planning meeting",
            preference="the weekly planning meeting",
            provenance=Provenance(source=MemorySource.INFERRED, confidence=0.6, last_updated=_WHEN),
        )
    )

    await store.search("weekly planning meeting", limit=5, kinds=[MemoryKind.SEMANTIC])

    trace = _only(sink, TraceKind.RETRIEVAL)
    assert trace.metrics[traces.EXCLUDED_KIND] == 1
    assert trace.metrics[traces.EXCLUDED_RETENTION] == 0
    assert trace.metrics[traces.EXCLUDED_WINDOW] == 0
    assert trace.metrics[traces.EXCLUDED_BAND] == 0


async def test_a_band_scoped_read_reports_a_structurally_zero_band_exclusion(
    make_store: Callable[..., SqliteMemoryStore], sink: FakeTraceSink
) -> None:
    """§8's fourth predicate, and the reason its count is zero rather than large.

    ADR-0113 §2 binds the band *before* the ranking cut, so the out-of-band record
    below never becomes a candidate — which the candidate count says outright — and
    the post-KNN pass has none to drop. The zero is therefore a true statement
    about the set the same trace reports, and not a count of what the band kept out
    of the store's answer; that population is filtered inside the KNN and could
    only be counted by a second vector search.

    ``bands`` beside it is what carries the information the zero cannot: whether a
    band predicate was bound at all.
    """
    store = make_store()
    await store.add(_semantic("inferred", "the weekly planning meeting"))
    await store.add(
        _semantic("asserted", "the weekly planning meeting", source=MemorySource.USER_ASSERTED)
    )

    found = await store.search("weekly planning meeting", limit=5, bands=[BeliefBand.ASSERTED])

    assert [record.id for record in found] == ["asserted"]
    trace = _only(sink, TraceKind.RETRIEVAL)
    assert trace.metrics[traces.BANDS] == 1
    assert trace.metrics[traces.CANDIDATES] == 1, "an out-of-band row was never a candidate"
    assert trace.metrics[traces.EXCLUDED_BAND] == 0


async def test_the_trace_reports_the_band_selection_the_search_actually_used(
    make_store: Callable[..., SqliteMemoryStore], sink: FakeTraceSink
) -> None:
    """ADR-0065 §3's input clause, extended to the *record* of the read.

    The shared suite already pins that ``search`` answers from the ``bands`` it was
    handed rather than a later version (``memory_store_contract.py``'s
    ``test_search_observes_its_bands_filter_before_its_first_await``). Nothing
    pinned the same of the trace, and the trace is the easier one to get wrong:
    computing its band figure is a second read of the caller's sequence, and moving
    that read past the embedder's ``await`` would make the record describe a
    selection the search never applied — the observation the instrument exists to
    make, made of something that never happened.

    The mutation is delivered from *inside* the read rather than from another task,
    so the case is deterministic and needs no scheduling: the embedder is the first
    ``await``, and it empties the caller's list on its way through. It therefore
    pins the position of the derivation rather than any race — no ``await``
    separates the two reads today, so on one event loop they cannot diverge, and
    this is the guard against an edit that changes that.
    """
    bands = [BeliefBand.ASSERTED]

    class _MutatingEmbedder:
        """Embeds, and clears the caller's band list while it is at it."""

        def __init__(self, inner: HashingEmbedder) -> None:
            self._inner = inner
            self.armed = False

        @property
        def model_id(self) -> str:
            """The wrapped embedder's model."""
            return self._inner.model_id

        @property
        def dimensions(self) -> int:
            """The wrapped embedder's width."""
            return self._inner.dimensions

        async def embed(self, texts: Sequence[str]) -> list[Embedding]:
            """Empty the caller's list once armed, then embed normally.

            Args:
                texts: What to embed.

            Returns:
                The wrapped embedder's vectors.
            """
            if self.armed:
                bands.clear()
            return await self._inner.embed(texts)

    embedder = _MutatingEmbedder(HashingEmbedder(dimensions=64))
    store = make_store(embedder=embedder)
    await store.add(_semantic("inferred", "the weekly planning meeting"))
    await store.add(
        _semantic("asserted", "the weekly planning meeting", source=MemorySource.USER_ASSERTED)
    )
    # Armed after the seeding writes, so the mutation lands inside the read this
    # case is about rather than being spent on a precondition.
    embedder.armed = True

    found = await store.search("weekly planning meeting", limit=5, bands=bands)

    assert [record.id for record in found] == ["asserted"], "the pre-mutation selection"
    assert _only(sink, TraceKind.RETRIEVAL).metrics[traces.BANDS] == 1, (
        "the trace must report the selection the read used, not a later one"
    )


async def test_an_unscoped_read_reports_no_band_restriction(
    make_store: Callable[..., SqliteMemoryStore], sink: FakeTraceSink
) -> None:
    """``bands=None`` restricted nothing, so there is no restriction to report.

    The exclusion count still appears, because the pass still ran — the same
    reading that gives ``excluded_kind`` a zero on a read that named no kinds.
    """
    store = make_store()
    await store.add(_semantic("live", "the weekly planning meeting"))

    await store.search("weekly planning meeting", limit=5)

    trace = _only(sink, TraceKind.RETRIEVAL)
    assert traces.BANDS not in trace.metrics
    assert trace.metrics[traces.EXCLUDED_BAND] == 0


async def test_a_short_circuited_read_still_traces_and_counts_no_candidates(
    make_store: Callable[..., SqliteMemoryStore], sink: FakeTraceSink
) -> None:
    """A read that answered without fetching: returned is observed, the rest is not.

    "Zero records came back" is a real observation and the key carries it; the
    candidate and exclusion counts are absent because nothing was fetched to
    count. The empty ``RecordIdSet`` under ``RETURNED`` is §3's other half — "a key
    present with an empty ``RecordIdSet`` means it was observed and it was empty".
    """
    store = make_store()
    await store.add(_semantic("live", "the weekly planning meeting"))

    assert await store.search("   ", limit=5) == []

    trace = _only(sink, TraceKind.RETRIEVAL)
    assert trace.outcome is TraceOutcome.OK
    assert trace.metrics[traces.LIMIT] == 5
    assert trace.metrics[traces.RETURNED] == 0
    assert traces.CANDIDATES not in trace.metrics
    # All four exclusion counts stand or fall together with the pass that
    # produces them, which is what keeps the band's structural zero from meaning
    # "no candidate set existed" (ADR-0119 §3).
    for key in (
        traces.EXCLUDED_KIND,
        traces.EXCLUDED_RETENTION,
        traces.EXCLUDED_WINDOW,
        traces.EXCLUDED_BAND,
    ):
        assert key not in trace.metrics
    assert trace.records[TraceRecordSet.RETURNED].ids == ()
    assert trace.records[TraceRecordSet.RETURNED].total == 0


async def test_a_faulting_read_traces_its_limit_and_nothing_it_never_reached(
    make_store: Callable[..., SqliteMemoryStore], sink: FakeTraceSink
) -> None:
    """§8's fault-path paragraph, in full.

    "A ``search`` whose query embedding raises never computes a candidate set…
    Under §3's observation rule the metric keys are simply **absent**, and so are
    the ``TraceRecordSet`` keys nothing was observed under." What survives is the
    envelope the read did reach: its limit, its elapsed time, its ``FAULT``
    outcome and its fault class.
    """
    store = make_store(embedder=_BrokenEmbedder())

    with pytest.raises(MemoryStoreError):
        await store.search("weekly planning meeting", limit=7)

    trace = _only(sink, TraceKind.RETRIEVAL)
    assert trace.outcome is TraceOutcome.FAULT
    assert trace.fault_class == "MemoryStoreError"
    assert trace.metrics == {traces.LIMIT: 7}
    assert trace.records == {}
    assert trace.elapsed is not None, "the read ran, so its duration was observed"


async def test_a_read_serving_an_operation_carries_that_operations_correlation(
    make_store: Callable[..., SqliteMemoryStore], sink: FakeTraceSink
) -> None:
    """ADR-0119 §4, read off the ambient carrier and never off a signature.

    The identifier is not on ``MemoryStore.search`` and may not be (§4's third
    clause), so the join is bought by reading the carrier ``core/correlation.py``
    holds — the one the engine boundary opens.
    """
    store = make_store()
    await store.add(_semantic("live", "the weekly planning meeting"))

    with correlated_operation() as correlation:
        await store.search("weekly planning meeting")

    assert _only(sink, TraceKind.RETRIEVAL).refs[TraceRef.CORRELATION] == correlation


async def test_a_read_outside_an_operation_omits_the_reference_rather_than_inventing_one(
    make_store: Callable[..., SqliteMemoryStore], sink: FakeTraceSink
) -> None:
    """``None`` is the honest answer outside an operation, and absence records it."""
    store = make_store()
    await store.add(_semantic("live", "the weekly planning meeting"))

    await store.search("weekly planning meeting")

    assert TraceRef.CORRELATION not in _only(sink, TraceKind.RETRIEVAL).refs


async def test_a_sink_that_raises_costs_the_trace_and_never_the_read(
    make_store: Callable[..., SqliteMemoryStore],
) -> None:
    """ADR-0119 §5: subordination, and the log record that keeps the loss loud.

    A trace one tier further from the user's answer than an episode cannot fail a
    read when ADR-0074 already ruled that losing an *episode* does not fail a turn.
    Silence is refused separately, because "a measure over a stream with dropped
    rows reports a smaller numerator and does not know it".

    A *raising* sink rather than :meth:`FakeTraceSink.fail_append`, deliberately:
    the fake swallows and logs on its own account (§7 says a conforming sink
    cannot raise), so scripting it would exercise the fake's guard and never the
    emitter's. §5 says what to do if one raises anyway, and this is that path.
    """
    store = make_store(sink_override=_RaisingSink())
    await store.add(_semantic("live", "the weekly planning meeting"))

    with structlog.testing.capture_logs() as captured:
        found = await store.search("weekly planning meeting")

    assert [record.id for record in found] == ["live"]
    assert [record["event"] for record in captured] == [traces.TRACE_NOT_RECORDED]
    (record,) = captured
    assert record["kind"] == "retrieval"
    assert record["seam"] == traces.SEAM_SEARCH
    assert record["error_class"] == "TraceStoreError"


async def test_a_clock_that_will_not_read_costs_the_trace_and_never_the_read(
    tmp_path: Path, sink: FakeTraceSink
) -> None:
    """A mis-wired clock is an instrument fault, and §5 subordinates every one.

    The store's *expiry* comparison depends on its clock and translates a bad
    reading into a ``MemoryStoreError`` (ADR-0026 §4); the trace's instant does
    not, so its absence costs a record and nothing else. The two are separate
    seams for a stronger reason than this case — see ``traces_now`` — and that
    separation is what lets this one break the emitter's clock alone.
    """

    def broken() -> datetime:
        msg = "the reading is naive"
        raise ClockReadingError(msg)

    store = SqliteMemoryStore(
        path=tmp_path / "memory.db",
        embedder=HashingEmbedder(dimensions=64),
        traces_sink=sink,
        traces_now=broken,
        now=_fixed_now,
    )
    try:
        with structlog.testing.capture_logs() as captured:
            assert await store.search("   ") == []
    finally:
        store.close()

    assert sink.recorded == ()
    assert [record["event"] for record in captured] == [traces.TRACE_NOT_RECORDED]


# --- the write path -----------------------------------------------------------


def _proposal(record: MemoryRecord) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=record, rationale="a producer proposed it")


def _preference(
    record_id: str, content: str, *, source: MemorySource = MemorySource.INFERRED
) -> MemoryRecord:
    return PreferenceMemory(
        id=record_id,
        content=content,
        preference=content,
        provenance=Provenance(
            source=source,
            confidence=1.0 if source is MemorySource.USER_ASSERTED else 0.6,
            last_updated=_WHEN,
        ),
    )


def _asserted(record_id: str, content: str) -> MemoryRecord:
    """A user's own belief — the one band ``DefaultMemoryPolicy`` accepts unwarranted.

    An ``INFERRED`` proposal is in the ``DERIVED`` band, where ADR-0072 §3 obliges
    a citation and rule 2 rejects one that cites nothing; a case about the *trace*
    should not have to carry a warrant to reach an ``ACCEPT``.
    """
    return _preference(record_id, content, source=MemorySource.USER_ASSERTED)


def _attested(record_id: str, content: str) -> MemoryRecord:
    """An attested belief a covered reading can close, in ADR-0117 §3's shape.

    The envelope window is open and the position is stated by the extent, which is
    what a conforming reader now proposes — ADR-0117 §1's reason being that a
    window stating a forward-looking position would put the record out of reach of
    retrieval, the fold and this very enumeration.
    """
    return PreferenceMemory(
        id=record_id,
        content=content,
        preference=content,
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=0.6,
            last_updated=_WHEN,
            attestation=Attestation(
                reported_by=_SOURCE,
                reported_at=_WHEN,
                extent=ReportedExtent(extends_until=_NOW + timedelta(days=1)),
            ),
        ),
    )


def _writer(
    store: MemoryStore, sink: TraceSink, *, policy: MemoryPolicy | None = None
) -> MemoryIngestor:
    return MemoryIngestor(
        store=store,
        policy=policy if policy is not None else DefaultMemoryPolicy(),
        traces_sink=sink,
        now=_fixed_now,
    )


async def test_two_proposals_reinforcing_one_record_keep_their_trace(
    sink: FakeTraceSink,
) -> None:
    """The repeat §3 forbids a ``RecordIdSet`` to carry, arriving honestly.

    One reading may hold two proposals that both fold into the same standing
    belief, and both results then name that one id. Filing it twice fails the
    type's "each id at most once" validator, which §5 turns into a **lost trace**
    for a crossing where nothing went wrong — the instrument lying because the
    writer did its job twice.

    So the set collapses and the counts do not: two rulings stay two in
    ``decisions_reinforce``, and the answer to "which records ended up
    reinforced" is a set, which is what §3 defines it to be.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    await store.add(_preference("standing", "the office is on the third floor"))
    writer = _writer(store, sink, policy=FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))
    reading = SourceReading(
        source=_SOURCE,
        read_at=_NOW,
        proposals=(
            _proposal(_preference("first", "the office is on the third floor")),
            _proposal(_preference("second", "the office is on the third floor")),
        ),
        coverage=None,
    )

    results = await writer.ingest_reading(reading)

    assert [result.record_id for result in results] == ["standing", "standing"]
    trace = _only(sink, TraceKind.MEMORY_WRITE)
    assert trace.metrics["decisions_reinforce"] == 2
    assert trace.records[TraceRecordSet.REINFORCED].ids == ("standing",)
    assert trace.records[TraceRecordSet.REINFORCED].total == 1


async def test_an_accepted_write_counts_every_kind_and_files_the_id_as_written(
    sink: FakeTraceSink,
) -> None:
    """ADR-0119 §8's write clause on the simplest ruling there is.

    Every ``MemoryDecisionKind`` gets a key, five of them zero. That is §3's
    observation rule read straight: a completed ingest **observed** every kind,
    and an absent key would claim it observed none of them.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    writer = _writer(store, sink)

    result = await writer.ingest(_proposal(_asserted("new", "the office is on the third floor")))

    assert result.decision.kind is MemoryDecisionKind.ACCEPT
    trace = _only(sink, TraceKind.MEMORY_WRITE)
    assert trace.seam == traces.SEAM_INGEST
    assert trace.outcome is TraceOutcome.OK
    assert trace.metrics[traces.PROPOSALS] == 1
    assert trace.metrics["decisions_accept"] == 1
    assert trace.metrics["decisions_reject"] == 0
    assert trace.records[TraceRecordSet.WRITTEN].ids == ("new",)
    assert trace.records[TraceRecordSet.REINFORCED].ids == ()
    assert trace.records[TraceRecordSet.SUPERSEDED].ids == ()
    assert TraceRecordSet.RETIRED not in trace.records, "no reconciliation ran, so none was seen"


async def test_a_reinforcement_is_filed_apart_from_a_write(sink: FakeTraceSink) -> None:
    """The distinction §8 buys the per-disposition keys for.

    "So a correction measure can tell a retired id from a reinforced one without
    re-deriving it" — which a flat sequence of ids could not express at all.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    await store.add(_preference("standing", "the office is on the third floor"))
    writer = _writer(store, sink, policy=FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))

    await writer.ingest(_proposal(_preference("fresh", "the office is on the third floor")))

    trace = _only(sink, TraceKind.MEMORY_WRITE)
    assert trace.metrics["decisions_reinforce"] == 1
    assert trace.records[TraceRecordSet.REINFORCED].ids == ("standing",)
    assert trace.records[TraceRecordSet.WRITTEN].ids == ()


async def test_a_supersede_files_the_correction_written_and_the_target_superseded(
    sink: FakeTraceSink,
) -> None:
    """The ids a correction rate is made of, on the two sides of the correction.

    A ``SUPERSEDE``'s live id is a **written** record — ADR-0045 §4 installs the
    correction fresh at a minted id — and what it displaced is the retirement set,
    which is the whole supersedable conflict set and not just the ruling's
    ``target_id`` (ADR-0050 §1). Reporting only the named one would under-count
    exactly the event this trace exists to record.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    await store.add(_preference("stale", "the office is on the third floor"))
    writer = _writer(store, sink)

    result = await writer.ingest(
        _proposal(_asserted("correction", "the office is on the fifth floor"))
    )

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    trace = _only(sink, TraceKind.MEMORY_WRITE)
    assert trace.metrics["decisions_supersede"] == 1
    assert trace.records[TraceRecordSet.SUPERSEDED].ids == ("stale",)
    assert trace.records[TraceRecordSet.WRITTEN].ids == (result.record_id,)


async def test_one_reading_is_one_crossing_and_one_trace(sink: FakeTraceSink) -> None:
    """ADR-0119 §5's one-crossing rule over §8's named case.

    "A ``MemoryWriter.ingest_reading`` call is one crossing and one trace, not one
    per resulting ``MemoryIngestResult``… the per-reading counts ride as metrics."
    Three proposals, one trace, and the count of them on it — which also pins that
    the member does not reach the write path through :meth:`MemoryIngestor.ingest`,
    since that would emit a second trace apiece.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    writer = _writer(store, sink)
    reading = SourceReading(
        source=_SOURCE,
        read_at=_NOW,
        proposals=tuple(_proposal(_attested(f"e{n}", f"entry number {n}")) for n in range(3)),
        coverage=None,
    )

    results = await writer.ingest_reading(reading)

    assert len(results) == 3
    trace = _only(sink, TraceKind.MEMORY_WRITE)
    assert trace.seam == traces.SEAM_INGEST_READING
    assert trace.metrics[traces.PROPOSALS] == 3
    assert trace.metrics[traces.COVERAGE_DECLARED] is False
    assert trace.metrics["decisions_accept"] == 3
    assert TraceRecordSet.RETIRED not in trace.records, "an uncovered reading reconciles nothing"
    assert traces.CLOSED not in trace.metrics


async def test_a_covered_reading_files_what_its_absence_retired(sink: FakeTraceSink) -> None:
    """ADR-0110's close, filed under its own key rather than folded into the writes.

    An empty ``RETIRED`` set is a different claim from an absent one (§3), so the
    covered arm carries the key whatever it closed — here, the belief the reading
    no longer reports.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    await store.add(_attested("gone", "the entry that vanished"))
    writer = _writer(store, sink)
    reading = SourceReading(
        source=_SOURCE,
        read_at=_NOW,
        proposals=(),
        coverage=ReadCoverage(covers_until=_NOW + timedelta(days=30)),
    )

    await writer.ingest_reading(reading)

    trace = _only(sink, TraceKind.MEMORY_WRITE)
    assert trace.metrics[traces.COVERAGE_DECLARED] is True
    assert trace.metrics[traces.CLOSED] == 1
    assert trace.records[TraceRecordSet.RETIRED].ids == ("gone",)


async def test_a_reading_that_refuses_half_way_still_files_what_it_applied(
    sink: FakeTraceSink,
) -> None:
    """A partial commit is observed work, and §3 forbids the trace to deny it.

    ADR-0115 §3 leaves "the proposals ingested before the raise stay applied", so a
    ``REFUSED`` trace carrying no ``WRITTEN`` id would say a record that is live was
    never written. An absent key means *not observed* — and this one was observed,
    committed, and is readable from the store while the trace denies it. That is
    the same fabrication §8's fault-path paragraph refuses in the other direction,
    arriving through a partial commit instead of through a zero.

    ``RETIRED`` stays absent because the reconciliation genuinely never ran, and
    the decision counts sum to one against ``proposals = 2``, which is what a
    half-finished crossing looks like when it is described honestly.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    writer = _writer(store, sink)
    unwarranted = SemanticMemory(
        id="derived",
        content="a conclusion drawn from nothing",
        fact="a conclusion drawn from nothing",
        provenance=Provenance(
            source=MemorySource.INFERRED,
            confidence=0.6,
            last_updated=_WHEN,
            evidence=("missing",),
        ),
    )
    reading = SourceReading(
        source=_SOURCE,
        read_at=_NOW,
        proposals=(
            _proposal(_asserted("landed", "the office is on the third floor")),
            _proposal(unwarranted),
        ),
        coverage=None,
    )

    with pytest.raises(UnresolvedEvidenceError):
        await writer.ingest_reading(reading)

    assert await store.get("landed") is not None, "the first proposal stayed applied"
    trace = _only(sink, TraceKind.MEMORY_WRITE)
    assert trace.outcome is TraceOutcome.REFUSED
    assert trace.metrics[traces.PROPOSALS] == 2
    assert trace.metrics["decisions_accept"] == 1
    assert trace.records[TraceRecordSet.WRITTEN].ids == ("landed",)
    assert TraceRecordSet.RETIRED not in trace.records, "the reconciliation never ran"


async def test_an_inadmissible_proposal_traces_as_a_refusal_and_not_a_fault(
    sink: FakeTraceSink,
) -> None:
    """§3's discriminator, by the exception's class and never its message.

    ADR-0077 §5 refuses a ``DERIVED`` proposal whose warrant does not exist, and
    that is an answer rather than a malfunction — the same reading ADR-0111 §9
    binds the scheduler's log record to, "so the two records about one event cannot
    disagree".
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    writer = _writer(store, sink)
    unwarranted = SemanticMemory(
        id="derived",
        content="a conclusion drawn from nothing",
        fact="a conclusion drawn from nothing",
        provenance=Provenance(
            source=MemorySource.INFERRED,
            confidence=0.6,
            last_updated=_WHEN,
            evidence=("missing",),
        ),
    )

    with pytest.raises(UnresolvedEvidenceError):
        await writer.ingest(_proposal(unwarranted))

    trace = _only(sink, TraceKind.MEMORY_WRITE)
    assert trace.outcome is TraceOutcome.REFUSED
    assert trace.fault_class == "UnresolvedEvidenceError"
    assert trace.metrics == {traces.PROPOSALS: 1}, "no ruling was reached, so no kind was observed"
    assert trace.records == {}


async def test_a_write_serving_an_operation_carries_that_operations_correlation(
    sink: FakeTraceSink,
) -> None:
    """§4's join reaches the write path through the same ambient carrier."""
    store = InMemoryMemoryStore(now=_fixed_now)
    writer = _writer(store, sink)

    with correlated_operation() as correlation:
        await writer.ingest(_proposal(_asserted("new", "the office is on the third floor")))

    assert _only(sink, TraceKind.MEMORY_WRITE).refs[TraceRef.CORRELATION] == correlation


async def test_a_sink_that_raises_costs_the_trace_and_never_the_write() -> None:
    """§5 again, on the seam where raising instead would be most tempting.

    The write already landed when the append fails, so propagating would tell the
    caller its write failed when it did not — the inversion §5 forbids, arriving
    through the instrument.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    writer = _writer(store, _RaisingSink())

    with structlog.testing.capture_logs() as captured:
        result = await writer.ingest(
            _proposal(_asserted("new", "the office is on the third floor"))
        )

    assert result.record_id == "new"
    assert await store.get("new") is not None
    (record,) = captured
    assert record["event"] == traces.TRACE_NOT_RECORDED
    assert record["kind"] == "memory_write"
    assert record["seam"] == traces.SEAM_INGEST


# --- the tables these emitters read the enums through -------------------------


def test_every_decision_kind_has_a_literal_metric_key() -> None:
    """§2's second clause needs a literal per kind, and §3 needs one for every kind.

    Totality is asserted rather than constructed, because the construction that
    would guarantee it — ``f"decisions_{kind.value}"`` — is the runtime-composed
    key §2 keeps out. A member added later fails here instead of losing its count.
    """
    assert set(traces.DECISION_METRICS) == set(MemoryDecisionKind)
    assert len(set(traces.DECISION_METRICS.values())) == len(MemoryDecisionKind)


def test_every_decision_kind_has_a_declared_disposition() -> None:
    """A ruling with no entry would drop its ids silently, which §8 cannot allow."""
    assert set(_WRITE_DISPOSITIONS) == set(MemoryDecisionKind)


@pytest.mark.parametrize(
    "label",
    [
        traces.SEAM_SEARCH,
        traces.SEAM_INGEST,
        traces.SEAM_INGEST_READING,
        *traces.DECISION_METRICS.values(),
        traces.LIMIT,
        traces.FETCH_K,
        traces.CANDIDATES,
        traces.RETURNED,
        traces.EXCLUDED_KIND,
        traces.EXCLUDED_RETENTION,
        traces.EXCLUDED_WINDOW,
        traces.EXCLUDED_BAND,
        traces.BANDS,
        traces.PROPOSALS,
        traces.COVERAGE_DECLARED,
        traces.CLOSED,
    ],
)
def test_every_literal_this_module_writes_is_a_trace_label(label: str) -> None:
    """Each constant goes through ``core``'s own validator, not this module's copy.

    ``memory/traces.py`` duplicates ``core/types.py``'s label pattern for its log
    record, and a constant the type would refuse reaches the emitter as a *lost
    trace* under §5 rather than as a loud failure. Both directions are checked, so
    the duplicate cannot drift into accepting something the type does not.
    """
    assert _LABEL.validate_python(label) == label
    assert re.fullmatch(traces._SEAM_LABEL, label) is not None
