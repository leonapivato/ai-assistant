"""The owner's permission lines, as the engine and the fake answer them (ADR-0376 §4).

What the shared contract cannot see from the surface: which connections among the things
the hub holds a line may name (§2:4), that the capabilities whose calls have a thing are the
ones the check derives a thing for (§2:3), and that the phases declare ``text`` beside the
tools their registry holds, each once.
"""

from __future__ import annotations

import pytest

from ai_assistant.core.types import (
    APPROVALS_CONNECTION,
    OWN_CHAT_CONNECTION,
    SCHEDULE_CONNECTION,
    ThingKey,
    ThingKind,
)
from ai_assistant.orchestration.message_tools import EMAIL_CAPABILITY, TEXT_CALL, TEXT_CAPABILITY
from ai_assistant.orchestration.permission_check import call_thing
from ai_assistant.orchestration.permission_lines import THING_CAPABILITIES, nameable_connections


def _connection(identifier: str) -> ThingKey:
    return ThingKey(kind=ThingKind.CONNECTION, identifier=identifier)


def test_a_line_may_name_each_held_connection_but_the_schedule_and_the_approvals() -> None:
    """§2:4: the system's own chat, a place and an account; never the two built-in places."""
    held = (
        _connection(OWN_CHAT_CONNECTION),
        _connection("telegram:conn-bot/42"),
        _connection(SCHEDULE_CONNECTION),
        _connection(APPROVALS_CONNECTION),
        _connection("account:mail-1"),
        ThingKey(kind=ThingKind.SOURCE, identifier="calendar"),
        ThingKey(kind=ThingKind.SOURCE, identifier="account:looks-like-one"),
    )

    assert nameable_connections(held) == {
        OWN_CHAT_CONNECTION,
        "telegram:conn-bot/42",
        "account:mail-1",
    }


def test_a_hub_holding_nothing_lets_a_line_name_no_connection() -> None:
    assert nameable_connections(()) == frozenset()


def test_the_capabilities_with_a_thing_are_the_two_message_calls() -> None:
    """§2:3: ``send_text``'s connection and ``send_email``'s account, and no other."""
    assert {TEXT_CAPABILITY, EMAIL_CAPABILITY} == THING_CAPABILITIES


@pytest.mark.parametrize("capability", ["remember_fact", "search_memories", "spawn_task"])
def test_the_check_derives_no_thing_for_a_capability_without_one(capability: str) -> None:
    """The check's ``call_thing`` agrees: a capability outside the two has none, even
    handed a place."""
    assert capability not in THING_CAPABILITIES
    assert call_thing(capability, place="telegram:conn-bot/42") is None


def test_the_check_derives_a_thing_for_each_capability_with_one() -> None:
    assert call_thing(TEXT_CAPABILITY, place="telegram:conn-bot/42") == "telegram:conn-bot/42"
    assert TEXT_CALL.capability == TEXT_CAPABILITY
