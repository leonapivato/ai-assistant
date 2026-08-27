"""Shared conformance suite for the SpeechTranscriber Protocol (ADR-0200 §1).

Every ``SpeechTranscriber`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`SpeechTranscriberContract` and overrides two fixtures: ``transcriber``,
the implementation under test, and ``recording``, a recording *that
implementation can actually decode*.

The second fixture is what lets one suite run against both a scripted fake and a
real engine. A fake answers from a script and does not care what the octets are;
a real transcriber decodes a container and would refuse anything else. Neither
could be served by a recording written into this file, so the subclass supplies
one and the suite asserts only what is true of both.

**What the suite asserts is the contract and nothing beyond it.** The declared
capability is a non-empty, stable set; a recording in a format the subject does
not name is refused with ``ValueError`` and refused *locally*; a transcript is a
``str`` that has a UTF-8 encoding, because the Protocol's return type is
``EncodableText`` and a value with no encoding could not cross the wire.

**What it deliberately does not assert.** That the transcript is *what was said*:
no fake can satisfy that, and ADR-0200 §13 puts it in an end-to-end exercise over
the real implementation instead. Nor that a blank return is impossible — ADR-0200
§1 makes a blank transcript a legitimate result meaning the recording carried no
words, so a suite requiring non-blankness would forbid a conforming answer.

The gate runs the whole suite with no network, so every implementation it runs
against must transcribe offline.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.protocols import SpeechTranscriber
from ai_assistant.core.types import SpokenAudio, SpokenAudioFormat
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.testing.cancellation import SuspendedCall

#: Ceiling on the cancellation case's waits, so a transcriber that never answers
#: fails instead of hanging the suite. A liveness bound, not a latency assertion.
_CANCELLATION_SECONDS = 5.0


class SpeechTranscriberContract:
    """The behavioural contract every ``SpeechTranscriber`` must satisfy."""

    @pytest.fixture
    def transcriber(self) -> SpeechTranscriber:
        """Override in a subclass to supply the implementation under test."""
        raise NotImplementedError

    @pytest.fixture
    def recording(self) -> SpokenAudio:
        """Override in a subclass to supply a recording the subject can decode.

        Its ``media_type`` must be one the subject's ``formats`` names, or the
        suite is testing the refusal path by accident.
        """
        raise NotImplementedError

    def test_conforms_to_protocol(self, transcriber: SpeechTranscriber) -> None:
        assert isinstance(transcriber, SpeechTranscriber)

    def test_formats_is_a_non_empty_frozenset_of_members(
        self, transcriber: SpeechTranscriber
    ) -> None:
        # Non-empty because a transcriber naming no format can be handed nothing:
        # ADR-0200 §3 has the engine read this property and refuse anything it
        # does not name, so an empty answer is a seam nobody can call.
        assert isinstance(transcriber.formats, frozenset)
        assert transcriber.formats
        assert all(isinstance(item, SpokenAudioFormat) for item in transcriber.formats)

    async def test_formats_is_stable(
        self, transcriber: SpeechTranscriber, recording: SpokenAudio
    ) -> None:
        # A capability that changed between reads — or once a model had loaded —
        # would let one recording be admitted against one answer and refused
        # against another, which is exactly the check ADR-0200 §3 puts before the
        # call.
        before = transcriber.formats

        assert transcriber.formats == before

        await transcriber.transcribe(recording)

        assert transcriber.formats == before

    def test_the_supplied_recording_is_one_this_subject_declares(
        self, transcriber: SpeechTranscriber, recording: SpokenAudio
    ) -> None:
        # Not a property of the implementation but of the fixture, and it has to
        # be checked or every case below could be passing against the refusal
        # path rather than the transcription path.
        assert recording.media_type in transcriber.formats

    async def test_a_transcript_is_encodable_text(
        self, transcriber: SpeechTranscriber, recording: SpokenAudio
    ) -> None:
        transcript = await transcriber.transcribe(recording)

        assert isinstance(transcript, str)
        # The declared return type is `EncodableText`. A `str` holding a lone
        # surrogate is one Python will hold and no UTF-8 encoder will accept, so a
        # transcriber producing one would fail at the frame rather than the seam.
        transcript.encode("utf-8")

    async def test_an_undeclared_format_is_refused(
        self, transcriber: SpeechTranscriber, recording: SpokenAudio
    ) -> None:
        undeclared = set(SpokenAudioFormat) - transcriber.formats
        if not undeclared:
            pytest.skip("this transcriber declares every format, so there is none to refuse")
        # The octets are the ones the subject *can* read, relabelled: what is
        # being tested is that the declared capability is consulted, not that the
        # bytes fail to parse.
        mislabelled = SpokenAudio(content=recording.content, media_type=undeclared.pop())

        with pytest.raises(ValueError, match=r"decode|format|audio"):
            await transcriber.transcribe(mislabelled)

    async def test_an_undeclared_format_is_refused_before_any_work(
        self, transcriber: SpeechTranscriber, recording: SpokenAudio
    ) -> None:
        # ADR-0200 §1 requires the refusal "locally, before any I/O". Observable
        # from outside only as *promptness*: the refusal must not have waited on
        # anything, so it lands within a single event-loop turn.
        undeclared = set(SpokenAudioFormat) - transcriber.formats
        if not undeclared:
            pytest.skip("this transcriber declares every format, so there is none to refuse")
        mislabelled = SpokenAudio(content=recording.content, media_type=undeclared.pop())

        call = asyncio.ensure_future(transcriber.transcribe(mislabelled))
        await settle()

        assert call.done()
        with pytest.raises(ValueError, match=r"decode|format|audio"):
            call.result()

    # --- cancellation (ADR-0060) -------------------------------------------

    #: Whether this implementation reaches no ``await`` at all inside
    #: ``transcribe`` — nothing handed off, nothing to interrupt mid-flight.
    #: ``core.protocols``' clause is then vacuously satisfied. Left ``False``, the
    #: suite requires the implementation to prove it by overriding
    #: :meth:`transcriber_suspended_mid_call`, so a transcriber that grows a
    #: handoff has to say something about what a cancellation does to it.
    holds_nothing_across_an_await: bool = False

    def transcriber_suspended_mid_call(
        self,
    ) -> AbstractAsyncContextManager[tuple[SpeechTranscriber, SuspendedCall, SpokenAudio]]:
        """Supply a transcriber whose next call stops at its worker handoff.

        Override unless :attr:`holds_nothing_across_an_await` is set. The
        suspension has to be arranged rather than raced for: a real call resolves
        without ever yielding back to a test that merely cancels a freshly started
        task.
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    async def test_a_cancelled_transcribe_is_not_absorbed_and_strands_nothing(self) -> None:
        """``core.protocols``' cancellation clause, on this seam (ADR-0060).

        Two properties, and they are the whole of it here for
        ``EmbedderContract``'s stated reason: no speech implementation owns an
        event-loop resource, so the "a second caller must not reach it" case the
        store suites turn on would be theatre. What is live is that the
        cancellation is delivered onward rather than turned into a transcript, and
        that once the abandoned work is let go nothing was left held with nobody
        to release it — which a later call answering at all is what detects.

        **When the cancellation is delivered is not asserted.** The clause permits
        a method to "defer delivery while it makes its resources safe", so the
        work is released before the cancellation is awaited and both shapes pass.
        """
        if self.holds_nothing_across_an_await:
            pytest.skip("transcribe reaches no await, so a cancellation cannot land inside it")

        async with self.transcriber_suspended_mid_call() as (transcriber, suspended, recording):
            call = asyncio.ensure_future(transcriber.transcribe(recording))
            try:
                await suspended.reached()
                call.cancel()
                await settle()
            finally:
                suspended.release()

            async with asyncio.timeout(_CANCELLATION_SECONDS):
                with pytest.raises(asyncio.CancelledError):
                    await call

            # Nothing was stranded: the same transcriber still answers. An
            # implementation that unwound out of a lock it never releases would
            # hang here rather than answer, which the timeout turns into a failure.
            async with asyncio.timeout(_CANCELLATION_SECONDS):
                transcript = await transcriber.transcribe(recording)
            assert isinstance(transcript, str)
