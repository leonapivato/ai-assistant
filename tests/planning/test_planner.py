"""Unit tests for the model-backed planner (ADR-0047).

Drives :class:`~ai_assistant.planning.ModelBackedPlanner` through the shared
``PlannerContract`` and against :class:`FakeModelProvider`, so extraction,
malformed-output handling, the bounded repair round, and memory personalization
are asserted deterministically — a fixed clock and a counter id factory make each
plan reproducible byte-for-byte.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from planner_contract import PlannerContract

from ai_assistant.core.errors import ModelError, PlanningError
from ai_assistant.core.types import (
    CurrentContext,
    Goal,
    MemorySource,
    PreferenceMemory,
    Provenance,
    Role,
    TimeOfDay,
)
from ai_assistant.planning import ModelBackedPlanner
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import Planner

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _fixed_now() -> datetime:
    return _WHEN


def _counter() -> Callable[[], str]:
    """A deterministic id factory: ``id-0``, ``id-1``, ... in call order."""
    count = 0

    def factory() -> str:
        nonlocal count
        value = f"id-{count}"
        count += 1
        return value

    return factory


def _goal(goal_id: str = "g1") -> Goal:
    return Goal(
        id=goal_id,
        statement="relocate to Lisbon",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN
        ),
        created_at=_WHEN,
    )


def _context() -> CurrentContext:
    return CurrentContext(
        now=_WHEN,
        time_of_day=TimeOfDay.MORNING,
        is_weekend=False,
        within_working_hours=True,
    )


_VALID_REPLY = json.dumps(
    {
        "rationale": "two steps to relocate",
        "steps": [
            {
                "intent": "find a place",
                "capability": "search_housing",
                "parameters": {"city": "Lisbon"},
            },
            {"intent": "book the move", "capability": "book_movers", "parameters": {}},
        ],
    }
)


def _planner(reply: str = _VALID_REPLY) -> ModelBackedPlanner:
    return ModelBackedPlanner(
        FakeModelProvider(reply),
        now=_fixed_now,
        id_factory=_counter(),
    )


class TestModelBackedPlannerContract(PlannerContract):
    """Runs ModelBackedPlanner through the shared Planner conformance suite."""

    @pytest.fixture
    def planner(self) -> Planner:
        return _planner()


async def test_extracts_capabilities_in_order() -> None:
    plan = await _planner().plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]
    assert [step.intent for step in plan.steps] == ["find a place", "book the move"]
    assert plan.rationale == "two steps to relocate"
    assert dict(plan.steps[0].parameters) == {"city": "Lisbon"}


async def test_ids_are_minted_from_the_factory_not_the_model() -> None:
    """The plan id and step ids come from the injected factory, in call order."""
    plan = await _planner().plan(_goal(), context=_context())

    # Steps are validated first (id-0, id-1), then the plan id (id-2).
    assert [step.id for step in plan.steps] == ["id-0", "id-1"]
    assert plan.id == "id-2"
    assert plan.goal_id == "g1"
    assert plan.created_at == _WHEN


async def test_tolerates_prose_and_code_fence_around_the_object() -> None:
    wrapped = f"Sure! Here is the plan:\n```json\n{_VALID_REPLY}\n```\nHope that helps."
    plan = await _planner(wrapped).plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]


async def test_memories_reach_the_prompt() -> None:
    """Retrieved memory is rendered into the prompt — what makes a plan personal."""
    model = FakeModelProvider(_VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())
    memory = PreferenceMemory(
        id="m1",
        content="prefers a quiet neighbourhood",
        preference="quiet neighbourhood",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.8, last_updated=_WHEN),
    )

    await planner.plan(_goal(), context=_context(), memories=[memory])

    user_turn = model.last_messages[1]
    assert user_turn.role is Role.USER
    assert "prefers a quiet neighbourhood" in user_turn.content


async def test_no_memories_is_a_generic_request() -> None:
    model = FakeModelProvider(_VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    await planner.plan(_goal(), context=_context())

    assert "No stored memories" in model.last_messages[1].content


async def test_unparseable_output_raises_planning_error() -> None:
    with pytest.raises(PlanningError):
        await _planner("I cannot help with that.").plan(_goal(), context=_context())


async def test_empty_steps_raises_planning_error() -> None:
    reply = json.dumps({"rationale": "nothing to do", "steps": []})
    with pytest.raises(PlanningError):
        await _planner(reply).plan(_goal(), context=_context())


async def test_blank_capability_raises_planning_error() -> None:
    reply = json.dumps({"steps": [{"intent": "x", "capability": "  "}]})
    with pytest.raises(PlanningError):
        await _planner(reply).plan(_goal(), context=_context())


async def test_non_object_parameters_raises_planning_error() -> None:
    reply = json.dumps({"steps": [{"intent": "x", "capability": "do_x", "parameters": [1, 2]}]})
    with pytest.raises(PlanningError):
        await _planner(reply).plan(_goal(), context=_context())


async def test_step_missing_capability_raises_planning_error() -> None:
    reply = json.dumps({"steps": [{"intent": "x"}]})
    with pytest.raises(PlanningError):
        await _planner(reply).plan(_goal(), context=_context())


async def test_repair_round_recovers_after_one_malformed_reply() -> None:
    """A malformed first reply is retried once; the second, valid reply wins."""
    model = FakeModelProvider.scripted("not json at all", _VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    plan = await planner.plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]
    assert model.call_count == 2


async def test_repair_is_bounded_by_max_attempts() -> None:
    """Two malformed replies exhaust the default two attempts, then it gives up."""
    model = FakeModelProvider.scripted("garbage one", "garbage two")
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    with pytest.raises(PlanningError):
        await planner.plan(_goal(), context=_context())
    assert model.call_count == 2


async def test_single_attempt_does_not_repair() -> None:
    model = FakeModelProvider("not json")
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter(), max_attempts=1)

    with pytest.raises(PlanningError):
        await planner.plan(_goal(), context=_context())
    assert model.call_count == 1


async def test_repair_prompt_echoes_the_reason_and_carries_the_bad_reply() -> None:
    model = FakeModelProvider.scripted("nope", _VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    await planner.plan(_goal(), context=_context())

    # The second call's conversation carries the bad reply and a repair turn.
    second_call = model.calls[1].messages
    assert any(m.role is Role.ASSISTANT and m.content == "nope" for m in second_call)
    assert second_call[-1].role is Role.USER
    assert "only the JSON object" in second_call[-1].content


async def test_max_attempts_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        ModelBackedPlanner(FakeModelProvider(_VALID_REPLY), max_attempts=0)


async def test_model_error_propagates_unwrapped() -> None:
    """A provider transport failure stays a ModelError, not a PlanningError."""

    def boom(_messages: object) -> str:
        raise RuntimeError("provider down")

    model = FakeModelProvider(boom)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    with pytest.raises(ModelError):
        await planner.plan(_goal(), context=_context())


async def test_clock_misread_surfaces_as_planning_error() -> None:
    """A naive clock reading is a PlanningError, not a raw ValueError (ADR-0026)."""

    def naive() -> datetime:
        return datetime(2026, 1, 1)  # noqa: DTZ001 - intentionally naive for the test

    planner = ModelBackedPlanner(FakeModelProvider(_VALID_REPLY), now=naive, id_factory=_counter())

    with pytest.raises(PlanningError):
        await planner.plan(_goal(), context=_context())
