"""The terminal's statement about what this turn's attempt produced (ADR-0262 §6).

§11's **L5**: "§6's six fixed statements, on the CLI and on the browser — **both
surfaces**, since a member rendered on one and not the other is the parity failure M4
recorded. **Thin, by golden rule 3**: it renders values L4 computed and derives none."

**Every case asserts over the rendered bytes**, because §6's obligation is discharged in
what the user reads and nowhere else — ``test_cli_forecast_statements.py``'s own clause
one vocabulary over: a statement that only exists in a helper's return value is a
statement no user was ever told.

**And the parity arm is here rather than in either surface's own module**, because what
it is about is the pair. This lane writes the two surfaces' prose byte for byte
identically, so the arm asserts an equality rather than the fixed half alone — which is
strictly stronger than ``ForecastNotRead``'s precedent, where §10 fixed only which
command each member names.
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
    AttemptOutcome,
    AttemptReport,
    ForecastNotRead,
    TurnOutcome,
)
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine

PATIENT: Final = timedelta(seconds=30)

_AT: Final = datetime(2026, 5, 1, 9, tzinfo=UTC)

_APP_JS: Final = Path(cli.__file__).resolve().parent / "gateway" / "assets" / "app.js"

#: The six members ADR-0262 §6's report admits, and the sentence each renders as.
#:
#: **Whole sentences rather than fragments**, because this lane writes both surfaces'
#: prose and the parity arm below asserts they are the same text. §6 fixes which fact
#: each names and leaves the wording to the lane, so what is pinned here is this lane's
#: choice — and pinning it whole is what makes a later edit to one surface fail rather
#: than drift.
_STATEMENTS: Final[dict[AttemptOutcome, str]] = {
    AttemptOutcome.VERIFIED: (
        "The criteria this attempt compared were checked, and they hold. "
        "'assistant goals' is where you read how the goal stands."
    ),
    AttemptOutcome.ANSWERED: (
        "An answer was produced, and nothing was verified. Nothing here says whether it is correct."
    ),
    AttemptOutcome.PARTIAL: (
        "Part of what you asked for was established, and part of it was not established."
    ),
    AttemptOutcome.FAILED: "The work failed, and no criterion of this goal was established.",
    AttemptOutcome.UNCERTAIN: (
        "An action was taken, and its outcome is not established. "
        "'assistant goals' is where you read how the goal stands."
    ),
    AttemptOutcome.CONDITION_PREVENTED: "The action was prevented before it ran.",
}

#: The one member of ``AttemptOutcome`` §6's report does **not** admit.
#:
#: §4 is explicit that ``CANCELLED`` "is reached by no limb" of the comparison, so no
#: conforming engine puts one on a report — but the **type admits it**, which
#: ``FakeAssistantEngine`` states in terms while refusing the *arrangement*: "narrowing it
#: here would be this fake policing a value ADR-0261 owns — which is why the refusal is on
#: the *arrangement* and not on :class:`AttemptReport`". So a hub at another version can
#: put one on this screen and this surface decides what a user then reads.
_NOT_A_REPORT_MEMBER: Final = AttemptOutcome.CANCELLED

#: The two members whose statement is compatible with a turn that needed no step.
#:
#: The partition the "No action was needed." guard is written over: ``VERIFIED`` says
#: criteria were checked and hold, ``ANSWERED`` says an answer was produced and nothing
#: was verified, and §12's first arm is exactly a turn of the second kind.
_COMPATIBLE_WITH_NO_ACTION: Final = frozenset({AttemptOutcome.VERIFIED, AttemptOutcome.ANSWERED})


def _flat(rendered: str) -> str:
    """Collapse Rich's wrapping and its continuation marker (#2072).

    :func:`cli._print` writes a ``↳`` onto every display line a line runs onto, so an
    assertion about words needs the marker gone as well as the break — and a command name
    is exactly the sort of string that lands on one.
    """
    return " ".join(rendered.replace("↳", " ").split())


def _said(member: AttemptOutcome, *, continues: bool = False) -> str:
    """What the terminal renders for one member, flattened."""
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=100)
    original = cli.console
    cli.console = console
    try:
        cli._render_attempt_report(AttemptReport(outcome=member, continues=continues))
    finally:
        cli.console = original
    return _flat(buffer.getvalue())


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
    """One turn that composed a reply, for an arm to copy the report onto.

    ``TurnOutcome`` refuses a reply beside a ``None`` turn, so an arm about what a
    *composed* pass renders needs a real turn behind it. The canonical fake composes one;
    what each arm replaces is the member ADR-0262 §6 makes load-bearing and nothing else.
    """
    engine = FakeAssistantEngine()
    turn = await engine.converse("book the flight", timeout=PATIENT)
    return TurnOutcome(turn=turn.turn, reply=turn.reply)


# --- §6: one statement per member, over their rendered bytes -----------------


def test_the_vocabulary_is_the_six_the_report_admits_and_one_it_does_not() -> None:
    """``AttemptOutcome`` is closed at seven and §6's report admits six of them.

    Pinned as a partition so that a member added by a later ADR fails here rather than
    reaching a user's terminal as a bare identifier — the #1113 rule at this vocabulary —
    and so that ``CANCELLED``'s exclusion stays a *decision* this module names rather than
    an omission a reader has to notice.
    """
    assert set(_STATEMENTS) | {_NOT_A_REPORT_MEMBER} == set(AttemptOutcome)
    assert _NOT_A_REPORT_MEMBER not in _STATEMENTS
    assert len(AttemptOutcome) == 7


@pytest.mark.parametrize("member", list(_STATEMENTS))
def test_every_report_member_renders_its_statement(member: AttemptOutcome) -> None:
    """§6: "one fixed statement per member, rendered beside the reply and never in place
    of it", under ADR-0242 §9's rule that a surface rendering none "has not implemented
    this section and is not a permitted degradation".
    """
    assert _said(member) == _STATEMENTS[member]


def test_no_two_members_render_the_same_statement() -> None:
    """A member rendering as another member names neither.

    §6 gives each of the six a distinct fact to name — a comparison that held, an answer
    with nothing verified, a part established and a part not, work that failed, an action
    whose outcome is not established, an action prevented before it ran — so two of them
    sharing a sentence would collapse a distinction the decision built.
    """
    said = {member: _said(member) for member in AttemptOutcome}

    assert len(set(said.values())) == len(AttemptOutcome)


def test_nothing_is_rendered_for_a_turn_that_ended_no_attempt(output: StringIO) -> None:
    """§6: the member is non-``None`` "exactly on a turn that ended an attempt under §4".

    Its absence is a turn that engaged no goal, a routed operation, ADR-0198 §1's
    restatement, every turn whose attempt stayed live — **and a turn whose
    ``commit_attempt`` was refused**, which §6 fixes as "a silence rather than a false
    claim", the composed reply standing as composed.
    """
    cli._render_attempt_report(None)

    assert output.getvalue() == ""


def test_a_member_outside_the_six_is_said_rather_than_shown_raw() -> None:
    """``CANCELLED`` is constructible in a report, and this is what a user then reads.

    The brief for this lane said ``AttemptReport``'s validator refuses the non-members.
    It does not: ``_an_unfinishable_outcome_offers_nothing_to_continue`` constrains
    ``continues`` alone, and ``FakeAssistantEngine`` says why the narrowing is not on the
    type — "narrowing it here would be this fake policing a value ADR-0261 owns". So the
    value constructs, a hub at another version can send one, and the surface decides.

    **Not a bare identifier and not silence**, which is ``FORECAST_NOT_READ_UNREADABLE``'s
    ratified position one vocabulary over — and **not a seventh fixed statement**, because
    §6 fixes six and minting one for a member it excludes would be this surface deciding a
    vocabulary. A cancelled attempt is ADR-0261 §2's act, with statements of its own.
    """
    report = AttemptReport(outcome=_NOT_A_REPORT_MEMBER, continues=False)

    assert report.outcome is AttemptOutcome.CANCELLED
    said = _said(_NOT_A_REPORT_MEMBER)
    assert "no words for" in said
    assert _NOT_A_REPORT_MEMBER.value not in said
    for claimed in ("verified", "failed", "established", "prevented", "answer was produced"):
        assert claimed not in said, claimed


# --- §6's bar: no statement asserts what the record does not carry -----------


@pytest.mark.parametrize("member", list(AttemptOutcome))
def test_no_statement_names_a_criterion_a_tool_a_figure_or_a_cause(
    member: AttemptOutcome,
) -> None:
    """§6: "none names a criterion, a tool, a destination, a figure, a ``Settings`` field
    or a cause", and ADR-0242 §9's bar binds on these word for word.

    ``FAILED``'s sentence names *criteria* as a class — §6 requires it to, "no criterion
    of this goal was established" — and names none, which is what the digits, the
    quotation marks and the identifier forms below are asserted over.

    **And no member reaches a person as a bare identifier**, which is the #1113 rule at
    this vocabulary: the underscore bar catches ``condition_prevented`` whole, and the
    sentence is never *only* a member's value. The English words ``verified`` and
    ``failed`` are §6's own — "that an answer was produced and **nothing was verified**",
    "that the work failed" — so they are asserted as prose rather than barred as
    identifiers.
    """
    said = _said(member)

    assert not any(character.isdigit() for character in said)
    for forbidden in ("http", "://", "@", "$", "£", "_", '"', "`", "because", "since"):
        assert forbidden not in said.lower(), f"{member}: {forbidden}"
    assert said.strip().rstrip(".").lower() not in {one.value for one in AttemptOutcome}


@pytest.mark.parametrize("member", list(AttemptOutcome))
def test_no_statement_says_the_goal_is_closed_or_that_an_attempt_was_ended(
    member: AttemptOutcome,
) -> None:
    """§6: "**no statement of this section asserts that an attempt was ended, that a
    status was written, or that a goal is now closed**", because §1 puts the comparison
    before the composing stage and both commits after it — "a statement that could be
    falsified by a commit taken after it was composed is one this decision does not
    write".

    **And none names the goal's status.** ``GoalStatus``' four words are what a later
    commit decides, and they are read at ``assistant goals`` rather than asserted here.
    """
    said = _said(member).lower()

    for forbidden in (
        "the goal is complete",
        "the goal is done",
        "goal is closed",
        "goal is now",
        "achieved",
        "abandoned",
        "blocked",
        "active",
        "the attempt was ended",
        "this attempt has ended",
        "recorded as",
    ):
        assert forbidden not in said, f"{member}: {forbidden}"


def test_the_verified_statement_speaks_of_the_criteria_this_attempt_compared() -> None:
    """§6: "``VERIFIED``'s statement speaks of *the criteria this attempt compared*" and
    is "never a claim that the goal is closed, since a revision landing beside it leaves
    the goal open (§5)", naming ``assistant goals`` as where the goal's state is read.
    """
    said = _said(AttemptOutcome.VERIFIED)

    assert "the criteria this attempt compared" in said.lower()
    assert "they hold" in said
    assert "'assistant goals'" in said


def test_the_answered_statement_says_nothing_was_verified_and_not_that_it_is_correct() -> None:
    """§6: for ``ANSWERED``, "that an answer was produced and **nothing was verified** —
    never that it is correct". It is not a weaker ``VERIFIED`` and does not read as one.
    """
    said = _said(AttemptOutcome.ANSWERED)

    assert "an answer was produced" in said.lower()
    assert "nothing was verified" in said
    assert "is correct" in said
    assert "it is correct." not in said.replace("whether it is correct.", "")


def test_the_partial_statement_names_a_part_established_and_a_part_not() -> None:
    """§6: for ``PARTIAL``, "that part of what was asked was established and part was
    **not established**". It does not say the goal is done and it names no criterion.
    """
    said = _said(AttemptOutcome.PARTIAL)

    assert "was established" in said
    assert "not established" in said


def test_the_failed_statement_speaks_of_the_criteria_and_never_of_the_acts() -> None:
    """§6: for ``FAILED``, "that the work failed and **no criterion of this goal was
    established**" — true of both of limb 1's arms — and "**It speaks of the criteria and
    never of the acts**: where one call satisfied and another contradicted, the criterion
    is ``unmet`` and the member is ``FAILED`` though an act did take effect, so a
    statement saying *nothing was done* would be false of the record and this one is not."

    **And it does not say a criterion was disproved**, which limb 1's conjunct does not
    establish: a criterion nothing compared is unestablished, not refuted.
    """
    said = _said(AttemptOutcome.FAILED)

    assert "the work failed" in said.lower()
    assert "no criterion of this goal was established" in said
    for forbidden in (
        "nothing was done",
        "nothing happened",
        "no effect",
        "disproved",
        "was false",
        "did not happen",
    ):
        assert forbidden not in said.lower(), forbidden


def test_the_uncertain_statement_says_nothing_about_whether_the_call_left() -> None:
    """§6: for ``UNCERTAIN``, "that an action was taken and **its outcome is not
    established**", naming ``assistant goals`` — and "**``UNCERTAIN``'s says nothing about
    whether the call left**", which is ADR-0261 §6's "no caller assumes the query did not
    leave" binding on one more statement.
    """
    said = _said(AttemptOutcome.UNCERTAIN)

    assert "an action was taken" in said.lower()
    assert "its outcome is not established" in said
    assert "'assistant goals'" in said
    for forbidden in ("never left", "did not leave", "nothing was sent", "no request"):
        assert forbidden not in said.lower(), forbidden


def test_the_condition_prevented_statement_names_neither_of_the_two_sources() -> None:
    """§6: for ``CONDITION_PREVENTED``, "that the action was **prevented before it ran** —
    which covers both of ``blocked``'s sources (§4) without asserting either, since
    ``SkipReason.UNMET_DEPENDENCY`` is a stated condition that did not hold and
    ``SkipReason.APPROVAL_DENIED`` is the user's own refusal, and since a read may well
    have succeeded first".
    """
    said = _said(AttemptOutcome.CONDITION_PREVENTED)

    assert "prevented before it ran" in said
    for forbidden in (
        "you declined",
        "you refused",
        "approval",
        "dependency",
        "condition was not met",
        "nothing ran",
        "nothing happened",
    ):
        assert forbidden not in said.lower(), forbidden


@pytest.mark.parametrize("member", list(AttemptOutcome))
@pytest.mark.parametrize("continues", [False, True], ids=["settled", "continues"])
def test_no_statement_carries_the_offer_and_continues_changes_none_of_them(
    member: AttemptOutcome, continues: bool
) -> None:
    """§6: "**The offer is in the reply rather than on the surface**" — "an offer a surface
    printed would reach neither the browser's transcript nor the spoken channel as part of
    what was said. So the **reply** carries the offer and the **surface** the outcome
    word."

    So ``continues`` is rendered by neither surface, and the statement for a member is the
    same text whichever value it carries. A second offer printed here would also be this
    file composing a reply, which golden rule 3 refuses.

    ``continues`` is ``True`` only where §6 admits it — the validator refuses ``True``
    beside ``VERIFIED``, ``ANSWERED`` and ``CONDITION_PREVENTED`` — so the ``True`` leg is
    skipped for those three rather than asserted against a value nobody can build.
    """
    if continues and member in {
        AttemptOutcome.VERIFIED,
        AttemptOutcome.ANSWERED,
        AttemptOutcome.CONDITION_PREVENTED,
    }:
        pytest.skip("§6 fixes continues False on these three and the validator refuses True")
    said = _said(member, continues=continues)

    assert said == _said(member, continues=False)
    for offer in ("shall i", "would you like", "try again", "take it further", "continue"):
        assert offer not in said.lower(), f"{member}: {offer}"


# --- §6's placement: beside the reply and never in place of it ---------------


async def test_the_statement_stands_beside_the_reply_and_never_in_place_of_it(
    output: StringIO,
) -> None:
    """§6: "one fixed statement per member, rendered **beside the reply and never in place
    of it**".

    Driven through the production :func:`cli._render_turn`, so what is asserted is the
    order a user actually reads rather than a call this module made itself.
    """
    reply = "I could not finish that one."
    base = await _composed()
    cli._render_turn(
        base.model_copy(
            update={
                "reply": reply,
                "attempt_report": AttemptReport(outcome=AttemptOutcome.PARTIAL, continues=True),
            }
        )
    )
    rendered = _flat(output.getvalue())

    assert reply in rendered
    assert rendered.index(reply) < rendered.index(_STATEMENTS[AttemptOutcome.PARTIAL])


async def test_a_forecast_statement_and_an_attempt_statement_ride_together(
    output: StringIO,
) -> None:
    """Two vocabularies, each saying only what its own servicing established.

    ADR-0262 §6 makes the report a member of its own rather than a case of any other, and
    ADR-0250 §5's rule that "no lane derives either from the other or collapses them" is
    the same discipline one member over. A turn that asked for a forecast it did not get
    and then ended its attempt carries both, and neither is suppressed on account of the
    other.
    """
    base = await _composed()
    cli._render_turn(
        base.model_copy(
            update={
                "forecast_not_read": ForecastNotRead.DECLINED,
                "attempt_report": AttemptReport(outcome=AttemptOutcome.UNCERTAIN, continues=True),
            }
        )
    )
    rendered = _flat(output.getvalue())

    assert "that forecast read was declined when it was ruled on" in rendered
    assert _STATEMENTS[AttemptOutcome.UNCERTAIN] in rendered


@pytest.mark.parametrize(
    "member", [one for one in AttemptOutcome if one not in _COMPATIBLE_WITH_NO_ACTION]
)
async def test_no_action_was_needed_is_not_printed_beside_a_statement_asserting_work(
    member: AttemptOutcome, output: StringIO
) -> None:
    """The contradiction on one screen, at this vocabulary.

    The comparison runs after the plan, so a turn that planned nothing still ends an
    attempt and still carries a report: limb 1's first arm is an established contradiction
    read off the goal's own earlier records, which needs no step of *this* turn. "No action
    was needed." one line from "The work failed, and no criterion of this goal was
    established." says both that nothing was owed and that work was attempted and did not
    complete — which is the pairing ``_render_turn``'s guard exists to prevent, and one
    **this lane would otherwise have created**.

    ``CANCELLED`` is in this arm because its statement is the unreadable one, which asserts
    nothing about what was attempted — so the notice is *not* suppressed there and this
    case asserts exactly that.
    """
    base = await _composed()
    assert base.turn is not None
    assert not base.turn.plan.steps, "the arm is about a turn that planned nothing"
    cli._render_turn(
        base.model_copy(update={"attempt_report": AttemptReport(outcome=member, continues=False)})
    )
    rendered = _flat(output.getvalue())

    suppressed = member is not _NOT_A_REPORT_MEMBER
    assert ("No action was needed." not in rendered) is suppressed, member
    assert _said(member) in rendered, member


@pytest.mark.parametrize("member", sorted(_COMPATIBLE_WITH_NO_ACTION))
async def test_no_action_was_needed_still_prints_beside_the_two_that_admit_it(
    member: AttemptOutcome, output: StringIO
) -> None:
    """The control the arm above needs to mean anything, and the reason the guard is on
    four members rather than on the report's presence.

    §6 fixes ``VERIFIED``'s statement as one about criteria that were checked and hold and
    ``ANSWERED``'s as "an answer was produced and **nothing was verified**", neither of
    which says a step was owed — and ADR-0262 §12's **first** arm is exactly a turn of the
    second kind: "what is two plus two?", one composing call, no step claimed, the attempt
    ending ``ANSWERED``. A guard on the member's presence would have taken a true line off
    every ordinary attempt-ending turn.
    """
    base = await _composed()
    cli._render_turn(
        base.model_copy(update={"attempt_report": AttemptReport(outcome=member, continues=False)})
    )
    rendered = _flat(output.getvalue())

    assert "No action was needed." in rendered, member
    assert _said(member) in rendered, member


# --- end to end, over the canonical fake's own lever -------------------------


def test_the_statement_reaches_a_user_driving_assistant_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole path, from the member the engine carries to the bytes on the terminal.

    This is the one thing the unit arms above cannot show: that ``ask`` reaches
    :func:`cli._render_attempt_report` at all. ``FakeAssistantEngine`` gained
    :attr:`~ai_assistant.testing.FakeAssistantEngine.attempt_report` for it (#2456) — no
    sequence of surface calls on that double runs a comparison, so every one of the six
    would otherwise be unreachable from a consumer's test.
    """
    engine = FakeAssistantEngine()
    engine.attempt_report = AttemptReport(outcome=AttemptOutcome.FAILED, continues=True)
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["ask", "book the flight", "--yes"])
    rendered = _flat(result.output)

    assert result.exit_code == 0
    assert _STATEMENTS[AttemptOutcome.FAILED] in rendered


