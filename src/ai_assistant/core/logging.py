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
appends a traceback with the exception's message. So each root handler is handed a
scrubbed copy of every record (:class:`_ScrubRecords`): its exception rendered as
class and frames, every exception it carries named by its class wherever its
message, arguments or extras would have printed it (the repr asyncio's message
embeds included), and an argument or extra this net cannot look inside masked, as
the redactor masks an unknown value.
"""

from __future__ import annotations

import copy
import logging
import re
import sys
import traceback
from collections import deque
from collections.abc import Mapping, Sequence, Set
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import PosixPath, PurePosixPath, PureWindowsPath, WindowsPath
from typing import TYPE_CHECKING, Any, Final, Self, TextIO, cast
from uuid import UUID

import structlog
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Iterable, MutableMapping

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


def _describe(failure: BaseException, seen: set[int] | None = None) -> list[str]:
    """``failure`` as its frames and class, with its chain and a group's members.

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
        lines.extend(traceback.format_list(traceback.extract_tb(one.__traceback__)))
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
                    for line in "".join(_describe(member, seen)).splitlines(keepends=True)
                )
        if link is not None:
            lines.append(f"\n{link}\n\n")
    return lines


def _described(failure: BaseException) -> _Described:
    """``failure`` rendered by :func:`_describe`, as one marked string."""
    return _Described("".join(_describe(failure)).rstrip("\n"))


def _raised(exc_info: object) -> BaseException | None:
    """The exception an ``exc_info`` value names, read as the renderer would read it.

    An exception, an ``exc_info`` tuple, or any other true value for the exception
    being handled — structlog's own reading, so nothing the renderer would have
    found is missed here.
    """
    if isinstance(exc_info, BaseException):
        return exc_info
    if isinstance(exc_info, tuple) and len(exc_info) == len(("type", "value", "traceback")):
        held = exc_info[1]
        if isinstance(held, BaseException):
            return held
    if exc_info:
        return sys.exc_info()[1]
    return None


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
        failure = _raised(event_dict.pop("exc_info", None))
        if failure is not None:
            event_dict["exception"] = _described(failure)
        elif "exception" in event_dict:
            given = event_dict["exception"]
            if isinstance(given, BaseException):
                event_dict["exception"] = _described(given)
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
        sio.write("\n" + _described(exc_info[1]))
    except Exception as exc:  # losing a log line beats leaking one
        raise structlog.DropEvent from exc


class _ClassName(str):
    """An exception standing in a log record's arguments or extras as its class alone.

    ``%s`` and ``%r`` both print the class, so ``log.error("failed: %s", exc)``
    renders ``failed: ValueError`` and never the exception's words. A string, so a
    host's formatter that serialises an extra handles it as one.
    """

    __slots__ = ()

    def __new__(cls, failure: BaseException) -> Self:
        """Name ``failure`` by its class.

        Args:
            failure: The exception to stand in for.

        Returns:
            Its class's name, as :func:`_class_name` gives it.
        """
        return super().__new__(cls, _class_name(failure))

    def __repr__(self) -> str:
        return str.__str__(self)


#: The attributes every ``LogRecord`` has, and those a formatter adds. Any other
#: attribute was set by a call site's ``extra``, which a host's format may print.
#: Read off a record built directly, never through ``makeLogRecord``: that calls the
#: process's record factory, and a field a host's factory adds is not a standard one.
_RECORD_FIELDS: Final = frozenset(
    vars(logging.LogRecord("", logging.NOTSET, "", 0, "", (), None))
) | {"message", "asctime"}

#: The standard fields whose text a host or a library chooses at run time: a
#: logger's, a thread's, a process's or a task's name. Cleared like an extra; the
#: rest are the logging module's own (a level, a path, a function's name).
_NAMED_FIELDS: Final = ("name", "threadName", "processName", "taskName")

#: How many values an exception's arguments may hold, at any depth, before its
#: ``str`` and ``repr`` are not built here (:func:`_affordable`).
_AFFORDABLE_PARTS: Final = 10_000

#: The sequences walked inside a record's arguments and extras. Every mapping is
#: walked; a sequence or set of any other type is masked, as an unknown object is:
#: a ``range`` or a library's lazy sequence can be unbounded to walk, and its repr
#: is the type's own to choose.
_WALKED_SEQUENCES: Final = (list, tuple, set, frozenset, deque)

