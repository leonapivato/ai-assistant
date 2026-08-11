"""The canonical delivery-outbox fake passes its shared conformance suite.

This is what lets other subsystems trust
:class:`~ai_assistant.testing.FakeNotificationOutbox` as a stand-in: it is held to
the contract ADR-0131 §3b states, by the same suite any later implementation will
be held to.

Beside the binding are the properties that are the *fake's own* rather than the
enqueue contract's — the transitions ADR-0131 declares no ``core`` Protocol for,
which reach a caller through ``orchestration``'s
:class:`~ai_assistant.orchestration.delivery.DeliveryOutbox` and so have no shared
suite to live in. They are asserted here because a fake nobody holds to them is a
fake that will diverge from the durable outbox the first time either changes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from notification_contract import CLASS, candidate
from outbox_contract import NOW, NotificationOutboxContract

from ai_assistant.core.types import (
    ClassReach,
    NotificationEnqueue,
    NotificationPreferences,
    NotificationReach,
)
from ai_assistant.testing import (
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeNotificationStore,
)


class MovingClock:
    """A clock a case advances, so a lease can be made to expire without waiting."""

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


class TestFakeNotificationOutboxContract(NotificationOutboxContract):
    """The canonical fake against ADR-0131 §3b's shared suite."""

    @pytest.fixture
    def outbox(self) -> FakeNotificationOutbox:
        """An empty outbox on a clock nothing moves."""
        return FakeNotificationOutbox(now=lambda: NOW)


