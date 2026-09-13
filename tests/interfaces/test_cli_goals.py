"""The command line's goal surface, clause by clause (ADR-0250 §19's M4).

§15 places this surface by name — "the command line and the browser both implement
this decision. Each renders a raised clarification in the exchange that raised it,
lists outstanding goals and their questions, carries an answer with its reference, and
offers the withdrawal and the abandonment acts" — so every case here asserts over the
**rendered bytes**, which is ADR-0242 §15's last clause one decision over: those are the
system's own words.

**Driven against the canonical fake, at the seam each obligation is about.** A goal
listing, a withdrawal and an abandonment are each one relayed call, and a turn's four
members are values the fake hands back — so the arms are stated over inputs and what is
observably rendered, never over an implementation's internals.

**This is not ``test_cli.py``'s deferred-question surface** and the separation is
ADR-0250 §15's own: ``assistant questions`` and ``assistant answer`` are ADR-0078 §8's
memory questions — *may I believe this about you*, answered yes or no — and a goal's
clarification asks *which of two things did you mean* and is answered in words. §15
forbids the two "in the same list, the same command or the same vocabulary", and
``test_the_two_question_surfaces_share_no_list_no_command_and_no_vocabulary`` is §20's
arm 30 at this surface.
"""

from __future__ import annotations

import asyncio
import re
import shlex
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import TYPE_CHECKING, Final

import pytest
import typer
from rich.console import Console
from typer.core import TyperGroup
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
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
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from ai_assistant.core.types import TurnResult

#: The ids every case uses. They are deliberately unmistakable runs of characters: the
#: no-identifier arm asserts their **absence** from every rendered statement, and an id
#: that could be a fragment of ordinary prose would make that assertion vacuous.
GOAL_ID: Final = "goal-zzqq-7741"
QUESTION_ID: Final = "question-xxpp-9930"

#: The goal's own outcome statement. It is the one piece of goal content a surface may
#: render, and it carries punctuation and a capital so a surface that re-cased or
#: re-wrapped it would be caught.
OUTCOME: Final = "Book the usual campsite for the last weekend of August."

QUESTION: Final = "Which campsite do you mean — Ericeira or Melides?"

AT: Final = datetime(2026, 1, 1, 11, tzinfo=UTC)
DEADLINE: Final = datetime(2026, 1, 8, 11, tzinfo=UTC)


def _clarification() -> Clarification:
    """The open question a paused goal is waiting on (ADR-0250 §10)."""
    return Clarification(question_id=QUESTION_ID, text=QUESTION, expires_at=DEADLINE)


def _summary(
    *,
    status: GoalStatus = GoalStatus.ACTIVE,
    paused: bool = True,
    engaged: datetime | None = AT,
    asking: bool = True,
) -> GoalSummary:
    """One goal as ``goals`` answers it (ADR-0250 §15)."""
    return GoalSummary(
        id=GOAL_ID,
        outcome=OUTCOME,
        status=status,
        paused=paused,
        last_engaged_at=engaged,
        clarification=_clarification() if asking else None,
    )


def _listing(*summaries: GoalSummary) -> FakeAssistantEngine:
    """A fake whose ``goals`` answers exactly these."""
    engine = FakeAssistantEngine()
    engine.goal_summaries = list(summaries)
    return engine


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer wide enough that nothing wraps."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=400))
    return buffer


def _flat(rendered: str) -> str:
    """Collapse Rich's wrapping and its continuation marker, so a case asserts words."""
    return " ".join(rendered.replace("↳", " ").split())


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object) -> None:
    """Point the commands' startup at ``engine`` (ADR-0084 §6's seam)."""

    async def _open() -> object:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)


_SGR = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _help_text(rendered: str) -> str:
    """Help output as flowing words: no colour, no borders, no wrapping."""
    return " ".join(
        _SGR.sub("", rendered).replace("│", " ").replace("*", "").replace("`", "").split()
    )


async def _composed() -> TurnResult:
    """One real ``TurnResult``, built through the fake's own ``converse``.

    ``TurnOutcome`` refuses a clarification, and most replies, on a pass that produced no
    ``TurnResult`` — so an arm about what a **composed** turn renders needs a real one
    behind it rather than a stub, which would exercise a shape the type does not admit.
    """
    engine = FakeAssistantEngine()
    outcome = await engine.converse("book the usual campsite", timeout=timedelta(seconds=5))
    assert outcome.turn is not None
    return outcome.turn


