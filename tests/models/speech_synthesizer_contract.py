"""Shared conformance suite for the SpeechSynthesizer Protocol (ADR-0200 §1).

Every ``SpeechSynthesizer`` implementation must pass this suite. A concrete test
subclasses :class:`SpeechSynthesizerContract` and overrides the ``synthesizer``
fixture; unlike its sibling suite it needs no second fixture, because the input to
this seam is text and text needs no model to be valid.

**What the suite asserts.** The declared capability is a non-empty, stable set; a
format outside it is refused with ``ValueError``, locally; every format *inside*
it produces a :class:`~ai_assistant.core.types.SpokenAudio` whose ``media_type``
**equals the one requested** — ADR-0200 §1's substitution ban, which is the clause
that makes the ``formats`` property worth reading; the rendering carries octets;
and a longer text renders longer.

**That last one is a proxy and is written down as one.** ADR-0200 §4 makes it this
seam's obligation that the audio is an audible rendering *of the text*, and no
suite can establish audibility against a test double — ADR-0200 §4 forbids
decoding a rendering to check it, and a fake produces nothing a decoder could
read. What a suite *can* refuse is the synthesizer that returns a constant blip
whatever it was asked to say, and length is what distinguishes it. Audibility
proper is discharged where it can be: an end-to-end exercise over the real voice,
transcribed back by the real recogniser (ADR-0200 §13).

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.protocols import SpeechSynthesizer
from ai_assistant.core.types import SpokenAudio, SpokenAudioFormat
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.testing.cancellation import SuspendedCall

_CANCELLATION_SECONDS = 5.0

#: The short and long texts the length proxy is measured over. The gap is wide on
#: purpose: what is being refused is a constant rendering, not a small difference
#: in how two voices pace a sentence.
_SHORT_TEXT = "Yes."
_LONG_TEXT = (
    "Your dentist appointment is on Thursday at three, and you asked me to remind "
    "you to bring the paperwork from last month along with you."
)


class SpeechSynthesizerContract:
    """The behavioural contract every ``SpeechSynthesizer`` must satisfy."""

    @pytest.fixture
    def synthesizer(self) -> SpeechSynthesizer:
        """Override in a subclass to supply the implementation under test."""
        raise NotImplementedError

    def test_conforms_to_protocol(self, synthesizer: SpeechSynthesizer) -> None:
        assert isinstance(synthesizer, SpeechSynthesizer)

    def test_formats_is_a_non_empty_frozenset_of_members(
        self, synthesizer: SpeechSynthesizer
    ) -> None:
        assert isinstance(synthesizer.formats, frozenset)
        assert synthesizer.formats
        assert all(isinstance(item, SpokenAudioFormat) for item in synthesizer.formats)

    async def test_formats_is_stable(self, synthesizer: SpeechSynthesizer) -> None:
        before = synthesizer.formats

        assert synthesizer.formats == before

        await synthesizer.synthesize(_SHORT_TEXT, format=next(iter(before)))

        assert synthesizer.formats == before

    async def test_every_declared_format_is_produced_as_asked(
        self, synthesizer: SpeechSynthesizer
    ) -> None:
        # ADR-0200 §1: "The returned value's `media_type` **equals** the requested
        # `format`." Checked over *every* declared member rather than one, because
        # a synthesizer that honoured its first format and substituted for the
        # rest would pass a single-format case and hand a caller a rendering it
        # cannot play.
        for wanted in sorted(synthesizer.formats):
            rendering = await synthesizer.synthesize(_SHORT_TEXT, format=wanted)

            assert isinstance(rendering, SpokenAudio)
            assert rendering.media_type is wanted
            # Octets, not merely a well-formed value: a rendering of nothing is
            # not a rendering, and `SpokenAudio` alone would admit one byte.
            assert len(rendering.decoded()) > 0

    async def test_a_longer_text_renders_longer(self, synthesizer: SpeechSynthesizer) -> None:
        # The proxy for "this is a rendering of *the text*" that a conformance
        # suite can carry; see the module docstring for what it does not reach.
        wanted = next(iter(synthesizer.formats))

        short = await synthesizer.synthesize(_SHORT_TEXT, format=wanted)
        long = await synthesizer.synthesize(_LONG_TEXT, format=wanted)

        assert len(long.decoded()) > len(short.decoded())

    async def test_an_undeclared_format_is_refused(self, synthesizer: SpeechSynthesizer) -> None:
        undeclared = set(SpokenAudioFormat) - synthesizer.formats
        if not undeclared:
            pytest.skip("this synthesizer declares every format, so there is none to refuse")

        with pytest.raises(ValueError, match=r"produce|format|audio"):
            await synthesizer.synthesize(_SHORT_TEXT, format=undeclared.pop())

    async def test_an_undeclared_format_is_refused_before_any_work(
        self, synthesizer: SpeechSynthesizer
    ) -> None:
        # ADR-0200 §1's "locally, before any I/O", observable from outside as
        # promptness: the refusal lands within a single event-loop turn.
        undeclared = set(SpokenAudioFormat) - synthesizer.formats
        if not undeclared:
            pytest.skip("this synthesizer declares every format, so there is none to refuse")

        call = asyncio.ensure_future(synthesizer.synthesize(_SHORT_TEXT, format=undeclared.pop()))
        await settle()

        assert call.done()
        with pytest.raises(ValueError, match=r"produce|format|audio"):
            call.result()

    # --- cancellation (ADR-0060) -------------------------------------------

    #: See :attr:`SpeechTranscriberContract.holds_nothing_across_an_await`.
    holds_nothing_across_an_await: bool = False

    def synthesizer_suspended_mid_call(
        self,
    ) -> AbstractAsyncContextManager[tuple[SpeechSynthesizer, SuspendedCall]]:
        """Supply a synthesizer whose next call stops at its worker handoff.

        Override unless :attr:`holds_nothing_across_an_await` is set.
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    async def test_a_cancelled_synthesize_is_not_absorbed_and_strands_nothing(self) -> None:
        """``core.protocols``' cancellation clause, on this seam (ADR-0060).

        The transcriber suite's case in the output direction, and its docstring
        carries the reasoning for what is asserted and what is deliberately not.
        """
        if self.holds_nothing_across_an_await:
            pytest.skip("synthesize reaches no await, so a cancellation cannot land inside it")

        async with self.synthesizer_suspended_mid_call() as (synthesizer, suspended):
            wanted = next(iter(synthesizer.formats))
            call = asyncio.ensure_future(synthesizer.synthesize(_LONG_TEXT, format=wanted))
            try:
                await suspended.reached()
                call.cancel()
                await settle()
            finally:
                suspended.release()

            async with asyncio.timeout(_CANCELLATION_SECONDS):
                with pytest.raises(asyncio.CancelledError):
                    await call

            async with asyncio.timeout(_CANCELLATION_SECONDS):
                rendering = await synthesizer.synthesize(_SHORT_TEXT, format=wanted)
            assert rendering.media_type is wanted
