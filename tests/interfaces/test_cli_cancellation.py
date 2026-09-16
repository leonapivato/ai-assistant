"""The terminal's cancellation surfaces (ADR-0261 §6, §7, §13's L3, §14 arms 8 and 10).

§13's **L3**: "The fixed statements §6 and §7 name, on the CLI's abandon and goals
surfaces and on the reply — **including the abandon command's exit code**, which today
answers non-zero for every ``GoalAbandonment`` member but ``ABANDONED`` and would
otherwise report a successful cancellation as a failure (§10). **Thin, by golden rule
3**: it renders values L2 computed and derives none."

**Every case asserts over the rendered bytes**, because §6's and §7's obligation is
discharged in what the user reads and nowhere else — ``test_cli_attempt_report.py``'s own
clause two vocabularies over: a statement that only exists in a helper's return value is
a statement no user was ever told.

**And the parity arms are here rather than in either surface's own module**, because what
they are about is the pair. This lane writes the two surfaces' prose byte for byte
identically, so each arm asserts an equality rather than the fixed half alone — which is
strictly stronger than what §6 and §7 themselves require, both of which leave the wording
to the lane and fix only which fact each statement names.

**The exit-code arm is a per-member table and not a comparison**, which is §14 arm 10's
own reason: the tree's assertion read ``code == (0 if member is GoalAbandonment.ABANDONED
else 1)`` and §10 names it as where "a silent regression lives" — a member added to the
vocabulary joins the **failing** side while every test stays green. The table lives in
``test_cli_goals.py``, beside the rest of that command's cases, and this module asserts
the rendering that arm is stated over.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Final

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.types import (
    DriveWithheld,
    GoalAbandonment,
    GoalStatus,
    GoalSummary,
    TurnOutcome,
)
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine

PATIENT: Final = timedelta(seconds=30)

_AT: Final = datetime(2026, 5, 1, 9, tzinfo=UTC)

_GOAL_ID: Final = "goal-qqzz-4417"

_APP_JS: Final = Path(cli.__file__).resolve().parent / "gateway" / "assets" / "app.js"

#: ADR-0261 §7's seven members, and the sentence each renders as.
#:
#: **Whole sentences rather than fragments**, because this lane writes both surfaces'
#: prose and the parity arm below asserts they are the same text. §7 fixes which fact each
#: names and leaves the wording to the lane, so what is pinned here is this lane's choice —
#: and pinning it whole is what makes a later edit to one surface fail rather than drift.
#:
#: **``ATTEMPT_CANCELLED`` and ``ATTEMPT_ENDED`` are one sentence because §7 writes them
#: one**: "for ``ATTEMPT_CANCELLED`` and ``ATTEMPT_ENDED``, that the attempt this plan
#: belonged to is over and that **the goal is not thereby closed**, asking again starting
#: a new one." The collapse §7 forbids is a different pair each time — "not
#: ``GOAL_CANCELLED`` with ``ATTEMPT_CANCELLED``, and not ``GOAL_BLOCKED`` with
#: ``ATTEMPT_PAUSED``" — and the arm below asserts those four read differently.
_STATEMENTS: Final[dict[DriveWithheld, str]] = {
    DriveWithheld.GOAL_CANCELLED: (
        "That goal was cancelled, and this turn did nothing further for it."
    ),
    DriveWithheld.GOAL_ACHIEVED: (
        "That goal is already reached, and this turn did nothing further for it."
    ),
    DriveWithheld.GOAL_BLOCKED: (
        "That goal cannot currently be reached, and it is still open. "
        "'assistant goals' is where you read how it stands."
    ),
    DriveWithheld.ATTEMPT_CANCELLED: (
        "The attempt that plan belonged to is over. The goal is not closed by that, "
        "and asking again starts a new attempt."
    ),
    DriveWithheld.ATTEMPT_ENDED: (
        "The attempt that plan belonged to is over. The goal is not closed by that, "
        "and asking again starts a new attempt."
    ),
    DriveWithheld.ATTEMPT_PAUSED: (
        "That goal is waiting on you. 'assistant goals' is where you read what it is waiting for."
    ),
    DriveWithheld.UNDERSTANDING_CHANGED: (
        "The plan I had no longer matches what that goal now asks. Asking again plans it afresh."
    ),
}

#: The two members §7 requires to name ``assistant goals``, and the five that name nothing.
#:
#: §7's fixed half: "for ``GOAL_BLOCKED``, that the goal **cannot currently be reached and
#: is still open**, naming ``assistant goals`` … for ``ATTEMPT_PAUSED``, that the goal is
#: waiting on the user, naming ``assistant goals``".
_NAMES_THE_LISTING: Final = frozenset({DriveWithheld.GOAL_BLOCKED, DriveWithheld.ATTEMPT_PAUSED})

#: The pairs §7 forbids collapsing, which is what makes the shared sentence above legible
#: as the ADR's own arrangement rather than as this surface folding two facts into one.
_MUST_NOT_READ_ALIKE: Final = (
    (DriveWithheld.GOAL_CANCELLED, DriveWithheld.ATTEMPT_CANCELLED),
    (DriveWithheld.GOAL_BLOCKED, DriveWithheld.ATTEMPT_PAUSED),
)


def _flat(rendered: str) -> str:
    """Collapse Rich's wrapping and its continuation marker (#2072).

    :func:`cli._print` writes a ``↳`` onto every display line a line runs onto, so an
    assertion about words needs the marker gone as well as the break — and a command name
    is exactly the sort of string that lands on one.
    """
    return " ".join(rendered.replace("↳", " ").split())


def _said(member: DriveWithheld | None) -> str:
    """What the terminal renders for one member, flattened."""
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=100)
    original = cli.console
    cli.console = console
    try:
        cli._render_drive_withheld(member)
    finally:
        cli.console = original
    return _flat(buffer.getvalue())


def _browser_map(name: str) -> dict[str, str]:
    """One top-level ``const NAME = { ... };`` of the shipped bundle, as sentences.

    Read out of ``app.js`` itself, which is where the browser's obligation is discharged:
    a parity arm over a value a test module restated would be green against two surfaces
    that had drifted together.
    """
    script = _APP_JS.read_text(encoding="utf-8")
    opened = script.index(f"\nconst {name} = {{")
    block = script[opened : script.index("\n};", opened)]
    parts = re.split(r"^  (\w+):", block, flags=re.MULTILINE)
    return {
        parts[index]: "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', parts[index + 1]))
        for index in range(1, len(parts), 2)
    }


def _browser_constant(name: str) -> str:
    """One top-level ``const NAME = "..." + "...";`` of the shipped bundle."""
    script = _APP_JS.read_text(encoding="utf-8")
    opened = script.index(f"\nconst {name} =")
    return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', script[opened : script.index(";\n", opened)]))


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=100))
    return buffer


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object) -> None:
    """Point the commands' startup at ``engine`` (ADR-0084 §6's seam)."""

    async def _open() -> object:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)


async def _composed() -> TurnOutcome:
    """One real composed turn from the canonical fake, for an arm to copy a member onto."""
    outcome = await FakeAssistantEngine().converse("book the flight", timeout=PATIENT)
    assert outcome.turn is not None
    return outcome


def _goal(*, effect_in_flight: bool, status: GoalStatus = GoalStatus.ACTIVE) -> GoalSummary:
    """One listed goal, with §6's field set either way."""
    return GoalSummary(
        id=_GOAL_ID,
        outcome="the flight is booked",
        status=status,
        paused=False,
        effect_in_flight=effect_in_flight,
        last_engaged_at=_AT,
    )


