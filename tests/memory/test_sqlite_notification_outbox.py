"""The durable delivery outbox against ADR-0131 §3's clauses.

Two halves. The first binds :class:`~ai_assistant.memory.SqliteNotificationOutbox`
to the shared conformance suite, so the enqueue's four outcomes are held to the
same contract the canonical fake is. The second covers what only a *durable*
implementation can be held to: the byte bound, the cross-restart survival of
entries and of the delivery counter, and ADR-0131 §3b's two-store ordering, none of
which an in-memory fake has an honest answer for.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from notification_contract import CLASS, candidate
from outbox_contract import NOW, NotificationOutboxContract

from ai_assistant.core.errors import NotificationOutboxError
from ai_assistant.core.types import (
    ClassReach,
    NotificationCandidate,
    NotificationEnqueue,
    NotificationPreferences,
    NotificationReach,
)
from ai_assistant.memory import SqliteNotificationOutbox
from ai_assistant.testing import FakeNotificationPolicy, FakeNotificationStore

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.protocols import NotificationStore

#: A ceiling wide enough that no case here meets it by accident. The cases that
#: are *about* the ceiling set their own.
_ROOMY = 1024 * 1024


class MovingClock:
    """A clock a case advances, so a lease can expire without anything waiting."""

    def __init__(self, at: datetime = NOW) -> None:
        """Start at ``at``."""
        self._at = at

    def __call__(self) -> datetime:
        """The current reading."""
        return self._at

    def advance(self, by: timedelta) -> datetime:
        """Move the clock forward and return the new reading."""
        self._at += by
        return self._at


def build(  # noqa: PLR0913 — one keyword per figure a case may vary, each defaulted
    path: Path | str,
    *,
    records: NotificationStore | None = None,
    now: object = None,
    lease: timedelta = timedelta(seconds=120),
    max_entries: int = 256,
    max_bytes: int = _ROOMY,
    candidate_ceiling: int = _ROOMY,
) -> SqliteNotificationOutbox:
    """One outbox, with everything a case is not about held constant."""
    return SqliteNotificationOutbox(
        path=path,
        records=records if records is not None else FakeNotificationStore(),
        lease=lease,
        max_entries=max_entries,
        max_bytes=max_bytes,
        candidate_ceiling=candidate_ceiling,
        now=(lambda: NOW) if now is None else now,  # type: ignore[arg-type]
    )


async def interrupting(
    records: FakeNotificationStore, key: str = "k1"
) -> tuple[str, NotificationCandidate]:
    """Rule one candidate to ``INTERRUPT`` and return its record id and candidate.

    The only path to an ``INTERRUPT`` is ADR-0130 §5's conjunctive clause with all
    four conditions held — perishable, a class at ``interrupt``, no quiet window,
    and budget to spend — so the class has to be raised before the offer. Its
    rarity "is the decision rather than a side effect", which is why this is a
    helper rather than something a case can stumble into.
    """
    await records.set_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),)
        )
    )
    subject = candidate(key=key, expires_at=NOW + timedelta(hours=2))
    ruled = await records.admit(subject, policy=FakeNotificationPolicy())
    assert ruled.notification_id is not None
    return ruled.notification_id, subject


class TestSqliteNotificationOutboxContract(NotificationOutboxContract):
    """The durable outbox against ADR-0131 §3b's shared suite."""

    @pytest.fixture
    def outbox(self, tmp_path: Path) -> SqliteNotificationOutbox:
        """An empty outbox on disk, on a clock nothing moves."""
        return build(tmp_path / "outbox.db")


