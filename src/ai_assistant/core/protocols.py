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
        ActionRequest,
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
        PermissionDecision,
        PermissionRuling,
        PlanExport,
        StepTransition,
        ToolDefinition,
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

        Refused while any of the goal's executions has a **live** (``RUNNING``)
        step: erasing one would destroy the record its executor is about to
        commit against. The caller cancels first, then retries. Deliberately
        keyed on ``has_live_step`` rather than ``is_active`` — a permanently
        failed or unresolved step never becomes inactive, so blocking on the
        wider predicate would make the goal undeletable for good.

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
            ActiveExecutionError: If any execution has a live step.
        """
        ...


@runtime_checkable
class ToolRegistry(Protocol):
    """What tools exist and what invoking them risks (ADR-0016 §5).

    The pipeline's tool-selection stage queries this, and ``permissions`` reads
    a candidate's declared metadata to rule on it. Both only ever *ask*, which
    is why this contract is **query-only**: populating a registry is internal to
    `tools`, in the way `context` keeps its ``ContextSource`` seam behind
    ``ContextProvider`` (ADR-0008).

    **The registry does not choose.** :meth:`find` returns every candidate;
    which one runs needs the user's policy and the current context, neither of
    which a registry has. Ranking here would collapse the
    ``planning → tool selection`` boundary ADR-0014 §2 preserves.

    Definitions carry no personal data: a :class:`ToolDefinition` is Tier 2
    configuration declared by code (ADR-0004 §1), so unlike ``MemoryStore`` and
    ``PlanStore`` this contract has no export/delete obligation.

    **Every query returns a detached snapshot** — the list *and* the definitions
    in it. These methods return ``list`` to match ``MemoryStore.search``, and a
    list is mutable, so an implementation handing back its own collection would
    let a caller's ``result.clear()`` deregister every tool through a *query*,
    routing around the registration lifecycle this contract keeps internal.
    """

    async def get(self, tool_id: str) -> ToolDefinition | None:
        """Return the definition registered as ``tool_id``, or ``None``."""
        ...

    async def find(self, capability: str) -> list[ToolDefinition]:
        """Return every tool advertising ``capability``, ordered by ``id``.

        Ordering is by id ascending because some total order must be specified
        or implementations differ observably; ``id`` is the one that carries no
        accidental meaning. Ordering by risk would be the beginning of ranking,
        and callers would come to depend on it.

        An unsatisfied capability returns an empty list rather than raising: a
        plan naming a capability nothing implements is a legitimate, detectable
        outcome, and ADR-0014 reserved ``SkipReason.NO_CAPABLE_TOOL`` for it.
        """
        ...

    async def capabilities(self) -> tuple[str, ...]:
        """Return every advertised capability, sorted and de-duplicated.

        The registry is the authority on the capability vocabulary, which stays
        an open set of strings rather than a ``core`` enum — an enum would make
        every new integration a breaking ``core`` change and foreclose tools
        this repository does not ship (ADR-0016 §5).
        """
        ...

    async def all_tools(self) -> list[ToolDefinition]:
        """Return every registered definition, ordered by ``id``."""
        ...


@runtime_checkable
class ActionPolicy(Protocol):
    """Rules on whether an action may be performed (ADR-0021 §3).

    The gate ADR-0004 §7 requires in front of every side-effecting tool call.
    Implementations live in `permissions` and are **the user's**: the contract
    fixes the *shape* of the function, never a threshold — "confirm at or above
    ``MEDIUM``" is a setting, not a decision a contract gets to make.

    **A policy rules; it does not name, mint, or record.** It returns a
    :class:`~ai_assistant.core.types.PermissionRuling`, which has no field in
    which to name a tool, a payload or a step, so it cannot substitute the
    subject of the decision it is answering about. It supplies neither an ``id``
    nor a clock, which leaves :meth:`decide` a genuine function of its argument
    — and that is what makes the obligations below checkable at all. And it does
    not write to the audit trail; the caller does (issue #107 records the
    accepted cost).

    Three obligations every implementation must satisfy, enforced by the shared
    conformance suite:

    * **Monotone in severity.** Raising ``risk_level``, raising
      ``reversibility``, or widening ``discloses`` — everything else held equal —
      must never produce a *less* restrictive outcome. Checkable without knowing
      an implementation's rules, and it rules out the whole class of accidents
      where a threshold comparison is written the wrong way round.
    * **Off-device disclosure is never auto-granted.** A definition with a
      non-empty ``discloses`` — any tier, not merely ``SECRET`` or ``PERSONAL``
      — may not receive ``ALLOW`` with ``authorised_by`` unset. This is the
      enforceable form of the two-field rule ADR-0016 §2 states as an obligation
      on this subsystem, and it has to be a *floor* because nothing weaker is
      checkable: a function that ignores an input is monotone in that input, so
      no monotonicity requirement can ever force a field to be read.
    * **An ``UNKNOWN`` cost is never auto-granted.** ADR-0016 §4 ratified
      ``UNKNOWN`` as "the author does not know — policy must fail closed", and
      this is where that clause acquires an enforcer.

    Within those floors an implementation may be arbitrarily permissive: a
    policy returning ``CONFIRM`` for everything and one returning ``ALLOW`` for
    every non-disclosing, known-cost tool both conform, and the suite
    deliberately cannot tell a good policy from a mediocre one. What it does
    guarantee is that the failures which are *not* matters of taste cannot
    occur — an inverted comparison, a disclosure auto-granted, a cost nobody
    declared treated as free.
    """

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        """Rule on ``request``.

        Must return ``authorised_by is None`` from a policy constructed with no
        authorisation source — today that is *every* policy, since standing
        grants are deferred, so no conforming implementation can invent an
        authorisation while ruling on a fresh request.

        Args:
            request: The self-contained action to rule on, carrying the tool
                definition by value rather than an id.

        Returns:
            The ruling. It describes only ``outcome``, ``reason`` and an
            optional authorisation pointer; the *subject* is transcribed from
            the request by
            :meth:`~ai_assistant.core.types.PermissionDecision.from_request`.
        """
        ...

    async def resolve(self, confirmed: PermissionDecision, *, approved: bool) -> PermissionRuling:
        """Turn a user's answer to a recorded ``CONFIRM`` into a ruling.

        This keeps **every permission outcome authored inside** `permissions`.
        Leaving the conversion to the caller would put the authoring of a
        permission outcome in `orchestration` or, worse, in an interface adapter
        — the business logic golden rule 3 keeps out of `interfaces/`.

        Three obligations bound what may be returned, and the first matters
        most:

        * **``approved=False`` must yield ``DENY``, with ``authorised_by``
          unset.** A user who declines has *decided*, and a policy that could
          turn a refusal into an ``ALLOW`` would make the confirmation prompt
          theatre — the single worst failure available to this subsystem, since
          it is the one moment the user believes they are in control.
        * **``approved=True`` may yield ``ALLOW`` or ``DENY``, and nothing
          else.** A policy is entitled to refuse a confirmation it no longer
          accepts — answered long after it was asked, or one whose request would
          now be ``DENY`` — rather than being obliged to rubber-stamp any
          ``True`` it is handed. What it may not do is treat consent as
          mandatory. It also may not return ``CONFIRM``: a resolving decision
          may not itself be a ``CONFIRM``, so re-asking would produce a ruling
          that is conforming and unrecordable.
        * **A ``confirmed`` whose ruling was not ``CONFIRM`` must not produce an
          ``ALLOW``**, so this cannot mint an authorisation out of a decision
          nobody was ever shown.

        A resolving ``ALLOW`` sets ``authorised_by`` to ``confirmed.id`` — this
        is the one path that may set it, and what it sets is verifiable, since
        ``AuditTrail.record`` holds the referenced record and checks it.

        Args:
            confirmed: The recorded ``CONFIRM`` the user was shown.
            approved: Whether the user approved it.

        Returns:
            The ruling that resolves ``confirmed``. The caller records it as a
            second decision whose ``resolves`` names ``confirmed.id``.
        """
        ...


@runtime_checkable
class AuditTrail(Protocol):
    """The append-only record of what the permission layer decided (ADR-0021 §4).

    A Tier 1 store by ADR-0004 §7's own words, so ADR-0004 §2's residency clause
    governs it: implementations persist **locally only**, and none of this may
    be written to a remote service.

    **Every query returns a detached snapshot** — the list, the decisions in it,
    and everything mutable those reach. This is ADR-0018 §3's rule applied to a
    second store: a ``PermissionDecision`` embeds a ``ToolDefinition`` which
    embeds a ``ToolCost``, and ``frozen=True`` refuses ``x.outcome = ...`` but
    not ``x.__dict__["outcome"] = ...``. A store handing back its own objects
    would let a reader rewrite the record of what was approved. As in ADR-0018
    §3 this isolates *store state*; it does not make a decision the caller now
    holds tamper-proof.

    **There is no ``update`` and no ``delete(id)``.** ADR-0004 §6 gives the user
    the right to delete their data, so the trail must be erasable — but
    *selective* erasure of an audit trail is indistinguishable from tampering
    with it, and an affordance that removes one inconvenient record undoes the
    guarantee for all of them. So the user may burn the book; nobody may tear
    out a page.
    """

    async def record(self, decision: PermissionDecision) -> str:
        """Append ``decision`` to the trail and return its id.

        **Write-once**: re-recording an id already present raises rather than
        overwriting. A deliberate departure from ``MemoryStore.add``, which
        upserts because there ``id`` is the caller's idempotency key; an audit
        trail that upserts is one where history can be rewritten by replaying a
        write.

        **Atomic**: the duplicate-id check, the resolution validation and the
        append are one operation, not a read followed by a write. Without that
        the single-use guarantee is a race — two concurrent resolutions of the
        same ``CONFIRM`` each observe no prior resolution, each append, and one
        user approval has authorised two executions. That is the class of
        failure ADR-0014 §5 answered with compare-and-swap on ``PlanStore``, and
        it deserves the same treatment: exactly one of two racing writes
        succeeds and the other raises. "The system composes on one event loop"
        is precisely the setting in which an ``await`` between a check and a
        write is an interleaving point.

        **Stores a detached, validated snapshot**, recursively over reachable
        mutable state. ADR-0018 §4 made this a rule for the registry's write
        path and the argument carries over unchanged: a store retaining the
        caller's object would let ``decision.__dict__["ruling"] = ...`` rewrite
        an appended entry after the fact, through a store whose entire premise
        is that entries are not rewritten. Detachment on queries alone closes
        the door and leaves the window open.

        **Enforces the resolution invariant**, because this is the only place
        both records are in hand. A decision whose ``resolves`` is set is
        refused unless the referenced id is present, its ruling was ``CONFIRM``,
        no other recorded decision already resolves it, its ``tool``,
        ``parameters_digest`` and ``step_id`` match the incoming decision's
        exactly, and it was not decided *after* the resolution answering it
        (equal timestamps are fine — a fast confirmation at a coarse clock
        resolution is real). The authorisation pointer is checked here too: a
        resolving ``ALLOW`` must carry ``authorised_by`` equal to its
        ``resolves``, and a resolving ``DENY`` must leave it unset. Without that
        pair, a resolving ``ALLOW`` could name any confirmation it liked — or a
        string naming nothing — while satisfying every other check, and the
        disclosure floor would be satisfiable by fabrication.

        This bounds **resolutions, not executions**, and the difference is worth
        being precise about: ``authorises()`` is a pure comparison, so the same
        resolved ``ALLOW`` answers ``True`` every time it is asked. Making an
        approval single-*use* needs an atomic consume-on-execution step, which
        belongs to the invocation contract. "Approve once" means the question is
        settled once, not that the answer is spent on exactly one call.

        Raises:
            DuplicateDecisionError: If a decision with this ``id`` is already
                recorded.
            InvalidResolutionError: If ``resolves`` is set and the invariant
                above does not hold.
        """
        ...

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Return the decision with ``decision_id``, or ``None`` if absent."""
        ...

    async def recent(self, *, limit: int = 50) -> list[PermissionDecision]:
        """Return the most recent decisions, newest first.

        Ordered by ``decided_at`` **descending**, ties broken by ``id``
        ascending. Both halves are needed: "newest first" is ambiguous between
        insertion order and decision time, which disagree whenever records are
        appended out of order, and two stores would then answer the same query
        differently while each believed it conformed. Decision time is the right
        choice for an audit trail — the question is when something *was
        decided*, not when a writer got around to it — and an ``id`` tie-break
        makes the order total rather than merely mostly determined.

        Bounded by default because the realistic query is "what has the
        assistant just done", and an unbounded read of a Tier 1 store by default
        is a shape worth not offering.

        Args:
            limit: Maximum number of decisions to return; must be strictly
                positive.

        Raises:
            ValueError: If ``limit`` is not strictly positive. Raised rather
                than clamped or passed through, because the natural
                implementation leaks: a store issuing ``LIMIT ?`` against SQLite
                turns ``limit=-1`` into *no limit at all*, so the one call
                offering a bounded read becomes the unbounded read it exists to
                avoid. Clamping silently is the other wrong answer — a caller
                that asked for something meaningless should learn that, not be
                served something it did not ask for.
        """
        ...

    async def export(self) -> list[PermissionDecision]:
        """Return a portable snapshot of every recorded decision (ADR-0004 §6)."""
        ...

    async def clear(self) -> int:
        """Delete every decision in the trail, returning the number removed.

        Wholesale erasure is a different act from selective deletion: it
        destroys the trail visibly and completely, which is what a data-rights
        operation should look like (ADR-0004 §6).
        """
        ...
