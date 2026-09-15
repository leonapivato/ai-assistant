"""The terminal's statement of what a turn did about reaching outside this system.

ADR-0264 §11's **lane 2**: `interfaces/cli.py` renders §7's statement. Lane 1 landed the
contract and `orchestration`'s establishment, fold and assembly; what is owed here is the
half §11 assigns by the assertion rather than by a count — "every arm's assertions about a
**rendered statement** are lane 2's, landed with the renderer they are about".

**Every case asserts over the rendered bytes**, because §7's obligation is discharged in
what the user reads and nowhere else — ADR-0242 §15's last clause one vocabulary over:
those are the system's own words. A statement that only exists in a helper's return value
is a statement no user was ever told.

**Driven through the production :func:`cli._render_turn` wherever the arm is about what a
user sees beside a reply**, so the order, the adjacency and the "No action was needed."
notice are asserted as a screen and not as a call this module made itself.
"""

from __future__ import annotations

import sys
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Final

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.types import (
    Belief,
    BeliefBand,
    MemoryKind,
    OutboundDestination,
    OutboundReach,
    OutboundStatement,
    RoutableOperation,
    RoutedOperation,
    RouteOutcome,
    SearchNotServiced,
    TurnOutcome,
)
from ai_assistant.interfaces import cli
from ai_assistant.orchestration.reads import SearchDisposition
from ai_assistant.testing import FakeAssistantEngine

PATIENT: Final = timedelta(seconds=30)

#: A contact with the one class the vocabulary declares, having brought records in.
_REACHED: Final = OutboundStatement(
    reach=OutboundReach.REACHED,
    destinations=(OutboundDestination.SEARCH_PROVIDER,),
    records=3,
)

#: The same contact, having brought nothing in — §4's ``0``, which never suppresses the
#: statement and is the case #2268 says a user cannot otherwise tell from a turn that
#: never looked.
_REACHED_EMPTY_HANDED: Final = OutboundStatement(
    reach=OutboundReach.REACHED, destinations=(OutboundDestination.SEARCH_PROVIDER,)
)

_NOT_REACHED: Final = OutboundStatement(reach=OutboundReach.NOT_REACHED)
_INDETERMINATE: Final = OutboundStatement(reach=OutboundReach.INDETERMINATE)

#: What each member's statement must say, as fragments of the rendered line.
#:
#: The three are §7's three sentences: that this turn reached outside this system, naming
#: each class and how many records it brought into the turn's supply; that it reached
#: nothing outside this system; and that this system cannot say which.
_STATEMENTS: Final[dict[OutboundReach, tuple[str, ...]]] = {
    OutboundReach.REACHED: (
        "this turn reached outside this system",
        "the web search provider you have configured",
        "3 records",
    ),
    OutboundReach.NOT_REACHED: ("this turn reached nothing outside this system",),
    OutboundReach.INDETERMINATE: (
        "cannot say whether this turn reached outside it",
        "either direction",
    ),
}

#: One representative value per member, so the enumeration arm below can be driven over
#: the vocabulary itself rather than over a list an editor keeps in step by hand.
_VALUES: Final[dict[OutboundReach, OutboundStatement]] = {
    OutboundReach.REACHED: _REACHED,
    OutboundReach.NOT_REACHED: _NOT_REACHED,
    OutboundReach.INDETERMINATE: _INDETERMINATE,
}


def _flat(rendered: str) -> str:
    """Collapse Rich's wrapping and its continuation marker (#2072).

    :func:`cli._print` writes a ``↳`` onto every display line a line runs onto, so an
    assertion about words needs the marker gone as well as the break.
    """
    return " ".join(rendered.replace("↳", " ").split())


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


