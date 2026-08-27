"""Reading and writing the two containers ADR-0200 §9 admits.

The speech seams exchange :class:`~ai_assistant.core.types.SpokenAudio` — a
container-and-codec a browser produces or plays — while every inference engine
consumes and produces bare mono PCM. This module is the whole of the translation
between the two, so :mod:`ai_assistant.models.moonshine_transcriber` and
:mod:`ai_assistant.models.vits_synthesizer` stay about their engines.

**The declared media type picks the demuxer; the bytes never do.** Both entry
points below name the container format to the underlying library rather than
letting it probe, so a value whose ``media_type`` says ``audio/webm;codecs=opus``
is read as WebM or refused, and cannot be re-interpreted as something else by an
input that lies. That is what makes ADR-0200 §1's ``formats`` check load-bearing
rather than advisory: the property a transcriber declares support for is the
property the decode is actually attempted under.

**Nothing here echoes the audio, and nothing here logs it** (ADR-0200 §8). Every
refusal names the class of defect and the container, never a byte of the value —
which matters most on this path, because a recording that fails to parse is
exactly the input whose refusal a caller renders and a log records.

**A decode is bounded before it is materialised.** A container is a compressed
representation, so a small body can describe a very long recording; ADR-0200 §6's
byte bound is enforced by the caller on the encoded form and says nothing about
what it expands to. :data:`_MAX_DECODED_SAMPLES` is this module's own ceiling on
what it will hold in memory, and it is deliberately far above any recording
ADR-0200 §6's default admits, so it bounds a hostile input rather than a real one.
"""

from __future__ import annotations

import fractions
import io
from typing import TYPE_CHECKING, Final

import av
import numpy as np

from ai_assistant.core.types import SpokenAudioFormat

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

#: The libav container name and the audio codec each admitted media type maps to.
#: The codec is checked on the way *in* only where the media type names one:
#: ``audio/webm;codecs=opus`` promises Opus, so a WebM carrying anything else is
#: not the value it claims to be, while ``audio/mp4`` names a container and no
#: codec at all and is read as whatever it holds.
_CONTAINERS: Final[dict[SpokenAudioFormat, tuple[str, str, str | None]]] = {
    SpokenAudioFormat.WEBM_OPUS: ("webm", "libopus", "opus"),
    SpokenAudioFormat.MP4: ("mp4", "aac", None),
}

#: What every engine in this package speaks: one channel of 32-bit float samples.
_MONO = "mono"
_FLOAT_PLANAR = "fltp"
_FLOAT_PACKED = "flt"

#: The rate renderings are produced at. 48 kHz because libopus accepts only
#: 8/12/16/24/48 kHz and 48 is its native one, and because using the same rate for
#: both containers keeps one resampling path rather than two.
RENDERING_SAMPLE_RATE: Final = 48_000

#: The most decoded samples one recording may expand to, at whatever rate the
#: caller asked for. Ten minutes at 16 kHz — more than an order of magnitude above
#: the three minutes of speech ADR-0200 §6's 512 KiB default admits, so a real
#: press never meets it and a container claiming hours does.
_MAX_DECODED_SAMPLES: Final = 10 * 60 * 16_000


class ContainerError(Exception):
    """A recording could not be read, or a rendering could not be written.

    An **internal vocabulary** class, in ``models/_embed_worker``'s sense: the
    speech implementations translate it into
    :class:`~ai_assistant.core.errors.SpeechError` at their own seam, because only
    they know what their documented boundary promises (ADR-0200 §1).
    """


def decode_mono(
    data: bytes, *, media_type: SpokenAudioFormat, sample_rate: int
) -> NDArray[np.float32]:
    """Decode one recording to mono float samples at ``sample_rate``.

    Blocking work. Callers run it off the event loop on threads they own
    (ADR-0200 §5, ADR-0118 §7).

    Args:
        data: The recording's octets, exactly as they arrived.
        media_type: What the caller declared the octets to be. Pins the demuxer;
            a value whose bytes are some other container is refused rather than
            re-interpreted.
        sample_rate: The rate the engine wants, in hertz.

    Returns:
        One channel of float samples in ``[-1, 1]``, at ``sample_rate``. Empty
        where the container held no audio frames at all.

    Raises:
        ContainerError: If the octets are not the declared container, hold no
            audio stream, carry a codec the media type forbids, decode to more
            than this module's ceiling, or fail to decode for any other reason.
    """
    container_name, _, required_codec = _CONTAINERS[media_type]
    try:
        with av.open(io.BytesIO(data), mode="r", format=container_name) as container:
            stream = _only_audio_stream(container, media_type)
            _check_codec(stream, required_codec, media_type)
            blocks = _resampled(container, sample_rate)
    except ContainerError:
        raise
    except Exception as exc:
        # Deliberately broad, and deliberately silent about the value. The
        # library raises several unrelated classes for a malformed input and
        # names none of them in its public API; what a caller can act on is that
        # this recording did not read, which is the whole of what is said.
        msg = f"the recording could not be read as {media_type.value}"
        raise ContainerError(msg) from exc
    if not blocks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(blocks)


