"""The on-device default :class:`~ai_assistant.core.protocols.SpeechTranscriber`.

``MoonshineTranscriber`` decodes the recording a browser sent and runs a local
speech-recognition model over it, so the owner's voice is never sent off-device
merely to be understood. This module is one of the two places ``sherpa_onnx`` is
imported; it is deliberately **not** re-exported from ``ai_assistant.models``, so
importing that package stays cheap.

The model is the **vendored** artifact ``speech_artifact.py`` makes a build input,
packaged inside this distribution and loaded from that path. Nothing here fetches
anything and there is no arbitrary-model path: this class serves the one verified
artifact.

## What it declares, and what it refuses

Both containers ADR-0200 §9 admits, because the decode is
:mod:`ai_assistant.models.speech_container`'s and that module reads either. A
recording whose ``media_type`` is not among them is refused with ``ValueError``
**before any I/O**, as ADR-0200 §1 requires — and the declared type picks the
demuxer, so a value that lies about its container is refused rather than
re-interpreted.

## The backend seam

``sherpa_onnx`` reaches this class through one narrow seam,
:class:`MoonshineBackend`, and the real one is the default — production
construction is unchanged and still runs the real model. The seam exists so the
*adapter* layer above it can run the shared ``SpeechTranscriberContract`` against
a deterministic stub, in :class:`~ai_assistant.models.fastembed_embedder`'s shape
and for its reason: patching the library out would assert properties of the patch
rather than of this adapter. The real engine is exercised separately, end to end
and offline, which is ADR-0200 §13's second clause.

## Where the blocking work runs (ADR-0200 §5, ADR-0118 §7)

The container decode, the lazy model load and inference are handed to a **daemon
thread this transcriber owns**, never to the event loop's default executor, and
the number of abandoned workers is bounded. The mechanism lives in
:mod:`ai_assistant.models._embed_worker`, whose docstring carries the reasoning.
The deadline is *not* here: it is
:class:`~ai_assistant.models.bounded_speech.BoundedSpeechTranscriber`, which the
composition root wires, so that it composes over every implementation rather than
binding this one (ADR-0200 §1, ADR-0118 §2).

## Nothing here retains the recording (ADR-0200 §8)

No message this module writes carries the audio, a fragment of it, or a length
that would let one be reconstructed — and **no message it writes was authored
anywhere else**. Every ``SpeechError`` below is raised with this project's own
text and the underlying exception attached only as ``__cause__``, never
interpolated, because a library's message is untrusted text on this path and
ADR-0200 §8 forbids writing one down. Suppressing the chain entirely is the
*orchestration* boundary's job, not this seam's (ADR-0200 §4).
"""

from __future__ import annotations

import base64
import threading
from typing import TYPE_CHECKING, Protocol

import sherpa_onnx

from ai_assistant.core.errors import SpeechError
from ai_assistant.core.types import SpokenAudioFormat
from ai_assistant.models._embed_worker import OwnedWorkers, WorkersExhaustedError
from ai_assistant.models.speech_artifact import (
    MOONSHINE_TINY_EN_INT8,
    SpeechArtifactError,
    packaged_artifact_dir,
)
from ai_assistant.models.speech_container import ContainerError, decode_mono

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np
    from numpy.typing import NDArray

    from ai_assistant.core.types import EncodableText, SpokenAudio

#: What the vendored model expects, in hertz. Not configurable: a recording
#: resampled to anything else is a recording this model was not trained on.
_MODEL_SAMPLE_RATE = 16_000

#: How many threads the engine may use for one call. One, deliberately: the seam
#: is invoked concurrently and every call already has a thread of its own, so a
#: per-call thread pool would multiply the hub's thread count by this figure for
#: latency the milestone has not asked for.
_ENGINE_THREADS = 1


class MoonshineModel(Protocol):
    """A loaded recogniser: mono 16 kHz samples in, words out."""

    def recognise(self, samples: NDArray[np.float32]) -> str:
        """Return the words heard in ``samples``, which are mono at 16 kHz."""
        ...


class MoonshineBackend(Protocol):
    """The one seam ``sherpa_onnx`` reaches this adapter through."""

    def load(self) -> MoonshineModel:
        """Load the vendored recogniser.

        Returns:
            The loaded model.

        Raises:
            Exception: Whatever the backend raised. The adapter translates it.
        """
        ...


class _SherpaMoonshineModel:
    """The real recogniser, wrapped so the seam above is one method."""

    def __init__(self, recognizer: sherpa_onnx.OfflineRecognizer) -> None:
        """Hold a constructed recogniser.

        Args:
            recognizer: The loaded engine.
        """
        self._recognizer = recognizer

    def recognise(self, samples: NDArray[np.float32]) -> str:
        """Return the words heard in ``samples``.

        Args:
            samples: Mono float samples at 16 kHz.

        Returns:
            The transcript, exactly as the engine produced it.
        """
        stream = self._recognizer.create_stream()
        stream.accept_waveform(_MODEL_SAMPLE_RATE, samples)
        self._recognizer.decode_stream(stream)
        text: str = stream.result.text
        return text


