"""Canonical, dependency-free fakes for the two speech Protocols (ADR-0200 §1).

The shared test doubles for :class:`~ai_assistant.core.protocols.SpeechTranscriber`
and :class:`~ai_assistant.core.protocols.SpeechSynthesizer`, so a subsystem that
composes speech — ``orchestration`` first — can test against contract-correct
implementations *without importing the models subsystem's internals* (CLAUDE.md
golden rule 1) and without loading a model, a codec or 260 MiB of weights.

**Neither fake produces or reads real audio, deliberately.** A
:class:`~ai_assistant.core.types.SpokenAudio` is base64 text and a media type, and
nothing in either Protocol promises that a rendering is decodable by anything but
a player — ADR-0200 §4 is explicit that no component decodes or re-transcribes a
rendering to check it. So :class:`FakeSpeechSynthesizer` emits deterministic bytes
whose *length grows with the text*, which is the only structural property a
consumer may lean on, and :class:`FakeSpeechTranscriber` answers from a script
rather than from the octets it was handed. That the real voice is audible, and
that the real recogniser hears it, is discharged where it can be: an end-to-end
exercise over the real implementations (ADR-0200 §13).

Both fakes can be suspended mid-flight and both can be made to fail, so they are
real subjects for ``core.protocols``' cancellation clause (ADR-0060) and for the
failure translation ADR-0200 §4 puts one boundary out.
"""

from __future__ import annotations

import hashlib
from base64 import b64encode
from collections import deque
from typing import TYPE_CHECKING

from ai_assistant.core.types import SpokenAudio, SpokenAudioFormat
from ai_assistant.testing.cancellation import DetachedWork

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ai_assistant.core.types import EncodableText, NonBlankEncodableText

#: What :class:`FakeSpeechTranscriber` answers once its script runs out. Non-blank,
#: so the default fake drives the ordinary path; a test wanting ADR-0200 §4's
#: no-words shape scripts ``""`` explicitly rather than getting it by accident.
DEFAULT_TRANSCRIPT = "what did I say I would do this week"

#: How many bytes of pseudo-audio :class:`FakeSpeechSynthesizer` emits per
#: character of text. Small, but strictly positive, which is what makes "a longer
#: text renders longer" true of the fake as it is of a real voice.
_BYTES_PER_CHARACTER = 8


def _checked_formats(formats: Iterable[SpokenAudioFormat] | None) -> frozenset[SpokenAudioFormat]:
    """Return the declared capability, refusing an empty one.

    Args:
        formats: What to declare, or ``None`` for every member.

    Returns:
        The declared set.

    Raises:
        ValueError: If ``formats`` is empty. A seam that names no format can be
            handed nothing and asked for nothing, so it would be a double that
            fails its own conformance suite rather than a narrower one.
    """
    declared = frozenset(SpokenAudioFormat) if formats is None else frozenset(formats)
    if not declared:
        msg = "formats must name at least one member"
        raise ValueError(msg)
    return declared


class FakeSpeechTranscriber:
    """A scripted ``SpeechTranscriber`` test double.

    Structurally implements
    :class:`~ai_assistant.core.protocols.SpeechTranscriber`. Every recording it is
    handed is recorded to :attr:`calls`.
    """

    def __init__(
        self,
        *,
        transcripts: Sequence[str] | None = None,
        formats: Iterable[SpokenAudioFormat] | None = None,
    ) -> None:
        """Create the fake transcriber.

        Args:
            transcripts: What to answer, in order. Once exhausted every further
                call answers :data:`DEFAULT_TRANSCRIPT`, so a test that cares
                about one call need not script the rest.
            formats: What to declare decodable. Defaults to every member.

        Raises:
            ValueError: If ``formats`` is empty.
        """
        self._formats = _checked_formats(formats)
        self._script: deque[str] = deque(transcripts or ())
        self.calls: list[SpokenAudio] = []
        self._armed: DetachedWork | None = None
        self._failure: Exception | None = None

    def suspend_next_transcribe(self) -> DetachedWork:
        """Hold the next :meth:`transcribe` open at a modelled worker handoff.

        The hook ``SpeechTranscriberContract``'s cancellation case takes (ADR-0060
        §3). Test-only, and deliberately not on the Protocol: the suite asks the
        *subject* it was handed rather than the seam every consumer depends on.

        Returns:
            The handle to wait on and release.

        Raises:
            RuntimeError: If a suspension is already armed. Two would silently
                make the second a no-op.
        """
        if self._armed is not None:
            msg = "a suspension is already armed on this transcriber"
            raise RuntimeError(msg)
        self._armed = DetachedWork()
        return self._armed

    def fail_next_transcribe(self, error: Exception) -> None:
        """Make the next :meth:`transcribe` raise ``error``.

        What ADR-0200 §4's translation is tested against one boundary out: a
        ``SpeechError`` becomes ``TranscriptionFailedError`` and anything else
        propagates, and a consumer cannot test either half without a seam it can
        make fail.

        Args:
            error: What to raise. Any exception, so the "everything else
                propagates" half can be driven too.
        """
        self._failure = error

    @property
    def formats(self) -> frozenset[SpokenAudioFormat]:
        """The container-and-codec members this fake declares it can decode."""
        return self._formats

    async def transcribe(self, audio: SpokenAudio) -> EncodableText:
        """Record the recording and answer from the script.

        The call is recorded **before** any suspension or failure, so a cancelled
        or failed transcription is still visible in :attr:`calls` — matching a
        real transcriber that has already started work.

        Args:
            audio: The recording.

        Returns:
            The next scripted transcript, or :data:`DEFAULT_TRANSCRIPT`.

        Raises:
            ValueError: If ``audio.media_type`` is not in :attr:`formats`, before
                anything is recorded — a refusal is not a call.
            CancelledError: If the awaiting task is cancelled while suspended.
            Exception: Whatever :meth:`fail_next_transcribe` armed.
        """
        if audio.media_type not in self._formats:
            msg = (
                f"this transcriber decodes "
                f"{', '.join(sorted(item.value for item in self._formats))}, "
                f"and was handed {audio.media_type.value}"
            )
            raise ValueError(msg)
        self.calls.append(audio)
        armed, self._armed = self._armed, None
        if armed is not None:
            await armed.hold()
        failure, self._failure = self._failure, None
        if failure is not None:
            raise failure
        return self._script.popleft() if self._script else DEFAULT_TRANSCRIPT

    @property
    def call_count(self) -> int:
        """How many times ``transcribe`` has been called."""
        return len(self.calls)


