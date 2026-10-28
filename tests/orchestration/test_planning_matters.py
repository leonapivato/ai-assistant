"""Planning's half of one matter, one activation: what a round is shown of running work.

ADR-0349 §4:9, §4:11, §6:2, §6:5-§6:10, §7:10, §7:19, §7:26-§7:27, through
:class:`PlanningStage` over a scripted completer, as ``test_planning`` drives it: the
list pull's running part as in-progress entries, the offers open to the round, the work
a waiting round waits on with a decline's reason, the finished work of what the
activation took over or waited on through the peer view, a stop call's and a look-up's
result, a refused stop naming its absorber, and the instruction's sections, each where it
applies.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Final

from test_planning import FLAG_ECHO, _earlier, _flags, _inputs, _sent, _stage

from ai_assistant.core.types import (
    PEER_COULDNT_FINISH_LINE,
    ChannelIdentity,
    PeerEffect,
    PeerNotes,
    PeerView,
    ProcessingReason,
    ProcessingStatus,
    ProjectedText,
    ProposedCall,
    RoundResponse,
    ToolOutcome,
)
from ai_assistant.orchestration.matter_calls import (
    ANSWER_OFFER,
    LOOK_UP_ACTIVATION,
    MATTER_LABEL_ARGUMENTS,
    STOP_ACTIVATION,
)
from ai_assistant.orchestration.matters import NotAsAsked
from ai_assistant.orchestration.planning import (
    CallOutcome,
    CallOutcomeKind,
    OfferShown,
    PeerShown,
    RunningShown,
)
from ai_assistant.orchestration.task_scheduler import (
    ActivationEntry,
    StartingEntry,
    StillLive,
    TaskEntry,
    TaskListing,
)
from ai_assistant.testing.parties import OWNERS_WORDS, UNIDENTIFIED_WORDS

_AT: Final = datetime(2026, 10, 21, 9, tzinfo=UTC)
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="ref/42")
_A: Final = "0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11"
_B: Final = "1c9a9f1f-3b6d-4d66-8b7d-7b3d2a1c1e22"


def _text(text: str) -> ProjectedText:
    return ProjectedText(text=text, full_chars=len(text))


def _view(**fields: Any) -> PeerView:
    values: dict[str, Any] = {
        "channel": _LINE,
        "parties": OWNERS_WORDS,
        "input": _text("search flats"),
        "meaning": "Search for flats.",
        "notes": (PeerNotes(notes=_text("Three in Leith.")),),
        "did": (PeerEffect(outcome=ToolOutcome.SUCCEEDED, capability="remember"),),
    }
    values.update(fields)
    return PeerView(**values)


def _matters(**fields: Any) -> dict[str, Any]:
    """Inputs of a round offered the calls on running work, with their labels."""
    values: dict[str, Any] = {
        "capabilities": (STOP_ACTIVATION, LOOK_UP_ACTIVATION, ANSWER_OFFER),
        "label_arguments": MATTER_LABEL_ARGUMENTS,
    }
    values.update(fields)
    return values


async def test_the_list_pulls_running_part_is_the_in_progress_entries() -> None:
    """§6:2, §5:6: under its episode label, what caused it, its input, whether it acted."""
    entry = ActivationEntry(
        activation_id=_A,
        started="Mon 26 Oct 2026 09:00",
        place="the person's Telegram chat",
        status="running",
        input="search flats",
        outside=False,
        acted=True,
    )
    withheld = ActivationEntry(
        activation_id=_B,
        started="",
        place="the schedule",
        status="running",
        input=None,
        outside=False,
        assistants=True,
    )
    outcome = CallOutcome(
        "round:earlier",
        "c1",
        CallOutcomeKind.DONE,
        result_id="result:1",
        tasks=TaskListing(running=(entry, withheld), listed=True),
    )
    stage, completer, _ = _stage(RoundResponse(text=""))
    earlier = _earlier(calls=(ProposedCall(call_id="c1", name="list_tasks", arguments={}),))

    await stage.plan(_inputs(rounds=(earlier,), outcomes=(outcome,)))

    running = _sent(completer)["rounds"][0]["calls"][0]["result"]["value"]["running"]
    assert running[0] == {
        "episode": running[0]["episode"],
        "place": "the person's Telegram chat",
        "input": "search flats",
        "has_acted": True,
    }
    assert running[0]["episode"].startswith("E")
    assert "scheduled" in running[1]["input"], "a task's instruction is withheld, said why"


async def test_an_offer_is_shown_under_the_offering_activations_label() -> None:
    """§7:19: the offered input, as an entry shows input, with the meaning recorded."""
    stage, completer, _ = _stage(RoundResponse(text=""), prompt=FLAG_ECHO)
    offer = OfferShown(activation_id=_B, input="only two bedrooms", meaning="Only two beds.")

    planned = await stage.plan(_inputs(**_matters(offers=(offer,))))

    (shown,) = json.loads(completer.last_call.messages[1].content)["offers"]
    assert shown["offer"].startswith("E")
    assert (shown["input"], shown["understood_as"]) == ("only two bedrooms", "Only two beds.")
    assert {"offers", "running_work"} <= _flags(completer)
    assert any(one.id == f"activation:{_B}" for one in planned.labels)


async def test_an_answer_naming_the_offers_label_maps_to_its_episode() -> None:
    """§7:20, ADR-0307 §5:2: the label maps to the offering activation's episode id."""
    offer = OfferShown(activation_id=_B, input="only two bedrooms", meaning="Only two beds.")
    first, completer, _ = _stage(RoundResponse(text=""))
    await first.plan(_inputs(**_matters(offers=(offer,))))
    label = json.loads(completer.last_call.messages[1].content)["offers"][0]["offer"]
    answering, _, _ = _stage(
        RoundResponse(
            calls=(
                ProposedCall(
                    call_id="c1", name="answer_offer", arguments={"offer": label, "take": True}
                ),
            )
        )
    )

    planned = await answering.plan(_inputs(**_matters(offers=(offer,))))

    (call,) = planned.calls
    assert call.call.arguments["offer"] == f"activation:{_B}"


