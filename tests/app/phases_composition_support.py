"""The production root with the phases wired, and a chat activation driven through it.

The composition root builds the phases on every deployment (ADR-0309 §2:6), so the
``test_phases_*`` suites under ``tests/app`` run a case asserting behaviour that
survived the cutover — the open episode, a channel's history, a restart's closing —
through the root as it is.

The substitutes are the model-facing seams alone, as the old-path composition suites
substitute them: the provider's ``complete``, answering the understanding stage with a
stated reading, and the tool-calling completer planning's rounds go through. A
conversational activation is a message written into a conversation and taken in by the
chat's reader (ADR-0293 §6), since ``converse`` retires at the cutover (ADR-0309 §5:1).

These suites import from here alone and copy any other fixture they need, so the
cutover's lanes can delete the old-path suites without taking a ported case's fixtures.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    ChannelIdentity,
    ChannelInput,
    ChatDevice,
    ControllerStage,
    DeviceAccess,
    EpisodicMemory,
    MessageAuthor,
    RoundResponse,
    TextChannelPayload,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.models import PydanticAIProvider
from ai_assistant.models.tool_calling import PydanticAIToolCallingCompleter
from ai_assistant.orchestration.activation_state import active_state
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.understanding import UNDERSTANDING_PROMPT
from ai_assistant.testing import FakeModelProvider, FakeToolCallingCompleter, default_renderings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from pathlib import Path

    import pytest

    from ai_assistant.core.protocols import (
        ActionPolicy,
        ConversationStore,
        EgressBinder,
        MemoryStore,
        ToolRegistry,
        WebSearcher,
    )
    from ai_assistant.core.types import ChannelResult, Message, OfferedTool
    from ai_assistant.orchestration import Engine
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.activation_writer import ActivationWriter
    from ai_assistant.orchestration.phase_path import PhasePath

#: An event's budget, and the most a case waits for an activation to settle.
BUDGET: Final = timedelta(seconds=10)
SETTLE: Final = 10.0

#: Every system message understanding's shipped template renders, one per combination
#: of its flags: how the fake tells understanding's call from the rest without
#: matching the instruction's words (ADR-0334 §9:1).
UNDERSTANDING_INSTRUCTIONS: Final = default_renderings(UNDERSTANDING_PROMPT)
#: The meaning the substituted understanding states for every input.
MEANING: Final = "The input means what it says."
_UNDERSTOOD: Final = json.dumps({"understanding": MEANING})

#: The device every conversation is written from: the owner's own.
PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)

#: An informational event channel, which declares its input ``outside`` (ADR-0284 §2:2).
SENSOR: Final = ChannelIdentity(channel_type="informational_event", instance_id="sensor")

#: What planning's default round writes, and so what a conversation is answered with.
REPLY: Final = "Noted."

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


def _reply(messages: Sequence[Message]) -> str:
    """Answer the understanding stage with a stated reading, and every other call alike."""
    return _UNDERSTOOD if messages[0].content in UNDERSTANDING_INSTRUCTIONS else REPLY


@dataclass
class Phased:
    """The engine the root built with the phases, and the fakes behind its model seams."""

    engine: Engine
    #: Every ``complete`` call the root's provider is asked, recorded.
    model: FakeModelProvider
    #: Every planning round, answered.
    completer: FakeToolCallingCompleter
    #: The settings the root was built from.
    settings: Settings
    _messages: Any = field(default_factory=lambda: count(1))

    @property
    def memory(self) -> MemoryStore:
        """The memory store the lifecycle and the writer were handed."""
        return self.engine._conversations._memory

    @property
    def conversations(self) -> ConversationStore:
        """The conversation store the lifecycle was handed, the chat space included."""
        return self.engine._conversations._conversations

    @property
    def writer(self) -> ActivationWriter:
        """The activation writer the lifecycle built."""
        return self.engine._conversations.activation_writer

    async def start_conversation(self) -> str:
        """Name :data:`PHONE` as the owner's device and start a conversation on it."""
        await self.engine.set_my_devices([PHONE])
        return (await self.engine.start_conversation()).id

    async def write(self, conversation_id: str, text: str) -> int:
        """Write ``text`` into the conversation from :data:`PHONE`; the reader takes it in.

        Returns:
            The message's position in the transcript.
        """
        message = UserMessage(
            device_id=PHONE.device_id, message_id=f"m-{next(self._messages)}", text=text
        )
        receipt = await self.engine.write_message(conversation_id, message=message)
        assert receipt.position is not None, "the conversation recorded the message"
        return receipt.position

    async def held(self, conversation_id: str) -> list[str]:
        """Every id the store physically holds on the conversation's channel."""
        page = await self.memory.channel_episode_ids(
            conversation_channel(conversation_id), limit=1000
        )
        return [entry.episode_id for entry in page]

    async def idle(self, conversation_id: str) -> None:
        """Wait until the conversation shows no activation working."""

        async def done() -> bool:
            digest = await self.engine.conversation(conversation_id)
            return digest is not None and not digest.state.working

        await until(done, what="the conversation to be idle")

    async def say(self, text: str, conversation_id: str | None = None) -> Turn:
        """One message, and the activation it started once it ended.

        A conversation is started where none is named. The turn's episode is the one its
        activation's id names, which the reader recorded as having taken the message in.
        """
        if conversation_id is None:
            conversation_id = await self.start_conversation()
        position = await self.write(conversation_id, text)
        activation = await self.taken_by(conversation_id, position)
        await self.idle(conversation_id)
        return Turn(conversation_id=conversation_id, activation_id=activation)

    async def taken_by(self, conversation_id: str, position: int) -> str:
        """The activation the reader recorded as taking in the message at ``position``."""
        found: dict[int, str] = {}

        async def taken() -> bool:
            found.update(await self.conversations.taken_in(conversation_id, positions=[position]))
            return position in found

        await until(taken, what=f"message {position} to be taken in")
        return found[position]

    async def messages(self, conversation_id: str) -> list[TranscriptMessage]:
        """The conversation's messages, oldest first."""
        page = await self.conversations.transcript(conversation_id, limit=100)
        assert page is not None
        return [one for one in page.entries if isinstance(one, TranscriptMessage)]

    async def answered(self, conversation_id: str) -> list[str]:
        """The texts the assistant wrote into the conversation, oldest first."""
        return [
            one.text
            for one in await self.messages(conversation_id)
            if one.author is MessageAuthor.ASSISTANT
        ]

    async def stored(self, address: str) -> EpisodicMemory | None:
        """The episode the store holds at ``address``, open or frozen."""
        record = await self.memory.get(address)
        assert record is None or isinstance(record, EpisodicMemory)
        return record

    async def event(self, text: str = "eco mode") -> ChannelResult:
        """One informational event, admitted and run by the phases."""
        return await self.engine.receive(
            ChannelInput(target=SENSOR, payload=TextChannelPayload(text=text)),
            reply=None,
            timeout=BUDGET,
        )

    def cut_off(self) -> None:
        """Make every later freeze not happen, as a process dying mid-pass leaves it."""

        async def died(state: ActivationState, *_args: object, **_kwargs: object) -> object:
            return state.degraded_report()

        # A test double standing in for the bound method, its signature loosened.
        self.writer.write = died  # type: ignore[method-assign,assignment]


