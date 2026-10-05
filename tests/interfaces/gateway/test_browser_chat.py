"""The chat, driven (ADR-0293 §11, ADR-0216 §2).

What the page *does* over time, which the bundle's text cannot say: a message is
*received*, the assistant's reply then arrives by following the changes after the
page's cursor, a send the conversation refuses offers what would let it through, a
read that fails stops the following rather than retrying it, and a hidden page pauses
and says so. The engine is the canonical fake; the assistant's reply is written into
the chat space the way the chat's writer writes one (ADR-0293 §6), so nothing about the
reply is fabricated at the page.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final

import pytest
from browser_drive import driving
from playwright.async_api import expect

from ai_assistant.core.errors import ConversationStoreError
from ai_assistant.core.types import (
    ChatDevice,
    ConversationState,
    DeviceAccess,
    MessageAuthor,
    NewMessage,
)
from ai_assistant.wire.errors import HubUnavailableError

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, Dialog, Route

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: Long enough for a quick follow (two seconds) and its digest read to land twice.
_FOLLOWED: Final = 10_000

#: Longer than one idle follow (ten seconds), for a case that has sent nothing.
_IDLE_FOLLOWED: Final = 15_000


async def _open(drive: Drive, *, devices: tuple[str, ...] = ("hub",)) -> str:
    """Put ``devices`` in "my devices", start a conversation, and open it in the chat."""
    await drive.engine.set_my_devices(
        [ChatDevice(device_id=one, access=DeviceAccess.READ_WRITE) for one in devices]
    )
    started = await drive.engine.start_conversation()
    await drive.page.click("#chat-button")
    await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")
    await drive.page.locator("#chat-conversations button", has_text="Open").click()
    await expect(drive.page.locator("#chat-heading")).to_have_text(f"Conversation {started.id}")
    return started.id


async def _send(drive: Drive, text: str) -> None:
    await drive.page.fill("#chat-text", text)
    await drive.page.click("#chat-send")


async def test_a_message_is_received_and_the_reply_arrives_by_following(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§4:4's *received*, then §6's reply reaching the page as a change, with §8's state."""
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive)
        await _send(drive, "Book the usual campsite.")

        transcript = drive.page.locator("#chat-transcript")
        await expect(transcript.locator("li").last).to_contain_text("Book the usual campsite.")
        (written,) = [one for name, one in drive.engine.calls if name == "write_message"]
        message = written["message"]
        assert message.device_id == "hub"  # type: ignore[attr-defined]

        held = drive.engine.conversation

        async def working(conversation_id: str) -> Any:
            digest = await held(conversation_id)
            assert digest is not None
            return digest.model_copy(update={"state": ConversationState(working=True)})

        drive.engine.conversation = working  # type: ignore[method-assign]
        await expect(drive.page.locator("#chat-state")).to_contain_text(
            "working on this", timeout=_FOLLOWED
        )

        drive.engine.conversation = held  # type: ignore[method-assign]
        await drive.engine.chat.append_message(
            conversation,
            NewMessage(author=MessageAuthor.ASSISTANT, text="Pinecrest, Friday.", replies_to=1),
        )
        reply = transcript.locator("li.from-assistant")
        await expect(reply).to_contain_text("Pinecrest, Friday.", timeout=_FOLLOWED)
        await expect(reply).to_contain_text("In reply to: “Book the usual campsite.”")
        await expect(drive.page.locator("#chat-state")).to_be_hidden(timeout=_FOLLOWED)


