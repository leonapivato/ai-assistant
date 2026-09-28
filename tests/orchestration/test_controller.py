"""The activation controller over constructed states and fake stages (ADR-0280 §3 to §6).

What a whole pass records, per activation kind, is in ``test_engine_stage_record.py``.
These cases hold the rules, the loop guard, the fixed defaults and the record's bound
apart from any engine.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Final

import pytest

from ai_assistant.core.errors import ModelTimeoutError, PlanningError
from ai_assistant.core.types import ControllerRule, ControllerStage, StageEntry, StageOutcome
from ai_assistant.orchestration.controller import (
    ACTIVATION_RULES,
    ActivationController,
    Rule,
    Stage,
    StageRecord,
    StageResult,
)

_AT: Final = datetime(2026, 9, 27, tzinfo=UTC)


@dataclass
class _Facts:
    """A constructed working set: every decision a plain field (``PassFacts``)."""

    conversation_turn: bool = False
    informational_event: bool = False
    conversation_resolved: bool = False
    routing_wired: bool = False
    route_decided: bool = False
    route_taken: bool = False
    understanding_wired: bool = False
    understanding_decided: bool = False
    event_summarized: bool = False
    associated: bool = False
    asks_which_goal: bool = False
    disambiguation_asked: bool = False
    continues_goal: bool = False
    reconciliation_wired: bool = False
    reconciled: bool = False
    turn_decided: bool = False
    turn_raised_question: bool = False
    plan_has_steps: bool = False
    drive_decided: bool = False
    parked: bool = False
    reply_composed: bool = False


def _due(facts: _Facts) -> Rule:
    return next(rule for rule in ACTIVATION_RULES if rule.answers(facts))


_TURN: Final = _Facts(conversation_turn=True)
_RESOLVED: Final = replace(_TURN, conversation_resolved=True)
_ASSOCIATED: Final = replace(_RESOLVED, associated=True)
_PLANNED: Final = replace(_ASSOCIATED, turn_decided=True)


# --- §4: the table, over constructed states ---------------------------------------


@pytest.mark.parametrize(
    ("facts", "rule", "stage"),
    [
        (
            _TURN,
            ControllerRule.CONVERSATION_UNRESOLVED,
            ControllerStage.BEGIN_CONVERSATION,
        ),
        (
            replace(_RESOLVED, routing_wired=True),
            ControllerRule.ROUTE_UNCHECKED,
            ControllerStage.ROUTING,
        ),
        (
            replace(_RESOLVED, routing_wired=True, route_decided=True, route_taken=True),
            ControllerRule.ROUTE_TAKEN,
            ControllerStage.END,
        ),
        (
            replace(_RESOLVED, understanding_wired=True),
            ControllerRule.NOT_UNDERSTOOD,
            ControllerStage.UNDERSTANDING,
        ),
        (
            _Facts(informational_event=True, understanding_wired=True, understanding_decided=True),
            ControllerRule.EVENT_UNSUMMARIZED,
            ControllerStage.EVENT_SUMMARY,
        ),
        (
            _Facts(informational_event=True),
            ControllerRule.EVENT_UNSUMMARIZED,
            ControllerStage.EVENT_SUMMARY,
        ),
        (_RESOLVED, ControllerRule.ASSOCIATION_DUE, ControllerStage.ASSOCIATE_GOAL),
        (
            replace(_ASSOCIATED, asks_which_goal=True),
            ControllerRule.DISAMBIGUATION_RAISED,
            ControllerStage.ASK_DISAMBIGUATION,
        ),
        (
            replace(_ASSOCIATED, continues_goal=True, reconciliation_wired=True),
            ControllerRule.CONTINUING_UNRECONCILED,
            ControllerStage.RECONCILE,
        ),
        (_ASSOCIATED, ControllerRule.UNPLANNED, ControllerStage.TURN_LOOP),
        (
            replace(_ASSOCIATED, continues_goal=True, reconciliation_wired=True, reconciled=True),
            ControllerRule.UNPLANNED,
            ControllerStage.TURN_LOOP,
        ),
        (
            replace(_PLANNED, plan_has_steps=True),
            ControllerRule.PLAN_HAS_STEPS,
            ControllerStage.DRIVE,
        ),
        (_PLANNED, ControllerRule.REPLY_OWED, ControllerStage.COMPOSE),
        (
            replace(_PLANNED, plan_has_steps=True, turn_raised_question=True),
            ControllerRule.REPLY_OWED,
            ControllerStage.COMPOSE,
        ),
        (
            replace(_PLANNED, plan_has_steps=True, drive_decided=True),
            ControllerRule.REPLY_OWED,
            ControllerStage.COMPOSE,
        ),
        (
            replace(_PLANNED, plan_has_steps=True, drive_decided=True, parked=True),
            ControllerRule.NOTHING_DUE,
            ControllerStage.END,
        ),
        (
            replace(_PLANNED, reply_composed=True),
            ControllerRule.NOTHING_DUE,
            ControllerStage.END,
        ),
        (
            replace(_ASSOCIATED, asks_which_goal=True, disambiguation_asked=True),
            ControllerRule.NOTHING_DUE,
            ControllerStage.END,
        ),
        (
            _Facts(informational_event=True, event_summarized=True),
            ControllerRule.NOTHING_DUE,
            ControllerStage.END,
        ),
    ],
)
def test_the_first_rule_that_answers_decides(
    facts: _Facts, rule: ControllerRule, stage: ControllerStage
) -> None:
    due = _due(facts)
    assert (due.name, due.makes_due) == (rule, stage)


def test_the_table_is_the_adrs_twelve_rows_in_order_ending_in_one_that_always_answers() -> None:
    assert [rule.name for rule in ACTIVATION_RULES] == [
        ControllerRule.CONVERSATION_UNRESOLVED,
        ControllerRule.ROUTE_UNCHECKED,
        ControllerRule.ROUTE_TAKEN,
        ControllerRule.NOT_UNDERSTOOD,
        ControllerRule.EVENT_UNSUMMARIZED,
        ControllerRule.ASSOCIATION_DUE,
        ControllerRule.DISAMBIGUATION_RAISED,
        ControllerRule.CONTINUING_UNRECONCILED,
        ControllerRule.UNPLANNED,
        ControllerRule.PLAN_HAS_STEPS,
        ControllerRule.REPLY_OWED,
        ControllerRule.NOTHING_DUE,
    ]
    assert ACTIVATION_RULES[-1].answers(_Facts())


def test_an_event_waits_for_a_wired_understanding_before_its_summary() -> None:
    event = _Facts(informational_event=True, understanding_wired=True)
    assert _due(event).name is ControllerRule.NOT_UNDERSTOOD


def test_a_turn_asking_which_goal_is_not_planned() -> None:
    asked = replace(_ASSOCIATED, asks_which_goal=True, disambiguation_asked=True)
    assert not any(
        rule.name is ControllerRule.UNPLANNED for rule in ACTIVATION_RULES if rule.answers(asked)
    )


def test_an_unwired_reconciliation_leaves_a_continuing_goal_to_the_turn_loop() -> None:
    continuing = replace(_ASSOCIATED, continues_goal=True)
    assert _due(continuing).name is ControllerRule.UNPLANNED


# --- §3, §5, §6: the loop, over fake stages ---------------------------------------


def _clock() -> tuple[list[datetime], object]:
    readings: list[datetime] = []
    ticks = count()

    def now() -> datetime:
        reading = _AT + timedelta(seconds=next(ticks))
        readings.append(reading)
        return reading

    return readings, now


@dataclass
class _FakeStage:
    """A stage that sets one decision, or ends as scripted."""

    name: ControllerStage
    decide: str | None = None
    result: StageResult = field(default_factory=lambda: StageResult(StageOutcome.DONE))
    runs: int = 0

    async def run(self, state: _Facts) -> StageResult:
        self.runs += 1
        if self.decide is not None:
            setattr(state, self.decide, True)
        return self.result


async def _run(
    facts: _Facts, *stages: _FakeStage, rules: tuple[Rule, ...] = ACTIVATION_RULES
) -> StageRecord:
    _, now = _clock()
    record = StageRecord()
    controller = ActivationController(stages=stages, clock=now, rules=rules)  # type: ignore[arg-type]  # the clock is a plain callable
    await controller.run(facts, record)
    return record


def _shape(record: StageRecord) -> list[tuple[ControllerStage, ControllerRule, StageOutcome]]:
    return [(entry.stage, entry.due, entry.outcome) for entry in record.entries]


async def test_the_controller_runs_what_is_due_until_nothing_is() -> None:
    record = await _run(
        _Facts(informational_event=True, understanding_wired=True),
        _FakeStage(ControllerStage.UNDERSTANDING, "understanding_decided"),
        _FakeStage(ControllerStage.EVENT_SUMMARY, "event_summarized"),
    )
    assert _shape(record) == [
        (ControllerStage.UNDERSTANDING, ControllerRule.NOT_UNDERSTOOD, StageOutcome.DONE),
        (ControllerStage.EVENT_SUMMARY, ControllerRule.EVENT_UNSUMMARIZED, StageOutcome.DONE),
        (ControllerStage.END, ControllerRule.NOTHING_DUE, StageOutcome.DONE),
    ]
    first, second, end = record.entries
    assert first.started_at < first.ended_at <= second.started_at < second.ended_at
    assert end.started_at == end.ended_at


async def test_a_rule_naming_a_stage_already_run_ends_the_pass_on_the_loop_guard() -> None:
    """§4's M38 loop guard: a stage that decides nothing is due again, and is not rerun."""
    stuck = _FakeStage(ControllerStage.EVENT_SUMMARY)
    record = await _run(_Facts(informational_event=True), stuck)
    assert stuck.runs == 1
    assert _shape(record) == [
        (ControllerStage.EVENT_SUMMARY, ControllerRule.EVENT_UNSUMMARIZED, StageOutcome.DONE),
        (ControllerStage.END, ControllerRule.STAGE_REPEATED, StageOutcome.DONE),
    ]


