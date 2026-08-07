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

Cancellation (ADR-0060), binding on **every** Protocol below:

    **A method that acquires a resource must not orphan it under cancellation.**
    If a method acquires anything whose safety outlives the coroutine — a
    connection, a lock, a spawned task, a file handle, a transaction — then at
    the moment ``CancelledError`` leaves that method, every such resource is
    either released, or still held exclusively by work the method started and
    can observe finishing. Never released while that work is still using it;
    never left held with nothing running that will release it.

    **A cancellation delivered from outside the call is delivered onward, never
    absorbed.** A method may defer delivery while it makes its resources safe,
    but it re-raises; it never converts such a cancellation into a return value,
    and never lets a collaborator's suppressed cancellation stand in for its
    own. Where delivery is deferred, the wait is on something the implementation
    can observe completing, and the deferral is bounded or documented as
    unbounded.

    *From outside* is load-bearing. A cancellation a method **issues itself**,
    to enforce a deadline it owns, is its own control flow and may be classified
    into a return value — that is exactly what ``ToolInvoker.invoke`` does on
    expiry (ADR-0029 §4), and what its ``Raises: CancelledError`` clause
    distinguishes when it says the seam does not convert a task "cancelled from
    outside". The resource clause above is unconditional and binds both cases;
    only the propagation clause turns on provenance.

    **A cancelled call's effect is indeterminate to the caller.** A cancelled
    write may or may not have committed. The caller may assume neither, and in
    particular may not assume the write did not land.

    The rule is cooperative and is stated in the weaker, true form: no seam can
    stop work that declines to be cancelled. What the rule buys is that the
    *resource* is safe and the cancellation *arrives*, not that the work stops.

Most Protocols here say nothing further about it, because no implementation of
them holds anything across an ``await`` — silence marks where the rule has no
bite today, never a seam it cannot reach (ADR-0060 §2).

Input observation (ADR-0065), binding on **every** Protocol below:

    **A call observes its inputs at one instant, before its first await.**

    Arguments belong to the caller, several types crossing these seams are
    mutable, and a ``Sequence`` argument is a container the caller may still be
    holding. So everything one call derives from one argument — what it stores,
    what it computes, what it returns — comes from **one** observation of that
    argument. A caller that mutates what it passed while the call is suspended
    may make the call act on the wrong version; it must never make one result
    describe two different versions.

    Three ways to discharge this, and the choice is the implementation's: do not
    suspend; do not read an argument again after suspending; or take a snapshot
    on the coroutine's first executed line — before the first ``await`` — and
    read only the snapshot thereafter, the returned value included. A snapshot
    must be deep enough to cover everything the call goes on to read. A frozen
    argument is not a discharge on its own: ``MemoryWrite`` is frozen and holds a
    mutable ``MemoryRecord``.

    The boundary is the coroutine's **first executed line**, not the call
    expression. Calling an ``async def`` only builds a coroutine, so a mutation
    made after construction and before the first await is captured whole. That is
    not a tear — the caller gets the state as of the moment the work began — and
    no invocation-time capture is claimed (ADR-0056).

    **The caller's side.** A caller may not assume a mid-flight mutation was
    ignored, nor that it was honoured. What it is owed is that the outcome is
    *coherent*, not that it reflects any chosen version. Mutating an argument
    across a call still in flight remains a caller error; this rule bounds the
    damage rather than blessing the practice.

    Silent where a method does not suspend, or where its arguments are immutable
    all the way down — which is most of this file.

The two clauses are a **different axis each**, deliberately, and neither is
scoped from the other's list (ADR-0065 §"This is not ADR-0060's axis"): one is
about a resource the implementation acquired, the other about an object the
caller still owns. ``AuditTrail`` is enforced under the first and wholly vacuous
under the second; ``Planner`` is the reverse.

Each subsystem declared in the architecture map adds its Protocol here as it is
designed, so this file grows to hold every seam that crosses a subsystem
boundary. ``tests/core/test_protocol_triad.py`` is what keeps that growth
honest: it enumerates the Protocols declared here and fails the gate for any one
missing its conformance suite, its canonical fake, or the binding that runs the
two together.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ai_assistant.core.types import DEFAULT_PAGE_SIZE

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime, timedelta

    from ai_assistant.core.types import (
        ActionPlan,
        ActionRequest,
        AnswerOutcome,
        Belief,
        BeliefBand,
        BeliefSummary,
        Confirmation,
        ContinuationToken,
        Conversation,
        ConversationDigest,
        ConversationExport,
        ConversationSummary,
        ConversationTurn,
        CurrentContext,
        DeferralAdmission,
        DeferralClaim,
        DeferralState,
        DeferredProposal,
        Embedding,
        EncodableText,
        EpisodicMemory,
        ExecutionState,
        FeedbackEvent,
        Goal,
        GoalDeletion,
        GrantableSource,
        GrantScope,
        Identifier,
        LearnOutcome,
        MemoryDecision,
        MemoryIngestResult,
        MemoryKind,
        MemoryRecord,
        MemoryUpdateProposal,
        MemoryWrite,
        Message,
        NonBlankEncodableText,
        ObservationOutcome,
        ObservationReport,
        ParkedBinding,
        PermissionDecision,
        PermissionRuling,
        PlanExport,
        Question,
        RecordChunk,
        SourceGrant,
        SourceReading,
        StepTransition,
        ToolCall,
        ToolDefinition,
        ToolResult,
        TurnOutcome,
        WalkPosition,
    )


@runtime_checkable
class ModelProvider(Protocol):
    """A model-agnostic language-model client.

    Concrete implementations (in `models`) wrap pydantic-ai so the rest of the
    system never imports a provider SDK directly. This is the seam that makes
    the assistant model-agnostic.

    How :meth:`complete` observes the conversation it is handed is governed by
    this module's input-observation clause (ADR-0065).
    """

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        """Produce the assistant's next message given the conversation so far.

        ``messages`` must be a conversation **awaiting an assistant reply**: it
        must be non-empty, and must not end with a ``Role.ASSISTANT`` turn. A
        caller asks ``complete()`` for the *next* assistant message; a history
        that already ends with one has nothing left to answer, and an empty
        history has nothing to answer at all. Either is a malformed request and
        raises ``ModelError`` before any model is contacted (ADR-0066 §1).

        Stated on the roles of ``messages``, deliberately — not on any translated
        representation — so it binds an implementation that never touches
        pydantic-ai. ``Role.SYSTEM`` is unaffected: a history ending in a system
        turn is a request and stays one.

        This is a **necessary condition, not a sufficient one**. It names two
        shapes that are never a request, and admits nothing by omission — a
        history satisfying it may still be refused for reasons of its own. A
        ``Role.TOOL`` turn is the case that makes the distinction bite: a tool
        exchange is not representable at this seam, and both implementations
        reject any history containing one. Passing this clause does not make such
        a history acceptable, and nothing here promises tool support.

        Args:
            messages: Conversation history, oldest first. Non-empty, and not
                ending on a ``Role.ASSISTANT`` turn.
            model: Optional ``"provider:model"`` override; falls back to the
                configured default when ``None``.

        Returns:
            The assistant's reply as a :class:`~ai_assistant.core.types.Message`.

        Raises:
            ModelError: If ``messages`` is empty, or ends with a
                ``Role.ASSISTANT`` turn. What binds every implementation is the
                *disposition*, not the class identity: the error is neither
                ``retryable`` nor ``routable``, because a malformed argument
                reproduces identically on every attempt from every route
                (ADR-0066 §3). An implementation is free to raise a subclass
                carrying that disposition.
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

    Cancelling :meth:`embed` is governed by this module's cancellation clause
    (ADR-0060).
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

    Records also carry a ``validity`` window — the valid-time axis of ADR-0045.
    ``get`` and ``search`` return only records *live at now* (both ends of the
    window enforced: past ``valid_until`` or before ``valid_from`` are hidden),
    the same read-time treatment ``expires_at`` gets. The two axes are
    independent and both are honoured: ``expires_at`` is retention (an expired
    record is gone from *everything*, including ``export``), the window is truth
    (a window-closed record is off the read path but **retained** and still
    returned by ``export``). A record can be retired-but-retained or
    still-live-but-expired; each axis is judged on its own terms.

    Writes are one-at-a-time through :meth:`add`, or many-at-once and atomically
    through :meth:`write_atomic` — a batch that commits in full or not at all
    (ADR-0046). ``write_atomic`` is the primitive supersession rides: closing a
    belief's window and inserting its replacement are two writes that must land
    together, never leaving the first without the second (ADR-0045 §8).

    Two reads answer two different questions and must not disagree. :meth:`search`
    is *retrieval*: it takes a query and ranks by relevance. :meth:`list_beliefs`
    is *inspection*: no query, a specified total order, a page, and a filter on the
    belief band (ADR-0073 §1). Both honour the same two read-time axes through the
    same store-level predicate, so "what do you believe about me" and "what do you
    retrieve" can never answer differently about a record's liveness.

    Reads come in three shapes and none of them may disagree with another about a
    record's liveness. :meth:`get` and :meth:`get_many` answer the same question
    about one id and about many; :meth:`search` is *retrieval* and :meth:`get_many`
    is neither — it resolves ids the caller already holds, in one snapshot, so a
    batch is internally consistent where a loop of singles is not (ADR-0086 §6).

    A fourth read is the *resumable enumeration* a scheduled job walks:
    :meth:`walk_records` returns a chunk in the store's own insertion order and
    :meth:`advance_walk` records how far a named walk has reached (ADR-0114).
    They are two operations rather than one on purpose — reading never advances
    anything — so a caller can make a chunk's effects durable *between* them,
    which is the ordering ADR-0111 §3 obliges and which a combined operation would
    make unexpressible. Neither is a retrieval: the walk ranks nothing and its
    order is a position rather than a judgement of relevance, so it is no part of
    what ADR-0112 governs.

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060). How :meth:`add` and :meth:`write_atomic` observe the records they
    are handed, how :meth:`get_many` observes its ``record_ids``, and how
    :meth:`list_beliefs` observes its ``bands`` and ``kinds`` filters, is governed
    by this module's input-observation clause (ADR-0065).
    """

    async def add(self, record: MemoryRecord) -> str:
        """Persist a record and return its id.

        Adding a record whose ``id`` already exists overwrites the previous one
        (an upsert), so ``id`` is the caller's idempotency key. All backends share
        this behaviour; the shared conformance suite enforces it.

        **The upsert is a claim, not a default to fall back on** (ADR-0108 §1). A
        caller that means to *install* — to write a record whose id was minted,
        derived, or taken from a producer, and which it expects to name nothing
        stored — uses :meth:`write_atomic` with
        ``MemoryWriteMode.INSERT_IF_ABSENT`` instead. That refuses the collision
        inside the same write that would otherwise destroy the standing record, so
        the check costs no read and cannot be raced. The accidental collision and
        the deliberate one are indistinguishable in the bytes, so nothing but the
        caller's declaration can tell them apart.

        **Callers inside this package declare it as a ``MemoryWriteMode``, not by
        reaching for this method.** ``add`` remains the upsert and remains part of
        this contract — implementations outside this repository satisfy it, which is
        why the cross-kind refusal below binds it too — but a method name does not
        *say* what it does, and "which writes can destroy a record" has to stay
        answerable by reading. So the one fold that deliberately lands on a stored
        record states ``MemoryWriteMode.UPSERT`` through :meth:`write_atomic`
        (ADR-0108 §2), and a new ``add`` call here is a choice to defend in review
        rather than a line to reach for.

        **A cross-kind collision is refused** (ADR-0108 §4). Where ``record.id``
        names a stored record of a different ``kind``, nothing is written. This is
        the same refusal :meth:`write_atomic`'s ``UPSERT`` mode makes, stated on
        both doors because an upsert-capable door that did not make it would be
        the way around it. "Names a stored record" is physical presence, in
        ``write_atomic``'s sense: an expired or window-closed row still collides.

        Raises:
            MemoryStoreError: ``record.id`` names a stored record of a different
                ``kind`` — nothing is written — or the write fails.
        """
        ...

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        """Apply every write in one atomic unit — all commit, or none do.

        The batch is ordered and all-or-nothing. On any element's failure — an
        ``INSERT_IF_ABSENT`` whose id already names a stored record, or any
        backend error — nothing in the batch is committed: no record it named is
        added, overwritten, or removed, so no read reflects the batch. ``get``,
        ``search`` and ``export`` return what they would have had ``write_atomic``
        not run, under their normal time-based filtering (a record that expires or
        whose window closes mid-call is hidden by that filter, ADR-0007/ADR-0045
        §6, not by any batch effect). On success every record is persisted.

        Returns the ids written, in the order of ``writes``. An empty batch is a
        no-op and returns an empty sequence.

        **An ``UPSERT`` element refuses a cross-kind collision** (ADR-0108 §4):
        where its id names a stored record of a different ``kind``, the whole batch
        fails and nothing is committed, exactly as any other element's failure
        does. ``INSERT_IF_ABSENT`` needs no such clause — it already refuses
        *every* collision, and refuses it earlier, so a cross-kind one raises
        ``MemoryStoreConflictError`` on that standing ground with the narrower
        "re-mint and retry" remedy intact.

        Raises:
            MemoryStoreConflictError: an ``INSERT_IF_ABSENT`` element's id already
                names a stored record. Nothing is written; the caller may re-mint
                and retry.
            MemoryStoreError: an ``UPSERT`` element's id names a stored record of a
                different ``kind`` (ADR-0108 §4), any other backend failure, or a
                malformed batch (two writes to the same id, ADR-0046 §3). Nothing
                is written.
        """
        ...

    async def get(self, record_id: str) -> MemoryRecord | None:
        """Return the record with ``record_id``, or ``None`` if it is not readable.

        Returns ``None`` when the record is absent, expired, **or not live at
        now** — a closed ``valid_until`` (``valid_until <= now``) or a not-yet-open
        ``valid_from`` (``valid_from > now``); both ends of the window are enforced
        (ADR-0045 §6).
        """
        ...

    async def get_many(self, record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
        """Return the readable records among ``record_ids``, keyed by id (ADR-0086 §6).

        The batch form of :meth:`get`, landed because two contract-mandated
        callers resolve *k* ids at a time — a conversation resume's history tail
        (ADR-0074 §5) and belief presentation, which ADR-0073 §4 and ADR-0077 §6
        oblige to resolve every citation of every belief on a page. At
        ``list_beliefs``' default page of 50 and
        :data:`~ai_assistant.core.types.MAX_EVIDENCE_CITATIONS` citations each
        that is 3,200 single reads for one screen, each one a lock acquisition on
        the shipped store; this makes it 50. ADR-0074 §5 declined it and named the
        hub as where to revisit — that trigger did **not** fire, and this lands on
        the argument the deferral actually turned on rather than on the one it
        named (ADR-0086 §6 partially supersedes ADR-0074 §5).

        **It never disagrees with ``get``.** For every id, this returns the record
        :meth:`get` would return, or omits it exactly where :meth:`get` would
        return ``None`` — absent, expired, or not live at now, both ends of the
        window enforced (ADR-0007, ADR-0045 §6). An id that does not resolve is
        **simply missing from the mapping**; it is never an error and never a
        ``None`` value. A second read that answered differently about a record's
        liveness is the failure this Protocol's docstring already forbids between
        ``search`` and ``list_beliefs``; a third read gets the same rule.

        **One read-time snapshot for the whole batch.** Every id in a call is
        judged against **one instant**, and against **one state of the store**: the
        result is exactly what this store would return for those ids at some single
        point in time, so no two entries can disagree about when "now" was or about
        what was stored then. This is a real guarantee and not book-keeping —
        resolving 64 citations through 64 ``get``s judges them against 64 instants,
        so a citation can expire mid-resolution and a belief's rendered count
        disagree with its own tombstones. **The guarantee is the snapshot, not any
        mechanism for obtaining one**: a lock and one clock reading is how the
        shipped SQLite store meets it, a transactional or remote store may meet it
        with no lock at all, and naming a mechanism here would put one concrete
        store's synchronisation into a contract every consumer depends on.

        **A mapping, not a sequence**, because the caller's question is *which* ids
        resolved — that is the lost count and the tombstone placement — and a
        positional result would make every caller re-derive the correspondence.
        Duplicate ids collapse, so the mapping never has more entries than the
        argument has distinct ids. Records are detached snapshots, like every other
        ``MemoryStore`` read.

        **There is deliberately no size cap on the argument** (ADR-0086 §6). This
        is not the unbounded read ADR-0021 §4 warns of: every record it returns had
        to be named, so the result is bounded by an argument the caller enumerated.
        A backend with a per-statement limit of its own meets that by chunking
        *behind* the single snapshot above, never by refusing — an implementation
        limit is not a contract limit, and this Protocol does not let one become
        one.

        How this call observes ``record_ids`` is governed by this module's
        input-observation clause (ADR-0065), exactly as ``write_atomic``'s
        ``Sequence`` argument is.

        Args:
            record_ids: The ids to resolve. An **empty sequence returns an empty
                mapping** and requires no round trip: asking for nothing is a
                question with an answer, in the same words ``list_beliefs``'
                ``limit=0`` and ``write_atomic``'s empty batch already use.

        Returns:
            A mapping from id to record, holding an entry for exactly those ids
            :meth:`get` would answer with a record.

        Raises:
            MemoryStoreError: If the store cannot be read, or a stored record is
                corrupt.
        """
        ...

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
    ) -> list[MemoryRecord]:
        """Return the records most relevant to ``query``, best first.

        Expired records are never returned, nor are records not live at now — a
        record whose window is closed or not yet open is omitted, both ends
        enforced, exactly as an expired one is (ADR-0045 §6).

        Args:
            query: The search text.
            limit: Maximum number of records to return.
            kinds: If given, restrict results to these memory kinds.
        """
        ...

    async def list_beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """Enumerate the beliefs held right now, newest revision first (ADR-0073 §1).

        The band-scoped read ADR-0072 §7 ruled owed: "show me what you believe
        about me". It carries **no query text** and is not a retrieval — nothing is
        ranked and no relevance is computed — so it is an enumeration with a stable
        order and a page rather than a filter on :meth:`search`.

        **Both read-time axes are honoured, exactly as ``get``/``search`` honour
        them.** An expired record is never returned, and neither is a record not
        live at now — a closed ``valid_until`` or a not-yet-open ``valid_from``,
        both ends enforced (ADR-0007, ADR-0045 §6). Inspection reads **live
        beliefs only**: a retired record is not a belief the assistant holds but a
        record of one it used to, and it stays reachable through ``export`` alone
        (ADR-0073 §3). There is deliberately no ``include_retired`` axis.

        **The order is total, stable and specified: ``provenance.last_updated``
        descending, ties broken by ``id`` ascending.** Some total order has to be
        named or two stores answer the same page differently while each believes it
        conforms — the argument ``AuditTrail.recent`` already makes, applied to a
        second store. Newest-revision-first is the right default for inspection,
        and supersession moves ``last_updated``, so a corrected topic surfaces
        where the user will look for it.

        **A page is the slice ``[offset : offset + limit]`` of the ordered,
        filtered sequence.** Take every record passing **both** filters and **both**
        read-time axes, order it by the rule above, skip ``offset`` of them, and
        return the next ``limit``. It follows that **a page is full whenever enough
        matching records exist**: exactly ``limit`` records come back when the
        filtered set has at least ``offset + limit`` members. So every predicate
        this read applies belongs *before* the cut — the two filters and both
        read-time axes alike. That binds the window more strictly than ``search``
        is bound: ADR-0045 §6 permits filtering ``valid_from`` after the ranking
        cut there, because dropping a row costs a method with no offset a result it
        never owed, whereas here it drops a row the caller can reach by no later
        page at all.

        Offset paging over a mutating store may skip or repeat a record — a
        revision moves one in the order and a deletion shifts every later one. That
        is accepted and named rather than closed: a listing a user re-runs is not a
        transaction (ADR-0073 §2), and no total match count is offered ("is there
        more" is answered by asking for the next page).

        ``score`` is ``None`` on every returned record — **cleared, not merely
        unset**. No relevance was computed, and a *stored* record can already carry
        one, since ``add`` accepts any :class:`~ai_assistant.core.types.MemoryRecord`
        including one ``search`` returned with its score populated.

        Records are detached snapshots, like every other ``MemoryStore`` read.

        Args:
            bands: If given, restrict results to these belief bands. ``None`` means
                every band; an **empty sequence selects nothing**. Keyed on
                :class:`~ai_assistant.core.types.BeliefBand` and never on
                ``MemorySource``: the band is the vocabulary ADR-0072 §2 ratified
                and the unit the user reads, and a source filter would push
                ``band_of`` into every caller and let one ask for half a band —
                ``OBSERVED`` without ``INFERRED`` — which ADR-0072 §4 keeps
                indistinguishable to the supersession law.
            kinds: If given, restrict results to these memory kinds. The same
                convention, stated rather than inferred from ``search`` so no
                implementation reads ``kinds=()`` as "no filter" — the opposite
                outcome, every record instead of none. The two filters compose by
                **conjunction**: a record is listed when its band is selected *and*
                its kind is.
            limit: Maximum number of records in the page. ``limit=0`` returns an
                empty page: asking for nothing is a question with an answer.
                Bounded by default (50, matching ``AuditTrail.recent``), because an
                unbounded read of a Tier 1 store by default is a shape worth not
                offering (ADR-0021 §4).
            offset: How many records of the ordered, filtered sequence to skip
                before the page begins.

        Returns:
            The page: matching records in the specified order, each a detached
            snapshot with ``score`` cleared to ``None``.

        Raises:
            ValueError: If ``limit`` or ``offset`` falls outside ``0 <= value <
                2**63`` — non-negative, and representable as a signed 64-bit
                integer. Both ends are refused rather than clamped because both are
                places two backends silently disagree. *Negative* is
                ``AuditTrail.recent``'s argument with more force: this is the first
                ``MemoryStore`` read that reaches a backend as a literal
                ``LIMIT ?``/``OFFSET ?``, and SQLite reads ``LIMIT -1`` as *no limit
                at all*, turning the bounded read into the unbounded one it exists
                to avoid. *Too large* is the same failure from the other side:
                Python's ``int`` is unbounded and SQLite's parameter binding is not,
                so an over-wide value raises ``OverflowError`` out of the driver
                while an in-memory store answers with an empty page. This
                deliberately differs from ``search``, whose non-positive ``limit``
                matches nothing: that limit is a ranking cut applied after a KNN and
                can neither invert into unboundedness nor reach a bind parameter.
            MemoryStoreError: If the store cannot be read, or a stored record is
                corrupt.
        """
        ...

    async def walk_records(self, walk: NonBlankEncodableText, *, limit: int) -> RecordChunk:
        """Read the next chunk of a named walk, changing nothing (ADR-0114 §1).

        The resumable enumeration a scheduled job walks. It examines at most
        ``limit`` records **in the store's own insertion order**, beginning
        strictly after the position recorded for ``walk``, and returns the
        eligible ones among them together with the position of the last record it
        **examined**.

        **It writes nothing.** Two consecutive reads with no intervening
        :meth:`advance_walk` return the same records. Splitting the read from the
        advance is what lets a caller put its effects *between* the two, which is
        the ordering ADR-0111 §3 obliges; an operation that advanced as it read
        would make a cursor leading its effects the only available behaviour.

        **The order is keyed on a value the store issues once per stored record,
        and never reissues.** Every key a store issues is greater than every key
        it has already issued, and no key is reissued after the record holding it
        is deleted, purged, retired or superseded, or after the store is emptied.
        A merely *unique* key is not enough: releasing a deleted top record's
        number to the next insert hands a new record a position an exhausted walk
        has already passed, so the walk never returns it, reports success, and
        nothing downstream knows the record existed. That guarantee runs from the
        moment a store begins issuing keys under this contract, and the first key
        it issues then is greater than every key present at that moment; keys
        issued before the store carried a walk surface are outside it, and no
        implementation is obliged to know what they were.

        **The read takes no caller filter, and it honours the store's own
        lifecycle predicate.** Those are different things and they fail in
        opposite directions. A caller filter would make a position mean "the last
        record matching *this* filter", so two callers sharing a name with
        different filters would advance each other past unexamined records. The
        lifecycle predicate cannot do that: it is fixed and identical for every
        caller of every walk. Any selection over a chunk is the caller's.

        **Only records retained *and* live at the instant it reads are
        yielded** — the same predicate :meth:`get` and :meth:`search` apply, on
        both ends of the validity window. An expired record is never yielded and
        neither is one whose window is closed or not yet open. The instant is read
        **once per chunk**, so one chunk is judged against one reading of the
        clock. Omitting this would make the walk the one read in the store that
        breaches retention, handing expired content — or a belief the user has
        already corrected — to a producer that will write a *new* durable belief
        from it (ADR-0045 §6). The walk sides with ``get``/``search`` rather than
        with :meth:`export`, because everything that *derives* new content reads
        the live set.

        A record whose eligibility changes *below* the cursor is not revisited,
        which is ADR-0111 §2's named limit: a window that opens after the walk
        examined its record is never reached. A job whose correctness requires
        reconsidering changed rows cannot express its selection as a high-water
        mark alone, and this contract gives it no other mechanism.

        Args:
            walk: Names the walk whose position this read resumes from. Opaque to
                the store: never interpreted, never normalised, and never shared
                between two names, so two names differing only in case or spacing
                are two walks. **Validated on entry**, before it reaches a query, a
                key or any stored state — the annotation states the intent and the
                entry check is what enforces it, because these aliases are pydantic
                validators and Python runs nothing for a plain method call.
            limit: Maximum number of records to **examine**, not to return. The
                bound is on examination because a read that scanned forward until
                it had ``limit`` *eligible* records would have no bound at all: a
                long run of expired or window-closed rows makes one call walk
                arbitrarily many of them, which is the unbounded chunk ADR-0111 §4
                forbids.

        Returns:
            The chunk: its eligible records in walk order, and the position of the
            last record examined. That position is absent **exactly when there was
            nothing left to examine**, and that — never an empty record list — is
            how a caller learns the walk is exhausted. A chunk may carry a position
            and no records, meaning the range it examined held nothing eligible;
            a caller advances on it exactly as on any other.

        Raises:
            ValueError: If ``walk`` is not
                :data:`~ai_assistant.core.types.NonBlankEncodableText` — empty,
                whitespace-only, or unencodable. Or if ``limit`` is not **exactly
                an ``int``** or falls outside ``1 <= limit < 2**63``. Every
                implementation checks both on entry, before the value reaches a
                query or a slice, so the refusal is the same refusal on every
                backend and none substitutes a different bound. ``bool`` is
                refused with the rest: it is an ``int`` subclass, so ``True``
                satisfies every range comparison and would quietly become a
                one-record chunk. **Zero is refused rather than answering with an
                empty page** as :meth:`list_beliefs` does, because here it is not
                harmless: a chunk that examines nothing carries no position, and an
                absent position *means the walk is exhausted* — so a job
                configured to a zero chunk would report a completed walk having
                read nothing at all. ``-1`` is refused for the mirror reason
                :meth:`list_beliefs` gives: SQLite reads ``LIMIT -1`` as *no limit*,
                so a forwarded argument returns the whole store from inside a job
                whose entire purpose is to be bounded.
            MemoryStoreError: If the store cannot be read, or a stored record is
                corrupt.
        """
        ...

    async def advance_walk(self, walk: NonBlankEncodableText, *, position: WalkPosition) -> None:
        """Record how far a named walk has reached (ADR-0114 §3).

        Writes the given position durably before returning, so a walk that has
        advanced has advanced whatever follows.

        **The caller advances only to a position from a chunk whose effects are
        already durable.** That is a caller-ordering precondition **no store can
        enforce** — the advance is a call like any other, and the store sees the
        same two calls in the same order whether or not the work between them
        landed. So every lane that ships a walking job ships a test for it: a
        failure or a cancellation arriving after the chunk's work has begun and
        before its effects are durable must leave the walk's recorded position
        **unchanged**, so the chunk is re-processed on the next run. A job tested
        only on its success path satisfies no clause of this contract.

        **The cursor never moves backwards.** An advance to a position at or
        behind the one recorded for that walk leaves the recorded position
        unchanged and is **not an error**. That makes the caller's mistakes
        harmless in the safe direction: a scheduled walk is at-least-once, so a
        resumed run can legitimately hold a stale position, and under this rule
        the worst outcome is repeated work — which the gate already folds into a
        ``REINFORCE`` rather than a duplicate (ADR-0077 §8). Without it the worst
        outcome is a walk rewound past records the *next* advance skips forever.
        Only the store can honour this, because only the store can compare two
        positions — the same fact that makes a position's opacity cost the caller
        nothing.

        **No transaction handle and no record writes cross this seam.** Every
        producer the corpus has reaches memory through the orchestration write
        stage (ADR-0078 §3, ADR-0106 §6), so a walker's effects are committed
        inside a transaction it does not hold, and a ``writes=`` parameter here
        would be surface with no consumer. What that costs is exactly one repeated
        chunk on a crash between a chunk's effects and its advance, which
        ADR-0111 §3 ratifies as the designed cost.

        Args:
            walk: Names the walk whose position is recorded. Opaque, as on
                :meth:`walk_records`, and validated on entry the same way.
            position: A position **this walk's** chunk read returned. The only
                admissible source is that read and the only admissible use is this
                call.

        Raises:
            ValueError: If ``walk`` is not
                :data:`~ai_assistant.core.types.NonBlankEncodableText`. Or if
                ``position`` is one the store can tell is invalid **from the value
                itself** — a malformed or missing token, or a value that is not a
                :class:`~ai_assistant.core.types.WalkPosition` at all, ``None``
                included. An implementation may not reach a different exception
                class by reading a field before it validates:
                ``AttributeError``, ``TypeError`` and a bare ``KeyError`` are
                breaches of this clause rather than variants of it, and
                ``model_construct`` builds an instance *without* running the
                model's validator, so a malformed token does reach the store with
                the declared type satisfied. Or if ``position`` is bound to a
                **different** walk — a defined refusal on every backend rather
                than a silent no-op, since an implementation makes the bound walk
                recoverable from the token it hands out. That is the whole of what
                the store detects: a well-formed token naming the right walk that
                no chunk read ever issued is a breach of opacity by the caller,
                and no implementation is obliged to notice one.
            MemoryStoreError: If the store cannot be written. A caller's bad
                argument is never reported as one.

        Note:
            Each refusal above leaves **every** recorded walk position exactly as
            it was — the named walk's and every sibling's. A refused call changes
            nothing.
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

        **Every recorded walk position is discarded with the records, in the same
        operation** (ADR-0114 §4). No walk resumes from a position naming rows a
        ``clear`` removed; leaving them would produce exactly the cursor-disagrees
        -with-store state ADR-0111 §7 has to detect, and not creating it is better
        than detecting it.

        **The key sequence is *not* reset**, and the two halves together are what
        make an in-flight walk safe across a ``clear``. A walker can be holding a
        chunk's position when another caller empties the store, and it will then
        advance to a position this method has already discarded; that advance is
        the first for its walk, so nothing compares against it and the store
        records it. That is harmless **only** because every record added after the
        ``clear`` is issued a key above every key issued before it, so the stale
        position names a point below all of them and the next chunk returns every
        one. An implementation that reset its high-water mark here would instead
        leave that stale position sitting *above* live records that would never be
        read again.

        Returns:
            The number of records removed. Discarded walk positions are not
            counted: they are operational state rather than records.
        """
        ...

    async def export(self) -> list[MemoryRecord]:
        """Return a portable snapshot of every retained (non-expired) record.

        The caller serialises the records to JSON (e.g. ``model_dump(mode="json")``);
        the snapshot carries no embeddings (ADR-0007 §3). Unlike ``get``/``search``,
        ``export`` returns records **whether their validity window is open or
        closed** — a superseded belief is data the store holds, so a data-rights
        export must include it (ADR-0045 §6, amending ADR-0007 §3). Only *expired*
        records (past ``expires_at``) are excluded: retention still wins over
        history, so a record the system promised to forget cannot resurface here.

        **Walk positions are absent**, and nothing about one is Tier 1: a position
        is a row position rather than content, which ADR-0111 §9 classifies as
        Tier 2. This is stated because ``export`` is ADR-0007's data-rights
        surface and a lane extending it would have no reason to know that.
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

        **A tainted derived proposal is never committed unconfirmed** (ADR-0106
        §6, giving ADR-0098 §4's fourth clause its enforcement point). No policy
        returns a committing ruling — ``ACCEPT``, ``REINFORCE``, ``SUPERSEDE`` or
        ``STORE_TEMPORARY`` — on a proposal whose ``proposed.provenance`` is in
        the ``DERIVED`` band, carries
        :attr:`~ai_assistant.core.types.Provenance.derived_from_external`, and
        carries no :class:`~ai_assistant.core.types.UserConfirmation` — whatever
        the policy's other rules, and however trusted the producer. Its terminal
        ruling is ``ASK_USER`` or ``REJECT``; the contract admits either, and
        which one a policy picks is its own reasoning. The fact is read off the
        argument already passed, so this needs no store and no evidence
        resolution — which is why ADR-0098 §5 could not site the rule and this
        one can.

        **The condition is band-scoped, and deliberately not
        :func:`~ai_assistant.core.types.rests_on_recorded_external_content`.**
        The two differ in both directions and each difference is load-bearing. An
        ``ATTESTED`` proposal satisfies that predicate by definition and must
        still be allowed to commit — a ceiling stated over it would refuse every
        reader's import and make the reader useless. And a stray
        ``derived_from_external`` outside the ``DERIVED`` band triggers nothing,
        because ADR-0106 §7 leaves such a record constructible while ADR-0106 §2
        says the field means nothing there. The rule is about a model-authored
        generalisation about the user that external content helped produce, never
        a faithful transcription at a band that already caps its standing
        (ADR-0098 §4).

        **A confirmation passes it.** ADR-0078 §5's confirmed answer is a
        *re-ingest*: the coordinator rebuilds the proposal carrying the user's
        authority and calls the writer again, marker and all. A rule firing a
        second time there would ask the user the question they just answered, and
        a tainted consolidation could never land at all. A ruling reached by
        asking the user is not the *auto*-acceptance ADR-0098 §4 forbids.

        Nothing here obliges the *wording* of any ``reason`` (ADR-0106 §6): a
        deployment injecting its own policy owns the legibility of its own
        questions, and this ceiling still binds it.

        Args:
            proposal: The candidate memory and why it was proposed.
            conflicts: Existing records the proposal contradicts, already
                resolved from the store (the proposal carries their ids).

        Returns:
            The decision to accept, reject, reinforce or supersede a named
            target record, defer to the user, or store the proposal temporarily.
        """
        ...


