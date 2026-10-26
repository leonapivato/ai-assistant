"""One matter, one activation, over constructed states (ADR-0349 §5-§7, §9-§10).

The engine drives these through whole passes in ``test_phases_matters``. Here each rule
is held apart: who is of one standing (§7:5), what is a pure read (ADR-0341 §2), what
understanding's in-progress section shows (§5:2-§5:10), when an activation is settled for
the waits (§7:12, §7:15), the takeover stage's one step (§7:4-§7:8, §7:17-§7:24), and the
answer to an offer (§7:20-§7:23).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Final

import pytest
from test_engine import tool
from test_engine_phases import _BOOK

from ai_assistant.core.config import Settings
from ai_assistant.core.types import (
    ActivationStop,
    ActivationUnderstanding,
    CapabilityEffect,
    ChannelIdentity,
    ChannelInput,
    DataTier,
    EpisodicMemory,
    InputOrigin,
    JoinedInput,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    RecordedInputMessage,
    TextChannelPayload,
    ToolDefinition,
    UnderstandingGround,
    UnderstandingOmission,
    UnderstandingProducer,
    WholeTextReply,
)
from ai_assistant.orchestration.activation_state import (
    ActivationState,
    Commitment,
    EpisodeProgress,
    admit_channel,
)
from ai_assistant.orchestration.disclosure import (
    BoundedAudienceSupply,
    UnboundedAudienceSupply,
)
from ai_assistant.orchestration.lookups import LOOK_UPS, READ_STORY, SEARCH_MEMORY
from ai_assistant.orchestration.matter_calls import (
    ANSWER_OFFER,
    LOOK_UP_ACTIVATION,
    STOP_ACTIVATION,
)
from ai_assistant.orchestration.matters import (
    DEFAULT_HELD_INPUT_LIMIT,
    DEFAULT_IN_PROGRESS_LIMIT,
    THE_USER,
    Answered,
    Became,
    InputStanding,
    Matters,
    NotAsAsked,
    TakeAnswer,
    in_progress,
    input_standing,
    is_pure_read,
    settled,
)
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.orchestration.story_calls import STORY_CALLS
from ai_assistant.orchestration.task_scheduler import SCHEDULE
from ai_assistant.testing import FakeMemoryStore, FakePlanStore
from ai_assistant.tools.web_search import WEB_SEARCH

_AT: Final = datetime(2026, 10, 21, 9, tzinfo=UTC)
_IDS: Final = (
    "0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11",
    "1c9a9f1f-3b6d-4d66-8b7d-7b3d2a1c1e22",
    "2dab0a2a-4c7e-4e77-9c8e-8c4e3b2d2f33",
    "3ebc1b3b-5d8f-4f88-8d9f-9d5f4c3e3a44",
)
_USERS: Final = input_standing(origin=InputOrigin.USER, established=True)
_SUPPLY: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())


def _place(name: str) -> ChannelIdentity:
    return ChannelIdentity(channel_type="conversation", instance_id=name)


def _said(text: str, *, position: int | None = 1) -> RecordedInputMessage:
    return RecordedInputMessage(text=text, sent_at=_AT, position=position)


def _episode(state: ActivationState, activation_id: str) -> EpisodicMemory:
    return EpisodicMemory(
        id=f"activation:{activation_id}",
        content="",
        occurred_at=_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_AT),
        processing_record=state.open_processing(),
        placement=Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_AT),
    )


def _running(  # noqa: PLR0913 — the place, the id, and one knob per fact a case varies
    place: str,
    activation_id: str,
    *,
    order: int,
    standing: InputStanding | None = _USERS,
    text: str = "book Riverside",
    episode: bool = True,
    channel: ChannelIdentity | None = None,
) -> ActivationState:
    """An admitted activation on ``place`` whose pass has begun, its episode written."""
    state = admit_channel(
        ChannelInput(target=channel or _place(place), payload=TextChannelPayload(text=text)),
        WholeTextReply(),
        clock=lambda: _AT,
        id_factory=lambda: activation_id,
    )
    state.standing = standing
    state.input_messages = (_said(text),)
    state.order = order
    if episode:
        state.capture = EpisodeProgress(
            address=f"activation:{activation_id}",
            captured_at=_AT,
            written=_episode(state, activation_id),
        )
    return state


def _version(*continues: str, version: int = 1) -> ActivationUnderstanding:
    return ActivationUnderstanding(
        version=version,
        recorded_at=_AT,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning=f"reading {version}",
        meaning_ground=UnderstandingGround.STATED,
        continues=continues,
    )


def _understood(state: ActivationState, *continues: str) -> ActivationUnderstanding:
    """Record the activation's first understanding version, naming ``continues``."""
    understanding = _version(*continues)
    state.understood(understanding, limit=4)
    return understanding


async def _no_stop(activation_id: str) -> ActivationStop:
    del activation_id
    return ActivationStop.STOPPED


