"""What a browser stream carries, and what never appears on one (ADR-0175 §2, §5).

The framing itself is this lane's, so what is pinned here is what the ADR *does*
fix about it — one discriminator, no second claim about what a value is, a terminal
partition a reader can act on, and no ``delivery_id`` anywhere.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from ai_assistant.core.types import (
    DataTier,
    NotificationCandidate,
    NotificationDelivery,
    ReplyChunk,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenRendering,
)
from ai_assistant.interfaces.gateway import streams
from ai_assistant.interfaces.gateway.http import StreamHead, render_stream_head

_AT = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)

#: The token ADR-0131 §4 mints for exactly one device, in the shape that type
#: describes. Distinctive on purpose: every case below searches the whole encoded
#: value for it, so a member added later that happened to carry it would fail here.
_TOKEN = "7." + "b3" * 16


#: A rendering of the summary, in the shape ADR-0200 §9 fixes. Its octets are
#: nothing in particular — what the projection below is about is which two members
#: cross and which do not, and the audio is opaque to every one of them.
_RENDERING = SpokenAudio(content="QUJDRA==", media_type=SpokenAudioFormat.MP4)


def _delivery(
    *,
    detail: str | None = "what else there is to say",
    spoken: SpokenAudio | None = None,
    rendering: SpokenRendering = SpokenRendering.NOT_REQUESTED,
) -> NotificationDelivery:
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
        spoken=spoken,
        spoken_rendering=rendering,
    )


def _rendered() -> NotificationDelivery:
    """One delivery carrying a rendering, which is ADR-0206 §6's ``RENDERED``."""
    return _delivery(spoken=_RENDERING, rendering=SpokenRendering.RENDERED)


def _withheld() -> NotificationDelivery:
    """One ADR-0206 §5 refused to speak: no rendering, and no substitute for one."""
    return _delivery(rendering=SpokenRendering.WITHHELD)


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


def test_the_keep_alive_cadence_is_a_header_in_microseconds_naming_its_unit() -> None:
    """Issue #1442: the figure a browser needs to tell a silent stream from a quiet one.

    ADR-0175 §4 obliges a write on every open delivery stream "at least once per
    ``gateway_notification_budget``" so that "the liveness of the gateway, of its hub
    connection and of the browser's own socket" is "observable at a bounded cadence" —
    but the figure is gateway configuration (§8) and nothing the page read carried it.

    **Microseconds, and the unit is in the name.** That is ``timedelta``'s own
    resolution, so the integer is exact in both directions and no reader rounds it
    through an IEEE-754 double; and a header carrying a bare number whose unit lived
    only in a docstring is the one thing a reader can misread in silence.

    Both halves are spelled out here rather than built from the constant they check,
    because a check assembled from its own subject passes whatever that subject
    becomes.
    """
    assert streams.keep_alive_header(timedelta(seconds=20)) == (
        "X-Assistant-Keep-Alive-Microseconds",
        "20000000",
    )
    assert streams.keep_alive_header(timedelta(microseconds=1))[1] == "1"


def test_the_cadence_is_stated_in_a_head_and_is_no_kind_of_stream_value() -> None:
    """The framing decision, pinned where the kinds are.

    §4's clauses about pending writes and abandonment are about *values*: "at most one
    value pending per stream", and one whose write has not completed when the next is
    due ends the stream. A preamble stating how the stream will be written is not a
    delivery, and making it a value put it under a rule written about a browser that
    had stopped reading — where it ended streams that had merely just opened. In the
    head it takes no place in the ordering and cannot be abandoned.
    """
    assert "open" not in {kind.value for kind in streams.ValueKind}
    assert all("keep_alive" not in kind.value for kind in streams.ValueKind)
    assert "keep_alive" not in json.dumps(streams.alive())


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


# --- ADR-0206 §8: the projection gains `spoken` and nothing else -------------


@pytest.mark.parametrize(
    ("delivery", "identity"),
    [
        pytest.param(_rendered(), "rendered", id="rendered"),
        pytest.param(_withheld(), "withheld", id="withheld"),
    ],
)
def test_the_notification_value_carries_exactly_five_members(
    delivery: NotificationDelivery, identity: str
) -> None:
    """§8: "The value the gateway writes on a delivery stream gains **exactly one
    member**, ``spoken``, and no other. ``streams.notification``'s enumeration is
    otherwise unchanged — ``kind``, ``notification_class``, ``summary`` and
    ``detail`` — and every member it drops today it still drops."

    Enumerated as a whole set rather than asserted member by member, because what §8
    fixes is a *closed* enumeration: a sixth member added by a later lane is the
    failure this catches, and a check that only looked for the five would not see it.
    """
    assert identity in {"rendered", "withheld"}
    assert set(streams.notification(delivery)) == {
        "kind",
        "notification_class",
        "summary",
        "detail",
        "spoken",
    }


@pytest.mark.parametrize(
    "delivery",
    [pytest.param(_rendered(), id="rendered"), pytest.param(_withheld(), id="withheld")],
)
def test_no_token_no_reason_and_no_evidence_crosses_beside_the_rendering(
    delivery: NotificationDelivery,
) -> None:
    """§8: "``spoken_rendering`` does **not** cross to a browser… a member carrying
    *why* one did not would be a value nothing on the page acts on"; and
    "``delivery_id`` still never reaches a browser, and neither do the confidence, the
    sensitivity or the references that projection drops today".

    Searched over the *encoded* value, so a member that carried one of them under
    another name fails here too — which is the same discipline the ``delivery_id``
    case above already applies, extended over the four ADR-0206 §8 names.
    """
    framed = streams.encode(streams.notification(delivery))

    assert _TOKEN.encode() not in framed
    for absent in (b"delivery_id", b"spoken_rendering", b"confidence", b"sensitivity"):
        assert absent not in framed
    assert b"event-1" not in framed


def test_a_rendering_crosses_as_exactly_its_content_and_its_media_type() -> None:
    """§8: "``spoken`` is… an object carrying exactly two members, ``content`` and
    ``media_type``, projected from that value."

    The media type crosses as the string ADR-0200 §9 makes the member's value — "the
    string value is the media type itself, parameters included, so a value that
    reaches an HTTP header or a ``MediaRecorder`` constructor is the member rather
    than a mapping of it" — so the page hands it to a decoder unchanged.
    """
    value = streams.notification(_rendered())
    crossed = json.loads(streams.encode(value))

    assert value["spoken"] == {"content": "QUJDRA==", "media_type": "audio/mp4"}
    assert crossed["spoken"] == {"content": "QUJDRA==", "media_type": "audio/mp4"}


def test_a_delivery_with_no_rendering_carries_the_member_as_null() -> None:
    """§8: "``spoken`` is ``null`` wherever ``NotificationDelivery.spoken`` is
    ``None``… There is no third shape and the member is never omitted, so a page reads
    one key rather than testing for a key's presence."

    Checked on the *encoded* value as well as on the mapping, because "never omitted"
    is a fact about what the browser receives: a projection that dropped the key would
    still satisfy a test that only asked what the value at that key was.
    """
    value = streams.notification(_withheld())

    assert value["spoken"] is None
    assert b'"spoken": null' in streams.encode(value)