class TestTheDurableTransitions:
    """The engine-side transitions ``core`` declares no Protocol for."""

    async def test_a_claim_leases_the_oldest_entry(self, tmp_path: Path) -> None:
        """§2a: selection, mint and lease are one step, in enqueue order."""
        outbox = build(tmp_path / "outbox.db")
        await outbox.offer(candidate(key="k1"))
        await outbox.offer(candidate(key="k2"))

        delivery = await outbox.claim()

        assert delivery is not None
        assert delivery.notification.candidate_key == "k1"

    async def test_a_delivery_identifier_has_both_halves(self, tmp_path: Path) -> None:
        """§4: a counter for uniqueness, 128 secure bits for unguessability.

        Both halves, because neither carries both obligations: a bare UUID is
        collision-*resistant* rather than unique, and a bare counter is a
        capability anyone can forge — "a device that has seen ``41`` can send
        ``acknowledging='42'`` and retire an entry leased to *another* device".
        """
        outbox = build(tmp_path / "outbox.db")
        await outbox.offer(candidate(key="k1"))

        delivery = await outbox.claim()

        assert delivery is not None
        counter, token = delivery.delivery_id.split(".")
        assert counter.isdigit()
        assert len(token) == 32
        assert int(token, 16) >= 0
        assert len(delivery.delivery_id.encode("utf-8")) <= 96

    async def test_the_delivery_counter_never_goes_backwards_across_a_restart(
        self, tmp_path: Path
    ) -> None:
        """§4: "The counter advances once per delivery and never goes backwards, a
        restart included."

        This is what makes uniqueness a *guarantee* rather than a probability, and
        it is the property a fresh in-memory counter would silently lose.
        """
        path = tmp_path / "outbox.db"
        outbox = build(path)
        await outbox.offer(candidate(key="k1"))
        first = await outbox.claim()
        assert first is not None
        outbox.close()

        reopened = build(path)
        await reopened.reconcile()
        second = await reopened.claim()

        assert second is not None
        assert int(second.delivery_id.split(".")[0]) > int(first.delivery_id.split(".")[0])

    async def test_an_entry_survives_a_restart(self, tmp_path: Path) -> None:
        """§3: "A notification the hub has disposed and not yet delivered is never
        held only in memory."

        ADR-0124 §11 records that "a laptop hub sleeps", so a hub that notices
        something at 02:00, restarts at 03:00 and has forgotten it by morning has
        produced exactly the failure this leg exists to close.
        """
        path = tmp_path / "outbox.db"
        outbox = build(path)
        await outbox.offer(candidate(key="k1"))
        outbox.close()

        reopened = build(path)
        delivery = await reopened.claim()

        assert delivery is not None
        assert delivery.notification.candidate_key == "k1"

    async def test_a_restart_voids_every_lease(self, tmp_path: Path) -> None:
        """§3: "no lease survives the process that granted it".

        "An entry still leased at startup is one whose holder is definitionally
        gone", and carrying leases across would mean a hub back in ten seconds
        waited out a full lease before anyone could have the entry.
        """
        path = tmp_path / "outbox.db"
        outbox = build(path)
        await outbox.offer(candidate(key="k1"))
        assert await outbox.claim() is not None
        outbox.close()

        reopened = build(path)
        await reopened.reconcile()

        assert await reopened.claim() is not None

    async def test_the_enqueue_order_survives_a_restart(self, tmp_path: Path) -> None:
        """§3: without stable ordering state, "the oldest entry" has no meaning
        after a restart — which is what the byte cost's definition-not-a-list is
        partly about."""
        path = tmp_path / "outbox.db"
        outbox = build(path)
        await outbox.offer(candidate(key="k1"))
        await outbox.offer(candidate(key="k2"))
        outbox.close()

        reopened = build(path, max_entries=2)
        await reopened.offer(candidate(key="k3"))

        delivery = await reopened.claim()
        assert delivery is not None
        assert delivery.notification.candidate_key == "k2"

    async def test_a_lease_expiry_returns_the_entry(self, tmp_path: Path) -> None:
        """§3: at-least-once, made observable."""
        clock = MovingClock()
        outbox = build(tmp_path / "outbox.db", now=clock, lease=timedelta(seconds=120))
        await outbox.offer(candidate(key="k1"))
        first = await outbox.claim()
        assert first is not None

        clock.advance(timedelta(seconds=121))

        second = await outbox.claim()
        assert second is not None
        assert second.delivery_id != first.delivery_id

    async def test_a_superseded_acknowledgement_is_a_no_op(self, tmp_path: Path) -> None:
        """§3: only the entry's *current* outstanding delivery retires it."""
        clock = MovingClock()
        outbox = build(tmp_path / "outbox.db", now=clock, lease=timedelta(seconds=120))
        await outbox.offer(candidate(key="k1"))
        stale = await outbox.claim()
        assert stale is not None
        clock.advance(timedelta(seconds=121))
        current = await outbox.claim()
        assert current is not None

        await outbox.acknowledge(stale.delivery_id)

        assert await outbox.offer(candidate(key="k1")) is NotificationEnqueue.ALREADY_HELD
        await outbox.acknowledge(current.delivery_id)
        assert await outbox.offer(candidate(key="k1")) is NotificationEnqueue.ENQUEUED