class FakeSpeechSynthesizer:
    """A deterministic ``SpeechSynthesizer`` test double.

    Structurally implements
    :class:`~ai_assistant.core.protocols.SpeechSynthesizer`. Every request is
    recorded to :attr:`calls` as a ``(text, format)`` pair.
    """

    def __init__(self, *, formats: Iterable[SpokenAudioFormat] | None = None) -> None:
        """Create the fake synthesizer.

        Args:
            formats: What to declare producible. Defaults to every member. A
                narrower set is how a consumer tests ADR-0200 §3's format
                intersection without a second implementation.

        Raises:
            ValueError: If ``formats`` is empty.
        """
        self._formats = _checked_formats(formats)
        self.calls: list[tuple[str, SpokenAudioFormat]] = []
        self._armed: DetachedWork | None = None
        self._failure: Exception | None = None

    def suspend_next_synthesize(self) -> DetachedWork:
        """Hold the next :meth:`synthesize` open at a modelled worker handoff.

        Returns:
            The handle to wait on and release.

        Raises:
            RuntimeError: If a suspension is already armed.
        """
        if self._armed is not None:
            msg = "a suspension is already armed on this synthesizer"
            raise RuntimeError(msg)
        self._armed = DetachedWork()
        return self._armed

    def fail_next_synthesize(self, error: Exception) -> None:
        """Make the next :meth:`synthesize` raise ``error``.

        The other half of what ADR-0200 §4's translation is tested against: a
        ``SpeechError`` here degrades the turn rather than failing it.

        Args:
            error: What to raise.
        """
        self._failure = error

    @property
    def formats(self) -> frozenset[SpokenAudioFormat]:
        """The container-and-codec members this fake declares it can produce."""
        return self._formats

    async def synthesize(
        self,
        text: NonBlankEncodableText,
        *,
        format: SpokenAudioFormat,  # noqa: A002 — ADR-0200 §1 fixes this signature
    ) -> SpokenAudio:
        """Record the request and return deterministic pseudo-audio.

        The octets are a hash of the text and the requested format, repeated to a
        length proportional to the text's — so the same request renders the same
        bytes, two different texts render differently, and a longer text renders
        longer. Nothing else about them is meaningful, and nothing may decode
        them.

        Args:
            text: What to say.
            format: The container to produce.

        Returns:
            The rendering, whose ``media_type`` is ``format``.

        Raises:
            ValueError: If ``format`` is not in :attr:`formats`, before anything
                is recorded.
            CancelledError: If the awaiting task is cancelled while suspended.
            Exception: Whatever :meth:`fail_next_synthesize` armed.
        """
        if format not in self._formats:
            msg = (
                f"this synthesizer produces "
                f"{', '.join(sorted(item.value for item in self._formats))}, "
                f"and was asked for {format.value}"
            )
            raise ValueError(msg)
        self.calls.append((text, format))
        armed, self._armed = self._armed, None
        if armed is not None:
            await armed.hold()
        failure, self._failure = self._failure, None
        if failure is not None:
            raise failure
        return SpokenAudio(content=_rendering(text, format), media_type=format)

    @property
    def call_count(self) -> int:
        """How many times ``synthesize`` has been called."""
        return len(self.calls)

    @property
    def spoken_texts(self) -> tuple[str, ...]:
        """Every text passed to ``synthesize`` so far, in order."""
        return tuple(text for text, _ in self.calls)


def _rendering(text: str, media_type: SpokenAudioFormat) -> str:
    """Return deterministic pseudo-audio for ``text``, as padded canonical base64."""
    seed = hashlib.sha256(f"{media_type.value}\0{text}".encode()).digest()
    length = max(len(seed), _BYTES_PER_CHARACTER * len(text))
    octets = (seed * (length // len(seed) + 1))[:length]
    return b64encode(octets).decode("ascii")
