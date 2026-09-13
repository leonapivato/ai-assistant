"""ADR-0252 §14's write, end to end, on both conforming stores.

The loop composes a row and ``Engine`` writes it through ``record_evidence`` at ADR-0249
§11's site; the ``supersedes`` set that write carries is §8's predicate, which §12 rules
is ``orchestration``'s and never the store's. **Neither half is observable from the
loop**, so these are engine-level arms: what they read is what a *later* turn's planner
is handed, which is the whole point of the row being durable.

Both arms run over ``FakePlanStore`` and over ``SqlitePlanStore``, because §12's clause
is that "a conformance suite exercising one implementation would be a suite that lets the
other disagree" — read one level up at the consumer that drives them.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from test_engine import AT, PATIENT, Harness, NoStepPlanner
from test_engine_goal_association import _associating, _goal, _seed

from ai_assistant.core.types import (
    AssociationVerdict,
    EpisodicMemory,
    EvidenceApplicability,
    EvidenceBasis,
    EvidenceStanding,
    GoalEvidence,
    MemorySource,
    Placement,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadOutcomeKind,
    ReadRequest,
    SemanticMemory,
    StructuredAsk,
)
from ai_assistant.orchestration.evidence import digest_of
from ai_assistant.planning.sqlite_store import SqlitePlanStore
from ai_assistant.testing import FakeMemoryStore, FakePlanStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from ai_assistant.core.protocols import PlanStore

#: The word the seeded belief, the seeded episode and the utterance share, so the
#: turn's retrieval selects the belief (which is what ADR-0240 §5's separator condition
#: needs) and the structured read reaches the episode.
_TOPIC: Final = "weather"

_CONVERSATION_GOAL: Final = "goal-campsite"

#: A structured read over one topic and no window — so the returned episode's own
#: ``topics`` compose a region that **covers** the seeded row's, which is §8 limb 4.
_STRUCTURED: Final = ReadRequest(
    asks=(ReadAsk(kind=ReadKind.STRUCTURED_READ, structure=StructuredAsk(topics=(_TOPIC,))),)
)


def _belief() -> SemanticMemory:
    """The non-episodic record ADR-0240 §5's separator condition needs in the supply."""
    return SemanticMemory(
        id="belief-1",
        content=f"they always ask about the {_TOPIC}",
        fact=f"they always ask about the {_TOPIC}",
        placement=Placement(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=AT),
    )


def _episode() -> EpisodicMemory:
    """The episode the structured read returns, carrying one applied axis."""
    return EpisodicMemory(
        id="episode-1",
        content=f"we talked about the {_TOPIC}",
        occurred_at=AT,
        topics=(_TOPIC,),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )


def _standing_row(goal_id: str) -> GoalEvidence:
    """A row an earlier turn of this goal left standing, read an hour ago."""
    return GoalEvidence(
        id="row-earlier",
        goal_id=goal_id,
        attempt_id="attempt-earlier",
        basis=EvidenceBasis.READ_OUTCOME,
        read_kind=ReadKind.STRUCTURED_READ,
        supported=(EvidenceApplicability(topics=(_TOPIC,)),),
        supported_elided=0,
        read_at=AT - timedelta(hours=1),
        records=("episode-0",),
        returned=1,
        admitted=1,
        verdict=ReadOutcomeKind.RETURNED_RECORDS.value,
        standing=EvidenceStanding.STANDING,
    )


class _AskingOnce(NoStepPlanner):
    """A planner that asks for one structured read on each turn's first call.

    Subclassed from the plan every other engine case is built on, so "a planner that
    emits a request" and "a planner" differ by one field. The request is dropped once a
    turn has been told what became of its ask (ADR-0251 §3's carrier is non-empty from
    the second call on), which is ADR-0228 §2(b) ending the turn on its second call.
    """

    def __init__(self) -> None:
        self.evidence: list[tuple[Any, ...]] = []

    async def plan(self, goal: Any, **kwargs: Any) -> Any:
        """Answer with the ordinary empty plan, asking once per turn."""
        self.evidence.append(tuple(kwargs["evidence"]))
        produced = await super().plan(
            goal,
            utterance=kwargs["utterance"],
            context=kwargs["context"],
            memories=kwargs["memories"],
            capabilities=kwargs["capabilities"],
        )
        asked = None if kwargs["read_outcomes"] else _STRUCTURED
        return produced.model_copy(
            update={"plan": produced.plan.model_copy(update={"read_request": asked})}
        )


