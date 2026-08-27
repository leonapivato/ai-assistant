"""Tests for the on-device voice (ADR-0200 §1, §5).

The transcriber's tests in the output direction, and their module docstring
carries the three-way offline split those tests and these both use. What is
particular here is the end-to-end case: text in, **playable** audio out, over the
real voice, with the network denied — and "playable" is asserted by actually
demuxing and decoding the container rather than by measuring its length.

That the audio is an *audible rendering of the text* is this seam's obligation
under ADR-0200 §4 and cannot be discharged by any conformance suite, so it is
discharged where the transcriber's module discharges it: one case speaks a
sentence and the real recogniser hears it back.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import TYPE_CHECKING

import numpy as np
import pytest
from network_guard import network_denied
from speech_synthesizer_contract import SpeechSynthesizerContract

from ai_assistant.core.errors import SpeechError
from ai_assistant.core.types import SpokenAudioFormat
from ai_assistant.models._embed_worker import _MAX_WORKERS
from ai_assistant.models.bounded_speech import BoundedSpeechSynthesizer
from ai_assistant.models.speech_artifact import SpeechArtifactError
from ai_assistant.models.speech_container import decode_mono
from ai_assistant.models.supertonic_synthesizer import (
    SupertonicSynthesizer,
    SupertonicVoice,
)
from ai_assistant.testing.cancellation import ThreadSuspension

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.protocols import SpeechSynthesizer
    from ai_assistant.testing.cancellation import SuspendedCall

_STUB_RATE = 22_050
_LIVENESS_SECONDS = 10.0

_SPOKEN_SENTENCE = "Your dentist appointment is on Thursday afternoon."


class _StubVoice:
    """A voice that renders a tone whose length grows with the text."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    @property
    def sample_rate(self) -> int:
        return _STUB_RATE

    def speak(self, text: str) -> np.ndarray:
        self.spoken.append(text)
        samples = max(_STUB_RATE // 10, _STUB_RATE * len(text) // 40)
        steps = np.linspace(0.0, samples / _STUB_RATE, samples, endpoint=False, dtype=np.float32)
        return (0.2 * np.sin(2 * np.pi * 440.0 * steps)).astype(np.float32)


class _StubBackend:
    """A backend that hands out one stub voice and counts the loads."""

    def __init__(self, voice: SupertonicVoice | None = None) -> None:
        self.voice = voice if voice is not None else _StubVoice()
        self.loads = 0

    def load(self) -> SupertonicVoice:
        self.loads += 1
        return self.voice


class _FailingBackend:
    """A backend that cannot produce a voice."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def load(self) -> SupertonicVoice:
        raise self._error


class TestSupertonicSynthesizerContract(SpeechSynthesizerContract):
    """Runs the real adapter, over a stub voice, through the shared suite."""

    @pytest.fixture
    def synthesizer(self) -> SpeechSynthesizer:
        return SupertonicSynthesizer(backend=_StubBackend())

    @contextlib.asynccontextmanager
    async def synthesizer_suspended_mid_call(
        self,
    ) -> AsyncIterator[tuple[SpeechSynthesizer, SuspendedCall]]:
        """Park the first call inside the worker thread, as a wedged engine would."""
        suspension = ThreadSuspension()
        armed = threading.Event()
        inner = _StubVoice()

        class _SuspendingVoice:
            @property
            def sample_rate(self) -> int:
                return _STUB_RATE

            def speak(self, text: str) -> np.ndarray:
                if not armed.is_set():  # the first call only; later ones run free
                    armed.set()
                    suspension.hold()
                return inner.speak(text)

        synthesizer = SupertonicSynthesizer(backend=_StubBackend(_SuspendingVoice()))
        try:
            yield synthesizer, suspension
        finally:
            suspension.release()


# --- the adapter -------------------------------------------------------------


def test_it_declares_both_containers() -> None:
    assert SupertonicSynthesizer(backend=_StubBackend()).formats == frozenset(SpokenAudioFormat)


@pytest.mark.parametrize("media_type", list(SpokenAudioFormat), ids=lambda m: m.name)
async def test_the_rendering_is_a_container_that_decodes(
    media_type: SpokenAudioFormat,
) -> None:
    # "Playable" asserted by demuxing rather than by length: a synthesizer that
    # returned the raw samples base64'd would satisfy every length check and be
    # unplayable in the browser this exists for.
    with network_denied():
        rendering = await SupertonicSynthesizer(backend=_StubBackend()).synthesize(
            _SPOKEN_SENTENCE, format=media_type
        )
        decoded = decode_mono(rendering.decoded(), media_type=media_type, sample_rate=16_000)

    assert rendering.media_type is media_type
    assert decoded.size > 1000
    assert np.isfinite(decoded).all()


async def test_the_text_reaches_the_voice_unchanged() -> None:
    # The adapter renders what it was handed: it does not strip, expand, or
    # otherwise pre-process the answer on the way to the engine.
    voice = _StubVoice()
    spoken = "  Bring the paperwork — it's on Thursday.  "

    await SupertonicSynthesizer(backend=_StubBackend(voice)).synthesize(
        spoken, format=SpokenAudioFormat.MP4
    )

    assert voice.spoken == [spoken]


async def test_the_voice_is_loaded_once_and_reused() -> None:
    backend = _StubBackend()
    synthesizer = SupertonicSynthesizer(backend=backend)

    await synthesizer.synthesize("first", format=SpokenAudioFormat.MP4)
    await synthesizer.synthesize("second", format=SpokenAudioFormat.MP4)

    assert backend.loads == 1


def test_construction_loads_nothing() -> None:
    backend = _StubBackend()

    SupertonicSynthesizer(backend=backend)

    assert backend.loads == 0


async def test_a_blank_text_is_refused_locally() -> None:
    # There is no audio of nothing. The declared parameter type is
    # `NonBlankEncodableText` and Python does not enforce it, so the seam does —
    # and as a `ValueError`, because it is a caller error rather than a failure of
    # the engine.
    synthesizer = SupertonicSynthesizer(backend=_StubBackend())

    with pytest.raises(ValueError, match="no audio of nothing"):
        await synthesizer.synthesize("   ", format=SpokenAudioFormat.MP4)


async def test_a_blank_text_never_reaches_the_voice() -> None:
    voice = _StubVoice()

    with pytest.raises(ValueError):  # noqa: PT011 - the message is pinned above
        await SupertonicSynthesizer(backend=_StubBackend(voice)).synthesize(
            "", format=SpokenAudioFormat.MP4
        )

    assert voice.spoken == []


# --- failure translation -----------------------------------------------------


async def test_a_missing_artifact_becomes_a_speech_error() -> None:
    backend = _FailingBackend(SpeechArtifactError("the voice is missing"))

    with pytest.raises(SpeechError, match="could not be loaded"):
        await SupertonicSynthesizer(backend=backend).synthesize(
            "hello", format=SpokenAudioFormat.MP4
        )


async def test_an_engine_that_will_not_start_becomes_a_speech_error() -> None:
    backend = _FailingBackend(RuntimeError("the runtime refused"))

    with pytest.raises(SpeechError, match="could not be started"):
        await SupertonicSynthesizer(backend=backend).synthesize(
            "hello", format=SpokenAudioFormat.MP4
        )


async def test_an_engine_failure_becomes_a_speech_error() -> None:
    class _BrokenVoice:
        @property
        def sample_rate(self) -> int:
            return _STUB_RATE

        def speak(self, text: str) -> np.ndarray:
            msg = "the runtime wedged"
            raise RuntimeError(msg)

    with pytest.raises(SpeechError, match="could not render"):
        await SupertonicSynthesizer(backend=_StubBackend(_BrokenVoice())).synthesize(
            "hello", format=SpokenAudioFormat.MP4
        )


async def test_a_voice_that_produces_nothing_is_a_failure_not_a_silence() -> None:
    # The mirror image of the transcriber's blank return, and deliberately *not*
    # symmetric with it: the caller had something to say, so producing nothing is
    # the engine failing rather than a legitimate result. ADR-0200 §4 has no shape
    # for a silent rendering.
    class _MuteVoice:
        @property
        def sample_rate(self) -> int:
            return _STUB_RATE

        def speak(self, text: str) -> np.ndarray:
            return np.zeros(0, dtype=np.float32)

    with pytest.raises(SpeechError, match="produced no audio"):
        await SupertonicSynthesizer(backend=_StubBackend(_MuteVoice())).synthesize(
            "hello", format=SpokenAudioFormat.MP4
        )


async def test_no_failure_writes_a_message_this_project_did_not_author() -> None:
    # ADR-0200 §8's authorship clause, at this seam. Nothing on this path renders
    # a library's message into what it raises; the cause is chained for diagnosis.
    marker = "recognisable-engine-detail"

    class _LeakyVoice:
        @property
        def sample_rate(self) -> int:
            return _STUB_RATE

        def speak(self, text: str) -> np.ndarray:
            raise RuntimeError(marker)

    with pytest.raises(SpeechError) as caught:
        await SupertonicSynthesizer(backend=_StubBackend(_LeakyVoice())).synthesize(
            "hello", format=SpokenAudioFormat.MP4
        )

    assert marker not in str(caught.value)
    assert isinstance(caught.value.__cause__, RuntimeError)


# --- containment (ADR-0200 §5, ADR-0118 §7) ----------------------------------


async def test_a_wedged_voice_does_not_stall_the_event_loop() -> None:
    """ADR-0200 §5's containment, observed from the loop rather than asserted."""
    suspension = ThreadSuspension()

    class _ParkedVoice:
        @property
        def sample_rate(self) -> int:
            return _STUB_RATE

        def speak(self, text: str) -> np.ndarray:
            suspension.hold()
            return np.zeros(_STUB_RATE, dtype=np.float32)

    bounded = BoundedSpeechSynthesizer(
        SupertonicSynthesizer(backend=_StubBackend(_ParkedVoice())), timeout_seconds=0.2
    )
    ticks = 0

    async def _tick() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0)
            ticks += 1

    try:
        async with asyncio.timeout(_LIVENESS_SECONDS):
            stuck = asyncio.ensure_future(bounded.synthesize("hello", format=SpokenAudioFormat.MP4))
            await _tick()
            with pytest.raises(SpeechError):
                await stuck
    finally:
        suspension.release()

    assert ticks == 5


