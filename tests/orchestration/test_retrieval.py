"""Tests for the per-band assembler (ADR-0072 §5, ADR-0113 §5 and §6).

ADR-0113 §7's fifth obligation is the reason this file exists rather than another
handful of store conformance clauses: §5's cross-call rule is "the one obligation
here that **no store conformance case can reach**. ``MemoryStoreContract`` drives
one store through one call; §5's cross-call rule is a property of the composition,
so a suite that passes says nothing about it."

The scripted double below is what makes that case deterministic without
concurrency. It stands in for a store whose contents a concurrent fold moves
between two of one turn's reads — which ADR-0113 §5 establishes is reachable on
the live write path, since ``add`` is an upsert on the caller's id and a
``REINFORCE`` fold takes the incoming provenance's source at the target's id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    Attestation,
    BeliefBand,
    MemoryKind,
    MemorySource,
    Provenance,
    SemanticMemory,
)
from ai_assistant.orchestration.retrieval import BAND_PRECEDENCE, assemble_by_band
from ai_assistant.testing import FakeMemoryStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryRecord

_AT = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)

#: One source per band, so a fixture can name a band and get a record in it. The
#: ``DERIVED`` band has two sources and ``OBSERVED`` stands for it here; ADR-0072
#: §4 keeps the two indistinguishable, which is why the filter is keyed on the band.
_SOURCE_FOR: dict[BeliefBand, MemorySource] = {
    BeliefBand.ASSERTED: MemorySource.USER_ASSERTED,
    BeliefBand.ATTESTED: MemorySource.EXTERNAL,
    BeliefBand.DERIVED: MemorySource.OBSERVED,
}


def _record(record_id: str, band: BeliefBand, *, score: float = 0.9) -> MemoryRecord:
    """A live semantic record in ``band``, carrying a relevance ``score``.

    ``search`` populates ``score`` (ADR-0113 §7), so the double's answers do too —
    a composition that dropped or recomputed it would otherwise pass unnoticed.
    """
    source = _SOURCE_FOR[band]
    return SemanticMemory(
        id=record_id,
        content=f"{record_id} content",
        fact=f"{record_id} content",
        score=score,
        provenance=Provenance(
            source=source,
            confidence=1.0 if source is MemorySource.USER_ASSERTED else 0.6,
            last_updated=_AT,
            attestation=(
                Attestation(reported_by="a-source", reported_at=_AT)
                if band is BeliefBand.ATTESTED
                else None
            ),
        ),
    )


class _ScriptedStore(FakeMemoryStore):
    """A store answering each band's ``search`` from a script, and recording the call.

    Only ``search`` is scripted; everything else stays the contract-correct fake, so
    this is a narrow override rather than a hand-rolled mock of the whole store —
    the idiom the rest of these tests use.

    The script is keyed by band and is a *list of answers*, popped in order, so one
    band can answer differently on a second call. Nothing here is bound by the
    contract the real stores are held to: the point of the double is to produce the
    cross-call states ADR-0113 §5 accepts and no single conforming call exhibits.
    """

    def __init__(self, script: dict[BeliefBand, list[list[MemoryRecord]]]) -> None:
        super().__init__(now=lambda: _AT)
        self._script = script
        self.calls: list[tuple[Sequence[BeliefBand] | None, int]] = []

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> list[MemoryRecord]:
        self.calls.append((bands, limit))
        assert bands is not None, "the assembler always scopes its reads to one band"
        assert len(bands) == 1, "one call per band, so a short band cannot hide behind another"
        answers = self._script.get(bands[0], [])
        found = answers.pop(0) if answers else []
        return found[:limit]


async def test_it_reads_one_call_per_band_in_precedence_order() -> None:
    """ADR-0072 §5's order, which ADR-0112 §4 reaffirmed and ADR-0113 §6 affirms."""
    store = _ScriptedStore({})

    await assemble_by_band(store, "q", limit=5)

    assert [bands for bands, _ in store.calls] == [[band] for band in BAND_PRECEDENCE]
    assert BAND_PRECEDENCE == (BeliefBand.ASSERTED, BeliefBand.ATTESTED, BeliefBand.DERIVED)


