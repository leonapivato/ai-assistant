"""The command line's parked-read surface, clause by clause (ADR-0244 §18, Lane 3).

§18 gives this lane five things and every one of them is discharged in what the user
reads: "ADR-0178 §7's floor for a read's confirmation, the exact query rendered (§13),
the answer collected, the seven ``ReadAnswerOutcome`` statements, the ninth
``SearchNotServiced`` statement naming ``assistant resume``, and the cancellation act."
So every case here asserts over the **rendered bytes**, which is ADR-0242 §15's last
clause read one vocabulary over: those are the system's own words.

**Driven against the canonical fake, at the seam the obligation is about.** ADR-0244 §19
states its arms "over inputs and observable outcomes, never over an implementation's
internals", and each arm is "driven at the seam it is about rather than through a turn
that would have to violate a clause to reach it" — which for this surface means
``FakeAssistantEngine.park_read`` and the two levers beside it, since a real park is
reached only through a servicing this adapter may not have, and ``INTERRUPTED`` is
reachable through no sequence of surface calls at all.

**This is not ``test_cli_reads.py``** and the separation is deliberate: that module is
ADR-0186 §10's *source-read trail* — ``assistant reads``, ``assistant export-reads`` —
and shares nothing with a parked read but the word. Putting a parked read's cases there
would make one module answer two unrelated decisions.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import TYPE_CHECKING, Final

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.types import (
    BoundAccount,
    Confirmation,
    ConfirmationEgress,
    ContinuationToken,
    CostBasis,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ReadAnswerOutcome,
    ReadCancellation,
    ReadKind,
    Reversibility,
    RiskLevel,
    SearchNotServiced,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
    TurnOutcome,
)
from ai_assistant.interfaces import cli
from ai_assistant.orchestration.reads import SearchDisposition
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from collections.abc import Iterator

PATIENT: Final = timedelta(seconds=30)

#: The query every case parks, which is what §13's "exact query" clause is asserted
#: over. It carries a capital, a space run and punctuation on purpose: a surface that
#: re-cased, normalised or re-wrapped the query would still render *a* query, and the
#: only way to catch that is to park one that does not survive those operations.
QUERY: Final = "Torre dos Clérigos  opening hours, 2026?"

#: When the read's ``CONFIRM`` was recorded. Before the fake's own fixed reading,
#: because ADR-0235 §4 refuses a resolution decided before the confirmation it
#: answers and the answer this fake stamps carries that reading.
AT: Final = datetime(2026, 1, 1, 11, tzinfo=UTC)

#: An instant safely after the fake's own fixed reading, which every answer it records
#: carries — ADR-0235 §1 refuses an expiry that is not strictly after it.
LATER: Final = datetime(2027, 1, 1, 12, tzinfo=UTC)


def _binding(*, planned: bool = False) -> EgressBinding:
    """The binding a ``WEB_SEARCH`` park's ruling was taken over.

    ADR-0244 §4: on such a park ``egress`` is **always** present, because ADR-0231 §5
    registers the search integration at the egress seam. So a case that parked without
    one would be exercising a shape this hub cannot produce.
    """
    return EgressBinding(
        spans=(
            EgressSpan(
                argument="query",
                index=None,
                provenance=DiscloserProvenance.SYSTEM_SELECTED,
                extent=len(QUERY),
                destination=EgressDestination(
                    protocol=DestinationProtocol.HTTPS,
                    supplied="Search.Example",
                    canonical="search.example",
                ),
            ),
        ),
        account=BoundAccount(reference="search-account", identity="owner@example.com"),
        transport_endpoint="https://search.example",
        planned_with_external_content=planned,
        coverage=SpanCoverage.NOT_COVERED,
    )


def _confirm(*, planned: bool = False) -> PermissionDecision:
    """The recorded ``CONFIRM`` a read park names, for the act that rides its answer.

    ADR-0235 §2 has the establishing act ride *the answer to a recorded ``CONFIRM``*,
    and the grant is transcribed from that decision rather than from the reduced
    ``ConfirmationEgress`` a surface holds — so a case driving the act hands the
    decision over rather than having the fake invent a call-level fact.
    """
    return PermissionDecision(
        id="decision-1",
        ruling=PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="it would leave here"),
        tool=ToolDefinition(
            id="web_search",
            capability="search_web",
            description="Ask one connected search account a question.",
            risk_level=RiskLevel.LOW,
            reversibility=Reversibility.REVERSIBLE,
            side_effecting=True,
            reads=(),
            writes=(),
            discloses=(DataTier.PERSONAL,),
            cost=ToolCost(basis=CostBasis.FREE),
            idempotency=Idempotency.NATURAL,
        ),
        parameters_digest="d" * 64,
        decided_at=AT,
        egress_binding=_binding(planned=planned),
    )


def _question(handle: str = "h-1") -> Confirmation:
    """One read's confirmation, as a servicing site would assemble it (§4)."""
    egress = _binding()
    return Confirmation(
        tool_id="web_search",
        tool_description="asks one connected search account a question",
        parameters={"origin": "search.example", "query": QUERY},
        reason="this lookup would leave the device, so it is put to you as a question",
        token=ContinuationToken(handle=handle),
        egress=ConfirmationEgress(
            account_identity=egress.account.identity,
            spans=egress.spans,
            planned_with_external_content=egress.planned_with_external_content,
            coverage=egress.coverage,
        ),
        read=ReadKind.WEB_SEARCH,
    )


