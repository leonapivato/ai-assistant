"""Exception hierarchy for the assistant.

All errors raised by the application inherit from :class:`AssistantError`, so
callers (and interface adapters) can catch the whole family with one handler.
Add new, specific subclasses rather than raising bare ``Exception``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Sequence


class AssistantError(Exception):
    """Base class for every error raised by ai-assistant."""


class ConfigurationError(AssistantError):
    """Configuration is missing or invalid (e.g. a required secret is unset)."""


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
        """
        super().__init__(message)
        self.unresolved_ids: tuple[str, ...] = tuple(unresolved_ids)


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
