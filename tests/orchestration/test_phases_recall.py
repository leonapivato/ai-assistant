"""Recall wired into the engine, on the phase path (ADR-0281, ADR-0309 §2:6).

``test_engine_recall`` drove these cases through the old table, which the switch lane
retired. Each case here is one of them run with the phases wired: the windows, recall
and understanding run before planning exactly as they do today, so what recall decides,
what it records and what understanding is shown stay pinned once the switch lands.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from phases_support import chat_turn, entries, event, phases_harness, processing, written
from structlog.testing import capture_logs
from test_engine import AT
from understanding_support import (
    ON_DEVICE_RECALL_THRESHOLD,
    STATED_PROPOSAL,
    Tag,
    recall_stage,
    rendered,
    understanding_stage,
)

from ai_assistant.core.types import (
    ActivationEnding,
    ChannelIdentity,
    ChannelInput,
    ControllerRule,
    ControllerStage,
    EpisodicMemory,
    InformationalEventResult,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Provenance,
    RecallOutcome,
    StageOutcome,
    TextChannelPayload,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.models.fastembed_embedder import FastEmbedEmbedder
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.recall import RecallStage
from ai_assistant.orchestration.understanding import WindowsStage
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakeStoryStore,
    FakeTraceSink,
)
from ai_assistant.testing.memories import memory as memory_record
from ai_assistant.testing.memories import remembered_support, said_support
from ai_assistant.testing.tool_calling import DEFAULT_ROUND_TEXT

if TYPE_CHECKING:
    from test_engine import Harness

    from ai_assistant.core.types import EpisodeProcessingRecord, MemoryRecord

_BUDGET: Final = timedelta(seconds=10)
_S = ControllerStage
_R = ControllerRule
_DONE = StageOutcome.DONE

#: A stored belief the ordinary turn's words recall on the canonical fake.
_BOOKED: Final = memory_record(
    "fact-booked",
    "The campsite at Pine Flat is booked for Friday.",
    said_support(when=AT, added_at=AT),
)
#: A second stored belief the same words recall.
_PERMIT: Final = memory_record(
    "fact-permit",
    "The campsite at Pine Flat needs a fire permit.",
    said_support(when=AT, added_at=AT),
)
_TURN: Final = "book the campsite at Pine Flat"


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
    return entries(record)


def _shown(model: FakeModelProvider) -> list[Tag]:
    """What the understanding stage's one call rendered as recalled memories."""
    return rendered(model.calls[0].messages).tags("Recalled memories")


def _note(model: FakeModelProvider) -> str:
    """Recalled memories' note, where it renders none (ADR-0353 §8:1)."""
    return rendered(model.calls[0].messages).section("Recalled memories")


class _Slow(FakeMemoryStore):
    """A store whose search outlasts any budget a case sets."""

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)

    async def search(self, query: str, **kwargs: Any) -> Any:
        await asyncio.sleep(10)
        return await super().search(query, **kwargs)


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


async def _no_episodes(_shared: frozenset[str]) -> tuple[EpisodicMemory, ...]:
    """An episode selector choosing none, so every stored episode is past the windows."""
    return ()


def _trail_report() -> ChannelInput:
    return ChannelInput(
        target=ChannelIdentity(channel_type="informational_event", instance_id="parks"),
        payload=TextChannelPayload(text="Bulletin 4471: NT segment status changed to C."),
    )


def _harness(
    memory: FakeMemoryStore | None = None,
    *,
    recall: RecallStage | None = None,
    understanding_model: FakeModelProvider | None = None,
    **knobs: Any,
) -> Harness:
    memory = memory or FakeMemoryStore(now=lambda: AT)
    return phases_harness(
        memory=memory,
        understanding=understanding_stage(
            model=understanding_model or FakeModelProvider(STATED_PROPOSAL)
        ),
        recall=recall or recall_stage(memory),
        **knobs,
    )


#: An understanding model whose reply is no proposal, so understanding fails.
def _unusable() -> FakeModelProvider:
    return FakeModelProvider("not a proposal")


# --- what recall decides, and what understanding is shown ---------------------------------


async def test_a_found_recall_is_recorded_and_shown_to_understanding() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(await _seeded(_BOOKED), understanding_model=model)
    await chat_turn(harness, _TURN)
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
    assert shown.get("label") == "M1"
    assert shown.text == _BOOKED.content


async def test_a_recall_that_found_nothing_is_recorded_and_said() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(understanding_model=model)
    await chat_turn(harness, _TURN)
    record = await _record(harness)
    assert record.recall is not None
    assert (record.recall.outcome, record.recall.items) == (RecallOutcome.NOTHING_FOUND, ())
    assert _note(model) == "Nothing is shown: recall found no memory for this stimulus."


async def test_a_turn_with_recall_unwired_renders_no_recalled_section() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = phases_harness(
        memory=FakeMemoryStore(now=lambda: AT), understanding=understanding_stage(model=model)
    )
    await chat_turn(harness, _TURN)
    record = await _record(harness)
    assert record.recall is None
    assert _S.RECALL not in [entry.stage for entry in record.stages]
    # ADR-0353 §8:1: the section is rendered, saying the system does not have it.
    assert _note(model).startswith("The system does not have it")


# --- §5: failure-tolerant --------------------------------------------------------------------


async def test_a_store_failure_is_tolerated_and_understanding_runs() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    failing = FakeMemoryStore(now=lambda: AT, failure="down")
    harness = _harness(recall=recall_stage(failing), understanding_model=model)
    conversation, _ = await chat_turn(harness, _TURN)
    record = await _record(harness)
    assert _entries(record)[1:4] == [
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, StageOutcome.FAILED),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
    ]
    assert _entries(record)[-1] == (_S.END, _R.NOTHING_DUE, _DONE)
    assert record.recall is not None
    assert record.recall.outcome is RecallOutcome.FAILED
    assert _note(model).startswith("It could not be read: recall failed")
    # The activation still answered.
    assert [one.text for one in await written(harness, conversation)][-1] == DEFAULT_ROUND_TEXT


