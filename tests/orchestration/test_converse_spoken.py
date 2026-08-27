"""The spoken turn, composed on the hub (ADR-0200 §§2-4, §6-§8).

Every row of ADR-0200 §13's table that falls inside this lane's fence and is about
the *engine* rather than about a type: the blank-transcript shapes, the local
refusals, the format pick, the four degradations, the total failure translation,
the budget threaded to each stage, cancellation, and retention. ADR-0199's
withholding at supply is next door in ``test_spoken_disclosure.py``, because it is
about what reaches the composing stage rather than about what the call returns.

``Harness`` wires the two canonical speech fakes by default, so a case that cares
about one seam narrows or arms that one and leaves the other alone; passing
``None`` for either is the unwired deployment.
"""

from __future__ import annotations

import ast
import asyncio
from base64 import b64encode
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
import structlog
from test_engine import PATIENT, Harness, NoStepPlanner, confirmable, tool

from ai_assistant.core.errors import (
    ConfigurationError,
    OversizedValueError,
    PlanningError,
    SpeechError,
    SpeechTimeoutError,
    TranscriptionFailedError,
)
from ai_assistant.core.types import (
    EpisodicMemory,
    SpeechFailure,
    SpokenAudio,
    SpokenAudioFormat,
)
from ai_assistant.orchestration import engine as engine_module
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.payloads import canonical_payload
from ai_assistant.orchestration.speech import classify_speech_failure
from ai_assistant.testing import (
    FakeModelProvider,
    FakeSpeechSynthesizer,
    FakeSpeechTranscriber,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.core.types import (
        ActionPlan,
        CurrentContext,
        Goal,
        MemoryRecord,
        ToolCall,
        ToolResult,
    )

_WEBM: Final = SpokenAudioFormat.WEBM_OPUS
_MP4: Final = SpokenAudioFormat.MP4

#: A recognisable span, so a retention assertion looks for one thing rather than
#: for "any audio". It is what the recording decodes to, so finding it anywhere is
#: finding the recording.
_CLIP: Final = "PRIVATE-CLIP-MARKER"

_ANSWER: Final = "You went hiking on Tuesday."


def _recording(media_type: SpokenAudioFormat = _MP4, *, payload: str = _CLIP) -> SpokenAudio:
    """One recording, in ``media_type``, whose octets carry a findable marker."""
    return SpokenAudio(content=b64encode(payload.encode()).decode("ascii"), media_type=media_type)


def _wired(model: ModelProvider | None = None, **knobs: object) -> Harness:
    """A harness whose composing stage runs over ``model`` (or over a fixed answer)."""
    stage = ComposingStage(
        model=FakeModelProvider(_ANSWER) if model is None else model,
        streaming=FakeStreamingCompleter(),
    )
    return Harness(composing=stage, **knobs)  # type: ignore[arg-type]  # heterogeneous harness knobs


# --- §4: a recording that carried no words -----------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
async def test_a_blank_transcript_is_four_absences_and_no_turn(blank: str) -> None:
    """§4: "nothing was asked, so nothing was answered".

    No turn ran, no episode was captured and no conversation was created — three
    separate claims, each checked, because a shape returning the right four members
    while still capturing an episode would be a recording with no words leaving a
    record of one.
    """
    harness = _wired(transcriber=FakeSpeechTranscriber(transcripts=[blank]))

    spoken = await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert (spoken.heard, spoken.outcome, spoken.spoken) == (None, None, None)
    assert spoken.spoken_degraded is False
    assert isinstance(harness.synthesizer, FakeSpeechSynthesizer)
    assert harness.synthesizer.call_count == 0
    assert await harness.memory.export() == []
    assert await harness.conversation_store.recent() == []


async def test_a_non_blank_transcript_reaches_heard_byte_for_byte() -> None:
    """§4: "nothing on this path strips, trims, case-folds or otherwise normalises it".

    The engine *tests* for blankness; it does not produce a trimmed value and then
    use it. A transcript with leading and trailing spaces is the case that tells
    those two implementations apart.
    """
    harness = _wired(transcriber=FakeSpeechTranscriber(transcripts=["  Calendar  "]))

    spoken = await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert spoken.heard == "  Calendar  "


# --- §4: the local refusals come first ---------------------------------------


@pytest.mark.parametrize("blank_transcript", [True, False])
async def test_a_malformed_conversation_id_is_refused_before_any_seam_call(
    blank_transcript: bool,
) -> None:
    """§4: the two clauses order rather than compete.

    A local refusal never becomes a no-words result, and it is settled *before*
    transcription — which is I/O — whether or not the recording would have
    transcribed blank. Parametrised over both, because a refusal that ran after the
    seam would still look right on the non-blank case.
    """
    transcriber = FakeSpeechTranscriber(transcripts=[""] if blank_transcript else ["hello"])
    harness = _wired(transcriber=transcriber)

    with pytest.raises(ValueError, match=r"\w"):
        await harness.engine.converse_spoken(
            _recording(), plays=(_MP4,), timeout=PATIENT, conversation_id="  "
        )

    assert transcriber.call_count == 0


async def test_an_empty_plays_is_refused_locally() -> None:
    """§3: ``plays`` is required, with no default, and non-empty."""
    harness = _wired()

    with pytest.raises(ValueError, match="plays"):
        await harness.engine.converse_spoken(_recording(), plays=(), timeout=PATIENT)

    assert isinstance(harness.transcriber, FakeSpeechTranscriber)
    assert harness.transcriber.call_count == 0


async def test_a_container_the_transcriber_cannot_decode_is_refused_before_any_io() -> None:
    """§9: the engine refuses it locally, on its own read of the seam's ``formats``.

    A conforming engine never provokes the seam's own ``ValueError``, so the
    refusal has to happen before the call rather than be caught from it — and the
    seam having recorded nothing is what shows which of the two ran.
    """
    transcriber = FakeSpeechTranscriber(formats=[_WEBM])
    harness = _wired(transcriber=transcriber)

    with pytest.raises(ValueError, match="audio/mp4"):
        await harness.engine.converse_spoken(_recording(_MP4), plays=(_MP4,), timeout=PATIENT)

    assert transcriber.call_count == 0


async def test_an_oversized_recording_is_refused_before_any_seam_call() -> None:
    """§6: ``OversizedValueError``, naming the limit and the field and not the clip.

    Locally and before any I/O — base64 decoding is not I/O — and the refusal names
    the bound rather than the recording, which is §8 reaching the one path a
    happy-path retention test would miss.
    """
    harness = _wired(max_spoken_audio_bytes=8)

    with pytest.raises(OversizedValueError) as raised:
        await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert raised.value.field == "hub_max_spoken_audio_bytes"
    assert raised.value.limit == 8
    assert _CLIP not in str(raised.value)
    assert isinstance(harness.transcriber, FakeSpeechTranscriber)
    assert harness.transcriber.call_count == 0


# --- §3: the format pick ------------------------------------------------------


async def test_the_engine_renders_in_the_first_named_format_the_seam_can_produce() -> None:
    """§3: "the **first** member of ``plays`` that the synthesizer's ``formats`` also names".

    The caller's *preference order* is honoured as far as the seam can, which is
    why ``plays`` is a tuple and a seam's ``formats`` is a set.
    """
    synthesizer = FakeSpeechSynthesizer(formats=[_MP4])
    harness = _wired(synthesizer=synthesizer)

    spoken = await harness.engine.converse_spoken(
        _recording(), plays=(_WEBM, _MP4), timeout=PATIENT
    )

    assert spoken.spoken is not None
    assert spoken.spoken.media_type is _MP4
    assert synthesizer.calls[0][1] is _MP4


async def test_an_empty_format_intersection_degrades_and_spends_nothing() -> None:
    """§4: "no synthesizer is called at all ... which is why nothing is spent on it"."""
    synthesizer = FakeSpeechSynthesizer(formats=[_WEBM])
    harness = _wired(synthesizer=synthesizer)

    spoken = await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert spoken.spoken is None
    assert spoken.spoken_degraded is True
    assert spoken.outcome is not None
    assert spoken.outcome.reply == _ANSWER
    assert synthesizer.call_count == 0


# --- §4: what is rendered, and only that -------------------------------------


async def test_the_value_handed_to_the_seam_is_byte_identical_to_the_reply() -> None:
    """§4: ``spoken`` is the rendering of ``outcome.reply`` **and of nothing else**.

    Nothing decodes the rendering here, and nothing may: that the audio is an
    audible rendering of the text is the synthesizer's obligation, discharged in
    its own conformance suite.
    """
    synthesizer = FakeSpeechSynthesizer()
    harness = _wired(synthesizer=synthesizer)

    spoken = await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    assert synthesizer.spoken_texts == (spoken.outcome.reply,)


async def test_a_parked_pass_renders_nothing_and_does_not_degrade() -> None:
    """§4: "a park ... leaves nothing to say", and nothing is invented to fill it.

    The shape where an implementation treating "no rendering" as a degradation
    would be wrong: nothing was withheld, nothing failed, and there was simply no
    answer — what the user must answer is the confirmation (ADR-0170 §4).
    """
    synthesizer = FakeSpeechSynthesizer()
    harness = _wired(tools=(confirmable(),), synthesizer=synthesizer)

    spoken = await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    assert spoken.outcome.reply is None
    assert spoken.spoken is None
    assert spoken.spoken_degraded is False
    assert synthesizer.call_count == 0


# --- §4: the translation is total, and stated both ways ----------------------


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (SpeechError("the engine wedged"), SpeechFailure.UNCLASSIFIED),
        (SpeechTimeoutError("too slow"), SpeechFailure.TIMED_OUT),
    ],
)
async def test_a_speech_error_from_transcribe_fails_the_call(
    raised: SpeechError, expected: SpeechFailure
) -> None:
    """§4: a ``SpeechError`` out of ``transcribe`` — and nothing else — becomes ours."""
    transcriber = FakeSpeechTranscriber()
    transcriber.fail_next_transcribe(raised)
    harness = _wired(transcriber=transcriber)

    with pytest.raises(TranscriptionFailedError) as caught:
        await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert caught.value.failure is expected


