"""The command line on the chat space (ADR-0293 §2-§5, §8, §11; ADR-0296 §6).

Every case drives the adapter against :class:`FakeAssistantEngine`, whose chat space
is the canonical conversation store, so what a command did is read back from the
store rather than inferred from what the terminal printed.
"""

from __future__ import annotations

import asyncio
from io import StringIO
from typing import TYPE_CHECKING

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import (
    ActivationEnding,
    ChatDevice,
    ConversationState,
    DeviceAccess,
    MessageAuthor,
    MessageReceipt,
    NewMessage,
    UserMessage,
)
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire import TransportError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from pathlib import Path

    from ai_assistant.core.types import ConversationDigest, Identifier, TranscriptPage

HUB = ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)
PHONE = ChatDevice(device_id="phone", access=DeviceAccess.READ)


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=100))
    return buffer


def _flat(rendered: str) -> str:
    """The rendered text with wrapping and continuation markers flowed back."""
    return " ".join(rendered.replace("↳", " ").split())


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object) -> list[None]:
    """Point every command's client at ``engine``, and record each one opened."""
    opened: list[None] = []

    async def _open() -> object:
        opened.append(None)
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)
    return opened


def _lines(*typed: str) -> Callable[[], Awaitable[str | None]]:
    """Lines as typed, then end of input."""
    pending = list(typed)

    async def _next() -> str | None:
        await asyncio.sleep(0)
        return pending.pop(0) if pending else None

    return _next


def _never() -> Callable[[], Awaitable[str | None]]:
    """A terminal nobody types at."""

    async def _next() -> str | None:
        await asyncio.Event().wait()
        return None  # pragma: no cover — never reached

    return _next


async def _until(output: StringIO, text: str) -> None:
    """Wait for ``text`` to be rendered, failing rather than hanging."""
    async with asyncio.timeout(5):
        while text not in _flat(output.getvalue()):  # noqa: ASYNC110 — a console buffer has no event to wait on
            await asyncio.sleep(0.01)


async def _started(engine: FakeAssistantEngine, *devices: ChatDevice) -> str:
    """A conversation started on ``devices`` as "my devices"."""
    await engine.set_my_devices(devices)
    return (await engine.start_conversation()).id


def _calls(engine: FakeAssistantEngine, name: str) -> list[dict[str, object]]:
    return [arguments for called, arguments in engine.calls if called == name]


async def _chat(
    engine: FakeAssistantEngine,
    conversation_id: str | None,
    read_line: Callable[[], Awaitable[str | None]],
    *,
    confirm: bool = True,
    poll_seconds: float = 60.0,
) -> int:
    return await cli._drive_chat(
        engine,
        conversation_id,
        device_id="hub",
        read_line=read_line,
        confirm=lambda: confirm,
        poll_seconds=poll_seconds,
    )


# --- which device this command line is (ADR-0296 §1, ADR-0298 §3) -----------


