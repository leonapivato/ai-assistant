"""A phases episode's placement (ADR-0309 §5:10).

ADR-0204 §2's two terms are evaluated over every memory record the activation was given
or obtained — its windows' records, what either recall run kept, what its calls
returned, digested ones included, and what its story views showed — once, at the freeze,
over every round, the windows left out on a pass of unbounded audience. A belief a round
remembered was placed by what planning had been given when it planned that round
(ADR-0217 §3:12) until ADR-0328 §13's interim retired; ``remember`` now records a
candidate and writes no belief.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final

import pytest
from story_support import activation, address, episode
from test_activation_state import _admitted
from test_authorizer import _ACTIVATION
from test_authorizer import _episode as _own_episode
from test_engine import AT, Harness
from test_engine_phases import (
    _BOUNDED,
    _DENTIST,
    _REPORTED,
    _SAID,
    _SETTLE,
    _begun,
    _call,
    _conversation,
    _Given,
    _harness,
    _phases,
    _recall_digest,
    _recalling_harness,
    _remembered,
    _say,
    _searching_harness,
    _settled,
)
from test_planning import _recorded_trigger
from understanding_support import understanding_stage

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationRecall,
    BeliefBand,
    ControllerStage,
    LabelKind,
    Memory,
    MemoryKind,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanningLabel,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    RoundResponse,
    StageOutcome,
    StoryActor,
)
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.disclosure import UnboundedAudienceSupply
from ai_assistant.orchestration.recall import Recalled
from ai_assistant.orchestration.story_links import Candidates, ShortView
from ai_assistant.orchestration.understanding import Fetched, TranscriptWindow
from ai_assistant.testing import FakeMemoryStore, FakeStoryStore, FakeToolCallingCompleter

if TYPE_CHECKING:
    from ai_assistant.core.types import EpisodicMemory, MemoryRecord
    from ai_assistant.orchestration.disclosure import TurnSupply

_STAMPED: Final = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=AT)
_UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())


def _stamped(record: Memory) -> Memory:
    """``record``, already stamped: ADR-0204 §2's second term, as ADR-0217 §1:3 carries it."""
    return record.model_copy(update={"placement": _STAMPED})


async def _frozen_with(
    *,
    supply: TurnSupply = _BOUNDED,
    windows: tuple[EpisodicMemory, ...] | None = None,
    recalled: tuple[EpisodicMemory | Memory, ...] = (),
    candidates: Candidates | None = None,
) -> bool:
    """The value the freeze sets, over a pass whose stages before planning gave these.

    The path runs no round: what the windows and recall gave is held at the freeze.
    """
    completer = FakeToolCallingCompleter.scripted()
    harness = _harness(completer)
    path = _phases(completer)(harness)
    working = _begun(path)
    working.messages.append("Hi.")
    fetched = Fetched(
        episodes=windows,
        recalled=recalled,
        fetched=tuple(one.id for one in (*(windows or ()), *recalled)),
        missing=(),
    )
    given = _Given(
        deadline=asyncio.get_running_loop().time() + _SETTLE,
        phases=working,
        understanding_fetch=fetched,
        supply=supply,
        story_candidates=candidates,
    )
    state = _admitted()
    taken: list[object] = []

    async def controlled() -> None:
        # Taken once, at the freeze: nothing is set while the pass runs.
        taken.append(state.facts)

    await path.run(given, controlled, state=state)

    assert taken == [None]
    assert state.facts is not None
    return state.facts.supplied_withheld


def _window_episode(*, stamped: bool) -> EpisodicMemory:
    return episode("earlier", placement=_STAMPED if stamped else None)


# --- the windows, and the pass's audience ----------------------------------------------


async def test_a_stamped_window_record_places_the_episode_on_a_bounded_pass() -> None:
    """ADR-0309 §5:10, ADR-0210 §1:5: on a bounded pass nothing is left out."""
    assert await _frozen_with(windows=(_window_episode(stamped=True),))
    assert not await _frozen_with(windows=(_window_episode(stamped=False),))


async def test_the_windows_are_left_out_on_an_unbounded_pass() -> None:
    """ADR-0309 §5:10, ADR-0210 §1:1: the windows set nothing when unbounded."""
    assert not await _frozen_with(supply=_UNBOUNDED, windows=(_window_episode(stamped=True),))


