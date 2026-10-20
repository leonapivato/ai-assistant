"""The observation record's types (ADR-0329 §16:1).

What a record holds, and the rules the type keeps so that no store can hold a record
the observer could not have written: a finding resting on parts of episodes, from the
episode whose record holds it; an outcome naming what was written or why nothing was;
a processed episode whose findings each have an outcome; a skipped one with no model
call; and the values the queue and the budget read off a record (§16:2, §16:9).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ConfirmationPart,
    EvidenceItemPart,
    FindingOutcome,
    FindingUnwritten,
    InputPart,
    LegacyPart,
    MemoryDecisionKind,
    MemoryOperationKind,
    ObservationAttempt,
    ObservationAttemptEnd,
    ObservationFinding,
    ObservationRecord,
    ObservationState,
    ObservationWrite,
    ObserverCall,
    ObserverStep,
    QuestionPart,
    RememberCallPart,
    RoundMessagePart,
)

_AT = datetime(2026, 10, 19, 9, tzinfo=UTC)
_EPISODE = "activation:act-1"


def _finding(**fields: Any) -> ObservationFinding:
    values: dict[str, Any] = {
        "id": "f1",
        "episode": _EPISODE,
        "claim": "The user prefers window seats.",
        "rests_on": (InputPart(episode=_EPISODE),),
    }
    return ObservationFinding(**(values | fields))


def _written(memory: str = "memory-1", **fields: Any) -> FindingOutcome:
    write = ObservationWrite(memory=memory, operations=(MemoryOperationKind.CREATE,), **fields)
    return FindingOutcome(at=_AT, ruling=MemoryDecisionKind.ACCEPT, writes=(write,))


def _attempt(*calls: datetime, end: ObservationAttemptEnd | None = None) -> ObservationAttempt:
    return ObservationAttempt(
        started_at=calls[0] if calls else _AT,
        calls=tuple(ObserverCall(step=ObserverStep.COMMIT, at=at) for at in calls),
        end=end,
    )


# --- a finding ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "part",
    [
        InputPart(episode=_EPISODE, message=1),
        RoundMessagePart(episode="activation:act-2", round="r1"),
        EvidenceItemPart(episode=_EPISODE, digest=0, item=0),
        ConfirmationPart(
            episode="activation:act-3",
            asking_activation="act-1",
            question=QuestionPart(round="r1", part=1),
        ),
    ],
    ids=["input", "a-later-rounds-message", "evidence", "confirmation"],
)
def test_a_finding_rests_on_any_part_of_an_episode(part: Any) -> None:
    """§9:6: the input or a message, a round's message, an evidence item, a confirmation."""
    assert _finding(rests_on=(part,)).rests_on == (part,)


@pytest.mark.parametrize(
    "part",
    [RememberCallPart(episode=_EPISODE, effect="e1"), LegacyPart(record="old-1")],
    ids=["a-candidate", "a-legacy-record"],
)
def test_a_finding_rests_on_no_candidate_and_no_legacy_record(part: Any) -> None:
    """§3:6: a candidate is a hint and never a part; a legacy record is no episode's."""
    with pytest.raises(ValidationError, match="rests on parts of episodes"):
        _finding(rests_on=(part,))


def test_a_finding_rests_on_at_least_one_part_each_once() -> None:
    """§9:1: a finding names the parts it rests on, and names each once."""
    with pytest.raises(ValidationError):
        _finding(rests_on=())
    with pytest.raises(ValidationError, match="each part it rests on once"):
        _finding(rests_on=(InputPart(episode=_EPISODE), InputPart(episode=_EPISODE)))


def test_a_track_record_entry_belongs_to_a_reliance_finding_on_its_memory() -> None:
    """§14:1: an entry is recorded on the memory a reliance call named, and only there."""
    entry = _written("memory-1", track_record=True)

    assert _finding(relied_on="memory-1", outcome=entry).outcome == entry
    with pytest.raises(ValidationError, match="reliance finding"):
        _finding(outcome=entry)
    with pytest.raises(ValidationError, match="reliance finding"):
        _finding(relied_on="memory-2", outcome=entry)


# --- an outcome --------------------------------------------------------------------


def test_an_outcome_names_what_was_written_or_why_not_and_never_both() -> None:
    """§16:1: what was written, with the memory ids and operations, or why nothing was."""
    assert _written().unwritten is None
    assert FindingOutcome(at=_AT, unwritten=FindingUnwritten.BELOW_FLOOR).writes == ()
    with pytest.raises(ValidationError, match="never both"):
        FindingOutcome(at=_AT)
    with pytest.raises(ValidationError, match="never both"):
        FindingOutcome(
            at=_AT,
            writes=_written().writes,
            unwritten=FindingUnwritten.NOT_KEPT,
        )


