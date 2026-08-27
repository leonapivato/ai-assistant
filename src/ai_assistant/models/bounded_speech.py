"""A deadline over either speech seam (ADR-0200 §1, ADR-0118 §2).

:class:`BoundedSpeechTranscriber` and :class:`BoundedSpeechSynthesizer` *wrap*
another implementation rather than extending one: each implements its Protocol,
delegates ``formats`` unchanged, and bounds the one call. That is
:class:`~ai_assistant.models.bounded_embedder.BoundedEmbedder`'s shape, taken for
the reason ADR-0200 §1 states in as many words — a deadline written into the seam
binds one implementation, and a deadline written as a wrapper "composes over
*every* implementation".

**Two classes rather than one generic wrapper**, because the two Protocols are
siblings rather than a family: neither inherits from the other, their calls have
different signatures, and a single object claiming both would be an implementation
of two contracts that ADR-0200 §1 is explicit nothing requires to travel together.
The duplication is four short methods.

**One attempt, no retry, no backoff** (ADR-0118 §3). An on-device engine does not
fail transiently the way a remote provider does, and against a wedged backend each
retry would abandon another worker — multiplying the blast radius of the one
failure mode the deadline exists to survive. ADR-0200 §11 leaves a retry or
routing wrapper deferred, with the condition that would make one worth writing.

**The deadline stops the caller waiting; it does not stop the work** (ADR-0200 §5,
ADR-0118 §7, ADR-0029 §4). By the time it fires, the implementation has already
submitted its work to a thread this decorator cannot reach, which is why
:class:`~ai_assistant.core.errors.SpeechTimeoutError` says the recording is not
known not to have been transcribed. Containment of the abandoned worker is the
implementation's obligation and is discharged in
:mod:`ai_assistant.models._embed_worker`.

**A ``ValueError`` passes straight through.** ADR-0200 §1's argument refusals are
the *inner* seam's, raised before any I/O and before this deadline could bite, and
re-labelling one as an expiry would send a caller to the wrong remedy.
"""

from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING

from ai_assistant.core.errors import ConfigurationError, SpeechTimeoutError

if TYPE_CHECKING:
    from ai_assistant.core.protocols import SpeechSynthesizer, SpeechTranscriber
    from ai_assistant.core.types import (
        EncodableText,
        NonBlankEncodableText,
        SpokenAudio,
        SpokenAudioFormat,
    )

#: The deadline these decorators apply when none is supplied. Generous relative to
#: what either engine takes on a warm model — the figure has to cover a *cold*
#: one, which ADR-0118 §4 puts inside the bound rather than outside it — and short
#: enough that a wedged seam is a fault a caller hears about rather than a hang.
DEFAULT_TIMEOUT_SECONDS = 30.0


def _checked_timeout(timeout_seconds: float) -> float:
    """Return a validated deadline, refusing anything ``asyncio`` cannot use.

    ``BoundedEmbedder``'s guard, and its three reasons: ``math.isfinite("30")``
    raises ``TypeError`` — which would escape as a builtin and contradict the
    ``ConfigurationError`` both constructors document — so the type is checked
    first; a non-finite deadline makes ``asyncio.timeout`` behave unpredictably;
    and ``bool`` is excluded because ``True`` would otherwise be coerced into a
    one-second deadline that fails every cold model load.

    Args:
        timeout_seconds: The deadline to validate.

    Returns:
        The deadline as a float.

    Raises:
        ConfigurationError: If it is not a finite, strictly positive real number.
    """
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
        msg = (
            f"timeout_seconds must be a real number, got "
            f"{type(timeout_seconds).__name__} ({timeout_seconds!r})"
        )
        raise ConfigurationError(msg)
    if not math.isfinite(timeout_seconds):
        msg = f"timeout_seconds must be a finite number, got {timeout_seconds}"
        raise ConfigurationError(msg)
    if timeout_seconds <= 0:
        msg = f"timeout_seconds must be positive, got {timeout_seconds}"
        raise ConfigurationError(msg)
    return float(timeout_seconds)


