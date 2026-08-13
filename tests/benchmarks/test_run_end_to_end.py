"""The smoke test, as a test: a whole run over the real stores, with no model call.

This is the harness's plumbing check in the form #1029's ground rule 1 makes safe to
run whenever — a real `SqliteMemoryStore`, a real `ConversationLifecycle` capture, a
real `MemoryIngestor` and policy, a real `SqliteTraceStore`, and the real
`assemble_by_band` retrieval path, with the two model seams replaced by the canonical
fakes. Nothing here is a measurement: the embedder is the hashing one and the answer
is scripted, so the numbers say the wires are connected and nothing else.

What it exists to catch is the class of failure that only appears when everything is
joined up — a capture whose episode the observation window never reaches, a
correlation scope that does not reach the store's trace emitter, a record schema that
cannot serialise what the run produces.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from benchmarks.memory.cases import BenchCase, BenchQuestion, BenchSession, BenchTurn
from benchmarks.memory.corpora.provenance import LOCOMO
from benchmarks.memory.grade import ExactGrader
from benchmarks.memory.records import QuestionRecord, RunManifest, RunMode, read_jsonl
from benchmarks.memory.run import execute_run, plan_run

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ModelUnavailableError
from ai_assistant.core.types import Message, Role
from ai_assistant.testing import FakeModelProvider, FakeObserver

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

pytestmark = pytest.mark.integration

FIRST = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)
BATCH = 2


def _case() -> BenchCase:
    """A two-session case with two questions, one of them unanswerable.

    Returns:
        The case.
    """
    return BenchCase(
        corpus_key="locomo",
        case_key="conv-test",
        sessions=(
            BenchSession(
                session_key="session_1",
                occurred_at=FIRST,
                turns=(
                    BenchTurn(speaker="Ada", text="Ada: I adopted a dog.", user_side=True),
                    BenchTurn(speaker="Bo", text="Bo: What is her name?", user_side=False),
                    BenchTurn(speaker="Ada", text="Ada: Her name is Juno.", user_side=True),
                    BenchTurn(speaker="Bo", text="Bo: Lovely name.", user_side=False),
                ),
            ),
            BenchSession(
                session_key="session_2",
                occurred_at=FIRST + timedelta(days=35),
                turns=(
                    BenchTurn(speaker="Ada", text="Ada: Juno is settling in.", user_side=True),
                    BenchTurn(speaker="Bo", text="Bo: Good to hear.", user_side=False),
                ),
            ),
        ),
        questions=(
            BenchQuestion(
                question_id="conv-test#0",
                category="1",
                question="What did Ada adopt?",
                answer="a dog",
                evidence=("D1:1",),
            ),
            BenchQuestion(
                question_id="conv-test#1",
                category="5",
                question="Did Ada adopt a cat?",
                answer="No such information",
                unanswerable=True,
            ),
        ),
    )


def _settings(tmp_path: Path) -> Settings:
    """Settings a plumbing check may use, and a scored run may not.

    `hashing` keeps ONNX out of the test; `episode_retention=None` keeps the first
    session's episodes alive under the corpus clock across the 35-day gap, which is the
    configuration the CLI warns a real run into.

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


async def _run(tmp_path: Path, *, mode: RunMode = RunMode.SMOKE) -> tuple[RunManifest, Path]:
    """Execute one run over the fixture case.

    Args:
        tmp_path: The test's directory.
        mode: The run mode.

    Returns:
        The manifest and the run's output directory.
    """
    settings = _settings(tmp_path)
    plan = plan_run(LOCOMO, (_case(),), batch_size=BATCH)
    root = tmp_path / "runs"
    manifest = await execute_run(
        plan,
        output_root=root,
        mode=mode,
        corpus_digests={"locomo10.json": "0" * 64},
        settings=settings,
        model=FakeModelProvider("a dog"),
        observer=FakeObserver(max_batch_size=BATCH),
    )
    return manifest, root / manifest.run_id


def test_plan_counts_exchanges_and_passes_without_touching_anything() -> None:
    """Six utterances fold into three exchanges — session 1's four turns pair into
    two, session 2's two into one — and three exchanges at a batch of two is one full
    pass plus a closing partial one."""
    plan = plan_run(LOCOMO, (_case(),), batch_size=BATCH)

    assert plan.turn_count == 3
    assert plan.observation_calls == 2
    assert plan.answer_calls == 2
    assert plan.judge_calls == 1  # the unanswerable one needs no judge call
    assert plan.model_calls == 5