class TestTheFakesDeliveryTransitions:
    """The engine-side transitions, which ``core`` declares no Protocol for."""

    async def test_a_claim_leases_the_oldest_entry_and_mints_an_identifier(self) -> None:
        """§2a: selecting, minting and leasing are one step, oldest first."""
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(candidate(key="k1"))
        await outbox.offer(candidate(key="k2"))

        first = await outbox.claim()

        assert first is not None
        assert first.notification.candidate_key == "k1"
        assert "." in first.delivery_id

    async def test_a_leased_entry_is_not_offered_to_a_second_claim(self) -> None:
        """§3: "No entry is ever outstanding to two devices at once."

        Delivered by the *lease* rather than by any identity, which is why
        ``next_notification`` needs none: an entry written to any caller is
        unavailable to every other until it is acknowledged or expires.
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(candidate(key="k1"))
        await outbox.claim()

        assert await outbox.claim() is None

    async def test_a_lease_expiry_returns_the_entry_to_the_outbox(self) -> None:
        """§3: "on expiry it returns to the outbox and may be delivered again".

        This is at-least-once made observable: a device that received a
        notification and died before acknowledging is shown it again.
        """
        clock = MovingClock()
        outbox = FakeNotificationOutbox(now=clock, lease=timedelta(seconds=120))
        await outbox.offer(candidate(key="k1"))
        first = await outbox.claim()
        assert first is not None

        clock.advance(timedelta(seconds=121))
        second = await outbox.claim()

        assert second is not None
        assert second.delivery_id != first.delivery_id

    async def test_an_acknowledgement_retires_the_entry(self) -> None:
        """§3: the acknowledgement is the terminal transition, not the write."""
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(candidate(key="k1"))
        delivery = await outbox.claim()
        assert delivery is not None

        await outbox.acknowledge(delivery.delivery_id)

        assert await outbox.offer(candidate(key="k1")) is NotificationEnqueue.ENQUEUED

    async def test_a_superseded_acknowledgement_is_a_no_op(self) -> None:
        """§3, §4: only the *current* outstanding delivery retires an entry.

        The sixteenth round's finding. Device A takes a delivery and goes quiet;
        the lease expires; the entry goes to device B. An acknowledgement scoped to
        the *entry* would let A retire B's delivery, possibly before B has shown it
        — losing the notification and falsifying at-least-once. A fresh identifier
        per delivery is what makes the condition decidable without the outbox
        knowing who is asking.
        """
        clock = MovingClock()
        outbox = FakeNotificationOutbox(now=clock, lease=timedelta(seconds=120))
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

    async def test_an_unknown_acknowledgement_is_accepted_and_does_nothing(self) -> None:
        """§3: the idempotent no-op is what lets a client acknowledge blindly."""
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(candidate(key="k1"))

        await outbox.acknowledge("nothing-the-outbox-minted")

        assert await outbox.offer(candidate(key="k1")) is NotificationEnqueue.ALREADY_HELD

    async def test_an_expired_entry_is_never_selected(self) -> None:
        """§3: a departing entry "is not selected for a poll".

        The one thing ADR-0130's perishability rule exists to prevent is a
        notification arriving after the moment it said it stopped mattering.
        """
        clock = MovingClock()
        outbox = FakeNotificationOutbox(now=clock)
        await outbox.offer(candidate(key="k1", expires_at=NOW + timedelta(minutes=5)))
        clock.advance(timedelta(minutes=6))

        assert await outbox.claim() is None

    async def test_the_count_bound_drops_the_oldest_unleased_entry(self) -> None:
        """§3: an enqueue over the bound drops until both bounds hold.

        "An outbox that is full is one whose owner has not been reachable, and of
        the notifications waiting, the stale ones are the ones worth least."
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW, max_entries=2)
        await outbox.offer(candidate(key="k1"))
        await outbox.offer(candidate(key="k2"))

        await outbox.offer(candidate(key="k3"))

        delivered = await outbox.claim()
        assert delivered is not None
        assert delivered.notification.candidate_key == "k2"

    async def test_a_leased_entry_is_the_last_victim_the_bound_takes(self) -> None:
        """§3: "leases are preferred *last*, and the tie-break is the same age order".

        The oldest entry is leased, so the bound takes the oldest *unleased* one
        instead — which is what makes the rule a preference rather than a blanket
        exemption, since the all-leased case still has to have an answer.
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW, max_entries=2)
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

    async def test_reconciliation_voids_every_lease(self) -> None:
        """§3: "A hub restart voids every lease."

        "A lease is only meaningful while the connection that took the delivery
        exists, and no connection survives a hub restart — so an entry still leased
        at startup is one whose holder is definitionally gone."
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(candidate(key="k1"))
        first = await outbox.claim()
        assert first is not None

        await outbox.reconcile()

        second = await outbox.claim()
        assert second is not None
        assert second.delivery_id != first.delivery_id

    async def test_reconciliation_removes_a_departing_entry(self) -> None:
        """§3b: the sweep runs in both directions, and this is the second.

        A removal that failed leaves a departing entry which the missing-entry
        sweep never looks at — it has a record — "and it is undeliverable while
        still counting against both bounds. Repeat that a few times and the outbox
        fills with entries nothing can clear."
        """
        clock = MovingClock()
        outbox = FakeNotificationOutbox(now=clock)
        await outbox.offer(candidate(key="k1", expires_at=NOW + timedelta(minutes=5)))
        clock.advance(timedelta(minutes=6))

        await outbox.reconcile()

        assert await outbox.claim() is None
        assert await outbox.offer(candidate(key="k1", noticed_at=clock())) is (
            NotificationEnqueue.ENQUEUED
        )

    async def test_a_candidate_over_the_ceiling_is_refused_not_evicted(self) -> None:
        """§4: the delivery ceiling "is never satisfied by evicting other entries"."""
        outbox = FakeNotificationOutbox(now=lambda: NOW, candidate_ceiling=10)
        assert await outbox.offer(candidate(key="k1")) is NotificationEnqueue.TOO_LARGE

    async def test_a_withdrawal_takes_the_entry_carrying_one_record(self) -> None:
        """§3a: an entry the outbox still holds may be withdrawn by the act that
        disposes of it differently, and withdrawing it removes it as an eviction
        does."""
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(candidate(key="k1"))

        assert await outbox.withdraw("no-such-record") is False


def test_the_fakes_clock_guard_raises_the_seams_own_error() -> None:
    """A naive reading is this seam's failure, not ``core``'s raw ``ValueError``.

    ADR-0026 §4's shape: the guard is what catches a producer this store would
    otherwise stamp an unusable instant from, and a caller of the outbox is
    promised the outbox's error.
    """
    from ai_assistant.core.errors import NotificationOutboxError  # noqa: PLC0415 — asserted about

    outbox = FakeNotificationOutbox(now=lambda: datetime(2026, 1, 1, 12, 0))  # noqa: DTZ001 — the naive reading under test

    with pytest.raises(NotificationOutboxError):
        outbox._now()


