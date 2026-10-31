"""Driving an activation through the phases, for cases that ran on the old path.

A case that drives a chat message or an event through the engine needs the phases
wired, since they plan every activation (ADR-0309 §2:6). These helpers wire them, as
``test_engine_phases`` does, so a case asserting behaviour that survived the cutover —
the stages before planning, capture, the reader, a stop, the drain — runs on them.

The ``test_phases_*`` suites import from here, from the shared ``*_support`` modules,
from ``test_engine``'s harness and from ``test_engine_phases`` alone, and copy any
other fixture they need: the suites that drive today's table lose their cases in the
cutover's lanes, and a ported case must not lose its fixtures with them.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final, cast

from channel_receiver_contract import event_input
from exchange_support import says
from test_engine import Harness
from test_engine_phases import _BOOK, _phases
from understanding_support import understanding_stage

from ai_assistant.core.types import (
    ActivationEnding,
    ChatDevice,
    ControllerRule,
    ControllerStage,
    DeviceAccess,
    EpisodicMemory,
    MessageAuthor,
    ProcessingReason,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedTextInput,
    RoundResponse,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.orchestration.conversations import activation_ending
from ai_assistant.testing import FakeToolCallingCompleter
from ai_assistant.testing.tool_calling import DEFAULT_ROUND_TEXT

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    import pytest

    from ai_assistant.core.types import (
        ChannelInput,
        ChannelResult,
        EpisodeProcessingRecord,
        OfferedTool,
        PlanningExchange,
        StageOutcome,
    )
    from ai_assistant.orchestration.phase_path import PhasePath
    from ai_assistant.testing import FakeMemoryStore
    from ai_assistant.testing.tool_calling import RoundReply

#: The device every case writes from: the owner's own, so it may read and write.
PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)

#: How long a case waits for an activation to settle before it fails, rather than hangs.
SETTLE: Final = 5.0

#: An event's budget, ample for every stage over the fakes.
EVENT_BUDGET: Final = timedelta(seconds=10)

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


# --- planning's rounds --------------------------------------------------------------------


def replying(words: str = DEFAULT_ROUND_TEXT) -> FakeToolCallingCompleter:
    """Planning whose every work's first round sends ``words``, and whose later rounds end it.

    The phases' stand-in for a model that answers the person and stops: each activation's
    first round (an exchange with no step yet) makes one ``text`` call, and each round
    after proposes nothing, so the work ends after two rounds.
    """

    return FakeToolCallingCompleter(response=replies(words))


def replies(words: str) -> RoundReply:
    """A response sending ``words`` in a work's first round, and nothing in each after."""

    def respond(exchange: PlanningExchange, _tools: Sequence[OfferedTool]) -> RoundResponse:
        return says(words) if not exchange.steps else RoundResponse()

    return respond


# --- the engine -------------------------------------------------------------------------


def phases_harness(
    completer: FakeToolCallingCompleter | None = None,
    *,
    phases: dict[str, Any] | None = None,
    **knobs: Any,
) -> Harness:
    """An engine with the phases wired, beside understanding, over ``knobs``' fakes.

    ``completer`` answers each planning round; the default (:func:`replying`) sends one
    message in its first round and proposes nothing in its second, so an activation ends
    after two rounds. ``phases`` are the
    keyword knobs ``test_engine_phases._phases`` takes; ``knobs`` are the harness's.
    Understanding is wired by default, since the phases are wired only beside it.
    """
    knobs.setdefault("understanding", understanding_stage())
    knobs.setdefault("tools", (_BOOK,))
    return Harness(
        phases=_phases(completer or replying(), **(phases or {})),
        **knobs,
    )


@dataclass(frozen=True)
class _Seams:
    """The harness attributes ``test_engine_phases._phases`` builds the path over."""

    invoker: object
    memory: object
    plans: object
    trail: object
    conversation_store: object


