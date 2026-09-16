"""The terminal's statement about a forecast this turn did not read (ADR-0260 §10).

The lane #2474 filed: §12 cut three lanes — the contract with its ``tools/``
implementation, the authority in ``permissions/``, and the servicing in
``orchestration/`` plus the composition root — and named ``interfaces/`` in none of them,
so once L3 landed ``TurnOutcome.forecast_not_read`` was populated by the engine and
rendered by nothing at all.

**Every case asserts over the rendered bytes**, because §10's obligation is discharged in
what the user reads and nowhere else — ADR-0242 §15's last clause one vocabulary over:
those are the system's own words. A statement that only exists in a helper's return value
is a statement no user was ever told.

**And the parity arm is here rather than in either surface's own module**, because what it
is about is the pair. ADR-0262 §11: "§6's six fixed statements, on the CLI and on the
browser — **both surfaces**, since a member rendered on one and not the other is the
parity failure M4 recorded."
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
    ForecastNotRead,
    OutboundDestination,
    OutboundReach,
    OutboundStatement,
    SearchNotServiced,
    TurnOutcome,
)
from ai_assistant.interfaces import cli
from ai_assistant.orchestration.reads import ForecastDisposition
from ai_assistant.testing import FakeAssistantEngine

PATIENT: Final = timedelta(seconds=30)

_AT: Final = datetime(2026, 5, 1, 9, tzinfo=UTC)

_APP_JS: Final = Path(cli.__file__).resolve().parent / "gateway" / "assets" / "app.js"

#: What each member's statement must say, as fragments of the rendered line.
#:
#: **Read off §10's own sentence per member**, which is the half the ADR fixes: a forecast
#: source not configured and an operator setting; a spend ceiling and an operator setting;
#: a question instead of a read, a recorded decision and ``assistant decisions``; declined
#: when it was ruled on; begun and stopped; and nothing the turn could use.
_STATEMENTS: Final[dict[ForecastNotRead, tuple[str, ...]]] = {
    ForecastNotRead.NOT_CONFIGURED: (
        "no forecast source is configured in this deployment",
        "operator setting",
    ),
    ForecastNotRead.AUTHORISATION_AWAITED: (
        "put to you as a question instead of being made",
        "a decision is recorded",
        "'assistant decisions'",
    ),
    ForecastNotRead.SPEND_EXHAUSTED: (
        "a spending ceiling refused that forecast read",
        "operator setting",
    ),
    ForecastNotRead.DECLINED: ("declined when it was ruled on",),
    ForecastNotRead.INTERRUPTED: ("begun and stopped",),
    ForecastNotRead.UNAVAILABLE: ("produced nothing this turn could use",),
}

#: The members this surface does **not** yet render, each naming the lane that closes it.
#:
#: **Empty is the intended state**, and it is ``SearchNotServiced``'s own device one
#: vocabulary over: an entry here is a lane-ordering fact rather than a permitted
#: degradation, and the partition arm below is what stops it growing by accident.
_DEFERRED_TO_A_LATER_LANE: Final[dict[ForecastNotRead, str]] = {}


def _flat(rendered: str) -> str:
    """Collapse Rich's wrapping and its continuation marker (#2072).

    :func:`cli._print` writes a ``↳`` onto every display line a line runs onto, so an
    assertion about words needs the marker gone as well as the break — and a command name
    is exactly the sort of string that lands on one.
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


async def _composed() -> TurnOutcome:
    """One turn that composed a reply, for an arm to copy the members it is about onto.

    ``TurnOutcome`` refuses a reply beside a ``None`` turn, so an arm about what a
    *composed* pass renders needs a real turn behind it. The canonical fake composes one;
    what each arm replaces is the member ADR-0260 §10 makes load-bearing and nothing else.
    """
    engine = FakeAssistantEngine()
    turn = await engine.converse("will it rain tomorrow?", timeout=PATIENT)
    return TurnOutcome(turn=turn.turn, reply=turn.reply)


# --- §10: one statement per member, over their rendered bytes ----------------


