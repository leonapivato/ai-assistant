"""The conversation surface, driven (#1371, ADR-0216 §2).

Three gaps the owner found on a phone during milestone 14's QA, and every one of
them is a fact about *time* rather than about the shipped bytes: which
conversation the next ask lands in **after a tap**, what the page says about the
thread **before** a new answer arrives, and what the listing says **after** a
forget returns. ADR-0216 §2 puts exactly that class here — "ordering in time,
concurrency, and what one handler does to a resource another holds" — and leaves
the enumerations and must-contains in ``test_bundle.py``, which is why nothing
below asserts that a string is present in ``app.js``.

The first of the three was already on the page (``da52be6a``) and this module
changes nothing about it. What it adds is the instrument it never had: a substring
assertion that ``renderConversation``'s button calls ``resumeConversation`` pins
the *shape* of the wiring and cannot say that pressing it moves the indicator.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import pytest
from browser_drive import driving

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, Dialog, Locator, Route

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.usefixtures("hermetic_assistant_env"),
]

#: When the seeded thread's last turn was recorded. A fixed instant rather than one
#: computed from the clock: what the cases read back is the page having rendered
#: *this* value, and a stamp derived at run time would put a second implementation
#: of the formatting rule inside the assertion that checks it.
_LAST_TURN = datetime(2026, 8, 22, 9, 15, tzinfo=UTC)

#: Counts the page's own reads of a relayed body, per path, **after the body has been
#: parsed** — installed before any of the bundle runs, in the manner of
#: ``browser_drive``'s Web Audio probe and for the same reason: what the two ordering
#: cases below need to know is when the page has *finished with* a response, and no
#: fact about the network says that.
#:
#: **Why the count is a synchronisation and not a sleep** (ADR-0216 §7). The
#: increment happens inside the ``await response.json()`` the page's ``relay``
#: performs, so the handler that acts on that body is a microtask continuation of it.
#: Every pending microtask drains before the next task runs, and a driver's
#: ``wait_for_function`` poll *is* a later task — so a poll that observes the count
#: has, by construction, run after the page finished deciding what to do with the
#: body. That is the happens-after both cases need, and it is a condition the page
#: reached rather than a duration guessed at.
_SETTLED = """() => {
window.__settled = {};
const realFetch = window.fetch;
window.fetch = async function (resource, options) {
  const response = await realFetch.call(this, resource, options);
  const path = new URL(typeof resource === "string" ? resource : resource.url, location.href)
    .pathname;
  const realJson = response.json.bind(response);
  response.json = async function () {
    const body = await realJson();
    window.__settled[path] = (window.__settled[path] || 0) + 1;
    return body;
  };
  return response;
};
}
"""


def _seed(drive: Drive, conversation_id: str, *, turns: int) -> None:
    """Hold one conversation on the engine, with a history behind it.

    ``FakeAssistantEngine.start_conversation`` records a *fresh* one — no turn yet,
    nothing recorded — which is the state #1371's first clause is about and the
    opposite of the state its second one is. A thread worth resuming already holds
    something, so the digest it recorded is replaced with one that does.

    Args:
        drive: The gateway, engine and page under test.
        conversation_id: The id to hold.
        turns: How many recorded turns its digest reports.
    """
    drive.engine.start_conversation(conversation_id)
    held = drive.engine.conversations_held[conversation_id]
    drive.engine.conversations_held[conversation_id] = held.model_copy(
        update={"recorded_turns": turns, "last_turn_at": _LAST_TURN}
    )


async def _open_listing(drive: Drive) -> None:
    """Press Conversations and wait for the panel to be showing."""
    await drive.page.click("#conversations-button")
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


def _first_row(drive: Drive) -> Locator:
    """The listing's first row, whichever conversation the ordering put there.

    Named rather than inlined because a bare ``button:text('Forget')`` over a listing
    of two is a strict-mode violation, and ``.first`` written at each call site is the
    kind of detail that is right in the case somebody copies and wrong in the copy.
    """
    return drive.page.locator("#conversation-list .conversation-row").first


async def test_the_row_the_owner_taps_names_the_conversation_it_will_continue(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The tap is a choice, and a choice needs the thing being chosen on screen.

    A text assertion can say the row *renders* the id; what it cannot say is that the
    id it renders is the one the indicator names afterwards. That is the property
    worth having — the two are written by different functions from different
    responses, and a listing keyed by activity and an indicator keyed by a tap are
    exactly the pair that can disagree.

    It is also laid out so an id cannot push the row off a phone: the name has the
    whole width of the row, and the page scrolls no further sideways than it did.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "c-1", turns=3)
        _seed(drive, "c-2", turns=1)
        await drive.page.set_viewport_size({"width": 390, "height": 844})
        await _open_listing(drive)
        named = await _first_row(drive).locator(".conversation-name").inner_text()
        assert named in {"Conversation c-1", "Conversation c-2"}
        await _first_row(drive).get_by_role("button", name="Continue").click()
        await drive.page.wait_for_selector("#resumed:not([hidden])")
        said = await drive.page.inner_text("#conversation")
        assert said == f"{named}. Your next question continues it."
        assert await drive.page.evaluate(
            "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )


async def test_tapping_continue_moves_the_indicator_to_that_conversation(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """#1371's first clause, as a fact about a tap rather than about a file.

    The owner's report was that after tapping a conversation in the list they could
    not tell which one the next ask would land in. The line that answers it is on the
    page and ``test_bundle.py`` pins its two sentences; what no reading of ``app.js``
    decides is whether pressing the button the listing renders actually reaches it.
    This presses it.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "c-1", turns=3)
        # Before the tap the page says the *other* of the two sentences, which is what
        # makes the assertion after it about the tap rather than about the default.
        assert "No conversation yet" in await drive.page.inner_text("#conversation")
        await _open_listing(drive)
        await _first_row(drive).get_by_role("button", name="Continue").click()
        await drive.page.wait_for_function(
            "() => document.getElementById('conversation').textContent.includes('c-1')"
        )
        said = await drive.page.inner_text("#conversation")
        assert said == "Conversation c-1. Your next question continues it."