def _step_question(handle: str = "h-step") -> Confirmation:
    """The same card with ``read`` absent — ADR-0244 §19's Arm 8 at this surface."""
    return _question(handle).model_copy(update={"read": None})


def _parked(handle: str = "h-1", *, planned: bool = False) -> FakeAssistantEngine:
    """A fake holding exactly one open read park, with its binding."""
    engine = FakeAssistantEngine()
    engine.park_read(handle, query=QUERY, egress=_binding(planned=planned))
    return engine


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer wide enough that nothing wraps."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=400))
    return buffer


@pytest.fixture
def narrow(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """A console too narrow to mark a value as data (ADR-0233 §8)."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=6))
    return buffer


def _flat(rendered: str) -> str:
    """Collapse Rich's wrapping and its continuation marker, so a case asserts words.

    **Never used to assert the query**, which carries a run of spaces this collapses:
    ADR-0244 §13's clause is about the bytes, and a query that only survives flattening
    is one the clause does not protect. Those assertions are over the raw screen.
    """
    return " ".join(rendered.replace("↳", " ").split())


def _squashed(rendered: str) -> str:
    """The screen with **every** space removed, for a window too narrow to hold words.

    At six columns Rich breaks inside words, so the only thing a case can say about a
    withheld card there is which sentence it is — and that survives only with the
    spacing gone.
    """
    return "".join(rendered.replace("↳", "").split())


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


def _answers() -> Iterator[ReadAnswerOutcome]:
    """Every member of the closed seven-member vocabulary (ADR-0244 §9)."""
    return iter(ReadAnswerOutcome)


# --- #2222 scenario 1 / ADR-0244 §19 Arm 1, at this surface ------------------
# "The question appears and nothing is sent." The engine half is Lane 1's; what is
# owed here is that the exchange that raised the question shows it, whole.


async def _parked_turn() -> TurnOutcome:
    """One turn that parked a read, built through the fake's own ``converse``.

    ``TurnOutcome`` refuses a reply beside a ``None`` turn, so an arm about what a
    *composed* turn renders needs a real :class:`~ai_assistant.core.types.TurnResult`
    behind it — ADR-0244 §19's Arm 1 is stated over exactly that shape: the turn "does
    not park … and whose reply — composed from the fixed fragment for ``ANSWER_AWAITED``
    — says a lookup awaits an answer".
    """
    engine = FakeAssistantEngine()
    composed = await engine.converse("when does it open?", timeout=PATIENT)
    return TurnOutcome(
        turn=composed.turn,
        reply=composed.reply,
        search_not_serviced=SearchNotServiced.ANSWER_AWAITED,
        read_confirmation=_question(),
    )


async def test_a_turn_that_parked_a_read_renders_the_floor_the_query_and_what_a_yes_does(
    output: StringIO,
) -> None:
    """§13's three clauses and ADR-0178 §7's floor, on one screen, before any answer.

    Driven through the production :func:`cli._render_turn`, so what is asserted is what
    a user reading the reply actually sees rather than a call this case made itself.
    """
    cli._render_turn(await _parked_turn())
    rendered = _flat(output.getvalue())

    # ADR-0178 §7's floor entire, from the one implementation both paths share.
    assert "owner@example.com" in rendered, "the account identity"
    assert "Search.Example" in rendered, "the supplied form"
    assert "search.example" in rendered, "and the canonical one"
    assert "query" in rendered, "the occurrence, by the argument it was selected by"
    # ADR-0244 §13's exact query, byte for byte — asserted over the **raw** screen,
    # because :func:`_flat` collapses the run of spaces the query carries and a query
    # that only survives flattening is one this clause does not protect.
    assert QUERY in output.getvalue()
    # §13's one sentence, and no more than it.
    assert "Answering yes makes this one lookup, once, and nothing else." in rendered
    # §13's cancellation act, offered at the question, as a command that pastes.
    assert "assistant cancel-read h-1" in rendered
    # §1: the turn did not park, so nothing is being collected here.
    assert "Nothing is being asked of you right now" in rendered


async def test_the_screen_beside_a_parked_read_never_says_the_lookup_produced_nothing(
    output: StringIO,
) -> None:
    """#2221's literal, which ADR-0244 §12 exists to stop being said.

    The reply says a lookup awaits an answer; the ninth statement names where it is
    answered; and nowhere on the screen is the sentence the dead end was made of.
    """
    cli._render_turn(await _parked_turn())
    rendered = _flat(output.getvalue())

    assert "waiting on your answer" in rendered
    assert "assistant resume" in rendered
    assert QUERY in output.getvalue()
    assert "produced nothing" not in rendered
    assert "nothing this turn could use" not in rendered


def test_the_query_is_rendered_whole_and_is_never_re_cased_or_re_wrapped(
    output: StringIO,
) -> None:
    """§13: no abbreviation, elision, truncation, re-casing, normalisation or re-quoting.

    The parked query carries a capital, a double space and punctuation, none of which
    survives a "tidy" rendering — so a surface that normalised it fails here rather
    than passing on a query that happened to be already normal.
    """
    cli._render_parked_read(_question())
    rendered = output.getvalue()

    assert QUERY in rendered
    assert QUERY.lower() not in rendered.replace(QUERY, ""), "no second, folded copy"


def test_every_argument_is_rendered_and_no_key_is_privileged(output: StringIO) -> None:
    """§4: ``parameters`` is "the origin and the composed query", and both are shown.

    The adapter does not look for a key called ``query``: which argument carries the
    composed query is the searcher's own declaration, and an adapter that knew it would
    be reading a tool's schema in ``interfaces/`` (golden rule 3).
    """
    cli._render_parked_read(_question())
    rendered = _flat(output.getvalue())

    assert "What it would ask, whole:" in rendered
    assert "origin:" in rendered
    assert "query:" in rendered


def test_a_step_confirmation_is_unchanged_and_carries_no_read_block(
    output: StringIO,
) -> None:
    """§19's Arm 8 at this surface: "a step's confirmation is unchanged"."""
    assert cli._render_confirmation(_step_question())
    rendered = _flat(output.getvalue())

    assert "Confirmation required" in rendered
    assert "A lookup is waiting on your answer" not in rendered
    assert "What it would ask, whole:" not in rendered
    assert "assistant cancel-read" not in rendered


def test_a_reads_question_with_no_recipient_facts_is_refused_rather_than_rendered_thin(
    output: StringIO,
) -> None:
    """ADR-0244 §13's permitted refusal, taken on the discriminator §4 gives it.

    §13 owes "ADR-0178 §7's floor **entire**" for a read's confirmation and says being
    a read relaxes no clause of it, so a card that could show neither the account nor
    the recipients is one §13 says "has not implemented this section". ADR-0244 §4
    rules the shape unreachable on a ``WEB_SEARCH`` park — ``egress`` "is always
    present" there — so what this pins is the conservative arm of a case that cannot
    arise rather than a behaviour a hub produces, and §13 licenses it in terms: "what a
    surface may do is **refuse** a confirmation it cannot render".
    """
    assert not cli._render_confirmation(_question().model_copy(update={"egress": None}))
    rendered = _flat(output.getvalue())

    assert "Confirmation withheld" in rendered
    assert "where this lookup would go" in rendered
    assert "the question is still open" in rendered, "a read holds no step to be waiting"
    assert QUERY not in output.getvalue()


def test_a_terminal_too_narrow_to_mark_the_query_as_data_withholds_the_card(
    narrow: StringIO,
) -> None:
    """ADR-0233 §8's second clause, on the block ADR-0244 §13 added.

    A read's arguments sit behind the same gutter a span's value does and carry the
    same claim, so a window that cannot hold the marker withholds the card rather than
    printing the query with nothing marking it as data.
    """
    assert not cli._render_confirmation(_question())

    assert "Confirmationwithheld" in _squashed(narrow.getvalue())
    assert "Clérigos" not in _squashed(narrow.getvalue()), "no fragment of the query"
    assert "Whatitwouldask" not in _squashed(narrow.getvalue())


# --- #2222 scenario 2 / Arm 2, at this surface -------------------------------


async def test_resume_answers_a_parked_read_and_says_it_was_made_once(
    output: StringIO,
) -> None:
    """The answer collected, relayed, and its member stated (§18, §9).

    ``pending_confirmations`` offers the park, the card is rendered before the answer
    is collected, and the approving answer comes back ``DISPATCHED``.
    """
    engine = _parked()

    code = await cli._drive_resume(engine, timeout=PATIENT, approver=lambda _c: True)
    rendered = _flat(output.getvalue())

    assert code == 0
    assert "A lookup is waiting on your answer" in rendered
    assert QUERY in output.getvalue()
    assert "you approved that lookup and it was made, once" in rendered
    assert [name for name, _ in engine.calls] == ["pending_confirmations", "resume"], (
        "one listing and one answer: no adapter reads a store (ADR-0244 §13)"
    )


async def test_a_second_answer_on_the_same_token_states_the_settled_question(
    output: StringIO,
) -> None:
    """§19's Arm 2, second half: "a second ``resume`` … returns ``ALREADY_SETTLED``"."""
    engine = _parked()
    await cli._drive_resume(engine, timeout=PATIENT, approver=lambda _c: True)
    settled = await engine.resume(ContinuationToken(handle="h-1"), approved=True, timeout=PATIENT)
    output.truncate(0)
    output.seek(0)

    cli._render_turn(settled)
    rendered = _flat(output.getvalue())

    assert settled.read_answer is ReadAnswerOutcome.ALREADY_SETTLED
    assert "had already been settled" in rendered
    assert "nothing was sent and nothing was recorded" in rendered
    assert "the answer that settled it" not in rendered, (
        "a withdrawal settles a park and records no answer (ADR-0244 §11)"
    )


# --- #2222 scenario 3 / Arm 3 ------------------------------------------------


async def test_declining_a_parked_read_says_nothing_was_sent_and_the_reply_stands(
    output: StringIO,
) -> None:
    """§10: ``turn`` and ``reply`` ``None``, and the parked turn's own reply stands."""
    engine = _parked()

    code = await cli._drive_resume(engine, timeout=PATIENT, approver=lambda _c: False)
    rendered = _flat(output.getvalue())

    assert code == 0
    assert "that lookup was declined" in rendered
    assert "Nothing was sent" in rendered
    assert "stands unchanged" in rendered


# --- #2222 scenario 5 / Arm 5, and scenario 6 / Arm 6 ------------------------


async def test_an_expired_question_is_told_apart_from_one_that_was_answered(
    output: StringIO,
) -> None:
    """§10: the expiry is a settlement, so the surface says *that lookup expired*
    rather than *no such question* — and never the sentence for a settled one."""
    engine = _parked()
    engine.read_answers["h-1"] = ReadAnswerOutcome.EXPIRED

    await cli._drive_resume(engine, timeout=PATIENT, approver=lambda _c: True)
    rendered = _flat(output.getvalue())

    assert "ran out of time before it was answered" in rendered
    assert "It cannot be answered now" in rendered
    assert "had already been settled" not in rendered
    assert "no such question" not in rendered


@pytest.mark.parametrize(
    ("member", "fragment"),
    [
        (ReadAnswerOutcome.AUTHORITY_CHANGED, "Your answer was recorded"),
        (ReadAnswerOutcome.OPERATION_CHANGED, "as the question you were shown described it"),
        (ReadAnswerOutcome.UNAVAILABLE_NOW, "cannot be made here now"),
    ],
)
async def test_a_refused_answer_says_the_lookup_was_not_made(
    member: ReadAnswerOutcome, fragment: str, output: StringIO
) -> None:
    """§19's Arm 6 at this surface: each refusal has its own statement, and each says
    the lookup was not made rather than reporting a lookup that happened."""
    engine = _parked()
    engine.read_answers["h-1"] = member

    await cli._drive_resume(engine, timeout=PATIENT, approver=lambda _c: True)
    rendered = _flat(output.getvalue())

    assert fragment in rendered
    assert "it was made, once" not in rendered


# --- the seven statements, as a closed vocabulary ---------------------------


@pytest.mark.parametrize("member", list(_answers()))
def test_every_read_answer_member_renders_a_statement(
    member: ReadAnswerOutcome, output: StringIO
) -> None:
    """§13: "A surface that renders no statement for a ``ReadAnswerOutcome`` member it
    was given … has not implemented this section — it is not permissibly degraded."

    Parametrised over the vocabulary itself, so a member added without its statement
    fails here rather than rendering nothing in a user's terminal.
    """
    cli._render_read_answer(member)

    assert _flat(output.getvalue()).strip(), f"{member} renders nothing"


def test_no_statement_is_rendered_where_no_parked_read_was_answered(
    output: StringIO,
) -> None:
    """§9: ``read_answer`` is ``None`` on every outcome that answered none, and the
    surface then says nothing about a parked lookup at all."""
    cli._render_read_answer(None)

    assert output.getvalue() == ""


@pytest.mark.parametrize("member", list(_answers()))
def test_no_read_answer_statement_carries_a_figure_a_party_or_a_vocabulary_token(
    member: ReadAnswerOutcome, output: StringIO
) -> None:
    """§9's bar, asserted over the rendered bytes and not over an intention.

    No statement carries a destination, a host, an origin, a provider name, an account
    identity, a query or any fragment of one, a monetary figure, a budget, a threshold,
    a ``Settings`` field name or a ``SearchNotServiced`` or ``SearchDisposition``
    value.

    **The token test is over the machine spelling and not over English words.** A
    vocabulary's *value* is its snake-cased name, which is what a surface would be
    leaking if it printed one; "declined" is an ordinary English word before it is
    anything else, and ADR-0242's own ratified statement for
    ``SearchNotServiced.DECLINED`` prints it.
    """
    cli._render_read_answer(member)
    rendered = _flat(output.getvalue())

    assert not any(character.isdigit() for character in rendered)
    for forbidden in ("http", "@", "$", "£", "search_calls_per_conversation", QUERY):
        assert forbidden not in rendered
    for vocabulary in (SearchNotServiced, SearchDisposition, ReadAnswerOutcome):
        for one in vocabulary:
            if "_" in one.value:
                assert one.value not in rendered


def test_the_dispatched_statement_claims_the_lookup_was_made_and_nothing_more(
    output: StringIO,
) -> None:
    """§8's split: the turn and the reply carry what the read produced, and this line
    describes neither. It does not say the lookup succeeded, found anything, or that
    the answer above is better for it."""
    cli._render_read_answer(ReadAnswerOutcome.DISPATCHED)
    rendered = _flat(output.getvalue()).lower()

    for forbidden in ("succeeded", "found", "worked", "useful", "answer above"):
        assert forbidden not in rendered


def test_the_two_changed_statements_differ_on_whether_the_answer_was_recorded(
    output: StringIO,
) -> None:
    """§9: ``AUTHORITY_CHANGED``'s ruling "**is** recorded"; ``OPERATION_CHANGED``'s
    park state is split across its three grounds, so its statement claims neither."""
    cli._render_read_answer(ReadAnswerOutcome.AUTHORITY_CHANGED)
    authority = _flat(output.getvalue())
    output.truncate(0)
    output.seek(0)
    cli._render_read_answer(ReadAnswerOutcome.OPERATION_CHANGED)
    operation = _flat(output.getvalue())

    assert "Your answer was recorded" in authority
    assert "recorded" not in operation


# --- #2222 scenario 7 / Arm 7: the cancellation act -------------------------


async def test_cancelling_an_open_question_withdraws_it_and_records_no_answer(
    output: StringIO,
) -> None:
    """§11: ``WITHDRAWN`` — "an ``OPEN`` park was settled ``CANCELLED`` and nothing was
    ever sent", and the statement says it recorded no answer, which is the whole
    difference from a denial."""
    engine = _parked()

    code = await cli._drive_cancel_read(engine, "h-1")
    rendered = _flat(output.getvalue())

    assert code == 0
    assert "That question is withdrawn." in rendered
    assert "not the same as saying no" in rendered
    assert [name for name, _ in engine.calls] == ["cancel_read"], (
        "one call, and no store read to find out what state the park was in"
    )
    assert await engine.pending_confirmations() == (), "the question is gone"


async def test_cancelling_a_dispatch_in_flight_never_says_the_request_did_not_leave(
    output: StringIO,
) -> None:
    """§11: "a cancelled dispatch leaves the park ``APPROVED`` and does not re-open it
    … no caller assumes the query did not leave"."""
    engine = _parked()
    engine.dispatching_read("h-1")

    code = await cli._drive_cancel_read(engine, "h-1")
    rendered = _flat(output.getvalue())

    assert code == 0
    assert "stopped while it was running" in rendered
    assert "I cannot tell you the request never left" in rendered
    assert "asking again is a fresh request" in rendered
    for forbidden in ("nothing was sent", "did not leave", "answer it again"):
        assert forbidden not in rendered.lower()


async def test_cancelling_a_settled_question_says_there_was_nothing_to_withdraw(
    output: StringIO,
) -> None:
    """§11: ``NOTHING_TO_CANCEL`` is scoped to this process — "no dispatch of it is
    running **here**" — and the act performed nothing, so the exit is non-zero."""
    engine = _parked()
    await engine.resume(ContinuationToken(handle="h-1"), approved=True, timeout=PATIENT)

    code = await cli._drive_cancel_read(engine, "h-1")
    rendered = _flat(output.getvalue())

    assert code == 1
    assert "There was nothing here for this to take." in rendered
    assert "withdrew nothing and interrupted nothing" in rendered


async def test_an_unknown_handle_is_a_typed_refusal_and_never_a_denial(
    output: StringIO,
) -> None:
    """§11 gives ``cancel_read`` ``resume``'s own rule, and ADR-0084 §7 is the clause:
    a token the engine does not hold yields one specific, typed refusal "and never a
    denial" — rendered here without a traceback and with a controlled exit code."""
    engine = _parked()

    code = await cli._drive_cancel_read(engine, "h-nothing")
    rendered = _flat(output.getvalue())

    assert code == 1
    assert "this token names no parked read" in rendered
    assert "withdraw" not in rendered.lower()
    assert await engine.pending_confirmations() != (), "the open question is untouched"


@pytest.mark.parametrize("member", list(ReadCancellation))
def test_every_cancellation_member_renders_a_statement(
    member: ReadCancellation, output: StringIO
) -> None:
    """§11's closed three-member vocabulary, each with its own fixed statement."""
    cli._render_read_cancellation(member)

    assert _flat(output.getvalue()).strip(), f"{member} renders nothing"


def test_the_command_is_named_and_takes_the_handle_the_question_printed() -> None:
    """ADR-0186 §9's rule at a new command: "a normative decision an operator cannot
    derive a working command from is one no test can pin". The spelling is pinned
    literally, and so is the sentence that keeps it apart from ``assistant reads``."""
    result = CliRunner().invoke(cli.app, ["cancel-read", "--help"])
    rendered = _help_text(result.output)

    assert result.exit_code == 0
    assert "Withdraw a lookup that is waiting on your answer" in rendered
    assert "no answer is recorded either way" in rendered
    assert "This is not assistant reads" in rendered


def test_a_blank_handle_is_refused_before_any_client_is_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0085 §3c at this command: the handle is ``Identifier``-shaped, so a blank one
    is a usage error during Typer's parsing rather than an uncaught ``ValueError``
    escaping the command's own boundary (ADR-0042 §7)."""
    engine = _parked()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["cancel-read", "   "])

    assert result.exit_code == 2
    assert engine.calls == []


