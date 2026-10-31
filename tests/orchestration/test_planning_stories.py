"""What planning is shown of stories, and how it renders them (ADR-0307 §6:1, §6:3-§6:4).

Driven directly over the planning stage, with the views built by hand as the phases'
glue would hand them over; ``test_phase_path_stories`` reads them from the stores.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from exchange_support import Tag, section, tag, tags
from test_planning import _AT, _episode, _inputs, _recorded_trigger, _sent, _stage

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
from ai_assistant.orchestration.planning import NOTE_REASONS, PlanningStories, PlanningStory
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


def _matters(completer: Any) -> str:
    """The briefing's matters section (ADR-0356 §3:1)."""
    return section(_sent(completer), "### Matters")


def _matter(completer: Any, label: str = "S1") -> Tag:
    """One top-level matter of the matters section, by its label."""
    (shown,) = [one for one in tags(_matters(completer)) if one.get("label") == label]
    return shown


def _lines_of(completer: Any) -> list[str]:
    """The lines between the matters section's tags: where each matter stands."""
    return [line for line in _matters(completer).split("\n") if line.startswith("- ")]


#: The work's stimulus is the owner's own words, so a round's notes are marked by the
#: matters it was shown alone (ADR-0356 §3:8, §9:6).
_OWNERS: Final = _recorded_trigger()


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

    planned = await stage.plan(_inputs(trigger=_OWNERS, stories=PlanningStories(stories=(story,))))

    shown = _matter(completer)
    assert shown.get("last_tidied") == "Thu 8 Oct 2026, 12:00 pm"
    assert shown.get("changes_since") == "3"
    (summary,) = [one for one in shown.tags if one.name == "summary"]
    assert summary.get("from") == "the system"
    assert summary.text == "A camping trip to Riverside in mid-October."
    assert summary.get("outside") is None
    (note,) = shown.held("note")
    assert (note.get("label"), note.text) == ("N1", "Next: check the dog policy.")
    assert note.get("from") == "the system"
    # The episode newer than the tidy-up is shown once, marked so; a latest episode it
    # already shows is not shown again (§5:1).
    episodes = [one for one in shown.tags if one.name == "episode"]
    assert [(one.get("label"), one.get("since_tidied")) for one in episodes] == [
        ("E1", "yes"),
        ("E2", None),
    ]
    assert all(one.get("at") for one in episodes)
    (parent,) = [one for one in shown.tags if one.name == "matter"]
    assert (parent.get("label"), parent.get("inherited")) == ("S2", "yes")
    assert tag(parent.text or "", "summary").text == "Plan our summer."
    stands = _lines_of(completer)
    assert stands[0] == (
        "- What was done in S1: E2 (unknown: it may or may not have happened, "
        "Fri 9 Oct 2026, 12:00 pm); E1 (done, Sat 10 Oct 2026, 12:00 pm)."
    )
    timeline = tags(_matters(completer), "latest")
    assert [one.get("episode") for one in timeline] == ["E1", "E2"]
    assert timeline[0].text == "booking the site"
    assert "- S1 is part of S2, with 2 members." in stands
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

    shown = _matter(completer)
    assert shown.get("last_tidied") == "never"
    assert shown.get("changes_since") == "2"
    (summary,) = shown.tags
    assert (summary.name, summary.get("written"), summary.text) == ("summary", "not yet", None)
    # No note, no episode: nothing renders where there is none.
    assert shown.held("note") == []
    assert shown.held("episode") == []


async def test_on_a_pass_that_may_not_show_owner_records_the_view_follows_understandings() -> None:
    """§6:4, ADR-0312 §4: summary withheld and said so, notes absent, tidy-up facts shown."""
    stage, completer, _ = _stage()
    story = _story(
        lines=(),
        withheld=True,
        notes_withheld=True,
        changes=4,
        inherited=(_short("story:summer", lines=(), withheld=True, notes_withheld=True),),
    )

    await stage.plan(_inputs(owner_records=False, stories=PlanningStories(stories=(story,))))

    shown = _matter(completer)
    summary = next(one for one in shown.tags if one.name == "summary")
    assert (summary.get("withheld"), summary.text) == ("yes", None)
    assert shown.get("last_tidied") == "Thu 8 Oct 2026, 12:00 pm"
    assert shown.get("changes_since") == "4"
    (parent,) = [one for one in shown.tags if one.name == "matter"]
    assert [(one.name, one.get("withheld")) for one in parent.tags] == [("summary", "yes")]
    assert shown.held("note") == []
    assert "older_notes" not in shown.attributes


