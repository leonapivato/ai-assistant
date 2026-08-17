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
from contextlib import AsyncExitStack
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import uuid4

from ai_assistant.app.composition import (
    CONFLICT_LIMIT,
    EPISODIC_SUPPLEMENT_LIMIT,
    RETRIEVAL_LIMIT,
)
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.models import ensure_credential_available, ensure_vendor_available
from benchmarks.memory.answer import ANSWER_SYSTEM_PROMPT, answer_question, retrieve_for
from benchmarks.memory.batch import (
    BatchSession,
    PollPolicy,
    PreparedQuestion,
    answer_batch,
    judge_batch,
)
from benchmarks.memory.grade import (
    JUDGE_PROMPT,
    ExactGrader,
    Grading,
    ModelGrader,
    Verdict,
    grading_without_a_call,
)
from benchmarks.memory.ingest import exchanges_of, ingest_case
from benchmarks.memory.records import (
    BatchRef,
    QuestionRecord,
    RunManifest,
    RunMode,
    RunPhase,
    TraceCursor,
    now_iso,
    write_jsonl_line,
)
from benchmarks.memory.select import CaseSelection
from benchmarks.memory.spend import RunAbortedError, SpendGuard
from benchmarks.memory.wiring import (
    DEFAULT_ISSUER,
    build_batch_completer,
    build_embedder,
    build_harness,
    build_model_provider,
    refuse_unbatchable_route,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import BatchCompleter, ModelProvider, Observer
    from benchmarks.memory.answer import AnswerAttempt
    from benchmarks.memory.cases import BenchCase, BenchQuestion
    from benchmarks.memory.corpora.provenance import Corpus
    from benchmarks.memory.grade import Grader
    from benchmarks.memory.ingest import IngestionSummary
    from benchmarks.memory.records import RetrievalTelemetry
    from benchmarks.memory.wiring import Harness

__all__ = [
    "BATCHES_FILE",
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

#: Where a batched run writes each accepted batch, **before** it waits on it.
#:
#: Append-only and separate from ``manifest.json`` on purpose. The manifest is
#: rewritten once at the end of a run, which is exactly the wrong shape for a record
#: whose whole job is to survive a run that does not reach its end: a batch is billed
#: from the moment the provider accepts it, and a process killed during the wait must
#: still leave behind what it is being charged for (ADR-0060, and ADR-0143 §2's reason
#: for handing the handle back before any waiting). The manifest carries the same
#: references afterwards, for a reader who has one.
BATCHES_FILE = "batches.jsonl"

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


def build_grader(
    settings: Settings,
    *,
    kind: str,
    route: str | None = None,
    guard: SpendGuard | None = None,
) -> Grader:
    """Build the grader named by ``kind``.

    **The judge is a route of its own, and defaults to the answering one.** It was
    pinned to ``settings.default_model`` outright, which made the judge and the system
    under test the same model by construction — a coupling nobody chose and one a
    reader of the artifacts could not see, since the manifest recorded the two figures
    separately and they simply always agreed. A judge is a *measuring instrument*: it
    is legitimate for it to be a cheaper or a different model from the one being
    measured, and it is not legitimate for that to be unstateable. So the route is an
    argument, ``None`` keeps the previous behaviour exactly, and whatever is used
    reaches the manifest through :attr:`~benchmarks.memory.grade.Grader.name`, which is
    the route the grading was actually performed on rather than a declaration beside it.

    Nothing here relaxes the scored-run gate. :func:`refuse_ineligible_scored_run`
    clause 4 asks that the grader be the model judge, which is about the *kind*; a
    scored run choosing a judge route is choosing a configuration, and it is recorded.
    Clause 5's ban is on an injected grader *object*, which is what would make the
    manifest untrue — a named route is the opposite of that.

    Args:
        settings: Loaded application settings.
        kind: ``"exact"`` or ``"model"``.
        route: The ``"provider:model"`` spec to judge on, or ``None`` for
            ``settings.default_model``. Ignored by the exact grader, which makes no
            model call at all.
        guard: The run's spend guard, shared with the answering and distillation seams.
            Ignored by the exact grader for the same reason: it spends nothing.

    Returns:
        The grader.

    Raises:
        ValueError: If ``kind`` names neither.
    """
    if kind == "exact":
        return ExactGrader()
    if kind == "model":
        spec = route if route is not None else settings.default_model
        return ModelGrader(build_model_provider(settings, spec, guard=guard), route=spec)
    msg = f"unknown grader {kind!r}; expected 'exact' or 'model'"
    raise ValueError(msg)


def check_credentials_for(
    settings: Settings,
    *,
    answering: bool,
    distillation: bool,
    judging: bool,
    judge_route: str | None = None,
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
        judge_route: The route the judge will be built on, or ``None`` for
            ``settings.default_model`` — the same fallback :func:`build_grader` applies,
            spelled here rather than assumed, because a judge on a route the answering
            seam never touches is precisely the configuration this check exists to
            refuse at startup instead of at the first graded answer.

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
    if answering:
        needed.add(settings.default_model)
    if judging:
        needed.add(judge_route if judge_route is not None else settings.default_model)
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
    judge_route: str | None = None,
    model: ModelProvider | None = None,
    observer: Observer | None = None,
    preregistration_final: bool = False,
    slice_seed: int | None = None,
    max_sessions: int | None = None,
    notes: str = "",
    keep_stores: bool = False,
    max_model_calls: int | None = None,
    phase: RunPhase = RunPhase.SYNC,
    batch_completer: BatchCompleter | None = None,
    issuer: str = DEFAULT_ISSUER,
    poll: PollPolicy | None = None,
    announce: Callable[[str], None] | None = None,
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
        judge_route: The ``"provider:model"`` spec the model judge grades on, or
            ``None`` for ``settings.default_model``. A judge is an instrument and need
            not be the model under test; whichever route is used lands in the
            manifest's ``judge`` field, which is read off the grader that graded rather
            than declared beside it. Ignored under ``grader_kind="exact"`` and under an
            injected grader, neither of which makes a call.
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
        phase: :class:`~benchmarks.memory.records.RunPhase`. ``SYNC``, the default,
            is the path every pilot before this one ran: one completion per question,
            then one per grading. ``BATCH`` retrieves for every question first, then
            answers them all in one ``BatchCompleter`` job and grades them in a
            second — half the price on the two seams that are ~60% of a scored run's
            spend, and two waits instead of ~2,000 serial round trips.

            **Ingestion is not on this axis and never batches.** Every observation
            pass reads the conversation's most recent window, so each one depends on
            the writes the pass before it made.

            **What a batched run can record that a synchronous one cannot** is an
            ``ungraded`` row whose cause is a batch item the provider expired,
            cancelled or failed (ADR-0143 §4). The manifest records the phase so those
            rows are readable; nothing silently becomes an empty answer, which would
            grade as an abstention and corrupt #1029's P7.
        batch_completer: Override the bulk-inference seam. Tests supply a fake; a live
            run does not, and a scored run may not — it is refused by
            :func:`refuse_ineligible_scored_run` clause 5 alongside the other three,
            for the same reason. Ignored under ``SYNC``, which submits nothing.
        issuer: The non-secret account label stamped on this run's batch handles and
            compared against any handle presented back (ADR-0143 §2). Recorded in
            ``batches.jsonl`` and in the manifest, because a handle is an address only
            *for that account*. Never a credential.
        poll: How long to wait on each batch and how often to ask, or ``None`` for
            :class:`~benchmarks.memory.batch.PollPolicy`'s defaults. Waiting is the
            caller's loop by ADR-0143 §2, and this is that loop's policy.
        announce: Where to print a batched run's progress — the handles as they are
            accepted and each poll's settled count — or ``None`` to print nothing. An
            operator watching a paid run needs to see the handle; a test does not.
        notes: Attached to the manifest.
        keep_stores: Keep every case's databases rather than only its traces.
        max_model_calls: The most model calls this run may make across every seam it
            **builds**, or ``None`` for no ceiling. Read the figure off :func:`plan_run`,
            which reports the same currency — one logical completion, so a call the retry
            policy repeats is charged once. A run that reaches it stops cleanly, keeps the
            records it wrote, and records why in the manifest.

            **An injected ``observer`` or ``grader`` spends outside it.** Neither is a
            ``ModelProvider``, so neither can be wrapped, and a caller supplying one has
            taken that seam's cost off this budget; ``model`` is the exception, being a
            provider, and is guarded whether built or injected. Clause 5 of
            :func:`refuse_ineligible_scored_run` refuses every injected seam on a scored
            run, so the ceiling covers a scored run whole.

    Returns:
        The manifest, already written to ``<output_root>/<run_id>/manifest.json`` —
        and rewritten there if the run aborted, carrying
        :attr:`~benchmarks.memory.records.RunManifest.aborted`. The caller decides
        what an abort means for its own exit status; this returns rather than raises,
        because the records written before the stop are the point of stopping cleanly.
    """
    resolved = settings if settings is not None else Settings()
    # Normalised here as well as inside the gate, so the manifest and the gate cannot
    # disagree about what this run is — see the gate for why a `StrEnum` makes that a
    # real hazard rather than a hypothetical one.
    mode = RunMode(mode)
    phase = RunPhase(phase)
    injected = tuple(
        name
        for name, seam in (
            ("batch_completer", batch_completer),
            ("grader", grader),
            ("model", model),
            ("observer", observer),
        )
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
    # One guard for the whole run, because ingestion, answering and judging draw on one
    # account: three per-seam budgets would each be inside their own bound while the
    # balance went to zero. It is created before the judge so both it and every case's
    # harness take the same instance; what it does *not* reach is an injected `observer`
    # or `grader`, which the parameter's own documentation states.
    guard = SpendGuard(limit=max_model_calls)
    # Built after the gate, so a scored run's judge is one this function constructed
    # from `Settings` and never one it was handed.
    judge = (
        grader
        if grader is not None
        else build_grader(resolved, kind=grader_kind, route=judge_route, guard=guard)
    )
    check_credentials_for(
        resolved,
        answering=model is None,
        distillation=observer is None,
        judging=grader is None and grader_kind == "model",
        judge_route=judge_route,
    )
    # Beside the credential check and for the same reason: a batched run that cannot
    # reach a batch endpoint should say so now, not after every case has been ingested
    # at full price. Skipped where a completer was injected, which is a fake and
    # answers for whatever route it likes.
    if phase is RunPhase.BATCH and batch_completer is None:
        refuse_unbatchable_route(resolved.default_model)
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
        phase=phase,
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
        # The supplement's own budget, recorded beside the belief budget because a run
        # is only recoverable from its manifest if both reads are in it (ADR-0158 §3).
        episodic_limit=EPISODIC_SUPPLEMENT_LIMIT,
        conflict_limit=CONFLICT_LIMIT,
        observation_batch_size=resolved.observation_batch_size,
        observation_max_proposals=resolved.observation_max_proposals,
        # The same `Settings` field `build_harness` hands the producer, so the manifest
        # cannot name a calendar the observation prompt did not run under.
        observer_timezone=resolved.timezone,
        episode_retention=(
            "none" if resolved.episode_retention is None else str(resolved.episode_retention)
        ),
        answer_prompt=ANSWER_SYSTEM_PROMPT,
        judge_prompt=JUDGE_PROMPT if isinstance(judge, ModelGrader) else None,
        notes=notes,
        model_call_ceiling=max_model_calls,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(manifest.model_dump_json(indent=1), encoding="utf-8")

    # The abort is caught here rather than allowed out, because the records written
    # before it are the whole point of stopping cleanly: a run that dies at question
    # 400 of 2,000 should leave 399 usable rows and a manifest saying why there are no
    # more, not a traceback and an artifact that describes a run which did not happen.
    # A `MemoryStoreError` is deliberately *not* caught with it — a failing store is not
    # a budget decision, and `answer._supplement` argues at length why that one ends the
    # run with nothing published.
    say = announce if announce is not None else _say_nothing
    batches_path = run_dir / BATCHES_FILE
    submitted: list[BatchRef] = []

    def file_batch(reference: BatchRef) -> None:
        """Put an accepted batch on disk before anything waits on it."""
        submitted.append(reference)
        write_jsonl_line(batches_path, reference)

    prepared: list[PreparedQuestion] = []
    aborted: str | None = None
    try:
        async with AsyncExitStack() as stack:
            session: BatchSession | None = None
            if phase is RunPhase.BATCH:
                # Entered here rather than per batch so one client serves both, and
                # closed by the stack however this run ends — the completer owns a
                # connection pool nothing else can reach.
                completer = (
                    batch_completer
                    if batch_completer is not None
                    else await stack.enter_async_context(
                        build_batch_completer(resolved, issuer=issuer)
                    )
                )
                session = BatchSession(
                    completer=completer,
                    guard=guard,
                    run_id=run_id,
                    on_batch=file_batch,
                    poll=poll if poll is not None else PollPolicy(),
                    announce=say,
                )
            driver = _CaseDriver(
                settings=resolved,
                judge=judge,
                guard=guard,
                run_id=run_id,
                run_dir=run_dir,
                records_path=records_path,
                keep_stores=keep_stores,
                model=model,
                observer=observer,
                session=session,
            )
            for case in plan.cases:
                prepared.extend(await driver.run(case))
            if session is not None:
                # Every case is ingested, scored for retrieval and closed before a single
                # paid batch exists. That ordering is the cheap direction under ADR-0143
                # §2's un-closed acceptance window: the work that can still fail happens
                # while nothing is billing.
                await _answer_and_judge_in_batches(
                    session, prepared, judge=judge, run_id=run_id, records_path=records_path
                )
    except RunAbortedError as stop:
        aborted = stop.reason
        # The aborted case keeps its databases whichever way `keep_stores` was set:
        # the deletion sits after the per-case `finally` and is skipped, which is the
        # right direction — the one case that did not finish is the one whose store
        # someone may want to look at.
    if aborted is not None or submitted:
        # The manifest's one rewrite, and both things it adds are facts a run only has
        # once it is over. A batch that must survive an interruption is already in
        # `batches.jsonl`, appended the moment the provider accepted it — this file is
        # the record for a reader, not the guard.
        manifest = manifest.model_copy(update={"aborted": aborted, "batches": tuple(submitted)})
        (run_dir / "manifest.json").write_text(manifest.model_dump_json(indent=1), encoding="utf-8")
    return manifest


@dataclass(frozen=True, slots=True)
class _CaseDriver:
    """Everything constant across a run's cases, so running one is one call.

    A bundle rather than eleven arguments threaded through a loop, and the grouping
    is the same one :class:`~benchmarks.memory.batch.BatchSession` makes: every field
    is fixed before the first case and identical for the last. What varies is the
    case, which is the argument.

    Attributes:
        settings: Loaded application settings.
        judge: The grader, used only on the synchronous path — a batched run grades
            after every case is closed.
        guard: The run's spend ceiling, shared by every seam the run builds.
        run_id: The run.
        run_dir: Where this run's artifacts live.
        records_path: Where synchronous rows are appended as they are produced.
        keep_stores: Keep every case's databases rather than only its traces.
        model: An injected answering seam, or ``None``.
        observer: An injected distillation seam, or ``None``.
        session: The batch session, or ``None`` under ``--phase sync``. It is what
            decides which of the two paths each question takes, so the phase is read
            off the thing that would do the batching rather than off a flag beside it.
    """

    settings: Settings
    judge: Grader
    guard: SpendGuard
    run_id: str
    run_dir: Path
    records_path: Path
    keep_stores: bool
    model: ModelProvider | None
    observer: Observer | None
    session: BatchSession | None

    async def run(self, case: BenchCase) -> list[PreparedQuestion]:
        """Ingest one case and either answer its questions or retrieve for them.

        Each case gets its own data directory and its own harness: a benchmark case is
        a whole memory, and two cases sharing a store would let one case's beliefs
        answer another's questions. The stores are removed afterwards unless asked
        for, because a LoCoMo case's ``memory.db`` carries thousands of vectors;
        ``traces.db`` is always kept, being the ADR-0119 record P8 is defined over.

        Args:
            case: The case to run.

        Returns:
            Under ``--phase batch``, one :class:`PreparedQuestion` per question,
            awaiting an answer. Under ``--phase sync``, an empty list — those rows are
            already written.

        Raises:
            RunAbortedError: If the run's ceiling or its account ran out. Raised
                through, so the caller's handler keeps what was written and the case's
                databases survive for inspection.
        """
        case_dir = self.run_dir / "cases" / case_dir_name(case.case_key)
        harness = build_harness(
            self.settings,
            data_dir=case_dir,
            model=self.model,
            observer=self.observer,
            guard=self.guard,
        )
        prepared: list[PreparedQuestion] = []
        try:
            summary = await ingest_case(
                harness, case, batch_size=self.settings.observation_batch_size
            )
            ingestion = _ingestion_summary(summary)
            cursor = TraceCursor(harness.traces)
            for question in case.questions:
                if self.session is None:
                    await _answer_now(
                        harness,
                        question,
                        case=case,
                        judge=self.judge,
                        cursor=cursor,
                        summary=summary,
                        ingestion=ingestion,
                        run_id=self.run_id,
                        records_path=self.records_path,
                    )
                else:
                    # Retrieval only. The two reads, the separator rule and the
                    # correlation scope are `retrieve_for`'s — the same function
                    # `answer_question` composes — so nothing #1029 computes about
                    # retrieval depends on which phase is running. The telemetry is
                    # collected *here*, while this case's trace store is still open:
                    # the answer arrives hours later, long after the store was closed
                    # and its databases deleted.
                    retrieved = await retrieve_for(harness, question)
                    prepared.append(
                        PreparedQuestion(
                            case=case,
                            question=question,
                            retrieved=retrieved,
                            telemetry=await cursor.collect(retrieved.correlation_id),
                            evidence_episode_ids=_evidence_episode_ids(summary, question),
                            ingestion=ingestion,
                        )
                    )
        finally:
            harness.close()
        if not self.keep_stores:
            for name in ("memory.db", "conversations.db", "deferrals.db"):
                (case_dir / name).unlink(missing_ok=True)
        return prepared


def _ingestion_summary(
    summary: IngestionSummary,
) -> dict[str, int | float | str | list[str]]:
    """Flatten what ingesting a case reported, for the rows it is denormalised onto.

    Args:
        summary: The summary.

    Returns:
        The fields every record of that case carries.
    """
    return {
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
        # The harness's own headlessness, reported beside the run's records so a
        # depressed P3/P5 is attributable to it rather than to retrieval: a deferred
        # proposal is a question nobody will answer, so the belief is never written
        # and no retrieval can find it.
        "proposals_deferred": summary.proposals_deferred,
        "proposals_ruled": summary.proposals_ruled,
        "ask_rate": summary.ask_rate,
        # The denominator for `QuestionRecord.evidence_episode_ids`: how many of this
        # case's corpus pointers became an episode at all.
        "evidence_keys_captured": summary.evidence_keys_captured,
        "observation_routes": sorted(summary.observation_routes),
    }


def _say_nothing(line: str) -> None:
    """Swallow a progress line, for a caller that asked for no announcements.

    Args:
        line: What would have been printed.
    """


def _evidence_episode_ids(
    summary: IngestionSummary, question: BenchQuestion
) -> tuple[tuple[str, ...], ...]:
    """#1074's join, projected onto one question's own corpus pointers.

    The case's whole mapping is thousands of entries wide on a LoCoMo dialogue and
    would be denormalised onto all ~199 of its records; the slice a question's own
    analysis reads is this one, and it is small.

    Args:
        summary: What ingesting the case reported.
        question: The question whose pointers to project.

    Returns:
        For each entry of ``question.evidence``, in order, the episode ids that
        pointer became. An empty tuple means it became none.
    """
    return tuple(tuple(summary.evidence_episodes.get(pointer, ())) for pointer in question.evidence)


def _question_record(  # noqa: PLR0913 — every parameter is one field of the record, and bundling them would only move the list somewhere a reader has to follow
    *,
    run_id: str,
    case: BenchCase,
    question: BenchQuestion,
    attempt: AnswerAttempt,
    grading: Grading,
    evidence_episode_ids: tuple[tuple[str, ...], ...],
    telemetry: RetrievalTelemetry,
    ingestion: Mapping[str, int | float | str | list[str]],
    batch_item_id: str | None = None,
) -> QuestionRecord:
    """Assemble the one row a question leaves behind, whichever phase produced it.

    One function so the two phases cannot record different things about the same
    question. Everything it reads is already phase-independent: an
    :class:`~benchmarks.memory.answer.AnswerAttempt` carries its retrieval's own ids
    and correlation scope whether the answer came back from ``complete`` or from a
    batch outcome (``RetrievedContext.answered``).

    Args:
        run_id: The run.
        case: The case, for its corpus and key.
        question: The question.
        attempt: The retrieval, paired with whatever answer arrived.
        grading: The verdict.
        evidence_episode_ids: #1074's join for this question.
        telemetry: What the ``RETRIEVAL`` traces said.
        ingestion: The case's summary, denormalised onto every one of its rows.
        batch_item_id: The id this question's answer was submitted under, or ``None``
            on a synchronous run.

    Returns:
        The record, ready to append.
    """
    return QuestionRecord(
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
        evidence_episode_ids=evidence_episode_ids,
        batch_item_id=batch_item_id,
        telemetry=telemetry,
        asked_at=attempt.asked_at,
        context_chars=len(attempt.context),
        ingestion=dict(ingestion),
    )


async def _answer_now(  # noqa: PLR0913 — the synchronous per-question step, lifted out of `execute_run` whole rather than reshaped
    harness: Harness,
    question: BenchQuestion,
    *,
    case: BenchCase,
    judge: Grader,
    cursor: TraceCursor,
    summary: IngestionSummary,
    ingestion: Mapping[str, int | float | str | list[str]],
    run_id: str,
    records_path: Path,
) -> None:
    """Answer, grade and record one question, in this process, right now.

    The ``--phase sync`` path, unchanged in behaviour from every pilot before this
    one and lifted out of :func:`execute_run` only so the loop can carry two phases
    without either being harder to read than it was.

    A per-question provider failure is recorded and stepped over rather than allowed
    to end the run. On a ~2,000-question paid run, dying at question 400 loses the
    1,586 after it *and* every later case, which is a far worse outcome than a handful
    of ``ungraded`` rows a reader can exclude. ``check_credentials_for`` is what keeps
    this from papering over a misconfiguration: a bad credential fails at startup, so
    what reaches here is a transient fault or a refused prompt. The failure is caught
    in ``answer_question``, inside the correlation scope, so the retrieval that had
    already happened keeps its ids and its telemetry. Grading is skipped rather than
    asked to judge an answer that does not exist.

    Args:
        harness: The wired pipeline for this case.
        question: The question to answer.
        case: The case it belongs to.
        judge: The grader.
        cursor: The case's trace cursor, walked forward one question at a time.
        summary: What ingesting the case reported.
        ingestion: That summary, flattened for the record.
        run_id: The run.
        records_path: Where the row is appended.
    """
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
        _question_record(
            run_id=run_id,
            case=case,
            question=question,
            attempt=attempt,
            grading=grading,
            evidence_episode_ids=_evidence_episode_ids(summary, question),
            telemetry=await cursor.collect(attempt.correlation_id),
            ingestion=ingestion,
        ),
    )


async def _answer_and_judge_in_batches(
    session: BatchSession,
    prepared: Sequence[PreparedQuestion],
    *,
    judge: Grader,
    run_id: str,
    records_path: Path,
) -> None:
    """Run the two batches, then write every row at once.

    **Records land at the end here, and that is the one property the batched phase
    gives up.** The synchronous path appends per question so a run that dies at 400 of
    2,000 leaves 399 usable rows; a batched one has no answer to write until its batch
    settles, so a death before that leaves none. What replaces the guarantee is
    ``batches.jsonl``: the handles are on disk from the moment the provider accepted
    them, and ADR-0143 §2's resumption clause makes the outcomes fetchable afterwards
    from any process holding the same ``issuer``. The rows are recoverable; they are
    just not already written.

    **A judge batch carries only the answers a judge must read.** An abstention and an
    unanswerable question are settled by
    :func:`~benchmarks.memory.grade.grading_without_a_call` — the same function the
    synchronous ``ModelGrader`` uses first — so they cost no item, exactly as they
    cost no call. On the pilot-3 partial that was most of the population.

    A grader that is not a model judge is applied here directly instead: it makes no
    call, so there is nothing to batch, and routing it through a batch would submit
    items for a decision already available locally.

    Args:
        session: The run's seam, ceiling, batch record and wait policy.
        prepared: Every question the run retrieved for.
        judge: The grader.
        run_id: The run.
        records_path: Where the rows are appended.
    """
    answers = await answer_batch(session, prepared)
    gradings: dict[str, Grading] = {}
    pending: list[tuple[str, BenchQuestion, str]] = []
    for one in prepared:
        answer, failure = answers[one.item_id]
        if failure is not None:
            gradings[one.item_id] = Grading(
                verdict=Verdict.UNGRADED,
                abstained=False,
                judge=judge.name,
                detail=f"answering failed: {failure}",
            )
        elif isinstance(judge, ModelGrader):
            settled = grading_without_a_call(one.question, answer, judge=judge.name)
            if settled is not None:
                gradings[one.item_id] = settled
            else:
                pending.append((one.item_id, one.question, answer))
        else:
            gradings[one.item_id] = await judge.grade(one.question, answer)
    gradings.update(await judge_batch(session, pending, judge_name=judge.name))
    for one in prepared:
        answer, failure = answers[one.item_id]
        write_jsonl_line(
            records_path,
            _question_record(
                run_id=run_id,
                case=one.case,
                question=one.question,
                attempt=one.retrieved.answered(answer=answer, failure=failure),
                grading=gradings[one.item_id],
                evidence_episode_ids=one.evidence_episode_ids,
                telemetry=one.telemetry,
                ingestion=one.ingestion,
                batch_item_id=one.item_id,
            ),
        )


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
