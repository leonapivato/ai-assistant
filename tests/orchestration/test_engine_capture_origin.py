"""What a captured episode records about the supply its turn ran over (ADR-0223).

ADR-0221 §6 deferred one field and ADR-0223 stamps it: capture writes the captured
episode's ``Provenance.derived_from_external`` from **the turn's own selection**,
threaded per call site and never computed at capture. This module is ADR-0223 §10's
representative-input tests 1-7, 9 and 10, each named in the case that discharges it.
Test 7 lives in ``test_composing`` beside the origin phrases it is about; test 8 is
the ``interfaces`` surface arm's and lives with that lane.

**Three properties are worth naming, because each is a distinct way to get this
wrong and none of them is caught by the others.**

- The value is a disjunction over ``rests_on_recorded_external_content``, not over
  the band, so a ``DERIVED`` record carrying the mark taints a turn exactly as an
  ``ATTESTED`` one does (test 2).
- It is computed **once per pass**, above the branch that decides whether there is a
  step to drive, so the no-step branch stamps it too and the episode's mark and the
  runner's ``SelectionOrigin`` are the same boolean rather than two that agree
  (tests 3 and 4).
- The partition is **ADR-0204 §2's and not ADR-0221 §5's**, and the two differ on
  one site by decision: a routed pass carries its own ``modality`` and a
  ``derived_from_external`` of ``False``, because ``modality`` is about the user
  material the episode renders and this field is about the supply the turn ran over
  — which a routed pass does not have (test 6).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

import pytest
from test_engine import (
    AT,
    CAPABILITY,
    EGRESS_SCHEMA,
    PATIENT,
    Harness,
    NoStepPlanner,
    OneStepPlanner,
    _external_belief,
    _fresh_facade,
    bound_binder,
    egress_confirmable,
    tool,
)
from test_engine_capture import _captured, _replying
from test_engine_routing import (
    _QUERY,
    _UTTERANCE,
    _names,
    _routed_harness,
    _seed_belief,
    _token,
)

from ai_assistant.core.types import (
    ActionPlan,
    CurrentContext,
    Disposition,
    EgressBinding,
    EpisodicMemory,
    Goal,
    MemorySource,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadRequest,
    RoutableOperation,
    SemanticMemory,
    TimeOfDay,
    rests_on_recorded_external_content,
)
from ai_assistant.learning import ModelBackedObserver
from ai_assistant.planning import ModelBackedPlanner
from ai_assistant.testing import FakeFetcher, FakeModelProvider

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryRecord, ShownFile

#: ADR-0233 §15 leaves ``StepRunner._bound`` passing the fail-closed constant, and §6
#: refuses that value at construction — so every egress call in this tree is
#: unconstructable until the lane that follows computes it. The ADR names the state in
#: terms: "a field that lands with nothing writing it leaves a seam answering
#: ``PATH_WITHOUT_MODEL`` and refusing every send, which is the fail-closed direction
#: working and an unfinished job". **Strict**, so the marker is an obligation rather
#: than a licence: #2051's first act is deleting these, any test that still fails then
#: is a real defect, and any that passes while still marked fails the suite. Not one
#: assertion below is changed by the marking.
_REFUSED_UNTIL_THE_COMPOSER_LANDS: Final = (
    "ADR-0233 §15: the seam refuses every send until the composer lane (#2051) computes coverage"
)

#: The ask. It carries the seeded records' own terms so the store's lexical search
#: selects them — the supply has to *contain* the record for the disjunction to have
#: anything to find, and a case that silently retrieved nothing would pass an
#: implementation that hard-codes ``False``.
_ASK: Final = "send it to the address in the invite"

#: A span that appears only in the document under ADR-0230's fetch root, so a supply
#: carrying it can only have got it from a fetch.
_FETCHED: Final = "the address in the invite:"


# --- scaffolding --------------------------------------------------------------


def _marked_derived_belief(record_id: str = "rec-marked") -> SemanticMemory:
    """A ``DERIVED``-band belief carrying ADR-0106 §2's marker.

    ``OBSERVED`` puts it in the ``DERIVED`` band, where ``band_of`` answers nothing
    about externality and the field is the only thing that does — so this is the
    record that separates a disjunction over the *predicate* from one over the band.
    """
    return SemanticMemory(
        id=record_id,
        content=_ASK,
        fact=_ASK,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.7,
            last_updated=AT,
            derived_from_external=True,
        ),
    )


def _clean_belief(record_id: str = "rec-clean") -> SemanticMemory:
    """A belief the predicate is false of, in a band that could have carried it."""
    return SemanticMemory(
        id=record_id,
        content=_ASK,
        fact=_ASK,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.7, last_updated=AT),
    )


def _asserted_belief(record_id: str = "rec-asserted") -> SemanticMemory:
    """The user's own word, which ADR-0098 §1 makes external however it was composed."""
    return SemanticMemory(
        id=record_id,
        content=_ASK,
        fact=_ASK,
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
    )


