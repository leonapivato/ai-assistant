"""``PROTOCOL_VERSION`` moved once for an input's parties, on the episode record (ADR-0351 §10:3).

§10:3 has each lane that changes a shape the wire carries advance the constant on
ADR-0124 §9's rule, in that change. P1 changes the processing record ``EpisodicMemory``
carries across the wire: its trigger trades ``origin`` for ``parties``, its messages gain
``party``, and its understanding versions and joined inputs gain ``relayed``. A test holds
that the number moved and that the move is accounted for in the log a reviewer reads,
which is ``test_taken_over_by_protocol_version.py``'s reasoning: ADR-0124 §9 makes the bump
rule a review obligation and decides no mechanical check. The cases below send a record
through the codec's own projection and read it back, and hold the members a peer at the
earlier version would refuse.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from typing import Final

from ai_assistant.core.channel_validation import declared_input
from ai_assistant.core.types import (
    ActivationUnderstanding,
    ChannelContext,
    ChannelIdentity,
    ClaimedAuthor,
    EpisodeProcessingRecord,
    EpisodicMemory,
    JoinedInput,
    MemorySource,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedInputMessage,
    RecordedTextInput,
    UnderstandingProducer,
    WholeTextReply,
)
from ai_assistant.testing.activation import ended_pass
from ai_assistant.wire import envelope
from ai_assistant.wire.codec import encode_projection, project

#: The version ADR-0351 §10:3 moves to, read at the moment the lane landed, and the one
#: it moves from. The absolute figure has one home,
#: ``tests/core/test_engine_surface_closure.py``.
_MOVED_TO: Final = 121
_MOVED_FROM: Final = 120

_AT: Final = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="conn-1/42")


def test_the_protocol_version_moved_past_the_figure_this_lane_reached() -> None:
    """§10:3: the move, asserted as a move and not as a state."""
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_its_ground() -> None:
    """The entry names ADR-0351 §10:3 and its ground, and the one it follows stands."""
    entry = _entry_for(_MOVED_TO)

    assert "ADR-0351 §10:3" in entry
    assert "parties" in entry
    assert "relayed" in entry
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
    parties, messages = declared_input(
        _LINE,
        (
            RecordedInputMessage(text="Is this right?", sent_at=_AT, position=1),
            RecordedInputMessage(
                text="Ana moved to Porto.",
                sent_at=_AT,
                position=2,
                forwarded_from=ClaimedAuthor(name="Sam", account_id=77),
            ),
        ),
    )
    record = EpisodeProcessingRecord(
        activation_id="act-line",
        started_at=_AT,
        ended_at=_AT,
        trigger=RecordedChannelTrigger(
            target=_LINE,
            channel=_LINE,
            payload=RecordedTextInput(text="Is this right?\n\nAna moved to Porto."),
            context=ChannelContext(),
            reply=WholeTextReply(),
            parties=parties,
            messages=messages,
        ),
        status=ProcessingStatus.COMPLETED,
        reason=ProcessingReason.RETURNED,
        understanding=(
            ActivationUnderstanding(
                version=1,
                recorded_at=_AT,
                producer=UnderstandingProducer.INTERPRETATION,
                meaning="The user asks whether Ana moved to Porto.",
                relayed=True,
            ),
        ),
        stages=ended_pass(_AT),
        joined=(JoinedInput(joined_at=_AT, channel=_LINE, messages=messages[:1], relayed=True),),
    )
    return EpisodicMemory(
        id="activation:act-line",
        content="Is this right?",
        occurred_at=_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_AT),
        processing_record=record,
    )


def test_a_record_carrying_its_parties_round_trips_through_the_codec() -> None:
    """§2:1, §2:6, §5:10, §5:14: the parties, each party and each mark cross as recorded."""
    episode = _episode()
    sent: dict[str, object] = json.loads(encode_projection(project(episode)))

    processing = sent["processing_record"]
    assert isinstance(processing, dict)
    trigger = processing["trigger"]
    assert isinstance(trigger, dict)
    assert "origin" not in trigger, "a peer at 120 refuses the trigger for want of it"
    assert [one["kind"] for one in trigger["parties"]] == ["person", "outside_source"]
    assert [one["party"]["kind"] for one in trigger["messages"]] == ["person", "outside_source"]
    assert processing["understanding"][0]["relayed"] is True
    assert processing["joined"][0]["relayed"] is True
    assert EpisodicMemory.model_validate(sent) == episode
