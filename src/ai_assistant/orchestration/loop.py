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
    FeedbackKind,
    Goal,
    MemoryKind,
    MemorySource,
    Provenance,
    TurnResult,
)
from ai_assistant.orchestration.conversations import BELIEF_KINDS
from ai_assistant.orchestration.retrieval import assemble_by_band

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

#: The kinds a correction's drawer is resolved into (ADR-0122 §3), **fixed by that
#: clause** and not asked of the processor.
#:
#: It is a literal here because ``FeedbackProcessor`` exposes ``process(event)`` and
#: nothing else, so this stage has no way to ask which kinds are mintable, and
#: inventing a declaration would be a Protocol change under golden rule 5 — surface
#: with one implementation and one caller, ratified to spare an ADR from naming two
#: enum members. The set matches what ADR-0009 §4 fixes
#: ``RuleBasedFeedbackProcessor`` to mint, and it **widens by a ratified decision
#: rather than by inference**: when ADR-0009 §6's ``PROCEDURAL``/``EPISODIC``
#: deferral is taken up, the lane taking it partially supersedes §3 in the scope of
#: this set, in the same change that makes those kinds mintable.
#:
#: Bounding it at all is what stops the correction vanishing. The store is full of
#: episodes, and an episode recording the user ordering espresso is a plausible best
#: match for a correction about espresso — resolved to ``EPISODIC``, ``_to_record``
#: returns no proposal, and the user's correction is lost *entirely*, which is
#: strictly worse than the mis-drawering ADR-0122 fixes.
RESOLUTION_KINDS: tuple[MemoryKind, ...] = (
    MemoryKind.PREFERENCE,
    MemoryKind.SEMANTIC,
)

#: How wide the resolution's single ranked read is (ADR-0122 §3) — the loop's own
#: knob, **distinct from the turn's** ``retrieval_limit``, so tuning what an answer
#: is personalised from does not silently move what a correction is filed under.
#:
#: Only the best-ranked candidate decides the drawer, so this is not a budget being
#: spent; it is padding. ``kinds`` keeps the post-cut placement ADR-0045 §6 and
#: ADR-0007 ratified for it (ADR-0113 §2 moves the *band* alone), so a store may
#: rank a page and filter it afterwards, and a page of one is a page a single
#: topically similar episode can empty. ``MemoryStore.search``'s own default is the
#: same number, which is the width this corpus already treats as "a page".
_DEFAULT_RESOLUTION_LIMIT = 10


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