# --- the flag that answers nothing here (ADR-0233 §8, ADR-0244 §13) ---------


def test_yes_does_not_answer_a_reads_question_and_leaves_it_open(
    output: StringIO,
) -> None:
    """ADR-0233 §8: a flag typed before the request existed answers more than one card
    and pre-selects an affirmative answer. It declines nothing either — ``None`` leaves
    the question open, which is ADR-0244 §10's "no terminal disposition is inferred
    from silence" at the one surface that could have inferred one."""
    assert cli._assume_yes(_question()) is None
    rendered = _flat(output.getvalue())

    assert "--yes does not answer this one." in rendered
    assert "It is a lookup that would leave this device" in rendered
    assert "the question is still open" in rendered
    assert "assistant resume" in rendered


async def test_a_yes_run_leaves_the_parked_read_standing_and_exits_non_zero(
    output: StringIO,
) -> None:
    """The flag's refusal, end to end: the question is still enumerable afterwards and
    the exit code does not let a script read "everything was resolved" off the run."""
    engine = _parked()

    code = await cli._drive_resume(engine, timeout=PATIENT, approver=cli._assume_yes)

    assert code == 1
    assert [one.token.handle for one in await engine.pending_confirmations()] == ["h-1"]
    assert [name for name, _ in engine.calls if name == "resume"] == []
    assert QUERY in output.getvalue(), "and the question was shown before the refusal"


