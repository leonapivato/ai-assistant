"""What each built tool declares under ADR-0306 §2, pinned (ADR-0312 §2 for the reads).

The five values are the hub's declarations (§2:4), and a change to one changes which
calls are claimed, recorded, digested or refused as already done, so each is pinned
here rather than left to be discovered.
"""

from __future__ import annotations

import pytest

from ai_assistant.core.types import CapabilityEffect, CapabilityResult, ToolDefinition
from ai_assistant.testing.forecasting import FAKE_FORECAST_READ
from ai_assistant.testing.searching import FAKE_WEB_SEARCH
from ai_assistant.tools.booking import BOOKING_ACT, BOOKING_AVAILABILITY
from ai_assistant.tools.builtin import CURRENT_TIME
from ai_assistant.tools.forecast import FORECAST_READ
from ai_assistant.tools.send_email import EMAIL
from ai_assistant.tools.web_search import WEB_SEARCH

_NONE = CapabilityEffect.NONE
_WORLD = CapabilityEffect.WORLD
_MAY = CapabilityResult.MAY_CARRY_OUTSIDE_TEXT
_NO = CapabilityResult.NO_OUTSIDE_TEXT

#: effect, leaves the hub, result, outcome can be unknown, safe to repeat.
_DECLARED: list[tuple[ToolDefinition, tuple[object, ...]]] = [
    (CURRENT_TIME, (_NONE, False, _NO, False, True)),
    (WEB_SEARCH, (_NONE, True, _MAY, True, True)),
    (FAKE_WEB_SEARCH, (_NONE, True, _MAY, True, True)),
    (FORECAST_READ, (_NONE, True, _MAY, True, True)),
    (FAKE_FORECAST_READ, (_NONE, True, _MAY, True, True)),
    (EMAIL, (_WORLD, True, _NO, True, False)),
    (BOOKING_AVAILABILITY, (_NONE, True, _NO, False, True)),
    (BOOKING_ACT, (_WORLD, True, _NO, True, False)),
]


@pytest.mark.parametrize(
    ("tool", "declared"), _DECLARED, ids=[f"{tool.id}" for tool, _ in _DECLARED]
)
def test_each_tool_declares_its_five_properties(
    tool: ToolDefinition, declared: tuple[object, ...]
) -> None:
    """ADR-0306 §2:1: each declaration states all five, as the hub chose them."""
    assert (
        tool.effect,
        tool.leaves_hub,
        tool.result,
        tool.outcome_can_be_unknown,
        tool.safe_to_repeat,
    ) == declared


def test_one_capability_declares_one_set_of_properties() -> None:
    """§2:7: every tool satisfying one capability declares the same five."""
    by_capability: dict[str, set[tuple[object, ...]]] = {}
    for tool, declared in _DECLARED:
        by_capability.setdefault(tool.capability, set()).add(declared)

    assert all(len(sets) == 1 for sets in by_capability.values())