def test_on_the_hubs_own_machine_the_device_is_hub(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    assert cli._this_device(settings, named=None) == "hub"
    assert cli._this_device(settings, named="hub") == "hub"


def test_on_the_hubs_own_machine_no_other_device_can_be_named(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="cannot name another"):
        cli._this_device(Settings(data_dir=tmp_path), named="phone")


def test_on_another_machine_the_device_is_named(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, remote_hub_address="100.64.0.1")

    assert cli._this_device(settings, named="node-laptop") == "node-laptop"
    with pytest.raises(ConfigurationError, match="--device"):
        cli._this_device(settings, named=None)


# --- opening or starting a conversation (ADR-0293 §2:1, §3) ------------------


async def test_chat_starts_a_conversation_on_my_devices_after_asking_to_add_this_one(
    output: StringIO,
) -> None:
    """§3:2: adding is the user's statement, shown before it is asked, and never silent."""
    engine = FakeAssistantEngine()

    code = await _chat(engine, None, _lines())

    assert code == 0
    assert await engine.my_devices() == (HUB,)
    started = _calls(engine, "start_conversation")
    assert len(started) == 1
    rendered = _flat(output.getvalue())
    assert "This device (hub) is not one of your devices for reading and writing." in rendered
    assert "says its screen is private" in rendered
    assert "Started a conversation:" in rendered
    assert "No messages yet." in rendered


async def test_chat_declined_starts_nothing_and_adds_nothing(output: StringIO) -> None:
    engine = FakeAssistantEngine()

    code = await _chat(engine, None, _lines("never sent"), confirm=False)

    assert code == 0
    assert await engine.my_devices() == ()
    assert _calls(engine, "start_conversation") == []
    assert _calls(engine, "write_message") == []
    assert "Left alone. No device was added." in output.getvalue()


async def test_chat_asks_nothing_where_this_device_already_writes(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    await engine.set_my_devices((HUB,))

    def _refuse() -> bool:
        raise AssertionError

    code = await cli._drive_chat(
        engine, None, device_id="hub", read_line=_lines(), confirm=_refuse, poll_seconds=60
    )

    assert code == 0
    assert len(_calls(engine, "start_conversation")) == 1
    assert "not one of your devices" not in output.getvalue()


async def test_chat_offers_this_device_to_a_conversation_without_it(output: StringIO) -> None:
    """§3:3: a conversation's devices change for that conversation, my devices untouched."""
    engine = FakeAssistantEngine()
    conversation = await _started(engine, PHONE)

    code = await _chat(engine, conversation, _lines("hello"))

    assert code == 0
    digest = await engine.conversation(conversation)
    assert digest is not None
    assert digest.devices == (HUB, PHONE)
    assert await engine.my_devices() == (PHONE,)
    assert "not one of this conversation's devices" in _flat(output.getvalue())
    assert "for this conversation" in _flat(output.getvalue())


@pytest.mark.parametrize("access", [DeviceAccess.WRITE, DeviceAccess.READ])
async def test_chat_offers_both_to_a_device_that_only_writes_or_only_reads(
    output: StringIO, access: DeviceAccess
) -> None:
    """§3:5: a write-only end is not shown the conversation, a read-only one cannot write."""
    engine = FakeAssistantEngine()
    conversation = await _started(engine, ChatDevice(device_id="hub", access=access))
    await engine.chat.append_message(
        conversation, NewMessage(author=MessageAuthor.ASSISTANT, text="the secret plan")
    )

    code = await _chat(engine, conversation, _lines(), confirm=False)

    assert code == 0
    assert "the secret plan" not in output.getvalue()
    assert "for reading and writing" in _flat(output.getvalue())
    assert _calls(engine, "transcript") == []


async def test_chat_started_on_a_write_only_device_asks_first(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    await engine.set_my_devices((ChatDevice(device_id="hub", access=DeviceAccess.WRITE),))

    await _chat(engine, None, _lines())

    assert await engine.my_devices() == (HUB,)
    assert "for reading and writing" in _flat(output.getvalue())


async def test_chat_reports_a_conversation_it_cannot_show(output: StringIO) -> None:
    engine = FakeAssistantEngine()

    code = await _chat(engine, "nobody", _lines("hello"))

    assert code == cli._EXIT_ERROR
    assert "No conversation has the id" in output.getvalue()
    assert _calls(engine, "write_message") == []


# --- a message in (ADR-0293 §4) ---------------------------------------------


async def test_a_typed_line_is_written_as_this_devices_message_and_received(
    output: StringIO,
) -> None:
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)

    code = await _chat(engine, conversation, _lines("", "Book Pinecrest for Friday"))

    assert code == 0
    written = _calls(engine, "write_message")
    assert len(written) == 1  # the blank line sent nothing
    message = written[0]["message"]
    assert isinstance(message, UserMessage)
    assert message.device_id == "hub"
    assert message.text == "Book Pinecrest for Friday"
    assert message.replies_to is None
    assert "received, #1" in output.getvalue()
    page = await engine.transcript(conversation)
    assert page is not None
    assert [entry.position for entry in page.entries] == [1]


async def test_each_message_carries_its_own_id(output: StringIO) -> None:
    """§4:1: the device chooses the id, unique per device — two messages, two ids."""
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)

    await _chat(engine, conversation, _lines("one", "two"))

    ids = {call["message"].message_id for call in _calls(engine, "write_message")}  # type: ignore[attr-defined]
    assert len(ids) == 2
    assert "received, #2" in output.getvalue()


async def test_a_reply_names_the_message_it_replies_to(output: StringIO) -> None:
    """§4:5: replying is how the user corrects the assistant."""
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)
    await engine.chat.append_message(
        conversation, NewMessage(author=MessageAuthor.ASSISTANT, text="Booked Lakeside.")
    )

    await _chat(engine, conversation, _lines("/reply 1 wrong campsite, I meant Pinecrest"))

    (written,) = _calls(engine, "write_message")
    message = written["message"]
    assert isinstance(message, UserMessage)
    assert message.replies_to == 1
    assert message.text == "wrong campsite, I meant Pinecrest"


