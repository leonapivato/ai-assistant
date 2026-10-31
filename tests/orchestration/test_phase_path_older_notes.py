"""A story read shows the notes a tidy-up took in, so a move or a split can carry them (#2893).

Planning names the notes a move or a split carries by the labels it was shown them under
(ADR-0307 §5:5), and the views it is given each round show only a story's notes newer
than its summary. A story read's full view also shows the story's older notes, newest
first a page at a time, each under its own ``N`` label (§5:1), so planning can read a
story and move any note it holds. These cases drive the phase path over fakes, as
#2893's scenario does: a read, then a move or a split naming what the read showed.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Final

from test_authorizer import _ACTIVATION
from test_authorizer import _episode as _own_episode
from test_engine import AT
from test_engine_phases import _SETTLE, _call, _Given, _harness, _phases
from test_phase_path_outside_grounds import _book, _grounds, _rounds
from test_phase_path_outside_grounds import _Given as _DiagnosedGiven
from test_phase_path_outside_grounds import _path as _diagnosed_path
from test_planning import _episode as _past_episode
from test_planning import _recorded_trigger

from ai_assistant.core.types import (
    ControllerStage,
    LabelKind,
    PlanningLabel,
    RoundResponse,
    StageOutcome,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    StorySummaryDraft,
    StorySummaryLine,
)
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.lookups import OLDER_NOTES_PAGE
from ai_assistant.orchestration.understanding import TranscriptWindow
from ai_assistant.testing import FakeDiagnosticSink, FakeStoryStore, FakeToolCallingCompleter

if TYPE_CHECKING:
    from ai_assistant.core.types import ProposedCall
    from ai_assistant.orchestration.phase_path import PhasePath, PhaseWorking

#: One planning round, then authorizing and acting on it.
_ROUND: Final = (ControllerStage.PLANNING, ControllerStage.AUTHORIZING, ControllerStage.ACTING)


async def _story(stories: FakeStoryStore, member: str) -> str:
    created = await stories.create(
        [StoryMember(kind=StoryMemberKind.ACTIVATION, id=member)], actor=StoryActor.OWNER
    )
    assert created.story_id is not None
    return created.story_id


async def _noted(
    stories: FakeStoryStore, story_id: str, text: str, *, outside: bool = False
) -> int:
    written = await stories.append_note(
        story_id, text, author=StoryNoteAuthor.PLANNING, written_during="past", outside=outside
    )
    assert written.note is not None
    return int(written.note.note_id)


async def _tidied(stories: FakeStoryStore, story_id: str) -> None:
    """Write a summary taking in every note pending on the story now."""
    state = await stories.current_summary(story_id)
    assert state is not None
    draft = StorySummaryDraft(
        lines=(StorySummaryLine(text="A trip to Porto."),),
        took_in_notes=tuple(note.note_id for note in state.pending_notes),
        outside=False,
    )
    assert (await stories.write_summary(story_id, draft, as_of=state.as_of)).refusal is None


async def _texts(stories: FakeStoryStore, story_id: str) -> list[str]:
    page = await stories.notes(story_id)
    assert page is not None
    return [note.text for note in page.notes]


def _shown(*labels: tuple[str, LabelKind, str]) -> tuple[PlanningLabel, ...]:
    return tuple(PlanningLabel(label=label, kind=kind, id=one) for label, kind, one in labels)


async def _run(
    stories: FakeStoryStore,
    *calls: ProposedCall,
    labels: tuple[PlanningLabel, ...],
    owner_records: bool = True,
    read_back: bool = False,
) -> tuple[PhaseWorking, FakeToolCallingCompleter]:
    """Plan, authorize and act one round per call, over the story calls and the look-ups.

    ``read_back`` plans one round more, which is shown what the last call returned.
    """
    completer = FakeToolCallingCompleter.scripted(
        *(RoundResponse(calls=(one,)) for one in calls), RoundResponse(text="Done.")
    )
    harness = _harness(completer)
    await harness.memory.add(_own_episode())
    await harness.memory.add(_past_episode("activation:past"))
    await harness.memory.add(_past_episode("activation:other"))
    path: PhasePath = _phases(completer, stories=stories, story_calls=True, look_ups=True)(harness)
    working = path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel("c1"), messages=()),
        conversation_id="c1",
        trigger=_recorded_trigger(),
        owner_records=owner_records,
        labels=labels,
    )
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)
    stages = {one.name: one for one in path.stages()}
    for _ in calls:
        for stage in _ROUND:
            assert (await stages[stage].run(given)).outcome is StageOutcome.DONE
    if read_back:
        planning = stages[ControllerStage.PLANNING]
        assert (await planning.run(given)).outcome is StageOutcome.DONE
    return working, completer


async def test_a_note_a_tidy_up_took_in_is_read_then_moved_by_its_label() -> None:
    """#2893's scenario: the Dana note, taken in by a tidy-up, moved back by its label.

    The read shows the trip's older notes, newest first: the car inspection as N1, the
    Dana note as N2. The move names N2, and the store moves that note, and that note only.
    """
    stories = FakeStoryStore(now=lambda: AT)
    trip = await _story(stories, "past")
    car = await _story(stories, "past")
    dana = await _noted(stories, trip, "Dana is driving us to Porto.")
    inspection = await _noted(stories, trip, "The car inspection is due before the trip.")
    await _tidied(stories, trip)

    working, _ = await _run(
        stories,
        _call("c1", "read_story", story="S1"),
        _call("c2", "move_story", story="S1", to="S2", notes=["N2"]),
        labels=_shown(("S1", LabelKind.STORY, trip), ("S2", LabelKind.STORY, car)),
    )

    (view,) = working.pages.values()
    assert view.older is not None
    assert [note.note_id for note in view.older] == [inspection, dana]
    assert not working.latest.planned.refused
    assert await _texts(stories, trip) == ["The car inspection is due before the trip."]
    assert await _texts(stories, car) == ["Dana is driving us to Porto."]


async def test_a_note_on_a_later_page_is_read_then_split_off_by_its_label() -> None:
    """Paging past the first page: the read naming page 2 shows the oldest note.

    The split names it by the label the read showed it under, beside the activation
    that leaves with it, and the new story holds both.
    """
    stories = FakeStoryStore(now=lambda: AT)
    created = await stories.create(
        [
            StoryMember(kind=StoryMemberKind.ACTIVATION, id="past"),
            StoryMember(kind=StoryMemberKind.ACTIVATION, id="other"),
        ],
        actor=StoryActor.OWNER,
    )
    trip = created.story_id
    assert trip is not None
    first = await _noted(stories, trip, "The car inspection is due.")
    for n in range(OLDER_NOTES_PAGE):
        await _noted(stories, trip, f"Packing list item {n}.")
    await _tidied(stories, trip)

    working, completer = await _run(
        stories,
        _call("c1", "read_story", story="S1", older_notes_page=2),
        _call("c2", "split_story", story="S1", episodes=["E1"], notes=["N1"]),
        labels=_shown(("S1", LabelKind.STORY, trip), ("E1", LabelKind.EPISODE, "activation:other")),
    )

    (view,) = working.pages.values()
    assert view.older is not None
    assert [note.note_id for note in view.older] == [first]
    assert (view.older_page, view.older_more) == (2, 0)
    # The page shown is the second: the oldest note, and nothing more beyond it.
    assert "more_older_notes" not in completer.calls[1].exchange.briefing
    assert not working.latest.planned.refused
    (split,) = await stories.stories_of(StoryMember(kind=StoryMemberKind.ACTIVATION, id="other"))
    assert split.story_id != trip
    assert await _texts(stories, str(split.story_id)) == ["The car inspection is due."]
    assert "The car inspection is due." not in await _texts(stories, trip)


async def test_on_a_pass_that_may_not_show_owner_records_a_read_shows_no_older_note() -> None:
    """ADR-0307 §6:4, ADR-0305 §4: absent with nothing said, as every story note is."""
    stories = FakeStoryStore(now=lambda: AT)
    trip = await _story(stories, "past")
    await _noted(stories, trip, "Dana is driving us to Porto.")
    await _tidied(stories, trip)

    working, completer = await _run(
        stories,
        _call("c1", "read_story", story="S1"),
        labels=_shown(("S1", LabelKind.STORY, trip)),
        owner_records=False,
        read_back=True,
    )

    (view,) = working.pages.values()
    assert view.notes_withheld
    assert view.older is None
    # The round after the read is shown its result: the story, and nothing of its notes.
    (call,) = json.loads(completer.last_call.exchange.briefing)["rounds"][0]["calls"]
    shown = call["result"]["value"]
    assert shown["label"] == "S1"
    assert not {"notes_since_tidied", "older_notes", "more_older_notes"} & set(shown)
    assert "Dana" not in completer.last_call.exchange.briefing


async def test_a_marked_older_note_a_read_shows_is_named_once_in_authorizings_grounds() -> None:
    """R2/F6: a marked older note read is outside content, counted as a newer one is.

    The note was taken in by a tidy-up, so only the read shows it; the next authorizing
    entry names it once, by its id, and the round that read it is marked.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "read_story", story="S1"),)),
        RoundResponse(calls=(_book(),), text="the venue answered"),
    )
    harness = _harness(completer)
    await harness.memory.add(_own_episode())
    await harness.memory.add(_past_episode("activation:past"))
    stories = FakeStoryStore(now=lambda: AT)
    trip = await _story(stories, "past")
    note = await _noted(stories, trip, "The venue says Saturday.", outside=True)
    await _tidied(stories, trip)
    sink = FakeDiagnosticSink()
    path = _diagnosed_path(completer, harness, sink, stories, look_ups=True)
    working = path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel("c1"), messages=()),
        conversation_id="c1",
        trigger=_recorded_trigger(),
        owner_records=True,
        labels=_shown(("S1", LabelKind.STORY, trip)),
    )
    given = _DiagnosedGiven(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)

    await _rounds(path, given, *_ROUND, ControllerStage.PLANNING, ControllerStage.AUTHORIZING)

    (view,) = working.pages.values()
    assert view.notes == ()
    assert view.older is not None
    assert [one.note_id for one in view.older] == [note]
    (_, marked) = working.planning_rounds()
    assert marked.notes_marked
    assert _grounds(sink) == [
        [],
        [
            {"ground": "fetched_outside", "record": str(note)},
            {"ground": "notes_marked", "record": marked.id},
            {"ground": "note_shown_marked", "record": str(note)},
        ],
    ]
    assert list(working.fetched_outside_from) == [str(note)]