async def test_a_story_cited_as_a_referent_is_shown_by_its_short_view() -> None:
    """§6:1, ADR-0304 §8: a referent story the activation is not in, by its short view."""
    stage, completer, _ = _stage()
    cited = _short("story:car", lines=_lines("The car repair."), notes=(_note(3, "Garage."),))

    planned = await stage.plan(_inputs(stories=PlanningStories(cited=(cited,))))

    (shown,) = tags(_matters(completer))
    assert shown.name == "matter"
    # A short view: no tidy-up facts, which only a story the activation is in shows.
    assert shown.attributes == {"label": "S1"}
    assert tag(shown.text or "", "summary").text == "The car repair."
    assert [one.text for one in shown.held("note")] == ["Garage."]
    assert _labels(planned)["S1"] == (LabelKind.STORY, "story:car")


async def test_unreadable_stories_are_said_to_be_unreadable() -> None:
    stage, completer, _ = _stage()

    await stage.plan(_inputs(stories=PlanningStories(unreadable=True)))

    shown = _matters(completer)
    assert shown.startswith(NOTE_REASONS[4])
    assert tags(shown) == []


async def test_with_no_story_store_wired_no_stories_section_is_shown() -> None:
    """ADR-0356 §4:1: the section is rendered all the same, its note saying none is held."""
    stage, completer, _ = _stage()

    await stage.plan(_inputs())

    shown = _matters(completer)
    assert shown.startswith(NOTE_REASONS[3])
    assert tags(shown) == []


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

    assert [one.get("label") for one in tags(_matters(completer))] == ["S1"]


async def test_a_marked_summary_marks_the_rounds_notes() -> None:
    """ADR-0303 §3:6: a marked summary planning reads is outside content it has read."""
    stage, completer, _ = _stage(RoundResponse(text="ok"))
    story = _story(outside=True)

    planned = await stage.plan(_inputs(trigger=_OWNERS, stories=PlanningStories(stories=(story,))))

    assert tag(_matters(completer), "summary").get("outside") == "yes"
    assert planned.round.notes_marked is True


async def test_a_marked_note_marks_the_rounds_notes() -> None:
    stage, completer, _ = _stage(RoundResponse(text="ok"))
    story = _story(notes=(_note(1, "The site said Sunday.", outside=True),))

    planned = await stage.plan(_inputs(trigger=_OWNERS, stories=PlanningStories(stories=(story,))))

    assert tag(_matters(completer), "note").get("outside") == "yes"
    assert planned.round.notes_marked is True


async def test_a_marked_moment_of_where_it_stands_marks_the_rounds_notes() -> None:
    stage, completer, _ = _stage(RoundResponse(text="ok"))
    story = _story(
        standing=_standing("story:trip", recent=(_moment("a", "a reply came", outside=True),))
    )

    planned = await stage.plan(_inputs(trigger=_OWNERS, stories=PlanningStories(stories=(story,))))

    assert tag(_matters(completer), "latest").get("outside") == "yes"
    assert planned.round.notes_marked is True


async def test_an_unmarked_view_leaves_the_rounds_notes_unmarked() -> None:
    stage, _, _ = _stage(RoundResponse(text="ok"))
    story = _story(
        notes=(_note(1, "Mine."),),
        inherited=(_short("story:summer", notes=(_note(2, "Also mine."),)),),
        standing=_standing("story:trip", recent=(_moment("a", "the user asked"),)),
    )

    planned = await stage.plan(_inputs(trigger=_OWNERS, stories=PlanningStories(stories=(story,))))

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

    assert [one.get("label") for one in tags(_matters(completer))] == ["S1", "S2"]
    stands = _lines_of(completer)
    assert stands == ["- What was done in S1: nothing recorded.", "- S2 was merged into S3."]
    # No timeline is shown where none is recorded.
    assert tags(_matters(completer), "latest") == []


async def test_an_outside_episode_in_an_inherited_or_cited_view_marks_the_rounds_notes() -> None:
    """ADR-0303 §3:1-§3:2, ADR-0307 §4:3: an episode whose input came from outside is read.

    Its provenance carries no mark and it holds no digest, so only its origin says so;
    the round's notes are recorded marked, and its words are withheld (ADR-0356 §3:6).
    """
    outside = _episode("activation:report", parties=UNIDENTIFIED_WORDS)
    for stories in (
        PlanningStories(
            stories=(_story(inherited=(_short("story:summer", episodes=(outside,)),)),)
        ),
        PlanningStories(cited=(_short("story:car", episodes=(outside,)),)),
    ):
        stage, completer, recorder = _stage(RoundResponse(text="ok"))

        await stage.plan(_inputs(trigger=_OWNERS, stories=stories))

        episode = tag(_matters(completer), "episode")
        assert episode.get("outside") == "yes"
        (received,) = episode.held("received")
        assert (received.get("withheld"), received.text) == ("yes", None)
        assert "the words they wrote" not in _matters(completer)
        ((recorded, _),) = recorder.recorded
        assert recorded.notes_marked is True