# --- ADR-0261 §7: one fixed statement per member, and no member without one --


@pytest.mark.parametrize("member", list(DriveWithheld))
def test_every_withheld_member_renders_a_statement_of_its_own(member: DriveWithheld) -> None:
    """§7's closure at seven, read off ``core``'s own vocabulary.

    "**One fixed statement per member**", beside the reply, under ADR-0242 §9's
    all-or-nothing rule — so an **eighth** member arriving with the ADR that decides it
    fails here rather than reaching a person as silence or as a bare identifier. That is
    the #1113 rule at this vocabulary, and it is why the parametrisation is over
    ``DriveWithheld`` itself rather than over the seven this module names.
    """
    said = _said(member)

    assert said.strip(), member
    assert member.value not in said, member
    assert said == _STATEMENTS[member], member


def test_an_absent_member_is_silence_and_not_a_refusal() -> None:
    """§7: the member is non-``None`` "exactly on a turn that *returned* after a
    ``ClaimRefused`` whose post-refusal read established one of the seven states".

    ``None`` on every other returned outcome — every turn that dispatched, every turn that
    stopped on one of ADR-0255 §2's five, every turn that drove nothing at all, and
    ADR-0198 §1's restatement — and a refusal that **propagates** returns no outcome at
    all, so it is outside the invariant rather than a silent case of it. A driver **skip**
    gains no carrier here either.
    """
    assert _said(None) == ""


