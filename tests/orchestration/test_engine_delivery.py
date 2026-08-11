"""ADR-0131 §4's ordering and refusals on the engine's own delivery surface.

What is here is the half the transport cannot decide: the closed budget range and
both of its ends, the ordering that puts validation before every effect, the
refusal when no outbox is composed, and the reconciliation that runs at
:meth:`~ai_assistant.orchestration.Engine.start` rather than at the first poll.
The connection rules are ``tests/wire/test_server_delivery.py``'s, and the
outbox's own transitions are tested where each implementation lives.

The engine is built from the same canonical fakes ``test_engine.py``'s harness
uses, so nothing here imports a subsystem (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from test_engine import AT, Harness, _grant_operations

from ai_assistant.core.errors import (
    ConfigurationError,
    NotificationBudgetError,
    NotificationOutboxError,
)
from ai_assistant.core.types import (
    ClassReach,
    DataTier,
    NotificationCandidate,
    NotificationEnqueue,
    NotificationPreferences,
    NotificationReach,
)
from ai_assistant.orchestration.engine import Engine
from ai_assistant.testing import (
    FakeAssistantEngine,
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeNotificationStore,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import NotificationDelivery
    from ai_assistant.orchestration.delivery import DeliveryOutbox

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _records() -> FakeNotificationStore:
    """A record store on the fixed clock every case here asserts against.

    **Not the wall clock, and that is a correctness property rather than a style.**
    ADR-0130 §5 admits a candidate only while it is still perishable, so a store left
    on the real clock rules a ``NOW + 2 hours`` expiry to ``DROP``/``EXPIRED`` from
    two hours after ``NOW`` onwards — a suite that passes when it is written and
    fails later against a wall clock nobody touched.
    """
    return FakeNotificationStore(now=lambda: NOW)


def _candidate(key: str = "k1") -> NotificationCandidate:
    """One candidate, with everything a case is not about held constant."""
    return NotificationCandidate(
        candidate_key=key,
        producer="a-producer",
        notification_class="calendar",
        summary="something the user did not ask for",
        noticed_at=NOW,
        confidence=0.5,
        sensitivity=DataTier.PERSONAL,
    )


def _wired(harness: Harness, outbox: DeliveryOutbox | None = None, **kwargs: object) -> Engine:
    """A façade over ``harness``'s durable state, holding a delivery outbox."""
    return Engine(
        grant_operations=_grant_operations(),
        loop=harness.engine._loop,
        runner=harness.engine._runner,
        plans=harness.plans,
        trail=harness.trail,
        memory=harness.memory,
        deferrals=harness.deferrals,
        traces=harness.traces,
        trace_sink=harness.trace_sink,
        trace_retention=harness.trace_retention,
        conversations=harness.conversations,
        observation=harness.observation,
        questions=harness.questions,
        notification_outbox=outbox,
        now=lambda: AT,
        **kwargs,  # type: ignore[arg-type]
    )


