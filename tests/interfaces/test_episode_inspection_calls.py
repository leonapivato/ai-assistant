"""ADR-0356 §14:4, §14:9: episode inspection shows each round and each call's entry.

The human detail renders, after its other sections, planning's rounds as the record holds
them, a round recorded before the decision with the message its text wrote, and each
call's entry: its capability, whether it declared an effect, its outcome and reason, and
what a message call sent, where and how (§8:2-§8:4).
"""

from __future__ import annotations

from io import StringIO

from rich.console import Console
from test_cli_episodes import _AT, _open_record, _record, _staged

from ai_assistant.core.types import (
    CallOutcomeKind,
    ChannelIdentity,
    DeliveryStatus,
    EpisodicMemory,
    PlanningRound,
    ProposedCall,
    RecordedCall,
    RecordedDelivery,
)
from ai_assistant.interfaces import episode_inspection

_CHAT = ChannelIdentity(channel_type="telegram", instance_id="conn-1/42")


def _lines(record: EpisodicMemory) -> list[str]:
    buffer = StringIO()
    episode_inspection.render_detail(
        Console(file=buffer, force_terminal=False, width=200), record, stories=()
    )
    return buffer.getvalue().splitlines()


def _planning(record: EpisodicMemory) -> list[str]:
    """The rounds and calls sections, between the retention notice and the JSON."""
    lines = _lines(record)
    start = next(n for n, line in enumerate(lines) if line.startswith("Retention expiry"))
    return lines[start + 1 : lines.index("{")]


def _after() -> EpisodicMemory:
    """Two rounds recorded after the decision: notes, a message call, a look-up."""
    rounds = (
        PlanningRound(
            id="r1",
            recorded_at=_AT,
            notes="look up the 18th first",
            notes_marked=False,
            calls=(ProposedCall(call_id="c1", name="web_search", arguments={"query": "q"}),),
        ),
        PlanningRound(
            id="r2",
            follows="r1",
            recorded_at=_AT,
            notes="pitch 4 is free",
            notes_marked=True,
            calls=(
                ProposedCall(call_id="c2", name="text", arguments={"words": "x"}),
                ProposedCall(call_id="c3", name="text", arguments={"words": "y"}),
                ProposedCall(call_id="c4", name="tidy_up", arguments={}),
            ),
        ),
    )
    entries = (
        RecordedCall(
            round="r1",
            call_id="c1",
            capability="web_search",
            effect=False,
            outcome=CallOutcomeKind.DONE,
            recorded_at=_AT,
        ),
        RecordedCall(
            round="r2",
            call_id="c2",
            capability="text",
            effect=True,
            outcome=CallOutcomeKind.DONE,
            delivered=RecordedDelivery(
                words="Pitch 4 is booked.", went=_CHAT, status=DeliveryStatus.SENT
            ),
            recorded_at=_AT,
            marked=True,
        ),
        RecordedCall(
            round="r2",
            call_id="c3",
            capability="text",
            effect=True,
            outcome=CallOutcomeKind.REFUSED,
            reason="names a place it was never shown",
            recorded_at=_AT,
        ),
        RecordedCall(round="r2", call_id="c4", capability="tidy_up", effect=True, recorded_at=_AT),
    )
    return _staged(_record("after", response="sent"), rounds=rounds, call_records=entries)


def test_a_round_after_the_decision_shows_its_notes_and_each_calls_entry() -> None:
    assert _planning(_after()) == [
        "Rounds:",
        f'  Round "r1", recorded {_AT.isoformat()}',
        '    Notes: "look up the 18th first"',
        f'  Round "r2", recorded {_AT.isoformat()}',
        '    Notes (rests on outside content): "pitch 4 is free"',
        "Calls:",
        '  Round "r1", call "c1": web_search (no effect): done',
        '  Round "r2", call "c2": text (with an effect; rests on outside content): done',
        '    Sent to telegram/conn-1/42: sent: "Pitch 4 is booked."',
        '  Round "r2", call "c3": text (with an effect): refused',
        '    Reason: "names a place it was never shown"',
        '  Round "r2", call "c4": tidy_up (with an effect): no outcome recorded',
    ]


def test_a_round_before_the_decision_shows_the_message_its_text_wrote() -> None:
    """§8:1: a round recorded before keeps its text as the message it wrote."""
    rounds = (
        PlanningRound(
            id="r1",
            recorded_at=_AT,
            text="Riverside has pitch 4 free.",
            notes="the 18th suits",
            place=_CHAT,
        ),
    )
    record = _staged(_record("before", response="sent"), rounds=rounds)

    assert _planning(record) == [
        "Rounds:",
        f'  Round "r1", recorded {_AT.isoformat()}',
        '    Message (into telegram/conn-1/42): "Riverside has pitch 4 free."',
        '    Notes: "the 18th suits"',
        "Calls: none recorded",
    ]


def test_a_delivery_that_failed_says_why() -> None:
    entry = RecordedCall(
        round="r1",
        call_id="c1",
        capability="text",
        effect=True,
        outcome=CallOutcomeKind.NOT_DONE,
        reason="the place refused it",
        delivered=RecordedDelivery(
            words="Booked.", went=_CHAT, status=DeliveryStatus.FAILED, reason="blocked by the user"
        ),
        recorded_at=_AT,
    )
    rounds = (
        PlanningRound(
            id="r1",
            recorded_at=_AT,
            calls=(ProposedCall(call_id="c1", name="text", arguments={"words": "Booked."}),),
        ),
    )
    record = _staged(_record("failed", response="none"), rounds=rounds, call_records=(entry,))

    assert _planning(record)[-4:] == [
        '  Round "r1", call "c1": text (with an effect): not_done',
        '    Reason: "the place refused it"',
        '    Sent to telegram/conn-1/42: failed: "Booked."',
        '      Why: "blocked by the user"',
    ]


def test_no_rounds_or_calls_say_so_and_an_open_episode_says_yet() -> None:
    assert _planning(_record("frozen", response="none")) == [
        "Rounds: none recorded",
        "Calls: none recorded",
    ]
    assert _planning(_open_record("open")) == [
        "Rounds: none recorded yet",
        "Calls: none recorded yet",
    ]


def test_an_episode_with_no_processing_record_has_neither() -> None:
    assert _planning(_record("plain")) == ["Rounds: unavailable", "Calls: unavailable"]


def test_a_rounds_text_is_quoted_so_it_cannot_pose_as_a_line() -> None:
    rounds = (PlanningRound(id="r1", recorded_at=_AT, text="ok\nCalls: none recorded"),)
    record = _staged(_record("quoted", response="sent"), rounds=rounds)

    assert '    Message: "ok\\nCalls: none recorded"' in _planning(record)