def phase_path(  # noqa: PLR0913 — the seams an engine already holds, and the path's knobs
    completer: FakeToolCallingCompleter | None = None,
    *,
    invoker: object,
    memory: object,
    plans: object,
    trail: object,
    conversations: object,
    **knobs: Any,
) -> PhasePath:
    """The phases, built as ``test_engine_phases`` builds them, over an engine's own seams.

    For a suite that builds its ``Engine`` directly rather than through the harness:
    the path holds the same invoker, memory store, plan store, trail and chat space the
    engine is handed, as the composition root's does (``_PhaseSeams``).
    """
    seams = _Seams(
        invoker=invoker,
        memory=memory,
        plans=plans,
        trail=trail,
        conversation_store=conversations,
    )
    build = _phases(completer or replying(), **knobs)
    return build(cast("Harness", seams))


class Gated(FakeToolCallingCompleter):
    """Planning's rounds, each answered only once :attr:`release` is set.

    ``responses`` are answered in turn, as :meth:`FakeToolCallingCompleter.scripted`
    answers them; with none, each work's rounds are :func:`replying`'s.
    """

    def __init__(self, *responses: RoundResponse) -> None:
        queue = list(responses)

        def next_response(
            _exchange: PlanningExchange, _tools: Sequence[OfferedTool]
        ) -> RoundResponse:
            return queue.pop(0)

        super().__init__(response=next_response if responses else replies(DEFAULT_ROUND_TEXT))
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        self.entered.set()
        await self.release.wait()
        self.finished.set()
        return await super().respond(exchange, tools, model=model)


class NeverFinishing(FakeToolCallingCompleter):
    """A planning call that runs until it is cancelled, and honours the cancellation.

    ADR-0083 §4's argument rests on every in-flight party honouring cancellation, so
    a fake that ignored it would test the shape that ADR declined.
    """

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        del exchange, tools, model
        self.entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise AssertionError  # pragma: no cover - the wait above never returns


# --- driving a conversation ----------------------------------------------------------------


def said(message_id: str, text: str, *, replies_to: int | None = None) -> UserMessage:
    """A message from :data:`PHONE`."""
    return UserMessage(
        device_id=PHONE.device_id, message_id=message_id, text=text, replies_to=replies_to
    )


async def open_conversation(harness: Harness) -> str:
    """Name :data:`PHONE` as the owner's device and start a conversation on it."""
    await harness.engine.set_my_devices([PHONE])
    return (await harness.engine.start_conversation()).id


async def say(harness: Harness, conversation: str, text: str, *, message_id: str = "m-1") -> None:
    """Write ``text`` into ``conversation`` from :data:`PHONE`, which starts an activation."""
    await harness.engine.write_message(conversation, message=said(message_id, text))


async def until(check: Callable[[], Awaitable[bool]], *, what: str) -> None:
    """Wait for ``check`` to hold, polling the loop; fail rather than hang."""
    deadline = asyncio.get_running_loop().time() + SETTLE
    while not await check():
        if asyncio.get_running_loop().time() > deadline:
            msg = f"never settled: {what}"
            raise AssertionError(msg)
        await asyncio.sleep(0.001)


async def written(harness: Harness, conversation: str) -> list[TranscriptMessage]:
    """The conversation's messages, oldest first."""
    page = await harness.conversation_store.transcript(conversation, limit=100)
    assert page is not None
    return [one for one in page.entries if isinstance(one, TranscriptMessage)]


async def answered(harness: Harness, conversation: str, count: int) -> list[TranscriptMessage]:
    """Wait for ``count`` assistant messages and for the reader to be idle, then read."""

    async def done() -> bool:
        messages = await written(harness, conversation)
        state = await harness.engine.conversation(conversation)
        assistant = [one for one in messages if one.author is MessageAuthor.ASSISTANT]
        return len(assistant) >= count and state is not None and not state.state.working

    await until(done, what=f"{count} assistant message(s)")
    return await written(harness, conversation)


