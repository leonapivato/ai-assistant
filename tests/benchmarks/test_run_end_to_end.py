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
from benchmarks.memory.answer import RETRIEVED_HEADING
from benchmarks.memory.cases import BenchCase, BenchQuestion, BenchSession, BenchTurn
from benchmarks.memory.corpora.provenance import LOCOMO
from benchmarks.memory.grade import ExactGrader
from benchmarks.memory.ingest import ingest_case
from benchmarks.memory.records import QuestionRecord, RunManifest, RunMode, read_jsonl
from benchmarks.memory.run import case_dir_name, execute_run, plan_run
from benchmarks.memory.select import first_questions, first_sessions
from benchmarks.memory.wiring import build_harness
from harness_reconcilers import OFFLINE_ROUTE, offline_reconciler

from ai_assistant.app import composition
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError, ModelUnavailableError
from ai_assistant.core.types import Message, Role
from ai_assistant.orchestration.conversations import CaptureReport
from ai_assistant.testing import FakeModelProvider, FakeObserver

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

pytestmark = pytest.mark.integration

FIRST = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)
BATCH = 2

#: The observation proposal ceiling `plan_run` bounds the reconciler's calls by.
#: Any positive number serves — no test below reads the figure back — but it is
#: passed rather than defaulted for the reason `plan_run` requires it: a planner
#: filling one in reports the cost of a run nobody asked for (#1293).
PROPOSALS = 3


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


def _cat_case() -> BenchCase:
    """A case keyed `a_b` — what `"a/b"` sanitises to — about nobody in `_case`.

    Every belief it can produce is distilled from these turns, so a record id it
    retrieves that also appears under the other case is a shared store and nothing
    else.

    Returns:
        The case.
    """
    return BenchCase(
        corpus_key="locomo",
        case_key="a_b",
        sessions=(
            BenchSession(
                session_key="session_1",
                occurred_at=FIRST,
                turns=(
                    BenchTurn(speaker="Cy", text="Cy: I moved to Lisbon.", user_side=True),
                    BenchTurn(speaker="Di", text="Di: How is the weather?", user_side=False),
                    BenchTurn(speaker="Cy", text="Cy: Warm all winter.", user_side=True),
                    BenchTurn(speaker="Di", text="Di: Enviable.", user_side=False),
                ),
            ),
        ),
        questions=(
            BenchQuestion(
                question_id="a_b#0",
                category="1",
                question="Where did Cy move?",
                answer="Lisbon",
                evidence=("D1:1",),
            ),
        ),
    )


def _settings(tmp_path: Path, *, timezone: str = "UTC") -> Settings:
    """Settings a plumbing check may use, and a scored run may not.

    `hashing` keeps ONNX out of the test; `episode_retention=None` keeps the first
    session's episodes alive under the corpus clock across the 35-day gap, which is the
    configuration the CLI warns a real run into.

    Args:
        tmp_path: The test's directory.
        timezone: The calendar the observation prompt runs under. Named explicitly so
            a case can choose one no default could produce.

    Returns:
        The settings.
    """
    return Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        episode_retention=None,
        observation_batch_size=BATCH,
        timezone=timezone,
    )


async def _run(
    tmp_path: Path, *, mode: RunMode = RunMode.SMOKE, timezone: str = "UTC"
) -> tuple[RunManifest, Path]:
    """Execute one run over the fixture case.

    Args:
        tmp_path: The test's directory.
        mode: The run mode.
        timezone: The calendar the run is configured with.

    Returns:
        The manifest and the run's output directory.
    """
    settings = _settings(tmp_path, timezone=timezone)
    plan = plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS)
    root = tmp_path / "runs"
    manifest = await execute_run(
        plan,
        output_root=root,
        mode=mode,
        corpus_digests={"locomo10.json": "0" * 64},
        settings=settings,
        model=FakeModelProvider("a dog"),
        observer=FakeObserver(max_batch_size=BATCH),
        reconciler=offline_reconciler(),
    )
    return manifest, root / manifest.run_id


