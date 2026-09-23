"""The engine driving ADR-0276's understanding stage: where it runs and what is recorded.

The stage's own behaviour — its windows, its one repair, its resolution — is in
``test_understanding.py``, and the carrier's bound and classification in
``test_activation_state.py``. What is left is only true of a whole pass: that the stage
runs after routing declines and before association on the conversational path and
before the event stage on the event path, that each branch ending a pass without an
understanding records the omission it names, that a spoken turn takes no episode
window, and that the event path maps the stage's failures outward as ADR-0274 §8 maps
the event stage's own.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from channel_receiver_contract import event_input
from test_engine import AT, Harness, NoStepPlanner
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.errors import (
    ChannelProcessingError,
    ChannelProcessingTimeoutError,
    ConfigurationError,
    ModelError,
    ModelTimeoutError,
    SpeechError,
    TranscriptionFailedError,
    UnderstandingError,
)
from ai_assistant.core.types import (
    ChannelInput,
    EpisodicMemory,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    RoutableOperation,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenReply,
    TextChannelPayload,
    UnderstandingOmission,
    UnderstandingProducer,
    WholeTextReply,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.informational_events import InformationalEventStage
from ai_assistant.orchestration.routing import RoutingStage
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakeRoutingRecorder,
    FakeSpeechTranscriber,
    FakeStreamingCompleter,
)
from ai_assistant.testing.speech import DEFAULT_TRANSCRIPT

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import (
        ChannelResult,
        EpisodeProcessingRecord,
        GoalBrief,
        Message,
        PlannerOutput,
    )

_BUDGET: Final = timedelta(seconds=10)
_UTTERANCE: Final = "Is our camping trip still on?"


class _Order:
    """One list every seam a case orders appends to, so the sequence is one fact."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def model(
        self, name: str, reply: str | Callable[[Sequence[Message]], str]
    ) -> FakeModelProvider:
        def answer(messages: Sequence[Message]) -> str:
            self.seen.append(name)
            return reply(messages) if callable(reply) else reply

        return FakeModelProvider(answer)


class _OrderedPlanner(NoStepPlanner):
    def __init__(self, order: _Order) -> None:
        self._order = order

    async def plan(self, goal: GoalBrief, **kwargs: Any) -> PlannerOutput:
        self._order.seen.append("plan")
        return await super().plan(goal, **kwargs)


def _harness(understanding_model: FakeModelProvider, **knobs: Any) -> Harness:
    memory = knobs.pop("memory", None) or FakeMemoryStore(now=lambda: AT)
    knobs.setdefault("planner", NoStepPlanner())
    knobs.setdefault(
        "composing",
        ComposingStage(model=FakeModelProvider("Yes."), streaming=FakeStreamingCompleter()),
    )
    return Harness(
        memory=memory,
        understanding=understanding_stage(memory, model=understanding_model),
        **knobs,
    )


def _text(text: str = _UTTERANCE) -> ChannelInput:
    return ChannelInput(target=NewConversation(), payload=TextChannelPayload(text=text))


def _speech() -> ChannelInput:
    return ChannelInput(
        target=NewConversation(),
        payload=SpeechChannelPayload(
            audio=SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)
        ),
    )


_SPOKEN: Final = SpokenReply(plays=(SpokenAudioFormat.MP4,))


async def _record(harness: Harness) -> EpisodeProcessingRecord:
    """The one captured episode's processing record."""
    (episode,) = [r for r in await harness.memory.export() if isinstance(r, EpisodicMemory)]
    assert episode.processing_record is not None
    return episode.processing_record


def _sent(model: FakeModelProvider, call: int = -1) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(model.calls[call].messages[1].content)
    return payload


class _Raising(FakeModelProvider):
    """A provider whose every completion raises ``error`` exactly as classified.

    The canonical fake wraps a reply callable's raise in a plain ``ModelError``, which
    is right for it and would hide the one distinction these cases are about.
    """

    def __init__(self, error: ModelError) -> None:
        super().__init__()
        self._error = error

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        raise self._error


# --- the conversational path ---------------------------------------------------------


