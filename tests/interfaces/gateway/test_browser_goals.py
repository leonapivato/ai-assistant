"""The goal surface as a browser really renders it (ADR-0250 §15, ADR-0216 §1).

§15 places this surface by name — "the command line and the browser both implement this
decision. Each renders a raised clarification in the exchange that raised it, lists
outstanding goals and their questions, carries an answer with its reference, and offers
the withdrawal and the abandonment acts" — and ADR-0216 §1 is why the cases are here and
not only in ``test_bundle.py``: a substring assertion is as green over a listener that
throws the first time a browser reaches it as over one that works.

**Both viewports, because a control that is off the screen is a control the owner does
not have.** ADR-0233 §15 obliges the browser lane to drive its floor "at a desktop width
and at a phone-class viewport", and ``browser_drive`` holds both figures.

**The engine is the canonical fake, seeded.** A real goal listing needs a plan store, an
association and a planner; what this surface owes is that what the engine answers reaches
the screen and that what the owner presses reaches the engine — which is stated over
inputs and observable outcomes exactly as the rest of this layer is.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final
from urllib.parse import urlparse

import pytest
from browser_drive import DESKTOP, PHONE, driving
from playwright.async_api import expect
from test_browser_conversations import _holding

from ai_assistant.core.types import (
    Clarification,
    ClarificationWithdrawal,
    EngagementDisposition,
    GoalAbandonment,
    GoalDisambiguation,
    GoalEngagement,
    GoalStatus,
    GoalSummary,
    ReferenceOutcome,
    TurnOutcome,
    TurnReference,
)

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, Dialog, Route, ViewportSize

pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]

GOAL_ID: Final = "goal-zzqq-7741"
OTHER_ID: Final = "goal-wwvv-3320"
QUESTION_ID: Final = "question-xxpp-9930"
OUTCOME: Final = "Book the usual campsite for the last weekend of August."
QUESTION: Final = "Which campsite do you mean — Ericeira or Melides?"
DEADLINE: Final = datetime(2026, 1, 8, 11, tzinfo=UTC)
ENGAGED: Final = datetime(2026, 1, 1, 11, tzinfo=UTC)

#: Both figures ADR-0233 §15 obliges, named once so every case runs at both.
_VIEWPORTS: Final = [DESKTOP, PHONE]


def _clarification() -> Clarification:
    return Clarification(question_id=QUESTION_ID, text=QUESTION, expires_at=DEADLINE)


def _summary(*, paused: bool = True, asking: bool = True) -> GoalSummary:
    return GoalSummary(
        id=GOAL_ID,
        outcome=OUTCOME,
        status=GoalStatus.ACTIVE,
        paused=paused,
        last_engaged_at=ENGAGED,
        clarification=_clarification() if asking else None,
    )


def _answering(drive: Drive, *, accept: bool) -> asyncio.Future[str]:
    """Answer the next ``window.confirm`` and hand the case what it said.

    ``Dialog.accept`` is a coroutine, so the handler cannot be a lambda: a page event
    listener is called synchronously and a coroutine nobody awaits leaves the dialog
    open, which blocks the renderer until the click times out.
    ``test_browser_conversations`` holds the same shape one ceremony over, and for the
    same reason — **the future is the case's synchronisation** (ADR-0216 §7): it
    resolves when the browser has been told what the owner chose, which is a condition
    the page reached rather than a duration the test guessed.

    Args:
        drive: The gateway, engine and page under test.
        accept: Whether the owner consents to giving the goal up.

    Returns:
        The message the ceremony put on screen, once it has been answered.
    """
    loop = asyncio.get_running_loop()
    answered: asyncio.Future[str] = loop.create_future()
    # Held so the tasks are not garbage-collected mid-flight, and held in this closure
    # rather than in a module global, so two cases cannot share it.
    running: list[asyncio.Task[None]] = []

    async def answer(dialog: Dialog) -> None:
        message = dialog.message
        await (dialog.accept() if accept else dialog.dismiss())
        if not answered.done():
            answered.set_result(message)

    drive.page.on("dialog", lambda dialog: running.append(loop.create_task(answer(dialog))))
    return answered


async def _open_goals(drive: Drive) -> None:
    """Press the control the owner presses, and wait for the panel it opens."""
    await drive.page.click("#goals-button")
    await drive.page.wait_for_selector("#goals:not([hidden])")


@pytest.mark.parametrize("viewport", _VIEWPORTS)
async def test_the_listing_puts_what_is_outstanding_on_the_screen(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """ADR-0250 §15's listing, and the surface #2286 says did not exist.

    #2286 (M31's QA) found the goal continuity record readable from no surface at all.
    This is that surface, driven: the outcome statement, the state, whether it is waiting
    on the owner, when it was last taken up, and the open question with its deadline.

    Driven at both widths, because a listing that renders correctly and scrolls off a
    phone is one the owner does not have.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.engine.goal_summaries = [_summary()]

        await _open_goals(drive)

        listed = drive.page.locator("#goal-list")
        await expect(listed).to_contain_text(OUTCOME)
        await expect(listed).to_contain_text("State: open — waiting on you")
        await expect(listed).to_contain_text(QUESTION)
        await expect(listed).to_contain_text("Answerable until")
        # The two ids, on screen because the acts take them (ADR-0250 §15, §13).
        await expect(listed).to_contain_text(GOAL_ID)
        await expect(listed).to_contain_text(QUESTION_ID)