def test_the_utc_helper_is_used_by_the_default_clock() -> None:
    """The shipped clock reads UTC, so a fake is never accidentally naive."""
    outbox = FakeNotificationOutbox()

    assert outbox._now().tzinfo is UTC


async def test_the_fakes_wait_reports_its_timeout() -> None:
    """A wait that ran out says so, which is what stops a caller spinning.

    The fake used to return at once on the reasoning that a wake is only a hint —
    true, and the reason the *arrival* half is a hint. The timeout half is not: a
    caller that could not tell them apart would re-read, find nothing and ask to
    wait again, forever against the injected fixed clock this tree tests with.
    """
    outbox = FakeNotificationOutbox(now=lambda: NOW)

    assert await outbox.wait_for_arrival(timedelta(milliseconds=20)) is False


async def test_the_fakes_wait_returns_early_on_an_offer() -> None:
    """The discriminating half: an enqueue wakes a parked wait.

    Without it the fake would be a sleep, and a consumer's notification would wait
    out the whole budget instead of arriving when it was produced.
    """
    import asyncio  # noqa: PLC0415 — the scheduling is the subject

    outbox = FakeNotificationOutbox(now=lambda: NOW)

    async def enqueue() -> None:
        await asyncio.sleep(0.01)
        await outbox.offer(candidate(key="k1"))

    woke, _ = await asyncio.gather(outbox.wait_for_arrival(timedelta(seconds=5)), enqueue())

    assert woke is True


async def test_the_fakes_withdrawal_reports_the_stores_answer() -> None:
    """Parity with the durable outbox on the already-dismissed path.

    A lingering entry whose record is no longer actionable must not report that the
    withdrawal ended something. Answering ``True`` there would have a consumer
    tested against this fake observe a different promoted engine contract from the
    one the shipped engine has — which is the one thing a canonical fake may not do.
    """
    records = FakeNotificationStore()
    await records.set_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),)
        )
    )
    subject = candidate(key="k1", expires_at=NOW + timedelta(hours=2))
    ruled = await records.admit(subject, policy=FakeNotificationPolicy())
    assert ruled.notification_id is not None
    outbox = FakeNotificationOutbox(records=records, now=lambda: NOW)
    await outbox.offer(subject)
    # The owner dismisses the record directly, leaving the entry behind.
    assert await records.dismiss(ruled.notification_id) is True

    assert await outbox.withdraw(ruled.notification_id) is False


async def test_the_fakes_withdrawal_reports_a_dismissal_it_performed() -> None:
    """The discriminating half: an actionable record ended here is ``True``."""
    records = FakeNotificationStore()
    await records.set_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),)
        )
    )
    subject = candidate(key="k1", expires_at=NOW + timedelta(hours=2))
    ruled = await records.admit(subject, policy=FakeNotificationPolicy())
    assert ruled.notification_id is not None
    outbox = FakeNotificationOutbox(records=records, now=lambda: NOW)
    await outbox.offer(subject)

    assert await outbox.withdraw(ruled.notification_id) is True


@pytest.mark.parametrize("entries", [0, -1, True])
def test_the_fake_refuses_an_entry_bound_the_contract_does_not_admit(entries: int) -> None:
    """ADR-0131 §5a admits no "off" for this bound, and nor may the fake.

    A fake looser than the contract certifies consumers a real outbox rejects: a
    ``max_entries`` of 0 held entries the durable outbox refuses to construct at
    all, so a consumer could pass here and fail against the shipped hub.
    """
    with pytest.raises(ValueError, match="ADR-0131 §5a"):
        FakeNotificationOutbox(max_entries=entries)


@pytest.mark.parametrize("lease", [timedelta(0), timedelta(seconds=-1)])
def test_the_fake_refuses_a_lease_the_contract_does_not_admit(lease: timedelta) -> None:
    """A zero lease expires every delivery the instant it is taken."""
    with pytest.raises(ValueError, match="ADR-0131 §5a"):
        FakeNotificationOutbox(lease=lease)