def _matters(states: list[ActivationState], *, held: int = DEFAULT_HELD_INPUT_LIMIT) -> Matters:
    return Matters(
        running=lambda: states,
        plans=FakePlanStore(now=lambda: _AT),
        memory=FakeMemoryStore(now=lambda: _AT),
        stop=_no_stop,
        held_input_limit=held,
        in_progress_limit=DEFAULT_IN_PROGRESS_LIMIT,
    )


# --- §9: the limits ----------------------------------------------------------------


def test_the_default_limits_are_the_settings_own() -> None:
    """An engine built without the composition root's values takes the settings' defaults."""
    assert Settings.model_fields["held_input_limit"].default == DEFAULT_HELD_INPUT_LIMIT
    assert Settings.model_fields["in_progress_limit"].default == DEFAULT_IN_PROGRESS_LIMIT


def test_a_limit_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="ADR-0349"):
        _matters([], held=0)


# --- §7:5: one standing --------------------------------------------------------------


def test_only_the_same_established_author_with_the_same_authority_and_origin_meet() -> None:
    assert _USERS.meets(_USERS)
    forward = input_standing(origin=InputOrigin.OUTSIDE, established=False)
    assert forward.author is None
    assert not forward.users_authority
    assert not forward.meets(_USERS)
    assert not _USERS.meets(forward)
    assert not forward.meets(forward)
    assert not _USERS.meets(InputStanding(THE_USER, users_authority=False, origin=InputOrigin.USER))
    assert not _USERS.meets(
        InputStanding(THE_USER, users_authority=True, origin=InputOrigin.OUTSIDE)
    )
    assert not _USERS.meets(
        InputStanding("someone else", users_authority=True, origin=InputOrigin.USER)
    )


# --- ADR-0341 §2: the pure read ------------------------------------------------------


@pytest.mark.parametrize(
    "declared", [*LOOK_UPS, LOOK_UP_ACTIVATION], ids=lambda one: str(one.capability)
)
def test_each_look_up_is_a_pure_read(declared: ToolDefinition) -> None:
    """§2:1, ADR-0349 §6:4: a look-up writes nothing, its own records, in the hub."""
    assert declared.writes == ()
    assert declared.effect is CapabilityEffect.OWN_RECORDS
    assert not declared.leaves_hub
    assert is_pure_read(declared)


@pytest.mark.parametrize(
    "declared",
    [*STORY_CALLS, REMEMBER_CANDIDATE, WEB_SEARCH, _BOOK, STOP_ACTIVATION, ANSWER_OFFER],
    ids=lambda one: str(one.capability),
)
def test_a_write_a_call_that_leaves_the_hub_and_one_in_the_world_are_not(
    declared: ToolDefinition,
) -> None:
    """§2:1, ADR-0349 §4:12, §7:20: the stop and the answer write, so each is an act."""
    assert not is_pure_read(declared)


def test_a_call_that_changes_nothing_and_stays_in_the_hub_is_still_a_pure_read() -> None:
    declared = tool().model_copy(update={"effect": CapabilityEffect.NONE, "leaves_hub": False})
    assert is_pure_read(declared)


def test_a_declaration_decides_never_a_name() -> None:
    """§2:2: the look-ups' properties under another name read; a write under theirs does not."""
    renamed = ToolDefinition.model_validate(
        {**SEARCH_MEMORY.model_dump(), "id": "opening_hours", "capability": "opening_hours"}
    )
    assert is_pure_read(renamed)
    writing = ToolDefinition.model_validate(
        {**READ_STORY.model_dump(), "writes": (DataTier.PERSONAL,)}
    )
    assert not is_pure_read(writing)


@pytest.mark.parametrize("declared", [STOP_ACTIVATION, LOOK_UP_ACTIVATION, ANSWER_OFFER])
def test_the_calls_on_running_work_are_declared_as_a_cancel_is(declared: ToolDefinition) -> None:
    """§4:7, §6:4, §7:20: own records, in the hub, never unknown, safe to repeat."""
    assert declared.effect is CapabilityEffect.OWN_RECORDS
    assert not declared.leaves_hub
    assert not declared.outcome_can_be_unknown
    assert declared.safe_to_repeat


# --- §5: the in-progress section ------------------------------------------------------


def test_the_section_shows_the_same_persons_running_work_on_any_place_newest_first() -> None:
    """§5:2, §5:6, §5:10: every place, the viewer's own included, newest first."""
    older = _running("a", _IDS[0], order=1)
    here = _running("c", _IDS[1], order=2, text="for two")
    viewer = _running("c", _IDS[2], order=3)
    here.committed = True

    entries = in_progress(
        [older, here, viewer], viewer=_IDS[2], person="person:owner", supply=_SUPPLY
    )

    assert [(one.activation_id, one.acted) for one in entries] == [
        (_IDS[1], True),
        (_IDS[0], False),
    ]
    assert entries[0].channel == _place("c")
    assert entries[0].input == "for two"


