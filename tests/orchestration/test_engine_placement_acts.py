"""The engine performing ADR-0217 §7's two acts against a real store.

What is only true of a **whole act over a store**, and so cannot be pinned in the
shared ``AssistantEngineContract``: the conditional write §7 gates these acts on, the
window it closes, the bound on the retry, the read discipline, and the one stamping
case the shared suite cannot reach because no call on the promoted surface writes a
``PROPOSED`` placement.

**The cases here are written against the implementations that would pass a weaker
suite.** An act that read, decided and wrote *unconditionally* passes every arm of the
shared suite — every one of them runs against a store nobody else is writing to — and
loses exactly what §7 gates the acts for: "a derivation landing between an act's read
and its write, overwritten by a stale ``unguard``, is exactly the laundering §3's
precedence refuses whenever it can see it". An act that retried without a bound passes
the interleaving case and never returns against a writer in a tight loop. And an act
that decided over a *rendered* placement rather than over the stored one passes both,
until the derivation lands between the render and the answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from test_engine import AT, Harness

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    SemanticMemory,
    Validity,
)
from ai_assistant.testing import FakeMemoryStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import MemoryRecord

#: The record every case here acts on.
_RECORD = "rec-placement"
_CONTENT = "the user's consultant said the merger is off"

#: The placement a derivation writes, and the one §3's closing clause protects. It
#: carries an instant because §1 admits an untimed ``DERIVED`` placement for §9's
#: decode alone, and a producer that narrowed stamps one.
_DERIVED = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=AT)

#: A model's proposal, which the shared suite cannot reach: ADR-0217 §4's proposer is
#: ``learning/observer.py``'s and lands in a later change, so the only way to hold an
#: act to §7's "a ``guard`` on a placement whose setter is ``PROPOSED`` … **does**
#: write" today is to seed the store a real producer would have written to.
_PROPOSED = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.PROPOSED, set_at=AT)


def _record(placement: Placement) -> SemanticMemory:
    """One stored belief carrying ``placement``."""
    return SemanticMemory(
        id=_RECORD,
        content=_CONTENT,
        fact=_CONTENT,
        validity=Validity(),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        placement=placement,
    )


async def _seed(store: FakeMemoryStore, placement: Placement) -> None:
    """Put the record into ``store`` carrying ``placement``."""
    await store.write_atomic(
        [MemoryWrite(record=_record(placement), mode=MemoryWriteMode.INSERT_IF_ABSENT)]
    )


async def _standing(store: FakeMemoryStore) -> Placement:
    """The placement the store now holds for the record."""
    held = await store.get(_RECORD)
    assert held is not None
    return held.placement


class _RacingStore(FakeMemoryStore):
    """A store in which another writer lands **after** each of the act's reads.

    The window ADR-0046 §5 named and ADR-0219 §2 closed, made reachable rather than
    argued about: the interleaving is arranged at the one instant that matters, which
    is *between the act's read and the act's write*. Overriding ``get`` puts it exactly
    there and nowhere else — a case that wrote the derivation before calling the act
    would be testing the ordinary refusal, which the shared suite already covers, and
    one that wrote it afterwards would be testing nothing at all.

    ``races`` bounds how many reads are followed by an interleaved write, which is what
    separates the two cases this file needs: **one** lets the act's second attempt
    succeed on the value it re-read, and an unbounded count exhausts §7's two attempts.
    """

    def __init__(self, *, lands: Placement, races: int) -> None:
        """Create a store that writes ``lands`` after the first ``races`` reads."""
        super().__init__(now=lambda: AT)
        self._lands = lands
        self._races = races
        #: How many interleaved writes actually happened. Read by a case as a
        #: **negative control**: an act that never re-read would leave this at one.
        self.raced = 0

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Read as the fake does, then let the other writer land.

        ``super().get`` is awaited to completion first, so the interleaved write is
        made outside the modelled resource this store holds for a read — the racing
        writer is a *second* caller, and one that could only write while the reader
        held the lock would be a writer no deployment has.
        """
        found = await super().get(record_id)
        if found is not None and self.raced < self._races:
            self.raced += 1
            await self.write_atomic(
                [
                    MemoryWrite(
                        record=_record(self._lands),
                        mode=MemoryWriteMode.UPSERT,
                    )
                ]
            )
        return found


