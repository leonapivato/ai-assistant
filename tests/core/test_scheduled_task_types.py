"""ADR-0350 §12:1-§12:3, §12:7-§12:8: the Task Scheduler's types in ``core``.

The scheduled task, its occurrence and their enumerations; the spawn the plan store writes
one from and what it answers; the two label kinds; the round's place; and the export's
new parts. Behaviour over a store is the ``PlanStore`` conformance suite's.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ENDED_OCCURRENCE_STATES,
    SCHEDULED_TASK_INSTRUCTION_MAX_CHARS,
    ChannelIdentity,
    DueAfterTasks,
    DueAt,
    DueNow,
    LabelKind,
    OccurrencePush,
    OccurrenceState,
    PlanExport,
    PlanningLabel,
    PlanningRound,
    ScheduledOccurrence,
    ScheduledTask,
    ScheduledTaskAuthor,
    ScheduledTaskCancel,
    ScheduledTaskWrite,
    TaskRefusal,
    TaskSpawn,
    TaskWriteAnswer,
    label_prefix,
)

_AT = datetime(2026, 10, 25, 8, tzinfo=UTC)
_HUB_CHAT = ChannelIdentity(channel_type="conversation", instance_id="c-1")
_LINE = ChannelIdentity(channel_type="telegram", instance_id="line")


def _task(**fields: Any) -> ScheduledTask:
    """A task due now, set in a conversation, with fields overridden."""
    return ScheduledTask.model_validate(
        {
            "id": "t1",
            "person": "person:owner",
            "author": ScheduledTaskAuthor.PERSON,
            "when": DueNow(),
            "instruction": "remind me to call Mom",
            "parent": "act-1",
            "set_in": _HUB_CHAT,
            "set_at": _AT,
            "chain_length": 1,
            "occurrences": (ScheduledOccurrence(number=1, due_at=_AT),),
            **fields,
        }
    )


# --- the enumerations (§12:1) ---------------------------------------------------------


def test_the_author_and_the_state_enumerations_are_the_decisions() -> None:
    """§12:1: the person or the assistant; and the eight states, in the decision's order."""
    assert [one.value for one in ScheduledTaskAuthor] == ["person", "assistant"]
    assert [one.value for one in OccurrenceState] == [
        "pending",
        "pushed",
        "done",
        "couldnt_finish",
        "stopped",
        "interrupted",
        "cancelled",
        "skipped",
    ]
    assert set(OccurrenceState) - ENDED_OCCURRENCE_STATES == {
        OccurrenceState.PENDING,
        OccurrenceState.PUSHED,
    }


# --- the occurrence --------------------------------------------------------------------


def test_an_occurrence_counts_its_pushes_and_names_the_one_it_is_pushed_to() -> None:
    """§8:5: the count is the activations named; the last names a pushed occurrence."""
    pushed = ScheduledOccurrence(
        number=1, due_at=_AT, state=OccurrenceState.PUSHED, activations=("a1", "a2")
    )
    again = pushed.model_copy(update={"state": OccurrenceState.PENDING})

    assert (pushed.pushes, pushed.pushed_to, pushed.ended) == (2, "a2", False)
    assert (again.pushes, again.pushed_to) == (2, None)


@pytest.mark.parametrize(
    ("fields", "fault"),
    [
        ({"state": OccurrenceState.DONE, "activations": ("a1",)}, "when it ended"),
        ({"ended_at": _AT}, "when it ended"),
        ({"state": OccurrenceState.PUSHED}, "names its activation"),
        (
            {"state": OccurrenceState.PUSHED, "activations": ("a1",), "due_at": None},
            "fell due",
        ),
        ({"activations": ("a1", "a1")}, "each activation once"),
        ({"second_try": True}, "pushed again"),
        (
            {"state": OccurrenceState.SKIPPED, "activations": ("a1",), "ended_at": _AT},
            "never pushed",
        ),
    ],
)
def test_an_occurrence_whose_parts_disagree_is_refused(fields: dict[str, Any], fault: str) -> None:
    with pytest.raises(ValidationError, match=fault):
        ScheduledOccurrence.model_validate({"number": 1, "due_at": _AT, **fields})


