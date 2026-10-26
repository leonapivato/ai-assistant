"""Planning's half of the Task Scheduler: the place list, the labels, the message's place.

ADR-0350 §5:10-§5:13, §6:7, §9:2, §12:8, through :class:`PlanningStage` over a scripted
completer, as ``test_planning`` drives it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from test_planning import FLAG_ECHO, _earlier, _flags, _inputs, _sent, _stage

from ai_assistant.core.types import (
    ChannelIdentity,
    LabelKind,
    ProposedCall,
    RoundResponse,
)
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


async def test_the_place_list_groups_places_under_headings_that_take_no_label() -> None:
    """§5:10, §5:13: each place carries its own ``L`` label, a heading none."""
    stage, completer, _ = _stage(RoundResponse(text=""))

    await stage.plan(_inputs(**_scheduled()))

    assert _sent(completer)["places"] == [
        {
            "channel": "The hub's chat",
            "places": [{"label": "L1", "is": "the conversation this input came from"}],
        },
        {
            "channel": "Telegram",
            "places": [{"label": "L2", "is": "the person's Telegram chat", "suggested": True}],
        },
    ]


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


async def test_a_scheduled_activations_message_names_its_place_by_label() -> None:
    """§6:7, §12:8: the label is taken off the message and its place recorded."""
    stage, _, recorder = _stage(RoundResponse(text="L2: time for the pills"))

    planned = await stage.plan(_inputs(**_scheduled(speaks_by_label=True)))

    assert planned.round.text == "time for the pills"
    assert planned.round.place == _LINE
    assert planned.message == "time for the pills"
    ((recorded, _),) = recorder.recorded
    assert recorded.place == _LINE


async def test_a_message_naming_no_place_on_the_list_names_none() -> None:
    """§6:7: an unshown label, or none, names no place, and authorizing refuses it."""
    stage, _, _ = _stage(RoundResponse(text="L9: somewhere"), RoundResponse(text="no label"))

    unknown = await stage.plan(_inputs(**_scheduled(speaks_by_label=True)))
    bare = await stage.plan(_inputs(**_scheduled(speaks_by_label=True)))

    assert (unknown.round.place, unknown.round.text) == (None, "L9: somewhere")
    assert (bare.round.place, bare.round.text) == (None, "no label")


async def test_another_activations_message_keeps_a_leading_label_as_text() -> None:
    """§6:8: an activation the Task Scheduler did not start replies where its input came from."""
    stage, _, _ = _stage(RoundResponse(text="L1: hello"))

    planned = await stage.plan(_inputs(**_scheduled()))

    assert planned.round.text == "L1: hello"
    assert planned.round.place is None


async def test_the_spawn_and_scheduled_flags_follow_what_the_round_offers() -> None:
    """§3:4, §6:7: the instruction's two sections, each where it applies."""
    offered, _, _ = _stage(RoundResponse(text=""), prompt=FLAG_ECHO)
    started, started_completer, _ = _stage(RoundResponse(text=""), prompt=FLAG_ECHO)
    plain, plain_completer, _ = _stage(RoundResponse(text=""), prompt=FLAG_ECHO)

    await offered.plan(_inputs(**_scheduled()))
    offered_flags = _flags(offered._completer)  # type: ignore[arg-type]  # the fake it holds
    await started.plan(_inputs(**_scheduled(speaks_by_label=True)))
    await plain.plan(_inputs())

    assert {"spawn"} <= offered_flags
    assert "scheduled" not in offered_flags
    assert {"spawn", "scheduled"} <= _flags(started_completer)
    assert not {"spawn", "scheduled"} & _flags(plain_completer)


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
    stage, completer, _ = _stage(RoundResponse(text=""))

    await stage.plan(
        _inputs(
            **_scheduled(
                rounds=(
                    _earlier(calls=(ProposedCall(call_id="c1", name="list_tasks", arguments={}),)),
                ),
                outcomes=(outcome,),
            )
        )
    )

    (round_,) = _sent(completer)["rounds"]
    (call,) = round_["calls"]
    shown = call["result"]["value"]
    (task,) = shown["scheduled"]
    assert task["label"].startswith("T")
    assert task["suggests"] == ["L2"]
    assert task["parent"]["episode"].startswith("E")
    assert shown["running"] == "none"


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

    (item,) = _sent(completer)["place_window"]
    assert item["episode"].startswith("E")
    assert item["scheduled_task"].startswith("T")
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
    stage, completer, _ = _stage(RoundResponse(text=""))
    earlier = _earlier(calls=(ProposedCall(call_id="c1", name=call, arguments={}),))

    await stage.plan(_inputs(**_scheduled(rounds=(earlier,), outcomes=(outcome,))))

    (round_,) = _sent(completer)["rounds"]
    shown: dict[str, Any] = round_["calls"][0]["result"]["value"]
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
    earlier = _earlier(calls=(ProposedCall(call_id="c1", name="spawn", arguments={}),))
    outcome = CallOutcome(earlier.id, "c1", CallOutcomeKind.NOT_DONE, reason)
    stage, completer, _ = _stage(RoundResponse(text=""))

    await stage.plan(_inputs(**_scheduled(rounds=(earlier,), outcomes=(outcome,))))

    shown = _sent(completer)["rounds"][0]["calls"][0]["outcome"]
    assert shown == "not done: the instant it would fall due is earlier than now"


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