@pytest.mark.parametrize(
    ("line", "said"),
    [
        ("/reply", "takes a message number"),
        ("/reply x text", "takes a message number"),
        ("/reply 3", "takes a message number"),
        ("/reply 0 text", "takes a message number"),
        ("/reply ² text", "takes a message number"),
        ("/reply 99999999999999999999 text", "takes a message number"),
        ("/stop", "is not a command here"),
    ],
)
async def test_a_command_it_cannot_read_sends_nothing(
    output: StringIO, line: str, said: str
) -> None:
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)

    await _chat(engine, conversation, _lines(line))

    assert _calls(engine, "write_message") == []
    assert said in _flat(output.getvalue())


async def test_a_doubled_slash_sends_a_message_starting_with_one(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)

    await _chat(engine, conversation, _lines("//etc/hosts is the file"))

    (written,) = _calls(engine, "write_message")
    assert written["message"].text == "/etc/hosts is the file"  # type: ignore[attr-defined]


async def test_quit_leaves_before_the_lines_after_it(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)

    code = await _chat(engine, conversation, _lines("/help", "/quit", "not sent"))

    assert code == 0
    assert _calls(engine, "write_message") == []
    assert output.getvalue().count("/reply N <text>") == 2  # on opening, and for /help


async def test_a_message_over_the_size_bound_is_not_sent(output: StringIO) -> None:
    """§4:7: refused with the error on the send, and nothing recorded."""
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)

    await _chat(engine, conversation, _lines("x" * 16_001))

    assert _calls(engine, "write_message") == []
    assert "Not sent: a message is at most 16000 characters" in _flat(output.getvalue())


async def test_a_device_that_is_no_longer_an_end_is_told_so(output: StringIO) -> None:
    """§7:2: only a conversation's devices write in it; the refusal is said plainly."""
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)

    async def _removed_then_typed() -> str | None:
        if not _calls(engine, "set_conversation_devices"):
            await engine.set_conversation_devices(conversation, devices=(PHONE,))
            return "hello?"
        return None

    await _chat(engine, conversation, _removed_then_typed)

    assert "Not sent: this device is not one of this conversation's devices" in _flat(
        output.getvalue()
    )


class _LosesTheFirstSend(FakeAssistantEngine):
    """A hub that records the first send and loses its answer on the way back."""

    async def write_message(
        self, conversation_id: Identifier, *, message: UserMessage
    ) -> MessageReceipt:
        receipt = await super().write_message(conversation_id, message=message)
        if len(_calls(self, "write_message")) == 1:
            msg = "the connection closed"
            raise TransportError(msg)
        return receipt


async def test_a_lost_send_is_sent_again_with_the_same_id(output: StringIO) -> None:
    """§4:2: sending is safe to repeat, so the repeat is the same message, recorded once."""
    engine = _LosesTheFirstSend()
    conversation = await _started(engine, HUB)

    code = await _chat(engine, conversation, _lines("hello"))

    assert code == 0
    first, second = _calls(engine, "write_message")
    assert first["message"] == second["message"]
    assert "received, #1" in output.getvalue()
    page = await engine.transcript(conversation)
    assert page is not None
    assert len(page.entries) == 1


# --- following the conversation (ADR-0293 §5:10-§5:13, §8, §11:1) -----------


async def test_the_assistants_message_is_shown_as_it_arrives(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)

    async def _typed() -> str | None:
        if not _calls(engine, "write_message"):
            return "Is Pinecrest free on Friday?"
        await _until(output, "received, #1")
        await engine.chat.append_message(
            conversation, NewMessage(author=MessageAuthor.ASSISTANT, text="Pinecrest is free.")
        )
        await _until(output, "Pinecrest is free.")
        return None

    code = await _chat(engine, conversation, _typed, poll_seconds=0.01)

    assert code == 0
    rendered = _flat(output.getvalue())
    assert "#2 Assistant" in rendered
    # The message this device sent is received, and not shown a second time.
    assert "#1 You" not in rendered


