"""Exception hierarchy for the assistant.

All errors raised by the application inherit from :class:`AssistantError`, so
callers (and interface adapters) can catch the whole family with one handler.
Add new, specific subclasses rather than raising bare ``Exception``.
"""

from __future__ import annotations


class AssistantError(Exception):
    """Base class for every error raised by ai-assistant."""


class ConfigurationError(AssistantError):
    """Configuration is missing or invalid (e.g. a required secret is unset)."""


class ModelError(AssistantError):
    """A language-model provider failed or returned an unusable response."""


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