async def test_recalls_own_budget_running_out_is_tolerated_and_understanding_runs() -> None:
    recall = RecallStage(
        memory=_Slow(),
        stories=FakeStoryStore(),
        threshold=0.5,
        limit=3,
        budget=timedelta(milliseconds=20),
    )
    harness = _harness(recall=recall)
    await chat_turn(harness, _TURN)
    record = await _record(harness)
    assert _entries(record)[1:4] == [
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, StageOutcome.TIMED_OUT),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
    ]
    assert record.recall is not None
    assert record.recall.outcome is RecallOutcome.TIMED_OUT


# --- events: the audience, and what is captured ----------------------------------------------


async def test_an_event_recalls_under_a_bounded_audience() -> None:
    text = "The thermostat entered eco mode at 18:00."
    episode = EpisodicMemory(
        id="episode-eco",
        content=text,
        occurred_at=AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )
    harness = _harness(await _seeded(episode), windows=WindowsStage(episodes=_no_episodes))
    _, captured = await event(harness)
    record = processing(captured)
    assert _entries(record)[:3] == [
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
    ]
    assert record.recall is not None
    assert [item.id for item in record.recall.items] == ["episode-eco"]


async def test_an_understood_event_is_captured_with_its_meaning_as_content() -> None:
    _, captured = await event(_harness())
    assert captured.content == json.loads(STATED_PROPOSAL)["understanding"]
    assert "thermostat" not in captured.content


async def test_an_event_captured_without_an_understanding_is_its_status_line() -> None:
    """ADR-0284 §7:1: no understanding, so a line of its status — and no outside words.

    The phases are wired only beside understanding, so an event captured without one is
    an event whose understanding failed: it could not finish, and its episode says so.
    """
    result, captured = await event(_harness(understanding_model=_unusable()))
    assert isinstance(result.result, InformationalEventResult)
    assert result.result.ended is ActivationEnding.COULDNT_FINISH
    record = processing(captured)
    assert record.understanding == ()
    assert record.status is not None
    assert record.reason is not None
    assert captured.content == f"status {record.status.value}, reason {record.reason.value}"
    assert "thermostat" not in captured.content


async def test_an_understood_event_is_found_by_a_later_activation_that_shares_its_matter() -> None:
    """ADR-0281 §3's acceptance test: embedded on its meaning, an event is recallable by
    what it was about; one captured without an understanding is not."""
    store = SqliteMemoryStore(
        path=":memory:", embedder=FastEmbedEmbedder(), traces_sink=FakeTraceSink(), now=lambda: AT
    )
    try:
        meaning = "The north trail at Pine Flat is closed for repairs."
        understood = phases_harness(
            memory=store,
            understanding=understanding_stage(
                model=FakeModelProvider(json.dumps({"understanding": meaning})),
            ),
        )
        await event(understood, _trail_report())
        unread = phases_harness(
            memory=store,
            understanding=understanding_stage(model=_unusable()),
        )
        await event(unread, _trail_report())
        captured = {
            episode.processing_record.understanding[-1].meaning
            if episode.processing_record.understanding
            else None: episode.id
            for episode in await store.export()
            if isinstance(episode, EpisodicMemory) and episode.processing_record is not None
        }
        recall = RecallStage(
            memory=store,
            stories=FakeStoryStore(),
            threshold=ON_DEVICE_RECALL_THRESHOLD,
            limit=3,
            budget=_BUDGET,
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


async def test_a_recalled_record_forgotten_before_understanding_is_not_rendered() -> None:
    """ADR-0282 §5: understanding renders what its fetch returned, never recall's copy;
    the rest keep their order and labels, and the missing id is recorded."""
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(await _forgetting("fact-booked"), understanding_model=model)
    with capture_logs() as logs:
        await chat_turn(harness, _TURN)
    record = await _record(harness)
    assert record.recall is not None
    assert {item.id for item in record.recall.items} == {"fact-booked", "fact-permit"}
    (shown,) = _shown(model)
    assert (shown.get("label"), shown.text) == ("M1", _PERMIT.content)
    # Understanding's fetch is the first; planning fetches what recall kept after it.
    (fetch, *_) = [log for log in logs if log["event"] == "stage_fetch"]
    assert (fetch["fetched"], fetch["missing"]) == (2, 1)


async def test_everything_recalled_forgotten_before_understanding_is_said() -> None:
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(await _forgetting("fact-booked", "fact-permit"), understanding_model=model)
    await chat_turn(harness, _TURN)
    record = await _record(harness)
    assert record.recall is not None
    assert record.recall.outcome is RecallOutcome.FOUND
    assert _note(model) == "Nothing is shown: what recall found is no longer in memory."


# --- recall searches past the windows (ADR-0282 §4) --------------------------------------


async def test_an_episode_the_window_holds_is_not_recalled() -> None:
    """The event's episode window holds the stored episode, so recall passes over it and
    keeps the belief below it; the episode renders in the window alone."""
    text = "The thermostat entered eco mode at 18:00."
    episode = EpisodicMemory(
        id="episode-eco",
        content=text,
        occurred_at=AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )
    fact = memory_record("fact-eco", text, remembered_support(when=AT, added_at=AT))
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(await _seeded(episode, fact), understanding_model=model)
    _, captured = await event(harness)
    record = processing(captured)
    assert record.recall is not None
    assert [item.id for item in record.recall.items] == ["fact-eco"]
    (shown,) = _shown(model)
    assert (shown.get("label"), shown.text) == ("M1", text)
