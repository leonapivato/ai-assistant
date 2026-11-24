"""The canonical FakePermissionLineStore passes the shared conformance suite (ADR-0367 §3:6).

This is what lets the lanes that check a call against lines, and those that list, make and
remove them for the owner, trust ``ai_assistant.testing.FakePermissionLineStore`` as a
stand-in for the store in ``permissions/``: it is held to the same contract. Below the
binding, what only the fake has: the fault it can be told to raise, and the identifiers an
injected ``new_id`` mints.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from permission_line_store_contract import (
    FULL_GRANT,
    MAIL_LIMIT,
    PermissionLineStoreContract,
    PermissionLineStoreFactory,
    made,
    ticking,
)

from ai_assistant.core.errors import PermissionLineStoreError
from ai_assistant.core.types import OWNER_PERSON_ID
from ai_assistant.testing import FakePermissionLineStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import PermissionLineStore

pytestmark = pytest.mark.anyio


class TestFakePermissionLineStoreContract(PermissionLineStoreContract):
    """Runs FakePermissionLineStore through the shared PermissionLineStore suite."""

    @pytest.fixture
    def store(self) -> PermissionLineStore:
        # Built here rather than through ``factory``: the triad check evaluates the
        # subject fixture with nothing but ``self``, so it sees the fake itself
        # (tests/core/test_protocol_triad.py, ``_fixture_value``).
        return FakePermissionLineStore(now=ticking())

    @pytest.fixture
    def factory(self) -> PermissionLineStoreFactory:
        def build(*, now: Callable[[], datetime]) -> PermissionLineStore:
            return FakePermissionLineStore(now=now)

        return build


async def test_an_arranged_fault_fails_the_next_member_and_touches_nothing() -> None:
    store = FakePermissionLineStore(now=ticking())
    line = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))

    for member in (
        store.standing,
        lambda: store.line(line.id),
        lambda: store.record_making(FULL_GRANT, by=OWNER_PERSON_ID),
        lambda: store.record_removal(line.id, by=OWNER_PERSON_ID),
    ):
        store.fail_next()
        with pytest.raises(PermissionLineStoreError, match="told to fail"):
            await member()

    assert await store.standing() == (line,)


async def test_an_identifier_a_held_line_carries_is_never_minted_again() -> None:
    store = FakePermissionLineStore(now=ticking(), new_id=lambda: "line:one")
    first = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))
    await store.record_removal(first.id, by=OWNER_PERSON_ID)
    before = await store.line(first.id)

    with pytest.raises(PermissionLineStoreError, match="already carries"):
        await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID)

    assert await store.standing() == ()
    assert await store.line(first.id) == before


@pytest.mark.parametrize("minted", ["", "  ", 7])
async def test_a_minted_identifier_that_is_not_one_is_a_store_fault(minted: object) -> None:
    store = FakePermissionLineStore(now=ticking(), new_id=lambda: minted)  # type: ignore[arg-type, return-value]  # the malformed factory under test

    with pytest.raises(PermissionLineStoreError, match="not one"):
        await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID)

    assert await store.standing() == ()


async def test_a_clock_reading_that_is_not_an_aware_instant_is_a_store_fault() -> None:
    store = FakePermissionLineStore(now=lambda: datetime(2026, 11, 24))  # noqa: DTZ001  # the naive reading under test

    with pytest.raises(PermissionLineStoreError, match="clock"):
        await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID)

    assert await store.standing() == ()
