"""Exception hierarchy for the assistant.

All errors raised by the application inherit from :class:`AssistantError`, so
callers (and interface adapters) can catch the whole family with one handler.
Add new, specific subclasses rather than raising bare ``Exception``.
"""

from __future__ import annotations

from typing import ClassVar


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