async def _composed(statement: OutboundStatement | None) -> TurnOutcome:
    """One turn that composed a reply, carrying ``statement``.

    ``TurnOutcome`` refuses a reply beside a ``None`` turn, so an arm about what a
    *composed* pass renders needs a real :class:`~ai_assistant.core.types.TurnResult`
    behind it. The canonical fake composes one; what this replaces is the member
    ADR-0264 §7 makes load-bearing and nothing else.
    """
    engine = FakeAssistantEngine()
    turn = await engine.converse("when does it open?", timeout=PATIENT)
    return TurnOutcome(turn=turn.turn, reply=turn.reply, outbound_statement=statement)


# --- §7's three statements, over the vocabulary itself -----------------------


def test_the_statements_and_the_vocabulary_are_the_same_set() -> None:
    """The partition, so a member cannot be added without its words.

    ADR-0264 §7 fixes one statement per ``OutboundReach`` member and §9 makes a surface
    rendering none for a value it was given one that "has not implemented this section,
    and is not exercising a permitted degradation". A member added to the enumeration
    without an entry below is that failure, and this is what turns it into a red test
    rather than a blank line in somebody's terminal.
    """
    assert set(_STATEMENTS) == set(OutboundReach)
    assert set(_VALUES) == set(OutboundReach)


@pytest.mark.parametrize("member", list(OutboundReach))
def test_every_member_renders_a_statement(member: OutboundReach, output: StringIO) -> None:
    """§7, §9: every value this surface is given is stated, in the words §7 fixes.

    Parametrised over the enumeration, so a fourth member arriving with its ADR (§4)
    fails here rather than rendering nothing.

    Driven with ``composed_a_reply=True``, which is the condition under which all three
    render; the asymmetry that separates them is the arm below.
    """
    cli._render_outbound_statement(_VALUES[member], composed_a_reply=True)
    rendered = _flat(output.getvalue())

    assert rendered.strip(), f"{member} renders nothing"
    for fragment in _STATEMENTS[member]:
        assert fragment in rendered


@pytest.mark.parametrize("member", list(OutboundDestination))
def test_every_destination_class_renders_its_own_words(member: OutboundDestination) -> None:
    """§5, §7: a class added without its phrase is a member with no rendering.

    ADR-0264 §5 is explicit that a later seam's member "does **not** render as
    ``SEARCH_PROVIDER`` and does not render as nothing", so the arm is over the
    vocabulary and asserts both halves: every member has words, and no two members share
    them.
    """
    words = cli._outbound_destination(member)

    assert words.strip()
    others = [cli._outbound_destination(one) for one in OutboundDestination if one is not member]
    assert words not in others, "a class rendering as another class names neither"


def test_a_reached_statement_names_the_class_and_never_a_destination(output: StringIO) -> None:
    """§4, §5: the class the owner chose, and no provider, host, account or connection.

    ADR-0247 §1 makes the configured provider "the destination the owner chose and the
    recipient they granted", so what is said back is that decision and not a fact about
    this turn's routing. §5 refuses a member that identifies a particular destination
    outright, "which would put a destination's identity into a reply, on every surface
    and on a channel of unbounded audience".
    """
    cli._render_outbound_statement(_REACHED, composed_a_reply=True)
    rendered = _flat(output.getvalue())

    assert "the web search provider you have configured" in rendered
    for forbidden in ("http", "://", "@", ".com", "brave", "Brave", "api", "key"):
        assert forbidden not in rendered


def test_the_count_of_zero_is_stated_rather_than_elided(output: StringIO) -> None:
    """§13 arm 2: "the rendered statement states the ``0`` rather than eliding it".

    §4: a ``0`` "means this turn's supply holds no record its contacts brought in, and it
    means nothing else — and it never suppresses the statement. A turn that reached
    outside itself and brought nothing into its supply is the case this decision most
    needs to state: it is the one a user cannot tell from a turn that did not look."
    """
    cli._render_outbound_statement(_REACHED_EMPTY_HANDED, composed_a_reply=True)
    rendered = _flat(output.getvalue())

    assert "this turn reached outside this system" in rendered
    assert "0 records" in rendered


