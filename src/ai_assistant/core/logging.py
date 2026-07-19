"""Logging configuration and the ADR-0004 §5 redaction safety net.

ADR-0004 classifies logs as **Tier 2** and forbids Tier 0 (secrets) and Tier 1
(personal data) from ever reaching them. §5 requires a structlog processor that
masks known-sensitive keys "as a safety net", preferring to fail closed over
leaking. This module is that processor plus the one place logging is configured.

**A safety net is not the primary defence.** The deny-list below catches a key
someone *named* sensitively; it cannot catch Tier 1 data logged under an
innocuous name — `error=str(exc)` where the provider quoted the user's prompt is
the canonical example, and no key-based rule would spot it. The primary defence
remains the convention: log identifiers, classes, and counts, never content. See
:func:`redact_sensitive` for what "fail closed" does and does not buy here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

import structlog

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping

    from ai_assistant.core.config import Settings

REDACTED: Final = "[redacted]"

# Substrings, matched case-insensitively against the key. Substrings rather than
# exact names so `api_key`, `user_token` and `refresh_token` are all caught
# without enumerating every compound anyone will invent. Over-matching is the
# intended direction: "auth" also catches "author", and a redacted author beats a
# leaked credential.
_SENSITIVE_KEY_PARTS: Final = frozenset(
    {
        # Tier 0 — secrets and credentials.
        "auth",
        "cookie",
        "credential",
        "key",
        "passwd",
        "password",
        "secret",
        "session",
        "token",
        # Tier 1 — conversation content and personal data.
        "address",
        "completion",
        "content",
        "email",
        "memory",
        "message",
        "phone",
        "prompt",
        "reply",
        "ssn",
    }
)

# Keys that would otherwise be caught by the list above but carry no user data.
# Kept deliberately short: every entry is a hole in the net, so each one has to
# earn its place.
_ALLOWED_KEYS: Final = frozenset(
    {
        "content_type",
        "memory_kind",  # an enum member name (e.g. "SEMANTIC"), never content
    }
)


def _is_sensitive(key: str) -> bool:
    """Return whether a log key should have its value masked."""
    lowered = key.lower()
    if lowered in _ALLOWED_KEYS:
        return False
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _redact_value(value: object) -> object:
    """Recursively mask sensitive keys inside nested structures.

    Nested containers are common in structured logs — routing reports a list of
    per-route dicts, for instance — so a top-level-only pass would miss most of
    what it is meant to catch.
    """
    if isinstance(value, dict):
        return {
            k: (REDACTED if _is_sensitive(str(k)) else _redact_value(v)) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        rebuilt = [_redact_value(item) for item in value]
        return tuple(rebuilt) if isinstance(value, tuple) else rebuilt
    return value


def redact_sensitive(
    _logger: object,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> Mapping[str, Any]:
    """Mask values under known-sensitive keys (a structlog processor).

    Args:
        _logger: The wrapped logger (unused).
        _method_name: The log method called (unused).
        event_dict: The event being logged.

    Returns:
        The event with sensitive values replaced by :data:`REDACTED`.

    Raises:
        structlog.DropEvent: If redaction itself fails. This is the sense in
            which the net "fails closed" (ADR-0004 §5): an event that could not
            be scrubbed is dropped rather than emitted unscrubbed. It cannot
            mean "drop anything unrecognised" — a deny-list has no way to know
            an unlisted key is safe, which is exactly why this is a net and not
            the primary defence.
    """
    try:
        return {
            key: (REDACTED if _is_sensitive(key) else _redact_value(value))
            for key, value in event_dict.items()
        }
    except Exception as exc:  # losing a log line beats leaking one
        raise structlog.DropEvent from exc


def configure_logging(settings: Settings) -> None:
    """Configure structlog for the application.

    Idempotent, so an adapter that calls it twice (or a test that reconfigures)
    does not stack processors.

    Args:
        settings: Loaded application settings; supplies the log level.
    """
    level = logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            # Redaction runs last among the enrichers, so it also scrubs keys
            # added by the processors above, not just by the call site.
            redact_sensitive,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
