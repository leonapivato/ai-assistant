"""Leg 7's retrieval exit instrument: latency and k-shortfall on an aged store (#789).

`docs/roadmap.md`'s leg-7 exit test asks that months of use make retrieval
better, not slower, "measured in this leg, as retrieval latency and k-shortfall
against a synthetically aged store". ADR-0112 §7 rules that measurement to be the
obligation itself, and gates every **headroom** change to retrieval behind it:
raising ``_RESULT_OVERFETCH``, lifting the KNN ``k`` cap, or adopting hybrid
retrieval are bets on a frequency, and this module is where that frequency is
read off rather than guessed.

**What it measures.** Two things, over
:class:`~ai_assistant.memory.SqliteMemoryStore` specifically. The store is the
subject and not a stand-in for it: issue #457 records that the shared conformance
suite runs over ``FakeMemoryStore``, which has no KNN and therefore no post-KNN
filter pass to under-serve from, so nothing in that suite can reach this at all.

1. **Retrieval latency** against the live-record count, so the "not slower" half
   of the exit test is a number.
2. **k-shortfall** — how often ``search(query, limit=N, kinds=[k])`` returns
   fewer than ``N`` rows while more than ``N`` eligible rows exist — as a
   function of the filtered-neighbour density that causes it. The store
   over-fetches ``min(N * _RESULT_OVERFETCH, _VEC_KNN_MAX_K)`` candidates and
   filters afterwards, so the shortfall arrives when ineligible *nearer*
   neighbours crowd the eligible ones out of that budget. #411 records the
   arithmetic: past ``limit = _VEC_KNN_MAX_K / _RESULT_OVERFETCH`` (512) the
   effective multiple shrinks below 8, so the same store under-serves a larger
   ``limit`` at a density that a smaller one survives.

**What it asserts, and what it only reports.** Every case asserts that the store
agrees with :mod:`aged_store`'s independent oracle — the instrument is worth
nothing if it cannot predict the subject — and the k-shortfall cases assert the
qualitative claims that carry the measurement (a shortfall appears only under
crowding; the ``limit``-512 boundary is real). The latency numbers are
**reported**, under a deliberately loose ceiling: a wall-clock target asserted in
a test is a claim about the CI runner, and ADR-0112 §7 wants a measurement, not a
threshold nobody chose. The ceiling that is asserted is a regression trip-wire,
sized so only a change of algorithmic order trips it.

**Volume, and how to run the real thing.** The gate profile is sized for the
Definition-of-Done gate. The measurement ADR-0112 §7 gates tuning on is the full
one, run on demand:

```console
$ uv run pytest tests/memory/test_aged_store_retrieval.py --aged-store-scale=full
```

Both profiles run the same tests against the same code; only the volumes differ,
so nothing is skipped and no case exists that only one profile ever executes.
Rows are written straight to the terminal, so the numbers appear on a passing run
as well as a failing one.
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from aged_store import (
    HOT_TOPIC,
    AgedStore,
    AgedStoreSpec,
    ClusteredEmbedder,
    Instants,
    candidate_budget,
    eligible_total,
    filtered_neighbours,
    install,
    plant,
    report,
    served_prediction,
)

from ai_assistant.core.types import MemoryKind
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory.sqlite_store import _RESULT_OVERFETCH, _VEC_KNN_MAX_K

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

pytestmark = pytest.mark.integration

_INSTANTS = Instants(
    now=datetime(2026, 8, 1, tzinfo=UTC),
    written=datetime(2026, 1, 1, tzinfo=UTC),
    closed=datetime(2026, 4, 1, tzinfo=UTC),
    opened=datetime(2026, 2, 1, tzinfo=UTC),
)

#: Rows of slack allowed between the oracle's prediction and the store's answer.
#: The oracle ranks the ``float32`` vectors the store holds, but accumulates the
#: dot product in Python's ``float64`` where ``sqlite-vec`` does its own, so a
#: record sitting *on* the candidate-budget boundary can fall either side of it.
#: One row absorbs that; a second would start absorbing a real disagreement.
_ORACLE_SLACK = 1

#: How far apart the two similarity computations may land before the difference
#: stops being arithmetic. Comfortably above ``float32`` resolution accumulated
#: across the vector width, and orders of magnitude below the separation between
#: two records the fixture places at different positions.
_DISTANCE_TOLERANCE = 1e-5

#: The latency trip-wire: fixed overhead per call, plus a per-live-record
#: allowance. ``search`` is a linear scan of the vector table (``vec0`` keeps no
#: ANN index), so cost is expected to be affine in the population — the ceiling
#: has the same shape, sized an order of magnitude above what an unloaded
#: developer machine measures. It exists to catch a change of *order*, and
#: deliberately not to assert a latency target: ADR-0112 §7 asks for the number,
#: and picking a threshold here would be the guess it forbids.
_LATENCY_FIXED_MS = 25.0
_LATENCY_PER_RECORD_MS = 0.05

#: The realistic k-shortfall sweep. Crowding is records per topical cluster,
#: window-closed ones included, because a closed record occupies a KNN candidate
#: exactly as a live one does. The closed fractions span a store nothing has
#: retired through one where retirement dominates — the direction ADR-0112 §8
#: says an aged store moves in as both producers accumulate. The whole population
#: is held still across the sweep, so the only thing varying is the share of the
#: candidate pool a query cannot be served from.
_SWEEP_CROWDINGS = (100, 1_000)
_SWEEP_CLOSED_FRACTIONS = (0.0, 0.5, 0.75, 0.9)
_SWEEP_LIMIT = 10


@dataclass(frozen=True)
class Profile:
    """How large the instrument runs.

    Attributes:
        latency_volumes: Live-record counts the latency sweep is taken at.
        queries: Searches timed per volume; the p50/p95 are over these.
        sweep_total: Whole population per configuration in the k-shortfall sweep.
    """

    latency_volumes: tuple[int, ...]
    queries: int
    sweep_total: int


_PROFILES = {
    "gate": Profile(latency_volumes=(500, 2_000, 8_000), queries=20, sweep_total=2_000),
    "full": Profile(latency_volumes=(2_000, 8_000, 32_000, 50_000), queries=40, sweep_total=20_000),
}


@pytest.fixture
def profile(aged_store_scale: str) -> Profile:
    """The volume profile this session asked for (``--aged-store-scale``)."""
    return _PROFILES[aged_store_scale]


@pytest.fixture
def make_store(tmp_path: Path) -> Iterator[Callable[[str], SqliteMemoryStore]]:
    """Build stores on the instrument's fixed clock, closed on teardown."""
    created: list[SqliteMemoryStore] = []

    def _make(name: str) -> SqliteMemoryStore:
        store = SqliteMemoryStore(
            path=tmp_path / f"{name}.db",
            embedder=ClusteredEmbedder(),
            now=lambda: _INSTANTS.now,
        )
        created.append(store)
        return store

    yield _make
    for store in created:
        store.close()


