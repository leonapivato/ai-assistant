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

from ai_assistant.core.diagnostics import diagnosed_activation_id, write_diagnostic
from ai_assistant.core.errors import MemoryStoreError, ModelTimeoutError, PlanningError
from ai_assistant.core.types import (
    ControllerRule,
    ControllerStage,
    DiagnosticKind,
    DiagnosticSource,
    StageEntry,
    StageOutcome,
)
from ai_assistant.orchestration.controller import (
    ACTIVATION_RULES,
    ActivationController,
    PassFacts,
    Rule,
    Stage,
    StageRecord,
    StageResult,
    TolerantStage,
    run_recorded,
)
from ai_assistant.testing import FakeDiagnosticSink

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
    windows_decided: bool = False
    recall_wired: bool = False
    recall_decided: bool = False
    deadline_passed: bool = False
    understanding_wired: bool = False
    understanding_decided: bool = False
    understanding_recorded: bool = False
    story_links_wired: bool = False
    story_links_decided: bool = False
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
    phases: _Phases | None = None


@dataclass
class _Phases:
    """A constructed phase working set: every decision a plain field (``PhaseFacts``)."""

    recalled_again: bool = False
    recall_kept_outside: bool = False
    recall_digested: bool = False
    rounds: int = 0
    round_limit: int = 3
    latest_round: str | None = None
    latest_has_calls: bool = False
    latest_has_text: bool = False
    latest_authorized: bool = False
    latest_allows: bool = False
    latest_acted: bool = False
    latest_digests_due: bool = False
    latest_calls_beyond_tidy_ups: bool = False


def _turn_asks_nothing(facts: PassFacts) -> bool:
    return facts.conversation_turn and facts.associated and not facts.asks_which_goal


#: The controller's mechanism cases' own table: the rows the old path's table ran
#: before the switch (ADR-0309 §2:6), kept here so those cases exercise the mechanism —
#: the first answer decides, the loop guard, tolerance, deadlines, the stop mark and the
#: record — over stages a case can fake without the phases' working set. The
#: controller's own table is §3's, :data:`ACTIVATION_RULES`, pinned below.
_MECHANISM_RULES: Final[tuple[Rule, ...]] = (
    Rule(
        ControllerRule.CONVERSATION_UNRESOLVED,
        lambda f: f.conversation_turn and not f.conversation_resolved,
        ControllerStage.BEGIN_CONVERSATION,
    ),
    Rule(
        ControllerRule.ROUTE_UNCHECKED,
        lambda f: f.conversation_turn and f.routing_wired and not f.route_decided,
        ControllerStage.ROUTING,
    ),
    Rule(ControllerRule.ROUTE_TAKEN, lambda f: f.route_taken, ControllerStage.END),
    # ADR-0282 §3: the windows are assembled before recall, wherever understanding is.
    Rule(
        ControllerRule.WINDOWS_UNASSEMBLED,
        lambda f: f.understanding_wired and not f.windows_decided,
        ControllerStage.WINDOWS,
    ),
    # ADR-0281 §2: recall runs before understanding, and only where both are wired.
    Rule(
        ControllerRule.NOT_RECALLED,
        lambda f: f.recall_wired and f.understanding_wired and not f.recall_decided,
        ControllerStage.RECALL,
    ),
    Rule(
        ControllerRule.NOT_UNDERSTOOD,
        lambda f: f.understanding_wired and not f.understanding_decided,
        ControllerStage.UNDERSTANDING,
    ),
    # ADR-0300 §6:11: the understanding's story links are recorded once it is a
    # recorded version, before anything the pass does with the input.
    Rule(
        ControllerRule.STORY_LINKS_UNRECORDED,
        lambda f: f.story_links_wired and f.understanding_recorded and not f.story_links_decided,
        ControllerStage.STORY_LINKS,
    ),
    Rule(
        ControllerRule.EVENT_UNSUMMARIZED,
        lambda f: (
            f.informational_event
            and not f.event_summarized
            and (f.understanding_decided or not f.understanding_wired)
        ),
        ControllerStage.EVENT_SUMMARY,
    ),
    Rule(
        ControllerRule.ASSOCIATION_DUE,
        lambda f: f.conversation_turn and not f.associated,
        ControllerStage.ASSOCIATE_GOAL,
    ),
    Rule(
        ControllerRule.DISAMBIGUATION_RAISED,
        lambda f: f.asks_which_goal and not f.disambiguation_asked,
        ControllerStage.ASK_DISAMBIGUATION,
    ),
    Rule(
        ControllerRule.CONTINUING_UNRECONCILED,
        lambda f: f.continues_goal and f.reconciliation_wired and not f.reconciled,
        ControllerStage.RECONCILE,
    ),
    Rule(
        ControllerRule.UNPLANNED,
        lambda f: _turn_asks_nothing(f) and not f.turn_decided,
        ControllerStage.TURN_LOOP,
    ),
    Rule(
        ControllerRule.PLAN_HAS_STEPS,
        lambda f: (
            f.turn_decided
            and not f.turn_raised_question
            and f.plan_has_steps
            and not f.drive_decided
        ),
        ControllerStage.DRIVE,
    ),
    Rule(
        ControllerRule.REPLY_OWED,
        lambda f: f.turn_decided and not f.parked and not f.reply_composed,
        ControllerStage.COMPOSE,
    ),
    Rule(ControllerRule.NOTHING_DUE, lambda _: True, ControllerStage.END),
)


def _due(facts: _Facts) -> Rule:
    return next(rule for rule in _MECHANISM_RULES if rule.answers(facts))


