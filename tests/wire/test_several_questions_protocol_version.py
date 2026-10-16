"""``PROTOCOL_VERSION`` moved once for several questions per reply (ADR-0322 §6:2).

§6:2 has the change advance the constant on ADR-0124 §9's rule. This lane's ground is
the understanding's answer pointer becoming a sequence, which the episode record the
wire carries holds. A test holds that the number moved and that the move is accounted
for in the log a reviewer reads, which is ``test_yes_path_protocol_version.py``'s
reasoning: ADR-0124 §9 makes the bump rule a review obligation and decides no
mechanical check.
"""

from __future__ import annotations

import inspect
from typing import Final

from ai_assistant.wire import envelope

#: The version ADR-0322 §6:2 moves to for this lane, read at the moment the lane landed,
#: and the one it moves from. The absolute figure has one home,
#: ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 108
_MOVED_FROM: Final = 107


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """§6:2: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_its_ground() -> None:
    """The entry names ADR-0322 §6:2 and its ground, and the one it follows stands."""
    entry = _entry_for(_MOVED_TO)

    assert "ADR-0322 §6:2" in entry
    assert "ActivationUnderstanding.answers" in entry
    assert f"#: {_MOVED_FROM}: " in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


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