async def test_the_seams_exception_is_not_chained_and_leaves_no_fragment() -> None:
    """§4, §8: raised ``from None``, carrying no part of what the seam said.

    A ``SpeechError`` takes arbitrary text, so an implementation that interpolated
    the clip it could not decode has put the recording inside the exception.
    ``raise ... from exc`` would keep that object reachable as ``__cause__`` and
    render it in the traceback, which is where §8's guarantee cannot reach it and
    where nobody looks.
    """
    transcriber = FakeSpeechTranscriber()
    transcriber.fail_next_transcribe(SpeechError(f"could not decode {_CLIP}"))
    harness = _wired(transcriber=transcriber)

    with pytest.raises(TranscriptionFailedError) as caught:
        await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert _CLIP not in str(caught.value)
    assert _CLIP not in repr(caught.value)


async def test_a_class_named_after_a_known_one_is_still_unclassified() -> None:
    """§4: the walk is matched by **object identity**, never by ``__name__``.

    ``models/routing.py``'s ``_classify`` one boundary out: a speech implementation
    is a stranger and the class it raises can be named anything at all, including a
    name this build declares.
    """

    class SpeechTimeoutError(SpeechError):
        """A stranger's class borrowing a name this build declares."""

    assert classify_speech_failure(SpeechTimeoutError("mine")) is SpeechFailure.UNCLASSIFIED

    transcriber = FakeSpeechTranscriber()
    transcriber.fail_next_transcribe(SpeechTimeoutError("mine"))
    harness = _wired(transcriber=transcriber)

    with pytest.raises(TranscriptionFailedError) as caught:
        await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert caught.value.failure is SpeechFailure.UNCLASSIFIED