def test_plan_counts_exchanges_and_passes_without_touching_anything() -> None:
    """Six utterances fold into three exchanges — session 1's four turns pair into
    two, session 2's two into one — and three exchanges at a batch of two is one full
    pass plus a closing partial one."""
    plan = plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS)

    assert plan.turn_count == 3
    assert plan.observation_calls == 2
    assert plan.answer_calls == 2
    assert plan.judge_calls == 1  # the unanswerable one needs no judge call
    # One reconciler request per proposal at most, and a pass yields at most
    # `max_proposals` of them — the loosest of the four bounds, and the reason it is
    # its own field rather than folded silently into the total (#1293).
    assert plan.reconciler_calls == 6
    assert plan.model_calls == 11


def test_the_plan_s_total_leaves_out_no_seam_that_spends() -> None:
    """A seam missing from the total is a seam ``--max-model-calls`` does not bound.

    Not hypothetical: the reconciler spent nothing for two pilots because it was never
    wired (#1293), and the first thing wiring it does is put thousands of paid calls
    behind a ceiling computed without them. Stated over the fields rather than a
    literal, so the next seam to arrive fails here unless it is counted.
    """
    plan = plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS)

    assert plan.model_calls == (
        plan.observation_calls + plan.answer_calls + plan.judge_calls + plan.reconciler_calls
    )


def test_plan_refuses_a_non_positive_batch() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        plan_run(LOCOMO, (_case(),), batch_size=0, max_proposals=PROPOSALS)


def test_plan_refuses_a_non_positive_proposal_ceiling() -> None:
    """The bound the reconciler's ceiling is computed from, refused on the terms the
    batch size beside it is refused on."""
    with pytest.raises(ValueError, match="max_proposals must be positive"):
        plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=0)


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


