"""The attempt report as a browser really renders it (ADR-0262 §6, ADR-0216 §1).

§11's **L5** puts the browser in the same lane as the terminal rather than a later one:
"§6's six fixed statements, on the CLI and on the browser — **both surfaces**, since a
member rendered on one and not the other is the parity failure M4 recorded."

**And ADR-0216 §1 is why these cases exist beside ``test_bundle.py``'s text-layer pins**: a
substring assertion over ``app.js`` is as green over a renderer nothing calls as over one
that works. What is asserted here is what Chromium put on the screen.

**Both viewports**, because a statement below the fold is a statement the owner does not
read. ``browser_drive`` holds ADR-0233 §15's two figures and this module drives both.

**The engine is the canonical fake, scripted.** No sequence of page acts runs a
comparison, so each case states the report it is about on ``turn_outcome``, which is
``test_browser_forecast.py``'s own arrangement one vocabulary over.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from typing import TYPE_CHECKING, Final

import pytest
from browser_drive import DESKTOP, PHONE, driving
from rich.console import Console
from test_browser_answers import _stop_substituting, _substitute

from ai_assistant.core.types import AttemptOutcome, AttemptReport, TurnOutcome
from ai_assistant.interfaces import cli

if TYPE_CHECKING:
    from pathlib import Path

    from browser_drive import Drive
    from playwright.async_api import Browser, ViewportSize

_QUESTION: Final = "book the flight"

#: The one member of ``AttemptOutcome`` ADR-0262 §6's report does not admit.
_NOT_A_REPORT_MEMBER: Final = AttemptOutcome.CANCELLED


def _terminal(member: AttemptOutcome) -> str:
    """What the **terminal** renders for one member, flattened.

    **Read off the other surface rather than restated here**, and that is the arm rather
    than a convenience. ADR-0262 §11 put both surfaces in one lane "since a member
    rendered on one and not the other is the parity failure M4 recorded", and this lane
    writes the two prose sets byte for byte identically — so driving the browser against
    the terminal's own words makes every case below a cross-surface assertion: a sentence
    edited in ``app.js`` and not in ``cli.py`` fails here, in Chromium, rather than only
    in ``test_cli_attempt_report.py``'s text-layer parity arm.

    A fourth copy of the six sentences, written out in this module, would have been green
    against two surfaces that had drifted together.
    """
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=200)
    original = cli.console
    cli.console = console
    try:
        cli._render_attempt_report(AttemptReport(outcome=member, continues=False))
    finally:
        cli.console = original
    return " ".join(buffer.getvalue().replace("\u21b3", " ").split())


#: The six §6's report admits, each as the terminal renders it.
_STATEMENTS: Final[dict[AttemptOutcome, str]] = {
    member: _terminal(member) for member in AttemptOutcome if member is not _NOT_A_REPORT_MEMBER
}

#: The two members whose statement is compatible with a turn that needed no step, and
#: which therefore do **not** suppress "No action was needed." — ADR-0262 §12's first arm
#: is a turn of the second kind.
_COMPATIBLE_WITH_NO_ACTION: Final = frozenset({AttemptOutcome.VERIFIED, AttemptOutcome.ANSWERED})

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


@pytest.mark.parametrize("member", list(_STATEMENTS))
@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_every_member_reaches_the_owner_as_a_sentence(
    gateway_browser: Browser, tmp_path: Path, member: AttemptOutcome, viewport: ViewportSize
) -> None:
    """ADR-0262 §6's six, on the screen, at both widths.

    Parametrised over the vocabulary itself, so an eighth ``AttemptOutcome`` arriving with
    the ADR that decides it fails here rather than rendering nothing in front of an owner
    — the #1113 rule, driven rather than read.

    **Beside the reply and never in place of it**: the reply the turn composed is still on
    the screen above the statement, which is the half a renderer that replaced the panel
    would pass a substring assertion on.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        base = await _composed(drive)
        said = await _ask(
            drive,
            base.model_copy(
                update={
                    "reply": "Here is where that got to.",
                    "attempt_report": AttemptReport(outcome=member, continues=False),
                }
            ),
        )

        assert _STATEMENTS[member] in said, member
        assert "Here is where that got to." in said
        assert said.index("Here is where that got to.") < said.index(_STATEMENTS[member])


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
async def test_a_turn_that_ended_no_attempt_says_nothing_about_one(
    gateway_browser: Browser, tmp_path: Path, viewport: ViewportSize
) -> None:
    """ADR-0262 §6: the member is non-``None`` "exactly on a turn that ended an attempt
    under §4".

    Its absence is a turn that engaged no goal, a routed operation, ADR-0198 §1's
    restatement, an attempt still live — **and a turn whose ``commit_attempt`` was
    refused**, which §6 fixes as "a silence rather than a false claim", the composed reply
    standing as composed. So the page says nothing about an attempt at all.
    """
    async with driving(gateway_browser, tmp_path, viewport=viewport) as drive:
        base = await _composed(drive)
        said = await _ask(drive, base.model_copy(update={"reply": "Booked, near enough."}))

        assert "Booked, near enough." in said
        for statement in _STATEMENTS.values():
            assert statement not in said