@dataclass(frozen=True)
class Turn:
    """A conversational activation: its conversation, and the activation the reader ran."""

    conversation_id: str
    activation_id: str

    @property
    def address(self) -> str:
        """The address its episode is stored at (ADR-0286 §2)."""
        return f"activation:{self.activation_id}"


async def until(check: Callable[[], Awaitable[bool]], *, what: str) -> None:
    """Wait for ``check`` to hold, polling the loop; fail rather than hang."""
    deadline = asyncio.get_running_loop().time() + SETTLE
    while not await check():
        if asyncio.get_running_loop().time() > deadline:
            msg = f"never settled: {what}"
            raise AssertionError(msg)
        await asyncio.sleep(0.005)


def build_phased(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    completer: FakeToolCallingCompleter | None = None,
    **settings: Any,
) -> Phased:
    """The production root over ``tmp_path`` with the phases wired, not yet started.

    ``settings`` are further :class:`Settings` fields; the embedder is the hashing one,
    so nothing is downloaded.
    """
    model = FakeModelProvider(_reply)
    planning = (
        completer if completer is not None else FakeToolCallingCompleter(RoundResponse(text=REPLY))
    )

    async def complete(
        _self: PydanticAIProvider, messages: Sequence[Message], *, model: str | None = None
    ) -> Message:
        return await recorded.complete(messages, model=model)

    async def respond(
        _self: PydanticAIToolCallingCompleter,
        messages: Sequence[Message],
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        return await planning.respond(messages, tools, model=model)

    recorded = model
    monkeypatch.setattr(PydanticAIProvider, "complete", complete)
    monkeypatch.setattr(PydanticAIToolCallingCompleter, "respond", respond)
    built = Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING, **settings)
    engine = build_engine(built, data_dir=tmp_path)
    assert engine._phases is not None, "the root wired the phases"
    return Phased(engine=engine, model=model, completer=planning, settings=built)


