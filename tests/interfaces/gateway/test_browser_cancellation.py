"""The cancellation surfaces as a browser really renders them (ADR-0261 §6, §7).

§13's **L3** puts the browser in the same lane as the terminal: "the fixed statements §6
and §7 name, on the CLI's abandon and goals surfaces and **on the reply**", and ADR-0262
§11's parity point is why one lane owes both — "a member rendered on one and not the other
is the parity failure M4 recorded".

**And ADR-0216 §1 is why these cases exist beside ``test_bundle.py``'s text-layer pins**: a
substring assertion over ``app.js`` is as green over a renderer nothing calls as over one
that works. What is asserted here is what Chromium put on the screen.

**Both viewports**, because a statement below the fold is a statement the owner does not
read. ``browser_drive`` holds ADR-0233 §15's two figures and this module drives both.

**The engine is the canonical fake, scripted.** No sequence of page acts meets a
``ClaimRefused`` — a withheld drive needs a ``PlanStore`` to refuse a ``→ RUNNING`` claim
on a liveness conjunct, which that double never takes — so the seven reach a consumer's
test through ``FakeAssistantEngine.drive_withheld`` and through the outcome each case
states, which is ``test_browser_attempt_report.py``'s own arrangement one vocabulary over.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import TYPE_CHECKING, Final

import pytest
from browser_drive import DESKTOP, PHONE, driving
from playwright.async_api import expect
from rich.console import Console
from test_browser_answers import _stop_substituting, _substitute

from ai_assistant.core.types import (
    DriveWithheld,
    GoalAbandonment,
    GoalStatus,
    GoalSummary,
    TurnOutcome,
)
from ai_assistant.interfaces import cli

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, Dialog, ViewportSize

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

_QUESTION: Final = "book the flight"

GOAL_ID: Final = "goal-qqzz-4417"
OUTCOME: Final = "Book the last flight out on the Friday."
ENGAGED: Final = datetime(2026, 1, 1, 11, tzinfo=UTC)

#: Both figures ADR-0233 §15 obliges, named once so every case runs at both.
_VIEWPORTS: Final = [DESKTOP, PHONE]


def _terminal(member: DriveWithheld) -> str:
    """What the **terminal** renders for one member, flattened.

    **Read off the other surface rather than restated here**, and that is the arm rather
    than a convenience. ADR-0262 §11 puts both surfaces in one lane "since a member
    rendered on one and not the other is the parity failure M4 recorded", and this lane
    writes the two prose sets byte for byte identically — so driving the browser against
    the terminal's own words makes every case below a cross-surface assertion: a sentence
    edited in ``app.js`` and not in ``cli.py`` fails here, in Chromium, rather than only in
    ``test_cli_cancellation.py``'s text-layer parity arm.

    A third copy of the seven sentences, written out in this module, would have been green
    against two surfaces that had drifted together.
    """
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=200)
    original = cli.console
    cli.console = console
    try:
        cli._render_drive_withheld(member)
    finally:
        cli.console = original
    return " ".join(buffer.getvalue().replace("↳", " ").split())


#: The seven §7 closes the vocabulary at, each as the terminal renders it.
_STATEMENTS: Final[dict[DriveWithheld, str]] = {
    member: _terminal(member) for member in DriveWithheld
}


def _summary(*, effect_in_flight: bool, status: GoalStatus = GoalStatus.ACTIVE) -> GoalSummary:
    """One listed goal, with ADR-0261 §6's field set either way."""
    return GoalSummary(
        id=GOAL_ID,
        outcome=OUTCOME,
        status=status,
        paused=False,
        effect_in_flight=effect_in_flight,
        last_engaged_at=ENGAGED,
    )


async def _composed(drive: Drive) -> TurnOutcome:
    """One real composed turn, from the fake's own ``converse``."""
    outcome = await drive.engine.converse(_QUESTION, timeout=timedelta(seconds=5))
    assert outcome.turn is not None
    return outcome


async def _ask(drive: Drive, outcome: TurnOutcome) -> str:
    """Run one turn whose outcome is scripted and return what the panel says.

    **The wait is on this turn's own reply reaching the panel, not on the panel being
    visible** (ADR-0216 §7: a condition the page exposes, rather than a sleep). A drive
    that has already answered once leaves ``#answer`` shown, so a second ask that waited
    only on the selector would read the *previous* turn's text and assert over it — green
    or red for the wrong reason. Each caller therefore gives its turn a distinguishable
    reply and this waits for it.
    """
    assert outcome.reply is not None
    drive.engine.turn_outcome = outcome
    await drive.page.fill("#utterance", _QUESTION)
    await drive.page.click("#ask-button")
    await drive.page.wait_for_selector("#answer:not([hidden])")
    await drive.page.wait_for_function(
        "expected => document.getElementById('answer-body').textContent.includes(expected)",
        arg=outcome.reply,
    )
    return await drive.answer()


