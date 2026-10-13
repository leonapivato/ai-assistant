"""ADR-0249 §11's carrier, and the absences §1 and §8 admit exactly one route to.

The loop builds the goal record and its revisions; ``Engine`` persists them, at the one
site that persists a plan today. What crosses the wire is the **brief**; the record
travels inside ``ai_assistant.orchestration`` as data, on ``RespondedTurn.goal``.

This file carries §16's arms that name L1 and that only an engine-level case can reach:
item 8 (the bootstrap is byte-equal), item 14 (a turn that ends early persists nothing),
and item 18 (the absences have exactly one producer).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from test_engine import Harness, NoStepPlanner

if TYPE_CHECKING:
    import pytest


def test_the_loop_holds_no_plan_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0228 §5, restated because ADR-0249 §11 relies on it.

    "No lane adds a second persistence site, gives ``LearningLoop`` a ``PlanStore``, or
    carries a plan out of a failing turn in order to write it" — and §11 adds the goal
    record to what that clause covers, which only holds while the loop cannot write.
    """
    del monkeypatch
    harness = Harness(planner=NoStepPlanner())
    loop: Any = harness.engine._loop

    assert not any(hasattr(getattr(loop, name, None), "save_goal") for name in vars(loop)), (
        "no attribute of the loop is a PlanStore"
    )