async def test_a_waiting_round_is_shown_what_it_waits_on_and_why_it_was_declined() -> None:
    """§7:23, §7:26: each as an entry shows it, and the decline's reason."""
    stage, completer, _ = _stage(RoundResponse(text=""), prompt=FLAG_ECHO)
    waited = RunningShown(
        activation_id=_A,
        place=_LINE,
        input="book Saturday",
        acted=True,
        parties=OWNERS_WORDS,
    )

    await stage.plan(_inputs(**_matters(waiting=(waited,), declined=((_A, "already booked"),))))

    (shown,) = json.loads(completer.last_call.messages[1].content)["waiting_on"]
    assert shown["place"] == "telegram:ref/42"
    assert (shown["input"], shown["has_acted"]) == ("book Saturday", True)
    assert shown["declined_this_input"] == "already booked"
    assert "waiting" in _flags(completer)


async def test_earlier_work_is_the_peer_view_read_as_provisional_with_its_marks() -> None:
    """§6:9-§6:13, §7:10: input, meaning as provisional, notes with marks, what it did."""
    stage, completer, _ = _stage(RoundResponse(text="", notes="kept"), prompt=FLAG_ECHO)
    view = _view(
        notes=(PeerNotes(notes=_text("Three in Leith.")), PeerNotes(notes=_text("x"), marked=True)),
        did=(
            PeerEffect(outcome=ToolOutcome.SUCCEEDED, capability="remember"),
            PeerEffect(outcome=ToolOutcome.INDETERMINATE, capability="book"),
            PeerEffect(outcome=ToolOutcome.SUCCEEDED, message=_text("Searching.")),
        ),
    )

    planned = await stage.plan(
        _inputs(earlier_work=(PeerShown(activation_id=_A, view=view, ended=True),))
    )

    (shown,) = json.loads(completer.last_call.messages[1].content)["earlier_work"]
    assert shown["status"] == "ended"
    assert shown["input"] == "search flats"
    assert shown["doing"].startswith("provisional")
    assert shown["found"][0] == {"notes": "Three in Leith."}
    assert "outside_content" in shown["found"][1]
    assert shown["did"] == [
        "the tool remember ran",
        "the tool book may have run; whether it did is not known",
        "sent the message: Searching.",
    ]
    assert "earlier_work" in _flags(completer)
    assert planned.round.notes_marked, "a marked note read marks the round's notes"


