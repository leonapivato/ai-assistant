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

import re
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import uuid4

from ai_assistant.app.composition import CONFLICT_LIMIT, RETRIEVAL_LIMIT
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.models import ensure_credential_available, ensure_vendor_available
from benchmarks.memory.answer import ANSWER_SYSTEM_PROMPT, answer_question
from benchmarks.memory.grade import JUDGE_PROMPT, ExactGrader, Grading, ModelGrader, Verdict
from benchmarks.memory.ingest import exchanges_of, ingest_case
from benchmarks.memory.records import (
    QuestionRecord,
    RunManifest,
    RunMode,
    TraceCursor,
    now_iso,
    write_jsonl_line,
)
from benchmarks.memory.select import CaseSelection
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
    "case_dir_name",
    "check_credentials_for",
    "execute_run",
    "plan_run",
    "refuse_ineligible_scored_run",
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

#: Everything a case directory name does not keep verbatim.
_UNSAFE_IN_DIR_NAME = re.compile(r"[^A-Za-z0-9._-]")

#: How much of the sanitised key survives into a case directory name.
_DIR_NAME_PREFIX_CHARS = 64

#: How much of the key's digest is appended to it.
_DIR_NAME_DIGEST_CHARS = 12


def case_dir_name(case_key: str) -> str:
    """Name the directory a case's stores live in, injectively.

    **Sanitising a key is not an injective mapping, and per-case store isolation
    needs one.** ``"a/b"`` and ``"a_b"`` both sanitise to ``a_b``, and two cases
    sharing a directory share their memory, conversations and deferral stores — so
    one case's beliefs can answer another's questions, which is the property
    :func:`execute_run` exists to keep. The name is therefore a sanitised prefix of
    the key *plus a digest of the whole key*: the prefix keeps the directory
    recognisable, which is what ``--keep-stores`` is for, and the digest is what
    makes distinct keys distinct directories.

    Args:
        case_key: The case's key, as its corpus gives it.

    Returns:
        One path component, unique to ``case_key``.
    """
    prefix = _UNSAFE_IN_DIR_NAME.sub("_", case_key)[:_DIR_NAME_PREFIX_CHARS]
    digest = sha256(case_key.encode("utf-8")).hexdigest()[:_DIR_NAME_DIGEST_CHARS]
    return f"{prefix}-{digest}"


@dataclass(frozen=True, slots=True)
class RunPlan:
    """What a run would do, computed without contacting anything.

    Attributes:
        corpus: The corpus.
        cases: The cases selected.
        max_sessions: The bound the selection shortened those cases' histories to —
            ``0`` where they are whole, and ``None`` where the cases arrived carrying
            no record of how they were selected. This is where the session bound comes
            from now: ``execute_run`` writes it to the manifest and hands it to the
            gate, so a caller cannot shorten the histories in selection and declare
            something else at execution (#1052). ``None`` is not "whole" — it is "not
            recorded", and a scored run is refused on it.
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
    max_sessions: int | None
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
        cases: The cases selected. A
            :class:`~benchmarks.memory.select.CaseSelection` — what
            :func:`~benchmarks.memory.select.first_sessions` returns — also says what
            the shortening did, and the plan carries that through to the manifest and
            the gate. A bare sequence says nothing about its own provenance, so the
            plan records ``None`` rather than assuming the histories are whole.
        batch_size: The observation batch size the run would use.

    Returns:
        The plan.

    Raises:
        ValueError: If ``batch_size`` is not positive, or if two cases share a
            ``case_key``.
    """
    if batch_size < 1:
        msg = f"batch_size must be positive, got {batch_size}"
        raise ValueError(msg)
    # Two cases under one key is a mistake whatever the directories do — the records
    # they write cannot be told apart afterwards. Refusing it in the planner means both
    # CLI commands report it before a store is opened or a model call is made, and it
    # is the half of case isolation `case_dir_name` cannot supply: a digest is a
    # function of the key, so one key is one directory however it is computed.
    duplicated = sorted(
        key for key, count in Counter(case.case_key for case in cases).items() if count > 1
    )
    if duplicated:
        msg = f"cases must have distinct case_key values; duplicated: {', '.join(duplicated)}"
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
        # Read off the selection, never off an argument: the whole point of #1052 is
        # that the code which shortened the histories is the only thing that knows it
        # did. `tuple(cases)` above deliberately drops the subclass, so a plan cannot
        # be re-planned into provenance it never had.
        max_sessions=cases.max_sessions if isinstance(cases, CaseSelection) else None,
        question_count=questions,
        turn_count=turns,
        observation_calls=observations,
        answer_calls=questions,
        judge_calls=judged,
    )


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


