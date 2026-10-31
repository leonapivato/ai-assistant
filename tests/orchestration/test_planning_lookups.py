"""How planning is shown what it looked up for itself (ADR-0307 §6:6, ADR-0308 §6).

Driven directly over the planning stage, each outcome built by hand as the phases' glue
hands it over: a memory search's records under their own M labels with its outside part
read by a digest, a story's full view with its marks, and a follow-up's digest told apart
by the question it answered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from test_planning import FLAG_ECHO, _earlier, _echoed, _inputs, _remembered, _sent, _stage
from test_planning_stories import _note, _story
from test_story_tidy_up import _note as _tidy_note
from test_story_tidy_up import _reply, _summary, _tidy_up, _trip
from test_story_tidy_up import _story as _tidy_story

from ai_assistant.core.types import (
    LabelKind,
    MemorySource,
    PlanningLabel,
    ProposedCall,
    RoundResponse,
    StoryActor,
)
from ai_assistant.orchestration.lookups import READ_STORY
from ai_assistant.orchestration.planning import (
    CallOutcome,
    CallOutcomeKind,
    DigestedEvidence,
    DigestItem,
    PlanningStories,
)
from ai_assistant.orchestration.story_calls import STORY_CALLS
from ai_assistant.orchestration.story_tidy_up import TidyUpResult
from ai_assistant.testing import FakeDiagnosticSink, FakeModelProvider

if TYPE_CHECKING:
    from ai_assistant.core.types import PlanningRound
    from ai_assistant.orchestration.planning import PlanningStory


def _search(call_id: str = "c1") -> ProposedCall:
    return ProposedCall(call_id=call_id, name="search_memory", arguments={"query": "dentist"})


async def test_a_searchs_records_are_shown_under_their_own_m_labels() -> None:
    """ADR-0308 §3:3, §4:15: each record not outside under its M label, never an outside one.

    Its outside records went to a digest, which the result says; a record whose current
    version rests on outside content is withheld, as a found one is.
    """
    earlier = _earlier(calls=(_search(),))
    said = _remembered("said", MemorySource.USER_ASSERTED, "dentist with Dr Rao")
    turned = _remembered("turned", MemorySource.EXTERNAL, "dentist moved to 3pm")
    outcome = CallOutcome(
        earlier.id,
        "c1",
        CallOutcomeKind.DONE,
        result_id="result:search",
        digested=True,
        records=(said, turned),
    )
    stage, completer, _ = _stage()

    planned = await stage.plan(_inputs(rounds=(earlier,), outcomes=(outcome,)))

    request = completer.last_call.exchange.briefing
    (call,) = _sent(completer)["rounds"][0]["calls"]
    assert call["result"]["label"] == "R1"
    value = call["result"]["value"]
    assert [(one["label"], one["fact"]) for one in value["remembered"]] == [
        ("M1", "dentist with Dr Rao")
    ]
    assert value["resting_on_outside_content"] == "read for you by a digest, under evidence"
    assert "moved to 3pm" not in request
    assert planned.labels == (
        PlanningLabel(label="R1", kind=LabelKind.RESULT, id="result:search"),
        PlanningLabel(label="M1", kind=LabelKind.MEMORY, id="said"),
    )


async def test_a_search_that_found_nothing_shown_says_so() -> None:
    earlier = _earlier(calls=(_search(),))
    outcome = CallOutcome(
        earlier.id, "c1", CallOutcomeKind.DONE, result_id="result:search", records=()
    )
    stage, completer, _ = _stage()

    await stage.plan(_inputs(rounds=(earlier,), outcomes=(outcome,)))

    (call,) = _sent(completer)["rounds"][0]["calls"]
    assert call["result"]["value"] == {"remembered": "none"}


async def test_a_storys_full_view_is_shown_under_the_result_with_its_marks() -> None:
    """ADR-0300 §10:6: a story read's lines with their marks; a marked one is read.

    The view is rendered as a story view is, its notes under N labels, and the round's
    notes are marked, since planning read a marked note (ADR-0307 §4:3).
    """
    earlier = _earlier(
        calls=(ProposedCall(call_id="c1", name="read_story", arguments={"story": "S1"}),)
    )
    view = _story(notes=(_note(4, "the venue wrote back: Saturday", outside=True),))
    outcome = CallOutcome(
        earlier.id, "c1", CallOutcomeKind.DONE, result_id="result:page", story=view
    )
    stage, completer, _ = _stage(RoundResponse(text="ok"))

    planned = await stage.plan(_inputs(rounds=(earlier,), outcomes=(outcome,)))

    (call,) = _sent(completer)["rounds"][0]["calls"]
    shown = call["result"]["value"]
    assert call["result"]["label"] == "R1"
    assert shown["label"] == "S1"
    assert shown["summary"] == ["A camping trip to Riverside in mid-October."]
    (note,) = shown["notes_since_tidied"]
    assert note["label"] == "N1"
    assert "outside_content" in note
    assert planned.round.notes_marked
    assert PlanningLabel(label="N1", kind=LabelKind.NOTE, id="4") in planned.labels


async def test_an_unmarked_full_view_marks_nothing() -> None:
    earlier = _earlier(
        calls=(ProposedCall(call_id="c1", name="read_story", arguments={"story": "S1"}),)
    )
    view = _story(notes=(_note(4, "they prefer Saturdays"),))
    outcome = CallOutcome(
        earlier.id, "c1", CallOutcomeKind.DONE, result_id="result:page", story=view
    )
    stage, _, _ = _stage(RoundResponse(text="ok"))

    planned = await stage.plan(_inputs(rounds=(earlier,), outcomes=(outcome,)))

    assert not planned.round.notes_marked


async def test_a_follow_ups_digest_is_told_apart_by_the_question_it_answered() -> None:
    """ADR-0308 §6:7: the same result, read again against the follow-up's question."""
    earlier = _earlier(
        calls=(
            ProposedCall(call_id="c1", name="web_search", arguments={"query": "trail"}),
            ProposedCall(call_id="c2", name="follow_up", arguments={"result": "R1"}),
        )
    )
    outcomes = (
        CallOutcome(earlier.id, "c1", CallOutcomeKind.DONE, result_id="result:1", digested=True),
        CallOutcome(earlier.id, "c2", CallOutcomeKind.DONE, result_id="result:1", digested=True),
    )
    item = DigestItem("open until dusk", LabelKind.RESULT, "result:1")
    evidence = (
        DigestedEvidence("result:1", answered=True, question="is it open"),
        DigestedEvidence("result:1", answered=True, items=(item,), question="until when"),
        DigestedEvidence(None, answered=True),
    )
    stage, completer, _ = _stage()

    await stage.plan(_inputs(rounds=(earlier,), outcomes=outcomes, evidence=evidence))

    sent = _sent(completer)
    first, follow_up = (call["result"] for call in sent["rounds"][0]["calls"])
    assert (
        first
        == follow_up
        == {
            "label": "R1",
            "value": "read for you by a digest, under evidence",
        }
    )
    asked, again, recalled = sent["evidence"]
    assert (asked["digest_of"], asked["looking_for"]) == ("R1", "is it open")
    assert (again["digest_of"], again["looking_for"]) == ("R1", "until when")
    assert again["digest"]["evidence"][0]["text"] == "open until dusk"
    assert "looking_for" not in recalled


