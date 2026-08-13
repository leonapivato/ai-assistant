"""The benchmark clock, and the folding of corpus turns into capture's exchanges."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from benchmarks.memory.cases import BenchSession, BenchTurn
from benchmarks.memory.clock import BenchmarkClock
from benchmarks.memory.ingest import exchanges_of

WHEN = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)


def test_a_clock_reads_what_it_was_set_to() -> None:
    clock = BenchmarkClock(start=WHEN)

    assert clock() == WHEN


def test_a_clock_defaults_to_the_epoch_not_the_wall() -> None:
    """A forgotten `set` should produce obviously wrong stamps, not plausible ones."""
    assert BenchmarkClock()() == datetime(1970, 1, 1, tzinfo=UTC)


def test_a_clock_moves_forward() -> None:
    clock = BenchmarkClock(start=WHEN)

    clock.set(WHEN + timedelta(days=30))

    assert clock() == WHEN + timedelta(days=30)


def test_a_clock_moves_backward_because_a_run_does() -> None:
    """Case n+1's first session can precede case n's last, and nothing here is monotonic."""
    clock = BenchmarkClock(start=WHEN)

    clock.set(WHEN - timedelta(days=400))

    assert clock() == WHEN - timedelta(days=400)


def test_a_naive_start_is_refused() -> None:
    """The product's `checked_clock` refuses one; failing here names this class."""
    with pytest.raises(ValueError, match="timezone-aware"):
        BenchmarkClock(start=datetime(2023, 5, 8, 13, 56))  # noqa: DTZ001 — the point of the test


def test_a_naive_set_is_refused() -> None:
    clock = BenchmarkClock(start=WHEN)

    with pytest.raises(ValueError, match="timezone-aware"):
        clock.set(datetime(2023, 5, 8, 13, 56))  # noqa: DTZ001 — the point of the test


def test_a_non_utc_offset_is_accepted() -> None:
    """Determinate is what is required, not UTC."""
    stamped = datetime(2023, 5, 8, 13, 56, tzinfo=timezone(timedelta(hours=-5)))

    assert BenchmarkClock(start=stamped)() == stamped


def _session(*turns: tuple[str, bool]) -> BenchSession:
    """Build a session from (text, user_side) pairs.

    Args:
        turns: The utterances.

    Returns:
        The session.
    """
    return BenchSession(
        session_key="s",
        occurred_at=WHEN,
        turns=tuple(
            BenchTurn(speaker="u" if user else "a", text=text, user_side=user)
            for text, user in turns
        ),
    )


def test_a_user_turn_and_the_reply_are_one_exchange() -> None:
    built = exchanges_of(_session(("hello", True), ("hi", False)))

    assert len(built) == 1
    assert built[0].content == "hello"
    assert built[0].outcome == "hi"
    assert built[0].user_led is True


def test_a_trailing_user_turn_has_no_outcome() -> None:
    """A session can end on the user; capture takes `outcome=None`."""
    built = exchanges_of(_session(("hello", True)))

    assert built[0].outcome is None


def test_consecutive_same_side_turns_join_into_one_half() -> None:
    """Neither corpus guarantees strict alternation."""
    built = exchanges_of(_session(("one", True), ("two", True), ("reply", False), ("more", False)))

    assert len(built) == 1
    assert built[0].content == "one\ntwo"
    assert built[0].outcome == "reply\nmore"


def test_a_session_opening_on_the_assistant_records_that_run_alone() -> None:
    """Five of LongMemEval's oracle sessions open this way; the content must survive."""
    built = exchanges_of(_session(("good morning", False), ("morning", True)))

    assert len(built) == 2
    assert built[0].content == "good morning"
    assert built[0].user_led is False
    assert built[1].content == "morning"
    assert built[1].user_led is True


def test_an_empty_session_yields_nothing() -> None:
    assert exchanges_of(_session()) == ()


def test_every_exchange_carries_non_blank_content() -> None:
    """Capture refuses a blank user half, so the builder must never produce one."""
    built = exchanges_of(
        _session(("a", False), ("b", True), ("c", False), ("d", True), ("e", True))
    )

    assert all(exchange.content.strip() for exchange in built)
