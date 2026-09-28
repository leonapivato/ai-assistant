"""The stage record each activation kind carries, end entry included (ADR-0280 §8).

Every case wires the understanding stage as the composition root does, except the one
that says it does not, and asserts the **exact** entries of the one captured episode's
processing record — which stage ran, the rule that made it due and how it ended — and
that no entry is the M38 loop guard's ``stage_repeated``. The rules and the controller
alone are in ``test_controller.py``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from channel_receiver_contract import event_input
from test_activation_state import _admitted
from test_channel_receiver import ControlledModel
from test_engine import AT, Harness, NoStepPlanner, confirmable, tool
from test_engine_goal_association import _associating, _goal, _seed
from understanding_support import STATED_PROPOSAL, recall_stage, understanding_stage

from ai_assistant.core.errors import (
    ModelTimeoutError,
    SpeechError,
    TranscriptionFailedError,
    UnderstandingError,
)
from ai_assistant.core.types import (
    AssociationVerdict,
    ChannelInput,
    ControllerRule,
    ControllerStage,
    EpisodicMemory,
    Ground,
    NewConversation,
    ProcessingStatus,
    ProposedElement,
    ProposedQuestion,
    ProposedUnderstanding,
    RoutableOperation,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenReply,
    StageOutcome,
    TextChannelPayload,
)
from ai_assistant.orchestration.activation_state import ActivationScope
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

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import EpisodeProcessingRecord, Message

_BUDGET: Final = timedelta(seconds=10)
_SPOKEN: Final = SpokenReply(plays=(SpokenAudioFormat.MP4,))

_S = ControllerStage
_R = ControllerRule
_DONE = StageOutcome.DONE

#: The stages every turn that reaches its turn loop runs first.
_TO_THE_LOOP: Final = [
    (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
    (_S.RECALL, _R.NOT_RECALLED, _DONE),
    (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
    (_S.ASSOCIATE_GOAL, _R.ASSOCIATION_DUE, _DONE),
    (_S.TURN_LOOP, _R.UNPLANNED, _DONE),
]
_COMPOSED_AND_ENDED: Final = [
    (_S.COMPOSE, _R.REPLY_OWED, _DONE),
    (_S.END, _R.NOTHING_DUE, _DONE),
]


def _harness(**knobs: Any) -> Harness:
    memory = knobs.pop("memory", None) or FakeMemoryStore(now=lambda: AT)
    knobs.setdefault(
        "composing",
        ComposingStage(model=FakeModelProvider("Yes."), streaming=FakeStreamingCompleter()),
    )
    understanding = knobs.pop("understanding_model", FakeModelProvider(STATED_PROPOSAL))
    knobs.setdefault("recall", recall_stage(memory))
    return Harness(
        memory=memory, understanding=understanding_stage(memory, model=understanding), **knobs
    )


def _text(text: str = "book the campsite") -> ChannelInput:
    return ChannelInput(target=NewConversation(), payload=TextChannelPayload(text=text))


def _speech() -> ChannelInput:
    return ChannelInput(
        target=NewConversation(),
        payload=SpeechChannelPayload(
            audio=SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)
        ),
    )


async def _record(harness: Harness) -> EpisodeProcessingRecord:
    (episode,) = [r for r in await harness.memory.export() if isinstance(r, EpisodicMemory)]
    assert episode.processing_record is not None
    return episode.processing_record


def _stages(
    record: EpisodeProcessingRecord,
) -> list[tuple[ControllerStage, ControllerRule, StageOutcome]]:
    """The record's entries as (stage, rule, outcome), asserting the guard never fired."""
    assert all(entry.due is not ControllerRule.STAGE_REPEATED for entry in record.stages)
    assert record.stages_elided == 0
    end = record.stages[-1]
    assert end.started_at == end.ended_at
    return [(entry.stage, entry.due, entry.outcome) for entry in record.stages]


async def _entries(harness: Harness) -> list[tuple[ControllerStage, ControllerRule, StageOutcome]]:
    return _stages(await _record(harness))


def _activation(harness: Harness) -> asyncio.Task[Any]:
    """The one admitted activation a shielded call is running."""
    (task,) = harness.engine._inflight
    return task


# --- typed turns --------------------------------------------------------------------