def test_a_looked_up_result_is_shown_only_under_its_id_and_as_itself() -> None:
    with pytest.raises(ValueError, match="minted"):
        CallOutcome("r", "c1", CallOutcomeKind.DONE, records=())
    with pytest.raises(ValueError, match="minted"):
        CallOutcome("r", "c1", CallOutcomeKind.DONE, story=_story())
    with pytest.raises(ValueError, match="looked up"):
        CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", result="raw", story=_story())


# --- a story read's older notes (#2893) ------------------------------------------------------


def _read(view: PlanningStory) -> tuple[PlanningRound, CallOutcome]:
    """An earlier round's story read, done, its full view ``view``."""
    earlier = _earlier(
        calls=(ProposedCall(call_id="c1", name="read_story", arguments={"story": "S1"}),)
    )
    return earlier, CallOutcome(
        earlier.id, "c1", CallOutcomeKind.DONE, result_id="result:page", story=view
    )


async def test_a_story_reads_older_notes_are_shown_each_under_its_own_n_label() -> None:
    """#2893: the notes a tidy-up took in, in the order read, newest first, labelled.

    Each is labelled as any note planning is shown is (ADR-0307 §5:1), so a move or a
    split can name it; the page says how many older ones it does not show, and how to
    read them.
    """
    view = _story(
        notes=(_note(9, "the dog's vet visit is Friday"),),
        older=(_note(7, "the car inspection is due"), _note(3, "Dana is driving")),
        older_page=2,
        older_more=4,
    )
    earlier, outcome = _read(view)
    stage, completer, _ = _stage()

    planned = await stage.plan(_inputs(rounds=(earlier,), outcomes=(outcome,)))

    (call,) = _sent(completer)["rounds"][0]["calls"]
    shown = call["result"]["value"]
    assert [one["label"] for one in shown["notes_since_tidied"]] == ["N1"]
    assert [(one["label"], one["text"]) for one in shown["older_notes"]] == [
        ("N2", "the car inspection is due"),
        ("N3", "Dana is driving"),
    ]
    assert shown["more_older_notes"] == (
        "4 older not shown: read the story again with older_notes_page 3 for the next page"
    )
    labels = {(one.label, one.id) for one in planned.labels if one.kind is LabelKind.NOTE}
    assert labels == {("N1", "9"), ("N2", "7"), ("N3", "3")}
    assert not planned.round.notes_marked


