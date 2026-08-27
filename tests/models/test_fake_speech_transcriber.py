"""The canonical FakeSpeechTranscriber passes the shared conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeSpeechTranscriber``
as a stand-in for a real transcriber: it is held to the same contract as
``MoonshineTranscriber``. Behaviour beyond the shared contract — the script, the
call record, the armed failure — is pinned here.
"""

from __future__ import annotations

import base64
import contextlib
from typing import TYPE_CHECKING

import pytest
from speech_transcriber_contract import SpeechTranscriberContract

from ai_assistant.core.errors import SpeechError
from ai_assistant.core.types import SpokenAudio, SpokenAudioFormat
from ai_assistant.testing import FakeSpeechTranscriber
from ai_assistant.testing.speech import DEFAULT_TRANSCRIPT

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.protocols import SpeechTranscriber
    from ai_assistant.testing.cancellation import SuspendedCall


def _recording(media_type: SpokenAudioFormat = SpokenAudioFormat.WEBM_OPUS) -> SpokenAudio:
    """A recording the fake accepts — its octets are never read."""
    return SpokenAudio(
        content=base64.b64encode(b"pretend this is a press-to-talk clip").decode("ascii"),
        media_type=media_type,
    )


class TestFakeSpeechTranscriberContract(SpeechTranscriberContract):
    """Runs FakeSpeechTranscriber through the shared conformance suite."""

    @pytest.fixture
    def transcriber(self) -> SpeechTranscriber:
        return FakeSpeechTranscriber()

    @pytest.fixture
    def recording(self) -> SpokenAudio:
        return _recording()

    @contextlib.asynccontextmanager
    async def transcriber_suspended_mid_call(
        self,
    ) -> AsyncIterator[tuple[SpeechTranscriber, SuspendedCall, SpokenAudio]]:
        """The fake models the worker handoff it does not really make (ADR-0060 §3).

        Answering from a script suspends nowhere, so without this the canonical
        fake could only opt out — and the cancellation case would run solely
        against the implementation that hands work to a thread.
        """
        transcriber = FakeSpeechTranscriber()
        yield transcriber, transcriber.suspend_next_transcribe(), _recording()


class TestFakeSpeechTranscriberNarrowedContract(SpeechTranscriberContract):
    """The same fake, declaring one format, so the refusal cases are not skipped.

    The suite skips its two refusal cases against a subject that declares every
    member — which the default fake does, deliberately, because that is what a
    consumer wiring it wants. This subclass exists so the refusal path is
    genuinely exercised rather than merely written down.
    """

    holds_nothing_across_an_await = True

    @pytest.fixture
    def transcriber(self) -> SpeechTranscriber:
        return FakeSpeechTranscriber(formats=[SpokenAudioFormat.WEBM_OPUS])

    @pytest.fixture
    def recording(self) -> SpokenAudio:
        return _recording()


def test_formats_defaults_to_every_member() -> None:
    assert FakeSpeechTranscriber().formats == frozenset(SpokenAudioFormat)


def test_an_empty_format_set_is_rejected() -> None:
    # A seam naming no format can be handed nothing, so it would be a double that
    # fails its own conformance suite rather than a narrower one.
    with pytest.raises(ValueError, match="at least one member"):
        FakeSpeechTranscriber(formats=[])


async def test_the_script_is_answered_in_order_then_the_default() -> None:
    transcriber = FakeSpeechTranscriber(transcripts=["first", "second"])

    assert await transcriber.transcribe(_recording()) == "first"
    assert await transcriber.transcribe(_recording()) == "second"
    assert await transcriber.transcribe(_recording()) == DEFAULT_TRANSCRIPT


async def test_a_blank_transcript_can_be_scripted() -> None:
    # ADR-0200 §1 makes a blank return a legitimate result meaning the recording
    # carried no words. A consumer cannot test ADR-0200 §4's shape for it without
    # a fake that can say so, and the default deliberately does not.
    transcriber = FakeSpeechTranscriber(transcripts=[""])

    assert await transcriber.transcribe(_recording()) == ""


async def test_every_recording_is_recorded_in_order() -> None:
    transcriber = FakeSpeechTranscriber()
    first, second = _recording(SpokenAudioFormat.WEBM_OPUS), _recording(SpokenAudioFormat.MP4)

    await transcriber.transcribe(first)
    await transcriber.transcribe(second)

    assert transcriber.calls == [first, second]
    assert transcriber.call_count == 2


async def test_an_armed_failure_is_raised_once() -> None:
    transcriber = FakeSpeechTranscriber()
    transcriber.fail_next_transcribe(SpeechError("the engine wedged"))

    with pytest.raises(SpeechError, match="wedged"):
        await transcriber.transcribe(_recording())

    assert await transcriber.transcribe(_recording()) == DEFAULT_TRANSCRIPT


async def test_a_failed_call_is_still_recorded() -> None:
    # A real transcriber that fails has already started work, so a consumer
    # asserting "the seam was reached" must be able to see it.
    transcriber = FakeSpeechTranscriber()
    transcriber.fail_next_transcribe(SpeechError("the engine wedged"))

    with pytest.raises(SpeechError):
        await transcriber.transcribe(_recording())

    assert transcriber.call_count == 1


async def test_a_refused_format_is_not_recorded_as_a_call() -> None:
    # A refusal is not a call: ADR-0200 §1 puts it before any I/O, so a consumer
    # asserting the seam was never reached must see nothing here.
    transcriber = FakeSpeechTranscriber(formats=[SpokenAudioFormat.WEBM_OPUS])

    with pytest.raises(ValueError, match="decodes"):
        await transcriber.transcribe(_recording(SpokenAudioFormat.MP4))

    assert transcriber.calls == []


def test_two_armed_suspensions_are_rejected() -> None:
    transcriber = FakeSpeechTranscriber()
    transcriber.suspend_next_transcribe()

    with pytest.raises(RuntimeError, match="already armed"):
        transcriber.suspend_next_transcribe()
