"""#827 and #639 end to end: a real calendar, a real writer, a real store.

The absence close (ADR-0110 §3) has never had a reachable producer, and #827 is
that finding — made against a live hub rather than reasoned about. Two of §3's
four conditions were structurally unsatisfiable: no reader declared a coverage,
and no reader's proposals stated a position. Every unit and conformance test in
the tree passed throughout, because each half behaved exactly as its own ADR said.

**So this file composes the halves and drives them with a file on disk.** No
fakes on the producing side: a real ``CalendarReader`` over a real ``.ics``, a
real ``MemoryIngestor`` over a real ``InMemoryMemoryStore`` and the real
``DefaultMemoryPolicy``, through the one Protocol member the two meet at
(``MemoryWriter.ingest_reading``, ADR-0115 §1). Nothing here reaches inside any
of them.

**The grant is deliberately not in this composition.** Whether a source is
granted is decided before a read happens and is pinned by
``tests/orchestration/`` and ``tests/permissions/``; it was also the one half #827
verified as working against the live hub. Wiring it here would widen the subject
without adding a claim about the mechanism that was broken.

Four things are asserted, and the first is not about the close at all:

* a future entry is **retrievable** the moment it is ingested, long before it
  happens — ADR-0096 §5's whole reason for proposing calendar entries as beliefs,
  and the capability ADR-0117 §4's guard rail forbids trading away;
* repeated identical reads mint **no duplicates** — the invisibility trap
  ADR-0117 §1 records, where an unretrievable record is invisible to conflict
  detection and every read installs a fresh one;
* removing an entry from the source **retires** its belief on the next covered
  reading — #639;
* the no-coverage and raising-read arms keep behaving as ADR-0110 §3 and ADR-0115
  §4 rule.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from ics_fixtures import NOW, calendar, reader, source, utc, vevent

from ai_assistant.core.errors import ReaderError
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor
from ai_assistant.readers import CALENDAR_READER_NAME

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.protocols import Reader
    from ai_assistant.core.types import MemoryRecord

#: A meeting three hours out — outside the two-hour window the shared fixtures
#: configure, so the cases that need it widen the window rather than move the
#: clock. The clock has to stay put: the whole point is that nothing depends on it.
_LATER = NOW + timedelta(hours=3)

_STANDUP = vevent(
    f"DTSTART:{utc(NOW + timedelta(hours=1))}",
    f"DTEND:{utc(NOW + timedelta(hours=1, minutes=15))}",
    "SUMMARY:standup",
    uid="standup",
)
_REVIEW = vevent(
    f"DTSTART:{utc(_LATER)}",
    f"DTEND:{utc(_LATER + timedelta(hours=1))}",
    "SUMMARY:design review",
    uid="review",
)

#: Wide enough to hold both entries, so "removed from the source" is the only
#: reason either could stop being reported.
_WIDE = {"window_future": timedelta(days=1)}


def _hub() -> tuple[InMemoryMemoryStore, MemoryIngestor]:
    """The composition root's pairing, with the clock the fixtures freeze."""
    store = InMemoryMemoryStore(now=lambda: NOW)
    return store, MemoryIngestor(store=store, policy=DefaultMemoryPolicy(), now=lambda: NOW)


async def _cycle(writer: MemoryIngestor, subject: Reader) -> None:
    """One scheduled cycle: read the source, put the whole reading through.

    One call into the writer and never one per proposal, which is ADR-0115 §2's
    clause and the reason the member takes a whole reading: a caller able to pair
    one reading's proposals with another reading's coverage would close records
    over a slice nobody exhausted.
    """
    await writer.ingest_reading(await subject.read())


async def _live_titles(store: InMemoryMemoryStore) -> set[str]:
    """Every live belief's entry title — what the assistant could answer from."""
    return {
        record.content.split('"')[1]
        for record in await store.list_beliefs(limit=100, offset=0)
        if '"' in record.content
    }


async def _held(store: InMemoryMemoryStore) -> list[MemoryRecord]:
    return list(await store.export())