async def test_a_speech_error_from_synthesize_degrades_rather_than_failing() -> None:
    """§4: "a failure after there is one would throw away an answer the user already has"."""
    synthesizer = FakeSpeechSynthesizer()
    synthesizer.fail_next_synthesize(SpeechError("the voice model wedged"))
    harness = _wired(synthesizer=synthesizer)

    spoken = await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert spoken.spoken is None
    assert spoken.spoken_degraded is True
    assert spoken.outcome is not None
    assert spoken.outcome.reply == _ANSWER


async def test_a_defect_from_transcribe_propagates_unchanged() -> None:
    """§4: "**Every other exception propagates unchanged**".

    Each stage catches ``SpeechError`` and neither catches ``Exception``: a stage
    that could be wholly broken while every call reported the same
    classified-looking degradation is the state hardest to notice.
    """
    transcriber = FakeSpeechTranscriber()
    transcriber.fail_next_transcribe(RuntimeError("a defect"))
    harness = _wired(transcriber=transcriber)

    with pytest.raises(RuntimeError, match="a defect"):
        await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)


async def test_a_defect_from_synthesize_propagates_rather_than_degrading() -> None:
    """The same clause on the other side, where degradation would have hidden it."""
    synthesizer = FakeSpeechSynthesizer()
    synthesizer.fail_next_synthesize(RuntimeError("a defect"))
    harness = _wired(synthesizer=synthesizer)

    with pytest.raises(RuntimeError, match="a defect"):
        await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)


