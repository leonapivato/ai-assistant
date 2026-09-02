"""The canonical notification store reads the whole population under a key (#1814).

:class:`~ai_assistant.testing.FakeNotificationStore` passes the shared
``NotificationStore`` suite in ``tests/core/test_fake_notifications.py``, and that
suite holds it to ADR-0130 §9's list as ADR-0215 §7 revises it. What it cannot hold
it to is ADR-0215 §2's population clause — "the lookup reads **every** record the
store retains under the offered key, and rules the offer ``DROP`` where any one of
them speaks at the ruling instant. No implementation may narrow that to a single
record — the most recently admitted or any other" — because the only pair that
separates a whole-population read from a narrowed one is *unreachable through the
Protocol*. §7 says so: the suite "could not pin it in any case, running as it does
against the canonical fake".

So the case lives beside the fake, exactly as ``test_engine_refusals.py`` holds the
canonical engine to a property its own suite does not state, and it seeds the pair
through the fake's own dict — the injection §7 leaves as the only route, since it
adds no member that would let a caller admit a chosen record. Its twin against the
durable store is
``tests/memory/test_sqlite_notification_store.py::test_a_legacy_overlap_suppresses_through_the_more_recently_admitted_record``;
two conforming stores must not be able to disagree here either.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ai_assistant.core.types import (
    DataTier,
    NotificationCandidate,
    NotificationCondition,
    NotificationDispositionKind,
)
from ai_assistant.testing import FakeNotificationPolicy, FakeNotificationStore

#: The clock's first reading. Local rather than imported from
#: ``tests/core/notification_contract.py``: this module asserts one clause and needs
#: none of that suite's machinery, and importing a conformance suite for a constant
#: would put the abstract bases on this module's collection path.
_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


class _MutableClock:
    """A clock the case moves, so a declared expiry can be crossed without waiting."""

    def __init__(self) -> None:
        self.at = _NOW

    def __call__(self) -> datetime:
        """Read the clock.

        Returns:
            The current reading, aware and UTC.
        """
        return self.at


def _candidate(*, expires_at: datetime, noticed_at: datetime) -> NotificationCandidate:
    """One candidate under the single key these cases deduplicate on.

    Args:
        expires_at: When the opportunity it names perishes.
        noticed_at: When the producer noticed it.

    Returns:
        The candidate.
    """
    return NotificationCandidate(
        candidate_key="k1",
        producer="a-producer",
        notification_class="calendar",
        summary="something the user did not ask for",
        noticed_at=noticed_at,
        expires_at=expires_at,
        confidence=0.5,
        sensitivity=DataTier.PERSONAL,
    )


async def test_a_legacy_overlap_suppresses_through_the_more_recently_admitted_record() -> None:
    """ADR-0215 §2's whole-population lookup, against the pair it was written for.

    §2 records how the pair arises and why no store can tell it apart from what this
    decision admits: "A store that ran under ADR-0130 §8 admitted a second record
    for a key the moment the first was dismissed; where that first record's candidate
    declared the *later* expiry, both of the pair speak under §1 until the earlier
    horizon passes... a store cannot tell the two vintages apart without a marker no
    clause here adds."

    Under this decision the pair cannot be built: a suppressing record makes every
    offer of its key a ``DROP`` and a ``DROP`` writes nothing, so from ADR-0215
    onward at most one record per key speaks. That is exactly why every arm in the
    shared suite would pass on a store that read only the most recently admitted
    record — and why the older record's declared expiry is moved out here directly,
    the one field the overlap turns on, on the record the fake already holds.

    At the ruling instant the younger record has perished and speaks for nothing,
    while the older one speaks until its planted horizon. A whole-population read
    drops the offer as a duplicate; a narrowed one admits it.
    """
    clock = _MutableClock()
    store = FakeNotificationStore(now=clock)
    policy = FakeNotificationPolicy()

    # The older record, admitted and dismissed the way ADR-0130 §8 left the key free.
    early = _NOW + timedelta(hours=1)
    older = await store.admit(_candidate(expires_at=early, noticed_at=_NOW), policy=policy)
    assert older.notification_id is not None
    assert await store.dismiss(older.notification_id) is True

    # The younger record, admitted for the same key once the older stopped speaking.
    clock.at = early
    younger = await store.admit(
        _candidate(expires_at=early + timedelta(hours=1), noticed_at=early), policy=policy
    )
    assert younger.notification_id is not None
    assert younger.kind is not NotificationDispositionKind.DROP

    # The overlap, planted: the *older* record now declares the *later* expiry.
    late = _NOW + timedelta(hours=10)
    # The fake's own dict, reached deliberately: §7 adds no member that would let a
    # caller admit a chosen record, so this is the only route the decision leaves.
    stored = store._records[older.notification_id]
    store._records[older.notification_id] = stored.model_copy(
        update={"candidate": stored.candidate.model_copy(update={"expires_at": late})}
    )

    # Between the two horizons: the most recently admitted record speaks for nothing.
    clock.at = early + timedelta(hours=2)
    held = {record.id: record for record in await store.held()}
    assert set(held) == {older.notification_id, younger.notification_id}
    assert held[younger.notification_id].speaks_for_its_key_at(clock.at) is False
    assert held[older.notification_id].speaks_for_its_key_at(clock.at) is True

    offered = await store.admit(
        _candidate(expires_at=late + timedelta(hours=1), noticed_at=clock.at), policy=policy
    )

    # A lookup narrowed to the most recently admitted record would admit this.
    assert offered.kind is NotificationDispositionKind.DROP
    assert offered.reason is NotificationCondition.DUPLICATE
    assert offered.notification_id is None
    assert len(await store.held()) == 2  # a DROP writes no record