async def test_a_message_from_another_device_and_a_deletion_are_shown(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    phone = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
    conversation = await _started(engine, HUB, phone)

    async def _typed() -> str | None:
        await engine.write_message(
            conversation,
            message=UserMessage(device_id="phone", message_id="m-1", text="from the phone"),
        )
        await _until(output, "from the phone")
        await engine.delete_message(conversation, position=1)
        await _until(output, "Message #1 was deleted.")
        return None

    await _chat(engine, conversation, _typed, poll_seconds=0.01)

    assert "#1 You (from phone)" in _flat(output.getvalue())


async def test_a_conversation_deleted_elsewhere_ends_the_chat(output: StringIO) -> None:
    """§2:3: the chat ends with the conversation, without waiting for another line."""
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)

    async def _delete_soon() -> None:
        await _until(output, "/reply N <text>")
        await engine.delete_conversation(conversation)

    deleting = asyncio.create_task(_delete_soon())
    code = await _chat(engine, conversation, _never(), poll_seconds=0.01)
    await deleting

    assert code == 0
    assert "This conversation was deleted." in output.getvalue()


async def test_a_device_no_longer_shown_the_conversation_ends_the_chat(
    output: StringIO,
) -> None:
    """§3:5: once this device may only write, it is not shown the conversation."""
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)

    async def _narrow_soon() -> None:
        await _until(output, "/reply N <text>")
        await engine.set_conversation_devices(
            conversation, devices=(ChatDevice(device_id="hub", access=DeviceAccess.WRITE),)
        )

    narrowing = asyncio.create_task(_narrow_soon())
    code = await _chat(engine, conversation, _never(), poll_seconds=0.01)
    await narrowing

    assert code == 0
    assert "This device is no longer shown this conversation." in output.getvalue()


class _NarrowsBeforeTheSnapshot(FakeAssistantEngine):
    """Another device makes this one write-only just before the snapshot is taken."""

    async def transcript(
        self,
        conversation_id: Identifier,
        *,
        before: int | None = None,
        limit: int = 50,
    ) -> TranscriptPage | None:
        if not _calls(self, "set_conversation_devices"):
            await self.set_conversation_devices(
                conversation_id,
                devices=(ChatDevice(device_id="hub", access=DeviceAccess.WRITE),),
            )
        return await super().transcript(conversation_id, before=before, limit=limit)


async def test_reading_taken_away_before_the_snapshot_shows_nothing(output: StringIO) -> None:
    """The snapshot's cursor covers the change, so it is the devices read after it that tell."""
    engine = _NarrowsBeforeTheSnapshot()
    conversation = await _started(engine, HUB)
    await engine.chat.append_message(
        conversation, NewMessage(author=MessageAuthor.ASSISTANT, text="the secret plan")
    )

    code = await _chat(engine, conversation, _lines("hello"))

    assert code == cli._EXIT_ERROR
    assert "the secret plan" not in output.getvalue()
    assert "no longer shown this conversation" in output.getvalue()
    assert _calls(engine, "write_message") == []


async def test_a_fresh_chat_space_is_not_shown_to_a_device_that_cannot_read(
    output: StringIO,
) -> None:
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)
    await engine.set_conversation_devices(
        conversation, devices=(ChatDevice(device_id="hub", access=DeviceAccess.WRITE),)
    )
    view = cli._ChatView(conversation, device_id="hub", cursor=10_000)

    assert await cli._poll_chat(engine, view) is False
    assert "no longer shown this conversation" in output.getvalue()


class _HoldsTheSend(FakeAssistantEngine):
    """A hub that never answers a send, as one whose connection hangs."""

    def __init__(self) -> None:
        super().__init__()
        self.sending = asyncio.Event()

    async def write_message(
        self, conversation_id: Identifier, *, message: UserMessage
    ) -> MessageReceipt:
        self.sending.set()
        await asyncio.Event().wait()
        raise AssertionError  # pragma: no cover — never reached


async def test_a_send_still_waiting_does_not_hold_off_the_end(output: StringIO) -> None:
    """The follower ending ends the chat, and the send is said to be of unknown outcome."""
    engine = _HoldsTheSend()
    conversation = await _started(engine, HUB)

    async def _delete_while_sending() -> None:
        await engine.sending.wait()
        await FakeAssistantEngine.delete_conversation(engine, conversation)

    deleting = asyncio.create_task(_delete_while_sending())
    code = await _chat(engine, conversation, _lines("hello?"), poll_seconds=0.01)
    await deleting

    assert code == 0
    rendered = _flat(output.getvalue())
    assert "This conversation was deleted." in rendered
    assert "may or may not have been received" in rendered


