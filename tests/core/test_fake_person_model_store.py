"""The canonical FakePersonModelStore passes the shared conformance suite.

This is what lets orchestration's person block, and every later consumer, trust
``ai_assistant.testing.FakePersonModelStore`` as a stand-in for the store: it is held to
the same contract the store in ``memory/`` will be (ADR-0338 §10, §11). Below the
binding, what only the fake has: the fault it can be told to raise, its default bound,
and the ids an injected ``new_id`` mints: one that fails, or that a held record already
carries, fails its write with nothing changed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from person_model_store_contract import (
    FIELD_CHARS,
    MEMORY,
    OTHER_MEMORY,
    PANEL,
    PersonModelStoreContract,
    PersonModelStoreFactory,
    pin_suggestion,
    ticking,
)

from ai_assistant.core.errors import PersonModelStoreError
from ai_assistant.core.types import OWNER_PERSON_ID, PersonModelWriteKind, ProfileField
from ai_assistant.testing import DEFAULT_PROFILE_FIELD_CHARS, FakePersonModelStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

    from ai_assistant.core.protocols import PersonModelStore

pytestmark = pytest.mark.anyio

#: The fake's default bound, restated rather than imported: a default changed without
#: this test noticing is the drift worth failing on.
_FIELD_CHARS_DEFAULT = 200


class TestFakePersonModelStoreContract(PersonModelStoreContract):
    """Runs FakePersonModelStore through the shared PersonModelStore suite."""

    @pytest.fixture
    def store(self) -> PersonModelStore:
        return FakePersonModelStore(field_chars=FIELD_CHARS, now=ticking())

    @pytest.fixture
    def factory(self) -> PersonModelStoreFactory:
        def build(
            *,
            field_chars: int = _FIELD_CHARS_DEFAULT,
            now: Callable[[], datetime] | None = None,
        ) -> PersonModelStore:
            if now is None:
                return FakePersonModelStore(field_chars=field_chars)
            return FakePersonModelStore(field_chars=field_chars, now=now)

        return build


async def test_an_arranged_fault_fails_the_next_member_and_touches_nothing() -> None:
    store = FakePersonModelStore()
    store.fail_next()

    with pytest.raises(PersonModelStoreError):
        await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)

    model = await store.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.pins == ()


async def test_its_default_bound_is_restated_here() -> None:
    store = FakePersonModelStore()

    at_bound = await store.set_field(
        OWNER_PERSON_ID, ProfileField.NAME, "x" * _FIELD_CHARS_DEFAULT, act=PANEL
    )
    over = await store.set_field(
        OWNER_PERSON_ID, ProfileField.NAME, "y" * (_FIELD_CHARS_DEFAULT + 1), act=PANEL
    )

    assert DEFAULT_PROFILE_FIELD_CHARS == _FIELD_CHARS_DEFAULT
    assert at_bound.kind is PersonModelWriteKind.WRITTEN
    assert over.kind is PersonModelWriteKind.REFUSED


def test_a_bound_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one"):
        FakePersonModelStore(field_chars=0)


class _Minting:
    """A ``new_id`` that mints ``fixed`` where given, and fails while ``failing`` is set."""

    def __init__(self, fixed: str | None = None) -> None:
        self.fixed = fixed
        self.failing = False
        self.minted = 0

    def __call__(self, kind: str) -> str:
        if self.failing:
            msg = "the id cannot be minted"
            raise PersonModelStoreError(msg)
        self.minted += 1
        return self.fixed or f"{kind}:minted-{self.minted}"


@pytest.mark.parametrize("route", ["accept", "add_pin"])
async def test_a_pin_whose_id_fails_to_mint_leaves_its_suggestion_pending(route: str) -> None:
    """§10:2: the pin is minted before the suggestion it takes up is accepted."""
    minting = _Minting()
    store = FakePersonModelStore(now=ticking(), new_id=minting)
    recorded = await store.record_suggestion(OWNER_PERSON_ID, pin_suggestion(MEMORY))
    assert recorded.record_id is not None
    before = await store.export()

    suggestion_id = recorded.record_id
    taking_up: Callable[[], Awaitable[object]] = (
        (lambda: store.accept_suggestion(OWNER_PERSON_ID, suggestion_id, by=OWNER_PERSON_ID))
        if route == "accept"
        else (lambda: store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL))
    )

    minting.failing = True
    with pytest.raises(PersonModelStoreError):
        await taking_up()

    assert await store.export() == before
    minting.failing = False
    retried = await store.accept_suggestion(OWNER_PERSON_ID, recorded.record_id, by=OWNER_PERSON_ID)
    assert retried.kind is PersonModelWriteKind.WRITTEN
    model = await store.read(OWNER_PERSON_ID)
    assert model is not None
    assert [pin.memory_id for pin in model.pins] == [MEMORY]
    assert model.suggestions == ()


def _writes(store: FakePersonModelStore) -> dict[str, Callable[[], Awaitable[object]]]:
    return {
        "pin": lambda: store.add_pin(OWNER_PERSON_ID, OTHER_MEMORY, act=PANEL),
        "mark": lambda: store.add_style_mark(OWNER_PERSON_ID, OTHER_MEMORY),
        "suggestion": lambda: store.record_suggestion(
            OWNER_PERSON_ID, pin_suggestion(OTHER_MEMORY)
        ),
    }


@pytest.mark.parametrize("write", ["pin", "mark", "suggestion"])
@pytest.mark.parametrize("removed", [False, True], ids=["standing", "removed"])
async def test_an_id_a_held_record_carries_is_never_minted_again(
    write: str, *, removed: bool
) -> None:
    """A minted id a record holds, removed or not, fails the write with nothing changed."""
    store = FakePersonModelStore(now=ticking(), new_id=_Minting(fixed="record:one"))
    first = await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)
    assert first.record_id == "record:one"
    if removed:
        await store.remove_pin(OWNER_PERSON_ID, "record:one")
    before = await store.export()

    with pytest.raises(PersonModelStoreError, match="already carries"):
        await _writes(store)[write]()

    assert await store.export() == before
