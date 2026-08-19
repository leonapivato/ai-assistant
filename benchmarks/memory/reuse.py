"""Answer a finished run's cases again, over the stores it kept, without re-ingesting.

**Ingestion is the dominant cost and none of it is what an answering arm varies.**
Pilot-5 (#1210) runs four arms over one corpus; the retrieval arm and the
answer-prompt arm differ from the baseline only *after* ingestion, so re-ingesting for
each pays a second and a third time for a step whose whole output is already on disk.
A run made with ``--keep-stores`` leaves every case's ``memory.db`` and
``conversations.db`` behind; this module is how the next run opens those instead of
rebuilding them, which takes an arm from ~$45 to ~$12-15 and makes every future
ablation cheap.

**What is reused is the stores; what is *inherited* is the description of how they
were built.** A reused run's manifest cannot honestly report this process's
``ASSISTANT_OBSERVER_MODEL`` as the route that distilled the beliefs it answers from —
that route is a fact about the source run, and the current environment may name a
different one. So the ingestion-side fields are copied from the source manifest
(:data:`INHERITED_FIELDS`) and the reuse itself is recorded in
:class:`~benchmarks.memory.records.ReuseRef`, which is what lets a reader of the new
artifacts see it did not ingest — from the manifest, and from any single line of
``records.jsonl``, whose ``ingestion`` object carries the source's own figures under
an explicit :data:`INGESTION_SOURCE_KEY` marker rather than a healthy-looking fresh
summary this run did not produce.

**A setting that would also change *this* run's reads must match, or the run is
refused** (:func:`refuse_ineligible_reuse`). The embedder is the sharp case: a vector
written under one embedding space and searched under another returns neighbours that
are noise, and nothing downstream can tell that from a bad score. A setting that only
shaped ingestion — the observer's route, its batch size, its proposal ceiling, its
calendar — cannot affect an answering pass at all, so it is recorded from the source
rather than refused on.

**The evidence join needs nothing new on disk, and that is why this lane touches no
store format.** #1074 already writes ``evidence_episode_ids`` — the projection of the
case's corpus-pointer-to-episode-id mapping onto one question's own pointers — into
every row of ``records.jsonl``, precisely so that P8's split survives a run that
deleted its stores. A reused run therefore reads the join back per question from the
source's records rather than recomputing it from an :class:`~benchmarks.memory.ingest.
IngestionSummary` it never produced, and the alignment is checked rather than assumed:
the join is a tuple positioned against the question's ``evidence``, so a source row
whose ``evidence`` differs from the planned question's is refused rather than
attached.

**Nothing about the reused run is taken from the planned cases except which
questions to ask.** A reused run does not capture a turn, so a case's sessions reach it
through exactly one channel: the instant the answering clock is set to, which decides
which memories the copied store still counts as live. That instant is therefore read
off the source's own records — the ``asked_at`` it published per question — rather than
recomputed from the case in hand, and a case that would answer at a different instant
is refused. A hand-built case with the same key, questions and evidence but a session
moved by a month cannot quietly retrieve under a different clock.

**The stores are copied into the new run's case directory, never opened in place.**
The source run's ``records.jsonl``, ``traces.db`` and databases are a published
measurement, and the cheapest way to guarantee this run cannot mutate them is to never
open them: SQLite writes to a database it is asked to read (a rollback journal, a
schema migration on open), so "we only read" is a property of the code rather than of
the file. Copying also leaves the reused run's own directory a complete artifact —
``--keep-stores`` on it yields something a third run can reuse in turn. What is
deliberately *not* copied is ``traces.db``: a reused run's traces are its own
retrievals', and folding the source's ingestion traces in would leave a store no
cursor can walk honestly.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Final

from benchmarks.memory.records import (
    QuestionRecord,
    ReuseRef,
    RunManifest,
    RunMode,
    case_dir_name,
    read_jsonl,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from benchmarks.memory.cases import BenchCase, BenchQuestion

__all__ = [
    "INGESTION_SOURCE_KEY",
    "INHERITED_FIELDS",
    "STORE_FILES",
    "VARIED_FIELDS",
    "ReusedRun",
    "describe_reuse",
    "load_reused_run",
    "refuse_ineligible_reuse",
    "reuse_reference",
]

#: The manifest fields a reused run takes from the run it reuses.
#:
#: Every one of them describes *ingestion*, which a reused run did not do: the route
#: that distilled the beliefs, the window and proposal ceiling it distilled under, the
#: calendar ADR-0156 §2 has it resolve relative expressions against, and the ingestor's
#: conflict probe. None of them is read by an answering pass, so none can be
#: "overridden" here in any meaningful sense — the stores are already written. Copying
#: them is the only truthful option; leaving this process's own settings in those
#: fields would produce a manifest describing a distillation that never happened.
INHERITED_FIELDS: Final = (
    "conflict_limit",
    "observation_batch_size",
    "observation_max_proposals",
    "observer_route",
    "observer_timezone",
)

#: The manifest fields whose difference from the source run is the point of the reuse.
#:
#: These are the answering-side axes: which model answered, on what prompt, under what
#: retrieval budgets, judged by what, in which phase. :func:`reuse_reference` records
#: which of them this run actually moved, so a reader comparing two arms does not have
#: to diff two manifests to find out what changed between them.
VARIED_FIELDS: Final = (
    "answer_prompt",
    "answer_route",
    "episodic_limit",
    "judge",
    "judge_prompt",
    "phase",
    "retrieval_limit",
)

#: The databases a case's directory holds, in the order they are copied.
#:
#: ``traces.db`` is deliberately absent — see this module's docstring. ``memory.db`` is
#: the one a reused run cannot do without, and its absence is what "the source run was
#: not kept with ``--keep-stores``" looks like on disk.
STORE_FILES: Final = ("memory.db", "conversations.db", "deferrals.db")

#: The file every reused case must have, and the one refusal 6 is stated in terms of.
REQUIRED_STORE: Final = "memory.db"

#: What SQLite may keep beside a database file, all of which hold the same pages it
#: does.
#:
#: A copy of ``ai_assistant.memory.sqlite_store._SIDECARS``, which is private and so
#: cannot be imported — the same discipline
#: :data:`benchmarks.memory.wiring.BATCH_PROVIDER` is copied under. Copying the
#: database and leaving a ``-wal`` behind would silently produce a store missing every
#: page that had not been checkpointed.
_SIDECARS: Final = ("-journal", "-wal", "-shm")

#: The key a reused run's ``ingestion`` object carries, naming the run whose stores
#: were answered over.
#:
#: **A reader of one JSONL line must be able to see this run did not ingest.** The
#: figures beside it are the source's, and they are true of the stores this run
#: answered from — which is what P8's denominators are read against — but a row that
#: carried them and nothing else would read as a healthy fresh ingestion.
INGESTION_SOURCE_KEY: Final = "reused_from"


@dataclass(frozen=True, slots=True)
class ReusedRun:
    """A finished run, loaded far enough to answer its cases again.

    Attributes:
        run_dir: The source run's directory.
        manifest: Its manifest, which is where every ingestion-side fact about the
            stores comes from.
        manifest_digest: The SHA-256 of ``manifest.json`` as it was read, so a reused
            run's provenance names the exact bytes it inherited from rather than a run
            id whose directory may since have been edited.
        ingestion: Each case key mapped to the ``ingestion`` object its rows carried.
            Denormalised identically onto every row of a case, so the first row of each
            is the whole of it.
        joins: Each ``(case key, question id)`` mapped to #1074's
            ``evidence_episode_ids`` for that question.
        evidence: Each ``(case key, question id)`` mapped to the corpus pointers the
            join above is positioned against, so the alignment can be checked rather
            than assumed.
        asked_at: Each ``(case key, question id)`` mapped to the instant the source run
            answered it at, ISO-8601 — the reading of the benchmark clock, not the wall
            clock. This is the run's *published* statement of when it retrieved, and it
            is what a reused run retrieves at, so the clock is verified provenance
            rather than a figure recomputed from whatever case the caller supplied.
    """

    run_dir: Path
    manifest: RunManifest
    manifest_digest: str
    ingestion: Mapping[str, Mapping[str, int | float | str | list[str]]]
    joins: Mapping[tuple[str, str], tuple[tuple[str, ...], ...]]
    evidence: Mapping[tuple[str, str], tuple[str, ...]]
    asked_at: Mapping[tuple[str, str], str]

    @property
    def run_id(self) -> str:
        """The source run's id."""
        return self.manifest.run_id

    def stores_for(self, case: BenchCase) -> Path:
        """Where the source run put one case's databases.

        Args:
            case: The case.

        Returns:
            The directory, which need not exist — refusal 6 is what decides that.
        """
        return self.run_dir / "cases" / case_dir_name(case.case_key)

    def stage(self, case: BenchCase, destination: Path) -> None:
        """Copy one case's databases into the new run's own directory.

        Every sidecar is copied with its database, and file modes are preserved:
        ``SqliteMemoryStore`` restricts its file to ``0600`` before the first statement
        (ADR-0004 §4), and a copy that widened that would put Tier 1 pages back on a
        world-readable file.

        Args:
            case: The case whose stores to copy.
            destination: The new run's case directory, created if absent.

        Raises:
            OSError: If a file could not be copied. Deliberately unhandled: a reused
                run that cannot read its own memories has nothing to measure, and the
                failure lands before any model call.
        """
        source = self.stores_for(case)
        destination.mkdir(parents=True, exist_ok=True)
        for name in STORE_FILES:
            for suffix in ("", *_SIDECARS):
                candidate = source / f"{name}{suffix}"
                if candidate.exists():
                    shutil.copy2(candidate, destination / candidate.name)

    def ingestion_for(self, case: BenchCase) -> dict[str, int | float | str | list[str]]:
        """The ingestion object this case's rows carry, marked as inherited.

        Args:
            case: The case.

        Returns:
            The source's figures plus :data:`INGESTION_SOURCE_KEY`. A case the source
            asked no questions of contributes no figures, and the marker alone is what
            a row of it would carry — which is still the honest statement that nothing
            was ingested here.
        """
        inherited = dict(self.ingestion.get(case.case_key, {}))
        inherited[INGESTION_SOURCE_KEY] = self.run_id
        return inherited

    def instant_for(self, case: BenchCase, question_id: str) -> datetime:
        """The instant the source run retrieved this question at.

        **Per question, and not per case.** The benchmark clock is a single moving
        reading: ingestion leaves it at the last session's instant and
        ``answer_question`` moves it only where the corpus states an ``asked_at``, so
        what a question is answered at depends on every question *before* it. A reused
        run that restored the clock once per case would reproduce the source only for
        a corpus whose questions all state an instant or all state none — and would
        diverge, silently, on any mix. Restoring per question makes the reused
        retrieval instant the source's published one by construction, whatever order
        the questions arrive in.

        Args:
            case: The case.
            question_id: The question.

        Returns:
            The instant, parsed from the source's record.

        Raises:
            KeyError: If the source recorded no row for that question, which
                :func:`refuse_ineligible_reuse` refuses long before this is reached.
        """
        return datetime.fromisoformat(self.asked_at[case.case_key, question_id])

    def join_for(self, case: BenchCase, question_id: str) -> tuple[tuple[str, ...], ...]:
        """#1074's join for one question, read back off the source's records.

        Args:
            case: The case.
            question_id: The question.

        Returns:
            For each of the question's corpus pointers, in order, the episode ids it
            became when the source run ingested it.

        Raises:
            KeyError: If the source recorded no row for that question, which
                :func:`refuse_ineligible_reuse` refuses long before this is reached.
        """
        return self.joins[case.case_key, question_id]


