"""ADR-0110's absence reconciliation: what a covered reading's absence closes.

The decision this file pins is narrow and its narrowness is the point. §3 lets a
validity window close on a record's *absence from a reading* only where four
conditions hold together, and each of them is here as its own case — because
every one of them is load-bearing, and three of them exist to stop a close rather
than to cause one.

**Condition 3 is asked of the extent, not of the record's own window** (ADR-0117
§3), and the helpers below are built in that shape rather than in ADR-0110 §3's
original one. A producer states where its entry lies in the *source's* world
through ``Attestation.extent``; the envelope validity window keeps its one
operational job and states nothing (ADR-0045 §2, ADR-0117 §4). So the fixtures
here carry a **fully open** window — which is what a conforming reader now
proposes — and earn their demotability from the extent alone. ADR-0117 §1 is why:
``Validity.live_at`` gates retrieval, this very enumeration *and* conflict
detection, so a window that stated a forward-looking entry's position would put
the record out of reach of all three.

**Which records are reachable at all is still decided jointly by §3 and §6.** §6
rules the enumeration to be ``list_beliefs``, which honours both read-time axes
before the cut — so only a belief **live at ``now``** is ever a candidate. §3 then
requires the declared extent to lie wholly inside the coverage, and a record whose
attestation declares none satisfies it for no reading at all.

**The serialisation cases are not ordinary tests.** ADR-0110 §5a refuses this
mechanism outright unless its selection and its closes are serialised against
every other writer on the store, and names the composition that satisfies it: the
reconciliation shares the single serialised writer's lock (#262). Nothing
mechanical would notice that guarantee being lost — a reconciliation holding its
own store handle passes every other test in this file — so the two cases at the
end assert the *shape* that makes it true, and not only the behaviour it
produces.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError, UnresolvedEvidenceError
from ai_assistant.core.types import (
    Attestation,
    DataTier,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryIngestResult,
    MemorySource,
    MemoryUpdateProposal,
    MemoryWriteMode,
    PreferenceMemory,
    Provenance,
    ReadCoverage,
    ReportedExtent,
    SemanticMemory,
    SourceReading,
    Validity,
)
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor
from ai_assistant.testing import FakeTraceSink

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.core.types import BeliefBand, MemoryKind, MemoryRecord, MemoryWrite

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_HORIZON = _NOW + timedelta(days=30)
_SOURCE = "calendar:work"


def _fixed_now() -> datetime:
    return _NOW


def _coverage() -> ReadCoverage:
    """What a forward-looking calendar read exhausts: everything up to a horizon.

    ``covers_from`` is left open deliberately. A read that exhausted "the next
    thirty days" has nothing to say about where an entry *started* — an entry that
    began last week and runs until Friday is inside what the read covered — and
    setting ``covers_from=now`` would exclude every record already in progress,
    which is most of what is live.
    """
    return ReadCoverage(covers_until=_HORIZON)


def _covered_extent(*, days_out: int = 1) -> ReportedExtent:
    """An entry the source places inside :func:`_coverage`.

    The shape §3 condition 3 needs: a bounded end says where in the source's world
    this entry stops, and an open start is contained because ``_coverage`` leaves
    ``covers_from`` open too. Nothing here touches the record's liveness — under
    ADR-0117 §3 the two are independent, which is the whole point of the change.
    """
    return ReportedExtent(extends_until=_NOW + timedelta(days=days_out))


def _attested(  # noqa: PLR0913 — an id and one keyword per axis a case may vary independently
    record_id: str,
    *,
    reported_by: str = _SOURCE,
    extent: ReportedExtent | None = None,
    states_extent: bool = True,
    validity: Validity | None = None,
    content: str | None = None,
) -> MemoryRecord:
    """An attested belief, in the shape a calendar reader's proposal lands in.

    The window is **open** unless a case says otherwise, because that is what a
    conforming producer now proposes (ADR-0117 §4): the belief is live,
    retrievable and visible to the fold, and its position is stated by ``extent``.

    ``content`` is overridable so a re-read can be modelled honestly: a reader
    mints a **fresh id** for every record it proposes (ADR-0092 §6), so a
    re-reported entry is folded by *similarity* rather than by id, and identical
    text is the one case neither matcher can miss.

    Args:
        record_id: The id to store it at.
        reported_by: Condition 1's axis.
        extent: Condition 3's axis. ``None`` takes :func:`_covered_extent`.
        states_extent: ``False`` builds a record whose attestation declares **no**
            extent — the state every belief stored before ADR-0117 is in, and the
            one that is demotable by no reading. A separate flag rather than
            ``extent=None`` so that "take the default" and "state nothing" cannot
            be spelled the same way.
        validity: The envelope window, for the cases that are *about* it.
        content: The belief's text.
    """
    text = content if content is not None else f"the entry {record_id} names"
    stated = (extent if extent is not None else _covered_extent()) if states_extent else None
    return PreferenceMemory(
        id=record_id,
        content=text,
        preference=text,
        validity=validity if validity is not None else Validity(),
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=0.6,
            last_updated=_WHEN,
            attestation=Attestation(reported_by=reported_by, reported_at=_WHEN, extent=stated),
        ),
    )


def _asserted(record_id: str) -> MemoryRecord:
    """A user's own belief. It carries no attestation, so §3 cannot reach it."""
    return PreferenceMemory(
        id=record_id,
        content=f"what the user said in {record_id}",
        preference=f"what the user said in {record_id}",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN
        ),
    )