def test_the_members_this_surface_defers_are_the_declared_ones() -> None:
    """The partition, so a deferral cannot be added by an editor's convenience.

    A member that renders nothing and is **not** named in
    :data:`_DEFERRED_TO_A_LATER_LANE` is the failure ADR-0242 §9 is about — "a surface
    that renders **no** statement for a member is a surface that has not implemented this
    section, not a permitted degradation" — and a member that renders something and *is*
    named there is a deferral somebody forgot to retire. Both are caught here, which is
    what makes the parametrised case below a narrowing of the vocabulary rather than a
    hole in it.
    """
    silent = set()
    for member in ForecastNotRead:
        buffer = StringIO()
        console = Console(file=buffer, force_terminal=False, width=100)
        original = cli.console
        cli.console = console
        try:
            cli._render_forecast_not_read(member)
        finally:
            cli.console = original
        if not _flat(buffer.getvalue()).strip():
            silent.add(member)

    assert silent == set(_DEFERRED_TO_A_LATER_LANE), (
        "every member this surface renders nothing for is one a lane is recorded as "
        "owing, and every member so recorded still renders nothing (ADR-0260 §10)"
    )
    assert set(_STATEMENTS) | set(_DEFERRED_TO_A_LATER_LANE) == set(ForecastNotRead), (
        "and the two together are the whole vocabulary"
    )


@pytest.mark.parametrize(
    "member", [one for one in ForecastNotRead if one not in _DEFERRED_TO_A_LATER_LANE]
)
def test_every_member_renders_a_statement(member: ForecastNotRead, output: StringIO) -> None:
    """§10: "one fixed statement per member", in the words §10 fixes.

    Parametrised over the vocabulary itself, so a seventh member arriving with the ADR
    that decides it fails here rather than rendering nothing in a user's terminal — the
    #1113 rule at this vocabulary, and ``SearchNotServiced``'s own arrangement.
    """
    cli._render_forecast_not_read(member)
    rendered = _flat(output.getvalue())

    assert rendered.strip(), f"{member} renders nothing"
    for fragment in _STATEMENTS[member]:
        assert fragment in rendered, f"{member}: {fragment}"


def test_no_statement_is_rendered_for_a_turn_that_read_its_forecast(output: StringIO) -> None:
    """§10: ``None`` "means the servicing recorded no ``ForecastDisposition``, and means
    nothing else" — a turn that serviced no forecast read, and a read the provider
    answered. The surface then says nothing about a forecast at all.
    """
    cli._render_forecast_not_read(None)

    assert output.getvalue() == ""


def test_no_two_members_render_the_same_statement() -> None:
    """A member rendering as another member names neither.

    ``_outbound_destination``'s ratified arm, one vocabulary over: ADR-0260 §10 makes the
    fold from §8's twelve dispositions non-injective **on purpose**, so the six that
    survive it are the whole of what the user can be told apart — and two of them sharing
    a sentence would collapse the distinction the fold was built to keep.
    """
    said = {}
    for member in ForecastNotRead:
        buffer = StringIO()
        console = Console(file=buffer, force_terminal=False, width=100)
        original = cli.console
        cli.console = console
        try:
            cli._render_forecast_not_read(member)
        finally:
            cli.console = original
        said[member] = _flat(buffer.getvalue())

    assert len(set(said.values())) == len(ForecastNotRead)


# --- ADR-0242 §9's bar, binding on this vocabulary word for word -------------


@pytest.mark.parametrize("member", list(ForecastNotRead))
def test_no_statement_names_a_place_a_provider_or_a_setting(
    member: ForecastNotRead, output: StringIO
) -> None:
    """§10: "No statement names a floor, a threshold, a ``Settings`` field, a
    configuration value, a provider, an origin, a place or a coordinate."

    Asserted over the rendered bytes and not over an intention. The ``Settings`` fields
    ADR-0260 §11 adds are the nine named ``forecast_*``, so the prefix is asserted rather
    than each of them; and no ``ForecastDisposition`` value appears, which is the
    vocabulary §8 keeps for the operator's audit and §10 keeps off the user's screen.
    """
    cli._render_forecast_not_read(member)
    rendered = _flat(output.getvalue())

    assert not any(character.isdigit() for character in rendered)
    for forbidden in ("http", "://", "@", "$", "£", "forecast_", "latitude", "longitude"):
        assert forbidden not in rendered.lower(), f"{member}: {forbidden}"
    for stage in ForecastDisposition:
        assert stage.value not in rendered, f"{member}: {stage.value}"


