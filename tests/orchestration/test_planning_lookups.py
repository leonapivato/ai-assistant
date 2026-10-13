"""How planning is shown what it looked up for itself (ADR-0307 §6:6, ADR-0308 §6).

Driven directly over the planning stage, each outcome built by hand as the phases' glue
hands it over: a memory search's records under their own M labels with its outside part
read by a digest, a story's full view with its marks, and a follow-up's digest told apart
by the question it answered.
"""

from __future__ import annotations

import pytest
from test_planning import _earlier, _inputs, _remembered, _sent, _stage
from test_planning_stories import _note, _story

from ai_assistant.core.types import (
    LabelKind,
    MemorySource,
    PlanningLabel,
    ProposedCall,
    RoundResponse,
)
from ai_assistant.orchestration.planning import (
    CallOutcome,
    CallOutcomeKind,
    DigestedEvidence,
    DigestItem,
)


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

    request = completer.last_call.messages[1].content
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
    stage, completer, _ = _stage(RoundResponse(text="ok", notes="Saturday it is"))

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
    stage, _, _ = _stage(RoundResponse(text="ok", notes="Saturday it is"))

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
