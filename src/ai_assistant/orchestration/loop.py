"""The closed learning loop: respond, observe a correction, reuse it (ADR-0022).

:class:`LearningLoop` is the first working slice of the request pipeline. It
wires four injected contracts — :class:`~ai_assistant.core.protocols.ContextProvider`,
:class:`~ai_assistant.core.protocols.MemoryStore`,
:class:`~ai_assistant.core.protocols.Planner` and
:class:`~ai_assistant.core.protocols.FeedbackProcessor`, plus the
:class:`~ai_assistant.core.protocols.MemoryWriter` that owns the write path —
into the roadmap's first vertical:

.. code-block:: text

    conversation
      → retrieve relevant user context
      → generate a response or plan
      → observe the user's correction
      → propose a preference update (policy accepts it)
      → use that preference successfully next time

Tool selection, permission checking and execution are still **not** here. The
last of the three now exists as :class:`~ai_assistant.orchestration.executor.StepExecutor`
(ADR-0029 §8), but the two stages between planning and it do not, and a turn
cannot reach an executor without a selected tool and a ruling on it. They join
the pipeline when they exist.

Nothing concrete is imported. Every collaborator arrives by injection and is
seen only through its Protocol (CLAUDE.md golden rule 1), which is what lets the
same engine run against the canonical fakes in tests and the real subsystems in
production.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import MemoryStoreError, PlanningError
from ai_assistant.core.types import (
    Goal,
    MemorySource,
    Provenance,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        ContextProvider,
        FeedbackProcessor,
        MemoryStore,
        MemoryWriter,
        Planner,
    )
    from ai_assistant.core.types import (
        ActionPlan,
        CurrentContext,
        FeedbackEvent,
        MemoryIngestResult,
        MemoryRecord,
    )

_log = structlog.get_logger(__name__)

#: A user's own utterance is asserted, not inferred, so the goal it becomes
#: carries full confidence (``Provenance`` requires 1.0 for ``USER_ASSERTED``).
_FULL_CONFIDENCE = 1.0

_DEFAULT_RETRIEVAL_LIMIT = 5


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


def _check_tuning(*, retrieval_limit: int) -> None:
    """Reject tuning that would disable retrieval while looking healthy.

    A *silent* misconfiguration, which is why it is refused at construction
    rather than left to surface as behaviour: ``retrieval_limit=0`` makes
    ``MemoryStore.search`` return nothing by contract, so every turn would be
    unpersonalised with ``memory_degraded`` reading ``False`` — a generic answer
    presented as a healthy personal one, the exact failure
    :attr:`TurnResult.memory_degraded` exists to expose.

    The conflict half of this check went where the conflict tuning went, into
    ``MemoryIngestor.__init__`` (ADR-0028 §4a): relocated with the values, not
    retired.

    Raises:
        TypeError: If ``retrieval_limit`` is not an integer.
        ValueError: If ``retrieval_limit`` is not positive.
    """
    # `isinstance` rather than a bare `< 1`, which `1.5` and `inf` both survive
    # — and a non-integral limit reaches `MemoryStore.search`, where a store
    # slicing by it raises `TypeError` far from the mistake. `bool` is excluded
    # because it is an `int` subclass and a flag is not a count.
    if isinstance(retrieval_limit, bool) or not isinstance(retrieval_limit, int):
        msg = f"retrieval_limit must be an integer, got {retrieval_limit!r}"
        raise TypeError(msg)
    if retrieval_limit < 1:
        msg = f"retrieval_limit must be at least 1, got {retrieval_limit}"
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
        writer: MemoryWriter,
        planner: Planner,
        feedback: FeedbackProcessor,
        retrieval_limit: int = _DEFAULT_RETRIEVAL_LIMIT,
        now: Clock = _utcnow,
        id_factory: Callable[[], str] = _uuid,
    ) -> None:
        """Wire the loop from injected contracts.

        **``writer`` must persist to ``memory``.** Nothing in the type system
        can say so — a ``MemoryWriter`` exposes no store, deliberately — so it
        is a composition-root obligation (ADR-0028 §4): whoever builds the loop
        passes the same ``MemoryStore`` instance to it and to the writer. Wired
        to two stores, learning reports a real record id and the next turn
        retrieves nothing, with ``memory_degraded`` reading ``False`` — the
        closed loop silently open.

        Args:
            context: Assembles the situational "right now" for each turn.
            memory: Long-term memory, read for retrieval. The store ``writer``
                writes to.
            writer: The memory write path — conflicts, policy and persistence in
                one call. It holds the policy; this loop does not.
            planner: Turns the turn's goal into an ``ActionPlan``.
            feedback: Turns a ``FeedbackEvent`` into memory-update proposals.
            retrieval_limit: How many memories a turn retrieves.
            now: Clock for goal timestamps; injectable so turns are
                deterministic in tests. It no longer stamps temporary-store
                expiry — that is the writer's own clock (ADR-0028 §4b), so a
                test wanting a deterministic expiry injects one there too.
                Guarded by :func:`~ai_assistant.core.clock.checked_clock`, so a
                non-conforming reading is a ``PlanningError`` from the stage that
                read it, `orchestration` having no error of its own (ADR-0026 §4).
            id_factory: Supplies goal ids; injectable for the same reason.

        Raises:
            TypeError: If ``retrieval_limit`` is not an integer (see
                :func:`_check_tuning`).
            ValueError: If ``retrieval_limit`` is below 1 (see
                :func:`_check_tuning`).
        """
        _check_tuning(retrieval_limit=retrieval_limit)
        self._context = context
        self._memory = memory
        self._writer = writer
        self._planner = planner
        self._feedback = feedback
        self._retrieval_limit = retrieval_limit
        self._clock = checked_clock(now, owner="LearningLoop")
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
            PlanningError: If ``utterance`` is blank, the injected clock's
                reading is not conforming (:meth:`_now_utc`), or the planner could not
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

        Process, then delegate: the feedback becomes proposals, and each is
        handed to the injected :class:`~ai_assistant.core.protocols.MemoryWriter`
        (ADR-0028 §4). Conflicts, the policy's ruling and the write itself all
        happen behind that seam — including a ``MERGE``, which is *applied* by
        `memory`'s own fold rather than reported and dropped. The model never
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
            MemoryStoreError: If the writer failed to read conflicts or write a
                record, or a ``MERGE`` named a target that is not among them.
        """
        proposals = await self._feedback.process(event)
        return tuple([await self._writer.ingest(proposal) for proposal in proposals])

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
                Also if the injected clock's reading is not conforming — see
                :meth:`_now_utc`.
        """
        statement = utterance.strip()
        if not statement:
            msg = "a turn needs a non-empty utterance"
            raise PlanningError(msg)
        # `_now_utc` rather than `self._clock`: the guard raises `core`'s
        # owner-labelled `ValueError`, and this stage owes its caller an
        # `AssistantError` (ADR-0026 §4), exactly as the blank check above does.
        now = self._now_utc()
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

    def _now_utc(self) -> datetime:
        """The guarded clock's reading, as the reading stage's own error.

        ``core/errors.py`` defines no error for `orchestration`, so ADR-0026 §4
        gives the failure to the *stage*: this clock is read only while
        constructing a turn's goal, which already raises ``PlanningError`` for a
        blank utterance, so a non-conforming reading raises the same.

        Raises:
            PlanningError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise PlanningError(str(exc)) from exc