def test_the_section_enters_what_the_task_scheduler_started_its_input_withheld() -> None:
    """§5:2-§5:3: a task's activation is its task's person's; its instruction is not shown."""
    viewer = _running("c", _IDS[1], order=2)
    task = _running(
        "schedule", _IDS[0], order=1, standing=None, text="water the plants", channel=SCHEDULE
    )
    (entry,) = in_progress([task, viewer], viewer=_IDS[1], person="person:owner", supply=_SUPPLY)
    assert entry.activation_id == _IDS[0]
    assert entry.channel == SCHEDULE
    assert entry.input is None
    assert entry.origin is InputOrigin.ASSISTANT


def test_nothing_is_entered_that_is_stopped_unwritten_or_another_persons() -> None:
    """§5:2-§5:4: its stop mark unset, its episode written, the same person's."""
    viewer = _running("c", _IDS[3], order=4)
    stopped = _running("a", _IDS[0], order=1)
    stopped.stop()
    unwritten = _running("b", _IDS[1], order=2, episode=False)
    forward = _running(
        "b",
        _IDS[2],
        order=3,
        standing=input_standing(origin=InputOrigin.OUTSIDE, established=False),
    )
    entries = in_progress(
        [viewer, stopped, unwritten, forward], viewer=_IDS[3], person="person:owner", supply=_SUPPLY
    )
    assert entries == []


def test_nothing_is_shown_to_an_author_not_established_or_where_the_audience_withholds_it() -> None:
    """§5:4-§5:5: an owner-placed episode is withheld from an unbounded audience."""
    other = _running("a", _IDS[0], order=1)
    forward = _running(
        "c",
        _IDS[1],
        order=2,
        standing=input_standing(origin=InputOrigin.OUTSIDE, established=False),
    )
    shown, more = _matters([other, forward]).in_progress(forward, supply=_SUPPLY)
    assert (shown, more) == ((), 0)
    established = _running("c", _IDS[2], order=3)
    shown, _ = _matters([other, established]).in_progress(
        established, supply=UnboundedAudienceSupply(speakable_attested_sources=frozenset())
    )
    assert shown == ()


def test_the_section_is_bounded_and_says_how_many_more_run() -> None:
    """§5:10: at most ``in_progress_limit`` entries, newest first, and the rest counted."""
    states = [_running(f"p{n}", f"{_IDS[0][:-2]}{n:02d}", order=n) for n in range(1, 9)]
    viewer = _running("v", _IDS[3], order=99)
    shown, more = _matters([*states, viewer]).in_progress(viewer, supply=_SUPPLY)
    assert len(shown) == DEFAULT_IN_PROGRESS_LIMIT
    assert more == 8 - DEFAULT_IN_PROGRESS_LIMIT
    assert shown[0].activation_id.endswith("08")


# --- §7:12, §7:15: settled ------------------------------------------------------------


def test_an_activation_is_settled_once_its_first_version_and_its_decision_are_recorded() -> None:
    state = _running("a", _IDS[0], order=1)
    assert not settled(state)
    _understood(state, _IDS[1])
    assert not settled(state), "its version names an activation, undecided"
    state.takeovers[1] = []
    assert settled(state)

    plain = _running("b", _IDS[1], order=2)
    _understood(plain)
    assert settled(plain), "a version naming nothing needs no decision"

    omitted = _running("c", _IDS[2], order=3)
    omitted.omit(UnderstandingOmission.FAILED)
    assert settled(omitted)

    stopped = _running("d", _IDS[3], order=4)
    stopped.stop()
    assert settled(stopped)


async def test_an_act_waits_for_each_newer_one_of_its_standing_and_no_other() -> None:
    """§7:12-§7:13: before it commits on any place, after only on its own; to the deadline."""
    older = _running("a", _IDS[0], order=1)
    elsewhere = _running("b", _IDS[1], order=2)
    matters = _matters([older, elsewhere])
    loop = asyncio.get_running_loop()
    assert not await matters.before_act(older, loop.time() + 0.05), "it waited to the deadline"

    older.committed = True
    assert await matters.before_act(older, loop.time() + 0.05), "elsewhere, after it acted"

    older.committed = False
    _understood(elsewhere)
    assert await matters.before_act(older, loop.time() + 0.05), "settled"


async def test_a_takeover_waits_for_each_older_ones_decision() -> None:
    """§7:15-§7:16: the older is settled once its decision is recorded."""
    older = _running("a", _IDS[0], order=1)
    newer = _running("b", _IDS[1], order=2)
    matters = _matters([older, newer])
    _understood(older, _IDS[3])
    loop = asyncio.get_running_loop()

    async def decide() -> None:
        await asyncio.sleep(0.01)
        older.takeovers[1] = []
        matters.changed()

    deciding = asyncio.ensure_future(decide())
    assert await matters.before_takeover(newer, loop.time() + 5)
    await deciding
    assert await matters.before_takeover(older, loop.time() + 0.01), "it waits on no newer one"


