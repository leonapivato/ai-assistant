"""The conversation surface, driven (#1371, ADR-0216 §2).

Gaps the owner found on a phone during milestone 14's QA, and each of them is a fact
about *time* or about the screen rather than about the shipped bytes: what a row
names, and what the listing says **after** a forget returns. ADR-0216 §2 puts exactly
that class here — "ordering in time, concurrency, and what one handler does to a
resource another holds" — and leaves the enumerations and must-contains in
``test_bundle.py``, which is why nothing below asserts that a string is present in
``app.js``.

**A row no longer continues a conversation** (ADR-0309 §5:4). "Continue" moved the
Ask form's selection into a thread, and the Ask form retired; the chat is where a
conversation is continued, and its own listing opens each one. So the cases about
which thread the next ask lands in, and about the digest read that said what it
held, retired with it.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import pytest
from browser_drive import driving, press
from playwright.async_api import expect

from ai_assistant.core.types import ChatDevice, DeviceAccess, UserMessage

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, Dialog, Locator, Page, Route

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: When the seeded thread's last turn was recorded. A fixed instant rather than one
#: computed from the clock: what the cases read back is the page having rendered
#: *this* value, and a stamp derived at run time would put a second implementation
#: of the formatting rule inside the assertion that checks it.
_LAST_TURN = datetime(2026, 8, 22, 9, 15, tzinfo=UTC)

#: Holds the page's own handling of one response, **after the gateway has answered
#: it** — installed over ``fetch`` in the manner of ``browser_drive``'s Web Audio
#: probe, and for the same reason: what a case needs to control is a moment inside the
#: page, and no fact about the network reaches it.
#:
#: This is what makes a response genuinely *older* rather than merely late. The
#: request goes out and is answered at the moment the page made it; what is deferred
#: is the page reading that answer. So the body a case releases is the gateway's own,
#: taken before whatever the case changed in between, and nothing about it is
#: fabricated (ADR-0216 §1, §4).
#:
#: Holding it here rather than at a Playwright route is also what keeps the layer
#: fast: an interception left outstanding while the page cancels the request behind it
#: takes thirty seconds of the context's teardown, which on a sixty-second budget
#: (ADR-0216 §3) is most of it.
_HOLDING = """(path) => {
  window.__held = { path: path, seen: 0, reached: false, release: null };
  const realFetch = window.fetch;
  window.fetch = async function (resource, options) {
    const asked = typeof resource === "string" ? resource : resource.url;
    const response = await realFetch.call(this, resource, options);
    if (new URL(asked, location.href).pathname === window.__held.path) {
      window.__held.seen += 1;
      if (window.__held.seen === 2) {
        window.__held.reached = true;
        await new Promise((resolve) => {
          window.__held.release = resolve;
        });
      }
    }
    return response;
  };
}
"""


def _seed(drive: Drive, conversation_id: str, *, turns: int) -> None:
    """Hold one conversation on the engine, with a history behind it.

    ``FakeAssistantEngine.hold_conversation`` records a *fresh* one — no turn yet,
    nothing recorded — which is the state #1371's first clause is about and the
    opposite of the state its second one is. A thread worth resuming already holds
    something, so the digest it recorded is replaced with one that does.

    Args:
        drive: The gateway, engine and page under test.
        conversation_id: The id to hold.
        turns: How many recorded turns its digest reports.
    """
    drive.engine.hold_conversation(conversation_id)
    held = drive.engine.conversations_held[conversation_id]
    drive.engine.conversations_held[conversation_id] = held.model_copy(
        update={"recorded_turns": turns, "last_turn_at": _LAST_TURN}
    )


async def _title(drive: Drive, conversation_id: str) -> str:
    """What the page calls a held conversation: when it started, by the page's own rule
    (``chatTime``), so no second copy of the formatting sits in an assertion."""
    started = drive.engine.conversations_held[conversation_id].started_at.isoformat()
    return str(await drive.page.evaluate("(iso) => chatTime(iso)", started))


async def _answered(drive: Drive, conversation_id: str) -> None:
    """Write one message into a held conversation, and let the fake's reader answer it.

    The episode the reader's activation captures is what forgetting destroys; a
    ``converse`` turn put one there until it retired (ADR-0309 §5:1).
    """
    engine = drive.engine
    await engine.set_my_devices([ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)])
    await engine.write_message(
        conversation_id, message=UserMessage(device_id="phone", message_id="m-1", text="hello")
    )
    async with asyncio.timeout(10):
        while engine._chat_reads:
            await asyncio.gather(*engine._chat_reads)


async def _open_listing(drive: Drive) -> None:
    """Press Conversations and wait for the panel to be showing."""
    await press(drive.page, "#conversations-button")
    await drive.page.wait_for_selector("#conversations:not([hidden])")


def _answering(
    drive: Drive, *, accept: bool, first: Callable[[], None] | None = None
) -> asyncio.Future[str]:
    """Answer the destroy ceremony, and settle once the answer has landed.

    **Registered before the click, which is a correctness requirement and not a
    style.** ``window.confirm`` blocks the page's script thread, and Playwright's
    click waits for the page to settle after dispatching; with no standing handler
    the two race, and the version of this module that answered the dialog *after*
    awaiting the click hung one case in ten — on the case with two rows and nowhere
    else, which is exactly the shape of flake ADR-0216 §7 forbids. A handler that is
    already there answers the ceremony the moment it is raised, so no Playwright
    action ever waits on a blocked renderer.

    **The future is the case's synchronisation** (ADR-0216 §7 again): it resolves
    when the browser has been told what the owner chose, which is a condition the
    page reached rather than a duration the test guessed. That matters most for the
    declining case, where nothing on screen changes and there is otherwise nothing
    to wait for.

    Args:
        drive: The gateway, engine and page under test.
        accept: Whether the owner consents to the destruction.
        first: Run at the moment the ceremony is on screen, before the answer is
            given — which is after the page has read the digest and before it has
            sent the forget, the one window in which the world can change under it.

    Returns:
        The message the ceremony put on screen, once it has been answered.
    """
    loop = asyncio.get_running_loop()
    answered: asyncio.Future[str] = loop.create_future()
    # Held so the tasks are not garbage-collected mid-flight, and held in the closure
    # `handle` carries rather than in a module global, so two cases cannot share it.
    running: list[asyncio.Task[None]] = []

    async def answer(dialog: Dialog) -> None:
        if first is not None:
            first()
        await (dialog.accept() if accept else dialog.dismiss())
        if not answered.done():
            answered.set_result(dialog.message)

    def handle(dialog: Dialog) -> None:
        running.append(loop.create_task(answer(dialog)))

    drive.page.on("dialog", handle)
    return answered


@dataclass
class _Held:
    """One request stopped in flight, and the driver's control over when it lands.

    Attributes:
        reached: Set once the held request has been intercepted, so a case can act in
            the window where it is outstanding rather than hoping to be inside it.
        released: Set by :meth:`release` to let it land.
        settled: Set once the browser has finished with that request, whichever way it
            ended — delivered, or cancelled by the page because it stopped wanting it.
        page: The page it was held on.
    """

    reached: asyncio.Event
    released: asyncio.Event
    settled: asyncio.Event
    page: Page

    async def release(self) -> None:
        """Let it land, and return once the page has finished with it.

        The wait is the whole value of this: what the cases assert after a release is
        that a superseded response changed *nothing*, and a negative asserted at an
        arbitrary moment asserts nothing at all. ``settled`` is the browser saying the
        request is over, and the ``evaluate`` after it is one further task — so every
        microtask the response's handler could still have been holding has drained
        (ADR-0216 §7).
        """
        self.released.set()
        await self.settled.wait()
        await self.page.evaluate("() => null")


async def _holding(drive: Drive, path: str, *, at: int) -> _Held:
    """Stop the ``at``-th request to ``path`` before it goes out, and hand back control.

    The request has not reached the gateway while it is held, so what a release
    produces is a *late* answer rather than an old one. Where a case needs a genuinely
    older answer — one taken before something it then changed — it holds the page's
    handling of the response instead, with :data:`_HOLDING`.

    Args:
        drive: The gateway, engine and page under test.
        path: The exact request path to count and hold.
        at: Which request to that path is held, counting from one.

    Returns:
        The handle: when it was reached, and a release that waits for it to be over.
    """
    held = _Held(
        reached=asyncio.Event(),
        released=asyncio.Event(),
        settled=asyncio.Event(),
        page=drive.page,
    )
    seen = {"n": 0}
    mine: dict[str, object] = {}

    async def hold(route: Route) -> None:
        seen["n"] += 1
        if seen["n"] != at:
            await route.continue_()
            return
        mine["request"] = route.request
        held.reached.set()
        await held.released.wait()
        # A request the page has since abandoned is already cancelled, so sending it
        # raises rather than returning -- which is the behaviour under test rather than
        # a fault in the harness.
        with contextlib.suppress(Exception):
            await route.continue_()
        held.settled.set()

    def note(request: object) -> None:
        if request is mine.get("request"):
            held.settled.set()

    drive.page.on("requestfailed", note)
    drive.page.on("requestfinished", note)
    await drive.page.route(lambda url: urlparse(url).path == path, hold)
    return held


def _first_row(drive: Drive) -> Locator:
    """The listing's first row, whichever conversation the ordering put there.

    Named rather than inlined because a bare ``button:text('Forget')`` over a listing
    of two is a strict-mode violation, and ``.first`` written at each call site is the
    kind of detail that is right in the case somebody copies and wrong in the copy.
    """
    return drive.page.locator("#conversation-list .conversation-row").first


async def test_a_row_names_its_conversation_and_offers_only_the_forget(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A row names the conversation it is about, and its one act is the forget.

    **Named**, because every other line about a conversation on this page names it —
    the destroy ceremony and the outcome of a forget — and a row of two timestamps
    gives the owner nothing to recognise the thread by. Named as the chat names it,
    by when it started, and never by the hub's id (#3209's follow-on).

    **No "Continue"** (ADR-0309 §5:4): it continued a conversation into the Ask form,
    which retired with the Ask panel, and the chat's own listing is where one is
    opened. Asserted over the row's buttons rather than over the file, because a
    control left on screen is what the owner would press.

    The ids seeded here are unbroken and far wider than 390px (adversarial review
    round 5, #1385's "Remo ve" one row over). The row no longer shows one, and they
    stay so that one brought back would still have to wrap rather than push the row
    off a phone.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        long = "conversation-" + "x" * 120
        _seed(drive, long, turns=3)
        _seed(drive, long.upper(), turns=1)
        await drive.page.set_viewport_size({"width": 390, "height": 844})
        await _open_listing(drive)
        names = await drive.page.locator("#conversation-list .conversation-name").all_inner_texts()
        # Named by when each started, apart from each other, and neither by its id.
        assert len(set(names)) == len(names) == 2
        for named in names:
            assert long not in named
            assert long.upper() not in named
        buttons = _first_row(drive).get_by_role("button")
        await expect(buttons).to_have_count(1)
        await expect(buttons).to_have_text("Forget")
        assert await drive.page.evaluate(
            "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )


async def test_a_forget_refreshes_the_listing_and_states_what_was_forgotten(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """#1371's third clause: "no confirmation or list refresh the owner could read".

    Both halves, in the order the page performs them, as ADR-0293 §11:4 leaves them:
    forgetting is memory-only, so the listing is re-read and the row stays, and the
    page says in words what was forgotten and that only deleting removes the
    conversation (§5:7).
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.hold_conversation("c-1")
        await _answered(drive, "c-1")
        _seed(drive, "c-1", turns=3)
        await _open_listing(drive)
        answered = _answering(drive, accept=True)
        await _first_row(drive).get_by_role("button", name="Forget").click()
        # The ceremony is the show-then-confirm that predates this lane, and it names
        # what the outcome will name -- so the outcome is not merely echoing the id
        # the button carried.
        asked = await answered
        title = await _title(drive, "c-1")
        assert f"Forget the conversation from {title}?" in asked
        assert "only deleting removes it" in asked
        await drive.page.wait_for_selector("#forget-outcome:not([hidden])")
        said = await drive.page.inner_text("#forget-outcome")
        assert said == (
            f"The assistant has forgotten the 3 recorded turn(s) of the conversation from "
            f"{title}, and no longer recalls them anywhere else. The conversation and its "
            "transcript stay; only deleting removes them."
        )
        await expect(drive.page.locator("#conversation-list .conversation-row")).to_have_count(1)
        assert set(drive.engine.conversations_held) == {"c-1"}
        assert await drive.engine.episode_memory.export() == []