async def test_a_chat_space_started_afresh_is_shown_again(output: StringIO) -> None:
    """A cursor past the newest change means a fresh store: resynchronise from a snapshot."""
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)
    view = cli._ChatView(conversation, device_id="hub", cursor=10_000)

    assert await cli._poll_chat(engine, view) is True

    assert "started afresh" in output.getvalue()
    assert view.cursor < 10_000


class _Working(FakeAssistantEngine):
    """A conversation whose current state is scripted (ADR-0293 §8)."""

    def __init__(self, states: Sequence[ConversationState]) -> None:
        super().__init__()
        self.states = list(states)

    async def conversation(self, conversation_id: Identifier) -> ConversationDigest | None:
        digest = await super().conversation(conversation_id)
        if digest is None or not self.states:
            return digest
        return digest.model_copy(update={"state": self.states.pop(0)})


async def test_working_and_how_it_ended_are_shown_as_they_change(output: StringIO) -> None:
    """§8:2, §8:3: working…, then how it ended — each change shown once."""
    idle = ConversationState()
    working = ConversationState(working=True, activation_id="a-1")
    done = ConversationState(last_ended=ActivationEnding.DONE)
    engine = _Working([idle, working, working, done, done])
    conversation = await _started(engine, HUB)
    view = cli._ChatView(conversation, device_id="hub", cursor=0)

    for _ in range(5):
        await cli._poll_chat(engine, view)

    rendered = output.getvalue()
    assert rendered.count("The assistant is working") == 1
    assert rendered.count("The assistant is done.") == 1
    assert rendered.index("working") < rendered.index("is done")


@pytest.mark.parametrize(
    ("ending", "said"),
    [
        (ActivationEnding.DONE, "The assistant is done."),
        (ActivationEnding.COULDNT_FINISH, "The assistant couldn't finish."),
        (ActivationEnding.INTERRUPTED, "interrupted; send your message again?"),
        (ActivationEnding.STOPPED, "The assistant was stopped."),
    ],
)
def test_every_ending_is_said(output: StringIO, ending: ActivationEnding, said: str) -> None:
    view = cli._ChatView("c-1", device_id="hub", cursor=0)

    view.show_state(ConversationState(last_ended=ending))

    assert said in output.getvalue()


def test_an_idle_conversation_says_nothing_about_the_assistant(output: StringIO) -> None:
    cli._ChatView("c-1", device_id="hub", cursor=0).show_state(ConversationState())

    assert output.getvalue() == ""


# --- reading a conversation (ADR-0293 §5) ------------------------------------


async def test_a_conversation_shows_its_devices_state_and_messages(output: StringIO) -> None:
    engine = _Working([ConversationState(last_ended=ActivationEnding.INTERRUPTED)])
    conversation = await _started(engine, HUB, PHONE)
    await engine.write_message(
        conversation, message=UserMessage(device_id="hub", message_id="m-1", text="first")
    )
    await engine.chat.append_message(
        conversation,
        NewMessage(author=MessageAuthor.ASSISTANT, text="line one\nline two", cut_off=True),
    )
    await engine.write_message(
        conversation,
        message=UserMessage(device_id="hub", message_id="m-2", text="again", replies_to=1),
    )
    await engine.delete_message(conversation, position=1)

    code = await cli._drive_show_conversation(engine, conversation, before=None, limit=50)

    assert code == 0
    rendered = _flat(output.getvalue())
    assert "hub — reads and writes" in rendered
    assert "phone — reads only" in rendered
    assert "interrupted; send your message again?" in rendered
    assert "#1 · deleted" in rendered
    assert "#2 Assistant" in rendered
    assert "│ line one" in rendered
    assert "│ line two" in rendered
    assert "Cut off before it finished" in rendered
    assert "replying to #1, a deleted message" in rendered


async def test_a_reply_to_a_deleted_message_older_than_the_page_says_so(
    output: StringIO,
) -> None:
    """§5:8: the reference names a deleted message wherever the message was."""
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)
    await engine.write_message(
        conversation, message=UserMessage(device_id="hub", message_id="m-1", text="oops")
    )
    await engine.write_message(
        conversation,
        message=UserMessage(device_id="hub", message_id="m-2", text="fixed", replies_to=1),
    )
    await engine.delete_message(conversation, position=1)

    await cli._drive_show_conversation(engine, conversation, before=None, limit=1)
    assert "replying to #1, a deleted message" in _flat(output.getvalue())
    output.truncate(0)
    output.seek(0)
    await _chat(engine, conversation, _lines())

    assert "replying to #1, a deleted message" in _flat(output.getvalue())


