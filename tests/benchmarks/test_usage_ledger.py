"""What a run measured about its own cost, and what it refuses to claim it measured.

Pilot-5 cost roughly twice its estimate and its own artifacts could not say where the
money went (#1292). The ledger closes the part of that gap the harness can reach, and the
tests here are in two halves accordingly.

**The first half is arithmetic**: a crossing is credited to the phase and route it was
made on, once; a scope collects exactly the crossings made inside it; a call that failed
contributes its prompt and no reply, because it was made and it was billed.

**The second half is the refusal**, and it is the more important of the two. No token
count crosses the ``ai_assistant`` model seam (#1305), so a token figure on any of these
artifacts could only have been derived from the character counts beside it — which is the
exact arithmetic that put pilot-5's estimate at half its true cost. So the token slots are
asserted empty, the marker that says *why* is asserted present, and
:class:`TestNothingDerivesTokensFromCharacters` walks every artifact a run writes to check
that nothing anywhere has quietly started dividing.

Everything runs offline. The answering and reconciling seams are fakes behind the real
guard, exactly as the rest of this suite wires them; the observation and judging labels
are checked where they are applied, because a built observer would reach the network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from benchmarks.memory.__main__ import _add_token_rows
from benchmarks.memory.batch import JUDGE_ITEM_SUFFIX, PollPolicy, item_id_for
from benchmarks.memory.cases import BenchCase, BenchQuestion, BenchSession, BenchTurn
from benchmarks.memory.corpora.provenance import LOCOMO, LONGMEMEVAL_ORIGINAL
from benchmarks.memory.grade import ExactGrader, ModelGrader
from benchmarks.memory.records import QuestionRecord, RunMode, RunPhase, read_jsonl
from benchmarks.memory.run import build_grader, execute_run, plan_run
from benchmarks.memory.select import first_sessions
from benchmarks.memory.spend import RunAbortedError, SpendGuard
from benchmarks.memory.usage import (
    MEASURED_TOKENS,
    TOKENS_UNAVAILABLE,
    UsageLedger,
    UsagePhase,
    UsageTally,
    prompt_chars,
)
from benchmarks.memory.wiring import build_harness, build_model_provider
from harness_reconcilers import OFFLINE_ROUTE, offline_reconciler
from rich.console import Console
from rich.table import Table

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ModelError, ModelUnavailableError
from ai_assistant.core.types import BatchOutcomeKind, Message, Role
from ai_assistant.learning import ModelBackedObserver
from ai_assistant.models.retry import RetryingProvider, RetryPolicy
from ai_assistant.testing import FakeModelProvider, FakeObserver
from ai_assistant.testing.batch import FakeBatchCompleter, ProgrammedOutcome

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from benchmarks.memory.grade import Grader
    from benchmarks.memory.records import RunManifest
    from benchmarks.memory.usage import UsageEntry, UsageTotals

    from ai_assistant.core.types import BatchHandle, BatchItemOutcome, BatchRequest, BatchStatus

FIRST = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)
BATCH = 2
PROPOSALS = 3
ANSWER = "she adopted a dog"
ISSUER = "acct-usage-tests"

#: The answering route these runs are configured on, and so the route every answering
#: ledger row must name.
ANSWER_ROUTE = "anthropic:claude-x"

#: A judge route deliberately different from the answering one, so a ledger row naming it
#: proves the judge's spend was attributed to the judge rather than folded into the model
#: under test — the same separation ``--judge-model`` exists for in the manifest.
JUDGE_ROUTE = "anthropic:claude-cheap"


def _entry(totals: UsageTotals, phase: UsagePhase) -> UsageEntry | None:
    """The one row for ``phase``, or ``None`` where the phase made no call.

    Args:
        totals: The readings.
        phase: The phase wanted.

    Returns:
        The entry, or ``None``.

    Raises:
        AssertionError: If the phase has more than one row. Every seam in these tests is
            built on one route, so two would mean a route moved mid-run — which is the
            thing ``IngestionSummary.observation_routes`` exists to catch and is never a
            condition a test here should pass over.
    """
    matched = [entry for entry in totals.entries if entry.phase == str(phase)]
    assert len(matched) <= 1, f"{phase} spans more than one route: {matched}"
    return matched[0] if matched else None


def _case(key: str = "conv-usage") -> BenchCase:
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


def _settings(tmp_path: Path) -> Settings:
    """Settings a plumbing check may use, and a scored run may not."""
    return Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        episode_retention=None,
        observation_batch_size=BATCH,
        default_model=ANSWER_ROUTE,
    )


class _SettlingCompleter:
    """A ``BatchCompleter`` that settles each batch the instant it is accepted.

    The canonical fake does everything that matters — the refusals, the snapshot, the
    deliberately jumbled result order — and this adds only the thing a test cannot wait
    for: a provider that finishes.
    """

    def __init__(self, inner: FakeBatchCompleter) -> None:
        self._inner = inner

    @property
    def issuer(self) -> str:
        return self._inner.issuer

    @property
    def provider(self) -> Any:
        return self._inner.provider

    async def submit(
        self, batch_key: str, items: Sequence[BatchRequest], *, model: str | None = None
    ) -> BatchHandle:
        handle = await self._inner.submit(batch_key, items, model=model)
        self._inner.provider.settle(handle.batch_id)
        return handle

    async def poll(self, handle: BatchHandle) -> BatchStatus:
        return await self._inner.poll(handle)

    async def fetch(self, handle: BatchHandle) -> Sequence[BatchItemOutcome]:
        return await self._inner.fetch(handle)


async def _run(
    tmp_path: Path,
    *,
    phase: RunPhase = RunPhase.SYNC,
    case: BenchCase | None = None,
    completer: _SettlingCompleter | None = None,
    judge: Grader | None = None,
) -> tuple[RunManifest, Path]:
    """Execute one run over a fixture case, with every model seam faked.

    The answering seam and the reconciler are injected and are therefore **guarded**,
    which is what puts them in the ledger; the observer is injected and is therefore not,
    which is the documented exemption and is asserted about rather than worked around.

    Args:
        tmp_path: The test's directory.
        phase: Which run phase.
        case: The case, or ``None`` for :func:`_case`.
        completer: The batch seam, required under ``BATCH``.
        judge: The grader, or ``None`` for the exact one — which makes no model call and
            so submits no judge batch.

    Returns:
        The manifest and its run directory.
    """
    subject = case if case is not None else _case()
    root = tmp_path / "runs"
    manifest = await execute_run(
        plan_run(LOCOMO, first_sessions((subject,), 0), batch_size=BATCH, max_proposals=PROPOSALS),
        output_root=root,
        mode=RunMode.SMOKE,
        corpus_digests={"locomo10.json": "0" * 64},
        settings=_settings(tmp_path),
        grader=judge if judge is not None else ExactGrader(),
        model=FakeModelProvider(ANSWER),
        observer=FakeObserver(max_batch_size=BATCH),
        reconciler=offline_reconciler(),
        phase=phase,
        batch_completer=completer,
        issuer=ISSUER,
        poll=PollPolicy(interval=0.0, timeout=30.0),
    )
    return manifest, root / manifest.run_id


class TestTheTallyAddsUpTheCrossingsItWasGiven:
    """The arithmetic, before anything is wired to it."""

    def test_crossings_on_one_seam_accumulate_into_one_row(self) -> None:
        """Two calls on one route are one entry carrying both, not two entries."""
        tally = UsageTally()
        tally.record(phase=UsagePhase.ANSWERING, route="a:b", calls=1, prompt=10, reply=3)
        tally.record(phase=UsagePhase.ANSWERING, route="a:b", calls=1, prompt=20, reply=7)

        totals = tally.snapshot()

        assert len(totals.entries) == 1
        assert totals.entries[0].calls == 2
        assert totals.entries[0].prompt_chars == 30
        assert totals.entries[0].reply_chars == 10
        assert (totals.calls, totals.prompt_chars, totals.reply_chars) == (2, 30, 10)

    def test_one_phase_on_two_routes_is_two_rows(self) -> None:
        """#1292 asks for totals "by model, by phase", so the pair is the key.

        A judge on its own route is the case this is really about: the run's own
        ``--judge-model`` makes it routine, and a ledger keyed by phase alone could not
        say what a re-run on a cheaper judge would save.
        """
        tally = UsageTally()
        tally.record(phase=UsagePhase.JUDGING, route="a:cheap", calls=1, prompt=5)
        tally.record(phase=UsagePhase.JUDGING, route="a:dear", calls=1, prompt=9)

        totals = tally.snapshot()

        assert [(entry.phase, entry.route) for entry in totals.entries] == [
            ("judging", "a:cheap"),
            ("judging", "a:dear"),
        ]

    def test_a_phase_that_made_no_call_has_no_row_at_all(self) -> None:
        """Absent, never a zero row.

        "This scope never touched the reconciler" and "the reconciler was crossed and
        cost nothing" are different facts about a run, and a zero row would render them
        identically — which is the ambiguity #1292 is about everywhere else.
        """
        tally = UsageTally()
        tally.record(phase=UsagePhase.ANSWERING, route="a:b", calls=1)

        totals = tally.snapshot()

        assert _entry(totals, UsagePhase.RECONCILIATION) is None

    def test_the_rows_come_back_in_a_stable_order(self) -> None:
        """So two runs' manifests diff cleanly and a test may assert on a sequence."""
        tally = UsageTally()
        for phase in (UsagePhase.RECONCILIATION, UsagePhase.ANSWERING, UsagePhase.JUDGING):
            tally.record(phase=phase, route="a:b", calls=1)

        assert [entry.phase for entry in tally.snapshot().entries] == [
            "answering",
            "judging",
            "reconciliation",
        ]