async def _engine(store: FakeMemoryStore) -> AsyncIterator[Harness]:
    """A wired engine over ``store``, started and closed."""
    harness = Harness(memory=store, now=lambda: AT)
    await harness.engine.start()
    try:
        yield harness
    finally:
        await harness.engine.aclose()


@pytest.fixture
async def plain() -> AsyncIterator[tuple[Harness, FakeMemoryStore]]:
    """An engine over an ordinary store nobody else is writing to."""
    store = FakeMemoryStore(now=lambda: AT)
    async for harness in _engine(store):
        yield harness, store


# --- §7's stamping case the shared suite cannot reach ------------------------


async def test_a_guard_on_a_proposed_placement_writes_the_owner_s_own_setter(
    plain: tuple[Harness, FakeMemoryStore],
) -> None:
    """§7's second consequence, stated so no implementation has to derive it.

    "A ``guard`` on a record whose placement is reach ``OWNER`` with setter
    ``PROPOSED`` … **does** write, because it changes the setter from one the owner may
    lift to one this ADR calls final, which is a difference §3 acts on." The **reach
    does not move** — it is ``OWNER`` on both sides — so an implementation that decided
    whether to write by comparing reaches alone would write nothing here and pass every
    arm of the shared suite, leaving a model's guess standing as something the owner
    could not later lift in one act.
    """
    harness, store = plain
    await _seed(store, _PROPOSED)

    placed = await harness.engine.guard(_RECORD)

    assert placed is not None
    assert placed.reach is PlacementReach.OWNER
    assert placed.set_by is PlacementSetter.OWNER_ACT
    assert await _standing(store) == placed


async def test_an_unguard_lifts_a_model_s_proposal_in_one_act(
    plain: tuple[Harness, FakeMemoryStore],
) -> None:
    """§3: an act "may widen one whose setter is ``PROPOSED`` or ``OWNER_ACT``".

    This is the clause ADR-0217 §3's answer to ADR-0130 §11 rests on — "the owner can
    lift it in one act (§7)" — and §11 orders §4's proposer *after* these acts for
    exactly that reason: a proposal narrowing a record in a tree where the owner could
    not lift it would falsify the justification the proposal stands on.
    """
    harness, store = plain
    await _seed(store, _PROPOSED)

    lifted = await harness.engine.unguard(_RECORD)

    assert lifted is not None
    assert lifted.reach is PlacementReach.ANYONE
    assert lifted.set_by is PlacementSetter.OWNER_ACT
    assert await _standing(store) == lifted


async def test_an_unguard_on_the_default_placement_writes_and_advances_the_revision(
    plain: tuple[Harness, FakeMemoryStore],
) -> None:
    """The store's half of the shared suite's arm, which only a store can say.

    The shared suite pins that the act *returns* reach ``ANYONE`` with setter
    ``OWNER_ACT``; an implementation that returned that value while writing nothing
    would pass it and leave the record carrying the default. ADR-0219 §1 gives the
    check its shape: "every write that stores a row stamps it with a fresh
    ``revision``", so a revision that moved is the store saying a write landed, and one
    that did not is the store saying none did.

    It is the exact converse of the case below, which asserts the revision **unmoved**
    for an act §7 says writes nothing — the two together are what make "writes" and
    "writes nothing" observable rather than asserted.
    """
    harness, store = plain
    await _seed(store, Placement())
    before = await store.get(_RECORD)
    assert before is not None

    released = await harness.engine.unguard(_RECORD)

    after = await store.get(_RECORD)
    assert after is not None
    assert released is not None
    assert released.reach is PlacementReach.ANYONE
    assert released.set_by is PlacementSetter.OWNER_ACT
    assert released.set_at is not None
    assert after.placement == released
    assert after.revision != before.revision