# --- §7:4-§7:8: the absorption, one step ----------------------------------------------


def test_the_newest_absorbs_the_older_and_brings_every_input_it_holds_naming_it() -> None:
    other = _running("a", _IDS[0], order=1)
    other.take_inputs(
        (
            JoinedInput(
                joined_at=_AT,
                channel=_place("x"),
                messages=(_said("at eight", position=2),),
                taken_over_from=_IDS[3],
            ),
        ),
        merged=(_IDS[3],),
    )
    taker = _running("b", _IDS[1], order=2, text="for two")
    matters = _matters([other, taker])

    decided, absorbed = matters.merge(taker, _understood(taker, _IDS[0]), at=_AT)

    assert absorbed == [_IDS[0]]
    assert [(one.activation_id, one.became) for one in decided] == [(_IDS[0], Became.ABSORBED)]
    assert (other.stopped, other.committed) == (True, True)
    assert other.absorbed_by == _IDS[1]
    assert [(one.taken_over_from, one.channel) for one in taker.joined] == [
        (_IDS[0], _place("a")),
        (_IDS[0], _place("x")),
    ]
    assert taker.merge_covered == 2, "the version that named it covers what it brought (§7:9)"
    assert taker.merged == (_IDS[3], _IDS[0])
    assert matters.forward(_IDS[0]) == _IDS[1]
    assert matters.absorbed_by(_IDS[0]) == _IDS[1]


def test_it_follows_forward_and_absorbs_the_absorber() -> None:
    """§7:4: the middle one absorbed the oldest, and the newest follows it forward."""
    oldest = _running("a", _IDS[0], order=1)
    middle = _running("b", _IDS[1], order=2)
    newest = _running("c", _IDS[2], order=3)
    matters = _matters([oldest, middle, newest])
    matters.merge(middle, _understood(middle, _IDS[0]), at=_AT)

    decided, absorbed = matters.merge(newest, _understood(newest, _IDS[0]), at=_AT)

    assert absorbed == [_IDS[1]]
    (named,) = decided
    assert (named.activation_id, named.reached, named.became) == (
        _IDS[0],
        _IDS[1],
        Became.ABSORBED,
    )
    assert [one.taken_over_from for one in newest.joined] == [_IDS[1], _IDS[1]]
    assert newest.merged == (_IDS[0], _IDS[1])


def test_nothing_newer_older_stopped_or_of_another_standing_is_absorbed() -> None:
    """§7:5: started before this one, running with its stop mark unset, of its standing."""
    taker = _running("c", _IDS[2], order=3)
    newer = _running("a", _IDS[3], order=4)
    stopped = _running("a", _IDS[0], order=1)
    stopped.stop()
    other = _running(
        "b",
        _IDS[1],
        order=2,
        standing=InputStanding(THE_USER, users_authority=False, origin=InputOrigin.USER),
    )
    matters = _matters([taker, newer, stopped, other])
    decided, absorbed = matters.merge(taker, _understood(taker, _IDS[3], _IDS[0], _IDS[1]), at=_AT)
    assert absorbed == []
    assert {one.became for one in decided} == {Became.NOT_TAKEN}
    assert taker.joined == ()


@pytest.mark.parametrize("limit", [1, 2])
def test_an_absorption_above_the_limit_absorbs_none(limit: int) -> None:
    """§7:6, §1:5's last case: at a limit of 1, and at one two absorptions exhaust."""
    first = _running("a", _IDS[0], order=1)
    second = _running("b", _IDS[1], order=2)
    taker = _running("c", _IDS[2], order=3)
    matters = _matters([first, second, taker], held=limit)

    decided, absorbed = matters.merge(taker, _understood(taker, _IDS[0], _IDS[1]), at=_AT)

    assert absorbed == []
    assert [one.became for one in decided] == [Became.NOT_TAKEN, Became.NOT_TAKEN]
    assert (first.stopped, second.stopped) == (False, False)


# --- §7:17-§7:22: the offer, and the wait on an older one ---------------------------


def test_one_that_has_acted_on_this_place_is_offered_this_input() -> None:
    older = _running("a", _IDS[0], order=1)
    older.committed = True
    newer = _running("a", _IDS[1], order=2, text="only two bedrooms")
    matters = _matters([older, newer])

    decided, absorbed = matters.merge(newer, _understood(newer, _IDS[0]), at=_AT)

    assert absorbed == []
    assert [one.became for one in decided] == [Became.OFFERED]
    (offer,) = older.offers.values()
    assert offer.offering == _IDS[1]
    assert offer.meaning == "reading 1"
    assert [[m.text for m in one.messages] for one in offer.inputs] == [["only two bedrooms"]]
    assert older.offers_untaken == 1
    assert newer.offered_to == _IDS[0]
    assert newer.waits_on == (_IDS[0],)