# --- understanding's candidate stories ----------------------------------------------------


@pytest.mark.parametrize("supply", [_BOUNDED, _UNBOUNDED], ids=["bounded", "unbounded"])
async def test_a_stamped_episode_of_a_candidate_story_places_the_episode(
    supply: TurnSupply,
) -> None:
    """Understanding was shown it (ADR-0300 §6:1), though it cited and linked nothing.

    A candidate story's episodes are not a window's records, so they count on every
    pass; the view is all that brought this one.
    """
    view = ShortView(
        story_id="trip", lines=(), notes=(), episodes=(episode("other", placement=_STAMPED),)
    )
    clean = ShortView(story_id="trip", lines=(), notes=(), episodes=(episode("other"),))

    assert await _frozen_with(supply=supply, candidates=Candidates(views=(view,)))
    assert not await _frozen_with(supply=supply, candidates=Candidates(views=(clean,)))


# --- what recall kept --------------------------------------------------------------------


_RECALLED: Final = {
    "stamped": _stamped(_remembered("said", MemorySource.USER_ASSERTED, "the dentist")),
    "about someone else": _remembered(
        "sam", MemorySource.USER_ASSERTED, "Sam's dentist"
    ).model_copy(update={"subjects": ("Sam",)}),
    "an unplaced source": _remembered("reported", MemorySource.EXTERNAL, "moved to 3pm"),
}


@pytest.mark.parametrize("record", _RECALLED.values(), ids=_RECALLED.keys())
@pytest.mark.parametrize("supply", [_BOUNDED, _UNBOUNDED], ids=["bounded", "unbounded"])
async def test_a_recall_find_withheld_or_stamped_places_the_episode(
    record: MemoryRecord, supply: TurnSupply
) -> None:
    """ADR-0204 §2:2's two terms over what recall kept, on every pass."""
    assert isinstance(record, Memory)
    assert await _frozen_with(supply=supply, recalled=(record,))


async def test_a_recall_find_placed_as_speakable_leaves_the_episode_for_anyone() -> None:
    """§2:2: ``False`` only where neither term holds."""
    said = _remembered("said", MemorySource.USER_ASSERTED, "the dentist")
    assert not await _frozen_with(recalled=(said,), windows=(_window_episode(stamped=False),))


def _kept(memory_id: str) -> Recalled:
    """A recall decision keeping one remembered fact, as recall records one."""
    item = RecalledItem(
        kind=MemoryKind.SEMANTIC,
        id=memory_id,
        excerpt="a remembered fact",
        provenance=RecallProvenance.USER,
        standing=BeliefBand.ASSERTED,
        rests_on_recorded_external_content=False,
        found_by=(RecallCue.ACTIVATION_INPUT,),
    )
    return Recalled(
        ActivationRecall(
            outcome=RecallOutcome.FOUND, cues=(RecallCue.ACTIVATION_INPUT,), items=(item,)
        ),
        scores=(0.9,),
    )


async def test_a_stamped_fact_planning_fetches_of_what_recall_kept_places_the_episode() -> None:
    """Either run's kept records, as planning fetches them before its first round (§3).

    No window and no fetch by understanding: the stamped fact reaches the activation only
    through planning's own fetch of what recall kept.
    """
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="Noted."))
    store = FakeMemoryStore(now=lambda: AT)
    await store.add(_stamped(_SAID))
    harness = Harness(understanding=understanding_stage(), memory=store)
    path = _phases(completer)(harness)
    working = _begun(path)
    working.second_recall = _kept(_SAID.id)
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)
    (planning,) = [one for one in path.stages() if one.name is ControllerStage.PLANNING]
    state = _admitted()

    async def controlled() -> None:
        assert (await planning.run(given)).outcome is StageOutcome.DONE

    await path.run(given, controlled, state=state)

    assert working.found is not None
    assert [one.id for one in working.found.recalled] == [_SAID.id]
    assert state.facts is not None
    assert state.facts.supplied_withheld


