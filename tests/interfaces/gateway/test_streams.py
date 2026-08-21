"""What a browser stream carries, and what never appears on one (ADR-0175 §2, §5).

The framing itself is this lane's, so what is pinned here is what the ADR *does*
fix about it — one discriminator, no second claim about what a value is, a terminal
partition a reader can act on, and no ``delivery_id`` anywhere.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from ai_assistant.core.types import (
    DataTier,
    NotificationCandidate,
    NotificationDelivery,
    ReplyChunk,
)
from ai_assistant.interfaces.gateway import streams
from ai_assistant.interfaces.gateway.http import StreamHead, render_stream_head

_AT = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)

#: The token ADR-0131 §4 mints for exactly one device, in the shape that type
#: describes. Distinctive on purpose: every case below searches the whole encoded
#: value for it, so a member added later that happened to carry it would fail here.
_TOKEN = "7." + "b3" * 16


def _delivery(*, detail: str | None = "what else there is to say") -> NotificationDelivery:
    """One delivery, as ``next_notification`` hands it back."""
    return NotificationDelivery(
        delivery_id=_TOKEN,
        notification=NotificationCandidate(
            candidate_key="a-key",
            producer="calendar-reader",
            notification_class="calendar-upcoming",
            summary="Standup starts in five minutes",
            detail=detail,
            noticed_at=_AT,
            confidence=0.8,
            sensitivity=DataTier.PERSONAL,
            references=("event-1",),
        ),
    )


# --- §2: one discriminator, and nothing else claiming what a value is --------


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(streams.chunk(ReplyChunk(text="hello")), id="chunk"),
        pytest.param(streams.outcome({"reply": "hi"}), id="outcome"),
        pytest.param(streams.notification(_delivery()), id="notification"),
        pytest.param(streams.alive(), id="alive"),
        pytest.param(streams.fault("hub-unreachable"), id="fault"),
    ],
)
def test_every_value_carries_exactly_one_kind_and_it_is_a_known_one(
    value: dict[str, object],
) -> None:
    """§2: "a reader resolves a value's kind from a discriminator the value itself
    carries and never by inspecting what the value contains"."""
    assert value["kind"] in {kind.value for kind in streams.ValueKind}


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(streams.chunk(ReplyChunk(text="hello")), id="chunk"),
        pytest.param(streams.outcome({"reply": "hi"}), id="outcome"),
        pytest.param(streams.notification(_delivery()), id="notification"),
        pytest.param(streams.alive(), id="alive"),
        pytest.param(streams.fault("hub-unreachable"), id="fault"),
    ],
)
def test_no_value_carries_a_second_claim_about_what_it_is(value: dict[str, object]) -> None:
    """§2: "no value carries a second claim about what it is".

    ADR-0173 §2's own argument at the second edge: a sequence number would be a
    second claim about an order the byte order already fixes, and "a frame that is a
    chunk by kind and final by flag is two answers to one question".
    """
    assert not {"final", "last", "terminal", "sequence", "index", "type"} & set(value)


def test_the_keep_alive_carries_nothing_but_its_own_kind() -> None:
    """§4's own words for it, and the reason: what it proves is that the gateway, its
    hub connection and the browser's socket are all still there."""
    assert streams.alive() == {"kind": "alive"}


def test_exactly_two_kinds_end_a_stream() -> None:
    """§2 partitions the endings a reader must tell apart, and the partition is
    stated once so the page and the gateway cannot hold two of them."""
    assert set(streams.TERMINAL_KINDS) == {streams.ValueKind.OUTCOME, streams.ValueKind.FAULT}


def test_the_media_type_is_not_the_one_an_event_source_reads() -> None:
    """§1 refuses the browser interface, not the format: an event stream's framing
    "remains available to the implementing lane as a way to *frame* values on a
    stream a ``fetch`` reads". Naming its media type here would invite a later lane
    to reach for the interface as well.

    Read off the served head rather than compared to a literal, because ``mypy``
    knows the constant's value and would rule the comparison out at type-check time —
    which would make the case vacuous rather than passing.
    """
    served = render_stream_head(StreamHead(content_type=streams.MEDIA_TYPE), policy="p")

    assert b"text/event-stream" not in served
    assert b"Content-Type: application/x-ndjson" in served