# --- the standing request rides a read's answer exactly as it rides a step's ---


async def test_the_standing_request_rides_a_reads_answer_and_is_relayed_unrounded(
    output: StringIO,
) -> None:
    """ADR-0244 §5: the act "still rides an answer where a park holds the confirmation".

    The flag is relayed exactly as it is today — nothing here fills it in, rounds it or
    extends it (ADR-0235 §1) — and the read's card is the one it rides, which is what
    :func:`cli._may_ride_an_establishing_act` reads off ADR-0178 §7's rendered floor.
    """
    engine = _parked()
    confirmed = _confirm()
    await engine.trail.record(confirmed)
    engine.hold_confirmation_decision("h-1", confirmed)

    code = await cli._drive_resume(
        engine,
        timeout=PATIENT,
        approver=lambda _c: True,
        remember_recipients_until=LATER,
    )

    rendered = _flat(output.getvalue())

    assert code == 0
    assert "Recipients not remembered for this one" not in rendered
    assert "you approved that lookup and it was made, once" in rendered
    assert "Remembered." in rendered, "the act rode the answer (ADR-0244 §5)"
    assert cli._decided_at(LATER) in rendered, (
        "until the instant the user chose, unrounded and unextended (ADR-0235 §1)"
    )


async def test_a_read_planned_over_external_content_takes_the_answer_without_the_act(
    output: StringIO,
) -> None:
    """ADR-0235 §2 unchanged at a read's card: where the act may not ride, the answer is
    still collected and the user is told, rather than the whole call being refused and
    their answer lost with it."""
    engine = _parked(planned=True)

    code = await cli._drive_resume(
        engine,
        timeout=PATIENT,
        approver=lambda _c: True,
        remember_recipients_until=LATER,
    )
    rendered = _flat(output.getvalue())

    assert code == 0
    assert "Recipients not remembered for this one" in rendered
    assert "you approved that lookup and it was made, once" in rendered
    relayed = [arguments for name, arguments in engine.calls if name == "resume"]
    assert relayed == [{"token": "h-1", "approved": True}], (
        "the argument is absent rather than sent as a null (ADR-0085 §10)"
    )


