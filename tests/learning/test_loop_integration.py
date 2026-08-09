"""The first closed learning loop, end to end.

Composes the *real* learning processor and the *real* memory write-path (no
fakes) to prove the vertical from ADR-0009: an explicit correction becomes a
durable memory the system can reuse.

Since ADR-0122 it also proves the vertical the QA run (#862) found broken. That
defect was invisible to every test that stopped at one subsystem's boundary: the
CLI's table, the processor's mapping and the ingestor's kind-scoped probe were
each correct on their own, and they did not compose. So the correction path is
driven here through a real ``LearningLoop`` over a real ``RuleBasedFeedbackProcessor``,
``MemoryIngestor``, ``DefaultMemoryPolicy`` and ``InMemoryMemoryStore``, and — for
the deferral the QA run actually hit — a real ``QuestionStage``.

The one fake is :class:`~ai_assistant.testing.FakeDeferralStore`: the durable queue
is a collaborator of the path rather than part of it, and ADR-0078's own suite binds
it to the same contract the persistent one meets.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ai_assistant.core.types import (
    AnswerKind,
    FeedbackEvent,
    FeedbackKind,
    MemoryDecisionKind,
    MemoryKind,
    MemorySource,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
)
from ai_assistant.learning import RuleBasedFeedbackProcessor
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor
from ai_assistant.orchestration import LearningLoop, MemoryWriteStage, QuestionStage
from ai_assistant.testing import (
    FakeContextProvider,
    FakeDeferralStore,
    FakePlanner,
    FakeTraceSink,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: The espresso/cappuccino pair from the QA run (#862, #864), trimmed so the
#: overlap clears ``MemoryIngestor``'s 0.75 conflict threshold — the correction
#: shares four of its five terms with the belief it corrects.
_ESPRESSO = "prefers espresso in the morning"
_CAPPUCCINO = "prefers cappuccino in the morning"


def _clock() -> datetime:
    return _WHEN


def _asserted() -> Provenance:
    return Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN)


def _observed() -> Provenance:
    return Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN)


class _Composed:
    """One composition root's worth of the real correction path.

    Every collaborator the loop and the answer path share is the **same instance**,
    which is the composition-root obligation ADR-0028 §4 and ADR-0078 §3 state and
    no type expresses: one store behind the loop, the ingestor and the question
    stage, and one deferral queue behind the write stage and the question stage.
    Wired to two of either, this file's tests pass while the system stays broken.
    """

    def __init__(self) -> None:
        """Wire the path, with one fixed clock and one stable id for what is minted."""
        self.store = InMemoryMemoryStore(now=_clock)
        self.deferrals = FakeDeferralStore(now=_clock)
        # One clock for every stage, so a retirement's close instant and the read
        # that must not return the retired record are judged against the same
        # reading — ``live_at`` is half-open, so a window closed *at* the fixed
        # instant is not live at it.
        self.ingestor = MemoryIngestor(
            traces_sink=FakeTraceSink(),
            store=self.store,
            policy=DefaultMemoryPolicy(),
            now=_clock,
        )
        self.writes = MemoryWriteStage(
            writer=self.ingestor, deferrals=self.deferrals, id_factory=lambda: "question-1"
        )
        self.loop = LearningLoop(
            context=FakeContextProvider(),
            memory=self.store,
            writes=self.writes,
            planner=FakePlanner(now=_clock),
            feedback=RuleBasedFeedbackProcessor(now=_clock, id_factory=lambda: "corrected-1"),
            now=_clock,
        )
        self.questions = QuestionStage(
            writer=self.ingestor,
            deferrals=self.deferrals,
            memory=self.store,
            now=_clock,
        )


def _correction(content: str, *, memory_kind: MemoryKind | None = None) -> FeedbackEvent:
    """What ``assistant learn --kind correction`` now builds — unpinned by default."""
    return FeedbackEvent(
        kind=FeedbackKind.CORRECTION,
        memory_kind=memory_kind,
        content=content,
        created_at=_WHEN,
    )


async def test_feedback_becomes_a_reusable_memory() -> None:
    store = InMemoryMemoryStore()
    ingestor = MemoryIngestor(
        traces_sink=FakeTraceSink(), store=store, policy=DefaultMemoryPolicy()
    )
    processor = RuleBasedFeedbackProcessor(id_factory=lambda: "pref-1")

    # 1. The user gives explicit feedback.
    event = FeedbackEvent(
        kind=FeedbackKind.PREFERENCE,
        memory_kind=MemoryKind.PREFERENCE,
        content="prefers concise replies",
        subject="email tone",
        created_at=_WHEN,
    )

    # 2. Learning proposes; 3. the policy disposes; 4. the store persists.
    [proposal] = await processor.process(event)
    result = await ingestor.ingest(proposal)

    assert result.decision.kind is MemoryDecisionKind.ACCEPT  # user-asserted -> accepted
    assert result.record_id == "pref-1"

    # 5. The preference is now retrievable — the loop can reuse it next time.
    stored = await store.get("pref-1")
    assert isinstance(stored, PreferenceMemory)
    assert stored.preference == "prefers concise replies"
    assert [r.id for r in await store.search("concise")] == ["pref-1"]


# --------------------------------------------------------------------------- #
# ADR-0122: a correction reaches the drawer its target lives in                #
# --------------------------------------------------------------------------- #


async def test_a_correction_supersedes_a_preference_it_never_named() -> None:
    """ADR-0122 §10's seam test, with a real processor and a real ingestor.

    The correction names no record type at all. The only thing in the store is a
    ``PreferenceMemory``, which the pre-ADR path could not reach — the CLI filed
    every correction as ``SEMANTIC``, and ``_detect_conflicts`` then searched only
    that drawer, so "candidates were fetched and *all* of them were excluded on the
    ``kind`` predicate" (#864).

    Three things are asserted, because fixing the *reach* without fixing the *type*
    would satisfy the first alone (§8a): the correction reaches its target and
    supersedes it, the target is gone, and what stands in its place is a
    ``PreferenceMemory`` — a belief the user's preference surfaces read — rather than
    a semantic fact filed beside the drawer it belongs in.
    """
    composed = _Composed()
    await composed.store.add(
        PreferenceMemory(
            id="pref-espresso",
            content=_ESPRESSO,
            preference=_ESPRESSO,
            provenance=_observed(),
        )
    )

    [outcome] = await composed.loop.learn(_correction(_CAPPUCCINO))

    assert outcome.result.decision.kind is MemoryDecisionKind.SUPERSEDE
    assert outcome.result.decision.target_id == "pref-espresso"
    assert await composed.store.get("pref-espresso") is None, "the wrong belief is retired"
    corrected = await composed.store.get(outcome.result.record_id or "")
    assert isinstance(corrected, PreferenceMemory), "the right drawer, not merely the right reach"
    assert corrected.preference == _CAPPUCCINO


async def test_the_qa_runs_correction_now_reaches_its_target_and_supersedes_on_accept() -> None:
    """The QA run's exact failure (#862, #864), driven end to end.

    The stored espresso preference is ``USER_ASSERTED`` here, as it is when a user
    teaches it, so the espresso and cappuccino statements *disagree* and ADR-0050 §2
    holds: two things the user said cannot both stay live, and the user resolves it.
    That is the path the QA run found sound once the correction was re-taught as
    ``--kind preference`` by hand — deferred, then superseded on
    ``assistant answer --accept``. What ADR-0122 changes is that the correction now
    gets there **without being told which drawer**, which is the whole of #864.

    Both halves are asserted: the deferral names the espresso preference as what the
    answer would retire, and accepting it retires exactly that and leaves the
    cappuccino preference live in the same drawer.
    """
    composed = _Composed()
    await composed.store.add(
        PreferenceMemory(
            id="pref-espresso",
            content=_ESPRESSO,
            preference=_ESPRESSO,
            provenance=_asserted(),
        )
    )

    [outcome] = await composed.loop.learn(_correction(_CAPPUCCINO))

    assert outcome.result.decision.kind is MemoryDecisionKind.ASK_USER
    assert outcome.result.conflicts == ("pref-espresso",), "the correction found its target"
    assert outcome.admission is not None
    assert outcome.admission.deferral is not None

    answered = await composed.questions.answer(outcome.admission.deferral.id, accept=True)

    assert answered.kind is AnswerKind.APPLIED
    assert await composed.store.get("pref-espresso") is None
    corrected = await composed.store.get(answered.record_id or "")
    assert isinstance(corrected, PreferenceMemory)
    assert corrected.preference == _CAPPUCCINO


async def test_the_pre_adr_default_is_what_missed_and_the_pin_still_reaches_it() -> None:
    """The defect's mechanism, pinned as the behaviour a pin still buys (§6).

    ``--memory-kind semantic`` is exactly what the removed table supplied for every
    correction, and it still means what the user says it means: the drawer is named,
    no resolution runs, and the proposal is minted as a ``SemanticMemory``. Against a
    preference target that finds no conflict — the espresso belief stands, and the
    correction's own utterance lands as a standing semantic fact that keeps surfacing
    in later reads (#864's second harm).

    Asserted rather than removed, for two reasons. It is the *contrast* that makes
    the test above a proof rather than a coincidence: the same store, the same
    utterance, the same everything but the drawer. And §6 rules the pin
    authoritative, so this outcome is now a user's stated choice rather than an
    adapter's invention — which is the only thing about it that changed.
    """
    composed = _Composed()
    await composed.store.add(
        PreferenceMemory(
            id="pref-espresso",
            content=_ESPRESSO,
            preference=_ESPRESSO,
            provenance=_asserted(),
        )
    )

    [outcome] = await composed.loop.learn(_correction(_CAPPUCCINO, memory_kind=MemoryKind.SEMANTIC))

    assert outcome.result.decision.kind is MemoryDecisionKind.ACCEPT
    assert outcome.result.conflicts == (), "the kind-scoped probe never sees the preference"
    stray = await composed.store.get(outcome.result.record_id or "")
    assert isinstance(stray, SemanticMemory)
    espresso = await composed.store.get("pref-espresso")
    assert espresso is not None, "and the contradicted belief is still standing"


async def test_an_unresolved_event_is_refused_by_the_real_processor() -> None:
    """§7, against the real processor rather than a double.

    ``_to_record``'s final arm answers a deferred ``PROCEDURAL``/``EPISODIC`` target
    with no proposal, which is correct — and an unresolved field falling through it
    would be answered the same way, so ``learn`` would write nothing and report
    nothing wrong. That is the silent drop ADR-0122 removes, reintroduced one layer
    down, and §7's refusal is what converts it into a fault.
    """
    processor = RuleBasedFeedbackProcessor(now=_clock, id_factory=lambda: "never-minted")

    with pytest.raises(ValueError, match="must carry a resolved memory_kind"):
        await processor.process(_correction(_CAPPUCCINO))
