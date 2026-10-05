"""The engine's half of ADR-0298 §5's route table, §2:6-§2:8, through the engine.

The wire server checks the rows that need only the roster and sets the requesting
device; the engine checks every row that depends on membership of "my devices" or of
a conversation, reading the requesting device (§5:6). Until the cutover nothing sets
a requesting device other than ``hub`` (§9:2), so each case here sets one itself, with
the wire server's own setter, around the call it makes.

Each conversation is set up by the hub's own machine — a call with nothing set —
which passes every row (§3:2), as the cutover's procedure gives devices their
memberships from the local socket (§9:5).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from test_engine import Harness, NoStepPlanner

from ai_assistant.core.device_context import current_requesting_device, serving_device
from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import (
    HUB_REQUESTING_DEVICE,
    ChannelIdentity,
    ChannelInput,
    ChatChanges,
    ChatDevice,
    ConversationStartedChange,
    DataTier,
    DeviceAccess,
    DeviceRole,
    DevicesChangedChange,
    MessageAuthor,
    NewConversation,
    NotificationCandidate,
    RequestingDevice,
    SendOutcome,
    StreamingTextReply,
    TextChannelPayload,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.conversations import ConversationLifecycle
from ai_assistant.orchestration.device_checks import DeviceChecks, device_page
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakeModelProvider,
    FakeNotificationOutbox,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ai_assistant.core.types import Message
    from ai_assistant.orchestration.engine import Engine

_PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
_WATCH: Final = ChatDevice(device_id="watch", access=DeviceAccess.READ)
_PEN: Final = ChatDevice(device_id="pen", access=DeviceAccess.WRITE)

#: The devices as the wire server would set them: no roster role, so what each may do
#: is its membership alone.
PHONE: Final = RequestingDevice(device_id="phone")
WATCH: Final = RequestingDevice(device_id="watch")
PEN: Final = RequestingDevice(device_id="pen")
#: A device in no set and holding no role, as every device is at the cutover (§9:4).
STRANGER: Final = RequestingDevice(device_id="stranger")
#: A device holding the command role and in no set.
CONSOLE: Final = RequestingDevice(device_id="console", roles=frozenset({DeviceRole.COMMANDS}))

_TIMEOUT: Final = timedelta(seconds=5)
_SETTLE: Final = 5.0


def _harness(*, notification_outbox: FakeNotificationOutbox | None = None) -> Harness:
    """An engine whose chat reader is off, so a written message waits."""
    return Harness(
        planner=NoStepPlanner(), chat_reader=False, notification_outbox=notification_outbox
    )


async def _conversation(engine: Engine, *devices: ChatDevice) -> str:
    """A conversation the hub's own machine starts on ``devices`` as "my devices"."""
    await engine.set_my_devices(devices)
    return (await engine.start_conversation()).id


def _said(device: RequestingDevice | ChatDevice, message_id: str, text: str) -> UserMessage:
    return UserMessage(device_id=device.device_id, message_id=message_id, text=text)


async def _refused[T](
    device: RequestingDevice, call: Callable[[], Awaitable[T]], reason: DeviceRefusal
) -> None:
    """``call`` made as ``device`` fails with ADR-0298 §6's refusal, for ``reason``."""
    with serving_device(device), pytest.raises(DeviceRefusedError) as raised:
        await call()
    assert raised.value.reason is reason


async def _as[T](device: RequestingDevice, call: Callable[[], Awaitable[T]]) -> T:
    with serving_device(device):
        return await call()


async def _messages(engine: Engine, conversation_id: str) -> list[TranscriptMessage]:
    page = await engine.transcript(conversation_id)
    assert page is not None
    return [one for one in page.entries if isinstance(one, TranscriptMessage)]


# --- the hub's own machine (§3:2, §2:8) -------------------------------------------


async def test_the_hubs_own_machine_keeps_the_device_a_message_names() -> None:
    """§2:8, §3:2: as ``hub`` a message is recorded under the device it names."""
    engine = _harness().engine
    conversation = await _conversation(engine, _PHONE)
    receipt = await _as(
        HUB_REQUESTING_DEVICE,
        lambda: engine.write_message(conversation, message=_said(_PHONE, "m-1", "hi")),
    )
    assert receipt.outcome is SendOutcome.RECORDED
    stranger = await engine.write_message(conversation, message=_said(STRANGER, "m-1", "hi"))
    assert stranger.outcome is SendOutcome.NOT_AN_END, "the store still answers the hub"