@pytest.mark.parametrize(
    ("outcome", "error", "ending"),
    [
        (StageOutcome.FAILED, PlanningError("broken"), ControllerRule.STAGE_FAILED),
        (StageOutcome.TIMED_OUT, ModelTimeoutError("late"), ControllerRule.STAGE_TIMED_OUT),
    ],
)
async def test_a_stage_that_did_not_end_done_ends_the_pass_and_reraises_its_error(
    outcome: StageOutcome, error: Exception, ending: ControllerRule
) -> None:
    """§5's fixed defaults: the end entry first, then the same error, unchanged."""
    _, now = _clock()
    record = StageRecord()
    controller = ActivationController(
        stages=(_FakeStage(ControllerStage.EVENT_SUMMARY, result=StageResult(outcome, error)),),
        clock=now,  # type: ignore[arg-type]  # a plain callable
    )
    with pytest.raises(type(error)) as caught:
        await controller.run(_Facts(informational_event=True), record)
    assert caught.value is error
    assert _shape(record) == [
        (ControllerStage.EVENT_SUMMARY, ControllerRule.EVENT_UNSUMMARIZED, outcome),
        (ControllerStage.END, ending, StageOutcome.DONE),
    ]


async def test_a_pass_cancelled_inside_a_stage_ends_interrupted() -> None:
    """§5: appended in the controller's ``finally``, before the cancellation propagates."""
    entered = asyncio.Event()

    async def hang(_: _Facts) -> None:
        entered.set()
        await asyncio.Event().wait()

    _, now = _clock()
    record = StageRecord()
    controller = ActivationController(
        stages=(Stage(ControllerStage.EVENT_SUMMARY, hang),),
        clock=now,  # type: ignore[arg-type]  # a plain callable
    )
    task = asyncio.create_task(controller.run(_Facts(informational_event=True), record))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _shape(record) == [(ControllerStage.END, ControllerRule.INTERRUPTED, StageOutcome.DONE)]