def load_reused_run(output_root: Path, run_id: str) -> ReusedRun:
    """Load a finished run's manifest and records, ready to answer over its stores.

    The id is resolved under ``output_root``, which is the same ``--output`` the new
    run writes to: runs are named by the directory they live in, so naming one by its
    id is naming it the way every other artifact does.

    Args:
        output_root: Where run directories live.
        run_id: The source run's id — one path component, not a path.

    Returns:
        The loaded run.

    **The three artifacts must describe one run.** A run directory is a directory
    like any other: a manifest restored from one run beside another's records and
    stores is a state nothing else would notice, and the reusing run would then record
    one run's provenance while retrieving over another's memories. So the directory
    name, the manifest's own ``run_id`` and every record's are required to agree —
    which is cheap, and is the only thing tying the digest this run publishes to the
    stores it actually opened.

    Raises:
        ValueError: If ``run_id`` is not a single path component; if the directory does
            not exist; if it holds no readable ``manifest.json`` or ``records.jsonl``;
            if those artifacts name a different run from each other or from the
            directory; if two rows claim one question; if a case's rows disagree
            about what ingesting it reported; or if a row's ``asked_at`` is not a
            timezone-aware instant. Every one is a refusal rather
            than an empty result: a run that cannot be read cannot be reused, and
            discovering that after a corpus fetch would be the expensive place to find
            out.
    """
    if not run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
        msg = (
            f"--from-run takes a run id, not a path: {run_id!r}. Runs are resolved "
            f"under the --output root the new run writes to."
        )
        raise ValueError(msg)
    run_dir = output_root / run_id
    manifest_path = run_dir / "manifest.json"
    records_path = run_dir / "records.jsonl"
    if not manifest_path.is_file():
        msg = (
            f"no run to reuse at {run_dir}: --from-run names a run directory under "
            f"the --output root, holding manifest.json and records.jsonl."
        )
        raise ValueError(msg)
    if not records_path.is_file():
        msg = (
            f"run {run_id} has no records.jsonl: a reused run reads #1074's evidence "
            f"join back per question from the source's records, so a run that wrote "
            f"none cannot be reused."
        )
        raise ValueError(msg)
    raw = manifest_path.read_bytes()
    manifest = RunManifest.model_validate_json(raw)
    if manifest.run_id != run_id:
        msg = (
            f"the artifacts in {run_dir} do not describe one run: manifest.json names "
            f"run {manifest.run_id!r} while the directory it sits in is {run_id!r}. "
            f"A manifest restored beside another run's stores would have this run "
            f"publish one run's provenance for another run's memories."
        )
        raise ValueError(msg)
    ingestion: dict[str, Mapping[str, int | float | str | list[str]]] = {}
    joins: dict[tuple[str, str], tuple[tuple[str, ...], ...]] = {}
    evidence: dict[tuple[str, str], tuple[str, ...]] = {}
    asked_at: dict[tuple[str, str], str] = {}
    for record in read_jsonl(records_path, QuestionRecord):
        if record.run_id != run_id:
            msg = (
                f"the artifacts in {run_dir} do not describe one run: records.jsonl "
                f"carries a row from run {record.run_id!r}. The evidence join and the "
                f"answering instant are read out of these rows, so a row from another "
                f"run would be attached to a retrieval it never made."
            )
            raise ValueError(msg)
        key = (record.case_key, record.question_id)
        if key in joins:
            # Refused rather than resolved, because there is no honest resolution: two
            # rows for one question are two different retrievals, and taking either
            # one would attach an evidence join and an answering instant that may
            # belong to the other. A run this harness wrote never produces them.
            msg = (
                f"run {run_id} recorded question {record.question_id!r} of case "
                f"{record.case_key!r} more than once: a reused run reads the join and "
                f"the answering instant back per question, and two rows for one "
                f"question do not say which."
            )
            raise ValueError(msg)
        recorded = ingestion.setdefault(record.case_key, record.ingestion)
        if recorded != record.ingestion:
            # The summary is denormalised onto every row of a case, so two rows
            # carrying different figures are not a summary to choose between: they are
            # a file that does not say what ingesting this case reported. Taking the
            # first would republish it onto every new row, including for questions
            # whose own row said otherwise.
            msg = (
                f"rows of case {record.case_key!r} in run {run_id} disagree about what "
                f"ingesting it reported: the summary is denormalised onto every row of "
                f"a case, so there is no first row to prefer."
            )
            raise ValueError(msg)
        joins[key] = record.evidence_episode_ids
        evidence[key] = record.evidence
        asked_at[key] = _checked_instant(record, run_id=run_id)
    return ReusedRun(
        run_dir=run_dir,
        manifest=manifest,
        manifest_digest=sha256(raw).hexdigest(),
        ingestion=ingestion,
        joins=joins,
        evidence=evidence,
        asked_at=asked_at,
    )


