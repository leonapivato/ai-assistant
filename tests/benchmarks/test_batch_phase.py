"""``--phase batch``: the same run, answered and judged through the Batches API.

**The load-bearing test is the parity one.** A batched run is only worth having if it
measures the same system a synchronous run measures, and nothing about that is
self-evident: the two phases retrieve at the same moment but answer hours apart, grade
through different code paths, and write their rows at different times.
:class:`TestTheTwoPhasesMeasureTheSameThing` runs one plan both ways over the real
stores and compares every field that is not a fresh identifier.

Everything else here is about the ways a batch can go wrong that a per-call run has no
equivalent for: an item the provider expired, cancelled or refused; a batch that never
settles; a paid job whose handle must survive the process that submitted it. Each of
those is a way a run could quietly record something false — an expired item read as an
empty answer would grade as an abstention and land in #1029's P7 as the system
declining — so each has a test that says what is recorded instead.

The seam is the canonical fake (`ai_assistant.testing.batch`), which returns its
outcomes in a deliberately jumbled order (ADR-0143 §4 leaves the order unspecified and
asks the fake to prove a consumer does not assume it). Nothing here reaches a network
or a credential.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from benchmarks.memory.batch import JUDGE_ITEM_SUFFIX, PollPolicy, item_id_for
from benchmarks.memory.cases import BenchCase, BenchQuestion, BenchSession, BenchTurn
from benchmarks.memory.corpora.provenance import LOCOMO
from benchmarks.memory.grade import ExactGrader, ModelGrader, Verdict
from benchmarks.memory.records import QuestionRecord, RunMode, RunPhase, read_jsonl
from benchmarks.memory.run import BATCHES_FILE, execute_run, plan_run
from benchmarks.memory.select import first_sessions
from benchmarks.memory.wiring import BATCH_PROVIDER

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import BatchOutcomeKind, BatchRequest, Message, Role
from ai_assistant.models.batch import _PROVIDER_NAME
from ai_assistant.testing import FakeModelProvider, FakeObserver
from ai_assistant.testing.batch import (
    BatchProvider,
    FakeBatchCompleter,
    ProgrammedOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from benchmarks.memory.grade import Grader

    from ai_assistant.core.protocols import BatchCompleter
    from ai_assistant.core.types import BatchHandle, BatchItemOutcome, BatchStatus

pytestmark = pytest.mark.integration

FIRST = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)
BATCH = 2

#: What both phases' answering seam says, so a parity comparison is about the harness
#: rather than about two different replies.
ANSWER = "she adopted a dog"

ISSUER = "acct-batch-tests"


def _case(key: str = "conv-test") -> BenchCase:
    """A two-session case with three questions: answerable, unanswerable, answerable."""
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
            BenchQuestion(
                question_id=f"{key}#2",
                category="2",
                question="What is the dog called?",
                answer="Juno",
                evidence=("D1:3",),
            ),
        ),
    )


def _settings(tmp_path: Path, *, default_model: str = "anthropic:claude-sonnet-4-5") -> Settings:
    """Settings a plumbing check may use, and a scored run may not."""
    return Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        episode_retention=None,
        observation_batch_size=BATCH,
        default_model=default_model,
    )


class _SettlingCompleter:
    """A ``BatchCompleter`` that settles each batch the instant it is accepted.

    Structurally a ``BatchCompleter`` and nothing more: every refusal, every snapshot
    and the jumbled result order are the canonical fake's, because replacing those
    would be testing a double instead of the contract. What this adds is the one thing
    a test cannot wait for — a provider that finishes — so the poll loop sees a real
    ``PENDING`` → ``COMPLETE`` transition without a real hour passing.

    Attributes:
        polls: How many times the run asked. Read to prove the loop polls at all,
            rather than fetching a batch it never confirmed had settled.
    """

    def __init__(self, inner: FakeBatchCompleter, *, settle: bool = True) -> None:
        self._inner = inner
        self._settle = settle
        self.polls = 0
        self.on_poll: list[Any] = []
        #: ``(batch_key, model)`` for each submission, so a test can assert **where**
        #: a batch was sent and not merely that one was.
        self.sent: list[tuple[str, str | None]] = []

    @property
    def issuer(self) -> str:
        return self._inner.issuer

    @property
    def provider(self) -> BatchProvider:
        return self._inner.provider

    async def submit(
        self, batch_key: str, items: Sequence[BatchRequest], *, model: str | None = None
    ) -> BatchHandle:
        self.sent.append((batch_key, model))
        handle = await self._inner.submit(batch_key, items, model=model)
        if self._settle:
            self._inner.provider.settle(handle.batch_id)
        return handle

    async def poll(self, handle: BatchHandle) -> BatchStatus:
        self.polls += 1
        for hook in self.on_poll:
            hook()
        return await self._inner.poll(handle)

    async def fetch(self, handle: BatchHandle) -> Sequence[BatchItemOutcome]:
        return await self._inner.fetch(handle)


def _completer(*, settle: bool = True, max_items: int | None = None) -> _SettlingCompleter:
    """A settling completer over a fresh provider."""
    return _SettlingCompleter(FakeBatchCompleter(issuer=ISSUER, max_items=max_items), settle=settle)


def _program_answers(completer: _SettlingCompleter, case: BenchCase, reply: str) -> None:
    """Make every one of ``case``'s answer items come back with ``reply``."""
    for question in case.questions:
        completer.provider.program(
            item_id_for(case.case_key, question.question_id),
            ProgrammedOutcome(content=reply),
        )