@pytest.mark.parametrize(
    ("raised", "outcome"),
    [
        (PlanningError("broken"), StageOutcome.FAILED),
        (ModelTimeoutError("late"), StageOutcome.TIMED_OUT),
        (TimeoutError(), StageOutcome.TIMED_OUT),
    ],
)
async def test_a_wrapped_method_is_classified_by_what_it_raised(
    raised: Exception, outcome: StageOutcome
) -> None:
    async def body(_: _Facts) -> None:
        raise raised

    result = await Stage(ControllerStage.COMPOSE, body).run(_Facts())
    assert result == StageResult(outcome, raised)


async def test_a_wrapped_method_that_returns_is_done() -> None:
    async def body(_: _Facts) -> None:
        return None

    assert await Stage(ControllerStage.COMPOSE, body).run(_Facts()) == StageResult(
        StageOutcome.DONE
    )


# --- §6: the record ---------------------------------------------------------------


def _entry(second: int) -> StageEntry:
    at = _AT + timedelta(seconds=second)
    return StageEntry(
        stage=ControllerStage.COMPOSE,
        due=ControllerRule.REPLY_OWED,
        started_at=at,
        ended_at=at,
        outcome=StageOutcome.DONE,
    )


def test_a_record_over_its_bound_keeps_the_first_half_and_the_last_and_counts_the_rest() -> None:
    record = StageRecord([_entry(second) for second in range(9)])
    record.end(ControllerRule.STAGE_REPEATED, _AT + timedelta(seconds=9))
    kept, elided = record.bounded(4)
    assert elided == 6
    assert [entry.started_at.second for entry in kept] == [0, 1, 8, 9]
    assert kept[-1].stage is ControllerStage.END


