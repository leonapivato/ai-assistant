"""The terminal surface for the establishing act (ADR-0235 §9).

Four commands, two flags, and the outcomes a user reads. §9 fixes the names
**here rather than leaving them to the lane**, for the reason ADR-0186 §9 fixed
``assistant decisions`` in terms: "a normative decision an operator cannot derive a
working command from is one no test can pin, and four commands named by four
readings are four incompatible surfaces". So the names are pinned literally.

**Every outcome case is asserted over the rendered output**, because ADR-0193 §1's
obligation — that a surface offering the act names a ceiling refusal to the user —
is discharged in what the user reads and nowhere else.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any, Final

import pytest
import typer.main
from rich.console import Console
from test_cli_decisions import _binding, _decision, _flat
from typer.testing import CliRunner

from ai_assistant.core.errors import (
    DuplicateRecipientGrantError,
    InvalidRecipientGrantError,
    PermissionDeniedError,
    RecipientGrantCeilingError,
    RecipientGrantError,
    UngrantableActError,
)
from ai_assistant.core.types import (
    PermissionOutcome,
    RecipientGrantNotEstablished,
    RecipientGrantOutcome,
)
from ai_assistant.interfaces import cli
from ai_assistant.testing.recipient_grants import recipient_grant

#: The instant a case types, and the shape §9 fixes: ISO 8601 with an offset.
_UNTIL: Final = "2026-10-01T09:00:00Z"

#: A grant a listing renders, at the fakes' own instants so nothing here invents a
#: second timeline.
_GRANT: Final = recipient_grant(grant_id="g-1")

#: One recorded ``CONFIRM`` about an egress call, as the listing renders it. Built
#: through ``test_cli_decisions``' own builder so the two modules render one row
#: rather than two that agree by accident.
_DECISION: Final = _decision(
    "d-1", outcome=PermissionOutcome.CONFIRM, binding=_binding(planned=False)
)


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=100))
    return buffer


def _resolved_commands() -> dict[str, Any]:
    """The Typer application's commands, resolved into click's own objects.

    ``registered_commands`` carries the *decorator's* record — the callback and the
    name it was registered under — and not the parameters, which Typer builds from
    the callback's signature when it constructs the click command. Names and flags
    are what ADR-0235 §9 fixes, so the cases below read them from the object a user's
    shell actually meets.
    """
    group = typer.main.get_command(cli.app)
    commands: dict[str, Any] = dict(group.commands)  # type: ignore[attr-defined]
    return commands


def _outcome(member: RecipientGrantNotEstablished) -> RecipientGrantOutcome:
    """The carrier a ``resume`` returns for one refusing member."""
    return RecipientGrantOutcome(not_established=member)


# --- §9: the names, fixed here rather than left to the lane ------------------


def test_the_four_command_names_are_the_ones_the_decision_fixed() -> None:
    """§9's four commands, **by these names and not by names a lane chooses**.

    Asserted literally, because without it §9 is prose an implementation satisfies
    under any name — the gap round 8 of ADR-0235's review found in an earlier draft
    of it. The vocabulary qualifies with ``recipient`` for §7's naming reason
    exactly: on this surface ``grant``, ``amend``, ``revoke``, ``grants`` and
    ``granted`` already have a referent and it is ``SourceGrant``.
    """
    group = cli.app  # the Typer application the entry point runs
    names = {command.name for command in group.registered_commands}

    assert {
        "remember-recipients",
        "recipient-grants",
        "recipient-grant-log",
        "revoke-recipient-grant",
    } <= names


def test_the_source_grant_commands_gain_no_recipient_argument() -> None:
    """ADR-0235 §7: two vocabularies and never one, held at the command surface.

    ``assistant grants``, ``assistant granted``, ``assistant grant``, ``assistant
    amend`` and ``assistant revoke`` stay source-grant commands and gain nothing.
    A parameter named for a recipient on any of them is the collapse §7 forbids,
    and it is the one a lane adding "just a flag" would reach for.
    """
    resolved = _resolved_commands()
    named = {
        name: {str(parameter.name) for parameter in resolved[name].params}
        for name in ("grants", "granted", "grant", "amend", "revoke")
    }

    for command, parameters in named.items():
        assert not any("recipient" in parameter for parameter in parameters), command


def test_the_two_flag_names_are_the_ones_the_decision_fixed() -> None:
    """§9's two flags: ``--until`` on the act, the qualified form on ``resume``.

    Each flag carries the name of the argument it supplies, and on ``resume`` the
    qualified form is also what keeps it from being read as a retention control over
    what the assistant remembers — which is what "remember" means everywhere else on
    this surface (``learn``, ``observe``, ``forget``).
    """
    resolved = _resolved_commands()
    flags = {
        name: {option for parameter in resolved[name].params for option in parameter.opts}
        for name in ("remember-recipients", "resume")
    }

    assert "--until" in flags["remember-recipients"]
    assert "--remember-recipients-until" in flags["resume"]
    assert "--remember-recipients-until" not in flags["remember-recipients"]


# --- §9: an instant carrying no offset is a usage error ----------------------


@pytest.mark.parametrize(
    "typed", ["2026-10-01T09:00:00", "2026-10-01", "tomorrow", "2026-10-01 09:00:00"]
)
def test_an_instant_carrying_no_offset_is_refused_before_any_client_is_built(
    typed: str,
) -> None:
    """§9: refused **during parameter parsing**, naming that an offset is required.

    ADR-0023 §3 names "a datetime a user typed meaning their own wall clock" as
    exactly the value for which attribution *fabricates* a fact rather than restoring
    one, and puts attribution in the adapter that knows the offset — which this one
    does not. Refusing rather than accepting-and-changing is ``_quiet_window``'s rule
    one type over.

    The exit code is 2, a usage error, and no engine is built: a ``ValueError`` out
    of the parse would escape the command's ``except (AssistantError,
    TransportError)`` boundary as an uncaught traceback, which ADR-0042 §7 forbids.
    """
    result = CliRunner().invoke(cli.app, ["remember-recipients", "d-1", "--until", typed])

    assert result.exit_code == 2
    assert "offset" in _flat(result.output) or "ISO 8601" in _flat(result.output)


def test_an_instant_with_an_offset_is_admitted() -> None:
    """The other half: both spellings ADR-0235 §9 names are admitted."""
    assert cli._offset_instant("2026-10-01T09:00:00Z") == "2026-10-01T09:00:00Z"
    assert cli._offset_instant("2026-10-01T11:00:00+02:00") == "2026-10-01T11:00:00+02:00"
    assert cli._parsed_instant("2026-10-01T09:00:00Z") == datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def test_naming_a_decision_without_an_until_is_a_usage_error() -> None:
    """The instant is the user's and this surface will not choose one (ADR-0235 §1).

    "No surface, adapter, gateway or engine defaults it, derives it, extends it,
    rounds it, offers it pre-filled, or supplies one where the user supplied none."
    The command that could most easily break that is this one — a default of "a
    week" would read as helpful — so the absence is a refusal rather than a silence.
    """
    result = CliRunner().invoke(cli.app, ["remember-recipients", "d-1"])

    assert result.exit_code == 2
    assert "--until" in _flat(result.output)


# --- §9: the five renderings, on ``assistant resume`` ------------------------


def test_a_ceiling_refusal_names_the_ceiling_and_the_revocation_command(
    output: StringIO,
) -> None:
    """ADR-0193 §1 discharged in the words the user reads (ADR-0235 §9).

    §1 obliges a surface offering the act to refuse it "with a reason visible to the
    user, naming that the ceiling was reached", with the recourse beside it — and
    ADR-0235 §9 fixes the recourse as ``assistant revoke-recipient-grant``. A refusal
    the user is shown, named and given a recourse for is not the dropped act §1
    forbids.

    It is **not** presented as a fault of the call that was confirmed, which had
    already been sent by the time the store refused.
    """
    cli._render_recipient_grant_outcome(_outcome(RecipientGrantNotEstablished.CEILING_REACHED))

    rendered = _flat(output.getvalue())
    assert "assistant revoke-recipient-grant" in rendered
    assert "as many standing recipient authorisations" in rendered
    assert "evicted" in rendered


def test_an_already_standing_refusal_names_the_standing_listing(output: StringIO) -> None:
    """The user needs **no** act at all: what they asked for is already true (§4)."""
    cli._render_recipient_grant_outcome(_outcome(RecipientGrantNotEstablished.ALREADY_STANDING))

    rendered = _flat(output.getvalue())
    assert "already authorised" in rendered
    assert "assistant recipient-grants" in rendered


def test_a_bare_refusal_names_no_cause(output: StringIO) -> None:
    """§9: on ``REFUSED`` it "says no standing authorisation was created and names no
    cause it was not given" — the bar ADR-0235 §11 states as "never guessed at"."""
    cli._render_recipient_grant_outcome(_outcome(RecipientGrantNotEstablished.REFUSED))

    rendered = _flat(output.getvalue())
    assert "No standing authorisation was created" in rendered
    assert "ceiling" not in rendered
    assert "already" not in rendered


