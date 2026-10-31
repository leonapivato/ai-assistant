"""``PROTOCOL_VERSION`` moved once for who took a matter, on the episode record (ADR-0352 §6:7).

§6:7 has the change that adds ``EpisodeProcessingRecord.taken_over_by`` advance the
constant on ADR-0124 §9's rule, since the processing record crosses the wire inside
episodes. A test holds that the number moved and that the move is accounted for in the
log a reviewer reads, which is ``test_yes_path_protocol_version.py``'s reasoning:
ADR-0124 §9 makes the bump rule a review obligation and decides no mechanical check. The
cases below send a record through the codec's own projection and read it back, and hold
the member a peer at the earlier version would refuse as extra.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from typing import Final

from ai_assistant.core.types import (
    ChannelContext,
    ControllerRule,
    EpisodeProcessingRecord,
    EpisodicMemory,
    MemorySource,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    UnderstandingOmission,
    WholeTextReply,
)
from ai_assistant.testing.activation import ended_pass
from ai_assistant.testing.parties import (
    OWNERS_WORDS,
)
from ai_assistant.wire import envelope
from ai_assistant.wire.codec import encode_projection, project

#: The version ADR-0352 §6:7 moves to, read at the moment the lane landed, and the one
#: it moves from. The absolute figure has one home,
#: ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 120
_MOVED_FROM: Final = 119

_AT: Final = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """§6:7: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_its_ground() -> None:
    """The entry names ADR-0352 §6:7 and its ground, and the one it follows stands."""
    entry = _entry_for(_MOVED_TO)

    assert "ADR-0352 §6:7" in entry
    assert "taken_over_by" in entry
    assert f"#: {_MOVED_FROM}: " in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def _entry_for(version: int) -> str:
    """The version log's entry for one version, one line, comment prefixes removed."""
    source = inspect.getsource(envelope)
    entry = source.split(f"#: {version}: ")[-1].split("PROTOCOL_VERSION: Final")[0]
    stripped = (line.removeprefix("#:").strip() for line in entry.splitlines())
    return " ".join(part for part in stripped if part)


def _episode(taker: str | None) -> EpisodicMemory:
    record = EpisodeProcessingRecord(
        activation_id="act-absorbed",
        started_at=_AT,
        ended_at=_AT,
        trigger=RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="book Riverside for Friday"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            parties=OWNERS_WORDS,
        ),
        status=ProcessingStatus.INTERRUPTED,
        reason=ProcessingReason.STOPPED,
        understanding_omitted=UnderstandingOmission.NOT_REACHED,
        stages=ended_pass(_AT, ControllerRule.STOPPED),
        taken_over_by=taker,
    )
    return EpisodicMemory(
        id="activation:act-absorbed",
        content="book Riverside for Friday",
        occurred_at=_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_AT),
        processing_record=record,
    )


def _sent(episode: EpisodicMemory) -> dict[str, object]:
    sent: dict[str, object] = json.loads(encode_projection(project(episode)))
    return sent


def test_a_record_naming_its_taker_round_trips_through_the_codec() -> None:
    """§5:2: the activation that took the matter crosses the wire as recorded."""
    episode = _episode("act-absorber")
    sent = _sent(episode)
    processing = sent["processing_record"]
    assert isinstance(processing, dict)
    assert processing["taken_over_by"] == "act-absorber"
    assert EpisodicMemory.model_validate(sent) == episode


def test_the_member_is_sent_when_nobody_took_the_matter() -> None:
    """ADR-0124 §9:2: every record carries the member, so a peer at 119 refuses it."""
    sent = _sent(_episode(None))
    processing = sent["processing_record"]
    assert isinstance(processing, dict)
    assert processing["schema_version"] == 12
    assert "taken_over_by" in processing
    assert processing["taken_over_by"] is None
    assert EpisodicMemory.model_validate(sent) == _episode(None)
