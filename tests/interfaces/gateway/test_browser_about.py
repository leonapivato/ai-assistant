"""The About you panel and the belief panel's pins, in a real browser (ADR-0338 §8:2).

The engine behind the page is the canonical fake with its person model switched on over
the shared suite's stores (``person_seed``), so each answer is the one the engine's
contract holds the fake to, and what is driven here is the page: the fields edited and
cleared, the slot with its fill and what it left out, a pin no longer current unpinned,
a style memory removed, a suggestion accepted and one dismissed, the change log, and a
pin made from the belief panel — each refusal said in words, and a hub with the switch
off shown as not switched on and never as a fault. Both widths ADR-0233 §15 has the
browser lane drive, with no horizontal scroll and an empty console.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import TYPE_CHECKING, Final

import pytest
from browser_drive import DESKTOP, PHONE, driving, press
from person_seed import ended, fact, field_suggestion, hold, outside, pin_suggestion, switch_on
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import expect
from test_browser_session_loss import _ends_the_session

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    PersonActHow,
    PersonModelAct,
    ProfileField,
    QuestionPart,
)
from ai_assistant.testing.memories import memory, pinned_support

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import (
        Browser,
        ConsoleMessage,
        Dialog,
        Page,
        Route,
        ViewportSize,
    )

    from ai_assistant.testing import FakePersonModelStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

_WIDTHS: Final = pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])

_PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)

#: A wording long enough to need wrapping at a phone's width, which is where a row that
#: does not wrap would push the page sideways.
_LONG: Final = (
    "Prefers that replies about travel name the train before the flight, and the "
    "cheaper fare before the faster one, unless the trip is for work"
)


def _complaints(page: Page) -> list[str]:
    """Every console error and uncaught exception, but the browser's own favicon probe."""
    heard: list[str] = []

    def note(message: ConsoleMessage) -> None:
        if message.type == "error" and not message.location["url"].endswith("/favicon.ico"):
            heard.append(f"{message.location['url']}: {message.text}")

    page.on("console", note)
    page.on("pageerror", lambda error: heard.append(str(error)))
    return heard


async def _overflow(page: Page) -> int:
    overflow: int = await page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    return overflow


async def _seed(drive: Drive) -> tuple[FakePersonModelStore, dict[str, str]]:
    """A person model with something in every part of the panel; its store, the ids."""
    people, memory = switch_on(drive.engine, budget_chars=60)
    await hold(
        drive.engine,
        memory,
        fact("m:diet", "Eats no meat."),
        fact("m:style", _LONG),
        outside("m:out", "The shop's page says Robin likes jazz."),
        ended("m:old", "Lives in Porto.", successor=None),
        fact("m:ada", "Sister Ada lives in Lisbon."),
    )
    await drive.engine.set_profile_field(OWNER_PERSON_ID, field=ProfileField.NAME, value="Robin")
    await drive.engine.pin_memory(OWNER_PERSON_ID, memory_id="m:diet")
    await people.add_pin(OWNER_PERSON_ID, "m:out", act=_PANEL)
    await people.add_pin(OWNER_PERSON_ID, "m:old", act=_PANEL)
    mark = await people.add_style_mark(OWNER_PERSON_ID, "m:style")
    language = await people.record_suggestion(
        OWNER_PERSON_ID, field_suggestion(ProfileField.LANGUAGE, "Português")
    )
    address = await people.record_suggestion(
        OWNER_PERSON_ID, field_suggestion(ProfileField.ADDRESS, "Rob")
    )
    ada = await people.record_suggestion(OWNER_PERSON_ID, pin_suggestion("m:ada"))
    ids = {
        "mark": mark.record_id,
        "language": language.record_id,
        "address": address.record_id,
        "ada": ada.record_id,
    }
    assert all(ids.values()), ids
    return people, {name: value for name, value in ids.items() if value is not None}


async def _open(drive: Drive) -> None:
    async with drive.page.expect_response("**/person/changes"):
        await press(drive.page, "#about-button")
    await drive.page.wait_for_selector("#about:not([hidden])")


async def _texts(page: Page, selector: str, count: int) -> list[str]:
    """The text of ``count`` rows, read once that many are on the page.

    A list is rendered whole in one pass from one answer, so waiting for its count waits
    for the render: the rows read after it are that answer's, never the page's last.
    """
    rows = page.locator(selector)
    await expect(rows).to_have_count(count)
    return [await rows.nth(index).inner_text() for index in range(count)]