@runtime_checkable
class MemoryWriter(Protocol):
    """The memory write path: conflicts, policy, persistence, in one call.

    The "persist" half of propose/dispose/persist (ADR-0028). It exists so a
    consumer of memory — the `orchestration` pipeline, above all — can commit a
    proposal without re-deriving `memory`'s own semantics: how a conflict is
    found, and what folding two records into one means.

    A writer holds its own :class:`MemoryPolicy` and its own store, and exposes
    neither. **The store it writes to must be the one its caller retrieves
    from** — a composition-root obligation, unenforceable here precisely because
    no store is on this seam (ADR-0028 §4).

    How :meth:`ingest` observes the proposal it is handed is governed by this
    module's input-observation clause (ADR-0065).
    """

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Resolve conflicts, ask the policy to rule, and apply its ruling.

        **Evidence must resolve.** A proposal whose ``proposed`` record is in the
        ``DERIVED`` band and whose ``provenance.evidence`` names a record this
        store does not hold is **refused**, before any ruling is sought: nothing
        is written, and no decision is returned (ADR-0077 §5). The refusal is a
        raise rather than a fabricated ``REJECT`` because a ruling is the policy's
        to make (ADR-0005 §3).

        This is a check, not a guarantee — an evidence record destroyed **by
        another actor** between the check and the write leaves a citation that no
        longer resolves, and no seam closes that. What it buys is that **every
        citation resolved once**, so a citation that later stops resolving is
        *loss* rather than a producer bug, and a surface presenting the belief can
        say so honestly. That residue stands exactly as it did (ADR-0077 §5/§6): a
        citation destroyed under the writer by someone else is *loss*, rendered as
        a tombstone with the presented confidence lowered, and no writer refusal
        closes it. What ADR-0081 §5 bounds is only the sentence's reach — a
        destruction performed by **this call's own write** is not that residue and
        is refused outright, below. ADR-0077 §5 is thereby **amended, not
        superseded**: nothing it decided changes, and every mechanism §6 specifies
        is keyed on a citation *failing* to resolve, which the refused case never
        reaches.

        It is deliberately **not** a floor on citing *nothing*: an empty evidence
        tuple names no record that fails to resolve, so it passes here and is
        judged by the policy, which is where ADR-0072 §3 put that rule. The two do
        not overlap, and each lives in exactly one place.

        **No write consumes the evidence its own proposal cites** (ADR-0081 §1).
        A ruling that would **install** the proposal at an id that same proposal's
        ``provenance.evidence`` names is **refused**: nothing is written, no window
        is closed, and no decision is returned. A write *installs* when it stores
        the proposal's content at an id — ``ACCEPT`` and ``STORE_TEMPORARY`` at the
        proposed record's own id, ``REINFORCE`` at the fold target it names, where
        a fold would union the target's id into the evidence of the record it
        writes *at* that id. A ``REINFORCE`` naming a ``target_id`` that is **not
        among the conflicts** installs nothing and is unaffected: it still raises
        on that standing ground instead, since this rule adds one refusal to the
        writer and subtracts none. It holds **whether or not** a record already stands
        there, and for **every** band, not only ``DERIVED``: the defect is a belief
        standing as its own warrant, and an ``ASSERTED`` or ``EXTERNAL`` record can
        reach it with nothing destroyed at all. The refusal keys on ids and write
        modes alone, so it reads nothing from the store and cannot be raced.

        A ``SUPERSEDE`` **re-mints** instead. Its correction lands at a freshly
        minted id, so where that candidate is one the proposal cites a conforming
        writer mints another rather than installing there; where it cannot find a
        free id within its own bound it refuses, with every target left live and
        unchanged (ADR-0081 §4). Its retirement-set writes **retire** rather than
        install — the record is written back with only its window narrowed and is
        retained — so a ``SUPERSEDE`` retiring a record the proposal cites still
        retires it and still lands. That is ADR-0077 §6's ratified residue, and
        this rule adds no refusal to ``SUPERSEDE`` and removes none: every standing
        refusal at this boundary keeps its precedence and its scope, and being
        cited neither triggers one nor excuses one.

        The rule is quantified over **this proposal's** evidence and **this
        write's** destination, both in hand when each write is formed — never over
        the tuple a ``REINFORCE`` unions (ADR-0081 §1a). A target that already
        cited *itself* is therefore out of scope: the fold neither creates that
        condition nor destroys the cited record, and refusing it would make such a
        record permanently unfoldable while making the refusal depend on state read
        from the store. ``REJECT`` and ``ASK_USER`` write nothing and are
        unaffected — once the call reaches the policy, a self-citing proposal the
        policy declines is reported as the decision the policy made rather than
        converted into an exception. The refusals that already *precede* a ruling
        keep that precedence: a self-citing proposal whose evidence does not
        resolve, or whose conflict set is over the ceiling, is still refused before
        any policy is asked.

        **An installing ruling states that it installs, and a colliding id is
        refused** (ADR-0108 §1, §2, §3). ``ACCEPT`` and ``STORE_TEMPORARY`` write
        the proposal as a *new* record: the ruling is that it contradicts nothing
        retrieved, so an id already naming a stored record is an accident in every
        case, and the write is **refused** — nothing written, no window closed. The
        writer does **not** re-mint the proposal's id and does not retry. That id
        is the producer's, and re-minting it would edit a record the producer made
        (ADR-0081 §9) and return an id nobody proposed; the refusal is a
        ``MemoryStoreConflictError``, whose documented remedy — re-mint and retry —
        is the producer's to take. This is the writer declaring what it means,
        not a store default doing it for free: :meth:`MemoryStore.add` remains an
        upsert, and a writer reaching for it here would silently destroy the
        standing record (#630). ``REINFORCE`` is the opposite case and is
        unaffected: it folds *at the target the ruling named*, so landing on a
        stored record is the decision rather than a collision, and it upserts.

        **A correction resolves every conflict it is shown, or it does not land**
        (ADR-0079 §1). A writer's conflict limit is a *ceiling*, not a truncation
        budget: at or below it the whole set conflict resolution surfaced reaches
        the policy — nothing retrieved is discarded — and above it this call
        **refuses**, writing nothing, closing no window and seeking no ruling. The
        obligation is stated on what the writer *retrieved*, because that is all a
        writer can observe; retrieval is not thereby exhaustive, and a conflict it
        never surfaced is invisible to this rule (issue #457). The limit's value
        stays each writer's own tuning; only the behaviour at the boundary is
        contract.

        **A ``SUPERSEDE`` retires the whole ruled-on set** (ADR-0079 §3, restating
        ADR-0050 §1): the record ``target_id`` names — **including** where that
        target is ``EXTERNAL`` (ADR-0045 §5b) — *and* every other conflict in the
        set the policy ruled on whose source is supersedable, in one atomic unit
        with the correction. The two standing refusals are unchanged: nothing folds
        onto a ``USER_ASSERTED`` target under either ruling, and ``USER_ASSERTED``
        and ``EXTERNAL`` *siblings* are never swept in.

        **A retirement clamps, and never resurrects** (ADR-0080 §1). Each record a
        supersession retires is written back with its window closed at the
        **earlier** of the writer's close instant and the record's own
        ``valid_until``, every other field preserved — so a retirement never
        extends a window and never moves ``valid_from``. One close instant serves
        the whole retirement set; how a writer determines that instant is expressly
        not contract, so a writer with no clock at all still conforms. A record
        already ended by its own terms is written back unchanged on the window,
        which counts as resolved rather than skipped.

        Where no representable close exists — a record the ruling would retire
        carries a ``valid_from`` at or after that end, so the window would be empty
        or inverted — this call **refuses**, with nothing written, no window
        closed, and every record in the set left **unchanged**: a statement about
        the stored records and their windows, not about what a later read returns,
        which ADR-0045 §6's read-time predicate decides at the reader's own clock
        (ADR-0080 §3).

        **No writer *installs* a record whose ``provenance.evidence`` exceeds
        :data:`~ai_assistant.core.types.MAX_EVIDENCE_CITATIONS`** (ADR-0086 §2).
        Where the record it would install does, it installs the retained subset
        and records the count of what it did not. The bound lives here and not on
        :class:`~ai_assistant.core.types.Provenance` because a validator would run
        on deserialisation too and make an *already-stored* over-long belief
        unreadable; the type admits a longer tuple, and a record already stored
        with one stays readable.

        - **"Install" is ADR-0081 §1's sense**, reused rather than redefined: a
          write installs when it stores the proposal's content at an id — an
          ``ACCEPT`` or ``STORE_TEMPORARY`` at the proposed record's id, a
          ``REINFORCE`` at its fold target, a ``SUPERSEDE``'s correction at the id
          it mints. **A write that merely *retires* is not an install** and carries
          the record as it stands, so a ``SUPERSEDE`` whose target is a legacy
          over-bound record retires it with its tuple and its ``evidence_elided``
          untouched. Truncating on the way *off* the read path would be an eager
          rewrite, which is the failure this bound is placed here to avoid.
        - **A ``REINFORCE`` whose union would exceed the bound retains the last
          ``MAX_EVIDENCE_CITATIONS`` of the deduplicated union** — recency, because
          the union deduplicates by id so every citation has weight exactly one and
          "most reinforcing" does not exist to be selected, while the oldest
          citations are the ones likeliest to have expired already (ADR-0086 §3).
          ``SUPERSEDE`` is untouched by this: ADR-0040 §5a has it carry nothing of
          the target across, so there is no union to bound.
        - **The elision is recorded, never silent** (ADR-0086 §4). The installed
          record's ``evidence_elided`` is the **sum of the counts on every record
          the install draws content from, plus the citations this install
          displaces** — one recurrence over every install, so a ``REINFORCE`` sums
          both records' counts even when the union fits and a proposal that already
          carried a count never has it reset. A ``SUPERSEDE`` draws from the
          proposal alone; the target's count is not inherited, even though the
          target's id survives.

        The scope is a :class:`~ai_assistant.core.types.MemoryRecord` install.
        :class:`~ai_assistant.core.types.Goal` carries a ``Provenance`` too and
        does not cross this seam; ADR-0077 §11 assigns that to the lane adding an
        inferred-goal producer.
        :class:`~ai_assistant.core.types.FeedbackEvent` is likewise unbounded and
        needs no rule of its own: a proposal derived from one crosses this seam
        like any other, and is bounded and counted here.

        Args:
            proposal: The candidate memory and why it was proposed. Its
                ``conflicts`` are resolved here, not supplied by the caller.

        Returns:
            The policy's decision and the id written, or ``None`` if nothing
            was.

        Raises:
            UnresolvedEvidenceError: If a ``DERIVED`` proposal cites a record the
                store does not hold. Carries the unresolved ids, so a caller can
                tell an evidence record that went away under it from a producer
                citing something it was never handed. Nothing is written and the
                policy is not asked. A ``MemoryStoreError``, so an existing
                handler for that class still catches it.
            MemoryStoreError: If conflict resolution surfaces more conflicts than
                this writer will resolve in one ingest (ADR-0079 §1) — nothing
                written, no ruling sought; if a record the ruling would retire has
                no representable close (ADR-0080 §3) — nothing written, every
                record in the set unchanged; if a ruling would install the proposal
                at an id the proposal cites, or a ``SUPERSEDE`` cannot mint an
                uncited free id within its bound (ADR-0081 §1/§4) — nothing
                written, every target live and unchanged; if reading conflicts or
                writing a record failed; or if a ``REINFORCE`` or ``SUPERSEDE``
                named a ``target_id`` that is not among the conflicts. Each of
                those refusals raises this class and **not**
                ``UnresolvedEvidenceError``, which names an *evidence* failure
                rather than a conflict set, a target's window, or a write set
                (ADR-0080 §7, ADR-0081 §3). The self-consuming-write refusal earns
                no subclass of its own: it is a pure function of the proposal and
                the ruling, so it is never a race and always a producer fault, and
                no caller has a second branch to take.
        """
        ...


@runtime_checkable
class ContextProvider(Protocol):
    """Assembles the situational :class:`~ai_assistant.core.types.CurrentContext`.

    The pipeline's context step (ADR-0008). Implementations compose one or more
    internal sources; only this typed contract crosses a subsystem boundary.

    Cancelling :meth:`assemble` is governed by this module's cancellation clause
    (ADR-0060).
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
class Observer(Protocol):
    """Distils beliefs about the user out of episodes it is handed (ADR-0077).

    The producer that makes passive accumulation real: it reads a bounded batch of
    :class:`~ai_assistant.core.types.EpisodicMemory` records — what actually
    happened — and proposes what the system should believe as a result. Named for
    that product role, as every Protocol here is (``Planner``, ``MemoryPolicy``,
    ``FeedbackProcessor``); nothing in this codebase uses the subscription pattern
    the word otherwise names.

    **It holds no store handle, and that is the scope limit rather than a rule
    about it.** :meth:`observe` receives the episodes; an implementation cannot
    fetch more, cannot widen its own batch, cannot read a belief, a plan, an audit
    record or a permission decision, and cannot reach :class:`MemoryStore` at all.
    The alternative — a producer holding a store and choosing what to read — would
    make "the scope of observation" a property of one implementation's code rather
    than of a ratified seam, and every later reviewer would have to re-derive it by
    reading that code. Here it is a type: episodes in, proposals out. **Selecting**
    the batch therefore belongs to `orchestration`, the one place that legitimately
    holds both stores by injection (ADR-0074 §9).

    **It writes nothing, and cannot rule on its own output.** An implementation
    holds neither a :class:`MemoryWriter` nor a :class:`MemoryPolicy`; the caller
    puts each returned proposal through the write path, in order and
    independently, exactly as the feedback loop already does (ADR-0009 §3,
    ADR-0028 §4). That is the whole content of "the model proposes; a
    deterministic policy disposes" for the producer the principle was written for
    (ADR-0005 §3), and ADR-0075 §2 names this producer as the paradigm case the
    gate exists for — it is **not** covered by the capture exemption.

    **A batch is a set of episodes, not a conversation.** Nothing here requires
    the batch's members to share a conversation, and an implementation must not
    ask which conversation an episode came from: an episode belonging to no
    conversation is the default shape (ADR-0074 §3), and a producer keying on
    conversation membership would re-impose "episode = turn" one layer up.

    How :meth:`observe` observes the batch it is handed is governed by this
    module's input-observation clause (ADR-0065) — its ``Sequence`` argument is a
    container the caller may still be holding, so the clause has real bite here
    even though every :class:`~ai_assistant.core.types.EpisodicMemory` in it is
    frozen. Cancelling it is governed by this module's cancellation clause
    (ADR-0060); a call that reaches a model provider is the widest suspension
    window in the system.
    """

    async def observe(self, episodes: Sequence[EpisodicMemory]) -> ObservationOutcome:
        """Propose what the batch justifies believing about the user.

        **What may be proposed.** A ``SemanticMemory``, ``PreferenceMemory`` or
        ``ProceduralMemory`` — never an ``EpisodicMemory``. An episode is a record
        that something happened, and the only thing entitled to write one is the
        deterministic capture path that was present when it happened (ADR-0074 §3,
        ADR-0075 §2). A model-authored episode would be a fabricated event wearing
        the type reserved for witnessed ones, and later beliefs would *cite* it as
        though it were evidence. An observer distils evidence; it does not
        manufacture it.

        **And it states no subject.** Every proposal leaves ``about_person``
        unset; one that would state it is **not proposed**, and is counted in
        ``discarded_unusable`` (ADR-0100 §5). This adds nothing to the bar below —
        a belief warranted only when it is *about the user* never has a non-owner
        subject to state, so the refusal excludes nothing a conforming observer
        would have produced. What it changes is that the bar is now *checkable*:
        an obligation that has been in this contract since ADR-0077 §2 with
        nothing able to see it is pinned by the shared conformance suite. It does
        not make that bar enforceable, and must not be read as though it did — a
        model proposing "Marta prefers window seats" with ``about_person`` unset
        is as undetectable after ADR-0100 as before. The difference is that the
        honest case is now recordable and the dishonest one is a lie about a
        field.

        **The refusal is the producer's and stays there.** It is not implemented
        by a caller dropping a returned proposal — the caller's obligation below
        is to put *each* returned proposal through the write path, in order and
        independently, and an exception to that clause is a change to this seam
        rather than a use of it — nor by a policy rule keyed on the band, since
        the axis is band-independent and ``MemoryPolicy.decide`` receives no
        producer identity to key on. Either would buy this producer's discipline
        by charging someone else's contract (ADR-0100 §5, ADR-0081 §3).

        **Every proposal is in the ``DERIVED`` band** — ``provenance.source`` is
        ``OBSERVED`` or ``INFERRED`` (ADR-0072 §2) — and the choice between them
        is ADR-0072 §3's test: whether the cited evidence *entails* the belief, or
        merely *supports* it. A wrong ``OBSERVED`` record is a recording bug; a
        wrong ``INFERRED`` record is a reasoning error over evidence that is itself
        correct, and a producer that cannot tell them apart is not entitled to
        either label.

        **Evidence discipline.** Every proposal cites at least one episode id, and
        **the ids are the producer's, never the model's**: an implementation that
        prompts a model references episodes by a label it assigned, and maps each
        label back to the id of the episode it actually read. This is ADR-0047 §2's
        rule applied to citations, and it is load-bearing — a model that can write
        an id can write one for an episode it never saw, and the provenance
        display would then confidently cite a record with nothing to do with the
        belief. Concretely:

        - every cited id is drawn from ``episodes``, and none from outside it;
        - an ``INFERRED`` proposal cites at least **two distinct** episode ids,
          because a generalisation from a single instance is exactly the
          "one unusual interaction hardens into a permanent, wrong preference"
          failure the band exists to bound (ADR-0005 §Context). An ``OBSERVED``
          proposal may rest on one, since it restates what its evidence shows;
        - support is counted over **distinct ids**, never over citations: two
          labels resolving to one episode are one support;
        - a proposal that cannot meet its floor is **not proposed**, and is
          counted in ``discarded_unusable``. It is never repaired by attaching the
          batch wholesale — evidence attached to satisfy a rule is not evidence.

        **Confidence is the producer's, and never the model's.** It is a
        deterministic, pure function of the epistemic step and the number of
        distinct supporting episodes: strictly below 1.0 always (1.0 is the
        standing the user's own word carries, ADR-0072 §3, and
        :class:`~ai_assistant.core.types.Provenance` now enforces it);
        an ``OBSERVED`` belief outranking an ``INFERRED`` one on the same support;
        non-decreasing in the number of supporting episodes, under a ceiling; no
        clock, no randomness, no model-supplied number. The exact values are each
        implementation's. Two properties follow and both matter more than
        calibration: a model-supplied confidence is the model's mood rather than a
        comparable quantity, and because the function is deterministic on its
        inputs, **re-observing the same episodes cannot inflate a belief** — a
        ``REINFORCE`` that takes the maximum finds nothing higher.

        **The bar for proposing at all is durable usefulness, not
        interestingness.** A belief is warranted only when it is *about the user*
        and would change a later answer. Summarising the exchange is the failure
        mode: it turns the belief store into a second transcript, at indefinite
        retention, behind the surface that answers "what do you believe about me".
        This is the half of selective memory a gate cannot enforce, because a
        policy judging one proposal at a time cannot see that all twenty of them
        are a retelling — so it is stated as a producer-side obligation.

        **Output is bounded, and excess is discarded rather than queued.** An
        implementation is constructed with its own maximum; ``proposals`` never
        exceeds it, and usable proposals dropped to meet it are counted in
        ``discarded_over_limit``. A queue would be durable state nothing here
        ratifies, and the episodes remain in the store, so a later pass over the
        same batch can propose what this one dropped.

        **``conflicts`` is left empty.** Conflicts are resolved by the writer, in
        the same call that rules on them, and are not supplied by the caller
        (ADR-0028 §3). A producer that filled them would be re-deriving `memory`'s
        conflict semantics.

        **Failure behaviour.** A model failure **propagates** unwrapped, its
        classification intact: the caller asked for observation and it did not
        happen, and returning "no beliefs" would be indistinguishable from
        "nothing to learn". A **malformed response degrades** instead: entries the
        producer can use are proposed, entries it cannot are discarded and
        counted, and nothing is invented to fill a gap. **No proposals is a normal
        outcome**, not an error (ADR-0022 §4).

        Args:
            episodes: The batch to observe, as a **set**: no id may appear twice,
                and its length may not exceed the maximum the implementation was
                constructed with. Both are refused rather than repaired (below).
                Order carries no meaning, and the batch's members need not share a
                conversation.

        Returns:
            The proposals distilled from the batch, with the two discard counts
            that say what was thrown away getting there. An **empty batch yields
            no proposals and no discards**, and reaches no model.

        Raises:
            ValueError: If ``episodes`` is longer than the implementation's
                configured maximum, or carries the same episode id twice — each
                **refused, never truncated or silently de-duplicated**. Truncating
                would disable half the work while the caller kept reporting health,
                and the episodes the caller believed were observed were never read
                (the posture ADR-0073 §2 set: out of range is a ``ValueError``, not
                a clamp). De-duplicating would hide a caller's selection bug and,
                worse, let one episode supply the two *distinct* supports an
                ``INFERRED`` belief owes. The obligation is on the seam because
                this is a cross-subsystem contract: a stage that bounds its own
                selection is not evidence that the next caller will.
            ModelError: Propagated unwrapped from a model-backed implementation.
        """
        ...


@runtime_checkable
class Reader(Protocol):
    """Reads one source and proposes what it read (ADR-0093, ADR-0095 §1).

    The read-only seam: it opens a source the hub can read — a notes vault synced
    onto the box, the maildir a co-located fetcher writes — and returns one bounded
    :class:`~ai_assistant.core.types.SourceReading` of what that source currently
    says. Named for its product role, as every Protocol here is (``Planner``,
    ``Observer``, ``MemoryPolicy``): the role is *reading a source*.

    **It holds no store handle, no writer, no policy and no engine**, which is the
    scope limit rather than a rule about it. An implementation may not write to any
    store, may not read a belief, and may not decide the fate of anything it
    proposes. The alternative — a producer holding a store and choosing what to
    read — would make the scope of ingestion "a property of the producer's code
    rather than of a ratified seam, and every later reviewer would have to
    re-derive it by reading an implementation. Here it is a type" (ADR-0077 §1,
    taken for its own reason rather than by imitation).

    **Every belief it proposes reaches memory through the gate**, i.e.
    :meth:`MemoryWriter.ingest` and the :class:`MemoryPolicy` behind it. A reader
    inherits no part of ADR-0075's capture exemption: a calendar entry is a third
    party's report, which is the definition of the ``ATTESTED`` band, and a band
    whose whole standing is that someone else said it is the last band that should
    reach the store unmediated (ADR-0093 §1).

    **It is never its own caller.** Selecting when a reader runs, and ingesting
    what it returns, are `orchestration`'s (ADR-0093 §1). Its reading has two
    legitimate consumers at two cadences — the situational context facet at
    assembly time, and ingestion on its schedule — and neither may derive its
    answer from the other's reading (§3).

    **A ``Reader`` is not a spoke** (ADR-0094 §1, ADR-0095 §1). It is an
    in-process object that opens a file, not an attachment that dials the hub
    across a process boundary, and no clause governing spokes binds it.

    Cancelling :meth:`read` is governed by this module's cancellation clause
    (ADR-0060), with one consequence spelled out on the method because it is the
    one place a conforming-looking reader can quietly get it wrong. This module's
    input-observation clause (ADR-0065) is **vacuous** here and is meant to stay
    that way: :meth:`read` takes no arguments, so there is no caller-owned
    container for a result to be torn across.
    """

    @property
    def name(self) -> str:
        """This reader's stable identifier, declared rather than configured.

        It is **Tier 2 / operational** (ADR-0004 §1) and must stay that way, and
        the obligation is stricter here than :attr:`ContextSource.name`'s rather
        than merely inherited, because a reader's identity has a second consumer.
        It is never derived from the source's location or contents — a path,
        filename, address or account identifier may not be used as one — because
        the identity is what lands on the reading, on
        :attr:`~ai_assistant.core.types.Attestation.reported_by` of every belief
        the gate then stores, in every export, and in every log line, in a system
        whose ADR-0004 §5 rule is that logs never contain Tier 1 data. A reader
        that wraps personal data names *itself* (``"calendar"``), never the data it
        holds (``"alice@example.com calendar"``). It is stated as its own clause
        because "used for logging" has been read as licence before (ADR-0055), and
        here it would be read as licence twice over.

        **Stable across calls**, and not a configurable value: a free-text setting
        is precisely the mechanism by which a user would put their email address or
        a path there, and no validator can tell a chosen label from a personal one.
        A declared constant cannot carry personal data at all, which is a property
        rather than a rule (ADR-0093 §7).

        A property rather than a constructor argument, for
        :attr:`ContextSource.name`'s reason: the assembler and the ingestion stage
        both log it, and a seam that cannot be asked its own name forces every
        caller to carry one beside it.
        """
        ...

    async def read(self) -> SourceReading:
        """Read the source once, within this reader's own bound, and report it.

        **It takes no arguments, and that is a decision** (ADR-0093 §10). A reader
        is given its own source (§1) and its bound is its own configuration (§5),
        so a caller able to widen the read is a caller able to defeat the bound —
        which is exactly the property ADR-0077 §1 bought by putting the maximum on
        the producer.

        **What may be proposed.** Records in the ``ATTESTED`` band —
        ``provenance.source`` is
        :attr:`~ai_assistant.core.types.MemorySource.EXTERNAL`, so each carries an
        :class:`~ai_assistant.core.types.Attestation` (ADR-0092 §1) — and **never**
        an ``EpisodicMemory``. An ingested episode has neither a gate it can
        survive nor an exemption it can claim: ADR-0075 §2 declines the capture
        exemption to this producer, and ADR-0075 §4 shows the gate is destructive
        to an episode. Manufacturing one would mean arguing an exemption for a
        record of an event this system did *not* witness (ADR-0093 §4).

        **It never proposes an absence**, cancellation or retraction of anything,
        and an entry missing from a later reading is not evidence that the entry
        was withdrawn. This is the safety rule the whole seam turns on, and it
        follows from the bound rather than from preference: a bounded read, a
        truncated file, a permission error and a genuinely deleted entry are
        **indistinguishable from the reading**, so a producer allowed to propose
        absence would retract the user's beliefs on the strength of a failed read —
        and the failure would look exactly like success (ADR-0093 §4).

        **Each proposal carries a ``rationale`` naming the source, and a
        ``sensitivity`` chosen for what the source holds rather than defaulted.**
        ``MemoryUpdateProposal.sensitivity`` defaults to ``DataTier.PERSONAL``,
        which is correct for a calendar and must not be assumed correct for the
        next source; a producer that defaults its way past that classification is
        the failure ADR-0004 §1's tiering exists to prevent.

        **A reader mints its own id for every record it proposes** and may never
        use the source's key — a ``VEVENT`` ``UID``, a row id, a URL — whether
        directly or namespaced (ADR-0092 §6).

        **Failure is a raise, never a smaller reading.** A read either completes
        within its bound and returns a
        :class:`~ai_assistant.core.types.SourceReading`, or raises; it may not
        return what it managed to gather. A half-parsed calendar is not a smaller
        calendar, and proposing from a partial read would write beliefs whose bound
        is the failure's shape with nothing in the stored record saying so
        (ADR-0093 §8).

        Returns:
            One reading: this reader's identity, the instant the read happened, any
            reading-wide as-of the source itself declared, and the proposals. An
            **empty ``proposals`` tuple is a successful reading** — the source had
            nothing to propose within the bound — and no caller may treat it as a
            failure signal. Returning an empty reading *on failure* is what this
            seam refuses: the scheduled job would report success on every failure
            and a reader whose file was unreadable for a week would look healthy
            for a week, while the facet would present "your calendar is clear" when
            the truth is "we could not read your calendar" (ADR-0093 §8).

        Raises:
            ReaderError: If the read cannot complete **because of its source** —
                missing, unreadable, or malformed — with the underlying failure
                preserved as ``__cause__`` and a payload-free message. An
                implementation may not let a source-level exception, an ``OSError``
                or a parser's own class, cross this seam unwrapped (ADR-0093 §8).
            CancelledError: Re-raised unchanged when the call is cancelled from
                outside. It is **excepted from the wrapping rule above** and is
                never converted into a ``ReaderError``. The carve-out is stated
                because the wording it qualifies invites the mistake — a cancelled
                read has, in plain English, "not completed", and a reader wrapping
                everything it catches would convert it, with the result that the
                facet degrades and the scheduler logs a source fault and re-arms,
                on a shutdown that was working correctly (ADR-0093 §8, ADR-0083 §4).
        """
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

        **``memories`` is what the pipeline assembled for this turn, not one
        relevance cut** (ADR-0074 §5). It carries the conversation's recent turns
        **first**, in order, then the records retrieved as relevant, best first
        *within that group*. The wording is restated rather than read generously:
        a conversation tail is usually the most relevant thing the store holds for
        a continued exchange, but a user who changes the subject mid-conversation
        is handed prior turns that are not relevant to the new goal at all, so
        calling the whole sequence "best first" would be a strain. The signature is
        unchanged and ``Planner`` grows no ``history`` parameter — both groups are
        ``MemoryRecord``s the planner already renders, and a second channel would
        split one prompt input in two for a distinction the planner does not act
        on. The widening is flagged under golden rule 5 rather than smuggled: a
        planner may rely on the grouping being meaningful, and must not rely on the
        sequence being globally ranked.

        Args:
            goal: The objective to plan for.
            context: The situational context assembled for this request.
            memories: The records the pipeline assembled for this turn — the
                conversation's recent turns in order, then records retrieved as
                relevant, best first within that group.

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

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060).
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

        **The returned execution's ``id`` is unique for the life of the audit
        trail** (ADR-0044 §1): an id handed to one execution is never handed to
        another, even after the first is deleted (:meth:`delete_goal`,
        :meth:`clear`) and even across a restart of a persistent store. This is
        normative, not incidental. ADR-0044 §3 recovers a parked confirmation by
        its ``(execution_id, step_id)`` binding, so were an id reused, a stale
        ``CONFIRM`` from a prior incarnation of that id — matching tool and
        parameters — could resolve and run the freshly created execution's
        action. The store owns this guarantee because it mints the id and
        accepts none from the caller, so the composition root cannot enforce it
        (ADR-0044 §1, #280). A store satisfies it with minted entropy in the id:
        a uuid, or — as the in-memory stores do — a per-incarnation random nonce
        combined with a monotonic, never-reset sequence, so that neither a reuse
        *within* one incarnation (the sequence never rewinds) nor one *across* a
        restart (a fresh incarnation never repeats a prior id) can occur. A
        non-persistent store restarts on every process start, so a bare
        process-local counter is **not** enough — it would rewind and re-mint a
        prior id that a persistent audit trail still binds a ``CONFIRM`` to.

        Uniqueness is met to the strength of the minted entropy — a uuid or a
        random nonce — which is the mechanism ADR-0044 §1 designates ("minted
        uuids already satisfy it"). A nonce collision is a cryptographically
        negligible event (~2^-122, not an interleaving a caller can provoke), not
        a reachable state a store must defend against with durable id-history
        checks; a store that instead keys on durable state it reopens (a future
        persistent store) meets the same bar without a nonce.

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
class ToolInvoker(Protocol):
    """Performs an authorisation it is handed, against a definition it holds (ADR-0029 §1).

    The other face of the registry. ``ToolRegistry`` answers questions; this one
    acts, and the split is a capability distinction rather than tidiness:
    handing every holder of a lookup the ability to execute is the shape
    ADR-0017 §8 wants to move away from, and a consumer that only reads is one a
    test can double without stubbing execution.

    **An id is invocable if and only if it is registered.** ``all_tools()`` and
    the set of ids :meth:`invoke` will act on are the same set, always. The
    callable is bound to its definition at registration, inside `tools/`, and
    this Protocol resolves through that same binding — so the canonical
    implementation is **one object implementing both Protocols** over one
    mapping from id to ``(definition, callable)``. Two tables keyed by the same
    id could be rebound independently, which is ADR-0016 §7's named failure:
    "executing an implementation whose risk declaration is not the one the user
    approved".

    That binds an implementation, not a wiring. A composition root injecting
    registry A and invoker B — each internally consistent, each holding an
    *equal* definition under one id — satisfies both Protocols and both
    conformance suites. No Protocol can close that (ADR-0029 §1); **the
    composition root must inject one object as both** (ADR-0029 §8), and the
    residue if it does not is narrow, since every *declaration* mismatch still
    fails closed.

    **This does not consult :class:`ActionPolicy`.** It verifies an
    authorisation it is handed and never obtains one: a seam that ruled and then
    executed would be judge and executioner in one object, and a ``CONFIRM``'s
    human round-trip would have nowhere to happen.

    **No credential crosses this seam, in either direction, ever** (ADR-0029
    §6). A tool that needs one obtains it itself, inside `tools/`.
    """

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4); wrapping it outside would cancel the invoker mid-await
        """Run the authorised ``call``, waiting no longer than ``timeout``.

        **Three checks happen first, in this order, before the callable is
        reached, and the order is part of the rule** (ADR-0029 §2):

        1. the call is **revalidated and detached**, so a mutation landed after
           construction cannot survive into execution;
        2. the definition on that detached copy equals the registry's own
           original — the check that closes ADR-0018 §4's tampered-but-valid
           definition, since the registry is the only holder of an untampered
           one;
        3. ``decision.authorises(request)`` on that same copy, re-evaluated
           rather than trusted from construction.

        Every subsequent check reads the revalidated copy, never the argument.
        Ordering it the other way is not a stylistic preference: a ``__dict__``
        write can leave ``parameters`` holding a value ``FrozenJson`` would never
        have accepted, and ``authorises`` compares a digest that canonicalises
        that mapping to JSON — so running it first raises a raw serialisation
        error out of a method whose contract is that it answers a question,
        after the executor has already committed its ``→ RUNNING`` claim.

        **Failures of the tool come back as data; only seam faults are raised.**
        An exception escaping the tool implementation becomes an ``INTERNAL``
        result, as does a return value :data:`FrozenJsonValue` rejects.
        ``BaseException`` propagates unchanged — a ``CancelledError`` or a
        ``KeyboardInterrupt`` must not be swallowed into a result.

        **The seam owns the deadline, and enforcing it is cooperative.** A caller
        wrapping this in ``asyncio.wait_for`` would cancel the invoker
        mid-await, so it would never reach the code that classifies the outcome.
        What the deadline buys is that the seam stops waiting, not that the tool
        stops working: a tool that suppresses its own cancellation can outlive
        it, and no seam can prevent that (ADR-0029 §4).

        On expiry the outcome is ``FAILED`` when the tool is not
        ``side_effecting`` **or** its ``idempotency`` is ``NATURAL``, and
        ``INDETERMINATE`` otherwise — ADR-0014 §4's case, reached through a
        deadline rather than through a crash. "The tool" there is the
        *registry's* definition, never ``call.request.tool``, which a
        ``__dict__`` write could have flipped to read-only mid-flight.

        ``TIMED_OUT`` means **this** deadline expired, established rather than
        inferred from an exception type: an upstream SDK raising Python's
        ``TimeoutError`` for its own reasons, well inside our budget, is an
        exception like any other and becomes ``INTERNAL``. Likewise a
        ``CancelledError`` the callable invents, with nothing cancelled, is a
        tool that raised and not a cancellation.

        Args:
            call: The authorised call. Its ``idempotency_key`` is passed to the
                tool when the tool's ``idempotency`` is ``KEYED``.
            timeout: How long the seam will wait. Keyword-only and required —
                the contract has no spelling for "forever", because a default
                would be ``core`` choosing a policy and ``None`` would be a
                documented route to an unbounded call.

        Returns:
            The classified outcome. Never ``None``, and never an exception for
            anything the tool did.

        Raises:
            ValueError: If ``timeout`` is not a ``timedelta``, or is not
                strictly positive — checked before the callable is created,
                because the annotation is not the enforcement and because
                ``asyncio.timeout(None)`` is no deadline at all. A zero or
                negative duration is refused rather than treated as an
                instantly-expired deadline: expiry is delivered at an await
                point, so a callable performing a synchronous side effect before
                its first ``await`` would already have acted.
            ToolBindingError: If any of the three checks above fails.
            CancelledError: If the invoking task is cancelled from outside. The
                seam does not convert it to a result — there is no return path
                from a task being torn down — so committing the step by the same
                rule the timeout uses, and then re-raising, is the executor's
                obligation (ADR-0029 §4).
        """
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

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060).
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
        ``parameters_digest``, ``step_id`` **and ``execution_id``** match the
        incoming decision's exactly (the ``execution_id`` conjunct is ADR-0044
        §2a: two executions of one plan parked on the same step produce two
        ``CONFIRM``s identical but for their execution, and without it B's answer
        could name A's confirmation), and it was not decided *after* the
        resolution answering it (equal timestamps are fine — a fast confirmation
        at a coarse clock resolution is real). The authorisation pointer is
        checked here too: a resolving ``ALLOW`` must carry ``authorised_by``
        equal to its ``resolves``, and a resolving ``DENY`` must leave it unset.
        Without that pair, a resolving ``ALLOW`` could name any confirmation it
        liked — or a string naming nothing — while satisfying every other check,
        and the disclosure floor would be satisfiable by fabrication.

        **A concrete binding resolves once** (ADR-0044 §2b). *On top of* the
        per-*confirmation* rule above — which stops the *same* ``CONFIRM`` being
        resolved twice and is unchanged (ADR-0036 §2) — a further rule fires
        **only when the confirmation's ``execution_id`` and ``step_id`` are both
        present**: once *any* ``CONFIRM`` for that ``(execution_id, step_id)``
        binding is resolved, the binding is decided, and no second resolution —
        of that confirmation *or a sibling* under the same binding — may be
        recorded. ADR-0037 §2 accepts several unresolved ``CONFIRM``s under one
        binding (a ``run`` that lost the ``PENDING → AWAITING_APPROVAL`` compare-
        and-swap still leaves its ``CONFIRM`` recorded), and those are the *same
        action* — one step of one execution — so they must share one *fate*:
        without this, a step whose ``CONFIRM`` was answered ``DENY`` could still
        have a sibling orphan answered ``ALLOW`` and execute the very action the
        user refused (the #257 window). When the binding is not concrete, only
        the per-confirmation rule applies, so two independent *direct*
        confirmations (each ``(None, None)``) never become mutually exclusive.

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

    async def pending_confirmation(
        self, *, execution_id: str, step_id: str
    ) -> PermissionDecision | None:
        """The confirmation this binding still awaits, or ``None`` (ADR-0044 §3).

        The recovery query. A restarted process reads a reloaded
        ``AWAITING_APPROVAL`` step, sees it is awaiting an answer, and asks the
        trail — *the store that already holds the confirmation* — for it by the
        ``(execution_id, step_id)`` binding ADR-0044 §1 and §2 established, rather
        than by a decision id it no longer has after the restart. ``resume`` then
        proceeds exactly as it does in-process, including its existing check that
        the returned confirmation's ``tool`` equals the reloaded step's
        ``bound_tool``.

        Keys on whether the *binding* carries a resolution, not on any single
        confirmation's state, and works in two steps **in this order**:

        1. **If any ``CONFIRM`` for ``(execution_id, step_id)`` is already
           resolved, return ``None``.** By §2b the binding is decided and no
           further resolution may be recorded, so the pipeline must not present
           it as answerable — and returning a still-unresolved sibling orphan
           here would hand back exactly the #257 hazard §2b closes.
        2. **Otherwise return the newest unresolved ``CONFIRM``** by the trail's
           own order (``decided_at`` descending, ``id`` ascending), or ``None``
           if the binding carries none. A binding may hold more than one
           unresolved ``CONFIRM`` (ADR-0037 §2's compare-and-swap loser), but
           they are the same action — selection is deterministic and
           single-candidate (ADR-0037 §1) — so any is a correct question to
           re-present and the newest is returned deterministically. This does
           **not** raise on multiple unresolved ``CONFIRM``s: that is a reachable,
           accepted state, not a corrupt one.

        **Query-only and returns a detached snapshot**, like every other
        ``AuditTrail`` read (ADR-0018 §3): it adds no write path and no way to
        mutate the trail, so the append-only and single-resolution guarantees are
        untouched.
        """
        ...

    async def resolution_of(self, *, execution_id: str, step_id: str) -> PermissionDecision | None:
        """The recorded resolution of this binding's confirmation, or None.

        The complement of ``pending_confirmation``. Where that method answers "what
        unresolved CONFIRM does this binding still await?", this answers "what
        resolution has this binding already received?" — the ALLOW or DENY whose
        ``resolves`` names a CONFIRM of the concrete ``(execution_id, step_id)``
        binding (ADR-0044 §2). It exists so a step stranded ``AWAITING_APPROVAL``
        with its ruling durable but its disposition transition uncommitted (#257) can
        be driven to the disposition already decided — idempotently, authoring
        nothing new — rather than re-authored, which the single-resolution rule
        (§2b) refuses.

        Returns None **only for a successful read of a binding that carries no
        resolution** (it is genuinely pending — ``pending_confirmation`` answers it —
        or carries no confirmation at all); None never stands in for a failure to
        read. By §2b a concrete binding carries at most one resolution, so when a
        resolution exists it is unique and this returns it. Query-only and returns a
        detached snapshot, like every other ``AuditTrail`` read (ADR-0018 §3).

        The ALLOW-or-DENY guarantee needs no new invariant: a resolving decision
        (``resolves`` set) whose own ruling is ``CONFIRM`` is already unconstructable
        (``PermissionDecision._a_resolution_is_not_itself_a_question``), so a
        resolving-``CONFIRM`` can never occupy the binding's resolution slot and
        this can never return one.

        Raises:
            AuditError: If the trail cannot be read (a closed or corrupt store, an
                I/O error). This is the same boundary ``pending_confirmation`` draws,
                and it is load-bearing: a read failure returned as None would let
                recovery classify a still-resolved step as trail-unanswerable and
                route it to cancellation, discarding a durable ruling. The cause is
                preserved.
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


@runtime_checkable
class SourceGrants(Protocol):
    """Answers what a source may be read for, and can create nothing (ADR-0097 §3).

    The query half of the grant seam. **Anything that drives a reader holds this
    and only this** — `orchestration`'s ingestion stage for
    :attr:`~ai_assistant.core.types.GrantScope.INGEST`, `context`'s reader adapter
    for :attr:`~ai_assistant.core.types.GrantScope.FACET` — as a **required
    constructor argument with no default**, so a composition that omits the gate
    does not type-check (ADR-0097 §5). The obligation stated in prose and honoured
    by review is the shape ``IngestionStage``'s own docstring already calls "a
    composition-root obligation no type can express"; this one *can* be expressed,
    so it is.

    **The split from :class:`SourceGrantStore` is what makes "only a user act
    creates a grant" a type rather than a promise.** A driver handed the whole
    store is a scheduler job that can mint its own authorisation: the ingestion
    stage runs on ADR-0083 §7's timer, and a ``record`` on the object in its hand
    is a valid ``SourceGrant`` away from authorising itself, with nothing about
    the resulting record looking wrong afterwards. So the capability is removed
    from the type the driver names — the move ADR-0077 §1 made for the same
    reason, and ADR-0093 §1 repeated for the reader.

    **It is a static guarantee and is stated as one.** Structural typing means a
    concrete store satisfies this Protocol, so a composition root may legitimately
    pass one object to both seams; what a driver cannot do is *name* ``record``,
    because ``mypy --strict`` runs over ``src`` and ``tests`` and the attribute is
    not on the annotated type. Overstating it as a runtime capability removal
    would be false.

    **A source grant is not an action authorisation.** It may never be cited as
    :attr:`~ai_assistant.core.types.PermissionRuling.authorised_by`, and no
    :class:`ActionPolicy` implementation may consult one. ADR-0021 §5's disclosure
    floor is neither relaxed nor satisfied by anything here, and its deferred
    standing grants for *actions* stay deferred (ADR-0097 §7).

    Cancelling :meth:`live` is governed by this module's cancellation clause
    (ADR-0060). Its input-observation clause (ADR-0065) is **vacuous** here and is
    meant to stay that way: the arguments are a ``str`` and an enum member, so
    there is no caller-owned container for a result to be torn across.
    """

    async def live(self, *, source: str, use: GrantScope) -> SourceGrant | None:
        """The live grant covering ``source`` for ``use``, or ``None``.

        **Returns the record rather than a boolean**, so a caller can name what
        authorised the read instead of merely knowing that something did
        (ADR-0097 §10).

        **``source`` is matched exactly.** No implementation may strip, case-fold
        or otherwise normalise at lookup: a store that was "helpful" here would
        change what a grant covers, and the grant surface already guarantees the
        admissible set is the set of readers' declared names (ADR-0097 §9).

        **Liveness is derived from the ``revokes`` relation alone.** A grant is
        live when no recorded revocation names it; no implementation may decide
        liveness by comparing ``decided_at`` values, and at most one live grant
        exists per source at any instant, so the answer is unique (ADR-0097 §4).

        **The answer is a detached snapshot**, which matters more here than on any
        other read in this file. This is the *only* member of the narrow seam and
        the one answer ADR-0097 §5's gate rests on, and ``frozen=True`` does not
        close the bypass: a caller granted ``FACET`` alone could mutate ``scope``
        on the returned object through ``__dict__`` to include ``INGEST``, and the
        driver's next check would authorise ingestion the user never granted —
        the gate defeated through its own answer.

        ``None`` means **no live grant covers this**, and never "the store could
        not be read"; an unreadable store raises.

        **What a driver owes around this call**, stated here because the seam is
        what those obligations are written against (ADR-0097 §5a). The guarantee
        available is that every read is *authorised at the instant it starts* —
        not that no byte of a source is read after a revocation is recorded, since
        ADR-0093 §7 puts the whole of a read on a worker nothing can stop. Three
        rules hold what is available, and none of them needs a lock:

        * **No ``await`` between this result and the call to
          :meth:`Reader.read`.** The check and the start of the read are one
          synchronous step, which closes the driver's window — the unbounded one.
        * **Re-check when ``read()`` returns.** A reading whose grant is no longer
          live at that moment is **discarded**: nothing is proposed from it, no
          facet is contributed from it.
        * **Fail closed on an unanswerable check.** A ``live`` that raises is not
          a grant; see :class:`~ai_assistant.core.errors.GrantError`.

        Args:
            source: The reader's declared identity, matched exactly.
            use: The use being gated.

        Returns:
            The live grant covering that source and use as a detached snapshot,
            or ``None`` if none does.

        Raises:
            GrantError: If the store cannot be read. Never returned as ``None``:
                a fault and a withdrawn grant are different facts, and a driver
                that cannot tell them apart is one that proceeds on silence.
        """
        ...


@runtime_checkable
class SourceGrantStore(Protocol):
    """The append-only record of what the user granted and withdrew (ADR-0097 §4).

    The writing half of the grant seam, and the wider of the two. **Nothing but
    the hub's grant operations holds one** — no scheduler job, no pipeline stage,
    no ``context`` source and no reader driver (ADR-0097 §3, §9). It satisfies
    :class:`SourceGrants` structurally, so one implementation serves both seams
    and a composition root may pass one object to each.

    A **Tier 1 local store** by ADR-0004 §7's own words, so ADR-0004 §2's
    residency clause governs it: implementations persist locally only, under
    ``Settings.data_dir`` and owner-only, and none of this may be written to a
    remote service.

    **Append-only, and a revocation is a record rather than a mutation.** No
    record is ever updated or individually deleted; erasure is wholesale only.
    This answers "are granting and revoking audited" by construction rather than
    by adding a log — a store in which the only writes are appends, in which
    revocation is an append, and in which nothing may be edited or selectively
    removed, cannot hold a history that differs from what happened. ADR-0021 §4's
    argument is taken over whole: the user may burn the book, and nobody may tear
    out a page.

    **There is no ``get(id)`` and no ``delete(id)``**, each declined for its own
    reason (ADR-0097 §10). A selective delete is the page torn out of the book. A
    ``get`` has no consumer — the revocation invariant is checked *inside*
    :meth:`record`, and a belief's join runs through ``source`` rather than
    through an id — so it would be surface with no consumer. Both are additive
    later.

    **Nothing mints a grant from what is already configured** (ADR-0097 §8). No
    grant is created from a ``Settings`` value, an existing source path, an
    already-ingested belief, an upgrade, a migration, or a first run; an
    installation that has been reading a source stops reading it until the user
    grants. Backfilling one would be configuration presenting itself as consent,
    performed once and invisibly, which is the single way ADR-0093 §7 says the
    decision must not be made.

    **Revoking is prospective.** It retires no belief, closes no validity window,
    deletes no record and alters no stored record; its whole effect is that
    :meth:`live` stops answering. A revocation is never presented as, and never
    produces, a retraction or an absence claim about what the source reported
    (ADR-0097 §6).

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060). Its input-observation clause (ADR-0065) is **vacuous**, as it is
    for :class:`AuditTrail` and for the same reason: the one caller-owned argument
    is a :class:`~ai_assistant.core.types.SourceGrant`, which is immutable all the
    way down. What a caller *can* still do is write past the frozen model through
    ``__dict__``, which is what :meth:`record`'s detachment obligation closes.
    """

    async def record(self, grant: SourceGrant) -> str:
        """Append ``grant`` to the store and return its id.

        **Write-once**: re-recording an id already present raises rather than
        overwriting, for :meth:`AuditTrail.record`'s reason — a store that upserts
        is one where history can be rewritten by replaying a write.

        **Atomic**: the duplicate-id check, the live-grant check, the revocation
        invariants and the append are one operation, not a read followed by a
        write. Without that the one-live-grant guarantee is a race — two
        concurrent grants for one source each observe none live, each append, and
        the source now has two authorisations where the contract says one.

        **Stores a detached, validated snapshot**, recursively over reachable
        state, and never retains the caller's object. Both halves matter and the
        write-side one is the half that is easy to drop: ``frozen=True`` refuses
        ``grant.scope = …`` and does not refuse ``grant.__dict__["scope"] = …``,
        so a store keeping the caller's object would let a grant be rewritten
        *after* it was appended, through a store whose entire premise is that its
        records are not rewritten (ADR-0018 §4, ADR-0021 §4). Validating matters
        for its own reason: a record corrupted past its own model — a naive
        ``decided_at``, an emptied ``scope`` — would be stored and then make every
        later read incoherent, and the construction invariants would have been
        checked on an object nobody kept.

        **At most one live grant per source.** A grant recorded for a source that
        already has a live one is refused; narrowing or widening is a revocation
        followed by a new grant, and both records are kept (ADR-0097 §2, §4).

        **The revocation invariants**, checked here because this is the only place
        both records are in hand. A record whose ``revokes`` is set is refused
        unless the named grant is present, is itself a granting record rather than
        a revocation, is not already revoked, names the same ``source``, and
        carries the same ``scope`` transcribed verbatim.

        **A revocation is never refused for its timestamp**, including one that
        predates the grant it revokes — the one place this contract departs from
        :meth:`AuditTrail.record`'s shape on purpose. ``decided_at`` is
        caller-supplied and this store reads no clock (ADR-0021 §3's rule, kept
        here), so a host clock corrected backwards would otherwise make every
        truthfully-timestamped revocation refusable until wall-clock time caught
        up — and a large enough correction would make a grant **permanently
        unrevokable**, which is the one property this contract exists to deliver.
        The ordering check protects nothing here: liveness is computed from
        ``revokes`` and nothing in this contract compares two instants. What is
        left is that :meth:`recent` can put a revocation beside or above the grant
        it revokes when the clock moved, which is a display oddity a surface can
        render honestly and never a wrong answer to "is this source granted"
        (ADR-0097 §4).

        Args:
            grant: The record to append — a grant, or the revocation of one.

        Returns:
            The recorded id.

        Raises:
            InvalidGrantError: If the id is already recorded, if the source
                already has a live grant, if the record does not satisfy its own
                model, or if ``revokes`` fails any invariant above.
            GrantError: If the store cannot be written.
        """
        ...

    async def live(self, *, source: str, use: GrantScope) -> SourceGrant | None:
        """The live grant covering ``source`` for ``use``, or ``None``.

        Exactly :meth:`SourceGrants.live`'s semantics — the same member, on the
        wider seam. Matched exactly, liveness derived from the ``revokes``
        relation alone, and the answer is a detached snapshot; ``None`` means no
        live grant covers this and never that the store could not be read.

        Raises:
            GrantError: If the store cannot be read.
        """
        ...

    async def recent(self, *, limit: int = 50) -> list[SourceGrant]:
        """Return the most recent records, newest first.

        Ordered by ``decided_at`` **descending**, ties broken by ``id``
        ascending, for :meth:`AuditTrail.recent`'s reason: "newest first" is
        ambiguous between insertion order and decision time, which disagree
        whenever records are appended out of order, and an ``id`` tie-break makes
        the order total rather than merely mostly determined.

        Bounded because every read of a Tier 1 store in this corpus is (ADR-0021
        §4, ADR-0073 §2), and the row count grows with grant churn rather than
        with the number of sources.

        **Revoked grants are still returned.** Revocation retires nothing, and a
        source that has been revoked keeps its complete grant history on file
        (ADR-0097 §6). Both the grant and the revocation are records here.

        Args:
            limit: Maximum number of records to return; must be strictly
                positive.

        Raises:
            ValueError: If ``limit`` is not strictly positive. Raised rather than
                clamped or passed through, for :meth:`AuditTrail.recent`'s reason
                — a store issuing ``LIMIT ?`` against SQLite turns ``limit=-1``
                into no limit at all.
            GrantError: If the store cannot be read.
        """
        ...

    async def export(self) -> list[SourceGrant]:
        """Return every record, in :meth:`recent`'s order (ADR-0007 §3, ADR-0004 §6).

        The user's export right, on ``AuditTrail.export``'s shape. Revoked grants
        and revocations alike are included: what this store is *for* is saying,
        completely and in order, what the user granted and withdrew for a source.

        Raises:
            GrantError: If the store cannot be read.
        """
        ...

    async def clear(self) -> int:
        """Delete every record, returning the number removed.

        Wholesale erasure only, for :meth:`AuditTrail.clear`'s reason: it destroys
        the history visibly and completely, which is what a data-rights operation
        should look like, where a selective delete would be indistinguishable from
        tampering (ADR-0004 §6, ADR-0021 §4).

        Raises:
            GrantError: If the store cannot be written.
        """
        ...


@runtime_checkable
class ConversationStore(Protocol):
    """The durable index of conversations and the turns under them (ADR-0074).

    A conversation is first-class, server-side state with an identity of its own,
    and this store owns that identity end to end: it **mints** the id (§1), it
    **allocates** each turn's ordinal, and it **derives** each turn's episode id
    from the two. A caller never supplies any of the three.

    A Tier 1 store by ADR-0004 §1's own words ("conversation history"), so §2's
    residency clause governs it: implementations persist **locally only**.

    **This store holds no content.** A turn's content is exactly one
    ``EpisodicMemory`` in the ``MemoryStore``, named here by ``episode_id``. The
    two are separate stores with no transaction between them, and the ordering is
    deliberate: the index entry lands **first** and names the episode before the
    episode exists, so no episode can exist for a conversation without its id
    having been recorded here (§8). That makes this index an **intent log** — an
    enumeration of it names every episode the conversation will ever have,
    including one whose write has not landed yet — and it is why an
    ``episode_id`` that does not resolve is an ordinary state (a gap) rather than
    a fault.

    **What this contract does not own.** Every sequence spanning both stores —
    finishing a user deletion, the retention reclaim, and the user-facing export
    that drops turns whose episodes no longer resolve — belongs to the
    capture/lifecycle stage in `orchestration`, the one layer that legitimately
    holds both handles by injection. A store that reached into memory to answer
    its own precondition would break golden rule 1 (§9).

    **The mutation exclusion, which is this seam's obligation and not a
    caller's.** Per conversation, an :meth:`append`, a :meth:`mark_active`, a
    :meth:`stamp_deleted` and a :meth:`drop_if_eligible` **never interleave**;
    each observes the conversation, decides, and writes as one indivisible step.
    An ``asyncio.Lock`` inside one engine would not discharge this — the engine
    already contemplates "another engine over the same durable stores", so two
    engines hold two locks and serialise nothing — which is why the obligation
    sits here (§8). Each implementation meets it in its own way: an in-memory
    store with a lock, a SQLite-backed one with a transaction, which is also what
    makes it hold across processes.

    **Invariants the store proves rather than asks a caller to keep:**

    * **Ordinals move forward.** Per conversation they are dense from
      :data:`~ai_assistant.core.types.FIRST_TURN_ORDINAL`, unique, and monotonic
      (ADR-0064's ruling applied to a second log). Stated exactly, because the
      overclaim is tempting: two appends land in one order every reader agrees on
      and neither can take the other's position. It does **not** detect that an
      appender planned against a tail that has since moved — that needs an
      expected-tail argument and a conflict error, deferred with ADR-0046 §5's
      compare-and-swap.
    * **A parked binding is unique across the index.** A step parks once, so a
      second turn carrying the same ``(execution_id, step_id)`` is a fault —
      a duplicated capture, or a replay — and :meth:`append` refuses it
      **atomically**: no ordinal is consumed and no row is left behind. Without
      that, resolving a recovered park could attach to whichever row an
      implementation happened to return. Turns that parked nothing are
      unconstrained.
    * **The episode id is derived and reserved.** It is a function of the
      conversation's id and the turn's ordinal — two values this store has already
      proved unique — so two captured episodes cannot collide by construction
      rather than by probability. The form is **structurally recognisable and
      reserved to captured conversation turns**: implementations mint into the
      ``conv:`` namespace and **no other producer may mint an id into it** (§3).
      It is opaque to callers, who only pass it back (to
      :meth:`turn_of_episode`, or as :meth:`episodes_to_purge`'s cursor) and hand
      it to the ``MemoryStore``.

    **A conversation stamped deleted is absent from every read that presents
    it** — :meth:`get`, :meth:`recent`, :meth:`export`, :meth:`turns`, and both
    reverse lookups — while :meth:`episodes_to_purge` still yields the episode
    ids the sweeps must destroy. That distinction is what keeps a tombstone from
    being a readable record of a deleted conversation while the deletion can
    still be carried out (§9).

    **Two reads carve out of that exclusion, and neither presents anything.**
    ADR-0076 adds the second: :meth:`stamped_conversation_ids` enumerates the
    tombstones, which is what makes a crashed deletion finishable at all — §8's
    tombstone was already durable and already named every episode involved, and
    nothing could *find* it. ADR-0074 §9.4's exclusion set is otherwise untouched
    in either direction: a caller that obtains a stamped id learns which ids are
    stamped and can learn nothing else about them.

    **Every read is bounded by default and totally ordered** (ADR-0021 §4,
    ADR-0073 §2): turns by ordinal ascending, conversations by ``last_active_at``
    descending with ``id`` ascending as the tie-break. Paging arguments carry
    ADR-0073 §2's range posture unchanged — out of range is a ``ValueError``, not
    a clamp — inherited rather than restated.

    **Every read returns a detached snapshot.** The four exchanged types are
    frozen pydantic models, so this costs nothing; it is stated so an
    implementation that grows an internal mutable row cannot hand one out.

    Every method raises :class:`~ai_assistant.core.errors.ConversationStoreError`
    for a store fault, and **refuses an id the store does not know rather than
    creating one** (§1) — silently starting a conversation turns a typo or a
    stale id into "my conversation vanished". Where a method already has a
    spelling for absence (a ``None`` return, or the ``bool`` of the two lifecycle
    mutations) that spelling is used and nothing is raised; every other method
    raises.

    **The unknown-id refusal is the narrower
    :class:`~ai_assistant.core.errors.UnknownConversationError`** (ADR-0076 §2),
    a subclass, so §9's sentence above stays true as written and every existing
    ``except ConversationStoreError`` still catches it. A store *fault* raises the
    base class. The distinction exists for the sweep and nothing else: an id that
    is gone by the time a sweep reaches it is a deletion someone else completed,
    and telling that from "the store is broken" is what lets a walk carry on
    instead of aborting.

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060). Input observation (ADR-0065) binds it too and is vacuous in
    practice: every argument this seam takes is immutable — a ``str``, an ``int``,
    a ``datetime``, or a frozen model — so there is no second observation to
    disagree with the first.
    """

    async def start(self) -> Conversation:
        """Mint a conversation id, insert the record, and return it (§1, §2).

        **The store mints; a client never invents an id.** Minting is server-side
        because a client that could name an id could collide with another client's
        or graft its turns onto a conversation it was never part of. The id is
        opaque, random (a UUID4 through the store's injected id factory) and
        device-agnostic: it encodes nothing, because anything encoded in it is a
        fact a future spoke would have to forge in order to resume, and an id that
        sorts by mint time is an ordering consumers start relying on before anyone
        decided it was one.

        **Starting is an insert, never an overwrite.** The record is written only
        if the minted id names nothing; on collision the store re-mints and
        retries, and exhausting a small retry budget raises rather than returning
        a conversation whose id names someone else's. The factory is *injected*,
        so a repeating test double or a future non-random scheme makes a collision
        reachable in a way probability does not answer. A ``start`` that overwrote
        would destroy a conversation; one that returned the existing record would
        graft a stranger's turns onto this client's.

        The returned conversation has ``last_active_at`` set (creation is
        activity) and ``last_turn_at`` unset — no turn has landed yet.

        Raises:
            ConversationStoreError: If the id factory kept colliding until the
                retry budget was exhausted, or the store cannot be written.
        """
        ...

    async def get(self, conversation_id: str) -> Conversation | None:
        """Return the conversation with ``conversation_id``, or ``None``.

        ``None`` when the id names nothing **or** names a conversation stamped
        deleted: a stamped conversation is gone as far as every presenting read is
        concerned (§8). ``conversation_id`` is untrusted input from an adapter and
        is treated as such — it is never rendered back into a message except
        through :func:`~ai_assistant.core.types.describe_untrusted`.

        Raises:
            ConversationStoreError: If the store cannot be read, or a stored row
                is corrupt.
        """
        ...

    async def mark_active(self, conversation_id: str) -> Conversation:
        """Record that a turn has *begun* in this conversation, and return it (§2).

        Activity is "someone was here", and it is recorded **before** the turn's
        work rather than only when the turn is captured. Two things need that. A
        turn against a conversation sitting at its retention horizon would
        otherwise be racing the reclaim that drops it — the user is *using* the
        conversation and nothing in the record would say so until the turn ended.
        And a turn that never completes still says the user was here, which is the
        honest input to "which conversation?".

        Sets ``last_active_at`` from the store's clock and **leaves
        ``last_turn_at`` alone**: an attempted continuation is not a recorded
        turn, and claiming one would be the worse error. It takes the same
        per-conversation exclusion as an append, a stamp and a reclaim.

        Raises:
            UnknownConversationError: If ``conversation_id`` names nothing or
                names a conversation stamped deleted — refused, never created
                (§1).
            ConversationStoreError: If the store cannot be written.
        """
        ...

    async def append(
        self,
        conversation_id: str,
        *,
        occurred_at: datetime,
        parked: ParkedBinding | None = None,
    ) -> ConversationTurn:
        """Record a turn: allocate its ordinal, derive its episode id, return it (§3).

        **One operation, because the caller must not guess any part of it.** The
        ordinal is the store's to allocate, so anything derived from it is the
        store's to derive: a caller that predicted the next ordinal in order to
        build the episode id would re-derive the invariant outside the seam that
        owns it, and two engines guessing at once would build the *same* id for
        what the store then makes two distinct turns — the collision the
        derivation exists to prevent, reintroduced by the caller. So allocate,
        derive and write are one indivisible step, and the returned
        :class:`~ai_assistant.core.types.ConversationTurn` carries the episode id
        the caller must then write into the ``MemoryStore``.

        This is the **intent** half of the two-store capture: when it returns, the
        turn is durably recorded and its episode does not exist yet. Sets the
        conversation's ``last_turn_at`` to ``occurred_at`` — "a turn was
        recorded", which is deliberately recorded-time and not landed-time: the
        episode can be missing from a turn that certainly happened (deleted,
        expired, or never written), and a field meaning "the episode is on disk"
        would be false for exactly those turns.

        Args:
            conversation_id: The conversation to append to.
            occurred_at: When the exchange happened, from the caller's injected
                clock (ADR-0026). Passed rather than read here so the turn and the
                episode recording it carry one instant.
            parked: Where the turn parked for confirmation, if it did. Unique
                across the whole index: a second turn claiming one binding is
                refused **atomically** — no ordinal consumed, nothing left behind.

        Returns:
            The recorded turn, naming its conversation, its ordinal and the
            derived episode id.

        Raises:
            UnknownConversationError: If ``conversation_id`` names nothing, or
                names a conversation stamped deleted — an append to a stamped
                conversation is refused, which is what makes a deletion durable
                against a racing capture (§8).
            ConversationStoreError: If ``parked`` duplicates a binding already
                claimed, or the store cannot be written.
            ValueError: If ``occurred_at`` is not a timezone-aware instant with a
                determinate offset (ADR-0023 §3): a naive value would be silently
                localised to the host's zone.
        """
        ...

    async def turns(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
        before_ordinal: int | None = None,
    ) -> list[ConversationTurn]:
        """Read a conversation's turns, oldest first, most recent page (§5, §9).

        The replay read, and a **complete backwards traversal** rather than only a
        tail: without ``before_ordinal`` it returns the last ``limit`` turns; with
        it, the last ``limit`` turns whose ordinal is **strictly below** it. Walk
        the whole conversation by calling again with ``before_ordinal`` set to the
        lowest ordinal just returned, until a page comes back empty — which
        terminates, and visits every turn exactly once, because ordinals are dense.

        Within a page the order is **ordinal ascending**, so a caller can hand the
        result straight to the planner as the conversation's recent turns in order
        (§5) without re-sorting.

        Args:
            conversation_id: The conversation to read.
            limit: Page size. ``None`` asks for the store's **configured replay
                window** — finite, the same value every caller gets by saying
                nothing, and a configured value rather than a constant because
                this bound sizes a prompt rather than a listing (§9.3). ``0``
                returns an empty page.
            before_ordinal: Exclusive upper bound on the ordinal. ``None`` reads
                the tail.

        Returns:
            The page, ordinal ascending; empty for a conversation with no turns
            below the bound.

        Raises:
            ValueError: If ``limit`` is outside ``[0, 2**63)`` or
                ``before_ordinal`` is outside ``[FIRST_TURN_ORDINAL, 2**63)``.
                Refused rather than clamped, for ADR-0073 §2's reason: a negative
                bound reaches SQLite, which reads ``LIMIT -1`` as *no limit at
                all*, and an over-wide one raises ``OverflowError`` out of the
                driver — so two backends silently disagree.
            UnknownConversationError: If ``conversation_id`` names nothing or
                names a conversation stamped deleted. ``turns`` is an ordinary
                presenting read, so it refuses a tombstone exactly as :meth:`get`
                hides one; the sweeps use :meth:`episodes_to_purge` instead.
            ConversationStoreError: If the store cannot be read.
        """
        ...

    async def stamped_conversation_ids(
        self,
        *,
        limit: int | None = None,
        after_id: str | None = None,
    ) -> list[str]:
        """Page over the ids of conversations stamped deleted but not yet dropped.

        The read ADR-0076 adds, and the one thing §8's deletion protocol was
        missing: the tombstone is durable and names every episode involved, but
        every other read excludes a stamped conversation by design, so a process
        that died between the stamp and the drop left work **no later run could
        rediscover**. The episodes the index named were then never destroyed and
        the index itself outlived its grace indefinitely — the residue §8's grace
        and reclaim exist to reclaim, made permanent by the absence of a way to
        enumerate it.

        **Ids and nothing else.** Not :class:`~ai_assistant.core.types.Conversation`
        records, not the stamp instant, not turn counts — the same shape and the
        same argument :meth:`episodes_to_purge` makes: returning only what the work
        needs removes the exposure instead of labelling it. A record-returning read
        would be a general resurrection of everything §8's stamp exists to hide,
        bought for a caller that needs an id to pass to two methods it already has.

        **The stamp instant is deliberately not returned either.** Handing back
        ``(id, deleted_at)`` so the caller could skip tombstones still inside their
        grace is wrong twice over: :meth:`drop_if_eligible` already re-checks the
        grace under the per-conversation exclusion, so a caller pre-filtering on
        ``deleted_at`` would decide eligibility on a reading taken *outside* that
        exclusion — the hazard §9.4 forbids, one layer up — and the sweep does not
        want the filter anyway, because §8's step 2 destroys a stamped
        conversation's episodes **whether or not** its grace has elapsed. So this
        yields every stamped conversation regardless of grace.

        **The order is ``id`` ascending and the cursor is placed lexically — not
        by looking the row up — and that is a correctness requirement.**
        :meth:`episodes_to_purge` may place its cursor by lookup because §9
        guarantees its rows survive the whole traversal ("nothing is removed until
        the record is dropped"). *This* walk has the opposite property: its rows
        are removed by the very sweep walking them. The ordinary sequence is take a
        batch, destroy each conversation's episodes, :meth:`drop_if_eligible`, then
        ask for the next batch using the last id received — by which time that row
        may be gone. A cursor resolved by lookup would be unplaceable exactly when
        the sweep is working correctly, and ordering by ``deleted_at`` would
        compound it, since a dropped row's stamp instant is unrecoverable. So the
        ordering key must be one the **caller already carries**, and ``id`` is the
        only such value this read returns.

        **Reading removes nothing**, exactly as :meth:`episodes_to_purge` removes
        nothing: a row leaves when :meth:`drop_if_eligible` succeeds and not
        before, so the sweep stays idempotent by re-walking and a *resumed* walk is
        as safe as a restarted one.

        Args:
            limit: Batch size; ``None`` asks for the store's configured batch —
                **100**, the figure the purge walk this is walked beside uses, so
                one sweep has one number to reason about rather than two. It is a
                fixed figure and not a ``Settings`` field: unlike the retention
                horizon it expresses no user policy, and unlike the replay window
                it sizes no prompt, so it is only ever a round-trip-versus-memory
                trade on a walk that always runs to exhaustion. ``0`` returns an
                empty batch.
            after_id: Exclusive cursor naming a **position in the id space**: the
                next batch is every stamped id ordering strictly after that string.
                An id that names no row is therefore a perfectly good cursor and is
                **not** an error — which is the whole point (see above). ``None``
                starts at the beginning.

        Returns:
            The batch, ``id`` ascending. An empty batch means the walk is done, and
            the deletion sweep **must** drain to one: finishing a batch and
            stopping is the failure §9's own multi-batch clause forbids.

        Raises:
            ValueError: If ``limit`` is outside ``[0, 2**63)``. ADR-0073 §2's
                posture, inherited unchanged; ``after_id`` carries no such refusal,
                because there is nothing for the store to fail to place.
            ConversationStoreError: If the store cannot be read.
        """
        ...

    async def episodes_to_purge(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
        after_id: str | None = None,
    ) -> list[str]:
        """Page forwards over a conversation's episode ids — **ids and nothing else**.

        The read the two sweeps take (§9): finishing a user deletion, which
        destroys the episodes the index names, and the retention reclaim, which
        destroys nothing and only asks the ``MemoryStore`` whether any of them
        still resolves. It works on a stamped conversation *and* on a live one,
        because those are respectively what each sweep walks.

        **Ids only, deliberately.** No ordinals, no timestamps, no bindings, no
        ``ConversationTurn``. A `core` Protocol is a cross-subsystem contract, so a
        method exists for *every* injected consumer — naming one ``sweep_turns``
        would document an intent the contract cannot enforce, and any caller
        holding a just-deleted id could still enumerate the whole index for the
        length of the grace. Returning only what the work needs removes the
        exposure instead of labelling it: the coordinator must be handed the ids
        it is about to destroy, and nothing else about a deleted conversation
        leaves the store until the record is dropped.

        **Nothing is removed by reading.** Sweep progress is a position within a
        call sequence, never a mutation of the index — the rows *are* the intent
        log, and a sweep that consumed them would discard the only durable
        reference to an episode whose write had not landed yet, letting the late
        write land unreachable. The rows go when :meth:`drop_if_eligible`
        succeeds, and not before. So the sweep is **idempotent by re-walking**: a
        run that dies part-way is re-run from the beginning, and every delete it
        repeats is a no-op on an id already gone.

        Args:
            conversation_id: The conversation whose episode ids to walk.
            limit: Batch size; ``None`` asks for the store's configured batch.
                ``0`` returns an empty batch.
            after_id: Exclusive cursor — an episode id from the previous batch,
                which the store resolves to a position because the encoding is its
                own. ``None`` starts at the first turn.

        Returns:
            The batch, in ordinal order. An empty batch means the walk is done;
            the deletion and reclaim sweeps **must** drain to one before asking
            for the conditional drop.

        Raises:
            ValueError: If ``limit`` is outside ``[0, 2**63)``, or ``after_id`` is
                not an episode id of this conversation. A cursor the store cannot
                place is refused rather than silently restarting the walk, which
                would make a sweep loop forever over its first batch.
            UnknownConversationError: If ``conversation_id`` names nothing. A
                sweep reaching an id another sweep already finished treats this as
                a **no-op and moves to the next id** (ADR-0076 §2); a store fault
                aborts it.
            ConversationStoreError: If the store cannot be read.
        """
        ...

    async def recent(self, *, limit: int = 50, offset: int = 0) -> list[Conversation]:
        """List conversations by last activity, most recent first (§2).

        The read that lets the hub answer "which conversation?", because a
        stateless client cannot: without it, "continue yesterday's conversation"
        would require the *client* to have kept the id, which is exactly the state
        VISION §Principle 8 forbids an interface to own.

        **Ordered by ``last_active_at`` descending, ties broken by ``id``
        ascending** — some total order must be named or two implementations answer
        the same page differently while each believes it conforms. The sort key is
        activity and **never ``last_turn_at``**: that key is defined only for
        conversations that have turns, and ordering by it would sink a
        conversation the user opened a minute ago below one they abandoned last
        week. Conversations stamped deleted are absent.

        A page is the slice ``[offset : offset + limit]`` of that ordered
        sequence. Offset paging over a mutating store may skip or repeat a row;
        that is accepted rather than closed, exactly as ADR-0073 §2 accepts it —
        a listing a user re-runs is not a transaction.

        Args:
            limit: Page size, bounded by default at 50 — the figure
                ``AuditTrail.recent`` set and ADR-0073 §2 reused, for its argument
                that an unbounded read of a Tier 1 store by default is a shape
                worth not offering. ``0`` returns an empty page.
            offset: How many ordered rows to skip before the page begins.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
            ConversationStoreError: If the store cannot be read.
        """
        ...

    async def turn_of_episode(self, episode_id: str) -> ConversationTurn | None:
        """Return the turn an episode records, or ``None`` (§9).

        The store owes both directions of the membership relation, because §10
        declines to duplicate it onto the record: conversation membership lives in
        this index and not as a ``conversation_id`` field on ``EpisodicMemory``,
        so that an episode belonging to no conversation is the *default* shape
        rather than a permitted exception.

        ``None`` when no turn cites that id **or** when the turn's conversation is
        stamped deleted. The second half matters: a caller holding an episode id
        from before the deletion would otherwise receive exactly the ordinal,
        timestamp and binding metadata a stamped conversation withholds from every
        other read.

        Raises:
            ConversationStoreError: If the store cannot be read.
        """
        ...

    async def turn_of_binding(self, binding: ParkedBinding) -> ConversationTurn | None:
        """Return the turn that parked on ``binding``, or ``None`` (§3).

        This is how a resumption finds its conversation. The resume path cannot be
        *told* which conversation it is in — the adapter relays an opaque token and
        nothing else, and after a restart that token is reconstructed from durable
        state with no live turn behind it — so the association is durable and
        recovered rather than passed: the turn that parked recorded the binding,
        and this resolves it back.

        ``None`` when no turn claims that binding **or** when the turn's
        conversation is stamped deleted. Both are the case ADR-0074 §3 already
        ratifies: nothing is captured for that resumption, and **no conversation
        is invented** for it — recording it under a conversation created for the
        purpose would assert a conversation the user never had.

        A binding is unique across the index (:meth:`append` enforces it), so
        "*the* turn" is a well-defined question rather than a choice between rows.

        Raises:
            ConversationStoreError: If the store cannot be read.
        """
        ...

    async def stamp_deleted(self, conversation_id: str) -> bool:
        """Stamp a conversation deleted — step 1 of §8's deletion protocol.

        The tombstone, and it is the conversation record itself. Stamping is
        durable, hides the conversation from every presenting read, and **refuses
        every later append**, so a capture racing the deletion cannot slip a turn
        in behind it. What the stamp does *not* do is remove anything: the index
        survives, still naming every episode id involved — including one whose
        write has not landed yet — which is what lets the sweep finish the
        deletion after a crash or a racing capture.

        The caller then destroys the episodes :meth:`episodes_to_purge` names and
        asks :meth:`drop_if_eligible` to remove the record. Those steps normally
        run to completion in the deleting call; the tombstone is what makes a
        crash survivable rather than final.

        Returns:
            ``True`` if this call stamped it; ``False`` if it was already stamped
            or the id names nothing. A ``bool`` rather than a raise on absence
            because §8's protocol is explicitly re-runnable — a deletion whose
            sweep is repeated after the record was dropped must be a no-op, not an
            error — and reporting "nothing to stamp" still refuses to create
            anything, which is all §1 asks of a method that does not present a
            conversation.

        Raises:
            ConversationStoreError: If the store cannot be written.
        """
        ...

    async def drop_if_eligible(self, conversation_id: str) -> bool:
        """Remove a conversation record and its index, if it is still eligible (§7, §8).

        Step 3 of the deletion protocol and the last step of the retention
        reclaim, and it **re-checks eligibility while holding the per-conversation
        exclusion**. That re-check is the whole point: eligibility is a claim about
        state an append or an activity mark changes, so deciding "idle, empty" and
        then dropping the record in a separate step is how a reclaim destroys a
        conversation the user has just come back to.

        Eligibility, judged against the store's own clock:

        * **A stamped conversation** is eligible once a bounded **grace period**
          has elapsed since the stamp. The grace widens the sweep's reach; it is
          not a bound and is not offered as one — no elapsed time proves a
          suspended write cannot still commit. What it buys is that the tombstone,
          and with it the only record naming a pending intent, outlives the
          deletion long enough for the next reclaim to catch a capture that
          committed and then died.
        * **An unstamped conversation** is eligible once its ``last_active_at`` is
          past the retention horizon. Eligibility reads *activity*, never
          ``last_turn_at``, so a continuation that is underway protects the
          conversation before its turn lands. Where the horizon is unset —
          retention disabled, "keep the episodes forever" — reclaim is **switched
          off** rather than guessed at: no duration means no horizon to compare
          against, and a conversation should not quietly disappear under a setting
          that asked to keep everything. Deletion is then the only thing that
          removes a conversation.

        The horizon is read at the moment reclaim runs, not stamped at creation, so
        a store moved from a 7-day horizon to a 30-day one keeps an emptied
        conversation's index until day 30 though its episodes left on day 7 — and
        moved the other way, drops it sooner. That is the behaviour a user changing
        the setting would predict, and what lingers is metadata rather than content.

        **The caller owns the other half of the precondition.** Whether a
        conversation still has live turns is a ``MemoryStore`` fact this store
        cannot see and may not ask about (golden rule 1). The coordinator drains
        :meth:`episodes_to_purge` — destroying the episodes for a deletion, merely
        observing them for a reclaim — and only then calls this.

        **What the re-check does and does not promise.** It defeats a reclaim whose
        eligibility was evaluated while the activity mark was still *within* the
        horizon. It does **not** keep a conversation alive for an arbitrarily long
        turn: once the mark itself has aged past the horizon the conversation is
        eligible again, and §7's ratified mid-turn outcome applies — the record is
        dropped, the capture append behind it is refused, and the user gets an
        answer that was not recorded. The two clauses describe different instants
        and neither weakens the other.

        Returns:
            ``True`` if the record and its index rows were removed; ``False`` if
            the conversation is not (or no longer) eligible, or the id names
            nothing. ``False`` on absence is what makes the sweep idempotent: it
            can run any number of times, and a re-run after a successful drop is a
            no-op rather than an error.

        Raises:
            ConversationStoreError: If the store cannot be written.
        """
        ...

    async def export(self) -> ConversationExport:
        """Return this store's own portable snapshot (§9, ADR-0004 §6).

        The conversations and their turn index, as the two frozen types, which the
        caller serialises with ``model_dump(mode="json")`` — ADR-0007 §3's rule
        applied to a second store, so the store does not invent a bespoke format.
        Conversations stamped deleted are **excluded**: they are deleted as far as
        every read is concerned.

        **No liveness filtering, because this store has no way to ask and no
        business asking.** A turn outlives its episode, so this snapshot carries
        rows whose episodes have expired or been destroyed. The user-facing export
        is composed in `orchestration`, which drops those turns — filtering them
        against the ``MemoryStore`` half of *the same export* rather than against a
        live read, so no exported turn can point at content the artifact does not
        carry — and a conversation left with nothing to show is dropped with them.
        Both reads are needed and neither substitutes for the other: the deletion
        sweep must see every row, the user's export must see none of them.

        It carries **no episode content**: episodes are ``MemoryStore`` records and
        that store's export already carries them, so repeating them here would put
        the same Tier 1 text in two exports under two retention rules.

        Ordered as the reads are (§9.3): conversations by ``last_active_at``
        descending with ``id`` ascending, turns by ``conversation_id`` then
        ``ordinal`` ascending.

        Raises:
            ConversationStoreError: If the store cannot be read, or a stored row
                is corrupt.
        """
        ...


@runtime_checkable
class DeferralStore(Protocol):
    """The durable queue of memory questions the user has not answered (ADR-0078 §2).

    An ``ASK_USER`` ruling produces a **question about a candidate belief**, and
    until this store existed nothing retained one: the ruling was reported and the
    proposal went out of scope. This is where a deferred proposal waits.

    **What it holds is a question, not a belief** (§1). ``band_of`` applied to a
    held proposal says only which band its record *would* enter if accepted, never
    what the system holds — so three properties follow, and each is a way the queue
    could otherwise leak into the user model:

    * it is **never returned by retrieval** — it is not in the ``MemoryStore``, so
      ``search`` cannot reach it and no plan or prompt is assembled from it;
    * it is **never listed as a belief** — a pending question appearing in belief
      inspection would claim the system holds something it explicitly declined to
      hold (ADR-0073 §3);
    * it **contributes no confidence and no evidence** to anything. A question is
      not weak evidence for its own answer.

    **A Tier 1 store, and Tier 1 only.** The proposal carries the user's own words,
    so this store inherits every obligation the ``MemoryStore`` carries under
    ADR-0004 and ADR-0007 — the same data directory and file permissions, inclusion
    in ``export``, destructible on request. A ``DataTier.SECRET`` proposal is
    therefore **never held**: ADR-0004 §3 is unconditional that Tier 0 secrets live
    in the OS keyring, "never in the memory database, never in a committed file",
    and a durable queue is a file. :class:`~ai_assistant.core.types.DeferredProposal`
    refuses one, so no conforming store can hold one however it is called.
    Deferral *content* is never logged; a log line names the deferral id.

    **The lifetime is load-bearing rather than tidy.** ``retention`` is a cap on how
    long unresolved personal content sits unanswered — a tighter guarantee than
    accepting the proposal would have given — and it holds for every state but one:
    an ``APPLYING`` row is never swept at any age, because sweeping it can orphan a
    committed memory write. Such a row is instead *shown* until the user disposes of
    it, which is a worse guarantee stated honestly rather than a better one claimed
    falsely.

    **The store produces every record; a caller hands none in.** Every instant on a
    :class:`~ai_assistant.core.types.DeferredProposal` is stamped from this store's
    own injected clock and ``retention`` from the lifetime it was constructed with,
    because each of those instants decides something a caller would otherwise decide
    for itself (§2). And **every state after ``PENDING`` is reached by a transition
    this Protocol owns** — :meth:`claim` and :meth:`resolve` — never by being
    handed in.

    **The lifetime and the queue cap are constructor parameters, validated at
    construction**, the ``_check_tuning`` arrangement ADR-0022 §4a ratified and for
    its reason: a bad value here disables a stage while the system reports health,
    so it is refused when the store is built rather than per call. It also means the
    lifetime is read **once per store**, never per operation, which is the other
    half of the rule that live configuration never reaches back into a question
    already asked.

    **The deadline is half-open, and the boundary instant is fixed by the record
    rather than by each backend.** A question is answerable while
    ``now < expires_at``; **at** ``expires_at`` it is not — ``Validity.live_at``'s
    own convention, adopted for consistency rather than preference, because two
    deadline notions in one memory system that disagree at the instant they name is
    a defect waiting for the first test that lands exactly on it. Every operation
    that consults the deadline uses
    :meth:`~ai_assistant.core.types.DeferredProposal.is_answerable_at` and its two
    siblings rather than spelling the comparison again: :meth:`pending`,
    :meth:`claim`, the cap count, the key's reach, and :meth:`purge`.

    **Volume is governed by three rules** (§7), and none of them designs the
    producer. Questions dedup on
    :attr:`~ai_assistant.core.types.MemoryUpdateProposal.question_key`. The
    answerable queue is bounded by a configured maximum, at which :meth:`defer`
    **refuses the new question rather than evicting an old one** — the producer
    still holds what it proposed and can re-propose, whereas an evicted question is
    gone with nobody left to notice. And both enumerations order **oldest first**,
    by ``deferred_at`` ascending with ``id`` ascending as tie-break, so the question
    whose admission is blocking a newer one is on the first page.

    **No *continuation* of a destroyed row may recreate it.** A continuation is a
    write that mutates a row it has already observed — a :meth:`claim` on a deferral
    it read as ``PENDING``, a :meth:`resolve` on one it holds a claim or a state
    for. Every destructive operation — :meth:`delete`, :meth:`clear`, :meth:`purge`
    — **linearizes against every continuation**, and a continuation landing after
    one finds nothing, does nothing, and reports what it found. Stated over that
    class rather than over one method, and over *continuations* rather than writes in
    general: :meth:`defer` is not a continuation, it **creates**, and this contract
    deliberately permits a new question to reuse the id of a deleted one. Creating
    at a free id and resurrecting a destroyed row are different acts that happen to
    touch the same key, and only the second is forbidden.

    **Every read returns a detached snapshot** of frozen models, and **no read
    republishes a claim token** — :meth:`claim` is the only place one appears.

    Every method raises
    :class:`~ai_assistant.core.errors.DeferralStoreError` for a store fault. Where a
    method has a spelling for absence or refusal — a ``None`` from :meth:`get` and
    :meth:`claim`, the ``bool`` of :meth:`resolve` and :meth:`delete` — that
    spelling is used and nothing is raised. A malformed paging argument is a
    ``ValueError``, ADR-0073 §2's posture inherited rather than restated.

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060). Input observation (ADR-0065) binds it too and is vacuous in
    practice: every argument this seam takes is immutable — a ``str``, an ``int``,
    an enum member, or a frozen model — so there is no second observation to
    disagree with the first.
    """

    async def defer(
        self,
        *,
        deferral_id: str,
        proposal: MemoryUpdateProposal,
        decision: MemoryDecision,
        predecessor_id: str | None = None,
        successor_to_claim: str | None = None,
    ) -> DeferralAdmission:
        """Admit a question, reporting **what happened and which deferral holds it**.

        **The arguments are exactly what the store cannot know and nothing else.**
        The caller brings the question — its id, the proposal, the ruling, and the
        parent link when it has one — and the store brings everything that is its
        own: ``deferred_at`` from its injected clock, ``retention`` from the
        lifetime it was constructed with, ``expires_at`` derived from the two, and
        ``state=PENDING``. It is not handed a ``DeferredProposal``; it **builds**
        one.

        **Key-idempotent.** If a deferral **the key still speaks for** carries the
        same ``question_key``, nothing is inserted and the admission is
        ``SUPPRESSED``, carrying that deferral — the reconciliation ADR-0052 §2
        ratified for parked confirmations, where "a binding already named by an
        entry reuses that entry's handle instead of minting a second". A key speaks
        for a deferral that is answerable, ``APPLYING``, or ``REJECTED`` within its
        retention (see
        :meth:`~ai_assistant.core.types.DeferredProposal.speaks_for_its_key_at`).
        A key whose only match is lapsed-and-unanswered, ``ACCEPTED``, ``STALE`` or
        ``REDEFERRED`` does **not** collide: the question lapsed, was settled, or
        was replaced by the successor it names, and a fresh proposal deserves a
        fresh question. An ``APPLYING`` key blocks until its row is **deleted**, and
        only until then — :meth:`purge` never removes one — because a twin question
        admitted while an apply may still be running would let its later answer
        write the second correction the claim exists to prevent.

        **The deadline of a suppressing question is not refreshed.** Refreshing
        would let a chatty producer keep a question alive indefinitely by
        re-proposing, which is the opposite of a lifetime.

        **An id already present is a hard error, not an overwrite.** ``defer``
        inserts only if the id is absent, where "absent" is *physical presence* in
        ADR-0046 §3's sense — a resolved or lapsed row still blocks the id — and
        otherwise raises
        :class:`~ai_assistant.core.errors.DeferralIdConflictError`, committing
        nothing. Without that a dict-backed store silently overwrites someone
        else's pending question while a SQL one raises, and the two disagree about
        whether a question still exists.

        **A retry of the same question under the same id is not a collision**, and
        it is the one stated exception. If the stored row's ``question_key`` equals
        the incoming one **and still speaks for it**, the id names a question that
        is still open — what a caller retrying an uncertain admission produces — so
        the key-idempotent path runs and the admission is ``SUPPRESSED``. If the key
        no longer speaks, the exception does not apply and the id raises: that
        question is finished, and a fresh question gets a fresh id. **Otherwise the
        id check comes first**, and the precedence is stated because the two rules
        can both fire: a call carrying id ``a`` and key ``K2``, against a store
        holding ``(a, K1)`` and ``(b, K2)``, is simultaneously a key duplicate of
        ``b`` and a physical collision on ``a``. The id collision wins, because it
        is a caller-side minting fault and the suppression path would hide it —
        handing the caller back a different question, under an id it believes it
        just minted.

        **A re-deferral does not consult the cap, and the exemption is held by a
        capability rather than named by an id.** ``successor_to_claim`` is the
        **parent's ``claim_id``**; when it is given the cap is not consulted.
        Naming the parent by its deferral id alone would not have worked:
        :meth:`interrupted` publishes the ids of ``APPLYING`` rows to any caller, so
        an id proves only that *some* answer is in flight, not that this caller is
        the one applying it. The token is minted by :meth:`claim`, returned to that
        caller alone, and on no other read — holding it is holding the claim. And
        because a capability alone still leaves the store unable to tell *which*
        question a successor belongs to, the link is on the record: the successor
        supplies ``predecessor_id``, and the token says the caller may.

        All of it is validated in the same atomic operation as the admission, and
        the first question asked is about the **parent**, not the token:

        * **``predecessor_id`` names no stored deferral.** The parent was destroyed
          by the user mid-apply, so there is no claimed answer to strand and no
          bookkeeping to record. The successor is admitted as an **ordinary
          question** — no cap bypass, no link, no ``successor_id`` stamped — and
          nothing raises. The exemption exists to protect a waiting parent and
          there is none.
        * **``predecessor_id`` names a stored deferral and the token does not match
          that deferral's claim.** This **raises**, changing nothing. The parent is
          alive and waiting; admitting an unlinked successor would leave it with no
          ``successor_id`` to name and its ``resolve(REDEFERRED)`` would fail
          forever.

        The remaining conditions are faults too and raise: that deferral is no
        longer ``APPLYING``, or it already carries a ``successor_id``. The two
        arguments must also agree on presence — a ``predecessor_id`` without a
        token, or a token without one, is a malformed call.

        On success the store stamps the parent's ``successor_id`` in the same
        commit, which is what makes the last condition enforceable and gives
        :meth:`resolve`'s ``REDEFERRED`` transition durable state to check rather
        than the caller's word. **Dedup still applies to a successor, and a
        suppressed one still links**: the successor's key differs from its parent's
        by construction, but not necessarily from some *other* pending question, and
        when the admission is ``SUPPRESSED`` the parent is still stamped — with the
        **existing** question's id. Without that the parent has no successor to
        name and a legitimately claimed answer strands ``APPLYING`` forever. So the
        pair is symmetric only when the successor was newly admitted; on the
        suppressed path the parent names the existing question and that question
        does not name back, because it has its own origin and rewriting its
        ``predecessor_id`` would falsify where it came from.

        One successor per claim, one claim per question, and every other question
        admitted under the cap — so the answerable queue can exceed its configured
        maximum only by the number of answers currently in flight, and it returns
        under it as each resolves.

        **Admission is one atomic operation**: the key lookup, the answerable-count
        check and the insert commit or fail together. Left non-atomic, two
        concurrent producers each see room at capacity-minus-one and the cap is
        exceeded, or two same-key calls each see no match and the queue holds the
        same question twice. A background producer is precisely a concurrent
        producer, so this is a live condition rather than a theoretical one.

        Args:
            deferral_id: The id the caller minted for this question. Caller-minted
                as a ``MemoryRecord``'s is, with retry-on-collision at the minting
                site.
            proposal: The deferred proposal, whose ``conflicts`` must be the ids the
                policy actually ruled against (§3, §4) — the frozen set this
                question is asked about, and the exact scope an answer to it will
                authorise.
            decision: The ``ASK_USER`` ruling that deferred it.
            predecessor_id: The question this one succeeds, on the re-deferral path;
                ``None`` for an ordinary admission.
            successor_to_claim: The parent's ``claim_id``, which authorises the link
                and the cap bypass; ``None`` for an ordinary admission.

        Returns:
            An admission whose ``outcome`` says which of the three things happened
            and whose ``deferral`` is the question it is about (``None`` only when
            the queue refused).

        Raises:
            DeferralIdConflictError: If ``deferral_id`` names a stored row carrying
                a different question, or one whose key no longer speaks for it.
                Nothing was committed; re-mint and retry.
            DeferralStoreError: If ``predecessor_id`` names a live deferral the
                token does not claim, one that is not ``APPLYING``, or one that
                already names a successor; if the two exemption arguments disagree
                about being present; or if the store cannot be written. Nothing is
                committed in any of those cases.
            ValueError: If ``proposal`` is a ``DataTier.SECRET`` proposal or
                ``decision`` is not an ``ASK_USER`` ruling — the record type refuses
                both, and the store is left unchanged.
        """
        ...

    async def get(self, deferral_id: str) -> DeferredProposal | None:
        """Return the deferral with ``deferral_id``, or ``None``.

        Whatever its state, including one whose deadline has passed: expiry is
        read-time-relative and never stamped, so a lapsed question is still a
        stored row a surface can explain. ``deferral_id`` is untrusted input from an
        adapter and is treated as such — never rendered back into a message except
        through :func:`~ai_assistant.core.types.describe_untrusted`.

        Raises:
            DeferralStoreError: If the store cannot be read, or a stored row is
                corrupt.
        """
        ...

    async def claim(self, deferral_id: str) -> DeferralClaim | None:
        """Take a question from ``PENDING`` to ``APPLYING``, minting its token (§2, §9).

        A compare-and-set atomic with its own read, refusing a deferral past
        ``expires_at``. It stamps ``claimed_at`` and returns the claimed deferral
        **and** the token; ``None`` when the deferral is absent, lapsed, or not
        ``PENDING``.

        **Nothing may apply an answer without holding a claim.** This is what makes
        an answer apply at most once under concurrency: without it two concurrent
        answers both read a ``PENDING`` deferral, both ingest, and **both write**,
        with only one winning the terminal compare-and-set while the loser's memory
        mutation stands — a duplicate correction with no crash anywhere, produced by
        ordinary concurrent use. It is ADR-0044 §2's "a binding resolves once"
        moved one step earlier so that it covers the *apply*, not only the
        bookkeeping.

        **The token is unpredictable, unique among live claims, and minted from an
        injected source.** "Fresh" is not enough: a store handing out ``"1"``,
        ``"2"``, ``"3"`` mints a fresh token every time and satisfies the word,
        while :meth:`interrupted` publishes every ``APPLYING`` deferral's id — so a
        caller reads an id, guesses the token, and resolves someone else's claim or
        spends its cap exemption. A capability anyone can guess is a parameter with
        extra steps. So the token is drawn from a **cryptographically unpredictable**
        source of at least 128 bits, and the source is **defaulted, not merely
        injectable**: injection exists for determinism in tests, but injection alone
        would let a composition root wire a counter and satisfy every word above, so
        a conforming store defaults to a ``secrets``-backed factory and a caller has
        to go out of its way to replace it.

        Uniqueness is guaranteed among **live** claims and is otherwise a property of
        the draw, stated at that width deliberately. A token already held by a live
        claim is detected and re-drawn, bounded, raising on exhaustion having changed
        nothing. Uniqueness across the store's whole history is **not** promised:
        closing that would need a durable ledger of every token ever issued,
        surviving ``delete`` and ``clear`` — storage of exactly what the user asked
        to destroy — to defend against a source repeating a 128-bit draw. A source
        that repeats is a fault to fix, not a state to reconcile.

        **There is no ``release``, and its absence is a decision.** A claim is never
        returned to ``PENDING`` — not on a timeout, not on request. An operation
        that re-opened a claim would have to be callable by something that is *not*
        the claim holder, since the holder of a crashed claim is gone; and a caller
        who can re-open a claim can re-open a **live** one, letting a third party
        apply the same answer while the first apply is still in flight. A process
        that dies between ``claim`` and ``resolve`` therefore leaves the deferral
        ``APPLYING`` forever: it is absent from :meth:`pending`, unclaimable, never
        swept, and reachable through :meth:`interrupted` so the user can dispose of
        it. The design trades recovery for the guarantee, and the cost is paid where
        it can be seen.

        Args:
            deferral_id: The question to claim.

        Returns:
            The claim — the now-``APPLYING`` deferral and its token — or ``None``
            when the question is not open.

        Raises:
            DeferralStoreError: If the bounded token re-mint was exhausted (nothing
                changed, and the deferral is left ``PENDING``), or the store cannot
                be written.
        """
        ...

    async def pending(self, *, limit: int = 50, offset: int = 0) -> list[DeferredProposal]:
        """Enumerate the **answerable** questions, oldest first (§2, §7).

        ``state is PENDING`` **and** before ``expires_at``, judged against this
        store's own clock reading, read-time-relatively as every ``MemoryStore``
        read is (ADR-0045 §6). A row whose ``expires_at`` is ``None`` never lapses
        out of it.

        **One page is judged against one clock reading** — ADR-0073 §8's clause,
        and it matters here for the same reason: a row dropped mid-scan shifts
        every subsequent offset.

        Bounded by default, for ADR-0073 §8's reason — it "keeps an unbounded read
        of a Tier 1 store from being what a caller gets by saying nothing". Total
        order: ``deferred_at`` ascending, ``id`` ascending as tie-break. **Oldest
        first**, because the head of the queue is the question whose admission is
        blocking a newer one, so a full cap is legible from the first page rather
        than discoverable only by paging to the end. It is an *admission* order, not
        an urgency order, and the two diverge only when the configured lifetime
        changed between admissions — ``retention`` is stamped per question and never
        recomputed — which this read follows rather than claiming an urgency it does
        not deliver.

        Args:
            limit: Maximum rows to return. An ``int`` in ``[0, 2**63)``.
            offset: How many matching rows to skip. An ``int`` in ``[0, 2**63)``.

        Returns:
            Up to ``limit`` answerable questions, in the total order above.

        Raises:
            ValueError: If either argument is not an ``int`` — a ``bool`` is not a
                count, and a ``float`` satisfies the range while no two backends
                agree what it means — or is outside ``[0, 2**63)``. Refused at both
                ends and before the first ``await``: ``limit=-1`` is SQLite's
                spelling for *no limit*, so an unvalidated negative turns the
                bounded read of a Tier 1 queue into an unbounded one.
            DeferralStoreError: If the store cannot be read, or a stored row is
                corrupt.
        """
        ...

    async def interrupted(self, *, limit: int = 50, offset: int = 0) -> list[DeferredProposal]:
        """Enumerate the ``APPLYING`` questions, in :meth:`pending`'s order (§2, §9).

        An answer was begun and its outcome is not recorded. This read exists
        because the surface must *show* such a question and disposing of it is the
        user's first recovery step, and after a restart nothing holds an id to
        :meth:`get` by — without it the stranded question is unreachable, which is
        the vanishing this contract is about, one state along.

        A **second enumeration** rather than a state filter on :meth:`pending`,
        following ADR-0076's precedent for exactly this shape and ADR-0073 §9's
        reason for declining an ``include_retired`` axis: two different questions
        behind one flag is one argument doing two jobs, and the answerable queue is
        the read every caller wants by default. The two reads are **disjoint** — a
        store that returned an interrupted question among the answerable ones would
        offer the user a claim that cannot be taken.

        Same bounded default, same total order, same argument range as
        :meth:`pending`.

        Args:
            limit: Maximum rows to return. An ``int`` in ``[0, 2**63)``.
            offset: How many matching rows to skip. An ``int`` in ``[0, 2**63)``.

        Returns:
            Up to ``limit`` interrupted questions, oldest first.

        Raises:
            ValueError: If either argument is not an ``int`` or is out of range,
                exactly as :meth:`pending` refuses them.
            DeferralStoreError: If the store cannot be read, or a stored row is
                corrupt.
        """
        ...

    async def resolve(
        self,
        deferral_id: str,
        *,
        claim_id: str | None,
        state: DeferralState,
        record_id: str | None = None,
        successor_id: str | None = None,
    ) -> bool:
        """Record a question's outcome: the terminal compare-and-set (§2, §9).

        Atomic with its own read. It succeeds from ``APPLYING`` to **any** terminal
        state — ``ACCEPTED``, ``REJECTED``, ``STALE`` or ``REDEFERRED`` — **only
        when ``claim_id`` matches the token :meth:`claim` minted for it**, and from
        ``PENDING`` to ``REJECTED`` with ``claim_id=None``, since an unclaimed
        rejection writes nothing and so needs no claim.

        **Every terminal state must be reachable from ``APPLYING``, including
        ``REJECTED``.** A ``MemoryWriter`` takes an injected policy, and a
        conforming policy that is not the default one may rule ``REJECT`` on a
        confirmed proposal, so an accept whose ingest returns ``REJECT`` would
        otherwise have no legal transition and strand forever. The mapping from
        ingest outcome to terminal state is therefore **total**:
        ``ACCEPT``/``STORE_TEMPORARY``/``REINFORCE``/``SUPERSEDE`` → ``ACCEPTED``
        with the record id; ``ASK_USER`` → ``REDEFERRED`` with the successor's;
        ``REJECT`` → ``REJECTED``; and a coordinator's own pre-ingest window check
        → ``STALE`` without an ingest at all.

        **``answered_at`` is stamped by the store, not passed in** — for a reason
        stronger than symmetry with :meth:`claim`: that instant is a **retention
        anchor**, so a caller that supplied it would decide how long its own
        rejection suppresses the next honest proposal. Resolve ``REJECTED`` with an
        instant in 1970 and the record is swept at once, so the user is re-asked
        something they just declined; supply one far in the future and the same key
        stays suppressed long past the retention it was admitted under. A validator
        requiring only that the stamp *exists* catches neither, so the parameter is
        absent rather than checked.

        **Each terminal state carries its own required payload and forbids the
        other's**, in the shape
        :meth:`~ai_assistant.core.types.MemoryDecision._outcome_fields_are_consistent`
        already enforces for a ruling: ``ACCEPTED`` requires ``record_id`` and no
        successor; ``REDEFERRED`` requires ``successor_id`` and no record id;
        ``REJECTED`` and ``STALE`` require neither and permit neither. Without it a
        valid claim can resolve ``ACCEPTED`` naming nothing that was written — a
        terminal state that lies, reached through the one call whose whole job is to
        record what happened. A malformed combination is **refused, not silently
        normalised**. The two ids are separate parameters rather than one overloaded
        slot so that each of those cases is expressible rather than ambiguous, and a
        ``REDEFERRED`` resolution's ``successor_id`` must equal the one the store
        stamped when it admitted that successor, so the transition is checked
        against durable state rather than the caller's word.

        **An unclaimed rejection is subject to the deadline too.** ``PENDING →
        REJECTED`` carries the same ``now < expires_at`` predicate every other
        operation does and fails past it. Without that, a client that displayed the
        question a moment before it lapsed could reject it a moment after, and the
        lapsed row would become a retained ``REJECTED`` key that suppresses a fresh
        identical proposal — the one outcome a lapsed key must not have. A question
        that is no longer answerable is no longer *rejectable*; the two are the same
        statement.

        **A resolve that linearizes after a destruction writes nothing at all.**
        "Atomic with its own read" bounds this call against another ``resolve`` and
        says nothing about a :meth:`delete`, a :meth:`clear` or a :meth:`purge`
        landing between that read and its write — so a read-then-write backend would
        put its stale terminal row back, **resurrecting Tier 1 content the user
        destroyed** through the call whose only job is bookkeeping. It returns
        ``False`` instead, and the row stays gone, absent from :meth:`get` and
        :meth:`export`, whichever way the race fell. A caller reading that ``False``
        after a disposal learns one thing — the question is gone — and reports the
        outcome it already holds from the ingest rather than inferring one from the
        failure.

        Args:
            deferral_id: The question to resolve.
            claim_id: The token :meth:`claim` returned, or ``None`` for the one
                unclaimed transition (``PENDING`` → ``REJECTED``).
            state: The terminal state to record.
            record_id: The record an accepted apply left live. Required for
                ``ACCEPTED``, forbidden otherwise.
            successor_id: The question a re-deferred answer raised. Required for
                ``REDEFERRED`` and must equal the id the store already stamped;
                forbidden otherwise.

        Returns:
            ``True`` if this call recorded the outcome. ``False`` from any other
            state, on a mismatched or absent ``claim_id``, on a second attempt, and
            when the row was destroyed before this call's write landed. The
            ``claim_id`` is what keeps the bookkeeping bound to the apply that
            actually ran: without it a caller who never applied anything could
            stamp a question ``ACCEPTED``.

            ``False`` too where the record's own stamped ``successor_id`` disagrees
            with the transition: a ``REDEFERRED`` resolution naming some *other*
            question, and any non-``REDEFERRED`` state on a row that already raised
            one. Both are compare-and-set preconditions judged against durable
            state, so they answer in the same shape as a stale ``claim_id`` rather
            than raising — the malformed-*payload* refusals, which need no state to
            detect, are the ``ValueError``s below. A row that raised a successor
            therefore has exactly one outcome available to it, and recording any
            other would store a record the type forbids.

        Raises:
            ValueError: If ``state`` is not a terminal state, or the payload is
                malformed for it. Nothing is written.
            DeferralStoreError: If the store cannot be written.
        """
        ...

    async def delete(self, deferral_id: str) -> bool:
        """Destroy one question and everything it holds — **unconditionally** (§2).

        ADR-0007's data right, shaped as ``MemoryStore.delete``. **No state refuses
        it**, including ``APPLYING``: ADR-0073 §9 declines a *band*-conditional
        delete because "it makes a data right conditional on a classification the
        system assigned", and a state-conditional one is the same mistake with an
        internal label instead of a band. ADR-0073 §6 already rules the consequence
        — "the record is *destroyed*, unconditionally… losing the history is what
        they asked for".

        That an ``APPLYING`` row is deletable while :meth:`purge` may never touch
        one is not an inconsistency; **the difference is who is acting, and it is
        the whole distinction.** If an in-flight ingest then commits, its
        :meth:`resolve` finds nothing and returns ``False`` — which after a delete
        means *the question was disposed of while the answer was being applied*, a
        true statement the caller reports, and after a sweep would mean *the system
        quietly destroyed the only record that an answer was ever given*. The first
        is a consequence the user chose; the second is one nobody chose.

        Deleting destroys the ``question_key`` with the row, which is what makes the
        two-step recovery reachable: while a stranded row lives it holds its key, so
        a re-proposal of the same correction would collide with it and be handed
        back an id nothing can claim.

        Args:
            deferral_id: The question to destroy.

        Returns:
            ``True`` if a row was removed, ``False`` if the id named nothing.

        Raises:
            DeferralStoreError: If the store cannot be written.
        """
        ...

    async def clear(self) -> int:
        """Destroy every question, whatever its state (§2, ADR-0007).

        The sweep half of the data right, shaped as ``MemoryStore.clear`` and
        unconditional in the same way :meth:`delete` is — an implementation that
        cleared the answerable queue and left the rest would pass every other
        clause here, so "unconditional" is stated rather than implied.

        Returns:
            How many rows were destroyed.

        Raises:
            DeferralStoreError: If the store cannot be written.
        """
        ...

    async def export(self) -> list[DeferredProposal]:
        """Return every stored question, for the user's own data export (ADR-0004 §6).

        A plain list of the frozen record type, which the caller serialises with
        ``model_dump(mode="json")`` — matching ``MemoryStore.export`` and
        ``AuditTrail.export`` rather than minting a bespoke export type, because
        this store has one collection and ``PlanExport``'s reason for existing does
        not apply.

        Every state is included, lapsed and terminal alike: the content is the
        user's and the export is theirs. **No claim token appears**, in this or any
        other read — a capability is not the user's data, and an export carrying one
        would hand the ability to resolve a live claim to anything that reads the
        file.

        Raises:
            DeferralStoreError: If the store cannot be read, or a stored row is
                corrupt.
        """
        ...

    async def purge(self) -> int:
        """Sweep the rows whose own stamped deadline has passed (§2, §6).

        Shaped as ``MemoryStore.purge_expired``, with **two named anchors and the
        same "a deadline is reached at the instant it names" convention** the
        answerability comparison uses from the other side
        (:meth:`~ai_assistant.core.types.DeferredProposal.is_purgeable_at`). A row
        is purgeable when it is **terminal**, its ``retention`` is not ``None``, and
        ``answered_at + retention <= now``; or when it is **``PENDING``**, its
        ``expires_at`` is not ``None``, and ``expires_at <= now``.

        **Both read the record, never the live setting.** ``retention`` is the
        duration stamped at admission, so a configuration change never reaches back
        and shortens or extends a question already asked. And ``retention is None``
        is a complete answer rather than an undefined expression: **a row admitted
        under "ask me forever" is never purged**, which is the same choice its
        ``PENDING`` sibling makes and the same one the user made.

        **The two anchors are different on purpose, and the asymmetry is the
        decision.** A terminal row is retained for one further lifetime because
        something depends on it surviving — a ``REJECTED`` key is read to refuse
        re-asking, and that is the whole retention argument. A lapsed row has no
        such dependant: its key stopped speaking the instant it lapsed, so nothing
        reads it and nothing is served by keeping it. Giving it the same grace by
        symmetry would hold an unanswered Tier 1 proposal for **twice** the
        configured lifetime, while that lifetime is what §1 calls the cap on how
        long unresolved sensitive content sits. The ``PENDING`` clause is therefore
        what makes that cap true, and it is the one a purge naturally omits: an
        unanswered question never transitions, so a sweep keyed on terminal states
        alone keeps the user's own words on disk forever.

        **It never removes an ``APPLYING`` row, at any age.** That row is the only
        durable record that an answer was begun; destroying it while its ingest is
        still running — a slow embed, a stalled store — would let the memory write
        commit against a question that no longer exists, so the bookkeeping fails
        and the fact that an answer was given survives nowhere. A sweep may not make
        that decision; a user may, and does, through :meth:`delete`. Correctness
        does not depend on ``purge`` running, but the exposure cap does, for every
        state except that one.

        Returns:
            How many rows were removed.

        Raises:
            DeferralStoreError: If the store cannot be written.
        """
        ...


@runtime_checkable
class AssistantEngine(Protocol):
    """The assistant's whole request surface, as a client sees it (ADR-0085 §1).

    **Provided by `orchestration`, consumed by `interfaces`.** It is the first
    *provided* contract in a file of consumed ones, and the direction is stated
    here rather than left to be inferred from the method names: everywhere else in
    this module a subsystem implements a contract the engine calls, and here the
    engine implements a contract an adapter calls. ADR-0084 §5 ruled the asymmetry
    "an observation about the file's current contents, not a rule anyone ratified",
    and this file is the floor path the review process already treats as contract
    surface.

    **Why it is a Protocol at all.** ADR-0042 §1 declined one because there was one
    engine and one class of consumer, and named its own revisit trigger: a second
    implementation. ADR-0084 §5 finds the trigger fired — a client satisfying this
    surface over a local transport *is* that second implementation — so the whole
    surface promotes rather than the part today's caller happens to use. A Protocol
    trimmed to the CLI would be re-widened by the first adapter that reads beliefs.

    **Lifecycle is deliberately absent.** ``start()`` and ``aclose()`` stay on the
    concrete class the composition root builds (ADR-0084 §5, ADR-0083 §8): a client
    that could call ``aclose()`` could shut down the hub from a spoke. Two
    consequences follow and are easy to miss —

    * a ``RuntimeError`` from a shutting-down engine is **not** a declared failure
      of any method here. It is a property of *that* object's lifecycle, not of
      this contract, and a client never observes it: shutdown stops the listener
      and unlinks the socket before draining, so a spoke arriving during shutdown
      reads a closed door. An implementation without a lifecycle does not have to
      invent one to conform;
    * the concrete engine keeps both methods and stays substitutable, because a
      Protocol constrains what an implementation must have, not what it may not.

    **One argument convention, applied to all nineteen methods** (ADR-0085 §2, and
    ADR-0102 §2 for the four grant operations): the
    *subject* of a call — the one thing it acts on — is positional, and every other
    argument is keyword-only. A keyword-only modifier can be joined by another
    without changing any call site; a second optional positional cannot. On the
    wire every argument is named regardless (ADR-0084 §3), which is precisely why
    the Python surface should agree with it.

    Five clauses bind every implementation and no type expresses them, so the
    shared conformance suite is what holds implementations to them:

    1. **The page-size default is normative.** An implementation called without
       ``limit`` behaves as though :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`
       had been passed. A default written in a ``Protocol`` signature binds nobody,
       and a client defaulting to 100 against an engine defaulting to 50 would
       return a different page for the same call (ADR-0085 §3a).
    2. **Every identifier argument undergoes
       :data:`~ai_assistant.core.types.Identifier` validation before any I/O** —
       which both *rejects* a blank value with ``ValueError`` and *strips*
       surrounding whitespace from the value the implementation then uses. Stating
       the normalisation is the load-bearing half: optional normalisation on an
       identity argument would make the answer to ``belief(" rec-1 ")`` a property
       of which implementation you are holding (ADR-0085 §3c).
    3. **Both of ``beliefs``' filters are materialised before the first ``await``.**
       A caller that mutates the sequence it passed cannot change which page it
       gets (ADR-0085 §3d). ``None`` and empty stay different: ``None`` selects
       every band or kind, an empty sequence selects nothing, and the two filters
       compose by conjunction.
    4. **A malformed page argument or a blank identifier is refused locally,
       before any I/O**, so both implementations refuse the same values without a
       round trip and neither is silently more permissive (ADR-0085 §9).
    5. **The size limit is part of this contract, not of a transport, and every
       implementation enforces it** — on arguments before dispatch, on results
       before return, and on errors before they are sent. The limit is the
       deployment's maximum frame size less a 512-byte envelope reserve, applied to
       the **whole serialised payload** and measured as the byte length of
       ADR-0087's canonical UTF-8 JSON encoding of it. It is enforced in **both**
       directions so a client is never silently less capable than the engine it
       stands in for: an oversized ``Belief.evidence`` coming back is refused
       exactly as an oversized utterance going in (ADR-0084 §4, ADR-0085 §8).

       **On a mutating call the result is measured after the work has committed**,
       because no measurement of a result can precede producing it — and a wire
       client meets the same situation one frame further out. The effect stands and
       is readable through the surface's own reads; ADR-0085 §8e names this residual
       and declines to design around it, since the unbounded factor is #473's and
       ADR-0084 §11 makes that the client lane's prerequisite. Tracked in #570.

    :class:`~ai_assistant.core.errors.OversizedValueError` is therefore declared by
    **every** method below and is not repeated in nineteen ``Raises`` blocks. No
    method is provably inside the bound: :data:`~ai_assistant.core.types.Identifier`
    carries no maximum length, so even ``forget`` can be handed an oversized
    argument, and every enumerating method's result grows with ``limit``. ADR-0102
    §10 applies the same bound to the four grant operations without exempting any of
    them, and names the one place it decides whether a source can be granted at all:
    :meth:`grantable_sources` carries §6's disclosure, so a configured location too
    long for the frame takes the whole enumeration down and leaves every source
    ungrantable through a conforming client.

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060), and how each observes its arguments by the input-observation clause
    (ADR-0065), of which clause 3 above is the surface's own restatement.
    """

    # --- the two turn calls (ADR-0042 §3) ---------------------------------

    async def converse(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, threaded to the seam that owns the deadline (ADR-0029 §4)
        conversation_id: Identifier | None = None,
    ) -> TurnOutcome:
        """Run one turn: plan against the utterance, and drive the step it produces.

        **The disposition is the gate's verdict; the named step's ``status`` and
        ``failure`` are the outcome.** A client that renders success from
        ``outcome.step.disposition`` alone is wrong —
        :attr:`~ai_assistant.core.types.Disposition.EXECUTED` says the permission
        gate let the call through and the executor committed something, not that
        the something succeeded. :attr:`~ai_assistant.core.types.StepOutcome.step_id`
        addresses the step's own record::

            next(s for s in outcome.step.state.steps if s.step_id == outcome.step.step_id)

        Args:
            utterance: What the user said. The only bare-text argument on this
                surface, and it must have a UTF-8 encoding like every other string
                the surface carries.
            timeout: The budget for the whole turn.
            conversation_id: The conversation to continue, or ``None`` to run in a
                fresh one. The id the outcome carries back is what a client keeps.

        Returns:
            What the turn produced, including the conversation it ran under and
            whether retrieval or capture degraded.

        Raises:
            ValueError: If ``conversation_id`` is present and blank, or the
                utterance has no UTF-8 encoding — refused locally, before any I/O.
            UnknownConversationError: If ``conversation_id`` names no conversation
                this engine can operate on.
            PlanningError: If the request could not be turned into an executable
                plan, or a step transition was refused.
            ContextError: If the situational context could not be assembled.
            AuditError: If a permission decision could not be recorded.
            ToolBindingError: If the selected tool could not be bound.
        """
        ...

    async def resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, threaded to the seam that owns the deadline (ADR-0029 §4)
    ) -> TurnOutcome:
        """Answer a parked confirmation and continue the step it belongs to.

        The disposition rule stated on :meth:`converse` binds here identically: a
        resumed step's own ``status`` and ``failure`` are its outcome, and the
        disposition is only the gate's verdict on it.

        ``turn`` is ``None`` on a resume driven from a **recovered** park: a
        confirmation reconstructed from durable state after a restart has no live
        turn, and fabricating one would misrepresent what the turn saw. The step is
        what a resume is for and is always present.

        Args:
            token: The opaque continuation the engine minted. Relayed, never
                interpreted or re-derived by the adapter (ADR-0042 §4).
            approved: The human's answer. The adapter collects it; it never authors
                the permission outcome itself.
            timeout: The budget for continuing the step.

        Returns:
            What the resumption produced.

        Raises:
            UnknownContinuationError: If the token names no parked step this engine
                can resume — a restart, or eviction under the outstanding-park cap.
                **Never a denial**: nobody ruled on this action (ADR-0084 §7).
            PermissionDeniedError: If the human refused, or the recorded ruling
                does not authorise the call.
            AuditError: If the resolution could not be recorded.
            ToolBindingError: If the selected tool could not be bound.
        """
        ...

    # --- the two accumulation legs ----------------------------------------

    async def learn(self, event: FeedbackEvent) -> LearnOutcome:
        """Fold one piece of feedback into memory, and say what it did.

        The *dictated* half of accumulation, where :meth:`observe` is the passive
        one. Every proposal the feedback produces goes through the ratified write
        path, and the summary carries one entry per proposal — including, for a
        deferral, where the question it raised went.

        Args:
            event: What the user said about what the assistant got right or wrong.

        Returns:
            One summary per proposal, in the order they were applied. Empty when
            the feedback proposed no update at all.

        Raises:
            MemoryStoreError: If reading or writing memory failed.
        """
        ...

    async def observe(self, *, conversation_id: Identifier | None = None) -> ObservationReport:
        """Read a bounded batch of a conversation's episodes and propose what they justify.

        The *passive* half of accumulation (ADR-0077 §8). It is deliberately
        explicit: nothing triggers it but a caller. Each proposal goes through the
        same write path :meth:`learn` uses, so the observer neither widens its own
        batch nor rules on its own output.

        ``conversation_id`` is a **selector rather than a subject**, which is why it
        is keyword-only like :meth:`converse`'s: "this conversation, or the most
        recently active" (ADR-0085 §2).

        Args:
            conversation_id: The conversation to read, or ``None`` to select the
                most recently active one.

        Returns:
            What the pass did — the proposals with their rulings, the counts kept
            apart, the route that read the episodes, and which conversation it was.

        Raises:
            ValueError: If ``conversation_id`` is present and blank.
            UnknownConversationError: If it names no conversation this engine can
                operate on.
            ConversationStoreError: If reading the conversation index failed.
            MemoryStoreError: If reading or writing memory failed.
            ModelError: If the observing call failed. Surfaced unwrapped and with
                its classification intact (ADR-0077 §3).
        """
        ...

    # --- the inspection surface (ADR-0073 §7, ADR-0077 §6) ----------------

    async def beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[BeliefSummary, ...]:
        """List what the assistant believes, newest revision first.

        **Returns summaries, not beliefs**, and the type is the enforcement
        (ADR-0085 §4a). ADR-0077 §6 gives the listing *existence* — the count, the
        lost count and the adjusted confidence — and gives resolved citations to
        :meth:`belief` alone. A :class:`~ai_assistant.core.types.BeliefSummary` has
        nowhere to put a citation's content, so a conforming listing cannot ship
        the corpus on every page.

        The listing still *resolves* existence per citation, because the adjusted
        confidence is a function of how many citations resolved.

        Args:
            bands: Which standings to include, or ``None`` for every band. An empty
                sequence selects nothing, which is a different answer from ``None``.
            kinds: Which typed memories to include, or ``None`` for every kind. The
                two filters compose by conjunction.
            limit: How many to return. Defaults to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`, and an
                implementation called without it behaves as though it had been
                passed.
            offset: How many to skip.

        Returns:
            One summary per live belief, in the store's stated order.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
                Refused rather than clamped, locally and before any I/O
                (ADR-0073 §2). An adapter that lets a user supply either should
                refuse an out-of-range value at its own parse boundary.
            MemoryStoreError: If reading memory failed.
        """
        ...

    async def belief(self, record_id: Identifier) -> Belief | None:
        """Read one belief with its citations resolved, or ``None`` if there is none.

        The other half of ADR-0077 §6's split: this is the view that renders the
        surviving citations as readable evidence and the lost ones as tombstones.

        Args:
            record_id: The belief's id, as the listing showed it.

        Returns:
            The belief, or ``None`` where the store holds no live record by that
            id.

        Raises:
            ValueError: If ``record_id`` is blank.
            MemoryStoreError: If reading memory failed.
        """
        ...

    async def forget(self, record_id: Identifier) -> bool:
        """Destroy one belief, permanently.

        Args:
            record_id: The belief's id.

        Returns:
            Whether a record was destroyed. ``False`` where the id named nothing
            live, which is not an error: the user's intent — "let this not be held"
            — is already satisfied.

        Raises:
            ValueError: If ``record_id`` is blank.
            MemoryStoreError: If reading or writing memory failed.
        """
        ...

    # --- the deferred-question surface (ADR-0078 §8) ----------------------

    async def questions(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[Question, ...]:
        """List the questions waiting for an answer.

        Args:
            limit: How many to return; defaults to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`.
            offset: How many to skip.

        Returns:
            The answerable questions, each with what accepting would retire.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
            DeferralStoreError: If reading the queue failed.
            MemoryStoreError: If resolving what a question would retire failed.
        """
        ...

    async def interrupted_questions(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[Question, ...]:
        """List the questions whose answer was begun and whose outcome is unrecorded.

        Not "failed" and not "retryable": the system does **not** know whether the
        memory write landed, which is the actual epistemic situation (ADR-0078 §9),
        and this enumeration is what lets a user dispose of one deliberately.

        Args:
            limit: How many to return; defaults to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`.
            offset: How many to skip.

        Returns:
            The interrupted questions.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
            DeferralStoreError: If reading the queue failed.
            MemoryStoreError: If resolving what a question would retire failed.
        """
        ...

    async def answer(self, question_id: Identifier, *, accept: bool) -> AnswerOutcome:
        """Answer one deferred question, and say what the answer did.

        An accepted answer is **re-submitted through the ratified write path**, so
        conflict detection, the policy, the atomic applier and the full-set
        retirement rule all run unchanged — which is what lets an answer raise a
        further question (``REDEFERRED``) rather than silently widening its own
        scope (ADR-0078 §5).

        Args:
            question_id: The question to answer.
            accept: Whether to have the assistant believe it.

        Returns:
            Which of the five outcomes happened, and what it left behind.

        Raises:
            ValueError: If ``question_id`` is blank.
            MemoryStoreError: If reading or writing memory failed.
            UnresolvedEvidenceError: If the re-submitted proposal cites a record
                the store no longer holds.
            DeferralStoreError: If reading or updating the queue failed.
        """
        ...

    async def forget_question(self, question_id: Identifier) -> bool:
        """Destroy one deferred question, so its subject can be asked again.

        Args:
            question_id: The question to destroy.

        Returns:
            Whether a question was destroyed. ``False`` where the id named nothing.

        Raises:
            ValueError: If ``question_id`` is blank.
            DeferralStoreError: If reading or updating the queue failed.
        """
        ...

    # --- the conversation surface (ADR-0074 §2, §8) -----------------------

    async def recent_conversations(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[ConversationSummary, ...]:
        """List conversations, most recently active first.

        The sort key is activity and never "has a turn landed": ordering by the
        latter would sink a conversation the user opened a minute ago below one
        they abandoned last week (ADR-0074 §2).

        Args:
            limit: How many to return; defaults to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`.
            offset: How many to skip.

        Returns:
            One summary per live conversation.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
            ConversationStoreError: If reading the conversation index failed.
        """
        ...

    async def conversation(self, conversation_id: Identifier) -> ConversationDigest | None:
        """Show what destroying one conversation would destroy, or ``None`` if absent.

        ADR-0073 §5's show-then-confirm at the unit the user thinks in: the count
        and the span, rather than a transcript nobody can read at a prompt
        (ADR-0074 §8).

        Args:
            conversation_id: The conversation to describe.

        Returns:
            The digest, or ``None`` where the id names no live conversation.

        Raises:
            ValueError: If ``conversation_id`` is blank.
            ConversationStoreError: If reading the conversation index failed.
        """
        ...

    async def forget_conversation(self, conversation_id: Identifier) -> bool:
        """Destroy one conversation and the episodes its turns index.

        Args:
            conversation_id: The conversation to destroy.

        Returns:
            Whether a conversation was destroyed. ``False`` where the id named
            nothing live.

        Raises:
            ValueError: If ``conversation_id`` is blank.
            ConversationStoreError: If reading or updating the conversation index
                failed.
            MemoryStoreError: If destroying the indexed episodes failed.
        """
        ...

    # --- durable recovery (ADR-0052 §1) -----------------------------------

    async def pending_confirmations(self) -> tuple[Confirmation, ...]:
        """Reconstruct every parked confirmation that is still answerable.

        The recovery path ADR-0052 §1 ratifies: after a restart the in-memory
        handle table is empty, so the answerable parks are rebuilt from durable
        state and each is handed back with a **freshly minted** token. Enumerating
        and re-minting is what makes a park survive a restart without the token
        itself having to be durable.

        Returns:
            One confirmation per answerable park, each carrying a token this engine
            will resolve. A tuple rather than a list, like every other enumeration
            on this surface: a caller that mutated a returned page has changed
            nothing about the engine's state and may believe otherwise
            (ADR-0085 §3b).

        Raises:
            PlanningError: If the durable execution state could not be read or
                reconciled.
            AuditError: If a recorded decision could not be read.
        """
        ...

    # --- the grant surface (ADR-0097 §9, ADR-0102 §1) ---------------------

    async def grantable_sources(self) -> tuple[GrantableSource, ...]:
        """List the sources the user may grant, with what is currently true of each.

        ADR-0097 §9's third clause — "The surface also answers what the grantable
        sources are" — so a client "offers a choice among declared identities rather
        than a free-text field". The set is the declared names of the readers this
        engine holds, which is what makes the admissible set a set of declared
        constants rather than free text (ADR-0093 §7).

        **This response is the only carrier of a source's configured location**
        (ADR-0102 §6, discharging ADR-0097 §9a). It is computed per call, never
        written to a :class:`~ai_assistant.core.types.SourceGrant`, never returned
        by :meth:`recent_grants`, never written to a log record and never persisted.
        Reading the user's own configuration back to the user over ADR-0084 §1's
        ``0600`` socket discloses it to nobody, which is §9a's own argument.

        **A source whose configured location exists and has no UTF-8 encoding is
        omitted**, and enumeration is not refused for it (ADR-0102 §6). Linux
        pathnames are bytes and Python surfaces an undecodable one through
        ``surrogateescape``, so ``str(path)`` can hold a lone surrogate that
        :data:`~ai_assistant.core.types.EncodableText` refuses and ADR-0087's
        encoder cannot express. Degrading ``location`` to ``None`` instead was the
        first draft and is refused: it would offer a source no conforming client may
        grant, and a client that ignored :meth:`grant`'s disclosure obligation would
        mint precisely the uninformed grant ADR-0097 §9a exists to prevent. A reader
        whose *declared name* is inadmissible (:meth:`grant`) is omitted for the
        same reason; the operator log line names the reader and carries no path.

        **A client renders each ``location`` and takes an explicit act from the user
        before it calls :meth:`grant`, and a client that cannot show the user a
        location does not call it** (ADR-0102 §6). Nothing on the wire distinguishes
        a client that rendered it from one that did not, so this is stated as the
        unenforceable obligation it is (ADR-0098 §5): what an engine enforces is
        that the value is *available* and that it settles nowhere. "Does not send
        ``grant``" rather than "prompts on a terminal" is deliberate — the property
        is that the user saw what they are authorising, and a spoke with no display
        refuses rather than granting unseen (ADR-0097 §8).

        Returns:
            One entry per grantable source this engine holds, deduplicated by
            declared identity so several instances of one source contribute one
            entry (ADR-0102 §7). Empty where nothing is configured, which is not an
            error: configuration says *where* and the grant says *whether*, and
            neither may be mistaken for the other.

        Raises:
            GrantError: If the grant store could not be read — every entry's
                ``live`` is a read of it.
        """
        ...

    async def grant(
        self, source: NonBlankEncodableText, *, scope: Sequence[GrantScope]
    ) -> SourceGrant:
        """Record the user's grant of one source for the uses ``scope`` names.

        The record is minted **here**: its id comes from an injected factory and its
        ``decided_at`` from an injected clock, and no caller supplies either, nor
        ``revokes`` (ADR-0102 §5). A client that sent a whole
        :class:`~ai_assistant.core.types.SourceGrant` would backdate a user act in a
        store whose entire value is that it says what actually happened, mint an id
        into a write-once store, and be able to point ``revokes`` at a record it
        never read.

        **``source`` is** :data:`~ai_assistant.core.types.NonBlankEncodableText`
        **and not** :data:`~ai_assistant.core.types.Identifier`, which is the type an
        author reaches for first and is wrong here (ADR-0102 §2). ``Identifier``
        strips, and ``wire/surface.py`` validates each argument against this
        annotation before dispatch — so a wire call ``grant(" calendar ")`` would
        arrive as ``"calendar"`` and be *matched* against a held reader named
        ``"calendar"``, where ADR-0097 §10 requires that "a source differing from a
        held reader's ``name`` only by surrounding whitespace is refused rather than
        matched". The normalisation would happen one layer below the comparison,
        and the in-process engine — handed the string unvalidated — would refuse the
        same call the wire accepted. **No implementation may strip, case-fold or
        otherwise normalise ``source`` at any point before it is compared.**

        **Admission, after validation and never instead of it** (ADR-0102 §4). A
        validated ``source`` is admitted **only** when it equals, exactly, the
        declared ``name`` of a :class:`Reader` this engine holds **and** that name
        validates as :data:`~ai_assistant.core.types.Identifier` and equals its own
        ``str.strip()``. Any other validated value raises
        :class:`~ai_assistant.core.errors.UngrantableSourceError`, no ``SourceGrant``
        is constructed from it, and the value reaches no store and no log.

        **No liveness pre-check, and the store is the arbiter** (ADR-0102 §5). An
        ``await`` between a check and a write is an interleaving point (ADR-0021 §4)
        and two clients can be connected at once, so a pre-check would narrow the
        window without closing it while inviting a reader to believe it had.
        ADR-0097 §10 makes ``record`` atomic over the duplicate check, the
        live-grant check, the revocation invariants and the append, so a lost race
        is a typed refusal and never a second live grant.

        Args:
            source: The reader's declared identity, compared exactly.
            scope: The uses this grant authorises. Non-empty and without duplicates;
                order is normalised to declaration order by the record's own
                validator (ADR-0097 §2, §10).

        Returns:
            The recorded grant, as it was appended.

        Raises:
            ValueError: If ``source`` is blank or has no UTF-8 encoding, or if
                ``scope`` is empty or names a use twice. A caller programming error
                rather than a condition of the system, refused **locally and before
                any I/O**, so both implementations refuse the same values without a
                round trip (ADR-0085 §9).
            UngrantableSourceError: If the validated ``source`` is not admissible.
                The refusal carries no filesystem path; it names the reader where a
                *held* reader's declared name or configured location is the
                inadmissible thing, and names no value at all where no held reader
                declares the value (ADR-0102 §4).
            GrantError: If the grant store could not be read or written.
            InvalidGrantError: If the store refused the record — most reachably
                because the source already has a live grant. Propagated rather than
                retried or converted into a success: the client's remedy is to
                re-read :meth:`grantable_sources`, which will show the source
                already granted.
        """
        ...

    async def revoke(self, source: NonBlankEncodableText) -> SourceGrant | None:
        """Withdraw the live grant on one source, or report that there was none.

        **Revocation is the operation this surface protects, and it applies no
        admission check** (ADR-0102 §4). Beyond the argument validation above, a
        revocation is refused for no property of the source's name — and in
        particular is *not* refused because no reader currently declares it.
        ADR-0097 §9 records that "a grant whose reader later disappears is not a
        defect", so an operator who unsets a source's path leaves a stored grant
        naming a source nothing drives; if this method applied the admission check
        that user could no longer withdraw their own live grant, and a configuration
        edit would have made a grant **permanently unrevokable**. That is precisely
        the failure ADR-0097 §4 refused when it declined an ordering invariant on
        ``decided_at``. Revocation is the user's whole remedy under ADR-0097 §6 and
        nothing may stand between them and it.

        **Nothing leaks through the opening this leaves.** A ``revoke`` naming a
        value no reader declares finds no live grant, constructs nothing, records
        nothing and returns ``None`` — so the free-text route into the store that
        ADR-0097 §1 and §9 exist to close stays closed on this path too, not by
        refusing the value but by there being nothing for it to reach.

        **The live grant is resolved by querying every member of**
        :class:`~ai_assistant.core.types.GrantScope` **and taking the first answer**
        (ADR-0102 §5), which is total because a grant's scope is non-empty. Querying
        one member is the wrong version that passes every test that exists: an
        implementation checking only ``FACET`` would leave an ``INGEST``-only grant
        unrevokable while reporting success by returning ``None``. The revoking
        record transcribes the revoked grant's ``source`` and ``scope`` verbatim.

        **It returns when the revoking record is durably appended, and it does not
        wait for, cancel, or report a read already in flight** (ADR-0102 §9). No
        client may present a revocation as having stopped one: ADR-0097 §5a
        guarantees that every read is authorised at the instant it *starts*, and a
        read already running completes on a worker nothing can stop (ADR-0093 §7).
        What is true is that no further read starts and nothing an in-flight read
        produces is used. The ``None`` return is not silence about this either — it
        means the source had no live grant when the operation ran, and says nothing
        about reads.

        Args:
            source: The source to withdraw, compared exactly and normalised by
                nothing (see :meth:`grant`).

        Returns:
            The revoking record that was appended, or ``None`` where no live grant
            covered the source.

        Raises:
            ValueError: If ``source`` is blank or has no UTF-8 encoding. Refused
                locally, before any I/O.
            GrantError: If the grant store could not be read or written.
            InvalidGrantError: If the store refused the revoking record — reachably,
                where the record it built lost a race to another revocation. A
                refusal rather than a silent success is the right answer: the client
                re-reads :meth:`grantable_sources` and sees the source is no longer
                granted, which is what it wanted.
        """
        ...

    async def recent_grants(self, *, limit: int = DEFAULT_PAGE_SIZE) -> tuple[SourceGrant, ...]:
        """List what the user granted and withdrew, newest first.

        The surface that discharges ADR-0097 §4's audit property: the record *is*
        the audit record, so nothing here is written to an
        :class:`AuditTrail` and no :class:`PermissionDecision` is synthesised for a
        grant (ADR-0102 §11). Revoked grants and revocations alike are returned —
        revocation retires nothing, and a source that has been revoked keeps its
        complete history on file (ADR-0097 §6).

        **A record this returns is never presented as live or as withdrawn on its
        own** (ADR-0102 §3). Liveness is :attr:`GrantableSource.live`'s, computed
        hub-side from the ``revokes`` relation; ADR-0097 §4 permits a revocation
        timestamped *before* the grant it revokes, and this page is ordered by
        ``decided_at``, so a clock correction can put a revoking record outside a
        page that contains the grant it revokes.

        **``limit`` and no ``offset``**, which departs from the four other paging
        signatures deliberately (ADR-0102 §10):
        :meth:`SourceGrantStore.recent` has no offset, so an ``offset`` here would
        be either a store change ADR-0102 does not own or an engine-side
        over-fetch-and-slice — a paging surface that lies about its cost, and whose
        cost grows with the page it is skipping. It is additive the day the store
        gains one (ADR-0008 §1).

        Args:
            limit: How many records to return. Defaults to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`, and an
                implementation called without it behaves as though it had been
                passed.

        Returns:
            The most recent records, newest first, ties broken by ``id`` ascending.

        Raises:
            ValueError: If ``limit`` is not strictly positive, or is outside
                ``[0, 2**63)``. **Refused locally and before any I/O, in every
                implementation** (ADR-0102 §10). Stated because the two contracts
                disagree about zero: ADR-0085 §9 admits a page argument in
                ``[0, 2**63)`` and ``SourceGrantStore.recent`` requires a strictly
                positive ``limit``, so ``recent_grants(limit=0)`` is well-formed
                under the surface rule and refused by the store — and §9's own
                clause is that neither implementation may be silently more
                permissive.
            TypeError: If ``limit`` is not an integer, or is a ``bool``. The type is
                checked before the range for :meth:`beliefs`' reason.
            GrantError: If the grant store could not be read.
        """
        ...