class TestAScopeCollectsExactlyWhatWasMadeInsideIt:
    """What makes a per-case and a per-question figure possible at all."""

    def test_a_scope_and_the_run_are_both_credited(self) -> None:
        """The run's total is never a sum a reader has to compute from the scopes."""
        ledger = UsageLedger()
        scope = UsageTally()
        with ledger.attributing_to(scope):
            ledger.record(phase=UsagePhase.ANSWERING, route="a:b", calls=1, prompt=4, reply=2)

        assert scope.snapshot().calls == 1
        assert ledger.run.snapshot().calls == 1

    def test_a_crossing_outside_the_scope_stays_outside_it(self) -> None:
        """The property the ingestion share depends on entirely.

        The case scope is opened around the ingest and closed before the question loop,
        so a summary reporting "what ingestion cost" is exactly that. If a scope leaked
        past its block, every case's ingestion figure would silently include that case's
        answering — which is the one number #1292 exists to isolate.
        """
        ledger = UsageLedger()
        scope = UsageTally()
        with ledger.attributing_to(scope):
            ledger.record(phase=UsagePhase.OBSERVATION, route="a:b", calls=1, prompt=100)
        ledger.record(phase=UsagePhase.ANSWERING, route="a:b", calls=1, prompt=7)

        assert _entry(scope.snapshot(), UsagePhase.ANSWERING) is None
        assert scope.snapshot().prompt_chars == 100
        assert ledger.run.snapshot().prompt_chars == 107

    def test_a_scope_closes_even_when_the_run_aborts_through_it(self) -> None:
        """A ``RunAbortedError`` travels past every per-question handler by design.

        So the one exception a paid run is most likely to end on is the one that would
        strand a scope open — and a stranded scope goes on collecting the *next* case's
        calls into the last case's summary.
        """
        ledger = UsageLedger()
        scope = UsageTally()
        with pytest.raises(RunAbortedError), ledger.attributing_to(scope):
            raise RunAbortedError("the ceiling was reached")

        assert ledger.open_scopes == []
        ledger.record(phase=UsagePhase.ANSWERING, route="a:b", calls=1)
        assert scope.snapshot().calls == 0

    def test_nested_scopes_are_both_credited(self) -> None:
        """Containment, stated because the other reading loses figures silently.

        Nothing nests today. The day something does, an inner crossing belongs in the
        outer total too — an innermost-wins rule would quietly subtract it from a
        containing scope that a reader believes is a total.
        """
        ledger = UsageLedger()
        outer, inner = UsageTally(), UsageTally()
        with ledger.attributing_to(outer), ledger.attributing_to(inner):
            ledger.record(phase=UsagePhase.ANSWERING, route="a:b", calls=1, prompt=6)

        assert outer.snapshot().prompt_chars == 6
        assert inner.snapshot().prompt_chars == 6