async def _aged(spec: AgedStoreSpec, store: SqliteMemoryStore) -> AgedStore:
    """Plant ``spec`` and install it into ``store``.

    The oracle is handed its own embedder instance rather than the store's, so a
    disagreement between the two rankings could never be hidden by shared state.
    """
    aged = await plant(spec, embedder=ClusteredEmbedder(), instants=_INSTANTS)
    await install(store, aged)
    return aged


async def _timed_search(
    store: SqliteMemoryStore, query: str, *, limit: int, kinds: Sequence[MemoryKind] | None
) -> tuple[int, float]:
    """Run one search, returning how many rows came back and how long it took, in ms."""
    started = time.perf_counter()
    got = await store.search(query, limit=limit, kinds=kinds)
    return len(got), (time.perf_counter() - started) * 1000.0


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    """The nearest-rank percentile of an already-sorted sample.

    Stated rather than improvised, because the obvious ``int(n * fraction)`` index
    returns the **maximum** for any sample where ``n * fraction`` reaches ``n - 1``
    — at 20 samples an asserted and reported "p95" was the largest observation,
    which overstates the tail and makes the reported figure something other than
    what it is labelled.
    """
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


async def _grade_against_the_oracle(
    store: SqliteMemoryStore, aged: AgedStore, *, query: str, limit: int
) -> None:
    """Assert one search returned rows that really are among the true nearest.

    Counting rows is not enough to know a timing is a timing of *retrieval*: a
    store that returned any ``limit`` rows at all would satisfy a count assertion
    and every latency ceiling, and the measurement would report a fast wrong
    answer as a healthy one. So each measured volume grades one of its own
    searches rather than borrowing the grounding case's much smaller store.

    The cutoff is taken over the **eligible** ranking, not the whole one. These
    populations are 30% window-closed, and a closed record is nearer to the query
    than plenty of live ones; grading against the unfiltered ranking would demand
    that ``search`` return rows ADR-0045 §6 requires it to hide.
    """
    ranked = await aged.rank(query, kinds=None)
    cutoff = [entry for entry in ranked if entry.eligible][limit - 1].distance
    oracle_distance = {entry.record_id: entry.distance for entry in ranked}
    got = await store.search(query, limit=limit, kinds=None)
    assert len(got) == limit
    for record in got:
        assert oracle_distance[record.id] <= cutoff + _DISTANCE_TOLERANCE, (
            f"{record.id} is not among the {limit} nearest live records of a "
            f"{aged.spec.total}-record store"
        )