def test_the_question_is_rendered_after_the_reply_and_never_in_place_of_it(
    output: StringIO,
) -> None:
    """ADR-0242 §9's ordering, carried onto ADR-0244 §9's two members.

    The reply is prose the user has by then read; the ninth statement says where the
    question is answered; the card is the question itself. A surface that rendered the
    card *instead* of the reply would be answering ADR-0244 §1's "the turn does not
    park" with a screen that says it did.
    """
    cli._render_turn(
        TurnOutcome(
            turn=None,
            capture_degraded=True,
            search_not_serviced=SearchNotServiced.ANSWER_AWAITED,
            read_confirmation=_question(),
        )
    )
    rendered = _flat(output.getvalue())

    assert rendered.index("this turn was not recorded") < rendered.index("assistant resume")
    assert rendered.index("assistant resume") < rendered.index("A lookup is waiting on your answer")


# --- round 1's three findings, each pinned where it would recur --------------


def test_the_nothing_to_cancel_statement_claims_nothing_about_what_is_running(
    output: StringIO,
) -> None:
    """Round 1, ``blocker``. ADR-0244 §11 returns this member on a race as well as on a
    dead park: "a cancellation that lost it answers ``NOTHING_TO_CANCEL`` where the
    answer is already running or done", and
    ``test_a_cancellation_that_lost_the_gate_interrupts_nothing`` drives that with the
    winning answer's dispatch held in flight. So a statement saying no lookup is
    running is false on a reachable path, and this one says the opposite in terms."""
    cli._render_read_cancellation(ReadCancellation.NOTHING_TO_CANCEL)
    rendered = _flat(output.getvalue()).lower()

    assert "no lookup is running" in rendered
    assert "it does not tell you" in rendered
    for forbidden in (
        "no lookup of it is running here",
        "nothing is running",
        "already settled and",
    ):
        assert forbidden not in rendered


