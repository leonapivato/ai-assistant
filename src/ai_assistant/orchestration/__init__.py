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
feedback → proposal → policy → memory).

``StepExecutor`` is the ``execute`` stage (ADR-0029 §8): it claims a plan step,
runs one authorised call through an injected ``ToolInvoker``, and commits what
came back.

``StepRunner`` is the join between them (ADR-0037): the tool-selection and
permission stages. It takes a ``PlanStep``, finds the tool advertising its
capability, has an ``ActionPolicy`` rule on it, records the
``PermissionDecision``, and hands the executor a ``ToolCall`` built from the
audit trail's own copy of that decision — or disposes of the step without
running it, saying durably why.
"""

from ai_assistant.orchestration.executor import StepExecutor
from ai_assistant.orchestration.loop import LearningLoop, TurnResult
from ai_assistant.orchestration.runner import Disposition, StepDisposition, StepRunner

__all__ = [
    "Disposition",
    "LearningLoop",
    "StepDisposition",
    "StepExecutor",
    "StepRunner",
    "TurnResult",
]