async def test_the_manifest_names_the_reconciler_that_was_built_not_the_one_configured(
    tmp_path: Path,
) -> None:
    """#1293's failure, made unreachable: the field is an account of an object.

    Two pilots exported ``ASSISTANT_RECONCILER_MODEL`` and recorded it while
    ``build_harness`` passed no reconciler at all, so the manifest named a mechanism
    that had never run. A field assembled from ``Settings`` cannot tell those apart —
    it is true either way. This run therefore configures one route and injects a
    reconciler naming another, and asserts the manifest reports what was *built*: a
    field rebuilt from the settings would say ``claude-configured`` here.
    """
    settings = _settings(tmp_path).model_copy(
        update={"reconciler_model": "anthropic:claude-configured"}
    )
    root = tmp_path / "runs"
    manifest = await execute_run(
        plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS),
        output_root=root,
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=settings,
        model=FakeModelProvider("a dog"),
        observer=FakeObserver(max_batch_size=BATCH),
        reconciler=offline_reconciler(),
    )

    written = json.loads((root / manifest.run_id / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.reconciler is not None
    assert OFFLINE_ROUTE in manifest.reconciler
    assert "claude-configured" not in manifest.reconciler
    # And it reached the artifact, which is the only copy an analysis has.
    assert written["reconciler"] == manifest.reconciler


async def test_a_manifest_written_before_the_episodic_supplement_still_loads(
    tmp_path: Path,
) -> None:
    """The one reason `episodic_limit` is optional, asserted rather than asserted about.

    The field's whole purpose is telling a supplemented run apart from a
    pre-ADR-0158 one, and the artifacts on the other side of that comparison were
    written before the key existed. A required field would raise on exactly those,
    which is the analysis the field exists to make possible. The legacy shape is
    produced by deleting the key from a real manifest rather than by hand-writing
    one, so this cannot drift from what the model actually emits.
    """
    manifest, run_dir = await _run(tmp_path)
    written = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest.episodic_limit == composition.EPISODIC_SUPPLEMENT_LIMIT
    assert written["episodic_limit"] == composition.EPISODIC_SUPPLEMENT_LIMIT

    del written["episodic_limit"]
    legacy = RunManifest.model_validate(written)

    assert legacy.episodic_limit is None
    assert legacy.retrieval_limit == manifest.retrieval_limit


async def test_the_manifest_records_the_calendar_the_run_distilled_under(
    tmp_path: Path,
) -> None:
    """Which zone the observation prompt ran under decides what a belief could say
    about when something happened (ADR-0156 §2, §3), so two runs' temporal categories
    are comparable only if it is the same one.

    The manifest is the run's self-description, and this is configuration it could not
    otherwise be asked for afterwards: the databases hold the beliefs, not the calendar
    they were read in. A zone far from UTC is used so the field could not be passing on
    the default.
    """
    manifest, run_dir = await _run(tmp_path, timezone="Pacific/Kiritimati")

    assert manifest.observer_timezone == "Pacific/Kiritimati"
    written = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert written["observer_timezone"] == "Pacific/Kiritimati"


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
    """#1029's P4. One to four: `assemble_by_band` reads band by band and stops once
    the budget is full, which is up to three, and ADR-0158's episodic supplement is a
    fourth read of its own. Above zero is what proves the correlation scope actually
    reaches the store's emitter."""
    _, run_dir = await _run(tmp_path)

    records = read_jsonl(run_dir / "records.jsonl", QuestionRecord)

    for record in records:
        assert 1 <= record.telemetry.search_calls <= 4
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
    # Two passes over three turns at a batch of two: the first reads turns 1 and 2, the
    # closing flush reads turn 3 and nothing else. Against the tail read this pass
    # re-read turn 2 as well; against the watermark it reads only what is above it, so
    # every turn is read exactly once and nothing is re-observed (ADR-0220 §§1, 3).
    assert ingestion["episodes_read"] == 3
    assert ingestion["episodes_reobserved"] == 0


async def test_beliefs_distilled_from_the_conversation_reach_the_prompt(
    tmp_path: Path,
) -> None:
    """The end-to-end property: capture wrote episodes, observation distilled them
    into the store, and retrieval found them. A run where this is empty is a run
    whose scores would be about an empty memory.

    Since ADR-0158 the prompt legitimately carries episodes too, so the belief half is
    read off the leading run rather than off the whole set — and the split doubles as
    §4's ordering asserted where it is observable from the artifact a reader has: an
    episode ahead of a belief here would be the interleaving the ADR forbids."""
    _, run_dir = await _run(tmp_path)

    records = read_jsonl(run_dir / "records.jsonl", QuestionRecord)

    assert records[0].retrieved_ids
    assert records[0].context_chars > 0
    kinds = records[0].retrieved_kinds
    beliefs = tuple(kind for kind in kinds if kind != "episodic")
    assert beliefs, "no belief reached the prompt, so the distillation half proved nothing"
    assert set(beliefs) <= {"semantic", "preference", "procedural"}
    assert kinds[: len(beliefs)] == beliefs, "an episode was placed ahead of a belief"


async def test_the_answer_reads_only_retrieved_context(tmp_path: Path) -> None:
    """The corpus is not reachable from the answering path; only the record list is.

    **The witness had to change with ADR-0158 and the property did not.** A verbatim
    corpus turn now reaches the prompt legitimately, as an episode the supplement
    retrieved, so "this turn's text is absent" stopped being evidence of anything. What
    still holds — and is what the module claims — is that the corpus reaches the model
    *only* through records the store returned: the turn appears inside a rendered
    record and nowhere else in what was sent, and the corpus fields no record can carry
    (the answer key, the evidence pointer, the case's other question) appear nowhere at
    all.

    Since #1189 the block is the product's own bullets rather than a dump of each
    record's JSON, so the witness is read off the rendered line instead of off a
    parsed record — the property is the same one and the text it is read from is the
    text the model was actually shown. Since #1194 a second corpus turn reaches it
    legitimately as well: an episode's ``outcome``, which the product's renderer now
    shows on the bullet's continuation line."""
    settings = _settings(tmp_path)
    model = FakeModelProvider("a dog")
    plan = plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS)

    await execute_run(
        plan,
        output_root=tmp_path / "runs",
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=settings,
        model=model,
        observer=FakeObserver(max_batch_size=BATCH),
        reconciler=offline_reconciler(),
    )

    sent = "\n".join(message.content for message in model.calls[0].messages)
    block = sent.split(RETRIEVED_HEADING, 1)[1].split("\n\nQuestion:", 1)[0]
    rendered = [line for line in block.splitlines() if line.startswith("  - [")]

    # A *user-side* turn, on the record's own bullet.
    witness = "Ada: Her name is Juno."
    assert any(witness in line for line in rendered), (
        "the fixture no longer puts a corpus turn in the prompt, so this proves nothing"
    )
    assert witness not in sent.replace(block, ""), (
        "a corpus turn reached the prompt outside the retrieved records"
    )
    # And the *other* speaker's turn, which corpus ingestion stores as that episode's
    # `outcome`. It used to be asserted absent, because `planner._render_record`
    # rendered `content` alone and the withholding was `planning`'s rather than this
    # harness's (#1194). The renderer shows it now, so the assertion flips — and the
    # property under test does not: it still reaches the model only inside a rendered
    # record, on the continuation line under that record's own bullet.
    reply = "Bo: Lovely name."
    outcomes = [line for line in block.splitlines() if line.startswith("    how it turned out:")]
    assert any(reply in line for line in outcomes), (
        "an episode's outcome did not reach the prompt, which the product's renderer shows"
    )
    assert reply not in sent.replace(block, ""), (
        "a corpus turn reached the prompt outside the retrieved records"
    )
    for withheld in ("No such information", "D1:1", "Did Ada adopt a cat?"):
        assert withheld not in sent, f"{withheld!r} is corpus material no record carries"
    assert "Question: What did Ada adopt?" in sent


async def test_the_traces_survive_the_run_and_the_stores_do_not(tmp_path: Path) -> None:
    """`traces.db` is the ADR-0119 record P8's analysis is defined over; `memory.db`
    is thousands of vectors nothing reads afterwards."""
    _, run_dir = await _run(tmp_path)

    case_dir = run_dir / "cases" / case_dir_name("conv-test")
    assert (case_dir / "traces.db").exists()
    assert not (case_dir / "memory.db").exists()
    assert not (case_dir / "conversations.db").exists()


async def test_keeping_the_stores_is_available(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    plan = plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS)
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
        reconciler=offline_reconciler(),
    )

    kept = root / manifest.run_id / "cases" / case_dir_name("conv-test")
    assert (kept / "memory.db").exists()
    assert kept.name.startswith("conv-test-")  # recognisable, which is what the flag is for