def _program_judgements(completer: _SettlingCompleter, case: BenchCase, reply: str) -> None:
    """Make every one of ``case``'s judge items come back with ``reply``.

    Separately programmable from the answers only because a judge item carries its own
    id — which is the reason it does. The two batches ask different questions about the
    same row, and a test that could not answer them differently would be unable to
    tell a judged run from an unjudged one.
    """
    for question in case.questions:
        completer.provider.program(
            f"{item_id_for(case.case_key, question.question_id)}{JUDGE_ITEM_SUFFIX}",
            ProgrammedOutcome(content=reply),
        )


async def _run(  # noqa: PLR0913 — each argument is one axis a test varies, and a bundle would hide which ones a case left alone
    tmp_path: Path,
    *,
    phase: RunPhase,
    case: BenchCase | None = None,
    completer: BatchCompleter | None = None,
    grader: Grader | None = None,
    settings: Settings | None = None,
    max_model_calls: int | None = None,
    poll: PollPolicy | None = None,
    mode: RunMode = RunMode.SMOKE,
    preregistration_final: bool = False,
    grader_kind: str = "exact",
) -> tuple[Any, Path]:
    """Execute one run over a fixture case, with every model seam faked."""
    subject = case if case is not None else _case()
    resolved = settings if settings is not None else _settings(tmp_path)
    plan = plan_run(LOCOMO, first_sessions((subject,), 0), batch_size=BATCH)
    root = tmp_path / "runs"
    manifest = await execute_run(
        plan,
        output_root=root,
        mode=mode,
        corpus_digests={"locomo10.json": "0" * 64},
        settings=resolved,
        grader=grader if grader is not None else ExactGrader(),
        grader_kind=grader_kind,
        model=FakeModelProvider(ANSWER),
        observer=FakeObserver(max_batch_size=BATCH),
        phase=phase,
        batch_completer=completer,
        issuer=ISSUER,
        preregistration_final=preregistration_final,
        poll=poll if poll is not None else PollPolicy(interval=0.0, timeout=30.0),
        max_model_calls=max_model_calls,
    )
    return manifest, root / manifest.run_id


def _comparable(record: QuestionRecord) -> dict[str, object]:
    """One record's phase-independent content.

    Identifiers minted per run — the run id, the correlation id, the generated record
    ids retrieval returned, the conversation id capture minted, and the batch item id
    that exists in only one phase — are excluded because they *cannot* agree across two
    runs; everything a reader of ``records.jsonl`` would draw a conclusion from is
    kept, including the shape of what was retrieved and the P4 call count.
    """
    return {
        "question_id": record.question_id,
        "category": record.category,
        "unanswerable": record.unanswerable,
        "answer": record.answer,
        "verdict": record.verdict,
        "abstained": record.abstained,
        "judge": record.judge,
        "judge_detail": record.judge_detail,
        "evidence": record.evidence,
        "asked_at": record.asked_at,
        "context_chars": record.context_chars,
        "retrieved_kinds": record.retrieved_kinds,
        "retrieved_count": len(record.retrieved_ids),
        "search_calls": record.telemetry.search_calls,
        "ingestion": {
            key: value for key, value in record.ingestion.items() if key != "conversation_id"
        },
    }


