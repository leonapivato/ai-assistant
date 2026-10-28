"""What planning is shown of stories, and how it renders them (ADR-0307 §6:1, §6:3-§6:4).

Driven directly over the planning stage, with the views built by hand as the phases'
glue would hand them over; ``test_phase_path_stories`` reads them from the stores.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from test_planning import _AT, _earlier, _episode, _inputs, _sent, _stage

from ai_assistant.core.types import (
    LabelKind,
    PlanningLabel,
    RoundResponse,
    StoryEffectState,
    StoryHeader,
    StoryNote,
    StoryNoteAuthor,
    StoryRelated,
    StoryRelation,
    StoryStanding,
    StoryStandingEffect,
    StoryStandingEpisode,
    StorySummaryLine,
)
from ai_assistant.orchestration.planning import PlanningStories, PlanningStory
from ai_assistant.orchestration.story_links import ShortView
from ai_assistant.testing.parties import UNIDENTIFIED_WORDS

if TYPE_CHECKING:
    from ai_assistant.core.types import EpisodicMemory

_TIDIED: Final = _AT - timedelta(days=3)


def _note(note_id: int, text: str, *, outside: bool = False) -> StoryNote:
    return StoryNote(
        note_id=note_id,
        text=text,
        author=StoryNoteAuthor.PLANNING,
        written_during="earlier",
        outside=outside,
        written_at=_AT - timedelta(days=1),
    )


def _lines(*texts: str) -> tuple[StorySummaryLine, ...]:
    return tuple(StorySummaryLine(text=text) for text in texts)


def _standing(story_id: str, **fields: Any) -> StoryStanding:
    return StoryStanding(
        story=StoryHeader(story_id=story_id, created_at=_TIDIED, merged_into=None), **fields
    )


def _moment(activation_id: str, meaning: str, *, outside: bool = False) -> StoryStandingEpisode:
    return StoryStandingEpisode(
        activation_id=activation_id,
        occurred_at=_AT - timedelta(days=1),
        meaning=meaning,
        in_progress=False,
        outside=outside,
    )


def _story(story_id: str = "story:trip", **fields: Any) -> PlanningStory:
    values: dict[str, Any] = {
        "story_id": story_id,
        "tidied_at": _TIDIED,
        "changes": 0,
        "written": True,
        "lines": _lines("A camping trip to Riverside in mid-October."),
    }
    values.update(fields)
    return PlanningStory(**values)


def _short(story_id: str, **fields: Any) -> ShortView:
    values: dict[str, Any] = {
        "story_id": story_id,
        "lines": _lines("Plan our summer."),
        "notes": (),
        "episodes": (),
        "written": True,
    }
    values.update(fields)
    return ShortView(**values)


def _past(activation_id: str) -> EpisodicMemory:
    return _episode(f"activation:{activation_id}")


def _labels(planned: Any) -> dict[str, tuple[LabelKind, str]]:
    return {one.label: (one.kind, one.id) for one in planned.labels}


async def test_each_part_of_a_story_view_is_shown_and_labelled() -> None:
    """§6:1: the summary, what is newer, the tidy-up facts, inherited views and standing."""
    stage, completer, _ = _stage()
    story = _story(
        changes=3,
        notes=(_note(7, "Next: check the dog policy."),),
        newer=(_past("b"),),
        latest=(_past("b"), _past("a")),
        inherited=(_short("story:summer"),),
        standing=_standing(
            "story:trip",
            done=(
                StoryStandingEffect(
                    activation_id="a", state=StoryEffectState.UNKNOWN, at=_AT - timedelta(days=2)
                ),
                StoryStandingEffect(
                    activation_id="b", state=StoryEffectState.DONE, at=_AT - timedelta(days=1)
                ),
            ),
            recent=(_moment("b", "booking the site"), _moment("a", "picking a weekend")),
            related=(
                StoryRelated(
                    relation=StoryRelation.PART_OF, story_id="story:summer", member_count=2
                ),
            ),
        ),
    )

    planned = await stage.plan(_inputs(stories=PlanningStories(stories=(story,))))

    (shown,) = _sent(completer)["stories"]
    assert shown["label"] == "S1"
    assert shown["summary"] == ["A camping trip to Riverside in mid-October."]
    assert "summary_outside_content" not in shown
    assert shown["last_tidied"] == _TIDIED.isoformat()
    assert shown["changes_since_tidied"] == 3
    (note,) = shown["notes_since_tidied"]
    assert (note["label"], note["text"]) == ("N1", "Next: check the dog policy.")
    assert note["written_by"] == "the assistant, while working on this matter"
    (newer,) = shown["episodes_since_tidied"]
    assert newer["label"] == "E1"
    assert "at" in newer
    # An episode already shown whole is named by its label (§5:1).
    assert shown["latest_episodes"][0] == {"label": "E1", "shown": "shown above under this label"}
    assert shown["latest_episodes"][1]["label"] == "E2"
    (parent,) = shown["part_of"]
    assert parent["label"] == "S2"
    assert parent["inherited"] == "a larger matter this story is part of"
    assert parent["summary"] == ["Plan our summer."]
    stands = shown["where_it_stands"]
    assert stands["done"] == [
        {
            "episode": "E2",
            "state": "unknown: it may or may not have happened",
            "at": (_AT - timedelta(days=2)).isoformat(),
        },
        {"episode": "E1", "state": "done", "at": (_AT - timedelta(days=1)).isoformat()},
    ]
    assert [one["episode"] for one in stands["timeline"]] == ["E1", "E2"]
    assert stands["timeline"][0]["understood"] == "booking the site"
    assert stands["related"] == [{"story": "S2", "relation": "part of", "members": 2}]
    # §5:1, §5:7: each thing is labelled on first show, and recorded with the episode.
    assert _labels(planned) == {
        "S1": (LabelKind.STORY, "story:trip"),
        "N1": (LabelKind.NOTE, "7"),
        "E1": (LabelKind.EPISODE, "activation:b"),
        "E2": (LabelKind.EPISODE, "activation:a"),
        "S2": (LabelKind.STORY, "story:summer"),
    }
    assert planned.round.notes_marked is False


async def test_a_story_never_tidied_says_so_and_still_counts_its_changes() -> None:
    stage, completer, _ = _stage()
    story = _story(tidied_at=None, changes=2, written=False, lines=())

    await stage.plan(_inputs(stories=PlanningStories(stories=(story,))))

    (shown,) = _sent(completer)["stories"]
    assert shown["summary"] == "none written yet"
    assert shown["last_tidied"] == "never"
    assert shown["changes_since_tidied"] == 2
    assert shown["notes_since_tidied"] == "none"
    assert shown["episodes_since_tidied"] == "none"
    assert shown["latest_episodes"] == "none shown"


async def test_on_a_pass_that_may_not_show_owner_records_the_view_follows_understandings() -> None:
    """§6:4, ADR-0312 §4: summary withheld and said so, notes absent, tidy-up facts shown.

    The activation's own rounds and their notes are shown to its own planning all the
    same.
    """
    stage, completer, _ = _stage()
    story = _story(
        lines=(),
        withheld=True,
        notes_withheld=True,
        changes=4,
        inherited=(_short("story:summer", lines=(), withheld=True, notes_withheld=True),),
    )

    await stage.plan(
        _inputs(
            owner_records=False,
            rounds=(_earlier(text="Looking.", notes="my own working state"),),
            stories=PlanningStories(stories=(story,)),
        )
    )

    sent = _sent(completer)
    (shown,) = sent["stories"]
    withheld = "withheld: this story has a summary, which this audience may not be shown"
    assert shown["summary"] == withheld
    assert "notes_since_tidied" not in shown
    assert shown["last_tidied"] == _TIDIED.isoformat()
    assert shown["changes_since_tidied"] == 4
    (parent,) = shown["part_of"]
    assert parent["summary"] == withheld
    assert "newest_notes" not in parent
    assert not any("note" in key for key in (*shown, *parent))
    assert sent["rounds"][0]["notes"] == "my own working state"


async def test_a_story_cited_as_a_referent_is_shown_by_its_short_view() -> None:
    """§6:1, ADR-0304 §8: a referent story the activation is not in, by its short view."""
    stage, completer, _ = _stage()
    cited = _short("story:car", lines=_lines("The car repair."), notes=(_note(3, "Garage."),))

    planned = await stage.plan(_inputs(stories=PlanningStories(cited=(cited,))))

    sent = _sent(completer)
    assert sent["stories"] == "none: this activation belongs to no story yet"
    (shown,) = sent["cited_stories"]
    assert shown["label"] == "S1"
    assert "inherited" not in shown
    assert shown["summary"] == ["The car repair."]
    assert [one["text"] for one in shown["newest_notes"]] == ["Garage."]
    assert _labels(planned)["S1"] == (LabelKind.STORY, "story:car")


async def test_unreadable_stories_are_said_to_be_unreadable() -> None:
    stage, completer, _ = _stage()

    await stage.plan(_inputs(stories=PlanningStories(unreadable=True)))

    sent = _sent(completer)
    assert sent["stories"] == "missing: the stories could not be read"
    assert "cited_stories" not in sent


async def test_with_no_story_store_wired_no_stories_section_is_shown() -> None:
    stage, completer, _ = _stage()

    await stage.plan(_inputs())

    assert "stories" not in _sent(completer)


async def test_a_story_labelled_by_understanding_keeps_its_label() -> None:
    """§5:1: a story shown under one label keeps it wherever else it is shown."""
    stage, completer, _ = _stage()
    story = _story(story_id="story:trip")

    await stage.plan(
        _inputs(
            labels=(PlanningLabel(label="S1", kind=LabelKind.STORY, id="story:trip"),),
            stories=PlanningStories(stories=(story,)),
        )
    )

    assert _sent(completer)["stories"][0]["label"] == "S1"


async def test_a_marked_summary_marks_the_rounds_notes() -> None:
    """ADR-0303 §3:6: a marked summary planning reads is outside content it has read."""
    stage, completer, _ = _stage(RoundResponse(text="ok", notes="it moved"))
    story = _story(outside=True)

    planned = await stage.plan(_inputs(stories=PlanningStories(stories=(story,))))

    assert _sent(completer)["stories"][0]["summary_outside_content"].startswith("rests on")
    assert planned.round.notes_marked is True


async def test_a_marked_note_marks_the_rounds_notes() -> None:
    stage, completer, _ = _stage(RoundResponse(text="ok", notes="it moved"))
    story = _story(notes=(_note(1, "The site said Sunday.", outside=True),))

    planned = await stage.plan(_inputs(stories=PlanningStories(stories=(story,))))

    (note,) = _sent(completer)["stories"][0]["notes_since_tidied"]
    assert note["outside_content"].startswith("rests on")
    assert planned.round.notes_marked is True


async def test_a_marked_moment_of_where_it_stands_marks_the_rounds_notes() -> None:
    stage, completer, _ = _stage(RoundResponse(text="ok", notes="it moved"))
    story = _story(
        standing=_standing("story:trip", recent=(_moment("a", "a reply came", outside=True),))
    )

    planned = await stage.plan(_inputs(stories=PlanningStories(stories=(story,))))

    (moment,) = _sent(completer)["stories"][0]["where_it_stands"]["timeline"]
    assert moment["outside_content"].startswith("rests on")
    assert planned.round.notes_marked is True


async def test_an_unmarked_view_leaves_the_rounds_notes_unmarked() -> None:
    stage, _, _ = _stage(RoundResponse(text="ok", notes="nothing outside"))
    story = _story(
        notes=(_note(1, "Mine."),),
        inherited=(_short("story:summer", notes=(_note(2, "Also mine."),)),),
        standing=_standing("story:trip", recent=(_moment("a", "the user asked"),)),
    )

    planned = await stage.plan(_inputs(stories=PlanningStories(stories=(story,))))

    assert planned.round.notes_marked is False


async def test_nothing_done_is_said_and_a_merged_story_names_where_it_went() -> None:
    stage, completer, _ = _stage()
    plain = _story(standing=_standing("story:trip"))
    merged = _story(
        story_id="story:old",
        standing=StoryStanding(
            story=StoryHeader(story_id="story:old", created_at=_TIDIED, merged_into="story:new")
        ),
    )

    await stage.plan(_inputs(stories=PlanningStories(stories=(plain, merged))))

    first, second = _sent(completer)["stories"]
    assert first["where_it_stands"]["done"] == "nothing recorded"
    assert first["where_it_stands"]["timeline"] == "none shown"
    assert second["where_it_stands"] == {"merged_into": "S3"}


async def test_an_outside_episode_in_an_inherited_or_cited_view_marks_the_rounds_notes() -> None:
    """ADR-0303 §3:1-§3:2, ADR-0307 §4:3: an episode whose input came from outside is read.

    Its provenance carries no mark and it holds no digest, so only its origin says so;
    the round's notes are recorded marked.
    """
    outside = _episode("activation:report", parties=UNIDENTIFIED_WORDS)
    for stories in (
        PlanningStories(
            stories=(_story(inherited=(_short("story:summer", episodes=(outside,)),)),)
        ),
        PlanningStories(cited=(_short("story:car", episodes=(outside,)),)),
    ):
        stage, completer, recorder = _stage(RoundResponse(text="ok", notes="from what I saw"))

        await stage.plan(_inputs(stories=stories))

        assert "an outside report" in json.dumps(_sent(completer))
        ((recorded, _),) = recorder.recorded
        assert recorded.notes_marked is True