@pytest.mark.parametrize("viewport", _VIEWPORTS)
async def test_every_control_a_row_offers_is_reachable_at_both_widths(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """The four acts a paused goal's row offers, each visible and each pressable.

    ADR-0250 §15 names what the surface owes and §12 pairs the withdrawal with the
    answer — "a user told only how to say yes or no has not been offered the third thing
    they can do", ADR-0244 §13's clause one record kind over. A control rendered off the
    screen at 390px is one the owner does not have, which is what the phone run is for.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.engine.goal_summaries = [_summary()]

        await _open_goals(drive)

        for label in ("Answer this", "Take the question back", "Take this up here", "Give this up"):
            await expect(drive.page.get_by_role("button", name=label)).to_be_visible()


async def test_a_goal_with_no_open_question_offers_neither_question_act(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A control for a question that does not exist is one that could never work.

    ``GoalSummary.clarification`` is ``None`` where no question stands (ADR-0250 §15), so
    the answer and the withdrawal have nothing to name — and the resume and the
    abandonment are still there, because they are about the goal.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary(paused=False, asking=False)]

        await _open_goals(drive)

        await expect(drive.page.get_by_role("button", name="Answer this")).to_have_count(0)
        await expect(drive.page.get_by_role("button", name="Take the question back")).to_have_count(
            0
        )
        await expect(drive.page.get_by_role("button", name="Take this up here")).to_be_visible()
        # `paused` is the engine's and this page renders the boolean it was handed
        # (ADR-0250 §15): an ACTIVE goal the engine says is not paused is not "waiting".
        await expect(drive.page.locator("#goal-list")).not_to_contain_text("waiting on you")


async def test_a_closed_goal_is_offered_no_abandonment(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0250 §12 answers ``ALREADY_CLOSED`` there, so the control would do nothing.

    Decided on the status the engine sent rather than on a rule derived here — pressing
    it on a row that closed since is still answered honestly, because the member comes
    back from the engine and is rendered.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [
            _summary(paused=False, asking=False).model_copy(update={"status": GoalStatus.ABANDONED})
        ]

        await _open_goals(drive)

        await expect(drive.page.locator("#goal-list")).to_contain_text("State: given up")
        await expect(drive.page.get_by_role("button", name="Give this up")).to_have_count(0)


@pytest.mark.parametrize("viewport", _VIEWPORTS)
async def test_a_blocked_goal_is_open_and_keeps_the_abandonment(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """ADR-0250 §1 names **two** open statuses, and this page offered the control on one.

    §1: *"A goal is **open** where its ``GoalStatus`` is ``ACTIVE`` or ``BLOCKED``, and
    **closed** where it is ``ACHIEVED`` or ``ABANDONED`` … **``BLOCKED`` is open**"* —
    ADR-0249 §4 defining it as *"this objective cannot **currently** be achieved"*. The
    engine's ``abandon_goal`` tests ``orchestration.goals.is_open`` over
    ``{ACTIVE, BLOCKED}`` and abandons such a goal, so hiding the control here took the
    one act that ends a goal away from the row that most wants it. Adversarial review,
    round 8, ``blocker``.

    Driven at both of ADR-0233 §15's figures, because a control restored at one width
    and lost to the other is still a control the owner cannot reach.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.engine.goal_summaries = [
            _summary(paused=False, asking=False).model_copy(update={"status": GoalStatus.BLOCKED})
        ]

        await _open_goals(drive)

        await expect(drive.page.locator("#goal-list")).to_contain_text("State: blocked")
        await expect(drive.page.get_by_role("button", name="Give this up")).to_be_visible()
        await expect(drive.page.get_by_role("button", name="Take this up here")).to_be_visible()


async def test_an_empty_listing_says_so(gateway_browser: Browser, tmp_path: Path) -> None:
    """Nothing outstanding is the ordinary case, and a blank panel answers nothing."""
    async with driving(gateway_browser, tmp_path) as drive:
        await _open_goals(drive)

        await expect(drive.page.locator("#goal-list")).to_contain_text("Nothing outstanding")


# --- the two acts (ADR-0250 §12) ---------------------------------------------


@pytest.mark.parametrize("member", list(ClarificationWithdrawal))
async def test_every_withdrawal_member_reaches_the_owner_as_a_sentence(
    gateway_browser: Browser, tmp_path: Path, member: ClarificationWithdrawal
) -> None:
    """ADR-0250 §15's non-degradation clause, driven rather than read.

    "A surface that renders no statement for a … ``ClarificationWithdrawal`` member it
    was given has not implemented this section — it is not permissibly degraded." The
    statement lands in the panel's own account node rather than in its fault slot,
    because neither member is the act failing: both are something the hub established.

    **And the statement carries every clause §12 gives it, not merely some sentence.**
    ``WITHDRAWN`` says what the act *buys* — "withdrawing removes the question and not
    the pause … **What the act buys is the freedom to ask again**" — and
    ``NOTHING_TO_WITHDRAW`` says that whatever settled the question stands, which is the
    half that stops a no-op reading as damage. Both were on the command line's twin and
    missing here, which a "some sentence appeared" assertion could not see. Round 9's
    parity sweep.
    """
    owed = {
        ClarificationWithdrawal.WITHDRAWN: "ask a better question about it",
        ClarificationWithdrawal.NOTHING_TO_WITHDRAW: "Whatever settled it stands unchanged",
    }
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary()]
        drive.engine.withdrawal = member

        await _open_goals(drive)
        await drive.page.click("text=Take the question back")

        said = drive.page.locator("#goal-said")
        await expect(said).to_be_visible()
        await expect(said).not_to_contain_text(QUESTION_ID)
        await expect(said).to_contain_text(owed[member])
        assert drive.engine.calls[-2:][0] == (
            "withdraw_clarification",
            {"question_id": QUESTION_ID},
        )


