"""Compose the harness into a run, and write down what it did.

**A run is planned before it is executed, and the plan costs nothing.**
:func:`plan_run` reports how many cases, how many questions and — the figure that
actually decides whether to press go — how many model calls the run will make, split
by what makes them. It contacts no provider and opens no store. #1029 budgets the
pilot in dollars, and the arithmetic behind those dollars should be visible before
the money is spent rather than inferred afterwards.

**Ingestion dominates, and the plan is where that becomes obvious.** Answering makes
one call per question; distillation makes one per twenty captured turns. On LoCoMo
that is ~1,986 answering calls against ~294 observation calls over ~5,880 turns — but
the observation calls carry twenty turns of transcript each, so the token cost does
not follow the call count. The plan reports both figures and asserts nothing about
their price, which is a vendor's number and not the harness's to guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from ai_assistant.app.composition import CONFLICT_LIMIT, RETRIEVAL_LIMIT
from ai_assistant.core.config import Settings
from benchmarks.memory.answer import ANSWER_SYSTEM_PROMPT, answer_question
from benchmarks.memory.grade import JUDGE_PROMPT, ExactGrader, ModelGrader
from benchmarks.memory.ingest import exchanges_of, ingest_case
from benchmarks.memory.records import (
    QuestionRecord,
    RunManifest,
    RunMode,
    TraceCursor,
    now_iso,
    write_jsonl_line,
)
from benchmarks.memory.wiring import build_embedder, build_harness, build_model_provider

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import ModelProvider, Observer
    from benchmarks.memory.cases import BenchCase
    from benchmarks.memory.corpora.provenance import Corpus
    from benchmarks.memory.grade import Grader

__all__ = [
    "DEFAULT_RUNS_DIR",
    "PREREGISTRATION_REFUSAL",
    "RunPlan",
    "build_grader",
    "execute_run",
    "plan_run",
    "refuse_unconfirmed_scored_run",
]

#: Why a scored run is refused without an explicit confirmation.
#:
#: The wording names the rule rather than the flag, because someone who hits this and
#: does not know what it is about should be sent to #1029 rather than to the argument
#: that silences it.
PREREGISTRATION_REFUSAL = (
    "A scored run is refused. Issue #1029 ground rule 1: the pre-registration is "
    "finalised by the owner before any scored evaluation, and until then only smoke "
    "runs are permitted and their outputs are not read as scores. If the "
    "pre-registration is final, re-run with --preregistration-final."
)

#: Where runs are written, beside the harness and ignored by git.
DEFAULT_RUNS_DIR = "runs"


@dataclass(frozen=True, slots=True)
class RunPlan:
    """What a run would do, computed without contacting anything.

    Attributes:
        corpus: The corpus.
        cases: The cases selected.
        question_count: Questions across those cases.
        turn_count: Exchanges capture would record.
        observation_calls: Model calls distillation would make — one per full batch
            of captured turns per case, plus one for each case's remainder.
        answer_calls: Model calls answering would make — one per question.
        judge_calls: Model calls grading would make, at most. Abstentions and
            unanswerable questions are graded without a call, so the true number is
            at or below this.
    """

    corpus: Corpus
    cases: tuple[BenchCase, ...]
    question_count: int
    turn_count: int
    observation_calls: int
    answer_calls: int
    judge_calls: int

    @property
    def model_calls(self) -> int:
        """The upper bound on model calls the run would make."""
        return self.observation_calls + self.answer_calls + self.judge_calls


def plan_run(corpus: Corpus, cases: Sequence[BenchCase], *, batch_size: int) -> RunPlan:
    """Compute what running these cases would cost, without running anything.

    Args:
        corpus: The corpus the cases came from.
        cases: The cases selected.
        batch_size: The observation batch size the run would use.

    Returns:
        The plan.

    Raises:
        ValueError: If ``batch_size`` is not positive.
    """
    if batch_size < 1:
        msg = f"batch_size must be positive, got {batch_size}"
        raise ValueError(msg)
    turns = 0
    observations = 0
    questions = 0
    judged = 0
    for case in cases:
        case_turns = sum(len(exchanges_of(session)) for session in case.sessions)
        turns += case_turns
        # One pass per full batch, and one more for the remainder — which is what the
        # driver does, so the figure is the driver's behaviour rather than a model of
        # it. A case with no turns contributes no pass.
        observations += case_turns // batch_size + (1 if case_turns % batch_size else 0)
        questions += len(case.questions)
        judged += sum(1 for question in case.questions if not question.unanswerable)
    return RunPlan(
        corpus=corpus,
        cases=tuple(cases),
        question_count=questions,
        turn_count=turns,
        observation_calls=observations,
        answer_calls=questions,
        judge_calls=judged,
    )


async def execute_run(  # noqa: PLR0913 — every parameter is a distinct axis of the experiment, and bundling them into a config object would hide which ones a caller left at a default
    plan: RunPlan,
    *,
    output_root: Path,
    mode: RunMode,
    corpus_digests: dict[str, str],
    settings: Settings | None = None,
    grader: Grader | None = None,
    model: ModelProvider | None = None,
    observer: Observer | None = None,
    slice_seed: int | None = None,
    notes: str = "",
    keep_stores: bool = False,
) -> RunManifest:
    """Run the plan, writing a manifest and one JSONL record per question.

    Each case gets its own data directory and its own harness: a benchmark case is a
    whole memory, and two cases sharing a store would let one case's beliefs answer
    another's questions. The stores are removed after each case unless asked for,
    because a LoCoMo case's ``memory.db`` carries thousands of vectors and ten of them
    is a lot of disk for something nothing reads. ``traces.db`` is always kept: it is
    the ADR-0119 record P8's analysis is defined over, and it is small.

    Args:
        plan: What to run.
        output_root: Where run directories are created.
        mode: Whether these outputs may be read as scores.
        corpus_digests: Each fetched file's name mapped to its SHA-256, for the
            manifest.
        settings: Loaded application settings; loaded from the environment when
            ``None``.
        grader: How to judge. Defaults to :class:`~benchmarks.memory.grade.ExactGrader`,
            which makes no model call — a default a scored run overrides deliberately.
        model: Override the answering seam. Tests supply one; a live run does not.
        observer: Override the distillation seam, likewise.
        slice_seed: The seed a stratified slice was drawn with, for the manifest.
        notes: Attached to the manifest.
        keep_stores: Keep every case's databases rather than only its traces.

    Returns:
        The manifest, already written to ``<output_root>/<run_id>/manifest.json``.
    """
    resolved = settings if settings is not None else Settings()
    judge = grader if grader is not None else ExactGrader()
    run_id = uuid4().hex[:12]
    run_dir = output_root / run_id
    records_path = run_dir / "records.jsonl"

    manifest = RunManifest(
        run_id=run_id,
        mode=mode,
        started_at=now_iso(),
        corpus=plan.corpus.key,
        corpus_title=plan.corpus.title,
        corpus_revision=plan.corpus.revision,
        corpus_licence=plan.corpus.licence,
        corpus_files=corpus_digests,
        case_count=len(plan.cases),
        question_count=plan.question_count,
        slice_seed=slice_seed,
        answer_route=resolved.default_model,
        observer_route=(
            resolved.observer_model
            if resolved.observer_model is not None
            else resolved.default_model
        ),
        judge=judge.name,
        embedder_kind=str(resolved.embedder),
        # Built once here rather than read off a case's harness, so the manifest is
        # written before any case runs — an interrupted run still says what it was.
        embedder_model_id=build_embedder(resolved).model_id,
        retrieval_limit=RETRIEVAL_LIMIT,
        conflict_limit=CONFLICT_LIMIT,
        observation_batch_size=resolved.observation_batch_size,
        observation_max_proposals=resolved.observation_max_proposals,
        episode_retention=(
            "none" if resolved.episode_retention is None else str(resolved.episode_retention)
        ),
        answer_prompt=ANSWER_SYSTEM_PROMPT,
        judge_prompt=JUDGE_PROMPT if isinstance(judge, ModelGrader) else None,
        notes=notes,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(manifest.model_dump_json(indent=1), encoding="utf-8")

    for case in plan.cases:
        case_dir = run_dir / "cases" / case.case_key.replace("/", "_")
        harness = build_harness(resolved, data_dir=case_dir, model=model, observer=observer)
        try:
            summary = await ingest_case(harness, case, batch_size=resolved.observation_batch_size)
            ingestion: dict[str, int | str | list[str]] = {
                "conversation_id": summary.conversation_id,
                "turns_captured": summary.turns_captured,
                "turns_degraded": summary.turns_degraded,
                "assistant_led_turns": summary.assistant_led_turns,
                "observation_passes": summary.observation_passes,
                "episodes_read": summary.episodes_read,
                "episodes_reobserved": summary.episodes_reobserved,
                "proposals": summary.proposals,
                "discarded_unusable": summary.discarded_unusable,
                "discarded_over_limit": summary.discarded_over_limit,
                "dropped_unsupported": summary.dropped_unsupported,
                "observation_routes": sorted(summary.observation_routes),
            }
            cursor = TraceCursor(harness.traces)
            for question in case.questions:
                attempt = await answer_question(harness, question)
                grading = await judge.grade(question, attempt.answer)
                write_jsonl_line(
                    records_path,
                    QuestionRecord(
                        run_id=run_id,
                        corpus=case.corpus_key,
                        case_key=case.case_key,
                        question_id=question.question_id,
                        category=question.category,
                        unanswerable=question.unanswerable,
                        question=question.question,
                        reference_answer=question.answer,
                        answer=attempt.answer,
                        verdict=str(grading.verdict),
                        abstained=grading.abstained,
                        judge=grading.judge,
                        judge_detail=grading.detail,
                        correlation_id=attempt.correlation_id,
                        retrieved_ids=attempt.retrieved_ids,
                        retrieved_kinds=attempt.retrieved_kinds,
                        evidence=question.evidence,
                        telemetry=await cursor.collect(attempt.correlation_id),
                        asked_at=attempt.asked_at,
                        context_chars=len(attempt.context),
                        ingestion=ingestion,
                    ),
                )
        finally:
            harness.close()
        if not keep_stores:
            for name in ("memory.db", "conversations.db", "deferrals.db"):
                (case_dir / name).unlink(missing_ok=True)
    return manifest


def refuse_unconfirmed_scored_run(mode: RunMode, *, preregistration_final: bool) -> None:
    """Refuse a scored run that has not confirmed #1029's ground rule 1.

    Args:
        mode: The mode asked for.
        preregistration_final: Whether the operator stated the pre-registration is
            final.

    Raises:
        PermissionError: If a scored run was asked for without that statement. The
            class is chosen for what it reads as at a terminal — this is a refusal on
            a rule, not a bad argument — and nothing catches it.
    """
    if mode is RunMode.SCORED and not preregistration_final:
        raise PermissionError(PREREGISTRATION_REFUSAL)


def build_grader(settings: Settings, *, kind: str) -> Grader:
    """Build the grader named by ``kind``.

    Args:
        settings: Loaded application settings.
        kind: ``"exact"`` or ``"model"``.

    Returns:
        The grader.

    Raises:
        ValueError: If ``kind`` names neither.
    """
    if kind == "exact":
        return ExactGrader()
    if kind == "model":
        route = settings.default_model
        return ModelGrader(build_model_provider(settings, route), route=route)
    msg = f"unknown grader {kind!r}; expected 'exact' or 'model'"
    raise ValueError(msg)