def _checked_instant(record: QuestionRecord, *, run_id: str) -> str:
    """The instant a row says it was answered at, refused unless a clock would take it.

    **Checked at load, so the refusal is preflight.** The value is read back off a file
    and handed to :class:`~benchmarks.memory.clock.BenchmarkClock`, which refuses a
    naive instant — but by the time a case is being answered the manifest is written
    and the stores are staged, so a run that failed there would leave a directory that
    looks like a run. There is nothing to gain by discovering it late: a row whose
    instant no clock would accept is a row this harness did not write.

    Args:
        record: The source row.
        run_id: The run it came from, for the message.

    Returns:
        The instant, unchanged, as the string the gate compares.

    Raises:
        ValueError: If it is not an ISO-8601 instant, or carries no determinate offset.
    """
    complaint = (
        f"run {run_id} recorded question {record.question_id!r} of case "
        f"{record.case_key!r} as answered at {record.asked_at!r}, which is not a "
        f"timezone-aware instant: a reused run retrieves at that reading, and the "
        f"benchmark clock refuses one it cannot place."
    )
    try:
        instant = datetime.fromisoformat(record.asked_at)
    except ValueError as exc:
        raise ValueError(complaint) from exc
    if instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
        raise ValueError(complaint)
    return record.asked_at


