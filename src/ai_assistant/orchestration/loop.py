"""The closed learning loop: respond, observe a correction, reuse it (ADR-0022).

:class:`LearningLoop` is the first working slice of the request pipeline. It
wires five injected contracts — :class:`~ai_assistant.core.protocols.ContextProvider`,
:class:`~ai_assistant.core.protocols.MemoryStore`,
:class:`~ai_assistant.core.protocols.Planner`,
:class:`~ai_assistant.core.protocols.ToolRegistry` and
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
object. The registry it holds is read for one thing and one thing only — the
capability vocabulary the planner is told about (ADR-0211 §3) — and this object
neither finds a tool, nor sees a ``ToolDefinition``, nor invokes anything. All
three now exist —
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
    BeliefBand,
    FeedbackKind,
    Goal,
    MemoryKind,
    MemorySource,
    Provenance,
    TurnResult,
)
from ai_assistant.orchestration.conversations import BELIEF_KINDS
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.reads import (
    Servicing,
    TriggerOutcome,
    TurnReadAudit,
    service_read_request,
)
from ai_assistant.orchestration.retrieval import assemble_by_band

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        ContextProvider,
        FeedbackProcessor,
        MemoryStore,
        Planner,
        ToolRegistry,
    )
    from ai_assistant.core.types import (
        CurrentContext,
        FeedbackEvent,
        MemoryRecord,
    )
    from ai_assistant.orchestration.writes import MemoryWriteStage, WriteOutcome

_log = structlog.get_logger(__name__)

#: A filter over the supply one turn runs on, applied **between retrieval and
#: planning** (ADR-0203 §2).
#:
#: It is handed what the turn assembled, what it retrieved, and the ids of the
#: records **this turn's relevance reads returned**, and returns what the rest of
#: the turn may run over. It is a *filter*: it may remove members, and it may
#: not add one, reorder what survives, assemble a second context, issue a retrieval,
#: reach a ``ContextProvider`` or a ``MemoryStore``, or make a store query of any
#: kind. It may also remove **nothing at all**:
#: :class:`~ai_assistant.orchestration.disclosure.BoundedAudienceSupply` is that
#: filter, and it rides this seam because ADR-0204 §2 puts its *evaluation* at
#: exactly the point ADR-0203 §2 puts the subtraction — once per turn, between
#: retrieval and planning, on every conversational operation. This loop applies
#: whatever it is given and holds no disclosure *policy*: what is placed, what is
#: speakable and what a facet's class means all stay in
#: :mod:`~ai_assistant.orchestration.disclosure`, which is what keeps ADR-0199's
#: posture in one module.
#:
#: **What the loop does read off the filter, since ADR-0226 §5, is the channel's
#: audience** — and only that. §5 refuses to service a read request on an operation
#: whose output channel's audience is unbounded, and ADR-0199 §1 makes that posture
#: "a function of the output channel's audience alone", which is why
#: :data:`~ai_assistant.orchestration.disclosure.TurnSupply` is a closed union of
#: exactly two classes. So :meth:`LearningLoop._turn` asks which of the two it holds
#: rather than taking a second boolean beside this one: a pair a caller can
#: contradict is not fail-closed, and §5 is a fail-closed clause. A filter that is
#: neither — including ``None`` — has declared no posture, and nothing is serviced.
#: No predicate, no placement and no subtraction is read here.
#:
#: **The third argument is the read set, and it is deliberately not a group boundary**
#: (ADR-0210 §1, §10 item 1). It is the ids :meth:`LearningLoop._retrieve` returned
#: together with the ids :meth:`LearningLoop._supplement`'s own read returned
#: **before** ADR-0158 §4's deduplication — what a relevance read taken with this
#: turn's goal statement *chose*, rather than where the composition finally put it.
#: The two differ: a record both the conversation tail and the supplement's read
#: carry is deduplicated out of the supplement and stands in the supply at the
#: tail's position alone, so ``len(recent)`` cannot see that a relevance read
#: selected it. What a filter does with the set is the filter's own business — this
#: loop reads nothing off it and applies the same seam on every operation.
type SupplyFilter = Callable[
    [CurrentContext, tuple[MemoryRecord, ...], frozenset[str]],
    tuple[CurrentContext, tuple[MemoryRecord, ...]],
]

#: A user's own utterance is asserted, not inferred, so the goal it becomes
#: carries full confidence (``Provenance`` requires 1.0 for ``USER_ASSERTED``).
_FULL_CONFIDENCE = 1.0

#: How wide a turn's retrieval reads when no composer tunes it (#1163).
#:
#: Held equal to ``app/composition.py``'s ``RETRIEVAL_LIMIT``, which is what every
#: real deployment is built with — that module passes its own figure explicitly
#: (ADR-0119 §9) rather than relying on this one, so the two are kept in step for
#: the reader's sake and neither depends on the other. This default governs a
#: direct construction: a test, or a composer that has not decided.
#:
#: 15 rather than 5 on #1029's scored-pilot re-rank analysis: among retrieval
#: misses whose gold record was already in the store, the gold-citing record's
#: median cosine rank was 12 and 114 of 277 fell at ranks 6 to 10, so a budget of 5
#: discarded records the ranking had already found.
#:
#: **And 30 rather than 15 on ADR-0162 §9's reach sweep**, because complete intake
#: (§1) removed the ceiling that made depth here worthless. The belief layer used to
#: saturate at 63.1% — the ceiling of what its distilled records cite at all — so
#: ADR-0160 §1 spent the marginal slot on episodes instead; the probe's belief-reach
#: curve now runs 55.1% at 5 to 81.2% at 50 and is still climbing, against a control
#: that runs 31.2% to 38.8% and is flat by 15. On union all-gold-reached, 30+10
#: reaches 85.1% where the incumbent 15+15 reaches 79.8%. The value is **provisional**
#: in the way §9 states: the byte-budgeted single ranked pool ADR-0160 §5 leaves open
#: replaces it, and pilot 5's post-hoc attribution re-tests it.
#:
#: Nothing here is validated from above (``_check_tuning`` imposes no ceiling), so
#: the number is a tuning judgement and not a bound — it is deliberately far under
#: ADR-0119 §3's 256-id trace cap.
_DEFAULT_RETRIEVAL_LIMIT = 30

#: How many episodes the turn's **supplementary** read may add (ADR-0158 §3).
#:
#: Held equal to ``app/composition.py``'s ``EPISODIC_SUPPLEMENT_LIMIT`` exactly as
#: the belief budget above is held equal to ``RETRIEVAL_LIMIT``, and for the same
#: reason: the deployment figure is the root's, passed explicitly, and this one
#: governs a direct construction.
#:
#: **A second budget, never a share of the first.** ADR-0158 §3 refuses the share
#: because ``RETRIEVAL_LIMIT``'s 5→15 move was bought for beliefs on #1029's
#: rank-miss measurement, and a share hands part of it back on no measurement —
#: worst in precisely the deployments where the belief layer is working. Two
#: budgets cost prompt size, which is the honest cost.
#:
#: 15 on a measurement rather than a judgement (ADR-0160 §1). The value began at 5
#: with nothing behind it; #1029's pilot-3 anatomy puts episode recall@5 at 55.3%
#: against recall@15 at 72.7%, while the belief layer was saturated at 63.1% because
#: that was the ceiling of what its distilled records cite at all.
#:
#: **Then 10 on ADR-0162 §9, which was the reversal.** Complete intake lifts the
#: belief ceiling, so the marginal slot was worth more there: the probe put 30+15 at
#: 86.5% against 30+10's 85.1% — 1.4 points for half again as much transcript in
#: every prompt, where an episode is a verbatim turn against a belief's distilled
#: sentence.
#:
#: **And 30 on ADR-0224 §1, which reverses that in turn on evidence neither move
#: had.** The #1844 replay widens the *existing* blind read and converts through
#: pilot-5's own scored answers: ≈ +3.6 points of LoCoMo accuracy at 30+30 against
#: ≈ +1.3 at 30+15, for no additional model call, no new read, no envelope and no
#: trigger. The count guard is still a weaker guard on *bytes* than it looks, which
#: is what ADR-0158 §8's deferred byte bound is for, and ADR-0224 §4 says plainly
#: that this spends more of that unmeasured budget rather than less — outweighed,
#: on this corpus, by a measured gain the guard was costing. Both values stay
#: provisional under ADR-0162 §9's third clause and are re-tested by pilot 5's
#: post-hoc attribution (ADR-0160 §3), read off a scored run; no ablation arm is
#: owed for either.
#:
#: It is a *default*, not a floor: a construction tuning the belief budget below it
#: and stating nothing episodic gets this figure capped at that budget, which is
#: §3's ceiling holding rather than yielding. ``LearningLoop.__init__`` is where
#: that resolution happens, because the cap needs both numbers. At 30 against a
#: default budget of 30 the cap is still a no-op for an untuned construction, but it
#: now bites for **every** construction stating a belief budget below 30, where at
#: 10 only a budget below 10 reached it — a wider band, and the band parity implies
#: (ADR-0224 §2). ADR-0158 §3 still refuses a *stated* bound above the budget, which
#: at parity means it accepts 30 against 30 and refuses 31.
_DEFAULT_EPISODIC_LIMIT = 30

#: The kinds the episodic supplement's read selects (ADR-0158 §3) — ``EPISODIC``
#: and nothing else, which is the half of the read that keeps a belief out of the
#: supplement. Widening it to ``None`` would admit *derived beliefs* into a group
#: appended after the belief group, which is the one way a belief could appear
#: twice in one prompt; the tail deduplication in :meth:`LearningLoop._supplement`
#: would not catch it, being scoped to the continuity tail.
_SUPPLEMENT_KINDS: tuple[MemoryKind, ...] = (MemoryKind.EPISODIC,)

#: The band the episodic supplement's read is pinned to (ADR-0158 §3).
#:
#: **Pinned rather than left at ``None``, and that is not an assumption about who
#: writes.** Capture stamps ``OBSERVED`` unconditionally so every episode *this
#: system writes* is ``DERIVED`` — but ``EpisodicMemory`` accepts any valid
#: ``Provenance``, ADR-0074 §3 reserves an id namespace precisely because a foreign
#: producer taking one is a fault it must contemplate, and ``band_of`` maps
#: ``EXTERNAL`` to ``ATTESTED``. A band-blind flat read would therefore put an
#: ``ATTESTED`` record into a bare relevance order beside ``DERIVED`` ones,
#: bypassing the precedence ADR-0072 §5 exists to impose in the one read that has
#: no composition to impose it. Pinned, the single call is correct by construction:
#: an episode outside this band is simply not retrieved, which is the conservative
#: direction. Making the first such record retrievable is a decision of its own and
#: takes an ADR settling how the supplement composes across bands (ADR-0158 §3).
#:
#: The filter is on the *band* rather than on the source because band is what
#: precedence is defined over — an ``INFERRED``-sourced episode is ``DERIVED`` and
#: is retrievable, and nothing about precedence turns on the difference.
_SUPPLEMENT_BANDS: tuple[BeliefBand, ...] = (BeliefBand.DERIVED,)

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
#: spent; it is padding — against the *ranking cut*, which is the only thing left
#: that can hide a live target from this read. ADR-0128 §1 moved every eligibility
#: predicate ahead of that cut, ``kinds`` among them, so a page can no longer be
#: emptied by records the filter would have dropped afterwards; what a page of one
#: still cannot survive is a single higher-ranked record that *is* eligible.
#: ``MemoryStore.search``'s own default is the same number, which is the width this
#: corpus already treats as "a page".
_DEFAULT_RESOLUTION_LIMIT = 10


def _narrowed(
    narrow: SupplyFilter | None,
    context: CurrentContext,
    memories: tuple[MemoryRecord, ...],
    retrieved_ids: frozenset[str],
) -> tuple[CurrentContext, tuple[MemoryRecord, ...]]:
    """Apply the supply filter, or leave the supply alone where there is none.

    One function rather than two ``if narrow is not None`` sites, because
    :meth:`LearningLoop._turn` now applies the filter at one of **two** positions —
    before planning on an unbounded-audience turn, after the servicing on a bounded
    one (ADR-0226 §7) — and ADR-0204 §2's "once" is a property of the pair. Two
    hand-written applications is how a later edit gets a turn evaluated twice, or
    not at all.

    Args:
        narrow: The filter, or ``None`` to run over everything assembled.
        context: The context the turn assembled.
        memories: The supply, in its groups.
        retrieved_ids: The ids this turn's relevance reads returned (ADR-0210 §1).

    Returns:
        What the rest of the turn may run over.
    """
    if narrow is None:
        return context, memories
    return narrow(context, memories, retrieved_ids)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


def _check_tuning(
    *, retrieval_limit: int, resolution_limit: int, episodic_limit: int | None
) -> None:
    """Reject tuning that would disable a read while looking healthy.

    A *silent* misconfiguration, which is why it is refused at construction
    rather than left to surface as behaviour: ``retrieval_limit=0`` makes
    ``MemoryStore.search`` return nothing by contract, so every turn would be
    unpersonalised with ``memory_degraded`` reading ``False`` — a generic answer
    presented as a healthy personal one, the exact failure
    :attr:`TurnResult.memory_degraded` exists to expose.

    **``episodic_limit`` is checked on a different axis, and zero is allowed
    there.** ADR-0158 §3's ceiling — the episodic bound never exceeds the belief
    budget — is the one place the product thesis is stated checkably rather than
    documented: whatever the numbers become, nobody can configure a system that
    asks for more transcript than belief, and enforcing it here is what makes that
    survive whoever tunes it next. A *zero* bound is not the silent failure the
    paragraph above describes and is refused nowhere: the supplement is
    non-essential by construction, a turn at a bound of zero is exactly as personal
    as it would otherwise have been (ADR-0158 §4), and §6's retraction clause
    explicitly may set it. What is refused is a negative or non-integral one, which
    is a mistake rather than a decision.

    **``None`` is "I did not tune this", and it is checked against nothing.** §3's
    clause binds the *configured* bound, and a caller who omitted the argument
    configured none: :class:`LearningLoop` resolves it against the belief budget it
    was given, which cannot breach the ceiling. Refusing that case instead would
    make a caller who lowered ``retrieval_limit`` alone — the pre-ADR-0158 shape of
    every direct construction — fail on an argument they never passed, which is a
    regression dressed as a guard rather than the clause being enforced.

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
        TypeError: If any stated limit is not an integer.
        ValueError: If ``retrieval_limit`` or ``resolution_limit`` is not
            positive, if a stated ``episodic_limit`` is negative, or if a stated
            ``episodic_limit`` exceeds ``retrieval_limit`` (ADR-0158 §3).
    """
    # `isinstance` rather than a bare `< 1`, which `1.5` and `inf` both survive
    # — and a non-integral limit reaches `MemoryStore.search`, where a store
    # slicing by it raises `TypeError` far from the mistake. `bool` is excluded
    # because it is an `int` subclass and a flag is not a count.
    stated: tuple[tuple[str, object, int], ...] = (
        ("retrieval_limit", retrieval_limit, 1),
        ("resolution_limit", resolution_limit, 1),
        *((("episodic_limit", episodic_limit, 0),) if episodic_limit is not None else ()),
    )
    for name, value, floor in stated:
        if isinstance(value, bool) or not isinstance(value, int):
            msg = f"{name} must be an integer, got {value!r}"
            raise TypeError(msg)
        if value < floor:
            msg = f"{name} must be at least {floor}, got {value}"
            raise ValueError(msg)
    if episodic_limit is not None and episodic_limit > retrieval_limit:
        msg = (
            f"episodic_limit must not exceed retrieval_limit (ADR-0158 §3): "
            f"{episodic_limit} > {retrieval_limit}"
        )
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
        registry: ToolRegistry,
        feedback: FeedbackProcessor,
        retrieval_limit: int = _DEFAULT_RETRIEVAL_LIMIT,
        resolution_limit: int = _DEFAULT_RESOLUTION_LIMIT,
        episodic_limit: int | None = None,
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
            registry: The tool registry this turn's capability vocabulary is read
                from, once, immediately before the planner call (ADR-0211 §3).
                **It must be the same object the tool-selection stage resolves the
                resulting steps against** — a composition-root obligation of
                exactly the shape the writer's above is, and unstatable in the type
                system for the same reason. Wired to a second registry, or to a
                second snapshot of one, a step could be planned against a
                capability the selecting registry never advertised: the
                ``NO_CAPABLE_TOOL`` narration #1772 records, reintroduced by wiring
                rather than by prompting, and invisible to every test that stubs one
                side. It is **required and undefaulted**, for the reason ADR-0211 §1
                makes the planner's own parameter required: an empty default would
                make every goal requiring an act decline, silently, and
                indistinguishably from a deployment that advertises nothing. Only
                ``capabilities()`` is called on it, and what it answers is passed to
                the planner unchanged.
            feedback: Turns a ``FeedbackEvent`` into memory-update proposals.
                **The processor wired here must mint every kind in**
                :data:`RESOLUTION_KINDS` (ADR-0122 §3). Nothing in the type system
                can state it — ``FeedbackProcessor`` exposes ``process`` and nothing
                else — so it is a composition-root obligation in ADR-0028 §4's
                sense, exactly like the writer's above, and a root that wires a
                processor minting fewer has mis-wired the loop. :meth:`learn` is
                what stops a breach of it from being silent.
            retrieval_limit: How many memories a turn retrieves. The **belief**
                budget: it is never reduced, shared or made conditional by the
                episodic supplement below (ADR-0158 §3).
            episodic_limit: How many episodes the turn's supplementary read may
                add, on top of ``retrieval_limit`` and never out of it (ADR-0158
                §3). ``0`` disables the supplement, which is a supported
                configuration rather than a misconfiguration — §6's retraction
                clause is stated in exactly those terms — and is why this one
                alone admits zero. **``None`` means untuned**, and resolves to
                :data:`_DEFAULT_EPISODIC_LIMIT` capped at ``retrieval_limit``:
                §3's ceiling binds what is *configured*, so a caller who tuned
                only the belief budget gets a supplement that fits inside it
                rather than a refusal about an argument they never passed. A
                *stated* bound above ``retrieval_limit`` is still refused, which
                is where the ceiling has to be un-clampable.
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
            TypeError: If any of ``retrieval_limit``, ``resolution_limit`` or
                ``episodic_limit`` is not an integer (see :func:`_check_tuning`).
            ValueError: If either of the first two is below 1, if a stated
                ``episodic_limit`` is negative, or if a stated ``episodic_limit``
                exceeds ``retrieval_limit`` (see :func:`_check_tuning`).
        """
        _check_tuning(
            retrieval_limit=retrieval_limit,
            resolution_limit=resolution_limit,
            episodic_limit=episodic_limit,
        )
        self._context = context
        self._memory = memory
        self._writes = writes
        self._planner = planner
        self._registry = registry
        self._feedback = feedback
        self._retrieval_limit = retrieval_limit
        self._resolution_limit = resolution_limit
        # Resolved after the check, and against the *validated* belief budget, so
        # the untuned bound can never be the thing that breaches ADR-0158 §3's
        # ceiling and can never be computed from a limit that was itself refused.
        self._episodic_limit = (
            min(_DEFAULT_EPISODIC_LIMIT, retrieval_limit)
            if episodic_limit is None
            else episodic_limit
        )
        self._clock = checked_clock(now, owner="LearningLoop")
        self._id_factory = id_factory

    async def respond(
        self,
        utterance: str,
        *,
        history: Sequence[MemoryRecord] = (),
        history_degraded: bool = False,
        narrow: SupplyFilter | None = None,
    ) -> TurnResult:
        """Run one turn, and record what its planner asked to have read.

        The turn itself is :meth:`_turn`, which this method wraps for one reason:
        **ADR-0226 §9's record is written once per turn and is conditioned on
        nothing.** "A turn that fired and then failed for any reason still
        contributes its numerator; a turn that did not fire still contributes its
        denominator; and a turn that never reached the planner's judgement (§8)
        contributes to neither and is recorded as not reached." A ``finally`` is
        what makes that true of *every* exit rather than of the ones an author
        thought of: the planner raising, the registry raising above it, a blank
        utterance, a failing context assembly, a cancellation. Each ends the turn
        without a plan, so each is §8's third outcome — recorded, and then the
        original failure goes on propagating unchanged.

        **The record is written here and the servicing decision is made below**,
        which is the order §9 permits — "at any point in the turn after the
        servicing decision is known". What §9 forbids is the reverse: a record
        gated on the plan being persisted or on capacity being admitted, both of
        which happen *above* this method in
        :meth:`~ai_assistant.orchestration.engine.Engine._run_turn` and would
        "silently drop exactly the turns most worth counting".

        Args:
            utterance: What the user said (:meth:`_turn`).
            history: The conversation's recent turns (:meth:`_turn`).
            history_degraded: Whether reading that history failed (:meth:`_turn`).
            narrow: The supply filter, or ``None`` (:meth:`_turn`).

        Returns:
            The turn's goal, context, assembled memories and plan.

        Raises:
            PlanningError: As :meth:`_turn` raises it.
            ContextError: As :meth:`_turn` raises it.
        """
        audit = TurnReadAudit()
        try:
            return await self._turn(
                utterance,
                history=history,
                history_degraded=history_degraded,
                narrow=narrow,
                audit=audit,
            )
        finally:
            audit.emit()

    async def _turn(
        self,
        utterance: str,
        *,
        history: Sequence[MemoryRecord],
        history_degraded: bool,
        narrow: SupplyFilter | None,
        audit: TurnReadAudit,
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

        **An episode may nonetheless reach the prompt, as a supplement with a
        budget of its own** (ADR-0158). ``memories`` is therefore
        ``recent + retrieved + supplement``: three groups, in that order, never
        interleaved. The supplement is a *second* read
        (:meth:`_supplement`), not a widening of the first — the sentence above
        stays true and the belief budget is untouched — and position is how this
        corpus expresses precedence into a prompt, so a distilled belief precedes
        the raw turn it might have been distilled from even where the episode is
        the more relevant record.

        **A caller may narrow the supply between retrieval and planning, and
        nothing further is read to replace what it removed** (ADR-0203 §§1-2). The
        ``narrow`` filter is applied to the assembled context and to all three
        groups of ``memories`` once they are in hand, and the plan, the
        ``TurnResult`` and therefore every stage downstream of this method run over
        exactly what it returned. Nothing is refetched, widened, re-run or
        backfilled afterwards: a turn may reach the planner with fewer records than
        the same utterance would on a caller that narrows nothing, and that is the
        decision working.

        **The filter is also told what this turn's relevance reads returned**
        (ADR-0210 §1, §10 item 1). Beside the flat sequence it is handed the ids
        :meth:`_retrieve` returned and the ids :meth:`_supplement`'s own read
        returned **before** ADR-0158 §4's deduplication — a *membership*, carrying
        nothing about a score, a rank or a group. This method reads nothing off it
        and computes it on every operation alike; what a filter makes of it is the
        filter's, which is what keeps ADR-0199's posture in one module. A boundary
        index would have been cheaper and is not enough: a record both the
        conversation tail and the supplement's read carry stands in the supply at
        the tail's position alone, and only the read's own answer records that a
        relevance read chose it.

        **The planner is also told what this deployment can actually do**
        (ADR-0211 §§1, 3). The turn reads ``capabilities()`` from the injected
        registry — the same object the tool-selection stage resolves the resulting
        steps against — and passes it, so the plan is judged against the vocabulary
        as it stood at that read. `planning` performs no read of its own: the
        vocabulary is pushed in exactly as ``context`` and ``memories`` are, and for
        the same reason (ADR-0014 §6). The read sits **after** ``narrow``: nothing
        is withheld from it, because a registry holds configuration rather than
        personal data (ADR-0016 §6), so it is the same on a spoken turn as on a
        typed one.

        ``memory_degraded`` is deliberately **upstream** of it —
        it reports whether the history read and the retrieval succeeded, which is a
        fact about this method's I/O and not about what a caller then chose to be
        supplied (ADR-0203 §3).

        **And the planner may ask for one more read, which this method services
        into a fourth group** (ADR-0226). The plan comes back carrying at most one
        :class:`~ai_assistant.core.types.ReadRequest`; where the operation's
        channel audience is bounded,
        :func:`~ai_assistant.orchestration.reads.service_read_request` follows it
        — the citation hop first, then the sighted query, sharing one budget of ten
        records the supply did not already hold — and the records it returns are
        **appended whole** after the episodic supplement, never interleaved (§7).
        ``memories`` therefore has four groups on such a turn and three on every
        other, which is the one respect in which ADR-0158 §5's sameness clause is
        superseded: ``Planner.plan``'s ``memories`` still carries exactly three,
        because the planner is called before the servicer and cannot be handed a
        group produced from its own output.

        **On an operation whose channel audience is unbounded the request is not
        serviced at all** (ADR-0226 §5). ADR-0203 §2 forbids a read that replaces
        what the subtraction removed, and on such a turn the planner judges
        sufficiency over a supply the subtraction has already thinned — so the read
        it emits is shaped by what was withheld even though the planner never saw
        it. The emission is still recorded, because what is scoped is the servicing.

        **The withholding evaluation moves with the fourth group and does not run
        twice** (ADR-0226 §7, superseding ADR-0204 §2's timing clause alone).
        ``narrow`` is applied **once** on every turn: after the servicing where one
        was possible, and exactly where ADR-0203 §1 puts it everywhere else. A
        second application would disjoin two evaluations' results, which §7 forbids
        in terms; an evaluation taken before the servicing would under-fire "on
        exactly the records the planner asked for", which is #1708's laundering path
        reopened by a new route.

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
            narrow: A :data:`SupplyFilter` applied between retrieval and planning,
                or ``None`` to plan over everything the turn assembled and
                retrieved. It is given the assembled context, all three groups of
                ``memories``, and the ids this turn's relevance reads returned
                (ADR-0210 §1). ``converse_spoken`` supplies ADR-0199 §3's
                subtraction here (ADR-0203 §1); ``converse`` and
                ``converse_streaming``, whose channel audience is bounded, supply
                the filter that evaluates the same predicate and removes nothing
                (ADR-0204 §2, §4). ``None`` remains valid and plans over
                everything: this method is the seam, not the policy.
            audit: ADR-0226 §9's record for this turn, filled in as the stages
                run and emitted by :meth:`respond` on every exit.

        Returns:
            The turn's goal, context, assembled memories and plan — each of them
            over the supply ``narrow`` returned, where one was given.

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
        preceding = recent + retrieved
        supplement, supplement_read = await self._supplement(goal.statement, preceding=preceding)
        memories = preceding + supplement
        # ADR-0210 §1: what this turn's two relevance reads *returned*, taken with
        # this turn's own goal statement. `supplement_read` is the read's own answer
        # **before** ADR-0158 §4's deduplication, which is why this is a set of ids
        # and not an index into `memories`: a record both the tail and that read
        # carry is deduplicated out of the supplement and survives at the tail's
        # position, where no boundary can distinguish it from a record the tail
        # merely happened to hold (§1's second clause).
        retrieved_ids = frozenset(record.id for record in retrieved) | supplement_read
        # ADR-0226 §5's channel scoping, read off the object that carries the
        # posture rather than taken as a second argument beside it. A boolean the
        # caller supplies alongside ``narrow`` is a pair a caller can *contradict* —
        # an unbounded supply declared bounded would service a request on the one
        # channel §5 refuses, and subtract after planning rather than before it —
        # and §5 is a fail-closed clause.
        #
        # **Exact, not `isinstance`, and `TurnSupply`'s members are `@final`.** What
        # is being asked is "which of ADR-0199 §1's two postures is this", and §1
        # makes that a closed question: a subtype is not a third answer to it. A
        # subclass overriding `__call__` to subtract would be classified bounded and
        # would put withheld records in the planner's own prompt, so the runtime test
        # declines it and `@final` stops it being written at all. Every other filter —
        # `None`, or one a test supplies — has declared no posture, and §5 refuses
        # rather than guesses, which is the same fail-closed direction.
        bounded_audience = type(narrow) is BoundedAudienceSupply
        if not bounded_audience:
            # ADR-0203 §1: between retrieval and planning, and applied to the
            # context as well as to the records — a facet no ADR has placed is
            # withheld from the planner exactly as an unplaced record is.
            # Everything after this line, this method's own return value
            # included, runs over what it returned.
            context, memories = _narrowed(narrow, context, memories, retrieved_ids)
        # ADR-0211 §3: read within the turn, from the registry selection resolves
        # against, and immediately before the call — so the plan is judged against
        # the vocabulary as it stood at this read. Nothing is withheld from it and
        # nothing needs to be: the registry "holds configuration, not personal
        # data" (ADR-0016 §6), so there is no record to place, no provenance to
        # read and no class to withhold, and the vocabulary is the same on a spoken
        # turn as on a typed one. That is why this sits *after* `narrow` rather
        # than inside it.
        capabilities = await self._registry.capabilities()
        plan = await self._planner.plan(
            goal, context=context, memories=memories, capabilities=capabilities
        )
        # ADR-0226 §8: the trigger *is* the emission, so the plan carrying a
        # request is the whole of what "the trigger fired" means. Read once, above
        # the branch, because every arm below reports it.
        request = plan.read_request
        audit.trigger = TriggerOutcome.NOT_FIRED if request is None else TriggerOutcome.FIRED
        if request is not None:
            audit.kinds = tuple(ask.kind for ask in request.asks)
            # ADR-0226 §5: what is scoped is the **servicing** and never the
            # emission, so a planner on an unbounded-audience turn is not told
            # its request will not be serviced and nothing suppresses it — the
            # trigger goes on being measured on every channel, and the audit
            # records the emission and that it was declined.
            audit.servicing = Servicing.SERVICED if bounded_audience else Servicing.DECLINED
        if bounded_audience:
            if request is not None:
                # ADR-0226 §5: after the planner returns and before the
                # `TurnResult` is constructed. `memories` here is the very
                # sequence the planner was passed, which is both §3's label space
                # and §7's deduplication set.
                # The servicer *writes* its record rather than returning one, on
                # every path out of it — including the one a cancellation carries
                # away, which is not a `MemoryStoreError` and so reaches neither its
                # degradation nor a `return` here. ADR-0226 §9's record is emitted
                # from `respond`'s `finally` regardless, so a servicing that never
                # finished must not leave one saying it completed.
                await service_read_request(self._memory, request, supply=memories, audit=audit)
                # §7: appended whole after the episodic supplement, never
                # interleaved. The three groups keep their positions, their order
                # and their meanings.
                memories += audit.read.records
            # ADR-0226 §7, superseding ADR-0204 §2's timing clause and nothing
            # else of §2: one evaluation, over the turn's **final** supply. On a
            # bounded-audience operation the filter subtracts nothing (ADR-0204
            # §4), so the planner above saw exactly what it would have seen with
            # the filter applied ahead of it — what moves is *when* the evaluation
            # is taken, so that it sees the group the planner asked for.
            context, memories = _narrowed(narrow, context, memories, retrieved_ids)
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
        # ``capped`` is unwrapped and not acted on (ADR-0128 §6). This read only
        # wants the nearest neighbour's kind, so a prefix answers it exactly as a
        # complete set would; whether ``LoopEngine`` should set ``memory_degraded``
        # from the signal is a policy this ADR deliberately does not decide.
        found = await self._memory.search(
            content, limit=self._resolution_limit, kinds=RESOLUTION_KINDS
        )
        best = next(iter(found.records), None)
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

    async def _supplement(
        self, query: str, *, preceding: Sequence[MemoryRecord]
    ) -> tuple[tuple[MemoryRecord, ...], frozenset[str]]:
        """Retrieve *episodes* relevant to ``query``, to append after the beliefs.

        ADR-0158 §1 admits the capability #791 held open: a question whose answer
        was said once and never distilled is answerable from an episode the store
        already holds, already embeds and already pays for. #1029's error anatomy
        priced the alternative — 652 of LoCoMo's 1,540 answerable questions, 42%,
        failed because the fact never became a belief, with the gold turn sitting in
        the same store and the same index, unreachable only because
        :meth:`_retrieve` asks for ``BELIEF_KINDS``.

        **A separate read, and everything that keeps it from becoming naive RAG is
        in this method's arguments.** ``kinds`` is
        :data:`_SUPPLEMENT_KINDS` and ``bands`` is :data:`_SUPPLEMENT_BANDS`, both
        pinned; the budget is this loop's own ``episodic_limit``, which never comes
        out of the belief budget. Merging the two reads instead — one kind-blind
        call — is what ADR-0158 §2 refuses: every episode is ``DERIVED`` by
        construction so the band composition would contain nothing, ADR-0128 §1
        binds ``kinds`` before the KNN cut so an admitted episode spends a candidate
        slot no downstream pass can give back, and a store holds an episode per turn
        against a belief per distilled fact — 17 to 42 beliefs from ~300 turns on the
        pilot's corpus. Under one shared budget the belief layer would be routinely
        displaced from its own answering prompt, not occasionally outranked.

        **The separator rule, which is a renderer constraint and not a second
        cap** (ADR-0158 §4). ``planning.planner`` splits ``memories`` into the
        conversation tail and the retrieved group by taking the **leading run** of
        ``EPISODIC`` records, so any belief between the two keeps them apart. Where
        the belief composition is empty there is no separator, the tail and the
        supplement form one unbroken episodic run, and the whole of it renders under
        the tail's heading — telling the model that an episode from three weeks ago
        was said moments ago. That is a fabricated claim about continuity, produced
        silently, and it is worse than the supplement being absent, so the
        supplement is dropped wherever nothing before it is non-``EPISODIC``. Two
        distinct states reach that: a resumed conversation whose query matched no
        belief, and the first turn of a fresh one, where the supplement would be the
        whole of ``memories``.

        The check is made *before* the read rather than after it, because dropping
        the result is the decision either way and an unread store is one fewer round
        trip and one fewer ``RETRIEVAL`` trace claiming a read whose records nothing
        used.

        **Deduplication against the tail** (ADR-0158 §4). The tail's records are
        episodes of this same store with these same ids (ADR-0074 §5, ADR-0086 §6),
        so a relevance read over ``EPISODIC`` returns them whenever the current
        conversation is on topic — the common case, not the edge. Without this the
        supplement's whole budget reprints what the prompt already carries, under a
        second heading. The **tail's** copy survives because its position carries the
        conversational order, which the supplement's does not. Deduplicating costs
        the supplement a slot rather than re-asking for a deeper page, exactly as
        ``assemble_by_band`` decides the same question: over-requesting against an
        estimate of duplicates is the headroom decision ADR-0113 §8 declines without
        #789's measurement.

        The belief group cannot collide here — ``BELIEF_KINDS`` and
        :data:`_SUPPLEMENT_KINDS` are disjoint — so the comparison over the whole of
        ``preceding`` is the tail rule with a strictly free extra term, and is
        written that way so it stays correct if a caller's ``history`` ever carries
        something else.

        **A failure drops the supplement alone** (ADR-0158 §4), and specifically
        does **not** set ``memory_degraded``: the beliefs are in hand, the plan is
        exactly as personal as it would have been at a bound of zero, and that flag
        is the one signal a user is told to trust for "you got a generic answer".
        Reporting a false positive on it costs more than the omission. The failure
        is not thereby silent — the store emits its ``RETRIEVAL`` trace on the fault
        path (ADR-0119 §8) and this stage logs, as the belief path's failure does.
        This is the clause of ADR-0158 that partially supersedes ADR-0022 §3's
        Retrieval row, in the scope of this read alone; the belief path's
        all-or-nothing degradation is untouched.

        **The read's own answer is returned beside the deduplicated supplement**
        (ADR-0210 §1, §10 item 1). The two differ by exactly what the tail or the
        belief composition already held, and the difference is load-bearing: a
        stamped episode of this conversation that this read *does* return is
        deduplicated away here and survives only at the tail's position, so a
        caller reading the composed groups alone would conclude no relevance read
        of this turn had chosen it. It is a set of ids and never the records —
        the deduplicated copies are the ones the turn runs over, and a second set
        of record objects at the same ids is a supply nobody supplied.

        Args:
            query: The turn's goal statement, the same query the belief
                composition was read with.
            preceding: The records already assembled for this turn, in order — the
                continuity tail and then the retrieved beliefs. Read for the
                separator rule and for deduplication, never appended to here.

        Returns:
            Up to ``episodic_limit`` episodes, best first, none of them already
            present in ``preceding``, and the ids this read returned **before**
            that deduplication. Both are empty where the bound is zero, where the
            separator is absent, or where the read failed — in the last case
            because nothing was returned to record, not because the answer is
            being suppressed.
        """
        if self._episodic_limit <= 0:
            return (), frozenset()
        if all(MemoryKind(record.kind) is MemoryKind.EPISODIC for record in preceding):
            return (), frozenset()
        try:
            found = await self._memory.search(
                query,
                limit=self._episodic_limit,
                kinds=_SUPPLEMENT_KINDS,
                bands=_SUPPLEMENT_BANDS,
            )
        except MemoryStoreError:
            # Warned, not raised, and `memory_degraded` deliberately untouched by
            # the caller: this is the whole of ADR-0158 §4's failure rule.
            _log.warning("episodic_supplement_degraded", stage="supplement", exc_info=True)
            return (), frozenset()
        # `capped` is unwrapped and not acted on (ADR-0128 §6), as the belief
        # composition's own read leaves it: a supplement is non-essential, so a
        # store's candidate ceiling shortening it is not a fact this turn reports.
        held = {record.id for record in preceding}
        return (
            tuple(record for record in found.records if record.id not in held),
            frozenset(record.id for record in found.records),
        )

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
