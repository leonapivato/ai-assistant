"""``PROTOCOL_VERSION`` moved once for the old path's vocabulary (ADR-0318 §7:3).

§7:3 has the lane that implements the decision advance the constant once, for every
ground at once, and the entry name each. A test holds that the number moved and that
the move is accounted for in the log a reviewer reads, which is
``test_recipient_grant_protocol_version.py``'s reasoning: ADR-0124 §9 makes the bump
rule a review obligation and decides no mechanical check.
"""

from __future__ import annotations

import inspect
from typing import Final

import pytest

from ai_assistant.wire import envelope

#: The version ADR-0318 §7:3 moves to, read at the moment the lane landed, and the one
#: it moves from. The absolute figure has one home,
#: ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 104
_MOVED_FROM: Final = 103


def test_the_protocol_version_moved_past_the_figure_this_decision_reached() -> None:
    """§7:3: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision() -> None:
    """The entry names ADR-0318 §7:3, and the one it follows stands unrewritten."""
    entry = _entry_for(_MOVED_TO)

    assert "ADR-0318 §7:3" in entry
    assert f"#: {_MOVED_FROM}: " in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


@pytest.mark.parametrize(
    "ground",
    [
        pytest.param("ActivationLinks", id="the record's links"),
        pytest.param("response_degraded", id="the compose stage's degradation"),
        pytest.param("RecordedResumeTrigger", id="the resume trigger"),
        pytest.param("Literal[11]", id="the record's version"),
        pytest.param("step_disposition", id="the stage verdicts"),
        pytest.param("ADR-0309 §3:6-§3:7", id="the controller's members"),
        pytest.param("waiting", id="the waiting status"),
        pytest.param("composition_failed", id="the reasons"),
        pytest.param("no_input", id="the omissions"),
        pytest.param("execution_id", id="the decision row"),
        pytest.param("facet", id="the grant use"),
    ],
)
def test_the_entry_names_each_ground(ground: str) -> None:
    """§7:3: one advance covers every ground, so the entry names every one."""
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