def test_a_store_fault_says_the_confirmed_call_was_unaffected(output: StringIO) -> None:
    """The arm that fails against a terminal rendering a storage fault as a refusal.

    ADR-0235 §4: a surface reporting a disk fault as a refusal would be telling the
    user their request was declined when it was not — so the rendering says the store
    could not be written **and** that the call itself was unaffected.
    """
    cli._render_recipient_grant_outcome(_outcome(RecipientGrantNotEstablished.STORE_UNAVAILABLE))

    rendered = _flat(output.getvalue())
    assert "could not be written" in rendered
    assert "not a refusal of what you asked for" in rendered


def test_a_declined_ruling_says_recorded_and_settled(output: StringIO) -> None:
    """§9's fifth sentence, and it is the same one ``remember-recipients`` gives.

    "The call was declined when it was ruled on, the decision is recorded and
    settled, and nothing was made standing" — because it is the same outcome reaching
    the user by the other road.
    """
    cli._render_recipient_grant_outcome(_outcome(RecipientGrantNotEstablished.DECLINED))

    rendered = _flat(output.getvalue())
    assert "declined when it was ruled on" in rendered
    assert "recorded and settled" in rendered
    assert "nothing was made standing" in rendered


def test_a_successful_act_says_what_it_covers_and_until_when(output: StringIO) -> None:
    """§5's floor on the establishing arm: the account, the recipients, the instant.

    And the statement §5 requires beside them — that calls this grant covers will not
    be put to the user, so their payload description is not shown again.
    """
    cli._render_recipient_grant_outcome(RecipientGrantOutcome(established=_GRANT))

    rendered = _flat(output.getvalue())
    assert _GRANT.id in rendered
    assert _GRANT.account.identity in rendered
    assert "not be put to you again" in rendered
    assert "never" in rendered


