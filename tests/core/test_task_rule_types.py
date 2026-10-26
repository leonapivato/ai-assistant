"""ADR-0340 §9:1-§9:3: a scheduled task's rule, in ``core``.

The rule and its two enumerations; a task with a rule, which holds more than one
occurrence; the spawn's first instant; the push's instants; the refusal the store makes;
and the export that carries them. Behaviour over a store is the ``PlanStore``
conformance suite's.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    RULE_ZONE_MAX_CHARS,
    ChannelIdentity,
    DueAt,
    DueOnRule,
    OccurrenceState,
    PlanExport,
    RuleDay,
    RulePush,
    ScheduledOccurrence,
    ScheduledTask,
    ScheduledTaskAuthor,
    TaskRefusal,
    TaskRuleKind,
    TaskSpawn,
)

_AT = datetime(2026, 10, 26, 11, tzinfo=UTC)
_DAY = timedelta(days=1)
_HUB_CHAT = ChannelIdentity(channel_type="conversation", instance_id="c-1")
_DAILY = DueOnRule(repeats=TaskRuleKind.DAILY, time_of_day=time(7, 0))


def _rule(**fields: Any) -> DueOnRule:
    return DueOnRule.model_validate(
        {"repeats": TaskRuleKind.DAILY, "time_of_day": time(7), **fields}
    )


def _task(*occurrences: ScheduledOccurrence, **fields: Any) -> ScheduledTask:
    """A task the person set on a daily rule, holding ``occurrences``."""
    return ScheduledTask.model_validate(
        {
            "id": "t1",
            "person": "person:owner",
            "author": ScheduledTaskAuthor.PERSON,
            "when": _DAILY,
            "instruction": "the bins",
            "parent": "act-1",
            "set_in": _HUB_CHAT,
            "set_at": _AT - _DAY,
            "chain_length": 1,
            "occurrences": occurrences or (ScheduledOccurrence(number=1, due_at=_AT),),
            **fields,
        }
    )


def _done(number: int, due_at: datetime, activation: str) -> ScheduledOccurrence:
    return ScheduledOccurrence(
        number=number,
        due_at=due_at,
        state=OccurrenceState.DONE,
        activations=(activation,),
        ended_at=due_at + timedelta(minutes=1),
    )


# --- the rule (§4:2-§4:4, §9:1) -------------------------------------------------------


def test_the_rules_kinds_and_days_are_the_decisions() -> None:
    """§4:2: daily, weekdays and weekly, closed; the days of the week, Monday first."""
    assert [one.value for one in TaskRuleKind] == ["daily", "weekdays", "weekly"]
    assert [one.value for one in RuleDay] == [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    assert TaskRefusal.ASSISTANTS_RULE.value == "assistants_rule"


def test_a_rule_holds_its_kind_days_time_zone_from_and_until_and_reads_back() -> None:
    """§9:1: a weekly rule's days are held in the order of the week, each once."""
    rule = DueOnRule(
        repeats=TaskRuleKind.WEEKLY,
        days=(RuleDay.THURSDAY, RuleDay.MONDAY),
        time_of_day=time(9, 30),
        zone="America/New_York",
        from_date=date(2026, 10, 27),
        until_date=date(2026, 12, 31),
    )

    assert rule.kind == "rule"
    assert rule.days == (RuleDay.MONDAY, RuleDay.THURSDAY)
    assert DueOnRule.model_validate_json(rule.model_dump_json()) == rule
    assert _rule(from_date=date(2026, 11, 1), until_date=date(2026, 11, 1)).until_date
    assert _DAILY.zone is None
    assert _DAILY.from_date is None
    assert _DAILY.until_date is None


def test_a_zone_is_checked_for_its_shape_and_never_resolved() -> None:
    """§3:5, §9:5: refusing a name ``zoneinfo`` does not know is the spawn's, before the store.

    A stored record must read back on a host whose tz database lacks the name.
    """
    assert _rule(zone="Nowhere/Imaginary").zone == "Nowhere/Imaginary"
    with pytest.raises(ValidationError):
        _rule(zone=" ")
    with pytest.raises(ValidationError):
        _rule(zone="Z" * (RULE_ZONE_MAX_CHARS + 1))


