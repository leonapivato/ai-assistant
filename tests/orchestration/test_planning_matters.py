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
from datetime import UTC, datetime
from typing import Any, Final

from test_planning import FLAG_ECHO, _earlier, _flags, _inputs, _sent, _stage

from ai_assistant.core.types import (
    PEER_COULDNT_FINISH_LINE,
    ChannelIdentity,
    InputOrigin,
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
from ai_assistant.orchestration.planning import (
    CallOutcome,
    CallOutcomeKind,
    OfferShown,
    PeerShown,
    RunningShown,
)
from ai_assistant.orchestration.task_scheduler import ActivationEntry, TaskListing

_AT: Final = datetime(2026, 10, 21, 9, tzinfo=UTC)
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="ref/42")
_A: Final = "0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11"
_B: Final = "1c9a9f1f-3b6d-4d66-8b7d-7b3d2a1c1e22"


def _text(text: str) -> ProjectedText:
    return ProjectedText(text=text, full_chars=len(text))


def _view(**fields: Any) -> PeerView:
    values: dict[str, Any] = {
        "channel": _LINE,
        "origin": InputOrigin.USER,
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
        origin=InputOrigin.ASSISTANT,
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
        origin=InputOrigin.USER,
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
        origin=InputOrigin.OUTSIDE,
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


async def test_the_sections_appear_only_where_they_apply() -> None:
    """The four flags, each set only for a round its part applies to."""
    stage, completer, _ = _stage(RoundResponse(text=""), prompt=FLAG_ECHO)
    await stage.plan(_inputs())
    assert not {"running_work", "offers", "waiting", "earlier_work"} & _flags(completer)


def test_a_running_entry_round_trips_its_acted_mark_and_origin() -> None:
    """§6:2: the listing carries both; an unknown origin reads as no listing, and one
    recorded before the key reads from its outside mark."""
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
        origin=InputOrigin.ASSISTANT,
    )
    encoded = encode_listing(TaskListing(running=(entry,), listed=True))
    decoded = decode_listing(encoded)
    assert decoded is not None
    assert decoded.running == (entry,)

    assert isinstance(encoded, dict)
    running = dict(encoded["running"][0])
    unknown = {**encoded, "running": [{**running, "origin": "unexpected"}]}
    assert decode_listing(unknown) is None
    legacy = {k: v for k, v in running.items() if k not in {"origin", "acted"}}
    older = decode_listing({**encoded, "running": [{**legacy, "outside": True}]})
    assert older is not None
    assert (older.running[0].origin, older.running[0].acted) == (InputOrigin.OUTSIDE, False)
