"""The hub chat's reader on its own: the start wait, composing, and holding (ADR-0332).

Driven over the canonical conversation store with a stand-in for the engine's
activation, and on a clock the case moves, so each case reads what the reader took in
and how long it waited.

- Where nothing is running, the reader takes a conversation's waiting messages in once
  ``chat_start_wait`` has passed since the latest of them and no composing signal is
  live, and no later than ``chat_composing_cap`` after the first (§5:1-§5:2).
- A composing signal stays live for ``chat_composing_lapse``, and only extends a start
  wait already running (§5:6-§5:8).
- While an activation runs, no message joins it by code (ADR-0349 §1:4's step 2): one
  noticed waits, and everything waiting is taken in together once it ends, until the
  readers' own step retires the holding (ADR-0349 §8).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    ChatDevice,
    DeviceAccess,
    MessageAuthor,
    NewMessage,
    TranscriptMessage,
)
from ai_assistant.orchestration.chat import ChatInput, ChatReader
from ai_assistant.testing import FakeConversationStore

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

#: How long a case waits for the reader before it fails rather than hangs.
_SETTLE: Final = 5.0

#: The device every message is written from: the owner's own.
_PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)

_START: Final = timedelta(seconds=1.5)
_LAPSE: Final = timedelta(seconds=3)
_CAP: Final = timedelta(seconds=10)


class _Clock:
    """A clock the case moves, and a sleep that waits for the case to wake it.

    A sleep records how long it was asked for and waits for :meth:`wake`; once woken,
    the clock reads at least the instant the sleep was to end.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []
        self._woken = asyncio.Event()
        self.sleeping = asyncio.Event()

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        end = self.now + seconds
        self.slept.append(seconds)
        self.sleeping.set()
        await self._woken.wait()
        self._woken.clear()
        self.now = max(self.now, end)

    async def wake(self) -> None:
        """Wake the sleep under way, and wait for the reader to act on it."""
        await asyncio.wait_for(self.sleeping.wait(), _SETTLE)
        self.sleeping.clear()
        self._woken.set()
        for _ in range(20):
            await asyncio.sleep(0)


class _Reader:
    """A chat reader over a fake store, its activation and its join stand-ins."""

    def __init__(
        self,
        *,
        store: FakeConversationStore | None = None,
        start_wait: timedelta | None = _START,
    ) -> None:
        self.store = store or FakeConversationStore()
        self.clock = _Clock()
        self.inputs: list[ChatInput] = []
        self.taken_at: list[float] = []
        self.gate: asyncio.Event | None = None
        self.entered = asyncio.Event()
        self.tasks: list[asyncio.Task[None]] = []
        self.closing = False
        self._ids = iter(f"act-{n}" for n in range(1, 100))
        self._sent = 0
        self.reader = ChatReader(
            conversations=self.store,
            activate=self._activate,
            spawn=self._spawn,
            closing=lambda: self.closing,
            mint=lambda: next(self._ids),
            start_wait=start_wait,
            composing_lapse=_LAPSE,
            composing_cap=_CAP,
            clock=self.clock,
            sleep=self.clock.sleep,
        )

    def _spawn(self, read: Coroutine[None, None, None]) -> None:
        self.tasks.append(asyncio.ensure_future(read))

    async def _activate(self, taken: ChatInput) -> bool:
        self.inputs.append(taken)
        self.taken_at.append(self.clock.now)
        marked: list[int] = []
        await self.reader.take_in(taken, into=marked)
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        return bool(marked)

    async def conversation(self) -> str:
        await self.store.set_my_devices([_PHONE])
        return (await self.store.start()).id

    async def say(self, conversation: str, text: str) -> int:
        """Write the user's message, and tell the reader, as the engine's write does."""
        self._sent += 1
        receipt = await self.store.append_message(
            conversation,
            NewMessage(
                author=MessageAuthor.USER,
                text=text,
                device_id="phone",
                message_id=f"m-{self._sent}",
            ),
        )
        assert receipt.position is not None
        self.reader.notice(conversation)
        return receipt.position

    async def until(self, check: Callable[[], bool], *, what: str) -> None:
        deadline = asyncio.get_running_loop().time() + _SETTLE
        while not check():
            if asyncio.get_running_loop().time() > deadline:
                msg = f"never settled: {what}"
                raise AssertionError(msg)
            await asyncio.sleep(0.001)

    async def marked(self, conversation: str, position: int) -> None:
        """Wait for the message at ``position`` to be marked taken in."""
        deadline = asyncio.get_running_loop().time() + _SETTLE
        while not await self.store.taken_in(conversation, positions=[position]):
            if asyncio.get_running_loop().time() > deadline:
                msg = "never marked"
                raise AssertionError(msg)
            await asyncio.sleep(0.001)

    async def idle(self) -> None:
        await asyncio.wait_for(asyncio.gather(*self.tasks), _SETTLE)


