"""The canonical FakePersonModelStore passes the shared conformance suite.

This is what lets orchestration's person block, and every later consumer, trust
``ai_assistant.testing.FakePersonModelStore`` as a stand-in for the store: it is held to
the same contract the store in ``memory/`` will be (ADR-0338 §10, §11). Below the
binding, what only the fake has: the fault it can be told to raise, and its default
bound.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from person_model_store_contract import (
    FIELD_CHARS,
    MEMORY,
    PANEL,
    PersonModelStoreContract,
    PersonModelStoreFactory,
    ticking,
)

from ai_assistant.core.errors import PersonModelStoreError
from ai_assistant.core.types import OWNER_PERSON_ID, PersonModelWriteKind, ProfileField
from ai_assistant.testing import DEFAULT_PROFILE_FIELD_CHARS, FakePersonModelStore

if TYPE_CHECKING:
    from collections.abc import Callable
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