async def test_an_abandonment_is_confirmed_from_the_row_and_then_relayed(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """Show-then-confirm at the unit the owner thinks in (ADR-0073 §5).

    What the prompt shows is the goal's outcome statement — which is what a goal *is* to
    a reader — and it says in terms what the act does not do, every clause of it ADR-0250
    §12's: the goal leaves what is considered, its open question is withdrawn, and
    nothing already done is undone.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary()]
        drive.engine.abandonment = GoalAbandonment.ABANDONED
        answered = _answering(drive, accept=True)

        await _open_goals(drive)
        await drive.page.click("text=Give this up")
        shown = await answered
        await expect(drive.page.locator("#goal-said")).to_be_visible()

        assert OUTCOME in shown
        assert "Nothing already done for it is undone" in shown
        assert ("abandon_goal", {"goal_id": GOAL_ID}) in drive.engine.calls


async def test_a_refused_confirmation_sends_nothing(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A ceremony the owner declines is a ceremony that performed nothing."""
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary()]
        answered = _answering(drive, accept=False)

        await _open_goals(drive)
        await drive.page.click("text=Give this up")
        await answered

        assert [call for call in drive.engine.calls if call[0] == "abandon_goal"] == []


# --- the reference, attached to the ordinary composer (ADR-0250 §11, §13) ----