def test_plan_refuses_a_non_positive_batch() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        plan_run(LOCOMO, (_case(),), batch_size=0)


async def test_a_run_writes_a_manifest_naming_its_mode(tmp_path: Path) -> None:
    """ "Has a scored run happened?" is answered by artifacts, not by recollection."""
    manifest, run_dir = await _run(tmp_path)

    written = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert written["mode"] == "smoke"
    assert manifest.mode is RunMode.SMOKE


async def test_the_manifest_records_the_configuration_rather_than_describing_it(
    tmp_path: Path,
) -> None:
    manifest, _ = await _run(tmp_path)

    assert manifest.corpus == "locomo"
    assert manifest.corpus_revision == LOCOMO.revision
    assert manifest.corpus_licence == "CC BY-NC 4.0"
    assert manifest.embedder_kind == "hashing"
    assert manifest.embedder_model_id
    assert manifest.retrieval_limit > 0
    assert manifest.conflict_limit > 0
    assert manifest.episode_retention == "none"
    assert manifest.answer_prompt.startswith("You are answering a question")
    # The offline grader makes no model call, so there is no judge prompt to record.
    assert manifest.judge_prompt is None


async def test_a_run_writes_one_record_per_question(tmp_path: Path) -> None:
    _, run_dir = await _run(tmp_path)

    records = read_jsonl(run_dir / "records.jsonl", QuestionRecord)

    assert [record.question_id for record in records] == ["conv-test#0", "conv-test#1"]


async def test_every_record_carries_its_correlation_id(tmp_path: Path) -> None:
    """The id is what ties an answer to its ADR-0119 traces (P8's linkage)."""
    _, run_dir = await _run(tmp_path)

    records = read_jsonl(run_dir / "records.jsonl", QuestionRecord)

    assert all(record.correlation_id for record in records)
    assert len({record.correlation_id for record in records}) == len(records)


async def test_the_traces_report_the_retrieval_calls_each_answer_made(
    tmp_path: Path,
) -> None:
    """#1029's P4. One to three, because `assemble_by_band` reads band by band and
    stops once the budget is full — and above zero, which is what proves the
    correlation scope actually reaches the store's emitter."""
    _, run_dir = await _run(tmp_path)

    records = read_jsonl(run_dir / "records.jsonl", QuestionRecord)

    for record in records:
        assert 1 <= record.telemetry.search_calls <= 3
        assert record.telemetry.outcomes == ("ok",) * record.telemetry.search_calls
        assert len(record.telemetry.limit) == record.telemetry.search_calls


async def test_the_exclusion_counts_are_the_structural_zeros_the_store_writes(
    tmp_path: Path,
) -> None:
    """Recorded because the day they stop being zero is the day they carry
    information — and because a prediction phrased in terms of them would read zeros
    today (ADR-0128 §1)."""
    _, run_dir = await _run(tmp_path)

    records = read_jsonl(run_dir / "records.jsonl", QuestionRecord)

    for record in records:
        assert set(record.telemetry.exclusions.values()) <= {0}


async def test_ingestion_is_summarised_on_every_record(tmp_path: Path) -> None:
    """Denormalised so a JSONL line can be read on its own."""
    _, run_dir = await _run(tmp_path)

    records = read_jsonl(run_dir / "records.jsonl", QuestionRecord)

    ingestion = records[0].ingestion
    assert ingestion["turns_captured"] == 3
    assert ingestion["turns_degraded"] == 0
    assert ingestion["observation_passes"] == 2
    # The closing window is partial and the read has no offset, so it re-reads one
    # turn the first pass already distilled — counted, not hidden.
    assert ingestion["episodes_read"] == 4
    assert ingestion["episodes_reobserved"] == 1


async def test_beliefs_distilled_from_the_conversation_reach_the_prompt(
    tmp_path: Path,
) -> None:
    """The end-to-end property: capture wrote episodes, observation distilled them
    into the store, and retrieval found them. A run where this is empty is a run
    whose scores would be about an empty memory."""
    _, run_dir = await _run(tmp_path)

    records = read_jsonl(run_dir / "records.jsonl", QuestionRecord)

    assert records[0].retrieved_ids
    assert records[0].context_chars > 0
    assert set(records[0].retrieved_kinds) <= {"semantic", "preference", "procedural"}


