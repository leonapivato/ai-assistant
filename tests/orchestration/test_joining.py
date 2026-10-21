"""Joining a running activation and taking one over, over constructed states (ADR-0332).

The engine drives these through whole passes in ``test_phases_joining``. Here each rule
is held apart: who may join (§3:3), what is a pure read (ADR-0341 §2), the one-step join
and commitment (§3:5, §3:6), what another place is shown (§4:1-§4:3) and the takeover's
one step (§4:6).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from test_engine import tool
from test_engine_phases import _BOOK

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConversationStoreError
from ai_assistant.core.types import (
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
from ai_assistant.orchestration.joining import (
    DEFAULT_JOIN_LIMIT,
    THE_USER,
    InputStanding,
    JoinCheck,
    JoiningInput,
    input_standing,
    is_pure_read,
    join_running,
    reserve_join,
    settle,
    take_over,
    visible_running,
)
from ai_assistant.orchestration.lookups import LOOK_UPS, READ_STORY, SEARCH_MEMORY
from ai_assistant.orchestration.remembering import REMEMBER
from ai_assistant.orchestration.story_calls import STORY_CALLS
from ai_assistant.tools.web_search import WEB_SEARCH

_AT: Final = datetime(2026, 10, 21, 9, tzinfo=UTC)
_IDS: Final = (
    "0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11",
    "1c9a9f1f-3b6d-4d66-8b7d-7b3d2a1c1e22",
    "2dab0a2a-4c7e-4e77-9c8e-8c4e3b2d2f33",
)
_USERS: Final = input_standing(origin=InputOrigin.USER, established=True)


def _place(name: str) -> ChannelIdentity:
    return ChannelIdentity(channel_type="conversation", instance_id=name)


def _said(text: str, *, at: datetime = _AT, position: int | None = 1) -> RecordedInputMessage:
    return RecordedInputMessage(text=text, sent_at=at, position=position)


def _running(  # noqa: PLR0913 — the place, the id, and one knob per fact a case varies
    place: str,
    activation_id: str = _IDS[0],
    *,
    standing: InputStanding | None = _USERS,
    text: str = "book Riverside",
    started: datetime = _AT,
    episode: bool = True,
) -> ActivationState:
    """An admitted activation on ``place`` whose pass has begun, its episode written."""
    state = admit_channel(
        ChannelInput(target=_place(place), payload=TextChannelPayload(text=text)),
        WholeTextReply(),
        clock=lambda: started,
        id_factory=lambda: activation_id,
    )
    state.standing = standing
    state.input_messages = (_said(text, at=started),)
    if episode:
        state.capture = EpisodeProgress(
            address=f"activation:{activation_id}",
            captured_at=started,
            written=EpisodicMemory(
                id=f"activation:{activation_id}",
                content="",
                occurred_at=started,
                provenance=Provenance(
                    source=MemorySource.OBSERVED, confidence=0.9, last_updated=started
                ),
                processing_record=state.open_processing(),
                placement=Placement(
                    reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=started
                ),
            ),
        )
    return state


def _joining(
    place: str,
    text: str = "make it Saturday",
    *,
    author: str | None = THE_USER,
    origin: InputOrigin = InputOrigin.USER,
) -> JoiningInput:
    return JoiningInput(
        channel=_place(place),
        messages=(_said(text, position=2),),
        standing=InputStanding(author=author, users_authority=author is not None, origin=origin),
    )


def _joined(text: str = "make it Saturday") -> JoinedInput:
    return JoinedInput(joined_at=_AT, channel=_place("a"), messages=(_said(text, position=2),))


def _marked(state: ActivationState) -> bool:
    """The committed mark, read afresh."""
    return state.committed


def _version(version: int) -> ActivationUnderstanding:
    return ActivationUnderstanding(
        version=version,
        recorded_at=_AT,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning=f"reading {version}",
        meaning_ground=UnderstandingGround.STATED,
    )


# --- §6:5: the limit ---------------------------------------------------------------


def test_the_default_limit_is_the_settings_own() -> None:
    """An engine built without the composition root's value takes the setting's default."""
    assert Settings.model_fields["join_limit"].default == DEFAULT_JOIN_LIMIT


# --- §3:3: who may join ------------------------------------------------------------


def test_only_the_same_established_author_with_the_same_authority_and_origin_joins() -> None:
    assert _USERS.joins(_USERS)
    forward = input_standing(origin=InputOrigin.OUTSIDE, established=False)
    assert forward.author is None
    assert not forward.users_authority
    # A forward never joins a user's activation, and a user's message never joins one a
    # forward started (§3:3's note).
    assert not forward.joins(_USERS)
    assert not _USERS.joins(forward)
    assert not forward.joins(forward)
    assert not _USERS.joins(InputStanding(THE_USER, users_authority=False, origin=InputOrigin.USER))
    assert not _USERS.joins(
        InputStanding(THE_USER, users_authority=True, origin=InputOrigin.OUTSIDE)
    )
    assert not _USERS.joins(
        InputStanding("someone else", users_authority=True, origin=InputOrigin.USER)
    )


def test_an_input_that_joins_carries_a_message() -> None:
    with pytest.raises(ValueError, match="at least one message"):
        JoiningInput(channel=_place("a"), messages=(), standing=_USERS)


# --- ADR-0341 §2: the pure read ------------------------------------------------------


@pytest.mark.parametrize("declared", LOOK_UPS, ids=lambda one: str(one.capability))
def test_each_look_up_is_a_pure_read(declared: ToolDefinition) -> None:
    """§2:1: a look-up writes nothing, declares the own records and stays in the hub."""
    assert declared.writes == ()
    assert declared.effect is CapabilityEffect.OWN_RECORDS
    assert not declared.leaves_hub
    assert is_pure_read(declared)


@pytest.mark.parametrize(
    "declared",
    [*STORY_CALLS, REMEMBER, WEB_SEARCH, _BOOK],
    ids=lambda one: str(one.capability),
)
def test_a_story_write_remember_the_web_search_and_a_call_in_the_world_are_not(
    declared: ToolDefinition,
) -> None:
    """§2:1: a write to the hub's own records, a call that leaves the hub, the world."""
    assert not is_pure_read(declared)


