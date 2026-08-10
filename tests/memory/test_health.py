"""Tests for ADR-0129's store-health census.

These touch the filesystem and the native ``sqlite-vec`` extension, so the module
is marked ``integration``. Everything here is offline and seeded: the embedder is
``tests/memory/aged_store.py``'s :class:`ClusteredEmbedder`, a pure function of
the text, and every clock is injected — which is not a convenience but §1's own
rule, since the tool has no ``T`` option for a test to pass.

The cases are organised around what §8 asks the implementing lane for, because
most of the value is in the dispositions and the domain: the reachable statements
(§1, §4), the unpurged expired row (§8's third clause), the ``k`` boundary trio
(§8's fourth), the determinism clause and the known concentration (§8's fifth),
and ``T`` moving the figures without moving the sample (§8's sixth). The contended
lock, the fifth disposition, belongs to the entry point and is asserted in
``tests/service/test_store_health_tool.py``.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

import pytest
import sqlite_vec
from aged_store import (
    HOT_TOPIC,
    AgedStoreSpec,
    ClusteredEmbedder,
    Instants,
    install,
    plant,
)

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    BeliefBand,
    MemoryKind,
    MemoryRecord,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Provenance,
    SemanticMemory,
    Validity,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory import health as health_module
from ai_assistant.memory.health import MAX_K, StoreHealthReader, StoreHealthReport
from ai_assistant.testing import FakeTraceSink

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

pytestmark = pytest.mark.integration

#: The census instant every fixed-clock case reads.
_NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

#: A sample larger than any store built here, so a case that is not *about*
#: sampling takes the whole candidate set and its figures are exact.
_ALL = 10_000

#: The SQLite sidecars a read-only census must not leave beside the store.
_SIDECARS = ("-journal", "-wal", "-shm")


class _MakeStore(Protocol):
    """The store factory the fixture below hands each case."""

    def __call__(
        self, *, now: datetime = ..., path: Path | None = ...
    ) -> SqliteMemoryStore:  # pragma: no cover - a Protocol body
        """Open a memory store on an injected clock."""


class _Clock:
    """A clock a case moves, since §1 gives the tool no ``T`` to pass."""

    def __init__(self, reading: datetime) -> None:
        self.reading = reading

    def __call__(self) -> datetime:
        """The current reading."""
        return self.reading


def _record(  # noqa: PLR0913 — one keyword per field a census reads, which is the point
    record_id: str,
    content: str,
    *,
    expires_at: datetime | None = None,
    validity: Validity | None = None,
    source: MemorySource = MemorySource.OBSERVED,
    about_person: str | None = None,
) -> MemoryRecord:
    """One semantic record, varying only the fields a census reads."""
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        about_person=about_person,
        expires_at=expires_at,
        validity=validity if validity is not None else Validity(),
        provenance=Provenance(
            source=source,
            confidence=1.0 if source is MemorySource.USER_ASSERTED else 0.6,
            last_updated=_NOW,
        ),
    )


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """Where a case's memory store lives unless it asks for another."""
    return tmp_path / "memory.db"


@pytest.fixture
def make_store(store_path: Path) -> Iterator[_MakeStore]:
    """Build memory stores on an injected clock, closed on teardown."""
    created: list[SqliteMemoryStore] = []

    def _make(*, now: datetime = _NOW, path: Path | None = None) -> SqliteMemoryStore:
        store = SqliteMemoryStore(
            path=path if path is not None else store_path,
            embedder=ClusteredEmbedder(),
            traces_sink=FakeTraceSink(),
            now=lambda: now,
        )
        created.append(store)
        return store

    yield _make
    for store in created:
        store.close()


async def _write(store: SqliteMemoryStore, records: Sequence[MemoryRecord]) -> None:
    """Install ``records`` in one atomic batch."""
    await store.write_atomic(
        [MemoryWrite(record=record, mode=MemoryWriteMode.INSERT_IF_ABSENT) for record in records]
    )


def _plain(count: int, *, start: int = 0) -> list[MemoryRecord]:
    """``count`` unremarkable live records in one topic."""
    return [_record(f"r{index}", f"t0 p{index} u{index}") for index in range(start, start + count)]