@pytest.mark.parametrize("member", list(ForecastNotRead))
def test_no_statement_promises_the_next_read_or_says_why_a_ruling_was_not_an_allow(
    member: ForecastNotRead, output: StringIO
) -> None:
    """§10, quoting ADR-0242 §9's bar: "no statement says that performing the act it names
    will make the next read happen, and none says why a ruling was not an ``ALLOW``".

    ``will`` is the whole of the first clause on this surface — a sentence with no future
    tense cannot promise the next read — and ``because`` is the second's: a statement that
    explained itself would be saying why a ruling went the way it did. The remaining
    fragments are the near misses a reassuring draft reaches for.
    """
    cli._render_forecast_not_read(member)
    rendered = _flat(output.getvalue()).lower()

    for forbidden in (
        "will",
        "because",
        "try again",
        "then it",
        "once you",
        "no authorisation",
        "not authorised",
        "would have",
    ):
        assert forbidden not in rendered, f"{member}: {forbidden}"


def test_only_the_awaited_statement_names_a_command_and_it_names_decisions(
    output: StringIO,
) -> None:
    """§10's fixed half: "what is fixed is which command each names and that
    ``UNAVAILABLE`` names none".

    ``AUTHORISATION_AWAITED`` names ``assistant decisions``; ``NOT_CONFIGURED`` names "no
    user act" because there is none, ``SPEND_EXHAUSTED`` names "an operator setting and no
    user act", and ``UNAVAILABLE`` names "no cause and no act".

    **And it names neither act a parked read would have.** ADR-0260 §11 mints no park for
    a forecast read, so the question is a recorded decision and never a resumable one:
    ``assistant resume``, ``assistant cancel-read`` and ``assistant remember-recipients``
    would each send a user to a listing this read is not in. That is the one place this
    vocabulary's ``AUTHORISATION_AWAITED`` differs from ``SearchNotServiced``'s, which
    names ``assistant remember-recipients``.
    """
    for member in ForecastNotRead:
        cli._render_forecast_not_read(member)
        rendered = _flat(output.getvalue())
        output.truncate(0)
        output.seek(0)
        names_a_command = member is ForecastNotRead.AUTHORISATION_AWAITED
        assert ("'assistant decisions'" in rendered) is names_a_command, member
        assert ("assistant " in rendered) is names_a_command, member
        for barred in ("assistant resume", "assistant cancel-read", "remember-recipients"):
            assert barred not in rendered, f"{member}: {barred}"


def test_the_unavailable_statement_names_no_cause_and_no_act(output: StringIO) -> None:
    """§10: ``UNAVAILABLE`` "says the read produced nothing the turn could use, **naming
    no cause and no act**", and "for a response that was refused after it arrived it does
    **not** say that no request was made".

    Seven dispositions fold onto it and two of them — ``RESPONSE_TOO_LARGE`` and
    ``UNATTESTED`` — reached the provider, so a sentence saying nothing was sent would be
    false on exactly those.
    """
    cli._render_forecast_not_read(ForecastNotRead.UNAVAILABLE)
    rendered = _flat(output.getvalue()).lower()

    assert "produced nothing this turn could use" in rendered
    for forbidden in (
        "nothing was sent",
        "no request",
        "never left",
        "did not leave",
        "failed",
        "error",
    ):
        assert forbidden not in rendered, forbidden


def test_the_not_configured_statement_names_no_user_act(output: StringIO) -> None:
    """§10: it says a forecast source is not configured in this deployment and that it is
    an operator setting, **naming no user act** — "there is none, and naming one that
    cannot help is worse than naming none"."""
    cli._render_forecast_not_read(ForecastNotRead.NOT_CONFIGURED)
    rendered = _flat(output.getvalue()).lower()

    assert "no forecast source is configured in this deployment" in rendered
    assert "operator setting" in rendered
    for forbidden in ("assistant ", "you can", "you configure", "set up", "enable", "ask an"):
        assert forbidden not in rendered, forbidden


