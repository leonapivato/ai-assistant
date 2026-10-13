"""How an activation ends where a stage before planning fails or runs out of time.

``test_engine_stage_record``, ``test_engine_understanding``, ``test_engine_recall`` and
``test_engine_windows`` drive these cases through ``converse``, which the switch refuses
(ADR-0309 §2:6, §5:1). The stages they hold are the same ones on the phases: the
windows, recall and understanding run first on every activation (ADR-0309 §3's rows 2 to
4), and a stage that fails or outlasts the activation's deadline ends it on the
controller's fixed default (ADR-0280 §5). Each case here is one of theirs, on an
activation the chat's reader starts: the record ends on the stage, its reason is the
row the stage's class takes, planning is never asked, and the conversation is told the
activation could not finish (ADR-0307 §3).
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from phases_support import (
    chat_turn,
    entries,
    phases_harness,
    processing,
    written,
)
from structlog.testing import capture_logs
from test_engine import AT
from understanding_support import (
    EPISODE_LIMIT,
    STATED_PROPOSAL,
    recall_stage,
    understanding_stage,
)

from ai_assistant.core.errors import MemoryStoreError, ModelError, ModelTimeoutError
from ai_assistant.core.types import (
    ControllerRule,
    ControllerStage,
    EpisodicMemory,
    MessageAuthor,
    ProcessingReason,
    ProcessingStatus,
    RecallOutcome,
    StageOutcome,
    UnderstandingOmission,
)
from ai_assistant.orchestration.chat import COULDNT_FINISH
from ai_assistant.orchestration.understanding import RecentEpisodes, WindowsStage
from ai_assistant.testing import FakeMemoryStore, FakeModelProvider, FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from test_engine import Harness

    from ai_assistant.core.types import Message
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.understanding import ChannelWindow, Windows

_S = ControllerStage
_R = ControllerRule
_DONE = StageOutcome.DONE

#: A budget a stalled stage outlasts and a prompt one does not.
_SHORT = timedelta(milliseconds=50)


def _built(
    model: FakeModelProvider | None = None,
    *,
    budget: timedelta | None = None,
    **knobs: Any,
) -> tuple[Harness, FakeToolCallingCompleter]:
    """The phases over ``model``'s understanding, the activation's budget ``budget``."""
    completer = FakeToolCallingCompleter()
    harness = phases_harness(
        completer,
        understanding=understanding_stage(
            model=model if model is not None else FakeModelProvider(STATED_PROPOSAL)
        ),
        **knobs,
    )
    if budget is not None:
        # The reader has no caller to hand it a budget (ADR-0029 §4); the composition
        # root sets it, and a case here shortens it.
        harness.engine._chat_turn_budget = budget
    return harness, completer


async def _ended(harness: Harness) -> EpisodicMemory:
    """One message's activation, its failure's log captured, once its episode froze."""
    with capture_logs():
        _, episode = await chat_turn(harness, "book the campsite")
    return episode


async def _told_it_could_not_finish(harness: Harness, conversation_of: EpisodicMemory) -> None:
    trigger = processing(conversation_of).trigger
    conversation = trigger.channel.instance_id  # type: ignore[union-attr]  # a conversation's trigger
    replies = [
        one.text
        for one in await written(harness, conversation)
        if one.author is MessageAuthor.ASSISTANT
    ]
    assert replies == [COULDNT_FINISH]


class _Raising(FakeModelProvider):
    def __init__(self, error: Exception) -> None:
        super().__init__(STATED_PROPOSAL)
        self._error = error

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        raise self._error


class _Stalled(FakeModelProvider):
    """A provider that answers only after any budget here has passed."""

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        await asyncio.sleep(10)
        return await super().complete(messages, model=model)


class _Blocking(FakeModelProvider):
    """A provider that answers without yielding, once the budget is spent."""

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        time.sleep(0.06)  # noqa: ASYNC251 — the point: a completion that never yields
        return await super().complete(messages, model=model)


# --- understanding (ADR-0276 §5, §6) -----------------------------------------------------


async def test_an_understanding_that_fails_ends_the_activation_on_its_stage() -> None:
    """§6: no substitute and no planning; the reason is its own terminal row."""
    harness, completer = _built(FakeModelProvider("not json"))

    episode = await _ended(harness)

    record = processing(episode)
    assert entries(record) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, StageOutcome.FAILED),
        (_S.END, _R.STAGE_FAILED, _DONE),
    ]
    assert (record.status, record.reason) == (
        ProcessingStatus.FAILED,
        ProcessingReason.UNDERSTANDING_FAILED,
    )
    assert record.understanding == ()
    assert record.understanding_omitted is UnderstandingOmission.FAILED
    assert completer.calls == [], "planning is never asked"
    await _told_it_could_not_finish(harness, episode)


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
    harness, completer = _built(_Raising(error))

    episode = await _ended(harness)

    record = processing(episode)
    assert record.reason is reason
    assert record.understanding_omitted is UnderstandingOmission.FAILED
    assert str(error) not in record.model_dump_json()
    assert completer.calls == []


async def test_a_deadline_expiring_inside_understanding_is_a_classified_timeout() -> None:
    """§5: the stage runs inside the activation's deadline; §6: ``failed / timeout``."""
    harness, completer = _built(_Stalled(STATED_PROPOSAL), budget=_SHORT)

    episode = await _ended(harness)

    record = processing(episode)
    assert (record.status, record.reason) == (ProcessingStatus.FAILED, ProcessingReason.TIMEOUT)
    assert entries(record)[-2:] == [
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]
    assert record.understanding_omitted is UnderstandingOmission.FAILED
    assert completer.calls == []
    await _told_it_could_not_finish(harness, episode)