def test_keys_that_sanitise_alike_still_name_different_directories() -> None:
    """The collision the digest exists to close: `"a/b"` and `"a_b"` both sanitise to
    `a_b`, and a case directory is a memory."""
    assert case_dir_name("a/b") != case_dir_name("a_b")
    assert case_dir_name("a/b").startswith("a_b-")
    assert case_dir_name("conv-26") == case_dir_name("conv-26")


def test_a_plan_refuses_two_cases_under_one_key() -> None:
    """No naming scheme separates a key from itself, so the refusal is the only
    place this can be caught — and it is caught before anything is spent."""
    with pytest.raises(ValueError, match="distinct case_key"):
        plan_run(LOCOMO, (_case(), _case()), batch_size=BATCH, max_proposals=PROPOSALS)


async def test_colliding_keys_get_their_own_stores(tmp_path: Path) -> None:
    """Two cases whose keys sanitise alike each keep their own memory: sharing one
    directory would let the dog case's beliefs answer the cat case's questions."""
    plan = plan_run(
        LOCOMO, (_case(key="a/b"), _cat_case()), batch_size=BATCH, max_proposals=PROPOSALS
    )
    root = tmp_path / "runs"

    manifest = await execute_run(
        plan,
        output_root=root,
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=FakeModelProvider("a dog"),
        observer=FakeObserver(max_batch_size=BATCH),
        keep_stores=True,
        reconciler=offline_reconciler(),
    )

    run_dir = root / manifest.run_id
    names = {case_dir_name("a/b"), case_dir_name("a_b")}
    assert {path.name for path in (run_dir / "cases").iterdir()} == names
    assert all((run_dir / "cases" / name / "memory.db").exists() for name in names)

    retrieved: dict[str, set[str]] = {}
    for record in read_jsonl(run_dir / "records.jsonl", QuestionRecord):
        retrieved.setdefault(record.case_key, set()).update(record.retrieved_ids)
    assert retrieved.keys() == {"a/b", "a_b"}
    assert retrieved["a/b"]
    assert retrieved["a_b"]
    assert not retrieved["a/b"] & retrieved["a_b"]