_TURN: Final = _Facts(conversation_turn=True)
_RESOLVED: Final = replace(_TURN, conversation_resolved=True)
_ASSOCIATED: Final = replace(_RESOLVED, associated=True)
_PLANNED: Final = replace(_ASSOCIATED, turn_decided=True)
_UNDERSTOOD: Final = replace(
    _RESOLVED, understanding_wired=True, windows_decided=True, understanding_decided=True
)


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
        # ADR-0282 §3: the windows first, wherever understanding is wired.
        (
            replace(_RESOLVED, understanding_wired=True),
            ControllerRule.WINDOWS_UNASSEMBLED,
            ControllerStage.WINDOWS,
        ),
        (
            replace(_RESOLVED, understanding_wired=True, recall_wired=True),
            ControllerRule.WINDOWS_UNASSEMBLED,
            ControllerStage.WINDOWS,
        ),
        (
            _Facts(informational_event=True, understanding_wired=True, recall_wired=True),
            ControllerRule.WINDOWS_UNASSEMBLED,
            ControllerStage.WINDOWS,
        ),
        (
            replace(_RESOLVED, understanding_wired=True, windows_decided=True),
            ControllerRule.NOT_UNDERSTOOD,
            ControllerStage.UNDERSTANDING,
        ),
        (
            replace(_RESOLVED, understanding_wired=True, windows_decided=True, recall_wired=True),
            ControllerRule.NOT_RECALLED,
            ControllerStage.RECALL,
        ),
        (
            replace(
                _RESOLVED,
                understanding_wired=True,
                windows_decided=True,
                recall_wired=True,
                recall_decided=True,
            ),
            ControllerRule.NOT_UNDERSTOOD,
            ControllerStage.UNDERSTANDING,
        ),
        (
            replace(_RESOLVED, routing_wired=True, understanding_wired=True, recall_wired=True),
            ControllerRule.ROUTE_UNCHECKED,
            ControllerStage.ROUTING,
        ),
        (
            _Facts(
                informational_event=True,
                understanding_wired=True,
                windows_decided=True,
                recall_wired=True,
            ),
            ControllerRule.NOT_RECALLED,
            ControllerStage.RECALL,
        ),
        (
            _Facts(informational_event=True, recall_wired=True),
            ControllerRule.EVENT_UNSUMMARIZED,
            ControllerStage.EVENT_SUMMARY,
        ),
        (
            _Facts(
                informational_event=True,
                understanding_wired=True,
                windows_decided=True,
                understanding_decided=True,
            ),
            ControllerRule.EVENT_UNSUMMARIZED,
            ControllerStage.EVENT_SUMMARY,
        ),
        (
            _Facts(informational_event=True),
            ControllerRule.EVENT_UNSUMMARIZED,
            ControllerStage.EVENT_SUMMARY,
        ),
        # ADR-0300 §6:11: the story links once understanding is a recorded version,
        # ahead of everything a turn or an event does with its input.
        (
            replace(_UNDERSTOOD, story_links_wired=True, understanding_recorded=True),
            ControllerRule.STORY_LINKS_UNRECORDED,
            ControllerStage.STORY_LINKS,
        ),
        (
            _Facts(
                informational_event=True,
                understanding_wired=True,
                windows_decided=True,
                understanding_decided=True,
                understanding_recorded=True,
                story_links_wired=True,
            ),
            ControllerRule.STORY_LINKS_UNRECORDED,
            ControllerStage.STORY_LINKS,
        ),
        (
            replace(
                _UNDERSTOOD,
                story_links_wired=True,
                understanding_recorded=True,
                story_links_decided=True,
            ),
            ControllerRule.ASSOCIATION_DUE,
            ControllerStage.ASSOCIATE_GOAL,
        ),
        # Wired, but no version recorded: the rule does not answer.
        (
            replace(_UNDERSTOOD, story_links_wired=True),
            ControllerRule.ASSOCIATION_DUE,
            ControllerStage.ASSOCIATE_GOAL,
        ),
        # A version recorded, and no stage wired: the rule does not answer.
        (
            replace(_UNDERSTOOD, understanding_recorded=True),
            ControllerRule.ASSOCIATION_DUE,
            ControllerStage.ASSOCIATE_GOAL,
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
    facts: _Facts, *stages: _FakeStage, rules: tuple[Rule, ...] = _MECHANISM_RULES
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
        _Facts(informational_event=True, understanding_wired=True, windows_decided=True),
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
        rules=_MECHANISM_RULES,
    )
    with pytest.raises(type(error)) as caught:
        await controller.run(_Facts(informational_event=True), record)
    assert caught.value is error
    assert _shape(record) == [
        (ControllerStage.EVENT_SUMMARY, ControllerRule.EVENT_UNSUMMARIZED, outcome),
        (ControllerStage.END, ending, StageOutcome.DONE),
    ]


# --- ADR-0281 §5: a failure-tolerant stage -----------------------------------------------


_EVENT_WIRED: Final = _Facts(
    informational_event=True, understanding_wired=True, windows_decided=True, recall_wired=True
)


def _tolerated(outcome: StageOutcome, error: Exception) -> _FakeStage:
    """A tolerant recall that records its decision, then returns ``outcome`` tolerated."""
    return _FakeStage(
        ControllerStage.RECALL,
        "recall_decided",
        result=StageResult(outcome, error, tolerated=True),
    )


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        (StageOutcome.FAILED, MemoryStoreError("down")),
        (StageOutcome.TIMED_OUT, TimeoutError()),
    ],
)
async def test_a_tolerated_result_is_recorded_and_understanding_follows(
    outcome: StageOutcome, error: Exception
) -> None:
    record = await _run(
        replace(_EVENT_WIRED),
        _tolerated(outcome, error),
        _FakeStage(ControllerStage.UNDERSTANDING, "understanding_decided"),
        _FakeStage(ControllerStage.EVENT_SUMMARY, "event_summarized"),
    )
    assert _shape(record) == [
        (ControllerStage.RECALL, ControllerRule.NOT_RECALLED, outcome),
        (ControllerStage.UNDERSTANDING, ControllerRule.NOT_UNDERSTOOD, StageOutcome.DONE),
        (ControllerStage.EVENT_SUMMARY, ControllerRule.EVENT_UNSUMMARIZED, StageOutcome.DONE),
        (ControllerStage.END, ControllerRule.NOTHING_DUE, StageOutcome.DONE),
    ]


async def test_a_tolerated_result_past_the_pass_deadline_ends_the_pass_and_reraises() -> None:
    late = ModelTimeoutError("the pass's deadline passed")
    record = StageRecord()
    _, now = _clock()
    controller = ActivationController(
        stages=(_tolerated(StageOutcome.TIMED_OUT, late),),
        clock=now,  # type: ignore[arg-type]  # a plain callable
        rules=_MECHANISM_RULES,
    )
    with pytest.raises(ModelTimeoutError) as caught:
        await controller.run(replace(_EVENT_WIRED, deadline_passed=True), record)
    assert caught.value is late
    assert _shape(record) == [
        (ControllerStage.RECALL, ControllerRule.NOT_RECALLED, StageOutcome.TIMED_OUT),
        (ControllerStage.END, ControllerRule.STAGE_TIMED_OUT, StageOutcome.DONE),
    ]


