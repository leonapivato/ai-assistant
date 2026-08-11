"""The shared conformance suite for ``NotificationOutbox`` (ADR-0131 §3b).

Every implementation of :class:`~ai_assistant.core.protocols.NotificationOutbox`
must pass this suite (``CONTRIBUTING.md`` -> "Protocol conformance suites"). A
concrete test subclasses it and supplies the fixtures.

**§3b names what this must assert and the naming is normative there**: "The
conformance suite of §3b's triad branches on these exact members, so a second
implementation is held to them rather than to a description." That is the reason
the four cases below compare against
:class:`~ai_assistant.core.types.NotificationEnqueue` members by identity — a
suite that asserted "an offer of a held candidate does nothing" would let one
implementation return ``ALREADY_HELD`` and another ``ENQUEUED``, both looking
correct and neither interoperable with a producer that branches.

**What is deliberately *not* asserted here, and why the line falls where it
does.** ADR-0131 §3b puts one method on this Protocol, ``offer``, so this suite
covers the enqueue and nothing else. The lease, the selection, the acknowledgement
and the reconciliation are the engine's transitions and reach a caller through
``orchestration``'s own :class:`~ai_assistant.orchestration.delivery.DeliveryOutbox`
rather than through ``core`` — the ADR declares no Protocol for them — so they are
held by each implementation's own tests instead. That gap is real and is recorded
in the PR that landed it rather than papered over: promoting them is a decision for
the ADR that next touches this seam.

**The byte bound is not asserted here either.** An in-memory implementation
persists nothing, so it has no honest byte cost to count, and a suite asserting one
would hold every implementation to a durable store's arithmetic. ADR-0131 §3's
"everything the outbox persists for it, defined by that property and not by a list"
is checkable only against something that persists, so it is
``tests/memory/test_sqlite_notification_outbox.py``'s.

Named ``*_contract`` (not ``test_*``) so pytest collects these only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from notification_contract import NOW, candidate

from ai_assistant.core.types import NotificationEnqueue

if TYPE_CHECKING:
    from ai_assistant.core.protocols import NotificationOutbox

#: Re-exported so a binding can build its subject's clock from the same instant
#: this suite judges at, without importing two modules to do it.
__all__ = ["NOW", "NotificationOutboxContract"]


class NotificationOutboxContract(ABC):
    """What every ``NotificationOutbox`` must do at the enqueue (ADR-0131 §3, §3b)."""

    @pytest.fixture
    @abstractmethod
    def outbox(self) -> NotificationOutbox:
        """The subject, empty, on a clock nothing moves."""

    # --- §3: the four outcomes, by their exact members ---------------------

    async def test_a_first_offer_is_enqueued(self, outbox: NotificationOutbox) -> None:
        """§3: the ordinary case commits an entry and takes custody of it.

        Custody transferring *at* that commit "and not before" is what leaves a
        producer able to act on a failure, so the outcome has to be observable
        rather than implied.
        """
        assert await outbox.offer(candidate(key="k1")) is NotificationEnqueue.ENQUEUED

    async def test_re_offering_an_identical_candidate_is_already_held(
        self, outbox: NotificationOutbox
    ) -> None:
        """§3: an identical candidate under a held key makes no second entry.

        **The case this exists for is a commit the caller never learned the outcome
        of.** The hub can commit an entry and die before the call returns; the
        producer, restarting, offers the same candidate again, and the key makes
        that retry a no-op rather than a second telling. §3b's reconciliation is the
        same mechanism reached from the other side.
        """
        first = candidate(key="k1")
        assert await outbox.offer(first) is NotificationEnqueue.ENQUEUED

        assert await outbox.offer(first) is NotificationEnqueue.ALREADY_HELD

    async def test_a_differing_candidate_under_a_held_key_is_a_collision(
        self, outbox: NotificationOutbox
    ) -> None:
        """§3: matching on the key alone would turn a producer's bug into a loss.

        That is the finding this refusal exists for, arriving from the other side
        of deduplication: "a candidate B enqueued under a key A already holds would
        receive what looks like a successful enqueue and never be told". Comparing
        the candidate is what makes the no-op a *retry*, and refusing the collision
        is what makes the difference reach the producer instead of the floor.
        """
        assert await outbox.offer(candidate(key="k1")) is NotificationEnqueue.ENQUEUED

        collision = candidate(key="k1", confidence=0.9)
        assert await outbox.offer(collision) is NotificationEnqueue.KEY_COLLISION

    async def test_the_held_entry_survives_a_collision_unreplaced(
        self, outbox: NotificationOutbox
    ) -> None:
        """§3: "The held entry is not replaced and the offered candidate is not
        enqueued under another key."

        Checked by re-offering the *original*, which must still read as held: an
        implementation that had replaced it would answer ``KEY_COLLISION`` here,
        and one that had enqueued the offered candidate under some other key would
        answer ``ENQUEUED``.
        """
        original = candidate(key="k1")
        await outbox.offer(original)
        await outbox.offer(candidate(key="k1", confidence=0.9))

        assert await outbox.offer(original) is NotificationEnqueue.ALREADY_HELD

    async def test_two_keys_are_two_entries(self, outbox: NotificationOutbox) -> None:
        """§3: deduplication is per key and never across the outbox."""
        assert await outbox.offer(candidate(key="k1")) is NotificationEnqueue.ENQUEUED

        assert await outbox.offer(candidate(key="k2")) is NotificationEnqueue.ENQUEUED

    # --- §3: departing entries participate in nothing but their removal ----

    async def test_an_expired_entrys_key_does_not_suppress_a_new_offer(
        self, outbox: NotificationOutbox
    ) -> None:
        """§3: a departing entry "does not match an offer's key under either clause".

        The forty-third round's finding, from the expiry side: a candidate enqueued
        while actionable and never polled before its expiry was never dismissed, so
        a dismissal-only reading of *departing* would leave it matching — and the
        re-noticed fact would be told "already held" while the entry it matched was
        on its way out. Making the expiry a departure cause closes it at the only
        point where both facts are visible.
        """
        stale = candidate(
            key="k1", noticed_at=NOW - timedelta(hours=2), expires_at=NOW - timedelta(hours=1)
        )
        assert await outbox.offer(stale) is NotificationEnqueue.ENQUEUED

        fresh = candidate(key="k1", expires_at=NOW + timedelta(hours=1))
        assert await outbox.offer(fresh) is NotificationEnqueue.ENQUEUED

    async def test_an_expired_entry_does_not_make_a_differing_offer_a_collision(
        self, outbox: NotificationOutbox
    ) -> None:
        """§3: the same rule read from the collision arm rather than the match arm.

        Stated as its own case because the rule is a statement about the *state* —
        "a departing entry participates in no transition except its own removal" —
        and ADR-0131 records that stating it over the cases it was noticed in
        lasted exactly one round each time.
        """
        await outbox.offer(
            candidate(
                key="k1", noticed_at=NOW - timedelta(hours=2), expires_at=NOW - timedelta(hours=1)
            )
        )

        differing = candidate(key="k1", confidence=0.9, expires_at=NOW + timedelta(hours=1))
        assert await outbox.offer(differing) is NotificationEnqueue.ENQUEUED

    # --- §3, §4: the ceilings are refusals and never evictions -------------

    async def test_an_unexpired_candidate_is_not_treated_as_departing(
        self, outbox: NotificationOutbox
    ) -> None:
        """§3: the expiry boundary is *at* the instant, not before it.

        Half-open in the direction ADR-0130 §5 fixes, so an entry whose expiry is
        still ahead is an ordinary held entry — which is what makes the previous two
        cases about expiry rather than about any candidate carrying one.
        """
        live = candidate(key="k1", expires_at=NOW + timedelta(days=1))
        assert await outbox.offer(live) is NotificationEnqueue.ENQUEUED

        assert await outbox.offer(live) is NotificationEnqueue.ALREADY_HELD