# --- starting (§5 "Starting") -----------------------------------------------------


async def test_starting_needs_a_device_in_my_devices() -> None:
    """§5: any access in "my devices" starts one; a device outside it is refused."""
    engine = _harness().engine
    await engine.set_my_devices([_WATCH])
    started = await _as(WATCH, engine.start_conversation)
    digest = await engine.conversation(started.id)
    assert digest is not None
    assert digest.devices == (_WATCH,)
    before = await engine.recent_conversations()
    await _refused(STRANGER, engine.start_conversation, DeviceRefusal.NO_ROLE)
    await _refused(CONSOLE, engine.start_conversation, DeviceRefusal.NOT_ALLOWED)
    assert await engine.recent_conversations() == before, "a refusal starts nothing"


# --- writing (§2:7, §5 "Writing") ---------------------------------------------------


async def test_a_device_writes_only_under_its_own_id() -> None:
    """§2:7: the message is bound to the requesting device; another id is refused."""
    engine = _harness().engine
    conversation = await _conversation(engine, _PHONE, _PEN)
    receipt = await _as(
        PHONE, lambda: engine.write_message(conversation, message=_said(PHONE, "m-1", "hi"))
    )
    assert (receipt.outcome, receipt.position) == (SendOutcome.RECORDED, 1)
    await _refused(
        PHONE,
        lambda: engine.write_message(conversation, message=_said(PEN, "m-2", "forged")),
        DeviceRefusal.NOT_ALLOWED,
    )
    assert [(one.device_id, one.text) for one in await _messages(engine, conversation)] == [
        ("phone", "hi")
    ]


async def test_writing_needs_an_end_for_writing() -> None:
    """§5: a write-only end writes; a reading end and a stranger are refused."""
    engine = _harness().engine
    conversation = await _conversation(engine, _PEN, _WATCH)
    written = await _as(
        PEN, lambda: engine.write_message(conversation, message=_said(PEN, "m-1", "hi"))
    )
    assert written.position == 1
    await _refused(
        WATCH,
        lambda: engine.write_message(conversation, message=_said(WATCH, "m-1", "hi")),
        DeviceRefusal.NOT_ALLOWED,
    )
    await _refused(
        STRANGER,
        lambda: engine.write_message(conversation, message=_said(STRANGER, "m-1", "hi")),
        DeviceRefusal.NO_ROLE,
    )
    await _refused(
        WATCH,
        lambda: engine.delete_message(conversation, position=1),
        DeviceRefusal.NOT_ALLOWED,
    )
    await _refused(
        WATCH, lambda: engine.delete_conversation(conversation), DeviceRefusal.NOT_ALLOWED
    )
    assert len(await _messages(engine, conversation)) == 1, "a refusal deletes nothing"
    assert await _as(PEN, lambda: engine.delete_message(conversation, position=1))
    assert await _as(PEN, lambda: engine.delete_conversation(conversation))


async def test_a_conversation_the_store_does_not_hold_has_no_ends() -> None:
    """§5:7: an unknown or deleted conversation is refused, not reported as unknown."""
    engine = _harness().engine
    conversation = await _conversation(engine, _PHONE)
    assert await engine.delete_conversation(conversation)
    for call in (
        lambda: engine.write_message(conversation, message=_said(PHONE, "m-1", "hi")),
        lambda: engine.write_message("never-started", message=_said(PHONE, "m-1", "hi")),
        lambda: engine.transcript(conversation),
        lambda: engine.conversation("never-started"),
    ):
        await _refused(PHONE, call, DeviceRefusal.NOT_ALLOWED)


# --- reading one (§5 "Reading one") -------------------------------------------------