async def _open_goals(drive: Drive) -> None:
    """Press the control the owner presses, and wait for the panel it opens."""
    await drive.page.click("#goals-button")
    await drive.page.wait_for_selector("#goals:not([hidden])")


# --- ADR-0261 §7: the seven statements, beside the reply ---------------------


@pytest.mark.parametrize("member", list(DriveWithheld))
@pytest.mark.parametrize("viewport", _VIEWPORTS, ids=["desktop", "phone"])
async def test_every_member_reaches_the_owner_as_a_sentence(
    gateway_browser: Browser, tmp_path: Path, member: DriveWithheld, viewport: ViewportSize
) -> None:
    """ADR-0261 §7's seven, on the screen, at both widths.

    Parametrised over the vocabulary itself, so an **eighth** ``DriveWithheld`` arriving
    with the ADR that decides it fails here rather than rendering nothing in front of an
    owner — the #1113 rule, driven rather than read.

    **Beside the reply and never in place of it**: the reply the turn composed is still on
    the screen above the statement, which is the half a renderer that replaced the panel
    would pass a substring assertion on.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        base = await _composed(drive)
        said = await _ask(
            drive,
            base.model_copy(
                update={"reply": "Here is where that got to.", "drive_withheld": member}
            ),
        )

        assert _STATEMENTS[member] in said, member
        assert "Here is where that got to." in said
        assert said.index("Here is where that got to.") < said.index(_STATEMENTS[member])


@pytest.mark.parametrize("viewport", _VIEWPORTS, ids=["desktop", "phone"])
async def test_a_turn_whose_drive_was_not_withheld_says_nothing_about_one(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """ADR-0261 §7: the member is non-``None`` "exactly on a turn that *returned* after a
    ``ClaimRefused`` whose post-refusal read established one of the seven states".

    Its absence is every turn that dispatched, every turn that stopped on one of ADR-0255
    §2's five, every turn that drove nothing at all, and ADR-0198 §1's restatement — and a
    refusal that **propagates** returns no outcome at all, so it reaches this page as an
    error rather than as a silent statement. A driver **skip** gains no carrier here
    either. So the page says nothing about a withheld drive at all.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        base = await _composed(drive)
        said = await _ask(drive, base.model_copy(update={"reply": "Booked, near enough."}))

        assert "Booked, near enough." in said
        for statement in _STATEMENTS.values():
            assert statement not in said


@pytest.mark.parametrize("member", list(DriveWithheld))
async def test_no_action_was_needed_is_not_shown_beside_a_withheld_drive(
    gateway_browser: Browser, tmp_path: Path, member: DriveWithheld
) -> None:
    """The contradiction on one screen, driven rather than read.

    "No action was needed." above "That goal was cancelled, and this turn did nothing
    further for it." says both that nothing was owed and that a step this turn was driving
    was not claimed.

    **Over all seven, because the guard is on the member's presence.** ``OutboundReach``
    and ``AttemptOutcome`` each have a member for having attempted nothing and
    ``DriveWithheld`` has none, so unlike the attempt report there is no partition here —
    which is exactly the shape a guard copied from the wrong neighbour would get wrong.

    **And the shape is one this page is handed rather than one a conforming hub
    composes**: §7's refusal comes from a claim on a step of the plan the outcome carries,
    so a conforming turn has a non-empty plan and the notice is already suppressed. The
    outcome crosses a frame, which is what the guard is for.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        base = await _composed(drive)
        assert base.turn is not None
        assert not base.turn.plan.steps, "the arm is about a turn the page is handed"
        said = await _ask(
            drive,
            base.model_copy(
                update={"reply": "Here is where that got to.", "drive_withheld": member}
            ),
        )

        assert "No action was needed." not in said, member
        assert _STATEMENTS[member] in said, member


async def test_no_action_was_needed_is_still_shown_where_no_drive_was_withheld(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The control the arm above needs to mean anything: a guard that suppressed the
    notice unconditionally would pass every case there and would have taken a true line
    off every ordinary turn."""
    async with driving(gateway_browser, tmp_path) as drive:
        base = await _composed(drive)
        said = await _ask(drive, base.model_copy(update={"reply": "Booked, near enough."}))

        assert "No action was needed." in said


