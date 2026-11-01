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
under the second.

Each subsystem declared in the architecture map adds its Protocol here as it is
designed, so this file grows to hold every seam that crosses a subsystem
boundary. ``tests/core/test_protocol_triad.py`` is what keeps that growth
honest: it enumerates the Protocols declared here and fails the gate for any one
missing its conformance suite, its canonical fake, or the binding that runs the
two together.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ai_assistant.core.types import DEFAULT_PAGE_SIZE, StoryDecision

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from datetime import datetime, timedelta

    from pydantic import BaseModel

    from ai_assistant.core.types import (
        ActionRequest,
        ActivationEffect,
        ActivationEffectClaim,
        ActivationStop,
        ApprovalCard,
        ApprovalChoice,
        ApprovalDue,
        ApprovalOutcomePush,
        ApprovalPanel,
        ApprovalPanelTap,
        ApprovalRequest,
        ApprovalRequestState,
        ApprovalRequestStep,
        ApprovalRequestWrite,
        ApprovalTap,
        BatchHandle,
        BatchItemOutcome,
        BatchRequest,
        BatchStatus,
        Belief,
        BeliefBand,
        BeliefSummary,
        BoundEgressCall,
        CarriedProvenance,
        ChannelEpisode,
        ChannelEpisodeId,
        ChannelEpisodePage,
        ChannelIdentity,
        ChannelInput,
        ChannelResult,
        ChatChanges,
        ChatDevice,
        ChatStreamChunk,
        ChatStreamEnd,
        ConflictRelation,
        ConnectedAccount,
        ConnectionAct,
        Conversation,
        ConversationDigest,
        ConversationExport,
        ConversationSummary,
        DeviceChanges,
        DeviceConversation,
        DiagnosticEntry,
        DurableIdentifier,
        EgressBinding,
        Embedding,
        EncodableText,
        EpisodeChunk,
        EpisodePage,
        EvaluationTrace,
        FetchOutcome,
        ForecastOutcome,
        FrozenJsonMapping,
        GrantableSource,
        GrantScope,
        HeldNotification,
        Identifier,
        Memory,
        MemoryChange,
        MemoryDecision,
        MemoryIngestResult,
        MemoryKind,
        MemoryLabelChange,
        MemoryLabelResult,
        MemoryRecord,
        MemorySearchResult,
        MemoryUpdateProposal,
        MemoryWrite,
        Message,
        MessageReceipt,
        NewMessage,
        NonBlankEncodableText,
        NotificationCandidate,
        NotificationDelivery,
        NotificationDisposition,
        NotificationEnqueue,
        NotificationPreferences,
        ObservationRecord,
        OccurrencePush,
        OccurrenceState,
        OfferedTool,
        PendingCandidate,
        PermissionDecision,
        PermissionRuling,
        PersonModel,
        PersonModelAct,
        PersonModelEdit,
        PersonModelExport,
        PersonModelList,
        PersonModelView,
        PersonModelWrite,
        Placement,
        PlanExport,
        PlanningExchange,
        ProcessingStatus,
        ProfileChange,
        ProfileField,
        ProposedSuggestion,
        QuestionPart,
        RecordChunk,
        RecordedInvocation,
        RoundResponse,
        RulePush,
        ScheduledDue,
        ScheduledTask,
        ScheduledTaskCancel,
        ScheduledTaskWrite,
        SearchOutcome,
        SecretName,
        SecretValue,
        SourceGrant,
        SourceListing,
        SourceListingEntry,
        SourceReading,
        SourceReadRecord,
        SpendAdmissionHandle,
        SpendTotal,
        SpokenAudio,
        SpokenAudioFormat,
        SpokenReply,
        StoryActor,
        StoryFlagName,
        StoryHeader,
        StoryLogPage,
        StoryMember,
        StoryNoteAuthor,
        StoryNoteId,
        StoryNoteList,
        StoryNoteOutcome,
        StoryOutcome,
        StoryPage,
        StoryStanding,
        StorySummary,
        StorySummaryDraft,
        StorySummaryOutcome,
        StorySummaryState,
        StorySummaryVersionList,
        StorySummaryView,
        StoryView,
        StoryViewPage,
        StructuredReply,
        TaskSpawn,
        TelegramButton,
        TelegramCallRecord,
        TelegramIntake,
        TelegramIntakeExport,
        TelegramOutcome,
        TelegramPollClaim,
        TelegramPollOutcome,
        TelegramSendOutcome,
        TicketClaim,
        ToolCall,
        ToolCost,
        ToolDefinition,
        ToolFailureKind,
        ToolInvocation,
        ToolOutcome,
        ToolResult,
        TraceChunk,
        TracePosition,
        TrackRecordEntry,
        TranscriptMessage,
        TranscriptPage,
        TransportEndpoint,
        UserMessage,
        UtcInstant,
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
class StructuredCompleter(Protocol):
    """A completion whose reply is asked for, and read, as a shape (ADR-0354 §2).

    A **sibling** of :class:`ModelProvider`, not a widening of it, on the ground
    ADR-0143 §1 and ADR-0307 §10 established: a member on a structural,
    ``@runtime_checkable`` Protocol would silently unsatisfy every existing
    implementation at once. Nothing is added to ``ModelProvider`` or
    :class:`ToolCallingCompleter`, this Protocol inherits from neither, and an object
    may implement it with either or both (§2:1).

    A **shape** is a pydantic model class its consumer defines (§3:1). The schema sent
    for it, its version and the rule its reply is read by are
    :mod:`ai_assistant.core.reply_shapes`'s, so every implementation, the canonical
    fake and the regression suite agree on all three (§3:5). Nothing outside
    ``models/`` names pydantic-ai or a provider SDK to make or read a structured call
    (§2:6).

    How :meth:`complete_structured` observes the conversation it is handed is governed
    by this module's input-observation clause (ADR-0065, §2:4).
    """

    async def complete_structured[T: BaseModel](
        self,
        messages: Sequence[Message],
        shape: type[T],
        *,
        model: str | None = None,
    ) -> StructuredReply[T]:
        """Ask for the next assistant reply as ``shape``, and read it as ``shape``.

        ``messages`` is held to :meth:`ModelProvider.complete`'s precondition (ADR-0066
        §1), read as that docstring states it, and carries no ``Role.TOOL`` turn.
        ``shape`` is a pydantic model class whose schema can be closed: every object
        in it names its properties, none gives its further keys a schema of their
        own, and no position in it admits any JSON value (§2:3).

        **Every response that comes back is returned** (§2:5), as the shape's value or
        as a returned failure (§5:2): ``refused`` where the provider declined,
        ``cut`` where the response stopped at its output ceiling, ``empty`` where the
        reply holds nothing but whitespace once its fence is removed, and ``invalid``
        where it does not validate as the shape or the response carries a call, the
        first of the four that applies. A returned failure is never raised, retried
        or routed (§5:4). The exchange beside it holds the reply as the model wrote
        it, the model that answered, the mode, the finish reason, a refusal's
        statement and category, the usage, and the shape's name and version (§5:3).

        Args:
            messages: Conversation history, oldest first. Non-empty, not ending on a
                ``Role.ASSISTANT`` turn, and carrying no ``Role.TOOL`` turn.
            shape: The pydantic model class the reply is asked for and read as.
            model: Optional ``"provider:model"`` override; falls back to the
                configured default when ``None``.

        Returns:
            The shape's value or a returned failure, with the exchange beside it.

        Raises:
            ModelError: Only where no response came back to read (§2:5). If
                ``messages`` is empty, ends on a ``Role.ASSISTANT`` turn or carries a
                ``Role.TOOL`` turn, or ``shape``'s schema cannot be closed, before
                any model is contacted and with ADR-0066 §3's disposition: neither
                ``retryable`` nor ``routable``. Also raised where the exchange with
                the provider fails or a deadline expires (§6:3), narrowed to the most
                specific subclass as :meth:`ModelProvider.complete`'s failures are
                (ADR-0063).
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
class BatchCompleter(Protocol):
    """Bulk completion: submit many conversations, poll, then fetch the answers.

    A **sibling** of :class:`ModelProvider`, not a widening of it (ADR-0143 §1).
    Nothing here is added to ``ModelProvider``, this Protocol does not inherit
    from it, and an object may implement both without anything requiring that it
    does. The ground is ``Embedder``'s exact one, one step stronger: bulk
    inference is a capability a provider may not offer — the library the model
    seam is built on exposes no batch surface at all, and the vendor endpoint that
    does is not available on every platform a ``default_model`` string may name. A
    member on ``ModelProvider`` would assert of *every* route a capability most
    routes cannot honour, and would oblige ``RetryingProvider`` and
    ``RoutingProvider`` to forward an operation neither one's policy fits: retrying
    a job measured in hours is not what a retry means, and routing a batch to a
    fallback is incoherent because a handle issued by one provider is meaningless
    to another.

    **Three members, and none of them waits.** Each performs a bounded exchange
    with the provider and returns; no implementation may satisfy :meth:`poll` or
    :meth:`fetch` by sleeping, retrying, or otherwise blocking until the batch
    settles. How many requests one exchange costs is the implementation's business
    and is not fixed here. Waiting is the caller's loop, over :meth:`poll`.

    **The split is decided by this module's cancellation clause, not by taste.**
    The nicer call site is one awaitable that hides the polling — and it fails
    ADR-0060. A submitted batch is a resource that is remote, outlives the
    coroutine, is being billed, and cannot be released by returning; a single
    awaitable that is cancelled orphans a paid job whose only identifier existed
    inside the frame that just unwound, and there is no shape of a bare awaitable
    that hands the identifier back on the cancellation path. Three members put the
    handle in the caller's hands **before any waiting begins**, so the worst a
    cancellation of the *wait* costs is the wait.

    **Splitting the wait out shrinks the orphaning window; it does not close it,
    and this contract says so rather than claiming otherwise.** A cancellation
    landing inside :meth:`submit` — after the provider accepted the batch, before
    the handle came back — orphans that batch. ADR-0060's effect limb governs it
    unamended: "a cancelled call's effect is indeterminate to the caller", so a
    caller cancelled there may assume neither that a batch exists nor that one does
    not. What the seam does is make the window as narrow as one round trip, by
    moving every refusable check to the near side of it (:meth:`submit`), and state
    the residue plainly. An idempotency promise on ``batch_key`` was drafted and
    **withdrawn**: the primary vendor surface transmits no idempotency key, carries
    no caller-supplied field on the batch, and filters no list by one, so an
    implementation could only have satisfied it by guessing (ADR-0143 §2, §11).

    **A handle is an address, not a capability** (ADR-0143 §2). An implementation
    accepts a :class:`~ai_assistant.core.types.BatchHandle` whose ``issuer`` equals
    its own configured one and rejects any other as a caller error, raising
    ``ModelError`` with the disposition ADR-0066 §3 fixes for a malformed argument
    — neither ``retryable`` nor ``routable`` — rather than returning an outcome.
    **Object identity is not the test:** a handle persisted to disk and presented
    to a freshly constructed implementation of equal ``issuer`` is valid, and that
    is what makes resumption across a process restart possible. The scope is
    deliberately the *account* and not the model route: reachability is a property
    of the credential's account, so a run resumed against the same
    ``"provider:model"`` string but a different account cannot fetch the first
    account's batch, and a route-only test would have called that handle valid and
    sent the caller to a failure it had been promised would not happen.

    ``issuer`` itself is **supplied by the composition root that constructs the
    implementation** and never derived from the credential. That is a concession
    the vendor surface forces: the client exposes an API key and no account
    identifier at all, and the obvious substitute is worse — a credential
    fingerprint changes on a routine rotation, so it would reject a handle that is
    still perfectly reachable, while still not distinguishing two credentials
    issued against one account. The cost is stated plainly: a misconfigured
    ``issuer`` can accept a handle for the wrong account and the seam cannot detect
    it. What it buys is that the failure is a visible configuration error rather
    than an invented one.

    **What this seam does not promise** (ADR-0143 §10), and no implementation may
    be relied on for: streaming — a batch is non-streaming by construction, and
    partial results before the terminal state are not offered; tool use — each item
    inherits :meth:`ModelProvider.complete`'s position that nothing at the model
    seam promises tool support, and a ``Role.TOOL`` turn is not representable in an
    item; prompt-cache behaviour across items or across batches; **cancelling** a
    submitted batch; a per-item model override; ordering; a size bound; or a
    handle's meaning to any provider other than its issuer.

    The absent ``cancel`` is worth its own sentence, because
    :class:`~ai_assistant.core.types.BatchOutcomeKind` keeps a ``CANCELLED``
    outcome and a reader will ask why the verb is missing. A cancel here could
    promise only that we asked: work already in flight is billed, the vendor's own
    cancel is a best-effort transition rather than a stop, and the caller's real
    remedy — stop polling and let the window close — costs nothing and is already
    available. A member whose only honest guarantee is "the request was sent" is
    weaker than no member, because it reads as a stop.

    How :meth:`submit` observes the items it is handed is governed by this
    module's input-observation clause (ADR-0065), which has real bite here and is
    **not** discharged by the items being frozen: ``submit`` takes a caller-owned
    ``Sequence``, validates it, then suspends on a network call.
    """

    async def submit(
        self,
        batch_key: NonBlankEncodableText,
        items: Sequence[BatchRequest],
        *,
        model: str | None = None,
    ) -> BatchHandle:
        """Hand a whole batch to the provider and return the handle that names it.

        **Every check that can refuse a batch happens before the provider is
        contacted**, and nothing happens after the provider accepts except
        returning (ADR-0143 §2). Each item's ``messages`` must satisfy the same
        precondition :meth:`ModelProvider.complete` states on its own — non-empty,
        not ending on a ``Role.ASSISTANT`` turn — read as that docstring states it:
        a **necessary condition, not a sufficient one**, admitting nothing by
        omission, so a history containing a ``Role.TOOL`` turn is refused although
        the clause does not name it.

        **A failing item refuses the whole batch**, never the well-formed subset.
        That costs something and is taken deliberately: a partially-submitted batch
        is a paid job the caller did not ask for and cannot describe, and the
        caller's own record of what it submitted would be wrong. Validating before
        contact is what makes the refusal free.

        ``batch_key`` is **never interpreted**. It is carried unchanged onto the
        returned handle so the caller can correlate its own durable record of an
        intended batch with the handle it got back. It is not an idempotency key:
        ``submit`` does not deduplicate on it, and two calls carrying one
        ``batch_key`` create two batches.

        The items are observed **at one instant, before the first ``await``**, by
        one of ADR-0065's three discharges, and the snapshot is deep enough to
        cover everything the call goes on to read — a shallow copy of the outer
        sequence would leave a caller free to mutate a
        :class:`~ai_assistant.core.types.BatchRequest` still in it, or that
        request's own ``messages``, between validation and transmission. A caller
        that mutates what it passed while ``submit`` is suspended can make the call
        act on the wrong version, but can never make one batch describe two.

        This seam fixes **no** size bound (ADR-0143 §7). An implementation *may*
        refuse an over-large batch, and when it does it states the bound it
        applied; a caller is obliged to be prepared to split. A number in the
        contract would be one vendor's limit written into a model-agnostic seam,
        wrong for the next implementation on the day it landed.

        Args:
            batch_key: The caller's own key for this batch. Carried unchanged onto
                the handle and never interpreted.
            items: The batch's items, each carrying a caller-minted ``item_id``
                unique within the batch. Must be non-empty.
            model: Optional ``"provider:model"`` override for the whole batch;
                falls back to the configured default when ``None``. There is no
                per-item override (ADR-0143 §10).

        Returns:
            The batch's :class:`~ai_assistant.core.types.BatchHandle`, carrying
            ``batch_key`` unchanged and the implementation's configured ``issuer``.

        Raises:
            ModelError: If ``items`` is empty, if any item's ``messages`` fails the
                precondition above, if two items share an ``item_id``, or if the
                implementation refuses the batch as over-large. Every one of these
                is refused before the provider is contacted, and what binds is the
                *disposition*: neither ``retryable`` nor ``routable``, because a
                malformed argument reproduces identically on every attempt from
                every route (ADR-0066 §3). A provider failure is narrowed to the
                most specific subclass.
        """
        ...

    async def poll(self, handle: BatchHandle) -> BatchStatus:
        """Ask the provider where a batch has got to, and return without waiting.

        One bounded exchange. A batch that has not settled is reported as
        :attr:`~ai_assistant.core.types.BatchState.PENDING`; ``poll`` never blocks
        until it settles, and a caller that wants to wait writes the loop.

        ``total`` is read from the provider on **every** call, beside the
        ``settled`` it must agree with, because nothing on the handle can be
        trusted as a count (ADR-0143 §9). An implementation whose provider reports
        no in-flight progress reports ``settled`` as ``0`` until the batch
        completes; that satisfies the invariant and is not a defect.

        Args:
            handle: The batch to ask about. Its ``issuer`` must equal this
                implementation's configured one; object identity is not the test.

        Returns:
            The batch's :class:`~ai_assistant.core.types.BatchStatus`.

        Raises:
            ModelError: If ``handle``'s ``issuer`` is not this implementation's —
                a caller error, neither ``retryable`` nor ``routable`` (ADR-0066
                §3) — or if the exchange with the provider fails, narrowed to the
                most specific subclass.
        """
        ...

    async def fetch(self, handle: BatchHandle) -> Sequence[BatchItemOutcome]:
        """Read a settled batch's outcomes: exactly one per submitted item.

        Defined only for a batch whose :meth:`poll` has reported
        :attr:`~ai_assistant.core.types.BatchState.COMPLETE`; a
        ``PENDING`` batch raises rather than being waited for. It returns one
        :class:`~ai_assistant.core.types.BatchItemOutcome` per submitted item — no
        more, no fewer, and none for an ``item_id`` that was not submitted.

        **The order is unspecified** and an implementation is not required to make
        it stable. A caller matches an outcome to its request by ``item_id`` and
        never by position: the vendor's results arrive unordered, and the seam
        admits kinds that carry no message, so ordering would be a convenience it
        cannot honestly provide.

        **A single item's failure is returned, never raised.** ``fetch`` raises
        only for a fault of the fetch itself — the handle, the transport, the
        results-retention window, or a batch that is not yet ``COMPLETE`` — and
        never because some items failed. A batch's whole point is that one item's
        refusal must not destroy the other results, and an exception is not a
        container that can hold them.

        **Retention is not the processing window, and a lapsed fetch raises.** The
        processing window is per item and surfaces as the ``EXPIRED`` outcome; the
        results retention is per batch and is reported as
        :attr:`~ai_assistant.core.types.BatchStatus.results_expire_at`. A ``fetch``
        against a batch whose retention has lapsed raises: it never returns an
        empty or short set of outcomes, and it never reports a lapsed item as
        ``EXPIRED``. Conflating the two is the failure this clause exists to
        prevent, and the dangerous direction is the silent one — a short return
        would read as a run of expired items and be scored as though it had
        happened.

        Args:
            handle: The batch to read. Its ``issuer`` must equal this
                implementation's configured one; object identity is not the test.

        Returns:
            One outcome per submitted item, in unspecified order.

        Raises:
            ModelError: If ``handle``'s ``issuer`` is not this implementation's, if
                the batch has not settled, if its results retention has lapsed, or
                if the exchange with the provider fails. The first two are caller
                errors and carry ADR-0066 §3's disposition; a provider failure is
                narrowed to the most specific subclass.
        """
        ...


@runtime_checkable
class ToolCallingCompleter(Protocol):
    """One planning round: a model response in the provider's native tool-calling shape.

    A **sibling** of :class:`ModelProvider`, not a widening of it (ADR-0307 §10), on
    the ground ADR-0143 §1 and ADR-0173 §5 established for :class:`BatchCompleter`
    and for the streaming completer ADR-0309 §5 retired: a member on
    ``ModelProvider`` would assert of every route a capability not every model
    offers, and would silently unsatisfy every existing implementation of a
    ``@runtime_checkable`` Protocol. Nothing is
    added to ``ModelProvider`` or ``Message``, this Protocol does not inherit from
    either, and an object may implement both.

    **One response, in its parts** (ADR-0356 §7:1): its text, which is all the text the
    model wrote outside a call, its calls, and its continuation. The text is the model's
    reply to the system, which planning keeps as the round's notes (§7:2); no tool
    carries notes, no tool name is reserved (§7:4), and no part of the response names
    the calls a message asks about (§7:5). No part asks for another round (ADR-0315
    §3:4).

    **One continuing exchange** (ADR-0356 §5). A round is asked with its work's whole
    exchange: the instruction, the briefing, then each earlier round's response and the
    report after it, in order (§5:1). The exchange is append-only, and the briefing is
    handed in byte for byte on every round (§5:2). Every ``user`` turn is the system
    speaking, the briefing or a report, and none is a person's (§2:1).

    **Thinking, handed back** (ADR-0356 §6). The response's ``continuation`` is what the
    provider needs handed back with it to continue the exchange, its thinking included,
    and each earlier response is handed back as the completer returned it (§6:2). It is
    opaque outside ``models/``. An implementation accepts an exchange whose earlier
    response carries no continuation, or one another model wrote, and sends a request the
    provider accepts; how is its own, and nothing outside ``models/`` relies on a model
    keeping its earlier thinking (§6:3).

    **It proposes and runs nothing.** A returned call is what the model proposed, as
    the provider returned it: nothing here runs it, checks it against its schema, or
    promises that it names a tool that was offered. Judging the calls is the
    caller's (ADR-0307 §5:3, §9:1).

    How :meth:`respond` observes the exchange and the tools it is handed is governed by
    this module's input-observation clause (ADR-0065): the tools are a caller-owned
    sequence, and the call suspends between reading them and answering.
    """

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        """Produce one planning round's response to ``exchange``, offering ``tools``.

        ``tools`` may be empty, and its names are distinct. No name is reserved: a tool
        of any name is offered as given (ADR-0356 §7:4).

        **The response comes back whole or not at all.** Its ``text`` is the text the
        model wrote outside a call, its text parts joined, possibly empty, and never its
        thinking; its ``calls`` are every call the model proposed, in the order the
        provider returned them, each with the provider's id, the name the model gave and
        its arguments as a JSON object; and its ``continuation`` is what the provider
        needs handed back with it, or ``None``. Nothing in the response asks for another
        round (ADR-0315 §3:4).

        Args:
            exchange: The work's exchange: the instruction, the briefing and each
                earlier round with its report, oldest first.
            tools: The capabilities offered for this round, with distinct names.
            model: Optional ``"provider:model"`` override; falls back to the
                configured default when ``None``.

        Returns:
            The round's response.

        Raises:
            ModelError: If two of ``tools`` share a name — before any model is
                contacted, and with ADR-0066 §3's disposition: neither ``retryable``
                nor ``routable``. Also raised where the exchange with the provider
                fails or its response cannot be read as a round, such as a call whose
                arguments are not a JSON object, narrowed to the most specific
                subclass.
        """
        ...


@runtime_checkable
class SpeechTranscriber(Protocol):
    """Turns a recording into the words it carries (ADR-0200 §1).

    A **sibling** of :class:`ModelProvider`, not a widening of it, and a sibling
    of :class:`SpeechSynthesizer` beside it. Nothing here is added to
    ``ModelProvider``, this Protocol inherits from nothing, and an object may
    implement both speech seams without anything requiring that it does. The
    ground is ``Embedder``'s and ``BatchCompleter``'s: speech recognition is a
    capability most providers do not offer, and a member on ``ModelProvider``
    would silently unsatisfy ``PydanticAIProvider``, ``RetryingProvider``,
    ``RoutingProvider`` and every fake at once — the asymmetry ADR-0021 §3 ruled
    and this module's own "prefer adding a new Protocol over widening an existing
    one".

    **Two members and no more**, and neither is a deadline. A timeout on this seam
    would bind one implementation; the deadline is a decorator the composition
    root wires over whichever implementation it built, so that it "composes over
    *every* implementation" (ADR-0200 §1, ADR-0118 §2). ``models/`` ships
    ``BoundedSpeechTranscriber`` for that.

    **Where inference runs is not decided here** (ADR-0200 §5). What binds an
    implementation that blocks is ADR-0118's two-layer containment: the deadline
    above, and blocking work run off the event loop on threads the implementation
    owns and bounds, never on the loop's default executor (ADR-0118 §7).
    Nothing here names a model, a vendor, a language or a sample rate.

    **Its failures are** :class:`~ai_assistant.core.errors.SpeechError` **and its
    subclasses, and nothing else that is not a defect** (ADR-0200 §1). No
    implementation raises a ``ModelError``. The one exception is the argument
    refusal below, which is a ``ValueError`` because it is a caller error rather
    than a seam failure and is settled before any I/O.

    Cancelling :meth:`transcribe` is governed by this module's cancellation
    clause (ADR-0060), and how it observes the value it is handed by the
    input-observation clause (ADR-0065) — vacuously, since
    :class:`~ai_assistant.core.types.SpokenAudio` is frozen and holds only
    scalars.

    **Nothing on this path retains the recording** (ADR-0200 §8). No
    implementation writes it, a fragment of it, or a length that would let one be
    reconstructed, to any store, index, trace, trail, outbox or log in either
    tier; and none puts it inside an exception message, where ADR-0200 §8's
    guarantee cannot see it and nobody looks.
    """

    @property
    def formats(self) -> frozenset[SpokenAudioFormat]:
        """The container-and-codec members this implementation can decode.

        A capability read **before** a call, which is why it is a set and carries
        no order: it expresses what can be read, never a preference among what
        can. A caller reads it and refuses a recording it does not name rather
        than handing one over to find out (ADR-0200 §1, §9).

        It answers the same across the lifetime of the implementation. A property
        that changed once a model had loaded would let a recording be admitted
        against one answer and refused against another.
        """
        ...

    async def transcribe(self, audio: SpokenAudio) -> EncodableText:
        """Return the words heard in ``audio``.

        **A blank return is not a failure.** Empty, or whitespace only — which is
        exactly what :data:`~ai_assistant.core.types.NonBlankEncodableText`
        refuses — means the recording carried no words, and the return type is the
        unrefined :data:`~ai_assistant.core.types.EncodableText` precisely so that
        a transcriber can say so without raising. What a caller does with it is
        ADR-0200 §4's, not this seam's.

        **The transcript is not normalised.** An implementation returns what it
        heard; it does not strip, trim, case-fold or otherwise rewrite the value
        to make a later blankness test easier, because a caller may compare the
        value it gets against one it stored (ADR-0096 §2, ADR-0102 §2).

        Args:
            audio: The recording. Its ``media_type`` must be named by
                :attr:`formats`.

        Returns:
            The words heard, or a blank string where there were none.

        Raises:
            ValueError: If ``audio.media_type`` is not named by :attr:`formats`.
                Raised locally, **before any I/O**, and refused rather than
                substituted — no implementation guesses at a container it did not
                declare. ADR-0200 §3 has the engine read :attr:`formats` before it
                calls, so a conforming caller never provokes this; it exists for
                the caller that is not one.
            SpeechError: If transcription failed. This class and its subclasses
                are the whole of the vocabulary, and a ``ModelError`` is not in
                it (ADR-0200 §1).
        """
        ...


@runtime_checkable
class SpeechSynthesizer(Protocol):
    """Turns text into audio of it being spoken (ADR-0200 §1).

    :class:`SpeechTranscriber`'s sibling, symmetric with it member for member,
    and introduced under the same ruling and the same three grounds. Read that
    Protocol's docstring for the seam-shape clauses — no deadline, containment
    rather than a process boundary, a ``SpeechError`` vocabulary, and no
    retention — each of which binds here identically.

    **Two members, and the redundancy argument does not reach them** (ADR-0200
    §1). *What this implementation can produce* and *what this rendering is in*
    are two questions, not one asked twice: the first is a capability read before
    a call, the second a fact about a value returned by one. What would have been
    redundant is a format property beside a returned ``media_type`` that could
    disagree with it — and :meth:`synthesize`'s equality clause is what forbids
    the disagreement rather than a second answer to one question.

    **That the audio is an audible rendering of the text is this seam's
    obligation**, discharged in its conformance suite (ADR-0200 §4). No consumer
    decodes, re-transcribes or otherwise inspects a rendering to check it, and no
    lane adds an operation that does.

    Cancelling :meth:`synthesize` is governed by this module's cancellation
    clause (ADR-0060).
    """

    @property
    def formats(self) -> frozenset[SpokenAudioFormat]:
        """The container-and-codec members this implementation can produce.

        The transcriber's property in the output direction, and a set for the same
        reason: a capability expresses no preference. The *preference* is the
        caller's, and ADR-0200 §3 puts it in an ordered argument on the promoted
        surface rather than here.
        """
        ...

    async def synthesize(
        self,
        text: NonBlankEncodableText,
        *,
        format: SpokenAudioFormat,  # noqa: A002 — ADR-0200 §1 fixes this signature
    ) -> SpokenAudio:
        """Render ``text`` as audio in ``format``.

        **The returned value's ``media_type`` equals ``format``** (ADR-0200 §1).
        An implementation asked for a format :attr:`formats` does not name refuses
        it rather than substituting one, so no caller is handed a rendering it
        cannot play in place of one it can.

        One positional subject and every other argument keyword-only is ADR-0085
        §2's convention, unchanged.

        Args:
            text: What to say. Non-blank, because there is no audio of nothing —
                a caller with nothing to say does not call this seam (ADR-0200
                §4's ``spoken`` is ``None`` on exactly those shapes).
            format: The container-and-codec to produce. Must be named by
                :attr:`formats`.

        Returns:
            The rendering, whose ``media_type`` is ``format``.

        Raises:
            ValueError: If ``format`` is not named by :attr:`formats`. Raised
                locally, **before any I/O**, for the same reason and with the same
                standing as the transcriber's refusal.
            SpeechError: If synthesis failed.
        """
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

    Two reads answer two different questions and neither may disagree with the
    other. :meth:`search` is *retrieval*: it takes a query and ranks by relevance.
    :meth:`list_beliefs` is *inspection*: no query, a specified total order, a page,
    and a filter on the belief band (ADR-0073 §1). Both honour the same two
    read-time axes through the same store-level predicate, so "what do you believe
    about me" and "what do you retrieve" can never answer differently about a
    record's liveness.

    The live reads come in three shapes and none of them may disagree with another
    about a record's liveness. :meth:`get` and :meth:`get_many` answer the same question
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

    **The history read** answers a different question from every live read
    (ADR-0342 §2). :meth:`get_history` resolves memory ids the caller already holds
    to the memories the store holds at them, whatever their status, returning
    exactly what :meth:`export` would carry at each and reaching no episode. It
    makes no claim about liveness, so it cannot disagree with a live read about
    one (ADR-0342 §4:4), and where :meth:`get` returns a memory it returns the same
    record (ADR-0342 §3:3). The live reads stay live-only: none of :meth:`get`,
    :meth:`get_many`, :meth:`search` or :meth:`list_beliefs` gains a parameter, a
    mode or a default that reaches a memory that is not live (ADR-0342 §4:3).

    **Episodes are numbered** (ADR-0283 §1). The store gives every episodic record,
    when it inserts it, a **number**: a positive integer from one counter shared by
    every record the store holds, greater than every number it issued before, never
    reissued and never changed. An upsert at a stored id keeps the number that id
    holds. An episode's channel is written by the first write that carries it and
    never changed by a later one (ADR-0286 §12, partially superseding ADR-0283
    §1:3): an episode stored on no channel may gain one, which is how an episode
    inserted at admission learns the channel its activation resolves later, and a
    write through :meth:`add` or any :meth:`write_atomic` mode whose record is on a
    different channel from the one stored at its id, or on none, raises
    ``MemoryStoreError`` and writes nothing. Neither a deletion, :meth:`purge_expired`
    nor :meth:`clear` releases a number, and a durable store's counter survives a
    close, a restart and a re-embedding. A
    channel's order is its episodes' numbers, ascending, and two reads answer by
    it: :meth:`channel_episodes` reads a channel's live episodes, and
    :meth:`channel_episode_ids` enumerates every episode the store holds on a
    channel. A durable store keeps an episode's channel type, channel instance and
    number as indexed columns written with the record, so none of these reads
    filters a channel through the record's JSON.

    **An episode is open or frozen** (ADR-0286 §1, §12). An episode whose processing
    record's ``status`` is ``None`` is **open**: its activation is still running,
    and the writer extends it as each stage ends. The store keeps whether an episode
    is open as an indexed column written with every write of the record, embeds no
    open episode, and embeds an episode's ``content`` by the write that freezes it.
    The reads that feed a model pass over an open episode: :meth:`search` and
    :meth:`channel_episodes` never return one and never count one against a limit,
    and :meth:`walk_records` stops before the lowest-numbered one
    (§6). :meth:`get`, :meth:`get_many`, :meth:`episodes`, :meth:`episode_chunk`,
    :meth:`channel_episode_ids`, :meth:`list_beliefs`,
    :meth:`export` and the deletions reach an open episode as they reach any other,
    and :meth:`open_episodes` enumerates them. :meth:`get_history` reaches no
    episode, open or frozen.

    **A recorded processing record and response change only by extension**
    (ADR-0286 §12, partially superseding ADR-0275 §12:6). A write through :meth:`add`
    or any :meth:`write_atomic` mode replacing a stored episode that carries a
    processing record, where the written record's processing record or ``outcome``
    differs from the stored one's, raises ``MemoryStoreError`` and writes nothing —
    unless the stored record is open and
    :func:`~ai_assistant.core.episode_encoding.episode_extends` holds of the two. A
    frozen episode's processing record and response are therefore immutable. The
    guard judges no other field: a write leaving both as stored is admitted, the
    owner's placement acts on a frozen episode and the re-derivation of its
    ``content`` included, and the record's own validators still bound what an open
    episode may carry.

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060). How :meth:`add` and :meth:`write_atomic` observe the records they
    are handed, how :meth:`get_many` and :meth:`get_history` observe their
    ``record_ids``, and how
    :meth:`search` and :meth:`list_beliefs` observe their ``Sequence`` filters, is
    governed by this module's input-observation clause (ADR-0065).
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

        **It stamps a fresh ``revision``, as every write that stores a row does**
        (ADR-0219 §1). The rule is stated once, on :meth:`write_atomic`, and binds
        this door identically: the value is store-authored, a submitted one is
        discarded, and the stamp is one the store has never issued and will never
        issue again. ``add`` itself stays **unconditional** — a conditional single
        write would be a second spelling of a one-element batch, and one door for the
        conditional write is what keeps the two doors from disagreeing (ADR-0219 §2).

        Raises:
            MemoryStoreError: ``record.id`` names a stored record of a different
                ``kind``, or the write would change a stored episode's processing
                record or response other than by extending an open one, or change or
                drop its channel (ADR-0286 §12) — nothing is written — or the write
                fails.
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

        **An ``IF_UNCHANGED`` element is a conditional replacement** (ADR-0219 §2).
        It is applied only where its id names a stored row whose ``revision`` equals
        the element's ``expected_revision``; otherwise the whole batch fails with
        ``MemoryStoreStaleError`` and nothing is committed — including where the id
        names no stored row at all, since a row deleted between the caller's read
        and its write is a lost update and not a no-op (§3). The comparison and the
        write are **one indivisible step** inside the batch's transaction, and on a
        durable backend that transaction excludes a concurrent writer — one in
        another process included — for the whole of it; a store that read the stored
        revision, released, and then wrote would reproduce the very window the mode
        closes, one layer down. "Names a stored row" is physical presence in the
        sense above, so an expired or window-closed row satisfies the presence
        requirement and its revision is the one compared, and the cross-kind refusal
        binds this door exactly as it binds ``UPSERT`` (§4). The remedy for a
        refusal is **re-read and re-decide**, never re-apply, and every retry is
        bounded by a fixed number of attempts the caller states.

        **Every write that stores a row stamps it with a fresh ``revision``**
        (ADR-0219 §1): a value the store has never issued and will never issue
        again, whatever id it is stored at and whatever was stored there before. It
        is store-authored — a submitted ``revision`` is discarded and never
        persisted — always positive, never ``0``, and returned by every read that
        returns a record. A durable store's issuer survives a close, a restart and a
        crash; ``clear`` destroys records and never the issuer. Callers compare two
        revisions for equality only: nothing may be derived from their order, their
        difference, or a count.

        Raises:
            MemoryStoreConflictError: an ``INSERT_IF_ABSENT`` element's id already
                names a stored record. Nothing is written; the caller may re-mint
                and retry.
            MemoryStoreStaleError: an ``IF_UNCHANGED`` element's id names a stored
                row at a different ``revision``, or names no stored row at all
                (ADR-0219 §3). Nothing is written; the caller re-reads and
                re-decides.
            MemoryStoreError: an ``UPSERT`` or ``IF_UNCHANGED`` element's id names a
                stored record of a different ``kind`` (ADR-0108 §4, ADR-0219 §4), an
                element would change a stored episode's processing record or
                response other than by extending an open one, or change or drop its
                channel (ADR-0286 §12; this Protocol's docstring), any other backend
                failure, or a malformed batch (two writes to the same id, ADR-0046
                §3). Nothing is written.
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
        oblige to resolve every citation of every belief on a page; ADR-0328 §15:2
        resolves every support of a memory the same way. A page of memories each
        resolving its supports one ``get`` at a time is a lock acquisition per
        support on the shipped store; this makes it one per memory. ADR-0074 §5
        declined it and named the hub as where to revisit — that trigger did **not**
        fire, and this lands on the argument the deferral actually turned on rather
        than on the one it named (ADR-0086 §6 partially supersedes ADR-0074 §5).

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

    async def get_history(self, record_ids: Sequence[str]) -> Mapping[str, Memory]:
        """Return the memories held at ``record_ids``, whatever their status (ADR-0342 §2).

        **The history read.** It answers, by id, for each memory the store holds —
        ``current``, ``ended`` or ``wrong``, its validity window open or closed — and
        it does nothing else. It exists for a caller holding a pointer to a memory
        that may since have been retired: a pin or a style mark, which follows the
        memory's successors (ADR-0338 §4:8), and the observer's pin pass, which adds
        a support to the pinned memory itself (ADR-0338 §9:6).

        **It answers exactly what** :meth:`export` **would carry at each id**
        (ADR-0342 §3:1). Where ``export`` would carry a memory at the read's
        instant, this returns that memory; where it would carry none, the id is
        omitted. So a memory past its ``expires_at`` is omitted: retention wins over
        history here as it does in ``export`` (ADR-0045 §6), and a memory is never
        more reachable through this read than through ``export``. A forgotten
        (deleted) memory is omitted, because the store no longer holds it. An
        episode is not a memory, so ``export`` carries no memory at an episode's id
        and this read omits it: an episode has no status and names no successor
        (ADR-0342 §3's table), and :meth:`get_many` already answers for episodes.

        **Where** :meth:`get` **would return a memory, this returns the same
        record** (ADR-0342 §3:3), so the two never disagree about a memory both
        answer for. It makes **no claim about liveness** (ADR-0342 §4:4): a memory it
        returns may be current, retired or outside its window, and only a live read
        — :meth:`get`, :meth:`get_many`, :meth:`search` or :meth:`list_beliefs` —
        answers whether it is held now. A caller presents a memory as current only
        where a live read returned it (ADR-0342 §5:1).

        Each memory comes back **whole, as stored** (ADR-0342 §2:2): its status, its
        validity, its operations log with the successor any operation names, its
        supports and its revision. The revision is the stored one, as every read's is
        (ADR-0219 §1), so a caller can write to a retired memory conditionally on
        what it read (ADR-0328 §5:4).

        **It takes ids alone and follows no chain** (ADR-0342 §4:1, §4:2). It never
        searches, ranks, lists, enumerates or pages, and it returns a successor only
        where the successor's id is in the argument too. Following a chain is the
        caller's, hop by hop (ADR-0342 §5:2, §5:3).

        **It answers in** :meth:`get_many`'s **shape** (ADR-0342 §2:3, §2:4;
        ADR-0086 §6). One call is one snapshot: every id is judged against one
        instant and one state of the store. An id that does not resolve is simply
        missing from the mapping, never an error and never a ``None`` value
        (ADR-0342 §3:2). Duplicate ids collapse, there is deliberately no size cap on
        the argument, and records are detached snapshots, like every other
        ``MemoryStore`` read.

        How this call observes ``record_ids`` is governed by this module's
        input-observation clause (ADR-0065), exactly as :meth:`get_many`'s argument
        is.

        Args:
            record_ids: The ids to resolve. An **empty sequence returns an empty
                mapping** and requires no round trip, as :meth:`get_many`'s does.

        Returns:
            A mapping from id to memory, holding an entry for exactly those ids at
            which :meth:`export` would carry a memory.

        Raises:
            MemoryStoreError: If the store cannot be read, or a stored record is
                corrupt (ADR-0342 §2:5).
        """
        ...

    async def search(  # noqa: PLR0913 — one argument per eligibility axis
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
        person: NonBlankEncodableText | None = None,
        as_subject: bool = False,
    ) -> MemorySearchResult:
        """Return the records most relevant to ``query``, best first.

        Expired records are never returned, nor are records not live at now — a
        record whose window is closed or not yet open is omitted, both ends
        enforced, exactly as an expired one is (ADR-0045 §6).

        **Every read-time eligibility predicate binds before the ranking cut**
        (ADR-0128 §1): the ``kinds`` filter, ADR-0007 §2's ``expires_at`` retention
        deadline, and **both** ends of ADR-0045 §6's validity window, alongside the
        band predicate ADR-0113 §2 already binds there. An implementation may not
        let a record failing any of them consume the candidate budget the cut is
        taken from, and the records it ranks are the records eligible on every one
        of those axes. A store that cannot bind one of them before its cut does not
        conform — the implementing lane stops and brings back an ADR rather than
        shipping the weaker form.

        That rules **where a predicate binds, not how large a page a caller gets**.
        ``limit`` still cuts, and a result holding ``limit`` records asserts nothing
        about whether the store holds further eligible records below it; the
        completeness a caller *does* get is ``capped``'s, below, and nowhere else.
        It also moves only *where* the axes bind and nothing about what they mean or
        which instant they are read against: no axis is added, removed or relaxed,
        ``search`` gains no ``include_retired`` axis and no as-of axis, and the
        liveness it applies stays read-time-relative (ADR-0128 §1).

        **``capped`` says whether the store's own candidate ceiling bound the read**
        (ADR-0128 §2), and it is the only under-service signal on this contract:
        ``search`` does not raise or otherwise refuse because a read was capped, no
        parameter selects a refusing or completeness-requiring mode, and no second
        member reports on a ``search`` that has already returned. Four clauses fix
        it, and they are what an implementation is judged against:

        * Where ``capped`` is ``False`` **and the result holds fewer than ``limit``
          records**, the store holds **no** further record matching the call's
          filters and passing its read-time eligibility axes. The result is the
          whole eligible set at the read instant and a caller may act on that.
        * Where ``capped`` is ``True``, the store's own candidate ceiling bound the
          read short of ``limit`` and the store certifies nothing — a caller may not
          read the result as the whole eligible set.
        * ``capped`` is ``False`` on **every** result holding ``limit`` records, and
          on such a result it certifies nothing: a full page never asserts that the
          store holds no more eligible records below the cut, however large or small
          the eligible set is and whether or not a ceiling was reached in filling
          the page. ``capped`` reports the store's ceiling, never the size of the
          eligible set.
        * ``True`` is available on a result **shorter than ``limit``** and nowhere
          else. There it is a refusal to certify and never a claim that more exists:
          an implementation reports ``False`` only where the first clause lets it
          certify and ``True`` wherever it cannot, including where its eligible set
          exactly meets its ceiling. It reports ``False``, never ``True``, where
          ``search`` matches nothing by construction — a blank query, a non-positive
          ``limit``, or a filter selecting nothing. An empty result is not a capped
          one.

        So ``capped`` certifies in one direction only, which is what keeps it
        mechanically decidable: ``False`` is the claim and ``True`` is the absence of
        one, so a store that cannot tell reports ``True`` and conforms. Requiring
        exactness in both directions would oblige it to prove a negative about rows
        it never fetched. **What a consumer does with the signal is not decided
        here** (ADR-0128 §6) — no caller is obliged to act on it.

        **The band filter binds before the ranking cut** (ADR-0113 §2). An
        implementation may not let a record outside the selected bands consume the
        candidate budget the cut is taken from: the records it ranks are the
        selected bands' records, never the selected-band members of a band-neutral
        top ``limit``. A store that cannot bind the band before its cut does not
        conform — the implementing lane stops and brings back an ADR rather than
        shipping the weaker form. This is the clause an implementation can pass in
        name and fail in substance, and it is why the band filter is a contract
        decision rather than a parameter: applied *after* the cut it reproduces the
        failure ADR-0072 §5 refuses by name, where "a flood of low-confidence
        inferences can displace an assertion *below the cut*". At a realistic band
        skew that is not a degradation but a total one — asking for the user's own
        assertions returns none of them while every one is live.

        **The band is an eligibility axis, never an ordering one** (ADR-0113 §4).
        It decides which records are ranked and contributes nothing to how ranked
        records compare: it is not a term in any ordering, not an addend or factor
        in any score, not a weight, and not a threshold a record is dropped below.
        Within one call the order is relevance alone, whichever bands are selected —
        where a call spans more than one, including the ``bands=None`` default,
        records of different bands are compared to one another by relevance and by
        nothing else. The prohibition is on the band *influencing* a comparison,
        never on the comparison happening. ``search`` stays band-neutral and
        confidence-neutral in the sense ADR-0072 §5 ruled and ADR-0112 §1 affirmed;
        neither currency nor evidence-strength is a term in any ordering here, and
        this parameter supplies neither quantity and creates no place to put one.

        **``bands`` does not turn this into an enumeration.** ``search``'s other
        refusals are unchanged: a blank query and a non-positive ``limit`` still
        match nothing, so an empty query with a band selected is still nothing
        rather than "the whole band" (ADR-0113 §3). That is deliberately unlike
        ``list_beliefs``, whose out-of-range ``limit`` and ``offset`` are *refused*.

        **Precedence is not this read's.** The store does not know which band the
        caller will place first, what budget each gets, or whether a band is being
        read at all. A consumer applying ADR-0072 §5's precedence issues one call
        per band and composes; the budget and the order stay with it (ADR-0113 §6).

        **Within one call the bands partition; across calls they do not.** Every
        returned record's band is one the caller selected —
        :func:`~ai_assistant.core.types.record_band` is total, so a record has exactly
        one band at one instant — and an implementation may not
        return an out-of-band record, in particular may not pad a short result with
        the next-nearest neighbour of another band to fill a page. A short result is
        the correct answer to a band with nothing more to give; padding converts an
        under-service into a wrong-band result the consumer cannot detect.

        Across calls **no disjointness is promised and none may be assumed**, and
        the mechanism is on the write path rather than hypothetical: ``add`` is an
        upsert keyed on the caller's id and a ``REINFORCE`` adds supports to a memory
        at its stable id (ADR-0328 §11:6), so a fold can move a memory between bands
        at that id. A consumer composing band-scoped reads
        therefore **deduplicates by record id**, keeping the copy from the
        higher-precedence band in ADR-0072 §5's order and counting it once against
        that band's budget — resolving the race by arrival order would decide
        precedence by loop order, which is the one thing §5 is about. A record that
        changes band between two of a turn's calls may instead be **missed** by all
        of them; that is accepted, not closed, and no consumer-side rule recovers
        it. A consumer may not read a short band-scoped result as evidence that the
        band holds nothing more. No multi-band snapshot and no cross-call read
        consistency of any kind is offered (ADR-0113 §5).

        Args:
            query: The search text.
            limit: Maximum number of records to return.
            kinds: If given, restrict results to these memory kinds.
            bands: If given, restrict results to these belief bands. ``None`` means
                every band — today's behaviour, so every existing caller is
                preserved unchanged; an **empty sequence selects nothing**, and is
                stated rather than left to be read off ``list_beliefs`` because that
                is how one implementation comes to treat ``bands=()`` as "no filter",
                the opposite outcome, on a parameter whose suite never asked. Keyed
                on :class:`~ai_assistant.core.types.BeliefBand`, the record's band as
                :func:`~ai_assistant.core.types.record_band` computes it (ADR-0328
                §11:2), and never on a standing or a source. Duplicates are set
                semantics and change nothing. ``bands`` and ``kinds`` compose by
                **conjunction**: a record is eligible when its band is selected *and*
                its kind is.
            person: If given, restrict results to memories naming this name in
                ``subjects`` or ``involved`` (ADR-0345 §9:6), compared exactly as
                carried: a name resolves to no identity (§9:3), so no case folding or
                aliasing applies. An episode names nobody there and is never
                returned. An eligibility predicate like the others, bound **before**
                the ranking cut (ADR-0128 §1), and composed with them by conjunction.
            as_subject: With ``person``, restrict to memories naming it in
                ``subjects`` alone. Without ``person`` it selects nothing more.

        Every frozen episode the axes select is returned, failed, interrupted and
        outside episodes included (ADR-0284 §6:2): a reader that should pass over a
        failed episode reads its status. **An open episode is never returned**
        (ADR-0286 §6:1): that predicate binds before every candidate ceiling, ranking
        cut and limit, under ADR-0128 §1, so an open episode spends no candidate slot
        and the activation's own episode takes no place in a result.

        Returns:
            A :class:`~ai_assistant.core.types.MemorySearchResult`: the matching
            records, most relevant first, each carrying its relevance ``score`` —
            **populated**, because this is a retrieval, the opposite of
            ``list_beliefs``' clearing rule (ADR-0073 §2) — and ``capped``, under
            the four clauses above. Each record is a detached snapshot, as with
            every ``MemoryStore`` read.
        """
        ...

    async def episodes(
        self,
        *,
        channel: ChannelIdentity | None = None,
        status: ProcessingStatus | None = None,
        cursor: NonBlankEncodableText | None = None,
        limit: int = 50,
    ) -> EpisodePage:
        """Inspect live episodic records under ADR-0275 §10.

        Filter by exact channel and status, then order by ``(occurred_at, id)``
        descending and take ``limit`` (a strict integer in [1, 100]). Unknown
        activation facts do not match a supplied filter. Addresses retain their
        exact stored characters, including blank values.

        Cursors are canonical unpadded URL-safe base64 EpisodeCursor values,
        bound to these filters. Continue strictly below their position. A next
        cursor exists exactly when another matching row existed at this read;
        this is not a snapshot across calls. Returned values are detached.

        Raises:
            ValueError: Invalid bounds, cursor spelling/version or filter mismatch,
                refused before I/O.
            MemoryStoreError: Store or record corruption failure.
        """
        ...

    async def episode_chunk(
        self,
        episode_id: EncodableText,
        *,
        version: NonBlankEncodableText | None = None,
        offset: int = 0,
        max_bytes: int = 65536,
    ) -> EpisodeChunk | None:
        """Read digest-bound detail of a live episode (ADR-0275 §10).

        Each call rereads the exact ID; absent, expired and non-episodic records
        return None. Serialize the validated entire episode's JSON-mode fields
        with sorted keys, compact separators, ensure_ascii=True, allow_nan=False.
        Version is the lowercase SHA-256 digest of those bytes. No cross-call
        content snapshot survives deletion. Return at most max_bytes bytes;
        next_offset is None exactly at the end, including an empty final slice.

        Raises:
            ValueError: Invalid UTF-8 address, malformed digest, strict integer
                offset outside [0, 2**63), size outside [1, 65536], versionless
                nonzero offset, or offset beyond current detail. Validate arguments
                before I/O; the last condition requires reading the record.
            StaleEpisodeReadError: A valid supplied digest differs from this read,
                with a fixed content-free message.
            MemoryStoreError: Store or record corruption failure.
        """
        ...

    async def channel_episodes(
        self,
        channel: ChannelIdentity,
        *,
        after: int | None = None,
        limit: int,
    ) -> ChannelEpisodePage:
        """Read a channel's live episodes in number order (ADR-0283 §3:1, §3:2).

        **The channel's order is its episodes' numbers, ascending** (§1), and
        nothing else: no timestamp and no id orders this read. An episode's channel
        is its processing record's ``trigger.channel``; an episode with no
        processing record, or whose trigger names no channel, is on no channel. A
        channel matches when both ``channel_type`` and ``instance_id`` are equal,
        exactly as stored.

        **Live** is :meth:`get`'s sense: an expired record, one whose window is
        closed and one whose window is not yet open are not read, both ends of the
        window enforced (ADR-0007, ADR-0045 §6).

        **Every live frozen episode on the channel is read** (ADR-0284 §6:1-§6:2),
        failed, interrupted and outside episodes included: the read takes no
        eligibility axis, and a reader that should pass over a failed episode reads
        its status. **An open episode is never read** (ADR-0286 §6:1), and the
        predicate binds before ``limit``: the running activation's own episode, which
        is on its channel for as long as it runs, takes no slot of a page.

        It returns, in number order ascending, **the newest** ``limit`` of the
        matching episodes when ``after`` is ``None``, or **the oldest** ``limit``
        numbered above ``after`` otherwise. A short page is the whole remainder in
        that mode. ``total`` is the count of every live frozen episode on the
        channel, whatever ``after`` and ``limit`` are, and counts no open episode —
        so a page and its ``total`` answer from one read instant and one state of
        the store.

        This is not the enumeration a deletion walks: it filters by liveness, and
        :meth:`channel_episode_ids` is that
        enumeration (ADR-0283 §8). Each record is a detached snapshot carrying its
        stored ``revision``, with ``score`` cleared to ``None`` because this read
        ranks nothing.

        Args:
            channel: The channel whose episodes are read.
            after: ``None`` for the channel's tail, or an episode number to read
                above. A number no store has issued yet is a valid value and
                answers an empty page.
            limit: The page size.

        Returns:
            The page and the channel's ``total``.

        Raises:
            ValueError: ``limit`` is not a strict integer in ``[1, 1000]``, or
                ``after`` is neither ``None`` nor a strict positive integer —
                ``bool`` is not a strict integer here. Refused before any I/O.
            MemoryStoreError: If the store cannot be read, or a stored record is
                corrupt.
        """
        ...

    async def channel_episode_ids(
        self,
        channel: ChannelIdentity,
        *,
        after: int | None = None,
        limit: int,
    ) -> tuple[ChannelEpisodeId, ...]:
        """Enumerate what this store physically holds on a channel (ADR-0283 §3:5).

        The number and id of **every** episodic record whose channel is ``channel``,
        in :meth:`channel_episodes`' sense of a channel: an expired record not yet
        purged, one whose window is closed or not yet open, and an ineligible one are
        all included. It returns the lowest ``limit`` numbered above ``after`` — or
        from the start of the channel where ``after`` is ``None`` — in number order
        ascending, and identifiers alone, never a record's content.

        This is the enumeration a conversation's deletion and reclaim walk, page by
        page until a read is empty (§8): no read filtered by liveness, validity or
        eligibility is that enumeration, and this read filters by none of them.

        Args:
            channel: The channel whose held episodes are enumerated.
            after: ``None`` for the channel's start, or an episode number to read
                above.
            limit: The page size.

        Returns:
            The page's identifiers, in number order.

        Raises:
            ValueError: ``limit`` is not a strict integer in ``[1, 1000]``, or
                ``after`` is neither ``None`` nor a strict positive integer, as
                :meth:`channel_episodes` bounds them. Refused before any I/O.
            MemoryStoreError: If the store cannot be read.
        """
        ...

    async def open_episodes(
        self,
        *,
        after: int | None = None,
        limit: int,
    ) -> tuple[ChannelEpisode, ...]:
        """Enumerate every open episode this store physically holds (ADR-0286 §12:1).

        An episode is open while its processing record's ``status`` is ``None``
        (§1). **Every** open episode is included, whatever its channel or none, and
        an expired one not yet purged, one whose window is closed and one whose
        window is not yet open are all included: this is the enumeration a restart
        walks to close what a dead process left open (§7), and no read filtered by
        liveness or validity is that enumeration.

        It returns the lowest ``limit`` numbered above ``after`` — or from the start
        where ``after`` is ``None`` — in number order ascending. Each entry carries
        the episode's number and the record as stored, a detached snapshot carrying
        its stored ``revision``, so a caller can condition a write on it, with
        ``score`` cleared to ``None`` because this read ranks nothing.

        Args:
            after: ``None`` for the start, or an episode number to read above. A
                number no store has issued yet is a valid value and answers an empty
                page.
            limit: The page size.

        Returns:
            The page's open episodes, in number order.

        Raises:
            ValueError: ``limit`` is not a strict integer in ``[1, 1000]``, or
                ``after`` is neither ``None`` nor a strict positive integer, as
                :meth:`channel_episodes` bounds them (ADR-0283 §3:2). Refused before
                any I/O.
            MemoryStoreError: If the store cannot be read, or a stored record is
                corrupt.
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
        """Enumerate the memories held right now, newest revision first (ADR-0073 §1).

        The band-scoped read ADR-0072 §7 ruled owed: "show me what you believe
        about me". **It lists memories, and excludes episodes by default**
        (ADR-0328 §11:2, ADR-0074 §6): with ``kinds`` ``None`` only the memory kind is
        listed, and an episode is listed only where the caller names its kind. It
        carries **no query text** and is not a retrieval — nothing is ranked and no
        relevance is computed — so it is an enumeration with a stable order and a page
        rather than a filter on :meth:`search`.

        **Both read-time axes are honoured, exactly as ``get``/``search`` honour
        them.** An expired record is never returned, and neither is a record not
        live at now — a closed ``valid_until`` or a not-yet-open ``valid_from``,
        both ends enforced (ADR-0007, ADR-0045 §6). Inspection reads **live
        beliefs only**: a retired record is not a belief the assistant holds but a
        record of one it used to. It stays reachable through ``export``, and by id
        through :meth:`get_history` (ADR-0342 §4:3, partially superseding ADR-0073
        §3), and never through this read: there is deliberately no
        ``include_retired`` axis.

        **The order is total, stable and specified: transaction time descending,
        ties broken by ``id`` ascending** — a memory's latest operation's instant
        (ADR-0328 §7:8), an episode's ``provenance.last_updated``, as
        :func:`~ai_assistant.core.types.record_transaction_time` computes both. Some
        total order has to be named or two stores answer the same page differently
        while each believes it conforms. Newest-revision-first is the right default
        for inspection, and every operation moves the transaction time, so a
        corrected topic surfaces where the user will look for it.

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
                :class:`~ai_assistant.core.types.BeliefBand`, the band
                :func:`~ai_assistant.core.types.record_band` computes (ADR-0328
                §11:2): the vocabulary ADR-0072 §2 ratified and the unit the user
                reads.
            kinds: If given, restrict results to these kinds; ``None`` means the
                memory kind alone, so episodes are excluded by default (ADR-0328
                §11:2). An **empty sequence selects nothing**, stated rather than
                inferred from ``search`` so no implementation reads ``kinds=()`` as
                "no filter". The two filters compose by **conjunction**: a record is
                listed when its band is selected *and* its kind is.
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

        **The walk waits at the oldest open episode** (ADR-0286 §6:2, partially
        superseding ADR-0114 §1:2 and §1:7). A chunk examines no record at or past the
        lowest-numbered open episode the store physically holds, an expired one
        included: it stops before it. Where that episode is the next record to
        examine, the chunk examines nothing and carries no position, which tells the
        caller that nothing is left to examine **for now**; the walk's recorded
        position has not passed the open episode, so a later read resumes there and
        returns it once it is frozen. The walk is held rather than passed over the
        episode, because it never returns below its position, and an episode passed
        over while open would never be read once frozen.

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
            nothing left to examine**, an open episode next included, and that —
            never an empty record list — is how a caller learns the walk is
            exhausted for now. A chunk may carry a position
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
    """Decides the fate of a proposed memory — the "dispose" half.

    The producer *proposes* a memory; a deterministic policy implementing this
    Protocol *disposes* of it, so writes to long-term memory are reviewable and
    bounded rather than an unmediated side effect of generation. A policy reads a
    memory through ADR-0328 §12: where an earlier clause it implements names a
    source, a band or a confidence, it reads the memory's band (§6:4) and whether it
    rests on outside content (§7:6), and no memory carries a confidence (§10:2).
    """

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
        relations: Mapping[str, ConflictRelation] | None = None,
    ) -> MemoryDecision:
        """Rule on a proposed memory.

        **A ruling is a total function of its arguments** (ADR-0159 §2, ADR-0328
        §11:10). No implementation consults a ``ModelProvider``, a
        ``BatchCompleter``, a store, a clock or a network. ``decide`` returns the same
        ruling for the same ``proposal``, the same ``conflicts`` and the same
        ``relations``.

        **``relations`` is what a fold may rest on, and similarity is not**
        (ADR-0159 §1, §4). A member of ``conflicts`` is surfaced by *topical
        similarity*; a :class:`~ai_assistant.core.types.ConflictRelation` is a
        statement about how the proposal stands to one *named* member. A member absent
        from the mapping is **unlabelled** and supplies ground for nothing. A policy
        **ignores any entry whose key is not the id of a member of ``conflicts``**. A
        target-carrying ruling names one of the records ``decide`` was handed
        (ADR-0040 §5). ``None`` and an empty mapping rule identically. The mapping is
        a runtime read-only view (ADR-0159 §8).

        **A tainted derived proposal is never committed unconfirmed** (ADR-0106 §6,
        read through ADR-0328 §12 and §13:4). No policy returns a committing ruling —
        ``ACCEPT``, ``REINFORCE`` or ``SUPERSEDE`` — on a proposal whose memory is in
        the ``DERIVED`` band, rests on outside content, and carries no
        :class:`~ai_assistant.core.types.UserConfirmation`. Its terminal ruling is
        ``ASK_USER`` or ``REJECT``. The condition is band-scoped: an ``ATTESTED``
        memory rests on outside content by its nature and must still be allowed to
        commit. A confirmation passes it.

        **No policy stores a proposal tentatively** (ADR-0328 §10:3): no
        implementation rules ``STORE_TEMPORARY``, and a writer handed that ruling
        refuses it. A proposal that does not meet an evidence bar is not committed;
        the bar is the observer's decision's.

        **A placed proposal is ruled by the floor and the confirmation rule alone**
        (ADR-0345 §4:5, §4:6). Its ``conflicts`` are the stored memories its placement
        names, as the writer read them, and ``relations`` is ``None``. A policy rules
        ``REJECT`` or ``ASK_USER`` where its admissibility floor does, may rule on a
        proposal carrying a :class:`~ai_assistant.core.types.UserConfirmation` as its
        rule on a confirmed proposal does, and otherwise rules ``ACCEPT``, which the
        writer reads as "apply the placement": no other rule of a policy reads a placed
        proposal. ``DefaultMemoryPolicy``'s rules 1 to 4 are those two; its rules 5 to
        12 read no placed proposal.

        Args:
            proposal: The candidate memory and why it was proposed.
            conflicts: Existing records the proposal contradicts, already resolved
                from the store (the proposal carries their ids).
            relations: How the proposal stands to named members of ``conflicts``,
                keyed by record id (ADR-0159 §8). ``None`` where nothing determined
                any. Read-only.

        Returns:
            The decision to accept, reject, reinforce or supersede a named target
            record, or to defer to the user.
        """
        ...


@runtime_checkable
class MemoryWriter(Protocol):
    """The memory write path: conflicts, policy, persistence (ADR-0028, ADR-0328 §11).

    The "persist" half of propose/dispose/persist. A writer holds its own
    :class:`MemoryPolicy` and its own store, and exposes neither. **The store it
    writes to must be the one its caller retrieves from** — a composition-root
    obligation, unenforceable here because no store is on this seam (ADR-0028 §4).

    Four members: :meth:`ingest` creates a memory under the policy (ADR-0328 §11:4),
    retiring at most one stored memory with it (ADR-0329 §12:4), or writes a placed
    proposal by its placement (ADR-0345 §4, §5); :meth:`apply` applies one operation to
    one stored memory (§11:3); :meth:`record_use` records one track-record entry
    (ADR-0329 §14:4); and :meth:`write_labels` replaces a memory's labels (ADR-0345
    §7:6). Every change to a memory's supports, status, validity or open questions is
    an operation citing the support that caused it (§5:1), and no write changes a
    memory's wording (§3:2).

    **Every support a writer adds records its holder** (ADR-0345 §2:2), set by code
    from the part and the episode's record
    (:func:`~ai_assistant.core.types.stamped_support`): a support a producer built
    with none gains the one §2's table gives it, and one carrying a holder the table
    does not give its part is refused with nothing written. No write rewrites a
    holder a stored support carries (§2:9).

    **A created memory's people and labels** (ADR-0345 §7, §9). A name in ``subjects``
    or ``involved`` that no part the memory rests on gives is refused (§9:3,
    :func:`~ai_assistant.core.types.names_not_given`). A memory carrying labels is
    written only by a writer wired with the composition root's
    :class:`~ai_assistant.core.types.LabelBounds` and an embedder: more labels, or a
    longer one, than the bounds admit is refused, and a label within their distance
    of a label it already carries is not added and is named in the result's
    ``refused_labels`` (§7:3, §7:5).

    **An observer's inference** (ADR-0329 §9:7) is admitted only as that clause has
    it: ``for`` and backing the claim as worded only on a memory whose other supports
    added with it are all ``for`` and none backs the claim as worded, and ``against``
    only on a memory the ingest creating its memory retires, its ``when`` that
    episode's ``occurred_at``. A writer refuses every other inference support with
    nothing written: one :meth:`ingest`'s memory carries that breaks the first rule,
    one ``against`` on it, one whose ``when`` is not its episode's, and any one
    :meth:`apply` would add, since an operation adds one support alone.

    How :meth:`ingest` and :meth:`apply` observe what they are handed is governed by
    this module's input-observation clause (ADR-0065).
    """

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Resolve conflicts, ask the policy to rule, and apply its ruling (ADR-0328 §11:4-§11:9).

        The proposal carries a memory whose supports and create its producer built.

        - **``ACCEPT`` installs the proposed memory** (§11:5), as a new record: an id
          already naming a stored record is refused with
          ``MemoryStoreConflictError`` and nothing written (ADR-0108 §1-§3).
        - **``REINFORCE`` adds the proposal's supports to the target**, one add
          support each, and leaves the target's wording as it is; a support the
          target already carries changes nothing (§11:6). Placement's ratchet
          (ADR-0217 §3) and the union of topics (ADR-0213 §8) apply as on any fold
          (§11:9). The write is conditional on the target's revision (ADR-0219 §5).
        - **``SUPERSEDE`` installs the proposed memory at a fresh id** and ends each
          memory the ruling retires, with an end citing the new memory's first
          support, added to the retired memory as an ``against`` support. Each retired
          memory names the new one as its successor and the new one names them as the
          memories it replaces, in one atomic write (§11:7, §5:6). An end
          ADR-0328 §6:5 refuses, or a retired memory that already carries the part
          that support points at, refuses the whole ingest with nothing written.
        - **``REJECT`` and ``ASK_USER`` write nothing** (§11:8); a
          ``STORE_TEMPORARY`` ruling is refused, with nothing written (§10:3).

        **A proposal carrying a retiring operation** (``proposal.retiring``, ADR-0329
        §12:4) is ruled on over every conflict but the memory it retires: that memory
        is withheld from the conflicts the policy is handed and from the ids the
        proposal it sees carries, so the policy never rules on it. The operation cites
        a support of the new memory, added to the retired memory as an ``against``
        support, and is applied only as the ruling allows:

        - **``ACCEPT``** installs the new memory and applies the operation in one atomic
          write, each naming the other: the operation names the new memory as its
          successor, and the new memory's create names the retired one among those it
          replaces (ADR-0328 §5:6).
        - **``REINFORCE`` of an end or a mark wrong** adds the supports to the target as
          above and applies the operation naming no successor, in one atomic write.
        - **``REINFORCE`` of a replace**, which must name its replacement, and **every
          other ruling** write nothing, and the result says what was ruled.

        The retired memory's write is conditional on the revision it was read at. The
        writer refuses, with nothing written, a retirement whose cited support is not a
        counted ``for`` support of the new memory backing it as worded (§12:5); one
        whose cited support ranks below the retired memory's standing (ADR-0328 §6:5);
        one citing a confirmation where ADR-0328 §4:6 does not let this ingest retire
        that memory — an ``ASSERTED`` memory only where the proposal's confirmation
        genuinely covers it (ADR-0078 §5b), a ``DERIVED`` or ``ATTESTED`` one always
        (ADR-0079 §3); and one §5 refuses on the retired memory as :meth:`apply` would.

        **What a ``SUPERSEDE`` retires** is the write path's law read through
        ADR-0328 §12, whatever relations the writer holds (ADR-0336 §5): the target
        the ruling names and, beyond it, only those other conflicts whose band is in
        the retirement class — ``DERIVED`` or ``ATTESTED`` (ADR-0079 §3, ADR-0092 §4)
        — **and** which the writer holds a ``CONTRADICTS`` relation for. A conflict
        the writer holds no relation for is left live, whatever its band, so a
        ``SUPERSEDE`` over a set nothing labelled retires its target alone; a conflict
        it holds a ``RESTATES`` or ``ADDS`` relation for is never retired
        (ADR-0159 §5). An ``ASSERTED`` memory is retired only where the proposal's
        confirmation genuinely covers it (ADR-0078 §5b), and nothing folds onto an
        ``ASSERTED`` target but an agreeing ``REINFORCE`` (ADR-0121 §5, ADR-0214 §3),
        which only adds supports. A ``REINFORCE`` of an ``ASSERTED`` proposal onto an
        ``ATTESTED`` target is refused (ADR-0038 §2a). A ``SUPERSEDE`` naming a
        conflict the writer holds a ``RESTATES`` or ``ADDS`` relation for is refused
        (ADR-0159 §5).

        **The refusals before a ruling.** A proposal whose memory carries a support
        pointing at an episode the store does not hold is refused with
        ``UnresolvedEvidenceError`` and nothing written (§4:7). Conflict detection
        surfacing more conflicts than the writer resolves in one ingest is refused
        (ADR-0079 §1). **After the ruling and before any write**, a write-producing
        ruling on a ``DataTier.SECRET`` proposal is refused (ADR-0078 §5b check 0), and
        a ruling that would install the proposal at an id its own supports point at is
        refused (ADR-0081 §1): ``SelfConsumingWriteError`` for an ``ACCEPT`` at the
        proposed id, ``FoldOntoCitedRecordError`` for a ``REINFORCE`` at its target.
        A ``SUPERSEDE``'s minted id re-mints past such an id rather than refusing.
        A retirement whose close is unrepresentable is refused with every memory left
        unchanged (ADR-0080 §3, ADR-0328 §5:11).

        **A placed proposal** (``proposal.placement``, ADR-0345 §4, §5) is written by
        its placement and the holder rule, with no reconciler and no conflict search:

        - **The policy is handed the memories the placement names**, as the writer
          read them, with ``relations`` ``None``, and its floor or its confirmation
          rule is final (§4:5, §4:6): a ``REJECT`` or ``ASK_USER`` writes nothing, and a
          confirmed proposal's ``SUPERSEDE`` is applied as above. An ``ACCEPT`` applies
          the placement; any other ruling on a placed proposal is refused.
        - **A stale placement is refused whole** (§4:7): where a named memory's stored
          revision differs from the one the placement records, or it is no longer held,
          nothing is written and the result's ``stale`` names each.
        - **Each relation writes what §5's table says**, in one atomic write conditional
          on every revision it changes (§5:6). A retiring relation adds the proposal's
          backing supports to the stored memory as ``against`` and stops the counted
          supports on it of the proposal's own holders, each citing that holder's
          backing support; the memory is retired by the relation's operation exactly
          where nothing then backs it as worded, and otherwise its remaining backing is
          added as ``against`` where the proposal lands (§3). ADR-0328 §6:5 does not
          bind (§3:6).
        - **One disposition** (§5:3): a ``claimed_too_much`` installs the proposal;
          otherwise a ``restates`` that would not raise the stored memory's standing,
          or a ``contained`` every proposal holder already holds, folds it, with no
          confirmation support among its supports; and otherwise it is installed.
        - **Refused whole**, with nothing written: a placed proposal carrying an
          ``observer_inference`` or ``pinned`` support (§5:10); one marked
          ``assistant_statement`` with no support pointing at a round's message, or
          backed as worded by a support the assistant's statement holds without being
          marked both ``assistant_statement`` and ``occasion`` (§2:4, §8:3); one marked
          ``occasion`` that sets a validity end (§8:4); and one whose validity end lies
          after its create's instant where the support its create cites names no
          about-when at that end (§6:1).

        Args:
            proposal: The candidate memory and why it was proposed. Its ``conflicts``
                are resolved here, not supplied by the caller.

        **What a deferral names** (ADR-0336 §7). The result's ``conflicts`` are every
        conflict the policy ruled against, on every ruling (ADR-0078 §4). On an
        ``ASK_USER`` ruling its ``contradicted`` holds, in the conflict set's order,
        the conflicts in band ``ASSERTED`` the writer holds a ``CONTRADICTS`` relation
        for, computed from the writer's own relations and never read off the ruling;
        on every other ruling it is empty. It is what a caller raises a question on.

        Returns:
            The policy's decision and the id left live, or ``None`` if nothing was
            written.

        Raises:
            UnresolvedEvidenceError: If a support points at an episode the store does
                not hold (§4:7). Nothing is written and the policy is not asked.
            MemoryStoreError: On every other refusal above, or a store failure.
                Nothing is written. ``MemoryStoreStaleError`` where a write met a
                record another writer moved, on each of a bounded number of attempts
                (ADR-0219 §5).
            SelfConsumingWriteError: If an ``ACCEPT`` would install the proposal at an
                id its own supports point at (ADR-0081 §1).
            FoldOntoCitedRecordError: If a ``REINFORCE`` would fold onto a record the
                proposal's supports point at — the only arm a caller may continue past
                (ADR-0116 §2, §4).
        """
        ...

    async def apply(self, change: MemoryChange) -> None:
        """Apply one operation to one stored memory (ADR-0328 §11:3).

        Computes the record the operation yields from the memory the caller read
        (§5's rules, applied by the writer itself) and writes it
        conditionally on that memory's revision (§5:4), so a memory another writer
        moved in between is refused rather than overwritten. An end, a mark wrong or a
        replace naming a successor is written in one atomic write with the
        successor's create (§5:6). Placement, topics and the track record are not
        operations and are not written here (§5:2).

        Every write §4, §5 or §6:5 refuses is refused, with nothing written: a support
        pointing at an episode the store does not hold (§4:7); an operation citing a
        support the memory does not carry once applied (§5:3); a create, which starts
        a memory and is :meth:`ingest`'s (§11:4); a transition §5:7 does not allow; a
        support stopped twice (§5:8); an end whose about-when lies after its instant
        (§5:10); an unrepresentable close (§5:11); and a lower standing overriding a
        higher one (§6:5). An add support whose part the memory already carries
        changes nothing and is not an error (§4:8).

        Args:
            change: The memory as read, the operation, and what it brings with it.

        Raises:
            UnresolvedEvidenceError: If the support it adds, or the successor's,
                points at an episode the store does not hold.
            MemoryStoreStaleError: If the stored memory is not the one read: its
                revision moved, or it is gone. Nothing is written; re-read and
                re-decide.
            MemoryStoreConflictError: If the successor's id names a stored record.
            MemoryStoreError: If any other rule refuses the operation, or a store
                failure. Nothing is written.
        """
        ...

    async def record_use(self, memory: Memory, entry: TrackRecordEntry) -> None:
        """Record one track-record entry on one stored memory (ADR-0329 §14:4).

        Writes ``memory`` with ``entry`` added to its track record, conditionally on
        the revision ``memory`` was read at (ADR-0219 §2), so a memory another writer
        moved in between is refused rather than overwritten. Where ``memory`` already
        carries an entry for ``entry``'s episode, nothing changes and it is not an error
        (ADR-0328 §8:3), the entry already there keeping its fields.

        An entry is not an operation and not a support (ADR-0328 §5:2, §8:4): nothing
        but the track record changes — no support, operation, status, validity, open
        question, placement or label — so the memory's standing is what it was.

        Args:
            memory: The stored memory, as read, revision and all.
            entry: The entry to record.

        Raises:
            MemoryStoreStaleError: If the stored memory is not the one read: its
                revision moved, or it is gone. Nothing is written; re-read and
                re-decide.
            MemoryStoreError: If ``memory`` is not one a store returned (it carries
                no revision), or a store failure. Nothing is written.
        """
        ...

    async def write_labels(self, change: MemoryLabelChange) -> MemoryLabelResult:
        """Replace one stored memory's labels whole (ADR-0345 §7:6).

        Writes ``change.memory`` carrying ``change.labels``, conditionally on the
        revision it was read at (ADR-0219 §2). A label the memory already carries keeps
        its instant, writer and episode; each new one is recorded at the write's
        instant, by ``change.by``, suggested by ``change.episode``. A new label whose
        embedding lies within the composition root's distance of a label the result
        already carries is not added, and the result names it (§7:5). A label write is
        not an operation and changes nothing but the labels (§7:6, §7:9).

        Args:
            change: The memory as read, its new labels, and who writes them.

        Returns:
            The labels the memory now carries, and those refused as near-duplicates.

        Raises:
            MemoryStoreStaleError: If the stored memory is not the one read.
            MemoryStoreError: If the labels break the composition root's bounds, the
                writer was wired with none, or a store failure. Nothing is written.
        """
        ...


@runtime_checkable
class Reader(Protocol):
    """Reads one source and proposes what it read (ADR-0093, ADR-0095 §1).

    The read-only seam: it opens a source the hub can read — a notes vault synced
    onto the box, the maildir a co-located fetcher writes — and returns one bounded
    :class:`~ai_assistant.core.types.SourceReading` of what that source currently
    says. Named for its product role, as every Protocol here is
    (``MemoryWriter``, ``MemoryPolicy``): the role is *reading a source*.

    **It holds no store handle, no writer, no policy and no engine**, which is the
    scope limit rather than a rule about it. An implementation may not write to any
    store, may not read a belief, and may not decide the fate of anything it
    proposes. The alternative — a producer holding a store and choosing what to
    read — would make the scope of ingestion "a property of the producer's code
    rather than of a ratified seam, and every later reviewer would have to
    re-derive it by reading an implementation. Here it is a type" (ADR-0077 §1,
    taken for its own reason rather than by imitation).

    **Nothing it proposes reaches memory on its own** (ADR-0294 §1): scheduled
    ingestion is retired, and a source's content reaches memory only as what an
    activation concludes, through :meth:`MemoryWriter.ingest` and the
    :class:`MemoryPolicy` behind it. A reader inherits no part of ADR-0075's
    capture exemption: a calendar entry is a third party's report, which is the
    definition of the ``ATTESTED`` band, and a band whose whole standing is that
    someone else said it is the last band that should reach the store unmediated
    (ADR-0093 §1).

    **It is never its own caller.** Selecting when a reader runs, and what is done
    with what it returns, are `orchestration`'s (ADR-0093 §1). Its reading's one
    consumer now is the upcoming-event producer (ADR-0319 §7:1); the situational
    context facet and ingestion, which once read it at their own cadences, are
    retired.

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
        """The identity of the **configured source** this reader serves.

        One configured source — one entry in a deployment's configuration for a
        reader type, with its own backing location — and not a reader class, not a
        backing location, and **not this object**: every ``Reader`` the composition
        root builds to serve one configured source returns that source's one
        identity (ADR-0189 §6). It is the only seam a source identity reaches, and
        a grant "keys on nothing else" (ADR-0097 §1).

        It is **Tier 2 / operational** (ADR-0004 §1) and must stay that way, and
        the obligation is stricter here than for a name used only in logs, because a
        reader's identity has a second consumer.
        It is never derived from the source's location or contents — a path,
        filename, address or account identifier may not be used as one, or as any
        part of one — because the identity is what lands on the reading, on
        :attr:`~ai_assistant.core.types.Attestation.reported_by` of every belief
        it proposes and of every one the retired ingestion stored, which stay
        (ADR-0294 §3), in every export, and in every log line, in a system
        whose ADR-0004 §5 rule is that logs never contain Tier 1 data. A reader
        that wraps personal data names *itself* (``"calendar"``), never the data it
        holds (``"alice@example.com calendar"``). It is stated as its own clause
        because "used for logging" has been read as licence before (ADR-0055), and
        here it would be read as licence twice over.

        **Two forms and no third, and never a discriminator on its own** (ADR-0190
        §3, §4). A **declared name** is non-empty,
        UTF-8-encodable, equal to its own ``str.strip()``, and contains no colon. A
        **bare** identity is a declared name and nothing else — ``"calendar"``,
        ``"email"``. A **discriminated** identity is that declared name, one ASCII
        colon, then a discriminator: exactly 32 characters drawn from
        ``0123456789abcdef``. So
        ``"calendar:0f3c9d1a7b45e28c6d90fa3b17e4c852"`` is an identity, while a
        bare discriminator, an empty declared part, an uppercase discriminator, a
        differently-ordered value and a differently-separated one are not
        identities at all. ``ReaderContract`` decides every part of that over the
        value alone; that the declared half is *this reader type's own* declared
        name is the concrete reader's test, because the suite holds a ``Reader``
        and nothing to compare a prefix against (ADR-0190 §3).

        **Which form a source holds is fixed when that source is configured**
        (ADR-0189 §6, ADR-0190 §1). The **first** source of a reader type a
        deployment configures may hold that type's bare declared name; every source
        of that type configured **after** it carries a minted discriminator,
        whether or not the first took the bare name. An identity is assigned once
        and never changes — not across restarts, not when the source is repointed
        at a different backing location, and not when a second source of the type
        is configured beside it — because a re-assignment would orphan every
        ``reported_by`` naming the old value and every grant keyed on it.

        **The type-name half stays the sensor's**, declared and not configurable;
        what a deployment supplies is the discriminator alone (ADR-0190 §1).
        ADR-0093 §7 chose a declared constant because "a free-text setting is
        precisely the mechanism by which a user would put their email address or a
        path there, and no validator can tell a chosen label from a personal one" —
        which still binds the declared half, and still forbids a human-facing label
        settling here (ADR-0189 §5). It does not reach a discriminator, because a
        validator *can* tell 32 hexadecimal characters from an address, so the
        hazard is closed by the shape of the value rather than by a rule about what
        may be typed into it. **ADR-0190 §1 partially supersedes ADR-0093 §7's "not
        a configurable value" clause in exactly that one respect and in no other**;
        §7's remaining identity properties, restated above, are untouched.

        **Stable across calls.** A reader whose identity moved under a read would
        scatter one source's beliefs across two ``reported_by`` values no later
        fold could bring back together — and an identity assigned once at
        configuration cannot move under a read, which is the property this clause
        exists to pin.

        A property rather than a constructor argument: a seam that cannot be asked
        its own name forces every caller to carry one beside it.
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
        ``SourceProposal.sensitivity`` defaults to ``DataTier.PERSONAL``,
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
class Fetcher(Protocol):
    """Lists one configured root, and reads one file of it (ADR-0230 §4).

    The **fetch** seam: it shows what a configured local root currently holds, and
    reads one entry of that listing into a single attested
    :class:`~ai_assistant.core.types.SemanticMemory` carrying the file's own text.
    Named for its product role, as every Protocol here is (``MemoryWriter``,
    ``Reader``): the role is *fetching one named thing, now, for this turn*.

    **It is not a ``Reader`` and reusing that seam was never available.** A
    ``Reader`` performs a whole-source read on its own cadence, bound by its own
    configuration, taking no address at all — and ADR-0093 §10 gives ``read()`` no
    arguments *by decision*. An address is exactly what this contract needs, so it
    is a second seam rather than a widened one.

    **Three members and not two, because the listing is the address space** (§4).
    A contract offering only :meth:`fetch` would need its caller to hold the
    addresses, which is the design ADR-0230 §2 refuses; a contract offering only
    :meth:`listing` cannot deliver a file. The two are one seam because the same
    configuration must govern both — an entry that is shown but not fetchable, or
    fetchable but never shown, is a bug in a place no test would look.

    **Listing membership is a capability this seam mints and verifies, and never a
    claim its caller makes** (§4). A ``Fetcher`` mints a fresh, unguessable
    ``token`` for each listing it produces and a fresh, unguessable ``handle`` for
    each entry of it, both derived from state **private to the fetcher**. Four
    properties are required of the mechanism and its spelling is an
    implementation's, in ADR-0093 §10's own form:

    * a token and a handle are **unforgeable without state private to the
      fetcher**;
    * a handle is **bound to the listing that minted it**;
    * a token **commits to its listing's ordered entry names**, so an authentic
      token cannot be carried onto an altered listing; and
    * verification does **not depend on the fetcher retaining anything**, so no
      listing's validity is a function of how many others have been produced
      since.

    A keyed digest satisfies all four — a per-listing random identifier and the
    listing's ordered entry names signed together with a key generated when the
    fetcher is constructed and never leaving it, each handle signed over that
    identifier, the entry's name and its position — and ADR-0230 §4 names no
    construction as the required one.

    **No token and no handle is rendered to any model, written to any log, put in
    any audit record, or carried on any record a fetch mints** (§4). Either in a
    prompt would be a capability offered to a model, which is the whole of what §2
    exists to prevent.

    **A ``Fetcher`` holds no store, no writer, no policy, no engine and no
    model.** It reads its own configured source and returns what it read. It may
    not write to any store, may not read a belief, and may not decide the fate of
    anything it mints. This is ADR-0093 §1's rule for its own reason: a producer
    that held a store would make the scope of what a fetch can do a property of an
    implementation rather than of a ratified seam.

    **It carries no lifecycle member, deliberately** (§4). A concrete fetcher
    holding an opened root handle exposes a ``close``; this Protocol does not,
    staying free of lifecycle exactly as ``MemoryStore`` and this system's other
    stores do, so the contract keeps saying what a fetch *is* and not who shuts
    one down. ``app/composition.py`` registers that ``close`` among the resources
    it has opened (ADR-0042 §2).

    **Neither member raises for a source reason** (§4). An absent file, an
    unreadable one, an over-size one and a failed extraction are
    :class:`~ai_assistant.core.types.FetchRefusal` members and never exceptions;
    an unreadable root is an empty listing. ADR-0230 adds **no** error class to
    ``core/errors.py``, because there is no failure a caller would handle
    differently from a refusal it must already handle.

    Cancelling either member is governed by this module's cancellation clause
    (ADR-0060), with the one consequence ADR-0230 §4 spells out because it is the
    place a conforming-looking implementation could satisfy every other clause and
    still get it wrong: a call cancelled from outside while suspended re-raises
    ``CancelledError`` and is converted into neither an empty listing nor a
    refusal.
    """

    @property
    def name(self) -> str:
        """The identity of the **configured source** this fetcher serves.

        In :attr:`Reader.name`'s own form and under its own obligation (ADR-0093
        §7, ADR-0189, ADR-0190), and every clause stated there binds here: it is
        **Tier 2 / operational**, it is never derived from the source's location
        or contents — a path, filename, directory name or account identifier may
        not be used as one, or as any part of one — it is assigned once when the
        source is configured and never changes, and it takes one of ADR-0190 §4's
        two forms and no third (a **bare** declared name, or that declared name,
        one ASCII colon and exactly 32 characters drawn from ``0123456789abcdef``).

        It is what ADR-0230 §5 puts in an
        :attr:`~ai_assistant.core.types.Attestation.reported_by`, and what a
        :attr:`~ai_assistant.core.types.SourceListing.source` equals. **The
        attested source is the configured root itself** — "the owner's documents
        folder" and not a vendor, a sender, or a service that synced a file into
        it — so a fetcher that named a document's origin here would be attributing
        a record to a system it cannot see (§5).

        **Stable across calls.** A fetcher whose identity moved under a listing
        would scatter one source's records across two ``reported_by`` values no
        later fold could bring back together, and would orphan every grant keyed on
        the old one.
        """
        ...

    async def listing(self) -> SourceListing:
        """Show what the configured root currently holds, within this fetcher's bound.

        **It takes no arguments, and that is a decision** (ADR-0230 §4, ADR-0093
        §10). The root, the ordering, the entry cap and the type allow-list are the
        fetcher's own configuration, and "a caller able to widen the listing is a
        caller able to defeat every bound behind it". There is no argument through
        which any of them can be moved, so the bound is not merely un-widenable —
        the address space is not reachable from a caller at all.

        **The root's direct children only** (§6): no recursion, no subdirectory
        traversal, no following of symbolic links out of the root. Ordered **most
        recently modified first**, capped at ``fetch_listing_max_entries``, and
        restricted to the formats the implementation supports — a file of any other
        type is **not listed**, so there is no authentic entry naming one.

        **The cap is a truncation and it is a declared one**, which is why it is
        not the case ADR-0093 §5 refuses. That section's objection is that a
        consumer *cannot tell*; a listing states in terms that it is the most
        recently modified entries of the root, up to its cap, and it proposes no
        belief and mints no record.

        Returns:
            One listing. An **empty ``entries`` tuple is a successful listing** —
            and a root that cannot be read produces one too, with no consumer
            distinguishing the two (§6). Its ``token`` is minted fresh, commits to
            the ordered entry names, and carries both of §4's expiry deadlines;
            neither deadline is rendered anywhere and neither outlives the process.

        Raises:
            CancelledError: Re-raised unchanged when the call is cancelled from
                outside, and converted into neither an empty listing nor a refusal
                (ADR-0230 §4).
        """
        ...

    async def fetch(self, listing: SourceListing, entry: SourceListingEntry) -> FetchOutcome:
        """Read the file ``entry`` names, once, and mint one record for it.

        **It takes the listing as well as the entry because the listing is the
        authority the entry's membership is verified against** (§4), and a contract
        in which the caller supplies only the entry has nothing to verify it in.

        **Membership is decided against the authenticated payload and never by
        value equality.** An implementation establishes three things and nothing
        else: that **this** fetcher signed the ``token``, whose payload commits to
        the listing's ordered sequence of entry ``name``s; that the ``handle`` is
        one this fetcher minted **for that listing**, over that entry's ``name``
        and its position; and that the name stands at that position of the
        committed sequence. **The ``entries`` tuple the caller handed in is
        untrusted input rather than evidence** — a caller can put any tuple there
        — so what an implementation does with it is compare its ordered names
        against the sequence the signed payload commits to, and refuse on any
        difference. The tuple is read; it is never believed.

        **What is refused, and what is not.** A listing or an entry this fetcher
        did not mint, an authentic token carried onto an altered ``entries`` —
        emptied, shortened, reordered, or with an entry's ``name`` changed — a
        handle minted for another listing, and a listing past either of §4's
        deadlines are all refused
        :attr:`~ai_assistant.core.types.FetchRefusal.NOT_FOUND`, deliberately the
        same class an absent file yields so that nothing is disclosed about
        whether a guessed name exists under the root. A **faithful copy** of an
        authentic listing and entry is *accepted*, because §4 forbids the fetcher
        retaining anything and an implementation distinguishing a copy would be
        deciding from retained object identity; and a copy whose ``size_bytes`` or
        ``modified_at`` was altered is accepted too, its altered fields ignored,
        because the commitment covers the addresses and not the display.

        **The membership check does not replace the root bound; both bind.** A
        conforming implementation refuses any entry that does not resolve to a
        regular file directly under its configured root, and one that reads outside
        that root for any entry, however that entry was constructed, does not
        conform. The handle establishes *that this fetcher showed it*; the root
        check establishes *that it is still what may be read*, and a bug in either
        is not covered by the other.

        **Resolution and acquisition are one operation, and no bound is decided
        against a path the fetch then re-opens.** A conforming implementation holds
        an **opened directory handle** on its configured root and opens the entry's
        file relative to that handle, by its single final component, without
        following a symbolic link and **without blocking** — the acquiring open is
        non-blocking, because a listed regular file can be replaced by a named pipe
        with no writer and an ordinary read-mode open of one blocks until a writer
        arrives, which is neither a record nor a refusal. It then decides every
        remaining question against the object it has open, never against a path or
        a ``stat`` taken before the open, and every bound is re-applied here rather
        than carried from the listing.

        Args:
            listing: The listing ``entry`` came from — the authority its membership
                is verified against, and the carrier of the token this fetcher
                minted.
            entry: The entry naming the file to read.

        Returns:
            One outcome carrying a record **or** a refusal, never both and never
            neither. A successful fetch mints exactly one ``SEMANTIC`` record whose
            ``content`` is the file's text as extracted, **verbatim** — nothing
            summarises, abridges, rewrites, annotates or classifies it — with
            ``provenance.source`` :attr:`~ai_assistant.core.types.MemorySource.EXTERNAL`,
            an :class:`~ai_assistant.core.types.Attestation` whose ``reported_by``
            is this fetcher's :attr:`name` and whose ``reported_at`` is the instant
            the file was read, and an empty ``evidence`` (ADR-0230 §5).

        Raises:
            CancelledError: Re-raised unchanged when the call is cancelled from
                outside, and converted into neither an outcome nor a refusal
                (ADR-0230 §4).
        """
        ...


@runtime_checkable
class WebSearcher(Protocol):
    """Asks one connected search account a question, and mints what it answers.

    The **search** seam (ADR-0231 §17): it proposes the act — an
    :class:`~ai_assistant.core.types.ActionRequest` for a composed query — and,
    once that act has been authorised, performs it and returns the records the
    provider's answer transcribes. Named for its product role, as every Protocol
    here is: the role is *asking the world this turn's question*.

    **Three members, and the split between the first two is the whole design.**
    :meth:`request` is the proposal and reaches no authorisation conclusion;
    :meth:`search` takes a :class:`~ai_assistant.core.types.ToolCall`, whose own
    validator has already run ADR-0021 §1's ``authorises``, so **an unauthorised
    search is unconstructable at the type level** — ``ToolInvoker.invoke``'s
    guarantee obtained without ``ToolInvoker``. Between them stand the binder, the
    policy and the trail, none of which this contract names (ADR-0231 §6).

    **It is not a registered tool and this seam is why.** ADR-0231 §5 registers
    the search integration at the egress seam against a connected account and in
    **no** ``ToolRegistry``, so it is absent from
    :meth:`ToolRegistry.capabilities` and :meth:`ToolRegistry.all_tools`, and
    un-invocable through the deployment's :class:`ToolInvoker`. Planning reaches
    it by capability all the same: `orchestration`'s phase path offers the
    declaration :meth:`request` proposes beside the registry's, and sends a search
    call to :meth:`search` rather than to the invoker (ADR-0309 §4:2). What a
    search returns is the records it mints, each with its own provenance, and
    never a tool's payload.

    **No member takes a store, a supply or a policy.** Not a
    :class:`~ai_assistant.core.types.MemoryRecord`, not a :class:`MemoryStore`,
    not an :class:`ActionPolicy`, not an :class:`AuditTrail` — and **no later
    lane adds one that does** (ADR-0231 §17). What :meth:`request` is handed is
    one query and nothing else, which is ADR-0231 §11's tenth clause at the second
    seam: a caller holding a record's content has no parameter to put it in.

    **A ``WebSearcher`` holds the credential and this contract never carries
    one.** ADR-0231 §5 puts the ``Secrets`` read at ``SecretScope.INTEGRATION``
    *inside* :meth:`search`, after ADR-0231 §6's three checks have passed — which
    is ADR-0148 §7's positional gate with one word changed. No credential crosses
    this seam in either direction, and no component outside ``tools/`` holds one
    on account of this decision.

    **Neither acting member raises for a source reason** (ADR-0231 §17). A refused
    admission, a failed transport, an expired deadline (ADR-0241 §4), a provider
    that answered something else, an over-large response, an unattested one and an
    empty one are
    :class:`~ai_assistant.core.types.SearchRefusal` members and never exceptions,
    for :class:`Fetcher`'s reason: a closed refusal
    enumeration makes the non-yield a value the audit can count and the turn can
    ignore, where an exception would make ADR-0226 §5's degradation posture the
    servicer's problem to catch correctly at every call site. ADR-0231 adds **no**
    error class to ``core/errors.py``.

    **It carries no lifecycle member, deliberately**, exactly as :class:`Fetcher`
    does: a concrete searcher holding an opened resource exposes a ``close``, and
    ``app/composition.py`` registers that ``close`` among the resources it has
    opened (ADR-0042 §2). The contract keeps saying what a search *is* and not who
    shuts one down.

    Cancelling either acting member is governed by this module's cancellation
    clause (ADR-0060), with the one consequence ADR-0231 §17 spells out because it
    is where a conforming-looking implementation could satisfy every other clause
    and still get it wrong: a call cancelled from outside while suspended
    re-raises ``CancelledError`` and is converted into neither an outcome nor a
    refusal.
    """

    @property
    def name(self) -> str:
        """The identity of the **configured source** this searcher serves.

        In :attr:`Reader.name`'s and :attr:`Fetcher.name`'s own form — a ``str``,
        which keeps #667's one-identifier-contract question exactly where it is —
        and it is what a minted record's
        :attr:`~ai_assistant.core.types.Attestation.reported_by` carries
        (ADR-0231 §10).

        **The attested source is the search source instance** — "the owner's web
        search" — and never a vendor, never an origin, never a URL and never a
        credential (ADR-0092 §3). What it reports is *what its index returns for
        this query now*: not that a page is accurate, not that its author said
        anything at a particular time, and not that a snippet is a faithful
        excerpt of one.

        **Stable across calls, non-blank, and a value
        :data:`~ai_assistant.core.types.Identifier` accepts unchanged** —
        ``name.strip() == name`` (ADR-0231 §17). The stability is
        :attr:`Fetcher.name`'s clause for its reason: an identity that moved under
        a turn would scatter one source's records across two ``reported_by``
        values no later fold could bring back together. The stripping clause is
        this seam's own, and it is stated rather than left implicit because §10
        requires ``reported_by`` and this value to be **equal**: ``reported_by``
        is typed ``Identifier``, which refuses a blank value *and strips the one
        it accepts*, so a searcher naming itself ``" search "`` would be
        conforming and yet mint a record whose ``reported_by`` is ``"search"`` —
        an equality this ADR asserts that no implementation could then satisfy.
        """
        ...

    async def request(self, query: NonBlankEncodableText, /) -> ActionRequest | None:
        """Propose the search this query would make, or answer that there is none.

        **The parameter is positional-only, and that is a decision**
        (ADR-0231 §17): no keyword
        name of it exists for a caller to pass a second value under, and no
        implementation may rename it into a wider one.

        **It reads no store, mints no identifier, opens no channel and reaches no
        authorisation conclusion** (ADR-0231 §17). Everything between this member
        and :meth:`search` — the binding, the ruling, the audit record and the
        construction of the ``ToolCall`` — belongs to the caller (ADR-0231 §6),
        and an implementation deciding any of it here would be answering a
        question the policy has not been asked.

        Args:
            query: The query to search for (ADR-0231 §11). Non-blank and
                UTF-8-encodable. It is the whole of what an implementation is given.

        Returns:
            The request to rule on — carrying this searcher's own declaration as
            :attr:`~ai_assistant.core.types.ActionRequest.tool`, exactly the origin
            and the query as
            :attr:`~ai_assistant.core.types.ActionRequest.parameters`, and ``None``
            for ``egress_binding`` (ADR-0231 §17). Or
            ``None`` where the deployment has connected no search account, which is
            a configuration fact and never a failure.

        Raises:
            CancelledError: Re-raised unchanged when the call is cancelled from
                outside while suspended (ADR-0060, ADR-0231 §17).
        """
        ...

    async def search(self, call: ToolCall, /, *, timeout: timedelta) -> SearchOutcome:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, §2); a caller wrapping this in `asyncio.timeout` cancels the searcher mid-await and cannot classify its own expiry
        """Perform the authorised search, and mint what its answer transcribes.

        **It takes a ``ToolCall`` and never an ``ActionRequest``**, so an
        unauthorised search is unconstructable at the type level (ADR-0231 §17).
        Construction is the first line and not the only one: ADR-0231 §6 requires
        this member to revalidate and detach the call, compare its definition
        against the searcher's **own registered declaration** — the authoritative
        original here, standing where ADR-0029 §2 puts the registry's, because
        this integration has an egress registration and no registry entry — and
        re-evaluate ``PermissionDecision.authorises`` against that same detached
        copy, in that order and before the credential is read or any channel is
        opened.

        **What else the implementation owes, in ADR-0231's own order**: the
        invocation deadline ``timeout`` states (ADR-0241 §1); ADR-0194 §3's spend
        admission, after those three checks and before the ledger claim, over the
        ``ToolCost`` on the revalidated copy; ADR-0192's claim and completion
        around the send, on every exit it observes; ADR-0148 §6's one-step
        credential read and its post-read discard; and ADR-0231 §10's
        transcription and minting. Only the deadline is visible in this signature,
        which is why §6 states the rest.

        **The bound is the caller's and there is no spelling for "unbounded"**
        (ADR-0241 §1). ``timeout`` is required, has no default and admits no
        ``None``, so every call declares one — ADR-0029 §4's rule at this seam
        verbatim, and for its reason: a default would be ``core`` choosing a
        policy and a nullable one would be a documented route to an unbounded
        call. How long a turn may wait is a property of the turn, so the figure is
        a parameter rather than a searcher's property.

        **The deadline is enforced inside this member** (ADR-0241 §2), never by a
        decorating ``WebSearcher`` a composition root interposes and never by a
        caller wrapping this call in ``asyncio.timeout``. An outer cancellation
        cannot classify its own expiry without performing the
        cancellation-to-outcome conversion the clause below forbids, and it stands
        outside the claim and the spend admission that an expiry has to account
        for.

        **The bound covers this seam's own work and not the send alone** — the
        revalidation, ADR-0194 §3's spend admission, the credential read, the
        channel, the response read and the transcription (ADR-0241 §1). It is
        **not** placed over either ledger append: ADR-0192 §3 pins the claim and
        the completion *"unbounded by this seam"*, and no lane closes that gap by
        wrapping either append in this deadline. So the guarantee is the weaker,
        true one — the seam stops waiting on the stages it owns — and no total is
        claimed for a ``search`` frame.

        **The parameter is a duration and nothing else, and no lane widens it**
        (ADR-0241 §1): not a deadline instant, not a clock, not a budget object,
        not a policy and not a carrier for a second value. ADR-0231 §17's clause
        that no member of this Protocol takes a ``MemoryRecord``, a supply, a
        ``MemoryStore``, an ``ActionPolicy`` or an ``AuditTrail`` binds verbatim.

        Args:
            call: The authorised call, whose ``request`` carries this searcher's
                declaration, the origin and the query, and whose ``decision`` is
                the recorded ``ALLOW`` that authorises them. Read only through the
                revalidated copy the implementation makes of it, never as handed.
            timeout: How long this call may take over the stages above. **Required,
                keyword-only, and strictly positive** (ADR-0241 §1). The
                annotation is not the enforcement, so an implementation checks the
                value: see ``Raises`` below.

        Returns:
            One outcome carrying records **or** a refusal, never both and never
            neither — a condition
            :class:`~ai_assistant.core.types.SearchOutcome` enforces itself. A
            successful search mints at most ``search_max_results`` ``SEMANTIC``
            records, in the order the provider returned the results they
            transcribe, each ``EXTERNAL``-sourced with an empty ``evidence`` and an
            :class:`~ai_assistant.core.types.Attestation` whose ``reported_by`` is
            this searcher's :attr:`name` and whose ``reported_at`` is the instant
            **the provider's response declared** (ADR-0231 §10, ADR-0092 §3).

            **An expiry of ``timeout`` is
            :attr:`~ai_assistant.core.types.SearchRefusal.DEADLINE_EXPIRED`** and
            never :attr:`~ai_assistant.core.types.SearchRefusal.TRANSPORT_FAILED`
            (ADR-0241 §4): it is returned like every other member and raised for
            no source reason. Classification keys on **this** deadline having
            fired and never on catching an exception type, so a ``TimeoutError``
            an upstream library raises for its own reasons inside the bound stays
            ``TRANSPORT_FAILED`` (ADR-0241 §7).

        Raises:
            ValueError: If ``timeout`` is not a ``timedelta``, or is not strictly
                positive — refused **before** the call is revalidated, before the
                credential is read, before the spend gate is consulted and before
                any channel is opened, so a refused value reaches no store, appends
                no claim and opens nothing (ADR-0241 §1). Zero and negative
                durations are refused rather than treated as instantly expired, for
                ADR-0029 §4's reason: expiry is delivered at an await point, so an
                implementation reading "expired" as "do not call" would be making a
                promise the event loop does not keep.
            CancelledError: Re-raised unchanged when the call is cancelled from
                outside while suspended, and converted into neither an outcome nor
                a refusal (ADR-0060, ADR-0231 §17). **Unchanged by ADR-0241**
                (§7): ``DEADLINE_EXPIRED`` is never returned for a cancellation the
                seam did not itself issue, and a cancellation that interrupted the
                call completes the ledger claim with the declaration's
                ``interrupted_outcome`` and an ``UNKNOWN`` cost before it re-raises.
        """
        ...


@runtime_checkable
class Forecaster(Protocol):
    """Asks one configured outside source what it says about the days ahead.

    The **forecast** seam (ADR-0260 §1, §4): it proposes the act — an
    :class:`~ai_assistant.core.types.ActionRequest` carrying its own declaration —
    and, once that act has been authorised, performs it and returns one record per
    day the provider's answer described. Named for its product role, as every
    Protocol here is: the role is *asking a configured outside source what it says
    about the days ahead*.

    **Three members, and the split between the first two is :class:`WebSearcher`'s**
    (§4). :meth:`request` is the proposal and reaches no authorisation conclusion;
    :meth:`read` takes a :class:`~ai_assistant.core.types.ToolCall`, whose own
    validator has already run ADR-0021 §1's ``authorises``, so **an unauthorised
    forecast read is unconstructable at the type level** — ``ToolInvoker.invoke``'s
    guarantee obtained without ``ToolInvoker``. Between them stand the binder, the
    policy and the trail, none of which this contract names (§6).

    **The ask carries nothing, and that is this kind's whole safety mechanism**
    (§3). :meth:`read` takes no query, no window, no place and no coordinate: the
    place is the deployment's own configured place and the horizon is the
    forecaster's own bound, so **no place crosses the planning seam in either
    direction** and a caller able to widen the read does not exist. That is
    ADR-0093 §10's rule honoured rather than worked around, at a seam that does take
    a call.

    **It is not a** :class:`Reader` (§1). ``Reader`` is untouched: its
    no-arguments rule, ADR-0095's placement ruling and every clause governing
    ``readers/`` bind exactly as they do today, ``ai_assistant.readers`` gains
    nothing from this decision, and no lane widens ``Reader.read``, adds an argument
    to it or adds a member to it. **It is not a context facet** either:
    ADR-0252 §3 rules that no facet produces an evidence row and ADR-0096 §3 bars
    one from a carried-over reading, and a forecast read's whole purpose is the
    evidence row it writes.

    **It is not a registered tool, and the route is closed at the type rather than
    by a rule** (§1). The integration is registered at the egress seam against the
    configured connection and in **no** ``ToolRegistry``, exactly as ADR-0231 §5
    registers the search: absent from :meth:`ToolRegistry.capabilities` and
    :meth:`ToolRegistry.all_tools`, unreachable by any plan step, and un-invocable
    through :class:`ToolInvoker`. ADR-0208 §1 is satisfied by not being a tool, and
    ADR-0170 §5a's "a tool's result is a JSON payload with no per-span provenance"
    is not approached.

    **No member takes a store, a supply, a policy, a trail or a record** (§4). Not a
    :class:`~ai_assistant.core.types.MemoryRecord`, not a :class:`MemoryStore`, not
    an :class:`ActionPolicy`, not an :class:`AuditTrail` — and **no later lane
    adds one that does**.

    **This contract never carries a credential** (§4). No credential crosses this
    seam in either direction, and none is in a binding. **The production forecaster
    holds none and reads none** (ADR-0344 §3): its transport holds no ``Secrets``
    face, and its connection is made by ADR-0325's keyless act, which supplies an
    identity alone. Any ``Secrets`` read is at ``SecretScope.INTEGRATION`` *inside*
    :meth:`read`, after the checks §6 names have passed — ADR-0148 §7's positional
    gate with one word changed. **This seam claims no exemption from the connection
    model and decides no new connection shape**: §6's binding still needs the
    ``ACTIVE`` record ``Settings.forecast_connection`` names.

    **Neither acting member raises for a source reason** (§4). A failed transport,
    an expired deadline, an over-large response, a provider that answered something
    else, an unattested response and one describing no usable day are
    :class:`~ai_assistant.core.types.ForecastRefusal` members and never exceptions,
    for :class:`Fetcher`'s and :class:`WebSearcher`'s reason: a closed refusal
    enumeration makes the non-yield a value the audit can count and the turn can
    ignore, where an exception would make ADR-0226 §5's degradation posture the
    servicer's problem to catch correctly at every call site. ADR-0260 adds **no**
    error class to ``core/errors.py``.

    **It carries no lifecycle member, deliberately** (§4), exactly as
    :class:`Fetcher` and :class:`WebSearcher` do: a concrete forecaster holding an
    opened resource exposes a ``close``, and ``app/composition.py`` registers that
    ``close`` among the resources it has opened (ADR-0042 §2). The contract keeps
    saying what a forecast read *is* and not who shuts one down.

    **A BREAKING contract change under golden rule 5**, landing with its shared
    conformance suite and its canonical fake in :mod:`ai_assistant.testing`
    (``CONTRIBUTING.md`` -> "Adding a Protocol").

    Cancelling either acting member is governed by this module's cancellation clause
    (ADR-0060), with the one consequence §4 spells out because it is where a
    conforming-looking implementation could satisfy every other clause and still get
    it wrong: a call cancelled from outside while suspended re-raises
    ``CancelledError`` and is converted into neither an outcome nor a refusal.
    """

    @property
    def name(self) -> str:
        """The identity of the **configured source** this forecaster serves.

        In :attr:`Reader.name`'s, :attr:`Fetcher.name`'s and
        :attr:`WebSearcher.name`'s own form — a ``str``, which keeps #667's
        one-identifier-contract question exactly where it is — and it is what a
        minted record's
        :attr:`~ai_assistant.core.types.Attestation.reported_by` carries and what
        ADR-0252 §1's ``source`` field carries (ADR-0260 §4, §9).

        **The attested source is the forecast source instance** — "the owner's
        forecast" — and never a vendor, never an origin, never a URL, never a
        credential and **never a place** (ADR-0092 §3, ADR-0260 §4). What it reports
        is *what this provider's forecast says for these days now*: not that the
        weather will be so, not that the forecast is accurate, and not that anything
        it names has happened.

        **Stable across calls, non-blank, and a value
        :data:`~ai_assistant.core.types.Identifier` accepts unchanged** —
        ``name.strip() == name``. The stability is :attr:`Fetcher.name`'s clause for
        its reason: an identity that moved under a turn would scatter one source's
        records across two ``reported_by`` values no later fold could bring back
        together. The stripping clause is this seam's own and is stated rather than
        left implicit because §5 requires ``reported_by`` and this value to be
        **equal**: ``reported_by`` is typed ``Identifier``, which refuses a blank
        value *and strips the one it accepts*, so a forecaster naming itself
        ``" forecast "`` would be conforming and yet mint a record whose
        ``reported_by`` is ``"forecast"`` — an equality this ADR asserts that no
        implementation could then satisfy.
        """
        ...

    async def request(self) -> ActionRequest | None:
        """Propose the forecast read this deployment's configuration would make.

        **It takes no arguments, and that is the decision rather than an omission**
        (ADR-0260 §3, §4). There is no parameter through which a caller could name a
        place, widen a horizon or compose a window, so the failure mode ADR-0231 §1
        is built against is unreachable rather than forbidden. No later lane adds
        one without the ADR that decides it.

        **It reads no store, mints no identifier, opens no channel and reaches no
        authorisation conclusion** (§4, §6). Everything between this member and
        :meth:`read` — the binding, the ruling, the audit record and the
        construction of the ``ToolCall`` — belongs to the caller, and an
        implementation deciding any of it here would be answering a question the
        policy has not been asked.

        Returns:
            The request to rule on — carrying this forecaster's own declaration as
            :attr:`~ai_assistant.core.types.ActionRequest.tool`, the arguments its
            own registered schema declares, and ``None`` for ``egress_binding``
            (the binding is derived by :class:`EgressBinder` and accepted from
            nobody). Or ``None`` where the deployment has configured no forecast
            provider, **which is a configuration fact and never a failure**.

        Raises:
            CancelledError: Re-raised unchanged when the call is cancelled from
                outside while suspended (ADR-0060, ADR-0260 §4).
        """
        ...

    async def read(self, call: ToolCall, /, *, timeout: timedelta) -> ForecastOutcome:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, §2); a caller wrapping this in `asyncio.timeout` cancels the forecaster mid-await and cannot classify its own expiry
        """Perform the authorised forecast read, and mint what its answer describes.

        **It takes a ``ToolCall`` and never an ``ActionRequest``**, so an
        unauthorised forecast read is unconstructable at the type level (ADR-0260
        §4). Construction is the first line and not the only one: §6 requires this
        member to perform ADR-0029 §2's three pre-execution checks **itself, in that
        order** — revalidate and detach the call; compare its definition for
        equality against the forecaster's **own registered declaration**, the
        authoritative original here, standing where ADR-0029 §2 puts the registry's,
        because this integration has an egress registration and no registry entry;
        and re-evaluate ``PermissionDecision.authorises`` against that same detached
        copy. Every subsequent step reads the revalidated copy and never the
        argument, and a failure at any of the three raises
        :class:`~ai_assistant.core.errors.ToolBindingError`, carrying **no**
        ``ForecastRefusal`` because it is no outcome of the read.

        **What else the implementation owes, in ADR-0260's own order**: the
        invocation deadline ``timeout`` states (ADR-0241 §1); ADR-0148 §6's
        one-step credential read, its four pre-transmit conditions and its post-read
        discard; the **one** provider request §3 allows; and §5's transcription and
        minting. Only the deadline is visible in this signature, which is why §6
        states the rest.

        **One ask is one read** (§3). No implementation issues two provider requests
        for one call, follows a link out of a response, requests a further page,
        re-issues with a different window, or retries a refused or failed request:
        there is no pagination, no depth and no traversal of any kind, on **any**
        outcome.

        **The bound is the caller's and there is no spelling for "unbounded"**
        (ADR-0241 §1). ``timeout`` is required, has no default and admits no
        ``None``, so every call declares one. How long a turn may wait is a property
        of the turn, so the figure is a parameter rather than a forecaster's
        property, and ADR-0260 §11 adds no second deadline figure of its own.

        **The deadline is enforced inside this member** (ADR-0241 §2), never by a
        decorating ``Forecaster`` a composition root interposes and never by a caller
        wrapping this call in ``asyncio.timeout``: an outer cancellation cannot
        classify its own expiry without performing the cancellation-to-outcome
        conversion the clause below forbids.

        **The parameter is a duration and nothing else, and no lane widens it**
        (ADR-0241 §1): not a deadline instant, not a clock, not a budget object, not
        a policy, not a horizon and not a carrier for a second value.

        Args:
            call: The authorised call, whose ``request`` carries this forecaster's
                declaration and the arguments its schema declares, and whose
                ``decision`` is the recorded ``ALLOW`` that authorises them. Read
                only through the revalidated copy the implementation makes of it,
                never as handed.
            timeout: How long this call may take over the stages above. **Required,
                keyword-only, and strictly positive** (ADR-0241 §1). The annotation
                is not the enforcement, so an implementation checks the value: see
                ``Raises`` below.

        Returns:
            One outcome carrying records **or** a refusal, never both and never
            neither — a condition
            :class:`~ai_assistant.core.types.ForecastOutcome` enforces itself. A
            successful read mints **one record per day the provider's answer
            covers** and §5 keeps, in the order the provider returned them and at
            most ``forecast_max_days`` of them taken **from the front**; each is
            ``SEMANTIC``, ``EXTERNAL``-sourced, carries empty ``evidence``, empty
            ``topics``, no ``about_person``, a **fully open** ``validity``, and an
            :class:`~ai_assistant.core.types.Attestation` whose ``reported_by`` is
            this forecaster's :attr:`name`, whose ``reported_at`` is the instant
            **the provider's response declared**, and whose
            :class:`~ai_assistant.core.types.ReportedExtent` is the day that record
            is about, computed from the day the provider named and the UTC offset
            the provider's own response declared for it — **and from nothing else**
            (§5, ADR-0117 §2, ADR-0092 §3).

            **An expiry of ``timeout`` is
            :attr:`~ai_assistant.core.types.ForecastRefusal.DEADLINE_EXPIRED`** and
            never
            :attr:`~ai_assistant.core.types.ForecastRefusal.TRANSPORT_FAILED`
            (ADR-0241 §4): it is returned like every other member and raised for no
            source reason. Classification keys on **this** deadline having fired and
            never on catching an exception type, so a ``TimeoutError`` an upstream
            library raises for its own reasons inside the bound stays
            ``TRANSPORT_FAILED`` (ADR-0241 §7).

        Raises:
            ValueError: If ``timeout`` is not a ``timedelta``, or is not strictly
                positive — refused **before** the call is revalidated, before any
                credential is read and before any channel is opened (ADR-0241 §1,
                ADR-0260 §4). Zero and negative durations are refused rather than
                read as instantly expired, for ADR-0029 §4's reason: expiry is
                delivered at an await point, so an implementation reading "expired"
                as "do not call" would be making a promise the event loop does not
                keep.
            ToolBindingError: If the call does not survive revalidation, carries a
                definition unequal to this forecaster's registered original, or is
                not authorised by its decision (ADR-0029 §2, ADR-0260 §6). **No
                credential is read and no channel is opened for any of them**, and
                none carries a ``ForecastRefusal``: a binding failure establishes
                no contact. ADR-0148 §6's own
                pre-transmit refusals are different and are **returned**, as
                :attr:`~ai_assistant.core.types.ForecastRefusal.PROVIDER_REFUSED` —
                one fault classified two ways at two seams is what ADR-0264 §13's
                third arm exists to catch.
            CancelledError: Re-raised unchanged when the call is cancelled from
                outside while suspended, and converted into neither an outcome nor a
                refusal (ADR-0060, ADR-0260 §4). **Never converted into
                ``DEADLINE_EXPIRED``** (ADR-0241 §7): a cancellation this seam did
                not itself issue is not its expiry.
        """
        ...


@runtime_checkable
class PlanStore(Protocol):
    """Durable planning state: stop, effect and observation records, and scheduled tasks.

    Planning owns this rather than the wiring layer, because plan state is
    personal data and carries ADR-0004's obligations (ADR-0014 §5). Implementations
    persist **locally only**; none may write plan state to a remote service.

    **Seven members are what the phases use**, and ADR-0309 §5 retires the rest: the
    goal, attempt, interpretation, intended-action, quote, question and evidence
    members, the execution members, and ``claim_effect``. :meth:`record_stop` writes
    a stop record, :meth:`claim_activation_effect` and
    :meth:`finish_activation_effect` write an activation's effect records,
    :meth:`activation_effects` reads them back by activation and :meth:`part_effects`
    by question part (ADR-0321 §4:4, §4:11), and :meth:`export` and :meth:`clear`
    carry ADR-0004 §6's data rights. Each of those writes is a **command and not a
    snapshot**, on ADR-0014 §5's argument: each names the change it makes, and none
    takes a stored record back in order to write it.

    **Three more are the observer's** (ADR-0329 §16:9): :meth:`write_observation`
    writes an episode's observation record, :meth:`observations` reads records by
    episode id, and :meth:`observer_calls_since` counts the model calls they record
    since an instant, for the observer's daily budget. The observation record is the
    one record here written whole, because it is the observer's own account of an
    episode rather than a fact another member decides; it is written **conditionally
    on the revision the writer read**, so two writers cannot both land a record
    computed from one state (ADR-0329 §16:6's backstop, in ADR-0219 §2's shape).

    **Fourteen more hold the Task Scheduler's content** (ADR-0350 §12:3): the scheduled
    tasks every spawn writes, with their occurrences. No stop writes a cascade record
    and nothing refuses a push below a stopped activation (ADR-0352 §2:2-§2:3); a
    stopped activation's spawns are refused on its stop record (ADR-0350 §3:3).
    :meth:`write_scheduled_task` writes a task with its spawn's effect claim and
    the limits' checks in one step, cancelling a task it replaces in that step and
    spending a ticket the spawn runs under in it (ADR-0362 §3:1);
    :meth:`cancel_scheduled_task` cancels one; :meth:`scheduled_tasks`,
    :meth:`person_scheduled_tasks`, :meth:`spawned_tasks` and :meth:`scheduled_lineage`
    read them by id, by person and state, by parent and by lineage; :meth:`live_below`
    reads whether anything below a task is live; :meth:`due_occurrences` reads what is
    due; :meth:`mark_occurrence_pushed` and :meth:`settle_occurrence` move an occurrence
    from pending to pushed to its outcome; :meth:`stop_pushed_activation` and
    :meth:`stopped_activations` write and read the stop record of a pushed id;
    :meth:`confirm_message_effect`
    settles a message's record from its place's confirmation after a restart; and
    :meth:`remove_scheduled_task` removes a task once nothing of it or below it is live.
    Each write is one indivisible step, so a cancel and a push, or two spawns of one
    round, are totally ordered (§7:5, §9:9). The Task Scheduler is a medium the hub
    hosts, and none of it is the assistant's memory (§2:3, §4:2).

    **Twelve more hold the Approvals channel's content** (ADR-0361 §8:2): the approval
    requests ``request_approval`` writes, each with its ticket (§3:2, §5).
    :meth:`write_approval_request` writes a request with ``request_approval``'s effect
    claim and §2:8's duplicate check in one step; :meth:`approval_requests`,
    :meth:`person_approval_requests` and :meth:`approval_request_by_token` read requests
    by id, by person and state, and by a card's token (§4:10);
    :meth:`record_approval_card` records a card and its token; :meth:`answer_approval_request`
    marks a pending request answered by a tap, the first to land winning (§4:9), and
    :meth:`expire_approval_request` ends one expired or voids its held ticket at its expiry
    (§3:5); :meth:`void_approval_ticket` makes a held ticket void (§5:7);
    :meth:`due_approval_outcomes` and :meth:`pushed_approval_outcomes` read the outcomes
    due to be pushed and those marked pushed, and :meth:`mark_approval_outcome_pushed`
    marks one pushed, naming its activation (§3:4, §3:7); and :meth:`claim_ticket_call`
    claims a call under a ticket, keyed by its request, spending it (§5:5), except a
    spawn's, which :meth:`write_scheduled_task` claims and spends in its own step
    (ADR-0362 §3:1, §3:3). **The store
    computes no instant**: a request's expiry, a tap's instant and an expiry's are the
    caller's, and a claim is decided at the instant its record was claimed at. The
    Approvals channel is a medium the hub hosts, and none of it is the assistant's memory
    (§3:1).

    **A task the person set may hold a rule** (ADR-0340 §4, §9:3), and then holds more
    than one occurrence over its life. :meth:`write_scheduled_task` writes its first
    occurrence at the instant its spawn carries; :meth:`mark_occurrence_pushed`, at an
    occurrence's first push, writes the next one at the instant the caller gives, with
    any it records skipped, in the step that marks it pushed, so a rule holds a pending
    occurrence until it ends; and :meth:`cancel_scheduled_task` ends it. **The store
    computes no instant** (§9:5): the rule's arithmetic is its callers' one function,
    and the store writes what they computed.

    **The stop record lives here and in no other store** (ADR-0297 §1, §2, §6):
    :meth:`record_stop` writes a record naming one activation, and an effect claim
    naming that activation is then refused with
    :class:`~ai_assistant.core.errors.ClaimStopped`. The claim it must refuse is
    decided here, and only the store that decides a claim holds a total order over
    it (ADR-0014 §5) — so whichever of a stop and a claim lands first wins, and there
    is no third case.

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060).
    """

    async def record_stop(self, activation_id: str, /) -> None:
        """Write a stop record naming ``activation_id`` (ADR-0297 §1).

        **One indivisible step**, writing that record and nothing else; from then on
        :meth:`claim_activation_effect` refuses every claim naming the activation with
        :class:`~ai_assistant.core.errors.ClaimStopped`.

        **Idempotent**: recording a stop for an activation the store already holds one
        for writes nothing and raises nothing. **It refuses no activation id on the
        ground that the store does not know it**, since the store knows nothing of
        which activations ran; a value that is not an identifier at all is not an
        activation id, and is refused as the bad input it is.

        **The record carries the activation id alone** — no instant, no reason, no
        conversation and no content; when the user stopped is recorded where the user
        reads it, as the episode's end entry. **No record is removed while the store
        holds its rows**: there is no expiry, sweep or release member, and the only
        route out is :meth:`clear`, which erases every record. :meth:`export` carries
        every record as :attr:`~ai_assistant.core.types.PlanExport.stopped_activations`.

        Raises:
            PlanningError: If ``activation_id`` is not an identifier, or the backend
                fails.
        """
        ...

    async def claim_activation_effect(
        self,
        effect: ActivationEffect,
        /,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool = False,
    ) -> ActivationEffectClaim:
        """Claim one effect of an activation by writing its record (ADR-0306 §5:4, §6:2).

        **One indivisible step**, which decides the stop, the duplicate backstop and
        the write together. A call or a message that gets an effect record is claimed
        here before it runs, with no outcome and, for a message, no position.

        In this order:

        1. **The stop.** Where the store holds a stop record for
           ``effect.activation_id`` (ADR-0297 §1), it raises ``ClaimStopped`` and
           writes nothing.
        2. **The id.** Where the store already holds a record under ``effect.id``, it
           raises ``PlanningError`` and writes nothing.
        3. **The spend.** Where ``effect.part`` is set, the call runs under an
           approval and the part is its key (ADR-0321 §4:9). Where a record of **any**
           activation already carries that part, whatever its outcome, it answers
           ``ALREADY_USED`` and writes nothing, so two yeses to one part cannot both
           run. ``match`` does not narrow this step.
        4. **The backstop.** Where ``match`` is a tuple, and a record of an
           activation it names carries the same capability and values digest with an
           outcome that is unknown, not yet written, or done, it answers
           ``ALREADY_DONE`` and writes nothing. A record not done never matches, and a
           message never matches. A deliberate repeat passes a done record; and a
           deliberate repeat that runs under an approval, ``effect.part`` set, also
           passes one whose outcome is unknown or not yet written (ADR-0321 §6:2).
        5. Otherwise it writes ``effect`` and answers ``CLAIMED``.

        **The store reads no story** (§6:3). ``orchestration`` supplies ``match``: for a
        call to a capability that is not safe to repeat, this activation's id and the
        activations of the episodes in its stories, taken when the round was
        authorized; for every other claim, ``None``, which matches nothing.

        Args:
            effect: The record to write. It carries no outcome, no reason and no
                position; its ``part`` is the claim's part key where the call runs
                under an approval, and ``None`` otherwise.
            match: The activations whose effects this claim is matched against, or
                ``None``.
            deliberate_repeat: Whether planning marked the call a deliberate repeat,
                which passes a matching effect that is done, and, where the call runs
                under an approval, one whose outcome is unknown or not yet written.

        Returns:
            ``CLAIMED`` where the record was written; ``ALREADY_USED`` where a record
            already carries the part key; ``ALREADY_DONE`` where a matching effect
            refused it.

        Raises:
            ClaimStopped: If the store holds a stop record for the activation.
            PlanningError: If the store already holds a record under the id, the
                record carries an outcome, a reason or a position, or a ticket or a
                request (ADR-0361: :meth:`claim_ticket_call` and
                :meth:`write_approval_request` claim those), ``match`` names an id with
                no UTF-8 encoding, or the backend fails. Nothing is written.
        """
        ...

    async def finish_activation_effect(
        self,
        effect_id: str,
        /,
        outcome: ToolOutcome,
        *,
        reason: str | None = None,
        position: int | None = None,
    ) -> None:
        """Write a claimed effect's outcome, once (ADR-0306 §5:5, §6:4).

        Writes the outcome, the reason where it is not done, and, for a message done,
        the position the medium returned for it, in one step.

        Args:
            effect_id: The record to finish.
            outcome: ``SUCCEEDED`` for done, ``FAILED`` for not done,
                ``INDETERMINATE`` for unknown.
            reason: Why the effect was not done; only with ``FAILED``.
            position: Where the medium recorded a message; only on a message done.

        Raises:
            PlanningError: If ``effect_id`` is not an identifier, the store holds
                no record under ``effect_id``, the record is already finished, the
                reason is blank or has no UTF-8 encoding, a reason rides on an
                outcome other than ``FAILED``, a position on anything but a message
                done, or the backend fails. Nothing is written.
        """
        ...

    async def activation_effects(
        self, activation_ids: Sequence[str], /
    ) -> tuple[ActivationEffect, ...]:
        """Return the effect records of the named activations (ADR-0306 §6:5).

        Finished or not, in the order they were claimed. An activation the store
        holds no record of contributes nothing.

        Args:
            activation_ids: The activations whose records to return.

        Returns:
            The records, in claim order.

        Raises:
            PlanningError: If ``activation_ids`` is a bare string, or not a sequence
                of strings, names an id with no UTF-8 encoding, or the backend fails.
        """
        ...

    async def part_effects(self, parts: Sequence[QuestionPart], /) -> tuple[ActivationEffect, ...]:
        """Return the effect records that carry any of ``parts``, of any activation.

        The read side of the claim's part key (ADR-0321 §4:9). Authorizing's *not
        already run* fact asks whether any record carries a part's key (§4:4), and the
        repeat check whether a part a call was asked about has been used (§4:11). A
        part may be spent in an activation no story of the reader's reaches, so this
        reads across every activation, which :meth:`activation_effects` does not.

        Finished or not, in the order they were claimed. A part no record carries
        contributes nothing, and the store holds at most one record per part, since
        :meth:`claim_activation_effect` writes none for a part already carried.

        Args:
            parts: The question parts to look for.

        Returns:
            The records carrying them, in claim order.

        Raises:
            PlanningError: If ``parts`` holds anything but a ``QuestionPart``, or the
                backend fails.
        """
        ...

    async def write_observation(
        self, record: ObservationRecord, /, *, expected_revision: int
    ) -> ObservationRecord:
        """Write an episode's observation record whole, conditionally (ADR-0329 §16:9).

        **One indivisible step**, which reads the record the store holds for
        ``record.episode`` and writes the new one only where it matches the
        expectation: ``expected_revision`` is ``0`` where the writer read no record,
        and the held record's revision where it read one. Otherwise it raises and
        writes nothing — a record held where none was expected, none held where one
        was, or one held at another revision.

        The written record is stamped with a fresh revision, positive and **never
        issued before by this store** — :meth:`clear` included, which erases records
        and never the issuer, so a revision read before a clear can never match a
        record written after it. The submitted ``revision`` is discarded. The store
        rules on nothing else: what a record holds is the observer's, and the type
        refuses a malformed one.

        Args:
            record: The record to write.
            expected_revision: The revision of the record the writer read, or ``0``
                where it read none.

        Returns:
            The record as stored, carrying its new revision.

        Raises:
            PlanningError: If ``record`` is not a valid ``ObservationRecord``,
                ``expected_revision`` is not a non-negative integer, the held record
                does not match it, or the backend fails. Nothing is written.
        """
        ...

    async def observations(self, episode_ids: Sequence[str], /) -> tuple[ObservationRecord, ...]:
        """Return the observation records held for the named episodes (ADR-0329 §16:9).

        Each with the revision the store holds for it, in the order the episodes are
        named, each once. An episode the store holds no record for contributes
        nothing, so a due episode with none is one never attempted — or one whose
        record :meth:`clear` erased, which is processed again (§16:9).

        Args:
            episode_ids: The episodes whose records to return.

        Returns:
            The records.

        Raises:
            PlanningError: If ``episode_ids`` is a bare string, or not a sequence of
                strings, names an id with no UTF-8 encoding, or the backend fails.
        """
        ...

    async def observer_calls_since(self, since: datetime, /) -> int:
        """Count the model calls the observation records hold at or after ``since``.

        ADR-0329 §16:9's budget reads the calls made in any 24 hours. Every call an
        attempt recorded counts, whatever the record's state, and :meth:`clear`
        erases them with the records that hold them.

        Args:
            since: The instant to count from, timezone-aware.

        Returns:
            The count.

        Raises:
            PlanningError: If ``since`` is not a timezone-aware instant, or the
                backend fails.
        """
        ...

    # --- the Task Scheduler's scheduled tasks (ADR-0350 §12:3) ---------------

    async def write_scheduled_task(  # noqa: PLR0913 — the spawn, its effect claim's three, the replace's rule and §9:7-§9:8's two limits
        self,
        spawn: TaskSpawn,
        effect: ActivationEffect,
        /,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool = False,
        replace_any: bool = False,
        chain_limit: int,
        pending_limit: int,
    ) -> ScheduledTaskWrite:
        """Write a scheduled task with its spawn's effect claim, in one step (ADR-0350 §3:3).

        **One indivisible step**, which decides the claim, the replace and the limits and
        writes the task and the effect record together, or writes nothing (§3:3, §9:4,
        §9:9). In this order:

        1. **The claim**, exactly as :meth:`claim_activation_effect` decides it: where
           the store holds a stop record for ``effect.activation_id``, the spawning
           activation, it raises ``ClaimStopped``; a held effect id raises
           ``PlanningError``; a spent part answers ``ALREADY_USED`` and the backstop
           ``ALREADY_DONE``. Each writes nothing. **Where ``effect.ticket`` names a
           request**, the spawn runs under its ticket, and the claim is decided exactly
           as :meth:`claim_ticket_call` decides it (ADR-0362 §3:1, ADR-0361
           §5:3-§5:5): the stop and the id as above; then the ticket, a request not
           held or never approved, a ticket used or whose key a record already
           carries, one void, and a claim whose ``claimed_at`` is at or after the
           request's expiry each answering ``TICKET_REFUSED`` with the
           ``TicketClaim`` that names it; then the backstop, the spawn counting as a
           call under an approval, ``ALREADY_DONE``. Each writes nothing, and leaves
           the ticket as it was.
        2. **The task id.** Where the store already holds a task under ``spawn.id``, it
           raises ``PlanningError`` and writes nothing.
        3. **The rule's author** (ADR-0340 §4:1, §9:2): a spawn whose when is a rule and
           whose author is not the person is refused as not done, ``assistants_rule``.
        4. **The replace** (§9:4), where ``spawn.replaces`` names a task. It is refused
           as not done where the store holds no such task, where it is for another
           person than ``spawn.person``, where ``replace_any`` is false and the spawning
           activation did not spawn it (§4:4), or where nothing of it is pending.
        5. **The wait** (§5:4), where ``spawn.when`` waits on named tasks: each must be
           a one-off task the store holds for ``spawn.person``, never one with a rule.
           And a replace never moves a task
           past its wait (§9:4): where the replaced task waits on tasks not all ended,
           the spawn must wait on each of them that has not. Either refusal is
           ``invalid_wait``.
        6. **The chain limit** (§9:7): the task's chain length, ``1`` where its parent
           was not started by the Task Scheduler and one more than that activation's
           task's otherwise, may not exceed ``chain_limit``.
        7. **The pending limit** (§9:8): the person's pending occurrences, counted after
           the replace's cancel, with the new task's, may not exceed ``pending_limit``.
        8. Otherwise it cancels the replaced task's pending occurrences as
           :meth:`cancel_scheduled_task` does, writes the task, and writes ``effect`` as
           a claim, with no outcome, which acting then finishes (ADR-0306 §5:5); and
           where the spawn runs under a ticket, it marks the ticket used by ``effect``,
           as :meth:`claim_ticket_call` does. Steps 2-7 hold unchanged for a spawn
           under a ticket, decided at the instant it runs, and a refusal of any of
           them writes nothing, so the ticket stays held (ADR-0362 §3:2).

        Whether the request was approved by the spawn's person, whether the spawning
        activation holds the approval's input, and whether ``replace_any`` is read as
        carried for a call under a ticket (ADR-0362 §3:5) are the caller's, as for
        :meth:`claim_ticket_call`: the store holds no activation.

        **The store authors what the spawn does not state.** The task's parent is the
        spawning activation, or the replaced task's parent on a replace, which also
        gives it the replaced task's suggested places in place of the spawn's, and so
        its chain length (§9:4). Its first occurrence is pending, due at
        ``spawn.set_at`` for a task due now, at its instant for one due at an instant,
        for one waiting on named tasks, at the instant the last of them ended where all
        have, and otherwise once they all have (§5:4); and for a rule at
        ``spawn.first_due_at``, the instant its caller computed (ADR-0340 §4:5, §9:3),
        written in this same step with the task and the effect claim. The store
        computes no instant of a rule's.

        Args:
            spawn: What the spawn states.
            effect: The spawn's effect record, a call claimed with no outcome, made by
                the spawning activation; carrying the spending key ``ticket`` where the
                spawn runs under a ticket (ADR-0362 §3:1), and never ``request``.
            match: The activations the claim is matched against, or ``None``, as for
                :meth:`claim_activation_effect`.
            deliberate_repeat: Whether planning marked the spawn a deliberate repeat.
            replace_any: Whether the spawning activation's input carries the person's
                authority, so it may replace any of the person's tasks rather than only
                one it spawned (§4:4).
            chain_limit: §12:5's chain limit, at least ``1``.
            pending_limit: §12:5's pending limit, per person, at least ``1``.

        Returns:
            ``WRITTEN`` with the task as written; ``ALREADY_USED`` or ``ALREADY_DONE``
            from the claim; ``TICKET_REFUSED`` with the ticket's refusal; or
            ``REFUSED`` with its reason. Only ``WRITTEN`` wrote.

        Raises:
            ClaimStopped: If the store holds a stop record for the spawning activation.
            PlanningError: If the spawn or the effect is not valid, the effect is not a
                call, carries an outcome or a request, or runs under a ticket whose call
                is another capability's, a limit is not a positive integer, the store
                already holds the effect's id or the task's, or the backend fails.
                Nothing is written. A spawn of a rule carrying no first instant, and a
                spawn of any other when carrying one, is not valid: each is the
                caller's error, and no ``TaskRefusal`` (ADR-0340 §9:3).
        """
        ...

    async def cancel_scheduled_task(
        self, task_id: str, /, *, person: str | None = None, spawned_by: str | None = None
    ) -> ScheduledTaskCancel:
        """End every pending occurrence of a task as cancelled (ADR-0350 §9:5).

        **One indivisible step.** It stops no running activation. It is refused as not
        done, writing nothing, where the store holds no such task, where ``person`` is
        given and the task is for another, where ``spawned_by`` is given and that
        activation did not spawn it (§4:4), or where nothing of it is pending. A task
        waiting on the cancelled one falls due once all it waits on have ended (§5:4).

        **A cancel ends a rule** (ADR-0340 §4:7): its pending occurrence ends cancelled,
        and no next occurrence is written after it. An occurrence of it still running
        runs on, and its outcome writes no next one either (§4:6). So a cancel while
        an occurrence runs cancels the next and ends the rule.

        Args:
            task_id: The task to cancel.
            person: The person the asking activation is for, or ``None`` for the Task
                Manager's command (§10:2).
            spawned_by: The asking activation, where its input does not carry the
                person's authority, so it may cancel only a task it spawned; ``None``
                otherwise.

        Returns:
            The task as left, or the reason it was refused.

        Raises:
            PlanningError: If an id is not an identifier, or the backend fails.
        """
        ...

    async def scheduled_tasks(self, task_ids: Sequence[str], /) -> tuple[ScheduledTask, ...]:
        """Return the named tasks the store holds, in the order named, each once (§12:3).

        A task the store does not hold contributes nothing.

        Raises:
            PlanningError: If ``task_ids`` is a bare string or not a sequence of strings,
                names an id with no UTF-8 encoding, or the backend fails.
        """
        ...

    async def person_scheduled_tasks(
        self, person: str, states: Sequence[OccurrenceState], /
    ) -> tuple[ScheduledTask, ...]:
        """Return a person's tasks with an occurrence in any of ``states`` (§4:6, §10:2).

        In the order they were written. The list pull and the Task Manager's queries read
        the pending ones, and the reader bounds what it shows (§12:5).

        Raises:
            PlanningError: If ``person`` is blank or has no UTF-8 encoding, ``states``
                holds anything but an ``OccurrenceState``, or the backend fails.
        """
        ...

    async def spawned_tasks(self, activation_ids: Sequence[str], /) -> tuple[ScheduledTask, ...]:
        """Return the tasks whose parent is any of the named activations (§12:3).

        In the order they were written. A stop call's result walks down through these,
        from the stopped activation to the tasks its descendants' occurrences spawned,
        and reads only (ADR-0352 §3:2).

        Raises:
            PlanningError: If ``activation_ids`` is a bare string or not a sequence of
                strings, names an id with no UTF-8 encoding, or the backend fails.
        """
        ...

    async def scheduled_lineage(self, activation_id: str, /) -> tuple[ScheduledTask, ...]:
        """Return the lineage of the task whose occurrence was pushed to an activation (§6:5).

        The task an occurrence of which was pushed to ``activation_id``, last, and each
        task above it before it, first the one at the start: a task is above another
        where an occurrence of it was pushed to the other's parent. The first task's
        parent is the activation that began the lineage, which no task records. Empty
        where no task the store holds was pushed to ``activation_id``, so it also
        answers whether the Task Scheduler started that activation, while its task is
        held (§9:1). §7:8 keeps every ancestor of live work, so the walk needs no task
        that was removed.

        Raises:
            PlanningError: If ``activation_id`` is not an identifier, or the backend
                fails.
        """
        ...

    async def live_below(self, task_id: str, /) -> bool:
        """Whether anything below a task is pending, pushed or running (§7:8).

        Below a task are the tasks its occurrences' activations spawned, and theirs in
        turn. An occurrence is pushed from its push until its outcome is written, which
        covers its activation's running, so this reads the store alone.

        Raises:
            PlanningError: If ``task_id`` is not an identifier, or the backend fails.
        """
        ...

    async def due_occurrences(self, at: datetime, /) -> ScheduledDue:
        """Return the pending occurrences due at or before ``at``, and the next due after.

        Each due occurrence on its own, earliest first (§7:3-§7:4), a task whose waits
        have all ended among them (§5:4); and the earliest instant a pending occurrence
        not yet due falls due, which the sensor sleeps until (§7:2). Instants are
        compared in UTC, never as elapsed time.

        Raises:
            PlanningError: If ``at`` is not a timezone-aware instant, or the backend
                fails.
        """
        ...

    async def mark_occurrence_pushed(
        self, task_id: str, number: int, activation_id: str, /, *, rule: RulePush | None = None
    ) -> OccurrencePush:
        """Mark a pending occurrence pushed, naming its activation, before it is admitted.

        **One indivisible step** (§7:5), so a cancel and a push are totally ordered and
        whichever lands first wins. Where the task is not held, or the occurrence is not
        pending, it answers ``NOT_PENDING`` and writes nothing. **Nothing in the task's
        lineage refuses it** (ADR-0352 §2:3): a stop record on the task's parent, or on
        the parent of any task above it, leaves the push as it is. Otherwise it
        marks the occurrence pushed to ``activation_id``, counting the push (§8:5), and
        answers ``PUSHED``.

        **An occurrence of a rule first pushed** (ADR-0340 §4:6, §4:8, §9:3) takes
        ``rule``, the instants its caller computed, and the store writes them in this
        same step. Where ``rule.latest`` is ``None``, the pending occurrence is pushed.
        Otherwise the rule missed more than one: the pending occurrence ends *skipped*,
        keeping its instant; an occurrence is recorded *skipped* at each of
        ``rule.skipped``; and one at ``rule.latest`` is the one pushed to
        ``activation_id``. Either way, the occurrence pushed is followed by one pending
        at ``rule.successor``, or by none where that is ``None``, the rule having ended.
        Each new occurrence takes the next number. So a rule holds a pending occurrence
        at every instant until it ends. **A push again after a restart** (ADR-0350
        §8:5-§8:6), of an occurrence pushed before, takes and writes no next
        occurrence, and nor does an occurrence of a task with no rule.

        Args:
            task_id: The task.
            number: The pending occurrence to push.
            activation_id: The activation it will be admitted under.
            rule: For a rule's occurrence never pushed before, the instants of its
                successor and of any it skips; ``None`` for every other push.

        Raises:
            PlanningError: If an id is not an identifier, ``number`` is not a positive
                integer, the task holds no such occurrence, an occurrence the store holds
                was already pushed to ``activation_id``, ``rule`` is not a ``RulePush``,
                a rule's pending occurrence never pushed comes with no ``rule``, a push
                again or a task with no rule comes with one, the instants ``rule`` gives
                are not each later than the pending occurrence's, or the backend fails.
                Nothing is written.
        """
        ...

    async def settle_occurrence(
        self, activation_id: str, state: OccurrenceState, /, *, second_try: bool = False
    ) -> ScheduledTask:
        """Write the outcome of the occurrence pushed to an activation (§7:6, §8).

        **One indivisible step.** ``state`` is the outcome the occurrence takes —
        ``done``, ``couldnt_finish``, ``stopped`` or ``interrupted`` — written with the
        instant it ended; a task waiting on its task falls due once all it waits on
        have ended (§5:4, §7:7). Or it is ``pending``, which pushes the occurrence
        again after a restart (§8:5), as a **second try** where ``second_try`` is set
        (§8:6). An occurrence that is a second try is never pushed again, and nor is
        one whose activation carries a stop record (§8:1).

        **It writes no next occurrence**, for a rule either (ADR-0340 §4:6): a rule's
        next was written when the occurrence was first pushed, and an occurrence pushed
        again keeps that next one pending beside it (§4:8).

        Args:
            activation_id: The activation the occurrence was pushed to.
            state: The outcome, or ``pending`` to push it again.
            second_try: With ``pending`` alone: whether it is pushed as a second try.

        Returns:
            The task as written.

        Raises:
            PlanningError: If ``activation_id`` is not an identifier, no occurrence is
                pushed to it, ``state`` is none of those, ``second_try`` rides on an
                outcome, the occurrence is a second try or its activation carries a stop
                record and ``state`` is ``pending``, or the backend fails. Nothing is
                written.
        """
        ...

    async def stop_pushed_activation(self, activation_id: str, /) -> bool:
        """Write a stop record for an activation pushed and not yet admitted (§9:10).

        **One indivisible step**: where an occurrence is pushed to ``activation_id``,
        it writes the stop record :meth:`record_stop` writes, so the sensor's admission
        refuses that id and the occurrence ends stopped; otherwise it writes nothing.

        Returns:
            Whether an occurrence was pushed to it, so a stop record was written.

        Raises:
            PlanningError: If ``activation_id`` is not an identifier, or the backend
                fails.
        """
        ...

    async def stopped_activations(self, activation_ids: Sequence[str], /) -> tuple[str, ...]:
        """Return which of the named activations the store holds a stop record for.

        In the order named, each once. The read the Task Scheduler's admission makes of
        a pushed id (§9:10), and its restart's settling of a pushed occurrence whose
        activation is not running (§8:1): a stop record is the store's, and only the
        store answers whether one is held (ADR-0297 §1).

        Raises:
            PlanningError: If ``activation_ids`` is a bare string or not a sequence of
                strings, names an id with no UTF-8 encoding, or the backend fails.
        """
        ...

    async def confirm_message_effect(
        self, effect_id: str, /, *, delivered: bool, position: int | None = None
    ) -> None:
        """Settle a message's effect record from its place's confirmation, once (§8:11).

        Where a message's record has an unknown outcome or none written, the kind of its
        place confirmed from its medium's own record whether it was sent: ``delivered``
        writes it done, with the position the medium recorded it at; otherwise it is
        written not done. **Every other change to an outcome already written is
        refused**, as :meth:`finish_activation_effect` refuses it (ADR-0306 §6:4).

        Args:
            effect_id: The message's record.
            delivered: Whether the medium recorded the message.
            position: Where it recorded it; required where it did, and only then.

        Raises:
            PlanningError: If ``effect_id`` is not an identifier, the store holds no
                record under it, the record is a call, its outcome is done or not done,
                the position does not match ``delivered``, or the backend fails.
                Nothing is written.
        """
        ...

    async def remove_scheduled_task(self, task_id: str, /) -> bool:
        """Remove a task once nothing of it or below it is live (ADR-0350 §7:8).

        **One indivisible step**, which removes the task only where nothing of it is
        pending, none of its occurrences is pushed, no task below it is pending or
        pushed, and no task the store holds waits on it. The fifth condition, that its
        parent is no longer running, is the engine's state and never the store's: the
        caller removes no task whose parent is still running.

        Returns:
            Whether the task was removed. A task not held, or kept, is not.

        Raises:
            PlanningError: If ``task_id`` is not an identifier, or the backend fails.
        """
        ...

    # --- the Approvals channel's requests (ADR-0361 §8:2) ---------------------

    async def write_approval_request(
        self,
        request: ApprovalRequest,
        effect: ActivationEffect,
        /,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool = False,
    ) -> ApprovalRequestWrite:
        """Write a request with ``request_approval``'s effect claim, in one step (§2:8-§2:9).

        **One indivisible step**, which decides the claim and the duplicate check and
        writes the request and the effect record together, or writes nothing. In this
        order:

        1. **The stop and the id**, as :meth:`claim_activation_effect` decides them:
           where the store holds a stop record for ``effect.activation_id``, the asking
           activation, it raises ``ClaimStopped``; a held effect id raises
           ``PlanningError``.
        2. **The request id.** Where the store already holds a request under
           ``request.id``, it raises ``PlanningError``.
        3. **The duplicate** (§2:8). Where a pending request for ``request.person``, not
           expired by ``request.written_at``, holds a call with the same capability,
           values and binding, it answers ``already_waiting`` with that request, which
           says since when.
        4. **The backstop**, as :meth:`claim_activation_effect` decides it over
           ``match``: ``already_done``.
        5. Otherwise it writes the request and ``effect`` as a claim, with no outcome,
           which acting then finishes (ADR-0306 §5:5), and answers ``written``.

        Args:
            request: The request to write: pending, with no answer, ticket, card or
                pushed mark. Its ``expires_at`` is the caller's, 24 hours on (§3:5).
            effect: ``request_approval``'s effect record, a call claimed with no outcome,
                made by the asking activation in the request's round and naming the
                request (:attr:`~ai_assistant.core.types.ActivationEffect.request`).
            match: The activations the claim is matched against, or ``None``, as for
                :meth:`claim_activation_effect`.
            deliberate_repeat: Whether planning marked the call a deliberate repeat.

        Returns:
            ``written`` with the request; ``already_waiting`` with the pending request it
            duplicates; or ``already_done``. Only ``written`` wrote.

        Raises:
            ClaimStopped: If the store holds a stop record for the asking activation.
            PlanningError: If the request is not valid or not fresh, the effect is not a
                call naming the request from its activation and round or carries an
                outcome, an id is already held, or the backend fails. Nothing is written.
        """
        ...

    async def approval_requests(self, request_ids: Sequence[str], /) -> tuple[ApprovalRequest, ...]:
        """Return the named requests the store holds, in the order named, each once (§8:2).

        A request the store does not hold contributes nothing.

        Raises:
            PlanningError: If ``request_ids`` is a bare string or not a sequence of
                strings, names an id with no UTF-8 encoding, or the backend fails.
        """
        ...

    async def person_approval_requests(
        self, person: str, states: Sequence[ApprovalRequestState], /
    ) -> tuple[ApprovalRequest, ...]:
        """Return a person's requests in any of ``states``, in the order written (§4:6).

        The panel reads the pending ones and those answered most recently, and the reader
        bounds what it shows.

        Raises:
            PlanningError: If ``person`` is blank or has no UTF-8 encoding, ``states``
                holds anything but an ``ApprovalRequestState``, or the backend fails.
        """
        ...

    async def approval_request_by_token(self, token: str, /) -> ApprovalRequest | None:
        """Return the request one of whose cards carries ``token``, or ``None`` (§4:10).

        A button's callback data is an opaque token minted for its card, naming no
        record, so this read is how a tap on the line finds its request. Its state is the
        request's, whatever it is, so a later tap is answered with it (§4:9).

        Raises:
            PlanningError: If ``token`` is blank or has no UTF-8 encoding, or the backend
                fails.
        """
        ...

    async def record_approval_card(self, request_id: str, card: ApprovalCard, /) -> ApprovalRequest:
        """Record one of a request's cards, with its token, in one step (§4:2-§4:4, §4:10).

        A card is recorded whatever state the request stands in, since a tap on the panel
        may answer it before its post returns. A card that failed or was not posted is
        not recorded (§2:7).

        Returns:
            The request as written.

        Raises:
            PlanningError: If an id is not an identifier, the card is not valid, the store
                holds no such request, a card of any request already carries the token, or
                the backend fails. Nothing is written.
        """
        ...

    async def answer_approval_request(
        self, request_id: str, state: ApprovalRequestState, tap: ApprovalTap, /
    ) -> ApprovalRequestStep:
        """Mark a pending request approved or denied by a tap, in one step (§4:9).

        **One indivisible step**, which refuses where the request is no longer pending,
        so the first tap to land wins: a later one answers ``not_pending`` with the
        request's state. A tap at or after the request's expiry answers ``past_expiry``.
        Each writes nothing. Otherwise the request takes ``state``, with ``tap`` as its
        answer, and an approval its ticket, held (§5:1); a deny grants none (§5:9).

        Args:
            request_id: The request tapped.
            state: ``approved`` or ``denied``.
            tap: Who tapped, as their surface's giver, and when.

        Returns:
            ``changed``, ``not_pending`` or ``past_expiry``, with the request as held.

        Raises:
            PlanningError: If an argument is not valid, ``state`` is neither approved
                nor denied, the store holds no such request, the tap is earlier than its
                write, or the backend fails.
        """
        ...

    async def expire_approval_request(
        self, request_id: str, at: datetime, /
    ) -> ApprovalRequestStep:
        """End a request expired at its expiry, in one step (§3:5).

        A pending request ends ``expired``. A ticket expires with its request, so an
        approved request whose ticket is still held has it made void (§5:7). Either
        answers ``changed``; any other request answers ``not_pending`` and writes nothing.

        Args:
            request_id: The request.
            at: The instant the caller read, at or after the request's expiry.

        Raises:
            PlanningError: If an argument is not valid, the store holds no such request,
                ``at`` is before its expiry, or the backend fails.
        """
        ...

    async def void_approval_ticket(self, request_id: str, /) -> ApprovalRequestStep:
        """Make a request's held ticket void, in one step (§5:7).

        The work holding the approval's input ended without running it. A request
        holding no ticket still held answers ``no_held_ticket`` and writes nothing.

        Raises:
            PlanningError: If ``request_id`` is not an identifier, the store holds no
                such request, or the backend fails.
        """
        ...

    async def due_approval_outcomes(self, at: datetime, /) -> ApprovalDue:
        """Return what the Approvals sensor reads at ``at`` (§3:4-§3:5).

        The requests answered or expired whose outcome no push has marked, in the order
        written; the requests whose expiry is at or before ``at`` that are still pending
        or hold a ticket still held; and the earliest expiry after ``at`` among such
        requests, which the sensor sleeps until. Instants are compared in UTC.

        Raises:
            PlanningError: If ``at`` is not a timezone-aware instant, or the backend
                fails.
        """
        ...

    async def pushed_approval_outcomes(self) -> tuple[ApprovalRequest, ...]:
        """Return every request whose outcome is marked pushed, in the order written (§3:7).

        The read a restart makes: an outcome marked pushed whose activation was never
        admitted is pushed again, under the activation its mark names. Whether that
        activation was admitted is the engine's to read, never the store's.

        Raises:
            PlanningError: If the backend fails.
        """
        ...

    async def mark_approval_outcome_pushed(
        self, request_id: str, activation_id: str, /
    ) -> ApprovalOutcomePush:
        """Mark a request's outcome pushed, naming its activation, before it is admitted.

        **One indivisible step** (§3:4), which refuses where the outcome is already
        marked, or the request is still pending: it answers ``not_due`` and writes
        nothing. Otherwise it records ``activation_id`` and answers ``pushed``.

        Raises:
            PlanningError: If an id is not an identifier, the store holds no such
                request, another request's outcome was already pushed to
                ``activation_id``, or the backend fails. Nothing is written.
        """
        ...

    async def claim_ticket_call(
        self,
        effect: ActivationEffect,
        /,
        *,
        match: tuple[str, ...] | None,
        deliberate_repeat: bool = False,
    ) -> TicketClaim:
        """Claim a call under a ticket, keyed by its request, spending it (§5:3-§5:5).

        **One indivisible step**, which decides the claim and the ticket and writes the
        effect record and the spend together, or writes nothing. In this order:

        1. **The stop and the id**, as :meth:`claim_activation_effect` decides them.
        2. **The ticket**, named by ``effect.ticket``: a request not held, or never
           approved, answers ``not_granted``; a ticket used, or one whose key a record
           already carries, ``used``; one void, ``void``; and a claim whose
           ``claimed_at`` is at or after the request's expiry, ``expired``.
        3. **The backstop**, as :meth:`claim_activation_effect` decides it over
           ``match``, a call under a ticket counting as a call under an approval:
           ``already_done``.
        4. Otherwise it writes ``effect`` as a claim, marks the ticket used by it, and
           answers ``claimed``.

        Whether the request was approved by the person the calling activation is for,
        and whether that activation holds the approval's input (§5:3, §5:6), are the
        caller's: the store holds no activation.

        Raises:
            ClaimStopped: If the store holds a stop record for the activation.
            PlanningError: If the effect is not a valid call naming a ticket, carries an
                outcome, its id is held, its capability is not the one the ticket's call
                holds, or the backend fails. Nothing is written.
        """
        ...

    async def export(self) -> PlanExport:
        """Return a portable snapshot of all planning state (ADR-0004 §6).

        **It carries the store's stop records** (ADR-0297 §1), as the tuple of
        activation ids :meth:`record_stop` recorded, each once.

        **And its activation effect records** (ADR-0306 §6), finished or not, in the
        order they were claimed. :meth:`clear` erases them with the rest.

        **And its observation records** (ADR-0329 §16:9), each with its revision,
        ordered by episode id.

        **And the Task Scheduler's content** (ADR-0350 §12:3): every scheduled task it
        holds, with its occurrences, in the order written.

        **And the Approvals channel's content** (ADR-0361 §8:2): every approval request it
        holds, with its answer, ticket, cards and pushed mark, in the order written.
        """
        ...

    async def clear(self) -> int:
        """Delete every record in this store, returning the number removed.

        **Every stop record goes with the rest** (ADR-0297 §1), and is counted among
        the records removed. **So does every observation record** (ADR-0329 §16:9),
        each counted once; the revision issuer is kept, so no revision is issued
        twice. **So does every scheduled task** (ADR-0350 §12:3), each counted once;
        no cascade record is held to count (ADR-0352 §6:3). **So does every approval
        request** (ADR-0361 §8:2, ADR-0292 §3:11), each counted once.

        Raises:
            PlanningError: If the backend fails.
        """
        ...


@runtime_checkable
class ToolRegistry(Protocol):
    """What tools exist and what invoking them risks (ADR-0016 §5).

    The pipeline's tool-selection stage queries this, and ``permissions`` reads
    a candidate's declared metadata to rule on it. Both only ever *ask*, which
    is why this contract is **query-only**: populating a registry is internal to
    `tools`.

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
        outcome.
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
        error out of a method whose contract is that it answers a question.

        **A fourth check follows those three, and then the claim** (ADR-0192 §1).
        An implementation that pairs a call with a callable shape — an *egress*
        callable that must be handed the binding the ruling fixed, against an
        ordinary one that must not be — checks that pairing here, **before** the
        claim, because it reads the registry's callable and not the call alone, so
        the three above do not subsume it. Where that check lives is
        `tools/`-internal and is contracted nowhere (ADR-0152 §10); *that it
        precedes the claim* is contracted here.

        **The spend admission runs after all four and before the claim**
        (ADR-0194 §3). ``invoke`` consults the :class:`SpendGate` it holds, handing
        it the ``ToolCost`` on the **revalidated, detached copy** the checks above
        produced and never the argument the caller passed. A refused call reaches
        no callable, appends no claim and appends no completion. The admission is
        **not** a fifth member of ADR-0029 §2's enumeration, which stays exhaustive
        at three: those three establish that the call is the one the user
        authorised and each raises ``ToolBindingError``; this establishes something
        else entirely and is ordered after them the way any later obligation on
        ``invoke`` is. A ``ToolBindingError`` therefore **pre-empts** every spend
        refusal, and no implementation moves the admission earlier to save a store
        read: a call mutated after construction could carry an ``UNKNOWN`` cost the
        user never authorised, and reaching the gate first would send the operator
        to a budget setting to repair a binding failure.

        **The gate's own exception is what leaves.** An implementation propagates
        the instance the gate raised rather than re-raising an equivalent, and adds
        nothing to it — no note, no appended message, no wrapped cause — because
        ADR-0194 §4 makes both messages payload-free where they are *raised* and
        this seam is the one that can undo it. A refusal states the numbers and
        never a recipient, an argument or a digest of one.

        **The handle is released in a ``finally``**, after the completion has been
        appended or after the failure that prevented it, on the admitted, raising
        and cancelled paths alike (ADR-0194 §3). The release is synchronous,
        idempotent and raises nothing, so unwinding cannot lose it and a
        book-keeping failure can never replace the call's own outcome. ``invoke``
        calls it **once** per admission even though the gate must tolerate more.

        **The admission runs inside the deadline, sharing the caller's one
        window.** ``timeout`` is not restarted when the admission returns: an
        implementation giving the admission its own fresh window and the callable
        another returns successfully at nearly twice the deadline the caller set. A
        deadline that expires during the admission is classified by ADR-0029 §4's
        existing rule, unchanged and unnarrowed — ``FAILED`` where the tool is not
        ``side_effecting`` or its ``idempotency`` is ``NATURAL``, ``INDETERMINATE``
        otherwise — because ``invoke`` was entered and nothing states which await it
        expired in (ADR-0034 §1). It is **not** the pre-callable exit a spend
        refusal is; that one qualifies on ADR-0034 §1's second ground, and the
        call is not done.

        **The claim is the consume, and it sits immediately before the callable.**
        ``invoke`` appends it through the :class:`InvocationLedger` it holds,
        passing the whole ``PermissionDecision`` the call carries and not its id
        alone, and a call whose claim is refused does not reach the callable. An
        implementation **holds an** :class:`InvocationLedger` **and never an**
        :class:`AuditTrail`: the ledger can neither record a decision, nor read
        one, nor export, nor ``clear``, so no decision write, no history read and
        no erasure reaches `tools/` through this seam (ADR-0192 §2).

        **After the claim, ``invoke`` performs no check that can raise a seam
        fault.** That is stated as a **property, not a list**, and it is what makes
        the completion obligation below total: every exit reached past the claim
        has an outcome ADR-0029 §§3-4 compute, so none of them needs one invented.
        A lane adding a check moves it above the claim rather than teaching the
        completion a new outcome.

        **Once a claim is appended, a completion is attempted on every exit this
        method observes** — a returned ``ToolResult``, an expired deadline, a
        cancellation — carrying the outcome ADR-0029 §§3-4 already compute for it,
        the ``failure_kind`` the result carried (transcribed, never synthesised),
        and the cost the result reported or a ``ToolCost`` whose basis is
        ``UNKNOWN`` where it reported none — never ``ToolDefinition.cost``
        (ADR-0192 §3, §5). The obligation is **to make the call**: a completion
        that is refused or fails to write changes nothing about the act itself.
        ``invoke`` returns the result the call produced, or re-raises what it was
        already raising; it does not convert a completion's failure into a
        ``ToolResult``, substitute an outcome, retry the act, or re-claim. A
        ``SUCCEEDED`` side effect is not reported as failed because a disk was
        full. Such a failure is not swallowed either: it reaches the operator as a
        Tier 2 diagnostic carrying enumerated fields and no free text — the ledger
        operation, the exception's fault class where it is an ``Exception``, and
        the outcome being written — and never an instance, a message, a member of a
        cause chain, or any identifier (ADR-0004 §5, ADR-0031 §5).

        A ``BaseException`` that is not a cancellation is not an exit that clause
        reaches: ADR-0029 §3 requires it to propagate unchanged, no outcome is
        invented for it, no completion is written, and the claim is left **open** —
        which states positively that the act **may have executed** and is read as
        nothing else (ADR-0192 §3). What the store already committed **stands**, on
        either append: where one raises, no row is known to have landed and none is
        known not to have, and nothing is deleted, rewritten or compensated to tell
        the two apart.

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

        **``timeout`` is the deadline for the *call*, and it is not a budget for
        this method's whole frame** (ADR-0192 §1, §3, §7). Neither ledger append is
        bounded by it: each is awaited to its outcome, so a store that has stopped
        answering blocks the call before the callable and blocks the classified
        result after it. That narrows ADR-0029 §4 deliberately and in one
        direction — a bound over the claim would buy a row that may or may not
        exist for an act that certainly never happened, and a bound over the
        completion would be a fiction, since the audit store this system wires
        absorbs cancellation until its worker finishes (ADR-0054). The trade is a
        liveness cost on a broken store, in exchange for the property that no act
        is performed on an authorisation whose claim could not be confirmed, and no
        outcome is dropped for a call that ran.

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
            ToolBindingError: If any of the checks above fails — the three, and
                the callable-shape pairing where an implementation has one.
                **No claim is appended for any of them** (ADR-0192 §1).
            SpendCeilingError: If the :class:`SpendGate` refuses the call because
                a configured ceiling would be crossed (ADR-0194 §4). A
                **pre-callable** exit: no callable is created, no claim and no
                completion are appended, and it qualifies on ADR-0034 §1's second
                ground, so the call is not done and is never retried. Propagated as the
                **instance** the gate raised, unchanged and unannotated, and never
                translated to ``PermissionDeniedError`` — the recorded ruling *is* an
                ``ALLOW``, and what refused is arithmetic over a period.
            SpendUndeterminedError: If the spend the admission needed could not be
                reduced to a number (ADR-0194 §4) — the declared amount is not
                countable, the declared cost has no number at all, the clock
                raised, the store read failed, the period is indeterminate, or the
                arithmetic trapped. The same pre-callable exit and the same
                propagation rule as above. It is a separate class because a call
                that could not be measured crossed no ceiling, and reporting it as
                one would state a number about a budget that nothing measured.
            AuthorisationSpentError: If the ledger refuses the claim because the
                authorisation is spent (ADR-0192 §1). Propagated unchanged rather
                than translated, and never auto-retried.
            UnrecordedAuthorisationError: If the trail holds no decision equal to
                the one this call carries under its id, or holds one whose ruling
                outcome is not ``ALLOW``. Propagated unchanged, likewise.
            AuditError: If the **claim** append failed with anything that is not an
                ``AssistantError`` — including a ``CancelledError`` a collaborator
                raised while the ``Task.cancelling()`` count was unmoved across the
                call, which is not a cancellation of this call and does not leave as
                one (ADR-0192 §1, ADR-0031 §2). Every exit from the claim append is
                a **pre-callable** one, so it qualifies on ADR-0034 §1's second
                ground, on the window rather than on a list of causes. A failure of the
                **completion** append is absorbed instead and reaches the operator as
                the diagnostic above.
            CancelledError: If the invoking task is cancelled from outside. The
                seam does not convert it to a result — there is no return path
                from a task being torn down — so recording the call's outcome by
                the same rule the timeout uses, and then re-raising, is the caller's
                obligation (ADR-0029 §4). It is delivered onward **whatever an
                append did**: where one failed while a cancellation was pending, the
                cancellation is what leaves and the append's failure is attached as
                its cause, never raised in its place (ADR-0060 §1).
        """
        ...


@runtime_checkable
class EgressBinder(Protocol):
    """Derives an egress call's binding before the ruling, or refuses it (ADR-0152 §1).

    ADR-0148 §11's surface (b): the seam by which `orchestration` obtains an
    egress binding — together with the call it was derived under — from `tools/`
    before :meth:`ActionPolicy.decide` is reached. ADR-0150 decided the *value*;
    this decides how the value is obtained, and the two together are what let
    ADR-0148 §1's earliness hold, since a request must already carry the whole
    binding when the policy sees it and every part of that binding is
    integration-specific knowledge living in `tools/`.

    **Two operations and no others.** :meth:`bind` answers "what binding does this
    call have", for a call reaching the permission stage for the first time;
    :meth:`rebind` answers "what binding does this call have, and is it the one
    that was approved", for a call resuming from a parked ``CONFIRM`` (ADR-0037
    §4). The alternative — a single member with ``provenance`` and ``approved``
    both optional and a rule that exactly one is supplied — is four constructible
    states of which two are ill-formed, policed by a rule rather than by a type;
    the ill-formed ones are "resume without checking what was approved" and
    "authorise afresh with a stored binding" (ADR-0152 §1).

    **Nothing about the binding is accepted; all of it is derived.** Neither
    member takes a destination, a canonical form, a span, an extent, a tier or a
    binding, and there is no argument through which one could be supplied
    (ADR-0152 §5). **Two** things cannot be derived and are therefore **carried**,
    both of them on :meth:`bind` in
    :class:`~ai_assistant.core.types.CarriedProvenance` and both of them on
    :meth:`rebind` transcribed from the approved binding: a span's recorded origin
    (ADR-0146 §2), and the call's ``planned_with_external_content`` (ADR-0181 §3,
    §4). They answer different questions — *who disclosed this span* and *did this
    system's selection rest on recorded external content* — and no component reads
    one axis as an answer on the other (ADR-0181 §1's third clause). What makes the
    second uncarryable-by-derivation is the same thing that makes the first so: it
    is a fact about an act performed **before** this seam was reached, and no
    inspection of an argument's value, field or shape may recover it (ADR-0146 §2,
    ADR-0181 §4's second clause).

    **A third Protocol rather than a member on** :class:`ToolRegistry`. ADR-0029
    §1's argument for splitting :class:`ToolInvoker` off transfers: a binder is a
    third capability with a third consumer set — selection's lookup needs it not
    at all, and acting, which invokes what authorizing ruled, needs it not at all
    — and adding ``bind`` to a
    registry would hand every holder of a lookup the ability to materialise an
    account reference and a transport endpoint (ADR-0017 §8). Whether one object
    in `tools/` presents all three faces or a second object presents this one is
    `tools/`-internal and is not contracted here (ADR-0152 §10).

    **Both members are ``async``, and that is not permission to await anything.**
    The read budget is **at most one** read per call and it is fixed: the
    connection record the bound tool's egress registration names, read for its
    connectability and its account identity and for nothing else (ADR-0152 §8,
    §10). Neither member performs network I/O of any kind, reads a clock, reads
    configuration or resolves anything, so neither can become the resolution path
    ADR-0148 §5 governs. Neither reads a keyring, a memory store, a plan store, an
    audit trail, a grant store, a notification store or a second connection
    record, and neither performs a write of any kind anywhere.

    **No credential value and no credential slot crosses this seam in either
    direction.** A :class:`~ai_assistant.core.types.SecretName`, its ``name``, and
    any string identifying a keyring entry appear in no argument, no return value
    and no refusal message. An implementation holds no :class:`Secrets` and no
    :class:`SecretStore` face, and holding this seam is not holding one (ADR-0125
    §8, ADR-0149 §8).

    **Every clause below is evaluated over the revalidated, detached copy of the
    argument, never over the caller's object** (ADR-0152 §1). That is ADR-0029
    §2's step 1 applied whole at a second seam — "the call is **revalidated and
    detached** — first", and "every subsequent check reads the revalidated copy,
    never the argument" — and it is what closes the suspension window the one
    awaited read opens. Without it a caller could hand in a registry-equal
    definition, let it revalidate and compare, suspend the seam on that read, then
    replace the declaration with ``object.__setattr__`` (which defeats
    ``frozen=True``, ADR-0018 §3) and have the binding derived under a declaration
    no longer equal to the registered original.

    **The seam assumes nothing about what a caller checked before reaching it.**
    On the ordinary path it is reached after ADR-0145's schema check, which
    ADR-0144 §7's eligibility filter performs during selection — but that is an
    ordering of the caller and not a precondition: every shape a clause
    depends on is re-established here from the ``tool`` and the ``parameters``
    handed over, because a request built by a bypass reaches the seam (ADR-0029
    §2, ADR-0145 §3). **A conformance suite therefore exercises every refusal
    directly**, against a subject handed inputs no caller would produce, and an
    implementation that refuses only what its caller would already have refused
    does not satisfy this contract (ADR-0152 §10).

    **The declaration this seam reads rides in the tool's ``parameters_schema``,
    in two keywords and no others** (ADR-0152 §3), each read **only** on the
    immediate subschema of a key of that schema's top-level ``properties``
    object: ``x-egress-destination``, whose value is a
    :class:`~ai_assistant.core.types.DestinationProtocol` member's own string
    value, present exactly on a destination-bearing argument; and
    ``x-egress-tier``, whose value is a
    :class:`~ai_assistant.core.types.DataTier` member's own string value, present
    exactly where the argument's field *establishes* that tier (ADR-0146 §5). No
    other keyword declares anything here, no field is added to
    :class:`~ai_assistant.core.types.ToolDefinition` for either, and nothing in
    the vocabulary declares whether an argument decomposes, is transmitted or is
    required — ADR-0150 §4, ADR-0150 §4 again, and JSON Schema's own ``required``
    each already state one of those.

    **A destination-bearing argument is flat** (ADR-0152 §4, ADR-0157 §1): its
    subschema is ``"type": "string"``; or ``"type": "array"`` whose ``items`` is a
    subschema whose own ``"type"`` is ``"string"``; or an ``anyOf`` holding
    **exactly two** branch subschemas, one of them the first form and the other
    the second, in either order — and nothing else. No other spelling of that
    union is flat: not ``"type": ["string", "array"]``, not a ``oneOf``, not an
    ``anyOf`` with one branch or with three or more, not one whose branch is
    itself an applicator or a ``$ref``, and not one carried beside a sibling
    ``"type"``. A declaration marking any other shape is refused when the
    declaration is read; a *call* whose declared destination-bearing argument
    carries a value that is not a JSON string and not a JSON array of JSON strings
    is refused before the ruling, whether or not the declaration was already
    refused. The two rules are not the same width and were never meant to be — the
    third form is what lets a declaration say what the per-call rule has always
    said, and it admits **no value** the per-call rule did not admit before
    (ADR-0157 §2).

    **No message any refusal raises renders an argument value, a supplied or
    canonical destination form, an account identity, a credential slot, or any
    part of a span's content** (ADR-0152 §11). It may name the tool id, an
    argument name the bound tool's declaration **statically names**, a zero-based
    index, a count, a field name, an error type, and the **connection reference** —
    which the connectability refusal does name, ADR-0149 §3's split between a
    loggable handle and a Tier 1 value. A key of ``parameters`` the declaration
    does not statically name is never interpolated into a message; a refusal for
    such a key states the count and the declared names and nothing of the key
    itself.

    Cancelling either member is governed by this module's cancellation clause
    (ADR-0060). It has little bite here — nothing is written anywhere — but the
    one awaited read must not be left holding a store's resource.
    """

    async def bind(
        self,
        tool: ToolDefinition,
        *,
        parameters: FrozenJsonMapping,
        provenance: CarriedProvenance,
    ) -> BoundEgressCall | None:
        """Derive the binding for a call reaching the permission stage first time.

        **What is given is the bound tool and the arguments**, which are two of the
        three things ADR-0148 §6's determinism clause makes the description a
        function of, plus the third that clause names and the seam cannot derive.
        No step id, no execution id, no decision, no ruling and no timeout: none of
        them bears on what this call would transmit or to whom.

        ``tool`` is the **definition** and never a tool id, so the declaration the
        binding was derived under and the declaration bound into the
        :class:`~ai_assistant.core.types.ActionRequest` are one object rather than
        two lookups that must agree — it is the same object the request carries,
        the policy rules on and the decision embeds verbatim (ADR-0021 §1).

        **``None`` is returned exactly when** the revalidation below succeeded,
        this seam holds **no egress registration** for ``tool.id`` — that is, no
        connected account bound to it — **and** ``tool.parameters_schema`` carries
        neither declaration keyword (ADR-0152 §8). Such a call is not an egress
        call: it carries no binding, and every refusal below is inapplicable to it.
        ``None`` never signals a failure, and no caller reads it as one. The caller
        then builds its request from its own ``tool`` and ``parameters`` with
        ``egress_binding=None``, and no behaviour of any non-egress call changes.

        What makes a tool an egress tool is the **connected account it is
        registered against** (ADR-0148 §6) and not the presence of a keyword: a
        tool bound to an account whose schema carries neither keyword is a
        well-formed egress call selecting no onward recipient, whose canonical
        destination set is the account alone. A tool this seam holds no
        registration for whose schema carries **either** keyword is **refused**
        rather than answered ``None`` — it is mis-registered, and returning ``None``
        would silently discard a declaration its author wrote.

        **The revalidation runs ahead of that condition, and the ordering is
        forced**: evaluating it reads ``tool.id`` and ``tool.parameters_schema``,
        which are fields of an argument revalidated before any field of it is read.
        A call whose arguments fail revalidation is therefore refused on this
        branch exactly as on every other, and never reaches the condition at all.

        **Every argument whose annotation carries validation is revalidated before
        any field of it is read, and detached** — ``tool``, ``parameters`` and
        ``provenance``, with no exemption for any of them on the ground that the
        annotation says the value is valid: ``model_construct`` is a documented
        escape hatch, ``object.__setattr__`` defeats ``frozen=True`` (ADR-0018 §3),
        and neither is detectable from a type. A revalidation failure raises
        :class:`~ai_assistant.core.errors.EgressBindingError` **chained from** the
        ``ValidationError`` revalidation raised, which is ADR-0029 §2's step 1 rule
        at a second seam. That is the whole of what is converted: an exception of
        any other type raised from inside a validator this seam invokes is **not**
        turned into an ``EgressBindingError`` — in particular a ``RecursionError``
        from freezing a deep ``parameters`` mapping propagates unconverted, which
        is ADR-0145 §14's pre-existing hazard at the shared frozen-JSON ingress
        (issue #1107) and is neither created nor fixed here.

        **The binding is derived whole and no part of it is accepted** (ADR-0152
        §5). Every :class:`~ai_assistant.core.types.EgressDestination` carries the
        canonical form **this seam's own canonicaliser for that occurrence's
        protocol** computed from its supplied form — which discharges ADR-0150
        §11's correspondence check by construction rather than by comparison, since
        an occurrence the seam computed cannot disagree with the computation that
        produced it. For each protocol the seam reaches **one** canonicaliser, and
        no integration, declaration, configuration or registration supplies a
        second for a protocol it already canonicalises (ADR-0148 §2). A supplied
        form for which that canonicaliser asserts no canonical form is refused, and
        never passed through as its own canonical form.

        The one field not derived is a span's ``provenance``. The seam writes
        :attr:`~ai_assistant.core.types.DiscloserProvenance.SYSTEM_SELECTED` for
        every span ``provenance`` does not name — ADR-0146 §2's fail-closed rule
        discharged by the component building the span rather than by a field
        default — and **refuses** an entry naming a span this call does not carry,
        rather than dropping it: a caller and this derivation disagreeing about
        what the payload is, is exactly what a silent drop would hide.

        Args:
            tool: The selected tool's definition, positionally, by ADR-0085 §2's
                convention. Refused if it is not equal to the definition this
                implementation holds registered under ``tool.id`` — ADR-0029 §1's
                registry-original check performed one stage earlier and for its
                stated reason, the seam being the only place the caller's
                definition and an untampered original meet. It is not a substitute
                for that check, which still runs at :meth:`ToolInvoker.invoke`.
                Where this implementation holds no registration for the id, the
                comparison is not reached and the ``None`` condition above governs.
            parameters: The arguments the ``ActionRequest`` will carry, unaltered.
                Nothing is amended, defaulted into them or substituted for them:
                what comes back on the egress path is the **same** mapping the
                binding was derived under, carried on the returned value.
            provenance: What the caller carries across this seam that the seam
                cannot derive, as a validating carrier rather than a bare mapping:
                the recorded origin of each span it holds one for, and the call's
                ``planned_with_external_content`` (ADR-0181 §3, §4). Neither has a
                default — a caller holding no span origins constructs the carrier
                over an empty mapping, and a caller holding no selection states
                ``False`` deliberately (ADR-0150 §5, ADR-0181 §3). The seam
                **carries** the second onto the binding unchanged and derives
                nothing for it: no component invents it where a caller did not
                supply it, and none infers it from an argument's value, field or
                shape (ADR-0181 §4's second clause).

        Returns:
            The derived binding beside the **detached** ``tool`` and
            ``parameters`` it was derived from, or ``None`` where the call is not
            an egress call. The caller builds its ``ActionRequest`` from **these
            three fields** and never from objects it retained across the call, and
            no ``await`` sits between this returning and that construction — the
            system composes on one event loop, so with no suspension point between
            them nothing else interleaves and the returned copies cannot be reached
            or replaced before the request is built.

        Raises:
            EgressBindingError: On every refusal ADR-0152 §6 states, and refusing
                is a refusal of the **whole call**: the binding is not produced,
                the ``ActionRequest`` is not built, and no ruling is sought
                (ADR-0148 §1). The named ones are: a top-level key of
                ``parameters`` the bound tool's ``parameters_schema`` does not
                **statically name** — a key of that schema's top-level
                ``properties`` object, never one admitted only by
                ``additionalProperties``, ``patternProperties``, ``propertyNames``
                or any other open-ended form, however validly the call type-checks
                against it, and a tool with no schema or no top-level
                ``properties`` statically names none; a span of an argument the
                declaration marks destination-bearing carrying no
                ``EgressDestination``; a declared destination-bearing argument
                whose value is not a JSON string or a JSON array of JSON strings,
                and a declaration marking an argument whose subschema is none of
                the three flat forms above (ADR-0157 §1); a declaration
                breaching the vocabulary — a keyword outside a top-level property's
                own subschema, a keyword value naming no member of its enum, a
                protocol this seam holds no canonicaliser for, or a
                destination-bearing argument stating no tier; a bound tool whose
                egress registration names a reference that is **not connectable**
                at the moment the call is bound, its connection record being absent
                or ``PENDING`` rather than ``ACTIVE`` (ADR-0148 §6, read at this
                moment and never carried over from registration or an earlier
                call); and, residually, any other call for which a whole,
                well-formed binding cannot be produced. A partial binding is never
                returned, a ``BoundEgressCall`` whose ``tool`` or ``parameters`` is
                other than the one its binding was derived under is never returned,
                and ``None`` is never returned to signal a failure.
            ConnectionStoreError: If the connection record could not be read at
                all (ADR-0151 §2a). **Never** translated into an
                ``EgressBindingError``: a
                store that could not be read asserts nothing about the call, which
                may be bindable a second later. It propagates to the caller, which
                has committed nothing — no ruling requested, no audit record written,
                no claim made. No implementation suppresses it, retries it inside
                the seam, or falls back to a cached connectability, a cached
                identity or a previous read.
            CancelledError: If the calling task is cancelled from outside.
        """
        ...

    async def rebind(
        self,
        tool: ToolDefinition,
        *,
        parameters: FrozenJsonMapping,
        approved: EgressBinding | None,
    ) -> BoundEgressCall | None:
        """Re-derive the binding for a resuming call, and check what was approved.

        ADR-0037 §4's resume sequence rebuilds the ``ActionRequest`` from the
        confirmation's own embedded ``ToolDefinition`` and the step's parameters,
        and a second ruling — :meth:`ActionPolicy.resolve` — is taken on it. Under
        ADR-0148 §1 that request must carry the whole binding before that ruling
        too, and this is where it is obtained.

        **Everything is re-derived except five things, all taken from
        ``approved``**: each span's provenance, matched to the derived span by
        :class:`~ai_assistant.core.types.EgressSpanLocator`, the binding's
        ``planned_with_external_content``, and the three facts the count below names.
        Nothing else in ``approved`` is read into the result. Transcribing the
        provenance is forced: a recorded origin is a fact about an act that happened
        before the confirmation was parked,
        plausibly before a restart, so a member that took a fresh ``provenance``
        argument would receive an empty one, describe every span as
        ``SYSTEM_SELECTED``, and compare unequal to an approved binding whose spans
        said ``USER_AUTHORED`` — refusing every resumed call whose user typed
        anything.

        **The second is transcribed for the same reason, arriving at a second
        field** (ADR-0181 §3's fifth and sixth clauses, which narrow ADR-0152 §7's
        count from exactly one to exactly two and narrow nothing else in it). The
        fact is about a **selection** this system made before the confirmation was
        parked, and ``rebind`` receives no selection set to recompute it from. A
        member that re-derived it would answer ``False``, compare unequal to every
        approved binding carrying ``True``, and refuse every resumed egress call
        planned over external material — which is precisely the call the user was
        asked about and approved. It is **not** re-derived, **not** defaulted and
        **not** omitted, and the fix a lane would otherwise reach for is to stop
        comparing.

        **The count is five** (ADR-0152 §7:1 and ADR-0247 §7:1 as ADR-0321 §10 counts
        them): ``coverage`` (ADR-0233 §4), ``closed_loop`` (ADR-0247 §7) and
        ``forecast_reach`` (ADR-0321 §4:16) are transcribed from ``approved`` too, for
        the same reason, each a fact about the composition that was shown and approved
        that this member receives nothing to recompute. ``forecast_reach`` is what lets
        an approved forecast read rebind equal to the binding that was shown.

        **Re-deriving and comparing uses ADR-0148 §6's determinism clause rather
        than working around it.** That clause forbids a binding being derived
        *after* the ruling and re-derived *at the seam*; this derivation happens
        **before** ``resolve``, and "the seam" there is the transmitting seam — the
        callable reached by :meth:`ToolInvoker.invoke`, which this touches not at
        all. §6 states the positive form in terms: the description is deterministic
        so that "the approver, the seam and a later auditor can each re-derive and
        compare". This is that comparison, performed by the component that has both
        values.

        **The account, the endpoint and the connectability are re-derived too**, so
        a registry rebuilt under a different configuration, or a reference that
        went ``PENDING`` while the ``CONFIRM`` was parked, refuses here rather than
        at the callable — one stage earlier and before a second ruling is recorded,
        which is ADR-0148 §1's stated direction of moving facts earlier. ADR-0148
        §6's four-way refusal at transmission is unchanged and is not made
        redundant: it is the check that runs after the second ruling, on a fact
        that can move between the ruling and the transmission.

        Args:
            tool: The confirmation's own embedded definition, subject to the same
                registry-original comparison :meth:`bind` describes.
            parameters: The step's parameters, unaltered, as :meth:`bind`.
            approved: The binding the parked ``CONFIRM`` carries, or ``None`` where
                the recorded decision carried none. Revalidated and detached like
                every other argument when it is not ``None``.

        Returns:
            The **derived** binding — never the one it was given — beside the
            detached ``tool`` and ``parameters`` it was derived under, so ADR-0037
            §4's rebuilt request is built from the same pair on the resuming path
            as on the first. Or ``None``, on exactly the condition :meth:`bind`
            states, when ``approved`` is ``None``.

        Raises:
            EgressBindingError: On every refusal :meth:`bind` states, and on three
                more this member alone can meet. The derived binding is not
                **equal** to ``approved`` — equal as ADR-0150 §9 compares a
                binding, whole and by value — which is what makes ADR-0150 §12's
                forged-canonical case reachable: a decision read back out of the
                trail carrying an occurrence whose canonical form is not what this
                seam's canonicaliser computes is unequal to a freshly derived
                binding, and is refused before ``resolve``. A ``provenance`` in
                ``approved`` that cannot be matched — a derived span whose locator
                names no span of ``approved``, or a span of ``approved`` whose
                locator names no derived span — each being a refusal, never filled
                with ``SYSTEM_SELECTED``, since that default is :meth:`bind`'s
                answer for an origin nobody recorded and using it here would
                silently convert a disagreement about the payload into an
                approved-looking description. And ``approved`` not ``None`` for a
                tool this seam holds **no** egress registration for: a recorded
                decision stating an egress call and a registry stating a non-egress
                tool disagree about what was authorised, and the answer to a
                disagreement is a refusal rather than the weaker of the two
                readings.
            ConnectionStoreError: As :meth:`bind`. Connectability is read afresh
                here too and never carried over from the moment the ``CONFIRM`` was
                asked.
            CancelledError: If the calling task is cancelled from outside.
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
    * **A call planned over recorded external content is never ``ALLOW``ed except
      on a decision of the user about that call** (ADR-0181 §5). No ruling this
      contract returns is ``ALLOW`` on a request whose ``egress_binding`` carries
      ``planned_with_external_content``, except under ADR-0148 §3's route (a) — the
      user's own answer about **that** request. No standing user policy and no
      standing grant covers such a call, whatever a later ADR permits for calls
      that do not carry it, and ADR-0154 §4's standing-authorisation floor is
      unchanged and unlifted by it.

    **That obligation binds** :meth:`decide` **and** :meth:`resolve` **separately,
    and each over the facts its own member receives**, which is why it is stated
    on both below rather than once here. No implementation discharges it on one
    member and not the other, and none reads ``decide``'s unavailability of route
    (a) as licence to relax the rule on ``resolve``. It is not a refusal: the call
    is still put to the user, with the fact in front of them (ADR-0181 §6), which is
    the containment #668 asks for. And no implementation acquires a trail read, a
    store handle or a grant seam **in order to discharge it** — ADR-0097 §7 forbids
    consulting either *source*-grant seam outright, so this obligation is
    discharged from the request.

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

        Must return ``authorised_by is None`` from a policy constructed with
        **no** authorisation source, so no such implementation can invent an
        authorisation while ruling on a fresh request. **Must return
        ``authorised_subject is None`` from every policy** (ADR-0321 §7:7): the
        field fingerprinted a standing recipient grant, recipient grants retired
        (§7:1), and no policy has a grant seam to read one from.

        **It returns no ``ALLOW`` at all on a request whose ``egress_binding``
        carries ``planned_with_external_content``** (ADR-0181 §5's third clause).
        This member holds an ``ActionRequest`` and no ``AuditTrail``, so ADR-0148
        §3's route (a) — a decision of the user about *this* request — is
        unavailable to it by construction: no resolution about the request exists
        yet, and the obligation is therefore discharged by returning ``CONFIRM`` or
        ``DENY``. The boundary is part of the rule: a request whose binding carries
        ``False``, and a request carrying no binding at all, are judged on the
        ordinary path and are not refused by it.

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
        * **Where ``confirmed.egress_binding`` carries
          ``planned_with_external_content``, an ``ALLOW`` requires ``approved`` to
          be true** (ADR-0181 §5's fourth clause). This member holds the recorded
          decision and the user's answer and **no request**, so its obligation is
          stated over exactly those two; ``approved`` being false yields ``DENY``
          as the first obligation above already requires, and the clause adds no
          new refusal to the approving path — the user's answer about that call
          *is* route (a). Nothing here obliges this member to compare a binding
          against a request, and no lane widens this Protocol to let it: that
          comparison exists one seam out, on
          :meth:`~ai_assistant.core.types.PermissionDecision.authorises`, over the
          binding as one whole.
        * **A ``confirmed`` whose ``egress_binding`` is an**
          :class:`~ai_assistant.core.types.OriginUnrecordedBinding` **must not
          produce an ``ALLOW``, whatever ``approved`` says** (ADR-0184 §7). The
          origin of such a call cannot be established at all — ADR-0181 §3 forbids a
          default and §4's second clause forbids a seam inventing one — and ADR-0181
          §5's second clause then leaves no route by which any authorisation covers
          it, the user's own answer included. It is a **floor rather than a route
          that exists**: nothing in the tree hands such a row here today, and ADR-0021 §5's
          "fail-closed twice over" is why the clause is written anyway — a floor is
          worth having because it holds when a route appears, and this one is
          checkable on any implementation without knowing its rules. ``decide``
          gains no matching clause and no lane adds one, because
          :attr:`~ai_assistant.core.types.ActionRequest.egress_binding` stays narrow
          and the case is unconstructable at that member (ADR-0184 §2, §7).
        * **A ``confirmed`` whose ``egress_binding`` is a**
          :class:`~ai_assistant.core.types.CoverageUnrecordedBinding` **must not
          produce an ``ALLOW``, whatever ``approved`` says** (ADR-0233 §14). ADR-0184
          §7's floor extended **by cause** and for §7's own reason: the fact the
          ruling would rest on was never recorded, so nothing says which of ADR-0155
          §3's two prohibitions governs what such a call would carry, and no
          authorisation — the user's own answer included — supplies one. The clause
          is stated separately rather than inherited because the origin guard does
          not catch this epoch: such a row **has**
          ``planned_with_external_content``, so it is not an
          ``OriginUnrecordedBinding`` and trips no ``isinstance`` written for that
          class. It is a floor on the same terms as the clause above — nothing in
          the tree hands such a row here today either — and ``decide`` gains no
          matching clause for the same reason.

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
class InvocationCompleter(Protocol):
    """The narrow face over the trail's invocation rows: completions only (ADR-0192 §2).

    **A capability distinction, and the narrow face is what makes it a type rather
    than a promise.** ``orchestration``'s recovery scan, retired at the cutover
    (ADR-0309 §5), completed open claims and **must not** claim (ADR-0192 §3), so it
    was handed this and nothing more — a dependency that cannot express the call. That
    is ADR-0029 §1's rule read where it points, and the corpus has paid for the narrow
    face three times on the identical argument: ADR-0125 §1 for ``Secrets`` beside
    :class:`SecretStore`, ADR-0149 §1 refusing a tool the power to provision itself, and
    ADR-0153 §2 for ``ConnectionPurger`` beside ``ConnectionProvisioner``.

    **One object satisfies this, :class:`InvocationLedger` and
    :class:`AuditTrail`**, over one store, and the composition root hands each
    consumer the face its job needs. Two tables keyed by the same decision could
    diverge, and the consume would then bound one of them (ADR-0029 §8).

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060), and how a call observes its inputs by the input-observation clause
    (ADR-0065).
    """

    async def complete_invocation(
        self,
        *,
        claim_id: DurableIdentifier,
        outcome: ToolOutcome,
        incurred_cost: ToolCost,
        failure_kind: ToolFailureKind | None = None,
    ) -> ToolInvocation:
        """Append the completion of ``claim_id`` and return the stored row.

        **One atomic store operation**, deciding every refusal below inside the
        same act as the append — never a check followed by an ``await`` and then a
        write. The row's ``id`` is minted here from the ledger's injected
        identifier factory and never accepted from a caller, and ``recorded_at``
        is stamped here from a guarded ``Clock`` (ADR-0026), one reading per
        append. ``decision_id`` is set from the claim being completed, so the two
        cannot disagree.

        **Stores a detached, validated snapshot** of what it was given, recursively
        over reachable mutable state, and **returns a row detached** from the one
        the store holds. ADR-0021 §4 made both rules for ``record`` and the
        premise is the same here: ``frozen=True`` bounds the ordinary write path
        and not ``__dict__``, so a retained or aliased object would rewrite
        history through a pointer this contract itself hands out. ``incurred_cost``
        is the live object at the end of the chain that clause names, so a shallow
        copy would share it.

        Args:
            claim_id: The claim this completes, learned from the row
                :meth:`InvocationLedger.claim_invocation` returned.
            outcome: What ADR-0029 §§3-4 computed for the exit.
            incurred_cost: What the invocation cost — the figure the tool
                reported, or a ``ToolCost`` whose basis is ``UNKNOWN`` where it
                reported none (ADR-0192 §5). Never ``ToolDefinition.cost``.
            failure_kind: Transcribed from the ``ToolResult`` that carried one,
                and **never synthesised**. A completion derived from an exception
                carries none, because no result was produced to transcribe from:
                ADR-0031 §3 rules that the seam never synthesises ``CANCELLED``,
                and no other member describes an externally delivered
                cancellation. The absence is the honest value.

        Returns:
            The stored completion row, detached.

        Raises:
            AuditError: If an argument is not valid — which includes a
                ``failure_kind`` supplied with a ``SUCCEEDED`` outcome, the one
                combination ``ToolInvocation``'s shape forbids — or if the guard
                rejects the clock's reading, or the store cannot be read or
                written. An exception the injected clock or identifier factory
                **callable itself** raises propagates unwrapped instead, its type
                and cause intact (ADR-0026 §2).
            InvalidCompletionError: If ``claim_id`` names no recorded claim, or
                names one a completion already names. **In this order and no
                other**: an argument fault first, then this. It never raises
                ``UnrecordedAuthorisationError`` — a completion names a claim, and
                the claim already names the decision.
        """
        ...


@runtime_checkable
class InvocationLedger(InvocationCompleter, Protocol):
    """The wide face: the narrow one plus the claim (ADR-0192 §2).

    ``tools/`` holds this, because ``ToolInvoker.invoke`` claims and completes. It
    inherits rather than stands beside for ADR-0125 §1's reason exactly — the wide
    face genuinely *is* the narrow face plus one member, so one object satisfies
    both and there are not two implementations to drift apart.

    **A ``ToolInvoker`` holds this and never an :class:`AuditTrail`.** The ledger
    can neither record a ``PermissionDecision``, nor read one, nor export, nor
    ``clear``, so no decision write, no history read and no erasure reaches
    ``tools/`` through this seam. Handing the invoker the whole trail would put all
    four into a subsystem the architecture map gives integrations, which is the
    shape ADR-0017 §8 wants to move away from.
    """

    async def claim_invocation(self, *, decision: PermissionDecision) -> ToolInvocation:
        """Append a claim under ``decision`` and return the stored row.

        **The append is the consume** (ADR-0192 §1). It is one atomic store
        operation, every refusal below is decided inside it, and a call whose claim
        is refused does not reach the callable. Two concurrent ``invoke``s on one
        decision reach one atomic append: one claims, the other is refused —
        ADR-0021 §4's own answer to the identical race, one seam later.

        **The whole decision is passed, not its id alone, and the store requires
        the two to be equal.** An id lookup admits a caller who takes the id of a
        recorded, harmless ``ALLOW`` and builds a second ``ALLOW`` carrying that id
        and a dangerous ``ToolDefinition``: the dangerous callable runs and the row
        then reports the harmless tool, which is worse than an unrecorded execution
        because it is a *misrecorded* one. The row stores the ``id`` and no other
        part of the value; the equality is what makes the id mean the decision.

        **What is spent is the authority to begin a further act, and nothing
        else.** No recorded row is removed, rewritten, hidden, expired or
        invalidated; ``PermissionDecision.authorises`` stays the pure comparison
        ADR-0021 §1 made it, answering identically before and after a claim.

        **An authorisation is spendable** when the decision's ``ToolDefinition`` is
        ``side_effecting`` and its ``idempotency`` is not ``NATURAL`` — ADR-0029
        §5's own discriminator. Otherwise no claim under it is ever refused on the
        ground that it is spent: a read gated by ADR-0016 §3 is invoked under one
        ``ALLOW`` as often as the pipeline needs it.

        On a spendable authorisation a first claim is admitted, and a **further**
        claim only where every one of these holds: no claim under that decision is
        open; **no** claim under it carries the outcome ``SUCCEEDED`` or
        ``INDETERMINATE``; the last claim in the ledger's own append order for that
        decision is completed ``FAILED`` with a recorded ``failure_kind`` whose
        ``retryable`` is true; the definition's ``idempotency`` is ``KEYED``; and
        the elapsed time from the **first** claim in that order to this one is
        strictly less than ``idempotency_window``. That is ADR-0029 §5's two-part
        retry conjunction transcribed onto the store rather than a looser one
        beside it — an ``Idempotency.NONE`` side-effecting tool gets exactly one
        claim, ever, whatever the failure kind.

        **An open claim refuses a further act, so completion durability is a third
        prerequisite for ADR-0029 §5's retry** (ADR-0192 §1, §7). Where a
        completion append fails before committing, the claim stays open and the
        next claim is refused twice over. That is the direction this member fails
        in everywhere: an open claim is an act that may have run at an outcome
        nobody observed.

        "First" and "last" are the ledger's own **durable append order** for that
        decision, never an ordering over ``recorded_at``. A stored instant is what
        a reader is shown; the order is what the rule is decided on, and a wall
        clock that steps backwards must not be able to make a completed act stop
        being the most recent one. The instant is taken from a guarded ``Clock``
        (ADR-0026) in **exactly one reading per append**, and that one reading is
        both what the admission is decided on and what the row stores — two
        readings would let a retry be admitted inside a window and stamped outside
        it. Any reading of the elapsed time that is not a positive duration is
        treated as the window having lapsed and the claim is refused, and a clock
        that raises refuses the claim too: ADR-0029 §5's fail-closed rule for the
        same measurement, enforced where the rule is.

        Args:
            decision: The authority for the act, by value.

        Returns:
            The stored claim row, detached. Its ``id`` is what the caller passes as
            :meth:`InvocationCompleter.complete_invocation`'s ``claim_id``, and it
            holds it nowhere else.

        Raises:
            AuditError: If an argument is not valid, or the guard rejects the
                clock's reading, or the store cannot be read or written, or the
                identifier factory returns a colliding id until the redraw bound is
                spent. An exception the injected clock or factory **callable
                itself** raises propagates unwrapped (ADR-0026 §2).
            UnrecordedAuthorisationError: If the store holds no decision under that
                id, holds one that is not equal to the decision passed, or holds
                one whose ruling outcome is not ``ALLOW``.
            AuthorisationSpentError: If the consume above refuses. **In this order
                and no other**: an argument fault, then the unrecorded
                authorisation, then the spend.
        """
        ...


@runtime_checkable
class AuditTrail(Protocol):
    """The append-only record of what the permission layer decided, and of what ran.

    ADR-0021 §4 minted it for the rulings. ADR-0192 §2 gives it a **second row
    kind** — a ``ToolInvocation``, appended twice per attempt through
    :class:`InvocationLedger`, which one object satisfies alongside this — so the
    trail now says both what was permitted and what was done under it. §4 of that
    ADR partially supersedes ADR-0021 §4's "It bounds resolutions, not executions":
    the trail holds executions, and the consume that section deferred to "the
    invocation contract" is the ledger's claim.

    The three reads below join a row to its decision or answer the recovery
    question; the writes are on the ledger faces, which is what keeps every history
    read and ``clear`` off the seam ``tools/`` holds.

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

    **A history read hands back what the row says, including a binding recorded
    before a member of :class:`~ai_assistant.core.types.EgressBinding` existed**
    (ADR-0184 §5, ADR-0233 §14). ``get``, ``recent`` and ``export`` return such
    a decision — carrying an
    :class:`~ai_assistant.core.types.OriginUnrecordedBinding` for a row written
    before ADR-0181 §3's ``planned_with_external_content``, or a
    :class:`~ai_assistant.core.types.CoverageUnrecordedBinding` for one written
    before ADR-0233 §4's ``coverage`` — as history, rather than failing; and a
    ``recent`` or an ``export`` over a trail holding one returns it **together
    with** every other row, which is the all-or-nothing failure that closes. A
    history read states what was recorded. Every *other* unreadable row is
    reported exactly as before; the
    tolerance is exactly as many shapes wide as there are epochs (ADR-0184 §1,
    ADR-0233 §14).

    That obligation is stated here and pinned in each implementation's own tests
    rather than in the shared conformance suite, for ADR-0049 §5's reason: it is a
    property of a store that persists a **serialised payload** and rebuilds it, and
    a fake holding objects has no bytes for a shared case to seed. ``record``'s
    refusal of the same shape is a different matter and *is* in the suite, because
    a test can construct such a decision directly.

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

        **"Already present" is read over every row the store holds, of either
        kind** (ADR-0192 §2). A decision whose ``id`` names a claim or a completion
        is refused ``AuditError``, inside this member's own atomic act and by the
        same comparison the ledger's collision check makes. Without it the
        invariant would hold only against ids the ledger mints, and a caller
        choosing a decision id equal to a claim's would put two records under one
        identifier from the other side — which ``recent_invocations``' join then
        resolves to two different rows. Nothing a caller could rely on is narrowed:
        a ``DurableIdentifier`` is the caller's to mint, and the store already
        refused a duplicate decision id. Before ADR-0192 the store held one row
        kind, so "already present" had one reading; the rule is extended onto the
        kind that ADR adds rather than changed.

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
        no other recorded decision already resolves it, its ``tool`` and
        ``parameters_digest`` match the incoming decision's exactly, and it was not
        decided *after* the resolution answering it (equal timestamps are fine — a fast
        confirmation at a coarse clock resolution is real). The authorisation pointer is
        checked here too: a resolving ``ALLOW`` must carry ``authorised_by`` equal to
        its ``resolves``, and a resolving ``DENY`` must leave it unset. Without that
        pair, a resolving ``ALLOW`` could name any confirmation it liked — or a string
        naming nothing — while satisfying every other check, and the disclosure floor
        would be satisfiable by fabrication.

        **ADR-0044 §2b's per-binding rule left with the step and the execution a
        decision no longer carries** (ADR-0318 §6:1), so only the per-confirmation rule
        above applies (ADR-0036 §2).

        This bounds **resolutions, not executions**, and the difference is worth
        being precise about: ``authorises()`` is a pure comparison, so the same
        resolved ``ALLOW`` answers ``True`` every time it is asked. Making an
        approval single-*use* needs an atomic consume-on-execution step, which
        belongs to the invocation contract. "Approve once" means the question is
        settled once, not that the answer is spent on exactly one call.

        **Refuses a decision whose ``egress_binding`` is an**
        :class:`~ai_assistant.core.types.OriginUnrecordedBinding` **or a**
        :class:`~ai_assistant.core.types.CoverageUnrecordedBinding` (ADR-0184 §4,
        ADR-0233 §14), with the trail's existing ``AuditError`` for a decision that
        is not a valid record and no new error class. ADR-0184 §4's second clause
        extended **by cause**, exactly as ADR-0184 §7's floor is: each shape
        represents a row written in an epoch that has ended — before ADR-0181 §3
        added ``planned_with_external_content``, or before ADR-0233 §4 added
        ``coverage`` — so each is only ever **read** out of a store and never minted
        into one. ``PermissionDecision.from_request`` gains no route to either,
        because :attr:`~ai_assistant.core.types.ActionRequest.egress_binding` stays
        narrow, so every live path is closed by construction and ``record`` is the
        floor for a caller that assembles a decision by hand: a caller bypassing
        ``PermissionDecision.from_request`` could otherwise construct such a
        decision and append it, minting a new row in an epoch that has ended — a
        fabrication of *history*, and the harder one to notice later than a
        fabricated value. This is a refusal of the same kind as the three above,
        and for ADR-0021 §4's reason: ``record`` is the boundary where the whole
        record is in hand. It does not contradict the rows that already exist —
        they were written when that shape *was* the current shape, which is the
        whole point of representing them rather than accepting new ones.

        **Refuses an ``ALLOW`` whose ruling carries an ``authorised_subject``,
        resolving or not** (ADR-0321 §7:7). The field fingerprinted the standing
        recipient grant a route-(b) ``ALLOW`` rested on, and recipient grants
        retired (§7:1): with no grant left to read, a decision carrying a digest
        claims an authorisation nothing can now establish, and no implementation is
        constructed with a grant seam to resolve one against. A **resolving**
        ``ALLOW`` carrying one was already refused — route (a) rests on a
        confirmation, which is not a grant and has no subject digest — and the
        refusal is now the same on both sides. ``record`` takes it from the
        decision alone, with no store read and no clock.

        **The route-(a) checks are unchanged** (ADR-0321 §4:7, §9): the resolution
        invariant above and the authorisation pointer's pairing hold exactly as
        before, and the yes path rests on them.

        **Validates a route-(c) standing row against the binding on the row, and
        reads nothing else for it** (ADR-0247 §2, ADR-0272 §1). A non-resolving
        ``ALLOW`` carrying an ``egress_binding`` and an ``authorised_by`` with
        **no** ``authorised_subject`` is accepted **only** where **exactly one** of
        its binding's ``closed_loop`` and ``forecast_reach`` is ``True`` **and** its
        ``authorised_by`` equals that binding's ``account.reference``; failing
        either, it is refused with the ``InvalidAuthorisationError`` the ``Raises:``
        section below names. Both facts are read **from the decision** — no store
        read, no ``Settings`` read and no clock — and the trail holds no
        configuration and is given none: the comparison of the binding's account
        and origin against what the owner configured is the policy's, taken where
        the configured values live.

        **Exactly one, because the eligibility fact is the kind's own** (ADR-0272
        §1). Each kind route (c) covers carries its own — ``closed_loop`` for a
        ``WEB_SEARCH``, ``forecast_reach`` for a forecast read (ADR-0260 §11) — so a
        binding carrying **neither** is of no kind this route covers, and one
        carrying **both** asserts a kind route (c)'s closed two-member set does not
        contain; admitting either would let one kind's authority be read off the
        other's. The digest's **absence** remains the *discriminator* and neither
        fact does its work: **which** rows are route (c) is unchanged, and what this
        states is what makes a route-(c) row **eligible**.

        Raises:
            AuditError: If the decision is not a valid record, which includes one
                carrying an ``OriginUnrecordedBinding`` or a
                ``CoverageUnrecordedBinding``.
            DuplicateDecisionError: If a decision with this ``id`` is already
                recorded.
            InvalidResolutionError: If ``resolves`` is set and the invariant
                above does not hold.
            InvalidAuthorisationError: If an ``ALLOW``, resolving or not, carries
                an ``authorised_subject``; or if a route-(c) decision carries a
                binding that records no origin, that does not carry exactly one of
                ``closed_loop`` and ``forecast_reach``, or a pointer that is not
                that binding's ``account.reference``.
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

    async def recent_invocations(self, *, limit: int = 50) -> list[RecordedInvocation]:
        """Return up to ``limit`` invocation rows, newest first, ties broken by id.

        ADR-0192 §2's first joined listing. It carries :meth:`recent`'s total
        order, its bounded default and its ``ValueError`` on a ``limit`` that is
        not strictly positive.

        **The row is joined to its decision inside one atomic store operation**, so
        every value returned is complete. No consumer assembles one from two reads
        and no implementation returns a row it could not pair: the tool's identity
        lives on the decision, and an engine reading rows and then reading
        decisions has an ``await`` between the two that a :meth:`clear` can land
        in.

        Returns a detached snapshot, as every other read here does (ADR-0018 §3).

        Raises:
            ValueError: If ``limit`` is not strictly positive.
            AuditError: If the trail cannot be read.
        """
        ...

    async def export_invocations(self) -> list[RecordedInvocation]:
        """Return a portable snapshot of every invocation row (ADR-0004 §6).

        The unbounded twin of :meth:`recent_invocations`, in the same order and
        joined the same way. It discharges ADR-0004 §6's portability obligation for
        this row kind, which :meth:`export` does for the decision rows and — after
        ADR-0192 §2 — for those alone: the obligation is met by the pair, and there
        is no single whole-trail export.

        Raises:
            AuditError: If the trail cannot be read.
        """
        ...

    async def open_invocations(self, *, decision_id: DurableIdentifier) -> list[ToolInvocation]:
        """Every claim under ``decision_id`` that no completion names (ADR-0192 §2).

        In the ledger's append order, as detached snapshots, from one atomic store
        operation. **It takes no ``limit``**: it is not a history read but the
        exact set ADR-0192 §3's recovery rule is written against, and a bounded
        answer would let a scan transition over claims it never saw.

        **A recovery query belongs with the store that owns the record**, which is
        ADR-0044 §3's move and not a new one — a
        restarted process asking the trail for the record it can no longer name by
        id. It goes here and never on :class:`InvocationLedger`, because the ledger
        is what ``tools/`` holds and a by-decision query over past claims is a
        history read. ``orchestration``'s recovery scan was its only consumer, and
        retired at the cutover (ADR-0309 §5).

        **It reserves every claim id it returns.** The store hands each to the same
        identifier factory the ledger mints from, and that factory returns none of
        them for the life of the process, exactly as it returns none it issued
        (ADR-0192 §2) — otherwise a claim ``clear()`` erased could be reissued to a
        later claim and receive the completion the scan is still holding, recording
        one call's outcome and cost against another's. The reservation is taken
        **inside the same atomic operation that reads the claims**, never after it,
        so an erasure and a fresh claim cannot land in the gap. It is
        store-internal: no id crosses a subsystem boundary to be reserved, and no
        consumer is given a reservation call. The two history reads above reserve
        nothing and need not — a surface completes no claim, so an id it holds can
        misdirect nothing.

        Args:
            decision_id: The authorisation whose open claims are wanted.

        Returns:
            The open claims, in append order, detached. Empty where none is open,
            which states that no call was in flight.

        Raises:
            AuditError: If the trail cannot be read.
        """
        ...

    async def clear(self) -> int:
        """Delete every row in the trail, returning the number removed.

        Wholesale erasure is a different act from selective deletion: it
        destroys the trail visibly and completely, which is what a data-rights
        operation should look like (ADR-0004 §6).

        **It erases both row kinds and counts both** (ADR-0192 §6). No operation
        erases one kind and leaves the other, and no surface offers one:
        "the user may burn the book; nobody may tear out a page" is a rule about
        one book, and two erasure acts over one store would let a user destroy the
        executions and keep the rulings.

        **It erases the consume with everything else.** A decision re-recorded
        after an erasure has no claim under it, so a claim under it is admitted —
        including where the value is byte-for-byte the one that was spent before.
        That is not a hole to be closed: the consume *is* a row, and a rule
        surviving the erasure of the rows it is made of would be a second,
        undeletable record of an act the user asked to have erased. No generation,
        epoch, tombstone or high-water mark is minted to narrow it.

        It wins any race with an in-flight invocation: a completion whose claim it
        erased is refused ``InvalidCompletionError`` like any other completion
        naming no claim, and nothing is recreated.
        """
        ...


@runtime_checkable
class SpendGate(Protocol):
    """Decides, before an act, whether the world may cost this much (ADR-0194 §3, §5).

    ``ToolInvoker.invoke`` holds one and **never** a :class:`SpendLedger`: an
    invoker able to read a totals projection has acquired a permissions-owned
    history it has no use for, which is ADR-0029 §1's argument one seam over. It
    appends no row, writes no durable state, and can neither record nor read a
    ``PermissionDecision``, neither export nor ``clear``.

    **Where the invocation is decided, and why not at the policy.**
    ``ActionPolicy.decide`` already reads ``ToolCost`` and looks like the home for
    a cost rule; two things forbid it. A ceiling check needs a running total (a
    store read) and a period (a clock read), and ADR-0021 §5's monotonicity and
    floor obligations are checkable only because ``decide`` is a genuine function
    of its argument. And a ruling cannot bind a total that moves after it: a
    ``CONFIRM`` is answered at human speed, and between the ruling and the act
    other calls complete and a calendar period can roll over. The only instant at
    which the answer is true is the instant before the act.

    **What the decision reads, exhaustively** (ADR-0194 §3): the ``ToolCost`` it is
    handed; the four configured spend values with the zone that selects the period;
    the instant read from the injected clock; and the rows and reservations the
    holder holds. Nothing else conditions it — not the calling subsystem, not the
    tool's identity, not a capability, not a protocol — and **no caller-controlled
    value**: there is no parameter, argument, header or configuration by which a
    caller obtains an invocation the ceiling would refuse, and no override, bypass
    or force flag exists to be reached for.

    Cancelling either method is governed by this module's cancellation clause
    (ADR-0060), and how a call observes its inputs by the input-observation clause
    (ADR-0065).
    """

    async def admit_invocation(self, *, estimate: ToolCost) -> SpendAdmissionHandle:
        """Admit this invocation and reserve its declared contribution, or refuse.

        **Where neither ceiling is configured this returns before it reads the
        clock, reads the store or performs any arithmetic**, takes no reservation,
        and cannot refuse — not on a crossed ceiling, not on a raising clock, not
        on a failed store read, not on a trapped computation. That is what makes
        ADR-0194 §1's "no ceiling configured means no ceiling" unconditional in
        fact and not only in wording.

        **Where at least one is configured** it compares the *projected* total
        against each configured ceiling for the period containing the invoker's
        current instant, and refuses where the projection is **strictly greater**
        than one. A projection exactly equal to a ceiling is admitted. The
        projection is the period's accounted total, plus the declared amounts of
        **every** reservation this holder is still holding — whichever period each
        was taken in, since a call admitted before a boundary can complete after it
        — plus ``estimate``'s own declared amount. Every declared amount is used for
        this arithmetic alone: none is added to an accounted total and none is
        written to any row (ADR-0194 §2).

        **The store read, the comparison and the reservation are one critical
        section**, with no other admission interleaved and **no release taking
        effect inside it either**. The Nth concurrent invocation sees the N-1
        reservations already taken and cannot project a total that omits a call
        already admitted. A release that lands between an admission's row snapshot
        and its comparison is the single interleaving that can under-count, so a
        recorded release takes effect at the **start of the next** critical
        section, before that admission's snapshot.

        **The holder mints the handle** (ADR-0194 §3). An injected id factory
        supplies candidate values and nothing more: a candidate the handle type
        would refuse, and a factory raising an ``Exception``, are each replaced by a
        value the holder generates itself — neither reaches the caller and neither
        costs the call. No value this holder has **ever delivered** is delivered
        again, over its whole lifetime and not merely among the outstanding set: a
        re-minted retired value would make a stale release drop a *live*
        reservation, after which a later admission projects a total omitting a call
        already in flight. The mint sits on the far side of the comparison, so a
        refusal consults no factory at all.

        **A reservation is in-memory state of the holder** — never a row, never
        durable, never a ``PermissionDecision`` — and is discarded when the process
        restarts, which is the one way an unreleased one ever ends. Between a
        completion's append and its release the same call is counted twice, once
        accounted and once reserved; that direction is deliberate, the mechanism
        over-counting for one operation rather than under-counting for one.

        **It runs inside the deadline ``invoke`` already enforces** (ADR-0029 §4),
        never outside it: an admission outside the deadline would move the one await
        that deadline exists for out of its reach. What that buys is what ADR-0029
        §4 buys and no more — the seam stops waiting, not that the gate stops
        working — and a store read that suppresses its own cancellation can outlive
        the deadline exactly as §4's third bullet already says.

        Args:
            estimate: The **pinned declaration** — the ``cost`` on the
                ``ToolDefinition`` the call's recorded ``PermissionDecision`` pins,
                read off the revalidated, detached copy ADR-0029 §2's checks
                produced and never off the argument a caller passed. It is not
                caller-supplied: a turn cannot author it and a tool cannot restate
                it between the ruling and the call. **No tool identity is taken**:
                the admission is not conditional on which tool is calling, so the
                seam is given nothing it must not read, and two tools declaring the
                same cost are deliberately indistinguishable here.

        Returns:
            The handle for the reservation this admission took, valid until it is
            released. Where no ceiling is configured no reservation was taken and
            the handle is a value the release accepts and ignores.

        Raises:
            SpendCeilingError: If a configured ceiling would be crossed, and only
                then. Never raised for a spend that could not be measured.
            SpendUndeterminedError: If the spend the admission needed could not be
                reduced to a number, on ADR-0194 §4's six grounds in that
                section's order — the declared amount is not countable; the
                declared cost has no number at all; the clock raised; the store
                read failed; the period is indeterminate; the arithmetic trapped.
                A backend exception is translated rather than propagated, so
                ``tools/`` never sees a store's own error type.

        No other ``Exception`` escapes: minting the handle adds no third class, and
        neither a ``ValidationError`` nor an id factory's own exception reaches the
        caller. A ``BaseException`` that is not an ``Exception`` — a
        ``CancelledError`` delivered from outside above all — propagates unchanged
        and is never translated into either class, and where a reservation was
        already recorded it is **removed before the exception leaves the member**,
        so nothing is left that nobody holds a key for.
        """
        ...

    def release_admission(self, handle: SpendAdmissionHandle) -> None:
        """Drop the reservation ``handle`` names. Synchronous, idempotent, silent.

        ``ToolInvoker.invoke`` calls this in a ``finally``, after ADR-0192's
        completion has been appended or after the failure that prevented it. **It
        raises no ``Exception`` at all**: an unknown handle and a handle already
        released are each a no-op, and a ``finally`` that raised would replace the
        call's own outcome with a book-keeping failure.

        **Synchronous because it is not I/O-bound and must not become so**, which
        is ``CLAUDE.md``'s own rule for the choice (ADR-0194 §5). It is given no
        store, no I/O and no lock a store read is held under, so there is nothing
        for it to await, and symmetry with the member above is not a ground that
        rule recognises. The asymmetry buys three properties an ``async`` release
        only approximates. It **cannot be made to wait** — by construction rather
        than by clause: were a release made to wait on the admission's exclusion, an
        invocation whose callable had already returned would block in its
        ``finally`` behind another invocation's store I/O and outlast the
        ``timeout`` its own caller set. It carries **no suspension point**, so a
        ``CancelledError`` cannot be delivered inside it and no interleaving exists
        in which a release begins, is interrupted, and leaves the reservation
        standing. And the invoker's ``finally`` reaches it with no ``await``, so
        unwinding under a cancellation cannot lose the release.

        An ``async`` release containing no await would have all three in practice
        and none of them in the contract: a cancellation is delivered only at a
        suspension point, so a shared conformance suite could not drive a
        cancelled-release fixture against the implementations that conform.

        **What a release records is a reservation, not a value**, and which
        reservation it names is decided **when this is called** and never later
        (ADR-0194 §3). A handle identifying no reservation outstanding at that
        moment — an unknown value, or one already retired — is discarded there and
        then and nothing is recorded. Only the moment of *application* is deferred
        to the next admission's critical section. An implementation recording the
        raw value and matching it at application time loses a live reservation: a
        release of an unknown value queued while an admission is paused, that
        admission then minting the same value, and the queued entry retiring a
        reservation taken **after** the release that supposedly names it.

        A release **lowers no accounted total**: that is read from ADR-0192's rows,
        which this member does not touch.

        Args:
            handle: The handle ``admit_invocation`` returned for this call.
        """
        ...


@runtime_checkable
class SpendLedger(Protocol):
    """States what each calendar period has cost, and refuses nothing (ADR-0194 §5).

    ``AssistantEngine``'s spend read holds one and **never** a :class:`SpendGate`:
    an adapter able to call the admission has acquired the ability to spend a
    budget. Two Protocols rather than one because they have two consumers and
    neither needs the other's face.

    **One object implements this, :class:`SpendGate` and ADR-0192's ledger seam**,
    over one store, because all three read the same rows — two stores keyed by the
    same rows could disagree about a total, which is the failure ADR-0016 §7 named
    for two registries one seam over. The composition root is the sole constructor
    and sole wirer, and hands each consumer the face its job needs.

    **The accounted total is derived and nothing here is durable** (ADR-0194 §7).
    This mints no counter, no per-period row, no cached total and no marker that
    survives a restart; an implementation that caches recomputes from the rows and
    no cache is authoritative. So ``AuditTrail.clear()`` erasing the rows leaves
    every period a currency is configured for determinate at ``Decimal("0")``, and
    nothing preserves a total across an erasure.

    Cancelling this member is governed by this module's cancellation clause
    (ADR-0060).
    """

    async def spend_totals(self) -> tuple[SpendTotal, ...]:
        """Return one total per period, in :class:`SpendPeriod`'s fixed order.

        ``CALENDAR_DAY`` then ``CALENDAR_MONTH``, and **both** entries whatever is
        configured. ``async`` because it reads a store, which is ``CLAUDE.md``'s
        rule for an I/O-bound method.

        **Both entries are derived from one reading of the clock and one snapshot
        of the rows.** A conforming implementation does not read the clock twice,
        and does not compute one period's total, let a completion append, and then
        compute the other's: a day total of 10 returned beside a month total of 0
        states two facts that cannot both be true of one instant, and a clock read
        either side of a calendar boundary pairs periods that do not contain each
        other. The two entries are one observation of one moment. The weaker
        "the day total never exceeds the month's" is a *consequence* of one
        snapshot and not a test for it: a pair aggregated either side of an append
        can satisfy it while being a state no snapshot of the rows was ever in.

        **The accounted total of a period is the sum of the reported
        per-invocation costs on ADR-0192's completion rows recorded in it**, and
        nothing else contributes: not a ``ToolDefinition.cost``, not a
        ``PermissionDecision``, not a model call. Every row in the period counts,
        including the one whose reported cost carried the total past a ceiling and
        one whose outcome is ``INDETERMINATE``. Model-provider spend is out of
        scope and enters no total.

        **An indeterminate period is returned, not raised** — ``accounted=None``
        beside a present ``currency``. A period is indeterminate where an open
        claim falls in it, where a reported cost has no number this mechanism may
        add (an ``UNKNOWN`` basis or a foreign currency, with no allowance
        configured), where a reported amount is not countable, or where the
        arithmetic trapped. It is a state of one period, ends when that period
        does, and is recomputed from the rows rather than persisted as a flag.

        Where no currency is configured nothing is summed and no total is stated:
        both entries carry ``currency=None``, ``ceiling=None`` and
        ``accounted=None``, which is the *other* meaning of that absence.

        Returns:
            Exactly two totals, in ``SpendPeriod``'s declaration order. Each
            carries the bounds ADR-0194 §1's rule computes for its own period in
            the ledger's configured zone, and the offsets in force at those two
            instants — a producer obligation, deliberately not a validator on the
            model, because only the producer can compare against the rule rather
            than against a second implementation of it.

        Raises:
            SpendUndeterminedError: Only where the values cannot be produced at
                all — a store read that failed, or an injected clock that raised.
                A trapped sum is not that case: the other period's figure is still
                computable, so the affected periods come back indeterminate. A
                backend exception is translated rather than propagated, and a
                ``CancelledError`` delivered from outside propagates unchanged.
        """
        ...


@runtime_checkable
class SourceGrants(Protocol):
    """Answers what a source may be read for, and can create nothing (ADR-0097 §3).

    The query half of the grant seam. **Anything that drives a reader holds this
    and only this** — `orchestration`'s upcoming-event producer for
    :attr:`~ai_assistant.core.types.GrantScope.NOTIFY`, the one driver left since
    the ingestion stage (ADR-0294) and the facet adapter (ADR-0318) retired — as a
    **required constructor argument with no default**, so a composition that omits
    the gate does not type-check (ADR-0097 §5, ADR-0132 §2, ADR-0133 §5). The
    drivers that exist are not a closed set: ADR-0133 §2 fixes the axis at one
    scope per *consumer* of a reading, so another arrives with another consumer
    and with its own decision. The obligation stated in prose and honoured
    by review is the shape the retired ``IngestionStage``'s docstring called "a
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
        close the bypass: a caller granted ``NOTIFY`` alone could mutate ``scope``
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
    the hub's grant operations holds one** — no scheduler job, no pipeline stage
    and no reader driver (ADR-0097 §3, §9). It satisfies
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

    async def standing(self) -> list[SourceGrant]:
        """Every live grant in the store (ADR-0139 §2).

        :meth:`live`'s enumeration, and it is a *separate* member rather than a
        widening of anything: :class:`SourceGrants` stays at one member, because a
        driver asks about the one source it is about to read and a driver that
        could enumerate the store is one that could log or leak the set
        (ADR-0097 §3).

        **Answers a question no other member on either seam can.**
        ``AssistantEngine.grantable_sources`` enumerates the readers the *hub*
        holds, so a grant whose reader was unconfigured is absent from it;
        :meth:`recent` returns records and ADR-0102 §3 forbids deriving liveness
        from them; :meth:`live` needs the source's name before it can be asked.
        So without this a user can hold a live grant no surface reports, on a
        source they must already know the name of to withdraw.

        **Liveness is the ``revokes`` relation and nothing else** (ADR-0097 §4),
        exactly as :meth:`live` computes it. No implementation may derive it from
        ``decided_at``, from :meth:`recent`'s ordering, or from anything outside
        the store.

        **Complete or nothing.** It takes no argument, is not paged, admits no
        ``limit`` and no ``offset``, and no implementation may truncate, sample or
        elide its result: a page of what the user authorises reads as complete
        while omitting an authorisation, which is the failure ADR-0102 §3 refused
        one query over. The set is bounded by one live grant per source (ADR-0097
        §4) and by the number of distinct identities ever granted, and it grows
        with those rather than with grant churn — which is the difference from
        :meth:`recent` and the reason :meth:`recent` keeps its ``limit``.

        **A store holding two live grants for one source answers with
        ``GrantError`` and answers nothing else**, as :meth:`live` already does
        for that source. It does not return both, does not choose between them,
        and does not return the sources it *could* answer for: two live grants
        make that source's authorisation unstatable, and a set with it omitted
        reads as complete and is not. A declared failure cannot be mistaken for
        an empty set, which is ADR-0097 §5a's fail-closed direction applied to an
        enumeration.

        Returns:
            A detached snapshot of every live grant, as every other query on this
            seam returns (ADR-0097 §4). **The order carries no meaning** — no
            caller may read a precedence, a recency claim or a liveness claim off
            a record's position — and an empty list means the store holds no live
            grant, never that it could not be read.

        Raises:
            GrantError: If the store cannot be read, holds a record that no longer
                validates, or holds two live grants for one source.
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
class SourceReadRecorder(Protocol):
    """Records that a source was read, and can answer nothing (ADR-0185 §4).

    The **write** half of the read seam. Anything that drives a reader holds this
    and only this — `orchestration`'s upcoming-event producer for
    :attr:`~ai_assistant.core.types.GrantScope.NOTIFY`, the one driver left — as a
    **required constructor argument with no default**, so a composition that omits the
    recorder does not type-check (ADR-0185 §5), on ADR-0097 §5's pattern for the
    gate itself.

    **The split from :class:`SourceReadTrail` is ADR-0097 §3's move, buying a
    different guarantee.** There ``record`` was removed from the driver's type so a
    scheduler job could not mint its own authorisation. Here the driver *must*
    write, so the capability removed is the other one — the ability to **read** the
    trail — and what that forecloses is the cursor ADR-0093 §5 forbids by name:

        A sensor's bound is a function of the clock, its configuration and the
        source's own content, and of nothing else. It may not be derived from
        durable state recording what previous runs read.

    A read trail is precisely durable state recording what previous runs read. A
    driver handed a queryable one is a driver that can ask "when did I last read
    this, and what did it produce" and skip, back off, or resume — the cursor
    ADR-0093 §5 removed, arriving through a store built for another purpose.
    Removing ``recent`` and ``export`` from the type the driver names makes that a
    ``mypy --strict`` failure instead of a review note.

    **It is a static guarantee and is stated as one**, exactly as
    :class:`SourceGrants` states its own. Structural typing means a concrete store
    satisfies both Protocols, so a composition root passes one object to a driver
    and to the hub's read-trail operations alike; what the driver cannot do is
    *name* ``recent``.

    **The two names are deliberately not close**, which is the opposite of
    :class:`SourceGrants`/:class:`SourceGrantStore`'s choice and right for the
    opposite reason (ADR-0185 §4). There the pair was named alike because the narrow
    seam is the safe one and the widening had to be visible at a constructor; here
    the *wide* seam is the dangerous one — handing a driver a
    :class:`SourceReadTrail` is handing it ADR-0093 §5's forbidden cursor — so the
    two should not be substitutable at a glance.

    **Never the liveness authority** (ADR-0185 §8). No read record is ever consulted
    to decide whether a source is granted, what a grant's scope is, or what a
    source's grant history is; :meth:`SourceGrants.live` remains the only answer to
    whether a read may happen. And the grant-management surface does not report
    reads: this ADR adds no member to :class:`SourceGrants` or
    :class:`SourceGrantStore`, and no client presents a read, a read count or a
    last-read instant beside a standing grant.

    Cancelling :meth:`record` is governed by this module's cancellation clause
    (ADR-0060), and the consequence is stated rather than left to be derived:
    **whether a cancelled attempt left a row is indeterminate where the
    cancellation landed inside a call already in flight**, because "a cancelled
    write may or may not have committed. The caller may assume neither." No
    component may assume either way, and no consumer reads the **absence** of a row
    as evidence that a read did not happen (ADR-0185 §1, §5a).
    """

    async def record(self, read: SourceReadRecord) -> str:
        """Append ``read`` to the trail and return its id.

        **Write-once**: re-recording an id already present raises rather than
        overwriting, for :meth:`AuditTrail.record`'s reason — a trail that upserts
        is one where history can be rewritten by replaying a write.

        **Atomic** over the duplicate check, the append and ADR-0185 §6's prune, for
        ADR-0021 §4's reason: without atomicity the single-write guarantee is a
        race, and a prune that is not in the same transaction leaves a window in
        which the store is over its cap.

        **Stores a detached, validated snapshot**, recursively over reachable
        mutable state, on :meth:`AuditTrail.record`'s reasoning: ``frozen=True``
        refuses ``read.outcome = …`` and not ``read.__dict__["outcome"] = …``, so a
        store retaining the caller's object would let an appended row be rewritten
        after the fact.

        **Called after the outcome is known, and before the reading is used**
        (ADR-0185 §5). No ``await`` on a recorder may stand between the ``live()``
        answer a driver gates on and its call to :meth:`Reader.read` — ADR-0097 §5's
        clause that "the check and the start of the read are one synchronous step"
        is unchanged — so the record for any attempt whose read ran is written after
        ``read()`` has returned or raised and after the re-check has ruled. Where
        this raises, the driver **discards the reading**: nothing is proposed, no
        facet is contributed, no candidate is concluded.

        Raises:
            ReadTrailError: If the record is not a valid one, if its id is already
                recorded, or if the store cannot be written. One class for all
                three, because the driver's recourse is identical (ADR-0185 §12).
        """
        ...


@runtime_checkable
class SourceReadTrail(Protocol):
    """The append-only record of every attempt to read a source (ADR-0185 §4).

    A Tier 1 local store, by ADR-0004 §7's own words as :class:`AuditTrail` already
    is, so ADR-0155 §1's residency clause governs it: implementations persist
    **locally only**, the file lives under ``Settings.data_dir`` and is created
    owner-only (ADR-0004 §4, ADR-0084 §9), and the hub owns it exclusively as it
    owns every other database in that directory (ADR-0083 §1, §10).

    **The wide seam, and the one nothing but the hub's read-trail operations
    holds.** It carries :meth:`SourceReadRecorder.record` with exactly the semantics
    stated there, so one ``permissions/`` class satisfies both Protocols
    structurally — the arrangement ``SqliteSourceGrantStore`` already has for
    :class:`SourceGrants` and :class:`SourceGrantStore`. This Protocol deliberately
    does **not** inherit :class:`SourceReadRecorder`: nothing in this file needs it
    to, and keeping them unrelated is what stops a driver's annotation from being
    widened by an ``isinstance`` habit.

    **Every query returns a detached snapshot** — the list, the records in it, and
    everything mutable those reach (ADR-0018 §3, ADR-0021 §4).

    **There is no ``update``, no ``get(id)``, no ``delete(id)``, no query by source
    and no count** (ADR-0185 §12). A selective delete is the page torn out of the
    book (ADR-0021 §4). A ``get`` has no consumer: nothing looks a read up by id. A
    per-source query and a count are the surface ADR's to ask for if it needs them,
    and adding them here would be surface with no consumer (ADR-0045 §1, ADR-0028
    §7); both are additive later.

    **The store has a horizon, and it is uniform** (ADR-0185 §6). It holds at most
    ``Settings.source_read_trail_max_rows`` records; when an append would exceed
    that, the **earliest-recorded** rows are deleted until it does not, atomically
    with the append. "Earliest-recorded" is the order of :meth:`record` calls and
    never :attr:`~ai_assistant.core.types.SourceReadRecord.checked_at` — that
    instant is caller-supplied, and a prune keyed on it after a backwards clock
    correction deletes the rows it just wrote. The only deletions the store performs
    are that prune and :meth:`clear`; no record is ever updated, no record is deleted
    individually, and no prune may be conditioned on a record's ``source``, ``use``,
    ``outcome``, ``grant`` or ``produced``. A uniform, content-blind, oldest-first
    horizon removes nothing anybody chose, which is why it does not tear a page out
    of the book, and it is ADR-0004 §6's own provision for size caps.

    **No bound, no schedule, no cursor and no skip decision is derived from this
    store** (ADR-0185 §8). ADR-0093 §5's clause binds it by name.

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060); see :class:`SourceReadRecorder` for what that means for a row.
    """

    async def record(self, read: SourceReadRecord) -> str:
        """Append ``read`` to the trail and return its id.

        Exactly :meth:`SourceReadRecorder.record`'s semantics — write-once, atomic
        over the duplicate check, the append and the prune, storing a detached and
        validated snapshot.

        Raises:
            ReadTrailError: If the record is not a valid one, if its id is already
                recorded, or if the store cannot be written.
        """
        ...

    async def recent(self, *, limit: int = 50) -> list[SourceReadRecord]:
        """Return the most recently recorded attempts, newest-recorded first.

        Ordered by **recording order**, reversed — never by ``checked_at``, and no
        implementation derives the order by comparing ``checked_at`` values
        (ADR-0185 §6). That is a departure from :meth:`AuditTrail.recent`, which
        orders by ``decided_at``, and it is deliberate: a decision is minted by a
        user act, a read is minted by a timer, and here a decision *does* rest on
        order — the prune — so the same premises ADR-0097 §4 reasons from reach the
        opposite conclusion.

        Bounded because every read of a Tier 1 store in this corpus is (ADR-0021 §4,
        ADR-0073 §2), and this store's row count grows with read *cadence*.

        Args:
            limit: Maximum number of records to return; must be strictly positive.

        Raises:
            ValueError: If ``limit`` is not strictly positive. Raised rather than
                clamped or passed through, for :meth:`AuditTrail.recent`'s reason —
                a store issuing ``LIMIT ?`` against SQLite turns ``limit=-1`` into
                no limit at all, so the one call offering a bounded read becomes the
                unbounded read it exists to avoid.
            ReadTrailError: If the trail cannot be read.
        """
        ...

    async def export(self) -> list[SourceReadRecord]:
        """Return every record the store holds, in recording order (ADR-0004 §6).

        The user's export right, on ``AuditTrail.export``'s shape. **It delivers the
        horizon rather than the history** (ADR-0185 §10): the store prunes, so this
        reconstructs every attempt it still holds and reads older than the
        configured cap are gone. That is the declared cost of the bound ADR-0139 §6
        required, and no lane may report it as a complete history.

        Raises:
            ReadTrailError: If the trail cannot be read.
        """
        ...

    async def clear(self) -> int:
        """Delete every record, returning the number removed.

        Wholesale erasure only, for :meth:`AuditTrail.clear`'s reason: it destroys
        the trail visibly and completely, which is what a data-rights operation
        should look like, where a selective delete would be indistinguishable from
        tampering (ADR-0004 §6, ADR-0021 §4).

        Raises:
            ReadTrailError: If the trail cannot be cleared.
        """
        ...


@runtime_checkable
class ConversationStore(Protocol):
    """The durable record of conversations (ADR-0074, ADR-0283 §6).

    A conversation is first-class, server-side state with an identity of its own,
    and this store owns that identity end to end: it **mints** the id (§1), and a
    caller never supplies one.

    A Tier 1 store by ADR-0004 §1's own words ("conversation history"), so §2's
    residency clause governs it: implementations persist **locally only**.

    **This store holds no episode.** What the assistant perceived and did in a
    conversation is the episodes on its channel in the ``MemoryStore`` —
    ``ChannelIdentity(channel_type="conversation", instance_id=<conversation_id>)`` —
    read in number order, and membership is the episode's channel (ADR-0283 §1, §4).
    Nothing here indexes them, allocates a position for them or derives their ids:
    every episode's id is ``activation:<activation_id>``, fixed at admission (ADR-0283
    §2). It keeps no observation watermark (ADR-0285 §4).

    **It holds the hub's chat space, the hosted medium** (ADR-0293 §1, ADR-0292 §3):
    each conversation's **transcript** of messages (§5), "my devices" and each
    conversation's devices (§3), the **change stream** every device catches up on
    (§5), and the chat's reader's **bookkeeping** of what it has taken in (§6). The
    transcript and the episodes are never kept in step (ADR-0293 §5:5), and
    forgetting, which is memory's act on the episodes, never reaches anything here
    (§5:6). Beside them it keeps the conversation itself.

    **What this contract does not own.** Every sequence spanning both stores —
    writing a conversational episode, finishing a user deletion, the retention
    reclaim — belongs to `orchestration`, the one layer that legitimately holds both
    handles by injection (ADR-0283 §7, §8). Whether a conversation's channel still
    holds an episode is the memory store's question, asked there; a store that
    reached into memory to answer its own precondition would break golden rule 1.

    **The mutation exclusion, which is this seam's obligation and not a
    caller's.** Per conversation, a :meth:`mark_active`, a :meth:`record_turn`, a
    :meth:`stamp_deleted`, a :meth:`drop_if_eligible`, an :meth:`append_message`, a
    :meth:`delete_message`, a :meth:`set_conversation_devices` and a :meth:`take_in`
    **never interleave**
    (ADR-0283 §6:8, less the ``record_observed`` member ADR-0285 §4 removes, and with
    ADR-0293's acts in the medium added); each observes the conversation, decides, and
    writes as one indivisible step. :meth:`set_my_devices` and :meth:`start` are
    likewise one step each against "my devices", so a conversation is started with one
    whole version of the set, never half of one. :meth:`remove_device` is one step
    against "my devices" and every conversation together, so no act on any of them
    lands between two of its removals (ADR-0296 §3:6). **The change stream is written
    inside the same step as the change it records**, so a change and its sequence
    number are one fact: no reader sees a change without its number, a number
    without its change, or a later number committed before an earlier one. An ``asyncio.Lock``
    inside one engine would not discharge this — the engine already contemplates
    "another engine over the same durable stores", so two engines hold two locks and
    serialise nothing — which is why the obligation sits here (ADR-0074 §8). Each
    implementation meets it in its own way: an in-memory store with a lock, a
    SQLite-backed one with a transaction, which is also what makes it hold across
    processes. It is also what makes :meth:`record_turn` the writer's deletion
    verification (ADR-0283 §7:2).

    **A conversation stamped deleted is absent from every read that presents
    it** — :meth:`get`, :meth:`recent`, :meth:`export`, :meth:`transcript`,
    :meth:`conversation_devices`, :meth:`untaken_messages`,
    :meth:`conversations_awaiting`, :meth:`taken_in` and :meth:`device_conversations`
    — while
    :meth:`stamped_conversation_ids` still enumerates it, so the deletion
    sweep can find the tombstone and delete every episode on its channel (ADR-0283
    §8). That distinction is what keeps a tombstone from being a readable record of
    a deleted conversation while the deletion can still be carried out.

    **That one carve-out presents nothing.** :meth:`stamped_conversation_ids`
    (ADR-0076) returns ids alone: a caller that obtains a stamped id learns which
    ids are stamped and can learn nothing else about them.

    **Every read is bounded by default and totally ordered** (ADR-0021 §4,
    ADR-0073 §2): conversations by ``last_active_at`` descending with ``id``
    ascending as the tie-break, and stamped ids by ``id`` ascending. Paging
    arguments carry ADR-0073 §2's range posture unchanged — out of range is a
    ``ValueError``, not a clamp — inherited rather than restated.

    **Every read returns a detached snapshot.** The exchanged types are frozen
    pydantic models, so this costs nothing; it is stated so an implementation that
    grows an internal mutable row cannot hand one out.

    Every method raises :class:`~ai_assistant.core.errors.ConversationStoreError`
    for a store fault, and **refuses an id the store does not know rather than
    creating one** (§1) — silently starting a conversation turns a typo or a
    stale id into "my conversation vanished". Where a method already has a
    spelling for absence (a ``None`` return — :meth:`record_turn`'s included — or
    the ``bool`` of the two lifecycle mutations) that spelling is used and nothing
    is raised; every other method raises.

    **The unknown-id refusal is the narrower
    :class:`~ai_assistant.core.errors.UnknownConversationError`** (ADR-0076 §2),
    a subclass, so the sentence above stays true as written and every existing
    ``except ConversationStoreError`` still catches it. A store *fault* raises the
    base class. The distinction exists for the sweep and nothing else: an id that
    is gone by the time a sweep reaches it is a deletion someone else completed,
    and telling that from "the store is broken" is what lets a walk carry on
    instead of aborting.

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060). Input observation (ADR-0065) binds it too: every argument this seam
    takes is immutable — a ``str``, an ``int``, a ``datetime`` or a frozen model —
    except the caller-owned sequences — :meth:`changes`' ``conversation_ids``, the ``devices`` of
    :meth:`set_my_devices` and :meth:`set_conversation_devices`, and the
    ``positions`` of :meth:`take_in` and :meth:`taken_in` — which an implementation
    reads once, before its first ``await``.

    **The chat space** (ADR-0293). What follows is the contract every implementation
    meets for it, beyond what each method states:

    * **Positions.** A conversation numbers its messages from 1 in the order it
      records them, and a position is never reused, deleted or not: a reply's
      reference and a deleted message's marker go on naming the one message
      (§5:8, §5:12).
    * **The change stream.** Every change to the chat space gets a sequence number
      from one counter across all its conversations, increasing in the order the
      changes were made and never reused (§5:10): a message added or deleted, a
      conversation started or deleted, and a set of devices changed. A change holds
      what a device needs to apply it and nothing a deletion removed: once a
      message is deleted its addition is no longer in the stream, and once a
      conversation is deleted only its deletion is.
    * **Deleting a message** removes its text and leaves its marker; the message's
      id stays recognised, so a late repeat of the send is that message and does not
      come back (§4:3, §5:12). A reply to it stays (§5:8).
    * **The claim an assistant's message was written under** (ADR-0350 §12:9, the row
      its §15 adds to ADR-0293 §5:2's table): the id of the effect record, where the
      writer passes one, is recorded with the message, names one message of the
      conversation, and stays when the message is deleted, so :meth:`effect_position`
      answers whether the message was written, deleted or not (ADR-0350 §8:11,
      §8:12). It is
      shown on no message a device reads — no transcript read, no change, no
      device's view carries it — and the export carries it with its message.
    * **Deleting a conversation** is :meth:`stamp_deleted`: its transcript, its
      devices and the reader's bookkeeping about it go in that step, the change is
      recorded, and nothing of memory is touched from here (§2:3, §5:6). Today's
      ``forget_conversation`` caller still deletes the episodes after stamping;
      that is the superseded route ADR-0293 §Decision:2 keeps in force until the
      first build separates forgetting from deleting (§11:4).
    * **"My devices"** is copied onto a conversation when it starts (§3:1); a
      conversation's devices then change only by :meth:`set_conversation_devices`
      (§3:3), and by :meth:`remove_device`, which revokes a device (ADR-0296 §3:6).
      Only a conversation's devices that may write can write a user's message in it
      (§7:2): the store, as the medium's host, refuses any other.
    * **The reader's bookkeeping is not the conversation's** (§6:7): it is in no
      transcript read and no change, and holds no text.

    **One device's view** (ADR-0296 §3, §4). Device ids stay opaque here: what a
    device is, its roles and its registration are the device session's, and nothing
    here checks a role. What this seam adds is what only the medium's host can
    answer, because only it holds each change together with the devices that stood
    when the change was recorded:

    * **A change reaches a device by membership as of that change.** A change in a
      conversation — a message added or deleted — reaches a device only if the
      device was that conversation's end for reading as the conversation's devices
      stood when the change was recorded; a change that sets a conversation's
      devices, or "my devices", reaches every device in the set before it or after
      it, whatever its access, and starting a conversation sets its devices from
      none. So a device sees the change that added it and the change that removed it
      (ADR-0296 §4:7, §4:8), and no change in that conversation from before the one
      or after the other: the snapshot it takes on joining covers what came before
      (ADR-0293 §5:13).
    * **A deletion reaches every device that read the conversation.** Deleting a
      conversation removes every earlier change of it from the stream, a device's
      removal among them, so the deletion stands in for all of them: the store keeps,
      beside the deletion's change and in nothing a read presents, every device that
      was the conversation's end for reading at any point of its recorded history,
      and the deletion reaches each of those — so a device removed and not yet caught
      up still learns it holds a conversation it must drop (ADR-0296 §4:8).
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

        **Starting is the act in the medium that creates an empty conversation**
        (ADR-0293 §2:1). In the same step the conversation is given "my devices" as
        they stand (§3:1) and a ``ConversationStartedChange`` carrying them is
        recorded. Its transcript is empty.

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
        per-conversation exclusion as a recorded turn, a stamp and a reclaim.

        Raises:
            UnknownConversationError: If ``conversation_id`` names nothing or
                names a conversation stamped deleted — refused, never created
                (§1).
            ConversationStoreError: If the store cannot be written.
        """
        ...

    async def record_turn(
        self,
        conversation_id: str,
        *,
        episode_id: str,
        occurred_at: datetime,
    ) -> Conversation | None:
        """Record that a conversational episode landed, and return the conversation.

        ADR-0283 §6:2, the writer's last step for a conversational episode (§7): the
        episode is already in the ``MemoryStore`` on the conversation's channel, and
        this tells the conversation so. **One step under the per-conversation
        exclusion**: it observes the conversation, decides, and writes, and never
        interleaves with :meth:`stamp_deleted` or :meth:`drop_if_eligible` — which
        is what makes it the writer's deletion verification (§7:2). A ``None`` here
        means the conversation was gone when the episode landed, and the writer
        deletes the episode.

        Where the conversation is **absent or stamped deleted** it writes nothing
        and returns ``None``, and raises nothing: that is the outcome a capture
        racing a deletion is owed, not a fault. Otherwise it sets ``last_turn_at``
        to ``occurred_at`` — "a turn was recorded", unconditionally and from the
        caller's reading rather than the store's clock — and leaves
        ``last_active_at`` alone. The episode id is opaque here: the store does not
        derive it, parse it or check that the episode exists.

        Args:
            conversation_id: The conversation the episode was written for.
            episode_id: The episode's id, ``activation:<activation_id>`` from
                admission (ADR-0283 §2).
            occurred_at: The episode's own ``occurred_at``, so the conversation and
                the episode carry one instant (ADR-0283 §7:1).

        Returns:
            The conversation as written, or ``None`` where it is absent or stamped.

        Raises:
            ValueError: Before any I/O, if ``episode_id`` is not a non-blank
                ``str``, or ``occurred_at`` is not a timezone-aware instant with a
                determinate offset (ADR-0023 §3).
            ConversationStoreError: If the store cannot be written.
        """
        ...

    async def stamped_conversation_ids(
        self,
        *,
        limit: int | None = None,
        after_id: str | None = None,
    ) -> list[str]:
        """Page over the ids of conversations stamped deleted but not yet dropped.

        The read ADR-0076 adds, and what makes a crashed deletion finishable: the
        tombstone is durable, but every other read excludes a stamped conversation
        by design, so a process that died between the stamp and the drop would
        otherwise leave work **no later run could rediscover** — the episodes on the
        conversation's channel never deleted, and the record outliving its grace
        indefinitely. Recovery walks this, and for each id repeats ADR-0283 §8's
        deletion steps.

        **Ids and nothing else.** Not :class:`~ai_assistant.core.types.Conversation`
        records, not the stamp instant, not counts: returning only what the work
        needs removes the exposure instead of labelling it. A record-returning read
        would be a general resurrection of everything §8's stamp exists to hide,
        bought for a caller that needs an id to pass to the deletion it already
        has.

        **The stamp instant is deliberately not returned either.** Handing back
        ``(id, deleted_at)`` so the caller could skip tombstones still inside their
        grace is wrong twice over: :meth:`drop_if_eligible` already re-checks the
        grace under the per-conversation exclusion, so a caller pre-filtering on
        ``deleted_at`` would decide eligibility on a reading taken *outside* that
        exclusion — the hazard ADR-0074 §9.4 forbids, one layer up — and the sweep
        does not want the filter anyway, because ADR-0283 §8 deletes a stamped
        conversation's episodes **whether or not** its grace has elapsed. So this
        yields every stamped conversation regardless of grace.

        **The order is ``id`` ascending and the cursor is placed lexically — not
        by looking the row up — and that is a correctness requirement.** This walk's
        rows are removed by the very sweep walking them. The ordinary sequence is
        take a batch, delete each conversation's episodes, :meth:`drop_if_eligible`,
        then ask for the next batch using the last id received — by which time that
        row may be gone. A cursor resolved by lookup would be unplaceable exactly
        when the sweep is working correctly, and ordering by ``deleted_at`` would
        compound it, since a dropped row's stamp instant is unrecoverable. So the
        ordering key must be one the **caller already carries**, and ``id`` is the
        only such value this read returns.

        **Reading removes nothing**: a row leaves when :meth:`drop_if_eligible`
        succeeds and not before, so the sweep stays idempotent by re-walking and a
        *resumed* walk is as safe as a restarted one.

        Args:
            limit: Batch size; ``None`` asks for the store's configured batch —
                **100**. It is a fixed figure and not a ``Settings`` field: unlike
                the retention horizon it expresses no user policy, so it is only
                ever a round-trip-versus-memory trade on a walk that always runs to
                exhaustion. ``0`` returns an empty batch.
            after_id: Exclusive cursor naming a **position in the id space**: the
                next batch is every stamped id ordering strictly after that string.
                An id that names no row is therefore a perfectly good cursor and is
                **not** an error — which is the whole point (see above). ``None``
                starts at the beginning.

        Returns:
            The batch, ``id`` ascending. An empty batch means the walk is done, and
            the deletion sweep **must** drain to one: finishing a batch and
            stopping leaves the tombstones after it unswept.

        Raises:
            ValueError: If ``limit`` is outside ``[0, 2**63)``. ADR-0073 §2's
                posture, inherited unchanged; ``after_id`` carries no such refusal,
                because there is nothing for the store to fail to place.
            ConversationStoreError: If the store cannot be read.
        """
        ...

    async def recent(self, *, limit: int = 50, offset: int = 0) -> list[Conversation]:
        """List conversations by last activity, most recent first (§2).

        The read that lets the hub answer "which conversation?", because a
        stateless client cannot: without it, "continue yesterday's conversation"
        would require the *client* to have kept the id, which is exactly the state
        VISION §Principle 8 forbids an interface to own. It is also the observation
        stage's candidate listing (ADR-0283 §11:2).

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

    async def stamp_deleted(self, conversation_id: str) -> bool:
        """Stamp a conversation deleted — the first step of ADR-0283 §8's deletion.

        The tombstone, and it is the conversation record itself. Stamping is
        durable, hides the conversation from every presenting read, and makes every
        later :meth:`record_turn` write nothing and answer ``None``, so a capture
        racing the deletion learns the conversation is gone. The record survives,
        enumerable by :meth:`stamped_conversation_ids`, which is what lets the sweep
        finish the deletion after a crash.

        **It is also the act in the medium that deletes the conversation** (ADR-0293
        §2:3), so in the same step it deletes the conversation's transcript, its
        devices and the reader's bookkeeping about it, removes the conversation's
        earlier changes from the change stream and records a
        ``ConversationDeletedChange``. It forgets nothing: no episode is reached
        from here (§2:3, §5:6).

        Today's ``forget_conversation`` route then deletes every episode on the
        conversation's channel, and asks
        :meth:`drop_if_eligible` to remove the record (ADR-0283 §8:1). That route
        keeps working as it does until the first build replaces it (ADR-0293
        §Decision:2), when forgetting becomes memory-only and deleting forgets
        nothing (§2:3, §2:4, §11:4); the episode deletion is that caller's step and
        never this method's. Those steps normally run to completion in the deleting
        call; the tombstone is what makes a crash survivable rather than final.

        Returns:
            ``True`` if this call stamped it; ``False`` if it was already stamped
            or the id names nothing. A ``bool`` rather than a raise on absence
            because the deletion is explicitly re-runnable — a deletion whose sweep
            is repeated after the record was dropped must be a no-op, not an error
            — and reporting "nothing to stamp" still refuses to create anything,
            which is all §1 asks of a method that does not present a conversation.

        Raises:
            ConversationStoreError: If the store cannot be written.
        """
        ...

    async def drop_if_eligible(self, conversation_id: str) -> bool:
        """Remove a conversation record, if it is still eligible (§7, §8).

        The last step of the deletion and of the retention reclaim, and it
        **re-checks eligibility while holding the per-conversation exclusion**. That
        re-check is the whole point: eligibility is a claim about state an activity
        mark changes, so deciding "idle" and then dropping the record in a separate
        step is how a reclaim destroys a conversation the user has just come back
        to.

        Eligibility, judged against the store's own clock:

        * **A stamped conversation** is eligible once a bounded **grace period**
          has elapsed since the stamp. The grace widens the sweep's reach; it is
          not a bound and is not offered as one — no elapsed time proves a
          suspended write cannot still commit. What it buys is that the tombstone
          outlives the deletion long enough for recovery's sweep to catch an
          episode whose write committed and then died.
        * **An unstamped conversation** is eligible once its ``last_active_at`` is
          past the retention horizon **and its transcript holds no message**: a
          transcript is kept until the user deletes it, so reclaim never drops a
          conversation that holds one (ADR-0293 §5:4, superseding ADR-0283 §8:2's
          condition). A deleted message's marker is not a message. Dropping such a
          conversation records a ``ConversationDeletedChange``, since its devices
          are owed the news as they are for a deletion. Eligibility reads *activity*, never
          ``last_turn_at``, so a continuation that is underway protects the
          conversation before its turn lands. Where the horizon is unset —
          retention disabled, "keep the episodes forever" — reclaim is **switched
          off** rather than guessed at: no duration means no horizon to compare
          against, and a conversation should not quietly disappear under a setting
          that asked to keep everything. Deletion is then the only thing that
          removes a conversation.

        The horizon is read at the moment reclaim runs, not stamped at creation, so
        a store moved from a 7-day horizon to a 30-day one keeps an emptied
        conversation's record until day 30 though its episodes left on day 7 — and
        moved the other way, drops it sooner. That is the behaviour a user changing
        the setting would predict, and what lingers is metadata rather than content.

        **The caller owns the other half of the precondition** (ADR-0283 §6:7, §8).
        Whether the conversation's channel is empty is a ``MemoryStore`` fact this
        store cannot see and may not ask about (golden rule 1): the deletion has
        deleted every episode on it, and the reclaim calls this only where the
        channel holds none.

        **What the re-check does and does not promise.** It defeats a reclaim whose
        eligibility was evaluated while the activity mark was still *within* the
        horizon. It does **not** keep a conversation alive for an arbitrarily long
        turn: once the mark itself has aged past the horizon the conversation is
        eligible again, and ADR-0074 §7's ratified mid-turn outcome applies — the
        record is dropped, the :meth:`record_turn` behind it answers ``None``, and
        the user gets an answer that was not recorded. The two clauses describe
        different instants and neither weakens the other.

        **Everything this store keeps under the conversation goes with the record**,
        in the same step — its transcript's markers, its devices and the reader's
        bookkeeping — and its changes but the record of its deletion, so none is
        left for a conversation minted later to inherit.

        Returns:
            ``True`` if the record was removed; ``False`` if
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

        The conversations, as the frozen type, which the caller serialises with
        ``model_dump(mode="json")`` — ADR-0007 §3's rule applied to a second store,
        so the store does not invent a bespoke format. Conversations stamped
        deleted are **excluded**: they are deleted as far as every read is
        concerned.

        It carries **every transcript's standing messages** (ADR-0293 §5:3,
        ADR-0292 §3:11), each an ``ExportedMessage`` with the effect record an
        assistant's message was claimed under (ADR-0350 §12:9, ADR-0004 §6), and
        **no episode** (ADR-0283 §4:3): a conversation's
        episodes are ``MemoryStore`` records and that store's export already carries
        them. **No liveness filtering** either: this store has no way to ask
        whether a conversation's channel still holds an episode, and no business
        asking.

        Ordered as :meth:`recent` is: ``last_active_at`` descending with ``id``
        ascending; the messages grouped by conversation in that order, each
        conversation's by ascending position. The conversations and the messages
        are read in one consistent reading.

        Raises:
            ConversationStoreError: If the store cannot be read, or a stored row
                is corrupt.
        """
        ...

    # --- the chat space: the transcript (ADR-0293 §4, §5) ------------------------

    async def append_message(self, conversation_id: str, message: NewMessage) -> MessageReceipt:
        """Write one message into a conversation's transcript, and answer for it.

        **The one write into a transcript**, for both authors: a user's message
        arriving from a device (ADR-0293 §4) and the assistant's through the chat's
        writer (§6). Under the per-conversation exclusion, in one step, it:

        1. answers ``REPEATED`` with the earlier message's position where the
           conversation already holds a user's message from the same device with
           the same message id, deleted or not, and writes nothing (§4:2, §4:3) —
           checked first, so a repeat is that message even where the device has
           since stopped being an end;
        2. answers ``REPEATED`` with the earlier message's position where an
           assistant's message carries an ``effect_id`` and the conversation already
           holds a message written under that effect record, deleted or not, and
           writes nothing (ADR-0350 §12:9): one claim is one message, so a write
           repeated under it is that message, as a device's repeat is;
        3. answers ``NOT_AN_END`` and writes nothing where a user's message comes
           from a device that is not one of the conversation's ends for writing
           (§7:2);
        4. answers ``NO_SUCH_REPLY`` and writes nothing where ``replies_to`` names a
           position the conversation never held (§4:5). A position whose message
           was deleted is one it held: a reply to it is recorded, naming it;
        5. otherwise records the message at the next position, stamped with the
           store's clock, with its ``effect_id`` where it carries one, records a
           ``MessageAddedChange``, and answers ``RECORDED`` with the position, which
           is *received* (§4:4). The change carries the message as a device reads
           it, with no effect id.

        **The message's id is unique per conversation and device here.** ADR-0293
        §4:1 has a device choose an id unique per device; a repeat is a send of the
        same message to the same conversation, so the store keys it there and
        leaves a device that reuses an id elsewhere its two messages.

        The size bound, the author's shape and an option's bound are refused when
        ``message`` is constructed (``NewMessage``); nothing here re-derives them.

        Args:
            conversation_id: The conversation written into.
            message: The message. A frozen model, observed once.

        Returns:
            The receipt: the outcome, and the position where the message is
            recorded.

        Raises:
            UnknownConversationError: If the id names nothing or names a
                conversation stamped deleted — refused, never created (ADR-0293
                §2:2: a conversation is never created as a side effect of a
                message).
            ConversationStoreError: If the store cannot be written.
        """
        ...

    async def delete_message(self, conversation_id: str, position: int) -> bool:
        """Delete one message, leaving its marker (ADR-0293 §5:8, §5:12).

        The act in the medium the user takes on a message of either author. Under
        the per-conversation exclusion, in one step: the message's text and every
        other property but its id are removed — its id being, for a user's message,
        its device and message id, and for an assistant's, the effect record it was
        claimed under (ADR-0350 §12:9) — its marker stands at its position,
        its ``MessageAddedChange`` leaves the change stream, and a
        ``MessageDeletedChange`` is recorded. A reply to it is left as it stands
        (§5:8). Nothing else is reached: deleting does not forget (ADR-0292 §3:10).

        Args:
            conversation_id: The conversation holding the message.
            position: The message's position, an ``int`` of at least 1.

        Returns:
            ``True`` where this call deleted the message; ``False`` where the
            conversation never held that position or the message was already
            deleted — deleting is safe to repeat.

        Raises:
            ValueError: Before any I/O, if ``position`` is not an ``int`` in
                ``[1, 2**63)``.
            UnknownConversationError: If the id names nothing or names a
                conversation stamped deleted.
            ConversationStoreError: If the store cannot be written.
        """
        ...

    async def effect_position(self, conversation_id: str, effect_id: str, /) -> int | None:
        """Answer whether a conversation holds the message claimed under ``effect_id``.

        ADR-0350 §12:9's read, which the Task Scheduler's sensor asks after a restart
        to confirm whether a message whose effect record has an unknown outcome, or
        none written, was sent (ADR-0350 §8:11): for the hub chat a message is sent
        once its transcript records it (ADR-0292 §7:4, ADR-0350 §8:12). It answers
        from the transcript itself, so the answer is what the medium recorded, never a
        guess.

        A read, so it takes no exclusion.

        Args:
            conversation_id: The conversation the message was claimed into.
            effect_id: The id of the effect record it was claimed under, as
                :meth:`append_message` recorded it with the message.

        Returns:
            The position of the message written under ``effect_id``, **deleted or
            not** — a message the user deleted was still sent, and its position is
            never reused (ADR-0293 §5:12) — or ``None`` where the conversation holds
            no message written under it.

        Raises:
            ValueError: Before any I/O, if ``effect_id`` is not a non-blank ``str``.
            UnknownConversationError: If the id names nothing or names a
                conversation stamped deleted. The place is gone, which is not an
                answer that the message was not sent: a caller confirming delivery
                leaves the record as it was (ADR-0350 §8:11). ``None`` is already this
                read's answer that the conversation holds no such message, so absence
                of the conversation is raised rather than spelled the same way.
            ConversationStoreError: If the store cannot be read, or a stored row
                is corrupt.
        """
        ...

    async def transcript(
        self, conversation_id: str, *, before: int | None = None, limit: int = 50
    ) -> TranscriptPage | None:
        """Read part of a conversation's transcript: recent messages, or older ones.

        ``before=None`` is the **snapshot** a device far behind, or new, takes of a
        conversation's recent messages; ``before=<position>`` loads the ones before
        it as the user scrolls back (ADR-0293 §5:13). The page is the last ``limit``
        entries with a position below ``before``, ascending, a deleted message as
        its marker; its ``as_of`` is the change stream's latest sequence number in
        the same reading, so a device follows the stream from there.

        A read, so it takes no exclusion. ``limit`` defaults to 50, the snapshot
        size ADR-0293 leaves open (What stays open), and carries ADR-0073 §2's range
        posture.

        Returns:
            The page, or ``None`` where the conversation is absent or stamped
            deleted.

        Raises:
            ValueError: Before any I/O, if ``before`` is not ``None`` or an ``int``
                in ``[1, 2**63)``, or ``limit`` is outside ``[0, 2**63)``.
            ConversationStoreError: If the store cannot be read, or a stored row
                is corrupt.
        """
        ...

    async def changes(
        self,
        *,
        after: int,
        conversation_ids: Sequence[str] | None = None,
        limit: int = 100,
    ) -> ChatChanges:
        """Read every change after a cursor (ADR-0293 §5:10, §5:11).

        A device keeps one cursor for the chat space and catches up with one
        request for every change after it. The changes are in sequence order, and
        a page holds at most ``limit`` of them; ``next_after`` is where to ask from
        next (``ChatChanges``).

        ``conversation_ids`` restricts the page to those conversations' changes —
        the conversations a device is an end of, decided by its caller — together
        with the changes to "my devices", which belong to no conversation. ``None``
        reads every change. A restricted read still moves ``next_after`` across the
        changes it passed over, so a device whose conversations are quiet keeps up.

        A read, so it takes no exclusion; it answers from one consistent reading.

        Args:
            after: The cursor: the last sequence number the reader applied, ``0``
                for none.
            conversation_ids: At most 1000 conversation ids, or ``None``. A bare
                ``str`` is refused rather than read as its characters.
            limit: Page size, at most ``2**63 - 1``; ``0`` returns no change and
                leaves ``next_after`` at ``after``.

        Returns:
            The changes, and the cursor to ask from next.

        Raises:
            ValueError: Before any I/O, if ``after`` or ``limit`` is outside
                ``[0, 2**63)``, or ``conversation_ids`` is a ``str``, holds more
                than 1000 ids or holds an element that is not a ``str``.
            ConversationStoreError: If the store cannot be read, or a stored row
                is corrupt.
        """
        ...

    # --- the chat space: devices (ADR-0293 §3) ------------------------------------

    async def my_devices(self) -> tuple[ChatDevice, ...]:
        """Return "my devices", the chat space's own set, ``device_id`` ascending (§3:1).

        Raises:
            ConversationStoreError: If the store cannot be read, or a stored row
                is corrupt.
        """
        ...

    async def set_my_devices(self, devices: Sequence[ChatDevice]) -> bool:
        """Replace "my devices" with ``devices`` (ADR-0293 §3:1, §3:2).

        An act in the medium, and the user's statement that each device's screen
        is private. A new conversation starts with the set as it stands; a
        conversation already started keeps its own devices (§3:3). Where the set
        changes, a ``DevicesChangedChange`` with no conversation is recorded in the
        same step.

        Returns:
            ``True`` where the set changed; ``False`` where ``devices`` is the set
            already held, and nothing was recorded.

        Raises:
            ValueError: Before any I/O, if ``devices`` is a ``str``, holds
                something that is not a ``ChatDevice``, names a device twice or
                holds more than ``CHAT_DEVICES_MAX``.
            ConversationStoreError: If the store cannot be written.
        """
        ...

    async def conversation_devices(self, conversation_id: str) -> tuple[ChatDevice, ...] | None:
        """Return a conversation's devices, ``device_id`` ascending (ADR-0293 §3:3).

        Returns:
            The set, or ``None`` where the conversation is absent or stamped
            deleted.

        Raises:
            ConversationStoreError: If the store cannot be read, or a stored row
                is corrupt.
        """
        ...

    async def set_conversation_devices(
        self, conversation_id: str, devices: Sequence[ChatDevice]
    ) -> bool:
        """Replace a conversation's devices with ``devices`` (ADR-0293 §3:3).

        An act in the medium, under the per-conversation exclusion. Where the set
        changes, a ``DevicesChangedChange`` naming the conversation is recorded in
        the same step. "My devices" is not touched.

        Returns:
            ``True`` where the set changed; ``False`` where it was already
            ``devices``, and nothing was recorded.

        Raises:
            ValueError: Before any I/O, as :meth:`set_my_devices`.
            UnknownConversationError: If the id names nothing or names a
                conversation stamped deleted.
            ConversationStoreError: If the store cannot be written.
        """
        ...

    # --- the chat space: the reader's bookkeeping (ADR-0293 §6) ------------------

    async def take_in(
        self, conversation_id: str, *, positions: Sequence[int], activation_id: str
    ) -> tuple[int, ...]:
        """Record that ``activation_id`` took in the user's messages at ``positions``.

        The reader's bookkeeping (ADR-0293 §6:6), marked when the activation is
        admitted (§6:8). Under the per-conversation exclusion, in one step, it marks
        each named position that holds a standing user's message not already
        marked; a position already marked keeps the activation that took it in
        first, so an interrupted activation's messages are not taken in again
        (§6:9). A position holding an assistant's message, a deleted message's
        marker, or nothing, is passed over: the assistant's own messages are never
        input (§6:1), and a message deleted before its activation was admitted is
        one the reader will not bring in again either way. No text is held.

        Args:
            conversation_id: The conversation the messages are in.
            positions: At most 1000 positions, each an ``int`` in ``[1, 2**63)``;
                duplicates are permitted.
            activation_id: The activation that took them in.

        Returns:
            The positions this call marked, ascending.

        Raises:
            ValueError: Before any I/O, if ``positions`` is a ``str``, holds more
                than 1000 positions or one outside ``[1, 2**63)`` or not an
                ``int``, or ``activation_id`` is not a non-blank ``str``.
            UnknownConversationError: If the id names nothing or names a
                conversation stamped deleted.
            ConversationStoreError: If the store cannot be written.
        """
        ...

    async def untaken_messages(
        self, conversation_id: str, *, limit: int = 100
    ) -> tuple[TranscriptMessage, ...]:
        """Return the user's messages not yet taken in, ascending (ADR-0293 §6:3, §6:9).

        What the reader brings in as one input when the conversation's running
        activation ends (§6:3), and after a restart (§6:9): every user's message
        that stands and that no activation has taken in, the first ``limit`` of
        them. A deleted message is not among them.

        Returns:
            The messages, or ``()`` where the conversation is absent or stamped
            deleted.

        Raises:
            ValueError: Before any I/O, if ``limit`` is outside ``[0, 2**63)``.
            ConversationStoreError: If the store cannot be read, or a stored row
                is corrupt.
        """
        ...

    async def conversations_awaiting(
        self, *, limit: int = 100, after_id: str | None = None
    ) -> list[str]:
        """Page over the conversations holding a user's message not yet taken in.

        How the reader finds, after a restart, the messages never taken in (ADR-0293
        §6:9). Ids alone, ``id`` ascending, of conversations not stamped deleted that
        hold at least one standing user's message no activation has taken in. The
        cursor is placed lexically, as :meth:`stamped_conversation_ids`' is, so an
        ``after_id`` naming no row is a good cursor.

        Raises:
            ValueError: If ``limit`` is outside ``[0, 2**63)``.
            ConversationStoreError: If the store cannot be read.
        """
        ...

    async def taken_in(
        self, conversation_id: str, *, positions: Sequence[int]
    ) -> Mapping[int, str]:
        """Return which activation took in each named message, where one did (§6:6).

        Keyed by position; a position no activation took in is simply missing, never
        an error and never a ``None`` value. An absent or stamped conversation answers with
        an empty mapping. A fresh mapping on every call.

        Raises:
            ValueError: Before any I/O, as :meth:`take_in`'s ``positions``.
            ConversationStoreError: If the store cannot be read, or a stored row
                is corrupt.
        """
        ...

    # --- the chat space: one device's view (ADR-0296 §3, §4) ----------------------

    async def device_changes(
        self, device_id: str, *, after: int, limit: int = 100
    ) -> DeviceChanges:
        """Read every change after a cursor that ``device_id`` may see (ADR-0296 §4:5).

        :meth:`changes` filtered to one device by the class docstring's rule: a
        message added or deleted where the device was that conversation's end for
        reading as the conversation's devices stood when the change was recorded; a
        change that sets a conversation's devices, or "my devices", where the device
        is in the set before it or after it; and a conversation's deletion where the
        device read the conversation at any point of its recorded history. So the
        change that removes the device from a conversation reaches it, or the
        conversation's deletion does where it removed that change from the stream
        (ADR-0296 §4:8), and the conversation's changes from before the change that
        adds it do not (§4:7).

        **The change that adds the device brings the conversation's snapshot**
        (ADR-0298 §7:6, §10:4): a change setting a conversation's devices — its start
        among them — that makes the device one of its ends for reading where it was
        not one before carries the conversation's entries as it stood at that change
        (§7:7): the newest :data:`~ai_assistant.core.types.CHAT_SNAPSHOT_ENTRIES` of
        the messages recorded at or before the change's sequence number, ascending, a
        message deleted since shown as its marker and nothing recorded after it. Read
        in the same reading as the page, so the device that applies the change has the
        snapshot with it. Every other change carries none.

        The page and its cursor are :meth:`changes`' own: in sequence order, at most
        ``limit`` changes, and ``next_after`` moves across every change passed over,
        seen or not, so a device whose conversations are quiet keeps up and sees the
        gaps ADR-0296 §4:6 rules it sees. A device the store has never heard of
        sees nothing and is no error: the device session, not this store, knows
        which devices exist.

        A read, so it takes no exclusion; it answers from one consistent reading.

        Args:
            device_id: The device, as the device session names it; a non-blank
                ``str``.
            after: The cursor: the last sequence number the device applied, ``0``
                for none.
            limit: Page size, at most ``2**63 - 1``; ``0`` returns no change and
                leaves ``next_after`` at ``after``.

        Returns:
            The changes the device may see, each adding change with its snapshot, and
            the cursor to ask from next.

        Raises:
            ValueError: Before any I/O, if ``device_id`` is not a non-blank ``str``,
                or ``after`` or ``limit`` is outside ``[0, 2**63)``.
            ConversationStoreError: If the store cannot be read, or a stored row
                is corrupt.
        """
        ...

    async def device_conversations(
        self, device_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[DeviceConversation]:
        """List the conversations ``device_id`` reads, with its access in each.

        The conversations where the device is one of the conversation's ends for
        reading, as their devices stand now (ADR-0293 §3:5, ADR-0296 §4:5) — what a
        device takes its snapshots of on joining (§4:7) and what a listing of its
        conversations holds. A conversation the device only writes in is not shown
        to it and is not listed; a conversation stamped deleted is not listed.

        Ordered and paged as :meth:`recent`: ``last_active_at`` descending, ``id``
        ascending, ``limit`` and ``offset`` with ADR-0073 §2's range posture. A
        device in no conversation, or one the store has never heard of, is answered
        with an empty list.

        Returns:
            The page of the device's conversations, each with its access.

        Raises:
            ValueError: Before any I/O, if ``device_id`` is not a non-blank ``str``,
                or ``limit`` or ``offset`` is outside ``[0, 2**63)``.
            ConversationStoreError: If the store cannot be read, or a stored row
                is corrupt.
        """
        ...

    async def remove_device(self, device_id: str) -> bool:
        """Remove ``device_id`` from "my devices" and from every conversation's devices.

        Revoking a device removes it as an end of every conversation (ADR-0296
        §3:6), and from "my devices", so it is an end of no new one. One step
        against "my devices" and every conversation together (the class
        docstring's exclusion): each set that names the device is set to itself
        without it, and each such removal is recorded as the ``DevicesChangedChange``
        :meth:`set_my_devices` or :meth:`set_conversation_devices` would record for
        it — "my devices" first, then the conversations by ``id`` ascending — so
        every other device sees the removal, and so would the device itself
        (:meth:`device_changes`). A conversation stamped deleted has no devices
        left to remove the device from.

        Nothing is revoked here beyond the sets: roles, registrations and open
        streams are the device session's.

        Returns:
            ``True`` where the device was removed from at least one set; ``False``
            where no set named it, and nothing was recorded — removing is safe to
            repeat.

        Raises:
            ValueError: Before any I/O, if ``device_id`` is not a non-blank ``str``.
            ConversationStoreError: If the store cannot be written.
        """
        ...


@runtime_checkable
class StoryStore(Protocol):
    """Which experiences belong to the same matter (ADR-0289 §§1-3).

    A **story** is the assistant's memory of which experiences belong together. The
    windows find what is recent, recall finds what is similar, and stories find what
    belongs. A story is identified by a ``story:`` id this store mints, carries the
    instant it was created and, once merged, the story it was merged into — and
    **nothing else**: no title, summary, state, owner or text of any kind (§2).
    What is learned about the matter is a belief about the story, kept outside it.

    **Members** are exactly one of two kinds, carried with the id and never inferred
    from it: an activation, named by its activation id, or another story (§2).

    **Two records, written together.** The **clean view** is each story's current
    members, each with the instant it was linked and the actor that linked it, in
    link order. The **change log** is append-only: each line carries a sequence
    number unique across the store, the story changed, what happened, the member
    where there is one, the story on the other side of a merge or a split, the note
    a split or a move carried where it records one (ADR-0304 §9:6), the actor, an
    optional triggering activation id and the store's clock reading. No
    line is ever rewritten or removed, and no field of either record holds free
    text. Every operation that changes a story writes both **in one transaction**:
    either both change or neither does, and a refused operation writes nothing.

    **The store reads no other store** (§1). It holds identities and checks only what
    its own records decide: that a story it is asked to write to or to name as a
    member exists and is not merged, and that no story would come to contain itself.
    Whether an activation has an episode is the engine's check, made before a create
    or a link (§4).

    **Refusals are outcomes.** Every refused write answers a
    :class:`~ai_assistant.core.types.StoryOutcome` carrying a
    :class:`~ai_assistant.core.types.StoryRefusalReason`, and writes nothing. The
    checks are made in a fixed order — no members, then the story written to
    (unknown, then merged), then each story member named (unknown, then merged), then
    the operation's own rule (self-merge, not a member, a note planning names that is
    not held, a note move's notes, loop) — and the first that fails is the one
    reported.
    :class:`~ai_assistant.core.errors.StoryStoreError` is raised only where the store
    could not read or write its file, and a malformed argument is a ``ValueError``.

    **Merged stories are followed, never written.** A write to a merged story, or one
    naming a merged story as a member, is refused with the story it was merged into.
    Reading a merged story returns its header, so a caller follows it (§3).

    **A story's notes and summary** (ADR-0300 §3, ADR-0303 §§2-4, ADR-0304 §2). Beside
    each story the store keeps its **notes** and its **summary**, with a **version log**
    recording the summary's history by identity; nothing ties the notes to the summary but that a
    tidy-up reads the one and writes the other. A note carries its text, who wrote it,
    the activation it was written during (nothing, for a note ``owner`` wrote), its
    mark, and the store's clock reading; none of it changes once written, no note is
    removed, and no rule of the store reads the activation it was written during. The
    summary is zero or more lines, each its text alone, and the summary's mark. The
    version log is append-only and holds identities, instants and enumerations only.

    **Every summary is kept** (ADR-0347 §2). A summary a later write replaces is kept,
    with the version that wrote it, its ``written_at``, its lines and its mark, exactly
    as written, beside the version log and not in it: :meth:`summary_at` reads it by its
    version. A kept summary never changes, and nothing removes one, as nothing removes a
    note or a version. Forgetting reaches no summary, current or kept (ADR-0304 §5:1, as
    ADR-0347 §3 keeps it).

    **One sequence orders the store's writes** (ADR-0347 §2:5). A version's number, a
    note's identity and a summary read's ``as_of`` are all drawn from it, and
    :meth:`position` reads where it stands, so a caller can name the versions written
    before a moment by number where a clock reading, which may run backwards, could not.

    **Pending.** A note or an activation member is pending on a story from when it
    comes to the story — written to it, linked into it, or brought by a merge, a
    split or a move — until a version of that story's summary records taking it in. A
    summary write takes in exactly the pending notes and episodes it names that were
    pending at the read it was built on, its ``as_of``: what becomes pending while a
    run is out stays pending after the run's write, and what a merge, a split or a
    move brought into a story is pending there whatever another story's version
    took in.

    **Membership writes carry notes**, each in the operation's own transaction
    (ADR-0303 §6): a merge moves every note the absorbed story holds to the story it
    is merged into; a split and a move each move exactly the notes they name that the
    story moved from holds, and no note by the activation it was written during; an
    unlink moves no note. **A split or a move whose actor is** ``planning`` **is
    refused whole** with ``note_not_held`` where a note it names is not held by the
    story moved from when it runs, checked inside its own transaction, so a note moved
    away meanwhile still refuses it (ADR-0307 §5:4); every other actor's passes such a
    note over. The store still reads no other store (ADR-0289 §1:3), and
    refuses a summary write only on what ADR-0300 §3, ADR-0302 §7 and ADR-0303 §4 state
    and on an identity naming nothing it holds: the hub's checks on a tidy-up's output
    are the hub's, and so is the summary's mark, which the store records as it is given.

    **A decision on a flag is a line in the change log** (ADR-0302 §§2-4). A flag is
    named by identity, as :class:`~ai_assistant.core.types.StoryFlagName` gives it:
    by the story whose version recorded it, that version's number and the flag as
    recorded. A tidy-up's flags are the only flags (ADR-0303 §8): understanding
    raises none, so a flag named by an activation is one the store does not hold. The
    stories a flag **concerns** are the story that raised it and then, on
    ``like_another``, the story it names, each followed through merges to the story it
    was merged into, and each counted once, at its first place. A write answering a
    flag — :meth:`leave_flag`, or ``create``,
    ``link``, ``merge``, ``split`` or ``move`` given ``answers`` — writes one
    ``decided`` line on each story the flag concerns, as they stand once its change
    is applied, after the change's own lines and in the same transaction, carrying
    the flag, the outcome its operation gives and the deciding actor, and no
    trigger. It checks the flag after every check the operation already makes:
    ``unknown_flag`` where the store's records hold no such flag, then
    ``already_decided`` where a ``decided`` line already answers it; a refused write
    writes nothing, its change included. The store reads only its own records for
    these checks — the version log and the change log — and makes them inside the
    deciding write's transaction, so two writers cannot both answer one flag.

    The decisions **recorded for** a story (ADR-0302 §3:6) are the ``decided`` lines
    on its own change log and on the change log of every story merged into it,
    directly or through a chain of merges, as its ``absorbed`` lines and theirs name
    them: a reader composes them from :meth:`log`, whose lines this contract leaves
    as they are.
    """

    async def create(
        self,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Mint a story holding ``members`` (ADR-0289 §3).

        Logs ``created``, then each member as ``added``, in the order given; a member
        named twice is added once. The store does not require two members: whether
        something connects moments is the linker's judgment.

        Given ``answers``, it groups the stories it names under the one it mints and
        records the decision ``grouped`` on the stories the flag concerns (ADR-0302
        §4:2), in its own transaction.

        Args:
            members: The story's first members, at least one.
            actor: Who is creating it.
            trigger: The activation that triggered it, where there was one.
            answers: The flag this create decides, where it decides one.

        Returns:
            The minted story's id, or a refusal: ``no_members`` for an empty list,
            ``unknown_story`` or ``merged_story`` for a story member that is not one
            the store can hold, then ``unknown_flag`` or ``already_decided``.

        Raises:
            ValueError: If an argument is malformed, including an activation member
                named by a create answering a flag (ADR-0302 §4:3).
            StoryStoreError: If the store cannot be read or written.
        """
        ...

    async def link(
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Add ``members`` to a story, each logged as ``added`` (ADR-0289 §3).

        A member already in the story is passed over, with no log line, and keeps its
        entry as it was. Given ``answers``, it records the decision ``grouped`` on the
        stories the flag concerns (ADR-0302 §4:2), in its own transaction.

        Args:
            story_id: The story to add to.
            members: The members to add, at least one.
            actor: Who is linking.
            trigger: The activation that triggered it, where there was one.
            answers: The flag this link decides, where it decides one.

        Returns:
            The story's id with the count of lines appended, or a refusal:
            ``no_members``, ``unknown_story``, ``merged_story``, or ``loop`` where a
            story member would make some story contain itself, naming the stories
            forming the loop, then ``unknown_flag`` or ``already_decided``. The store
            never merges, re-links or drops a link to resolve a loop.

        Raises:
            ValueError: If an argument is malformed, including an activation member
                named by a link answering a flag (ADR-0302 §4:3).
            StoryStoreError: If the store cannot be read or written.
        """
        ...

    async def unlink(
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
    ) -> StoryOutcome:
        """Remove ``members`` from a story, each logged as ``removed`` (ADR-0289 §3).

        A member not in the story is passed over, with no log line. A story left with
        no members stays as a story with no members. The notes resting on a removed
        activation stay on the story (ADR-0300, *What stays open*).

        Args:
            story_id: The story to remove from.
            members: The members to remove, at least one.
            actor: Who is unlinking.
            trigger: The activation that triggered it, where there was one.

        Returns:
            The story's id with the count of lines appended, or a refusal:
            ``no_members``, ``unknown_story`` or ``merged_story``.

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the store cannot be read or written.
        """
        ...

    async def merge(
        self,
        story_id: Identifier,
        into: Identifier,
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Merge story A (``story_id``) into story B (``into``) (ADR-0289 §3).

        Logs ``merged_into`` on A and ``absorbed`` on B, each naming the other. Each
        of A's members is removed from A, logged ``removed`` on A, and added to B
        where B does not already hold it, logged ``added`` on B; a member B already
        holds keeps its existing entry, link instant, actor and place. Where B was
        itself a member of A it is removed from A and nothing is added for it. A is
        then removed from every story that held it, logged ``removed`` on each, and B
        is added to each such story that does not already hold B and is not B,
        logged ``added``. A is left with no members, and records B as the story it
        was merged into. Every note A holds moves to B, in the same transaction, and
        is pending on B, as is each activation member added to B (ADR-0300 §3); no
        line is logged for each note, since every note goes (ADR-0304 §9).
        Given ``answers``, it records the decision ``merged`` on the stories the flag
        concerns as they stand after the merge, so never on A (ADR-0302 §3:4).

        Args:
            story_id: The story absorbed, A.
            into: The story it is merged into, B.
            actor: Who is merging.
            trigger: The activation that triggered it, where there was one.
            answers: The flag this merge decides, where it decides one.

        Returns:
            B's id with the count of lines appended, or a refusal: ``unknown_story``
            or ``merged_story`` for either side, ``self_merge`` where A is B, or
            ``loop`` where the result would leave some story containing itself, then
            ``unknown_flag`` or ``already_decided``.

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the store cannot be read or written.
        """
        ...

    async def split(  # noqa: PLR0913 — ADR-0302 §4:2 adds ``answers`` as a keyword to this operation
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
        notes: Sequence[StoryNoteId] = (),
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Move a non-empty subset of a story's members into a new story (ADR-0289 §3).

        Mints story C, removes ``members`` from A logged ``removed`` on A, and adds
        them to C, which logs ``created`` and each as ``added``. Both log
        ``split_off`` naming the other. The moved members keep A's link order. C is
        not made a member of A.

        In the same transaction it moves to C exactly the notes named in ``notes``
        that A holds, whoever wrote them; a note named that A does not hold is passed
        over, as a member not held is by an unlink, and no note moves by the
        activation it was written during (ADR-0303 §6). Where ``actor`` is
        ``planning``, a note named that A does not hold when the split runs refuses
        the whole split instead (ADR-0307 §5:4). Every other note stays on A.
        Each note that goes is logged ``note_moved_out`` on A and ``note_moved_in``
        on C, each line naming the note and the other story (ADR-0304 §9:6). What C
        receives is pending on C (ADR-0300 §3). Given ``answers``, it records the
        decision ``split`` on the stories the flag concerns (ADR-0302 §4:2).

        Args:
            story_id: The story split, A.
            members: The members to move, every one a current member of A.
            actor: Who is splitting.
            trigger: The activation that triggered it, where there was one.
            notes: The notes that go with the split; none by default.
            answers: The flag this split decides, where it decides one.

        Returns:
            C's id, or a refusal: ``no_members``, ``unknown_story``,
            ``merged_story``, ``not_a_member`` naming a member A does not hold, or,
            for ``planning``, ``note_not_held`` naming A, then ``unknown_flag`` or
            ``already_decided``.

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the store cannot be read or written.
        """
        ...

    async def move(  # noqa: PLR0913 — ADR-0302 §4:2 and ADR-0303 §6:2 add keywords to this operation
        self,
        story_id: Identifier,
        to: Identifier,
        members: Sequence[StoryMember] = (),
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
        notes: Sequence[StoryNoteId] = (),
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Move activation members, notes, or both, from one story to another.

        ADR-0300 §3, ADR-0303 §6, ADR-0304 §9. Each member is removed from the first
        story, logged ``removed`` there, and added to the second where the second
        does not already hold it, logged ``added`` there; one the second already
        holds keeps its entry as it was. Exactly the notes named in ``notes`` that
        the first story holds move to the second, each logged ``note_moved_out`` on
        the first and ``note_moved_in`` on the second, each line naming the note and
        the other story; and no note moves by the activation it was written during.
        A note keeps its text, its author, the activation it was written during, its
        mark and when it was written. All of it is one transaction, and what the
        second story receives is pending there. Given ``answers``, it records the
        decision ``moved`` on the stories the flag concerns (ADR-0302 §4:2).

        A **note move** names no member and one or more notes, and carries exactly
        the named notes the first story holds. Where the move names members as well,
        a named note the first story does not hold is passed over. Where ``actor`` is
        ``planning``, a named note the first story does not hold when the move runs
        refuses the whole move instead, members and notes alike (ADR-0307 §5:4).

        Args:
            story_id: The story moved from.
            to: The story moved to, another story.
            members: The activation members to move, every one a current member of
                the first story; none by default.
            actor: Who is moving.
            trigger: The activation that triggered it, where there was one.
            notes: The notes that go with the move; none by default.
            answers: The flag this move decides, where it decides one.

        Returns:
            The second story's id with the count of lines appended, or a refusal:
            ``no_members`` where it names no member and no note; ``unknown_story``
            or ``merged_story`` for either side, the first story first;
            ``not_a_member`` naming a member the first story does not hold; for
            ``planning``, ``note_not_held`` naming the first story where it does not
            hold a note named; or, for a note move, ``no_notes`` naming the first
            story where it holds none of the notes named; then ``unknown_flag`` or
            ``already_decided``.

        Raises:
            ValueError: If an argument is malformed: a story member named, or the
                two stories the same.
            StoryStoreError: If the store cannot be read or written.
        """
        ...

    async def leave_flag(
        self,
        flag: StoryFlagName,
        *,
        actor: StoryActor,
        outcome: StoryDecision = StoryDecision.LEFT,
    ) -> StoryOutcome:
        """Record a decision on a flag that changed no story.

        ADR-0302 §4:1, ADR-0303 §8. Writes one ``decided`` line with ``outcome`` on
        each story the flag concerns, in one transaction, and changes no story's
        members: ``left`` where the decider chose to leave the stories as they are,
        and ``not_applied`` where it chose a change the store refused.

        Args:
            flag: The flag decided.
            actor: Who decided.
            outcome: ``left`` by default, or ``not_applied``.

        Returns:
            The first story it wrote a line on, in the order the stories a flag
            concerns are given, with the count of its lines, or a refusal:
            ``unknown_flag`` where the store's records hold no such flag, or
            ``already_decided`` where a ``decided`` line already answers it.

        Raises:
            ValueError: If an argument is malformed, including an ``outcome`` other
                than ``left`` or ``not_applied``.
            StoryStoreError: If the store cannot be read or written.
        """
        ...

    async def header(self, story_id: Identifier) -> StoryHeader | None:
        """Read a story's header: its id, creation instant and merge target.

        Returns:
            The header, or ``None`` where the store holds no such story.

        Raises:
            ValueError: If the id is malformed.
            StoryStoreError: If the store cannot be read.
        """
        ...

    async def view(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryViewPage | None:
        """Read a page of a story's clean view, in link order.

        Args:
            story_id: The story to read.
            cursor: ``None`` for the first page, else a page's ``next_cursor``.
            limit: The most entries the page holds, in ``[1, MAX_STORY_PAGE]``.

        Returns:
            The page, carrying the story's header and current member count, or
            ``None`` where the store holds no such story.

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the store cannot be read.
        """
        ...

    async def log(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryLogPage | None:
        """Read a page of a story's change log, in sequence order.

        Args:
            story_id: The story to read.
            cursor: ``None`` for the first page, else a page's ``next_cursor``.
            limit: The most lines the page holds, in ``[1, MAX_STORY_PAGE]``.

        Returns:
            The page, or ``None`` where the store holds no such story.

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the store cannot be read.
        """
        ...

    async def stories(
        self,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryPage:
        """Read a page of every story the store holds, newest first.

        Merged stories are listed too: each is still a story, with its header.

        Args:
            cursor: ``None`` for the first page, else a page's ``next_cursor``.
            limit: The most stories the page holds, in ``[1, MAX_STORY_PAGE]``.

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the store cannot be read.
        """
        ...

    async def stories_of(self, member: StoryMember) -> tuple[StoryHeader, ...]:
        """Read the stories ``member`` belongs to directly, newest first.

        The reverse lookup: the episode detail needs it now, and the forgetting
        milestone and the readers of beliefs about a story will later (§3). A story
        that only contains a story containing ``member`` is not among them.

        Raises:
            ValueError: If the member is malformed.
            StoryStoreError: If the store cannot be read.
        """
        ...

    # --- the notes and the summary (ADR-0300 §3, ADR-0304 §2) -----------------

    async def append_note(
        self,
        story_id: Identifier,
        text: str,
        *,
        author: StoryNoteAuthor,
        written_during: Identifier | None = None,
        outside: bool = False,
    ) -> StoryNoteOutcome:
        """Write a note to a story, pending there (ADR-0303 §2, §4:7).

        The note is stamped with the store's clock and an identity the store
        assigns. The tidy-up writes no note (§2:1), so nothing writes one as
        ``tidy_up``.

        Args:
            story_id: The story the note is for.
            text: The note's text, non-blank, within ``STORY_NOTE_MAX_CHARS``.
            author: ``planning`` or ``owner``.
            written_during: The activation the note was written during; ``None``
                exactly for ``owner``.
            outside: The note's mark, as the hub's record of what that activation
                read gives it (§3:1); never for ``owner``.

        Returns:
            The note as written, or a refusal: ``unknown_story``, or
            ``merged_story`` naming where the story went.

        Raises:
            ValueError: If an argument is malformed, including an author of
                ``tidy_up``, or an activation or a mark the author does not admit.
            StoryStoreError: If the store cannot be read or written.
        """
        ...

    async def write_summary(
        self,
        story_id: Identifier,
        draft: StorySummaryDraft,
        *,
        as_of: int,
    ) -> StorySummaryOutcome:
        """Write a new summary and its version, and no note (ADR-0303 §4).

        One transaction: the new summary, its lines and its mark, becomes the
        current one, and the one it replaces is kept, readable by its version through
        :meth:`summary_at` (ADR-0347 §2); and the version is appended, recording what
        it took in, the other stories' summary versions its run read, its flags and its
        mark. It takes in exactly the notes and episodes the draft names that were
        pending on the story at ``as_of``; a name the story holds that was not is not
        recorded as taken in, and stays pending where it is pending. A draft taking in
        what the story does not hold when the write runs is refused (ADR-0302 §7). A
        summary version the draft names as read is checked only as an identity the store
        holds, never as a member (§4:2). A refused write writes nothing.

        Args:
            story_id: The story whose summary is written.
            draft: The summary and what is written beside it.
            as_of: The ``as_of`` of the :meth:`current_summary` read the summary was
                built on.

        Returns:
            The version appended, or a refusal, checked in this order:
            ``unknown_story``; ``merged_story``; ``summary_moved_on`` where a version
            has been written since ``as_of``, so the version the summary was built on
            is no longer the current one; ``unknown_story`` for a flag naming a
            story the store does not hold, then for a summary version read naming one;
            ``not_held`` for the first, in this order, of an episode named as taken
            in that is not one of its activation members and a note named as taken
            in that it does not hold, naming that activation or note; and
            ``over_cap`` where the lines together exceed ``STORY_SUMMARY_CAP_CHARS``,
            every line counted. No write answers ``unknown_note``.

        Raises:
            ValueError: If an argument is malformed, including an ``as_of`` the
                store has not reached, a flag naming the story written, or a summary
                version read naming the story written or a version that story's log
                does not hold.
            StoryStoreError: If the store cannot be read or written.
        """
        ...

    async def current_summary(self, story_id: Identifier) -> StorySummaryState | None:
        """Read a story's summary with the notes and episodes pending on it.

        One consistent read, carrying the ``as_of`` a summary built on it is written
        with. A merged story reads as it was left: its notes went to the story it
        was merged into, so nothing is pending on it.

        Returns:
            The state, or ``None`` where the store holds no such story.

        Raises:
            ValueError: If the id is malformed.
            StoryStoreError: If the store cannot be read.
        """
        ...

    async def notes(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryNoteList | None:
        """Read a page of the notes a story holds, in the order they were written.

        Args:
            story_id: The story to read.
            cursor: ``None`` for the first page, else a page's ``next_cursor``.
            limit: The most notes the page holds, in ``[1, MAX_STORY_PAGE]``.

        Returns:
            The page, or ``None`` where the store holds no such story.

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the store cannot be read.
        """
        ...

    async def summary_versions(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StorySummaryVersionList | None:
        """Read a page of a story's version log, oldest first.

        Args:
            story_id: The story to read.
            cursor: ``None`` for the first page, else a page's ``next_cursor``.
            limit: The most versions the page holds, in ``[1, MAX_STORY_PAGE]``.

        Returns:
            The page, or ``None`` where the store holds no such story.

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the store cannot be read.
        """
        ...

    async def summary_at(self, story_id: Identifier, version: int) -> StorySummary | None:
        """Read the summary a version of a story wrote, as it was written (ADR-0347 §2:4).

        The current summary and every summary a later write replaced alike, each with
        the version that wrote it, its ``written_at``, its lines and its mark. A merged
        story's summaries are read by its own id, as it was left. The read names one
        version: which version a caller wants, such as the latest at or below a
        :meth:`position` it recorded, is the caller's to work out from
        :meth:`summary_versions`.

        Args:
            story_id: The story whose summary is read.
            version: The version that wrote it.

        Returns:
            The summary, or ``None`` where the store holds no text for that version —
            a version written before the store kept every summary, which an upgrade
            gives no text (ADR-0347 §5:1) — or the version is not that story's, the
            store holding no such story or no such version included.

        Raises:
            ValueError: If the id is malformed or ``version`` is not an exact ``int``
                in ``[1, 2**63)``.
            StoryStoreError: If the store cannot be read.
        """
        ...

    async def position(self) -> int:
        """Read where the store's one sequence stands (ADR-0347 §2:5).

        The sequence a version's number and a summary read's ``as_of`` lie on: every
        version written before the call has a number at or below the value returned,
        and every version written after it a number above it. It is what
        :meth:`current_summary` reports as ``as_of`` at the same moment, read without
        naming a story.

        Returns:
            The position, an ``int`` in ``[0, 2**63)``; ``0`` for a store that has
            written nothing on the sequence.

        Raises:
            StoryStoreError: If the store cannot be read.
        """
        ...


@runtime_checkable
class NotificationPolicy(Protocol):
    """Rules on one notification candidate — mechanically (ADR-0130 §4, §5).

    **The disposition is mechanical, and no model makes it.** §11 is normative:
    no implementation may consult a ``ModelProvider``, and no lane may add a
    model-judged disposition without superseding §4. An interruption a model
    chose cannot be explained to the user who received it, cannot be tested
    deterministically, and cannot run when no provider is reachable — which is
    exactly when a resident process is still noticing.

    **Determinism is an obligation of this contract, not a property of the
    signature** (§9). For the same candidate, the same standing preferences, the
    same durable record and the same instant, an implementation returns the same
    disposition. Every input the ruling depends on is an argument or a
    construction-time property of the implementation; the ruling is a function of
    those and of nothing else. The method is ``async`` mirroring
    :meth:`MemoryPolicy.decide`, and an implementation that awaits anything
    outside its arguments has already broken the clause above.

    **A producer's confidence, its summary and its choice of class are evidence
    on the proposal** (§4). An implementation may read them; no clause of §5 is
    satisfied by a producer asserting that it should be. And **no numeric
    priority or urgency score is part of this contract** (§11): weighed by a
    producer a score is self-granted authority, weighed by the policy it is a
    threshold nobody can calibrate on the first day.

    **The one construction-time input is the timezone.** Quiet windows are read in
    the zone of the person the ruling is for, and in ``Settings.timezone`` where
    theirs is empty (ADR-0130 §6, as ADR-0338 §3:6 supersedes §6:4). It is a property
    of the implementation rather than an argument, because a caller free to vary it
    per call could move the user's night: a ruling in another zone is handed another
    instance.

    **A DST-ambiguous local instant resolves at ``fold=0``**, on ADR-0093 §7b's
    rule for the same hazard. A local time the spring transition skips entirely
    resolves to **the instant the clock next passes it**, which is the transition:
    §5 asks for "the earliest instant at which every condition that failed could
    next hold", and its tolerance of a late *run* is about a tick that slipped
    rather than a licence to compute a due instant that is wrong.

    Cancelling this method is governed by this module's cancellation clause
    (ADR-0060). Input observation (ADR-0065) binds it and is vacuous in practice:
    every argument is immutable — a frozen model, a ``bool``, an ``int`` or a
    tz-aware ``datetime``.
    """

    async def rule(  # noqa: PLR0913 — §4's determinism needs every input the ruling reads to be an argument; bundling them would mint a type §9 does not name
        self,
        candidate: NotificationCandidate,
        *,
        notification_id: Identifier,
        preferences: NotificationPreferences,
        now: UtcInstant,
        duplicate: bool,
        at_cap: bool,
        budget_spent: int,
        budget_frees_at: UtcInstant | None,
    ) -> NotificationDisposition:
        """Rule on one candidate against the standing state as it then is (§5).

        **Four conditions are evaluated first, in the order
        :data:`~ai_assistant.core.types.DROP_CONDITIONS` states them, and each
        yields ``DROP`` naming itself as the reason**: the candidate declares an
        expiry not later than ``now``; the reach level for its class is ``off``;
        it duplicates a record still **speaking for its key** (ADR-0215 §2, which
        replaces §5's third condition); the store is at its cap. A candidate
        that passes all four is ruled ``INTERRUPT`` when **every** condition of
        :data:`~ai_assistant.core.types.INTERRUPT_CONDITIONS` holds, and ``HOLD``
        otherwise — naming the first unsatisfied one, which for a candidate
        declaring no expiry at all is the expiry condition.

        **``HOLD`` is the outcome whenever no clause selects another**, and it is
        not silence: a held record is readable through §7's enumeration, and what
        ``HOLD`` withholds is the *interruption*, which is the scarce thing.

        **Sensitivity is not a condition here.** A ``DataTier.SECRET`` candidate
        is refused by
        :class:`~ai_assistant.core.types.NotificationCandidate`'s own validator
        and reaches no ruling (§2).

        **The returned ``HOLD`` carries the whole set of conditions that failed,
        not the first alone** (§5). The reason names the first for rendering; the
        set is what §6 reads when a standing setting is written, and a rule that
        read the reason instead would miss a record whose *second* failure is the
        one the setting change removes. ``reconsider_at`` is set to the earliest
        instant at which every failing condition could next hold, and is left
        unset where any of them is not one time alone resolves — the reach level
        and an absent expiry are each such a condition, as are the two that look
        time-resolvable and are not: a budget of zero, and a set of quiet windows
        covering every minute of the day. A due instant those cannot reach
        promises a re-ruling that can only re-hold, on every tick, for the life of
        the record.

        Args:
            candidate: The proposal to rule on.
            notification_id: The id of the record this ruling would produce or
                update. Always stamped onto the returned disposition; a store
                that ruled ``DROP`` on an *offer* clears it before returning,
                because §8 writes no durable record for one.
            preferences: The standing settings in force, which an empty store
                supplies as
                :class:`~ai_assistant.core.types.NotificationPreferences`'
                shipped defaults (§6).
            now: The ruling instant, tz-aware. Every comparison in §5 is made
                against this one value rather than against a clock this
                implementation reads, which is half of what makes the ruling
                reproducible.
            duplicate: Whether a record that still **speaks for** this
                candidate's key at ``now`` already exists (§8 as ADR-0215 §2
                replaces it) — actionable, or dismissed and inside the expiry its
                own candidate declared. **Not** the actionable population, and
                not derivable from ``at_cap``'s: tying the two is what #1372
                measured. A reconsideration passes ``False``: it is not an offer
                and never matches itself (§5).
            at_cap: Whether the store holds its cap of **actionable** records
                (§7). A reconsideration passes ``False``: the record already
                occupies its slot, so the cap is not a condition of re-ruling it.
            budget_spent: How many ``INTERRUPT`` dispositions the store has
                recorded inside ``preferences.budget_window`` ending at ``now``.
                A unit is spent when a disposition is **recorded**, never when
                contact is attempted and never when it succeeds (§5).
            budget_frees_at: When that window next falls below the budget, or
                ``None`` where time alone will not free a unit — which a budget
                of zero is. Read only to stamp ``reconsider_at``.

        Returns:
            The ruling, naming the condition that decided it.
        """
        ...


@runtime_checkable
class NotificationWriter(Protocol):
    """The one seam a producer holds, and the whole of what it may do (§1, §3).

    **A producer holds no channel, no delivery seam and no client connection**
    (§1). Its only outcome is the disposition this seam returns, and it may take
    no other action on the strength of having produced a candidate. It may not
    select its own disposition, exempt itself from §5, or write to the store
    other than through here.

    This is ADR-0093 §1's posture applied to the other end of the system: the
    producer notices; it does not decide, and it does not deliver. In practice
    the first producers will be scheduler jobs of ADR-0083 §7's shape, driven
    from the composition root — but this contract names none of them, because
    what makes proactive contact safe is that producing is not delivering, not
    that some list of producers was blessed.

    **Any component may hold this seam**, subject to the import boundaries
    ``lint-imports`` enforces and to its own contract. ADR-0130 §1 widens no
    existing prohibition and leaves ADR-0093 §1's rule that a ``Reader`` "takes
    no store handle, no writer, no policy and no engine" unchanged — so a
    ``Reader`` may **not** hold this seam.

    **One call, because conflict detection is not a separate stage** — ADR-0028
    §3's ruling for the memory write path, and the same holds here (§3).

    Every method raises
    :class:`~ai_assistant.core.errors.NotificationStoreError` for a store fault.

    Cancelling this method is governed by this module's cancellation clause
    (ADR-0060), and how it observes its argument by the input-observation clause
    (ADR-0065) — vacuous here, the argument being a frozen model.
    """

    async def offer(self, candidate: NotificationCandidate) -> NotificationDisposition:
        """Offer one candidate, and report what was ruled about it (§3).

        Reads the standing preferences and the durable record, asks the injected
        :class:`NotificationPolicy` to rule, records the ruling where §8 requires
        a record, and returns the disposition.

        **The duplicate lookup of §8, the cap check of §7, the budget read of §6,
        the ruling of §5 and the writing of any record are one atomic act in the
        store** (§3). Two offers made concurrently may not both proceed on the
        strength of the same last remaining unit of budget, the same last free
        slot under the cap, or the same absence of a record **speaking for** one
        key (ADR-0215 §2, which binds §3's clause to the suppressing set where it
        named the actionable one). Without that, all three of those guarantees are
        advisory — a
        ``HOLD`` racing another ``HOLD`` breaks duplicate suppression and the cap
        exactly as a raced ``INTERRUPT`` breaks the budget.

        **A ``DROP`` writes no durable record; a ``HOLD`` and an ``INTERRUPT``
        do** (§8), and the returned disposition names the record where there is
        one.

        **Offering the same thing again is expected and is safe** (§8). A
        producer that re-notices the same fact on every tick is behaving as
        designed: no producer may require a durable cursor in order to be
        correct, and the candidate key is what makes that so.

        Args:
            candidate: What the producer noticed, and what it says the user might
                be told. Its ``candidate_key`` is what §8 deduplicates on.

        Returns:
            The ruling, naming the condition that decided it and the record it
            produced where §8 required one.

        Raises:
            NotificationStoreError: If the store cannot be read or written.
        """
        ...


@runtime_checkable
class NotificationOutbox(Protocol):
    """Custody of a ruled interruption, from the producer to the wire (ADR-0131 §3).

    **A separate Protocol from :class:`NotificationWriter`, and the boundary is
    the propose/dispose line itself** (ADR-0131 §3b). The writer decides *whether*
    the user is interrupted; this carries an interruption that has already been
    ruled. Folding the enqueue into the writer would put the transport's custody
    question inside the call whose whole subject is the policy question, and would
    make ADR-0130's ratified single-call seam mean something new. Two Protocols
    keep "producing is not delivering" (ADR-0130 §1) true in the type system
    rather than only in prose, and the composition root is where they meet.

    **What it holds is a durable, bounded, leased queue for the owner** (§3). An
    entry is placed in the hub's data directory before it is offered to any
    device and survives a restart; it is offered to **one** device at a time — the
    first to ask — and retired when that device acknowledges it. Delivery is
    **at-least-once**: a device that receives a notification, shows it and dies
    before acknowledging will be shown it again, which is the right side to fail
    on for a notification and is stated rather than discovered.

    **It is not on :class:`AssistantEngine` and nothing it carries crosses the
    wire** (§3b). Adding it bumps no protocol version of its own; ADR-0124 §9's
    bump this seam incurs is for ``next_notification`` alone.

    **The outbox holds notifications and nothing else** (§3). It is not a memory,
    not an episode and not a trace; no lane may route it through
    :class:`MemoryStore` or :class:`TraceStore`, and nothing in it is a record any
    retrieval path reads.

    **Every transition of the outbox is linearizable with respect to every
    other** (§3): each observes the state some serial order of them would
    produce, none may act on an observation another has since invalidated, and a
    transition reading two parts of the outbox and acting on both does so in one
    step. The obligation is on **every** transition, named or not — an enqueue's
    key decision, bound check, eviction and insertion; a selection with its mint
    and lease; an acknowledgement's match and retirement; a lease expiry; an
    eviction's classification and drop. ADR-0131 §3 records four separate
    findings of one defect behind that rule: a predicate stated over outbox state
    binds nothing unless the read and the act that depends on it are one step. No
    atomicity is required *across* to the hub's connection registry, whose
    relation to this is an ordering rather than a shared state.

    Cancelling this method is governed by this module's cancellation clause
    (ADR-0060), and how it observes its argument by the input-observation clause
    (ADR-0065) — vacuous here, the argument being a frozen model.
    """

    async def offer(self, candidate: NotificationCandidate) -> NotificationEnqueue:
        """Hand one ruled interruption to the seam, and learn whether it took it.

        **The enqueue is a single durable commit, and the seam takes custody at
        that commit and not before** (§3). A caller that has not seen this return
        has not handed the notification over, which is what leaves a producer able
        to do something about a failure — ADR-0094 §10a's custody clause, mirrored
        for material travelling outward.

        **The entry is keyed by the candidate's own ``candidate_key``** (ADR-0130
        §8), and this call takes no key from its caller. There is one key per
        candidate and every path computes the same one, ADR-0131 §3b's startup
        reconciliation included — which is what makes running it twice, or against
        entries that already exist, a no-op. Keys of removed entries are not
        remembered: a candidate re-offered after its entry was delivered and
        acknowledged is a **new** notification earning its own disposition, its
        own budget unit and its own entry (ADR-0130 §7).

        **Matching is on the key *and* the candidate** (§3). Matching on the key
        alone would turn a producer's bug into a silent loss — a different
        candidate offered under a held key would receive what looks like a
        successful enqueue and never be told — so an identical candidate is
        :attr:`~ai_assistant.core.types.NotificationEnqueue.ALREADY_HELD` and a
        differing one is
        :attr:`~ai_assistant.core.types.NotificationEnqueue.KEY_COLLISION`.
        Equality is ADR-0087 §2's canonical encoding: two candidates are identical
        when theirs are.

        **A departing entry matches nothing** (§3). An entry whose ADR-0130 record
        has ceased to be actionable — the seam gave it up and dismissed its
        record, or the candidate's own expiry has passed on the hub's clock —
        participates in no transition except its own removal, so an offer whose
        key equals a departing entry's makes a new entry rather than reporting the
        one on its way out.

        **Both refusals are terminal for the record, not merely for the offer**
        (§3b): a caller that receives ``TOO_LARGE`` or ``KEY_COLLISION`` dismisses
        the ADR-0130 record, which ends its actionability and frees §7's cap, and
        records the refusal in the hub's log. No refusal may leave an actionable
        record with no entry, because that is exactly the state §3b's invariant
        reads as an incomplete handoff and reconciliation would re-offer forever.
        The refusal does **not** refund the budget unit ADR-0130 §5 spent when the
        disposition was recorded, and no lane may make it do so.

        Args:
            candidate: The candidate whose disposition ADR-0130 §5 ruled
                ``INTERRUPT``. Its ``candidate_key`` is the entry's key and this
                seam supplies none.

        Returns:
            Which of §3's four outcomes the offer reached.

        Raises:
            NotificationOutboxError: If the durable store cannot commit. **No
                custody transfers**: the candidate is still the caller's, nothing
                was enqueued, and the record stays actionable for a retry or for
                the next reconciliation.
        """
        ...


@runtime_checkable
class NotificationStore(Protocol):
    """The durable home of held notifications and the user's standing settings.

    ADR-0130 §9's third contract: it holds the durable records, the standing
    preferences of §6, the cap of §7, the enumerations §7's read surface serves,
    and the records due for reconsideration under §5.

    **A Tier 1 store, and Tier 1 only.** A candidate carries free text a producer
    wrote to be shown to a person, so this store inherits every obligation the
    ``MemoryStore`` carries under ADR-0004 and ADR-0007 — the same data
    directory and file permissions, inclusion in :meth:`export`, destructible on
    request. A ``DataTier.SECRET`` candidate is **never held**:
    :class:`~ai_assistant.core.types.NotificationCandidate` refuses one at
    validation, so no conforming store can hold one however it is called, in any
    disposition and under any setting (§2).

    **Two populations, and the rules here read one each** (ADR-0215 §§1-4,
    replacing ADR-0130 §7's single one). The cap counts **actionable** records and
    no others, exactly as ratified, so dismissing frees capacity at once and an
    expired record holds none (ADR-0215 §3). §8's duplicate rule reads the
    **suppressing** set instead: a record speaks for its key while it is
    actionable, and on past a dismissal — no reconsideration ``DROP`` having
    reached it — until the expiry its candidate declared. So a fact recurring
    after its notification **expired** is a new candidate and not a duplicate, as
    before; one recurring after its notification was **dismissed** is still a
    duplicate until it perishes. Retention then runs from the instant a record
    ceased to be **actionable**, unchanged, and no record is purged while it still
    **speaks** for its key, whatever its retention — which is what makes §8's
    suppression guarantee unconditional (§7, ADR-0215 §4).

    **The two reads stay two reads.** An implementation computing one population
    and using it for both would re-introduce, in the other direction, exactly the
    coupling ADR-0215 removes: capacity is about the list a person reads and
    suppression is about repeat contact over one fact, and #1372 is the bill for
    answering them from one query.

    **The cap refuses; it never evicts** (§7, §11). At the cap a new candidate is
    ruled ``DROP`` naming the cap and no existing record is displaced. §11 makes
    that unrelaxable by an implementing lane, together with §7's rule that no
    notification and no count of notifications is injected into a turn.

    **A spent unit of budget outlives the record that spent it** (§5: "no spent
    unit is refunded except by an act that says so"). The count §5's budget clause
    reads is therefore **not** derivable from the retained records, and an
    implementation that derived it would refund a unit on three ordinary acts:
    :meth:`delete`, :meth:`clear`, and a :meth:`purge` running under a retention
    horizon shorter than the budget window. The last is a *scheduler's* act rather
    than a user's, so the bound §5 exists to make computable would widen on a
    timer. What an implementation keeps is the instant alone — no key, no summary,
    no class — so it is a rate limiter's state rather than the user's content, it
    appears in no :meth:`export`, and destroying a notification still destroys
    everything the notification said.

    **The store produces every record; a caller hands none in.** ``id``,
    ``admitted_at``, ``ruled_at`` and ``retention`` are the store's own — the
    first two from its injected clock, the last from the retention it was
    constructed with — because each decides something a caller would otherwise
    be deciding for itself, and a validator that only checks the fields agree with each
    other cannot catch it.

    **An id it mints is fresh, and a collision is a fault rather than an
    overwrite.** Because ids are this store's own, a repeat is its own defect and
    not a caller's — but the consequence of absorbing one is still a record lost
    silently, and two dispositions naming it. So an admission at an id a record
    already holds **raises**, committing nothing, where a dict would otherwise overwrite while a SQL
    backend raised on its primary key. Nothing is committed by a failed
    admission either — no record, and **no unit of budget** — so a candidate the
    record type refuses leaves the store exactly as it found it.

    **The cap and the retention are constructor parameters, validated at
    construction**, the ``_check_tuning`` arrangement ADR-0022 §4a ratified and
    for its reason: a bad value here disables a stage while the system reports
    health. It also means the retention is read **once per store**, never per
    operation, which is the other half of §7's rule that a stamped duration is
    never consulted from the setting afterwards.

    Every method raises
    :class:`~ai_assistant.core.errors.NotificationStoreError` for a store fault.
    Where a method has a spelling for absence or refusal — the ``None`` from
    :meth:`get` and :meth:`reconsider`, the ``bool`` of :meth:`dismiss` and
    :meth:`delete` — that spelling is used and nothing is raised. A malformed
    paging argument is a ``ValueError``, ADR-0073 §2's posture inherited rather
    than restated.

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060). Input observation (ADR-0065) binds it too and is vacuous in
    practice: every argument this seam takes is immutable — a ``str``, an
    ``int``, or a frozen model.
    """

    @property
    def cap(self) -> int:
        """The most **actionable** records this store holds (ADR-0130 §7).

        Exactly an integer in ``0 < value < 2**63``, fixed at construction. There
        is deliberately no spelling for "unlimited": a cap of ``0`` is at
        capacity before its first admission, and the duration axis is where the
        deliberate escape lives (``retention`` of ``None``).

        Published because a conformance suite cannot test a boundary nobody
        stated, and because a surface rendering "you are at capacity" needs the
        number rather than an inference from a refusal.
        """
        ...

    async def admit(
        self, candidate: NotificationCandidate, *, policy: NotificationPolicy
    ) -> NotificationDisposition:
        """Rule on an offered candidate and record the ruling — atomically (§3).

        **The whole act is one atomic act in this store**: the duplicate lookup
        of §8, the cap check of §7, the budget read of §6, the ruling of §5 and
        the writing of any record. Two calls made concurrently may not both
        proceed on the strength of the same last remaining unit of budget, the
        same last free slot under the cap, or the same absence of a record
        **speaking for** one key (ADR-0215 §2). The three limbs read the three
        populations they name: the budget window, the actionable set, and the
        suppressing set.

        **The duplicate lookup reads every record retained under the offered
        key** and rules ``DROP`` where any one of them speaks at the ruling
        instant (ADR-0215 §2). No implementation may narrow that to a single
        record — the most recently admitted or any other. From this decision
        onward at most one record per key speaks at any instant, a suppressing
        record making every offer of its key a ``DROP`` and a ``DROP`` writing
        nothing; but a store that ran under ADR-0130 §8 admitted a second record
        the moment the first was dismissed, and where that first declared the
        later expiry both speak until the earlier horizon passes. Such a pair
        needs no migration and no sweep — it suppresses the key until the later
        horizon and then stops, which is the rule — and no store can tell the two
        vintages apart.

        **The policy is an argument rather than a collaborator this store
        holds**, and that is what makes the atomicity above expressible: the
        ruling happens *inside* the critical section, so no window exists between
        reading the state and writing the record it was ruled against. The store
        neither chooses the policy nor rules anything itself — it supplies §5's
        four store-side facts and applies what comes back.

        **A ``DROP`` writes no durable record** (§8), and the disposition
        returned for one carries no ``notification_id``: there is no record to
        name. A ``HOLD`` and an ``INTERRUPT`` each write one, stamped with this
        store's ``admitted_at`` and its constructed retention.

        Args:
            candidate: What was noticed. Refused before this store is reached if
                its sensitivity is Tier 0 or its expiry has already passed (§2).
            policy: The ruling, asked inside this store's critical section.

        Returns:
            The disposition, naming the condition that decided it.

        Raises:
            NotificationStoreError: If the store cannot be read or written.
        """
        ...

    async def reconsider(
        self, notification_id: str, *, policy: NotificationPolicy
    ) -> NotificationDisposition | None:
        """Re-rule one held record that has fallen due, in place (§5).

        **A reconsideration is not a new offer.** It introduces no second record,
        §8's duplicate rule does not read the record being reconsidered as a
        duplicate of itself, and the cap is not consulted — the record already
        holds its slot. The policy rules it afresh against the standing state as
        it then is, and the existing record is updated in place, atomically on
        §3's clause.

        **A late reconsideration is not a fault.** ``reconsider_at`` is the
        instant *before* which a record may not be reconsidered, never a deadline
        by which it must have been, on ADR-0083 §7's rule that "a missed or late
        tick is never a correctness bug".

        **A reconsideration ruled ``INTERRUPT`` spends a unit of budget like any
        other ruling**, and ruled ``HOLD`` carries a fresh ``reconsider_at`` on
        the same rule. **It never deletes a record and never writes a second
        one**: ruled ``DROP`` — by expiry, or by a reach level lowered to ``off``
        since the hold — it records that disposition, the record ceases to be
        actionable, and §7's retention is what removes it.

        Args:
            notification_id: The record to re-rule.
            policy: The ruling, asked inside this store's critical section.

        Returns:
            The fresh disposition, or ``None`` where the id named nothing, or
            named a record that is not actionable or has not fallen due. The
            ``None`` is a spelling for "there was nothing to do", not a fault:
            a job driving this over a page of due records races other writers by
            construction.

        Raises:
            NotificationStoreError: If the store cannot be read or written.
        """
        ...

    async def due(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> list[HeldNotification]:
        """The actionable records whose ``reconsider_at`` has arrived (§5).

        The read half of the reconsideration operation: a caller enumerates here
        and re-rules each through :meth:`reconsider`, which is what keeps the
        ruling inside this store's critical section while the *loop* stays on the
        concrete engine where ADR-0083 §8 puts a maintenance surface.

        Ordered by ``reconsider_at`` ascending with ``id`` ascending as tie-break,
        so the record that has been due longest is on the first page.

        Args:
            limit: How many to return; defaults to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`.
            offset: How many to skip.

        Returns:
            A detached snapshot of the due records, oldest due first.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
            NotificationStoreError: If the store cannot be read.
        """
        ...

    async def held(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> list[HeldNotification]:
        """The retained records, for the enumeration §7's read surface serves.

        **Every retained record, not only the actionable ones.** §7 is explicit
        that expiry "deletes nothing, and an expired record stays enumerable and
        renders as expired", so filtering here would hide from the user the
        record whose moment passed — which is most of what there is to say about
        a notification.

        Ordered **oldest first**, by ``admitted_at`` ascending with ``id``
        ascending as tie-break, on ADR-0078 §7's ordering and for its reason: the
        cap refuses rather than evicts, so the record blocking a newer one is the
        oldest actionable one and belongs on the first page. §11 declines an
        urgency-ordered or imminent-expiry view here as ADR-0078 §7 declined it
        there.

        Args:
            limit: How many to return; defaults to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`.
            offset: How many to skip.

        Returns:
            A detached snapshot of frozen records, oldest first.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
            NotificationStoreError: If the store cannot be read.
        """
        ...

    async def get(self, notification_id: str) -> HeldNotification | None:
        """One record by id, or ``None`` where the id names nothing.

        Args:
            notification_id: The record to read.

        Returns:
            A detached snapshot, or ``None``.

        Raises:
            NotificationStoreError: If the store cannot be read.
        """
        ...

    async def dismiss(self, notification_id: str) -> bool:
        """End one record's actionability, leaving it readable (§7, §9).

        **A dismissal is not a deletion.** The record stays enumerable and stays
        in :meth:`export`; what ends is its actionability, which frees a slot
        under the cap **at once**.

        **It does not free the record's key** (ADR-0215 §§1-2, replacing the rule
        §7 stated here). The record goes on suppressing candidates carrying that
        key until the expiry its own candidate declared — or, where the candidate
        declared none, no further than its actionability reached. A dismissal is a
        statement about the record, and ADR-0131 §3b's reuse of it makes it a
        statement about bytes as well; neither is a statement about the *fact*,
        and a fact does not stop being the same fact because a record about it
        came off a list or a device confirmed some bytes. A fact that recurs after
        its notification **expired** is still a new candidate, because there the
        fact itself perished.

        Retention runs from this instant, not from admission (§7) — though a
        record that still speaks for its key is not purged at that horizon
        (:meth:`purge`).

        Dismissing a record that is already not actionable changes nothing and
        reports ``False``: the cessation instant a retention horizon is measured
        from may not be moved by a second call.

        Args:
            notification_id: The record to dismiss.

        Returns:
            ``True`` if an actionable record was dismissed, ``False`` if the id
            named nothing or named a record that was already not actionable.

        Raises:
            NotificationStoreError: If the store cannot be written.
        """
        ...

    async def preferences(self) -> NotificationPreferences:
        """The three standing settings in force (§6).

        **An empty store is a working policy.** A store holding no preference
        returns
        :class:`~ai_assistant.core.types.NotificationPreferences`' shipped
        defaults — reach ``hold`` for every class, no quiet windows, and three
        interruptions per rolling twenty-four hours — so no setting is a
        precondition of the system running and the tuning surface works on the
        first day, from an empty store, with no history.

        Returns:
            The settings, defaulted where the user has set nothing.

        Raises:
            NotificationStoreError: If the store cannot be read.
        """
        ...

    async def set_preferences(self, preferences: NotificationPreferences) -> int:
        """Write the standing settings, and re-arm what the change reaches (§6).

        **The write and the re-arming are one atomic act.** Writing a standing
        setting sets ``reconsider_at`` to the instant of the write on every
        **actionable held** record whose *failed-condition set* holds a condition
        that change could remove. ``reconsider_at`` is a floor, so this may move
        a record's due instant earlier as well as give it one — and a record
        whose set holds only the expiry condition is reached by no setting and
        keeps the stamp its ruling gave it.

        **Reading the whole failed set is what makes the rule correct, and the
        first reason is not.** A candidate inside a quiet window closing at 08:00
        whose budget is also spent until 10:00 is held with two failures and due
        at 10:00. If the user raises the budget at 07:30, a rule reading only the
        recorded first reason sees "quiet window", leaves the record at 10:00,
        and loses the two hours the user just bought.

        **Lowering a class's reach to ``off`` is the one change that reads no
        failed set**: it makes **every** actionable held record of that class due
        at the instant of the write, so each is ruled ``DROP`` on the next
        reconsideration and ceases to be actionable. "Never tell me this" reaches
        what is already held, not only what comes next — the one direction where
        under-reaching costs the user something rather than the machine.

        **No setting change reaches a record already ruled ``INTERRUPT``** (§6).
        Reconsideration is an operation on a *held* record throughout, and
        whether contact already handed to a channel can be recalled is the
        delivery seam's question, not this one's.

        **Nothing here re-rules anything.** Stamping the write instant routes the
        act through §5's one ruling path instead of adding a second, and the
        reconsideration job picks the records up on its next run.

        **The whole value is written, and the last write wins.** A caller
        changing one setting reads, adjusts and writes back, so two writers
        racing each other lose the earlier one's edit entirely — this contract
        carries no version token and detects no conflict, and saying so is the
        point of stating it. The alternative was not free: a per-field write
        loses the *same* update with no way to notice it happened, and a
        conflict-detecting write is contract surface ADR-0130 §9 does not
        ratify. Both writers here are a person at a prompt rather than a machine
        on a timer, which is why ADR-0078 §2's resolve-once compare-and-set
        earns its cost there and not here. Tracked as an open question against
        real usage rather than decided by an implementing lane.

        Args:
            preferences: The settings to hold from now on, **replacing** what is
                held rather than merging into it.

        Returns:
            How many records the write made due for reconsideration.

        Raises:
            NotificationStoreError: If the store cannot be written.
        """
        ...

    async def delete(self, notification_id: str) -> bool:
        """Destroy one record — **unconditionally** (§9, ADR-0004 §6).

        ADR-0007's data right. No state
        refuses it, and it is a different act from :meth:`dismiss`: a dismissal
        ends actionability and leaves the record readable, so the *delete*
        surface is what ADR-0004 §6's delete right reaches.

        Destroying the record destroys its ``candidate_key`` with it, so the same
        observation may be proposed again and admitted afresh.

        **It does not refund a unit of budget** (§5). Destroying the record of an
        interruption does not unmake the interruption, and a store that let it
        would hand any caller a way to spend the budget twice per window.

        Args:
            notification_id: The record to destroy.

        Returns:
            ``True`` if a record was removed, ``False`` if the id named nothing.

        Raises:
            NotificationStoreError: If the store cannot be written.
        """
        ...

    async def clear(self) -> int:
        """Destroy every record, whatever its state (§9, ADR-0007).

        The sweep half of the data right, and unconditional in the same way
        :meth:`delete` is. It does **not** reset the standing preferences: those are
        the user's settings rather than the user's notifications, and a sweep that
        silently restored every class to ``hold`` would undo a "never tell me this"
        the user meant to keep. It does **not** refund the budget either, for
        :meth:`delete`'s reason (§5).

        Returns:
            How many records were destroyed.

        Raises:
            NotificationStoreError: If the store cannot be written.
        """
        ...

    async def export(self) -> list[HeldNotification]:
        """Return every stored record, for the user's own data export (ADR-0004 §6).

        A plain list of the frozen record type, rather than a bespoke export type.
        Every record is included, dismissed, expired and dropped alike: the content
        is the user's and the export is theirs.

        Raises:
            NotificationStoreError: If the store cannot be read, or a stored
                record is corrupt.
        """
        ...

    async def purge(self) -> int:
        """Sweep the records retention has released (§7).

        Called by the retention purge job ADR-0083 §7 already runs, in the shape
        it already calls ``MemoryStore.purge_expired``.

        A record is purgeable only once it **no longer speaks for its key**
        (ADR-0215 §§1, 4, replacing §7's actionability test) and its stamped
        retention has elapsed past the horizon — never at it
        (:meth:`~ai_assistant.core.types.HeldNotification.is_purgeable_at`). Both
        halves are load-bearing: **no record is purged while it is still
        speaking, whatever its retention**, so a record's key suppresses
        duplicates for the whole time §8 says it does — which is §7's own stated
        reason applied to the population §8 now reads, and without it a deployment
        with a short retention reproduces #1372 on a slower schedule; and
        ``retention is None`` is a complete answer rather than an undefined
        expression — such a record is never purged.

        **Both conditions are the record's own to answer**, and a store may not
        compose the speaking test around ``is_purgeable_at`` in a backend or a
        helper (ADR-0215 §4): a store asks the record whether it is purgeable and
        purges what says yes. Two conforming stores must not be able to disagree
        about the instant a record becomes purgeable, and a backend that composed
        it would pass every store-level conformance case while the *next* backend
        written against the type purged a record that still speaks.

        **The retention read is the record's, never the live setting's** (§7), so
        a configuration change never reaches back and shortens the horizon of a
        record already admitted.

        **It refunds no unit of budget** (§5), which matters here more than at
        :meth:`delete`: this is a *scheduler's* act, so a store deriving its spend
        count from the retained records would widen the budget on a timer wherever
        a deployment configured a retention shorter than the budget window.

        Returns:
            How many records were removed.

        Raises:
            NotificationStoreError: If the store cannot be written.
        """
        ...


@runtime_checkable
class TraceSink(Protocol):
    """Where an emitter puts a trace, and the only trace seam a subsystem holds.

    The narrow half of ADR-0119 §7's three-way split, and the *write* seam is the
    narrow one here where ADR-0097 §5 made the *query* seam narrow — the same
    mechanism turned the other way round. **Every emitting site takes one of these
    as a required constructor argument with no default**, so a composition that
    omits it does not type-check. An optional sink defaults to unwired, an unwired
    emitter produces no traces, and no traces is indistinguishable from no events
    — the lie ADR-0119 §5 refuses, arriving through composition instead of I/O.

    **What a holder of this seam cannot do is read a trace back** (§7). Nothing
    this system does is conditioned on what a trace says, no trace is ever
    assembled into a prompt, and a trace the pipeline cannot read is a trace
    `models/` cannot send — so ADR-0004 §2's egress rule needs no new exception.

    **The instrument is subordinate to the work it observes** (§5). No retrieval,
    write, turn, scheduled run or startup fails, retries, or changes its result
    because a trace could not be written; see :meth:`emit`.

    Cancelling :meth:`emit` is governed by this module's cancellation clause
    (ADR-0060). Its input-observation clause (ADR-0065) is **vacuous**: the one
    argument is an :class:`~ai_assistant.core.types.EvaluationTrace`, which is
    immutable all the way down — every mapping it holds is detached and frozen at
    validation (ADR-0119 §13a).
    """

    async def emit(self, trace: EvaluationTrace) -> None:
        """Append ``trace``. **No trace-store failure escapes** (ADR-0119 §5, §7).

        **Idempotent on the trace's id.** A second trace bearing an id the store
        already holds is refused *silently* — logged as an emission failure under
        §5, with the stored trace kept. Unlike :meth:`AuditTrail.record`, where
        "re-recording an id already present raises rather than overwriting",
        raising is not available here because §5 subordinates the instrument; and
        overwriting would let a later write rewrite the record of an earlier
        event. Keeping the first is the only option that loses nothing already
        recorded.

        **A trace that could not be recorded is logged**, as a Tier 2 log record
        naming the kind, the seam and the failure's class (§5). Emission failure
        is never silent: a missing trace is otherwise indistinguishable from a
        non-event, which is the specific way an instrument lies.

        **No trace is emitted for the writing of a trace** (§5), which is both the
        #710 lesson applied before the fact and what closes the obvious regress.

        It is safe to promise that no store failure escapes because the trace is a
        validated pydantic model before this is called: a malformed trace is an
        emitter bug that fails at construction, in the emitter's own tests, and
        never reaches here. What ``emit`` can therefore encounter is
        environmental — a locked database, a full disk — which is precisely the
        class §5 subordinates. That in turn is safe to say only because ADR-0119
        §3 makes the one externally-sourced string,
        :attr:`~ai_assistant.core.types.EvaluationTrace.fault_class`, a **total**
        conversion (:func:`~ai_assistant.core.types.fault_class_of`) rather than a
        validation an exception could fail.

        Args:
            trace: The event to record, already stamped by the emitter's clock.

        Raises:
            CancelledError: **Not a blanket no-raise.** A cancellation delivered
                from outside the call is re-raised once the sink has made its
                resources safe, as this module's cancellation clause requires of
                every method in it (ADR-0060 §1). An instrument that swallowed one
                would defeat the shutdown drain rather than subordinate itself
                to it.
        """
        ...


@runtime_checkable
class TraceRetention(Protocol):
    """The trace store's deletion seam: a horizon, swept by the job that already sweeps.

    The second narrow seam (ADR-0119 §7). Purging is `orchestration`'s capability
    rather than an emitter's, because ADR-0083 §8 puts the retention purge behind
    an ``Engine`` maintenance operation and ADR-0119 §10 wires the trace purge
    there rather than inventing a second sweeping mechanism — ADR-0078 §10 item
    8's instruction taken literally, as ADR-0083 §7 already took it for the
    deferral purge.

    **There is no count cap and no size cap** (§10). A trace is deleted only for
    being older than the horizon. A cap evicts the *oldest* rows, which in #829's
    design are the unarmed baseline — the half of the natural experiment that
    cannot be re-created.

    **Enforcement is by deletion only.** A trace still on disk is returned by
    :meth:`TraceStore.walk` whatever its age; there is no read-time retention
    filter. That is a difference from ADR-0007 §2 rather than a departure from it:
    that rule enforces at read time because it is a *privacy* guarantee over Tier
    1, and a Tier 2 horizon is a disk-space policy over data that identifies
    nobody.

    Cancelling :meth:`purge_before` is governed by this module's cancellation
    clause (ADR-0060); its input-observation clause (ADR-0065) is vacuous, the one
    argument being an instant.
    """

    async def purge_before(self, instant: UtcInstant) -> int:
        """Delete every trace older than ``instant``; return how many (ADR-0119 §10).

        ``UtcInstant`` rather than a merely-aware ``datetime``: a horizon compared
        against stored instants must be canonicalised the same way, or the sweep
        and the rows it sweeps disagree about what "older" means (ADR-0023,
        ADR-0030).

        **This one raises**, unlike :meth:`TraceSink.emit`. A sweep is not the work
        being observed, so ADR-0119 §5's subordination has nothing to say about it,
        and a purge that silently did nothing would let a store grow without bound
        behind a horizon an operator believes is enforced.

        The purge's own ``OPERATION`` trace lands in the store it just swept, one
        instant after the sweep, and is therefore never a candidate for it. Noted
        because it looks like a paradox and is not.

        Args:
            instant: The horizon. A trace whose ``occurred_at`` is strictly before
                it is deleted; one at the instant is kept.

        Returns:
            How many traces were removed.

        Raises:
            TraceStoreError: If the store cannot be written.
        """
        ...


@runtime_checkable
class TraceStore(TraceSink, TraceRetention, Protocol):
    """The whole trace store: append, purge, and the walk nothing in the pipeline holds.

    The seventh SQLite database under ``Settings.data_dir`` (ADR-0119 §6), and a
    **Tier 2** store — the only one in this file that is. A separate database
    rather than a table beside an existing one, for two reasons and the second
    decides: a trace about a failed write inside the failed write's own database
    is lost exactly when it is most wanted, and this is the only store here with a
    decided deletion horizon, so putting a swept table beside ``memory.db``'s
    retention axes would be three lifetimes in one file.

    **It structurally satisfies both narrow Protocols**, so one concrete
    implements all three and the composition root hands each collaborator exactly
    the seam it is entitled to (§7): a :class:`TraceSink` to every emitter, a
    :class:`TraceRetention` to the ``Engine``'s maintenance operation, and this
    type to nothing in the pipeline. That is the arrangement
    :class:`SourceGrants`/:class:`SourceGrantStore` uses today, with one more
    specialisation because there is one more capability.

    **No component of the request pipeline holds a seam carrying the walk** —
    `orchestration`, `memory`, `planning`, `readers`, `learning`,
    `tools`, `permissions` — and none reads a trace back (§7). An instrument whose
    readings change behaviour is measuring a system that includes the instrument,
    and leg 8's exit test would be circular in a way that is nearly impossible to
    see afterwards in the numbers.

    **A reference is permitted to dangle** (§10). A trace referencing a deleted
    record keeps an opaque id that now resolves to nothing, which is the honest
    record: the deletion does not un-happen the retrieval, and an id whose row is
    gone identifies nobody. Nothing here ever resolves a reference to check it.

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060).
    """

    async def walk(self, *, after: TracePosition | None = None, limit: int) -> TraceChunk:
        """One chunk in insertion order, resuming after ``after`` (ADR-0119 §7a).

        **The order is the store's total insertion order** — the order in which
        appends landed, never ``occurred_at`` order — under ADR-0114 §2's rule that
        a position "is opaque to its caller, and is never a value a caller
        composes". ADR-0119 §3 has the *emitter* stamp the instant, so two traces
        can carry the same one and a slow sink can land an earlier instant after a
        later one; an order over ``occurred_at`` is therefore neither total nor
        stable, and a page boundary drawn on it can skip a row that arrives behind
        the cursor. A measure that wants a time window filters within the walk; it
        does not order by time.

        **One call returns an ordered prefix**: at most ``limit`` traces, in
        insertion order, of those appended after ``after`` and still present. It
        returns no trace at or before that position. The *completeness* guarantee
        is a property of the **sequence** of calls, each resumed from the position
        the last one handed back — calls resumed that way collectively return every
        retained trace after the first position, in order and exactly once. An
        append that lands during a call takes a position after every position
        already issued, so no page boundary skips or duplicates a trace.

        **Every chunk carries a position, always** — after the last trace returned,
        or, when the chunk is empty, the position the walk was resumed from, and
        for a walk starting at ``None`` the store's floor. There is no exhausted
        state in which a caller is handed no position. An earlier draft had the
        walk report exhaustion with ``position: None``, which is the natural shape
        and wrong: a reader handed that has stopped *and thrown away the only thing
        that would let it resume*, so a trace appended between the query and the
        return is unreachable.

        **A chunk shorter than ``limit`` means nothing further is present yet**,
        never "this walk is over". A caller may resume from the position it was
        handed at any later time and receive whatever has been appended since. The
        walk is a high-water mark rather than an iterator.

        **The position is the caller's to hold.** This store persists no cursor,
        names no walk, and two concurrent readers never contend — unlike
        :meth:`MemoryStore.advance_walk`, whose walk is resumed by a scheduled
        *job* across process restarts (ADR-0111 §1, ADR-0114 §5). A measure is a
        reader, not a job.

        A resumed walk may see rows appended since the position was issued —
        correct, since they are genuinely later — and may find rows gone that were
        present when it started, which is ADR-0119 §10's purge doing its job.
        Neither is an anomaly.

        **The one operation no pipeline component may reach** (§7).

        Args:
            after: Where to resume, or ``None`` to start at the store's floor.
                Opaque: the only admissible source is a :class:`TraceChunk` this
                store returned.
            limit: The most traces to return. Keyword-only and **required**: a
                default would make the unbounded read the easy one.

        Returns:
            The chunk, and the position it reached.

        Raises:
            ValueError: If ``limit`` is zero or below, as ADR-0114 §6 refuses one
                for the chunked walk and for the same reason; or if ``after`` is a
                position this store cannot read — a caller-held position this store
                did not issue is a caller bug, not the recoverable state ADR-0111
                §7 discards for a *durable* cursor. Every refusal in this contract
                is a ``ValueError``, mirroring ADR-0114 §6a.
            TraceStoreError: If the store cannot be read, or holds a row that
                cannot be hydrated — a row carrying no readable ``id`` included
                (ADR-0119 §3). Every trace returned is a **detached snapshot**, as
                :class:`AuditTrail` and :class:`MemoryStore` already give, for the
                reason ``AuditTrail`` states: ``frozen=True`` refuses
                ``x.outcome = …`` and not ``x.__dict__["outcome"] = …``.
        """
        ...


@runtime_checkable
class DiagnosticSink(Protocol):
    """Where an emitter writes a diagnostic entry, and all it can do there (ADR-0314 §3).

    The write seam of the diagnostic record: one file per activation, holding what
    each phase was given and returned (§6). **There is no read.** No Protocol in
    this module carries a read of the record, so nothing handed this seam can read
    an entry back, and nothing the system decides is conditioned on one (§3:1).
    The store implementing it lives in ``evaluation/``, which no subsystem imports,
    and the composition root hands each emitter this seam, or ``None`` where
    ``Settings.diagnostic_record`` is false (§4:4).

    **The instrument is subordinate to the work it describes** (§2:4): no stage
    fails, retries or changes its result because an entry could not be written;
    see :meth:`write`.

    Cancelling :meth:`write` is governed by this module's cancellation clause
    (ADR-0060). Its input-observation clause (ADR-0065) is vacuous: the one
    argument is a :class:`~ai_assistant.core.types.DiagnosticEntry`, immutable all
    the way down.
    """

    async def write(self, entry: DiagnosticEntry) -> None:
        """Append ``entry`` to its activation's file. **No failure escapes** (§2:4).

        An entry that cannot be written — a refused activation id, a full file, a
        full disk — is dropped and logged naming the activation, the source and the
        failure's class, never any of the entry's content (ADR-0004 §5).

        Args:
            entry: The entry, stamped by its emitter.

        Raises:
            CancelledError: **Not a blanket no-raise.** A cancellation delivered
                from outside the call makes the file safe and is re-raised (§2:5,
                ADR-0060 §1), as :meth:`TraceSink.emit` re-raises one.
        """
        ...


@runtime_checkable
class DiagnosticRetention(Protocol):
    """The diagnostic record's deletion seam: its window, swept by the one sweep (§7).

    What the ``Engine``'s retention sweep is handed, beside the trace store's
    :class:`TraceRetention`; it deletes files by age and reads no entry (§3:3).
    The sweep runs whether or not the record is on, so files written while it was
    on are still deleted after it is turned off (§7:3).

    Cancelling :meth:`purge_before` is governed by this module's cancellation
    clause (ADR-0060); its input-observation clause (ADR-0065) is vacuous, the one
    argument being an instant.
    """

    async def purge_before(self, instant: UtcInstant) -> int:
        """Delete every file in the record whose last write is older than ``instant``.

        **This one raises**, as :meth:`TraceRetention.purge_before` does: a sweep is
        not the work being described, and a sweep that silently did nothing would
        keep raw outside text past the window the owner believes deletes it.

        Args:
            instant: The window's edge. A file last written strictly before it is
                deleted; one written at it or after is kept.

        Returns:
            How many files were deleted.

        Raises:
            DiagnosticRecordError: If the record's directory cannot be listed or a
                file in it cannot be deleted.
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

    **One argument convention, applied to every method below** (ADR-0085 §2, and
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

       **On a method that returns an iterator the clause is restated rather than
       relaxed** (ADR-0173 §11): the limit is enforced **on each value before it is
       yielded** — on every chunk and on the terminal value alike — in place of
       "on results before return", which such a method has no single point to
       satisfy. What moves is *when* the check runs, not what it admits, and
       ADR-0173 §3's ceiling is the same rule read forward for a reply stream:
       because no chunk is yielded whose text the terminal value cannot repeat, a
       stream cannot publish text the limit would have refused.

       **On a mutating call the result is measured after the work has committed**,
       because no measurement of a result can precede producing it — and a wire
       client meets the same situation one frame further out. The effect stands and
       is readable through the surface's own reads; ADR-0085 §8e names this residual
       and declines to design around it, since the unbounded factor is #473's and
       ADR-0084 §11 makes that the client lane's prerequisite. Tracked in #570.

    :class:`~ai_assistant.core.errors.OversizedValueError` is therefore declared by
    **every** method below and is not repeated in each one's ``Raises`` block. No
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

    # --- the turn calls (ADR-0042 §3, ADR-0293 §11) -----------------------

    async def receive(
        self,
        input: ChannelInput,  # noqa: A002 — ADR-0274 §4 names the public parameter
        *,
        reply: SpokenReply | None,
        timeout: timedelta,  # noqa: ASYNC109 — operation budget (ADR-0274 §4)
    ) -> ChannelResult:
        """Process a channel input and return its result (ADR-0274 §§3-8).

        Snapshot nested input before admitting work. The one supported
        combination is informational_event/text/no reply (ADR-0313 §4:1). No
        conversational combination is one: ADR-0293 §11 replaces the text one
        with the acts in the medium, a typed message being written into a
        conversation rather than received here, and ADR-0313 §3:2 retires the
        spoken one with spoken conversation. Every other combination raises
        ValueError before processing and before collaborator I/O. Supplied local
        context reaches processing separately from stored history and acquires
        no authority.

        An event runs through the phases as one activation, and one that cannot
        finish or is stopped returns its result rather than raising (ADR-0313
        §4:3-§4:5). Cancellation propagates after cleanup. A result returns only on this
        call; errors are never success receipts. Public wrapper fields count against the
        payload limit.
        """
        ...

    async def stop_activation(self, activation_id: Identifier, /) -> ActivationStop:
        """Stop one running activation (ADR-0297 §5, ADR-0295 §1).

        The stop command, naming exactly one activation by the id a device read from
        its conversation's current state while it showed "working…". **Two writes in
        a fixed order** (ADR-0297 §3): the activation's in-process stop mark, set in
        one synchronous step that first tests whether its end entry is appended, and
        then its stop record in the plan store, against which the store refuses every
        later claim made under that activation (§2). **No task is cancelled**: a stage
        already running runs to its own end under its own deadlines, and an effect
        already sent finishes and records its outcome (§4). The stopped pass then ends
        with the stop's end entry, writes nothing into its conversation, and a turn
        call awaiting it raises
        :class:`~ai_assistant.core.errors.ActivationStoppedError`.

        **It checks no device role itself** (§5:7): it is reached only as a command,
        and which devices may send one is decided where every command's sender is
        checked.

        Args:
            activation_id: The activation to stop.

        Returns:
            :attr:`~ai_assistant.core.types.ActivationStop.STOPPED` where the mark
            was set, or found already set, on an activation whose end entry was not
            yet appended, and its stop record was written;
            :attr:`~ai_assistant.core.types.ActivationStop.ALREADY_ENDED`, writing
            nothing, where its end entry was already appended or no running
            activation has that id but an episode stands at
            ``activation:<activation_id>``; and
            :attr:`~ai_assistant.core.types.ActivationStop.NO_SUCH_ACTIVATION`,
            writing nothing, where neither holds.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``activation_id`` is not an identifier.
            PlanningError: If the stop record cannot be written. The mark stays set,
                so the activation still ends as stopped and starts nothing new, and a
                repeated stop writes the record again (§3:7).
            MemoryStoreError: If the episode store cannot be read to tell an ended
                activation from one that never ran.
        """
        ...

    # --- the inspection surface (ADR-0073 §7, ADR-0077 §6) ----------------

    async def episodes(
        self,
        *,
        channel: ChannelIdentity | None = None,
        status: ProcessingStatus | None = None,
        cursor: NonBlankEncodableText | None = None,
        limit: int = 50,
    ) -> EpisodePage:
        """Read live episode summaries in descending capture order (ADR-0275)."""
        ...

    async def episode_chunk(
        self,
        episode_id: EncodableText,
        *,
        version: NonBlankEncodableText | None = None,
        offset: int = 0,
        max_bytes: int = 65536,
    ) -> EpisodeChunk | None:
        """Read canonical episode bytes, preserving the exact address (ADR-0275)."""
        ...

    # --- stories (ADR-0289 §4) ---------------------------------------------
    #
    # **Nine methods over the story store, and no stage reads them.** Every write
    # carries the actor ``owner`` and no triggering activation. Before a create or a
    # link naming an activation member, the engine reads ``activation:<id>`` through
    # ``MemoryStore.get`` for each and refuses the write with ``unknown_activation``
    # where no record is there; an open episode is a record there (ADR-0286 §6), so a
    # running activation can be linked. A merge or a split checks no activation. A
    # refusal is a ``StoryOutcome``, never an exception.

    async def create_story(self, members: Sequence[StoryMember]) -> StoryOutcome:
        """Create a story holding ``members``, as the owner (ADR-0289 §§3-4).

        Raises:
            ValueError: If ``members`` is malformed.
            StoryStoreError: If the story store cannot be read or written.
            MemoryStoreError: If an activation's record cannot be read.
        """
        ...

    async def link_story(
        self, story_id: Identifier, members: Sequence[StoryMember]
    ) -> StoryOutcome:
        """Add ``members`` to a story, as the owner (ADR-0289 §§3-4).

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the story store cannot be read or written.
            MemoryStoreError: If an activation's record cannot be read.
        """
        ...

    async def unlink_story(
        self, story_id: Identifier, members: Sequence[StoryMember]
    ) -> StoryOutcome:
        """Remove ``members`` from a story, as the owner (ADR-0289 §§3-4).

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the story store cannot be read or written.
        """
        ...

    async def merge_stories(self, story_id: Identifier, into: Identifier) -> StoryOutcome:
        """Merge story ``story_id`` into story ``into``, as the owner (ADR-0289 §§3-4).

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the story store cannot be read or written.
        """
        ...

    async def split_story(
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        notes: Sequence[StoryNoteId] = (),
    ) -> StoryOutcome:
        """Split ``members`` off a story into a new one, as the owner (ADR-0289 §§3-4).

        Exactly the notes named in ``notes`` that the story holds go to the new
        story, in the split's transaction, and are pending there; a note named that
        it does not hold is passed over, and no note goes by the activation it was
        written during (ADR-0303 §6:1-§6:2, §10:1). Every other note stays.

        Args:
            story_id: The story split.
            members: The members that leave it, every one a current member.
            notes: The notes that go with them; none by default.

        Returns:
            The new story's id, or a refusal: ``no_members``, ``unknown_story``,
            ``merged_story``, or ``not_a_member`` naming a member the story does
            not hold.

        Raises:
            ValueError: If an argument is malformed: a note id that is not an
                integer in ``[1, 2**63)`` among them.
            StoryStoreError: If the story store cannot be read or written.
        """
        ...

    async def story(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryView | None:
        """Read a page of a story's members, resolved (ADR-0289 §4).

        Each activation member carries its episode's ``EpisodeSummary``, or is marked
        forgotten where no record is there any more; each story member carries its
        current member count, one level deep. A page too large for the payload limit
        is shortened, with a cursor resuming after the last member it keeps.

        Returns:
            The view, or ``None`` where the store holds no such story.

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the story store cannot be read.
            MemoryStoreError: If an activation's record cannot be read.
        """
        ...

    async def story_log(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryLogPage | None:
        """Read a page of a story's change log, oldest first (ADR-0289 §4).

        Returns:
            The page, or ``None`` where the store holds no such story.

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the story store cannot be read.
        """
        ...

    async def stories(
        self, *, cursor: int | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> StoryPage:
        """Read a page of every story, newest first (ADR-0289 §4).

        Raises:
            ValueError: If an argument is malformed.
            StoryStoreError: If the story store cannot be read.
        """
        ...

    async def activation_stories(self, activation_id: Identifier) -> tuple[StoryHeader, ...]:
        """Read the stories an activation belongs to directly, newest first (ADR-0289 §4).

        Raises:
            ValueError: If the id is malformed.
            StoryStoreError: If the story store cannot be read.
        """
        ...

    # --- the story commands (ADR-0300 §8) -----------------------------------
    #
    # **Four more, over the story's summary and where its matter stands.** Each names its
    # story by id. The reads show the owner what ADR-0303 §3's default lets a reader be
    # shown, with the summary's mark and each note's (§3:8); the writes carry the owner as
    # author or actor and no triggering activation (ADR-0289 §4:4). A move, like a
    # merge or a split, moves members a story already holds and checks no activation's
    # record (ADR-0289 §4:3); a move or a split carries exactly the notes it names
    # (ADR-0303 §6). A refusal is an outcome, never an exception.

    async def story_summary(self, story_id: Identifier) -> StorySummaryView | None:
        """Read a story's summary as the owner is shown it (ADR-0300 §8:3, ADR-0303 §10:2).

        When the summary was last tidied; its lines and its mark, or
        that the summary was withheld; and the story's notes, newest first up to the
        view's bound, each with its id, its mark and whether it is pending, with the
        count of those beyond it. The owner is shown the summary, as a record placed for
        the owner alone, and nothing behind it decides that: no version log is walked
        and no episode or note it took in withholds it, forgotten or not (ADR-0304
        §4:1, §4:3). The notes are listed so that the owner can name them in a split
        or a move.

        Returns:
            The summary, or ``None`` where the store holds no such story. A merged
            story's carries its header alone.

        Raises:
            ValueError: If the id is malformed.
            StoryStoreError: If the story store cannot be read.
        """
        ...

    async def story_standing(self, story_id: Identifier) -> StoryStanding | None:
        """Read where a story's matter stands, worked out for the owner (ADR-0300 §8:1).

        Assembled from the records each time, never stored: what was done, the
        timeline of its episodes, an open one marked in progress, and the related
        matters.

        Returns:
            Where it stands, or ``None`` where the store holds no such story. A
            merged story's carries its header alone.

        Raises:
            ValueError: If the id is malformed.
            StoryStoreError: If the story store cannot be read.
            MemoryStoreError: If an episode cannot be read.
        """
        ...

    async def add_story_note(
        self, story_id: Identifier, text: NonBlankEncodableText
    ) -> StoryNoteOutcome:
        """Add a note to a story, written by the owner (ADR-0300 §8:3).

        The note rests on nothing and is never marked as fed by outside content
        (§3:3-§3:4); it is pending on the story until a version of its summary takes
        it in.

        Returns:
            The note as written, or a refusal: ``unknown_story``, or
            ``merged_story`` naming where the story went.

        Raises:
            ValueError: If an argument is malformed: a blank text, or one longer
                than ``STORY_NOTE_MAX_CHARS``.
            StoryStoreError: If the story store cannot be read or written.
        """
        ...

    async def move_story_members(
        self,
        story_id: Identifier,
        to: Identifier,
        members: Sequence[StoryMember] = (),
        *,
        notes: Sequence[StoryNoteId] = (),
    ) -> StoryOutcome:
        """Move activation members, notes, or both, from one story to another, as the owner.

        ADR-0300 §3:14, ADR-0303 §6:1-§6:2 and §10:1, ADR-0304 §9. Exactly the notes
        named in ``notes`` that the first story holds go to the second, in one
        transaction with the members, and are pending there, each logged on both
        stories; no note goes by the activation it was written during, and every
        other note stays. A **note move** names no member and one or more notes;
        where members are named as well, a named note the first story does not hold
        is passed over.

        Args:
            story_id: The story moved from.
            to: The story moved to, another story.
            members: The activation members to move, every one a current member of
                the first story; none by default.
            notes: The notes that go; none by default.

        Returns:
            The second story's id with the count of lines appended, or a refusal:
            ``no_members`` where it names no member and no note; ``unknown_story``
            or ``merged_story`` for either side, the first story first;
            ``not_a_member`` naming a member the first story does not hold; or, for
            a note move, ``no_notes`` naming the first story where it holds none of
            the notes named.

        Raises:
            ValueError: If an argument is malformed: a story member named, the two
                stories the same, or a note id that is not an integer in
                ``[1, 2**63)``.
            StoryStoreError: If the story store cannot be read or written.
        """
        ...

    async def beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[BeliefSummary, ...]:
        """List the memories the assistant holds, newest revision first.

        **Memories by default**: with no ``kinds`` the listing excludes episodes
        (ADR-0328 §11:2), and a caller naming the episodic kind lists them (ADR-0074
        §6, kept by ADR-0328 §18). Every entry is a
        :class:`~ai_assistant.core.types.BeliefSummary`: a memory's carries the values
        ADR-0328 §15:1 names, and an episode's is
        :func:`~ai_assistant.core.types.episode_summary`'s. **Returns summaries, not the
        single-memory view**, and the type is the enforcement (ADR-0085 §4a): a
        summary has nowhere to put a support's content, so a conforming listing cannot
        ship the corpus on every page. It still resolves whether each memory's
        supports' episodes resolve, for §15:7's mark.

        Args:
            bands: Which bands to include, or ``None`` for every band. An empty
                sequence selects nothing, which is a different answer from ``None``.
            kinds: Which kinds to include, or ``None`` for memories alone. An empty
                sequence selects nothing. The two filters compose by conjunction.
            limit: How many to return. Defaults to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`, and an
                implementation called without it behaves as though it had been
                passed.
            offset: How many to skip.

        Returns:
            One summary per live record selected, in the store's stated order.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
                Refused rather than clamped, locally and before any I/O
                (ADR-0073 §2). An adapter that lets a user supply either should
                refuse an out-of-range value at its own parse boundary.
            MemoryStoreError: If reading memory failed.
        """
        ...

    async def belief(self, record_id: Identifier) -> Belief | None:
        """Read one memory with its supports resolved, or ``None`` if there is none.

        The single-memory view (ADR-0328 §15:2): every support, the part it points
        at resolved to readable content or shown as gone. An id naming an episode
        reads as :func:`~ai_assistant.core.types.episode_view`, so ``forget``'s
        ceremony shows an episode before destroying it, as it shows a memory
        (ADR-0074 §6, ADR-0073 §5).

        Args:
            record_id: The record's id, as the listing showed it.

        Returns:
            The view, or ``None`` where the store holds no live record by that id.

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

    async def pending_candidates(self) -> tuple[PendingCandidate, ...]:
        """Read the candidates the observer has not yet processed (ADR-0329 §18:2).

        The read the belief panel calls to show the pending candidates, each by its
        fact and marked pending (§18:1). A candidate is a ``remember`` call a round
        recorded, joined to the effect record that shows it done (§3:3), and it is
        pending while its episode has no observation record marked processed, skipped
        or stuck (§16:2). None of them is a memory: ``belief`` and ``forget`` name
        nothing by one.

        **Where ``remember`` records no candidate, it returns none.** Until the
        observer is wired, ``remember`` writes a memory under ADR-0328 §13's interim
        (ADR-0329 §19:3-§19:4), and no call it recorded is presented as pending.

        **Every pending candidate, whatever its age** (§18:1): a candidate recorded under
        an approval as well as one an episode's own rounds recorded (§3:3). The cost
        grows with the episode store, and an implementation keeps it small by reading
        in full only an episode the observer has not settled whose activation has a
        ``remember`` effect record done.

        Returns:
            The pending candidates, the most recent episode's first; within an
            episode, those its own rounds recorded in the order recorded, then those
            recorded under an approval in the order they ran. Empty where there are
            none.

        Raises:
            MemoryStoreError: If the episodes cannot be read.
            PlanningError: If the plan store cannot be read.
        """
        ...

    # --- the person model, for the panels (ADR-0338 §8:1-§8:3) -------------
    #
    # Eight members: two reads and six writes. **Shown only to that person and to the
    # owner** (§8:3): on the wire each is in the route table's command row, so a device
    # without the role of source of commands and queries, which the roster gives the
    # owner's devices alone, is refused before dispatch (ADR-0298 §5:6). **Every write
    # is a ``panel`` act by the owner**, the person the command role serves, on the
    # person's model (§3:4, §4:2); where the person is the owner, as on today's
    # one-person hub (§2:1), that is the person's act on their own.
    #
    # **Where the hub keeps no person model** — no person-model store is wired, which
    # is where ``Settings.person_model`` is off (§11:2) — each member raises
    # :class:`~ai_assistant.core.errors.PersonModelOffError`, after its arguments are
    # validated and before anything is read.
    #
    # Every id argument is ``NonBlankEncodableText``, refused blank and **never
    # stripped**: the person model holds every id verbatim, and a pointer that
    # normalised what it was handed could name another record (ADR-0338 §10:4).

    async def person_model(
        self,
        person_id: NonBlankEncodableText,
        *,
        lists: Sequence[PersonModelList] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> PersonModelView | None:
        """Read one person's model, as the About you panel shows it (ADR-0338 §8:1-§8:2).

        The fields; the kept-in-mind slot, assembled as the person block assembles it
        on a private place, which every place on the hub is today (§7), with the budget
        it fills and the memories it left out and why (§6:2, §6:4); the pins whose chain
        reaches no current memory, each with the wording of the memory it was made on
        (§4:8); the standing style marks, each with the current memory it shows, or the
        wording of the one it was made on where it shows none (§5:3); and the pending
        suggestions, each marked where it rests on outside content (§7:9), a pin
        suggestion's only while its memory is current (§9:5). A pin or mark whose memory
        the memory store no longer holds is shown nowhere (§4:10). The change log is
        :meth:`profile_changes`'s, a page at a time.

        Every memory it shows is worded, as the memory store holds it under the id
        the pin, mark or suggestion points at, so the panel reads no memory again by an
        id an implementation could normalise.

        **Its five lists are paged together**: the slot, what it left out, the pins no
        longer current, the style marks and the suggestions each hold the page of
        their own order ``offset`` and ``limit`` name, beside their totals, so every
        entry is reached by bounded reads however many there are. Each entry carries
        its own wording beside the id its control names, so a page is rendered with no
        other, and the slot's fill is the whole slot's, whatever the page.

        Args:
            person_id: The person, by id: :data:`~ai_assistant.core.types.OWNER_PERSON_ID`
                on today's hub.
            lists: The lists the page fills, or ``None`` for every one; an empty
                sequence fills none. A list not named is empty and its total still
                given, so one entry of one list is the smallest read.
            limit: How many entries each list's page holds at most.
            offset: How many of each list's entries to skip.

        Returns:
            Their model, or ``None`` where the hub holds no such person.

        Raises:
            ValueError: If ``person_id`` is blank or unwritable, or ``limit`` or
                ``offset`` falls outside ``0 <= value < 2**63``. Refused locally.
            TypeError: If ``limit`` or ``offset`` is not an integer.
            PersonModelOffError: If the hub keeps no person model.
            PersonModelStoreError: If the person-model store cannot be read.
            MemoryStoreError: If the memory store cannot be read.
        """
        ...

    async def profile_changes(
        self,
        person_id: NonBlankEncodableText,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[ProfileChange, ...]:
        """One page of a person's change log, the most recent change first (ADR-0338 §3:5).

        Every change to a field, with the old value, the new, who made it, when and how.
        The log is append-only and kept until the person's data is deleted, so it is
        read here a page at a time and never with the rest of :meth:`person_model`.

        Args:
            person_id: Whose log.
            limit: How many entries the page holds at most.
            offset: How many of the most recent to skip.

        Returns:
            The page; empty where the hub holds no such person, or past the log's end.

        Raises:
            ValueError: If ``person_id`` is blank or unwritable, or ``limit`` or
                ``offset`` falls outside ``0 <= value < 2**63``. Refused locally.
            TypeError: If ``limit`` or ``offset`` is not an integer.
            PersonModelOffError: If the hub keeps no person model.
            PersonModelStoreError: If the person-model store cannot be read.
        """
        ...

    async def set_profile_field(
        self,
        person_id: NonBlankEncodableText,
        *,
        field: ProfileField,
        value: EncodableText | None = None,
    ) -> PersonModelEdit:
        """Set one of a person's five fields, or clear it with ``None`` (ADR-0338 §3, §8:2).

        On the panel: validated and written by the store in one step with its
        change-log entry, and every pending suggestion of that field and value accepted
        in the same step (§3:2-§3:5, §8:8). A value equal to the one held changes and
        logs nothing (§3:3).

        Args:
            person_id: Whose field.
            field: Which field.
            value: Its new value, or ``None`` to clear it. ``None`` is the default
                because the wire carries an absent argument, never a ``null`` one
                (ADR-0085 §10): a clear sent from a client arrives with no value.

        Returns:
            The store's write: ``written``; ``unchanged``; or ``refused`` with
            ``unknown_person``, or ``invalid_value`` and its reason.

        Raises:
            ValueError: If ``person_id`` is blank, ``field`` is not one of the five, or
                an argument is unwritable. Refused locally.
            PersonModelOffError: If the hub keeps no person model.
            PersonModelStoreError: If the store cannot be read or written.
        """
        ...

    async def pin_memory(
        self, person_id: NonBlankEncodableText, *, memory_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Pin a memory for a person, on the beliefs panel (ADR-0338 §4:1-§4:3, §8:2).

        Only a current memory is pinned, and only where the wordings of the memories
        the person's pins show, with the new one's, stay within the slot's budget
        (§4:2, §6:3); the check and the write are made under the one lock per person
        every pin is made under. A memory already pinned changes nothing, and a pin
        accepts every pending pin suggestion of its memory in the same write (§8:8).

        Args:
            person_id: Whose pin.
            memory_id: The memory, by id.

        Returns:
            ``refused`` ``not_current`` or ``over_budget``, with nothing written; or the
            store's write: ``written`` with the pin's id, ``unchanged`` with the
            standing pin's, or ``refused`` ``unknown_person``.

        Raises:
            ValueError: If an id is blank or unwritable. Refused locally.
            PersonModelOffError: If the hub keeps no person model.
            PersonModelStoreError: If the person-model store cannot be read or written.
            MemoryStoreError: If the memory store cannot be read.
        """
        ...

    async def unpin_memory(
        self, person_id: NonBlankEncodableText, *, memory_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Unpin a memory for a person, erasing nothing (ADR-0338 §4:7, §8:2).

        Every standing pin that shows the memory — made on it, or whose chain's current
        end it is (§4:8) — is marked removed; so is a pin no longer current, named by
        the memory it was made on. The memory and its ``pinned`` support stay.

        Args:
            person_id: Whose pins.
            memory_id: The memory, by id.

        Returns:
            The store's write: ``written`` where a pin was removed, ``unchanged`` where
            no standing pin showed the memory, or the store's refusal that stopped the
            removal.

        Raises:
            ValueError: If an id is blank or unwritable. Refused locally.
            PersonModelOffError: If the hub keeps no person model.
            PersonModelStoreError: If the person-model store cannot be read or written,
                including after a first pin was removed: read :meth:`person_model`.
            MemoryStoreError: If the memory store cannot be read.
        """
        ...

    async def remove_style_mark(
        self, person_id: NonBlankEncodableText, *, mark_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Remove a style mark, so its memory is not marked again (ADR-0338 §5:3, §8:2).

        Args:
            person_id: Whose mark.
            mark_id: The mark, by the id :meth:`person_model` reads.

        Returns:
            The store's write: ``written``; ``unchanged`` where it was already removed;
            or ``refused`` with ``unknown_person`` or ``unknown_record``.

        Raises:
            ValueError: If an id is blank or unwritable. Refused locally.
            PersonModelOffError: If the hub keeps no person model.
            PersonModelStoreError: If the store cannot be read or written.
        """
        ...

    async def accept_person_suggestion(
        self, person_id: NonBlankEncodableText, *, suggestion_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Accept a pending suggestion on the panel (ADR-0338 §8:2, §8:8, §9:2, §9:5).

        A field suggestion takes its field to its value as an accepted suggestion, its
        change logged naming the episode it rests on (§3:5). A pin suggestion pins its
        memory as :meth:`pin_memory` does, checked the same way, and the pin accepts
        the suggestion in the same write (§8:8).

        Args:
            person_id: Whose.
            suggestion_id: The suggestion, by the id :meth:`person_model` reads.

        Returns:
            For a field suggestion, the store's write: ``written`` with the
            suggestion's id, or ``refused`` with ``unknown_person``,
            ``unknown_record``, ``already_decided``, or ``invalid_value`` and its
            reason where the value no longer passes the store's bound (§3:2). For a pin suggestion,
            :meth:`pin_memory`'s outcome for its memory.

        Raises:
            ValueError: If an id is blank or unwritable. Refused locally.
            PersonModelOffError: If the hub keeps no person model.
            PersonModelStoreError: If the person-model store cannot be read or written.
            MemoryStoreError: If the memory store cannot be read.
        """
        ...

    async def dismiss_person_suggestion(
        self, person_id: NonBlankEncodableText, *, suggestion_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Dismiss a pending suggestion, so an equal one is never recorded again (§9:2, §12).

        Args:
            person_id: Whose.
            suggestion_id: The suggestion, by the id :meth:`person_model` reads.

        Returns:
            The store's write: ``written``; or ``refused`` with ``unknown_person``,
            ``unknown_record`` or ``already_decided``.

        Raises:
            ValueError: If an id is blank or unwritable. Refused locally.
            PersonModelOffError: If the hub keeps no person model.
            PersonModelStoreError: If the store cannot be read or written.
        """
        ...

    # --- the hub page's approvals panel (ADR-0361 §4:6-§4:9, §8:4) ---------
    #
    # The panel is a surface of the one approvals store, beside the line's card (§4:1).
    # Both members are the person's own: a request is shown to, and answered by, the
    # person it is for, and on the hub page that person is established by the device
    # being admitted under ADR-0124 (§4:8), whose every enrolled device carries the
    # owner's single principal (ADR-0124 §5). So neither member names a person: the
    # person is the owner's, ``OWNER_PERSON_ID``, and a request for anyone else is not
    # shown and not answered. Both sit in the route table's command row, so a device
    # without the command role is refused before dispatch (ADR-0298 §5:6).

    async def approvals(self, *, limit: int = DEFAULT_PAGE_SIZE) -> ApprovalPanel:
        """The person's requests, as the hub page's approvals panel shows them (§4:6).

        The pending ones, the oldest first, and the ones answered or expired most
        recently, the most recent first, each with its state; each as its card shows
        it, by the one renderer every surface shows a request by (§2:11), and whole,
        so a request too long for one Telegram message is answered here (§4:4). A
        request still pending at or after its expiry is shown expired, since no tap
        can approve it now (§3:5).

        Args:
            limit: The most entries each of the two lists holds.

        Returns:
            The panel.

        Raises:
            ValueError: If ``limit`` is out of range. Refused locally.
            TypeError: If ``limit`` is not an integer. Refused locally.
            PlanningError: If the plan store cannot be read.
        """
        ...

    async def tap_approval(
        self, request_id: Identifier, /, *, choice: ApprovalChoice
    ) -> ApprovalPanelTap:
        """The panel's tap: approve or deny one of the person's pending requests (§4:9).

        **A command, never perceived** (§4:7): it starts no activation, joins none, and
        no model reads it. It marks the request approved or denied as
        ``ApprovalGiver.USER_TAP_ON_HUB_PANEL``, with the tap's instant, in the plan
        store's one step that refuses where the request is no longer pending, so the
        first tap to land, on the panel or on the card, wins, and a later one is
        answered with the request's state. A tap that landed wakes the Approvals
        channel's sensor, which pushes its outcome (§3:4); the line's reader edits the
        card (§4:5). A request that is not the person's changes nothing and is answered
        ``unknown``, showing nothing of it (§4:8).

        Args:
            request_id: The request, by the id :meth:`approvals` reads.
            choice: Approve or Deny.

        Returns:
            ``answered``, ``already_answered``, ``expired`` or ``unknown``, with the
            request as the panel now shows it on every answer but ``unknown``.

        Raises:
            ValueError: If ``request_id`` is not an identifier, or ``choice`` is
                neither Approve nor Deny. Refused locally.
            PlanningError: If the plan store cannot be read or written; nothing is
                then answered.
        """
        ...

    # --- the owner's placement acts (ADR-0217 §7) -------------------------

    async def guard(self, record_id: Identifier) -> Placement | None:
        """Keep the record ``record_id`` names for the owner alone.

        The owner's explicit act **after the fact**, on a record already in the
        store. It writes reach ``OWNER`` with setter ``OWNER_ACT`` and the instant
        of the act — but **only where ADR-0217 §3's precedence lets it win, and only
        where what it would write differs from what the record carries**. So a
        ``guard`` on a placement whose setter is ``PROPOSED``, or on the default
        placement, *does* write: it changes the setter from one the owner may lift
        to one §3 calls final, which is a difference §3 acts on. A ``guard`` on a
        placement whose setter is ``DERIVED`` changes nothing and is **not an
        error** — ADR-0204 §5's narrowing already stands, and §3's total order puts
        ``DERIVED`` above ``OWNER_ACT`` at the same reach — and a second ``guard``
        on an already-guarded record writes nothing, so the instant does not move.

        **Idempotent in the strict sense**: calling it twice returns exactly what
        the first call returned, the instant included.

        **The act is a read-modify-write made conditional on the record being
        unchanged since it read it** (ADR-0219 §2, ADR-0046 §5). A derivation
        landing between the read and the write would otherwise be overwritten, and
        what that loses is a *narrowing* rather than a content merge. On a conflict
        the act re-reads and re-decides against the value the record now carries;
        the retry is bounded at **two attempts in all**, and a second conflict
        writes nothing and raises ``MemoryStoreError``, which this method already
        declares. Nothing here loops unboundedly, and the bound is safe because the
        act is idempotent: a caller that meant it repeats it.

        **The read discipline stands beside that gate rather than being replaced by
        it**: the act decides over the record as read in the call that writes it,
        never over one read earlier for a rendered list or a confirmation prompt.
        :meth:`forget` carries the same ruling for its own window over the same
        store, and ADR-0197 §7's confirmation is not a writer's lock.

        **No placement reaches a floor** (ADR-0199 §3, ADR-0217 §3): guarding
        changes nothing about a Tier 0 value, which is withheld from every channel
        whatever any placement says.

        Args:
            record_id: The record's id, taken as opaque.

        Returns:
            The record's placement **as it stands after the act** — which is the
            placement it already carried where the act wrote nothing — or ``None``
            where ``record_id`` named nothing live. ``None`` is not an error, on
            :meth:`forget`'s own reading of the same case: the user's intent is
            already satisfied.

        Raises:
            ValueError: If ``record_id`` is blank.
            MemoryStoreError: If reading or writing memory failed, including where
                the bounded retry above was exhausted.
        """
        ...

    async def unguard(self, record_id: Identifier) -> Placement | None:
        """Let the record ``record_id`` names be spoken to anyone again.

        :meth:`guard`'s counterpart, and the *widening* direction of the owner's
        act. It writes reach ``ANYONE`` with setter ``OWNER_ACT`` and the instant of
        the act, on the same two conditions: §3's precedence must let it win, and
        what it would write must differ from what the record carries in reach or in
        setter.

        **Where the placement's setter is ``DERIVED`` it writes nothing**, and the
        refusal **raises nothing**: it returns that placement unchanged — reach
        ``OWNER``, setter ``DERIVED`` — and a surface reads the returned reach and
        setter to say why nothing moved. ADR-0204 §5's closing prohibition is not
        lifted by an act, and a raise was rejected for two reasons: it would make an
        act this system declines on ratified grounds indistinguishable from an
        operation that *failed*, and it would make an idempotent act a failure
        too. The two routes that remain open for such a record are a supersession
        and a class ruling under ADR-0199 §6; neither is this method's.

        **Widening a record whose ``about_person`` is stated changes nothing about
        what an unbounded channel carries** (ADR-0199 §3's second clause, ADR-0217
        §3): the act is accepted and the record stays withheld there on the subject
        axis, which no placement reaches.

        The conditional write, its bounded two-attempt retry and the read discipline
        are :meth:`guard`'s, unchanged — and on this method they are what make a
        **stale** ``unguard`` unable to clear a ``DERIVED`` placement in place,
        which is the laundering ADR-0217 §7 gates these acts to prevent.

        Args:
            record_id: The record's id, taken as opaque.

        Returns:
            The record's placement as it stands after the act, or ``None`` where
            ``record_id`` named nothing live.

        Raises:
            ValueError: If ``record_id`` is blank.
            MemoryStoreError: If reading or writing memory failed, including where
                the bounded retry above was exhausted.
        """
        ...

    # --- the notification surface (ADR-0130 §7, §9) -----------------------
    # Contract surface, because `AssistantEngine` is a Protocol in this file
    # (§9). Five methods and no more: **reconsideration is deliberately absent**
    # — it is part of the maintenance surface ADR-0083 §8 places "on a class in
    # `orchestration`, not `core` contract surface", no client asks for it, and
    # no interface adapter may drive it.

    async def notifications(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[HeldNotification, ...]:
        """List the notifications the assistant is holding for the user (§7).

        **Held notifications are reachable only through this explicit
        enumeration.** No notification, and no count of notifications, is
        injected into a turn's result, into :meth:`converse`, or into any
        response to a request that did not ask for it — ADR-0078 §8's third reach
        applied unchanged, because a turn's content may not depend on queue
        depth. Its count-on-every-turn variant stays declined and its "revisit
        when the hub can push" trigger unfired, the hub still being unable to
        push (ADR-0094 §2, ADR-0084 §3).

        **Every retained record, oldest first**, including one whose moment has
        passed: expiry ends interruptibility and actionability but deletes
        nothing, so an expired record is still enumerated and renders as expired
        (§7).

        Args:
            limit: How many to return; defaults to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`.
            offset: How many to skip.

        Returns:
            The page, oldest first.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
            NotificationStoreError: If reading the store failed.
        """
        ...

    async def dismiss_notification(self, notification_id: Identifier) -> bool:
        """Dispose of one notification, without destroying it (§7, §9).

        The first of the two acts §6 says a surface rendering an interruption
        should offer in one step; lowering that class's reach through
        :meth:`set_notification_preferences` is the other.

        **A dismissal is not a deletion.** The record stays readable and stays in
        the user's export; what ends is its actionability, which frees a slot
        under the cap at once. It does **not** free the notification's key: where
        the candidate declared an expiry, the record goes on suppressing the same
        fact until that instant, so dismissing does not invite that fact back on
        the next tick. Where the candidate declared **no** expiry there is no
        horizon to supply and suppression ends exactly where actionability does
        (ADR-0215 §1; §7 and §8 as ADR-0215 §§1-2 replace them). A fact that
        recurs after its notification *expired* is a new candidate, as before.

        Args:
            notification_id: The notification to dismiss.

        Returns:
            Whether an actionable notification was dismissed. ``False`` where the
            id named nothing, or named one already dismissed, expired or dropped.

        Raises:
            ValueError: If ``notification_id`` is blank.
            NotificationStoreError: If reading or updating the store failed.
            NotificationOutboxError: If the notification's delivery outbox entry
                could not be given up. **Nothing is reported as dismissed then**,
                and the entry is left in a state no poll can select, so a retry is
                safe and the seam's own reconciliation finishes what this call could
                not (ADR-0131 §3, §3b). Declared because ADR-0131 §3a makes a
                disposal reach the outbox — "the disposing act calls the seam rather
                than the seam polling for it" — and ADR-0085 §9 requires a method's
                failures to be declared rather than raised unnamed.
        """
        ...

    async def forget_notification(self, notification_id: Identifier) -> bool:
        """Destroy one notification, so its subject can be proposed again (§9).

        ADR-0004 §6's delete right, in the shape :meth:`forget` takes.
        Beside :meth:`dismiss_notification` deliberately: a dismissal ends
        actionability and leaves the record readable, so this is the surface the
        delete right reaches and that one is not.

        Args:
            notification_id: The notification to destroy.

        Returns:
            Whether a notification was destroyed. ``False`` where the id named
            nothing.

        Raises:
            ValueError: If ``notification_id`` is blank.
            NotificationStoreError: If reading or updating the store failed.
            NotificationOutboxError: If the notification's delivery outbox entry
                could not be withdrawn. **Nothing is destroyed then**, which is
                ADR-0131 §3a's ordering holding rather than failing: "No lane may
                delete a record whose entry it has not already withdrawn."
        """
        ...

    async def notification_preferences(self) -> NotificationPreferences:
        """Read the three standing settings that tune proactive contact (§6).

        **An empty store is a working policy**: reach ``hold`` for every class
        including one no preference names, no quiet windows, and three
        interruptions per rolling twenty-four hours. So this is answerable on the
        first day, from an empty store, with no history — which is what makes the
        tuning surface reachable before there is any usage to learn from.

        Returns:
            The settings in force, defaulted where the user has set nothing.

        Raises:
            NotificationStoreError: If reading the store failed.
        """
        ...

    async def set_notification_preferences(
        self, preferences: NotificationPreferences
    ) -> NotificationPreferences:
        """Write the three standing settings, and re-arm what the change reaches (§6).

        **Which is exactly why a setting change re-rules what is already held.**
        Reach is not a condition time resolves, so a record held because its
        class was at ``hold`` carries no ``reconsider_at`` from its ruling and
        would otherwise sit there until it expired — the user raises the class,
        agrees to be interrupted, and is not. The write stamps its own instant
        onto the records it actually reaches, and the reconsideration job picks
        them up on its next run.

        **Lowering a class to ``off`` reaches every actionable held record of
        that class**, whatever it was held for, so "never tell me this" reaches
        what is already held and not only what comes next. **No setting change
        reaches a record already ruled ``INTERRUPT``**: whether contact already
        handed to a channel can be recalled is the delivery seam's question.

        **The whole value is written, and the last write wins.** A caller
        changing one setting reads, adjusts and writes back; two writers racing
        each other lose the earlier one's edit, this surface carrying no version
        token and detecting no conflict. See :meth:`NotificationStore.set_preferences`
        for why that is stated rather than designed around.

        Args:
            preferences: The settings to hold from now on, **replacing** what is
                held rather than merging into it.

        Returns:
            The settings now in force, as the store holds them.

        Raises:
            ValueError: If two rows name the same notification class, or a quiet
                window carries a timezone or has no readable extent.
            NotificationStoreError: If writing the store failed.
        """
        ...

    # --- the delivery surface (ADR-0131 §1, §4) ---------------------------

    async def next_notification(
        self,
        *,
        acknowledging: Identifier | None = None,
        plays: tuple[SpokenAudioFormat, ...] = (),
        budget: timedelta,
    ) -> NotificationDelivery | None:
        """Wait up to ``budget`` for a notification, and acknowledge the last one.

        **The one method by which a notification crosses the wire** (ADR-0131 §1).
        A disposed notification reaches a device only as the result payload of a
        request that device sent: the device asks "have you anything for me, and I
        will wait up to this long", and the hub answers with a notification the
        moment it has one, or with nothing when the device's patience runs out.
        That is a long poll, and it is the shape that costs no ratified clause —
        ADR-0094 §2's direction rule is satisfied because the device establishes
        the connection, ADR-0084 §3's serial rule because a poll is one request
        frame and one result frame, and ADR-0124 §1's accountability bullet
        because there is still no path by which the hub transmits something nobody
        asked for.

        **A poll owns its connection for that connection's whole life** (§2). Over
        the wire, a client that has a poll outstanding sends no other request on
        that connection, and one wanting an ordinary session while polling opens a
        second. That is not a nicety: ADR-0084 §3 makes a second request while one
        is outstanding a protocol violation that closes the connection, so a
        shared connection does not degrade under load — it is simply broken, on
        the first turn the owner takes while a poll is in flight. The hub enforces
        it in both directions, by closing, and the rule is the **transport's**
        rather than this method's: it turns on a connection identity this
        signature deliberately does not have, which is why it is not a declared
        failure here. An in-process engine has no connections and could never
        raise such an error, and the same declared contract meaning two different
        things on the two sides of the wire is exactly what ADR-0084 §5 promoted
        this façade to a Protocol to prevent.

        **No argument carries a device identity and no lane may add one** (§4).
        Where ADR-0131's rules are per-device the identity is the one ADR-0124 §4
        established at admission, held per connection by the hub's listener, and
        never read from a payload — which ADR-0124 §4 forbids in terms. The rules
        that live *here* need no identity: "an entry is offered to one device at a
        time" is delivered by the **lease**, and the acknowledgement is honoured
        because ``delivery_id`` is a capability that went to exactly one device.

        **Selecting an entry, minting its ``delivery_id`` and starting its lease
        are one indivisible step** (§2a), and nothing about the lease depends on
        the transport. There is no state in which an entry is chosen for a poll
        and not yet leased. A caller that goes away after that step leaves the
        lease standing, and the entry returns to the outbox when it expires —
        which is §3's at-least-once case reached one step earlier.

        **A staged delivery cannot be recalled** (§3a). Once this has returned a
        delivery, those bytes may reach the device whatever happens afterwards —
        expiry, deletion, withdrawal, dismissal or eviction — and no lane may add
        an operation that unsends one. What a departure guarantees is that no
        *later* poll selects the entry.

        **A caller that can play audio asks for a rendering here, and the rendering
        is produced inside the call that answers the poll** (ADR-0206 §1). ``plays``
        is the whole of what that ADR adds to these arguments: an empty one asks for
        nothing, and none is produced — no placement is decided, no synthesizer is
        called, and nothing about the poll's behaviour differs from what §4 already
        fixes. A caller that cannot play audio omits it and is unaffected by every
        other clause of ADR-0206.

        **A rendering is produced after the entry has been selected, and never
        before.** No entry is rendered in advance of a poll that asked for one, no
        rendering is retained between polls, and a redelivery of the same entry
        renders afresh. No rendering is written to the outbox, to any store, index,
        trail, trace, audit trail or log, in either tier: ADR-0200 §8's first clause
        binds this path in the terms it is already written in, and ADR-0206 adds no
        exception to it.

        **Exactly one triple is placed as speakable** (ADR-0206 §3), on a channel
        whose audience is unbounded — a rendering is played out of a device into a
        room. It is a candidate whose ``producer`` is ``"calendar-upcoming"``, whose
        ``notification_class`` is ``"upcoming_event"`` and whose ``sensitivity`` is
        :attr:`~ai_assistant.core.types.DataTier.PERSONAL`. **Every other triple is
        withheld** — the same producer and class at any other sensitivity, every
        class of a producer that ADR is silent about, and every producer that does
        not exist yet — and no implementation reads the placement as reaching a
        tier, a class or a producer it did not name. The decision is made from those
        three recorded fields and from **nothing else**: not from ``summary``,
        ``detail``, ``references`` or ``confidence``, not by keyword,
        pattern or classifier, and not by asking a model (ADR-0199 §2).

        **A withheld notification arrives unspoken and nothing audible marks it**
        (ADR-0206 §5). No synthesizer is called, nothing is spent, the delivery
        carries no audio, and no chime, tone or spoken notice substitutes for it.
        The delivery is still returned by this poll and is still acknowledged
        normally: one poll serves both of that device's channels, so the rendered
        surface — a channel of bounded audience — gets it at once rather than
        waiting for a second request.

        **What is spoken is ``summary``, byte for byte** (ADR-0206 §4). No prefix,
        no announcement, no salutation, no punctuation added or removed, no case
        folding, no trimming and no second value composed from it; ``detail`` is
        **not** spoken on any candidate under any placement. No model is called on
        this path and no stage composes anything.

        **Speaking never fails the poll** (ADR-0206 §6). A ``SpeechError`` out of
        ``synthesize`` — and nothing else — degrades; every other exception
        propagates unchanged, and a delivered cancellation is neither a withholding
        nor a degradation. ``spoken`` is not ``None`` **exactly when**
        ``spoken_rendering`` is
        :attr:`~ai_assistant.core.types.SpokenRendering.RENDERED`, and the delivery
        travels in every degradation.

        **``budget`` bounds the waiting and nothing else, and the rendering is the
        request's own work** (ADR-0206 §7, ADR-0135 §3). It is performed whatever the
        state of the budget, runs to completion, and is never declined, shortened or
        degraded because the budget has elapsed — so a poll that renders answers
        later than ``budget`` by construction. Its bound is the deadline decorator
        the composition root wires over the synthesizer and nothing else.

        Args:
            acknowledging: The ``delivery_id`` this caller is confirming, or
                ``None``. It retires the entry **only** where it is that entry's
                current outstanding delivery; anything else — an unknown
                identifier, a retired entry, or a delivery the entry has since
                superseded — is accepted and does nothing. That idempotent no-op
                is what lets a client reconnect after any failure and acknowledge
                blindly rather than reason about what the hub remembers.
            plays: The formats this caller can render, in preference order
                (ADR-0206 §1). Empty — the default — asks for no rendering. Where
                it is non-empty and ADR-0206 §3 places the candidate, the format
                rendered is the **first** member this hub's synthesizer's
                ``formats`` also names (ADR-0200 §3), and an empty intersection
                degrades rather than substituting a format the caller did not name.
                It says what the caller can render and never who can hear: omitting
                it declines to open a channel of unbounded audience rather than
                declaring a bounded one, and no implementation reads a ``plays``, a
                transport, a session or a device as making that channel bounded
                (ADR-0199 §8).
            budget: How long the hub may hold this request before answering with
                nothing. Honoured over the closed range from zero to
                ``hub_max_notification_budget``; **zero is an immediate poll**,
                answered at once with whatever is available, which may be nothing —
                and which, under ADR-0135 §3, still does the request's own work, so
                a zero budget renders exactly as any other does.

        Returns:
            The notification to show and the token that retires it, or ``None``
            where the budget elapsed with nothing available. Where ``plays`` asked
            for a rendering, ``spoken`` carries it and ``spoken_rendering`` says why
            it is there or is not (ADR-0206 §6).

        Raises:
            ValueError: If ``acknowledging`` is blank, or ``plays`` names something
                that is not a :class:`~ai_assistant.core.types.SpokenAudioFormat`.
                A malformed argument is refused before any outbox state changes,
                exactly as an out-of-range ``budget`` is, and no rendering is
                attempted on a request whose arguments were refused (ADR-0206 §7).
            NotificationBudgetError: If ``budget`` is negative or above
                ``hub_max_notification_budget``. The request then has **no effect
                on the outbox**: arguments are validated before the
                acknowledgement is applied, before any entry is selected and
                before any other outbox state changes, so a refused request
                retires nothing, leases nothing and mints nothing (§4). Without
                that ordering a device sending a valid ``acknowledging`` with an
                invalid ``budget`` could have its notification permanently retired
                by a call that reported failure.
            NotificationOutboxError: If applying ``acknowledging`` could not
                commit its dismissal, or the outbox cannot be read or written.
                Nothing is retired then and the same value may be sent again.
            OversizedValueError: If the result exceeds ADR-0085 §8's contract
                limit. Unreachable in a conforming deployment — §4's 256-byte
                delivery reserve is what makes it so — and declared because
                ADR-0085 §9 requires every method to declare it.
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
        """Read one conversation: its count and span, its current state and its devices.

        ADR-0073 §5's show-then-confirm at the unit the user thinks in: the count
        and the span, rather than a transcript nobody can read at a prompt
        (ADR-0074 §8). **It gains the conversation's current state** (ADR-0293
        §8, §11:3) — whether an activation started from it is running, which one,
        and how the last one ended — and its devices (§3:3), which a device that
        caught up from a snapshot has no change to learn from. Its transcript is
        :meth:`transcript`'s.

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
        """Forget the episodes on a conversation's place, and leave the conversation.

        **Memory-only** (ADR-0293 §2:4, §11:4): forgetting is a command on the
        assistant's memory, and it reaches the episodes on the conversation's place
        alone (§2:8). The conversation, its transcript and its devices stay as they
        were (§5:6) — removing those is :meth:`delete_conversation`, and no single
        operation both deletes and forgets (§2:7). It reaches those episodes
        **whether or not the conversation still stands** in the medium (§2:5), so
        a conversation deleted first can still be forgotten by its id, and it
        forgets an episode still open on the place as :meth:`forget` forgets an
        open episode, so no later write re-creates it (§2:6, ADR-0286 §8).

        Args:
            conversation_id: The conversation whose episodes to forget.

        Returns:
            Whether an episode was forgotten. ``False`` where the place held none.

        Raises:
            ValueError: If ``conversation_id`` is blank.
            MemoryStoreError: If an episode could not be read or forgotten.
        """
        ...

    # --- the chat space: acts in the medium and its reads (ADR-0293 §11) ---
    #
    # ADR-0293 §11:2's replacement for the conversation's turn calls, beside them
    # until the first build retires those (§Decision:2). Each act is the user's in
    # the hosted medium (§2); a written message is recorded and answered *received*
    # (§4:4), and what the assistant does with it is the chat's reader's (§6).
    # Device identifiers are opaque here: which devices may act is the device
    # session's (ADR-0293 §2, ADR-0296).

    async def start_conversation(self) -> ConversationSummary:
        """Start an empty conversation, shown on "my devices" (ADR-0293 §2:1, §3:1).

        An act in the medium: the conversation is created empty, given "my devices"
        as they stand, and the change is recorded. It is the one route that creates
        a conversation without a message (§2:2).

        Returns:
            The new conversation, with no turn recorded.

        Raises:
            ConversationStoreError: If the conversation could not be started.
        """
        ...

    async def my_devices(self) -> tuple[ChatDevice, ...]:
        """Read "my devices", the chat space's own set, ``device_id`` ascending (§3:1).

        Raises:
            ConversationStoreError: If the set could not be read.
        """
        ...

    async def set_my_devices(self, devices: Sequence[ChatDevice]) -> bool:
        """Replace "my devices" (ADR-0293 §3:1, §3:2).

        An act in the medium, and the user's statement that each device's screen is
        private. A conversation started later is shown on the set as it then
        stands; one already started keeps its own devices (§3:3).

        Args:
            devices: The whole set, each device once, at most
                :data:`~ai_assistant.core.types.CHAT_DEVICES_MAX`. Read once, before
                the first ``await``.

        Returns:
            Whether the set changed.

        Raises:
            ValueError: If ``devices`` is a ``str``, holds something that is not a
                ``ChatDevice``, names one device twice or holds too many.
            ConversationStoreError: If the set could not be written.
        """
        ...

    async def set_conversation_devices(
        self, conversation_id: Identifier, *, devices: Sequence[ChatDevice]
    ) -> bool:
        """Choose one conversation's devices, away from "my devices" (ADR-0293 §3:3).

        An act in the medium; "my devices" is not touched.

        Args:
            conversation_id: The conversation.
            devices: Its whole set of devices, as :meth:`set_my_devices` takes one.

        Returns:
            Whether the set changed.

        Raises:
            ValueError: If ``conversation_id`` is blank, or ``devices`` as
                :meth:`set_my_devices` refuses it.
            UnknownConversationError: If the id names no conversation, or one deleted.
            ConversationStoreError: If the set could not be written.
        """
        ...

    async def write_message(
        self, conversation_id: Identifier, *, message: UserMessage
    ) -> MessageReceipt:
        """Write the user's message into a conversation, and answer *received* (§4).

        An act in the medium from one of the conversation's devices. Once the
        conversation has recorded the message, the answer carries its position,
        which is *received* (§4:4). Sending is safe to repeat: the same device's
        same message id is the same message, recorded once, deleted or not (§4:2,
        §4:3). A device that is not one of the conversation's ends for writing, or a
        reply naming a position the conversation never held, is answered with an
        outcome and no position, and nothing is recorded (§7:2, §4:5).

        The message is recorded and answered; it starts no activation here. Taking
        it in is the chat's reader's (§6).

        Args:
            conversation_id: The conversation written into.
            message: The message. Its size bound is its type's, so an oversized one
                cannot be sent (§4:7).

        Returns:
            The receipt: the outcome, and the position where the message is.

        Raises:
            ValueError: If ``conversation_id`` is blank.
            UnknownConversationError: If the id names no conversation, or one
                deleted — a conversation is never created by a message (§2:2).
            ConversationStoreError: If the message could not be written.
        """
        ...

    async def composing(self, conversation_id: Identifier) -> None:
        """Say that the person is typing into a conversation's composer (ADR-0332 §5).

        An act in the medium that writes nothing into it (§5:9): the signal goes to the
        chat's reader and is answered with nothing. It is live for
        ``Settings.chat_composing_lapse`` after it arrives (§5:6), and only extends a
        start wait already running for the conversation: it starts no read and no wait,
        and does nothing where no wait is running (§5:7). It is not input. It starts no
        activation, joins nothing and holds no act, and it is never written into the
        transcript, any store or any episode (§5:8). So a signal for a conversation with
        no wait, or for one the hub no longer holds, has no effect.

        The requesting device must be the conversation's end for writing: ADR-0298
        §5:1's Writing row, where §5:11 places the method.

        Args:
            conversation_id: The conversation being typed into.

        Raises:
            ValueError: If ``conversation_id`` is blank.
            DeviceRefusedError: If the requesting device is not one of the conversation's
                ends for writing.
            ConversationStoreError: If the conversation's devices could not be read to
                check that.
        """
        ...

    async def delete_message(self, conversation_id: Identifier, *, position: int) -> bool:
        """Delete one message of either author, leaving its marker (§5:8, §5:9, §5:12).

        A reply to it stays, naming a deleted message. Deleting forgets nothing.

        Args:
            conversation_id: The conversation holding the message.
            position: The message's position, at least 1.

        Returns:
            ``True`` where this call deleted it; ``False`` where the conversation
            never held that position or it was already deleted.

        Raises:
            ValueError: If ``conversation_id`` is blank, or ``position`` is not an
                ``int`` in ``[1, 2**63)``.
            UnknownConversationError: If the id names no conversation, or one deleted.
            ConversationStoreError: If the message could not be deleted.
        """
        ...

    async def delete_conversation(self, conversation_id: Identifier) -> bool:
        """Delete a conversation and its transcript, forgetting nothing (§2:3).

        An act in the medium. The conversation leaves every read and the change is
        recorded; the episodes on its place stay, and forgetting them is
        :meth:`forget_conversation`'s (§2:4, §2:7).

        Args:
            conversation_id: The conversation to delete.

        Returns:
            ``True`` where this call deleted it; ``False`` where it was already
            deleted or the id names nothing.

        Raises:
            ValueError: If ``conversation_id`` is blank.
            ConversationStoreError: If the deletion could not be written.
        """
        ...

    async def transcript(
        self,
        conversation_id: Identifier,
        *,
        before: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> TranscriptPage | None:
        """Read a conversation's recent messages, or older ones (ADR-0293 §5:13).

        ``before=None`` is the snapshot a device far behind, or new, takes;
        ``before=<position>`` loads the messages before it as the user scrolls back.
        A deleted message reads as its marker. The page's ``as_of`` is where the
        device follows :meth:`chat_changes` from.

        **A page that does not fit the payload limit is shortened, not refused**:
        the oldest entries are left off, and the page's first position is where the
        next ``before`` reads from, so nothing is lost.

        Args:
            conversation_id: The conversation.
            before: ``None`` for the most recent messages, or a position to read
                below.
            limit: How many entries at most; defaults to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`.

        Returns:
            The page, or ``None`` where the id names no conversation, or one deleted.

        Raises:
            ValueError: If ``conversation_id`` is blank, ``before`` is not ``None``
                or an ``int`` in ``[1, 2**63)``, or ``limit`` is outside
                ``[0, 2**63)``.
            ConversationStoreError: If the transcript could not be read.
        """
        ...

    async def chat_changes(
        self,
        *,
        after: int,
        conversation_ids: Sequence[Identifier] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ChatChanges:
        """Read every change to the chat space after a cursor (ADR-0293 §5:10, §5:11).

        A device keeps one cursor and catches up with one request for every change
        after it, and asks again from ``next_after``. A plain request, answered at
        once; following the stream as it happens is the device session's
        (ADR-0296).

        **A page that does not fit the payload limit is shortened, not refused**:
        the newest changes are left off, and ``next_after`` is the last change
        returned, so the next read resumes after it.

        Args:
            after: The last sequence number the device applied, ``0`` for none.
            conversation_ids: The conversations to read the changes of, with the
                changes to "my devices" beside them, or ``None`` for every change.
                At most 1000 ids; read once, before the first ``await``.
            limit: How many changes at most; defaults to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`.

        Returns:
            The changes, in sequence order, and the cursor to ask from next.

        Raises:
            ValueError: If ``after`` or ``limit`` is outside ``[0, 2**63)``, or
                ``conversation_ids`` is a ``str``, holds a blank id or more than 1000.
            ConversationStoreError: If the changes could not be read.
        """
        ...

    def follow_chat(self, *, after: int) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        """Follow the chat space's change stream from a cursor (ADR-0296 §4, ADR-0298 §7).

        The change stream as one streaming method (ADR-0296 §4:1): every change after
        ``after`` that the requesting device may see, in sequence order, and then each
        change as it happens, with the answer kept open. Each chunk is a
        :class:`~ai_assistant.core.types.ChatStreamChunk` holding exactly one of a
        change, a conversation's current state, the device's roles or a heartbeat; only
        a change carries a sequence number, and a device's cursor is the last one it
        applied (§4:4, §4:6).

        **What the device sees** is ``ConversationStore.device_changes``' as-of
        membership — a change in a conversation where the device was an end for
        reading when the change was recorded, and a change to a set the device is in
        before or after — kept, for a conversation the device does not read when the
        stream sends to it, to the change that removed it and the conversation's
        deletion (ADR-0298 §7:5). The change that makes the device an end for reading
        arrives in one chunk with the conversation's snapshot as of that change,
        shortened from its oldest end to fit the payload limit (§7:6-§7:8). A
        conversation's current state is pushed when it changes, for the conversations
        the device reads (ADR-0296 §4:9). The hub's own machine sees every change and
        every conversation, and no snapshot, since it is an end of every one.

        **The stream holds no lease and is ended only by revocation, the dead-peer
        timeout or its device** (ADR-0298 §7:15): the device closes the iterator to
        stop. The one :class:`~ai_assistant.core.types.ChatStreamEnd` is written when
        the engine is shutting down, carrying the cursor to reopen from. The roles and
        the heartbeat are the hub's session layer's to write (§7:10), so an engine
        followed in-process yields neither.

        **The local refusals are raised from the call, not from the iteration**, as
        :meth:`chat_changes` raises them. The role check of ADR-0298 §5's "Reading
        many" row is the stream's first step, so a device holding no role is refused
        with :class:`~ai_assistant.core.errors.DeviceRefusedError` from the first
        iteration, before any chunk.

        Args:
            after: The last sequence number the device applied, ``0`` for none.

        Returns:
            An async iterator over the stream's chunks, ending only with the engine.
            Close it to stop following (:func:`contextlib.aclosing`).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``after`` is outside ``[0, 2**63)``.
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

        **A new grant names** ``NOTIFY`` **alone** (ADR-0294 §4, ADR-0318 §6:2). A
        ``scope`` naming
        :attr:`~ai_assistant.core.types.GrantScope.INGEST` is refused with
        ``ValueError``, locally and before any I/O, exactly as an empty one is, and
        nothing is recorded: nothing reads a source under that use any more, so a
        grant naming it would promise remembering nothing performs. ``GrantScope``
        keeps the member, so a recorded grant naming it stays readable, exportable
        and revocable — the refusal is of the *new* grant and of nothing else.

        Args:
            source: The reader's declared identity, compared exactly.
            scope: The uses this grant authorises. Non-empty, without duplicates and
                without ``INGEST``; order is normalised to declaration order by the
                record's own validator (ADR-0097 §2, §10; ADR-0294 §4).

        Returns:
            The recorded grant, as it was appended.

        Raises:
            ValueError: If ``source`` is blank or has no UTF-8 encoding, or if
                ``scope`` is empty, names a use twice, or names ``INGEST``. A caller
                programming error rather than a condition of the system, refused
                **locally and before any I/O**, so both implementations refuse the
                same values without a round trip (ADR-0085 §9, ADR-0294 §4).
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
        implementation checking only ``NOTIFY`` would leave an ``INGEST``-only grant
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

    async def standing_grants(self) -> tuple[SourceGrant, ...]:
        """List every grant the user currently authorises (ADR-0139 §2).

        **The surface answers two questions and keeps them apart** (ADR-0139 §1).
        *What may I grant?* is :meth:`grantable_sources`, answered from the
        readers this engine holds. *What do I currently authorise?* is this,
        answered from the grant store. **Neither answer is derivable from the
        other and no surface may present one as the other**: the two may
        legitimately disagree — a source may be grantable and ungranted, granted
        and not currently held, or both — and no implementation may reconcile
        them, suppress an entry of one because it is absent from the other, or
        refuse an answer because they differ.

        Without it there is a state in which a user holds a live grant and no
        operation reports it: ``grantable_sources`` is keyed on the composition
        root, so an operator who unsets a reader's configured path makes the grant
        on it invisible while leaving it live and read-authorising. It stays
        revocable — :meth:`revoke` applies no admission check, deliberately
        (ADR-0102 §4) — and this is what tells the user its name.

        **One read of the store, so the answer is a snapshot.** No source appears
        twice, none is missing because another was being written, and the set is
        internally consistent. It is the grants live *at the moment the response
        was computed*, which is :attr:`GrantableSource.live`'s own bound: it is
        not a claim that stays true afterwards, and no client may present it as
        one.

        **Complete or refused, never truncated.** It takes no argument, is not
        paged, and admits no ``limit`` and no ``offset``. Where the result does not
        fit the contract limit it raises
        :class:`~ai_assistant.core.errors.OversizedValueError` and reports
        nothing — a refusal a client renders as one, whose remedy is
        ``hub_max_frame_bytes`` exactly as for :meth:`grantable_sources` — because
        a page of what you authorise reads as complete while omitting an
        authorisation. Withdrawal survives a frame too small to list: ``revoke``'s
        request and result are two small values (ADR-0102 §10).

        **Liveness is the store's ``revokes`` relation alone** (ADR-0097 §4). No
        implementation may derive it from ``decided_at``, from
        :meth:`recent_grants`' ordering, or from which readers this engine holds.
        A ``GrantError`` from a store holding two live grants for one source is
        propagated rather than converted.

        **What a client presents, and what it may never present** (ADR-0139 §3).
        A surface presenting this set presents it whole: it may not omit a record
        because no held reader declares its source, may not merge the set into an
        enumeration of grantable sources, and may not present a standing grant as
        a source the user may grant. It renders exactly the uses each grant names,
        adding none and omitting none, and never as a partial scope in need of the
        members it leaves out — while a surface *offering* a choice among uses
        carries every member of
        :class:`~ai_assistant.core.types.GrantScope`, named in words. No surface
        presents a source's configuration state as part of a grant, and none
        presents a grant as a statement about whether a source is being read: what
        a grant says is what the user authorised, and whether a read happened is
        not a question this surface answers.

        **Amending a grant stays two acts and no method here performs both**
        (ADR-0139 §4). A client composes :meth:`revoke` then :meth:`grant`, in
        that order, which is what puts the intermediate state where a surface can
        report it. Such a surface reports each act as one of exactly three
        outcomes — it landed, it is known not to have landed, or its outcome is
        **not known** — and never infers the *source's* state from an act's
        outcome; this method is what states that instead.

        Returns:
            Every grant live when the response was computed, whatever this engine
            holds. **The order carries no meaning**: no client may read a
            precedence, a recency claim or a liveness claim off a record's
            position, and an implementation's chosen order is a display convention
            rather than a contract clause. Empty means nothing is authorised,
            which is not an error.

        Raises:
            GrantError: If the grant store could not be read, or holds two live
                grants for one source.
        """
        ...

    # --- the connection surface (ADR-0151 §1) --------------------------------
    #
    # Six operations. ADR-0151 §1 derived five rather than preferring them:
    # ADR-0149 §9 names connecting, re-provisioning, disconnecting and listing,
    # and ADR-0139 §1 splits the last into *what is connected now* and *what was
    # done*, which are answered from different halves of the store and neither of
    # which derives the other. ADR-0325 §5:1 adds the sixth,
    # :meth:`connect_keyless_account`, for a source that needs no credential.
    # **No other operation on any surface performs, or reports the outcome of, a
    # provisioning act or a disconnection.**
    #
    # **None of them is reachable by a model or a plan** (ADR-0151 §13). No
    # ``ToolDefinition`` binds one, no plan step reaches one, no model-authored
    # value becomes an argument to one, and no scheduler job invokes one — a
    # connection is created, re-provisioned and disconnected only by an explicit
    # user act through a client. Two limbs of that are already mechanical: `tools`
    # is a subsystem, subsystems never import `orchestration` and never import one
    # another. It is written anyway because what it would invert is ADR-0005 §3.
    #
    # **No ruling and no trail** (ADR-0151 §12, ADR-0149 §7). No ``ActionPolicy``
    # ruling is sought for any of these, no ``PermissionDecision`` is synthesised
    # for one, and no ``AuditTrail`` record is written for one; a connection is not
    # an authorisation and no surface presents one as permission to act.
    # :meth:`recent_connection_acts` is what discharges the record half of
    # ADR-0004 §7 for a provisioning act.
    #
    # **No lane exposes these over any transport but ADR-0084 §1's loopback
    # socket** — in particular not over ADR-0124's remote listener — before a
    # ratified decision rules the credential's hop from an enrolled device
    # (ADR-0151 §13). It is a precondition on that lane rather than a check here,
    # because a method cannot see its transport (ADR-0098 §5).

    async def connect_account(
        self, *, identity: NonBlankEncodableText, credential: SecretValue
    ) -> ConnectedAccount:
        """Connect a fresh account under a reference the hub mints (ADR-0151 §2).

        **It takes no reference argument and no implementation accepts one under
        another name or through another route** (ADR-0151 §2). The reference is
        minted by the provisioner as the reference's first record is written, from
        a source no fresh process resumes; no client, no ``Settings`` value, no
        configuration file and no model-authored value supplies, proposes,
        constrains or predicts one (§3). So this call cannot be aimed at an
        existing record at all, which is what makes "I meant to replace a
        credential and created a second connection instead" unreachable rather
        than merely visible — the mistake a user actually makes.

        **It is a separate operation from :meth:`reprovision_account` although
        ADR-0148 §6 gives both one act**, because the per-method failures differ
        and ADR-0085 §9 makes those part of the contract: this one cannot fail
        with an unknown reference and cannot lose a compare-and-swap, since its
        reference is minted and no other act can be holding it.

        **It returns only when ADR-0148 §6's third write has landed**, carrying
        ``state=ACTIVE``, the identity supplied in this call, and the reference's
        first revision. An implementation that returns after the first or second
        write, or returns a ``PENDING`` record, does not conform (ADR-0151 §7).

        **The identity is refused rather than normalised** (ADR-0151 §5). Nothing
        strips, case-folds, case-normalises or Unicode-normalises it, at the
        surface or below, and what is returned is byte-for-byte what was supplied.
        Every client that accepts an identity displays it to the user as part of
        the act — an obligation the hub cannot enforce and states anyway, because
        ADR-0149 §4's third answer to a credential pasted into the identity field
        is precisely that the value is *seen*.

        **The credential reaches this system by no other route** and comes to rest
        only in the keyring (ADR-0151 §6). It is named ``credential`` on both
        operations that take one so ``core/logging.py``'s key-name redaction covers
        it wherever a payload mapping is logged, and no implementation renames it,
        aliases it, or nests it under a key redaction does not reach.
        `orchestration` relays it and does nothing else with it: it does not
        unwrap it, log it, retain it beyond the call, copy it into any other value,
        retry a call with it, or read it back. No operation returns one or any
        value derived from one, and none is recorded in a trace, an ``AuditTrail``,
        a conversation or a plan.

        **A cancellation propagates unconverted** (ADR-0151 §7, ADR-0060). It is
        not a failure and no implementation converts one into any class below. A
        cancelled client reports the outcome as *not known*, states the
        reference's state as unread, and starts no new call in order to report.

        Args:
            identity: The user-recognisable name of the account, recorded verbatim.
            credential: The account's secret, still in its redacting holder.

        Returns:
            The live record this act wrote, ``ACTIVE`` at the reference's first
            revision, carrying the minted reference.

        Raises:
            ValueError: If ``credential`` is blank, unencodable or oversized
                (ADR-0125 §3) — refused with a message naming neither the value
                nor its length (ADR-0125 §6).
            UnusableIdentityError: If ``identity`` exceeds
                :data:`~ai_assistant.core.types.ACCOUNT_IDENTITY_MAX_BYTES` once
                UTF-8 encoded, carries a Unicode control character or a line break,
                or is **equal** to ``credential``'s plaintext. Raised **locally,
                before any I/O**, by every implementation — the wire client
                included — so no such call reaches the hub and no credential is
                sent for one (ADR-0151 §5). The comparison is exact string
                equality, made before the first of ADR-0148 §6's three writes, and
                the message names neither value, no part of either, and no length
                of either.
            IncompleteProvisioningError: If the act's first write returned and the
                act did not complete. It carries the minted reference, which the
                store then holds, and asserts nothing about the reference's live
                record at the moment it is caught (ADR-0151 §7).
            ProvisioningOutcomeUnknownError: If the activation **failed rather than
                returning**, so neither completion nor incompletion may be
                asserted. It carries the reference, which exists; the resolution is
                to read :meth:`connected_accounts`, never to re-run the act on the
                assumption it failed.
            ConnectionStoreError: If the act's own **first** write did not return.
                It carries **no** reference, because there may be none to carry,
                and the act's outcome is therefore not known.
            OversizedValueError: If the arguments do not fit the configured frame.
                Nothing is written; no implementation truncates a credential or an
                identity, splits the act across frames, or falls back to another
                route, and raising ``hub_max_frame_bytes`` is the operator's only
                remedy (ADR-0151 §11).
        """
        ...

    async def reprovision_account(
        self,
        reference: Identifier,
        *,
        identity: NonBlankEncodableText,
        credential: SecretValue,
    ) -> ConnectedAccount:
        """Replace the credential under a reference the hub returned (ADR-0151 §2).

        ADR-0148 §6's same three writes, aimed at an existing reference: the record
        first as *pending* at the incremented revision, the credential second, the
        record *active* third. The reference is **compared exactly** — no
        implementation matches one by prefix, by case-insensitive comparison or by
        any equivalence other than equality (ADR-0151 §3) — and it is one this hub
        previously returned, because §3's mint means a user has no name of their
        own to type. A client that offers connecting therefore must offer listing.

        **It refuses a reference the store does not hold**, which is what turns
        the typo that :meth:`connect_account` cannot make into a typed refusal
        rather than a silent second connection.

        **Its predecessor's slot is deleted once its own activation has landed**,
        and never before (ADR-0148 §6). A deletion that fails leaves an
        unreferenced credential rather than an incorrect one, and the failure is
        reported and never suppressed — see ``ResidualCredentialError`` below,
        which means the act **completed**.

        :meth:`connect_account`'s clauses on the identity, on the credential and
        on cancellation apply here word for word.

        Args:
            reference: The connection to re-provision, exactly as the hub returned
                it.
            identity: The account identity for the new revision, recorded
                verbatim. It may differ from the previous revision's.
            credential: The replacement secret, still in its redacting holder.

        Returns:
            The live record this act wrote, ``ACTIVE`` at the new revision.

        Raises:
            ValueError: If ``reference`` is blank or unwritable, or ``credential``
                is blank, unencodable or oversized. Refused locally.
            UnusableIdentityError: On :meth:`connect_account`'s terms.
            UnknownConnectionError: If the store holds no entry for ``reference``.
                Refused before the first write, so nothing is written.
            DisplacedProvisioningError: If another act took the record over, at any
                of ADR-0148 §6's three points. It means **no record this act wrote
                is the reference's live record** — and **not** that this act wrote
                nothing: the store may hold this act's own pending entry and the
                keyring a credential in this act's own slot, both named by the
                store, read by no call, and removed by a disconnection of that
                reference and by ADR-0149 §8's purge (ADR-0151 §7). No
                implementation performs a liveness pre-check to narrow the window,
                because a pre-check narrows without closing it while inviting a
                reader to believe it had.
            IncompleteProvisioningError: On :meth:`connect_account`'s terms,
                carrying this reference.
            ProvisioningOutcomeUnknownError: On :meth:`connect_account`'s terms.
            ResidualCredentialError: If the **predecessor-slot deletion** failed
                after the activation returned having landed. The act
                **completed** — the reference is connected at the new revision —
                and what remains is an unreferenced credential the store still
                names (ADR-0151 §7). No client reports it as a failed connection.
            ConnectionStoreError: On :meth:`connect_account`'s terms.
            OversizedValueError: On :meth:`connect_account`'s terms.
        """
        ...

    async def connect_keyless_account(self, *, identity: NonBlankEncodableText) -> ConnectedAccount:
        """Connect a source that needs no credential, under a reference the hub mints.

        **A keyless connection** (ADR-0325 §2): one live record carrying the
        identity the user names, the ``ACTIVE`` state and **no credential slot**,
        written in one act (§3:2). Its callable is built with no key and refuses a
        record that has one; a callable built with a key refuses a record that has
        none.

        **It takes no reference and no credential, and accepts neither under another
        name** (§5:1). The reference is minted as :meth:`connect_account`'s is
        (ADR-0151 §3). **It is a separate operation and not an optional credential**
        (§4): a user who forgot their key must not get a working-looking connection
        that every credentialed callable then refuses, so leaving the credential out
        is a choice made on purpose. No client performs it because a credential was
        not supplied, was blank or was refused, and none falls back to it from
        :meth:`connect_account` (§4:4).

        **The identity is the name the user gives their use of the source** — for
        example "Open-Meteo" — supplied in this act and recorded verbatim (§4:2). No
        component infers it from a reference, an endpoint, an origin, a ``Settings``
        value or a remote lookup, and no client fills it in from configuration.
        ADR-0151 §5's refusals bind it **locally and before any I/O, in every
        implementation**, the wire client included: an identity whose UTF-8
        encoding exceeds
        :data:`~ai_assistant.core.types.ACCOUNT_IDENTITY_MAX_BYTES`, or that carries
        a control character or a line break, is refused with
        :class:`~ai_assistant.core.errors.UnusableIdentityError` (§4:3). There is no
        credential to compare it against, and nothing replaces that comparison.
        Every client that accepts the identity displays it to the user as part of
        the act, and what is returned carries it byte for byte (§4:5).

        **Created only by an explicit user act through a client** (§4:1): no
        ``Settings`` value, configuration, upgrade, migration, first run, backup
        restore, scheduler job, plan step, tool, callable or model creates one or
        supplies its identity. It is on ADR-0151's connection surface and that
        surface's clauses bind it as they bind the other five (§5:5): no ruling, no
        trail, not reachable by a model or a plan, and served over ADR-0084 §1's
        loopback socket only.

        **It returns only when its one write has landed**, carrying
        ``state=ACTIVE``, the identity supplied in this call and revision 1 (§3:5).
        A keyless reference is otherwise ordinary: :meth:`disconnect_account` and
        :meth:`reprovision_account` act on it unchanged, and after a
        re-provisioning it names a slot (§3:7).

        **A cancellation propagates unconverted**, on :meth:`connect_account`'s
        terms.

        Args:
            identity: The name the user gives the connection, recorded verbatim.

        Returns:
            The live record this act wrote, ``ACTIVE`` at revision 1, carrying the
            minted reference.

        Raises:
            UnusableIdentityError: If ``identity`` exceeds
                :data:`~ai_assistant.core.types.ACCOUNT_IDENTITY_MAX_BYTES` once
                UTF-8 encoded, or carries a Unicode control character or a line
                break. Raised **locally, before any I/O**, by every implementation;
                the message names no part of the identity and no length of it.
            ConnectionStoreError: If the act's one write failed rather than
                returning. It carries **no** reference, the outcome is not known,
                and a client resolves it by reading :meth:`connected_accounts`
                (ADR-0325 §3:6), as it would :meth:`connect_account`'s.
            OversizedValueError: If the argument does not fit the configured frame.
                Nothing is written, and raising ``hub_max_frame_bytes`` is the
                operator's only remedy (ADR-0151 §11).
        """
        ...

    async def disconnect_account(self, reference: Identifier) -> ConnectedAccount | None:
        """Disconnect a reference and delete its credentials (ADR-0149 §5).

        **Two steps in a fixed order**: the removal entry is appended **first**,
        after which the reference has no live record; the credential slots are
        deleted **second**. Deleting the credential first would leave a window in
        which a live *active* record names a slot holding nothing.

        **Idempotent and re-runnable** (ADR-0149 §5). On a reference the store
        holds no entry for it writes nothing and deletes nothing, so a mistyped
        reference leaves no tombstone. It does not reset the reference's revision.

        **It is prospective, and no surface may say otherwise** (ADR-0151 §8). It
        does not stop a transmission already in flight, does not cancel a
        provisioning act, and is **not** a guarantee that the keyring holds nothing
        for that reference — ADR-0149 §5 states the weaker, true guarantee, that no
        live record names any slot for it.

        **Disconnecting every reference is not ADR-0149 §8's purge** and does not
        discharge ADR-0004 §6's delete right. No surface presents it as either, and
        no lane composes one out of the other (ADR-0151 §8).

        Args:
            reference: The connection to disconnect, compared exactly.

        Returns:
            The live record removed, as it stood immediately before the removal
            entry was appended — or ``None`` where the reference had no live record
            to remove, which covers both a reference the store has never held and
            one whose latest entry is already a removal. **A ``None`` is not a
            report of a disconnection**: no client presents it as one, as a
            confirmation that a credential was deleted, or as a statement that the
            reference does not exist. It says one thing — no live record was
            removed by this call (ADR-0151 §8).

        Raises:
            ValueError: If ``reference`` is blank or unwritable. Refused locally.
            ResidualCredentialError: If the removal entry **landed** and at least
                one credential deletion did not. The reference **is** disconnected,
                the residual credentials stay named by the store, and the remedy is
                to run this call again. A client reports the reference as
                disconnected **and** the deletion as incomplete, and never as a
                failed disconnection (ADR-0151 §8).
            ConnectionStoreError: If the store could not be read or written.
            OversizedValueError: If the argument or the record exceeds the limit.
        """
        ...

    async def connected_accounts(self) -> tuple[ConnectedAccount, ...]:
        """What is connected now, from the store's live records alone (ADR-0151 §9).

        **Complete or refused, never truncated.** It takes no argument, is not
        paged, and admits no ``limit`` and no ``offset``; where the result does not
        fit the configured frame it raises
        :class:`~ai_assistant.core.errors.OversizedValueError` and reports nothing.
        A truncated answer to "what is connected" is a false answer rather than a
        partial one, and there is no honest way for a client to tell the two apart
        (ADR-0139 §2).

        **Answered from the store and never from what the hub can currently
        offer** (ADR-0139 §1). It returns the live record for every reference that
        has one, whatever tools the hub has registered, whatever integrations
        exist, and whatever configuration says: a connection whose integration is
        no longer built is still a connection, and a listing that filtered by what
        the hub holds would hide from the owner exactly the connections they most
        need to see — and hide them from the disconnection that is their only
        remedy.

        **A pending reference is included, with its state** (ADR-0151 §4). It is
        neither omitted nor substituted for by the previous act's record. **No
        client presents a ``PENDING`` record as a working connection**: a surface
        rendering one says the reference is *not connectable* and that the remedy
        is to run the act again, and never that the connection is being
        established, is in progress, or will complete on its own. Nothing is
        running — ADR-0148 §6 rules an interrupted act's state "refused rather than
        reconciled", and the record is inert until a user acts.

        **Computed from one read of the store**, so it is a snapshot: no reference
        appears twice, none is missing because another was being written, and the
        set is internally consistent. It is not a claim that stays true after it is
        computed, and no client presents it as one.

        Returns:
            Every live record, in no contractual order.

        Raises:
            ConnectionStoreError: If the store cannot be read, or holds an entry
                that no longer validates.
            OversizedValueError: If the live set does not fit the contract limit.
        """
        ...

    async def recent_connection_acts(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[ConnectionAct, ...]:
        """What was done, newest first, bounded by ``limit`` (ADR-0151 §9).

        **One row per act on a reference** — per ``(reference, revision)`` pair —
        carrying the furthest provisioning state that act reached, in the store's
        own append order. The store's entry granularity is `tools`-internal
        (ADR-0149 §3) and is not exposed: no implementation returns two rows for
        one act, and no client reads the store's internal shape off this result.

        **It answers a different question from :meth:`connected_accounts` and
        neither derives the other** (ADR-0139 §1). The unsoundness is structural
        and it is the page boundary rather than a clock: a reference whose latest
        act falls outside the page is one a client walking the page would report by
        an *earlier* act, so a user with several connections and a busy history
        would see a disconnected account reported as connected — on the deployment
        with the most history and nowhere else, which is the failure that never
        shows up in a test. **No client derives a reference's current state from
        this**, and none presents a row from it as live, as withdrawn, or as the
        account currently connected under that reference.

        **It carries no instant** (ADR-0151 §9). A connection record has none
        (ADR-0149 §3), so no client presents this order as a timing claim, an
        interval, or a statement about when anything happened: its order is the
        order the store recorded the acts in, and that is the whole of what a
        position means.

        **This is the surface that discharges the record half of ADR-0004 §7** for
        a provisioning act (ADR-0151 §12). A Tier 1 store whose only reader is the
        code that writes it is reviewable by nobody the clause was written for.

        Args:
            limit: The most rows to return. Refused when **not strictly positive**,
                locally and before any I/O, in every implementation — stricter than
                ADR-0085 §9's ``[0, 2**63)`` for :meth:`recent_grants`' reason
                (ADR-0151 §2a). There is deliberately no ``offset``: an offset over
                a store that has none is either a store change or an engine-side
                over-fetch-and-slice, which is a paging surface that lies about its
                cost (ADR-0102 §10).

        Returns:
            Up to ``limit`` acts, newest first. ``account`` is ``None`` **exactly
            when** the act was a disconnection and present exactly when it was a
            provisioning act; where present, its ``reference`` and ``revision``
            equal the act's own (ADR-0151 §4).

        Raises:
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
            ConnectionStoreError: If the store cannot be read, or holds an entry
                that no longer validates.
            OversizedValueError: If the page exceeds the contract limit.
        """
        ...

    # --- the audit trail's two reads (ADR-0186 §1) --------------------------
    #
    # **The trail becomes readable by the person it is kept for, and that is the
    # whole of what these two add.** ADR-0021 §4 gives :class:`AuditTrail` five
    # reads and #1485 records what the milestone-23 QA run found when it drove
    # them: every one answers exactly as ruled, and nothing a user can drive
    # reaches four of them. These promote two of the five and no more.
    #
    # **Neither composes.** Each relays one store read, sorted, and reads no other
    # store (ADR-0186 §1) — so the listing is a **prefix** of the export under §2's
    # order, which is the property an engine that filtered or enriched either one
    # would break with no surface able to tell.
    #
    # **Three of the five stay unpromoted, each for its own reason** (ADR-0186 §4),
    # and no lane adds a counterpart on the strength of this Protocol.
    # ``resolution_of`` was keyed on a binding a user does not hold and every row it
    # could return is in the export (ADR-0309 §5 has since retired it with the old
    # path's park and resume); ``record`` would let a client append to the audit
    # record of what was permitted, which is the fabrication ADR-0184 §4 closed the
    # last route to; and ``clear`` would put an irreversible destruction of the whole
    # record one request away on a transport an enrolled device reaches — the user's
    # erasure right stays where ADR-0021 §4 and ADR-0126 §2 put it. ``get`` is
    # *deferred* rather than refused, with its trigger: a surface that must deep-link
    # one row (ADR-0008 §1).
    #
    # **Both are served on both listeners** (ADR-0186 §5). Neither is a connection
    # method and neither is withheld from ADR-0124's remote listener: a
    # ``PermissionDecision`` carries no credential and no payload, and every class of
    # fact in one already crossed that hop inside a ``Confirmation``'s
    # ``ConfirmationEgress`` until those left with the old path (ADR-0309 §5). Neither
    # is one of ADR-0177 §1's thirty browser operations, and no browser request resolves
    # to either (ADR-0186 §6).

    async def recent_decisions(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[PermissionDecision, ...]:
        """What the permission layer ruled, newest first, bounded (ADR-0186 §1).

        The bounded half of the pair, reading :meth:`AuditTrail.recent`. It
        **relays**: no composition, no filter by tool, by outcome or by window, no
        projection, no enrichment and no summary, and no read of any other store.
        A consumer wanting a subset selects it from what this returns.

        **Bounded and complete are two operations rather than one** (ADR-0186 §1).
        ADR-0021 §4 fixes the store's two reads against each other in terms —
        ``recent`` is bounded by default "because the realistic query is 'what has
        the assistant just done', and an unbounded read of a Tier 1 store by
        default is a shape worth not offering", while ``export`` is the deliberate
        unbounded read discharging a portability obligation. A single method whose
        ``limit`` could be omitted to mean *everything* would make the unbounded
        read the default shape of the listing and hide a data-rights act inside a
        page query.

        **The order is this operation's own guarantee** (ADR-0186 §2), and it is
        the same total order for both: ``decided_at`` **descending**, ties broken
        by ``id`` **ascending**. ``recent_decisions(limit=n)`` returns the first
        ``n`` of the sequence :meth:`export_decisions` returns over the same trail
        state — the **prefix** property, which is what keeps the two answers
        comparable.

        **The order is a claim about when a ruling was made and about nothing
        else** (ADR-0186 §2, ADR-0021 §4). It is not insertion order, and the two
        disagree whenever records are appended out of order; no surface presents a
        position as a statement about when anything was *done*.

        **A page's silence is a fact about the page** (ADR-0186 §7). A resolution
        may lie outside a bounded page, so no surface renders an unresolved
        ``CONFIRM`` as denied, as allowed, as expired, or as awaiting anything.

        **What a surface owes a row it renders is ADR-0186 §7 and §8**, stated once
        over "a surface" so that every adapter inherits it: the ruling's outcome,
        its reason, the instant, and the recorded ``ToolDefinition``'s identifier
        and capability read from the row rather than a registry; ADR-0178 §7's
        content obligations in full over an ``EgressBinding``, a
        :class:`~ai_assistant.core.types.CoverageUnrecordedBinding` or an
        :class:`~ai_assistant.core.types.OriginUnrecordedBinding`; the call's origin
        in **three** distinct states, the third — never recorded — rendered as
        neither of the other two (ADR-0184 §2); nothing at all asserted where the
        binding is ``None``; every value inserted as data; and a row rendered whole
        or not at all, a surface that cannot render one rendering **fewer rows**
        rather than partial ones. §8's bars are the other half: no liveness, no
        authorisation, no transmission wording, no payload behind the digest, no
        tier reach presented as a measurement, and no confirmation composed from a
        row.

        Args:
            limit: The most rows to return. Refused when **not strictly
                positive**, locally and before any I/O, in every implementation —
                stricter than ADR-0085 §9's ``[0, 2**63)`` for
                :meth:`recent_grants`' reason (ADR-0186 §3), since
                ``AuditTrail.recent`` itself refuses zero and §9 forbids either
                implementation from being silently more permissive. There is
                deliberately no ``offset``: the store has none, so an offset would
                be either a store change this contract does not own or an
                engine-side over-fetch-and-slice, which is a paging surface that
                lies about its cost (ADR-0102 §10).

        Returns:
            Up to ``limit`` decisions, newest first, ties broken by ``id``
            ascending — the first ``limit`` of :meth:`export_decisions`' sequence.

        Raises:
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
            AuditError: If the trail cannot be read, or holds a row that no longer
                validates. A row whose binding records no origin, or no coverage, is
                **not** such a row: it comes back as history, carrying an
                :class:`~ai_assistant.core.types.OriginUnrecordedBinding` or a
                :class:`~ai_assistant.core.types.CoverageUnrecordedBinding`, together
                with every other row (ADR-0184 §5, ADR-0233 §14).
            OversizedValueError: If the page exceeds the contract limit.
        """
        ...

    async def export_decisions(self) -> tuple[PermissionDecision, ...]:
        """Every recorded decision, in the same order (ADR-0186 §1, ADR-0021 §4).

        The unbounded half, reading :meth:`AuditTrail.export`, and the surface that
        **discharges ADR-0004 §6's portability obligation for this store** —
        ADR-0021 §4 assigns it there, and until this operation existed it was
        assigned to nobody a user could reach. It relays on :meth:`recent_decisions`'
        terms: nothing composed, filtered, projected, enriched or summarised, and no
        other store read.

        **The order is this operation's own guarantee even though the store states
        none** (ADR-0186 §2). ``AuditTrail.export`` promises no order and this
        contract adds none to it, so an implementation relaying a store read that
        arrives unordered **owes the sort**, over a list it has already
        materialised. Two implementations handing back the same rows in different
        orders would satisfy every other clause here while giving two users two
        different accounts of one history.

        **Complete or refused, never truncated.** It takes no argument and is
        bounded by nothing at the contract, and is subject to ADR-0085 §8c's payload
        limit exactly as every other unbounded read on this surface is. A trail whose
        canonical encoding exceeds the limit raises
        :class:`~ai_assistant.core.errors.OversizedValueError` carrying the limit and
        the measured size; no implementation truncates the artifact, samples it, or
        returns a partial export without saying so. The remedy is
        ``hub_max_frame_bytes``, the setting the connect reply already carries to the
        client — a ceiling rather than a bound, since the trail has no retention rule
        (#108). A cursor is rejected rather than deferred (ADR-0186 §3): it would
        change a ratified store contract for a trail size nobody has observed, and
        replace one honest refusal with an assembly a user cannot verify is complete.

        **A row this returns is read under §7's floor and §8's bars**, exactly as
        :meth:`recent_decisions`' rows are; an artifact written from them is a
        **faithful copy**, and a row whose binding records no origin carries no
        ``planned_with_external_content`` key anywhere under ``egress_binding``
        (ADR-0184 §3). The absence *is* the state, and annotating it would make the
        artifact fail re-validation against ``PermissionDecision``, whose models set
        ``extra="forbid"`` — so the export would no longer be an export.

        Returns:
            Every recorded decision, ordered by ``decided_at`` descending with ties
            broken by ``id`` ascending — :meth:`recent_decisions`' order, applied to
            the whole trail.

        Raises:
            AuditError: If the trail cannot be read, or holds a row that no longer
                validates — on :meth:`recent_decisions`' terms, an unrecorded origin
                excepted.
            OversizedValueError: If the whole trail exceeds the contract limit.
        """
        ...

    # --- the read trail's two reads (ADR-0186 §10) --------------------------
    #
    # **The second pair, mirroring the first**, over
    # :meth:`SourceReadTrail.recent` and :meth:`SourceReadTrail.export` — the shape
    # ADR-0186 §10 fixes for it and ADR-0185 §12 left to this lane. Everything §1
    # says about the decision pair is said here about this one: two operations
    # because a single method cannot be both bounded and complete, neither
    # composing, filtering, projecting, enriching or summarising, and neither
    # reading any other store.
    #
    # **The two trails partition the subject** (ADR-0186 §10, ADR-0185 §10): a read
    # is never a ``PermissionDecision`` and an egress is never a
    # ``SourceReadRecord``, and **neither pair answers the other's half**. No
    # surface presents :meth:`recent_decisions` or :meth:`export_decisions` as an
    # answer to what was read from a source, and none presents these two as an
    # answer to what was decided about an act on the world. Nothing joins them: two
    # rows about the same content share no key, and milestone 24's exit does not ask
    # them to.
    #
    # **What this pair inherits from §1's, without restating it** (ADR-0186 §10):
    # §2's determinism, stated below in this store's own terms; §3's local refusal
    # of ``limit``; §7's last two clauses — a surface renders a row whole or renders
    # **fewer rows**, never partial ones, and inserts every value into its output as
    # **data**, neutralised for that target on render (ADR-0042 §4); and §8's bars on
    # liveness, on authorisation and on event wording. The neutralisation clause is
    # not inherited pro forma: ADR-0183 rules that "the adversary writes the source",
    # and ``SourceReadRecord.source`` is a declared identity stored **byte for byte**
    # with nothing normalised (ADR-0185 §2).
    #
    # **What it does not inherit is §7's egress content floor**, which is about a
    # binding no read record carries. A read row has no ``account_identity``, no
    # spans, no destination set and no payload description, and its origin fact is
    # not a boolean at all: ADR-0185 §3 rules that "the origin fact a read record
    # carries is its ``source``", because on this side there is nothing to compute —
    # a field asserting *this content is external* would be ``True`` on every row
    # ever written.
    #
    # **No per-source query and no count — this lane's choice, not a prohibition it
    # inherited.** ADR-0185 §12 declined to mint either "without a consumer" and left
    # them "the surface ADR's to ask for if it needs them"; ADR-0186 §10 passes that
    # question on rather than closing it, naming "the per-source query and the count
    # it declined to mint without a consumer, which are this surface's to ask for and
    # not this document's to guess at". §1's "no third method, no argument beyond
    # ``limit``" is written about the decision pair and is **not** in §10's
    # inheritance list, so it stands here as the precedent for the shape rather than
    # as the rule.
    #
    # Declined on the same ground ADR-0185 §12 used one level down: a query with no
    # consumer is surface with no consumer (ADR-0045 §1, ADR-0028 §7), and the
    # consumer this pair has is the CLI lane, which can select from what these
    # return. That also keeps the two answers comparable, and it stops a contract
    # acquiring methods nobody calls (ADR-0021 §4). Both stay additive the day a
    # consumer arrives (ADR-0008 §1) — which is the whole reason declining is cheap.
    #
    # **The transport and the browser are decided by their own rules and not by
    # §10's inheritance**, and the distinction is worth stating because §10's
    # inheritance list is *closed*: it names §2, §3, §7's last two clauses and §8's
    # three bars, and it does **not** name §5 or §6. Those two sections are written
    # about the operations §1 mints, and they are cited below as the **precedent**
    # for identical reasoning one store over rather than as clauses this pair
    # inherits. What actually governs here:
    #
    # * **Both listeners carry both, and neither is a connection method** — by the
    #   mechanism's own default rather than by any clause about these methods.
    #   ``wire/surface.py``'s ``METHODS`` is derived from this Protocol and
    #   ``wire/server.py`` bars a method from the remote listener exactly when it is
    #   in ``CONNECTION_METHODS``, so a promoted method is carried on both unless a
    #   decision withholds it. The only decision that withholds any is ADR-0151 §13,
    #   and its ground does not reach here: the five are withheld because they carry
    #   a **Tier 0 credential**, which ADR-0124 §3's accepted-disclosure list does
    #   not cover. A ``SourceReadRecord`` carries no credential and no content —
    #   ADR-0185 §10 excludes content from the record by name — so no new class of
    #   data reaches ADR-0124's hop. ADR-0186 §5 reaches the same conclusion for the
    #   decision pair on the same reasoning.
    # * **No browser request resolves to either** — by ADR-0177 §1's *first* clause,
    #   which is an explicit closed enumeration ("exactly these **thirty** … and no
    #   others") governing every method it does not name. ADR-0186's own Context
    #   states the general rule: "A method added to the Protocol is therefore
    #   outside that enumeration until an ADR puts it inside, which is the property
    #   ADR-0168 §6 wanted when it chose to name what may appear rather than what
    #   may not." So the bar needs no inheritance to bind, and the count of thirty
    #   does not move: it counts what a browser may reach, not what this surface
    #   carries.
    # * **``PROTOCOL_VERSION`` moves** — by ADR-0124 §9's **first** limb, which
    #   reaches "any change to the promoted surface's method set" directly.
    #
    # **This pair is minted by the lane that adds it, against a merged contract**,
    # which is ADR-0186 §10 in terms: the read surface "is a **second pair**
    # mirroring §1's, over ADR-0185 §12's ``SourceReadTrail.recent`` and
    # ``SourceReadTrail.export``, minted by its own lane against the merged
    # contract". What that lane carries is the same shape §11's first clause fixes
    # for the decision lane — the Protocol methods, the shared conformance cases,
    # the ``orchestration`` implementation, the canonical fake, ``HubClient``'s
    # forwarding methods and the version bump, "one change under ADR-0137 §2". §11
    # is written about that lane and is not in §10's inheritance list, so it is the
    # template this one follows rather than a definition of it.
    # No further ADR stands between the two, and §6
    # shows that ADR-0186 says so when it means it: a browser view is "a **later
    # consumer lane with its own ratified decision**", where §10 says "its own
    # lane … against the merged contract". What §10 leaves open is the *spelling*,
    # in ADR-0185 §12's own idiom — "the semantics above are the contract, the
    # spelling is the lane's".

    async def recent_reads(self, *, limit: int = DEFAULT_PAGE_SIZE) -> tuple[SourceReadRecord, ...]:
        """What this system read from a source, newest-recorded first, bounded.

        The bounded half of the read pair, reading :meth:`SourceReadTrail.recent`
        (ADR-0186 §10). It **relays**, on :meth:`recent_decisions`' terms exactly.

        **The order is recording order, and that is a real departure from §1's
        rather than a restatement of it.** ADR-0186 §10 binds this pair to §2's
        *determinism* while forbidding it to reshape §2's *order*, and this store's
        order is not §2's: :meth:`SourceReadTrail.recent` is ordered "by **recording
        order**, reversed — never by ``checked_at``, and no implementation derives
        the order by comparing ``checked_at`` values" (ADR-0185 §6). So both
        operations here answer **newest-recorded first**, and
        :meth:`export_reads` is where the obligation bites.

        **No implementation sorts these rows**, and it could not do so correctly if
        it tried. A :class:`~ai_assistant.core.types.SourceReadRecord` carries no
        sequence number, its ``id`` is caller-minted and unordered, and its
        ``checked_at`` is **caller-supplied** — so an implementation ordering by
        ``checked_at`` would answer differently after a backwards clock correction,
        for rows the store itself keys its prune on recording order to avoid
        (ADR-0185 §6). Recording order is the store's to state and this surface's to
        preserve.

        **The prefix property holds and is what makes the two comparable**
        (ADR-0186 §2, §10): ``recent_reads(limit=n)`` returns the first ``n`` of the
        sequence :meth:`export_reads` returns over the same trail state.

        **A row states an attempt and never a live fact** (ADR-0186 §8, ADR-0185
        §8). No surface derives from one whether a source is still granted, what a
        grant's scope is, or what a source's grant history is —
        ``SourceGrants.live`` remains the only answer to whether a read may happen.
        A ``grant`` naming an id that no longer resolves is **legible history rather
        than corruption**: the row says truthfully what the read cited at the time,
        and no implementation treats it as a defect, repairs it, or drops the row.
        No bound, no schedule, no cursor and no skip decision is derived from what
        this returns (ADR-0093 §5, ADR-0185 §8), and no client presents a read, a
        read count or a last-read instant beside a standing grant (ADR-0139 §6).

        **A row states what was attempted, not what came of it** (ADR-0186 §8's
        third bar, one store over). ``produced`` counts the items the reading
        carried and says nothing about what any use did with them — that is memory's
        record and the notification store's (ADR-0185 §10) — and an outcome is a
        ruling on the attempt rather than a word for an event.

        Args:
            limit: The most rows to return. Refused when **not strictly positive**,
                locally and before any I/O, in every implementation (ADR-0186 §3,
                §10) — the same refusal :meth:`recent_decisions` states, and for the
                same reason: :meth:`SourceReadTrail.recent` refuses a non-positive
                ``limit`` where ADR-0085 §9 would admit zero, and neither
                implementation may be silently more permissive than the other. There
                is deliberately no ``offset``, no ``source`` and no ``outcome``
                argument (ADR-0102 §10, ADR-0186 §1's second clause).

        Returns:
            Up to ``limit`` records, newest-recorded first — the first ``limit`` of
            :meth:`export_reads`' sequence.

        Raises:
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
            ReadTrailError: If the trail cannot be read.
            OversizedValueError: If the page exceeds the contract limit.
        """
        ...

    async def export_reads(self) -> tuple[SourceReadRecord, ...]:
        """Every read attempt the trail still holds, in the same order.

        The unbounded half, reading :meth:`SourceReadTrail.export` (ADR-0186 §10),
        and the surface on which ADR-0004 §6's export right reaches this store.

        **The reversal is this operation's own obligation**, and it is ADR-0186 §2's
        clause arriving in this store's terms. :meth:`SourceReadTrail.export`
        returns "every record the store holds, **in recording order**" — oldest
        first — while :meth:`recent_reads` answers newest-recorded first. An
        implementation that relayed the store's list would hand back the **reverse**
        of the listing's order, and §2's prefix guarantee would be gone with it. So
        the operation reverses what it was handed, over a list it has already
        materialised.

        **Reversed and never sorted**, which is the difference from
        :meth:`export_decisions` worth stating rather than leaving to be discovered.
        ``AuditTrail.export`` states *no* order, so that operation owes a sort; this
        store *does* state one, so the order is derivable only from the store's
        contract and never from the rows. An implementation reaching for
        ``sorted(rows, key=…checked_at…)`` would be ordering by a caller-supplied
        instant the store itself refuses to key on (ADR-0185 §6), and would answer
        differently after a backwards clock correction.

        **It delivers the horizon rather than the history, and no surface presents
        it otherwise** (ADR-0186 §10, ADR-0185 §9, §10). The store prunes: it holds
        at most ``Settings.source_read_trail_max_rows`` records and deletes the
        earliest-recorded first, so this reconstructs every attempt it **still
        holds** and reads older than the configured cap are gone. That is the
        declared cost of the bound ADR-0139 §6 required, ADR-0004 §6's export right
        is satisfied to that extent and no further, and **no lane may report it as a
        complete history**.

        **The two exports on this surface are therefore not equally complete**
        (ADR-0186 §10). :meth:`export_decisions` returns every row its trail holds
        and that trail prunes nothing (#108). A composed artifact carrying both
        states the read half's horizon **on its face**; one presenting a pruned half
        and an unpruned half as one record would claim a completeness half of it
        does not have.

        **Complete or refused, never truncated** (ADR-0186 §3, §10). It takes no
        argument, is bounded by nothing at the contract, and is subject to ADR-0085
        §8c's payload limit exactly as every other unbounded read on this surface
        is. A trail whose canonical encoding exceeds the limit raises
        :class:`~ai_assistant.core.errors.OversizedValueError` carrying the limit and
        the measured size; no implementation truncates the artifact, samples it, or
        returns a partial export without saying so. The remedy is
        ``hub_max_frame_bytes``, the setting the connect reply already carries to the
        client — and, on this store alone, ``source_read_trail_max_rows``, which is
        the horizon itself rather than a frame budget.

        Returns:
            Every record the store still holds, newest-recorded first —
            :meth:`recent_reads`' order, applied to the whole trail.

        Raises:
            ReadTrailError: If the trail cannot be read.
            OversizedValueError: If the whole trail exceeds the contract limit.
        """
        ...

    # --- the trail's two invocation reads (ADR-0192 §4) ---------------------
    #
    # **A third pair over the same store, and the row kind is what is new.** The
    # decision pair above answers what was *decided*; these two answer what the
    # system *did* on an authorisation — a claim written before the callable and a
    # completion written after it (ADR-0192 §§1-2). They read
    # :meth:`AuditTrail.recent_invocations` and :meth:`AuditTrail.export_invocations`
    # and nothing else.
    #
    # **The two row kinds are two operations returning two sequences** (ADR-0192
    # §4). No operation here returns a mixed sequence, neither
    # :meth:`recent_decisions` nor :meth:`export_decisions` widens to carry a
    # :class:`~ai_assistant.core.types.ToolInvocation` or a
    # :class:`~ai_assistant.core.types.RecordedInvocation`, and ADR-0186 §8's clauses
    # bind every row these two return, unchanged and in full.
    #
    # **ADR-0188's hub-down egress record is not returned by either** (ADR-0192 §4).
    # It is neither row kind, it is rendered through no operation ADR-0192 decides,
    # it is listed among no row of these listings, and it is counted in no bound
    # stated over them.

    async def recent_invocations(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[RecordedInvocation, ...]:
        """What the system did on an authorisation, newest first (ADR-0192 §4).

        The bounded half of the pair, reading
        :meth:`AuditTrail.recent_invocations`. It **relays**: no composition, no
        filter by tool, by outcome or by window, no projection, no enrichment and no
        summary, and no read of any other store. The join to the decision is the
        **store's**, taken inside one atomic operation, which is what lets this stay
        a relay — an engine pairing rows with decisions itself would have an
        ``await`` between the two reads and a ``clear()`` able to land in it
        (ADR-0192 §2, §4).

        **Bounded and complete are two operations rather than one**, on
        :meth:`recent_decisions`' reasoning exactly (ADR-0186 §1, ADR-0192 §4): a
        single method whose ``limit`` could be omitted to mean *everything* would
        make the unbounded read of a Tier 1 store the default shape of the listing
        and would destroy the prefix property below.

        **The order is this operation's own guarantee, over a list it has
        materialised** (ADR-0192 §4): the row's ``recorded_at`` **descending**, ties
        broken by the row's ``id`` **ascending**. ``recent_invocations(limit=n)``
        returns the first ``n`` of the sequence :meth:`export_invocations` returns
        over the same trail state.

        **What a surface owes a row it renders is ADR-0192 §4**, stated once over "a
        surface" so that every adapter inherits it. For **every** row: the row's kind
        — claim or completion — the instant it was recorded, and the tool identifier
        and capability the value itself carries. For a **completion** also the
        outcome, the failure kind where the row *carries one*, and the incurred cost
        **including that the cost is unknown** where the basis is ``UNKNOWN``. Where
        the outcome is not ``SUCCEEDED`` and the row carries no ``failure_kind``, the
        floor is met by rendering **that no kind was reported** — neither a kind the
        surface chose nor a blank, and the row and the field both stay. Nothing is
        omitted, truncated, summarised, sampled or counted in place of, and a surface
        that cannot render one whole renders **fewer of them**.

        **Every value rendered comes from the row in hand** (ADR-0192 §4). No
        surface joins two operations' answers, reads a store, calls a second
        operation to complete a row, or infers a missing half.

        **A row is an act the system *began* on that authorisation** — a call it
        claimed and then attempted — and never a statement that the tool callable
        was entered (ADR-0192 §4, ADR-0034 §1). The claim is written *before* the
        callable, and ADR-0192 §1's cancellation clause has a path where the claim
        lands, its completion is written, and the callable is provably never entered.

        **One state establishes entry and is the one a surface may say most about**:
        a completion whose outcome is ``SUCCEEDED`` is the tool reporting an outcome
        back through the seam. Where such a row also carries ``egress_call`` true, a
        surface may say the egress call was **attempted and reported success** — on
        no other row and in no other state. It may **not** say the call was *sent*:
        ADR-0031 §4 bounds ``SUCCEEDED`` to a validated callable return, an unexpired
        deadline and no increase in the cancellation count, none of which is a
        transmission.

        **No surface says or implies that anything was read, received, delivered,
        seen or acted on** by any recipient, on any row, in any state (ADR-0192 §4).
        And **no surface names a recipient, an account, an endpoint or a
        destination** on an invocation row: ``egress_call`` states that the call was
        an egress call and states nothing about whose bytes went where — the
        recipients are :meth:`recent_decisions`' to render under ADR-0186 §7's floor.

        **One attempt appears as up to two rows and is presented as the two rows it
        is** (ADR-0192 §4). A claim renders as a call begun and a completion as how a
        call finished; a claim is never rendered as *pending*, *open*, *in flight*,
        *awaiting an outcome*, or as having "no completion yet", because no row
        carries that fact and the clause above forbids the join that would establish
        it. A surface rendering both kinds together states each row's kind and
        renders neither in the other's vocabulary, and presents no decision row as a
        transmission, no invocation row as a ruling, and no joined pair as a single
        record.

        **A page's silence is a fact about the page** (ADR-0192 §4). No surface
        derives a count of calls, attempted or completed, from anything but the rows
        it holds; the absence of a completion, or of a claim, from a bounded page is
        a fact about the page.

        Args:
            limit: The most rows to return. Refused when it is **not an integer**,
                when it is a ``bool``, and when it is outside ``[1, 2**63)`` —
                locally and before any I/O, in every implementation (ADR-0192 §4).
                That is :meth:`recent_decisions`' bound for its reason:
                ``AuditTrail.recent_invocations`` itself refuses zero, and ADR-0085
                §9 forbids either implementation from being silently more permissive.
                There is deliberately no ``offset``.

        Returns:
            Up to ``limit`` rows, newest first, ties broken by ``id`` ascending —
            the first ``limit`` of :meth:`export_invocations`' sequence.

        Raises:
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
            AuditError: If the trail cannot be read, or holds a row it could not
                pair with the decision that row names.
            OversizedValueError: If the page exceeds the contract limit.
        """
        ...

    async def export_invocations(self) -> tuple[RecordedInvocation, ...]:
        """Every invocation row, in the same order (ADR-0192 §4, ADR-0004 §6).

        The unbounded half, reading :meth:`AuditTrail.export_invocations`, and the
        surface that discharges ADR-0004 §6's portability obligation **for this row
        kind** — :meth:`export_decisions` does it for the decision rows and, after
        ADR-0192 §2, for those alone. The obligation is met by the pair, and there is
        no single whole-trail export. It relays on :meth:`recent_invocations`' terms:
        nothing composed, filtered, projected, enriched or summarised, and no other
        store read.

        **The order is this operation's own guarantee**, over a list it has
        materialised — ``recorded_at`` descending, ties broken by ``id`` ascending
        (ADR-0192 §4). ``AuditTrail.export_invocations`` promises
        ``recent_invocations``' order, and this contract owes the sort regardless:
        two implementations handing back the same rows in different orders would
        satisfy every other clause here while giving two users two different accounts
        of one history.

        **Complete or refused, never truncated.** It takes no argument and is
        subject to ADR-0085 §8c's payload limit exactly as :meth:`export_decisions`
        is (ADR-0192 §4). A trail whose canonical encoding exceeds the limit raises
        :class:`~ai_assistant.core.errors.OversizedValueError` carrying the limit and
        the measured size; no implementation truncates the artifact, samples it, or
        returns a partial export without saying so. The remedy is
        ``hub_max_frame_bytes``, the setting the connect reply already carries to the
        client. **The projection is bounded by construction** and does not make that
        ceiling worse: a :class:`~ai_assistant.core.types.RecordedInvocation` is one
        small row, two identifiers and a boolean, where a
        :class:`~ai_assistant.core.types.PermissionDecision` carries a whole
        ``ToolDefinition`` and an egress binding (ADR-0192 §4, ADR-0186 §3).

        **A row this returns is read under :meth:`recent_invocations`' floor and
        bars**, and an artifact written from them is a **faithful copy**: no key is
        added, renamed or annotated for presentation, so the array re-validates as
        ``tuple[RecordedInvocation, ...]``, whose models set ``extra="forbid"``.

        Returns:
            Every invocation row the trail holds, ordered by ``recorded_at``
            descending with ties broken by ``id`` ascending —
            :meth:`recent_invocations`' order, applied to the whole trail.

        Raises:
            AuditError: If the trail cannot be read, or holds a row it could not
                pair with the decision that row names.
            OversizedValueError: If the whole trail exceeds the contract limit.
        """
        ...

    # --- what the world has cost (ADR-0194 §6) ------------------------------
    #
    # **One member and a read.** It relays :meth:`SpendLedger.spend_totals` and
    # returns what it returns — no composition, no filtering, no reordering, and no
    # second source. The engine holds a ``SpendLedger`` and **never** a
    # :class:`SpendGate`: an adapter able to call the admission has acquired the
    # ability to spend a budget (ADR-0194 §5).
    #
    # **The browser gets nothing from it.** This operation is not one of ADR-0177
    # §1's thirty, no browser request resolves to it, no browser argument reaches
    # it, the gateway makes no call of its own to it, and ADR-0194 §6 widens that
    # enumeration by nothing. A browser view is a later consumer lane with its own
    # ratified decision.

    async def spend_totals(self) -> tuple[SpendTotal, ...]:
        """What each calendar period has cost, in ``SpendPeriod``'s fixed order.

        ``CALENDAR_DAY`` then ``CALENDAR_MONTH``, both entries whatever is
        configured, and each carrying the bounds ADR-0194 §1's rule computed for
        its own period in the **ledger's** configured zone together with the UTC
        offsets in force at those two instants. A renderer prints each bound from
        the value's own offset and never from its own zone or its own ``tzdata``
        (ADR-0194 §5, §6) — which is what lets a client on a different zone
        database render a value its producer computed correctly.

        **An indeterminate period is returned rather than raised** —
        ``accounted=None`` beside a present ``currency`` — and ``currency`` is what
        discriminates that from the other absence: ``currency=None`` means no
        currency is configured and no total was computed. No third meaning is
        assigned to the absence, and a renderer collapsing the two tells a user "no
        total" while their calls are being refused.

        **No surface presents an accounted total as an amount billed, owed or
        charged** (ADR-0194 §6). It is the sum of what this system's tools
        *reported*, and a surface states it as that.

        Returns:
            Exactly two totals, in ``SpendPeriod``'s declaration order.

        Raises:
            SpendUndeterminedError: Only where the ledger cannot produce the values
                at all — a store read that failed, or an injected clock that raised
                (ADR-0194 §5). A trapped sum is **not** that case: the affected
                period comes back indeterminate and the other period's figure is
                still computable.
            OversizedValueError: Under ADR-0085 §8, which this ADR does not lift and
                makes no claim about the reachability of: ADR-0194 §1 bounds each
                contributing amount and nothing bounds the number of rows, so an
                accounted total is not bounded and the declaration is a real one.

        **No other** ``AssistantError`` **escapes**, and that closed set is over
        *this surface's* failure vocabulary and not over a transport's. A
        hub-backed implementation raises
        :class:`~ai_assistant.wire.errors.HubUnavailableError` where no hub is
        listening or the connection goes away mid-request, and
        :class:`~ai_assistant.wire.errors.ProtocolError` on a malformed or truncated
        reply; **both reach the caller unwrapped**, and neither is a failure this
        member declares. They are deliberately not translated to
        ``SpendUndeterminedError``: ADR-0194 §4 enumerates that class over six
        grounds, each of them a way *the spend* could not be reduced to a number,
        and a connection that was not there is none of them — reporting one as the
        other would tell a user a fact about their budget that nothing measured.
        ``recent_decisions`` and ``export_decisions`` are in exactly this position
        and declare neither (ADR-0085 §9, ADR-0186 §5).
        """
        ...


@runtime_checkable
class Secrets(Protocol):
    """Reads one scope's Tier 0 secrets from this installation's keyring (ADR-0125 §1).

    The reading face of the keyring seam, and the one **every read-only consumer
    holds**: `models/` for a provider credential, a `tools/` tool for its own
    integration credential, and the wire client's connect path for the device
    credential ADR-0124 §6 confines to one purpose and one path (ADR-0125 §8).
    None of them holds :class:`SecretStore`, and the split is what makes that a
    type rather than a promise — a tool handed a three-method store can delete the
    device's enrolment credential, and neither the type system nor review would
    notice, because the two entries sit in one keyring behind one object.

    **An instance is bound to two facts the composition root chooses, and a
    caller can name neither.** One installation — the resolved
    ``Settings.data_dir`` ADR-0084 §9 already locates everything else by, injected
    as a namespace rather than read from a setting here — and one
    :class:`~ai_assistant.core.types.SecretScope`. So two data directories on one
    machine share no entry, which is what stops a QA hub's enrolment from
    overwriting the owner's real credential; and a tool's object *refuses* an
    ``ENROLMENT`` name rather than answering it. Every scope word in ADR-0125 §8
    is mechanical for that reason and not advisory.

    **One class and one keyring backing, several instances.** ``PROVIDER``,
    ``INTEGRATION`` and ``ENROLMENT`` are three instances of the one
    keyring-backed implementation, each taking the same installation namespace,
    so the scope is what differs between them and nothing else (§1). One object
    satisfies this Protocol and :class:`SecretStore` structurally, so a root
    hands each consumer the face its job needs without needing two classes.

    **This is a storage seam, not an authorisation one.** No method here performs
    a permission check, consults `permissions/`, or writes an audit record
    (ADR-0125 §9). Nothing here discharges ADR-0017 §3's "credential access
    gated, not just transmission" condition, narrows ADR-0004 §7, or answers #74.
    What the shape does buy is that #74 can land without changing a signature: a
    gating implementation is an object that implements *this* Protocol, consults
    `permissions/` and delegates — a decorator at the composition root, which is
    why :meth:`get` takes a name and returns a value and carries no
    decision-shaped parameter for a decision nobody has made.

    **There is no enumeration**, here or on the wider face. No method lists the
    entries in an installation, in a scope, or at all; every caller reaches an
    entry by naming it (ADR-0125 §5). No consumer needs one, the capability it
    would hand a tool is "discover and read every secret on this machine" rather
    than "read the secret I was given a name for", and a cross-platform keyring's
    portable surface is get, set and delete. The honest consequence is that a
    complete purge of Tier 0 data is composed from the names its holders know, so
    every consumer that writes an entry owes a path that deletes it, and no lane
    may present a purge that skips a scope as complete.

    **Not a Tier 1 store, and not the hub's enrolment-verifier store.** Nothing
    but a Tier 0 secret goes in it, with one exception: a non-secret value
    ADR-0124 §4 and §6 require to travel with one, which today is the enrolled hub
    identity. And ADR-0124 §6's enrolment record — a device's overlay identity,
    its credential *verifier*, its enrolment and revocation instants — stays in
    ``data_dir`` under ADR-0083's layout. A hub that kept credentials here would
    have destroyed the property §6 retains, that the hub holds no device's Tier 0
    secret at rest.

    Cancelling :meth:`get` is governed by this module's cancellation clause
    (ADR-0060), and it **has bite**: a keyring call is I/O and may be in flight.
    Its input-observation clause (ADR-0065) is **vacuous** here and is meant to
    stay that way — :class:`~ai_assistant.core.types.SecretName` is frozen and
    :data:`~ai_assistant.core.types.SecretValue` is immutable, so there is no
    caller-owned container for a result to be torn across.
    """

    async def get(self, name: SecretName) -> SecretValue | None:
        """The value last written under ``name``, or ``None`` if there is none.

        Reads nothing else, consults no policy, writes no record, and creates no
        entry (ADR-0125 §4). The value comes back **verbatim** — no whitespace
        trimmed, no Unicode normalised, no case changed, no re-encoding, nothing
        altered between a :meth:`SecretStore.set` and a subsequent read (§3). Two
        spellings of a secret are two different secrets, and a store that
        helpfully stripped a trailing newline would produce an authentication
        failure nobody could reproduce by inspection.

        **``None`` means the entry is unset, and never that the keyring could not
        be read.** An unreachable keyring raises, and that distinction is the one
        this contract most depends on: if it answered ``None``, "this device is
        not enrolled" and "this device's keyring is locked" would be the same
        observation, and an enrolment flow reading a first run could mint a
        replacement credential that revokes the working one (ADR-0125 §7).

        **``name`` is revalidated here, as a whole, before anything else
        happens** (ADR-0125 §4, §7). Before the keyring is touched, and before
        any attribute of the argument is read: reaching in to dump its fields or
        to read its ``scope`` for a backend prefix checks the invariants *after*
        having depended on them, so a forged argument would fail somewhere other
        than this boundary and with something other than a ``ValueError``. A
        well-typed ``SecretName`` is not proof its invariants ran —
        ``model_construct`` is public and yields one carrying a key ADR-0125 §2
        forbids, which on a case-insensitive backend addresses the very entry its
        lowercase spelling names.

        A concurrent write is never observed half-applied: this returns either
        what a concurrent ``set`` wrote or what preceded it, never a mixture and
        never a fragment. Nothing further is guaranteed under concurrency.

        Args:
            name: The entry to read. Its ``scope`` must be the one this instance
                is bound to.

        Returns:
            The stored value, verbatim, or ``None`` if the entry is unset.

        Raises:
            ValueError: If ``name`` does not satisfy
                :class:`~ai_assistant.core.types.SecretName`'s own invariants, or
                if its ``scope`` is not this instance's. Raised **whatever the
                keyring's state**, including when there is no backend at all: an
                argument fault is deterministic and the caller's to fix, and a
                tool reaching for another scope must be refused identically
                whether the keyring is locked, absent or wide open (ADR-0125 §7).
            SecretStoreUnavailableError: If no keyring backend is available, or
                the backend is locked with no unlock possible in this session.
                Never ``None``.
            SecretStoreError: If the keyring was reached and the read failed.
        """
        ...


@runtime_checkable
class SecretStore(Secrets, Protocol):
    """The whole keyring seam: read, write and remove (ADR-0125 §1).

    :class:`Secrets` plus the two methods that change what is stored. **Holding
    this face is what makes a consumer a writer**, which is the whole point of
    ADR-0125 §1's split: a consumer that only reads is handed :class:`Secrets`,
    and a consumer that writes on one path and reads on another is handed the
    narrow face on the reading one — the shape ADR-0125 §8 gives the wire client,
    whose connect path is `Secrets` and nothing wider.

    **Which consumers hold it is not enumerated here, deliberately.** That is
    decided per scope by ADR-0125 §8 and by whichever later ADR admits a holder,
    each holder's own module saying what it holds and why; a roster in this file
    would read as a closed list while the decisions moved past it, which is what
    happened to the one that stood here (issue #1322). What *is* closed is the
    set of scopes — ADR-0125 §2's three — and no consumer may acquire a fourth
    without the ADR that clause requires.

    Every clause on :class:`Secrets` binds here unchanged — the scope and
    installation binding, the refusal to enumerate, the storage-not-authorisation
    rule, and what may go in it. One object satisfies both Protocols
    structurally, which is what lets a composition root pass a single instance to
    a consumer's ``Secrets`` parameter and to the client's ``SecretStore`` one;
    what a read-only consumer cannot do is *name* :meth:`set` or :meth:`delete`,
    because ``mypy --strict`` runs over ``src`` and ``tests`` and the attributes
    are not on the annotated type.

    **Nothing further is guaranteed under concurrency, and two assumptions are
    named as forbidden because they are the ones a caller would reach for**
    (ADR-0125 §4). :meth:`delete`'s ``bool`` is **not** a synchronisation
    primitive: two callers deleting one entry may both be told ``True``, so it may
    never elect a winner or make an operation happen exactly once. And there is no
    atomicity **across** names — no transaction, no compare-and-set, no
    multi-name write. The claim is stated in the weaker, true form for this
    module's own reason: no cross-platform keyring offers a compare-and-delete, so
    contracting one would ratify an obligation the chosen backing cannot meet. A
    consumer that genuinely needs mutual exclusion over a secret owns a lock; it
    does not read one out of a return value.

    **Two entries can therefore be half-written, and ADR-0124 already handles
    it.** A device holds a credential and an enrolled hub identity, and a crash
    between two :meth:`set` calls leaves one — which ADR-0124 §6 already rules is
    "an incomplete enrolment the client refuses to connect on", a state the client
    must detect whatever the storage does. A client that prefers to avoid it
    entirely may store the pair as one value under one name; both satisfy
    ADR-0124 §6 and ADR-0125 rules neither in.

    Cancelling any method here is governed by this module's cancellation clause
    (ADR-0060), and its last paragraph is the one with bite: **a cancelled write
    may or may not have committed**, so a caller may not assume a cancelled
    :meth:`set` did not land. An implementation driving a synchronous keyring
    library from a worker thread is exactly the shape ADR-0054 ruled on — a
    cancelled call must not release what a worker thread still holds — and that
    rule is inherited here rather than restated.
    """

    async def set(self, name: SecretName, value: SecretValue) -> None:
        """Store ``value`` under ``name``, creating or replacing the entry.

        **Replaces rather than refuses, because rotation is the case that
        matters** (ADR-0125 §4). ADR-0124 §6 makes re-enrolling a device that
        already has a live enrolment a single act that mints a replacement
        credential and forbids an intermediate state; a store that refused an
        occupied name would force delete-then-set at the device, with a window in
        which it holds nothing and a crash in that window leaving it unenrolled.
        So this never refuses on the ground that an entry already exists.

        The value is stored **verbatim** (§3): nothing is trimmed, normalised,
        re-cased or re-encoded between here and a subsequent :meth:`Secrets.get`.

        **Both arguments are revalidated here, at this boundary, before the
        keyring is touched** (ADR-0125 §4) — ``name`` against its own model as a
        whole, and ``value`` through
        :func:`~ai_assistant.core.types.secret_value`. Neither type protects the
        boundary on its own, and they fail to for different reasons.
        :data:`~ai_assistant.core.types.SecretValue` is
        ``Annotated[SecretStr, …]`` with no runtime identity distinct from
        ``SecretStr``, so a caller who builds ``SecretStr("")`` or a 2 KB one and
        passes it directly satisfies every static check while the validator never
        runs; ``SecretName`` does validate when constructed normally, and
        ``model_construct`` skips that altogether. An implementation may not rely
        on either having been validated upstream, exactly as
        :class:`~ai_assistant.core.errors.AssistantError` calls
        :func:`~ai_assistant.core.types.encodable_text` rather than trusting the
        annotation, and as :meth:`SourceGrantStore.record` stores a *validated*
        snapshot rather than the object it was handed.

        A refusal changes nothing: no entry is created, none is replaced, and the
        entry the argument would have addressed is left exactly as it was.

        Args:
            name: The entry to write. Its ``scope`` must be this instance's.
            value: The secret to store, verbatim.

        Raises:
            ValueError: If ``name`` or ``value`` does not satisfy its own type's
                invariants, or if ``name``'s ``scope`` is not this instance's.
                Raised whatever the keyring's state, and nothing is written.
            SecretStoreUnavailableError: If no keyring backend is available, or
                the backend is locked with no unlock possible in this session.
            SecretStoreError: If the keyring was reached and the write failed.
        """
        ...

    async def delete(self, name: SecretName) -> bool:
        """Remove the entry under ``name``, reporting whether one was there.

        **Raises nothing for an absent entry, and calling it repeatedly is
        safe** (ADR-0125 §4, §6). The caller is ADR-0124 §8's device-side
        unenrolment, whose whole job is to make sure the entry is gone; an
        unenrolment that raised the second time it ran would be a worse surface
        for the one operation an owner performs when something has already gone
        wrong. A ``bool`` rather than an exception, because absence and refusal get
        a return value where one exists, and exceptions are kept for faults.

        **The ``bool`` is not a synchronisation primitive.** Two callers deleting
        one entry may both be told ``True`` — no cross-platform keyring offers a
        compare-and-delete — so it may never be used to elect a winner or to make
        an operation happen exactly once (ADR-0125 §4).

        ``name`` is revalidated as a whole before the keyring is touched, on
        :meth:`Secrets.get`'s terms, and a refusal removes nothing.

        Args:
            name: The entry to remove. Its ``scope`` must be this instance's.

        Returns:
            ``True`` if an entry was removed, ``False`` if there was none.

        Raises:
            ValueError: If ``name`` does not satisfy
                :class:`~ai_assistant.core.types.SecretName`'s invariants, or if
                its ``scope`` is not this instance's. Raised whatever the
                keyring's state, and nothing is removed.
            SecretStoreUnavailableError: If no keyring backend is available, or
                the backend is locked with no unlock possible in this session.
            SecretStoreError: If the keyring was reached and the removal failed.
        """
        ...


@runtime_checkable
class ConnectionProvisioner(Protocol):
    """Performs ADR-0148 §6's provisioning act, and says what is connected (ADR-0151 §10).

    The seam by which `orchestration` reaches the connection provisioner in
    `tools/` (ADR-0149 §10). Six members, one per operation on
    ``AssistantEngine``'s connection surface (ADR-0151 §1, ADR-0325 §5:2 adding
    :meth:`provision_keyless` as the sixth), and the placement is
    forced rather than chosen: those operations are engine methods,
    ``AssistantEngine`` is `orchestration`'s, the act's owner is in `tools/`
    (ADR-0149 §1), and a subsystem boundary between them is a Protocol by golden
    rule 1.

    **Holding this seam is not holding a keyring face**, which is the distinction
    ADR-0102 §7 drew about a composition root and ``SourceGrantStore`` and
    ADR-0149 §8's tenth clause states directly for this neighbourhood. The object
    in `orchestration` names six members that take and return `core` types; it
    cannot name ``set``, ``delete`` or ``get``, and no annotation on it mentions
    :class:`Secrets` or :class:`SecretStore` — so ADR-0125 §8's fourth clause
    stays true of `orchestration` word for word.

    **No credential value, and no value derived from one, is returned by any
    member**, and no member names a :class:`~ai_assistant.core.types.SecretName`
    in an argument or a return type (ADR-0149 §10). A
    :class:`~ai_assistant.core.types.ConnectedAccount` and a
    :class:`~ai_assistant.core.types.ConnectionAct` are the whole of what crosses
    it in the returning direction. The credential crosses in the other direction
    on two members, still wrapped in
    :data:`~ai_assistant.core.types.SecretValue`'s redacting holder, and an
    implementation of this seam hands it to the keyring without unwrapping it any
    more times than the write needs.

    **The members are named shorter than the operations they serve, and that is
    deliberate** (ADR-0151 §10). ``AssistantEngine`` needs ``connect_account``
    because its namespace holds every other engine operation besides, and a bare
    ``connect`` would sit beside ADR-0084 §2's connect handshake; this Protocol's
    whole subject is connections. Members named identically to the engine's would
    invite a reader to assume one forwards to the other unchanged, which the mint
    asymmetry and the declared-failure difference both say it does not.

    **Two failures the engine declares are absent here, and their absence is the
    contract rather than an omission** (ADR-0151 §10). No member declares
    :class:`~ai_assistant.core.errors.UnusableIdentityError`, because ADR-0151 §5
    refuses an unusable identity **locally and before any I/O** in every
    implementation of the engine operation — the wire client included — so no
    such call arrives here. And no member declares ``ValueError`` for an argument
    the engine has already validated. :class:`OversizedValueError` is likewise not
    a seam failure: ADR-0085 §8c bounds a serialised payload, and nothing is
    serialised across this boundary.

    **This enumeration is what ADR-0151 §10 places and is not a bar on a later
    ADR adding a member.** ADR-0325 §5:2 exercised it by adding
    :meth:`provision_keyless`; ADR-0153 §2 exercised the freedom it reserved by
    declaring :class:`ConnectionPurger` as a seam of its own rather than by taking
    the member; this Protocol gains **no** purge member, and ADR-0153 §7 records
    it as unchanged.

    **Every implementation is reached by injection and never by an injected
    concrete.** `orchestration` imports no module of `tools/` (golden rule 1), and
    the composition root wires the one implementation.

    Cancelling any member is governed by this module's cancellation clause
    (ADR-0060), and it **has bite**: an implementation writes a connection store
    and a keyring, so a call may be cancelled between two of ADR-0148 §6's three
    writes. ADR-0151 §7 fixes what that leaves — a cancellation propagates
    unconverted, is never turned into
    :class:`~ai_assistant.core.errors.ProvisioningOutcomeUnknownError` or any
    other class on this surface, and leaves the same outcomes those classes
    describe, which the caller reports as *not known* and resolves by reading
    :meth:`connected`. This module's input-observation clause (ADR-0065) is
    **vacuous** here and is meant to stay that way: every argument is a string, an
    integer or a redacting holder over a string, so there is no caller-owned
    container for a result to be torn across.
    """

    async def provision(
        self, *, identity: NonBlankEncodableText, credential: SecretValue
    ) -> ConnectedAccount:
        """Connect a fresh account, minting its reference (ADR-0148 §6, ADR-0151 §3).

        **Takes no reference argument and accepts none under any other name.**
        The mint is the provisioner's: ADR-0149 §1 puts the act, and §3 the store,
        inside `tools/`, so the only component that can mint a reference into that
        store is this one — and an engine-side factory would put the mint on the
        far side of the boundary from the compare-and-swap it has to be atomic
        with. The engine passes nothing and reads the reference off the record
        this returns.

        **The reference is minted from a source no fresh process resumes** — a
        version 4 UUID or an equivalent draw, never a counter, a clock or a hash
        of a supplied value — and is **never reused while the connection store
        holds any entry naming it**, not after a disconnection and not for a
        second account (ADR-0151 §3). The store refuses an append that would
        introduce a reference it already holds, which is the half of the guarantee
        it can establish by itself. The guarantee is bounded by the store's own
        history and ADR-0149 §8's purge is what ends it; **no implementation
        retains a ledger of spent references across a purge**, which would be
        exactly the Tier 1 data ADR-0004 §6 requires the purge to destroy.

        **It returns only when ADR-0148 §6's third write has landed**, and the
        record it returns carries
        :attr:`~ai_assistant.core.types.ProvisioningState.ACTIVE`, the identity
        supplied in this call, and the revision this act took — the reference's
        first (ADR-0151 §7). An implementation that returns after the first or
        second write, or that returns a ``PENDING`` record, does not conform.

        **The identity is recorded verbatim** (ADR-0149 §4): nothing strips,
        case-folds, case-normalises or Unicode-normalises it, and the record
        returned carries it byte-for-byte as supplied.

        **Its refusals cannot lose a compare-and-swap and cannot name an unknown
        reference**, which is why this is two operations over ADR-0148 §6's one
        act rather than one method with an optional reference (ADR-0151 §1): a
        fresh connection's reference is minted and no other act can be holding it.

        Args:
            identity: The user-recognisable name of the account, already refused
                by the engine if it is unusable (ADR-0151 §5).
            credential: The account's credential, relayed unwrapped-into-nothing
                and written to this act's own slot alone.

        Returns:
            The live record this act wrote, ``ACTIVE`` at its own revision.

        Raises:
            IncompleteProvisioningError: If the credential write failed, if either
                of ADR-0148 §6's two re-reads failed, or if the activation's
                compare-and-swap was observed not to land. It carries the minted
                reference, which the store then holds, and asserts that this act
                did not complete and nothing it wrote is or becomes the live
                credential (ADR-0151 §7). A keyring failure at the credential
                write is **converted** into it with the
                :class:`~ai_assistant.core.errors.SecretStoreError` chained as the
                cause; no implementation converts one into
                :class:`~ai_assistant.core.errors.ConnectionStoreError`,
                suppresses one, or treats one as an absent credential.
            ProvisioningOutcomeUnknownError: If the activation **failed rather
                than returning**. The store may have committed the
                compare-and-swap and failed before saying so, so neither
                completion nor incompletion may be asserted; it carries the
                reference, which exists.
            ConnectionStoreError: If the act's own **first** write did not return.
                It carries no reference, because there may be none to carry, and
                nothing about the act may be asserted.
        """
        ...

    async def reprovision(
        self,
        reference: Identifier,
        *,
        identity: NonBlankEncodableText,
        credential: SecretValue,
    ) -> ConnectedAccount:
        """Replace the credential under an existing reference (ADR-0148 §6).

        The same three writes as :meth:`provision`, aimed at a reference the hub
        previously returned: the record first as *pending* at the incremented
        revision naming this act's own slot, the credential second into that slot,
        and the record *active* third. The reference is **compared exactly** — no
        implementation matches one by prefix, by case-insensitive comparison or by
        any equivalence other than equality (ADR-0151 §3).

        **The revision it takes is strictly greater than every revision that
        reference has ever held**, a disconnection included, so ADR-0148 §6's "a
        revision is never reused and never decreases" holds across disconnection
        and re-connection rather than only within one connected life (ADR-0149
        §5).

        **It deletes its predecessor's slot once its own activation has landed**,
        and never before (ADR-0148 §6). A deletion that fails leaves an
        unreferenced slot rather than an incorrect one, and the failure is
        reported and never suppressed.

        **No implementation retries a displaced act, reorders the three writes,
        splits them across calls, or rolls back a write that landed** (ADR-0149
        §9). None activates a record whose credential write it did not itself
        perform, infers an identity from a credential, or treats an absent
        credential as a reason to change a record's state (ADR-0149 §6).

        Args:
            reference: The connection to re-provision, exactly as the hub
                returned it.
            identity: The account identity for the new revision, recorded
                verbatim. It may differ from the previous revision's.
            credential: The replacement credential, written to this act's own
                slot.

        Returns:
            The live record this act wrote, ``ACTIVE`` at the new revision.

        Raises:
            UnknownConnectionError: If the store holds no entry for ``reference``.
                Refused before the first write, so nothing is written.
            DisplacedProvisioningError: If another act took the record over, at
                any of ADR-0148 §6's three points. It does **not** mean this act
                wrote nothing: depending on the point, the store may hold this
                act's own pending entry and the keyring a credential in this act's
                own slot, both named by the store and removed by a disconnection
                of that reference and by ADR-0149 §8's purge (ADR-0151 §7).
            IncompleteProvisioningError: On :meth:`provision`'s terms.
            ProvisioningOutcomeUnknownError: On :meth:`provision`'s terms.
            ResidualCredentialError: If the **predecessor-slot deletion** failed
                after the activation returned having landed. The act
                **completed** — the reference is connected at the new revision —
                and what remains is an unreferenced credential the store still
                names (ADR-0151 §7). The underlying
                :class:`~ai_assistant.core.errors.SecretStoreError` is chained as
                the cause.
            ConnectionStoreError: On :meth:`provision`'s terms.
        """
        ...

    async def provision_keyless(self, *, identity: NonBlankEncodableText) -> ConnectedAccount:
        """Connect a source that needs no credential, minting its reference (ADR-0325 §3).

        **One write, not ADR-0148 §6's three** (ADR-0325 §3:2): the reference's
        first entry, appended ``ACTIVE`` with the identity supplied, revision 1 and
        **no credential slot**. The store's refusal of an append that would
        introduce a reference it already holds (ADR-0151 §3:2) is the act's
        compare-and-swap, so a fresh reference cannot lose one to another act.

        **It calls neither ``set`` nor ``delete`` on the keyring and reads nothing
        from it** (§3:3). There is no credential to write and no predecessor slot to
        delete, because the act is always on a reference it mints and never on one
        the store holds (§3:4); nothing re-provisions a reference into this shape.

        **Takes no reference argument and no credential, and accepts neither under
        any other name.** The reference is minted exactly as :meth:`provision`'s is,
        from a source no fresh process resumes and never reused while the store
        holds any entry naming it (ADR-0151 §3).

        **It returns only when its write has landed** (§3:5), carrying
        :attr:`~ai_assistant.core.types.ProvisioningState.ACTIVE`, the identity
        supplied in this call byte-for-byte, and revision 1. A keyless reference is
        otherwise an ordinary one: :meth:`disconnect` and :meth:`reprovision` act on
        it unchanged, and after a re-provisioning it names a slot (§3:7).

        Args:
            identity: The name the user gives their use of the source, already
                refused by the engine if it is unusable (ADR-0325 §4:3) and
                recorded verbatim.

        Returns:
            The live record this act wrote, ``ACTIVE`` at revision 1.

        Raises:
            ConnectionStoreError: If the one write failed rather than returning, or
                was refused because the store already holds the minted reference.
                It carries **no** reference, and the act's outcome is therefore not
                known (§3:6); the resolution is to read :meth:`connected`. No other
                failure class is raised (ADR-0325 §5:2).
        """
        ...

    async def disconnect(self, reference: Identifier) -> ConnectedAccount | None:
        """Remove a reference's live record and delete its credentials (ADR-0149 §5).

        **Two steps in a fixed order**: a removal entry is appended to the
        connection store **first**, after which the reference has no live record;
        the credential slots are deleted **second**. No other order is permitted —
        deleting the credential first would leave a window in which a live,
        *active* record names a slot holding nothing, which a caller reads as
        connected and discovers empty at the credential read.

        **The slots it deletes are every distinct slot named by an entry for that
        reference whose revision is strictly below the removal entry's own.**
        Deleting only the live record's slot does not satisfy the clause, and
        deleting a slot named by an entry at or above the removal's revision
        **violates** it: those belong to acts this disconnection did not displace,
        and deleting one would leave a later act's activation standing over an
        empty slot (ADR-0149 §5).

        **Idempotent and re-runnable.** On a reference with entries but no live
        record it appends no second removal entry and repeats the deletion pass at
        the latest removal's revision — which is the remedy for a slot a displaced
        act wrote after that removal landed, and for one whose deletion failed. On
        a reference the store holds **no entry** for it writes nothing and deletes
        nothing: no removal entry, so a typo leaves no tombstone and creates no
        revision sequence.

        **It does not reset the reference's revision** (ADR-0149 §5).

        **What it guarantees is that no live record names any slot for that
        reference**, and no surface may state the stronger guarantee that the
        keyring holds nothing for it: a provisioning act displaced by the removal
        may have a keyring write already in flight, which ADR-0148 §6 rules is
        "neither stopped nor waited for" and which lands in that act's own slot
        afterwards. Such a slot is **named by the store**, so a re-run of this call
        and ADR-0149 §8's purge both still reach it.

        **It is prospective.** It does not wait for, cancel or report a
        transmission already in flight, and no surface may present it as having
        stopped one (ADR-0149 §5).

        Args:
            reference: The connection to disconnect, compared exactly.

        Returns:
            The live record removed — as it stood immediately before the removal
            entry was appended — or ``None`` where the reference had no live
            record to remove, which covers both a reference the store has never
            held and one whose latest entry is already a removal. A ``None`` is
            **not** a report of a disconnection: it says one thing, that no live
            record was removed by this call (ADR-0151 §8).

        Raises:
            ResidualCredentialError: If the removal entry **landed** and at least
                one credential deletion did not. The reference is disconnected,
                the residual credentials stay named by the store, and the remedy
                is to run this call again (ADR-0151 §8). The underlying
                :class:`~ai_assistant.core.errors.SecretStoreError` is chained as
                the cause, and the failure is never suppressed.
            ConnectionStoreError: If the store could not be read or written.
        """
        ...

    async def connected(self) -> tuple[ConnectedAccount, ...]:
        """The live record for every reference that has one (ADR-0151 §9).

        **The complete set or a failure.** It is not paged, admits no ``limit``
        and no ``offset``, and no implementation truncates, samples or elides it: a
        truncated answer to "what is connected" is a false answer rather than a
        partial one, and there is no honest way for a client to tell the two apart
        (ADR-0139 §2).

        **Answered from the connection store's live records alone**, whatever
        tools the hub has registered, whatever integrations exist, and whatever
        configuration says. A connection whose integration is no longer built,
        whose tool is no longer registered, or whose configuration has changed is
        still a connection — the record exists, the credential exists in the
        keyring, and the user is the only party who can end it. A listing that
        filtered by what the hub currently holds would hide from the owner exactly
        the connections they most need to see, and hide them from the
        disconnection that is their only remedy (ADR-0139 §1).

        **A pending reference is included, with its state**, and is neither
        omitted nor substituted for by the previous act's record (ADR-0151 §4).

        **Computed from one read of the store**, so it is a snapshot: no reference
        appears twice, none is missing because another was being written, and the
        set is internally consistent. It is not a claim that stays true after it is
        computed, and no client presents it as one.

        Returns:
            Every live record, in no contractual order.

        Raises:
            ConnectionStoreError: If the store cannot be read, or holds an entry
                that no longer validates.
        """
        ...

    async def recent_acts(self, *, limit: int) -> tuple[ConnectionAct, ...]:
        """What was done, newest first, bounded by ``limit`` (ADR-0151 §9).

        **One row per act on a reference** — per ``(reference, revision)`` pair —
        carrying the furthest provisioning state that act reached, in the store's
        own append order. The store's entry granularity is `tools/`-internal
        (ADR-0149 §3) and is not exposed: no implementation returns two rows for
        one act, and no client reads the store's internal shape off this result.

        **It answers a different question from :meth:`connected` and neither
        derives the other** (ADR-0139 §1). The unsoundness is the page boundary: a
        reference whose latest act falls outside the page is one a client walking
        the page would report by an *earlier* act, so a user with several
        connections and a busy history would see a disconnected account reported
        as connected — on the deployment with the most history and nowhere else.

        **It carries no instant**, so its order is the order the store recorded the
        acts in and that is the whole of what a position means (ADR-0151 §9).

        **``limit`` has no default here.** The default is ``AssistantEngine``'s
        (ADR-0085 §3a, :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`), and a
        seam repeating it would be a second place for one number to drift
        (ADR-0151 §10). The engine has already refused a non-positive value before
        this seam is reached, so no member declares ``ValueError`` for it.

        Args:
            limit: The most rows to return, strictly positive.

        Returns:
            Up to ``limit`` acts, newest first.

        Raises:
            ConnectionStoreError: If the store cannot be read, or holds an entry
                that no longer validates.
        """
        ...


@runtime_checkable
class ConnectionPurger(Protocol):
    """The seam ADR-0126's offline delete act reaches the purge through (ADR-0153 §2).

    Two members and no more. The holder is an **offline, irreversible,
    destructive tool** — ``ai-assistant-purge`` in `service/`, running with the hub
    stopped and holding the instance lock — and handing it
    :class:`ConnectionProvisioner` instead would let the one component in the
    system whose entire purpose is destroying an installation also create a
    connection in one. Nothing would call it and nothing would notice; the
    capability would simply be expressible. That is ADR-0125 §1's argument and
    ADR-0149 §1's arriving a third time, and paying for the narrow face again is
    consistency rather than novelty.

    **The two Protocols do not inherit from one another, and that is the point.**
    :class:`SecretStore` inherits from :class:`Secrets` because the wide face
    genuinely *is* the narrow face plus writes. Here neither face contains the
    other: this one has :meth:`purge`, which the provisioner must not have — or
    the engine could purge an installation from a client — and the provisioner has
    four members this one must not have. Two disjoint faces over one
    implementation is the honest declaration, and what a consumer holds is decided
    by what the composition root hands it rather than by a subset relation.

    **Its primary production implementation is the connection provisioner in
    `tools/`** (ADR-0149 §1, ADR-0149 §8), and no second implementation exists in
    production. `service/` reaches it by injection from the composition root and
    constructs neither it, nor a :class:`SecretStore`, nor a connection store
    (golden rule 1, ADR-0126 §3).

    **Holding it confers no keyring face** (ADR-0149 §8's tenth clause), and no
    lane cites holding it as acquiring one. It carries no member that writes,
    provisions, re-provisions or disconnects, no member that reads a credential
    value, and no member that names a
    :class:`~ai_assistant.core.types.SecretName` in any argument or return type.

    **``@runtime_checkable`` is stated as a decision rather than left to the
    house style** (ADR-0153 §2): ADR-0153 §8's conformance suite asserts
    ``isinstance(subject, ConnectionPurger)``, and against a bare ``Protocol``
    that obligation would not fail — it would error.

    Cancelling :meth:`purge` is governed by this module's cancellation clause
    (ADR-0060) and it **has bite**: the purge deletes keyring entries one at a
    time, so a cancellation can arrive with a deletion in flight. ADR-0153 §4 and
    §8 fix what that leaves — the ``CancelledError`` propagates unconverted and is
    never reported as a failed purge, every connection-store entry stays in place,
    and whatever the implementation acquired has been released or completed by the
    moment the cancellation leaves it. This module's input-observation clause
    (ADR-0065) is **vacuous** here: neither member takes an argument.
    """

    async def connected(self) -> tuple[ConnectedAccount, ...]:
        """The live record for every reference that has one (ADR-0153 §2).

        **The same question :meth:`ConnectionProvisioner.connected` answers, with
        the same signature and the same semantics**, and one implementation
        satisfies both faces with **one** method; no lane gives them divergent
        behaviour. Two names for one answer would invite two implementations and a
        drift between them, and a reader comparing the faces would have to check
        whether the difference in name meant a difference in meaning.

        It writes nothing, deletes nothing and reads no credential value.

        **It is on this face rather than derived elsewhere because ADR-0153 §5's
        statement needs it and nothing else can supply it.** The offline act has
        no engine, no hub and no client, so ``connected_accounts`` is unreachable
        to it; and after the act the connection store is gone, so a statement
        composed afterwards names nothing. That is ADR-0126 §7's argument for
        stating the device list before the destruction, applied to a second class
        of custodian the act cannot reach.

        Returns:
            Every live record — each reference's latest entry, where that entry is
            not a removal (ADR-0149 §3).

        Raises:
            ConnectionStoreError: If the store cannot be read, or holds an entry
                that no longer validates. The act treats this as a refusal and
                destroys nothing: an unreadable index is the case in which
                proceeding guarantees the unrepairable state rather than risking
                it (ADR-0153 §4).
        """
        ...

    async def purge(self) -> None:
        """Delete every credential the connection store names, then its entries.

        ADR-0149 §8's purge. It deletes every credential slot the store names —
        the live records' slots and every superseded, pending or removed record's
        slot — and then the entries that named them. No other component composes
        such a path, because ADR-0125 §5 refuses enumeration and the connection
        store is the only durable list of those slots (ADR-0149 §3).

        **The entries are removed only once every distinct slot the store names
        has been confirmed deleted or confirmed absent.** A slot whose deletion
        raises leaves **every** entry in place, the failure reported and never
        suppressed, and no part of the purge proceeding past it. Ordering alone
        does not discharge the obligation: "slots before the store" is satisfied
        by a purge that attempts every slot, has one deletion raise, and destroys
        the store anyway — leaving a credential with no remaining durable name,
        which is precisely the unreachable-and-present state the ordering exists
        to prevent (ADR-0149 §8).

        **A partial purge is a failed purge and is never reported as a completed
        one**, which is why this returns nothing: no value distinguishes a lesser
        outcome (ADR-0153 §2).

        **Idempotent.** It deduplicates the slot names the store yields, treats an
        absent entry as deleted — ``delete`` raises nothing for one (ADR-0125 §4)
        — and re-running it after a failure deletes what remains. Nothing in it
        may be made to depend on a slot being present, so a second call after a
        success does nothing and raises nothing.

        **Scope-confined by construction**: the implementation's
        :class:`SecretStore` instance is bound to
        :attr:`~ai_assistant.core.types.SecretScope.INTEGRATION` and to one
        installation (ADR-0125 §2), so the purge cannot reach a ``PROVIDER`` or
        ``ENROLMENT`` entry or another installation's, and it enumerates nothing.

        **It is a whole-installation act and runs with no provisioning act
        concurrent with it.** The coordinator is responsible for that, trivially
        so where the act is offline (ADR-0126 §2, ADR-0149 §8): the instance lock
        is held across it, no hub can start, and no provisioning act exists to
        race. The purge itself carries no revision cutoff, because it is deleting
        everything rather than displacing a state.

        **An installation that never provisioned a connection is unaffected.** A
        purge over a store that names no slot makes no keyring call, so it cannot
        fail on an absent, locked or backendless keyring — which is what keeps
        this from blocking the delete right on a headless box (ADR-0153 §4).

        Raises:
            SecretStoreUnavailableError: If the keyring cannot be reached at all
                and the store names at least one slot. Reported as the deployment
                condition it is and **never** as "there was nothing to purge"
                (ADR-0125 §7, ADR-0153 §4).
            SecretStoreError: If the keyring was reached and a deletion failed.
                Every store entry stays in place.
            ConnectionStoreError: If the store cannot be read or its entries
                cannot be removed.
        """
        ...


@runtime_checkable
class ByteChannel(Protocol):
    """A duplex byte stream to one endpoint, with its own TLS state (ADR-0191 §1).

    What :meth:`OutboundTransport.open_channel` returns, contracted here because
    it crosses the same seam the opener does. Deliberately **not** an HTTP client:
    it carries no URL, no request or response model, no redirect handling and no
    notion of a method or a header, and a protocol — SMTP, HTTP, JSON-RPC or
    anything else — is built on top of it by the module that holds it and never
    inside the capability (ADR-0191 §2).

    It carries no timeout, no deadline and no retry parameter either. What bounds
    a call that hangs in the transport is ADR-0029 §4's invocation deadline, which
    already bounds the whole invocation; a second bound would be a second place a
    call can be cut, and the two would disagree the first time either was tuned.

    **Six members and no others**, so two implementations cannot disagree about
    the shape a consumer was written against.

    **``read`` and ``read_line`` consume one shared cursor over one stream**:
    octets returned by either are never returned again by the other.

    **The holder closes what it opened** (ADR-0191 §3). A channel is opened per
    call, and neither this Protocol nor :class:`OutboundTransport` carries a pool,
    a cache or a keep-alive — so no subsystem retains a route to the world between
    calls.

    **Reaching TLS is the holder's obligation where the endpoint says so**
    (ADR-0191 §4). Where the endpoint's mode is the upgrade one the channel is
    cleartext until :meth:`start_tls` completes, and this contract neither performs
    the upgrade nor can compel it: what it offers is :attr:`is_secure`, read from
    the channel's own state rather than inferred from the order commands were
    written in, so a holder that must not present a credential in the clear has
    something true to refuse on.

    **It reports what happened to the connection and asserts nothing about
    delivery.** Which outcome a channel failure produces is the holder's
    judgement, made from where in its own protocol the failure landed; this
    contract moves none of that judgement into the capability.
    """

    @property
    def is_secure(self) -> bool:
        """Whether a TLS handshake has completed on this channel."""
        ...

    async def read_line(self) -> bytes:
        r"""Read one line, terminator included, or empty bytes at end of stream.

        The terminator is a single ``b"\n"`` and the line is returned
        **including** it — including a preceding ``b"\r"`` where the far end sent
        one, which is the protocol's to strip and not this contract's.

        **Empty bytes means end of stream and means nothing else.** Octets
        received before end of stream with no terminator among them are discarded
        and end of stream is reported in their place: a line with no terminator is
        not a reply, whatever octets arrived, and reporting it as one would let a
        truncated stream stand in for an answer.

        Returns:
            The line including its terminator, or ``b""`` at end of stream.

        Raises:
            TransportError: If the connection could not be continued, or if the
                far end sent more than
                :data:`~ai_assistant.core.types.TRANSPORT_OCTET_CEILING` octets
                before a terminator. The bound is on the octets **before** the
                terminator, so a line of exactly that many is accepted and comes
                back one octet longer. A far end sending an unterminated line is
                buying memory from a client that is holding a credential, which is
                a fact about the connection and so is this type's subject.
        """
        ...

    async def read(self, limit: int, /) -> bytes:
        """Read at least one and at most ``limit`` octets, or empty bytes at end of stream.

        A short read is ordinary and is not an error.

        Args:
            limit: How many octets at most, an integer in
                ``1..TRANSPORT_OCTET_CEILING`` inclusive.

        Returns:
            Between one and ``limit`` octets, or ``b""`` at end of stream.

        Raises:
            ValueError: If ``limit`` is outside that range — zero, negative, or
                larger — so that **no spelling of ``limit`` means "read until end
                of stream"**. The obvious implementation delegates to
                ``asyncio.StreamReader.read``, where ``-1`` is the standard
                spelling for exactly that, and a peer that streams without closing
                would then exhaust memory through a method whose name says it is
                bounded. It is ``ValueError`` and not ``TransportError`` because
                the two have different subjects: a ``TransportError`` says what
                happened to the connection, and an out-of-domain limit is the
                caller's own defect and says nothing about it. This contract
                states behaviour for integer values; a non-integer is a typing
                defect the gate catches, and no implementation is obliged to
                re-check it at runtime.
            TransportError: If the connection could not be continued.
        """
        ...

    async def write(self, data: bytes, /) -> None:
        """Write ``data`` and flush it.

        Args:
            data: The octets to send.

        Raises:
            TransportError: If the connection could not be continued.
        """
        ...

    async def start_tls(self) -> None:
        """Upgrade this channel to TLS, verifying the endpoint's certificate.

        The peer's certificate chain **and** its hostname are verified against the
        endpoint's host (ADR-0191 §4). This contract exposes no
        verification-disabling option, no caller-supplied trust configuration and
        no way to name a second host for the certificate, so no holder can obtain
        a TLS connection that was not verified against the endpoint it asked for.

        Raises:
            TransportError: If the upgrade was declined or the certificate did not
                verify. :attr:`is_secure` stays ``False``.
        """
        ...

    async def close(self) -> None:
        """Release the channel, whatever state it is in.

        **Idempotent**, and it **suppresses and logs an ordinary release failure
        rather than raising it**: a channel that cannot be released reports that to
        its logs and not to its caller. That is a rule about exception replacement
        rather than about tidiness — a holder closes from a cleanup path, where
        Python replaces the exception in flight with one raised there, so a channel
        that raised here would turn a holder's honest "this may or may not have
        been delivered" into an internal failure and record a possible disclosure
        as one that did not happen.

        **A cancellation delivered from outside the call is exempt from that**, and
        is governed by ADR-0060 §1 above: this method makes the channel safe and
        then re-raises. It never absorbs such a cancellation and never converts it
        into a return. The two rules do not collide once the subject is right: one
        is about a *release failure*, which the caller can do nothing with, and the
        other about a *cancellation*, which is the caller's own control flow
        arriving.
        """
        ...


@runtime_checkable
class OutboundTransport(Protocol):
    """The capability of opening a connection off the device (ADR-0191 §1).

    ADR-0017 §8 described this shape and deferred it; ADR-0191 adopts it. **The
    capability is the opener and not the channel, because opening is the act being
    governed**: a channel is the *result* of an opening, and a subsystem that holds
    one already has a connection — so the thing that must be scarce, and therefore
    the thing that must be injected, is the ability to obtain a channel at all.

    **A subsystem handed none has no route.** Every constructor and factory that
    needs a transport takes it as a **required** argument, with no default value
    and no ``None``-means-the-real-one fallback; there is no module-level
    instance, no accessor function, no registry entry and no import-time
    construction of one anywhere; and there is no parameter, setting, environment
    variable, fallback or retry by which a component that was not handed the
    capability obtains one (ADR-0191 §3). That holds in tests as well as in
    production: a test receives the canonical fake by the same route the
    composition root hands the real implementation, and no test-only back door
    exists for obtaining either.

    **What that buys is a property assertable at runtime, and not a sandbox.**
    Nothing in Python stops a module importing ``asyncio`` and opening a
    connection; what is closed by construction is the *handout*. The import
    contracts and the source-reading nets stay as defence in depth for the case
    this capability cannot see — a module that never asks (ADR-0191 §7) — and
    ADR-0017 §4's "an import contract is a net, not a proof" stands as ratified.

    **Its shape is what pins the destination** (ADR-0191 §4). The one method takes
    an endpoint it was handed, so an implementation performs no name resolution
    beyond that host, follows no redirect or referral, and offers no way to reach
    a second host on one call. A URL-shaped capability would hand its holder the
    world: its argument names a host, so a holder that can build a string can
    reach any host.
    """

    async def open_channel(self, endpoint: TransportEndpoint) -> ByteChannel:
        """Open a channel to ``endpoint``, and to nothing else.

        Args:
            endpoint: The host, port and TLS mode to connect to, already parsed.
                An implementation parses no string of its own.

        Returns:
            A channel already connected to ``endpoint``, and already under TLS
            where ``endpoint.implicit_tls`` is ``True``.

        Raises:
            TransportError: If the endpoint could not be connected, or a
                connection was made and could not be verified. A channel that
                could not be connected or could not be verified is **raised over
                rather than returned**, so no holder is ever handed one whose
                state it would have to interrogate.
            CancelledError: Re-raised after the release below, never absorbed and
                never converted into a return (ADR-0060 §1).

        **A call that acquires a socket and then leaves by any exceptional path
        before returning a channel releases what it acquired first.** That covers
        a cancellation delivered from outside, and equally an ordinary failure
        during establishment — a connect that failed after the socket existed, an
        implicit-TLS certificate that did not verify, a channel object that could
        not be constructed. No channel reached the caller in any of those cases,
        so nothing else can ever release it, and ADR-0060 §1's first clause is
        unsatisfiable at this seam any other way.

        **A failure that arises on a channel this method already returned is not
        that clause's subject** — a refused ``start_tls``, a line that overran, a
        write to a far end that has gone. Releasing there is the holder's, under
        the rule that a channel is closed by whoever opened it: the division is by
        *where the failure lands*, and there is no case belonging to both.
        """
        ...


@runtime_checkable
class TelegramBotClient(Protocol):
    """The line's bot on Telegram, as the line's reader and writer reach it (ADR-0323).

    **The line's bot** is the owner's own in direct mode, and in relayed mode the
    shared bot the relay on the box holds, which the user linked their account to
    (ADR-0330 §2, §12:1). Which mode a line is in is configuration of the one
    production implementation at its construction, fixed for its life (ADR-0330 §3:3,
    §12:2): no member, argument or result here says or changes it. **In relayed mode
    the relay stands in Telegram's place** in what this contract says the calls reach
    (ADR-0330 §4:16): it serves the Bot API faithfully, so every rule below about
    what Telegram answered holds of the relay's answers unchanged (§4).

    **The line's one route to Telegram** (§11). Every Bot API call the line makes —
    a poll for new messages and buttons' callbacks, a message sent, the typing
    indicator renewed, and an approval request's card posted, edited and its tap
    answered (ADR-0361 §8:3) — is made by the one production implementation of this
    contract, in ``ai_assistant.tools.egress`` and in no other module (§11:1, ADR-0330
    §9:1), and the line's reader and writer in ``orchestration`` reach it through this
    Protocol alone (§15). Named for the thing it talks to, as :class:`OutboundTransport`
    is: what a caller holds is the bot, and what it can ask of it is these six calls.

    **These are not egress calls in ADR-0148's sense** (§11:2): no ``ActionRequest``,
    binding or ruling exists for them, and the approval that covers what they carry
    is the owner's connect act and the line's two settings (§12:1). What stands in
    for ADR-0148's per-call machinery is the order every implementation keeps, and
    which §11 and §13 state:

    1. **The arguments are checked first**, before anything is read and before the
       call's bound starts: a value no call could be made with is a ``ValueError``,
       and nothing is touched for it.
    2. **A chat other than the one the line's settings name is refused** before
       anything else is read (§6:1, §12:1) — :attr:`TelegramFailure.OTHER_CHAT`.
       Nothing a caller passes can name a chat the owner did not.
    3. **Only then is the line's credential read** — the bot's token in direct mode,
       the hub's relay credential in relayed mode (ADR-0330 §6:4) — through the
       ``INTEGRATION``-scoped ``Secrets`` face, once per call, with the connection
       record read before it and again before any byte is sent (§11:4, ADR-0148 §6,
       ADR-0330 §6:5). A record that is not active, that moved across the read, or
       that names a slot holding nothing, is :attr:`TelegramFailure.UNAVAILABLE`, and
       nothing is written. **In relayed mode a credential containing ``:``** — the
       mark every Bot API token carries — **is refused the same way**, before any
       byte is written, so a bot token in the hub's keyring never reaches a relay
       (ADR-0330 §6:3).
    4. **The credential is bound into the request target inside the implementation**,
       in the token's place, and no caller ever holds the target (§11:8, ADR-0330
       §6:6). Nothing this contract returns or raises, and nothing an implementation
       logs, carries the target or any part of the credential (§11:9).
    5. **One request, to the line's one origin**: ``https://api.telegram.org``, fixed
       in code, in direct mode; in relayed mode the configured relay origin, in its
       canonical form, verified against the configured certificates alone and never
       against the system's authorities, and no call to ``https://api.telegram.org``
       at all (§11:5, ADR-0330 §3:2, §3:4, §7). A relay whose certificate does not
       verify is a channel that could not be opened —
       :attr:`TelegramFailure.NOT_WRITTEN`, nothing written (ADR-0330 §7:4). Either
       way the request is on a channel opened for this call and closed by it, with no
       redirect followed (§11:5, §11:14), and every call is a ``POST`` with a JSON
       body (§11:7).

    **The claim is the caller's, and the contract makes naming it unavoidable.**
    §11:3 and §13:2 make every call wait for a durable record claimed before it is
    sent — an activation's message on its effect record (ADR-0306 §5:4), and a fixed
    reply, a typing indicator and a poll on a record of the line's own. That record
    is the caller's to claim and to complete with the outcome returned here: this
    contract holds no ledger, as :class:`Forecaster` holds none. What it
    does hold is that **every call names the attempt it is the claimed record's**:
    ``attempt`` is required on every member and refused blank, so a call
    written without a claim in hand does not have a value to pass, and what the
    implementation records of the call is filed under it.

    **The line's two bounds are the caller's, and there is no spelling for
    "unbounded"** (§11:10 to §11:12, ADR-0241 §1). Every member takes ``timeout``,
    required, keyword-only, strictly positive, and enforced inside the call: a
    caller wrapping a call in ``asyncio.timeout`` instead would cancel it mid-await
    and could not tell a request that was written from one that was not, which is
    the distinction §6:3 to §6:4 turns on.

    **No member raises for anything Telegram or the network did.** Each failure is
    a :class:`~ai_assistant.core.types.TelegramFailure` on the returned outcome,
    for :class:`Forecaster`'s reason: the caller has a record to complete whatever
    happened, and an exception would leave it claimed with no outcome — which
    §13:2 forbids resolving by guessing. ``ValueError`` is raised only for an
    argument no call could be made with, before anything is read.

    **Cancellation** (ADR-0060): a call cancelled from outside re-raises
    ``CancelledError`` after closing its channel, and is converted into no outcome.
    Its effect is indeterminate to the caller: a request may have been written.
    A call's own bound ending is not a cancellation from outside, and is an
    outcome.

    **A BREAKING contract change under golden rule 5**, decided by ADR-0323 §15 and
    landing with its conformance suite and canonical fake in
    :mod:`ai_assistant.testing` (``CONTRIBUTING.md`` → "Adding a Protocol"). Rules 3
    and 5 are restated for relayed mode by ADR-0330 §12:1, again with the suite, and
    with no member, argument, result or ``TelegramFailure`` member changed (§12:2).
    ADR-0361 §8:3 widens it again, with the suite and the fake: sending a message with
    buttons (:meth:`send_with_buttons`), editing a message (:meth:`edit_message`) and
    answering a button's callback (:meth:`answer_callback`), and a poll asks for
    callbacks beside messages (:attr:`~ai_assistant.core.types.TelegramUpdate.callback`).
    All three keep the five rules above, and the connect act's approval covers them for
    the one chat the settings name (ADR-0361 §4:12).
    """

    @property
    def chat_id(self) -> int:
        """The one chat this client writes to: the user's private chat with the bot.

        Telegram identifies a private chat by the other account's id, so this is
        ``Settings.telegram_user_id`` (§3:2). Fixed for the client's life. A send or
        a typing indicator naming any other chat is refused before the token is read.
        """
        ...

    async def poll(
        self,
        *,
        attempt: str,
        offset: int | None,
        wait: timedelta,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, ADR-0323 §11:10); an outer `asyncio.timeout` could not tell a written request from one never sent
    ) -> TelegramPollOutcome:
        """Ask Telegram for new messages, confirming what ``offset`` says was dealt with.

        One ``getUpdates`` call, asking for new messages and buttons' callbacks only
        (ADR-0361 §8:3), which Telegram holds
        open for at most ``wait`` while none is waiting (§11:10). **The offset
        confirms**: Telegram forgets every update whose id is below it, so a caller
        passes one only for updates already dealt with (§5:6) — and ``None`` confirms
        nothing. That makes a poll a write, which is why it is a ``POST`` (§11:6).

        An update returned is one Telegram still holds: a poll that confirms nothing
        returns it again. Which updates are input is the reader's (§5:1 to §5:3); this
        returns every update Telegram handed back, those from other accounts and chats
        included, so the reader can confirm them too.

        Args:
            attempt: The id of the durable record the caller claimed for this poll
                (§13:2). Non-blank.
            offset: The lowest update id still wanted, or ``None``. Non-negative:
                Telegram reads a negative offset as "forget all but the last few",
                which no reader means.
            wait: How long Telegram may hold the request while nothing is waiting —
                ``Settings.telegram_poll_wait``. Zero or more; Telegram takes whole
                seconds, so a fraction is dropped and the wait is never longer than
                asked.
            timeout: The bound on the whole poll — ``Settings.telegram_poll_bound``.
                Strictly greater than ``wait`` (§11:10).

        Returns:
            Done, with the updates Telegram handed back in ascending update id; or a
            failure, carrying none. **A poll that reaches its bound is**
            :attr:`~ai_assistant.core.types.TelegramFailure.UNKNOWN`, its channel
            closed, and has taken nothing in (§11:11).

        Raises:
            ValueError: If ``attempt`` is blank, ``offset`` is not a non-negative
                ``int`` or ``None``, ``wait`` is not a non-negative ``timedelta``, or
                ``timeout`` is not a ``timedelta`` strictly greater than ``wait``.
                Raised before anything is read.
            CancelledError: Re-raised after the channel is closed, when the poll is
                cancelled from outside (ADR-0060 §1).
        """
        ...

    async def send(
        self,
        *,
        attempt: str,
        chat_id: int,
        text: str,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, ADR-0323 §11:12); an outer `asyncio.timeout` could not tell a written request from one never sent
    ) -> TelegramSendOutcome:
        """Send one message of plain text to the line's chat (§6).

        One ``sendMessage`` call, and **never a retry**: whether to send again is the
        caller's, read off the outcome's
        :attr:`~ai_assistant.core.types.TelegramFailure.retryable` (§6:3). A text
        longer than one Telegram message is not this member's to cut: the writer cuts
        it into parts by §6:6's rule and sends each, so that each part is one call
        with its own outcome, and a message cut short between parts is recorded as
        what it is (§6:6).

        Args:
            attempt: The id of the durable record the caller claimed for this
                message — for an activation's message, its effect record (§11:3).
                Non-blank.
            chat_id: The chat to send to. Anything but :attr:`chat_id` is refused as
                :attr:`~ai_assistant.core.types.TelegramFailure.OTHER_CHAT`.
            text: The message's text, sent as plain text. Not blank, encodable as
                UTF-8, and within
                :data:`~ai_assistant.core.types.TELEGRAM_MESSAGE_LIMIT` as
                :func:`~ai_assistant.core.types.telegram_length` measures it.
            timeout: The bound on this send — ``Settings.telegram_send_bound``
                (§11:12). Strictly positive.

        Returns:
            Done, with the message id Telegram returned (§6:2); or a failure. **A
            send cut off by its bound after its request was written is**
            :attr:`~ai_assistant.core.types.TelegramFailure.UNKNOWN`; one cut off
            before it was written is
            :attr:`~ai_assistant.core.types.TelegramFailure.NOT_WRITTEN`.

        Raises:
            ValueError: If ``attempt`` is blank, ``chat_id`` is not an ``int``,
                ``text`` is not text this member will send, or ``timeout`` is not a
                strictly positive ``timedelta``. Raised before anything is read.
            CancelledError: Re-raised after the channel is closed, when the send is
                cancelled from outside (ADR-0060 §1). Whether the message was sent is
                then unknown to the caller.
        """
        ...

    async def show_typing(
        self,
        *,
        attempt: str,
        chat_id: int,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, ADR-0323 §11:12); an outer `asyncio.timeout` could not tell a written request from one never sent
    ) -> TelegramOutcome:
        """Show Telegram's "typing…" in the line's chat, once (§6:7).

        One ``sendChatAction`` call. Telegram shows the indicator for a few seconds,
        so the writer renews it while an activation runs; nothing is written into the
        chat (ADR-0292 §11:7).

        Args:
            attempt: The id of the durable record the caller claimed for this
                indicator (§13:2). Non-blank.
            chat_id: The chat to show it in. Anything but :attr:`chat_id` is refused
                as :attr:`~ai_assistant.core.types.TelegramFailure.OTHER_CHAT`.
            timeout: The bound on this call — ``Settings.telegram_send_bound``.
                Strictly positive.

        Returns:
            Done, or a failure classed as a send's is.

        Raises:
            ValueError: If ``attempt`` is blank, ``chat_id`` is not an ``int``, or
                ``timeout`` is not a strictly positive ``timedelta``. Raised before
                anything is read.
            CancelledError: Re-raised after the channel is closed, when the call is
                cancelled from outside (ADR-0060 §1).
        """
        ...

    async def send_with_buttons(
        self,
        *,
        attempt: str,
        chat_id: int,
        text: str,
        buttons: Sequence[TelegramButton],
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, ADR-0323 §11:12); an outer `asyncio.timeout` could not tell a written request from one never sent
    ) -> TelegramSendOutcome:
        """Send one message of plain text with a row of buttons under it (ADR-0361 §4:2).

        One ``sendMessage`` call carrying an inline keyboard of one row, and **never a
        retry**, as :meth:`send`. A tap on a button comes back on a later poll as an
        update's :attr:`~ai_assistant.core.types.TelegramUpdate.callback`, carrying the
        button's data. Every rule :meth:`send` keeps holds here: the chat, the text, the
        bound and the outcome.

        Args:
            attempt: The id of the durable record the caller claimed for this message
                (§13:2). Non-blank.
            chat_id: The chat to send to. Anything but :attr:`chat_id` is refused as
                :attr:`~ai_assistant.core.types.TelegramFailure.OTHER_CHAT`.
            text: The message's text, as :meth:`send` takes it: within one message.
            buttons: The buttons, in order on one row: one to
                :data:`~ai_assistant.core.types.TELEGRAM_BUTTONS_MAX`, each a
                :class:`~ai_assistant.core.types.TelegramButton`, their data distinct.
            timeout: The bound on this send. Strictly positive.

        Returns:
            Done, with the message id Telegram returned; or a failure, classed as
            :meth:`send` classes it.

        Raises:
            ValueError: If an argument is one :meth:`send` refuses, or ``buttons`` is a
                bare string, not a sequence of buttons, empty, longer than the bound, or
                carries one data twice. Raised before anything is read.
            CancelledError: Re-raised after the channel is closed, when the send is
                cancelled from outside (ADR-0060 §1).
        """
        ...

    async def edit_message(  # noqa: PLR0913 — the call's six keywords, each the Bot API's
        self,
        *,
        attempt: str,
        chat_id: int,
        message_id: int,
        text: str,
        buttons: Sequence[TelegramButton],
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, ADR-0323 §11:12); an outer `asyncio.timeout` could not tell a written request from one never sent
    ) -> TelegramOutcome:
        """Replace the text and the buttons of a message the bot sent (ADR-0361 §4:5).

        One ``editMessageText`` call, and **never a retry**. The message keeps its id
        and its place in the chat; its text becomes ``text`` and its buttons
        ``buttons``, and an empty ``buttons`` takes every button away. Telegram refuses
        an edit that would change nothing, and that refusal is
        :attr:`~ai_assistant.core.types.TelegramFailure.REFUSED` as any other is: the
        caller edits only where what it shows changed.

        Args:
            attempt: The id of the durable record the caller claimed for this edit
                (§13:2). Non-blank.
            chat_id: The chat the message is in. Anything but :attr:`chat_id` is
                refused as :attr:`~ai_assistant.core.types.TelegramFailure.OTHER_CHAT`.
            message_id: The id Telegram gave the message: a positive ``int``.
            text: The message's new text, as :meth:`send` takes it.
            buttons: The buttons it shows after the edit, as :meth:`send_with_buttons`
                takes them, or none.
            timeout: The bound on this call. Strictly positive.

        Returns:
            Done, or a failure classed as a send's is.

        Raises:
            ValueError: If an argument is one :meth:`send` refuses, ``message_id`` is
                not a positive ``int``, or ``buttons`` is not a sequence of buttons
                :meth:`send_with_buttons` would send, empty allowed. Raised before
                anything is read.
            CancelledError: Re-raised after the channel is closed, when the call is
                cancelled from outside (ADR-0060 §1).
        """
        ...

    async def answer_callback(
        self,
        *,
        attempt: str,
        chat_id: int,
        callback_id: str,
        text: str,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, ADR-0323 §11:12); an outer `asyncio.timeout` could not tell a written request from one never sent
    ) -> TelegramOutcome:
        """Answer one button's callback, showing ``text`` on the tapper's screen (§4:9).

        One ``answerCallbackQuery`` call, and **never a retry**. Telegram shows the text
        briefly over the chat and writes nothing into it. ``chat_id`` is the chat the
        tapped message is in, which the caller read off the callback: a callback from
        any chat but :attr:`chat_id` is no callback the line answers.

        Args:
            attempt: The id of the durable record the caller claimed for this answer
                (§13:2). Non-blank.
            chat_id: The chat the callback came from. Anything but :attr:`chat_id` is
                refused as :attr:`~ai_assistant.core.types.TelegramFailure.OTHER_CHAT`.
            callback_id: Telegram's id for the callback query, as the update carried
                it: non-blank, within
                :data:`~ai_assistant.core.types.TELEGRAM_CALLBACK_ID_MAX_CHARS`.
            text: What to show: non-blank, with a UTF-8 form, within
                :data:`~ai_assistant.core.types.TELEGRAM_CALLBACK_ANSWER_MAX_CHARS`.
            timeout: The bound on this call. Strictly positive.

        Returns:
            Done, or a failure classed as a send's is.

        Raises:
            ValueError: If ``attempt`` is blank, ``chat_id`` is not an ``int``,
                ``callback_id`` or ``text`` is not one this member sends, or ``timeout``
                is not a strictly positive ``timedelta``. Raised before anything is
                read.
            CancelledError: Re-raised after the channel is closed, when the call is
                cancelled from outside (ADR-0060 §1).
        """
        ...


@runtime_checkable
class TelegramIntakeRecord(Protocol):
    """The Telegram line's own durable record: its intake, and its own calls (ADR-0323).

    **Two records of the line's, kept in one store because one step needs both.**

    * **The intake record** (§5:8 to §5:10), the reader's bookkeeping as
      :class:`ConversationStore`'s ``take_in`` is the hub chat's (ADR-0293 §6:6 to
      §6:9): which updates the reader took in, by their Telegram update ids and by
      which activation, and which non-text messages it answered. It holds no message
      text, no sender and no time. An update from another account or chat is not
      input and is recorded nowhere (§5:2): the reader confirms it through the offset
      alone.
    * **The line's own call records** (§13:2): every call the line makes other than
      an activation's message — a poll, a typing indicator, the fixed reply to a
      non-text message and the fixed message after a restart — is claimed here before
      it is sent, under an attempt id this record mints, and finished here with its
      outcome. An activation's message is claimed on its effect record instead
      (§11:3, ADR-0306 §5:4), and nothing here touches one. A claim left with no
      outcome, as after a crash, is never resolved by guessing: no member writes an
      outcome but :meth:`finish`, and none treats an open claim as done or as not
      done.

    They share a store because answering a non-text message *is* claiming its fixed
    reply: §5:9's "never answered again" and §13:2's "claimed before it is sent" are
    one fact, written in one indivisible step by :meth:`claim_reply`. And a poll's
    offset is the intake record's (§12): :meth:`claim_poll` hands the poll the offset
    to send, so what a poll confirms is only what this record holds as dealt with
    (§11:11).

    **The confirm rule** (§5:6). The reader confirms an update to Telegram once it is
    dealt with — input once its activation is admitted and :meth:`take_in` has
    marked it, a non-text message once :meth:`claim_reply` has answered it, and an
    update that is not input once it is seen. The reader, which holds the updates,
    says when every update up to an id is dealt with (:meth:`confirm_through`); the
    record owes Telegram that confirmation until a poll carrying it comes back done,
    and then owes nothing, so a later poll sends no offset at all.

    **What it keeps.** An update Telegram has forgotten is never handed back, so once
    a poll whose offset confirmed it comes back done, the record drops the update and
    every finished fixed-reply record for it: what was kept to tell a repeat from a
    new update has nothing left to tell. Of the finished polls and typing indicators,
    each implementation keeps a bounded number, the newest, and drops the rest. **A
    claim with no outcome is never dropped**, and neither is a restart's fixed
    message, whatever its outcome; :meth:`clear` erases everything. How long a poll's
    or a typing indicator's record is kept is the implementation's (§13:2); like
    every record of the line, it is the user's data and is purged with it.

    **The mutation exclusion is this seam's obligation and not a caller's**, as
    :class:`ConversationStore`'s is: every member that writes observes the record,
    decides and writes as one indivisible step, against every other member, across
    processes as well as coroutines. An implementation meets it its own way — an
    in-memory one with a lock, a SQLite-backed one with an ``IMMEDIATE``
    transaction.

    **Every read returns a detached snapshot**: the exchanged types are frozen
    pydantic models, and each mapping returned is fresh.

    Every member raises :class:`~ai_assistant.core.errors.TelegramIntakeRecordError`
    for a store fault. A malformed argument is a ``ValueError``, raised before
    anything is read. Cancelling any member is governed by this module's
    cancellation clause (ADR-0060). Input observation (ADR-0065) binds it too: every
    argument is immutable except the caller-owned ``update_ids`` sequences of
    :meth:`take_in` and :meth:`recorded`, which an implementation reads once,
    before its first ``await``.

    A Tier 1 store under ``Settings.data_dir``, so the assistant's own store
    (ADR-0155 §1:2): implementations persist **locally only**.

    **A BREAKING contract change under golden rule 5**, decided by ADR-0323 §15's
    second contract seam and landing with its conformance suite, its canonical fake
    in :mod:`ai_assistant.testing` and its store (``CONTRIBUTING.md`` → "Adding a
    Protocol", ADR-0137 §2).
    """

    # --- the intake record (§5:6, §5:8 to §5:10) ------------------------------------

    async def take_in(self, update_ids: Sequence[int], *, activation_id: str) -> tuple[int, ...]:
        """Record that ``activation_id`` took in the updates ``update_ids`` name (§5:8).

        Called when the activation is admitted (§5:6, ADR-0293 §6:8). In one step it
        marks each named update the record does not hold; an update already taken in
        keeps the activation that took it in first, and an update answered is never
        taken in (§5:9). So after a restart the updates an interrupted activation took
        in are not taken in again (§5:10). No text is held.

        Args:
            update_ids: At most 1000 update ids, each an ``int`` in ``[0, 2**63)``;
                duplicates are permitted.
            activation_id: The activation that took them in; a non-blank ``str``.

        Returns:
            The update ids this call marked, ascending.

        Raises:
            ValueError: Before any I/O, if ``update_ids`` is a ``str`` or not a
                sequence, holds more than 1000 ids or one outside ``[0, 2**63)`` or
                not an ``int``, or ``activation_id`` is not a non-blank ``str``.
            TelegramIntakeRecordError: If the record cannot be written.
        """
        ...

    async def recorded(self, update_ids: Sequence[int]) -> Mapping[int, TelegramIntake]:
        """Return what the record holds of each named update, where it holds one (§5:8).

        How the reader tells a repeat from a new update before it admits an
        activation: an update the record holds was dealt with, by the activation an
        entry taken in names or by the fixed line an entry answered records. Keyed by
        update id; an update the record holds nothing of is simply missing. A fresh
        mapping on every call.

        Raises:
            ValueError: Before any I/O, as :meth:`take_in`'s ``update_ids``.
            TelegramIntakeRecordError: If the record cannot be read, or a stored row
                is corrupt.
        """
        ...

    async def confirm_through(self, update_id: int) -> None:
        """Record that every update up to and including ``update_id`` is dealt with.

        The reader's statement under §5:6, made once it has dealt with each update
        Telegram handed it up to this one: taken in, answered, or seen and not input.
        From then the record owes Telegram the confirmation, and the next poll it
        claims carries the offset ``update_id + 1`` (:meth:`claim_poll`) until one
        comes back done. **It never lowers what is owed**: a lower id where a higher
        one is owed changes nothing.

        Args:
            update_id: An ``int`` in ``[0, 2**63 - 1)``.

        Raises:
            ValueError: Before any I/O, if ``update_id`` is not such an ``int``.
            TelegramIntakeRecordError: If the record cannot be written.
        """
        ...

    # --- the line's own call records (§13:2) -----------------------------------------

    async def claim_poll(self) -> TelegramPollClaim:
        """Claim a poll's record, and hand it the offset it is to send (§5:6, §13:2).

        One step: it mints an attempt and records the claim with the offset the
        record owes Telegram, or ``None`` where it owes none, which the poll then
        sends unchanged. So a poll confirms only what :meth:`confirm_through` said is
        dealt with (§11:11).

        Returns:
            The claim: its attempt and its offset.

        Raises:
            TelegramIntakeRecordError: If the record cannot be written, or the id
                factory kept minting an attempt already held.
        """
        ...

    async def claim_typing(self, activation_id: str) -> str:
        """Claim the record of one typing indicator shown for ``activation_id`` (§6:7).

        Always claims: the writer renews the indicator while the activation runs,
        and each renewal is a call of its own.

        Args:
            activation_id: The activation the indicator is shown for.

        Returns:
            The claimed record's attempt.

        Raises:
            ValueError: Before any I/O, if ``activation_id`` is not a non-blank
                ``str``.
            TelegramIntakeRecordError: If the record cannot be written, or the id
                factory kept minting an attempt already held.
        """
        ...

    async def claim_reply(self, update_id: int) -> str | None:
        """Answer the non-text message or stop command ``update_id`` carries, by its reply.

        One step that is both §5:8's "which non-text messages it answered" and
        §13:2's claim: from it the record holds the update answered, so it is never
        taken in, and a duplicate fetch sends no second fixed line (§5:9).

        **A stop command is answered here too** (ADR-0332 §8:6): the reader records it
        as an update it answered, as it records a non-text message, before it acts on
        it. The record holds no more of a stop than of any other answered update: its
        id, and the fixed reply's call record. So the reader tells a stop it has already
        acted on from a new one by :meth:`recorded`, read before this claim. An update
        the record holds as answered is a repeat, which stops nothing, and the claim
        then only retries a reply that came back retryable. It claims
        nothing, and answers ``None``, where the update was taken in, or where a
        fixed reply to it was already claimed and has not come back with a failure
        Telegram did not get or said it did not send — that is, where a reply is
        claimed with no outcome, was sent, may have been sent, or was refused for
        good. Where every earlier reply came back retryable
        (:attr:`~ai_assistant.core.types.TelegramFailure.retryable`, §6:3), it claims
        a new one, which is the retry.

        Args:
            update_id: The update the non-text message or the stop command came in,
                an ``int`` in ``[0, 2**63)``.

        Returns:
            The claimed record's attempt, or ``None`` where no reply may be sent.

        Raises:
            ValueError: Before any I/O, if ``update_id`` is not such an ``int``.
            TelegramIntakeRecordError: If the record cannot be written, or the id
                factory kept minting an attempt already held.
        """
        ...

    async def claim_interrupted(self, activation_id: str) -> str | None:
        """Claim the fixed message reporting that a restart cut ``activation_id`` off.

        §6:10's one message by rule, claimed once per activation, under the same rule
        as :meth:`claim_reply`: ``None`` where a message for the activation is
        claimed with no outcome, was sent, may have been, or was refused for good,
        and a new claim where every earlier one came back retryable. Which
        activation a restart cut off is the writer's to say.

        Args:
            activation_id: The activation the restart cut off.

        Returns:
            The claimed record's attempt, or ``None`` where no message may be sent.

        Raises:
            ValueError: Before any I/O, if ``activation_id`` is not a non-blank
                ``str``.
            TelegramIntakeRecordError: If the record cannot be written, or the id
                factory kept minting an attempt already held.
        """
        ...

    async def finish(self, attempt: str, outcome: TelegramOutcome) -> None:
        """Write a claimed call's outcome, once (§13:2).

        ``outcome`` is what the Bot API client returned for the call: done where it
        carries no failure, unknown where its failure is
        :attr:`~ai_assistant.core.types.TelegramFailure.UNKNOWN`, and not done
        otherwise. Where the call is a poll that came back done and carried an
        offset, Telegram has forgotten every update below it: the record no longer
        owes that confirmation, and drops those updates and the finished fixed
        replies to them (the class docstring's "What it keeps").

        Args:
            attempt: The attempt the call was claimed under.
            outcome: The outcome the client returned for it.

        Raises:
            ValueError: Before any I/O, if ``attempt`` is not a non-blank ``str`` or
                ``outcome`` is not a ``TelegramOutcome``.
            TelegramIntakeRecordError: If the record holds no call under
                ``attempt``, the call is already finished, or the record cannot be
                written. Nothing is written.
        """
        ...

    async def call(self, attempt: str) -> TelegramCallRecord | None:
        """Return the call record claimed under ``attempt``, or ``None``.

        ``None`` where the record holds no call under it: never claimed, or dropped
        once finished (the class docstring's "What it keeps").

        Raises:
            ValueError: Before any I/O, if ``attempt`` is not a non-blank ``str``.
            TelegramIntakeRecordError: If the record cannot be read, or the stored
                row is corrupt.
        """
        ...

    # --- the user's data rights (ADR-0004 §6) ---------------------------------------

    async def export(self) -> TelegramIntakeExport:
        """Return everything the record holds (ADR-0004 §6).

        The offset owed, every update held in update id ascending, and every call
        record held in claim order, finished or not.

        Raises:
            TelegramIntakeRecordError: If the record cannot be read, or a stored row
                is corrupt.
        """
        ...

    async def clear(self) -> int:
        """Erase everything the record holds, returning how many records went.

        Every update held and every call record count, claims with no outcome among
        them; the offset owed goes too and counts as none. Afterwards the record is
        as new.

        Raises:
            TelegramIntakeRecordError: If the record cannot be written.
        """
        ...


@runtime_checkable
class PersonModelStore(Protocol):
    """The only route to the person model (ADR-0338 §10:1).

    **What it holds** (§10:3): the people, keyed by id (§2:1); each one's profile of
    five set fields (§3:1) and its append-only change log (§3:5); the pins (§4:1) and
    the style marks (§5:3), each a pointer to a memory; and the observer's suggestions
    (§9:2, §9:5). No memory wording, no episode text and no copy of any record of
    another store: only those, and the ids of the memories and episodes they point at.
    So nothing here checks a memory: whether it is current, whether a pin would exceed
    the kept-in-mind slot's budget (§6:3) and whether it rests on outside content are
    each the caller's, against the memory store, before the write.

    **One person, the owner** (§2:1): the store holds exactly the person
    :data:`~ai_assistant.core.types.OWNER_PERSON_ID`, with the role ``owner``, created
    when the store is first created, and no member adds another before a decision on
    members (#691). Every member is keyed by a person's id all the same, and a write
    naming a person the store does not hold is refused ``unknown_person``.

    **Each member that writes does so in one atomic step** (§10:2), observing the
    store, deciding and writing against every other member, across processes as well
    as coroutines: a field's write records its change-log entry in the same step, and
    a write that takes a pending suggestion's field to its value, or pins its memory,
    marks the suggestion accepted in that step too (§8:9). A refused write writes
    nothing, and a write the contract says changes nothing writes nothing either
    (``unchanged``).

    **The writers are the callers'** (§3:4, §9:7): a field is written by the person, or
    the owner, on the panel or under the person's yes, and once by the hub's seed; the
    observer writes only suggestions and style marks. The store records the act it is
    handed and judges only what it holds.

    **Every read returns a detached snapshot**: the exchanged types are frozen pydantic
    models.

    Every member raises :class:`~ai_assistant.core.errors.PersonModelStoreError` for a
    store fault. A malformed argument is a ``ValueError``, raised before anything is
    read. Cancelling any member is governed by this module's cancellation clause
    (ADR-0060).

    A store under ADR-0326, in the hub's data directory and outside ``MemoryStore``'s
    contract (§10:1, §10:6), whose export carries every record it holds and whose
    clear erases them all (§10:5).

    **A BREAKING contract change under golden rule 5**, decided by ADR-0338 §10 and
    landing with its conformance suite, its canonical fake in :mod:`ai_assistant.testing`
    and its primary production caller, orchestration's person block (``CONTRIBUTING.md``
    → "Adding a Protocol", ADR-0137 §2).
    """

    async def read(self, person_id: str) -> PersonModel | None:
        """Read one person's model: their profile, change log, pins, marks and suggestions.

        Args:
            person_id: The person, by id.

        Returns:
            Their model, with every pin and mark, removed ones included, and the
            pending suggestions; ``None`` where the store holds no such person.

        Raises:
            ValueError: If ``person_id`` is blank.
            PersonModelStoreError: If the store cannot be read.
        """
        ...

    async def set_field(
        self,
        person_id: str,
        field: ProfileField,
        value: str | None,
        *,
        act: PersonModelAct,
    ) -> PersonModelWrite:
        """Set one field to ``value``, or clear it with ``None`` (ADR-0338 §3:2-§3:5).

        In one step: the value is validated (§3:2) — ``None`` clears the field, and any
        other value is text with a UTF-8 encoding, not blank, within the store's bound
        on a field's length, which a composition-root constant holds, and for a time
        zone a name ``zoneinfo`` resolves; the field is written; its
        change-log entry is appended with the old value, the new, the act and the
        instant; and every pending field suggestion of that field and value is marked
        accepted (§8:9). A value equal to the one held changes and logs nothing
        (§3:3), and still marks such a suggestion accepted.

        Args:
            person_id: Whose field.
            field: Which field.
            value: Its new value, or ``None`` to clear it.
            act: Who made the change, and how; never a suggestion's, which only
                :meth:`accept_suggestion` writes. A yes's act names the question part
                it spent or the request whose ticket ran the call (ADR-0362 §2:1).

        Returns:
            ``written``; ``unchanged``; or ``refused`` with ``unknown_person``,
            ``invalid_value`` and its reason, or ``invalid_act``.

        Raises:
            PersonModelStoreError: If the store cannot be read or written.
        """
        ...

    async def add_pin(
        self, person_id: str, memory_id: str, *, act: PersonModelAct
    ) -> PersonModelWrite:
        """Pin ``memory_id`` for ``person_id`` (ADR-0338 §4:1-§4:2).

        The caller has checked that the memory is current and that the slot's budget
        holds it (§4:2, §6:3). Pinning a memory the person already has a standing pin
        on changes nothing (§4:2). A pin marks every pending pin suggestion of that
        memory accepted in the same step (§8:9).

        Args:
            person_id: Whose pin.
            memory_id: The memory, by id.
            act: Who pinned it, and how: on the panel, or by a yes, naming the question
                part it spent or the request whose ticket ran the call (ADR-0362 §2:1).

        Returns:
            ``written`` with the new pin's id; ``unchanged`` with the standing pin's;
            or ``refused`` with ``unknown_person`` or ``invalid_act``.

        Raises:
            ValueError: If ``memory_id`` is blank.
            PersonModelStoreError: If the store cannot be read or written.
        """
        ...

    async def remove_pin(self, person_id: str, pin_id: str) -> PersonModelWrite:
        """Unpin: mark the pin removed, erasing nothing (ADR-0338 §4:7).

        Args:
            person_id: Whose pin.
            pin_id: The pin.

        Returns:
            ``written``; ``unchanged`` where it was already removed; or ``refused`` with
            ``unknown_person`` or ``unknown_record``.

        Raises:
            ValueError: If ``pin_id`` is blank.
            PersonModelStoreError: If the store cannot be read or written.
        """
        ...

    async def add_style_mark(self, person_id: str, memory_id: str) -> PersonModelWrite:
        """Mark ``memory_id`` as stating how the person wants Aether to speak (§5:3, §9:4).

        A memory already marked, or whose mark the person removed, is not marked again
        (``unchanged``).

        Args:
            person_id: Whose.
            memory_id: The memory, by id.

        Returns:
            ``written`` with the mark's id; ``unchanged`` with the existing mark's; or
            ``refused`` with ``unknown_person``.

        Raises:
            ValueError: If ``memory_id`` is blank.
            PersonModelStoreError: If the store cannot be read or written.
        """
        ...

    async def remove_style_mark(self, person_id: str, mark_id: str) -> PersonModelWrite:
        """Remove a style mark, keeping it as removed so it is never made again (§5:3).

        Args:
            person_id: Whose.
            mark_id: The mark.

        Returns:
            ``written``; ``unchanged`` where it was already removed; or ``refused`` with
            ``unknown_person`` or ``unknown_record``.

        Raises:
            ValueError: If ``mark_id`` is blank.
            PersonModelStoreError: If the store cannot be read or written.
        """
        ...

    async def record_suggestion(
        self, person_id: str, suggestion: ProposedSuggestion
    ) -> PersonModelWrite:
        """Record a suggestion as pending (ADR-0338 §9:2, §9:5).

        Not recorded (``unchanged``) where the profile already holds a field
        suggestion's value, a pin suggestion's memory has a standing pin, an equal
        suggestion is pending, or the person dismissed an equal one. A field
        suggestion's value is validated as a field's is (§9:2).

        Args:
            person_id: Whose.
            suggestion: What it proposes, and what it rests on.

        Returns:
            ``written`` with its id; ``unchanged`` with the equal suggestion's id where
            one stopped it; or ``refused`` with ``unknown_person`` or ``invalid_value``.

        Raises:
            PersonModelStoreError: If the store cannot be read or written.
        """
        ...

    async def accept_suggestion(
        self, person_id: str, suggestion_id: str, *, by: str
    ) -> PersonModelWrite:
        """Accept a pending suggestion: take its field to its value, or pin its memory.

        In one step. A field suggestion writes its field as an accepted suggestion,
        naming the episode it rests on, and logs the change; a pin suggestion pins its
        memory as made on the panel (ADR-0338 §4:1). Either marks the suggestion, and
        every pending one equal to it, accepted (§8:9). The caller has checked a pin's
        memory as :meth:`add_pin` requires. A field suggestion's value is validated
        again, as every field write is (§3:2), against the bound the store holds now,
        which may be tighter than the one it was recorded under: a value that fails is
        refused ``invalid_value`` with its reason, nothing is written, and the
        suggestion stays pending.

        Args:
            person_id: Whose.
            suggestion_id: The suggestion.
            by: The person accepting it, by id.

        Returns:
            ``written`` with the suggestion's id; or ``refused`` with
            ``unknown_person``, ``unknown_record``, ``already_decided``, or
            ``invalid_value`` and its reason.

        Raises:
            ValueError: If ``suggestion_id`` or ``by`` is blank.
            PersonModelStoreError: If the store cannot be read or written.
        """
        ...

    async def dismiss_suggestion(self, person_id: str, suggestion_id: str) -> PersonModelWrite:
        """Dismiss a pending suggestion, so an equal one is never recorded again (§9:2).

        Args:
            person_id: Whose.
            suggestion_id: The suggestion.

        Returns:
            ``written``; or ``refused`` with ``unknown_person``, ``unknown_record`` or
            ``already_decided``.

        Raises:
            ValueError: If ``suggestion_id`` is blank.
            PersonModelStoreError: If the store cannot be read or written.
        """
        ...

    async def export(self) -> PersonModelExport:
        """Return every record the store holds (ADR-0338 §10:5).

        Raises:
            PersonModelStoreError: If the store cannot be read.
        """
        ...

    async def clear(self) -> int:
        """Erase every record the store holds, returning how many went (ADR-0338 §10:5).

        Every person, profile, change-log entry, pin, mark and suggestion counts, the
        owner included: afterwards the store holds nothing.

        Raises:
            PersonModelStoreError: If the store cannot be written.
        """
        ...