class RecordingOutbox:
    """A :class:`DeliveryOutbox` that records the order it was driven in.

    The subject of the ordering cases, because ADR-0131 §4's rule is about *which
    call happened first* rather than about either call's answer — an assertion on
    the outcome would pass whichever way round they ran.
    """

    def __init__(self) -> None:
        """Start with nothing to give and nothing recorded."""
        self.calls: list[str] = []
        self.reconciled = 0
        self.recovered = 0
        self.withdrew = True
        self.withdrawal_fails = False

    async def offer(self, candidate: NotificationCandidate) -> NotificationEnqueue:
        """Record that a candidate was handed off (ADR-0131 §3b)."""
        self.calls.append(f"offer:{candidate.candidate_key}")
        return NotificationEnqueue.ENQUEUED

    async def claim(self) -> NotificationDelivery | None:
        """Answer that nothing is available."""
        self.calls.append("claim")
        return None

    async def acknowledge(self, delivery_id: str) -> None:
        """Record that an acknowledgement reached the outbox."""
        self.calls.append(f"acknowledge:{delivery_id}")

    async def recover_leases(self) -> None:
        """Record that the inherited leases were voided (ADR-0131 §3).

        **It suspends**, for :class:`FakeNotificationOutbox`'s reason: a real
        recovery reaches a store and yields, and a guard that is only correct while
        nothing interleaves is not a guard. Without the yield the concurrency case
        below would pass against an unlocked check-and-set.
        """
        await asyncio.sleep(0)
        self.calls.append("recover_leases")
        self.recovered += 1

    async def reconcile(self) -> None:
        """Record that the startup repair ran."""
        self.calls.append("reconcile")
        self.reconciled += 1

    async def withdraw(self, record_id: str) -> bool:
        """Record that a withdrawal reached the outbox (ADR-0131 §3a)."""
        self.calls.append(f"withdraw:{record_id}")
        if self.withdrawal_fails:
            msg = "the outbox could not begin the withdrawal"
            raise NotificationOutboxError(msg)
        return self.withdrew

    async def wait_for_arrival(
        self,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's own poll budget (ADR-0029 §4)
    ) -> bool:
        """Report the timeout, so a budget costs a case nothing to exercise.

        Returning ``False`` is the conforming spelling of "the wait ran out", and
        it is what a caller ends its poll on — a fake that reported an arrival it
        had not waited for would spin the caller instead.
        """
        del timeout
        self.calls.append("wait")
        return False


class TestTheBudgetRange:
    """ADR-0131 §4: honoured over the closed range from zero to the ceiling."""

    @pytest.mark.parametrize("budget", [timedelta(seconds=-1), timedelta(days=-1)])
    async def test_a_negative_budget_is_refused(self, budget: timedelta) -> None:
        """§4: ``timedelta`` admits negatives and nothing else would refuse one.

        "One implementation would return an empty result while another handed it to
        a timeout primitive and raised something undeclared — no common conforming
        behaviour", which is the fifteenth round's finding.
        """
        engine = FakeAssistantEngine()

        with pytest.raises(NotificationBudgetError):
            await engine.next_notification(budget=budget)

    async def test_a_budget_above_the_ceiling_is_refused_not_clamped(self) -> None:
        """§4: "The hub does not silently clamp it in either direction."

        Clamping is accepting-and-ignoring in a second costume: a client whose
        ninety-minute budget were honoured as ninety seconds has been told, by
        acceptance, that its budget was accepted.
        """
        engine = FakeAssistantEngine()

        with pytest.raises(NotificationBudgetError):
            await engine.next_notification(budget=timedelta(hours=2))

    async def test_zero_is_an_immediate_poll_and_not_an_error(self) -> None:
        """§4: "the one out-of-range value that means something".

        "A device that has just been opened by the owner wants to know what is
        waiting *now*", and refusing zero would push every client into faking it
        with a one-second budget — the same behaviour with worse latency and an
        arbitrary constant in it.
        """
        engine = FakeAssistantEngine()

        assert await engine.next_notification(budget=timedelta(0)) is None

    async def test_the_ceiling_itself_is_inside_the_range(self) -> None:
        """§4: the range is *closed*, so the ceiling is honoured rather than refused."""
        engine = FakeAssistantEngine()

        assert await engine.next_notification(budget=engine.max_notification_budget) is None

    async def test_the_concrete_engine_refuses_the_same_range(self) -> None:
        """The refusal is the *engine's* and not the fake's, so both are held to it."""
        engine = _wired(Harness(), FakeNotificationOutbox())

        with pytest.raises(NotificationBudgetError, match="ADR-0131 §4"):
            await engine.next_notification(budget=timedelta(seconds=-1))

    async def test_a_non_positive_ceiling_is_refused_at_construction(self) -> None:
        """§5a: "'off' is not an available value" for any of the five figures."""
        with pytest.raises(ConfigurationError, match="max_notification_budget"):
            _wired(Harness(), FakeNotificationOutbox(), max_notification_budget=timedelta(0))


