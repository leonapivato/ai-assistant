"""The two narrowing levers, which are not the same lever."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from benchmarks.memory.cases import BenchCase, BenchQuestion, BenchSession, BenchTurn
from benchmarks.memory.select import first_questions, first_sessions

FIRST = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)


def _case(key: str, *, sessions: int, questions: int) -> BenchCase:
    """A case with the requested shape.

    Args:
        key: The case key.
        sessions: How many sessions.
        questions: How many questions.

    Returns:
        The case.
    """
    return BenchCase(
        corpus_key="locomo",
        case_key=key,
        sessions=tuple(
            BenchSession(
                session_key=f"session_{index}",
                occurred_at=FIRST + timedelta(days=30 * index),
                turns=(BenchTurn(speaker="Ada", text=f"turn {index}", user_side=True),),
            )
            for index in range(sessions)
        ),
        questions=tuple(
            BenchQuestion(question_id=f"{key}#{index}", category="1", question="q?", answer="a")
            for index in range(questions)
        ),
    )


def test_a_question_limit_stops_at_the_first_case_that_covers_it() -> None:
    """On LoCoMo a question limit is really a case limit — five questions should
    ingest one dialogue, not ten."""
    cases = (_case("a", sessions=3, questions=199), _case("b", sessions=3, questions=199))

    taken = first_questions(cases, 5)

    assert len(taken) == 1
    assert len(taken[0].questions) == 5


def test_a_question_limit_spills_into_the_next_case_when_one_runs_short() -> None:
    cases = (_case("a", sessions=1, questions=2), _case("b", sessions=1, questions=9))

    taken = first_questions(cases, 5)

    assert [len(case.questions) for case in taken] == [2, 3]


def test_a_zero_question_limit_keeps_everything() -> None:
    cases = (_case("a", sessions=1, questions=2),)

    assert first_questions(cases, 0) == cases


def test_a_question_limit_above_the_corpus_keeps_everything() -> None:
    cases = (_case("a", sessions=1, questions=2),)

    assert first_questions(cases, 99) == cases


def test_a_session_limit_shortens_every_case() -> None:
    cases = (_case("a", sessions=19, questions=2), _case("b", sessions=4, questions=2))

    shortened = first_sessions(cases, 2)

    assert [len(case.sessions) for case in shortened] == [2, 2]


def test_a_session_limit_leaves_the_questions_alone() -> None:
    """The two levers are independent: shortening the history asks the same questions
    of a different memory, which is why it is a plumbing lever and not a sampling one."""
    cases = (_case("a", sessions=19, questions=7),)

    assert len(first_sessions(cases, 2)[0].questions) == 7


def test_a_session_limit_above_the_case_keeps_what_there_is() -> None:
    cases = (_case("a", sessions=3, questions=2),)

    assert len(first_sessions(cases, 99)[0].sessions) == 3


def test_a_zero_session_limit_keeps_everything() -> None:
    cases = (_case("a", sessions=3, questions=2),)

    assert first_sessions(cases, 0) == cases


def test_a_negative_session_limit_is_refused() -> None:
    """Python's slice would silently drop from the end instead."""
    cases = (_case("a", sessions=3, questions=2),)

    with pytest.raises(ValueError, match="cannot be negative"):
        first_sessions(cases, -1)


def test_a_negative_question_limit_is_refused() -> None:
    """The loop would otherwise break immediately and return no cases — a run that
    completes, writes a manifest and reports success having asked nothing."""
    cases = (_case("a", sessions=1, questions=2),)

    with pytest.raises(ValueError, match="cannot be negative"):
        first_questions(cases, -1)