async def test_it_composes_the_bands_in_precedence_order() -> None:
    """The assembler fills ``ASSERTED`` first, then ``ATTESTED``, then ``DERIVED``.

    Asserted on the composed *order* and not merely on membership: at equal
    relevance an assertion outranks an inference (ADR-0072 §5), and a consumer that
    returned the right set in the wrong order would hand the planner a prompt whose
    precedence is decided by whatever renders it.
    """
    store = _ScriptedStore(
        {
            BeliefBand.ASSERTED: [[_record("a", BeliefBand.ASSERTED)]],
            BeliefBand.ATTESTED: [[_record("t", BeliefBand.ATTESTED)]],
            BeliefBand.DERIVED: [[_record("d", BeliefBand.DERIVED)]],
        }
    )

    composed = await assemble_by_band(store, "q", limit=5)

    assert [record.id for record in composed] == ["a", "t", "d"]
    assert all(record.score is not None for record in composed), "relevance survives assembly"


async def test_one_budget_is_filled_in_order_and_a_short_band_donates_its_remainder() -> None:
    """The budget policy ADR-0113 §6 leaves to this lane, pinned so it is not accidental.

    §6 names "whether a band whose page comes back short donates its remainder to
    the next band" as a real open question. The answer taken is yes, by having one
    budget rather than three shares: each call asks for what remains. So a store
    holding one assertion and many inferences spends the rest of the budget on
    inferences instead of returning one record and three empty slots.
    """
    store = _ScriptedStore(
        {
            BeliefBand.ASSERTED: [[_record("a", BeliefBand.ASSERTED)]],
            BeliefBand.ATTESTED: [[]],
            BeliefBand.DERIVED: [[_record(f"d{i}", BeliefBand.DERIVED) for i in range(5)]],
        }
    )

    composed = await assemble_by_band(store, "q", limit=4)

    assert [record.id for record in composed] == ["a", "d0", "d1", "d2"]
    # Each call asked for what was left, which is what makes the donation happen.
    assert [limit for _, limit in store.calls] == [4, 3, 3]


async def test_a_band_that_fills_the_budget_stops_the_later_reads() -> None:
    """A full budget ends the composition, so the lower bands are never asked.

    Not merely an optimisation: ADR-0113 §8 observes that N band-scoped calls buy N
    independent candidate budgets, and the latency of the extra calls is #789's
    question. Skipping the calls whose results could not be used is the part of that
    cost this lane can decline without deciding anything §8 reserves.
    """
    store = _ScriptedStore(
        {BeliefBand.ASSERTED: [[_record(f"a{i}", BeliefBand.ASSERTED) for i in range(4)]]}
    )

    composed = await assemble_by_band(store, "q", limit=2)

    assert [record.id for record in composed] == ["a0", "a1"]
    assert [bands for bands, _ in store.calls] == [[BeliefBand.ASSERTED]]


async def test_it_deduplicates_across_calls_and_keeps_the_higher_precedence_copy() -> None:
    """ADR-0113 §5's cross-call rule — the obligation no store suite can reach.

    The scenario is a fold moving a record between two of one turn's calls, at a
    stable id. The double returns ``x`` from the ``ATTESTED`` call and then again
    from the ``DERIVED`` call, the second copy carrying derived provenance: the
    record moved bands underneath the composition, which ADR-0113 §5 rules is
    possible and adds no snapshot to prevent.

    Three things are asserted, and ADR-0113 §7 names all three:

    1. ``x`` is retained **once**. A consumer that concatenates presents one belief
       twice under two different bands, which ADR-0072 §6 makes a presentation
       fault.
    2. The copy retained is the **higher-precedence** band's — attested here, so its
       provenance is the ``EXTERNAL`` one and not the ``OBSERVED`` one.
    3. It is charged **once** to that band's budget: the derived band still
       contributes ``d``, so the duplicate did not consume a slot twice.

    The double moves the record *down* the precedence order, which the live writer
    forbids at a stable id — ``_refuse_unsafe_fold`` clause 1 and the corroboration
    arm between them permit only upward moves. ADR-0113 §7 explicitly allows this:
    "The double need not restrict itself to the moves the writer permits — it is
    standing in for a concurrent fold, and the obligation is on the composition."
    It is also the only way to produce a *duplicate* while reading in precedence
    order, because an upward move under that order produces the **miss** the next
    test covers instead.
    """
    moved_up = _record("x", BeliefBand.ATTESTED)
    moved_down = _record("x", BeliefBand.DERIVED)
    store = _ScriptedStore(
        {
            BeliefBand.ASSERTED: [[]],
            BeliefBand.ATTESTED: [[moved_up]],
            BeliefBand.DERIVED: [[moved_down, _record("d", BeliefBand.DERIVED)]],
        }
    )

    composed = await assemble_by_band(store, "q", limit=3)

    assert [record.id for record in composed] == ["x", "d"]
    assert composed[0].provenance.source is MemorySource.EXTERNAL, (
        "the surviving copy must be the higher-precedence band's, not whichever "
        "arrived last (ADR-0113 §5)"
    )