class TestValidationPrecedesEveryEffect:
    """§4: "a refused request retires nothing, leases nothing and mints nothing"."""

    async def test_a_refused_budget_does_not_apply_the_acknowledgement(self) -> None:
        """§4, the nineteenth round's finding.

        "A device holding delivery ``D`` can send
        ``next_notification(acknowledging=D, budget=timedelta(seconds=-1))``.
        Without an ordering rule, one implementation acknowledges and then refuses —
        reporting a failed request while having permanently retired ``D``, so the
        device's retry with a valid budget finds the notification gone." Two
        conforming hubs, one lost notification.
        """
        outbox = FakeNotificationOutbox()
        await outbox.offer(_candidate())
        held = await outbox.claim()
        assert held is not None
        engine = _wired(Harness(), outbox)

        with pytest.raises(NotificationBudgetError):
            await engine.next_notification(
                acknowledging=held.delivery_id, budget=timedelta(seconds=-1)
            )

        # Still the entry's current outstanding delivery, so the device's retry
        # with a valid budget still retires it.
        await outbox.acknowledge(held.delivery_id)
        assert await outbox.claim() is None

    async def test_a_blank_acknowledgement_is_refused(self) -> None:
        """A malformed argument "of any kind, not only an out-of-range duration"."""
        engine = _wired(Harness(), FakeNotificationOutbox())

        with pytest.raises(ValueError, match="acknowledging"):
            await engine.next_notification(acknowledging="   ", budget=timedelta(0))


class TestThePollLoop:
    """The acknowledge-then-select order, and what the budget buys."""

    async def test_the_acknowledgement_precedes_the_selection(self) -> None:
        """§4: "**validate, then acknowledge, then select**"."""
        outbox = RecordingOutbox()
        engine = _wired(Harness(), outbox)

        await engine.next_notification(acknowledging="1.abc", budget=timedelta(0))

        assert outbox.calls[:2] == ["acknowledge:1.abc", "claim"]

    async def test_a_zero_budget_reads_once_and_never_waits(self) -> None:
        """§4: an immediate poll is "the same request with the waiting removed"."""
        outbox = RecordingOutbox()
        engine = _wired(Harness(), outbox)

        await engine.next_notification(budget=timedelta(0))

        assert outbox.calls == ["claim"]

    async def test_an_available_entry_answers_without_waiting(self) -> None:
        """A poll with something waiting returns at once, whatever its budget."""
        outbox = FakeNotificationOutbox()
        await outbox.offer(_candidate())
        engine = _wired(Harness(), outbox)

        delivery = await engine.next_notification(budget=timedelta(seconds=30))

        assert delivery is not None
        assert delivery.notification.candidate_key == "k1"

    async def test_a_leased_entry_is_not_handed_to_a_second_poll(self) -> None:
        """§3, through the engine: the lease is what makes "one at a time" true."""
        outbox = FakeNotificationOutbox()
        await outbox.offer(_candidate())
        engine = _wired(Harness(), outbox)

        first = await engine.next_notification(budget=timedelta(0))
        second = await engine.next_notification(budget=timedelta(0))

        assert first is not None
        assert second is None


