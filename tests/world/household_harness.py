"""A mock household: people, their accounts, and the places they write from (milestone 20).

A test declares a household and drives it through the real engine over the canonical
fakes, then reads back what the hub recorded of each message: who sent it and at what
level (ADR-0366 §4:1, §5:6, ADR-0368 §2:6), and the three facts of the work it started
(ADR-0368 §2:1 to §2:4). It is built so that a case reads as the scenario it states::

    async with Household() as home:
        sam = home.person("sam")
        phone = await home.device(sam, "sams-phone")
        work = await home.say(phone, "What's on today?")

**A person** is an identity in the household's
:class:`~ai_assistant.testing.FakeIdentityStore`. The owner is there from the start
(:attr:`Household.owner`, ADR-0366 §2:5); :meth:`Household.person` adds anyone else
through the fake's test-only :meth:`~ai_assistant.testing.FakeIdentityStore.hold_identity`
seam, which stands in for the later decision that will provide for a second identity
(ADR-0366 §1:3, §2:4). A real hub holds the owner alone until milestone 5.

**An account** is one of today's two kinds, each linked to its person by an act of the
owner's, or left unlinked where the test passes no person:

- :meth:`Household.device`: a device that writes the hub chat, its account the device
  (``conversation``, :func:`~ai_assistant.orchestration.work_facts.chat_account`),
  linked by a ``device`` act. Every device declared is one of "my devices" and an end
  for writing of the household's one conversation, so it can write whether or not a
  link ties it to anyone.
- :meth:`Household.telegram`: a Telegram account on the line, its account the user id
  (``telegram``, :func:`~ai_assistant.orchestration.work_facts.line_account`), linked by
  a ``configured`` act. The line's own chat is :data:`LINE_CHAT`: the owner's Telegram
  account, as ``Settings.telegram_user_id`` names it.

:meth:`Household.lower` and :meth:`Household.withdraw` lower a link and withdraw the
lowering (ADR-0366 §5:5), and :meth:`Household.fault_next_read` makes the store's next
read fail, so the links cannot be read for one message (ADR-0374 §2:1). The hub's own
machine is the device ``hub`` (:data:`~ai_assistant.core.types.HUB_DEVICE_ID`), declared
like any other. Linking an account to someone other than the owner departs
from ADR-0366 §3:3, which lets the owner link only their own accounts until a later
decision says who else may: the harness does it as the fake allows, for the same reason
it holds a second identity.

**A platform** is where a message is written: the hub chat, from any declared device,
written as that device (ADR-0298 §2:7), or the line, through
:class:`~ai_assistant.testing.FakeTelegramBotClient`, which delivers a message from any
sender id in that sender's private chat with the bot. :meth:`Household.say` writes one
and waits for the work it started; :meth:`Household.say_together` writes several into
one start wait (ADR-0332 §5:1), so they are one input of one work (ADR-0368 §4:5);
:meth:`Household.post` writes one and waits for nothing.

**What the hub recorded** is a :class:`Work`: the frozen episode, its trigger's senders,
the sender each line message records, the facts the work started with and stands at,
and the ``work_facts_recorded`` log entries that compare them with today's path
(:func:`~ai_assistant.orchestration.work_facts.log_facts`), which still decides whom a
work is for until the readers switch (ADR-0368 §1:3).

**To add a scenario:** declare the people and accounts it names, say what each says,
and assert on the :class:`Work` that comes back. **To add a kind of account:** a
dataclass holding its account and link, a declaring method linking it by the owner's
act, and a branch in :meth:`Household.post` writing through that kind's reader, which
finds the sender itself; the harness never decides a sender.

**What it cannot show.** It proves the hub's rules over fakes, not how a real platform
behaves: a real Telegram's ids, a gateway's device registration and a device's
enrolment are not here, and every link is written straight into the fake store rather
than by the act a running hub records it from. Whatever a platform's own gate drops
never reaches the engine here either: the line takes in only its configured account's
messages in its own chat (ADR-0323 §5:1, ``TelegramReader._own``), so a message from
any other Telegram account, linked or not, is dropped before the hub reads a sender for
it, and a case that sends one shows that and nothing more. A work that an input joins
while it runs (an absorption or a take, ADR-0349 §7) is not driven: several inputs
join here only by sharing a start wait.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final, Self

from phases_support import frozen, input_of, phases_harness, processing, until
from structlog.testing import capture_logs
from telegram_support import CASE_START_WAIT, REFERENCE, YieldingTelegram
from telegram_support import text as line_update

from ai_assistant.core.device_context import serving_device
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    ChatDevice,
    DeviceAccess,
    InputSender,
    LinkAct,
    LinkActHow,
    LinkWriteKind,
    MessageAuthor,
    RequestingDevice,
    Sureness,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.orchestration.telegram import TelegramLineSeams, line_channel
from ai_assistant.orchestration.work_facts import chat_account, line_account
from ai_assistant.testing import (
    FakeIdentityStore,
    FakeTelegramBotClient,
    FakeTelegramIntakeRecord,
)

if TYPE_CHECKING:
    from collections.abc import Callable, MutableMapping
    from types import TracebackType

    from test_engine import Harness

    from ai_assistant.core.types import (
        EpisodeProcessingRecord,
        EpisodicMemory,
        LinkWrite,
        WorkFacts,
    )

__all__ = [
    "LINE_CHAT",
    "Device",
    "Household",
    "Person",
    "TelegramAccount",
    "Work",
]

#: The owner's Telegram account: the line's configured account, and so its chat.
LINE_CHAT: Final = 424242

#: The event every recording of a work's facts is logged under.
_FACTS_LOGGED: Final = "work_facts_recorded"

#: How long the hub chat's start wait is held open while :meth:`Household.say_together`
#: writes: far longer than any write takes, and handed back before the wait is released.
_HELD_START_WAIT: Final = 60.0


@dataclass(frozen=True, slots=True)
class Person:
    """Someone in the household: an identity, by its id (ADR-0366 §2:1).

    Attributes:
        id: The identity's id; the owner's is ``OWNER_PERSON_ID``.
    """

    id: str

    def at(self, level: Sureness) -> InputSender:
        """This person as the sender of an input at ``level``."""
        return InputSender(person=self.id, level=level)


@dataclass(frozen=True, slots=True)
class Device:
    """A device that writes the hub chat, and the link that ties it, if one does.

    Attributes:
        device_id: The device's id, which the message names and the account carries.
        person: Whose device it is linked as; ``None`` where no link ties it.
        link_id: The link's id; ``None`` where no link ties it.
    """

    device_id: str
    person: Person | None
    link_id: str | None

    @property
    def account(self) -> Account:
        """The account its messages arrive by, as the hub chat's reader names it."""
        found = chat_account(self.device_id)
        assert found is not None
        return found


