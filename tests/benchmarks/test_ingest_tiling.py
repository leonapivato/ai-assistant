"""ADR-0162 §7: where the harness's observation windows tile, they overlap.

The loss the section closes is a fact stated across a window boundary — the user
names a trip in the last turn of one window and says where they went in the first
turn of the next, visible to neither pass as a whole. Under ADR-0077 §2's warrant bar
that was rare, because a fragment cleared the bar seldom enough to be noise; under
ADR-0162 §1 every fragment is proposable, so a boundary now cuts through material
that would otherwise have been recorded, at a rate set by an arbitrary alignment
rather than by the data.

These tests pin the clause **as a relation between consecutive windows** rather than
as a pass count, because the pass count is what a driver gets right by accident.
``ObservationStage`` holds no cursor and reads the conversation's most recent
``batch_size`` turns on every call (ADR-0077 §8), so the overlap is not a parameter
the driver passes anywhere: it is bought by advancing fewer captures between passes,
and the only place it is visible is the batches the observer was actually handed.
``FakeObserver`` records every one, which is what makes that checkable here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from benchmarks.memory.cases import BenchCase, BenchSession, BenchTurn
from benchmarks.memory.ingest import _overlap_of, ingest_case
from benchmarks.memory.wiring import build_harness

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.testing import FakeObserver

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.types import EpisodicMemory

pytestmark = pytest.mark.integration

FIRST = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)


def _case(turns: int) -> BenchCase:
    """A supplied transcript of ``turns`` utterances, one episode each.

    ``user_supplied`` is what makes the arithmetic exact: a user-supplied session
    yields **one exchange per corpus turn** rather than folding pairs, so "turn" in
    this file means the same thing it means in ``observation_batch_size``.

    Args:
        turns: How many utterances the case carries.

    Returns:
        The case.
    """
    return BenchCase(
        corpus_key="locomo",
        case_key="tiling",
        sessions=(
            BenchSession(
                session_key="S1",
                occurred_at=FIRST,
                user_supplied=True,
                turns=tuple(
                    BenchTurn(
                        speaker="Caroline",
                        text=f"utterance {index}",
                        user_side=True,
                        evidence_key=f"D1:{index}",
                    )
                    for index in range(1, turns + 1)
                ),
            ),
        ),
        questions=(),
    )


async def _windows(tmp_path: Path, *, turns: int, batch_size: int) -> list[list[str]]:
    """Ingest a case of ``turns`` and return the episode ids of each pass's window.

    Args:
        tmp_path: The test's directory.
        turns: How many utterances to capture.
        batch_size: The window the stage is built with, and the driver paces on.

    Returns:
        One list of episode ids per observation pass, in pass order.
    """
    settings = Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        episode_retention=None,
        observation_batch_size=batch_size,
    )
    observer = FakeObserver(beliefs=[], max_batch_size=batch_size)
    harness = build_harness(settings, data_dir=tmp_path / "case", observer=observer)
    try:
        await ingest_case(harness, _case(turns), batch_size=batch_size)
    finally:
        harness.close()
    return [[record.id for record in batch] for batch in _batches(observer)]


def _batches(observer: FakeObserver) -> list[list[EpisodicMemory]]:
    """The batches the fake was handed, oldest pass first."""
    return [list(batch) for batch in observer.batches]


async def test_consecutive_windows_share_their_boundary_episodes(tmp_path: Path) -> None:
    """§7's first clause, asserted as the identity it states.

    "The last *k* episodes of one window are the first *k* of the next" is a
    statement about two windows, so it is checked as one — the tail of the earlier
    window and the head of the later one are the *same episodes in the same order*,
    not merely the same count. A driver that advanced correctly but reordered, or
    that re-read a different *k* episodes, passes a count assertion and fails this.

    At a batch of 6 the overlap is 3, so the second pass begins 3 captures after the
    first and its window runs from turn 4 to turn 9. The tenth turn is the closing
    remainder, which the module docstring already explains overlaps by more — that is
    ADR-0162 §7 arriving on top of the pre-existing partial-window behaviour, and it
    is why the identity is asserted between the two *full* windows.
    """
    batch_size = 6
    overlap = _overlap_of(batch_size)

    windows = await _windows(tmp_path, turns=10, batch_size=batch_size)

    assert overlap == 3
    assert len(windows) == 3
    assert all(len(window) == batch_size for window in windows)
    assert windows[0][-overlap:] == windows[1][:overlap]
    assert len(set(windows[0]) & set(windows[1])) == overlap, "and shares no more"


async def test_an_episode_carried_in_by_the_overlap_is_a_full_member(tmp_path: Path) -> None:
    """§7's second clause: carried in, not shown as context.

    The alternative shape — render the previous tail as material the model may read
    and not propose from — needs two classes of prompt entry and a rule about
    citation that ADR-0077 §5 does not have. This one needs neither, because the
    carried episode arrives as an ordinary member of an ordinary batch. What that
    means concretely is that nothing in the second window marks it: the observer is
    handed a plain ``Sequence[EpisodicMemory]`` and cannot tell a carried episode
    from a new one, which is the property being pinned.
    """
    windows = await _windows(tmp_path, turns=10, batch_size=6)

    carried = set(windows[0]) & set(windows[1])

    assert carried
    # In the window and not beside it: every carried id occupies one of the window's
    # own positions, at its head, in the order the earlier window left them.
    assert set(windows[1][: len(carried)]) == carried
    # And it is a set of distinct ids like any other, because `Observer.observe`
    # refuses a batch that repeats one — so the carry cannot have doubled an episode.
    assert len(set(windows[1])) == len(windows[1])


async def test_a_carried_tail_alone_never_buys_a_closing_pass(tmp_path: Path) -> None:
    """The overlap must not manufacture a window wholly contained in the one before.

    A driver that reset its pending count to the overlap rather than to zero would
    end every case with a spurious final pass over the same last ``batch_size``
    turns the previous pass just read — the same episodes, a second model call, and a
    duplicate of every proposal. Ingesting exactly one window's worth is where that
    shows: one pass, and no second one over the tail it carried forward.
    """
    windows = await _windows(tmp_path, turns=6, batch_size=6)

    assert len(windows) == 1
    assert len(windows[0]) == 6


async def test_a_batch_of_one_forgoes_the_overlap_entirely(tmp_path: Path) -> None:
    """§7's fourth clause, which rules the empty-bound case rather than leaving it.

    ``observation_batch_size`` may be 1 — ``Settings`` permits it and the harness's
    own fixtures use it — and there the bound "at least 1 and at most
    ``batch_size // 2``" is empty. An overlap of 1 on a window of 1 advances the
    tiling by nothing, so no value satisfies progress and overlap together; §7 sets
    *k* to 0 and says the deployment forgoes the remedy. The observable consequence
    is that the windows tile exactly as they did before ADR-0162.
    """
    assert _overlap_of(1) == 0

    windows = await _windows(tmp_path, turns=3, batch_size=1)

    assert len(windows) == 3
    assert all(len(window) == 1 for window in windows)
    assert not set(windows[0]) & set(windows[1])
    assert not set(windows[1]) & set(windows[2])


@pytest.mark.parametrize("batch_size", [1, 2, 3, 4, 8, 20, 100])
def test_the_overlap_stays_inside_the_bound_the_adr_sets(batch_size: int) -> None:
    """§7's third and fourth clauses as a property, over the whole range.

    At least 1 and at most ``batch_size // 2`` wherever that bound is non-empty, and
    exactly 0 where it is. The floor is what makes the clause a rule rather than a
    permission — 0 is the behaviour ADR-0162 §7 replaces — and the ceiling is a cost
    bound: the re-read cost is exactly ``batch / (batch - k)`` passes over a corpus,
    so *k* at half the batch doubles ingestion spend and anything above it more than
    doubles it.
    """
    overlap = _overlap_of(batch_size)

    if batch_size == 1:
        assert overlap == 0
    else:
        assert 1 <= overlap <= batch_size // 2


@pytest.mark.parametrize("batch_size", [6, 8, 20])
def test_the_overlap_guarantees_a_run_of_that_many_turns_plus_one_is_whole(
    batch_size: int,
) -> None:
    """What the chosen figure buys, stated as the property that chose it.

    Windows start every ``batch_size - k`` turns and run ``batch_size`` long, so a
    run of ``L`` consecutive turns starting anywhere is contained in some window
    exactly when ``L <= k + 1``. That is the guarantee the constant is set for — a
    fact spread over at most ``k + 1`` consecutive turns is whole in some pass — and
    it is asserted by exhaustive simulation rather than restated, because the
    arithmetic is the whole justification for the number.
    """
    overlap = _overlap_of(batch_size)
    stride = batch_size - overlap
    longest = overlap + 1

    starts = [1 + stride * index for index in range(4 * batch_size)]
    for start in range(1, 3 * batch_size):
        assert any(
            window_start <= start and start + longest - 1 <= window_start + batch_size - 1
            for window_start in starts
        ), f"a run of {longest} turns from {start} fits no window"