def test_a_retiring_finding_names_both_memories_it_wrote_on() -> None:
    """§12:4: the new memory and the retired one, each with its operations."""
    outcome = FindingOutcome(
        at=_AT,
        ruling=MemoryDecisionKind.ACCEPT,
        writes=(
            ObservationWrite(memory="new", operations=(MemoryOperationKind.CREATE,)),
            ObservationWrite(
                memory="old",
                operations=(MemoryOperationKind.ADD_SUPPORT, MemoryOperationKind.REPLACE),
            ),
        ),
    )

    assert [write.memory for write in outcome.writes] == ["new", "old"]
    with pytest.raises(ValidationError, match="each memory it wrote on once"):
        FindingOutcome(at=_AT, writes=(outcome.writes[0], outcome.writes[0]))


def test_a_write_names_an_operation_or_an_entry() -> None:
    """A write that changed nothing on its memory is no write."""
    assert ObservationWrite(memory="m", track_record=False).operations == ()
    with pytest.raises(ValidationError, match="operation or a track-record entry"):
        ObservationWrite(memory="m")


def test_an_ask_naming_no_memory_is_recorded_under_its_ruling() -> None:
    """§13:3: an ``ASK_USER`` naming no stored memory writes nothing, and says so."""
    asked = FindingOutcome(
        at=_AT, ruling=MemoryDecisionKind.ASK_USER, unwritten=FindingUnwritten.ASKED
    )

    assert asked.ruling is MemoryDecisionKind.ASK_USER
    with pytest.raises(ValidationError, match="ruling of ask_user"):
        FindingOutcome(at=_AT, unwritten=FindingUnwritten.ASKED)


def test_an_ask_naming_memories_raised_a_question_on_each() -> None:
    """§13:1: an ``ASK_USER`` on stored memories is a write: a question on each."""
    raised = (MemoryOperationKind.ADD_SUPPORT, MemoryOperationKind.RAISE_QUESTION)
    outcome = FindingOutcome(
        at=_AT,
        ruling=MemoryDecisionKind.ASK_USER,
        writes=(
            ObservationWrite(memory="a", operations=raised),
            ObservationWrite(memory="b", operations=raised),
        ),
    )

    assert len(outcome.writes) == 2


# --- an attempt --------------------------------------------------------------------


def test_an_attempts_calls_follow_its_start_in_order() -> None:
    """A call is made after the attempt started, and the calls are recorded in order."""
    later = _AT + timedelta(seconds=5)
    assert len(_attempt(_AT, later).calls) == 2
    with pytest.raises(ValidationError, match="in order"):
        _attempt(later, _AT)
    with pytest.raises(ValidationError, match="in order"):
        ObservationAttempt(started_at=later, calls=(ObserverCall(step=ObserverStep.SCOUT, at=_AT),))


# --- the record --------------------------------------------------------------------


def test_a_finding_comes_from_the_episode_whose_record_holds_it() -> None:
    """§8:3: each finding names the one episode it comes from, and is recorded there."""
    with pytest.raises(ValidationError, match="comes from the episode"):
        ObservationRecord(
            episode=_EPISODE,
            state=ObservationState.WAITING,
            findings=(_finding(episode="activation:other"),),
        )


def test_a_record_names_each_finding_once() -> None:
    """§16:4: a retry finds a finding by its id, so the id is unique on the record."""
    with pytest.raises(ValidationError, match="each finding once"):
        ObservationRecord(
            episode=_EPISODE, state=ObservationState.WAITING, findings=(_finding(), _finding())
        )


def test_a_processed_episodes_findings_each_have_an_outcome() -> None:
    """§16:4: a retry runs what has no outcome, so a processed episode has none left."""
    done = _finding(outcome=_written())

    assert ObservationRecord(
        episode=_EPISODE, state=ObservationState.PROCESSED, findings=(done,)
    ).findings == (done,)
    with pytest.raises(ValidationError, match="each have an outcome"):
        ObservationRecord(
            episode=_EPISODE,
            state=ObservationState.PROCESSED,
            findings=(done, _finding(id="f2")),
        )
    waiting = ObservationRecord(
        episode=_EPISODE, state=ObservationState.WAITING, findings=(done, _finding(id="f2"))
    )
    assert [one.outcome is None for one in waiting.findings] == [False, True]


