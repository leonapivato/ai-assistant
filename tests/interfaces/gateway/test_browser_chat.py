"""The chat, driven (ADR-0293 §11, ADR-0216 §2).

What the page *does* over time, which the bundle's text cannot say: a message is
*received*, the assistant's reply then arrives on the change stream (ADR-0296 §4,
ADR-0298 §7), a send the conversation refuses offers what would let it through, a
stream that ends stops the following rather than reopening it, a hidden page pauses and
says so, and a device removed from a conversation — or refused for holding no role —
drops what it held. The engine is the canonical fake, whose change stream is the
engine's own; the assistant's reply is written into the chat space the way the chat's
writer writes one (ADR-0293 §6), so nothing about the reply is fabricated at the page.
A conversation's current state is pushed onto the stream by the case
(:meth:`DriveEngine.push_state`), as the engine pushes it when its activity changes.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final

import pytest
from browser_drive import DESKTOP, PHONE, driving
from playwright.async_api import expect

from ai_assistant.core.errors import ConversationStoreError, DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import (
    CHAT_DEVICES_MAX,
    ChatDevice,
    ChatStreamChunk,
    ChatStreamEnd,
    ConversationState,
    DeviceAccess,
    MessageAuthor,
    NewMessage,
)
from ai_assistant.wire.errors import HubUnavailableError

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, Dialog, Locator, Route

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: Long enough for a change to reach the page: the fake reads its store every quarter
#: second, and the gateway relays at once.
_FOLLOWED: Final = 10_000

#: The same, for a case that waits on an ending rather than on a change.
_IDLE_FOLLOWED: Final = 15_000

#: A device of its own, rather than the hub's machine (ADR-0296 §1).
_LAPTOP: Final = "nLAPTOP01CNTRL"


def _follows(drive: Drive) -> list[int]:
    """The cursor of every change stream the page opened, in order."""
    return [
        int(str(arguments["after"]))
        for name, arguments in drive.engine.calls
        if name == "follow_chat"
    ]


async def _followed(drive: Drive, count: int) -> None:
    """Wait, bounded, until the hub has recorded ``count`` change streams.

    Nothing on the page says that yet: it holds its stream from the moment it asks, and
    the gateway writes the stream's head before it asks the hub, so neither
    ``chat.stream`` nor its ``headed`` means the follow has been recorded. The case
    asserts what it counted afterwards, so a follow that never comes still fails it.
    """
    for _ in range(100):
        if len(_follows(drive)) >= count:
            return
        await asyncio.sleep(0.1)


async def _open(drive: Drive, *, devices: tuple[str, ...] = ("hub",)) -> str:
    """Put ``devices`` in "my devices", start a conversation, and open it in the chat."""
    await drive.engine.set_my_devices(
        [ChatDevice(device_id=one, access=DeviceAccess.READ_WRITE) for one in devices]
    )
    started = await drive.engine.start_conversation()
    await drive.page.click("#chat-button")
    await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")
    await _streaming(drive)
    await drive.page.locator("#chat-conversations button.chat-open:not([aria-current])").click()
    await expect(drive.page.locator("#chat-heading")).to_have_text(await _title(drive, started.id))
    # The conversation's opening reads have landed: its state is the last of them.
    await drive.page.wait_for_function("() => chat.state !== null")
    return started.id


async def _title(drive: Drive, conversation: str) -> str:
    """What the page calls a conversation: its start, in this browser's terms."""
    return str(await drive.page.evaluate("(id) => chatTitle(id)", conversation))


def _row(drive: Drive, conversation: str) -> Locator:
    """The listing's row that opens one conversation."""
    return drive.page.locator(f'#chat-conversations [data-conversation="{conversation}"]')


async def _streaming(drive: Drive) -> None:
    """Wait until the page's change stream is open: the gateway answered its head."""
    await drive.page.wait_for_function("() => chat.stream !== null && chat.stream.headed")


async def _send(drive: Drive, text: str) -> None:
    await drive.page.fill("#chat-text", text)
    await drive.page.click("#chat-send")


