"""Tests for the on-device transcriber (ADR-0200 §1, §5).

These stay offline in three different ways, and the differences matter:

- Against a **stub** backend the adapter is exercised end to end and run through
  the shared :class:`SpeechTranscriberContract` — the container decode, the
  format refusal, the load-once-and-reuse of a model, the failure translation.
  Those are the properties that could regress on a library bump or a refactor of
  this module, and a stub is what lets them run in a fast gate.
- Against the **real** engine, one case transcribes a real recording and asserts
  the words come back. That is ADR-0200 §13's second clause, which the
  conformance suite explicitly does not discharge: the suite cannot assert that a
  transcript is *what was said*, and this can.
- Every case runs with the network denied, so "no socket opened" is asserted
  rather than assumed.

The recording the real case uses is produced by *this project's own synthesizer*
rather than committed as a fixture. That is deliberate and is the stronger test:
it exercises both seams over their real engines in one pass, and it cannot go
stale against a re-pinned voice the way a recorded clip would.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import threading
import time
from typing import TYPE_CHECKING

import numpy as np
import pytest
from network_guard import network_denied
from speech_transcriber_contract import SpeechTranscriberContract

from ai_assistant.core.errors import SpeechError
from ai_assistant.core.types import SpokenAudio, SpokenAudioFormat
from ai_assistant.models._embed_worker import _MAX_WORKERS
from ai_assistant.models.bounded_speech import BoundedSpeechTranscriber
from ai_assistant.models.moonshine_transcriber import MoonshineModel, MoonshineTranscriber
from ai_assistant.models.speech_artifact import SpeechArtifactError
from ai_assistant.models.speech_container import encode_mono
from ai_assistant.models.supertonic_synthesizer import SupertonicSynthesizer
from ai_assistant.testing.cancellation import ThreadSuspension

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.protocols import SpeechTranscriber
    from ai_assistant.testing.cancellation import SuspendedCall

#: What the stub model answers. Deliberately not something a real recogniser would
#: produce from a tone, so a case passing only because the real engine agreed with
#: the stub would be visible.
_STUB_TRANSCRIPT = "the stub heard this"

_TONE_RATE = 22_050

#: A bound on failure, never on a passing run: a wedged seam that is not contained
#: would hang the suite instead of failing it.
_LIVENESS_SECONDS = 10.0

#: The words the real end-to-end case says and expects to hear back. Ordinary
#: words rather than a tongue-twister: what is being measured is that the pipeline
#: is wired, not the model's word error rate.
_SPOKEN_SENTENCE = "The dentist appointment is on Thursday afternoon."

#: The content words of that sentence, and how many of them the transcript must
#: carry. Not all four (#1717): int8 inference is not bit-reproducible, and asking
#: for all four blocked two merges in one day on changes that touched nothing near
#: this seam — gate run 33165593987 (PR #1710, docs-only) lost `dentist`, gate run
#: 33207357743 (PR #1754) lost `appointment`, and each tree then passed a rerun of
#: the very same bytes. 2 of 20 consecutive local runs on this branch's base failed
#: the same way. So the loss is sporadic and lands on a different word each time:
#: noise, not an engine that has stopped hearing a word. One transcription cannot
#: tell those two apart, which is why requiring all four bought no detection here,
#: only a false alarm every ten-or-so runs. Three of four keeps what ADR-0200 §13's
#: second normative clause asks of this case — audio in, *this* transcript out,
#: over the real engines, with the network denied — while tolerating the one loss
#: that clause never claimed to measure. The full transcript is in the failure
#: message either way, so a genuine regression stays legible and reopens #1717 with
#: the evidence these two runs could not carry.
_HEARD_CONTENT_WORDS = frozenset({"dentist", "appointment", "thursday", "afternoon"})
_HEARD_CONTENT_WORDS_REQUIRED = 3

#: The real-engine case's wall-clock budget, and a ceiling on pathology rather
#: than a latency target. It has to bound the model load as well as the
#: inference: `MoonshineTranscriber.__init__` loads nothing, so the files are
#: read inside the first `transcribe` — ADR-0118 §4's shape, which that
#: constructor's own docstring names — and a budget the cold load sat outside
#: would bound the cheaper half of this case.
#:
#: The figure is measured rather than picked (#2091, filed on the hypothesis
#: that a `just test-fast` run had exhausted it under CPU contention). On this
#: project's 8-core box the case costs 2.4-2.6s serially; 7.7s inside a whole
#: `just test-fast` run, where a dozen unbounded cases cost more and the slowest
#: costs 23s; and from there it scales with oversubscription rather than with
#: anything about the engines — 14.2s against 24 runnable processes on 8 cores
#: (3x, which is exactly what `just test-fast`'s own three-slot lease permits),
#: 28.9s against 48 (7x, which it does not). Reaching 120s that way needs ~40x,
#: an order of magnitude past what the recipe can produce.
#:
#: So the budget stays where it was. Tightening it toward the measured cost
#: would trade the ceiling for a latency target and buy the flake #2091 feared,
#: and widening a bound nothing has been shown to approach would only make the
#: wedge it exists to catch take longer to report.
_REAL_ENGINE_SECONDS = 120.0


def _tone(seconds: float = 0.4) -> np.ndarray:
    steps = np.linspace(0.0, seconds, int(_TONE_RATE * seconds), endpoint=False, dtype=np.float32)
    return (0.2 * np.sin(2 * np.pi * 440.0 * steps)).astype(np.float32)


def _recording(
    media_type: SpokenAudioFormat = SpokenAudioFormat.WEBM_OPUS, *, seconds: float = 0.4
) -> SpokenAudio:
    """A real container the adapter's decode step will actually read."""
    octets = encode_mono(_tone(seconds), sample_rate=_TONE_RATE, media_type=media_type)
    return SpokenAudio(content=base64.b64encode(octets).decode("ascii"), media_type=media_type)


