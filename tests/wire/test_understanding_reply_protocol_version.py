"""``PROTOCOL_VERSION`` moved once for understanding's new record (ADR-0353 §15:2).

§15:2 has each lane that changes a shape the wire carries advance the constant on
ADR-0124 §9's rule, in that change. U1 changes the understanding versions the processing
record ``EpisodicMemory`` carries across the wire: each loses its ground, references,
relationships, unresolved matters and answer pointers and gains ``unclear``; a referent
may be ``running``; and a recall record may name the cue ``understood_gap``. A test holds
that the number moved and that the move is accounted for in the log a reviewer reads,
which is ``test_taken_over_by_protocol_version.py``'s reasoning: ADR-0124 §9 makes the
bump rule a review obligation and decides no mechanical check. The case below sends a
record through the codec's own projection and reads it back, and holds the members a
peer at the earlier version would refuse.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ActivationRecall,
    ActivationUnderstanding,
    BeliefBand,
    ChannelContext,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputOrigin,
    MemoryKind,
    MemorySource,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    UnclearPoint,
    UnderstandingProducer,
    UnderstandingReferent,
    WholeTextReply,
)
from ai_assistant.testing.activation import ended_pass
from ai_assistant.testing.parties import parties_for
from ai_assistant.wire import envelope
from ai_assistant.wire.codec import encode_projection, project

#: The version ADR-0353 §15:2 moves to, read at the moment the lane landed, and the one
#: it moves from. The absolute figure has one home,
#: ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 122
_MOVED_FROM: Final = 121

_AT: Final = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

#: ADR-0353 §9:5's retired fields, none of which a version at 122 carries.
_RETIRED: Final = ("meaning_ground", "references", "relationships", "unresolved", "answers")


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """§15:2: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_its_ground() -> None:
    """The entry names ADR-0353 §15:2 and its ground, and the one it follows stands."""
    entry = _entry_for(_MOVED_TO)

    assert "ADR-0353 §15:2" in entry
    assert "unclear" in entry
    assert "running" in entry
    assert "understood_gap" in entry
    assert f"#: {_MOVED_FROM}: " in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def _entry_for(version: int) -> str:
    """The version log's entry for one version, one line, comment prefixes removed."""
    source = inspect.getsource(envelope)
    entry = source.split(f"#: {version}: ")[-1].split("PROTOCOL_VERSION: Final")[0]
    stripped = (line.removeprefix("#:").strip() for line in entry.splitlines())
    return " ".join(part for part in stripped if part)


def _episode() -> EpisodicMemory:
    running = UnderstandingReferent(
        kind="running",
        id="activation:act-booking",
        source="conversation:chat-1",
        excerpt="book a table for 4 on Friday",
    )
    item = RecalledItem(
        kind=MemoryKind.MEMORY,
        id="mem-1",
        excerpt="Maren likes Luigi's.",
        provenance=RecallProvenance.USER,
        standing=BeliefBand.ASSERTED,
        rests_on_recorded_external_content=False,
        found_by=(RecallCue.UNDERSTOOD_GAP,),
    )
    record = EpisodeProcessingRecord(
        activation_id="act-u1",
        started_at=_AT,
        ended_at=_AT,
        trigger=RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="make it Saturday"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            parties=parties_for(InputOrigin.USER),
        ),
        status=ProcessingStatus.COMPLETED,
        reason=ProcessingReason.RETURNED,
        understanding=(
            ActivationUnderstanding(
                version=1,
                recorded_at=_AT,
                producer=UnderstandingProducer.INTERPRETATION,
                meaning="Maren moves the running booking to Saturday.",
                meaning_referents=(running,),
                unclear=(UnclearPoint(gap="which time", readings=("eight", "nine")),),
                continues=("act-booking",),
            ),
        ),
        stages=ended_pass(_AT),
        recall_second_run=ActivationRecall(
            outcome=RecallOutcome.FOUND,
            cues=(RecallCue.UNDERSTOOD_MEANING, RecallCue.UNDERSTOOD_GAP),
            items=(item,),
        ),
    )
    return EpisodicMemory(
        id="activation:act-u1",
        content="make it Saturday",
        occurred_at=_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_AT),
        processing_record=record,
    )


def test_a_record_in_the_new_shape_round_trips_through_the_codec() -> None:
    """§9:3-§9:5, §10:1, §14:4: the unclear points, the running referent and the gap cue
    cross as recorded, and no retired field crosses."""
    episode = _episode()
    sent: dict[str, object] = json.loads(encode_projection(project(episode)))

    processing = sent["processing_record"]
    assert isinstance(processing, dict)
    (version,) = processing["understanding"]
    assert not set(_RETIRED) & set(version), "a peer at 121 refuses the version for want of it"
    assert version["unclear"] == [{"gap": "which time", "readings": ["eight", "nine"]}]
    assert version["meaning_referents"][0]["kind"] == "running"
    assert processing["recall_second_run"]["cues"] == ["understood_meaning", "understood_gap"]
    assert EpisodicMemory.model_validate(sent) == episode


@pytest.mark.parametrize("retired", _RETIRED)
def test_a_version_a_peer_at_121_sends_with_a_retired_field_is_refused(retired: str) -> None:
    """ADR-0124 §9:2: a hub at 122 refuses each retired field as extra."""
    sent: dict[str, object] = json.loads(encode_projection(project(_episode())))
    processing = sent["processing_record"]
    assert isinstance(processing, dict)
    processing["understanding"][0][retired] = "stated" if retired == "meaning_ground" else []

    with pytest.raises(ValidationError):
        EpisodicMemory.model_validate(sent)