class TestTheStartupReconciliation:
    """§3b: "running to completion before it serves any poll"."""

    async def test_start_runs_the_reconciliation(self) -> None:
        """The hub calls ``start`` at step 4 and accepts at step 6, so "before any
        poll" is a fact about the listener rather than a promise a constructor
        makes."""
        outbox = RecordingOutbox()
        engine = _wired(Harness(), outbox)

        await engine.start()

        assert outbox.reconciled == 1

    async def test_start_without_an_outbox_is_unchanged(self) -> None:
        """The CLI's in-process engine serves no poll, so it has nothing to repair."""
        engine = _wired(Harness())

        await engine.start()  # must not raise

    async def test_start_recovers_the_inherited_leases_before_it_reconciles(self) -> None:
        """§3's voiding is the engine's step, and it precedes the repair.

        Before the reconciliation because an entry whose inherited lease is still
        standing is not available, so a repair running first would read the outbox in
        a state the recovery is about to change.
        """
        outbox = RecordingOutbox()
        engine = _wired(Harness(), outbox)

        await engine.start()

        assert outbox.calls == ["recover_leases", "reconcile"]

    async def test_a_second_start_recovers_no_lease_a_second_time(self) -> None:
        """§3 authorises voiding for a *restart*, and a second ``start`` is not one.

        "An entry still leased at startup is one whose holder is definitionally gone"
        is true of a lease the previous process granted and false of one this process
        granted a moment ago. ``start`` promises it is safe to call more than once, so
        an unguarded recovery would take a live lease and put one entry in two
        devices' hands. The repair itself stays repeatable.
        """
        outbox = RecordingOutbox()
        engine = _wired(Harness(), outbox)

        await engine.start()
        await engine.start()

        assert outbox.recovered == 1
        assert outbox.reconciled == 2

    async def test_two_overlapping_starts_recover_once_between_them(self) -> None:
        """A bare flag is not a guard across an ``await`` (round 10).

        Both calls read the flag as ``False``; the first recovers and returns, a poll
        leases an entry, and the second resumes its already-started recovery and
        voids that live lease — one entry claimable by a second device, reached
        *through* the guard meant to prevent it. ``start`` is public and documents
        only that it is safe to call more than once, so nothing in this class
        excludes the overlap; the hub's step 4/step 6 ordering is a fact about
        ``service/hub.py`` and not a property callers of this method inherit.
        """
        outbox = RecordingOutbox()
        engine = _wired(Harness(), outbox)

        await asyncio.gather(engine.start(), engine.start())

        assert outbox.recovered == 1


class TestAnUnwiredOutboxRefusesLegibly:
    """A deployment that composed none delivers nothing, and says so."""

    async def test_a_poll_with_no_outbox_is_a_configuration_error(self) -> None:
        """ "No outbox is composed" and "nothing is waiting" are different facts.

        The shape ``notifications`` already takes when no notification store is
        wired: an empty answer would tell a device the outbox is empty when in
        truth the hub cannot deliver at all.
        """
        engine = _wired(Harness())

        with pytest.raises(ConfigurationError, match="no notification outbox is wired"):
            await engine.next_notification(budget=timedelta(0))

    async def test_the_refusal_precedes_no_state_change(self) -> None:
        """The budget is still judged first, so the two refusals cannot disagree."""
        engine = _wired(Harness())

        with pytest.raises(NotificationBudgetError):
            await engine.next_notification(budget=timedelta(seconds=-1))


