"""ADR-0220: the harness's observation pages tile contiguously and share nothing.

ADR-0162 §7 required consecutive windows to overlap — "the last *k* episodes of one
window are the first *k* of the next" — and forward-bound "any durable-cursor walk
(ADR-0111 §1) if one is built". ADR-0212 built it, and its §1 rules that no later
pass of a build reading the watermark selects a turn at or below it, which is exactly
what an overlap of *k* ≥ 1 asks for. ADR-0220 §1 rules ADR-0212's clauses the ones
that stand, forgoes §7's overlap for this walk and sets *k* to 0 there; §3 binds this
driver to follow, and §2 accepts the boundary loss that used to buy.

These tests pin the cadence **as a relation between consecutive pages** rather than
as a pass count, because the pass count is what a driver gets right by accident. The
driver does not select turns — ``ObservationStage`` does, from the watermark — so
what is checkable here is when the driver calls it and what the observer was
therefore handed. ``FakeObserver`` records every batch, which is what makes that
checkable at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import chain, pairwise
from typing import TYPE_CHECKING

import pytest
from benchmarks.memory.cases import BenchCase, BenchSession, BenchTurn
from benchmarks.memory.ingest import IngestionSummary, _turns_above_watermark, ingest_case
from benchmarks.memory.wiring import build_harness
from harness_reconcilers import offline_reconciler

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import UnknownConversationError
from ai_assistant.orchestration.conversations import CaptureReport
from ai_assistant.testing import FakeConversationStore, FakeObserver

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from pathlib import Path

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
        batch_size: The page the stage is built with.

    Returns:
        The settings.
    """
    return Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        episode_retention=None,
        observation_batch_size=batch_size,
    )


async def _ingest(
    tmp_path: Path,
    *,
    turns: int,
    batch_size: int,
    capture: Callable[..., Coroutine[object, object, CaptureReport]] | None = None,
) -> tuple[IngestionSummary, list[list[str]]]:
    """Ingest a case of ``turns`` and return its summary and each pass's page.

    Args:
        tmp_path: The test's directory.
        turns: How many utterances to capture.
        batch_size: The page the stage is built with, and the driver paces on.
        capture: Optional replacement for ``lifecycle.capture``, built by a
            ``_failing_*`` helper below. ``None`` captures for real throughout.

    Returns:
        The summary, and one list of episode ids per observation pass in pass order.
        A pass whose page resolved no episode at all never reaches the observer
        (ADR-0212 §5), so it is counted in ``observation_passes`` and absent here.
    """
    settings = _settings(tmp_path, batch_size=batch_size)
    observer = FakeObserver(beliefs=[], max_batch_size=batch_size)
    harness = build_harness(
        settings, data_dir=tmp_path / "case", observer=observer, reconciler=offline_reconciler()
    )
    try:
        if capture is not None:
            harness.lifecycle.capture = capture  # type: ignore[method-assign]
        summary = await ingest_case(harness, _case(turns), batch_size=batch_size)
    finally:
        harness.close()
    return summary, [[record.id for record in batch] for batch in observer.batches]


def _captured_in_order(summary: IngestionSummary, *, turns: int) -> list[str]:
    """Every episode this case stored, in capture order.

    Read off ``evidence_episodes`` rather than off the store: ``_case`` gives turn
    *n* the pointer ``D1:n``, and the join is written at capture time, so the mapping
    is the driver's own record of which turns became episodes and in what order. A
    turn whose episode never landed has no entry and is absent, which is what makes
    this the right expectation for a page listing too.

    Args:
        summary: What ``ingest_case`` returned.
        turns: How many utterances the case carried.

    Returns:
        The episode ids, capture order.
    """
    return [
        episode
        for index in range(1, turns + 1)
        for episode in summary.evidence_episodes.get(f"D1:{index}", ())
    ]


