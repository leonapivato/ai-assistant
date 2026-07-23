"""Planning: turns complex requests into executable plans.

Breaks a request into ordered steps, tracks progress, and decides what to do
next. Consumes the model layer for reasoning and the tool registry for the
actions a plan can take; owns the plan/step data model and its lifecycle.

Contract: :class:`~ai_assistant.core.protocols.Planner` produces an
``ActionPlan`` from a ``Goal``; :class:`~ai_assistant.core.protocols.PlanStore`
holds the durable goals, plans and execution state (ADR-0014).
"""

from __future__ import annotations

from ai_assistant.planning.execution import DEFAULT_MAX_ATTEMPTS, PlanExecution
from ai_assistant.planning.planner import DEFAULT_PLAN_ATTEMPTS, ModelBackedPlanner
from ai_assistant.planning.store import InMemoryPlanStore

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_PLAN_ATTEMPTS",
    "InMemoryPlanStore",
    "ModelBackedPlanner",
    "PlanExecution",
]