async def test_a_typed_turn_that_drives_a_step() -> None:
    harness = _harness(tools=(tool(),))
    outcome = await harness.engine.converse("send the note", timeout=_BUDGET)
    assert outcome.step is not None
    assert outcome.step.confirmation is None
    assert await _entries(harness) == [
        *_TO_THE_LOOP,
        (_S.DRIVE, _R.PLAN_HAS_STEPS, _DONE),
        *_COMPOSED_AND_ENDED,
    ]


class _Asking(NoStepPlanner):
    async def plan(self, goal: Any, **fields: Any) -> Any:
        produced = await super().plan(goal, **fields)
        return produced.model_copy(
            update={
                "understanding": ProposedUnderstanding(
                    retains_outcome=True,
                    criteria=(
                        ProposedElement(text="a pitch by the river", ground=Ground.INFERRED),
                    ),
                    questions=(ProposedQuestion(text="Which campsite?", about="S1"),),
                )
            }
        )


async def test_a_typed_turn_that_raises_a_question() -> None:
    harness = _harness(planner=_Asking())
    outcome = await harness.engine.converse("book the campsite", timeout=_BUDGET)
    assert outcome.clarification is not None
    assert await _entries(harness) == [*_TO_THE_LOOP, *_COMPOSED_AND_ENDED]


async def test_a_typed_turn_that_plans_no_step() -> None:
    harness = _harness(planner=NoStepPlanner())
    await harness.engine.converse("what is two plus two?", timeout=_BUDGET)
    assert await _entries(harness) == [*_TO_THE_LOOP, *_COMPOSED_AND_ENDED]


async def test_a_turn_that_ends_in_a_disambiguation() -> None:
    harness = _harness(
        planner=NoStepPlanner(), associator=_associating(AssociationVerdict.UNDECIDED, "G1", "G2")
    )
    conversation = (await harness.conversations.begin(None)).id
    for goal_id, statement in (("goal-one", "book a campsite"), ("goal-two", "book a flight")):
        await _seed(
            harness.plans,
            _goal(goal_id, statement, conversation=conversation),
            engaged_in=conversation,
        )
    outcome = await harness.engine.converse(
        "make it Sunday", timeout=_BUDGET, conversation_id=conversation
    )
    assert outcome.disambiguation is not None
    assert await _entries(harness) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
        (_S.ASSOCIATE_GOAL, _R.ASSOCIATION_DUE, _DONE),
        (_S.ASK_DISAMBIGUATION, _R.DISAMBIGUATION_RAISED, _DONE),
        (_S.END, _R.NOTHING_DUE, _DONE),
    ]


async def test_a_turn_whose_step_parks_for_confirmation_composes_nothing() -> None:
    harness = _harness(tools=(confirmable(),))
    outcome = await harness.engine.converse("send the note", timeout=_BUDGET)
    assert outcome.step is not None
    assert outcome.step.confirmation is not None
    assert await _entries(harness) == [
        *_TO_THE_LOOP,
        (_S.DRIVE, _R.PLAN_HAS_STEPS, _DONE),
        (_S.END, _R.NOTHING_DUE, _DONE),
    ]


def _routing(operation: str) -> RoutingStage:
    reply = (
        {"operation": operation, "query": "the campsite"}
        if operation != "none"
        else {"operation": "none"}
    )
    return RoutingStage(model=FakeModelProvider(json.dumps(reply)), recorder=FakeRoutingRecorder())


async def test_a_routed_turn_ends_on_the_taken_route() -> None:
    harness = _harness(planner=NoStepPlanner(), routing=_routing(RoutableOperation.FORGET.value))
    outcome = await harness.engine.converse("forget the campsite", timeout=_BUDGET)
    assert outcome.routed is not None
    assert await _entries(harness) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.ROUTING, _R.ROUTE_UNCHECKED, _DONE),
        (_S.END, _R.ROUTE_TAKEN, _DONE),
    ]


async def test_a_declined_route_is_a_decision_and_the_turn_goes_on() -> None:
    harness = _harness(planner=NoStepPlanner(), routing=_routing("none"))
    await harness.engine.converse("book the campsite", timeout=_BUDGET)
    assert await _entries(harness) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.ROUTING, _R.ROUTE_UNCHECKED, _DONE),
        *_TO_THE_LOOP[1:],
        *_COMPOSED_AND_ENDED,
    ]


