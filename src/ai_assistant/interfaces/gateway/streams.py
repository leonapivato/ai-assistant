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

#: What separates two values on a stream.
_TERMINATOR: Final = b"\n"


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
