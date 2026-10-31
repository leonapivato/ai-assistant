"""How planning is shown what it looked up for itself (ADR-0307 §6:6, ADR-0308 §6).

Driven directly over the planning stage, each outcome built by hand as the phases' glue
hands it over: a memory search's records under their own M labels with its outside part
read by a digest, a story's full view with its marks, and a follow-up's digest told apart
by the question it answered. A look-up's result reaches the round after the one that
called it, in that round's report (ADR-0356 §5:3-§5:4).
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from exchange_support import Tag, reported, section, tag, tags
from test_planning import _inputs, _remembered, _sent, _stage
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
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.orchestration.planning import PlannedRound, PlanningStory
    from ai_assistant.testing import FakeToolCallingCompleter

#: What came of a round's calls, built from that round's id.
type _Outcomes = Callable[[str], tuple[CallOutcome, ...]]


def _search(call_id: str = "c1") -> ProposedCall:
    return ProposedCall(call_id=call_id, name="search_memory", arguments={"query": "dentist"})


async def _reported(
    calls: tuple[ProposedCall, ...],
    outcomes: _Outcomes,
    *,
    later: dict[str, Any] | None = None,
    **fields: Any,
) -> tuple[FakeToolCallingCompleter, PlannedRound]:
    """A round that proposes ``calls``, then the next, reported what came of them.

    Args:
        calls: The first round's calls.
        outcomes: What came of them, from the first round's id.
        later: Inputs the second round holds beside the first's.
        **fields: The first round's inputs.

    Returns:
        The completer, and the second round as planned.
    """
    stage, completer, _ = _stage(RoundResponse(calls=calls), RoundResponse(text="ok"))
    inputs = _inputs(**fields)
    first = await stage.plan(inputs)
    planned = await stage.plan(
        replace(
            inputs,
            work=first.work,
            rounds=(first.round,),
            labels=first.labels,
            outcomes=outcomes(first.round.id),
            **(later or {}),
        )
    )
    return completer, planned


def _result(completer: FakeToolCallingCompleter) -> dict[str, Any]:
    """The one result the second round's report holds, decoded."""
    (shown,) = reported(completer.last_call)
    result: dict[str, Any] = shown["result"]
    return result


def _view(completer: FakeToolCallingCompleter) -> Tag:
    """The matter a story read's result shows (ADR-0300 §10:6)."""
    return tag(_result(completer)["value"], "matter")


async def test_a_searchs_records_are_shown_under_their_own_m_labels() -> None:
    """ADR-0308 §3:3, §4:15: each record not outside under its M label, never an outside one.

    Its outside records went to a digest, which the result says; a record whose current
    version rests on outside content is withheld, as a found one is.
    """
    said = _remembered("said", MemorySource.USER_ASSERTED, "dentist with Dr Rao")
    turned = _remembered("turned", MemorySource.EXTERNAL, "dentist moved to 3pm")

    completer, planned = await _reported(
        (_search(),),
        lambda round_id: (
            CallOutcome(
                round_id,
                "c1",
                CallOutcomeKind.DONE,
                result_id="result:search",
                digested=True,
                records=(said, turned),
            ),
        ),
    )

    result = _result(completer)
    assert result["label"] == "R1"
    value = result["value"]
    remembered = [tag(one, "memory") for one in value["remembered"]]
    assert [(one.get("label"), one.text) for one in remembered] == [("M1", "dentist with Dr Rao")]
    assert value["resting_on_outside_content"] == "read for you by a digest, under evidence"
    report = completer.last_call.exchange.steps[-1].report
    assert "moved to 3pm" not in "\n".join(one.text for one in report.results)
    assert planned.labels == (
        PlanningLabel(label="R1", kind=LabelKind.RESULT, id="result:search"),
        PlanningLabel(label="M1", kind=LabelKind.MEMORY, id="said"),
    )