#: The path types the redactor trusts. A path is text, so the stdlib net clears it.
_PATH_TYPES: Final = frozenset({PurePosixPath, PureWindowsPath, PosixPath, WindowsPath})

#: The extras ``structlog.stdlib.ProcessorFormatter.wrap_for_formatter`` attaches,
#: by which ``ProcessorFormatter`` tells a structlog event from a foreign record.
_STRUCTLOG_PLUMBING: Final = frozenset({"_logger", "_name"})


class _UnscrubbableError(Exception):
    """A record this module could not make content-free, so it is dropped."""


def _exc_info_raised(exc_info: object) -> BaseException | None:
    """The exception a stdlib ``exc_info`` names: an ``exc_info`` tuple's, or itself.

    Unlike :func:`_raised`, a true value is never read as "the exception being
    handled": the logging module resolved that when the record was made, and a
    record may be emitted long after, on another thread.
    """
    if isinstance(exc_info, tuple) and len(exc_info) == len(("type", "value", "traceback")):
        exc_info = exc_info[1]
    return exc_info if isinstance(exc_info, BaseException) else None


def _walked(value: object) -> Iterable[object] | None:
    """What :func:`_carried` and :func:`_plain` look inside ``value`` at, or ``None``.

    A mapping's keys and values, or a walked sequence's items.
    """
    if isinstance(value, Mapping):
        return [part for pair in value.items() for part in pair]
    if isinstance(value, _WALKED_SEQUENCES):
        return value
    return None


def _carried(values: Iterable[object]) -> list[BaseException]:
    """Every exception in ``values``, at any depth of a walked container.

    Each container is looked inside once, so shared structure and a cycle end the
    walk rather than repeating it.
    """
    pending = list(values)
    found: list[BaseException] = []
    seen: set[int] = set()
    while pending:
        one = pending.pop()
        if isinstance(one, BaseException):
            found.append(one)
            continue
        inside = _walked(one)
        if inside is None or id(one) in seen:
            continue
        seen.add(id(one))
        pending.extend(inside)
    return found


def _held(carried: Sequence[BaseException]) -> list[BaseException]:
    """``carried`` with each one's chain and a group's members, each listed once.

    So a cycle, or a member groups share, ends the walk rather than repeating it.
    """
    pending = list(carried)
    found: list[BaseException] = []
    seen: set[int] = set()
    while pending:
        one = pending.pop()
        if id(one) in seen:
            continue
        seen.add(id(one))
        found.append(one)
        held: list[BaseException | None] = [one.__cause__, one.__context__]
        if isinstance(one, BaseExceptionGroup):
            held.extend(one.exceptions)
        pending.extend(member for member in held if member is not None)
    return found


def _affordable(failure: BaseException) -> bool:
    """Whether ``failure``'s ``str`` and ``repr`` cost no more than its arguments' size.

    A repr is linear in a tree of values and can be exponential in a graph that
    shares them: ``[shared, shared]`` nested sixteen times is seventeen lists and a
    repr of 65,536 leaves, as is a group holding the group before it twice. So the
    arguments are walked first — into a held exception's own arguments too — and an
    exception whose arguments share an object, or hold more than
    :data:`_AFFORDABLE_PARTS` values, has neither built. :class:`_Unsaid` still
    clears its text arguments and notes, and masks its repr where one appears.
    """
    pending = list(failure.args)
    seen: set[int] = set()
    parts = 0
    while pending:
        one = pending.pop()
        parts += 1
        if parts > _AFFORDABLE_PARTS:
            return False
        if isinstance(one, str) or type(one) in _SAFE_EXACT_TYPES:
            continue
        if id(one) in seen:
            return False
        seen.add(id(one))
        inside = one.args if isinstance(one, BaseException) else _walked(one)
        if inside is not None:
            pending.extend(inside)
    return True


def _renderings(text: str) -> list[str]:
    """``text`` as a formatter commonly prints it: as is, and escaped by ``repr`` or ``ascii``.

    Each with and without its quotes, and each line on its own, as is and escaped: a
    line of a multi-line text is printed between the escapes of the lines around it.
    """
    lines = text.splitlines()
    return [
        text,
        repr(text),
        repr(text)[1:-1],
        ascii(text),
        ascii(text)[1:-1],
        *lines,
        *(repr(line)[1:-1] for line in lines),
        *(ascii(line)[1:-1] for line in lines),
    ]


