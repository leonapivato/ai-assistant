"""The on-device default :class:`~ai_assistant.core.protocols.SpeechSynthesizer`.

``VitsSynthesizer`` renders an answer as speech with a local model and writes it
into the container the caller asked for, so nothing the assistant says leaves the
device to be spoken. It is :mod:`ai_assistant.models.moonshine_transcriber`'s
sibling and shares every seam-shape decision with it — the backend seam, the owned
worker threads, the deadline living in a decorator rather than here, and the rule
that no message this module writes was authored anywhere else. Read that module's
docstring for the reasoning; only what differs is written down again below.

## The voice is a phoneme model, and that was a measurement

The obvious cheaper candidate is a VITS voice driven from a pronunciation
lexicon: three files instead of 359, and no grapheme-to-phoneme data. It was
measured and **rejected**, because it silently drops every word its lexicon does
not contain — "you have a meeting with Sam at 3pm" renders without the time, and
an unfamiliar name renders without the name. ADR-0200 §4 makes it *this seam's*
obligation that the audio is an audible rendering of the text, and for a personal
assistant the out-of-vocabulary words are exactly the names, numbers and
abbreviations the answer is about. ``speech_artifact.py`` records the comparison
beside the pin.

## What it produces

Both containers ADR-0200 §9 admits, because the encode is
:mod:`ai_assistant.models.speech_container`'s. A ``format`` outside them is
refused with ``ValueError`` before any I/O (ADR-0200 §1), and the returned value's
``media_type`` **equals** the requested one — this module never substitutes a
container it finds easier to write.
"""

from __future__ import annotations

import base64
import threading
from typing import TYPE_CHECKING, Protocol

import numpy as np
import sherpa_onnx

from ai_assistant.core.errors import SpeechError
from ai_assistant.core.types import SpokenAudio, SpokenAudioFormat
from ai_assistant.models._embed_worker import OwnedWorkers, WorkersExhaustedError
from ai_assistant.models.speech_artifact import (
    VITS_PIPER_EN_US_AMY_LOW,
    SpeechArtifactError,
    packaged_artifact_dir,
)
from ai_assistant.models.speech_container import ContainerError, encode_mono

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray

    from ai_assistant.core.types import NonBlankEncodableText

#: How many threads the engine may use for one call. One, for the reason
#: ``moonshine_transcriber`` gives.
_ENGINE_THREADS = 1

#: Which voice of a multi-speaker model to use. The vendored voice has one.
_SPEAKER = 0

#: The rate the vendored voice is rendered at, relative to its trained pace.
_SPEED = 1.0


class VitsVoice(Protocol):
    """A loaded voice: text in, mono float samples out."""

    @property
    def sample_rate(self) -> int:
        """The rate :meth:`speak` produces samples at, in hertz."""
        ...

    def speak(self, text: str) -> NDArray[np.float32]:
        """Return mono float samples of ``text`` being spoken."""
        ...


class VitsBackend(Protocol):
    """The one seam ``sherpa_onnx`` reaches this adapter through."""

    def load(self) -> VitsVoice:
        """Load the vendored voice.

        Returns:
            The loaded voice.

        Raises:
            Exception: Whatever the backend raised. The adapter translates it.
        """
        ...


class _SherpaVitsVoice:
    """The real voice, wrapped so the seam above is one property and one method."""

    def __init__(self, tts: sherpa_onnx.OfflineTts) -> None:
        """Hold a constructed engine.

        Args:
            tts: The loaded engine.
        """
        self._tts = tts

    @property
    def sample_rate(self) -> int:
        """The rate this voice renders at, as the engine reports it."""
        rate: int = self._tts.sample_rate
        return rate

    def speak(self, text: str) -> NDArray[np.float32]:
        """Render ``text``.

        Args:
            text: What to say.

        Returns:
            Mono float samples at :attr:`sample_rate`.
        """
        return np.asarray(
            self._tts.generate(text, sid=_SPEAKER, speed=_SPEED).samples, dtype=np.float32
        )


class _SherpaVitsBackend:
    """Builds the real voice from the vendored artifact."""

    def __init__(self, directory: Path) -> None:
        """Hold the directory the artifact was packaged into.

        Args:
            directory: The vendored voice directory.
        """
        self._directory = directory

    def load(self) -> VitsVoice:
        """Construct the engine over the packaged files.

        Returns:
            The loaded voice.

        Raises:
            SpeechArtifactError: If a file the engine needs is absent, so that a
                missing build input reads as a build input rather than as a
                synthesis failure.
        """
        model = self._directory / "en_US-amy-low.onnx"
        tokens = self._directory / "tokens.txt"
        data_dir = self._directory / "espeak-ng-data"
        for path in (model, tokens):
            if not path.is_file():
                msg = f"the vendored voice is incomplete: {path.name!r} is missing"
                raise SpeechArtifactError(msg)
        if not data_dir.is_dir():
            msg = "the vendored voice is incomplete: its espeak-ng data is missing"
            raise SpeechArtifactError(msg)
        return _SherpaVitsVoice(
            sherpa_onnx.OfflineTts(
                sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                            model=str(model), tokens=str(tokens), data_dir=str(data_dir)
                        ),
                        provider="cpu",
                        num_threads=_ENGINE_THREADS,
                        debug=False,
                    )
                )
            )
        )