async def test_a_deduplicated_copy_costs_the_band_that_returned_it_a_slot() -> None:
    """The accepted residue of composing against one budget, pinned so it is known.

    Each call asks for what remains, so a lower band whose answer contains a record
    already held comes back one short of what it could have supplied — here the
    derived band is asked for one record, answers with the duplicate, and ``d`` is
    never reached even though the store had it.

    Pinned rather than fixed. The fix is to over-request against an estimate of how
    many duplicates to expect, which is a headroom decision of the kind ADR-0113 §8
    declines to make without #789's measurement, and the read itself already refuses
    a full-page guarantee (§2: "a call may return fewer than ``limit`` records while
    eligible ones exist"). If this ever bites, it is the same conversation as #457.
    """
    store = _ScriptedStore(
        {
            BeliefBand.ASSERTED: [[]],
            BeliefBand.ATTESTED: [[_record("x", BeliefBand.ATTESTED)]],
            BeliefBand.DERIVED: [
                [_record("x", BeliefBand.DERIVED), _record("d", BeliefBand.DERIVED)]
            ],
        }
    )

    composed = await assemble_by_band(store, "q", limit=2)

    assert [record.id for record in composed] == ["x"]
    assert [limit for _, limit in store.calls] == [2, 2, 1]


async def test_a_record_that_moves_up_between_two_calls_is_missed_and_not_recovered() -> None:
    """The residue reading in precedence order buys, asserted as accepted (§5).

    ADR-0113 §5 is explicit that this is "accepted, not closed: no consumer-side
    rule recovers a record no call returned, and this ADR adds no mechanism that
    would". So this test pins the *absence* of a recovery mechanism deliberately —
    it is not a latent bug someone should later "fix" by re-reading a band.

    The scenario is the reachable one: a ``DERIVED`` record folded to ``ATTESTED``
    (ADR-0113 §5's own worked case, the premise of issue #733). Reading high band
    first, it is absent from the attested call because it was not yet promoted, and
    absent from the derived call because it no longer is derived.
    """
    store = _ScriptedStore(
        {
            BeliefBand.ASSERTED: [[]],
            BeliefBand.ATTESTED: [[]],  # not promoted yet when this call ran
            BeliefBand.DERIVED: [[]],  # no longer derived by the time this one did
        }
    )

    composed = await assemble_by_band(store, "q", limit=5)

    assert composed == []


async def test_an_out_of_band_record_is_not_composed_into_the_band_that_returned_it() -> None:
    """ADR-0113 §5's per-call partition, enforced rather than trusted.

    A store may not return a record whose band the caller did not select, and in
    particular may not pad a short page from another band. The store suite proves
    the obligation of each store; this checks the assembler does not *rely* on it,
    because the consequence of a padded page is the one failure the consumer cannot
    otherwise detect — an inference occupying the slot precedence reserved for an
    assertion, presented to the planner as an assertion.
    """
    store = _ScriptedStore(
        {
            # The asserted call pads its empty page with a derived record.
            BeliefBand.ASSERTED: [[_record("pad", BeliefBand.DERIVED)]],
            BeliefBand.ATTESTED: [[]],
            BeliefBand.DERIVED: [[_record("d", BeliefBand.DERIVED)]],
        }
    )

    composed = await assemble_by_band(store, "q", limit=5)

    assert [record.id for record in composed] == ["d"]


@pytest.mark.parametrize("limit", [0, -1])
async def test_a_non_positive_budget_reads_nothing(limit: int) -> None:
    """No budget means no calls, matching ``search``'s own non-positive ``limit``.

    Asserted on the *calls* and not only the result: three reads whose answers are
    discarded would be a silent cost on a path a caller asked for nothing from.
    """
    store = _ScriptedStore({BeliefBand.ASSERTED: [[_record("a", BeliefBand.ASSERTED)]]})

    assert await assemble_by_band(store, "q", limit=limit) == []
    assert store.calls == []