async def test_a_reply_arriving_to_a_deleted_message_says_so(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    phone = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
    conversation = await _started(engine, HUB, phone)
    await engine.write_message(
        conversation, message=UserMessage(device_id="phone", message_id="m-1", text="oops")
    )
    await engine.delete_message(conversation, position=1)
    view = cli._ChatView(conversation, device_id="hub", cursor=0)
    await engine.write_message(
        conversation,
        message=UserMessage(device_id="phone", message_id="m-2", text="fixed", replies_to=1),
    )
    view.cursor = (await engine.chat_changes(after=0)).next_after - 1

    await cli._poll_chat(engine, view)

    assert "replying to #1, a deleted message" in _flat(output.getvalue())


async def test_a_conversation_reads_further_back(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)
    for n in range(1, 4):
        await engine.write_message(
            conversation, message=UserMessage(device_id="hub", message_id=f"m-{n}", text=f"n{n}")
        )

    await cli._drive_show_conversation(engine, conversation, before=None, limit=1)
    assert "--before 3" in _flat(output.getvalue())
    output.truncate(0)
    output.seek(0)
    await cli._drive_show_conversation(engine, conversation, before=3, limit=5)

    rendered = _flat(output.getvalue())
    assert "n1" in rendered
    assert "n2" in rendered
    assert "n3" not in rendered


async def test_a_conversation_it_cannot_show_is_reported(output: StringIO) -> None:
    code = await cli._drive_show_conversation(
        FakeAssistantEngine(), "nobody", before=None, limit=50
    )

    assert code == cli._EXIT_ERROR
    assert "No conversation has the id" in output.getvalue()


async def test_starting_a_conversation_says_where_it_is_shown(output: StringIO) -> None:
    engine = FakeAssistantEngine()

    assert await cli._drive_start_conversation(engine) == 0
    assert "shown on no device" in _flat(output.getvalue())
    output.truncate(0)
    output.seek(0)
    await engine.set_my_devices((HUB,))
    await cli._drive_start_conversation(engine)

    rendered = _flat(output.getvalue())
    assert "hub — reads and writes" in rendered
    assert "assistant chat -c" in rendered


# --- deleting (ADR-0293 §2:3, §2:7, §5:8, §5:9) ------------------------------


async def test_deleting_a_message_shows_it_then_deletes_it_alone(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)
    await engine.write_message(
        conversation, message=UserMessage(device_id="hub", message_id="m-1", text="oops")
    )
    await engine.write_message(
        conversation,
        message=UserMessage(device_id="hub", message_id="m-2", text="kept", replies_to=1),
    )
    shown: list[str] = []

    def _confirm() -> bool:
        shown.append(output.getvalue())
        return True

    code = await cli._drive_delete_message(engine, conversation, 1, confirm=_confirm)

    assert code == 0
    assert "oops" in shown[0]
    assert "a reply to it stays" in _flat(shown[0])
    assert "The assistant's memory is not changed" in _flat(shown[0])
    page = await engine.transcript(conversation)
    assert page is not None
    assert [type(entry).__name__ for entry in page.entries] == [
        "DeletedMessage",
        "TranscriptMessage",
    ]


async def test_deleting_a_reply_shows_its_target_was_deleted(output: StringIO) -> None:
    """§5:8, in the preview: the reply being deleted names a deleted message."""
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)
    await engine.write_message(
        conversation, message=UserMessage(device_id="hub", message_id="m-1", text="oops")
    )
    await engine.write_message(
        conversation,
        message=UserMessage(device_id="hub", message_id="m-2", text="fixed", replies_to=1),
    )
    await engine.delete_message(conversation, position=1)

    await cli._drive_delete_message(engine, conversation, 2, confirm=lambda: False)

    assert "replying to #1, a deleted message" in _flat(output.getvalue())


async def test_deleting_a_message_declined_leaves_it(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)
    await engine.write_message(
        conversation, message=UserMessage(device_id="hub", message_id="m-1", text="kept")
    )

    code = await cli._drive_delete_message(engine, conversation, 1, confirm=lambda: False)

    assert code == 0
    assert _calls(engine, "delete_message") == []
    assert "Nothing was deleted" in output.getvalue()