@pytest.mark.parametrize(("left", "right"), _MUST_NOT_READ_ALIKE)
def test_the_two_pairs_the_adr_forbids_collapsing_read_differently(
    left: DriveWithheld, right: DriveWithheld
) -> None:
    """§7: "**No lane collapses any two of the seven** — not ``GOAL_CANCELLED`` with
    ``ATTEMPT_CANCELLED``, and not ``GOAL_BLOCKED`` with ``ATTEMPT_PAUSED``."

    A goal's disposition and its attempt's state are two facts and get two members. The
    one pair that *does* read alike here is ``ATTEMPT_CANCELLED`` with ``ATTEMPT_ENDED``,
    which is §7's own arrangement rather than a fold — that section writes the two one
    sentence — and the case below pins it as such.
    """
    assert _said(left) != _said(right)


def test_the_one_pair_the_adr_writes_one_sentence_reads_alike() -> None:
    """§7 gives ``ATTEMPT_CANCELLED`` and ``ATTEMPT_ENDED`` one statement between them.

    Stated so the equality above is legible as the ADR's arrangement rather than as an
    accident this surface could quietly extend to a third member: the two still have
    entries of their own, so the closure arm still fails on an eighth.
    """
    assert _said(DriveWithheld.ATTEMPT_CANCELLED) == _said(DriveWithheld.ATTEMPT_ENDED)


@pytest.mark.parametrize("member", list(DriveWithheld))
def test_no_withheld_statement_asserts_what_the_read_did_not_establish(
    member: DriveWithheld,
) -> None:
    """§7's bar, over the rendered sentences as absences.

    "**No statement says that the step would have succeeded, that the effect did not
    happen, that no step of this plan was ever started, or why a store refused** — what
    each asserts is what this turn did, which is the only thing the read establishes."

    **And the member names *where the goal stands*, never *why the step was not
    claimed***: one ``ClaimRefused`` covers both liveness raisers and the read cannot
    establish which fired, so a sentence naming a conjunct, a store, a transition or a
    version would be naming something nothing established. ADR-0242 §9's own bar carries
    the rest — no identifier, no figure, no ``Settings`` name.
    """
    said = _said(member)

    assert _GOAL_ID not in said
    assert not any(character.isdigit() for character in said), member
    for barred in (
        "would have",
        "did not happen",
        "never started",
        "refused",
        "because",
        "conjunct",
        "store",
        "version",
        "transition",
        "claim",
        "step",
    ):
        assert barred not in said.lower(), (member, barred)


@pytest.mark.parametrize("member", list(DriveWithheld))
def test_only_the_two_statements_the_adr_fixes_name_the_listing(member: DriveWithheld) -> None:
    """§7's fixed half: ``GOAL_BLOCKED`` and ``ATTEMPT_PAUSED`` name ``assistant goals``.

    Each is a statement about a goal that is **still open** — ADR-0250 §1 rules
    ``BLOCKED`` open, and a paused goal is waiting on the user — so what the user needs is
    where to read what it is waiting on. The other five name no act at all: there is none
    that helps, and naming one that cannot help is worse than naming none
    (``_render_forecast_not_read``'s own clause one vocabulary over).

    **And none of the seven names a command that would be wrong**, which is the arm a
    "names something" test leaves open: a statement pointing at ``assistant resume`` would
    send a user to an act no member of this vocabulary admits.
    """
    said = _said(member)

    assert ("assistant goals" in said) is (member in _NAMES_THE_LISTING), member
    for barred in (
        "assistant resume",
        "assistant ask",
        "assistant abandon-goal",
        "assistant cancel-read",
    ):
        assert barred not in said, (member, barred)


