"""What a listing may do when its session ends underneath it (#2404, #2395).

**The shape.** A listing reads the header half, ``await``s its request, and on a ``200``
renders its rows and calls ``show(panel, true)``. If the session ends while that request
is out — any *other* request meeting ``no-live-session``, which routes through
``refused`` → ``report`` → ``sessionLost`` → ``showBootstrap`` — the half is forgotten
and every control panel is hidden, but nothing invalidates the run in flight. The
generation counters order two *listings*; they say nothing about the session under them.
So the late ``200`` resumes, renders, and re-reveals its panel: the owner's rows on
screen beside a form asking them to start a session.

PR #2393's adversarial review found it at round 9 in ``listAuthorizations`` and fixed it
there; the arm it left is
``test_browser_authorizations.py::test_a_listing_that_outlives_its_session_reveals_nothing``
and it is the template every case here is written on. This module is the sweep #2404
asked for: one arm per listing that calls ``show(...)`` after an ``await``, driven at
both of ADR-0233 §15's widths.

**Nothing here sleeps** (ADR-0216 §7). What is asserted is a state the page must *not*
reach, and a bare retrying assertion would pass the instant before the reveal it is
looking for — so each case needs an ordering rather than a duration, and takes one: the
stale response is awaited to its **last byte**, and then a whole network round trip is
made through the page's own form. A resumed listing whose body has fully arrived cannot
still be pending across a round trip, so by the time that completes the continuation has
run. Re-entry reveals no control panel of its own — ``showConsole`` shows the console,
the notification panel and the control entry points and nothing else — so a control panel
visible at the end was revealed by the stale response.

**The census that says this list is complete** is in ``test_bundle.py``
(``test_every_listing_that_resumes_asks_whether_its_session_still_stands``), which is
universally quantified over the script: a listing added later is covered by the rule
rather than by anybody remembering to extend the table below.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest
from browser_drive import DESKTOP, PHONE, driving
from gateway_mint import bootstrap_value
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import expect
from test_browser_confirmations import _email, _read
from test_browser_conversations import _open_listing
from test_browser_conversations import _seed as _seed_conversation

from ai_assistant.core.types import GoalStatus, GoalSummary

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, Dialog, Route, ViewportSize

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

GOAL_ID: Final = "goal-late-4041"
OUTCOME: Final = "Find somewhere for the Tuesday dinner"


@dataclass(frozen=True)
class _Listing:
    """One audited listing: what opens it, what it asks for, and what it renders into.

    Attributes:
        panel: The ``section.panel`` id the listing reveals.
        opener: The control the owner presses to start it.
        path: The glob its request is routed by.
        rendered: The node its rows are rendered into — empty of elements is what
            "rendered nothing" means, because an *empty* listing still writes a hint
            line into it, so a continuation that ran at all leaves a child behind.
    """

    panel: str
    opener: str
    path: str
    rendered: str


#: Every listing that calls ``show(...)`` after an ``await`` — the audit #2404 asked for.
#:
#: ``authorizations`` is not here because it already has its own arm, written with the
#: fix PR #2393 made and now exercising the shared guard that replaced it. Two acts read
#: a listing after an ``await`` as well — ``forgetQuestion`` and ``forgetNotification``
#: re-read their listing to confirm against — and neither is here because neither renders
#: rows or reveals a panel on its success path: what they do with the answer is put a
#: ``window.confirm`` in front of the owner.
_AUDITED: Final = (
    _Listing("confirmations", "#confirmations-button", "**/confirmations", "confirmation-list"),
    _Listing("conversations", "#conversations-button", "**/conversations", "conversation-list"),
    _Listing("sources", "#sources-button", "**/sources", "source-list"),
    _Listing("standing", "#standing-button", "**/grants/standing", "standing-list"),
    _Listing("history", "#history-button", "**/grants/recent", "history-list"),
    _Listing("beliefs", "#beliefs-button", "**/beliefs", "belief-list"),
    _Listing("questions", "#questions-button", "**/questions", "question-list"),
    _Listing("review", "#review-button", "**/notifications", "review-list"),
    _Listing("goals", "#goals-button", "**/goals", "goal-list"),
    _Listing("tuning", "#tuning-button", "**/notification/preferences", "tuning-body"),
    _Listing("connections", "#connections-button", "**/connections", "connection-list"),
    _Listing(
        "connection-log", "#connection-log-button", "**/connections/recent", "connection-log-list"
    ),
    _Listing("observation", "#observe-button", "**/observe", "observation-body"),
)

#: The request each case ends the session with: one the page makes for a *different*
#: panel, so that what invalidates the run in flight is a condition reported elsewhere —
#: which is the whole of #2404's shape. The sources listing ends its own session with the
#: beliefs read instead, for the obvious reason.
_KILLER: Final = ("#sources-button", "**/sources")
_OTHER_KILLER: Final = ("#beliefs-button", "**/beliefs")


def _summary() -> GoalSummary:
    """One outstanding goal, so that "rendered nothing" is a statement about content."""
    return GoalSummary(
        id=GOAL_ID,
        outcome=OUTCOME,
        status=GoalStatus.ACTIVE,
        paused=False,
        last_engaged_at=datetime(2026, 9, 15, 9, 0, tzinfo=UTC),
        clarification=None,
    )


async def _ends_the_session(one: Route) -> None:
    """Answer one request the way a gateway answers a session that is gone."""
    await one.fulfill(
        status=401,
        content_type="application/json",
        body=json.dumps({"fault": "no-live-session"}),
    )


async def _refused_at_the_door(one: Route) -> None:
    """Answer one request the way a gateway answers the *other* session condition.

    ``cookie-half-mismatch`` is what a request sent under the old header half with the
    new session's cookie really meets, and it is a refusal the gateway decides at the
    door: the hub never saw the request, so the act is known **not** to have landed.
    """
    with contextlib.suppress(PlaywrightError):
        await one.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps({"fault": "cookie-half-mismatch"}),
        )


def _held(
    loop: asyncio.AbstractEventLoop,
) -> tuple[asyncio.Future[None], Callable[[Route], Awaitable[None]]]:
    """A route that holds its request until the case lets it go."""
    release: asyncio.Future[None] = loop.create_future()

    async def hang(one: Route) -> None:
        await release
        # The page may have been navigated away from under a held route by the time
        # this resumes in a failing run; the case's own assertions are what report it.
        with contextlib.suppress(PlaywrightError):
            await one.fallback()

    return release, hang


async def _empty(drive: Drive, node: str) -> int:
    """How many elements a listing has rendered into its node.

    ``inner_text`` would answer ``""`` for every one of these whether or not anything
    was rendered, because the panel under test is hidden — which is the assertion, and
    would make the assertion vacuous. Counting children asks the document instead.
    """
    return int(await drive.page.locator(f"#{node}").evaluate("node => node.childElementCount"))


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
@pytest.mark.parametrize("listing", _AUDITED, ids=[one.panel for one in _AUDITED])
async def test_a_listing_that_outlives_its_session_renders_nothing_and_reveals_nothing(
    gateway_browser: Browser, tmp_path: Path, listing: _Listing, viewport: ViewportSize
) -> None:
    """The sweep: one arm per audited listing, at both widths (#2404).

    The listing is started and held. The session then ends through a request of another
    panel's — the page's own, refused ``no-live-session`` — so what the held run has to
    notice is a condition it never saw. It is released, awaited to its last byte, and the
    owner re-enters through the page's own form; the panel must be hidden and its node
    must hold nothing, an empty listing's hint line included, because a continuation that
    rendered at all writes one.
    """
    loop = asyncio.get_running_loop()
    release, hang = _held(loop)
    opener, killer = _OTHER_KILLER if listing.path == _KILLER[1] else _KILLER

    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.engine.goal_summaries = [_summary()]
        await drive.page.route(listing.path, hang)
        async with drive.page.expect_request(listing.path):
            await drive.page.click(listing.opener)

        # The session ends under the held listing, through a request of its own.
        await drive.page.route(killer, _ends_the_session)
        await drive.page.click(opener)
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")

        async with drive.page.expect_response(listing.path) as stale:
            release.set_result(None)
        await (await stale.value).finished()
        await drive.admit()

        await expect(drive.page.locator(f"#{listing.panel}")).to_be_hidden()
        assert await _empty(drive, listing.rendered) == 0


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_a_listing_released_after_re_entry_is_not_the_new_session_s_answer(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """Rows fetched under the old session are not the new one's answer.

    The half the request was sent under is gone and a *different* one is held by the
    time it comes back, which is the direction a generation counter cannot see and a
    comparison against the current half can. Here the owner re-enters **before** the
    stale response is released, so the page is on the console with a live session when
    the continuation runs: nothing is hidden by the bootstrap form, and a panel that
    opened opened because this response opened it.

    The ordering is a whole network round trip made *after* the stale body has fully
    arrived — the beliefs read, which only a page holding a session makes at all.
    """
    loop = asyncio.get_running_loop()
    release, hang = _held(loop)

    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.engine.goal_summaries = [_summary()]
        await drive.page.route("**/goals", hang)
        async with drive.page.expect_request("**/goals"):
            await drive.page.click("#goals-button")

        await drive.page.route("**/sources", _ends_the_session)
        await drive.page.click("#sources-button")
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")

        # Re-entry, and only then the old session's answer.
        await drive.admit()
        async with drive.page.expect_response("**/goals") as stale:
            release.set_result(None)
        await (await stale.value).finished()
        async with drive.page.expect_response("**/beliefs"):
            await drive.page.click("#beliefs-button")

        # The session the owner has just started is still theirs. The held request
        # carried the old header half and the *new* cookie, so the gateway answered
        # `cookie-half-mismatch` — and a page that reported that refusal would have
        # forgotten the new half and put the bootstrap form back, a dead request ending
        # a live session.
        await expect(drive.page.locator("#bootstrap")).to_be_hidden()
        await expect(drive.page.locator("#console")).to_be_visible()
        await expect(drive.page.locator("#goals")).to_be_hidden()
        assert OUTCOME not in await drive.page.locator("#goal-list").evaluate(
            "node => node.textContent"
        )


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_the_goals_panel_is_hidden_when_the_session_ends(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """#2395: ``CONTROL_PANELS`` omitted ``goals``, so the sweep never reached it.

    Nothing about a request in flight here: the panel is open and full, the session ends
    through the next act the owner takes, and the goal's outcome statement stayed on
    screen behind the bootstrap form for as long as they left it there.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.engine.goal_summaries = [_summary()]
        await drive.page.click("#goals-button")
        await expect(drive.page.locator("#goal-list")).to_contain_text(OUTCOME)

        await drive.page.route("**/sources", _ends_the_session)
        await drive.page.click("#sources-button")
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")

        await expect(drive.page.locator("#goals")).to_be_hidden()
        assert OUTCOME not in await drive.page.inner_text("body")


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_a_refusal_answered_to_a_dead_session_opens_no_panel(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """The other half of the reveal, and the one a caller's guard cannot reach.

    ``relay`` renders a refusal **before** it returns — ``refused`` → ``report`` →
    ``fault`` → ``show(panel, true)`` — so a listing refused for some ordinary reason
    after its session has ended re-opens its panel beside the bootstrap form carrying
    the condition.

    **The condition goes with the opening**, which is the rule this lane ships whole: a
    resumed continuation whose session has ended puts nothing on the screen. What is
    withheld here is ``GATEWAY_GONE`` — a sentence about a gateway that "may have
    stopped", over a session that had already ended, into a panel the owner has closed.
    Whether a page still *looking* at that panel is owed the condition anyway is #2451,
    which two rounds of review answered in opposite directions.
    """
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()

    async def refuses(one: Route) -> None:
        await release
        with contextlib.suppress(PlaywrightError):
            await one.fulfill(
                status=404,
                content_type="application/json",
                body=json.dumps({"fault": "no-such-thing"}),
            )

    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        await drive.page.route("**/beliefs", refuses)
        async with drive.page.expect_request("**/beliefs"):
            await drive.page.click("#beliefs-button")

        await drive.page.route("**/sources", _ends_the_session)
        await drive.page.click("#sources-button")
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")

        async with drive.page.expect_response("**/beliefs") as stale:
            release.set_result(None)
        await (await stale.value).finished()
        await drive.admit()

        await expect(drive.page.locator("#beliefs")).to_be_hidden()
        assert "The gateway did not answer" not in await drive.page.locator("#beliefs").evaluate(
            "node => node.textContent"
        )


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_a_preference_write_is_not_sent_under_a_session_that_has_ended(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """The one act in the sweep, where the guard has to come before the *request*.

    ``writePreferences`` is a read-modify-write: it re-reads the whole value, changes the
    one thing the control names, and sends the whole value back. If the session ends
    while that read is out, resuming would put the modified value on the wire under a
    header half the gateway no longer admits — a request answered ``no-live-session``,
    for a write the owner will have to make again, from a page that has already told them
    their session is gone.
    """
    loop = asyncio.get_running_loop()
    release, hang = _held(loop)
    written = []

    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.page.on("request", lambda one: written.append(one.url))
        await drive.page.click("#tuning-button")
        await drive.page.wait_for_selector("#tuning:not([hidden])")

        await drive.page.route("**/notification/preferences", hang)
        await drive.page.fill("#reach-class", "delivery")
        async with drive.page.expect_request("**/notification/preferences"):
            await drive.page.get_by_role("button", name="Set", exact=True).click()

        await drive.page.route("**/sources", _ends_the_session)
        await drive.page.click("#sources-button")
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")

        async with drive.page.expect_response("**/notification/preferences") as stale:
            release.set_result(None)
        await (await stale.value).finished()
        await drive.admit()

        await expect(drive.page.locator("#tuning")).to_be_hidden()
        assert not [one for one in written if one.endswith("/notification/preferences/set")]


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_a_listing_whose_request_fails_after_its_session_ended_opens_no_panel(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """The failing path reveals a panel too, and adversarial review round 1 found it.

    Every other case here supplies a completed response. This one supplies none: the held
    request is aborted after the session ends, ``relay``'s ``fetch`` rejects, and the
    caller's ``catch`` calls ``fault(GATEWAY_GONE, panel)`` — which *shows* the panel it
    writes into. So a control panel opens beside the bootstrap form moments after
    ``showBootstrap`` hid every panel and cleared every fault slot, carrying a condition
    about a session that no longer exists and that the owner could do nothing with.

    Driven at the beliefs listing; the census in ``test_bundle.py`` is what says every
    other ``catch`` compares the same way.
    """
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()

    async def fails(one: Route) -> None:
        await release
        with contextlib.suppress(PlaywrightError):
            await one.abort("connectionreset")

    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        await drive.page.route("**/beliefs", fails)
        async with drive.page.expect_request("**/beliefs"):
            await drive.page.click("#beliefs-button")

        await drive.page.route("**/sources", _ends_the_session)
        await drive.page.click("#sources-button")
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")

        async with drive.page.expect_event(
            "requestfailed", predicate=lambda one: one.url.endswith("/beliefs")
        ):
            release.set_result(None)
        await drive.admit()

        await expect(drive.page.locator("#beliefs")).to_be_hidden()
        assert await _empty(drive, "belief-list") == 0


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_an_answer_refused_at_the_door_after_re_entry_strands_no_token(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """The guard withholds the reveal and must not withhold the classification.

    ``relay`` hands one caller the refusal it read, because the difference between two
    refusals is what decides whether a consent token comes back (ADR-0177 §7's third
    clause). Dropping that for a request whose session has ended reads as "a refusal this
    page cannot classify at all", which takes the not-known branch: the token is stranded,
    the listing is re-read, and the owner is told an action *may* have been carried
    out — of a request the gateway refused at its own door, which the hub never saw.

    Adversarial review, round 1, ``major``. What is asserted is the **account**: a
    sentence there is this page claiming not to know something it does know. The panel
    itself is not asserted on, and deliberately — re-entry's ``showConsole`` takes a
    quiet read of the pending listing, so under the new session the panel opens again
    with the park still waiting, which is that session's own answer and not this one's.
    """
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()

    async def door(one: Route) -> None:
        await release
        await _refused_at_the_door(one)

    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.engine.parked["h-1"] = _email()
        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")

        await drive.page.route("**/confirmation/resume", door)
        row = drive.page.locator("#confirmation-list .confirmation-row").first
        async with drive.page.expect_request("**/confirmation/resume"):
            await row.locator("button", has_text="Yes, do it").click()

        await drive.page.route("**/sources", _ends_the_session)
        await drive.page.click("#sources-button")
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")

        async with drive.page.expect_response("**/confirmation/resume") as stale:
            release.set_result(None)
        await (await stale.value).finished()
        await drive.admit()

        await expect(drive.page.locator("#answer-said")).to_be_hidden()
        assert "the action may have been carried out" not in await drive.page.inner_text("body")


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_a_cancellation_refused_at_the_door_after_re_entry_settles_nothing(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """The same, for the other caller that asks to be told which refusal it met.

    ``cancelRead`` reads the condition to choose between ``CANCELLATION_UNRESOLVED`` and
    a refusal known not to have landed (ADR-0244 §11). Withholding it settles the act as
    unresolved and writes an account saying the connection failed before a reply was
    read, of a reply this browser read in full. The panel is not asserted on, for the
    reason the case above gives.
    """
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()

    async def door(one: Route) -> None:
        await release
        await _refused_at_the_door(one)

    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.engine.read_parked["r-1"] = _read()
        drive.engine._read_handles.add("r-1")
        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")

        await drive.page.route("**/confirmation/cancel-read", door)
        row = drive.page.locator("#confirmation-list .confirmation-row").first
        async with drive.page.expect_request("**/confirmation/cancel-read"):
            await row.locator("button", has_text="Cancel this lookup").click()

        await drive.page.route("**/sources", _ends_the_session)
        await drive.page.click("#sources-button")
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")

        async with drive.page.expect_response("**/confirmation/cancel-read") as stale:
            release.set_result(None)
        await (await stale.value).finished()
        await drive.admit()

        await expect(drive.page.locator("#cancellation-said")).to_be_hidden()
        assert "before this browser read a reply" not in await drive.page.inner_text("body")


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_a_record_read_to_be_confirmed_over_is_not_put_after_its_session_ends(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """A ``window.confirm`` is display, and adversarial review round 2 found it uncovered.

    ``forgetConversation`` and its three siblings read the record they are about to
    destroy so that what the owner confirms is something the page has just seen. The read
    is the only thing that has happened when it resumes — nothing has been destroyed, so
    there is nothing owed an account — and what it does with the answer is put the
    record's content in front of the owner: a conversation's id and its recorded turn
    count here, a belief's content and confidence one function over, a notification's
    summary in a third.

    So a read that outlives its session opens a modal over the bootstrap form quoting the
    owner's records, and the first version of this sweep stepped past all four because it
    selected functions carrying a literal ``show(..., true)``. What is asserted is that no
    dialog is raised at all: a dismissed one has already been read.
    """
    loop = asyncio.get_running_loop()
    release, hang = _held(loop)
    raised: list[str] = []
    # Held so a dismissal in flight is not garbage-collected, and held here rather than
    # in a global so two cases cannot share it.
    dismissing: list[asyncio.Task[None]] = []

    async def dismiss(one: Dialog) -> None:
        raised.append(one.message)
        await one.dismiss()

    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.page.on("dialog", lambda one: dismissing.append(loop.create_task(dismiss(one))))
        _seed_conversation(drive, "c-1", turns=3)
        await _open_listing(drive)

        await drive.page.route("**/conversation", hang)
        async with drive.page.expect_request("**/conversation"):
            await (
                drive.page.locator("#conversation-list .conversation-row")
                .first.get_by_role("button", name="Forget")
                .click()
            )

        await drive.page.route("**/sources", _ends_the_session)
        await drive.page.click("#sources-button")
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")

        async with drive.page.expect_response("**/conversation") as stale:
            release.set_result(None)
        await (await stale.value).finished()
        await drive.admit()

        assert raised == []
        await expect(drive.page.locator("#conversations")).to_be_hidden()


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_a_destruction_consented_under_a_session_that_ended_ends_no_other(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """Two tabs, which is how a live session meets a request from a dead one.

    ``window.confirm`` blocks *this page's* script thread and nothing else, and a session
    belongs to the browser rather than to a tab. So: the destroy ceremony is on screen in
    one tab, a fresh session is started in another — which replaces the cookie the first
    tab's requests carry — and the consent then goes out under a header half the gateway
    no longer admits. It is refused at the door.

    What that refusal must not do is end the session the other tab has just started.
    ``refused`` → ``report`` → ``sessionLost`` would forget the new half and throw this
    tab back to the bootstrap form: a dead request ending a live one, from the one door a
    comparison after the ``await`` cannot reach, which is why the guard is inside
    ``relay``. And the destruction must not be *reported*, because it did not happen.

    Whether this tab — looking straight at the panel it pressed the control in — is owed
    the condition as well is **#2451**, and this lane does not decide it: rounds 3 and 4
    answered it in opposite directions over the same per-panel fault slot, so what ships
    is the uniform rule with no race in it.

    Nothing here turns on the first tab *noticing* the storage change — it cannot, and
    that is measured rather than assumed: its renderer is blocked by the ceremony, so a
    cross-tab write to the shared half is not visible to it until after the script that
    would read it has run. What it acts on is the answer it gets.
    """
    loop = asyncio.get_running_loop()
    answering: list[asyncio.Task[None]] = []

    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        elsewhere = await drive.page.context.new_page()
        await elsewhere.goto(f"{drive.origin}/")

        async def consent(one: Dialog) -> None:
            # A whole second session, through the page's own form: minted, disclosed and
            # promoted, which is what replaces the cookie this tab's next request carries.
            #
            # The half is dropped and the page reloaded first, because that tab is holding
            # the *same* session and shows the console rather than the entry form — the
            # storage is shared, which is the whole premise. It is done here rather than
            # in the setup because the first tab reads the half it sends before the
            # ceremony opens, and a page with none goes to the bootstrap form instead.
            await elsewhere.evaluate(
                "() => window.localStorage.removeItem('assistant.session.header-half')"
            )
            await elsewhere.reload()
            await elsewhere.fill("#bootstrap-value", bootstrap_value(drive.gateway))
            await elsewhere.click("#bootstrap-form button[type=submit]")
            await elsewhere.wait_for_selector("#console:not([hidden])")
            await one.accept()

        drive.page.on("dialog", lambda one: answering.append(loop.create_task(consent(one))))
        _seed_conversation(drive, "c-1", turns=3)
        await _open_listing(drive)

        await (
            drive.page.locator("#conversation-list .conversation-row")
            .first.get_by_role("button", name="Forget")
            .click()
        )

        # The session the other tab holds is still theirs: this tab was not thrown back
        # to the bootstrap form by a request that belonged to the session before it, and
        # the conversation it did not destroy is not reported as gone. The listing is
        # what orders the assertions -- only a page still holding a session makes it.
        async with drive.page.expect_response("**/conversations"):
            await drive.page.click("#conversations-button")
        await expect(drive.page.locator("#bootstrap")).to_be_hidden()
        await expect(drive.page.locator("#console")).to_be_visible()
        assert "is gone" not in await drive.page.inner_text("#conversations")


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_a_destruction_that_lands_after_its_session_ended_opens_nothing(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """The *second* request of a two-request flow, held (adversarial review, round 5).

    The ceremony is answered while the session is live, the destruction goes out, and the
    session ends under it — so what resumes is the act's own continuation rather than a
    prerequisite read's. It re-reads the listing, and that read is a listing like any
    other: it renders nothing and reveals nothing once the session it was asked under is
    gone.

    What it *does* say is written into the panel rather than onto the screen:
    ``sayForgotten`` fills a node inside the conversations panel and reveals nothing, so
    the account of a destruction that really happened waits there for an owner who opens
    that panel again. Which is #2451's first reading, arrived at here by construction
    rather than by ruling — the ruling is still owed, and what is asserted is only that
    nothing opened.
    """
    loop = asyncio.get_running_loop()
    release, hang = _held(loop)
    answering: list[asyncio.Task[None]] = []

    async def consent(one: Dialog) -> None:
        await one.accept()

    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.page.on("dialog", lambda one: answering.append(loop.create_task(consent(one))))
        _seed_conversation(drive, "c-1", turns=3)
        await _open_listing(drive)

        await drive.page.route("**/conversation/forget", hang)
        async with drive.page.expect_request("**/conversation/forget"):
            await (
                drive.page.locator("#conversation-list .conversation-row")
                .first.get_by_role("button", name="Forget")
                .click()
            )

        await drive.page.route("**/sources", _ends_the_session)
        await drive.page.click("#sources-button")
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")

        async with drive.page.expect_response("**/conversation/forget") as stale:
            release.set_result(None)
        await (await stale.value).finished()
        await drive.admit()

        # The panel the act belonged to is closed and stays closed. Its rows are the ones
        # the listing rendered *before* the session ended -- the late continuation's own
        # re-read renders nothing, which is the listing rule one case up -- so what is
        # asserted here is the opening, which is this case's claim.
        await expect(drive.page.locator("#conversations")).to_be_hidden()