async def test_only_the_two_statements_the_adr_fixes_name_a_command(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0261 §7's fixed half, driven.

    §7 names ``assistant goals`` in ``GOAL_BLOCKED``'s statement and in
    ``ATTEMPT_PAUSED``'s, each being a statement about a goal that is **still open** where
    what the owner needs is where to read what it is waiting on. The other five name
    nothing. Naming the terminal's command from this page is this surface's own ratified
    practice (``UNREADABLE_RULINGS``): inventing a control here would be minting a route no
    ratified decision gives this surface.
    """
    names_goals = {DriveWithheld.GOAL_BLOCKED, DriveWithheld.ATTEMPT_PAUSED}
    async with driving(gateway_browser, tmp_path) as drive:
        base = await _composed(drive)
        for index, member in enumerate(DriveWithheld):
            said = await _ask(
                drive,
                base.model_copy(
                    update={"reply": f"Answer number {index}.", "drive_withheld": member}
                ),
            )
            assert ("assistant goals" in said) is (member in names_goals), member
            for barred in ("assistant resume", "assistant decisions", "assistant abandon-goal"):
                assert barred not in said, (member, barred)


async def test_the_statement_reaches_the_owner_through_the_fakes_own_lever(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The whole path, from the member the engine carries to the pixels.

    Every case above states the member on an outcome it hands the fake; this one sets
    :attr:`~ai_assistant.testing.FakeAssistantEngine.drive_withheld` and lets the double
    carry it onto the outcome its own ``converse`` composes — which is the arm that shows
    the member survives the engine, the wire and ``_outcome_view`` rather than only the
    renderer.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.drive_withheld = DriveWithheld.UNDERSTANDING_CHANGED
        await drive.page.fill("#utterance", _QUESTION)
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")
        await drive.page.wait_for_function(
            "expected => document.getElementById('answer-body').textContent.includes(expected)",
            arg=_STATEMENTS[DriveWithheld.UNDERSTANDING_CHANGED],
        )


async def test_a_value_outside_the_seven_is_said_rather_than_shown_raw(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A value that is not one of §7's seven is reported as one the page has no words for.

    §7 closes the vocabulary at seven, so no conforming hub sends an eighth — but a
    browser can be sent any string at all, and ADR-0168 §6 makes what the page does with
    one this surface's decision rather than the hub's.

    **Not a bare identifier and not silence**, which is ``ATTEMPT_REPORT_UNREADABLE``'s
    ratified position one vocabulary over, and **not an eighth fixed statement**: minting
    one for a member §7 does not name would be this surface deciding a vocabulary.

    **And the notice is *not* suppressed here**, which is the arm that decides how the
    guard is written. The unreadable sentence "asserts nothing the page has not been
    told", so there is nothing for "No action was needed." to contradict — and the same
    branch is what an **absent** member reaches, which is what a hub at another version
    sends. A guard testing ``=== null`` would suppress a true notice on both; the
    membership test is why it does not, and the case that found it is
    ``test_a_member_outside_the_six_is_said_rather_than_shown_raw`` one vocabulary over.

    Driven by substituting the response body, because a value outside the enumeration is
    one no conforming gateway sends and ``_outcome_view`` cannot be made to send it. The
    stream is switched off first so that the substituted path is the one the page asks.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.page.uncheck("#stream-answer")
        await _substitute(
            drive,
            path="/ask",
            body=(
                '{"outcome": {"conversation_id": "c-1", "capture_degraded": false, '
                '"memory_degraded": false, "reply": "Right.", "reply_degraded": false, '
                '"rationale": null, "steps": [], "step": null, "routed": null, '
                '"read_confirmation": null, "read_answer": null, "goal_engagement": null, '
                '"clarification": null, "reference": null, "disambiguation": null, '
                '"forecast_not_read": null, "attempt_report": null, '
                '"drive_withheld": "a_later_member", "authorizations": []}}'
            ),
        )
        await drive.page.fill("#utterance", _QUESTION)
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")
        said = await drive.answer()
        await _stop_substituting(drive)

        assert "no words for" in said
        assert "a_later_member" not in said
        for statement in _STATEMENTS.values():
            assert statement not in said
        assert "No action was needed." in said


async def test_an_outcome_carrying_no_such_member_at_all_still_shows_the_true_notice(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The **absent** member, which is the shape a hub at an earlier version sends.

    ``undefined`` is not ``null`` in JavaScript, and a guard written as ``=== null``
    treats an absent key as a *present* member — suppressing "No action was needed." on a
    turn that genuinely needed no action, with no statement on the screen to replace it.
    That is a true line silently removed, which is the opposite direction from the
    contradiction the guard exists to prevent, and it is why the term is a membership
    test.

    ``renderDriveWithheld`` already treats the two alike (§7's silence); this pins that the
    guard does too, over a body carrying no ``drive_withheld`` key at all.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        await drive.page.uncheck("#stream-answer")
        await _substitute(
            drive,
            path="/ask",
            body=(
                '{"outcome": {"conversation_id": "c-1", "capture_degraded": false, '
                '"memory_degraded": false, "reply": "Right.", "reply_degraded": false, '
                '"rationale": null, "steps": [], "step": null, "routed": null, '
                '"read_confirmation": null, "read_answer": null, "goal_engagement": null, '
                '"clarification": null, "reference": null, "disambiguation": null, '
                '"forecast_not_read": null, "attempt_report": null, "authorizations": []}}'
            ),
        )
        await drive.page.fill("#utterance", _QUESTION)
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")
        said = await drive.answer()
        await _stop_substituting(drive)

        assert "No action was needed." in said
        assert "no words for" not in said
        for statement in _STATEMENTS.values():
            assert statement not in said


# --- ADR-0261 §6: the listing row --------------------------------------------


@pytest.mark.parametrize("viewport", _VIEWPORTS, ids=["desktop", "phone"])
async def test_a_goal_with_an_outstanding_action_says_so_in_the_listing(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """ADR-0261 §6's row statement, on the screen, at both widths.

    "For a listing row whose ``effect_in_flight`` is true, that an action of this goal **is
    outstanding — claimed, possibly sent, outcome unknown**." The listing carries it
    because the act's answer is heard once: a user who comes back tomorrow asking "did that
    booking go through?" reads this listing, "and a listing showing an ``abandoned`` goal
    with nothing beside it would have lost the fact R78 requires".

    **Driven at both widths**, because a sentence that renders correctly and scrolls off a
    phone is one the owner does not have.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.engine.goal_summaries = [_summary(effect_in_flight=True)]

        await _open_goals(drive)

        listed = drive.page.locator("#goal-list")
        await expect(listed).to_contain_text(cli._EFFECT_IN_FLIGHT)
        await expect(listed).to_contain_text(OUTCOME)


async def test_a_goal_with_nothing_outstanding_says_nothing_about_one(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The control: **false** is the ordinary state and the row is silent there.

    §6 makes the cleared field "deliberately indistinguishable from a goal that claimed
    nothing" — what the effect *did* is held by the step's own status, and naming that
    disposition to the user "is #2397's and not this field's" — so a row rendering anything
    at all on a false field would be minting a vocabulary this decision does not mint.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary(effect_in_flight=False)]

        await _open_goals(drive)

        listed = drive.page.locator("#goal-list")
        await expect(listed).to_contain_text(OUTCOME)
        assert cli._EFFECT_IN_FLIGHT not in (await listed.inner_text())


async def test_the_abandonment_reports_the_claimed_action_by_its_facts(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0261 §14 arm 10: "**the rendering is asserted by its facts rather than its
    prose**".

    §6 fixes the two facts the abandonment surface owes for
    ``ABANDONED_EFFECT_IN_FLIGHT``: that an action **was claimed and may have been sent**,
    and where that goal's state and any outcome since established is read. On this surface
    that second half is the listing itself rather than the terminal's command, which §6's
    own last clause admits — "the exact wording is the lane's; what is fixed is which fact
    each names" — the statement being rendered directly above the listing it would
    otherwise be pointing at.

    **And it asserts no outcome**: not that the action did not happen, not that it did, and
    not that anything the owner does will withdraw it.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary(effect_in_flight=True)]
        drive.engine.abandonment = GoalAbandonment.ABANDONED_EFFECT_IN_FLIGHT

        # ``Dialog.accept`` is a coroutine, so the handler cannot be a lambda: a page
        # event listener is called synchronously and a coroutine nobody awaits leaves
        # the dialog open, which blocks the renderer until the click times out.
        # ``test_browser_goals._answering`` holds the same shape, and the task is held
        # in this closure so it is not garbage-collected mid-flight.
        loop = asyncio.get_running_loop()
        running: list[asyncio.Task[None]] = []

        async def _accept(dialog: Dialog) -> None:
            await dialog.accept()

        drive.page.on("dialog", lambda dialog: running.append(loop.create_task(_accept(dialog))))
        await _open_goals(drive)
        await drive.page.get_by_role("button", name="Give this up").click()
        await drive.page.wait_for_function(
            "expected => document.getElementById('goals').textContent.includes(expected)",
            arg="may have been sent",
        )

        said = await drive.page.locator("#goals").inner_text()
        assert "claimed" in said
        for barred in ("did not happen", "will be undone", "withdraw"):
            assert barred not in said.lower(), barred