def _stored(*record_ids: str) -> tuple[MemoryIngestResult, ...]:
    """Ingest results that left each id live — §4's definition of *present*."""
    return tuple(
        MemoryIngestResult(
            record_id=record_id,
            decision=MemoryDecision(
                kind=MemoryDecisionKind.REINFORCE, reason="unchanged", target_id=record_id
            ),
        )
        for record_id in record_ids
    )


def _stored_nothing() -> MemoryIngestResult:
    """The result a ``REJECT`` or an ``ASK_USER`` deferral leaves behind (§4)."""
    return MemoryIngestResult(
        record_id=None,
        decision=MemoryDecision(kind=MemoryDecisionKind.ASK_USER, reason="ask the user"),
    )


def _reading(
    *,
    proposals: tuple[MemoryUpdateProposal, ...] = (),
    coverage: ReadCoverage | None,
) -> SourceReading:
    """One reader pass, as ADR-0115 §1's member takes it."""
    return SourceReading(source=_SOURCE, read_at=_NOW, proposals=proposals, coverage=coverage)


def _store() -> InMemoryMemoryStore:
    return InMemoryMemoryStore(now=_fixed_now)


def _ingestor(store: MemoryStore) -> MemoryIngestor:
    return MemoryIngestor(
        traces_sink=FakeTraceSink(), store=store, policy=DefaultMemoryPolicy(), now=_fixed_now
    )


async def _window_of(store: MemoryStore, record_id: str) -> Validity:
    """The record's window, read through ``export``.

    ``get`` would not do: a closed record is off the read path and ``get`` returns
    ``None`` for it (ADR-0045 §6), which is the behaviour being *relied on* rather
    than a way to observe it. ``export`` returns retained records whether their
    window is open or closed, which is the point of the "invalidate, don't delete"
    ruling this whole mechanism sits on — nothing is deleted, and every closed
    record stays exportable.
    """
    records = {record.id: record for record in await store.export()}
    assert record_id in records, f"{record_id!r} is not retained at all"
    return records[record_id].validity


async def _is_live(store: MemoryStore, record_id: str) -> bool:
    """Whether the record is still on the read path — ``get`` answers exactly this."""
    return await store.get(record_id) is not None


async def _reconcile(
    ingestor: MemoryIngestor,
    *,
    source: str,
    coverage: ReadCoverage,
    results: Sequence[MemoryIngestResult],
) -> int:
    """Drive §3's and §4's rules directly, under the hold they run inside.

    ``_close_absent`` is private precisely because ADR-0110 §5a requires it to run
    inside :meth:`MemoryIngestor.ingest_reading`'s single lock hold — reachable
    from outside it, it would *be* the unserialised read-modify-write §5a refuses.
    The cases below are about the **rules**, which are the same whatever holds the
    lock, so they take the lock and call it. That the real path holds it across the
    ingest as well is a different property, and the two cases at the end of this
    module are what pin it.

    Counts what came back rather than returning it. ADR-0119 §8 made
    ``_close_absent`` hand out the closed **ids**, so a trace can carry them under
    ``TraceRecordSet.RETIRED``; every case below is about *how many* windows the
    rules close, and the ids themselves are pinned where the trace is.
    """
    async with ingestor._lock:
        closed = await ingestor._close_absent(source=source, coverage=coverage, results=results)
    return len(closed)