def _failing_episodes(
    harness_store_delete: Callable[[str], Coroutine[object, object, object]],
    real_capture: Callable[..., Coroutine[object, object, CaptureReport]],
    positions: set[int],
) -> Callable[..., Coroutine[object, object, CaptureReport]]:
    """Capture for real, then destroy the episode at each named position.

    The *episode-stage* failure: the turn is appended and holds its ordinal, and
    ``ObservationStage`` passes over it without backfilling (ADR-0074 §5). So the
    page is ``batch_size`` turns and fewer than ``batch_size`` episodes, which is
    where a cadence in turns and a count of episodes come apart.

    Args:
        harness_store_delete: The memory store's ``delete``.
        real_capture: The lifecycle's own ``capture``.
        positions: 1-based capture positions whose episode is destroyed after the
            turn is appended.

    Returns:
        The replacement.
    """
    seen = 0

    async def _capture(conversation_id: str, *, content: str, **kwargs: object) -> CaptureReport:
        """Capture, then destroy this position's episode where it is named.

        Args:
            conversation_id: The conversation.
            content: The user half.
            kwargs: Relayed.

        Returns:
            The real report, or a degraded one whose turn stands and whose episode
            does not.
        """
        nonlocal seen
        seen += 1
        report = await real_capture(conversation_id, content=content, **kwargs)
        if seen not in positions or report.episode_id is None:
            return report
        await harness_store_delete(report.episode_id)
        return CaptureReport(conversation_id=conversation_id, degraded=True)

    return _capture


def _failing_appends(
    real_capture: Callable[..., Coroutine[object, object, CaptureReport]],
    positions: set[int],
) -> Callable[..., Coroutine[object, object, CaptureReport]]:
    """Refuse each named capture before anything is appended.

    The **lost append**, which ``CaptureReport`` reports identically to a lost
    episode (#1075) and which is the one that leaves no turn behind at all.

    Args:
        real_capture: The lifecycle's own ``capture``.
        positions: 1-based capture positions to refuse.

    Returns:
        The replacement.
    """
    seen = 0

    async def _capture(conversation_id: str, *, content: str, **kwargs: object) -> CaptureReport:
        """Refuse this position, or capture for real.

        Args:
            conversation_id: The conversation.
            content: The user half.
            kwargs: Relayed.

        Returns:
            A degraded report whose turn was never recorded, or the real one.
        """
        nonlocal seen
        seen += 1
        if seen in positions:
            return CaptureReport(conversation_id=conversation_id, degraded=True)
        return await real_capture(conversation_id, content=content, **kwargs)

    return _capture


@pytest.mark.parametrize("turns", [1, 5, 6, 7, 12, 13])
async def test_the_pages_tile_the_conversation_once_end_to_end(tmp_path: Path, turns: int) -> None:
    """ADR-0220 §1 as the one property that contains the rest.

    Concatenating the pages in pass order reproduces the conversation's episodes in
    capture order, exactly once each. That is contiguity, disjointness, ordering and
    completeness in a single equality, over turn counts that are a multiple of the
    batch, one short of it, one over it, and below it outright — the remainder shapes
    §3 names, since that is where the replaced clauses differed most.

    An overlap would break it by repeating ids; a dropped page by omitting them; a
    driver that skipped the closing flush by truncating the tail.
    """
    summary, pages = await _ingest(tmp_path, turns=turns, batch_size=6)

    assert list(chain.from_iterable(pages)) == _captured_in_order(summary, turns=turns)
    assert summary.turns_captured == turns
    assert summary.episodes_reobserved == 0


async def test_consecutive_pages_are_disjoint_and_full_until_the_last(
    tmp_path: Path,
) -> None:
    """The relation between two pages, asserted as the relation rather than a count.

    ADR-0162 §7's identity was ``earlier[-k:] == later[:k]``; ADR-0220 §1 replaces it
    with its complement — consecutive pages share no episode at all — and adds that
    every page but the last is a **full** one, because the driver fires at one full
    page in ADR-0212 §3's sense and never before.
    """
    _, pages = await _ingest(tmp_path, turns=14, batch_size=6)

    assert len(pages) == 3
    assert [len(page) for page in pages] == [6, 6, 2]
    for earlier, later in pairwise(pages):
        assert not set(earlier) & set(later)


