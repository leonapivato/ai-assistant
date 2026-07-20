"""Orchestration: the engine that ties everything together.

The heart of the product. For each request it runs the pipeline:
intent understanding → context assembly → memory retrieval → planning →
tool selection → permission checking → execution → learning/memory updates.

It depends *only* on the Protocols in ``core.protocols`` — never on concrete
subsystem implementations, which are injected. That inversion is what keeps the
engine testable and the subsystems independently replaceable.

Contract: this package *consumes* contracts; it wires implementations together.

``LearningLoop`` is the first working slice of that pipeline: the closed
learning loop of ADR-0022 (intent → context → retrieval → planning, then
feedback → proposal → policy → memory). Tool selection, permission checking and
execution join it when those subsystems can actually invoke something.
"""

from ai_assistant.orchestration.loop import LearningLoop, TurnResult

__all__ = ["LearningLoop", "TurnResult"]
