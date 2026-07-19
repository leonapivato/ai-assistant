"""The contracts (Protocols) each subsystem implements.

This is the most important file for parallel, agent-driven development. Every
subsystem is defined here as a ``typing.Protocol`` — a structural interface with
no implementation. The `orchestration` engine depends only on these Protocols,
so a concrete implementation of any one subsystem can be written, reviewed,
swapped, or mocked in tests without touching the others.

Guidelines when evolving these contracts:
  * A Protocol change is a breaking change — call it out in review and record
    the decision in ``docs/adr/`` before implementing against it.
  * Prefer adding a new Protocol over widening an existing one.
  * Keep methods ``async`` where they touch I/O (models, memory, tools) so the
    whole system composes on one event loop.

Only two exemplar contracts are defined for now (``ModelProvider`` and
``MemoryStore``). The remaining subsystems declared in the architecture add
their Protocols here as they are designed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import (
        ActionPlan,
        CurrentContext,
        Embedding,
        ExecutionState,
        FeedbackEvent,
        Goal,
        GoalDeletion,
        MemoryDecision,
        MemoryKind,
        MemoryRecord,
        MemoryUpdateProposal,
        Message,
        PlanExport,
        StepTransition,
    )


@runtime_checkable
class ModelProvider(Protocol):
    """A model-agnostic language-model client.

    Concrete implementations (in `models`) wrap pydantic-ai so the rest of the
    system never imports a provider SDK directly. This is the seam that makes
    the assistant model-agnostic.
    """

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        """Produce the assistant's next message given the conversation so far.

        Args:
            messages: Conversation history, oldest first.
            model: Optional ``"provider:model"`` override; falls back to the
                configured default when ``None``.

        Returns:
            The assistant's reply as a :class:`~ai_assistant.core.types.Message`.
        """
        ...


@runtime_checkable
class Embedder(Protocol):
    """Turns text into dense vectors for semantic retrieval (see ADR-0006).

    A model-agnostic embedding seam, separate from :class:`ModelProvider`
    because embedding is a distinct capability a provider may not offer.

    An embedder is bound to a single model. Per-call model selection is
    intentionally omitted: vectors from different models are not comparable, so
    a store must embed everything with one model (ADR-0006 §4).
    """

    @property
    def model_id(self) -> str:
        """A stable identifier for the embedding model.

        Vectors are tagged with this so a store can detect that it was built
        with a different model and must be re-embedded (ADR-0006 §4).
        """
        ...

    @property
    def dimensions(self) -> int:
        """The fixed length of the vectors this embedder produces."""
        ...

    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        """Embed a batch of texts, returning one vector per input, in order."""
        ...


@runtime_checkable
class MemoryStore(Protocol):
    """Persistent long-term memory with semantic retrieval.

    Records carry an optional ``expires_at`` retention deadline. A record past
    that deadline is treated as already forgotten: ``get`` and ``search`` never
    return it, whether or not ``purge_expired`` has reclaimed it yet (ADR-0007).
    """

    async def add(self, record: MemoryRecord) -> str:
        """Persist a record and return its id.

        Adding a record whose ``id`` already exists overwrites the previous one
        (an upsert), so ``id`` is the caller's idempotency key. All backends share
        this behaviour; the shared conformance suite enforces it.
        """
        ...

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Return the record with ``record_id``, or ``None`` if absent or expired."""
        ...

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
    ) -> list[MemoryRecord]:
        """Return the records most relevant to ``query``, best first.

        Expired records are never returned.

        Args:
            query: The search text.
            limit: Maximum number of records to return.
            kinds: If given, restrict results to these memory kinds.
        """
        ...

    async def delete(self, record_id: str) -> bool:
        """Delete one record.

        Args:
            record_id: The id of the record to remove.

        Returns:
            ``True`` if a record was removed, ``False`` if none had that id.
        """
        ...

    async def clear(self) -> int:
        """Delete every record in this store, returning the number removed.

        This empties the store's own (Tier 1) rows only; it is not a
        whole-system erase (ADR-0007 §4).
        """
        ...

    async def export(self) -> list[MemoryRecord]:
        """Return a portable snapshot of all live (non-expired) records.

        The caller serialises the records to JSON (e.g. ``model_dump(mode="json")``);
        the snapshot excludes expired records and carries no embeddings (ADR-0007 §3).
        """
        ...

    async def purge_expired(self) -> int:
        """Physically remove records past their ``expires_at``.

        Returns:
            The number of expired records removed. Read methods already hide
            expired records, so this changes reclaimed space, not visibility.
        """
        ...


@runtime_checkable
class MemoryPolicy(Protocol):
    """Decides the fate of a proposed memory update — the "dispose" half.

    The model *proposes* memories; a deterministic policy implementing this
    Protocol *disposes* of them, so writes to long-term memory are reviewable
    and bounded rather than an unmediated side effect of generation.
    """

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        """Rule on a proposed memory update.

        Args:
            proposal: The candidate memory and why it was proposed.
            conflicts: Existing records the proposal contradicts, already
                resolved from the store (the proposal carries their ids).

        Returns:
            The decision to accept, reject, merge, defer to the user, or store
            the proposal temporarily.
        """
        ...


