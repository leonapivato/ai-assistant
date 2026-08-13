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

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field

from ai_assistant.core.types import TraceKind, TraceRecordSet, TraceRef

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
    "QuestionRecord",
    "RetrievalTelemetry",
    "RunManifest",
    "RunMode",
    "TraceCursor",
    "now_iso",
    "read_jsonl",
    "write_jsonl_line",
]


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


class RetrievalTelemetry(BaseModel):
    """What ADR-0119's traces said about the retrieval behind one answer.

    Every field is read from ``RETRIEVAL`` traces carrying the answer's correlation
    id, never asserted by the driver — the point is evidence about the pipeline.

    Attributes:
        search_calls: How many times ``MemoryStore.search`` was crossed. This is
            #1029's P4 figure. Expect one to three: ``assemble_by_band`` reads one
            band at a time and stops once the budget is full.
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
        judge: What graded it.
        judge_detail: The judge's own words, where it produced any.
        correlation_id: Ties this answer to its traces in ``traces.db``.
        retrieved_ids: The records placed in the prompt, in prompt order.
        retrieved_kinds: Their kinds, aligned with ``retrieved_ids``.
        retrieved_evidence: The episode ids each retrieved record cites, aligned with
            ``retrieved_ids``.
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
            the reader failed; one appearing nowhere in it was never retrieved.

            An **empty tuple** for a pointer says that pointer never became an episode
            in this run — it named a turn outside the ingested slice
            (``--max-sessions``), or its capture degraded, or the corpus gave that
            turn no pointer at all. Read it against
            ``ingestion["evidence_keys_captured"]`` before concluding anything: a case
            that mapped nothing has a *missing* split, not a negative one.
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
    telemetry: RetrievalTelemetry
    asked_at: str
    context_chars: int
    ingestion: dict[str, int | float | str | list[str]]


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
        conflict_limit: The ingestor's conflict-probe limit.
        observation_batch_size: Turns per observation pass.
        observation_max_proposals: Beliefs one pass may return.
        episode_retention: The configured horizon, or ``"none"``. **Read this before
            reading a score**: the harness runs on the corpus's clock, so a finite
            horizon expires a session's episodes a horizon after that session's own
            instant, and a corpus spanning a year under a 30-day default is one whose
            early episodes are gone before the late ones are captured.
        answer_prompt: The answering system prompt, in full.
        judge_prompt: The judging system prompt, in full, or ``None`` where the
            grader made no model call.
        notes: Anything the operator wants attached to this run.
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
    max_sessions: int = 0
    answer_route: str
    observer_route: str
    judge: str
    embedder_kind: str
    embedder_model_id: str
    retrieval_limit: int
    conflict_limit: int
    observation_batch_size: int
    observation_max_proposals: int
    episode_retention: str
    answer_prompt: str
    judge_prompt: str | None
    notes: str = ""


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
