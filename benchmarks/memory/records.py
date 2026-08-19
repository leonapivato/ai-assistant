"""What a run writes down: the manifest, the per-question record, and trace linkage.

**The artifacts are the deliverable.** #1029 reports results hypothesis by hypothesis
and #833 wants the epistemics legible, so what a run leaves behind has to answer "what
exactly was measured?" without anyone remembering. That means the manifest records the
configuration rather than describing it — every route, every bound, both prompts, the
corpus digest — and the per-question record carries what P4 and P8 are computed from
rather than a summary of it.

**Nothing here aggregates.** No accuracy, no per-category rate, no verdict against a
prediction. Two reasons, and the second is the binding one: an aggregate over a smoke
run is a score, and #1029's ground rule 1 says smoke outputs are not looked at as
scores — a harness that printed "68%" after a five-question plumbing check would make
that rule impossible to keep. Aggregation belongs to whatever reads the JSONL after the
pre-registration is final.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field

from ai_assistant.core.types import BatchHandle, TraceKind, TraceRecordSet, TraceRef

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.protocols import TraceStore
    from ai_assistant.core.types import EvaluationTrace, TracePosition

__all__ = [
    "BANDS_KEY",
    "CANDIDATES_KEY",
    "EXCLUSION_KEYS",
    "FETCH_K_KEY",
    "LIMIT_KEY",
    "BatchRef",
    "QuestionRecord",
    "RetrievalTelemetry",
    "ReuseRef",
    "RunManifest",
    "RunMode",
    "RunPhase",
    "TraceCursor",
    "case_dir_name",
    "now_iso",
    "read_jsonl",
    "write_jsonl_line",
]


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


class RunMode(StrEnum):
    """Whether a run's outputs may be read as scores.

    ``SMOKE`` is the default everywhere, and ``SCORED`` is reachable only by asking
    for it and confirming the pre-registration is final. The value is written into
    the manifest, so the question "has a scored run happened?" is answered by the
    artifacts on disk rather than by anyone's recollection — which is what makes
    #1029's ground rule 1 auditable instead of merely agreed.
    """

    SMOKE = "smoke"
    SCORED = "scored"


class RunPhase(StrEnum):
    """How a run makes the model calls that answer and judge its questions.

    Ingestion is **not** on this axis and never batches: ``ObservationStage`` reads
    the conversation's most recent window, so every pass depends on the writes the
    pass before it made (``benchmarks.memory.ingest``). What varies here is only
    what happens once a case's memory is built.

    ``SYNC`` is the default and is what every pilot before this one ran: one
    completion per question, then one per grading, in order.

    ``BATCH`` retrieves for every question first, submits the answers as one
    ``BatchCompleter`` job, waits, then submits the gradings as a second. The
    vendor bills a batch at half the per-request price, and answering plus judging
    is about 60% of a scored run's cost. The wall clock changes shape rather than
    simply shrinking: two waits, each typically under an hour, instead of ~2,000
    serial round trips.

    It is recorded in the manifest because it is a configuration of the run and not
    a detail of how it was driven: a reader comparing two record sets needs to know
    that one of them may carry ``ungraded`` rows for a reason the other cannot have
    (:class:`~ai_assistant.core.types.BatchOutcomeKind`'s three non-success kinds).
    """

    SYNC = "sync"
    BATCH = "batch"


class BatchRef(BaseModel):
    """A submitted batch, written down so a paid job is never lost.

    **This is ADR-0060's shape applied to money rather than to a lock.** A batch is
    remote, outlives the coroutine that made it, is being billed, and cannot be
    released by returning; ADR-0143 §2 splits ``submit`` from the waiting precisely
    so the handle is in the caller's hands *before* any waiting begins. Holding it
    in memory would discharge that only until the process dies, so the run writes it
    to ``batches.jsonl`` before its first ``poll`` — an interrupted run then leaves a
    file naming exactly what it is being charged for, and the outcomes stay fetchable
    from any process with the same ``issuer`` (§2's resumption clause).

    It carries no count the provider would have to agree with, for the reason
    :class:`~ai_assistant.core.types.BatchHandle` carries none: ``item_count`` here
    is *the caller's* record of what it submitted, which is the set §4 has the caller
    match outcomes against, and never a claim about what ``poll`` will report.

    Attributes:
        kind: ``"answer"`` or ``"judge"`` — which of the run's two batches this is.
        batch_key: The run's own key for it, carried unchanged onto the handle and
            never interpreted by the provider.
        batch_id: The provider's identifier.
        issuer: The non-secret account label the batch is reachable from. Recorded
            because a handle is only an address *for that account*: a run resumed
            against another one cannot fetch this.
        submitted_at: When the provider accepted it, ISO-8601.
        item_count: How many items this run put in it.
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    batch_key: str
    batch_id: str
    issuer: str
    submitted_at: str
    item_count: int

    @classmethod
    def of(cls, handle: BatchHandle, *, kind: str, item_count: int) -> BatchRef:
        """Record a handle the provider has just accepted.

        Args:
            handle: What ``submit`` returned.
            kind: ``"answer"`` or ``"judge"``.
            item_count: How many items were submitted.

        Returns:
            The reference, ready to append to ``batches.jsonl``.
        """
        return cls(
            kind=kind,
            batch_key=handle.batch_key,
            batch_id=handle.batch_id,
            issuer=handle.issuer,
            submitted_at=handle.submitted_at.isoformat(),
            item_count=item_count,
        )


class RetrievalTelemetry(BaseModel):
    """What ADR-0119's traces said about the retrieval behind one answer.

    Every field is read from ``RETRIEVAL`` traces carrying the answer's correlation
    id, never asserted by the driver — the point is evidence about the pipeline.

    Attributes:
        search_calls: How many times ``MemoryStore.search`` was crossed. This is
            #1029's P4 figure. Expect one to four: ``assemble_by_band`` reads one
            band at a time and stops once the budget is full, which is up to three,
            and ADR-0158's episodic supplement is a fourth read of its own.

            **The fourth read happens only where the episodic bound is positive and
            the belief composition came back non-empty**, and both conditions are
            checked before the store is touched (``benchmarks.memory.answer._supplement``).
            The second is the one a run meets or misses per question; the first is a
            property of the whole run, which ADR-0158 §6's ablation arm may set to
            ``0`` — and a manifest whose ``episodic_limit`` is ``0`` is a run where one
            to *three* calls is the healthy count and a fourth would be the anomaly
            (#1186).
        returned_ids: Every record id any of those calls returned, in trace order,
            deduplicated. A superset of what reached the prompt, because
            ``assemble_by_band`` deduplicates and cuts to the budget.
        returned_total: The number returned across all calls, before deduplication.
        limit: The ``limit`` each call carried, in call order.
        fetch_k: The candidate budget each call actually fetched with, where the
            store observed it.
        candidates: How many candidates each call ranked, where observed.
        bands: How many bands each call restricted itself to, where observed. Beside
            the structural zeros below this is the figure that says a band predicate
            was bound at all, which is what ``memory/traces.py`` records it for.
        ceiling_bound: Whether any call's ``fetch_k`` came in below its ``limit``.
            That is the offline reading of the same fact ``MemorySearchResult.capped``
            reports to a caller: the store's own candidate ceiling bound the read, so
            it certified nothing about completeness. Derived rather than read,
            because the trace carries no ``capped`` key — ``memory/traces.py`` says
            in as many words that ``fetch_k`` below ``limit`` *is* that signal from
            the offline side.
        outcomes: Each call's ``TraceOutcome``. Anything but ``ok`` means the answer
            was produced over a degraded retrieval and the record should not be
            counted as a reader error.
        exclusions: The four per-predicate exclusion counts, summed, where the store
            observed them. **Expected to be all zeros**: since ADR-0128 §1 every
            eligibility predicate binds inside the KNN, so nothing is dropped after
            ranking and there is nothing to count. Recorded anyway, because the day
            that changes is a day this field starts carrying information and nobody
            will think to add it then.
    """

    model_config = ConfigDict(frozen=True)

    search_calls: int = 0
    returned_ids: tuple[str, ...] = ()
    returned_total: int = 0
    limit: tuple[int, ...] = ()
    fetch_k: tuple[int, ...] = ()
    candidates: tuple[int, ...] = ()
    bands: tuple[int, ...] = ()
    ceiling_bound: bool = False
    outcomes: tuple[str, ...] = ()
    exclusions: dict[str, int] = Field(default_factory=dict)


class QuestionRecord(BaseModel):
    """One question, answered and judged, with everything a post-hoc analysis reads.

    Attributes:
        run_id: Which run produced this.
        corpus: The corpus key.
        case_key: The case — one store's worth of conversation.
        question_id: The question.
        category: The corpus's own category label, unmapped.
        unanswerable: Whether abstaining is the correct behaviour.
        question: The question as asked.
        reference_answer: The corpus's answer.
        answer: What the system said.
        verdict: The grader's ruling.
        abstained: Whether the answer declined to answer.
        judge: What graded it — ``"exact"``, or ``model:<provider>:<model>`` naming the
            route the judge actually ran on. Read off the grader that graded rather
            than from a setting beside it, so a run that chose a judge route
            (``--judge-model``) records the one it used and a run that did not records
            the answering route it fell back to. The two are legitimately different: a
            judge is an instrument, not part of the system under test.
        judge_detail: The judge's own words, where it produced any.
        correlation_id: Ties this answer to its traces in ``traces.db``.
        retrieved_ids: The records placed in the prompt, in prompt order.
        retrieved_kinds: Their kinds, aligned with ``retrieved_ids``.
        retrieved_evidence: The episode ids standing behind each retrieved record,
            aligned with ``retrieved_ids`` — the episodes a belief cites, and for an
            episode its own id, so the join below is one rule over both groups
            (#1187, and :attr:`~benchmarks.memory.answer.AnswerAttempt.retrieved_evidence`
            for why an episode cites nothing to begin with).
        retrieved_evidence_elided: How many citations each retrieved record no longer
            carries (ADR-0086 §4), aligned with ``retrieved_ids``. Non-zero turns an
            empty join below into "cannot tell" rather than "never retrieved".
        evidence: The corpus's own pointer to the supporting turns, carried through
            untouched. P8's split is computed against this.
        evidence_episode_ids: For each entry of ``evidence``, in the same order, the
            captured episode ids that corpus pointer became during this run (#1074).

            **This is the join P8 needs, and it is written here because it exists
            nowhere else.** ``evidence`` is a corpus pointer — a LoCoMo ``dia_id``, a
            LongMemEval session id — and ``retrieved_ids`` are generated record ids;
            before this field nothing retained mapped one to the other, and the
            episodes carrying the link live in a ``memory.db`` a default run deletes.
            With it the split is a set intersection over this file alone: an evidence
            episode appearing somewhere in ``retrieved_evidence`` was in context and
            the reader failed; one appearing nowhere in it was never retrieved. Since
            #1187 that intersection also sees the episodes ADR-0158's supplement put in
            the prompt directly — they carry no citations of their own, so before it
            they could never satisfy the test however often they were retrieved.

            An **empty tuple** for a pointer says that pointer never became an episode
            in this run — it named a turn outside the ingested slice
            (``--max-sessions``), or its capture degraded, or the corpus gave that
            turn no pointer at all. Read it against
            ``ingestion["evidence_keys_captured"]`` before concluding anything: a case
            that mapped nothing has a *missing* split, not a negative one.
        batch_item_id: The ``item_id`` this question's answer was submitted and
            matched back under, or ``None`` on a synchronous run — where the field is
            absent rather than empty, so an older artifact and a ``--phase sync`` one
            read alike and neither claims a batch it was not in.

            **Recorded because ADR-0143 §4 makes the caller the only party that can
            check the match.** ``fetch`` returns one outcome per submitted item and
            the caller matches by ``item_id``, never by position; nothing on the
            provider's side can be asked afterwards which question an id stood for.
            Written here, the join from ``batches.jsonl`` back to a question survives
            the process, which is what makes a batch that settled after an interrupted
            run still readable.
        telemetry: What the traces said.
        asked_at: The benchmark clock's reading while the question was answered.
        context_chars: How large the rendered context block was. A crude proxy for
            how much the model had to read, kept because it costs nothing and a run
            whose contexts are near-empty is one to look at before its scores.
        ingestion: The case's ingestion summary, repeated on every record of that
            case. Denormalised deliberately: a JSONL line that cannot be read on its
            own is a format that invites a join, and the file is small.

            **It carries the case's ask rate**, which is the one harness artifact
            #1029's P3 and P5 can be silently depressed by: benchmark ingestion is
            headless, so a proposal the policy rules ``ASK_USER`` on becomes a
            question nobody answers and a belief nobody writes, and retrieval cannot
            find what was never stored. The rate is a property of *this harness* and
            not of the pipeline's answers, so it is not an aggregate ground rule 1
            forbids — nothing here says whether an answer was right.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    corpus: str
    case_key: str
    question_id: str
    category: str
    unanswerable: bool
    question: str
    reference_answer: str
    answer: str
    verdict: str
    abstained: bool
    judge: str
    judge_detail: str | None = None
    correlation_id: str
    retrieved_ids: tuple[str, ...]
    retrieved_kinds: tuple[str, ...]
    retrieved_evidence: tuple[tuple[str, ...], ...]
    retrieved_evidence_elided: tuple[int, ...]
    evidence: tuple[str, ...]
    evidence_episode_ids: tuple[tuple[str, ...], ...]
    batch_item_id: str | None = None
    telemetry: RetrievalTelemetry
    asked_at: str
    context_chars: int
    ingestion: dict[str, int | float | str | list[str]]


class ReuseRef(BaseModel):
    """Where a run's memories came from, when it did not build them itself.

    **A run that reused another's stores must be readable as one from its own
    artifacts.** Ingestion is most of what a run costs and all of what its manifest's
    observer-side fields describe, so a run that skipped it and left those fields
    reading like a fresh distillation would be a manifest that is wrong in exactly the
    place a reader checks first. This is the field that makes the reuse visible, and
    :mod:`benchmarks.memory.reuse` is where the rest of the discipline lives.

    Attributes:
        run_id: The run whose kept case stores were answered over.
        manifest_sha256: The SHA-256 of that run's ``manifest.json`` as it was read.
            The id names a directory, which is mutable; this names the bytes the
            inherited fields below were actually taken from.
        corpus_revision: The upstream revision the source was pinned to. Duplicated
            from the source manifest so the join between the two artifacts can be
            checked without opening the other one.
        embedder_model_id: The embedding space the reused vectors live in — which the
            reusing run is required to match, since a vector written under one and
            searched under another returns noise.
        inherited: The manifest fields whose values were taken from the source run
            because they describe *ingestion*, which this run did not do
            (:data:`~benchmarks.memory.reuse.INHERITED_FIELDS`). Recorded as names
            rather than as values, because the values are in this manifest already;
            what a reader cannot otherwise tell is which of them this process
            contributed and which it copied.
        varied: The answering-side fields whose values differ from the source run's —
            the arm's whole content. Empty means a re-answer under the same
            configuration, which is a legitimate thing to want (a re-run of a run that
            aborted late, a check that the harness is deterministic where it claims to
            be) and is worth being able to see at a glance.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    manifest_sha256: str
    corpus_revision: str
    embedder_model_id: str
    inherited: tuple[str, ...]
    varied: tuple[str, ...]


class RunManifest(BaseModel):
    """The configuration a run happened under, recorded rather than described.

    Attributes:
        run_id: Unique, and the directory name the artifacts live under.
        mode: :class:`RunMode`. The field that says whether these outputs may be
            read as scores.
        started_at: When the run began, wall clock, ISO-8601.
        corpus: The corpus key.
        corpus_title: Its published name.
        corpus_revision: The immutable upstream revision the data was pinned to.
        corpus_licence: Its licence.
        corpus_files: Each fetched file's name mapped to its SHA-256.
        case_count: Cases in the run.
        question_count: Questions in the run.
        slice_seed: The seed a stratified slice was drawn with, where one was.
        phase: :class:`RunPhase` — whether the answers and gradings were made one
            call at a time or through the Batches API. Ingestion is synchronous under
            both and is not on this axis.

            **Read it before reading a run's ``ungraded`` rows.** A batched run can
            record a question as ungraded for a reason a synchronous one has no way
            to produce: an item the provider expired, cancelled, or failed
            (:class:`~ai_assistant.core.types.BatchOutcomeKind`). The verdict is the
            same word and the cause is not, so the two record sets are only
            comparable with this field in hand.
        batches: Every batch this run submitted, in submission order, or empty on a
            synchronous run. The same references ``batches.jsonl`` already carries —
            duplicated here because that file is the *guard*, appended before the
            first poll so an interrupted run can still name what it is paying for,
            and this is the *record*, so a manifest describes its own run whole.
        max_sessions: The session bound the cases were shortened to, or ``0`` where the
            histories are whole. **A non-zero value means the run answered questions
            about a conversation that did not happen**, which is legitimate for a
            plumbing check and is not a measurement; it is recorded because a record
            set that cannot say which bound produced it can be neither reproduced nor
            compared. Taken from the run's plan — the selection that did the shortening
            is what sets it — rather than from what a caller said it was (#1052). A
            smoke run planned from cases with no selection recorded is the one case
            where a declaration lands here instead, and a scored run cannot be that.
        answer_route: The ``"provider:model"`` spec answers came from.
        observer_route: The spec episodes were distilled through.
        judge: What graded the answers.
        embedder_kind: The configured ``EmbedderKind``. A scored run is
            ``on-device``; ``hashing`` is a plumbing check and its outputs are not a
            measurement of retrieval at all.
        embedder_model_id: The embedding space the vectors live in.
        retrieval_limit: The budget ``assemble_by_band`` filled.
        episodic_limit: The budget ADR-0158's **episodic supplement** filled — the
            second, ``EPISODIC``-only read appended after the beliefs, whose budget is
            never a share of ``retrieval_limit`` above.

            **A manifest carrying a positive value here is a run that made the
            supplementary read**, which is why it is recorded rather than left
            implicit in the code the run happened to be cut from. Three states, and
            they are distinguishable:

            * ``None`` — the key is **absent**, which is the pilot's earlier runs:
              their harness predates ADR-0158 and made the belief read alone. It is
              optional for exactly this reason and no other. Every run this code
              writes states a number, so a ``None`` is always an older artifact and
              never a gap in a current one; that is what keeps the comparison this
              field exists for loadable at all, since the artifact a reader most needs
              to tell apart from a new one is the one written before the field existed.
            * ``0`` — the supplement was **disabled** and never read. The bound is
              checked before the store is touched, exactly as
              ``LearningLoop._supplement`` checks it, so this is not an empty read
              (ADR-0158 §6 may take the value there in both directions).
            * Positive — the read was made, on every question whose belief composition
              came back non-empty. Imported from the composition root like the budget
              above, so it cannot name a bound the product does not use.
        conflict_limit: The ingestor's conflict-probe limit.
        observation_batch_size: Turns per observation pass.
        observation_max_proposals: Beliefs one pass may return.
        observer_timezone: The IANA calendar the observation prompt showed each
            episode's ``occurred_at`` in, and the one a relative expression was
            resolved against (ADR-0156 §2, §3). Recorded because it bounds what the
            producer could state at all: two runs' temporal categories are comparable
            only if both distilled under the same calendar, and a zone far from the
            speaker's dates an evening utterance a day out. The configured
            ``Settings.timezone``, which is where every consumer of it reads it
            (ADR-0008 §6) — so a manifest naming one is also the record that the
            harness passed one rather than leaving the producer without a calendar
            (#1171). Like ``observer_route`` beside it this is the **configured**
            value rather than one read back off the producer, which nothing exposes;
            what makes it the calendar a *scored* run actually distilled under is
            :func:`~benchmarks.memory.run.refuse_ineligible_scored_run` clause 5,
            which refuses an injected observer outright for exactly this reason. A
            smoke run may inject one, and its manifest is already not a measurement.
        episode_retention: The configured horizon, or ``"none"``. **Read this before
            reading a score**: the harness runs on the corpus's clock, so a finite
            horizon expires a session's episodes a horizon after that session's own
            instant, and a corpus spanning a year under a 30-day default is one whose
            early episodes are gone before the late ones are captured.
        answer_prompt: The answering system prompt, in full.
        judge_prompt: The judging system prompt, in full, or ``None`` where the
            grader made no model call.
        notes: Anything the operator wants attached to this run.
        model_call_ceiling: The run-level bound on model calls, or ``None`` where none
            was asked for. Recorded beside ``aborted`` because the two are read
            together: a ceiling with no abort is a run that came in under budget, and a
            ceiling with an abort naming it is a run that did not.
        reused_from: The run whose kept case stores this one answered over instead of
            ingesting the corpus itself, or ``None`` — the default, and every artifact
            written before the option existed — where it ingested.

            **Read it before reading any observer-side field above.** On a reused run
            the fields naming ``inherited`` here describe the *source* run's
            distillation, because that is what wrote the beliefs being answered from;
            this process's own observer settings did nothing and are not recorded. The
            same fact is on every row of ``records.jsonl``, whose ``ingestion`` object
            carries a ``reused_from`` marker beside the source's figures, so a reader
            holding one JSONL line and no manifest is not misled either.

        aborted: Why the run stopped before finishing, or ``None`` where it ran to
            completion.

            **``None`` on an old artifact and ``None`` on a finished run mean the same
            thing here, and that is deliberate.** Every other optional field on this
            model distinguishes the two; this one does not need to, because a run that
            predates the field could not have aborted *cleanly* — it died with a
            traceback and left no manifest claim either way. So the honest reading of
            ``None`` is "this manifest does not record a clean stop", which is true of
            both.

            The field is written by rewriting ``manifest.json`` at the end of the
            run. **The manifest is rewritten at most once**, after the last case, to
            record this and ``batches`` — both being facts a run only has once it is
            over. It is otherwise written once before any case runs, so an interrupted
            run still says what it was, and the orphan guard that must survive an
            interruption is ``batches.jsonl`` rather than this file.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    mode: RunMode
    started_at: str
    corpus: str
    corpus_title: str
    corpus_revision: str
    corpus_licence: str
    corpus_files: dict[str, str]
    case_count: int
    question_count: int
    slice_seed: int | None
    phase: RunPhase = RunPhase.SYNC
    batches: tuple[BatchRef, ...] = ()
    max_sessions: int = 0
    answer_route: str
    observer_route: str
    judge: str
    embedder_kind: str
    embedder_model_id: str
    retrieval_limit: int
    episodic_limit: int | None = None
    conflict_limit: int
    observation_batch_size: int
    observation_max_proposals: int
    observer_timezone: str
    episode_retention: str
    answer_prompt: str
    judge_prompt: str | None
    notes: str = ""
    model_call_ceiling: int | None = None
    reused_from: ReuseRef | None = None
    aborted: str | None = None


class TraceCursor:
    """Reads ADR-0119 traces back, one question's worth at a time.

    **Holding the walk is what an offline analysis tool does.** ADR-0119 §7 withholds
    it from every component of the *request pipeline*, on the ground that an
    instrument whose readings change behaviour measures a system including the
    instrument. Nothing here is in a pipeline: this runs after the answer exists, in
    a process that is not the hub, and nothing it reads is an input to anything the
    system does. It is the shape ``MeasureReader`` already has.

    **Advancing to exhaustion is sound only because a benchmark run is sequential.**
    A short chunk means "nothing further yet" and never "the walk is over"
    (``TraceStore.walk``), because an append can land during a call. Here there is
    exactly one writer, it is this process, and it has finished writing for this
    question before the cursor is asked — so an empty chunk is exhaustion.
    """

    def __init__(self, store: TraceStore, *, page: int = 500) -> None:
        """Start a cursor at the store's floor.

        Args:
            store: The trace store to walk.
            page: How many traces to read per call.
        """
        self._store = store
        self._page = page
        self._position: TracePosition | None = None

    async def collect(self, correlation_id: str) -> RetrievalTelemetry:
        """Read every trace appended since the last call, and fold the retrievals.

        Traces that are not ``RETRIEVAL``, or that carry a different correlation id,
        are walked past rather than kept — an ingestion's ``MEMORY_WRITE`` traces and
        the conflict probe's own retrievals share the stream, and only this answer's
        reads are P4's figure.

        Args:
            correlation_id: The scope the answer ran under.

        Returns:
            The telemetry.
        """
        fold = _RetrievalFold()
        while True:
            chunk = await self._store.walk(after=self._position, limit=self._page)
            self._position = chunk.position
            if not chunk.traces:
                break
            for trace in chunk.traces:
                if trace.kind is TraceKind.RETRIEVAL and (
                    trace.refs.get(TraceRef.CORRELATION) == correlation_id
                ):
                    fold.add(trace)
        return fold.result()


class _RetrievalFold:
    """Accumulates the retrieval traces of one answer into one telemetry record.

    A mutable accumulator rather than a comprehension because the trace's own rule is
    that an **absent key means not observed** (ADR-0119 §3), so every field is
    conditionally appended and there is no total function over a trace to map.
    """

    def __init__(self) -> None:
        """Start empty."""
        self.calls = 0
        self.returned: list[str] = []
        self.seen: set[str] = set()
        self.total = 0
        self.limits: list[int] = []
        self.fetch: list[int] = []
        self.candidates: list[int] = []
        self.bands: list[int] = []
        self.outcomes: list[str] = []
        self.exclusions: dict[str, int] = {}
        self.ceiling_bound = False

    def add(self, trace: EvaluationTrace) -> None:
        """Fold one ``RETRIEVAL`` trace in.

        Args:
            trace: The trace, already known to be this answer's.
        """
        self.calls += 1
        self.outcomes.append(str(trace.outcome))
        self._add_returned(trace)
        asked = _observed_int(trace.metrics.get(LIMIT_KEY))
        fetched = _observed_int(trace.metrics.get(FETCH_K_KEY))
        for target, value in ((self.limits, asked), (self.fetch, fetched)):
            if value is not None:
                target.append(value)
        # `fetch_k` below `limit` is the offline reading of `MemorySearchResult.capped`
        # — `ai_assistant.memory.traces` says so where it defines the key.
        if asked is not None and fetched is not None and fetched < asked:
            self.ceiling_bound = True
        for target, key in ((self.candidates, CANDIDATES_KEY), (self.bands, BANDS_KEY)):
            value = _observed_int(trace.metrics.get(key))
            if value is not None:
                target.append(value)
        for key in EXCLUSION_KEYS:
            value = _observed_int(trace.metrics.get(key))
            if value is not None:
                self.exclusions[key] = self.exclusions.get(key, 0) + value

    def _add_returned(self, trace: EvaluationTrace) -> None:
        """Fold the trace's returned-id set in, deduplicating across calls.

        Args:
            trace: The trace.
        """
        identifiers = trace.records.get(TraceRecordSet.RETURNED)
        if identifiers is None:
            return
        self.total += identifiers.total
        for identifier in identifiers.ids:
            if identifier not in self.seen:
                self.seen.add(identifier)
                self.returned.append(identifier)

    def result(self) -> RetrievalTelemetry:
        """The folded telemetry.

        Returns:
            The record.
        """
        return RetrievalTelemetry(
            search_calls=self.calls,
            returned_ids=tuple(self.returned),
            returned_total=self.total,
            limit=tuple(self.limits),
            fetch_k=tuple(self.fetch),
            candidates=tuple(self.candidates),
            bands=tuple(self.bands),
            ceiling_bound=self.ceiling_bound,
            outcomes=tuple(self.outcomes),
            exclusions=self.exclusions,
        )


#: The metric keys ``ai_assistant.memory.traces`` writes on a retrieval.
#:
#: Written as literals rather than imported, because importing them would be this
#: harness reaching past a subsystem's public surface into the module constants of an
#: implementation — the thing golden rule 1 forbids inside the package and that a
#: consumer outside it should not do either. The cost of the copy is that it can go
#: stale silently, so it does not: ``tests/benchmarks/test_trace_vocabulary.py``
#: asserts each literal against the constant it mirrors, and fails the day one moves.
LIMIT_KEY: Final = "limit"
FETCH_K_KEY: Final = "fetch_k"
CANDIDATES_KEY: Final = "candidates"
BANDS_KEY: Final = "bands"
EXCLUSION_KEYS: Final = (
    "excluded_kind",
    "excluded_retention",
    "excluded_window",
    "excluded_band",
)


def write_jsonl_line(path: Path, payload: BaseModel) -> None:
    """Append one model to a JSONL file, creating it and its parents.

    Appending per record rather than writing at the end is deliberate: a run that
    dies at question 400 of 500 should leave 399 usable records, not an empty file.

    Args:
        path: The JSONL file.
        payload: The record to append.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload.model_dump_json())
        handle.write("\n")


def read_jsonl[ModelT: BaseModel](path: Path, model: type[ModelT]) -> tuple[ModelT, ...]:
    """Read a JSONL file back into models.

    Args:
        path: The JSONL file.
        model: The model each line validates as.

    Returns:
        The records, in file order.
    """
    lines = (line for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return tuple(model.model_validate_json(line) for line in lines)


def now_iso() -> str:
    """The wall clock, as ISO-8601 in UTC.

    Used for the manifest's ``started_at`` and for nothing the benchmark measures —
    the measurement runs on :mod:`benchmarks.memory.clock`.

    Returns:
        The instant.
    """
    return datetime.now(UTC).isoformat()


def _observed_int(value: object) -> int | None:
    """Read a metric that is an integer count, or was not observed.

    ``bool`` is excluded although it is an ``int`` subclass, for the reason
    ``Settings`` excludes it from its own counts: a flag is not a count, and a metric
    that arrived as one would be folded into a sum as 0 or 1 and say nothing.

    Args:
        value: The metric's value, or ``None`` where the crossing did not observe it.

    Returns:
        The count, or ``None``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