async def test_an_act_that_writes_nothing_leaves_the_stored_revision_alone(
    plain: tuple[Harness, FakeMemoryStore],
) -> None:
    """§7's "neither does an act whose whole effect would be to rewrite a placement it
    does not change", read at the store rather than at the return value.

    The shared suite pins that a second ``guard`` *returns* the first's value; only the
    store can say whether anything was written. An implementation that rewrote the
    identical placement would return the right value and still stamp a fresh
    ``revision`` (ADR-0219 §1) — which is not cosmetic: it would invalidate a
    conditional write another caller had computed against the record, turning an act
    that did nothing into an act that makes someone else's act fail.
    """
    harness, store = plain
    await _seed(store, Placement())
    await harness.engine.guard(_RECORD)
    settled = await store.get(_RECORD)
    assert settled is not None

    again = await harness.engine.guard(_RECORD)

    after = await store.get(_RECORD)
    assert after is not None
    assert after.revision == settled.revision
    assert again == settled.placement


# --- §7's gate: the window, and what a stale act must not do -----------------


async def test_a_derivation_landing_inside_the_window_refuses_the_widening() -> None:
    """§10's interleaving arm, which §7's gate is what makes testable.

    "With a derivation's write landing between an ``unguard``'s read and its write, the
    conditional write fails, the act re-reads, §3 refuses the widening, and the record
    is left reach ``OWNER`` with setter ``DERIVED`` — the returned value saying so."

    This is the case the whole gate exists for, and it is a **disclosure** rather than a
    lost merge: an unconditional act would write reach ``ANYONE`` with setter
    ``OWNER_ACT`` over a narrowing ADR-0204 §5's closing prohibition forbids clearing in
    place, and every later read would find a record the derivation withheld now
    speakable to anyone. The store is asserted as well as the return value, because an
    implementation that returned the refusal while having written the widening would
    pass a case that read only what came back.
    """
    store = _RacingStore(lands=_DERIVED, races=1)
    async for harness in _engine(store):
        await _seed(store, Placement())

        answered = await harness.engine.unguard(_RECORD)

        assert store.raced == 1
        assert answered is not None
        assert answered.reach is PlacementReach.OWNER
        assert answered.set_by is PlacementSetter.DERIVED
        assert await _standing(store) == _DERIVED


async def test_a_guard_racing_a_derivation_lands_on_the_value_it_re_read() -> None:
    """The other half of §7's conflict clause: the act re-reads and **re-decides**.

    "Where the conditional write finds the record changed since the read, the act reads
    it again and applies §3's precedence to the value it now carries." Here the value it
    now carries is a ``DERIVED`` narrowing, so the re-decision is a refusal — and the
    point of the case beside the one above is that the act reaches that refusal by
    *reading*, not by remembering: an implementation that re-submitted the payload it
    computed over the rejected snapshot would write ``OWNER_ACT`` over ``DERIVED``,
    which is the lost update wearing a conditional write's clothes.
    """
    store = _RacingStore(lands=_DERIVED, races=1)
    async for harness in _engine(store):
        await _seed(store, Placement())

        answered = await harness.engine.guard(_RECORD)

        assert answered == _DERIVED
        assert await _standing(store) == _DERIVED


