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

**An exception is logged by its class and its frames, never its words.** A
rendered traceback is out of the redactor's reach — it is a string by the time it
exists — and the renderer's default one prints the exception's message and every
raising frame's locals, which hold the conversation's text. So the chain renders
an exception itself, before redaction, as its class and the frames it passed
through (:func:`scrub_exceptions`), and the renderer's exception formatter does
the same should anything reach it. No content reaches a log (ADR-0314 §3:2).

**A standard-library record is held to the same rule.** Records from the
``logging`` module — a third-party library's, asyncio's "Task exception was never
retrieved" — never pass through structlog's chain, and the stdlib's formatter
appends a traceback with the exception's message. So each root handler is handed,
in place of a record that carries an exception, a fresh record built from its
standard fields alone (:class:`_ScrubRecords`): its logger's name, its level, where
it was logged, and as its message a fixed marker followed by each exception's class
and frames. No argument and no extra is carried over. Nothing is taken out of a
string: any string can be rebuilt from an exception's words, so the record's
strings are not printed at all. A record that carries no exception prints as it is.

"Carries an exception" is shallow by design: ``exc_info``, or an exception passed
directly as the message, an argument or an extra — what a realistic emitter does.
An object built to hide one deeper, and content a call site puts into a record with
no exception, are the call site's to keep out of a log (ADR-0004 §5).
"""

from __future__ import annotations

import copy
import logging
import sys
import traceback
from collections.abc import Mapping, Sequence, Set
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import PosixPath, PurePosixPath, PureWindowsPath, WindowsPath
from types import TracebackType
from typing import TYPE_CHECKING, Any, Final, TextIO, cast
from uuid import UUID

import structlog
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, MutableMapping

    from structlog.typing import ExcInfo

    from ai_assistant.core.config import Settings

REDACTED: Final = "[redacted]"

# Types safe to render as-is: their repr is their own value, with no nested
# fields that could hide user data. Anything not listed is masked (see
# `_redact_value`), so this set is the boundary of what the net trusts.
#
# Matched by *exact type*, never isinstance. A subclass can override __repr__ to
# render anything at all, so `class Sneaky(int): __repr__ = ...` inherits from a
# trusted type without being one. Enum is handled separately, by name.
_SAFE_EXACT_TYPES: Final = frozenset(
    {
        bool,
        int,
        float,
        complex,
        Decimal,
        UUID,
        PurePosixPath,
        PureWindowsPath,
        PosixPath,
        WindowsPath,
        datetime,
        date,
        time,
        timedelta,
        type(None),
    }
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
    # An Enum's *value* can be a secret (`ApiKey.VALUE = "sk-live-…"`), and its
    # repr shows it. The member name is code-defined and is all a diagnostic
    # needs, so the name is what gets rendered.
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    # Exact types, not isinstance: an `int` subclass overriding __repr__ renders
    # as whatever it likes, so inheriting from a safe type is not evidence of
    # being safe.
    if type(value) in _SAFE_EXACT_TYPES:
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

    The test is **shape, not content**: a field name is an identifier, so
    anything that is not one is treated as data. Listing the shapes data can
    take is unwinnable — an earlier version looked for ``@`` and ``=`` and
    happily emitted ``{"123-45-6789": 1}`` and ``{"Alice Smith": 1}``. Asking
    what a *field name* looks like has one answer; asking what data looks like
    has infinitely many.

    Residual limit, stated rather than hidden: a single bare token like
    ``"Alice"`` is a valid identifier and passes. Nothing distinguishes it from
    a field name without knowing the value's meaning, which a key-based net by
    definition does not. Over-matching in the other direction (``content-type``
    as a key is masked) is fixed by renaming the key.
    """
    return not key.isidentifier()


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


class _Described(str):
    """An exception already rendered here, as its class and frames alone.

    Marked by type so a second pass of :func:`scrub_exceptions` keeps it rather
    than masking it as a string it cannot vouch for.
    """

    __slots__ = ()


def _class_name(failure: BaseException) -> str:
    """``failure``'s class, qualified by its module unless it is a builtin."""
    cls = type(failure)
    module = cls.__module__
    if module in {"builtins", "__main__"}:
        return cls.__qualname__
    return f"{module}.{cls.__qualname__}"