def _quiet(**knobs: object) -> Harness:
    """A harness that plans nothing and answers with a constant.

    ``NoStepPlanner`` is the cheapest shape that still produces a turn, retrieves a
    supply and captures an episode — and it is the branch ADR-0223 §2 exists for, so
    it is also the default here rather than an afterthought.
    """
    return Harness(composing=_replying("Noted."), planner=NoStepPlanner(), **knobs)  # type: ignore[arg-type]  # the harness's own heterogeneous knobs


def _egress_harness(**knobs: object) -> Harness:
    """A harness whose one confirmable tool is bound to a connected account."""
    definition = egress_confirmable()
    return Harness(tools=(definition,), binder=bound_binder(definition), **knobs)  # type: ignore[arg-type]  # the harness's own heterogeneous knobs


def _allowable_egress_harness() -> Harness:
    """A harness whose bound tool the fake policy allows outright on a clean turn.

    ``tool()`` is low-risk, reversible, free and discloses nothing, so every clause
    of :class:`~ai_assistant.testing.FakeActionPolicy` but ADR-0181 §5's is silent
    on it. That is what makes the ruling read the origin fact and nothing else: the
    step executes on a clean turn and parks on a tainted one, so §6's product
    sentence is observable as a change of disposition rather than as a field.
    """
    definition = tool("smtp", parameters_schema=EGRESS_SCHEMA)
    return Harness(
        tools=(definition,),
        binder=bound_binder(definition),
        planner=OneStepPlanner(capability=CAPABILITY),
        composing=_replying("Sent."),
    )


def _stamps(records: tuple[MemoryRecord, ...]) -> list[str]:
    """The ids of the records in ``records`` the predicate is true of."""
    return [
        record.id for record in records if rests_on_recorded_external_content(record.provenance)
    ]


# --- §10 test 1: the disjunction, both directions ------------------------------


async def test_a_turn_whose_supply_held_an_attested_record_captures_a_stamped_episode() -> None:
    """§10's test 1, positive half: §1's disjunction, over an ``ATTESTED`` record.

    ``rests_on_recorded_external_content`` is true of an ``ATTESTED`` record by
    ``band_of`` alone (ADR-0106 §1), so this is the plainest supply that taints a
    turn — a belief a connected source reported, selected into the model call the
    turn ran over. The selection is asserted rather than assumed: a case whose store
    returned nothing would pass an implementation that hard-coded ``True``.
    """
    harness = _quiet()
    await harness.memory.add(_external_belief())

    outcome = await harness.engine.converse(_ASK, timeout=PATIENT)

    assert outcome.turn is not None
    assert _stamps(tuple(outcome.turn.memories)) == ["rec-external"], (
        "the tainted record really was selected into this turn's supply"
    )
    (episode,) = await _captured(harness)
    assert episode.provenance.derived_from_external is True