class TestTheBounds:
    """ADR-0131 §3's two bounds, which only a durable outbox can be held to."""

    async def test_the_byte_bound_drops_until_both_bounds_hold(self, tmp_path: Path) -> None:
        """§3: "It drops until the bounds hold, not once, and the difference is not
        pedantry."

        One drop is enough for the count bound, where every entry costs exactly
        one, and not for the byte bound, where entries differ by orders of
        magnitude — the seventh round exhibited an outbox half a megabyte over
        after the single drop an earlier draft authorised.
        """
        outbox = build(tmp_path / "outbox.db", max_bytes=1200)
        for key in ("k1", "k2", "k3", "k4", "k5", "k6"):
            assert await outbox.offer(candidate(key=key)) is NotificationEnqueue.ENQUEUED

        seen = []
        while (delivery := await outbox.claim()) is not None:
            seen.append(delivery.notification.candidate_key)
            await outbox.acknowledge(delivery.delivery_id)

        assert "k6" in seen
        assert "k1" not in seen

    async def test_an_entry_over_the_byte_bound_alone_is_refused(self, tmp_path: Path) -> None:
        """§3: "An entry whose own byte cost exceeds ``hub_notification_outbox_bytes``
        is refused at the enqueue… It is never satisfied by evicting other entries."

        Which is what keeps the eviction rule from emptying the outbox for a single
        entry that could never fit.
        """
        outbox = build(tmp_path / "outbox.db", max_bytes=200)
        await outbox.offer(candidate(key="k1"))

        assert await outbox.offer(candidate(key="k2")) is NotificationEnqueue.TOO_LARGE

    async def test_the_delivery_ceiling_refuses_before_any_bound_is_consulted(
        self, tmp_path: Path
    ) -> None:
        """§4: a candidate over the contract limit less the delivery reserve
        "cannot be delivered… and it never reaches the outbox"."""
        outbox = build(tmp_path / "outbox.db", candidate_ceiling=10)

        assert await outbox.offer(candidate(key="k1")) is NotificationEnqueue.TOO_LARGE
        assert await outbox.claim() is None

    async def test_the_count_bound_prefers_an_unleased_victim(self, tmp_path: Path) -> None:
        """§3: "each drop taking the oldest entry that is not leased"."""
        outbox = build(tmp_path / "outbox.db", max_entries=2)
        await outbox.offer(candidate(key="k1"))
        await outbox.offer(candidate(key="k2"))
        leased = await outbox.claim()
        assert leased is not None
        assert leased.notification.candidate_key == "k1"

        await outbox.offer(candidate(key="k3"))

        await outbox.acknowledge(leased.delivery_id)
        remaining = await outbox.claim()
        assert remaining is not None
        assert remaining.notification.candidate_key == "k3"

    async def test_every_entry_leased_still_has_a_defined_victim(self, tmp_path: Path) -> None:
        """§3: the eviction rule is stated as a *total* function.

        "Drop the oldest undelivered entry" has no subject when every entry is
        leased, and an implementation reaching that state has two illegal moves
        available with nothing to choose between them. Breaking a lease forfeits
        the redelivery and not the notification, which is the cheapest thing
        available to break.
        """
        outbox = build(tmp_path / "outbox.db", max_entries=1)
        await outbox.offer(candidate(key="k1"))
        assert await outbox.claim() is not None

        assert await outbox.offer(candidate(key="k2")) is NotificationEnqueue.ENQUEUED

        delivery = await outbox.claim()
        assert delivery is not None
        assert delivery.notification.candidate_key == "k2"

    def test_a_bound_that_cannot_hold_is_refused_at_construction(self, tmp_path: Path) -> None:
        """§5a: none of the figures is nullable and none may be zero."""
        for kwargs in (
            {"lease": timedelta(0)},
            {"max_entries": 0},
            {"max_bytes": 0},
            {"candidate_ceiling": 0},
        ):
            with pytest.raises(ValueError, match="ADR-0131 §5a"):
                build(tmp_path / "outbox.db", **kwargs)