async def test_a_search_that_found_nothing_shown_says_so() -> None:
    completer, _ = await _reported(
        (_search(),),
        lambda round_id: (
            CallOutcome(
                round_id, "c1", CallOutcomeKind.DONE, result_id="result:search", records=()
            ),
        ),
    )

    assert _result(completer)["value"] == {"remembered": "none"}


_READ: ProposedCall = ProposedCall(call_id="c1", name="read_story", arguments={"story": "S1"})


def _read(view: PlanningStory) -> _Outcomes:
    """A story read, done, its full view ``view``."""
    return lambda round_id: (
        CallOutcome(round_id, "c1", CallOutcomeKind.DONE, result_id="result:page", story=view),
    )


async def test_a_storys_full_view_is_shown_under_the_result_with_its_marks() -> None:
    """ADR-0300 §10:6: a story read's lines with their marks; a marked one is read.

    The view is rendered as a story view is, its notes under N labels, and the round's
    notes are marked, since planning read a marked note (ADR-0307 §4:3).
    """
    view = _story(notes=(_note(4, "the venue wrote back: Saturday", outside=True),))

    completer, planned = await _reported((_READ,), _read(view))

    assert _result(completer)["label"] == "R1"
    shown = _view(completer)
    assert shown.get("label") == "S1"
    assert tag(shown.text or "", "summary").text == "A camping trip to Riverside in mid-October."
    (note,) = shown.held("note")
    assert (note.get("label"), note.get("outside")) == ("N1", "yes")
    assert planned.round.notes_marked
    assert PlanningLabel(label="N1", kind=LabelKind.NOTE, id="4") in planned.labels


async def test_an_unmarked_full_view_marks_nothing() -> None:
    view = _story(notes=(_note(4, "they prefer Saturdays"),))

    _, planned = await _reported((_READ,), _read(view))

    assert not planned.round.notes_marked


async def test_a_follow_ups_digest_is_told_apart_by_the_question_it_answered() -> None:
    """ADR-0308 §6:7: the same result, read again against the follow-up's question.

    Each result resting on outside content is its digest's evidence (ADR-0356 §5:4), each
    digest told apart by what it looked for; a recall digest, of no result, is news.
    """
    item = DigestItem("open until dusk", LabelKind.RESULT, "result:1")
    evidence = (
        DigestedEvidence("result:1", answered=True, question="is it open"),
        DigestedEvidence("result:1", answered=True, items=(item,), question="until when"),
        DigestedEvidence(None, answered=True),
    )

    completer, _ = await _reported(
        (
            ProposedCall(call_id="c1", name="web_search", arguments={"query": "trail"}),
            ProposedCall(call_id="c2", name="follow_up", arguments={"result": "R1"}),
        ),
        lambda round_id: (
            CallOutcome(round_id, "c1", CallOutcomeKind.DONE, result_id="result:1", digested=True),
            CallOutcome(round_id, "c2", CallOutcomeKind.DONE, result_id="result:1", digested=True),
        ),
        later={"evidence": evidence},
    )

    first, follow_up = reported(completer.last_call)
    assert (
        first["result"]
        == follow_up["result"]
        == {"label": "R1", "value": "read for you by a digest, under evidence"}
    )
    # Each digest goes to one call: the search's first, the follow-up's after it.
    (asked,) = first["evidence"]
    (again,) = follow_up["evidence"]
    assert asked.startswith("- A digest of R1, looking for is it open:")
    assert again.startswith("- What a digest read of R1, looking for until when,")
    (read,) = tags(again, "evidence")
    assert (read.text, read.get("source"), read.get("outside")) == ("open until dusk", "R1", "yes")
    news = completer.last_call.exchange.steps[-1].report.news
    (recalled,) = [line for line in news.split("\n") if "the outside memories recall found" in line]
    assert "looking for" not in recalled


