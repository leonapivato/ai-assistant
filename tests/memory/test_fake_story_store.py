"""The canonical FakeStoryStore passes the shared conformance suite (ADR-0289 §1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from story_store_contract import STORY_AT, StoryStoreContract

from ai_assistant.testing import FakeStoryStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import StoryStore


class TestFakeStoryStoreContract(StoryStoreContract):
    """Runs FakeStoryStore through the shared StoryStore conformance suite."""

    @pytest.fixture
    def store(self) -> StoryStore:
        return FakeStoryStore(now=lambda: STORY_AT)
