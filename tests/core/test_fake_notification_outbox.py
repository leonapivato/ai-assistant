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

from ai_assistant.core.errors import NotificationOutboxError, NotificationStoreError
from ai_assistant.core.types import (
    ClassReach,
    HeldNotification,
    NotificationCandidate,
    NotificationEnqueue,
    NotificationPreferences,
    NotificationReach,
)
from ai_assistant.testing import (
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeNotificationStore,
)
from ai_assistant.testing.notifications import _RECORD_PAGE


def _records() -> FakeNotificationStore:
    """A record store on the fixed clock every case here asserts against.

    **Not the wall clock, and that is a correctness property rather than a style.**
    ADR-0130 §5 admits a candidate only while it is still perishable, so a store left
    on the real clock rules a ``NOW + 2 hours`` expiry to ``DROP``/``EXPIRED`` from
    two hours after ``NOW`` onwards — a suite that passes when it is written and
    fails later against a wall clock nobody touched.
    """
    return FakeNotificationStore(now=lambda: NOW)


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

    async def test_recovery_voids_every_lease(self) -> None:
        """§3: "A hub restart voids every lease."

        "A lease is only meaningful while the connection that took the delivery
        exists, and no connection survives a hub restart — so an entry still leased
        at startup is one whose holder is definitionally gone."
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(candidate(key="k1"))
        first = await outbox.claim()
        assert first is not None

        await outbox.recover_leases()

        second = await outbox.claim()
        assert second is not None
        assert second.delivery_id != first.delivery_id

    async def test_reconciliation_takes_no_lease(self) -> None:
        """Parity with the durable outbox: voiding is ``recover_leases``' step alone.

        Guarded inside the repair it would be guarded per *object*, so a second
        outbox over one store in one live process would strip a lease the first had
        granted — ADR-0131 §3's "one entry, two devices". The caller owns the
        once-ness (``Engine.start``), so a repair from anywhere takes nothing.
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(candidate(key="k1"))
        held = await outbox.claim()
        assert held is not None

        await outbox.reconcile()

        assert await outbox.claim() is None

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
    records = _records()
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
    records = _records()
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


class _DisposingStore(FakeNotificationStore):
    """The canonical store, with a ``held`` that dismisses a record on its way out.

    The reconciliation race as a fixture: the page it returns still names the record,
    and the record is no longer actionable by the time the caller acts on it. A
    subclass rather than a wrapper, so it is the contract-correct fake in every
    respect but the one method under test.
    """

    def __init__(self) -> None:
        """Start disposing of nothing, on the fixed clock the cases assert against."""
        super().__init__(now=lambda: NOW)
        #: The record to dismiss on the next read, disarmed by that read.
        self.dismiss_on_read: str | None = None

    async def held(self, *, limit: int = 50, offset: int = 0) -> list[HeldNotification]:
        """Answer the page, then dismiss the armed record behind the caller's back."""
        page = await super().held(limit=limit, offset=offset)
        if self.dismiss_on_read is not None:
            disposing, self.dismiss_on_read = self.dismiss_on_read, None
            await super().dismiss(disposing)
        return page


async def _ruled(records: FakeNotificationStore) -> tuple[str, NotificationCandidate]:
    """Rule one candidate to ``INTERRUPT``, returning its record id and candidate."""
    await records.set_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),)
        )
    )
    subject = candidate(key="k1", expires_at=NOW + timedelta(hours=2))
    ruled = await records.admit(subject, policy=FakeNotificationPolicy())
    assert ruled.notification_id is not None
    return ruled.notification_id, subject


async def test_the_fakes_reconciliation_does_not_resurrect_a_disposed_record() -> None:
    """Parity with the durable outbox on ADR-0131 §3a's ordering.

    §3b's repair reads the records, releases the lock and offers what is missing; the
    owner can dismiss or delete one of those in the gap, and the withdrawal that
    disposal performs finds no entry to take. An unconditional re-offer then inserts
    one *afterwards*, delivering a notification the owner had already removed. The
    durable outbox re-resolves under its own lock and declines; a fake that
    resurrected it would certify consumers against a contract nothing implements.
    """
    records = _DisposingStore()
    record_id, _ = await _ruled(records)
    outbox = FakeNotificationOutbox(records=records, now=lambda: NOW)
    records.dismiss_on_read = record_id

    await outbox.reconcile()

    assert await outbox.claim() is None


async def test_the_fakes_producer_offer_still_needs_no_record_behind_it() -> None:
    """The discriminating half: only the *repair* declines a recordless offer.

    §3b's "nothing further is owed" covers a caller keeping records of its own — or
    none, which is this fake's own default. Declining there would make the outbox
    unusable by anything but ADR-0130's store.
    """
    outbox = FakeNotificationOutbox(now=lambda: NOW)

    assert await outbox.offer(candidate(key="k1")) is NotificationEnqueue.ENQUEUED
    assert await outbox.claim() is not None


#: The single wide page the fake used to read the whole store with, and treat as a
#: total. Named so the case can point at the records that page cut off.
_OLD_SINGLE_PAGE = 1000

