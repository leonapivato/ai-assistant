"""ADR-0357 §2 and §4: what every message call shares, read without the phases.

``text``'s declaration and the check of its arguments, who a message is for, the
platforms ``via`` names, the pass-through wording step, and ``email``'s names, pinned to
the declaration ``tools`` spells. ``text`` takes no ``asks`` and no message carries exact
lines (ADR-0361 §8:5): a yes is asked for by ``request_approval`` alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.orchestration.message_tools import (
    ATTACHMENTS_ARGUMENT,
    BCC_ARGUMENT,
    CC_ARGUMENT,
    EMAIL_CAPABILITY,
    EXACT_ARGUMENT,
    FROM_ARGUMENT,
    FROM_ASSISTANT,
    FROM_USER,
    SUBJECT_ARGUMENT,
    TEXT_CALL,
    TEXT_CAPABILITY,
    TO_ARGUMENT,
    VIA_ARGUMENT,
    WORDS_ARGUMENT,
    TextArguments,
    platform_name,
    platform_type,
    reworded,
    text_arguments,
    who_it_is_for,
)
from ai_assistant.tools import send_email
from ai_assistant.tools.send_email import EMAIL

if TYPE_CHECKING:
    from ai_assistant.core.types import ToolDefinition


def _schema(tool: ToolDefinition) -> dict[str, Any]:
    """A declaration's parameters schema as plain JSON, for reading."""
    schema: dict[str, Any] = tool.model_dump(mode="json")["parameters_schema"]
    return schema


# --- text's declaration (§2:2) ----------------------------------------------------------


def test_text_takes_to_and_words_required_and_via_and_exact_optional() -> None:
    """§2:2: who and what are the choices that cannot be left to the tool (§5:3).

    ADR-0361 §8:5: ``asks`` is no longer among them.
    """
    schema = _schema(TEXT_CALL)
    assert TEXT_CALL.capability == TEXT_CAPABILITY
    assert list(schema["required"]) == [TO_ARGUMENT, WORDS_ARGUMENT]
    assert set(schema["properties"]) == {TO_ARGUMENT, WORDS_ARGUMENT, VIA_ARGUMENT, EXACT_ARGUMENT}
    assert schema["additionalProperties"] is False


def test_texts_schema_encodes_no_conditional_requirement() -> None:
    """§5:6: a requirement that depends on other arguments is the tool's check."""
    schema = _schema(TEXT_CALL)
    for keyword in ("if", "then", "else", "dependentRequired", "dependentSchemas", "oneOf"):
        assert keyword not in schema
    assert "anyOf" not in schema


def test_texts_description_says_it_is_sent_as_the_assistant() -> None:
    """§2:9: text is always sent in the system's own voice, and takes no argument naming whose.

    The assistant is named "the system" everywhere planning reads (ADR-0353 §4:2).
    """
    assert "in the system's own voice" in TEXT_CALL.description
    assert FROM_ARGUMENT not in _schema(TEXT_CALL)["properties"]


# --- text's arguments (§6:1, §6:3) -------------------------------------------------------


def test_well_formed_arguments_are_read_whole() -> None:
    checked = text_arguments({"to": "the user", "words": "On it.", "via": " L2 ", "exact": True})
    assert checked == TextArguments(to="the user", words="On it.", via="L2", exact=True)


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
        pytest.param(
            {"to": "the user", "words": "Hi.", "asks": ["1.1"]}, "nothing else", id="asks"
        ),
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


# --- the wording step (§4) ----------------------------------------------------------------


@pytest.mark.parametrize("exact", [True, False])
def test_until_the_wording_step_is_built_every_messages_words_go_unchanged(exact: bool) -> None:
    """§4:3: ``exact`` is accepted and changes nothing."""
    words = "  Tell her: 'I'll be late'  \n"
    assert reworded(words, exact=exact) == words


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
    assert "asks" not in properties  # ADR-0361 §8:5: no message asks
    assert EMAIL.safe_to_repeat is False