class TestTheTwoPhasesMeasureTheSameThing:
    """The parity claim, over the real stores and the real retrieval path."""

    async def test_a_batched_run_records_what_a_synchronous_one_records(
        self, tmp_path: Path
    ) -> None:
        case = _case()
        completer = _completer()
        _program_answers(completer, case, ANSWER)

        _, sync_dir = await _run(tmp_path / "sync", phase=RunPhase.SYNC, case=case)
        _, batch_dir = await _run(
            tmp_path / "batch", phase=RunPhase.BATCH, case=case, completer=completer
        )

        synchronous = read_jsonl(sync_dir / "records.jsonl", QuestionRecord)
        batched = read_jsonl(batch_dir / "records.jsonl", QuestionRecord)

        assert [_comparable(one) for one in batched] == [_comparable(one) for one in synchronous]

    async def test_only_the_batched_rows_name_a_batch_item(self, tmp_path: Path) -> None:
        case = _case()
        completer = _completer()
        _program_answers(completer, case, ANSWER)

        _, sync_dir = await _run(tmp_path / "sync", phase=RunPhase.SYNC, case=case)
        _, batch_dir = await _run(
            tmp_path / "batch", phase=RunPhase.BATCH, case=case, completer=completer
        )

        assert all(
            one.batch_item_id is None
            for one in read_jsonl(sync_dir / "records.jsonl", QuestionRecord)
        )
        batched = read_jsonl(batch_dir / "records.jsonl", QuestionRecord)
        assert [one.batch_item_id for one in batched] == [
            item_id_for(case.case_key, question.question_id) for question in case.questions
        ]

    async def test_each_answer_reaches_the_question_it_was_asked_for(self, tmp_path: Path) -> None:
        # The fake returns its outcomes jumbled on purpose (ADR-0143 §4). Giving each
        # item a distinct reply is what turns "matched by id" from a claim into an
        # observation: a positional assumption would shuffle these.
        case = _case()
        completer = _completer()
        for index, question in enumerate(case.questions):
            completer.provider.program(
                item_id_for(case.case_key, question.question_id),
                ProgrammedOutcome(content=f"reply-{index}"),
            )

        _, run_dir = await _run(tmp_path, phase=RunPhase.BATCH, case=case, completer=completer)

        answers = {
            one.question_id: one.answer
            for one in read_jsonl(run_dir / "records.jsonl", QuestionRecord)
        }
        # The unanswerable question's reply is still its own; abstention is judged from
        # the text, and the text has to be the one that item came back with.
        assert answers == {
            question.question_id: f"reply-{index}" for index, question in enumerate(case.questions)
        }


class TestAnItemThatProducedNoAnswer:
    """The three non-success outcomes, each recorded rather than read as an answer."""

    @pytest.mark.parametrize(
        ("kind", "expected"),
        [
            (BatchOutcomeKind.EXPIRED, "expired"),
            (BatchOutcomeKind.CANCELLED, "cancelled"),
            (BatchOutcomeKind.FAILED, "failed"),
        ],
    )
    async def test_it_is_ungraded_and_says_why(
        self, tmp_path: Path, kind: BatchOutcomeKind, expected: str
    ) -> None:
        case = _case()
        completer = _completer()
        _program_answers(completer, case, ANSWER)
        doomed = case.questions[0]
        completer.provider.program(
            item_id_for(case.case_key, doomed.question_id), ProgrammedOutcome(kind=kind)
        )

        _, run_dir = await _run(tmp_path, phase=RunPhase.BATCH, case=case, completer=completer)

        rows = {
            one.question_id: one for one in read_jsonl(run_dir / "records.jsonl", QuestionRecord)
        }
        row = rows[doomed.question_id]
        assert row.verdict == str(Verdict.UNGRADED)
        assert row.judge_detail is not None
        assert expected in row.judge_detail
        # **Not an abstention.** An empty answer scored as a decline is the failure
        # this whole path exists to avoid: it would enter #1029's P7 as the system
        # choosing not to answer, when the system was never asked.
        assert row.abstained is False

    async def test_the_providers_own_words_never_reach_a_record(self, tmp_path: Path) -> None:
        case = _case()
        completer = _completer()
        _program_answers(completer, case, ANSWER)
        doomed = case.questions[0]
        completer.provider.program(
            item_id_for(case.case_key, doomed.question_id),
            ProgrammedOutcome(kind=BatchOutcomeKind.FAILED, detail="SECRET-VENDOR-PROSE"),
        )

        _, run_dir = await _run(tmp_path, phase=RunPhase.BATCH, case=case, completer=completer)

        text = (run_dir / "records.jsonl").read_text(encoding="utf-8")
        assert "SECRET-VENDOR-PROSE" not in text

    async def test_the_other_items_are_unaffected(self, tmp_path: Path) -> None:
        # ADR-0143 §5's whole point: one item's refusal must not destroy the rest.
        case = _case()
        completer = _completer()
        _program_answers(completer, case, ANSWER)
        completer.provider.program(
            item_id_for(case.case_key, case.questions[0].question_id),
            ProgrammedOutcome(kind=BatchOutcomeKind.EXPIRED),
        )

        _, run_dir = await _run(tmp_path, phase=RunPhase.BATCH, case=case, completer=completer)

        rows = read_jsonl(run_dir / "records.jsonl", QuestionRecord)
        assert len(rows) == len(case.questions)
        assert rows[2].answer == ANSWER


