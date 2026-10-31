"""ADR-0357 §2, §4 and §8:2: what every message call shares, read without the phases.

``text``'s declaration and the check of its arguments, who a message is for, the
platforms ``via`` names, the pass-through wording step, the asking message's lines, and
``email``'s names, pinned to the declaration ``tools`` spells.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.orchestration.message_tools import (
    ASKS_ARGUMENT,
    ATTACHMENTS_ARGUMENT,
    BCC_ARGUMENT,
    CC_ARGUMENT,
    EMAIL_CAPABILITY,
    EXACT_ARGUMENT,
    FROM_ARGUMENT,
    FROM_ASSISTANT,
    FROM_USER,
    NEEDS_YOUR_YES,
    SUBJECT_ARGUMENT,
    TEXT_CALL,
    TEXT_CAPABILITY,
    TO_ARGUMENT,
    VIA_ARGUMENT,
    WORDS_ARGUMENT,
    TextArguments,
    asks_named,
    carries_asks,
    platform_name,
    platform_type,
    reworded,
    text_arguments,
    who_it_is_for,
    with_question,
)
from ai_assistant.tools import send_email
from ai_assistant.tools.send_email import EMAIL

if TYPE_CHECKING:
    from ai_assistant.core.types import ToolDefinition

_LINE: Final = 'book — slot: "19:00"'


def _schema(tool: ToolDefinition) -> dict[str, Any]:
    """A declaration's parameters schema as plain JSON, for reading."""
    schema: dict[str, Any] = tool.model_dump(mode="json")["parameters_schema"]
    return schema


# --- text's declaration (§2:2) ----------------------------------------------------------


def test_text_takes_to_and_words_required_and_via_exact_and_asks_optional() -> None:
    """§2:2: who and what are the choices that cannot be left to the tool (§5:3)."""
    schema = _schema(TEXT_CALL)
    assert TEXT_CALL.capability == TEXT_CAPABILITY
    assert list(schema["required"]) == [TO_ARGUMENT, WORDS_ARGUMENT]
    assert set(schema["properties"]) == {
        TO_ARGUMENT,
        WORDS_ARGUMENT,
        VIA_ARGUMENT,
        EXACT_ARGUMENT,
        ASKS_ARGUMENT,
    }
    assert schema["additionalProperties"] is False


def test_texts_schema_encodes_no_conditional_requirement() -> None:
    """§5:6: a requirement that depends on other arguments is the tool's check."""
    schema = _schema(TEXT_CALL)
    for keyword in ("if", "then", "else", "dependentRequired", "dependentSchemas", "oneOf"):
        assert keyword not in schema
    assert "anyOf" not in schema


def test_texts_description_says_it_is_sent_as_the_assistant() -> None:
    """§2:9: text is always sent as the assistant, and takes no argument naming whose voice."""
    assert "as the assistant" in TEXT_CALL.description
    assert FROM_ARGUMENT not in _schema(TEXT_CALL)["properties"]


# --- text's arguments (§6:1, §6:3) -------------------------------------------------------


def test_well_formed_arguments_are_read_whole() -> None:
    checked = text_arguments(
        {"to": "the user", "words": "On it.", "via": " L2 ", "exact": True, "asks": ["1.1"]}
    )
    assert checked == TextArguments(
        to="the user", words="On it.", via="L2", exact=True, asks=("1.1",)
    )


def test_left_out_optional_arguments_are_the_tools_to_decide() -> None:
    assert text_arguments({"to": "the user", "words": "On it."}) == TextArguments(
        to="the user", words="On it."
    )


@pytest.mark.parametrize(
    ("arguments", "says"),
    [
        pytest.param({"to": "the user"}, "'words'", id="no-words"),
        pytest.param({"to": "the user", "words": "  "}, "'words'", id="blank-words"),
        pytest.param({"words": "Hi."}, "'to'", id="no-one"),
        pytest.param({"to": 3, "words": "Hi."}, "'to'", id="to-not-text"),
        pytest.param({"to": "the user", "words": "Hi.", "via": []}, "'via'", id="via-list"),
        pytest.param({"to": "the user", "words": "Hi.", "via": " "}, "'via'", id="via-blank"),
        pytest.param({"to": "the user", "words": "Hi.", "exact": "yes"}, "'exact'", id="exact"),
        pytest.param({"to": "the user", "words": "Hi.", "asks": "1.1"}, "'asks'", id="asks"),
        pytest.param({"to": "the user", "words": "Hi.", "asks": [""]}, "'asks'", id="asks-blank"),
        pytest.param({"to": "the user", "words": "Hi.", "from": "user"}, "nothing else", id="from"),
    ],
)
def test_an_argument_missing_or_wrong_comes_back_saying_which(
    arguments: dict[str, object], says: str
) -> None:
    """§6:3: an argument that is missing or wrong is never guessed."""
    checked = text_arguments(arguments)
    assert isinstance(checked, str)
    assert says in checked