async def test_leaving_the_thread_moves_the_indicator_back(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """And the control out of a thread moves it back, which is the other direction.

    A page that only ever moved the indicator *into* a conversation would read as
    correct on the tap above and still leave the owner unable to tell they had left
    one — the state ``startFresh`` exists to reach.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "c-1", turns=3)
        await _open_listing(drive)
        await _first_row(drive).get_by_role("button", name="Continue").click()
        await drive.page.wait_for_selector("#new-conversation:not([hidden])")
        await drive.page.click("#new-conversation")
        await drive.page.wait_for_function(
            "() => document.getElementById('conversation').textContent"
            + ".includes('No conversation yet')"
        )
        assert await drive.page.is_hidden("#new-conversation")


async def test_resuming_states_what_the_thread_already_holds_before_any_new_ask(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """#1371's second clause, in the half the ratified contracts admit.

    "The page renders only the answer to the new ask, never the prior turns, so
    resume is invisible until the assistant references earlier context." The whole of
    the owner's complaint is about the moment *before* a new answer, so that is where
    this asserts: nothing has been asked, and the page already says the thread is not
    empty and how far back it goes.

    It is the count and the span, because that is the whole of what ``conversation``
    hands a browser (ADR-0074 §8). The transcript half is #1818.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "c-1", turns=3)
        await _open_listing(drive)
        assert await drive.page.is_hidden("#resumed")
        await _first_row(drive).get_by_role("button", name="Continue").click()
        await drive.page.wait_for_selector("#resumed:not([hidden])")
        said = await drive.page.inner_text("#resumed")
        assert "3 recorded turn(s)" in said
        assert "2026-08-22" in said
        # Nothing was asked and no answer panel was ever shown, which is the property
        # the clause is actually about: resume used to be invisible until one arrived.
        assert await drive.page.is_hidden("#answer")


async def test_a_thread_with_nothing_in_it_says_so_rather_than_printing_a_broken_span(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A conversation with no turn is a real state and reads as one.

    ``last_turn_at`` is ``None`` where no turn was ever recorded, and a span printed
    with a missing end is a span nobody can read — the rule ``renderConversation``
    already keeps one line up for the listing's own hint.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.start_conversation("c-1")
        await _open_listing(drive)
        await _first_row(drive).get_by_role("button", name="Continue").click()
        await drive.page.wait_for_selector("#resumed:not([hidden])")
        said = await drive.page.inner_text("#resumed")
        assert "Nothing has been recorded in it yet." in said
        assert "null" not in said
        assert "undefined" not in said


async def test_the_resumed_line_goes_when_the_owner_leaves_the_thread(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A count about a thread nobody is in is a claim the page must not leave standing.

    This is the invariant ``setConversation`` carries, and it is why the clear lives
    there rather than in the one caller: every route that changes the selection
    invalidates the digest, and a reader cannot tell a stale count from a fresh one.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "c-1", turns=3)
        await _open_listing(drive)
        await _first_row(drive).get_by_role("button", name="Continue").click()
        await drive.page.wait_for_selector("#resumed:not([hidden])")
        await drive.page.click("#new-conversation")
        await drive.page.wait_for_selector("#resumed", state="hidden")
        assert await drive.page.inner_text("#resumed") == ""


async def test_a_forget_refreshes_the_listing_and_states_that_it_is_gone(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """#1371's third clause: "no confirmation or list refresh the owner could read".

    Both halves, in the order the page performs them. The row goes — which is the
    listing having been re-read against an engine that no longer holds it — and the
    page says so in words, which is the half a shorter list on a phone does not
    supply.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "c-1", turns=3)
        await _open_listing(drive)
        answered = _answering(drive, accept=True)
        await _first_row(drive).get_by_role("button", name="Forget").click()
        # The ceremony is the show-then-confirm that predates this lane, and it names
        # what the outcome will name -- so the outcome is not merely echoing the id
        # the button carried.
        assert "Destroy conversation c-1?" in await answered
        await drive.page.wait_for_selector("#forget-outcome:not([hidden])")
        said = await drive.page.inner_text("#forget-outcome")
        assert said == (
            "Conversation c-1 is gone. It held 3 recorded turn(s), "
            "and the episodes they index went with it."
        )
        assert "No conversations yet." in await drive.page.inner_text("#conversation-list")
        assert drive.engine.conversations_held == {}


async def test_a_forget_that_destroyed_nothing_says_that_instead(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """``forget_conversation`` answers *whether* there was one, and the page reads it.

    The race is real and it is the one ADR-0175 §6 leaves open by design: the
    conversation is the hub's, so a terminal or another tab can destroy it between
    this page's digest read and its forget. Until this lane the page discarded the
    answer and reported a destruction that had not happened.

    The engine is emptied behind the page's back at exactly that moment — after the
    digest has been read and while the ceremony is on screen — which is not a
    contrived state but the only one in which the two branches differ.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "c-1", turns=3)
        await _open_listing(drive)

        def emptied() -> None:
            drive.engine.conversations_held.clear()
            drive.engine.activity.clear()

        answered = _answering(drive, accept=True, first=emptied)
        await _first_row(drive).get_by_role("button", name="Forget").click()
        assert await answered
        await drive.page.wait_for_selector("#forget-outcome:not([hidden])")
        said = await drive.page.inner_text("#forget-outcome")
        assert said == "There was no conversation c-1 left to forget, so nothing was destroyed."


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


async def test_an_answer_landing_first_is_not_undone_by_the_digest_behind_it(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A digest still in flight when a turn lands must not re-render a count it made stale.

    Adversarial review round 1, ``major``, and the whole reason the guard counts
    invalidations of the line rather than changes of selection. Continue ``c-1``, ask
    a question in ``c-1`` while the digest read is still out, and let the answer
    arrive first: ``renderOutcome`` reaches ``setConversation`` without touching
    ``chose``, so a guard written against ``chose`` would let the digest through and
    put back a count that is short by the turn just recorded.

    An answer is one of the invalidators, and the *other* case is a different thread
    being chosen — driven separately below, because only this one reaches
    ``setConversation`` without passing through ``changeConversation``.

    The digest request is held rather than raced for: ADR-0216 §7 forbids a fixed
    sleep, and an ordering the driver *decides* is the only kind that cannot be lost
    on a loaded runner. Nothing about the response is fabricated — what the page ends
    up not being told is decided by the page, not by this test.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "c-1", turns=3)
        reached = asyncio.Event()
        released = asyncio.Event()
        settled = asyncio.Event()
        held: dict[str, object] = {}

        async def hold(route: Route) -> None:
            held["request"] = route.request
            reached.set()
            await released.wait()
            with contextlib.suppress(Exception):
                await route.continue_()

        def note(request: object) -> None:
            if request is held.get("request"):
                settled.set()

        drive.page.on("requestfailed", note)
        drive.page.on("requestfinished", note)
        await drive.page.route(lambda url: urlparse(url).path == "/conversation", hold)
        await _open_listing(drive)
        await _first_row(drive).get_by_role("button", name="Continue").click()
        await reached.wait()
        await drive.page.fill("#utterance", "what did we decide?")
        await drive.page.click("#ask-button")
        # `releaseAsk` is the page's own "this turn is over", and it runs after the
        # outcome has been rendered -- so past this the answer has already reached
        # `setConversation`.
        await drive.page.wait_for_selector("#ask-button:not([disabled])")
        assert await drive.page.is_hidden("#resumed")
        released.set()
        await settled.wait()
        await drive.page.evaluate("() => null")
        assert not [one for one in drive.engine.calls if one[0] == "conversation"]
        assert await drive.page.is_hidden("#resumed")


async def test_a_digest_for_a_thread_the_owner_has_left_reports_nothing_at_all(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A read nobody is waiting for is stopped, not merely ignored.

    Adversarial review round 2, ``major``. A guard on what this page *renders* leaves
    the refusal path uncovered, because ``relay`` classifies a refusal and writes it
    into the panel's fault slot itself, before any caller sees a value. Continue
    ``c-1`` with its digest held, continue ``c-2`` and get its answer, let ``c-1`` be
    destroyed from somewhere else, and the abandoned read would report "There is no
    conversation of that name" over a panel whose selection and resumed line are
    about ``c-2``.

    So the read is aborted when the line it would write is cleared, and the assertion
    is the strong one that follows: the gateway is never asked at all.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        _seed(drive, "c-1", turns=3)
        _seed(drive, "c-2", turns=9)
        reached = asyncio.Event()
        released = asyncio.Event()
        settled = asyncio.Event()
        abandoned: dict[str, object] = {}
        reads = {"n": 0}

        async def hold_the_first_digest(route: Route) -> None:
            reads["n"] += 1
            if reads["n"] == 1:
                abandoned["request"] = route.request
                reached.set()
                await released.wait()
            # The abandoned request is cancelled while this handler is held, so
            # continuing it raises rather than returning -- which is the fix working.
            with contextlib.suppress(Exception):
                await route.continue_()

        def note(request: object) -> None:
            if request is abandoned.get("request"):
                settled.set()

        drive.page.on("requestfailed", note)
        drive.page.on("requestfinished", note)
        await drive.page.route(
            lambda url: urlparse(url).path == "/conversation", hold_the_first_digest
        )
        await _open_listing(drive)
        rows = drive.page.locator("#conversation-list .conversation-row")
        first = await rows.nth(0).locator(".conversation-name").inner_text()
        await rows.nth(0).get_by_role("button", name="Continue").click()
        await reached.wait()
        # The thread the abandoned read is about is destroyed from somewhere that is
        # not this page, which is the state that makes its refusal a refusal.
        left = first.removeprefix("Conversation ")
        drive.engine.conversations_held.pop(left)
        drive.engine.activity.pop(left)
        await rows.nth(1).get_by_role("button", name="Continue").click()
        await drive.page.wait_for_selector("#resumed:not([hidden])")
        stated = await drive.page.inner_text("#resumed")
        released.set()
        await settled.wait()
        # One round trip, which is a later task: every microtask the abandoned read
        # could still have been holding has drained by the time this answers.
        await drive.page.evaluate("() => null")
        # The read for the thread the owner left never reached the gateway at all; the
        # one for the thread they are in did.
        asked = [
            one[1]["conversation_id"] for one in drive.engine.calls if one[0] == "conversation"
        ]
        assert left not in asked
        assert asked
        assert await drive.page.inner_text("#resumed") == stated
        assert "no conversation" not in (await drive.page.inner_text("#conversations")).lower()


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
        await drive.page.evaluate(_SETTLED)
        reached = asyncio.Event()
        released = asyncio.Event()
        reads = {"n": 0}

        async def hold_the_refresh(route: Route) -> None:
            reads["n"] += 1
            # The first read is the panel opening and the second is the forget's own
            # refresh; only that one is held.
            if reads["n"] == 2:
                reached.set()
                await released.wait()
            await route.continue_()

        await drive.page.route(lambda url: urlparse(url).path == "/conversations", hold_the_refresh)
        await _open_listing(drive)
        answered = _answering(drive, accept=True)
        await _first_row(drive).get_by_role("button", name="Forget").click()
        assert await answered
        await reached.wait()
        await drive.page.click("#conversations-button")
        await drive.page.wait_for_function("() => (window.__settled['/conversations'] || 0) === 2")
        assert await drive.page.is_hidden("#forget-outcome")
        released.set()
        await drive.page.wait_for_function("() => (window.__settled['/conversations'] || 0) === 3")
        assert await drive.page.is_hidden("#forget-outcome")


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
        await drive.page.click("#conversations-button")
        await drive.page.wait_for_selector("#forget-outcome", state="hidden")
        assert await drive.page.inner_text("#forget-outcome") == ""