def test_a_call_that_changes_nothing_and_stays_in_the_hub_is_still_a_pure_read() -> None:
    """§2:1 keeps what ADR-0332 §3:1 counted: effect none, no writes, does not leave."""
    declared = tool().model_copy(update={"effect": CapabilityEffect.NONE, "leaves_hub": False})
    assert is_pure_read(declared)


def _renamed(declared: ToolDefinition, name: str, **update: object) -> ToolDefinition:
    """``declared`` under another id and capability, validated as a declaration."""
    return ToolDefinition.model_validate(
        {**declared.model_dump(), "id": name, "capability": name, **update}
    )


def test_the_look_ups_properties_under_another_name_are_a_pure_read() -> None:
    """§2:2: the declaration decides, never the call's or its capability's name."""
    assert is_pure_read(_renamed(SEARCH_MEMORY, "opening_hours"))


def test_a_write_under_a_look_ups_name_is_not_a_pure_read() -> None:
    """§2:2: a name admits nothing; a write the declaration names commits."""
    assert not is_pure_read(
        _renamed(READ_STORY, str(READ_STORY.capability), writes=(DataTier.PERSONAL,))
    )
    assert not is_pure_read(_renamed(SEARCH_MEMORY, str(SEARCH_MEMORY.capability), leaves_hub=True))


# --- §3:6: the join, one step ------------------------------------------------------


def test_a_join_is_taken_until_the_activation_commits_stops_ends_or_reaches_the_limit() -> None:
    state = _running("a")
    assert state.join(_joined(), limit=3)
    assert state.joined == (_joined(),)
    assert state.inputs_held == 2

    committed = _running("a")
    committed.committed = True
    assert not committed.join(_joined(), limit=3)

    stopped = _running("a")
    assert stopped.stop()
    assert not stopped.join(_joined(), limit=3)

    ended = _running("a")
    ended.processing(_AT, None)
    assert not ended.join(_joined(), limit=3)

    # §6:5: 0 turns joining off, and a limit reached takes no more.
    assert not _running("a").join(_joined(), limit=0)
    full = _running("a")
    assert full.join(_joined("one"), limit=1)
    assert not full.join(_joined("two"), limit=1)
    assert [one.messages[0].text for one in full.joined] == ["one"]


def test_the_episode_records_each_joined_input_in_order() -> None:
    """§3:16: on the open record as the pass stands, and on the frozen one."""
    state = _running("a")
    state.join(_joined("one"), limit=3)
    state.join(_joined("two"), limit=3)
    assert [one.messages[0].text for one in state.open_processing().joined] == ["one", "two"]
    assert state.processing(_AT, None).joined == state.joined


# --- §3:5-§3:7: the commitment step -----------------------------------------------


