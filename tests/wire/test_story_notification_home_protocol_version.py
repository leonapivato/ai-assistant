"""``PROTOCOL_VERSION`` moved for the home on stories and held notifications (ADR-0124 §9:2).

ADR-0386 §2:1 and §3:1 put ADR-0383 §2's home on ``StoryHeader`` and ``HeldNotification``,
and both cross the wire: a header on every story read the engine answers, a held
notification on every page ``notifications`` answers. ADR-0386 §1:3 leaves the version to
ADR-0124 §9:2, which advances it in the change that makes a frame one peer sends invalid
for the other. A test holds that the number moved and that the move is accounted for in
the log a reviewer reads, as the earlier moves' tests do; the cases below send each type
through the codec's own projection and read it back, and hold that one sent without a
home, as a peer at the earlier version sends it, is refused.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from pydantic import BaseModel, ValidationError

from ai_assistant.core.types import (
    DataTier,
    HeldNotification,
    NotificationCandidate,
    NotificationCondition,
    NotificationDispositionKind,
    RecordHome,
    StoryHeader,
)
from ai_assistant.wire import envelope
from ai_assistant.wire.codec import encode_projection, project

#: The version this lane moves to, read at the moment it landed, and the one it moves
#: from. The absolute figure has one home, ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 138
_MOVED_FROM: Final = 137

_AT: Final = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """ADR-0124 §9:2: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_these_decisions_and_their_ground() -> None:
    """The entry names ADR-0386, the home and both types, and the one it follows stands."""
    source = inspect.getsource(envelope)
    entry = source.split(f"#: {_MOVED_TO}: ")[-1].split("PROTOCOL_VERSION: Final")[0]
    flat = " ".join(line.removeprefix("#:").strip() for line in entry.splitlines())

    assert "ADR-0386" in flat
    assert "home" in flat
    assert "StoryHeader" in flat
    assert "HeldNotification" in flat
    assert f"#: {_MOVED_FROM}: " in source, (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def _header() -> StoryHeader:
    return StoryHeader(
        story_id="story:1", created_at=_AT, merged_into=None, home=RecordHome.owners()
    )


def _held() -> HeldNotification:
    return HeldNotification(
        id="note-1",
        home=RecordHome.shared(),
        candidate=NotificationCandidate(
            candidate_key="k1",
            producer="upcoming",
            notification_class="calendar",
            summary="The dentist is on Thursday.",
            noticed_at=_AT,
            confidence=0.8,
            sensitivity=DataTier.PERSONAL,
        ),
        kind=NotificationDispositionKind.HOLD,
        reason=NotificationCondition.REACH_INTERRUPT,
        failed=(NotificationCondition.REACH_INTERRUPT,),
        ruled_at=_AT,
        admitted_at=_AT,
        retention=timedelta(days=7),
    )


def _records() -> tuple[BaseModel, ...]:
    return _header(), _held()


@pytest.mark.parametrize("record", _records(), ids=["story-header", "held-notification"])
def test_a_records_home_round_trips_through_the_codec(record: BaseModel) -> None:
    """ADR-0383 §2:2: the kind and the identifier both cross, and read back whole."""
    sent: dict[str, object] = json.loads(encode_projection(project(record)))

    assert sent["home"] == record.model_dump(mode="json")["home"]
    assert type(record).model_validate(sent) == record


@pytest.mark.parametrize("record", _records(), ids=["story-header", "held-notification"])
def test_a_record_sent_without_a_home_is_refused(record: BaseModel) -> None:
    """ADR-0383 §5:4: a peer at the earlier version sends no home, which this one refuses."""
    sent: dict[str, object] = json.loads(encode_projection(project(record)))
    del sent["home"]

    with pytest.raises(ValidationError, match="home"):
        type(record).model_validate(sent)