def _chain(failure: BaseException, seen: set[int]) -> list[tuple[BaseException, str | None]]:
    """``failure``'s chain, oldest first, each with the line leading to the one after it.

    Walked iteratively, so a long ``__context__`` chain — a retry loop raising
    inside its own handler — renders instead of overflowing the stack. The newest,
    ``failure`` itself, is last and has no line after it. An exception in ``seen``
    is already rendered and ends the walk, so a cycle — a member whose context is
    its own group — ends rather than recursing; each one walked is added to it.
    """
    chain: list[tuple[BaseException, str | None]] = [(failure, None)]
    seen.add(id(failure))
    current = failure
    while True:
        earlier: BaseException | None
        if current.__cause__ is not None:
            earlier = current.__cause__
            link = "The above exception was the direct cause of the following exception:"
        elif current.__context__ is not None and not current.__suppress_context__:
            earlier = current.__context__
            link = "During handling of the above exception, another exception occurred:"
        else:
            earlier = None
        if earlier is None or id(earlier) in seen:
            return chain[::-1]
        seen.add(id(earlier))
        chain.append((earlier, link))
        current = earlier


#: An exception, with the traceback it is shown with.
type _Raised = tuple[BaseException, TracebackType | None]


def _describe(
    failure: BaseException, frames: TracebackType | None, seen: set[int] | None = None
) -> list[str]:
    """``failure`` as its frames and class, with its chain and a group's members.

    ``failure``'s own frames are those of ``frames``: its ``__traceback__``, or the
    traceback an ``exc_info`` tuple names with it, which a caller may have saved or
    shortened. Every exception chained to it or held in it is shown with its own.
    Each frame is its file, line, function and source line. What is never read:
    the exception's message, a chained or held exception's message, its notes,
    and any frame's locals — each can carry what the user or a model said. A
    group's members are listed under it, indented, each with its own frames and
    chain, so a failure in a task group's child keeps its class and where it was
    raised. Each exception is expanded once: one met again — a member two groups
    share — is named by its class alone, so groups that share members cannot
    multiply into a rendering exponential in their nesting.
    """
    seen = set() if seen is None else seen
    lines: list[str] = []
    for one, link in _chain(failure, seen):
        shown = frames if one is failure else one.__traceback__
        lines.extend(traceback.format_list(traceback.extract_tb(shown)))
        lines.append(f"{_class_name(one)}\n")
        if isinstance(one, BaseExceptionGroup):
            held = one.exceptions
            for number, member in enumerate(held, start=1):
                lines.append(f"+ {number}/{len(held)}\n")
                if id(member) in seen:
                    lines.append(f"| {_class_name(member)}, shown above\n")
                    continue
                lines.extend(
                    f"| {line}"
                    for line in "".join(_describe(member, member.__traceback__, seen)).splitlines(
                        keepends=True
                    )
                )
        if link is not None:
            lines.append(f"\n{link}\n\n")
    return lines


def _described(failure: BaseException, frames: TracebackType | None) -> _Described:
    """``failure`` shown with ``frames``, rendered by :func:`_describe`, as one marked string."""
    return _Described("".join(_describe(failure, frames)).rstrip("\n"))


def _raised(exc_info: object) -> _Raised | None:
    """The exception an ``exc_info`` value names, read as the renderer would read it.

    An exception, an ``exc_info`` tuple, or any other true value for the exception
    being handled — structlog's own reading, so nothing the renderer would have
    found is missed here. A tuple's exception comes with the tuple's traceback
    (:func:`_exc_info_raised`), as the renderer would show it.
    """
    named = _exc_info_raised(exc_info)
    if named is None and exc_info:
        _, held, frames = sys.exc_info()
        named = None if held is None else (held, frames)
    return named


