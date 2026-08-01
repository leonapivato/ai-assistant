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

Tool selection, permission checking and execution are still **not** part of this
object. All three now exist —
:class:`~ai_assistant.orchestration.runner.StepRunner` disposes of a single
:class:`~ai_assistant.core.types.PlanStep` through them (ADR-0037) — but nothing
drives them from a :class:`~ai_assistant.core.types.ActionPlan` yet: ordering,
dependencies and cancellation across a plan's steps are the next slice, and
:meth:`LearningLoop.respond` still ends at the plan.

Nothing concrete is imported. Every collaborator arrives by injection and is
seen only through its Protocol (CLAUDE.md golden rule 1), which is what lets the
same engine run against the canonical fakes in tests and the real subsystems in
production.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import MemoryStoreError, PlanningError
from ai_assistant.core.types import (
    Goal,
    MemorySource,
    Provenance,
    TurnResult,
)
from ai_assistant.orchestration.conversations import BELIEF_KINDS

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        ContextProvider,
        FeedbackProcessor,
        MemoryStore,
        Planner,
    )
    from ai_assistant.core.types import (
        FeedbackEvent,
        MemoryRecord,
    )
    from ai_assistant.orchestration.writes import MemoryWriteStage, WriteOutcome

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
        writes: MemoryWriteStage,
        planner: Planner,
        feedback: FeedbackProcessor,
        retrieval_limit: int = _DEFAULT_RETRIEVAL_LIMIT,
        now: Clock = _utcnow,
        id_factory: Callable[[], str] = _uuid,
    ) -> None:
        """Wire the loop from injected contracts.

        **The writer behind ``writes`` must persist to ``memory``.** Nothing in
        the type system can say so — a ``MemoryWriter`` exposes no store,
        deliberately — so it is a composition-root obligation (ADR-0028 §4):
        whoever builds the loop passes the same ``MemoryStore`` instance to it and
        to the writer. Wired to two stores, learning reports a real record id and
        the next turn retrieves nothing, with ``memory_degraded`` reading
        ``False`` — the closed loop silently open.

        Args:
            context: Assembles the situational "right now" for each turn.
            memory: Long-term memory, read for retrieval. The store the write
                stage's writer writes to.
            writes: The orchestration **write stage** — the ratified memory write
                path plus the durable queue a deferred question waits in
                (ADR-0078 §3). This loop holds it rather than a ``MemoryWriter``
                of its own, and that is the wiring choice the whole feature rests
                on: a producer's stage holding the writer directly would get the
                ratified policy and applier and silently lose the queue, which is
                exactly the drop ADR-0078 ends.
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
        self._writes = writes
        self._planner = planner
        self._feedback = feedback
        self._retrieval_limit = retrieval_limit
        self._clock = checked_clock(now, owner="LearningLoop")
        self._id_factory = id_factory

    async def respond(
        self,
        utterance: str,
        *,
        history: Sequence[MemoryRecord] = (),
        history_degraded: bool = False,
    ) -> TurnResult:
        """Run one turn: intent, context, memory retrieval, planning.

        The stage order mirrors the pipeline in ``CLAUDE.md``, and each stage
        can only use what the ones before it produced: retrieval is scoped by
        the goal, and the planner is handed both the context and the memories
        precisely because a planner that fetched them itself would import two
        subsystems it has no business importing (``Planner``, ADR-0014 §6).

        **Continuity reaches the model through the seam it already has**
        (ADR-0074 §5). The conversation's recent turns arrive as ``history`` and
        go into ``memories`` **first**, followed by the relevance-retrieved
        beliefs; ``Planner`` grows no ``history`` parameter, because both groups
        are ``MemoryRecord``s the planner already renders and a second channel
        would split one prompt input in two for a distinction it does not act on.
        Reading the history is the capture stage's job, not this one's: it spans
        both durable stores, and only that stage holds both.

        **Retrieval selects the belief kinds** and never ``EPISODIC``
        (:data:`~ai_assistant.orchestration.conversations.BELIEF_KINDS`,
        ADR-0074 §6), so a captured turn does not compete with beliefs for the
        retrieval budget.

        Args:
            utterance: What the user said. It becomes the goal's statement
                unrewritten — trimmed of surrounding whitespace, and otherwise
                untouched. No intent inference happens here, because inferring
                one needs a model and no contract offers that yet.
            history: The conversation's recent turns, oldest first, already
                resolved to records. Empty for a fresh conversation.
            history_degraded: Whether reading that history failed. Folded into
                :attr:`TurnResult.memory_degraded` rather than reported
                separately: from the user's side both are "this answer is less
                informed than it should have been", and a second flag would ask an
                adapter to explain a distinction it cannot act on.

        Returns:
            The turn's goal, context, assembled memories and plan.

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
        # Observed before the first await, so a caller mutating the sequence it
        # passed cannot change what the planner is shown (ADR-0065).
        recent = tuple(history)
        goal = self._goal_from(utterance)
        context = await self._context.assemble()
        retrieved, degraded = await self._retrieve(goal.statement)
        memories = recent + retrieved
        plan = await self._planner.plan(goal, context=context, memories=memories)
        return TurnResult(
            goal=goal,
            context=context,
            memories=memories,
            plan=plan,
            memory_degraded=degraded or history_degraded,
        )

    async def learn(self, event: FeedbackEvent) -> tuple[WriteOutcome, ...]:
        """Fold one piece of feedback back into memory.

        Process, then delegate: the feedback becomes proposals, and each goes
        through the injected **write stage** — the ratified
        :class:`~ai_assistant.core.protocols.MemoryWriter` (ADR-0028 §4) plus the
        durable queue an ``ASK_USER`` ruling parks its question in (ADR-0078 §3).
        Conflicts, the policy's ruling and the write itself all happen behind that
        seam — including a ``REINFORCE`` or ``SUPERSEDE``, which is *applied* by
        `memory`'s own fold rather than reported and dropped. The model never
        writes memory directly (VISION §7).

        **A deferral no longer vanishes here.** Until ADR-0078 an ``ASK_USER``
        ruling was reported and the proposal went out of scope, so ADR-0050 §2's
        "the incoming one is held pending the user's answer, not dropped"
        described nothing. Now the stage parks it and the outcome says what the
        queue did with it, which is what lets a user who submitted a correction be
        told where it went — including when the queue refused it, the case an
        implementation is most likely to leave as a silent no-op (ADR-0078 §7).

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
            One :class:`~ai_assistant.orchestration.writes.WriteOutcome` per
            proposal, in the order they were proposed, each carrying the policy's
            decision, the id written (``None`` when nothing was), and what the
            queue did with a question the ruling deferred (``None`` when it raised
            none).

        Raises:
            MemoryStoreError: If the writer failed to read conflicts or write a
                record, or a ``REINFORCE`` or ``SUPERSEDE`` named a ``target_id``
                that is not among them.
            DeferralStoreError: If a deferred question could not be parked. The
                ruling is already applied, so this surfaces rather than being
                swallowed — with the earlier proposals applied, exactly as a store
                failure leaves them.
        """
        proposals = await self._feedback.process(event)
        return tuple([await self._writes.write(proposal) for proposal in proposals])

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
        """Retrieve *beliefs* relevant to ``query``, degrading rather than failing.

        Returns the records and whether retrieval degraded. Losing memory costs
        the answer its personalisation, not its usefulness, so the turn
        continues — but it continues *saying so*, via
        :attr:`TurnResult.memory_degraded`.

        The ``kinds`` filter is ADR-0074 §6: ``MemoryStore.search`` itself stays
        band-neutral and kind-filtered only by its caller's argument, and this
        caller asks for beliefs. Cross-conversation episodic recall — "what did we
        discuss last Tuesday?" — is a real capability deferred with its ranking
        question, because mixing raw turns with distilled beliefs in one relevance
        cut is the ordering problem leg 7 is for.
        """
        try:
            memories = await self._memory.search(
                query, limit=self._retrieval_limit, kinds=BELIEF_KINDS
            )
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
