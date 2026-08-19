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
from itertools import pairwise
from typing import TYPE_CHECKING

import pytest
from benchmarks.memory.cases import BenchCase, BenchSession, BenchTurn
from benchmarks.memory.ingest import _overlap_of, ingest_case
from benchmarks.memory.wiring import build_harness

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.orchestration.conversations import CaptureReport
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


def _settings(tmp_path: Path, *, batch_size: int) -> Settings:
    """Settings a plumbing check may use, and a scored run may not.

    Args:
        tmp_path: The test's directory.
        batch_size: The window the stage is built with.

    Returns:
        The settings.
    """
    return Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        episode_retention=None,
        observation_batch_size=batch_size,
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
    settings = _settings(tmp_path, batch_size=batch_size)
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


async def _windows_with_gaps(
    tmp_path: Path, *, turns: int, batch_size: int, unresolvable: set[int]
) -> list[list[str]]:
    """Ingest ``turns`` where the captures in ``unresolvable`` store no episode.

    The failure simulated is the *episode-stage* one, which is the case that matters
    for §7: the turn is appended and holds a slot in every window that reaches it,
    and ``ObservationStage`` skips it without backfilling (ADR-0074 §5). So the window
    is ``batch_size`` turns and fewer than ``batch_size`` episodes, which is exactly
    where turn-paced tiling and episode-counted overlap come apart.

    Args:
        tmp_path: The test's directory.
        turns: How many utterances to capture.
        batch_size: The window the stage is built with.
        unresolvable: 1-based capture positions whose episode is deleted after the
            turn is appended.

    Returns:
        One list of episode ids per observation pass, in pass order.
    """
    settings = _settings(tmp_path, batch_size=batch_size)
    observer = FakeObserver(beliefs=[], max_batch_size=batch_size)
    harness = build_harness(settings, data_dir=tmp_path / "case", observer=observer)
    real_capture = harness.lifecycle.capture
    position = 0

    async def _capture(conversation_id: str, *, content: str, **kwargs: object) -> CaptureReport:
        """Capture for real, then destroy the episode where this position is named.

        Args:
            conversation_id: The conversation.
            content: The user half.
            kwargs: Relayed.

        Returns:
            The real report, or a degraded one whose turn stands and whose episode
            does not.
        """
        nonlocal position
        position += 1
        report = await real_capture(conversation_id, content=content, **kwargs)  # type: ignore[arg-type]
        if position not in unresolvable or report.episode_id is None:
            return report
        await harness.store.delete(report.episode_id)
        return CaptureReport(conversation_id=conversation_id, degraded=True)

    try:
        harness.lifecycle.capture = _capture  # type: ignore[method-assign]
        await ingest_case(harness, _case(turns), batch_size=batch_size)
    finally:
        harness.close()
    return [[record.id for record in batch] for batch in observer.batches]


async def test_a_gap_in_a_window_does_not_shrink_the_overlap_it_carries(
    tmp_path: Path,
) -> None:
    """§7 counts **episodes**, and a window of turns can hold fewer of them.

    ``ObservationStage``'s window is the conversation's most recent ``batch_size``
    *turns*, and a turn whose episode no longer resolves still holds a slot in it
    (ADR-0074 §5). A driver pacing purely on captures therefore satisfies §7 only
    while every turn resolves: put one gap in the first window and its last three
    *episodes* stop being the next window's first three, because the next window's
    six turns contain only five episodes and start a position too late.

    This is the shape the architecture lens named, run as it described it — six
    captures with the sixth's episode destroyed, then three more that land — and the
    assertion is §7's identity itself rather than a pass count.
    """
    batch_size = 6
    overlap = _overlap_of(batch_size)

    windows = await _windows_with_gaps(tmp_path, turns=9, batch_size=batch_size, unresolvable={6})

    assert overlap == 3
    assert len(windows) >= 2
    assert len(windows[0]) == batch_size - 1, "the gap costs the first window an episode"
    assert windows[0][-overlap:] == windows[1][:overlap]


