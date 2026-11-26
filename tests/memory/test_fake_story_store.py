"""The canonical FakeStoryStore passes the shared conformance suite (ADR-0289 §1)."""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING

import pytest
from story_store_contract import STORY_AT, StoryStoreContract

from ai_assistant.testing import FakeStoryStore

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

    from ai_assistant.core.protocols import StoryStore
    from ai_assistant.core.types import RecordHome, SightMode


class TestFakeStoryStoreContract(StoryStoreContract):
    """Runs FakeStoryStore through the shared StoryStore conformance suite."""

    @pytest.fixture
    def store(self) -> StoryStore:
        return FakeStoryStore(now=lambda: STORY_AT)

    @pytest.fixture
    def sight_store_factory(self) -> Callable[[SightMode], StoryStore]:
        def build(mode: SightMode) -> StoryStore:
            ids = count(1)
            return FakeStoryStore(
                now=lambda: STORY_AT, new_id=lambda: f"{next(ids):04d}", sight_mode=mode
            )

        return build

    @pytest.fixture
    def remove_stories(self) -> Callable[[StoryStore, Collection[str]], None]:
        """Remove stories whole from the fake's state, as the suite's test-only door asks."""

        def remove(store: StoryStore, story_ids: Collection[str]) -> None:
            assert isinstance(store, FakeStoryStore)
            gone = set(story_ids)
            state = store._state  # the test-only door the Protocol has none of
            state.stories = {key: one for key, one in state.stories.items() if key not in gone}
            state.log = [one for one in state.log if one.story_id not in gone]
            state.notes = {key: one for key, one in state.notes.items() if one.story_id not in gone}
            state.summaries = {key: one for key, one in state.summaries.items() if key not in gone}
            state.kept = {key: one for key, one in state.kept.items() if one[0] not in gone}
            state.versions = [one for one in state.versions if one[0] not in gone]

        return remove

    @pytest.fixture
    def set_story_home(self) -> Callable[[StoryStore, str, RecordHome], None]:
        """Give a stored story another home in the fake's state, as the suite's door asks."""

        def rehome(store: StoryStore, story_id: str, home: RecordHome) -> None:
            assert isinstance(store, FakeStoryStore)
            store._state.stories[story_id].home = home  # the test-only door

        return rehome
