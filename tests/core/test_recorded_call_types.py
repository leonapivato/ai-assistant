"""ADR-0356 §8, §13: each call's entry on the episode, the projection's calls and joins,
and a message call's part.

The types are ``core``'s, so these hold their validators, the record's extension rule and
the projection on values alone: ``RecordedCall``, ``RecordedDelivery``, the record's
``call_records``, ``episode_extends``' new arm, ``ProjectedRound.position``,
``ProjectedCall``, ``ProjectedJoin``, ``MessageCallPart`` and ``statement_citations``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

import pytest
from pydantic import ValidationError
from test_planning_round_types import _NOW, _call, _episode, _frozen, _open, _round

from ai_assistant.core.episode_encoding import episode_extends, project_episode
from ai_assistant.core.types import (
    CallOutcomeKind,
    ChannelIdentity,
    DeliveryStatus,
    EpisodeProcessingRecord,
    EpisodicMemory,
    JoinedInput,
    MemoryMark,
    MemorySupport,
    MessageCallPart,
    ProjectedText,
    RecordedCall,
    RecordedDelivery,
    RecordedInputMessage,
    StatementCitation,
    SupportDirection,
    SupportOrigin,
    statement_citations,
)
from ai_assistant.testing.memories import memory, message_support
from ai_assistant.testing.parties import OWNERS_WORDS

_CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="chat-1")


def _delivered(words: str = "It's booked for Thursday.") -> RecordedDelivery:
    return RecordedDelivery(words=words, went=_CHAT, status=DeliveryStatus.SENT)


def _entry(round_id: str = "r1", call_id: str = "c1", **fields: object) -> RecordedCall:
    values: dict[str, object] = {
        "round": round_id,
        "call_id": call_id,
        "capability": "web_search",
        "effect": False,
        "outcome": CallOutcomeKind.DONE,
        "recorded_at": _NOW,
    }
    values.update(fields)
    return RecordedCall.model_validate(values)


# --- the entry (§8:3-§8:4, §13) -------------------------------------------------------


def test_an_entry_carries_a_reason_only_with_its_outcome() -> None:
    _entry(outcome=None)
    _entry(outcome=CallOutcomeKind.REFUSED, reason="names nothing you were shown")
    with pytest.raises(ValidationError, match="reason only with its outcome"):
        _entry(outcome=None, reason="still running")


@pytest.mark.parametrize(
    "outcome", [CallOutcomeKind.DONE, CallOutcomeKind.NOT_DONE, CallOutcomeKind.UNKNOWN]
)
def test_a_message_call_sent_or_attempted_holds_what_it_sent(outcome: CallOutcomeKind) -> None:
    entry = _entry(capability="text", effect=True, outcome=outcome, delivered=_delivered())
    assert entry.delivered is not None
    assert (entry.delivered.words, entry.delivered.went) == ("It's booked for Thursday.", _CHAT)


@pytest.mark.parametrize("outcome", [None, CallOutcomeKind.REFUSED, CallOutcomeKind.NEEDS_YOU])
def test_a_call_that_sent_nothing_holds_no_delivery(outcome: CallOutcomeKind | None) -> None:
    with pytest.raises(ValidationError, match="holds a delivery"):
        _entry(capability="text", effect=True, outcome=outcome, delivered=_delivered())


def test_the_outcome_kinds_are_the_ones_planning_was_shown() -> None:
    """§13: moved into core, its members unchanged."""
    assert [one.value for one in CallOutcomeKind] == [
        "done",
        "not_done",
        "unknown",
        "needs_you",
        "refused",
    ]
    assert [one.value for one in DeliveryStatus] == [
        "sent",
        "delivered",
        "read",
        "failed",
        "unknown",
    ]


# --- the record's entries (§8:2, §13) -------------------------------------------------


def _with_calls() -> EpisodeProcessingRecord:
    return _open(
        rounds=(
            _round("r1", calls=(_call("c1"), _call("c2", "text"))),
            _round("r2", follows="r1", calls=(_call("c3"),)),
        )
    )


def test_the_record_holds_an_entry_for_each_call_its_rounds_proposed() -> None:
    record = _with_calls().model_copy(
        update={"call_records": (_entry("r1", "c1"), _entry("r2", "c3"))}
    )
    EpisodeProcessingRecord.model_validate(record.model_dump())
    assert EpisodeProcessingRecord.model_validate(_with_calls().model_dump()).call_records == ()


@pytest.mark.parametrize(
    ("round_id", "call_id"),
    [("r9", "c1"), ("r1", "c3"), ("r2", "c1")],
    ids=["a round it does not hold", "a call that round did not propose", "the wrong round"],
)
def test_an_entry_naming_a_call_no_round_proposed_is_refused(round_id: str, call_id: str) -> None:
    data = _with_calls().model_dump()
    data["call_records"] = [_entry(round_id, call_id).model_dump()]
    with pytest.raises(ValidationError, match="a call it proposed"):
        EpisodeProcessingRecord.model_validate(data)


def test_two_entries_for_one_call_are_refused() -> None:
    """§14:9: two entries for one call are refused by the type."""
    data = _with_calls().model_dump()
    data["call_records"] = [
        _entry("r1", "c1").model_dump(),
        _entry("r1", "c1", outcome=CallOutcomeKind.UNKNOWN).model_dump(),
    ]
    with pytest.raises(ValidationError, match="one entry for each call"):
        EpisodeProcessingRecord.model_validate(data)


def _episode_of(record: EpisodeProcessingRecord) -> EpisodicMemory:
    return _episode(record)


def test_an_open_episode_is_extended_by_entries_appended_at_the_end() -> None:
    """§13: ``episode_extends`` admits entries appended, every earlier one unchanged."""
    first = _with_calls().model_copy(update={"call_records": (_entry("r1", "c1"),)})
    appended = first.model_copy(
        update={"call_records": (_entry("r1", "c1"), _entry("r2", "c3", outcome=None))}
    )
    assert episode_extends(_episode_of(first), _episode_of(appended))
    changed = first.model_copy(
        update={
            "call_records": (
                _entry("r1", "c1", outcome=CallOutcomeKind.UNKNOWN),
                _entry("r2", "c3"),
            )
        }
    )
    assert not episode_extends(_episode_of(first), _episode_of(changed))
    dropped = first.model_copy(update={"call_records": ()})
    assert not episode_extends(_episode_of(first), _episode_of(dropped))


# --- the projection (§13) --------------------------------------------------------------


def _joined(at_seconds: int, *, relayed: bool = False) -> JoinedInput:
    return JoinedInput(
        joined_at=_NOW + timedelta(seconds=at_seconds),
        channel=_CHAT,
        messages=(
            RecordedInputMessage(
                text="and the vet too", sent_at=_NOW, position=4, party=OWNERS_WORDS[0]
            ),
        ),
        relayed=relayed,
    )


def _projected_record() -> EpisodeProcessingRecord:
    """A call-only round, then a round with notes, then a round after an input joined."""
    rounds = (
        _round("r1", calls=(_call("c1"),), recorded_at=_NOW),
        _round("r2", follows="r1", notes="looked it up", recorded_at=_NOW + timedelta(seconds=2)),
        _round("r3", follows="r2", text="Done.", recorded_at=_NOW + timedelta(seconds=9)),
    )
    return _frozen(
        _open(
            rounds=rounds,
            joined=(_joined(5), _joined(6, relayed=True)),
            call_records=(_entry("r1", "c1", marked=True),),
        )
    )


def test_the_projection_carries_calls_and_joins_where_owner_records_are_admitted() -> None:
    projection = project_episode(
        _episode(_projected_record(), outcome="Done."), excerpt_chars=8, owner_records=True
    )
    (call,) = projection.calls
    assert (call.position, call.capability, call.effect, call.marked) == (
        0,
        "web_search",
        False,
        True,
    )
    assert call.outcome is CallOutcomeKind.DONE
    assert call.arguments == ProjectedText(text='{"query"', full_chars=14)
    own, relayed = projection.joined
    # Taken in after the second round and before the third: position 2.
    assert (own.position, own.channel, own.parties) == (2, _CHAT, OWNERS_WORDS)
    assert own.input == ProjectedText(text="and the ", full_chars=15)
    # Withheld as the input is: relayed, it is no longer the person's own words.
    assert relayed.relayed
    assert relayed.input is None


def test_the_projection_carries_no_call_and_no_join_otherwise() -> None:
    projection = project_episode(_episode(_projected_record(), outcome="Done."), excerpt_chars=8)
    assert projection.calls == ()
    assert projection.joined == ()


def test_a_call_only_round_keeps_its_place_before_a_round_with_notes() -> None:
    """§14:9: a short view of an episode whose call-only round precedes a round with notes
    shows the call first: the call-only round is not projected, and its position still
    orders its call before the next round's notes."""
    projection = project_episode(
        _episode(_projected_record(), outcome="Done."), excerpt_chars=50, owner_records=True
    )
    assert [one.position for one in projection.rounds] == [1, 2]
    (call,) = projection.calls
    assert call.position < projection.rounds[0].position


