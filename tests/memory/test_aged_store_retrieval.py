"""Leg 7's retrieval exit instrument: latency and service on an aged store (#789).

`docs/roadmap.md`'s leg-7 exit test asks that months of use make retrieval
better, not slower, "measured in this leg, as retrieval latency and k-shortfall
against a synthetically aged store". ADR-0112 §7 rules that measurement to be the
obligation itself, and gates every **headroom** change to retrieval behind it:
lifting the KNN ``k`` cap or adopting hybrid retrieval are bets on a frequency,
and this module is where that frequency is read off rather than guessed.

**The k-shortfall it was built to measure no longer exists**, and the instrument
is inverted rather than retired. ADR-0128 §1 binds every eligibility predicate
before the ranking cut, so an ineligible row never enters the candidate set and
the density these cases vary has nothing left to compete with. The sweeps are
kept because the density is exactly what makes the new claim worth anything: a
store that served in full on a clean fixture would prove nothing, and the medians
reported below are the evidence that these queries ran under real pressure. What
was a shortfall *rate* is now a shortfall *count asserted to be zero*, at
filtered-neighbour densities an order of magnitude past the retired budget.

**What it measures.** Two things, over
:class:`~ai_assistant.memory.SqliteMemoryStore` specifically. The store is the
subject and not a stand-in for it: issue #457 records that the shared conformance
suite runs over ``FakeMemoryStore``, which has no KNN and therefore no candidate
ceiling to under-serve from, so nothing in that suite can reach this at all.

1. **Retrieval latency** against the live-record count, so the "not slower" half
   of the exit test is a number. This is the half ADR-0128 §1 could plausibly have
   cost something, since the pre-filter reads more per search; the trip-wire is
   unchanged and the figures are below it.
2. **Service under crowding** — that ``search(query, limit=N, kinds=[k])`` returns
   ``min(N, eligible)`` rows however many ineligible *nearer* neighbours surround
   them. Before ADR-0128 §1 it did not: the store over-fetched
   ``min(N * 8, _VEC_KNN_MAX_K)`` candidates and filtered afterwards, so service
   collapsed once the filtered-neighbour density passed ``fetch_k - N``, and #411
   recorded the arithmetic that made a *larger* ``limit`` fail at a density a
   smaller one survived. What is left of that is the ``k`` cap itself, which is
   the whole of what ``capped`` reports (ADR-0128 §2).

**What it asserts, and what it only reports.** Every case asserts that the store
agrees with :mod:`aged_store`'s independent oracle — the instrument is worth
nothing if it cannot predict the subject — and the sweep cases assert the
qualitative claims that carry the measurement (service is complete at every
density; the fixture really was crowded). The latency numbers are
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
    Ranked,
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
from ai_assistant.memory.sqlite_store import _VEC_KNN_MAX_K
from ai_assistant.testing import FakeTraceSink

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
            traces_sink=FakeTraceSink(),
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
    got = (await store.search(query, limit=limit, kinds=kinds)).records
    return len(got), (time.perf_counter() - started) * 1000.0


async def _measured_search(  # noqa: PLR0913 — the graded call needs all of its context
    store: SqliteMemoryStore,
    ranked: Sequence[Ranked],
    *,
    query: str,
    limit: int,
    kinds: Sequence[MemoryKind] | None,
    where: str,
) -> int:
    """Run one search, grade it against the oracle, and return how many rows it served.

    Every measurement the instrument reports comes through here, because a
    complete answer is only evidence once the ways of faking one are excluded.
    Three things are checked, in the order that makes each one mean something:

    * **Every returned row is eligible.** Checked first and by identity, because
      the distance test below cannot see this: the ineligible records are by
      construction the *nearer* ones, so a leaked ``PREFERENCE`` or window-closed
      row sits comfortably inside any cutoff drawn from the eligible ranking. A
      store that leaked one while dropping an eligible row would otherwise have
      matched the predicted count and passed. Since ADR-0128 §1 this is also the
      check that would catch a pre-filter that is not actually binding: the
      ineligible rows are no longer *dropped* anywhere, they are never fetched.
    * **The rows are the right rows.** The served rows are a prefix of the eligible
      ranking, so a served row's distance can never exceed the last served
      position's. A store that dropped one eligible row and back-filled with a
      farther eligible one fails here. This is where a ``float32`` disagreement at
      the cut lands — which eligible record fills the last slot — and the tolerance
      absorbs it.
    * **The count is exact, with no slack at all.** ``served_prediction`` is now a
      ``min`` of three integers and depends on no ordering, so the oracle and the
      store cannot legitimately disagree about it. The conditional row of slack the
      old KNN-then-filter prediction needed is gone with the prediction: it would
      only ever have absolved a regression that lost an eligible row.
    """
    predicted = served_prediction(ranked, limit=limit)
    count, _ = await _timed_search(store, query, limit=limit, kinds=kinds)
    got = (await store.search(query, limit=limit, kinds=kinds)).records

    eligible = [entry for entry in ranked if entry.eligible]
    eligible_ids = {entry.record_id for entry in eligible}
    for record in got:
        assert record.id in eligible_ids, (
            f"{where}: {record.id} is not eligible for this query, so search returned a row "
            f"its kind, retention or validity-window filter should have dropped"
        )
    if count:
        oracle_distance = {entry.record_id: entry.distance for entry in ranked}
        cutoff = eligible[min(count, len(eligible)) - 1].distance
        for record in got:
            assert oracle_distance[record.id] <= cutoff + _DISTANCE_TOLERANCE, (
                f"{where}: {record.id} is not among the {count} nearest eligible records"
            )

    assert count == predicted, (
        f"{where}: served {count} where the oracle predicts {predicted}. The prediction "
        f"depends on no ordering, so this is a disagreement and not float32"
    )
    return count


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    """The nearest-rank percentile of an already-sorted sample.

    Stated rather than improvised, because the obvious ``int(n * fraction)`` index
    returns the **maximum** for any sample where ``n * fraction`` reaches ``n - 1``
    — at 20 samples an asserted and reported "p95" was the largest observation,
    which overstates the tail and makes the reported figure something other than
    what it is labelled.
    """
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


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
        # one that queried a *wrong* store would report a fast lie that counts. The
        # grading is the same one the k-shortfall cases use — one owner, so the
        # latency volumes cannot drift onto a weaker check than the sweep's.
        assert min(served) == 10, f"a query at live={live} was under-served before any filtering"
        graded = aged.topic_query(0)
        await _measured_search(
            store,
            await aged.rank(graded, kinds=None),
            query=graded,
            limit=10,
            kinds=None,
            where=f"latency volume live={live}",
        )
        ceiling = _LATENCY_FIXED_MS + _LATENCY_PER_RECORD_MS * spec.total
        assert p95 < ceiling, (
            f"p95 {p95:.1f}ms at live={live} exceeds the {ceiling:.1f}ms trip-wire"
        )

    report(pytestconfig, rows)


@pytest.mark.parametrize("closed_fraction", _SWEEP_CLOSED_FRACTIONS)
@pytest.mark.parametrize("crowding", _SWEEP_CROWDINGS)
async def test_no_shortfall_at_any_filtered_neighbour_density(
    make_store: Callable[[str], SqliteMemoryStore],
    profile: Profile,
    pytestconfig: pytest.Config,
    crowding: int,
    closed_fraction: float,
) -> None:
    """The #457 regression at scale: crowding no longer costs a caller anything.

    This case used to *measure* the k-shortfall — how often a kind-filtered search
    under-returned, and at what density — and it reported 0% below a
    filtered-neighbour density of ``fetch_k - limit`` and 100% above it. ADR-0128
    §1 removes the mechanism: an ineligible row never enters the candidate set, so
    the density this sweep varies has nothing left to compete with. The sweep is
    kept and inverted rather than deleted, because the density is exactly what
    makes the claim worth anything — a store that under-served on a clean fixture
    would prove nothing either way, and the reported medians are the evidence that
    these queries ran under real pressure.

    Every query is still graded against the oracle, so a served row is checked to
    be eligible, to be one of the right rows, and to be counted exactly.
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
        count = await _measured_search(
            store,
            ranked,
            query=query,
            limit=_SWEEP_LIMIT,
            kinds=kinds,
            where=f"query {index}, crowding {crowding}, closed {closed_fraction}",
        )
        densities.append(filtered_neighbours(ranked, limit=_SWEEP_LIMIT))
        if count < entitled:
            shortfalls += 1

    report(
        pytestconfig,
        [
            f"no-shortfall  crowding={crowding:>5} closed={closed_fraction:<5} "
            f"live={spec.live:>6} total={spec.total:>6} "
            f"filtered-neighbours(median)={statistics.median(densities):>7.1f} "
            f"max={max(densities):>7} budget={candidate_budget(_SWEEP_LIMIT)} "
            f"shortfall={shortfalls}/{profile.queries}"
        ],
    )

    assert shortfalls == 0, (
        f"{shortfalls} of {profile.queries} queries under-returned while eligible records "
        f"existed — an eligibility predicate is binding after the ranking cut (ADR-0128 §1)"
    )
    # The claim only means something if these queries were actually crowded: at the
    # densities this sweep reaches, the pre-ADR-0128 store lost every eligible row
    # once the density passed `fetch_k - limit`, which was 70 at this limit.
    if closed_fraction >= 0.5:
        assert max(densities) > candidate_budget(_SWEEP_LIMIT), (
            "no query in this sweep saw more filtered nearer neighbours than the whole "
            "candidate budget, so the fixture is not dense enough to prove anything"
        )


