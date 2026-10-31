"""The engine's lifetime and its conversations, with the phases running its work (ADR-0309 §2:6).

``test_engine`` drives these cases with a ``converse`` call as the work in flight, or as
the turn that records an episode. ``converse`` retires at the cutover (ADR-0309 §5:1),
and every conversational activation is then one the chat's reader starts and the phases
run. Each case here is one of today's with a chat activation in its place: the drain
waits for it, cancels it past its budget and closes nothing until it has unwound; every
closer runs, in order; the conversations a person chooses from, forgets and deletes; and
the one trace an activation emits.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from channel_episodes import channel_ids
from phases_support import (
    PHONE,
    SETTLE,
    Gated,
    NeverFinishing,
    answered,
    chat_turn,
    open_conversation,
    phases_harness,
    say,
)

from ai_assistant.core.device_context import current_requesting_device, serving_device
from ai_assistant.core.types import (
    HUB_REQUESTING_DEVICE,
    RequestingDevice,
    TraceKind,
    TraceOutcome,
    TraceRef,
)
from ai_assistant.orchestration.engine import DrainPhase
from ai_assistant.testing import FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from test_engine import Harness

    from ai_assistant.core.types import OfferedTool, PlanningExchange, RoundResponse


async def _running(harness: Harness, entered: asyncio.Event) -> str:
    """Start one chat activation and wait until its planning call has begun."""
    conversation = await open_conversation(harness)
    await say(harness, conversation, "hello")
    await asyncio.wait_for(entered.wait(), SETTLE)
    return conversation


# --- the drain (ADR-0042 §2, ADR-0083) --------------------------------------------------


async def test_shutdown_drains_in_flight_work_before_closing() -> None:
    """Closing waits for a running activation to quiesce before it closes resources."""
    completer = Gated()
    closed = asyncio.Event()
    closed_while_inflight = False

    async def close() -> None:
        nonlocal closed_while_inflight
        closed_while_inflight = not completer.release.is_set()
        closed.set()

    harness = phases_harness(completer, closers=(close,))
    await _running(harness, completer.entered)

    closing = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.sleep(0)  # let aclose reach its drain
    assert not closed.is_set()  # the resource is not closed while work is in flight

    completer.release.set()
    await closing
    assert completer.finished.is_set()
    assert closed.is_set()
    assert closed_while_inflight is False


async def test_cancelling_aclose_still_closes_the_resources() -> None:
    """A cancelled aclose does not leave connections open (§2 ownership)."""
    completer = Gated()
    closed = asyncio.Event()

    async def close() -> None:
        closed.set()

    harness = phases_harness(completer, closers=(close,))
    await _running(harness, completer.entered)

    # First aclose blocks on the drain; cancel it while it waits.
    closing = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.sleep(0)
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert not closed.is_set()  # nothing closed yet — the drain is still waiting

    # The shutdown task survives the cancellation; letting work finish and awaiting
    # aclose again completes the closures exactly once.
    completer.release.set()
    await harness.engine.aclose()
    assert closed.is_set()


async def test_the_drain_is_unbounded_when_no_budget_is_given() -> None:
    """The pre-ADR-0083 shape, kept as the default (``drain_timeout=None``)."""
    completer = NeverFinishing()
    harness = phases_harness(completer)
    await _running(harness, completer.entered)

    closing = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.sleep(0.05)

    assert not closing.done()
    assert not completer.cancelled.is_set()

    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing


async def test_phase_a_ends_and_phase_b_cancels_the_remainder() -> None:
    """The budget is what keeps the graceful path reachable at all (ADR-0083 §4)."""
    completer = NeverFinishing()
    harness = phases_harness(completer, drain_timeout=timedelta(milliseconds=20))
    await _running(harness, completer.entered)

    await harness.engine.aclose()

    assert completer.cancelled.is_set()
    assert harness.engine.drain_phase is DrainPhase.CANCELLED


async def test_nothing_is_closed_until_the_cancelled_work_has_completed() -> None:
    """Phase B awaits what it cancelled, and that is ADR-0042 §2 satisfied literally.

    The cancelled call's cleanup is held behind its own gate, standing in for ADR-0054's
    worker thread finishing after the cancellation and before the error surfaces: while
    it is held, shutdown stays pending and nothing is closed.
    """
    closed = asyncio.Event()
    unwinding = asyncio.Event()
    finish_unwinding = asyncio.Event()
    unwound = asyncio.Event()

    class _SlowToUnwind(NeverFinishing):
        async def respond(
            self,
            exchange: PlanningExchange,
            tools: Sequence[OfferedTool],
            *,
            model: str | None = None,
        ) -> RoundResponse:
            try:
                return await super().respond(exchange, tools, model=model)
            except asyncio.CancelledError:
                unwinding.set()
                await finish_unwinding.wait()
                assert not closed.is_set(), "a resource was closed while work was unwinding"
                unwound.set()
                raise

    async def close() -> None:
        closed.set()

    completer = _SlowToUnwind()
    harness = phases_harness(completer, closers=(close,), drain_timeout=timedelta(milliseconds=20))
    await _running(harness, completer.entered)

    closing = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.wait_for(unwinding.wait(), SETTLE)
    # Phase B has cancelled the call, whose cleanup is still running.
    for _ in range(10):
        await asyncio.sleep(0)
    assert not closing.done(), "shutdown finished while cancelled work was still unwinding"
    assert not closed.is_set(), "a resource was closed while cancelled work was unwinding"

    finish_unwinding.set()
    await asyncio.wait_for(closing, SETTLE)

    assert unwound.is_set()
    assert closed.is_set()


async def test_work_that_finishes_inside_the_budget_is_never_cancelled() -> None:
    """Phase A is a *wait*, not a deadline the drain enforces on healthy work."""
    completer = Gated()
    harness = phases_harness(completer, drain_timeout=timedelta(seconds=30))
    await _running(harness, completer.entered)

    closing = asyncio.ensure_future(harness.engine.aclose())
    await asyncio.sleep(0)
    completer.release.set()
    await closing

    assert completer.finished.is_set()
    assert harness.engine.drain_phase is not DrainPhase.CANCELLED


async def test_aclose_closes_owned_resources_in_order() -> None:
    """The façade releases every resource, in the order it was handed them."""
    order: list[str] = []

    async def close_a() -> None:
        order.append("a")

    async def close_b() -> None:
        order.append("b")

    harness = phases_harness(closers=(close_a, close_b))
    await chat_turn(harness, "send it")
    await harness.engine.aclose()
    assert order == ["a", "b"]


async def test_aclose_attempts_every_closer_even_when_one_fails() -> None:
    """A raising closer must not skip the resources after it (§2 releases every one)."""
    closed: list[str] = []

    async def close_a() -> None:
        closed.append("a")
        msg = "resource a would not close"
        raise RuntimeError(msg)

    async def close_b() -> None:
        closed.append("b")

    harness = phases_harness(closers=(close_a, close_b))
    await chat_turn(harness, "send it")
    with pytest.raises(ExceptionGroup):
        await harness.engine.aclose()
    assert closed == ["a", "b"]  # b was closed despite a failing first


# --- conversations (ADR-0074, ADR-0293 §2) ----------------------------------------------


async def test_engine_start_finishes_a_deletion_a_previous_run_left_unfinished() -> None:
    """ADR-0074 §8: the reclaim runs "by the deleting call, **at engine start**".

    Since ADR-0293 §2:3 finishing it forgets nothing: the episode stays on its place.
    """
    harness = phases_harness()
    conversation, _ = await chat_turn(harness, "hello")
    (episode_id,) = await channel_ids(harness.memory, conversation)
    # An interrupted §8 sequence: the stamp landed, nothing else did.
    assert await harness.conversation_store.stamp_deleted(conversation) is True
    assert await harness.memory.get(episode_id) is not None

    await harness.engine.start()

    assert await harness.memory.get(episode_id) is not None, "deleting forgets nothing"
    assert await harness.engine.conversation(conversation) is None


async def test_recent_conversations_projects_what_a_person_chooses_from() -> None:
    """§2: the conversations a person chooses from, by activity."""
    harness = phases_harness()
    conversation, _ = await chat_turn(harness, "hello")

    listed = await harness.engine.recent_conversations()

    assert [one.id for one in listed] == [conversation]


async def test_forget_conversation_shows_the_span_then_forgets_the_episodes() -> None:
    """§8's show-then-confirm, then ADR-0293 §2:4: the episodes go, the conversation stays.

    Deleting it is the separate act, and forgets nothing (§2:3, §2:7).
    """
    harness = phases_harness()
    conversation, _ = await chat_turn(harness, "hello")
    await chat_turn(harness, "again", conversation=conversation, message_id="m-2")

    digest = await harness.engine.conversation(conversation)
    assert digest is not None
    assert digest.recorded_turns == 2
    assert digest.last_turn_at is not None

    assert await harness.engine.forget_conversation(conversation) is True

    assert await harness.memory.export() == [], "every episode it recorded is forgotten"
    after = await harness.engine.conversation(conversation)
    assert after is not None, "forgetting leaves the conversation"
    assert after.recorded_turns == 0
    assert await harness.engine.forget_conversation(conversation) is False

    assert await harness.engine.delete_conversation(conversation) is True
    assert await harness.engine.conversation(conversation) is None
    assert await harness.engine.recent_conversations() == ()


# --- traces (ADR-0119 §8) ----------------------------------------------------------------


async def test_a_completed_activation_emits_one_trace_through_the_sink() -> None:
    """The whole of §8's envelope, over a real activation rather than a stub.

    Through the ``TraceSink`` and not the ``TraceRetention``: they are two narrowings of
    one object in production (ADR-0119 §7), and the harness keeps them as two fakes so a
    case can tell which capability was used.
    """
    harness = phases_harness()

    await chat_turn(harness, "hello")

    (trace,) = [one for one in harness.trace_sink.recorded if one.seam == "chat_reader"]
    assert trace.kind is TraceKind.OPERATION
    assert trace.outcome is TraceOutcome.OK
    assert trace.refs[TraceRef.CORRELATION]
    assert harness.traces.recorded == ()


# --- the requesting device (ADR-0298 §2:6) ------------------------------------------------


class _Witness(FakeToolCallingCompleter):
    """Planning's default round, recording the requesting device it ran under."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[RequestingDevice] = []

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        self.seen.append(current_requesting_device())
        return await super().respond(exchange, tools, model=model)


async def test_the_activation_a_message_starts_does_not_run_as_its_device() -> None:
    """§2:6: the reader's activation runs with the requesting device unset."""
    witness = _Witness()
    harness = phases_harness(witness)
    conversation = await open_conversation(harness)
    with serving_device(RequestingDevice(device_id=PHONE.device_id)):
        await say(harness, conversation, "hi")
    await answered(harness, conversation, 1)
    assert witness.seen
    assert all(one == HUB_REQUESTING_DEVICE for one in witness.seen)