# --- §3: the four conditions, one case each ---------------------------------


async def test_a_covered_absence_closes_the_window() -> None:
    """All four conditions met: the source looked, and did not find it."""
    store = _store()
    await store.add(_attested("gone"))

    closed = await _reconcile(
        _ingestor(store), source=_SOURCE, coverage=_coverage(), results=_stored("still-here")
    )

    assert closed == 1
    assert (await _window_of(store, "gone")).valid_until == _NOW
    # Off the read path, and still retained — "invalidate, don't delete".
    assert not await _is_live(store, "gone")


async def test_a_record_another_source_reported_is_untouched() -> None:
    """§3 condition 1 — this reading speaks only for what its own source said."""
    store = _store()
    await store.add(_attested("theirs", reported_by="calendar:personal"))

    closed = await _reconcile(
        _ingestor(store), source=_SOURCE, coverage=_coverage(), results=_stored("mine")
    )

    assert closed == 0
    assert (await _window_of(store, "theirs")).valid_until is None
    assert await _is_live(store, "theirs")


async def test_an_assertion_inside_the_coverage_is_unreachable() -> None:
    """§3 condition 1 again, and the reason #729 asks for it.

    "ASSERTED is never auto-demotable" holds here **by construction** rather than
    by a check: ``Provenance.attestation`` is present exactly when the band is
    ``ATTESTED`` (ADR-0092 §1), so an assertion can never satisfy condition 1 —
    the stronger form ADR-0080 §2 preferred for the same band.
    """
    store = _store()
    await store.add(_asserted("the-users-own"))

    closed = await _reconcile(
        _ingestor(store), source=_SOURCE, coverage=_coverage(), results=_stored("something-else")
    )

    assert closed == 0
    assert await _is_live(store, "the-users-own")


async def test_a_record_that_states_no_extent_is_never_absence_demotable() -> None:
    """§3 condition 3 — the clause that separates a bounded read from a deletion.

    A source that states no position for an entry has told a bounded reading
    nothing about the region that entry occupies, so no such reading can have
    exhausted it. Closing anyway would be doing exactly what ADR-0093 §4's
    indistinguishability argument forbids: retracting on the strength of having
    looked somewhere else.

    It is also the state **every belief stored before ADR-0117** is in, which is
    what makes the field's arrival need no migration: an existing record decodes
    with no extent and acquires no new way to be retired (§9).
    """
    store = _store()
    await store.add(_attested("states-no-position", states_extent=False))

    closed = await _reconcile(
        _ingestor(store), source=_SOURCE, coverage=_coverage(), results=_stored("other")
    )

    assert closed == 0
    assert (await _window_of(store, "states-no-position")).valid_until is None


async def test_a_bounded_window_does_not_substitute_for_a_missing_extent() -> None:
    """§3's "whatever its envelope validity window", pinned as its own case.

    The carrier moved rather than widened (ADR-0117 §3), so the interval ADR-0110
    §3 originally named is now simply not consulted. A record bounded exactly as
    that reading asked — ``valid_until`` inside the coverage — is still demotable
    by nothing, because it states no position in the source's world.

    Without this case the change of operand would be indistinguishable from a rule
    that accepted *either* carrier, which is a rule two writers could implement
    differently while both passing.
    """
    store = _store()
    await store.add(
        _attested(
            "bounded-but-silent",
            states_extent=False,
            validity=Validity(valid_until=_NOW + timedelta(days=1)),
        )
    )

    closed = await _reconcile(
        _ingestor(store), source=_SOURCE, coverage=_coverage(), results=_stored("other")
    )

    assert closed == 0
    assert await _is_live(store, "bounded-but-silent")