def _only_audio_stream(
    container: av.container.InputContainer, media_type: SpokenAudioFormat
) -> av.audio.stream.AudioStream:
    """Return the container's single audio stream, refusing anything else."""
    streams = container.streams.audio
    if len(streams) != 1:
        msg = (
            f"a {media_type.value} recording must carry exactly one audio stream, "
            f"and this one carries {len(streams)}"
        )
        raise ContainerError(msg)
    return streams[0]


def _check_codec(
    stream: av.audio.stream.AudioStream, required: str | None, media_type: SpokenAudioFormat
) -> None:
    """Refuse a stream whose codec the media type does not admit."""
    if required is None:
        return
    if stream.codec_context.name != required:
        msg = (
            f"{media_type.value} names its codec, so a recording carrying "
            f"another one is not the value it claims to be"
        )
        raise ContainerError(msg)


def _resampled(
    container: av.container.InputContainer, sample_rate: int
) -> list[NDArray[np.float32]]:
    """Decode and resample every audio frame, refusing an oversized expansion."""
    resampler = av.AudioResampler(format=_FLOAT_PACKED, layout=_MONO, rate=sample_rate)
    blocks: list[NDArray[np.float32]] = []
    total = 0
    for frame in container.decode(audio=0):
        total = _collect(resampler.resample(frame), blocks, total)
    # `resample(None)` flushes whatever the resampler still holds; without it a
    # short recording can come back a fraction shorter than it really is.
    _collect(resampler.resample(None), blocks, total)
    return blocks


def _collect(
    frames: Sequence[av.audio.frame.AudioFrame], blocks: list[NDArray[np.float32]], total: int
) -> int:
    """Append each frame's samples, refusing once the ceiling is passed."""
    for frame in frames:
        samples = frame.to_ndarray().reshape(-1).astype(np.float32, copy=False)
        total += int(samples.size)
        if total > _MAX_DECODED_SAMPLES:
            msg = (
                f"the recording decodes to more than {_MAX_DECODED_SAMPLES} samples, "
                f"which is past what this seam will hold in memory"
            )
            raise ContainerError(msg)
        blocks.append(samples)
    return total


def encode_mono(
    samples: NDArray[np.float32], *, sample_rate: int, media_type: SpokenAudioFormat
) -> bytes:
    """Encode mono float samples as one whole container.

    Blocking work, like :func:`decode_mono`.

    Args:
        samples: One channel of float samples in ``[-1, 1]``.
        sample_rate: The rate ``samples`` are at, in hertz.
        media_type: The container-and-codec to produce.

    Returns:
        The container's octets, complete and playable.

    Raises:
        ContainerError: If the rendering could not be written.
    """
    container_name, codec_name, _ = _CONTAINERS[media_type]
    buffer = io.BytesIO()
    try:
        with av.open(buffer, mode="w", format=container_name) as container:
            stream = container.add_stream(codec_name, rate=RENDERING_SAMPLE_RATE, layout=_MONO)
            if not isinstance(stream, av.audio.stream.AudioStream):
                # Unreachable for either entry in `_CONTAINERS`, both of which
                # name audio codecs. Stated rather than asserted because the
                # library types this call as a union over all three stream kinds,
                # and a silent `cast` here would be the one place a mistyped
                # constant became a crash inside ffmpeg rather than a refusal.
                msg = f"{codec_name!r} is not an audio codec"
                raise ContainerError(msg)
            resampler = av.AudioResampler(
                format=stream.format.name, layout=_MONO, rate=RENDERING_SAMPLE_RATE
            )
            source = av.AudioFrame.from_ndarray(
                np.ascontiguousarray(samples.reshape(1, -1), dtype=np.float32),
                format=_FLOAT_PLANAR,
                layout=_MONO,
            )
            source.sample_rate = sample_rate
            source.time_base = fractions.Fraction(1, sample_rate)
            source.pts = 0
            for frame in [*resampler.resample(source), *resampler.resample(None)]:
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
    except ContainerError:
        raise
    except Exception as exc:
        msg = f"the rendering could not be written as {media_type.value}"
        raise ContainerError(msg) from exc
    return buffer.getvalue()
