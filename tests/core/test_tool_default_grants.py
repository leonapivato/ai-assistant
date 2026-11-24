"""Every tool the system declares carries its default grant (ADR-0367 §4:3, ADR-0380 §4).

Two ways of finding the declarations, so that neither passes vacuously:

- **The sweep** imports every module under ``ai_assistant`` and collects each declaration
  held at module level, alone or in a tuple, which is how every tool is declared: the
  registry's integrations, the assistant's own records' calls, ``send_text``,
  ``note_reliance``, and the canonical fakes' search and forecast.
- **The composed hub** is built over an empty data directory and asked for every tool its
  phases offer, the registry's and the own records' alike, so a declaration made other
  than at module level is still found.

The table pins each declaration's how and bar, as the owner chose them on 2026-11-24
(#3678, "The default grants"): normal for what leaves the hub, weak for the rest; how
``allowed`` on every one. A change to one is a visible diff here, and a declaration the
table does not name fails the sweep.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING, Final

import pytest

import ai_assistant
from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import GrantHow, Sureness, ToolDefinition
from ai_assistant.orchestration.message_tools import TEXT_CALL

if TYPE_CHECKING:
    from pathlib import Path

_WEAK: Final = (GrantHow.ALLOWED, Sureness.WEAK)
_NORMAL: Final = (GrantHow.ALLOWED, Sureness.NORMAL)

#: Each declaration by its id, with its capability, its how and its bar.
DEFAULT_GRANTS: Final[dict[str, tuple[str, tuple[GrantHow, Sureness]]]] = {
    # Anything that leaves the system: normal.
    "email": ("send_email", _NORMAL),
    "web_search": ("search_web", _NORMAL),
    "fake_web_search": ("search_web", _NORMAL),
    "forecast_read": ("read_forecast", _NORMAL),
    "fake_forecast_read": ("read_forecast", _NORMAL),
    "simulated_booking_availability": ("booking_availability", _NORMAL),
    "simulated_booking": ("book_stay", _NORMAL),
    # Answering: weak, so a reminder set at weak can speak when it comes due.
    "text": ("send_text", _WEAK),
    # Look-ups: weak.
    "current_time": ("report_current_time", _WEAK),
    "read_episode": ("read_episode", _WEAK),
    "read_story": ("read_matter", _WEAK),
    "read_older_history": ("read_origin_history", _WEAK),
    "follow_up": ("reread_result", _WEAK),
    "search_connections": ("search_connections", _WEAK),
    "search_episodes": ("search_episodes", _WEAK),
    "search_memory": ("search_memories", _WEAK),
    # The person's own reminders: weak.
    "spawn": ("spawn_task", _WEAK),
    "list_tasks": ("list_tasks", _WEAK),
    "cancel_task": ("cancel_task", _WEAK),
    # The person's own memory and profile: weak.
    "remember": ("remember_fact", _WEAK),
    "pin": ("pin_memory", _WEAK),
    "unpin": ("unpin_memory", _WEAK),
    "set_profile": ("set_profile_field", _WEAK),
    "note_reliance": ("note_reliance", _WEAK),
    # The person's own matters: weak.
    "start_story": ("start_matter", _WEAK),
    "note_story": ("note_matter", _WEAK),
    "link_story": ("add_to_matter", _WEAK),
    "unlink_story": ("remove_from_matter", _WEAK),
    "move_story": ("move_to_matter", _WEAK),
    "merge_stories": ("merge_matters", _WEAK),
    "split_story": ("split_matter", _WEAK),
    "group_stories": ("group_matters", _WEAK),
    "tidy_story": ("tidy_matter", _WEAK),
    # The work's own running: weak.
    "stop_activation": ("stop_work", _WEAK),
    "answer_offer": ("answer_offer", _WEAK),
    "request_approval": ("request_approval", _WEAK),
}


def _declared_in(value: object) -> list[ToolDefinition]:
    if isinstance(value, ToolDefinition):
        return [value]
    if isinstance(value, tuple | list) and value:
        held = list(value)
        if all(isinstance(one, ToolDefinition) for one in held):
            return held
    return []


def _swept() -> dict[str, list[tuple[str, ToolDefinition]]]:
    """Every module-level declaration under ``ai_assistant``, by id, with where it is held."""
    found: dict[str, list[tuple[str, ToolDefinition]]] = {}
    for module_info in pkgutil.walk_packages(ai_assistant.__path__, "ai_assistant."):
        module = importlib.import_module(module_info.name)
        for name, value in vars(module).items():
            for tool in _declared_in(value):
                found.setdefault(str(tool.id), []).append((f"{module_info.name}.{name}", tool))
    return found


@pytest.fixture(scope="module")
def swept() -> dict[str, list[tuple[str, ToolDefinition]]]:
    return _swept()


def test_the_sweep_finds_the_declarations_it_must(
    swept: dict[str, list[tuple[str, ToolDefinition]]],
) -> None:
    """Not vacuous: ``send_text`` and the registry's email are among what it found."""
    assert "text" in swept
    assert "email" in swept
    assert len(swept) >= len(DEFAULT_GRANTS)