def test_a_default_fake_turn_says_nothing_about_an_attempt_driving_assistant_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And the default reaches the same screen as silence, which §6 fixes the meaning of.

    The member is non-``None`` "exactly on a turn that ended an attempt under §4". A fake
    with no report scripted ended none, so a turn composed under it says nothing about an
    attempt to the user.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["ask", "book the flight", "--yes"])
    rendered = _flat(result.output)

    assert result.exit_code == 0
    for member in AttemptOutcome:
        assert _said(member) not in rendered, member


# --- ADR-0262 §11's parity point, over the two surfaces' own words -----------


def test_the_two_surfaces_render_the_same_sentence_for_the_same_member() -> None:
    """ADR-0262 §11: "both surfaces, since a member rendered on one and not the other is
    the parity failure M4 recorded."

    §6 leaves the wording to the lane and fixes which fact each names, so a parity arm
    could assert the fixed half alone — which is what ``ForecastNotRead``'s precedent
    does. This lane writes the two surfaces' prose byte for byte identically instead, so
    the arm asserts the **equality**: a member whose sentence is edited on one surface and
    not the other fails here, which is strictly more than the fixed half would catch.

    The browser's six are read out of the shipped bundle, which is where that surface's
    obligation is discharged.
    """
    script = _APP_JS.read_text(encoding="utf-8")
    opened = script.index("\nconst ATTEMPT_OUTCOME_WORDS = {")
    block = script[opened : script.index("\n};", opened)]
    parts = re.split(r"^  (\w+):", block, flags=re.MULTILINE)
    browser = {
        parts[index]: "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', parts[index + 1]))
        for index in range(1, len(parts), 2)
    }

    assert set(browser) == {member.value for member in _STATEMENTS}
    for member, statement in _STATEMENTS.items():
        assert browser[member.value] == statement, member
        assert _said(member) == statement, member


def test_neither_surface_renders_a_seventh_statement_and_both_refuse_the_same_way() -> None:
    """The member outside the six reaches the same refusal on both surfaces.

    §6's all-or-nothing rule is about the six it fixes; what a surface does with a value
    that is not one of them is the surface's, and doing it differently on the two is the
    parity failure §11 names one value over. Both say they have no words for it, and
    neither puts the identifier on the screen.
    """
    script = _APP_JS.read_text(encoding="utf-8")
    opened = script.index("\nconst ATTEMPT_REPORT_UNREADABLE =")
    browser = "".join(
        re.findall(r'"((?:[^"\\]|\\.)*)"', script[opened : script.index(";\n", opened)])
    )

    assert browser == _said(_NOT_A_REPORT_MEMBER)
    assert _NOT_A_REPORT_MEMBER.value not in browser