async def test_a_turn_records_version_one_understood_before_it_was_planned() -> None:
    """§5: after routing declined and the conversation resolved, before the goal's work."""
    order = _Order()
    model = order.model("understand", STATED_PROPOSAL)
    harness = _harness(model, planner=_OrderedPlanner(order))
    result = await harness.engine.receive(_text(), reply=WholeTextReply(), timeout=_BUDGET)
    assert result.capture.state == "recorded"
    assert order.seen == ["understand", "plan"]
    assert _sent(model)["input"]["text"] == _UTTERANCE
    record = await _record(harness)
    (understood,) = record.understanding
    assert understood.version == 1
    assert understood.producer is UnderstandingProducer.INTERPRETATION
    assert understood.meaning == "The input means what it says."
    assert record.understanding_omitted is None
    assert record.understanding_elided == 0


async def test_a_taken_route_records_routed_and_never_enters_the_stage() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    router = FakeModelProvider(
        json.dumps({"operation": RoutableOperation.FORGET.value, "query": "x"})
    )
    harness = _harness(model, routing=RoutingStage(model=router, recorder=FakeRoutingRecorder()))
    await harness.engine.receive(_text("forget that"), reply=WholeTextReply(), timeout=_BUDGET)
    assert model.calls == []
    record = await _record(harness)
    assert record.understanding == ()
    assert record.understanding_omitted is UnderstandingOmission.ROUTED


async def test_a_declined_route_reaches_the_stage() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    router = FakeModelProvider(json.dumps({"operation": "none"}))
    harness = _harness(model, routing=RoutingStage(model=router, recorder=FakeRoutingRecorder()))
    await harness.engine.receive(_text(), reply=WholeTextReply(), timeout=_BUDGET)
    assert len(model.calls) == 1
    assert (await _record(harness)).understanding_omitted is None


async def test_an_understanding_error_fails_the_pass_before_association() -> None:
    """§6: no substitute, no goal work, and the reason is its own terminal row."""
    order = _Order()
    model = order.model("understand", "not json")
    harness = _harness(model, planner=_OrderedPlanner(order))
    with pytest.raises(UnderstandingError):
        await harness.engine.receive(_text(), reply=WholeTextReply(), timeout=_BUDGET)
    assert order.seen == ["understand", "understand"]
    assert harness.associator.call_count == 0
    record = await _record(harness)
    assert (record.status, record.reason) == (
        ProcessingStatus.FAILED,
        ProcessingReason.UNDERSTANDING_FAILED,
    )
    assert record.understanding == ()
    assert record.understanding_omitted is UnderstandingOmission.FAILED


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ModelTimeoutError("provider timed out"), ProcessingReason.TIMEOUT),
        (ModelError("provider down"), ProcessingReason.PROCESSING_FAILED),
    ],
)
async def test_a_model_error_takes_the_row_its_class_already_takes(
    error: ModelError, reason: ProcessingReason
) -> None:
    harness = _harness(_Raising(error))
    with pytest.raises(type(error)):
        await harness.engine.receive(_text(), reply=WholeTextReply(), timeout=_BUDGET)
    record = await _record(harness)
    assert record.reason is reason
    assert record.understanding_omitted is UnderstandingOmission.FAILED
    assert str(error) not in record.model_dump_json()


class _Stalled(FakeModelProvider):
    """A provider that answers only after ``seconds`` — longer than any budget here."""

    def __init__(self, reply: str, *, seconds: float = 10.0) -> None:
        super().__init__(reply)
        self._seconds = seconds

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        await asyncio.sleep(self._seconds)
        return await super().complete(messages, model=model)


async def test_a_deadline_expiring_inside_the_stage_is_a_classified_timeout() -> None:
    """§5: the stage runs inside the pass's existing deadline; §6: `failed / timeout`."""
    harness = _harness(_Stalled(STATED_PROPOSAL))
    with pytest.raises(ModelTimeoutError):
        await harness.engine.receive(
            _text(), reply=WholeTextReply(), timeout=timedelta(milliseconds=50)
        )
    assert harness.associator.call_count == 0
    record = await _record(harness)
    assert (record.status, record.reason) == (ProcessingStatus.FAILED, ProcessingReason.TIMEOUT)
    assert record.understanding_omitted is UnderstandingOmission.FAILED