async def test_a_belief_whose_entry_lies_ahead_of_the_read_is_demotable_and_live() -> None:
    """#639's cancelled future meeting, which ADR-0110 §3's carrier made unreachable.

    Both halves matter and only one of them is about the close. The belief is on
    the read path **now**, a month before its entry happens — which is ADR-0096 §5's
    whole reason for proposing calendar entries as beliefs, and what a
    position-stating envelope window would have destroyed (ADR-0117 §1). And it is
    demotable, because the extent says where the entry lies and the reading
    exhausted that region.
    """
    store = _store()
    ahead = _covered_extent(days_out=29)
    await store.add(_attested("meeting-next-month", extent=ahead))
    assert await _is_live(store, "meeting-next-month"), "retrievable long before it happens"

    closed = await _reconcile(
        _ingestor(store), source=_SOURCE, coverage=_coverage(), results=_stored("other")
    )

    assert closed == 1
    assert not await _is_live(store, "meeting-next-month")


async def test_a_record_reaching_past_the_horizon_is_not_contained() -> None:
    """§3 condition 3 — *wholly* within, so an overhang is not covered."""
    store = _store()
    await store.add(
        _attested("overhangs", extent=ReportedExtent(extends_until=_HORIZON + timedelta(days=5)))
    )

    closed = await _reconcile(
        _ingestor(store), source=_SOURCE, coverage=_coverage(), results=_stored("other")
    )

    assert closed == 0


async def test_a_record_starting_before_a_bounded_coverage_is_not_contained() -> None:
    """§3 condition 3 on the other end: an unbounded start is not inside a set one."""
    store = _store()
    await store.add(_attested("began-who-knows-when"))

    closed = await _reconcile(
        _ingestor(store),
        source=_SOURCE,
        coverage=ReadCoverage(covers_from=_NOW - timedelta(days=1), covers_until=_HORIZON),
        results=_stored("other"),
    )

    assert closed == 0


async def test_an_unbounded_coverage_contains_an_unbounded_extent() -> None:
    """§3's containment at the one place both ends are open on both sides."""
    store = _store()
    await store.add(_attested("wide-open", extent=ReportedExtent()))

    closed = await _reconcile(
        _ingestor(store), source=_SOURCE, coverage=ReadCoverage(), results=_stored("other")
    )

    assert closed == 1


async def test_a_record_the_ingest_left_live_is_present_and_survives() -> None:
    """§3 condition 4 — presence is the ingest's own answer (§4)."""
    store = _store()
    await store.add(_attested("re-reported"))

    closed = await _reconcile(
        _ingestor(store), source=_SOURCE, coverage=_coverage(), results=_stored("re-reported")
    )

    assert closed == 0
    assert await _is_live(store, "re-reported")


async def test_a_coverage_that_exhausted_no_instant_is_unrepresentable() -> None:
    """§2's invariant: both ends set means the end is after the start."""
    with pytest.raises(ValueError, match="covers_until must be after covers_from"):
        ReadCoverage(covers_from=_NOW, covers_until=_NOW)


# --- §4: absence is the ingest's answer, and one blank suspends the reading --


async def test_one_proposal_that_stored_nothing_suspends_the_whole_reading() -> None:
    """§4's second clause, and the case it is built for.

    A proposal conflicting with a ``USER_ASSERTED`` record is ruled ``ASK_USER``
    and nothing is written. The entry *is* in the source; the ingest simply stored
    nothing for it. Counting that as an absence would close the window of the
    attested record the user is being asked about — on the strength of the
    question.
    """
    store = _store()
    await store.add(_attested("would-have-closed"))

    closed = await _reconcile(
        _ingestor(store),
        source=_SOURCE,
        coverage=_coverage(),
        results=(*_stored("elsewhere"), _stored_nothing()),
    )

    assert closed == 0
    assert await _is_live(store, "would-have-closed")


async def test_an_empty_covered_reading_closes_every_covered_belief() -> None:
    """The most consequential path in the decision, and it is the correct one.

    A reading with no proposals is a **successful** pass over a source that had
    nothing to say within the bound (ADR-0093 §8) — never a failure signal. So a
    calendar that has been cleared for the next thirty days produces an empty
    reading with a coverage, nothing is present, and every covered belief that
    source reported is closed. That is exactly #639's cancelled meeting, at scale.

    It is worth an explicit case precisely because it is the one that retires the
    most on the least: the safety is not that the set is small, it is that every
    record in it satisfied §3's four conditions, that the source is re-read on a
    schedule, and that a wrongly closed attested window is re-proposed by the next
    read (ADR-0092 §4's recoverability, which is what makes an absence rule
    affordable at all).
    """
    store = _store()
    for index in range(3):
        await store.add(_attested(f"cancelled-{index}"))
    await store.add(_attested("someone-elses", reported_by="calendar:personal"))
    await store.add(_asserted("the-users-own"))

    closed = await _reconcile(_ingestor(store), source=_SOURCE, coverage=_coverage(), results=())

    assert closed == 3
    assert await _is_live(store, "someone-elses")
    assert await _is_live(store, "the-users-own")


