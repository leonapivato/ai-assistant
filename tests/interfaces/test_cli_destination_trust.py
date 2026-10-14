"""The terminal surface for the trust act (ADR-0242).

Three commands, four refusal renderings and one next-step line. ADR-0242 §5 fixes the
command names **here rather than leaving them to the lane**, for the reason ADR-0186 §9
fixed ``assistant decisions`` in terms — "a normative decision an operator cannot derive
a working command from is one no test can pin" — so the names are pinned literally.

**Every outcome case is asserted over the rendered output**, because ADR-0242 §3's floor
is discharged in what the user reads and nowhere else.
"""

from __future__ import annotations

import re
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
)
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine

_AT: Final = datetime(2026, 5, 1, 9, tzinfo=UTC)

#: One recorded ``CONFIRM`` whose binding carries a clean footing — ADR-0242 §1's three
#: conditions, all satisfied, which is what makes the act available on it.
_ELIGIBLE: Final = _decision(
    "d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False)
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
    assert "trust" not in {param.name for param in commands["remember-recipients"].params}


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


def test_a_successful_revocation_claims_only_what_the_boolean_establishes(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§4: "No surface derives liveness from anything but ``standing_destination_trust()``."

    ADR-0238 §1 refuses a second record over a live record's **exact** destination set
    and admits an *overlapping* one, and ``trust_of``'s rule is membership of *some one*
    live record. So with live records over ``{A}`` and ``{A, B}``, revoking the first
    answers ``True`` while ``trust_of({A})`` still answers ``USER_CHOSEN`` — and a
    sentence promising that composition for those parties is back to the user's own words
    would be false in exactly that case.

    What the boolean establishes is that **one record** was withdrawn, and the rendering
    says that and points at the one read that answers what stands.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    async def _revoked(record_id: object) -> bool:
        return True

    monkeypatch.setattr(engine, "revoke_destination_trust", _revoked)
    result = CliRunner().invoke(cli.app, ["revoke-destination-trust", "t-1"])
    rendered = _flat(output.getvalue())

    assert result.exit_code == 0
    assert "Withdrawn." in rendered
    assert "another record you hold may name them too" in rendered
    assert "'assistant destination-trust' is the only honest answer" in rendered
    assert "It does not follow that those parties are no longer chosen" in rendered
    for forbidden in ("your own words alone", "are no longer chosen."):
        assert forbidden not in rendered


def test_the_grantable_listing_states_the_five_facts_before_any_id_is_typed(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§3: "**before it collects the act**", which on a terminal is before the typing.

    §1 puts the offer at the listing — "The user names a decision from a listing that
    already renders the canonical destination set ``core`` derived" — so this is where a
    user meets the five facts, beside the next-step line that names both acts. A
    statement only the performing command printed would have been read after the decision
    to perform it rather than before.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    async def _grantable(*, limit: int = 20) -> tuple[object, ...]:
        return (_ELIGIBLE,)

    monkeypatch.setattr(engine, "grantable_decisions", _grantable)
    CliRunner().invoke(cli.app, ["remember-recipients"])
    rendered = _flat(output.getvalue())

    assert "not the question of whether I may talk" in rendered
    assert "drawn from things I hold about you" in rendered
    assert "carries no end date" in rendered
    assert "not repaired by this" in rendered
    assert rendered.index("assistant trust-destinations <decision-id>") < rendered.index(
        "carries no end date"
    ), "the command is offered and the facts follow it on the same screen, before any typing"


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


# --- §9: the decisions page offers the act ------------------------------------


def test_the_decisions_page_offers_the_act_and_states_the_five_facts(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§3 on the route §9 prescribes, which is the one a refused follow-up sends users to.

    ``TRUST_MISSING``'s statement names ``assistant decisions`` **and not** ``assistant
    remember-recipients``, because the decision recording that refusal carries
    ``planned_with_external_content`` and the decision the user granted from has been
    resolved — so the other listing "can therefore be empty at exactly the moment its
    guidance is followed" (§9). A user arriving here and typing the command would
    otherwise read the five facts only after performing the act, which is what §3's
    "before it collects the act" forbids.

    **The grant act is not offered here**, and that is a decision rather than an
    omission: ADR-0235 §3's availability set is what ``remember-recipients`` renders and
    a row here may fail it for reasons this page does not compute, so naming that command
    beside a row it cannot judge would be this surface deriving an availability it was
    not given.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    async def _recent(*, limit: int = 20) -> tuple[object, ...]:
        return (_ELIGIBLE,)

    monkeypatch.setattr(engine, "recent_decisions", _recent)
    result = CliRunner().invoke(cli.app, ["decisions"])
    rendered = _flat(output.getvalue())

    assert result.exit_code == 0
    assert "assistant trust-destinations <decision-id>" in rendered
    assert "neither completes the other" in rendered
    assert "not the question of whether I may talk" in rendered
    assert "drawn from things I hold about you" in rendered
    assert "carries no end date" in rendered
    assert "not repaired by this" in rendered
    assert "cannot show you what a future call would send" in rendered


def test_the_five_facts_carry_no_word_the_decisions_page_bars(output: StringIO) -> None:
    """ADR-0186 §8's two bars, held over the block that now renders on that page.

    §8's third clause bars any word for an **event** beside a ruling — the page records
    what was decided and never what was carried out — and its fifth bars
    :attr:`~ai_assistant.core.types.ToolDefinition.reads`, ``writes`` and ``discloses``,
    which are ceilings on what a tool *may* reach rather than per-call measurements. A
    block written for one page and rendered on another is exactly where such a word
    creeps back, so it is asserted here rather than left to the page's own arms.
    """
    cli._render_destination_trust_preamble()
    rendered = _flat(output.getvalue()).lower()

    for event in ("sent", "delivered", "transmitted", "emailed", "went"):
        assert not re.search(rf"\b{event}\b", rendered), event
    assert not re.search(r"\bread\b", rendered)
    for reach in ("reads", "writes", "discloses"):
        assert reach not in rendered