class _Blocking(FakeModelProvider):
    """A provider that answers without yielding, after the budget is spent.

    The loop never gets control while it runs, so no timer can fire inside the stage:
    only a check of the deadline after the stage returns can see it was crossed.
    """

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        time.sleep(0.06)  # noqa: ASYNC251 — the point: a completion that never yields
        return await super().complete(messages, model=model)


async def test_a_stage_that_crosses_the_deadline_without_yielding_is_still_timed_out() -> None:
    harness = _harness(_Blocking(STATED_PROPOSAL))
    with pytest.raises(ModelTimeoutError):
        await harness.engine.receive(
            _text(), reply=WholeTextReply(), timeout=timedelta(milliseconds=50)
        )
    assert harness.associator.call_count == 0
    record = await _record(harness)
    assert record.reason is ProcessingReason.TIMEOUT
    assert record.understanding == ()
    assert record.understanding_omitted is UnderstandingOmission.FAILED


async def test_a_late_unparseable_output_is_the_timeout_and_earns_no_repair() -> None:
    model = _Blocking("not json")
    harness = _harness(model)
    with pytest.raises(ModelTimeoutError):
        await harness.engine.receive(
            _text(), reply=WholeTextReply(), timeout=timedelta(milliseconds=50)
        )
    assert len(model.calls) == 1
    record = await _record(harness)
    assert record.reason is ProcessingReason.TIMEOUT
    assert record.understanding_omitted is UnderstandingOmission.FAILED


async def test_a_deadline_that_expired_ahead_of_the_stage_is_not_reached() -> None:
    """§5: routing spent the budget, so the stage is never entered."""
    model = FakeModelProvider(STATED_PROPOSAL)
    router = _Stalled(json.dumps({"operation": "none"}), seconds=0.1)
    harness = _harness(model, routing=RoutingStage(model=router, recorder=FakeRoutingRecorder()))
    with pytest.raises(ModelTimeoutError):
        await harness.engine.receive(
            _text(), reply=WholeTextReply(), timeout=timedelta(milliseconds=20)
        )
    assert model.calls == []
    record = await _record(harness)
    assert record.reason is ProcessingReason.TIMEOUT
    assert record.understanding_omitted is UnderstandingOmission.NOT_REACHED


# --- the spoken path --------------------------------------------------------------------


async def test_a_spoken_turn_is_understood_from_its_transcript_with_no_episode_window() -> None:
    """§4, ADR-0250 §15: `converse_spoken` takes no episode window."""
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(model)
    await harness.engine.receive(
        _text("an earlier typed turn"), reply=WholeTextReply(), timeout=_BUDGET
    )
    await harness.engine.receive(_speech(), reply=_SPOKEN, timeout=_BUDGET)
    sent = _sent(model)
    assert sent["input"]["text"] == DEFAULT_TRANSCRIPT
    assert sent["episode_window"] == "not provided for input on this channel"


async def test_speech_with_no_words_records_no_text_and_never_enters_the_stage() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(model, transcriber=FakeSpeechTranscriber(transcripts=["  "]))
    await harness.engine.receive(_speech(), reply=_SPOKEN, timeout=_BUDGET)
    assert model.calls == []
    assert (await _record(harness)).understanding_omitted is UnderstandingOmission.NO_TEXT


async def test_a_failed_transcription_records_no_text() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    transcriber = FakeSpeechTranscriber()
    transcriber.fail_next_transcribe(SpeechError("private"))
    harness = _harness(model, transcriber=transcriber)
    with pytest.raises(TranscriptionFailedError):
        await harness.engine.receive(_speech(), reply=_SPOKEN, timeout=_BUDGET)
    assert model.calls == []
    record = await _record(harness)
    assert record.reason is ProcessingReason.TRANSCRIPTION_FAILED
    assert record.understanding_omitted is UnderstandingOmission.NO_TEXT


# --- the event path -----------------------------------------------------------------------


async def test_an_event_is_understood_before_the_event_stage_over_its_supplied_window() -> None:
    order = _Order()
    model = order.model("understand", STATED_PROPOSAL)
    events = InformationalEventStage(order.model("event", "Eco mode."))
    harness = _harness(model, informational_events=events)
    result = await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)
    assert result.capture.state == "recorded"
    assert order.seen == ["understand", "event"]
    sent = _sent(model)
    assert sent["input"]["received_as"].startswith("a report received on informational_event")
    assert [item["label"] for item in sent["channel_window"]] == ["H1"]
    record = await _record(harness)
    assert [u.version for u in record.understanding] == [1]
    assert record.understanding_omitted is None


