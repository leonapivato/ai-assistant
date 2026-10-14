"""Planning: the plan store, holding an activation's stop record and effect records.

Owns the durable state the phases keep about an activation: the stop record that
refuses its further effects (ADR-0297 §1) and acting's record of each effect it
claims and finishes (ADR-0306 §6), with the ADR-0004 data rights over both.

Contract: :class:`~ai_assistant.core.protocols.PlanStore` (ADR-0014). The goals,
plans and step execution the old path kept here retired with it, and so did its
model-backed planner (ADR-0309 §5).
"""

from __future__ import annotations

from ai_assistant.planning.sqlite_store import SqlitePlanStore
from ai_assistant.planning.store import InMemoryPlanStore

__all__ = [
    "InMemoryPlanStore",
    "SqlitePlanStore",
]