def test_a_record_within_its_bound_is_written_whole() -> None:
    record = StageRecord([_entry(0)])
    record.end(ControllerRule.NOTHING_DUE, _AT)
    kept, elided = record.bounded(64)
    assert (len(kept), elided) == (2, 0)


def test_a_supplied_ending_is_appended_to_the_written_record_only_where_none_stands() -> None:
    record = StageRecord()
    kept, _ = record.bounded(64, ending=(ControllerRule.INTERRUPTED, _AT))
    assert [(entry.stage, entry.due) for entry in kept] == [
        (ControllerStage.END, ControllerRule.INTERRUPTED)
    ]
    assert record.entries == [], "the state is not changed by a finalization reading"
    record.end(ControllerRule.NOTHING_DUE, _AT)
    kept, _ = record.bounded(64, ending=(ControllerRule.INTERRUPTED, _AT))
    assert [entry.due for entry in kept] == [ControllerRule.NOTHING_DUE]


def test_a_supplied_ending_past_the_bound_is_kept_as_the_last_entry() -> None:
    record = StageRecord([_entry(second) for second in range(5)])
    kept, elided = record.bounded(2, ending=(ControllerRule.INTERRUPTED, _AT))
    assert elided == 4
    assert [entry.stage for entry in kept] == [ControllerStage.COMPOSE, ControllerStage.END]


def test_nothing_is_appended_after_the_end_entry() -> None:
    record = StageRecord()
    record.end(ControllerRule.NOTHING_DUE, _AT)
    with pytest.raises(RuntimeError, match="exactly one end entry"):
        record.end(ControllerRule.NOTHING_DUE, _AT)


def test_a_bound_below_two_is_refused() -> None:
    with pytest.raises(ValueError, match="first entry and its end entry"):
        StageRecord().bounded(1)