def test_one_that_has_acted_elsewhere_or_two_that_have_are_waited_on_with_no_offer() -> None:
    """§7:17-§7:18: across places no offer; and an input continuing two waits on both."""
    there = _running("a", _IDS[0], order=1)
    there.committed = True
    newer = _running("b", _IDS[1], order=2)
    matters = _matters([there, newer])
    decided, _ = matters.merge(newer, _understood(newer, _IDS[0]), at=_AT)
    assert [one.became for one in decided] == [Became.WAITED_ON]
    assert there.offers == {}
    assert newer.waits_on == (_IDS[0],)

    one = _running("c", _IDS[0], order=1)
    two = _running("c", _IDS[1], order=2)
    one.committed = two.committed = True
    both = _running("c", _IDS[2], order=3)
    matters = _matters([one, two, both])
    decided, _ = matters.merge(both, _understood(both, _IDS[0], _IDS[1]), at=_AT)
    assert [one.became for one in decided] == [Became.WAITED_ON, Became.WAITED_ON]
    assert (one.offers, two.offers) == ({}, {})
    assert both.waits_on == (_IDS[0], _IDS[1])


def test_no_offer_is_made_once_held_inputs_and_untaken_offers_reach_the_limit() -> None:
    """§7:22: each offer counts from when it is made, whether declined or withdrawn."""
    older = _running("a", _IDS[0], order=1)
    older.committed = True
    older.offers_untaken = 1
    newer = _running("a", _IDS[1], order=2)
    matters = _matters([older, newer], held=2)
    decided, _ = matters.merge(newer, _understood(newer, _IDS[0]), at=_AT)
    assert [one.became for one in decided] == [Became.WAITED_ON]
    assert older.offers == {}


def test_an_absorber_makes_the_absorbed_ones_offer_again_with_every_input_it_holds() -> None:
    """§7:24: withdrawn and made again, and the absorber waits on what the other did."""
    older = _running("a", _IDS[0], order=1)
    older.committed = True
    offering = _running("a", _IDS[1], order=2, text="two bedrooms")
    absorber = _running("a", _IDS[2], order=3, text="and a garden")
    matters = _matters([older, offering, absorber])
    matters.merge(offering, _understood(offering, _IDS[0]), at=_AT)
    first = older.offers[_IDS[1]]

    decided, absorbed = matters.merge(absorber, _understood(absorber, _IDS[1]), at=_AT)

    assert absorbed == [_IDS[1]]
    assert first.decision.became is Became.WITHDRAWN
    assert list(older.offers) == [_IDS[2]]
    again = older.offers[_IDS[2]]
    assert [[m.text for m in one.messages] for one in again.inputs] == [
        ["and a garden"],
        ["two bedrooms"],
    ]
    assert older.offers_untaken == 2, "the withdrawn one still counts (§7:22)"
    assert [one.became for one in decided] == [Became.ABSORBED, Became.OFFERED]


# --- §7:20-§7:23: the answer --------------------------------------------------------


def _offered(
    *, held: int = DEFAULT_HELD_INPUT_LIMIT
) -> tuple[Matters, ActivationState, ActivationState]:
    older = _running("a", _IDS[0], order=1)
    older.committed = True
    newer = _running("a", _IDS[1], order=2, text="only two bedrooms")
    matters = _matters([older, newer], held=held)
    matters.merge(newer, _understood(newer, _IDS[0]), at=_AT)
    return matters, older, newer


def test_a_take_hands_the_input_over_and_stops_the_offering_one() -> None:
    matters, older, newer = _offered()

    answered = matters.answer(older, _IDS[1], take=True, reason=None)

    assert answered == Answered(TakeAnswer.TAKEN, meaning="reading 1")
    assert (newer.stopped, newer.committed) == (True, True)
    assert newer.handed_to == _IDS[0]
    assert [one.taken_over_from for one in older.joined] == [_IDS[1]]
    assert older.merge_covered == 1, "the offer's meaning covers it (§7:9)"
    assert older.merged == (_IDS[1],)
    assert older.offers == {}
    assert older.offers_untaken == 0
    assert [(one.activation_id, one.became) for one in older.took] == [(_IDS[1], Became.TAKEN)]
    assert matters.forward(_IDS[1]) == _IDS[0], "a hand-over is followed forward (§7:4)"
    assert matters.absorbed_by(_IDS[1]) is None


def test_a_decline_records_its_reason_and_the_offering_one_waits() -> None:
    matters, older, newer = _offered()
    answered = matters.answer(older, _IDS[1], take=False, reason="already booked")
    assert answered == Answered(TakeAnswer.DECLINED, "already booked", meaning="reading 1"), (
        "as asked, so no reason it fell short"
    )
    assert newer.offered_to is None
    assert newer.declined == ((_IDS[0], "already booked"),)
    assert newer.waits_on == (_IDS[0],)
    assert not newer.stopped
    assert older.offers_untaken == 1


