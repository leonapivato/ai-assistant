"""The assistant's message, rendered in a conversation for this terminal (ADR-0042 §4).

``test_cli`` pins these properties on ``ask``'s rendering of a composed answer,
``_render_reply``, which retires with ``ask`` at the cutover (ADR-0309 §5:1). What the
assistant says reaches this terminal afterwards as a message in a conversation, rendered
by the chat surface's ``_render_chat_entry``. Each case here is one of ``test_cli``'s,
run against that renderer: model output is neutralised — Rich markup escaped and every
character a terminal would act on replaced — while its line breaks, whichever ending
wrote them, stay the breaks they are.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from typing import Final

import pytest
from rich.console import Console

from ai_assistant.core.types import MessageAuthor, TranscriptMessage
from ai_assistant.interfaces import cli

_AT: Final = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=100))
    return buffer


def _rendered(output: StringIO, text: str) -> str:
    """What the conversation shows for an assistant message carrying ``text``."""
    message = TranscriptMessage(
        conversation_id="c-1",
        position=2,
        author=MessageAuthor.ASSISTANT,
        written_at=_AT,
        text=text,
    )
    cli._render_chat_entry(message, known={})
    return output.getvalue()


def _lines(rendered: str) -> list[str]:
    """The rendered text of the message, each line without its gutter."""
    return [line.lstrip(" │").rstrip() for line in rendered.splitlines()[1:]]


def test_an_assistant_message_is_neutralised_for_the_terminal(output: StringIO) -> None:
    """§4: Rich markup inside model output is shown, and an escape never reaches here."""
    rendered = _rendered(output, "[bold red]not markup[/] \x1b[31m")

    assert "not markup" in rendered
    assert "[bold red]" in rendered, "shown as text, not consumed as a style"
    assert "\x1b[31m" not in rendered


def test_a_multi_paragraph_message_keeps_the_breaks_it_was_written_with(
    output: StringIO,
) -> None:
    """#1336: a paragraph break is content, not a character to neutralise."""
    rendered = _rendered(output, "Blocked for deep work.\n\nOne caveat worth being straight.")

    assert "�" not in rendered, "the breaks are content, not characters to neutralise"
    lines = _lines(rendered)
    first = lines.index("Blocked for deep work.")
    assert lines[first + 1] == ""
    assert lines[first + 2] == "One caveat worth being straight."


@pytest.mark.parametrize("ending", ["\r\n", "\r", "\n"], ids=["crlf", "cr", "lf"])
def test_a_message_written_with_any_line_ending_renders_as_one_break(
    output: StringIO, ending: str
) -> None:
    """A ``\\r`` must neither reach the terminal nor cost the break it was part of."""
    rendered = _rendered(output, f"First.{ending}Second.")

    assert "\r" not in rendered, "the character a terminal would act on never reaches it"
    assert "�" not in rendered
    lines = _lines(rendered)
    first = lines.index("First.")
    assert lines[first + 1] == "Second."


def test_the_break_is_kept_and_every_other_control_character_is_neutralised(
    output: StringIO,
) -> None:
    """Only the break is spared; §4's obligation is otherwise discharged whole."""
    rendered = _rendered(output, "First.\n\x1b[2JSecond.\x07")

    assert "\x1b" not in rendered
    assert "\x07" not in rendered
    assert rendered.count("�") == 2, "the escape and the bell, and nothing else"
    assert "First." in _lines(rendered)


def test_rich_markup_split_across_a_break_is_shown_and_not_consumed(output: StringIO) -> None:
    """Rich's tag pattern matches across a newline, so the whole value is escaped."""
    rendered = _rendered(output, "[red\nbold]still here")

    assert "still here" in rendered
    assert "[red" in rendered, "shown as text, not consumed as a style"
    assert "bold]" in rendered