async def test_a_degraded_capture_does_not_cost_the_episode_before_it(tmp_path: Path) -> None:
    """`capture` appends the turn before it writes the episode, so an episode-stage
    failure leaves a turn whose id no longer resolves — and `ObservationStage` reads the
    most recent `batch_size` *turns*, skipping an unresolvable one without backfilling.
    That turn holds a window slot. Pacing on successful captures alone would let the
    episode before it fall out of every window ever read, undistilled and silently."""
    settings = _settings(tmp_path)
    observer = FakeObserver(max_batch_size=BATCH)
    harness = build_harness(
        settings,
        data_dir=tmp_path / "case",
        model=FakeModelProvider("x"),
        observer=observer,
        reconciler=offline_reconciler(),
    )
    real_capture = harness.lifecycle.capture
    # The *middle* exchange of three, so the degraded turn sits between two successes.
    # At a batch of two that is what pushes the first episode out of every window the
    # buggy cadence would ever read; degrading the last exchange proves nothing, because
    # the episode before it has already been observed by the pass that filled.
    degrade_on = "Her name is Juno."

    async def _capture(conversation_id: str, *, content: str, **kwargs: object) -> CaptureReport:
        """Capture for real, then fail the episode the way the store failing would.

        Deleting the episode after the turn is appended reproduces the exact state an
        episode-stage failure (or §8's compensation) leaves behind: the turn stands,
        its episode is gone, and the report says degraded.
        """
        report = await real_capture(conversation_id, content=content, **kwargs)  # type: ignore[arg-type]
        if degrade_on not in content or report.episode_id is None:
            return report
        await harness.store.delete(report.episode_id)
        return CaptureReport(conversation_id=conversation_id, degraded=True)

    try:
        harness.lifecycle.capture = _capture  # type: ignore[method-assign]
        summary = await ingest_case(harness, _case(), batch_size=BATCH)
    finally:
        harness.close()

    observed = "\n".join(episode.content for batch in observer.batches for episode in batch)
    assert summary.turns_degraded == 1
    # The episode captured *before* the degraded turn is the one the defect lost.
    assert "adopted a dog" in observed


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
        plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS),
        output_root=tmp_path / "runs",
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=model,
        observer=FakeObserver(max_batch_size=BATCH),
        reconciler=offline_reconciler(),
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
        plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS),
        output_root=tmp_path / "runs",
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=_FailsOnceProvider(fail_on=1),
        observer=FakeObserver(max_batch_size=BATCH),
        reconciler=offline_reconciler(),
    )

    failed = read_jsonl(tmp_path / "runs" / manifest.run_id / "records.jsonl", QuestionRecord)[0]

    assert failed.answer == ""
    assert failed.retrieved_ids
    assert 1 <= failed.telemetry.search_calls <= 4
    assert failed.telemetry.returned_ids


