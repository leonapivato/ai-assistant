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
from collections.abc import Mapping, Sequence, Set
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

import structlog
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from ai_assistant.core.config import Settings

REDACTED: Final = "[redacted]"

# Types safe to render as-is: their repr is their own value, with no nested
# fields that could hide user data. Anything not listed is masked (see
# `_redact_value`), so this list is the boundary of what the net trusts.
_SAFE_SCALARS: Final = (
    bool,
    int,
    float,
    complex,
    Decimal,
    Enum,
    UUID,
    PurePath,
    datetime,
    date,
    time,
    timedelta,
    type(None),
)

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
        # Tier 1 — conversation content.
        "answer",
        "body",
        "completion",
        "content",
        "memory",
        "message",
        "prompt",
        "query",
        "reply",
        "transcript",
        # Tier 1 — personal data. Compound name keys rather than a bare "name":
        # "name" would swallow model_name, source_name, field_name and every
        # other diagnostic identifier, which is over-matching that makes logs
        # useless rather than safe.
        "address",
        "birth",
        "dob",
        "email",
        "first_name",
        "full_name",
        "last_name",
        "latitude",
        "longitude",
        "phone",
        "postcode",
        "real_name",
        "ssn",
        "surname",
        "username",
        "user_name",
    }
)


def _is_sensitive(key: str) -> bool:
    """Return whether a log key should have its value masked.

    There is deliberately **no allow-list**. An exemption is a permanent hole in
    the net justified by an assumption about the value, and the assumption is
    what fails: `content_type` looks like inert MIME metadata right up until
    someone logs ``'text/plain; name="<patient record>"'``. When an over-matched
    key genuinely hurts a diagnostic, rename the key — that is a local fix, where
    an exemption is a global one.
    """
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _as_mapping(value: object) -> Mapping[Any, Any] | None:
    """Return ``value`` as a mapping of fields, or ``None`` if it is not one.

    Dataclasses and pydantic models are unwrapped here so the recursion can look
    inside them. Left alone they reach the renderer as a repr —
    ``Cfg(api_key='sk-live-…')`` — which is the leak in its most convenient
    form. `core/types.py` is entirely pydantic models, so this is the shape data
    actually travels in throughout this codebase.
    """
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: getattr(value, f.name) for f in fields(value)}
    if isinstance(value, BaseModel):
        return dict(value)
    return None


def _redact_mapping(mapping: Mapping[Any, Any]) -> dict[str, object]:
    """Redact a mapping's keys and values, without losing entries to collisions.

    Masking two data-carrying keys would otherwise map both to ``[redacted]``
    and silently drop one — a redactor that quietly discards diagnostics is its
    own kind of failure, so masked keys are numbered.
    """
    redacted: dict[str, object] = {}
    masked = 0
    for key, value in mapping.items():
        name = str(key)
        scrubbed = REDACTED if _is_sensitive(name) else _redact_value(value)
        if _key_carries_data(name):
            masked += 1
            redacted[REDACTED if masked == 1 else f"{REDACTED}:{masked}"] = scrubbed
        else:
            redacted[name] = scrubbed
    return redacted


def _redact_value(value: object) -> object:
    """Recursively mask sensitive keys inside nested structures.

    Nested containers are common in structured logs — routing reports a list of
    per-route dicts, for instance — so a top-level-only pass would miss most of
    what it is meant to catch.
    """
    # Match on the abstract Mapping/Sequence protocols, not the concrete dict and
    # list/tuple types. A `UserDict`, a `MappingProxyType`, or any custom mapping
    # is a perfectly ordinary thing to log and would sail through a `dict`-only
    # check with its secrets intact — which it did, until an adversarial review
    # pointed at exactly that.
    mapping = _as_mapping(value)
    if mapping is not None:
        return _redact_mapping(mapping)
    # str/bytes are Sequences and must not be walked character by character.
    if isinstance(value, (str, bytes, bytearray)):
        return value
    if isinstance(value, (Sequence, Set)):
        rebuilt = [_redact_value(item) for item in value]
        # Preserve tuple-ness, since a renderer may format it differently; every
        # other sequence or set degrades to a list, which is fine for output.
        return tuple(rebuilt) if isinstance(value, tuple) else rebuilt
    if isinstance(value, _SAFE_SCALARS):
        return value
    # Fail closed on anything we cannot look inside. An unrecognised object goes
    # to the renderer as its repr, and a repr shows whatever the object holds —
    # so "unknown" has to mean "masked", not "hope it is harmless". The cost is
    # that logging an exotic type shows [redacted] instead of a useful value;
    # the fix is to log a field of it, or add it to _SAFE_SCALARS deliberately.
    return REDACTED


def _key_carries_data(key: str) -> bool:
    """Return whether a mapping key looks like data rather than a field name.

    Keys are usually developer-chosen names, which is why they are matched
    against the deny-list rather than masked wholesale — but a mapping keyed by
    *data* (per-user counters, a parsed query string) puts Tier 0/1 content in
    the key position, where redacting only the value achieves nothing.

    The signals are ``@`` and ``=``: an email address used as a key, or a
    ``token=secret`` fragment. Both are vanishingly rare in a deliberate field
    name and strongly suggest data. A field name that legitimately contains one
    should be renamed rather than exempted.
    """
    return "@" in key or "=" in key


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


def _configure(level: int) -> None:
    """Install the processor chain at ``level``."""
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
        # Deliberately not cached. With caching on, a module-level
        # ``structlog.get_logger(__name__)`` binds to whatever configuration
        # existed at its first call and keeps it forever — so a later
        # configure_logging() silently has no effect on it. That is a correctness
        # problem for the log *level*, and a privacy problem for the redaction
        # processor: a logger that ran before configuration would keep emitting
        # through a chain with no redaction in it. Re-binding per call costs a
        # dict lookup; a leaking logger costs rather more.
        cache_logger_on_first_use=False,
    )


def configure_logging(settings: Settings) -> None:
    """Configure logging from application settings.

    Safe to call more than once: each call replaces the configuration outright
    rather than adding to it, and loggers are not cached, so a later call takes
    effect even on a logger already in use.

    Only the *level* is settings-dependent. The redaction processor is already
    installed at import (see below), so calling this is about verbosity, never
    about safety.

    Args:
        settings: Loaded application settings; supplies the log level.
    """
    _configure(logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO))


# Installed at import, not left to an entry point to remember.
#
# Configuring only from the CLI callback would leave every other way of using
# this package — a test, a script, an embedding application, `orchestration`
# wired up directly — on structlog's default chain, which has no redaction in
# it. A safety net that depends on the caller invoking it is not a safety net,
# and ADR-0004 §5 says structlog *is* configured, not that one adapter
# configures it.
#
# The cost is an import side effect on global structlog state, which is a real
# imposition on a host application. It is accepted here because the failure
# modes are asymmetric: the worst case for configuring is that a host re-applies
# its own configuration afterwards (and wins, since this is not idempotent-
# guarded), while the worst case for not configuring is a silent Tier 0/1 leak.
_configure(logging.INFO)