# --- §5: the close is a retirement and carries a retirement's obligations ----


async def test_every_close_shares_one_instant_and_lands_in_one_write_set() -> None:
    """§5's two atomicity clauses at once: one ``now``, one ``write_atomic``.

    A set of retirements that half-lands is a set of beliefs retired for a reading
    that was never fully accounted for (ADR-0045 §8, one act over), and two closes
    stamped from two clock readings would make one reconciliation look like two.

    **Every close lands at exactly ``now``**, and ADR-0080 §1's other clamp branch
    — ``min(now, valid_until)`` where the record ended first — is unreachable from
    here rather than untested: §6's enumeration returns only beliefs live at
    ``now``, and a live belief's ``valid_until`` is by definition after it. The
    clamp is inherited whole (:func:`~ai_assistant.memory.ingest._close_window`)
    so that it stays correct if that ever stops being true.
    """
    store = _RecordingStore(now=_fixed_now)
    for index in range(3):
        await store.add(_attested(f"gone-{index}", extent=_covered_extent(days_out=index + 1)))

    closed = await _reconcile(
        _ingestor(store), source=_SOURCE, coverage=_coverage(), results=_stored("other")
    )

    assert closed == 3
    assert len(store.batches) == 1, "the closes must land as one write set, never a loop"
    batch = store.batches[0]
    assert len(batch) == 3
    assert {write.mode for write in batch} == {MemoryWriteMode.UPSERT}
    assert {write.record.validity.valid_until for write in batch} == {_NOW}


async def test_an_unrepresentable_close_refuses_and_writes_nothing() -> None:
    """ADR-0080 §3's refusal, and it takes the whole batch with it (§5).

    A close at or before a set ``valid_from`` is the half-open window ``[F, F)``,
    live at no instant — a record the store could not read back. Reaching it needs
    a store that hands back a record not yet live, which is the clock-coherence
    gap issue #460 carries and is simulated here; what matters is that the
    reconciliation refuses rather than writing it, and that the batch it was
    building never lands.
    """
    store = _LeakyStore(now=_fixed_now)
    await store.add(_attested("would-have-closed", extent=_covered_extent(days_out=2)))
    store.leak = _attested(
        "not-yet-open",
        validity=Validity(valid_from=_NOW + timedelta(days=1), valid_until=_HORIZON),
    )

    with pytest.raises(MemoryStoreError, match="at or before its valid_from"):
        await _reconcile(
            _ingestor(store), source=_SOURCE, coverage=_coverage(), results=_stored("other")
        )

    assert store.batches == [], "the refusal must precede the batch, not follow it"
    assert await _is_live(store, "would-have-closed")


async def test_the_walk_pages_past_the_first_page_of_beliefs() -> None:
    """§6's enumeration: a live set larger than one page is still fully examined."""
    store = _store()
    total = 120  # comfortably more than `_ABSENCE_PAGE`
    for index in range(total):
        await store.add(_attested(f"gone-{index}", extent=_covered_extent(days_out=index + 1)))

    closed = await _reconcile(
        _ingestor(store),
        source=_SOURCE,
        coverage=ReadCoverage(covers_until=_NOW + timedelta(days=total + 1)),
        results=_stored("other"),
    )

    assert closed == total


# --- §5a: the serialisation prerequisite, pinned by shape and by behaviour ---


class _RecordingStore(InMemoryMemoryStore):
    """An in-memory store that records the write sets it is handed.

    It also lets a test hold the *selection* open, which is what the isolation
    case below needs: the window §5a is about opens when the candidates are read
    and closes when the batch lands.
    """

    def __init__(self, *, now: Clock) -> None:
        super().__init__(now=now)
        self.batches: list[Sequence[MemoryWrite]] = []
        self.selecting = asyncio.Event()
        self.may_select = asyncio.Event()
        self.may_select.set()

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        self.batches.append(tuple(writes))
        return await super().write_atomic(writes)

    async def list_beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        self.selecting.set()
        await self.may_select.wait()
        return await super().list_beliefs(bands=bands, kinds=kinds, limit=limit, offset=offset)