def test_the_count_is_singular_for_one_record(output: StringIO) -> None:
    """A count read as prose, so "1 records" is not what a user is shown."""
    cli._render_outbound_statement(
        OutboundStatement(
            reach=OutboundReach.REACHED,
            destinations=(OutboundDestination.SEARCH_PROVIDER,),
            records=1,
        ),
        composed_a_reply=True,
    )

    assert "1 record " in _flat(output.getvalue())


def test_no_statement_says_a_record_reached_supported_or_affected_the_answer(
    output: StringIO,
) -> None:
    """§7: ``records`` says the records entered this turn's supply and nothing beyond it.

    "Not that a model was given them, not that the answer rests on them, not that it is
    more current for them, and not that it would have differed without them" (§4). A
    surface asserting more "would be attributing the answer's content to material a model
    may never have seen".
    """
    cli._render_outbound_statement(_REACHED, composed_a_reply=True)
    rendered = _flat(output.getvalue()).lower()

    assert "a count here says what arrived and nothing about whether any answer used it" in (
        rendered
    )
    for forbidden in (
        "the answer rests",
        "based on",
        "sources for",
        "used them",
        "informed",
        "up to date",
        "up-to-date",
        "current",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize("member", list(OutboundReach))
def test_no_statement_carries_an_identifier_a_figure_or_a_disposition(
    member: OutboundReach, output: StringIO
) -> None:
    """§4, §7's bar, asserted **over the rendered bytes** and not over an intention.

    None of the three carries a destination, a host, an origin, a provider name, a
    connection reference, an account identity, a tool identifier, a query or any fragment
    of one, a record, a title, a snippet, a monetary figure, a duration, a ``Settings``
    field name, a ``SearchDisposition`` value, a record id, a decision id or an instant.

    **The one number any of them may carry is** ``records``, which §7 obliges — so the
    digits are asserted to be exactly that count's and never merely absent, which would
    fail the arm above instead of this one.
    """
    statement = _VALUES[member]
    cli._render_outbound_statement(statement, composed_a_reply=True)
    rendered = _flat(output.getvalue())

    digits = "".join(character for character in rendered if character.isdigit())
    expected = str(statement.records) if statement.reach is OutboundReach.REACHED else ""
    assert digits == expected

    for forbidden in ("http", "://", "@", "$", "£", "web_search_cost_per_call", "ms", "seconds"):
        assert forbidden not in rendered
    for stage in SearchDisposition:
        assert stage.value not in rendered


# --- §7's asymmetry, and its one condition ----------------------------------


def test_a_pass_that_composed_no_reply_renders_only_the_reached_statement(
    output: StringIO,
) -> None:
    """§13 arm 10, and §7's asymmetry in terms.

    "``REACHED`` reports an **act this system performed**, which the user is owed whether
    or not prose was written — ADR-0227's posture that the audit records acts — while the
    other two report **nothing having happened**, whose only function is to stop a reply
    being read as claiming otherwise, so where there is no reply they answer a question
    nobody asked."

    §13 arm 10 names both failures: an implementation that renders ``NOT_REACHED`` with no
    reply beside it fails this, and so does one that suppresses ``REACHED`` there.
    """
    for silent in (_NOT_REACHED, _INDETERMINATE):
        buffer = StringIO()
        with redirect_stdout(buffer):
            cli._render_outbound_statement(silent, composed_a_reply=False)
        assert _flat(output.getvalue()) == "", f"{silent.reach} renders with no reply beside it"

    cli._render_outbound_statement(_REACHED, composed_a_reply=False)

    assert "this turn reached outside this system" in _flat(output.getvalue())


@pytest.mark.parametrize("shape", ["composition_failed", "recovered_park"])
async def test_a_reply_less_pass_renders_only_the_reached_statement_on_the_screen(
    shape: str, output: StringIO
) -> None:
    """§13 arm 10, driven through :func:`cli._render_turn` and not through the helper.

    The arm above pins what the helper does with ``composed_a_reply=False``; this pins
    that a reply-less pass **reaches** it at all. A renderer that called it only where
    ``outcome.reply`` was set would leave every arm in this module green while a turn
    that searched and then composed nothing said nothing about the contact — which is
    exactly the case §7 says the user is owed "whether or not prose was written".

    Two of ADR-0170 §4's reply-less shapes, because they leave
    :func:`cli._render_turn` differently: one whose composition failed before anything
    was published, and one resumed from a **recovered** park, which carries no ``turn``
    at all and so skips every block below the statement.

    **The two silent values are asserted defensively here.** §7 leaves the member
    ``None`` on a reply-less pass that established nothing, so a conforming engine does
    not produce a reply-less ``NOT_REACHED`` — but §13 arm 10 names rendering one "with
    no reply beside it" as a failure in terms, and a surface is held to what it does
    with a value it is handed.
    """

    engine = FakeAssistantEngine()
    composed = await engine.converse("when does it open?", timeout=PATIENT)

    def _outcome(statement: OutboundStatement) -> TurnOutcome:
        if shape == "composition_failed":
            return TurnOutcome(
                turn=composed.turn, reply=None, reply_degraded=True, outbound_statement=statement
            )
        return TurnOutcome(turn=None, reply=None, outbound_statement=statement)

    cli._render_turn(_outcome(_REACHED))
    reached = _flat(output.getvalue())
    output.truncate(0)
    output.seek(0)
    for silent in (_NOT_REACHED, _INDETERMINATE):
        cli._render_turn(_outcome(silent))
        rendered = _flat(output.getvalue())
        output.truncate(0)
        output.seek(0)
        for fragment in _STATEMENTS[silent.reach]:
            assert fragment not in rendered, f"{silent.reach} rendered with no reply beside it"

    assert "this turn reached outside this system" in reached
    assert "3 records" in reached


@pytest.mark.parametrize(
    "prose",
    [
        "I did not search for anything just now.",
        "I searched the web and here is what came back.",
        "It opens at nine.",
    ],
)
async def test_the_statement_does_not_depend_on_what_the_reply_says(
    prose: str, monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§7: "The condition is the reply's existence and never its content."

    "No surface reads the prose to decide whether to render, which would be the model
    judgement §10 refuses." Driven through :func:`cli._render_turn` over three replies —
    one denying a contact, one claiming one, and one mentioning neither — and the
    rendered statement is the same line every time. A reply that is **blank** is not a
    fourth case here: ``TurnOutcome`` refuses one, so "composed a reply" and "composed
    prose" cannot come apart in that direction.
    """
    engine = FakeAssistantEngine()
    turn = await engine.converse("when does it open?", timeout=PATIENT)
    cli._render_turn(TurnOutcome(turn=turn.turn, reply=prose, outbound_statement=_NOT_REACHED))

    assert "this turn reached nothing outside this system" in _flat(output.getvalue())


async def test_a_turn_carrying_no_statement_renders_none(
    output: StringIO,
) -> None:
    """§7: silence on a pass that neither established a contact nor composed a reply.

    A routed park is that shape, and "no surface renders a statement for a value it was
    not given".
    """
    cli._render_turn(await _composed(None))
    rendered = _flat(output.getvalue())

    assert "reached" not in rendered
    assert "cannot say whether" not in rendered


# --- §8: both statements ride together --------------------------------------


async def test_both_statements_are_rendered_where_a_turn_carries_both(
    output: StringIO,
) -> None:
    """§8, and §13 arm 3's last clause: "renders both statements".

    The shape is the one §8 names: a response received and then refused, which records
    ``UNATTESTED`` — so the turn carries ``REACHED`` with ``records`` ``0`` **and**
    ``search_not_serviced`` ``UNAVAILABLE``. "Read together they say: a request was made,
    and nothing usable came back." Neither is read off the other and neither suppresses
    nor qualifies the other, which is what this asserts: both lines, on one screen.
    """
    engine = FakeAssistantEngine()
    turn = await engine.converse("when does it open?", timeout=PATIENT)
    cli._render_turn(
        TurnOutcome(
            turn=turn.turn,
            reply=turn.reply,
            outbound_statement=_REACHED_EMPTY_HANDED,
            search_not_serviced=SearchNotServiced.UNAVAILABLE,
        )
    )
    rendered = _flat(output.getvalue())

    assert "this turn reached outside this system" in rendered
    assert "0 records" in rendered
    assert "that lookup produced nothing this turn could use" in rendered


async def test_the_statement_stands_beside_the_reply_and_never_in_place_of_it(
    output: StringIO,
) -> None:
    """§7: "beside the reply where one exists and never in place of it".

    Driven through the production :func:`cli._render_turn`, so what is asserted is the
    order a user actually reads: the prose first, the statement that contradicts it
    directly under, and ADR-0242 §9's statement after that.
    """
    engine = FakeAssistantEngine()
    turn = await engine.converse("when does it open?", timeout=PATIENT)
    reply = "Nothing was searched just now."
    cli._render_turn(
        TurnOutcome(
            turn=turn.turn,
            reply=reply,
            outbound_statement=_REACHED,
            search_not_serviced=SearchNotServiced.UNAVAILABLE,
        )
    )
    rendered = _flat(output.getvalue())

    assert rendered.index("Nothing was searched just now.") < rendered.index(
        "this turn reached outside this system"
    )
    assert rendered.index("this turn reached outside this system") < rendered.index(
        "that lookup produced nothing this turn could use"
    )


# --- §13 arm 11: the routed pass, and the two composers this surface has ------


def _both_ways(outcome: TurnOutcome, output: StringIO) -> tuple[str, str]:
    """Render one outcome as a whole reply and as a settled stream, and return both.

    ADR-0173 §10's third clause is why the streamed half is never assumed from the
    first: "the step account is rendered whether or not chunks were rendered", and a
    renderer reached only on the one-result path would leave every streamed turn
    silent — which is the path ``assistant ask`` actually takes.
    """
    cli._render_turn(outcome)
    one_result = _flat(output.getvalue())
    output.truncate(0)
    output.seek(0)
    cli._render_turn(outcome, streamed=cli._StreamedReply())
    return one_result, _flat(output.getvalue())


def test_a_routed_pass_that_is_not_a_park_renders_the_statement_both_ways(
    output: StringIO,
) -> None:
    """§13 arm 11: "The whole-reply and streaming passes **render** §7's statement."

    The arm's subject is a **routed** pass, which is the path an implementation
    updating only the conversational composer would leave behind: ADR-0197 §8 makes
    ``routed`` and ``step`` mutually exclusive and gives such a pass no ``turn`` at
    all, so it takes an early return out of :func:`cli._render_turn` and renders none
    of the plan. §7 is explicit that it still carries a statement — "a routed pass
    that is not a park carries ``NOT_REACHED``, because ADR-0197 §10 rules that on it
    the composing stage runs on §6's two inputs and an answer is owed" — so a
    regression returning before the statement would suppress it here and nowhere else.

    Arm 11 names three composers and this surface has two of them. ADR-0200 §4 makes
    ``spoken`` the rendering of ``outcome.reply`` and of nothing else, and this module
    exposes no spoken command at all, so the spoken third is a carried member with no
    rendering here — ADR-0264 §12's stated cost rather than this lane's omission.
    """
    routed = TurnOutcome(
        turn=None,
        conversation_id="c-1",
        routed=RoutedOperation(operation=RoutableOperation.UNGUARD, outcome=RouteOutcome.PERFORMED),
        reply="That belief can be spoken to anyone again.",
        outbound_statement=_NOT_REACHED,
    )

    one_result, streamed = _both_ways(routed, output)

    assert "this turn reached nothing outside this system" in one_result
    assert "this turn reached nothing outside this system" in streamed


def test_a_routed_park_renders_no_statement(output: StringIO) -> None:
    """§7, §13 arm 11's last clause: "A **routed park** carries ``None`` and renders
    nothing."

    ADR-0197 §10 rules that on a routed park "the composing stage is not reached", so
    it is one of exactly two shapes §7 leaves the member ``None`` on — and a surface
    that invented a statement there would be asserting what no value establishes. The
    card is parked through the canonical fake's own lever, because ADR-0197 §7 makes a
    routed park unreachable from the surface by any other route.
    """
    engine = FakeAssistantEngine()
    card = engine.park_routed(
        "h-1",
        operation=RoutableOperation.FORGET,
        subject=(
            Belief(
                id="b-1",
                band=BeliefBand.ASSERTED,
                kind=MemoryKind.PREFERENCE,
                content="you drink tea",
                confidence=0.9,
                last_updated=datetime(2026, 5, 1, 9, tzinfo=UTC),
            ),
        ),
    )

    cli._render_turn(
        TurnOutcome(
            turn=None,
            conversation_id="c-1",
            routed=RoutedOperation(
                operation=RoutableOperation.FORGET,
                outcome=RouteOutcome.AWAITING_CONFIRMATION,
                confirmation=card,
            ),
            reply=None,
        )
    )
    rendered = _flat(output.getvalue())

    assert "reached" not in rendered
    assert "cannot say whether" not in rendered


async def test_a_conversational_pass_renders_the_statement_both_ways(
    output: StringIO,
) -> None:
    """The same, on the composer the routed one is contrasted with.

    The two paths leave :func:`cli._render_turn` by different returns, so a renderer
    wired into one of them is green on half this surface's turns.
    """
    engine = FakeAssistantEngine()
    turn = await engine.converse("when does it open?", timeout=PATIENT)
    whole = TurnOutcome(turn=turn.turn, reply=turn.reply, outbound_statement=_NOT_REACHED)

    one_result, streamed = _both_ways(whole, output)

    assert "this turn reached nothing outside this system" in one_result
    assert "this turn reached nothing outside this system" in streamed


# --- the two issues this lane closes with lane 1 -----------------------------


async def test_2268s_turn_says_it_reached_whatever_the_reply_claims(
    output: StringIO,
) -> None:
    """#2268: a successful servicing disowned in prose, contradicted on the same screen.

    The reply is the one the M31 exit QA run recorded — "nothing was searched just now" —
    beside a trail that records a servicing returning three records. §10: the statement
    "is composed by code and cannot be made to agree with a denial or with a false claim,
    so a user reading both sees the disagreement without anything having classified it".
    """
    engine = FakeAssistantEngine()
    turn = await engine.converse("find more about that", timeout=PATIENT)
    cli._render_turn(
        TurnOutcome(
            turn=turn.turn,
            reply="I did not search for anything; nothing was searched just now.",
            outbound_statement=_REACHED,
        )
    )
    rendered = _flat(output.getvalue())

    assert "nothing was searched just now" in rendered, "the reply is not edited to agree"
    assert "this turn reached outside this system" in rendered
    assert "3 records" in rendered


async def test_2365s_turn_says_it_reached_nothing_beside_a_reply_claiming_searches(
    output: StringIO,
) -> None:
    """#2365: a reply claiming "this turn's searches" on a turn that made no call.

    §9's arm: "the rendered statement says this turn reached nothing outside this
    system", and "an implementation that leaves the member ``None`` on such a turn fails
    this arm, which is the whole of what #2365 records". The member is lane 1's; that it
    reaches a user's screen is this lane's.
    """
    cli._render_turn(await _composed(_NOT_REACHED))
    rendered = _flat(output.getvalue())

    assert "this turn reached nothing outside this system" in rendered


# --- the notice this statement would otherwise contradict --------------------


async def test_no_action_was_needed_is_not_printed_beside_a_reached_statement(
    output: StringIO,
) -> None:
    """The contradiction this lane would otherwise have created on one screen.

    A search is serviced in context assembly and not as a plan step (ADR-0242 §6), so a
    turn whose planner then declined every capability reaches the renderer with an empty
    plan — #2268's own shape. "No action was needed." one line under "this turn reached
    outside this system" is the contradiction the guard already exists to prevent, and
    PR #2325 is the ratified precedent for a lane closing the cases its own member
    creates.
    """
    cli._render_turn(await _composed(_REACHED))
    rendered = _flat(output.getvalue())

    assert "this turn reached outside this system" in rendered
    assert "No action was needed." not in rendered


@pytest.mark.parametrize("statement", [_NOT_REACHED, _INDETERMINATE, None])
async def test_no_action_was_needed_still_prints_where_nothing_was_reached(
    statement: OutboundStatement | None, output: StringIO
) -> None:
    """The guard is on ``REACHED`` and on neither of the other two.

    A turn that reached nothing is exactly a turn of which "no action was needed" may
    well be true, so narrowing the notice further would be this lane taking a decision
    ADR-0264 does not give it. #2329's two pre-existing members are untouched for the
    same reason.
    """
    cli._render_turn(await _composed(statement))

    assert "No action was needed." in _flat(output.getvalue())


# --- end to end, over the canonical fake's own scripting ---------------------


def test_the_statement_reaches_a_user_driving_assistant_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole path, from the member the engine carries to the bytes on the terminal.

    ``FakeAssistantEngine`` carries ADR-0264 §7's member on every outcome it composes and
    lets a caller script another (#2381, #2382), so this drives the real command over a
    scripted ``REACHED`` rather than over an outcome this module handed the renderer.
    That is the one thing the unit arms above cannot show: that ``ask`` reaches
    :func:`cli._render_outbound_statement` at all.
    """
    engine = FakeAssistantEngine()
    engine.outbound_statement = _REACHED
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["ask", "when does it open?", "--yes"])
    rendered = _flat(result.output)

    assert result.exit_code == 0
    assert "this turn reached outside this system" in rendered
    assert "the web search provider you have configured" in rendered
    assert "3 records" in rendered


def test_a_default_fake_turn_says_it_reached_nothing_driving_assistant_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And the default value reaches the same screen, which is #2381's whole point.

    A canonical fake supplying no statement "let a surface be written, tested green
    against it and never read the field at all"; the default is a fresh ``NOT_REACHED``,
    and a turn composed under it says so to the user.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["ask", "when does it open?", "--yes"])

    assert result.exit_code == 0
    assert "this turn reached nothing outside this system" in _flat(result.output)