def test_a_call_that_collected_no_act_says_nothing_about_standing_grants(
    output: StringIO,
) -> None:
    """ADR-0235 §6: where the carrier is absent the surface says nothing at all.

    The asymmetry with every case above is the decision rather than an omission: a
    user told nothing about a request they *made* concludes it was granted, and a
    user told something about a request they never made is being answered a question
    they did not ask.
    """
    cli._render_recipient_grant_outcome(None)

    assert output.getvalue() == ""


# --- §9: the same five, on ``assistant remember-recipients`` -----------------


class _Raising:
    """An engine whose ``establish_recipient_grant`` raises whatever it was handed.

    The five renderings are read from the **type** of the refusal and from nothing
    else (ADR-0235 §11), so what a case varies is the class — not a message, not a
    count, and not a listing read afterwards.
    """

    def __init__(self, error: Exception) -> None:
        """Hold the refusal every act raises."""
        self.error = error

    async def establish_recipient_grant(self, decision_id: str, *, expires_at: object) -> object:
        """Raise it."""
        raise self.error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RecipientGrantCeilingError("at the ceiling"), "assistant revoke-recipient-grant"),
        (DuplicateRecipientGrantError("already standing"), "already authorised"),
        (InvalidRecipientGrantError("refused"), "No standing authorisation was created"),
        (RecipientGrantError("unwritable"), "could not be written"),
        (PermissionDeniedError("declined"), "declined when it was ruled on"),
    ],
)
async def test_the_act_states_each_outcome_from_the_refusals_own_type(
    error: Exception, expected: str, output: StringIO
) -> None:
    """ADR-0235 §12's matching terminal arm, and the gap round 12 of its review found.

    ADR-0193 §1's ceiling clause binds **every** surface offering the act, so the
    five sentences ``assistant resume`` gives from its carrier are the five this
    command gives from the refusal's own type. A lane that rendered the carrier on
    one population and let the refusal propagate on the other would ship a surface
    ADR-0193 §1 does not permit.

    **None of the five escapes as a traceback**, which is what the exit code asserts:
    a raise out of here would be the uncontrolled exit ADR-0042 §7 forbids.
    """
    code = await cli._drive_establish(
        _Raising(error),  # type: ignore[arg-type]  # only one member is reached
        "d-1",
        expires_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
    )

    assert code == cli._EXIT_ERROR
    assert expected in _flat(output.getvalue())


async def test_a_refusal_before_the_answer_says_the_call_is_not_made_by_this_act(
    output: StringIO,
) -> None:
    """ADR-0235 §12's ``UngrantableActError`` arm on population (b).

    The population-(b) rendering **does not** say the call is still answerable: there
    is no park to answer, and a surface offering a retry it knows will not be there
    would be inviting the one thing §6 forbids it to promise. The population-(a)
    rendering below is the other half of the same clause.
    """
    code = await cli._drive_establish(
        _Raising(UngrantableActError("that confirmation was already answered")),  # type: ignore[arg-type]
        "d-1",
        expires_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
    )

    rendered = _flat(output.getvalue())
    assert code == cli._EXIT_ERROR
    assert "already answered" in rendered
    assert "still waiting for an answer" not in rendered


