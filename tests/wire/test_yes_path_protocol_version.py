"""``PROTOCOL_VERSION`` moved once for the yes path's contracts (ADR-0321 §9:2).

§9:2 has each change to a shape the wire carries advance the constant on ADR-0124 §9's
rule. This lane's grounds are the episode record's asked calls, answer pointer and
approved-action label kind, and the decision's approval. A test holds that the number
moved and that the move is accounted for in the log a reviewer reads, which is
``test_stores_and_types_protocol_version.py``'s reasoning: ADR-0124 §9 makes the bump
rule a review obligation and decides no mechanical check.
"""

from __future__ import annotations

import inspect
from typing import Final

import pytest

from ai_assistant.wire import envelope

#: The version ADR-0321 §9:2 moves to for this lane, read at the moment the lane landed,
#: and the one it moves from. The absolute figure has one home,
#: ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 106
_MOVED_FROM: Final = 105


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """§9:2: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision() -> None:
    """The entry names ADR-0321 §9:2, and the one it follows stands unrewritten."""
    entry = _entry_for(_MOVED_TO)

    assert "ADR-0321 §9:2" in entry
    assert f"#: {_MOVED_FROM}: " in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


@pytest.mark.parametrize(
    "ground",
    [
        pytest.param("AskedCall", id="the round's asked calls"),
        pytest.param("AnsweredQuestion", id="the understanding's answer pointer"),
        pytest.param("approved_action", id="the approved-action label kind"),
        pytest.param("Approval", id="the decision's approval"),
        pytest.param("QuestionPart", id="the part the decision runs under"),
    ],
)
def test_the_entry_names_each_ground(ground: str) -> None:
    """§9:2: one advance covers every ground, so the entry names every one."""
    assert ground in _entry_for(_MOVED_TO)


def _entry_for(version: int) -> str:
    """The version log's entry for one version, one line, comment prefixes removed.

    Args:
        version: The version whose entry to return.

    Returns:
        That entry's prose.
    """
    source = inspect.getsource(envelope)
    entry = source.split(f"#: {version}: ")[-1].split("PROTOCOL_VERSION: Final")[0]
    stripped = (line.removeprefix("#:").strip() for line in entry.splitlines())
    return " ".join(part for part in stripped if part)
