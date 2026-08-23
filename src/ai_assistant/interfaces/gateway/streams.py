r"""What a browser stream carries, and the one discriminator (ADR-0175 §1, §2).

**A stream is the body of the response to one ordinary request the browser made.**
There is no socket, no upgrade and nothing an ``EventSource`` reaches, because
ADR-0168 §6 requires both halves of a web session on every admitted request and
requires the header half to travel "only as a request header the front end sets" —
and a `WebSocket` handshake and an `EventSource` request are the two requests on
which a page cannot set a header at all.

**The framing is this lane's to decide** (§2, on ADR-0168 §12's division: the
request shapes and paths "are not `core` surface, they are not a Protocol, and the
front end and the gateway ship and version in one distribution"). What is decided
*here* rather than by the ADR is the concrete answer to the two clauses §2 does
fix, and this module is the whole of it:

* **one JSON object per line**, UTF-8, served as ``application/x-ndjson`` over
  HTTP/1.1 chunked transfer. A JSON encoding never emits a bare newline inside a
  value — a line feed in a model's answer is written ``\\n`` — so the line *is* the
  frame and a reader needs no length prefix and no escape rule of its own;
* **a ``kind`` member on every value, and nothing else claiming what the value
  is.** A reader resolves the kind from that member and never by inspecting what
  the value contains. That is ADR-0173 §2's argument taken at the second edge: a
  frame "that is a chunk by kind and final by flag is two answers to one question",
  and a browser reading a stream is the second reader of the same sequence.

**Two of the five kinds are terminal and three are not**, which is the other clause
§2 fixes: "a reader that reached a terminal value has the whole of what the gateway
sent; a reader that did not has a transport failure and the front end reports it as
one". :data:`TERMINAL_KINDS` is that partition stated once, so the page and the
gateway cannot disagree about it.

**No ``delivery_id`` appears in any value this module builds** (ADR-0175 §5). It is
a capability ADR-0131 §4 mints for exactly one device, and ADR-0172 §1 closes the
class of values a browser holds at three — so the notification's *content* crosses
and the token does not. :func:`notification` is the only function here that sees a
:class:`~ai_assistant.core.types.NotificationDelivery`, and it reads one member of
it.
"""

from __future__ import annotations

import json
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    from collections.abc import Mapping

    from ai_assistant.core.types import NotificationDelivery, ReplyChunk

#: The media type every stream is served with. ``application/x-ndjson`` is the
#: registered-in-practice name for one JSON value per line, and it is *not*
#: ``text/event-stream``: ADR-0175 §1 refuses the browser interface that reads that
#: type, and naming it here would invite a lane to reach for `EventSource` again.
MEDIA_TYPE: Final = "application/x-ndjson"

#: The header a **delivery** stream states its own keep-alive cadence in (#1442).
#:
#: **The unit is in the name, because the wire is where it has to be readable.** The
#: value is a decimal count of microseconds — ``timedelta``'s own resolution, so the
#: integer is exact in both directions, no fraction is parsed anywhere, and no reader
#: has to round it through an IEEE-754 double. A header carrying a bare number whose
#: unit lived only in a docstring would be the one thing a reader can misread silently,
#: and the cost of saying it is twelve characters.
#:
#: The ``X-`` prefix is RFC 6648's deprecated form and is used anyway, for one reason:
#: ``X-Assistant-Session`` is already the name the page sets on every admitted request
#: (ADR-0168 §6), and one convention a reader can see twice beats two conventions each
#: of which is right on its own.
KEEP_ALIVE_HEADER: Final = "X-Assistant-Keep-Alive-Microseconds"

#: What separates two values on a stream.
_TERMINATOR: Final = b"\n"

#: The unit :func:`keep_alive_header` spells a duration in, named once so this module
#: and the page cannot disagree about it. ``timedelta``'s own resolution.
_MICROSECOND: Final = timedelta(microseconds=1)


class ValueKind(StrEnum):
    """The kinds a stream value can be, fixed in advance (ADR-0175 §2).

    Closed rather than open, for ADR-0168 §6's own reason one surface out: naming
    what may appear "is the only form that stays right when a later lane adds a
    request shape nobody has thought of yet". A reader that meets a kind it does
    not know treats the value as one it cannot render rather than guessing.
    """

    CHUNK = "chunk"
    """One :class:`~ai_assistant.core.types.ReplyChunk` of a streamed answer
    (ADR-0173 §2). Never terminal, and never the record of what the assistant
    said — ADR-0173 §3 keeps the terminal outcome's ``reply`` authoritative."""

    OUTCOME = "outcome"
    """The terminal value of an answer stream, carrying the whole
    :class:`~ai_assistant.core.types.TurnOutcome` view. Terminal."""

    NOTIFICATION = "notification"
    """One delivery the hub returned, written to every open delivery stream
    (ADR-0175 §4). Never terminal: a delivery stream carries many."""

    ALIVE = "alive"
    """The keep-alive of ADR-0175 §4 — "a value carrying nothing but its own
    kind". It is what makes the liveness of the gateway, of its hub connection and
    of the browser's own socket observable at a bounded cadence, on a stream that
    may be silent for as long as the assistant has nothing to say. Never
    terminal."""

    FAULT = "fault"
    """The terminal value of a stream that ended in a fault the gateway can name —
    a turn the hub declined, a poll it could not complete. Terminal, and it keeps
    ADR-0168 §9's distinction: a fault *value* is a request the hub received and
    answered, where a body that ends without a terminal value is a transport
    failure and the front end reports it as one."""


#: Which kinds end a stream. Stated once so the front end and the gateway cannot
#: hold two partitions (ADR-0175 §2).
TERMINAL_KINDS: Final = frozenset({ValueKind.OUTCOME, ValueKind.FAULT})


