"""Milestone 24's read half: ADR-0185 §11's five pre-registered arms.

§11 is quoted at each arm so every case is measured against the ratified wording
rather than against a paraphrase. Its framing clause:

    The read half of milestone 24's exit is pre-registered as the five arms and the
    five figures below. No lane substitutes an arm, drops a figure, or reports the
    read half met on a run that did not produce all five figures.

And the clause that decides what a non-zero figure means:

    A non-zero figure on any of the five is a **breach of a ratified clause** and
    not a threshold to tune. The lane reports it, opens the issue, and does not
    close the milestone on it.

So all five are asserted here as well as reported: a breach of a ratified clause
may not sit inside a green gate.

**Each figure is measured over its own arm's run and no other** (§11). Arms (a),
(b), (c) and (e) run far below the cap so nothing is pruned under them; arm (d)
deliberately drives more than its cap, "so a completeness figure taken over arm (d)
would count the prune as a loss".

The egress half (#747) and band precedence (#663) are pre-registered by their own
lanes and are not this ADR's, so nothing here reports them.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import m24_harness
import pytest
from m24_harness import (
    CALENDAR,
    EMAIL,
    READ_AT,
    ROOMY,
    Clock,
    Driven,
    Gate,
    OutstandingReader,
    World,
    count,
    failing_reader,
    reconstruct,
    report,
    seeded_reader,
)

from ai_assistant.core.errors import ReadTrailError
from ai_assistant.core.types import GrantScope, ReadOutcome
from ai_assistant.testing import FakeSourceReadRecorder, source_grant
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ai_assistant.core.types import SourceReadRecord

#: The marker arm (c) seeds into the source's entries, its path and its configured
#: location, and then searches every exported field for. A single token with no
#: substring that could occur naturally, so a hit is a leak and never a collision.
MARKER = "zqxleakmarker7"

#: How many proposals a seeded reading carries, so ``produced`` is a number the arm
#: writes down rather than reads back off the record it is checking.
SEEDED = 2


@pytest.fixture
def world() -> Iterator[World]:
    """A world at a roomy cap, closed after the arm."""
    subject = World()
    try:
        yield subject
    finally:
        subject.close()


async def _drive_the_six(world: World, use: GrantScope, source: str) -> list[Driven]:
    """Drive one attempt to each of ``ReadOutcome``'s six members, for one use.

    Every arrangement is the ratified clause it comes from, and each is named at the
    call rather than left to be inferred from the fixture:

    * ``COMPLETED`` — granted throughout; the gate ruled the reading admissible.
    * ``REFUSED`` — the first ``live()`` answered ``None`` (ADR-0097 §5).
    * ``UNANSWERED`` — the first ``live()`` raised, so the driver failed closed.
    * ``FAILED`` — the read raised (ADR-0093 §8).
    * ``DISCARDED`` — the re-check answered ``None``, so the reading was discarded
      whole (ADR-0097 §5).
    * ``UNCONFIRMED`` — the re-check raised, so it was discarded "exactly as a
      withdrawn grant is".

    The last three are the ones §11 singles out: "``UNANSWERED``, ``DISCARDED`` and
    ``UNCONFIRMED`` are the three outcomes no ordinary run produces, and they are the
    three this ADR adds the most value by recording; an exit test that never drove
    them would leave them unexercised in the state that matters."
    """
    driven: list[Driven] = []

    driven.append(
        await world.drive(
            use,
            reader=seeded_reader(source, proposals=SEEDED),
            gate=world.granted(source),
            outcome=ReadOutcome.COMPLETED,
            produced=SEEDED,
        )
    )
    driven.append(
        await world.drive(
            use,
            reader=seeded_reader(source, proposals=SEEDED),
            gate=world.ungranted(),
            outcome=ReadOutcome.REFUSED,
        )
    )
    driven.append(
        await world.drive(
            use,
            reader=seeded_reader(source, proposals=SEEDED),
            gate=world.granted(source),
            outcome=ReadOutcome.UNANSWERED,
            raise_on=(1,),
        )
    )
    driven.append(
        await world.drive(
            use,
            reader=failing_reader(source),
            gate=world.granted(source),
            outcome=ReadOutcome.FAILED,
        )
    )

    revoked = world.granted(source)
    revoked.inner.revoke_after(1)
    driven.append(
        await world.drive(
            use,
            reader=seeded_reader(source, proposals=SEEDED),
            gate=revoked,
            outcome=ReadOutcome.DISCARDED,
            produced=SEEDED,
        )
    )
    driven.append(
        await world.drive(
            use,
            reader=seeded_reader(source, proposals=SEEDED),
            gate=world.granted(source),
            outcome=ReadOutcome.UNCONFIRMED,
            raise_on=(2,),
            produced=SEEDED,
        )
    )
    return driven


# --- arm (a): completeness ---------------------------------------------------


async def _run_arm_a(world: World) -> tuple[list[Driven], list[SourceReadRecord]]:
    """Drive arm (a)'s run: eighteen attempts, then export.

    Six outcomes over three uses, alternating the two declared readers so that both
    identities appear under every use — §11's "across all three uses and both
    readers, including at least one of each of ``ReadOutcome``'s six members".
    Eighteen is far below :data:`~m24_harness.ROOMY`, so nothing is pruned.
    """
    driven: list[Driven] = []
    for index, use in enumerate(GrantScope):
        driven += await _drive_the_six(world, use, CALENDAR if index % 2 == 0 else EMAIL)
    return driven, await world.trail.export()


async def test_arm_a_reconstructs_every_attempt_from_the_trail_alone(world: World) -> None:
    """§11 arm (a), and §10's definition of what "reconstructible" means.

    §10: "'Reconstructible' means, for a read, that the trail alone yields the
    source's declared identity, the use, the instant its grant check resolved, its
    outcome, whether the source was opened where §1 determines it, the grant it ran
    under where there was one, and how many items the reading carried."

    **From ``export()`` alone, with no other store consulted** — which is the arm's
    own wording and the point of the milestone: a reconstruction that reached for
    the grant store, or for memory, would be measuring a join rather than the trail.
    Every field asserted below comes off the exported row.
    """
    driven, exported = await _run_arm_a(world)
    indexed = reconstruct(exported)

    assert len(exported) == len(driven)
    for attempt in driven:
        row = indexed[attempt.checked_at]
        assert row.source == attempt.source
        assert row.use is attempt.use
        assert row.outcome is attempt.outcome
        assert row.produced == attempt.produced
        # §2's correspondence, which is what lets a reader of the trail partition a
        # row without trusting the writer's discipline.
        ungranted = attempt.outcome in {ReadOutcome.REFUSED, ReadOutcome.UNANSWERED}
        assert (row.grant is None) is ungranted


async def test_arm_a_stamps_the_instant_the_first_check_resolved(world: World) -> None:
    """§12's ``checked_at``, and the two traps §11 arms it with.

    "The arm asserts each record's ``checked_at`` against the instant that clock
    served when the first ``live()`` answered — on a ``live()`` made to suspend
    across a clock tick, so a lane that read the clock before the call fails here,
    and on a read whose bytes are acquired later, so a lane that reached for
    ``SourceReading.read_at`` fails here too."

    Both traps are live in every one of the eighteen attempts: the gate suspends and
    ticks the clock inside the first ``live()``, and every seeded reading is stamped
    :data:`~m24_harness.READ_AT`, which is hours after any instant the clock serves.
    So this asserts three things at once — the instant is the clock's, it is the
    *post*-suspension one, and it is not the reading's.
    """
    driven, exported = await _run_arm_a(world)
    indexed = reconstruct(exported)

    for attempt in driven:
        assert indexed[attempt.checked_at].checked_at == attempt.checked_at
    assert all(row.checked_at != READ_AT for row in exported)
    assert all(row.checked_at < READ_AT for row in exported)


async def test_arm_a_records_the_two_failed_shapes_indistinguishably(world: World) -> None:
    """§11 arm (a)'s ``FAILED``-twice clause: §1's indeterminacy exercised, not assumed.

    "The ``FAILED`` member is driven **twice**: once from a reader that refuses
    before starting work (``OneWorker``'s outstanding reservation) and once from one
    that fails with the bytes in hand, and the arm asserts the two records are
    indistinguishable."

    §1's ruling is that on ``FAILED`` "the read was **attempted** and raised, and
    whether the source was opened is **not determinable from the record**". The
    reason is a boundary rather than a choice: both shapes cross the seam as
    ``ReaderError`` because ADR-0093 §8 requires it, and the discriminating classes
    live in ``readers/_source.py``, which ``orchestration`` and ``context`` may not
    import under golden rule 1. A record that claimed either way would assert
    something nobody knew.

    The first shape is driven through the **real** ``OneWorker``, whose own contract
    says "Nothing is started."
    """
    # **One gate for both attempts**, so both rows cite the same grant. Two gates
    # would mint two grants, and the rows would then differ on a field that is about
    # the *authorisation* rather than about the failure — which would make the
    # comparison pass or fail for a reason §1's clause is not about.
    gate = world.granted(CALENDAR)

    outstanding = OutstandingReader(CALENDAR)
    await outstanding.occupy()
    try:
        refused_before_starting = await world.drive(
            GrantScope.INGEST,
            reader=outstanding,  # type: ignore[arg-type]  # a duck-typed reader over the real OneWorker
            gate=gate,
            outcome=ReadOutcome.FAILED,
        )
    finally:
        await outstanding.release()

    failed_with_bytes = await world.drive(
        GrantScope.INGEST,
        reader=failing_reader(CALENDAR),
        gate=gate,
        outcome=ReadOutcome.FAILED,
    )

    indexed = reconstruct(await world.trail.export())
    first = indexed[refused_before_starting.checked_at]
    second = indexed[failed_with_bytes.checked_at]

    # Everything but the record's own id and its instant, which are per-attempt by
    # construction and say nothing about the source: the two rows are the same
    # statement about two materially different events, which is the clause.
    assert first.model_dump(exclude={"id", "checked_at"}) == second.model_dump(
        exclude={"id", "checked_at"}
    )
    assert first.outcome is ReadOutcome.FAILED
    assert first.produced == 0


async def test_arm_a_figures(world: World) -> None:
    """The **unrecorded-read count** and the **misattributed outcome count** (§11).

    §11 defines the first as "over arm (a)'s run, attempts driven minus records
    exported", and the second as "over arm (a)'s and arm (b)'s runs, records whose
    outcome does not match the attempt the harness drove". Both are "zero by
    construction under §1, §2, §5 and §6 and are measured rather than asserted" —
    which says how the *ADR* establishes them, and is the instruction to measure
    rather than a prohibition on the measurement failing.

    Arm (b)'s share of the second figure is reported by its own case, over its own
    run, because §11 forbids computing a figure across arms.
    """
    driven, exported = await _run_arm_a(world)
    indexed = reconstruct(exported)

    unrecorded = len(driven) - len(exported)
    misattributed = sum(
        1 for attempt in driven if indexed[attempt.checked_at].outcome is not attempt.outcome
    )

    report(
        [
            "",
            "arm (a) — completeness (ADR-0185 §11)",
            f"  unrecorded-read count      {count(unrecorded, len(driven))}  attempts driven "
            "minus records exported; must be zero",
            f"  misattributed outcome      {count(misattributed, len(driven))}  records whose "
            "outcome does not match the attempt driven; must be zero",
        ]
    )

    assert unrecorded == 0
    assert misattributed == 0


# --- arm (b): the revocation question ----------------------------------------


async def _run_arm_b(world: World) -> list[Driven]:
    """Grant a source, drive reads, revoke it, and let the driver run again.

    §11 arm (b): "the trail alone must answer 'was this source read after I revoked
    it', telling an attempt that was refused from one that completed, from one
    discarded at the re-check, and from one whose re-check could not be answered."

    The revocation is a **real appended record** on the fake's own log rather than a
    lever that fakes the answer, so the history the gate holds afterwards is one a
    conforming store could genuinely be in.
    """
    driven: list[Driven] = []
    granted = world.granted(CALENDAR)

    driven.append(
        await world.drive(
            GrantScope.INGEST,
            reader=seeded_reader(CALENDAR, proposals=SEEDED),
            gate=granted,
            outcome=ReadOutcome.COMPLETED,
            produced=SEEDED,
        )
    )

    # The read already in flight when the revocation lands — ADR-0097 §5a's residual,
    # and the row ADR-0185 §1 says the trail most exists for.
    mid_read = world.granted(CALENDAR)
    mid_read.inner.revoke_after(1)
    driven.append(
        await world.drive(
            GrantScope.INGEST,
            reader=seeded_reader(CALENDAR, proposals=SEEDED),
            gate=mid_read,
            outcome=ReadOutcome.DISCARDED,
            produced=SEEDED,
        )
    )

    # The re-check that could not be answered: a store fault and a withdrawn grant
    # are different facts, and ADR-0097 §5 requires an operator to tell them apart.
    driven.append(
        await world.drive(
            GrantScope.INGEST,
            reader=seeded_reader(CALENDAR, proposals=SEEDED),
            gate=world.granted(CALENDAR),
            outcome=ReadOutcome.UNCONFIRMED,
            raise_on=(2,),
            produced=SEEDED,
        )
    )

    # And after the revocation: the source is configured, the timer keeps firing,
    # and every attempt is refused. ADR-0185 §7: "the interesting fact about it is
    # not that nothing was read — it is that something kept trying, on a schedule,
    # after the user said no."
    revoked = world.ungranted()
    for _ in range(3):
        driven.append(
            await world.drive(
                GrantScope.INGEST,
                reader=seeded_reader(CALENDAR, proposals=SEEDED),
                gate=revoked,
                outcome=ReadOutcome.REFUSED,
            )
        )
    return driven


async def test_arm_b_the_trail_alone_answers_the_revocation_question(world: World) -> None:
    """§11 arm (b), and the question ADR-0139 §6 says has no answer today.

    "'was this source read after I revoked it' has no answer today", because the only
    trace is ADR-0097 §8's operator log line, which "is not durable state and is not
    exportable". A trail of successes alone would answer it only by *absence*, and an
    absence in this store is ambiguous by construction — §1's own clause forbids
    reading one as evidence that a read did not happen. A ``REFUSED`` row is a
    statement.
    """
    driven = await _run_arm_b(world)
    exported = await world.trail.export()
    indexed = reconstruct(exported)

    outcomes = [indexed[attempt.checked_at].outcome for attempt in driven]
    assert outcomes == [attempt.outcome for attempt in driven]
    # The four are distinguishable from one another, which is the arm's own wording:
    # refused, completed, discarded at the re-check, and unanswerable at it.
    assert set(outcomes) == {
        ReadOutcome.COMPLETED,
        ReadOutcome.DISCARDED,
        ReadOutcome.UNCONFIRMED,
        ReadOutcome.REFUSED,
    }
    # And the discarded one still says what it carried: "this read across your
    # revocation carried two proposals that were dropped" is a materially different
    # audit fact from "it carried none" (ADR-0185 §2).
    discarded = next(row for row in exported if row.outcome is ReadOutcome.DISCARDED)
    assert discarded.produced == SEEDED


async def test_arm_b_figure(world: World) -> None:
    """The **misattributed outcome count** over arm (b)'s own run (§11).

    Reported separately from arm (a)'s because §11 forbids computing a figure across
    arms: "Each figure is measured over **its own arm's run and no other**, and each
    arm's run is stated with its denominator."
    """
    driven = await _run_arm_b(world)
    indexed = reconstruct(await world.trail.export())

    misattributed = sum(
        1 for attempt in driven if indexed[attempt.checked_at].outcome is not attempt.outcome
    )

    report(
        [
            "",
            "arm (b) — the revocation question (ADR-0185 §11)",
            f"  misattributed outcome      {count(misattributed, len(driven))}  records whose "
            "outcome does not match the attempt driven; must be zero",
        ]
    )

    assert misattributed == 0


# --- arm (c): no content -----------------------------------------------------


def _plant(directory: Path) -> Path:
    """A real ``.ics`` whose entries, path and configured location carry the marker.

    All three, because §11 arm (c) names all three: "The source is seeded with a
    distinctive marker string in its entries, its path and its configured location".
    The configured location *is* the path here — ADR-0093 §7 gives a reader one
    configured source — so the marker appears in the directory, in the filename and
    in every ``SUMMARY``.
    """
    seeded = directory / f"{MARKER}-dir"
    seeded.mkdir(parents=True, exist_ok=True)
    source = seeded / f"{MARKER}.ics"
    stamp = "20260801T090000Z"
    events = "".join(
        "\r\n".join(
            [
                "BEGIN:VEVENT",
                f"UID:{MARKER}-{index}",
                f"DTSTAMP:{stamp}",
                "DTSTART:20260801T100000Z",
                "DTEND:20260801T103000Z",
                f"SUMMARY:{MARKER} lunch with {MARKER}",
                "END:VEVENT",
                "",
            ]
        )
        for index in range(2)
    )
    source.write_bytes(
        (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//ai-assistant m24 exit//EN\r\n"
            f"{events}END:VCALENDAR\r\n"
        ).encode()
    )
    return source


async def test_arm_c_no_exported_field_carries_a_byte_of_the_source(
    world: World, tmp_path: Path
) -> None:
    """§11 arm (c) — the one that would otherwise be held by review.

    "ADR-0139 §6's content prohibition is the kind of clause a diff satisfies and a
    later field quietly breaks — a failure class stringified into a record, a path
    arriving inside an exception message, exactly the mistake ADR-0093 §8 documents
    at length. A marker search over every exported field fails on it mechanically."

    Driven against the **real** ``CalendarReader`` over a planted file, because a
    fake has no path and no configured location and so could not carry two of the
    three places §11 seeds. Both a completed read and a failed one are driven: the
    failure is the path an exception message would leak along, and it is the one
    ADR-0093 §8 documents.

    The search is over ``model_dump(mode="json")`` rather than over named fields, so
    a field a later ADR adds is searched too without this arm being edited — which is
    the property that makes it a guard rather than a snapshot.
    """
    from ai_assistant.readers import CalendarReader  # noqa: PLC0415  — arm (c) alone needs it

    source = _plant(tmp_path)
    window = READ_AT - READ_AT.replace(hour=0)
    reader = CalendarReader(source, now=lambda: READ_AT, window_past=window, window_future=window)
    await world.drive(
        GrantScope.INGEST,
        reader=reader,
        gate=world.granted(reader.name),
        outcome=ReadOutcome.COMPLETED,
    )

    missing = CalendarReader(
        source.with_name("absent.ics"),
        now=lambda: READ_AT,
        window_past=window,
        window_future=window,
    )
    await world.drive(
        GrantScope.INGEST,
        reader=missing,
        gate=world.granted(missing.name),
        outcome=ReadOutcome.FAILED,
    )

    exported = await world.trail.export()
    assert len(exported) == 2
    leaks = [row for row in exported if MARKER in str(row.model_dump(mode="json"))]

    report(
        [
            "",
            "arm (c) — no content (ADR-0185 §11)",
            f"  content-leak count         {count(len(leaks), len(exported))}  records "
            "containing any byte of the marker; must be zero",
        ]
    )

    assert leaks == []


# --- arm (d): the bound ------------------------------------------------------


async def test_arm_d_the_cap_holds_and_the_survivors_are_the_newest() -> None:
    """§11 arm (d) — "the row count never exceeds the cap and the survivors are the
    most recently recorded".

    Driven deliberately past the cap, which is why the completeness figure is not
    taken over this run: §11 says a figure taken here "would count the prune as a
    loss". The count is asserted after **every** append rather than once at the end,
    because a store that pruned on a schedule would leave a window in which it is
    over its cap and an end-of-run assertion could not see it (ADR-0185 §6: "there is
    no window in which the store is over its cap").
    """
    cap = 5
    world = World(max_rows=cap)
    try:
        driven: list[Driven] = []
        overflow = 0
        for _ in range(cap * 3):
            driven.append(
                await world.drive(
                    GrantScope.FACET,
                    reader=seeded_reader(CALENDAR, proposals=SEEDED),
                    gate=world.granted(CALENDAR),
                    outcome=ReadOutcome.COMPLETED,
                    produced=SEEDED,
                )
            )
            overflow = max(overflow, len(await world.trail.export()) - cap)

        exported = await world.trail.export()
        survivors = [row.checked_at for row in exported]
        newest = [attempt.checked_at for attempt in driven[-cap:]]

        report(
            [
                "",
                "arm (d) — the bound (ADR-0185 §11)",
                f"  overflow count             {count(max(overflow, 0), len(driven))}  rows "
                "held beyond the cap at any point; must be zero",
            ]
        )

        assert overflow <= 0
        assert survivors == newest
    finally:
        world.close()


# --- arm (e): the two attempts §5a names -------------------------------------


async def test_arm_e_nothing_comes_of_an_unrecorded_attempt(world: World) -> None:
    """§11 arm (e), quoted whole because what it does *not* assert is half of it.

    "A run drives one attempt whose recorder raises, one cancelled while ``read()``
    is outstanding, and one cancelled inside a recorder call already in flight. It
    asserts of each that nothing was proposed, no facet was contributed and no
    candidate was concluded, and of the two cancelled ones that the cancellation
    propagated unconverted. **It asserts nothing about whether a row exists** for the
    third: ADR-0060 makes that indeterminate, and an arm that pinned it either way
    would pin what the contract refuses to promise."

    §5's guarantee is over the **effects** of an unrecorded read rather than over the
    existence of its row — "nothing durable, nothing in a prompt and nothing in a
    notification comes of a read the trail does not hold" — and an exit test that
    only counted rows would never touch it, "leaving the one clause that carries the
    fail-closed property unexercised while the milestone closed on four green
    figures".
    """
    leaked = 0

    # 1. The recorder raised. The read ran; the row was attempted and refused.
    refusing = FakeSourceReadRecorder()
    refusing.fail_record()
    facet = world.driver(
        GrantScope.FACET,
        reader=seeded_reader(CALENDAR, proposals=SEEDED),
        gate=world.granted(CALENDAR),
        recorder=refusing,
    )
    with pytest.raises(ReadTrailError):
        await facet.contribute()  # type: ignore[attr-defined]  # the FACET driver
    leaked += len(refusing.written)

    ingestion_gate = world.granted(CALENDAR)
    ingestion = world.driver(
        GrantScope.INGEST,
        reader=seeded_reader(CALENDAR, proposals=SEEDED),
        gate=ingestion_gate,
        recorder=refusing,
    )
    with pytest.raises(ReadTrailError):
        await ingestion.ingest()  # type: ignore[attr-defined]  # the INGEST driver
    # Nothing was proposed: the reading is discarded whole, exactly as it is across
    # a revocation (ADR-0185 §5).
    leaked += len((await world.memory.search("reported thing", limit=10)).records)

    notify_gate = world.granted(CALENDAR)
    upcoming = world.driver(
        GrantScope.NOTIFY,
        reader=seeded_reader(CALENDAR, proposals=SEEDED),
        gate=notify_gate,
        recorder=refusing,
    )
    with pytest.raises(ReadTrailError):
        await upcoming.notice()  # type: ignore[attr-defined]  # the NOTIFY driver
    leaked += len(world.notifications.offered)

    # 2. Cancelled while `read()` is outstanding. No recorder call is started on the
    # way out (ADR-0185 §1, §5a), and the cancellation is delivered onward unchanged.
    slow = seeded_reader(CALENDAR, proposals=SEEDED)
    gate = world.granted(CALENDAR)
    gate.begin()
    suspended = slow.suspend_next()
    driver = world.driver(GrantScope.FACET, reader=slow, gate=gate, recorder=world.trail)
    running = asyncio.ensure_future(driver.contribute())  # type: ignore[attr-defined]
    await suspended.reached()
    running.cancel()
    suspended.release()
    with pytest.raises(asyncio.CancelledError):
        await running
    # Never converted into a `ReaderError`: a shutdown that is working correctly is
    # not a degraded source (ADR-0093 §8).
    assert await world.trail.export() == []

    # 3. Cancelled inside a recorder call already in flight. **Nothing is asserted
    # about whether a row exists** — ADR-0060 rules that "a cancelled write may or
    # may not have committed. The caller may assume neither."
    holding = FakeSourceReadRecorder()
    held = holding.suspend_next_operation()
    inflight_gate = world.granted(CALENDAR)
    inflight_gate.begin()
    stage = world.driver(
        GrantScope.INGEST,
        reader=seeded_reader(CALENDAR, proposals=SEEDED),
        gate=inflight_gate,
        recorder=holding,
    )
    pending = asyncio.ensure_future(stage.ingest())  # type: ignore[attr-defined]
    await held.reached()
    pending.cancel()
    held.release()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await settle()
    leaked += len((await world.memory.search("reported thing", limit=10)).records)
    leaked += len(world.notifications.offered)

    report(
        [
            "",
            "arm (e) — the two attempts ADR-0185 §5a names (§11)",
            f"  leaked-product count       {count(leaked, 4)}  proposals, facets or "
            "candidates that reached a consumer from an unrecorded attempt; must be zero",
        ]
    )

    assert leaked == 0


def test_the_read_half_registers_no_live_arm() -> None:
    """§11's last normative clause, pinned so no lane invents one.

    "The suite is **deterministic, offline and in the ordinary gate**, against
    ``ai_assistant.testing``'s fakes and a seeded reader. No live arm is registered:
    nothing in the read half depends on a model's behaviour, so ADR-0181 §8's capped
    live run has no counterpart here and no lane invents one."

    Asserted as a property of this module and its world rather than argued in prose:
    no arm here carries a mark that would take it out of the ordinary gate, and
    neither namespace holds a model seam. A lane adding a live runner would have to
    delete this case, which is a visible act rather than a quiet one.

    **Marks rather than source text**, because a scan for a word finds it in the
    prose that explains why it is absent — which is a case that fails on its own
    docstring. What is checked is what pytest actually sees.
    """
    arms = [
        value
        for name, value in vars(sys.modules[__name__]).items()
        if name.startswith("test_") and callable(value)
    ]
    marks = {mark.name for arm in arms for mark in getattr(arm, "pytestmark", ())}

    assert arms, "the discovery found no arms, so the assertion below is vacuous"
    assert marks <= {"parametrize"}, marks
    for namespace in (vars(sys.modules[__name__]), vars(m24_harness)):
        assert not any("Model" in name or "Embedder" in name for name in namespace)


def test_the_harness_serves_a_clock_no_reading_could_be_mistaken_for() -> None:
    """The trap arm (a) rests on, pinned rather than trusted to two constants.

    A run that drove eighteen attempts would move the clock eighteen ticks; if
    :data:`~m24_harness.READ_AT` were ever moved back inside that span, arm (a)'s
    "``checked_at`` is not the reading's" assertion would start passing for a
    reason that has nothing to do with the implementation.
    """
    clock = Clock()
    for _ in range(1_000):
        clock.tick()

    assert clock.now < READ_AT


def test_the_roomy_cap_is_above_what_the_completeness_arms_drive() -> None:
    """§11: arms (a) and (b) must drive fewer attempts than the cap.

    "so that nothing is pruned under them, and arm (d) deliberately drives more, so a
    completeness figure taken over arm (d) would count the prune as a loss". Arm (a)
    drives eighteen and arm (b) six; a later edit that grew either past the cap would
    make ``unrecorded-read count`` non-zero for a reason the figure does not mean.
    """
    assert ROOMY > 18 * 4


def test_the_gate_is_a_source_grants_and_nothing_wider() -> None:
    """The harness may not hand a driver more than the composition root does.

    ADR-0097 §3's split is what stops a scheduler job minting its own
    authorisation, and a harness whose gate carried ``record`` would let an arm pass
    against a wiring no deployment has.
    """
    gate: object = Gate(Clock(), [source_grant(CALENDAR)])

    for member in ("record", "recent", "export", "clear", "standing"):
        assert not hasattr(gate, member), member