class _SherpaMoonshineBackend:
    """Builds the real recogniser from the vendored artifact."""

    def __init__(self, directory: Path) -> None:
        """Hold the directory the artifact was packaged into.

        Args:
            directory: The vendored model directory.
        """
        self._directory = directory

    def load(self) -> MoonshineModel:
        """Construct the engine over the packaged files.

        Returns:
            The loaded model.

        Raises:
            SpeechArtifactError: If a file the engine needs is absent. Checked
                here rather than left to the library, so a missing build input
                reads as a build input rather than as an inference failure.
        """
        for name in ("preprocess.onnx", "encode.int8.onnx", "tokens.txt"):
            if not (self._directory / name).is_file():
                msg = (
                    f"the vendored speech-recognition artifact is incomplete: "
                    f"{name!r} is missing from {self._directory}"
                )
                raise SpeechArtifactError(msg)
        return _SherpaMoonshineModel(
            sherpa_onnx.OfflineRecognizer.from_moonshine(
                preprocessor=str(self._directory / "preprocess.onnx"),
                encoder=str(self._directory / "encode.int8.onnx"),
                uncached_decoder=str(self._directory / "uncached_decode.int8.onnx"),
                cached_decoder=str(self._directory / "cached_decode.int8.onnx"),
                tokens=str(self._directory / "tokens.txt"),
                num_threads=_ENGINE_THREADS,
                provider="cpu",
                debug=False,
            )
        )


class MoonshineTranscriber:
    """A ``SpeechTranscriber`` over the vendored on-device recognition model.

    Structurally implements
    :class:`~ai_assistant.core.protocols.SpeechTranscriber`, so it stands in
    anywhere the contract is expected.
    """

    def __init__(self, *, backend: MoonshineBackend | None = None) -> None:
        """Build the transcriber.

        Nothing is loaded here: construction stays offline and cheap, and the
        model files are read on the first :meth:`transcribe`, inside the worker
        that call owns. That is ADR-0118 §4's shape — the deadline the
        composition root wraps this in therefore bounds the cold load too, rather
        than being escaped by it.

        Args:
            backend: The seam the engine is reached through. Defaults to the real
                one, over the vendored artifact.
        """
        self._backend: MoonshineBackend = backend or _SherpaMoonshineBackend(
            packaged_artifact_dir(MOONSHINE_TINY_EN_INT8)
        )
        self._model: MoonshineModel | None = None
        self._load_lock = threading.Lock()
        self._workers = OwnedWorkers(thread_name="moonshine-transcribe", subject="transcription")

    @property
    def formats(self) -> frozenset[SpokenAudioFormat]:
        """Every container this transcriber can decode, which is both of them.

        The decode is :mod:`ai_assistant.models.speech_container`'s rather than
        the engine's — the engine consumes bare samples and knows nothing about
        containers — so what this seam supports is what that module reads.
        """
        return frozenset(SpokenAudioFormat)

    async def transcribe(self, audio: SpokenAudio) -> EncodableText:
        """Return the words heard in ``audio``.

        Args:
            audio: The recording.

        Returns:
            The transcript, unnormalised — or a blank string where the recording
            carried no words, which ADR-0200 §1 makes a result rather than a
            failure.

        Raises:
            ValueError: If ``audio.media_type`` is not in :attr:`formats`. Raised
                before any I/O, base64 decoding included.
            SpeechError: If the recording could not be read, or the engine could
                not be loaded or run. Raised with this project's own message; the
                underlying failure is attached as ``__cause__`` and never
                interpolated (ADR-0200 §8).
        """
        if audio.media_type not in self.formats:
            msg = (
                f"this transcriber decodes "
                f"{', '.join(sorted(item.value for item in self.formats))}, "
                f"and was handed {audio.media_type.value}"
            )
            raise ValueError(msg)
        # Read off the argument before the first await, which is ADR-0065's
        # snapshot — trivially satisfied here, since a `SpokenAudio` is frozen and
        # holds only scalars, but taken explicitly so the worker closes over
        # values rather than over the caller's object.
        content = audio.content
        media_type = audio.media_type
        try:
            return await self._workers.run(lambda: self._transcribe_sync(content, media_type))
        except WorkersExhaustedError as exc:
            msg = "every transcription worker slot is occupied, so this call is refused"
            raise SpeechError(msg) from exc

    def _transcribe_sync(self, content: str, media_type: SpokenAudioFormat) -> str:
        """Decode the container and run the engine, on the worker's thread."""
        try:
            data = base64.b64decode(content, validate=True)
        except ValueError as exc:
            # Unreachable through `SpokenAudio`, whose validator already decoded
            # this value. Kept because the argument's *type* is what guarantees
            # that, and a caller reaching this method with a bare string would
            # otherwise get a `binascii.Error` out of a seam that declares
            # `SpeechError`.
            msg = "the recording's base64 did not decode"
            raise SpeechError(msg) from exc
        try:
            samples = decode_mono(data, media_type=media_type, sample_rate=_MODEL_SAMPLE_RATE)
        except ContainerError as exc:
            msg = f"the recording could not be decoded as {media_type.value}"
            raise SpeechError(msg) from exc
        if samples.size == 0:
            # A container with no audio frames is not a failure: it carried no
            # words, which ADR-0200 §1 makes a blank return.
            return ""
        try:
            return self._loaded().recognise(samples)
        except SpeechError:
            raise
        except Exception as exc:
            msg = "the speech-recognition engine could not transcribe this recording"
            raise SpeechError(msg) from exc

    def _loaded(self) -> MoonshineModel:
        """Return the loaded model, loading it once under this object's lock."""
        with self._load_lock:
            if self._model is None:
                try:
                    self._model = self._backend.load()
                except SpeechArtifactError as exc:
                    msg = "the vendored speech-recognition model could not be loaded"
                    raise SpeechError(msg) from exc
                except Exception as exc:
                    msg = "the speech-recognition engine could not be started"
                    raise SpeechError(msg) from exc
            return self._model