async def test_a_case_whose_turns_are_not_a_multiple_of_the_batch_ends_on_a_short_page(
    tmp_path: Path,
) -> None:
    """#1237's shape, dissolved rather than answered (ADR-0220 §3).

    The question was where the closing pass may place ADR-0162 §7's carried tail. With
    *k* at 0 there is no carried tail to place: the closing pass reads the page above
    the watermark like every other pass, so it re-reads nothing an earlier pass
    distilled. Against the old tail read the same case re-read ``batch_size -
    remainder`` turns, which is the cost §3 records as falling.
    """
    summary, pages = await _ingest(tmp_path, turns=10, batch_size=6)

    assert [len(page) for page in pages] == [6, 4]
    assert not set(pages[0]) & set(pages[1])
    assert summary.episodes_read == 10, "each turn read exactly once"
    assert summary.episodes_reobserved == 0


async def test_a_case_shorter_than_one_batch_is_still_distilled(tmp_path: Path) -> None:
    """The commonest case, and why the closing flush stays (ADR-0220 §3).

    A LongMemEval haystack is often shorter than one batch outright, so a driver that
    only ever fired at a full page would ingest such a conversation and distil
    nothing from it. The flush is what makes the pass happen, and this is the case it
    exists for.
    """
    summary, pages = await _ingest(tmp_path, turns=4, batch_size=6)

    assert len(pages) == 1
    assert len(pages[0]) == 4
    assert summary.observation_passes == 1


async def test_a_case_of_exactly_one_batch_buys_exactly_one_pass(tmp_path: Path) -> None:
    """The flush must not manufacture a page wholly contained in the one before.

    A driver whose closing condition asked "has anything been captured since the last
    pass" rather than "does the conversation hold turns above its watermark" would end
    every whole-batch case with a spurious second pass over the same episodes — a
    second model call and a duplicate of every proposal. The watermark is what makes
    the condition exact: after the one pass it stands at the conversation's last
    ordinal, so the flush has nothing to do.
    """
    summary, pages = await _ingest(tmp_path, turns=6, batch_size=6)

    assert len(pages) == 1
    assert len(pages[0]) == 6
    assert summary.observation_passes == 1


async def test_a_gap_costs_a_page_an_episode_and_does_not_move_the_boundary(
    tmp_path: Path,
) -> None:
    """The cadence counts turns; a page of turns can hold fewer episodes.

    A turn whose episode no longer resolves still holds its ordinal and is passed over
    without backfilling (ADR-0074 §5), so the page is short of episodes while the
    boundary stays exactly where the ordinals put it. A driver pacing on successful
    captures would slide the boundary by the number of gaps; this one does not,
    because it asks the store rather than counting its own successes.
    """
    settings = _settings(tmp_path, batch_size=6)
    observer = FakeObserver(beliefs=[], max_batch_size=6)
    harness = build_harness(
        settings, data_dir=tmp_path / "case", observer=observer, reconciler=offline_reconciler()
    )
    capture = _failing_episodes(harness.store.delete, harness.lifecycle.capture, {3})
    try:
        harness.lifecycle.capture = capture  # type: ignore[method-assign]
        summary = await ingest_case(harness, _case(12), batch_size=6)
    finally:
        harness.close()

    pages = [[record.id for record in batch] for batch in observer.batches]
    assert [len(page) for page in pages] == [5, 6], "the gap costs the first page an episode"
    assert not set(pages[0]) & set(pages[1]), "and the second page starts above it regardless"
    assert summary.turns_degraded == 1


