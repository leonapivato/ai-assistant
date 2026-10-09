"""ADR-0304 §4's privacy minimum: what a reader is shown of a story's notes and summary.

One question about the reader decides both: whether a record placed for the owner alone
may be shown to it (ADR-0303 §3:9, ADR-0304 §4:1). Nothing behind a summary is read to
decide it (§4:3), so this module reads no store at all.
"""

from __future__ import annotations

import ast
import inspect
from typing import Any, Final

from story_support import AT, episode

from ai_assistant.core.types import StoryNote, StoryNoteAuthor
from ai_assistant.orchestration import story_privacy
from ai_assistant.orchestration.story_privacy import SummaryVisibility, activation_of


def _note(note_id: int, **fields: Any) -> StoryNote:
    values: dict[str, Any] = {
        "note_id": note_id,
        "text": "a note",
        "author": StoryNoteAuthor.PLANNING,
        "written_during": "a-1",
        "outside": False,
        "written_at": AT,
    }
    return StoryNote.model_validate(values | fields)


_PLANNED: Final = _note(1)
_MARKED: Final = _note(2, outside=True)
_OWNER: Final = _note(3, author=StoryNoteAuthor.OWNER, written_during=None)


def test_a_note_is_shown_where_an_owner_record_may_be_whoever_wrote_it() -> None:
    """ADR-0303 §3:9: the activation it was written during, and its mark, decide nothing."""
    for note in (_PLANNED, _MARKED, _OWNER):
        assert SummaryVisibility(owner_records=True).note(note)
        assert not SummaryVisibility(owner_records=False).note(note)


def test_a_summary_is_shown_exactly_where_an_owner_record_may_be() -> None:
    """ADR-0304 §4:1: the summary follows a note's rule, and nothing else decides it."""
    assert SummaryVisibility(owner_records=True).summary()
    assert not SummaryVisibility(owner_records=False).summary()


def test_the_rule_reads_no_store_and_walks_no_version_log() -> None:
    """ADR-0304 §4:3: no rule walks a version log, so the module touches no store.

    The retired walk read ``StoryStore.summary_versions`` and followed ``read_pages``;
    neither name, nor any store, appears in the module's code.
    """
    tree = ast.parse(inspect.getsource(story_privacy))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert not {"StoryStore", "MemoryStore"} & imported
    assert not {"summary_versions", "read_pages", "took_in_episodes"} & (names | attributes)
    assert not hasattr(story_privacy, "behind")


def test_an_episode_recording_no_activation_has_none() -> None:
    legacy = episode("a-1").model_copy(update={"processing_record": None})

    assert activation_of(legacy) is None
    assert activation_of(episode("a-1")) == "a-1"