async def test_a_degraded_composition_is_composed_once_and_the_pass_ends() -> None:
    """ADR-0170 §8's blank completion: one ``compose`` entry, then ``nothing_due``."""
    composer = FakeModelProvider("")
    harness = _harness(
        planner=NoStepPlanner(),
        composing=ComposingStage(model=composer, streaming=FakeStreamingCompleter()),
    )
    outcome = await harness.engine.converse("say something", timeout=_BUDGET)
    assert outcome.reply_degraded is True
    assert len(composer.calls) == 1
    assert await _entries(harness) == [*_TO_THE_LOOP, *_COMPOSED_AND_ENDED]


async def test_a_pass_whose_understanding_fails_ends_on_the_failed_stage() -> None:
    harness = _harness(planner=NoStepPlanner(), understanding_model=FakeModelProvider("not json"))
    with pytest.raises(UnderstandingError):
        await harness.engine.converse("book the campsite", timeout=_BUDGET)
    assert await _entries(harness) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, StageOutcome.FAILED),
        (_S.END, _R.STAGE_FAILED, _DONE),
    ]


class _Stalled(FakeModelProvider):
    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        await asyncio.sleep(10)
        return await super().complete(messages, model=model)


async def test_a_pass_whose_understanding_times_out_ends_on_the_timed_out_stage() -> None:
    harness = _harness(planner=NoStepPlanner(), understanding_model=_Stalled(STATED_PROPOSAL))
    with pytest.raises(ModelTimeoutError):
        await harness.engine.converse("book the campsite", timeout=timedelta(milliseconds=50))
    record = await _record(harness)
    assert record.status is ProcessingStatus.FAILED
    assert _stages(record) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]


class _SlowDecline(FakeModelProvider):
    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        await asyncio.sleep(0.1)
        return await super().complete(messages, model=model)


async def test_an_understanding_stage_due_past_the_deadline_is_not_entered() -> None:
    """§5: routing spent the budget, so understanding reads no history and times out."""
    router = RoutingStage(
        model=_SlowDecline(json.dumps({"operation": "none"})), recorder=FakeRoutingRecorder()
    )
    # Recall unwired, so understanding is the stage due past the deadline.
    harness = _harness(planner=NoStepPlanner(), routing=router, recall=None)
    reads: list[str] = []
    history = harness.engine._conversations.history

    async def counted(conversation_id: str) -> Any:
        reads.append(conversation_id)
        return await history(conversation_id)

    harness.engine._conversations.history = counted  # type: ignore[method-assign]  # observe the read
    with pytest.raises(ModelTimeoutError):
        await harness.engine.converse("book the campsite", timeout=timedelta(milliseconds=20))
    assert reads == []
    assert await _entries(harness) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.ROUTING, _R.ROUTE_UNCHECKED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]


async def test_a_history_read_outlasting_the_deadline_times_the_stage_out() -> None:
    """§5: expiry during the stage, before the understanding model is called."""
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(planner=NoStepPlanner(), understanding_model=model)

    async def hangs(conversation_id: str) -> Any:
        await asyncio.sleep(10)

    harness.engine._conversations.history = hangs  # type: ignore[method-assign]  # a read that never returns in time
    with pytest.raises(ModelTimeoutError):
        await harness.engine.converse("book the campsite", timeout=timedelta(milliseconds=50))
    assert model.calls == []
    assert await _entries(harness) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]


# --- spoken turns ---------------------------------------------------------------------


async def test_a_spoken_turn_runs_the_turns_stages_over_its_transcript() -> None:
    harness = _harness(planner=NoStepPlanner())
    await harness.engine.receive(_speech(), reply=_SPOKEN, timeout=_BUDGET)
    assert await _entries(harness) == [*_TO_THE_LOOP, *_COMPOSED_AND_ENDED]


async def test_a_spoken_turn_with_no_words_records_no_text_input() -> None:
    harness = _harness(
        planner=NoStepPlanner(), transcriber=FakeSpeechTranscriber(transcripts=["  "])
    )
    await harness.engine.receive(_speech(), reply=_SPOKEN, timeout=_BUDGET)
    assert await _entries(harness) == [(_S.END, _R.NO_TEXT_INPUT, _DONE)]