async def test_a_marked_older_note_is_outside_content_read() -> None:
    """ADR-0303 §3:6: a marked older note is rendered as a marked note is, and read."""
    view = _story(older=(_note(3, "the venue wrote back: Saturday", outside=True),))
    earlier, outcome = _read(view)
    stage, completer, _ = _stage(RoundResponse(text="ok"))

    planned = await stage.plan(_inputs(rounds=(earlier,), outcomes=(outcome,)))

    (call,) = _sent(completer)["rounds"][0]["calls"]
    (note,) = call["result"]["value"]["older_notes"]
    assert "outside_content" in note
    assert planned.round.notes_marked


async def test_a_note_shown_in_both_lists_keeps_one_label() -> None:
    """ADR-0307 §5:1: a note keeps the label it was first shown under, wherever shown."""
    same = _note(4, "they prefer Saturdays")
    earlier, outcome = _read(_story(notes=(same,), older=(same,)))
    stage, completer, _ = _stage()

    await stage.plan(_inputs(rounds=(earlier,), outcomes=(outcome,)))

    (call,) = _sent(completer)["rounds"][0]["calls"]
    shown = call["result"]["value"]
    assert shown["notes_since_tidied"][0]["label"] == shown["older_notes"][0]["label"] == "N1"


async def test_a_read_page_with_no_older_note_says_so_and_offers_no_more() -> None:
    earlier, outcome = _read(_story(older=()))
    stage, completer, _ = _stage()

    await stage.plan(_inputs(rounds=(earlier,), outcomes=(outcome,)))

    (call,) = _sent(completer)["rounds"][0]["calls"]
    shown = call["result"]["value"]
    assert shown["older_notes"] == "none on this page"
    assert "more_older_notes" not in shown


async def test_where_no_note_may_be_shown_a_read_says_nothing_of_older_notes() -> None:
    """ADR-0307 §6:4, ADR-0305 §4: absent, with nothing said, as every story note is."""
    earlier, outcome = _read(_story(notes_withheld=True, older=(), older_more=3))
    stage, completer, _ = _stage()

    await stage.plan(_inputs(rounds=(earlier,), outcomes=(outcome,)))

    (call,) = _sent(completer)["rounds"][0]["calls"]
    shown = call["result"]["value"]
    assert not {"notes_since_tidied", "older_notes", "more_older_notes"} & set(shown)


async def test_the_view_planning_is_given_each_round_shows_no_older_notes() -> None:
    """#2893: the default view stays the summary and what is newer than it."""
    stories = PlanningStories(stories=(_story(notes=(_note(4, "they prefer Saturdays"),)),))
    stage, completer, _ = _stage()

    await stage.plan(_inputs(stories=stories))

    (shown,) = _sent(completer)["stories"]
    assert set(shown) == {
        "label",
        "summary",
        "last_tidied",
        "changes_since_tidied",
        "notes_since_tidied",
        "episodes_since_tidied",
        "latest_episodes",
    }


