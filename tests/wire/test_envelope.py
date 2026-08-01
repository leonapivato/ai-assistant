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
    ACK_BUILD,
    ACK_MAX_FRAME_BYTES,
    ACK_READY,
    ACK_VERSION,
    CONNECT_CLIENT,
    CONNECT_VERSION,
    MAX_CORRELATION_ID_BYTES,
    MAX_IDENTIFIER_BYTES,
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


def test_an_over_long_client_identifier_is_refused() -> None:
    """ADR-0085 §8d's per-member bound: 64 bytes for either identifier."""
    with pytest.raises(ValueError, match=str(MAX_IDENTIFIER_BYTES)):
        connect_payload(client="x" * 400)


def test_a_member_nobody_bounded_still_cannot_widen_the_handshake() -> None:
    """ADR-0085 §8d bounds the payload, not its members one at a time.

    "Two separate members turned out to be unbounded on inspection, which is
    evidence that inspection is not a reliable way to enumerate them" — and a later
    protocol version may add a fifth that no per-member sentence would reach. So the
    case that matters is a member no rule names, which is what this stands in for:
    the aggregate refuses it even though every *named* member is inside its own
    bound.
    """
    future = {
        CONNECT_VERSION: PROTOCOL_VERSION,
        CONNECT_CLIENT: "assistant-cli",
        "something_a_later_version_added": "y" * 300,
    }
    with pytest.raises(UndecodableFrameError, match=str(CONNECT_PAYLOAD_BYTES)):
        read_connect(future)


def test_a_received_handshake_payload_is_held_to_the_same_bound() -> None:
    """The reader is bound too, and the asymmetry is what made this worth closing.

    §8d states the bound flatly over "each connect-exchange payload — the request
    and the reply alike", and a reader that accepted what the builder refuses would
    be more permissive than the contract on the one exchange whose whole job is to
    bound itself — letting a peer spend up to ``hub_max_frame_bytes`` on a frame
    that has told the hub nothing yet.
    """
    with pytest.raises(UndecodableFrameError, match=str(MAX_IDENTIFIER_BYTES)):
        read_connect({CONNECT_VERSION: PROTOCOL_VERSION, CONNECT_CLIENT: "x" * 100})
    with pytest.raises(UndecodableFrameError, match=str(MAX_IDENTIFIER_BYTES)):
        read_connect_ack(
            {
                ACK_VERSION: PROTOCOL_VERSION,
                ACK_BUILD: "b" * 100,
                ACK_READY: True,
                ACK_MAX_FRAME_BYTES: 1024,
            }
        )


def test_a_build_identifier_is_trimmed_on_bytes_and_not_on_characters() -> None:
    """The bound exists so the reply fits the frame-size floor, and a floor is bytes.

    A character count is the tempting spelling and the wrong one: 64 non-ASCII
    characters are more than 64 bytes, so a character-trimmed identifier would
    still overrun what the floor was proved against.
    """
    payload = connect_ack_payload(build="é" * 100, max_frame_bytes=1024)
    assert len(str(payload[ACK_BUILD]).encode()) <= MAX_IDENTIFIER_BYTES
    read_connect_ack(payload)


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