class TestTheTwoStoreOrdering:
    """ADR-0131 §3b: dismiss first, remove after, and reconcile both directions."""

    async def test_an_acknowledgement_dismisses_the_record(self, tmp_path: Path) -> None:
        """§3b: "**Every** way an entry leaves the outbox **dismisses** its ADR-0130
        record."

        Without it, a delivered and retired entry leaves an actionable record with
        no entry — indistinguishable from one that never reached the outbox — so
        the next startup would tell the owner again.
        """
        records = FakeNotificationStore()
        record_id, subject = await interrupting(records)
        outbox = build(tmp_path / "outbox.db", records=records)
        await outbox.offer(subject)
        delivery = await outbox.claim()
        assert delivery is not None

        await outbox.acknowledge(delivery.delivery_id)

        held = await records.get(record_id)
        assert held is not None
        assert held.dismissed_at is not None

    async def test_reconciliation_offers_an_actionable_interrupt_with_no_entry(
        self, tmp_path: Path
    ) -> None:
        """§3b: the missing-entry direction — an incomplete handoff, repaired.

        ADR-0130 §3 makes recording the disposition and spending the budget one
        atomic act; ``offer`` is a second act with its own commit. Crash between
        them and the budget is spent, the record exists, no entry exists, and
        nothing brings the two back into agreement.
        """
        records = FakeNotificationStore()
        await interrupting(records)
        outbox = build(tmp_path / "outbox.db", records=records)

        await outbox.reconcile()

        delivery = await outbox.claim()
        assert delivery is not None
        assert delivery.notification.candidate_key == "k1"

    async def test_reconciliation_is_idempotent(self, tmp_path: Path) -> None:
        """§3b: "idempotent by §3's key rule, since every path keys on the
        candidate's own ``candidate_key``"."""
        records = FakeNotificationStore()
        await interrupting(records)
        outbox = build(tmp_path / "outbox.db", records=records)

        await outbox.reconcile()
        await outbox.reconcile()

        first = await outbox.claim()
        assert first is not None
        await outbox.acknowledge(first.delivery_id)
        assert await outbox.claim() is None

    async def test_reconciliation_removes_a_departing_entry(self, tmp_path: Path) -> None:
        """§3b: the second direction, which a one-way sweep leaves accumulating."""
        clock = MovingClock()
        outbox = build(tmp_path / "outbox.db", now=clock)
        await outbox.offer(candidate(key="k1", expires_at=NOW + timedelta(minutes=5)))
        clock.advance(timedelta(minutes=6))

        await outbox.reconcile()

        assert await outbox.claim() is None

    async def test_a_withdrawal_removes_the_entry_carrying_a_record(self, tmp_path: Path) -> None:
        """§3a: "An entry the outbox still holds may be **withdrawn** by the act
        that disposes of it differently, and withdrawing it removes it as an
        eviction does."

        The delete right reaches the outbox: delete a record whose entry has not
        been written and nothing in §3 made that entry departing, so it would be
        delivered after the user deleted the thing it was about.
        """
        records = FakeNotificationStore()
        record_id, subject = await interrupting(records)
        outbox = build(tmp_path / "outbox.db", records=records)
        await outbox.offer(subject)

        assert await outbox.withdraw(record_id) is True

        assert await outbox.claim() is None

    async def test_a_withdrawal_of_an_unheld_record_reports_nothing(self, tmp_path: Path) -> None:
        """§3a: a record with no entry is a no-op rather than a failure."""
        outbox = build(tmp_path / "outbox.db")

        assert await outbox.withdraw("no-such-record") is False


class TestTheSeamsFailures:
    """What this seam raises, and that it is always its own error."""

    def test_an_unopenable_database_is_the_seams_own_error(self, tmp_path: Path) -> None:
        """A backend fault is a ``NotificationOutboxError`` and never a raw
        ``sqlite3.Error`` leaking past the seam."""
        directory = tmp_path / "not-a-file"
        directory.mkdir()

        with pytest.raises(NotificationOutboxError):
            build(directory)

    def test_a_naive_clock_reading_is_the_seams_own_error(self, tmp_path: Path) -> None:
        """ADR-0026 §4: the guard raises this seam's failure, not ``core``'s raw one."""
        outbox = build(tmp_path / "outbox.db", now=lambda: datetime(2026, 1, 1, 12, 0))  # noqa: DTZ001 — the naive reading under test

        with pytest.raises(NotificationOutboxError):
            outbox._now()

    def test_the_database_file_is_owner_only(self, tmp_path: Path) -> None:
        """ADR-0004 §4: an entry holds free text a producer wrote to be shown to a
        person, so the file carries the same mode every Tier 1 store does."""
        path = tmp_path / "outbox.db"
        build(path)

        assert path.stat().st_mode & 0o777 == 0o600