class VitsSynthesizer:
    """A ``SpeechSynthesizer`` over the vendored on-device voice.

    Structurally implements
    :class:`~ai_assistant.core.protocols.SpeechSynthesizer`, so it stands in
    anywhere the contract is expected.
    """

    def __init__(self, *, backend: VitsBackend | None = None) -> None:
        """Build the synthesizer.

        Nothing is loaded here, for the reason
        :class:`~ai_assistant.models.moonshine_transcriber.MoonshineTranscriber`
        gives: the cold load belongs inside the first call, where the deadline the
        composition root wraps this in can bound it (ADR-0118 §4).

        Args:
            backend: The seam the engine is reached through. Defaults to the real
                one, over the vendored artifact.
        """
        self._backend: VitsBackend = backend or _SherpaVitsBackend(
            packaged_artifact_dir(VITS_PIPER_EN_US_AMY_LOW)
        )
        self._voice: VitsVoice | None = None
        self._load_lock = threading.Lock()
        self._workers = OwnedWorkers(thread_name="vits-synthesize", subject="synthesis")

    @property
    def formats(self) -> frozenset[SpokenAudioFormat]:
        """Every container this synthesizer can produce, which is both of them."""
        return frozenset(SpokenAudioFormat)

    async def synthesize(
        self,
        text: NonBlankEncodableText,
        *,
        format: SpokenAudioFormat,  # noqa: A002 — ADR-0200 §1 fixes this signature
    ) -> SpokenAudio:
        """Render ``text`` as audio in ``format``.

        Args:
            text: What to say. Non-blank.
            format: The container to produce.

        Returns:
            The rendering, whose ``media_type`` is ``format``.

        Raises:
            ValueError: If ``format`` is not in :attr:`formats`, or if ``text`` is
                blank. Both are raised before any I/O. The second enforces the
                declared parameter type at runtime, which Python does not: a blank
                value is not a shorter thing to say, it is nothing to say, and
                ADR-0200 §4 keeps such a call away from this seam entirely.
            SpeechError: If the voice could not be loaded or run, or the rendering
                could not be written. Raised with this project's own message.
        """
        if format not in self.formats:
            msg = (
                f"this synthesizer produces "
                f"{', '.join(sorted(item.value for item in self.formats))}, "
                f"and was asked for {format.value}"
            )
            raise ValueError(msg)
        if not text.strip():
            msg = "there is no audio of nothing, so a blank text is not something to say"
            raise ValueError(msg)
        spoken = text
        try:
            return await self._workers.run(lambda: self._synthesize_sync(spoken, format))
        except WorkersExhaustedError as exc:
            msg = "every synthesis worker slot is occupied, so this call is refused"
            raise SpeechError(msg) from exc

    def _synthesize_sync(self, text: str, media_type: SpokenAudioFormat) -> SpokenAudio:
        """Render and encode, on the worker's thread."""
        voice = self._loaded()
        try:
            samples = voice.speak(text)
        except Exception as exc:
            msg = "the speech-synthesis engine could not render this text"
            raise SpeechError(msg) from exc
        if samples.size == 0:
            # Not a blank-transcript case in reverse: the caller had something to
            # say and this seam produced nothing, which is a failure of the engine
            # rather than a legitimate silence (ADR-0200 §4 has no shape for one).
            msg = "the speech-synthesis engine produced no audio for this text"
            raise SpeechError(msg)
        try:
            content = encode_mono(samples, sample_rate=voice.sample_rate, media_type=media_type)
        except ContainerError as exc:
            msg = f"the rendering could not be written as {media_type.value}"
            raise SpeechError(msg) from exc
        try:
            return SpokenAudio(
                content=base64.b64encode(content).decode("ascii"), media_type=media_type
            )
        except ValueError as exc:
            # Unreachable: `b64encode` emits padded canonical base64 over the
            # standard alphabet by construction, which is exactly what
            # `Base64Audio` requires. Translated rather than left to escape,
            # because a `ValidationError` out of here would read to a caller as
            # the argument refusal this method documents.
            msg = "the rendering could not be carried as a value"
            raise SpeechError(msg) from exc

    def _loaded(self) -> VitsVoice:
        """Return the loaded voice, loading it once under this object's lock."""
        with self._load_lock:
            if self._voice is None:
                try:
                    self._voice = self._backend.load()
                except SpeechArtifactError as exc:
                    msg = "the vendored voice could not be loaded"
                    raise SpeechError(msg) from exc
                except Exception as exc:
                    msg = "the speech-synthesis engine could not be started"
                    raise SpeechError(msg) from exc
            return self._voice