async def test_an_outside_fact_recalls_digest_reads_is_held_for_the_freeze() -> None:
    """What recall kept, digested (§5:10): the outside fact reaches only the digest.

    Recall's digest is due on its own, planning never fetched what recall kept, and the
    fact the digest read is one a channel of unbounded audience withholds.
    """
    case = await _recall_digest()

    assert (await case.digesting.run(case.given)).outcome is StageOutcome.DONE

    assert case.working.found is None
    assert case.working.recall_digest_fetch is not None
    assert case.working.supplied.withheld(_BOUNDED)
    assert case.working.supplied.withheld(_UNBOUNDED)


async def test_end_to_end_an_outside_fact_recall_kept_places_the_episode() -> None:
    """Recall's second run keeps a fact a source reported, which its digest reads."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="It is on Friday."))
    harness, _ = await _recalling_harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when?")
    frozen = await _settled(harness, conversation, seeded=frozenset({"activation:past"}))

    assert frozen.placement == _STAMPED


# --- what its calls returned, digested ones included -------------------------------------


def _search_then_answer() -> FakeToolCallingCompleter:
    return FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "search_memories", query="dentist", looking_for="when"),)),
        RoundResponse(text="It is with Dr Rao."),
    )


@pytest.mark.parametrize(
    ("records", "placed"),
    [
        pytest.param((_SAID,), Placement(), id="a placed fact: anyone"),
        pytest.param((_stamped(_SAID),), _STAMPED, id="a stamped fact: the owner"),
        pytest.param((_REPORTED,), _STAMPED, id="a digested outside fact: the owner"),
    ],
)
async def test_a_memory_searchs_records_place_the_episode(
    records: tuple[Memory, ...], placed: Placement
) -> None:
    """What a call returned, fetched for planning or read by a digest (§5:10)."""
    harness = await _searching_harness(_search_then_answer(), *records)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when is the dentist?")
    frozen = await _settled(harness, conversation, seeded=frozenset(one.id for one in records))

    assert frozen.placement == placed


async def test_a_quick_question_over_nothing_leaves_the_episode_for_anyone() -> None:
    """ADR-0204 §1:3: an activation given nothing withheld writes the default."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="Hello!"))
    harness = _harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "hi")
    frozen = await _settled(harness, conversation)

    assert frozen.placement == Placement()


# --- what a story view showed --------------------------------------------------------------


async def test_a_stamped_episode_a_story_view_shows_places_the_episode() -> None:
    """A story view's episodes are memory records the activation was given (§5:10).

    No window and no recall: the stamped episode reaches the activation only as the
    latest episode of the story it belongs to.
    """
    stories = FakeStoryStore(now=lambda: AT)
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(episode("other", placement=_STAMPED))
    created = await stories.create(
        [activation("other"), activation(_ACTIVATION)], actor=StoryActor.OWNER
    )
    assert created.story_id is not None
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="Noted."))
    harness = Harness(understanding=understanding_stage(), memory=memory)
    path = _phases(completer, stories=stories)(harness)
    working = _begun(path)
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)
    (planning,) = [one for one in path.stages() if one.name is ControllerStage.PLANNING]
    state = _admitted()

    async def controlled() -> None:
        assert (await planning.run(given)).outcome is StageOutcome.DONE

    await path.run(given, controlled, state=state)

    shown = completer.calls[0].exchange.briefing
    assert address("other") in {one.id for one in working.labels.labels}, shown
    assert state.facts is not None
    assert state.facts.supplied_withheld


