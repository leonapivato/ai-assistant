"""The permission-line commands: the owner's lines at the terminal (ADR-0376 §4 to §6).

Driven through the CLI over the canonical fake engine holding a line store, declaring
``text`` and holding the system's own chat and the line's place, so what is asserted is
what the command line renders of answers the hub would give (``line_inspection``), and
that each command sends what the owner typed and nothing else (§6:1). Each command that
could suggest a line decides a call says that none does yet (ADR-0367 §4:5).
"""

from __future__ import annotations

import asyncio
from io import StringIO
from typing import TYPE_CHECKING, Final

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import PermissionLineStoreError
from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    OWN_CHAT_CONNECTION,
    OWNER_PERSON_ID,
    GrantHow,
    PermissionLineEntry,
    PermissionLineKind,
    Sureness,
    ThingKey,
    ThingKind,
)
from ai_assistant.interfaces import cli, line_inspection
from ai_assistant.orchestration.message_tools import TEXT_CALL
from ai_assistant.testing import FakeAssistantEngine, FakePermissionLineStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine

_LINE_PLACE: Final = "telegram:conn-line/424242"


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Capture the CLI's console, wide enough that no line is wrapped."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=600))
    return buffer


def _wire(monkeypatch: pytest.MonkeyPatch, engine: AssistantEngine) -> None:
    async def opened() -> AssistantEngine:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", opened)


def _engine() -> tuple[FakeAssistantEngine, FakePermissionLineStore]:
    engine = FakeAssistantEngine()
    lines = FakePermissionLineStore()
    engine.lines = lines
    engine.declared_tools = (TEXT_CALL,)
    engine.held_things = (
        ThingKey(kind=ThingKind.CONNECTION, identifier=OWN_CHAT_CONNECTION),
        ThingKey(kind=ThingKind.CONNECTION, identifier=_LINE_PLACE),
    )
    return engine, lines


def _invoke(*args: str) -> int:
    return CliRunner().invoke(cli.app, ["permissions", *args]).exit_code


def _cleared(output: StringIO) -> None:
    output.truncate(0)
    output.seek(0)


#: The default line of ``text``, as the listing shows it.
_TEXT_DEFAULT: Final = [
    'Default grant of tool "text"',
    "  Who: anyone",
    '  Action: "send_text"',
    "  How: allowed, at weak or above",
]