async def test_retrieval_latency_scales_with_the_live_record_count(
    make_store: Callable[[str], SqliteMemoryStore],
    profile: Profile,
    pytestconfig: pytest.Config,
) -> None:
    """Measure ``search`` latency against store size — the exit test's "not slower" half."""
    rows = ["", "k-shortfall instrument — retrieval latency over SqliteMemoryStore.search"]
    rows.append(f"{'live':>8} {'total':>8} {'p50 ms':>9} {'p95 ms':>9} {'max ms':>9} {'us/rec':>8}")
    for live in profile.latency_volumes:
        spec = AgedStoreSpec(live=live, topics=max(1, live // 40), closed_fraction=0.3)
        store = make_store(f"latency-{live}")
        aged = await _aged(spec, store)

        latencies: list[float] = []
        served: list[int] = []
        for index in range(profile.queries):
            count, elapsed = await _timed_search(
                store, aged.topic_query(index), limit=10, kinds=None
            )
            latencies.append(elapsed)
            served.append(count)

        latencies.sort()
        p50 = _percentile(latencies, 0.50)
        p95 = _percentile(latencies, 0.95)
        rows.append(
            f"{spec.live:>8} {spec.total:>8} {p50:>9.2f} {p95:>9.2f} "
            f"{latencies[-1]:>9.2f} {p50 * 1000 / spec.total:>8.2f}"
        )

        # A measurement that queried an empty store would report a fast lie, and
        # one that queried a *wrong* store would report a fast lie that counts.
        assert min(served) == 10, f"a query at live={live} was under-served before any filtering"
        await _grade_against_the_oracle(store, aged, query=aged.topic_query(0), limit=10)
        ceiling = _LATENCY_FIXED_MS + _LATENCY_PER_RECORD_MS * spec.total
        assert p95 < ceiling, (
            f"p95 {p95:.1f}ms at live={live} exceeds the {ceiling:.1f}ms trip-wire"
        )

    report(pytestconfig, rows)


@pytest.mark.parametrize("closed_fraction", _SWEEP_CLOSED_FRACTIONS)
@pytest.mark.parametrize("crowding", _SWEEP_CROWDINGS)
async def test_k_shortfall_against_filtered_neighbour_density(
    make_store: Callable[[str], SqliteMemoryStore],
    profile: Profile,
    pytestconfig: pytest.Config,
    crowding: int,
    closed_fraction: float,
) -> None:
    """Measure how often a kind-filtered search under-returns, and at what density.

    Every query is graded against the oracle, so a shortfall is attributed rather
    than merely observed: the reported density is the count of ineligible records
    ranked *nearer* than the last row the caller asked for, which is exactly what
    the over-fetch budget was competing with.
    """
    spec = AgedStoreSpec.sized(
        total=profile.sweep_total, crowding=crowding, closed_fraction=closed_fraction
    )
    store = make_store(f"sweep-{crowding}-{closed_fraction}")
    aged = await _aged(spec, store)
    kinds = [MemoryKind.SEMANTIC]

    shortfalls = 0
    densities: list[int] = []
    for index in range(profile.queries):
        query = aged.topic_query(index)
        ranked = await aged.rank(query, kinds=kinds)
        entitled = min(_SWEEP_LIMIT, eligible_total(ranked))
        predicted = served_prediction(ranked, limit=_SWEEP_LIMIT)
        count, _ = await _timed_search(store, query, limit=_SWEEP_LIMIT, kinds=kinds)

        assert abs(count - predicted) <= _ORACLE_SLACK, (
            f"store served {count} where the oracle predicts {predicted} "
            f"(query {index}, crowding {crowding}, closed {closed_fraction})"
        )
        densities.append(filtered_neighbours(ranked, limit=_SWEEP_LIMIT))
        if count < entitled:
            shortfalls += 1

    rate = shortfalls / profile.queries
    report(
        pytestconfig,
        [
            f"k-shortfall  crowding={crowding:>5} closed={closed_fraction:<5} "
            f"live={spec.live:>6} total={spec.total:>6} "
            f"filtered-neighbours(median)={statistics.median(densities):>7.1f} "
            f"budget={candidate_budget(_SWEEP_LIMIT)} "
            f"shortfall={shortfalls}/{profile.queries} ({rate:.0%})"
        ],
    )

    # The measurement's own claim: a shortfall is a crowding effect, never a
    # volume effect. It cannot happen while the ineligible records nearer than
    # the last wanted row fit inside the candidate budget.
    budget = candidate_budget(_SWEEP_LIMIT)
    if shortfalls:
        assert max(densities) >= budget - _SWEEP_LIMIT, (
            "a shortfall was observed without enough filtered nearer neighbours to cause one"
        )


async def test_k_shortfall_concentrates_where_correction_does(
    make_store: Callable[[str], SqliteMemoryStore],
    profile: Profile,
    pytestconfig: pytest.Config,
) -> None:
    """Measure the case #457 actually describes: one well-corrected topic, the rest healthy.

    The sweep above retires a store *evenly*, and at an even 50% closure no query
    under-returns. But ADR-0112 §8's claim is local, not global — "a well-corrected
    topic accumulates precisely the filtered-out nearer neighbours that eat the
    over-fetch headroom". This case holds the store-wide closed fraction at that
    same harmless 50% and moves all of it into one topic. If the claim is right,
    the store-wide number is the wrong number to tune on.
    """
    limit = _SWEEP_LIMIT
    kinds = [MemoryKind.SEMANTIC]
    spec = AgedStoreSpec.sized(
        total=profile.sweep_total, crowding=100, closed_fraction=0.5, closed_concentration=1.0
    )
    store = make_store("concentrated")
    aged = await _aged(spec, store)

    measured: dict[str, tuple[int, int, int]] = {}
    for label, topic in (("corrected", HOT_TOPIC), ("untouched", HOT_TOPIC + 1)):
        query = aged.topic_query(topic)
        ranked = await aged.rank(query, kinds=kinds)
        predicted = served_prediction(ranked, limit=limit)
        count, _ = await _timed_search(store, query, limit=limit, kinds=kinds)
        assert abs(count - predicted) <= _ORACLE_SLACK, (
            f"store served {count} on the {label} topic where the oracle predicts {predicted}"
        )
        measured[label] = (
            min(limit, eligible_total(ranked)),
            count,
            filtered_neighbours(ranked, limit=limit),
        )

    census = aged.census()
    report(
        pytestconfig,
        [
            "",
            f"k-shortfall instrument — closure concentrated in one topic "
            f"(store-wide closed {spec.closed_fraction:.0%}, "
            f"supersede {census['closed_supersede']} / absence {census['closed_absence']})",
            f"{'topic':>11} {'entitled':>9} {'served':>7} {'filtered-nbrs':>14}",
            *(
                f"{label:>11} {entitled:>9} {served:>7} {density:>14}"
                for label, (entitled, served, density) in measured.items()
            ),
        ],
    )

    corrected_entitled, corrected_served, _ = measured["corrected"]
    untouched_entitled, untouched_served, _ = measured["untouched"]
    assert corrected_served < corrected_entitled, (
        "the corrected topic served its full request, so this store is not concentrated enough "
        "to measure the effect"
    )
    assert untouched_served == untouched_entitled, (
        "the untouched topic under-returned too, so the contrast is not attributable to closure"
    )


async def test_k_shortfall_arrives_earlier_once_the_knn_cap_clamps_the_over_fetch(
    make_store: Callable[[str], SqliteMemoryStore],
    pytestconfig: pytest.Config,
) -> None:
    """Measure #411's arithmetic bound: past ``limit`` 512 the effective multiple shrinks.

    One dense cluster, four fifths of it window-closed. At ``limit`` 512 the
    over-fetch is the full ``8 x limit`` and the live minority still fills the
    request; at ``limit`` 1024 the same fetch is clamped to ``_VEC_KNN_MAX_K``,
    the effective multiple is 4, and the identical store under-serves. Same
    population, same query, same filter — only the arithmetic differs.

    The volumes here are fixed rather than scaled by the profile: the clamp bites
    at an absolute candidate count, so a smaller store would not reach it and a
    larger one would measure nothing further.
    """
    boundary = _VEC_KNN_MAX_K // _RESULT_OVERFETCH
    spec = AgedStoreSpec(
        live=boundary * 3, topics=1, closed_fraction=0.8, preference_share=0.0, seed=411
    )
    store = make_store("knn-cap")
    aged = await _aged(spec, store)
    query = aged.topic_query(0)
    ranked = await aged.rank(query, kinds=None)

    rows = ["", "k-shortfall instrument — the over-fetch clamp at limit = 512 (#411)"]
    rows.append(f"{'limit':>7} {'budget':>8} {'multiple':>9} {'entitled':>9} {'served':>7}")
    observed: dict[int, tuple[int, int]] = {}
    for limit in (boundary, boundary * 2):
        entitled = min(limit, eligible_total(ranked))
        predicted = served_prediction(ranked, limit=limit)
        count, _ = await _timed_search(store, query, limit=limit, kinds=None)
        assert abs(count - predicted) <= _ORACLE_SLACK, (
            f"store served {count} at limit={limit} where the oracle predicts {predicted}"
        )
        budget = candidate_budget(limit)
        rows.append(f"{limit:>7} {budget:>8} {budget / limit:>9.2f} {entitled:>9} {count:>7}")
        observed[limit] = (entitled, count)
    report(pytestconfig, rows)

    assert candidate_budget(boundary) == boundary * _RESULT_OVERFETCH
    assert candidate_budget(boundary * 2) == _VEC_KNN_MAX_K

    entitled_at_boundary, served_at_boundary = observed[boundary]
    assert served_at_boundary == entitled_at_boundary, (
        "the unclamped over-fetch should still have served this store in full"
    )
    entitled_above, served_above = observed[boundary * 2]
    assert served_above < entitled_above, (
        f"expected a shortfall past the clamp: served {served_above} of {entitled_above} entitled"
    )


async def test_the_oracle_agrees_with_an_unfiltered_search(
    make_store: Callable[[str], SqliteMemoryStore],
    pytestconfig: pytest.Config,
) -> None:
    """Ground the instrument: with nothing filtered out, the store returns the oracle's top rows.

    The measurements above trust the oracle's ranking to attribute a shortfall.
    That trust is only worth what this case establishes — that on a population
    where nothing is ineligible, every row the store returns is one of the true
    nearest, and the similarity it reports is the one the oracle computes.

    The comparison is by distance and not by id order, and
    :data:`_DISTANCE_TOLERANCE` says why: the oracle accumulates its dot product
    in ``float64`` where ``sqlite-vec`` uses its own arithmetic over the same
    ``float32`` components, so two records within that tolerance of each other
    may legitimately swap across the cut. Grading the *ranking* rather than the
    permutation is what makes the instrument robust without making it lax — a
    record outside the true top-``limit`` by more than the tolerance still fails.
    """
    limit = 10
    spec = AgedStoreSpec(live=400, topics=8, closed_fraction=0.0, preference_share=0.0, seed=7)
    store = make_store("oracle")
    aged = await _aged(spec, store)

    worst = 0.0
    for topic in range(spec.topics):
        query = aged.topic_query(topic)
        ranked = await aged.rank(query, kinds=None)
        oracle_distance = {entry.record_id: entry.distance for entry in ranked}
        got = await store.search(query, limit=limit, kinds=None)

        assert len(got) == limit
        cutoff = ranked[limit - 1].distance
        scores: list[float] = []
        for record in got:
            assert record.score is not None, "search populates a score on every row it returns"
            assert oracle_distance[record.id] <= cutoff + _DISTANCE_TOLERANCE, (
                f"{record.id} is not among the true nearest {limit} for topic {topic}"
            )
            assert record.score == pytest.approx(
                1.0 - oracle_distance[record.id], abs=_DISTANCE_TOLERANCE
            )
            worst = max(worst, abs(record.score - (1.0 - oracle_distance[record.id])))
            scores.append(record.score)
        assert scores == sorted(scores, reverse=True)

    report(
        pytestconfig,
        [
            f"oracle agreement: {spec.topics} topics x top-{limit}, "
            f"worst similarity disagreement {worst:.2e}"
        ],
    )


def test_the_instrument_reads_the_constants_it_is_measuring() -> None:
    """Guard the instrument's premise: the budget it predicts is the store's own.

    ``candidate_budget`` is the store's ``fetch_k`` expression, not a copy of it,
    so a lane that raises ``_RESULT_OVERFETCH`` under ADR-0112 §7's gate gets a
    re-measurement rather than a red test with a stale 8 in it. This case fails
    only if that wiring is broken.
    """
    assert candidate_budget(1) == _RESULT_OVERFETCH
    assert candidate_budget(_VEC_KNN_MAX_K) == _VEC_KNN_MAX_K
    assert candidate_budget(_VEC_KNN_MAX_K // _RESULT_OVERFETCH) == _VEC_KNN_MAX_K


def test_the_reported_percentile_is_the_percentile_and_not_the_maximum() -> None:
    """Guard the figure the latency table publishes, on a sample whose answer is known.

    The naive ``ordered[int(n * 0.95)]`` returns the largest observation for
    ``n = 20``, which is what this instrument first reported as a p95 — a labelled
    number that was in fact a different statistic. Nearest-rank is the convention
    and this is where it is pinned.
    """
    sample = [float(value) for value in range(1, 21)]

    assert _percentile(sample, 0.95) == 19.0
    assert _percentile(sample, 0.95) != max(sample)
    assert _percentile(sample, 0.50) == 10.0
    assert _percentile(sample, 1.0) == max(sample)
    assert _percentile([4.0], 0.95) == 4.0
    for count in (1, 2, 5, 19, 20, 40):
        ordered = [float(value) for value in range(count)]
        assert _percentile(ordered, 0.95) == ordered[math.ceil(0.95 * count) - 1]


async def test_the_embedder_honours_a_width_other_than_the_default() -> None:
    """Guard the embedder's configurable width, which the fixture advertises.

    Term indices are drawn modulo the *instance's* width; drawing them modulo the
    module default made every non-default width an ``IndexError`` at embed time,
    which no measurement exercised because none varies it.

    The width floor is asserted here too, and it is not cosmetic: below it the
    three contributions crowd into the same buckets and can cancel to the zero
    vector, which a cosine KNN cannot rank and which would void every distance the
    oracle computes from it. Sweeping 200,000 texts at width 1 turned up 23 such
    cancellations, so the floor closes a reachable hole rather than a theoretical
    one.
    """
    for width in (64, 256, 1024):
        embedder = ClusteredEmbedder(dimensions=width)
        vectors = await embedder.embed([f"t{topic} p{topic} tail" for topic in range(64)])

        assert embedder.dimensions == width
        for vector in vectors:
            assert len(vector) == width
            assert math.isclose(math.sqrt(math.sumprod(vector, vector)), 1.0, abs_tol=1e-6)

    with pytest.raises(ValueError, match="dimensions must be >= 64"):
        ClusteredEmbedder(dimensions=1)
    # A NaN and an infinity both fail `spread < 0.0`, so only the finite check
    # refuses them — and an infinite spread normalises to a vector of NaNs, which
    # ranks against nothing and loses no comparison it should lose.
    for bad in (-1.0, math.inf, math.nan):
        with pytest.raises(ValueError, match="spread a finite value"):
            ClusteredEmbedder(spread=bad)


def test_a_sized_spec_refuses_a_population_it_cannot_actually_plant() -> None:
    """Guard ``sized``'s one promise: the population it builds is the one requested.

    ``closed`` is derived from ``live``, so clamping ``live`` up to 1 re-inflated
    ``total`` through the derivation — a 2,000-record request at 99.99% closure
    silently became a **10,000**-record store, and a sweep would have reported
    numbers against the volume it asked for rather than the one it measured.
    """
    for closed_fraction in _SWEEP_CLOSED_FRACTIONS:
        spec = AgedStoreSpec.sized(total=2_000, crowding=100, closed_fraction=closed_fraction)
        assert spec.total == 2_000
        assert spec.closed == pytest.approx(2_000 * closed_fraction, abs=1)

    with pytest.raises(ValueError, match="leaves no live record"):
        AgedStoreSpec.sized(total=2_000, crowding=100, closed_fraction=0.9999)
    # Zero reached a raw ZeroDivisionError; a negative silently collapsed the
    # store to one topic, reporting a density nobody asked for.
    for crowding in (0, -5):
        with pytest.raises(ValueError, match="must both be >= 1"):
            AgedStoreSpec.sized(total=2_000, crowding=crowding, closed_fraction=0.5)
    # `total` is met exactly or not at all. Two roundings compose, so some
    # requests have no live count that lands on them; the near miss is refused
    # rather than returned under the requested label.
    with pytest.raises(ValueError, match="no live count yields exactly 3"):
        AgedStoreSpec.sized(total=3, crowding=1, closed_fraction=0.5)
    for total in range(2, 400):
        for fraction in (0.0, 0.25, 0.5, 0.75, 0.8, 0.9):
            try:
                spec = AgedStoreSpec.sized(total=total, crowding=10, closed_fraction=fraction)
            except ValueError:
                continue
            assert spec.total == total, f"total={total} fraction={fraction} drifted"


def test_the_instants_refuse_a_timeline_that_leaves_closed_records_live() -> None:
    """Guard the fixture's premise: a record it calls window-closed is closed at ``now``.

    This is the failure that would not announce itself. With ``closed`` after
    ``now`` every ``SUPERSEDE`` and ``ABSENCE`` record is still live, so the
    planted population consumes no candidates as filtered rows — and the
    instrument would publish a k-shortfall rate against a store that was never
    aged, with a census that counts exactly what it meant to plant.
    """
    ordered = _INSTANTS
    assert ordered.opened < ordered.closed <= ordered.now

    with pytest.raises(ValueError, match="closed must not be after now"):
        Instants(
            now=datetime(2026, 3, 1, tzinfo=UTC),
            written=datetime(2026, 1, 1, tzinfo=UTC),
            closed=datetime(2026, 4, 1, tzinfo=UTC),
            opened=datetime(2026, 2, 1, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="opened must precede closed"):
        Instants(
            now=ordered.now,
            written=ordered.written,
            closed=ordered.opened,
            opened=ordered.closed,
        )
    with pytest.raises(ValueError, match="written must not be after now"):
        Instants(
            now=ordered.now,
            written=datetime(2027, 1, 1, tzinfo=UTC),
            closed=ordered.closed,
            opened=ordered.opened,
        )
    # A naive instant used to reach the ordering comparison first and surface as
    # a raw TypeError about offsets, which says nothing about the timeline.
    with pytest.raises(ValueError, match="opened is not"):
        Instants(
            now=ordered.now,
            written=ordered.written,
            closed=ordered.closed,
            opened=datetime(2026, 2, 1),  # noqa: DTZ001 — naive on purpose; this is the refusal
        )