def refuse_ineligible_reuse(  # noqa: PLR0913 — one parameter per precondition, and bundling them into a config object would hide which ones a caller left at a default
    reused: ReusedRun | None,
    cases: Sequence[BenchCase],
    *,
    mode: RunMode,
    corpus_key: str,
    corpus_revision: str,
    max_sessions: int | None,
    embedder_kind: str,
    embedder_model_id: str,
    episode_retention: str,
) -> None:
    """Refuse a reuse that would answer over the wrong memories, before any model call.

    **Every precondition for reusing a run's stores lives here, and every one is a
    refusal rather than a warning** — the shape
    :func:`~benchmarks.memory.run.refuse_ineligible_scored_run` is written in, for the
    same reason: each condition below makes the new run's own artifacts false, so a
    warning would be a run that completes, writes records that look like a
    measurement, and is not one.

    The test that decides whether a difference belongs here is whether it reaches
    *this* run's reads. A setting that only shaped ingestion is inherited into the
    manifest (:data:`INHERITED_FIELDS`) rather than refused on, because the stores are
    already written and nothing an answering pass does can be affected by it.

    1. **The source run must have finished.** An aborted run stopped mid-case, and the
       case it stopped in keeps its databases whatever ``--keep-stores`` said — so its
       store holds a conversation that was half distilled, with no artifact saying
       which half. There is no way to answer honestly over that.
    2. **Same corpus, same revision.** Different data behind the same key is different
       data; the questions would be asked of memories from another conversation.
    3. **Same session bound.** A shortened history is a different memory, and it also
       moves the instant ingestion left the clock at — which is the instant a corpus
       stating no ``asked_at`` retrieves under.
    4. **Same embedding space.** The sharpest of them: vectors written by one embedder
       and searched by another return neighbours that are noise, and no downstream
       artifact can tell that from a bad score.
    5. **Same episode retention.** The horizon is applied against the corpus clock, so
       it decides which episodes the copied stores still hold *and* what a read of them
       may return.
    6. **Every case's stores must be there.** ``memory.db`` is what a source run
       without ``--keep-stores`` deleted, so its absence is that mistake's name.
    7. **Every question must be covered by the source's records, and covered
       compatibly.** Three things are read back per question and each is checked
       rather than assumed: the evidence join is *positional*, so a row whose corpus
       pointers differ carries the wrong join and one whose entries do not line up
       with its own pointers carries a malformed one; and the answering instant this
       case implies — the question's own where it states one, and the last session's
       otherwise — must be the instant the source recorded. A reused run retrieves at
       the source's published instant whatever the case says
       (:meth:`ReusedRun.instant_for`), so a case implying another one is either
       mistaken about which memories were live or not the case the source ingested;
       either way its own artifacts would describe a retrieval that did not happen.
    8. **A scored run may only reuse a scored run.** ``refuse_ineligible_scored_run``
       makes a scored run's *own* configuration true by construction, but it can say
       nothing about the process that built the memories — a smoke run may inject a
       fake observer, and a scored run answering over stores a fake distilled would be
       labelled scored while measuring nothing. The source's own mode is the only
       evidence of that available afterwards, so it is required.

    Args:
        reused: The loaded source run, or ``None`` where this run ingests — which is
            the ordinary case and has nothing to refuse. Taking the option rather than
            being called under a condition is what keeps the whole rule in one place:
            a caller cannot reuse a run and forget to ask.
        cases: The cases this run will work on.
        mode: The mode asked for, for clause 8.
        corpus_key: The corpus this run selected from.
        corpus_revision: The revision it is pinned to.
        max_sessions: The bound this run's plan recorded — ``None`` where its cases
            carry no record of how they were selected, which is refused for the reason
            #1052 gives: nobody having written it down is not evidence that the
            histories match.
        embedder_kind: The configured ``EmbedderKind``, as the manifest spells it.
        embedder_model_id: The embedding space this run's reads will run in.
        episode_retention: The configured horizon, as the manifest spells it.

    Raises:
        ValueError: Under any of the eight.
    """
    if reused is None:
        return
    source = reused.manifest
    if source.aborted is not None:
        msg = (
            f"run {reused.run_id} aborted ({source.aborted}) and cannot be reused: the "
            f"case it stopped in keeps a half-ingested store, and nothing in the "
            f"artifacts says which case that was."
        )
        raise ValueError(msg)
    for label, mine, theirs in (
        ("corpus", corpus_key, source.corpus),
        ("corpus revision", corpus_revision, source.corpus_revision),
        ("embedder", embedder_kind, source.embedder_kind),
        ("embedding space", embedder_model_id, source.embedder_model_id),
        ("episode retention", episode_retention, source.episode_retention),
    ):
        if mine != theirs:
            msg = (
                f"run {reused.run_id} was made with {label} {theirs!r} and this run "
                f"configures {mine!r}: its stores were written under the first, so "
                f"answering them under the second measures neither. Re-ingest, or "
                f"configure this run to match."
            )
            raise ValueError(msg)
    if max_sessions is None:
        msg = (
            f"a run reusing {reused.run_id}'s stores cannot be planned from cases that "
            f"carry no record of how they were selected: the session bound decides "
            f"which conversation is in those stores, so it has to be compared rather "
            f"than assumed (#1052). Plan through "
            f"benchmarks.memory.select.first_sessions(cases, limit)."
        )
        raise ValueError(msg)
    if max_sessions != source.max_sessions:
        msg = (
            f"run {reused.run_id} ingested histories bounded at {source.max_sessions} "
            f"sessions and this run plans {max_sessions}: a different bound is a "
            f"different memory, and it moves the instant ingestion left the clock at."
        )
        raise ValueError(msg)
    _refuse_unusable_cases(reused, cases)
    if RunMode(mode) is RunMode.SCORED and source.mode is not RunMode.SCORED:
        msg = (
            f"a scored run cannot reuse {reused.run_id}, which is a "
            f"{source.mode} run: the eligibility gate makes a scored run's own "
            f"configuration true by construction and can say nothing about the process "
            f"that wrote the memories — a smoke run may have distilled them through an "
            f"injected observer. Reuse a scored run's stores."
        )
        raise ValueError(msg)