async def test_a_stage_that_crosses_the_deadline_without_yielding_is_still_timed_out() -> None:
    """§5: a valid understanding that returns past the deadline is the timeout, unrecorded.

    The completion never yields, so no timer fires inside the stage: only the check of
    the deadline once it returns sees it was crossed.
    """
    harness, completer = _built(_Blocking(STATED_PROPOSAL), budget=_SHORT)

    episode = await _ended(harness)

    record = processing(episode)
    assert record.reason is ProcessingReason.TIMEOUT
    assert record.understanding == ()
    assert record.understanding_omitted is UnderstandingOmission.FAILED
    assert completer.calls == []


async def test_a_late_unparseable_output_is_the_timeout_and_earns_no_repair() -> None:
    model = _Blocking("not json")
    harness, _ = _built(model, budget=_SHORT)

    episode = await _ended(harness)

    assert len(model.calls) == 1
    record = processing(episode)
    assert record.reason is ProcessingReason.TIMEOUT
    assert record.understanding_omitted is UnderstandingOmission.FAILED


# --- the windows and recall (ADR-0282 §3, ADR-0281) ---------------------------------------


async def test_an_episode_selection_outlasting_the_deadline_times_the_windows_stage_out() -> None:
    """§5, ADR-0282 §3: expiry while the windows stage awaits its episode selector, before
    recall or the understanding model runs.

    ``test_engine_stage_record`` held this over ``converse``'s history read. The reader
    hands the transcript in, so the read the windows stage still awaits inside the
    activation's deadline is the episode selector's.
    """
    model = FakeModelProvider(STATED_PROPOSAL)

    async def hangs(shared: frozenset[str]) -> tuple[EpisodicMemory, ...]:
        await asyncio.sleep(10)
        return ()

    harness, completer = _built(model, windows=WindowsStage(episodes=hangs), budget=_SHORT)

    episode = await _ended(harness)

    assert model.calls == []
    assert entries(processing(episode)) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]
    assert completer.calls == []
    await _told_it_could_not_finish(harness, episode)


class _UnyieldingWindows(WindowsStage):
    """A windows stage that holds the loop past a short deadline, then returns."""

    async def assemble(
        self, channel: ChannelWindow, *, audience: TurnSupply, episodes: bool
    ) -> Windows:
        time.sleep(0.06)  # noqa: ASYNC251 — the point: no timer can fire while it runs
        return await super().assemble(channel, audience=audience, episodes=episodes)


async def test_windows_that_cross_the_deadline_without_yielding_are_the_expiry() -> None:
    """ADR-0280 §5: assembly that returned past the deadline is the stage's timeout."""
    memory = FakeMemoryStore(now=lambda: AT)
    windows = _UnyieldingWindows(episodes=RecentEpisodes(memory=memory, limit=EPISODE_LIMIT))
    harness, completer = _built(memory=memory, windows=windows, budget=_SHORT)

    episode = await _ended(harness)

    assert entries(processing(episode)) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]
    assert completer.calls == []


class _SlowSearch(FakeMemoryStore):
    """A store whose search outlasts any budget a case sets."""

    async def search(self, query: str, **kwargs: Any) -> Any:
        await asyncio.sleep(10)
        return await super().search(query, **kwargs)


async def test_the_deadline_passing_during_recall_ends_the_activation() -> None:
    """The activation's deadline, not recall's own budget: the activation ends there."""
    memory = _SlowSearch(now=lambda: AT)
    harness, completer = _built(memory=memory, recall=recall_stage(memory), budget=_SHORT)

    episode = await _ended(harness)

    record = processing(episode)
    assert entries(record) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]
    assert completer.calls == []
    await _told_it_could_not_finish(harness, episode)


class _UnyieldingSearch(FakeMemoryStore):
    """A store whose search holds the loop past a short deadline, then answers or fails."""

    def __init__(self, *, fails: bool) -> None:
        super().__init__(now=lambda: AT)
        self._fails = fails

    async def search(self, query: str, **kwargs: Any) -> Any:
        time.sleep(0.06)  # noqa: ASYNC251 — the point: no timer can fire while it runs
        if self._fails:
            msg = "down"
            raise MemoryStoreError(msg)
        return await super().search(query, **kwargs)


@pytest.mark.parametrize("fails", [False, True], ids=["returns", "fails"])
async def test_recall_that_crosses_the_deadline_without_yielding_is_the_expiry(
    fails: bool,
) -> None:
    """ADR-0281 §5, ADR-0280 §5: whatever recall returned past the deadline, the
    activation ends timed out there, and what recall produced is not recorded."""
    harness, completer = _built(recall=recall_stage(_UnyieldingSearch(fails=fails)), budget=_SHORT)

    episode = await _ended(harness)

    record = processing(episode)
    assert entries(record) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]
    assert record.recall is not None
    assert (record.recall.outcome, record.recall.items) == (RecallOutcome.TIMED_OUT, ())
    assert completer.calls == []