def test_every_declaration_carries_a_default_grant(
    swept: dict[str, list[tuple[str, ToolDefinition]]],
) -> None:
    """ADR-0380 §4:1, §4:2: none without one, wherever it is held."""
    missing = sorted(
        where for held in swept.values() for where, tool in held if tool.default_grant is None
    )
    assert not missing, f"declared with no default grant (ADR-0380 §4:1): {missing}"


def test_each_declarations_default_grant_is_the_one_the_table_pins(
    swept: dict[str, list[tuple[str, ToolDefinition]]],
) -> None:
    """The owner's choice, per tool; a declaration the table does not name fails here."""
    read = {
        tool_id: {
            (
                str(tool.capability),
                (tool.default_grant.how, tool.default_grant.bar),
            )
            for _, tool in held
            if tool.default_grant is not None
        }
        for tool_id, held in swept.items()
    }
    assert read == {tool_id: {pinned} for tool_id, pinned in DEFAULT_GRANTS.items()}


def test_normal_is_exactly_what_leaves_the_hub(
    swept: dict[str, list[tuple[str, ToolDefinition]]],
) -> None:
    """The owner's rule as declared: a bar of normal where a call leaves the hub."""
    for held in swept.values():
        for where, tool in held:
            assert tool.default_grant is not None, where
            expected = Sureness.NORMAL if tool.leaves_hub else Sureness.WEAK
            assert tool.default_grant.bar is expected, where


def test_no_default_grant_says_with_approval(
    swept: dict[str, list[tuple[str, ToolDefinition]]],
) -> None:
    """What needs a yes today stays the approval rules' and the policy's (ADR-0367 §4:5)."""
    hows = {
        tool.default_grant.how
        for held in swept.values()
        for _, tool in held
        if tool.default_grant is not None
    }
    assert hows == {GrantHow.ALLOWED}


@pytest.mark.integration
async def test_every_tool_the_composed_hub_offers_carries_a_default_grant(
    tmp_path: Path,
) -> None:
    """ADR-0380 §4:1 on the running hub: its registry's tools and its own records' calls.

    ``send_text`` is offered beside them by the phases rather than held by the tools, so it
    is checked by itself.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        phases = engine._phases
        assert phases is not None
        offered = await phases._tools.all_tools()
    finally:
        await engine.aclose()

    ids = {str(tool.id) for tool in offered}
    assert {"current_time", "remember", "spawn", "stop_activation", "request_approval"} <= ids
    missing = sorted(str(tool.id) for tool in offered if tool.default_grant is None)
    assert not missing, f"offered with no default grant (ADR-0380 §4:1): {missing}"
    assert ids <= set(DEFAULT_GRANTS), "the table pins every tool the hub offers"
    assert TEXT_CALL.default_grant is not None
