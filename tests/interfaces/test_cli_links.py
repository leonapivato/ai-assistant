"""The linked-accounts commands: the owner's links at the terminal (ADR-0373 §2 to §4).

Driven through the CLI over the canonical fake engine holding an identity store with
the owner's two configured accounts linked, so what is asserted is what the command
line renders of answers the hub would give (``link_inspection``), and that each command
sends what the owner typed and nothing else (§4:1).
"""

from __future__ import annotations

import asyncio
from io import StringIO
from typing import TYPE_CHECKING, Final

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import IdentityStoreError
from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    OWNER_PERSON_ID,
    Account,
    LinkedAccount,
    StandingLowering,
    Sureness,
)
from ai_assistant.interfaces import cli, link_inspection
from ai_assistant.testing import FakeAssistantEngine, FakeIdentityStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine

_HUB_CHAT: Final = Account(kind="conversation", identifier=HUB_DEVICE_ID)
_LINE: Final = Account(kind="telegram", identifier="424242")


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Capture the CLI's console, wide enough that no line is wrapped."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=400))
    return buffer


def _wire(monkeypatch: pytest.MonkeyPatch, engine: AssistantEngine) -> None:
    async def opened() -> AssistantEngine:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", opened)


def _engine() -> tuple[FakeAssistantEngine, FakeIdentityStore]:
    engine = FakeAssistantEngine()
    identities = FakeIdentityStore(configured=(_HUB_CHAT, _LINE))
    engine.identities = identities
    return engine, identities


def _invoke(*args: str) -> int:
    result = CliRunner().invoke(cli.app, ["links", *args])
    return result.exit_code


def test_the_listing_shows_each_account_its_level_and_its_kinds_most(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, _ = _engine()
    _wire(monkeypatch, engine)

    assert _invoke("list") == 0

    assert output.getvalue().splitlines() == [
        'Link "link:1": "conversation" account "hub"',
        "  Level: normal (its kind gives at most normal)",
        'Link "link:2": "telegram" account "424242"',
        "  Level: normal (its kind gives at most normal)",
        link_inspection.HOW_TO_ACT,
    ]
    assert engine.calls == [("linked_accounts", {})]


def test_an_empty_listing_says_so(monkeypatch: pytest.MonkeyPatch, output: StringIO) -> None:
    _wire(monkeypatch, FakeAssistantEngine())

    assert _invoke("list") == 0

    assert output.getvalue().strip() == link_inspection.NONE_LINKED


def test_lowering_the_line_to_none_shows_the_lowering_and_the_level(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """#3642's live step at the terminal: lower the Telegram link, by the owner's act."""
    engine, identities = _engine()
    _wire(monkeypatch, engine)

    assert _invoke("lower", "link:2", "--level", "none") == 0

    assert output.getvalue().splitlines() == [
        "Lowered. The lowering stands until you withdraw it.",
        'Link "link:2": "telegram" account "424242"',
        "  Level: none (its kind gives at most normal)",
        '  Lowering "lowering:1": to none, made by you',
    ]
    assert engine.calls == [("lower_link", {"link_id": "link:2", "level": Sureness.NONE})]
    held = _lowerings_on(identities, _LINE)
    assert [(one.by, one.level) for one in held] == [(OWNER_PERSON_ID, Sureness.NONE)]


def _lowerings_on(identities: FakeIdentityStore, account: Account) -> list[StandingLowering]:
    """The standing lowerings on ``account``'s link, read synchronously from the fake."""
    held = asyncio.run(identities.find_link(account))
    assert held is not None
    return [StandingLowering(id=one.id, level=one.level, by=one.by) for one in held.lowerings]


def test_a_repeated_lowering_is_said_unchanged_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, _ = _engine()
    _wire(monkeypatch, engine)
    assert _invoke("lower", "link:2", "--level", "weak") == 0
    output.truncate(0)
    output.seek(0)

    assert _invoke("lower", "link:2", "--level", "weak") == 0

    assert output.getvalue().splitlines()[0] == (
        "Unchanged: you had already lowered this link to that level."
    )


@pytest.mark.parametrize(
    ("link_id", "level", "said"),
    [
        (
            "link:9",
            "none",
            'Refused: none of your linked accounts has the link id "link:9". Nothing was changed.',
        ),
        (
            "link:2",
            "strong",
            "Refused: that level is not below the most this account's kind gives, so it "
            "would lower nothing. Nothing was changed.",
        ),
    ],
)
def test_a_refused_lowering_says_why_and_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, output: StringIO, link_id: str, level: str, said: str
) -> None:
    engine, _ = _engine()
    _wire(monkeypatch, engine)

    assert _invoke("lower", link_id, "--level", level) == 1

    assert output.getvalue().strip() == said


@pytest.mark.parametrize("args", [["lower", "link:2"], ["lower", "link:2", "--level", "low"]])
def test_a_level_is_required_and_one_of_the_four(
    monkeypatch: pytest.MonkeyPatch, output: StringIO, args: list[str]
) -> None:
    """§2:3: ``level`` has no default; a usage error, and nothing is sent."""
    engine, _ = _engine()
    _wire(monkeypatch, engine)

    assert _invoke(*args) == 2
    assert engine.calls == []


def test_a_blank_id_is_a_usage_error(monkeypatch: pytest.MonkeyPatch, output: StringIO) -> None:
    engine, _ = _engine()
    _wire(monkeypatch, engine)

    assert _invoke("withdraw", "  ") == 2
    assert _invoke("lower", "", "--level", "none") == 2
    assert engine.calls == []


def test_withdrawing_restores_the_level(monkeypatch: pytest.MonkeyPatch, output: StringIO) -> None:
    """#3642: withdraw the lowering and see the level restored."""
    engine, _ = _engine()
    _wire(monkeypatch, engine)
    assert _invoke("lower", "link:2", "--level", "none") == 0
    output.truncate(0)
    output.seek(0)

    assert _invoke("withdraw", "lowering:1") == 0

    assert output.getvalue().splitlines() == [
        "Withdrawn. The lowering no longer stands.",
        'Link "link:2": "telegram" account "424242"',
        "  Level: normal (its kind gives at most normal)",
    ]
    assert engine.calls[-1] == ("withdraw_lowering", {"lowering_id": "lowering:1"})


def test_withdrawing_what_does_not_stand_is_no_error(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§2:6: ``not_standing`` is not an error."""
    engine, _ = _engine()
    _wire(monkeypatch, engine)

    assert _invoke("withdraw", "lowering:7") == 0

    assert output.getvalue().strip() == (
        'No lowering with the id "lowering:7" stands on your linked accounts, so nothing '
        "was changed."
    )


def test_a_store_fault_is_rendered_not_dumped(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, identities = _engine()
    identities.fail_next()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["links", "list"])

    assert result.exit_code == 1
    assert not isinstance(result.exception, IdentityStoreError)


def test_an_account_identifier_cannot_pose_as_a_line(output: StringIO) -> None:
    """Every engine-supplied value is escaped and quoted."""
    entry = LinkedAccount(
        link_id="link:1",
        person_id=OWNER_PERSON_ID,
        account=Account(kind="telegram", identifier='42\n  Level: strong "x"'),
        most=Sureness.NORMAL,
        level=Sureness.NONE,
    )

    link_inspection.render_listing(Console(file=output, force_terminal=False, width=400), (entry,))

    lines = output.getvalue().splitlines()
    assert lines[0] == 'Link "link:1": "telegram" account "42\\n  Level: strong \\"x\\""'
    assert sum(line.lstrip().startswith("Level:") for line in lines) == 1