class _StubModel:
    """A recogniser that answers without a model."""

    def __init__(self) -> None:
        self.heard: list[int] = []

    def recognise(self, samples: np.ndarray) -> str:
        self.heard.append(int(samples.size))
        return _STUB_TRANSCRIPT


class _StubBackend:
    """A backend that hands out one stub model and counts the loads."""

    def __init__(self, model: MoonshineModel | None = None) -> None:
        self.model = model if model is not None else _StubModel()
        self.loads = 0

    def load(self) -> MoonshineModel:
        self.loads += 1
        return self.model


class _FailingBackend:
    """A backend that cannot produce a model."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def load(self) -> MoonshineModel:
        raise self._error


class TestMoonshineTranscriberContract(SpeechTranscriberContract):
    """Runs the real adapter, over a stub engine, through the shared suite."""

    @pytest.fixture
    def transcriber(self) -> SpeechTranscriber:
        return MoonshineTranscriber(backend=_StubBackend())

    @pytest.fixture
    def recording(self) -> SpokenAudio:
        return _recording()

    @contextlib.asynccontextmanager
    async def transcriber_suspended_mid_call(
        self,
    ) -> AsyncIterator[tuple[SpeechTranscriber, SuspendedCall, SpokenAudio]]:
        """Park the first call inside the worker thread, as a wedged engine would.

        Arranged rather than raced for: a stub call resolves inside one event-loop
        turn, so a case that merely cancels a freshly started task would find it
        already finished and assert nothing.
        """
        suspension = ThreadSuspension()
        armed = threading.Event()

        class _SuspendingModel:
            def recognise(self, samples: np.ndarray) -> str:
                if not armed.is_set():  # the first call only; later ones run free
                    armed.set()
                    suspension.hold()
                return _STUB_TRANSCRIPT

        transcriber = MoonshineTranscriber(backend=_StubBackend(_SuspendingModel()))
        try:
            yield transcriber, suspension, _recording()
        finally:
            suspension.release()


# --- the adapter -------------------------------------------------------------


def test_it_declares_both_containers() -> None:
    # What it can decode is `speech_container`'s capability, not the engine's:
    # the engine consumes bare samples and knows nothing about containers.
    assert MoonshineTranscriber(backend=_StubBackend()).formats == frozenset(SpokenAudioFormat)


@pytest.mark.parametrize("media_type", list(SpokenAudioFormat), ids=lambda m: m.name)
async def test_it_decodes_either_container_before_the_engine_sees_it(
    media_type: SpokenAudioFormat,
) -> None:
    model = _StubModel()

    with network_denied():
        assert (
            await MoonshineTranscriber(backend=_StubBackend(model)).transcribe(
                _recording(media_type)
            )
            == _STUB_TRANSCRIPT
        )

    # The engine was handed samples, and enough of them to be the recording rather
    # than an empty array the adapter shortcut past.
    [heard] = model.heard
    assert heard > 1000


async def test_the_model_is_loaded_once_and_reused() -> None:
    backend = _StubBackend()
    transcriber = MoonshineTranscriber(backend=backend)

    await transcriber.transcribe(_recording())
    await transcriber.transcribe(_recording())

    assert backend.loads == 1


async def test_construction_loads_nothing() -> None:
    # ADR-0118 §4: the cold load belongs inside the first call, where the deadline
    # the composition root wraps this in can bound it. A load at construction
    # would escape that bound entirely.
    backend = _StubBackend()

    MoonshineTranscriber(backend=backend)

    assert backend.loads == 0


async def test_a_blank_transcript_is_passed_through_unchanged() -> None:
    # ADR-0200 §1 makes a blank return a result rather than a failure: the
    # recording carried no words. The adapter must not turn one into an error, a
    # placeholder, or a stripped-and-rewritten value on the way out.
    class _SilentModel:
        def recognise(self, samples: np.ndarray) -> str:
            return ""

    transcriber = MoonshineTranscriber(backend=_StubBackend(_SilentModel()))

    assert await transcriber.transcribe(_recording()) == ""


async def test_a_transcript_is_carried_byte_for_byte() -> None:
    # ADR-0200 §4's clause about the non-blank case, enforced at the seam that
    # produces the value: nothing on this path strips, trims or case-folds it. An
    # adapter that normalised would make a later comparison against a stored value
    # fail for a reason no caller can see.
    spoken = "  Remind me about the Dentist  "

    class _VerbatimModel:
        def recognise(self, samples: np.ndarray) -> str:
            return spoken

    transcriber = MoonshineTranscriber(backend=_StubBackend(_VerbatimModel()))

    assert await transcriber.transcribe(_recording()) == spoken


# --- failure translation -----------------------------------------------------


async def test_octets_that_are_not_the_declared_container_become_a_speech_error() -> None:
    # A `ContainerError` is an internal vocabulary class; what a caller's
    # `except SpeechError` has to be sufficient for is this seam's boundary.
    bogus = SpokenAudio(
        content=base64.b64encode(b"this is not a container").decode("ascii"),
        media_type=SpokenAudioFormat.WEBM_OPUS,
    )

    with pytest.raises(SpeechError, match="could not be decoded"):
        await MoonshineTranscriber(backend=_StubBackend()).transcribe(bogus)


async def test_a_missing_artifact_becomes_a_speech_error() -> None:
    backend = _FailingBackend(SpeechArtifactError("preprocess.onnx is missing"))

    with pytest.raises(SpeechError, match="could not be loaded"):
        await MoonshineTranscriber(backend=backend).transcribe(_recording())


async def test_an_engine_that_will_not_start_becomes_a_speech_error() -> None:
    backend = _FailingBackend(RuntimeError("the runtime refused"))

    with pytest.raises(SpeechError, match="could not be started"):
        await MoonshineTranscriber(backend=backend).transcribe(_recording())


async def test_an_engine_failure_becomes_a_speech_error() -> None:
    class _BrokenModel:
        def recognise(self, samples: np.ndarray) -> str:
            msg = "the runtime wedged"
            raise RuntimeError(msg)

    with pytest.raises(SpeechError, match="could not transcribe"):
        await MoonshineTranscriber(backend=_StubBackend(_BrokenModel())).transcribe(_recording())


async def test_no_failure_writes_a_message_this_project_did_not_author() -> None:
    # ADR-0200 §8's authorship clause, at this seam: a library's message is
    # untrusted text on this path, and an engine that interpolated the clip it
    # could not decode would have put the recording inside the exception. The
    # cause is chained for diagnosis and never rendered into what we raise.
    marker = "recognisable-clip-marker"

    class _LeakyModel:
        def recognise(self, samples: np.ndarray) -> str:
            raise RuntimeError(marker)

    with pytest.raises(SpeechError) as caught:
        await MoonshineTranscriber(backend=_StubBackend(_LeakyModel())).transcribe(_recording())

    assert marker not in str(caught.value)
    assert isinstance(caught.value.__cause__, RuntimeError)


async def test_a_refusal_names_no_recording() -> None:
    # The `ValueError` path: ADR-0200 §1's local refusal, which must also say
    # nothing about the octets it was handed. Driven through a subclass declaring
    # one container, because the shipped adapter declares both and so has nothing
    # to refuse.
    recording = _recording(SpokenAudioFormat.MP4)

    with pytest.raises(ValueError, match="decodes") as caught:
        await _NarrowTranscriber().transcribe(recording)

    assert recording.content not in str(caught.value)


class _NarrowTranscriber(MoonshineTranscriber):
    """The real adapter, declaring one container, so the refusal path is reachable."""

    def __init__(self) -> None:
        super().__init__(backend=_StubBackend())

    @property
    def formats(self) -> frozenset[SpokenAudioFormat]:
        return frozenset({SpokenAudioFormat.WEBM_OPUS})


# --- containment (ADR-0200 §5, ADR-0118 §7) ----------------------------------


async def test_a_wedged_engine_does_not_stall_the_event_loop() -> None:
    """ADR-0200 §5's containment, observed from the loop rather than asserted.

    The engine is parked inside its worker; the loop must stay live — another
    coroutine runs to completion while the transcription is stuck — and the
    bounded seam must come back with its own expiry rather than hanging.
    """
    suspension = ThreadSuspension()

    class _ParkedModel:
        def recognise(self, samples: np.ndarray) -> str:
            suspension.hold()
            return _STUB_TRANSCRIPT

    bounded = BoundedSpeechTranscriber(
        MoonshineTranscriber(backend=_StubBackend(_ParkedModel())), timeout_seconds=0.2
    )
    ticks = 0

    async def _tick() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0)
            ticks += 1

    try:
        async with asyncio.timeout(_LIVENESS_SECONDS):
            stuck = asyncio.ensure_future(bounded.transcribe(_recording()))
            await _tick()
            with pytest.raises(SpeechError):
                await stuck
    finally:
        suspension.release()

    assert ticks == 5


async def test_every_worker_slot_occupied_is_refused_rather_than_stranding_a_thread() -> None:
    # ADR-0118 §7's bound, which ADR-0200 §5 takes whole: what must not happen is
    # a seam quietly accumulating one stuck thread per call.
    suspension = ThreadSuspension()

    class _ParkedModel:
        def recognise(self, samples: np.ndarray) -> str:
            suspension.hold()
            return _STUB_TRANSCRIPT

    transcriber = MoonshineTranscriber(backend=_StubBackend(_ParkedModel()))
    parked = [
        asyncio.ensure_future(transcriber.transcribe(_recording())) for _ in range(_MAX_WORKERS)
    ]
    try:
        async with asyncio.timeout(_LIVENESS_SECONDS):
            # Polled rather than awaited on an event: what is being waited for
            # is a count inside the dispatcher, and giving it an `asyncio.Event`
            # purely for this case would be test machinery in production code.
            while transcriber._workers.live < _MAX_WORKERS:  # noqa: ASYNC110
                await asyncio.sleep(0.01)

            with pytest.raises(SpeechError, match="worker slot is occupied"):
                await transcriber.transcribe(_recording())
    finally:
        suspension.release()
        for call in parked:
            call.cancel()
        await asyncio.gather(*parked, return_exceptions=True)


# --- the real engine, offline (ADR-0200 §13) ---------------------------------


@pytest.mark.integration
async def test_the_real_engine_hears_real_speech_with_no_socket_opened() -> None:
    """Audio in, transcript out, over both real engines, with the network denied.

    ADR-0200 §13's second clause, and what the conformance suite deliberately
    cannot discharge: that the words come back. The recording is produced by this
    project's own voice, so one case exercises both seams and neither can go stale
    against a re-pinned model.

    An expiry names the leg it died in and what the other leg cost, because the
    one failure ever seen here (#2091) left no record of either and the run that
    would have carried it was gone by the time it was looked for.
    """
    legs: dict[str, float] = {}
    try:
        async with asyncio.timeout(_REAL_ENGINE_SECONDS):
            with network_denied():
                started = time.monotonic()
                spoken = await SupertonicSynthesizer().synthesize(
                    _SPOKEN_SENTENCE, format=SpokenAudioFormat.WEBM_OPUS
                )
                legs["synthesis"] = time.monotonic() - started
                started = time.monotonic()
                heard = await MoonshineTranscriber().transcribe(spoken)
                legs["recognition"] = time.monotonic() - started
    except TimeoutError:
        finished = ", ".join(f"{leg} {cost:.1f}s" for leg, cost in legs.items()) or "none"
        # This case's own budget is the only thing here that raises `TimeoutError`:
        # neither seam takes a deadline (ADR-0200 §1), and `SpeechTimeoutError` —
        # which only a `Bounded...` decorator raises, and nothing here wires one —
        # is an `AssistantError` and not a `TimeoutError`.
        pytest.fail(
            f"the real engines did not finish inside {_REAL_ENGINE_SECONDS}s; "
            f"completed legs: {finished}. Serially this case costs ~2.5s and "
            "~8s inside a whole `just test-fast` run, so a run that reaches this "
            "budget is stalled rather than merely sharing a busy machine (#2091)."
        )

    assert spoken.media_type is SpokenAudioFormat.WEBM_OPUS
    assert len(spoken.decoded()) > 1000
    # Compared on content words rather than on the whole string: a recogniser is
    # entitled to its own punctuation and casing, and pinning those would be a
    # word-error-rate assertion this case is not making. Both assertions carry the
    # transcript, because the one thing a failure here has to answer is what the
    # engine actually said.
    assert heard.strip(), f"the real engine returned a blank transcript: {heard!r}"
    words = {word.strip(".,").lower() for word in heard.split()}
    heard_words = _HEARD_CONTENT_WORDS & words
    assert len(heard_words) >= _HEARD_CONTENT_WORDS_REQUIRED, (
        f"heard {len(heard_words)} of {len(_HEARD_CONTENT_WORDS)} content words, "
        f"needed {_HEARD_CONTENT_WORDS_REQUIRED}; "
        f"missing {sorted(_HEARD_CONTENT_WORDS - heard_words)} "
        f"from {_SPOKEN_SENTENCE!r}; full transcript: {heard!r}"
    )