class TestTheGuardedSeamRecordsWhatItActuallySent:
    """The wrapper, which is the only thing on the path of every call a run builds."""

    async def test_a_call_records_its_prompt_and_its_reply(self) -> None:
        """Both halves, measured rather than declared."""
        guard = SpendGuard()
        provider = guard.wrap(
            FakeModelProvider(ANSWER), phase=UsagePhase.ANSWERING, route=ANSWER_ROUTE
        )
        turn = [Message(role=Role.USER, content="hello"), Message(role=Role.USER, content="again")]

        await provider.complete(turn)

        entry = _entry(guard.usage.run.snapshot(), UsagePhase.ANSWERING)
        assert entry is not None
        assert entry.route == ANSWER_ROUTE
        assert entry.calls == 1
        assert entry.prompt_chars == prompt_chars(turn) == len("hello") + len("again")
        assert entry.reply_chars == len(ANSWER)

    async def test_a_failed_call_records_its_prompt_and_no_reply(self) -> None:
        """It was made and it is billed, which is why the guard charges it too.

        A ledger that recorded only what came back would understate exactly the run an
        operator is reading a bill to explain — the one whose calls were failing.
        """
        guard = SpendGuard()
        provider = guard.wrap(
            _AlwaysFails(ModelUnavailableError("model completion failed: 503")),
            phase=UsagePhase.ANSWERING,
            route=ANSWER_ROUTE,
        )

        with pytest.raises(ModelUnavailableError):
            await provider.complete([Message(role=Role.USER, content="hello")])

        entry = _entry(guard.usage.run.snapshot(), UsagePhase.ANSWERING)
        assert entry is not None
        assert (entry.calls, entry.prompt_chars, entry.reply_chars) == (1, len("hello"), 0)

    async def test_a_retried_call_is_recorded_once(self) -> None:
        """The same placement decision the charge already turns on.

        The wrapper sits outside ``RetryingProvider``, so the ledger's ``calls`` column
        is in ``plan_run``'s currency. A recorder inside the retry would make a flaky
        hour indistinguishable from an expensive one.
        """
        inner = _AlwaysFails(ModelUnavailableError("model completion failed: 503"))
        guard = SpendGuard()
        provider = guard.wrap(
            RetryingProvider(
                inner,
                policy=RetryPolicy(
                    timeout_seconds=5.0,
                    max_attempts=3,
                    backoff_base_seconds=0.001,
                    backoff_max_seconds=0.001,
                ),
            ),
            phase=UsagePhase.ANSWERING,
            route=ANSWER_ROUTE,
        )

        with pytest.raises(ModelUnavailableError):
            await provider.complete([Message(role=Role.USER, content="hello")])

        assert inner.calls == 3, "the policy did not retry, so this proves nothing"
        entry = _entry(guard.usage.run.snapshot(), UsagePhase.ANSWERING)
        assert entry is not None
        assert entry.calls == 1

    async def test_a_per_call_route_override_is_the_route_recorded(self) -> None:
        """Where the call went, not where the seam was built to go.

        ``ModelProvider.complete`` takes a per-call override, and a ledger naming the
        constructed route while the request went elsewhere would attribute spend to a
        model that never saw a prompt — the same false provenance ``--judge-model``
        exists to prevent in the manifest.
        """
        guard = SpendGuard()
        provider = guard.wrap(
            FakeModelProvider(ANSWER), phase=UsagePhase.JUDGING, route=ANSWER_ROUTE
        )

        await provider.complete([Message(role=Role.USER, content="hi")], model="anthropic:cheap")

        entry = _entry(guard.usage.run.snapshot(), UsagePhase.JUDGING)
        assert entry is not None
        assert entry.route == "anthropic:cheap"


