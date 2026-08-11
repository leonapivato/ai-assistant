"""The concrete producer seam: rule in the store, hand off on the way out.

ADR-0130 §3's ``NotificationWriter`` had no implementation in ``src`` until
ADR-0132's producer needed one, and ADR-0131 §3b's live-handoff clause therefore
had no call path to bind (#964). Both land in
:class:`~ai_assistant.orchestration.notifications.NotificationWriteStage`, and
this module is what holds it to them.

Every collaborator is a canonical fake from ``ai_assistant.testing``, so nothing
here imports a subsystem concrete (CLAUDE.md golden rule 1). The one hand-rolled
double is :class:`_BrokenOutbox`, which has to be scripted: "the failure reaches
the producer" is a claim about an exception this seam does not otherwise raise.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import NotificationOutboxError
from ai_assistant.core.types import (
    ClassReach,
    DataTier,
    NotificationCandidate,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
)
from ai_assistant.orchestration import NotificationWriteStage
from ai_assistant.testing import (
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeNotificationStore,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import NotificationEnqueue

#: The store's and the outbox's clock. The candidate below expires after it, so
#: the ruling is perishable and the escalation test is reachable (ADR-0130 §5).
_NOW = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)

_CLASS = "test_class"


class _BrokenOutbox:
    """An outbox whose ``offer`` raises this seam's declared store failure."""

    def __init__(self) -> None:
        self.calls = 0

    async def offer(self, candidate: NotificationCandidate) -> NotificationEnqueue:
        """Refuse custody, loudly (ADR-0131 §3b)."""
        self.calls += 1
        msg = "the outbox is broken"
        raise NotificationOutboxError(msg)


def _candidate(*, key: str = "k-1", expires_at: datetime | None = None) -> NotificationCandidate:
    """One well-formed candidate, perishable by default."""
    return NotificationCandidate(
        candidate_key=key,
        producer="test-producer",
        notification_class=_CLASS,
        summary="something is about to happen",
        noticed_at=_NOW,
        expires_at=expires_at if expires_at is not None else _NOW.replace(hour=10),
        confidence=0.9,
        sensitivity=DataTier.PERSONAL,
    )


async def _interrupting_store() -> FakeNotificationStore:
    """A store whose preferences let the escalation test through (ADR-0130 §6)."""
    store = FakeNotificationStore(now=lambda: _NOW)
    await store.set_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=_CLASS, reach=NotificationReach.INTERRUPT),)
        )
    )
    return store


async def test_the_seam_rules_through_the_store_and_reports_what_it_ruled() -> None:
    """ADR-0130 §3: one call, and the ruling is the store's rather than this seam's.

    §3 requires the duplicate lookup, the cap check, the budget read, the ruling
    and the write to be **one atomic act in the store**, so this stage's whole job
    is to hold the policy and hand it over. A writer that read the state, ruled,
    and then wrote would satisfy every word of §3 except the one that matters —
    and the observable consequence of getting it right is that the disposition
    coming back is the *store's*, carrying the record id it minted.
    """
    store = await _interrupting_store()
    stage = NotificationWriteStage(
        store=store, policy=FakeNotificationPolicy(), outbox=FakeNotificationOutbox()
    )

    ruling = await stage.offer(_candidate())

    assert ruling.kind is NotificationDispositionKind.INTERRUPT
    held = await store.held(limit=10)
    assert [record.id for record in held] == [ruling.notification_id]


async def test_an_actionable_interrupt_reaches_the_outbox_before_the_call_returns() -> None:
    """ADR-0131 §3b's live handoff, which is the primary path and not a repair.

    §3b: "When a ``NotificationWriter`` call returns an actionable ``INTERRUPT``
    disposition, the same call path calls ``NotificationOutbox.offer`` with that
    candidate before it returns to the producer." Without it, "a hub that
    committed a disposition, spent its budget and simply never called ``offer``
    broke no rule here, while a device sat on an outstanding long poll receiving
    nothing" — which is the state §3b found on its forty-ninth round.

    **Asserted through a ``claim``, not through a spy count.** What the clause
    buys is a *deliverable* entry the moment the producer's call returns, and a
    counter would pass for an implementation that offered the wrong candidate.
    """
    store = await _interrupting_store()
    outbox = FakeNotificationOutbox(records=store, now=lambda: _NOW)
    stage = NotificationWriteStage(store=store, policy=FakeNotificationPolicy(), outbox=outbox)
    candidate = _candidate()

    await stage.offer(candidate)

    delivery = await outbox.claim()
    assert delivery is not None
    assert delivery.notification == candidate


async def test_a_ruling_that_is_not_an_interrupt_hands_off_nothing() -> None:
    """A ``HOLD`` is not contact, and §3b's handoff is about contact.

    The default reach is ``hold`` for every class (ADR-0130 §6), so an untuned
    deployment rules ``HOLD`` — and an implementation that enqueued on every
    ruling would deliver, on the first poll, precisely the notifications the user
    has not agreed to be interrupted by. This is the assertion that separates
    "hand off an interruption" from "hand off a record".
    """
    store = FakeNotificationStore(now=lambda: _NOW)
    outbox = FakeNotificationOutbox(records=store, now=lambda: _NOW)
    stage = NotificationWriteStage(store=store, policy=FakeNotificationPolicy(), outbox=outbox)

    ruling = await stage.offer(_candidate())

    assert ruling.kind is NotificationDispositionKind.HOLD
    assert await outbox.claim() is None