def test_the_already_settled_statement_does_not_say_an_answer_stands(
    output: StringIO,
) -> None:
    """Round 1, ``major``. §9 covers "answered, denied **or cancelled**" with one
    member, and §11 says a cancellation "records no answer" — so naming *the answer
    that settled it* is false for every park a withdrawal took."""
    cli._render_read_answer(ReadAnswerOutcome.ALREADY_SETTLED)
    rendered = _flat(output.getvalue()).lower()

    assert "whatever settled it stands" in rendered
    for forbidden in ("the answer that settled", "your earlier answer", "the answer stands"):
        assert forbidden not in rendered


def test_the_offered_command_is_one_unbroken_line_at_an_ordinary_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 1, ``major``, #1023's half: :func:`cli._print` folds at the console width
    by inserting a real newline, so a hint wider than the screen pastes as **two**
    commands — the verb with no argument, and the argument as a command of its own.
    The offer therefore goes through :func:`cli._print_hint`, and this drives it at a
    width an ordinary terminal has with a handle long enough to overflow it."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=80))
    handle = "h-" + "0123456789" * 8

    cli._render_read_terms(_question(handle))
    offered = [one for one in buffer.getvalue().splitlines() if "cancel-read" in one]

    assert len(offered) == 1, "the command is one display line, not folded across two"
    assert f"assistant cancel-read {handle}" in offered[0]


