"""The forecast statement as a browser really renders it (ADR-0260 §10, ADR-0216 §1).

§10 places no deferral on any surface — "A surface renders, beside the reply and never in
place of it, one fixed statement per member" — and ADR-0262 §11 is why the browser is in
the same lane as the terminal rather than a later one: "both surfaces, since a member
rendered on one and not the other is the parity failure M4 recorded".

**And ADR-0216 §1 is why these cases exist beside ``test_bundle.py``'s text-layer pins**: a
substring assertion over ``app.js`` is as green over a renderer nothing calls as over one
that works. What is asserted here is what Chromium put on the screen.

**Both viewports**, because a statement below the fold is a statement the owner does not
read. ``browser_drive`` holds ADR-0233 §15's two figures and this module drives both.

**The engine is the canonical fake, scripted.** It wires no forecaster and records no
``ForecastDisposition``, so no sequence of page acts reaches any of the six: each case
states the outcome it is about on ``turn_outcome``, which is
``test_browser_goals.py``'s own arrangement one vocabulary over. (The attribute lever
:attr:`~ai_assistant.testing.FakeAssistantEngine.forecast_not_read` this lane added is
what reaches the member where the *outcome* is not the caller's to build —
``converse_streaming``'s, and the terminal's end-to-end arm.)
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

import pytest
from browser_drive import DESKTOP, PHONE, driving
from test_browser_answers import _stop_substituting, _substitute

from ai_assistant.core.types import ForecastNotRead, TurnOutcome

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, ViewportSize

#: What each member must say on this surface, as a fragment of the answer panel's text.
#:
#: The wording is the lane's and §10 fixes only which command each names, so the fragments
#: are the sentence's own load-bearing words rather than the whole of it.
_SAID: Final[dict[ForecastNotRead, str]] = {
    ForecastNotRead.NOT_CONFIGURED: "No forecast source is configured in this deployment.",
    ForecastNotRead.AUTHORISATION_AWAITED: ("put to you as a question instead of being made"),
    ForecastNotRead.SPEND_EXHAUSTED: "A spending ceiling refused that forecast read.",
    ForecastNotRead.DECLINED: "That forecast read was declined when it was ruled on.",
    ForecastNotRead.INTERRUPTED: "That forecast read was begun and stopped.",
    ForecastNotRead.UNAVAILABLE: "That forecast read produced nothing this turn could use.",
}

_QUESTION: Final = "will it rain tomorrow?"

#: The marks every module of the executable layer carries (ADR-0216 §3).
#:
#: ``loop_scope="session"`` is the load-bearing one: the browser is one session-scoped
#: fixture shared by the whole layer, and a case on a per-function loop awaits a browser
#: bound to another loop and never wakes — a hang rather than a failure, which is what
#: it cost to find.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.browser,
    pytest.mark.xdist_group("gateway_browser"),
    pytest.mark.asyncio(loop_scope="session"),
]


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


@pytest.mark.parametrize("member", list(ForecastNotRead))
@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_every_member_reaches_the_owner_as_a_sentence(
    gateway_browser: Browser, tmp_path: Path, member: ForecastNotRead, viewport: ViewportSize
) -> None:
    """ADR-0260 §10's six, on the screen, at both widths.

    Parametrised over the vocabulary itself, so a seventh member arriving with the ADR
    that decides it fails here rather than rendering nothing in front of an owner — the
    #1113 rule, driven rather than read.

    **Beside the reply and never in place of it**: the reply the turn composed is still on
    the screen above the statement, which is the half a renderer that replaced the panel
    would pass a substring assertion on.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        base = await _composed(drive)
        said = await _ask(
            drive,
            base.model_copy(update={"reply": "I cannot say.", "forecast_not_read": member}),
        )

        assert _SAID[member] in said, member
        assert "I cannot say." in said
        assert said.index("I cannot say.") < said.index(_SAID[member])


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_a_turn_that_read_its_forecast_says_nothing_about_one(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """ADR-0260 §10: ``None`` "means the servicing recorded no ``ForecastDisposition``, and
    means nothing else" — a turn that serviced no forecast read, and a read the provider
    answered. So the page says nothing about a forecast at all, which is the byte-identity
    the member's absence is owed.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        base = await _composed(drive)
        said = await _ask(drive, base.model_copy(update={"reply": "Sunny, most likely."}))

        assert "Sunny, most likely." in said
        assert "forecast" not in said.lower()


@pytest.mark.parametrize("member", list(ForecastNotRead))
async def test_no_action_was_needed_is_not_shown_beside_a_forecast_statement(
    gateway_browser: Browser, tmp_path: Path, member: ForecastNotRead
) -> None:
    """Adversarial review, round 1, ``major``: the contradiction on one screen.

    A forecast read is serviced in context assembly and not as a plan step, so a turn
    whose planner then declined every capability reaches ``renderOutcome`` with an empty
    plan while ``forecast_not_read`` says a read it asked for did not happen. "No action
    was needed." above "That forecast read was begun and stopped" says both that nothing
    was owed and that something was attempted and stopped.

    **All six, because this vocabulary has no member for having attempted nothing** —
    ADR-0260 §10 fixes the absence as that state, so ``null`` is where the guard stays
    off. Driven rather than read, because the guard is a condition over an outcome and a
    substring assertion over ``app.js`` is as green over one nothing evaluates.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        base = await _composed(drive)
        assert base.turn is not None
        assert not base.turn.plan.steps, "the arm is about a turn that planned nothing"
        said = await _ask(
            drive, base.model_copy(update={"reply": "I cannot say.", "forecast_not_read": member})
        )

        assert "No action was needed." not in said, member
        assert _SAID[member] in said, member


async def test_no_action_was_needed_is_still_shown_where_no_forecast_was_asked_for(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The control the arm above needs to mean anything: a guard that suppressed the
    notice unconditionally would pass every case there and would have taken a true
    statement off every ordinary turn."""
    async with driving(gateway_browser, tmp_path) as drive:
        base = await _composed(drive)
        said = await _ask(drive, base.model_copy(update={"reply": "Sunny, most likely."}))

        assert "No action was needed." in said


async def test_only_the_awaited_statement_names_a_command(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0260 §10's fixed half, on the surface that has no listing of its own.

    "What is fixed is which command each names and that ``UNAVAILABLE`` names none."
    ``AUTHORISATION_AWAITED`` names ``assistant decisions`` here as it does on the
    terminal, because §10 fixes the command per **member** and not per surface, and this
    page has no decisions listing to point at — inventing a control here would be minting
    a route no ratified decision gives this surface. Naming the terminal's command from
    the page is this surface's own ratified practice (``UNREADABLE_RULINGS``).
    """
    async with driving(gateway_browser, tmp_path) as drive:
        base = await _composed(drive)
        for index, member in enumerate(ForecastNotRead):
            said = await _ask(
                drive,
                base.model_copy(
                    update={"reply": f"Answer number {index}.", "forecast_not_read": member}
                ),
            )
            names_a_command = member is ForecastNotRead.AUTHORISATION_AWAITED
            assert ("assistant decisions" in said) is names_a_command, member
            for barred in ("assistant resume", "assistant cancel-read", "remember-recipients"):
                assert barred not in said, f"{member}: {barred}"


async def test_a_member_outside_the_enumeration_is_said_rather_than_shown_raw(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A value that is not one of the six is reported as one the page has no words for.

    **Not a bare identifier and not silence**, which is ``READ_ANSWER_UNREADABLE``'s
    position one vocabulary over: an enum value on the screen is this surface reporting an
    internal vocabulary to a person, and silence is the failure #2474 was filed about — a
    turn whose forecast did not happen reading exactly like one whose forecast was never
    asked for.

    **Rendered rather than thrown for**, and that is where this differs from
    ``renderReadAnswer``: nothing on this page is spent, given back or settled by a
    forecast statement, so the honest ending is to say what is known and no more.

    Driven by substituting the response body, because a value outside the enumeration is
    one no conforming gateway sends and ``_outcome_view`` cannot be made to send it. The
    stream is switched off first so that the substituted path is the one the page asks —
    ``/ask`` carries the whole outcome as one body, where ``/ask/stream`` carries it as
    the last value of an NDJSON sequence.
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
                '"forecast_not_read": "a_later_member", "authorizations": []}}'
            ),
        )
        await drive.page.fill("#utterance", _QUESTION)
        await drive.page.click("#ask-button")
        await drive.page.wait_for_selector("#answer:not([hidden])")
        said = await drive.answer()
        await _stop_substituting(drive)

        assert "no words for" in said
        assert "a_later_member" not in said
