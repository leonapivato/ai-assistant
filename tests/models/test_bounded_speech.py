"""The deadline ADR-0200 §1 keeps off the seam and puts in a decorator.

Both decorators are the same object twice, so most cases are parametrised over
the pair; where the two calls differ — the arguments, and what a synthesizer's
``media_type`` must equal — they are written out.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.core.errors import ConfigurationError, SpeechError, SpeechTimeoutError
from ai_assistant.core.protocols import SpeechSynthesizer, SpeechTranscriber
from ai_assistant.core.types import SpokenAudio, SpokenAudioFormat
from ai_assistant.models import BoundedSpeechSynthesizer, BoundedSpeechTranscriber
from ai_assistant.testing import FakeSpeechSynthesizer, FakeSpeechTranscriber

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_TINY_DEADLINE = 0.05

#: Long enough that nothing on a passing run reaches it, short enough that a
#: broken decorator fails the suite instead of hanging it.
_LIVENESS_SECONDS = 5.0

_RECORDING = SpokenAudio(content="QUJDRA==", media_type=SpokenAudioFormat.WEBM_OPUS)


class _ParkedTranscriber:
    """A transcriber whose call never answers."""

    def __init__(self) -> None:
        self.released = asyncio.Event()

    @property
    def formats(self) -> frozenset[SpokenAudioFormat]:
        return frozenset(SpokenAudioFormat)

    async def transcribe(self, audio: SpokenAudio) -> str:
        await self.released.wait()
        return "too late"


class _ParkedSynthesizer:
    """A synthesizer whose call never answers."""

    def __init__(self) -> None:
        self.released = asyncio.Event()

    @property
    def formats(self) -> frozenset[SpokenAudioFormat]:
        return frozenset(SpokenAudioFormat)

    async def synthesize(
        self,
        text: str,
        *,
        format: SpokenAudioFormat,  # noqa: A002 — ADR-0200 §1 fixes this signature
    ) -> SpokenAudio:
        await self.released.wait()
        return SpokenAudio(content="QUJDRA==", media_type=format)


class _SwallowingTranscriber(_ParkedTranscriber):
    """A transcriber that absorbs the cancellation its deadline delivers.

    The shape ``bounded_embedder.py`` records the corpus having paid for: expiry
    does not always surface as an exception, so an inner seam that swallows the
    ``CancelledError`` can return normally and hand back a value produced after
    the deadline had already passed.
    """

    async def transcribe(self, audio: SpokenAudio) -> str:
        try:
            await asyncio.sleep(_LIVENESS_SECONDS)
        except asyncio.CancelledError:
            return "produced after the deadline"
        return "never reached"


def _bounded_pair(seconds: float) -> list[tuple[str, Callable[[], Awaitable[Any]]]]:
    """One parked, bounded call per seam, ready to await."""
    transcriber = BoundedSpeechTranscriber(_ParkedTranscriber(), timeout_seconds=seconds)
    synthesizer = BoundedSpeechSynthesizer(_ParkedSynthesizer(), timeout_seconds=seconds)
    return [
        ("transcribe", lambda: transcriber.transcribe(_RECORDING)),
        ("synthesize", lambda: synthesizer.synthesize("hello", format=SpokenAudioFormat.MP4)),
    ]


# --- the deadline ------------------------------------------------------------


@pytest.mark.parametrize("name", ["transcribe", "synthesize"])
async def test_an_expired_call_raises_the_speech_timeout(name: str) -> None:
    call = dict(_bounded_pair(_TINY_DEADLINE))[name]

    async with asyncio.timeout(_LIVENESS_SECONDS):
        with pytest.raises(SpeechTimeoutError, match="did not complete within"):
            await call()


@pytest.mark.parametrize("name", ["transcribe", "synthesize"])
async def test_the_expiry_is_retryable_and_routable(name: str) -> None:
    call = dict(_bounded_pair(_TINY_DEADLINE))[name]

    with pytest.raises(SpeechTimeoutError) as caught:
        await call()

    assert caught.value.retryable is True
    assert caught.value.routable is True


async def test_an_inner_seam_that_swallows_the_cancellation_still_expires() -> None:
    # `asyncio` abandons a call by cancelling it, so a seam that absorbs the
    # cancellation returns normally and the context manager exits quietly. Asking
    # the deadline whether it expired is the only way to notice, and this is the
    # case that proves the decorator does.
    bounded = BoundedSpeechTranscriber(_SwallowingTranscriber(), timeout_seconds=_TINY_DEADLINE)

    async with asyncio.timeout(_LIVENESS_SECONDS):
        with pytest.raises(SpeechTimeoutError):
            await bounded.transcribe(_RECORDING)


# --- what it delegates and what it passes through ----------------------------


def test_the_declared_capability_is_delegated_unchanged() -> None:
    # A deadline does not change what can be decoded or produced. Rewriting this
    # would make a recording admissible against the wrapper and refused by what it
    # wraps, or the reverse.
    narrow = frozenset({SpokenAudioFormat.MP4})

    assert BoundedSpeechTranscriber(FakeSpeechTranscriber(formats=narrow)).formats == narrow
    assert BoundedSpeechSynthesizer(FakeSpeechSynthesizer(formats=narrow)).formats == narrow


async def test_a_successful_call_is_returned_unchanged() -> None:
    inner = FakeSpeechTranscriber(transcripts=["what I actually said"])

    assert await BoundedSpeechTranscriber(inner).transcribe(_RECORDING) == "what I actually said"


async def test_the_requested_format_survives_the_decorator() -> None:
    bounded = BoundedSpeechSynthesizer(FakeSpeechSynthesizer())

    rendering = await bounded.synthesize("hello", format=SpokenAudioFormat.WEBM_OPUS)

    assert rendering.media_type is SpokenAudioFormat.WEBM_OPUS


async def test_an_argument_refusal_passes_through_as_a_value_error() -> None:
    # ADR-0200 §1's refusals are the inner seam's, raised before any I/O and
    # before this deadline could bite. Re-labelling one as an expiry would send a
    # caller to the wrong remedy.
    bounded = BoundedSpeechSynthesizer(FakeSpeechSynthesizer(formats=[SpokenAudioFormat.MP4]))

    with pytest.raises(ValueError, match="produces"):
        await bounded.synthesize("hello", format=SpokenAudioFormat.WEBM_OPUS)


async def test_an_inner_speech_error_is_not_relabelled() -> None:
    # The inner seam's faults are its own vocabulary; a decorator that wrapped
    # them would destroy the distinction between "the engine failed" and "we ran
    # out of time", which are different remedies.
    inner = FakeSpeechTranscriber()
    inner.fail_next_transcribe(SpeechError("the engine wedged"))

    with pytest.raises(SpeechError, match="wedged") as caught:
        await BoundedSpeechTranscriber(inner).transcribe(_RECORDING)

    assert not isinstance(caught.value, SpeechTimeoutError)


async def test_an_outer_cancellation_is_delivered_onward_not_converted() -> None:
    # `asyncio.timeout` leaves a cancellation it did not cause alone, which is
    # what `core/protocols.py`'s cancellation clause requires (ADR-0060 §1).
    parked = _ParkedTranscriber()
    bounded = BoundedSpeechTranscriber(parked, timeout_seconds=_LIVENESS_SECONDS)
    call = asyncio.ensure_future(bounded.transcribe(_RECORDING))
    await asyncio.sleep(0)

    call.cancel()

    with pytest.raises(asyncio.CancelledError):
        await call


# --- what it refuses to be built with ----------------------------------------


@pytest.mark.parametrize("decorator", [BoundedSpeechTranscriber, BoundedSpeechSynthesizer])
@pytest.mark.parametrize(
    "timeout",
    [0, -1.0, float("inf"), float("nan"), True, "30"],
    ids=["zero", "negative", "infinite", "nan", "bool", "string"],
)
def test_an_unusable_deadline_is_refused_at_construction(decorator: type, timeout: object) -> None:
    # `bool` and `"30"` are the two that would otherwise pass quietly: `True`
    # would be coerced into a one-second deadline that fails every cold model
    # load, and `math.isfinite("30")` raises `TypeError` — a builtin escaping from
    # a constructor that documents `ConfigurationError`.
    with pytest.raises(ConfigurationError, match="timeout_seconds"):
        decorator(FakeSpeechTranscriber(), timeout_seconds=timeout)


# --- the shape of the thing being wrapped ------------------------------------


def test_each_decorator_satisfies_the_protocol_it_wraps() -> None:
    assert isinstance(BoundedSpeechTranscriber(FakeSpeechTranscriber()), SpeechTranscriber)
    assert isinstance(BoundedSpeechSynthesizer(FakeSpeechSynthesizer()), SpeechSynthesizer)


@pytest.mark.parametrize(
    ("decorator", "member"),
    [(BoundedSpeechTranscriber, "transcribe"), (BoundedSpeechSynthesizer, "synthesize")],
)
def test_the_decorated_call_takes_no_deadline_either(decorator: type, member: str) -> None:
    # The deadline belongs to the *constructor*, not the call: a per-call timeout
    # here would put back exactly what ADR-0200 §1 took off the seam.
    parameters = set(inspect.signature(getattr(decorator, member)).parameters)

    assert not parameters & {"timeout", "timeout_seconds", "deadline"}