def _rows(path: Path, sql: str) -> list[tuple[object, ...]]:
    """Read the store file directly, for the cases whose subject is the file."""
    conn = sqlite3.connect(str(path))
    try:
        return [tuple(row) for row in conn.execute(sql)]
    finally:
        conn.close()


def _drop_every_vector(path: Path) -> None:
    """Leave the records and take the geometry away.

    ``vec_records`` is joined to ``records`` by ``rowid`` with **no foreign key**
    and a re-embed rebuilds the store wholesale, so a record with no vector is a
    reachable state rather than a corruption — which is why §3 counts them apart.
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("DELETE FROM vec_records")
        conn.commit()
    finally:
        conn.close()


def _samples(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Record which records each run selected, which §7 keeps out of the report.

    §8's determinism and ``T`` clauses are both about *which records were looked
    at*, and the report deliberately cannot say — it prints no identifier. So the
    selection is observed at the one place it is made.
    """
    seen: list[tuple[str, ...]] = []
    original = health_module._Tally.sample

    def spy(self: health_module._Tally) -> list[health_module._Candidate]:
        selected = original(self)
        seen.append(tuple(candidate.record_id for candidate in selected))
        return selected

    monkeypatch.setattr(health_module._Tally, "sample", spy)
    return seen


def _band(report: StoreHealthReport, band: BeliefBand) -> tuple[int, int]:
    """The live and not-live counts the report states for ``band``."""
    for fill in report.bands:
        if fill.band is band:
            return fill.live, fill.not_live
    raise AssertionError(f"the report states no fill for {band}")


def _census_of(path: Path, *, at: datetime = _NOW, sample: int = _ALL, k: int) -> StoreHealthReport:
    """Take one census of ``path`` at a fixed instant."""
    return StoreHealthReader(store=path, now=lambda: at).report(sample=sample, k=k)


class TestStatedDispositions:
    """§4's and §1's reachable outputs — each a stated output, none an exception."""

    def test_an_absent_store_is_stated_and_is_not_created(self, store_path: Path) -> None:
        """ "The report says so and states no figure, and the tool does not create one"."""
        report = _census_of(store_path, k=4)

        assert report.statement is not None
        assert report.census is None
        assert report.read_at is None
        assert "no memory store" in report.render()
        assert not store_path.exists()

    def test_an_empty_store_is_stated_and_no_figure_is(
        self, make_store: _MakeStore, store_path: Path
    ) -> None:
        """ "Where the store exists and holds no record, the report says the store is empty"."""
        make_store().close()

        report = _census_of(store_path, k=4)

        assert report.statement is not None
        assert "holds no record" in report.render()
        assert report.census is None
        assert report.concentration is None

    async def test_a_store_with_no_retired_record_leaves_the_closure_age_undefined(
        self, make_store: _MakeStore, store_path: Path
    ) -> None:
        """§1: undefined over an empty population, "rather than stating a figure or a zero"."""
        store = make_store()
        await _write(store, _plain(5))
        store.close()

        report = _census_of(store_path, k=2)

        assert report.census is not None
        assert report.census.retired == 0
        assert report.closure_age is not None
        assert not report.closure_age.defined
        assert "undefined" in report.closure_age.rendered_intervals()
        assert "0:00:00" not in report.closure_age.rendered_intervals()

    async def test_a_store_with_no_vector_leaves_the_density_undefined(
        self, make_store: _MakeStore, store_path: Path
    ) -> None:
        """A vectorless record enters the census and leaves the density's population."""
        store = make_store()
        await _write(store, _plain(5))
        store.close()
        _drop_every_vector(store_path)

        report = _census_of(store_path, k=2)

        assert report.census is not None
        assert report.census.total == 5
        assert report.without_vector == 5
        assert report.concentration is not None
        assert report.concentration.candidates == 0
        assert not report.concentration.defined
        assert not report.concentration.not_live.defined
        assert "undefined" in report.render()

    async def test_an_unpurged_expired_record_is_in_the_census_export_would_not_return_it(
        self, make_store: _MakeStore, store_path: Path
    ) -> None:
        """§8's third clause, over the one store where the two populations disagree."""
        past = _NOW - timedelta(days=1)
        writing = make_store(now=past)
        await _write(
            writing,
            [
                _record("kept", "t0 p0 u0"),
                _record("doomed", "t0 p1 u1", expires_at=past + timedelta(minutes=1)),
            ],
        )
        writing.close()
        # `export` reads the store's own clock, so it has to be past the deadline
        # for the two populations to differ. Nothing purges: `purge_expired` is
        # never called, which is the state §8 names.
        reading = make_store(now=_NOW)
        exported = {record.id for record in await reading.export()}
        reading.close()

        report = _census_of(store_path, k=1)

        assert exported == {"kept"}
        assert report.census is not None
        assert report.census.total == 2
        assert report.census.expired == 1
        assert report.census.live == 2, "liveness and expiry are separate axes (§3)"
        assert _rows(store_path, "SELECT COUNT(*) FROM records") == [(2,)]

    async def test_the_closure_age_is_the_interval_from_each_valid_until_to_the_instant(
        self, make_store: _MakeStore, store_path: Path
    ) -> None:
        """§3's third figure, over the population §3 defines it on — records retired at ``T``."""
        store = make_store()
        await _write(
            store,
            [
                _record(
                    "old", "t0 p0 u0", validity=Validity(valid_until=_NOW - timedelta(days=30))
                ),
                _record("new", "t0 p1 u1", validity=Validity(valid_until=_NOW - timedelta(days=2))),
                *_plain(4, start=2),
            ],
        )
        store.close()

        report = _census_of(store_path, k=2)

        assert report.closure_age is not None
        assert report.closure_age.count == 2, "the population is the records retired at T"
        assert report.closure_age.minimum == timedelta(days=2).total_seconds()
        assert report.closure_age.maximum == timedelta(days=30).total_seconds()
        assert "30 days" in report.closure_age.rendered_intervals()


