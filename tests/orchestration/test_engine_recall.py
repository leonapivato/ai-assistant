"""Recall wired into the engine: its stage, its record and what it shows (ADR-0281).

Each case builds the engine as the composition root does, with recall and understanding
both wired, and asserts what the one captured episode's processing record carries — the
stage entries, the recall result — and what the understanding stage was shown. The
stage alone is in ``test_recall.py``, and the rules and the controller in
``test_controller.py``.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from channel_receiver_contract import event_input
from structlog.testing import capture_logs
from test_engine import AT, Harness, NoStepPlanner
from understanding_support import (
    ON_DEVICE_RECALL_THRESHOLD,
    STATED_PROPOSAL,
    recall_stage,
    understanding_stage,
)

from ai_assistant.core.errors import (
    ChannelProcessingTimeoutError,
    MemoryStoreError,
    ModelTimeoutError,
)
from ai_assistant.core.types import (
    ChannelIdentity,
    ChannelInput,
    ControllerRule,
    ControllerStage,
    EpisodicMemory,
    MemoryKind,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    NewConversation,
    Provenance,
    RecallOutcome,
    RoutableOperation,
    SemanticMemory,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenReply,
    StageOutcome,
    TextChannelPayload,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.models.fastembed_embedder import FastEmbedEmbedder
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.informational_events import InformationalEventStage
from ai_assistant.orchestration.recall import RecallStage
from ai_assistant.orchestration.routing import RoutingStage
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakeRoutingRecorder,
    FakeStreamingCompleter,
    FakeTraceSink,
)
from ai_assistant.testing.speech import DEFAULT_TRANSCRIPT

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import EpisodeProcessingRecord, MemoryRecord, Message

_BUDGET: Final = timedelta(seconds=10)
_S = ControllerStage
_R = ControllerRule
_DONE = StageOutcome.DONE

#: A stored belief the ordinary turn's words recall on the canonical fake.
_BOOKED: Final = SemanticMemory(
    id="fact-booked",
    content="The campsite at Pine Flat is booked for Friday.",
    fact="The campsite at Pine Flat is booked for Friday.",
    provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
)
_TURN: Final = "book the campsite at Pine Flat"


def _harness(
    memory: FakeMemoryStore | None = None,
    *,
    recall: RecallStage | None = None,
    understanding_model: FakeModelProvider | None = None,
    **knobs: Any,
) -> Harness:
    memory = memory or FakeMemoryStore(now=lambda: AT)
    knobs.setdefault("planner", NoStepPlanner())
    knobs.setdefault(
        "composing",
        ComposingStage(model=FakeModelProvider("Yes."), streaming=FakeStreamingCompleter()),
    )
    knobs.setdefault(
        "informational_events", InformationalEventStage(FakeModelProvider("Summarized."))
    )
    return Harness(
        memory=memory,
        understanding=understanding_stage(
            model=understanding_model or FakeModelProvider(STATED_PROPOSAL)
        ),
        recall=recall or recall_stage(memory),
        **knobs,
    )


async def _seeded(*records: MemoryRecord) -> FakeMemoryStore:
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.write_atomic(
        [MemoryWrite(record=record, mode=MemoryWriteMode.INSERT_IF_ABSENT) for record in records]
    )
    return memory


async def _record(harness: Harness) -> EpisodeProcessingRecord:
    """The one captured activation's processing record."""
    (record,) = [
        r.processing_record
        for r in await harness.memory.export()
        if isinstance(r, EpisodicMemory) and r.processing_record is not None
    ]
    return record


def _entries(record: EpisodeProcessingRecord) -> list[tuple[ControllerStage, ControllerRule, Any]]:
    assert all(entry.due is not ControllerRule.STAGE_REPEATED for entry in record.stages)
    return [(entry.stage, entry.due, entry.outcome) for entry in record.stages]


def _shown(model: FakeModelProvider) -> Any:
    """What the understanding stage's one call rendered as its recalled section."""
    return json.loads(model.calls[0].messages[1].content)["recalled"]


def _speech() -> ChannelInput:
    return ChannelInput(
        target=NewConversation(),
        payload=SpeechChannelPayload(
            audio=SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)
        ),
    )


class _Slow(FakeMemoryStore):
    """A store whose search outlasts any budget a case sets."""

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.searches = 0

    async def search(self, query: str, **kwargs: Any) -> Any:
        self.searches += 1
        await asyncio.sleep(10)
        return await super().search(query, **kwargs)


# --- what recall decides, and what understanding is shown ---------------------------------


