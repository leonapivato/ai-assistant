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

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Final

from exchange_support import reported, section, tag
from test_planning import _inputs, _sent, _stage

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


async def _results(
    calls: tuple[ProposedCall, ...], *outcomes: CallOutcome, **fields: Any
) -> list[dict[str, Any]]:
    """What came of one round's ``calls``, as the next round's report shows each.

    ADR-0356 §5:3-§5:4: a call's result reaches the round after it, in its report, never
    the briefing. Each outcome is taken as the first round's, whatever round it names.
    """
    stage, completer, _ = _stage(RoundResponse(calls=calls), RoundResponse())
    inputs = _inputs(**fields)
    planned = await stage.plan(inputs)
    await stage.plan(
        replace(
            inputs,
            work=planned.work,
            rounds=(*inputs.rounds, planned.round),
            labels=(*inputs.labels, *planned.labels),
            outcomes=tuple(replace(one, round_id=planned.round.id) for one in outcomes),
        )
    )
    return reported(completer.calls[1], 0)


def _matters(**fields: Any) -> dict[str, Any]:
    """Inputs of a round offered the calls on running work, with their labels."""
    values: dict[str, Any] = {
        "capabilities": (STOP_ACTIVATION, ANSWER_OFFER),
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

    (listed,) = await _results(
        (ProposedCall(call_id="c1", name="list_tasks", arguments={}),), outcome
    )

    running = listed["result"]["value"]["running"]
    assert running[0] == {
        "episode": running[0]["episode"],
        "place": "the person's Telegram chat",
        "input": running[0]["input"],
        "has_acted": True,
    }
    assert running[0]["episode"].startswith("E")
    assert tag(running[0]["input"], "said").text == "search flats"
    # A task's instruction is withheld: the tag says so, and carries none of it.
    withheld_task = tag(running[1]["input"], "task")
    assert (withheld_task.get("withheld"), withheld_task.text) == ("yes", None)


async def test_an_offer_is_shown_under_the_offering_activations_label() -> None:
    """§7:19: the offered input, as an entry shows input, with the meaning recorded."""
    stage, completer, _ = _stage(RoundResponse(text=""))
    offer = OfferShown(activation_id=_B, input="only two bedrooms", meaning="Only two beds.")

    planned = await stage.plan(_inputs(**_matters(offers=(offer,))))

    shown = tag(section(_sent(completer), "## Concurrent stimuli"), "stimulus", offered="yes")
    assert (shown.get("label") or "").startswith("E")
    assert shown.held("said")[0].text == "only two bedrooms"
    assert shown.held("understood")[0].text == "Only two beds."
    assert any(one.id == f"activation:{_B}" for one in planned.labels)


async def test_an_answer_naming_the_offers_label_maps_to_its_episode() -> None:
    """§7:20, ADR-0307 §5:2: the label maps to the offering activation's episode id."""
    offer = OfferShown(activation_id=_B, input="only two bedrooms", meaning="Only two beds.")
    first, completer, _ = _stage(RoundResponse(text=""))
    await first.plan(_inputs(**_matters(offers=(offer,))))
    label = tag(_sent(completer), "stimulus", offered="yes").get("label")
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
    stage, completer, _ = _stage(RoundResponse(text=""))
    waited = RunningShown(
        activation_id=_A,
        place=_LINE,
        input="book Saturday",
        acted=True,
        parties=OWNERS_WORDS,
    )

    await stage.plan(_inputs(**_matters(waiting=(waited,), declined=((_A, "already booked"),))))

    shown = tag(section(_sent(completer), "## Concurrent stimuli"), "stimulus", waited_on="yes")
    assert shown.get("origin") == "Telegram"
    assert shown.held("said")[0].text == "book Saturday"
    assert shown.get("acted") == "yes"
    assert shown.get("declined") == "already booked"


async def test_earlier_work_is_the_peer_view_read_as_provisional_with_its_marks() -> None:
    """§6:9-§6:13, §7:10: input, meaning as provisional, notes with marks, what it did."""
    stage, completer, _ = _stage(RoundResponse(text="kept"))
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

    shown = tag(section(_sent(completer), "## Short-term memory"), "episode")
    assert shown.get("status") == "ended"
    assert [one.text for one in shown.held("said")] == ["search flats"]
    (doing,) = shown.held("understood")
    assert (doing.text, doing.get("provisional")) == ("Search for flats.", "yes")
    plain, marked = shown.held("notes")
    assert (plain.text, plain.get("outside")) == ("Three in Leith.", None)
    assert (marked.text, marked.get("outside")) == ("x", "yes")
    assert [one.text for one in shown.held("did")] == [
        "the tool remember ran",
        "the tool book may have run; whether it did is not known",
        "sent the message: Searching.",
    ]
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

    shown = tag(section(_sent(completer), "## Short-term memory"), "episode")
    assert [one.text for one in shown.held("did")] == [PEER_COULDNT_FINISH_LINE]
    (received,) = shown.held("input")[0].tags
    assert (received.get("withheld"), received.text) == ("yes", None), "outside: withheld"
    assert shown.held("understood") == []


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
        reason="newer work absorbed it since it was shown, so nothing was stopped",
        peer=PeerShown(activation_id=_B, absorbed_by=_A),
    )
    calls = (
        ProposedCall(call_id="c1", name="stop_activation", arguments={"activation": "E1"}),
        ProposedCall(call_id="c2", name="stop_activation", arguments={"activation": "E2"}),
    )

    done, absorbed = await _results(calls, stopped, refused, **_matters())

    value = tag(done["result"]["value"], "episode")
    assert value.get("stopped_by_this_call") == "yes"
    assert value.get("status") == "ended"
    assert [one.text for one in value.held("did")] == ["the tool remember ran"]
    assert absorbed["absorbed_by"] == value.get("label"), "the absorber, by its label"
    assert absorbed["outcome"] == (
        "not done: newer work absorbed it since it was shown, so nothing was stopped"
    )


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
    calls = tuple(
        ProposedCall(
            call_id=f"c{index}",
            name="answer_offer",
            arguments={"offer": "E1", "take": index != 4},
        )
        for index in range(1, 5)
    )

    withdrawn, limited, taken, declined = (
        tag(one["result"]["value"], "episode")
        for one in await _results(calls, *outcomes, **_matters())
    )
    assert withdrawn.get("answer") == "withdrawn"
    label = withdrawn.get("label")
    assert withdrawn.get("because") == (
        f"{label} was stopped before the answer, so the input it carried is no longer "
        "asked for, and the work that input asked for is not to be done"
    )
    assert [one.text for one in withdrawn.held("understood")] == [
        "Move the floss reminder to 10 PM."
    ]
    assert limited.get("answer") == "declined"
    because = limited.get("because") or ""
    assert "already holds as much input as it may" in because
    assert because.count(limited.get("label") or "-") == 1, "it names the offering work"
    assert [one.text for one in limited.held("understood")] == ["Make it 9 PM."]
    for one in (taken, declined):
        assert set(one.attributes) == {"label", "answer"}, "nothing the hub settled"
        assert one.tags == (), "so no reason, and no meaning"