@runtime_checkable
class ContextProvider(Protocol):
    """Assembles the situational :class:`~ai_assistant.core.types.CurrentContext`.

    The pipeline's context step (ADR-0008). Implementations compose one or more
    internal sources; only this typed contract crosses a subsystem boundary.
    """

    async def assemble(self) -> CurrentContext:
        """Return the situational context for right now.

        Assembly is advisory: a failing optional source degrades its facet rather
        than aborting, so this returns a valid context whenever the required core
        can be built.
        """
        ...


@runtime_checkable
class FeedbackProcessor(Protocol):
    """Turns feedback into memory-update proposals — the learning step (ADR-0009).

    Implementations (in `learning`) map a
    :class:`~ai_assistant.core.types.FeedbackEvent` into zero or more
    :class:`~ai_assistant.core.types.MemoryUpdateProposal`s. They *propose* only;
    the pipeline feeds the proposals to the memory write-path, so the model never
    writes memory directly.
    """

    async def process(self, event: FeedbackEvent) -> Sequence[MemoryUpdateProposal]:
        """Return the memory-update proposals implied by ``event`` (possibly none)."""
        ...


@runtime_checkable
class Planner(Protocol):
    """Turns a :class:`~ai_assistant.core.types.Goal` into a plan (ADR-0014 §6).

    The pipeline's planning step. Implementations produce an ``ActionPlan`` and
    nothing else — no model output ever sets execution status, which stays the
    property of deterministic code (VISION §7).
    """

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        """Produce a plan for ``goal``.

        ``context`` and ``memories`` are passed in rather than fetched: the
        pipeline assembles context and retrieves memory before planning, and a
        planner that reached for them itself would import two subsystems it has
        no business importing. Retrieved memory is also what makes a plan
        personal rather than generic.

        Args:
            goal: The objective to plan for.
            context: The situational context assembled for this request.
            memories: Records retrieved as relevant to the goal, best first.

        Returns:
            A frozen :class:`~ai_assistant.core.types.ActionPlan`.

        Raises:
            PlanningError: If no plan could be produced for the goal.
        """
        ...


@runtime_checkable
class PlanStore(Protocol):
    """Durable planning state: goals, plans, and execution (ADR-0014 §5).

    Planning owns this rather than the wiring layer, because plan state is
    personal data and carries ADR-0004's obligations. Implementations persist
    **locally only**; none may write plan state to a remote service.

    Writes to execution state go through :meth:`commit_transition`, never by
    handing back a whole state, so the transition graph cannot be bypassed.
    """

    async def save_goal(self, goal: Goal) -> str:
        """Persist a goal and return its id (an upsert, keyed on ``id``)."""
        ...

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Return the goal with ``goal_id``, or ``None`` if absent."""
        ...

    async def save_plan(self, plan: ActionPlan) -> str:
        """Persist a plan and return its id.

        Raises:
            PlanningError: If the plan's ``goal_id`` names no stored goal.
        """
        ...

    async def get_plan(self, plan_id: str) -> ActionPlan | None:
        """Return the plan with ``plan_id``, or ``None`` if absent."""
        ...

    async def start_execution(self, plan_id: str) -> ExecutionState:
        """Open a fresh execution for ``plan_id`` and return it.

        The initial state is *derived* — one ``PENDING`` step per plan step, in
        order, at version 0 — rather than supplied, which is what guarantees the
        positional correspondence with the plan that everything else assumes.

        Raises:
            PlanningError: If ``plan_id`` names no stored plan.
        """
        ...

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        """Apply one step transition and return the new state.

        The only write path for execution state. Implementations apply the
        transition against the stored snapshot, so an illegal move is rejected
        rather than persisted, and the write is compare-and-swap on
        ``expected_version``.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            IllegalTransitionError: If the move is not legal from the step's
                current status.
            PlanningError: If the execution or step does not exist.
        """
        ...

    async def get_execution(self, execution_id: str) -> ExecutionState | None:
        """Return the execution with ``execution_id``, or ``None`` if absent."""
        ...

    async def active_executions(self) -> list[ExecutionState]:
        """Return every execution with a non-terminal step.

        This is what makes resumption possible: the query a restarting system
        issues to find work left in flight.
        """
        ...

    async def export(self) -> PlanExport:
        """Return a portable snapshot of all planning state (ADR-0004 §6)."""
        ...

    async def delete_goal(self, goal_id: str) -> GoalDeletion:
        """Delete a goal, cascading to its plans and their execution state.

        Refused while any of the goal's executions is still active: erasing an
        in-flight execution would destroy the record its executor is about to
        commit against. The caller cancels first, then retries.

        Returns:
            A :class:`~ai_assistant.core.types.GoalDeletion` reporting what was
            removed, or — when refused — which executions blocked it.
        """
        ...

    async def clear(self) -> int:
        """Delete every record in this store, returning the number removed.

        Bound by the same in-flight rule as :meth:`delete_goal`: a bulk erase is
        not a licence to orphan a side effect a goal-scoped one would refuse to.

        Raises:
            ActiveExecutionError: If any execution is still active.
        """
        ...
