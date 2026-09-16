"""ADR-0254 §11's two surfaces, as a browser really renders them (ADR-0216 §1).

§11 owes *"a listing and a revocation"*, and §20 assigns *"the interface adapters that
render them"* to this lane — so what is asserted here is that what the engine answers
reaches the screen, that what the owner presses reaches the engine, and that what §11's
rendering bar keeps off a surface is not on it.

**Both viewports**, because ADR-0233 §15 obliges the browser lane to drive a floor *"at
a desktop width and at a phone-class viewport"*: a withdrawal control that renders
correctly and scrolls off a phone is one the owner does not have.

**The command line's twin is** ``tests/interfaces/test_cli_authorizations.py``, and the
two are written against the same clauses deliberately. ADR-0250's M4 review spent three
rounds fixing one surface and leaving the other, so the parity is asserted here rather
than left to two readings.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import pytest
from browser_drive import DESKTOP, PHONE, driving
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import expect

from ai_assistant.core.types import (
    AuthorizationProjection,
    AuthorizationView,
    BoundKind,
    CoverageView,
    GoalStatus,
    GoalSummary,
    QuoteView,
    ToolDefinition,
    ValueBound,
)
from ai_assistant.testing import (
    AUTHORIZATION_NOW,
    AUTHORIZATION_TOOL,
    authorization_basis,
    coverage_member,
    money_bound,
    opening_act,
    terms_bound,
)

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import (
        Browser,
        ConsoleMessage,
        Dialog,
        Request,
        Response,
        Route,
        ViewportSize,
    )

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

GOAL_ID: Final = "goal-zzqq-7741"
OUTCOME: Final = "Book the usual campsite for the last weekend of August."

#: A second goal, so the panel can be opened twice in quick succession.
OTHER_ID: Final = "goal-wwvv-3320"
OTHER: Final = "Find somewhere to leave the dog."

#: A second declaration, so two rows of one goal can be withdrawn at once.
OTHER_TOOL: Final = ToolDefinition.model_validate(
    AUTHORIZATION_TOOL.model_dump() | {"id": "hotels"}
)
STATEMENT: Final = OUTCOME
ENGAGED: Final = datetime(2026, 1, 1, 11, tzinfo=UTC)

#: Both figures ADR-0233 §15 obliges, named once so every case runs at both.
_VIEWPORTS: Final = [DESKTOP, PHONE]

#: The one console error a correct page produces, and it is the browser's own: a browser
#: asks for a favicon unprompted and admission is decided before routing, so a
#: session-less request to any path answers 401.
_BROWSERS_OWN_PROBE = "/favicon.ico"


def _view(row_id: str, tool: ToolDefinition, bound: ValueBound) -> AuthorizationView:
    """One :class:`AuthorizationView` an act would announce."""
    return AuthorizationView(
        id=row_id,
        goal_statement=STATEMENT,
        tool=tool,
        coverage=(CoverageView(kind=BoundKind.MONEY, bound=bound, span="what you said"),),
        expires_at=AUTHORIZATION_NOW + timedelta(hours=1),
        live=True,
    )


def _summary(*, goal_id: str = GOAL_ID, outcome: str = OUTCOME) -> GoalSummary:
    """One goal row the authorities panel can be opened from."""
    return GoalSummary(
        id=goal_id,
        outcome=outcome,
        status=GoalStatus.ACTIVE,
        paused=False,
        last_engaged_at=ENGAGED,
        clarification=None,
    )


def _seed(drive: Drive, *, lapsed: bool = False) -> None:
    """One goal and one standing authority over it, as the engine would answer them."""
    drive.engine.goal_summaries = [_summary()]
    drive.engine.hold_authorization(
        opening_act(
            id="auth-1",
            goal=GOAL_ID,
            coverage=(
                coverage_member(
                    BoundKind.MONEY,
                    bound=money_bound("50"),
                    basis=authorization_basis(span="up to fifty pounds"),
                ),
                coverage_member(
                    BoundKind.TERMS,
                    bound=terms_bound("refundable"),
                    basis=authorization_basis(span="only if I can cancel"),
                ),
            ),
            expires_at=(
                AUTHORIZATION_NOW - timedelta(minutes=1)
                if lapsed
                else AUTHORIZATION_NOW + timedelta(hours=1)
            ),
        ),
        goal_statement=STATEMENT,
    )


async def _open_authorities(drive: Drive) -> None:
    """Press the two controls the owner presses, and wait for the panel they open."""
    await drive.page.click("#goals-button")
    await drive.page.wait_for_selector("#goals:not([hidden])")
    await drive.page.click("#goal-list button:has-text('What this authorises')")
    await drive.page.wait_for_selector("#authorizations:not([hidden])")


def _note(message: ConsoleMessage, complaints: list[str]) -> None:
    """Keep every console error but the one the browser makes on its own."""
    if message.type == "error" and not message.location["url"].endswith(_BROWSERS_OWN_PROBE):
        complaints.append(f"{message.location['url']}: {message.text}")


def _answering(drive: Drive, *, accept: bool) -> asyncio.Future[str]:
    """Answer the next ``window.confirm`` and hand the case what it said.

    ``Dialog.accept`` is a coroutine, so the handler cannot be a lambda: a page event
    listener is called synchronously and a coroutine nobody awaits leaves the dialog
    open. ``test_browser_goals`` holds the same shape one ceremony over, and for the
    same reason — **the future is the case's synchronisation** (ADR-0216 §7).
    """
    loop = asyncio.get_running_loop()
    answered: asyncio.Future[str] = loop.create_future()
    running: list[asyncio.Task[None]] = []

    async def answer(dialog: Dialog) -> None:
        message = dialog.message
        await (dialog.accept() if accept else dialog.dismiss())
        if not answered.done():
            answered.set_result(message)

    drive.page.on("dialog", lambda dialog: running.append(loop.create_task(answer(dialog))))
    return answered


# --- §11's listing, at both widths --------------------------------------------


@pytest.mark.parametrize("viewport", _VIEWPORTS)
async def test_the_listing_puts_what_one_goal_authorises_on_the_screen(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§11's listing, driven: the goal by **statement**, the declaration, every member as
    its own statement with the owner's words beneath it, the horizon, and whether it
    still stands.

    Driven at both widths because a listing that renders correctly and scrolls off a
    phone is one the owner does not have.
    """
    complaints: list[str] = []
    thrown: list[str] = []
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        drive.page.on("console", lambda message: _note(message, complaints))
        _seed(drive)

        await _open_authorities(drive)

        panel = drive.page.locator("#authorizations")
        await expect(panel).to_contain_text(STATEMENT)
        await expect(panel).to_contain_text(AUTHORIZATION_TOOL.id)
        await expect(panel).to_contain_text("the amount: up to 50 GBP")
        await expect(panel).to_contain_text('from what you said: "up to fifty pounds"')
        await expect(panel).to_contain_text("the terms: one of: refundable")
        await expect(panel).to_contain_text("It still stands")
        await expect(panel).to_contain_text("id: auth-1")
        await expect(panel.get_by_role("button", name="Withdraw this")).to_be_visible()
    assert complaints == []
    assert thrown == []


