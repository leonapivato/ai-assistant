"""``PROTOCOL_VERSION`` moved once for a record's home (ADR-0383 §13, ADR-0124 §9:2).

ADR-0383 §13 has the version advance once for its milestone, in the lane that adds the
home to models the wire carries: ``EpisodicMemory`` and ``Memory`` cross it inside every
``MemoryRecord`` a frame carries. A test holds that the number moved and that the move is
accounted for in the log a reviewer reads, as the earlier moves' tests do. The cases
below send a record through the codec's own projection and read it back, and hold that
one sent without a home, as a peer at the earlier version sends it, is refused.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.types import (
    EpisodicMemory,
    MemoryRecord,
    MemorySource,
    Provenance,
    RecordHome,
)
from ai_assistant.testing.memories import memory
from ai_assistant.wire import envelope
from ai_assistant.wire.codec import encode_projection, project

#: The version ADR-0383 §13 moves to, read at the moment the lane landed, and the one it
#: moves from. The absolute figure has one home,
#: ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 137
_MOVED_FROM: Final = 136

_AT: Final = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)

_RECORD: Final[TypeAdapter[MemoryRecord]] = TypeAdapter(MemoryRecord)


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """§13: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_its_ground() -> None:
    """The entry names ADR-0383 and the home, and the one it follows stands."""
    source = inspect.getsource(envelope)
    entry = source.split(f"#: {_MOVED_TO}: ")[-1].split("PROTOCOL_VERSION: Final")[0]
    flat = " ".join(line.removeprefix("#:").strip() for line in entry.splitlines())

    assert "ADR-0383" in flat
    assert "home" in flat
    assert f"#: {_MOVED_FROM}: " in source, (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def _records() -> tuple[MemoryRecord, ...]:
    episode = EpisodicMemory(
        id="e1",
        home=RecordHome.shared(),
        content="the house wifi was reset",
        occurred_at=_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_AT),
    )
    return episode, memory("m1", "The user is vegetarian.")


@pytest.mark.parametrize("record", _records(), ids=["episode", "memory"])
def test_a_records_home_round_trips_through_the_codec(record: MemoryRecord) -> None:
    """ADR-0383 §2:2: the kind and the identifier both cross, and read back whole."""
    sent: dict[str, object] = json.loads(encode_projection(project(record)))

    assert sent["home"] == record.home.model_dump(mode="json")
    assert _RECORD.validate_python(sent) == record


@pytest.mark.parametrize("record", _records(), ids=["episode", "memory"])
def test_a_record_sent_without_a_home_is_refused(record: MemoryRecord) -> None:
    """§5:4: a peer at the earlier version sends no home, which this version refuses."""
    sent: dict[str, object] = json.loads(encode_projection(project(record)))
    del sent["home"]

    with pytest.raises(ValidationError, match="home"):
        _RECORD.validate_python(sent)
