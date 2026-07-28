"""The canonical FakeConversationStore passes the shared conformance suite.

This is what lets other subsystems trust
``ai_assistant.testing.FakeConversationStore`` as a stand-in for a real store: it
is held to the same contract as ``SqliteConversationStore``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from conversation_store_contract import (
    ConversationStoreContract,
    ConversationStoreFactory,
    MovableClock,
)

from ai_assistant.core.errors import ConversationStoreError
from ai_assistant.testing import FakeConversationStore

if TYPE_CHECKING:
    from collections.abc import Callable

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


async def test_the_fake_refuses_a_clock_that_is_not_a_conforming_reading() -> None:
    """A fake looser than the contract certifies consumers a real store rejects.

    ``ConversationStoreError``, not the raw ``ValueError`` ``core`` raises, because
    that is what the persistent store raises at the same seam (ADR-0026 §4, §7).
    """
    store = FakeConversationStore(now=lambda: datetime(2026, 6, 1))  # noqa: DTZ001 — the point

    with pytest.raises(ConversationStoreError):
        await store.start()