def test_the_held_populations_refusal_says_the_call_is_still_answerable(
    output: StringIO,
) -> None:
    """The other half: on ``resume`` the step stays parked, so the surface says so."""
    cli._render_ungrantable(
        UngrantableActError("that expiry is not after the answer"), still_answerable=True
    )

    rendered = _flat(output.getvalue())
    assert "still waiting for an answer" in rendered
    assert "--remember-recipients-until" in rendered


# --- §5, §8: the listing that tells the user a search was refused ------------


def test_the_listing_states_the_three_facts_before_it_offers_anything(
    output: StringIO,
) -> None:
    """ADR-0235 §5's three facts about the call the user is deciding on.

    That the call was refused and was not made; that answering now does not make it;
    and that what an answer establishes is a standing authorisation for the
    **recipients** of calls like it, never for their payloads. Stated before any act
    is collected, which is what §5 means by a rendering *floor*.
    """
    cli._render_grantable_decisions((_DECISION,), limit=50)

    rendered = _flat(output.getvalue())
    assert "refused and was not made" in rendered
    assert "does not make it" in rendered
    assert "recipients" in rendered
    assert "assistant remember-recipients" in rendered


def test_an_empty_listing_states_no_owed_work(output: StringIO) -> None:
    """ADR-0235 §3, §8: this is a place to look and never a queue.

    "It does not state that the turn would have answered differently, that a reply
    was incomplete, that a search would have succeeded, or that anything is owed."
    An empty listing is the case where an implementation would most easily reach for
    inbox language, so it is the one pinned.
    """
    cli._render_grantable_decisions((), limit=50)

    rendered = _flat(output.getvalue())
    assert "Nothing to answer" in rendered
    for owed in ("pending", "waiting for you", "outstanding", "unread"):
        assert owed not in rendered


# --- §7: the two listings and the revocation --------------------------------


def test_the_standing_listing_says_it_is_not_the_source_grant_question(
    output: StringIO,
) -> None:
    """ADR-0235 §7: two vocabularies, kept visibly apart in what the user reads."""
    cli._render_standing_recipient_grants((_GRANT,))

    rendered = _flat(output.getvalue())
    assert _GRANT.id in rendered
    assert "assistant granted" in rendered
    assert "assistant revoke-recipient-grant" in rendered


def test_the_log_says_liveness_may_not_be_read_off_it(output: StringIO) -> None:
    """ADR-0235 §7: a record here says an act happened, never that it still stands."""
    cli._render_recipient_grant_log((_GRANT,), limit=50)

    rendered = _flat(output.getvalue())
    assert "never that it still stands" in rendered
    assert "assistant recipient-grants" in rendered


def test_an_empty_standing_listing_says_every_call_is_put_to_you(output: StringIO) -> None:
    """The honest empty answer, and it is the state the whole surface starts in."""
    cli._render_standing_recipient_grants(())

    rendered = _flat(output.getvalue())
    assert "Nothing standing" in rendered
    assert "every outbound call is put to you" in rendered


# --- §4: no interfaces module holds a recipient-grant store ------------------


def test_no_interfaces_module_imports_or_holds_a_recipient_grant_seam() -> None:
    """ADR-0235 §12's boundary arm, which is "otherwise a rule a reviewer has to notice".

    §4 rules that no ``interfaces`` adapter holds a ``RecipientGrantStore``, a
    ``RecipientGrants`` or a ``RecipientGrantResolution``. A surface is given
    **records** by the five operations and reads no store — which is golden rule 3
    and ADR-0193 §11's second clause read one operation over: a renderer given the
    store face would hold ``record`` and ``clear``, and a remote client could not
    perform the read at all.

    **Asserted over the import statements rather than over the whole source**,
    because the prose that *states* the bar names the three classes and would fail a
    substring scan. What the bar is actually about is a module that can reach one,
    and reaching one means importing it.

    ``lint-imports`` does not catch this: `interfaces` may import `core`, which is
    where the three Protocols live, so the architecture contracts are satisfied by a
    module that named all three.
    """
    barred = {"RecipientGrantStore", "RecipientGrants", "RecipientGrantResolution"}
    root = Path(cli.__file__).parent
    holders: dict[str, set[str]] = {}
    for module in sorted(root.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        found = imported & barred
        if found:
            holders[module.name] = found

    assert holders == {}