TURN: Final = asyncio.run(_composed())


def _engagement(
    disposition: EngagementDisposition,
    *,
    revised: bool = False,
    added: tuple[str, ...] = (),
    removed: tuple[str, ...] = (),
) -> GoalEngagement:
    """What one turn did with the goal it engaged (ADR-0250 §5)."""
    return GoalEngagement(
        disposition=disposition,
        outcome=OUTCOME,
        revised=revised,
        outcome_changed=revised and bool(added or removed),
        added=added,
        removed=removed,
    )


def _engaged(
    disposition: EngagementDisposition,
    *,
    revised: bool = False,
    added: tuple[str, ...] = (),
    removed: tuple[str, ...] = (),
) -> TurnOutcome:
    """One composed turn carrying an engagement (ADR-0250 §5)."""
    return TurnOutcome(
        turn=TURN,
        conversation_id="c-1",
        reply="Booked nothing yet.",
        goal_engagement=_engagement(disposition, revised=revised, added=added, removed=removed),
    )


def _drive(monkeypatch: pytest.MonkeyPatch, outcome: TurnOutcome, argv: list[str]) -> None:
    """Run one turn whose outcome is scripted, through the ordinary ``ask`` path."""
    engine = FakeAssistantEngine()
    engine.turn_outcome = outcome
    _wire(monkeypatch, engine)
    assert CliRunner().invoke(cli.app, argv).exit_code == 0


# --- the listing (ADR-0250 §15), which is #2286's surface --------------------