async def test_an_error_escaping_a_tolerant_stage_ends_the_pass_as_stage_failed() -> None:
    broken = PlanningError("escaped")

    async def body(_: _Facts) -> StageResult:
        raise broken

    record = StageRecord()
    _, now = _clock()
    controller = ActivationController(
        stages=(TolerantStage(ControllerStage.RECALL, body),),
        clock=now,  # type: ignore[arg-type]  # a plain callable
        rules=_MECHANISM_RULES,
    )
    with pytest.raises(PlanningError) as caught:
        await controller.run(replace(_EVENT_WIRED), record)
    assert caught.value is broken
    assert _shape(record) == [
        (ControllerStage.RECALL, ControllerRule.NOT_RECALLED, StageOutcome.FAILED),
        (ControllerStage.END, ControllerRule.STAGE_FAILED, StageOutcome.DONE),
    ]


async def test_a_result_not_marked_tolerated_takes_the_fixed_default() -> None:
    """Only the stage that caught and handled a failure marks it; nothing else continues."""
    record = StageRecord()
    _, now = _clock()
    failed = MemoryStoreError("down")
    controller = ActivationController(
        stages=(
            _FakeStage(
                ControllerStage.RECALL,
                "recall_decided",
                result=StageResult(StageOutcome.FAILED, failed),
            ),
        ),
        clock=now,  # type: ignore[arg-type]  # a plain callable
        rules=_MECHANISM_RULES,
    )
    with pytest.raises(MemoryStoreError):
        await controller.run(replace(_EVENT_WIRED), record)
    assert record.entries[-1].due is ControllerRule.STAGE_FAILED


@pytest.mark.parametrize(
    ("raised", "outcome"),
    [
        (PlanningError("broken"), StageOutcome.FAILED),
        (ModelTimeoutError("late"), StageOutcome.TIMED_OUT),
    ],
)
async def test_a_tolerant_stage_classifies_an_escaped_raise_and_never_tolerates_it(
    raised: Exception, outcome: StageOutcome
) -> None:
    async def body(_: _Facts) -> StageResult:
        raise raised

    assert await TolerantStage(ControllerStage.RECALL, body).run(_Facts()) == StageResult(
        outcome, raised
    )


async def test_a_tolerant_stage_whose_deadline_passed_is_not_entered_or_tolerated() -> None:
    late = ModelTimeoutError("the deadline passed")
    entered = False

    async def body(_: _Facts) -> StageResult:
        nonlocal entered
        entered = True
        return StageResult(StageOutcome.DONE)

    stage = TolerantStage(ControllerStage.RECALL, body, expired=lambda _: late)
    assert await stage.run(_Facts()) == StageResult(StageOutcome.TIMED_OUT, late)
    assert not entered


@pytest.mark.parametrize(
    "returned",
    [
        StageResult(StageOutcome.DONE),
        StageResult(StageOutcome.FAILED, MemoryStoreError("down"), tolerated=True),
    ],
    ids=["done", "tolerated"],
)
async def test_a_tolerant_stage_that_returns_past_its_deadline_is_timed_out(
    returned: StageResult,
) -> None:
    """ADR-0281 §5: past the deadline, whatever the body returned is the expiry."""
    late = ModelTimeoutError("the deadline passed")
    reads = iter((None, late))

    async def body(_: _Facts) -> StageResult:
        return returned

    stage = TolerantStage(ControllerStage.RECALL, body, expired=lambda _: next(reads))
    assert await stage.run(_Facts()) == StageResult(StageOutcome.TIMED_OUT, late)


async def test_a_tolerant_stage_returns_what_its_body_returned() -> None:
    tolerated = StageResult(StageOutcome.FAILED, MemoryStoreError("down"), tolerated=True)

    async def body(_: _Facts) -> StageResult:
        return tolerated

    assert await TolerantStage(ControllerStage.RECALL, body).run(_Facts()) is tolerated


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
        rules=_MECHANISM_RULES,
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


async def test_a_stage_whose_deadline_already_passed_is_not_entered() -> None:
    """§5: not run, and ``timed_out`` carrying the deadline error."""
    entered = False
    late = ModelTimeoutError("the deadline passed")

    async def body(_: _Facts) -> None:
        nonlocal entered
        entered = True

    stage = Stage(ControllerStage.UNDERSTANDING, body, expired=lambda _: late)
    assert await stage.run(_Facts()) == StageResult(StageOutcome.TIMED_OUT, late)
    assert not entered
    assert await Stage(ControllerStage.UNDERSTANDING, body, expired=lambda _: None).run(
        _Facts()
    ) == StageResult(StageOutcome.DONE)
    assert entered


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


# --- ADR-0297 §4: a stopped pass -------------------------------------------------------


@dataclass
class _Mark:
    """An activation's stop mark, as the controller reads it."""

    stopped: bool = False

    def __call__(self) -> bool:
        return self.stopped


@dataclass
class _StoppingStage(_FakeStage):
    """A stage that sets the stop mark while it runs, then ends as scripted."""

    mark: _Mark = field(default_factory=_Mark)

    async def run(self, state: _Facts) -> StageResult:
        self.mark.stopped = True
        return await super().run(state)


def _stoppable(mark: _Mark, *stages: _FakeStage) -> ActivationController[_Facts]:
    _, now = _clock()
    return ActivationController(
        stages=stages,
        clock=now,  # type: ignore[arg-type]  # a plain callable
        rules=_MECHANISM_RULES,
        stopped=mark,
    )


async def test_a_mark_set_before_the_controller_runs_no_stage_and_ends_stopped() -> None:
    """§4:1-§4:3: read before the rules are evaluated, so nothing is due and nothing runs."""
    mark = _Mark(stopped=True)
    stage = _FakeStage(ControllerStage.EVENT_SUMMARY, "event_summarized")
    record = StageRecord()

    await _stoppable(mark, stage).run(_Facts(informational_event=True), record)

    assert stage.runs == 0
    assert _shape(record) == [(ControllerStage.END, ControllerRule.STOPPED, StageOutcome.DONE)]


