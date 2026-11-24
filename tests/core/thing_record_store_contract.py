"""Shared conformance suite for the ThingRecordStore Protocol (ADR-0381 §3).

Every ``ThingRecordStore`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`ThingRecordStoreContract` and
supplies one fixture, ``factory``, which builds an empty subject on a chosen clock.

The cases follow the contract: a store that starts empty, in which a thing with no record
reads as none (ADR-0381 §5:1); a record written with its key, the owner and its instant
(§3:2, §3:3); a thing's key telling a connection from a source, and matched exactly; a
write where a record stands writing nothing (§3:4), concurrent ones included; every record
carried by the export, in the order recorded (§3:4); and a person other than the owner,
or a malformed key, refused before anything is read. What only one implementation owes —
the things recorded as it opens, a persistent store's file, what survives its reopening,
its schema label, a backend fault; the fake's arranged fault — is that implementation's own
test.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a ``Test``-prefixed
subclass.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Final, Protocol

import pytest

from ai_assistant.core.protocols import ThingRecordStore
from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    APPROVALS_CONNECTION,
    OWN_CHAT_CONNECTION,
    OWNER_PERSON_ID,
    SCHEDULE_CONNECTION,
    ThingKey,
    ThingKind,
    ThingRecord,
    ThingRecording,
    ThingRecordingKind,
)

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.anyio

#: The first reading of the clock :func:`ticking` hands out, and its step.
START: Final = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
STEP: Final = timedelta(seconds=1)

#: The system's own chat, as one connection (ADR-0376 §2:4).
OWN_CHAT: Final = ThingKey(kind=ThingKind.CONNECTION, identifier=OWN_CHAT_CONNECTION)
#: The line's place: one chat of one bot.
LINE_PLACE: Final = ThingKey(kind=ThingKind.CONNECTION, identifier="telegram:conn-bot/424242")
#: The schedule and the approvals, each as its one place (ADR-0381 §3:2).
SCHEDULE: Final = ThingKey(kind=ThingKind.CONNECTION, identifier=SCHEDULE_CONNECTION)
APPROVALS: Final = ThingKey(kind=ThingKind.CONNECTION, identifier=APPROVALS_CONNECTION)
#: An account connection, by its reference.
MAIL_ACCOUNT: Final = ThingKey(kind=ThingKind.CONNECTION, identifier="account:conn-mail")
#: A source, by its reader's declared identity (ADR-0097 §1:1).
CALENDAR: Final = ThingKey(kind=ThingKind.SOURCE, identifier="calendar")

#: One of each kind of thing a record is kept for (ADR-0381 §2:1, §2:2).
EVERY_KIND: Final = (OWN_CHAT, LINE_PLACE, SCHEDULE, APPROVALS, MAIL_ACCOUNT, CALENDAR)


def ticking() -> Callable[[], datetime]:
    """A clock that reads :data:`START`, then one :data:`STEP` later on each reading.

    Returns:
        The clock.
    """
    seconds = count()
    return lambda: START + next(seconds) * STEP


class ThingRecordStoreFactory(Protocol):
    """Builds an empty subject on the clock given."""

    def __call__(self, *, now: Callable[[], datetime]) -> ThingRecordStore: ...


def recorded(recording: ThingRecording) -> ThingRecord:
    """The record a write wrote, asserting that it wrote one.

    Args:
        recording: What a write returned.

    Returns:
        Its new record.
    """
    assert recording.kind is ThingRecordingKind.RECORDED, recording
    return recording.record


class ThingRecordStoreContract:
    """Behaviour every ThingRecordStore implementation must exhibit."""

    @pytest.fixture
    def factory(self) -> ThingRecordStoreFactory:
        """Build an empty subject. Overridden per implementation."""
        raise NotImplementedError

    @pytest.fixture
    def store(self, factory: ThingRecordStoreFactory) -> ThingRecordStore:
        """An empty subject on a ticking clock from :data:`START`."""
        return factory(now=ticking())

    def test_it_satisfies_the_protocol(self, store: ThingRecordStore) -> None:
        assert isinstance(store, ThingRecordStore)

    # --- a thing with no record (ADR-0381 §5:1) ----------------------------------------

    async def test_it_starts_empty_and_a_thing_with_no_record_reads_as_none(
        self, store: ThingRecordStore
    ) -> None:
        for key in EVERY_KIND:
            assert await store.whose(key) is None
        assert await store.export() == ()

    # --- a write (ADR-0381 §3:2-§3:4) --------------------------------------------------

    @pytest.mark.parametrize("key", EVERY_KIND, ids=lambda key: key.identifier)
    async def test_a_record_holds_its_key_the_owner_and_its_instant(
        self, store: ThingRecordStore, key: ThingKey
    ) -> None:
        record = recorded(await store.record_whose(key, person=OWNER_PERSON_ID))

        assert record == ThingRecord(key=key, person=OWNER_PERSON_ID, recorded_at=START)
        assert await store.whose(key) == record
        assert await store.export() == (record,)

    async def test_a_record_names_only_its_own_thing(self, store: ThingRecordStore) -> None:
        recorded(await store.record_whose(MAIL_ACCOUNT, person=OWNER_PERSON_ID))

        for key in EVERY_KIND:
            if key != MAIL_ACCOUNT:
                assert await store.whose(key) is None

    async def test_a_connection_and_a_source_of_one_identifier_are_two_things(
        self, store: ThingRecordStore
    ) -> None:
        """The key is the thing's kind and its identifier together (ADR-0381 §3:2)."""
        connection = ThingKey(kind=ThingKind.CONNECTION, identifier=OWN_CHAT_CONNECTION)
        source = ThingKey(kind=ThingKind.SOURCE, identifier=OWN_CHAT_CONNECTION)
        first = recorded(await store.record_whose(connection, person=OWNER_PERSON_ID))

        assert await store.whose(source) is None
        second = recorded(await store.record_whose(source, person=OWNER_PERSON_ID))

        assert await store.export() == (first, second)

    async def test_an_identifier_is_matched_exactly(self, store: ThingRecordStore) -> None:
        recorded(await store.record_whose(MAIL_ACCOUNT, person=OWNER_PERSON_ID))

        for other in ("account:conn-Mail", "account:conn-mail2", "account:conn-mai"):
            assert await store.whose(ThingKey(kind=ThingKind.CONNECTION, identifier=other)) is None

    async def test_the_export_carries_every_record_in_the_order_recorded(
        self, store: ThingRecordStore
    ) -> None:
        records = [
            recorded(await store.record_whose(key, person=OWNER_PERSON_ID)) for key in EVERY_KIND
        ]

        assert await store.export() == tuple(records)
        assert [one.recorded_at for one in records] == [
            START + number * STEP for number in range(len(EVERY_KIND))
        ]

    # --- a write where a record stands (ADR-0381 §3:4, §7:1) ---------------------------

    async def test_a_write_where_a_record_stands_writes_nothing(
        self, store: ThingRecordStore
    ) -> None:
        first = recorded(await store.record_whose(CALENDAR, person=OWNER_PERSON_ID))

        again = await store.record_whose(CALENDAR, person=OWNER_PERSON_ID)

        assert again == ThingRecording(kind=ThingRecordingKind.ALREADY_RECORDED, record=first)
        assert await store.whose(CALENDAR) == first
        assert await store.export() == (first,)

    async def test_concurrent_writes_for_one_thing_write_one_record(
        self, store: ThingRecordStore
    ) -> None:
        recordings = await asyncio.gather(
            *(store.record_whose(LINE_PLACE, person=OWNER_PERSON_ID) for _ in range(8))
        )

        kinds = [one.kind for one in recordings]
        assert kinds.count(ThingRecordingKind.RECORDED) == 1
        assert kinds.count(ThingRecordingKind.ALREADY_RECORDED) == len(recordings) - 1
        assert len({one.record for one in recordings}) == 1
        assert await store.export() == (recordings[0].record,)

    # --- what is refused before anything is read (ADR-0381 §3:3) -----------------------

    @pytest.mark.parametrize(
        "person",
        [ANYONE_GROUP_ID, "person:someone-else", "", "  ", f" {OWNER_PERSON_ID}", 7, None],
    )
    async def test_a_person_other_than_the_owner_is_a_value_error(
        self, store: ThingRecordStore, person: object
    ) -> None:
        with pytest.raises(ValueError, match="owner's identity alone"):
            await store.record_whose(CALENDAR, person=person)  # type: ignore[arg-type]  # the malformed person under test

        assert await store.whose(CALENDAR) is None
        assert await store.export() == ()

    @pytest.mark.parametrize("key", ["calendar", ("source", "calendar"), None, 7])
    async def test_a_key_that_is_not_a_thing_key_is_a_value_error(
        self, store: ThingRecordStore, key: object
    ) -> None:
        with pytest.raises(ValueError, match="ThingKey"):
            await store.whose(key)  # type: ignore[arg-type]  # the malformed key under test
        with pytest.raises(ValueError, match="ThingKey"):
            await store.record_whose(key, person=OWNER_PERSON_ID)  # type: ignore[arg-type]  # the malformed key under test

        assert await store.export() == ()

    @pytest.mark.parametrize(
        ("kind", "identifier"),
        [
            (ThingKind.CONNECTION, "conversation:chat-1"),
            (ThingKind.CONNECTION, "task_scheduler:other"),
            (ThingKind.CONNECTION, "no-separator"),
            (ThingKind.SOURCE, " calendar"),
        ],
    )
    async def test_a_key_that_skipped_validation_is_a_value_error(
        self, store: ThingRecordStore, kind: ThingKind, identifier: str
    ) -> None:
        key = ThingKey.model_construct(kind=kind, identifier=identifier)

        with pytest.raises(ValueError, match="not a valid ThingKey"):
            await store.whose(key)
        with pytest.raises(ValueError, match="not a valid ThingKey"):
            await store.record_whose(key, person=OWNER_PERSON_ID)

        assert await store.export() == ()
