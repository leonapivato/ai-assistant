"""ADR-0158's second read, as the harness performs it.

The harness mirrors ``LearningLoop``'s answering retrieval **by hand** — it must not
run the engine (``benchmarks.memory.wiring``) — so every clause of ADR-0158 §§2-4 that
the loop gets from its own code, this harness gets from a copy. These are the
behavioural half of holding that copy honest; the static half, which fails the day the
loop's kinds, bands or budget move, is in ``test_harness_contracts.py``.

Four properties are asserted because each one is a way the pilot's numbers could be
about a system that is not the shipped one:

* **The episodes are there, and they are last.** A run whose supplement never fired
  would measure the pre-ADR-0158 product while claiming to measure this one, and the
  episodic-rescue attribution (#1177) would read a structural zero as a finding.
* **The belief budget is untouched.** §3's two budgets are the whole of the thesis
  guard: a supplement that displaced a belief would be the shared budget §2 refuses,
  arriving through the harness instead of through the product.
* **The bound binds.** An unbounded episodic read is naive RAG over the transcript,
  which is the one-line version of this design ADR-0158 refuses by name.
* **The separator rule fires.** The loop drops the supplement where nothing before it
  is non-``EPISODIC``; a benchmark question is a fresh conversation's first turn, so
  here that is exactly "the belief read came back empty" — a state the pilot reaches
  often, and the one where the two implementations would most easily diverge.

The band pin is asserted too, over a record capture did not write, because that is the
only clause of the read whose effect is invisible on a store this harness fills by
itself.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest import mock

import pytest
from benchmarks.memory.answer import (
    EMPTY_CONTEXT,
    SUPPLEMENT_BANDS,
    SUPPLEMENT_KINDS,
    answer_question,
)
from benchmarks.memory.cases import BenchCase, BenchQuestion, BenchSession, BenchTurn
from benchmarks.memory.corpora.provenance import LOCOMO
from benchmarks.memory.ingest import ingest_case
from benchmarks.memory.records import RunMode
from benchmarks.memory.run import execute_run, plan_run
from benchmarks.memory.wiring import build_harness
from harness_reconcilers import offline_reconciler

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    Attestation,
    EpisodicMemory,
    MemoryKind,
    MemorySource,
    Provenance,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.orchestration.conversations import BELIEF_KINDS
from ai_assistant.orchestration.retrieval import assemble_by_band
from ai_assistant.testing import FakeModelProvider, FakeObserver

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from benchmarks.memory.answer import AnswerAttempt
    from benchmarks.memory.wiring import Harness

    from ai_assistant.core.types import BeliefBand, MemorySearchResult

pytestmark = pytest.mark.integration

FIRST = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)
BATCH = 2

#: The observation proposal ceiling `plan_run` bounds the reconciler's calls by.
#: Any positive number serves — no test below reads the figure back — but it is
#: passed rather than defaulted for the reason `plan_run` requires it: a planner
#: filling one in reports the cost of a run nobody asked for (#1293).
PROPOSALS = 3
#: Turns enough that capture writes more episodes than the supplement's budget, which
#: is what makes the bound observable rather than vacuously satisfied.
#:
#: **Turns, not episodes, and capture halves them** — one ``EpisodicMemory`` per
#: user/assistant exchange — so this figure buys 34 episodes against ADR-0224 §1's
#: bound of 30.
#:
#: **It is sized against the bound, so it moves whenever the bound rises.** It was 16
#: when the bound was 5, and went to 32 when ADR-0160 §1 took the bound to 15, because
#: 16 turns buy 8 episodes and the assertion below would then have been the fixture
#: failing rather than the read. It stood unchanged through ADR-0162 §9's drop to 10,
#: which needed no room it did not already have, and goes to 68 here because 32 turns
#: buy 16 against ADR-0224 §1's 30 — the same fixture failure, reported by the same
#: assertion, which is why that assertion is worth its runtime.
TURNS = 68


def _case() -> BenchCase:
    """A case holding more eligible episodes than the episodic budget admits.

    The margin is deliberately narrow rather than a comfortable multiple: ``TURNS``
    tracks the bound, and at ADR-0224 §1's 30 every further turn is ingestion time
    the assertion does not need. 34 episodes against 30 proves the bound bites in
    exactly the way 16 against 10 did.

    Returns:
        The case, with one question.
    """
    turns = tuple(
        BenchTurn(
            speaker="Ada" if index % 2 == 0 else "Bo",
            text=f"{'Ada' if index % 2 == 0 else 'Bo'}: line {index} about the dog Juno.",
            user_side=index % 2 == 0,
            evidence_key=f"D1:{index}",
        )
        for index in range(TURNS)
    )
    return BenchCase(
        corpus_key="locomo",
        case_key="supplement",
        sessions=(BenchSession(session_key="session_1", occurred_at=FIRST, turns=turns),),
        questions=(
            BenchQuestion(
                question_id="supplement#0",
                category="1",
                question="What is the dog called?",
                answer="Juno",
                evidence=("D1:0",),
            ),
        ),
    )


def _settings(tmp_path: Path) -> Settings:
    """Settings a plumbing check may use, and a scored run may not.

    Args:
        tmp_path: The test's directory.

    Returns:
        The settings — the hashing embedder, and no horizon to expire the episodes
        this module is entirely about.
    """
    return Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        episode_retention=None,
        observation_batch_size=BATCH,
    )


def _harness(tmp_path: Path, *, observer: FakeObserver) -> Harness:
    """Wire one harness over a scratch directory.

    Args:
        tmp_path: The test's directory.
        observer: The distillation seam — the knob that decides whether this store
            ends up holding beliefs at all.

    Returns:
        The harness. The caller closes it.
    """
    return build_harness(
        _settings(tmp_path),
        data_dir=tmp_path / "case",
        model=FakeModelProvider("Juno"),
        observer=observer,
        reconciler=offline_reconciler(),
    )


def _kinds(attempt: AnswerAttempt) -> tuple[MemoryKind, ...]:
    """The attempt's retrieved kinds, as enum members.

    Args:
        attempt: The answered question.

    Returns:
        One member per record placed in the prompt, in prompt order.
    """
    return tuple(MemoryKind(kind) for kind in attempt.retrieved_kinds)


def _episodic_ids(attempt: AnswerAttempt) -> tuple[str, ...]:
    """The ids of the episodes the supplement contributed.

    Args:
        attempt: The answered question.

    Returns:
        The ids, in prompt order.
    """
    return tuple(
        record_id
        for record_id, kind in zip(attempt.retrieved_ids, _kinds(attempt), strict=True)
        if kind is MemoryKind.EPISODIC
    )


def _rendered_kinds(context: str) -> tuple[str, ...]:
    """The kinds of the rendered block, in the order the model reads them.

    Kinds and not ids, because since #1189 the block is the product's own bullets and
    an id never reaches the prompt at all — which is the change, not a loss for this
    test: the group boundary ADR-0158 §4 carries by position is a boundary *between
    kinds*, so it is exactly what the rendered order has to preserve.

    The heading line is skipped and the tag is read off each bullet's ``[kind/source]``
    prefix.

    Args:
        context: The rendered block.

    Returns:
        One kind per bullet.
    """
    return tuple(
        line.split("[", 1)[1].split("/", 1)[0]
        for line in context.splitlines()
        if line.startswith("  - [")
    )


def _leading_beliefs(kinds: Sequence[MemoryKind]) -> int:
    """How many records precede the first episode.

    Args:
        kinds: The prompt's kinds, in order.

    Returns:
        The length of the leading non-``EPISODIC`` run.
    """
    for index, kind in enumerate(kinds):
        if kind is MemoryKind.EPISODIC:
            return index
    return len(kinds)


async def test_the_supplement_appends_episodes_after_the_beliefs(tmp_path: Path) -> None:
    """ADR-0158 §4's ordering, end to end: beliefs, then episodes, never interleaved.

    The prompt is checked as well as the record, because position is the *only* thing
    carrying the group boundary — the harness's block, like the product's renderer,
    puts both groups under one heading and labels neither — so an ordering held in
    `retrieved_kinds` and lost in the rendered text would be a correct artifact over a
    wrong experiment.
    """
    harness = _harness(tmp_path, observer=FakeObserver(max_batch_size=BATCH))
    try:
        await ingest_case(harness, _case(), batch_size=BATCH)
        attempt = await answer_question(harness, _case().questions[0])
    finally:
        harness.close()

    kinds = _kinds(attempt)
    assert MemoryKind.EPISODIC in kinds, "the supplement contributed nothing at all"
    boundary = _leading_beliefs(kinds)
    assert boundary > 0, "the belief composition contributed nothing, so this proves nothing"
    assert all(kind is MemoryKind.EPISODIC for kind in kinds[boundary:]), (
        "a belief was rendered after an episode, which is the interleaving §4 forbids"
    )
    assert _rendered_kinds(attempt.context) == attempt.retrieved_kinds


async def test_the_supplement_takes_nothing_from_the_belief_budget(tmp_path: Path) -> None:
    """§3's two budgets, asserted as the count a belief-only read returns.

    The comparison is against a *second* read of the same store rather than against a
    constant, so it holds whatever the corpus happens to distil: the beliefs the
    supplemented answer carried must be exactly the beliefs the answer would have
    carried without it.
    """
    question = _case().questions[0]
    harness = _harness(tmp_path, observer=FakeObserver(max_batch_size=BATCH))
    try:
        await ingest_case(harness, _case(), batch_size=BATCH)
        attempt = await answer_question(harness, question)
        beliefs_alone = await assemble_by_band(
            harness.store,
            question.question,
            limit=harness.retrieval_limit,
            kinds=BELIEF_KINDS,
        )
    finally:
        harness.close()

    boundary = _leading_beliefs(_kinds(attempt))
    assert attempt.retrieved_ids[:boundary] == tuple(record.id for record in beliefs_alone)
    assert beliefs_alone, "a store with no beliefs cannot show that the budget survived"


async def test_the_supplement_never_exceeds_its_own_bound(tmp_path: Path) -> None:
    """§3's budget, over a store holding several times as many episodes as it allows.

    Asserted as equality rather than as a ceiling: this store holds far more eligible
    episodes than the bound, so a supplement short of it would mean the read is not
    filling the budget it was given, which is a different defect from overrunning it.
    """
    harness = _harness(tmp_path, observer=FakeObserver(max_batch_size=BATCH))
    try:
        await ingest_case(harness, _case(), batch_size=BATCH)
        episodes = await harness.store.search(
            "line about the dog Juno", limit=TURNS, kinds=(MemoryKind.EPISODIC,)
        )
        attempt = await answer_question(harness, _case().questions[0])
        bound = harness.episodic_limit
    finally:
        harness.close()

    assert len(episodes.records) > bound, "the fixture no longer overfills the bound"
    assert len(_episodic_ids(attempt)) == bound


async def test_an_empty_belief_read_drops_the_supplement(tmp_path: Path) -> None:
    """§4's separator rule, in the state that reaches it here.

    The loop drops the supplement where nothing before it is non-``EPISODIC``, because
    the planner would otherwise render relevance-retrieved episodes under the *recent
    turns* heading and tell the model they were just said. This harness renders no
    such heading, so the fabrication is not reachable here — the rule is kept anyway,
    because a benchmark question is a fresh conversation's first turn and this is the
    condition the shipped loop drops on in exactly that state. Answering from episodes
    here would score a system that does not exist.
    """
    harness = _harness(tmp_path, observer=FakeObserver((), max_batch_size=BATCH))
    try:
        await ingest_case(harness, _case(), batch_size=BATCH)
        episodes = await harness.store.search(
            "line about the dog Juno", limit=TURNS, kinds=(MemoryKind.EPISODIC,)
        )
        attempt = await answer_question(harness, _case().questions[0])
    finally:
        harness.close()

    assert episodes.records, "the store must hold retrievable episodes for this to bite"
    assert attempt.retrieved_ids == ()
    assert attempt.context == EMPTY_CONTEXT


async def test_an_episode_outside_the_derived_band_is_not_supplemented(tmp_path: Path) -> None:
    """§3's band pin, over the one record shape it exists for.

    Capture stamps ``OBSERVED`` unconditionally, so every episode this harness writes
    is ``DERIVED`` and the pin is inert on a store the harness filled alone. The pin is
    not therefore untestable: ``EpisodicMemory`` accepts any ``Provenance``, and an
    ``EXTERNAL`` one bands as ``ATTESTED``, which is the record a band-blind read would
    hand to a bare relevance order with no composition to impose ADR-0072 §5's
    precedence. Written directly to the store because nothing in the harness produces
    one — which is the point of asserting it.
    """
    foreign = EpisodicMemory(
        id="calendar:work:1",
        content="a record capture did not write, about the dog Juno",
        occurred_at=FIRST,
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=0.5,
            last_updated=FIRST,
            attestation=Attestation(reported_by="calendar:work", reported_at=FIRST),
        ),
    )
    harness = _harness(tmp_path, observer=FakeObserver(max_batch_size=BATCH))
    try:
        await ingest_case(harness, _case(), batch_size=BATCH)
        await harness.store.add(foreign)
        band_blind = await harness.store.search(
            foreign.content, limit=TURNS, kinds=(MemoryKind.EPISODIC,)
        )
        attempt = await answer_question(harness, _case().questions[0])
    finally:
        harness.close()

    assert foreign.id in {record.id for record in band_blind.records}, (
        "the record must be retrievable without the band filter for this to mean anything"
    )
    assert foreign.id not in attempt.retrieved_ids


async def test_a_zero_bound_makes_no_episodic_read_at_all(tmp_path: Path) -> None:
    """The disabled state the manifest's ``episodic_limit`` claims to distinguish.

    ADR-0158 §6 may take the bound to zero on the ablation arm's evidence, and the
    loop checks it *before* touching the store precisely so that a disabled supplement
    is a read that never happened rather than an empty one. A manifest reader is told
    those are different states, so the difference is asserted here: no ``search`` is
    crossed with the supplement's kinds, which is also what keeps a disabled run's P4
    count comparable with a pre-ADR-0158 one.
    """
    harness = _harness(tmp_path, observer=FakeObserver(max_batch_size=BATCH))
    asked: list[tuple[MemoryKind, ...]] = []
    real = SqliteMemoryStore.search

    async def _watched(
        self: SqliteMemoryStore,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> MemorySearchResult:
        asked.append(tuple(kinds or ()))
        return await real(self, query, limit=limit, kinds=kinds, bands=bands)

    try:
        await ingest_case(harness, _case(), batch_size=BATCH)
        disabled = dataclasses.replace(harness, episodic_limit=0)
        with mock.patch.object(SqliteMemoryStore, "search", _watched):
            attempt = await answer_question(disabled, _case().questions[0])
    finally:
        harness.close()

    assert MemoryKind.EPISODIC not in _kinds(attempt)
    assert attempt.retrieved_ids, "the belief composition must still have run"
    assert tuple(SUPPLEMENT_KINDS) not in asked


async def test_a_failed_episodic_read_ends_the_run_rather_than_publishing_belief_only(
    tmp_path: Path,
) -> None:
    """The lane's one deliberate departure from ADR-0158 §4, pinned as behaviour.

    The loop swallows a failed episodic read and keeps the beliefs, because a user's
    answer is worth more than the supplement. A benchmark's loss function is the
    opposite: swallowing it would publish a whole run of belief-only prompts as a
    measurement of a configuration that never ran, with nothing in the artifacts
    saying so. So the harness lets it propagate, and this asserts the consequence that
    actually matters — the run stops and **no question record is written** — rather
    than the exception in isolation.

    The failure is injected on the store's own method and narrowed to the supplement's
    exact ``kinds`` *and* ``bands``, so the ingestion path's conflict probe and the
    belief composition both run for real. ``asked`` then records that the belief read
    was crossed before the episodic one, which is what rules out the trivially passing
    version of this test: a run that died during ingestion.
    """
    asked: list[tuple[MemoryKind, ...]] = []
    real = SqliteMemoryStore.search

    async def _failing(
        self: SqliteMemoryStore,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> MemorySearchResult:
        asked.append(tuple(kinds or ()))
        if tuple(kinds or ()) == tuple(SUPPLEMENT_KINDS) and tuple(bands or ()) == tuple(
            SUPPLEMENT_BANDS
        ):
            msg = "the episodic read failed"
            raise MemoryStoreError(msg)
        return await real(self, query, limit=limit, kinds=kinds, bands=bands)

    root = tmp_path / "runs"
    plan = plan_run(LOCOMO, (_case(),), batch_size=BATCH, max_proposals=PROPOSALS)
    with (
        mock.patch.object(SqliteMemoryStore, "search", _failing),
        pytest.raises(MemoryStoreError),
    ):
        await execute_run(
            plan,
            output_root=root,
            mode=RunMode.SMOKE,
            corpus_digests={},
            settings=_settings(tmp_path),
            model=FakeModelProvider("Juno"),
            observer=FakeObserver(max_batch_size=BATCH),
            reconciler=offline_reconciler(),
        )

    assert tuple(BELIEF_KINDS) in asked, "the belief read never happened, so the run died earlier"
    assert asked[-1] == tuple(SUPPLEMENT_KINDS)
    written = [path for path in root.rglob("records.jsonl") if path.read_text(encoding="utf-8")]
    assert not written, "a belief-only question record was published for a broken run"
