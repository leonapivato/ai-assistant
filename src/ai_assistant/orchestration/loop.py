"""The closed learning loop: respond, observe a correction, reuse it (ADR-0022).

:class:`LearningLoop` is the first working slice of the request pipeline. It
wires four injected contracts — :class:`~ai_assistant.core.protocols.ContextProvider`,
:class:`~ai_assistant.core.protocols.MemoryStore`,
:class:`~ai_assistant.core.protocols.Planner` and
:class:`~ai_assistant.core.protocols.FeedbackProcessor`, plus the
:class:`~ai_assistant.core.protocols.MemoryPolicy` that guards the write path —
into the roadmap's first vertical:

.. code-block:: text

    conversation
      → retrieve relevant user context
      → generate a response or plan
      → observe the user's correction
      → propose a preference update (policy accepts it)
      → use that preference successfully next time

Tool selection, permission checking and execution are deliberately **not** here:
nothing is invocable yet (ADR-0016 §7 deferred ``Tool.invoke``), so a stage that
ran a tool could not be written honestly. They join the pipeline when they exist.

Nothing concrete is imported. Every collaborator arrives by injection and is
seen only through its Protocol (CLAUDE.md golden rule 1), which is what lets the
same engine run against the canonical fakes in tests and the real subsystems in
production.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.errors import MemoryStoreError, PlanningError
from ai_assistant.core.types import (
    Goal,
    MemoryDecisionKind,
    MemoryIngestResult,
    MemoryKind,
    MemorySource,
    Provenance,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import timedelta

    from ai_assistant.core.protocols import (
        ContextProvider,
        FeedbackProcessor,
        MemoryPolicy,
        MemoryStore,
        Planner,
    )
    from ai_assistant.core.types import (
        ActionPlan,
        CurrentContext,
        FeedbackEvent,
        MemoryDecision,
        MemoryRecord,
        MemoryUpdateProposal,
    )

_log = structlog.get_logger(__name__)

#: A user's own utterance is asserted, not inferred, so the goal it becomes
#: carries full confidence (``Provenance`` requires 1.0 for ``USER_ASSERTED``).
_FULL_CONFIDENCE = 1.0

_DEFAULT_RETRIEVAL_LIMIT = 5
_DEFAULT_CONFLICT_THRESHOLD = 0.75
_DEFAULT_CONFLICT_LIMIT = 5


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


def _check_tuning(*, retrieval_limit: int, conflict_threshold: float, conflict_limit: int) -> None:
    """Reject tuning that would disable a stage while looking healthy.

    Each of these is a *silent* misconfiguration, which is why it is refused at
    construction rather than left to surface as behaviour. ``retrieval_limit=0``
    makes ``MemoryStore.search`` return nothing by contract, so every turn would
    be unpersonalised with ``memory_degraded`` reading ``False`` — a generic
    answer presented as a healthy personal one, the exact failure
    :attr:`TurnResult.memory_degraded` exists to expose. ``conflict_limit=0``
    hands the policy no conflicts, so every proposal is ruled on as though
    nothing contradicted it. A ``NaN`` threshold compares ``False`` against
    every score, silently doing the same.

    Raises:
        ValueError: If a limit is not positive, or the threshold is not a finite
            value in ``[0, 1]`` — the range a ``MemoryRecord.score`` occupies.
    """
    for name, limit in (("retrieval_limit", retrieval_limit), ("conflict_limit", conflict_limit)):
        if limit < 1:
            msg = f"{name} must be at least 1, got {limit}"
            raise ValueError(msg)
    if not isfinite(conflict_threshold) or not 0.0 <= conflict_threshold <= 1.0:
        msg = f"conflict_threshold must be a finite value in [0, 1], got {conflict_threshold!r}"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TurnResult:
    """What one conversational turn produced (ADR-0022 §2).

    A frozen dataclass in `orchestration` rather than a pydantic model in
    ``core/types.py``, because it crosses no *subsystem* boundary: only
    `interfaces`, which already depends on this package, ever sees one. It
    graduates to ``core`` on the day a subsystem needs to receive one.

    Attributes:
        goal: The objective this turn was planned against, minted from the
            utterance.
        context: The situational context assembled for the turn.
        memories: The records retrieved as relevant, best first — empty on the
            first turn, and empty when retrieval degraded.
        plan: What the planner decided to do.
        memory_degraded: Whether retrieval failed, making ``plan`` a *generic*
            answer rather than a personal one. Reported rather than swallowed:
            an unpersonalised answer is the one failure a user of this system
            most deserves to be told about.
    """

    goal: Goal
    context: CurrentContext
    memories: tuple[MemoryRecord, ...]
    plan: ActionPlan
    memory_degraded: bool = False


class LearningLoop:
    """Runs a conversational turn, and folds the user's correction back in.

    Two entry points, one per half of the loop: :meth:`respond` answers, and
    :meth:`learn` observes. They are deliberately separate calls rather than one
    method taking optional feedback — a correction arrives whenever the user
    gets round to it, which is usually not within the turn it corrects.
    """

    def __init__(  # noqa: PLR0913  # one parameter per injected contract; that is the design
        self,
        *,
        context: ContextProvider,
        memory: MemoryStore,
        policy: MemoryPolicy,
        planner: Planner,
        feedback: FeedbackProcessor,
        retrieval_limit: int = _DEFAULT_RETRIEVAL_LIMIT,
        conflict_threshold: float = _DEFAULT_CONFLICT_THRESHOLD,
        conflict_limit: int = _DEFAULT_CONFLICT_LIMIT,
        now: Callable[[], datetime] = _utcnow,
        id_factory: Callable[[], str] = _uuid,
    ) -> None:
        """Wire the loop from injected contracts.

        Args:
            context: Assembles the situational "right now" for each turn.
            memory: Long-term memory — read for retrieval, written by the
                learning half.
            policy: Rules on every proposed memory update before it is written.
            planner: Turns the turn's goal into an ``ActionPlan``.
            feedback: Turns a ``FeedbackEvent`` into memory-update proposals.
            retrieval_limit: How many memories a turn retrieves.
            conflict_threshold: Minimum retrieval score for an existing record
                to be offered to the policy as conflicting with a proposal.
            conflict_limit: Maximum number of conflict candidates considered.
            now: Clock for goal timestamps and temporary-store expiry;
                injectable so turns are deterministic in tests.
            id_factory: Supplies goal ids; injectable for the same reason.

        Raises:
            ValueError: If a limit is below 1, or ``conflict_threshold`` is not a
                finite value in ``[0, 1]`` (see :func:`_check_tuning`).
        """
        _check_tuning(
            retrieval_limit=retrieval_limit,
            conflict_threshold=conflict_threshold,
            conflict_limit=conflict_limit,
        )
        self._context = context
        self._memory = memory
        self._policy = policy
        self._planner = planner
        self._feedback = feedback
        self._retrieval_limit = retrieval_limit
        self._conflict_threshold = conflict_threshold
        self._conflict_limit = conflict_limit
        self._now = now
        self._id_factory = id_factory

    async def respond(self, utterance: str) -> TurnResult:
        """Run one turn: intent, context, memory retrieval, planning.

        The stage order mirrors the pipeline in ``CLAUDE.md``, and each stage
        can only use what the ones before it produced: retrieval is scoped by
        the goal, and the planner is handed both the context and the memories
        precisely because a planner that fetched them itself would import two
        subsystems it has no business importing (``Planner``, ADR-0014 §6).

        Args:
            utterance: What the user said. It becomes the goal's statement
                unrewritten — trimmed of surrounding whitespace, and otherwise
                untouched. No intent inference happens here, because inferring
                one needs a model and no contract offers that yet.

        Returns:
            The turn's goal, context, retrieved memories and plan.

        Raises:
            PlanningError: If ``utterance`` is blank, or the planner could not
                produce a plan.
            ContextError: If context assembly failed outright. Assembly already
                degrades a failing optional source internally (ADR-0008), so
                this is a wiring fault, and the alternative — inventing a
                situation the planner would then treat as fact — is worse than
                stopping.
        """
        goal = self._goal_from(utterance)
        context = await self._context.assemble()
        memories, degraded = await self._retrieve(goal.statement)
        plan = await self._planner.plan(goal, context=context, memories=memories)
        return TurnResult(
            goal=goal,
            context=context,
            memories=memories,
            plan=plan,
            memory_degraded=degraded,
        )

    async def learn(self, event: FeedbackEvent) -> tuple[MemoryIngestResult, ...]:
        """Fold one piece of feedback back into memory.

        Runs the propose/dispose/persist path for each proposal the feedback
        implies: conflicts are resolved from the store, the policy rules on the
        proposal given them, and only then is anything written. The model never
        writes memory directly (VISION §7).

        Proposals are applied in order and independently; there is no
        transaction, because ``MemoryStore`` offers none. Two consequences, both
        deliberate:

        * A store failure propagates with the earlier proposals **already
          applied**. Reporting success for a partially applied set would be a
          claim about memory integrity this loop cannot make.
        * Two proposals carrying the same record id resolve **last-write-wins**,
          because ``MemoryStore.add`` is an upsert keyed on id — the id is the
          caller's idempotency key, and de-duplicating here would override a
          processor that meant to supersede its own earlier proposal. Both
          outcomes report that id, which is what makes the collision visible.

        Args:
            event: The correction or stated preference the user gave.

        Returns:
            One result per proposal, in the order they were proposed, each
            carrying the policy's decision and the id written (``None`` when
            nothing was).

        Raises:
            MemoryStoreError: If reading conflicts or writing a record failed.
        """
        proposals = await self._feedback.process(event)
        return tuple([await self._ingest(proposal) for proposal in proposals])

    def _goal_from(self, utterance: str) -> Goal:
        """Mint the turn's goal from what the user said.

        Unrewritten and ``USER_ASSERTED``: the statement is the user's own, so a
        goal built from it must not be indistinguishable from one the system
        inferred (``Goal``, ADR-0014 §1). Surrounding whitespace is stripped —
        ``Goal``'s own validator would strip it anyway, so doing it here keeps
        the blank check and the stored statement in agreement.

        Raises:
            PlanningError: If the utterance is blank. Caught here rather than
                left to ``Goal``'s validator so the failure arrives as an
                ``AssistantError`` a caller can handle, not a ``ValidationError``.
        """
        statement = utterance.strip()
        if not statement:
            msg = "a turn needs a non-empty utterance"
            raise PlanningError(msg)
        now = self._now()
        return Goal(
            id=self._id_factory(),
            statement=statement,
            provenance=Provenance(
                source=MemorySource.USER_ASSERTED,
                confidence=_FULL_CONFIDENCE,
                last_updated=now,
            ),
            created_at=now,
        )

    async def _retrieve(self, query: str) -> tuple[tuple[MemoryRecord, ...], bool]:
        """Retrieve memories relevant to ``query``, degrading rather than failing.

        Returns the records and whether retrieval degraded. Losing memory costs
        the answer its personalisation, not its usefulness, so the turn
        continues — but it continues *saying so*, via
        :attr:`TurnResult.memory_degraded`.
        """
        try:
            memories = await self._memory.search(query, limit=self._retrieval_limit)
        except MemoryStoreError:
            _log.warning("memory_retrieval_degraded", stage="retrieve", exc_info=True)
            return (), True
        return tuple(memories), False

    async def _ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Resolve conflicts, ask the policy, and apply its ruling."""
        conflicts = await self._conflicts_for(proposal.proposed)
        proposal = proposal.model_copy(update={"conflicts": [record.id for record in conflicts]})
        decision = await self._policy.decide(proposal, conflicts=conflicts)
        record_id = await self._apply(decision, proposal.proposed)
        return MemoryIngestResult(decision=decision, record_id=record_id)

    async def _conflicts_for(self, record: MemoryRecord) -> list[MemoryRecord]:
        """Return the stored records ``record`` plausibly contradicts.

        Same kind, similar enough to clear ``conflict_threshold``, and never the
        proposal itself — a record cannot conflict with the version of it being
        re-proposed, and offering it as one would invite a merge into itself.
        """
        matches = await self._memory.search(
            record.content,
            limit=self._conflict_limit,
            kinds=[MemoryKind(record.kind)],
        )
        return [
            match
            for match in matches
            if match.id != record.id and (match.score or 0.0) >= self._conflict_threshold
        ]

    async def _apply(self, decision: MemoryDecision, proposed: MemoryRecord) -> str | None:
        """Write what the decision calls for, and return the id written.

        ``MERGE`` is reported but **not applied** (ADR-0022 §4). Folding two
        records into one is `memory`'s own semantics — it lives in
        ``MemoryIngestor``, which golden rule 1 forbids this package from
        importing — and re-deriving that fold here would fork it. The decision
        and a ``None`` record id are returned instead, so the caller sees
        exactly what was ruled and that nothing was stored.
        """
        match decision.kind:
            case MemoryDecisionKind.ACCEPT:
                return await self._memory.add(proposed)
            case MemoryDecisionKind.STORE_TEMPORARY:
                expires_at = self._expiry(decision.ttl)
                return await self._memory.add(
                    proposed.model_copy(update={"expires_at": expires_at})
                )
            case _:  # MERGE, REJECT, ASK_USER — nothing is written.
                _log.info("memory_update_not_applied", decision=decision.kind.value)
                return None

    def _expiry(self, ttl: timedelta | None) -> datetime | None:
        """Stamp an expiry ``ttl`` from now, failing loudly if unrepresentable."""
        if ttl is None:
            return None
        try:
            return self._now() + ttl
        except OverflowError as exc:
            msg = f"temporary-store ttl {ttl!r} overflows the representable date range"
            raise MemoryStoreError(msg) from exc
