"""The on-device default :class:`~ai_assistant.core.protocols.SpeechSynthesizer`.

``SupertonicSynthesizer`` renders an answer as speech with a local model and writes it
into the container the caller asked for, so nothing the assistant says leaves the
device to be spoken. It is :mod:`ai_assistant.models.moonshine_transcriber`'s
sibling and shares every seam-shape decision with it — the backend seam, the owned
worker threads, the deadline living in a decorator rather than here, and the rule
that no message this module writes was authored anywhere else. Read that module's
docstring for the reasoning; only what differs is written down again below.

## The voice takes text, not phonemes

The vendored model is indexed straight off the characters it is handed, so this
module hands it the answer and nothing else — no pronunciation lexicon, no
grapheme-to-phoneme pass, and no dictionary that could quietly not contain a word.
``speech_artifact.py`` records why that decided the choice: the two obvious
alternatives were rejected, one on its licence and one on a measurement showing it
drops the words a personal assistant's answers are most often about.

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
    SUPERTONIC_3_INT8,
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

#: Which of the vendored model's voice styles to speak in. Not configurable at
#: this rung: ADR-0200 §1 says a voice is the implementing lane's to choose, and a
#: setting for it would be a deployment knob nothing has asked for.
_SPEAKER = 0

#: Every file the engine is constructed over, checked for presence before the
#: library is asked — so a missing build input reads as one rather than as an
#: opaque failure from inside the runtime.
_ENGINE_FILES = (
    "duration_predictor.int8.onnx",
    "text_encoder.int8.onnx",
    "vector_estimator.int8.onnx",
    "vocoder.int8.onnx",
    "tts.json",
    "unicode_indexer.bin",
    "voice.bin",
)

#: The rate the vendored voice is rendered at, relative to its trained pace.
_SPEED = 1.0


class SupertonicVoice(Protocol):
    """A loaded voice: text in, mono float samples out."""

    @property
    def sample_rate(self) -> int:
        """The rate :meth:`speak` produces samples at, in hertz."""
        ...

    def speak(self, text: str) -> NDArray[np.float32]:
        """Return mono float samples of ``text`` being spoken."""
        ...


class SupertonicBackend(Protocol):
    """The one seam ``sherpa_onnx`` reaches this adapter through."""

    def load(self) -> SupertonicVoice:
        """Load the vendored voice.

        Returns:
            The loaded voice.

        Raises:
            Exception: Whatever the backend raised. The adapter translates it.
        """
        ...


class _SherpaSupertonicVoice:
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


class _SherpaSupertonicBackend:
    """Builds the real voice from the vendored artifact."""

    def __init__(self, directory: Path) -> None:
        """Hold the directory the artifact was packaged into.

        Args:
            directory: The vendored voice directory.
        """
        self._directory = directory

    def load(self) -> SupertonicVoice:
        """Construct the engine over the packaged files.

        Returns:
            The loaded voice.

        Raises:
            SpeechArtifactError: If a file the engine needs is absent, so that a
                missing build input reads as a build input rather than as a
                synthesis failure.
        """
        paths = {name: self._directory / name for name in _ENGINE_FILES}
        for name, path in paths.items():
            if not path.is_file():
                msg = f"the vendored voice is incomplete: {name!r} is missing"
                raise SpeechArtifactError(msg)
        return _SherpaSupertonicVoice(
            sherpa_onnx.OfflineTts(
                sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        supertonic=sherpa_onnx.OfflineTtsSupertonicModelConfig(
                            duration_predictor=str(paths["duration_predictor.int8.onnx"]),
                            text_encoder=str(paths["text_encoder.int8.onnx"]),
                            vector_estimator=str(paths["vector_estimator.int8.onnx"]),
                            vocoder=str(paths["vocoder.int8.onnx"]),
                            tts_json=str(paths["tts.json"]),
                            unicode_indexer=str(paths["unicode_indexer.bin"]),
                            voice_style=str(paths["voice.bin"]),
                        ),
                        provider="cpu",
                        num_threads=_ENGINE_THREADS,
                        debug=False,
                    )
                )
            )
        )


class SupertonicSynthesizer:
    """A ``SpeechSynthesizer`` over the vendored on-device voice.

    Structurally implements
    :class:`~ai_assistant.core.protocols.SpeechSynthesizer`, so it stands in
    anywhere the contract is expected.
    """

    def __init__(self, *, backend: SupertonicBackend | None = None) -> None:
        """Build the synthesizer.

        Nothing is loaded here, for the reason
        :class:`~ai_assistant.models.moonshine_transcriber.MoonshineTranscriber`
        gives: the cold load belongs inside the first call, where the deadline the
        composition root wraps this in can bound it (ADR-0118 §4).

        Args:
            backend: The seam the engine is reached through. Defaults to the real
                one, over the vendored artifact.
        """
        self._backend: SupertonicBackend = backend or _SherpaSupertonicBackend(
            packaged_artifact_dir(SUPERTONIC_3_INT8)
        )
        self._voice: SupertonicVoice | None = None
        self._load_lock = threading.Lock()
        self._workers = OwnedWorkers(thread_name="supertonic-synthesize", subject="synthesis")

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
            rate = voice.sample_rate
        except Exception as exc:
            # Read in its own guarded step rather than inline in the call below.
            # It is a *property on the engine*, so it can fail for every reason
            # `speak` can — and evaluated as an argument it would escape the arm
            # beneath, which catches only this module's own `ContainerError`. A
            # raw exception out of here would be a failure the seam's declared
            # vocabulary does not cover (ADR-0200 §1). Found by architecture
            # review, round 2.
            msg = "the speech-synthesis engine could not report the rate it renders at"
            raise SpeechError(msg) from exc
        try:
            content = encode_mono(samples, sample_rate=rate, media_type=media_type)
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

    def _loaded(self) -> SupertonicVoice:
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