def wired_phases(engine: Engine) -> PhasePath:
    """The phases the composition root built into ``engine`` (ADR-0309 §2:6).

    The reach-in is deliberate: the root's obligations are about *which object ends up
    where*, and no public surface exposes that.
    """
    phases = engine._phases
    assert phases is not None, "the root wires the phases on every deployment"
    return phases


def wired_registry(engine: Engine) -> ToolRegistry:
    """The deployment's one registry and invoker, as the phases' tools hold it."""
    return wired_phases(engine)._tools._registry


def wired_binder(engine: Engine) -> EgressBinder | None:
    """The egress binding seam authorizing binds a call through (ADR-0152 §10)."""
    return wired_phases(engine)._authorizing._binder


def wired_policy(engine: Engine) -> ActionPolicy:
    """The policy authorizing rules with (ADR-0306 §4:11)."""
    return wired_phases(engine)._authorizing._policy


def wired_searcher(engine: Engine) -> WebSearcher | None:
    """The configured search the phases' tools hold, or ``None`` (ADR-0309 §4)."""
    return wired_phases(engine)._tools._searcher


def phased(record: EpisodicMemory | None) -> EpisodicMemory:
    """``record``, once checked that every stage that ran on it is one §3's table runs."""
    assert record is not None
    assert record.processing_record is not None
    other = {one.stage for one in record.processing_record.stages} - PHASE_PATH_STAGES
    assert not other, f"a stage off the phase path ran: {sorted(other)}"
    return record


@dataclass
class Gate:
    """A stage wrapper's stopping point: where a matching pass waits, and what it saw."""

    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    addresses: list[str] = field(default_factory=list)
    working: list[Any] = field(default_factory=list)

    @property
    def address(self) -> str:
        """The address of the pass that waited here."""
        (address,) = self.addresses
        return address


def hold(
    monkeypatch: pytest.MonkeyPatch,
    engine: Engine,
    stage: str,
    matches: Callable[[Any], bool],
) -> Gate:
    """Hold a matching pass once ``stage``'s body returns, before its entry is appended.

    The phases' stages before planning are the engine's own methods, read when a pass
    builds its stage list, so a wrapper set on the engine is the one the pass runs.
    """
    gate = Gate()
    original: Callable[[Any], Awaitable[None]] = getattr(engine, stage)

    async def held(working: Any) -> None:
        await original(working)
        if matches(working):
            state = active_state()
            assert state is not None
            assert state.episode_address is not None
            gate.addresses.append(state.episode_address)
            gate.working.append(working)
            gate.entered.set()
            await gate.release.wait()

    monkeypatch.setattr(engine, stage, held)
    return gate


def saying(text: str) -> Callable[[Any], bool]:
    """A pass whose input is ``text``."""
    return lambda working: getattr(working, "utterance", None) == text