class TestItWritesNothing:
    """§4's second clause, asserted against the file rather than against intent."""

    async def test_the_census_changes_no_row_and_advances_no_walk_cursor(
        self, make_store: _MakeStore, store_path: Path
    ) -> None:
        """ "It adds, updates, deletes and purges no record, and it advances no walk cursor"."""
        store = make_store()
        await _write(store, _plain(6))
        chunk = await store.walk_records("consolidation", limit=2)
        assert chunk.position is not None
        await store.advance_walk("consolidation", position=chunk.position)
        store.close()
        records = "SELECT rowid, id, data FROM records ORDER BY rowid"
        walks = "SELECT walk, position FROM walk_positions ORDER BY walk"
        before_records = _rows(store_path, records)
        before_walks = _rows(store_path, walks)
        assert before_walks, "the fixture must set a cursor for this case to mean anything"

        _census_of(store_path, k=2)

        assert _rows(store_path, records) == before_records
        assert _rows(store_path, walks) == before_walks
        for suffix in _SIDECARS:
            sidecar = store_path.with_name(store_path.name + suffix)
            assert not sidecar.exists(), f"the census left {sidecar.name} behind"


class TestTheDensityDomain:
    """§3's ``k + 1`` rule and §8's boundary trio."""

    @pytest.mark.parametrize("k", [0, -1])
    def test_a_k_that_is_zero_or_negative_is_refused_rather_than_run(
        self, store_path: Path, k: int
    ) -> None:
        """Refused before the store is even looked for, which is what "rather than run" means."""
        with pytest.raises(MemoryStoreError, match="positive integer"):
            _census_of(store_path, k=k)

    def test_a_k_the_vector_index_could_not_serve_is_refused(self, store_path: Path) -> None:
        """A neighbourhood of ``k`` needs ``k + 1`` from an index whose ceiling is fixed."""
        with pytest.raises(MemoryStoreError, match="at most"):
            _census_of(store_path, k=MAX_K + 1)

    @pytest.mark.parametrize("sample", [0, -3])
    def test_a_sample_below_one_is_refused(self, store_path: Path, sample: int) -> None:
        """A sample of nothing is not a smaller sample."""
        with pytest.raises(MemoryStoreError, match="at least one record"):
            _census_of(store_path, sample=sample, k=4)

    @pytest.mark.parametrize(
        "value",
        [1.5, float("nan"), float("inf"), True, None, "4"],
        ids=["fraction", "nan", "infinity", "bool", "none", "text"],
    )
    async def test_a_parameter_that_is_not_a_whole_number_is_refused(
        self, make_store: _MakeStore, store_path: Path, value: object
    ) -> None:
        """§3 makes ``k`` a *positive integer*, and an ordering test is not that test.

        A caller reaching the reader directly is not held to the annotation — the
        entry point's parser is, but it is not the only caller. ``1.5`` passes
        every comparison in the domain check and would divide a neighbourhood by a
        fraction; ``nan`` passes them by refusing to compare, and used to reach an
        empty heap and raise a raw ``IndexError``; ``True`` is a ``k`` of one by
        accident of the type system rather than by anybody's intent.
        """
        store = make_store()
        await _write(store, _plain(6))
        store.close()
        reader = StoreHealthReader(store=store_path, now=lambda: _NOW)

        with pytest.raises(MemoryStoreError, match="whole number"):
            reader.report(sample=value, k=3)  # type: ignore[arg-type]  # the annotation is the thing under test
        with pytest.raises(MemoryStoreError, match="whole number"):
            reader.report(sample=4, k=value)  # type: ignore[arg-type]  # likewise

    async def test_exactly_k_vector_bearing_records_reports_the_figure_undefined(
        self, make_store: _MakeStore, store_path: Path
    ) -> None:
        """ "Undefined where the candidate set holds fewer than ``k + 1`` records"."""
        store = make_store()
        await _write(store, _plain(4))
        store.close()

        report = _census_of(store_path, k=4)

        assert report.concentration is not None
        assert report.concentration.candidates == 4
        assert not report.concentration.defined
        assert not report.concentration.density.defined
        assert "needs 5" in report.render()

    async def test_exactly_k_plus_one_takes_it_over_full_neighbourhoods(
        self, make_store: _MakeStore, store_path: Path
    ) -> None:
        """ "No sampled record is dropped for want of a full neighbourhood"."""
        store = make_store()
        await _write(store, _plain(5))
        store.close()

        report = _census_of(store_path, k=4)

        assert report.concentration is not None
        assert report.concentration.candidates == 5
        assert report.concentration.defined
        assert report.concentration.evaluated == 5
        assert report.concentration.density.count == 5, "a record was dropped for want of a k-th"
        # Every neighbour is live, so every density is a *measured* zero over a
        # full neighbourhood — a different statement from the undefined one above.
        assert report.concentration.density.maximum == 0.0