def hold_start_waits(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    """Hold every start wait the hub chat's reader sleeps in from here until it is set.

    What a case writes meanwhile waits in one start wait (ADR-0332 §5:1), however long
    the writing takes, so it is one input; a start wait that has already passed when its
    read first looks sleeps not at all, so the harness's wait needs to outlast the call
    that writes the first message.
    """
    reader = harness.engine._chat_reader
    assert reader is not None
    over = asyncio.Event()

    async def held(seconds: float) -> None:
        del seconds
        await over.wait()

    monkeypatch.setattr(reader, "_sleep", held)
    return over


async def idle(harness: Harness, conversation: str) -> None:
    """Wait until the conversation shows no activation working."""

    async def done() -> bool:
        digest = await harness.engine.conversation(conversation)
        return digest is not None and not digest.state.working

    await until(done, what="the conversation to be idle")


async def working(harness: Harness, conversation: str) -> str:
    """Wait for the conversation to show *working…* with an id, and return the id."""
    found: list[str] = []

    async def shown() -> bool:
        digest = await harness.engine.conversation(conversation)
        if digest is None or not digest.state.activation_ids:
            return False
        found.append(digest.state.activation_ids[-1])
        return True

    await until(shown, what="the running activation's id")
    return found[-1]


# --- what an activation left ---------------------------------------------------------------


def phased(episode: EpisodicMemory) -> EpisodicMemory:
    """``episode``, once checked that every stage that ran on it is one §3's table runs.

    Raises:
        AssertionError: If another ran, so the case is not on the phase path at all.
    """
    record = processing(episode)
    other = {one.stage for one in record.stages} - PHASE_PATH_STAGES
    assert not other, f"a stage off the phase path ran: {sorted(other)}"
    return episode


def processing(episode: EpisodicMemory) -> EpisodeProcessingRecord:
    """The episode's processing record, which every activation's episode carries."""
    assert episode.processing_record is not None
    return episode.processing_record


def entries(
    record: EpisodeProcessingRecord,
) -> list[tuple[ControllerStage, ControllerRule, StageOutcome]]:
    """The record's stage entries, as (stage, rule, outcome)."""
    return [(one.stage, one.due, one.outcome) for one in record.stages]


async def episodes(memory: FakeMemoryStore) -> list[EpisodicMemory]:
    """Every episode the store holds, open or frozen, in the store's order."""
    return [one for one in await memory.export() if isinstance(one, EpisodicMemory)]


async def frozen(harness: Harness) -> list[EpisodicMemory]:
    """Every episode whose processing record is frozen, in the store's order."""
    return [
        one
        for one in await episodes(harness.memory)
        if one.processing_record is not None and not one.processing_record.is_open
    ]


def input_of(episode: EpisodicMemory) -> str:
    """The text an episode's activation was admitted with."""
    trigger = processing(episode).trigger
    assert isinstance(trigger, RecordedChannelTrigger)
    assert isinstance(trigger.payload, RecordedTextInput)
    return trigger.payload.text


def stopped(episode: EpisodicMemory) -> None:
    """The record says a stop ended it: its reason, its status and its end entry."""
    record = processing(episode)
    assert (record.status, record.reason) == (
        ProcessingStatus.INTERRUPTED,
        ProcessingReason.STOPPED,
    )
    assert record.stages[-1].stage is ControllerStage.END
    assert record.stages[-1].due is ControllerRule.STOPPED
    assert activation_ending(episode) is ActivationEnding.STOPPED


async def settled(
    harness: Harness, conversation: str, *, before: frozenset[str] = frozenset()
) -> EpisodicMemory:
    """Wait for the conversation's activation to end and its episode to freeze.

    ``before`` names the frozen episodes that are not it.

    Raises:
        AssertionError: If nothing settles within :data:`SETTLE`.
    """
    found: list[EpisodicMemory] = []

    async def done() -> bool:
        state = await harness.engine.conversation(conversation)
        found[:] = [one for one in await frozen(harness) if one.id not in before]
        return state is not None and not state.state.working and bool(found)

    await until(done, what="the activation to settle")
    (episode,) = found
    return phased(episode)


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
    assert not processing(episode).is_open
    return result, phased(episode)