class TestTheJudgeBatchCarriesOnlyWhatAJudgeMustRead:
    """An abstention costs no call, so it must cost no item either."""

    async def test_an_unanswerable_question_is_not_submitted_for_grading(
        self, tmp_path: Path
    ) -> None:
        case = _case()
        completer = _completer()
        # Two real answers and one abstention. The abstention is settled by the same
        # rule the synchronous judge applies first, before any batch is built.
        for question in case.questions:
            completer.provider.program(
                item_id_for(case.case_key, question.question_id), ProgrammedOutcome(content=ANSWER)
            )
        abstaining = case.questions[1]
        completer.provider.program(
            item_id_for(case.case_key, abstaining.question_id),
            ProgrammedOutcome(content="I don't know"),
        )
        _program_judgements(completer, case, "CORRECT")

        manifest, _ = await _run(
            tmp_path,
            phase=RunPhase.BATCH,
            case=case,
            completer=completer,
            grader=ModelGrader(FakeModelProvider("CORRECT"), route="fake:judge"),
        )

        answer_batch, judge_batch = manifest.batches
        assert answer_batch.item_count == len(case.questions)
        # Three questions asked, one of them declined: two gradings to buy.
        assert judge_batch.item_count == len(case.questions) - 1

    async def test_a_judged_answer_carries_the_judges_verdict(self, tmp_path: Path) -> None:
        case = _case()
        completer = _completer()
        _program_answers(completer, case, ANSWER)
        _program_judgements(completer, case, "CORRECT")

        _, run_dir = await _run(
            tmp_path,
            phase=RunPhase.BATCH,
            case=case,
            completer=completer,
            grader=ModelGrader(FakeModelProvider("CORRECT"), route="fake:judge"),
        )

        rows = {
            one.question_id: one for one in read_jsonl(run_dir / "records.jsonl", QuestionRecord)
        }
        answerable = [one for one in rows.values() if not one.unanswerable]
        assert answerable
        assert all(one.verdict == str(Verdict.CORRECT) for one in answerable)
        assert all(one.judge == "model:fake:judge" for one in answerable)
        # The declined one never reached the judge batch and is graded correct for
        # abstaining, which is what `grading_without_a_call` settles.
        declined = rows[case.questions[1].question_id]
        assert declined.judge_detail == "abstention expected"

    async def test_the_judge_batch_is_sent_to_the_judge_route_it_records(
        self, tmp_path: Path
    ) -> None:
        # A judge is an instrument and need not be the model under test, so
        # `--judge-model` names a second route. A judge batch submitted to the
        # *answering* route while the row records the judge's would be a manifest
        # naming a judge that never saw the prompt — the exact false provenance
        # `--judge-model` was added to prevent.
        case = _case()
        completer = _completer()
        _program_answers(completer, case, ANSWER)
        _program_judgements(completer, case, "CORRECT")

        _, run_dir = await _run(
            tmp_path,
            phase=RunPhase.BATCH,
            case=case,
            completer=completer,
            grader=ModelGrader(FakeModelProvider("CORRECT"), route="anthropic:a-judge"),
        )

        answer_send, judge_send = completer.sent
        # The answering batch takes the completer's configured route; the judge batch
        # overrides it, per ADR-0143 §2's per-batch override.
        assert answer_send[1] is None
        assert judge_send[1] == "anthropic:a-judge"
        rows = read_jsonl(run_dir / "records.jsonl", QuestionRecord)
        assert all(one.judge == "model:anthropic:a-judge" for one in rows)

    async def test_a_judge_item_that_did_not_come_back_is_ungraded(self, tmp_path: Path) -> None:
        case = _case()
        completer = _completer()
        _program_answers(completer, case, ANSWER)
        _program_judgements(completer, case, "probably correct, I'd say")

        _, run_dir = await _run(
            tmp_path,
            phase=RunPhase.BATCH,
            case=case,
            completer=completer,
            grader=ModelGrader(FakeModelProvider("CORRECT"), route="fake:judge"),
        )

        rows = read_jsonl(run_dir / "records.jsonl", QuestionRecord)
        graded = [one for one in rows if not one.unanswerable]
        assert all(one.verdict == str(Verdict.UNGRADED) for one in graded)
        assert all("unparseable" in (one.judge_detail or "") for one in graded)