async def test_a_turn_whose_supply_rested_on_nothing_external_captures_an_unstamped_one() -> None:
    """§10's test 1, negative half: ``OBSERVED`` and ``USER_ASSERTED`` only.

    The half that makes the positive one mean something. Both bands the supply holds
    here are bands ``rests_on_recorded_external_content`` is false of — ``DERIVED``
    with no marker, and ``ASSERTED``, which ADR-0098 §1 keeps false in principle
    because "a user who pastes an email into a turn is exercising judgement".

    What the ``False`` says is §7's sentence and no other: *no record in that supply
    carried the marker*. It is never *no external content was involved*.
    """
    harness = _quiet()
    await harness.memory.add(_clean_belief())
    await harness.memory.add(_asserted_belief())

    outcome = await harness.engine.converse(_ASK, timeout=PATIENT)

    assert outcome.turn is not None
    selected = {record.id for record in outcome.turn.memories}
    assert {"rec-clean", "rec-asserted"} <= selected, "both records really were selected"
    assert _stamps(tuple(outcome.turn.memories)) == []
    (episode,) = await _captured(harness)
    assert episode.provenance.derived_from_external is False


# --- §10 test 2: the predicate, not the band -----------------------------------


async def test_a_marked_derived_record_in_the_supply_stamps_the_episode() -> None:
    """§10's test 2: the second-order case, which a band test would miss.

    §1 fixes the value as the disjunction of
    ``rests_on_recorded_external_content`` over the turn's selection — **not** of
    ``band_of(...) is ATTESTED``. A ``DERIVED`` record carrying ADR-0106 §2's marker
    is a belief this system authored over material that included a connected
    source's report, and it carries the taint forward exactly as the report does. An
    implementation that tested the band would answer ``False`` here and would wash
    the externality off at the second hop instead of at the first.
    """
    harness = _quiet()
    await harness.memory.add(_marked_derived_belief())

    outcome = await harness.engine.converse(_ASK, timeout=PATIENT)

    assert outcome.turn is not None
    selected = {record.id for record in outcome.turn.memories}
    assert "rec-marked" in selected
    assert all(
        record.provenance.source is not MemorySource.EXTERNAL for record in outcome.turn.memories
    ), "nothing in this supply is ATTESTED, so only the predicate can find the taint"
    (episode,) = await _captured(harness)
    assert episode.provenance.derived_from_external is True


# --- §10 test 3: the branch §2 exists for --------------------------------------


async def test_a_pass_with_no_steps_stamps_the_same_value_as_one_with_a_step() -> None:
    """§10's test 3: the no-action branch, which a naive threading loses.

    Before ADR-0223 §2 the pass computed ``SelectionOrigin.over(turn.memories)``
    **inside** the branch that has a step to run, so the ``if not turn.plan.steps:``
    branch reached capture having never computed it. A stamp threaded from that call
    site would be unavailable on exactly the passes that plan nothing, which are not
    rare — every question a user asks that needs no tool is one.

    The two harnesses differ **only** in their planner, and the assertion is that
    they agree, so the case cannot pass by both answering ``False``: the positive
    value is asserted on both.
    """
    stepless = _quiet()
    await stepless.memory.add(_external_belief())
    stepped = Harness(tools=(tool(),), planner=OneStepPlanner(), composing=_replying("Sent."))
    await stepped.memory.add(_external_belief())

    await stepless.engine.converse(_ASK, timeout=PATIENT)
    stepped_outcome = await stepped.engine.converse(_ASK, timeout=PATIENT)

    assert stepped_outcome.step is not None
    assert stepped_outcome.step.disposition is Disposition.EXECUTED, "the pass really drove one"
    (without,) = await _captured(stepless)
    (with_step,) = await _captured(stepped)
    assert without.provenance.derived_from_external is True
    assert with_step.provenance.derived_from_external == without.provenance.derived_from_external


