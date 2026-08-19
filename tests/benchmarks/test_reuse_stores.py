"""``--from-run``: answering a corpus again over the case stores a previous run kept.

The claim this file exists to hold is **parity**: a reused run must measure the same
memories the source run measured, and say so in its own artifacts. Nothing about that
is self-evident — the stores are copied between processes, the harness clock starts at
its epoch default rather than where ingestion left it, and every ingestion-side figure
a row carries was produced by a run this one did not make. So each of those is a test:
the same retrievals come back, the clock is where ingestion left it, the evidence join
is the source's, and a reader of one JSONL line can see no ingestion happened here.

The other half is the gate. A reuse that answers over the wrong memories produces
records that look exactly like a measurement, so every precondition is a refusal and
each of them has a test — including that they all fire *before* a model call, which is
what makes a mistake cost a second instead of an hour.

Everything runs over the real stores with the two model seams replaced by the
canonical fakes, exactly as `test_run_end_to_end.py` does: the embedder is the hashing
one and the answer is scripted, so nothing here is a measurement.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import TYPE_CHECKING, Any

import pytest
from benchmarks.memory.batch import PollPolicy, item_id_for
from benchmarks.memory.cases import BenchCase, BenchQuestion, BenchSession, BenchTurn
from benchmarks.memory.corpora.provenance import LOCOMO
from benchmarks.memory.records import (
    QuestionRecord,
    RunManifest,
    RunMode,
    RunPhase,
    case_dir_name,
    read_jsonl,
)
from benchmarks.memory.reuse import (
    INGESTION_SOURCE_KEY,
    INHERITED_FIELDS,
    load_reused_run,
    refuse_ineligible_reuse,
)
from benchmarks.memory.run import execute_run, plan_run
from benchmarks.memory.select import first_sessions

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.testing import FakeModelProvider, FakeObserver
from ai_assistant.testing.batch import FakeBatchCompleter, ProgrammedOutcome

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import Observer
    from ai_assistant.core.types import (
        BatchHandle,
        BatchItemOutcome,
        BatchRequest,
        BatchStatus,
    )

pytestmark = pytest.mark.integration

FIRST = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)
LAST = FIRST + timedelta(days=35)
BATCH = 2
ISSUER = "acct-reuse-tests"


def _case(key: str = "conv-test") -> BenchCase:
    """A two-session case with two questions, one of them unanswerable.

    Args:
        key: The case key, and the prefix its question ids take.

    Returns:
        The case.
    """
    return BenchCase(
        corpus_key="locomo",
        case_key=key,
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
                    BenchTurn(speaker="Bo", text="Bo: What is her name?", user_side=False),
                    BenchTurn(speaker="Ada", text="Ada: Her name is Juno.", user_side=True),
                    BenchTurn(speaker="Bo", text="Bo: Lovely name.", user_side=False),
                ),
            ),
            BenchSession(
                session_key="session_2",
                occurred_at=LAST,
                turns=(
                    BenchTurn(speaker="Ada", text="Ada: Juno is settling in.", user_side=True),
                    BenchTurn(speaker="Bo", text="Bo: Good to hear.", user_side=False),
                ),
            ),
        ),
        questions=(
            BenchQuestion(
                question_id=f"{key}#0",
                category="1",
                question="What did Ada adopt?",
                answer="a dog",
                evidence=("D1:1",),
            ),
            BenchQuestion(
                question_id=f"{key}#1",
                category="5",
                question="Did Ada adopt a cat?",
                answer="No such information",
                unanswerable=True,
            ),
        ),
    )


#: Where a stated-instant question in `_mixed_case` moves the benchmark clock to.
MOVED = LAST + timedelta(days=200)


def _mixed_case(*, stated_first: bool) -> BenchCase:
    """A case where one question states an instant and the other does not.

    The shape both the clock restoration and the gate's expected instant have to get
    right: the stated question *moves* the clock, so an unstated question after it is
    asked at the moved reading rather than at the last session's, and which of the two
    each question gets depends on the order they are asked in.

    Args:
        stated_first: Whether the question stating an instant comes first.

    Returns:
        The case.
    """
    case = _case("mixed")
    unstated = case.questions[0].model_copy(update={"question_id": "mixed#unstated"})
    stated = case.questions[1].model_copy(update={"question_id": "mixed#stated", "asked_at": MOVED})
    ordered = (stated, unstated) if stated_first else (unstated, stated)
    return case.model_copy(update={"questions": ordered})


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    """Settings a plumbing check may use, and a scored run may not.

    Args:
        tmp_path: The test's directory.
        overrides: Fields a case varies — the answering route, the observer's.

    Returns:
        The settings.
    """
    return Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        episode_retention=None,
        observation_batch_size=BATCH,
        **overrides,
    )


async def _ingest(  # noqa: PLR0913 — each argument is one axis a test varies, and a bundle would hide which ones a case left alone
    root: Path,
    tmp_path: Path,
    *,
    cases: Sequence[BenchCase] | None = None,
    keep_stores: bool = True,
    settings: Settings | None = None,
    observer: Observer | None = None,
) -> tuple[RunManifest, Path]:
    """Run a case the ordinary way, keeping its stores for a later run to answer over.

    Args:
        root: Where run directories go — shared with the reusing run, because
            ``--from-run`` resolves an id under the ``--output`` root.
        tmp_path: The test's directory.
        cases: The cases, defaulting to one.
        keep_stores: Whether the databases survive the run.
        settings: Settings, defaulting to the plumbing ones.
        observer: The distillation seam, defaulting to a fresh fake.

    Returns:
        The manifest and the run's directory.
    """
    selected = first_sessions(cases if cases is not None else (_case(),), 0)
    manifest = await execute_run(
        plan_run(LOCOMO, selected, batch_size=BATCH),
        output_root=root,
        mode=RunMode.SMOKE,
        corpus_digests={"locomo10.json": "0" * 64},
        settings=settings if settings is not None else _settings(tmp_path),
        model=FakeModelProvider("a dog"),
        observer=observer if observer is not None else FakeObserver(max_batch_size=BATCH),
        keep_stores=keep_stores,
    )
    return manifest, root / manifest.run_id


async def _reanswer(  # noqa: PLR0913 — as above: one argument per axis a case varies
    root: Path,
    tmp_path: Path,
    source_id: str,
    *,
    cases: Sequence[BenchCase] | None = None,
    settings: Settings | None = None,
    observer: Observer | None = None,
    model: FakeModelProvider | None = None,
    phase: RunPhase = RunPhase.SYNC,
    completer: _SettlingCompleter | None = None,
    keep_stores: bool = False,
) -> tuple[RunManifest, Path]:
    """Answer the same cases again over ``source_id``'s stores.

    Args:
        root: Where run directories go, and where ``source_id`` is resolved.
        tmp_path: The test's directory.
        source_id: The run to reuse.
        cases: The cases, defaulting to one.
        settings: Settings, defaulting to the plumbing ones.
        observer: The distillation seam, defaulting to a fresh fake — which a reused
            run must never call.
        model: The answering seam, defaulting to a fresh fake.
        phase: Synchronous or batched.
        completer: The bulk-inference seam, under ``BATCH``.
        keep_stores: Whether this run's own copies survive it.

    Returns:
        The manifest and the run's directory.
    """
    selected = first_sessions(cases if cases is not None else (_case(),), 0)
    manifest = await execute_run(
        plan_run(LOCOMO, selected, batch_size=BATCH),
        output_root=root,
        mode=RunMode.SMOKE,
        corpus_digests={"locomo10.json": "0" * 64},
        settings=settings if settings is not None else _settings(tmp_path),
        model=model if model is not None else FakeModelProvider("a dog"),
        observer=observer if observer is not None else FakeObserver(max_batch_size=BATCH),
        reuse=load_reused_run(root, source_id),
        phase=phase,
        batch_completer=completer,
        issuer=ISSUER,
        poll=PollPolicy(interval=0.0, timeout=5.0),
        keep_stores=keep_stores,
    )
    return manifest, root / manifest.run_id


def _rows(run_dir: Path) -> tuple[QuestionRecord, ...]:
    """Every row a run wrote.

    Args:
        run_dir: The run's directory.

    Returns:
        The records, in file order.
    """
    return read_jsonl(run_dir / "records.jsonl", QuestionRecord)


def _tree_digest(root: Path) -> dict[str, str]:
    """Every file under ``root``, mapped to the SHA-256 of its bytes.

    Args:
        root: The directory to walk.

    Returns:
        Relative path to digest, so a comparison names the file that moved.
    """
    return {
        str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _edit_manifest(run_dir: Path, **updates: object) -> None:
    """Rewrite a finished run's manifest, to stand in for a run made differently.

    Cheaper and more precise than making a second run under each configuration the
    gate refuses — several of which (an abort, a scored mode) cannot be produced with
    injected seams at all.

    Args:
        run_dir: The run's directory.
        updates: The manifest fields to replace.
    """
    path = run_dir / "manifest.json"
    written = json.loads(path.read_text(encoding="utf-8"))
    written.update(updates)
    path.write_text(json.dumps(written), encoding="utf-8")


def _refuse(root: Path, source_id: str, cases: Sequence[BenchCase], **overrides: Any) -> None:
    """Put a reuse through the gate with everything matching except ``overrides``.

    Args:
        root: Where runs live.
        source_id: The run to reuse.
        cases: The cases the reusing run would work on.
        overrides: The preconditions a case varies.

    Raises:
        ValueError: When the gate refuses, which is what every caller asserts.
    """
    reused = load_reused_run(root, source_id)
    arguments: dict[str, Any] = {
        "mode": RunMode.SMOKE,
        "corpus_key": "locomo",
        "corpus_revision": LOCOMO.revision,
        "max_sessions": 0,
        "embedder_kind": reused.manifest.embedder_kind,
        "embedder_model_id": reused.manifest.embedder_model_id,
        "episode_retention": reused.manifest.episode_retention,
    }
    refuse_ineligible_reuse(reused, cases, **{**arguments, **overrides})


class _SettlingCompleter:
    """A ``BatchCompleter`` that settles each batch the instant it is accepted.

    The same wrapper `test_batch_phase.py` uses and for the same reason: the canonical
    fake is the seam under test, and what a test cannot wait for is a provider that
    finishes.
    """

    def __init__(self, inner: FakeBatchCompleter) -> None:
        self._inner = inner

    @property
    def issuer(self) -> str:
        """The account label handles are stamped with."""
        return self._inner.issuer

    async def submit(
        self, batch_key: str, items: Sequence[BatchRequest], *, model: str | None = None
    ) -> BatchHandle:
        """Accept a batch and settle it at once.

        Args:
            batch_key: The caller's key for it.
            items: What to answer.
            model: The route, or ``None``.

        Returns:
            The handle.
        """
        handle = await self._inner.submit(batch_key, items, model=model)
        self._inner.provider.settle(handle.batch_id)
        return handle

    async def poll(self, handle: BatchHandle) -> BatchStatus:
        """Report the batch's state.

        Args:
            handle: The batch.

        Returns:
            Its status.
        """
        return await self._inner.poll(handle)

    async def fetch(self, handle: BatchHandle) -> Sequence[BatchItemOutcome]:
        """Read a settled batch's outcomes.

        Args:
            handle: The batch.

        Returns:
            The outcomes, in the fake's deliberately jumbled order.
        """
        return await self._inner.fetch(handle)


class TestAReusedRunDoesNotIngest:
    """The point of the feature, asserted on the seam that would have cost the money."""

    async def test_the_observer_is_never_called(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        source, _ = await _ingest(root, tmp_path)
        observer = FakeObserver(max_batch_size=BATCH)

        await _reanswer(root, tmp_path, source.run_id, observer=observer)

        assert observer.batches == []

    async def test_it_still_answers_every_question(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)

        _, reused_dir = await _reanswer(root, tmp_path, source.run_id)

        assert [row.question_id for row in _rows(reused_dir)] == [
            row.question_id for row in _rows(source_dir)
        ]

    async def test_the_reused_stores_are_this_run_s_own_copies(self, tmp_path: Path) -> None:
        """Copied rather than opened in place, so the source cannot be written to."""
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)

        _, reused_dir = await _reanswer(root, tmp_path, source.run_id, keep_stores=True)

        case_dir = reused_dir / "cases" / case_dir_name("conv-test")
        assert (case_dir / "memory.db").is_file()
        assert (case_dir / "conversations.db").is_file()
        # Its own, and only its own: the source's ingestion traces stay in the source.
        assert (case_dir / "traces.db").is_file()
        assert (case_dir / "traces.db").read_bytes() != (
            source_dir / "cases" / case_dir_name("conv-test") / "traces.db"
        ).read_bytes()


class TestItAnswersOverTheSameMemories:
    """Parity with the run that ingested — the claim a cheap arm rests on."""

    async def test_it_retrieves_what_the_source_retrieved(self, tmp_path: Path) -> None:
        """Same stores, same embedder, same clock: the reads have to come back the same.

        This is the whole of the fidelity claim in one assertion. The retrieval is
        deterministic given those three, so a difference here means one of them did not
        survive the copy.
        """
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)

        _, reused_dir = await _reanswer(root, tmp_path, source.run_id)

        assert [row.retrieved_ids for row in _rows(reused_dir)] == [
            row.retrieved_ids for row in _rows(source_dir)
        ]

    async def test_the_clock_is_where_ingestion_left_it(self, tmp_path: Path) -> None:
        """LoCoMo states no ``asked_at``, so the answering instant is the last session's.

        A reused run that skipped the ingest would otherwise retrieve at the benchmark
        clock's epoch default, judging every liveness axis against 1970.
        """
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)

        _, reused_dir = await _reanswer(root, tmp_path, source.run_id)

        assert {row.asked_at for row in _rows(reused_dir)} == {LAST.isoformat()}
        assert [row.asked_at for row in _rows(reused_dir)] == [
            row.asked_at for row in _rows(source_dir)
        ]

    async def test_the_instant_is_read_off_the_source_s_own_records(self, tmp_path: Path) -> None:
        """Not recomputed from the case in hand, which is the caller's rather than the
        source run's account of what happened."""
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)
        reused = load_reused_run(root, source.run_id)

        instant = reused.instant_for(_case(), "conv-test#0")

        assert instant.isoformat() == _rows(source_dir)[0].asked_at

    @pytest.mark.parametrize("stated_first", [True, False])
    async def test_a_corpus_mixing_stated_and_unstated_instants(
        self, tmp_path: Path, stated_first: bool
    ) -> None:
        """The clock is one moving reading, so a question's instant depends on the ones
        before it.

        A stated instant moves the clock and an unstated question keeps whatever the
        one before it left, so a case reusing its own source run has to be accepted and
        reproduced under *both* orders — which is what a rule assigning every unstated
        question the last session's instant, or a clock restored once per case, gets
        wrong in opposite directions.
        """
        root = tmp_path / "runs"
        case = _mixed_case(stated_first=stated_first)
        source, source_dir = await _ingest(root, tmp_path, cases=(case,))

        _, reused_dir = await _reanswer(root, tmp_path, source.run_id, cases=(case,))

        answered_at = {row.question_id: row.asked_at for row in _rows(reused_dir)}
        assert answered_at == {row.question_id: row.asked_at for row in _rows(source_dir)}
        assert answered_at == {
            "mixed#stated": MOVED.isoformat(),
            # After the stated one it inherits the moved reading; before it, the
            # instant ingestion left.
            "mixed#unstated": (MOVED if stated_first else LAST).isoformat(),
        }

    async def test_the_evidence_join_is_the_one_ingestion_recorded(self, tmp_path: Path) -> None:
        """#1074's join is read back per question rather than recomputed."""
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)

        _, reused_dir = await _reanswer(root, tmp_path, source.run_id)

        joins = {row.question_id: row.evidence_episode_ids for row in _rows(reused_dir)}
        assert joins == {row.question_id: row.evidence_episode_ids for row in _rows(source_dir)}
        # And not vacuously equal: the evidenced question really did map to an episode.
        assert len(joins["conv-test#0"]) == 1
        assert joins["conv-test#0"][0] != ()