def _replaced(text: str, words: Mapping[str, str]) -> str:
    """``text`` with each of ``words`` replaced by its value, in one pass, longest first.

    Every occurrence of every word is found with ``str.find``, then taken leftmost
    first and, at one place, longest first, skipping any that overlaps one already
    taken; so a replacement put in is never read again. Not a regular expression: an
    exception's text can be megabytes long, and compiling it — then holding it in
    the ``re`` module's cache — would cost far more than finding it.
    """
    spans: list[tuple[int, int, str]] = []
    for word, replacement in words.items():
        at = text.find(word)
        while at != -1:
            spans.append((at, at + len(word), replacement))
            at = text.find(word, at + len(word))
    if not spans:
        return text
    spans.sort(key=lambda span: (span[0], span[0] - span[1]))
    parts: list[str] = []
    cursor = 0
    for start, end, replacement in spans:
        if start >= cursor:
            parts.extend((text[cursor:start], replacement))
            cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


class _Unsaid:
    """What takes the words of a record's exceptions out of a string.

    Each exception's text, each of its text arguments and each of its notes is
    replaced by its class wherever it appears, as are the forms a formatter commonly
    turns one into (:func:`_renderings`), and the exception's own repr. Its text and
    repr are built only where that is affordable (:func:`_affordable`). That leaves
    a rendering this module could not reproduce — asyncio's debug mode prints a callback's arguments
    through ``reprlib``, which cuts a long repr to ``ValueError('P…_END')`` — so a
    line still holding a carried exception's class followed by ``(`` is cut there,
    and what followed is masked.

    Over-matching is the intended direction, as for the redactor's keys: an
    exception whose text is a common word takes that word out of the rest of the
    text too.
    """

    __slots__ = ("_built", "_words")

    def __init__(self, failures: Sequence[BaseException]) -> None:
        words: dict[str, str] = {}
        for failure in failures:
            name = _class_name(failure)
            # Each text argument and note on its own: a group's ``str`` adds a count
            # of its members to its message, and a call site can print either alone.
            texts = [arg for arg in failure.args if isinstance(arg, str)]
            notes = getattr(failure, "__notes__", ())
            if isinstance(notes, (list, tuple)):  # assigned by hand, it could be a string
                texts.extend(note for note in notes if isinstance(note, str))
            said: list[str] = []
            if _affordable(failure):
                texts.append(str(failure))
                said.append(repr(failure))
            for text in texts:
                said.extend(_renderings(text))
            for one in said:
                if one.strip():
                    words.setdefault(one, name)
        self._words = words
        names = sorted({type(failure).__name__ for failure in failures}, key=len, reverse=True)
        self._built = (
            re.compile(r"\b(" + "|".join(re.escape(name) for name in names) + r")\(")
            if names
            else None
        )

    def __call__(self, text: str) -> str:
        """``text`` with no word of the record's exceptions left in it.

        Args:
            text: A string the record would put in front of a formatter.

        Returns:
            The string, with each exception named by its class alone.
        """
        if self._built is None:
            return text
        text = _replaced(text, self._words)
        lines = []
        for line in text.splitlines(keepends=True):
            opened = self._built.search(line)
            if opened is None:
                lines.append(line)
            else:
                ending = line[len(line.rstrip("\r\n")) :]
                lines.append(f"{line[: opened.start()]}{opened.group(1)}({REDACTED}){ending}")
        return "".join(lines)


def _plain_leaf(value: object, unsaid: _Unsaid) -> object:
    """A value that is neither a string, an exception nor a walked container, made plain.

    Only exact types are trusted, as the redactor trusts them: a subclass renders as
    it likes. A path is text, so it is cleared as a string is, and becomes one; so is
    a time zone's name, so a time carrying a zone becomes its ``str``, which prints
    the offset alone. Any other plain value — a number, a date, a UUID — has no text
    of its own and is kept. An enum is named by its member, as the redactor names
    one, and the name cleared, since an enum can be made at run time from any text.
    Anything else is masked. Bytes are masked too: they are raw data — a library
    reporting a malformed document quotes its bytes — and never words this net can
    match.
    """
    if type(value) in _PATH_TYPES:
        return unsaid(str(value))
    if isinstance(value, (datetime, time)) and value.tzinfo is not None:
        return unsaid(str(value)) if type(value) in _SAFE_EXACT_TYPES else REDACTED
    if type(value) in _SAFE_EXACT_TYPES:
        return value
    if isinstance(value, Enum):
        return unsaid(f"{type(value).__name__}.{value.name}")
    return REDACTED


