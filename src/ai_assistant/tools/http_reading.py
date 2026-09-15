"""Reading an HTTPS response the way two integrations both have to read one.

The parts of :mod:`ai_assistant.tools.web_search` that are not about searching: the
RFC 9110 ``Date`` field a response declares its own instant in, and the bounded
decode of a JSON body. ADR-0231 §10 and ADR-0260 §5 state the **same** rule over
that instant — "``reported_at`` is the instant the provider's own response declares,
on the provider's own clock, and there is no substitute" (ADR-0092 §3) — and a
second implementation of it is a place two integrations could come to disagree about
what a provider said. So it is stated once, here, and read from both.

**Nothing here opens anything, and nothing here is about a provider.** No credential,
no binding, no registration and no origin reaches this module; what it is handed is
octets an exchange has already read under its own bound. The provider-specific half —
which path, which parameters, which fields a request carries and what a body's shape
means — stays in each integration's own module, because ADR-0231 §5 and ADR-0260 §6
both put that choice there.

**It is bound by the transport-confinement contract like every other ``tools/``
module**, rather than exempted: it imports no network package and opens no
connection, and being *inside* the fence is what keeps the seam the one absence.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import FrozenJson

#: RFC 9110 §5.6.7's ``Date`` field, lowercased as
#: :class:`~ai_assistant.tools.egress.HttpsResponse` lowercases a field name. See
#: :func:`declared_instant` for why the instant is read from here.
_DATE_FIELD: Final = "date"

#: RFC 9110 §5.6.7's IMF-fixdate day names, in the order the format numbers them.
#: Spelled rather than parsed with ``%a``, which reads the process locale.
_IMF_DAYS: Final = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

#: Its month names, likewise and for the same reason.
_IMF_MONTHS: Final = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

#: How long an IMF-fixdate is: ``Sun, 06 Nov 1994 08:49:37 GMT``.
_IMF_LENGTH: Final = 29

#: How deeply a documented response may nest. Public, so the boundary case that keeps
#: this figure honest reads it rather than restating it. A documented answer is an
#: object holding an object or array holding objects — four levels at most — so a
#: bound two orders of magnitude above that refuses nothing a documented answer
#: carries while sitting far below the depth at which ``json``'s scanner exhausts the
#: interpreter's stack.
MAX_JSON_DEPTH: Final = 100

#: The octets that open a JSON structure, and those that close one.
_JSON_OPENERS: Final = frozenset(b"[{")
_JSON_CLOSERS: Final = frozenset(b"]}")

#: The two octets that decide where a JSON string ends, and so which brackets are
#: structure and which are a third party's words (:func:`_too_deep`).
_QUOTE: Final = ord('"')
_BACKSLASH: Final = ord("\\")


def declared_instant(headers: Sequence[tuple[str, str]]) -> datetime | None:
    """The instant the provider's own response declares, or ``None``.

    **Where it is read from, and what makes it the provider's own statement.**
    ADR-0231 §10 and ADR-0260 §5 each oblige the implementing lane to say both, "for
    the provider the owner chose". It is RFC 9110 §5.6.7's ``Date`` field, which
    §6.6.1 defines as "the date and time at which the message was originated" — a
    value the origin server writes from its own clock, about its own act of
    answering, before the response leaves it. It is **not** the instant this system
    sent the request, not the instant it received the response, and not a value
    derived from either; nothing on this path reads a clock at all.

    **Strict IMF-fixdate, and the obsolete formats are not read.** RFC 9110 §5.6.7
    requires a sender to generate that one format and forbids it generating another,
    and both decisions rule that "a value carried in that position which cannot be
    read as an instant is not a declared one". So an RFC 850 or ``asctime`` spelling
    lands with a malformed one — the fail-closed direction, which mints nothing
    rather than attesting to a value read under a rule the sender was told not to
    use. The parse is written out rather than taken from ``strptime``, whose ``%a``
    and ``%b`` read the process locale: a hub started under a non-English locale
    would otherwise refuse every well-formed date on that machine and nowhere else.

    Args:
        headers: The response's fields, names already lowercased.

    Returns:
        The instant, or ``None`` where the field is absent, appears more than once,
        or carries a value this format does not admit.
    """
    values = [value for field, value in headers if field == _DATE_FIELD]
    if len(values) != 1:
        # Two `Date` fields declare two instants, so the response declares none this
        # integration will pick between — the "no substitute" rule read at the one
        # place a client could invent one by taking the first.
        return None
    value = values[0]
    if len(value) != _IMF_LENGTH:
        return None
    day, comma, rest = value[:3], value[3:5], value[5:]
    if day not in _IMF_DAYS or comma != ", ":
        return None
    stamp, space, zone = rest[:20], rest[20:21], rest[21:]
    if space != " " or zone != "GMT":
        return None
    return _imf_stamp(stamp)


def _imf_stamp(stamp: str) -> datetime | None:
    """The ``dd Mmm yyyy hh:mm:ss`` half of an IMF-fixdate, as a UTC instant.

    Args:
        stamp: Exactly twenty characters, already split out by
            :func:`declared_instant`.

    Returns:
        The instant, or ``None`` where any field is not the fixed-width decimal the
        format states — a two-digit day, a named month, a four-digit year and three
        two-digit time fields, separated exactly as the format separates them.
    """
    separators = ((2, " "), (6, " "), (11, " "), (14, ":"), (17, ":"))
    if any(stamp[position] != character for position, character in separators):
        return None
    month = stamp[3:6]
    if month not in _IMF_MONTHS:
        return None
    fields = (stamp[0:2], stamp[7:11], stamp[12:14], stamp[15:17], stamp[18:20])
    if not all(field.isdigit() and field.isascii() for field in fields):
        return None
    day, year, hour, minute, second = (int(field) for field in fields)
    try:
        return datetime(year, _IMF_MONTHS.index(month) + 1, day, hour, minute, second, tzinfo=UTC)
    except ValueError:
        # A day the month does not have, or a time field out of range. `isdigit`
        # admits the digits; only the calendar can refuse the value, and a date that
        # names no determinate instant is treated exactly as a malformed string is.
        return None


def decoded_object(body: bytes) -> dict[str, FrozenJson] | None:
    """The response body as a UTF-8 JSON object, or ``None`` where it is not one.

    **A response the decoder cannot descend is one of the shapes, and it is refused
    here rather than left to leave.** ``json``'s scanner descends one level per open
    bracket, so a *well-formed* body nested deeply enough exhausts the interpreter's
    stack instead of failing to parse — which is reachable well inside a megabyte
    response bound, and is therefore a response a provider can actually send. Both
    seams raise for no source reason, and a body a provider sent is exactly a source
    reason.

    **The guard is a bound on the nesting rather than a caught ``RecursionError``**,
    and that is the difference between refusing and hoping: a stack that has already
    overflowed is not one an ``except`` clause can be relied on to unwind, which is
    what the first attempt at this discovered. So the depth is counted off the octets
    **before** the decoder is entered, and a body past the bound is refused without
    being parsed at all — the same posture the response bound one seam over takes,
    where "nothing is parsed" is what makes an over-large response yield no value.

    Args:
        body: The response's octets, as the exchange read them under its bound.

    **``NaN``, ``Infinity`` and ``-Infinity`` are not JSON, and this decoder does not
    take them.** Python's ``json`` accepts all three by default as an extension; RFC
    8259 admits no such token, so a body carrying one is a body outside the documented
    format — and a decoder that took it would let a response mint records off octets
    the format does not describe, **anywhere in the body**, including a member neither
    integration reads. :func:`_no_such_constant` is what refuses them, and it refuses
    by raising a ``ValueError`` the clause below already answers.

    Returns:
        The object, or ``None`` where the octets are not UTF-8, are not JSON, carry a
        token JSON does not have, are nested past :data:`MAX_JSON_DEPTH`, or are JSON
        that is not an object. All of them are one operator fact — the provider
        answered something this integration does not read — so they are one answer
        rather than five.
    """
    if _too_deep(body):
        return None
    try:
        decoded = json.loads(body.decode("utf-8"), parse_constant=_no_such_constant)
    except ValueError:
        # `ValueError` and not the two concrete classes: `UnicodeDecodeError` and
        # `json.JSONDecodeError` are both subclasses of it, and naming the base keeps
        # a third `ValueError` from this one call from leaving a member that returns
        # refusals.
        return None
    return decoded if isinstance(decoded, dict) else None


def _no_such_constant(token: str) -> object:
    """Refuse ``NaN``, ``Infinity`` and ``-Infinity``, which JSON does not have.

    Python's decoder accepts all three as an extension unless a caller says otherwise,
    and a response carrying one is a response outside RFC 8259 — so the honest answer
    is that the provider answered something this integration does not read, not that it
    answered a number no arithmetic here could use.

    Args:
        token: The constant the decoder met.

    Returns:
        Nothing: this function always raises. The annotation is what a
        ``parse_constant`` hook is typed as.

    Raises:
        ValueError: Always. :func:`decoded_object` already answers that class with
            ``None``, so the refusal needs no branch of its own.
    """
    msg = f"{token!r} is not a JSON value (RFC 8259)"
    raise ValueError(msg)


def _too_deep(body: bytes) -> bool:
    r"""Whether ``body`` nests structures past what these integrations will decode.

    Counted over the octets rather than over a parse, because the point is to decide
    it **before** the decoder is entered: see :func:`decoded_object`.

    **String-aware, and that is the whole of the correctness here.** A bracket inside
    a JSON string is a character in a third party's words and not a structure — both
    seams transcribe such a span **verbatim** — so a counter that read one would
    refuse an answer whose title happens to carry brackets, which is a drop neither
    decision admits. And it fails in the other direction too: a ``]`` inside an
    earlier string would *decrement* the running depth, so a crafted response could
    carry a real nesting this bound was meant to catch and pass under it. Both lenses
    of PR #2074's round 3 found the pair, and both are the same defect.

    Only two escapes matter for finding where a string ends: ``\\`` and ``\"``, and
    treating any ``\`` as consuming the next octet handles both. **UTF-8 makes the
    scan safe over octets**: no byte of a multi-byte sequence is below ``0x80``, so
    neither ``"`` nor ``\`` nor a bracket can appear inside one.

    Args:
        body: The response's octets.

    Returns:
        Whether the running structural depth ever passes :data:`MAX_JSON_DEPTH`.
    """
    depth = 0
    in_string = False
    escaped = False
    for octet in body:
        if in_string:
            if escaped:
                escaped = False
            elif octet == _BACKSLASH:
                escaped = True
            elif octet == _QUOTE:
                in_string = False
        elif octet == _QUOTE:
            in_string = True
        elif octet in _JSON_OPENERS:
            depth += 1
            if depth > MAX_JSON_DEPTH:
                return True
        elif octet in _JSON_CLOSERS:
            depth -= 1
    return False


__all__ = ["MAX_JSON_DEPTH", "declared_instant", "decoded_object"]