def test_neither_goal_blocked_nor_attempt_ended_says_the_goal_is_closed() -> None:
    """§7: "``GOAL_BLOCKED`` and ``ATTEMPT_ENDED`` therefore say what is true of each and
    never that the goal is closed or cancelled."

    ADR-0250 §1 rules ``BLOCKED`` **open**, and ADR-0249 §4 that "an attempt reaching a
    terminal state **does not** move the goal's status" — so a sentence saying the goal
    was given up would be false of both. ``ATTEMPT_CANCELLED`` is the sharper case and is
    asserted with them: §7 reaches it "on a goal ADR-0250 §13 has **reopened**", so saying
    the goal was cancelled there "would say the goal was given up when the user has just
    taken it up again".
    """
    for member in (
        DriveWithheld.GOAL_BLOCKED,
        DriveWithheld.ATTEMPT_ENDED,
        DriveWithheld.ATTEMPT_CANCELLED,
    ):
        said = _said(member).lower()
        assert "given up" not in said, member
        assert "cancelled" not in said, member
        assert "abandoned" not in said, member


# --- ADR-0242 §9: beside the reply, and the notice it must not sit above -----


async def test_the_statement_is_rendered_beside_the_reply_and_not_in_place_of_it(
    output: StringIO,
) -> None:
    """ADR-0242 §9, as §7 inherits it: "beside the reply and never in place of it".

    The reply the turn composed is still on the screen above the statement, which is the
    half a renderer that replaced the panel would pass a substring assertion on.
    """
    base = await _composed()
    cli._render_turn(
        base.model_copy(
            update={
                "reply": "Here is where that got to.",
                "drive_withheld": DriveWithheld.GOAL_CANCELLED,
            }
        )
    )

    screen = _flat(output.getvalue())
    assert "Here is where that got to." in screen
    assert _STATEMENTS[DriveWithheld.GOAL_CANCELLED] in screen
    assert screen.index("Here is where that got to.") < screen.index(
        _STATEMENTS[DriveWithheld.GOAL_CANCELLED]
    )


@pytest.mark.parametrize("member", list(DriveWithheld))
async def test_no_action_was_needed_is_not_shown_beside_a_withheld_drive(
    member: DriveWithheld, output: StringIO
) -> None:
    """The contradiction on one screen, at this vocabulary.

    "No action was needed." one line from "That goal was cancelled, and this turn did
    nothing further for it." says both that nothing was owed and that a step this turn was
    driving was not claimed. The guard is on the member's **presence** and on all seven,
    which is ``forecast_not_read``'s term rather than ``attempt_report``'s: ``OutboundReach``
    and ``AttemptOutcome`` each have a member for having attempted nothing and
    ``DriveWithheld`` has none.

    **The shape is one this surface is *handed* rather than one a conforming hub
    composes**, which is stated rather than hidden: §7's refusal comes from a claim on a
    step of the plan this outcome carries, so a conforming turn has a non-empty plan and
    the enclosing test already fails. The outcome crosses a frame, so what the guard
    protects is the value, exactly as it does on the browser.
    """
    base = await _composed()
    assert base.turn is not None
    assert not base.turn.plan.steps, "the arm is about a turn the surface is handed"

    cli._render_turn(base.model_copy(update={"drive_withheld": member}))

    screen = _flat(output.getvalue())
    assert "No action was needed." not in screen, member
    assert _STATEMENTS[member] in screen, member


async def test_no_action_was_needed_is_still_shown_where_no_drive_was_withheld(
    output: StringIO,
) -> None:
    """The control the arm above needs to mean anything: a guard that suppressed the
    notice unconditionally would pass every case there and would have taken a true line
    off every ordinary turn."""
    cli._render_turn(await _composed())

    assert "No action was needed." in _flat(output.getvalue())


# --- end to end, over the canonical fake's own lever -------------------------