def _texts(taken: ChatInput) -> list[str]:
    return [one.text for one in taken.messages]


# --- the start wait (§5:1-§5:2) ----------------------------------------------------------


async def test_messages_inside_the_start_wait_are_taken_in_together_after_the_latest() -> None:
    """§5:1: the wait runs from the latest message, and what arrived is one input."""
    chat = _Reader()
    conversation = await chat.conversation()
    await chat.say(conversation, "book Riverside")
    await asyncio.wait_for(chat.clock.sleeping.wait(), _SETTLE)
    assert chat.inputs == [], "nothing is taken in before the wait has passed"

    chat.clock.now = 1.0
    await chat.say(conversation, "for Saturday")
    await chat.clock.wake()
    assert chat.inputs == [], "the second message moved the wait's end"
    await chat.clock.wake()
    await chat.idle()

    (taken,) = chat.inputs
    assert _texts(taken) == ["book Riverside", "for Saturday"]
    assert chat.clock.slept == [_START.total_seconds(), 1.0], "until 1.0 + the start wait"


async def test_a_composing_signal_extends_the_wait_and_a_lapsed_one_does_not() -> None:
    """§5:1, §5:6: the wait ends once no signal is live, so typing holds it."""
    chat = _Reader()
    conversation = await chat.conversation()
    await chat.say(conversation, "book Riverside")
    await asyncio.wait_for(chat.clock.sleeping.wait(), _SETTLE)
    chat.clock.now = 1.0
    chat.reader.composing(conversation)
    await chat.clock.wake()
    assert chat.inputs == []
    await chat.clock.wake()
    await chat.idle()

    assert len(chat.inputs) == 1
    assert chat.clock.slept == [_START.total_seconds(), 1.0 + _LAPSE.total_seconds() - 1.5], (
        "held until the signal lapsed, 1.0 + the lapse"
    )


async def test_the_cap_ends_the_wait_whatever_the_composing_signal_says() -> None:
    """§5:2: no later than ``chat_composing_cap`` after the first waiting message."""
    chat = _Reader()
    conversation = await chat.conversation()
    await chat.say(conversation, "book Riverside")
    await asyncio.wait_for(chat.clock.sleeping.wait(), _SETTLE)
    while not chat.inputs:
        # The person keeps typing: a signal arrives while the reader sleeps.
        chat.clock.now += 0.5
        chat.reader.composing(conversation)
        await chat.clock.wake()
    await chat.idle()

    assert chat.taken_at == [pytest.approx(_CAP.total_seconds())], "taken in at the cap"


async def test_a_composing_signal_with_no_wait_running_does_nothing() -> None:
    """§5:7-§5:8: it starts no read and no wait, and is not input."""
    chat = _Reader()
    conversation = await chat.conversation()
    chat.reader.composing(conversation)
    assert chat.tasks == []

    await chat.say(conversation, "hi")
    await chat.clock.wake()
    await chat.idle()
    chat.reader.composing(conversation)

    assert chat.tasks[1:] == [], "a signal once the wait has ended starts nothing"
    assert chat.clock.slept == [_START.total_seconds()], "and extended nothing"
    assert len(chat.inputs) == 1


async def test_without_a_start_wait_a_message_is_taken_in_at_once() -> None:
    """A reader built with none, as the canonical fake engine builds it: no wait at all."""
    chat = _Reader(start_wait=None)
    conversation = await chat.conversation()
    await chat.say(conversation, "hi")
    chat.reader.composing(conversation)
    await chat.idle()

    assert len(chat.inputs) == 1
    assert chat.clock.slept == []