async def test_the_instruction_is_one_text_whatever_the_work_holds() -> None:
    """ADR-0356 §4:2, §5:2: the instruction takes no flag, so offers, waiting, earlier
    work and the calls on running work change none of it; they reach planning in the
    briefing, and a call a waiting round may not make is refused (§4:5)."""
    plain, plain_completer, _ = _stage(RoundResponse(text=""))
    await plain.plan(_inputs())
    full, full_completer, _ = _stage(RoundResponse(text=""))
    waited = RunningShown(
        activation_id=_A, place=_LINE, input="book Saturday", acted=True, parties=OWNERS_WORDS
    )
    offer = OfferShown(activation_id=_B, input="only two bedrooms", meaning="Only two beds.")
    await full.plan(
        _inputs(
            **_matters(
                offers=(offer,),
                waiting=(waited,),
                earlier_work=(PeerShown(activation_id=_A, view=_view(), ended=True),),
            )
        )
    )
    assert (
        full_completer.last_call.exchange.instruction
        == plain_completer.last_call.exchange.instruction
    )


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
    """What a stop's result shows, beside the stopped work's view, of what it set up."""
    calls = (ProposedCall(call_id="c1", name="stop_activation", arguments={"activation": "E1"}),)
    (call,) = await _results(calls, _stop_shown(set_up), **_matters())
    assert tag(call["result"]["value"], "episode").get("label") == "E1"
    return call["result"]["set_up_still_live"]


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
    assert tag(reminder["carries"], "task").text == "check the project notes"
    assert reminder["set_by"] == "person"
    assert reminder["parent"]["is"].startswith("spawned by")
    hidden = tag(withheld["carries"], "task")
    assert (hidden.get("withheld"), hidden.text) == ("yes", None), "a marked task's (§3:5)"
    assert shown["more_scheduled_not_shown"] == 2
    running, starting = shown["running"]
    assert running["episode"].startswith("E")
    assert "has_acted" in running
    assert starting["scheduled_task"].startswith("T")
    assert starting["status"] == "starting"
    assert shown["more_running_not_shown"] == 1


async def test_a_stop_calls_result_says_when_nothing_it_set_up_is_still_live() -> None:
    """ADR-0352 §3:1: where there is none, the result says so."""
    assert await _set_up_shown(StillLive()) == "nothing it set up is still live"


async def test_a_stop_calls_result_says_when_what_it_set_up_could_not_be_read() -> None:
    """The stop stands, and nothing is claimed of what it set up."""
    assert "could not be read" in await _set_up_shown(StillLive(read=False))


#: ADR-0352 §3:8's line, as it is said now: in the stop's own description, since a rule
#: about one tool is said there (ADR-0357 §7:1).
_WORDS_COVER: Final = "where it is unclear what the words cover, ask which."


async def test_the_words_cover_line_goes_with_the_stop_and_never_in_the_instruction() -> None:
    """ADR-0352 §3:8, ADR-0357 §7:1: offered with the stop, in a waiting round and in any
    other; never in the instruction, which takes no flag (ADR-0356 §4:2)."""
    waited = RunningShown(
        activation_id=_A, place=_LINE, input="book Saturday", acted=True, parties=OWNERS_WORDS
    )
    for fields in ({}, {"waiting": (waited,)}):
        stage, completer, _ = _stage(RoundResponse(text=""))
        await stage.plan(_inputs(**_matters(**fields)))
        (stop,) = (one for one in completer.last_call.tools if one.name == "stop_activation")
        assert stop.description.count(_WORDS_COVER) == 1
        assert _WORDS_COVER not in completer.last_call.exchange.instruction
    stage, completer, _ = _stage(RoundResponse(text=""))
    await stage.plan(_inputs())
    assert all(one.name != "stop_activation" for one in completer.last_call.tools)
    assert _WORDS_COVER not in completer.last_call.exchange.instruction
