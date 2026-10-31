"""Planning's half of the Task Scheduler: the place list, the labels, the message's place.

ADR-0350 §5:10-§5:13, §6:7, §9:2, §12:8, through :class:`PlanningStage` over a scripted
completer, as ``test_planning`` drives it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from exchange_support import reported, section, tag, tags
from test_planning import _inputs, _sent, _stage

from ai_assistant.core.types import (
    ChannelIdentity,
    LabelKind,
    ProposedCall,
    RoundResponse,
)
from ai_assistant.orchestration.message_tools import TEXT_CALL
from ai_assistant.orchestration.planning import (
    CallOutcome,
    CallOutcomeKind,
    PlaceAuthor,
    PlaceItem,
    PlaceWindow,
    RefusedCall,
)
from ai_assistant.orchestration.task_manager import spawn_when
from ai_assistant.orchestration.task_scheduler import (
    LIST_TASKS,
    SPAWN,
    TASK_SCHEDULER_LABEL_ARGUMENTS,
    ActivationEntry,
    ListedPlace,
    TaskEntry,
    TaskListing,
)

_HERE = ChannelIdentity(channel_type="conversation", instance_id="c-1")
_LINE = ChannelIdentity(channel_type="telegram", instance_id="ref/42")
_PLACES = (
    ListedPlace(_HERE, "The hub's chat", "the conversation this input came from"),
    ListedPlace(_LINE, "Telegram", "the person's Telegram chat", suggested=True),
)


def _scheduled(**fields: Any) -> dict[str, Any]:
    """Inputs of an activation offered spawn: the spawn tool, its labels and the list."""
    values: dict[str, Any] = {
        "capabilities": (SPAWN,),
        "label_arguments": TASK_SCHEDULER_LABEL_ARGUMENTS,
        "places": _PLACES,
    }
    values.update(fields)
    return values


async def _reported(call: ProposedCall, outcome: CallOutcome) -> dict[str, Any]:
    """What the round after ``call``'s is reported of it, its outcome ``outcome``'s.

    ADR-0356 §5:3: the first round proposes ``call``; the second is asked with that
    round's report, whose one result is decoded here. ``outcome`` is read as the first
    round's.
    """
    stage, completer, _ = _stage(RoundResponse(calls=(call,)), RoundResponse())
    inputs = _inputs(**_scheduled(capabilities=(SPAWN, LIST_TASKS)))
    planned = await stage.plan(inputs)
    assert planned.refused == ()
    await stage.plan(
        replace(
            inputs,
            work=planned.work,
            rounds=(planned.round,),
            labels=planned.labels,
            outcomes=(replace(outcome, round_id=planned.round.id),),
        )
    )
    (result,) = reported(completer.last_call, 0)
    return result


async def test_the_place_list_groups_places_under_headings_that_take_no_label() -> None:
    """§5:10, §5:13: each place carries its own ``L`` label, a heading none."""
    stage, completer, _ = _stage(RoundResponse(text=""))

    await stage.plan(_inputs(**_scheduled()))

    situation = section(_sent(completer), "## The situation")
    listed = situation.split("Places a message can be sent by its label:\n", 1)[1]
    headings = [line for line in listed.split("\n") if "<place" not in line]
    assert headings == ["  - The hub's chat:", "  - Telegram:"]
    here, line = tags(listed, "place")
    assert (here.get("label"), here.text, here.get("suggested")) == (
        "L1",
        "the conversation this input came from",
        None,
    )
    assert (line.get("label"), line.text, line.get("suggested")) == (
        "L2",
        "the person's Telegram chat",
        "yes",
    )


async def test_a_spawn_naming_a_heading_or_a_label_never_shown_is_refused_whole() -> None:
    """§5:13, §13:3: a channel heading is never named, and an unshown label refuses."""
    calls = (
        ProposedCall(
            call_id="c1", name="spawn", arguments={"instruction": "x", "places": ["Telegram"]}
        ),
        ProposedCall(call_id="c2", name="spawn", arguments={"instruction": "x", "places": ["L7"]}),
        ProposedCall(call_id="c3", name="spawn", arguments={"instruction": "x", "places": ["L2"]}),
    )
    stage, _, _ = _stage(RoundResponse(calls=calls))

    planned = await stage.plan(_inputs(**_scheduled()))

    assert [one.call.call_id for one in planned.refused] == ["c1", "c2"]
    assert all(isinstance(one, RefusedCall) for one in planned.refused)
    (kept,) = planned.calls
    assert kept.call.model_dump()["arguments"]["places"] == ["telegram:ref/42"]


async def test_a_scheduled_activations_message_goes_where_its_text_calls_via_names() -> None:
    """ADR-0357 §2:4: a message's place is a ``text`` call's ``via``, by its ``L`` label.

    ADR-0356 §7 retires §6:7's leading label on the round's text: that text is its notes
    alone and places nothing, and ``via`` is handed on as planning named it, for the tool
    to resolve against the place list.
    """
    pills = ProposedCall(
        call_id="c1",
        name="text",
        arguments={"to": "the user", "words": "time for the pills", "via": "L2"},
    )
    stage, _, recorder = _stage(RoundResponse(text="L2: time for the pills", calls=(pills,)))

    planned = await stage.plan(_inputs(**_scheduled(capabilities=(SPAWN, TEXT_CALL))))

    assert planned.message is None
    assert (planned.round.text, planned.round.place) == ("", None)
    assert planned.round.notes == "L2: time for the pills"
    (sent,) = planned.calls
    assert sent.call == pills
    ((recorded, _),) = recorder.recorded
    assert recorded.place is None


async def test_a_rounds_text_names_no_place_labelled_or_not() -> None:
    """ADR-0356 §7: a round's text is its notes, whatever label it begins with, or none."""
    stage, _, _ = _stage(
        RoundResponse(text="L2: somewhere"),
        RoundResponse(text="L9: somewhere"),
        RoundResponse(text="no label"),
    )

    shown = await stage.plan(_inputs(**_scheduled()))
    unknown = await stage.plan(_inputs(**_scheduled()))
    bare = await stage.plan(_inputs(**_scheduled()))

    for planned, notes in (
        (shown, "L2: somewhere"),
        (unknown, "L9: somewhere"),
        (bare, "no label"),
    ):
        assert (planned.round.place, planned.round.text, planned.round.notes) == (None, "", notes)
        assert planned.message is None


