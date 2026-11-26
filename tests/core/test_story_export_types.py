"""ADR-0385 §6:8, §11: the story store's export, as frozen models in ``core``.

``StoryExport`` holds the stories, no story twice; each ``ExportedStory`` holds a story's
header and every part of it that takes its home (ADR-0383 §3:2), each part its own, so a
log line naming another story or a kept summary no version of the story wrote is refused.
Nothing store-wide is a field of either (§8:5).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ExportedStory,
    RecordHome,
    StoryActor,
    StoryChange,
    StoryEntry,
    StoryExport,
    StoryHeader,
    StoryLogLine,
    StoryMember,
    StoryMemberKind,
    StoryNote,
    StoryNoteAuthor,
    StorySummary,
    StorySummaryLine,
    StorySummaryVersion,
)

_AT = datetime(2026, 11, 26, 12, tzinfo=UTC)


def _header(story_id: str = "story:one") -> StoryHeader:
    return StoryHeader(
        story_id=story_id, created_at=_AT, merged_into=None, home=RecordHome.owners()
    )


def _line(story_id: str = "story:one", sequence: int = 1) -> StoryLogLine:
    return StoryLogLine(
        sequence=sequence,
        story_id=story_id,
        change=StoryChange.CREATED,
        member=None,
        other_story=None,
        actor=StoryActor.OWNER,
        trigger=None,
        at=_AT,
    )


def _whole(story_id: str = "story:one") -> ExportedStory:
    member = StoryMember(kind=StoryMemberKind.ACTIVATION, id="a1")
    return ExportedStory(
        story=_header(story_id),
        members=(StoryEntry(position=2, member=member, linked_at=_AT, actor=StoryActor.OWNER),),
        log=(_line(story_id),),
        notes=(
            StoryNote(
                note_id=3,
                text="A note.",
                author=StoryNoteAuthor.PLANNING,
                written_during="a1",
                outside=False,
                written_at=_AT,
            ),
        ),
        versions=(
            StorySummaryVersion(version=4, written_at=_AT, took_in_notes=(3,), outside=False),
        ),
        summaries=(
            StorySummary(
                version=4, written_at=_AT, lines=(StorySummaryLine(text="Line."),), outside=False
            ),
        ),
    )


def test_a_story_is_exported_with_every_part_of_it() -> None:
    whole = _whole()
    assert StoryExport(stories=(whole,)).stories == (whole,)


def test_an_export_holds_no_story_by_default_and_a_story_no_part() -> None:
    assert StoryExport().stories == ()
    bare = ExportedStory(story=_header())
    assert (bare.members, bare.log, bare.notes, bare.versions, bare.summaries) == ((),) * 5


def test_an_exported_story_carries_no_log_line_of_another_story() -> None:
    with pytest.raises(ValidationError, match="only its own log lines"):
        ExportedStory(story=_header(), log=(_line("story:other"),))


def test_an_exported_story_carries_no_summary_its_own_versions_did_not_write() -> None:
    summary = StorySummary(version=9, written_at=_AT, lines=(), outside=False)
    with pytest.raises(ValidationError, match="summaries its own versions wrote"):
        ExportedStory(story=_header(), summaries=(summary,))


def test_a_version_with_no_kept_summary_is_carried() -> None:
    """ADR-0347 §5:1: a version written before every summary was kept has no text."""
    version = StorySummaryVersion(version=1, written_at=_AT, outside=False)
    assert ExportedStory(story=_header(), versions=(version,)).summaries == ()


def test_an_export_carries_no_story_twice() -> None:
    with pytest.raises(ValidationError, match="no story twice"):
        StoryExport(stories=(_whole(), _whole()))


def test_both_models_are_frozen_and_closed() -> None:
    exported = StoryExport(stories=(_whole(),))
    with pytest.raises(ValidationError):
        exported.stories = ()
    with pytest.raises(ValidationError):
        StoryExport.model_validate({"stories": [], "position": 3})
    with pytest.raises(ValidationError):
        ExportedStory.model_validate({"story": _header().model_dump(), "as_of": 3})


def test_an_export_round_trips_through_its_json() -> None:
    exported = StoryExport(stories=(_whole("story:two"), _whole()))
    assert StoryExport.model_validate_json(exported.model_dump_json()) == exported