def encode(value: Mapping[str, Any]) -> bytes:
    """Frame one value for a stream: one JSON object, one line.

    Args:
        value: The value, already carrying its ``kind``.

    Returns:
        The bytes to write, terminator included.
    """
    return json.dumps(value).encode("utf-8") + _TERMINATOR


def chunk(piece: ReplyChunk) -> dict[str, Any]:
    """One instalment of a streamed answer (ADR-0173 §2, ADR-0175 §3).

    Args:
        piece: The chunk the engine yielded.

    Returns:
        The value to write.
    """
    return {"kind": ValueKind.CHUNK.value, "text": piece.text}


def outcome(view: Mapping[str, Any]) -> dict[str, Any]:
    """The terminal value of an answer stream (ADR-0175 §3).

    It carries the ``TurnOutcome`` view **whole**, so all four of ADR-0173 §6's
    shapes are readable at the browser from ``reply`` and ``reply_degraded`` alone.
    The fourth — an answer owed and *partly* produced — is the one a browser
    surface loses by accident, because the natural rendering of a stream is to show
    the chunks and stop, which displays it identically to a complete answer.

    Args:
        view: The rendered turn, as ``server._outcome_view`` built it.

    Returns:
        The value to write.
    """
    return {"kind": ValueKind.OUTCOME.value, "outcome": dict(view)}


def notification(delivery: NotificationDelivery) -> dict[str, Any]:
    """One delivery, as a browser renders it — and without its token (ADR-0175 §5).

    **The enumeration is the point**, exactly as ``_outcome_view``'s is: what may
    reach the page is decided here rather than by whatever a
    :class:`~ai_assistant.core.types.NotificationCandidate` happens to carry. Two
    members cross — the summary and the detail ADR-0130 §2 makes "the only free
    text… what the *user* would be shown" — plus the class the page groups on.

    **``delivery_id`` is read and dropped, deliberately.** ADR-0131 §4 makes it a
    capability held by exactly one device so the engine can honour an
    acknowledgement "without ever knowing who is asking"; a browser holding one
    would be a fourth member of the class ADR-0172 §1 closes at three and says
    twice may not be widened "by resemblance". So no browser acknowledges, retires,
    withdraws or dismisses a delivery, and the gateway acknowledges on its own next
    poll (ADR-0175 §5).

    **No confidence, no sensitivity and no references cross either.** ADR-0175 §12
    records that ADR-0130 is *unreached* by that decision — the gateway re-judges no
    disposition — and a page that showed a producer's confidence beside a
    notification would be presenting evidence as though it were the ruling, which
    ADR-0130 §4 separates in terms.

    Args:
        delivery: What ``next_notification`` returned.

    Returns:
        The value to write.
    """
    candidate = delivery.notification
    return {
        "kind": ValueKind.NOTIFICATION.value,
        "notification_class": candidate.notification_class,
        "summary": candidate.summary,
        "detail": candidate.detail,
    }


def alive() -> dict[str, Any]:
    """The keep-alive: its own kind and nothing else (ADR-0175 §4).

    Returns:
        The value to write.
    """
    return {"kind": ValueKind.ALIVE.value}


def keep_alive_header(budget: timedelta) -> tuple[str, str]:
    """A delivery stream's own head, stating the cadence §4 obliges a write within.

    **This is the fact a browser needs and could not have** (#1442). §4 spends the
    keep-alive to make "the liveness of the gateway, of its hub connection and of the
    browser's own socket observable at a bounded cadence", so a stream silent past a
    multiple of that cadence is the one thing the keep-alive exists to expose — but
    the cadence is ``gateway_notification_budget``, gateway configuration (§8), and
    nothing the page read carried it. Without it a ``fetch`` that never settled left
    the page reading "Watching for notifications" for ever with its own control
    hidden, and ADR-0182 §7's announced re-arm could not fire either, because §7
    re-establishes a stream "only while it holds none".

    **In the head rather than as a value on the stream.** ADR-0175 §2 leaves "the
    exact framing of a value on a stream" to this lane, so either was available — and
    the head is right on both clauses. §4 governs *values*: at most one pending per
    stream, and one whose write has not completed when the next is due is abandoned.
    A preamble is not a delivery, and making it a value put it under a rule written
    about browsers that stopped reading, where it ended freshly opened streams. A
    header is read off the response before a single value is, needs no place in the
    ordering, and cannot be abandoned. ADR-0168 §5 independently closes the other
    candidate — the bootstrap exchange "returns nothing but the two session values §6
    requires" — so the figure could never have ridden that body.

    **It is on the delivery stream alone.** An answer stream carries no keep-alive
    and §4 obliges nothing on it, so a header there would be a claim about an
    obligation that does not exist.

    Args:
        budget: ``gateway_notification_budget`` (ADR-0175 §8) — "the interval within
            which §4 obliges a write on every open delivery stream".

    Returns:
        The header's name and value.
    """
    return KEEP_ALIVE_HEADER, str(budget // _MICROSECOND)


def fault(name: str, *, detail: str | None = None) -> dict[str, Any]:
    """The terminal value of a stream the gateway can name the ending of.

    It carries the same ``fault`` vocabulary an ordinary refusal body does, so the
    page describes a fault that arrived on a stream with the words it already has
    for one that arrived as a response — which is ADR-0168 §9's distinction
    surviving to what the owner reads rather than stopping at a status code.

    Args:
        name: The fault's machine-readable name.
        detail: What the hub said, where it said anything.

    Returns:
        The value to write.
    """
    value: dict[str, Any] = {"kind": ValueKind.FAULT.value, "fault": name}
    if detail is not None:
        value["detail"] = detail
    return value