@pytest.mark.parametrize("viewport", _VIEWPORTS)
async def test_answering_a_clarification_is_the_ordinary_turn_with_a_reference(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """ADR-0250 §11, driven end to end from the listing the owner was shown.

    "Answering is a turn and not an operation of its own, and that is the whole reason
    ``converse`` gains a keyword rather than the surface gaining a fifth verb." So the
    page has no answer form: pressing the row's control attaches the reference to the
    composer, and the next thing the owner sends carries it.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        drive.engine.goal_summaries = [_summary()]

        await _open_goals(drive)
        await drive.page.click("text=Answer this")
        await expect(drive.page.locator("#referencing")).to_be_visible()
        await drive.page.fill("#utterance", "the one at Melides")
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")

        turns = [call for call in drive.engine.calls if call[0].startswith("converse")]
        assert turns[-1][1]["reference"] == TurnReference(question_id=QUESTION_ID)
        # And it goes with the turn it was attached to: the next question is an
        # ordinary one, not a second answer to a question already settled.
        await expect(drive.page.locator("#referencing")).to_be_hidden()


async def test_a_goal_is_taken_up_here_by_pointing_at_it(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0250 §13's decision 5, at the surface that performs it.

    "A goal is resumed from another conversation by explicit reference and by that
    alone … performed from a surface listing the user was shown (§15)." There is no
    automatic cross-conversation association, so this control is the whole of the route.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary()]

        await _open_goals(drive)
        await drive.page.click("text=Take this up here")
        await drive.page.fill("#utterance", "make it Monday")
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")

        turns = [call for call in drive.engine.calls if call[0].startswith("converse")]
        assert turns[-1][1]["reference"] == TurnReference(goal_id=GOAL_ID)


async def test_a_reference_chosen_while_a_turn_is_out_survives_that_turn(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A turn drops the reference it carried and never a later one.

    The ask control is disabled while a turn is out, but the goals panel's are not — so
    an owner can pick a second goal while the first answer is still in flight, and a
    clear that ran on completion whatever was attached by then would undo an act they
    had just taken, silently, one turn later. Adversarial review, round 1, ``major``.

    Driven as the owner reaches it: attach a question, send, and — while that request is
    held — attach a goal instead. The turn then lands, and what the next question carries
    is the goal.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [
            _summary(),
            _summary(asking=False).model_copy(update={"id": OTHER_ID}),
        ]
        # The turn's request is stopped before it goes out, so the second choice lands
        # **inside** the window rather than by luck of scheduling (ADR-0216 §7).
        # ``_holding`` is ``test_browser_conversations``' own device, imported rather
        # than restated: a second implementation of "one request stopped in flight" is a
        # second thing a flake could be about.
        held = await _holding(drive, "/ask/stream", at=1)

        await _open_goals(drive)
        await drive.page.click("text=Answer this")
        await drive.page.fill("#utterance", "the one at Melides")
        await drive.page.click("#ask-button")
        await held.reached.wait()
        # The second choice, taken while the first turn's request is still outstanding.
        await drive.page.locator("#goal-list > div").nth(1).get_by_text("Take this up here").click()
        await held.release()
        await drive.page.wait_for_selector("#answer:not([hidden])")

        await expect(drive.page.locator("#referencing")).to_be_visible()
        await drive.page.fill("#utterance", "and make it Monday")
        await drive.page.click("#ask-button")
        # **The second turn's own completion, and not a predicate the first already
        # satisfied** (adversarial review, round 2, `major`). `#answer-body` holds a
        # paragraph from the first turn, so a wait for "a paragraph exists" is true
        # before the second request has even gone out. The hint is the condition this
        # page reaches only on the second turn's completion: it was asserted visible two
        # lines above, and `ask` hides it by clearing the reference it sent.
        await expect(drive.page.locator("#referencing")).to_be_hidden()

        turns = [call for call in drive.engine.calls if call[0].startswith("converse")]
        assert turns[-2][1]["reference"] == TurnReference(question_id=QUESTION_ID)
        assert turns[-1][1]["reference"] == TurnReference(goal_id=OTHER_ID)


async def test_a_refusal_the_gateway_took_leaves_the_reference_attached(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A turn that never reached the assistant consumes nothing.

    ADR-0168 §6 classifies a request "from its method and path alone" and the door takes
    an expired session, a malformed body and the connection ceiling **before**
    ``_assistant`` is reached — so such a turn settled no question and engaged no goal.
    Consuming the reference there would leave the owner's next press sending an ordinary
    turn in place of the answer they meant, and the hint would already be gone.
    Adversarial review, round 2, ``major``.

    The refusal is fulfilled at the transport rather than provoked, because every
    condition that produces one genuinely — an expired session most of all — also ends
    the session and takes the page off this panel, which is a different case. What is
    under test is what the page does with a refusal head, and that is what this hands it.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary()]

        # The **first** request is refused and every later one goes through, so the
        # retry below is a real turn rather than a second fabricated answer. Counted in
        # the handler for ``_holding``'s reason: unrouting by pattern would have to match
        # the matcher as well as the handler, and one counter cannot get that wrong.
        seen = {"n": 0}

        async def refuse(route: Route) -> None:
            seen["n"] += 1
            if seen["n"] > 1:
                await route.continue_()
                return
            await route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps({"fault": "malformed-request"}),
            )

        await drive.page.route(lambda url: urlparse(url).path == "/ask/stream", refuse)

        await _open_goals(drive)
        await drive.page.click("text=Answer this")
        await drive.page.fill("#utterance", "the one at Melides")
        await drive.page.click("#ask-button")
        await expect(drive.page.locator("#console .fault")).to_be_visible()

        # Still attached, still offered, and still saying what it is for: the owner
        # presses again and the same answer goes to the same question.
        await expect(drive.page.locator("#referencing")).to_be_visible()
        await expect(drive.page.locator("#referencing")).to_contain_text(
            "answers the clarification"
        )
        await expect(drive.page.locator("#clear-reference")).to_be_visible()
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")

        turns = [call for call in drive.engine.calls if call[0].startswith("converse")]
        assert [call[1]["reference"] for call in turns] == [TurnReference(question_id=QUESTION_ID)]


async def test_a_reference_already_sent_is_not_offered_as_one_that_can_be_taken_back(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The control stops being offered once the body carrying it has gone out.

    The reference is serialised at submission, so a "never mind" pressed while that
    request is in flight would hide the hint while the value still reached the assistant
    — a page claiming to have withdrawn something it had already sent, which is the
    silent refusal this surface spends the most words preventing (#1536, ADR-0139 §4).
    Adversarial review, round 2, ``major``.

    **And the sentence does not say the turn can be stopped**, because that is a
    different control with a different meaning: ``Stop waiting`` ends this browser's
    wait, and ADR-0173 §9 is explicit that abandoning the stream does not abandon the
    turn.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary()]
        held = await _holding(drive, "/ask/stream", at=1)

        await _open_goals(drive)
        await drive.page.click("text=Answer this")
        await drive.page.fill("#utterance", "the one at Melides")
        await drive.page.click("#ask-button")
        await held.reached.wait()

        await expect(drive.page.locator("#clear-reference")).to_be_hidden()
        said = await drive.page.inner_text("#referencing")
        assert "no longer be taken back" in said
        assert "stop" not in said.lower()

        await held.release()
        await expect(drive.page.locator("#referencing")).to_be_hidden()


async def test_a_wait_the_owner_ended_leaves_the_reference_offered_again(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """An abort is an ending too, and the page must not be left mid-sentence.

    Pressing ``Stop waiting`` aborts the request, so the exchange leaves ``ask`` through
    its ``catch`` — and a reconciliation written after the await would run on exactly one
    of three endings. What that left was a hint reading "that went out with the question
    now running" for good, on a wait the owner had just been told this browser was no
    longer listening for, with the control hidden so the reference could be neither taken
    back nor read. Adversarial review, round 3, ``major``.

    **The reference comes back rather than being consumed**, which is the conservative
    direction and the one ADR-0173 §9 argues for: abandoning the stream does not abandon
    the turn, so the assistant may have taken the question — and a second send of the
    same reference is answered ``ALREADY_SETTLED`` and rendered as its own fixed
    statement (ADR-0250 §11). That is an honest sentence; the other way round is an
    answer that silently goes nowhere.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary()]
        held = await _holding(drive, "/ask/stream", at=1)

        await _open_goals(drive)
        await drive.page.click("text=Answer this")
        await drive.page.fill("#utterance", "the one at Melides")
        await drive.page.click("#ask-button")
        await held.reached.wait()
        await drive.page.click("#stop-waiting")
        # The held request is let go before the state is read, because the abort reaches
        # the `fetch` through the interceptor: `release` returns once the browser has
        # finished with that request, whichever way it ended, so what is asserted below
        # is a settled state rather than a race (ADR-0216 §7).
        await held.release()

        await expect(drive.page.locator("#referencing")).to_contain_text(
            "answers the clarification"
        )
        await expect(drive.page.locator("#clear-reference")).to_be_visible()

        # And it is still the reference the next question carries.
        await drive.page.click("#ask-button")
        await expect(drive.page.locator("#referencing")).to_be_hidden()
        turns = [call for call in drive.engine.calls if call[0].startswith("converse")]
        assert turns[-1][1]["reference"] == TurnReference(question_id=QUESTION_ID)


