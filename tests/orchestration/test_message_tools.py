"""ADR-0364 §9: what every message call shares, read without the phases.

``send_text``'s declaration and the check of its arguments (§9:1-§9:2), the exact parts
words mark and their escapes (§9:6-§9:8), the pass-through wording step (§9:9), and
``send_email``'s names, pinned to the declaration ``tools`` spells (§9:11-§9:14).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.orchestration.message_tools import (
    BCC_ARGUMENT,
    CC_ARGUMENT,
    CONNECTION_ARGUMENT,
    EMAIL_CAPABILITY,
    FROM_ARGUMENT,
    SUBJECT_ARGUMENT,
    TEXT_CALL,
    TEXT_CAPABILITY,
    TO_ARGUMENT,
    WORDS_ARGUMENT,
    ExactWords,
    TextArguments,
    escaped_exact,
    exact_words,
    platform_name,
    reworded,
    text_arguments,
)
from ai_assistant.tools import send_email
from ai_assistant.tools.send_email import EMAIL

if TYPE_CHECKING:
    from ai_assistant.core.types import ToolDefinition


def _schema(tool: ToolDefinition) -> dict[str, Any]:
    """A declaration's parameters schema as plain JSON, for reading."""
    schema: dict[str, Any] = tool.model_dump(mode="json")["parameters_schema"]
    return schema


# --- send_text's declaration (§9:1-§9:2) -------------------------------------------------


def test_send_text_takes_a_connection_and_words_and_nothing_else() -> None:
    """§9:1: ``to`` goes, since who a message reaches is its connection's."""
    schema = _schema(TEXT_CALL)
    assert TEXT_CALL.capability == TEXT_CAPABILITY == "send_text"
    assert TEXT_CALL.id == "text"
    assert list(schema["required"]) == [CONNECTION_ARGUMENT, WORDS_ARGUMENT]
    assert set(schema["properties"]) == {CONNECTION_ARGUMENT, WORDS_ARGUMENT}
    assert schema["additionalProperties"] is False


def test_the_connection_is_checked_by_its_pattern_with_no_enum() -> None:
    """§9:2: an ``L`` label by pattern, so the offered tools stay identical across works."""
    connection = _schema(TEXT_CALL)["properties"][CONNECTION_ARGUMENT]
    assert connection["pattern"] == "^L[1-9][0-9]*$"
    assert "enum" not in connection


def test_well_formed_arguments_are_read_whole() -> None:
    checked = text_arguments({CONNECTION_ARGUMENT: "L2", WORDS_ARGUMENT: "Running late."})
    assert checked == TextArguments(connection="L2", words="Running late.")


@pytest.mark.parametrize(
    ("arguments", "said"),
    [
        pytest.param({CONNECTION_ARGUMENT: "L1"}, WORDS_ARGUMENT, id="no-words"),
        pytest.param({CONNECTION_ARGUMENT: "L1", WORDS_ARGUMENT: "  "}, WORDS_ARGUMENT, id="blank"),
        pytest.param({WORDS_ARGUMENT: "Hi."}, CONNECTION_ARGUMENT, id="no-connection"),
        pytest.param(
            {CONNECTION_ARGUMENT: "Telegram", WORDS_ARGUMENT: "Hi."},
            CONNECTION_ARGUMENT,
            id="a-platform-by-name",
        ),
        pytest.param(
            {CONNECTION_ARGUMENT: "L1", WORDS_ARGUMENT: "Hi.", "to": "the owner"},
            "nothing else",
            id="undeclared",
        ),
    ],
)
def test_an_argument_missing_or_wrong_comes_back_saying_which(
    arguments: dict[str, object], said: str
) -> None:
    checked = text_arguments(arguments)
    assert isinstance(checked, str)
    assert said in checked


def test_a_result_names_each_platform() -> None:
    assert platform_name("conversation") == "the hub chat"
    assert platform_name("telegram") == "Telegram"
    assert platform_name("email") == "email"