async def test_a_failed_activations_couldnt_finish_is_a_fixed_line() -> None:
    """§6:9, §1:5's case: nothing else of what it did is shown."""
    stage, completer, _ = _stage(RoundResponse(text=""))
    view = _view(
        input=None,
        parties=UNIDENTIFIED_WORDS,
        meaning=None,
        notes=(),
        did=(PeerEffect(outcome=ToolOutcome.SUCCEEDED, couldnt_finish=True),),
        status=ProcessingStatus.FAILED,
        reason=ProcessingReason.PROCESSING_FAILED,
    )

    await stage.plan(_inputs(earlier_work=(PeerShown(activation_id=_A, view=view, ended=True),)))

    (shown,) = json.loads(completer.last_call.messages[1].content)["earlier_work"]
    assert shown["did"] == [PEER_COULDNT_FINISH_LINE]
    assert "outside" in shown["input"]
    assert "doing" not in shown


async def test_a_stop_calls_result_and_a_refusal_naming_its_absorber() -> None:
    """§4:9, §4:11: the stopped work through the peer view; the absorber by its label."""
    stopped = CallOutcome(
        "round:earlier",
        "c1",
        CallOutcomeKind.DONE,
        result_id="result:1",
        peer=PeerShown(activation_id=_A, view=_view(), ended=True, stopped=True),
    )
    refused = CallOutcome(
        "round:earlier",
        "c2",
        CallOutcomeKind.NOT_DONE,
        reason="not done: newer work absorbed it since it was shown, so nothing was stopped",
        peer=PeerShown(activation_id=_B, absorbed_by=_A),
    )
    earlier = _earlier(
        calls=(
            ProposedCall(call_id="c1", name="stop_activation", arguments={"activation": "E1"}),
            ProposedCall(call_id="c2", name="stop_activation", arguments={"activation": "E2"}),
        )
    )
    stage, completer, _ = _stage(RoundResponse(text=""))

    await stage.plan(_inputs(**_matters(rounds=(earlier,), outcomes=(stopped, refused))))

    done, absorbed = _sent(completer)["rounds"][0]["calls"]
    value = done["result"]["value"]
    assert value["stopped_by_this_call"] is True
    assert value["status"] == "ended"
    assert value["did"] == ["the tool remember ran"]
    assert absorbed["absorbed_by"].startswith("E")
    assert "absorbed" in absorbed["outcome"]


def _answered(call_id: str, activation_id: str, **fields: Any) -> CallOutcome:
    return CallOutcome(
        "round:earlier",
        call_id,
        CallOutcomeKind.DONE,
        result_id=f"result:{call_id}",
        peer=PeerShown(activation_id=activation_id, **fields),
    )