async def test_a_close_ends_a_start_wait_at_once_and_takes_nothing_in() -> None:
    """The engine closing: the wait ends, the message waits, and a restart takes it in."""
    chat = _Reader()
    conversation = await chat.conversation()
    await chat.say(conversation, "hi")
    await asyncio.wait_for(chat.clock.sleeping.wait(), _SETTLE)

    chat.closing = True
    chat.reader.close()
    await chat.idle()

    assert chat.inputs == []
    assert [one.text for one in await chat.store.untaken_messages(conversation)] == ["hi"]


def test_the_waits_are_held_to_their_bounds() -> None:
    """§6:1-§6:3: strictly positive, and the cap no shorter than either."""
    store = FakeConversationStore()

    def build(start: timedelta, lapse: timedelta, cap: timedelta) -> ChatReader:
        async def activate(taken: ChatInput) -> bool:
            del taken
            return True

        return ChatReader(
            conversations=store,
            activate=activate,
            spawn=lambda read: read.close(),
            closing=lambda: False,
            mint=lambda: "act-1",
            start_wait=start,
            composing_lapse=lapse,
            composing_cap=cap,
        )

    for start, lapse, cap in (
        (timedelta(0), _LAPSE, _CAP),
        (_START, timedelta(0), _CAP),
        (_START, _LAPSE, timedelta(seconds=2)),
    ):
        with pytest.raises(ValueError, match="ADR-0332"):
            build(start, lapse, cap)
    build(_START, _LAPSE, _LAPSE)


# --- holding behind running work (ADR-0332 §2:4, until ADR-0349 §1:4's step 3) ----------


async def _running(chat: _Reader) -> str:
    """A conversation whose first activation has been admitted and holds."""
    chat.gate = asyncio.Event()
    conversation = await chat.conversation()
    await chat.say(conversation, "book Riverside")
    await chat.clock.wake()
    await asyncio.wait_for(chat.entered.wait(), _SETTLE)
    return conversation


async def test_a_message_written_while_one_runs_waits_and_is_taken_in_after() -> None:
    """ADR-0349 §1:4's step 2: nothing joins by code; what waits is taken in together."""
    chat = _Reader()
    conversation = await _running(chat)
    first = await chat.say(conversation, "actually Saturday")
    await chat.say(conversation, "and at seven")
    for _ in range(20):
        await asyncio.sleep(0.001)
    assert await chat.store.taken_in(conversation, positions=[first]) == {}, "it waits"
    assert len(chat.inputs) == 1

    assert chat.gate is not None
    chat.gate.set()
    await chat.until(lambda: len(chat.inputs) == 2, what="what waited was taken in")
    await chat.idle()
    assert _texts(chat.inputs[1]) == ["actually Saturday", "and at seven"]
    assert chat.clock.slept == [_START.total_seconds()], (
        "taken in at once when the activation ended, with no second start wait"
    )


class _HeldQuery(FakeConversationStore):
    """A store whose next read of the waiting messages waits for :attr:`release`."""

    def __init__(self) -> None:
        super().__init__()
        self.hold = False
        self.held = asyncio.Event()
        self.release = asyncio.Event()

    async def untaken_messages(
        self, conversation_id: str, *, limit: int = 100
    ) -> tuple[TranscriptMessage, ...]:
        if self.hold:
            self.hold = False
            self.held.set()
            await self.release.wait()
        return await super().untaken_messages(conversation_id, limit=limit)


async def test_a_message_and_a_signal_during_the_read_of_what_waits_extend_the_wait() -> None:
    """§5:1-§5:2: the wait is read again after the read, its cap still the first's."""
    store = _HeldQuery()
    chat = _Reader(store=store)
    conversation = await chat.conversation()
    await chat.say(conversation, "book Riverside")
    store.hold = True
    await chat.clock.wake()
    await asyncio.wait_for(store.held.wait(), _SETTLE)

    chat.clock.now = 1.6
    await chat.say(conversation, "for Saturday")
    chat.reader.composing(conversation)
    store.release.set()
    await chat.clock.wake()
    await chat.idle()

    (taken,) = chat.inputs
    assert _texts(taken) == ["book Riverside", "for Saturday"]
    assert chat.taken_at == [pytest.approx(1.6 + _LAPSE.total_seconds())], (
        "held until the signal lapsed"
    )