class TestTheArtifactsSayItDidNotIngest:
    """A reused run that read like a fresh one would be a false record."""

    async def test_every_row_names_the_run_it_answered_over(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)

        _, reused_dir = await _reanswer(root, tmp_path, source.run_id)

        for row in _rows(reused_dir):
            assert row.ingestion[INGESTION_SOURCE_KEY] == source.run_id
        # The figures beside the marker are the source's, because they are true of the
        # stores this run answered over — P8's denominators are read against them.
        inherited = dict(_rows(reused_dir)[0].ingestion)
        del inherited[INGESTION_SOURCE_KEY]
        assert inherited == dict(_rows(source_dir)[0].ingestion)

    async def test_the_manifest_records_where_the_memories_came_from(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)

        manifest, _ = await _reanswer(root, tmp_path, source.run_id)

        assert manifest.reused_from is not None
        assert manifest.reused_from.run_id == source.run_id
        assert manifest.reused_from.corpus_revision == LOCOMO.revision
        assert manifest.reused_from.embedder_model_id == source.embedder_model_id
        assert manifest.reused_from.inherited == INHERITED_FIELDS
        assert (
            manifest.reused_from.manifest_sha256
            == sha256((source_dir / "manifest.json").read_bytes()).hexdigest()
        )

    async def test_an_ingesting_run_records_no_reuse(self, tmp_path: Path) -> None:
        """The field's default, asserted so the absence stays meaningful."""
        manifest, _ = await _ingest(tmp_path / "runs", tmp_path)

        assert manifest.reused_from is None

    async def test_the_observer_side_fields_describe_the_run_that_distilled(
        self, tmp_path: Path
    ) -> None:
        """This process's observer settings did nothing, so they are not what is recorded."""
        root = tmp_path / "runs"
        source, _ = await _ingest(
            root, tmp_path, settings=_settings(tmp_path, observer_model="anthropic:distiller")
        )

        manifest, _ = await _reanswer(
            root,
            tmp_path,
            source.run_id,
            settings=_settings(tmp_path, observer_model="anthropic:someone-else"),
        )

        assert source.observer_route == "anthropic:distiller"
        assert manifest.observer_route == "anthropic:distiller"

    async def test_it_reports_the_answering_axis_this_arm_moved(self, tmp_path: Path) -> None:
        """What is varied is the arm's whole content, and a reader should not have to
        diff two manifests to find it."""
        root = tmp_path / "runs"
        source, _ = await _ingest(root, tmp_path)

        manifest, _ = await _reanswer(
            root,
            tmp_path,
            source.run_id,
            settings=_settings(tmp_path, default_model="anthropic:a-different-answerer"),
        )

        assert manifest.reused_from is not None
        assert manifest.reused_from.varied == ("answer_route",)

    async def test_a_re_answer_under_one_configuration_varies_nothing(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        source, _ = await _ingest(root, tmp_path)

        manifest, _ = await _reanswer(root, tmp_path, source.run_id)

        assert manifest.reused_from is not None
        assert manifest.reused_from.varied == ()


class TestTheSourceRunIsNotTouched:
    """Its records, traces and stores are a published measurement."""

    async def test_nothing_under_the_source_directory_changes(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)
        before = _tree_digest(source_dir)

        await _reanswer(root, tmp_path, source.run_id)

        assert _tree_digest(source_dir) == before


class TestUnderTheBatchPhase:
    """The seam a reused run answers on is the phase's, not the reuse's."""

    async def test_a_reused_run_answers_in_batches(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)
        inner = FakeBatchCompleter(issuer=ISSUER)
        case = _case()
        for question in case.questions:
            inner.provider.program(
                item_id_for(case.case_key, question.question_id),
                ProgrammedOutcome(content="a dog"),
            )

        _, reused_dir = await _reanswer(
            root,
            tmp_path,
            source.run_id,
            phase=RunPhase.BATCH,
            completer=_SettlingCompleter(inner),
        )

        rows = _rows(reused_dir)
        assert [row.question_id for row in rows] == [row.question_id for row in _rows(source_dir)]
        assert [row.batch_item_id for row in rows] == [
            item_id_for(case.case_key, question.question_id) for question in case.questions
        ]
        # The retrieval is still the source's, which is what makes a batched arm cheap
        # *and* comparable.
        assert [row.retrieved_ids for row in rows] == [
            row.retrieved_ids for row in _rows(source_dir)
        ]


class TestALoadThatCannotBeARun:
    """``--from-run`` names a run id, and a run has to be there and be readable."""

    def test_a_path_is_not_a_run_id(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="takes a run id, not a path"):
            load_reused_run(tmp_path, "../elsewhere")

    def test_an_empty_id_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="takes a run id, not a path"):
            load_reused_run(tmp_path, "")

    def test_a_run_that_is_not_there(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="no run to reuse"):
            load_reused_run(tmp_path, "deadbeefcafe")

    async def test_a_manifest_from_another_run(self, tmp_path: Path) -> None:
        """A run directory is a directory: nothing else would notice the mix-up."""
        root = tmp_path / "runs"
        first, first_dir = await _ingest(root, tmp_path)
        _, second_dir = await _ingest(root, tmp_path)
        (first_dir / "manifest.json").write_text(
            (second_dir / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8"
        )

        with pytest.raises(ValueError, match="do not describe one run"):
            load_reused_run(root, first.run_id)

    async def test_a_record_from_another_run(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        first, first_dir = await _ingest(root, tmp_path)
        _, second_dir = await _ingest(root, tmp_path)
        (first_dir / "records.jsonl").write_text(
            (second_dir / "records.jsonl").read_text(encoding="utf-8"), encoding="utf-8"
        )

        with pytest.raises(ValueError, match="do not describe one run"):
            load_reused_run(root, first.run_id)

    async def test_rows_of_one_case_that_disagree_about_its_ingestion(self, tmp_path: Path) -> None:
        """The summary is denormalised onto every row, so there is no first row to
        prefer — and the figures are the denominators P8 is read against."""
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)
        path = source_dir / "records.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[1]["ingestion"]["turns_captured"] += 1
        path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")

        with pytest.raises(ValueError, match="disagree about what ingesting it reported"):
            load_reused_run(root, source.run_id)

    async def test_a_run_that_wrote_no_records(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)
        (source_dir / "records.jsonl").unlink()

        with pytest.raises(ValueError, match=r"has no records\.jsonl"):
            load_reused_run(root, source.run_id)


class TestTheGateRefusesTheWrongMemories:
    """Every precondition, one test each — each of them a refusal, never a warning."""

    async def test_a_source_run_that_aborted(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)
        _edit_manifest(source_dir, aborted="the ceiling was reached")

        with pytest.raises(ValueError, match="cannot be reused"):
            _refuse(root, source.run_id, (_case(),))

    @pytest.mark.parametrize(
        ("override", "expected"),
        [
            ({"corpus_key": "longmemeval-s"}, "corpus"),
            ({"corpus_revision": "some-other-sha"}, "corpus revision"),
            ({"embedder_kind": "on-device"}, "embedder"),
            ({"embedder_model_id": "another/space"}, "embedding space"),
            ({"episode_retention": "30 days, 0:00:00"}, "episode retention"),
        ],
    )
    async def test_a_configuration_the_stores_were_not_written_under(
        self, tmp_path: Path, override: dict[str, Any], expected: str
    ) -> None:
        root = tmp_path / "runs"
        source, _ = await _ingest(root, tmp_path)

        with pytest.raises(ValueError, match=expected):
            _refuse(root, source.run_id, (_case(),), **override)

    async def test_a_different_session_bound(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        source, _ = await _ingest(root, tmp_path)

        with pytest.raises(ValueError, match="a different bound is a different memory"):
            _refuse(root, source.run_id, (_case(),), max_sessions=1)

    async def test_cases_carrying_no_record_of_how_they_were_selected(self, tmp_path: Path) -> None:
        """#1052's rule: nobody having written it down is not evidence the bounds match."""
        root = tmp_path / "runs"
        source, _ = await _ingest(root, tmp_path)

        with pytest.raises(ValueError, match="no record of how they were selected"):
            _refuse(root, source.run_id, (_case(),), max_sessions=None)

    async def test_a_source_run_that_kept_no_stores(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        source, _ = await _ingest(root, tmp_path, keep_stores=False)

        with pytest.raises(ValueError, match="only a run made with --keep-stores"):
            _refuse(root, source.run_id, (_case(),))

    async def test_a_question_the_source_never_answered(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        source, _ = await _ingest(root, tmp_path)
        case = _case()
        extended = case.model_copy(
            update={
                "questions": (
                    *case.questions,
                    BenchQuestion(
                        question_id="conv-test#2",
                        category="1",
                        question="Where does Ada live?",
                        answer="unknown",
                    ),
                )
            }
        )

        with pytest.raises(ValueError, match="recorded no row for question"):
            _refuse(root, source.run_id, (extended,))

    async def test_a_question_whose_corpus_pointers_moved(self, tmp_path: Path) -> None:
        """The join is a tuple positioned against those pointers, so it cannot travel."""
        root = tmp_path / "runs"
        source, _ = await _ingest(root, tmp_path)
        case = _case()
        moved = case.model_copy(
            update={
                "questions": (
                    case.questions[0].model_copy(update={"evidence": ("D1:3",)}),
                    *case.questions[1:],
                )
            }
        )

        with pytest.raises(ValueError, match="the join is positioned"):
            _refuse(root, source.run_id, (moved,))

    async def test_a_case_whose_sessions_would_answer_at_another_instant(
        self, tmp_path: Path
    ) -> None:
        """The one channel a planned case has into a reused run, and it is checked.

        Nothing about a case's sessions is captured on this path, so the only thing
        they still decide is the instant the copied store is read at — which decides
        which memories it counts as live. A same-key case with the same questions,
        the same evidence and the same session bound, but a final session a month
        later, is a different retrieval wearing the same name.
        """
        root = tmp_path / "runs"
        source, _ = await _ingest(root, tmp_path)
        case = _case()
        moved = case.model_copy(
            update={
                "sessions": (
                    *case.sessions[:-1],
                    case.sessions[-1].model_copy(update={"occurred_at": LAST + timedelta(days=30)}),
                )
            }
        )

        with pytest.raises(ValueError, match="different retrievals"):
            _refuse(root, source.run_id, (moved,))

    async def test_a_case_that_reorders_a_mixed_instant_question_list(self, tmp_path: Path) -> None:
        """Reordering moves an unstated question across the one that moves the clock.

        The reused run would answer it at the source's instant either way — the clock
        is restored per question — so what this refuses is a case whose own account of
        when it asks would not match the retrieval it is about to publish.
        """
        root = tmp_path / "runs"
        source, _ = await _ingest(root, tmp_path, cases=(_mixed_case(stated_first=False),))

        with pytest.raises(ValueError, match="different retrievals"):
            _refuse(root, source.run_id, (_mixed_case(stated_first=True),))

    async def test_a_join_that_does_not_line_up_with_its_own_pointers(self, tmp_path: Path) -> None:
        """`QuestionRecord` does not enforce the cardinality, so the gate does.

        #1074's join is positional. A row carrying fewer entries than pointers would
        republish a mapping with a pointer missing from it, and P8's
        retrieved-but-misread versus never-retrieved split would be quietly wrong
        rather than visibly absent.
        """
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)
        path = source_dir / "records.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["evidence"] = ["D1:1", "D1:3"]
        path.write_text(
            "".join(f"{json.dumps(row)}\n" for row in rows),
            encoding="utf-8",
        )
        case = _case()
        widened = case.model_copy(
            update={
                "questions": (
                    case.questions[0].model_copy(update={"evidence": ("D1:1", "D1:3")}),
                    *case.questions[1:],
                )
            }
        )

        with pytest.raises(ValueError, match="evidence-join entries"):
            _refuse(root, source.run_id, (widened,))

    async def test_two_rows_for_one_question(self, tmp_path: Path) -> None:
        """Two retrievals of one question do not say which join or instant is its."""
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)
        path = source_dir / "records.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("".join(f"{line}\n" for line in [*lines, lines[0]]), encoding="utf-8")

        with pytest.raises(ValueError, match="more than once"):
            load_reused_run(root, source.run_id)

    async def test_a_scored_run_reusing_a_smoke_run(self, tmp_path: Path) -> None:
        """A smoke run may have distilled through an injected observer, and nothing
        afterwards can tell."""
        root = tmp_path / "runs"
        source, _ = await _ingest(root, tmp_path)

        with pytest.raises(ValueError, match="a scored run cannot reuse"):
            _refuse(root, source.run_id, (_case(),), mode=RunMode.SCORED)

    async def test_a_scored_source_is_accepted(self, tmp_path: Path) -> None:
        """The other side of clause 8, so the test above is about the mode and not
        about some other refusal firing first."""
        root = tmp_path / "runs"
        source, source_dir = await _ingest(root, tmp_path)
        _edit_manifest(source_dir, mode="scored")

        _refuse(root, source.run_id, (_case(),), mode=RunMode.SCORED)


class TestTheRefusalComesBeforeAnySpend:
    """A mistake should cost a second, not an ingestion's worth of latency."""

    async def test_execute_run_refuses_at_the_boundary_that_writes_the_manifest(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "runs"
        source, _ = await _ingest(root, tmp_path, keep_stores=False)
        model = FakeModelProvider("a dog")
        observer = FakeObserver(max_batch_size=BATCH)

        with pytest.raises(ValueError, match="only a run made with --keep-stores"):
            await _reanswer(root, tmp_path, source.run_id, model=model, observer=observer)

        assert model.calls == []
        assert observer.batches == []
        # And nothing was written: the run never got as far as having a directory.
        assert sorted(path.name for path in root.iterdir()) == [source.run_id]
