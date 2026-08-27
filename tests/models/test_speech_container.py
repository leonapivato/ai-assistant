"""Reading and writing the two containers ADR-0200 §9 admits.

Everything here runs with the network denied, because the whole claim about this
layer is that it is local: a container is demuxed and a rendering is muxed in
memory, and nothing is fetched to do either.
"""

from __future__ import annotations

import numpy as np
import pytest
from network_guard import network_denied

from ai_assistant.core.types import SpokenAudioFormat
from ai_assistant.models.speech_container import (
    RENDERING_SAMPLE_RATE,
    ContainerError,
    decode_mono,
    encode_mono,
)

_TONE_RATE = 22_050
_MODEL_RATE = 16_000


def _tone(seconds: float = 1.0, hertz: float = 440.0) -> np.ndarray:
    steps = np.linspace(0.0, seconds, int(_TONE_RATE * seconds), endpoint=False, dtype=np.float32)
    return (0.2 * np.sin(2 * np.pi * hertz * steps)).astype(np.float32)


@pytest.fixture(params=list(SpokenAudioFormat), ids=lambda member: member.name)
def media_type(request: pytest.FixtureRequest) -> SpokenAudioFormat:
    member: SpokenAudioFormat = request.param
    return member


def test_a_rendering_round_trips_through_its_own_container(
    media_type: SpokenAudioFormat,
) -> None:
    # Not byte-identity — both codecs are lossy, which is the point of using them
    # — but duration and amplitude survive, which is what "playable" means here.
    with network_denied():
        encoded = encode_mono(_tone(), sample_rate=_TONE_RATE, media_type=media_type)
        decoded = decode_mono(encoded, media_type=media_type, sample_rate=_MODEL_RATE)

    assert len(encoded) > 0
    # A second of audio, within the priming/padding a codec is entitled to add.
    assert _MODEL_RATE * 0.9 <= decoded.size <= _MODEL_RATE * 1.2
    assert 0.1 < float(np.max(np.abs(decoded))) < 1.0
    assert np.isfinite(decoded).all()


def test_the_declared_type_picks_the_demuxer_rather_than_the_bytes(
    media_type: SpokenAudioFormat,
) -> None:
    # The security property this module turns on: a value whose `media_type` says
    # one container and whose octets are another is refused, not re-interpreted.
    # Without it, ADR-0200 §1's `formats` check would be advisory.
    other = next(member for member in SpokenAudioFormat if member is not media_type)
    encoded = encode_mono(_tone(0.2), sample_rate=_TONE_RATE, media_type=media_type)

    with pytest.raises(ContainerError, match="could not be read"):
        decode_mono(encoded, media_type=other, sample_rate=_MODEL_RATE)


@pytest.mark.parametrize(
    "octets",
    [b"", b"not audio at all", bytes(512), b"\x1aE\xdf\xa3" + bytes(64)],
    ids=["empty", "text", "zeros", "truncated-webm-header"],
)
def test_octets_that_are_not_a_container_are_refused(
    octets: bytes, media_type: SpokenAudioFormat
) -> None:
    with pytest.raises(ContainerError):
        decode_mono(octets, media_type=media_type, sample_rate=_MODEL_RATE)


def test_a_refusal_never_echoes_the_recording(media_type: SpokenAudioFormat) -> None:
    # ADR-0200 §8, on the path §8's own retention test would miss: a recording
    # that fails to parse is exactly the input whose refusal a caller renders and
    # a log records.
    clip = b"\x00\x01recognisable-clip-marker\x02\x03"

    with pytest.raises(ContainerError) as caught:
        decode_mono(clip, media_type=media_type, sample_rate=_MODEL_RATE)

    assert "recognisable-clip-marker" not in str(caught.value)
    assert repr(clip) not in str(caught.value)


def test_the_rendering_declares_the_rate_it_was_written_at(
    media_type: SpokenAudioFormat,
) -> None:
    # The encoder resamples to one rate for both containers, so a voice at any
    # rate produces a container a browser will play.
    encoded = encode_mono(_tone(0.5), sample_rate=_TONE_RATE, media_type=media_type)
    decoded = decode_mono(encoded, media_type=media_type, sample_rate=RENDERING_SAMPLE_RATE)

    assert RENDERING_SAMPLE_RATE * 0.4 <= decoded.size <= RENDERING_SAMPLE_RATE * 0.7


def test_a_longer_rendering_is_longer(media_type: SpokenAudioFormat) -> None:
    short = encode_mono(_tone(0.2), sample_rate=_TONE_RATE, media_type=media_type)
    long = encode_mono(_tone(2.0), sample_rate=_TONE_RATE, media_type=media_type)

    assert len(long) > len(short)


def test_nothing_here_opens_a_socket(media_type: SpokenAudioFormat) -> None:
    # Asserted rather than assumed: both directions are claims about something
    # *not* happening, and observing the right answer cannot tell a cached fetch
    # from no fetch at all.
    with network_denied():
        encoded = encode_mono(_tone(0.2), sample_rate=_TONE_RATE, media_type=media_type)
        decode_mono(encoded, media_type=media_type, sample_rate=_MODEL_RATE)
