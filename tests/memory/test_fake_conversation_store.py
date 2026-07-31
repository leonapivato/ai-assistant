"""The canonical FakeConversationStore passes the shared conformance suite.

This is what lets other subsystems trust
``ai_assistant.testing.FakeConversationStore`` as a stand-in for a real store: it
is held to the same contract as ``SqliteConversationStore``.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from conversation_store_contract import (
    ConversationStoreContract,
    ConversationStoreFactory,
    MovableClock,
)

from ai_assistant.core.errors import ConversationStoreError, UnknownConversationError
from ai_assistant.testing import FakeConversationStore
from ai_assistant.testing.cancellation import SuspendedMidWrite, settle

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from ai_assistant.core.protocols import ConversationStore

#: The fake's own defaults, restated here rather than imported: the suite asserts
#: the store *behaves* to these figures, so a default changed without this test
#: noticing is exactly the drift worth failing on.
_TAIL_DEFAULT = 20
_PURGE_DEFAULT = 100


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


class TestFakeConversationStoreContract(ConversationStoreContract):
    """Runs FakeConversationStore through the shared ConversationStore suite."""

    @pytest.fixture
    def store(self) -> ConversationStore:
        return FakeConversationStore(now=_fixed_now)

    @pytest.fixture
    def defaults(self) -> tuple[ConversationStore, MovableClock]:
        clock = MovableClock()
        return FakeConversationStore(now=clock), clock

    @pytest.fixture
    def factory(self) -> ConversationStoreFactory:
        def build(  # noqa: PLR0913 — one keyword per injected seam
            *,
            now: Callable[[], datetime],
            new_id: Callable[[], str],
            retention: timedelta | None,
            tombstone_grace: timedelta,
            tail_limit: int,
            purge_batch: int,
        ) -> ConversationStore:
            return FakeConversationStore(
                now=now,
                new_id=new_id,
                retention=retention,
                tombstone_grace=tombstone_grace,
                tail_limit=tail_limit,
                purge_batch=purge_batch,
            )

        return build

    @pytest.fixture
    def tail_default(self) -> int:
        return _TAIL_DEFAULT

    @pytest.fixture
    def purge_default(self) -> int:
        return _PURGE_DEFAULT

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[ConversationStore]]:
        """The fake models the resource it does not really own (ADR-0060 §3).

        Dicts need no serialising, so without this the canonical fake could only opt
        out — and ADR-0060's case would run solely against the ``sqlite3`` store,
        the implementation that already holds the invariant. Every mutation passes
        through the *one* modelled resource, so ``arm`` ignores which operation it
        is handed: the parametrised cases (#370) exercise the same ``held()`` path
        here and earn their keep on the ``sqlite3`` store, where each operation is a
        separate lock site. Nothing to dispose of, hence the bare yield.
        """
        store = FakeConversationStore(now=_fixed_now)
        yield SuspendedMidWrite(
            store=store,
            log=store.resource_log,
            arm=lambda _operation: store.suspend_next_operation(),
        )


async def test_no_lock_is_kept_for_a_conversation_the_store_does_not_hold() -> None:
    """#453: every call against an id that names nothing used to leave a lock behind.

    ``_exclusive`` takes the lock *before* checking whether the id exists — which it
    must, or a concurrent ``stamp_deleted`` and ``append`` could both observe the
    conversation as live — so the entry was created for a typo, a dropped
    conversation and a refused append alike, and ``_locks`` grew without bound in a
    long-running or fuzzing process. Read off the dict because there is nowhere else
    the leak is observable: every one of these calls is a no-op or an error either
    way, which is exactly why it went unnoticed.
    """
    store = FakeConversationStore(now=_fixed_now, tombstone_grace=timedelta(hours=1))

    assert await store.stamp_deleted("nobody") is False
    assert await store.drop_if_eligible("nobody") is False
    with pytest.raises(UnknownConversationError):
        await store.append("nobody", occurred_at=_fixed_now())
    with pytest.raises(UnknownConversationError):
        await store.mark_active("nobody")

    assert store._locks == {}


async def test_no_lock_is_kept_for_a_conversation_that_was_dropped() -> None:
    """The other half: a conversation that really existed and then went away."""
    clock = MovableClock()
    grace = timedelta(hours=1)
    store = FakeConversationStore(now=clock, tombstone_grace=grace)

    conversation = await store.start()
    await store.append(conversation.id, occurred_at=clock())
    assert await store.stamp_deleted(conversation.id) is True
    clock.advance(grace)
    assert await store.drop_if_eligible(conversation.id) is True

    assert store._locks == {}


async def test_the_exclusion_hands_one_lock_to_every_caller_of_one_id() -> None:
    """Discarding the entry must not hand a late arrival a lock of its own.

    This is the failure the fix had to avoid, and the one thing this fake must not
    have: an exclusion that goes on being *acquired* while silently ceasing to
    *exclude*. A **queue** is what makes it observable, so the case builds one —
    a caller inside, a second waiting behind it, and only then a third arriving
    after the first has left. An implementation that popped the entry as soon as
    its first holder departed would mint a second lock for that third caller, which
    would enter beside the second rather than queue behind it.

    Driven through ``_exclusive`` directly: it is a private seam, but the property
    is about lock *identity* across arrivals and there is no public surface on which
    to observe it — every mutation acquires and releases within one call.
    """
    store = FakeConversationStore(now=_fixed_now)
    inside: list[str] = []
    gates = {name: asyncio.Event() for name in ("first", "second", "third")}

    async def mutate(name: str) -> None:
        async with store._exclusive("c-1"):
            inside.append(name)
            await gates[name].wait()

    first = asyncio.ensure_future(mutate("first"))
    await settle()
    second = asyncio.ensure_future(mutate("second"))
    await settle()
    assert inside == ["first"], "the second caller must queue, not run beside the first"

    gates["first"].set()
    await settle()
    assert inside == ["first", "second"], "the second caller should have been let through"

    third = asyncio.ensure_future(mutate("third"))
    await settle()
    assert inside == ["first", "second"], (
        "a third caller arriving after the first left was handed its own lock and ran "
        "inside the exclusion beside the second — the exclusion has stopped excluding"
    )

    for name in ("second", "third"):
        gates[name].set()
        await settle()
    await asyncio.gather(first, second, third)

    assert store._locks == {}, "and nothing is left behind once nobody holds it"


async def test_the_fake_refuses_a_clock_that_is_not_a_conforming_reading() -> None:
    """A fake looser than the contract certifies consumers a real store rejects.

    ``ConversationStoreError``, not the raw ``ValueError`` ``core`` raises, because
    that is what the persistent store raises at the same seam (ADR-0026 §4, §7).
    """
    store = FakeConversationStore(now=lambda: datetime(2026, 6, 1))  # noqa: DTZ001 — the point

    with pytest.raises(ConversationStoreError):
        await store.start()