class TestThePollTerminates:
    """The wait's timeout is what ends a poll, not the clock alone."""

    async def test_an_empty_poll_with_a_budget_ends_on_the_waits_timeout(self) -> None:
        """A wait that ran out ends the poll rather than sending it round again.

        **Trusting the clock alone is what made this a spin.** The engine's
        deadline is read from an injected clock, and the tree's dominant test idiom
        freezes one — so a loop that re-read, found nothing and asked to wait again
        would never reach its deadline at all. The timeout is the one answer a wait
        can be trusted for, so it is what ends the poll.
        """
        outbox = RecordingOutbox()
        engine = _wired(Harness(), outbox)

        assert await engine.next_notification(budget=timedelta(seconds=30)) is None

        assert outbox.calls == ["claim", "wait"]

    async def test_an_empty_poll_against_the_canonical_fake_ends(self) -> None:
        """The same, through the fake a consumer actually holds.

        Bounded by the budget rather than by the clock, so it terminates on a
        frozen one — which is what a canonical fake owes its consumers.
        """
        engine = _wired(Harness(), FakeNotificationOutbox(now=lambda: NOW))

        assert await engine.next_notification(budget=timedelta(milliseconds=20)) is None

    async def test_an_arrival_between_the_claim_and_the_wait_is_not_lost(self) -> None:
        """The wake is armed by the claim that found nothing, not by the wait.

        An arrival landing between a poll's empty ``claim`` and its call to
        ``wait_for_arrival`` used to be erased: the event was already set, the wait
        cleared it, and the poll slept out its whole budget with an entry available
        the whole time — answering ``None`` while the hub had something, which is
        the one thing ADR-0131 §1 says a poll must not do.
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        engine = _wired(Harness(), outbox)
        # The claim that finds nothing is what arms the wake, so an offer taken
        # before any wait begins is still visible to the next one.
        assert await outbox.claim() is None
        await outbox.offer(_candidate())

        delivery = await engine.next_notification(budget=timedelta(seconds=5))

        assert delivery is not None

    async def test_an_arrival_during_the_wait_is_delivered(self) -> None:
        """The discriminating half: a wake sends the poll back for the re-read.

        A loop that ended on *every* wait would answer nothing to a notification
        that arrived one millisecond into a five-minute budget.
        """
        import asyncio  # noqa: PLC0415 — the scheduling is the subject

        outbox = FakeNotificationOutbox(now=lambda: NOW)
        engine = _wired(Harness(), outbox)

        async def enqueue() -> None:
            await asyncio.sleep(0.01)
            await outbox.offer(_candidate())

        delivery, _ = await asyncio.gather(
            engine.next_notification(budget=timedelta(seconds=5)), enqueue()
        )

        assert delivery is not None
        assert delivery.notification.candidate_key == "k1"


class TestForgettingWithdrawsBeforeItDeletes:
    """ADR-0131 §3a: the delete right reaches the outbox, and the order is forced."""

    async def test_forget_notification_withdraws_the_entry_first(self) -> None:
        """§3a: "No lane may delete a record whose entry it has not already
        withdrawn."

        Deleting first would leave an entry whose record is gone — not departing,
        not expired, undetectably stale — and the next poll would deliver a
        notification about something the user had deleted.
        """
        outbox = RecordingOutbox()
        harness = Harness()
        store = _records()
        engine = _wired(
            harness, outbox, notifications=store, notification_policy=FakeNotificationPolicy()
        )

        await engine.forget_notification("a-record")

        assert outbox.calls == ["withdraw:a-record"]

    async def test_a_forgotten_notification_is_no_longer_delivered(self) -> None:
        """The end-to-end property, through a real outbox rather than a recorder.

        This is the case the ordering exists for: an entry already enqueued for an
        `INTERRUPT` record, deleted by the user, and then not delivered.
        """
        store = _records()
        await store.set_preferences(
            NotificationPreferences(
                reaches=(
                    ClassReach(notification_class="calendar", reach=NotificationReach.INTERRUPT),
                )
            )
        )
        subject = _candidate()
        ruled = await store.admit(
            subject.model_copy(update={"expires_at": NOW + timedelta(hours=2)}),
            policy=FakeNotificationPolicy(),
        )
        assert ruled.notification_id is not None
        outbox = FakeNotificationOutbox(records=store, now=lambda: NOW)
        await outbox.offer(subject.model_copy(update={"expires_at": NOW + timedelta(hours=2)}))
        engine = _wired(
            Harness(), outbox, notifications=store, notification_policy=FakeNotificationPolicy()
        )

        assert await engine.forget_notification(ruled.notification_id) is True

        assert await engine.next_notification(budget=timedelta(0)) is None

    async def test_dismiss_notification_withdraws_the_entry(self) -> None:
        """ADR-0131 §3: the owner's dismissal reaches the outbox, and must.

        §3 makes an entry departing when its record "has ceased to be actionable",
        and names the two causes the seam can decide locally — it gave the entry up,
        or the candidate expired. An owner's dismissal is neither, which is why §3
        rules that route "arrives as §3a's withdrawal — **the disposing act calls
        the seam** rather than the seam polling for it".
        """
        store = _records()
        await store.set_preferences(
            NotificationPreferences(
                reaches=(
                    ClassReach(notification_class="calendar", reach=NotificationReach.INTERRUPT),
                )
            )
        )
        subject = _candidate().model_copy(update={"expires_at": NOW + timedelta(hours=2)})
        ruled = await store.admit(subject, policy=FakeNotificationPolicy())
        assert ruled.notification_id is not None
        outbox = FakeNotificationOutbox(records=store, now=lambda: NOW)
        await outbox.offer(subject)
        engine = _wired(
            Harness(), outbox, notifications=store, notification_policy=FakeNotificationPolicy()
        )

        assert await engine.dismiss_notification(ruled.notification_id) is True

        assert await engine.next_notification(budget=timedelta(0)) is None

    async def test_dismissing_without_an_outbox_still_dismisses(self) -> None:
        """The CLI's engine serves no poll, so it has no entry to withdraw."""
        store = _records()
        engine = _wired(
            Harness(), None, notifications=store, notification_policy=FakeNotificationPolicy()
        )

        assert await engine.dismiss_notification("nothing") is False

    async def test_forgetting_without_an_outbox_still_deletes(self) -> None:
        """The CLI's engine serves no poll, so it has no entry to withdraw."""
        store = _records()
        engine = _wired(
            Harness(), None, notifications=store, notification_policy=FakeNotificationPolicy()
        )

        assert await engine.forget_notification("nothing") is False