# --- §8: nothing on this path writes a message it did not author -------------


async def test_a_defects_message_reaches_no_log_tier() -> None:
    """§8's authorship clause, on the path §4 keeps open on purpose.

    ``RuntimeError(audio.content)`` is constructible by the same implementation
    that could construct ``SpeechError(audio.content)``. Propagation is unchanged;
    what is forbidden is any component on this path *writing* that message down.
    """
    transcriber = FakeSpeechTranscriber()
    transcriber.fail_next_transcribe(RuntimeError(_CLIP))
    harness = _wired(transcriber=transcriber)

    with structlog.testing.capture_logs() as captured, pytest.raises(RuntimeError):
        await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert _CLIP not in repr(captured)


async def test_a_seam_failures_message_reaches_no_log_tier() -> None:
    """§8's error-path half: what is logged is the classification, not the seam's words."""
    transcriber = FakeSpeechTranscriber()
    transcriber.fail_next_transcribe(SpeechError(f"could not decode {_CLIP}"))
    harness = _wired(transcriber=transcriber)

    with structlog.testing.capture_logs() as captured, pytest.raises(TranscriptionFailedError):
        await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert _CLIP not in repr(captured)
    assert any(entry.get("failure") == SpeechFailure.UNCLASSIFIED.value for entry in captured)


async def test_no_audio_reaches_any_store_trail_or_log() -> None:
    """§8: the recording and the rendering exist for the call and nowhere else.

    Read over every durable surface this harness exposes — the memory store, the
    audit trail, the source-read trail and both log tiers — because §8's claim is
    over "any store, index, trace, audit trail, routing trail, outbox or log" and a
    check over one of them would pass on an implementation that wrote to another.
    """
    harness = _wired()

    with structlog.testing.capture_logs() as captured:
        spoken = await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert spoken.spoken is not None
    written = repr(
        (
            captured,
            await harness.memory.export(),
            await harness.trail.recent(),
            await harness.reads.recent(),
            await harness.conversation_store.recent(),
        )
    )
    assert _CLIP not in written
    assert spoken.spoken.content not in written


async def test_the_captured_episode_records_no_channel_and_no_audio() -> None:
    """§8: "This ADR adds no field to ``EpisodicMemory``, no field to ``Provenance``".

    The turn a spoken call runs is captured exactly as ADR-0074 §3 captures every
    turn — one episode, whose content is the exchange the transcript drove and
    nothing about where it came from (ADR-0074 §11).
    """
    harness = _wired(transcriber=FakeSpeechTranscriber(transcripts=["what did I do"]))

    await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    episodes = [
        record for record in await harness.memory.export() if isinstance(record, EpisodicMemory)
    ]
    assert len(episodes) == 1
    assert "what did I do" in episodes[0].content
    assert _CLIP not in episodes[0].content


# --- §3: the budget threaded to each stage -----------------------------------


async def test_an_expiry_inside_transcribe_is_a_timed_out_transcription_failure() -> None:
    """§3: expiry inside ``transcribe`` is a ``SpeechTimeoutError``, which §4 translates.

    The **caller's** budget rather than the decorator's, which is §3's other half:
    "the effective bound on a speech stage is the **lesser** of the caller's
    remaining budget and the decorator's". No decorator is wired here at all, so
    the deadline that fires can only be the caller's.
    """
    transcriber = FakeSpeechTranscriber()
    detached = transcriber.suspend_next_transcribe()
    harness = _wired(transcriber=transcriber)

    try:
        with pytest.raises(TranscriptionFailedError) as caught:
            await harness.engine.converse_spoken(
                _recording(), plays=(_MP4,), timeout=timedelta(milliseconds=20)
            )
    finally:
        detached.release()

    assert caught.value.failure is SpeechFailure.TIMED_OUT