async def test_a_mark_set_during_a_stage_ends_the_pass_before_the_next() -> None:
    """§4:1: read again once the stage's result is in hand; the next stage never starts."""
    mark = _Mark()
    first = _StoppingStage(ControllerStage.UNDERSTANDING, "understanding_decided", mark=mark)
    second = _FakeStage(ControllerStage.EVENT_SUMMARY, "event_summarized")
    record = StageRecord()

    await _stoppable(mark, first, second).run(
        _Facts(informational_event=True, understanding_wired=True, windows_decided=True), record
    )

    assert (first.runs, second.runs) == (1, 0)
    assert _shape(record) == [
        (ControllerStage.UNDERSTANDING, ControllerRule.NOT_UNDERSTOOD, StageOutcome.DONE),
        (ControllerStage.END, ControllerRule.STOPPED, StageOutcome.DONE),
    ]


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        (StageOutcome.FAILED, PlanningError("refused")),
        (StageOutcome.TIMED_OUT, ModelTimeoutError("late")),
    ],
)
async def test_a_stage_failing_after_the_mark_ends_stopped_and_is_not_reraised(
    outcome: StageOutcome, error: Exception
) -> None:
    """§4:4: the stop was taken in first, so it is what ended the pass."""
    mark = _Mark()
    failing = _StoppingStage(
        ControllerStage.EVENT_SUMMARY, result=StageResult(outcome, error), mark=mark
    )
    record = StageRecord()

    await _stoppable(mark, failing).run(_Facts(informational_event=True), record)

    assert _shape(record) == [
        (ControllerStage.EVENT_SUMMARY, ControllerRule.EVENT_UNSUMMARIZED, outcome),
        (ControllerStage.END, ControllerRule.STOPPED, StageOutcome.DONE),
    ]


async def test_a_cancellation_reaching_a_marked_pass_propagates_with_the_stops_end_entry() -> None:
    """§4:3: no task is cancelled by a stop, but one that is still propagates (ADR-0060)."""
    mark = _Mark()
    entered = asyncio.Event()

    async def hang(_: _Facts) -> None:
        mark.stopped = True
        entered.set()
        await asyncio.Event().wait()

    record = StageRecord()
    _, now = _clock()
    controller = ActivationController(
        stages=(Stage(ControllerStage.EVENT_SUMMARY, hang),),
        clock=now,  # type: ignore[arg-type]  # a plain callable
        rules=_MECHANISM_RULES,
        stopped=mark,
    )
    task = asyncio.create_task(controller.run(_Facts(informational_event=True), record))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _shape(record) == [(ControllerStage.END, ControllerRule.STOPPED, StageOutcome.DONE)]


async def test_a_pass_ended_by_a_rule_is_not_moved_by_a_later_mark() -> None:
    """§3:3: the end entry appended first decides; the mark cannot rewrite it."""
    mark = _Mark()
    record = StageRecord()

    await _stoppable(mark).run(_Facts(informational_event=True, event_summarized=True), record)
    mark.stopped = True

    assert _shape(record) == [(ControllerStage.END, ControllerRule.NOTHING_DUE, StageOutcome.DONE)]


async def test_a_recorded_stage_that_raises_after_the_mark_ends_stopped_and_reraises() -> None:
    """The resume path's record (ADR-0284 §5:5): the stop's end entry, the error kept.

    The raise continues to the resume, which returns what it established where its
    answer was recorded, and raises as it would have where none was.
    """
    mark = _Mark()
    record = StageRecord()
    _, now = _clock()
    error = PlanningError("refused")

    async def body() -> None:
        mark.stopped = True
        raise error

    with pytest.raises(PlanningError) as caught:
        await run_recorded(
            lambda: record,
            ControllerStage.DRIVE,
            ControllerRule.PARK_ANSWERED,
            clock=now,  # type: ignore[arg-type]  # a plain callable
            body=body,
            stopped=mark,
        )
    assert caught.value is error
    assert _shape(record) == [
        (ControllerStage.DRIVE, ControllerRule.PARK_ANSWERED, StageOutcome.FAILED),
        (ControllerStage.END, ControllerRule.STOPPED, StageOutcome.DONE),
    ]


# --- ADR-0309 §3: the phases' table, the round's step and the per-round guard ----------


_PHASE_PASS: Final = _Facts(
    conversation_turn=True,
    conversation_resolved=True,
    understanding_wired=True,
    windows_decided=True,
    understanding_decided=True,
    understanding_recorded=True,
)


def _phase_due(phases: _Phases, facts: _Facts = _PHASE_PASS) -> Rule:
    return next(rule for rule in ACTIVATION_RULES if rule.answers(replace(facts, phases=phases)))


def test_the_controllers_one_table_is_section_3s_rows_in_order() -> None:
    """ADR-0309 §3's thirteen rows, in order, the last always answering (§2:6, §7:1).

    The old path's rows are gone from it (§3:6): no routing, event summary, goal, turn
    loop, drive or compose row answers on any pass.
    """
    assert [rule.name for rule in ACTIVATION_RULES] == [
        ControllerRule.CONVERSATION_UNRESOLVED,
        ControllerRule.WINDOWS_UNASSEMBLED,
        ControllerRule.NOT_RECALLED,
        ControllerRule.NOT_UNDERSTOOD,
        ControllerRule.STORY_LINKS_UNRECORDED,
        ControllerRule.UNDERSTOOD_NOT_RECALLED,
        ControllerRule.RECALL_UNDIGESTED,
        ControllerRule.FIRST_ROUND_DUE,
        ControllerRule.ROUND_UNAUTHORIZED,
        ControllerRule.ROUND_AUTHORIZED,
        ControllerRule.ROUND_LIMIT_REACHED,
        ControllerRule.ROUND_DUE,
        ControllerRule.NOTHING_DUE,
    ]
    assert ACTIVATION_RULES[-1].answers(_Facts())
    kept = {rule.name for rule in ACTIVATION_RULES}
    assert kept.isdisjoint(
        {
            ControllerRule.ROUTE_UNCHECKED,
            ControllerRule.ROUTE_TAKEN,
            ControllerRule.EVENT_UNSUMMARIZED,
            ControllerRule.ASSOCIATION_DUE,
            ControllerRule.DISAMBIGUATION_RAISED,
            ControllerRule.CONTINUING_UNRECONCILED,
            ControllerRule.UNPLANNED,
            ControllerRule.PLAN_HAS_STEPS,
            ControllerRule.REPLY_OWED,
        }
    )
    assert {rule.makes_due for rule in ACTIVATION_RULES}.isdisjoint(
        {
            ControllerStage.ROUTING,
            ControllerStage.EVENT_SUMMARY,
            ControllerStage.ASSOCIATE_GOAL,
            ControllerStage.ASK_DISAMBIGUATION,
            ControllerStage.RECONCILE,
            ControllerStage.TURN_LOOP,
            ControllerStage.DRIVE,
            ControllerStage.COMPOSE,
        }
    )