@pytest.mark.parametrize(
    "unresolvable",
    [{2}, {5}, {6}, {2, 6}, {4, 5}],
    ids=["early", "in-the-carry", "at-the-edge", "two-apart", "two-adjacent"],
)
async def test_the_overlap_identity_holds_wherever_the_gap_falls(
    tmp_path: Path, unresolvable: set[int]
) -> None:
    """The same identity, over the positions a gap can take relative to the carry.

    A gap before the carried tail, inside it, and at the window's own edge each move
    a different part of the arithmetic, and two gaps test that the carry is counted
    rather than measured off a fixed offset. Parametrised rather than argued, because
    the failure mode is an off-by-one that one position would hide.

    **The closing pass is held to a weaker claim, and that predates ADR-0162.** A case
    whose turn count does not land on the schedule ends with a remainder, and the read
    has no offset — the module docstring says so — so the last pass re-reads more of
    the previous window than the carry asks for. Overlapping by *more* than *k* is not
    a breach of a clause that puts *k* episodes into the next window; what would be is
    losing them, so the final pair is checked for exactly that.
    """
    batch_size = 6
    overlap = _overlap_of(batch_size)

    windows = await _windows_with_gaps(
        tmp_path, turns=12, batch_size=batch_size, unresolvable=unresolvable
    )

    assert len(windows) >= 3, "enough passes for the identity to be tested on its own"
    for earlier, later in pairwise(windows[:-1]):
        carried = min(overlap, len(earlier))
        assert earlier[-carried:] == later[:carried], (
            f"§7's identity failed between scheduled windows, gaps at {unresolvable}"
        )
    earlier, later = windows[-2], windows[-1]
    carried = min(overlap, len(earlier))
    tail = earlier[-carried:]
    assert tail
    assert any(later[index : index + carried] == tail for index in range(len(later))), (
        f"the closing pass lost the carried tail, gaps at {unresolvable}"
    )


async def test_a_lost_append_keeps_the_carried_tail_without_its_position(
    tmp_path: Path,
) -> None:
    """The one failure the driver cannot see, bounded rather than claimed away (#1229).

    `CaptureReport` reports a **lost append** and a lost **episode** identically —
    `degraded=True`, no episode id — which is #1075, whose title says in terms that a
    driver's cadence needs the distinction. Only the second leaves a turn in the
    conversation, so under the first this driver's positions run ahead of it and the
    schedule aims at a turn that is not where it thinks.

    **The direction of that error is the safe one, and this is where it is proved.**
    Over-counting fires a pass earlier in real turns than intended, so the next window
    begins at or before the episode the carry aimed at and still *contains* the whole
    carried tail: §7's remedy — a fact spread across a boundary is whole in some pass
    — is delivered, and what is lost is its position as the literal prefix, plus some
    duplicated passes. This runs the architecture lens's own case, `batch_size` 6 with
    captures 5 and 6 refused at append, and asserts exactly that bound and no more.

    Closing it exactly needs #1075 and a change in `orchestration`, which this module
    may not make: a floor on the schedule would buy this case by breaking the
    episode-stage case above, because the driver cannot tell which one it is in.
    """
    batch_size = 6
    overlap = _overlap_of(batch_size)
    settings = _settings(tmp_path, batch_size=batch_size)
    observer = FakeObserver(beliefs=[], max_batch_size=batch_size)
    harness = build_harness(settings, data_dir=tmp_path / "case", observer=observer)
    real_capture = harness.lifecycle.capture
    position = 0

    async def _capture(conversation_id: str, *, content: str, **kwargs: object) -> CaptureReport:
        """Refuse the fifth and sixth captures before anything is appended.

        Args:
            conversation_id: The conversation.
            content: The user half.
            kwargs: Relayed.

        Returns:
            A degraded report whose turn was never recorded, or the real one.
        """
        nonlocal position
        position += 1
        if position in {5, 6}:
            return CaptureReport(conversation_id=conversation_id, degraded=True)
        return await real_capture(conversation_id, content=content, **kwargs)  # type: ignore[arg-type]

    try:
        harness.lifecycle.capture = _capture  # type: ignore[method-assign]
        await ingest_case(harness, _case(12), batch_size=batch_size)
    finally:
        harness.close()

    windows = [[record.id for record in batch] for batch in observer.batches]
    assert len(windows) >= 2
    for earlier, later in pairwise(windows):
        carried = min(overlap, len(earlier))
        tail = earlier[-carried:]
        assert any(later[index : index + carried] == tail for index in range(len(later))), (
            "a lost append may cost the tail its position and must never cost the tail"
        )