def test_the_default_clock_reads_utc(tmp_path: Path) -> None:
    """The shipped clock is tz-aware, so a hub is never accidentally naive."""
    outbox = SqliteNotificationOutbox(
        path=tmp_path / "outbox.db",
        records=FakeNotificationStore(),
        lease=timedelta(seconds=120),
        max_entries=256,
        max_bytes=_ROOMY,
        candidate_ceiling=_ROOMY,
    )

    assert outbox._now().tzinfo is UTC


async def test_the_durable_wait_reports_its_timeout(tmp_path: Path) -> None:
    """The same contract the canonical fake is held to, from the durable side."""
    outbox = build(tmp_path / "outbox.db")

    assert await outbox.wait_for_arrival(timedelta(milliseconds=20)) is False


async def test_the_durable_wait_returns_early_on_an_offer(tmp_path: Path) -> None:
    """An enqueue wakes a parked poll rather than making it wait out its budget."""
    import asyncio  # noqa: PLC0415 — the scheduling is the subject

    outbox = build(tmp_path / "outbox.db")

    async def enqueue() -> None:
        await asyncio.sleep(0.01)
        await outbox.offer(candidate(key="k1"))

    woke, _ = await asyncio.gather(outbox.wait_for_arrival(timedelta(seconds=5)), enqueue())

    assert woke is True


class TestATerminalRefusalIsTerminalForTheRecord:
    """ADR-0131 §3b: a refusal that left the record actionable was the defect."""

    async def test_too_large_dismisses_the_record(self, tmp_path: Path) -> None:
        """§3b, the fifty-seventh round.

        "Returning ``TOO_LARGE`` and doing nothing else left the record actionable
        with no entry, which is exactly the state §3b's invariant reads as an
        incomplete handoff: every reconciliation would offer the same permanently-
        undeliverable candidate again, until it expired, while a polling device
        received nothing."
        """
        records = FakeNotificationStore()
        record_id, subject = await interrupting(records)
        outbox = build(tmp_path / "outbox.db", records=records, candidate_ceiling=10)

        assert await outbox.offer(subject) is NotificationEnqueue.TOO_LARGE

        held = await records.get(record_id)
        assert held is not None
        assert held.dismissed_at is not None

    async def test_a_dismissed_refusal_is_not_re_offered_by_reconciliation(
        self, tmp_path: Path
    ) -> None:
        """The property the dismissal buys: no reconciliation retries it.

        Read through the sweep rather than through the record, because "not
        actionable" is what reconciliation turns on and asserting the flag alone
        would not show that the loop is actually broken.
        """
        records = FakeNotificationStore()
        _, subject = await interrupting(records)
        outbox = build(tmp_path / "outbox.db", records=records, candidate_ceiling=10)
        await outbox.offer(subject)

        await outbox.reconcile()

        assert await outbox.claim() is None

    async def test_a_too_large_entry_over_the_byte_bound_dismisses_too(
        self, tmp_path: Path
    ) -> None:
        """The second ceiling takes the same answer, being the same outcome."""
        records = FakeNotificationStore()
        record_id, subject = await interrupting(records)
        outbox = build(tmp_path / "outbox.db", records=records, max_bytes=200)

        assert await outbox.offer(subject) is NotificationEnqueue.TOO_LARGE

        held = await records.get(record_id)
        assert held is not None
        assert held.dismissed_at is not None

    async def test_a_collision_leaves_the_held_entrys_record_alone(self, tmp_path: Path) -> None:
        """§3 meets §3b: "The held entry is not replaced."

        ADR-0130 §8 suppresses duplicates by key, so a differing candidate offered
        under a held key ordinarily shares the held entry's record — and dismissing
        that would make the held entry departing. §3b's invariant is not the one at
        risk there, because that record still *has* an entry.
        """
        records = FakeNotificationStore()
        record_id, subject = await interrupting(records)
        outbox = build(tmp_path / "outbox.db", records=records)
        await outbox.offer(subject)

        differing = subject.model_copy(update={"confidence": 0.9})
        assert await outbox.offer(differing) is NotificationEnqueue.KEY_COLLISION

        held = await records.get(record_id)
        assert held is not None
        assert held.dismissed_at is None
        delivery = await outbox.claim()
        assert delivery is not None