async def test_reading_one_needs_an_end_for_reading() -> None:
    """§5: a reading end reads the transcript and the digest; a writing end does not."""
    engine = _harness().engine
    conversation = await _conversation(engine, _PEN, _WATCH)
    page = await _as(WATCH, lambda: engine.transcript(conversation))
    assert page is not None
    digest = await _as(WATCH, lambda: engine.conversation(conversation))
    assert digest is not None
    await _refused(PEN, lambda: engine.transcript(conversation), DeviceRefusal.NOT_ALLOWED)
    await _refused(PEN, lambda: engine.conversation(conversation), DeviceRefusal.NOT_ALLOWED)
    await _refused(STRANGER, lambda: engine.transcript(conversation), DeviceRefusal.NO_ROLE)


# --- reading many (§5 "Reading many") ---------------------------------------------


async def test_a_device_is_listed_only_the_conversations_it_reads() -> None:
    """§5: the listing holds what the device reads, in the listing's own order."""
    engine = _harness().engine
    first = await _conversation(engine, _PHONE)
    await _conversation(engine, _PEN)
    third = await _conversation(engine, _PHONE, _WATCH)
    order = [one.id for one in await engine.recent_conversations()]
    expected = [one for one in order if one in {first, third}]
    listed = await _as(PHONE, engine.recent_conversations)
    assert [one.id for one in listed] == expected
    paged = await _as(PHONE, lambda: engine.recent_conversations(limit=1, offset=1))
    assert [one.id for one in paged] == expected[1:]
    assert [one.id for one in await _as(WATCH, engine.recent_conversations)] == [third]
    assert await _as(CONSOLE, engine.recent_conversations) == (), "a role, and nothing read"
    await _refused(STRANGER, engine.recent_conversations, DeviceRefusal.NO_ROLE)


async def test_a_device_reads_only_the_changes_it_may_see() -> None:
    """§5: ``chat_changes`` answers by the device, and its filter still applies."""
    engine = _harness().engine
    mine = await _conversation(engine, _PHONE)
    theirs = await _conversation(engine, _PEN)
    page = await _as(PHONE, lambda: engine.chat_changes(after=0))
    seen = {one.conversation_id for one in page.changes}
    assert mine in seen
    assert theirs not in seen
    everything = await engine.chat_changes(after=0)
    assert page.next_after == everything.next_after, "the cursor crosses what it passed"
    filtered = await _as(PHONE, lambda: engine.chat_changes(after=0, conversation_ids=["other"]))
    assert {one.conversation_id for one in filtered.changes} == {None}, "my devices' changes"
    await _refused(STRANGER, lambda: engine.chat_changes(after=0), DeviceRefusal.NO_ROLE)


def test_a_device_page_is_restricted_as_the_store_restricts_one() -> None:
    """The named conversations' changes and "my devices"' changes, with the cursor."""
    page = ChatChanges(
        changes=(
            DevicesChangedChange(seq=1, devices=(_PHONE,)),
            ConversationStartedChange(seq=2, conversation_id="a"),
            ConversationStartedChange(seq=3, conversation_id="b"),
        ),
        next_after=9,
    )
    assert device_page(page, None) is page
    kept = device_page(page, ["b"])
    assert [one.seq for one in kept.changes] == [1, 3]
    assert kept.next_after == 9


# --- the legacy turn (§5 "A legacy turn") -----------------------------------------


async def test_a_legacy_turn_needs_both_ends() -> None:
    """§5: no conversation named needs "my devices" for both; a named one, its own."""
    engine = _harness().engine
    await engine.set_my_devices([_PHONE, _WATCH])
    outcome = await _as(PHONE, lambda: engine.converse("hello", timeout=_TIMEOUT))
    assert outcome.conversation_id is not None
    await _refused(
        WATCH, lambda: engine.converse("hello", timeout=_TIMEOUT), DeviceRefusal.NOT_ALLOWED
    )
    written_only = await _conversation(engine, _PEN, _PHONE)
    await engine.set_conversation_devices(
        written_only, devices=[ChatDevice(device_id="phone", access=DeviceAccess.WRITE)]
    )
    await _refused(
        PHONE,
        lambda: engine.converse("hello", timeout=_TIMEOUT, conversation_id=written_only),
        DeviceRefusal.NOT_ALLOWED,
    )
    await _refused(STRANGER, lambda: engine.answer("q-1", accept=True), DeviceRefusal.NO_ROLE)