#: Comfortably more records than that, so there are records beyond it to point at.
_PAST_ONE_PAGE = _OLD_SINGLE_PAGE + 100


async def test_the_fakes_sweep_reads_every_record_and_not_one_page_of_them() -> None:
    """Parity with the durable outbox, which pages until a short page.

    Both of the fake's reads asked for ``held(limit=1000, offset=0)`` and treated
    that page as the whole store. It is not one: ``FakeNotificationStore``'s ``cap``
    is caller-configurable, so a consumer holding more silently lost every record
    past the first page — ADR-0131 §3b's reconciliation never offering them, and
    ``_resolve`` answering ``None`` for a candidate whose record was merely further
    down. A canonical fake that truncates where the shipped implementation does not
    certifies consumers against a contract nothing implements.
    """
    records = FakeNotificationStore(now=lambda: NOW, cap=_PAST_ONE_PAGE + 100)
    await records.set_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
            interruption_budget=_PAST_ONE_PAGE * 2,
        )
    )
    for index in range(_PAST_ONE_PAGE):
        ruled = await records.admit(
            candidate(key=f"k{index}", expires_at=NOW + timedelta(hours=2)),
            policy=FakeNotificationPolicy(),
        )
        assert ruled.notification_id is not None
    outbox = FakeNotificationOutbox(
        records=records, now=lambda: NOW, max_entries=_PAST_ONE_PAGE + 100
    )
    # Read the probe out of the store's **own** order rather than assuming the last
    # candidate admitted lands last: ``held`` orders by the admission instant, which
    # this fixed clock makes identical for every record, so the tie-break decides and
    # "the one I added last" is not reliably past the boundary. Taking the first
    # record the old single page would have cut off makes the case exact.
    beyond = await records.held(limit=_RECORD_PAGE, offset=_OLD_SINGLE_PAGE)
    assert beyond, "the store must hold more than the page the fake used to read"
    probe = beyond[0]

    await outbox.reconcile()

    # The sweep reached it: an entry exists under its key, so a fresh offer of the
    # same candidate is the no-op §3 makes it rather than an enqueue.
    assert await outbox.offer(probe.candidate) is NotificationEnqueue.ALREADY_HELD
    # And the resolution reached it too: the entry knows which record it carries,
    # which is the only reason a withdrawal can report that it ended one.
    assert await outbox.withdraw(probe.id) is True


class _FailingStore(FakeNotificationStore):
    """The canonical store with a ``dismiss`` and a ``held`` a case can break."""

    def __init__(self) -> None:
        """Start failing nothing, on the fixed clock the cases assert against."""
        super().__init__(now=lambda: NOW)
        self.refuse_dismiss = False
        self.refuse_held = False

    async def dismiss(self, notification_id: str) -> bool:
        """Refuse when armed, so a post-commit path can be exercised."""
        if self.refuse_dismiss:
            msg = "the notification store is unavailable"
            raise NotificationStoreError(msg)
        return await super().dismiss(notification_id)

    async def held(self, *, limit: int = 50, offset: int = 0) -> list[HeldNotification]:
        """Refuse when armed, so the read path's translation is reachable."""
        if self.refuse_held:
            msg = "the notification store is unavailable"
            raise NotificationStoreError(msg)
        return await super().held(limit=limit, offset=offset)


