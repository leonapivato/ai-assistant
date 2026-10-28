"""The activation viewer's page, driven in a real browser (ADR-0316 §3, §6:7).

What the server's JSON cannot say: that the page puts an entry's raw text into the
document as text, that a round's calls each show their own verdict, that a round's
drawer shows the tools its request offered, that a model call opens readable with its
raw entries a tab away and each part copies as plain text, and that a drawer shows only
what the last click asked for, however its loads interleave. The viewer is
bound on loopback over a record written by ADR-0314's store, and driven by the suite's
one shared browser (ADR-0216 §3).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
from playwright.async_api import expect
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

sys.path.insert(0, str(Path(__file__).parent))
from _activation_record import (
    HOSTILE,
    KEPT_FACTS,
    READING,
    ROUND_2_MESSAGE,
    ROUND_TOOL_DESCRIPTION,
    SEARCH_RESULT,
    WALKED,
    WALKED_TITLES,
    at,
    iso,
    serving,
    viewer,
    write_record,
    write_walked,
)
from _follow_up_record import ACT_A as FOLLOWED_A
from _follow_up_record import ACT_F as FOLLOWED_F
from _follow_up_record import ANSWER as FOLLOW_UP_ANSWER
from _follow_up_record import MODEL_NAME as FOLLOW_UP_MODEL
from _follow_up_record import write_followed
from _learning_record import (
    ALONE_CLAIM,
    EVIDENCE_CLAIM,
    KEPT_CLAIM,
    NOT_KEPT_CLAIM,
    NOT_KEPT_NOTE,
    SAID,
    write_learning,
)
from _model_call_record import ADDED, CALLS, LABELS, ODD, ROUND_1_INPUT, write_calls
from _replay_record import ACT_A, PLANNING_TOLD, Model, make_copy, replay_tool
from _replay_record import now as replay_now

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from playwright.async_api import Browser, Locator, Page, Route
    from pydantic_ai.messages import ModelMessage

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

#: Long enough for a poll and a fetch to land.
_SHOWN: Final = 10_000


@pytest.fixture
def record(tmp_path: Path) -> Path:
    """A record written by ADR-0314's store, its model calls' activations beside it."""
    return write_calls(write_record(tmp_path))


@pytest.fixture
def server(record: Path) -> Iterator[Any]:
    """The viewer on loopback over ``record``."""
    with serving(record) as bound:
        yield bound


@contextlib.asynccontextmanager
async def _page(
    browser: Browser, *, width: int = 1280, permissions: list[str] | None = None
) -> AsyncIterator[Page]:
    """A fresh page in its own context, closed when the case is done with it."""
    context = await browser.new_context(
        viewport={"width": width, "height": 860}, permissions=permissions or []
    )
    try:
        yield await context.new_page()
    finally:
        await context.close()


async def _open(page: Page, port: int, activation_id: str) -> None:
    await page.goto(f"http://127.0.0.1:{port}/#{activation_id}")
    await expect(page.locator("#detail-body")).to_be_visible(timeout=_SHOWN)


async def test_entry_text_reaches_the_page_as_text(server: Any, gateway_browser: Browser) -> None:
    async with _page(gateway_browser) as page:
        await _open(page, server.port, "act-1")
        await expect(page.locator("#d-input")).to_have_text(HOSTILE, timeout=_SHOWN)
        await page.locator(".tl-lane .bar.call").first.click()
        await expect(page.locator("#drawer-body pre").nth(1)).to_contain_text("<script>")
        assert await page.locator("img").count() == 0
        assert await page.locator("script").count() == 1
        assert await page.title() == "Activation viewer"


async def test_each_call_shows_its_own_verdict(server: Any, gateway_browser: Browser) -> None:
    async with _page(gateway_browser) as page:
        await _open(page, server.port, "act-1")
        chips = page.locator(".round").first.locator(".chip")
        await expect(chips).to_have_text(
            ["web_search · allowed", "web_search · needs you"], timeout=_SHOWN
        )
        await expect(page.locator(".round").first).to_contain_text("marked")


@pytest.fixture
def scheduled(tmp_path: Path) -> Iterator[Any]:
    """The viewer over a record with an activation whose input shows no messages."""
    directory = write_record(tmp_path)
    content = json.dumps(
        {"input": {"text": "Scheduled instruction", "received_as": "scheduled work"}}
    )
    line = {
        "activation_id": "scheduled",
        "source": "understanding",
        "kind": "given",
        "recorded_at": iso(300_000),
        "body": {"messages": [{"role": "user", "content": content}]},
    }
    (directory / "scheduled.jsonl").write_text(json.dumps(line) + "\n")
    with serving(directory) as bound:
        yield bound


@pytest.mark.parametrize("width", [1280, 390], ids=["desktop", "phone"])
async def test_an_input_with_no_messages_shows_its_text_on_the_input_card(
    scheduled: Any, gateway_browser: Browser, width: int
) -> None:
    async with _page(gateway_browser, width=width) as page:
        await _open(page, scheduled.port, "scheduled")
        card = page.locator("#arrival-card")
        await expect(card).to_be_visible(timeout=_SHOWN)
        await expect(card.locator(".arrival-text")).to_have_text("Scheduled instruction")
        await expect(card.locator("dd").first).to_have_text("scheduled work")
        await expect(card.locator(".arrival-message")).to_have_count(0)


def _offered(page: Page) -> Locator:
    """The drawer's section listing the tools a planning request offered the provider."""
    heading = page.locator("h3", has_text=re.compile(r"^Offered to the provider$"))
    return page.locator("#drawer-body .sec").filter(has=heading)