def _refuse_unusable_cases(reused: ReusedRun, cases: Sequence[BenchCase]) -> None:
    """Refuse a case whose stores are missing or whose questions the source never asked.

    Clauses 6 and 7 of :func:`refuse_ineligible_reuse`, lifted out whole: they are the
    two that walk the plan rather than compare two manifests, and the walk is what
    makes the gate long enough to be worth reading on its own.

    Args:
        reused: The source run.
        cases: The cases this run will work on.

    **The instant each question is compared at is walked, not assigned.** The
    benchmark clock is one moving reading: ingestion leaves it at the last session and
    each question that states an instant moves it, so a question stating none is asked
    at whatever the question *before* it left behind — which is the last session only
    when no earlier question stated one. Reproducing that walk here is what keeps the
    gate from refusing a case reusing its own source run.

    Args:
        reused: The source run.
        cases: The cases this run will work on.

    Raises:
        ValueError: If a case kept no memory store, if the source recorded no row for
            one of its questions, if such a row carries different corpus pointers from
            the ones the join would be attached to, or if the case puts a question at
            an instant the source did not answer it at.
    """
    for case in cases:
        store = reused.stores_for(case) / REQUIRED_STORE
        if not store.is_file():
            msg = (
                f"run {reused.run_id} kept no {REQUIRED_STORE} for case "
                f"{case.case_key!r} (looked in {store.parent}): only a run made with "
                f"--keep-stores can be reused."
            )
            raise ValueError(msg)
        instant = case.sessions[-1].occurred_at
        for question in case.questions:
            if question.asked_at is not None:
                instant = question.asked_at
            _refuse_uncarriable_question(reused, case, question, instant)