# --- §10 test 4: one value, two consumers --------------------------------------


@pytest.mark.xfail(strict=True, reason=_REFUSED_UNTIL_THE_COMPOSER_LANDS)
async def test_the_episodes_stamp_and_the_runners_origin_are_the_same_value() -> None:
    """§10's test 4: §2's invariant, exercised where the value is ``True``.

    §2's point is not that the two agree but that there is only one of them. If they
    could be computed separately, a conversation could hold an episode saying its
    turn ran over external material while that turn's own egress call said it did
    not — "the corpus would hold two answers to one question". The observable second
    consumer is the binding the ruling was taken over, read from the **recorded**
    decision rather than from anything the runner still held, because that is the
    value ADR-0181 §3 actually carries to the policy.
    """
    harness = _egress_harness()
    await harness.memory.add(_external_belief())

    outcome = await harness.engine.converse(_ASK, timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.AWAITING_CONFIRMATION
    recorded = await harness.trail.get("d-1")
    assert recorded is not None
    assert isinstance(recorded.egress_binding, EgressBinding)
    (episode,) = await _captured(harness)
    assert episode.provenance.derived_from_external is True
    assert (
        episode.provenance.derived_from_external
        == recorded.egress_binding.planned_with_external_content
    )


# --- §10 test 5: the parked turn's own value, retained -------------------------


@pytest.mark.xfail(strict=True, reason=_REFUSED_UNTIL_THE_COMPOSER_LANDS)
async def test_a_stamped_parks_resolution_is_stamped_though_the_resolving_pass_is_clean() -> None:
    """§10's test 5: §3's second case, exercised in the direction a recompute fails.

    The resolution's episode renders the **parked** turn's goal statement and plan
    rationale (ADR-0074 §3), from a pass that retrieves nothing of its own. So the
    value carried is that turn's own, "retained with the parked turn and applied
    unchanged. No implementation re-evaluates, recomputes or defaults it at the
    second capture".

    Exercised as a *stamped* park resolved by a clean pass, which is the direction
    that fails a recompute — the opposite direction passes an implementation that
    recomputes, because a clean park recomputed over an empty supply is clean too.
    The record that tainted the parking turn is **destroyed before the resume**, so
    even an implementation that went back to the store for it would answer ``False``
    here: what is asserted is that the value came from the retained park and from
    nowhere else.
    """
    harness = _egress_harness()
    await harness.memory.add(_external_belief())

    parked = await harness.engine.converse(_ASK, timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    assert await harness.memory.delete("rec-external") is True

    await harness.engine.resume(parked.step.confirmation.token, approved=True, timeout=PATIENT)

    park, resolution = await _captured(harness)
    assert park.provenance.derived_from_external is True
    assert resolution.provenance.derived_from_external is True, "the parked turn's own value (§3)"


# --- §10 test 6: the three passes carrying no turn -----------------------------


async def test_a_routed_pass_captures_false_though_the_store_holds_a_tainted_record() -> None:
    """§10's test 6, first arm: §3's third case, and the site the two partitions split on.

    A routed pass reaches no retrieval and no planner (ADR-0197 §1), so it selects
    nothing and there is no supply for the predicate to find. That is why it sits in
    §3's **third** case here while ADR-0221 §5 puts it in its **first** — ``modality``
    is about the user material the episode renders, which a routed pass has, and this
    field is about the supply the turn ran over, which it does not. "A lane reading
    the two partitions as one table will stamp it wrong."

    The store is seeded with a tainted record it would have selected on any
    non-routed pass, so the ``False`` is a statement about the routed pass rather
    than about an empty store.
    """
    harness = _routed_harness(router=_names(RoutableOperation.RECENT_READS))
    await harness.memory.add(_external_belief())

    outcome = await harness.engine.converse(_UTTERANCE, timeout=PATIENT)

    assert outcome.routed is not None
    assert outcome.turn is None, "a routed pass produces no TurnResult and selects nothing"
    (episode,) = await _captured(harness)
    assert episode.provenance.derived_from_external is False


async def test_a_routed_parks_resolution_captures_false() -> None:
    """§10's test 6, second arm: the resumption of a routed park.

    This episode "carries neither a turn nor an utterance and renders the bare fact
    of the resumption alone", so there is no turn to retain a value from and nothing
    in what it holds for a stamp to be about. ``False`` is a fact about this record,
    stated in code, rather than a default the site fell into.
    """
    harness = _routed_harness(router=_names(RoutableOperation.FORGET, _QUERY))
    await _seed_belief(harness.memory)
    await harness.memory.add(_external_belief())

    parked = await harness.engine.converse(_UTTERANCE, timeout=PATIENT)
    await harness.engine.resume(_token(parked), approved=True, timeout=PATIENT)

    park, resolution = await _captured(harness)
    assert park.provenance.derived_from_external is False
    assert resolution.provenance.derived_from_external is False


@pytest.mark.xfail(strict=True, reason=_REFUSED_UNTIL_THE_COMPOSER_LANDS)
async def test_a_resumption_recovered_from_durable_state_captures_false() -> None:
    """§10's test 6, third arm: no live turn, so nothing to retain.

    A park reconstructed by ``pending_confirmations`` on a fresh façade carries no
    ``TurnResult`` (ADR-0052), and its resolution's episode therefore renders no
    turn's goal statement and no turn's plan rationale. §3's third case again — and
    the arm that separates it from test 5, because the **parking** turn here was
    stamped and the recovered resolution still is not. That is not an inconsistency:
    the value belongs to what each episode holds, and this one holds no turn.
    """
    harness = _egress_harness()
    await harness.memory.add(_external_belief())

    await harness.engine.converse(_ASK, timeout=PATIENT)

    fresh = _fresh_facade(harness)
    pending = await fresh.pending_confirmations()
    assert len(pending) == 1
    recovered = await fresh.resume(pending[0].token, approved=True, timeout=PATIENT)
    assert recovered.turn is None

    park, resolution = await _captured(harness)
    assert park.provenance.derived_from_external is True
    assert resolution.provenance.derived_from_external is False


# --- §10 test 9: §6's product sentence, pinned ---------------------------------


@pytest.mark.xfail(strict=True, reason=_REFUSED_UNTIL_THE_COMPOSER_LANDS)
async def test_a_second_turn_after_a_stamped_first_turn_gets_no_allow() -> None:
    """§10's test 9: the egress consequence §6 accepts, end to end.

    §6's product sentence: "once a conversation has held one record resting on
    recorded external content, the episodes captured from the turns that saw it are
    stamped; those episodes are in the conversation's recent turns; and every
    subsequent turn of that conversation that reaches the egress seam is a
    confirmation rather than an allow".

    The record that tainted the first turn is **destroyed** before the second, so
    the only thing in the second turn's supply the predicate can find is the first
    turn's own captured episode — asserted, not assumed. The tool is one the fake
    policy allows outright on a clean turn, so the consequence shows up as a change
    of disposition: the control conversation below runs the same tool to
    ``EXECUTED`` on both turns.
    """
    harness = _allowable_egress_harness()
    await harness.memory.add(_external_belief())

    first = await harness.engine.converse(_ASK, timeout=PATIENT)
    assert first.conversation_id is not None
    (stamped,) = await _captured(harness)
    assert stamped.provenance.derived_from_external is True
    assert await harness.memory.delete("rec-external") is True

    second = await harness.engine.converse(
        _ASK, timeout=PATIENT, conversation_id=first.conversation_id
    )

    assert second.turn is not None
    assert _stamps(tuple(second.turn.memories)) == [stamped.id], (
        "the first turn's own episode is the only thing left carrying the fact"
    )
    assert second.step is not None
    assert second.step.disposition is Disposition.AWAITING_CONFIRMATION, (
        "ADR-0181 §5's third clause: no ruling on this request is ALLOW"
    )
    request = harness.policy.requests[-1]
    assert request.egress_binding is not None
    assert request.egress_binding.planned_with_external_content is True
    assert all(
        resolution.ruling.outcome.value != "allow" for resolution, _ in harness.policy.resolutions
    )


@pytest.mark.xfail(strict=True, reason=_REFUSED_UNTIL_THE_COMPOSER_LANDS)
async def test_a_conversation_that_never_held_an_external_record_keeps_its_allow() -> None:
    """The control for the case above, and it is not padding.

    Without it, an implementation that stamped every episode — or a policy that
    confirmed this tool unconditionally — would pass test 9. Same harness, same
    tool, same two turns, no external record: both turns execute, and the second
    turn's supply holds the first turn's unstamped episode.
    """
    harness = _allowable_egress_harness()

    first = await harness.engine.converse(_ASK, timeout=PATIENT)
    assert first.conversation_id is not None
    assert first.step is not None
    assert first.step.disposition is Disposition.EXECUTED
    (episode,) = await _captured(harness)
    assert episode.provenance.derived_from_external is False

    second = await harness.engine.converse(
        _ASK, timeout=PATIENT, conversation_id=first.conversation_id
    )

    assert second.turn is not None
    assert episode.id in {record.id for record in second.turn.memories}
    assert second.step is not None
    assert second.step.disposition is Disposition.EXECUTED


# --- §10 test 10: the two prompts that must not move ---------------------------


def _episode(*, marked: bool) -> EpisodicMemory:
    """One captured episode, stamped or not, identical in every other byte."""
    return EpisodicMemory(
        id="ep-1",
        content="The user asked: send the note. The assistant planned: one step.",
        occurred_at=AT,
        outcome="Sent.",
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.9,
            last_updated=AT,
            derived_from_external=marked,
        ),
    )


def _assembled(provider: FakeModelProvider) -> str:
    """Every message this provider was ever handed, joined."""
    return "\n".join(message.content for call in provider.calls for message in call.messages)


async def test_the_planners_rendering_of_a_stamped_episode_is_byte_identical() -> None:
    """§10's test 10, first half: §4's last clause, guarded at the planner.

    §4 gives the episodic origin arm to ``orchestration/composing.py`` and to nothing
    else: "``planning/planner.py``'s and ``learning/observer.py``'s renderings gain no
    origin phrase by this ADR". Their prompts are three copies of a table that must
    not become shared (ADR-0221 §3, golden rule 1), and the way a lane accidentally
    shares one is by "fixing" the other two to match. This is the guard on that.

    Driven through the real producer's public call rather than its private renderer,
    so what is compared is the prompt a model would actually receive.
    """
    decline = json.dumps({"rationale": "nothing to do", "steps": [], "no_capability_needed": True})
    stamped = FakeModelProvider(decline)
    unstamped = FakeModelProvider(decline)
    goal = Goal(
        id="g-1",
        statement="send the note",
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )
    context = CurrentContext(
        now=AT, time_of_day=TimeOfDay.MORNING, is_weekend=False, within_working_hours=True
    )

    for provider, marked in ((stamped, True), (unstamped, False)):
        await ModelBackedPlanner(provider).plan(
            goal, context=context, memories=(_episode(marked=marked),), capabilities=(CAPABILITY,)
        )

    assert _assembled(stamped) == _assembled(unstamped)


async def test_the_observers_rendering_of_a_stamped_episode_is_byte_identical() -> None:
    """§10's test 10, second half, and the guard on §9's first clause.

    §9: "``learning/observer.py`` and ``orchestration/observation.py`` compute no
    disjunction of this field over their batch today, and this ADR adds none, obliges
    none and is not cited toward one." Propagation is deferred until someone has a
    taint rate (§11), and this case is what makes a lane that reaches for it early do
    so deliberately rather than by editing a prompt that looked wrong.
    """
    stamped = FakeModelProvider(json.dumps({"beliefs": []}))
    unstamped = FakeModelProvider(json.dumps({"beliefs": []}))

    for provider, marked in ((stamped, True), (unstamped, False)):
        await ModelBackedObserver(provider).observe([_episode(marked=marked)])

    assert _assembled(stamped) == _assembled(unstamped)


# --- ADR-0230 §14 test 10: a fetched record taints the conversation ------------


#: A root holding one document whose text carries the ask's own terms, so the store's
#: lexical search is not what puts it in the supply — the **fetch** is.
_FETCH_ROOT: Final = {"invite.md": f"the address in the invite: {_ASK}"}


class _FetchingOneStepPlanner(OneStepPlanner):
    """Plans the same step every turn, and names a file on its **first call only**.

    The first turn fetches; every call after it asks for nothing. That is what makes
    the second turn's ruling evidence about the *captured episode* rather than about a
    second fetch — with a planner that named the file every turn, the consequence
    ADR-0230 §14 item 10 asserts would be indistinguishable from the first turn's own.
    """

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
    ) -> ActionPlan:
        """Answer the base plan, carrying a ``LOCAL_FILE`` ask the first time only."""
        first = self._calls == 0
        plan = await super().plan(
            goal,
            context=context,
            memories=memories,
            capabilities=capabilities,
            files=files,
        )
        if not first:
            return plan
        return plan.model_copy(
            update={
                "read_request": ReadRequest(asks=(ReadAsk(kind=ReadKind.LOCAL_FILE, entry="F1"),))
            }
        )


