"""#1074: the join that makes P8's split computable from the retained artifacts.

A question's ``evidence`` is a **corpus** pointer — a LoCoMo ``dia_id``, a LongMemEval
session id — and a retrieval returns **generated** record ids. Nothing retained mapped
one to the other, and the episodes that carry the link live in a ``memory.db`` a default
run deletes, so "the evidence was retrieved and the reader failed" could not be told
from "the evidence was never retrieved" without a run someone had thought to pass
``--keep-stores`` on.

These tests pin both halves of the fix and the seam between them: ingestion records
which captured episode each corpus pointer became, the answer records which episodes
each retrieved belief cites, and a record carries enough of both to decide the split
with nothing but ``records.jsonl`` open.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from benchmarks.memory.cases import BenchCase, BenchQuestion, BenchSession, BenchTurn
from benchmarks.memory.corpora.provenance import LOCOMO
from benchmarks.memory.ingest import ingest_case
from benchmarks.memory.records import QuestionRecord, RunMode, read_jsonl
from benchmarks.memory.run import case_dir_name, execute_run, plan_run
from benchmarks.memory.wiring import build_harness

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.orchestration.conversations import CaptureReport
from ai_assistant.testing import FakeModelProvider, FakeObserver

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

FIRST = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)

#: One exchange per observation pass. The case below folds to a single exchange, so a
#: batch of one makes the whole run deterministic: one episode, one belief, and a
#: retrieval budget of five over a store holding one record returns it.
BATCH = 1

#: A pointer no turn in the case carries — the corpus citing a turn this run never
#: ingested, which is what ``--max-sessions`` produces at scale.
UNINGESTED = "D9:9"


def _case() -> BenchCase:
    """A one-exchange case whose two turns are keyed and whose questions cite them.

    Returns:
        The case.
    """
    return BenchCase(
        corpus_key="locomo",
        case_key="join-test",
        sessions=(
            BenchSession(
                session_key="session_1",
                occurred_at=FIRST,
                turns=(
                    BenchTurn(
                        speaker="Ada",
                        text="Ada: I adopted a dog.",
                        user_side=True,
                        evidence_key="D1:1",
                    ),
                    BenchTurn(
                        speaker="Bo",
                        text="Bo: What is her name?",
                        user_side=False,
                        evidence_key="D1:2",
                    ),
                ),
            ),
        ),
        questions=(
            BenchQuestion(
                question_id="join-test#0",
                category="1",
                question="What did Ada adopt?",
                answer="a dog",
                evidence=("D1:1",),
            ),
            BenchQuestion(
                question_id="join-test#1",
                category="1",
                question="What did Ada cook?",
                answer="nothing",
                evidence=(UNINGESTED,),
            ),
        ),
    )


def _settings(tmp_path: Path) -> Settings:
    """Settings a plumbing check may use, and a scored run may not.

    Args:
        tmp_path: The test's directory.

    Returns:
        The settings.
    """
    return Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        episode_retention=None,
        observation_batch_size=BATCH,
    )


async def _records(tmp_path: Path) -> tuple[tuple[QuestionRecord, ...], Path]:
    """Run the case and read its records back.

    Args:
        tmp_path: The test's directory.

    Returns:
        The records in file order, and the run directory.
    """
    root = tmp_path / "runs"
    manifest = await execute_run(
        plan_run(LOCOMO, (_case(),), batch_size=BATCH),
        output_root=root,
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=FakeModelProvider("a cat"),
        observer=FakeObserver(max_batch_size=BATCH),
    )
    run_dir = root / manifest.run_id
    return read_jsonl(run_dir / "records.jsonl", QuestionRecord), run_dir


async def test_ingestion_maps_every_pointer_of_an_exchange_to_the_episode_it_became(
    tmp_path: Path,
) -> None:
    """The fold is many-to-one, so both cited turns name the one episode they became.
    Capture is the only moment both a corpus pointer and an episode id are in hand."""
    harness = build_harness(
        _settings(tmp_path),
        data_dir=tmp_path / "case",
        model=FakeModelProvider("x"),
        observer=FakeObserver(max_batch_size=BATCH),
    )
    try:
        summary = await ingest_case(harness, _case(), batch_size=BATCH)
    finally:
        harness.close()

    assert summary.turns_captured == 1
    assert sorted(summary.evidence_episodes) == ["D1:1", "D1:2"]
    episodes = {tuple(ids) for ids in summary.evidence_episodes.values()}
    assert len(episodes) == 1  # one exchange, one episode, both pointers on it
    assert all(len(ids) == 1 for ids in summary.evidence_episodes.values())
    assert summary.evidence_keys_captured == 2


async def test_a_degraded_capture_leaves_its_pointers_unmapped(tmp_path: Path) -> None:
    """An entry mapping a pointer to nothing would read as "retrieved nothing" when the
    truth is "was never stored", so a capture that reported degraded contributes none —
    and `evidence_keys_captured` is then the zero that says the split is *missing*."""
    harness = build_harness(
        _settings(tmp_path),
        data_dir=tmp_path / "case",
        model=FakeModelProvider("x"),
        observer=FakeObserver(max_batch_size=BATCH),
    )
    real_capture = harness.lifecycle.capture

    async def _capture(conversation_id: str, *, content: str, **kwargs: object) -> CaptureReport:
        """Capture for real, then fail the episode the way the store failing would.

        Args:
            conversation_id: The conversation.
            content: The user half.
            kwargs: Relayed.

        Returns:
            A degraded report.
        """
        report = await real_capture(conversation_id, content=content, **kwargs)  # type: ignore[arg-type]
        if report.episode_id is None:
            return report
        await harness.store.delete(report.episode_id)
        return CaptureReport(conversation_id=conversation_id, degraded=True)

    try:
        harness.lifecycle.capture = _capture  # type: ignore[method-assign]
        summary = await ingest_case(harness, _case(), batch_size=BATCH)
    finally:
        harness.close()

    assert summary.turns_degraded == 1
    assert summary.evidence_episodes == {}
    assert summary.evidence_keys_captured == 0


async def test_a_record_carries_the_episodes_its_own_pointers_became(tmp_path: Path) -> None:
    """Aligned with `evidence`, and only this question's pointers: the case's whole
    mapping is thousands of entries wide on a real LoCoMo dialogue and would be
    denormalised onto all ~199 of its records."""
    records, _ = await _records(tmp_path)
    cited = records[0]

    assert cited.evidence == ("D1:1",)
    assert len(cited.evidence_episode_ids) == len(cited.evidence)
    assert len(cited.evidence_episode_ids[0]) == 1
    assert cited.ingestion["evidence_keys_captured"] == 2


async def test_a_pointer_this_run_never_ingested_maps_to_nothing(tmp_path: Path) -> None:
    """An empty tuple is "never became an episode" — a turn outside the ingested slice,
    a degraded capture, or a corpus turn with no pointer. It is not "never retrieved",
    and `evidence_keys_captured` is what tells a reader which they are looking at."""
    records, _ = await _records(tmp_path)
    uncited = records[1]

    assert uncited.evidence == (UNINGESTED,)
    assert uncited.evidence_episode_ids == ((),)
    assert uncited.ingestion["evidence_keys_captured"] == 2


async def test_every_retrieved_record_carries_the_episodes_it_cites(tmp_path: Path) -> None:
    """The retrieval half of the join, aligned with `retrieved_ids` so a wrong answer
    can be attributed record by record rather than in aggregate."""
    records, _ = await _records(tmp_path)
    cited = records[0]

    assert cited.retrieved_ids
    assert len(cited.retrieved_evidence) == len(cited.retrieved_ids)
    assert len(cited.retrieved_evidence_elided) == len(cited.retrieved_ids)
    # Nothing has been folded or displaced in a run this short, so every belief still
    # carries every citation it was written with — which is what makes the intersection
    # below decisive rather than merely suggestive (ADR-0086 §4).
    assert set(cited.retrieved_evidence_elided) == {0}
    assert any(cited.retrieved_evidence)


async def test_the_split_is_decidable_from_the_records_with_the_stores_deleted(
    tmp_path: Path,
) -> None:
    """#1074's whole point. The evidence episode appears among the episodes a retrieved
    belief cites, so this answer is "retrieved, and the reader failed" — and the reading
    is made with `memory.db` and `conversations.db` already gone, which is what "no
    `--keep-stores` required" means."""
    records, run_dir = await _records(tmp_path)
    cited = records[0]

    case_dir = run_dir / "cases" / case_dir_name("join-test")
    assert not (case_dir / "memory.db").exists()
    assert not (case_dir / "conversations.db").exists()

    wanted = {episode for pointers in cited.evidence_episode_ids for episode in pointers}
    in_context = {episode for cites in cited.retrieved_evidence for episode in cites}
    assert wanted
    assert wanted <= in_context

    # And the other arm is reachable from the same two fields, without a third input:
    # a question whose evidence maps to nothing intersects nothing.
    uncited = records[1]
    assert not {episode for pointers in uncited.evidence_episode_ids for episode in pointers}