async def test_a_future_entry_is_retrievable_the_moment_it_is_ingested(
    tmp_path: Path,
) -> None:
    """ADR-0117 §4's guard rail, and the capability ADR-0110 §3's carrier destroyed.

    "No implementation of this decision may make a belief's presence on the read
    path depend on when it was last read." A meeting three hours out is searchable,
    enumerable and gettable *now* — which is how "what is on my calendar this
    afternoon" is answered at all (ADR-0096 §5 gives the facet three scalars and
    deliberately no entry text).

    Under ADR-0110 §3's original reading this belief's envelope window would have
    been the meeting's own span, and all three of those would have been false until
    the meeting began (ADR-0117 §1).
    """
    path = source(tmp_path, calendar(_REVIEW))
    store, writer = _hub()

    await _cycle(writer, reader(path, **_WIDE))

    assert await _live_titles(store) == {"design review"}
    held = await _held(store)
    assert len(held) == 1
    assert held[0].validity.live_at(NOW), "live three hours before the meeting starts"
    assert await store.search("design review", limit=5), "and reachable by search"


async def test_repeated_identical_reads_fold_rather_than_minting_duplicates(
    tmp_path: Path,
) -> None:
    """The invisibility trap ADR-0117 §1 records, at the cadence #827 observed.

    A reader mints a fresh id per proposal (ADR-0092 §6), so idempotency lives in
    the fold: an unchanged re-read proposes the same content,
    ``_detect_conflicts`` ranks the identical live record top, the policy rules
    ``REINFORCE``, and the fold lands at the **target's** id.

    That whole chain runs through ``MemoryStore.search``, which returns only live
    records — so a producer whose beliefs were not live would find no conflict, and
    every cycle would install a duplicate at a freshly minted id. At a 20-second
    interval that is thousands of unretrievable, un-demotable records per entry per
    day, which is why this is asserted over three cycles rather than assumed.
    """
    path = source(tmp_path, calendar(_STANDUP, _REVIEW))
    store, writer = _hub()

    for _ in range(3):
        await _cycle(writer, reader(path, **_WIDE))

    assert len(await _held(store)) == 2, "one record per entry, however often we read"
    assert await _live_titles(store) == {"standup", "design review"}


async def test_removing_an_entry_retires_its_belief_on_the_next_covered_read(
    tmp_path: Path,
) -> None:
    """#639 and #827, end to end and with nothing stubbed.

    A cancelled meeting stops being believed — and it stops on the strength of a
    reading that *exhausted the region the entry occupies and did not find it*,
    which is the warrant ADR-0110 §2 built coverage to supply and ADR-0117 §3's
    extent to make checkable.

    **Retired, not deleted** (ADR-0045 §6): the record stays in the store and in
    ``export``, with its window closed. And the entry that is still in the file is
    untouched, which is the property that separates this from "the reader stopped
    reporting" — one belief moved and the other did not.
    """
    path = source(tmp_path, calendar(_STANDUP, _REVIEW))
    store, writer = _hub()
    await _cycle(writer, reader(path, **_WIDE))
    assert await _live_titles(store) == {"standup", "design review"}

    source(tmp_path, calendar(_STANDUP))  # the review is called off
    await _cycle(writer, reader(path, **_WIDE))

    assert await _live_titles(store) == {"standup"}
    retired = [record for record in await _held(store) if "design review" in record.content]
    assert len(retired) == 1, "retired, not deleted"
    assert retired[0].validity.valid_until == NOW
    assert not retired[0].validity.live_at(NOW)


async def test_an_emptied_calendar_retires_everything_it_had_reported(
    tmp_path: Path,
) -> None:
    """The reading that retires the most on the least, and it is the correct one.

    A cleared calendar produces an **empty** reading, which ADR-0093 §8 rules a
    success rather than a failure signal. The safety is not that the set is small:
    it is that every record in it satisfied all four of §3's conditions, that the
    source is re-read on a schedule, and that a wrongly closed attested window is
    re-proposed by the next read (ADR-0092 §4).
    """
    path = source(tmp_path, calendar(_STANDUP, _REVIEW))
    store, writer = _hub()
    await _cycle(writer, reader(path, **_WIDE))

    source(tmp_path, calendar())
    await _cycle(writer, reader(path, **_WIDE))

    assert await _live_titles(store) == set()
    assert len(await _held(store)) == 2, "both retained, both retired"