async def test_every_worker_slot_occupied_is_refused_rather_than_stranding_a_thread() -> None:
    suspension = ThreadSuspension()

    class _ParkedVoice:
        @property
        def sample_rate(self) -> int:
            return _STUB_RATE

        def speak(self, text: str) -> np.ndarray:
            suspension.hold()
            return np.zeros(_STUB_RATE, dtype=np.float32)

    synthesizer = SupertonicSynthesizer(backend=_StubBackend(_ParkedVoice()))
    parked = [
        asyncio.ensure_future(synthesizer.synthesize("hello", format=SpokenAudioFormat.MP4))
        for _ in range(_MAX_WORKERS)
    ]
    try:
        async with asyncio.timeout(_LIVENESS_SECONDS):
            # Polled rather than awaited on an event, for the reason the
            # transcriber's twin of this case gives.
            while synthesizer._workers.live < _MAX_WORKERS:  # noqa: ASYNC110
                await asyncio.sleep(0.01)

            with pytest.raises(SpeechError, match="worker slot is occupied"):
                await synthesizer.synthesize("hello", format=SpokenAudioFormat.MP4)
    finally:
        suspension.release()
        for call in parked:
            call.cancel()
        await asyncio.gather(*parked, return_exceptions=True)


# --- the real voice, offline (ADR-0200 §13) ----------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("media_type", list(SpokenAudioFormat), ids=lambda m: m.name)
async def test_the_real_voice_writes_playable_audio_with_no_socket_opened(
    media_type: SpokenAudioFormat,
) -> None:
    """Text in, playable audio out, over the real voice, with the network denied.

    ADR-0200 §13's second clause for this seam. "Playable" is demuxed and decoded
    here rather than inferred: what the browser will be handed is a container, and
    a rendering that is not one is not a rendering however many bytes it has.
    """
    async with asyncio.timeout(120.0):
        with network_denied():
            rendering = await SupertonicSynthesizer().synthesize(
                _SPOKEN_SENTENCE, format=media_type
            )
            decoded = decode_mono(rendering.decoded(), media_type=media_type, sample_rate=16_000)

    assert rendering.media_type is media_type
    # A sentence of speech, not a click: at 16 kHz this is at least a second.
    assert decoded.size > 16_000
    assert 0.01 < float(np.max(np.abs(decoded))) <= 1.0