async def test_the_manifest_records_a_session_bound(tmp_path: Path) -> None:
    """A record set that cannot say which bound produced it can be neither reproduced
    nor compared. This plan was built from a bare tuple, which records no selection —
    the one case where the caller's declaration is all anyone has, and reachable only
    by a smoke run because the gate refuses a scored one planned that way."""
    manifest = await execute_run(
        plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS),
        output_root=tmp_path / "runs",
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=FakeModelProvider("a dog"),
        observer=FakeObserver(max_batch_size=BATCH),
        max_sessions=2,
        reconciler=offline_reconciler(),
    )

    assert manifest.max_sessions == 2


async def test_a_whole_history_records_a_zero_bound(tmp_path: Path) -> None:
    manifest, _ = await _run(tmp_path)

    assert manifest.max_sessions == 0


async def test_a_scored_run_cannot_truncate_in_selection_and_declare_nothing(
    tmp_path: Path,
) -> None:
    """#1052, in the shape the issue records it: the shortening happens in selection and
    the bound used to be a separate argument to this function, so a caller could cut the
    histories to two sessions, pass `max_sessions=0`, and have the gate wave through a
    run whose manifest claimed whole histories while every answer came from a truncated
    memory. The bound now comes from the plan, so the declaration cannot be the thing
    that is checked."""
    settings = _settings(tmp_path).model_copy(update={"embedder": EmbedderKind.ON_DEVICE})
    plan = plan_run(
        LOCOMO, first_sessions((_case(),), 1), batch_size=BATCH, max_proposals=PROPOSALS
    )

    with pytest.raises(ValueError, match="different memory"):
        await execute_run(
            plan,
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=settings,
            grader_kind="model",
            preregistration_final=True,
            max_sessions=0,
            reconciler=offline_reconciler(),
        )

    assert not (tmp_path / "runs").exists()


async def test_a_scored_run_sees_a_bound_a_question_limit_passed_through(
    tmp_path: Path,
) -> None:
    """The levers compose in either order, and the CLI applies the question one second.
    A gate that only saw the bound when `first_sessions` was the outermost call would be
    bypassed by putting the other lever after it."""
    settings = _settings(tmp_path).model_copy(update={"embedder": EmbedderKind.ON_DEVICE})
    cases = first_questions(first_sessions((_case(),), 1), 1)

    with pytest.raises(ValueError, match="different memory"):
        await execute_run(
            plan_run(LOCOMO, cases, batch_size=BATCH, max_proposals=PROPOSALS),
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=settings,
            grader_kind="model",
            preregistration_final=True,
            reconciler=offline_reconciler(),
        )


async def test_a_scored_run_is_refused_when_the_plan_records_no_selection(
    tmp_path: Path,
) -> None:
    """The complement of the bypass: cases handed in as a bare tuple say nothing about
    what was done to them, and "nobody wrote it down" is not evidence of a whole
    history. Refusing it is what stops the derivation from being sidestepped by simply
    not using the selection layer."""
    settings = _settings(tmp_path).model_copy(update={"embedder": EmbedderKind.ON_DEVICE})

    with pytest.raises(ValueError, match="no record of how"):
        await execute_run(
            plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS),
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=settings,
            grader_kind="model",
            preregistration_final=True,
            reconciler=offline_reconciler(),
        )


async def test_the_manifest_records_a_bound_no_caller_declared(tmp_path: Path) -> None:
    """The figure comes from the selection that applied it, so it reaches the manifest
    with no declaration made anywhere — which is the whole of #1052: the record and the
    data can no longer be two separate inputs that disagree."""
    manifest = await execute_run(
        plan_run(LOCOMO, first_sessions((_case(),), 1), batch_size=BATCH, max_proposals=PROPOSALS),
        output_root=tmp_path / "runs",
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=FakeModelProvider("a dog"),
        observer=FakeObserver(max_batch_size=BATCH),
        reconciler=offline_reconciler(),
    )

    assert manifest.max_sessions == 1