async def test_a_belief_this_source_did_not_report_is_untouched(tmp_path: Path) -> None:
    """§3's condition 1 through the real composition, not only through the rule.

    A second calendar's beliefs are out of reach of this one's reading, whatever it
    covers — and so is anything the user asserted, which is #729's clause holding
    by construction rather than by a check.
    """
    path = source(tmp_path, calendar(_STANDUP))
    store, writer = _hub()
    await _cycle(writer, reader(path, **_WIDE))
    ours = (await _held(store))[0]
    attestation = ours.provenance.attestation
    assert attestation is not None
    # The same belief in every respect but its reporter — so a survivor is spared
    # by condition 1 and by nothing else about its shape.
    await store.add(
        ours.model_copy(
            update={
                "id": "someone-elses",
                "provenance": ours.provenance.model_copy(
                    update={
                        "attestation": attestation.model_copy(
                            update={"reported_by": "calendar:personal"}
                        )
                    }
                ),
            }
        )
    )

    source(tmp_path, calendar())
    await _cycle(writer, reader(path, **_WIDE))

    held = {record.id: record for record in await _held(store)}
    assert held["someone-elses"].validity.live_at(NOW), "another source's belief is unreachable"


async def test_an_entry_the_reader_cannot_interpret_suspends_the_demotion(
    tmp_path: Path,
) -> None:
    """§5's second clause, end to end and with its cost visible.

    The design review is genuinely gone from the file. It is **not** retired,
    because the same read could not interpret a third entry the source still holds
    — so the reading declares no coverage, takes ADR-0115 §4's ruled path, and
    warrants nothing. The cost is real and silent, and ADR-0117's Consequences say
    so; the alternative is closing windows on a warrant the reading does not have,
    for an entry that will not be re-proposed by any later read either.
    """
    unreadable = vevent("SUMMARY:no start at all", uid="broken")
    path = source(tmp_path, calendar(_STANDUP, _REVIEW))
    store, writer = _hub()
    await _cycle(writer, reader(path, **_WIDE))
    assert await _live_titles(store) == {"standup", "design review"}

    source(tmp_path, calendar(_STANDUP, unreadable))
    reading = await reader(path, **_WIDE).read()
    assert reading.coverage is None, "the read did not account for everything it held"
    await writer.ingest_reading(reading)

    assert await _live_titles(store) == {"standup", "design review"}


async def test_a_read_that_cannot_complete_retires_nothing(tmp_path: Path) -> None:
    """ADR-0093 §8 and ADR-0110 §4's suspension, at the seam that must honour both.

    A read that cannot complete **raises** and constructs no reading at all, so
    there is nothing to reconcile and nothing to retire. This is the failure mode
    ADR-0093 §4's indistinguishability argument is about: a missing file and an
    emptied calendar must never look alike to the write path, and here they do not
    — the emptied calendar retires two beliefs and the missing file retires none.
    """
    path = source(tmp_path, calendar(_STANDUP, _REVIEW))
    store, writer = _hub()
    subject = reader(path, **_WIDE)
    await _cycle(writer, subject)
    path.unlink()

    with pytest.raises(ReaderError):
        await _cycle(writer, reader(path, **_WIDE))

    assert await _live_titles(store) == {"standup", "design review"}


async def test_the_beliefs_carry_this_readers_identity_and_the_sources_report_time(
    tmp_path: Path,
) -> None:
    """What the close is scoped by, and the fact it is deliberately not scoped by.

    ``reported_by`` is the only durable handle a stored record keeps on where it
    came from (ADR-0092 §6), and it is what ADR-0110 §3's condition 1 keys on. The
    extent beside it is a different fact about a different thing: this entry's
    ``DTSTAMP`` is months before the meeting it describes, and neither value is
    derived from the other (ADR-0117 §6).
    """
    path = source(tmp_path, calendar(_REVIEW))
    store, writer = _hub()

    await _cycle(writer, reader(path, **_WIDE))

    attestation = (await _held(store))[0].provenance.attestation
    assert attestation is not None
    assert attestation.reported_by == CALENDAR_READER_NAME
    assert attestation.reported_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert attestation.extent is not None
    assert attestation.extent.extends_from == _LATER
