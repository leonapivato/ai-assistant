"""#1029's third backlog cross-check: what becomes of an ``ASK_USER`` ruling here.

Benchmark ingestion is **headless**. A proposal the memory policy rules ``ASK_USER`` on
raises a question that is parked in a durable queue nobody will ever read, and nothing
is written for it — so a belief the observer proposed, and that a real user would
plausibly have confirmed, is absent from the store and no retrieval can find it. That is
a property of the *harness*, not of the pipeline the pilot is measuring, and it depresses
#1029's P3 and P5 without leaving a mark.

**The declared disposition is: counted, and never answered.** Auto-resolution was
considered and rejected — the harness would then be ruling on proposals it also produced,
which is the separation ADR-0005 §3 exists for, and any answering rule would be a policy
change whose effect would be reported as a result of the pilot. So the artifact is
measured instead of removed, and every record carries the case's ask rate beside its
other ingestion figures.

The tests drive the **real** ``DefaultMemoryPolicy`` through the real write stage: an
observer that proposes secret-tier content is the one arm of that policy an injected
producer can reach, and it is a real ``ASK_USER``, not a simulated one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from benchmarks.memory.cases import BenchCase, BenchQuestion, BenchSession, BenchTurn
from benchmarks.memory.corpora.provenance import LOCOMO
from benchmarks.memory.ingest import IngestionSummary, ingest_case
from benchmarks.memory.records import QuestionRecord, RunMode, read_jsonl
from benchmarks.memory.run import execute_run, plan_run
from benchmarks.memory.wiring import build_harness

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    DataTier,
    MemorySource,
    MemoryUpdateProposal,
    ObservationOutcome,
    Provenance,
    SemanticMemory,
)
from ai_assistant.testing import FakeModelProvider, FakeObserver

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ai_assistant.core.types import EpisodicMemory

pytestmark = pytest.mark.integration

FIRST = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)
BATCH = 1


class _SecretObserver:
    """An ``Observer`` proposing one secret-tier belief per batch.

    Structurally implements :class:`~ai_assistant.core.protocols.Observer`. It exists
    because :class:`~ai_assistant.testing.FakeObserver` scripts everything about a
    proposal *except* its ``sensitivity``, and secret tier is the ``ASK_USER`` arm of
    ``DefaultMemoryPolicy`` a producer can reach without a user-asserted record in the
    store — which benchmark ingestion, whose every belief is derived, never has.

    Citations are drawn from the batch, as a conforming producer's are: a proposal
    citing anything else is refused by the observation stage before a policy sees it.
    """

    def __init__(self, *, max_batch_size: int = BATCH) -> None:
        """Create the observer.

        Args:
            max_batch_size: The largest batch it accepts.
        """
        self.max_batch_size = max_batch_size
        self.max_proposals = 1

    async def observe(self, episodes: Sequence[EpisodicMemory]) -> ObservationOutcome:
        """Propose one secret-tier belief over the batch.

        Args:
            episodes: The batch.

        Returns:
            The outcome; empty for an empty batch, which proposes nothing.
        """
        batch = tuple(episodes)
        if not batch:
            return ObservationOutcome()
        return ObservationOutcome(
            proposals=(
                MemoryUpdateProposal(
                    proposed=SemanticMemory(
                        id=f"secret-{batch[0].id}",
                        content="the passphrase was mentioned",
                        fact="the passphrase was mentioned",
                        provenance=Provenance(
                            source=MemorySource.OBSERVED,
                            confidence=0.6,
                            evidence=(batch[0].id,),
                            last_updated=FIRST,
                            last_confirmed_at=batch[0].occurred_at,
                        ),
                    ),
                    rationale="the batch mentions something secret",
                    sensitivity=DataTier.SECRET,
                ),
            ),
        )


def _case(case_key: str = "ask-test") -> BenchCase:
    """A one-exchange case.

    Args:
        case_key: The case key.

    Returns:
        The case.
    """
    return BenchCase(
        corpus_key="locomo",
        case_key=case_key,
        sessions=(
            BenchSession(
                session_key="session_1",
                occurred_at=FIRST,
                turns=(
                    BenchTurn(
                        speaker="Ada",
                        text="Ada: the passphrase is hunter2.",
                        user_side=True,
                        evidence_key="D1:1",
                    ),
                    BenchTurn(
                        speaker="Bo",
                        text="Bo: noted.",
                        user_side=False,
                        evidence_key="D1:2",
                    ),
                ),
            ),
        ),
        questions=(
            BenchQuestion(
                question_id=f"{case_key}#0",
                category="1",
                question="What is the passphrase?",
                answer="hunter2",
                evidence=("D1:1",),
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


async def test_an_ask_user_ruling_is_counted_rather_than_dropped(tmp_path: Path) -> None:
    """The count exists because the alternative is a belief that silently never lands:
    nothing is written for a deferral, so retrieval cannot find it and P3/P5 fall with
    no evidence of why."""
    harness = build_harness(
        _settings(tmp_path),
        data_dir=tmp_path / "case",
        model=FakeModelProvider("x"),
        observer=_SecretObserver(),
    )
    try:
        summary = await ingest_case(harness, _case(), batch_size=BATCH)
    finally:
        harness.close()

    assert summary.proposals == 1
    assert summary.proposals_deferred == 1
    assert summary.ask_rate == pytest.approx(1.0)


async def test_a_run_that_asks_nothing_reports_a_zero_ask_rate(tmp_path: Path) -> None:
    """The reading that makes the measure worth having: an ask rate of zero is what
    lets a depressed P3/P5 be charged to retrieval rather than to the harness."""
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

    assert summary.proposals
    assert summary.proposals_deferred == 0
    assert summary.ask_rate == pytest.approx(0.0)


def test_the_rate_is_over_proposals_a_policy_actually_ruled_on() -> None:
    """A proposal the write path refused for unresolved evidence (ADR-0077 §5) never
    reached a policy, so it was never eligible to be deferred. Leaving it in the
    denominator would understate the ask rate by exactly the amount the run was already
    degraded — the two artifacts would mask each other."""
    summary = IngestionSummary(
        conversation_id="c", proposals=10, dropped_unsupported=6, proposals_deferred=2
    )

    assert summary.proposals_ruled == 4
    assert summary.ask_rate == pytest.approx(0.5)


def test_an_empty_population_reports_zero_rather_than_dividing() -> None:
    """A case that proposed nothing did not ask anything either."""
    summary = IngestionSummary(conversation_id="c")

    assert summary.proposals_ruled == 0
    assert summary.ask_rate == pytest.approx(0.0)


async def test_every_record_reports_the_ask_rate_beside_the_run(tmp_path: Path) -> None:
    """ "Alongside the run's records" literally: the figure is in `records.jsonl`, so an
    analysis reading the artifacts sees the harness artifact without being told to look
    for it. It is not an aggregate ground rule 1 forbids — it says nothing about whether
    an answer was right."""
    root = tmp_path / "runs"
    manifest = await execute_run(
        plan_run(LOCOMO, (_case(),), batch_size=BATCH),
        output_root=root,
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=FakeModelProvider("hunter2"),
        observer=_SecretObserver(),
    )

    records = read_jsonl(root / manifest.run_id / "records.jsonl", QuestionRecord)

    assert records
    for record in records:
        assert record.ingestion["proposals_deferred"] == 1
        assert record.ingestion["proposals_ruled"] == 1
        assert record.ingestion["ask_rate"] == pytest.approx(1.0)