def test_the_commitment_step_sets_aside_a_round_planned_before_a_join() -> None:
    state = _running("a")
    state.understood(_version(1), limit=8, inputs=1)
    assert state.join(_joined(), limit=3)

    assert state.commit(1) is Commitment.SET_ASIDE
    assert not _marked(state)
    # The input still joins: nothing committed.
    assert state.join(_joined("and for four"), limit=3)

    state.understood(_version(2), limit=8, inputs=state.inputs_held)
    assert state.covers(2) == 3
    assert state.commit(2) is Commitment.COMMITTED
    assert _marked(state)
    # §3:6: once committed, no join is taken.
    assert not state.join(_joined("too late"), limit=3)
    assert state.commit(2) is Commitment.COMMITTED


def test_the_commitment_step_commits_where_nothing_joined_and_runs_nothing_once_stopped() -> None:
    state = _running("a")
    state.understood(_version(1), limit=8, inputs=1)
    assert state.commit(1) is Commitment.COMMITTED

    stopped = _running("a")
    stopped.understood(_version(1), limit=8, inputs=1)
    stopped.stop()
    assert stopped.commit(1) is Commitment.STOPPED
    assert not stopped.committed

    # A round planned with no recorded version covers the trigger alone.
    unversioned = _running("a")
    assert unversioned.commit(None) is Commitment.COMMITTED


# --- the join's entry point --------------------------------------------------------


def test_the_entry_point_joins_the_activation_running_on_the_inputs_place() -> None:
    here = _running("a", _IDS[0])
    there = _running("b", _IDS[1])

    assert join_running([here, there], _joining("a"), limit=3, at=_AT) == _IDS[0]
    (joined,) = here.joined
    assert joined.channel == _place("a")
    assert joined.joined_at == _AT
    assert joined.taken_over_from is None
    assert there.joined == ()


def test_the_entry_point_joins_nothing_it_may_not() -> None:
    # Nothing running on the place: the input starts the next activation there (§2:4).
    assert join_running([_running("b")], _joining("a"), limit=3, at=_AT) is None
    # Another author, authority or origin (§3:3).
    assert join_running([_running("a")], _joining("a", author=None), limit=3, at=_AT) is None
    assert (
        join_running([_running("a")], _joining("a", origin=InputOrigin.OUTSIDE), limit=3, at=_AT)
        is None
    )
    # A running activation whose standing is not established yet takes nothing.
    assert join_running([_running("a", standing=None)], _joining("a"), limit=3, at=_AT) is None
    # More than one running on a place that runs one at a time: none, failing closed.
    two = [_running("a", _IDS[0]), _running("a", _IDS[1])]
    assert join_running(two, _joining("a"), limit=3, at=_AT) is None
    # The limit (§6:5).
    assert join_running([_running("a")], _joining("a"), limit=0, at=_AT) is None


def test_a_message_after_a_stop_joins_nothing() -> None:
    """§3:3's note, the activation's half of §1:4's first case: it waits instead."""
    state = _running("a")
    assert state.stop()
    assert join_running([state], _joining("a"), limit=3, at=_AT) is None
    assert state.joined == ()


# --- §4:1-§4:3: what another place is shown ---------------------------------------


def test_the_same_persons_running_work_on_other_places_is_shown_oldest_first() -> None:
    viewer = _running("c", _IDS[2], started=_AT + timedelta(seconds=9))
    later = _running("b", _IDS[1], text="for two", started=_AT + timedelta(seconds=5))
    earlier = _running("a", _IDS[0], started=_AT)
    later.committed = True

    shown = visible_running(
        [viewer, later, earlier],
        viewer,
        supply=BoundedAudienceSupply(speakable_attested_sources=frozenset()),
    )

    assert [(one.activation_id, one.committed) for one in shown] == [
        (_IDS[0], False),
        (_IDS[1], True),
    ]
    assert shown[0].place == _place("a")
    assert [one.text for one in shown[0].messages] == ["book Riverside"]


def test_nothing_is_shown_that_is_not_the_same_persons_running_work_on_another_place() -> None:
    viewer = _running("c", _IDS[2])
    same_place = _running("c", _IDS[1])
    stopped = _running("a", _IDS[0])
    stopped.stop()
    other_person = _running(
        "b", _IDS[1], standing=InputStanding("someone else", True, InputOrigin.USER)
    )
    unwritten = _running("b", _IDS[1], episode=False)
    forward = _running(
        "b", _IDS[1], standing=input_standing(origin=InputOrigin.OUTSIDE, established=False)
    )

    for one in (same_place, stopped, other_person, unwritten, forward):
        assert (
            visible_running(
                [viewer, one],
                viewer,
                supply=BoundedAudienceSupply(speakable_attested_sources=frozenset()),
            )
            == ()
        )