@dataclass(frozen=True, slots=True)
class TelegramAccount:
    """A Telegram account on the line, and the link that ties it, if one does.

    Attributes:
        user_id: The account's Telegram user id, and its private chat with the bot.
        person: Whose account it is linked as; ``None`` where no link ties it.
        link_id: The link's id; ``None`` where no link ties it.
    """

    user_id: int
    person: Person | None
    link_id: str | None

    @property
    def account(self) -> Account:
        """The account its messages arrive by, as the line's reader names it."""
        found = line_account(self.user_id)
        assert found is not None
        return found


type HouseholdAccount = Device | TelegramAccount


@dataclass(frozen=True, slots=True)
class Work:
    """What the hub recorded of one work, once it ended.

    Attributes:
        episode: The work's frozen episode.
        logged: Each ``work_facts_recorded`` log entry the work wrote, in order: the
            facts beside what today's path says of the same work.
        replies: What the work wrote back where the message came from, in order.
    """

    episode: EpisodicMemory
    logged: tuple[MutableMapping[str, Any], ...]
    replies: tuple[str, ...]

    @property
    def record(self) -> EpisodeProcessingRecord:
        """The episode's processing record."""
        return processing(self.episode)

    @property
    def text(self) -> str:
        """The text the work was admitted with."""
        return input_of(self.episode)

    @property
    def senders(self) -> tuple[InputSender, ...]:
        """Who sent its input: each distinct sender, at the lowest level it came at."""
        return self.record.trigger.senders

    @property
    def message_senders(self) -> tuple[InputSender | None, ...]:
        """The sender each message records, where its kind records messages (the line)."""
        return tuple(one.sender for one in self.record.trigger.messages)

    @property
    def facts(self) -> WorkFacts | None:
        """The three facts the work started with."""
        return self.record.facts

    @property
    def facts_now(self) -> WorkFacts | None:
        """The three facts as they stand, after every input that joined it."""
        return self.record.facts_now

    @property
    def disagrees(self) -> tuple[str, ...]:
        """Which facts today's path says otherwise, when the work started."""
        (entry,) = [one for one in self.logged if one["at"] == "start"]
        return tuple(entry["differs"])