def check_credentials_for(
    settings: Settings, *, answering: bool, distillation: bool, judging: bool
) -> None:
    """Fail now if a route this run will actually build holds no credential.

    **Route by route, and not ``app.ensure_model_credentials``.** That helper checks
    the router's whole preference order, which is right for the hub — it builds a
    ``RoutingProvider`` and will reach every one of those routes. This harness builds
    one fixed route per seam and disables routing outright (:mod:`benchmarks.memory.wiring`),
    so checking the fallbacks would refuse to run a perfectly valid benchmark because
    of a credential for a vendor it will never construct. The per-route pair is public
    and is what the composition root itself pairs.

    **Only the seams this run builds are checked.** A seam the caller injected is a
    fake, and a fake needs no credential — which is what keeps this suite runnable with
    no key configured at all.

    Args:
        settings: Loaded application settings.
        answering: Whether the answering seam will be built here.
        distillation: Whether the observer will be built here.
        judging: Whether a model judge will be built here.

    Raises:
        ConfigurationError: If a vendor is unresolvable or holds no credential.
    """
    observer_route = (
        settings.observer_model if settings.observer_model is not None else settings.default_model
    )
    # Accumulated into a set rather than a mapping from spec to "is it needed": the
    # observer's route *defaults to* `default_model`, so a mapping keyed by spec has
    # one entry overwrite the other and a run judging on the default route while
    # injecting the observer would check nothing at all. Duplicates are checked once,
    # which is what the set is for.
    needed: set[str] = set()
    if answering or judging:
        needed.add(settings.default_model)
    if distillation:
        needed.add(observer_route)
    for spec in sorted(needed):
        # Vendor first, then credential — the order `ensure_credential_available`
        # asks for: an uninstalled package surfaces there as a bare `ImportError`
        # with a worse message than its sibling's.
        ensure_vendor_available(spec)
        ensure_credential_available(spec)


