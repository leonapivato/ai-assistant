"""The belief panel says whose a memory is, and what the assistant said (ADR-0345 §12).

Driven in a real browser over the shipped page, at a desktop width and at a phone's
(ADR-0216, ADR-0233 §15): a memory someone other than the owner holds says so, a memory
the owner alone holds says nothing about holders, and a memory marked as the assistant's
statement reads as what the assistant said, citing when, and who kept it, never as the
owner's word (§12:4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest
from browser_drive import DESKTOP, PHONE, driving, press
from playwright.async_api import expect

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Memory,
    MemoryMark,
    MemorySupport,
    SupportHolder,
    belief_view,
)
from ai_assistant.testing.memories import memory, message_support, said_support

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, ConsoleMessage, Page, ViewportSize

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

_WIDTHS: Final = pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])

_AT: Final = datetime(2026, 10, 20, 18, tzinfo=UTC)
_OWNER: Final = SupportHolder.person(OWNER_PERSON_ID)


def _complaints(page: Page) -> list[str]:
    """Every console error and uncaught exception, but the browser's own favicon probe."""
    heard: list[str] = []

    def note(message: ConsoleMessage) -> None:
        if message.type == "error" and not message.location["url"].endswith("/favicon.ico"):
            heard.append(f"{message.location['url']}: {message.text}")

    page.on("console", note)
    page.on("pageerror", lambda error: heard.append(str(error)))
    return heard


def _show(drive: Drive, *records: Memory) -> None:
    for record in records:
        drive.engine.beliefs_held[record.id] = belief_view(record, now=_AT, contents={})


def _by(episode: str, holder: SupportHolder) -> MemorySupport:
    return said_support(episode, when=_AT, added_at=_AT).model_copy(update={"holder": holder})


@_WIDTHS
async def test_whose_memory_it_is_and_what_the_assistant_said_are_shown(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§12:1, §12:4: holders where not the owner alone; a statement as what was said."""
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        heard = _complaints(drive.page)
        _show(
            drive,
            memory("m:own", "Ana is the user's sister.", _by("activation:a", _OWNER)),
            memory(
                "m:tom",
                "Ana lives in Porto.",
                _by("activation:b", SupportHolder.person("tom")),
            ),
            memory(
                "m:said",
                "X is the best car for the commute.",
                _by("activation:c", _OWNER),
                message_support("activation:d", when=_AT, added_at=_AT).model_copy(
                    update={"backs_as_worded": False}
                ),
                marks=(MemoryMark.ASSISTANT_STATEMENT,),
            ),
        )
        page = drive.page
        async with page.expect_response("**/candidates/pending"):
            await press(page, "#beliefs-button")

        own = page.locator("#belief-list > .belief-row", has_text="the user's sister")
        tom = page.locator("#belief-list > .belief-row", has_text="Ana lives in Porto")
        said = page.locator("#belief-list > .belief-row", has_text="best car")
        await expect(tom).to_contain_text("Held by: another person (tom)")
        await expect(own).not_to_contain_text("Held by")
        await expect(said).to_contain_text("What I said")
        await expect(said).not_to_contain_text("You told me")
        await expect(said).to_contain_text("I said this, in my message of")
        await expect(said).to_contain_text("You kept it.")
        await expect(said).not_to_contain_text("you said it")
        overflow: int = await page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 0
        assert heard == []
