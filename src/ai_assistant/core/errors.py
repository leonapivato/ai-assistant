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
    rather than to one undifferentiated error. The ``retryable`` class attribute
    marks the failures that a later attempt could plausibly resolve (a transient
    fault), as opposed to those that would fail identically on every retry (bad
    credentials, a refused prompt).

    A bare ``ModelError`` remains valid for a failure that does not fit any
    subclass, and is conservatively treated as non-retryable.
    """

    retryable: ClassVar[bool] = False


class ModelAuthError(ModelError):
    """The provider rejected our credentials (HTTP 401/403).

    Not retryable: the same key will be refused again.
    """


class ModelRateLimitError(ModelError):
    """The provider throttled the request (HTTP 429).

    Retryable, but only after a delay — retrying immediately will be throttled
    again. Honouring a provider-supplied ``Retry-After`` is deferred to the
    retry slice that consumes it.
    """

    retryable: ClassVar[bool] = True


class ModelTimeoutError(ModelError):
    """The provider did not respond within the deadline (HTTP 408 or a timeout).

    Retryable: a subsequent attempt may well be served.
    """

    retryable: ClassVar[bool] = True


class ModelUnavailableError(ModelError):
    """The provider is unreachable or failing (HTTP 5xx, connection errors).

    Retryable: this is the provider's problem, not the request's.
    """

    retryable: ClassVar[bool] = True


class ModelContentFilterError(ModelError):
    """The provider refused the request or response on content-policy grounds.

    Not retryable: the same prompt will be refused again.
    """


class ModelResponseError(ModelError):
    """The provider replied, but the response was malformed or unusable.

    Not retryable by default: a response we cannot parse usually reflects a
    mismatch in what we asked for rather than a transient fault.
    """


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