async def test_an_expiry_inside_synthesize_degrades() -> None:
    """§3: expiry inside ``synthesize`` is a ``SpeechTimeoutError``, which §4 degrades."""
    synthesizer = FakeSpeechSynthesizer()
    detached = synthesizer.suspend_next_synthesize()
    harness = _wired(synthesizer=synthesizer)

    try:
        spoken = await harness.engine.converse_spoken(
            _recording(), plays=(_MP4,), timeout=timedelta(milliseconds=20)
        )
    finally:
        detached.release()

    assert spoken.spoken is None
    assert spoken.spoken_degraded is True
    assert spoken.outcome is not None
    assert spoken.outcome.reply == _ANSWER


async def test_a_budget_already_spent_is_the_next_stages_expiry() -> None:
    """§3: "A budget already exhausted when a stage is reached is that stage's expiry"."""
    harness = _wired()

    with pytest.raises(TranscriptionFailedError) as caught:
        await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=timedelta(0))

    assert caught.value.failure is SpeechFailure.TIMED_OUT


# --- §4: cancellation is neither failure -------------------------------------


async def test_a_cancellation_inside_transcribe_propagates() -> None:
    """§4: it "never becomes ``TranscriptionFailedError`` and never sets ``spoken_degraded``"."""
    transcriber = FakeSpeechTranscriber()
    detached = transcriber.suspend_next_transcribe()
    harness = _wired(transcriber=transcriber)

    call = asyncio.ensure_future(
        harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)
    )
    await detached.reached()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    detached.release()


async def test_a_cancellation_inside_synthesize_propagates() -> None:
    """The same clause on the other stage, where a degradation would have swallowed it."""
    synthesizer = FakeSpeechSynthesizer()
    detached = synthesizer.suspend_next_synthesize()
    harness = _wired(synthesizer=synthesizer)

    call = asyncio.ensure_future(
        harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)
    )
    await detached.reached()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    detached.release()


# --- §4, §6: the four degradations, and the one that raises ------------------


async def test_an_oversized_rendering_degrades_rather_than_refusing() -> None:
    """§6: "the answer already exists and still travels as ``outcome.reply``"."""
    # A **short** recording and a long rendering, so the bound this case sets binds
    # only the rendering: an oversized *utterance* is refused before any I/O, which
    # is the opposite outcome and would pass a test that never reached the seam.
    harness = _wired(max_spoken_audio_bytes=8)

    spoken = await harness.engine.converse_spoken(
        _recording(payload="ab"), plays=(_MP4,), timeout=PATIENT
    )

    assert spoken.spoken is None
    assert spoken.spoken_degraded is True
    assert spoken.outcome is not None
    assert spoken.outcome.reply == _ANSWER


async def test_a_result_over_the_payload_limit_drops_its_rendering() -> None:
    """§4's fourth case, measured on the **whole projected result**.

    §6 bounds the recording and the rendering each on its own; ADR-0085 §8c bounds
    the serialised whole. So a rendering well inside §6 can still be the byte that
    breaks the frame — and without this case that outcome had no legal value at
    all, since returning it would breach §8c and dropping the rendering would
    contradict §4's own "exactly when".
    """
    lawful = await _wired(planner=NoStepPlanner()).engine.converse_spoken(
        _recording(), plays=(_MP4,), timeout=PATIENT
    )
    assert lawful.spoken is not None
    without = len(canonical_payload(lawful.model_copy(update={"spoken": None})))
    with_rendering = len(canonical_payload(lawful))
    assert without < with_rendering

    tight = _wired(planner=NoStepPlanner(), max_payload_bytes=with_rendering - 1)
    degraded = await tight.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert degraded.spoken is None
    assert degraded.spoken_degraded is True
    assert degraded.outcome is not None
    assert degraded.outcome.reply == _ANSWER
    assert degraded.heard == lawful.heard


async def test_a_result_still_over_the_limit_with_no_rendering_raises() -> None:
    """§4's one-step re-measure: nothing further is dropped, and ``heard`` is not shortened.

    ``heard`` is owed to the caller by §4's disclosure clause and ``outcome`` is the
    answer, so there is no third thing to give up; an implementation that shortened
    either would be truncating a result rather than degrading a rendering.
    """
    lawful = await _wired(planner=NoStepPlanner()).engine.converse_spoken(
        _recording(), plays=(_MP4,), timeout=PATIENT
    )
    # The *degraded* shape's size and not the lawful one's with its rendering
    # blanked: ``spoken_degraded`` flips to ``true``, which is one byte shorter than
    # ``false``, and a limit computed from the wrong shape would admit exactly the
    # value this case needs refused.
    degraded_shape = lawful.model_copy(update={"spoken": None, "spoken_degraded": True})
    without = len(canonical_payload(degraded_shape))
    assert len(canonical_payload(lawful.outcome)) < without - 1

    tight = _wired(planner=NoStepPlanner(), max_payload_bytes=without - 1)
    with pytest.raises(OversizedValueError):
        await tight.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)