async def test_a_trailing_unresolved_turn_is_re_read_and_that_is_not_an_overlap(
    tmp_path: Path,
) -> None:
    """ADR-0220 §1's third normative clause, run as it describes itself.

    A page whose highest turns did not resolve advances only to the highest *resolved*
    ordinal (ADR-0212 §5), so the next page begins at the lowest turn of that trailing
    unresolved run and selects it again. That is a re-selected **turn**, and §1 says in
    terms it "is not an overlap in ADR-0162 §7's sense" — the turn carries no episode,
    so the observer is never handed the same episode twice and the pages stay disjoint.

    With a batch of 6 and the sixth turn's episode destroyed, the first page reads
    turns 1 to 6 and resolves five, the watermark stops at 5, and the second page is turns
    6 to 11 - six turns, five episodes, none of them the first page's.
    """
    settings = _settings(tmp_path, batch_size=6)
    observer = FakeObserver(beliefs=[], max_batch_size=6)
    harness = build_harness(
        settings, data_dir=tmp_path / "case", observer=observer, reconciler=offline_reconciler()
    )
    capture = _failing_episodes(harness.store.delete, harness.lifecycle.capture, {6})
    try:
        harness.lifecycle.capture = capture  # type: ignore[method-assign]
        summary = await ingest_case(harness, _case(12), batch_size=6)
    finally:
        harness.close()

    pages = [[record.id for record in batch] for batch in observer.batches]
    assert [len(page) for page in pages] == [5, 5, 1]
    for earlier, later in pairwise(pages):
        assert not set(earlier) & set(later), "a re-read turn with no episode shares nothing"
    assert list(chain.from_iterable(pages)) == _captured_in_order(summary, turns=12)


async def test_a_page_that_resolved_nothing_advances_in_one_pass(tmp_path: Path) -> None:
    """ADR-0212 §5's reason for advancing over a wholly unresolvable page.

    Advancing in one pass rather than one turn at a time is what stops a conversation
    of expired turns becoming a permanent candidate re-reading one dead page. The pass
    is spent and counted, and it reaches no observer at all — there is nothing to hand
    one — so the next page is the six turns after it rather than the same six again.
    """
    settings = _settings(tmp_path, batch_size=6)
    observer = FakeObserver(beliefs=[], max_batch_size=6)
    harness = build_harness(
        settings, data_dir=tmp_path / "case", observer=observer, reconciler=offline_reconciler()
    )
    capture = _failing_episodes(harness.store.delete, harness.lifecycle.capture, {1, 2, 3, 4, 5, 6})
    try:
        harness.lifecycle.capture = capture  # type: ignore[method-assign]
        summary = await ingest_case(harness, _case(12), batch_size=6)
    finally:
        harness.close()

    pages = [[record.id for record in batch] for batch in observer.batches]
    assert summary.observation_passes == 2, "the barren page is a pass, and it is spent"
    assert [len(page) for page in pages] == [6], "and only one pass had anything to show"
    assert summary.turns_degraded == 6


async def test_a_lost_append_holds_the_cadence_back_because_the_ordinal_does_not_move(
    tmp_path: Path,
) -> None:
    """What makes an ordinal cadence observably different from a capture count.

    A **lost append** and a lost **episode** are reported identically — ``degraded``,
    no episode id — and only the second leaves a turn in the conversation (#1075,
    whose title says in terms that a driver's cadence needs the distinction). A driver
    counting its own captures would fire the first pass at capture 6, over a
    conversation holding four turns: a short page against a ``Settings`` bound that
    counts turns, and every later page misaligned by two.

    Reading the store instead, the fifth and sixth captures move nothing, so the first
    page is still a full six turns and falls at capture 8. ADR-0220 §3 requires this
    case kept for exactly that reason.
    """
    settings = _settings(tmp_path, batch_size=6)
    observer = FakeObserver(beliefs=[], max_batch_size=6)
    harness = build_harness(
        settings, data_dir=tmp_path / "case", observer=observer, reconciler=offline_reconciler()
    )
    capture = _failing_appends(harness.lifecycle.capture, {5, 6})
    try:
        harness.lifecycle.capture = capture  # type: ignore[method-assign]
        summary = await ingest_case(harness, _case(12), batch_size=6)
    finally:
        harness.close()

    pages = [[record.id for record in batch] for batch in observer.batches]
    assert [len(page) for page in pages] == [6, 4], "full pages of turns, not of captures"
    assert summary.turns_captured == 10
    assert summary.turns_degraded == 2
    assert list(chain.from_iterable(pages)) == _captured_in_order(summary, turns=12)