async def test_the_answer_reads_only_retrieved_context(tmp_path: Path) -> None:
    """The corpus is not reachable from the answering path; only the record list is."""
    settings = _settings(tmp_path)
    model = FakeModelProvider("a dog")
    plan = plan_run(LOCOMO, (_case(),), batch_size=BATCH)

    await execute_run(
        plan,
        output_root=tmp_path / "runs",
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=settings,
        model=model,
        observer=FakeObserver(max_batch_size=BATCH),
    )

    sent = "\n".join(message.content for message in model.calls[0].messages)
    assert "Bo: Lovely name." not in sent
    assert "Question: What did Ada adopt?" in sent


async def test_the_traces_survive_the_run_and_the_stores_do_not(tmp_path: Path) -> None:
    """`traces.db` is the ADR-0119 record P8's analysis is defined over; `memory.db`
    is thousands of vectors nothing reads afterwards."""
    _, run_dir = await _run(tmp_path)

    case_dir = run_dir / "cases" / "conv-test"
    assert (case_dir / "traces.db").exists()
    assert not (case_dir / "memory.db").exists()
    assert not (case_dir / "conversations.db").exists()


async def test_keeping_the_stores_is_available(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    plan = plan_run(LOCOMO, (_case(),), batch_size=BATCH)
    root = tmp_path / "runs"

    manifest = await execute_run(
        plan,
        output_root=root,
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=settings,
        model=FakeModelProvider("a dog"),
        observer=FakeObserver(max_batch_size=BATCH),
        keep_stores=True,
    )

    assert (root / manifest.run_id / "cases" / "conv-test" / "memory.db").exists()


async def test_a_run_grades_the_unanswerable_question_on_abstention(
    tmp_path: Path,
) -> None:
    """The scripted answer answers, so the abstention question scores incorrect —
    which is the shape #1029's P7 predicts a real run will show."""
    _, run_dir = await _run(tmp_path)

    records = read_jsonl(run_dir / "records.jsonl", QuestionRecord)

    assert records[1].unanswerable is True
    assert records[1].verdict == "incorrect"
    assert records[1].abstained is False


class _FailsOnceProvider:
    """Answers, then fails, then answers — the shape a transient outage has."""

    def __init__(self, *, fail_on: int) -> None:
        """Fail the ``fail_on``-th call (1-based).

        Args:
            fail_on: Which call raises.
        """
        self._fail_on = fail_on
        self.calls = 0

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        """Answer, or raise on the nominated call.

        Args:
            messages: Ignored.
            model: Ignored.

        Returns:
            A fixed reply.

        Raises:
            ModelUnavailableError: On the nominated call.
        """
        self.calls += 1
        if self.calls == self._fail_on:
            raise ModelUnavailableError("provider is down")
        return Message(role=Role.ASSISTANT, content="a dog")


async def test_an_answering_failure_does_not_end_the_run(tmp_path: Path) -> None:
    """Dying at question 400 of a paid 2,000-question run loses the 1,586 after it and
    every later case, which is far worse than one row a reader can exclude."""
    model = _FailsOnceProvider(fail_on=1)
    manifest = await execute_run(
        plan_run(LOCOMO, (_case(),), batch_size=BATCH),
        output_root=tmp_path / "runs",
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=model,
        observer=FakeObserver(max_batch_size=BATCH),
    )

    records = read_jsonl(tmp_path / "runs" / manifest.run_id / "records.jsonl", QuestionRecord)

    assert len(records) == 2
    assert records[0].verdict == "ungraded"
    assert records[0].judge_detail == "answering failed: ModelUnavailableError"
    assert records[1].verdict == "incorrect"


async def test_a_failed_answer_keeps_the_retrieval_it_actually_made(
    tmp_path: Path,
) -> None:
    """Retrieval runs before the provider is called, so its traces already exist when
    the failure lands. Recording zero calls would be a false entry in exactly the field
    P8 is computed from — and the cursor, walking forward, would step past those traces
    permanently. Handling the failure inside the correlation scope is what keeps them
    attributable."""
    manifest = await execute_run(
        plan_run(LOCOMO, (_case(),), batch_size=BATCH),
        output_root=tmp_path / "runs",
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=_FailsOnceProvider(fail_on=1),
        observer=FakeObserver(max_batch_size=BATCH),
    )

    failed = read_jsonl(tmp_path / "runs" / manifest.run_id / "records.jsonl", QuestionRecord)[0]

    assert failed.answer == ""
    assert failed.retrieved_ids
    assert 1 <= failed.telemetry.search_calls <= 3
    assert failed.telemetry.returned_ids


async def test_the_manifest_records_a_session_bound(tmp_path: Path) -> None:
    """A record set that cannot say which bound produced it can be neither reproduced
    nor compared."""
    manifest = await execute_run(
        plan_run(LOCOMO, (_case(),), batch_size=BATCH),
        output_root=tmp_path / "runs",
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=FakeModelProvider("a dog"),
        observer=FakeObserver(max_batch_size=BATCH),
        max_sessions=2,
    )

    assert manifest.max_sessions == 2


async def test_a_whole_history_records_a_zero_bound(tmp_path: Path) -> None:
    manifest, _ = await _run(tmp_path)

    assert manifest.max_sessions == 0


async def test_execute_run_refuses_an_ineligible_scored_run_itself(tmp_path: Path) -> None:
    """The gate lives at the boundary that writes the manifest, not only at the command
    line: this function is exported, and a caller reaching it directly could otherwise
    label an ineligible run `scored`."""
    with pytest.raises(PermissionError):
        await execute_run(
            plan_run(LOCOMO, (_case(),), batch_size=BATCH),
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=_settings(tmp_path),
            model=FakeModelProvider("a dog"),
            observer=FakeObserver(max_batch_size=BATCH),
        )

    assert not (tmp_path / "runs").exists()


async def test_execute_run_refuses_a_scored_run_on_the_hashing_embedder(
    tmp_path: Path,
) -> None:
    """Confirmed, whole histories — and still refused, because `_settings` selects the
    QA embedder and the exact grader."""
    with pytest.raises(ValueError, match="non-semantic"):
        await execute_run(
            plan_run(LOCOMO, (_case(),), batch_size=BATCH),
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=_settings(tmp_path),
            model=FakeModelProvider("a dog"),
            observer=FakeObserver(max_batch_size=BATCH),
            preregistration_final=True,
        )


async def test_execute_run_refuses_a_scored_run_judged_by_the_exact_grader(
    tmp_path: Path,
) -> None:
    """The gate names the grader the harness is about to *build*, not one a caller
    supplied and described — here everything else is eligible and only the judge is
    not."""
    settings = _settings(tmp_path).model_copy(update={"embedder": EmbedderKind.ON_DEVICE})

    with pytest.raises(ValueError, match="LLM judge"):
        await execute_run(
            plan_run(LOCOMO, (_case(),), batch_size=BATCH),
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=settings,
            grader_kind="exact",
            preregistration_final=True,
        )


async def test_execute_run_refuses_a_scored_run_with_an_injected_seam(
    tmp_path: Path,
) -> None:
    """The manifest records the routes the settings name, so a seam supplied by the
    caller makes that record false. This is the one precondition that can be checked
    without trusting anything a caller says: an override is present or it is not — and
    it is what stops a grader that merely *calls itself* a model judge from producing a
    scored artifact."""
    settings = _settings(tmp_path).model_copy(update={"embedder": EmbedderKind.ON_DEVICE})

    with pytest.raises(ValueError, match="injected seam"):
        await execute_run(
            plan_run(LOCOMO, (_case(),), batch_size=BATCH),
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=settings,
            grader_kind="model",
            model=FakeModelProvider("a dog"),
            observer=FakeObserver(max_batch_size=BATCH),
            preregistration_final=True,
        )


async def test_execute_run_names_every_injected_seam_in_its_refusal(
    tmp_path: Path,
) -> None:
    """A refusal naming one of three overrides sends the reader round the loop twice."""
    settings = _settings(tmp_path).model_copy(update={"embedder": EmbedderKind.ON_DEVICE})

    with pytest.raises(ValueError, match="injected seam") as caught:
        await execute_run(
            plan_run(LOCOMO, (_case(),), batch_size=BATCH),
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=settings,
            grader_kind="model",
            grader=ExactGrader(),
            model=FakeModelProvider("a dog"),
            observer=FakeObserver(max_batch_size=BATCH),
            preregistration_final=True,
        )

    assert "grader, model, observer" in str(caught.value)
