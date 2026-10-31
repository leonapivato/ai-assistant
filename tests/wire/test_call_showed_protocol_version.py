"""``PROTOCOL_VERSION`` moved once for what each call showed (ADR-0358 §11:7).

§11:7 has the change that adds what each call showed to ``RecordedCall`` advance the
constant on ADR-0124 §9's rule, in that change, since the processing record crosses the
wire inside episodes. A test holds that the number moved and that the move is accounted
for in the log a reviewer reads, as ``test_call_records_protocol_version.py`` does. The
cases below send a record through the codec's own projection and read it back, and hold
that an entry sent without the addition, as a peer at the earlier version sends it, still
validates (§11:6).
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from typing import Final

from ai_assistant.core.types import (
    CallOutcomeKind,
    CallShowed,
    ChannelContext,
    ChannelIdentity,
    DeliveryStatus,
    EpisodeProcessingRecord,
    EpisodicMemory,
    MemorySource,
    NewConversation,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    ProposedCall,
    Provenance,
    RecordedCall,
    RecordedChannelTrigger,
    RecordedDelivery,
    RecordedTextInput,
    ShownRecord,
    ShownRecordKind,
    ShownText,
    UnderstandingOmission,
    WholeTextReply,
)
from ai_assistant.testing.activation import ended_pass
from ai_assistant.testing.parties import OWNERS_WORDS
from ai_assistant.wire import envelope
from ai_assistant.wire.codec import encode_projection, project

#: The version ADR-0358 §11:7 moves to, read at the moment the lane landed, and the one
#: it moves from. The absolute figure has one home,
#: ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 124
_MOVED_FROM: Final = 123

_AT: Final = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
_CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="chat-1")


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """§11:7: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_its_ground() -> None:
    """The entry names ADR-0358 §11:7 and its ground, and the one it follows stands."""
    source = inspect.getsource(envelope)
    entry = source.split(f"#: {_MOVED_TO}: ")[-1].split("PROTOCOL_VERSION: Final")[0]
    flat = " ".join(line.removeprefix("#:").strip() for line in entry.splitlines())

    assert "ADR-0358 §11:7" in flat
    assert "showed" in flat
    assert f"#: {_MOVED_FROM}: " in source, (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def _episode() -> EpisodicMemory:
    planned = PlanningRound(
        id="round-1",
        recorded_at=_AT,
        calls=(
            ProposedCall(call_id="c0", name="search_memory", arguments={"query": "Riverside"}),
            ProposedCall(call_id="c1", name="text", arguments={"words": "Booked."}),
        ),
    )
    record = EpisodeProcessingRecord(
        activation_id="act-1",
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
        status=ProcessingStatus.COMPLETED,
        reason=ProcessingReason.RETURNED,
        understanding_omitted=UnderstandingOmission.NOT_REACHED,
        stages=ended_pass(_AT),
        rounds=(planned,),
        call_records=(
            RecordedCall(
                round="round-1",
                call_id="c0",
                capability="search_memory",
                effect=False,
                outcome=CallOutcomeKind.DONE,
                recorded_at=_AT,
                showed=CallShowed(
                    parts=(
                        ShownText(text="One memory matches:"),
                        ShownRecord(kind=ShownRecordKind.MEMORY, id="mem-riverside"),
                    ),
                    cut=True,
                ),
            ),
            RecordedCall(
                round="round-1",
                call_id="c1",
                capability="text",
                effect=True,
                outcome=CallOutcomeKind.DONE,
                delivered=RecordedDelivery(words="Booked.", went=_CHAT, status=DeliveryStatus.SENT),
                recorded_at=_AT,
            ),
        ),
    )
    return EpisodicMemory(
        id="activation:act-1",
        content="book Riverside for Friday",
        occurred_at=_AT,
        outcome="Booked.",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_AT),
        processing_record=record,
    )


def test_what_a_call_showed_round_trips_through_the_codec() -> None:
    """§11:2, §11:4: an entry keeps what its call showed, by reference, across the wire."""
    episode = _episode()
    sent: dict[str, object] = json.loads(encode_projection(project(episode)))
    processing = sent["processing_record"]
    assert isinstance(processing, dict)
    assert processing["schema_version"] == 12
    looked, texted = processing["call_records"]
    assert looked["showed"] == {
        "parts": [
            {"shown": "text", "text": "One memory matches:"},
            {"shown": "record", "kind": "memory", "id": "mem-riverside", "summary_version": None},
        ],
        "cut": True,
    }
    assert texted["showed"] is None
    assert EpisodicMemory.model_validate(sent) == episode


def test_an_entry_sent_without_the_addition_still_validates() -> None:
    """§11:6: an entry as a peer at the earlier version sends it, with no ``showed``,
    validates unchanged and keeps nothing of what its call showed."""
    sent: dict[str, object] = json.loads(encode_projection(project(_episode())))
    processing = sent["processing_record"]
    assert isinstance(processing, dict)
    for entry in processing["call_records"]:
        del entry["showed"]
    read = EpisodicMemory.model_validate(sent)
    assert read.processing_record is not None
    assert [entry.showed for entry in read.processing_record.call_records] == [None, None]