async def test_a_declaration_that_disagrees_with_the_plan_is_refused(
    tmp_path: Path,
) -> None:
    """A smoke run is not a measurement and the derived bound is what lands in the
    manifest either way, so nothing recorded here would be false. It is refused anyway:
    the caller believes something about its own data that is not true, and quietly
    correcting that on the smoke run leaves the belief in place for the scored one."""
    with pytest.raises(ValueError, match="declares max_sessions=0"):
        await execute_run(
            plan_run(
                LOCOMO, first_sessions((_case(),), 1), batch_size=BATCH, max_proposals=PROPOSALS
            ),
            output_root=tmp_path / "runs",
            mode=RunMode.SMOKE,
            corpus_digests={},
            settings=_settings(tmp_path),
            model=FakeModelProvider("a dog"),
            observer=FakeObserver(max_batch_size=BATCH),
            max_sessions=0,
            reconciler=offline_reconciler(),
        )

    assert not (tmp_path / "runs").exists()


async def test_a_bound_the_selection_never_reached_is_no_contradiction(
    tmp_path: Path,
) -> None:
    """`--max-sessions 99` over a two-session case shortened nothing, so the histories
    are whole, the manifest says `0`, and the declaration is not treated as a
    disagreement. Refusing it would fail a run that is entirely legitimate."""
    manifest = await execute_run(
        plan_run(LOCOMO, first_sessions((_case(),), 99), batch_size=BATCH, max_proposals=PROPOSALS),
        output_root=tmp_path / "runs",
        mode=RunMode.SMOKE,
        corpus_digests={},
        settings=_settings(tmp_path),
        model=FakeModelProvider("a dog"),
        observer=FakeObserver(max_batch_size=BATCH),
        max_sessions=99,
        reconciler=offline_reconciler(),
    )

    assert manifest.max_sessions == 0


async def test_execute_run_refuses_an_ineligible_scored_run_itself(tmp_path: Path) -> None:
    """The gate lives at the boundary that writes the manifest, not only at the command
    line: this function is exported, and a caller reaching it directly could otherwise
    label an ineligible run `scored`."""
    with pytest.raises(PermissionError):
        await execute_run(
            plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS),
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=_settings(tmp_path),
            model=FakeModelProvider("a dog"),
            observer=FakeObserver(max_batch_size=BATCH),
            reconciler=offline_reconciler(),
        )

    assert not (tmp_path / "runs").exists()


async def test_execute_run_refuses_a_scored_run_on_the_hashing_embedder(
    tmp_path: Path,
) -> None:
    """Confirmed, whole histories — and still refused, because `_settings` selects the
    QA embedder and the exact grader. `first_sessions(..., 0)` is how "whole" is stated
    to the gate now: the bound comes from the plan's own selection."""
    with pytest.raises(ValueError, match="non-semantic"):
        await execute_run(
            plan_run(
                LOCOMO, first_sessions((_case(),), 0), batch_size=BATCH, max_proposals=PROPOSALS
            ),
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=_settings(tmp_path),
            model=FakeModelProvider("a dog"),
            observer=FakeObserver(max_batch_size=BATCH),
            preregistration_final=True,
            reconciler=offline_reconciler(),
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
            plan_run(
                LOCOMO, first_sessions((_case(),), 0), batch_size=BATCH, max_proposals=PROPOSALS
            ),
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=settings,
            grader_kind="exact",
            preregistration_final=True,
            reconciler=offline_reconciler(),
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
            plan_run(
                LOCOMO, first_sessions((_case(),), 0), batch_size=BATCH, max_proposals=PROPOSALS
            ),
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=settings,
            grader_kind="model",
            model=FakeModelProvider("a dog"),
            observer=FakeObserver(max_batch_size=BATCH),
            preregistration_final=True,
            reconciler=offline_reconciler(),
        )