def test_the_declined_statement_says_only_what_the_ruling_did(output: StringIO) -> None:
    """§10: it "says the read was declined when it was ruled on, and names no floor, no
    threshold and no ``Settings`` field".

    And it stands unchanged on a turn that was denied and then answered — "a later read
    does not clear it" — so it must not say a forecast is absent from the reply.
    """
    cli._render_forecast_not_read(ForecastNotRead.DECLINED)
    rendered = _flat(output.getvalue()).lower()

    assert "declined when it was ruled on" in rendered
    for forbidden in ("no forecast", "nothing about", "policy", "threshold", "denied"):
        assert forbidden not in rendered, forbidden


# --- §10's placement: beside the reply and never in place of it --------------


async def test_the_statement_stands_beside_the_reply_and_never_in_place_of_it(
    output: StringIO,
) -> None:
    """§10: "beside the reply and never in place of it".

    Driven through the production :func:`cli._render_turn`, so what is asserted is the
    order a user actually reads rather than a call this module made itself.
    """
    reply = "I did not look at a forecast just now."
    base = await _composed()
    cli._render_turn(
        base.model_copy(update={"reply": reply, "forecast_not_read": ForecastNotRead.DECLINED})
    )
    rendered = _flat(output.getvalue())

    assert reply in rendered
    assert rendered.index(reply) < rendered.index("declined when it was ruled on")


async def test_both_statements_are_rendered_where_a_turn_carries_a_search_and_a_forecast(
    output: StringIO,
) -> None:
    """ADR-0260 §10's member is a vocabulary of its own and not a case of ADR-0242 §9's.

    A revising turn can service a search and a forecast read and have both refused, and
    the two members are computed at different sites from different dispositions. Neither
    is read off the other — §10: "the fact is never derived from ``ForecastNotRead``,
    which is non-injective by design" — and neither suppresses nor qualifies the other,
    which is what this asserts: both lines, on one screen.
    """
    base = await _composed()
    cli._render_turn(
        base.model_copy(
            update={
                "forecast_not_read": ForecastNotRead.NOT_CONFIGURED,
                "search_not_serviced": SearchNotServiced.UNAVAILABLE,
            }
        )
    )
    rendered = _flat(output.getvalue())

    assert "that lookup produced nothing this turn could use" in rendered
    assert "no forecast source is configured in this deployment" in rendered


async def test_an_outbound_contact_and_an_unavailable_forecast_ride_together(
    output: StringIO,
) -> None:
    """ADR-0264 §8's both-statements rule, at this seam (ADR-0260 §10).

    "A contact and an ``UNAVAILABLE`` ride together where both hold — a
    ``RESPONSE_TOO_LARGE`` or an ``UNATTESTED`` reached the provider and yielded nothing
    usable — which is ADR-0264 §8's both-statements rule and not an exception to it." Read
    together they say a request was made and nothing usable came back, and **neither is
    derived from the other**.
    """
    base = await _composed()
    cli._render_turn(
        base.model_copy(
            update={
                "forecast_not_read": ForecastNotRead.UNAVAILABLE,
                "outbound_statement": OutboundStatement(
                    reach=OutboundReach.REACHED,
                    destinations=(OutboundDestination.FORECAST_PROVIDER,),
                ),
            }
        )
    )
    rendered = _flat(output.getvalue())

    assert "this turn reached outside this system" in rendered
    assert "that forecast read produced nothing this turn could use" in rendered


@pytest.mark.parametrize("member", list(ForecastNotRead))
async def test_no_action_was_needed_is_not_printed_beside_a_forecast_statement(
    member: ForecastNotRead, output: StringIO
) -> None:
    """Adversarial review, round 1, ``major``: the contradiction on one screen.

    A forecast read is serviced in context assembly and not as a plan step, so a turn
    whose planner then declined every capability reaches :func:`cli._render_turn` with an
    empty plan while ``forecast_not_read`` says a read it asked for did not happen. "No
    action was needed." beside "that forecast read was begun and stopped" says both that
    nothing was owed and that something was attempted and stopped.

    **Parametrised over all six, because this vocabulary has no member for having
    attempted nothing.** ``_reached_outside``'s arm one vocabulary over guards ``REACHED``
    alone — ``OutboundReach`` *has* such a member, and "a turn that reached nothing is
    exactly a turn of which 'no action was needed' may well be true". ADR-0260 §10 fixes
    the absence as the state where the servicing "recorded no ``ForecastDisposition``", so
    ``None`` is where this guard stays off and every member is a turn that asked.
    """
    base = await _composed()
    assert base.turn is not None
    assert not base.turn.plan.steps, "the arm is about a turn that planned nothing"
    cli._render_turn(base.model_copy(update={"forecast_not_read": member}))
    rendered = _flat(output.getvalue())

    assert "No action was needed." not in rendered, member
    for fragment in _STATEMENTS[member]:
        assert fragment in rendered, f"{member}: {fragment}"