def test_only_a_text_call_with_asks_not_empty_carries_it() -> None:
    """§8:1, §8:3: a malformed ``asks`` still makes its call the asking message."""
    assert carries_asks(TEXT_CAPABILITY, {"asks": ["1.1"]})
    assert carries_asks(TEXT_CAPABILITY, {"asks": "1.1"})
    assert not carries_asks(TEXT_CAPABILITY, {"asks": []})
    assert not carries_asks(TEXT_CAPABILITY, {"words": "Hi."})
    assert not carries_asks(EMAIL_CAPABILITY, {"asks": ["1.1"]})
    assert asks_named({"asks": ["1.1", " 1.2 "]}) == ("1.1", " 1.2 ")
    assert asks_named({"asks": "1.1"}) == ()


# --- who it is for (§2:3) ---------------------------------------------------------------


@pytest.mark.parametrize(
    "to", ["the user", "The User", "user", "Leonardo", "leonardo pivato", "Leo"]
)
def test_the_user_is_found_as_planning_was_shown_them(to: str) -> None:
    assert who_it_is_for(to, named=("Leonardo Pivato", "Leo")) is None


def test_a_name_that_fits_no_one_comes_back_with_who_it_could_be() -> None:
    """§2:3: never a guess."""
    why = who_it_is_for("Anna", named=("Leonardo Pivato",))
    assert why is not None
    assert "the user ('Leonardo Pivato')" in why
    bare = who_it_is_for("Anna")
    assert bare is not None
    assert bare.endswith("it could be the user")


# --- where it goes (§2:4, §3:1) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "channel_type"),
    [
        ("telegram", "telegram"),
        ("Telegram", "telegram"),
        ("hub_chat", "conversation"),
        ("the hub chat", "conversation"),
        ("hub-chat", "conversation"),
        ("whatsapp", None),
    ],
)
def test_a_platform_is_named_as_planning_writes_it(name: str, channel_type: str | None) -> None:
    assert platform_type(name) == channel_type


def test_a_result_names_each_platform() -> None:
    assert platform_name("telegram") == "Telegram"
    assert platform_name("conversation") == "the hub chat"
    assert platform_name("imessage") == "imessage"


# --- the wording step (§4) and the asking message (§8:2) ---------------------------------


@pytest.mark.parametrize("exact", [True, False])
def test_until_the_wording_step_is_built_every_messages_words_go_unchanged(exact: bool) -> None:
    """§4:3: ``exact`` is accepted and changes nothing."""
    words = "  Tell her: 'I'll be late'  \n"
    assert reworded(words, exact=exact) == words


def test_the_exact_lines_follow_the_words_under_the_fixed_line() -> None:
    """§8:2, ADR-0321 §2:5: after the words, after a blank line, under one fixed line."""
    assert with_question("Shall I book it?", _LINE) == (
        f"Shall I book it?\n\n{NEEDS_YOUR_YES}\n{_LINE}"
    )


def test_a_message_asking_nothing_is_its_words_as_they_are() -> None:
    words = f"Shall I?\n\n{NEEDS_YOUR_YES}"
    assert with_question(words, None) == words
    assert with_question(words, "") == words


@pytest.mark.parametrize("own", [NEEDS_YOUR_YES, "needs your yes", "  NEEDS YOUR YES :  \n"])
def test_a_fixed_line_the_words_end_with_is_dropped_so_it_appears_once(own: str) -> None:
    """#3103: the backstop, on the asking message's words."""
    asked = with_question(f"I'll book it if you say yes.\n\n{own}", _LINE)
    assert asked == f"I'll book it if you say yes.\n\n{NEEDS_YOUR_YES}\n{_LINE}"


def test_a_fixed_line_mid_words_is_left_as_written() -> None:
    words = f"Look under {NEEDS_YOUR_YES} below.\nShall I?"
    assert with_question(words, _LINE) == f"{words}\n\n{NEEDS_YOUR_YES}\n{_LINE}"


# --- email's names (§2:5) ---------------------------------------------------------------


def test_emails_names_are_the_ones_its_declaration_spells() -> None:
    """§2:5: the gate reads the arguments the tool declares, by the same names."""
    properties = _schema(EMAIL)["properties"]
    assert EMAIL.capability == EMAIL_CAPABILITY
    assert {
        TO_ARGUMENT,
        CC_ARGUMENT,
        BCC_ARGUMENT,
        SUBJECT_ARGUMENT,
        WORDS_ARGUMENT,
        ATTACHMENTS_ARGUMENT,
        FROM_ARGUMENT,
        EXACT_ARGUMENT,
    } == set(properties)
    assert list(_schema(EMAIL)["required"]) == [
        TO_ARGUMENT,
        SUBJECT_ARGUMENT,
        WORDS_ARGUMENT,
    ]
    assert list(properties[FROM_ARGUMENT]["enum"]) == [FROM_ASSISTANT, FROM_USER]
    assert (send_email.FROM_ASSISTANT, send_email.FROM_USER) == (FROM_ASSISTANT, FROM_USER)
    assert ASKS_ARGUMENT not in properties  # §8:1: an email's yes approves nothing
    assert EMAIL.safe_to_repeat is False