def test_recall_runs_again_once_understanding_has_recorded_and_before_the_first_round() -> None:
    """ADR-0308 §2:9, §3's row 6: after the story links, before ``first_round_due``."""
    facts = replace(_PHASE_PASS, recall_wired=True, recall_decided=True)
    rule = _phase_due(_Phases(), facts)
    assert (rule.name, rule.makes_due) == (
        ControllerRule.UNDERSTOOD_NOT_RECALLED,
        ControllerStage.RECALL,
    )
    linking = replace(facts, story_links_wired=True)
    assert _phase_due(_Phases(), linking).name is ControllerRule.STORY_LINKS_UNRECORDED
    assert _phase_due(_Phases(recalled_again=True), facts).name is ControllerRule.FIRST_ROUND_DUE


def test_recall_does_not_run_again_where_it_is_not_wired_or_nothing_is_recorded() -> None:
    assert _phase_due(_Phases()).name is ControllerRule.FIRST_ROUND_DUE
    unrecorded = replace(
        _PHASE_PASS, recall_wired=True, recall_decided=True, understanding_recorded=False
    )
    assert _phase_due(_Phases(), unrecorded).name is ControllerRule.NOTHING_DUE


def test_a_phase_rule_on_a_pass_the_phases_do_not_plan_is_a_defect() -> None:
    with pytest.raises(RuntimeError, match="only on a pass the phases plan"):
        next(rule for rule in ACTIVATION_RULES if rule.answers(_PHASE_PASS))


def test_the_first_round_is_due_once_understanding_has_recorded() -> None:
    """ADR-0307 §8:6, and §3's row 8 following ``story_links_unrecorded``."""
    rule = _phase_due(_Phases())
    assert (rule.name, rule.makes_due) == (ControllerRule.FIRST_ROUND_DUE, ControllerStage.PLANNING)
    linking = replace(_PHASE_PASS, story_links_wired=True)
    assert _phase_due(_Phases(), linking).name is ControllerRule.STORY_LINKS_UNRECORDED


@pytest.mark.parametrize(
    "latest",
    [
        _Phases(rounds=1, latest_round="r1", latest_has_calls=True),
        _Phases(rounds=1, latest_round="r1", latest_has_text=True),
    ],
)
def test_a_round_with_a_call_or_text_is_authorized_first(latest: _Phases) -> None:
    rule = _phase_due(latest)
    assert (rule.name, rule.makes_due) == (
        ControllerRule.ROUND_UNAUTHORIZED,
        ControllerStage.AUTHORIZING,
    )


def test_a_round_with_neither_a_call_nor_text_ends_the_pass() -> None:
    """ADR-0315 §2:3: no progress ends the activation after its message."""
    latest = _Phases(rounds=1, latest_round="r1")
    assert _phase_due(latest).name is ControllerRule.NOTHING_DUE


def test_an_authorized_round_runs_acting_and_digesting_beside_it_for_outside_text() -> None:
    """§3:3: digesting beside acting only where an allowed call may bring outside text."""
    decided = _Phases(
        rounds=1,
        latest_round="r1",
        latest_has_calls=True,
        latest_authorized=True,
        latest_allows=True,
    )
    rule = _phase_due(decided)
    assert (rule.name, rule.makes_due, rule.beside) == (
        ControllerRule.ROUND_AUTHORIZED,
        ControllerStage.ACTING,
        ControllerStage.DIGESTING,
    )
    assert rule.beside_when is not None
    assert not rule.beside_when(replace(_PHASE_PASS, phases=decided))
    assert rule.beside_when(replace(_PHASE_PASS, phases=replace(decided, latest_digests_due=True)))


_FINISHED: Final = _Phases(
    rounds=1,
    latest_round="r",
    latest_has_calls=True,
    latest_calls_beyond_tidy_ups=True,
    latest_authorized=True,
    latest_allows=True,
    latest_acted=True,
)

#: A round whose only calls are tidy-ups, every one of them finished.
_TIDIED: Final = replace(_FINISHED, latest_calls_beyond_tidy_ups=False)


@pytest.mark.parametrize(
    ("latest", "due"),
    [
        # A call other than a tidy-up, finished: another round runs, whatever it brought
        # back, a call done with nothing brought included (ADR-0315 §2:1).
        (_FINISHED, ControllerRule.ROUND_DUE),
        # Nothing was allowed, so nothing ran: every call has finished, refused or
        # needing the user, and another round runs.
        (replace(_FINISHED, latest_allows=False, latest_acted=False), ControllerRule.ROUND_DUE),
        # Only tidy-ups: the activation ends after the round's message (§2:2).
        (_TIDIED, ControllerRule.NOTHING_DUE),
        # Only tidy-ups, refused: a refused tidy-up brings no round either (§2:2).
        (replace(_TIDIED, latest_allows=False, latest_acted=False), ControllerRule.NOTHING_DUE),
        # A round past the limit ends the pass instead of running (§2:4).
        (replace(_FINISHED, rounds=3), ControllerRule.ROUND_LIMIT_REACHED),
        # A tidy-up-only round at the limit ends as nothing due, not as the limit.
        (replace(_TIDIED, rounds=3), ControllerRule.NOTHING_DUE),
        # Calls still running: neither another round nor the end.
        (replace(_FINISHED, latest_acted=False), ControllerRule.ROUND_AUTHORIZED),
    ],
    ids=[
        "finished",
        "nothing-allowed",
        "tidy-ups-only",
        "tidy-ups-refused",
        "past-the-limit",
        "tidy-ups-at-the-limit",
        "still-running",
    ],
)
def test_the_next_round_is_due_once_every_call_other_than_a_tidy_up_has_finished(
    latest: _Phases, due: ControllerRule
) -> None:
    assert _phase_due(latest).name is due


@dataclass
class _Recalling:
    """A recall stage over ``_Facts``: the first run decides, then the second, as scripted."""

    name: ControllerStage = ControllerStage.RECALL
    second_decides: bool = True
    runs: int = 0

    async def run(self, state: _Facts) -> StageResult:
        self.runs += 1
        assert state.phases is not None
        if not state.recall_decided:
            state.recall_decided = True
        elif self.second_decides:
            state.phases.recalled_again = True
        return StageResult(StageOutcome.DONE)


@dataclass
class _PhaseStage:
    """A phase stage over ``_Phases``: it applies its decisions, then ends as scripted."""

    name: ControllerStage
    decide: dict[str, object] = field(default_factory=dict)
    result: StageResult = field(default_factory=lambda: StageResult(StageOutcome.DONE))
    wait: asyncio.Event | None = None
    runs: int = 0
    cancelled: bool = False
    started: asyncio.Event = field(default_factory=asyncio.Event)

    async def run(self, state: _Facts) -> StageResult:
        self.runs += 1
        self.started.set()
        assert state.phases is not None
        for name, value in self.decide.items():
            setattr(state.phases, name, value)
        if self.wait is not None:
            try:
                await self.wait.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return self.result