def _plain_mapping(
    value: Mapping[Any, Any], unsaid: _Unsaid, done: set[int]
) -> dict[object, object]:
    """A mapping made plain, keys and all, keeping every entry.

    Two keys can become one: two exceptions of a class both stand as its name. The
    later is numbered, as the redactor numbers masked keys, rather than overwriting
    the earlier.
    """
    rebuilt: dict[object, object] = {}
    for key, item in value.items():
        plain_key = _hashable(_plain(key, unsaid, done))
        if plain_key in rebuilt:
            count = 2
            while f"{plain_key}:{count}" in rebuilt:
                count += 1
            plain_key = f"{plain_key}:{count}"
        rebuilt[plain_key] = _plain(item, unsaid, done)
    return rebuilt


def _hashable(key: object) -> object:
    """A rebuilt mapping key, masked if rebuilding left it unhashable (a set become a list)."""
    try:
        hash(key)
    except TypeError:
        return REDACTED
    return key


def _plain(value: object, unsaid: _Unsaid, done: set[int]) -> object:
    """``value`` as plain values a formatter can print without an exception's words.

    An exception stands as its class (:class:`_ClassName`) and a string loses the
    words of the record's exceptions. A plain value is kept, an enum is named by its
    member, and a mapping or walked sequence is rebuilt from its parts (a ``dict``, a
    ``tuple``, or a ``list``). Anything else is masked, as the redactor masks it:
    its repr is whatever it holds, which can be an exception this net never saw — a
    finished task's repr carries its exception's. A container met again — shared,
    or a cycle — is masked rather than printed again: a graph that shares its parts
    prints exponentially in its depth.
    """
    if isinstance(value, BaseException):
        return _ClassName(value)
    if isinstance(value, str):
        # As an exact string: a subclass renders as it likes.
        return unsaid(str.__str__(value))
    inside = _walked(value)
    if inside is None:
        return _plain_leaf(value, unsaid)
    if id(value) in done:
        return REDACTED
    done.add(id(value))
    result: object
    if isinstance(value, Mapping):
        result = _plain_mapping(value, unsaid, done)
    else:
        items = [_plain(item, unsaid, done) for item in inside]
        result = tuple(items) if isinstance(value, tuple) else items
    return result


def _from_structlog(record: logging.LogRecord) -> bool:
    """Whether ``record`` is a structlog event wrapped for ``ProcessorFormatter``.

    Its message is the event dict, which ``ProcessorFormatter`` copies and renders
    itself; turned into a string, the formatter fails on it.
    """
    return isinstance(record.msg, dict) and all(
        hasattr(record, field) for field in _STRUCTLOG_PLUMBING
    )


