"""Unit tests for the model-backed planner (ADR-0047).

Drives :class:`~ai_assistant.planning.ModelBackedPlanner` through the shared
``PlannerContract`` and against :class:`FakeModelProvider`, so extraction,
malformed-output handling, the bounded repair round, and memory personalization
are asserted deterministically — a fixed clock and a counter id factory make each
plan reproducible byte-for-byte.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from planner_contract import PlannerContract

from ai_assistant.core.errors import ModelError, PlanningError
from ai_assistant.core.types import (
    CurrentContext,
    Goal,
    MemorySource,
    Message,
    PreferenceMemory,
    Provenance,
    Role,
    TimeOfDay,
)
from ai_assistant.planning import ModelBackedPlanner
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

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


async def test_max_attempts_above_two_allows_multiple_repair_rounds() -> None:
    """Two malformed replies then a valid one succeeds at max_attempts=3."""
    model = FakeModelProvider.scripted("bad one", "bad two", _VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter(), max_attempts=3)

    plan = await planner.plan(_goal(), context=_context())

    assert [step.capability for step in plan.steps] == ["search_housing", "book_movers"]
    assert model.call_count == 3


async def test_max_attempts_three_exhausts_after_three_calls() -> None:
    model = FakeModelProvider.scripted("bad one", "bad two", "bad three")
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter(), max_attempts=3)

    with pytest.raises(PlanningError):
        await planner.plan(_goal(), context=_context())
    assert model.call_count == 3


async def test_max_attempts_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        ModelBackedPlanner(FakeModelProvider(_VALID_REPLY), max_attempts=0)


@pytest.mark.parametrize("bad", [1.5, True, "2", None])
async def test_non_int_max_attempts_is_rejected(bad: object) -> None:
    """A non-int (bool included) is a TypeError at construction, not a later crash."""
    with pytest.raises(TypeError, match="max_attempts"):
        ModelBackedPlanner(FakeModelProvider(_VALID_REPLY), max_attempts=bad)  # type: ignore[arg-type]


async def test_deeply_nested_json_becomes_planning_error() -> None:
    """A pathologically nested payload enters the repair path, not a RecursionError."""
    depth = sys.getrecursionlimit() + 100
    reply = '{"steps":' + "[" * depth + "]" * depth + "}"

    with pytest.raises(PlanningError):
        await _planner(reply).plan(_goal(), context=_context())


async def test_oversized_integer_becomes_planning_error() -> None:
    """An over-limit integer literal raises a plain ValueError; it is still bounded."""
    big = "1" * (sys.get_int_max_str_digits() + 100)
    reply = '{"steps":[{"intent":"x","capability":"do_x","parameters":{"n":' + big + "}}]}"
    model = FakeModelProvider(reply)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())

    with pytest.raises(PlanningError):
        await planner.plan(_goal(), context=_context())
    assert model.call_count == 2


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


# --- one observation of the caller's goal (ADR-0065) -------------------------


class _GatedModel:
    """A ``ModelProvider`` that parks the first call until the test releases it.

    Structurally implements
    :class:`~ai_assistant.core.protocols.ModelProvider`. ``FakeModelProvider``
    cannot express this: its ``complete`` never suspends, so a caller has no
    moment at which ``plan`` is genuinely parked. Here the first ``complete``
    announces that ``plan`` has reached its first — and widest — suspension
    point, then waits, which hands control back to the test's own task while
    ``plan`` is still in flight. Later calls (the bounded repair round) answer
    immediately, so only one window has to be coordinated.
    """

    def __init__(self, *replies: str) -> None:
        self._replies = deque(replies)
        self.reached = asyncio.Event()
        self.resume = asyncio.Event()
        self.calls: list[tuple[Message, ...]] = []

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,  # part of the ModelProvider signature; unused here
    ) -> Message:
        """Record the conversation, park the first call, then reply."""
        self.calls.append(tuple(m.model_copy(deep=True) for m in messages))
        if not self.reached.is_set():
            self.reached.set()
            await self.resume.wait()
        return Message(role=Role.ASSISTANT, content=self._replies.popleft())


async def test_the_plan_names_the_goal_the_model_was_shown() -> None:
    """A goal mutated *during* the model call cannot reach the plan (ADR-0065).

    The mutation lands while ``plan`` is parked inside ``complete`` — not before
    the call and not after it returned, which is the only window that
    distinguishes one observation from two. ``ActionPlan`` is frozen, so a
    ``goal_id`` taken from a second observation would be permanently wrong in an
    auditable record (ADR-0014 §2).
    """
    model = _GatedModel(_VALID_REPLY)
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())
    goal = _goal("g1")

    task = asyncio.ensure_future(planner.plan(goal, context=_context()))
    await model.reached.wait()
    goal.id = "g-tampered"
    goal.statement = "relocate to Berlin"
    model.resume.set()
    plan = await task

    assert plan.goal_id == "g1"
    # ...and that id agrees with the single observation the prompt was rendered
    # from, which is the property: one result, one version of the input.
    prompt = model.calls[0][1].content
    assert "relocate to Lisbon" in prompt
    assert "Berlin" not in prompt


async def test_the_exhaustion_message_names_the_goal_the_call_began_with() -> None:
    """The give-up message is derived from the same one observation (ADR-0065).

    It is read after every model call, so it is the second post-await read of the
    caller's goal in this method, and it names a goal in an error a human acts on.
    """
    model = _GatedModel("garbage one", "garbage two")
    planner = ModelBackedPlanner(model, now=_fixed_now, id_factory=_counter())
    goal = _goal("g1")

    task = asyncio.ensure_future(planner.plan(goal, context=_context()))
    await model.reached.wait()
    goal.id = "g-tampered"
    model.resume.set()

    with pytest.raises(PlanningError) as caught:
        await task
    assert "g1" in str(caught.value)
    assert "g-tampered" not in str(caught.value)