def test_the_listing_shows_each_made_line_and_each_default(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, _ = _engine()
    _wire(monkeypatch, engine)
    assert (
        _invoke(
            "grant",
            "send_text",
            "--who",
            "me",
            "--how",
            "with_approval",
            "--bar",
            "normal",
            "--on",
            _LINE_PLACE,
            "--asked-through",
            OWN_CHAT_CONNECTION,
        )
        == 0
    )
    _cleared(output)

    assert _invoke("list") == 0

    assert output.getvalue().splitlines() == [
        'Grant "line:1", made by you',
        "  Who: you",
        '  Action: "send_text"',
        f'  On: "{_LINE_PLACE}"',
        "  How: allowed with approval, at normal or above",
        '  Only when every message the work acts on came by: "conversation"',
        *_TEXT_DEFAULT,
        line_inspection.HOW_TO_ACT,
        line_inspection.NOT_YET_DECIDING,
    ]
    assert engine.calls[-1] == ("permission_lines", {})


def test_a_listing_with_no_line_says_so(monkeypatch: pytest.MonkeyPatch, output: StringIO) -> None:
    _wire(monkeypatch, FakeAssistantEngine())

    assert _invoke("list") == 0

    assert output.getvalue().splitlines() == [
        line_inspection.NO_LINES,
        line_inspection.NOT_YET_DECIDING,
    ]


def test_a_grant_sends_what_the_owner_typed_and_shows_the_line(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§4:3, §6:1: ``me`` is the owner's identity; nothing else is added to the call."""
    engine, lines = _engine()
    _wire(monkeypatch, engine)

    code = _invoke("grant", "send_text", "--who", "me", "--how", "allowed", "--bar", "weak")

    assert code == 0
    assert output.getvalue().splitlines() == [
        "Made. The line stands until you remove it.",
        'Grant "line:1", made by you',
        "  Who: you",
        '  Action: "send_text"',
        "  How: allowed, at weak or above",
        line_inspection.NOT_YET_DECIDING,
    ]
    assert engine.calls == [
        (
            "make_grant",
            {
                "who": OWNER_PERSON_ID,
                "action": "send_text",
                "how": GrantHow.ALLOWED,
                "bar": Sureness.WEAK,
            },
        )
    ]
    held = asyncio.run(lines.standing())
    assert [(one.who, one.made_by) for one in held] == [(OWNER_PERSON_ID, OWNER_PERSON_ID)]


def test_a_repeated_grant_is_said_unchanged_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, _ = _engine()
    _wire(monkeypatch, engine)
    grant = ("grant", "send_text", "--who", "anyone", "--how", "allowed", "--bar", "none")
    assert _invoke(*grant) == 0
    _cleared(output)

    assert _invoke(*grant) == 0

    assert output.getvalue().splitlines()[0] == (
        "Unchanged: a line you made with exactly these parts already stands."
    )


def test_a_limit_names_who_the_action_and_its_connection(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, _ = _engine()
    _wire(monkeypatch, engine)

    assert _invoke("limit", "send_text", "--who", "anyone", "--on", _LINE_PLACE) == 0

    assert output.getvalue().splitlines() == [
        "Made. The line stands until you remove it.",
        'Limit "line:1", made by you',
        "  Who: anyone",
        '  Action: "send_text"',
        f'  On: "{_LINE_PLACE}"',
        line_inspection.NOT_YET_DECIDING,
    ]
    assert engine.calls == [
        ("make_limit", {"who": ANYONE_GROUP_ID, "action": "send_text", "thing": _LINE_PLACE})
    ]


@pytest.mark.parametrize(
    ("args", "said"),
    [
        (
            ("limit", "send_text", "--who", "person:guest"),
            "a line names you ('me') or 'anyone', and no one else yet",
        ),
        (
            ("limit", "book_stay", "--who", "me"),
            "no tool this hub declares has that capability; 'assistant permissions list' "
            "shows each tool's default line, with its capability",
        ),
        (
            ("limit", "send_text", "--who", "me", "--on", "task_scheduler:schedule"),
            f"a connection you named is not one this hub has. "
            f"{line_inspection.CONNECTION_SPELLING}",
        ),
    ],
)
def test_a_refused_making_says_why_and_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, output: StringIO, args: tuple[str, ...], said: str
) -> None:
    engine, lines = _engine()
    _wire(monkeypatch, engine)

    assert _invoke(*args) == 1

    assert output.getvalue().splitlines() == [
        f"Refused: {said}. Nothing was changed.",
        line_inspection.NOT_YET_DECIDING,
    ]
    assert asyncio.run(lines.standing()) == ()


@pytest.mark.parametrize(
    "args",
    [
        ("grant", "send_text", "--who", "me", "--how", "allowed"),
        ("grant", "send_text", "--who", "me", "--bar", "weak"),
        ("grant", "send_text", "--how", "allowed", "--bar", "weak"),
        ("grant", "send_text", "--who", "me", "--how", "sometimes", "--bar", "weak"),
        ("grant", "send_text", "--who", "me", "--how", "allowed", "--bar", "medium"),
        ("grant", "  ", "--who", "me", "--how", "allowed", "--bar", "weak"),
        ("limit", "send_text", "--who", " "),
        ("limit", "send_text", "--who", "me", "--on", " "),
        ("remove", ""),
    ],
)
def test_a_missing_or_malformed_part_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, output: StringIO, args: tuple[str, ...]
) -> None:
    """§4:3, §4:7: who, how and bar have no default; nothing is sent."""
    engine, _ = _engine()
    _wire(monkeypatch, engine)

    assert _invoke(*args) == 2
    assert engine.calls == []


def test_removing_a_line_shows_it_and_listing_after_shows_it_no_more(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, lines = _engine()
    _wire(monkeypatch, engine)
    assert _invoke("limit", "send_text", "--who", "me") == 0
    _cleared(output)

    assert _invoke("remove", "line:1") == 0

    assert output.getvalue().splitlines() == [
        "Removed. The line no longer stands, and is kept as removed.",
        'Limit "line:1", made by you',
        "  Who: you",
        '  Action: "send_text"',
    ]
    assert engine.calls[-1] == ("remove_line", {"line_id": "line:1"})
    kept = asyncio.run(lines.line("line:1"))
    assert kept is not None
    assert kept.removed_by == OWNER_PERSON_ID


def test_removing_what_does_not_stand_is_no_error(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§4:6: ``not_standing`` is not an error."""
    engine, _ = _engine()
    _wire(monkeypatch, engine)

    assert _invoke("remove", "line:7") == 0

    assert output.getvalue().strip() == (
        'No line you made with the id "line:7" stands, so nothing was changed.'
    )


def test_a_store_fault_is_rendered_not_dumped(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, lines = _engine()
    lines.fail_next()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["permissions", "list"])

    assert result.exit_code == 1
    assert not isinstance(result.exception, PermissionLineStoreError)


@pytest.mark.parametrize("args", [(), ("list",), ("grant",), ("limit",)])
def test_the_help_says_lines_do_not_decide_calls_yet(args: tuple[str, ...]) -> None:
    """The brief's one line: lines do not decide calls until the switch (ADR-0367 §4:5)."""
    result = CliRunner().invoke(cli.app, ["permissions", *args, "--help"], terminal_width=600)

    assert result.exit_code == 0
    assert " ".join(result.output.split()).count(line_inspection.NOT_YET_DECIDING) >= 1


def test_a_value_from_the_engine_cannot_pose_as_a_line(output: StringIO) -> None:
    """Every engine-supplied value is escaped and quoted."""
    entry = PermissionLineEntry(
        kind=PermissionLineKind.GRANT,
        who=ANYONE_GROUP_ID,
        action="send_text",
        how=GrantHow.ALLOWED,
        bar=Sureness.WEAK,
        tool_id='text\n  Who: you "x"',
    )

    line_inspection.render_listing(Console(file=output, force_terminal=False, width=400), (entry,))

    lines = output.getvalue().splitlines()
    assert lines[0] == 'Default grant of tool "text\\n  Who: you \\"x\\""'
    assert sum(line.lstrip().startswith("Who:") for line in lines) == 1