async def test_a_found_recall_is_recorded_and_shown_to_understanding() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(await _seeded(_BOOKED), understanding_model=model)
    await harness.engine.converse(_TURN, timeout=_BUDGET)
    record = await _record(harness)
    assert _entries(record)[:4] == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
    ]
    assert record.recall is not None
    assert record.recall.outcome is RecallOutcome.FOUND
    assert [item.id for item in record.recall.items] == ["fact-booked"]
    (shown,) = _shown(model)
    assert shown["label"] == "M1"
    assert shown["fact"] == _BOOKED.fact


async def test_a_recall_that_found_nothing_is_recorded_and_said() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(understanding_model=model)
    await harness.engine.converse(_TURN, timeout=_BUDGET)
    record = await _record(harness)
    assert record.recall is not None
    assert (record.recall.outcome, record.recall.items) == (RecallOutcome.NOTHING_FOUND, ())
    assert _shown(model) == "missing: nothing was recalled for this input"


async def test_a_turn_with_recall_unwired_renders_no_recalled_section() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    memory = FakeMemoryStore(now=lambda: AT)
    harness = Harness(
        memory=memory,
        planner=NoStepPlanner(),
        understanding=understanding_stage(model=model),
        composing=ComposingStage(
            model=FakeModelProvider("Yes."), streaming=FakeStreamingCompleter()
        ),
    )
    await harness.engine.converse(_TURN, timeout=_BUDGET)
    record = await _record(harness)
    assert record.recall is None
    assert _S.RECALL not in [entry.stage for entry in record.stages]
    assert "recalled" not in json.loads(model.calls[0].messages[1].content)


# --- §5: failure-tolerant, and the two deadlines -------------------------------------------


async def test_a_store_failure_is_tolerated_and_understanding_runs() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    failing = FakeMemoryStore(now=lambda: AT, failure="down")
    harness = _harness(recall=recall_stage(failing), understanding_model=model)
    outcome = await harness.engine.converse(_TURN, timeout=_BUDGET)
    assert outcome.reply == "Yes."
    record = await _record(harness)
    assert _entries(record)[1:4] == [
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, StageOutcome.FAILED),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
    ]
    assert _entries(record)[-1] == (_S.END, _R.NOTHING_DUE, _DONE)
    assert record.recall is not None
    assert record.recall.outcome is RecallOutcome.FAILED
    assert _shown(model) == "missing: recall failed, so no memories are shown"


async def test_recalls_own_budget_running_out_is_tolerated_and_understanding_runs() -> None:
    recall = RecallStage(memory=_Slow(), threshold=0.5, limit=3, budget=timedelta(milliseconds=20))
    harness = _harness(recall=recall)
    await harness.engine.converse(_TURN, timeout=_BUDGET)
    record = await _record(harness)
    assert _entries(record)[1:4] == [
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, StageOutcome.TIMED_OUT),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
    ]
    assert record.recall is not None
    assert record.recall.outcome is RecallOutcome.TIMED_OUT


async def test_the_pass_deadline_passing_during_recall_ends_the_turn() -> None:
    """The activation's deadline, not recall's budget: the pass ends and re-raises."""
    harness = _harness(recall=recall_stage(_Slow()))
    with pytest.raises(ModelTimeoutError, match="during recall"):
        await harness.engine.converse(_TURN, timeout=timedelta(milliseconds=50))
    record = await _record(harness)
    assert _entries(record) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]
    assert record.recall is not None
    assert record.recall.outcome is RecallOutcome.TIMED_OUT


async def test_the_pass_deadline_passing_during_recall_ends_an_event() -> None:
    harness = _harness(recall=recall_stage(_Slow()))
    with pytest.raises(ChannelProcessingTimeoutError):
        await harness.engine.receive(event_input(), reply=None, timeout=timedelta(milliseconds=50))
    record = await _record(harness)
    assert _entries(record) == [
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]


class _Unyielding(FakeMemoryStore):
    """A store whose search holds the loop past a short deadline, then answers or fails."""

    def __init__(self, *records: MemoryRecord, fails: bool = False) -> None:
        super().__init__(now=lambda: AT)
        self._fails = fails

    async def search(self, query: str, **kwargs: Any) -> Any:
        time.sleep(0.05)  # noqa: ASYNC251 — the point: no timer can fire while it runs
        if self._fails:
            msg = "down"
            raise MemoryStoreError(msg)
        return await super().search(query, **kwargs)


