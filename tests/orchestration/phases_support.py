"""Driving an activation through the phases, for cases that ran on the old path.

Until the switch lane (ADR-0309 §2:6, §4:5) a case that drives a chat message or an
event through the engine runs today's table unless the phases are wired. These helpers
wire them, as ``test_engine_phases`` does, so a case asserting behaviour that survives
the cutover — the stages before planning, capture, the reader, a stop, the drain — runs
on the path the switch leaves, and stays green before and after it.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from channel_receiver_contract import event_input
from test_engine import Harness, NoStepPlanner
from test_engine_phases import _BOOK, _phases
from understanding_support import understanding_stage

from ai_assistant.core.types import (
    ChatDevice,
    ControllerStage,
    DeviceAccess,
    EpisodicMemory,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.testing import FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import (
        ChannelInput,
        ChannelResult,
        ControllerRule,
        StageOutcome,
    )

#: The device every case writes from: the owner's own, so it may read and write.
PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)

#: How long a case waits for an activation to settle before it fails, rather than hangs.
SETTLE: Final = 5.0

#: An event's budget, ample for every stage over the fakes.
EVENT_BUDGET: Final = timedelta(seconds=10)


def phases_harness(
    completer: FakeToolCallingCompleter | None = None,
    *,
    phases: dict[str, Any] | None = None,
    **knobs: Any,
) -> Harness:
    """An engine with the phases wired, beside understanding, over ``knobs``' fakes.

    ``completer`` answers each planning round; the default writes one message and
    proposes nothing, so an activation ends after one round. ``phases`` are the
    keyword knobs ``test_engine_phases._phases`` takes; ``knobs`` are the harness's.
    Understanding is wired by default, since the phases are wired only beside it.
    """
    knobs.setdefault("planner", NoStepPlanner())
    knobs.setdefault("understanding", understanding_stage())
    knobs.setdefault("tools", (_BOOK,))
    return Harness(
        phases=_phases(completer or FakeToolCallingCompleter(), **(phases or {})),
        **knobs,
    )


async def open_conversation(harness: Harness) -> str:
    """Name :data:`PHONE` as the owner's device and start a conversation on it."""
    await harness.engine.set_my_devices([PHONE])
    return (await harness.engine.start_conversation()).id


async def say(harness: Harness, conversation: str, text: str, *, message_id: str = "m-1") -> None:
    """Write ``text`` into ``conversation`` from :data:`PHONE`, which starts an activation."""
    message = UserMessage(device_id=PHONE.device_id, message_id=message_id, text=text)
    await harness.engine.write_message(conversation, message=message)


#: The stages ADR-0309 §3's table makes due, and the end of the pass.
PHASE_PATH_STAGES: Final = frozenset(
    {
        ControllerStage.BEGIN_CONVERSATION,
        ControllerStage.WINDOWS,
        ControllerStage.RECALL,
        ControllerStage.UNDERSTANDING,
        ControllerStage.STORY_LINKS,
        ControllerStage.DIGESTING,
        ControllerStage.PLANNING,
        ControllerStage.AUTHORIZING,
        ControllerStage.ACTING,
        ControllerStage.END,
    }
)


def phased(episode: EpisodicMemory) -> EpisodicMemory:
    """``episode``, once checked that every stage that ran on it is one §3's table runs.

    Raises:
        AssertionError: If another ran, so the case is not on the phase path at all.
    """
    record = episode.processing_record
    assert record is not None
    other = {one.stage for one in record.stages} - PHASE_PATH_STAGES
    assert not other, f"a stage off the phase path ran: {sorted(other)}"
    return episode


async def frozen(harness: Harness) -> list[EpisodicMemory]:
    """Every episode whose processing record is frozen, in the store's order."""
    return [
        one
        for one in await harness.memory.export()
        if isinstance(one, EpisodicMemory)
        and one.processing_record is not None
        and not one.processing_record.is_open
    ]


async def settled(
    harness: Harness, conversation: str, *, before: frozenset[str] = frozenset()
) -> EpisodicMemory:
    """Wait for the conversation's activation to end and its episode to freeze.

    ``before`` names the frozen episodes that are not it.

    Raises:
        AssertionError: If nothing settles within :data:`SETTLE`.
    """
    deadline = asyncio.get_running_loop().time() + SETTLE
    while True:
        state = await harness.engine.conversation(conversation)
        episodes = [one for one in await frozen(harness) if one.id not in before]
        if state is not None and not state.state.working and episodes:
            (episode,) = episodes
            return phased(episode)
        if asyncio.get_running_loop().time() > deadline:
            msg = "the activation never settled"
            raise AssertionError(msg)
        await asyncio.sleep(0.001)


async def chat_turn(
    harness: Harness,
    text: str,
    *,
    conversation: str | None = None,
    message_id: str = "m-1",
) -> tuple[str, EpisodicMemory]:
    """One message written, and the episode of the activation it started, once frozen.

    A conversation is started where ``conversation`` names none. A second turn on the
    same conversation names it and a ``message_id`` of its own.

    Returns:
        The conversation's id and the new episode.
    """
    if conversation is None:
        conversation = await open_conversation(harness)
    before = frozenset(one.id for one in await frozen(harness))
    await say(harness, conversation, text, message_id=message_id)
    return conversation, await settled(harness, conversation, before=before)


async def written(harness: Harness, conversation: str) -> list[TranscriptMessage]:
    """The conversation's messages, oldest first."""
    page = await harness.conversation_store.transcript(conversation, limit=100)
    assert page is not None
    return [one for one in page.entries if isinstance(one, TranscriptMessage)]


async def event(
    harness: Harness,
    received: ChannelInput | None = None,
    *,
    timeout: timedelta = EVENT_BUDGET,  # noqa: ASYNC109 — the event's budget, handed to receive
) -> tuple[ChannelResult, EpisodicMemory]:
    """Receive an event — the shared contract's by default — and read the episode it froze."""
    result = await harness.engine.receive(
        event_input() if received is None else received, reply=None, timeout=timeout
    )
    assert result.capture.episode_id is not None
    episode = await harness.memory.get(result.capture.episode_id)
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert not episode.processing_record.is_open
    return result, phased(episode)


def entries(
    episode: EpisodicMemory,
    *,
    keep: Callable[[ControllerStage], bool] = lambda _: True,
) -> list[tuple[ControllerStage, ControllerRule, StageOutcome]]:
    """The episode's stage entries, as (stage, rule, outcome), for the stages ``keep``s."""
    record = episode.processing_record
    assert record is not None
    return [(one.stage, one.due, one.outcome) for one in record.stages if keep(one.stage)]