def test_a_looked_up_result_is_shown_only_under_its_id_and_as_itself() -> None:
    with pytest.raises(ValueError, match="minted"):
        CallOutcome("r", "c1", CallOutcomeKind.DONE, records=())
    with pytest.raises(ValueError, match="minted"):
        CallOutcome("r", "c1", CallOutcomeKind.DONE, story=_story())
    with pytest.raises(ValueError, match="looked up"):
        CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", result="raw", story=_story())


# --- a story read's older notes (#2893) ------------------------------------------------------


def _older(shown: Tag) -> list[Tag]:
    """The older notes a story read's view lists: those a tidy-up took in."""
    return [one for one in shown.held("note") if one.get("taken_in") == "yes"]


def _newer(shown: Tag) -> list[Tag]:
    """The notes newer than the summary a view lists."""
    return [one for one in shown.held("note") if one.get("taken_in") is None]


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

    completer, planned = await _reported((_READ,), _read(view))

    shown = _view(completer)
    assert [one.get("label") for one in _newer(shown)] == ["N1"]
    assert [(one.get("label"), one.text) for one in _older(shown)] == [
        ("N2", "the car inspection is due"),
        ("N3", "Dana is driving"),
    ]
    assert shown.get("more_older") == (
        "4 older not shown: read the story again with older_notes_page 3 for the next page"
    )
    labels = {(one.label, one.id) for one in planned.labels if one.kind is LabelKind.NOTE}
    assert labels == {("N1", "9"), ("N2", "7"), ("N3", "3")}
    assert not planned.round.notes_marked


async def test_a_marked_older_note_is_outside_content_read() -> None:
    """ADR-0303 §3:6: a marked older note is rendered as a marked note is, and read."""
    view = _story(older=(_note(3, "the venue wrote back: Saturday", outside=True),))

    completer, planned = await _reported((_READ,), _read(view))

    (note,) = _older(_view(completer))
    assert note.get("outside") == "yes"
    assert planned.round.notes_marked


async def test_a_note_shown_in_both_lists_keeps_one_label() -> None:
    """ADR-0307 §5:1: a note keeps the label it was first shown under, wherever shown."""
    same = _note(4, "they prefer Saturdays")

    completer, _ = await _reported((_READ,), _read(_story(notes=(same,), older=(same,))))

    shown = _view(completer)
    assert _newer(shown)[0].get("label") == _older(shown)[0].get("label") == "N1"


async def test_a_read_page_with_no_older_note_says_so_and_offers_no_more() -> None:
    completer, _ = await _reported((_READ,), _read(_story(older=())))

    shown = _view(completer)
    assert shown.get("older_notes") == "none on this page"
    assert _older(shown) == []
    assert "more_older" not in shown.attributes


async def test_where_no_note_may_be_shown_a_read_says_nothing_of_older_notes() -> None:
    """ADR-0307 §6:4, ADR-0305 §4: absent, with nothing said, as every story note is."""
    completer, _ = await _reported(
        (_READ,), _read(_story(notes_withheld=True, older=(), older_more=3))
    )

    shown = _view(completer)
    assert shown.held("note") == []
    assert not {"older_notes", "more_older"} & set(shown.attributes)


async def test_the_view_planning_is_given_each_round_shows_no_older_notes() -> None:
    """#2893: the default view stays the summary and what is newer than it."""
    stories = PlanningStories(stories=(_story(notes=(_note(4, "they prefer Saturdays"),)),))
    stage, completer, _ = _stage()

    await stage.plan(_inputs(stories=stories))

    (shown,) = tags(section(_sent(completer), "### Matters"))
    assert [one.name for one in shown.tags] == ["summary", "note"]
    assert _older(shown) == []
    assert set(shown.attributes) == {"label", "last_tidied", "changes_since"}


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

_CUE = "older_notes"
_CUE_TEXT = "read the story to see them by their labels"
_STORY_READS = (*STORY_CALLS, READ_STORY)