def _check_tuning(*, retrieval_limit: int, resolution_limit: int) -> None:
    """Reject tuning that would disable a read while looking healthy.

    A *silent* misconfiguration, which is why it is refused at construction
    rather than left to surface as behaviour: ``retrieval_limit=0`` makes
    ``MemoryStore.search`` return nothing by contract, so every turn would be
    unpersonalised with ``memory_degraded`` reading ``False`` — a generic answer
    presented as a healthy personal one, the exact failure
    :attr:`TurnResult.memory_degraded` exists to expose.

    ``resolution_limit`` is checked for the sharper version of the same reason
    (ADR-0122 §3). A non-positive one makes ``search`` match nothing, so **every**
    unpinned correction would resolve by §5's fallback and land as ``SEMANTIC`` —
    which is exactly the pre-ADR defect, restored by a number, reported as success,
    and indistinguishable at every surface from a store that genuinely holds no
    target. There is no reading of "resolve from the best-ranked neighbour" under
    which asking for none of them is the request.

    The conflict half of this check went where the conflict tuning went, into
    ``MemoryIngestor.__init__`` (ADR-0028 §4a): relocated with the values, not
    retired.

    Raises:
        TypeError: If either limit is not an integer.
        ValueError: If either limit is not positive.
    """
    # `isinstance` rather than a bare `< 1`, which `1.5` and `inf` both survive
    # — and a non-integral limit reaches `MemoryStore.search`, where a store
    # slicing by it raises `TypeError` far from the mistake. `bool` is excluded
    # because it is an `int` subclass and a flag is not a count.
    for name, value in (
        ("retrieval_limit", retrieval_limit),
        ("resolution_limit", resolution_limit),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            msg = f"{name} must be an integer, got {value!r}"
            raise TypeError(msg)
        if value < 1:
            msg = f"{name} must be at least 1, got {value}"
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
        resolution_limit: int = _DEFAULT_RESOLUTION_LIMIT,
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
                **The processor wired here must mint every kind in**
                :data:`RESOLUTION_KINDS` (ADR-0122 §3). Nothing in the type system
                can state it — ``FeedbackProcessor`` exposes ``process`` and nothing
                else — so it is a composition-root obligation in ADR-0028 §4's
                sense, exactly like the writer's above, and a root that wires a
                processor minting fewer has mis-wired the loop. :meth:`learn` is
                what stops a breach of it from being silent.
            retrieval_limit: How many memories a turn retrieves.
            resolution_limit: How wide the single ranked read is that resolves an
                unpinned correction's drawer (ADR-0122 §3). Deliberately its own
                knob rather than a reuse of ``retrieval_limit``: the two answer
                different questions, and a deployment tuning what an answer is
                personalised from must not silently move what a correction is filed
                under.
            now: Clock for goal timestamps; injectable so turns are
                deterministic in tests. It no longer stamps temporary-store
                expiry — that is the writer's own clock (ADR-0028 §4b), so a
                test wanting a deterministic expiry injects one there too.
                Guarded by :func:`~ai_assistant.core.clock.checked_clock`, so a
                non-conforming reading is a ``PlanningError`` from the stage that
                read it, `orchestration` having no error of its own (ADR-0026 §4).
            id_factory: Supplies goal ids; injectable for the same reason.

        Raises:
            TypeError: If ``retrieval_limit`` or ``resolution_limit`` is not an
                integer (see :func:`_check_tuning`).
            ValueError: If either is below 1 (see :func:`_check_tuning`).
        """
        _check_tuning(retrieval_limit=retrieval_limit, resolution_limit=resolution_limit)
        self._context = context
        self._memory = memory
        self._writes = writes
        self._planner = planner
        self._feedback = feedback
        self._retrieval_limit = retrieval_limit
        self._resolution_limit = resolution_limit
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

        Resolve, process, then delegate: an absent ``memory_kind`` is resolved
        first (:meth:`_resolved`, ADR-0122 §3), the feedback becomes proposals, and
        each goes through the injected **write stage** — the ratified
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

        **An empty answer to a *resolved* event is a mis-wiring, not a deferral**
        (ADR-0122 §7). The two look identical at the seam and mean opposite things.
        Where the caller **pinned** the kind, no proposal keeps exactly the meaning
        ADR-0009 §4 and §6 give it — a target this processor defers — and is
        returned as the empty outcome it has always been. Where *this stage*
        resolved the kind, it chose one from :data:`RESOLUTION_KINDS` **because**
        the processor mints it, so an empty sequence says the composition root wired
        one that does not; reporting it as "no update proposed" would drop a
        correction on the strength of a wiring mistake. That is what makes §3's
        untypeable obligation enforceable in the only way such an obligation can be:
        not checked at wiring time, and not survivable at use time.

        Raises:
            MemoryStoreError: If the resolution's read failed (:meth:`_resolved`),
                or the writer failed to read conflicts or write a record, or a
                ``REINFORCE`` or ``SUPERSEDE`` named a ``target_id`` that is not
                among them.
            DeferralStoreError: If a deferred question could not be parked. The
                ruling is already applied, so this surfaces rather than being
                swallowed — with the earlier proposals applied, exactly as a store
                failure leaves them.
            RuntimeError: If the wired ``FeedbackProcessor`` proposed nothing for an
                event *this stage* resolved (above). Deliberately outside the
                ``AssistantError`` subtree, which ADR-0085 §10a fixes as the wire's
                error vocabulary — the set of conditions a client can act on. A
                mis-wired composition root is not one of them, and minting a member
                for it would be authoring contract surface this lane may not author;
                it is the shape ``orchestration`` already uses for a condition of its
                own outside that vocabulary.
        """
        resolved = await self._resolved(event)
        proposals = await self._feedback.process(resolved)
        if not proposals and event.memory_kind is None:
            msg = (
                f"the wired FeedbackProcessor proposed nothing for a correction this loop "
                f"resolved to {resolved.memory_kind}; every kind in RESOLUTION_KINDS must be "
                f"mintable by it (ADR-0122 §3, §7) — the composition root has mis-wired the "
                f"loop, and the user's feedback is not being stored"
            )
            raise RuntimeError(msg)
        return tuple([await self._writes.write(proposal) for proposal in proposals])

    async def _resolved(self, event: FeedbackEvent) -> FeedbackEvent:
        """Return ``event`` with a ``memory_kind``, resolving an absent one (ADR-0122 §3).

        **A pin is authoritative and suppresses the read** (§6). A ``memory_kind``
        already present is the caller saying "I know which drawer, do not look", so
        this returns the event untouched and issues nothing. A resolution that ran
        and *then* deferred to the pin would perform a search whose result it
        discards; one that ran and *overrode* it would silently discard a choice the
        user stated. Neither is available.

        **The intent decides how an absent one is resolved**, and the two arms are
        not symmetric. A stated ``PREFERENCE`` establishes a ``PreferenceMemory`` by
        its own intent — the user is not pointing at a stored belief, they are
        stating one — so it resolves without a read. Omitting that arm would be a
        defect rather than a missing shortcut: ``interfaces/cli.py`` states the same
        asymmetry, but it binds one adapter, and *this* is where every producer's
        event arrives. A programmatic ``FeedbackEvent(kind=PREFERENCE, ...)`` with no
        ``memory_kind`` would otherwise be resolved by search, and a best-ranked
        semantic neighbour would file the user's stated preference as a fact — the
        wrong-drawer defect this stage exists to end, reproduced on the arm it was
        never about.

        A ``CORRECTION`` points at a belief that already exists, whose record type is
        a property of *that* belief, so it is read from the store
        (:meth:`_resolve_drawer`).

        Raises:
            MemoryStoreError: If the resolution's read failed. It propagates: see
                :meth:`_resolve_drawer`.
        """
        if event.memory_kind is not None:
            return event
        if event.kind is FeedbackKind.PREFERENCE:
            return event.model_copy(update={"memory_kind": MemoryKind.PREFERENCE})
        return event.model_copy(update={"memory_kind": await self._resolve_drawer(event.content)})

    async def _resolve_drawer(self, content: str) -> MemoryKind:
        """Name the drawer a correction belongs in — **never a conflict** (ADR-0122 §3).

        One ranked read, scoped to :data:`RESOLUTION_KINDS` and unscoped by band, and
        the best-ranked record's kind is the answer. It applies no similarity
        threshold and makes no ruling: it selects a kind and nothing else, and
        whether a contradiction exists remains ``MemoryIngestor``'s and the
        ``MemoryPolicy``'s question alone. A threshold here would duplicate
        ``conflict_threshold`` in a subsystem that may not import the constant
        holding it, and would drift from it silently. So a neighbour scoring below
        the ingestor's threshold simply finds no conflict there and is stored as new
        — today's outcome for that case, in the drawer the belief lives in rather
        than a different one.

        **``kinds`` is passed to ``search`` rather than applied afterwards**, and
        that is load-bearing. A page fetched unscoped is a page of whatever ranked
        highest, so a store holding many topically similar episodes returns them and
        nothing mintable, whereupon §5 files a correction whose target was sitting
        just below the cut. Passing ``kinds`` does not move the predicate before the
        ranking cut — ADR-0113 §2 moves the band alone — but it puts this read on
        exactly the footing ``MemoryIngestor._detect_conflicts`` already stands on.

        **Where more than one drawer matches, the best-ranked wins**, and no second
        proposal is minted (§4). Relevance is the only ordering this corpus admits:
        ADR-0113 §4 makes the band an eligibility axis and "never an ordering one",
        and a kind-preference rank invented here would be exactly the second ordering
        term ADR-0112 §1 refuses, on a weaker signal. One utterance is one belief —
        ``search`` returning neighbours in two drawers is a fact about the store's
        contents, not evidence that the user holds two wrong beliefs.

        **An empty read is a fact, and §5 answers it**: with no live target the
        correction is a free-standing assertion, and ``SEMANTIC`` is the drawer for
        one. Nothing is dropped, refused or held.

        **A failure is not a drawer.** The read is not wrapped, so a raising store
        aborts the ``learn``. This is the one place ``learn`` must not copy
        ``respond``: a turn whose retrieval fails is answered with fewer memories and
        says so through ``memory_degraded``, because an answer with less context is
        still an answer — but a correction whose *type* could not be resolved is
        about to be filed in a drawer chosen by the failure rather than by the
        belief. §5's fallback answers "the store looked and holds nothing", a fact;
        it may not be made to answer "the store could not look", which is not one. A
        transient failure genuinely costs a ``learn`` that might have completed;
        that is accepted, because a failed ``learn`` is a legible fault the user
        retries and a mis-drawered belief is a silent one they do not know to.

        **A stale resolution is benign and is not raced against.** This read happens
        outside ``MemoryIngestor``'s lock, so a record can retire between it and the
        probe; the correction then lands in a drawer whose target has just gone,
        finds no conflict, and is stored as new — again the pre-existing outcome, in
        a better drawer. Nothing is written on the basis of the resolution, so there
        is nothing for a race to corrupt.

        **Retrieval's reach is not claimed to be exhaustive.** A target ranked below
        this one read is not found, exactly as ``_detect_conflicts`` states for
        itself — "what it never surfaced is invisible here" — and it is issue #457's,
        neither closed nor widened by this read.

        Raises:
            MemoryStoreError: As the store raises.
        """
        candidates = await self._memory.search(
            content, limit=self._resolution_limit, kinds=RESOLUTION_KINDS
        )
        best = next(iter(candidates), None)
        return MemoryKind.SEMANTIC if best is None else MemoryKind(best.kind)

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

        **This composes per band rather than reading once** (ADR-0072 §5, via
        ADR-0113's ``bands`` filter). It used to make one band-neutral call and pass
        the records on unchanged, which is precisely what §5 refuses: "a flood of
        low-confidence inferences can displace an assertion *below the cut*". Issue
        #663 reported it and ADR-0112 §5 diagnosed it as unfixable on the contract
        of the day. The budget policy and the composition live in
        :func:`~ai_assistant.orchestration.retrieval.assemble_by_band`, which is
        where ADR-0113 §6 puts them; this method keeps only what it already owned —
        the query, the kind filter, and what a failure means for the turn.

        Degradation stays all-or-nothing, unchanged from the single-call version. A
        failure on any band's read discards the whole retrieval, which is a sharper
        edge than it was now that the assertions may already be in hand when the
        derived band's call fails; that is filed as #805 rather than answered here,
        because a partially-composed prompt is a short result that looks complete
        and choosing between the two is a policy question, not a refactor.
        """
        try:
            memories = await assemble_by_band(
                self._memory, query, limit=self._retrieval_limit, kinds=BELIEF_KINDS
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