# --- §2, §5: where this may and may not be wired -----------------------------


async def test_an_engine_with_no_speech_seams_refuses_rather_than_failing() -> None:
    """A deployment fact is not a seam failure.

    ``TranscriptionFailedError`` would report a hub that has no transcriber as one
    whose transcription failed, and would invite a retry that cannot succeed. This
    is ``Engine.ingest_email``'s shape, and it is a property of *this object's*
    wiring rather than of the contract — the standing ``AssistantEngine``'s own
    docstring gives a shutting-down engine's ``RuntimeError``.
    """
    harness = _wired(transcriber=None, synthesizer=None)

    with pytest.raises(ConfigurationError, match="speech"):
        await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)


@pytest.mark.parametrize("missing", ["transcriber", "synthesizer"])
def test_half_a_speech_pipeline_is_refused_at_construction(missing: str) -> None:
    """One seam without the other can hear and never answer, which nobody chose."""
    with pytest.raises(ConfigurationError, match="both"):
        _wired(**{missing: None})


def test_the_service_package_holds_neither_speech_protocol() -> None:
    """§5: "none is wired into ``ai_assistant.service`` as a resident job".

    Read over the package's own source rather than over an import graph, because a
    module that merely *named* either Protocol would already be a step toward the
    wiring §5 forbids — so the check is the stricter of the two.
    """
    from ai_assistant import service  # noqa: PLC0415 — asserted about

    _assert_no_speech_protocol_under(Path(service.__file__).parent)


def test_no_module_under_interfaces_references_either_speech_protocol() -> None:
    """§2: "no adapter calls a ``SpeechTranscriber`` or a ``SpeechSynthesizer`` at all"."""
    from ai_assistant import interfaces  # noqa: PLC0415 — asserted about

    _assert_no_speech_protocol_under(Path(interfaces.__file__).parent)


def _assert_no_speech_protocol_under(root: Path) -> None:
    """Fail if any module under ``root`` names either speech Protocol."""
    modules = sorted(root.rglob("*.py"))
    assert modules, f"{root} holds no modules, so this check would pass vacuously"
    for module in modules:
        source = module.read_text(encoding="utf-8")
        assert "SpeechTranscriber" not in source, module
        assert "SpeechSynthesizer" not in source, module


def test_the_wire_codec_carries_no_audio_branch() -> None:
    """§9: "``wire/codec.py``'s ``project`` gains no branch".

    Audio crosses as :data:`~ai_assistant.core.types.Base64Audio`, which is text,
    so the codec needs to know nothing about it — and a lane that reached for a
    ``bytes`` row would be taking the supersession ADR-0200 §9 declined.
    """
    from ai_assistant.wire import codec  # noqa: PLC0415 — asserted about

    source = Path(codec.__file__).read_text(encoding="utf-8")
    for name in ("SpokenAudio", "Base64Audio", "SpokenAudioFormat", "b64", "base64"):
        assert name not in source, name


def test_a_frozenset_of_formats_has_no_wire_form() -> None:
    """§3: ``plays`` is a tuple because a set would fail closed at the first call.

    ``wire/codec.py``'s ``project`` dispatches ``list | tuple`` and has no branch
    for a ``set`` or a ``frozenset``, so a set-typed argument raises rather than
    guessing at an order — the same fallthrough that decides §9.
    """
    from ai_assistant.wire.codec import project  # noqa: PLC0415 — asserted about

    assert project((_MP4, _WEBM)) == [_MP4.value, _WEBM.value]
    with pytest.raises(TypeError):
        project(frozenset({_MP4}))


# --- §3: the budget is threaded, and the turn keeps its own semantics ---------


class _RaisingPlanner:
    """A ``Planner`` whose plan fails, so the turn raises rather than degrading."""

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        """Raise ``PlanningError``, which is one of ``converse``'s declared failures."""
        del goal, context, memories
        msg = "the request could not be planned"
        raise PlanningError(msg)