async def test_a_message_is_received_and_the_reply_arrives_by_following(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§4:4's *received*, then §6's reply reaching the page as a change, with §8's state."""
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.chat_reader = False  # the reply is the case's own
        conversation = await _open(drive)
        await _send(drive, "Book the usual campsite.")

        transcript = drive.page.locator("#chat-transcript")
        await expect(transcript.locator("li").last).to_contain_text("Book the usual campsite.")
        (written,) = [one for name, one in drive.engine.calls if name == "write_message"]
        message = written["message"]
        assert message.device_id == "hub"  # type: ignore[attr-defined]

        drive.engine.push_state(conversation, ConversationState(working=True))
        await expect(drive.page.locator("#chat-state")).to_contain_text(
            "working on this", timeout=_FOLLOWED
        )

        await drive.engine.chat.append_message(
            conversation,
            NewMessage(author=MessageAuthor.ASSISTANT, text="Pinecrest, Friday.", replies_to=1),
        )
        drive.engine.push_state(conversation, ConversationState())
        reply = transcript.locator("li.from-assistant")
        await expect(reply).to_contain_text("Pinecrest, Friday.", timeout=_FOLLOWED)
        await expect(reply).to_contain_text("In reply to: “Book the usual campsite.”")
        await expect(drive.page.locator("#chat-state")).to_be_hidden(timeout=_FOLLOWED)
        # One stream carried all of it: the page asked nothing on a clock.
        assert len(_follows(drive)) == 1
        assert not [name for name, _ in drive.engine.calls if name == "chat_changes"][1:]


async def test_a_send_from_a_device_that_is_not_an_end_says_how_to_add_it(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§7:2: only a conversation's devices write in it; the page says so and how to fix it.

    Changing the conversation's devices is the command line's here; once it is done, the
    resend carries the same message id, so the conversation records it once (§4:2).
    """
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive, devices=())
        await _send(drive, "Hello?")

        pending = drive.page.locator("#chat-transcript li.pending")
        await expect(pending).to_contain_text("not one of this conversation's devices")
        await expect(pending).to_contain_text(
            f"assistant conversation-devices {conversation} --add hub"
        )
        await drive.engine.set_conversation_devices(
            conversation, devices=[ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)]
        )
        await pending.locator("button", has_text="Send again").click()

        await expect(pending).to_have_count(0, timeout=_FOLLOWED)
        await expect(drive.page.locator("#chat-transcript li.from-user")).to_contain_text("Hello?")
        writes = [one for name, one in drive.engine.calls if name == "write_message"]
        assert len(writes) == 2
        assert writes[0]["message"] == writes[1]["message"]


async def test_a_stream_that_fails_stops_and_follows_again_from_its_cursor_when_asked(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0182 §7: nothing is reopened of the page's own motion after a failure; and
    ADR-0296 §4:4: the stream the owner's press opens starts from the last change the
    page applied, so a message written meanwhile arrives and nothing is replayed."""
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.chat_reader = False
        conversation = await _open(drive)
        await drive.engine.chat.append_message(
            conversation, NewMessage(author=MessageAuthor.ASSISTANT, text="Before the failure.")
        )
        transcript = drive.page.locator("#chat-transcript")
        await expect(transcript).to_contain_text("Before the failure.", timeout=_FOLLOWED)
        applied = await drive.page.evaluate("chat.cursor")

        drive.engine.push(ConversationStoreError("the store is unreadable"))
        follow = drive.page.locator("#chat-follow")
        await expect(follow).to_contain_text("Stopped following", timeout=_IDLE_FOLLOWED)
        await expect(drive.page.locator("#chat-follow-again")).to_be_visible()
        await expect(drive.page.locator("#chat .fault")).to_contain_text("declined")
        await drive.engine.chat.append_message(
            conversation, NewMessage(author=MessageAuthor.ASSISTANT, text="While stopped.")
        )
        await drive.page.wait_for_timeout(3_000)
        assert len(_follows(drive)) == 1
        assert drive.engine.open_streams == 0
        await expect(transcript).not_to_contain_text("While stopped.")

        await drive.page.click("#chat-follow-again")
        await expect(follow).to_contain_text("because you asked")
        await expect(drive.page.locator("#chat-follow-again")).to_be_hidden()
        await expect(transcript).to_contain_text("While stopped.", timeout=_FOLLOWED)
        assert _follows(drive)[1] == applied
        await expect(transcript.locator("li", has_text="Before the failure.")).to_have_count(1)


async def test_a_hidden_page_pauses_and_follows_again_when_it_comes_back(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Hiding pauses the following, and coming back resumes it — each said on screen."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        await drive.page.evaluate(
            """() => {
              Object.defineProperty(document, "visibilityState", {
                configurable: true, get: () => "hidden" });
              document.dispatchEvent(new Event("visibilitychange"));
            }"""
        )
        follow = drive.page.locator("#chat-follow")
        await expect(follow).to_contain_text("Paused while this page is hidden")
        assert await drive.page.evaluate("chat.stream === null && !chat.following")
        # The stream went with it, and its hub connection with that.
        for _ in range(50):
            if drive.engine.open_streams == 0:
                break
            await asyncio.sleep(0.1)
        assert drive.engine.open_streams == 0

        await drive.page.evaluate(
            """() => {
              Object.defineProperty(document, "visibilityState", {
                configurable: true, get: () => "visible" });
              document.dispatchEvent(new Event("visibilitychange"));
            }"""
        )
        await expect(follow).to_contain_text("You came back")
        await drive.page.wait_for_function("() => chat.stream !== null")
        await _followed(drive, 2)
        assert len(_follows(drive)) == 2


async def test_a_deleted_message_leaves_its_reply_naming_a_deleted_message(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§5:8: deleting deletes that message alone, and a reply to it says what it named."""
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.chat_reader = False  # the reply is the case's own
        conversation = await _open(drive)
        await _send(drive, "Ericeira.")
        await expect(drive.page.locator("#chat-transcript li.from-user")).to_contain_text(
            "Ericeira."
        )
        await drive.engine.chat.append_message(
            conversation,
            NewMessage(author=MessageAuthor.ASSISTANT, text="Booked.", replies_to=1),
        )
        reply = drive.page.locator("#chat-transcript li.from-assistant")
        await expect(reply).to_contain_text("Booked.", timeout=_FOLLOWED)

        # Registered before the click: `window.confirm` blocks the page's script, so a
        # handler that is already standing is what keeps the click from waiting on it.
        loop = asyncio.get_running_loop()
        answered: asyncio.Future[str] = loop.create_future()
        running: list[asyncio.Task[None]] = []

        async def accept(dialog: Dialog) -> None:
            await dialog.accept()
            answered.set_result(dialog.message)

        drive.page.once("dialog", lambda dialog: running.append(loop.create_task(accept(dialog))))
        await drive.page.locator("#chat-transcript li.from-user button", has_text="Delete").click()
        assert "forgets nothing" in await answered

        await expect(drive.page.locator("#chat-transcript li.from-user")).to_have_count(0)
        await expect(reply).to_contain_text("In reply to a message that was deleted.")
        assert ("delete_message", {"conversation_id": conversation, "position": 1}) in (
            drive.engine.calls
        )


async def test_a_conversation_restored_off_the_listing_is_named_from_its_own_read(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A reload restores the conversation the tab was reading, which may be on a page of
    the listing the page has not read: its name comes from its own read, so the heading
    and any outcome about it name it rather than "this conversation" (adversarial
    review, round 3)."""
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive)
        title = await _title(drive, conversation)

        async def nothing_listed(*, limit: int = 50, offset: int = 0) -> tuple[Any, ...]:
            return ()

        drive.engine.recent_conversations = nothing_listed  # type: ignore[method-assign]
        await drive.page.reload()

        await drive.page.wait_for_function("(id) => chat.selected === id", arg=conversation)
        await expect(drive.page.locator("#chat-heading")).to_have_text(title)
        assert await drive.page.evaluate("(id) => chatName(id)", conversation) == (
            f"the conversation from {title}"
        )


async def test_a_late_forget_answer_names_its_conversation_when_nothing_else_could(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Adversarial review, round 4: the conversation a reload restored is on no page the
    page has listed, and its own read fails, so the page knows no start to name it by.
    A forget answer that lands after another conversation was opened still names the
    one it was about — by the hub's id, the one name left — and never "this
    conversation", which would now be the other one."""
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive)
        other = (await drive.engine.start_conversation()).id
        listed = await drive.engine.recent_conversations()
        real_read = drive.engine.conversation

        async def only_the_other(*, limit: int = 50, offset: int = 0) -> tuple[Any, ...]:
            return tuple(one for one in listed if one.id == other)

        async def failing_for_it(conversation_id: str) -> Any:
            if conversation_id == conversation:
                msg = "the store could not be read"
                raise ConversationStoreError(msg)
            return await real_read(conversation_id)

        drive.engine.recent_conversations = only_the_other  # type: ignore[method-assign]
        drive.engine.conversation = failing_for_it  # type: ignore[method-assign]
        await drive.page.reload()
        await drive.page.wait_for_function("(id) => chat.selected === id", arg=conversation)
        await expect(drive.page.locator("#chat-heading")).to_have_text("This conversation")

        await drive.page.evaluate(_HOLDING, "/conversation/forget")
        drive.page.once("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))
        await drive.page.click("#chat-thread .chat-about > summary")
        await drive.page.click("#chat-forget")
        await drive.page.wait_for_function("() => window.__held.reached")
        await _row(drive, other).click()
        await drive.page.wait_for_function("(id) => chat.selected === id", arg=other)
        await drive.page.evaluate("() => window.__held.release()")

        said = drive.page.locator("#chat-said")
        await expect(said).to_contain_text(f"conversation {conversation}", ignore_case=True)
        await expect(said).not_to_contain_text("this conversation", ignore_case=True)


async def test_a_long_listing_is_named_in_one_pass(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Names are looked up, not searched for: five thousand conversations started in
    distinct minutes are known and named well inside a second's work, where telling
    each apart against every other took seconds for a fifth as many (adversarial
    review, round 3)."""
    async with driving(gateway_browser, tmp_path) as drive:
        spent = await drive.page.evaluate(
            """() => {
              const summaries = Array.from({ length: 5000 }, (_, n) => ({
                id: `c-${n}`,
                started_at: new Date(Date.UTC(2026, 0, 1) + n * 60000).toISOString(),
              }));
              const began = performance.now();
              knowStarts(summaries);
              const names = new Set(summaries.map((one) => conversationName(one.id)));
              return { ms: performance.now() - began, distinct: names.size };
            }"""
        )

    assert spent["distinct"] == 5000
    assert spent["ms"] < 2000, spent


async def test_a_send_whose_answer_was_lost_is_shown_once_it_is_recorded(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§4:2: a send the page got no answer to, which the hub did record, is not shown twice.

    The hub records the message and the answer never reaches the page (a transport
    failure past the write). The page says it does not know, and when following brings
    the message in it is matched by this device's message id and shown as recorded.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        held = drive.engine.write_message

        async def lost(conversation_id: str, *, message: Any) -> Any:
            await held(conversation_id, message=message)
            raise HubUnavailableError("the connection went away after the write")

        drive.engine.write_message = lost  # type: ignore[method-assign]
        await _send(drive, "Did this arrive?")
        pending = drive.page.locator("#chat-transcript li.pending")
        await expect(pending).to_contain_text("not known whether this arrived")

        await expect(pending).to_have_count(0, timeout=_IDLE_FOLLOWED)
        await expect(drive.page.locator("#chat-transcript li.from-user")).to_have_count(1)


_HIDE_AND_SHOW = """() => {
  for (const state of ["hidden", "visible"]) {
    Object.defineProperty(document, "visibilityState", {
      configurable: true, get: () => state });
    document.dispatchEvent(new Event("visibilitychange"));
  }
}"""


async def test_a_reload_keeps_the_conversation_the_chat_was_reading(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The tab's chat and its conversation survive a reload, as the ask's thread does."""
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive)
        title = await _title(drive, conversation)
        await drive.page.reload()

        await expect(drive.page.locator("#chat-heading")).to_have_text(title)
        assert await drive.page.evaluate("() => chat.selected") == conversation


#: Holds the page's reading of the first answer to ``path`` until the case releases it,
#: after the gateway has answered — so the body released is the gateway's own, read before
#: whatever the case changed meanwhile (``test_browser_conversations``' device).
_HOLDING = """(path) => {
  window.__held = { path: path, reached: false, release: null, open: 0, most: 0 };
  const realFetch = window.fetch;
  window.fetch = async function (resource, options) {
    const asked = typeof resource === "string" ? resource : resource.url;
    const mine = new URL(asked, location.href).pathname === window.__held.path;
    if (mine) {
      window.__held.open += 1;
      window.__held.most = Math.max(window.__held.most, window.__held.open);
    }
    try {
      const response = await realFetch.call(this, resource, options);
      if (mine && !window.__held.reached) {
        window.__held.reached = true;
        await new Promise((resolve) => {
          window.__held.release = resolve;
        });
      }
      return response;
    } finally {
      if (mine) {
        window.__held.open -= 1;
      }
    }
  };
}
"""


async def test_a_transcript_read_before_a_deletion_does_not_bring_the_message_back(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§5:12: a marker the following applied outranks a snapshot read before it."""
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive)
        await _send(drive, "Delete me later.")
        await expect(
            drive.page.locator("#chat-transcript li.from-user:not(.pending)")
        ).to_have_count(1, timeout=_FOLLOWED)
        await drive.page.click("#chat-start")
        await drive.page.wait_for_function(
            "(id) => chat.selected !== null && chat.selected !== id", arg=conversation
        )

        await drive.page.evaluate(_HOLDING, "/chat/transcript")
        await drive.page.locator("#chat-conversations button.chat-open:not([aria-current])").click()
        await drive.page.wait_for_function("() => window.__held.reached")
        await drive.engine.delete_message(conversation, position=1)
        await drive.page.wait_for_function("() => chat.deleted.has(1)", timeout=_IDLE_FOLLOWED)
        await drive.page.evaluate("window.__held.release()")

        await drive.page.wait_for_function("() => !window.__held.open")
        await expect(drive.page.locator("#chat-transcript li.from-user")).to_have_count(0)


async def test_the_page_holds_one_stream_whatever_asks_for_one_meanwhile(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """One change stream at a time (ADR-0182 §7's third clause, for this stream too): a
    send, the network coming back and the page being seen again open no second one."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        await drive.page.wait_for_function("() => chat.stream !== null")
        await _send(drive, "While a stream is open.")
        await expect(drive.page.locator("#chat-transcript li.from-user")).to_contain_text(
            "While a stream is open.", timeout=_FOLLOWED
        )
        await drive.page.evaluate(
            """() => {
              document.dispatchEvent(new Event("visibilitychange"));
              window.dispatchEvent(new Event("online"));
            }"""
        )
        await drive.page.wait_for_timeout(1_000)
        assert len(_follows(drive)) == 1
        assert drive.engine.open_streams == 1


async def test_a_state_read_that_fails_on_opening_stops_the_following(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The read made on opening a conversation is not tried again by the following."""
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.engine.set_my_devices(
            [ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)]
        )
        await drive.engine.start_conversation()
        reads: list[str] = []

        async def failing(conversation_id: str) -> Any:
            reads.append(conversation_id)
            raise ConversationStoreError("the index is unreadable")

        drive.engine.conversation = failing  # type: ignore[method-assign]
        await drive.page.click("#chat-button")
        await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")
        await drive.page.locator("#chat-conversations button.chat-open:not([aria-current])").click()

        await expect(drive.page.locator("#chat-follow")).to_contain_text("Stopped following")
        stopped_at = len(reads)
        await drive.page.wait_for_timeout(5_000)
        assert len(reads) == stopped_at == 1


async def test_following_again_reads_the_state_whose_read_failed(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The state read made as following starts again is not retried when it fails, and
    does not stop the stream; following starting again reads it again even when no
    change has come since."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        held = drive.engine.conversation
        reads: list[str] = []

        async def failing(conversation_id: str) -> Any:
            reads.append(conversation_id)
            raise ConversationStoreError("the index is unreadable")

        drive.engine.conversation = failing  # type: ignore[method-assign]
        # Following starts again on the page being seen again, and reads the state once,
        # since it may have changed while nothing here followed; that read fails.
        await drive.page.evaluate(_HIDE_AND_SHOW)
        await expect(drive.page.locator("#chat .fault")).to_contain_text(
            "declined", timeout=_IDLE_FOLLOWED
        )
        # ADR-0182 §7: it is not read again of the page's own motion; and the stream it
        # was read beside goes on.
        await drive.page.wait_for_timeout(3_000)
        assert len(reads) == 1
        await expect(drive.page.locator("#chat-follow")).to_contain_text("You came back")
        assert await drive.page.evaluate("() => chat.following && chat.stream !== null")

        # Read again, though nothing changed. What it shows is not this read's alone:
        # the stream sends the state as it opens too (#2740), and the stream wins.
        again: list[str] = []

        async def counted(conversation_id: str) -> Any:
            again.append(conversation_id)
            return await held(conversation_id)

        drive.engine.conversation = counted  # type: ignore[method-assign]
        await drive.page.evaluate(_HIDE_AND_SHOW)
        for _ in range(100):
            if again:
                break
            await drive.page.wait_for_timeout(50)
        assert again == reads


async def test_a_new_session_follows_though_the_old_ones_stream_was_still_out(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A stream left over from an ended session does not stand in for the new one's,
    and its ending — the gateway ended it with the session — stops nothing."""
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.page.evaluate(_HOLDING, "/chat/follow")
        await drive.page.click("#chat-button")
        await drive.page.wait_for_function("() => window.__held.reached", timeout=_IDLE_FOLLOWED)
        assert await drive.page.evaluate("() => chat.stream !== null && !chat.stream.headed")
        drive.expire_sessions()
        await drive.page.click("#chat-start")
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")
        await drive.admit()
        await drive.page.click("#chat-button")
        await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")

        await drive.page.evaluate("window.__held.release()")
        await drive.page.wait_for_timeout(500)
        assert await drive.page.evaluate("() => chat.following && chat.stream !== null")
        await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")


async def test_a_state_change_with_no_transcript_change_reaches_an_idle_page(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§8:1: the state is followed while a conversation is open, sent from here or not."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        # The opening read of the state has landed, idle, before the state changes: what
        # shows the change is a later read made by the following.
        await drive.page.wait_for_function(
            "() => chat.state !== null && !chat.state.working && chat.following"
        )
        conversation = await drive.page.evaluate("chat.selected")
        reads = [name for name, _ in drive.engine.calls if name == "conversation"]

        drive.engine.push_state(conversation, ConversationState(working=True))
        await expect(drive.page.locator("#chat-state")).to_contain_text(
            "working on this", timeout=_IDLE_FOLLOWED
        )
        # Pushed, not read: no read of the conversation was made for it (ADR-0296 §4:9).
        assert [name for name, _ in drive.engine.calls if name == "conversation"] == reads


async def test_a_transcript_that_could_not_be_read_is_offered_again(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Nothing reads the transcript again of its own motion; the owner is handed it."""
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.engine.set_my_devices(
            [ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)]
        )
        started = await drive.engine.start_conversation()
        await drive.engine.chat.append_message(
            started.id, NewMessage(author=MessageAuthor.ASSISTANT, text="Already here.")
        )
        held = drive.engine.transcript

        async def failing(*arguments: Any, **keywords: Any) -> Any:
            raise ConversationStoreError("the transcript is unreadable")

        drive.engine.transcript = failing  # type: ignore[method-assign]
        await drive.page.click("#chat-button")
        await drive.page.locator("#chat-conversations button.chat-open:not([aria-current])").click()
        again = drive.page.locator("#chat-reread")
        await expect(again).to_be_visible()

        drive.engine.transcript = held  # type: ignore[method-assign]
        await again.click()
        await expect(drive.page.locator("#chat-transcript")).to_contain_text("Already here.")
        await expect(again).to_be_hidden()


async def test_a_chat_opened_on_a_hidden_page_waits_to_be_seen(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Following starts only on a visible page; coming back starts it, and says so."""
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.page.evaluate(_HOLDING, "/chat/devices")
        await drive.page.click("#chat-button")
        await drive.page.wait_for_function("() => window.__held.reached")
        await drive.page.evaluate(
            """() => {
              Object.defineProperty(document, "visibilityState", {
                configurable: true, get: () => "hidden" });
              document.dispatchEvent(new Event("visibilitychange"));
            }"""
        )
        await drive.page.evaluate("window.__held.release()")
        follow = drive.page.locator("#chat-follow")
        await expect(follow).to_contain_text("Paused while this page is hidden")
        assert await drive.page.evaluate("() => !chat.following && chat.stream === null")

        await drive.page.evaluate(
            """() => {
              Object.defineProperty(document, "visibilityState", {
                configurable: true, get: () => "visible" });
              document.dispatchEvent(new Event("visibilitychange"));
            }"""
        )
        await expect(follow).to_contain_text("You came back")


async def test_a_send_whose_refusal_could_not_be_read_is_not_known(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0177 §7: an answer the page could not read leaves the outcome not known."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)

        async def unreadable(route: Route) -> None:
            await route.fulfill(status=502, body="<html>proxy</html>")

        await drive.page.route("**/chat/message/write", unreadable)
        try:
            await _send(drive, "Did it?")
            pending = drive.page.locator("#chat-transcript li.pending")
            await expect(pending).to_contain_text("not known whether this arrived")
            await expect(pending.locator("button", has_text="Send again")).to_be_visible()
        finally:
            await drive.page.unroute("**/chat/message/write", unreadable)


async def test_a_devices_read_that_fails_on_opening_is_read_again_on_the_owners_press(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Following again opens the chat again where an opening read failed."""
    async with driving(gateway_browser, tmp_path) as drive:
        held = drive.engine.my_devices

        async def failing() -> Any:
            raise ConversationStoreError("the set is unreadable")

        drive.engine.my_devices = failing  # type: ignore[method-assign]
        await drive.page.click("#chat-button")
        await expect(drive.page.locator("#chat-follow")).to_contain_text("Stopped following")

        drive.engine.my_devices = held  # type: ignore[method-assign]
        await drive.page.click("#chat-follow-again")
        await expect(drive.page.locator("#chat-this-device")).to_contain_text("device hub")
        await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")


async def test_a_stream_the_gateway_opened_late_applies_every_change_since_the_cursor(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§5:10: the change stream is the authority, so no change it carries is skipped.

    The stream is asked for from the cursor read when the chat opened, and reaches the
    gateway after two changes to "my devices"; it carries both, and the page applies
    both, in order.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.engine.set_my_devices(
            [
                ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE),
                ChatDevice(device_id="nTABLET", access=DeviceAccess.READ),
                ChatDevice(device_id="nPHONE", access=DeviceAccess.READ),
            ]
        )
        loop = asyncio.get_running_loop()
        held: asyncio.Future[Route] = loop.create_future()

        async def hold(route: Route) -> None:
            if not held.done():
                held.set_result(route)
                return
            await route.continue_()

        await drive.page.route("**/chat/follow", hold)
        await drive.page.click("#chat-button")
        devices = drive.page.locator("#chat-my-devices li")
        await expect(devices).to_have_count(3)
        try:
            route = await asyncio.wait_for(held, timeout=_IDLE_FOLLOWED / 1000)
            await drive.engine.set_my_devices(
                [
                    ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE),
                    ChatDevice(device_id="nPHONE", access=DeviceAccess.READ),
                ]
            )
            await drive.engine.set_my_devices(
                [ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)]
            )
            await route.continue_()
            await expect(devices).to_have_count(1, timeout=_FOLLOWED)
        finally:
            await drive.page.unroute("**/chat/follow", hold)


async def test_an_event_does_not_resume_a_chat_whose_opening_read_failed(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The owner's control stays until pressed; coming back does not stand in for it."""
    async with driving(gateway_browser, tmp_path) as drive:

        async def failing() -> Any:
            raise ConversationStoreError("the set is unreadable")

        drive.engine.my_devices = failing  # type: ignore[method-assign]
        await drive.page.click("#chat-button")
        await expect(drive.page.locator("#chat-follow")).to_contain_text("Stopped following")
        await drive.page.evaluate(
            """() => {
              document.dispatchEvent(new Event("visibilitychange"));
              window.dispatchEvent(new Event("online"));
            }"""
        )
        await expect(drive.page.locator("#chat-follow-again")).to_be_visible()
        assert await drive.page.evaluate("() => !chat.following")


async def test_a_reply_being_written_to_a_message_deleted_meanwhile_names_it_as_deleted(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§5:12: the composer's reference follows the transcript, so no deleted text stays."""
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive)
        await drive.engine.chat.append_message(
            conversation, NewMessage(author=MessageAuthor.ASSISTANT, text="Secret plan.")
        )
        message = drive.page.locator("#chat-transcript li.from-assistant")
        await expect(message).to_contain_text("Secret plan.", timeout=_IDLE_FOLLOWED)
        await message.locator("button", has_text="Reply").click()
        replying = drive.page.locator("#chat-replying")
        await expect(replying).to_contain_text("Secret plan.")

        await drive.engine.delete_message(conversation, position=1)
        await expect(replying).to_have_text(
            "In reply to a message that was deleted.", timeout=_IDLE_FOLLOWED
        )


async def test_a_reply_to_a_deleted_message_older_than_the_snapshot_says_so(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§5:8 for a target outside the loaded page: it is read, and named as deleted."""
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.engine.set_my_devices(
            [ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)]
        )
        started = await drive.engine.start_conversation()
        for index in range(1, 51):
            await drive.engine.chat.append_message(
                started.id, NewMessage(author=MessageAuthor.ASSISTANT, text=f"Note {index}.")
            )
        await drive.engine.chat.append_message(
            started.id,
            NewMessage(author=MessageAuthor.ASSISTANT, text="About the first.", replies_to=1),
        )
        await drive.engine.delete_message(started.id, position=1)

        await drive.page.click("#chat-button")
        await drive.page.locator("#chat-conversations button.chat-open:not([aria-current])").click()
        reply = drive.page.locator("#chat-transcript li", has_text="About the first.")
        await expect(reply).to_contain_text("In reply to a message that was deleted.")


async def test_a_listing_that_could_not_be_read_again_stops_the_following(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A conversation started elsewhere is not left unlisted with nothing to press."""
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.page.click("#chat-button")
        follow = drive.page.locator("#chat-follow")
        await expect(follow).to_contain_text("Following this chat")
        held = drive.engine.recent_conversations

        async def failing(**arguments: Any) -> Any:
            raise ConversationStoreError("the index is unreadable")

        drive.engine.recent_conversations = failing  # type: ignore[method-assign]
        started = await drive.engine.start_conversation()
        await expect(follow).to_contain_text("Stopped following", timeout=_IDLE_FOLLOWED)

        drive.engine.recent_conversations = held  # type: ignore[method-assign]
        await drive.page.click("#chat-follow-again")
        await expect(_row(drive, started.id)).to_have_count(1)
        await expect(follow).to_contain_text("Following this chat")


async def test_every_old_reply_target_is_read_including_one_a_live_reply_names(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§5:8 for more targets than any one batch, and for a reply that arrives while open.

    Every target sits outside the opening snapshot (the latest 50 entries): 26 deleted
    messages, then 50 fillers, then 25 replies to the first 25 of them.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.engine.set_my_devices(
            [ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)]
        )
        started = await drive.engine.start_conversation()
        for index in range(1, 27):
            await drive.engine.chat.append_message(
                started.id, NewMessage(author=MessageAuthor.ASSISTANT, text=f"Old {index}.")
            )
        for index in range(1, 51):
            await drive.engine.chat.append_message(
                started.id, NewMessage(author=MessageAuthor.ASSISTANT, text=f"Filler {index}.")
            )
        for index in range(1, 26):
            await drive.engine.chat.append_message(
                started.id,
                NewMessage(
                    author=MessageAuthor.ASSISTANT, text=f"About {index}.", replies_to=index
                ),
            )
        for index in range(1, 27):
            await drive.engine.delete_message(started.id, position=index)

        await drive.page.click("#chat-button")
        await drive.page.locator("#chat-conversations button.chat-open:not([aria-current])").click()
        replies = drive.page.locator("#chat-transcript li", has_text="About ")
        await expect(replies).to_have_count(25)
        assert await drive.page.evaluate("() => chat.oldest") > 26
        await expect(
            drive.page.locator("#chat-transcript li", has_text="In reply to message")
        ).to_have_count(0)
        await expect(
            drive.page.locator("#chat-transcript li", has_text="About 1.")
        ).to_contain_text("In reply to a message that was deleted.")

        await drive.engine.chat.append_message(
            started.id,
            NewMessage(author=MessageAuthor.ASSISTANT, text="About 26.", replies_to=26),
        )
        late = drive.page.locator("#chat-transcript li", has_text="About 26.")
        await expect(late).to_contain_text(
            "In reply to a message that was deleted.", timeout=_IDLE_FOLLOWED
        )


async def test_a_reply_target_lookup_that_failed_is_not_made_again_unasked(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0182 §7: a later message does not re-issue a lookup that failed."""
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.engine.set_my_devices(
            [ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)]
        )
        started = await drive.engine.start_conversation()
        for index in range(1, 60):
            await drive.engine.chat.append_message(
                started.id, NewMessage(author=MessageAuthor.ASSISTANT, text=f"Note {index}.")
            )
        await drive.engine.chat.append_message(
            started.id,
            NewMessage(author=MessageAuthor.ASSISTANT, text="About the first.", replies_to=1),
        )
        held = drive.engine.transcript
        lookups: list[int | None] = []

        async def failing_lookups(conversation_id: str, **keywords: Any) -> Any:
            if keywords.get("limit") == 1:
                lookups.append(keywords.get("before"))
                raise ConversationStoreError("the transcript is unreadable")
            return await held(conversation_id, **keywords)

        drive.engine.transcript = failing_lookups  # type: ignore[method-assign]
        await drive.page.click("#chat-button")
        await drive.page.locator("#chat-conversations button.chat-open:not([aria-current])").click()
        reply = drive.page.locator("#chat-transcript li", has_text="About the first.")
        await expect(reply).to_contain_text("In reply to message 1.")
        await drive.page.wait_for_function("() => chat.resolving === null")
        assert lookups == [2]

        await drive.engine.chat.append_message(
            started.id, NewMessage(author=MessageAuthor.ASSISTANT, text="Unrelated.")
        )
        await expect(drive.page.locator("#chat-transcript")).to_contain_text(
            "Unrelated.", timeout=_IDLE_FOLLOWED
        )
        await drive.page.wait_for_function("() => chat.resolving === null")
        assert lookups == [2]


async def test_a_read_reply_target_deleted_later_is_named_as_deleted(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A marker outranks the text kept for a reply, whichever path brought the marker."""
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.engine.set_my_devices(
            [ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)]
        )
        started = await drive.engine.start_conversation()
        await drive.engine.chat.append_message(
            started.id, NewMessage(author=MessageAuthor.ASSISTANT, text="The secret.")
        )
        for index in range(2, 60):
            await drive.engine.chat.append_message(
                started.id, NewMessage(author=MessageAuthor.ASSISTANT, text=f"Filler {index}.")
            )
        await drive.engine.chat.append_message(
            started.id,
            NewMessage(author=MessageAuthor.ASSISTANT, text="About the secret.", replies_to=1),
        )
        await drive.page.click("#chat-button")
        await drive.page.locator("#chat-conversations button.chat-open:not([aria-current])").click()
        reply = drive.page.locator("#chat-transcript li", has_text="About the secret.")
        await expect(reply).to_contain_text("The secret.")

        # Stop following, delete it elsewhere, and bring the marker in by loading back.
        await drive.page.evaluate("() => stopFollowing(null, true)")
        await drive.engine.delete_message(started.id, position=1)
        await drive.page.click("#chat-older")
        await expect(reply).to_contain_text("In reply to a message that was deleted.")
        await expect(reply).not_to_contain_text("“The secret.”")


async def test_a_lookups_marker_removes_a_loaded_message_whatever_the_next_lookup_does(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§5:12: a marker a lookup brings removes the message from the loaded transcript too,
    and is on screen before the next lookup is awaited — so a next lookup that fails does
    not leave the deleted text up.

    Two reply targets lie outside the opening snapshot. The first lookup is held while
    an older page loads the target's text; the target is then deleted elsewhere, with
    following stopped so only the lookup can bring the marker; and the second lookup
    fails.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.engine.set_my_devices(
            [ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)]
        )
        started = await drive.engine.start_conversation()
        for text in ("Secret A.", "Secret B."):
            await drive.engine.chat.append_message(
                started.id, NewMessage(author=MessageAuthor.ASSISTANT, text=text)
            )
        for index in range(3, 60):
            await drive.engine.chat.append_message(
                started.id, NewMessage(author=MessageAuthor.ASSISTANT, text=f"Filler {index}.")
            )
        for target in (1, 2):
            await drive.engine.chat.append_message(
                started.id,
                NewMessage(
                    author=MessageAuthor.ASSISTANT, text=f"About {target}.", replies_to=target
                ),
            )
        held = drive.engine.transcript
        gate = asyncio.Event()
        lookups: list[int | None] = []

        async def gated(conversation_id: str, **keywords: Any) -> Any:
            if keywords.get("limit") != 1:
                return await held(conversation_id, **keywords)
            lookups.append(keywords.get("before"))
            if len(lookups) == 1:
                await gate.wait()
                return await held(conversation_id, **keywords)
            raise ConversationStoreError("the transcript is unreadable")

        drive.engine.transcript = gated  # type: ignore[method-assign]
        await drive.page.click("#chat-button")
        await drive.page.locator("#chat-conversations button.chat-open:not([aria-current])").click()
        await drive.page.wait_for_function("() => chat.resolving !== null")
        assert lookups == [2]

        await drive.page.evaluate("() => stopFollowing(null, true)")
        await drive.page.click("#chat-older")
        transcript = drive.page.locator("#chat-transcript")
        await expect(transcript).to_contain_text("Secret A.")

        await drive.engine.delete_message(started.id, position=1)
        gate.set()
        await drive.page.wait_for_function("() => chat.resolving === null")

        assert lookups == [2, 3]
        await expect(transcript).not_to_contain_text("Secret A.")
        await expect(
            drive.page.locator("#chat-transcript li", has_text="About 1.")
        ).to_contain_text("In reply to a message that was deleted.")


# --- what the device holds, and what it drops (ADR-0296 §4:7-§4:8, ADR-0298 §7) ------


async def test_a_device_removed_from_a_conversation_drops_it(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0296 §4:8: "When a device stops being an end of a conversation for reading, its
    stream says so, and the device drops the conversation" — off the screen it was open
    on and out of the listing, said on the page. Driven at both widths."""
    for viewport in (DESKTOP, PHONE):
        async with driving(gateway_browser, tmp_path, device=_LAPTOP, viewport=viewport) as drive:
            conversation = await _open(drive, devices=(_LAPTOP,))
            await expect(drive.page.locator("#chat-this-device")).to_contain_text(_LAPTOP)

            # The owner, at the command line, leaves this device out of it.
            await drive.engine.set_conversation_devices(conversation, devices=[])

            said = drive.page.locator("#chat-said")
            await expect(said).to_contain_text(
                "This device no longer reads the conversation from", timeout=_FOLLOWED
            )
            await expect(drive.page.locator("#chat-thread")).to_be_hidden()
            await expect(_row(drive, conversation)).to_have_count(0)
            await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")
            assert await drive.page.evaluate(
                "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )


async def test_a_device_added_to_a_conversation_is_listed_it_with_its_snapshot(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0298 §7:6: the change that makes this device a reader arrives with the
    conversation's snapshot; the page lists the conversation, and opening it shows what
    was written before the device could read it."""
    async with driving(gateway_browser, tmp_path, device=_LAPTOP) as drive:
        await drive.page.click("#chat-button")
        await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")
        started = await drive.engine.start_conversation()
        await drive.engine.chat.append_message(
            started.id, NewMessage(author=MessageAuthor.ASSISTANT, text="Written before.")
        )
        await drive.engine.set_conversation_devices(
            started.id, devices=[ChatDevice(device_id=_LAPTOP, access=DeviceAccess.READ_WRITE)]
        )

        await expect(_row(drive, started.id)).to_have_count(1, timeout=_FOLLOWED)
        await drive.page.locator("#chat-conversations button.chat-open:not([aria-current])").click()
        await expect(drive.page.locator("#chat-transcript")).to_contain_text("Written before.")


async def test_a_device_refused_for_holding_no_role_drops_every_conversation(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0298 §7:17: a device refused the change stream for holding no role drops every
    conversation it holds, as if it had seen the change that removed it from each — and
    says why, with the remedy, and reopens nothing of its own motion."""
    async with driving(gateway_browser, tmp_path, device=_LAPTOP) as drive:
        conversation = await _open(drive, devices=(_LAPTOP,))
        drive.engine.refuse_following = DeviceRefusal.NO_ROLE
        # The owner hides the page and comes back, which opens the stream again.
        await drive.page.evaluate(_HIDE_AND_SHOW)

        await expect(drive.page.locator("#chat-said")).to_contain_text(
            "holding no role", timeout=_FOLLOWED
        )
        await expect(drive.page.locator("#chat .fault")).to_contain_text(
            f"ai-assistant-device assign {_LAPTOP} commands"
        )
        await expect(drive.page.locator("#chat-thread")).to_be_hidden()
        await expect(_row(drive, conversation)).to_have_count(0)
        await expect(drive.page.locator("#chat-follow")).to_contain_text("Stopped following")
        await expect(drive.page.locator("#chat-follow-again")).to_be_visible()
        opened = len(_follows(drive))
        await drive.page.wait_for_timeout(2_000)
        assert len(_follows(drive)) == opened


async def test_a_listing_read_before_a_removal_does_not_bring_the_conversation_back(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0296 §4:8: a listing answered before the change that removed this device still
    names the conversation; landing after the drop, it does not list it again."""
    async with driving(gateway_browser, tmp_path, device=_LAPTOP) as drive:
        conversation = await _open(drive, devices=(_LAPTOP,))
        await drive.page.evaluate(_HOLDING, "/conversations")
        await drive.engine.start_conversation()  # the stream says so, and the page relists
        await drive.page.wait_for_function("() => window.__held.reached", timeout=_FOLLOWED)

        await drive.engine.set_conversation_devices(conversation, devices=[])
        await expect(drive.page.locator("#chat-said")).to_contain_text(
            "no longer reads", timeout=_FOLLOWED
        )
        await drive.page.evaluate("window.__held.release()")
        await drive.page.wait_for_function("() => !window.__held.open")

        listing = drive.page.locator("#chat-conversations")
        await expect(listing.locator("li")).to_have_count(1)
        await expect(_row(drive, conversation)).to_have_count(0)


async def test_a_listing_read_before_a_no_role_refusal_lists_nothing_when_it_lands(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0298 §7:17 drops every conversation, including what a listing still out says."""
    async with driving(gateway_browser, tmp_path, device=_LAPTOP) as drive:
        await _open(drive, devices=(_LAPTOP,))
        await drive.page.evaluate(_HOLDING, "/conversations")
        await drive.engine.start_conversation()
        await drive.page.wait_for_function("() => window.__held.reached", timeout=_FOLLOWED)

        drive.engine.refuse_following = DeviceRefusal.NO_ROLE
        await drive.page.evaluate(_HIDE_AND_SHOW)
        await expect(drive.page.locator("#chat-said")).to_contain_text(
            "holding no role", timeout=_FOLLOWED
        )
        await drive.page.evaluate("window.__held.release()")
        await drive.page.wait_for_function("() => !window.__held.open")

        await expect(drive.page.locator("#chat-conversations")).to_contain_text(
            "No conversations yet."
        )


async def test_a_state_read_refused_for_a_removal_leaves_the_stream_to_say_so(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A device removed from the conversation on screen while the page was hidden is
    refused that conversation's state when it comes back; the refusal stops nothing, and
    the stream then delivers the removal, which drops the conversation (ADR-0296 §4:8)."""
    async with driving(gateway_browser, tmp_path, device=_LAPTOP) as drive:
        conversation = await _open(drive, devices=(_LAPTOP,))

        async def refused(conversation_id: str) -> Any:
            msg = "reading one conversation needs this device among its readers"
            raise DeviceRefusedError(msg, reason=DeviceRefusal.NOT_ALLOWED)

        await drive.page.evaluate(
            """() => {
              Object.defineProperty(document, "visibilityState", {
                configurable: true, get: () => "hidden" });
              document.dispatchEvent(new Event("visibilitychange"));
            }"""
        )
        await drive.engine.set_conversation_devices(conversation, devices=[])
        drive.engine.conversation = refused  # type: ignore[method-assign]
        await drive.page.evaluate(
            """() => {
              Object.defineProperty(document, "visibilityState", {
                configurable: true, get: () => "visible" });
              document.dispatchEvent(new Event("visibilitychange"));
            }"""
        )

        await expect(drive.page.locator("#chat-said")).to_contain_text(
            "This device no longer reads the conversation from", timeout=_FOLLOWED
        )
        await expect(drive.page.locator("#chat-thread")).to_be_hidden()
        await expect(drive.page.locator("#chat-follow")).to_contain_text("You came back")
        assert await drive.page.evaluate("() => chat.following")


async def test_a_roles_chunk_with_no_roles_drops_nothing(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The roles the stream carries are the roster's (ADR-0298 §7:9), and membership of a
    conversation is a role the roster does not carry: so an empty set is not the
    ``NO_ROLE`` refusal §7:17 drops on. The page says what the set is and keeps
    following, with every conversation it held."""
    async with driving(gateway_browser, tmp_path, device=_LAPTOP) as drive:
        conversation = await _open(drive, devices=(_LAPTOP,))
        drive.engine.push(ChatStreamChunk(roles=()))

        await expect(drive.page.locator("#chat-this-device")).to_contain_text(
            "roster gives it no role", timeout=_FOLLOWED
        )
        await expect(drive.page.locator("#chat-heading")).to_have_text(
            await _title(drive, conversation)
        )
        assert await drive.page.evaluate("() => chat.selected") == conversation
        await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")
        await expect(drive.page.locator("#chat-said")).to_be_hidden()


async def test_a_hub_shutting_down_stops_the_following_and_it_carries_on_after(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """``ChatStreamEnd`` is the hub going away, said as that rather than as a failure;
    following again starts from the cursor it carried."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        await drive.page.wait_for_function("() => chat.stream !== null")
        cursor = await drive.page.evaluate("chat.cursor")
        drive.engine.push(ChatStreamEnd(next_after=cursor + 5))

        follow = drive.page.locator("#chat-follow")
        await expect(follow).to_contain_text("the hub is shutting down", timeout=_FOLLOWED)
        await expect(drive.page.locator("#chat .fault")).to_be_hidden()
        await drive.page.click("#chat-follow-again")
        await expect(follow).to_contain_text("because you asked")
        await _followed(drive, 2)
        assert _follows(drive)[-1] == cursor + 5


# --- the phone's two halves (#3098) ---------------------------------------------


async def test_a_message_to_the_open_conversation_is_news_on_a_phone_showing_the_list(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Going back to the list leaves the conversation open but off the screen, so a
    message arriving in it is marked on its row like any other's; opening it again
    shows the message, clears the mark, and reads nothing."""
    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        drive.engine.chat_reader = False  # the message is the case's own
        conversation = await _open(drive)
        await drive.page.click("#chat-back")
        await expect(drive.page.locator("#chat-transcript")).to_be_hidden()
        reads = [name for name, _ in drive.engine.calls if name == "transcript"]

        await drive.engine.chat.append_message(
            conversation, NewMessage(author=MessageAuthor.ASSISTANT, text="While you were away.")
        )
        row = drive.page.locator("#chat-conversations button.chat-open[aria-current]")
        await expect(row).to_contain_text("new messages", timeout=_FOLLOWED)

        await row.click()
        await expect(drive.page.locator("#chat-transcript")).to_contain_text("While you were away.")
        await expect(row).not_to_contain_text("new messages")
        assert [name for name, _ in drive.engine.calls if name == "transcript"] == reads


#: Whether the open details end inside the chat's frame and the window.
_DETAILS_INSIDE_THE_FRAME: Final = """() => {
  const body = document.querySelector(".chat-about-body").getBoundingClientRect();
  const frame = document.querySelector(".chat-app").getBoundingClientRect();
  return body.bottom <= frame.bottom && body.bottom <= window.innerHeight;
}"""

#: The details scrolled within themselves to their end, as a finger would scroll them.
_DETAILS_SCROLLED_TO_THE_END: Final = """() => {
  const body = document.querySelector(".chat-about-body");
  body.scrollTop = body.scrollHeight;
}"""

#: Whether the element is what a press at its centre lands on.
_ON_TOP: Final = """(selector) => {
  const target = document.querySelector(selector);
  const box = target.getBoundingClientRect();
  const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
  return hit !== null && (hit === target || target.contains(hit));
}"""


async def test_every_device_and_both_acts_in_a_conversations_details_are_reachable(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The details open over a frame that clips what passes its edge, so at a phone's
    height a conversation with the surface's most devices still ends inside the frame,
    scrolls within itself to its last device, and its Forget still answers a press.

    Measured rather than reached with Playwright's own scrolling: the frame's clip is a
    box a script can scroll and a finger cannot, so a drive that let Playwright scroll it
    would pass on exactly the page this case is about.
    """
    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        await drive.engine.set_my_devices(
            [ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)]
        )
        started = await drive.engine.start_conversation()
        await drive.engine.set_conversation_devices(
            started.id,
            devices=[
                ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE),
                *(
                    ChatDevice(device_id=f"nDEVICE{one:02d}", access=DeviceAccess.READ)
                    for one in range(1, CHAT_DEVICES_MAX)
                ),
            ],
        )
        await drive.page.click("#chat-button")
        await _streaming(drive)
        await drive.page.locator("#chat-conversations button.chat-open:not([aria-current])").click()
        listed = drive.page.locator("#chat-conversation-devices li")
        await expect(listed).to_have_count(CHAT_DEVICES_MAX)

        await drive.page.click("#chat-thread .chat-about > summary")
        assert await drive.page.evaluate(_DETAILS_INSIDE_THE_FRAME)
        await drive.page.evaluate(_DETAILS_SCROLLED_TO_THE_END)
        for target in ("#chat-conversation-devices li:last-child", "#chat-forget"):
            assert await drive.page.evaluate(_ON_TOP, target), target

        loop = asyncio.get_running_loop()
        asked: asyncio.Future[str] = loop.create_future()
        running: list[asyncio.Task[None]] = []

        async def dismiss(dialog: Dialog) -> None:
            await dialog.dismiss()
            asked.set_result(dialog.message)

        drive.page.once("dialog", lambda dialog: running.append(loop.create_task(dismiss(dialog))))
        await drive.page.click("#chat-forget")
        assert "Forget this conversation?" in await asked


#: The contrast of a focused control's ring against what it sits on, in the browser's
#: own computed colours: WCAG's 3:1 for a non-text indicator.
_RING_CONTRAST: Final = """(button) => {
  const channel = (value) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const luminance = (css) => {
    const [r, g, b] = css.match(/[\\d.]+/g).slice(0, 3).map(Number);
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };
  const ring = getComputedStyle(button);
  const ground = getComputedStyle(button.closest("li")).backgroundColor;
  const [high, low] = [luminance(ring.outlineColor), luminance(ground)].sort((a, b) => b - a);
  return {
    visible: button.matches(":focus-visible") && ring.outlineStyle !== "none",
    contrast: (high + 0.05) / (low + 0.05),
  };
}"""


@pytest.mark.parametrize("scheme", ["dark", "light"])
async def test_a_focused_control_on_the_owners_own_message_is_seen(
    gateway_browser: Browser, tmp_path: Path, scheme: str
) -> None:
    """The keyboard's place is visible inside the gold, in both schemes (#3113).

    The page's focus ring is the gold, and the owner's messages are *filled* with it —
    so a ring left at the page's colour would be gold on gold on exactly the controls a
    keyboard reaches first going back from the message box: the last message's Reply and
    Delete. Reached by the keyboard rather than focused by a script, because the ring is
    drawn for `:focus-visible`, which is the browser's own judgement of how focus came.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
        await _open(drive)
        await drive.page.fill("#chat-text", "Seen from the keyboard.")
        await drive.page.press("#chat-text", "Control+Enter")
        await expect(
            drive.page.locator("#chat-transcript li.from-user:not(.pending)")
        ).to_have_count(1, timeout=_FOLLOWED)

        await drive.page.focus("#chat-text")
        for _ in range(8):
            await drive.page.keyboard.press("Shift+Tab")
            if await drive.page.evaluate(
                "() => document.activeElement.closest('li.from-user') !== null"
            ):
                break
        focused = drive.page.locator("li.from-user button:focus")
        await expect(focused).to_have_count(1)
        ring = await focused.evaluate(_RING_CONTRAST)
        assert ring["visible"], ring
        assert ring["contrast"] >= 3, ring