def test_nothing_is_shown_to_an_author_not_established_or_where_the_audience_withholds_it() -> None:
    """§4:3, and §4:2's audience: an owner-placed episode is withheld from an unbounded one."""
    other = _running("a")
    viewer = _running(
        "c", _IDS[2], standing=input_standing(origin=InputOrigin.OUTSIDE, established=False)
    )
    assert (
        visible_running(
            [other, viewer],
            viewer,
            supply=BoundedAudienceSupply(speakable_attested_sources=frozenset()),
        )
        == ()
    )

    established = _running("c", _IDS[2])
    assert (
        visible_running(
            [other, established],
            established,
            supply=UnboundedAudienceSupply(speakable_attested_sources=frozenset()),
        )
        == ()
    )


# --- §4:6: the takeover, one step --------------------------------------------------


def test_a_takeover_stops_the_other_and_brings_its_whole_input_naming_it() -> None:
    other = _running("a", _IDS[0])
    assert other.join(
        JoinedInput(joined_at=_AT, channel=_place("a"), messages=(_said("at eight", position=2),)),
        limit=3,
    )
    taker = _running("b", _IDS[1], text="for two")

    assert take_over([other, taker], taker, _IDS[0], limit=3, at=_AT)

    assert other.stopped
    assert other.committed
    (joined,) = taker.joined
    assert joined.taken_over_from == _IDS[0]
    assert joined.channel == _place("a")
    assert [one.text for one in joined.messages] == ["book Riverside", "at eight"]
    # The episode validates it: no takeover of itself, none twice.
    assert taker.processing(_AT, None).joined == (joined,)


@pytest.mark.parametrize("limit", [0, 1], ids=["off", "exhausted"])
def test_a_takeover_is_refused_at_the_limit_and_nothing_is_stopped(limit: int) -> None:
    other = _running("a", _IDS[0])
    taker = _running("b", _IDS[1])
    if limit:
        assert taker.join(_joined(), limit=limit)

    assert not take_over([other, taker], taker, _IDS[0], limit=limit, at=_AT)

    assert not other.stopped
    assert not other.committed
    assert len(taker.joined) == limit


def test_a_takeover_is_refused_where_the_other_has_acted_stopped_ended_or_differs() -> None:
    """§4:8: nothing is stopped or taken; this activation goes on."""
    taker = _running("b", _IDS[1])
    committed = _running("a", _IDS[0])
    committed.committed = True
    stopped = _running("a", _IDS[0])
    stopped.stop()
    ended = _running("a", _IDS[0])
    ended.processing(_AT, None)
    differs = _running("a", _IDS[0], standing=InputStanding(THE_USER, False, InputOrigin.USER))

    for other in (committed, stopped, ended, differs):
        assert not take_over([other, taker], taker, _IDS[0], limit=3, at=_AT)
        assert taker.joined == ()
    # An activation unknown, or the taker itself, is not taken either.
    assert not take_over([taker], taker, _IDS[0], limit=3, at=_AT)
    assert not take_over([taker], taker, _IDS[1], limit=3, at=_AT)
    # A taker that has committed takes no join, so it takes nothing over.
    acted = _running("b", _IDS[1])
    acted.committed = True
    fresh = _running("a", _IDS[0])
    assert not take_over([fresh, acted], acted, _IDS[0], limit=3, at=_AT)
    assert not fresh.stopped


# --- §3:6, §3:18: a join taken pending its reader's marking ----------------------------


def test_a_pending_join_is_no_input_until_confirmed_and_counts_toward_the_limit() -> None:
    """Taken in one step with its check; read by nothing until its marking lands."""
    state = _running("a")
    found, pending = reserve_join([state], _joining("a"), limit=1, at=_AT)

    assert found is JoinCheck.JOINABLE
    assert pending is not None
    assert pending.activation_id == _IDS[0]
    assert _joined_now(state) == ()
    assert state.inputs_held == 1, "no stage reads it yet"
    assert _joining_now(state)
    assert reserve_join([state], _joining("a"), limit=1, at=_AT) == (JoinCheck.REFUSED, None)

    pending.confirm([2])
    assert not _joining_now(state)
    (joined,) = _joined_now(state)
    assert [one.text for one in joined.messages] == ["make it Saturday"]