def test_a_waiting_occurrence_has_no_due_instant_until_its_waits_end() -> None:
    """§5:4: pending with no instant is a task waiting on named tasks."""
    waiting = ScheduledOccurrence(number=1)
    assert (waiting.state, waiting.due_at) == (OccurrenceState.PENDING, None)


# --- the task --------------------------------------------------------------------------


def test_a_task_round_trips_and_reads_its_ending_from_its_occurrence() -> None:
    """§3:6: every part it holds survives its JSON, and it ends when its occurrence does."""
    task = _task(
        when=DueAt(at=_AT + timedelta(hours=1)),
        places=(_LINE, _HUB_CHAT),
        outside_content=True,
        occurrences=(
            ScheduledOccurrence(
                number=1,
                due_at=_AT + timedelta(hours=1),
                state=OccurrenceState.DONE,
                activations=("a1",),
                ended_at=_AT + timedelta(hours=2),
            ),
        ),
    )

    assert ScheduledTask.model_validate_json(task.model_dump_json()) == task
    assert (task.pending, task.ended, task.ended_at) == (False, True, _AT + timedelta(hours=2))
    assert task.activations == ("a1",)
    assert task.occurrence(1) is task.occurrences[0]
    assert task.occurrence(2) is None


@pytest.mark.parametrize(
    ("fields", "fault"),
    [
        ({"occurrences": (ScheduledOccurrence(number=2, due_at=_AT),)}, "numbered from one"),
        (
            {
                "occurrences": (
                    ScheduledOccurrence(number=1, due_at=_AT),
                    ScheduledOccurrence(number=2, due_at=_AT),
                )
            },
            "a task with no rule holds one occurrence",
        ),
        ({"places": (_LINE, _LINE)}, "each place once"),
        ({"when": DueAfterTasks(tasks=("t1",))}, "never waits on itself"),
        ({"occurrences": (ScheduledOccurrence(number=1, due_at=_AT + timedelta(1)),)}, "set"),
        ({"when": DueAt(at=_AT + timedelta(hours=1))}, "falls due at it"),
        ({"instruction": "x" * (SCHEDULED_TASK_INSTRUCTION_MAX_CHARS + 1)}, "at most"),
        ({"instruction": "  "}, "blank"),
        ({"chain_length": 0}, "greater than or equal"),
    ],
)
def test_a_task_whose_parts_disagree_is_refused(fields: dict[str, Any], fault: str) -> None:
    with pytest.raises(ValidationError, match=fault):
        _task(**fields)


def test_a_wait_names_each_task_once_and_at_least_one() -> None:
    """§5:4: a hub event naming tasks names some, and none twice."""
    with pytest.raises(ValidationError):
        DueAfterTasks(tasks=())
    with pytest.raises(ValidationError, match="each task it names once"):
        DueAfterTasks(tasks=("t1", "t1"))


# --- the spawn and what the store answers ---------------------------------------------


def _spawn(**fields: Any) -> TaskSpawn:
    return TaskSpawn.model_validate(
        {
            "id": "t2",
            "person": "person:owner",
            "author": ScheduledTaskAuthor.ASSISTANT,
            "when": DueNow(),
            "instruction": "check back",
            "set_in": _HUB_CHAT,
            "set_at": _AT,
            **fields,
        }
    )


@pytest.mark.parametrize(
    ("fields", "fault"),
    [
        ({"places": (_HUB_CHAT, _HUB_CHAT)}, "each place once"),
        ({"when": DueAfterTasks(tasks=("t2",))}, "never waits on itself"),
        ({"replaces": "t2"}, "never the one it writes"),
    ],
)
def test_a_spawn_whose_parts_disagree_is_refused(fields: dict[str, Any], fault: str) -> None:
    with pytest.raises(ValidationError, match=fault):
        _spawn(**fields)