async def _drive(plans: PlanStore) -> tuple[Harness, _AskingOnce, str, str]:
    """Run one turn continuing a goal that already holds a standing row.

    Args:
        plans: The store to wire the engine with.

    Returns:
        The harness, the planner it was wired with, the goal's id and the
        conversation's.
    """
    planner = _AskingOnce()
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(_belief())
    await memory.add(_episode())
    harness = Harness(
        planner=planner,
        memory=memory,
        plans=cast("FakePlanStore", plans),
        associator=_associating(AssociationVerdict.CONTINUES),
    )
    conversation = (await harness.conversations.begin(None)).id
    goal = await _seed(
        plans,
        _goal(_CONVERSATION_GOAL, "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )
    await plans.record_evidence(_standing_row(goal.id))

    outcome = await harness.engine.converse(
        f"what is the {_TOPIC} doing", timeout=PATIENT, conversation_id=conversation
    )

    assert outcome.turn is not None
    return harness, planner, goal.id, conversation


@pytest.fixture(name="sqlite_plans")
async def _sqlite_plans(tmp_path: Path) -> AsyncIterator[SqlitePlanStore]:
    """The other conforming ``PlanStore``, over a real file."""
    store = SqlitePlanStore(path=tmp_path / "plans.db", now=lambda: AT)
    try:
        yield store
    finally:
        store.close()


async def _assert_round_trip(plans: PlanStore, goal_id: str) -> GoalEvidence:
    """The row the turn wrote reads back whole, and the mark rode on the same write.

    Args:
        plans: The store the engine was wired with.
        goal_id: The goal the turn continued.

    Returns:
        The row the turn wrote.
    """
    history = await plans.evidence_of(goal_id)
    assert [row.id for row in history.rows] == ["row-earlier", history.rows[1].id], (
        "ADR-0252 §12's total order: read_at oldest first"
    )
    earlier, written = history.rows

    assert written.basis is EvidenceBasis.READ_OUTCOME
    assert written.read_kind is ReadKind.STRUCTURED_READ
    assert written.goal_id == goal_id
    assert written.verdict == ReadOutcomeKind.DUPLICATE.value, (
        "ADR-0252 §18 arm 31's composition half: the episode is already in the turn's "
        "supply, so the read classifies DUPLICATE with admitted == 0 - and §5 makes that "
        "member answering, because whether the supply already held the records is a fact "
        "about this turn's supply and not about the response"
    )
    assert written.admitted == 0, "the round was unproductive for ADR-0251 §7's fold"
    assert written.returned == 1, "and the source did return a record to compose a region from"
    assert written.requested == EvidenceApplicability(topics=(_TOPIC,)), "§3, from the typed ask"
    assert written.supported == (EvidenceApplicability(topics=(_TOPIC,)),), "§3, from the record"
    assert written.records == ("episode-1",), "§1: a durable kind names what it returned"
    assert written.as_of is None, "§4: the owner's own records declare no reading-level instant"
    assert await plans.get_evidence(written.id) == written, "§12: read back by id, unchanged"

    assert earlier.standing is EvidenceStanding.SUPERSEDED, (
        "§8: the later row covers it, answers, and is strictly later — so it refreshes it"
    )
    assert earlier.superseded_by == written.id, "and the mark names what did it (§1)"
    return written


async def test_a_turns_row_reaches_the_fake_store_and_supersedes_what_it_refreshes() -> None:
    """§14's write and §8's predicate, end to end over ``FakePlanStore``."""
    harness, planner, goal_id, _ = await _drive(FakePlanStore(now=lambda: AT))

    written = await _assert_round_trip(harness.plans, goal_id)
    assert planner.evidence[0] == (digest_of(_standing_row(goal_id)),), (
        "§11: this turn's planner saw the history as it stood, not the row it was about "
        "to write — a row is persisted after every planner call the turn makes"
    )
    assert written.attempt_id is not None


async def test_a_turns_row_reaches_the_sqlite_store_and_supersedes_what_it_refreshes(
    sqlite_plans: SqlitePlanStore,
) -> None:
    """The same turn, the same assertions, over the other conforming implementation."""
    _, _, goal_id, _ = await _drive(sqlite_plans)

    await _assert_round_trip(sqlite_plans, goal_id)


async def test_a_later_turn_is_handed_the_digest_of_what_an_earlier_turn_wrote() -> None:
    """§11 across turns: the round trip the row exists for.

    An attempt that read a forecast on turn 1 held, on turn 4, "no record that it did, no
    record of what the response covered". This is that closed: the second turn's planner
    is handed a digest projected from the row the first turn wrote, carrying what the
    response supported and no identifier of any kind.
    """
    harness, planner, goal_id, conversation = await _drive(FakePlanStore(now=lambda: AT))
    written = await _assert_round_trip(harness.plans, goal_id)

    await harness.engine.converse(
        f"and the {_TOPIC} tomorrow", timeout=PATIENT, conversation_id=conversation
    )

    latest = planner.evidence[-1]
    assert digest_of(written) in latest, "the row the earlier turn wrote, projected"
    assert written.id not in repr(latest), "§11: the digest carries no identifier of any kind"


async def test_two_concurrent_writes_on_one_goal_still_supersede(
    sqlite_plans: SqlitePlanStore,
) -> None:
    """§8 holds when two of this engine's turns write one goal's evidence at once.

    **The store's indivisible write is not enough on its own, and §12 is why.** It puts
    the refresh predicate in ``orchestration`` and the atomicity in the store, so the
    ``supersedes`` a write carries was computed from an ``evidence_of`` read taken
    *before* that write. Two turns that both read the history before either writes each
    compute their set against the same older history, and the later covering row is
    then written with an empty ``supersedes`` — leaving the earlier row ``STANDING``
    where §8's six limbs require it ``SUPERSEDED``, which is the "retained historical
    disagreement" correction 1 exists to remove.

    **The interleaving this arm reaches is the harder of the two**, and it was worth
    finding out which: both writes compute a set naming the row the turn wrote, the
    first applies its mark, and the second is then refused **whole** on §12's rule that
    a mark is never re-applied — so without the lock the second turn does not merely
    miss a retirement, it fails with a ``PlanningError``. Removing the
    ``_evidence_lock`` fails this arm on exactly that.

    ``Engine._record_evidence`` is entered directly because that is the section under
    test: driving two ``converse`` calls would have both rows take the harness's one
    fixed instant, and §8 limb 6 then refuses the supersession for the **right** reason
    — equal effective instants supersede in neither direction — so the arm could not
    tell the race from the rule. The two rows here differ only in ``read_at``.

    The residual a process-local lock cannot close — a second process over one data
    directory — is #2339.
    """
    harness, _, goal_id, _ = await _drive(sqlite_plans)
    written = await _assert_round_trip(sqlite_plans, goal_id)

    def _covering(row_id: str, minutes: int) -> GoalEvidence:
        """A row covering everything written before it, read ``minutes`` later."""
        return written.model_copy(
            update={
                "id": row_id,
                "read_at": written.read_at + timedelta(minutes=minutes),
                "standing": EvidenceStanding.STANDING,
                "superseded_by": None,
            }
        )

    await asyncio.gather(
        harness.engine._record_evidence((_covering("row-a", 1),)),
        harness.engine._record_evidence((_covering("row-b", 2),)),
    )

    history = await sqlite_plans.evidence_of(goal_id)
    standing = [row.id for row in history.rows if row.standing is EvidenceStanding.STANDING]
    assert standing == ["row-b"], (
        "one row stands: each write's predicate saw the marks the write before it "
        "applied, so the newest covering row retired every older one rather than "
        "standing beside a row a stale read had left alone"
    )
    displaced = await sqlite_plans.get_evidence(written.id)
    assert displaced is not None
    assert displaced.standing is EvidenceStanding.SUPERSEDED
    assert displaced.superseded_by == "row-a", "retired by the first of the two to run"
    middle = await sqlite_plans.get_evidence("row-a")
    assert middle is not None
    assert middle.standing is EvidenceStanding.SUPERSEDED
    assert middle.superseded_by == "row-b", "and that one by the second, in its turn"