class _LeakyStore(_RecordingStore):
    """A store whose enumeration leaks one record that is not live at ``now``.

    Simulates #460's clock-coherence gap — a store read running ahead of the
    writer's own clock — which is the only way a close can reach ADR-0080 §3's
    refusal through this path.
    """

    leak: MemoryRecord | None = None

    async def list_beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        page = await super().list_beliefs(bands=bands, kinds=kinds, limit=limit, offset=offset)
        if self.leak is not None and offset == 0:
            return [self.leak, *page]
        return page


def test_the_reconciliation_holds_no_store_and_no_writer_of_its_own() -> None:
    """§5a by shape: the parameters are the reading's facts and nothing else.

    This is the case that fails if someone later hands the reconciliation its own
    handle. Sharing the writer's store and the writer's lock is not an incidental
    implementation detail — it is the *entire* reason ADR-0110 §5a permits the
    mechanism to be implemented at all, and a reconciliation given a store of its
    own would keep passing every behavioural test in this file while serialising
    against nothing.
    """
    assert set(inspect.signature(MemoryIngestor._close_absent).parameters) == {
        "self",
        "source",
        "coverage",
        "results",
    }
    assert set(inspect.signature(MemoryIngestor.ingest_reading).parameters) == {
        "self",
        "reading",
    }


async def test_no_other_write_interleaves_anywhere_in_the_reading() -> None:
    """§5a by behaviour: the ingest, the selection and the closes are one section.

    ``write_atomic`` makes a write *set* atomic and does nothing for the read that
    produced it (ADR-0046 §5), so what has to hold is that **no other writer runs
    anywhere between the reading's ingest and its closes**. Three separate holds
    would each be serialised and the sequence still would not be: a write landing
    in a gap makes the reading's account of what is present stale, and a close
    computed from a stale account retires a belief the store was told about after
    the reading looked.

    So the selection is held open — which under ``ingest_reading`` is *inside* the
    same hold as the ingest — and an ordinary ``ingest`` is started behind it. It
    must not complete, because it wants the very lock the reading is holding.
    """
    store = _RecordingStore(now=_fixed_now)
    await store.add(_attested("gone"))
    ingestor = _ingestor(store)
    intruder = MemoryUpdateProposal(
        proposed=_attested("intruder", validity=Validity()),
        rationale="a concurrent write",
        sensitivity=DataTier.PERSONAL,
    )

    store.may_select.clear()
    reading = asyncio.create_task(ingestor.ingest_reading(_reading(coverage=_coverage())))
    await store.selecting.wait()

    competing = asyncio.create_task(ingestor.ingest(intruder))
    # Give the competing write every chance to run: were it not blocked on the
    # reading's lock, it would have finished several loop turns ago.
    for _ in range(10):
        await asyncio.sleep(0)
    assert not competing.done(), "an ingest interleaved with the reading's read-modify-write"

    store.may_select.set()
    assert list(await reading) == []
    await competing
    # The close still landed, and the intruder's write did not race it.
    assert not await _is_live(store, "gone")


async def test_a_covered_reading_ingests_and_reconciles_in_one_call() -> None:
    """The real public path end to end: what re-appeared stays, what did not goes.

    ``ingest_reading`` is the only way in, so this is also what pins that the two
    halves agree — presence is the ingest's own answer (§4), and the record the
    reading re-proposed is the one that survives.
    """
    store = _store()
    await store.add(_attested("still-there"))
    await store.add(_attested("cancelled"))
    # A re-read mints a fresh id and re-proposes the same text, which folds onto
    # the stored record by similarity and marks it present at *its own* id
    # (ADR-0092 §6, ADR-0110 §4).
    proposal = MemoryUpdateProposal(
        proposed=_attested("freshly-minted", content="the entry still-there names"),
        rationale="the source still reports it",
        sensitivity=DataTier.PERSONAL,
    )

    results = await _ingestor(store).ingest_reading(
        _reading(proposals=(proposal,), coverage=_coverage())
    )

    assert len(results) == 1
    assert await _is_live(store, "still-there")
    assert not await _is_live(store, "cancelled")


