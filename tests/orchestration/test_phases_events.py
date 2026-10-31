"""An event ``receive`` admits, run by the phases: its lifetime and its record (ADR-0313 §4).

``test_channel_receiver``, ``test_activation_channels`` and ``test_engine_stage_record``
drove these cases through the old event path, whose summary stage retired at the cutover
(ADR-0309 §5:5). On the phases an event is one activation whose place takes no message,
and one that cannot finish returns *couldn't finish* rather than raising (ADR-0313
§4:5); what it shares with today's path is pinned here: a caller's cancellation and the
deadline each wait for the model call to clean up, the drain waits for an admitted event
and refuses new work, overlapping events keep their own identity, a capture that cannot
be recorded degrades without losing the result, and a failure or a cancellation records
the episode once, with no private diagnostic in it.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import pytest
from channel_receiver_contract import event_input
from phases_support import SETTLE, entries, phases_harness, processing
from test_engine import AT
from understanding_support import recall_stage, rendered, understanding_stage

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import (
    ActivationEnding,
    ChannelContext,
    ChannelContextItem,
    ControllerRule,
    ControllerStage,
    EpisodicMemory,
    InformationalEventResult,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedTextInput,
    RoundResponse,
    StageOutcome,
    TextChannelPayload,
)
from ai_assistant.testing import FakeMemoryStore, FakeModelProvider, FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from test_engine import Harness

    from ai_assistant.core.types import ChannelResult, Message, OfferedTool, PlanningExchange

_BUDGET: Final = timedelta(seconds=10)
_S = ControllerStage
_R = ControllerRule
_DONE = StageOutcome.DONE


class _Controlled(FakeToolCallingCompleter):
    """A planning barrier with observable cancellation cleanup."""

    def __init__(self, *, arrivals: int = 1) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cleaned = asyncio.Event()
        self.error: BaseException | None = None
        self._arrivals = arrivals
        self._arrived = 0

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        self._arrived += 1
        if self._arrived >= self._arrivals:
            # Set once ``arrivals`` calls are all held at the barrier.
            self.entered.set()
        try:
            await self.release.wait()
            if self.error is not None:
                raise self.error
            return await super().respond(exchange, tools, model=model)
        finally:
            self.cleaned.set()


def _ended(result: ChannelResult) -> ActivationEnding:
    assert isinstance(result.result, InformationalEventResult)
    return result.result.ended


async def _only(harness: Harness) -> EpisodicMemory:
    (episode,) = await harness.memory.export()
    assert isinstance(episode, EpisodicMemory)
    return episode


async def test_a_caller_cancellation_propagates_after_cleanup_and_ends_interrupted() -> None:
    """The stage it was cancelled in has no entry; the end entry says why it ended."""
    completer = _Controlled()
    memory = FakeMemoryStore(now=lambda: AT)
    harness = phases_harness(completer, memory=memory, recall=recall_stage(memory))
    task = asyncio.create_task(harness.engine.receive(event_input(), reply=None, timeout=_BUDGET))
    await completer.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert completer.cleaned.is_set()
    record = processing(await _only(harness))
    assert record.status is ProcessingStatus.INTERRUPTED
    assert entries(record)[:3] == [
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
    ]
    assert entries(record)[-1] == (_S.END, _R.INTERRUPTED, _DONE)
    assert _S.PLANNING not in [stage for stage, _, _ in entries(record)]
    await harness.engine.aclose()


async def test_the_deadline_cancels_and_awaits_the_model_calls_cleanup() -> None:
    """The event's budget runs out mid-call: it could not finish, once the call cleaned up.

    The budget is long enough for the stages before planning to finish over the fakes
    however loaded the machine is, and the planning call never answers, so the deadline
    passes while that call is held. The call is checked as reached before it is checked
    as cleaned up.
    """
    completer = _Controlled()
    harness = phases_harness(completer)
    receiving = asyncio.ensure_future(
        harness.engine.receive(event_input(), reply=None, timeout=timedelta(seconds=1))
    )
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    assert not completer.cleaned.is_set()
    result = await asyncio.wait_for(receiving, SETTLE)
    assert _ended(result) is ActivationEnding.COULDNT_FINISH
    assert completer.cleaned.is_set()


@pytest.mark.parametrize("cancelled", [False, True])
async def test_a_failure_or_a_cancellation_records_once_after_the_calls_cleanup(
    cancelled: bool,
) -> None:
    """ADR-0286 §2: stored open from admission; frozen once, and no private diagnostic."""
    completer = _Controlled()
    harness = phases_harness(completer)
    task = asyncio.create_task(harness.engine.receive(event_input(), reply=None, timeout=_BUDGET))
    await completer.entered.wait()
    opened = await _only(harness)
    assert processing(opened).is_open
    if cancelled:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        completer.error = ModelError("private diagnostic")
        completer.release.set()
        assert _ended(await task) is ActivationEnding.COULDNT_FINISH
    assert completer.cleaned.is_set()
    episode = await _only(harness)
    assert processing(episode).status is (
        ProcessingStatus.INTERRUPTED if cancelled else ProcessingStatus.FAILED
    )
    assert episode.outcome is None
    assert "private diagnostic" not in episode.model_dump_json()


async def test_the_drain_waits_for_an_admitted_event_and_refuses_new_work() -> None:
    completer = _Controlled()
    harness = phases_harness(completer)
    task = asyncio.create_task(harness.engine.receive(event_input(), reply=None, timeout=_BUDGET))
    await completer.entered.wait()
    draining = asyncio.create_task(harness.engine.aclose())
    await asyncio.sleep(0)
    assert not draining.done()
    with pytest.raises(RuntimeError, match="shut"):
        await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)
    completer.release.set()
    assert _ended(await task) is ActivationEnding.DONE
    await draining


async def test_overlapping_events_keep_separate_identity_context_and_receipts() -> None:
    """Two events in flight at once: each is processed over its own input and context.

    Both are held in planning together before either is released, so what each stage
    was handed is read while the other runs, not after it ended.
    """

    def meaning_of(messages: Sequence[Message]) -> str:
        """Understanding's reading names the input it was handed, so it can be traced."""
        text = rendered(messages).stimulus
        return json.dumps({"understanding": f"It reported {text}."})

    completer = _Controlled(arrivals=2)
    understood = FakeModelProvider(meaning_of)
    harness = phases_harness(completer, understanding=understanding_stage(model=understood))

    async def receive(text: str) -> ChannelResult:
        supplied = event_input().model_copy(
            update={
                "payload": TextChannelPayload(text=text),
                "context": ChannelContext(history=(ChannelContextItem(text=text),)),
            }
        )
        return await harness.engine.receive(supplied, reply=None, timeout=_BUDGET)

    first = asyncio.create_task(receive("first"))
    second = asyncio.create_task(receive("second"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    # Both are in planning at once, and each was understood over its own input and
    # its own supplied history, never the other's.
    assert len(completer.calls) == 0  # neither round has been answered yet
    seen = sorted(
        (sent.stimulus, [item.text for item in sent.tags("Stimulus origin knowledge")])
        for sent in (rendered(call.messages) for call in understood.calls)
    )
    assert seen == [("first", ["first"]), ("second", ["second"])]
    completer.release.set()
    results = await asyncio.gather(first, second)
    assert len({result.capture.activation_id for result in results}) == 2
    # And each planning round was handed the understanding of its own input alone.
    planned = sorted(
        json.loads(call.exchange.briefing)["understanding"]["meaning"] for call in completer.calls
    )
    assert planned == ["It reported first.", "It reported second."]
    for result, expected in zip(results, ("first", "second"), strict=True):
        assert result.capture.episode_id is not None
        episode = await harness.memory.get(result.capture.episode_id)
        assert isinstance(episode, EpisodicMemory)
        trigger = processing(episode).trigger
        assert isinstance(trigger, RecordedChannelTrigger)
        assert isinstance(trigger.payload, RecordedTextInput)
        assert trigger.payload.text == trigger.context.history[0].text == expected


async def test_invalid_activation_metadata_degrades_capture_without_losing_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = phases_harness(FakeToolCallingCompleter(RoundResponse(text="Eco mode noted.")))
    monkeypatch.setattr(harness.engine, "_activation_id_factory", lambda: "not-a-uuid")
    result = await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)
    assert _ended(result) is ActivationEnding.DONE
    assert result.capture.state == "degraded"
    assert result.capture.activation_id is None
    assert result.capture.episode_id is None
    assert await harness.memory.export() == []