async def execute_run(  # noqa: PLR0913 — every parameter is a distinct axis of the experiment, and bundling them into a config object would hide which ones a caller left at a default
    plan: RunPlan,
    *,
    output_root: Path,
    mode: RunMode,
    corpus_digests: dict[str, str],
    settings: Settings | None = None,
    grader: Grader | None = None,
    grader_kind: str = "exact",
    model: ModelProvider | None = None,
    observer: Observer | None = None,
    preregistration_final: bool = False,
    slice_seed: int | None = None,
    max_sessions: int | None = None,
    notes: str = "",
    keep_stores: bool = False,
) -> RunManifest:
    """Run the plan, writing a manifest and one JSONL record per question.

    Each case gets its own data directory and its own harness: a benchmark case is a
    whole memory, and two cases sharing a store would let one case's beliefs answer
    another's questions. :func:`case_dir_name` is what makes that true rather than
    merely intended — distinct keys get distinct directories even when they sanitise
    alike. The stores are removed after each case unless asked for,
    because a LoCoMo case's ``memory.db`` carries thousands of vectors and ten of them
    is a lot of disk for something nothing reads. ``traces.db`` is always kept: it is
    the ADR-0119 record P8's analysis is defined over, and it is small.

    **Deleting the rest costs the analysis nothing, which is a property this function
    now has rather than one it always had** (#1074). The link between a corpus evidence
    pointer and the generated record ids a retrieval returns used to exist only in the
    episodes inside ``memory.db``, so P8's split needed a run someone had thought to
    pass ``--keep-stores`` on. It is written into ``records.jsonl`` here instead —
    ``evidence_episode_ids`` off the ingestion summary, ``retrieved_evidence`` off the
    answer — so the split is computable from the retained artifacts by default.

    Args:
        plan: What to run.
        output_root: Where run directories are created.
        mode: Whether these outputs may be read as scores. A ``SCORED`` run is put
            through :func:`refuse_ineligible_scored_run` **here**, at the boundary that
            actually writes the manifest, not only at the command line — this function
            is exported and a caller reaching it directly could otherwise label an
            ineligible run ``scored``.
        preregistration_final: Whether the operator states #1029's pre-registration is
            discharged. Defaults to ``False``, so the unsafe direction needs an
            argument and the safe one needs nothing.
        corpus_digests: Each fetched file's name mapped to its SHA-256, for the
            manifest.
        settings: Loaded application settings; loaded from the environment when
            ``None``.
        grader: Override the grading seam. Refused for a scored run, like the other
            two — a manifest that records a configured judge while an injected one
            graded is a manifest that is wrong.
        grader_kind: Which grader to build when none is injected: ``"exact"`` (no model
            call, the default) or ``"model"``. This is what the gate checks, because it
            names what the harness is about to construct rather than what a caller
            called it.
        model: Override the answering seam. Tests supply one; a live run does not.
        observer: Override the distillation seam, likewise.
        slice_seed: The seed a stratified slice was drawn with, for the manifest.
        max_sessions: **Not what is recorded, and not what the gate reads.** The bound
            comes from ``plan.max_sessions`` — set by the code that actually shortened
            the histories — because taking it from here let a caller truncate in
            selection and declare ``0`` at execution, which the gate then permitted
            while the manifest claimed whole histories (#1052). What this now is: a
            declaration, kept because the command line makes one, refused when it
            disagrees with a bound the plan actually applied, and used as the manifest's
            value only for a plan that recorded no selection at all. ``None``, the
            default, declares nothing — which is always safe, and is what a caller that
            planned through :func:`~benchmarks.memory.select.first_sessions` should
            pass, because the plan already knows.
        notes: Attached to the manifest.
        keep_stores: Keep every case's databases rather than only its traces.

    Returns:
        The manifest, already written to ``<output_root>/<run_id>/manifest.json``.
    """
    resolved = settings if settings is not None else Settings()
    # Normalised here as well as inside the gate, so the manifest and the gate cannot
    # disagree about what this run is — see the gate for why a `StrEnum` makes that a
    # real hazard rather than a hypothetical one.
    mode = RunMode(mode)
    injected = tuple(
        name
        for name, seam in (("grader", grader), ("model", model), ("observer", observer))
        if seam is not None
    )
    refuse_ineligible_scored_run(
        mode,
        preregistration_final=preregistration_final,
        max_sessions=plan.max_sessions,
        embedder=resolved.embedder,
        grader_kind=grader_kind,
        injected_seams=injected,
    )
    # The declaration is cross-checked against the plan rather than silently overridden:
    # a caller who believes the histories are whole while the plan says they were cut to
    # two has a bug wherever that belief came from, and a smoke run that quietly
    # corrected it would leave the bug in place for the scored run. The exemption is a
    # plan that shortened nothing: `--max-sessions 99` over a 3-session corpus really
    # did leave the histories whole, so a declaration of 99 against a derived 0 is a
    # lever that missed rather than a contradiction.
    if plan.max_sessions and max_sessions is not None and max_sessions != plan.max_sessions:
        msg = (
            f"the plan's cases were shortened to {plan.max_sessions} sessions but this "
            f"run declares max_sessions={max_sessions}: the bound is derived from the "
            f"plan (#1052), so a declaration that disagrees with it is refused rather "
            f"than silently corrected. Omit the argument."
        )
        raise ValueError(msg)
    # A plan whose `max_sessions` is `None` arrived with no record of how its cases were
    # selected. A scored run never reaches here — the gate above refuses it — so this is
    # a smoke run, whose manifest is explicitly not a measurement, and the caller's word
    # is the only thing anyone has; where it said nothing either, `0` is what the field
    # has always meant by default.
    recorded_max_sessions = (
        plan.max_sessions
        if plan.max_sessions is not None
        else (max_sessions if max_sessions is not None else 0)
    )
    # Built after the gate, so a scored run's judge is one this function constructed
    # from `Settings` and never one it was handed.
    judge = grader if grader is not None else build_grader(resolved, kind=grader_kind)
    check_credentials_for(
        resolved,
        answering=model is None,
        distillation=observer is None,
        judging=grader is None and grader_kind == "model",
    )
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
        max_sessions=recorded_max_sessions,
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
        case_dir = run_dir / "cases" / case_dir_name(case.case_key)
        harness = build_harness(resolved, data_dir=case_dir, model=model, observer=observer)
        try:
            summary = await ingest_case(harness, case, batch_size=resolved.observation_batch_size)
            ingestion: dict[str, int | float | str | list[str]] = {
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
                # The harness's own headlessness, reported beside the run's records so
                # a depressed P3/P5 is attributable to it rather than to retrieval: a
                # deferred proposal is a question nobody will answer, so the belief is
                # never written and no retrieval can find it.
                "proposals_deferred": summary.proposals_deferred,
                "proposals_ruled": summary.proposals_ruled,
                "ask_rate": summary.ask_rate,
                # The denominator for `QuestionRecord.evidence_episode_ids`: how many
                # of this case's corpus pointers became an episode at all.
                "evidence_keys_captured": summary.evidence_keys_captured,
                "observation_routes": sorted(summary.observation_routes),
            }
            cursor = TraceCursor(harness.traces)
            for question in case.questions:
                # A per-question provider failure is recorded and stepped over rather
                # than allowed to end the run. On a ~2,000-question paid run, dying at
                # question 400 loses the 1,586 after it *and* every later case, which
                # is a far worse outcome than a handful of `ungraded` rows a reader can
                # exclude. `ensure_model_credentials` above is what keeps this from
                # papering over a misconfiguration: a bad credential fails at startup,
                # so what reaches here is a transient fault or a refused prompt.
                #
                # The failure is caught in `answer_question`, inside the correlation
                # scope, so the retrieval that had already happened keeps its ids and
                # its telemetry. Grading is skipped rather than asked to judge an
                # answer that does not exist.
                attempt = await answer_question(harness, question)
                grading = (
                    Grading(
                        verdict=Verdict.UNGRADED,
                        abstained=False,
                        judge=judge.name,
                        detail=f"answering failed: {attempt.failure}",
                    )
                    if attempt.failure is not None
                    else await judge.grade(question, attempt.answer)
                )
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
                        retrieved_evidence=attempt.retrieved_evidence,
                        retrieved_evidence_elided=attempt.retrieved_evidence_elided,
                        evidence=question.evidence,
                        # #1074's join, projected onto this question's own pointers.
                        # The case's whole mapping is thousands of entries wide on a
                        # LoCoMo dialogue and would be denormalised onto all ~199 of
                        # its records; the slice a question's own analysis reads is
                        # this one, and it is small.
                        evidence_episode_ids=tuple(
                            tuple(summary.evidence_episodes.get(pointer, ()))
                            for pointer in question.evidence
                        ),
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


