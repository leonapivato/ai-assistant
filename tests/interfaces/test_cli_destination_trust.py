"""The terminal surface for the trust act, and the statement beside a reply (ADR-0242).

Three commands, four refusal renderings, one next-step line and eight statements.
ADR-0242 §5 fixes the command names **here rather than leaving them to the lane**, for
the reason ADR-0186 §9 fixed ``assistant decisions`` in terms — "a normative decision an
operator cannot derive a working command from is one no test can pin" — so the names are
pinned literally.

**Every outcome case is asserted over the rendered output**, because ADR-0242 §3's floor
and §9's eight statements are discharged in what the user reads and nowhere else. §15's
last clause is explicit that the eight surface statements are asserted "over their
rendered bytes, because those are the system's own words".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Final

import pytest
import typer.main
from rich.console import Console
from test_cli_decisions import _binding, _decision
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import (
    DuplicateDestinationTrustError,
    InvalidDestinationTrustError,
    UntrustableDestinationError,
)
from ai_assistant.core.types import (
    CanonicalDestination,
    DestinationProtocol,
    DestinationTrust,
    DestinationTrustRecord,
    PermissionOutcome,
    SearchNotServiced,
    TurnOutcome,
)
from ai_assistant.interfaces import cli
from ai_assistant.orchestration.reads import SearchDisposition
from ai_assistant.testing import FakeAssistantEngine

_AT: Final = datetime(2026, 5, 1, 9, tzinfo=UTC)

#: One recorded ``CONFIRM`` whose binding carries a clean footing — ADR-0242 §1's three
#: conditions, all satisfied, which is what makes the act available on it.
_ELIGIBLE: Final = _decision(
    "d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False)
)

#: The same row with ADR-0181 §4's fact set, which §1's third condition refuses: trust
#: recorded from a call a model reached *from* external content is the loop closing on
#: itself.
_EXTERNAL: Final = _decision(
    "d-2", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=True)
)

_RECORD: Final = DestinationTrustRecord(
    id="t-1",
    destinations=(
        CanonicalDestination(protocol=DestinationProtocol.SMTP, canonical="a@example.com"),
    ),
    trust=DestinationTrust.USER_CHOSEN,
    established_at=_AT - timedelta(days=1),
)


def _flat(rendered: str) -> str:
    """Collapse Rich's wrapping **and its continuation marker**, so an assertion is
    about words and not about the console width (#2072).

    :func:`cli._print` writes a ``↳`` onto every display line a line runs onto, so a
    helper that removed the break and kept the marker would leave one between two words
    of a single sentence — and a command name is exactly the sort of string that
    straddles a wrap.
    """
    return " ".join(rendered.replace("\u21b3", " ").split())


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=100))
    return buffer


class _TrailedEngine(FakeAssistantEngine):
    """A hub whose trail holds exactly the decisions a case seeds.

    ``FakeAssistantEngine`` is otherwise untouched, so the three trust members drive
    ADR-0242 §1's real conditions against a real trail rather than a scripted outcome —
    which is what makes a refusal here the refusal a production engine raises.
    """

    def __init__(self, *decisions: object) -> None:
        super().__init__()
        self.seeded = decisions


class _RefusingEngine(FakeAssistantEngine):
    """A hub whose trust act raises exactly what a case names.

    The four renderings ADR-0242 §5 fixes are read from the **type** of the refusal, so
    a case that could not choose the type could not drive them.
    """

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    async def establish_destination_trust(self, decision_id: object) -> DestinationTrustRecord:
        """Raise the scripted refusal, having written nothing."""
        raise self._error

    async def standing_destination_trust(self) -> tuple[DestinationTrustRecord, ...]:
        """Raise the scripted refusal on the listing too."""
        raise self._error

    async def revoke_destination_trust(self, record_id: object) -> bool:
        """Raise the scripted refusal on the revocation too."""
        raise self._error


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object) -> None:
    """Wire ``engine`` behind the one seam the commands obtain a client through.

    :func:`~ai_assistant.interfaces.cli._open_engine` and not ``build_engine``: after
    ADR-0084 §6 the CLI has no composition root to reach, it obtains a *client*, and the
    one function that obtains it is the one place a test substitutes.
    """

    async def _open() -> object:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)


# --- §5: the names, fixed here rather than left to the lane ------------------


def test_the_three_command_names_are_the_ones_the_decision_fixed() -> None:
    """§5's three commands, **by these names and not by names a lane chooses**.

    Asserted literally, because without it §5 is prose an implementation satisfies
    under any name. The vocabulary qualifies with ``destination`` for ADR-0186 §1's
    naming rule coming out the same way a third time: on this surface ``grant``,
    ``amend``, ``revoke``, ``grants`` and ``granted`` already name ``SourceGrant`` and
    ``remember-recipients``, ``recipient-grants`` and ``revoke-recipient-grant``
    already name ``RecipientGrant``.
    """
    names = {command.name for command in cli.app.registered_commands}

    assert {
        "trust-destinations",
        "destination-trust",
        "revoke-destination-trust",
    } <= names


def test_the_standing_listing_takes_no_limit() -> None:
    """§4: "a truncated answer to *what do I trust* is a false answer".

    ``assistant recipient-grants`` takes none for the same reason one store over, and
    a lane adding one here would be answering a different question.
    """
    group = typer.main.get_command(cli.app)
    listing = group.commands["destination-trust"]  # type: ignore[attr-defined]

    assert [param.name for param in listing.params] == []


def test_no_flag_on_any_command_performs_the_other_act() -> None:
    """§5: "**No flag on any command performs the other act**."

    ``--until`` stays ``establish_recipient_grant``'s expiry and gains no sibling here,
    and the trust command takes no expiry at all — ADR-0238 §1 fixes the record at five
    fields with no ``expires_at``, so a ``--until`` would be a ``core/types.py`` change
    against that clause rather than a flag a surface may add (§2, §14).
    """
    group = typer.main.get_command(cli.app)
    commands = dict(group.commands)  # type: ignore[attr-defined]

    assert [param.name for param in commands["trust-destinations"].params] == ["decision_id"]
    assert [param.name for param in commands["revoke-destination-trust"].params] == ["record_id"]
    assert "trust" not in {param.name for param in commands["remember-recipients"].params} | {
        param.name for param in commands["resume"].params
    }


# --- §3: the five facts, stated before the act is collected ------------------


def test_the_five_facts_are_stated_before_the_act_is_collected(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§3's four facts about what the act does, and the fifth that is easy to leave out.

    The fifth is the one an earlier reading would omit and that would be false to leave
    implied: a conversation that has already read from a destination it did not trust is
    **not** repaired by the act, because ADR-0238 §5's recorded half is monotone over a
    conversation.
    """
    _wire(monkeypatch, _TrailedEngine())

    CliRunner().invoke(cli.app, ["trust-destinations", "d-1"])
    rendered = _flat(output.getvalue())

    assert "not[/] the question of whether I may talk" in rendered or "not the question" in rendered
    assert "drawn from things I hold about you" in rendered
    assert "withdraw it at any time" in rendered
    assert "carries no end date" in rendered
    assert "not[/] repaired by this" in rendered or "not repaired by this" in rendered
    assert "what a later conversation may compose" in rendered


def test_the_surface_says_it_cannot_show_what_a_future_call_would_send(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§3: ADR-0233 §8's span-value floor is not met here and this does not claim it is.

    The record widens what may be composed for calls **not yet planned**, so no surface
    can show the user those bytes and none pretends otherwise. What is shown is the
    **class** — records this system holds about the user, composed into a query by a
    model, under a per-conversation call budget — and the statement names no number,
    quotes no budget, estimates no volume and promises no bound.
    """
    _wire(monkeypatch, _TrailedEngine())

    CliRunner().invoke(cli.app, ["trust-destinations", "d-1"])
    rendered = _flat(output.getvalue())

    assert "cannot show you what a future call would send" in rendered
    assert "have not been planned yet" in rendered
    # The **class** and not a quantity: no number, no budget, no volume, no bound.
    assert "records I hold about you" in rendered
    # **The class, and it stops there**: the statement about what is drawn on names no
    # number, quotes no budget, estimates no volume and promises no bound. Asserted over
    # that statement rather than over the whole screen, because §3's numbered facts
    # above it are an enumeration of the facts and not a quantity of anything.
    about_the_future = rendered.split("records I hold about you")[-1].split("Not recorded")[0]
    assert not any(character.isdigit() for character in about_the_future)


# --- §5: the four renderings, each read from the type of the refusal ---------


def test_a_duplicate_is_rendered_as_already_chosen(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§5: on ``DuplicateDestinationTrustError`` it says the destination is already chosen.

    **Read from the type and never from a message or a read-back** (§2), which is why
    the subclass exists at all: the user's recourse on this ground is *no act at all*,
    where every other refusal leaves them something to do.
    """
    _wire(monkeypatch, _RefusingEngine(DuplicateDestinationTrustError("already")))

    result = CliRunner().invoke(cli.app, ["trust-destinations", "d-1"])
    rendered = _flat(output.getvalue())

    assert result.exit_code == 1
    assert "Nothing to do." in rendered
    assert "already ones you have chosen" in rendered
    assert "assistant destination-trust" in rendered


def test_the_base_refusal_names_no_cause_it_was_not_given(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§5: on the base class it says no trust was recorded and names no cause.

    ADR-0238 §13 closes that decision's ``core/errors.py`` surface at one name, so this
    class covers a refusal *and* a write the store could not perform, and ADR-0242 §2
    forbids telling them apart by any other means. The honest statement is the
    disjunction plus the one thing both grounds establish.
    """
    _wire(monkeypatch, _RefusingEngine(InvalidDestinationTrustError("refused")))

    result = CliRunner().invoke(cli.app, ["trust-destinations", "d-1"])
    rendered = _flat(output.getvalue())

    assert result.exit_code == 1
    assert "Not recorded." in rendered
    assert "will not guess which it was" in rendered
    assert "Nothing stands from this either way" in rendered


def test_an_untrustable_decision_names_which_condition_failed(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§1, §5: the message names which of the three conditions failed, and this relays it.

    **No lane branches on the message** (§1). This renderer prints the sentence the
    operation composed rather than re-deriving it, which is what keeps one statement of
    the ordering rule in the tree.
    """
    _wire(
        monkeypatch,
        _RefusingEngine(UntrustableDestinationError("decision 'd-2' records a call planned over")),
    )

    result = CliRunner().invoke(cli.app, ["trust-destinations", "d-2"])
    rendered = _flat(output.getvalue())

    assert result.exit_code == 1
    assert "records a call planned over" in rendered
    assert "Nothing was recorded and nothing was sent." in rendered


def test_a_store_fault_on_the_listing_is_rendered_as_one(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§5's fourth rendering, on the operation where the type is unambiguous.

    ADR-0242 §2 gives ``standing_destination_trust`` exactly one failure — "if the trust
    store could not be read" — so this class means a store fault *there*, and saying so
    states what the type establishes rather than guessing.
    """
    _wire(monkeypatch, _RefusingEngine(InvalidDestinationTrustError("unreadable")))

    result = CliRunner().invoke(cli.app, ["destination-trust"])
    rendered = _flat(output.getvalue())

    assert result.exit_code == 1
    assert "could not be read or written" in rendered
    assert "storage fault and not a refusal" in rendered


# --- §4: the listing and the revocation --------------------------------------


def test_an_empty_listing_says_so_without_answering_another_question(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§4: two vocabularies and never one, held at the surface.

    A page that answered "what do I trust" with recipient grants or source grants is how
    someone comes to believe that revoking one revoked the other.
    """
    _wire(monkeypatch, FakeAssistantEngine())

    result = CliRunner().invoke(cli.app, ["destination-trust"])
    rendered = _flat(output.getvalue())

    assert result.exit_code == 0
    assert "Nothing chosen." in rendered
    assert "not the same question as 'assistant recipient-grants'" in rendered
    assert "'assistant granted'" in rendered


def test_a_live_record_is_listed_with_its_parties_and_no_end_date(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§4: the store's own live set, rendered whole, with §2's asymmetry stated.

    A trust record carries **no expiry** — ADR-0238 §1 fixes it at five fields with
    ``revoked_at`` the only lifecycle member — and the listing says so rather than
    letting a reader carry ``RecipientGrant``'s expectation over.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    async def _standing() -> tuple[DestinationTrustRecord, ...]:
        return (_RECORD,)

    monkeypatch.setattr(engine, "standing_destination_trust", _standing)
    result = CliRunner().invoke(cli.app, ["destination-trust"])
    rendered = _flat(output.getvalue())

    assert result.exit_code == 0
    assert "t-1" in rendered
    assert "a@example.com" in rendered
    assert "carries an end date" in rendered
    assert "revoke-destination-trust" in rendered


def test_revoking_an_unknown_id_is_answered_and_not_reported_as_a_fault(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§4: ``False`` is the honest answer to a caller arriving after the record is gone.

    "The user's recourse succeeded — the trust they asked to withdraw is withdrawn." No
    lane retries, revokes twice, or reports the loss as a fault, and the exit code says
    so.
    """
    _wire(monkeypatch, FakeAssistantEngine())

    result = CliRunner().invoke(cli.app, ["revoke-destination-trust", "t-9"])
    rendered = _flat(output.getvalue())

    assert result.exit_code == 0
    assert "Nothing to withdraw." in rendered
    assert "may already have been withdrawn" in rendered


# --- §5: the next-step line names both acts, as two acts ---------------------


def test_the_grantable_listing_names_both_acts_as_two(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§5: both acts side by side over the same decision id, named as two questions.

    This is what discharges ADR-0238 §1's "knowing it was a second question" at the
    point of discovery, and it is the whole of the coupling between the two acts. It
    performs **no trust read** to do it: the line is a fixed statement of what the two
    commands are, not a rendering of any destination's current state.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    async def _grantable(*, limit: int = 20) -> tuple[object, ...]:
        return (_ELIGIBLE,)

    monkeypatch.setattr(engine, "grantable_decisions", _grantable)
    result = CliRunner().invoke(cli.app, ["remember-recipients"])
    rendered = _flat(output.getvalue())

    assert result.exit_code == 0
    assert "neither completes the other" in rendered
    assert "assistant remember-recipients <decision-id> --until <instant>" in rendered
    assert "assistant trust-destinations <decision-id>" in rendered
    assert "standing_destination_trust" not in [call[0] for call in engine.calls]


# --- §9: the eight statements, over their rendered bytes ---------------------


_STATEMENTS: Final = {
    SearchNotServiced.SEARCH_DISABLED: ("switched off in this installation", "operator setting"),
    SearchNotServiced.NOT_ADMITTED: ("did not admit that lookup", "per conversation"),
    SearchNotServiced.SPEND_EXHAUSTED: ("spending ceiling refused", "operator setting"),
    SearchNotServiced.DECLINED: ("declined when it was ruled on",),
    SearchNotServiced.TRUST_MISSING: (
        "assistant trust-destinations <decision-id>",
        "assistant decisions",
        "a later conversation may compose",
    ),
    SearchNotServiced.AUTHORISATION_AWAITED: (
        "put to you as a question",
        "assistant remember-recipients",
    ),
    SearchNotServiced.INTERRUPTED: ("begun and stopped",),
    SearchNotServiced.UNAVAILABLE: ("nothing this turn could use",),
}


@pytest.mark.parametrize("member", list(SearchNotServiced))
def test_every_member_renders_a_statement(
    member: SearchNotServiced, monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§9: "A surface that renders **no** statement for a member is a surface that has
    not implemented this section, not a permitted degradation."

    Parametrised over the vocabulary itself, so a ninth member added without its
    statement fails here rather than rendering nothing in a user's terminal — which is
    what §13 means by "a member added without its two texts is a member with no
    rendering".
    """
    cli._render_search_not_serviced(member)
    rendered = _flat(output.getvalue())

    assert rendered.strip(), f"{member} renders nothing"
    for fragment in _STATEMENTS[member]:
        assert fragment in rendered


def test_no_statement_is_rendered_for_a_turn_that_serviced_every_search(
    output: StringIO,
) -> None:
    """§6: on every other turn the surface says nothing about a lookup at all."""
    cli._render_search_not_serviced(None)

    assert output.getvalue() == ""


@pytest.mark.parametrize("member", list(SearchNotServiced))
def test_no_statement_carries_a_destination_a_count_or_a_figure(
    member: SearchNotServiced, monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§9's bar, asserted **over the rendered bytes** and not over an intention.

    None of the eight carries a destination, a host, an origin, a provider name, a
    connection reference, an account identity, a query or any fragment of one, a record,
    a count, a monetary figure, a duration, a budget, a ``Settings`` field name or a
    ``SearchDisposition`` value. §7's bar on the prompt fragments and this bar are one
    rule stated at the two render sites it has to hold at.
    """
    cli._render_search_not_serviced(member)
    rendered = _flat(output.getvalue())

    assert not any(character.isdigit() for character in rendered)
    for forbidden in ("http", "@", "$", "£", "search_calls_per_conversation"):
        assert forbidden not in rendered
    # **No ``SearchDisposition`` value**, which is the vocabulary §8 keeps for the
    # operator's audit and §9 keeps out of the user's screen.
    for stage in SearchDisposition:
        assert stage.value not in rendered


def test_the_two_confirm_statements_name_different_commands(output: StringIO) -> None:
    """§8's finding, held at the surface: one disposition, two acts, two commands.

    ``RULING_CONFIRM`` is recorded both where no grant covers the recipients at all and
    where a grant stands but the closed loop is not closed. "An explanation derived from
    the disposition alone would send half of milestone 31's users to the wrong command",
    and this is what makes that concrete.
    """
    cli._render_search_not_serviced(SearchNotServiced.AUTHORISATION_AWAITED)
    awaited = _flat(output.getvalue())
    output.truncate(0)
    output.seek(0)
    cli._render_search_not_serviced(SearchNotServiced.TRUST_MISSING)
    missing = _flat(output.getvalue())

    assert "assistant remember-recipients" in awaited
    assert "assistant trust-destinations" not in awaited
    assert "assistant trust-destinations" in missing
    assert "assistant remember-recipients" not in missing


def test_the_awaited_statement_does_not_say_no_authorisation_covers_the_recipients(
    output: StringIO,
) -> None:
    """§9, §15's arm 2(a2): the sentence that is false on a reachable configuration.

    ADR-0236 §4 fixes the shipped default in terms — with ``web_search_cost_per_call``
    unset "the ``RecipientGrants`` seam is consulted **zero** times whatever grants
    exist" — so a ``CONFIRM`` establishes nothing about what grants stand, and a
    statement asserting one would be false of a deployment holding a standing grant.
    """
    cli._render_search_not_serviced(SearchNotServiced.AUTHORISATION_AWAITED)
    rendered = _flat(output.getvalue())

    for forbidden in ("no standing", "not authorised", "no authorisation", "missing"):
        assert forbidden not in rendered.lower()


def test_the_trust_statement_promises_no_eligible_decision(output: StringIO) -> None:
    """§9: the statement names what makes a decision eligible and asserts nothing about
    what is there.

    "There is a reachable deployment on which none exists" — one whose *first* search is
    planned over external content — so a statement promising an available id would be
    false on it. And ADR-0181 §6's second clause binds: ``False`` is rendered as no
    assurance, so it does not say the request was composed from the user's own words
    alone and names no source and no kind of source.
    """
    cli._render_search_not_serviced(SearchNotServiced.TRUST_MISSING)
    rendered = _flat(output.getvalue())

    assert "no record selected into it was marked as resting on recorded external content" in (
        rendered
    )
    for forbidden in ("your own words alone", "there will be", "you will find", "guarantee"):
        assert forbidden not in rendered.lower()


def test_the_unavailable_statement_names_no_cause_and_no_act(output: StringIO) -> None:
    """§8, §9: the deliberate residue names no cause and no act.

    It is one member rather than thirteen "because none of the situations behind it
    gives the user anything to do — including the closed-loop case, where an act exists
    but is not one that would help". **Naming an act that cannot help is worse than
    naming none.**
    """
    cli._render_search_not_serviced(SearchNotServiced.UNAVAILABLE)
    rendered = _flat(output.getvalue())

    assert "assistant" not in rendered
    assert "no request" not in rendered.lower()


def test_the_statement_is_rendered_beside_the_reply_and_never_in_place_of_it(
    output: StringIO,
) -> None:
    """§9: "beside the reply and never in place of it".

    Driven through the production ``_render_turn``, so what is asserted is the order a
    user actually reads rather than a call this test made itself.
    """
    cli._render_turn(
        TurnOutcome(
            turn=None,
            capture_degraded=True,
            search_not_serviced=SearchNotServiced.TRUST_MISSING,
        )
    )
    rendered = _flat(output.getvalue())

    assert "this turn was not recorded" in rendered
    assert rendered.index("this turn was not recorded") < rendered.index(
        "assistant trust-destinations"
    )