def test_a_take_above_the_limit_is_refused_as_a_decline() -> None:
    """§7:22: refused, counting as a decline, with that reason."""
    matters, older, newer = _offered(held=2)
    older.take_inputs(
        (
            JoinedInput(
                joined_at=_AT, channel=_place("a"), messages=(_said("x"),), taken_over_from=_IDS[3]
            ),
        ),
        merged=(_IDS[3],),
    )
    answered = matters.answer(older, _IDS[1], take=True, reason=None)
    assert answered.came_to is TakeAnswer.DECLINED
    assert answered.reason == "it already holds as much input as it may"
    assert answered.not_as_asked is NotAsAsked.AT_LIMIT
    assert not newer.stopped
    assert newer.declined[0][0] == _IDS[0]


def test_an_offer_whose_offering_one_no_longer_runs_is_withdrawn() -> None:
    matters, older, newer = _offered()
    newer.stop()
    answered = matters.answer(older, _IDS[1], take=True, reason=None)
    assert answered.came_to is TakeAnswer.WITHDRAWN
    assert answered.not_as_asked is NotAsAsked.STOPPED
    assert answered.meaning == "reading 1", "the input it carried is named"
    assert older.joined == ()


def _offered_in() -> tuple[list[ActivationState], Matters, ActivationState, ActivationState]:
    """As :func:`_offered`, with the list of what runs, for an activation to end."""
    older = _running("a", _IDS[0], order=1)
    older.committed = True
    newer = _running("a", _IDS[1], order=2, text="only two bedrooms")
    states = [older, newer]
    matters = _matters(states)
    matters.merge(newer, _understood(newer, _IDS[0]), at=_AT)
    return states, matters, older, newer


def test_a_withdrawal_reads_the_stop_after_the_offering_one_has_ended() -> None:
    """ADR-0352 §4:2: a stop by the control most often ends it before the answer runs."""
    states, matters, older, newer = _offered_in()
    newer.stop()
    states.remove(newer)  # it ends
    answered = matters.answer(older, _IDS[1], take=True, reason=None)
    assert (answered.came_to, answered.not_as_asked) == (
        TakeAnswer.WITHDRAWN,
        NotAsAsked.STOPPED,
    )


def test_a_withdrawal_whose_offering_one_ended_unstopped_says_it_ended() -> None:
    states, matters, older, newer = _offered_in()
    states.remove(newer)  # it ends, unstopped
    answered = matters.answer(older, _IDS[1], take=False, reason="not this work's")
    assert (answered.came_to, answered.not_as_asked) == (
        TakeAnswer.WITHDRAWN,
        NotAsAsked.ENDED,
    )


def test_an_answer_naming_no_open_offer_is_refused() -> None:
    matters, older, _ = _offered()
    assert matters.answer(older, _IDS[2], take=True, reason=None) == Answered(
        TakeAnswer.NO_OFFER, not_as_asked=NotAsAsked.NO_OFFER
    )


def test_an_older_that_ends_without_answering_has_declined() -> None:
    """§7:24: an older that ends, or is stopped, without answering has declined it."""
    matters, older, newer = _offered()
    matters.ended(older)
    assert newer.offered_to is None
    assert newer.declined[0][0] == _IDS[0]
    assert older.offers == {}


# --- §7:14: the commitment step ---------------------------------------------------


def test_the_commitment_step_commits_and_runs_nothing_once_stopped() -> None:
    state = _running("a", _IDS[0], order=1)
    assert state.commit() is Commitment.COMMITTED
    assert state.committed
    stopped = _running("b", _IDS[1], order=2)
    stopped.stop()
    assert stopped.commit() is Commitment.STOPPED
    assert not stopped.committed


def test_inputs_held_count_toward_the_limit() -> None:
    state = _running("a", _IDS[0], order=1)
    assert state.inputs_held == 1
    state.take_inputs(
        (
            JoinedInput(
                joined_at=_AT, channel=_place("a"), messages=(_said("x"),), taken_over_from=_IDS[1]
            ),
        ),
        merged=(_IDS[1],),
    )
    assert state.inputs_held == 2


# --- §7:4, §7:13, §7:17: following forward, and what a wait waits for -------------------


def test_an_offer_follows_forward_to_the_absorber_that_has_acted() -> None:
    """§7:4, §1:5's case: the absorbed one leads to its absorber, which is offered."""
    oldest = _running("a", _IDS[0], order=1)
    absorber = _running("a", _IDS[1], order=2)
    newest = _running("a", _IDS[2], order=3, text="and a garden")
    matters = _matters([oldest, absorber, newest])
    matters.merge(absorber, _understood(absorber, _IDS[0]), at=_AT)
    absorber.committed = True

    decided, absorbed = matters.merge(newest, _understood(newest, _IDS[0]), at=_AT)

    assert absorbed == []
    (named,) = decided
    assert (named.reached, named.became) == (_IDS[1], Became.OFFERED)
    assert list(absorber.offers) == [_IDS[2]]


