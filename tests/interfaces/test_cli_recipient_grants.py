"""The terminal surface for standing recipient grants (ADR-0235 §9, ADR-0313 §5).

The establishing act, ``assistant remember-recipients``, left the command line with
``establish_recipient_grant`` (ADR-0313 §5:1). What stays is the listing, the log and
the revocation, with their signatures and results (§5:2). ADR-0235 §9 fixes their
names **here rather than leaving them to the lane**, for the reason ADR-0186 §9 fixed
``assistant decisions`` in terms: "a normative decision an operator cannot derive a
working command from is one no test can pin". So the names are pinned literally.
"""

from __future__ import annotations

import ast
from io import StringIO
from pathlib import Path
from typing import Any, Final

import pytest
import typer.main
from rich.console import Console
from test_cli_decisions import _flat

from ai_assistant.interfaces import cli
from ai_assistant.testing.recipient_grants import recipient_grant

#: A grant a listing renders, at the fakes' own instants so nothing here invents a
#: second timeline.
_GRANT: Final = recipient_grant(grant_id="g-1")


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


# --- §9: the names, fixed here rather than left to the lane ------------------


def test_the_three_command_names_are_the_ones_the_decision_fixed() -> None:
    """§9's commands that stay, **by these names and not by names a lane chooses**.

    Asserted literally, because without it §9 is prose an implementation satisfies
    under any name — the gap round 8 of ADR-0235's review found in an earlier draft
    of it. The vocabulary qualifies with ``recipient`` for §7's naming reason
    exactly: on this surface ``grant``, ``amend``, ``revoke``, ``grants`` and
    ``granted`` already have a referent and it is ``SourceGrant``.
    """
    group = cli.app  # the Typer application the entry point runs
    names = {command.name for command in group.registered_commands}

    assert {
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