async def test_a_dropped_candidate_hands_off_nothing() -> None:
    """A ``DROP`` wrote no durable record, so there is nothing to carry (§8).

    Driven through the ``off`` reach rather than through an expiry, so the drop is
    one a *setting* produced: "never tell me this" reaching the outbox would be the
    loudest possible version of the bug.
    """
    store = FakeNotificationStore(now=lambda: _NOW)
    await store.set_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=_CLASS, reach=NotificationReach.OFF),)
        )
    )
    outbox = FakeNotificationOutbox(records=store, now=lambda: _NOW)
    stage = NotificationWriteStage(store=store, policy=FakeNotificationPolicy(), outbox=outbox)

    ruling = await stage.offer(_candidate())

    assert ruling.kind is NotificationDispositionKind.DROP
    assert ruling.reason is not None
    assert await outbox.claim() is None


async def test_a_deployment_with_no_outbox_still_rules_and_records() -> None:
    """The CLI's case: it serves no poll, so there is nowhere for one to go.

    ``None`` is a composition's *statement* rather than an omission — the argument
    is required — and what it must not do is make the ruling half-work. The record
    is still written, still enumerable, and still dismissible through the surfaces
    ADR-0130 §9 gives the user.
    """
    store = await _interrupting_store()
    stage = NotificationWriteStage(store=store, policy=FakeNotificationPolicy(), outbox=None)

    ruling = await stage.offer(_candidate())

    assert ruling.kind is NotificationDispositionKind.INTERRUPT
    assert len(await store.held(limit=10)) == 1


async def test_a_failed_enqueue_reaches_the_producer_and_leaves_the_record_actionable() -> None:
    """ADR-0131 §3b: no custody transferred, and the failure is not silent.

    "An ``offer`` that raises ``NotificationOutboxError`` leaves the record
    actionable and the notification undelivered. The path may retry it; if it does
    not, the next reconciliation offers it. Neither is silent: the failure reaches
    the producer as §3b's declared error." A seam that swallowed it would report a
    successful pass over a notification nobody will ever receive, and §3b's
    reconciliation would be the only thing that ever noticed.
    """
    store = await _interrupting_store()
    outbox = _BrokenOutbox()
    stage = NotificationWriteStage(store=store, policy=FakeNotificationPolicy(), outbox=outbox)

    with pytest.raises(NotificationOutboxError):
        await stage.offer(_candidate())

    assert outbox.calls == 1
    # The ruling committed before the handoff was attempted, which is what makes
    # the record "still actionable" a fact rather than a hope: reconciliation has
    # something to find.
    held = await store.held(limit=10)
    assert len(held) == 1
    assert held[0].dismissed_at is None


async def test_a_re_offer_of_the_same_key_is_dropped_and_hands_off_nothing() -> None:
    """ADR-0130 §8's duplicate suppression, seen from the seam that spends it.

    "A producer that re-notices the same fact on every tick is behaving as
    designed", and ADR-0132 §5 spends exactly that guarantee: the producer holds no
    durable record of what it has offered before. What must not happen is a second
    outbox entry for the same key on every tick — the reach is ``interrupt`` here,
    so an implementation that handed off before consulting the duplicate answer
    would enqueue one per tick forever.
    """
    store = await _interrupting_store()
    outbox = FakeNotificationOutbox(records=store, now=lambda: _NOW)
    stage = NotificationWriteStage(store=store, policy=FakeNotificationPolicy(), outbox=outbox)

    first = await stage.offer(_candidate(key="same"))
    second = await stage.offer(_candidate(key="same"))

    assert first.kind is NotificationDispositionKind.INTERRUPT
    assert second.kind is NotificationDispositionKind.DROP
    assert await outbox.claim() is not None
    assert await outbox.claim() is None  # and exactly one entry was ever made


async def test_the_reach_the_user_set_is_what_decides_the_handoff() -> None:
    """The seam reads no preference of its own; the store's ruling is the input.

    Raising the class's reach is the user's act (ADR-0130 §6), and the same
    candidate through the same seam must change outcome on the strength of that
    act alone. This is the case that would catch a stage which decided
    "interrupting" from the candidate's own evidence — its confidence, its class,
    its summary — which §4 rules is evidence rather than authority.
    """
    quiet_store = FakeNotificationStore(now=lambda: _NOW)
    loud_store = await _interrupting_store()
    policy = FakeNotificationPolicy()

    quiet = await NotificationWriteStage(store=quiet_store, policy=policy, outbox=None).offer(
        _candidate()
    )
    loud = await NotificationWriteStage(store=loud_store, policy=policy, outbox=None).offer(
        _candidate()
    )

    assert quiet.kind is NotificationDispositionKind.HOLD
    assert loud.kind is NotificationDispositionKind.INTERRUPT
    assert (await quiet_store.preferences()).reach_for(_CLASS) is NotificationReach.HOLD