def test_a_newer_input_follows_a_hand_over_to_the_activation_that_took_it() -> None:
    """§7:4, §1:5's case: a hand-over is followed forward as an absorption is."""
    older = _running("a", _IDS[0], order=1)
    older.committed = True
    offering = _running("a", _IDS[1], order=2)
    states = [older, offering]
    matters = _matters(states)
    matters.merge(offering, _understood(offering, _IDS[0]), at=_AT)
    matters.answer(older, _IDS[1], take=True, reason=None)
    later = _running("a", _IDS[2], order=3)
    states.append(later)

    decided, _ = matters.merge(later, _understood(later, _IDS[1]), at=_AT)

    (named,) = decided
    assert named.reached == _IDS[0], "it reached the activation that took the input"
    assert named.became is Became.OFFERED


async def test_an_input_arriving_during_an_acts_wait_is_not_waited_for() -> None:
    """§7:12, §1:5's case: what an act waits for is what runs when the wait begins."""
    older = _running("a", _IDS[0], order=1)
    newer = _running("b", _IDS[1], order=2)
    states = [older, newer]
    matters = _matters(states)
    waiting = asyncio.ensure_future(
        matters.before_act(older, asyncio.get_running_loop().time() + 5)
    )
    await asyncio.sleep(0.01)
    later = _running("c", _IDS[2], order=3)
    states.append(later)
    _understood(newer)
    matters.changed()
    assert await asyncio.wait_for(waiting, 1), "it ended once the newer one settled"
    assert not settled(later)


def test_re_plans_for_offers_stop_once_the_limit_is_reached() -> None:
    """§7:22, §1:5's case: each offer counts from when it is made, so they run out."""
    older = _running("a", _IDS[0], order=1)
    older.committed = True
    states = [older]
    matters = _matters(states, held=3)
    made = []
    for n, activation_id in enumerate(_IDS[1:], start=2):
        newer = _running("a", activation_id, order=n)
        states.append(newer)
        decided, _ = matters.merge(newer, _understood(newer, _IDS[0]), at=_AT)
        made.append(decided[0].became)
        older.offers.clear()  # each declined, or withdrawn, at once
    assert made == [Became.OFFERED, Became.OFFERED, Became.WAITED_ON]
    assert older.offers_untaken == 2


def test_a_stopped_activation_takes_nothing_in_and_offers_nothing() -> None:
    """ADR-0295 §2:1: stopped after its takeover wait began, its step does nothing."""
    older = _running("a", _IDS[0], order=1)
    acted = _running("a", _IDS[1], order=2)
    acted.committed = True
    taker = _running("a", _IDS[2], order=3)
    matters = _matters([older, acted, taker])
    taker.stop()

    decided, absorbed = matters.merge(taker, _understood(taker, _IDS[0], _IDS[1]), at=_AT)

    assert absorbed == []
    assert [one.became for one in decided] == [Became.NOT_TAKEN, Became.NOT_TAKEN]
    assert not older.stopped
    assert acted.offers == {}
    assert taker.joined == ()


def test_an_absorber_keeps_what_the_absorbed_one_waited_on_once_it_has_ended() -> None:
    """§7:24, §7:27: an ended wait target is not waited for, but its work is still shown."""
    ended = _running("x", _IDS[0], order=1)
    ended.committed = True
    waiter = _running("a", _IDS[1], order=2)
    states = [ended, waiter]
    matters = _matters(states)
    matters.merge(waiter, _understood(waiter, _IDS[0]), at=_AT)
    assert waiter.waits_on == (_IDS[0],)
    states.remove(ended)  # it ends
    absorber = _running("b", _IDS[2], order=3)
    states.append(absorber)

    matters.merge(absorber, _understood(absorber, _IDS[1]), at=_AT)

    assert absorber.waits_on == (_IDS[0],)
    assert matters.waiting_on(absorber) == (), "nothing to wait for: it has ended"


def test_absorbing_one_whose_offer_was_declined_waits_with_no_new_offer() -> None:
    """§7:24: only an open offer is made again; a declined one stays a wait."""
    older = _running("a", _IDS[0], order=1)
    older.committed = True
    offering = _running("a", _IDS[1], order=2)
    states = [older, offering]
    matters = _matters(states)
    matters.merge(offering, _understood(offering, _IDS[0]), at=_AT)
    matters.answer(older, _IDS[1], take=False, reason="already booked")
    absorber = _running("a", _IDS[2], order=3)
    states.append(absorber)

    decided, absorbed = matters.merge(absorber, _understood(absorber, _IDS[1]), at=_AT)

    assert absorbed == [_IDS[1]]
    assert [one.became for one in decided] == [Became.ABSORBED, Became.WAITED_ON]
    assert older.offers == {}, "no offer is made to it again"
    assert absorber.waits_on == (_IDS[0],)
    assert older.offers_untaken == 1


