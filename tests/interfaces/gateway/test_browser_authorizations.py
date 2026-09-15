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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from browser_drive import DESKTOP, PHONE, driving
from playwright.async_api import expect

from ai_assistant.core.types import (
    AuthorizationProjection,
    AuthorizationView,
    CoverageView,
    GoalStatus,
    GoalSummary,
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
        coverage=(CoverageView(argument="amount", bound=bound, span="what you said"),),
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
                    "amount",
                    bound=money_bound("50"),
                    basis=authorization_basis(span="up to fifty pounds"),
                ),
                coverage_member(
                    "terms",
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
        await expect(panel).to_contain_text("amount: up to 50 GBP")
        await expect(panel).to_contain_text('from what you said: "up to fifty pounds"')
        await expect(panel).to_contain_text("terms: one of: refundable")
        await expect(panel).to_contain_text("It still stands")
        await expect(panel).to_contain_text("id: auth-1")
        await expect(panel.get_by_role("button", name="Withdraw this")).to_be_visible()
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
        said = drive.page.locator("#authorization-said")
        await expect(said).to_contain_text("Withdrawn.")
        await expect(said).to_contain_text("Nothing already decided is rewritten")
        await expect(drive.page.locator("#authorizations")).to_contain_text("Nothing standing")
        assert [name for name, _ in drive.engine.calls if "authoriz" in name] == [
            "standing_authorizations",
            "revoke_authorization",
            "standing_authorizations",
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
        await expect(drive.page.locator("#authorization-said")).to_be_hidden()


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

        said = drive.page.locator("#authorization-said")
        await expect(said).to_contain_text("nothing was withdrawn")
        await expect(said).to_contain_text("declining it")
        assert await said.evaluate("(node) => node.className") == "notice"


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
    """
    loop = asyncio.get_running_loop()
    held: asyncio.Future[None] = loop.create_future()
    landed: asyncio.Future[None] = loop.create_future()
    seen = 0
    answered = 0

    async def route(one: Route) -> None:
        nonlocal seen
        seen += 1
        if seen == 1:
            await held
        await one.fallback()

    def arrived(response: Response) -> None:
        """Resolve once the **overtaken** response has reached the page.

        The case's synchronisation (ADR-0216 §7): what the assertions below need is
        that the late answer has been handled and changed nothing — a condition the
        page reached, not a duration the test guessed.
        """
        nonlocal answered
        if not response.url.endswith("/authorizations"):
            return
        answered += 1
        if answered == 2 and not landed.done():
            landed.set_result(None)

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        _seed(drive)
        drive.engine.goal_summaries = [_summary(), _summary(goal_id=OTHER_ID, outcome=OTHER)]
        drive.engine.goal_statements[OTHER_ID] = OTHER
        drive.page.on("response", arrived)
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


async def test_a_withdrawal_reports_nothing_where_the_panel_has_moved_on(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A settlement is attributed to the work it was taken on, or to nothing.

    Start withdrawing a row of goal A, then open goal B before the revocation returns:
    writing *"Withdrawn"* above B's rows would say the act was done to B's work, and
    re-reading A would discard the listing the owner just asked for. The act still
    happens and is recorded — what is dropped is the sentence, because there is nowhere
    honest to put it. Adversarial review, round 3, ``major``.
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
        await (
            drive.page.locator("#goal-list button:has-text('What this authorises')").nth(1).click()
        )
        await expect(drive.page.locator("#authorizations")).to_contain_text(OTHER)
        held.set_result(None)

        await expect(drive.page.locator("#authorization-said")).to_be_hidden()
        await expect(drive.page.locator("#authorizations")).to_contain_text(OTHER)
        assert STATEMENT not in await drive.page.locator("#authorizations").inner_text()
        assert "revoke_authorization" in [name for name, _ in drive.engine.calls]


async def test_a_withdrawal_taken_from_an_announcement_reports_beside_it(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0254 §11's handle is put in front of the owner *at the act*, so the act taken
    there has to report there.

    The panel's own slot is inside a section an owner who has never opened it cannot
    see — and before this fix, pressing an announcement's control mutated the store and
    wrote the settlement into that invisible node: the act working and the owner told
    nothing, which is the opposite of §11's reason for carrying the handle at all.
    Adversarial review, round 1, ``blocker``.

    **The panel is never opened in this case**, deliberately: that is the state the
    defect lived in.
    """
    rail = ToolDefinition.model_validate(AUTHORIZATION_TOOL.model_dump() | {"id": "rail"})
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        drive.engine.hold_authorization(
            opening_act(id="auth-train", goal=GOAL_ID, tool=rail), goal_statement=STATEMENT
        )
        drive.engine.authorizations = (_view("auth-train", rail, money_bound("50")),)
        await drive.page.fill("#utterance", "up to fifty for the train")
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")
        asked = _answering(drive, accept=True)

        await drive.page.click("#answer-body button:has-text('Withdraw this')")
        await asyncio.wait_for(asked, timeout=10)

        beside = drive.page.locator("#answer-body .authorization-said")
        await expect(beside).to_be_visible()
        await expect(beside).to_contain_text("Withdrawn.")
        await expect(drive.page.locator("#authorizations")).to_be_hidden()
        assert [name for name, _ in drive.engine.calls if "authoriz" in name] == [
            "revoke_authorization"
        ]


async def test_a_withdrawal_from_an_announcement_that_moves_nothing_reports_beside_it(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The same, on the refusal: a settlement that moved nothing is still a settlement
    the owner is owed, and it is owed where they took the act.
    """
    rail = ToolDefinition.model_validate(AUTHORIZATION_TOOL.model_dump() | {"id": "rail"})
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        drive.engine.authorizations = (_view("auth-nobody", rail, money_bound("50")),)
        await drive.page.fill("#utterance", "up to fifty for the train")
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")
        asked = _answering(drive, accept=True)

        await drive.page.click("#answer-body button:has-text('Withdraw this')")
        await asyncio.wait_for(asked, timeout=10)

        beside = drive.page.locator("#answer-body .authorization-said")
        await expect(beside).to_be_visible()
        await expect(beside).to_contain_text("no record of that id")


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
                        argument="amount", bound=money_bound("50"), span="up to fifty pounds"
                    ),
                ),
                expires_at=AUTHORIZATION_NOW + timedelta(hours=1),
            ),
        )

        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")

        row = drive.page.locator("#confirmation-list .confirmation-row")
        await expect(row).to_contain_text("Answering yes also leaves a standing authority")
        await expect(row).to_contain_text("amount: up to 50 GBP")
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
    (one) => one.textContent.includes('standing authority') || one.textContent.includes('amount:')
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
                coverage=(), expires_at=AUTHORIZATION_NOW + timedelta(hours=1)
            ),
        )

        await drive.page.click("#confirmations-button")
        await drive.page.wait_for_selector("#confirmation-list .confirmation-row")

        row = drive.page.locator("#confirmation-list .confirmation-row")
        await expect(row).to_contain_text("no argument of yours")
        await expect(row).to_contain_text("not permission for anything wider")


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
