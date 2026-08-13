"""#848's caveat, pinned at the limits a pilot retrieval actually uses.

ADR-0119 §3 caps a trace's ``records`` set at :data:`TRACE_RECORD_SET_CAP` ids and
**declares** the truncation; §4 then rules that a measure needing *record identity*
excludes such a trace from its population rather than reading a partial list as
complete. P8 is exactly such a measure — the whole split turns on which record ids came
back — so P8 is measurable only while the pilot's retrievals stay under the cap.

**This is not a fix of #848 and does not close it.** #848 fires the day a traced call
site reads more than 256 records; what is asserted here is that the call sites this
harness drives do not, and that the identity they carry is in fact complete. If a future
change raises a bound past the cap, the static half below fails here — in a test that
names P8 — rather than silently in an analysis months later.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from benchmarks.memory.answer import answer_question
from benchmarks.memory.cases import BenchCase, BenchQuestion, BenchSession, BenchTurn
from benchmarks.memory.ingest import ingest_case
from benchmarks.memory.wiring import build_harness

from ai_assistant.app.composition import CONFLICT_LIMIT, RETRIEVAL_LIMIT
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import TRACE_RECORD_SET_CAP, TraceKind, TraceRecordSet
from ai_assistant.testing import FakeModelProvider, FakeObserver

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.types import EvaluationTrace

pytestmark = pytest.mark.integration

FIRST = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)
BATCH = 2


def test_the_pilot_reads_far_below_the_cap_that_would_cost_it_record_identity() -> None:
    """The two bounds a benchmark run retrieves under, both from the composition root:
    the per-band budget `assemble_by_band` fills, and the ingestor's conflict probe.
    Neither may reach the cap, or P8's population starts shrinking silently."""
    assert RETRIEVAL_LIMIT < TRACE_RECORD_SET_CAP
    assert CONFLICT_LIMIT < TRACE_RECORD_SET_CAP


def _case() -> BenchCase:
    """A case long enough to fill several observation passes and a retrieval budget.

    Returns:
        The case.
    """
    turns = tuple(
        BenchTurn(
            speaker="Ada" if index % 2 == 0 else "Bo",
            text=f"{'Ada' if index % 2 == 0 else 'Bo'}: line {index} about the dog Juno.",
            user_side=index % 2 == 0,
            evidence_key=f"D1:{index}",
        )
        for index in range(12)
    )
    return BenchCase(
        corpus_key="locomo",
        case_key="trace-identity",
        sessions=(BenchSession(session_key="session_1", occurred_at=FIRST, turns=turns),),
        questions=(
            BenchQuestion(
                question_id="trace-identity#0",
                category="1",
                question="What is the dog called?",
                answer="Juno",
                evidence=("D1:0",),
            ),
        ),
    )


async def _retrieval_traces(tmp_path: Path) -> tuple[tuple[EvaluationTrace, ...], tuple[str, ...]]:
    """Ingest and answer once, then read back every ``RETRIEVAL`` trace the run emitted.

    The whole stream is read rather than one answer's scope: the conflict probe's reads
    happen during *ingestion* and are the call site with the larger bound, so a check
    scoped to the answer would test the smaller of the two limits and miss the one
    nearer the cap.

    Args:
        tmp_path: The test's directory.

    Returns:
        Every ``RETRIEVAL`` trace, and the ids the answering prompt was built from.
    """
    settings = Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        episode_retention=None,
        observation_batch_size=BATCH,
    )
    case = _case()
    harness = build_harness(
        settings,
        data_dir=tmp_path / "case",
        model=FakeModelProvider("Juno"),
        observer=FakeObserver(max_batch_size=BATCH),
    )
    try:
        await ingest_case(harness, case, batch_size=BATCH)
        attempt = await answer_question(harness, case.questions[0])
        collected: list[EvaluationTrace] = []
        position = None
        while True:
            chunk = await harness.traces.walk(after=position, limit=500)
            position = chunk.position
            if not chunk.traces:
                break
            collected.extend(chunk.traces)
    finally:
        harness.close()
    return (
        tuple(trace for trace in collected if trace.kind is TraceKind.RETRIEVAL),
        attempt.retrieved_ids,
    )


async def test_every_retrieval_trace_carries_its_returned_ids_whole(tmp_path: Path) -> None:
    """Truncated exactly when `total` exceeds `len(ids)` — there is no separate flag to
    disagree with — so a complete set is the observed half of #848's "it is zero today"."""
    traces, _ = await _retrieval_traces(tmp_path)

    assert traces
    for trace in traces:
        returned = trace.records.get(TraceRecordSet.RETURNED)
        assert returned is not None
        assert len(returned.ids) == returned.total
        assert returned.total <= TRACE_RECORD_SET_CAP


async def test_the_records_the_prompt_was_built_from_are_named_in_the_traces(
    tmp_path: Path,
) -> None:
    """Record *identity*, not a count: P8 asks which records came back, so a trace whose
    ids did not cover what reached the prompt would leave the split unanswerable even
    with nothing truncated."""
    traces, retrieved = await _retrieval_traces(tmp_path)

    named = {
        identifier
        for trace in traces
        if (returned := trace.records.get(TraceRecordSet.RETURNED)) is not None
        for identifier in returned.ids
    }
    assert retrieved
    assert set(retrieved) <= named