@pytest.mark.parametrize(
    ("handle", "expected"),
    [
        ("h 1", "'h 1'"),
        ("h;rm -rf /", "'h;rm -rf /'"),
        ("h'1", "'h'\"'\"'1'"),
    ],
)
def test_a_handle_needing_quoting_is_offered_quoted(
    handle: str, expected: str, output: StringIO
) -> None:
    """Round 1, ``major``, #984's half: ``ContinuationToken.handle`` is an
    ``Identifier``, which requires encodability and nothing more — so an interior space
    or a shell metacharacter is admissible, and an unquoted line is a *valid* command
    against the wrong argument when pasted."""
    cli._render_read_terms(_question(handle))
    rendered = output.getvalue()

    assert f"assistant cancel-read {expected}" in rendered


def test_a_handle_the_terminal_cannot_show_withholds_the_command_and_says_so(
    output: StringIO,
) -> None:
    """Round 1, ``major``, #1013's half: :func:`cli._safe` *replaces* a character a
    terminal must not be handed, so a value carrying one renders — inside perfectly
    correct quotes — as a command naming something that does not exist. A wrong command
    is worse than no command, so the copyable line is withheld and the act is explained
    instead. The question itself is not withdrawn by that."""
    cli._render_read_terms(_question("h\x1b[2J1"))
    rendered = _flat(output.getvalue())

    assert "Withdraw it with 'assistant cancel-read'." in rendered
    assert "Its handle" in rendered
    assert "assistant cancel-read h" not in rendered