def test_the_statement_reaches_a_user_driving_assistant_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole path, from the member the engine carries to the bytes on the terminal.

    This is the one thing the unit arms above cannot show: that ``ask`` reaches
    :func:`cli._render_drive_withheld` at all. ``FakeAssistantEngine`` gained
    :attr:`~ai_assistant.testing.FakeAssistantEngine.drive_withheld` for it — a withheld
    drive needs a ``PlanStore`` to refuse a ``→ RUNNING`` claim on a liveness conjunct,
    which that double never takes, so every one of the seven would otherwise be
    unreachable from a consumer's test.
    """
    engine = FakeAssistantEngine()
    engine.drive_withheld = DriveWithheld.ATTEMPT_PAUSED
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["ask", "book the flight", "--yes"])

    assert result.exit_code == 0
    assert _STATEMENTS[DriveWithheld.ATTEMPT_PAUSED] in _flat(result.output)


def test_a_default_fake_turn_says_nothing_about_a_withheld_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And the default reaches the same screen as silence, which §7 fixes the meaning of.

    A fake takes no ``→ RUNNING`` claim and so meets no ``ClaimRefused``, which is exactly
    the state ``None`` names — so a turn composed under it says nothing about a withheld
    drive at all.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["ask", "book the flight", "--yes"])
    screen = _flat(result.output)

    assert result.exit_code == 0
    for statement in _STATEMENTS.values():
        assert statement not in screen


# --- ADR-0261 §6: the listing row --------------------------------------------


def test_a_goal_with_an_outstanding_action_says_so_in_the_listing(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§6: "for a listing row whose ``effect_in_flight`` is true, that an action of this
    goal **is outstanding — claimed, possibly sent, outcome unknown**".

    **And the listing carries it because the act's answer is heard once.** A user who
    comes back tomorrow asking "did that booking go through?" reads ``assistant goals``,
    "and a listing showing an ``ABANDONED`` goal with nothing beside it would have lost
    the fact R78 requires".
    """
    engine = FakeAssistantEngine()
    engine.goal_summaries = [_goal(effect_in_flight=True)]
    _wire(monkeypatch, engine)

    code = CliRunner().invoke(cli.app, ["goals"]).exit_code

    screen = _flat(output.getvalue())
    assert code == 0
    assert cli._EFFECT_IN_FLIGHT in screen