async def test_a_rounds_drawer_shows_the_tools_its_request_offered(
    server: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser) as page:
        await _open(page, server.port, "act-1")
        await page.locator(".round").first.click()
        offered = _offered(page)
        await expect(offered).to_have_count(1, timeout=_SHOWN)
        # Every name, in the request's order, the reserved one last; and its description
        # alone, with no schema drawn.
        await expect(offered.locator("dd")).to_have_text("web_search, planning_round")
        await expect(offered.locator("h4")).to_have_text(
            ["planning_round · reserved: the round's own tool"]
        )
        await expect(offered.locator("pre")).to_have_text([ROUND_TOOL_DESCRIPTION])


async def test_a_returned_entry_written_before_the_list_was_kept_shows_its_response(
    server: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser) as page:
        await _open(page, server.port, "act-1")
        await page.locator(".round").nth(1).click()
        body = page.locator("#drawer-body")
        await expect(body).to_contain_text("Here is the answer.", timeout=_SHOWN)
        # Authorizing's entry is drawn after planning's, so planning's is done by now.
        await expect(body.locator(".sec h3", has_text="Message")).to_have_count(1)
        await expect(_offered(page)).to_have_count(0)
        await expect(body).not_to_contain_text("did not read as expected")


async def test_offered_tools_of_an_unexpected_shape_lose_their_hint_and_stay_text(
    server: Any, record: Path, gateway_browser: Browser
) -> None:
    def returned(offered: object, ms: int) -> dict[str, object]:
        return {
            "activation_id": "odd",
            "source": "planning",
            "kind": "returned",
            "recorded_at": iso(ms),
            "body": {"response": {"parts": []}, "read_as_round": True, "offered_tools": offered},
        }

    odd = [
        "not a tool",
        {"description": "no name"},
        {"name": 7},
        {"name": "web_search", "description": HOSTILE},
        {"name": "planning_round", "description": HOSTILE},
    ]
    lines = [returned(odd, 0), returned("not a list", 10)]
    (record / "odd.jsonl").write_text("".join(json.dumps(one) + "\n" for one in lines))
    async with _page(gateway_browser) as page:
        await _open(page, server.port, "odd")
        await page.locator("details.card > summary").click()
        rows = page.locator("#entries .entry-row")
        await rows.first.click()
        offered = _offered(page)
        await expect(offered.locator("dd")).to_have_text(
            "web_search, planning_round", timeout=_SHOWN
        )
        await expect(offered.locator("pre")).to_have_text([HOSTILE])
        assert await page.locator("img").count() == 0
        await page.locator("#drawer-close").click()
        await rows.nth(1).click()
        await expect(page.locator("#drawer-body")).to_contain_text("not a list", timeout=_SHOWN)
        await expect(_offered(page)).to_have_count(0)
        await expect(page.locator("#drawer-body")).not_to_contain_text("did not read as expected")


async def test_a_drawer_shows_only_what_the_last_click_asked_for(
    server: Any, gateway_browser: Browser
) -> None:
    requested = asyncio.Event()
    released = asyncio.Event()

    async def hold_act_1(route: Route) -> None:
        if "id=act-1" in route.request.url:
            requested.set()
            await released.wait()
        await route.continue_()

    async with _page(gateway_browser) as page:
        await page.route("**/api/entry?*", hold_act_1)
        await _open(page, server.port, "act-1")
        # Planning's call on act-1, two lines, its first load held.
        await page.locator(".tl-lane").nth(3).locator(".bar.call").first.click()
        await asyncio.wait_for(requested.wait(), timeout=10)
        # Then act-2, and one of its entries, before act-1's load comes back.
        await page.evaluate("location.hash = 'act-2'")
        await expect(page.locator("#d-input")).to_have_text("hello", timeout=_SHOWN)
        await page.locator(".tl-lane .bar.call").first.click()
        headings = page.locator("#drawer-body .sec h3")
        await expect(headings.first).to_have_text("understanding · given", timeout=_SHOWN)
        readable = page.locator("#drawer-read .call-head h2")
        await expect(readable).to_have_text("Understanding", timeout=_SHOWN)
        released.set()
        # Long enough for act-1's two held loads to land, were they drawn.
        await page.wait_for_timeout(500)
        shown = await headings.all_text_contents()
        assert all(not one.startswith("planning") for one in shown), shown
        await expect(page.locator("#drawer-title")).not_to_contain_text("planning")
        await expect(readable).to_have_text("Understanding")