# --- the framing this lane chose: one JSON object, one line ------------------


def test_a_value_is_one_line_and_a_newline_inside_it_does_not_break_the_frame() -> None:
    """The property that makes the line the frame: a JSON encoding writes a line feed
    in a model's answer as an escape, so a reader needs no length prefix of its own.

    A composed answer with paragraph breaks in it is the ordinary case, not an
    adversarial one — ``.reply { white-space: pre-wrap }`` exists because answers
    arrive with the breaks they were written with.
    """
    framed = streams.encode(streams.chunk(ReplyChunk(text="first\n\nsecond")))

    assert framed.count(b"\n") == 1
    assert framed.endswith(b"\n")
    assert json.loads(framed)["text"] == "first\n\nsecond"


# --- §5: the token never leaves the gateway ----------------------------------


@pytest.mark.parametrize("detail", ["some detail", None])
def test_a_notification_value_carries_no_delivery_id(detail: str | None) -> None:
    """§5: "A ``delivery_id`` never reaches a browser. It is placed in no value the
    gateway writes on a stream, in no response body, in no document and in no URL".

    ADR-0131 §4 makes it "a **capability**" honoured without knowing who is asking,
    and ADR-0172 §1 closes the class of such values a browser holds at three and
    forbids widening it "by resemblance". Searched over the *encoded* value rather
    than over its keys, so a member added later that carried the token fails here.
    """
    framed = streams.encode(streams.notification(_delivery(detail=detail)))

    assert _TOKEN.encode() not in framed
    assert b"delivery_id" not in framed


def test_a_notification_value_carries_the_two_texts_a_user_would_be_shown() -> None:
    """ADR-0130 §2 makes ``summary`` and ``detail`` "the only free text… what the
    *user* would be shown", and §9 has them rendered exactly as a reply is."""
    value = streams.notification(_delivery())

    assert value["summary"] == "Standup starts in five minutes"
    assert value["detail"] == "what else there is to say"
    assert value["notification_class"] == "calendar-upcoming"


def test_a_notification_value_carries_no_evidence_the_page_could_present_as_a_ruling() -> None:
    """ADR-0175 §12 records ADR-0130 as *unreached*: this surface "reads no
    notification's summary, detail, confidence, sensitivity or references, and
    re-judges no disposition" beyond rendering what the hub disposed.

    ADR-0130 §4 keeps the confidence, the summary and the class "evidence, not
    authority", and a page showing a producer's confidence beside a notification
    would be presenting the one as the other — the warrant ADR-0099 §4's floor and
    ADR-0073 §4's before it forbid a surface lending a value.
    """
    value = streams.notification(_delivery())

    assert not {"confidence", "sensitivity", "references", "producer", "candidate_key"} & set(value)


# --- the outcome value carries the turn whole --------------------------------


def test_the_outcome_value_carries_the_view_whole_and_adds_nothing() -> None:
    """§3: "The terminal value carries the ``TurnOutcome`` whole, so all four of
    ADR-0173 §6's shapes are readable at the browser from the two members alone"."""
    view = {"reply": "half an answer", "reply_degraded": True, "steps": []}

    value = streams.outcome(view)

    assert value["outcome"] == view


def test_a_fault_value_carries_its_detail_only_where_there_is_one() -> None:
    """The same shape a refusal body has, so the page describes a fault that arrived
    on a stream with the words it already has for one that arrived as a response."""
    assert streams.fault("hub-unreachable") == {"kind": "fault", "fault": "hub-unreachable"}
    assert streams.fault("hub-unreachable", detail="no hub")["detail"] == "no hub"