def test_a_write_carries_its_task_or_its_reason_as_its_answer_says() -> None:
    """§3:3, §4:5: the task exactly where written, the reason exactly where refused."""
    ScheduledTaskWrite(answer=TaskWriteAnswer.WRITTEN, task=_task())
    ScheduledTaskWrite(answer=TaskWriteAnswer.REFUSED, reason=TaskRefusal.CHAIN_LIMIT)
    ScheduledTaskWrite(answer=TaskWriteAnswer.ALREADY_DONE)
    with pytest.raises(ValidationError, match="its task"):
        ScheduledTaskWrite(answer=TaskWriteAnswer.WRITTEN)
    with pytest.raises(ValidationError, match="a reason"):
        ScheduledTaskWrite(answer=TaskWriteAnswer.REFUSED)
    with pytest.raises(ValidationError, match="a reason"):
        ScheduledTaskWrite(answer=TaskWriteAnswer.ALREADY_USED, reason=TaskRefusal.CHAIN_LIMIT)


def test_a_cancel_carries_its_task_or_its_reason() -> None:
    ScheduledTaskCancel(task=_task())
    ScheduledTaskCancel(reason=TaskRefusal.NOTHING_PENDING)
    with pytest.raises(ValidationError):
        ScheduledTaskCancel()
    with pytest.raises(ValidationError):
        ScheduledTaskCancel(task=_task(), reason=TaskRefusal.NOTHING_PENDING)


# --- the labels (§12:2) and the round's place (§12:8) ------------------------------------


def test_a_scheduled_task_and_a_place_are_labelled_t_and_l() -> None:
    """§12:2: two label kinds, with prefixes no other kind has."""
    assert (label_prefix(LabelKind.SCHEDULED_TASK), label_prefix(LabelKind.PLACE)) == ("T", "L")
    PlanningLabel(label="T1", kind=LabelKind.SCHEDULED_TASK, id="t1")
    PlanningLabel(label="L12", kind=LabelKind.PLACE, id="conversation:c-1")
    with pytest.raises(ValidationError, match="its kind's prefix"):
        PlanningLabel(label="L1", kind=LabelKind.SCHEDULED_TASK, id="t1")


def test_a_round_names_the_place_its_message_goes_into_and_validates_without_it() -> None:
    """§12:8: a place for a round carrying a message; a round written before still reads."""
    placed = PlanningRound(id="r1", recorded_at=_AT, text="Time to call Mom.", place=_LINE)
    before = PlanningRound.model_validate({"id": "r2", "recorded_at": _AT, "text": "Hi."})

    assert PlanningRound.model_validate_json(placed.model_dump_json()) == placed
    assert before.place is None
    with pytest.raises(ValidationError, match="names the place"):
        PlanningRound(id="r3", recorded_at=_AT, place=_LINE)


# --- the export (§12:3) -----------------------------------------------------------------


def test_the_export_refuses_a_task_twice() -> None:
    with pytest.raises(ValidationError, match="duplicate scheduled task"):
        PlanExport(exported_at=_AT, scheduled_tasks=(_task(), _task()))
    exported = PlanExport(exported_at=_AT, scheduled_tasks=(_task(),))
    assert PlanExport.model_validate_json(exported.model_dump_json()) == exported


def test_the_export_carries_no_cascade_record() -> None:
    """ADR-0352 §6:3: ``cascades`` is gone, so a document carrying it is refused as extra."""
    assert "cascades" not in PlanExport.model_fields
    with pytest.raises(ValidationError, match="cascades"):
        PlanExport.model_validate({"exported_at": _AT, "cascades": ["a1"]})


def test_a_push_has_no_cascade_answer() -> None:
    """ADR-0352 §6:2: ``OccurrencePush`` loses ``cascade_cancelled``, its recorded exception."""
    assert {one.value for one in OccurrencePush} == {"pushed", "not_pending"}