@pytest.mark.parametrize("viewport", _VIEWPORTS)
async def test_a_strict_ceiling_is_on_the_screen_as_one_and_never_as_an_inclusive_one(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """ADR-0266 §3, driven: *"under 100"* and *"at most 100"* stopped being one value.

    **A page that said "up to" for both would show the owner a limit a cent wider than
    the one they hold** — the permissive direction ADR-0254 §2's asymmetry names, on
    the surface §11 exists to make the working checkable on. Driven rather than
    asserted over the bytes because what is at issue is the sentence a person reads.
    """
    complaints: list[str] = []
    thrown: list[str] = []
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.page.on("pageerror", lambda error: thrown.append(str(error)))
        drive.page.on("console", lambda message: _note(message, complaints))
        drive.engine.goal_summaries = [_summary()]
        drive.engine.hold_authorization(
            opening_act(
                id="auth-1",
                goal=GOAL_ID,
                coverage=(
                    coverage_member(
                        BoundKind.MONEY,
                        bound=money_bound("100", maximum_exclusive=True),
                        basis=authorization_basis(span="under 100 euros"),
                    ),
                ),
                expires_at=AUTHORIZATION_NOW + timedelta(hours=1),
            ),
            goal_statement=STATEMENT,
        )

        await _open_authorities(drive)

        panel = drive.page.locator("#authorizations")
        await expect(panel).to_contain_text("the amount: under 100 GBP")
        await expect(panel).to_contain_text('from what you said: "under 100 euros"')
        assert "up to" not in await panel.inner_text()
    assert complaints == []
    assert thrown == []


@pytest.mark.parametrize("viewport", _VIEWPORTS)
async def test_the_listing_says_a_lapsed_record_has_lapsed_and_still_offers_it(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§16 returns a lapsed row deliberately: *"a user can see and revoke what they once
    authorised"* — so the control is on a lapsed row and the row says which it is.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        _seed(drive, lapsed=True)

        await _open_authorities(drive)

        panel = drive.page.locator("#authorizations")
        await expect(panel).to_contain_text("It has lapsed")
        await expect(panel.get_by_role("button", name="Withdraw this")).to_be_visible()


async def test_the_listing_renders_no_identifier_but_the_revocation_handle(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§20 arm 62's bar, asserted over the **rendered text** of the whole panel.

    The row behind it carries a goal id, a connected account and a subject digest; none
    of them is on the screen, and the goal is rendered by statement and never by id.
    """
    row = opening_act(id="auth-1", goal=GOAL_ID)
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)

        await _open_authorities(drive)
        shown = await drive.page.locator("#authorizations").inner_text()

    assert "auth-1" in shown
    assert GOAL_ID not in shown
    assert row.account.reference not in shown
    assert row.account.identity not in shown
    assert row.subject_digest not in shown


async def test_the_panel_labels_the_goal_with_what_the_listing_returned(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0254 §11: the **engine** reads the goal's statement and the surface renders
    *that*.

    The goal listing this panel is opened from is a page of summaries fetched earlier, so
    a statement revised in between would leave the panel labelling this goal's authorities
    with the goal's previous outcome — a divergence no test can see while both values are
    seeded the same. Here they are seeded **differently**, and what is on screen is the
    one the listing operation answered with. Adversarial review, round 1, ``blocker``.
    """
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        drive.engine.goal_statements[GOAL_ID] = "Book the campsite — now for six people."

        await _open_authorities(drive)

        panel = drive.page.locator("#authorizations")
        await expect(panel).to_contain_text("now for six people")
        assert OUTCOME not in await panel.inner_text()


async def test_a_goal_with_nothing_standing_says_so_rather_than_showing_a_blank(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A goal holding no authority answers empty, and the panel says what that means."""
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        drive.engine.goal_summaries = [_summary()]

        await _open_authorities(drive)

        await expect(drive.page.locator("#authorizations")).to_contain_text("Nothing standing")


# --- §11's withdrawal ----------------------------------------------------------


async def test_the_withdrawal_is_shown_before_it_is_taken_and_then_reports_what_it_did(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0073 §5's show-then-confirm, at the unit the owner thinks in, and §11's
    prospective clause said out loud rather than left to be inferred.
    """
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        await _open_authorities(drive)
        asked = _answering(drive, accept=True)

        await drive.page.click("#authorization-list button:has-text('Withdraw this')")
        message = await asyncio.wait_for(asked, timeout=10)

        assert STATEMENT in message
        assert "no narrowing" in message
        said = drive.page.locator("#authorizations .authorization-said")
        await expect(said).to_contain_text("Withdrawn.")
        await expect(said).to_contain_text("Nothing already decided is rewritten")
        # **The sentence names the record it moved**, which is what makes a node the
        # listing does not own honest: the rows under it may by then be another goal's.
        await expect(said).to_contain_text(STATEMENT)
        await expect(said).to_contain_text(AUTHORIZATION_TOOL.id)
        # **The row is retired in place and the listing is not re-read.** A record the
        # store says is now `REVOKED` must not go on reading "still stands" beside an
        # enabled control, and a refresh here would be one more request to race the
        # owner's next. Adversarial review, round 4, ``major``.
        panel = drive.page.locator("#authorizations")
        await expect(panel).to_contain_text("You withdrew this.")
        assert "still stands" not in await panel.inner_text()
        await expect(panel.get_by_role("button", name="Withdraw this")).to_have_count(0)
        assert [name for name, _ in drive.engine.calls if "authoriz" in name] == [
            "standing_authorizations",
            "revoke_authorization",
        ]


async def test_declining_the_ceremony_withdraws_nothing(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The other half of show-then-confirm: a dismissed dialog reaches the engine not at
    all, so the record stands and the panel is unchanged.
    """
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        await _open_authorities(drive)
        asked = _answering(drive, accept=False)

        await drive.page.click("#authorization-list button:has-text('Withdraw this')")
        await asyncio.wait_for(asked, timeout=10)

        assert "revoke_authorization" not in [name for name, _ in drive.engine.calls]
        await expect(drive.page.locator("#authorizations")).to_contain_text("still stands")
        await expect(drive.page.locator(".authorization-said")).to_have_count(0)


async def test_a_withdrawal_that_moves_nothing_reports_what_the_store_found(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§16's ``not_at_source``, and it is **not** the fault slot.

    The row is withdrawn from somewhere else while the panel stands open — the ordinary
    way a listing goes stale — so the press reaches a record that exists and is no
    longer at the edge's source. That is the store working rather than failing: every
    member of this vocabulary is something the hub established, the two that moved
    nothing included, and writing *"there was nothing here for this to take"* into a
    fault slot would report a working act as a broken one.

    The sentence also names the act that **does** withdraw a question the owner never
    answered — declining it — because §1's graph makes a ``PROPOSED`` row unrevocable
    here and a user meeting this refusal has no other way to learn that.
    """
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        await _open_authorities(drive)
        await drive.engine.revoke_authorization("auth-1")
        asked = _answering(drive, accept=True)

        await drive.page.click("#authorization-list button:has-text('Withdraw this')")
        await asyncio.wait_for(asked, timeout=10)

        said = drive.page.locator("#authorizations .authorization-said")
        await expect(said).to_contain_text("nothing was withdrawn")
        await expect(said).to_contain_text("declining it")
        # **Not the fault slot, and the row is left exactly where it was**: the store
        # moved nothing, so neither does the display.
        assert "notice" in await said.evaluate("(node) => node.className")
        await expect(drive.page.locator("#authorizations")).to_contain_text("still stands")


async def test_an_overtaken_listing_renders_nothing_and_claims_no_goal(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Two rows pressed in quick succession are two requests that can land in either
    order, and the one that is not the latest is dropped whole.

    Without it the rows on screen and the goal the panel believes it is showing can name
    **different** goals: a slow request for A landing after a fast one for B leaves B's
    statement recorded and A's rows drawn, and a withdrawal taken from an A row then
    re-reads B and writes *"Withdrawn"* above it — an act reported against work it was
    not taken on. Adversarial review, round 2, ``major``.

    Driven by holding the **first** request at the socket until the second has finished,
    which is the interleaving the defect needs and which no sequential case reaches.

    **The overtaken request is now stopped rather than merely ignored** (round 12), so
    what the case waits on is that request reaching a terminal state — a response *or* a
    cancellation, whichever the browser gives it. Either is a condition the page reached
    rather than a duration this test guessed (ADR-0216 §7), and waiting only for a
    response would wait for one the abort guarantees never comes.
    """
    loop = asyncio.get_running_loop()
    held: asyncio.Future[None] = loop.create_future()
    landed: asyncio.Future[None] = loop.create_future()
    seen = 0
    settled = 0

    async def route(one: Route) -> None:
        nonlocal seen
        seen += 1
        if seen == 1:
            await held
        with contextlib.suppress(PlaywrightError):
            # A request the page aborted while this handler was suspended can no longer
            # be continued, and that is the outcome under test rather than a fault.
            await one.fallback()

    def done(url: str) -> None:
        """Resolve once **both** listings have stopped being in flight.

        The overtaken one stops by being cancelled and the newer one by answering; the
        case cares only that neither is still outstanding when it asserts.
        """
        nonlocal settled
        if not url.endswith("/authorizations"):
            return
        settled += 1
        if settled == 2 and not landed.done():
            landed.set_result(None)

    def arrived(response: Response) -> None:
        done(response.url)

    def cancelled(request: Request) -> None:
        done(request.url)

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        drive.engine.goal_summaries = [_summary(), _summary(goal_id=OTHER_ID, outcome=OTHER)]
        drive.engine.goal_statements[OTHER_ID] = OTHER
        drive.page.on("response", arrived)
        drive.page.on("requestfailed", cancelled)
        await drive.page.route("**/authorizations", route)
        await drive.page.click("#goals-button")
        await drive.page.wait_for_selector("#goals:not([hidden])")
        rows = drive.page.locator("#goal-list button:has-text('What this authorises')")

        await rows.nth(0).click()
        await rows.nth(1).click()
        await drive.page.wait_for_selector("#authorizations:not([hidden])")
        await expect(drive.page.locator("#authorizations")).to_contain_text(OTHER)
        held.set_result(None)
        await asyncio.wait_for(landed, timeout=10)

        # The overtaken response has arrived and must have changed nothing at all.
        panel = drive.page.locator("#authorizations")
        await expect(panel).to_contain_text("Nothing standing")
        assert STATEMENT not in await panel.inner_text()


async def test_an_overtaken_listing_that_comes_back_refused_changes_nothing(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A superseded listing must not be able to speak at all, not merely be ignored.

    ``relay`` renders a refusal **before** it returns — ``refused`` → ``report`` →
    ``sessionLost`` — so a comparison after the ``await`` is too late for the refusal
    path. An overtaken listing coming back refused writes a stale fault over the newer
    listing's rows, and one coming back ``no-live-session`` after the owner has
    re-entered forgets the **new** session's header half and throws the page back to
    the bootstrap form: a dead request ending a live session. Adversarial review,
    round 12, ``major``.

    Driven at the worst of the two: the overtaken request is released as a
    ``no-live-session`` refusal. Stopped, it has no response to classify, so the page
    keeps its session and its rows — and the following exchange, which only a page that
    still holds a session can make, is what orders any handling of that refusal before
    the assertions.
    """
    loop = asyncio.get_running_loop()
    held: asyncio.Future[None] = loop.create_future()
    delivered: asyncio.Future[None] = loop.create_future()
    seen = 0

    async def route(one: Route) -> None:
        nonlocal seen
        seen += 1
        if seen != 1:
            await one.fallback()
            return
        await held
        with contextlib.suppress(PlaywrightError):
            await one.fulfill(
                status=401,
                content_type="application/json",
                body=json.dumps({"fault": "no-live-session"}),
            )
        if not delivered.done():
            delivered.set_result(None)

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        drive.engine.goal_summaries = [_summary(), _summary(goal_id=OTHER_ID, outcome=OTHER)]
        drive.engine.goal_statements[OTHER_ID] = OTHER
        await drive.page.route("**/authorizations", route)
        await drive.page.click("#goals-button")
        await drive.page.wait_for_selector("#goals:not([hidden])")
        rows = drive.page.locator("#goal-list button:has-text('What this authorises')")

        await rows.nth(0).click()
        await rows.nth(1).click()
        await expect(drive.page.locator("#authorizations")).to_contain_text(OTHER)
        held.set_result(None)
        await asyncio.wait_for(delivered, timeout=10)

        # Only a page that still holds a session makes this request at all.
        async with drive.page.expect_response("**/goals", timeout=5000):
            await drive.page.click("#goals-button")

        await expect(drive.page.locator("#bootstrap")).to_be_hidden()
        await expect(drive.page.locator("#console")).to_be_visible()
        panel = drive.page.locator("#authorizations")
        await expect(panel).to_contain_text(OTHER)
        assert "no longer" not in await panel.inner_text()


async def test_a_listing_that_outlives_its_session_reveals_nothing(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A panel is not re-opened by a response admitted under a session that has ended.

    The generation counter orders two *listings* and says nothing about the session
    under them. Let the listing hang, let any other request meet ``no-live-session`` —
    ``sessionLost`` forgets the header half and puts the bootstrap entry back — and the
    hanging run is still the latest, so on the unguarded page it resumes, renders, and
    calls ``show("authorizations", true)``: one goal's standing authorities on screen
    beside a form asking the owner to start a session. Adversarial review, round 9,
    ``major``.

    **Nothing here sleeps** (ADR-0216 §7). What is asserted is a state the page must
    *not* reach, and a bare retrying assertion would pass the instant before the reveal
    it is looking for — so the case needs an ordering rather than a duration. It takes
    one: the stale response is awaited to its **last byte**, and then the owner
    **re-enters** through the page's own form, which completes only once ``#console`` is
    on screen at the end of a fresh bootstrap exchange. A resumed listing whose body has
    fully arrived cannot still be pending across a whole network round trip, so by the
    time the console is up the continuation has run — and it has run under a *different*
    header half, which the guard refuses on the same terms. Re-entry reveals no control
    panel of its own (``showConsole`` shows the console, notifications and the control
    entry points and nothing else), so a panel visible at the end was revealed by the
    stale response.
    """
    loop = asyncio.get_running_loop()
    held: asyncio.Future[None] = loop.create_future()

    async def route(one: Route) -> None:
        await held
        await one.fallback()

    async def ended(one: Route) -> None:
        await one.fulfill(
            status=401,
            content_type="application/json",
            body=json.dumps({"fault": "no-live-session"}),
        )

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        await drive.page.click("#goals-button")
        await drive.page.wait_for_selector("#goals:not([hidden])")
        await drive.page.route("**/authorizations", route)
        await drive.page.click("#goal-list button:has-text('What this authorises')")

        # The session ends under the hanging listing, through a request of its own.
        await drive.page.route("**/goals", ended)
        await drive.page.click("#goals-button")
        await drive.page.wait_for_selector("#bootstrap:not([hidden])")

        async with drive.page.expect_response("**/authorizations") as stale:
            held.set_result(None)
        await (await stale.value).finished()
        await drive.admit()

        await expect(drive.page.locator("#authorizations")).to_be_hidden()
        await expect(drive.page.locator("#authorization-list .notification-row")).to_have_count(0)


async def test_a_withdrawal_is_read_back_after_the_panel_moves_to_another_goal(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A settlement is **readable** and **attributed**, whatever the panel does meanwhile.

    Four rounds converged on this arm and it states all four. Start withdrawing a row of
    goal A, then open goal B before the revocation returns. A bare *"Withdrawn."* above
    B's rows says the act was done to B's work (round 3); dropping the sentence because
    the panel moved on is silence about an act that happened (round 4); and writing it
    into the row is writing into a node the listing has already detached, so the owner
    reads nothing at all (round 5). What is asserted here is the shape true under all
    four: the sentence is on screen, it names **goal A** and the declaration it moved,
    and B's listing beneath it is B's.
    """
    loop = asyncio.get_running_loop()
    held: asyncio.Future[None] = loop.create_future()

    async def route(one: Route) -> None:
        await held
        await one.fallback()

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        drive.engine.goal_summaries = [_summary(), _summary(goal_id=OTHER_ID, outcome=OTHER)]
        drive.engine.goal_statements[OTHER_ID] = OTHER
        await _open_authorities(drive)
        await drive.page.route("**/authorization/revoke", route)
        asked = _answering(drive, accept=True)

        await drive.page.click("#authorization-list button:has-text('Withdraw this')")
        await asyncio.wait_for(asked, timeout=10)
        # The owner re-points the panel while the withdrawal is still out.
        await drive.page.click("#goals-button")
        await drive.page.wait_for_selector("#goals:not([hidden])")
        rows = drive.page.locator("#goal-list button:has-text('What this authorises')")
        await rows.nth(1).click()
        await expect(drive.page.locator("#authorizations")).to_contain_text(OTHER)
        held.set_result(None)

        said = drive.page.locator("#authorizations .authorization-said")
        await expect(said).to_be_visible()
        await expect(said).to_contain_text("Withdrawn.")
        await expect(said).to_contain_text(STATEMENT)
        await expect(said).to_contain_text(AUTHORIZATION_TOOL.id)
        await expect(drive.page.locator("#authorization-goal")).to_contain_text(OTHER)


async def test_the_same_goal_re_opened_mid_withdrawal_still_shows_what_the_act_did(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The row on screen at the end of an act is not the row that started it.

    The owner has only to press *What this authorises* on the **same** goal while a
    withdrawal is out: the listing is cleared and rebuilt, and an act that writes into
    the elements it closed over writes into DOM the page has already thrown away. What
    is left on screen then is worse than silence — the rebuilt row reads *"still
    stands"* beside an **enabled** control that can issue a second revocation against a
    record the store has already settled. Adversarial review, round 7, ``blocker``.

    What is asserted is the property that replaced the placement: a row's state is a
    function of the **record**, so the rebuilt row is drawn out of reach while the act
    is out and drawn withdrawn once it settles, and the record beside it — untouched by
    the act — keeps its own control.
    """
    loop = asyncio.get_running_loop()
    held: asyncio.Future[None] = loop.create_future()

    async def route(one: Route) -> None:
        await held
        await one.fallback()

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        await _open_authorities(drive)
        await drive.page.route("**/authorization/revoke", route)
        asked = _answering(drive, accept=True)

        await drive.page.click("#authorization-list button:has-text('Withdraw this')")
        await asyncio.wait_for(asked, timeout=10)
        # A second record of the same goal, so re-opening it is a listing that really
        # rebuilds the rows rather than one the case cannot tell apart from the first.
        drive.engine.hold_authorization(
            opening_act(id="auth-2", goal=GOAL_ID, tool=OTHER_TOOL), goal_statement=STATEMENT
        )
        await drive.page.click("#goals-button")
        await drive.page.wait_for_selector("#goals:not([hidden])")
        await drive.page.click("#goal-list button:has-text('What this authorises')")
        rows = drive.page.locator("#authorization-list .notification-row")
        await expect(rows).to_have_count(2)

        acted = rows.filter(has_text="id: auth-1")
        untouched = rows.filter(has_text="id: auth-2")
        # Drawn a second time, mid-act: the control must be out of reach on the row the
        # page has a request out for, and only on that one.
        await expect(acted.locator("button")).to_be_disabled()
        await expect(untouched.locator("button")).to_be_enabled()
        held.set_result(None)

        await expect(acted).to_contain_text("You withdrew this.")
        assert "still stands" not in await acted.inner_text()
        await expect(acted.locator("button")).to_have_count(0)
        await expect(untouched).to_contain_text("still stands")
        await expect(untouched.locator("button")).to_be_enabled()
        # And the act reported, naming the record it moved.
        said = drive.page.locator("#authorizations .authorization-said")
        await expect(said).to_contain_text("Withdrawn.")
        await expect(said).to_contain_text(AUTHORIZATION_TOOL.id)
        assert [name for name, _ in drive.engine.calls].count("revoke_authorization") == 1


async def test_a_record_whose_id_carries_a_control_character_is_still_restated(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The act finds its rows by comparing the value, not by building a selector from it.

    ``Identifier`` refuses only a blank and requires a UTF-8 encoding — ADR-0018 §2
    declined the visible-text tightening and issue #62 still holds the control-character
    question open — so ``id`` may carry ``U+0000``. ``CSS.escape`` maps that to
    ``U+FFFD``, which is a *lossy* escape rather than a failing one: a selector built
    from such an id matches nothing, and the row the store has just settled goes on
    reading *"still stands"* beside a live control — the state round 7 closed, reached
    through the escape. Adversarial review, round 8, ``major``.

    Driven through the **payload**, because no builder in ``ai_assistant.testing`` mints
    an id like this and the subject is what the page does with one that arrives.
    """
    handle = "auth\x00one"
    listing = {
        "authorizations": [
            {
                "id": handle,
                "goal_statement": STATEMENT,
                "tool_id": AUTHORIZATION_TOOL.id,
                "tool_description": AUTHORIZATION_TOOL.description,
                "coverage": [
                    {
                        "kind": "money",
                        "fixed": None,
                        "bound": {
                            "kind": "money",
                            "currency": "GBP",
                            "maximum_exclusive": False,
                            "maximum": "50",
                            "minimum": None,
                            "starts_at": None,
                            "ends_at": None,
                            "timezone": None,
                            "terms": None,
                        },
                        "span": "up to fifty pounds",
                    }
                ],
                "expires_at": "2026-09-13T21:00:00+00:00",
                "live": True,
            }
        ]
    }

    async def rows(one: Route) -> None:
        await one.fulfill(status=200, content_type="application/json", body=json.dumps(listing))

    async def settled(one: Route) -> None:
        await one.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"settlement": "settled"}),
        )

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        await drive.page.route("**/authorizations", rows)
        await drive.page.route("**/authorization/revoke", settled)
        await _open_authorities(drive)
        _answering(drive, accept=True)

        await drive.page.click("#authorization-list button:has-text('Withdraw this')")

        row = drive.page.locator("#authorization-list .notification-row")
        await expect(row).to_contain_text("You withdrew this.")
        await expect(row.locator("button")).to_have_count(0)
        assert "still stands" not in await row.inner_text()
        # And one entry, not a second one built because the first could not be found.
        await expect(drive.page.locator("#authorizations .authorization-said")).to_have_count(1)


async def test_a_second_press_while_the_first_is_out_reaches_the_hub_once(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Two accepted presses would race, and their answers would contradict each other.

    The store admits exactly one winner, so the loser comes back ``NOT_AT_SOURCE`` — and
    landing after the winner it would overwrite *"Withdrawn."* with *"nothing was
    withdrawn"* above a row already reading *"You withdrew this."* The control is out of
    reach for the duration instead, so there is one request and one answer. Adversarial
    review, round 5, ``major``.
    """
    loop = asyncio.get_running_loop()
    held: asyncio.Future[None] = loop.create_future()

    async def route(one: Route) -> None:
        await held
        await one.fallback()

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        await _open_authorities(drive)
        await drive.page.route("**/authorization/revoke", route)
        asked = _answering(drive, accept=True)
        control = drive.page.locator("#authorization-list button:has-text('Withdraw this')")

        await control.click()
        await asyncio.wait_for(asked, timeout=10)
        await expect(control).to_be_disabled()
        await control.click(force=True)
        held.set_result(None)

        await expect(drive.page.locator("#authorizations")).to_contain_text("You withdrew this.")
        assert [name for name, _ in drive.engine.calls].count("revoke_authorization") == 1


async def test_two_rows_withdrawn_at_once_each_keep_their_own_answer(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Every act reports in an entry of its own, keyed by the record it is about.

    One shared node is overwritten when two rows are withdrawn at once, and which of them
    answered what is lost — particularly the difference between a withdrawal that moved a
    record and one that found nothing to move. Driven with the **second** answer released
    first, so a last-writer-wins node would show only it. Adversarial review, round 6,
    ``major``.
    """
    loop = asyncio.get_running_loop()
    gates: list[asyncio.Future[None]] = [loop.create_future(), loop.create_future()]
    seen = 0

    async def route(one: Route) -> None:
        nonlocal seen
        gate = gates[min(seen, 1)]
        seen += 1
        await gate
        await one.fallback()

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        # A second record of the same goal, so both rows sit in one listing.
        drive.engine.hold_authorization(
            opening_act(id="auth-2", goal=GOAL_ID, tool=OTHER_TOOL), goal_statement=STATEMENT
        )
        await _open_authorities(drive)
        await drive.page.route("**/authorization/revoke", route)
        controls = drive.page.locator("#authorization-list button:has-text('Withdraw this')")

        # One handler for both ceremonies: a second `page.on("dialog")` would try to
        # answer a dialog the first had already answered.
        answered = 0

        async def accept(dialog: Dialog) -> None:
            nonlocal answered
            await dialog.accept()
            answered += 1

        running: list[asyncio.Task[None]] = []
        drive.page.on("dialog", lambda one: running.append(loop.create_task(accept(one))))

        await controls.nth(0).click()
        await controls.nth(1).click()
        while answered < 2:  # noqa: ASYNC110 — the condition is the page's, not a duration
            await asyncio.sleep(0.05)
        # The **second** answer is released first, so a last-writer-wins node would keep
        # only it.
        gates[1].set_result(None)
        gates[0].set_result(None)

        entries = drive.page.locator("#authorizations .authorization-said")
        await expect(entries).to_have_count(2)
        await expect(entries.nth(0)).to_contain_text("Withdrawn.")
        await expect(entries.nth(1)).to_contain_text("Withdrawn.")
        shown = await entries.all_inner_texts()
        assert sum(AUTHORIZATION_TOOL.id in one for one in shown) == 1, shown
        assert sum(OTHER_TOOL.id in one for one in shown) == 1, shown


async def test_a_malformed_bound_is_reported_rather_than_rendered(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A limit the record does not carry is never presented as one (ADR-0254 §2).

    Driven through the **payload** rather than over the source, which is what round 6
    asked for: the listing's answer is rewritten on the wire to carry a money bound whose
    amount, currency and currency key are all absent — a shape ``ValueBound`` refuses and
    no conforming hub sends — and what the page must not do is render ``up to null``.
    """
    body = {
        "authorizations": [
            {
                "id": "auth-1",
                "goal_statement": STATEMENT,
                "tool_id": AUTHORIZATION_TOOL.id,
                "tool_description": AUTHORIZATION_TOOL.description,
                "coverage": [
                    {
                        "kind": "money",
                        "fixed": None,
                        "bound": {
                            "kind": "money",
                            "currency": None,
                            "maximum_exclusive": False,
                            "maximum": None,
                            "minimum": None,
                            "starts_at": None,
                            "ends_at": None,
                            "timezone": None,
                            "terms": None,
                        },
                        "span": "up to fifty pounds",
                    }
                ],
                "expires_at": "2026-09-13T21:00:00+00:00",
                "live": True,
            }
        ]
    }

    async def route(one: Route) -> None:
        await one.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        await drive.page.route("**/authorizations", route)

        await drive.page.click("#goals-button")
        await drive.page.wait_for_selector("#goals:not([hidden])")
        await drive.page.click("#goal-list button:has-text('What this authorises')")
        await drive.page.wait_for_selector("#authorizations:not([hidden])")

        panel = drive.page.locator("#authorizations")
        await expect(panel).to_contain_text("no words for")
        shown = await panel.inner_text()
        assert "up to null" not in shown
        assert "undefined" not in shown


async def test_a_fixed_period_naming_a_real_day_is_rendered(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A fixed ``PERIOD`` member reaches the screen as the day it names (§11).

    **Its counterpart — an impossible date reported rather than rendered — is
    deliberately not here, and that is where the two lenses disagreed.** Adversarial
    round 4 asked the page to check the calendar; architecture round 5 ruled that
    parsing a **blocker** under golden rule 3, ADR-0266 §3 putting fixed-period
    validity on the `core` contract. Architecture's reading is the one that survives
    contact: the round-4 parser had drifted from ``period_reading_form`` by the very
    next round, in both directions. So the invariant is enforced where §3 puts it —
    ``tests/core/test_authorization_views.py`` pins that ``CoverageView`` refuses
    ``2026-02-30`` — and the page renders what a validated projection carries.
    """
    body = {
        "authorizations": [
            {
                "id": "auth-1",
                "goal_statement": STATEMENT,
                "tool_id": AUTHORIZATION_TOOL.id,
                "tool_description": AUTHORIZATION_TOOL.description,
                "coverage": [
                    {
                        "kind": "period",
                        "fixed": "2026-02-28",
                        "bound": None,
                        "span": "the last day of February",
                    }
                ],
                "expires_at": "2026-09-13T21:00:00+00:00",
                "live": True,
            }
        ]
    }

    async def route(one: Route) -> None:
        await one.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        await drive.page.route("**/authorizations", route)

        await drive.page.click("#goals-button")
        await drive.page.wait_for_selector("#goals:not([hidden])")
        await drive.page.click("#goal-list button:has-text('What this authorises')")
        await drive.page.wait_for_selector("#authorizations:not([hidden])")

        panel = drive.page.locator("#authorizations")
        await expect(panel).to_contain_text("the dates: fixed at 2026-02-28")


@pytest.mark.parametrize("stray", [None, "true", 1], ids=["null", "text", "one"])
async def test_a_period_bound_whose_exclusivity_flag_is_not_false_is_reported(
    gateway_browser: Browser, tmp_path: Path, stray: object
) -> None:
    """A field of the money shape is absent-as-``False`` on the other two (§2, §3).

    ``maximum_exclusive`` is a ``bool`` with a default, so it crosses on **every**
    bound of every kind and the page's ``absent`` test — which reads ``null`` and
    ``undefined`` — cannot see it. A reader asking only that it is not ``true``
    admitted ``null``, ``"true"`` and ``1``, each a shape ``ValueBound`` refuses and
    no conforming hub sends, and each of which would then have rendered as a valid
    authority. Adversarial review, round 7, ``major``.
    """
    body = {
        "authorizations": [
            {
                "id": "auth-1",
                "goal_statement": STATEMENT,
                "tool_id": AUTHORIZATION_TOOL.id,
                "tool_description": AUTHORIZATION_TOOL.description,
                "coverage": [
                    {
                        "kind": "period",
                        "fixed": None,
                        "bound": {
                            "kind": "period",
                            "currency": None,
                            "maximum_exclusive": stray,
                            "maximum": None,
                            "minimum": None,
                            "starts_at": "2026-09-13T09:00:00+00:00",
                            "ends_at": "2026-09-13T21:00:00+00:00",
                            "timezone": "Europe/London",
                            "terms": None,
                        },
                        "span": "that weekend",
                    }
                ],
                "expires_at": "2026-09-13T21:00:00+00:00",
                "live": True,
            }
        ]
    }

    async def route(one: Route) -> None:
        await one.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        await drive.page.route("**/authorizations", route)

        await drive.page.click("#goals-button")
        await drive.page.wait_for_selector("#goals:not([hidden])")
        await drive.page.click("#goal-list button:has-text('What this authorises')")
        await drive.page.wait_for_selector("#authorizations:not([hidden])")

        panel = drive.page.locator("#authorizations")
        await expect(panel).to_contain_text("no words for")
        assert "the dates: from" not in await panel.inner_text()


async def test_a_bound_carrying_another_kinds_field_is_reported(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A mixed shape is refused, not rendered with the extra limit dropped.

    ``boundSentence`` reads only the fields of the kind it branches on, so a money bound
    carrying a ``terms`` set would show the ceiling and say nothing about the set — a
    limit the record carries and the owner is not shown. ``ValueBound`` refuses the mixed
    shape outright. Adversarial review, round 6, ``major``.
    """
    body = {
        "authorizations": [
            {
                "id": "auth-1",
                "goal_statement": STATEMENT,
                "tool_id": AUTHORIZATION_TOOL.id,
                "tool_description": AUTHORIZATION_TOOL.description,
                "coverage": [
                    {
                        "kind": "money",
                        "fixed": None,
                        "bound": {
                            "kind": "money",
                            "currency": "GBP",
                            "maximum_exclusive": False,
                            "maximum": "50",
                            "minimum": None,
                            "starts_at": None,
                            "ends_at": None,
                            "timezone": None,
                            "terms": ["refundable"],
                        },
                        "span": "up to fifty pounds",
                    }
                ],
                "expires_at": "2026-09-13T21:00:00+00:00",
                "live": True,
            }
        ]
    }

    async def route(one: Route) -> None:
        await one.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        await drive.page.route("**/authorizations", route)

        await drive.page.click("#goals-button")
        await drive.page.wait_for_selector("#goals:not([hidden])")
        await drive.page.click("#goal-list button:has-text('What this authorises')")
        await drive.page.wait_for_selector("#authorizations:not([hidden])")

        panel = drive.page.locator("#authorizations")
        await expect(panel).to_contain_text("no words for")
        assert "up to 50 GBP" not in await panel.inner_text()


async def test_a_period_bound_without_its_zone_is_reported_rather_than_rendered(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A ``PERIOD`` states its zone, and an interval without one is not one.

    Driven through the **payload**, as its two neighbours are.
    ``ValueBound._the_kind_carries_its_own_arguments_and_no_others`` builds its
    ``missing`` list from every field the kind takes *except* ``minimum``, so ``PERIOD``
    requires ``timezone`` and no conforming hub sends one without it. Rendering the two
    ends anyway states a window that is a different window in every zone the owner might
    be in — a limit the record does not carry. Adversarial review, round 7, ``major``.
    """
    body = {
        "authorizations": [
            {
                "id": "auth-1",
                "goal_statement": STATEMENT,
                "tool_id": AUTHORIZATION_TOOL.id,
                "tool_description": AUTHORIZATION_TOOL.description,
                "coverage": [
                    {
                        "kind": "period",
                        "fixed": None,
                        "bound": {
                            "kind": "period",
                            "currency": None,
                            "maximum_exclusive": False,
                            "maximum": None,
                            "minimum": None,
                            "starts_at": "2026-08-29T00:00:00+00:00",
                            "ends_at": "2026-08-31T00:00:00+00:00",
                            "timezone": None,
                            "terms": None,
                        },
                        "span": "between the Saturday and the Monday",
                    }
                ],
                "expires_at": "2026-09-13T21:00:00+00:00",
                "live": True,
            }
        ]
    }

    async def route(one: Route) -> None:
        await one.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        await drive.page.route("**/authorizations", route)

        await drive.page.click("#goals-button")
        await drive.page.wait_for_selector("#goals:not([hidden])")
        await drive.page.click("#goal-list button:has-text('What this authorises')")
        await drive.page.wait_for_selector("#authorizations:not([hidden])")

        panel = drive.page.locator("#authorizations")
        await expect(panel).to_contain_text("no words for")
        shown = await panel.inner_text()
        assert "2026-08-29" not in shown, shown
        assert "between the Saturday and the Monday" not in shown, shown


async def test_an_announcement_names_the_handle_and_where_the_act_is_taken(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0254 §11 puts the **handle** in front of the owner at the act, and that is
    what an announcement carries.

    **It offers no control, and that is the decision rather than an omission.** An
    announcement sits in a reply the next turn replaces, so a withdrawal taken there
    reports into DOM the page has already thrown away — the fifth way a settlement could
    be lost, and the one round 6 found. This is the command line's own shape: its
    announcement prints ``assistant revoke-authorization <id>`` rather than performing
    the withdrawal, so the two surfaces state the same act in the same place.
    """
    rail = ToolDefinition.model_validate(AUTHORIZATION_TOOL.model_dump() | {"id": "rail"})
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        drive.engine.authorizations = (_view("auth-train", rail, money_bound("50")),)

        await drive.page.fill("#utterance", "up to fifty for the train")
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")

        body = drive.page.locator("#answer-body")
        await expect(body).to_contain_text("I have taken that as standing permission")
        await expect(body).to_contain_text("id: auth-train")
        await expect(body).to_contain_text("What this authorises")
        await expect(body.get_by_role("button", name="Withdraw this")).to_have_count(0)


# --- §11 at the question -------------------------------------------------------


@pytest.mark.parametrize("viewport", _VIEWPORTS)
async def test_the_confirmation_says_what_answering_would_leave_standing(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§11 at the question, driven at both widths.

    *"A confirmation that establishes a bound without naming it is not a confirmation of
    that bound"*, and the whole of it is above the approval control — ADR-0233 §8's
    ordering clause read onto this member.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.engine.park(
            "h-1",
            authorization=AuthorizationProjection(
                coverage=(
                    CoverageView(
                        kind=BoundKind.MONEY, bound=money_bound("50"), span="up to fifty pounds"
                    ),
                ),
                expires_at=AUTHORIZATION_NOW + timedelta(hours=1),
                quote=None,
            ),
        )

        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")

        row = drive.page.locator("#confirmation-list .confirmation-row")
        await expect(row).to_contain_text("Answering yes also leaves a standing authority")
        await expect(row).to_contain_text("the amount: up to 50 GBP")
        await expect(row).to_contain_text('from what you said: "up to fifty pounds"')
        above = await drive.page.evaluate(_PROJECTION_IS_ABOVE_THE_CONTROL)
        assert above is True


#: Whether every sentence of the projection sits above the approval control's own pixels.
#:
#: ADR-0233 §8's ordering clause is *"a claim about a rendering that no assertion over
#: the bytes can check"* (§15), and §11's projection inherits it: an owner who pressed
#: *yes* having scrolled past the bound has not been shown it.
_PROJECTION_IS_ABOVE_THE_CONTROL = """
() => {
  const row = document.querySelector('#confirmation-list .confirmation-row');
  const lines = [...row.querySelectorAll('p')].filter(
    (one) =>
      one.textContent.includes('standing authority') ||
      one.textContent.includes('the amount:')
  );
  const control = row.querySelector('button');
  const top = control.getBoundingClientRect().top;
  return lines.length > 0 && lines.every((one) => one.getBoundingClientRect().bottom <= top);
}
"""


async def test_a_confirmation_that_establishes_nothing_standing_says_nothing(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0178 §4's discriminator: ``null`` is absence, and absence renders nothing.

    A sentence on every ordinary confirmation saying *"this establishes nothing
    standing"* would be noise on the overwhelming majority of them.
    """
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        drive.engine.park("h-1")

        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")

        row = drive.page.locator("#confirmation-list .confirmation-row")
        await expect(row).not_to_contain_text("standing authority")


async def test_an_empty_coverage_says_what_it_covers_rather_than_nothing(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§20 arm 54: an empty projection is an authority over an **argument-free** call.

    A blank here would read as *"no limits"*, which is the opposite of what the record
    says.
    """
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        drive.engine.park(
            "h-1",
            authorization=AuthorizationProjection(
                coverage=(), expires_at=AUTHORIZATION_NOW + timedelta(hours=1), quote=None
            ),
        )

        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")

        row = drive.page.locator("#confirmation-list .confirmation-row")
        await expect(row).to_contain_text("no argument of yours")
        await expect(row).to_contain_text("not permission for anything wider")


#: The figure a proposed row was built over (ADR-0267 §7).
#:
#: **A different amount in a different currency from the ceiling beside it**, so an arm
#: asserting the figure cannot pass on the bound: a quote of ``50 GBP`` under a ceiling of
#: ``up to 50 GBP`` would be satisfied by a page that rendered the bound twice.
QUOTE: Final = QuoteView(
    amount=Decimal("45.50"),
    currency="EUR",
    read_at=datetime(2026, 9, 13, 8, 0, tzinfo=UTC),
)


@pytest.mark.parametrize("viewport", _VIEWPORTS)
async def test_the_question_names_the_figure_the_act_was_quoted_at(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """ADR-0267 §7 at the question, driven at both widths.

    *"A confirmation that renders a ceiling without the figure the act was quoted at is
    not a confirmation of that charge"*, and §6 rests the disclosure on **both** halves:
    the number the proof rests on and how old it is.

    **Beside and never in place of the ceiling**, which is what the two different
    currencies here make checkable — and the whole of it is above the approval control,
    ADR-0233 §8's ordering clause read onto this member exactly as the projection's own
    arm reads it.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.engine.park(
            "h-1",
            authorization=AuthorizationProjection(
                coverage=(
                    CoverageView(
                        kind=BoundKind.MONEY, bound=money_bound("50"), span="up to fifty pounds"
                    ),
                ),
                expires_at=AUTHORIZATION_NOW + timedelta(hours=1),
                quote=QUOTE,
            ),
        )

        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")

        row = drive.page.locator("#confirmation-list .confirmation-row")
        await expect(row).to_contain_text("quoted at 45.50 EUR")
        await expect(row).to_contain_text("2026-09-13T08:00:00+00:00")
        await expect(row).to_contain_text("the amount: up to 50 GBP")
        assert await drive.page.evaluate(_PROJECTION_IS_ABOVE_THE_CONTROL) is True


async def test_the_figure_is_disclosed_and_is_never_offered_as_a_check(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0267 §6: *"That is a disclosure and not a check"*.

    Nothing expires a quote, no comparison reads its age, and the window between the
    reading and the charge is open — so the page says what the figure is and says that
    answering is not a warrant that it still holds, rather than leaving a bare number to
    be read as a guarantee.
    """
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        drive.engine.park(
            "h-1",
            authorization=AuthorizationProjection(
                coverage=(), expires_at=AUTHORIZATION_NOW + timedelta(hours=1), quote=QUOTE
            ),
        )

        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")

        row = drive.page.locator("#confirmation-list .confirmation-row")
        await expect(row).to_contain_text("not a warrant that it is still current")
        shown = await row.inner_text()
        for claim in ("guaranteed", "held for you", "locked"):
            assert claim not in shown, claim


async def test_a_question_whose_row_records_no_figure_renders_none(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0178 §4 one member in: ``null`` is absence, and absence renders nothing.

    ADR-0267 §7 gives the field three absent cases on the one write path that sets it,
    and none of them is a figure this page could invent. The projection around it still
    renders whole.
    """
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        drive.engine.park(
            "h-1",
            authorization=AuthorizationProjection(
                coverage=(
                    CoverageView(
                        kind=BoundKind.MONEY, bound=money_bound("50"), span="up to fifty pounds"
                    ),
                ),
                expires_at=AUTHORIZATION_NOW + timedelta(hours=1),
                quote=None,
            ),
        )

        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")

        row = drive.page.locator("#confirmation-list .confirmation-row")
        await expect(row).to_contain_text("the amount: up to 50 GBP")
        await expect(row).not_to_contain_text("quoted at")
        await expect(row).not_to_contain_text("still current")


async def test_a_quote_that_arrived_malformed_refuses_that_question_and_not_the_page(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0267 §7, in the direction that costs something: a ceiling rendered **without**
    the figure *"is not a confirmation of that charge"*.

    So a projection carrying a quote this page cannot read refuses **that** confirmation
    rather than rendering the bound and dropping the figure silently — ADR-0178 §4's own
    narrowness (*"may refuse that confirmation rather than every confirmation"*), and
    ``readCoverageView``'s existing arrangement one member over.

    Driven by rewriting the response on the wire, because a conforming hub cannot send
    this shape: ``QuoteView`` refuses it outright.
    """
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        drive.engine.park(
            "h-1",
            authorization=AuthorizationProjection(
                coverage=(
                    CoverageView(
                        kind=BoundKind.MONEY, bound=money_bound("50"), span="up to fifty pounds"
                    ),
                ),
                expires_at=AUTHORIZATION_NOW + timedelta(hours=1),
                quote=QUOTE,
            ),
        )
        await drive.page.route("**/confirmations", _without_the_currency)

        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmations:not([hidden])")

        panel = drive.page.locator("#confirmations")
        await expect(panel).to_contain_text("cannot be rendered here")
        await expect(panel).not_to_contain_text("the amount: up to 50 GBP")
        await expect(panel).not_to_contain_text("45.50")


async def _without_the_currency(route: Route) -> None:
    """Strip the quote's ``currency`` out of every parked confirmation on the wire."""
    response = await route.fetch()
    body = json.loads(await response.text())
    for one in body["confirmations"]:
        quote = one["authorization"]["quote"]
        del quote["currency"]
    await route.fulfill(response=response, body=json.dumps(body))


# --- §11's announcement ---------------------------------------------------------


async def test_an_act_that_opened_two_authorities_is_announced_as_two(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§20 arm 64: two rows, two views, two different bounds, each naming its own
    declaration — and each carrying its own withdrawal handle at the instant the
    authority comes into being.
    """
    rail = ToolDefinition.model_validate(AUTHORIZATION_TOOL.model_dump() | {"id": "rail"})
    hotels = ToolDefinition.model_validate(AUTHORIZATION_TOOL.model_dump() | {"id": "hotels"})
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        drive.engine.authorizations = tuple(
            _view(one, tool, bound)
            for one, tool, bound in (
                ("auth-train", rail, money_bound("50")),
                ("auth-hotel", hotels, money_bound("100")),
            )
        )

        await drive.page.fill("#utterance", "up to fifty for the train and a hundred for the hotel")
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")

        body = drive.page.locator("#answer-body")
        await expect(body).to_contain_text("I have taken that as standing permission")
        await expect(body).to_contain_text("rail")
        await expect(body).to_contain_text("hotels")
        await expect(body).to_contain_text("up to 50 GBP")
        await expect(body).to_contain_text("up to 100 GBP")
        await expect(body).to_contain_text("id: auth-train")
        await expect(body).to_contain_text("id: auth-hotel")
