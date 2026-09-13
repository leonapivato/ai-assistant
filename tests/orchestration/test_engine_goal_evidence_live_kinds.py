"""ADR-0252 §3's composition and §8's supersession on the kinds the deployment performs.

Issue #2366 read the M32 acceptance run's rows — ``requested=None`` and ``supported=()``
on every one — and concluded that *"the two fields that give a row its meaning are empty
on every read kind the running system can perform"*, so that §8's refresh test *"cannot
fire end to end"*. The rows it read were a **scratch** hub's, created that hour; the
production ``plans.db`` was outside that run's fence.

These arms drive the composition on the memory kinds over records shaped as the live
store's own producers write them, and they pin what that survey actually shows:

* **``supported`` is reachable on the memory kinds.** §3 composes one region per record
  the ask returned, from that record's own ``topics``, ``participants`` and
  ``about_person`` — and a record that carries one of those contributes one. A
  ``SIGHTED_QUERY`` reads
  :data:`~ai_assistant.orchestration.conversations.BELIEF_KINDS`, and a belief carrying
  ``topics`` is the ordinary live shape rather than an unusual one.
* **§8's supersession therefore fires end to end**, on a `SIGHTED_QUERY`, through
  ``Engine`` and a conforming ``PlanStore``: the later row covers the standing one, and
  the standing one comes back ``SUPERSEDED`` with ``superseded_by`` naming it.
* **An empty ``supported`` is a fact about the record and not about the composition.**
  A turn's own captured episode is written with ``topics`` and ``participants`` empty
  (:meth:`~ai_assistant.orchestration.conversations.ConversationService.episode_of`) and
  is labelled only later, by the observation pass
  (:meth:`~ai_assistant.orchestration.observation.ObservationPass._label`). A row over an
  unlabelled record carries no region, which is §3's *"a record carrying no applied axis
  contributes no region"* working, and is what the scratch run saw.

What these arms do **not** claim. ``WEB_SEARCH`` and ``LOCAL_FILE`` rows do carry
``supported`` empty, and ADR-0252 §3 states that in terms over both minting clauses —
that is the decision rather than a defect, and §15 names decision 8's reader as what
changes it. ``requested`` is likewise absent on four kinds of five by §3 as written.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import AT, PATIENT, Harness, NoStepPlanner
from test_engine_goal_association import _associating, _goal, _seed

from ai_assistant.core.types import (
    AssociationVerdict,
    Capture,
    EpisodicMemory,
    EvidenceApplicability,
    EvidenceBasis,
    EvidenceStanding,
    GoalEvidence,
    MemorySource,
    Modality,
    Placement,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadOutcomeKind,
    ReadRequest,
    SemanticMemory,
)
from ai_assistant.orchestration.evidence import region_of
from ai_assistant.testing import FakeMemoryStore, FakePlanStore

if TYPE_CHECKING:
    from ai_assistant.core.types import MemoryRecord

#: The label the seeded records carry and the seeded row supports, so the region the
#: live read composes **covers** the standing row's — which is §8 limb 4.
_TOPIC: Final = "weather"

_GOAL: Final = "goal-campsite"

#: A sighted query, which is the kind the acceptance run's two memory-side rows were
#: written from. Its ask has no typed part, so §3 leaves ``requested`` absent on it.
_SIGHTED: Final = ReadRequest(
    asks=(ReadAsk(kind=ReadKind.SIGHTED_QUERY, query=f"what the {_TOPIC} is doing"),)
)

#: A hop naming the supply's first record, which is the other memory kind the run
#: exercised — its one row carried ``verdict=duplicate``, because a named record is in
#: the supply by construction (ADR-0229 §2). ``M1`` is the first record the turn's own
#: retrieval put in front of the planner, which is the one record the store holds.
_HOP: Final = ReadRequest(asks=(ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M1",)),))


def _belief(*, topics: tuple[str, ...]) -> SemanticMemory:
    """A belief shaped as the live store holds one.

    The live store's belief-kind records carry ``topics`` and carry **no**
    ``about_person`` and no ``Provenance.attestation`` — so the topics axis is the one
    §3 applies, and the window axis is not applied at all (which is §3's own dated
    observation about this corpus's producers).

    Args:
        topics: The labels the record carries, empty for a record no pass has labelled.

    Returns:
        The record.
    """
    return SemanticMemory(
        id="belief-1",
        content=f"the lake is usually dry when they ask about the {_TOPIC}",
        fact=f"the lake is usually dry when they ask about the {_TOPIC}",
        topics=topics,
        about_person=None,
        placement=Placement(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=AT),
    )


def _captured_episode() -> EpisodicMemory:
    """One turn's own episode, with the fields the capture path fills and no others.

    ``ConversationService.episode_of`` writes ``id``, ``content``, ``occurred_at``,
    ``outcome``, ``disposition``, ``capture``, ``expires_at``, ``provenance`` and
    ``placement`` — and **neither** ``topics`` **nor** ``participants``. Both arrive
    later, from ``ObservationPass._label``, and only on a pass that reaches this episode.

    Returns:
        The record, as the capture path leaves it.
    """
    return EpisodicMemory(
        id="episode-1",
        content=f"The user asked: what is the {_TOPIC} doing.",
        occurred_at=AT,
        capture=Capture(modality=Modality.TEXT),
        placement=Placement(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )


def _labelled_episode() -> EpisodicMemory:
    """The same episode after the observation pass filed it (ADR-0239 §3).

    That pass replaces ``topics`` and ``participants`` and carries every other field
    across unchanged, so this differs from :func:`_captured_episode` in exactly the two
    fields §3 composes a region from.

    Returns:
        The record, labelled.
    """
    return _captured_episode().model_copy(update={"topics": (_TOPIC,), "participants": ("Marta",)})


def _standing_row(goal_id: str, kind: ReadKind) -> GoalEvidence:
    """A row an earlier turn of this goal left standing, read an hour ago.

    Args:
        goal_id: The goal it belongs to.
        kind: What was read — §8 limb 3 requires the refreshing row to match it.

    Returns:
        The row.
    """
    return GoalEvidence(
        id="row-earlier",
        goal_id=goal_id,
        attempt_id="attempt-earlier",
        basis=EvidenceBasis.READ_OUTCOME,
        read_kind=kind,
        supported=(EvidenceApplicability(topics=(_TOPIC,)),),
        supported_elided=0,
        read_at=AT - timedelta(hours=1),
        records=("record-0",),
        returned=1,
        admitted=1,
        verdict=ReadOutcomeKind.RETURNED_RECORDS.value,
        standing=EvidenceStanding.STANDING,
    )


class _AskingOnce(NoStepPlanner):
    """A planner that emits one request on each turn's first call.

    The request is dropped once the turn has been told what became of its ask
    (ADR-0251 §3's carrier is non-empty from the second call on), which is ADR-0228
    §2(b) ending the turn on its second call.
    """

    def __init__(self, request: ReadRequest) -> None:
        self._request = request

    async def plan(self, goal: Any, **kwargs: Any) -> Any:
        """Answer with the ordinary empty plan, asking once per turn.

        Args:
            goal: The brief, passed through.
            **kwargs: The ``Planner`` Protocol's keywords.

        Returns:
            The plan, carrying the request on the turn's first call.
        """
        produced = await super().plan(
            goal,
            utterance=kwargs["utterance"],
            context=kwargs["context"],
            memories=kwargs["memories"],
            capabilities=kwargs["capabilities"],
        )
        asked = None if kwargs["read_outcomes"] else self._request
        return produced.model_copy(
            update={"plan": produced.plan.model_copy(update={"read_request": asked})}
        )


async def _drive(
    record: MemoryRecord, request: ReadRequest, kind: ReadKind
) -> tuple[FakePlanStore, str]:
    """Run one turn of a goal that already holds a standing row of ``kind``.

    Args:
        record: The one record the store holds, so the ask reaches it and ``M1`` names
            it.
        request: What the planner asks for on the turn's first call.
        kind: The read kind the standing row was written from.

    Returns:
        The store the engine was wired with and the goal's id.
    """
    plans = FakePlanStore(now=lambda: AT)
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(record)
    harness = Harness(
        planner=_AskingOnce(request),
        memory=memory,
        plans=plans,
        associator=_associating(AssociationVerdict.CONTINUES),
    )
    conversation = (await harness.conversations.begin(None)).id
    goal = await _seed(
        plans,
        _goal(_GOAL, "book a campsite", conversation=conversation),
        engaged_in=conversation,
    )
    await plans.record_evidence(_standing_row(goal.id, kind))

    outcome = await harness.engine.converse(
        f"what is the {_TOPIC} doing", timeout=PATIENT, conversation_id=conversation
    )
    assert outcome.turn is not None
    return plans, goal.id


async def test_a_sighted_query_row_carries_the_records_own_region_and_supersedes() -> None:
    """§3 composes from the record and §8 then fires, on the kind production performs.

    This is issue #2366's decisive claim driven end to end: a ``SIGHTED_QUERY`` over a
    belief carrying ``topics`` writes a row whose ``supported`` is that record's own
    region, and the standing row it covers is marked in the same write.
    """
    plans, goal_id = await _drive(_belief(topics=(_TOPIC,)), _SIGHTED, ReadKind.SIGHTED_QUERY)

    history = await plans.evidence_of(goal_id)
    earlier, written = history.rows

    assert written.read_kind is ReadKind.SIGHTED_QUERY
    assert written.requested is None, (
        "§3: a sighted query's only argument is a composed query, which ADR-0228 §11 "
        "rules a model completion no lane treats as evidence of anything"
    )
    assert written.supported == (EvidenceApplicability(topics=(_TOPIC,)),), (
        "§3's first source: one region per record the ask returned, from that record's "
        "own values — this is what #2366 reports as structurally unreachable"
    )
    assert written.records == ("belief-1",), "§1: a durable kind names what it returned"
    assert written.returned == 1

    assert earlier.standing is EvidenceStanding.SUPERSEDED, (
        "§8: the later row is of the same basis and kind, covers the earlier row's "
        "support, answers, and is strictly later — so it refreshes it"
    )
    assert earlier.superseded_by == written.id, "and the mark names what did it (§1)"


async def test_a_citation_hop_row_carries_the_named_records_region() -> None:
    """The other memory kind the acceptance run exercised composes from its records too.

    The run's one hop row carried ``verdict=duplicate`` and ``supported=()``. The verdict
    is ADR-0229 §2 working — a named record is in the supply by construction, so nothing
    is admitted — and §5 makes it **answering**; the empty support was the record's own
    state, not the kind's.
    """
    plans, goal_id = await _drive(_belief(topics=(_TOPIC,)), _HOP, ReadKind.CITATION_HOP)

    history = await plans.evidence_of(goal_id)
    _, written = history.rows

    assert written.read_kind is ReadKind.CITATION_HOP
    assert written.verdict == ReadOutcomeKind.DUPLICATE.value
    assert written.supported == (EvidenceApplicability(topics=(_TOPIC,)),), (
        "§3: the named record's own applied axis, composed from the record and never "
        "from the label the ask carried"
    )


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        pytest.param(_captured_episode(), None, id="as the capture path writes one"),
        pytest.param(
            _labelled_episode(),
            EvidenceApplicability(participants=("Marta",), topics=(_TOPIC,)),
            id="as the observation pass leaves one",
        ),
        pytest.param(_belief(topics=()), None, id="a belief no pass has labelled"),
        pytest.param(
            _belief(topics=(_TOPIC,)),
            EvidenceApplicability(topics=(_TOPIC,)),
            id="a belief carrying its topics",
        ),
    ],
)
def test_whether_a_region_is_composed_is_a_fact_about_the_record(
    record: MemoryRecord, expected: EvidenceApplicability | None
) -> None:
    """The same composition, over the two states this system's own producers leave.

    An episode is written unlabelled and labelled later, so a row over a turn's own
    freshly captured episode carries no region and a row over the same episode after the
    observation pass carries one. Neither is a property of the read kind.

    Args:
        record: The record the ask returned.
        expected: The region §3 composes from it, or ``None``.
    """
    assert region_of(record) == expected