async def test_the_kinds_filter_reaches_every_band_call() -> None:
    """``kinds`` is passed through unchanged; the caller owns which kinds it wants.

    ADR-0074 §6 puts the belief-kind selection in the caller — ``LoopEngine`` asks
    for beliefs so a captured turn does not compete for the retrieval budget — and
    the assembler must not narrow or widen it per band.
    """
    seen: list[Sequence[MemoryKind] | None] = []

    class _KindRecordingStore(_ScriptedStore):
        async def search(
            self,
            query: str,
            *,
            limit: int = 10,
            kinds: Sequence[MemoryKind] | None = None,
            bands: Sequence[BeliefBand] | None = None,
        ) -> list[MemoryRecord]:
            seen.append(kinds)
            return await super().search(query, limit=limit, kinds=kinds, bands=bands)

    store = _KindRecordingStore({})

    await assemble_by_band(store, "q", limit=3, kinds=[MemoryKind.SEMANTIC])

    assert [list(asked or []) for asked in seen] == [[MemoryKind.SEMANTIC]] * len(BAND_PRECEDENCE)


async def test_the_kinds_filter_is_observed_once_for_the_whole_composition() -> None:
    """ADR-0065 §3's clause, owed by the composition and not only by each call.

    Every ``MemoryStore.search`` already snapshots ``kinds`` on its own first
    executed line (#436), so each of the three calls here is individually coherent.
    The composition is not: it reads the caller's sequence three times with two
    awaits in between, so a caller mutating it mid-flight would get an answer whose
    asserted band was filtered on one kind set and whose derived band was filtered
    on another — one result describing two versions of one input, which is what
    ADR-0065 exists to prevent, reappearing one layer above the seam that already
    closed it.

    The mutation is driven from inside the reads, which is where it lands
    deterministically and is the moment a real caller's concurrent task would reach
    it. The caller's own list is asserted to have grown, so the case cannot pass by
    the mutation silently failing to happen.
    """
    caller_kinds = [MemoryKind.SEMANTIC]
    seen: list[tuple[MemoryKind, ...]] = []

    class _MutatingStore(_ScriptedStore):
        async def search(
            self,
            query: str,
            *,
            limit: int = 10,
            kinds: Sequence[MemoryKind] | None = None,
            bands: Sequence[BeliefBand] | None = None,
        ) -> list[MemoryRecord]:
            seen.append(tuple(kinds or ()))
            caller_kinds.append(MemoryKind.PREFERENCE)  # the caller grows its own list
            return await super().search(query, limit=limit, kinds=kinds, bands=bands)

    store = _MutatingStore({})

    await assemble_by_band(store, "q", limit=3, kinds=caller_kinds)

    assert seen == [(MemoryKind.SEMANTIC,)] * len(BAND_PRECEDENCE), (
        "every band must be filtered on the kinds the call began with; a later "
        "band seeing the appended kind is one answer built from two inputs"
    )
    assert caller_kinds == [MemoryKind.SEMANTIC, *([MemoryKind.PREFERENCE] * 3)]


async def test_a_failing_band_read_propagates_rather_than_composing_a_partial_result() -> None:
    """Degradation is the caller's to decide, so the error is not swallowed here.

    ``LoopEngine._retrieve`` catches this and reports ``memory_degraded``. Composing
    what succeeded would be a policy — a partial prompt is a short result that looks
    complete (ADR-0113 §5 warns against reading one as evidence a band is empty) —
    and this lane declined to invent it, filing #805 instead.
    """

    class _FailingStore(_ScriptedStore):
        async def search(
            self,
            query: str,
            *,
            limit: int = 10,
            kinds: Sequence[MemoryKind] | None = None,
            bands: Sequence[BeliefBand] | None = None,
        ) -> list[MemoryRecord]:
            assert bands is not None
            if bands[0] is BeliefBand.DERIVED:
                msg = "derived read is down"
                raise MemoryStoreError(msg)
            return await super().search(query, limit=limit, kinds=kinds, bands=bands)

    store = _FailingStore({BeliefBand.ASSERTED: [[_record("a", BeliefBand.ASSERTED)]]})

    with pytest.raises(MemoryStoreError, match="derived read is down"):
        await assemble_by_band(store, "q", limit=5)