async def test_a_gateway_that_went_away_leaves_the_reference_offered_again(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The other thrown ending, which is a rejected ``fetch`` rather than an act.

    ``ask``'s catch says ``GATEWAY_GONE`` for a connection that failed, and that ending
    reaches the reference through the same ``finally``: nothing was sent that arrived, so
    the value goes back on offer with the words it carried. Adversarial review, round 3,
    ``major``.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary()]

        async def cut(route: Route) -> None:
            await route.abort()

        await drive.page.route(lambda url: urlparse(url).path == "/ask/stream", cut)

        await _open_goals(drive)
        await drive.page.click("text=Answer this")
        await drive.page.fill("#utterance", "the one at Melides")
        await drive.page.click("#ask-button")
        await expect(drive.page.locator("#console .fault")).to_be_visible()

        await expect(drive.page.locator("#referencing")).to_contain_text(
            "answers the clarification"
        )
        await expect(drive.page.locator("#clear-reference")).to_be_visible()


async def test_giving_a_goal_up_takes_the_reference_to_it_with_it(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """An abandoned goal must not come back on the owner's next sentence.

    Press "Answer this", then "Give this up", then ask about anything at all: without
    this the question's id was still attached, ADR-0250 §11 makes a settled question's
    ``goal_id`` resolve "in every case" so the turn engages that goal, and §13 **reopens**
    a closed goal that a turn associates to. The owner gave the work up and their next
    sentence silently took it back. Adversarial review, round 4, ``major``.

    Nothing is lost by dropping it: "the handle is the question's own durable ``id`` and
    needs no re-minting" (§11), and the listing this act re-reads is where it is read
    again.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary()]
        drive.engine.abandonment = GoalAbandonment.ABANDONED
        _answering(drive, accept=True)

        await _open_goals(drive)
        await drive.page.click("text=Answer this")
        await expect(drive.page.locator("#referencing")).to_be_visible()
        await drive.page.click("text=Give this up")
        await expect(drive.page.locator("#goal-said")).to_be_visible()

        await expect(drive.page.locator("#referencing")).to_be_hidden()
        await drive.page.fill("#utterance", "what is on today")
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")

        turns = [call for call in drive.engine.calls if call[0].startswith("converse")]
        assert turns[-1][1]["reference"] is None


async def test_withdrawing_a_question_takes_the_reference_to_it_with_it(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The same clause one act over: there is no longer a question to answer.

    A withdrawal settles the question and clears the words it held (ADR-0250 §12), so a
    hint still promising that the next thing typed answers it is a sentence the page
    cannot stand behind — and the turn would engage the goal on the settled question's
    own ``goal_id`` (§11). Adversarial review, round 4, ``major``.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary()]
        drive.engine.withdrawal = ClarificationWithdrawal.WITHDRAWN

        await _open_goals(drive)
        await drive.page.click("text=Answer this")
        await expect(drive.page.locator("#referencing")).to_be_visible()
        await drive.page.click("text=Take the question back")
        await expect(drive.page.locator("#goal-said")).to_be_visible()

        await expect(drive.page.locator("#referencing")).to_be_hidden()


async def test_an_act_on_one_goal_leaves_a_reference_to_another_alone(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The identity check, which is what stops the clause above becoming a sweep.

    Two goals; a reference taken on the first, an act performed on the second. The act
    establishes nothing about the first, so the reference it carries stays exactly where
    the owner put it.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [
            _summary(),
            _summary(asking=False).model_copy(update={"id": OTHER_ID}),
        ]
        drive.engine.abandonment = GoalAbandonment.ABANDONED
        _answering(drive, accept=True)

        await _open_goals(drive)
        await drive.page.click("text=Answer this")
        await drive.page.locator("#goal-list > div").nth(1).get_by_text("Give this up").click()
        await expect(drive.page.locator("#goal-said")).to_be_visible()

        await expect(drive.page.locator("#referencing")).to_be_visible()
        await drive.page.fill("#utterance", "the one at Melides")
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")

        turns = [call for call in drive.engine.calls if call[0].startswith("converse")]
        assert turns[-1][1]["reference"] == TurnReference(question_id=QUESTION_ID)


async def test_a_stream_that_ended_without_an_outcome_leaves_the_reference_offered_again(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The last ending of the reference's lifecycle, enumerated rather than waited for.

    A body that ends without a terminal value is a transport failure (ADR-0175 §2), and
    one that ends before its first chunk establishes nothing about the assistant at all:
    ``waiting.ran`` is set by an ok head on the whole entry, by the first chunk, and by a
    terminal outcome, and this ending reaches none of the three.

    **The reference is kept, which is the conservative direction and is stated as a
    cost.** Such a turn may have run — ADR-0175 §10 declines resuming a cut stream, so
    what the page knows is only that it read no ending — and a second send of the same
    reference is answered ``ALREADY_SETTLED`` and rendered as its own fixed statement
    (ADR-0250 §11). That is an honest sentence; consuming it would be an answer that
    silently went nowhere.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary()]

        async def cut(route: Route) -> None:
            await route.fulfill(status=200, content_type="application/x-ndjson", body="")

        await drive.page.route(lambda url: urlparse(url).path == "/ask/stream", cut)

        await _open_goals(drive)
        await drive.page.click("text=Answer this")
        await drive.page.fill("#utterance", "the one at Melides")
        await drive.page.click("#ask-button")
        await expect(drive.page.locator("#console .fault")).to_be_visible()

        await expect(drive.page.locator("#referencing")).to_contain_text(
            "answers the clarification"
        )
        await expect(drive.page.locator("#clear-reference")).to_be_visible()


@pytest.mark.parametrize(
    ("path", "act", "again", "expected"),
    [
        # The goal this act closed, taken back up: §13's explicit-reference resume.
        ("/goal/abandon", "Give this up", "Take this up here", TurnReference(goal_id=GOAL_ID)),
        # The question this act settled, selected again — which is the shape the id test
        # matches and the identity test does not.
        (
            "/clarification/withdraw",
            "Take the question back",
            "Answer this",
            TurnReference(question_id=QUESTION_ID),
        ),
    ],
)
async def test_a_selection_made_while_an_act_is_out_is_the_one_that_stands(  # noqa: PLR0913 — the two fixtures plus one parameter per leg of the interleaving: the act's path, the control that starts it, the control pressed while it is out, and what the next turn must then carry
    gateway_browser: Browser,
    tmp_path: Path,
    path: str,
    act: str,
    again: str,
    expected: TurnReference,
) -> None:
    """The later of the owner's two acts wins, over the **same** record.

    An act's request can still be out when the owner presses "Take this up here" on the
    same row, and matching by record id alone let the answer erase a selection made
    *after* it. ADR-0250 §13 makes taking a closed goal up by explicit reference a
    legitimate act — "a goal is resumed … by explicit reference and by that alone" — so
    the newer press is a decision and not a leftover. Adversarial review, round 5,
    ``major``.

    Driven over both acts, because both settle a record the reference can name, and with
    the act's own request held so the interleaving is the drive's rather than the
    scheduler's (ADR-0216 §7).
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary()]
        drive.engine.abandonment = GoalAbandonment.ABANDONED
        drive.engine.withdrawal = ClarificationWithdrawal.WITHDRAWN
        _answering(drive, accept=True)
        held = await _holding(drive, path, at=1)

        await _open_goals(drive)
        await drive.page.click("text=Answer this")
        await drive.page.click(f"text={act}")
        await held.reached.wait()
        # Taken while the act is still out, and about the same record it is settling.
        await drive.page.click(f"text={again}")
        await held.release()
        await expect(drive.page.locator("#goal-said")).to_be_visible()

        await expect(drive.page.locator("#referencing")).to_be_visible()
        await drive.page.fill("#utterance", "pick it back up")
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")

        turns = [call for call in drive.engine.calls if call[0].startswith("converse")]
        assert turns[-1][1]["reference"] == expected


