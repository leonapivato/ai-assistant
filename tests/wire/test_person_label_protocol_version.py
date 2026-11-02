"""``PROTOCOL_VERSION`` moved once for the ``P`` label (ADR-0364 §14:3).

§14:3 has lane B advance the constant where a type ADR-0364 changes crosses the wire:
``LabelKind`` gains ``person`` (§4:1), carried on the labels the processing record holds.
A test holds that the number moved and that the move is accounted for in the log a
reviewer reads, as ``test_person_act_request_protocol_version.py`` does, and that a ``P``
label is a planning label of its kind.
"""

from __future__ import annotations

import inspect
from typing import Final

import pytest

from ai_assistant.core.types import LabelKind, PlanningLabel, label_prefix
from ai_assistant.wire import envelope

#: The version ADR-0364 §14:3 moves to, read at the moment the lane landed, and the one it
#: moves from. The absolute figure has one home,
#: ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 128
_MOVED_FROM: Final = 127


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """§14:3: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_its_ground() -> None:
    """The entry names ADR-0364 §14:3 and its ground, and the one it follows stands."""
    source = inspect.getsource(envelope)
    entry = source.split(f"#: {_MOVED_TO}: ")[-1].split("PROTOCOL_VERSION: Final")[0]
    flat = " ".join(line.removeprefix("#:").strip() for line in entry.splitlines())

    assert "ADR-0364 §14:3" in flat
    assert "LabelKind" in flat
    assert "person" in flat
    assert f"#: {_MOVED_FROM}: " in source, (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def test_a_person_label_is_a_p_label() -> None:
    """§4:1: ``P1`` names a person, and no other kind's label takes ``P``."""
    assert label_prefix(LabelKind.PERSON) == "P"
    label = PlanningLabel(label="P1", kind=LabelKind.PERSON, id="person:owner")
    assert label.label == "P1"
    with pytest.raises(ValueError, match="prefix"):
        PlanningLabel(label="P1", kind=LabelKind.PLACE, id="conversation:c-1")