class TestEverySeamIsLabelledWhereItIsBuilt:
    """A phase is fixed at the wrapping site, because nothing downstream could infer it.

    ``observer_model`` and ``reconciler_model`` both fall back to ``default_model``, so a
    run that took the defaults has three seams on one route: a ledger that read the phase
    off the route would report one bucket and call it a split. These check the label is
    applied where the seam is constructed — the built observer is checked structurally
    rather than driven, because building it for real reaches the network.
    """

    def test_the_answering_seam_is_labelled_answering(self, tmp_path: Path) -> None:
        """And on the run's own answer route."""
        guard = SpendGuard()
        harness = build_harness(
            _settings(tmp_path),
            data_dir=tmp_path / "case",
            model=FakeModelProvider(ANSWER),
            observer=FakeObserver(max_batch_size=BATCH),
            reconciler=offline_reconciler(),
            guard=guard,
        )
        try:
            assert harness.model._phase is UsagePhase.ANSWERING  # type: ignore[attr-defined]
            assert harness.model._route == ANSWER_ROUTE  # type: ignore[attr-defined]
        finally:
            harness.close()

    def test_the_built_observer_is_labelled_observation(self, tmp_path: Path) -> None:
        """Read off the built producer, because nothing exposes it.

        The same reading ``test_a_built_observer_spends_the_run_budget`` takes, and for
        the same reason: an ``Observer`` holds its provider and shows nobody. Not driven,
        because a built observer's provider is a live ``PydanticAIProvider``.
        """
        guard = SpendGuard()
        harness = build_harness(
            _settings(tmp_path),
            data_dir=tmp_path / "case",
            reconciler=offline_reconciler(),
            guard=guard,
        )
        try:
            observer = harness.observation._observer
            assert isinstance(observer, ModelBackedObserver)
            assert observer._model._phase is UsagePhase.OBSERVATION  # type: ignore[attr-defined]
            assert observer._model._route == ANSWER_ROUTE  # type: ignore[attr-defined]
        finally:
            harness.close()

    def test_the_reconciler_is_labelled_reconciliation_and_keeps_its_own_route(
        self, tmp_path: Path
    ) -> None:
        """Ingestion, but a separate row from observation.

        ``plan_run`` bounds this phase with a ceiling pilot-5 put five times above the
        truth (``RunPlan.reconciler_calls``), so a measured figure here is the one the
        planner most needs and the one folding it into observation would destroy.
        """
        guard = SpendGuard()
        harness = build_harness(
            _settings(tmp_path),
            data_dir=tmp_path / "case",
            model=FakeModelProvider(ANSWER),
            observer=FakeObserver(max_batch_size=BATCH),
            reconciler=offline_reconciler(),
            guard=guard,
        )
        try:
            seam = harness.reconciliation.model
            assert seam._phase is UsagePhase.RECONCILIATION  # type: ignore[attr-defined]
            assert seam._route == OFFLINE_ROUTE  # type: ignore[attr-defined]
        finally:
            harness.close()

    def test_the_model_judge_is_labelled_judging_on_its_own_route(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A judge is an instrument and frequently a different model, so it is a row.

        Built rather than injected, because an injected grader holds its provider behind
        a surface with no accessor and is outside the ledger exactly as it is outside the
        ceiling.
        """
        monkeypatch.setenv("ANTHROPIC_API_KEY", "present-for-a-route-nothing-calls")
        guard = SpendGuard()

        grader = build_grader(
            _settings(tmp_path), kind="model", route="anthropic:claude-cheap", guard=guard
        )

        assert isinstance(grader, ModelGrader)
        assert grader._model._phase is UsagePhase.JUDGING  # type: ignore[attr-defined]
        assert grader._model._route == "anthropic:claude-cheap"  # type: ignore[attr-defined]

    def test_an_unguarded_build_still_has_to_name_its_phase(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asked for even where it labels nothing, so a caller never learns to omit it.

        ``build_reconciler`` builds unguarded on purpose — one layer wraps, and two would
        charge every crossing twice and silently, by ADR-0159 §3. The argument is still
        required there, because a parameter that is only sometimes load-bearing is one
        that goes missing on the day it matters.
        """
        monkeypatch.setenv("ANTHROPIC_API_KEY", "present-for-a-route-nothing-calls")

        built = build_model_provider(
            _settings(tmp_path), ANSWER_ROUTE, phase=UsagePhase.OBSERVATION
        )

        assert not hasattr(built, "_guard"), "an unguarded build must not be wrapped"


class TestARunRecordsWhatEachScopeCost:
    """End to end, on the real stores, over the paths a pilot actually takes."""

    async def test_the_manifest_carries_the_run_total_by_phase_and_route(
        self, tmp_path: Path
    ) -> None:
        """#1292's "run totals (by model, by phase)", and it agrees with the ceiling.

        The ``calls`` column is the same currency ``SpendGuard.charge`` counts and
        ``plan_run`` reports, which is what lets a finished run be read against the plan
        that authorised it — the first time that has been possible.
        """
        manifest, _ = await _run(tmp_path)

        assert manifest.usage is not None
        answering = _entry(manifest.usage, UsagePhase.ANSWERING)
        assert answering is not None
        assert answering.route == ANSWER_ROUTE
        assert answering.calls == len(_case().questions)
        assert answering.prompt_chars > 0
        assert answering.reply_chars == answering.calls * len(ANSWER)

    async def test_the_ingestion_summary_carries_that_case_s_ingestion_and_nothing_else(
        self, tmp_path: Path
    ) -> None:
        """The share #1292 exists to close, isolated by the scope's boundaries.

        Answering must be **absent** from it: the case scope closes before the question
        loop, and a summary that had swallowed the answers would report an ingestion cost
        that is really a whole case's — which is the number nobody could get at.
        """
        _, run_dir = await _run(tmp_path)

        row = read_jsonl(run_dir / "records.jsonl", QuestionRecord)[0]

        calls = row.ingestion["usage_reconciliation_calls"]
        chars = row.ingestion["usage_reconciliation_prompt_chars"]
        assert isinstance(calls, int)
        assert isinstance(chars, int)
        assert calls >= 1
        assert chars > 0
        assert "usage_answering_calls" not in row.ingestion
        assert row.ingestion["usage_tokens"] == TOKENS_UNAVAILABLE

    async def test_a_sync_row_carries_that_question_s_own_calls(self, tmp_path: Path) -> None:
        """One question, one answering call, and no ingestion in sight.

        The per-question figure #1292 asks for. Ingestion's absence is the assertion that
        matters: the answering scope opens after the case scope has closed, so a row's
        usage is what *this question* cost rather than a share of the case.
        """
        _, run_dir = await _run(tmp_path)

        rows = read_jsonl(run_dir / "records.jsonl", QuestionRecord)

        for row in rows:
            assert row.usage is not None
            answering = _entry(row.usage, UsagePhase.ANSWERING)
            assert answering is not None, row.question_id
            assert answering.calls == 1
            assert answering.reply_chars == len(ANSWER)
            assert _entry(row.usage, UsagePhase.RECONCILIATION) is None
            assert _entry(row.usage, UsagePhase.OBSERVATION) is None

    async def test_a_batched_row_carries_the_item_it_was_submitted_as(self, tmp_path: Path) -> None:
        """The batched phase has no scope, so attribution is the ``item_id`` join.

        Every prepared question is submitted and every submitted item is reported, so
        every row has an answering figure — including the unanswerable one, whose answer
        item is submitted like any other and whose *judge* item is never created.
        """
        case = _case()
        completer = _SettlingCompleter(FakeBatchCompleter(issuer=ISSUER))
        for question in case.questions:
            completer.provider.program(
                item_id_for(case.case_key, question.question_id),
                ProgrammedOutcome(content=ANSWER),
            )

        _, run_dir = await _run(tmp_path, phase=RunPhase.BATCH, case=case, completer=completer)

        rows = read_jsonl(run_dir / "records.jsonl", QuestionRecord)
        assert len(rows) == len(case.questions)
        for row in rows:
            assert row.usage is not None
            answering = _entry(row.usage, UsagePhase.ANSWERING)
            assert answering is not None, row.question_id
            assert answering.calls == 1
            assert answering.route == ANSWER_ROUTE
            assert answering.reply_chars == len(ANSWER)

    async def test_a_batch_item_that_never_answered_still_records_its_prompt(
        self, tmp_path: Path
    ) -> None:
        """Submitted is billed, whatever came back — the same rule a failed call gets.

        An expired, cancelled or failed item is exactly the row an operator reading an
        overrun is looking for: it was paid for and it bought nothing. Walking the
        outcomes rather than the submitted items would drop it and make a partly-failed
        batch look cheaper than it was.
        """
        case = _case()
        completer = _SettlingCompleter(FakeBatchCompleter(issuer=ISSUER))
        first, *rest = case.questions
        completer.provider.program(
            item_id_for(case.case_key, first.question_id),
            ProgrammedOutcome(kind=BatchOutcomeKind.EXPIRED),
        )
        for question in rest:
            completer.provider.program(
                item_id_for(case.case_key, question.question_id),
                ProgrammedOutcome(content=ANSWER),
            )

        _, run_dir = await _run(tmp_path, phase=RunPhase.BATCH, case=case, completer=completer)

        rows = {
            row.question_id: row for row in read_jsonl(run_dir / "records.jsonl", QuestionRecord)
        }
        expired = rows[first.question_id]
        assert expired.usage is not None
        entry = _entry(expired.usage, UsagePhase.ANSWERING)
        assert entry is not None
        assert entry.calls == 1
        assert entry.prompt_chars > 0
        assert entry.reply_chars == 0, "an expired item bought nothing and must say so"

    async def test_a_judge_item_lands_on_the_question_its_answer_did(self, tmp_path: Path) -> None:
        """A judge id is an answer id plus a suffix, and one row wants both halves.

        A question's cost is its answer *and* its judgement, so the join strips the
        suffix and the two land in one tally under one row. Without it a batched run's
        judging spend would be in the manifest and attributable to no question at all.

        **The unanswerable question is the control.** An abstention is graded without a
        call (``grading_without_a_call``), so it has no judge item at all — and its row
        therefore carries an answering figure and no judging one, which is what makes
        the two rows above a join rather than a constant.
        """
        case = _case()
        completer = _SettlingCompleter(FakeBatchCompleter(issuer=ISSUER))
        for question in case.questions:
            item = item_id_for(case.case_key, question.question_id)
            completer.provider.program(item, ProgrammedOutcome(content=ANSWER))
            completer.provider.program(
                f"{item}{JUDGE_ITEM_SUFFIX}", ProgrammedOutcome(content="CORRECT")
            )

        _, run_dir = await _run(
            tmp_path,
            phase=RunPhase.BATCH,
            case=case,
            completer=completer,
            judge=ModelGrader(FakeModelProvider("CORRECT"), route=JUDGE_ROUTE),
        )

        rows = {
            row.question_id: row for row in read_jsonl(run_dir / "records.jsonl", QuestionRecord)
        }
        answered, unanswerable = rows[f"{case.case_key}#0"], rows[f"{case.case_key}#1"]
        assert answered.usage is not None
        judging = _entry(answered.usage, UsagePhase.JUDGING)
        assert judging is not None, "the judge item did not join back to its question"
        assert judging.calls == 1
        assert judging.route == JUDGE_ROUTE
        assert judging.prompt_chars > 0
        assert _entry(answered.usage, UsagePhase.ANSWERING) is not None

        assert unanswerable.usage is not None
        assert _entry(unanswerable.usage, UsagePhase.ANSWERING) is not None
        assert _entry(unanswerable.usage, UsagePhase.JUDGING) is None

    async def test_an_injected_observer_is_outside_the_ledger_as_it_is_outside_the_ceiling(
        self, tmp_path: Path
    ) -> None:
        """The documented exemption, pinned rather than worked around.

        An ``Observer`` is not a ``ModelProvider``, so there is nothing to wrap and
        nothing to record. The gap is bounded by who may inject: clause 5 of
        ``refuse_ineligible_scored_run`` refuses every injected seam on a scored run, so
        a *scored* run's ledger is whole and this is reachable only from a smoke run,
        whose artifacts are already not a measurement.
        """
        manifest, _ = await _run(tmp_path)

        assert manifest.usage is not None
        assert _entry(manifest.usage, UsagePhase.OBSERVATION) is None


class TestNothingDerivesTokensFromCharacters:
    """The refusal, checked on every artifact a run leaves behind.

    No token count crosses the ``ai_assistant`` model seam (#1305), so any token figure
    on these artifacts could only have come from dividing the character counts beside it
    — which is the arithmetic that put pilot-5's estimate at half its cost. The absence
    is therefore asserted, and so is the marker that makes the absence legible to someone
    reading a run directory with none of this in mind.
    """

    async def test_every_artifact_reports_tokens_absent_and_says_why(self, tmp_path: Path) -> None:
        """The manifest, every row, and every entry within them."""
        manifest, run_dir = await _run(tmp_path)
        rows = read_jsonl(run_dir / "records.jsonl", QuestionRecord)
        assert manifest.usage is not None

        carried = [manifest.usage, *(row.usage for row in rows if row.usage is not None)]
        assert len(carried) == 1 + len(rows), "a row lost its usage object"
        for totals in carried:
            assert totals.tokens_measured is False
            assert totals.tokens_unavailable == TOKENS_UNAVAILABLE
            for entry in totals.entries:
                assert entry.input_tokens is None
                assert entry.output_tokens is None

    def test_the_flat_rendering_states_the_absence_as_words(self) -> None:
        """Never as a boolean, because the flat mapping has no column for one.

        A ``bool`` smuggled through the ``int`` half of that union would serialise as
        ``0`` — the one rendering of "not measured" a reader could take for a measurement
        of zero.
        """
        tally = UsageTally()
        tally.record(phase=UsagePhase.OBSERVATION, route="a:b", calls=1, prompt=90, reply=4)

        flat = tally.snapshot().flat()

        assert flat["usage_tokens"] == TOKENS_UNAVAILABLE
        assert flat["usage_observation_prompt_chars"] == 90
        assert flat["usage_calls"] == 1

    def test_the_flat_rendering_sums_routes_and_keeps_phases(self) -> None:
        """The phases are what the ingestion share is a share *of*.

        Routes are dropped because a run's observer and reconciler routes are each fixed
        for the whole run and already in the manifest; the phases are not, because
        folding them together is exactly what makes an ingestion figure unreadable.
        """
        tally = UsageTally()
        tally.record(phase=UsagePhase.OBSERVATION, route="a:one", calls=1, prompt=10)
        tally.record(phase=UsagePhase.OBSERVATION, route="a:two", calls=1, prompt=5)
        tally.record(phase=UsagePhase.RECONCILIATION, route="a:one", calls=2, prompt=8)

        flat = tally.snapshot().flat()

        assert flat["usage_observation_calls"] == 2
        assert flat["usage_observation_prompt_chars"] == 15
        assert flat["usage_reconciliation_calls"] == 2


class TestThePlanReportsMeasuredTokensAndNoOthers:
    """``plan``'s token column: somebody's real measurement, and a floor rather than a total."""

    def test_the_floor_is_answering_plus_judging_and_excludes_ingestion(self) -> None:
        """A total would be the estimate that ran 2x low.

        Observation and reconciliation dominate a run's spend and nothing has ever
        measured them, so the plan reports what is known and names what is not.
        """
        plan = plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS)
        measured = MEASURED_TOKENS["locomo"]

        assert plan.answering_tokens == measured.answer_tokens * plan.answer_calls
        assert plan.judging_tokens == measured.judge_tokens * plan.judge_calls
        assert plan.token_floor == plan.answering_tokens + plan.judging_tokens
        assert plan.observation_calls > 0, "the phase the floor excludes must be non-empty"

    def test_a_corpus_no_pilot_has_run_gets_no_figure_rather_than_a_sibling_s(self) -> None:
        """``longmemeval-original`` is a different file with a different question set.

        Copying the cleaned variant's measurement onto it would be an estimate wearing a
        measurement's name, on a table whose entire point is that it carries neither.
        """
        case = _case()
        plan = plan_run(LONGMEMEVAL_ORIGINAL, (case,), batch_size=BATCH, max_proposals=PROPOSALS)

        assert plan.measured_tokens is None
        assert plan.answering_tokens is None
        assert plan.judging_tokens is None
        assert plan.token_floor is None

    def test_every_measured_figure_names_the_run_it_came_from(self) -> None:
        """These moved 2-4.5x between pilot-4 and pilot-5 on the same corpora.

        A bare number would mislead a reader whose retrieval budget or rendering differs;
        the source is what lets them judge whether it applies to them.
        """
        assert MEASURED_TOKENS
        for key, measured in MEASURED_TOKENS.items():
            assert "pilot-" in measured.source, key
            assert measured.answer_tokens > 0
            assert measured.judge_tokens > 0

    def test_the_plan_table_prints_the_floor_and_the_caveat(self) -> None:
        """The deliverable is a column an operator reads, not a property a test reads."""
        table = Table(show_header=False)
        _add_token_rows(
            table, plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS)
        )
        console = Console(width=200, no_color=True)
        with console.capture() as captured:
            console.print(table)
        printed = captured.get()

        assert "answering tokens" in printed
        assert "never measured" in printed
        assert "at least" in printed
        assert "pilot-5" in printed


class _AlwaysFails:
    """A ``ModelProvider`` that raises, counting the attempts it was given.

    Attributes:
        calls: How many times ``complete`` was entered — the figure that distinguishes a
            policy that retried from one that did not.
    """

    def __init__(self, error: ModelError) -> None:
        self._error = error
        self.calls = 0

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        """Raise, having counted the attempt.

        Args:
            messages: Ignored.
            model: Ignored.

        Returns:
            Never.

        Raises:
            ModelError: Always — the one this was built with.
        """
        self.calls += 1
        raise self._error
