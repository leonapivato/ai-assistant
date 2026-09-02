"""ADR-0217 §7's two acts against a clock that will not read (issue #1862).

``Engine._placed_at`` reads the injected clock for a placement act's ``set_at`` and
translates a non-conforming reading into ``MemoryStoreError`` — deliberately *not*
``Engine._now``'s ``TraceStoreError``, because §7 declares an **exhaustive** two
errors for ``guard`` and ``unguard`` and a third arriving there would falsify that
list. ADR-0026 §4 is the ground: "each subsystem translates at its own boundary",
and the reading takes "the error of the stage that read the clock" — this reading
exists only to stamp a placement being written to memory, so it is the write's own
error.

**Why here rather than in ``tests/test_clock_seams.py``.** That module drives the
engine's clock seam through ``purge_expired``, the retention sweep, and pins its
error as ``TraceStoreError`` — one label, one error, and its table asserts the
labels are unique. This is the *second* reading of the same engine clock, with a
different translation, and only an act can reach it.

**Why here rather than in ``test_engine_placement_acts.py``.** That module's whole
subject is what an act does over a store nobody has broken; every case there runs
on a valid fixed clock, which is exactly the gap this file fills.

Separate from the shared ``AssistantEngineContract`` for the reason the sibling
module is: ``FakeAssistantEngine.placement_clock`` is an unguarded attribute with
no ``checked_clock`` around it and no translation to mirror (ADR-0026 §7 covers the
fakes, and this one has no clock *seam* — it has a stamp factory a case moves), so
there is nothing on the fake for a shared arm to assert against.
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from typing import TYPE_CHECKING

import pytest
from test_engine import AT, Harness

from ai_assistant.core.clock import ClockReadingError
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

#: The record every case here acts on.
_RECORD = "rec-placement-clock"
_CONTENT = "the user's consultant said the merger is off"


class _Indeterminate(tzinfo):
    """A ``tzinfo`` that is *set* and answers no offset (ADR-0026 §2's step 2).

    Not the same fault as a naive reading and not caught by the same test: the
    value carries a zone, so an implementation checking ``tzinfo is None`` would
    accept it and hand ``astimezone`` a value it would then read as host-local.
    """

    def utcoffset(self, dt: datetime | None) -> None:
        """No determinate offset, which is what the guard rejects."""
        return

    def tzname(self, dt: datetime | None) -> None:
        """Unnamed, as a zone with no offset must be."""
        return

    def dst(self, dt: datetime | None) -> None:
        """No DST rule either."""
        return


#: The three shapes ``_placed_at``'s ``Raises`` enumerates — "naive, indeterminate,
#: or outside the localizable range" — each a genuine ``datetime``, so what refuses
#: them is the guard rather than the annotation. A fourth shape, a reading that is
#: not a ``datetime`` at all, is ``core``'s own step 1 and is pinned in
#: ``tests/core/test_clock.py``; reaching it from here would take a cast whose only
#: effect is to lie to the type checker about the seam's declared contract.
_NON_CONFORMING: tuple[tuple[str, datetime], ...] = (
    ("naive", datetime(2026, 7, 21, 12)),  # noqa: DTZ001 — the naive reading is the subject
    ("indeterminate", datetime(2026, 7, 21, 12, tzinfo=_Indeterminate())),
    ("outside the localizable range", datetime.max.replace(tzinfo=UTC)),
)

#: Both members of §7's pair. Neither is the other's alias: they differ in the reach
#: they write, and a translation added to one and not the other would leave half the
#: declared error list false.
_ACTS = ("guard", "unguard")


class _WaveringClock:
    """A clock that reads conformingly until a case breaks it, and can be mended.

    ``checked_clock`` is explicit that it validates "per reading, not once at
    construction", on the ground that "a fixture that is aware on its first reading
    and naive on its third is an ordinary test double" — this is that double. It
    matters here rather than being a convenience: an engine wired to a clock that was
    broken from the first reading could not be *started* under this harness, and a
    case that could not seed a live record could not show the stored placement
    surviving the act.
    """

    def __init__(self) -> None:
        """Create a clock reading :data:`AT`, failing nothing."""
        self.reading: datetime = AT
        #: An exception the clock raises **on its own account**, which ADR-0026 §2
        #: keeps outside the guard: "an exception raised by the clock callable itself
        #: propagates unwrapped".
        self.failure: BaseException | None = None

    def __call__(self) -> datetime:
        """The current reading, or the current failure."""
        if self.failure is not None:
            raise self.failure
        return self.reading


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


@pytest.fixture
async def wavering() -> AsyncIterator[tuple[Harness, FakeMemoryStore, _WaveringClock]]:
    """An engine whose own clock a case can break, over a store that is not broken.

    Every collaborator gets its own conforming clock — ``Harness`` defaults each fake
    to a fixed one and passes only this to the engine — so the reading under test is
    the engine's and never one borrowed from a stage it drives. The clock is mended
    before the engine is closed, because a shutdown is not the subject and an
    unreadable clock during the drain would be a second fault in the same case.
    """
    store = FakeMemoryStore(now=lambda: AT)
    clock = _WaveringClock()
    harness = Harness(memory=store, now=clock)
    await harness.engine.start()
    try:
        yield harness, store, clock
    finally:
        clock.reading = AT
        clock.failure = None
        await harness.engine.aclose()


# --- the translation ---------------------------------------------------------


@pytest.mark.parametrize("act", _ACTS)
@pytest.mark.parametrize(
    "reading",
    [reading for _, reading in _NON_CONFORMING],
    ids=[name for name, _ in _NON_CONFORMING],
)
async def test_a_non_conforming_reading_reaches_the_caller_as_the_write_s_own_error(
    wavering: tuple[Harness, FakeMemoryStore, _WaveringClock],
    reading: datetime,
    act: str,
) -> None:
    """ADR-0217 §7's exhaustive ``Raises`` list, held to the one path that could
    falsify it.

    The act is one §7 says **writes** — the seeded placement is the default, which
    both members change — so it reaches the stamp, and the stamp is the only thing
    that fails. What arrives at the caller must be ``MemoryStoreError``: a
    ``ClockReadingError`` leaking out would be a bare ``ValueError`` in the caller's
    hands, and a ``TraceStoreError`` — ``Engine._now``'s translation, one stage over
    — would be a third error on a surface that declares two.

    The cause is asserted as well as the type, because ``raise ... from exc`` is what
    keeps the diagnosis: an implementation that raised a fresh ``MemoryStoreError``
    with the same text would satisfy the caller's ``except`` and destroy the
    traceback that names the clock.
    """
    harness, store, clock = wavering
    await _seed(store, Placement())
    before = await store.get(_RECORD)
    assert before is not None

    clock.reading = reading
    with pytest.raises(MemoryStoreError) as caught:
        await getattr(harness.engine, act)(_RECORD)

    assert "Engine" in str(caught.value), "the diagnostic must name the seam that read"
    assert isinstance(caught.value.__cause__, ClockReadingError)
    after = await store.get(_RECORD)
    assert after is not None
    assert after.placement == Placement()
    assert after.revision == before.revision


@pytest.mark.parametrize("act", _ACTS)
async def test_a_failed_stamp_leaves_no_half_performed_act_behind(
    wavering: tuple[Harness, FakeMemoryStore, _WaveringClock],
    act: str,
) -> None:
    """The other half of the arm above, and the one that separates two failures.

    An act that wrote and then failed to report is a placement the owner asked for,
    got told did not happen, and now carries — the exact state ADR-0217 §7's
    conditional write exists to keep out of the store. So the check is that the act
    is still available afterwards and still *writes*: the record is acted on again
    over a mended clock and the placement it then carries is the one that act makes,
    which an implementation that had already written the first attempt could not
    distinguish itself from by the stored value alone. The revision does the
    distinguishing — ADR-0219 §1 stamps a fresh one on every write, so a store whose
    revision moved during the failed act is a store that took a write.
    """
    harness, store, clock = wavering
    await _seed(store, Placement())
    before = await store.get(_RECORD)
    assert before is not None

    clock.reading = _NON_CONFORMING[0][1]
    with pytest.raises(MemoryStoreError, match=r"\w"):
        await getattr(harness.engine, act)(_RECORD)
    during = await store.get(_RECORD)
    assert during is not None
    assert during.revision == before.revision

    clock.reading = AT
    placed = await getattr(harness.engine, act)(_RECORD)

    assert placed is not None
    assert placed.set_by is PlacementSetter.OWNER_ACT
    assert placed.set_at == AT
    after = await store.get(_RECORD)
    assert after is not None
    assert after.placement == placed
    assert after.revision != before.revision


@pytest.mark.parametrize("act", _ACTS)
async def test_a_failure_of_the_clock_itself_is_not_relabelled_as_a_bad_reading(
    wavering: tuple[Harness, FakeMemoryStore, _WaveringClock],
    act: str,
) -> None:
    """ADR-0026 §2's reading/invocation boundary, at the seam that translates.

    "The guard covers the reading, not the invocation": a clock that fails on its own
    account propagates unwrapped, carrying its own type and cause. That only survives
    a translating boundary if the boundary catches ``ClockReadingError`` and not bare
    ``ValueError`` — and a provider that is simply down raises the latter. A boundary
    that caught ``ValueError`` here would tell the owner their clock returned a bad
    reading, which is a different and false diagnosis, and it would pass the arm
    above unchanged.
    """
    harness, store, clock = wavering
    await _seed(store, Placement())

    clock.failure = ValueError("the clock provider is down")
    with pytest.raises(ValueError, match="the clock provider is down") as caught:
        await getattr(harness.engine, act)(_RECORD)

    assert not isinstance(caught.value, ClockReadingError)
    assert not isinstance(caught.value, MemoryStoreError)
    held = await store.get(_RECORD)
    assert held is not None
    assert held.placement == Placement()


# --- the stamp is reached only where §7 says the act writes ------------------


@pytest.mark.parametrize("act", _ACTS)
async def test_an_act_that_writes_nothing_never_reads_the_clock_at_all(
    wavering: tuple[Harness, FakeMemoryStore, _WaveringClock],
    act: str,
) -> None:
    """What makes "raised before writing" a statement about §3 rather than luck.

    A ``DERIVED`` placement is §3's closing clause: neither act lifts it, both answer
    with the placement the record already carries, and neither writes. So neither
    stamps — and an implementation that read the clock before deciding, or that
    stamped a placement it was about to discard, would turn a refusal the owner is
    entitled to into an error, on a record it was never going to touch.
    """
    harness, store, clock = wavering
    derived = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=AT)
    await _seed(store, derived)

    clock.reading = _NON_CONFORMING[0][1]
    answered = await getattr(harness.engine, act)(_RECORD)

    assert answered == derived
    held = await store.get(_RECORD)
    assert held is not None
    assert held.placement == derived