def scrub_exceptions(
    _logger: object,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Render an event's exception as its class and frames alone (a structlog processor).

    The event's ``exc_info`` is replaced by an ``exception`` the renderer prints as
    it stands: the class, a group's member classes, any chained exception's class,
    and the frames each passed through — never a message, a note or a frame's
    locals. An exception object under ``exception`` is rendered the same way. Any
    other value there is a traceback rendered before this net, whose words cannot be
    told from its frames, so it is masked.

    The trade-off is deliberate: an operator reads what happened from the event's
    name and the class, never from the message. Detail that carries content belongs
    in the diagnostic record (ADR-0314), not in a log.

    Args:
        _logger: The wrapped logger (unused).
        _method_name: The log method called (unused).
        event_dict: The event being logged.

    Returns:
        The event with no exception content left in it.

    Raises:
        structlog.DropEvent: If the exception cannot be rendered. As with
            :func:`redact_sensitive`, an event that cannot be made safe is
            dropped rather than emitted with its exception intact.
    """
    try:
        raised = _raised(event_dict.pop("exc_info", None))
        if raised is not None:
            event_dict["exception"] = _described(*raised)
        elif "exception" in event_dict:
            given = event_dict["exception"]
            if isinstance(given, BaseException):
                event_dict["exception"] = _described(given, given.__traceback__)
            elif not isinstance(given, _Described):
                event_dict["exception"] = REDACTED
    except Exception as exc:  # losing a log line beats leaking one
        raise structlog.DropEvent from exc
    return event_dict


def _write_exception(sio: TextIO, exc_info: ExcInfo) -> None:
    """Write an exception as its class and frames: the renderer's exception formatter.

    The second net. :func:`scrub_exceptions` leaves no ``exc_info`` for the
    renderer to format, but were one to reach it — a processor reordered, a chain
    assembled by hand — it is written without its message or any frame's locals,
    where the renderer's default formatter prints both.

    Raises:
        structlog.DropEvent: If the exception cannot be rendered.
    """
    try:
        sio.write("\n" + _described(exc_info[1], exc_info[2]))
    except Exception as exc:  # losing a log line beats leaking one
        raise structlog.DropEvent from exc


#: What a record that carries an exception prints in place of its message, ahead of
#: each exception's class and frames. Fixed and code-owned, so it holds none of the
#: record's words.
_WITHHELD: Final = "[message withheld: the record carries an exception]"

#: The attributes every ``LogRecord`` has, and those a formatter adds. Any other
#: attribute was set by a call site's ``extra``, which a host's format may print.
#: Read off a record built directly, never through ``makeLogRecord``: that calls the
#: process's record factory, and a field a host's factory adds is not a standard one.
_RECORD_FIELDS: Final = frozenset(
    vars(logging.LogRecord("", logging.NOTSET, "", 0, "", (), None))
) | {"message", "asctime"}

#: The standard fields a fresh record takes from the record it stands for, past those
#: its constructor takes: when and where it was logged, never what.
_COPIED_FIELDS: Final = (
    "levelname",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "process",
    "processName",
    "taskName",
)

#: The extras ``structlog.stdlib.ProcessorFormatter.wrap_for_formatter`` attaches,
#: by which ``ProcessorFormatter`` tells a structlog event from a foreign record.
_STRUCTLOG_PLUMBING: Final = frozenset({"_logger", "_name"})


class _UnscrubbableError(Exception):
    """A record this module could not make content-free, so it is dropped."""


class _Replaced(logging.LogRecord):
    """A record this net built in place of one that carried an exception.

    Its own type, so a handler's failure to emit it is cut from the exception being
    handled before the handler reports it (:func:`_cut_from_the_handled`).
    """


def _exc_info_raised(exc_info: object) -> _Raised | None:
    """The exception a stdlib ``exc_info`` names, with the traceback it is shown with.

    An ``exc_info`` tuple's exception comes with the tuple's own traceback, which a
    caller may have saved or shortened and which need not be the exception's
    current ``__traceback__``; an exception comes with its own. Unlike
    :func:`_raised`, a true value is never read as "the exception being handled":
    the logging module resolved that when the record was made, and a record may be
    emitted long after, on another thread.
    """
    if isinstance(exc_info, tuple) and len(exc_info) == len(("type", "value", "traceback")):
        held, frames = exc_info[1], exc_info[2]
        if not isinstance(held, BaseException):
            return None
        return held, frames if isinstance(frames, TracebackType) else None
    if isinstance(exc_info, BaseException):
        return exc_info, exc_info.__traceback__
    return None


def _extras(record: logging.LogRecord) -> list[str]:
    """The attributes of ``record`` a call site's ``extra`` or a record factory set."""
    return [key for key in vars(record) if key not in _RECORD_FIELDS]


def _carried(record: logging.LogRecord) -> list[_Raised]:
    """The exceptions ``record`` carries, its ``exc_info``'s first, each with its traceback.

    Shallow, and only this: the exception its ``exc_info`` names; its message, when
    that is an exception; an exception that is directly one of its arguments (a
    tuple's element, or a value of the mapping a sole mapping argument becomes); and
    an exception that is directly the value of an extra. Nothing inside a container
    or an object is looked at. These are what a realistic emitter passes —
    ``logger.exception``, asyncio's handler, ``log.warning("failed: %s", err)``,
    ``extra={"error": err}`` — and an exception held deeper is the call site's to
    keep out of a log (ADR-0004 §5).
    """
    candidates: list[object] = [record.msg]
    args = record.args
    if isinstance(args, Mapping):
        candidates.extend(args.values())
    elif isinstance(args, tuple):
        candidates.extend(args)
    candidates.extend(getattr(record, key) for key in _extras(record))
    named = _exc_info_raised(record.exc_info)
    carried = [] if named is None else [named]
    carried.extend((one, one.__traceback__) for one in candidates if isinstance(one, BaseException))
    return carried


def _fresh(record: logging.LogRecord, msg: object, kept: Iterable[str] = ()) -> logging.LogRecord:
    """A new record standing for ``record``, built from its standard fields alone.

    It has ``record``'s logger name, level, place (path, line, function), time,
    thread, process and ``stack_info`` — which the logging module builds from the
    caller's frames alone, and which prints no local — and ``msg`` as its message.
    It has no arguments, no ``exc_info`` or ``exc_text``, and no extra but those
    named in ``kept``. Built by the ``LogRecord`` class directly, never through the
    process's record factory, which a host may have made to add fields of its own.
    """
    fresh = _Replaced(
        record.name,
        record.levelno,
        record.pathname,
        record.lineno,
        msg,
        (),
        None,
        record.funcName,
        record.stack_info,
    )
    for field in _COPIED_FIELDS:
        setattr(fresh, field, getattr(record, field, getattr(fresh, field, None)))
    for key in kept:
        setattr(fresh, key, getattr(record, key))
    return fresh


def _from_structlog(record: logging.LogRecord) -> bool:
    """Whether ``record`` is a structlog event wrapped for ``ProcessorFormatter``.

    Its message is the event dict, which ``ProcessorFormatter`` copies and renders
    itself; turned into a string, the formatter fails on it.
    """
    return isinstance(record.msg, dict) and all(
        hasattr(record, field) for field in _STRUCTLOG_PLUMBING
    )


def _scrubbed_event(record: logging.LogRecord) -> logging.LogRecord:
    """A copy of a wrapped structlog event, its dict through this module's structlog net.

    The event dict goes through :func:`scrub_exceptions` then
    :func:`redact_sensitive`, the rule every structlog event is held to: an
    exception is its class and frames, and any value the redactor cannot vouch for —
    an exception under another key included — is masked. Where the event carries an
    exception — an ``exception`` or a true ``exc_info`` in its dict, as the structlog
    chain left it; an exception directly as one of its values; its record's
    ``exc_info``; or an exception directly as an extra — it is handed on as a fresh
    record (:func:`_fresh`) with no extra but the plumbing ``ProcessorFormatter``
    reads, as a foreign record is: a factory can put an exception's text in one. Its
    ``exc_info`` is rendered as class and frames, and, where the event dict has no
    ``exception`` of its own, put there: ``ProcessorFormatter`` clears ``exc_text`` by
    default, and the event dict is what it renders.
    """
    given = cast("dict[str, Any]", record.msg)
    held: dict[str, Any] = dict(given)
    try:
        event = scrub_exceptions(None, record.levelname.lower(), held)
        scrubbed = dict(redact_sensitive(None, record.levelname.lower(), event))
    except structlog.DropEvent as exc:
        # Not an ``Exception``: raised as is, it would pass every handler's own
        # ``except Exception`` and reach the line that logged the record.
        raise _UnscrubbableError from exc
    raised = _exc_info_raised(record.exc_info)
    exc_text = _exception_text([raised] if raised is not None else [], record.exc_text)
    if raised is not None and "exception" not in scrubbed:
        # A host's record factory set the record's ``exc_info``; structlog's
        # ``wrap_for_formatter`` passes none. In ``exc_text`` alone, the class and
        # frames would be cleared by ``ProcessorFormatter`` before it rendered.
        scrubbed["exception"] = exc_text
        exc_text = None
    extras = [key for key in _extras(record) if key not in _STRUCTLOG_PLUMBING]
    carries = (
        raised is not None
        # An exception the structlog chain already rendered is an ``exception`` key,
        # and one not yet rendered may be a bare ``exc_info=True``.
        or "exception" in given
        or bool(given.get("exc_info"))
        or any(isinstance(value, BaseException) for value in given.values())
        or any(isinstance(getattr(record, key), BaseException) for key in extras)
    )
    if carries:
        safe = _fresh(record, scrubbed, kept=_STRUCTLOG_PLUMBING)
    else:
        safe = copy.copy(record)
        safe.msg = scrubbed
    safe.exc_text = exc_text
    safe.exc_info = None
    return safe


def _exception_text(carried: Sequence[_Raised], exc_text: str | None) -> str | None:
    """A record's exceptions as class and frames, or ``None`` if it has none to show.

    Each carried exception is rendered by :func:`_describe`, with its chain and a
    group's members, and one already shown — the cause of another, or the same one
    passed twice — is not shown again. Where the record carries none, a traceback a
    formatter rendered before this net (a record sent over a socket carries its
    traceback as text alone) cannot have its words told from its frames, so it is
    masked.
    """
    if carried:
        seen: set[int] = set()
        shown = [
            "".join(_describe(one, frames, seen)) for one, frames in carried if id(one) not in seen
        ]
        return _Described("\n".join(part.rstrip("\n") for part in shown))
    if isinstance(exc_text, _Described) or not exc_text:
        return exc_text
    return REDACTED


def _scrubbed_record(record: logging.LogRecord) -> logging.LogRecord:
    """``record``, or a fresh record in its place that prints none of its words.

    The rule F7 holds a structlog event to, applied to a standard-library record: an
    exception is shown by its class and frames, and never by anything that could
    hold its words. No string is edited to take words out of it. A record that
    carries an exception (:func:`_carried`), or a traceback rendered before this net,
    is replaced by a fresh record (:func:`_fresh`) that keeps only what is
    code-owned: its logger's name, its level, where and when it was logged. Its
    message is :data:`_WITHHELD` followed by each exception's class and frames
    (:func:`_exception_text`). It has no arguments and **no extra**: none is masked
    and none is kept, so a host's format that names one fails in that host's handler,
    whose report of the failure is cut from the exception being handled
    (:func:`_cut_from_the_handled`), and prints the fixed message and ``()``. The
    description is the message, not ``exc_text``, so a formatter that discards
    ``exc_text`` — ``ProcessorFormatter`` does, by default — still prints it; and no
    ``exc_info`` is left for a formatter to render its own way.

    A record that carries no exception is returned as it is, and prints as it
    printed before this net: what a call site puts in an ordinary message is the
    call site's to keep out of it (ADR-0004 §5).

    A structlog event wrapped for ``ProcessorFormatter`` is handed on with its event
    dict put through this module's structlog net (:func:`_scrubbed_event`).

    The record itself is never changed, so every other handler it reaches is handed
    the record as it was logged.
    """
    if _from_structlog(record):
        return _scrubbed_event(record)
    carried = _carried(record)
    pre_rendered = bool(record.exc_text) and not isinstance(record.exc_text, _Described)
    if not carried and not pre_rendered:
        return record
    shown = _exception_text(carried, record.exc_text)
    return _fresh(record, f"{_WITHHELD}\n{shown}" if shown else _WITHHELD)


class _ScrubRecords(logging.Filter):
    """A handler's filter that hands it each record with no exception's words in it.

    Fails closed: a record that cannot be scrubbed is dropped, never emitted as it
    was logged.
    """

    def filter(self, record: logging.LogRecord) -> bool | logging.LogRecord:
        """Return ``record`` or its content-free copy, or ``False`` to drop it.

        Args:
            record: The record a handler is about to emit.

        Returns:
            The record to emit in its place, or ``False`` if it could not be made.
        """
        try:
            return _scrubbed_record(record)
        except Exception:  # losing a log line beats leaking one
            return False


class _ContentFreeFormatter(logging.Formatter):
    """The formatter of this module's own handler: the second net for stdlib records.

    The handler's :class:`_ScrubRecords` hands it records already scrubbed; were one
    to reach it otherwise — ``emit`` called directly, the filter removed — it is
    scrubbed here, and an ``exc_info`` is still rendered as its class and frames
    alone, where the stdlib's default appends the exception's message.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format ``record`` with no exception's words in it.

        Args:
            record: The record to format.

        Returns:
            The formatted line.
        """
        return super().format(_scrubbed_record(record))

    def formatException(self, ei: Any) -> str:  # noqa: N802 — the stdlib's name
        """Render an exception as its class and frames, never its message.

        Args:
            ei: An ``exc_info`` tuple.

        Returns:
            The rendering, or nothing if no exception is named.
        """
        raised = _exc_info_raised(ei)
        if raised is None:
            return ""
        return str(_described(*raised))


class _ContentFreeHandler(logging.StreamHandler[TextIO]):
    """This module's own standard-error handler on the root logger.

    Installed only where the root logger has none, as ``logging.basicConfig`` would
    have installed one. It fails closed: a record that cannot be formatted is
    dropped. The stdlib's default reports such a failure with the record's message
    and arguments, which is the leak the formatter exists to prevent.
    """

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 — the stdlib's name
        """Drop a record that could not be emitted, saying nothing of it.

        Args:
            record: The record that could not be emitted (unused).
        """
        del record


def _cut_from_the_handled() -> None:
    """Cut the failure being handled from what it was raised during.

    A host's format that names an extra fails on a record this net built (it has
    none), in the host's own handler. A record logged inside an ``except`` block —
    ``logger.exception``, the commonest of all — makes that failure chain the
    exception being handled, and a handler's report of the failure (the stdlib's
    prints the whole chain) would print its words. The failure is the handler's own,
    raised over a record that holds none of the words, so its link to what came
    before is dropped, and the handler then reports it as it always does. Nothing
    else about the failure is changed.
    """
    failure = sys.exc_info()[1]
    if failure is not None:
        failure.__cause__ = None
        failure.__context__ = None
        failure.__suppress_context__ = True


#: ``logging.Handler.handleError`` as it was when this module was imported.
_HANDLERS_HANDLE_ERROR: Final = logging.Handler.handleError


def _handle_error(self: logging.Handler, record: logging.LogRecord) -> None:
    """``logging.Handler.handleError``, over a failure cut from the handled exception.

    Installed on the ``Handler`` class itself, so every handler that reaches it —
    one the net never attached to included, such as the target a ``MemoryHandler``
    on the root logger forwards a replaced record to — reports a failure on a record
    this net built without the exception being handled (:func:`_cut_from_the_handled`).
    The report itself is the stdlib's.
    """
    if type(record) is _Replaced:
        _cut_from_the_handled()
    _HANDLERS_HANDLE_ERROR(self, record)


class _ReportsContentFree:
    """A root handler's own ``handleError``, over a failure cut from the handled exception.

    For a handler whose class overrides ``handleError``, so the ``Handler`` class's
    (:func:`_handle_error`) may never be reached. On a record this net built, the
    failure is cut from the exception being handled (:func:`_cut_from_the_handled`);
    then the handler's own ``handleError`` runs, for every record, so what it does on
    a failure — a socket handler closes its socket to reconnect — is kept.
    """

    def __init__(self, hosts: Callable[[logging.LogRecord], None]) -> None:
        self._hosts = hosts

    def __call__(self, record: logging.LogRecord) -> None:
        """Handle a failure to emit ``record``.

        Args:
            record: The record that could not be emitted.
        """
        if type(record) is _Replaced:
            _cut_from_the_handled()
        self._hosts(record)


def _install_stdlib_net(level: int | None) -> None:
    """Make every standard-library record the root logger emits content-free.

    Each handler on the root logger, and ``logging.lastResort``, gains
    :class:`_ScrubRecords` once — a host's handler included, which keeps its own
    format and level and loses only what a record carrying an exception would
    print, as :func:`install_redaction` composes with a host's structlog chain
    rather than replacing it. Given a ``level`` and a root logger with no handler,
    this module's own standard-error handler is installed and the root set to that
    level, as ``logging.basicConfig`` did. ``basicConfig`` does nothing at all
    where the root already has a handler — under pytest, or in a host that
    configured logging first — so the net is attached here rather than left to it.
    A failure to emit a record this net built is cut from the exception being handled
    before it is reported (:func:`_cut_from_the_handled`): the ``Handler`` class's
    ``handleError`` is replaced once (:func:`_handle_error`), which reaches a
    handler the net never attached to, and
    each root handler's own is wrapped once (:class:`_ReportsContentFree`), which
    reaches one whose class overrides it.

    All of it is done under the logging module's own lock, as ``basicConfig`` does
    its check and install: two concurrent calls on a root with no handler would
    otherwise each find none and each install one, and every record would print
    twice. The lock is reentrant, and ``addHandler`` takes it too.
    """
    # The lock ``basicConfig``, ``dictConfig`` and ``addHandler`` hold; typeshed does
    # not declare it, since it is the module's own.
    with logging._lock:  # type: ignore[attr-defined]
        if logging.Handler.handleError is not _handle_error:
            logging.Handler.handleError = _handle_error  # type: ignore[method-assign]
        root = logging.getLogger()
        if level is not None and not root.handlers:
            ours = _ContentFreeHandler()
            ours.setFormatter(_ContentFreeFormatter("%(message)s"))
            root.addHandler(ours)
            root.setLevel(level)
        for handler in [*root.handlers, logging.lastResort]:
            if handler is None:
                continue
            if not any(isinstance(one, _ScrubRecords) for one in handler.filters):
                handler.addFilter(_ScrubRecords())
            if not isinstance(handler, _ContentFreeHandler) and not isinstance(
                handler.handleError, _ReportsContentFree
            ):
                # An instance attribute, so the handler's ``self.handleError(record)``
                # finds it ahead of its class's method.
                handler.handleError = _ReportsContentFree(handler.handleError)  # type: ignore[method-assign]


def _configure(level: int) -> None:
    """Install the processor chain, and the standard library's net, at ``level``."""
    _install_stdlib_net(level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            # Before redaction, which would mask an exception object passed as
            # ``exc_info`` to a string the renderer reads as "the exception being
            # handled".
            scrub_exceptions,
            # Redaction runs last among the enrichers, so it also scrubs keys
            # added by the processors above, not just by the call site.
            redact_sensitive,
            # The renderer's own exception formatter prints the message and every
            # frame's locals; this one prints neither, should an ``exc_info``
            # ever reach it.
            structlog.dev.ConsoleRenderer(exception_formatter=_write_exception),
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


def install_redaction() -> None:
    """Ensure the redaction processor is active, without stealing a host's setup.

    Called at import (below), because a safety net the caller has to remember to
    install is not a safety net: configuring only from the CLI callback left
    tests, scripts, and any embedding application on structlog's default chain,
    which has no redaction in it.

    But *replacing* a configuration we did not create is its own bug. An
    embedding application that had installed a stricter processor — masking
    ``medical_record``, say — lost it the moment it imported this package, and
    the next such event went out unredacted. Strictly worse than doing nothing,
    because the host had already solved the problem.

    So: if structlog is unconfigured, install the full chain. If it is already
    configured, leave every processor the host chose in place and *insert* ours —
    :func:`scrub_exceptions`, then :func:`redact_sensitive` — ahead of the
    renderer. Both configurations end up strictly more redacted than either was
    alone, and the host keeps its formatting, level, and factory. The standard
    library's handlers are composed with the same way: each root handler gains a
    filter that hands it a record carrying an exception as its class and frames
    alone, and keeps its own format (see :func:`_install_stdlib_net`).
    """
    if not structlog.is_configured():
        _configure(logging.INFO)
        return

    # A host that configured structlog owns its standard-library logging too: its
    # root handlers gain the scrubbing filter, and none is added to them.
    _install_stdlib_net(None)

    # Mutated **in place**, not replaced. A host using
    # `cache_logger_on_first_use=True` (structlog's own recommendation for
    # production) binds a logger's processor chain on first use and never
    # consults the configuration again — so calling `structlog.configure()` with
    # a new list installs the redactor for loggers created *later* while every
    # already-used logger keeps emitting through its old, unredacted chain. The
    # cached logger holds a reference to this very list, so inserting into it is
    # what actually reaches those loggers.
    processors = structlog.get_config()["processors"]
    # Before the renderer, which is by convention last and turns the event dict
    # into a string — after which there is nothing structured left to scrub. The
    # exception scrubber goes ahead of the redactor, as in our own chain: the
    # redactor masks an exception object, which then names nothing to render.
    if scrub_exceptions not in processors:
        at = (
            processors.index(redact_sensitive)
            if redact_sensitive in processors
            else max(len(processors) - 1, 0)
        )
        processors.insert(at, scrub_exceptions)
    if redact_sensitive not in processors:
        processors.insert(max(len(processors) - 1, 0), redact_sensitive)


install_redaction()