async def test_a_send_from_a_device_that_is_not_an_end_offers_to_add_it(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§7:2: only a conversation's devices write in it; the page says so and offers the fix.

    The resend carries the same message id, so the conversation records it once (§4:2).
    """
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive, devices=())
        await _send(drive, "Hello?")

        pending = drive.page.locator("#chat-transcript li.pending")
        await expect(pending).to_contain_text("not one of this conversation's devices")
        await pending.locator("button", has_text="Add this device").click()

        await expect(pending).to_have_count(0, timeout=_FOLLOWED)
        await expect(drive.page.locator("#chat-transcript li.from-user")).to_contain_text("Hello?")
        writes = [one for name, one in drive.engine.calls if name == "write_message"]
        assert len(writes) == 2
        assert writes[0]["message"] == writes[1]["message"]
        assert (await drive.engine.conversation(conversation)) is not None


async def test_a_follow_read_that_fails_stops_and_waits_for_the_owner(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0182 §7: nothing is re-issued of the page's own motion after a failure."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        held = drive.engine.chat_changes
        failed: list[int] = []

        async def failing(**arguments: Any) -> Any:
            failed.append(1)
            raise ConversationStoreError("the store is unreadable")

        drive.engine.chat_changes = failing  # type: ignore[method-assign]
        follow = drive.page.locator("#chat-follow")
        await expect(follow).to_contain_text("Stopped following", timeout=_IDLE_FOLLOWED)
        await expect(drive.page.locator("#chat-follow-again")).to_be_visible()
        stopped_at = len(failed)
        await drive.page.wait_for_timeout(5_000)
        assert len(failed) == stopped_at

        drive.engine.chat_changes = held  # type: ignore[method-assign]
        await drive.page.click("#chat-follow-again")
        await expect(follow).to_contain_text("because you asked")
        await expect(drive.page.locator("#chat-follow-again")).to_be_hidden()


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
        assert await drive.page.evaluate("chat.timer === null && !chat.following")

        await drive.page.evaluate(
            """() => {
              Object.defineProperty(document, "visibilityState", {
                configurable: true, get: () => "visible" });
              document.dispatchEvent(new Event("visibilitychange"));
            }"""
        )
        await expect(follow).to_contain_text("You came back")


async def test_a_deleted_message_leaves_its_reply_naming_a_deleted_message(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§5:8: deleting deletes that message alone, and a reply to it says what it named."""
    async with driving(gateway_browser, tmp_path) as drive:
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


async def test_a_state_read_that_fails_while_working_stops_the_following(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0182 §7: the state read is not tried again of the page's own motion either."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        held = drive.engine.conversation
        reads: list[str] = []

        async def working_then_failing(conversation_id: str) -> Any:
            reads.append(conversation_id)
            if len(reads) > 1:
                raise ConversationStoreError("the index is unreadable")
            digest = await held(conversation_id)
            assert digest is not None
            return digest.model_copy(update={"state": ConversationState(working=True)})

        drive.engine.conversation = working_then_failing  # type: ignore[method-assign]
        await _send(drive, "Start something.")
        follow = drive.page.locator("#chat-follow")
        await expect(follow).to_contain_text("Stopped following", timeout=_IDLE_FOLLOWED)
        stopped_at = len(reads)
        await drive.page.wait_for_timeout(5_000)
        assert len(reads) == stopped_at


async def test_a_reload_keeps_the_conversation_the_chat_was_reading(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The tab's chat and its conversation survive a reload, as the ask's thread does."""
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive)
        await drive.page.reload()

        await expect(drive.page.locator("#chat-heading")).to_have_text(
            f"Conversation {conversation}"
        )


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
        await expect(drive.page.locator("#chat-heading")).not_to_have_text(
            f"Conversation {conversation}"
        )

        await drive.page.evaluate(_HOLDING, "/chat/transcript")
        await drive.page.locator("#chat-conversations button", has_text="Open").click()
        await drive.page.wait_for_function("() => window.__held.reached")
        await drive.engine.delete_message(conversation, position=1)
        await drive.page.wait_for_function("() => chat.deleted.has(1)", timeout=_IDLE_FOLLOWED)
        await drive.page.evaluate("window.__held.release()")

        await drive.page.wait_for_function("() => !window.__held.open")
        await expect(drive.page.locator("#chat-transcript li.from-user")).to_have_count(0)


async def test_a_send_never_puts_a_second_changes_read_beside_one_in_flight(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """One read of the changes at a time, whatever asks for the next one meanwhile."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        await drive.page.evaluate(_HOLDING, "/chat/changes")
        await drive.page.wait_for_function("() => window.__held.reached", timeout=_IDLE_FOLLOWED)
        await _send(drive, "While a read is out.")
        await expect(drive.page.locator("#chat-transcript li.pending")).to_contain_text("Received.")
        await drive.page.wait_for_timeout(3_000)
        assert await drive.page.evaluate("window.__held.most") == 1

        await drive.page.evaluate("window.__held.release()")
        await expect(drive.page.locator("#chat-transcript li.pending")).to_have_count(
            0, timeout=_FOLLOWED
        )
        assert await drive.page.evaluate("window.__held.most") == 1


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
        await drive.page.locator("#chat-conversations button", has_text="Open").click()

        await expect(drive.page.locator("#chat-follow")).to_contain_text("Stopped following")
        stopped_at = len(reads)
        await drive.page.wait_for_timeout(5_000)
        assert len(reads) == stopped_at == 1


async def test_following_again_reads_the_state_whose_read_failed(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The owner's recovery reads the state again even when no change has come since."""
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive)
        held = drive.engine.conversation

        async def failing(conversation_id: str) -> Any:
            raise ConversationStoreError("the index is unreadable")

        drive.engine.conversation = failing  # type: ignore[method-assign]
        # Another device writes, so the following reads the state and that read fails.
        await drive.engine.chat.append_message(
            conversation, NewMessage(author=MessageAuthor.ASSISTANT, text="A notice.")
        )
        await expect(drive.page.locator("#chat-follow")).to_contain_text(
            "Stopped following", timeout=_IDLE_FOLLOWED
        )

        async def working(conversation_id: str) -> Any:
            digest = await held(conversation_id)
            assert digest is not None
            return digest.model_copy(update={"state": ConversationState(working=True)})

        drive.engine.conversation = working  # type: ignore[method-assign]
        await drive.page.click("#chat-follow-again")
        await expect(drive.page.locator("#chat-state")).to_contain_text("working on this")


async def test_a_new_session_follows_though_the_old_ones_read_was_still_out(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A read left over from an ended session does not stand in for the new one's."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open(drive)
        await drive.page.evaluate(_HOLDING, "/chat/changes")
        await drive.page.wait_for_function("() => window.__held.reached", timeout=_IDLE_FOLLOWED)
        drive.expire_sessions()
        await drive.page.click("#chat-start")
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")
        await drive.admit()
        await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")

        await drive.page.evaluate("window.__held.release()")
        await drive.page.wait_for_timeout(500)
        assert await drive.page.evaluate(
            "() => chat.following && (chat.timer !== null || chat.reading === chat.ticks)"
        )


async def test_one_edit_of_a_device_set_is_out_at_a_time(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Two removals built from one set would undo each other, so the second waits."""
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.engine.set_my_devices(
            [
                ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE),
                ChatDevice(device_id="nTABLET", access=DeviceAccess.READ),
                ChatDevice(device_id="nPHONE", access=DeviceAccess.READ),
            ]
        )
        await drive.page.click("#chat-button")
        devices = drive.page.locator("#chat-my-devices li")
        await expect(devices).to_have_count(3)
        await drive.page.evaluate(_HOLDING, "/chat/devices/set")

        await devices.filter(has_text="nTABLET").locator("button", has_text="Remove").click()
        await drive.page.wait_for_function("() => window.__held.reached")
        await expect(
            devices.filter(has_text="nPHONE").locator("button", has_text="Remove")
        ).to_be_disabled()

        await drive.page.evaluate("window.__held.release()")
        await expect(devices).to_have_count(2)
        await devices.filter(has_text="nPHONE").locator("button", has_text="Remove").click()
        await expect(devices).to_have_count(1)
        assert [one.device_id for one in await drive.engine.my_devices()] == ["hub"]


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
        held = drive.engine.conversation
        reads: list[str] = []

        async def working(conversation_id: str) -> Any:
            reads.append(conversation_id)
            digest = await held(conversation_id)
            assert digest is not None
            return digest.model_copy(update={"state": ConversationState(working=True)})

        drive.engine.conversation = working  # type: ignore[method-assign]
        await expect(drive.page.locator("#chat-state")).to_contain_text(
            "working on this", timeout=_IDLE_FOLLOWED
        )
        assert reads


async def test_an_edits_late_answer_does_not_undo_a_newer_set(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A set the following applied after an edit went out outranks the edit's answer."""
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.engine.set_my_devices(
            [
                ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE),
                ChatDevice(device_id="nTABLET", access=DeviceAccess.READ),
                ChatDevice(device_id="nPHONE", access=DeviceAccess.READ),
            ]
        )
        await drive.page.click("#chat-button")
        devices = drive.page.locator("#chat-my-devices li")
        await expect(devices).to_have_count(3)
        await drive.page.evaluate(_HOLDING, "/chat/devices/set")
        await devices.filter(has_text="nTABLET").locator("button", has_text="Remove").click()
        await drive.page.wait_for_function("() => window.__held.reached")

        # Another device leaves only this one, after the edit went out.
        await drive.engine.set_my_devices(
            [ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)]
        )
        await drive.page.wait_for_function(
            "() => chat.myDevices.length === 1", timeout=_IDLE_FOLLOWED
        )
        await drive.page.evaluate("window.__held.release()")

        await drive.page.wait_for_function("() => !chat.editingMine")
        await expect(devices).to_have_count(1)


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
        await drive.page.locator("#chat-conversations button", has_text="Open").click()
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
        assert await drive.page.evaluate("() => !chat.following && chat.timer === null")

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


async def test_a_late_state_read_does_not_restore_a_device_an_edit_removed(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """An answer asked before an edit loses to the edit, whichever arrives first."""
    async with driving(gateway_browser, tmp_path) as drive:
        conversation = await _open(drive)
        await drive.engine.set_conversation_devices(
            conversation,
            devices=[
                ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE),
                ChatDevice(device_id="nTABLET", access=DeviceAccess.READ),
            ],
        )
        ends = drive.page.locator("#chat-conversation-devices li")
        await expect(ends).to_have_count(2, timeout=_IDLE_FOLLOWED)

        await drive.page.evaluate(_HOLDING, "/conversation")
        await drive.page.wait_for_function("() => window.__held.reached", timeout=_IDLE_FOLLOWED)
        await ends.filter(has_text="nTABLET").locator("button", has_text="Remove").click()
        await expect(ends).to_have_count(1)
        await drive.page.evaluate("window.__held.release()")

        await drive.page.wait_for_function("() => !window.__held.open")
        await expect(ends).to_have_count(1)


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
        await expect(drive.page.locator("#chat-add-device")).to_be_visible()
        await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")


async def test_a_read_the_gateway_answered_late_applies_every_change_it_carries(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§5:10: the change stream is the authority, so no change it carries is skipped.

    The read leaves the page before an edit and reaches the gateway after the edit and
    another device's change, so it carries both; the page applies both, in order.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.engine.set_my_devices(
            [
                ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE),
                ChatDevice(device_id="nTABLET", access=DeviceAccess.READ),
                ChatDevice(device_id="nPHONE", access=DeviceAccess.READ),
            ]
        )
        await drive.page.click("#chat-button")
        devices = drive.page.locator("#chat-my-devices li")
        await expect(devices).to_have_count(3)
        await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")

        loop = asyncio.get_running_loop()
        held: asyncio.Future[Route] = loop.create_future()

        async def hold(route: Route) -> None:
            if not held.done():
                held.set_result(route)
                return
            await route.continue_()

        await drive.page.route("**/chat/changes", hold)
        try:
            route = await asyncio.wait_for(held, timeout=_IDLE_FOLLOWED / 1000)
            await devices.filter(has_text="nTABLET").locator("button", has_text="Remove").click()
            await expect(devices).to_have_count(2)
            await drive.engine.set_my_devices(
                [ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)]
            )
            await route.continue_()
            await expect(devices).to_have_count(1, timeout=_FOLLOWED)
        finally:
            await drive.page.unroute("**/chat/changes", hold)


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


async def test_a_landed_edit_holds_its_set_until_the_stream_has_caught_up_past_it(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A read sent before an edit landed may bring an older set back; nothing is built on it.

    The set's controls stay held until a read sent after the edit's answer is applied, so
    the next edit is built from the set the hub holds, and the hub ends with what the
    owner chose.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.engine.set_my_devices(
            [
                ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE),
                ChatDevice(device_id="nTABLET", access=DeviceAccess.READ),
                ChatDevice(device_id="nPHONE", access=DeviceAccess.READ),
            ]
        )
        await drive.page.click("#chat-button")
        devices = drive.page.locator("#chat-my-devices li")
        await expect(devices).to_have_count(3)

        await devices.filter(has_text="nTABLET").locator("button", has_text="Remove").click()
        await expect(devices).to_have_count(2)
        phone = devices.filter(has_text="nPHONE").locator("button", has_text="Remove")
        await drive.page.evaluate(_HOLDING, "/chat/changes")
        await drive.page.wait_for_function("() => window.__held.reached", timeout=_IDLE_FOLLOWED)
        await expect(phone).to_be_disabled()

        await drive.page.evaluate("window.__held.release()")
        await expect(phone).to_be_enabled()
        await phone.click()
        await expect(devices).to_have_count(1)
        assert [one.device_id for one in await drive.engine.my_devices()] == ["hub"]