class TestReconsiderationHandsOffAtOnce:
    """ADR-0131 §3b: the live handoff is the primary path, on this path too."""

    async def test_a_reconsidered_interrupt_reaches_the_outbox(self) -> None:
        """§3b names this call site: "It is also the reconsideration path's answer
        without a second clause."

        Without it the notification the user's own setting change made actionable
        waits for a restart — which is exactly what §3b forbids reconciliation from
        being, "a repair that is also the primary path being a design where the
        ordinary case waits on a restart".
        """
        store = _records()
        subject = _candidate().model_copy(update={"expires_at": NOW + timedelta(hours=2)})
        ruled = await store.admit(subject, policy=FakeNotificationPolicy())
        assert ruled.kind is not None
        outbox = RecordingOutbox()
        engine = _wired(
            Harness(), outbox, notifications=store, notification_policy=FakeNotificationPolicy()
        )
        # Raising the class is the act that makes the held record due and
        # re-rules it to INTERRUPT.
        await engine.set_notification_preferences(
            NotificationPreferences(
                reaches=(
                    ClassReach(notification_class="calendar", reach=NotificationReach.INTERRUPT),
                )
            )
        )

        assert await engine.reconsider_notifications() >= 1

        assert f"offer:{subject.candidate_key}" in outbox.calls

    async def test_a_reconsideration_that_still_holds_offers_nothing(self) -> None:
        """The discriminating half: only an ``INTERRUPT`` is handed off.

        A record re-ruled and still held has earned no contact, and offering it
        would put a notification in the outbox that ADR-0130 §5 never ruled
        deliverable.
        """
        store = _records()
        subject = _candidate().model_copy(update={"expires_at": NOW + timedelta(hours=2)})
        await store.admit(subject, policy=FakeNotificationPolicy())
        outbox = RecordingOutbox()
        engine = _wired(
            Harness(), outbox, notifications=store, notification_policy=FakeNotificationPolicy()
        )

        await engine.reconsider_notifications()

        assert not [call for call in outbox.calls if call.startswith("offer:")]