async def test_a_reading_without_coverage_ingests_and_closes_nothing() -> None:
    """The default path: ADR-0093 §4's refusal, left exactly as it stands."""
    store = _store()
    await store.add(_attested("untouched"))

    results = await _ingestor(store).ingest_reading(_reading(coverage=None))

    assert list(results) == []
    assert await _is_live(store, "untouched")


async def test_a_coverage_widened_mid_flight_does_not_authorise_a_close() -> None:
    """ADR-0065's input-observation clause, for the value that authorises retirement.

    The coverage is read *after* every ingest await, by the reconciliation, and it
    is what decides which records §3 counts as covered. A model tampered past
    ``frozen=True`` is inside this repository's threat model (ADR-0018 §3,
    ADR-0021 §4) — it is the very threat :meth:`MemoryIngestor.ingest`'s own
    snapshot exists for — so a caller that widened ``covers_until`` to ``None``
    while the ingest was in flight would otherwise have the reconciliation retire a
    record that lay outside the coverage the read actually declared.

    That is not a small slip: an unbounded record is contained by an unbounded
    coverage alone, so widening the bound is exactly the edit that turns "states no
    position in the source's world" into "covered", and it would close a belief on
    the strength of a slice nobody exhausted.
    """
    store = _store()
    await store.add(_attested("open-window", validity=Validity()))
    coverage = _coverage()
    proposal = MemoryUpdateProposal(
        proposed=_attested("something-new", validity=Validity()),
        rationale="the source reported it",
        sensitivity=DataTier.PERSONAL,
    )
    ingestor = _ingestor(store)

    task = asyncio.create_task(
        ingestor.ingest_reading(_reading(proposals=(proposal,), coverage=coverage))
    )
    await asyncio.sleep(0)  # let the snapshot happen, then tamper
    object.__setattr__(coverage, "covers_until", None)
    await task

    # The bound the reading declared still governs: an open window is not covered.
    assert await _is_live(store, "open-window")


async def test_a_covered_reading_whose_later_proposal_raises_closes_nothing() -> None:
    """ADR-0115 §3's partial-ingest clause, and why there is no ``finally``.

    A reading that was never fully accounted for warrants no absence — ADR-0110 §4's
    suspension clause reached by a second road. An implementation that reconciled
    from a cleanup path would close records on a reading it only half read, and
    would pass every other case in this module while doing it.

    The earlier proposals stay applied, exactly as the per-proposal loop leaves them.
    """
    store = _store()
    await store.add(_attested("would-have-closed"))
    ingestor = _ingestor(store)
    # The second proposal cites an episode the store does not hold, which the
    # ingestor refuses before any ruling is sought (ADR-0077 §5).
    good = MemoryUpdateProposal(
        proposed=_attested(
            "fresh",
            validity=Validity(),
            content="an unrelated statement about wednesday travel",
        ),
        rationale="the source reported it",
        sensitivity=DataTier.PERSONAL,
    )
    bad = MemoryUpdateProposal(
        proposed=SemanticMemory(
            id="derived-with-no-evidence",
            content="something inferred",
            fact="something inferred",
            provenance=Provenance(
                source=MemorySource.INFERRED,
                confidence=0.6,
                last_updated=_WHEN,
                evidence=("episode-that-does-not-exist",),
            ),
        ),
        rationale="inferred",
        sensitivity=DataTier.PERSONAL,
    )

    with pytest.raises(UnresolvedEvidenceError):
        await ingestor.ingest_reading(_reading(proposals=(good, bad), coverage=_coverage()))

    assert await _is_live(store, "would-have-closed"), "a half-read reading closes nothing"
    assert await _is_live(store, "fresh"), "the proposals before the raise stay applied"


def test_the_writer_holds_no_deferral_store() -> None:
    """ADR-0115 §5, pinned by construction rather than by behaviour.

    §7 keeps this off the shared suite deliberately: ``MemoryWriter`` neither accepts
    nor exposes a ``DeferralStore``, so a black-box suite cannot tell a conforming
    writer from one secretly holding a queue, and a case asserting the negative would
    pass vacuously against both. What *is* checkable is the constructor — a writer
    that cannot be given a queue cannot reach one.
    """
    parameters = set(inspect.signature(MemoryIngestor.__init__).parameters)

    assert not {name for name in parameters if "deferral" in name.lower()}