@pytest.mark.parametrize(
    ("fields", "fault"),
    [
        ({"repeats": TaskRuleKind.WEEKLY}, "one or more days"),
        ({"days": (RuleDay.MONDAY,)}, "only a weekly rule names days"),
        ({"repeats": TaskRuleKind.WEEKDAYS, "days": (RuleDay.MONDAY,)}, "only a weekly"),
        (
            {"repeats": TaskRuleKind.WEEKLY, "days": (RuleDay.MONDAY, RuleDay.MONDAY)},
            "each day once",
        ),
        ({"time_of_day": time(7, 0, 30)}, "to the minute"),
        ({"time_of_day": time(7, 0, 0, 5)}, "to the minute"),
        ({"time_of_day": time(7, tzinfo=UTC)}, "local time"),
        (
            {"from_date": date(2026, 11, 2), "until_date": date(2026, 11, 1)},
            "never earlier than its from",
        ),
        ({"repeats": "monthly"}, "Input should be"),
    ],
)
def test_a_rule_whose_parts_disagree_is_refused(fields: dict[str, Any], fault: str) -> None:
    with pytest.raises(ValidationError, match=fault):
        _rule(**fields)


# --- a task with a rule (§4:1, §4:6-§4:10, §9:1) --------------------------------------


def test_a_task_with_a_rule_holds_more_than_one_occurrence_numbered_from_one() -> None:
    """§4:6, §4:10: every occurrence kept, in order, the one pending last."""
    task = _task(
        _done(1, _AT, "a1"),
        ScheduledOccurrence(
            number=2, due_at=_AT + _DAY, state=OccurrenceState.SKIPPED, ended_at=_AT + 3 * _DAY
        ),
        ScheduledOccurrence(
            number=3,
            due_at=_AT + 2 * _DAY,
            state=OccurrenceState.PUSHED,
            activations=("a3",),
        ),
        ScheduledOccurrence(number=4, due_at=_AT + 3 * _DAY),
    )

    assert ScheduledTask.model_validate_json(task.model_dump_json()) == task
    assert task.pending
    assert task.activations == ("a1", "a3")


def test_an_occurrence_pushed_again_is_pending_beside_the_rules_next() -> None:
    """§4:8: pushed again after a restart, it is pending, and so is the successor."""
    task = _task(
        ScheduledOccurrence(number=1, due_at=_AT, activations=("a1",)),
        ScheduledOccurrence(number=2, due_at=_AT + _DAY),
    )

    assert [one.state for one in task.occurrences] == [OccurrenceState.PENDING] * 2


def test_a_rule_that_has_ended_holds_nothing_pending() -> None:
    """§4:7: after its until or a cancel, no next occurrence is written."""
    task = _task(
        _done(1, _AT, "a1"),
        ScheduledOccurrence(
            number=2, due_at=_AT + _DAY, state=OccurrenceState.CANCELLED, ended_at=_AT
        ),
    )

    assert task.ended


@pytest.mark.parametrize(
    ("fields", "occurrences", "fault"),
    [
        ({"author": ScheduledTaskAuthor.ASSISTANT}, (), "only a task the person set"),
        (
            {},
            (_done(1, _AT, "a1"), ScheduledOccurrence(number=2, due_at=None)),
            "falls due at an instant",
        ),
        (
            {},
            (_done(1, _AT, "a1"), ScheduledOccurrence(number=2, due_at=_AT)),
            "each later than the one before it",
        ),
        (
            {},
            (
                ScheduledOccurrence(number=1, due_at=_AT),
                ScheduledOccurrence(number=2, due_at=_AT + _DAY),
            ),
            "never pushed and still pending, its last",
        ),
        (
            {},
            (ScheduledOccurrence(number=1, due_at=_AT), _done(2, _AT + _DAY, "a2")),
            "never pushed and still pending, its last",
        ),
        ({}, (ScheduledOccurrence(number=2, due_at=_AT),), "numbered from one"),
    ],
)
def test_a_task_with_a_rule_whose_parts_disagree_is_refused(
    fields: dict[str, Any], occurrences: tuple[ScheduledOccurrence, ...], fault: str
) -> None:
    with pytest.raises(ValidationError, match=fault):
        _task(*occurrences, **fields)


