"""The engine's two read-trail reads, over a **real** store and a real driver.

The shared suite holds all three implementations to ADR-0186 §10's order, §3's local
refusals and §3's oversized result, over doubles. Two things it structurally cannot
hold any of them to are here instead, and each is a property of *this* wiring rather
than of the contract.

**The order the reversal depends on is the store's, and only a real store has it.**
``export_reads`` is correct exactly when ``SourceReadTrail.export`` really answers in
recording order, because the operation reverses what it is handed rather than
sorting it — a ``SourceReadRecord`` carries no sequence number and its ``checked_at``
is caller-supplied, so there is nothing on the row to sort by (ADR-0185 §6). The
canonical fake obtains that order from a Python list, where it is true by
construction; ``SqliteSourceReadTrail`` obtains it from SQL, where it is true by a
query. A fake-only case would pass for an engine paired with a store whose
``ORDER BY`` was wrong or absent, and the two would be wrong together in the
direction nobody looks.

**The single-instance obligation has no type and no contract clause.** ADR-0185 §4
passes one object to every driver narrowed to ``SourceReadRecorder``, and ADR-0186
§10 hands the same object whole to the façade; that these are one object is a
composition-root obligation "no type can say", of the same shape as ADR-0042 §2's
``plans`` and ADR-0052 §1's ``trail``. The failure it guards against is silent and
would survive every case in the shared suite: a façade wired to a *second* trail
answers a user's history from a store nothing writes to, and an empty answer there is
indistinguishable from the truthful answer that nothing has been read. So the case
below writes through the **driver's** narrow seam and reads back through the
**engine's** wide one, which is the only arrangement in which the two seams being one
object is what is under test.

Driven through ``Engine`` rather than through ``SqliteSourceReadTrail`` directly,
for ``test_engine_decisions``' reason: the store's own read half is already pinned in
``tests/permissions/test_reads.py``, and what is unpinned without this module is
whether the operation a user will reach relays it whole and in the right direction.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from test_engine import Harness

from ai_assistant.orchestration.engine import Engine
from ai_assistant.permissions import SqliteSourceReadTrail
from ai_assistant.testing import FakeReader, source_read_record

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

#: When the seeded attempts' grant checks resolved. Fixed, so the order under test is
#: the values' rather than the run's.
_AT = datetime(2026, 3, 2, 14, 0, tzinfo=UTC)

#: The four rows, as ``(id, seconds after`` :data:`_AT` ``)``, **in recording order**.
#:
#: The instants disagree with the recording order in both directions, which is what
#: makes the case about the order rather than about a coincidence: sorted by
#: ``checked_at`` ascending these are ``a-3, a-2, a-1, a-4`` and descending its
#: reverse, and neither is :data:`_EXPECTED`. The ids are deliberately not monotonic
#: in the recorded sequence either, so an implementation sorting by ``id`` in either
#: direction is refuted as well.
_SEEDED: tuple[tuple[str, int], ...] = (
    ("a-1", 2),
    ("a-3", 0),
    ("a-4", 3),
    ("a-2", 1),
)

#: ADR-0186 §10's order over :data:`_SEEDED`: newest-**recorded** first, which is the
#: recorded sequence reversed. Written out rather than computed, so the expectation is
#: something a reader checks against the ADR rather than against a second copy of the
#: implementation.
_EXPECTED: tuple[str, ...] = ("a-2", "a-4", "a-3", "a-1")


@pytest.fixture
async def durable(tmp_path: Path) -> AsyncIterator[tuple[Harness, SqliteSourceReadTrail]]:
    """A harness whose engine reads a real, seeded ``SqliteSourceReadTrail``.

    The rows are written **through the store** rather than through the surface,
    because nothing on the promoted surface appends one: ADR-0186 §10's pair is two
    reads, since a row is authored on the seam that gated the read (ADR-0185 §5).

    ``max_rows`` is far above the four seeded here, so ADR-0185 §6's prune never
    fires and this module is about the order alone. The horizon has its own cases in
    ``tests/permissions/test_reads.py``, where the store that implements it lives.

    The store is yielded beside the harness so a case can ask it directly what order
    it handed over — the same negative-control arrangement the shared suite's
    ``reads`` fixture uses, and what stops the reversal case being vacuous.
    """
    trail = SqliteSourceReadTrail(path=tmp_path / "reads.db", max_rows=1_000)
    try:
        for record_id, offset in _SEEDED:
            await trail.record(
                source_read_record(
                    "calendar",
                    record_id=record_id,
                    checked_at=_AT + timedelta(seconds=offset),
                    produced=1,
                )
            )
        yield Harness(reads=trail), trail
    finally:
        trail.close()


async def test_the_export_reverses_a_real_store_s_recording_order(
    durable: tuple[Harness, SqliteSourceReadTrail],
) -> None:
    """ADR-0186 §10 against SQL rather than against a list.

    The store's own answer is read first, so the case is evidence of a **reversal**
    rather than of a store that happened to agree: a durable trail whose ``ORDER BY``
    had been written the other way would make the second assertion pass for the wrong
    reason, and the first is what refuses that.
    """
    harness, trail = durable

    assert [row.id for row in await trail.export()] == [record_id for record_id, _ in _SEEDED]

    exported = await harness.engine.export_reads()

    assert tuple(row.id for row in exported) == _EXPECTED


async def test_the_listing_is_the_real_store_s_prefix(
    durable: tuple[Harness, SqliteSourceReadTrail],
) -> None:
    """ADR-0186 §2 through §10, over the two reads a real trail implements.

    The prefix property is the one that spans **both** store reads, so a store whose
    ``recent`` and ``export`` disagreed about order would fail here while satisfying
    either read's own case in isolation.
    """
    harness, _trail = durable
    exported = await harness.engine.export_reads()

    for size in range(1, len(_EXPECTED) + 1):
        assert await harness.engine.recent_reads(limit=size) == exported[:size]


async def test_the_order_is_not_derived_from_the_instant_on_the_row(
    durable: tuple[Harness, SqliteSourceReadTrail],
) -> None:
    """ADR-0185 §6: recording order, "never by ``checked_at``".

    Stated over a real store because this is where the temptation is cheapest to
    satisfy: SQLite will happily ``ORDER BY checked_at``, the column is right there,
    and over most trails it agrees with recording order. It stops agreeing exactly
    when the host clock is corrected backwards — the deployment ADR-0185 §6 keys the
    store's own prune away from ``checked_at`` to survive, where "a prune keyed on it
    after a backwards clock correction deletes the rows it just wrote".
    """
    harness, _trail = durable
    by_instant = sorted(_SEEDED, key=lambda row: row[1])
    answered = tuple(row.id for row in await harness.engine.export_reads())

    assert answered == _EXPECTED
    assert answered != tuple(record_id for record_id, _ in by_instant)
    assert answered != tuple(record_id for record_id, _ in reversed(by_instant))


async def test_what_a_driver_recorded_is_what_the_engine_lists() -> None:
    """The single-instance obligation, end to end through both seams.

    The harness wires **one** ``FakeSourceReadTrail`` into the ingestion stages as a
    ``SourceReadRecorder`` and into the façade as a ``SourceReadTrail``, exactly as
    the composition root does (ADR-0185 §4, ADR-0186 §10). So driving a real
    ingestion writes a row through the narrow seam, and the engine's own operation is
    the only thing that reads it back.

    **This is the case that says the surface is not decorative.** Every other case in
    this lane seeds a trail directly and would pass just as well against a façade
    wired to a second, empty store — which is the failure ADR-0042 §2 says no type
    can catch, and the one #1485 records for the audit trail one store over: a
    correct value with no reader.

    The row is asserted from ADR-0185 §2's fields rather than by object identity,
    because what the driver wrote and what the engine returns are two detached
    snapshots by contract (ADR-0021 §4) and comparing objects would assert the wrong
    thing.
    """
    reader = FakeReader()
    harness = Harness(reader=reader)

    report = await harness.engine.ingest_calendar()
    listed = await harness.engine.recent_reads()

    assert report.source == reader.name
    assert [row.source for row in listed] == [reader.name]
    assert [row.produced for row in listed] == [report.proposed]
    assert listed == await harness.engine.export_reads()


@pytest.mark.parametrize("operation", ["recent_reads", "export_reads"])
async def test_a_read_of_the_trail_is_refused_once_shutdown_has_begun(operation: str) -> None:
    """After ``aclose``, neither read accepts new work (ADR-0042 §2 stops accepting).

    Asserted for both because they take different paths into the engine — one
    validates an argument first and the other has none to validate — so a subject
    could reject on one and not the other while looking symmetrical in the source.
    """
    harness = Harness()
    await harness.engine.aclose()

    with pytest.raises(RuntimeError, match="shutting down"):
        await getattr(harness.engine, operation)()


async def test_neither_read_changes_what_the_trail_holds(
    durable: tuple[Harness, SqliteSourceReadTrail],
) -> None:
    """ADR-0186 §4 through §10: the promoted surface reads and never appends.

    A client that could append to the record of what its assistant had read could
    fabricate the history milestone 24's exit is measured on — the fabrication
    ADR-0184 §4 closed the last route to on the audit trail, and the reason ADR-0186
    §10's pair is two reads rather than three operations.

    Asserted against the **store** after driving both operations twice, rather than
    against the absence of a method: a relay that recorded its own read — an
    access-log-of-the-access-log, which is a real temptation on an audit surface —
    would leave the Protocol's method set untouched and this trail growing.
    """
    harness, trail = durable
    before = await trail.export()

    await harness.engine.recent_reads()
    await harness.engine.export_reads()
    await harness.engine.recent_reads(limit=1)
    await harness.engine.export_reads()

    assert await trail.export() == before


def test_the_engine_is_typed_as_holding_the_wide_seam() -> None:
    """ADR-0186 §10: the façade names ``SourceReadTrail`` and not the recorder.

    The narrowing runs the other way for the three drivers — ADR-0185 §4 annotates
    each of them ``SourceReadRecorder`` so that "what a driver cannot do is *name*
    ``recent``" — and the façade is the one holder of the wide seam. Asserted on the
    annotation because that *is* the mechanism: structural typing means the object
    passed is the same class either way, and only the declared parameter type decides
    what each holder can reach. A lane that narrowed this parameter would break both
    operations and a lane that widened a driver's would hand a sensor the cursor
    ADR-0093 §5 forbids, and neither shows up in any behavioural case.
    """
    annotation = inspect.signature(Engine.__init__).parameters["reads"].annotation

    assert annotation == "SourceReadTrail"
