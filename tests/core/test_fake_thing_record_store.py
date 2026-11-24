"""The canonical FakeThingRecordStore passes the shared conformance suite (ADR-0381 §3).

This is what lets the lanes that read whose a thing is (ADR-0381 §6) trust
``ai_assistant.testing.FakeThingRecordStore`` as a stand-in for the store in
``permissions/``: it is held to the same contract. Below the binding, what only the fake
has: the fault it can be told to raise, and the things it records as it is built.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from thing_record_store_contract import (
    CALENDAR,
    LINE_PLACE,
    MAIL_ACCOUNT,
    OWN_CHAT,
    START,
    ThingRecordStoreContract,
    ThingRecordStoreFactory,
    recorded,
    ticking,
)

from ai_assistant.core.errors import ThingRecordStoreError
from ai_assistant.core.types import OWNER_PERSON_ID, ThingRecord
from ai_assistant.testing import FakeThingRecordStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import ThingRecordStore

pytestmark = pytest.mark.anyio


class TestFakeThingRecordStoreContract(ThingRecordStoreContract):
    """Runs FakeThingRecordStore through the shared ThingRecordStore suite."""

    @pytest.fixture
    def store(self) -> ThingRecordStore:
        # Built here rather than through ``factory``: the triad check evaluates the
        # subject fixture with nothing but ``self``, so it sees the fake itself
        # (tests/core/test_protocol_triad.py, ``_fixture_value``).
        return FakeThingRecordStore(now=ticking())

    @pytest.fixture
    def factory(self) -> ThingRecordStoreFactory:
        def build(*, now: Callable[[], datetime]) -> ThingRecordStore:
            return FakeThingRecordStore(now=now)

        return build


async def test_an_arranged_fault_fails_the_next_member_and_touches_nothing() -> None:
    store = FakeThingRecordStore(now=ticking())
    record = recorded(await store.record_whose(CALENDAR, person=OWNER_PERSON_ID))

    for call in (
        lambda: store.whose(CALENDAR),
        lambda: store.record_whose(MAIL_ACCOUNT, person=OWNER_PERSON_ID),
        store.export,
    ):
        store.fail_next()
        with pytest.raises(ThingRecordStoreError, match="told to fail"):
            await call()

    assert await store.export() == (record,)


async def test_the_things_it_is_built_with_are_the_owners_at_one_instant() -> None:
    store = FakeThingRecordStore(held=(OWN_CHAT, LINE_PLACE, OWN_CHAT, CALENDAR), now=ticking())

    assert await store.export() == tuple(
        ThingRecord(key=key, person=OWNER_PERSON_ID, recorded_at=START)
        for key in (OWN_CHAT, LINE_PLACE, CALENDAR)
    )


def test_a_held_entry_that_is_not_a_thing_key_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="ThingKey"):
        FakeThingRecordStore(held=("calendar",))  # type: ignore[arg-type]  # the malformed entry under test


def test_a_naive_clock_is_its_error_only_where_a_held_thing_is_recorded() -> None:
    naive = datetime(2026, 11, 24)  # noqa: DTZ001  # the naive reading under test
    FakeThingRecordStore(now=lambda: naive)

    with pytest.raises(ThingRecordStoreError, match="clock"):
        FakeThingRecordStore(held=(CALENDAR,), now=lambda: naive)