@pytest.mark.parametrize("position", [1, 2, 2**63 - 1])
async def test_deleting_a_message_that_does_not_stand_asks_nothing(
    output: StringIO, position: int
) -> None:
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)
    await engine.write_message(
        conversation, message=UserMessage(device_id="hub", message_id="m-1", text="gone")
    )
    await engine.delete_message(conversation, position=1)

    def _refuse() -> bool:
        raise AssertionError

    code = await cli._drive_delete_message(engine, conversation, position, confirm=_refuse)

    assert code == cli._EXIT_ERROR
    assert f"holds no message #{position}" in _flat(output.getvalue())


async def test_deleting_a_conversation_forgets_nothing_and_names_forgetting(
    output: StringIO,
) -> None:
    """§2:3, §2:7: deleting and forgetting are offered side by side, never as one."""
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)

    code = await cli._drive_delete_conversation(engine, conversation, confirm=lambda: True)

    assert code == 0
    assert await engine.conversation(conversation) is None
    assert _calls(engine, "forget_conversation") == []
    rendered = _flat(output.getvalue())
    assert "It forgets nothing" in rendered
    assert f"assistant forget-conversation {conversation}" in rendered


async def test_a_deleted_conversation_can_still_be_forgotten(output: StringIO) -> None:
    """§2:5: forgetting reaches the place whether or not the conversation stands."""
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)
    await engine.delete_conversation(conversation)

    await cli._drive_forget_conversation(engine, conversation, confirm=lambda _digest: True)

    assert _calls(engine, "forget_conversation") == [{"conversation_id": conversation}]
    assert "Forgetting it still removes any episodes" in _flat(output.getvalue())


async def test_deleting_a_conversation_declined_leaves_it(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)

    assert await cli._drive_delete_conversation(engine, conversation, confirm=lambda: False) == 0
    assert await engine.conversation(conversation) is not None


# --- devices (ADR-0293 §3) ---------------------------------------------------


