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
:meth:`Household.post` writes one and waits for nothing; :meth:`Household.say_unstored`
writes one whose episode the store refuses, a work for a person the hub does not admit
(ADR-0383 §2:3, §4:1), and reads back the record it tried to write.

**What the hub recorded, and what it did** is a :class:`Work`: the frozen episode, its
trigger's senders, the sender each line message records, the facts the work started
with and stands at, what every reader reads of them (:attr:`Work.reads`: whose work it is
and whose authority it carries, ADR-0368 §9:1, §9:5), the ``work_facts_recorded`` log
entries (:func:`~ai_assistant.orchestration.work_facts.log_facts`), the planning rounds
the work ran, as the planner was asked them (:attr:`Work.rounds`: what each was shown,
and what each call it proposed came back with), and the replies it wrote. A case hands
:class:`Household` a ``planner`` to propose calls of its own; by default each work's first
round sends one reply and its second ends it.

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

from channel_receiver_contract import event_input
from phases_support import (
    episodes,
    event,
    frozen,
    input_of,
    phases_harness,
    processing,
    replies,
    until,
)
from structlog.testing import capture_logs
from telegram_support import CASE_START_WAIT, REFERENCE, YieldingTelegram
from telegram_support import text as line_update
from test_engine import AT as HARNESS_AT
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.device_context import serving_device
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    ChatDevice,
    DeviceAccess,
    EpisodicMemory,
    InputSender,
    LinkAct,
    LinkActHow,
    LinkWriteKind,
    MessageAuthor,
    RequestingDevice,
    Sureness,
    TelegramForwardKind,
    TelegramForwardOrigin,
    TextChannelPayload,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.orchestration.telegram import TelegramLineSeams, line_channel
from ai_assistant.orchestration.work_facts import (
    chat_account,
    held_senders,
    line_account,
    persons_authority,
    persons_work,
)
from ai_assistant.testing import (
    FakeIdentityStore,
    FakeMemoryStore,
    FakeModelProvider,
    FakePersonModelStore,
    FakeTelegramBotClient,
    FakeTelegramIntakeRecord,
    FakeToolCallingCompleter,
)
from ai_assistant.testing.tool_calling import DEFAULT_ROUND_TEXT

if TYPE_CHECKING:
    from collections.abc import Callable, MutableMapping, Sequence
    from types import TracebackType

    from test_engine import Harness

    from ai_assistant.core.types import (
        EpisodeProcessingRecord,
        LinkWrite,
        MemoryRecord,
        MemoryWrite,
        WorkFacts,
    )
    from ai_assistant.testing.tool_calling import RoundCall, RoundReply

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