def _fetching_egress_harness() -> Harness:
    """``_allowable_egress_harness``, plus a fetcher and a planner that names a file.

    The store is seeded with **nothing** external, so the only thing that can taint
    the first turn is the document — which is ADR-0230 §5's mark doing the work
    ADR-0223 §6 then acts on.
    """
    definition = tool("smtp", parameters_schema=EGRESS_SCHEMA)
    return Harness(
        tools=(definition,),
        binder=bound_binder(definition),
        planner=_FetchingOneStepPlanner(capability=CAPABILITY),
        composing=_replying("Sent."),
        fetcher=FakeFetcher(_FETCH_ROOT, read_at=AT),
    )


@pytest.mark.xfail(strict=True, reason=_REFUSED_UNTIL_THE_COMPOSER_LANDS)
async def test_a_turn_that_fetched_stamps_its_capture_and_the_next_turn_asks() -> None:
    """ADR-0230 §14 item 10, end to end and not at the predicate.

    "A bounded-audience turn that fetches captures an episode whose
    ``derived_from_external`` is ``True``; the same turn's ``SelectionOrigin`` carries
    ``planned_with_external_content``; and a **subsequent** turn of that conversation
    reaching the egress seam is a confirmation rather than an allow."

    **This is the assertion standing between this rung and #1844's exfiltration
    channel.** ADR-0230 §8's containment is that a steered loop has nowhere to steer
    to, and the one outward path a steered plan can reach is the egress seam — where
    ADR-0223 §6's allow applies "exactly as it applies for any other reason", so "every
    subsequent turn of that conversation that reaches the egress seam is a
    confirmation rather than an allow". §5 calls that "the milestone's control rather
    than its cost", and this is where the control is observable.

    The store holds nothing external at any point, and the planner names the file on
    the first turn alone — so the second turn's ruling can only be reading the first
    turn's own captured episode, which is asserted rather than assumed.
    """
    harness = _fetching_egress_harness()

    first = await harness.engine.converse(_ASK, timeout=PATIENT)

    assert first.conversation_id is not None
    assert first.turn is not None
    assert [record.id for record in first.turn.memories if _FETCHED in record.content] != [], (
        "the fetch really did put the document in this turn's supply"
    )
    (stamped,) = await _captured(harness)
    assert stamped.provenance.derived_from_external is True, "ADR-0223 §1 over ADR-0230 §5"

    second = await harness.engine.converse(
        _ASK, timeout=PATIENT, conversation_id=first.conversation_id
    )

    assert second.turn is not None
    assert _stamps(tuple(second.turn.memories)) == [stamped.id], (
        "the first turn's own episode is the only thing carrying the fact"
    )
    assert _FETCHED not in "\n".join(record.content for record in second.turn.memories), (
        "and the second turn fetched nothing of its own (ADR-0230 §10: turn-scoped)"
    )
    assert second.step is not None
    assert second.step.disposition is Disposition.AWAITING_CONFIRMATION, (
        "ADR-0181 §5's third clause: no ruling on this request is ALLOW"
    )
    request = harness.policy.requests[-1]
    assert request.egress_binding is not None
    assert request.egress_binding.planned_with_external_content is True
    assert all(
        resolution.ruling.outcome.value != "allow" for resolution, _ in harness.policy.resolutions
    )