class TestDeterminism:
    """§8's fifth clause — the one an implementation can pass in name and fail in substance."""

    async def test_two_runs_over_an_unchanged_store_select_the_same_sample_and_agree(
        self, make_store: _MakeStore, store_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """§3: "where the clock's reading is also held fixed, the two runs produce
        identical figures"."""
        store = make_store()
        await _write(
            store, [_record(f"r{index}", f"t{index % 4} p{index} u{index}") for index in range(60)]
        )
        store.close()
        seen = _samples(monkeypatch)
        reader = StoreHealthReader(store=store_path, now=lambda: _NOW)

        first = reader.report(sample=17, k=5)
        second = reader.report(sample=17, k=5)

        assert len(seen) == 2
        assert seen[0] == seen[1], "the sample moved between two runs over an unchanged store"
        assert len(seen[0]) == 17, "the run did not sample what it was asked to"
        assert first == second
        assert first.render() == second.render()

    def test_the_sample_does_not_depend_on_the_clock(self) -> None:
        """The clause binds *which records are looked at*, and that must not move with ``T``.

        Asserted at the tally rather than through a store, because the property is
        about the draw and nothing else: the same records, classified against two
        instants that put every one of them on the other side of its window, must
        still produce the same selection.
        """
        records = [
            _record(
                f"r{index}",
                f"t0 p{index} u{index}",
                validity=Validity(valid_until=_NOW + timedelta(hours=1)),
            )
            for index in range(40)
        ]
        early = health_module._Tally(_NOW, sample=9)
        late = health_module._Tally(_NOW + timedelta(days=1), sample=9)
        for rowid, record in enumerate(records, start=1):
            for tally in (early, late):
                tally.add(rowid=rowid, record_id=record.id, record=record, has_vector=True)

        assert early.live == 40
        assert late.live == 0
        assert [candidate.record_id for candidate in early.sample()] == [
            candidate.record_id for candidate in late.sample()
        ]

    async def test_the_density_finds_a_concentration_the_fixture_built(
        self, make_store: _MakeStore, tmp_path: Path
    ) -> None:
        """§8: asserted "over a store built with a known concentration".

        Two stores of the same size with the same store-wide closed proportion,
        differing only in *where* the retired records went. The one that piled them
        into a single topic produces live records whose whole neighbourhood is
        retired; the one that dealt them round-robin produces none. That is #457's
        mechanism seen in the store rather than in a read, and it is why §3 makes
        the figure a distribution: the two stores share a store-wide proportion,
        and only the tail tells them apart.
        """
        even = await self._planted(make_store, tmp_path, name="even", concentration=0.0)
        piled = await self._planted(make_store, tmp_path, name="piled", concentration=1.0)

        assert even.concentration is not None
        assert piled.concentration is not None
        assert even.census == piled.census, "the two stores must differ only in placement"
        null = even.concentration.not_live.value
        assert null is not None
        assert piled.concentration.not_live.value == null

        assert even.concentration.density.maximum is not None
        assert piled.concentration.density.maximum is not None
        assert even.concentration.density.mean is not None
        assert piled.concentration.density.mean is not None

        # The evenly-retired store sits on its null, which is what the null is for.
        assert even.concentration.density.mean == pytest.approx(null, abs=0.05)
        assert even.concentration.density.maximum < 1.0, (
            "an evenly-retired store should reach no fully-retired neighbourhood"
        )
        # The piled one is a heavy right tail on the same null: most live records
        # meet no retirement at all, and the ones inside the well-corrected topic
        # meet nothing else.
        assert piled.concentration.density.median == 0.0
        assert piled.concentration.density.maximum == 1.0, (
            "a live record inside the well-corrected topic should meet nothing but retirements"
        )
        # And this is #799's finding, reproduced: a *mean* would call the piled
        # store the healthier of the two, which is why §3 states a distribution.
        assert piled.concentration.density.mean < even.concentration.density.mean

    @staticmethod
    async def _planted(
        make_store: _MakeStore, tmp_path: Path, *, name: str, concentration: float
    ) -> StoreHealthReport:
        """Plant #799's aged store at one concentration and take a census of it."""
        instants = Instants(
            now=_NOW,
            written=_NOW - timedelta(days=30),
            closed=_NOW - timedelta(days=10),
            opened=_NOW - timedelta(days=20),
        )
        spec = AgedStoreSpec.sized(
            total=600, crowding=30, closed_fraction=0.3, closed_concentration=concentration
        )
        aged = await plant(spec, embedder=ClusteredEmbedder(), instants=instants)
        assert any(planted.topic == HOT_TOPIC for planted in aged.planted)
        path = tmp_path / f"{name}.db"
        store = make_store(now=_NOW, path=path)
        await install(store, aged)
        store.close()
        return _census_of(path, k=10)


class TestTheReadInstant:
    """§8's sixth clause — ``T`` moves the figures and not the sample."""

    async def test_a_lapsing_window_moves_the_figures_and_leaves_the_sample_alone(
        self, make_store: _MakeStore, store_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The record's closure shows up as one member leaving the *evaluated* sample."""
        closes = _NOW + timedelta(hours=1)
        store = make_store()
        await _write(
            store,
            [
                _record("lapsing", "t0 p99 u99", validity=Validity(valid_until=closes)),
                *_plain(11),
            ],
        )
        store.close()
        seen = _samples(monkeypatch)
        clock = _Clock(_NOW)
        reader = StoreHealthReader(store=store_path, now=clock)

        before = reader.report(sample=_ALL, k=3)
        clock.reading = closes + timedelta(hours=1)
        after = reader.report(sample=_ALL, k=3)

        assert seen[0] == seen[1], "the sample moved with the clock"
        assert before.concentration is not None
        assert after.concentration is not None
        assert before.concentration.candidates == after.concentration.candidates == 12
        assert before.concentration.sample == after.concentration.sample == 12
        assert before.census is not None
        assert after.census is not None
        assert (before.census.live, before.census.retired) == (12, 0)
        assert (after.census.live, after.census.retired) == (11, 1)
        assert before.concentration.evaluated == 12
        assert after.concentration.evaluated == 11
        assert _band(before, BeliefBand.DERIVED) == (12, 0)
        assert _band(after, BeliefBand.DERIVED) == (11, 1)
        assert before.read_at == _NOW
        assert after.read_at == closes + timedelta(hours=1)


class TestWhatTheReportCarries:
    """§1's last clause, §6's, and §7's content rules."""

    async def test_it_states_the_instant_every_parameter_and_the_population_size(
        self, make_store: _MakeStore, store_path: Path
    ) -> None:
        """ "A figure reported without them is not one of these figures" (§1)."""
        store = make_store()
        await _write(store, _plain(9))
        store.close()

        rendered = _census_of(store_path, sample=6, k=3).render()

        assert "2026-08-10T12:00:00+0000" in rendered
        assert "sample 6" in rendered
        assert "k 3" in rendered
        assert "records                        9" in rendered
        assert "no vector stored               0" in rendered

    async def test_every_band_and_every_kind_is_stated_including_the_empty_ones(
        self, make_store: _MakeStore, store_path: Path
    ) -> None:
        """§3 states the band fill "for each ``BeliefBand``", not for each band met.

        A store of nothing but ``OBSERVED`` records has no attested belief and no
        asserted one. Omitting those lines would leave a reader to guess whether
        the band was empty or the report forgot it — which is §1's own argument
        about a zero, applied to a count that really was measured.
        """
        store = make_store()
        await _write(store, _plain(6))
        store.close()

        report = _census_of(store_path, k=2)

        assert [fill.band for fill in report.bands] == sorted(BeliefBand, key=lambda b: b.value)
        assert _band(report, BeliefBand.DERIVED) == (6, 0)
        assert _band(report, BeliefBand.ASSERTED) == (0, 0)
        assert _band(report, BeliefBand.ATTESTED) == (0, 0)
        assert [kind for kind, _ in report.by_kind] == sorted(kind.value for kind in MemoryKind)
        rendered = report.render()
        for band in BeliefBand:
            assert f"{band.value:<30} live" in rendered

    async def test_it_carries_no_identifier_no_content_and_no_vector(
        self, make_store: _MakeStore, store_path: Path
    ) -> None:
        """§7's first clause, over a store whose every field is distinctive."""
        store = make_store()
        await _write(
            store,
            [
                _record(
                    "zzsecretidzz",
                    "t0 p0 qqcontentqq",
                    about_person="wwsubjectww",
                    source=MemorySource.USER_ASSERTED,
                ),
                *_plain(5, start=1),
            ],
        )
        store.close()

        rendered = _census_of(store_path, k=2).render()

        assert "zzsecretidzz" not in rendered
        assert "qqcontentqq" not in rendered
        assert "wwsubjectww" not in rendered
        assert "0." in rendered, "a report stating nothing would pass the three assertions above"
        # The labels §7 does permit are here, so the absences above are absences.
        assert MemoryKind.SEMANTIC.value in rendered
        assert BeliefBand.ASSERTED.value in rendered
        assert BeliefBand.DERIVED.value in rendered

    async def test_it_states_no_verdict(self, make_store: _MakeStore, store_path: Path) -> None:
        """§6, at the only place a reader would meet one."""
        store = make_store()
        await _write(store, _plain(6))
        store.close()

        rendered = _census_of(store_path, k=2).render().lower()

        for verdict in ("pass", "fail", "healthy", "unhealthy", "warning", "ok", "should be"):
            assert verdict not in rendered