def _refuse_uncarriable_question(
    reused: ReusedRun, case: BenchCase, question: BenchQuestion, instant: datetime
) -> None:
    """Refuse a question whose row is missing, misaligned, or answered at another time.

    Clause 7 of :func:`refuse_ineligible_reuse`, one question at a time.

    Args:
        reused: The source run.
        case: The case the question belongs to.
        question: The question.
        instant: Where this case puts the question — its own stated instant, or
            wherever the clock stood after the questions before it. Walked by the
            caller, because it is a property of the sequence rather than of the
            question.

    Raises:
        ValueError: If the source recorded no row for it; if that row's corpus
            pointers differ from the ones this run plans; if its evidence join does
            not line up with its own pointers; or if this run would answer it at an
            instant the source did not answer it at.
    """
    key = (case.case_key, question.question_id)
    if key not in reused.joins:
        msg = (
            f"run {reused.run_id} recorded no row for question "
            f"{question.question_id!r} of case {case.case_key!r}: a reused run "
            f"reads #1074's evidence join back per question, so it can only "
            f"answer questions the source run also answered. Select the same "
            f"questions, or re-ingest."
        )
        raise ValueError(msg)
    if reused.evidence[key] != question.evidence:
        msg = (
            f"run {reused.run_id} recorded question {question.question_id!r} "
            f"of case {case.case_key!r} with evidence {reused.evidence[key]} "
            f"and this run plans {question.evidence}: the join is positioned "
            f"against those pointers, so it cannot be carried across."
        )
        raise ValueError(msg)
    if len(reused.joins[key]) != len(question.evidence):
        msg = (
            f"run {reused.run_id} recorded {len(reused.joins[key])} evidence-join "
            f"entries for the {len(question.evidence)} pointer(s) of question "
            f"{question.question_id!r} of case {case.case_key!r}: #1074's join is "
            f"positional, so a row whose entries do not line up with its own pointers "
            f"would drop a pointer out of P8's split silently."
        )
        raise ValueError(msg)
    if reused.asked_at[key] != instant.isoformat():
        msg = (
            f"run {reused.run_id} answered question {question.question_id!r} of case "
            f"{case.case_key!r} at {reused.asked_at[key]} and this case puts it at "
            f"{instant.isoformat()}: the copied store's liveness axes are judged "
            f"against that instant, so the two are different retrievals and the "
            f"comparison the reuse claims is not one."
        )
        raise ValueError(msg)