# --- a message call's part (§13:2-§13:3) ---------------------------------------------


def test_a_message_call_part_takes_a_round_messages_origin() -> None:
    part = MessageCallPart(episode="activation:activation", round="r1", call_id="c2")
    for origin in (SupportOrigin.ASSISTANT_MESSAGE, SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE):
        MemorySupport(
            points_at=part,
            origin=origin,
            direction=SupportDirection.FOR,
            backs_as_worded=True,
            when=_NOW,
            added_at=_NOW,
            added_by=message_support().added_by,
        )
    with pytest.raises(ValidationError):
        MemorySupport(
            points_at=part,
            origin=SupportOrigin.USER_MESSAGE,
            direction=SupportDirection.FOR,
            backs_as_worded=True,
            when=_NOW,
            added_at=_NOW,
            added_by=message_support().added_by,
        )


def test_two_messages_of_one_round_are_cited_apart() -> None:
    """§13:3: a statement resting on two message calls of one round cites each by its call."""
    supports = [
        message_support().model_copy(
            update={
                "points_at": MessageCallPart(episode="e1", round="r1", call_id=call_id),
            }
        )
        for call_id in ("c1", "c2")
    ]
    said = memory(
        "said", "I said it was booked.", *supports, marks=(MemoryMark.ASSISTANT_STATEMENT,)
    )
    assert statement_citations(said) == (
        StatementCitation(episode="e1", round="r1", when=supports[0].when, call_id="c1"),
        StatementCitation(episode="e1", round="r1", when=supports[1].when, call_id="c2"),
    )
    older = memory(
        "older", "I said so.", message_support("e0"), marks=(MemoryMark.ASSISTANT_STATEMENT,)
    )
    (cited,) = statement_citations(older)
    assert cited.call_id is None