def test_a_task_with_no_rule_still_holds_one_occurrence() -> None:
    """ADR-0350 §3:6: the bound is lifted for a rule alone."""
    with pytest.raises(ValidationError, match="a task with no rule holds one occurrence"):
        _task(
            _done(1, _AT, "a1"),
            ScheduledOccurrence(number=2, due_at=_AT),
            when=DueAt(at=_AT),
        )


# --- the spawn's first instant (§4:5, §9:1-§9:2) ---------------------------------------


def _spawn(**fields: Any) -> TaskSpawn:
    return TaskSpawn.model_validate(
        {
            "id": "t2",
            "person": "person:owner",
            "author": ScheduledTaskAuthor.PERSON,
            "when": _DAILY,
            "instruction": "the bins",
            "set_in": _HUB_CHAT,
            "set_at": _AT - _DAY,
            "first_due_at": _AT,
            **fields,
        }
    )


def test_a_spawn_carries_a_rules_first_instant_and_none_for_another_when() -> None:
    """§9:1: the instant its caller computed, for a rule alone."""
    assert _spawn().first_due_at == _AT
    assert _spawn(when=DueAt(at=_AT), first_due_at=None).first_due_at is None
    with pytest.raises(ValidationError, match="first occurrence for a rule"):
        _spawn(first_due_at=None)
    with pytest.raises(ValidationError, match="first occurrence for a rule"):
        _spawn(when=DueAt(at=_AT))


def test_a_spawn_of_a_rule_by_the_assistant_validates_for_the_store_to_refuse() -> None:
    """§9:2: the refusal of §4:1 is the plan store's, as not done, so the spawn holds it."""
    assert _spawn(author=ScheduledTaskAuthor.ASSISTANT).author is ScheduledTaskAuthor.ASSISTANT


# --- the push's instants (§4:6, §4:8, §9:3) --------------------------------------------


def test_a_push_states_the_successor_either_way() -> None:
    """§9:3: the next occurrence's instant, or none where the rule has ended."""
    assert RulePush(successor=_AT).successor == _AT
    assert RulePush(successor=None).successor is None
    with pytest.raises(ValidationError):
        RulePush.model_validate({})


def test_a_missed_rules_push_states_what_it_skips_and_the_latest() -> None:
    """§4:8: the skipped instants, then the latest pushed, then its successor, in order."""
    push = RulePush(skipped=(_AT, _AT + _DAY), latest=_AT + 2 * _DAY, successor=_AT + 3 * _DAY)

    assert RulePush.model_validate_json(push.model_dump_json()) == push
    assert RulePush(latest=_AT, successor=None).skipped == ()
    with pytest.raises(ValidationError, match="followed by the one it pushes"):
        RulePush(skipped=(_AT,), successor=_AT + _DAY)
    with pytest.raises(ValidationError, match="in order"):
        RulePush(skipped=(_AT + _DAY, _AT), latest=_AT + 2 * _DAY, successor=None)
    with pytest.raises(ValidationError, match="in order"):
        RulePush(latest=_AT + _DAY, successor=_AT + _DAY)


# --- the export (§9:3) ----------------------------------------------------------------


def test_the_export_carries_a_task_with_a_rule() -> None:
    """§9:3: the new fields ride in the task, at the label ADR-0352 §6:3 moves to."""
    task = _task(_done(1, _AT, "a1"), ScheduledOccurrence(number=2, due_at=_AT + _DAY))
    export = PlanExport(exported_at=_AT, scheduled_tasks=(task,))

    assert export.schema_version == 26
    assert PlanExport.model_validate_json(export.model_dump_json()) == export