@pytest.mark.parametrize("fails", [False, True], ids=["returns", "fails"])
async def test_recall_that_crosses_the_deadline_without_yielding_is_the_expiry(
    fails: bool,
) -> None:
    """§5: whatever recall returned past the deadline, the pass ends timed out, and what
    it produced is not recorded."""
    harness = _harness(recall=recall_stage(_Unyielding(fails=fails)))
    with pytest.raises(ModelTimeoutError, match="during recall"):
        await harness.engine.converse(_TURN, timeout=timedelta(milliseconds=20))
    record = await _record(harness)
    assert _entries(record) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]
    assert record.recall is not None
    assert (record.recall.outcome, record.recall.items) == (RecallOutcome.TIMED_OUT, ())


class _SlowDecline(FakeModelProvider):
    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        await asyncio.sleep(0.1)
        return await super().complete(messages, model=model)


async def test_a_pass_out_of_time_before_recall_searches_nothing() -> None:
    """Routing spent the budget, so the windows stage, due first, is not entered: recall
    searches nothing and makes no decision (ADR-0282 §3)."""
    slow = _Slow()
    router = RoutingStage(
        model=_SlowDecline(json.dumps({"operation": "none"})), recorder=FakeRoutingRecorder()
    )
    harness = _harness(recall=recall_stage(slow), routing=router)
    with pytest.raises(ModelTimeoutError, match="assembling the windows"):
        await harness.engine.converse(_TURN, timeout=timedelta(milliseconds=20))
    record = await _record(harness)
    assert _entries(record) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.ROUTING, _R.ROUTE_UNCHECKED, _DONE),
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]
    assert slow.searches == 0
    assert record.recall is None


# --- which passes recall, and under which audience ------------------------------------------


async def test_a_routed_turn_makes_no_recall_decision() -> None:
    reply = json.dumps({"operation": RoutableOperation.FORGET.value, "query": "the campsite"})
    router = RoutingStage(model=FakeModelProvider(reply), recorder=FakeRoutingRecorder())
    harness = _harness(await _seeded(_BOOKED), routing=router)
    await harness.engine.converse("forget the campsite", timeout=_BUDGET)
    record = await _record(harness)
    assert record.recall is None


async def test_a_spoken_turn_recalls_no_episode() -> None:
    """§4: the spoken operation's supply is of unbounded audience, so recall asks for
    semantic records alone — an episode the audience predicate would admit included."""
    words = DEFAULT_TRANSCRIPT
    episode = EpisodicMemory(
        id="episode-spoken",
        content=words,
        occurred_at=AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )
    fact = SemanticMemory(
        id="fact-spoken",
        content=words,
        fact=words,
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
    )
    harness = _harness(await _seeded(episode, fact))
    await harness.engine.receive(
        _speech(), reply=SpokenReply(plays=(SpokenAudioFormat.MP4,)), timeout=_BUDGET
    )
    record = await _record(harness)
    assert record.recall is not None
    assert [(item.kind, item.id) for item in record.recall.items] == [
        (MemoryKind.SEMANTIC, "fact-spoken")
    ]


async def test_an_event_recalls_under_a_bounded_audience() -> None:
    text = "The thermostat entered eco mode at 18:00."
    episode = EpisodicMemory(
        id="episode-eco",
        content=text,
        occurred_at=AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )
    harness = _harness(await _seeded(episode))
    await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)
    records = [
        r.processing_record
        for r in await harness.memory.export()
        if isinstance(r, EpisodicMemory) and r.id != "episode-eco" and r.processing_record
    ]
    (record,) = records
    assert _entries(record)[:3] == [
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
    ]
    assert record.recall is not None
    assert [item.id for item in record.recall.items] == ["episode-eco"]


# --- §3: an inspection-only episode is embedded on its understanding ------------------------


async def test_an_understood_event_is_captured_with_its_meaning_as_content() -> None:
    harness = _harness()
    await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)
    (episode,) = [r for r in await harness.memory.export() if isinstance(r, EpisodicMemory)]
    assert episode.content == json.loads(STATED_PROPOSAL)["meaning"]
    assert "thermostat" not in episode.content


async def test_an_event_captured_without_an_understanding_keeps_the_constant() -> None:
    harness = Harness(informational_events=InformationalEventStage(FakeModelProvider("Eco.")))
    await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)
    (episode,) = [r for r in await harness.memory.export() if isinstance(r, EpisodicMemory)]
    assert episode.content == "Recorded activation; inspect its processing record."


# --- §3: capture to recall, over the real store and the real embedder ------------------------