@pytest.mark.parametrize(
    ("script", "raised", "reason"),
    [
        (
            FakeModelProvider("not json"),
            ChannelProcessingError,
            ProcessingReason.UNDERSTANDING_FAILED,
        ),
        (
            _Raising(ModelTimeoutError("provider timed out")),
            ChannelProcessingTimeoutError,
            ProcessingReason.TIMEOUT,
        ),
        (
            _Raising(ModelError("provider down")),
            ChannelProcessingError,
            ProcessingReason.PROCESSING_FAILED,
        ),
    ],
)
async def test_an_event_passes_failure_is_mapped_as_the_event_stages_own(
    script: FakeModelProvider,
    raised: type[ChannelProcessingError],
    reason: ProcessingReason,
) -> None:
    """§6 on ADR-0274 §8's partition: the event stage is never reached."""
    events_model = FakeModelProvider("Eco mode.")
    harness = _harness(script, informational_events=InformationalEventStage(events_model))
    with pytest.raises(raised) as caught:
        await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)
    assert type(caught.value) is raised
    assert caught.value.__cause__ is None
    assert events_model.calls == []
    record = await _record(harness)
    assert record.reason is reason
    assert record.understanding_omitted is UnderstandingOmission.FAILED


async def test_an_event_deadline_expiring_inside_the_stage_maps_to_the_timeout_error() -> None:
    events_model = FakeModelProvider("Eco mode.")
    harness = _harness(
        _Stalled(STATED_PROPOSAL), informational_events=InformationalEventStage(events_model)
    )
    with pytest.raises(ChannelProcessingTimeoutError):
        await harness.engine.receive(event_input(), reply=None, timeout=timedelta(milliseconds=50))
    assert events_model.calls == []
    record = await _record(harness)
    assert record.reason is ProcessingReason.TIMEOUT
    assert record.understanding_omitted is UnderstandingOmission.FAILED


async def test_an_event_captured_on_one_channel_is_in_a_conversations_episode_window() -> None:
    """§4: across every channel, attributed from the record as a report received."""
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(
        model, informational_events=InformationalEventStage(FakeModelProvider("Eco mode."))
    )
    await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)
    await harness.engine.receive(_text(), reply=WholeTextReply(), timeout=_BUDGET)
    (episode,) = _sent(model)["episode_window"]
    assert episode["label"] == "P1"
    assert episode["input"] == "The thermostat entered eco mode at 18:00."
    assert episode["item"].startswith("a report received on informational_event:thermostat-1")
    assert episode["understood_then"]["meaning"] == "The input means what it says."


async def test_a_second_turn_sees_the_first_under_h_and_not_again_under_p() -> None:
    """§3's same-exchange rule, end to end: the tail's episode is not in the P window."""
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(model)
    first: ChannelResult = await harness.engine.receive(
        _text("Find a campsite."), reply=WholeTextReply(), timeout=_BUDGET
    )
    assert first.channel is not None
    await harness.engine.receive(
        ChannelInput(target=first.channel, payload=TextChannelPayload(text=_UTTERANCE)),
        reply=WholeTextReply(),
        timeout=_BUDGET,
    )
    sent = _sent(model)
    (item,) = sent["channel_window"]
    assert item["label"] == "H1"
    assert item["also_in_episode_window"] is True
    assert sent["episode_window"].startswith("missing")


# --- wiring ---------------------------------------------------------------------------------


@pytest.mark.parametrize("limit", [None, 1])
def test_a_stage_wired_without_a_version_bound_of_two_is_refused(limit: int | None) -> None:
    with pytest.raises(ConfigurationError, match="version bound"):
        _harness(FakeModelProvider(STATED_PROPOSAL), understanding_version_limit=limit)


async def test_an_engine_with_no_stage_records_not_reached() -> None:
    harness = Harness(planner=NoStepPlanner())
    await harness.engine.receive(_text(), reply=WholeTextReply(), timeout=_BUDGET)
    record = await _record(harness)
    assert record.understanding == ()
    assert record.understanding_omitted is UnderstandingOmission.NOT_REACHED