class TestAPaidJobIsNeverLost:
    """ADR-0060's rule, applied to a batch that is billing from the moment it exists."""

    async def test_the_handle_is_on_disk_before_the_first_poll(self, tmp_path: Path) -> None:
        case = _case()
        completer = _completer()
        _program_answers(completer, case, ANSWER)
        seen: list[bool] = []

        _, run_dir = await _run(
            tmp_path,
            phase=RunPhase.BATCH,
            case=case,
            completer=_arm(completer, seen, tmp_path),
        )

        # Every poll — the first one included — happened with the handle already
        # written. A process killed during the wait leaves a file naming what it is
        # being charged for.
        assert seen
        assert all(seen)
        assert (run_dir / BATCHES_FILE).exists()

    async def test_a_batch_that_never_settles_stops_the_run_and_keeps_the_handle(
        self, tmp_path: Path
    ) -> None:
        case = _case()
        completer = _completer(settle=False)
        _program_answers(completer, case, ANSWER)

        manifest, run_dir = await _run(
            tmp_path,
            phase=RunPhase.BATCH,
            case=case,
            completer=completer,
            poll=PollPolicy(interval=0.0, timeout=0.0),
        )

        assert manifest.aborted is not None
        assert "stopped waiting" in manifest.aborted
        # The run stopped; the batch did not. Both records of it survive.
        assert len(manifest.batches) == 1
        assert (run_dir / BATCHES_FILE).read_text(encoding="utf-8").strip()

    async def test_the_ceiling_stops_the_run_before_a_batch_is_submitted(
        self, tmp_path: Path
    ) -> None:
        case = _case()
        completer = _completer()
        _program_answers(completer, case, ANSWER)

        manifest, _ = await _run(
            tmp_path,
            phase=RunPhase.BATCH,
            case=case,
            completer=completer,
            max_model_calls=1,
        )

        assert manifest.aborted is not None
        assert "ceiling" in manifest.aborted
        # Nothing was submitted, so nothing is billable — which is the whole reason
        # the guard charges the submission as one unit rather than item by item.
        assert completer.provider.batches == {}
        assert manifest.batches == ()


class TestWhatTheManifestSays:
    """A record set is only comparable to another with the phase in hand."""

    async def test_it_records_the_phase_and_every_batch(self, tmp_path: Path) -> None:
        case = _case()
        completer = _completer()
        _program_answers(completer, case, ANSWER)

        manifest, run_dir = await _run(
            tmp_path, phase=RunPhase.BATCH, case=case, completer=completer
        )

        assert manifest.phase is RunPhase.BATCH
        # One batch: an exact grader makes no call, so there is nothing to grade in a
        # second one.
        assert [one.kind for one in manifest.batches] == ["answer"]
        assert manifest.batches[0].issuer == ISSUER
        assert manifest.batches[0].item_count == len(case.questions)
        written = (run_dir / "manifest.json").read_text(encoding="utf-8")
        assert '"phase": "batch"' in written

    async def test_a_synchronous_run_names_no_batch(self, tmp_path: Path) -> None:
        manifest, _ = await _run(tmp_path, phase=RunPhase.SYNC)

        assert manifest.phase is RunPhase.SYNC
        assert manifest.batches == ()


