"""The envelope's refusals, and the handshake's two.

ADR-0084 §3 makes the framing and the codec normative "because two implementations
that satisfy every rule above could still be unable to exchange a frame". These are
the rules that stop one frame having two meanings.
"""

from __future__ import annotations

import uuid

import pytest

from ai_assistant.wire.codec import CONNECT_PAYLOAD_BYTES
from ai_assistant.wire.envelope import (
    MAX_CORRELATION_ID_BYTES,
    PROTOCOL_VERSION,
    Envelope,
    FrameKind,
    connect_ack_payload,
    connect_payload,
    decode_envelope,
    encode_envelope,
    read_connect,
    read_connect_ack,
)
from ai_assistant.wire.errors import ProtocolError, UndecodableFrameError


def test_an_envelope_round_trips() -> None:
    """The ordinary case: kind, correlation id, method, payload."""
    envelope = Envelope(
        kind=FrameKind.REQUEST, id="c-1", payload={"record_id": "r-1"}, method="belief"
    )
    assert decode_envelope(encode_envelope(envelope)) == envelope


def test_a_duplicate_member_is_refused() -> None:
    """§3: "the same bytes, two meanings, which is exactly the interoperability
    failure this subsection exists to prevent".

    JSON permits duplicates and decoders disagree about which wins, so
    ``{"kind":"request","kind":"error"}`` could decode as a request in one
    implementation and an error in another. Refusing is "the only option compatible
    with the rule that an undecodable frame closes the connection: a decoder that
    silently picked one would not be undecodable, merely wrong".
    """
    raw = b'{"kind":"request","kind":"error","id":"c-1","payload":null,"method":"forget"}'
    with pytest.raises(UndecodableFrameError, match="duplicate"):
        decode_envelope(raw)


def test_a_duplicate_member_inside_the_payload_is_refused_too() -> None:
    """§3: "in the envelope **and in payload objects alike**"."""
    raw = b'{"kind":"request","id":"c-1","method":"forget","payload":{"a":1,"a":2}}'
    with pytest.raises(UndecodableFrameError, match="duplicate"):
        decode_envelope(raw)


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        (b"\xff\xfe", "UTF-8"),
        (b"not json", "decodable JSON"),
        (b'"a string"', "JSON object"),
        (b'{"kind":"request","id":"c-1"}', "missing required"),
        (b'{"kind":"nope","id":"c-1","payload":null}', "no known kind"),
        (b'{"kind":"request","id":1,"payload":null,"method":"forget"}', "must be a string"),
        (b'{"kind":"request","id":"c-1","payload":null}', "must name a method"),
        (b'{"kind":"result","id":"c-1","payload":null,"method":"forget"}', "must not name"),
        (b'{"kind":"result","id":"c-1","payload":null,"extra":1}', "no protocol version"),
    ],
)
def test_the_undecodable_class_is_closed_rather_than_enumerated(raw: bytes, why: str) -> None:
    """§3 covers "the whole class rather than a list that would go stale".

    Each of these is a frame whose envelope does not decode, so the server's answer
    is to close the connection without a response: "there is no correlation id to
    quote and **no agreed encoding to reply in**".

    The last row is this implementation's own reading of "these members, and no
    others" (ADR-0085 §8a): an unknown member is refused rather than ignored,
    because ADR-0084 §3's exact-match version means the two halves ship together, so
    a member nobody declared is a bug on the writing side rather than a later
    version to accommodate.
    """
    with pytest.raises(UndecodableFrameError, match=why):
        decode_envelope(raw)


def test_a_correlation_id_longer_than_the_reserve_assumes_is_refused() -> None:
    """ADR-0085 §8a bounds it at 36 bytes, and the reserve is computed against that.

    "A frame whose ``id`` is longer is a protocol violation… because the length is
    part of what makes the frame decodable within budget." Without the bound, §8b's
    110-byte worst case is not a worst case.
    """
    over = "x" * (MAX_CORRELATION_ID_BYTES + 1)
    raw = encode_envelope(Envelope(kind=FrameKind.RESULT, id=over, payload=None))
    with pytest.raises(UndecodableFrameError, match="correlation id"):
        decode_envelope(raw)


def test_a_thirty_six_byte_correlation_id_is_admitted() -> None:
    """The discriminating half: the bound refuses what it must and nothing else.

    A UUID string is exactly 36 bytes, so a bound that were off by one would refuse
    every frame this client sends.
    """
    identifier = str(uuid.uuid4())
    assert len(identifier) == MAX_CORRELATION_ID_BYTES
    envelope = Envelope(kind=FrameKind.RESULT, id=identifier, payload=None)
    assert decode_envelope(encode_envelope(envelope)).id == identifier


# --- the connect exchange (ADR-0084 §2) ------------------------------------


def test_a_connect_frame_omits_the_credential_it_does_not_carry() -> None:
    """§2: "a conforming client either omits the member or sends it empty"."""
    payload = connect_payload(client="assistant-cli")
    assert payload["version"] == PROTOCOL_VERSION
    assert "credential" not in payload
    assert read_connect(payload) == (PROTOCOL_VERSION, "assistant-cli")


def test_an_empty_credential_is_accepted_and_a_populated_one_is_refused() -> None:
    """§2, the whole of it, and the reason is stated as a rule for a reason.

    "Accepting-and-ignoring is the alternative and it is the dangerous one: a client
    that presents a credential and is admitted has been told, by admission, that its
    credential was checked. Nothing on this transport checks anything — the ``0600``
    bit is doing the work — so admitting a credentialled connect would manufacture
    exactly that false belief, and it would do so silently on the day someone points
    a future authenticating client at an old hub."
    """
    assert read_connect(connect_payload(client="cli", credential="")) == (PROTOCOL_VERSION, "cli")
    with pytest.raises(ProtocolError, match="no credential"):
        read_connect(connect_payload(client="cli", credential="hunter2"))


def test_either_connect_payload_is_bounded_as_a_whole() -> None:
    """ADR-0085 §8d bounds the payload, not its members one at a time.

    "Two separate members turned out to be unbounded on inspection, which is
    evidence that inspection is not a reliable way to enumerate them" — and a later
    protocol version may add a fifth that no per-member sentence would reach. The
    aggregate is fail-closed in the direction that matters: a member nobody thought
    about cannot silently widen either frame past the floor.
    """
    with pytest.raises(ValueError, match=str(CONNECT_PAYLOAD_BYTES)):
        connect_payload(client="x" * 400)


def test_the_connect_reply_carries_the_hub_s_authoritative_frame_size() -> None:
    """§3: "the client enforces the number it was told" rather than one of its own.

    "A client configured at 32 MiB against a hub at 16 MiB would accept a 20 MiB
    utterance that the hub then refuses on its prefix, and §4's whole move — putting
    the size bound in the *contract* so both implementations agree — would be false
    in the one place it is load-bearing."
    """
    payload = connect_ack_payload(build="1.2.3", max_frame_bytes=1234)
    assert read_connect_ack(payload) == (PROTOCOL_VERSION, 1234)


def test_a_hub_that_is_not_ready_is_reported_rather_than_assumed_away() -> None:
    """The listener only accepts after ADR-0083 §3's step 6, so this cannot happen.

    It is checked anyway because "not ready" arriving through the one field that
    says so must not be read as ready — the failure would be a client proceeding
    against a half-built engine, which §14.2 exists to prevent.
    """
    payload = dict(connect_ack_payload(build="b", max_frame_bytes=1024))
    payload["ready"] = False
    with pytest.raises(ProtocolError, match="not ready"):
        read_connect_ack(payload)