async def test_my_devices_are_shown(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    change = cli._device_change(None, None, DeviceAccess.READ_WRITE)

    assert await cli._drive_devices(engine, None, change, confirm=lambda: True) == 0
    assert "Your devices" in output.getvalue()
    assert "none." in output.getvalue()


async def test_adding_to_my_devices_says_what_it_means_first(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    await engine.set_my_devices((PHONE,))
    shown: list[str] = []

    def _confirm() -> bool:
        shown.append(_flat(output.getvalue()))
        return True

    change = cli._device_change(["hub", "watch"], ["phone"], DeviceAccess.READ_WRITE)
    code = await cli._drive_devices(engine, None, change, confirm=_confirm)

    assert code == 0
    assert "says its screen is private" in shown[0]
    assert [one.device_id for one in await engine.my_devices()] == ["hub", "watch"]
    assert "already started keeps its own devices" in _flat(output.getvalue())


async def test_a_device_added_again_takes_the_access_asked(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    await engine.set_my_devices((HUB,))

    change = cli._device_change(["hub"], None, DeviceAccess.READ)
    await cli._drive_devices(engine, None, change, confirm=lambda: True)

    assert await engine.my_devices() == (ChatDevice(device_id="hub", access=DeviceAccess.READ),)


async def test_removing_alone_asks_nothing_and_names_what_was_absent(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    await engine.set_my_devices((HUB, PHONE))

    def _refuse() -> bool:
        raise AssertionError

    change = cli._device_change(None, ["phone", "tablet"], DeviceAccess.READ_WRITE)
    await cli._drive_devices(engine, None, change, confirm=_refuse)

    assert await engine.my_devices() == (HUB,)
    assert "tablet was not one of them." in output.getvalue()


async def test_adding_declined_changes_nothing(output: StringIO) -> None:
    engine = FakeAssistantEngine()

    change = cli._device_change(["hub"], None, DeviceAccess.READ_WRITE)
    await cli._drive_devices(engine, None, change, confirm=lambda: False)

    assert await engine.my_devices() == ()
    assert _calls(engine, "set_my_devices") == []


async def test_a_conversations_devices_change_and_mine_do_not(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    conversation = await _started(engine, HUB)

    change = cli._device_change(["phone"], ["hub"], DeviceAccess.READ)
    code = await cli._drive_devices(engine, conversation, change, confirm=lambda: True)

    assert code == 0
    digest = await engine.conversation(conversation)
    assert digest is not None
    assert digest.devices == (PHONE,)
    assert await engine.my_devices() == (HUB,)
    assert "for this conversation" in _flat(output.getvalue())


async def test_a_full_set_of_devices_adds_nothing(output: StringIO) -> None:
    engine = FakeAssistantEngine()
    full = tuple(ChatDevice(device_id=f"d-{n:02}", access=DeviceAccess.READ) for n in range(64))
    await engine.set_my_devices(full)

    change = cli._device_change(["hub"], None, DeviceAccess.READ_WRITE)
    code = await cli._drive_devices(engine, None, change, confirm=lambda: True)

    assert code == cli._EXIT_ERROR
    assert "holds at most 64" in output.getvalue()
    assert await engine.my_devices() == full


async def test_the_devices_of_a_conversation_it_cannot_show_are_reported(
    output: StringIO,
) -> None:
    change = cli._device_change(None, None, DeviceAccess.READ_WRITE)

    code = await cli._drive_devices(FakeAssistantEngine(), "nobody", change, confirm=lambda: True)

    assert code == cli._EXIT_ERROR
    assert "No conversation has the id" in output.getvalue()


# --- the commands, end to end through Typer -----------------------------------


def test_a_device_named_twice_is_a_usage_error_before_any_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = _wire(monkeypatch, FakeAssistantEngine())

    result = CliRunner().invoke(cli.app, ["my-devices", "--add", "hub", "--remove", "hub"])

    assert result.exit_code == 2
    assert opened == []


def test_a_message_number_out_of_range_is_a_usage_error_before_any_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = _wire(monkeypatch, FakeAssistantEngine())

    for argv in (
        ["delete-message", "c-1", "0", "--yes"],
        ["delete-message", "c-1", str(2**63), "--yes"],
        ["conversation", "c-1", "--before", "0"],
    ):
        assert CliRunner().invoke(cli.app, argv).exit_code == 2, argv
    assert opened == []


def test_chat_through_the_terminal(
    monkeypatch: pytest.MonkeyPatch, output: StringIO, tmp_path: Path
) -> None:
    """The prompt and the lines share the terminal: the prompt first, then the lines."""
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    monkeypatch.setattr(cli, "load_settings", lambda: Settings(data_dir=tmp_path))

    result = CliRunner().invoke(cli.app, ["chat"], input="y\nhello there\n")

    assert result.exit_code == 0, result.output
    (written,) = _calls(engine, "write_message")
    assert written["message"].text == "hello there"  # type: ignore[attr-defined]
    assert "received, #1" in output.getvalue()


def test_chat_refuses_to_guess_the_device_for_a_hub_elsewhere(
    monkeypatch: pytest.MonkeyPatch, output: StringIO, tmp_path: Path
) -> None:
    opened = _wire(monkeypatch, FakeAssistantEngine())
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: Settings(data_dir=tmp_path, remote_hub_address="100.64.0.1"),
    )

    result = CliRunner().invoke(cli.app, ["chat"])

    assert result.exit_code == 1
    assert opened == []
    assert "name this device with --device" in _flat(output.getvalue())


def test_each_command_reaches_the_engine(monkeypatch: pytest.MonkeyPatch, output: StringIO) -> None:
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    runner = CliRunner()

    assert runner.invoke(cli.app, ["my-devices", "--add", "hub", "--yes"]).exit_code == 0
    assert runner.invoke(cli.app, ["start-conversation"]).exit_code == 0
    (started,) = _calls(engine, "start_conversation")
    conversation = next(iter(engine.conversations_held))
    assert runner.invoke(cli.app, ["conversation", conversation]).exit_code == 0
    assert (
        runner.invoke(
            cli.app, ["conversation-devices", conversation, "--add", "phone", "--yes"]
        ).exit_code
        == 0
    )
    assert runner.invoke(cli.app, ["delete-message", conversation, "1", "--yes"]).exit_code == 1
    assert runner.invoke(cli.app, ["delete-conversation", conversation, "--yes"]).exit_code == 0
    assert started == {}
    assert _called(engine) >= {
        "my_devices",
        "set_my_devices",
        "start_conversation",
        "conversation",
        "transcript",
        "set_conversation_devices",
        "delete_conversation",
    }


def _called(engine: FakeAssistantEngine) -> set[str]:
    """The surface methods ``engine`` was called through."""
    return {called for called, _ in engine.calls}