def test_a_pending_join_confirmed_with_nothing_marked_joins_nothing() -> None:
    state = _running("a")
    _, pending = reserve_join([state], _joining("a"), limit=3, at=_AT)
    assert pending is not None
    pending.confirm([])
    assert state.joined == ()
    assert not _joining_now(state)

    _, again = reserve_join([state], _joining("a"), limit=3, at=_AT)
    assert again is not None
    again.withdraw()
    assert state.joined == ()
    assert not _joining_now(state)


async def test_acting_waits_while_a_join_is_pending_and_not_once_it_settles() -> None:
    """§3:18: the commitment step's wait; it returns at once where nothing is pending."""
    state = _running("a")
    await state.settled()
    _, pending = reserve_join([state], _joining("a"), limit=3, at=_AT)
    assert pending is not None
    waiting = asyncio.ensure_future(state.settled())
    await asyncio.sleep(0)
    assert not waiting.done()

    pending.confirm([2])
    await asyncio.wait_for(waiting, 1)
    assert state.commit(1) is Commitment.SET_ASIDE, "the join it waited for is found"


def test_a_join_before_the_pass_begins_is_not_yet_and_one_stopped_is_refused() -> None:
    """§3:3: a standing not yet set is asked again; a stop before the pass refuses."""
    early = _running("a", standing=None)
    assert reserve_join([early], _joining("a"), limit=3, at=_AT) == (JoinCheck.NOT_YET, None)
    early.stop()
    assert reserve_join([early], _joining("a"), limit=3, at=_AT) == (JoinCheck.REFUSED, None)
    assert reserve_join([], _joining("a"), limit=3, at=_AT) == (JoinCheck.REFUSED, None)


def test_a_pending_join_is_no_condition_of_a_takeover() -> None:
    """§4:6's conditions are exhaustive: the engine waits for the marking, and never refuses.

    The engine's takeover stage waits for the other's join to settle before this step
    (``Engine._takeover_settled``); the step itself reads only §4:6's conditions.
    """
    other = _running("a", _IDS[0])
    _, pending = reserve_join([other], _joining("a"), limit=3, at=_AT)
    assert pending is not None
    taker = _running("b", _IDS[1])

    assert take_over([other, taker], taker, _IDS[0], limit=3, at=_AT)
    assert other.stopped


async def test_a_marking_is_written_to_its_end_through_a_cancellation() -> None:
    """§3:18: the join is confirmed with what the store marked, then the cancellation goes on."""
    state = _running("a")
    _, pending = reserve_join([state], _joining("a"), limit=3, at=_AT)
    assert pending is not None
    release = asyncio.Event()
    marked: list[int] = []

    async def marking() -> None:
        await release.wait()
        marked.append(2)

    settling = asyncio.ensure_future(settle(pending, marking(), lambda: marked))
    await asyncio.sleep(0)
    settling.cancel()
    await asyncio.sleep(0)
    assert not settling.done(), "the marking under way is not cut off"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await settling
    (joined,) = _joined_now(state)
    assert [one.position for one in joined.messages] == [2]
    assert not _joining_now(state)


async def test_a_marking_that_fails_confirms_nothing_and_raises() -> None:
    state = _running("a")
    _, pending = reserve_join([state], _joining("a"), limit=3, at=_AT)
    assert pending is not None

    async def marking() -> None:
        msg = "the store refuses the marking"
        raise ConversationStoreError(msg)

    with pytest.raises(ConversationStoreError):
        await settle(pending, marking(), list)
    assert _joined_now(state) == ()
    assert not _joining_now(state)


async def test_the_freezes_wait_holds_a_cancellation_until_the_join_settles() -> None:
    """§3:16: a cancellation during the freeze's wait is returned, once nothing is pending."""
    state = _running("a")
    assert await state.settled_through() is None
    _, pending = reserve_join([state], _joining("a"), limit=3, at=_AT)
    assert pending is not None
    waiting = asyncio.ensure_future(state.settled_through())
    await asyncio.sleep(0)
    waiting.cancel()
    await asyncio.sleep(0)
    assert not waiting.done()

    pending.confirm([2])
    held = await asyncio.wait_for(waiting, 1)
    assert isinstance(held, asyncio.CancelledError)
    assert len(_joined_now(state)) == 1


def _joining_now(state: ActivationState) -> bool:
    """Whether a join is pending its marking, read afresh."""
    return state.joining


def _joined_now(state: ActivationState) -> tuple[JoinedInput, ...]:
    """The inputs that joined, read afresh."""
    return state.joined