class Household:
    """An engine over the canonical fakes, with the people and accounts a test declares.

    Used as an async context manager: entering starts the engine, so the line polls,
    and leaving closes it.

    Attributes:
        identities: The identity store the engine reads who sent each message from.
        owner: The owner, held from the start.
        bot: The fake Telegram the line polls and writes through.
        harness: The engine and the fakes behind it.
    """

    def __init__(self) -> None:
        """Build the household: the owner alone, no account linked, the line wired."""
        self.identities = FakeIdentityStore()
        self.owner = Person(OWNER_PERSON_ID)
        self.bot = FakeTelegramBotClient(chat_id=LINE_CHAT, first_message_id=700)
        line = TelegramLineSeams(
            client=YieldingTelegram(self.bot),
            intake=FakeTelegramIntakeRecord(),
            reference=REFERENCE,
            poll_wait=timedelta(seconds=1),
            poll_bound=timedelta(seconds=2),
            send_bound=timedelta(seconds=1),
            start_wait=CASE_START_WAIT,
        )
        self.harness: Harness = phases_harness(identities=self.identities, telegram=line)
        self._devices: list[ChatDevice] = []
        self._conversation: str | None = None
        self._ids = count(1)

    async def __aenter__(self) -> Self:
        """Start the engine, so the line's reader polls."""
        await self.harness.engine.start()
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        """Close the engine."""
        await self.harness.engine.aclose()

    # --- people and accounts ----------------------------------------------------------

    def person(self, name: str) -> Person:
        """Someone other than the owner, held as an identity of their own.

        Args:
            name: A short name; the identity's id is ``person:<name>``.

        Returns:
            The person.
        """
        held = Person(f"person:{name}")
        self.identities.hold_identity(held.id)
        return held

    async def device(self, person: Person | None, device_id: str) -> Device:
        """A device that writes the hub chat, linked to ``person`` by the owner's act.

        Args:
            person: Whose device to link it as; ``None`` leaves it linked to no one.
            device_id: The device's id.

        Returns:
            The device.
        """
        made = Device(device_id=device_id, person=person, link_id=None)
        if person is not None:
            link_id = await self._link(person, made.account, LinkActHow.DEVICE)
            made = Device(device_id=device_id, person=person, link_id=link_id)
        self._devices.append(ChatDevice(device_id=device_id, access=DeviceAccess.READ_WRITE))
        engine = self.harness.engine
        await engine.set_my_devices(self._devices)
        if self._conversation is not None:
            await engine.set_conversation_devices(self._conversation, devices=self._devices)
        return made

    async def telegram(self, person: Person | None, user_id: int = LINE_CHAT) -> TelegramAccount:
        """A Telegram account on the line, linked to ``person`` by the owner's act.

        Args:
            person: Whose account to link it as; ``None`` leaves it linked to no one.
            user_id: Its Telegram user id; the line's own account by default.

        Returns:
            The account.
        """
        made = TelegramAccount(user_id=user_id, person=person, link_id=None)
        if person is None:
            return made
        link_id = await self._link(person, made.account, LinkActHow.CONFIGURED)
        return TelegramAccount(user_id=user_id, person=person, link_id=link_id)

    async def _link(self, person: Person, account: Account, how: LinkActHow) -> str:
        act = LinkAct(how=how, by=OWNER_PERSON_ID)
        return _written(await self.identities.link(person.id, account, act=act))

    async def lower(
        self, account: HouseholdAccount, level: Sureness, *, by: Person | None = None
    ) -> str:
        """Lower ``account``'s link to ``level`` (ADR-0366 §5:5).

        Args:
            account: A linked account.
            level: The level to lower it to, below its kind's most.
            by: Who lowers it; the owner by default.

        Returns:
            The lowering's id, to withdraw it by.
        """
        assert account.link_id is not None, "only a linked account can be lowered"
        maker = by or self.owner
        return _written(await self.identities.lower(account.link_id, level, by=maker.id))

    async def withdraw(self, lowering_id: str, *, by: Person | None = None) -> None:
        """Withdraw a lowering, by whoever made it; the owner by default."""
        maker = by or self.owner
        _written(await self.identities.withdraw_lowering(lowering_id, by=maker.id))

    def fault_next_read(self) -> None:
        """Make the identity store's next read fail, as a store fault does (ADR-0374 §2:1).

        Through the fake's own one-shot seam
        (:meth:`~ai_assistant.testing.FakeIdentityStore.fail_next`): the next member called
        raises, touching nothing. A message's reader reads each account once, so call it
        right before the one message whose read is to fail.
        """
        self.identities.fail_next()

    # --- writing ----------------------------------------------------------------------

    async def post(self, account: HouseholdAccount, words: str) -> None:
        """Write ``words`` from ``account``, and wait for nothing.

        On the hub chat it is written as the device, which must be an end for writing
        of the conversation (ADR-0298 §2:7); on the line it is held for the next poll,
        from the account in its private chat with the bot.
        """
        number = next(self._ids)
        if isinstance(account, TelegramAccount):
            self.bot.hold(line_update(number, words, sender=account.user_id, chat=account.user_id))
            return
        conversation = await self._the_conversation()
        message = UserMessage(device_id=account.device_id, message_id=f"m-{number}", text=words)
        with serving_device(RequestingDevice(device_id=account.device_id)):
            await self.harness.engine.write_message(conversation, message=message)

    async def say(self, account: HouseholdAccount, words: str) -> Work:
        """Write ``words`` from ``account``, and read what the hub recorded of its work.

        Raises:
            AssertionError: If not exactly one work ends for it.
        """
        return await self._one_work(lambda: self.post(account, words))

    async def say_together(self, *said: tuple[Device, str]) -> Work:
        """Write each message into one start wait of the hub chat, as one work's input.

        The chat's reader takes in everything written while its start wait runs as one
        input (ADR-0332 §5:1), so the messages, from the devices given, start one work
        (ADR-0368 §4:5).

        Raises:
            AssertionError: If not exactly one work ends for them.
        """

        async def written() -> None:
            with self._start_wait_held():
                for device, words in said:
                    await self.post(device, words)

        return await self._one_work(written)

    # --- reading back -----------------------------------------------------------------

    async def works(self) -> list[Work]:
        """Every work that has ended, in the store's order, with no logs or replies."""
        return [Work(one, (), ()) for one in await frozen(self.harness)]

    async def _one_work(self, write: Callable[[], Any]) -> Work:
        before = {one.id for one in await frozen(self.harness)}
        sent_before = len(self.bot.messages)
        written_before = len(await self._replies())
        with capture_logs() as logs:
            await write()
            episode = await self._settled(before)
        line = processing(episode).trigger.channel == line_channel(REFERENCE, LINE_CHAT)
        replies = (
            tuple(body for _, body in self.bot.messages[sent_before:])
            if line
            else tuple(await self._replies())[written_before:]
        )
        entries = tuple(
            one
            for one in logs
            if one["event"] == _FACTS_LOGGED
            and one["activation_id"] == processing(episode).activation_id
        )
        return Work(episode=episode, logged=entries, replies=replies)

    async def _settled(self, before: set[str]) -> EpisodicMemory:
        found: list[EpisodicMemory] = []

        async def done() -> bool:
            found[:] = [one for one in await frozen(self.harness) if one.id not in before]
            return bool(found) and await self._idle()

        await until(done, what="the work to end")
        (episode,) = found
        return episode

    async def _idle(self) -> bool:
        if self._conversation is None:
            return True
        digest = await self.harness.engine.conversation(self._conversation)
        return digest is not None and not digest.state.working

    async def _replies(self) -> list[str]:
        if self._conversation is None:
            return []
        page = await self.harness.conversation_store.transcript(self._conversation, limit=100)
        assert page is not None
        return [
            one.text
            for one in page.entries
            if isinstance(one, TranscriptMessage) and one.author is MessageAuthor.ASSISTANT
        ]

    async def _the_conversation(self) -> str:
        if self._conversation is None:
            assert self._devices, "declare a device before writing the hub chat"
            self._conversation = (await self.harness.engine.start_conversation()).id
        return self._conversation

    def _start_wait_held(self) -> _HeldStartWait:
        reader = self.harness.engine._chat_reader
        assert reader is not None
        return _HeldStartWait(reader)


class _HeldStartWait:
    """Hold the hub chat's start wait open while a case writes, then let it end at once.

    Every write into a held wait joins it, however long the writing takes. Leaving hands
    back the reader's own wait and sleep before the held sleep is released, so the read
    then finds its wait over and takes in everything written as one input.
    """

    def __init__(self, reader: Any) -> None:
        self._reader = reader
        self._over = asyncio.Event()

    def __enter__(self) -> None:
        self._wait, self._sleep = self._reader._start_wait, self._reader._sleep
        over = self._over

        async def held(seconds: float) -> None:
            del seconds
            await over.wait()

        self._reader._start_wait = _HELD_START_WAIT
        self._reader._sleep = held

    def __exit__(self, *_: object) -> None:
        self._reader._start_wait, self._reader._sleep = self._wait, self._sleep
        self._over.set()


def _written(write: LinkWrite) -> str:
    """The record a write made, or an ``AssertionError`` naming why the store refused."""
    assert write.kind is LinkWriteKind.WRITTEN, f"the identity store refused: {write}"
    assert write.record_id is not None
    return write.record_id