def test_a_count_past_cpythons_conversion_cap_still_renders(output: StringIO) -> None:
    """A statement ADR-0264 §7 obliges must not become a traceback on an admitted value.

    ``records`` is bounded by ``ge=0`` and by nothing else — §4 hands "what validation
    it carries beyond ``ge=0``" to this module and to #2362, and settles none of it — and
    it is a **boundary-crossing** field a wire decode builds as well as this tree. So the
    value reaching the renderer is whatever a frame carried, and CPython raises
    :class:`ValueError` converting an ``int`` past :func:`sys.get_int_max_str_digits`
    digits to text: an f-string here would replace §7's statement with a stack trace on
    the one surface obliged to render it.

    Asserted by **counting the digits on screen** rather than by matching the number as a
    substring, because Rich wraps a 4301-digit word across display lines and a substring
    assertion would be about the console's width.
    """
    digits = sys.get_int_max_str_digits() + 1
    cli._render_outbound_statement(
        OutboundStatement(
            reach=OutboundReach.REACHED,
            destinations=(OutboundDestination.SEARCH_PROVIDER,),
            records=10 ** (digits - 1),
        ),
        composed_a_reply=True,
    )
    rendered = _flat(output.getvalue())

    assert "this turn reached outside this system" in rendered
    assert sum(character.isdigit() for character in rendered) == digits
    assert "e+" not in rendered, "and as plain digits, never in scientific notation"