def _opening(words: str) -> re.Pattern[str]:
    """A text that starts with ``words``, for a waiting assertion on a line's opening.

    The pattern is run by the browser's ``RegExp``, so only what is special to both is
    escaped (``re.escape`` also escapes spaces, which only a lenient ``RegExp`` reads).
    """
    return re.compile("^" + re.sub(r"[.*+?^${}()|[\]\\/]", r"\\\g<0>", words))


def _lines(text: str) -> list[str]:
    """A row's rendered lines, without the blank ones its paragraphs' margins make."""
    return [one for one in text.splitlines() if one.strip()]


# --- the switch ------------------------------------------------------------------


@_WIDTHS
async def test_a_hub_with_no_person_model_shows_the_panel_as_not_switched_on(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """``PersonModelOffError`` is a state: the panel says so, with no fault and no error."""
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        heard = _complaints(drive.page)
        async with drive.page.expect_response("**/person"):
            await press(drive.page, "#about-button")
        await drive.page.wait_for_selector("#about:not([hidden])")

        await expect(drive.page.locator("#about-state")).to_have_text(
            _opening("The person model is not switched on on this hub yet")
        )
        await expect(drive.page.locator("#about-body")).to_be_hidden()
        await expect(drive.page.locator("#about > .fault:not([hidden])")).to_have_count(0)
        asked = [name for name, _ in drive.engine.calls]
        assert "person_model" in asked
        assert "profile_changes" not in asked
        assert heard == []


async def test_a_belief_panel_on_such_a_hub_offers_no_pin(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        heard = _complaints(drive.page)
        drive.engine.beliefs_held = {}
        _, memory = switch_on(drive.engine)
        drive.engine.person_blocks = None
        await hold(drive.engine, memory, fact("m:diet", "Eats no meat."))

        async with drive.page.expect_response("**/candidates/pending"):
            await press(drive.page, "#beliefs-button")

        await expect(drive.page.locator("#belief-pin-state")).to_have_text(
            "Pinning is not switched on on this hub yet."
        )
        # The row first, so that no Pin is counted on a list not yet rendered.
        await expect(drive.page.locator("#belief-list button", has_text="Forget")).to_have_count(1)
        await expect(drive.page.locator("#belief-list button", has_text="Pin")).to_have_count(0)
        assert heard == []


# --- the panel -------------------------------------------------------------------


@_WIDTHS
async def test_the_panel_shows_every_part_of_the_model_in_words(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§8:2: the fields, the slot with its fill and what it left out, the pins no longer
    current, the style memories, the suggestions and the change log."""
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        heard = _complaints(drive.page)
        await _seed(drive)

        await _open(drive)

        page = drive.page
        await expect(page.locator("#field-name")).to_have_value("Robin")
        fields = page.locator("#profile-fields > form")
        await expect(fields.nth(2)).to_contain_text("Not set: I go by Aether.")
        await expect(fields.nth(3)).to_contain_text("Not set: I use the hub's own time zone.")
        await expect(page.locator("#kept-fill")).to_have_text(
            "Using 13 of the 60 characters I keep in mind."
        )
        assert [_lines(text) for text in await _texts(page, "#kept-list > .about-row", 1)] == [
            ["Pinned", "Eats no meat.", "Unpin"]
        ]
        left = await _texts(page, "#left-out-list > .about-row", 2)
        assert "The shop's page says Robin likes jazz." in left[0]
        assert "it rests on outside content" in left[0]
        assert _LONG in left[1]
        assert "no room left for it" in left[1]
        stale = await _texts(page, "#no-longer-current-list > .about-row", 1)
        assert "Lives in Porto." in stale[0]
        styles = await _texts(page, "#style-list > .about-row", 1)
        assert [_lines(text) for text in styles] == [[_LONG, "Remove"]]
        suggestions = await _texts(page, "#suggestion-list > .about-row", 3)
        assert any("Sister Ada lives in Lisbon." in text for text in suggestions)
        assert any("“Português”" in text for text in suggestions)
        # The change log is read after the rest of the panel has been rendered.
        changes = await _texts(page, "#change-list > .about-row", 1)
        assert _lines(changes[0])[0] == "Your name: not set → “Robin”"
        assert _lines(changes[0])[1].endswith("· by you, on the panel or the command line")
        assert await _overflow(page) <= 0
        assert heard == []


@_WIDTHS
async def test_a_yes_on_a_card_is_logged_by_its_request_and_a_yes_to_a_question_as_before(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """ADR-0362 §2:1: a change a ticket ran is said as a yes on that request's card; a
    stored act of the question form keeps its words (ADR-0361 §8:5)."""
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        heard = _complaints(drive.page)
        people, _ = switch_on(drive.engine)
        # A request id is a uuid's 32 hex digits, unbroken: at a phone's width it wraps.
        request = "approval:938d954a1f2e4c6b8a0d3e5f7a9b1c2d"
        asked = PersonModelAct(
            how=PersonActHow.APPROVAL,
            by=OWNER_PERSON_ID,
            approval=QuestionPart(round="r-ask", part=1),
            episode_id="episode:asked",
        )
        tapped = PersonModelAct(
            how=PersonActHow.APPROVAL,
            by=OWNER_PERSON_ID,
            request=request,
            episode_id="episode:approval",
        )
        await people.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Rob", act=asked)
        await people.set_field(OWNER_PERSON_ID, ProfileField.ADDRESS, "Test19", act=tapped)

        await _open(drive)

        rows = drive.page.locator("#change-list > .about-row")
        await expect(rows).to_have_count(2)
        await expect(rows.nth(0).locator(".hint")).to_have_text(
            re.compile(r' · by your yes on the card for request "' + request + '"$')
        )
        await expect(rows.nth(0)).to_contain_text("What I call you: not set → “Test19”")
        await expect(rows.nth(0)).not_to_contain_text("question")
        await expect(rows.nth(1).locator(".hint")).to_have_text(
            re.compile(r" · by your yes to my question$")
        )
        await expect(rows.nth(1)).to_contain_text("Your name: not set → “Rob”")
        assert await _overflow(drive.page) <= 0
        assert heard == []


@_WIDTHS
async def test_a_field_is_saved_cleared_and_refused_in_words(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§3: a field edited, cleared, and a zone ``zoneinfo`` refuses said as refused."""
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        heard = _complaints(drive.page)
        people, _ = switch_on(drive.engine)
        await _open(drive)
        page = drive.page
        outcome = page.locator("#about-outcome")

        await page.fill("#field-time_zone", "Mars/Olympus")
        async with page.expect_response("**/person/changes"):
            await page.press("#field-time_zone", "Enter")
        await expect(outcome).to_have_text(_opening("That value was not saved. The rule is:"))
        # What was refused is what the person corrects, so it stays in the box.
        await expect(page.locator("#field-time_zone")).to_have_value("Mars/Olympus")

        await page.fill("#field-time_zone", "Europe/Lisbon")
        async with page.expect_response("**/person/changes"):
            await page.press("#field-time_zone", "Enter")
        await expect(outcome).to_have_text("Saved.")
        # The panel is built again, its change log last, and only then is the keyboard
        # left where it was: the focus is read once the log shows the save.
        await expect(page.locator("#change-list > .about-row")).to_have_count(1)
        await expect(page.locator("#field-time_zone")).to_be_focused()
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert held.profile.time_zone == "Europe/Lisbon"
        await expect(page.locator("#profile-fields > form").nth(3)).to_contain_text(
            "Now: Europe/Lisbon"
        )

        async with page.expect_response("**/person/changes"):
            await (
                page.locator("#profile-fields > form")
                .nth(3)
                .get_by_role("button", name="Clear")
                .click()
            )
        await expect(outcome).to_have_text("Cleared.")
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert held.profile.time_zone is None
        changes = await _texts(page, "#change-list > .about-row", 2)
        assert [_lines(text)[0] for text in changes] == [
            "Your time zone: “Europe/Lisbon” → not set",
            "Your time zone: not set → “Europe/Lisbon”",
        ]
        assert heard == []


async def test_a_stale_pin_is_unpinned_a_style_memory_removed_and_suggestions_decided(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§4:8, §5:3, §8:8 and §9:2: each act from its own row, and the panel read again."""
    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        heard = _complaints(drive.page)
        people, ids = await _seed(drive)
        await _open(drive)
        page = drive.page
        outcome = page.locator("#about-outcome")

        async with page.expect_response("**/person/changes"):
            await page.locator("#no-longer-current-list button", has_text="Unpin").click()
        await expect(outcome).to_have_text("Unpinned. The memory itself is kept.")
        await expect(page.locator("#no-longer-current")).to_be_hidden()

        async with page.expect_response("**/person/changes"):
            await page.locator("#style-list button", has_text="Remove").click()
        await expect(outcome).to_have_text(_opening("Removed."))
        await expect(page.locator("#style-list")).to_have_text("Nothing yet.")

        language = page.locator("#suggestion-list > .about-row", has_text="Português")
        async with page.expect_response("**/person/changes"):
            await language.get_by_role("button", name="Accept").click()
        await expect(outcome).to_have_text("Accepted.")
        await expect(page.locator("#field-language")).to_have_value("Português")

        address = page.locator("#suggestion-list > .about-row", has_text="“Rob”")
        async with page.expect_response("**/person/changes"):
            await address.get_by_role("button", name="Dismiss").click()
        await expect(outcome).to_have_text("Dismissed. I will not suggest it again.")

        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert [one.id for one in held.suggestions] == [ids["ada"]]
        assert held.standing_marks == ()
        assert [one.memory_id for one in held.standing_pins] == ["m:diet", "m:out"]
        assert heard == []


async def test_a_list_past_a_page_offers_the_rest_and_reads_that_list_alone(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Each list is a page beside its total (§8:1); the rest is one press away."""
    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        heard = _complaints(drive.page)
        people, memory = switch_on(drive.engine)
        records = [fact(f"m:{index:02}", f"Style {index:02}.") for index in range(27)]
        await hold(drive.engine, memory, *records)
        for record in records:
            await people.add_style_mark(OWNER_PERSON_ID, record.id)
        await _open(drive)
        page = drive.page

        await expect(page.locator("#style-list > .about-row")).to_have_count(25)
        async with page.expect_request("**/person") as asked:
            await page.locator("#style-list > button", has_text="Show more").click()
        await (await asked.value).response()
        await expect(page.locator("#style-list > .about-row")).to_have_count(27)

        sent = (await asked.value).post_data_json
        assert sent is not None
        assert (sent["lists"], sent["offset"]) == (["style_marks"], 25)
        await expect(page.locator("#style-list > button")).to_have_count(0)
        assert heard == []


# --- the belief panel's pin and unpin ----------------------------------------------


@_WIDTHS
async def test_a_memory_is_pinned_from_the_belief_panel_whose_control_says_it_confirms(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§8:2 and §4:3: pin and unpin on each current memory; a refusal in words."""
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        heard = _complaints(drive.page)
        people, memory = switch_on(drive.engine, budget_chars=20)
        await hold(
            drive.engine,
            memory,
            fact("m:diet", "Eats no meat."),
            fact("m:long", "A wording longer than the budget."),
        )
        page = drive.page
        async with page.expect_response("**/candidates/pending"):
            await press(page, "#beliefs-button")
        await expect(page.locator("#belief-pin-state")).to_have_text(
            "Pinning a memory keeps it in mind in every conversation, and confirms its "
            "wording as yours."
        )
        diet = page.locator("#belief-list > .belief-row", has_text="Eats no meat.")
        long = page.locator("#belief-list > .belief-row", has_text="longer than the budget")
        outcome = page.locator("#belief-outcome")

        pin = diet.get_by_role("button", name="Pin: confirms this wording")
        await pin.focus()
        async with page.expect_response("**/person/pin"):
            await page.keyboard.press("Enter")
        # The outcome is written once the page has read the answer's body, which can be
        # after the response has arrived, so each one is waited for, never read straight off.
        await expect(outcome).to_have_text(_opening("Pinned."))

        async with page.expect_response("**/person/pin"):
            await long.get_by_role("button", name="Pin: confirms this wording").click()
        await expect(outcome).to_have_text(
            _opening("Pinning it would take what I keep in mind over its budget")
        )

        async with page.expect_response("**/person/unpin"):
            await diet.get_by_role("button", name="Unpin").click()
        await expect(outcome).to_have_text("Unpinned. The memory itself is kept.")

        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert held.standing_pins == ()
        assert await _overflow(page) <= 0
        assert heard == []


async def test_a_memory_confirmed_by_a_pin_says_it_was_pinned_not_asked(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """#3333: the row, which carries no supports, names neither way; the single view
    read before a forget says the person pinned it, and never "when I asked you"."""
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        heard = _complaints(drive.page)
        _, store = switch_on(drive.engine)
        await hold(drive.engine, store, memory("m:sun", "Calls home on Sundays.", pinned_support()))
        shown: list[str] = []
        asked = asyncio.Event()

        async def answer(dialog: Dialog) -> None:
            shown.append(dialog.message)
            await dialog.dismiss()
            asked.set()

        drive.page.on("dialog", answer)
        page = drive.page
        async with page.expect_response("**/candidates/pending"):
            await press(page, "#beliefs-button")
        row = page.locator("#belief-list > .belief-row", has_text="Calls home on Sundays.")
        await expect(row).to_contain_text(
            re.compile(r"^Why: You confirmed this wording\.$", re.MULTILINE), use_inner_text=True
        )

        # The question is asked once the page has read the single view's body, so it is
        # waited for, not assumed to have come with the response.
        await row.get_by_role("button", name="Forget").click()
        await asyncio.wait_for(asked.wait(), timeout=5)

        assert len(shown) == 1
        assert "Why: You confirmed this wording by pinning it." in shown[0]
        assert "when I asked you" not in shown[0]
        assert heard == []


async def test_a_pin_is_refused_where_the_id_now_names_another_wording_than_the_row(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """§4:3: a pin confirms the wording shown, so it is made only on the row's wording.

    The listing's id is normalised and the person model's is not (§10:4): two memories
    whose ids differ only by padding list under one id, and a pin from the padded one's
    row would pin, and confirm, the other (adversarial review, round 1).
    """
    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        heard = _complaints(drive.page)
        people, store = switch_on(drive.engine)
        await hold(
            drive.engine, store, fact(" m:diet ", "Eats no meat."), fact("m:diet", "Eats meat.")
        )
        page = drive.page
        async with page.expect_response("**/candidates/pending"):
            await press(page, "#beliefs-button")
        padded = page.locator("#belief-list > .belief-row", has_text="Eats no meat.")
        plain = page.locator("#belief-list > .belief-row", has_text="Eats meat.")
        outcome = page.locator("#belief-outcome")

        async with page.expect_response("**/belief"):
            await padded.get_by_role("button", name="Pin: confirms this wording").click()
        await expect(outcome).to_have_text(_opening("That memory is not the one shown here"))
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert held.pins == ()

        async with page.expect_response("**/person/pin"):
            await plain.get_by_role("button", name="Pin: confirms this wording").click()
        await expect(outcome).to_have_text(_opening("Pinned."))

        # And the padded row's Unpin does not take the other memory's pin away.
        async with page.expect_response("**/belief"):
            await padded.get_by_role("button", name="Unpin").click()
        await expect(outcome).to_have_text(_opening("That memory is not the one shown here"))
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert [pin.memory_id for pin in held.standing_pins] == ["m:diet"]

        async with page.expect_response("**/person/unpin"):
            await plain.get_by_role("button", name="Unpin").click()
        await expect(outcome).to_have_text("Unpinned. The memory itself is kept.")
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert held.standing_pins == ()
        assert heard == []


async def test_a_belief_act_while_one_is_out_is_said_and_not_sent(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A Pin whose read is slow holds the write lock from before that read, so an Unpin
    pressed meanwhile is refused in words, never sent ahead of it (adversarial review,
    round 6)."""
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()
    sent: list[str] = []

    async def hang(route: Route) -> None:
        sent.append(route.request.url)
        await release
        await route.fallback()

    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        heard = _complaints(drive.page)
        people, store = switch_on(drive.engine)
        await hold(drive.engine, store, fact("m:diet", "Eats no meat."))
        page = drive.page
        async with page.expect_response("**/candidates/pending"):
            await press(page, "#beliefs-button")
        diet = page.locator("#belief-list > .belief-row", has_text="Eats no meat.")
        outcome = page.locator("#belief-outcome")
        await page.route("**/belief", hang)

        async with page.expect_request("**/belief"):
            await diet.get_by_role("button", name="Pin: confirms this wording").click()
        await diet.get_by_role("button", name="Unpin").click()
        await expect(outcome).to_have_text(_opening("Your last change is still being made"))
        async with page.expect_response("**/person/pin"):
            release.set_result(None)

        await expect(outcome).to_have_text(_opening("Pinned."))
        assert len(sent) == 1
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert [pin.memory_id for pin in held.standing_pins] == ["m:diet"]
        assert heard == []


@_WIDTHS
async def test_a_belief_read_stalled_under_an_ended_session_holds_up_no_later_write(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """A Pin's read, stalled while its session ends, refuses no write of the session
    re-entered after it, and sends no pin once it is let go (adversarial review,
    round 8)."""
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()
    pins: list[str] = []

    async def hang(route: Route) -> None:
        await release
        # The page may have moved on from under a held route in a failing run; the
        # case's own assertions are what report it.
        with contextlib.suppress(PlaywrightError):
            await route.fallback()

    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        people, store = switch_on(drive.engine)
        await hold(drive.engine, store, fact("m:diet", "Eats no meat."))
        page = drive.page
        page.on("request", lambda one: pins.append(one.url) if "/person/pin" in one.url else None)
        async with page.expect_response("**/candidates/pending"):
            await press(page, "#beliefs-button")
        diet = page.locator("#belief-list > .belief-row", has_text="Eats no meat.")
        await page.route("**/belief", hang)
        async with page.expect_request("**/belief"):
            await diet.get_by_role("button", name="Pin: confirms this wording").click()

        await page.route("**/sources", _ends_the_session)
        await press(page, "#sources-button")
        await page.wait_for_selector("#bootstrap:not([hidden])")
        await page.unroute("**/sources")
        await drive.admit()
        await _open(drive)

        await page.fill("#field-name", "Robin")
        async with page.expect_response("**/person/changes"):
            await page.press("#field-name", "Enter")
        await expect(page.locator("#about-outcome")).to_have_text("Saved.")
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert held.profile.name == "Robin"

        # The old session's read, let go: its answer is not this session's, so no pin
        # follows it. The ordering is a whole round trip after its last byte.
        async with page.expect_response("**/belief") as stale:
            release.set_result(None)
        await (await stale.value).finished()
        async with page.expect_response("**/person/changes"):
            await press(page, "#about-button")
        assert pins == []
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        # No console check: the browser logs the ended session's own refusals (the 401
        # that ends it, the 409 its stalled read is answered), which are not defects.
        assert held.standing_pins == ()


async def test_a_save_keeps_what_was_typed_in_other_fields_and_while_it_was_sent(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Every write reads the panel again; a draft never sent survives it (adversarial
    review, round 1), and so does one typed while the write was in flight, whose box
    keeps the keyboard and its caret through the rebuild (round 10)."""
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()

    async def hang(route: Route) -> None:
        await release
        await route.fallback()

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        heard = _complaints(drive.page)
        people, _ = switch_on(drive.engine)
        await _open(drive)
        page = drive.page

        await page.fill("#field-name", "Robin")
        await page.fill("#field-language", "Português")
        await page.route("**/person/field/set", hang)
        async with page.expect_request("**/person/field/set"):
            await page.press("#field-name", "Enter")
        await page.fill("#field-address", "Rob")
        async with page.expect_response("**/person/changes"):
            release.set_result(None)

        await expect(page.locator("#about-outcome")).to_have_text("Saved.")
        await expect(page.locator("#field-name")).to_have_value("Robin")
        await expect(page.locator("#field-language")).to_have_value("Português")
        await expect(page.locator("#field-address")).to_have_value("Rob")
        await expect(page.locator("#change-list > .about-row")).to_have_count(1)
        await expect(page.locator("#field-address")).to_be_focused()
        await page.keyboard.type("by")
        await expect(page.locator("#field-address")).to_have_value("Robby")
        await expect(page.locator("#field-name")).to_have_value("Robin")
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert (held.profile.name, held.profile.language, held.profile.address) == (
            "Robin",
            None,
            None,
        )
        assert heard == []


async def test_a_box_typed_back_to_its_old_value_while_saving_keeps_what_was_typed(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A correction typed into the field being saved is a draft too, whatever its value
    (adversarial review, round 2)."""
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()

    async def hang(route: Route) -> None:
        await release
        await route.fallback()

    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        heard = _complaints(drive.page)
        people, _ = switch_on(drive.engine)
        await drive.engine.set_profile_field(
            OWNER_PERSON_ID, field=ProfileField.NAME, value="Robin"
        )
        await _open(drive)
        page = drive.page

        await page.fill("#field-name", "Rob")
        await page.route("**/person/field/set", hang)
        async with page.expect_request("**/person/field/set"):
            await page.press("#field-name", "Enter")
        await page.fill("#field-name", "Robin")
        async with page.expect_response("**/person/changes"):
            release.set_result(None)

        await expect(page.locator("#about-outcome")).to_have_text("Saved.")
        await expect(page.locator("#field-name")).to_have_value("Robin")
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert held.profile.name == "Rob"
        assert heard == []


async def test_a_second_save_while_one_is_out_is_said_and_not_sent(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Two saves in flight could land in either order; the second is not sent, and
    what it carried stays in the box (adversarial review, round 3)."""
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()
    sent: list[str] = []

    async def hang(route: Route) -> None:
        sent.append(route.request.post_data or "")
        await release
        await route.fallback()

    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        heard = _complaints(drive.page)
        people, _ = switch_on(drive.engine)
        await _open(drive)
        page = drive.page
        await page.route("**/person/field/set", hang)

        await page.fill("#field-name", "Rob")
        async with page.expect_request("**/person/field/set"):
            await page.press("#field-name", "Enter")
        await page.fill("#field-name", "Robert")
        await page.press("#field-name", "Enter")
        await expect(page.locator("#about-outcome")).to_have_text(
            _opening("Your last change is still being made")
        )
        async with page.expect_response("**/person/changes"):
            release.set_result(None)

        await expect(page.locator("#about-outcome")).to_have_text("Saved.")
        await expect(page.locator("#field-name")).to_have_value("Robert")
        assert len(sent) == 1
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert held.profile.name == "Rob"
        assert heard == []


async def test_a_save_that_never_arrived_leaves_its_text_for_sending_again(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A transport failure says so, and the panel read again keeps the unsent text."""
    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        switch_on(drive.engine)
        await _open(drive)
        page = drive.page
        await page.route("**/person/field/set", lambda route: route.abort())

        await page.fill("#field-language", "Português")
        await page.press("#field-language", "Enter")
        await page.wait_for_selector("#about > .fault:not([hidden])")
        async with page.expect_response("**/person/changes"):
            await press(page, "#about-button")

        await expect(page.locator("#field-language")).to_have_value("Português")


async def test_a_belief_panel_that_could_not_read_the_switch_says_so(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A failed read of the person model is said on the panel's state line, which the
    listing read after it does not clear, and no row offers a pin (round 3)."""
    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        _, store = switch_on(drive.engine)
        await hold(drive.engine, store, fact("m:diet", "Eats no meat."))
        page = drive.page
        await page.route(
            "**/person",
            lambda route: route.fulfill(
                status=422,
                content_type="application/json",
                body='{"fault": "assistant-declined", "detail": "the store could not be read"}',
            ),
        )

        async with page.expect_response("**/candidates/pending"):
            await press(page, "#beliefs-button")

        await expect(page.locator("#belief-pin-state")).to_have_text(
            _opening("I could not read whether pinning is switched on")
        )
        # The row first, so that no Pin is counted on a list not yet rendered.
        await expect(page.locator("#belief-list .belief-row")).to_have_count(1)
        await expect(page.locator("#belief-list button", has_text="Pin")).to_have_count(0)


async def test_a_stalled_read_after_a_write_holds_up_no_later_write(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The one-write lock is the write's alone; the read after it is ordered by its run
    (adversarial review, round 4)."""
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()
    held_once: list[bool] = []

    async def stall_first(route: Route) -> None:
        if not held_once:
            held_once.append(True)
            await release
        await route.fallback()

    async with driving(gateway_browser, tmp_path, viewport=DESKTOP) as drive:
        heard = _complaints(drive.page)
        people, _ = switch_on(drive.engine)
        await _open(drive)
        page = drive.page
        await page.route("**/person/changes", stall_first)

        await page.fill("#field-name", "Robin")
        async with page.expect_request("**/person/changes"):
            await page.press("#field-name", "Enter")
        async with page.expect_response("**/person/changes"):
            await press(page, "#about-button")
        await page.fill("#field-language", "Português")
        async with page.expect_response("**/person/field/set"):
            await page.press("#field-language", "Enter")

        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert (held.profile.name, held.profile.language) == ("Robin", "Português")
        release.set_result(None)
        assert heard == []


async def test_a_read_overtaken_by_a_later_save_leaves_the_focus_where_it_is(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A save's read that comes back after a later save's puts no focus back: the person
    is typing in the later box (adversarial review, round 9)."""
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()
    held_once: list[bool] = []

    async def stall_first(route: Route) -> None:
        if not held_once:
            held_once.append(True)
            await release
        await route.fallback()

    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        heard = _complaints(drive.page)
        switch_on(drive.engine)
        await _open(drive)
        page = drive.page
        language = page.locator("#field-language")
        await page.route("**/person/changes", stall_first)

        await page.fill("#field-name", "Robin")
        async with page.expect_request("**/person/changes"):
            await page.press("#field-name", "Enter")
        await page.fill("#field-language", "Português")
        async with page.expect_response("**/person/changes"):
            await page.press("#field-language", "Enter")
        await expect(page.locator("#change-list > .about-row")).to_have_count(2)
        await expect(language).to_be_focused()

        # The first save's read, let go; the ordering is a whole round trip after its
        # last byte.
        async with page.expect_response("**/person/changes") as stale:
            release.set_result(None)
        await (await stale.value).finished()
        await page.evaluate("() => fetch('/').then((answer) => answer.text())")
        await expect(language).to_be_focused()
        await page.keyboard.type("!")
        await expect(language).to_have_value("Português!")
        await expect(page.locator("#field-name")).to_have_value("Robin")
        assert heard == []


async def test_a_box_typed_in_before_the_panel_has_loaded_keeps_the_keyboard(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The fields are shown before the change log lands; the menu's move to the heading
    once it has does not take the keyboard from a box typed in meanwhile (adversarial
    review, round 11). Left alone, the heading takes it."""
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()

    async def hang(route: Route) -> None:
        await release
        await route.fallback()

    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        heard = _complaints(drive.page)
        switch_on(drive.engine)
        page = drive.page
        address = page.locator("#field-address")
        await page.route("**/person/changes", hang)
        async with page.expect_request("**/person/changes"):
            await press(page, "#about-button")
        await page.fill("#field-address", "Rob")

        async with page.expect_response("**/person/changes") as late:
            release.set_result(None)
        await (await late.value).finished()
        await expect(page.locator("#change-list")).to_contain_text("No change yet.")
        await page.evaluate("() => fetch('/').then((answer) => answer.text())")
        await expect(address).to_be_focused()
        await page.keyboard.type("by")
        await expect(address).to_have_value("Robby")

        await page.unroute("**/person/changes")
        await press(page, "#about-button")
        await expect(page.locator("#about > :first-child")).to_be_focused()
        assert heard == []


async def test_a_box_typed_in_while_a_clear_is_out_keeps_what_was_typed(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Typing is counted, not inferred from the text: typing the old value back during a
    Clear is still a draft (adversarial review, round 4)."""
    loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = loop.create_future()

    async def hang(route: Route) -> None:
        await release
        await route.fallback()

    async with driving(gateway_browser, tmp_path, viewport=PHONE) as drive:
        heard = _complaints(drive.page)
        people, _ = switch_on(drive.engine)
        await drive.engine.set_profile_field(
            OWNER_PERSON_ID, field=ProfileField.NAME, value="Robin"
        )
        await _open(drive)
        page = drive.page
        await page.route("**/person/field/set", hang)

        async with page.expect_request("**/person/field/set"):
            await (
                page.locator("#profile-fields > form")
                .nth(0)
                .get_by_role("button", name="Clear")
                .click()
            )
        await page.fill("#field-name", "Rob")
        await page.fill("#field-name", "Robin")
        async with page.expect_response("**/person/changes"):
            release.set_result(None)

        await expect(page.locator("#about-outcome")).to_have_text("Cleared.")
        await expect(page.locator("#field-name")).to_have_value("Robin")
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert held.profile.name is None
        assert heard == []


@_WIDTHS
async def test_a_value_with_a_line_break_is_saved_back_unchanged(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """§3 bounds a field by its length alone, so a line break set from the command line
    is a valid value; a Save from its box, untouched, writes nothing over it, and an edit
    keeps the breaks it shows (adversarial review, round 7)."""
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        heard = _complaints(drive.page)
        people, _ = switch_on(drive.engine)
        await drive.engine.set_profile_field(
            OWNER_PERSON_ID, field=ProfileField.NAME, value="Robin\nSmith"
        )
        await drive.engine.set_profile_field(
            OWNER_PERSON_ID, field=ProfileField.ADDRESS, value="Rob\r\nby"
        )
        await _open(drive)
        page = drive.page
        outcome = page.locator("#about-outcome")
        name = page.locator("#field-name")
        await expect(name).to_have_value("Robin\nSmith")
        assert await name.evaluate("(box) => box.tagName") == "TEXTAREA"

        for field in (0, 1):
            async with page.expect_response("**/person/changes"):
                await (
                    page.locator("#profile-fields > form")
                    .nth(field)
                    .get_by_role("button", name="Save")
                    .click()
                )
            await expect(outcome).to_have_text("That is what it already was, so nothing changed.")
        await expect(name).to_have_value("Robin\nSmith")
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert (held.profile.name, held.profile.address) == ("Robin\nSmith", "Rob\r\nby")

        # Enter in the box is a line, not a Save; the Save sends the lines shown.
        await name.press("ControlOrMeta+End")
        await name.press("Enter")
        await name.press_sequentially("Jr")
        async with page.expect_response("**/person/changes"):
            await (
                page.locator("#profile-fields > form")
                .nth(0)
                .get_by_role("button", name="Save")
                .click()
            )
        await expect(outcome).to_have_text("Saved.")
        await expect(name).to_have_value("Robin\nSmith\nJr")
        held = await people.read(OWNER_PERSON_ID)
        assert held is not None
        assert held.profile.name == "Robin\nSmith\nJr"
        assert await _overflow(page) <= 0
        assert heard == []