class TestTheFakeKeepsTheDurableOutboxsInvariants:
    """The parity audit, as tests — one per invariant the durable outbox holds.

    Four consecutive review rounds each found the fake diverging from
    ``SqliteNotificationOutbox`` on a different invariant, which is a fact about how
    the fake was built rather than about any one defect: it inherited the durable
    outbox's hard-won rules by review instead of by construction. These close the
    class. Where a difference is *intended* — the byte bound and §4's delivery-counter
    ceiling, neither of which an in-memory fake can honestly model — it is recorded in
    the class docstring rather than asserted here.
    """

    async def test_a_store_read_failure_is_the_seams_own_error(self) -> None:
        """Both Protocols declare ``NotificationOutboxError`` and nothing else.

        The read reaches every ``offer`` through ``_resolve``, and ``reconcile``
        directly, so an untranslated store fault is the type a consumer catches
        differing from the type the shipped hub raises.
        """
        records = _FailingStore()
        outbox = FakeNotificationOutbox(records=records, now=lambda: NOW)
        records.refuse_held = True

        with pytest.raises(NotificationOutboxError):
            await outbox.offer(candidate(key="k1"))
        with pytest.raises(NotificationOutboxError):
            await outbox.reconcile()

    async def test_a_dismissal_failure_is_the_seams_own_error(self) -> None:
        """The same for the write half, which two of three callers used to leak raw."""
        records = _FailingStore()
        record_id, subject = await _ruled(records)
        outbox = FakeNotificationOutbox(records=records, now=lambda: NOW)
        await outbox.offer(subject)
        held = await outbox.claim()
        assert held is not None
        records.refuse_dismiss = True

        with pytest.raises(NotificationOutboxError):
            await outbox.acknowledge(held.delivery_id)
        with pytest.raises(NotificationOutboxError):
            await outbox.withdraw(record_id)

    async def test_a_failed_acknowledgement_leaves_the_entry_deliverable(self) -> None:
        """§4: a failure restores the entry exactly as it was.

        Marked departing and then left that way would make it selectable by no poll
        and recoverable only by a reconciliation — a notification lost to a transient
        store fault.
        """
        records = _FailingStore()
        _, subject = await _ruled(records)
        outbox = FakeNotificationOutbox(records=records, now=lambda: NOW)
        await outbox.offer(subject)
        held = await outbox.claim()
        assert held is not None
        records.refuse_dismiss = True
        with pytest.raises(NotificationOutboxError):
            await outbox.acknowledge(held.delivery_id)

        records.refuse_dismiss = False

        await outbox.acknowledge(held.delivery_id)
        assert await outbox.offer(subject) is NotificationEnqueue.ENQUEUED

    async def test_custody_transfers_before_an_eviction_can_fail(self) -> None:
        """§4's shape at the other end of an entry's life: the insert commits first.

        A producer told "no custody transferred" would retry and be answered
        ``ALREADY_HELD``, contradicting the error it was just given. So a failed
        eviction is deferred — the victim stays departing, deliverable to nobody —
        and the offer still reports ``ENQUEUED``.
        """
        records = _FailingStore()
        _, old = await _ruled(records)
        outbox = FakeNotificationOutbox(records=records, now=lambda: NOW, max_entries=1)
        assert await outbox.offer(old) is NotificationEnqueue.ENQUEUED
        records.refuse_dismiss = True

        fresh = candidate(key="k2", expires_at=NOW + timedelta(hours=2))
        assert await outbox.offer(fresh) is NotificationEnqueue.ENQUEUED

        # The victim reaches nobody, and the entry that took its place is deliverable.
        delivery = await outbox.claim()
        assert delivery is not None
        assert delivery.notification.candidate_key == "k2"
        assert await outbox.claim() is None

    async def test_an_offer_refuses_while_a_departure_cannot_be_finished(self) -> None:
        """§3b: an offer whose head-of-offer repair fails transfers no custody.

        A failed withdrawal leaves an entry marked departing with its record still
        actionable. An offer under **any** key then meets that departure in the
        store-wide settle, and while the record store is still unavailable it cannot
        be finished. Suppressing that would answer ``ENQUEUED`` over a repair that did
        not happen, and let a consumer pass with state the durable outbox refuses —
        it does not catch the failure either, and the settle runs before anything has
        committed, so nothing is owed to a producer but the declared error.
        """
        records = _FailingStore()
        record_id, subject = await _ruled(records)
        outbox = FakeNotificationOutbox(records=records, now=lambda: NOW)
        await outbox.offer(subject)
        records.refuse_dismiss = True
        with pytest.raises(NotificationOutboxError):
            await outbox.withdraw(record_id)  # leaves the row marked departing

        independent = candidate(key="k2", expires_at=NOW + timedelta(hours=2))
        with pytest.raises(NotificationOutboxError):
            await outbox.offer(independent)

        # No custody transferred: the refused offer left no entry behind, and once the
        # store recovers the same offer is taken and the departure is finished.
        records.refuse_dismiss = False
        assert await outbox.offer(independent) is NotificationEnqueue.ENQUEUED
        swept = await records.get(record_id)
        assert swept is not None
        assert swept.dismissed_at is not None

    async def test_an_offer_settles_departures_under_other_keys_too(self) -> None:
        """The head-of-offer settle is a store-wide sweep, as the durable one is.

        Performed only inside ``reconcile``, departing entries accumulate between
        repairs and keep counting toward ``max_entries`` — so an outbox at its bound
        refuses work it has room for.
        """
        records = _FailingStore()
        record_id, first = await _ruled(records)
        outbox = FakeNotificationOutbox(records=records, now=lambda: NOW, max_entries=2)
        await outbox.offer(first)
        # A failed *withdrawal* is what strands a departure: unlike a failed
        # acknowledgement, it does not restore the mark, so the row stays departing
        # with its record still actionable — §3b's half-done handoff.
        records.refuse_dismiss = True
        with pytest.raises(NotificationOutboxError):
            await outbox.withdraw(record_id)
        records.refuse_dismiss = False

        # An offer under a *different* key clears the departure left under the first.
        second = candidate(key="k2", expires_at=NOW + timedelta(hours=2))
        assert await outbox.offer(second) is NotificationEnqueue.ENQUEUED

        # **Asserted on the record store, not on the next offer's outcome.** The
        # decline-and-retry path reaches `ENQUEUED` for `first` either way, so only
        # the record tells the two apart: the settle dismisses before it removes, so
        # a swept departure leaves its record dismissed here and now.
        swept = await records.get(record_id)
        assert swept is not None
        assert swept.dismissed_at is not None
        assert await outbox.offer(first) is NotificationEnqueue.ENQUEUED


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