def _phase_controller(*stages: _PhaseStage | _Recalling) -> ActivationController[_Facts]:
    _, now = _clock()
    return ActivationController(
        stages=stages,
        clock=now,  # type: ignore[arg-type]  # a plain callable
        rules=ACTIVATION_RULES,
    )


_PLANS_A_CALL: Final[dict[str, object]] = {
    "rounds": 1,
    "latest_round": "r1",
    "latest_has_calls": True,
    "latest_has_text": True,
}
_ALLOWS_A_SEARCH: Final[dict[str, object]] = {
    "latest_authorized": True,
    "latest_allows": True,
    "latest_digests_due": True,
}


async def test_one_round_runs_acting_and_digesting_as_one_step_each_with_its_own_entry() -> None:
    """§3:3-§3:4: the step ends when both have, and each records an entry due the rule."""
    record = StageRecord()
    await _phase_controller(
        _PhaseStage(ControllerStage.PLANNING, dict(_PLANS_A_CALL)),
        _PhaseStage(ControllerStage.AUTHORIZING, dict(_ALLOWS_A_SEARCH)),
        _PhaseStage(ControllerStage.ACTING, {"latest_acted": True}),
        _PhaseStage(ControllerStage.DIGESTING),
    ).run(replace(_PHASE_PASS, phases=_Phases()), record)
    assert _shape(record) == [
        (ControllerStage.PLANNING, ControllerRule.FIRST_ROUND_DUE, StageOutcome.DONE),
        (ControllerStage.AUTHORIZING, ControllerRule.ROUND_UNAUTHORIZED, StageOutcome.DONE),
        (ControllerStage.ACTING, ControllerRule.ROUND_AUTHORIZED, StageOutcome.DONE),
        (ControllerStage.DIGESTING, ControllerRule.ROUND_AUTHORIZED, StageOutcome.DONE),
        (ControllerStage.END, ControllerRule.NOTHING_DUE, StageOutcome.DONE),
    ]
    acting, digesting = record.entries[2:4]
    assert acting.started_at == digesting.started_at


async def test_acting_alone_runs_where_no_allowed_call_may_bring_outside_text() -> None:
    digesting = _PhaseStage(ControllerStage.DIGESTING)
    record = StageRecord()
    await _phase_controller(
        _PhaseStage(ControllerStage.PLANNING, dict(_PLANS_A_CALL)),
        _PhaseStage(
            ControllerStage.AUTHORIZING, {"latest_authorized": True, "latest_allows": True}
        ),
        _PhaseStage(ControllerStage.ACTING, {"latest_acted": True}),
        digesting,
    ).run(replace(_PHASE_PASS, phases=_Phases()), record)
    assert digesting.runs == 0
    assert [entry.stage for entry in record.entries][2:] == [
        ControllerStage.ACTING,
        ControllerStage.END,
    ]


@pytest.mark.parametrize(
    ("outcome", "ending"),
    [
        (StageOutcome.FAILED, ControllerRule.STAGE_FAILED),
        (StageOutcome.TIMED_OUT, ControllerRule.STAGE_TIMED_OUT),
    ],
)
async def test_acting_that_does_not_end_done_cancels_digesting_and_ends_on_its_error(
    outcome: StageOutcome, ending: ControllerRule
) -> None:
    """§3:4: the fixed default for acting; digesting, cancelled, records ``failed``."""
    error = PlanningError("the claim failed")
    digesting = _PhaseStage(ControllerStage.DIGESTING, wait=asyncio.Event())
    record = StageRecord()
    with pytest.raises(PlanningError) as caught:
        await _phase_controller(
            _PhaseStage(ControllerStage.PLANNING, dict(_PLANS_A_CALL)),
            _PhaseStage(ControllerStage.AUTHORIZING, dict(_ALLOWS_A_SEARCH)),
            _PhaseStage(ControllerStage.ACTING, result=StageResult(outcome, error)),
            digesting,
        ).run(replace(_PHASE_PASS, phases=_Phases()), record)
    assert caught.value is error
    assert digesting.cancelled
    assert _shape(record)[2:] == [
        (ControllerStage.ACTING, ControllerRule.ROUND_AUTHORIZED, outcome),
        (ControllerStage.DIGESTING, ControllerRule.ROUND_AUTHORIZED, StageOutcome.FAILED),
        (ControllerStage.END, ending, StageOutcome.DONE),
    ]


async def test_a_cancelled_step_cancels_both_stages_and_ends_interrupted() -> None:
    acting = _PhaseStage(ControllerStage.ACTING, wait=asyncio.Event())
    digesting = _PhaseStage(ControllerStage.DIGESTING, wait=asyncio.Event())
    record = StageRecord()
    controller = _phase_controller(
        _PhaseStage(ControllerStage.PLANNING, dict(_PLANS_A_CALL)),
        _PhaseStage(ControllerStage.AUTHORIZING, dict(_ALLOWS_A_SEARCH)),
        acting,
        digesting,
    )
    task = asyncio.ensure_future(controller.run(replace(_PHASE_PASS, phases=_Phases()), record))
    await asyncio.gather(acting.started.wait(), digesting.started.wait())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert acting.cancelled
    assert digesting.cancelled
    assert record.entries[-1].due is ControllerRule.INTERRUPTED


@dataclass
class _NextRound(_PhaseStage):
    """A planning stage that records one more round each time it runs."""

    async def run(self, state: _Facts) -> StageResult:
        result = await super().run(state)
        assert state.phases is not None
        state.phases.rounds += 1
        state.phases.latest_round = f"r{state.phases.rounds}"
        return result


async def test_planning_runs_once_per_round_until_the_round_limit_ends_the_pass() -> None:
    """§3:5, ADR-0307 §11: the guard is scoped to the latest round, not to the pass."""
    planning = _NextRound(
        ControllerStage.PLANNING,
        {
            "latest_has_calls": True,
            "latest_calls_beyond_tidy_ups": True,
            "latest_authorized": True,
        },
    )
    record = StageRecord()
    await _phase_controller(planning).run(
        replace(_PHASE_PASS, phases=_Phases(round_limit=3)), record
    )
    assert planning.runs == 3
    assert [entry.due for entry in record.entries] == [
        ControllerRule.FIRST_ROUND_DUE,
        ControllerRule.ROUND_DUE,
        ControllerRule.ROUND_DUE,
        ControllerRule.ROUND_LIMIT_REACHED,
    ]