async def test_an_act_waits_for_a_newer_one_whose_pass_has_not_set_its_standing() -> None:
    """§7:12: admitted on a place that establishes its author, it may be of this standing,
    so it is waited for until its standing shows it is not, or it settles."""
    older = _running("a", _IDS[0], order=1)
    newer = _running("b", _IDS[1], order=2, standing=None)
    matters = _matters([older, newer])
    loop = asyncio.get_running_loop()
    assert not await matters.before_act(older, loop.time() + 0.05), "it waited to the deadline"

    waiting = asyncio.ensure_future(matters.before_act(older, loop.time() + 5))
    await asyncio.sleep(0.01)
    newer.standing = input_standing(origin=InputOrigin.OUTSIDE, established=False)
    matters.changed()
    assert await asyncio.wait_for(waiting, 1), "a forward's standing is not this one's"


# --- §7:12, §8:2: what the readers hold in their start waits ----------------------------


async def test_an_act_waits_for_an_input_a_reader_holds_in_its_start_wait() -> None:
    """§7:12, §1:5's case: before it commits, one held on any of its person's places;
    after, only one held on its own place; each until it is let go."""
    older = _running("a", _IDS[0], order=1)
    matters = _matters([older])
    loop = asyncio.get_running_loop()
    elsewhere = matters.hold(_place("b"))
    assert not await matters.before_act(older, loop.time() + 0.05), "it waited to the deadline"

    older.committed = True
    assert await matters.before_act(older, loop.time() + 0.05), "elsewhere, after it acted"
    here = matters.hold(_place("a"))
    assert not await matters.before_act(older, loop.time() + 0.05), "its own place, after"

    waiting = asyncio.ensure_future(matters.before_act(older, loop.time() + 5))
    await asyncio.sleep(0.01)
    assert not waiting.done()
    here.release()
    assert await asyncio.wait_for(waiting, 1), "let go: nothing was taken in"
    elsewhere.release()


async def test_a_held_input_once_admitted_is_waited_for_until_its_activation_settles() -> None:
    """§7:12: "each held input's activation once admitted", until it settles (§7:12)."""
    older = _running("a", _IDS[0], order=1)
    states = [older]
    matters = _matters(states)
    held = matters.hold(_place("a"))
    waiting = asyncio.ensure_future(
        matters.before_act(older, asyncio.get_running_loop().time() + 5)
    )
    await asyncio.sleep(0.01)
    held.admitted(_IDS[1])
    await asyncio.sleep(0.01)
    assert not waiting.done(), "admitted, its activation not yet running"

    newer = _running("a", _IDS[1], order=2)
    states.append(newer)
    matters.changed()
    await asyncio.sleep(0.01)
    assert not waiting.done(), "running, its understanding not yet recorded"
    _understood(newer)
    matters.changed()
    assert await asyncio.wait_for(waiting, 1), "settled"
    assert not held.released, "held until its activation ends, which the reader says"


async def test_what_is_held_once_an_acts_wait_has_begun_is_not_waited_for() -> None:
    """§7:12: what it waits for is what is held when the wait begins."""
    older = _running("a", _IDS[0], order=1)
    newer = _running("a", _IDS[1], order=2)
    matters = _matters([older, newer])
    waiting = asyncio.ensure_future(
        matters.before_act(older, asyncio.get_running_loop().time() + 5)
    )
    await asyncio.sleep(0.01)
    later = matters.hold(_place("a"))
    _understood(newer)
    matters.changed()
    assert await asyncio.wait_for(waiting, 1), "it ended once the newer one settled"
    assert not later.released


async def test_no_act_waits_on_its_own_input_an_older_ones_or_one_no_person_wrote() -> None:
    """§7:12: only a newer input of its person could absorb it or offer to it (§7:5)."""
    earlier = _running("a", _IDS[1], order=1)
    older = _running("a", _IDS[0], order=2)
    matters = _matters([earlier, older])
    _understood(earlier)
    own = matters.hold(_place("a"))
    own.admitted(_IDS[0])
    before = matters.hold(_place("a"))
    before.admitted(_IDS[1])
    matters.hold(ChannelIdentity(channel_type="upcoming_event", instance_id="e-1"))
    loop = asyncio.get_running_loop()
    assert await matters.before_act(older, loop.time() + 0.05), "none of them is waited for"

    forward = _running(
        "b",
        _IDS[2],
        order=3,
        standing=input_standing(origin=InputOrigin.OUTSIDE, established=False),
    )
    matters.hold(_place("b"))
    assert await matters.before_act(forward, loop.time() + 0.05), (
        "an input whose author is not established meets none, so it waits for none"
    )