async def test_a_concentrated_topic_is_served_in_full_like_an_untouched_one(
    make_store: Callable[[str], SqliteMemoryStore],
    profile: Profile,
    pytestconfig: pytest.Config,
) -> None:
    """The case #457 actually describes, now with the two topics agreeing.

    The sweep above retires a store *evenly*. ADR-0112 §8's claim is local: "a
    well-corrected topic accumulates precisely the filtered-out nearer neighbours
    that eat the over-fetch headroom", so the store-wide number was the wrong number
    to tune on. This case held the store-wide closed fraction at a harmless 50% and
    moved all of it into one topic, and it used to assert the contrast — the
    corrected topic under-returning while the untouched one did not.

    It now asserts the contrast is **gone**, which is the whole of what ADR-0128 §1
    buys and the inversion #457 records: the failure grew with use and grew fastest
    exactly where the user had been most engaged, so a well-corrected topic was the
    topic whose retrieval failed first. Both topics now serve their entitlement, and
    the corrected one's filtered-neighbour count is reported beside it as the
    evidence that it is still the crowded one.
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
        count = await _measured_search(
            store, ranked, query=query, limit=limit, kinds=kinds, where=f"{label} topic"
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
            f"concentrated closure — one topic carries all of it "
            f"(store-wide closed {spec.closed_fraction:.0%}, "
            f"supersede {census['closed_supersede']} / absence {census['closed_absence']})",
            f"{'topic':>11} {'entitled':>9} {'served':>7} {'filtered-nbrs':>14}",
            *(
                f"{label:>11} {entitled:>9} {served:>7} {density:>14}"
                for label, (entitled, served, density) in measured.items()
            ),
        ],
    )

    corrected_entitled, corrected_served, corrected_density = measured["corrected"]
    untouched_entitled, untouched_served, _ = measured["untouched"]
    assert corrected_density > candidate_budget(limit), (
        "the corrected topic is not actually crowded, so this store cannot witness the effect"
    )
    assert corrected_served == corrected_entitled, (
        "the corrected topic under-returned: closure concentrated in one topic still costs "
        "that topic its retrieval, which is the inversion #457 records (ADR-0128 §1)"
    )
    assert untouched_served == untouched_entitled


async def test_the_knn_cap_is_the_only_ceiling_left_and_search_reports_it(
    make_store: Callable[[str], SqliteMemoryStore],
    pytestconfig: pytest.Config,
) -> None:
    """#411's arithmetic, and what replaced it: the ceiling is reported rather than silent.

    This case used to measure the over-fetch clamp — at ``limit`` 512 the fetch was
    the full ``8 x limit`` and the live minority filled the request, at 1024 the
    same fetch was clamped and the identical store under-served. ADR-0128 §1 removes
    the multiple along with the pass it padded for, so neither ``limit`` under-serves
    now and the arithmetic #411 and #115 both record stops having a consequence.

    What is left is the ``k`` cap itself, and it is the whole of what ``capped``
    reports (ADR-0128 §2). The three reads below are the ceiling's three states on a
    store holding more eligible records than the cap:

    * below it — a full page, ``capped`` false, and the store certifies nothing;
    * exactly at it — still a full page, still false, and this is the case an
      earlier draft of §2 made unsatisfiable by reading ``capped`` as "the store
      examined everything";
    * above it — short of what was asked for, and ``capped`` true, which is the
      refusal to certify that #457 says nothing above the store could make.

    The volumes are fixed rather than scaled by the profile: the cap bites at an
    absolute candidate count, so a smaller store would not reach it and a larger one
    would measure nothing further.
    """
    spec = AgedStoreSpec(
        live=_VEC_KNN_MAX_K + 500, topics=1, closed_fraction=0.5, preference_share=0.0, seed=411
    )
    store = make_store("knn-cap")
    aged = await _aged(spec, store)
    query = aged.topic_query(0)
    ranked = await aged.rank(query, kinds=None)
    eligible = eligible_total(ranked)
    assert eligible > _VEC_KNN_MAX_K, "the fixture must hold more eligible records than the cap"

    rows = ["", "the KNN cap — the only ceiling left, and the only thing `capped` reports"]
    rows.append(f"{'limit':>7} {'budget':>8} {'eligible':>9} {'served':>7} {'capped':>7}")
    observed: dict[int, tuple[int, bool]] = {}
    for limit in (_VEC_KNN_MAX_K // 8, _VEC_KNN_MAX_K, _VEC_KNN_MAX_K + 1):
        found = await store.search(query, limit=limit, kinds=None)
        count = await _measured_search(
            store, ranked, query=query, limit=limit, kinds=None, where=f"limit={limit}"
        )
        rows.append(
            f"{limit:>7} {candidate_budget(limit):>8} {eligible:>9} {count:>7} {found.capped!s:>7}"
        )
        observed[limit] = (count, found.capped)
    report(pytestconfig, rows)

    assert candidate_budget(_VEC_KNN_MAX_K // 8) == _VEC_KNN_MAX_K // 8  # no multiple to clamp
    assert candidate_budget(_VEC_KNN_MAX_K + 1) == _VEC_KNN_MAX_K  # the clamp, and the ceiling

    below_served, below_capped = observed[_VEC_KNN_MAX_K // 8]
    assert below_served == _VEC_KNN_MAX_K // 8, "a limit under the cap is served in full"
    assert below_capped is False

    at_served, at_capped = observed[_VEC_KNN_MAX_K]
    assert at_served == _VEC_KNN_MAX_K, "a limit exactly at the cap is still a full page"
    assert at_capped is False, (
        "a full page reports `capped` false however much of the store went unexamined "
        "(ADR-0128 §2's third clause)"
    )

    above_served, above_capped = observed[_VEC_KNN_MAX_K + 1]
    assert above_served == _VEC_KNN_MAX_K, "the cap bounds the read one row short"
    assert above_capped is True, (
        "the ceiling bound this read short of `limit` and the store said nothing about it — "
        "which is the silence #457 is the report of (ADR-0128 §2)"
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
        got = (await store.search(query, limit=limit, kinds=None)).records

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

    ``candidate_budget`` is the store's ``fetch_k`` expression, not a copy of it, so
    a lane that moves the ceiling (#411 part 2) gets a re-measurement rather than a
    red test with a stale 4096 in it. This case fails only if that wiring is broken.

    There is no over-fetch multiple to read any more — ADR-0128 §1 removed it with
    the post-cut pass it padded for — so ``fetch_k`` is ``limit`` under the ceiling
    and the ceiling above it, and the case pins both sides of that boundary.
    """
    assert candidate_budget(1) == 1
    assert candidate_budget(_VEC_KNN_MAX_K - 1) == _VEC_KNN_MAX_K - 1
    assert candidate_budget(_VEC_KNN_MAX_K) == _VEC_KNN_MAX_K
    assert candidate_budget(_VEC_KNN_MAX_K + 1) == _VEC_KNN_MAX_K


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
    topics = 64
    for width in (64, 256, 1024):
        embedder = ClusteredEmbedder(dimensions=width)
        # `tail` begins with `t`, which a prefix-matching parser read as the topic
        # token — every one of these would have shared one centroid, and this case
        # would have asserted nothing about topic separation while appearing to.
        vectors = await embedder.embed([f"t{topic} p0 tail" for topic in range(topics)])

        assert embedder.dimensions == width
        for vector in vectors:
            assert len(vector) == width
            assert math.isclose(math.sqrt(math.sumprod(vector, vector)), 1.0, abs_tol=1e-6)
        # Same position, different topics: the topic token must be what separates
        # them, or the density axis is measuring one cluster wearing many labels.
        assert len({tuple(vector) for vector in vectors}) == topics
        similarities = [math.sumprod(vectors[0], other) for other in vectors[1 : min(topics, 16)]]
        assert max(similarities) < 0.5, (
            f"topics are not separated at width {width}: nearest cross-topic "
            f"similarity {max(similarities):.3f}"
        )

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