async def test_the_turn_is_given_what_is_left_of_the_callers_budget() -> None:
    """§3, ADR-0029 §4: "the caller's budget, threaded to the seam that owns the deadline".

    ``converse`` hands the executor the caller's budget whole, because the turn is
    the whole call there. A spoken call spends part of it on transcription first, so
    what reaches the executor is strictly less — which is the difference between a
    budget threaded and one restarted at each stage, and it is observable without
    any wall-clock assertion.
    """
    spoken_seen = _recording_invoker(spoken := _wired(tools=(tool(),)))
    await spoken.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    written_seen = _recording_invoker(written := _wired(tools=(tool(),)))
    await written.engine.converse("what is on", timeout=PATIENT)

    assert written_seen == [PATIENT]
    assert len(spoken_seen) == 1
    assert spoken_seen[0] < PATIENT


def _recording_invoker(harness: Harness) -> list[timedelta]:
    """Record every deadline the harness's tool seam is handed.

    The instance attribute shadows the bound method, so the runner and the executor
    — which hold this very object — go through the recorder without the harness
    needing a knob for it.
    """
    seen: list[timedelta] = []
    original = harness.invoker.invoke

    async def recording(
        call: ToolCall,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — mirroring ``ToolInvoker.invoke``, whose seam owns the deadline (ADR-0029 §4)
    ) -> ToolResult:
        seen.append(timeout)
        return await original(call, timeout=timeout)

    harness.invoker.invoke = recording  # type: ignore[method-assign]
    return seen


async def test_the_turns_own_failure_is_neither_a_transcription_nor_a_synthesis_one() -> None:
    """§3: "Expiry during the turn behaves exactly as it does on ``converse``".

    Generalised to the turn's failures, which is the substance of that clause and
    the half an implementation could get wrong: a ``PlanningError`` from the middle
    stage is one of ``converse``'s declared failures and stays one. It never becomes
    ``TranscriptionFailedError`` — that class means the *seam* failed — and it never
    arrives as a degradation, because nothing about the answer is degraded when
    there is no answer.
    """
    spoken = _wired(planner=_RaisingPlanner())
    with pytest.raises(PlanningError):
        await spoken.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    written = _wired(planner=_RaisingPlanner())
    with pytest.raises(PlanningError):
        await written.engine.converse("what is on", timeout=PATIENT)


# --- §5: a wedged seam does not stall the loop --------------------------------


async def test_a_wedged_seam_does_not_stall_the_event_loop() -> None:
    """§5: blocking work runs off the loop, on threads the implementation owns.

    What the *engine* owes here is that awaiting a seam suspends only the call
    awaiting it. A seam held open mid-flight leaves the loop free, so a second turn
    runs to completion beside it — which is ADR-0118 §7's "a live hub with a dead
    capability, not a live hub that recovers", observed from the hub's side.
    """
    transcriber = FakeSpeechTranscriber()
    detached = transcriber.suspend_next_transcribe()
    # Two turns run against this harness, so each needs its own goal id: the default
    # factory answers one constant, and a second turn reusing it is refused by the
    # plan store rather than by anything this case is about.
    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = _wired(transcriber=transcriber, loop_id_factory=lambda: next(goals))

    wedged = asyncio.ensure_future(
        harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)
    )
    await detached.reached()

    beside = await asyncio.wait_for(
        harness.engine.converse("what is on", timeout=PATIENT), timeout=5
    )

    assert beside.reply == _ANSWER
    assert not wedged.done()
    detached.release()
    await wedged


# --- §4: every raise on this path passes its classification -------------------


def test_every_transcription_failure_raised_in_orchestration_names_its_failure() -> None:
    """§4: "Every raise on this path passes ``failure`` explicitly".

    The default exists for ADR-0085 §10a's reduced payload and for nothing else, and
    an implementation that leaned on it would silently report every seam failure as
    ``UNCLASSIFIED`` beside ``details_elided`` ``False`` — which reads as "the seam
    raised a bare ``SpeechError``" and would be a lie on every timeout.

    Checked over the syntax rather than over a run, because a run only reaches the
    raises the cases happen to drive.
    """
    root = Path(engine_module.__file__).parent
    raises = [
        node
        for module in sorted(root.rglob("*.py"))
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "TranscriptionFailedError"
    ]
    assert raises, "no TranscriptionFailedError is constructed in orchestration/"
    for call in raises:
        assert any(keyword.arg == "failure" for keyword in call.keywords), ast.dump(call)