async def test_execute_run_names_every_injected_seam_in_its_refusal(
    tmp_path: Path,
) -> None:
    """A refusal naming one of three overrides sends the reader round the loop twice."""
    settings = _settings(tmp_path).model_copy(update={"embedder": EmbedderKind.ON_DEVICE})

    with pytest.raises(ValueError, match="injected seam") as caught:
        await execute_run(
            plan_run(
                LOCOMO, first_sessions((_case(),), 0), batch_size=BATCH, max_proposals=PROPOSALS
            ),
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=settings,
            grader_kind="model",
            grader=ExactGrader(),
            model=FakeModelProvider("a dog"),
            observer=FakeObserver(max_batch_size=BATCH),
            preregistration_final=True,
            reconciler=offline_reconciler(),
        )

    assert "grader, model, observer" in str(caught.value)


async def test_the_gate_is_not_bypassed_by_the_mode_s_bare_string(tmp_path: Path) -> None:
    """`RunMode` is a `StrEnum`, so `"scored"` equals `RunMode.SCORED` and is not it —
    an identity test on an unnormalised argument would return early on exactly the
    value it exists to catch, while the manifest coerced the same string happily."""
    with pytest.raises(PermissionError):
        await execute_run(
            plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS),
            output_root=tmp_path / "runs",
            mode="scored",  # type: ignore[arg-type]  # the point of the test: a caller outside mypy's reach
            corpus_digests={},
            settings=_settings(tmp_path),
            model=FakeModelProvider("a dog"),
            observer=FakeObserver(max_batch_size=BATCH),
            reconciler=offline_reconciler(),
        )

    assert not (tmp_path / "runs").exists()


async def test_an_unknown_mode_is_refused_rather_than_written(tmp_path: Path) -> None:
    """Normalising through the enum rejects a mode nobody defined, as a bonus."""
    with pytest.raises(ValueError, match="not a valid RunMode"):
        await execute_run(
            plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS),
            output_root=tmp_path / "runs",
            mode="provisional",  # type: ignore[arg-type]  # as above
            corpus_digests={},
            settings=_settings(tmp_path),
            model=FakeModelProvider("a dog"),
            observer=FakeObserver(max_batch_size=BATCH),
            reconciler=offline_reconciler(),
        )


async def test_a_real_judge_beside_fake_seams_still_checks_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every seam not injected is one this function builds from `Settings`, and the
    model judge is one of them. Skipping the check here would turn a missing credential
    into a completed run of `ungraded` rows."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PYDANTIC_AI_GATEWAY_API_KEY", raising=False)

    with pytest.raises(ConfigurationError):
        await execute_run(
            plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS),
            output_root=tmp_path / "runs",
            mode=RunMode.SMOKE,
            corpus_digests={},
            settings=_settings(tmp_path),
            grader_kind="model",
            model=FakeModelProvider("a dog"),
            observer=FakeObserver(max_batch_size=BATCH),
            reconciler=offline_reconciler(),
        )


async def test_wholly_injected_seams_need_no_credential(tmp_path: Path) -> None:
    """The complement, and what keeps this suite runnable with no key configured."""
    manifest, _ = await _run(tmp_path)

    assert manifest.judge == "exact"


@pytest.mark.parametrize("confirmation", ["false", "no", 1, 0.0, [], "True"])
async def test_a_non_boolean_confirmation_does_not_admit_a_scored_run(
    tmp_path: Path, confirmation: object
) -> None:
    """`not "false"` is False, so a truthiness test reads the string "false" as
    confirmation of the one rule that must never be confirmed by accident. The
    parameters are what a shell wrapper or a config file produces."""
    with pytest.raises(PermissionError):
        await execute_run(
            plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS),
            output_root=tmp_path / "runs",
            mode=RunMode.SCORED,
            corpus_digests={},
            settings=_settings(tmp_path),
            model=FakeModelProvider("a dog"),
            observer=FakeObserver(max_batch_size=BATCH),
            preregistration_final=confirmation,  # type: ignore[arg-type]  # the point of the test
            reconciler=offline_reconciler(),
        )