@pytest.mark.xfail(strict=True, reason=_REFUSED_UNTIL_THE_COMPOSER_LANDS)
async def test_a_conversation_whose_root_showed_a_file_nobody_named_keeps_its_allow() -> None:
    """The control: a wired fetcher is not itself a taint.

    Without it the case above would pass on an implementation that stamped every turn
    a fetcher was wired into — which is precisely what a mark taken from the listing
    rather than from the fetch would do, and what ADR-0230 §3 forbids by making an
    unnamed listing carry no meaning at all.
    """
    definition = tool("smtp", parameters_schema=EGRESS_SCHEMA)
    harness = Harness(
        tools=(definition,),
        binder=bound_binder(definition),
        planner=OneStepPlanner(capability=CAPABILITY),
        composing=_replying("Sent."),
        fetcher=FakeFetcher(_FETCH_ROOT, read_at=AT),
    )

    first = await harness.engine.converse(_ASK, timeout=PATIENT)
    assert first.conversation_id is not None
    (episode,) = await _captured(harness)
    assert episode.provenance.derived_from_external is False

    second = await harness.engine.converse(
        _ASK, timeout=PATIENT, conversation_id=first.conversation_id
    )

    assert second.step is not None
    assert second.step.disposition is Disposition.EXECUTED


async def test_servicing_a_local_file_ask_is_not_itself_an_egress() -> None:
    """ADR-0230 §14 item 10's second clause, and §8's property (b) asserted.

    "Servicing the ask engages no ``DestinationProtocol`` member, requires no
    confirmation of its own and routes through no egress seam." §8 argues it from the
    shape of the act — "a fetch is an open, a read and a close on a filesystem: this
    system composes no outward request and names no destination on the fetch path" —
    and this is that stated as behaviour.

    The harness holds a **bound, confirmable egress tool**, so there is a
    ``DestinationProtocol`` member to engage and a seam to route through; the plan
    drives no step, so the only thing this turn did was fetch. Nothing reaches the
    policy at all.
    """
    definition = egress_confirmable()
    harness = Harness(
        tools=(definition,),
        binder=bound_binder(definition),
        planner=_FetchingOneStepPlanner(capability="answer_only"),
        composing=_replying("Noted."),
        fetcher=FakeFetcher(_FETCH_ROOT, read_at=AT),
    )

    outcome = await harness.engine.converse(_ASK, timeout=PATIENT)

    assert outcome.turn is not None
    assert [record.id for record in outcome.turn.memories if _FETCHED in record.content] != [], (
        "the turn really did fetch"
    )
    assert harness.policy.requests == [], "no permission request, so no confirmation"
    assert harness.policy.resolutions == [], "and no ruling of any kind"
    assert outcome.step is None or outcome.step.disposition is not (
        Disposition.AWAITING_CONFIRMATION
    ), "the fetch required no confirmation of its own"