async def test_a_forget_that_destroyed_nothing_says_that_instead(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """``forget_conversation`` answers *whether* it forgot anything, and the page reads it.

    Memory-only since ADR-0293 §11:4, so the answer is ``False`` where the
    conversation's place holds no episode — a terminal or another tab may have
    forgotten it already — and the page says that rather than claiming a forgetting
    that did not happen. The seeded digest reports turns its place no longer holds.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "c-1", turns=3)
        await _open_listing(drive)
        answered = _answering(drive, accept=True)
        await _first_row(drive).get_by_role("button", name="Forget").click()
        assert await answered
        await drive.page.wait_for_selector("#forget-outcome:not([hidden])")
        said = await drive.page.inner_text("#forget-outcome")
        assert said == (
            f"The conversation from {await _title(drive, 'c-1')} held nothing in the "
            "assistant's memory, so nothing was forgotten."
        )


async def test_declining_the_ceremony_destroys_nothing_and_states_nothing(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The outcome is written by the act, so an act nobody took writes none.

    ADR-0175 §6 is explicit that the confirmation "is not a control"; that is a
    statement about what it *defends*, and not a licence to render an outcome for a
    destruction that did not happen.

    **The round trip after the dismissal is a synchronisation and not a sleep**
    (ADR-0216 §7). ``confirm`` blocks the page's script thread; dismissing it resumes
    that thread, and everything ``forgetConversation`` does from there to its
    ``return`` is synchronous. So an ``evaluate`` the driver sends afterwards cannot
    be answered until that work has run, which is the happens-after this case needs
    and is a condition of the page rather than a duration.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "c-1", turns=3)
        await _open_listing(drive)
        answered = _answering(drive, accept=False)
        await _first_row(drive).get_by_role("button", name="Forget").click()
        assert await answered
        await drive.page.evaluate("() => null")
        assert await drive.page.is_hidden("#forget-outcome")
        assert set(drive.engine.conversations_held) == {"c-1"}
        assert not [one for one in drive.engine.calls if one[0] == "forget_conversation"]


async def test_a_refresh_that_lost_its_race_does_not_write_over_the_newer_listing(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A forget's outcome is the last word only while its own refresh still is.

    Adversarial review round 1, ``major``. Accept a forget, hold the refresh it
    triggers, press "Conversations", and let the owner's newer read return first: the
    older refresh then resumes and writes its outcome into a slot the newer read had
    cleared, above a listing it did not produce. Counting reads as they *begin* is
    what lets the resuming one see that it is no longer the last word — and the
    outcome is dropped rather than restored, because the page has no way to put it
    back where it would be true.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "c-1", turns=3)
        _seed(drive, "c-2", turns=1)
        held = await _holding(drive, "/conversations", at=2)
        await _open_listing(drive)
        answered = _answering(drive, accept=True)
        await _first_row(drive).get_by_role("button", name="Forget").click()
        assert await answered
        await held.reached.wait()
        await press(drive.page, "#conversations-button")
        # Both rows: forgetting leaves the conversation listed (ADR-0293 §11:4).
        await expect(drive.page.locator("#conversation-list .conversation-row")).to_have_count(2)
        assert await drive.page.is_hidden("#forget-outcome")
        await held.release()
        assert await drive.page.is_hidden("#forget-outcome")


async def test_a_superseded_listing_read_cannot_put_back_a_row_the_newer_one_dropped(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The generation guards the listing itself, and not only the outcome above it.

    Adversarial review round 6, ``major``. Let a read be answered while ``doomed``
    still exists, hold the page's *handling* of that answer, destroy ``doomed`` from
    somewhere else, and let a listing the owner asks for afterwards render the shorter
    truth. The held read resuming last would clear the list and repopulate it from its
    older answer — putting ``doomed`` back as a row for a conversation that is gone,
    which is the page telling the owner something it has already told them is false.

    The older answer is the gateway's own, taken when the page really asked for it;
    only the reading of it is deferred. So what is asserted is what the page does with
    a real stale response, not with one this case wrote.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "kept", turns=3)
        _seed(drive, "doomed", turns=1)
        await drive.page.evaluate(_HOLDING, "/conversations")
        rows = drive.page.locator("#conversation-list .conversation-row")
        await _open_listing(drive)
        await expect(rows).to_have_count(2)
        # The second read is answered while `doomed` is still there, and held.
        await press(drive.page, "#conversations-button")
        await drive.page.wait_for_function("() => window.__held.reached")
        drive.engine.conversations_held.pop("doomed")
        drive.engine.activity.pop("doomed")
        # The third read goes out afterwards and is answered with the shorter truth.
        await press(drive.page, "#conversations-button")
        await expect(rows).to_have_count(1)
        await drive.page.evaluate("() => window.__held.release()")
        # One round trip after the release, which is a later task: every microtask the
        # held read's continuation could have been holding has drained (ADR-0216 §7).
        await drive.page.evaluate("() => null")
        await expect(rows).to_have_count(1)
        assert await rows.nth(0).get_attribute("data-conversation") == "kept"


async def test_a_second_read_of_the_listing_clears_the_outcome_it_did_not_produce(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """An outcome standing above a listing it was never made against is a stale claim.

    The order is the load-bearing part: ``listConversations`` clears the slot on every
    read, and ``forgetConversation`` writes *after* the refresh it triggers — so the
    outcome survives its own refresh and no other.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "c-1", turns=3)
        _seed(drive, "c-2", turns=1)
        await _open_listing(drive)
        answered = _answering(drive, accept=True)
        await _first_row(drive).get_by_role("button", name="Forget").click()
        assert await answered
        await drive.page.wait_for_selector("#forget-outcome:not([hidden])")
        await press(drive.page, "#conversations-button")
        await drive.page.wait_for_selector("#forget-outcome", state="hidden")
        assert await drive.page.inner_text("#forget-outcome") == ""