async def test_a_refused_stream_starts_no_turn() -> None:
    """§5, §6:1: the streamed turns are checked before the turn starts."""
    engine = _harness().engine
    await engine.set_my_devices([_WATCH])
    before = await engine.recent_conversations()

    async def drained(stream: object) -> None:
        async for _ in stream:  # type: ignore[attr-defined]  # an async iterator either way
            pass

    with serving_device(WATCH):
        received = engine.receive_streaming(
            ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="hi")),
            reply=StreamingTextReply(),
            timeout=_TIMEOUT,
        )
        with pytest.raises(DeviceRefusedError) as raised:
            await drained(received)
        assert raised.value.reason is DeviceRefusal.NOT_ALLOWED
        conversed = engine.converse_streaming("hi", timeout=_TIMEOUT)
        with pytest.raises(DeviceRefusedError):
            await drained(conversed)
    assert await engine.recent_conversations() == before


async def test_only_a_conversation_target_is_a_legacy_turn() -> None:
    """§5:2: any other target is spoke traffic, the wire server's alone to check."""
    checks = DeviceChecks(
        ConversationLifecycle(
            conversations=FakeConversationStore(), memory=FakeMemoryStore(), retention=None
        )
    )
    spoke = ChannelIdentity(channel_type="informational_event", instance_id="calendar")
    await checks.receiving(STRANGER, spoke, "receive")
    with pytest.raises(DeviceRefusedError):
        await checks.receiving(
            STRANGER, ChannelIdentity(channel_type="conversation", instance_id="c"), "receive"
        )


# --- the notification poll (§5 "Notification poll") -------------------------------


async def test_a_poll_needs_my_devices_for_reading_and_a_refused_one_takes_nothing() -> None:
    """§5, §6:1: a refused poll leases nothing, so the next poll is handed the entry."""
    outbox = FakeNotificationOutbox()
    await outbox.offer(
        NotificationCandidate(
            candidate_key="k1",
            producer="a-producer",
            notification_class="calendar",
            summary="something the user did not ask for",
            noticed_at=outbox_now(),
            confidence=0.5,
            sensitivity=DataTier.PERSONAL,
        )
    )
    engine = _harness(notification_outbox=outbox).engine
    await engine.set_my_devices([_PEN, _WATCH])
    await _refused(
        PEN,
        lambda: engine.next_notification(budget=timedelta(0)),
        DeviceRefusal.NOT_ALLOWED,
    )
    await _refused(
        STRANGER, lambda: engine.next_notification(budget=timedelta(0)), DeviceRefusal.NO_ROLE
    )
    delivered = await _as(WATCH, lambda: engine.next_notification(budget=timedelta(0)))
    assert delivered is not None


def outbox_now() -> datetime:
    """The wall clock the default outbox reads, which a candidate is noticed at."""
    return datetime.now(UTC)


# --- work that outlives a request (§2:6) ------------------------------------------


class _Witness(FakeModelProvider):
    """A composing model that records the requesting device it was called under."""

    def __init__(self) -> None:
        super().__init__("Hello there.")
        self.seen: list[RequestingDevice] = []

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        self.seen.append(current_requesting_device())
        return await super().complete(messages, model=model)


async def test_the_activation_a_message_starts_does_not_run_as_its_device() -> None:
    """§2:6: the reader's activation runs with the requesting device unset."""
    witness = _Witness()
    harness = Harness(
        planner=NoStepPlanner(),
        composing=ComposingStage(model=witness, streaming=FakeStreamingCompleter()),
        conversation_store=FakeConversationStore(),
    )
    engine = harness.engine
    conversation = await _conversation(engine, _PHONE)
    await _as(PHONE, lambda: engine.write_message(conversation, message=_said(PHONE, "m", "hi")))
    deadline = asyncio.get_running_loop().time() + _SETTLE
    while not any(
        one.author is MessageAuthor.ASSISTANT for one in await _messages(engine, conversation)
    ):
        assert asyncio.get_running_loop().time() < deadline, "the reader never answered"
        await asyncio.sleep(0.001)
    assert witness.seen
    assert all(one == HUB_REQUESTING_DEVICE for one in witness.seen)