# --- exact parts (§9:6-§9:8) -------------------------------------------------------------


def test_words_with_no_tag_are_read_as_written() -> None:
    assert exact_words("See you at 7.") == ExactWords(text="See you at 7.")


def test_a_marked_part_is_read_out_and_its_tags_removed() -> None:
    read = exact_words('She said <exact>"bring the blue folder"</exact>, so bring it.')
    assert read == ExactWords(
        text='She said "bring the blue folder", so bring it.',
        parts=('"bring the blue folder"',),
    )


def test_a_message_wrapped_whole_is_one_part() -> None:
    read = exact_words("<exact>Dinner moved to 8.</exact>")
    assert read == ExactWords(text="Dinner moved to 8.", parts=("Dinner moved to 8.",))


@pytest.mark.parametrize(
    ("words", "said"),
    [
        pytest.param("Say <exact>this", "never closed", id="unclosed"),
        pytest.param("<exact>a <exact>b</exact></exact>", "inside", id="nested"),
        pytest.param("this</exact>", "closes no", id="stray-close"),
    ],
)
def test_a_tag_that_does_not_close_comes_back_not_done(words: str, said: str) -> None:
    """§9:8: an unclosed tag, a tag opened inside a part, or a stray close."""
    read = exact_words(words)
    assert isinstance(read, str)
    assert said in read


def test_a_backslash_before_a_tag_sends_it_as_literal_text() -> None:
    """§9:8: one backslash sends the tag as written, and is itself not sent."""
    read = exact_words(r"Type \<exact> to mark a part.")
    assert read == ExactWords(text="Type <exact> to mark a part.")


def test_two_backslashes_send_one_and_leave_the_tag_a_tag() -> None:
    read = exact_words("a path C:\\\\<exact>dir</exact>")
    assert read == ExactWords(text="a path C:\\dir", parts=("dir",))


@pytest.mark.parametrize(
    "words",
    [
        "Plain words.",
        "A literal <exact> tag and a </exact> one.",
        "Escaped already: \\<exact> and \\\\</exact>.",
    ],
)
def test_words_wrapped_whole_read_back_exactly(words: str) -> None:
    """§8:6: an old ``exact`` call's words, wrapped whole with their tags escaped."""
    assert exact_words(escaped_exact(words)) == ExactWords(text=words, parts=(words,))


def test_until_the_wording_step_is_built_the_words_go_as_written_tags_removed() -> None:
    """§9:9: nothing is reworded, and the tags are removed."""
    read = exact_words("Tell her <exact>the code is 4471</exact>.")
    assert not isinstance(read, str)
    assert reworded(read) == "Tell her the code is 4471."


# --- send_email's names (§9:11-§9:14) ------------------------------------------------------


def test_emails_names_are_the_ones_its_declaration_spells() -> None:
    """ADR-0364 §8:1: the capability is ``send_email``, its id still ``email``."""
    schema = _schema(EMAIL)
    assert EMAIL.capability == EMAIL_CAPABILITY == send_email.EMAIL_CAPABILITY == "send_email"
    assert EMAIL.id == send_email.EMAIL_ID == "email"
    properties = schema["properties"]
    assert set(properties) == {
        FROM_ARGUMENT,
        TO_ARGUMENT,
        CC_ARGUMENT,
        BCC_ARGUMENT,
        SUBJECT_ARGUMENT,
        WORDS_ARGUMENT,
    }
    assert list(schema["required"]) == [FROM_ARGUMENT, TO_ARGUMENT, SUBJECT_ARGUMENT, "words"]


def test_an_email_takes_no_attachment_and_no_exact() -> None:
    """§9:6, §9:14: ``exact`` and ``attachments`` go."""
    properties = _schema(EMAIL)["properties"]
    assert "attachments" not in properties
    assert "exact" not in properties