async def test_planning_due_again_for_a_round_it_already_followed_is_guarded() -> None:
    stuck = _PhaseStage(
        ControllerStage.PLANNING,
        {
            "rounds": 1,
            "latest_round": "r1",
            "latest_has_calls": True,
            "latest_authorized": True,
            "latest_calls_beyond_tidy_ups": True,
        },
    )
    record = StageRecord()
    await _phase_controller(stuck).run(replace(_PHASE_PASS, phases=_Phases()), record)
    assert stuck.runs == 2
    assert record.entries[-1].due is ControllerRule.STAGE_REPEATED


async def test_recall_runs_twice_on_a_pass_the_second_under_its_own_row() -> None:
    """ADR-0308 §2:9-§2:10: first before understanding, then once it has recorded."""
    recall = _Recalling()
    record = StageRecord()
    await _phase_controller(
        recall, _PhaseStage(ControllerStage.PLANNING, {"rounds": 1, "latest_round": "r1"})
    ).run(replace(_PHASE_PASS, recall_wired=True, phases=_Phases()), record)
    assert recall.runs == 2
    assert _shape(record) == [
        (ControllerStage.RECALL, ControllerRule.NOT_RECALLED, StageOutcome.DONE),
        (ControllerStage.RECALL, ControllerRule.UNDERSTOOD_NOT_RECALLED, StageOutcome.DONE),
        (ControllerStage.PLANNING, ControllerRule.FIRST_ROUND_DUE, StageOutcome.DONE),
        (ControllerStage.END, ControllerRule.NOTHING_DUE, StageOutcome.DONE),
    ]


async def test_a_pass_that_would_run_recall_a_third_time_is_guarded() -> None:
    """ADR-0308 §2:10: ADR-0280 §4:6's guard ends it, recall having run twice."""
    recall = _Recalling(second_decides=False)
    planning = _PhaseStage(ControllerStage.PLANNING)
    record = StageRecord()
    await _phase_controller(recall, planning).run(
        replace(_PHASE_PASS, recall_wired=True, phases=_Phases()), record
    )
    assert (recall.runs, planning.runs) == (2, 0)
    assert [entry.due for entry in record.entries] == [
        ControllerRule.NOT_RECALLED,
        ControllerRule.UNDERSTOOD_NOT_RECALLED,
        ControllerRule.STAGE_REPEATED,
    ]


# --- ADR-0308 §4:5-§4:6, ADR-0309 §3's row 7: recall's digest ---------------------------


_RECALLED_OUTSIDE: Final = _Phases(recalled_again=True, recall_kept_outside=True)


def test_recall_digest_is_due_once_the_second_run_has_decided_and_kept_outside_records() -> None:
    """§4:5: after the second run's row, before ``first_round_due``."""
    rule = _phase_due(_RECALLED_OUTSIDE)
    assert (rule.name, rule.makes_due, rule.beside) == (
        ControllerRule.RECALL_UNDIGESTED,
        ControllerStage.DIGESTING,
        None,
    )
    # The second run's row is read first: no digest before the second-run decision.
    facts = replace(_PHASE_PASS, recall_wired=True, recall_decided=True)
    assert (
        _phase_due(replace(_RECALLED_OUTSIDE, recalled_again=False), facts).name
        is ControllerRule.UNDERSTOOD_NOT_RECALLED
    )


@pytest.mark.parametrize(
    "phases",
    [
        # No second-run decision: recall's not wired, so neither run row answers.
        _Phases(recall_kept_outside=True),
        # Neither run kept a memory record whose source is outside.
        _Phases(recalled_again=True),
        # Recall's digest is recorded, whatever came of it.
        replace(_RECALLED_OUTSIDE, recall_digested=True),
    ],
)
def test_recall_digest_is_not_due_otherwise_and_the_first_round_follows(phases: _Phases) -> None:
    assert _phase_due(phases).name is ControllerRule.FIRST_ROUND_DUE


def test_the_first_round_waits_for_recall_digest() -> None:
    """§4:6, ADR-0307 §8:6: the second run has finished only once its digest is recorded."""
    assert _phase_due(_RECALLED_OUTSIDE).name is ControllerRule.RECALL_UNDIGESTED
    digested = replace(_RECALLED_OUTSIDE, recall_digested=True)
    assert _phase_due(digested).name is ControllerRule.FIRST_ROUND_DUE


async def test_recall_digest_runs_once_before_the_first_round_then_digesting_beside_acting() -> (
    None
):
    """ADR-0309 §3:5: once for recall's digest, and once per round beside acting."""
    recall = _Recalling()
    digesting = _PhaseStage(ControllerStage.DIGESTING, {"recall_digested": True})
    record = StageRecord()
    await _phase_controller(
        recall,
        digesting,
        _PhaseStage(ControllerStage.PLANNING, dict(_PLANS_A_CALL)),
        _PhaseStage(ControllerStage.AUTHORIZING, dict(_ALLOWS_A_SEARCH)),
        _PhaseStage(ControllerStage.ACTING, {"latest_acted": True}),
    ).run(
        replace(_PHASE_PASS, recall_wired=True, phases=_Phases(recall_kept_outside=True)),
        record,
    )
    assert digesting.runs == 2
    assert _shape(record) == [
        (ControllerStage.RECALL, ControllerRule.NOT_RECALLED, StageOutcome.DONE),
        (ControllerStage.RECALL, ControllerRule.UNDERSTOOD_NOT_RECALLED, StageOutcome.DONE),
        (ControllerStage.DIGESTING, ControllerRule.RECALL_UNDIGESTED, StageOutcome.DONE),
        (ControllerStage.PLANNING, ControllerRule.FIRST_ROUND_DUE, StageOutcome.DONE),
        (ControllerStage.AUTHORIZING, ControllerRule.ROUND_UNAUTHORIZED, StageOutcome.DONE),
        (ControllerStage.ACTING, ControllerRule.ROUND_AUTHORIZED, StageOutcome.DONE),
        (ControllerStage.DIGESTING, ControllerRule.ROUND_AUTHORIZED, StageOutcome.DONE),
        (ControllerStage.END, ControllerRule.NOTHING_DUE, StageOutcome.DONE),
    ]