async def test_a_span_of_a_century_draws_a_handful_of_ticks(
    server: Any, record: Path, gateway_browser: Browser
) -> None:
    lines: list[dict[str, object]] = [
        {
            "activation_id": "wide",
            "source": "planning",
            "kind": "given",
            "recorded_at": when,
            "body": {},
        }
        for when in ("1900-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00")
    ]
    (record / "wide.jsonl").write_text("".join(json.dumps(one) + "\n" for one in lines))
    async with _page(gateway_browser) as page:
        await _open(page, server.port, "wide")
        await expect(page.locator(".tl-lane").first).to_be_visible(timeout=_SHOWN)
        assert 2 <= await page.locator(".tick").count() <= 8
        lanes = await page.locator(".tl-lane").count()
        assert await page.locator(".grid").count() <= 8 * lanes


async def test_a_change_of_activation_takes_the_old_details_down_at_once(
    server: Any, gateway_browser: Browser
) -> None:
    released = asyncio.Event()

    async def hold_act_2(route: Route) -> None:
        if "id=act-2" in route.request.url:
            await released.wait()
        await route.continue_()

    async with _page(gateway_browser) as page:
        await page.route("**/api/activation?*", hold_act_2)
        await _open(page, server.port, "act-1")
        await expect(page.locator(".round")).to_have_count(2, timeout=_SHOWN)
        await page.evaluate("location.hash = 'act-2'")
        # While act-2's details are still loading, nothing of act-1's is on show.
        await expect(page.locator("#detail-body")).to_be_hidden()
        await expect(page.locator("#detail-empty")).to_have_text("Loading…")
        released.set()
        await expect(page.locator("#d-input")).to_have_text("hello", timeout=_SHOWN)


