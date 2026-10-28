"""ADR-0332 §3:16, §3:17 and §7:1, §7:2: a joined input, as the episode records it.

The record's ``joined`` field, the one invariant the record holds of it, and the appends
``episode_extends`` admits for it (ADR-0286 §3:3, as ADR-0332 §10 adds to it).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.episode_encoding import episode_extends
from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    ControllerRule,
    ControllerStage,
    EpisodeProcessingRecord,
    EpisodicMemory,
    JoinedInput,
    MemorySource,
    NewConversation,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedInputMessage,
    RecordedTextInput,
    StageEntry,
    StageOutcome,
    UnderstandingOmission,
    WholeTextReply,
)
from ai_assistant.testing.parties import (
    OWNERS_WORDS,
)

_NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
_LATER = _NOW + timedelta(seconds=30)
_OWNER_ONLY = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_NOW)
_CHAT = ChannelIdentity(channel_type="conversation", instance_id="chat-1")
_LINE = ChannelIdentity(channel_type="telegram", instance_id="line")


def _joined(
    text: str = "actually, Saturday",
    *,
    channel: ChannelIdentity = _CHAT,
    taken_over_from: str | None = None,
    at: datetime = _NOW,
) -> JoinedInput:
    return JoinedInput(
        joined_at=at,
        channel=channel,
        messages=(RecordedInputMessage(text=text, sent_at=at, position=4),),
        taken_over_from=taken_over_from,
    )


def _open(**fields: object) -> EpisodeProcessingRecord:
    values: dict[str, object] = {
        "activation_id": "activation",
        "started_at": _NOW,
        "trigger": RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="book Riverside for Friday"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            parties=OWNERS_WORDS,
        ),
    }
    values.update(fields)
    return EpisodeProcessingRecord.model_validate(values)


def _frozen(record: EpisodeProcessingRecord) -> EpisodeProcessingRecord:
    end = StageEntry(
        stage=ControllerStage.END,
        due=ControllerRule.NOTHING_DUE,
        started_at=_LATER,
        ended_at=_LATER,
        outcome=StageOutcome.DONE,
    )
    return EpisodeProcessingRecord.model_validate(
        {
            **dict(record),
            "status": ProcessingStatus.COMPLETED,
            "reason": ProcessingReason.RETURNED,
            "ended_at": _LATER,
            "stages": (*record.stages, end),
            "understanding_omitted": UnderstandingOmission.NOT_REACHED,
        }
    )


def _extends(before: EpisodeProcessingRecord, after: EpisodeProcessingRecord) -> bool:
    def episode(record: EpisodeProcessingRecord) -> EpisodicMemory:
        return EpisodicMemory(
            id="activation:activation",
            content="",
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
            occurred_at=_NOW,
            processing_record=record,
            placement=_OWNER_ONLY,
        )

    return episode_extends(episode(before), episode(after))


# --- the joined input ---------------------------------------------------------------------


def test_a_joined_input_carries_exactly_the_decisions_fields() -> None:
    """§7:1: when it joined, the place, its messages, and the activation taken over.

    ADR-0351 §5:14 adds ``relayed``, the relay mark an absorption or a take records.
    """
    assert set(JoinedInput.model_fields) == {
        "joined_at",
        "channel",
        "messages",
        "taken_over_from",
        "relayed",
    }
    assert _joined().taken_over_from is None
    assert not _joined().relayed


def test_a_joined_input_carries_at_least_one_message() -> None:
    """§7:1: ``messages`` is non-empty."""
    with pytest.raises(ValidationError):
        JoinedInput(joined_at=_NOW, channel=_CHAT, messages=())


def test_a_joined_input_is_frozen_and_closed() -> None:
    """§7:1: frozen with ``extra="forbid"``."""
    with pytest.raises(ValidationError):
        JoinedInput.model_validate({**_joined().model_dump(), "author": "someone"})
    with pytest.raises(ValidationError):
        _joined().joined_at = _LATER


def test_a_takeover_names_an_activation() -> None:
    """§3:17: a join a takeover brought names the activation it was taken from."""
    taken = _joined(channel=_LINE, taken_over_from="act-on-the-line")
    assert taken.taken_over_from == "act-on-the-line"
    with pytest.raises(ValidationError):
        _joined(taken_over_from="  ")


# --- the record ---------------------------------------------------------------------------


def test_the_record_defaults_to_no_joined_input() -> None:
    """§7:2: a record written before the field validates unchanged."""
    record = _open()
    assert record.joined == ()
    assert record.schema_version == 11
    assert "joined" not in record.model_dump(exclude_defaults=True)


def test_a_record_with_joined_input_round_trips() -> None:
    record = _open(
        joined=(_joined(), _joined("and four people", channel=_LINE, taken_over_from="act-2"))
    )
    assert EpisodeProcessingRecord.model_validate_json(record.model_dump_json()) == record


def test_no_takeover_names_the_activation_itself() -> None:
    """§4:6: a takeover stops another activation."""
    with pytest.raises(ValidationError, match="its own activation"):
        _open(joined=(_joined(taken_over_from="activation"),))


def test_an_absorbed_activations_inputs_stand_side_by_side() -> None:
    """ADR-0349 §7:7, §10:7: an absorption appends every input the other holds, each
    naming it, in one step, so two inputs naming one activation stand side by side."""
    record = _open(
        joined=(
            _joined(taken_over_from="act-2"),
            _joined("and four people", channel=_LINE, taken_over_from="act-2"),
        )
    )
    assert [one.taken_over_from for one in record.joined] == ["act-2", "act-2"]


def test_no_activation_is_taken_over_twice() -> None:
    """ADR-0349 §7:7, §7:21: an absorbed or handed-over activation is stopped, so its
    inputs come in one step: two runs naming one activation are refused."""
    with pytest.raises(ValidationError, match="in one step, at most once"):
        _open(
            joined=(
                _joined(taken_over_from="act-2"),
                _joined("and four people"),
                _joined(taken_over_from="act-2"),
            )
        )
    with pytest.raises(ValidationError, match="in one step, at most once"):
        _open(
            joined=(
                _joined(taken_over_from="act-2"),
                _joined(taken_over_from="act-3"),
                _joined(taken_over_from="act-2"),
            )
        )


def test_no_run_names_the_activation_itself() -> None:
    """ADR-0332 §4:6 stands: no input is taken from the activation that holds it, even
    beside inputs taken from another."""
    with pytest.raises(ValidationError, match="its own activation"):
        _open(joined=(_joined(taken_over_from="act-2"), _joined(taken_over_from="activation")))


def test_two_joins_on_the_place_need_no_takeover() -> None:
    record = _open(joined=(_joined(), _joined("and four people")))
    assert len(record.joined) == 2


# --- episode_extends ----------------------------------------------------------------------


def test_a_joined_input_appended_extends() -> None:
    """ADR-0286 §3:3, as §10 adds to it: a revision may extend ``joined``."""
    assert _extends(_open(), _open(joined=(_joined(),)))
    stored = _open(joined=(_joined(),))
    assert _extends(stored, _open(joined=(_joined(), _joined("and four people"))))


def test_the_freezing_revision_keeps_the_joined_inputs() -> None:
    stored = _open(joined=(_joined(),))
    assert _extends(stored, _frozen(stored))


def test_a_joined_input_is_never_edited() -> None:
    stored = _open(joined=(_joined(),))
    assert not _extends(stored, _open(joined=(_joined("something else"),)))


def test_a_joined_input_is_never_dropped() -> None:
    stored = _open(joined=(_joined(), _joined("and four people")))
    assert not _extends(stored, _open(joined=(_joined(),)))


def test_a_joined_input_is_never_inserted_ahead_of_one_recorded() -> None:
    stored = _open(joined=(_joined("and four people"),))
    assert not _extends(stored, _open(joined=(_joined(), _joined("and four people"))))