#: The event a capture logs for an episode write it could not keep.
_CAPTURE_DEGRADED: Final = "activation_capture_degraded"

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
        logged: Each ``work_facts_recorded`` log entry the work wrote, in order: what was
            decided of it.
        replies: What the work wrote back where the message came from, in order.
        rounds: Each planning round the work ran, as the planner was asked it: what it
            was shown, and the calls the rounds before it proposed, with their results.
        understood: Each understanding call the work made, as its user message: what
            understanding was shown (ADR-0353 §2).
        stored: Whether the store holds the episode. ``False`` for a work whose episode
            write was refused (:meth:`Household.say_unstored`): ``episode`` is then the
            open record its admission tried to write, which the store never held.
        losses: Each ``activation_capture_degraded`` log entry the work wrote, for a
            work read by :meth:`Household.say_unstored`: what its capture could not keep.
    """

    episode: EpisodicMemory
    logged: tuple[MutableMapping[str, Any], ...]
    replies: tuple[str, ...]
    rounds: tuple[RoundCall, ...] = ()
    understood: tuple[str, ...] = ()
    stored: bool = True
    losses: tuple[MutableMapping[str, Any], ...] = ()

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
    def reads(self) -> tuple[str | None, str | None]:
        """What every reader reads of the work's facts as they stand (ADR-0368 §9).

        Whose work it is, where it is a person's (§9:5), and whose authority it carries,
        where it carries a person's (§9:1): the person block, spawn's offer, an approval
        request's person and the person's running work read the first; the stop call, a
        yes, a task's author and its cancel and replace the second.
        """
        facts = self.facts_now
        senders = held_senders(self.record.trigger, self.record.joined)
        return persons_work(facts, senders), persons_authority(facts, senders)

    @property
    def briefing(self) -> str:
        """What the work's first planning round was shown (ADR-0356 §3)."""
        return self.rounds[0].exchange.briefing


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

    def __init__(
        self, planner: RoundReply | None = None, *, people: FakePersonModelStore | None = None
    ) -> None:
        """Build the household: the owner alone, no account linked, the line wired.

        Args:
            planner: What planning proposes in each round; by default one reply in a
                work's first round and nothing in its second.
            people: The person-model store the person blocks are assembled from, and a
                work that is no person's reads a name from (ADR-0375 §6:3); none wired
                by default.
        """
        self.identities = FakeIdentityStore()
        self.understanding = FakeModelProvider(reply=STATED_PROPOSAL)
        self.planner = FakeToolCallingCompleter(response=planner or replies(DEFAULT_ROUND_TEXT))
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
        self.memory = _WitnessedMemory(now=lambda: HARNESS_AT)
        knobs: dict[str, Any] = {"memory": self.memory}
        if people is not None:
            knobs["person_blocks"] = PersonBlocks(store=people, memory=self.memory)
        self.harness: Harness = phases_harness(
            self.planner,
            identities=self.identities,
            telegram=line,
            understanding=understanding_stage(model=self.understanding),
            **knobs,
        )
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

    async def forward(self, account: TelegramAccount, words: str) -> Work:
        """Forward ``words`` on the line from ``account``, as Sam's, and read its work.

        A forward's sender is who forwarded it, by the account it arrived by, and its
        words are Sam's, claimed (ADR-0351 §2:7, §4:2).

        Raises:
            AssertionError: If not exactly one work ends for it.
        """
        origin = TelegramForwardOrigin(kind=TelegramForwardKind.USER, name="Sam", account_id=5)

        async def forwarded() -> None:
            number = next(self._ids)
            self.bot.hold(
                line_update(
                    number, words, sender=account.user_id, chat=account.user_id, forward=origin
                )
            )

        return await self._one_work(forwarded)

    async def say(self, account: HouseholdAccount, words: str) -> Work:
        """Write ``words`` from ``account``, and read what the hub recorded of its work.

        Raises:
            AssertionError: If not exactly one work ends for it.
        """
        return await self._one_work(lambda: self.post(account, words))

    async def say_unstored(self, account: HouseholdAccount, words: str) -> Work:
        """Write ``words`` from ``account``, for a work whose episode write is refused.

        A work for a person the hub does not admit writes no episode in this milestone
        (ADR-0383 §2:3, §4:1): the store refuses the admission's write of its open
        episode, capture ends there, and the work runs and answers all the same. The
        :class:`Work` read back holds that refused record, as
        :class:`_WitnessedMemory` kept it: its trigger, senders and facts are what the
        work was admitted with. It is ``stored=False``.

        Raises:
            AssertionError: If not exactly one work ends for it, or the store holds any
                episode of it.
        """
        before = {one.id for one in await episodes(self.memory)}
        refused_before = len(self.memory.refused)
        planned_before = len(self.planner.calls)
        understood_before = len(self.understanding.calls)
        sent_before = len(self.bot.messages)
        written_before = len(await self._replies())
        with capture_logs() as logs:
            await self.post(account, words)

            def tried() -> list[EpisodicMemory]:
                return [
                    one
                    for one in self.memory.refused[refused_before:]
                    if isinstance(one, EpisodicMemory)
                ]

            async def done() -> bool:
                answered = len(self.bot.messages) > sent_before or (
                    len(await self._replies()) > written_before
                )
                return bool(tried()) and answered and await self._idle()

            await until(done, what="the work to end")
        (episode,) = tried()
        assert {one.id for one in await episodes(self.memory)} == before
        activation = processing(episode).activation_id
        line = processing(episode).trigger.channel == line_channel(REFERENCE, LINE_CHAT)
        return Work(
            episode=episode,
            logged=tuple(
                one
                for one in logs
                if one["event"] == _FACTS_LOGGED and one["activation_id"] == activation
            ),
            replies=(
                tuple(body for _, body in self.bot.messages[sent_before:])
                if line
                else tuple(await self._replies())[written_before:]
            ),
            rounds=tuple(self.planner.calls[planned_before:]),
            understood=tuple(
                one.messages[-1].content for one in self.understanding.calls[understood_before:]
            ),
            stored=False,
            losses=tuple(one for one in logs if one["event"] == _CAPTURE_DEGRADED),
        )

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

    async def report(self, words: str) -> Work:
        """A connected source pushes ``words`` as an informational event: no person sent it.

        Raises:
            AssertionError: If not exactly one work ends for it.
        """

        async def pushed() -> None:
            await event(
                self.harness,
                event_input().model_copy(update={"payload": TextChannelPayload(text=words)}),
            )

        return await self._one_work(pushed)

    # --- reading back -----------------------------------------------------------------

    async def works(self) -> list[Work]:
        """Every work that has ended, in the store's order, with no logs or replies."""
        return [Work(one, (), ()) for one in await frozen(self.harness)]

    async def _one_work(self, write: Callable[[], Any]) -> Work:
        before = {one.id for one in await frozen(self.harness)}
        planned_before = len(self.planner.calls)
        understood_before = len(self.understanding.calls)
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
        return Work(
            episode=episode,
            logged=entries,
            replies=replies,
            rounds=tuple(self.planner.calls[planned_before:]),
            understood=tuple(
                one.messages[-1].content for one in self.understanding.calls[understood_before:]
            ),
        )

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


class _WitnessedMemory(FakeMemoryStore):
    """The canonical fake memory store, keeping each record a write of it refused.

    It refuses exactly what the fake refuses, and raises as it raises; it only keeps the
    record, so a case can read what a work tried to write where the store kept nothing
    of it (:meth:`Household.say_unstored`).

    Attributes:
        refused: Every record an ``add`` or a ``write_atomic`` was refused for, in order.
    """

    def __init__(self, **knobs: Any) -> None:
        super().__init__(**knobs)
        self.refused: list[MemoryRecord] = []

    async def add(self, record: MemoryRecord) -> str:
        """The fake's ``add``, keeping ``record`` where it is refused."""
        try:
            return await super().add(record)
        except MemoryStoreError:
            self.refused.append(record)
            raise

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        """The fake's ``write_atomic``, keeping each record of a refused batch."""
        try:
            return await super().write_atomic(writes)
        except MemoryStoreError:
            self.refused.extend(one.record for one in writes)
            raise


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