async def test_a_stamped_episode_a_storys_full_view_shows_is_held_for_the_freeze() -> None:
    """What a call returned (§5:10): a story read's full view, its episodes included.

    The activation is not in the story, so no story view before the round shows it; it
    was shown the story's label by an earlier round, and reads its full view.
    """
    stories = FakeStoryStore(now=lambda: AT)
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(episode("past", placement=_STAMPED))
    created = await stories.create([activation("past")], actor=StoryActor.OWNER)
    assert created.story_id is not None
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "read_matter", matter="S1"),)),
    )
    harness = Harness(understanding=understanding_stage(), memory=memory)
    path = _phases(completer, stories=stories, look_ups=True)(harness)
    working = path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel("c1"), messages=()),
        conversation_id="c1",
        trigger=_recorded_trigger(),
        owner_records=True,
        labels=(PlanningLabel(label="S1", kind=LabelKind.STORY, id=created.story_id),),
    )
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)
    stages = {one.name: one for one in path.stages()}

    assert (await stages[ControllerStage.PLANNING].run(given)).outcome is StageOutcome.DONE
    assert not working.supplied.withheld(_BOUNDED)
    for stage in (ControllerStage.AUTHORIZING, ControllerStage.ACTING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE

    (view,) = working.pages.values()
    assert [one.id for one in view.latest] == [address("past")]
    assert working.supplied.withheld(_BOUNDED)


async def test_a_story_reads_view_is_held_though_a_call_beside_it_fails_the_round() -> None:
    """What a call returned is obtained, whatever became of the round's other calls.

    The story read returns its view; the remember beside it cannot be claimed, so acting
    ends the round on that error. The episodes the read returned are still held.
    """
    stories = FakeStoryStore(now=lambda: AT)
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(_own_episode())
    await memory.add(episode("past", placement=_STAMPED))
    created = await stories.create([activation("past")], actor=StoryActor.OWNER)
    assert created.story_id is not None
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call("c1", "read_matter", matter="S1"),
                _call(
                    "c2",
                    "remember_fact",
                    fact="The trip is on.",
                    why="a plan",
                    rests_on_this_stimulus=True,
                ),
            )
        ),
    )
    harness = Harness(understanding=understanding_stage(), memory=memory)
    claim = harness.plans.claim_activation_effect

    async def unclaimable(effect: ActivationEffect, /, **kwargs: Any) -> Any:
        if effect.capability == "remember_fact":
            msg = "the plan store could not record the claim"
            raise PlanningError(msg)
        return await claim(effect, **kwargs)

    setattr(harness.plans, "claim_activation_effect", unclaimable)  # noqa: B010 — one method replaced on the instance
    path = _phases(completer, stories=stories, look_ups=True)(harness)
    working = path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel("c1"), messages=()),
        conversation_id="c1",
        trigger=_recorded_trigger(),
        owner_records=True,
        labels=(PlanningLabel(label="S1", kind=LabelKind.STORY, id=created.story_id),),
    )
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)
    stages = {one.name: one for one in path.stages()}
    for stage in (ControllerStage.PLANNING, ControllerStage.AUTHORIZING):
        assert (await stages[stage].run(given)).outcome is StageOutcome.DONE

    acted = await stages[ControllerStage.ACTING].run(given)

    assert acted.outcome is StageOutcome.FAILED
    # ADR-0356 §8:6, ADR-0358 §11:2: the read acting handed back done is held under its
    # result all the same, so its entry keeps what it showed.
    assert [one.story_id for one in working.pages.values()] == [created.story_id]
    assert working.supplied.withheld(_BOUNDED)


# --- over every round -------------------------------------------------------------------


async def test_the_value_is_taken_over_every_round() -> None:
    """ADR-0309 §5:10: taken once, at the freeze, over every round.

    Round 1 records a candidate before anything withheld has been given, and searches;
    its search returns a stamped fact, which round 2 is shown. Round 2 records another.
    The episode, taken once at the freeze over both rounds, is placed for the owner
    alone, and neither candidate writes a belief (ADR-0329 §3:3).
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call(
                    "c1",
                    "remember_fact",
                    fact="The user sees a dentist.",
                    why="health",
                    rests_on_this_stimulus=True,
                ),
                _call("c2", "search_memories", query="dentist", looking_for="when"),
            ),
        ),
        RoundResponse(
            text="Noted.",
            calls=(
                _call(
                    "c3",
                    "remember_fact",
                    fact="The dentist is Dr Rao.",
                    why="health",
                    rests_on_results=["R1"],
                ),
            ),
        ),
    )
    stamped = _stamped(_remembered("said", MemorySource.USER_ASSERTED, f"{_DENTIST} with Dr Rao"))
    harness = await _searching_harness(completer, stamped)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "remember my dentist")
    frozen = await _settled(harness, conversation, seeded=frozenset({"said"}))

    effects = await harness.plans.activation_effects([frozen.id.removeprefix("activation:")])
    assert frozen.processing_record is not None
    rounds = [one.id for one in frozen.processing_record.rounds]
    remembered = [one.round for one in effects if one.capability == "remember_fact"]
    assert remembered == rounds
    assert [one.id for one in await harness.memory.export() if isinstance(one, Memory)] == ["said"]
    assert frozen.placement == _STAMPED