async def test_an_activation_that_stops_writing_stops_reading_as_running(
    server: Any, record: Path, gateway_browser: Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = {
        "activation_id": "quiet",
        "source": "planning",
        "kind": "given",
        "recorded_at": iso(0),
        "body": {},
    }
    (record / "quiet.jsonl").write_text(json.dumps(line) + "\n")
    written = at(0).timestamp() * 1000
    clock = [written + 1_000]
    monkeypatch.setattr(viewer, "_now", lambda: clock[0])
    async with _page(gateway_browser) as page:
        await _open(page, server.port, "quiet")
        await expect(page.locator("#d-badges")).to_contain_text("running", timeout=_SHOWN)
        # No byte more is written; only the time passes.
        clock[0] = written + 600_000
        await expect(page.locator("#d-badges")).not_to_contain_text("running", timeout=_SHOWN)
        await expect(page.locator("#d-meta")).to_contain_text("no end recorded")
        title = await page.locator(".tl-lane .bar.call").first.get_attribute("title")
        assert title is not None
        assert "no returned entry was recorded" in title


# --- §3:3: a model call, readable --------------------------------------------------------


async def _open_round(page: Page, port: int, number: int) -> Locator:
    await _open(page, port, CALLS)
    await page.locator(".round").nth(number - 1).click()
    readable = page.locator("#drawer-read")
    await expect(readable.locator(".call-head h2")).to_have_text(
        f"Planning · round {number}", timeout=_SHOWN
    )
    return readable


async def test_a_model_call_opens_readable_with_its_raw_entries_a_tab_away(
    server: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser) as page:
        readable = await _open_round(page, server.port, 1)
        told = readable.locator("#call-told .part")
        await expect(told).to_have_count(3)
        # The record's raw text, as text: the instructions' second paragraph carries it.
        await expect(told.nth(1).locator(".part-text")).to_have_text(LABELS)
        assert await page.locator("img").count() == 0
        keys = readable.locator("#call-given details.part > summary .name")
        await expect(keys).to_have_text(list(ROUND_1_INPUT))
        await expect(readable.locator("#call-tools .part-head .name")).to_have_text(
            ["web_search", "send_email", "planning_round"]
        )
        await expect(readable.locator("#call-did")).to_contain_text("12,345")
        await expect(readable.locator("#call-did .part-head .name")).to_have_text(
            [
                "1 · Thinking (the provider's summary)",
                "2 · Text",
                "3 · Call · web_search",
                "4 · Episode notes",
                "5 · Asks named",
            ]
        )
        await expect(page.locator("#drawer-body")).to_be_hidden()
        await page.locator("#tab-raw").click()
        await expect(readable).to_be_hidden()
        await expect(page.locator("#drawer-body")).to_contain_text("Whole body")
        await page.locator("#tab-read").click()
        await expect(readable).to_be_visible()


async def test_a_parts_copy_control_copies_its_plain_text(
    server: Any, gateway_browser: Browser
) -> None:
    granted = ["clipboard-read", "clipboard-write"]
    async with _page(gateway_browser, permissions=granted) as page:
        readable = await _open_round(page, server.port, 1)
        copy = readable.locator("#call-told .part").nth(1).locator(".copy")
        await copy.click()
        await expect(copy).to_have_text("Copied")
        assert await page.evaluate("navigator.clipboard.readText()") == LABELS
        stories = readable.locator("#call-given details.part").nth(2)
        await stories.locator(".copy").click()
        copied = await page.evaluate("navigator.clipboard.readText()")
        assert copied == '"stories": ' + json.dumps(ROUND_1_INPUT["stories"], indent=1)
        # A copy control inside a part's summary copies without opening the part.
        assert await stories.get_attribute("open") is None


async def test_round_to_round_shows_the_diff_of_each_changed_part(
    server: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser) as page:
        readable = await _open_round(page, server.port, 2)
        changes = readable.locator("#call-changes")
        await expect(changes).to_contain_text("since round 1")
        await expect(changes.locator(".part-head .name")).to_have_text(
            ["instructions", "input · rounds", "input · results", "tool · send_email"]
        )
        await expect(changes.locator(".diff .add").first).to_have_text("+" + ADDED)
        await expect(changes).to_contain_text("Unchanged: input · understood")
        await page.locator("#drawer-close").click()
        await page.locator(".round").first.click()
        await expect(page.locator("#drawer-read #call-changes")).to_contain_text(
            "none before it", timeout=_SHOWN
        )


async def test_understandings_call_says_its_usage_is_not_recorded(
    server: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser) as page:
        await _open(page, server.port, CALLS)
        await page.locator(".tl-lane").nth(2).locator(".bar.call").first.click()
        did = page.locator("#drawer-read #call-did")
        await expect(did).to_contain_text("records no token usage", timeout=_SHOWN)
        await expect(did).to_contain_text("#3090")
        await expect(did).not_to_contain_text("input tokens")
        headings = page.locator("#drawer-read #call-told .part-heading")
        await expect(headings).to_have_text(["What to return", "RULES"])


async def test_a_call_of_other_shapes_says_what_it_cannot_read(
    server: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser) as page:
        await _open(page, server.port, ODD)
        await page.locator("details.card > summary").click()
        rows = page.locator("#entries .entry-row")
        await rows.first.click()
        readable = page.locator("#drawer-read")
        await expect(readable).to_contain_text("no list of messages", timeout=_SHOWN)
        await expect(readable).to_contain_text("no response parts")
        await expect(readable).not_to_contain_text("did not read as expected")
        # A request whose body is no object is still a call, its body shown raw.
        await page.locator("#drawer-close").click()
        await rows.last.click()
        await expect(page.locator("#drawer-body")).to_contain_text("not an object", timeout=_SHOWN)
        await expect(page.locator("#drawer-tabs")).to_be_visible()
        await page.locator("#drawer-close").click()
        await page.evaluate("location.hash = 'act-1'")
        await expect(page.locator("#d-input")).to_have_text(HOSTILE, timeout=_SHOWN)
        # A step is no model call: it opens its raw entry alone.
        await page.locator(".tl-lane").first.locator(".pt, .bar").first.click()
        await expect(page.locator("#drawer-body .sec h3").first).to_be_visible(timeout=_SHOWN)
        await expect(page.locator("#drawer-tabs")).to_be_hidden()
        await expect(page.locator("#drawer-read")).to_be_hidden()


async def test_a_model_call_reads_at_a_phones_width_with_no_sideways_scroll(
    server: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser, width=390) as page:
        await _open(page, server.port, CALLS)
        await page.locator(".round").nth(1).click()
        readable = page.locator("#drawer-read")
        await expect(readable.locator("#call-changes .diff")).to_have_count(2, timeout=_SHOWN)
        box = await page.locator("#drawer").bounding_box()
        assert box is not None
        assert box["width"] <= 390
        wide = await readable.evaluate("node => node.scrollWidth - node.clientWidth")
        assert wide <= 0


# --- ADR-0316 §3:3: every step stays clickable ------------------------------------------


async def test_every_step_is_clickable_beside_the_model_call_inside_it(
    server: Any, gateway_browser: Browser
) -> None:
    """ADR-0333 §1:2: a model call's bar no longer covers its step's (ADR-0316 §3:3)."""
    async with _page(gateway_browser, width=1400) as page:
        await _open(page, server.port, "act-1")
        steps = page.locator(".tl-lane .bar.step")
        await expect(steps).to_have_count(7, timeout=_SHOWN)
        covered = await page.evaluate(
            """() => [...document.querySelectorAll('.tl-lane .bar')].filter((bar) => {
                const r = bar.getBoundingClientRect();
                return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
                  !== bar;
            }).map((bar) => bar.title)"""
        )
        assert covered == []
        round_1 = page.locator(".tl-lane .bar.step", has_text="round 1")
        await round_1.click()
        await expect(page.locator("#drawer-title")).to_contain_text("round 1")
        await expect(page.locator("#drawer-body")).to_contain_text("first_round_due")
        await expect(page.locator("#drawer-tabs")).to_be_hidden()


# --- ADR-0333 §5: the learning lane and the learning overview ---------------------------


@pytest.fixture
def learning(tmp_path: Path) -> Iterator[Any]:
    """The viewer over the activation record and the observer's files beside it."""
    with serving(write_learning(write_record(tmp_path))) as bound:
        yield bound


async def test_the_overview_shows_each_findings_claim_and_outcome_newest_first(
    learning: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser, width=1400) as page:
        await page.goto(f"http://127.0.0.1:{learning.port}/#learning")
        cards = page.locator(".ov-card")
        await expect(cards).to_have_count(4, timeout=_SHOWN)
        await expect(cards.first).to_contain_text(SAID["a-retried"])
        kept = cards.nth(2)
        await expect(kept.locator(".ov-finding .claim")).to_have_text([KEPT_CLAIM, NOT_KEPT_CLAIM])
        await expect(kept.locator(".oc")).to_have_text(["memory created", "nothing kept"])
        await expect(kept).to_contain_text(NOT_KEPT_NOTE)
        await expect(cards.nth(1)).to_contain_text("own record absent")
        await page.locator("#ov-filters button", has_text="Not kept").click()
        await expect(page.locator(".ov-finding .claim")).to_have_text([NOT_KEPT_CLAIM])
        await page.locator("#ov-filters button", has_text="All findings").click()
        await page.locator("#ov-search").fill("vegetarian")
        await expect(page.locator(".ov-finding")).to_have_count(1)


async def test_a_finding_jumps_to_the_exact_prompt_and_reply_behind_it(
    learning: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser, width=1400) as page:
        await page.goto(f"http://127.0.0.1:{learning.port}/#learning")
        row = page.locator(".ov-finding", has_text=NOT_KEPT_CLAIM)
        await row.locator(".jump", has_text="Framing").click()
        readable = page.locator("#drawer-read")
        await expect(readable.locator(".call-head h2")).to_have_text(
            "Observer · framing f2", timeout=_SHOWN
        )
        await expect(readable.locator("#call-did")).to_contain_text(NOT_KEPT_NOTE)
        await page.locator("#tab-raw").click()
        await expect(page.locator("#drawer-body")).to_contain_text("observer · given")
        await page.locator("#drawer-close").click()
        await row.locator(".jump", has_text="Outcome").click()
        await expect(page.locator("#drawer-body")).to_contain_text("What framing decided")
        await expect(page.locator("#drawer-tabs")).to_be_hidden()


async def test_an_activations_page_shows_its_learning_by_attempt(
    learning: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser, width=1400) as page:
        await _open(page, learning.port, "a-retried")
        attempts = page.locator(".ln-attempt")
        await expect(attempts).to_have_count(2, timeout=_SHOWN)
        await expect(attempts.first).to_contain_text("timed out")
        await expect(attempts.nth(1).locator(".ov-finding")).to_contain_text(EVIDENCE_CLAIM)
        # ADR-0346 §6:2: the occasion was placed once, and its placement is a click away.
        await expect(attempts.nth(1).locator(".jump", has_text="Placement 1")).to_be_enabled()
        await expect(page.locator("#timeline-card")).to_be_visible()
        await attempts.nth(1).locator(".ln-track .bar.call").first.click()
        await expect(page.locator("#drawer-read .call-head h2")).to_have_text(
            "Observer · scout", timeout=_SHOWN
        )


async def test_an_activation_whose_own_record_is_gone_shows_its_learning_alone(
    learning: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser, width=1400) as page:
        await _open(page, learning.port, "a-alone")
        await expect(page.locator("#d-own-absent")).to_contain_text(
            "own record is absent", timeout=_SHOWN
        )
        await expect(page.locator("#timeline-card")).to_be_hidden()
        await expect(page.locator("#rounds-card")).to_be_hidden()
        await expect(page.locator("#learning-card .ov-finding")).to_contain_text(ALONE_CLAIM)


async def test_the_overview_reads_at_a_phones_width_with_no_sideways_scroll(
    learning: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser, width=390) as page:
        await page.goto(f"http://127.0.0.1:{learning.port}/#learning")
        await expect(page.locator(".ov-card")).to_have_count(4, timeout=_SHOWN)
        wide = await page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert wide <= 0


# --- ADR-0335 §6:4-§6:5: a replay's results beside the call they replay ------------------


@pytest.fixture
def replayed(tmp_path: Path) -> Iterator[Any]:
    """The viewer over a copy whose planning round a replay sent again, as recorded."""
    copy = make_copy(tmp_path)
    status = asyncio.run(
        replay_tool.replay(
            replay_tool.ReplayOptions(
                copy=copy, model="fake:model", sources=frozenset({"planning"})
            ),
            report=lambda _: None,
            caller=Model().caller(),
            now=replay_now,
        )
    )
    assert status == 0
    with serving(copy / "diagnostics") as bound:
        yield bound


async def test_a_replayed_activation_is_marked_and_its_call_shows_the_result(
    replayed: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser) as page:
        await page.goto(f"http://127.0.0.1:{replayed.port}/")
        marked = page.locator("#list li", has=page.locator(".badge.b-replayed"))
        await expect(marked).to_have_count(1, timeout=_SHOWN)
        await _open(page, replayed.port, ACT_A)
        await page.locator(".round").first.click()
        readable = page.locator("#drawer-read")
        await expect(readable.locator("#call-replays .replay")).to_have_count(1, timeout=_SHOWN)
        await expect(readable.locator(".call-nav button", has_text="Replays")).to_be_visible()
        one = readable.locator("#call-replays .replay")
        await expect(one.locator("h4")).to_have_text("planning · 0123456789ab · recorded")
        await expect(one).to_contain_text("claude-original")
        # The candidate's instruction is one click away (§6:4).
        told = one.locator("details.part")
        await expect(told.locator(".part-text")).to_be_hidden()
        await told.locator("summary").click()
        await expect(told.locator(".part-text")).to_have_text(PLANNING_TOLD)
        await expect(one.locator(".part-head .name", has_text="Text")).to_be_visible()


@pytest.fixture
def sampled(tmp_path: Path) -> Iterator[Any]:
    """The viewer over a copy whose planning round a replay sent twice, each followed up."""
    copy = make_copy(tmp_path)
    status = asyncio.run(
        replay_tool.replay(
            replay_tool.ReplayOptions(
                copy=copy,
                model="fake:model",
                sources=frozenset({"planning"}),
                samples=2,
                follow_up="",
            ),
            report=lambda _: None,
            caller=Model().caller(),
            now=replay_now,
        )
    )
    assert status == 0
    with serving(copy / "diagnostics") as bound:
        yield bound


@pytest.mark.parametrize("width", [1280, 390], ids=["desktop", "phone"])
async def test_a_calls_samples_are_shown_together_under_one_heading(
    sampled: Any, gateway_browser: Browser, width: int
) -> None:
    async with _page(gateway_browser, width=width) as page:
        await _open(page, sampled.port, ACT_A)
        await page.locator(".round").first.click()
        readable = page.locator("#drawer-read")
        one = readable.locator("#call-replays .replay")
        await expect(one).to_have_count(1, timeout=_SHOWN)
        await expect(one.locator("h4")).to_have_text("planning · 0123456789ab · recorded")
        samples = one.locator(".replay-sample")
        await expect(samples).to_have_count(2)
        await expect(samples.locator(":scope > .replay-head h5")).to_have_text(
            ["sample 1 of 2", "sample 2 of 2"]
        )
        await expect(samples.nth(1).locator(".part-head .name", has_text="Text")).to_be_visible()
        # Each sample's follow-up beside it: the answer as text, the question a click away.
        asked = samples.locator(".follow-up")
        await expect(asked).to_have_count(2)
        first = asked.first
        await expect(first.locator("h5")).to_contain_text("follow-up")
        await expect(first.locator(".part-text").first).to_have_text(Model().reply)
        question = first.locator("details.part")
        await expect(question.locator(".part-text")).to_be_hidden()
        await question.locator("summary").click()
        await expect(question.locator(".part-text")).to_be_visible()
        wide = await readable.evaluate("node => node.scrollWidth - node.clientWidth")
        assert wide <= 0


@pytest.fixture
def cut(tmp_path: Path) -> Iterator[Any]:
    """The viewer over a copy whose planning round was replayed and its follow-up failed."""
    copy = make_copy(tmp_path)

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if any(isinstance(one, ModelResponse) for one in messages):
            raise ModelHTTPError(status_code=429, model_name="named")
        return ModelResponse(parts=[TextPart("a replayed reply")])

    status = asyncio.run(
        replay_tool.replay(
            replay_tool.ReplayOptions(
                copy=copy, model="fake:model", sources=frozenset({"planning"}), follow_up=""
            ),
            report=lambda _: None,
            caller=replay_tool.ModelCaller(FunctionModel(answer), timeout=10),
            now=replay_now,
        )
    )
    assert status == 0
    with serving(copy / "diagnostics") as bound:
        yield bound


@pytest.mark.parametrize("width", [1280, 390], ids=["desktop", "phone"])
async def test_a_follow_up_that_failed_is_shown_as_its_failure(
    cut: Any, gateway_browser: Browser, width: int
) -> None:
    async with _page(gateway_browser, width=width) as page:
        await _open(page, cut.port, ACT_A)
        await page.locator(".round").first.click()
        readable = page.locator("#drawer-read")
        asked = readable.locator("#call-replays .replay .follow-up")
        await expect(asked).to_have_count(1, timeout=_SHOWN)
        await expect(asked.locator(".fail")).to_contain_text("failed: ModelRateLimitError")
        await expect(asked.locator(".part-head .name", has_text="Answer")).to_have_count(0)
        wide = await readable.evaluate("node => node.scrollWidth - node.clientWidth")
        assert wide <= 0


async def test_a_replayed_call_reads_at_a_phones_width_with_no_sideways_scroll(
    replayed: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser, width=390) as page:
        await _open(page, replayed.port, ACT_A)
        await page.locator(".round").first.click()
        readable = page.locator("#drawer-read")
        await expect(readable.locator("#call-replays .replay")).to_have_count(1, timeout=_SHOWN)
        await readable.locator("#call-replays details.part summary").click()
        wide = await readable.evaluate("node => node.scrollWidth - node.clientWidth")
        assert wide <= 0


# --- ADR-0337 §8:17: the hub's follow-up, one click from the call it follows ---------------


@pytest.fixture
def followed(tmp_path: Path) -> Iterator[Any]:
    """The viewer over a record the hub's follow-up asker followed up."""
    with serving(write_followed(tmp_path)) as bound:
        yield bound


@pytest.mark.parametrize("width", [1280, 390], ids=["desktop", "phone"])
async def test_a_calls_follow_up_is_shown_beside_it_off_the_timeline(
    followed: Any, gateway_browser: Browser, width: int
) -> None:
    async with _page(gateway_browser, width=width) as page:
        await _open(page, followed.port, FOLLOWED_A)
        await expect(page.locator("#detail-body")).not_to_contain_text(FOLLOW_UP_ANSWER)
        await page.locator(".round").first.click()
        readable = page.locator("#drawer-read")
        asked = readable.locator("#call-follow-ups .follow-up")
        await expect(asked).to_have_count(1, timeout=_SHOWN)
        await expect(readable.locator(".call-nav button", has_text="Follow-up")).to_be_visible()
        await expect(asked.locator("h5")).to_contain_text("follow-up")
        await expect(asked.locator("h5")).to_contain_text("default")
        await expect(asked.locator(".kv")).to_contain_text(FOLLOW_UP_MODEL)
        await expect(asked.locator(".part-text").first).to_have_text(FOLLOW_UP_ANSWER)
        wide = await readable.evaluate("node => node.scrollWidth - node.clientWidth")
        assert wide <= 0


@pytest.mark.parametrize("width", [1280, 390], ids=["desktop", "phone"])
async def test_a_hub_follow_up_that_failed_is_shown_as_its_failure(
    followed: Any, gateway_browser: Browser, width: int
) -> None:
    async with _page(gateway_browser, width=width) as page:
        await _open(page, followed.port, FOLLOWED_F)
        await page.locator(".round").first.click()
        readable = page.locator("#drawer-read")
        asked = readable.locator("#call-follow-ups .follow-up")
        await expect(asked).to_have_count(1, timeout=_SHOWN)
        await expect(asked.locator(".fail")).to_contain_text("failed: ModelRateLimitError")
        await expect(asked.locator(".part-head .name", has_text="Answer")).to_have_count(0)
        wide = await readable.evaluate("node => node.scrollWidth - node.clientWidth")
        assert wide <= 0


async def test_a_follow_up_file_is_not_in_the_list(followed: Any, gateway_browser: Browser) -> None:
    async with _page(gateway_browser) as page:
        await page.goto(f"http://127.0.0.1:{followed.port}/")
        await expect(page.locator("#list li")).to_have_count(2, timeout=_SHOWN)
        await expect(page.locator("#list")).not_to_contain_text("followup")


# --- walk mode: one activation, a step at a time ---------------------------------------


@pytest.fixture
def walked(tmp_path: Path) -> Iterator[Any]:
    """The viewer over the walked activation, beside the record and the observer's files."""
    with serving(write_learning(write_walked(write_record(tmp_path)))) as bound:
        yield bound


async def _sideways(page: Page) -> float:
    return float(
        await page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
    )


@pytest.mark.parametrize("width", [1280, 390], ids=["desktop", "phone"])
async def test_walk_mode_steps_through_an_activation_in_its_own_order(
    walked: Any, gateway_browser: Browser, width: int
) -> None:
    async with _page(gateway_browser, width=width) as page:
        await page.goto(f"http://127.0.0.1:{walked.port}/#{WALKED}/walk/1")
        count = page.locator("#walk-count")
        title = page.locator(".walk-head h2")
        await expect(count).to_have_text(f"step 1 of {len(WALKED_TITLES)}", timeout=_SHOWN)
        await expect(page.locator(".walk-pill")).to_have_count(len(WALKED_TITLES))
        await expect(page.locator("#overview")).to_be_hidden()
        await expect(page.locator("#walk-prev")).to_be_disabled()
        # The input is raw outside text, and reaches the page as text.
        await expect(page.locator("#walk-step")).to_contain_text(HOSTILE)
        assert await page.locator("img").count() == 0
        for number, expected in enumerate(WALKED_TITLES, 1):
            await expect(title).to_have_text(expected)
            await expect(count).to_have_text(f"step {number} of {len(WALKED_TITLES)}")
            assert page.url.endswith(f"#{WALKED}/walk/{number}")
            assert await _sideways(page) <= 0
            if number < len(WALKED_TITLES):
                await page.locator("#walk-next").click()
        await expect(page.locator("#walk-next")).to_be_disabled()
        await expect(title).to_have_text("The end")
        await expect(page.locator("#walk-step")).to_contain_text("Ended: finished")


async def test_the_arrow_keys_move_and_a_step_opens_its_call_readable(
    walked: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser) as page:
        await page.goto(f"http://127.0.0.1:{walked.port}/#{WALKED}/walk/2")
        step = page.locator("#walk-step")
        await expect(step.locator(".walk-head h2")).to_have_text(
            "Recall · first run", timeout=_SHOWN
        )
        await expect(step).to_contain_text(KEPT_FACTS[0])
        await expect(step).to_contain_text("The record does not say why a find was not kept.")
        await page.keyboard.press("ArrowRight")
        await expect(step.locator(".walk-head h2")).to_have_text("Understanding")
        await expect(step).to_contain_text(READING["meaning"])
        # ADR-0353 §14:10: a reply recorded before it, in the shape it was written in.
        await expect(step).to_contain_text("earlier shape")
        await expect(step).to_contain_text("Which date in May")
        await expect(step.locator(".walk-label", has_text="S1")).to_contain_text("Trip to Lisbon")
        await page.keyboard.press("ArrowLeft")
        await expect(step.locator(".walk-head h2")).to_have_text("Recall · first run")
        await page.keyboard.press("ArrowRight")
        await step.locator(".jump", has_text="The call, readable").click()
        await expect(page.locator("#drawer-read .call-head h2")).to_have_text(
            "Understanding", timeout=_SHOWN
        )


#: A reply in ADR-0353 §9:1's shape, written to an activation of its own.
_REPLIED: Final = "replied"
_REPLY: Final = {
    "understanding": "Move the Lisbon booking to the 10th.",
    "cites": ["S1"],
    "unclear": [{"gap": "which flight on the 10th", "readings": ["the morning one"]}],
    "belongs_to": ["S1"],
    "meant_for": [],
    "relayed": False,
}


@pytest.fixture
def replied(tmp_path: Path) -> Iterator[Any]:
    """The viewer over an activation whose understanding replied in the reply's shape."""
    record = write_record(tmp_path)
    given = {
        "messages": [
            {
                "role": "user",
                "content": json.dumps({"stories": [{"label": "S1", "summary": "Trip to Lisbon"}]}),
            }
        ]
    }
    rows = [
        {"source": "understanding", "kind": "given", "recorded_at": iso(20), "body": given},
        {
            "source": "understanding",
            "kind": "returned",
            "recorded_at": iso(30),
            "body": {"reply": json.dumps(_REPLY)},
        },
    ]
    (record / f"{_REPLIED}.jsonl").write_text(
        "".join(json.dumps({"activation_id": _REPLIED, **one}) + "\n" for one in rows)
    )
    with serving(record) as bound:
        yield bound


async def test_a_reply_in_its_six_keys_walks_in_that_shape(
    replied: Any, gateway_browser: Browser
) -> None:
    """ADR-0353 §14:10: the reply's shape, its unclear point with its reading, its labels."""
    async with _page(gateway_browser) as page:
        await page.goto(f"http://127.0.0.1:{replied.port}/#{_REPLIED}/walk/2")
        step = page.locator("#walk-step")
        await expect(step.locator(".walk-head h2")).to_have_text("Understanding", timeout=_SHOWN)
        await expect(step).to_contain_text(str(_REPLY["understanding"]))
        await expect(step).to_contain_text("which flight on the 10th")
        await expect(step).to_contain_text("reading: the morning one")
        await expect(step.locator("h3", has_text="Belongs to")).to_be_visible()
        await expect(step.locator(".walk-label", has_text="S1").first).to_contain_text(
            "Trip to Lisbon"
        )
        await expect(step).not_to_contain_text("earlier shape")


async def test_a_deep_link_opens_its_step_and_the_overview_is_a_click_away(
    walked: Any, gateway_browser: Browser
) -> None:
    async with _page(gateway_browser) as page:
        await page.goto(f"http://127.0.0.1:{walked.port}/#{WALKED}/walk/9")
        step = page.locator("#walk-step")
        await expect(step.locator(".walk-head h2")).to_have_text(
            "Planning · round 2", timeout=_SHOWN
        )
        await expect(step).to_contain_text("What came back from round 1")
        await expect(step).to_contain_text(SEARCH_RESULT)
        await expect(step).to_contain_text(ROUND_2_MESSAGE)
        await page.locator("#mode-overview").click()
        await expect(page.locator("#timeline-card")).to_be_visible()
        await expect(page.locator("#walk-card")).to_be_hidden()
        assert page.url.endswith(f"#{WALKED}")
        await page.locator("#mode-walk").click()
        await expect(step.locator(".walk-head h2")).to_have_text("Input")
        await page.goto(f"http://127.0.0.1:{walked.port}/#a-retried/walk/99")
        await expect(step.locator(".walk-head h2")).to_have_text(
            "Learning · attempt 2", timeout=_SHOWN
        )
        await expect(step.locator(".ov-finding")).to_contain_text(EVIDENCE_CLAIM)


async def test_a_change_of_activation_never_shows_the_last_ones_walk(
    walked: Any, gateway_browser: Browser
) -> None:
    released = asyncio.Event()

    async def hold_act_1(route: Route) -> None:
        if "id=act-1" in route.request.url:
            await released.wait()
        await route.continue_()

    async with _page(gateway_browser) as page:
        await page.route("**/api/walk?*", hold_act_1)
        await page.goto(f"http://127.0.0.1:{walked.port}/#{WALKED}/walk/3")
        step = page.locator("#walk-step")
        await expect(step.locator(".walk-head h2")).to_have_text("Understanding", timeout=_SHOWN)
        await page.evaluate("location.hash = 'act-1/walk/4'")
        # act-1's details load while its walk is held: nothing of the walked one's shows.
        await expect(page.locator("#d-input")).to_have_text(HOSTILE, timeout=_SHOWN)
        await expect(step).to_have_text("Loading…")
        await expect(page.locator(".walk-pill")).to_have_count(0)
        released.set()
        await expect(step.locator(".walk-head h2")).to_have_text(
            "Authorizing · round 1", timeout=_SHOWN
        )
        await step.locator(".jump", has_text="Its entry, whole").click()
        await expect(page.locator("#drawer-body")).to_contain_text("asks first")
