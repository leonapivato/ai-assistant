"""The canonical FakeSpeechSynthesizer passes the shared conformance suite.

What lets other subsystems trust ``ai_assistant.testing.FakeSpeechSynthesizer`` as
a stand-in for a real voice: it is held to the same contract as
``SupertonicSynthesizer``. Behaviour beyond that contract — determinism, the call
record, the armed failure — is pinned here.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import pytest
from speech_synthesizer_contract import SpeechSynthesizerContract

from ai_assistant.core.errors import SpeechError
from ai_assistant.core.types import SpokenAudioFormat
from ai_assistant.testing import FakeSpeechSynthesizer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.protocols import SpeechSynthesizer
    from ai_assistant.testing.cancellation import SuspendedCall


class TestFakeSpeechSynthesizerContract(SpeechSynthesizerContract):
    """Runs FakeSpeechSynthesizer through the shared conformance suite."""

    @pytest.fixture
    def synthesizer(self) -> SpeechSynthesizer:
        return FakeSpeechSynthesizer()

    @contextlib.asynccontextmanager
    async def synthesizer_suspended_mid_call(
        self,
    ) -> AsyncIterator[tuple[SpeechSynthesizer, SuspendedCall]]:
        """The fake models the worker handoff it does not really make (ADR-0060 §3)."""
        synthesizer = FakeSpeechSynthesizer()
        yield synthesizer, synthesizer.suspend_next_synthesize()


class TestFakeSpeechSynthesizerNarrowedContract(SpeechSynthesizerContract):
    """The same fake, declaring one format, so the refusal cases are not skipped."""

    holds_nothing_across_an_await = True

    @pytest.fixture
    def synthesizer(self) -> SpeechSynthesizer:
        return FakeSpeechSynthesizer(formats=[SpokenAudioFormat.MP4])


def test_formats_defaults_to_every_member() -> None:
    assert FakeSpeechSynthesizer().formats == frozenset(SpokenAudioFormat)


def test_an_empty_format_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one member"):
        FakeSpeechSynthesizer(formats=[])


async def test_the_same_request_renders_the_same_bytes() -> None:
    # The shared contract promises nothing about reproducibility, because the
    # Protocol does not. This fake does — it is pure hashing arithmetic — and a
    # consumer comparing two renderings may rely on it, so it is pinned here.
    synthesizer = FakeSpeechSynthesizer()

    first = await synthesizer.synthesize("the same words", format=SpokenAudioFormat.MP4)
    second = await synthesizer.synthesize("the same words", format=SpokenAudioFormat.MP4)

    assert first == second


async def test_different_texts_render_differently() -> None:
    synthesizer = FakeSpeechSynthesizer()

    first = await synthesizer.synthesize("one thing", format=SpokenAudioFormat.MP4)
    second = await synthesizer.synthesize("another thing", format=SpokenAudioFormat.MP4)

    assert first.content != second.content


async def test_one_text_renders_differently_per_format() -> None:
    # Two containers of one utterance are two different byte strings, so a fake
    # that ignored the format would let a consumer's format handling pass while
    # doing nothing.
    synthesizer = FakeSpeechSynthesizer()

    webm = await synthesizer.synthesize("one thing", format=SpokenAudioFormat.WEBM_OPUS)
    mp4 = await synthesizer.synthesize("one thing", format=SpokenAudioFormat.MP4)

    assert webm.content != mp4.content


async def test_every_request_is_recorded_in_order() -> None:
    synthesizer = FakeSpeechSynthesizer()

    await synthesizer.synthesize("first", format=SpokenAudioFormat.MP4)
    await synthesizer.synthesize("second", format=SpokenAudioFormat.WEBM_OPUS)

    assert synthesizer.calls == [
        ("first", SpokenAudioFormat.MP4),
        ("second", SpokenAudioFormat.WEBM_OPUS),
    ]
    assert synthesizer.spoken_texts == ("first", "second")
    assert synthesizer.call_count == 2


async def test_an_armed_failure_is_raised_once() -> None:
    synthesizer = FakeSpeechSynthesizer()
    synthesizer.fail_next_synthesize(SpeechError("the voice wedged"))

    with pytest.raises(SpeechError, match="wedged"):
        await synthesizer.synthesize("something", format=SpokenAudioFormat.MP4)

    rendering = await synthesizer.synthesize("something", format=SpokenAudioFormat.MP4)
    assert rendering.media_type is SpokenAudioFormat.MP4


async def test_a_refused_format_is_not_recorded_as_a_call() -> None:
    synthesizer = FakeSpeechSynthesizer(formats=[SpokenAudioFormat.MP4])

    with pytest.raises(ValueError, match="produces"):
        await synthesizer.synthesize("something", format=SpokenAudioFormat.WEBM_OPUS)

    assert synthesizer.calls == []


def test_two_armed_suspensions_are_rejected() -> None:
    synthesizer = FakeSpeechSynthesizer()
    synthesizer.suspend_next_synthesize()

    with pytest.raises(RuntimeError, match="already armed"):
        synthesizer.suspend_next_synthesize()