def _trail_report() -> ChannelInput:
    return ChannelInput(
        target=ChannelIdentity(channel_type="informational_event", instance_id="parks"),
        payload=TextChannelPayload(text="Bulletin 4471: NT segment status changed to C."),
    )


async def test_an_understood_event_is_found_by_a_later_activation_that_shares_its_matter() -> None:
    """ADR-0281 §3's acceptance test: embedded on its meaning, an event is recallable by
    what it was about; one captured without an understanding is not."""
    store = SqliteMemoryStore(
        path=":memory:", embedder=FastEmbedEmbedder(), traces_sink=FakeTraceSink(), now=lambda: AT
    )
    try:
        meaning = "The north trail at Pine Flat is closed for repairs."
        understood = Harness(
            memory=store,  # type: ignore[arg-type]  # the harness only hands its store on
            understanding=understanding_stage(
                model=FakeModelProvider(
                    json.dumps({"meaning": meaning, "meaning_ground": "stated"})
                ),
            ),
            informational_events=InformationalEventStage(FakeModelProvider("Trail closed.")),
        )
        await understood.engine.receive(_trail_report(), reply=None, timeout=_BUDGET)
        unread = Harness(
            memory=store,  # type: ignore[arg-type]  # as above
            informational_events=InformationalEventStage(FakeModelProvider("Trail closed.")),
        )
        await unread.engine.receive(_trail_report(), reply=None, timeout=_BUDGET)
        captured = {
            episode.processing_record.understanding[-1].meaning
            if episode.processing_record.understanding
            else None: episode.id
            for episode in await store.export()
            if isinstance(episode, EpisodicMemory) and episode.processing_record is not None
        }
        recall = RecallStage(
            memory=store, threshold=ON_DEVICE_RECALL_THRESHOLD, limit=3, budget=_BUDGET
        )
        later = await recall.recall(
            "Is the north trail at Pine Flat open again?",
            audience=BoundedAudienceSupply(speakable_attested_sources=frozenset()),
            deadline=asyncio.get_running_loop().time() + 30,
        )
        found = [item.id for item in later.result.items]
        assert captured[meaning] in found
        assert captured[None] not in found
    finally:
        store.close()


# --- understanding fetches what recall kept (ADR-0282 §5) ---------------------------------

#: A second stored belief the ordinary turn's words recall on the canonical fake.
_PERMIT: Final = SemanticMemory(
    id="fact-permit",
    content="The campsite at Pine Flat needs a fire permit.",
    fact="The campsite at Pine Flat needs a fire permit.",
    provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
)


class _ForgetsAfterSearch(FakeMemoryStore):
    """A store that deletes the named records once a search has returned them."""

    def __init__(self, *forgotten: str) -> None:
        super().__init__(now=lambda: AT)
        self._forgotten = forgotten

    async def search(self, query: str, **kwargs: Any) -> Any:
        found = await super().search(query, **kwargs)
        for record_id in self._forgotten:
            await self.delete(record_id)
        return found


async def _forgetting(*forgotten: str) -> _ForgetsAfterSearch:
    memory = _ForgetsAfterSearch(*forgotten)
    await memory.write_atomic(
        [
            MemoryWrite(record=record, mode=MemoryWriteMode.INSERT_IF_ABSENT)
            for record in (_BOOKED, _PERMIT)
        ]
    )
    return memory


async def test_a_recalled_record_forgotten_before_understanding_is_not_rendered() -> None:
    """ADR-0282 §5: understanding renders what its fetch returned, never recall's copy;
    the rest keep their order and labels, and the missing id is recorded."""
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(await _forgetting("fact-booked"), understanding_model=model)
    with capture_logs() as logs:
        await harness.engine.converse(_TURN, timeout=_BUDGET)
    record = await _record(harness)
    assert record.recall is not None
    assert {item.id for item in record.recall.items} == {"fact-booked", "fact-permit"}
    (shown,) = _shown(model)
    assert (shown["label"], shown["fact"]) == ("M1", _PERMIT.fact)
    (fetch,) = [log for log in logs if log["event"] == "stage_fetch"]
    assert (fetch["fetched"], fetch["missing"]) == (2, 1)


async def test_everything_recalled_forgotten_before_understanding_is_said() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(await _forgetting("fact-booked", "fact-permit"), understanding_model=model)
    await harness.engine.converse(_TURN, timeout=_BUDGET)
    record = await _record(harness)
    assert record.recall is not None
    assert record.recall.outcome is RecallOutcome.FOUND
    assert _shown(model) == "missing: what was recalled is no longer in memory"