@pytest.mark.parametrize("reads", [True, False], ids=["read_offered", "no_read"])
async def test_the_template_is_handed_story_reads_where_a_story_read_is_offered(
    reads: bool,
) -> None:
    """ADR-0334 §4:2; #2893, #2944: the code computes it from what the round offers.

    ``story_calls`` beside it, since the story calls are offered either way, so the
    template can say a story read shows older notes beside them.
    """
    sink = FakeDiagnosticSink()
    stage, completer, _ = _stage(prompt=FLAG_ECHO, diagnostics=sink)
    inputs = _inputs(capabilities=(*STORY_CALLS, *((READ_STORY,) if reads else ())))

    flags = await _echoed(stage, completer, sink, inputs)

    assert "story_calls" in flags
    assert ("story_reads" in flags) is reads


async def test_a_note_moved_away_leaves_the_story_it_left_nothing_to_tidy_until_noted() -> None:
    """#2944: the premise of the procedure's last step, over the canonical fakes.

    A note a tidy-up took in, moved to another story, leaves nothing pending on the story
    it left, so tidying that story reads nothing and its summary keeps the line. A note
    there saying where the matter went is what the next tidy-up reads, and it rewrites.
    """
    stories, memory, trip = await _trip()
    car = await _tidy_story(stories, "a-2")
    inspection = await _tidy_note(stories, trip, "The car's inspection is due before Porto.")
    first = FakeModelProvider(_reply(["Porto trip.", "Car inspection before departure."]))
    assert (await _tidy_up(first, stories, memory).run(trip)).result is TidyUpResult.WRITTEN

    moved = await stories.move(trip, car, actor=StoryActor.PLANNING, notes=(inspection,))
    assert moved.refusal is None
    idle = FakeModelProvider(_reply(["unused"]))
    left = await _tidy_up(idle, stories, memory).run(trip)

    assert left.result is TidyUpResult.NOTHING_TO_READ
    assert idle.calls == []
    assert await _summary(stories, trip) == ["Porto trip.", "Car inspection before departure."]

    await _tidy_note(stories, trip, "The car's inspection now lives with the car story.")
    second = FakeModelProvider(_reply(["Porto trip."]))
    noted = await _tidy_up(second, stories, memory).run(trip)

    assert noted.result is TidyUpResult.WRITTEN
    assert await _summary(stories, trip) == ["Porto trip."]


# --- a tidied story's summary points at the story read (#2944) ---------------------------------

_CUE = "summary_built_from"
_STORY_READS = (*STORY_CALLS, READ_STORY)


@pytest.mark.parametrize(
    ("fields", "cued"),
    [
        ({}, True),
        ({"tidied_at": None, "written": False, "lines": ()}, False),
        ({"notes_withheld": True}, False),
    ],
    ids=["tidied", "never_tidied", "notes_withheld"],
)
async def test_a_tidied_storys_view_says_a_read_lists_any_notes_its_summary_came_from(
    fields: dict[str, Any], cued: bool
) -> None:
    """#2944: beside the summary of a story a tidy-up has written, never otherwise.

    It says "may": a summary can be built from episodes alone, and the view does not say
    which. Where no note may be shown the notes part says nothing of notes (ADR-0305 §4),
    so neither does this.
    """
    stage, completer, _ = _stage()

    await stage.plan(
        _inputs(capabilities=_STORY_READS, stories=PlanningStories(stories=(_story(**fields),)))
    )

    (shown,) = _sent(completer)["stories"]
    assert (_CUE in shown) is cued
    if cued:
        assert shown[_CUE] == (
            "what tidy-ups took in, which may include older notes: read the story to see any "
            "by their labels"
        )
        assert list(shown).index(_CUE) == list(shown).index("summary") + 1


async def test_no_view_points_at_a_story_read_where_none_is_offered() -> None:
    """#2944: the cue is shown only where a story read is offered, as the procedure is."""
    stage, completer, _ = _stage()

    await stage.plan(
        _inputs(capabilities=STORY_CALLS, stories=PlanningStories(stories=(_story(),)))
    )

    (shown,) = _sent(completer)["stories"]
    assert _CUE not in shown


async def test_a_story_reads_own_view_lists_the_older_notes_and_points_nowhere() -> None:
    """#2944: a read's view lists the older notes itself, so it carries no cue."""
    earlier, outcome = _read(_story(older=(_note(7, "the car inspection is due"),)))
    stage, completer, _ = _stage()

    await stage.plan(_inputs(capabilities=_STORY_READS, rounds=(earlier,), outcomes=(outcome,)))

    (call,) = _sent(completer)["rounds"][0]["calls"]
    shown = call["result"]["value"]
    assert "older_notes" in shown
    assert _CUE not in shown
