"""Planning: the durable goals and plans, and the execution state over them.

Owns the plan/step data model and its lifecycle: the stores that hold goals,
plans and their progress, and the execution that tracks a plan step by step.

Contract: :class:`~ai_assistant.core.protocols.PlanStore` holds the durable
goals, plans and execution state (ADR-0014). No implementation of
:class:`~ai_assistant.core.protocols.Planner` lives here: the model-backed one
retired with the old path (ADR-0309 §5).
"""

from __future__ import annotations

from ai_assistant.planning.execution import DEFAULT_MAX_ATTEMPTS, PlanExecution
from ai_assistant.planning.sqlite_store import SqlitePlanStore
from ai_assistant.planning.store import InMemoryPlanStore

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "InMemoryPlanStore",
    "PlanExecution",
    "SqlitePlanStore",
]
