"""The spoken turn's two seam stages, and the classification that crosses out of them.

ADR-0200 §3 makes ``converse_spoken``'s ``timeout`` the budget for the **whole
call** — transcription, the turn and synthesis together — and threads it to each
stage (ADR-0029 §4). Neither speech Protocol takes a deadline of its own: the
deadline is a decorator the composition root wires over whichever implementation
it built, so that it "composes over *every* implementation" (ADR-0118 §2). What
this module adds is the other half of §3's clause — **the effective bound on a
speech stage is the lesser of the caller's remaining budget and the decorator's**,
so a stage never outlives the call and a generous deployment setting never
overrides a tight caller.

The two bounds compose by racing rather than by arithmetic: whichever fires first
ends the call, and either way the failure is a
:class:`~ai_assistant.core.errors.SpeechTimeoutError`, which is the one class
ADR-0200 §1 admits for an expiry and the one ADR-0200 §4 classifies as
:attr:`~ai_assistant.core.types.SpeechFailure.TIMED_OUT`. A budget already
exhausted when a stage is reached is that stage's expiry and is not a separate
case — a non-positive remaining budget fires immediately.

**The classification is an identity-matched MRO walk over a mapping frozen at
import** (ADR-0200 §4), never the exception's ``__name__``, its module or its
message. This is ``models/routing.py``'s ``_classify`` applied one boundary
further out and for its reason: a speech implementation is a stranger, and the
class it raises can be named anything at all — including the name of a class this
build declares. Identity is what makes a look-alike unable to buy a
classification.

**Nothing here writes a message it did not author** (ADR-0200 §8). A seam's
exception carries arbitrary text and an implementation that interpolated the clip
it could not decode has put the recording inside it; so this module logs the
project's own classification and never the seam's words, and the refusal it hands
the caller is built from a template rather than from what was caught.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import SpeechError, SpeechTimeoutError
from ai_assistant.core.types import SpeechFailure

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from ai_assistant.core.protocols import SpeechSynthesizer, SpeechTranscriber
    from ai_assistant.core.types import SpokenAudio, SpokenAudioFormat

__all__ = [
    "DEFAULT_MAX_SPOKEN_AUDIO_BYTES",
    "classify_speech_failure",
    "synthesize_within",
    "transcribe_within",
]

_log = structlog.get_logger(__name__)

#: ADR-0200 §6's bound on a spoken recording **and** a spoken rendering, in bytes
#: of decoded audio, at the figure that ADR names — 512 KiB. An engine takes it as
#: a constructor argument so a deployment (and a test) can set it; this is what it
#: gets by saying nothing, and it is
#: ``Settings.hub_max_spoken_audio_bytes``'s own default.
#:
#: Spelled here rather than imported from ``core.config`` for
#: ``DEFAULT_MAX_PAYLOAD_BYTES``'s reason one module over: a figure the engine and
#: the canonical fake carry cannot be a settings read, since neither has a
#: ``Settings``. ``tests/orchestration/test_spoken_bounds.py`` pins the two
#: together, so the duplication cannot drift.
DEFAULT_MAX_SPOKEN_AUDIO_BYTES: Final[int] = 512 * 1024

#: One entry per class of the :class:`~ai_assistant.core.errors.SpeechError`
#: taxonomy ADR-0200 §1 fixes, **nearest first**, frozen at import.
#:
#: The order is the walk's: :func:`classify_speech_failure` takes the first entry
#: whose class *is* — by identity — a class in the caught exception's MRO, so a
#: ``SpeechTimeoutError`` matches its own row before it reaches the base's. A lane
#: that adds a third ``SpeechError`` subclass adds its row here **and** its
#: ``SpeechFailure`` member in the same change, which is the bijection ADR-0200 §4
#: states and ``tests/core/test_speech_failure_bijection.py`` enforces.
_CLASSIFICATIONS: Final[tuple[tuple[type[SpeechError], SpeechFailure], ...]] = (
    (SpeechTimeoutError, SpeechFailure.TIMED_OUT),
    (SpeechError, SpeechFailure.UNCLASSIFIED),
)


def classify_speech_failure(exc: BaseException) -> SpeechFailure:
    """Name a caught seam failure in this project's own vocabulary (ADR-0200 §4).

    Walks the exception's MRO and takes the nearest class :data:`_CLASSIFICATIONS`
    names, **matched by object identity**. A class an implementation happened to
    call ``SpeechTimeoutError``, or one that subclasses nothing this build
    declares, reaches the fallback: the value is what *this* build's taxonomy says,
    never what the raiser's naming implies.

    Args:
        exc: The exception the seam raised.

    Returns:
        The member naming it, or
        :attr:`~ai_assistant.core.types.SpeechFailure.UNCLASSIFIED` where the
        taxonomy does not reach it.
    """
    for kind in type(exc).__mro__:
        for known, member in _CLASSIFICATIONS:
            if kind is known:
                return member
    return SpeechFailure.UNCLASSIFIED


async def transcribe_within(
    transcriber: SpeechTranscriber, audio: SpokenAudio, *, seconds: float
) -> str:
    """Transcribe under the caller's remaining budget (ADR-0200 §3).

    Args:
        transcriber: The seam, already wrapped in whatever deadline decorator the
            composition root wired. Its own bound still applies; this one is the
            caller's, and the effective bound is the lesser of the two.
        audio: The recording. Its ``media_type`` was checked against the seam's
            ``formats`` before this was called, so the seam's ``ValueError``
            refusal is unreachable from a conforming engine.
        seconds: What is left of the call's budget. Non-positive means the budget
            was already spent, which is this stage's expiry.

    Returns:
        The words heard, blank where there were none.

    Raises:
        SpeechTimeoutError: If the caller's budget expired first.
        SpeechError: Whatever the seam raised, unwrapped — its own vocabulary,
            which the caller classifies.
        CancelledError: A delivered cancellation, which ADR-0200 §4 makes neither
            a transcription failure nor a synthesis failure.
    """
    return await _within(
        transcriber.transcribe(audio), seconds=seconds, subject="the transcription"
    )


async def synthesize_within(
    synthesizer: SpeechSynthesizer,
    text: str,
    *,
    media_type: SpokenAudioFormat,
    seconds: float,
) -> SpokenAudio:
    """Render ``text`` under the caller's remaining budget (ADR-0200 §3).

    Args:
        synthesizer: The seam, under its own deadline decorator.
        text: Exactly ``outcome.reply`` and nothing derived from it — ADR-0200 §4
            makes ``spoken`` the rendering of that value byte for byte.
        media_type: The format the engine picked from ``plays`` (ADR-0200 §3),
            already known to be one this seam's ``formats`` names.
        seconds: What is left of the call's budget.

    Returns:
        The rendering, whose ``media_type`` equals ``media_type``.

    Raises:
        SpeechTimeoutError: If the caller's budget expired first.
        SpeechError: Whatever the seam raised, unwrapped — which ADR-0200 §4
            degrades rather than failing on.
        CancelledError: A delivered cancellation, which never degrades.
    """
    return await _within(
        synthesizer.synthesize(text, format=media_type), seconds=seconds, subject="the rendering"
    )


async def _within[T](work: Awaitable[T], *, seconds: float, subject: str) -> T:
    """Await ``work`` under a caller-budget deadline, in ``models/``'s own shape.

    ``BoundedSpeechTranscriber``'s pattern, taken whole because the corpus has
    already paid for the two mistakes it avoids:

    * **Expiry does not always surface as an exception.** ``asyncio`` abandons a
      call by *cancelling* it, and a seam that swallows that ``CancelledError`` can
      still return normally — handing back a transcript produced after the deadline
      had passed. Asking the deadline whether it expired is the only way to notice.
    * **Two different failures arrive as ``TimeoutError``.** An inner
      ``TimeoutError`` raised instantly is not this deadline expiring, and
      conflating them would discard the seam's own account. The deadline is asked
      directly.

    An outer cancellation never reaches either arm: ``asyncio.timeout`` leaves a
    cancellation it did not cause alone, which is what ``core/protocols.py``'s
    cancellation clause requires (ADR-0060 §1) and what ADR-0200 §4 restates for
    this call.

    Args:
        work: The seam call.
        seconds: The caller's remaining budget.
        subject: What is being bounded, for the project-authored message.

    Returns:
        Whatever the seam returned, where it returned in time.

    Raises:
        SpeechTimeoutError: If the caller's budget expired.
    """
    deadline = asyncio.timeout(max(seconds, 0.0))
    cause: TimeoutError | None = None
    try:
        async with deadline:
            produced = await work
        if not deadline.expired():
            return produced
    except TimeoutError as exc:
        if not deadline.expired():
            raise
        cause = exc
    msg = f"{subject} did not complete within the caller's remaining budget"
    raise SpeechTimeoutError(msg) from cause