async def test_no_action_was_needed_still_prints_where_no_forecast_was_asked_for(
    output: StringIO,
) -> None:
    """The control the arm above needs to mean anything.

    A guard that suppressed the notice unconditionally would pass every case above and
    would have removed a true statement from every ordinary turn. ADR-0260 §10's ``None``
    is a turn that serviced no forecast read *or* one the provider answered, and "no
    action was needed" may well be true of it.
    """
    cli._render_turn(await _composed())

    assert "No action was needed." in _flat(output.getvalue())


# --- end to end, over the canonical fake's own lever -------------------------


def test_the_statement_reaches_a_user_driving_assistant_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole path, from the member the engine carries to the bytes on the terminal.

    This is the one thing the unit arms above cannot show: that ``ask`` reaches
    :func:`cli._render_forecast_not_read` at all. ``FakeAssistantEngine`` gained
    :attr:`~ai_assistant.testing.FakeAssistantEngine.forecast_not_read` for it — no
    sequence of surface calls on that double records a ``ForecastDisposition``, so every
    one of the six would otherwise be unreachable from a consumer's test.
    """
    engine = FakeAssistantEngine()
    engine.forecast_not_read = ForecastNotRead.SPEND_EXHAUSTED
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["ask", "will it rain tomorrow?", "--yes"])
    rendered = _flat(result.output)

    assert result.exit_code == 0
    assert "a spending ceiling refused that forecast read" in rendered
    assert "operator setting" in rendered


def test_a_default_fake_turn_says_nothing_about_a_forecast_driving_assistant_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And the default reaches the same screen as silence, which §10 fixes the meaning of.

    ``None`` "means the servicing recorded no ``ForecastDisposition``, and means nothing
    else". A fake wires no forecaster and services no read, so it has recorded none — and
    a turn composed under it says nothing about a forecast to the user.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["ask", "will it rain tomorrow?", "--yes"])

    assert result.exit_code == 0
    assert "forecast" not in _flat(result.output).lower()


# --- ADR-0262 §11's parity point, over the two surfaces' own words -----------


def test_the_two_surfaces_name_the_same_command_for_the_same_member() -> None:
    """ADR-0262 §11: "both surfaces, since a member rendered on one and not the other is
    the parity failure M4 recorded."

    ADR-0260 §10 leaves the wording to the lane and fixes which command each member names,
    so what is asserted is the fixed half rather than an identity of prose: the same member
    names the same command on both surfaces, and the five that name none name none on
    either. The browser's six are read out of the shipped bundle, which is where that
    surface's obligation is discharged.
    """
    script = _APP_JS.read_text(encoding="utf-8")
    opened = script.index("\nconst FORECAST_NOT_READ_WORDS = {")
    block = script[opened : script.index("\n};", opened)]
    parts = re.split(r"^  (\w+):", block, flags=re.MULTILINE)
    browser = {
        parts[index]: "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', parts[index + 1]))
        for index in range(1, len(parts), 2)
    }

    assert set(browser) == {member.value for member in ForecastNotRead}
    for member in ForecastNotRead:
        buffer = StringIO()
        console = Console(file=buffer, force_terminal=False, width=100)
        original = cli.console
        cli.console = console
        try:
            cli._render_forecast_not_read(member)
        finally:
            cli.console = original
        terminal = _flat(buffer.getvalue())
        names_a_command = member is ForecastNotRead.AUTHORISATION_AWAITED
        assert ("'assistant decisions'" in terminal) is names_a_command, member
        assert ("'assistant decisions'" in browser[member.value]) is names_a_command, member