async def test_an_answers_result_says_why_the_hub_settled_it_so() -> None:
    """ADR-0349 §7:22-§7:23, ADR-0352 §4:2, #3471, #3477: a withdrawal and a refusal at
    the limit each carry their reason, naming the offering work by its label and the
    input it carried by its meaning; a take, and a decline planning chose, carry none."""
    outcomes = (
        _answered(
            "c1",
            _A,
            answered="withdrawn",
            not_as_asked=NotAsAsked.STOPPED,
            meaning="Move the floss reminder to 10 PM.",
        ),
        _answered(
            "c2",
            _B,
            answered="declined",
            not_as_asked=NotAsAsked.AT_LIMIT,
            meaning="Make it 9 PM.",
        ),
        _answered("c3", _A, answered="taken", meaning="Move it."),
        _answered("c4", _B, answered="declined", meaning="Move it."),
    )
    earlier = _earlier(
        calls=tuple(
            ProposedCall(
                call_id=f"c{index}",
                name="answer_offer",
                arguments={"offer": "E1", "take": index != 4},
            )
            for index in range(1, 5)
        )
    )
    stage, completer, _ = _stage(RoundResponse(text=""))

    await stage.plan(_inputs(**_matters(rounds=(earlier,), outcomes=outcomes)))

    withdrawn, limited, taken, declined = (
        one["result"]["value"] for one in _sent(completer)["rounds"][0]["calls"]
    )
    assert withdrawn["answer"] == "withdrawn"
    label = withdrawn["episode"]
    assert withdrawn["because"] == (
        f"{label} was stopped before the answer, so the input it carried is no longer "
        "asked for, and the work that input asked for is not to be done"
    )
    assert withdrawn["understood_as"] == "Move the floss reminder to 10 PM."
    assert limited["answer"] == "declined"
    assert "already holds as much input as it may" in limited["because"]
    assert limited["because"].count(limited["episode"]) == 1, "it names the offering work"
    assert limited["understood_as"] == "Make it 9 PM."
    for one in (taken, declined):
        assert set(one) == {"episode", "answer"}, "nothing the hub settled, so no reason"


async def test_the_sections_appear_only_where_they_apply() -> None:
    """The four flags, each set only for a round its part applies to."""
    stage, completer, _ = _stage(RoundResponse(text=""), prompt=FLAG_ECHO)
    await stage.plan(_inputs())
    assert not {"running_work", "offers", "waiting", "earlier_work"} & _flags(completer)


def test_a_running_entry_round_trips_its_acted_mark_and_whose_input_it_is() -> None:
    """§6:2: the listing carries both; one recorded with the retired origin key reads an
    assistant's input from it, and one recorded before either reads as not the
    assistant's (ADR-0351 §8:1)."""
    from ai_assistant.orchestration.task_scheduler import (  # noqa: PLC0415 — this case's
        decode_listing,
        encode_listing,
    )

    entry = ActivationEntry(
        activation_id=_A,
        started="",
        place="the schedule",
        status="running",
        input=None,
        outside=False,
        acted=True,
        assistants=True,
    )
    encoded = encode_listing(TaskListing(running=(entry,), listed=True))
    decoded = decode_listing(encoded)
    assert decoded is not None
    assert decoded.running == (entry,)

    assert isinstance(encoded, dict)
    running = dict(encoded["running"][0])
    unknown = {**encoded, "running": [{**running, "assistants": "unexpected"}]}
    assert decode_listing(unknown) is None
    legacy = {k: v for k, v in running.items() if k not in {"assistants", "acted"}}
    assert decode_listing({**encoded, "running": [{**legacy, "origin": "unexpected"}]}) is None
    retired = decode_listing({**encoded, "running": [{**legacy, "origin": "assistant"}]})
    assert retired is not None
    assert (retired.running[0].assistants, retired.running[0].acted) == (True, False)
    older = decode_listing({**encoded, "running": [{**legacy, "outside": True}]})
    assert older is not None
    assert (older.running[0].assistants, older.running[0].outside) == (False, True)


def _stop_shown(set_up: StillLive) -> CallOutcome:
    return CallOutcome(
        "round:earlier",
        "c1",
        CallOutcomeKind.DONE,
        result_id="result:1",
        peer=PeerShown(activation_id=_A, view=_view(), ended=True, stopped=True, set_up=set_up),
    )