class TestADisposalWithdrawsBeforeItCommits:
    """ADR-0131 §3, §3a: the ordering, and what each failure leaves behind."""

    async def test_dismissal_withdraws_before_the_record_is_dismissed(self) -> None:
        """The withdrawal performs the dismissal, so nothing can land between them.

        Dismissing first and withdrawing afterwards committed the record's
        dismissal and only then reached the outbox — so a withdrawal that failed
        left a non-actionable record beside an unmarked, still selectable entry,
        and the next poll delivered a notification the owner had dismissed.
        """
        outbox = RecordingOutbox()
        store = _records()
        engine = _wired(
            Harness(), outbox, notifications=store, notification_policy=FakeNotificationPolicy()
        )

        assert await engine.dismiss_notification("a-record") is True

        assert outbox.calls == ["withdraw:a-record"]

    async def test_a_failing_withdrawal_dismisses_nothing(self) -> None:
        """§3a: the record is not reported dismissed when the outbox refused.

        The engine declares ``NotificationOutboxError`` on this method for exactly
        this path (ADR-0085 §9), and the store is never asked — so a retry is safe
        and nothing is half-done.
        """
        outbox = RecordingOutbox()
        outbox.withdrawal_fails = True
        store = _records()
        engine = _wired(
            Harness(), outbox, notifications=store, notification_policy=FakeNotificationPolicy()
        )

        with pytest.raises(NotificationOutboxError):
            await engine.dismiss_notification("a-record")

    async def test_a_record_with_no_entry_falls_through_to_the_store(self) -> None:
        """The ordinary case: never offered, so there is nothing to withdraw."""
        outbox = RecordingOutbox()
        outbox.withdrew = False
        store = _records()
        engine = _wired(
            Harness(), outbox, notifications=store, notification_policy=FakeNotificationPolicy()
        )

        assert await engine.dismiss_notification("never-offered") is False

        assert outbox.calls == ["withdraw:never-offered"]

    async def test_a_failing_withdrawal_destroys_nothing(self) -> None:
        """§3a: "No lane may delete a record whose entry it has not already
        withdrawn." """
        outbox = RecordingOutbox()
        outbox.withdrawal_fails = True
        store = _records()
        engine = _wired(
            Harness(), outbox, notifications=store, notification_policy=FakeNotificationPolicy()
        )

        with pytest.raises(NotificationOutboxError):
            await engine.forget_notification("a-record")


class TestTheFakeEngineDisposesLikeTheRealOne:
    """The canonical fake may not deliver what it has dismissed or deleted."""

    async def test_the_fake_does_not_deliver_a_dismissed_notification(self) -> None:
        """A fake that updated only the record store would certify consumers
        against a contract the shipped engine does not have."""
        engine = FakeAssistantEngine()
        # **Real-clock-relative, because this engine's notification surface takes no
        # injected clock** (#970). A fixed ``NOW + 2 hours`` is a fuse: ADR-0130 §5
        # admits a candidate only while it is perishable, so the case passes when it
        # is written and rules ``DROP``/``EXPIRED`` two hours later, on a wall clock
        # nobody touched. Every other case here injects ``NOW`` instead.
        subject = _candidate().model_copy(
            update={"expires_at": datetime.now(UTC) + timedelta(hours=2)}
        )
        ruled = await engine.notification_store.admit(subject, policy=FakeNotificationPolicy())
        assert ruled.notification_id is not None
        await engine.notification_outbox.offer(subject)

        await engine.dismiss_notification(ruled.notification_id)

        assert await engine.next_notification(budget=timedelta(0)) is None

    async def test_the_fake_does_not_deliver_a_forgotten_notification(self) -> None:
        """The same for the delete right (ADR-0004 §6, ADR-0131 §3a)."""
        engine = FakeAssistantEngine()
        # **Real-clock-relative, because this engine's notification surface takes no
        # injected clock** (#970). A fixed ``NOW + 2 hours`` is a fuse: ADR-0130 §5
        # admits a candidate only while it is perishable, so the case passes when it
        # is written and rules ``DROP``/``EXPIRED`` two hours later, on a wall clock
        # nobody touched. Every other case here injects ``NOW`` instead.
        subject = _candidate().model_copy(
            update={"expires_at": datetime.now(UTC) + timedelta(hours=2)}
        )
        ruled = await engine.notification_store.admit(subject, policy=FakeNotificationPolicy())
        assert ruled.notification_id is not None
        await engine.notification_outbox.offer(subject)

        await engine.forget_notification(ruled.notification_id)

        assert await engine.next_notification(budget=timedelta(0)) is None