class TestWhatIsRefusedBeforeAnythingIsSpent:
    """Both refusals land before a store is opened, for the same reason."""

    async def test_a_scored_run_cannot_take_an_injected_completer(self, tmp_path: Path) -> None:
        # The bulk seam joins the other three under clause 5, and for the same reason:
        # the manifest records the routes the settings name, and a seam the caller
        # supplied makes that record false. Every earlier clause is satisfied here so
        # the refusal that fires is the one under test — the on-device embedder is
        # named rather than constructed, because the gate runs before anything is
        # built.
        settings = Settings(
            data_dir=tmp_path / "data",
            embedder=EmbedderKind.ON_DEVICE,
            episode_retention=None,
            observation_batch_size=BATCH,
            default_model="anthropic:claude-sonnet-4-5",
        )

        with pytest.raises(ValueError, match="batch_completer"):
            await _run(
                tmp_path,
                phase=RunPhase.BATCH,
                completer=_completer(),
                grader=ModelGrader(FakeModelProvider("CORRECT"), route="fake:judge"),
                settings=settings,
                mode=RunMode.SCORED,
                preregistration_final=True,
                grader_kind="model",
            )

    async def test_an_unbatchable_route_is_refused_before_a_store_is_opened(
        self, tmp_path: Path
    ) -> None:
        settings = _settings(tmp_path, default_model="openai:gpt-5-mini")

        with pytest.raises(ConfigurationError, match="phase batch"):
            await _run(tmp_path, phase=RunPhase.BATCH, settings=settings)

        # Refused before the run directory exists, which is the point: discovering
        # this at `submit` means discovering it after every case has been ingested.
        assert not (tmp_path / "runs").exists()

    async def test_an_unbatchable_judge_route_is_refused_before_a_store_is_opened(
        self, tmp_path: Path
    ) -> None:
        # The answering route is batchable and the judge's is not. Checking only the
        # first would ingest every case and buy the answer batch before refusing at
        # the judge submission.
        with pytest.raises(ConfigurationError, match="phase batch"):
            await _run(
                tmp_path,
                phase=RunPhase.BATCH,
                grader=ModelGrader(FakeModelProvider("CORRECT"), route="openai:gpt-5-mini"),
            )

        assert not (tmp_path / "runs").exists()

    def test_the_batchable_provider_matches_the_implementation(self) -> None:
        """The copied constant is the one `models/batch.py` actually answers for."""
        assert BATCH_PROVIDER == _PROVIDER_NAME


class TestTheWaitIsABoundedOne:
    """A submitted batch is billing, so the loop that waits on it must end."""

    @pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -1.0])
    def test_a_timeout_that_is_not_a_duration_is_refused(self, timeout: float) -> None:
        # `--batch-timeout nan` parses perfectly well as a float and then makes every
        # `monotonic() >= deadline` false, so the loop would poll a paid batch forever
        # instead of stopping cleanly. Refused where the value is made, not where it
        # would have failed to bite.
        with pytest.raises(ValueError, match="timeout"):
            PollPolicy(timeout=timeout)

    @pytest.mark.parametrize("interval", [float("nan"), float("inf"), -1.0])
    def test_an_interval_that_is_not_a_duration_is_refused(self, interval: float) -> None:
        with pytest.raises(ValueError, match="interval"):
            PollPolicy(interval=interval)

    def test_zero_is_legal_in_both(self) -> None:
        # `interval=0` polls as fast as the provider answers, and `timeout=0` gives up
        # after one poll — both meaningful things to ask for.
        assert PollPolicy(interval=0.0, timeout=0.0).timeout == 0.0


class TestItemIds:
    """The id is the only thing that matches an outcome back to a question."""

    def test_keys_that_sanitise_alike_get_different_ids(self) -> None:
        assert item_id_for("a/b", "q") != item_id_for("a_b", "q")

    def test_questions_within_a_case_get_different_ids(self) -> None:
        assert item_id_for("case", "q1") != item_id_for("case", "q2")

    def test_an_id_is_stable_across_calls(self) -> None:
        assert item_id_for("case", "q1") == item_id_for("case", "q1")

    def test_an_id_survives_a_batch_request_unchanged(self) -> None:
        # `item_id` is `NonBlankEncodableText` and not `Identifier` precisely so it is
        # carried byte-for-byte (ADR-0143 §9); an id this harness minted must not be
        # one the type would normalise.
        minted = item_id_for("case with spaces/and slashes", "q#1")
        request = BatchRequest(item_id=minted, messages=[Message(role=Role.USER, content="x")])

        assert request.item_id == minted


def _arm(completer: _SettlingCompleter, seen: list[bool], tmp_path: Path) -> _SettlingCompleter:
    """Have every poll record whether the batches file existed when it ran."""

    def observe() -> None:
        runs = tmp_path / "runs"
        found = runs.exists() and any(path.is_file() for path in runs.glob(f"*/{BATCHES_FILE}"))
        seen.append(found)

    completer.on_poll.append(observe)
    return completer