async def _set_up_shown(set_up: StillLive) -> Any:
    earlier = _earlier(
        calls=(ProposedCall(call_id="c1", name="stop_activation", arguments={"activation": "E1"}),)
    )
    stage, completer, _ = _stage(RoundResponse(text=""))
    await stage.plan(_inputs(**_matters(rounds=(earlier,), outcomes=(_stop_shown(set_up),))))
    (call,) = _sent(completer)["rounds"][0]["calls"]
    return call["result"]["value"]["set_up_still_live"]


async def test_a_stop_calls_result_lists_what_the_work_set_up_that_is_still_live() -> None:
    """ADR-0352 §3:1, §3:3-§3:6: tasks by T label, running work by E, starting by T."""
    task = TaskEntry(
        task_id="task:reminder",
        state="pending",
        falls_due="Mon 26 Oct 2026 10:00 (UTC)",
        instruction="check the project notes",
        outside=False,
        places=(),
        parent=_A,
        parent_text="spawned by the person's message in the person's Telegram chat",
        author="person",
    )
    marked = replace(task, task_id="task:marked", instruction=None, outside=True)
    running = ActivationEntry(
        activation_id=_B,
        started="",
        place="the schedule",
        status="running",
        input=None,
        outside=False,
        assistants=True,
    )
    left = StillLive(
        tasks=(task, marked),
        more_tasks=2,
        activations=(running, StartingEntry(task_id="task:gather")),
        more_activations=1,
    )

    shown = await _set_up_shown(left)

    reminder, withheld = shown["scheduled"]
    assert reminder["label"].startswith("T")
    assert reminder["falls_due"] == "Mon 26 Oct 2026 10:00 (UTC)"
    assert reminder["carries"] == "check the project notes"
    assert reminder["set_by"] == "person"
    assert reminder["parent"]["is"].startswith("spawned by")
    assert "outside" in withheld["carries"], "a marked task's text is withheld (§3:5)"
    assert shown["more_scheduled_not_shown"] == 2
    step, starting = shown["running"]
    assert step["episode"].startswith("E")
    assert "has_acted" in step
    assert starting == {"scheduled_task": starting["scheduled_task"], "status": "starting"}
    assert starting["scheduled_task"].startswith("T")
    assert shown["more_running_not_shown"] == 1


async def test_a_stop_calls_result_says_when_nothing_it_set_up_is_still_live() -> None:
    """ADR-0352 §3:1: where there is none, the result says so."""
    assert await _set_up_shown(StillLive()) == "nothing it set up is still live"


async def test_a_stop_calls_result_says_when_what_it_set_up_could_not_be_read() -> None:
    """The stop stands, and nothing is claimed of what it set up."""
    shown = await _set_up_shown(StillLive(read=False))
    assert "could not be read" in shown


#: ADR-0352 §3:8's line, as the prompts front routed it (§3:10).
_WORDS_COVER: Final = (
    "Stop or cancel exactly what the person's words cover: each piece of running work and "
    "each task they cover, by the labels you were shown, including those a stop's result "
    "lists. Keep the rest, and where it is unclear what the words cover, ask which."
)


def _instruction(**flags: bool) -> str:
    from ai_assistant.orchestration.planning import PLANNING_PROMPT  # noqa: PLC0415
    from ai_assistant.testing.prompts import default_prompt  # noqa: PLC0415 — this case's

    every = dict.fromkeys(PLANNING_PROMPT.flags, False) | flags
    values = {
        "approved_action_tool": "approved_action",
        "note_reliance_capability": "note_reliance",
        "needs_your_yes": "needs your yes",
    }
    return default_prompt(PLANNING_PROMPT).render(flags=every, values=values)


def test_the_words_cover_line_renders_once_wherever_the_stop_is_offered() -> None:
    """ADR-0352 §3:8: once, in a waiting round and in any other, and never without it."""
    for waiting in (False, True):
        assert _instruction(running_work=True, waiting=waiting).count(_WORDS_COVER) == 1
    assert _WORDS_COVER not in _instruction(running_work=False)
    assert _WORDS_COVER not in _instruction(running_work=False, waiting=True)
