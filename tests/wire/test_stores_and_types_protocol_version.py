"""``PROTOCOL_VERSION`` moved once for the cutover's stores-and-types lane (ADR-0313 §6:4).

§6:4 has each lane §6 names advance the constant, and this lane's grounds are §3:3's
spoken delivery report, §5:4's members and their families, and the old path's errors
(ADR-0309 §5), which the wire rebuilds by name. A test holds that the number moved and
that the move is accounted for in the log a reviewer reads, which is
``test_old_vocabulary_protocol_version.py``'s reasoning: ADR-0124 §9 makes the bump rule
a review obligation and decides no mechanical check.
"""

from __future__ import annotations

import inspect
from typing import Final

import pytest

from ai_assistant.wire import envelope

#: The version ADR-0313 §6:4 moves to for this lane, read at the moment the lane landed,
#: and the one it moves from. The absolute figure has one home,
#: ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 105
_MOVED_FROM: Final = 104


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """§6:4: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision() -> None:
    """The entry names ADR-0313 §6:4, and the one it follows stands unrewritten."""
    entry = _entry_for(_MOVED_TO)

    assert "ADR-0313 §6:4" in entry
    assert f"#: {_MOVED_FROM}: " in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


@pytest.mark.parametrize(
    "ground",
    [
        pytest.param("intended_action", id="the decision's act"),
        pytest.param("authorised_goal", id="the ruling's goal scope"),
        pytest.param("proved_quote", id="the ruling's pinned quote"),
        pytest.param("bounded_arguments", id="the declaration's bounded arguments"),
        pytest.param("quoted_output", id="the declaration's quoted output"),
        pytest.param("charged_output", id="the declaration's charged output"),
        pytest.param("postconditions", id="the declaration's postconditions"),
        pytest.param("goal_id", id="the notification's goal"),
        pytest.param("SpokenDeliveryReport", id="the spoken delivery report"),
        pytest.param("ClaimRefused", id="the old path's errors"),
        pytest.param("ActiveExecutionError", id="the plan store's refusal"),
    ],
)
def test_the_entry_names_each_ground(ground: str) -> None:
    """§6:4: one advance covers every ground, so the entry names every one."""
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