async def test_the_retry_is_bounded_at_two_attempts_and_then_raises() -> None:
    """§10's exhausted-retry arm: "a bound that is never exercised is a bound nobody
    has tested".

    "With a writer changing the record before each of the act's two attempts, the act
    raises ``MemoryStoreError`` and the record is left exactly as the other writer left
    it, with nothing of the act's written." ``MemoryStoreError`` is the error **both
    members already declare**, so §7's exhaustive ``Raises`` list is unmoved and neither
    operation gains an error.

    Livelock is refused rather than made improbable: an act that cannot land while
    another writer rewrites the same record in a tight loop is a failure the caller can
    see, not a call that never returns. The read count is asserted at exactly two,
    which is the half a `pytest.raises` alone would not catch — an implementation
    looping ten times before giving up raises the same error.

    **The racing writer leaves the placement alone**, which is what makes the retry
    exhaust rather than resolve: an interleaved *derivation* would have the act's
    re-read reach §3's ordinary refusal and write nothing at all — the case above — so
    a store that landed one here would be testing the refusal a second time and would
    never reach the bound.
    """
    store = _RacingStore(lands=Placement(), races=99)
    async for harness in _engine(store):
        await _seed(store, Placement())

        with pytest.raises(MemoryStoreError, match=r"\w"):
            await harness.engine.unguard(_RECORD)

        assert store.raced == 2
        assert await _standing(store) == Placement()


async def test_a_racing_writer_that_is_not_a_derivation_still_costs_only_one_retry(
    plain: tuple[Harness, FakeMemoryStore],
) -> None:
    """The bound is on the *attempts*, not on the kind of writer that raced.

    A second act of the owner's is as much a second writer as a derivation is, and §7's
    conflict clause is stated over "the record changed since the read" rather than over
    what changed it. So an ``unguard`` that meets one ordinary rewrite in its window
    still lands, on the value it re-read — which is what makes the bound safe rather
    than merely small: "a caller that meant it repeats it".
    """
    store = _RacingStore(lands=Placement(), races=1)
    async for harness in _engine(store):
        await _seed(store, Placement())

        lifted = await harness.engine.guard(_RECORD)

        assert store.raced == 1
        assert lifted is not None
        assert lifted.reach is PlacementReach.OWNER
        assert lifted.set_by is PlacementSetter.OWNER_ACT
        assert await _standing(store) == lifted


# --- §7's read discipline ----------------------------------------------------


async def test_an_act_follows_the_stored_placement_and_not_a_rendered_one(
    plain: tuple[Harness, FakeMemoryStore],
) -> None:
    """§10's read-discipline arm, and §7's "each act decides §3's precedence over the
    record it read in the call that writes it, never over one read earlier".

    The sequence is the one a surface actually produces: a listing shows the record
    carrying a ``PROPOSED`` placement, the owner is offered a ``guard`` against that,
    the derivation lands while they are reading, and the act is then performed. It
    leaves ``DERIVED`` and writes nothing. ``AssistantEngine.forget`` carries the same
    ruling for its own window over the same store, and ADR-0197 §7's confirmation is
    not a writer's lock — this ADR does not make it one.
    """
    harness, store = plain
    await _seed(store, _PROPOSED)
    rendered = await _standing(store)
    assert rendered.set_by is PlacementSetter.PROPOSED

    # The derivation lands between the render and the answer.
    await store.write_atomic([MemoryWrite(record=_record(_DERIVED), mode=MemoryWriteMode.UPSERT)])

    answered = await harness.engine.guard(_RECORD)

    assert answered == _DERIVED
    assert await _standing(store) == _DERIVED


async def test_an_act_on_a_record_the_store_no_longer_holds_answers_none(
    plain: tuple[Harness, FakeMemoryStore],
) -> None:
    """The same window, one step further: the record is **gone** by the time of the act.

    ``None`` and not an error, on ``forget``'s own reading of the case, and not a
    ``MemoryStoreStaleError`` either: nothing was attempted, because the act's own read
    found nothing to decide over. ADR-0219 §3 makes a deleted row a *stale* conditional
    write for a caller that computed one, and this shows the act never gets that far.
    """
    harness, store = plain
    await _seed(store, Placement())
    assert await store.delete(_RECORD) is True

    assert await harness.engine.guard(_RECORD) is None
    assert await harness.engine.unguard(_RECORD) is None
