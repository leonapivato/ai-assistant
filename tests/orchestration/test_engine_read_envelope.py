"""The read envelope where the engine decides what the turn stage is told (ADR-0226).

Three of ADR-0226 §11's tests are about what happens *above*
:meth:`~ai_assistant.orchestration.loop.LearningLoop.respond`, so they live here
rather than beside the servicer:

* **item 1** — the reply-vocabulary question answering through the hop, driven end
  to end through ``converse`` so that "the answer carries it" is the reply and not
  a seam. §11 calls this "the milestone's exit shape and the one test that fails if
  the hop is merely wired".
* **item 5**'s engine arm — ``converse_spoken`` declares its channel's audience
  unbounded (ADR-0200 §3), so its request is declined by the object the engine
  already mints rather than by a second fact it has to keep in step.
* **item 10**'s two post-plan arms — a turn rejected for capacity and a turn whose
  ``PlanStore.save_plan`` raises, both of which happen **after** the loop has
  planned and serviced, and neither of which may suppress §9's record.

Everything else §11 owes this lane is in ``test_loop_reads.py``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog
from test_converse_spoken import _MP4, _recording
from test_engine import AT, PATIENT, Harness, NoStepPlanner, OneStepPlanner, confirmable
from test_engine_routing import _routed_harness, _router

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    ActionPlan,
    EpisodicMemory,
    MemorySource,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadRequest,
    SemanticMemory,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.reads import READ_AUDIT_EVENT, Servicing, TriggerOutcome
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping, Sequence

    from ai_assistant.core.types import CurrentContext, Goal, MemoryRecord

#: The token the assistant introduced and the user never used. §11 item 1's whole
#: premise is that a blind read keyed on the *question's* vocabulary cannot reach
#: the exchange holding it, because only ``content`` is embedded.
_LENDER: Final = "Brightpath Financial"

_QUESTION: Final = "which lender was recommended"

#: The utterance ``_routed_harness`` routes a ``forget`` on (ADR-0197 §1).
_ROUTED: Final = "please forget that preference"

#: A router reply that names no operation, which ADR-0197 §1 makes a **decline**.
_DECLINED: Final = json.dumps({"no_operation": True})


def _hop(*labels: str) -> ReadRequest:
    return ReadRequest(asks=(ReadAsk(kind=ReadKind.CITATION_HOP, labels=labels),))


def _query(text: str) -> ReadRequest:
    return ReadRequest(asks=(ReadAsk(kind=ReadKind.SIGHTED_QUERY, query=text),))


class _AskingPlanner(NoStepPlanner):
    """``NoStepPlanner`` with a scripted request beside its plan, recording its supply.

    Subclassed rather than written out so the plan is the one every other engine
    case is built on: ADR-0226 §4's field is additive, so "a planner that emits a
    request" and "a planner" differ by one field and nothing else.
    """

    def __init__(self, request: ReadRequest | None) -> None:
        self._request = request
        self.calls: list[tuple[MemoryRecord, ...]] = []

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
    ) -> ActionPlan:
        self.calls.append(tuple(memories))
        plan = await super().plan(
            goal, context=context, memories=memories, capabilities=capabilities
        )
        return plan.model_copy(update={"read_request": self._request})


class _AskingOneStepPlanner(OneStepPlanner):
    """``OneStepPlanner`` with a request beside it — §11 item 10's capacity arm.

    ``_admit_and_reserve`` is reached only where the plan has a step, so the turn
    that meets backpressure has to be one the engine would otherwise have driven.
    """

    def __init__(self, request: ReadRequest) -> None:
        super().__init__()
        self._request = request

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
    ) -> ActionPlan:
        plan = await super().plan(
            goal, context=context, memories=memories, capabilities=capabilities
        )
        return plan.model_copy(update={"read_request": self._request})


def _belief(record_id: str, content: str, *, evidence: tuple[str, ...] = ()) -> SemanticMemory:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=Provenance(
            source=MemorySource.OBSERVED, confidence=0.6, last_updated=AT, evidence=evidence
        ),
    )


def _episode(record_id: str, content: str) -> EpisodicMemory:
    return EpisodicMemory(
        id=record_id,
        content=content,
        occurred_at=AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )


def _echoing_composer() -> ComposingStage:
    """A composing stage whose reply says whether the exchange reached the prompt.

    The point of driving item 1 through the engine rather than through the turn
    stage is that "the answer carries it" becomes an assertion about the answer. The
    model is a fake, so what it can honestly report is what it was *shown* — which
    is exactly the property the hop exists to produce.
    """

    def reply(messages: Sequence[Any]) -> str:
        prompt = "\n".join(str(message.content) for message in messages)
        return _LENDER if _LENDER in prompt else "I have no record of that."

    return ComposingStage(model=FakeModelProvider(reply=reply), streaming=FakeStreamingCompleter())


def _records(captured: Sequence[MutableMapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [event for event in captured if event["event"] == READ_AUDIT_EVENT]


def _record(captured: Sequence[MutableMapping[str, Any]]) -> Mapping[str, Any]:
    [only] = _records(captured)
    return only


# --------------------------------------------------------------------------- #
# §11 item 1: the reply-vocabulary question answers through the hop            #
# --------------------------------------------------------------------------- #


async def _seeded_store() -> FakeMemoryStore:
    """A store holding the exchange and the belief that cites it.

    The belief carries the *question's* vocabulary and the episode carries the
    *answer's*: "a question whose answer shares no wording with the record that holds
    it is not a ranking problem, and no allocation of a blind read fixes it".
    """
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(_episode("episode-1", f"{_LENDER} is the best fit for your budget."))
    await memory.add(
        _belief(
            "belief-1",
            "the user asked about a lender for the house purchase",
            evidence=("episode-1",),
        )
    )
    return memory


async def test_the_reply_vocabulary_question_answers_through_the_hop() -> None:
    """§11 item 1: the milestone's exit shape, end to end.

    The blind read returns the belief and not the exchange — it is keyed on the
    question's words, and only ``content`` is embedded. The planner names that
    belief's label; the hop reaches the episode by pointer; and the answer carries
    it. #1844's sentence, mechanised: the hop "is **not a search**, so the reply's
    vocabulary never has to match anything; and it reaches the exchange by pointer,
    which is the only mechanism that answers 'which lender did you recommend?'"

    **This fails if the hop is merely wired**, which is why the assertion is the
    composed reply rather than the fourth group.
    """
    planner = _AskingPlanner(_hop("M1"))
    harness = Harness(memory=await _seeded_store(), planner=planner, composing=_echoing_composer())

    outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    planned = [record.id for record in planner.calls[0]]
    assert planned == ["belief-1"], "the blind read reached the belief and not the exchange"
    assert outcome.turn is not None
    assert [record.id for record in outcome.turn.memories] == ["belief-1", "episode-1"]
    assert outcome.reply == _LENDER


async def test_the_same_question_without_the_emission_cannot_answer() -> None:
    """The control that makes the case above a finding rather than a coincidence.

    The same store, the same question and the same composer — and a planner that
    asks for nothing. The exchange is unreachable, which is the system as it stands
    before this envelope and is what the +22.8 points of "hop" in the replay's split
    are made of.
    """
    harness = Harness(
        memory=await _seeded_store(),
        planner=_AskingPlanner(None),
        composing=_echoing_composer(),
    )

    outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    assert outcome.turn is not None
    assert [record.id for record in outcome.turn.memories] == ["belief-1"]
    assert outcome.reply == "I have no record of that."


# --------------------------------------------------------------------------- #
# §11 item 5's engine arm: converse_spoken declines                            #
# --------------------------------------------------------------------------- #


async def test_a_spoken_turn_services_nothing_and_records_the_emission_as_declined() -> None:
    """§11 item 5, on the operation ADR-0200 §3 declares unbounded.

    ADR-0203 §2's backfill clause is what decided this: on such a turn the planner
    judges sufficiency over a supply the subtraction has already thinned, so a read
    it emits "is shaped by what was withheld even though the planner never saw it".

    The engine derives the refusal from the supply object it already mints, which is
    what keeps §5 mechanical rather than remembered — and the emission is still
    recorded, because "what is scoped is the **servicing**, so the trigger goes on
    being measured on every channel".
    """
    planner = _AskingPlanner(_hop("M1"))
    harness = Harness(memory=await _seeded_store(), planner=planner)

    with structlog.testing.capture_logs() as captured:
        spoken = await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    turn = spoken.outcome.turn
    assert turn is not None
    assert turn.memories == planner.calls[0], "no fourth group"
    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["servicing"] == Servicing.DECLINED.value
    assert record["returned"] == 0


async def test_a_typed_turn_of_the_same_engine_is_serviced() -> None:
    """The pair to the case above: the scoping is the channel's and not the engine's.

    One engine, one planner, one store — and the request is serviced on ``converse``
    and declined on ``converse_spoken``. That is ADR-0199 §1's posture being a
    function of the output channel's audience alone.
    """
    planner = _AskingPlanner(_hop("M1"))
    harness = Harness(memory=await _seeded_store(), planner=planner)

    with structlog.testing.capture_logs() as captured:
        outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    assert outcome.turn is not None
    assert [record.id for record in outcome.turn.memories] == ["belief-1", "episode-1"]
    record = _record(captured)
    assert record["servicing"] == Servicing.SERVICED.value
    assert record["new"] == 1


# --------------------------------------------------------------------------- #
# §11 item 10's post-plan arms: the record is gated on nothing                 #
# --------------------------------------------------------------------------- #


async def test_a_turn_rejected_for_capacity_still_contributes_its_numerator() -> None:
    """§11 item 10's first arm, and §9's reason for it.

    ``AssistantEngine`` admits and reserves capacity **after** the loop has planned
    and serviced, "so a full system rejects a turn whose planner had already fired".
    Under a record gated on the turn completing, the fire rate would read low by
    exactly the number of turns that went wrong.
    """
    harness = Harness(
        tools=(confirmable(),),
        planner=_AskingOneStepPlanner(_query("an earlier exchange")),
        max_outstanding_confirmations=1,
    )
    parked = await harness.engine.converse("send one", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None

    with (
        structlog.testing.capture_logs() as captured,
        pytest.raises(RuntimeError, match="already awaiting an answer"),
    ):
        await harness.engine.converse("send two", timeout=PATIENT)

    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["servicing"] == Servicing.SERVICED.value


async def test_a_turn_whose_plan_cannot_be_persisted_still_contributes_its_numerator() -> None:
    """§11 item 10's second arm: a ``PlanStore.save_plan`` failure loses no record.

    §9 makes the emission "conditioned on nothing: not on the plan being persisted,
    not on the turn completing, and not on capacity being admitted". The record owes
    nothing to those later stages, "because it carries no reference into them".
    """
    harness = Harness(memory=await _seeded_store(), planner=_AskingPlanner(_hop("M1")))

    async def refuse(plan: ActionPlan) -> str:
        del plan
        msg = "fake: the plan store is unavailable"
        raise MemoryStoreError(msg)

    harness.plans.save_plan = refuse  # type: ignore[method-assign]

    with structlog.testing.capture_logs() as captured, pytest.raises(MemoryStoreError):
        await harness.engine.converse(_QUESTION, timeout=PATIENT)

    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["servicing"] == Servicing.SERVICED.value
    assert record["new"] == 1


async def test_a_routed_pass_reaches_no_turn_stage_and_writes_no_record() -> None:
    """The reading this lane takes on a pass that never reaches a supply.

    ADR-0197 §1 ends the pipeline at a taken route: "no history is read, no goal is
    minted, no context is assembled, no memories are retrieved, no plan is made or
    driven". §9 puts the record in the turn — "at any point in the turn after the
    servicing decision is known" — and a routed pass has no servicing decision to
    make and no supply to judge, so it emits none rather than emitting a
    not-reached record from a second site.

    Recorded as a case rather than left implicit, because it is the one shape §8's
    three outcomes do not obviously classify, and a later lane should meet the
    reading rather than rediscover the question. A **declined** route is a turn like
    any other and does write one, which is the pair below.
    """
    harness = _routed_harness()

    with structlog.testing.capture_logs() as captured:
        outcome = await harness.engine.converse(_ROUTED, timeout=PATIENT)

    assert outcome.routed is not None, "the route was taken"
    assert _records(captured) == []


async def test_a_declined_route_runs_the_ordinary_pipeline_and_writes_one_record() -> None:
    """The pair to the case above: a declined route is a turn (ADR-0197 §1).

    "The pass proceeds exactly as it does today and the outcome it returns carries
    no trace of the stage having run" — so it reaches the turn stage, reaches the
    servicing decision, and contributes its denominator.
    """
    harness = _routed_harness(
        router=_router(_DECLINED), planner=_AskingPlanner(None), memory=await _seeded_store()
    )

    with structlog.testing.capture_logs() as captured:
        outcome = await harness.engine.converse(_QUESTION, timeout=PATIENT)

    assert outcome.routed is None, "the route was declined"
    assert _record(captured)["trigger"] == TriggerOutcome.NOT_FIRED.value