async def test_a_run_of_lost_appends_leaves_the_cadence_where_it_was(tmp_path: Path) -> None:
    """A conversation that never moved is never due, however many captures were made.

    Eight refused appends record no turn, so the conversation holds nothing above a
    watermark it does not have and no pass is due. The ninth capture lands, and the
    closing flush is what distils it — one pass over one turn, not the nine a capture
    count would have made due.
    """
    settings = _settings(tmp_path, batch_size=6)
    observer = FakeObserver(beliefs=[], max_batch_size=6)
    harness = build_harness(
        settings, data_dir=tmp_path / "case", observer=observer, reconciler=offline_reconciler()
    )
    capture = _failing_appends(harness.lifecycle.capture, set(range(1, 9)))
    try:
        harness.lifecycle.capture = capture  # type: ignore[method-assign]
        summary = await ingest_case(harness, _case(9), batch_size=6)
    finally:
        harness.close()

    pages = [[record.id for record in batch] for batch in observer.batches]
    assert [len(page) for page in pages] == [1]
    assert summary.observation_passes == 1


async def test_a_batch_of_one_tiles_one_turn_at_a_time(tmp_path: Path) -> None:
    """The boundary value ``Settings`` permits, where the old *k* was 0 already.

    ADR-0162 §7 forwent the overlap at a batch of 1 because no value satisfies
    progress and overlap together there; ADR-0220 §1 forgoes it at every batch, so
    this is no longer the exception — it is the general rule seen at its smallest.
    What it still pins is that the cadence has no off-by-one at the bound: one turn
    above the watermark is one full page, so every capture is due.
    """
    _, pages = await _ingest(tmp_path, turns=3, batch_size=1)

    assert [len(page) for page in pages] == [1, 1, 1]
    for earlier, later in pairwise(pages):
        assert not set(earlier) & set(later)


async def test_the_cadence_refuses_a_conversation_that_is_gone() -> None:
    """``get`` answers ``None`` for absent and for stamped-deleted alike.

    A driver that read that as "no turns above the watermark" would end its case
    silently, reporting a summary for a conversation that is not there. Asserted on
    the canonical fake rather than through a run, because reaching it through
    ``ingest_case`` would mean deleting the conversation mid-case — a state the
    benchmark harness never produces and a test would have to manufacture.
    """
    store = FakeConversationStore()

    with pytest.raises(UnknownConversationError):
        await _turns_above_watermark(store, "conv:nope")


async def test_the_cadence_counts_the_turns_above_the_watermark() -> None:
    """The subtraction itself, over the three positions a watermark can take.

    Absent is ``FIRST_TURN_ORDINAL - 1`` and makes every turn unobserved — never zero
    and never a claim about the turns below anything (ADR-0212 §1). A recorded
    watermark leaves the turns strictly above it. One at the conversation's last
    ordinal leaves none, which is the flush's stopping condition.
    """
    store = FakeConversationStore()
    conversation = await store.start()
    for index in range(5):
        await store.append(conversation.id, occurred_at=FIRST + timedelta(minutes=index))

    assert await _turns_above_watermark(store, conversation.id) == 5
    await store.record_observed(conversation.id, through_ordinal=2)
    assert await _turns_above_watermark(store, conversation.id) == 3
    await store.record_observed(conversation.id, through_ordinal=5)
    assert await _turns_above_watermark(store, conversation.id) == 0
