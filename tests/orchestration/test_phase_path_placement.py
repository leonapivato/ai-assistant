"""A phases episode's placement, and a remembered belief's (ADR-0309 §5:10, ADR-0217 §3:12).

ADR-0204 §2's two terms are evaluated over every memory record the activation was given
or obtained — its windows' records, what either recall run kept, what its calls
returned, digested ones included, and what its story views showed — once, at the freeze,
over every round, the windows left out on a pass of unbounded audience. A belief a round
remembers is placed by what planning had been given when it planned that round. With the
opt-in unset, today's path places its episode by its own evaluation, unchanged.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

import pytest
from story_support import activation, address, episode
from test_activation_state import _admitted
from test_authorizer import _ACTIVATION
from test_engine import AT, Harness, NoStepPlanner
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
from understanding_support import understanding_stage

from ai_assistant.core.types import (
    ActivationRecall,
    BeliefBand,
    ControllerStage,
    InputOrigin,
    LabelKind,
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
    SemanticMemory,
    StageOutcome,
    StoryActor,
)
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.disclosure import UnboundedAudienceSupply
from ai_assistant.orchestration.recall import Recalled
from ai_assistant.orchestration.remembering import remembered_record_id
from ai_assistant.orchestration.story_links import Candidates, ShortView
from ai_assistant.orchestration.understanding import Fetched, TranscriptWindow
from ai_assistant.testing import FakeMemoryStore, FakeStoryStore, FakeToolCallingCompleter

if TYPE_CHECKING:
    from ai_assistant.core.types import EpisodicMemory, MemoryRecord
    from ai_assistant.orchestration.disclosure import TurnSupply

_STAMPED: Final = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=AT)
_UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())


def _stamped(record: SemanticMemory) -> SemanticMemory:
    """``record``, already stamped: ADR-0204 §2's second term, as ADR-0217 §1:3 carries it."""
    return record.model_copy(update={"placement": _STAMPED})


async def _frozen_with(
    *,
    supply: TurnSupply = _BOUNDED,
    windows: tuple[EpisodicMemory, ...] | None = None,
    recalled: tuple[EpisodicMemory | SemanticMemory, ...] = (),
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
    ).model_copy(update={"about_person": "Sam"}),
    "an unplaced source": _remembered("reported", MemorySource.EXTERNAL, "moved to 3pm"),
}


@pytest.mark.parametrize("record", _RECALLED.values(), ids=_RECALLED.keys())
@pytest.mark.parametrize("supply", [_BOUNDED, _UNBOUNDED], ids=["bounded", "unbounded"])
async def test_a_recall_find_withheld_or_stamped_places_the_episode(
    record: MemoryRecord, supply: TurnSupply
) -> None:
    """ADR-0204 §2:2's two terms over what recall kept, on every pass."""
    assert isinstance(record, SemanticMemory)
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
    harness = Harness(planner=NoStepPlanner(), understanding=understanding_stage(), memory=store)
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
        RoundResponse(calls=(_call("c1", "search_memory", query="dentist", looking_for="when"),)),
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
    records: tuple[SemanticMemory, ...], placed: Placement
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
    harness = Harness(planner=NoStepPlanner(), understanding=understanding_stage(), memory=memory)
    path = _phases(completer, stories=stories)(harness)
    working = _begun(path)
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)
    (planning,) = [one for one in path.stages() if one.name is ControllerStage.PLANNING]
    state = _admitted()

    async def controlled() -> None:
        assert (await planning.run(given)).outcome is StageOutcome.DONE

    await path.run(given, controlled, state=state)

    shown = completer.calls[0].messages[1].content
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
        RoundResponse(calls=(_call("c1", "read_story", story="S1"),)),
    )
    harness = Harness(planner=NoStepPlanner(), understanding=understanding_stage(), memory=memory)
    path = _phases(completer, stories=stories, look_ups=True)(harness)
    working = path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel("c1"), messages=()),
        conversation_id="c1",
        trigger_origin=InputOrigin.USER,
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


# --- over every round, and the belief a round remembers ----------------------------------


async def test_the_value_is_taken_over_every_round_and_a_belief_by_its_own_round() -> None:
    """ADR-0309 §5:10 for the episode; ADR-0217 §3:12 for each belief.

    Round 1 remembers before anything withheld has been given, and searches; its search
    returns a stamped fact, which round 2 is shown. Round 2 remembers again. The first
    belief was produced over a clean supply and is written for anyone; the second over
    one holding the stamped fact, and is written for the owner alone; the episode, taken
    once at the freeze over both rounds, is placed for the owner alone.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call("c1", "remember", statement="The user sees a dentist."),
                _call("c2", "search_memory", query="dentist", looking_for="when"),
            ),
        ),
        RoundResponse(
            text="Noted.",
            calls=(_call("c3", "remember", statement="The dentist is Dr Rao."),),
        ),
    )
    stamped = _stamped(_remembered("said", MemorySource.USER_ASSERTED, f"{_DENTIST} with Dr Rao"))
    harness = await _searching_harness(completer, stamped)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "remember my dentist")
    frozen = await _settled(harness, conversation, seeded=frozenset({"said"}))

    effects = await harness.plans.activation_effects([frozen.id.removeprefix("activation:")])
    remembered = {one.round: one for one in effects if one.capability == "remember"}
    assert frozen.processing_record is not None
    first, second = (one.id for one in frozen.processing_record.rounds)
    written_first = await harness.memory.get(remembered_record_id(remembered[first].id))
    written_second = await harness.memory.get(remembered_record_id(remembered[second].id))
    assert written_first is not None
    assert written_second is not None
    assert written_first.placement == Placement()
    assert written_second.placement == _STAMPED
    assert frozen.placement == _STAMPED


# --- with the opt-in unset -------------------------------------------------------------------


async def test_with_the_opt_in_unset_todays_path_places_by_its_own_evaluation() -> None:
    """ADR-0309 §2:6: the old path's episode is placed by its own supply, unchanged.

    Today's chat turn retrieves the stamped fact for the input that names it, and its
    bounded evaluation stamps the episode; over an input naming nothing it does not.
    """
    for text, placed in (("dentist appointment", _STAMPED), ("hello", Placement())):
        store = FakeMemoryStore(now=lambda: AT)
        await store.add(_stamped(_remembered("said", MemorySource.USER_ASSERTED, _DENTIST)))
        harness = Harness(
            planner=NoStepPlanner(), understanding=understanding_stage(), memory=store
        )
        conversation = await _conversation(harness)

        await _say(harness, conversation, text)
        frozen = await _settled(harness, conversation, seeded=frozenset({"said"}))

        assert frozen.placement == placed, text