def test_the_listing_shows_what_is_outstanding_with_its_state_and_its_question(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §15's listing, and the surface #2286 says did not exist.

    #2286 (M31's QA) found the goal continuity record readable from no surface at all.
    This is that surface: every field ``GoalSummary`` carries reaches the screen — the
    outcome statement, the status, whether it is waiting on the owner, when it was last
    taken up, and the open question with its deadline.

    **Paused and open are two facts and are shown as two.** A goal can be open and
    running, open and waiting, or closed, and collapsing the pair would lose exactly the
    state this listing exists to make visible.
    """
    _wire(monkeypatch, _listing(_summary()))

    assert CliRunner().invoke(cli.app, ["goals"]).exit_code == 0

    screen = _flat(output.getvalue())
    assert OUTCOME in screen
    assert "open — waiting on you" in screen
    assert "Last taken up: 2026-01-01 11:00 UTC" in screen
    assert QUESTION in screen
    assert "Answerable until 2026-01-08 11:00 UTC" in screen


def test_the_listing_renders_the_two_ids_its_acts_take_and_no_other(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §15's own exception, stated as the rule rather than as a lapse.

    "The question id is rendered because the act takes it, and that is the tree's own
    pattern rather than an exception carved here" — ADR-0078 §8's ``Question.id`` being
    the precedent — and the alternative it refuses by name is "a re-minted opaque
    handle", which "is ADR-0052 §1's machinery bought for a record that is already
    durable". The goal id is on the same footing: §13 performs the cross-conversation
    resumption by a ``TurnReference`` carrying one, "performed from a surface listing
    the user was shown (§15)".

    So both ids are on the screen **and each is rendered beside the command that takes
    it**, which is what makes them handles rather than internals on display.
    """
    _wire(monkeypatch, _listing(_summary()))

    assert CliRunner().invoke(cli.app, ["goals"]).exit_code == 0

    screen = _flat(output.getvalue())
    assert f"--goal {GOAL_ID}" in screen
    assert f"assistant abandon-goal {GOAL_ID}" in screen
    assert f"--answering {QUESTION_ID}" in screen
    assert f"assistant withdraw-clarification {QUESTION_ID}" in screen
    # **And neither id appears anywhere else**, which is what makes them handles rather
    # than internals on display: the outcome statement heads the row, and an id printed
    # as a heading would be lossy for exactly the values the acts most need (round 7).
    assert screen.count(GOAL_ID) == 2
    assert screen.count(QUESTION_ID) == 2


@pytest.mark.parametrize(
    ("question_id", "argument"),
    [
        ("q 1", "'q 1'"),
        ("it's-mine", "'it'\"'\"'s-mine'"),
        ("q;rm -rf /", "'q;rm -rf /'"),
    ],
)
def test_a_command_this_listing_offers_parses_back_to_the_id_it_names(
    monkeypatch: pytest.MonkeyPatch, output: StringIO, question_id: str, argument: str
) -> None:
    """#984's clause on this listing's two commands.

    ``Identifier`` requires encodability and nothing more, so an interior space is
    admissible — and a line rendered without quoting is then a *valid* command against
    the wrong argument: ``--answering q 1`` names ``q``. Adversarial review, round 6,
    ``major``.

    Asserted by **parsing the rendered line the way a shell would** rather than by
    looking for quotes, which is the only form that says the paste works.
    """
    _wire(
        monkeypatch,
        _listing(
            _summary().model_copy(
                update={
                    "clarification": _clarification().model_copy(
                        update={"question_id": question_id}
                    )
                }
            )
        ),
    )

    assert CliRunner().invoke(cli.app, ["goals"]).exit_code == 0

    screen = _flat(output.getvalue())
    assert f"--answering {argument}" in screen
    assert f"assistant withdraw-clarification {argument}" in screen
    answering = shlex.split(screen[screen.index("--answering") :].split("Or take it back")[0])
    assert answering == ["--answering", question_id]


def test_an_id_this_terminal_cannot_show_withholds_the_command_and_not_the_act(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """#1013's clause on the same two commands.

    ``_safe`` **replaces** a character a terminal must not be handed, so a value carrying
    one renders — inside perfectly correct shell quotes — as a command naming something
    that does not exist: the failure quoting was added to prevent, arriving one step
    later and looking like a working instruction. ``"q\x1b[2J1"`` is an admissible
    ``Identifier``.

    **What is withheld is the copyable line and never the act**: both commands are still
    named, and each still takes the value from anything that can carry the exact bytes.
    """
    _wire(
        monkeypatch,
        _listing(
            _summary().model_copy(
                update={
                    "clarification": _clarification().model_copy(
                        update={"question_id": "q\x1b[2J1"}
                    )
                }
            )
        ),
    )

    assert CliRunner().invoke(cli.app, ["goals"]).exit_code == 0

    screen = _flat(output.getvalue())
    assert "no command here to copy" in screen
    assert "assistant withdraw-clarification" in screen
    assert "--answering" in screen
    assert "\x1b" not in screen


def test_the_commands_this_listing_offers_are_never_folded_into_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1023's clause on the same two commands.

    Rich wraps by inserting a **real newline**, so a hint wider than the console arrives
    as two lines and pastes as two commands — ``assistant withdraw-clarification`` with
    no argument, and then the argument as a command of its own. ``_print_hint`` emits the
    line as it stands and lets the terminal fold it, which keeps it one line to anything
    that copies it. No field a hint carries has a length limit, so the trigger is a long
    id plus a narrow terminal.
    """
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=30))
    long_id = "q" * 120
    _wire(
        monkeypatch,
        _listing(
            _summary().model_copy(
                update={
                    "clarification": _clarification().model_copy(update={"question_id": long_id})
                }
            )
        ),
    )

    assert CliRunner().invoke(cli.app, ["goals"]).exit_code == 0

    lines = buffer.getvalue().splitlines()
    assert any(f"assistant withdraw-clarification {long_id}" in line for line in lines)
    assert any(f"--answering {long_id}" in line for line in lines)


@pytest.mark.parametrize(
    ("goal_id", "argument"),
    [("g 1", "'g 1'"), ("g;rm -rf /", "'g;rm -rf /'"), ("it's-mine", "'it'\"'\"'s-mine'")],
)
def test_the_resume_command_parses_back_to_the_goal_it_names(
    monkeypatch: pytest.MonkeyPatch, output: StringIO, goal_id: str, argument: str
) -> None:
    """Round 6's clause on the **goal** id, which round 7 found it missing.

    ADR-0250 §13 makes this listing the sole route to a cross-conversation resumption —
    "a goal is resumed from another conversation by explicit reference and by that
    alone", "performed from a surface listing the user was shown (§15)" — so a goal whose
    id this surface cannot hand back is a goal that cannot be resumed at all.
    Adversarial review, round 7, ``blocker``.
    """
    _wire(monkeypatch, _listing(_summary(asking=False).model_copy(update={"id": goal_id})))

    assert CliRunner().invoke(cli.app, ["goals"]).exit_code == 0

    screen = _flat(output.getvalue())
    assert f"--goal {argument}" in screen
    assert f"assistant abandon-goal {argument}" in screen
    resume = shlex.split(screen[screen.index("--goal") :].split("Or give it up")[0])
    assert resume == ["--goal", goal_id]


def test_a_goal_id_this_terminal_cannot_show_withholds_the_command_and_not_the_act(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """#1013's clause on the goal id: a wrong command is worse than no command.

    ``_safe`` **replaces** a character a terminal must not be handed, so an id carrying
    one rendered — as a heading, and inside correct shell quotes — as something naming a
    different goal. ``"g\x1b[2J1"`` is an admissible ``Identifier``. Round 7,
    ``blocker``.
    """
    _wire(monkeypatch, _listing(_summary(asking=False).model_copy(update={"id": "g\x1b[2J1"})))

    assert CliRunner().invoke(cli.app, ["goals"]).exit_code == 0

    screen = _flat(output.getvalue())
    assert "no command here to copy" in screen
    assert "--goal" in screen
    assert "assistant abandon-goal" in screen
    assert "\x1b" not in screen


def test_a_closed_goal_is_offered_the_resume_and_not_the_abandonment(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §12 answers ``ALREADY_CLOSED`` there, so the command would do nothing.

    And §13 is why the *resume* is still offered: "a closed goal is reopened by a turn
    that associates to it, by any path of §3: a ``TurnReference`` naming it" — and an
    abandoned goal is a candidate in no conversation, so the reference is its only route
    back. The browser hides the same control for the same reason, stated once per surface
    rather than derived from the other.
    """
    _wire(
        monkeypatch,
        _listing(
            _summary(paused=False, asking=False).model_copy(update={"status": GoalStatus.ABANDONED})
        ),
    )

    assert CliRunner().invoke(cli.app, ["goals"]).exit_code == 0

    screen = _flat(output.getvalue())
    assert "State: given up" in screen
    assert f"--goal {GOAL_ID}" in screen
    assert "abandon-goal" not in screen


def test_the_listing_renders_the_engines_paused_and_derives_nothing(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §15: ``paused`` "is computed and never stored … the engine computes it".

    Stated "so that two surfaces cannot render it differently — which is why ADR-0249 §5
    states the derivation once — and **no adapter derives it**". The arm drives the
    combination a deriving adapter would get wrong: an ``ACTIVE`` goal the engine says
    is **not** paused. An adapter inferring the pause from the status would call it
    waiting; this one renders the boolean it was handed.
    """
    _wire(monkeypatch, _listing(_summary(paused=False, asking=False)))

    assert CliRunner().invoke(cli.app, ["goals"]).exit_code == 0

    screen = _flat(output.getvalue())
    assert "State: open" in screen
    assert "waiting on you" not in screen


def test_the_status_words_are_total_over_the_enumeration() -> None:
    """A member with no words is a member rendered as its own identifier.

    ``_GOAL_STATUS_WORDS`` is keyed by the members' **values** rather than by the
    members, because ADR-0249 §16 item 7's guard —
    ``tests/core/test_goal_status_has_no_producer.py`` — reads the shipped tree for the
    *shapes* a producer can take, and it cannot tell a rendering map's key from one. A
    presentation layer does not need to name the member to render it, ``GoalStatus``
    being a ``StrEnum``; what it does need is to have words for every one, and that is
    what this asserts, from ``core``'s own enumeration rather than from a list kept here.

    This module is under ``tests/`` and names the members freely: the guard's scan is
    over ``src/`` alone, which is where a producer would have to live.
    """
    assert set(cli._GOAL_STATUS_WORDS) == {member.value for member in GoalStatus}
    assert all(cli._GOAL_STATUS_WORDS[member.value] for member in GoalStatus)


def test_a_goal_no_turn_has_taken_up_says_so_rather_than_showing_a_blank(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0249 §1's four absences reaching a surface (ADR-0250 §15).

    ``last_engaged_at`` is absent on a goal no turn has engaged — the state ADR-0249
    §12's migration leaves every pre-decision goal in — and an absence rendered as a
    blank line is one a reader cannot tell from a missing field.
    """
    _wire(monkeypatch, _listing(_summary(engaged=None, paused=False, asking=False)))

    assert CliRunner().invoke(cli.app, ["goals"]).exit_code == 0

    assert "No turn has taken it up yet." in _flat(output.getvalue())


def test_an_empty_listing_says_so_and_is_not_a_failure(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """Nothing outstanding is the ordinary case and exits zero.

    A non-zero exit there would make "is anything waiting on me" unaskable from a
    script, which is the one question this listing exists to answer.
    """
    _wire(monkeypatch, _listing())

    assert CliRunner().invoke(cli.app, ["goals"]).exit_code == 0

    assert "Nothing outstanding" in _flat(output.getvalue())


@pytest.mark.parametrize("argv", [["goals", "--offset", "1"], ["goals", "--limit", "0"]])
def test_an_empty_page_makes_no_claim_about_what_is_outstanding(
    monkeypatch: pytest.MonkeyPatch, output: StringIO, argv: list[str]
) -> None:
    """An empty page is not an empty listing, and only one of the two is checkable here.

    :func:`_render_notifications` states the rule one listing over and this is it: a page
    asked for past the end, or asked for with ``--limit 0``, is empty whatever is
    outstanding. "Nothing outstanding" there would be a false absence and a confident
    one — it is the answer to *is anything waiting on me*, so a script reading it off
    ``--offset 1`` would report a paused goal as none. ``--limit 0`` is accepted here as
    it is on every other listing, which is what makes the second case reachable.

    Adversarial review, round 1, ``major``. The arm drives a store that **does** hold a
    goal, because the defect is invisible over an empty one.
    """
    _wire(monkeypatch, _listing(_summary()))

    assert CliRunner().invoke(cli.app, argv).exit_code == 0

    screen = _flat(output.getvalue())
    assert "No goals on this page" in screen
    assert "Nothing outstanding" not in screen


# --- the two acts (ADR-0250 §12) ---------------------------------------------


@pytest.mark.parametrize("member", list(ClarificationWithdrawal))
def test_every_withdrawal_member_is_rendered_and_names_no_record(
    member: ClarificationWithdrawal, monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §15's non-degradation clause over ``ClarificationWithdrawal``.

    "A surface that renders no statement for a … ``ClarificationWithdrawal`` member it
    was given has not implemented this section — it is **not permissibly degraded**."
    Parametrised over ``core``'s own enumeration, so a third member fails here rather
    than reaching a person as a blank.

    **And neither statement carries an identifier**, which is §15's bar: the question
    the act named is not restated as an id, because the act took it and the sentence is
    about what became of it.
    """
    engine = FakeAssistantEngine()
    engine.withdrawal = member
    _wire(monkeypatch, engine)

    code = CliRunner().invoke(cli.app, ["withdraw-clarification", QUESTION_ID]).exit_code

    screen = _flat(output.getvalue())
    assert screen.strip()
    assert QUESTION_ID not in screen
    assert GOAL_ID not in screen
    # The act that took nothing back exits non-zero, so a script cannot read "that
    # question is withdrawn" off a run in which nothing was withdrawn (#531).
    assert code == (0 if member is ClarificationWithdrawal.WITHDRAWN else 1)


def test_a_withdrawal_says_the_pause_is_still_there_and_that_no_answer_was_recorded(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §12's two clauses that a comforting wording would lose.

    "Withdrawing removes the question and not the pause: the attempt stays
    ``AWAITING_CLARIFICATION`` and the goal stays open", and a withdrawal "records no
    answer, revises no interpretation and engages no goal" — ADR-0244 §11's distinction
    between a denial and a cancellation, one record kind over. A statement saying the
    work had resumed would be false of every case, and one reporting the act as a
    refusal would describe a ruling nothing holds.
    """
    engine = FakeAssistantEngine()
    engine.withdrawal = ClarificationWithdrawal.WITHDRAWN
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, ["withdraw-clarification", QUESTION_ID]).exit_code == 0

    screen = _flat(output.getvalue())
    assert "No answer was recorded" in screen
    assert "still open and still waiting" in screen


@pytest.mark.parametrize("member", list(GoalAbandonment))
def test_every_abandonment_member_is_rendered_and_names_no_record(
    member: GoalAbandonment, monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """The clause above one vocabulary over, over ``GoalAbandonment``'s three."""
    engine = FakeAssistantEngine()
    engine.abandonment = member
    _wire(monkeypatch, engine)

    code = CliRunner().invoke(cli.app, ["abandon-goal", GOAL_ID]).exit_code

    screen = _flat(output.getvalue())
    assert screen.strip()
    assert GOAL_ID not in screen
    assert QUESTION_ID not in screen
    assert code == (0 if member is GoalAbandonment.ABANDONED else 1)


def test_an_abandonment_says_what_it_did_not_touch(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §12's load-bearing half, which the reassuring wording would drop.

    Abandoning "does not move the attempt's state, does not write an ``AttemptOutcome``,
    does not end an execution and does not cancel anything in flight: what becomes of an
    attempt on an abandoned goal is A9's". So the statement says the goal leaves what is
    considered and says nothing about work already under way — a sentence promising that
    everything stopped would be false on a reachable state.
    """
    engine = FakeAssistantEngine()
    engine.abandonment = GoalAbandonment.ABANDONED
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, ["abandon-goal", GOAL_ID]).exit_code == 0

    screen = _flat(output.getvalue())
    assert "any question it had open is withdrawn" in screen
    assert "Nothing already done for it was undone" in screen
    assert "nothing under way was cancelled" in screen


def test_the_two_acts_relay_the_id_and_decide_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Golden rule 3 at this seam: the adapter relays and the engine decides.

    ADR-0250 §15: "no adapter reads a store, joins a row, computes a member or composes
    a reply". So each act is exactly one call carrying exactly the id the user typed,
    and neither takes a second call to find out what state the record was in.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    CliRunner().invoke(cli.app, ["withdraw-clarification", QUESTION_ID])
    CliRunner().invoke(cli.app, ["abandon-goal", GOAL_ID])

    assert engine.calls == [
        ("withdraw_clarification", {"question_id": QUESTION_ID}),
        ("abandon_goal", {"goal_id": GOAL_ID}),
    ]


# --- the reference (ADR-0250 §11, §13) ---------------------------------------


def test_answering_a_clarification_is_a_turn_and_not_a_verb_of_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0250 §11: ``converse`` gains a keyword rather than the surface a fifth verb.

    "Answering is a turn and not an operation of its own, and that is the whole reason
    ``converse`` gains a keyword rather than the surface gaining a fifth verb" — because
    decision 3 requires the answer to restate the understanding, recheck and **proceed**,
    which is everything a turn already is. So the answer rides ``ask``, and what crosses
    the seam is a ``TurnReference`` naming the question.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    code = CliRunner().invoke(cli.app, ["ask", "the one at Melides", "--answering", QUESTION_ID])

    assert code.exit_code == 0
    streamed = [call for call in engine.calls if call[0] == "converse_streaming"]
    assert [call[1]["reference"] for call in streamed] == [TurnReference(question_id=QUESTION_ID)]


def test_a_goal_is_taken_up_from_another_conversation_by_pointing_at_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0250 §13's decision 5, at the surface that performs it.

    "A goal is resumed from another conversation by explicit reference and by that
    alone. The reference is a ``TurnReference`` carrying a ``goal_id`` (§11), performed
    from a surface listing the user was shown (§15)." There is no automatic
    cross-conversation association, so this keyword is the whole of the route.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    code = CliRunner().invoke(cli.app, ["ask", "make it Monday", "--goal", GOAL_ID])

    assert code.exit_code == 0
    streamed = [call for call in engine.calls if call[0] == "converse_streaming"]
    assert [call[1]["reference"] for call in streamed] == [TurnReference(goal_id=GOAL_ID)]


def test_a_turn_carrying_neither_keyword_carries_no_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ordinary turn is unchanged, which is what ``None`` defaulting is for."""
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, ["ask", "what is two plus two?"]).exit_code == 0

    streamed = [call for call in engine.calls if call[0] == "converse_streaming"]
    assert [call[1]["reference"] for call in streamed] == [None]


def test_naming_both_records_is_a_usage_error_before_any_engine_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0250 §11 admits exactly two shapes, and the pair is refused as a usage error.

    The model validator is the authority — "a shape a caller cannot reach is better
    refused by the type than documented" — and what this adds is that the refusal
    reaches the user as *which two flags conflict* rather than as a validation message
    out of ``core`` about members of a type they never named. Exit code 2 is Typer's
    usage code, and no engine is opened.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, ["ask", "either", "--answering", QUESTION_ID, "--goal", GOAL_ID]
    )

    assert result.exit_code == 2
    assert engine.calls == []


# --- the four members on a turn (ADR-0250 §5, §10, §11) ----------------------


@pytest.mark.parametrize("member", list(ReferenceOutcome))
def test_every_reference_outcome_member_is_rendered_and_names_no_record(
    member: ReferenceOutcome, monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §15's non-degradation clause over ``ReferenceOutcome``'s four.

    **Rendered whether or not a goal was engaged**, which is why the outcome driven here
    carries no ``goal_engagement``: "an ``UNKNOWN`` reference is reported whatever the
    association then does … ``reference`` is a member of its own precisely so that the
    user is still told the handle they gave resolved to nothing", and "no implementation
    constructs a ``GoalEngagement`` in order to carry a reference outcome".
    """
    _drive(
        monkeypatch,
        TurnOutcome(turn=TURN, conversation_id="c-1", reply="Right.", reference=member),
        ["ask", "the one at Melides", "--answering", QUESTION_ID],
    )

    screen = _flat(output.getvalue())
    assert screen.strip()
    assert QUESTION_ID not in screen
    assert GOAL_ID not in screen


def test_an_expired_reference_says_the_work_carries_on(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §14's decision 2, and §12's prohibition read at the render site.

    Where a reference names an expired question "the reply says that the question
    expired and that the goal is still being worked on", and §12 forbids reading an
    expiry as "a refusal, an abandonment, a denial or a decision of any kind". §11 adds
    that a late answer "reopens the work rather than vanishing", so a statement reporting
    the answer as lost would be wrong twice over.
    """
    _drive(
        monkeypatch,
        TurnOutcome(
            turn=TURN,
            conversation_id="c-1",
            reply="Right.",
            reference=ReferenceOutcome.EXPIRED,
        ),
        ["ask", "the one at Melides", "--answering", QUESTION_ID],
    )

    screen = _flat(output.getvalue())
    assert "still open and is still being worked on" in screen


def test_a_settled_question_is_never_reported_as_an_expiry(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §11's pair, which a shared sentence would collapse.

    "A question answered an hour after it was asked and referenced a week later is
    ``ALREADY_SETTLED``, not ``EXPIRED``: it was answered, and a reply saying otherwise
    would tell the user their answer never arrived."
    """
    _drive(
        monkeypatch,
        TurnOutcome(
            turn=TURN,
            conversation_id="c-1",
            reply="Right.",
            reference=ReferenceOutcome.ALREADY_SETTLED,
        ),
        ["ask", "the one at Melides", "--answering", QUESTION_ID],
    )

    screen = _flat(output.getvalue())
    assert "already settled" in screen
    assert "run out of time" not in screen


@pytest.mark.parametrize("member", list(EngagementDisposition))
def test_every_engagement_disposition_is_rendered_and_names_no_record(
    member: EngagementDisposition, monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §15's non-degradation clause over ``EngagementDisposition``'s four."""
    _drive(monkeypatch, _engaged(member), ["ask", "book it"])

    screen = _flat(output.getvalue())
    assert screen.strip()
    assert GOAL_ID not in screen
    assert QUESTION_ID not in screen


def test_the_surface_composes_no_announcement_of_its_own(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §5's announcement is the reply's, and this surface writes no second one.

    §5 gives the sentence to the reply — one "naming the goal it is about", stating "the
    goal's ``outcome`` as this turn recorded it, **every text in ``added``**, and **every
    text in ``removed``**" — and rules it "composed by ``orchestration`` from the typed
    value and by no model's decision". It is already on the screen where §5 owes it.

    A surface restating those texts would put the announcement in a second place; on a
    ``CONTINUED`` or an ``OPENED`` that moved no word it would put one where §5 rules the
    turn silent ("announcing it would be noise on every turn"). So the arm drives a
    revision that moved words and asserts that **none of them** appears in anything this
    adapter wrote: the reply is empty of them here precisely because the fake composes
    none, which is what makes the absence this surface's.
    """
    _drive(
        monkeypatch,
        _engaged(
            EngagementDisposition.CONTINUED,
            revised=True,
            added=("the last weekend of September",),
            removed=("the last weekend of August",),
        ),
        ["ask", "make it September"],
    )

    screen = _flat(output.getvalue())
    assert "September" not in screen
    assert "August" not in screen
    assert OUTCOME not in screen
    # And the disposition's own statement is still there: silence would be the other
    # failure, which §15 refuses in terms.
    assert "carried on the work" in screen


def test_a_raised_clarification_appears_in_the_exchange_that_raised_it(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §10, and the id §15 admits because the answer act takes it.

    ``clarification`` "carries the question **this turn raised**, so the question appears
    in the exchange that raised it". The turn did not park — "it composes, its answer
    *is* the question, and it returns" — so what is offered is the next turn's keyword
    and the withdrawal, and there is no token and no approval pair.
    """
    _drive(
        monkeypatch,
        TurnOutcome(
            turn=TURN,
            conversation_id="c-1",
            reply="Which one did you mean?",
            goal_engagement=_engagement(EngagementDisposition.OPENED),
            clarification=_clarification(),
        ),
        ["ask", "book the usual campsite"],
    )

    screen = _flat(output.getvalue())
    assert QUESTION in screen
    assert f"--answering {QUESTION_ID}" in screen
    assert f"assistant withdraw-clarification {QUESTION_ID}" in screen
    assert "Answerable until 2026-01-08 11:00 UTC" in screen


def test_an_undecided_turn_is_not_reported_as_needing_no_action(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0250 §5's ask reaches the screen, and the surface adds the act and no more.

    The ask itself is the reply's — "composed by ``orchestration`` from the typed value",
    deterministically, so that it "cannot disagree with the member beside it" — and §14
    places the mention of a paused goal in the reply of exactly this turn. A second
    listing of the same outcome statements underneath would be that mention twice on one
    screen, and would be this adapter composing a reply (golden rule 3).

    So the arm asserts both directions: the candidates are **not** restated, and the act
    the owner reaches for next **is** named.
    """
    _drive(
        monkeypatch,
        TurnOutcome(
            turn=None,
            conversation_id="c-1",
            reply="Is this about the campsite, or something new?",
            disambiguation=GoalDisambiguation(candidates=(OUTCOME,), elided=0),
        ),
        ["ask", "make it Monday"],
    )

    screen = _flat(output.getvalue())
    assert screen.count(OUTCOME) == 0
    assert "--goal <goal-id>" in screen
    assert "assistant goals" in screen


# --- ADR-0250 §20's arm 30: the surfaces are separate ------------------------


def test_the_two_question_surfaces_share_no_list_no_command_and_no_vocabulary() -> None:
    """ADR-0250 §20's arm 30, and §15's clause it is stated over.

    "``assistant questions`` and ``assistant answer`` list and answer **memory**
    questions only, and neither lists nor accepts a ``GoalQuestion``; the clarification
    acts neither list nor accept an ADR-0078 ``Question``."

    Asserted over the registered commands, which is where the confusion would land: the
    memory acts keep their names and their ``--accept/--reject`` answer, the goal acts
    take names of their own, and no command is registered that answers both. "Two
    goal-shaped things with the same English word is the confusion this section is
    written to prevent."
    """
    group = typer.main.get_command(cli.app)
    assert isinstance(group, TyperGroup)
    names = set(group.commands)

    # The memory surface, unrenamed and ungained: §15 says this decision "adds no member
    # to them, changes no argument of them, and renames nothing".
    assert {"questions", "answer", "forget-question"} <= names
    memory = {param.name for param in group.commands["answer"].params}
    assert memory == {"question_id", "accept"}

    # The goal surface, under names of its own.
    assert {"goals", "withdraw-clarification", "abandon-goal"} <= names
    assert "accept" not in {param.name for param in group.commands["withdraw-clarification"].params}

    # And no command answers both kinds: the goal acts take no belief flag, and the
    # memory answer takes no reference.
    assert "answering" not in {param.name for param in group.commands["answer"].params}
    assert "goal" not in {param.name for param in group.commands["answer"].params}


def test_each_goal_surface_says_which_kind_of_question_it_is_not_about() -> None:
    """The confusion §15 names is headed off in the help, where a reader meets it.

    "A deferred memory question asks *may I believe this about you*, is answered
    yes-or-no, and its answer writes a belief. A goal clarification asks *which of two
    things did you mean*, is answered in words, and its answer revises an
    interpretation." A user who reaches the wrong command reaches it from the help, so
    the help is where the two are told apart.
    """
    listing = _help_text(CliRunner().invoke(cli.app, ["goals", "--help"]).output)

    assert "not assistant questions" in listing
    assert "questions about work" in listing