def describe_reuse(manifest: RunManifest, reused: ReusedRun | None) -> RunManifest:
    """Put the reuse into the manifest, or hand back a manifest that ingested.

    The ingestion-side fields describe the run that *wrote* these stores, because this
    run did not write them and its own observer settings did nothing at all. The
    reference is computed against the manifest **after** that inheritance, so a field
    this run inherited can never be reported as one it varied.

    Args:
        manifest: The manifest as this run's own configuration built it.
        reused: The source run, or ``None`` where this run ingested — in which case the
            manifest is already the whole truth and is returned untouched.

    Returns:
        The manifest to write.
    """
    if reused is None:
        return manifest
    inherited = manifest.model_copy(
        update={name: getattr(reused.manifest, name) for name in INHERITED_FIELDS}
    )
    return inherited.model_copy(update={"reused_from": reuse_reference(reused, inherited)})


def reuse_reference(reused: ReusedRun, manifest: RunManifest) -> ReuseRef:
    """Record where this run's memories came from, and what it changed.

    Args:
        reused: The source run.
        manifest: The new run's manifest, **after** :data:`INHERITED_FIELDS` have been
            taken from the source — so a field this run inherited can never be reported
            as one it varied.

    Returns:
        The provenance record the manifest carries.
    """
    return ReuseRef(
        run_id=reused.run_id,
        manifest_sha256=reused.manifest_digest,
        corpus_revision=reused.manifest.corpus_revision,
        embedder_model_id=reused.manifest.embedder_model_id,
        inherited=INHERITED_FIELDS,
        varied=tuple(
            name
            for name in VARIED_FIELDS
            if getattr(manifest, name) != getattr(reused.manifest, name)
        ),
    )
