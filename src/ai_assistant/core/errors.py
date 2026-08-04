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
    generic failure, and never a denial", covering both a hub restart, after which
    a process-scoped handle table is empty, and eviction under
    ``max_outstanding_confirmations``. Before this the engine raised a bare
    :class:`PlanningError`, indistinguishable from four other planning faults.

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