async def test_a_reference_can_be_given_up_before_it_is_sent(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A reference the owner has changed their mind about must have a way out.

    Nothing is lost by giving one up: "the handle is the question's own durable ``id``
    and needs no re-minting" (ADR-0250 §11), so it is read again from the listing at no
    cost — where a consent token is process-scoped and is spent carefully.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        drive.engine.goal_summaries = [_summary()]

        await _open_goals(drive)
        await drive.page.click("text=Answer this")
        await drive.page.click("#clear-reference")
        await expect(drive.page.locator("#referencing")).to_be_hidden()
        await drive.page.fill("#utterance", "something else entirely")
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")

        turns = [call for call in drive.engine.calls if call[0].startswith("converse")]
        assert turns[-1][1]["reference"] is None


# --- the four members on a turn (ADR-0250 §5, §10, §11) ----------------------


async def _composed(drive: Drive) -> TurnOutcome:
    """One real composed turn, from the fake's own ``converse``."""
    outcome = await drive.engine.converse("book the usual campsite", timeout=timedelta(seconds=5))
    assert outcome.turn is not None
    return outcome


async def _ask(drive: Drive, outcome: TurnOutcome) -> str:
    """Run one turn whose outcome is scripted and return what the panel says."""
    drive.engine.turn_outcome = outcome
    await drive.page.fill("#utterance", "book the usual campsite")
    await drive.page.click("#ask-button")
    await drive.page.wait_for_selector("#answer:not([hidden])")
    return await drive.answer()


@pytest.mark.parametrize("member", list(EngagementDisposition))
async def test_every_engagement_disposition_reaches_the_owner_as_a_sentence(
    gateway_browser: Browser, tmp_path: Path, member: EngagementDisposition
) -> None:
    """ADR-0250 §15's non-degradation clause over ``EngagementDisposition``'s four.

    And **no announcement of the page's own**: §5 gives that sentence to the reply,
    stating the outcome and every text in ``added`` and ``removed``, so the arm drives a
    revision that moved words and asserts none of them reaches the screen from here.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        base = await _composed(drive)
        said = await _ask(
            drive,
            base.model_copy(
                update={
                    "reply": "Right.",
                    "goal_engagement": GoalEngagement(
                        disposition=member,
                        outcome=OUTCOME,
                        revised=True,
                        outcome_changed=True,
                        added=("the last weekend of September",),
                        removed=("the last weekend of August",),
                    ),
                }
            ),
        )

        assert "What I am working on" in said
        assert "September" not in said
        assert OUTCOME not in said
        assert GOAL_ID not in said


@pytest.mark.parametrize("member", list(ReferenceOutcome))
async def test_every_reference_outcome_reaches_the_owner_as_a_sentence(
    gateway_browser: Browser, tmp_path: Path, member: ReferenceOutcome
) -> None:
    """ADR-0250 §15's clause over ``ReferenceOutcome``'s four, driven.

    Rendered whether or not a goal was engaged, which is why the outcome carries no
    engagement: "``reference`` is a member of its own precisely so that the user is
    still told the handle they gave resolved to nothing".
    """
    async with driving(gateway_browser, tmp_path) as drive:
        base = await _composed(drive)
        said = await _ask(drive, base.model_copy(update={"reply": "Right.", "reference": member}))

        assert said.strip()
        assert QUESTION_ID not in said
        assert GOAL_ID not in said


async def test_a_raised_question_is_on_the_screen_with_the_id_its_answer_takes(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0250 §10: the question appears in the exchange that raised it.

    The turn did not park — "it composes, its answer *is* the question, and it returns" —
    so there is no token and no approval pair, and the id is on screen because the answer
    act takes it (§15).
    """
    async with driving(gateway_browser, tmp_path) as drive:
        base = await _composed(drive)
        said = await _ask(
            drive,
            base.model_copy(
                update={
                    "reply": "Which one did you mean?",
                    "goal_engagement": GoalEngagement(
                        disposition=EngagementDisposition.OPENED, outcome=OUTCOME
                    ),
                    "clarification": _clarification(),
                }
            ),
        )

        assert QUESTION in said
        assert QUESTION_ID in said
        assert "No action was needed." not in said


async def test_an_undecided_turn_says_what_to_do_and_does_not_restate_the_ask(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0250 §5's ask is the reply's, and §14 places it in exactly this turn.

    A second listing of the same outcome statements underneath would be that mention
    twice on one screen, and would be this page composing a reply (golden rule 3). What
    the page adds is the half a reply cannot carry: where the owner goes next.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        said = await _ask(
            drive,
            TurnOutcome(
                turn=None,
                conversation_id="c-1",
                reply="Is this about the campsite, or something new?",
                disambiguation=GoalDisambiguation(candidates=(OUTCOME,), elided=0),
            ),
        )

        assert said.count(OUTCOME) == 0
        assert "What I am working on" in said
        assert "No action was needed." not in said