def test_a_goal_with_nothing_outstanding_says_nothing_about_one(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """The control: **false** is the ordinary state and the row is silent there.

    §6 makes the cleared field "deliberately indistinguishable from a goal that claimed
    nothing" — "what the effect *did* is held by the step's own status" and naming that
    disposition to the user "is #2397's and not this field's" — so a row rendering
    anything at all on a false field would be minting the vocabulary this decision does
    not mint.
    """
    engine = FakeAssistantEngine()
    engine.goal_summaries = [_goal(effect_in_flight=False)]
    _wire(monkeypatch, engine)

    CliRunner().invoke(cli.app, ["goals"])

    screen = _flat(output.getvalue())
    assert "outstanding" not in screen.lower()
    assert cli._EFFECT_IN_FLIGHT not in screen


def test_the_row_asserts_no_outcome_and_names_no_call() -> None:
    """§6's bar, over the sentence itself.

    "**No statement says that the action did not happen, that it did, or that anything
    the user does will withdraw it.**" And *in flight* "means the claim landed, never that
    the call left": the field is true where a step stands ``INDETERMINATE`` or ``RUNNING``
    and asserts nothing about whether ``ToolInvoker.invoke`` was entered, so "may have
    been sent" is the strongest thing the sentence is allowed to say.

    **And it names no effect key**, because §6 makes *outstanding* "the step's status and
    never the presence of an effect key" and includes a **read** deliberately: "the word
    *effect* in both names is R78's and not ADR-0259 §1's, so neither name asserts that an
    ``EffectKey`` exists".
    """
    said = cli._EFFECT_IN_FLIGHT

    assert "claimed" in said
    assert "may have been sent" in said
    assert "not known" in said
    for barred in ("did not", "was sent", "will be", "withdraw", "undo", "cancel", "key", "tool"):
        assert barred not in said.lower(), barred


def test_the_row_and_the_act_are_two_instants_and_the_listing_is_not_guarded_on_the_act(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§14 arm 10's last clause, at this surface: "**No arm asserts that the two agree
    across two instants.**"

    §6 rules that the act's answer and the listing's field "are the same predicate over
    the same scope, read at two instants: they cannot disagree **about one instant**, and
    are never required to agree across two" — so a row reading **false** beside a goal an
    act answered ``ABANDONED_EFFECT_IN_FLIGHT`` for is "the accurate answer to a different
    question". This surface therefore renders the boolean it was handed and takes no
    second read: a listing that reconciled itself against a remembered answer would be the
    durable record §6 forbids anything from making.
    """
    engine = FakeAssistantEngine()
    engine.abandonment = GoalAbandonment.ABANDONED_EFFECT_IN_FLIGHT
    engine.goal_summaries = [_goal(effect_in_flight=False, status=GoalStatus.ABANDONED)]
    _wire(monkeypatch, engine)

    CliRunner().invoke(cli.app, ["abandon-goal", _GOAL_ID])
    output.truncate(0)
    output.seek(0)
    CliRunner().invoke(cli.app, ["goals"])

    assert cli._EFFECT_IN_FLIGHT not in _flat(output.getvalue())


# --- ADR-0261 §14 arm 10: the abandonment statement, by its facts ------------


def test_the_abandonment_says_the_action_was_claimed_and_may_have_been_sent(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§14 arm 10: "**the rendering is asserted by its facts rather than its prose**".

    A zero exit over the ordinary ``ABANDONED`` text "would pass an exit-code arm alone",
    so the arm names the two facts §6 fixes: "the abandonment surface says that an action
    **was claimed and may have been sent** and names **``assistant goals``**".

    **And it asserts no outcome** (§6): not that the action did not happen, not that it
    did, and not that anything the user does will withdraw it.
    """
    engine = FakeAssistantEngine()
    engine.abandonment = GoalAbandonment.ABANDONED_EFFECT_IN_FLIGHT
    _wire(monkeypatch, engine)

    CliRunner().invoke(cli.app, ["abandon-goal", _GOAL_ID])

    screen = _flat(output.getvalue())
    assert "claimed" in screen
    assert "may have been sent" in screen
    assert "assistant goals" in screen
    for barred in ("did not happen", "will be undone", "withdraw", "reversed by you"):
        assert barred not in screen.lower(), barred


def test_the_ordinary_abandonment_says_nothing_about_an_outstanding_action(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """The control the arm above needs: ``ABANDONED`` is the member that reports none.

    §6 returns ``ABANDONED_EFFECT_IN_FLIGHT`` "exactly where ``close_goal_abandoned``
    answers true" and ``ABANDONED`` "in every other abandoning case", so a statement that
    mentioned a claimed action on both would report an effect over a goal that had none.
    """
    engine = FakeAssistantEngine()
    engine.abandonment = GoalAbandonment.ABANDONED
    _wire(monkeypatch, engine)

    CliRunner().invoke(cli.app, ["abandon-goal", _GOAL_ID])

    screen = _flat(output.getvalue()).lower()
    assert "claimed" not in screen
    assert "may have been sent" not in screen


# --- ADR-0262 §11's parity point, at ADR-0261's three vocabularies -----------


def test_the_two_surfaces_render_the_same_withheld_sentence_for_the_same_member() -> None:
    """§7 leaves the wording to the lane and fixes which fact each names, so a parity arm
    could assert the fixed half alone.

    This lane writes the two surfaces' prose byte for byte identically instead, so the arm
    asserts the **equality**: a member whose sentence is edited on one surface and not the
    other fails here. ADR-0262 §11 is the reason it is worth having — "a member rendered
    on one and not the other is the parity failure M4 recorded".

    The browser's seven are read out of the shipped bundle, which is where that surface's
    obligation is discharged.
    """
    browser = _browser_map("DRIVE_WITHHELD_WORDS")

    assert set(browser) == {member.value for member in DriveWithheld}
    for member, statement in _STATEMENTS.items():
        assert browser[member.value] == statement, member
        assert _said(member) == statement, member


def test_the_two_surfaces_render_the_same_listing_row() -> None:
    """The same equality one fact over, at §6's listing statement.

    §6 fixes only which fact the row names; this lane writes one sentence and both
    surfaces render it, so an edit to either fails here.
    """
    assert _browser_constant("EFFECT_IN_FLIGHT") == cli._EFFECT_IN_FLIGHT


def test_the_browser_refuses_a_value_outside_the_seven_without_putting_it_on_screen() -> None:
    """What a surface does with a value that is **not** one of the seven.

    §7 closes the vocabulary, so the terminal's ``match`` is exhaustive and a value outside
    it cannot be constructed there. The browser has no such guarantee — the member arrives
    over a frame as a string — so it says what is known and no more, which is
    ``ATTEMPT_REPORT_UNREADABLE``'s ratified position one vocabulary over: not a bare
    identifier, and not silence.
    """
    said = _browser_constant("DRIVE_WITHHELD_UNREADABLE")

    assert said.strip()
    for member in DriveWithheld:
        assert member.value not in said, member
    for barred in ("refused", "failed", "error", "cancelled", "claim"):
        assert barred not in said.lower(), barred