async def test_another_activations_message_keeps_a_leading_label_as_text() -> None:
    """§6:8: an activation the Task Scheduler did not start places nothing by its text."""
    stage, _, _ = _stage(RoundResponse(text="L1: hello"))

    planned = await stage.plan(_inputs(**_scheduled()))

    assert planned.round.text == ""
    assert planned.round.notes == "L1: hello"
    assert planned.round.place is None
    assert planned.message is None


async def test_a_listing_shows_tasks_and_their_parents_by_label() -> None:
    """§4:6-§4:8, §9:2: tasks under ``T`` labels, parents under ``E``, places under ``L``."""
    entry = TaskEntry(
        task_id="task:bins",
        state="pending",
        falls_due="at Mon 26 Oct 2026 20:00 (UTC)",
        instruction="remind them about the bins",
        outside=False,
        places=("telegram:ref/42",),
        parent="a-parent",
        parent_text="spawned by the person's message in a conversation",
        author="person",
    )
    outcome = CallOutcome(
        "round:earlier",
        "c1",
        CallOutcomeKind.DONE,
        result_id="result:1",
        tasks=TaskListing(scheduled=(entry,), listed=True),
    )

    result = await _reported(ProposedCall(call_id="c1", name="list_tasks", arguments={}), outcome)

    shown = result["result"]["value"]
    (task,) = shown["scheduled"]
    assert task["label"].startswith("T")
    assert task["suggests"] == ["L2"]
    assert task["parent"]["episode"].startswith("E")
    assert shown["running"] == "none"
    # ADR-0356 §3: the task's instruction is carried as the system's own words.
    assert tag(task["carries"], "task", **{"from": "the system"}).text == (
        "remind them about the bins"
    )


async def test_a_window_item_a_tasks_activation_wrote_shows_its_task_label() -> None:
    """§9:2: beside its episode label."""
    window = PlaceWindow(
        takes_message=True,
        items=(
            PlaceItem(
                author=PlaceAuthor.ASSISTANT,
                text="time for the pills",
                at=datetime(2026, 10, 25, 20, 0, tzinfo=UTC),
                episode_id="activation:step",
                task_id="task:pills",
            ),
        ),
    )
    stage, completer, _ = _stage(RoundResponse(text=""))

    planned = await stage.plan(_inputs(place=window))

    (item,) = tags(section(_sent(completer), "## Stimulus origin knowledge"), "message")
    assert item.text == "time for the pills"
    assert (item.get("episode") or "").startswith("E")
    assert (item.get("task") or "").startswith("T")
    assert any(one.kind is LabelKind.SCHEDULED_TASK for one in planned.labels)