def test_a_skipped_episode_has_no_finding_and_no_model_call() -> None:
    """§16:7: skipped by rule, with no model call."""
    assert (
        ObservationRecord(
            episode=_EPISODE,
            state=ObservationState.SKIPPED,
            attempts=(_attempt(end=ObservationAttemptEnd.FINISHED),),
        ).call_count()
        == 0
    )
    with pytest.raises(ValidationError, match="no model call"):
        ObservationRecord(
            episode=_EPISODE,
            state=ObservationState.SKIPPED,
            attempts=(_attempt(_AT, end=ObservationAttemptEnd.FINISHED),),
        )
    with pytest.raises(ValidationError, match="no finding"):
        ObservationRecord(episode=_EPISODE, state=ObservationState.SKIPPED, findings=(_finding(),))


def test_only_the_last_attempt_may_run_and_only_while_the_episode_waits() -> None:
    """An attempt records outcomes as it goes, so a waiting record may hold one open."""
    open_last = (_attempt(_AT, end=ObservationAttemptEnd.FAILED), _attempt(_AT))

    assert (
        ObservationRecord(
            episode=_EPISODE, state=ObservationState.WAITING, attempts=open_last
        ).attempts
        == open_last
    )
    with pytest.raises(ValidationError, match="last attempt"):
        ObservationRecord(
            episode=_EPISODE,
            state=ObservationState.WAITING,
            attempts=(_attempt(_AT), _attempt(_AT, end=ObservationAttemptEnd.FAILED)),
        )
    with pytest.raises(ValidationError, match="leaves its episode waiting"):
        ObservationRecord(episode=_EPISODE, state=ObservationState.STUCK, attempts=open_last)


def test_attempts_are_in_the_order_they_started() -> None:
    later = _AT + timedelta(minutes=1)
    with pytest.raises(ValidationError, match="order they started"):
        ObservationRecord(
            episode=_EPISODE,
            state=ObservationState.WAITING,
            attempts=(
                _attempt(later, end=ObservationAttemptEnd.FAILED),
                _attempt(_AT, end=ObservationAttemptEnd.FAILED),
            ),
        )


@pytest.mark.parametrize(
    "state", [ObservationState.PROCESSED, ObservationState.SKIPPED, ObservationState.STUCK]
)
def test_only_a_waiting_episode_has_a_next_attempt(state: ObservationState) -> None:
    """§16:4: the backoff is a waiting episode's."""
    with pytest.raises(ValidationError, match="next attempt"):
        ObservationRecord(episode=_EPISODE, state=state, next_attempt_at=_AT)


def test_the_queue_takes_a_waiting_episode_once_its_backoff_has_passed() -> None:
    """§16:2: due, not settled, and may be attempted now."""
    backing_off = ObservationRecord(
        episode=_EPISODE, state=ObservationState.WAITING, next_attempt_at=_AT
    )

    assert not backing_off.attemptable(_AT - timedelta(seconds=1))
    assert backing_off.attemptable(_AT)
    assert ObservationRecord(episode=_EPISODE, state=ObservationState.WAITING).attemptable(_AT)
    for state in (ObservationState.PROCESSED, ObservationState.SKIPPED, ObservationState.STUCK):
        assert not ObservationRecord(episode=_EPISODE, state=state).attemptable(_AT)


def test_the_budget_counts_every_attempts_calls_from_an_instant() -> None:
    """§16:9: the calls each attempt made, at or after the instant asked about."""
    later = _AT + timedelta(hours=1)
    record = ObservationRecord(
        episode=_EPISODE,
        state=ObservationState.STUCK,
        attempts=(
            _attempt(_AT, _AT, end=ObservationAttemptEnd.FAILED),
            _attempt(later, end=ObservationAttemptEnd.FAILED),
        ),
    )

    assert record.call_count() == 3
    assert record.call_count(_AT) == 3
    assert record.call_count(later) == 1
    assert record.call_count(later + timedelta(microseconds=1)) == 0
    assert record.last_call_at == later
    assert ObservationRecord(episode=_EPISODE, state=ObservationState.WAITING).last_call_at is None


def test_a_record_round_trips_through_json() -> None:
    """A store keeps the record as its JSON dump, so the dump must read back equal."""
    record = ObservationRecord(
        episode=_EPISODE,
        state=ObservationState.PROCESSED,
        attempts=(_attempt(_AT, end=ObservationAttemptEnd.FINISHED),),
        findings=(
            _finding(candidate="effect-1", outcome=_written()),
            _finding(
                id="f2",
                relied_on="memory-9",
                outcome=FindingOutcome(at=_AT, unwritten=FindingUnwritten.NOT_KEPT),
            ),
        ),
        revision=7,
    )

    assert ObservationRecord.model_validate_json(record.model_dump_json()) == record


def test_a_revision_is_never_negative() -> None:
    with pytest.raises(ValidationError):
        ObservationRecord(episode=_EPISODE, state=ObservationState.WAITING, revision=-1)