async def test_a_pass_that_would_run_recall_digest_again_is_guarded() -> None:
    """§3:5: digesting runs once for recall's digest; ADR-0280 §4:6's guard ends a second."""
    stuck = _PhaseStage(ControllerStage.DIGESTING)
    planning = _PhaseStage(ControllerStage.PLANNING)
    record = StageRecord()
    await _phase_controller(stuck, planning).run(
        replace(_PHASE_PASS, phases=replace(_RECALLED_OUTSIDE)), record
    )
    assert (stuck.runs, planning.runs) == (1, 0)
    assert [entry.due for entry in record.entries] == [
        ControllerRule.RECALL_UNDIGESTED,
        ControllerRule.STAGE_REPEATED,
    ]


async def test_a_failed_recall_digest_tolerated_goes_on_to_the_first_round() -> None:
    """§4:12: digesting is failure-tolerant; its decision is held, so the row is done."""
    digesting = _PhaseStage(
        ControllerStage.DIGESTING,
        {"recall_digested": True},
        result=StageResult(StageOutcome.FAILED, PlanningError("unread"), tolerated=True),
    )
    planning = _PhaseStage(ControllerStage.PLANNING, {"rounds": 1, "latest_round": "r1"})
    record = StageRecord()
    await _phase_controller(digesting, planning).run(
        replace(_PHASE_PASS, phases=replace(_RECALLED_OUTSIDE)), record
    )
    assert _shape(record) == [
        (ControllerStage.DIGESTING, ControllerRule.RECALL_UNDIGESTED, StageOutcome.FAILED),
        (ControllerStage.PLANNING, ControllerRule.FIRST_ROUND_DUE, StageOutcome.DONE),
        (ControllerStage.END, ControllerRule.NOTHING_DUE, StageOutcome.DONE),
    ]


# --- ADR-0314 §4, §5:4: the controller's step entries and the activation it binds ---------

_ACTIVATION: Final = "3f2b8c4e-1d5a-4e7b-9c0d-2a6f8e1b7c35"


@dataclass
class _Diagnosing:
    """A stage that writes one entry of its own, and records what it saw bound."""

    name: ControllerStage
    decide: str
    sink: FakeDiagnosticSink
    seen: list[str | None] = field(default_factory=list)

    async def run(self, state: _Facts) -> StageResult:
        self.seen.append(diagnosed_activation_id())
        await write_diagnostic(
            self.sink, DiagnosticSource.UNDERSTANDING, DiagnosticKind.GIVEN, lambda: {"n": 1}
        )
        setattr(state, self.decide, True)
        return StageResult(StageOutcome.DONE)


def _diagnosed(
    *stages: object, sink: FakeDiagnosticSink | None, activation_id: str | None = _ACTIVATION
) -> ActivationController[_Facts]:
    _, now = _clock()
    return ActivationController(
        stages=stages,  # type: ignore[arg-type]  # fakes standing for stages
        clock=now,  # type: ignore[arg-type]  # a plain callable
        rules=_MECHANISM_RULES,
        activation_id=activation_id,
        diagnostics=sink,
    )


async def test_each_entry_the_controller_appends_is_written_as_a_step() -> None:
    """§4: the rule that answered, the stage, when it started and ended, and how it ended."""
    sink = FakeDiagnosticSink()
    record = StageRecord()

    await _diagnosed(
        _FakeStage(ControllerStage.UNDERSTANDING, "understanding_decided"),
        _FakeStage(ControllerStage.EVENT_SUMMARY, "event_summarized"),
        sink=sink,
    ).run(_Facts(informational_event=True, understanding_wired=True, windows_decided=True), record)

    steps = sink.of(DiagnosticSource.CONTROLLER, DiagnosticKind.STEP)
    assert [dict(step.body) for step in steps] == [
        entry.model_dump(mode="json") for entry in record.entries
    ]
    assert {step.activation_id for step in steps} == {_ACTIVATION}


async def test_every_stage_runs_under_the_activation_the_controller_binds() -> None:
    """§5:4: a stage's own entries are written for the activation, with no argument."""
    sink = FakeDiagnosticSink()
    stage = _Diagnosing(ControllerStage.EVENT_SUMMARY, "event_summarized", sink)

    await _diagnosed(stage, sink=sink).run(_Facts(informational_event=True), StageRecord())

    assert stage.seen == [_ACTIVATION]
    assert [one.activation_id for one in sink.of(DiagnosticSource.UNDERSTANDING)] == [_ACTIVATION]
    assert diagnosed_activation_id() is None


async def test_a_failed_step_is_written_with_its_failure() -> None:
    error = PlanningError("the store is down")
    sink = FakeDiagnosticSink()
    controller = _diagnosed(
        _FakeStage(ControllerStage.EVENT_SUMMARY, result=StageResult(StageOutcome.FAILED, error)),
        sink=sink,
    )

    with pytest.raises(PlanningError):
        await controller.run(_Facts(informational_event=True), StageRecord())

    failed, ended = sink.of(DiagnosticSource.CONTROLLER)
    assert failed.body["outcome"] == "failed"
    assert failed.body["failure"] == {"class": "PlanningError", "message": "the store is down"}
    assert (ended.body["stage"], ended.body["due"]) == ("end", "stage_failed")


async def test_a_pass_with_no_admitted_activation_or_no_sink_writes_nothing() -> None:
    """§5:4: nothing is written where none is bound; §2:1: nor where the record is off."""
    sink = FakeDiagnosticSink()
    unbound = _Diagnosing(ControllerStage.EVENT_SUMMARY, "event_summarized", sink)

    await _diagnosed(unbound, sink=sink, activation_id=None).run(
        _Facts(informational_event=True), StageRecord()
    )
    await _diagnosed(_FakeStage(ControllerStage.EVENT_SUMMARY, "event_summarized"), sink=None).run(
        _Facts(informational_event=True), StageRecord()
    )

    assert unbound.seen == [None]
    assert sink.recorded == ()


async def test_a_cancelled_pass_awaits_no_write_on_its_way_out() -> None:
    """The interrupted end entry is appended, and nothing is awaited under cancellation."""
    sink = FakeDiagnosticSink()
    entered = asyncio.Event()

    async def hang(_: _Facts) -> None:
        entered.set()
        await asyncio.Event().wait()

    record = StageRecord()
    running = asyncio.ensure_future(
        _diagnosed(Stage(ControllerStage.EVENT_SUMMARY, hang), sink=sink).run(
            _Facts(informational_event=True), record
        )
    )
    await entered.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert record.entries[-1].due is ControllerRule.INTERRUPTED
    assert sink.of(DiagnosticSource.CONTROLLER) == ()