class BoundedSpeechTranscriber:
    """A ``SpeechTranscriber`` that bounds every ``transcribe`` call.

    Structurally implements
    :class:`~ai_assistant.core.protocols.SpeechTranscriber`, so it stands in for
    the transcriber it wraps anywhere the contract is expected.
    """

    def __init__(
        self, inner: SpeechTranscriber, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        """Wrap ``inner`` with a per-call deadline.

        Args:
            inner: The transcriber to delegate to.
            timeout_seconds: The deadline over one whole ``transcribe`` call,
                including any lazy model load performed inside it (ADR-0118 §4).

        Raises:
            ConfigurationError: If ``timeout_seconds`` is not a finite, strictly
                positive real number.
        """
        self._inner = inner
        self._timeout_seconds = _checked_timeout(timeout_seconds)

    @property
    def formats(self) -> frozenset[SpokenAudioFormat]:
        """The inner transcriber's capability, delegated unchanged.

        A deadline does not change what can be decoded. Answering anything else
        here would make a recording admissible against the wrapper and refused by
        what it wraps, or the reverse.
        """
        return self._inner.formats

    async def transcribe(self, audio: SpokenAudio) -> EncodableText:
        """Transcribe through the inner seam, under this deadline.

        Args:
            audio: The recording.

        Returns:
            Whatever the inner transcriber returned.

        Raises:
            SpeechTimeoutError: If the call outlived the deadline. The worker the
                inner implementation started is **not** known to have stopped.
            ValueError: The inner seam's argument refusal, unchanged.
            SpeechError: Whatever the inner transcriber raised, unwrapped —
                including a ``SpeechTimeoutError`` of its own. Its faults are its
                own vocabulary and this seam has nothing to add to them.
        """
        deadline = asyncio.timeout(self._timeout_seconds)
        cause: TimeoutError | None = None
        try:
            async with deadline:
                transcript = await self._inner.transcribe(audio)
            # Expiry does not always surface as an exception, and the corpus has
            # already paid for assuming it does (`models/bounded_embedder.py`).
            # `asyncio` abandons a call by *cancelling* it, and an inner seam that
            # swallows that `CancelledError` can still return normally — handing
            # back a transcript produced after the deadline had passed. Asking the
            # deadline whether it expired is the only way to notice.
            if not deadline.expired():
                return transcript
        except TimeoutError as exc:
            # Two different failures arrive as `TimeoutError` and conflating them
            # produces a false report: an inner `TimeoutError` raised instantly
            # would be re-labelled as this deadline expiring, with the engine's
            # own account discarded. The deadline is asked directly, which stays
            # right even for an inner failure arriving after our own expiry has
            # been scheduled but before it fires.
            #
            # An outer cancellation never reaches this arm at all: `asyncio.timeout`
            # leaves a cancellation it did not cause alone, which is what
            # `core/protocols.py`'s cancellation clause requires (ADR-0060 §1).
            if not deadline.expired():
                raise
            cause = exc
        msg = f"the transcription did not complete within its {self._timeout_seconds:g}s deadline"
        raise SpeechTimeoutError(msg) from cause


class BoundedSpeechSynthesizer:
    """A ``SpeechSynthesizer`` that bounds every ``synthesize`` call.

    :class:`BoundedSpeechTranscriber`'s sibling, and every clause of that class's
    docstring and of this module's binds here identically.
    """

    def __init__(
        self, inner: SpeechSynthesizer, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        """Wrap ``inner`` with a per-call deadline.

        Args:
            inner: The synthesizer to delegate to.
            timeout_seconds: The deadline over one whole ``synthesize`` call,
                including any lazy model load performed inside it.

        Raises:
            ConfigurationError: If ``timeout_seconds`` is not a finite, strictly
                positive real number.
        """
        self._inner = inner
        self._timeout_seconds = _checked_timeout(timeout_seconds)

    @property
    def formats(self) -> frozenset[SpokenAudioFormat]:
        """The inner synthesizer's capability, delegated unchanged."""
        return self._inner.formats

    async def synthesize(
        self,
        text: NonBlankEncodableText,
        *,
        format: SpokenAudioFormat,  # noqa: A002 — ADR-0200 §1 fixes this signature
    ) -> SpokenAudio:
        """Synthesize through the inner seam, under this deadline.

        Args:
            text: What to say.
            format: The container to produce.

        Returns:
            Whatever the inner synthesizer returned, including its ``media_type``
            — which this decorator neither reads nor rewrites.

        Raises:
            SpeechTimeoutError: If the call outlived the deadline.
            ValueError: The inner seam's argument refusal, unchanged.
            SpeechError: Whatever the inner synthesizer raised, unwrapped.
        """
        deadline = asyncio.timeout(self._timeout_seconds)
        cause: TimeoutError | None = None
        try:
            async with deadline:
                rendering = await self._inner.synthesize(text, format=format)
            if not deadline.expired():
                return rendering
        except TimeoutError as exc:
            if not deadline.expired():
                raise
            cause = exc
        msg = f"the synthesis did not complete within its {self._timeout_seconds:g}s deadline"
        raise SpeechTimeoutError(msg) from cause
