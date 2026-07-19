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


class ContextError(AssistantError):
    """Situational context could not be assembled (e.g. a source-wiring bug)."""


class ToolError(AssistantError):
    """An external tool failed to execute."""


class PermissionDeniedError(AssistantError):
    """An action was blocked by the permission/policy layer."""


class PlanningError(AssistantError):
    """A request could not be turned into an executable plan."""
