"""The chat's Stop control, driven (ADR-0297 §5, §6:4; ADR-0295 §1:2).

What the page does with a stop, which the bundle's text cannot say: the control is
offered only while the open conversation's state shows "working…" with an id, it names
that id and no other, the answer is said beside it, and once the state ends the control
is gone and the state's own ending says *stopped*. The engine is the canonical fake;
the state is scripted on its ``conversation`` read and pushed onto its change stream as
the engine pushes a state that changed (ADR-0296 §4:9), and its stop on
``stop_activation``, so the page is driven against the gateway's real relay.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest
from browser_drive import DESKTOP, PHONE, driving
from playwright.async_api import expect

from ai_assistant.core.types import (
    ActivationEnding,
    ActivationStop,
    ChatDevice,
    ConversationState,
    DeviceAccess,
)

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, ViewportSize

    from ai_assistant.core.types import Identifier

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: Long enough for a pushed state to reach the page.
_FOLLOWED: Final = 10_000

#: An activation id as the current state names one (ADR-0275 §6:1's canonical UUID4).
_ACTIVATION: Final = "00000000-0000-4000-8000-000000000001"
_NEXT: Final = "00000000-0000-4000-8000-000000000002"

_VIEWPORTS: Final = [DESKTOP, PHONE]


class _Scripted:
    """The open conversation's current state, and what a stop answers, as a case sets them."""

    def __init__(self, drive: Drive) -> None:
        self.drive = drive
        self.conversation_id: str | None = None
        self._state = ConversationState()
        self.answer = ActivationStop.STOPPED
        self.stops: list[str] = []
        held = drive.engine.conversation

        async def conversation(conversation_id: Identifier) -> Any:
            digest = await held(conversation_id)
            return None if digest is None else digest.model_copy(update={"state": self._state})

        async def stop_activation(activation_id: Identifier, /) -> ActivationStop:
            self.stops.append(activation_id)
            return self.answer

        drive.engine.conversation = conversation  # type: ignore[method-assign]
        drive.engine.stop_activation = stop_activation  # type: ignore[method-assign]

    @property
    def state(self) -> ConversationState:
        """The conversation's current state, as the hub would read it now."""
        return self._state

    @state.setter
    def state(self, state: ConversationState) -> None:
        """Change it, and push it onto the change stream as the engine would."""
        self._state = state
        assert self.conversation_id is not None
        self.drive.engine.push_state(self.conversation_id, state)


async def _open(drive: Drive) -> _Scripted:
    """Open a conversation in the chat, following it, with its state scripted."""
    drive.engine.chat_reader = False  # the state is the case's own
    scripted = _Scripted(drive)
    await drive.engine.set_my_devices([ChatDevice(device_id="hub", access=DeviceAccess.READ_WRITE)])
    started = await drive.engine.start_conversation()
    scripted.conversation_id = started.id
    await drive.page.click("#chat-button")
    await expect(drive.page.locator("#chat-follow")).to_contain_text("Following this chat")
    await drive.page.wait_for_function("() => chat.stream !== null && chat.stream.headed")
    await drive.page.locator("#chat-conversations button", has_text="Open").click()
    await expect(drive.page.locator("#chat-heading")).to_have_text(f"Conversation {started.id}")
    await drive.page.wait_for_function("() => chat.state !== null")
    return scripted


@pytest.mark.parametrize("viewport", _VIEWPORTS)
async def test_stop_names_the_running_activation_and_is_gone_once_it_ends(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§5:7's id, relayed whole; §5:4's answer said; *stopped* once the state ends.

    Driven at both widths with the control on screen, because a control that scrolls a
    phone sideways is one the owner does not have.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        scripted = await _open(drive)
        stop = drive.page.locator("#chat-stop")
        await expect(stop).to_be_hidden()

        scripted.state = ConversationState(working=True, activation_id=_ACTIVATION)
        await expect(stop).to_be_visible(timeout=_FOLLOWED)
        assert await drive.page.evaluate(
            "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        await stop.click()

        said = drive.page.locator("#chat-stop-said")
        await expect(said).to_contain_text("Stopped. Nothing new starts in this")
        await expect(said).to_contain_text("finishes first")
        await expect(stop).to_be_hidden()
        assert scripted.stops == [_ACTIVATION]

        scripted.state = ConversationState(last_ended=ActivationEnding.STOPPED)
        await expect(drive.page.locator("#chat-state")).to_contain_text(
            "was stopped", timeout=_FOLLOWED
        )
        await expect(said).to_be_hidden()
        await expect(stop).to_be_hidden()


async def test_working_with_no_id_offers_no_stop(gateway_browser: Browser, tmp_path: Path) -> None:
    """ADR-0297 §5's residual: an activation whose id was not minted cannot be stopped."""
    async with driving(gateway_browser, tmp_path) as drive:
        scripted = await _open(drive)
        scripted.state = ConversationState(working=True)

        await expect(drive.page.locator("#chat-state")).to_contain_text(
            "working on this", timeout=_FOLLOWED
        )
        await drive.page.wait_for_timeout(2_500)
        await expect(drive.page.locator("#chat-stop")).to_be_hidden()


@pytest.mark.parametrize(
    ("member", "words"),
    [
        (ActivationStop.ALREADY_ENDED, "That had already ended, so nothing was stopped."),
        (ActivationStop.NO_SUCH_ACTIVATION, "holds nothing that says this ran"),
    ],
)
async def test_an_answer_that_wrote_nothing_says_so_and_leaves_the_control(
    gateway_browser: Browser, tmp_path: Path, member: ActivationStop, words: str
) -> None:
    """§5:5, §5:6: nothing was written, and the state still says working, so it stays."""
    async with driving(gateway_browser, tmp_path) as drive:
        scripted = await _open(drive)
        scripted.answer = member
        scripted.state = ConversationState(working=True, activation_id=_ACTIVATION)
        stop = drive.page.locator("#chat-stop")
        await expect(stop).to_be_visible(timeout=_FOLLOWED)

        await stop.click()

        await expect(drive.page.locator("#chat-stop-said")).to_contain_text(words)
        await expect(stop).to_be_visible()
        await expect(stop).to_be_enabled()


async def test_a_later_activation_starts_with_no_answer_beside_it(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The answer is about one activation: the next one is offered the control afresh."""
    async with driving(gateway_browser, tmp_path) as drive:
        scripted = await _open(drive)
        scripted.state = ConversationState(working=True, activation_id=_ACTIVATION)
        stop = drive.page.locator("#chat-stop")
        await expect(stop).to_be_visible(timeout=_FOLLOWED)
        await stop.click()
        await expect(stop).to_be_hidden()

        scripted.state = ConversationState(working=True, activation_id=_NEXT)

        await expect(stop).to_be_visible(timeout=_FOLLOWED)
        await expect(drive.page.locator("#chat-stop-said")).to_be_hidden()
        await stop.click()
        await expect(stop).to_be_hidden()
        assert scripted.stops == [_ACTIVATION, _NEXT]
