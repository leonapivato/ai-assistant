"""Exception hierarchy for the assistant.

All errors raised by the application inherit from :class:`AssistantError`, so
callers (and interface adapters) can catch the whole family with one handler.
Add new, specific subclasses rather than raising bare ``Exception``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from ai_assistant.core.types import encodable_text

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ToolCost, ToolFailure


class AssistantError(Exception):
    r"""Base class for every error raised by ai-assistant.

    **Its text is encodable, and its structured state says whether it survived
    delivery** (ADR-0085 §9, §10a). Both obligations arrive with the promoted
    engine surface, and both are properties of *this* class rather than of any
    subtype, so they are stated once here.

    **Every ``str`` an error carries validates as
    :data:`~ai_assistant.core.types.EncodableText`.** ADR-0085 §4c requires every
    string the promoted surface can carry to have a UTF-8 encoding, and an
    exception is where that is least obvious:
    ``UnresolvedEvidenceError("bad \ud800", ["\ud800"])`` constructed before this,
    and ADR-0085 §10a's reduction cannot rescue it — the reduction *measures* a
    payload, and measuring means encoding, so the failure lands before the rule
    that was meant to handle an oversized error. The declared exception would then
    reach a caller as an undeclared transport failure. ``core/errors.py`` is
    deliberately outside ``tests/core/test_text_encodability_coverage.py``'s reach
    (that check is scoped to ``core.types``), so this is held by
    :func:`~ai_assistant.core.types.encodable_text` running in the constructor and
    by a structural test over every subtype rather than by a field list.

    The message is validated here; a subtype carrying structured state validates
    its own strings, because only it knows which of its arguments are text.

    Attributes:
        details_elided: Whether this exception was reconstructed from an error
            payload whose structured state did not fit (ADR-0085 §10a). ``False``
            everywhere else, and in particular on every in-process raise, because
            nothing elides there. It exists so a client whose reconstruction lost
            an exception's structured state can say so instead of presenting an
            empty list as an empty answer: ``unresolved_ids`` defaults to ``()``,
            so a reconstructed :class:`UnresolvedEvidenceError` without the flag
            would tell a caller that *nothing* was unresolved at the exact moment
            that too much was. It is **transport metadata rather than exception
            state**, so it is excluded from the wire's ``details`` object and is
            carried by the frame's own ``reduced`` member.
    """

    def __init__(self, *args: object) -> None:
        r"""Create the error, refusing text that cannot be written down.

        Args:
            *args: The exception's arguments, as :class:`Exception` takes them.
                Every ``str`` among them is validated.

        Raises:
            ValueError: If any string argument has no UTF-8 encoding.
        """
        for arg in args:
            if isinstance(arg, str):
                encodable_text(arg)
        super().__init__(*args)
        self.details_elided: bool = False


class ConfigurationError(AssistantError):
    """Configuration is missing or invalid (e.g. a required secret is unset)."""


class IncompatibleStateError(AssistantError):
    """Persisted state this build cannot serve **correctly** (ADR-0083 §6).

    Raised by a store **at open**, and only when serving the state on disk would
    be *silently wrong* — answers a caller cannot tell from correct ones. It is
    deliberately **not** "this state is unfamiliar": state written by a different
    build that this one can still serve correctly is served, not refused
    (ADR-0064 §3 is the standing example, and §6 keeps it).

    **It is `AssistantError`-derived and not a store error, and that placement is
    the decision.** The first instance is :class:`SqliteMemoryStore`'s embedder
    mismatch, which refused correctly but as a ``MemoryStoreError`` — a subsystem
    error from below the disk line, so an entry point could not tell "this
    deployment cannot serve this store" from "this disk is broken" without
    matching on a message string. A resident hub must tell them apart: one is a
    deployment fault a human has to clear (exit ``78``, the supervisor stays
    down), the other may clear on its own (exit ``1``, the supervisor restarts).
    Raising a distinct class is what makes the mapping a type check rather than a
    string match.

    Nothing about *what* is detected, or *when*, changes with this class — so
    ADR-0024 §2's "owes no new migration contract" stays true, and automating the
    remedy remains ADR-0006 §4's and leg 7's.

    Attributes:
        expected: What this build requires of the state, as operator-readable
            text.
        found: What was actually on disk.
        operator_action: What a human must do before a restart can succeed. The
            hub prints this before exiting ``78`` (ADR-0083 §5), which is how "if
            the hub is not running, the reason is legible" is discharged for this
            class of fault.

    All three are operational text and carry **no Tier 0/1 content** (ADR-0004
    §5): they name settings keys, paths, model identifiers and dimensions —
    never memory content and never a conversation.
    """

    def __init__(self, message: str, *, expected: str, found: str, operator_action: str) -> None:
        """Record the mismatch and the remedy alongside the message.

        Args:
            message: The one-line summary, as any other error carries.
            expected: What this build requires of the state.
            found: What was actually on disk.
            operator_action: What a human must do before a restart can succeed.

        Raises:
            ValueError: If the message or any of the three has no UTF-8 encoding.
                :class:`AssistantError` validates the message; the structured state
                is validated here, because only this type knows which of its
                arguments are text (ADR-0085 §9's rule is over *every* string an
                error carries, not over the two that happen to be declared
                failures of a Protocol method).
        """
        super().__init__(message)
        self.expected = encodable_text(expected)
        self.found = encodable_text(found)
        self.operator_action = encodable_text(operator_action)


class ModelError(AssistantError):
    """A language-model provider failed or returned an unusable response.

    Subclasses narrow *why* the call failed so a caller can react to the cause
    rather than to one undifferentiated error. Two independent class attributes
    say what a caller may do about it:

    - ``retryable`` — would *this same call, to this same provider* plausibly
      succeed if repeated? True for a transient fault, false for one that would
      fail identically every time (bad credentials, a refused prompt).
    - ``routable`` — would *a different provider* plausibly succeed? True when
      the failure is a property of the provider we asked (its quota, its
      outage, its credentials), false when it is a property of the request
      itself and would travel with it.

    They are orthogonal, and the interesting cases are the ones where they
    disagree. An expired API key is not retryable — the same key is refused
    every time — but it is routable, because a different provider authenticates
    with a different credential. A prompt refused on content-policy grounds is
    neither: reissuing it changes nothing, and shopping it to another provider
    is not resilience.

    A bare ``ModelError`` remains valid for a failure that does not fit any
    subclass, and is conservatively treated as neither retryable nor routable.
    """

    retryable: ClassVar[bool] = False
    routable: ClassVar[bool] = False


class ModelAuthError(ModelError):
    """The provider rejected our credentials (HTTP 401/403).

    Not retryable: the same key will be refused again. Routable: credentials are
    per provider, so a different one may well accept the call — this is the
    clearest case of the two flags disagreeing.
    """

    routable: ClassVar[bool] = True


class ModelRateLimitError(ModelError):
    """The provider throttled the request (HTTP 429).

    Retryable, but only after a delay — retrying immediately will be throttled
    again. Honouring a provider-supplied ``Retry-After`` is deferred to the
    retry slice that consumes it. Routable: quota is per provider, so a
    fallback is not throttled by our usage of this one.
    """

    retryable: ClassVar[bool] = True
    routable: ClassVar[bool] = True


class ModelTimeoutError(ModelError):
    """The provider did not respond within the deadline (HTTP 408 or a timeout).

    Retryable: a subsequent attempt may well be served. Routable: a provider
    slow enough to miss the deadline is a reason to try a different one.
    """

    retryable: ClassVar[bool] = True
    routable: ClassVar[bool] = True


class ModelUnavailableError(ModelError):
    """The provider is unreachable or failing (HTTP 5xx, connection errors).

    Retryable: this is the provider's problem, not the request's. Routable for
    the same reason — an outage is the canonical case for a fallback.
    """

    retryable: ClassVar[bool] = True
    routable: ClassVar[bool] = True


class ModelContentFilterError(ModelError):
    """The provider refused the request or response on content-policy grounds.

    Neither retryable nor routable: the same prompt will be refused again, and
    re-sending it to another provider until one accepts is not resilience — it
    is shopping for a permissive filter. Falling back here would also widen the
    set of providers that see a prompt already flagged as sensitive, which
    ADR-0004 asks us not to do silently.
    """


class ModelResponseError(ModelError):
    """The provider replied, but the response was malformed or unusable.

    Not retryable by default: a response we cannot parse usually reflects a
    mismatch in what we asked for rather than a transient fault. Routable
    though — the mismatch is often with *this model's* capabilities, and
    another may answer usably.
    """

    routable: ClassVar[bool] = True


class EmbeddingDeadlineExpiredError(AssistantError):
    """An embedding call outlived its deadline (ADR-0118 §5).

    Raised by the bounded ``Embedder`` the composition root wires — every call
    through the embedding seam passes through it, so the store's writes, the
    store's ``search`` and the re-embedding migration are all bounded by one
    object (ADR-0118 §2, §8).

    **Its own class, and deliberately not a** :class:`ModelError`. ADR-0118 §5
    requires the condition to be "distinct from every class an embedder raises for
    a backend fault and from every class a store raises for a store fault", and
    ``ModelError`` is exactly what both shipped embedders raise for a backend
    fault — a missing vendored artifact, an unloadable model, a result that breaks
    the contract. Sitting under it would leave the one discrimination this class
    exists for to a message match, which ADR-0083 §6 records the cost of.
    :class:`ModelTimeoutError` is refused for the neighbouring reason ADR-0118
    names in terms: its documented subject is a *provider* that did not respond,
    and ``models/retry.py`` already gives it the job of telling our deadline from
    the provider's own. Overloading it would make one class mean both "the model
    provider timed out" and "the local embedding runtime wedged", which are
    different remedies.

    **A fault, never a refusal** (ADR-0118 §6). It is not in the class list
    ADR-0111 §9 reserves for refusals a deployment's configuration makes correct,
    and nothing makes it quieter on repetition. A refusal is correct behaviour
    under a configuration an operator chose; a wedged embedding backend is a hub
    that has stopped being able to remember anything, and it must read that way on
    the tenth interval as loudly as on the first.

    **The work is not known to have stopped.** The deadline stops the caller
    waiting; it cannot interrupt a synchronous worker (ADR-0118 §7, ADR-0029 §4).
    A caller may not assume the embedding did not happen — only that it did not
    answer in time.

    **A component that translates embedder faults into its own vocabulary
    translates this one distinguishably**, preserving it as the cause (ADR-0118
    §5's second clause). A discriminator that dies one frame above where it was
    raised is not a discriminator.

    It carries a message and nothing else, which is what lets it round-trip the
    wire from that message alone (ADR-0085 §10a).
    """


class MemoryStoreError(AssistantError):
    """Reading from or writing to long-term memory failed.

    Named ``MemoryStoreError`` rather than ``MemoryError`` to avoid shadowing
    the Python builtin of that name.
    """


class MemoryStoreConflictError(MemoryStoreError):
    """An ``INSERT_IF_ABSENT`` write's id already named a stored record (ADR-0046 §4).

    The batch was rolled back — nothing was written. The caller minted a
    colliding id and should re-mint and retry (ADR-0045 §4).

    Subclasses :class:`MemoryStoreError` so every existing ``except
    MemoryStoreError`` still catches it (the writer boundary documents
    ``MemoryStoreError`` as the only error that crosses the seam, ADR-0028 §5),
    while the applier catches the narrower conflict to distinguish "id collided,
    mint again" from "the store is broken, abort" — mirroring
    :class:`StaleExecutionError` under :class:`PlanningError`.
    """


class UnresolvedEvidenceError(MemoryStoreError):
    """A ``DERIVED`` proposal cited a record the store does not hold (ADR-0077 §5).

    Raised by ``MemoryWriter.ingest`` before any ruling is sought: nothing is
    written, and no decision is fabricated — a ruling is the policy's to make
    (ADR-0005 §3), so a writer inventing a ``REJECT`` would put a decision nobody
    made into the ingest result.

    Narrowed out of :class:`MemoryStoreError` for one caller and one question:
    **the ingesting stage cannot otherwise tell a race from a bug.** An episode is
    selected while live and the observing model call suspends for a round trip, so
    a citation can expire under its retention horizon — or be deleted with its
    conversation — between selection and the write. That is an ordinary
    consequence of a finite horizon, not a producer fault; against one
    undifferentiated class the stage either aborts a batch that was working, or
    swallows real faults to avoid doing so.

    :attr:`unresolved_ids` is what makes the discrimination possible. The writer
    sees only "this id does not resolve"; the stage compares those ids against the
    batch it selected. **Every** unresolved id inside that batch is the race — drop
    that proposal, count it, carry on with the rest. **Any** id outside it is the
    producer citing something it was never handed, and propagates. The quantifier
    is deliberate: a fault accompanied by an expiry is still a fault.

    **Additive, not a narrowing.** A subclass *is* a ``MemoryStoreError``, so
    every existing ``except MemoryStoreError`` still catches it and ADR-0028 §5's
    "``MemoryStoreError`` is what crosses this seam" stays true as written. It is
    precisely the distinguishable subclass ADR-0079 §4 named and left open, taken
    by the lane that has the consumer, in the shape
    :class:`UnknownConversationError` already has under
    :class:`ConversationStoreError`.
    """

    def __init__(self, message: str, unresolved_ids: Sequence[str] = ()) -> None:
        """Create the refusal, recording which citations failed to resolve.

        Args:
            message: What was refused and why, for a human reader.
            unresolved_ids: The cited ids the store does not hold, in the order
                they were cited. Snapshotted into a tuple, so a caller mutating
                the sequence it passed cannot rewrite the error after the fact.

        Raises:
            ValueError: If the message or any id has no UTF-8 encoding
                (:class:`AssistantError`).
        """
        super().__init__(message)
        self.unresolved_ids: tuple[str, ...] = tuple(
            encodable_text(unresolved) for unresolved in unresolved_ids
        )


class SelfConsumingWriteError(MemoryStoreError):
    """A ruling would install a proposal at an id that proposal cites (ADR-0081 §1).

    Refused between the policy's ruling and the write dispatch: nothing is
    written, no window is closed, and no decision is fabricated — a ruling is the
    policy's to make (ADR-0005 §3). The belief would otherwise stand as its own
    warrant, and a citation a write consumes cannot be presented honestly:
    ADR-0077 §6's tombstone is keyed on a citation *failing* to resolve, and here
    it resolves, to the record that replaced its referent.

    **This class is the arm where the destination was the producer's own choice**
    — ``ACCEPT`` and ``STORE_TEMPORARY`` install at ``proposed.id``, which the
    producer minted and the producer cited. Nothing outside the producer chose
    either value, so a refusal here is the bug ADR-0081 §Context describes and
    remains one. :class:`FoldOntoCitedRecordError` is the other arm.

    **Narrowed out of :class:`MemoryStoreError` for one caller and one question**,
    in :class:`UnresolvedEvidenceError`'s shape and for its kind of reason: a
    scheduled bulk producer cannot otherwise tell this refusal from a broken store
    without matching on a message, which ADR-0111 §9 forbids and ADR-0083 §6
    records the cost of. ADR-0081 §3 declined a subclass on the ground that there
    was "no caller with a second branch"; ADR-0116 §3 records that this ground has
    expired and replaces the ruling.

    **Additive, not a narrowing.** A subclass *is* a ``MemoryStoreError``, so every
    existing ``except MemoryStoreError`` still catches it and ADR-0028 §5's
    "``MemoryStoreError`` is what crosses this seam" stays true as written.
    """


class FoldOntoCitedRecordError(SelfConsumingWriteError):
    """...and the destination is the fold target the policy chose (ADR-0116 §2).

    ``REINFORCE`` installs at the ruling's ``target_id``, which the **policy**
    picked by conflict detection over the proposal's own content. A producer that
    generalises over the records it cites — a consolidator is the case ADR-0116 was
    written for — cannot foresee that pick, so a refusal here is a normal outcome
    of generalising rather than a producer fault.

    **This is the only arm a caller may continue past** (ADR-0116 §4). Catching it,
    a caller treats the refusal as a ruling on one proposal: it counts the
    proposal, carries on with the rest, and a walking job records its chunk as done
    (§5). Catching the *base* class to reach both arms is forbidden by the same
    section — it would absorb a producer bug into the path built for the case that
    is not one.

    Subclasses :class:`SelfConsumingWriteError` rather than sitting beside it, so a
    caller wanting the family rather than the arm has one name to catch, and
    ``except SelfConsumingWriteError`` keeps its plain meaning: *a write was refused
    for consuming its own citation*.
    """


class MemoryStoreEmbeddingExpiredError(MemoryStoreError):
    """An embedding this store awaited outlived its deadline (ADR-0118 §5).

    Raised where a ``memory/`` component translates an embedder fault into the
    store's error vocabulary — ``SqliteMemoryStore._embed_one`` and
    ``Reembedder._embed`` — with the :class:`EmbeddingDeadlineExpiredError` the
    bounded embedder raised kept as the ``__cause__``. It is the *translation* of
    that class, not a second name for it: the seam's own class does not subclass
    :class:`MemoryStoreError` and must not, because a store fault and an embedder
    fault are the two things ADR-0118 §5 asks a reader to tell apart.

    **This class exists because the first clause of §5 is not sufficient on its
    own.** Both translations above catch ``Exception`` and re-raise
    ``MemoryStoreError(f"embedder failed: {exc}")``, which flattened a well-classed
    timeout into the class a broken disk also raises — so §5's second clause is
    normative: "A component that translates an embedder fault into its own error
    vocabulary translates an expiry into a correspondingly distinct class of that
    vocabulary, preserving the original as the cause. The condition is legible at
    every boundary it crosses, or it is legible nowhere." A discriminator that dies
    one frame above where it was raised is not a discriminator.

    **Additive, not a narrowing.** A subclass *is* a ``MemoryStoreError``, so every
    existing ``except MemoryStoreError`` still catches it and ADR-0028 §5's
    "``MemoryStoreError`` is what crosses this seam" stays true as written — the
    shape :class:`MemoryStoreConflictError` and :class:`UnresolvedEvidenceError`
    already have.

    **The read path raises it too, not only the write path.** ``search`` embeds the
    query through the same ``_embed_one`` (ADR-0118 §8), so an interactive query
    whose embedding is pathologically slow fails with this class rather than never
    answering.

    **A fault, never a refusal** (ADR-0118 §6), inherited from the cause: a wedged
    embedding backend is a hub that has stopped being able to remember anything,
    and nothing here makes it quieter on repetition.

    **The work is not known to have stopped.** The deadline stops the caller
    waiting; it cannot interrupt a synchronous worker (ADR-0118 §7). A caller may
    not read this class as "the embedding did not happen" — only as "it did not
    answer in time". What *is* guaranteed is the store's own transactional
    promise, unchanged: the embedding is awaited before any lock is taken, so a
    write that raises this wrote nothing.

    It carries a message and nothing else, which is what lets it round-trip the
    wire from that message alone (ADR-0085 §10a).
    """


class ConversationStoreError(AssistantError):
    """Reading from or writing to the conversation index failed (ADR-0074 §9).

    Its own class in the :class:`AssistantError` hierarchy because a conversation
    is none of the things the existing errors name: not memory, not planning, not
    context, not audit. It covers a store fault, an id the store does not know —
    refused rather than silently created (ADR-0074 §1) — an append to a
    conversation stamped deleted (§8), a duplicate parked binding (§9.1), and a
    ``start`` whose id factory kept colliding until the retry budget ran out.

    A malformed *argument* is not this error: a paging value out of range is a
    ``ValueError``, inherited unchanged from ADR-0073 §2 rather than restated.
    """


class UnknownConversationError(ConversationStoreError):
    """The id named no conversation this store can operate on (ADR-0076 §2).

    Narrowed out of :class:`ConversationStoreError` for one caller and one
    question: **a sweep cannot otherwise tell "already done" from "broken".**
    Sweeper A enumerates conversation ``C``; sweeper B — or the deleting call, or
    a later scheduler — finishes ``C`` and drops it; A's next
    ``episodes_to_purge(C)`` then raises. Against one undifferentiated class A
    either aborts a start-up sweep that was working perfectly, or swallows real
    store faults to avoid doing so.

    So an enumerated id that is gone by the time the stage acts on it is a
    **no-op** — the sweep moves to the next id, because a conversation that is
    gone is a deletion that completed — while every other
    ``ConversationStoreError`` aborts the sweep and is reported. That is what makes
    a duplicated *walk* harmless, the half ``drop_if_eligible``'s re-check (which
    makes a duplicated *drop* harmless) does not cover.

    **Additive, not a narrowing of what ADR-0074 §9 promised**: a subclass *is* a
    ``ConversationStoreError``, so every existing ``except ConversationStoreError``
    still catches it and §9's "every method raises ``ConversationStoreError``"
    stays true as written. It is the shape :class:`MemoryStoreConflictError`
    already has under :class:`MemoryStoreError`, for the reason recorded there.

    Raised for an id the store does not know **as an operable conversation** —
    absent, or stamped deleted, which every presenting read already treats as
    absent (ADR-0074 §8). A store *fault* still raises the base class.
    """


class DeferralStoreError(AssistantError):
    """Reading from or writing to the deferred-question queue failed (ADR-0078 §2).

    Its own class in the :class:`AssistantError` hierarchy for the reason
    :class:`ConversationStoreError` is one: a deferred question is none of the
    things the existing errors name — not memory, not planning, not context, not
    audit. It is a *question about* a candidate belief, deliberately not a belief
    of any band (ADR-0078 §1), and it lives in a store of its own.

    It covers a store fault, an exhausted claim-token re-mint, and every
    caller-side fault around the re-deferral exemption: a ``predecessor_id``
    naming a live deferral whose claim the supplied token does not match, one that
    is no longer ``APPLYING`` or already names a successor, and a
    ``predecessor_id`` and a token that disagree about being present. Each of those
    would otherwise strand a claimed answer with no successor to name, which is the
    class of fault to surface rather than absorb.

    A malformed *argument* is not this error: a paging value out of range is a
    ``ValueError``, inherited from ADR-0073 §2 unchanged rather than restated.
    Where a method already has a spelling for absence or refusal — a ``None``
    return from ``get``/``claim``, the ``bool`` of ``resolve``/``delete`` — that
    spelling is used and nothing is raised.
    """


class NotificationStoreError(AssistantError):
    """Reading from or writing to the notification store failed (ADR-0130 §9).

    Its own class in the :class:`AssistantError` hierarchy for the reason
    :class:`DeferralStoreError` is one: a held notification is none of the things
    the existing errors name. It is a *proposal to volunteer something*, ruled by
    a deterministic policy and held in a store of its own, and a caller that
    wanted to catch a notification fault without also catching a memory one has
    no other way to say so.

    It covers a store fault and nothing else. A malformed *argument* is not this
    error: a paging value out of range is a ``ValueError``, inherited from
    ADR-0073 §2 unchanged rather than restated, and a candidate that the type
    itself refuses — a ``DataTier.SECRET`` sensitivity, an expiry that has
    already passed — raises from
    :class:`~ai_assistant.core.types.NotificationCandidate`'s own validator
    before any store is reached (ADR-0130 §2). Where a method has a spelling for
    absence or refusal — the ``None`` from a reconsideration that found nothing
    due, the ``bool`` of ``dismiss`` and ``delete`` — that spelling is used and
    nothing is raised.
    """


class NotificationOutboxError(AssistantError):
    """The delivery outbox could not commit what it was asked to (ADR-0131 §3b).

    Its own class in the shape :class:`MemoryStoreError`, :class:`DeferralStoreError`
    and :class:`TraceStoreError` already take, and for the reason §3b gives: the
    four members of :class:`~ai_assistant.core.types.NotificationEnqueue` are
    outcomes an offer *reached*, and a store that could not reach one at all is a
    fault rather than a fifth outcome. Without this type a disk-full or a
    transaction failure would fall outside every outcome, and a producer would
    receive an implementation exception with no contract telling it whether the
    notification had been taken.

    **No custody transfers when it is raised** (§3b). ADR-0131 §3 puts the
    transfer at the enqueue's single durable commit "and not before", so a caller
    that sees this error still holds the candidate, nothing was enqueued, the
    ADR-0130 record stays actionable, and the path may retry it — or leave it to
    §3b's startup reconciliation, which offers it again.

    ``next_notification`` declares it too, because applying an ``acknowledging``
    value writes to both stores (ADR-0131 §4). There it means the
    acknowledgement's **dismissal** did not commit: nothing is retired, and the
    caller may send the same value again. Once that dismissal has committed the
    acknowledgement has taken effect, and a failure of the entry's subsequent
    removal does not fail the call — the entry is departing, deliverable to
    nobody, and reconciliation completes the removal.
    """


class NotificationBudgetError(AssistantError):
    """A poll's ``budget`` is outside the range the hub honours (ADR-0131 §4).

    Negative, or above ``hub_max_notification_budget``. **Both ends need a
    refusal and only one is obvious**: ``timedelta`` admits zero and negative
    values and exceeds no maximum, so without this one implementation would
    return an empty result for ``timedelta(seconds=-1)`` and another would hand
    it to a timeout primitive and raise something undeclared. Zero is *not* an
    error — it is the immediate poll, the one out-of-range-looking value that
    means something (§4).

    **The hub does not silently clamp in either direction.** A client whose
    ninety-minute budget were honoured as ninety seconds would have been told, by
    acceptance, that its budget was accepted — which is ADR-0084 §2's argument
    against accepting-and-ignoring, transferred unchanged.

    **It carries no structured state, and that is a decision rather than an
    omission** (§4). ADR-0085 §10a requires an oversized error payload to travel
    with ``details: null`` and the client to reconstruct the declared exception
    with its structured state absent — a discipline
    :class:`OversizedValueError` pays because ADR-0084 §4 obliges it to carry the
    limit and the field. Nothing obliges this one: its two numbers are what a
    caller reads, not what a caller branches on, so they belong in the message,
    where §10a's reduction cannot strand them. An error with no ``details``
    object is one there is no reduced form of.

    It is an ordinary engine refusal, raised from an *argument*, so an in-process
    engine has everything it needs to raise it and a wire client's hub raises it
    from the same value — which is the substitutability ADR-0084 §5 promoted the
    façade to a Protocol for. ADR-0131 §2's poll conflict is the condition that
    could *not* meet that test, and it is a connection close rather than a second
    type here.
    """


class DeferralIdConflictError(DeferralStoreError):
    """A ``defer`` supplied an id a stored row already carries (ADR-0078 §2).

    Nothing was committed; the caller minted a colliding id and should re-mint and
    retry. "Already carries" is *physical presence* in ADR-0046 §3's sense rather
    than read-visibility, so a resolved or lapsed row still blocks the id.

    Narrowed out of :class:`DeferralStoreError` for one caller and one question:
    **a re-mint is the only correct response to this and the wrong response to
    everything else.** A caller that retried on an exhausted token draw or on a
    stranded-parent refusal would loop on a fault that will not change; one that
    did not re-mint here would drop a question over a bad dice roll.

    It is deliberately **not** what a same-question retry produces. Key idempotency
    is about the *question*: if the stored row's ``question_key`` equals the
    incoming one and still speaks for it, the id names a question that is still
    open — which is exactly what an uncertain admission retried under the same id
    produces — so the admission is suppressed instead. This error is for one id
    naming **two different questions**, which is the minting fault, and it takes
    precedence over suppression when both apply: a fault that is reported can be
    fixed, and one absorbed into a plausible-looking success is found later, by
    someone else.

    Subclasses :class:`DeferralStoreError`, so every ``except DeferralStoreError``
    still catches it — the shape :class:`MemoryStoreConflictError` has under
    :class:`MemoryStoreError`, for the reason recorded there.
    """


class TraceStoreError(AssistantError):
    """Reading from or writing to the evaluation-trace store failed (ADR-0119 §13b).

    Its own class in the :class:`AssistantError` hierarchy, mirroring
    :class:`MemoryStoreError`, because the trace store is a store of its own —
    the seventh SQLite database under ``Settings.data_dir`` (ADR-0119 §6), Tier 2
    where every other one named here is Tier 1.

    **It never reaches an emitter**, and that asymmetry is the whole of ADR-0119
    §5. ``TraceSink.emit`` swallows a store fault and logs it, because a failure
    to record a trace may not propagate into the operation being traced; only
    ``TraceStore.walk`` and ``TraceRetention.purge_before`` — a measure's read and
    the hub's sweep, neither of which is the work being observed — raise this.

    A malformed *argument* is not this error: a non-positive walk bound and a
    position the store cannot read are both ``ValueError``, mirroring ADR-0114
    §6a. A row the store cannot hydrate **is** this error, the row carrying no
    readable ``id`` included: minting a fresh one there would hand back a trace
    that no longer identifies the event it came from (ADR-0119 §3).
    """


class ContextError(AssistantError):
    """Situational context could not be assembled (e.g. a source-wiring bug)."""


class ReaderError(AssistantError):
    """A :class:`~ai_assistant.core.protocols.Reader` could not read its source.

    Raised when a read cannot complete **because of its source** — the file is
    missing, unreadable, or malformed — with the underlying failure preserved as
    ``__cause__`` (ADR-0093 §8, §10, under ADR-0095 §1's names). A reader may not
    let a source-level exception, an ``OSError`` or a parser's own class, cross the
    seam unwrapped: both consumers would then have to catch by *implementation* —
    knowing which exceptions each reader's parser can throw — and the alternative
    to that knowledge is a bare ``except Exception``, which swallows programming
    errors as degraded sources.

    **One class and not a family.** A missing file, a permission denial and a
    malformed document are the *same* fact to both consumers — the source could
    not be read — and they differ only in what an operator should do, which is what
    the cause and the log line carry. :class:`ContextError` is deliberately not
    reused: it is reserved for programmer/wiring bugs the assembler should not
    paper over (ADR-0008 §4), and a calendar file that is absent is neither.

    **A cancellation is never converted into one** (ADR-0093 §8). A cancelled read
    has, in plain English, "not completed", and a reader wrapping everything it
    catches would convert it — with the result that both consumers treat a
    caller's own cancellation as a degraded source, on a shutdown that was working
    correctly. ``read()`` is bound by ``core/protocols.py``'s cancellation clause
    exactly as every other seam is.

    **Its message is payload-free.** It carries the reader's declared identity and
    the failure's class, and never the source's location, its contents, or any
    string derived from either. ``raise ReaderError(str(exc)) from exc`` satisfies
    every word of the wrapping rule and, for a missing
    ``/home/alice/Private/therapy.ics``, produces a message that *is* that path —
    which the scheduler then writes to a log (ADR-0083 §7). That is Tier 1 data in
    an operational log, forbidden outright by ADR-0004 §5. The cause is retained on
    the exception; only its **class** may be logged, never its message.
    """


class ToolError(AssistantError):
    """An external tool failed to execute."""


class ToolRegistrationError(ToolError):
    """A tool could not be registered under the id it asked for (ADR-0016 §5).

    Raised when an id is already bound to a different definition, or has been
    deregistered. Tool metadata is a security control, so quietly overwriting
    ``risk_level=CRITICAL`` with ``LOW`` under an id a policy already trusts
    would be a privilege escalation with a lookup's ergonomics — and rebinding
    between approval and execution would let a step run against a definition
    the user never approved.
    """


class ToolBindingError(ToolError):
    """The call about to run is not the one that was authorised (ADR-0029 §1, §2).

    Raised by ``ToolInvoker.invoke`` when the call does not survive
    revalidation, when its ``tool.id`` is bound to nothing, when the definition
    it carries is not equal to the registry's own original, or when its decision
    does not authorise its request.

    All four are the same fault, and none of them is a tool failing — so none
    may be an ordinary ``FAILED`` :class:`~ai_assistant.core.types.ToolResult`
    an executor might retry. That is why this is raised where every other
    invocation outcome is returned: an exception has no
    ``failure.kind.retryable`` to read, so there is nothing for a retry decision
    to be made from (ADR-0029 §8).

    A revalidation failure carries the underlying ``ValidationError`` as its
    cause, the shape ADR-0026 §2 uses when ``core`` translates an arbitrary
    fault into its own error.
    """


class ClassifiedToolError(AssistantError):
    """A tool reporting a failure it classified itself (ADR-0032 §1).

    Raised by a ``ToolImplementation`` that knows *why* it failed, and caught by
    ``ToolInvoker.invoke``, which turns it into a
    :class:`~ai_assistant.core.types.ToolResult`. **It never escapes ``invoke``**
    — so no consumer of that Protocol catches it, and nothing about it is ever
    rendered into an error payload for the wire (ADR-0085 §10a).

    **Not a :class:`ToolError`**: that branch holds the seam's own faults, which
    an executor must never turn into a retryable result (ADR-0029 §8), and
    ``except ToolError`` is a plausible line for an executor or an interface
    adapter to write. This is the opposite — a value in flight, on its way to
    becoming one — so keeping it off that branch means the conflation is not
    available. :class:`AssistantError` still holds it, so this module's stated
    invariant is preserved.

    **Its home is ``core/errors.py`` and the decisive argument is the canonical
    fake.** ``ai_assistant.testing.invoker`` re-implements this seam's rules and
    must not import ``ai_assistant.tools`` (ADR-0031 §1); a ``tools/``-homed
    carrier would leave it importing that subsystem or declaring a second,
    structurally-equal exception type — and ``except`` keys on identity, so that
    divergence would be silent and total rather than a test failure.

    **It carries a constructed ``ToolFailure``, not a ``kind`` and a ``str``**, so
    that ``ToolFailure``'s own validators fire inside the tool's frame at the
    raise site, where the author can see them. That is the *ordinary* path and not
    a guarantee: ``model_construct`` bypasses every validator while still
    satisfying ``isinstance``, which is why ADR-0032 §6 has the seam revalidate
    the carrier rather than trust that the raise site did.

    **Nothing is passed to :class:`AssistantError`'s initialiser**, so ``args`` is
    empty and ``str()`` renders as nothing. ADR-0032 §5 forbids the seam to render
    anything derived from this object — ``str()``, ``repr()``, ``args``,
    ``__cause__``, ``__context__``, ``__notes__`` — into a message or a log, and a
    carrier holding no text is the form in which that rule cannot be broken by
    accident. What an operator reads is :attr:`failure`, which the seam passes
    through by value.

    ``raise ClassifiedToolError(...) from upstream`` is good practice and stays
    safe: the cause chain is what a developer wants in a traceback, and the seam
    renders no part of it.

    Attributes:
        failure: The classification, as the tool built it. Its ``kind`` is the
            tool's to choose from :class:`~ai_assistant.core.types.ToolFailureKind`
            except ``TIMED_OUT``, which is reserved to the seam's own deadline and
            refused (ADR-0032 §3); ``message`` is operator-facing **Tier 2** text
            the integration authors rather than copies from an upstream error body
            (ADR-0029 §3). It crosses by value and unedited, or is discarded whole.
        effect_may_have_committed: Whether this call's effect may already have
            landed upstream — a request that failed at the transport layer with no
            response, a connection reset, a client-side abort after the bytes went
            out. **Keyword-only and undefaulted**: the raiser answers it explicitly
            every time, because both candidate defaults are wrong in a direction
            (ADR-0032 §2). It is a *fact the seam rules on*, never the outcome: the
            seam answers ``INDETERMINATE`` only when this is true **and** the
            registry's own ``definition.interrupted_outcome`` is ``INDETERMINATE``,
            and ``FAILED`` otherwise — so a report can only make an outcome more
            ignorant, never less, and never reaches ``SUCCEEDED``.
        incurred_cost: What the call cost, as the tool reports it (ADR-0192 §5,
            ADR-0195 §3). **Keyword-only and defaulted to ``None``**, where
            ``effect_may_have_committed`` deliberately is not: silence about a
            price already means "no figure" and is the fail-closed direction under
            ADR-0194 §2, while silence about a side effect would assert one. A
            failed call may genuinely have been billed — an upstream that charged
            for a request it then rejected — and ADR-0194 §2 requires such a row to
            be counted. It states a price and **never** whether the effect
            committed; nothing infers either from the other.
    """

    def __init__(
        self,
        failure: ToolFailure,
        *,
        effect_may_have_committed: bool,
        incurred_cost: ToolCost | None = None,
    ) -> None:
        """Carry one classified failure across the invocation seam.

        Args:
            failure: The tool's own classification of why the call failed.
            effect_may_have_committed: Whether the effect may already have landed.
            incurred_cost: What the call cost, or ``None`` for no figure.
        """
        super().__init__()
        self.failure: ToolFailure = failure
        self.effect_may_have_committed: bool = effect_may_have_committed
        self.incurred_cost: ToolCost | None = incurred_cost


class PermissionDeniedError(AssistantError):
    """An action was blocked by the permission/policy layer."""


class AuditError(AssistantError):
    """A write to the permission audit trail was refused (ADR-0021 §4).

    The base for the refusals below, so a caller can handle "the trail would not
    accept this" with one handler. The trail is an *active* participant rather
    than a filing cabinet: it validates what it is asked to append, which means
    ``record`` has a failure mode every caller must handle. That cost is
    accepted because the alternative is a ``resolves`` pointer attesting that a
    user agreed to something they were never shown.
    """


class DuplicateDecisionError(AuditError):
    """A decision id already present in the trail was re-recorded (ADR-0021 §4).

    ``record`` is write-once, a deliberate departure from ``MemoryStore.add``'s
    upsert. Memory keys on ``id`` as the caller's idempotency key; an audit
    trail that upserts is one where history can be rewritten by replaying a
    write, which is the one property the trail exists to deny.
    """


class InvalidResolutionError(AuditError):
    """A decision's ``resolves`` pointer failed the trail's invariant (ADR-0021 §1).

    Raised when the referenced decision is absent, was not a ``CONFIRM``, has
    already been resolved, describes a different subject, was decided *after*
    the resolution claiming to answer it, or when the resolving ruling's
    ``authorised_by`` does not match its ``resolves``.

    Distinct from :class:`DuplicateDecisionError` because the caller's response
    differs: a duplicate id is a replayed write, whereas an invalid resolution
    is an answer that does not belong to the question it names — the
    substitution the pointer exists to prevent.
    """


class InvalidAuthorisationError(AuditError):
    """A decision's standing authorisation was not validated (ADR-0193 §6).

    Raised by :meth:`~ai_assistant.core.protocols.AuditTrail.record` on a
    **route-(b) egress decision** — a non-resolving ``ALLOW`` whose
    ``egress_binding`` is not ``None`` and whose ``authorised_by`` is set — where
    any of ADR-0193 §6's eight checks fails: the pointer named no outstanding
    grant; the grant it named does not cover the decision (a different
    ``ToolDefinition``, a different ``BoundAccount``, a destination set that does
    not contain every member of the decision's); the grant was not live as of the
    decision's own ``decided_at``; the binding is an ``OriginUnrecordedBinding``
    or carries ``planned_with_external_content``; the ruling's
    ``authorised_subject`` is unset or does not equal the digest ``record``
    recomputes from the record the store returned; or the seam could not be read.
    It is also raised on a **resolving** ``ALLOW`` carrying an
    ``authorised_subject`` at all, which is a decision claiming an authorisation
    of a kind it does not have.

    **Its own class beside** :class:`DuplicateDecisionError` **and**
    :class:`InvalidResolutionError`, for their reason: a replayed write, a
    substituted resolution subject and an unvalidated standing pointer are three
    facts an operator must be able to tell apart, and no lane widens
    :class:`InvalidResolutionError`'s stated subject to cover this one
    (ADR-0193 §6).

    **A store fault from the resolution seam arrives here too, chained.** Where
    :meth:`~ai_assistant.core.protocols.RecipientGrantResolution.outstanding`
    raises :class:`RecipientGrantError`, ``record`` refuses with this error raised
    ``from`` it — so a caller keeps the one :class:`AuditError` handler while an
    operator keeps the two facts apart, "the pointer named no outstanding grant"
    and "the seam could not be read", in the message and in ``__cause__``
    (ADR-0193 §6).
    """


class AuthorisationSpentError(AuditError):
    """A claim was refused because the authorisation it names is spent (ADR-0192 §1).

    An authorisation is *spendable* when the ``ToolDefinition`` its decision
    carries is ``side_effecting`` and its ``idempotency`` is not ``NATURAL``. On
    such a decision the ledger admits a first claim, and a further one only where
    ADR-0029 §5's retry conjunction has been transcribed onto the store: no claim
    open, none completed ``SUCCEEDED`` or ``INDETERMINATE``, the last completed
    ``FAILED`` with a retryable kind, ``KEYED``, and inside the window measured
    from the *first* claim.

    **This is the direction the consume fails in.** An open claim is an act that
    may have run at an outcome nobody observed, so it refuses the next claim
    rather than admitting one — including a retry ADR-0029 §5 would otherwise
    admit, whose third prerequisite is therefore that the preceding completion
    committed (ADR-0192 §1, §7).

    A seam fault: returned as no ``ToolResult``, never as data, and never
    auto-retried. Derives from :class:`AuditError` and not from ``ToolError``
    because the refusal is the store's.
    """


class UnrecordedAuthorisationError(AuditError):
    """A claim named an authority this trail did not record (ADR-0192 §1, §2).

    Raised where the store holds no decision under the id passed, where the
    decision it holds is **not equal** to the one passed — the whole value, by the
    frozen model's own equality — or where the stored decision's ruling outcome is
    not ``ALLOW``.

    **The three grounds are one class deliberately.** They are all "the authority
    this call claims is not one this store recorded", and separating them would
    tell a caller which half of a forgery was detected. The equality conjunct is
    what closes the attack ADR-0192 §1 names: an id lookup alone admits a caller
    who takes the id of a recorded, harmless ``ALLOW`` and builds a second
    ``ALLOW`` carrying that id and a dangerous ``ToolDefinition``, which would run
    and then be *misrecorded* as the harmless one.
    """


class InvalidCompletionError(AuditError):
    """A completion named no open claim (ADR-0192 §2).

    Raised where ``claim_id`` names no recorded claim, or names one a completion
    already names. A completion never raises
    :class:`UnrecordedAuthorisationError`: it names a claim, and the claim already
    names the decision.

    **``clear()`` is the one interleaving that makes this reachable in ordinary
    running** (ADR-0192 §6): an erasure landing between a claim and its completion
    leaves the completion naming nothing, and it is refused here exactly as any
    other completion naming no claim is. Nothing is recreated — the store putting
    back a row the user destroyed on purpose is the one answer it may not give.
    """


class SpendError(AssistantError):
    """A spend ceiling refused an invocation before it began (ADR-0194 §4).

    The base for the two refusals below, so a caller that only wants "the budget
    would not let this run" gets one handler. Both are **seam faults**: raised by
    :meth:`~ai_assistant.core.protocols.SpendGate.admit_invocation`, never
    returned as a :class:`~ai_assistant.core.types.ToolResult`, and never
    auto-retried.

    **Not a :class:`PermissionDeniedError`, and the corpus has drawn this line
    twice already.** That class means somebody was asked and said no. Here the
    recorded ruling *is* ``ALLOW`` — the user said yes about this call — and what
    refuses is arithmetic over a calendar period. Folding the two together would
    let a surface tell a user their answer was overruled when it was honoured and
    their month was spent, and would leave a trace unable to separate "you
    declined" from "you are out of budget" (ADR-0097 §7's reasoning one store
    over).

    **The refusal is an exit before the callable is entered**, so it falls in the
    window ADR-0034 §1 governs and qualifies on that section's second ground: the
    executor commits ``RUNNING -> FAILED`` and never retries, on the window and
    not on a list of classes.

    **No :class:`BaseException` that is not an ``Exception`` is ever translated
    into this hierarchy** (ADR-0194 §4). A ``CancelledError`` delivered from
    outside propagates unchanged: it is neither a refusal nor a budget fact, and
    ADR-0029 §4 and ADR-0031 already own how one is classified.
    """


class SpendCeilingError(SpendError):
    """A configured ceiling would have been crossed (ADR-0194 §4).

    Raised where the **projected** total — the period's accounted total, plus
    every reservation the gate is holding, plus this call's own declared cost —
    is strictly greater than a configured ceiling. A projection exactly equal to
    a ceiling is admitted, so this class never fires at equality.

    **Its message states the ceiling that was crossed, its period, its currency,
    the accounted total and the projected total.** The accounted figure alone
    would leave a user reading "90 against a ceiling of 100" beside a refusal and
    no way to see the reservations and the declaration that made 101. Where both
    configured ceilings are crossed by one projection, **one** error is raised
    naming **both**, in ``SpendPeriod``'s fixed order — ``CALENDAR_DAY`` then
    ``CALENDAR_MONTH`` — with each one's ceiling and total: naming only the day
    would tell a user to wait until tomorrow when their month is spent, and naming
    only the month would hide the nearer bound.

    **It is never raised for a spend that could not be measured.** A crossing is
    knowable only after every other ground has been ruled out, so this class never
    pre-empts :class:`SpendUndeterminedError` and a call that could not be
    measured is never reported as one that overspent.

    **The message is payload-free** (ADR-0194 §4, ADR-0093 §8's rule for
    ``SensorError``). It carries no argument value, no recipient, no account, no
    tool output and no digest of any of them: the error travels further than the
    call did, and the numbers are the whole explanation.
    """


class SpendUndeterminedError(SpendError):
    """The spend the admission needed could not be reduced to a number (ADR-0194 §4).

    Raised on exactly **six** grounds, evaluated in this order, the first that
    holds being the one the message names:

    1. the call's own declared ``ToolCost.amount`` is not countable (ADR-0194 §1);
    2. the call's own declared cost has no number at all — an ``UNKNOWN`` basis,
       or a cost in a currency other than the configured one — with no allowance
       configured (ADR-0194 §2);
    3. the injected clock raised;
    4. the store read failed;
    5. the period is indeterminate — an open claim in it, or a completion whose
       reported cost has no number this mechanism may add (ADR-0194 §2);
    6. the arithmetic trapped.

    **The order is not arbitrary and it is contract.** Without it two conforming
    implementations meeting a non-countable amount and a raising clock in the same
    call would send the operator to two different repairs. The first two are facts
    about the call and need no I/O, so they are decided before anything is read;
    the clock precedes the store because the period is what selects the rows;
    indeterminacy is a property of rows already read; and a trap can only arise
    once operands exist.

    **A separate class from :class:`SpendCeilingError` because the messages state
    different facts and one of them would otherwise be false.** None of these six
    crossed a ceiling — nothing measured one — so reporting one as a crossing
    would tell the user a number about their budget that nothing computed. It is
    also why no implementation substitutes a large stand-in amount for an unpriced
    cost: that stand-in would have to be a particular ``Decimal``, and two
    implementations picking different ones would refuse the same call while
    reporting different contract values.

    **What the message says.** Which of the six grounds applied, and the period
    only where one was determined — a clock that raised leaves no period to name,
    and the message says the clock failed rather than inventing one. Where the
    ground is an indeterminate period and **both** configured periods are
    indeterminate at once, it names both in ``SpendPeriod``'s fixed order, and it
    names only the periods that are both indeterminate and carrying a ceiling of
    their own. It states no amount, and it is payload-free on the same terms as
    the class above.

    **Also raised by
    :meth:`~ai_assistant.core.protocols.SpendLedger.spend_totals`**, but only
    where that member cannot produce its values at all — a failed store read or a
    raising clock. An indeterminate period is *returned* there, as
    ``accounted=None`` beside a present ``currency``, and never raised.
    """


class GrantError(AssistantError):
    """A source-grant store could not be read or written (ADR-0097 §10).

    The store fault, and the base for the refusal below, so a caller that only
    wants "the grant store could not answer" gets one handler.

    **A driver that cannot get an answer fails closed**, which is stated on the
    error because the tempting reading is the other one (ADR-0097 §5a). A
    :meth:`~ai_assistant.core.protocols.SourceGrants.live` that raises this is not
    a grant: before a read nothing is opened, and after a read the reading is
    discarded exactly as a withdrawn grant is. No driver may proceed on a stale
    answer, on the earlier of two lookups, or on an absent one. "The check failed,
    so carry on with what we already knew" is what an implementer writes when the
    alternative looks like losing a scheduled run, and it is the wrong trade twice
    over — the thing being protected is the user's personal files, and ADR-0016
    §4's ``UNKNOWN`` cost already rules this direction for the neighbouring case.

    **It propagates rather than being converted into**
    :class:`SourceNotGrantedError` (ADR-0097 §5a). A store fault and a withdrawn
    grant are different facts, and an operator must be able to tell them apart.
    """


class InvalidGrantError(GrantError):
    """A source-grant store refused the record it was handed (ADR-0097 §4, §10).

    Raised when ``record`` refuses: a duplicate id (the store is write-once), a
    second live grant for a source that already has one, a record that does not
    satisfy its own model, or a revocation failing any of ADR-0097 §4's
    invariants — naming a grant that is absent, is itself a revocation, is
    already revoked, names a different ``source``, or transcribes a different
    ``scope``.

    **One class rather than three**, deliberately unlike :class:`AuditError`'s
    split into :class:`DuplicateDecisionError` and
    :class:`InvalidResolutionError`. Those are separate because a replayed write
    and a substituted subject call for different handling; here the caller's
    recourse is identical in every case — read the store and construct a
    different record — so a family would be three names for one response
    (ADR-0097 §10).

    A **timestamp is never a ground for this refusal**, including a revocation
    that predates the grant it revokes. ``decided_at`` is caller-supplied and the
    store reads no clock, so a host clock corrected backwards would otherwise make
    a grant permanently unrevokable — the one property this contract exists to
    deliver, defeated by an invariant that was protecting nothing (ADR-0097 §4).
    """


class RecipientGrantError(AssistantError):
    """A recipient-grant store could not be read or written (ADR-0193 §1).

    The store fault, and the base for the refusal below, so a caller that only
    wants "the recipient-grant store could not answer" gets one handler.

    **A component that cannot get an answer from this seam fails closed**
    (ADR-0193 §1's last clause). A
    :meth:`~ai_assistant.core.protocols.RecipientGrants.covering` that raises this
    is **not** a grant: no policy proceeds on a stale answer, on an earlier lookup
    or on an absent one, and none reaches a route-(b) ``ALLOW``. That is
    :class:`GrantError`'s own clause read one store over, and the direction is the
    same one ADR-0016 §4's ``UNKNOWN`` cost already rules for the neighbouring
    case.

    **Deliberately not** :class:`GrantError`, whose stated subject is the
    *source*-grant store (ADR-0193 §1). One handler catching both would join the
    two seams ADR-0097 §7 keeps apart — a source grant may never authorise a send
    and a recipient grant may never authorise a read — and the two fail closed
    onto different things: a source fault stops a read of the user's files, and
    this one stops a send.
    """


class InvalidRecipientGrantError(RecipientGrantError):
    """A recipient-grant store refused the record it was handed (ADR-0193 §1).

    Raised by :meth:`~ai_assistant.core.protocols.RecipientGrantStore.record`: a
    duplicate id (the store is write-once), a **granting** record duplicating an
    outstanding grant's ``tool``, ``account`` and ``destinations``, a granting
    record that would take the count of outstanding granting records above
    ``Settings.recipient_grant_max_outstanding``, a record that does not satisfy
    its own model, or a revocation naming a grant that is absent, is itself a
    revoking record, is already revoked, or transcribes a different field.

    **One class rather than several**, on :class:`InvalidGrantError`'s reasoning
    and for its reason: the caller's recourse is identical in every refusing case
    — read the store and construct a different record — so a family would be
    several names for one response (ADR-0193 §1).

    **The count ceiling refuses rather than truncating**, and a **revoking** record
    is never refused on that ground whatever the count: a ceiling that could block
    a revocation would trap a user above it with no way down (ADR-0193 §1).

    A **timestamp is never a ground for this refusal on a revocation**, including
    one that predates the grant it revokes: ``decided_at`` is caller-supplied and
    this store reads no clock on the write path, so a host clock corrected
    backwards would otherwise make a grant permanently unrevokable (ADR-0193 §1).
    """


class SourceNotGrantedError(AssistantError):
    """A source was read for a use no live grant covers (ADR-0097 §5, §10).

    Raised by a **driver** — `orchestration`'s ingestion stage — not by the
    store, when an ingestion pass finds no live ``INGEST`` grant for the reader it
    was about to run. Nothing is opened: the source is not resolved, not opened
    and not parsed, because opening the user's calendar is the act the grant is
    about (ADR-0097 §5).

    **Never reported as a successful pass.** An ungranted pass reported as zero
    proposals is indistinguishable from "the source had nothing to say within the
    bound", which ADR-0093 §8 rules a *success* — so a deployment whose grant was
    revoked would look healthy while ingesting nothing.

    **And never a** :class:`ReaderError`, which means "the source could not be
    read": an operator debugging a missing calendar should not be sent to the
    filesystem for a fault that lives in the grant store.

    **Not** :class:`PermissionDeniedError`, whose docstring scopes it to an action
    blocked by the permission/policy layer and which ``orchestration/runner.py``
    raises when a confirmation was refused. ADR-0097 §7's whole content is that a
    source refusal and an action refusal are different subjects, and a caller that
    cannot tell them apart is one that will report "you declined to send that
    email" when the calendar was never granted.

    The facet path raises nothing: a facet whose source has no live ``FACET``
    grant is simply **absent**, as every optional-source fault is, and
    ``CurrentContext`` says nothing about why (ADR-0097 §5, ADR-0096 §4).
    """


class UngrantableSourceError(AssistantError):
    """A ``source`` names nothing the hub can offer a grant for (ADR-0102 §2a, §4).

    Raised by the engine's ``grant`` operation when a validated ``source`` is not
    admissible: no reader the hub holds declares it, the reader that declares it
    declares a name that is not in canonical form, or the reader's configured
    location exists and has no UTF-8 encoding so §6's disclosure cannot be made.
    Nothing is constructed from the value, and it reaches no store.

    **One class rather than three**, on ADR-0097 §10's own reasoning for keeping
    :class:`InvalidGrantError` single: "the caller's recourse is identical in all
    three". Here it is identical too — call ``grantable_sources`` and pick from what
    it returns — so a family would be three names for one response.

    **Not a subclass of** :class:`GrantError`, whose stated subject is a store that
    could not be read or written: this refusal never touches the store. And
    deliberately not named near :class:`SourceNotGrantedError`'s — that one is the
    driver-side "the user has not granted this source for this use", and
    a caller that could not tell it from "there is no such source" is one that will
    tell a user to grant something the hub cannot offer.

    **It carries a message and nothing else**, which is what makes it survive the
    wire. ``wire/errors.py`` reconstructs by resolving the class name over
    ``core.errors`` and calling it with the message positionally, so a class with no
    ``__init__`` round-trips from its message alone (ADR-0085 §10a) — and that is
    the shape §4's refusal rule wants anyway, since a refusal here may carry no
    filesystem path and may not echo a caller-supplied ``source``.

    **What the message may name** (ADR-0102 §4): a refusal raised because a *held*
    reader's declared name or configured location is inadmissible names that
    reader; one raised because no held reader declares the value names no value at
    all. A client that sent the value still has it, and the useful remedy is the
    enumeration rather than an echo.
    """


class ReadTrailError(AssistantError):
    """The source-read trail could not be written or read (ADR-0185 §12).

    Raised by a :class:`~ai_assistant.core.protocols.SourceReadRecorder` or a
    :class:`~ai_assistant.core.protocols.SourceReadTrail` when the store refuses a
    record — a duplicate id, or a record that does not satisfy its own model — or
    when the backend cannot be read or written at all.

    **One class rather than two**, unlike :class:`AuditError`'s split into
    :class:`DuplicateDecisionError` and :class:`InvalidResolutionError`, and unlike
    :class:`GrantError`/:class:`InvalidGrantError`. ADR-0185 §5 makes the driver's
    recourse identical however the write failed: **discard the reading** — nothing
    is proposed, no facet is contributed, no candidate is concluded. A caller that
    could tell a broken store from a duplicate id would do nothing different with
    the answer, so a family would be two names for one response. ADR-0185 §14 defers
    the split with the condition that fires it: the first consumer that retries one
    class and not the other.

    **A driver that cannot record fails closed, and that is what this error means
    to its catcher** (ADR-0185 §5). ADR-0004 §7 conditions *access* to Tier 0/1 data
    on a record of it, so a system that kept what it read when it could not record
    the reading would have kept Tier 1 data outside the trail its charter puts it
    in. The attempt is then left **unrecorded** — ADR-0185 §5a names that path
    explicitly and rules it a place the mechanism does not reach rather than a place
    the obligation does not apply — and what is guaranteed instead is the
    consequence: nothing durable, nothing in a prompt and nothing in a notification
    comes of a read the trail does not hold. No lane may cite that path as authority
    to leave a source access unrecorded.

    **Nothing durable records that the recorder itself failed**, and ADR-0185 §5
    says so plainly: the only durable place such a note could be written is the
    store that just refused the write. An operator learns of it through the driver's
    own failure posture — a logged fault under ADR-0083 §7 for a scheduled read, an
    absent facet under ADR-0008 §4 — which is a signal rather than a record and is
    not offered as one. ADR-0185 §14 defers the second, independent sink that would
    close it.
    """


class RoutingTrailError(AssistantError):
    """The routing trail could not be written or read (ADR-0197 §9).

    Raised by a :class:`~ai_assistant.core.protocols.RoutingRecorder` or a
    :class:`~ai_assistant.core.protocols.RoutingTrail` when the store refuses a row
    — a row id already held under a differing record, a ``route_id`` already held by
    a retained row of a different route, a sequence the route state machine does not
    admit, or a record that does not satisfy its own model — and when the backend
    cannot be read or written at all.

    **One class rather than several**, as :class:`ReadTrailError` is one class rather
    than two, and ADR-0197 §9 fixes it in as many words. The recourse is identical
    however the write failed: the act the row precedes **does not proceed**, the pass
    ends in :attr:`~ai_assistant.core.types.RouteOutcome.UNRECORDED`, and the
    operation is never called. A caller that could tell a broken store from a
    colliding ``route_id`` would do nothing different with the answer.

    **What this error means to its catcher is that nothing happened** (ADR-0197 §9).
    The row is written *before* the act it precedes, so a refusal here is a refusal
    to act: no belief is destroyed, no grant is withdrawn, no park is registered and
    no token is minted. That is the whole difference between
    :attr:`~ai_assistant.core.types.RouteOutcome.UNRECORDED` and
    :attr:`~ai_assistant.core.types.RouteOutcome.FAILED`, which states that the
    operation was called and raised — and a surface that rendered the two alike would
    tell a user their belief might be gone when this decision guarantees it is not.
    """


class PlanningError(AssistantError):
    """A request could not be turned into an executable plan.

    Also the base for the plan-execution faults below, so a caller can catch the
    whole planning family with one handler.
    """


class IllegalTransitionError(PlanningError):
    """A step transition is not legal from the step's current status (ADR-0014 §4).

    Raised by the execution tracker rather than tolerated, because the
    transition graph is what keeps execution state deterministic (VISION §7).
    """


class RetriesExhaustedError(PlanningError):
    """A step has used its retry budget and may not be claimed again.

    Distinct from :class:`IllegalTransitionError` because the caller's response
    differs: an illegal transition is a bug, whereas exhausted retries are an
    expected outcome the executor should surface rather than keep hammering.
    """


class StaleExecutionError(PlanningError):
    """A write lost the optimistic-concurrency race (ADR-0014 §5).

    The stored execution has advanced since the caller read it, so the write was
    computed against a state that no longer holds. The caller should re-read and
    retry. This is the failure that stops two workers from both claiming a step
    and running a non-idempotent tool twice.
    """


class ActiveExecutionError(PlanningError):
    """A destructive store operation was refused because work is in flight.

    Erasing an execution while a step is ``RUNNING`` would destroy the record
    the executor is about to commit against, leaving a side effect in the world
    with nothing recording it. The caller cancels the execution first, then
    retries (ADR-0014 §5).
    """


class UnknownContinuationError(PlanningError):
    """The continuation token names no parked step this engine can resume (ADR-0084 §7).

    ADR-0084 §7 ratified that presenting a token the server cannot resolve "yields
    one specific, typed refusal — an unknown-continuation error — and never a
    generic failure, and never a denial". Before this the engine raised a bare
    :class:`PlanningError`, indistinguishable from four other planning faults.

    **The cases it covers, as ADR-0198 §5 enumerates them** — the states the tree
    produces, rather than an inherited example (#1641):

    * an unknown handle;
    * a handle from a previous process life, after which the process-scoped handle
      table is empty;
    * a park ``pending_confirmations``' own reconciliation evicted because the trail
      no longer holds its binding pending (ADR-0052 §2);
    * a routed park already claimed, and an **expired routed** park, whose entry is
      evicted and whose slot is released so the token really does name nothing
      afterwards (ADR-0197 §7);
    * a settled record discarded under ADR-0198 §4's bound.

    **Two states are deliberately not among them.** The outstanding-confirmation
    ceiling **evicts nothing**: ``Engine._admit_and_reserve`` keeps the table bounded
    "without ever dropping a live continuation … at the ceiling the engine refuses to
    drive another step rather than parking one and having to strand it", raising
    before a park exists. And an ordinary parked step answered past its
    ``expires_at`` is refused by the runner's freshness check with
    :class:`PermissionDeniedError` before anything is authored, its park still
    registered — ADR-0084 §7 rules in terms that such a token "is not 'expired'",
    because collapsing the two "would tell a user their answer was too late when in
    fact the hub restarted".

    **A token whose binding the engine has settled and still retains is not one of
    these** (ADR-0198 §§1, 5). It is answered by a restatement of the recorded
    outcome instead, because the remedy differs: a token that names nothing is
    answered by enumerating ``pending_confirmations()`` and re-minting, and a token
    whose binding is settled is answered by reading what was decided — and ADR-0052
    §1 step 2 never lists a settled binding, so there is nothing to re-mint. Where
    the remedies coincide the error stays one, which is ADR-0084 §7's own test.

    **Never a denial**, and that is the distinction the type exists to keep: an
    unresolvable token means nobody ruled on the action, whereas
    :class:`PermissionDeniedError` means somebody did and said no. Reporting one as
    the other would tell a user their action was refused when it was merely
    forgotten.

    **A subclass of :class:`PlanningError` rather than of
    :class:`AssistantError` directly**, deliberately: every existing
    ``Raises: PlanningError`` contract on the engine surface stays true and a
    caller that already handles it keeps working, while a caller that wants
    ADR-0084 §7's specific remedy — enumerate ``pending_confirmations()`` and
    re-mint — can catch the thing that has that remedy.
    """


class OversizedValueError(AssistantError):
    """A call's payload is larger than the contract admits (ADR-0085 §8).

    ADR-0084 §4 makes the size limit "part of the promoted Protocol's declared
    contract, not a property of the transport, and *every* implementation enforces
    it" — so a client is never silently less capable than the engine it stands in
    for, in either direction. ADR-0085 §8c fixes the number and its subject: the
    limit is ``hub_max_frame_bytes`` less a 512-byte envelope reserve, applied to
    the **whole serialised payload** rather than to any one value, measured as the
    byte length of ADR-0087's canonical UTF-8 JSON encoding of it.

    **It is declared by every method on that surface**, because no method is
    provably inside the bound: :data:`~ai_assistant.core.types.Identifier` carries
    no maximum length, so even ``forget(record_id=…)`` can be handed an oversized
    argument, and every enumerating method's result grows with ``limit``.

    **The error payload is the one class that is reduced rather than refused**
    (ADR-0085 §10a): answering an oversized *error* with another error would
    recurse, and would mislabel — what was too large was the diagnosis, not the
    value the caller sent.

    Attributes:
        limit: The contract limit in bytes, so "too large" comes with a number a
            caller can act on.
        size: The payload's measured size in bytes, under the same encoding.
        field: The top-level member of the payload whose own canonical encoding is
            longest, ties broken by the member name's bytes in ascending order, or
            ``None`` where the payload has no named members. **Top-level only, and
            no path syntax**: naming ``utterance`` or ``evidence`` is what a caller
            needs to act, and ``proposals[3].evidence[7].content`` is not enough
            better to be worth a grammar and its escaping rules. The ``None`` case
            is reachable rather than defensive — an oversized ``beliefs`` page is a
            bare JSON array with no member to name, and a ``forget`` result a bare
            ``true``.

    ADR-0084 §4 asks for "the field that exceeded it"; under a payload-level bound
    no single field *exceeds* the limit — the payload does — so the faithful
    reading is the field that contributed most to exceeding it, which is what
    :attr:`field` names. Naming it by a rule rather than by judgement is what keeps
    two implementations from reconstructing different errors for one payload.
    """

    def __init__(self, message: str, *, limit: int, size: int, field: str | None = None) -> None:
        """Create the refusal, carrying the number and the largest contributor.

        Args:
            message: What was refused and why, for a human reader.
            limit: The contract limit in bytes.
            size: The payload's measured size in bytes.
            field: The largest contributing top-level member, or ``None`` where the
                payload has no named members.

        Raises:
            ValueError: If the message or ``field`` has no UTF-8 encoding
                (:class:`AssistantError`).
        """
        super().__init__(message)
        self.limit = limit
        self.size = size
        self.field = None if field is None else encodable_text(field)


class SecretStoreError(AssistantError):
    """A keyring operation failed (ADR-0125 §6).

    Its own class rather than a member of an existing family: the keyring is not
    a store under ``Settings.data_dir``, it is an operating-system service with
    its own custody, and ADR-0004 §3 keeps Tier 0 in it and out of every database
    named elsewhere in this module.

    **Absence is never this error.** An unset name is a ``None`` from
    :meth:`~ai_assistant.core.protocols.Secrets.get` and a ``False`` from
    :meth:`~ai_assistant.core.protocols.SecretStore.delete`, and neither raises
    (ADR-0125 §4, §6). Confusing the two is the failure §7 spends its longest
    argument on, and :class:`SecretStoreUnavailableError` is what keeps them
    apart.

    **A malformed argument is not this error either.** A key outside §2's
    grammar, a blank or oversized value, and a name for another scope are all
    ``ValueError`` — ADR-0073 §2's spelling, inherited unchanged — because
    nothing about the store failed (§6). Every method raises them *before* the
    keyring is touched, so a caller that gets this one knows the backend was
    reached and answered badly.

    **No secret reaches it.** Neither this exception's message, nor its
    arguments, nor its ``repr``, nor any log line an implementation emits
    alongside it may contain a secret value or anything derived from one — a
    prefix, a suffix, a truncation, a digest, or its length (ADR-0125 §6). The
    :class:`~ai_assistant.core.types.SecretName` may appear in all of them, and
    should: diagnosing a keyring fault requires saying which entry it was about.
    The obvious wrapper is the leak — a backend that names the value it rejected,
    re-raised as ``SecretStoreError(str(exc))``, writes the credential into an
    error that ``core/logging.py``'s redaction cannot catch, because that
    processor redacts by key name rather than by content.
    """


class SecretStoreUnavailableError(SecretStoreError):
    """The keyring cannot be reached on this machine at all (ADR-0125 §7).

    No backend is available, or the backend is present and locked with no unlock
    possible in this session. Absent, locked and headless are deliberately **one
    visible state**: what they have in common is that no call can succeed until a
    human acts, and telling them apart would tell a caller more about the
    machine's state than it is entitled to ask.

    Narrowed out of :class:`SecretStoreError` for the reason this module narrows
    anywhere — **the correct response differs**, which is
    :class:`IncompatibleStateError`'s own argument applied to a second fault. A
    keyring that is absent or locked is a deployment condition a human clears, so
    retrying is futile and the operator has to be told; a write the backend
    rejected may be transient. It subclasses rather than sits beside, as
    :class:`MemoryStoreConflictError` and :class:`DeferralIdConflictError` do, so
    a caller that only wants "the secret is not available" writes one handler.

    **``get`` never returns ``None`` for this condition**, and that clause is the
    reason this class exists. If an unreachable keyring answered ``None``, "this
    device is not enrolled" and "this device's keyring is locked" would be one
    observation: a client would report the owner as unenrolled while they are
    enrolled, and an enrolment flow reading ``None`` as a first run could mint a
    replacement credential and, under ADR-0124 §6's uniqueness clause, revoke the
    working one — a locked keyring turned into a revocation nobody asked for.

    **An argument fault still wins.** A malformed name or value, or a
    well-formed name outside the instance's bound scope, raises ``ValueError``
    whatever the keyring's state, including when there is no backend at all
    (ADR-0125 §7). Reporting the machine's state to a caller who also passed a
    bad name would hide the one fault that call will keep hitting after the
    operator installs a keyring — and a tool reaching for the device credential
    must be refused identically whether the keyring is locked, absent or wide
    open.

    **The message states the condition in terms the operator can act on** —
    which backend was looked for and what was found — and never in terms of a
    value (§7).
    """


# --- connections: the seven failures of a provisioning act (ADR-0151 §2a) ----
# Six outcomes and seven classes. The count is the subject's rather than the
# design's: ADR-0148 §6 gives a provisioning act three writes and three
# displacement points, and ADR-0149 §5 and §8 give it a deletion that can outlive
# its own success — so a caller owes the user six different sentences with six
# different next steps, and no two of them are interchangeable. A surface that
# collapsed any pair would tell a user their credential was unused when it was
# live, or send them to re-run an act that had already worked.
#
# **A class rather than a field, for each of them** (ADR-0151 §7, §8): the
# distinction a caller must not miss belongs in the type they catch, because a
# field is what an inattentive client renders past.
#
# **No class here names the supplied identity, the supplied credential, any part
# or derivation of either, or a filesystem path** (ADR-0151 §2a). The identity is
# Tier 1 personal data (ADR-0149 §3) and the credential is Tier 0; what a refusal
# on this surface names is the *reference*, which ADR-0149 §3 rules a non-secret
# handle chosen by code and licenses to be logged.


class UnusableIdentityError(AssistantError):
    """The account identity supplied with a provisioning act is refused (ADR-0151 §5).

    One class for four refusals, on the same test: the identity equals the
    plaintext of the credential supplied in the same call, it carries a Unicode
    control character or a line break, or its UTF-8 encoding exceeds
    :data:`~ai_assistant.core.types.ACCOUNT_IDENTITY_MAX_BYTES`. In every case the
    recourse is to supply a different identity, so one class is right and three
    would be surface with no consumer (ADR-0097 §10's rule, applied here).

    **Raised locally, before any I/O, by every implementation of
    ``connect_account`` and ``reprovision_account`` — the client included.** Both
    implementations therefore refuse the same values without a round trip and
    neither is silently more permissive (ADR-0085 §9). No such call reaches the
    hub, and no credential is sent for one — which is the property that matters
    most here, because the refused call is one of the two that carry a Tier 0
    value.

    **An** :class:`AssistantError` **rather than ADR-0085 §9's ``ValueError``,
    and the distinction is §9's own.** A ``ValueError`` there is "a caller
    programming error rather than a condition of the system" — a blank id, a
    non-positive ``limit``. An identity is a value the *user typed*, and a person
    pasting a token into the wrong field has not made a programming error: a
    client needs to render the refusal, and ``wire/server.py`` converts an
    ``AssistantError`` into an error frame while letting anything else close the
    connection. A dropped socket is the worst available outcome on the one call
    that carries a credential, because the natural client response to a dropped
    socket is to retry it.

    **The message names neither value, no part of either, and no length of
    either** (ADR-0151 §5). It says which rule was broken and nothing about what
    broke it.

    It carries no structured state and in particular **no reference**: the
    refusal happens before any write, so ``connect_account`` has none to name
    (§3's mint produces one only as the first record is written) and
    ``reprovision_account``'s caller already holds the one they supplied.
    """


class ConnectionStoreError(AssistantError):
    """The connection store could not be read or written (ADR-0151 §2a).

    The per-store class this corpus writes for every durable store —
    :class:`MemoryStoreError`, :class:`ConversationStoreError`,
    :class:`DeferralStoreError`, :class:`NotificationStoreError`,
    :class:`TraceStoreError`, :class:`GrantError` — arriving for the seventh
    (ADR-0149 §3). Declared by all five connection operations, because all five
    read or write the store.

    **Raised by a provisioning act it leaves the act's outcome *not known*.**
    ADR-0151 §7 classifies by two facts the act knows, and this is the class for a
    failure *before the act's own first write returns*: whether that write landed
    cannot be asserted, so a reference may or may not exist. The client reports it
    as not known — never as landed and never as not landed — and resolves it by
    reading ``connected_accounts`` once the store is readable (ADR-0139 §4).

    **It carries no reference, because there may be none to carry.** That is the
    one place this class differs from :class:`ProvisioningOutcomeUnknownError`,
    which asserts the reference exists and asserts nothing else.
    """


class UnknownConnectionError(ConnectionStoreError):
    """``reprovision_account`` named a reference the store does not hold (ADR-0151 §2a).

    What the corpus does for "you named something this store does not hold",
    after :class:`UnknownConversationError` and :class:`UnknownContinuationError`.
    Refused before the first write, so nothing is written.

    **It reaches ``reprovision_account`` only.** ``disconnect_account`` on an
    unheld reference is not an error at all — it returns ``None``, which says one
    thing: no live record was removed by this call (ADR-0151 §8) — and
    ``connect_account`` names nothing, because its reference is minted and cannot
    be aimed at an existing record (ADR-0151 §3).

    A subclass of :class:`ConnectionStoreError` so a caller that only wants "the
    connection store could not answer" writes one handler, in the shape
    :class:`UnknownConversationError` already has under
    :class:`ConversationStoreError`.
    """


class DisplacedProvisioningError(ConnectionStoreError):
    """Another act took the connection record over (ADR-0151 §2a, §7).

    ADR-0148 §6 gives a provisioning act three points at which another act can
    take the record from it — the taking compare-and-swap, the re-read before the
    credential write, and the activation's own compare-and-swap — and all three
    end the same way for the caller: **no record this act wrote is the
    reference's live one**, and the recourse is to read ``connected_accounts`` and
    decide whether to run the act again. One class covers them because the
    caller's recourse is identical (ADR-0097 §10).

    **It does not mean the act wrote nothing**, and ADR-0151 §7 is careful about
    that because an earlier draft got it wrong. ADR-0148 §6's "never held it and
    writes nothing" is scoped by its own words to an act whose *taking*
    compare-and-swap fails; the re-read and activation clauses displace an act
    that has already appended its pending entry and may already have written its
    credential, which §6 then rules lands "in that act's own slot". So depending
    on the point, the store may hold that act's own pending entry at its own
    revision and the keyring may hold a credential in that act's own slot.
    Neither is read by any call, both are named by the store, and both are
    removed by a disconnection of that reference and by ADR-0149 §8's purge.

    **No client presents it as having left the store unchanged, as having rolled
    anything back, or as a reason to retry the same act blind** (ADR-0151 §7). It
    reports the act as not performed and the reference's state as unread.

    No operation performs a liveness pre-check to narrow the window, because a
    pre-check narrows and does not close it while inviting a reader to believe it
    had.
    """


class IncompleteProvisioningError(AssistantError):
    """A provisioning act did not complete, and its reference exists (ADR-0151 §7).

    It asserts **exactly two things**. The reference it carries *exists* in the
    connection store, because this act's own first write landed and ADR-0149 §3's
    store is append-only. And *this act did not complete*, because no activation
    of it landed, so nothing it wrote is or ever becomes the live credential.

    It asserts **nothing** about the reference's live record at the moment it is
    caught: this act's record may still be live and pending, or a later act may
    have displaced it, and the store is what says which. A client names the
    reference, says the act did not complete, says the reference's state is
    unread, and offers ``reprovision_account`` or ``disconnect_account`` on it —
    both safe whoever now owns the record, the first by its own compare-and-swap
    and the second by being idempotent (ADR-0149 §5). **No client reports the call
    as having changed nothing.**

    Raised where the credential write fails, where either of ADR-0148 §6's two
    re-reads fails, and where an activation's compare-and-swap is *observed not to
    land* other than by a later act holding the record (ADR-0151 §7). A keyring
    failure at the credential write is **converted** into this class with the
    underlying :class:`SecretStoreError` chained as the cause: the raw class says
    the keyring failed and says nothing about which of the three writes had
    landed, and the two answers are opposite (ADR-0151 §2a).
    """

    def __init__(self, message: str, reference: str = "") -> None:
        """Create the failure, recording which reference the act was on.

        Args:
            message: What did not complete, for a human reader. **Sized by its
                raiser** so that the whole error payload — the code, this message
                and the one ``details`` member — fits the budget
                ``hub_max_frame_bytes`` leaves at its 1024-byte floor (ADR-0151
                §11, ADR-0085 §8c, §8d). ADR-0085 §10a nulls ``details`` before it
                truncates a message, so a payload that has to be reduced is one
                that arrives without its reference — and on the two classes
                ``connect_account`` raises, that is the only handle the caller
                will ever have, because the mint made it.
            reference: The connection reference whose record this act wrote.
                Defaults to the empty string so a *reduced* delivery still
                reconstructs (ADR-0085 §10a); ``details_elided`` is what tells such
                a caller the value was lost, rather than an empty one reading as an
                answer.

        Raises:
            ValueError: If either string has no UTF-8 encoding
                (:class:`AssistantError`).
        """
        super().__init__(message)
        self.reference: str = encodable_text(reference)


class ProvisioningOutcomeUnknownError(AssistantError):
    """A provisioning act's activation failed rather than returning (ADR-0151 §7).

    It asserts that the reference it carries **exists** and asserts **nothing
    else**: the store may have committed the compare-and-swap and failed before
    saying so, so neither completion nor incompletion may be asserted — the act
    may have completed, or may have left the record pending.

    The client names the reference, says the outcome is not known, and resolves it
    by reading ``connected_accounts`` — **never by re-running the act on the
    assumption it failed**, which would rotate a credential that may already be
    live. Both remedies stay available afterwards, whichever the read shows.

    **The activation is a connection-store write, not a keyring one** (ADR-0148
    §6), so ADR-0151 §2a's keyring-conversion clause does not reach it and no lane
    reads it as doing so.
    """

    def __init__(self, message: str, reference: str = "") -> None:
        """Create the failure, recording which reference the act was on.

        Args:
            message: What outcome is unknown, for a human reader. Sized by its
                raiser for :class:`IncompleteProvisioningError`'s reason — and this
                is the widest of the three codes at 31 bytes, which is the one the
                shared message bound is sized against (ADR-0151 §11).
            reference: The connection reference the act was on. Defaults to the
                empty string so a reduced delivery still reconstructs.

        Raises:
            ValueError: If either string has no UTF-8 encoding
                (:class:`AssistantError`).
        """
        super().__init__(message)
        self.reference: str = encodable_text(reference)


class ResidualCredentialError(AssistantError):
    """The act completed and a credential it was to delete did not go (ADR-0151 §7, §8).

    **The act it was raised by completed.** After ``reprovision_account`` the
    reference is connected at the new revision; after ``disconnect_account`` the
    reference has no live record. What failed is a deletion of a credential the
    act was to remove — the predecessor's slot (ADR-0148 §6) or the
    disconnection's deletion pass (ADR-0149 §5) — so an unreferenced credential
    remains, named by the store, read by no call, and reachable by a re-run of
    ``disconnect_account`` and by ADR-0149 §8's purge. **No client reports it as a
    failed connection or a failed disconnection.**

    **Raising rather than reporting a residue in a field is ADR-0149 §5's own
    requirement doing the choosing**: §5 says the failure "is reported and never
    suppressed", and a boolean field saying the deletion did not complete is
    exactly what an inattentive client suppresses — it renders the success and
    drops the flag — whereas an exception cannot be ignored without being caught,
    and a catch is a line a reviewer reads. The cost is that an operation both
    succeeds and raises, which is unusual enough that ADR-0151 §7 and §8 say
    precisely what a caller may conclude from it.

    A keyring failure at either deletion is **converted** into this class with the
    underlying :class:`SecretStoreError` chained as the cause (ADR-0151 §2a). The
    conversion is what makes the outcome answerable from the class rather than
    from a rule about ordering: ADR-0148 §6's predecessor-slot deletion happens
    *after* the activation, so a keyring failure there arrives with all three
    writes landed and the record active — and a client deriving the answer from
    the write order would report a live connection as pending and rotate a
    credential that was working.
    """

    def __init__(self, message: str, reference: str = "") -> None:
        """Create the failure, recording which reference the act was on.

        Args:
            message: Which deletion did not complete, for a human reader. Sized
                by its raiser for :class:`IncompleteProvisioningError`'s reason.
            reference: The connection reference the act was on. Defaults to the
                empty string so a reduced delivery still reconstructs. It is
                inside ADR-0151 §11's bound although its caller supplied it,
                because that clause is stated over *the class* rather than over
                which references are re-suppliable.

        Raises:
            ValueError: If either string has no UTF-8 encoding
                (:class:`AssistantError`).
        """
        super().__init__(message)
        self.reference: str = encodable_text(reference)


class EgressBindingError(AssistantError):
    """This call cannot be bound, so no ruling is sought for it (ADR-0152 §9).

    The one refusal class both members of
    :class:`~ai_assistant.core.protocols.EgressBinder` raise, and ADR-0152 §9 adds
    no other and no subclass of it. Every refusal ADR-0152 §6, §7 and §8 states
    ends here: a declaration that cannot describe the call, a destination with no
    canonical form, an argument the schema never statically named, a reference
    that is not connectable, a definition unequal to its registered original, a
    resumed binding unequal to the one that was approved.

    **One class rather than a family, on ADR-0145 §4's argument.** ADR-0151 §2a
    declares seven classes for five operations because a caller acts differently
    on each; here it does not. Every refusal ends the turn having disclosed
    nothing, asked nobody, written nothing and claimed nothing, and every one of
    them is corrected the same way — by a different call or a corrected
    declaration. "A second member would be a distinction visible to a client that
    cannot act on it differently."

    **Raised, never returned** (ADR-0152 §9). The return type carries a
    :class:`~ai_assistant.core.types.BoundEgressCall` or ``None``, and neither can
    express "this call cannot be completed"; ``None`` is ADR-0152 §8's answer for
    a call that is not an egress call at all and never signals a failure.

    **It carries no structured state**: no reference, no argument name, no
    destination, no tier and no count. What a refusal says is its message, bound
    by ADR-0152 §11 — which permits the tool id, an argument name the bound tool's
    declaration statically names, a zero-based index, a count, a field name, an
    error type and the connection reference, and permits nothing else.

    **A :class:`ConnectionStoreError` is never translated into this class**
    (ADR-0152 §9). A store that could not be read asserts nothing about the call:
    it may be perfectly bindable a second later, and the remedy is not a different
    call. It propagates out of the runner stage unconverted, as
    :class:`AuditError` and :class:`PlanningError` already do for an
    infrastructure fault rather than a step outcome. So does a ``RecursionError``
    raised while an argument is revalidated (ADR-0152 §12, issue #1107): this
    class is promised for a chained ``ValidationError`` and for nothing else.
    """


class TransportError(AssistantError):
    """A connection could not be made or could not be continued (ADR-0191 §1).

    What :meth:`~ai_assistant.core.protocols.OutboundTransport.open_channel` and
    every I/O-bearing method of :class:`~ai_assistant.core.protocols.ByteChannel`
    raise: an unreachable endpoint, a certificate that did not verify, a failed
    upgrade, a write to a far end that has gone, or a far end sending more octets
    for one line than :data:`~ai_assistant.core.types.TRANSPORT_OCTET_CEILING`
    admits.

    **The shared refusal type**, raised by the production implementation and by
    the canonical fake alike, so the conformance suites hold both to one taxonomy
    and the fake needs no ``tools`` import to express a connection failure.

    **A caller-supplied ``limit`` outside its domain is not this class's, and the
    division is by subject** (ADR-0191 §1). A ``TransportError`` says what
    happened to the *connection*; an out-of-domain ``limit`` is the caller's own
    defect and says nothing about it, so ``read`` raises ``ValueError`` for one.

    **It is not re-rooted into `tools`, and `tools` is not re-rooted into it.**
    ``ai_assistant.tools.egress`` keeps ``EgressTransportError`` and
    ``TransportPinError`` for refusals about a *binding*; where its ordering
    requires, that seam wraps or converts one of these into its own hierarchy.

    **It carries no structured state and its message renders no payload.** What a
    refusal may name is the condition — a host, a port, a bound that was
    exceeded, an error type — and never an octet that was written or read.
    """