async def test_a_spoken_turn_whose_transcription_fails_records_no_text_input() -> None:
    transcriber = FakeSpeechTranscriber()
    transcriber.fail_next_transcribe(SpeechError("private"))
    harness = _harness(planner=NoStepPlanner(), transcriber=transcriber)
    with pytest.raises(TranscriptionFailedError):
        await harness.engine.receive(_speech(), reply=_SPOKEN, timeout=_BUDGET)
    assert await _entries(harness) == [(_S.END, _R.NO_TEXT_INPUT, _DONE)]


async def test_a_pass_cancelled_during_transcription_records_interrupted() -> None:
    transcriber = FakeSpeechTranscriber()
    work = transcriber.suspend_next_transcribe()
    harness = _harness(planner=NoStepPlanner(), transcriber=transcriber)
    call = asyncio.create_task(harness.engine.receive(_speech(), reply=_SPOKEN, timeout=_BUDGET))
    await work.reached()
    _activation(harness).cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    record = await _record(harness)
    assert record.status is ProcessingStatus.INTERRUPTED
    assert _stages(record) == [(_S.END, _R.INTERRUPTED, _DONE)]


# --- informational events ----------------------------------------------------------------


async def test_an_informational_event_is_understood_then_summarized() -> None:
    harness = _harness(informational_events=InformationalEventStage(FakeModelProvider("Eco.")))
    await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)
    assert await _entries(harness) == [
        (_S.RECALL, _R.NOT_RECALLED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
        (_S.EVENT_SUMMARY, _R.EVENT_UNSUMMARIZED, _DONE),
        (_S.END, _R.NOTHING_DUE, _DONE),
    ]


async def test_an_event_with_the_understanding_stage_unwired_is_still_summarized() -> None:
    """ADR-0281 §2: recall wired but understanding not, so recall is never due."""
    memory = FakeMemoryStore(now=lambda: AT)
    harness = Harness(
        memory=memory,
        recall=recall_stage(memory),
        informational_events=InformationalEventStage(FakeModelProvider("Eco.")),
    )
    await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)
    assert await _entries(harness) == [
        (_S.EVENT_SUMMARY, _R.EVENT_UNSUMMARIZED, _DONE),
        (_S.END, _R.NOTHING_DUE, _DONE),
    ]


# --- cancellation -------------------------------------------------------------------------


async def test_a_pass_cancelled_while_the_controller_runs_ends_interrupted() -> None:
    """§5: the stage it was cancelled in has no entry; the end entry says why it ended."""
    model = ControlledModel()
    harness = _harness(informational_events=InformationalEventStage(model))
    call = asyncio.create_task(harness.engine.receive(event_input(), reply=None, timeout=_BUDGET))
    await model.entered.wait()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    record = await _record(harness)
    assert record.status is ProcessingStatus.INTERRUPTED
    assert _stages(record) == [
        (_S.RECALL, _R.NOT_RECALLED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
        (_S.END, _R.INTERRUPTED, _DONE),
    ]


async def test_a_pass_cancelled_at_the_admission_barrier_ends_interrupted() -> None:
    harness = Harness()
    state = _admitted()

    async def work() -> str:
        raise AssertionError("processing never starts")

    task = harness.engine._activation_task(
        ActivationScope(state), work, seam="receive", check_output=lambda _: None
    )
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    episode = await harness.memory.get(f"activation:{state.activation_id}")
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert _stages(episode.processing_record) == [(_S.END, _R.INTERRUPTED, _DONE)]


# --- resume -------------------------------------------------------------------------------


async def test_a_resume_carries_no_stage_record() -> None:
    """§1: ``resume`` keeps its legacy path."""
    harness = _harness(tools=(confirmable(),))
    outcome = await harness.engine.converse("send the note", timeout=_BUDGET)
    assert outcome.step is not None
    assert outcome.step.confirmation is not None
    await harness.engine.resume(outcome.step.confirmation.token, approved=True, timeout=_BUDGET)
    records = [
        r.processing_record
        for r in await harness.memory.export()
        if isinstance(r, EpisodicMemory) and r.processing_record is not None
    ]
    assert [len(record.stages) for record in records] == [7, 0]