def _matter(completer: FakeToolCallingCompleter) -> Tag:
    (shown,) = tags(section(_sent(completer), "### Matters"))
    return shown


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

    Where no note may be shown the notes part says nothing of notes (ADR-0305 §4), so
    neither does this.
    """
    stage, completer, _ = _stage()

    await stage.plan(
        _inputs(capabilities=_STORY_READS, stories=PlanningStories(stories=(_story(**fields),)))
    )

    assert _matter(completer).get(_CUE) == (_CUE_TEXT if cued else None)


async def test_no_view_points_at_a_story_read_where_none_is_offered() -> None:
    """#2944: the cue is shown only where a story read is offered, as the procedure is."""
    stage, completer, _ = _stage()

    await stage.plan(
        _inputs(capabilities=STORY_CALLS, stories=PlanningStories(stories=(_story(),)))
    )

    assert _CUE not in _matter(completer).attributes


async def test_a_story_reads_own_view_lists_the_older_notes_and_points_nowhere() -> None:
    """#2944: a read's view lists the older notes itself, so it carries no cue."""
    completer, _ = await _reported(
        (_READ,),
        _read(_story(older=(_note(7, "the car inspection is due"),))),
        capabilities=_STORY_READS,
    )

    shown = _view(completer)
    assert [one.text for one in _older(shown)] == ["the car inspection is due"]
    assert shown.get(_CUE) is None


async def test_two_follow_ups_each_take_the_digest_of_their_own_question() -> None:
    """ADR-0308 §6:7, ADR-0356 §5:4: digests matched by question, whatever their order."""
    later = DigestItem("open until dusk", LabelKind.RESULT, "result:1")
    early = DigestItem("open now", LabelKind.RESULT, "result:1")
    evidence = (
        DigestedEvidence("result:1", answered=True, items=(later,), question="until when"),
        DigestedEvidence("result:1", answered=True, items=(early,), question="is it open"),
    )

    def follow(call_id: str, question: str) -> ProposedCall:
        return ProposedCall(
            call_id=call_id, name="follow_up", arguments={"result": "R1", "looking_for": question}
        )

    completer, _ = await _reported(
        (follow("c1", "is it open"), follow("c2", "until when")),
        lambda round_id: (
            CallOutcome(round_id, "c1", CallOutcomeKind.DONE, result_id="result:1", digested=True),
            CallOutcome(round_id, "c2", CallOutcomeKind.DONE, result_id="result:1", digested=True),
        ),
        later={"evidence": evidence},
    )

    first, second = reported(completer.last_call)
    assert [one.text for one in tags(first["evidence"][0], "evidence")] == ["open now"]
    assert [one.text for one in tags(second["evidence"][0], "evidence")] == ["open until dusk"]


async def test_two_follow_ups_asking_alike_each_take_one_digest_in_order() -> None:
    """Two calls asking one question of one result: one digest each, in call order."""
    one = DigestItem("first read", LabelKind.RESULT, "result:1")
    two = DigestItem("second read", LabelKind.RESULT, "result:1")
    evidence = (
        DigestedEvidence("result:1", answered=True, items=(one,), question="hours"),
        DigestedEvidence("result:1", answered=True, items=(two,), question="hours"),
    )
    calls = tuple(
        ProposedCall(
            call_id=call_id, name="follow_up", arguments={"result": "R1", "looking_for": "hours"}
        )
        for call_id in ("c1", "c2")
    )

    completer, _ = await _reported(
        calls,
        lambda round_id: tuple(
            CallOutcome(
                round_id, call_id, CallOutcomeKind.DONE, result_id="result:1", digested=True
            )
            for call_id in ("c1", "c2")
        ),
        later={"evidence": evidence},
    )

    first, second = reported(completer.last_call)
    assert [one.text for one in tags(first["evidence"][0], "evidence")] == ["first read"]
    assert [one.text for one in tags(second["evidence"][0], "evidence")] == ["second read"]