def refuse_ineligible_scored_run(  # noqa: PLR0913 — one parameter per precondition, and bundling them into a config object would hide which ones a caller left at a default
    mode: RunMode,
    *,
    preregistration_final: bool,
    max_sessions: int | None = None,
    embedder: EmbedderKind = EmbedderKind.ON_DEVICE,
    grader_kind: str = "model",
    injected_seams: Sequence[str] = (),
) -> None:
    """Refuse a scored run that is not entitled to be one.

    **Every precondition for a scored run lives here, in one place, and every one of
    them is a refusal rather than a warning.** The distinction that decides which
    conditions belong here is whether the configuration *contradicts what the run's own
    artifacts would claim*. A scored manifest asserts that this is the pilot's one
    configuration; each condition below makes that assertion false, so a warning would
    be a run that completes, writes something labelled `scored`, and is not.

    1. **The pre-registration must be final** — #1029's ground rule 1, which is the
       whole reason the mode exists.
    2. **Histories must be whole, and the plan must be in a position to say so.** A
       shortened history is a different memory, so the questions are about a
       conversation that did not happen. The bound is read off the plan — set by
       :func:`~benchmarks.memory.select.first_sessions`, which is what does the
       shortening — rather than declared by the caller, because those were two separate
       inputs and a caller could truncate in selection and declare nothing at execution
       (#1052). ``None``, meaning the cases carry no record of how they were selected,
       is refused alongside a non-zero bound: nobody having written it down is not
       evidence that the histories are whole.
    3. **The embedder must be on-device.** ``hashing`` is non-semantic, so retrieval
       under it is not the retrieval the pilot is measuring (#1029's configuration
       block requires "the real embedder, not the QA-run hashing embedder").
    4. **The grader must be the model judge.** LoCoMo and LongMemEval both grade with
       an LLM judge, and :class:`~benchmarks.memory.grade.ExactGrader` is a normalised
       substring match — deliberately poor, and not comparable to the published
       numbers this pilot is positioned against.
    5. **No seam may be injected.** ``execute_run`` accepts overrides for the
       answering, distillation and grading seams so tests can drive the whole pipeline
       without a model call — and the manifest records the *configured* routes, which
       an injected seam makes false. A scored run therefore builds all three from
       ``Settings`` and refuses any override, which is what makes the manifest true by
       construction rather than by the caller's good behaviour. Like clause 2 since
       #1052, it is checked without trusting anything a caller says: an override is
       present or it is not.

    **``episode_retention`` is deliberately *not* here**, and the omission is the rule
    working rather than a gap. A finite horizon is the product's own default and a
    legitimate thing to measure; what it does under the corpus clock is surprising, not
    false, so it is warned about at the command line and recorded in the manifest. The
    four above are configurations under which the word ``scored`` would be untrue.

    Args:
        mode: The mode asked for.
        preregistration_final: Whether the operator stated the pre-registration is
            final.
        max_sessions: The session bound the plan's cases were shortened to; ``0`` means
            whole histories and ``None`` — the default, so the unknown is the direction
            that needs no argument — means nothing recorded what the selection did.
            :func:`execute_run` passes ``plan.max_sessions`` here; the command line
            passes its own flag, one screen before the corpus is fetched, so an
            ineligible scored run is refused in a second rather than after a download.
            That earlier call is a declaration and is deliberately the stricter of the
            two — it refuses ``--max-sessions 99`` on a corpus no case of which has 99
            sessions, which selection would have shown to shorten nothing. The asymmetry
            only ever refuses, never admits, and no scored run reaches a store on it.
        embedder: The configured embedder.
        grader_kind: Which grader will be built. Named rather than inspected off a
            grader object, because a display name is something a caller controls and
            this has to be the kind the harness itself is about to construct.
        injected_seams: The names of any seams the caller overrode.

    Raises:
        PermissionError: If a scored run was asked for without the pre-registration
            being stated final. The class is chosen for what it reads as at a terminal
            — this is a refusal on a rule, not a bad argument — and nothing catches it.
        ValueError: If a scored run was asked for under any of the others.
    """
    if RunMode(mode) is not RunMode.SCORED:
        return
    if preregistration_final is not True:
        # `is not True`, not `not …`: this arrives from a command line and from callers
        # outside mypy's reach, where `"false"` and `0` are both things a shell wrapper
        # produces — and `not "false"` is False, so a truthiness test reads the string
        # "false" as confirmation of the one rule that must never be confirmed by
        # accident.
        raise PermissionError(PREREGISTRATION_REFUSAL)
    if max_sessions is None:
        msg = (
            "a scored run cannot be planned from cases that carry no record of how "
            "they were selected: the session bound is derived from the plan, not "
            "declared, so that a caller cannot shorten the histories and say nothing "
            "about it (#1052). Plan the run from "
            "benchmarks.memory.select.first_sessions(cases, limit) — limit 0 for the "
            "whole histories a scored run needs."
        )
        raise ValueError(msg)
    if max_sessions:
        msg = (
            f"a scored run cannot be made over histories shortened to {max_sessions} "
            f"sessions: a shortened history is a different memory, so its answers are "
            f"about a conversation that did not happen. --max-sessions is a plumbing "
            f"lever for smoke runs."
        )
        raise ValueError(msg)
    if embedder is not EmbedderKind.ON_DEVICE:
        msg = (
            f"a scored run cannot use ASSISTANT_EMBEDDER={embedder}: retrieval under "
            f"the hashing embedder is non-semantic, so the run would not measure the "
            f"pipeline #1029 predicts about. Set it to on-device."
        )
        raise ValueError(msg)
    if grader_kind != "model":
        msg = (
            f"a scored run cannot use --grader {grader_kind}: both benchmarks grade "
            f"with an LLM judge, and the exact grader is a normalised substring match "
            f"whose scores are not comparable to any published number. Use "
            f"--grader model."
        )
        raise ValueError(msg)
    if injected_seams:
        named = ", ".join(sorted(injected_seams))
        msg = (
            f"a scored run cannot take an injected seam ({named}): the manifest records "
            f"the routes the settings name, and a seam supplied by the caller makes that "
            f"record false. A scored run builds every seam from Settings."
        )
        raise ValueError(msg)