def _rule_entry(**fields: Any) -> TaskEntry:
    values: dict[str, Any] = {
        "task_id": "task:bins",
        "state": "pending",
        "falls_due": "every weekday at 7:00 AM; next at Mon 26 Oct 2026 07:00 (UTC)",
        "instruction": "remind them about the bins",
        "outside": False,
        "places": (),
        "parent": "a-parent",
        "parent_text": "spawned by the person's message in a conversation",
        "author": "person",
        "repeats": "every weekday at 7:00 AM",
    }
    values.update(fields)
    return TaskEntry(**values)


async def _shown(listing: TaskListing, call: str) -> dict[str, Any]:
    """What planning's next round is shown of a call's ``listing``."""
    outcome = CallOutcome(
        "round:earlier", "c1", CallOutcomeKind.DONE, result_id="result:1", tasks=listing
    )
    result = await _reported(ProposedCall(call_id="c1", name=call, arguments={}), outcome)
    shown: dict[str, Any] = result["result"]["value"]
    return shown


async def test_a_spawns_read_back_and_its_rules_words_reach_planning() -> None:
    """ADR-0340 §6:2-§6:3, §8:2: the spawned task's read-back, said back from the record."""
    said = "Every weekday at 7:00 AM; next: Monday 26 October, at 7:00 AM. It suggests no place."

    shown = await _shown(TaskListing(spawned=_rule_entry(read_back=said)), "spawn")

    assert shown["spawned"]["read_back"] == said
    assert shown["spawned"]["repeats"] == "every weekday at 7:00 AM"


async def test_a_listed_task_shows_its_rule_and_no_read_back() -> None:
    """ADR-0340 §8:2: the list pull carries a rule's words; only a spawn says a task back."""
    shown = await _shown(TaskListing(scheduled=(_rule_entry(),), listed=True), "list_tasks")

    (task,) = shown["scheduled"]
    assert task["repeats"] == "every weekday at 7:00 AM"
    assert "read_back" not in task


async def test_a_refused_spawn_is_said_not_done_once() -> None:
    """#3452: the Task Manager's reason follows the outcome's own "not done", never twice."""
    now = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    reason = spawn_when({"at": "2026-10-25T08:00:00+00:00"}, now=now, zone=ZoneInfo("UTC"))
    assert isinstance(reason, str)
    outcome = CallOutcome("round:earlier", "c1", CallOutcomeKind.NOT_DONE, reason)

    result = await _reported(
        ProposedCall(call_id="c1", name="spawn", arguments={"instruction": "x"}), outcome
    )

    assert result["outcome"] == "not done: the instant it would fall due is earlier than now"


def _ended(**fields: Any) -> ActivationEntry:
    values: dict[str, Any] = {
        "activation_id": "step",
        "started": "Mon 26 Oct 2026 00:32 (America/New_York)",
        "place": "a scheduled step, started by the Task Scheduler",
        "status": "completed (returned)",
        "input": "remind them about the bins",
        "outside": False,
    }
    values.update(fields)
    return ActivationEntry(**values)


async def test_an_ended_step_says_where_its_messages_went_as_the_place_list_shows_places() -> None:
    """#3445, ADR-0350 §12:8: by label and description on the list, by kind off it."""
    gone = "conversation:deleted"
    listing = TaskListing(
        recent=(
            _ended(activation_id="a", wrote_into=("telegram:ref/42",)),
            _ended(
                activation_id="b", wrote_into=(gone,), may_have_written_into=("conversation:c-1",)
            ),
            _ended(activation_id="c", wrote_into=()),
            _ended(activation_id="d"),
        ),
        listed=True,
    )

    shown = await _shown(listing, "list_tasks")

    told, off_the_list, silent, unread = shown["ended_lately"]
    assert told["wrote_into"] == [{"label": "L2", "is": "the person's Telegram chat"}]
    assert "may_have_written_into" not in told
    assert off_the_list["wrote_into"] == [
        {"is": "a conversation in the hub's chat", "on_your_place_list": False}
    ]
    assert off_the_list["may_have_written_into"] == [
        {"label": "L1", "is": "the conversation this input came from"}
    ]
    assert silent["wrote_into"] == "wrote no message"
    assert "wrote_into" not in unread


async def test_an_ended_step_whose_only_message_is_not_known_is_not_said_to_have_written_none() -> (
    None
):
    """#3445, ADR-0306 §5:5: an outcome not known is no answer that nothing was written."""
    listing = TaskListing(
        recent=(_ended(wrote_into=(), may_have_written_into=("telegram:ref/42",)),),
        listed=True,
    )

    shown = await _shown(listing, "list_tasks")

    (unknown,) = shown["ended_lately"]
    assert "wrote_into" not in unknown
    assert unknown["may_have_written_into"] == [{"label": "L2", "is": "the person's Telegram chat"}]