async def test_captures_that_store_no_episode_buy_no_pass_of_their_own(
    tmp_path: Path,
) -> None:
    """The other route to a window wholly contained in the one before it.

    ``pending`` counts **every** capture, degraded or not, and deliberately: the
    window counts turns, an episode-stage failure still leaves a turn holding a slot,
    and `CaptureReport` reports a lost append identically (#1075), so pacing on
    successful captures alone would let a good episode fall out of every window that
    is ever read. What that costs is that a run of captures storing nothing can carry
    ``pending`` to the trigger on its own — and where the appends were the half that
    failed, the conversation has not moved, so the pass re-reads exactly the window
    the last one read. It was reachable before ADR-0162 §7 after ``batch_size`` such
    captures; the overlap makes it reachable after ``batch_size - overlap``.

    So the trigger also asks whether anything landed. Here the first six captures are
    real and the next three store nothing at all: without the gate the driver fires a
    second pass over the first six episodes, and with it the run ends on one pass. The counting is
    unchanged, which the summary is asserted on — all nine turns are counted, three of
    them as degraded.
    """
    batch_size = 6
    settings = _settings(tmp_path, batch_size=batch_size)
    observer = FakeObserver(beliefs=[], max_batch_size=batch_size)
    harness = build_harness(settings, data_dir=tmp_path / "case", observer=observer)
    real_capture = harness.lifecycle.capture
    landed: list[str] = []

    async def _capture(conversation_id: str, *, content: str, **kwargs: object) -> CaptureReport:
        """Capture for real for the first six turns, then store nothing at all.

        Args:
            conversation_id: The conversation.
            content: The user half.
            kwargs: Relayed.

        Returns:
            The real report, or a degraded one carrying no episode.
        """
        if len(landed) >= batch_size:
            return CaptureReport(conversation_id=conversation_id, degraded=True)
        report = await real_capture(conversation_id, content=content, **kwargs)  # type: ignore[arg-type]
        landed.append(content)
        return report

    try:
        harness.lifecycle.capture = _capture  # type: ignore[method-assign]
        summary = await ingest_case(harness, _case(batch_size + 3), batch_size=batch_size)
    finally:
        harness.close()

    assert summary.turns_captured == batch_size
    assert summary.turns_degraded == 3
    assert summary.observation_passes == 1
    assert [[record.id for record in batch] for batch in observer.batches] == [
        [record.id for record in observer.batches[0]]
    ]


async def test_a_pass_fires_on_the_first_capture_that_lands_after_a_barren_stretch(
    tmp_path: Path,
) -> None:
    """The gate postpones a pass; it must never cancel one.

    Postponing lets ``pending`` run past the threshold, so the trigger tests ``>=``
    rather than ``==`` — an equality would step over the boundary during the barren
    stretch and never come back to it, and every episode captured afterwards would go
    unobserved until the *next* whole window. The barren stretch here is deliberately
    longer than the window for exactly that reason: the threshold of six is crossed at
    the sixth capture, with nothing stored and no pass owed, and the equality is gone
    by the time anything lands. What is pinned is the tighter property — the pass
    fires on the very first capture that lands an episode, with that episode the most
    recent turn in the window it reads.
    """
    batch_size = 6
    barren = 8
    settings = _settings(tmp_path, batch_size=batch_size)
    observer = FakeObserver(beliefs=[], max_batch_size=batch_size)
    harness = build_harness(settings, data_dir=tmp_path / "case", observer=observer)
    real_capture = harness.lifecycle.capture
    seen: list[str] = []

    async def _capture(conversation_id: str, *, content: str, **kwargs: object) -> CaptureReport:
        """Store nothing for the first ``barren`` captures, then capture for real.

        Args:
            conversation_id: The conversation.
            content: The user half.
            kwargs: Relayed.

        Returns:
            A degraded report carrying no episode, or the real one.
        """
        seen.append(content)
        if len(seen) <= barren:
            return CaptureReport(conversation_id=conversation_id, degraded=True)
        return await real_capture(conversation_id, content=content, **kwargs)  # type: ignore[arg-type]

    try:
        harness.lifecycle.capture = _capture  # type: ignore[method-assign]
        await ingest_case(harness, _case(barren + 1), batch_size=batch_size)
    finally:
        harness.close()

    windows = [[record.id for record in batch] for batch in observer.batches]
    assert len(windows) == 1, "one pass, and it is the capture that landed that bought it"
    assert len(windows[0]) == 1, "the one turn that was actually appended"


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