def _scrubbed_record(record: logging.LogRecord) -> logging.LogRecord:
    """A copy of ``record`` that carries no exception's words.

    Every exception the record carries — its ``exc_info``, its message, one among
    its arguments or its extras, at any depth of a walked container — is found
    first. Then the message, the arguments and the extras are made plain
    (:func:`_plain`): an exception stands as its class, a string loses the words of
    every one of those exceptions, their chains and a group's members, and an
    object this net cannot look inside is masked. Each part is cleared *before* the
    message is formatted, so ``%r`` cannot escape a word out of reach, and once, so a
    class name put in is never read again. A message formatted before it was logged
    is its own one part: asyncio's "Task exception was never retrieved" embeds the
    task's repr, which holds ``exception=ValueError('…')``.

    A structlog event wrapped for ``ProcessorFormatter`` keeps its event dict as
    its message, put through this module's structlog net, :func:`scrub_exceptions`
    then :func:`redact_sensitive`; its plumbing extras are left as they are.

    The copy's message has no arguments left to format. Its exception is rendered
    as its class and frames, as :func:`scrub_exceptions` renders one, and set as the
    text a formatter appends, with no ``exc_info`` left for a formatter to render
    its own way. Text a formatter rendered before this net — a record sent over a
    socket carries its traceback as text alone — cannot have its words told from
    its frames, so it is masked. ``stack_info`` is kept: the logging module builds
    it from the caller's frames alone, which hold no message and print no local.

    The record itself is untouched, so every other handler it reaches is handed the
    record as it was logged.
    """
    raised = _exc_info_raised(record.exc_info)
    wrapped = _from_structlog(record)
    extras = {
        key: value
        for key, value in vars(record).items()
        if key not in _RECORD_FIELDS and not (wrapped and key in _STRUCTLOG_PLUMBING)
    }
    args = record.args
    # A sole mapping argument is the record's ``args`` itself: printed whole by ``%s``,
    # or read by name by ``%(name)s``. Either way its keys are printed or matched, so
    # it is walked, and made plain, as one value, keys and all.
    arguments = [args] if isinstance(args, Mapping) else list(args or ())
    message: list[object] = [] if wrapped else [record.msg]
    unsaid = _Unsaid(_held(_carried([raised, *message, *arguments, *extras.values()])))
    done: set[int] = set()

    safe = copy.copy(record)
    for key, value in extras.items():
        setattr(safe, key, _plain(value, unsaid, done))
    for field in _NAMED_FIELDS:
        named_by = getattr(record, field, None)
        if isinstance(named_by, str):
            setattr(safe, field, unsaid(named_by))
    if wrapped:
        safe.msg = _scrubbed_event(record)
    else:
        named = copy.copy(record)
        named.msg = _plain(record.msg, unsaid, done)
        if isinstance(args, Mapping):
            named.args = cast("dict[str, object]", _plain(args, unsaid, done))
        elif args:
            named.args = tuple(_plain(value, unsaid, done) for value in args)
        text = named.getMessage()
        safe.msg = text
        safe.args = ()
        safe.message = text
    safe.exc_text = _exception_text(record, raised)
    safe.exc_info = None
    return safe


def _scrubbed_event(record: logging.LogRecord) -> dict[str, Any]:
    """A wrapped structlog event's dict, through :func:`scrub_exceptions` and the redactor."""
    held: dict[str, Any] = dict(cast("dict[str, Any]", record.msg))
    try:
        event = scrub_exceptions(None, record.levelname.lower(), held)
        return dict(redact_sensitive(None, record.levelname.lower(), event))
    except structlog.DropEvent as exc:
        # Not an ``Exception``: raised as is, it would pass every handler's own
        # ``except Exception`` and reach the line that logged the record.
        raise _UnscrubbableError from exc


def _exception_text(record: logging.LogRecord, raised: BaseException | None) -> str | None:
    """The text a formatter appends for ``record``'s exception: class and frames alone."""
    if raised is not None:
        return _described(raised)
    if isinstance(record.exc_text, _Described) or not record.exc_text:
        return record.exc_text
    return REDACTED


class _ScrubRecords(logging.Filter):
    """A handler's filter that hands it each record with no exception's words in it.

    Fails closed: a record that cannot be scrubbed is dropped, never emitted as it
    was logged.
    """

    def filter(self, record: logging.LogRecord) -> bool | logging.LogRecord:
        """Return a scrubbed copy of ``record``, or ``False`` to drop it.

        Args:
            record: The record a handler is about to emit.

        Returns:
            The copy to emit in its place, or ``False`` if it could not be made.
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
        return str(_described(raised))


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


def _install_stdlib_net(level: int | None) -> None:
    """Make every standard-library record the root logger emits content-free.

    Each handler on the root logger, and ``logging.lastResort``, gains
    :class:`_ScrubRecords` once — a host's handler included, which keeps its own
    format and level and loses only the exception's words, as
    :func:`install_redaction` composes with a host's structlog chain rather than
    replacing it. Given a ``level`` and a root logger with no handler, this
    module's own standard-error handler is installed and the root set to that
    level, as ``logging.basicConfig`` did. ``basicConfig`` does nothing at all
    where the root already has a handler — under pytest, or in a host that
    configured logging first — so the net is attached here rather than left to it.
    """
    root = logging.getLogger()
    if level is not None and not root.handlers:
        ours = _ContentFreeHandler()
        ours.setFormatter(_ContentFreeFormatter("%(message)s"))
        root.addHandler(ours)
        root.setLevel(level)
    for handler in [*root.handlers, logging.lastResort]:
        if handler is not None and not any(
            isinstance(one, _ScrubRecords) for one in handler.filters
        ):
            handler.addFilter(_ScrubRecords())


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
    filter that hands it records with no exception's words in them, and keeps its
    own format (see :func:`_install_stdlib_net`).
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