@pytest.mark.parametrize("member", list(_STATEMENTS))
async def test_no_action_was_needed_is_not_shown_beside_a_statement_asserting_work(
    gateway_browser: Browser, tmp_path: Path, member: AttemptOutcome
) -> None:
    """The contradiction on one screen, driven rather than read.

    The comparison runs after the plan, so a turn that planned nothing still ends an
    attempt and still carries a report — limb 1's first arm is an established
    contradiction read off the goal's own earlier records, which needs no step of this
    turn. "No action was needed." above "The work failed, and no criterion of this goal
    was established." says both that nothing was owed and that work was attempted and did
    not complete.

    **Over all six, because the split is the point.** ``VERIFIED`` and ``ANSWERED`` each
    say something a turn that needed no step may truthfully say, and ADR-0262 §12's first
    arm is exactly a turn of the second kind — so the notice **stays** beside those two.
    Suppressing it on the member's presence would have taken a true line off every
    ordinary attempt-ending turn.

    **``CANCELLED`` is driven in the substitution case below rather than here**, because
    the canonical fake refuses that *arrangement* outright — "a report naming it is a
    state no engine reaches, and a double that let a consumer arrange one would certify
    that consumer against a seventh fixed statement §6 does not authorise". So a
    conforming hub cannot produce the turn this case would need, and the only honest route
    to it is a substituted body.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        base = await _composed(drive)
        assert base.turn is not None
        assert not base.turn.plan.steps, "the arm is about a turn that planned nothing"
        said = await _ask(
            drive,
            base.model_copy(
                update={
                    "reply": "Here is where that got to.",
                    "attempt_report": AttemptReport(outcome=member, continues=False),
                }
            ),
        )

        suppressed = member not in _COMPATIBLE_WITH_NO_ACTION
        assert ("No action was needed." not in said) is suppressed, member
        assert _STATEMENTS[member] in said, member


async def test_no_action_was_needed_is_still_shown_where_no_attempt_ended(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """The control the arm above needs to mean anything: a guard that suppressed the
    notice unconditionally would pass every case there and would have taken a true
    statement off every ordinary turn."""
    async with driving(gateway_browser, tmp_path) as drive:
        base = await _composed(drive)
        said = await _ask(drive, base.model_copy(update={"reply": "Booked, near enough."}))

        assert "No action was needed." in said


async def test_only_the_two_statements_that_cannot_speak_for_the_status_name_a_command(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0262 §6's fixed half, on the surface that has no goals listing of its own.

    §6 names ``assistant goals`` in ``VERIFIED``'s statement and in ``UNCERTAIN``'s,
    because each is a statement a later commit could leave the goal standing differently
    beside — so it says where the status is read rather than asserting one. The other four
    name nothing. Naming the terminal's command from this page is this surface's own
    ratified practice (``UNREADABLE_RULINGS``): inventing a control here would be minting
    a route no ratified decision gives this surface.
    """
    names_goals = {AttemptOutcome.VERIFIED, AttemptOutcome.UNCERTAIN}
    async with driving(gateway_browser, tmp_path) as drive:
        base = await _composed(drive)
        for index, member in enumerate(_STATEMENTS):
            said = await _ask(
                drive,
                base.model_copy(
                    update={
                        "reply": f"Answer number {index}.",
                        "attempt_report": AttemptReport(outcome=member, continues=False),
                    }
                ),
            )
            assert ("assistant goals" in said) is (member in names_goals), member
            for barred in ("assistant resume", "assistant decisions", "assistant cancel-read"):
                assert barred not in said, f"{member}: {barred}"


async def test_no_statement_carries_the_offer_that_belongs_to_the_reply(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """ADR-0262 §6: "**The offer is in the reply rather than on the surface**".

    "An offer a surface printed would reach neither the browser's transcript nor the
    spoken channel as part of what was said. So the **reply** carries the offer and the
    **surface** the outcome word." Driven over a ``continues`` report whose reply carries
    the offer, so what is asserted is that the page rendered the reply's one and did not
    add a second of its own.
    """
    async with driving(gateway_browser, tmp_path) as drive:
        base = await _composed(drive)
        said = await _ask(
            drive,
            base.model_copy(
                update={
                    "reply": "I got part of the way. Shall I try again later?",
                    "attempt_report": AttemptReport(outcome=AttemptOutcome.PARTIAL, continues=True),
                }
            ),
        )

        assert said.count("Shall I try again later?") == 1
        assert _STATEMENTS[AttemptOutcome.PARTIAL] in said
        assert "continues" not in said.lower()


async def test_a_member_outside_the_six_is_said_rather_than_shown_raw(
    gateway_browser: Browser, tmp_path: Path
) -> None:
    """A value that is not one of §6's six is reported as one the page has no words for.

    ``AttemptOutcome`` is closed at seven and the report admits six; ``CANCELLED`` "is
    reached by no limb" of the comparison (§4) but the **type admits it**, so a hub at
    another version can send one — and a browser can be sent any string at all.

    **Not a bare identifier and not silence**, which is ``FORECAST_NOT_READ_UNREADABLE``'s
    ratified position one vocabulary over, and **not a seventh fixed statement**: §6 fixes
    six, and minting one for a member it excludes would be this surface deciding a
    vocabulary.

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
                '"forecast_not_read": null, "attempt_report": "a_later_member", '
                '"authorizations": []}}'
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
        # And the notice is **not** suppressed here: the unreadable statement asserts
        # nothing about what was attempted, so there is nothing for "No action was
        # needed." to contradict. This is the one route to a value outside the six —
        # the canonical fake refuses the arrangement — and it is where `CANCELLED`'s
        # own behaviour is driven, the two reaching the same branch.
        assert "No action was needed." in said
