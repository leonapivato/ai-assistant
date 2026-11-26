"""A work's pass carries its sight, and recall and the windows read through it (ADR-0383).

Milestone 22's B8a: the sight is made from the work's recorded facts and every sender of
every input it holds when its facts are first recorded, and made again, never wider, each
time an input joins (§6:4 to §6:6); recall's two runs and the episode windows read the
stores :class:`~ai_assistant.orchestration.bound_stores.BoundStores` binds to it, and
nothing else (§7:7, §9:1). With stores built to withhold, the reads answer by §6's table;
in the counting build they answer as before and each writes its count (§11:1).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Final

import pytest
from phases_support import chat_turn
from story_support import AT, activation, address, episode
from structlog.testing import capture_logs
from understanding_support import FAKE_RECALL_THRESHOLD, RECALL_BUDGET, RECALL_LIMIT

import ai_assistant.orchestration.work_facts as work_facts_module
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ChannelIdentity,
    ChannelInput,
    InputSender,
    JoinedInput,
    MemoryWrite,
    MemoryWriteMode,
    NewConversation,
    RecordedInputMessage,
    RecordHome,
    Sight,
    SightBound,
    SightMode,
    SightReader,
    StoryActor,
    Sureness,
    TextChannelPayload,
    WholeTextReply,
)
from ai_assistant.orchestration.activation_state import (
    CURRENT_ACTIVATION,
    ActivationScope,
    ActivationState,
    admit_channel,
    work_sight,
)
from ai_assistant.orchestration.bound_stores import BoundStores
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.recall import Recalled, RecallStage
from ai_assistant.orchestration.understanding import (
    RecentEpisodes,
    TranscriptWindow,
    Windows,
    WindowsStage,
)
from ai_assistant.testing import FakeMemoryStore, FakeStoryStore
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from collections.abc import Iterator, MutableMapping, Sequence

    from ai_assistant.core.types import MemoryRecord

_ID: Final = "60f3c223-6a54-4b06-aab8-4fc397c3d43b"
_CONVERSATION: Final = ChannelIdentity(channel_type="conversation", instance_id="c-1")
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="conn-1:4242")
_BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())

_OWNER: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)
_OWNER_WEAK: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.WEAK)
_UNIDENTIFIED: Final = InputSender(person=None, level=Sureness.NONE)

#: The words every record a case means recall to keep holds, so the fake scores it 1.0.
_CUE: Final = "canoe booked Sunday"
_TEXT: Final = "The canoe is booked for Sunday."
#: The owner's memory and an episode of an earlier work of theirs, in the owner's domain.
_FACT: Final = memory("fact-canoe", _TEXT, said_support(when=AT, added_at=AT))
_EARLIER: Final = episode("a-earlier", text=_TEXT)


def _admitted(*senders: InputSender, id_factory: str = _ID) -> ActivationState:
    """A hub chat message from ``senders``, admitted as the chat's reader admits one."""
    return admit_channel(
        ChannelInput(target=NewConversation(), payload=TextChannelPayload(text=_CUE)),
        WholeTextReply(),
        clock=lambda: AT,
        id_factory=lambda: id_factory,
        senders=senders,
    )


def _joining(sender: InputSender) -> JoinedInput:
    """An input from ``sender`` on the line, as a merge brings one in."""
    line = admit_channel(
        ChannelInput(target=_LINE, payload=TextChannelPayload(text="and Saturday")),
        WholeTextReply(),
        clock=lambda: AT,
        id_factory=lambda: _ID,
        messages=(RecordedInputMessage(text="and Saturday", sent_at=AT, sender=sender),),
    )
    return JoinedInput(joined_at=AT, channel=_LINE, messages=line.trigger.messages)


def _sight(state: ActivationState) -> Sight:
    sight = state.sight
    assert sight is not None
    return sight


class _Reads:
    """Recall and the windows over one memory store and one story store, both built to
    ``mode``, through the one holder, as the composition root wires them."""

    def __init__(self, mode: SightMode) -> None:
        self.memory = FakeMemoryStore(now=lambda: AT, sight_mode=mode)
        self.stories = FakeStoryStore(now=lambda: AT, sight_mode=mode)
        stores = BoundStores(memory=self.memory, stories=self.stories)
        self.recall = RecallStage(
            stores=stores,
            threshold=FAKE_RECALL_THRESHOLD,
            limit=RECALL_LIMIT,
            budget=RECALL_BUDGET,
        )
        self.windows = WindowsStage(
            episodes=RecentEpisodes(memory=self.memory, limit=10).walk, stores=stores
        )

    async def seed(self, *records: MemoryRecord) -> None:
        await self.memory.write_atomic(
            [MemoryWrite(record=one, mode=MemoryWriteMode.INSERT_IF_ABSENT) for one in records]
        )
        await self.stories.create(
            [activation("a-earlier")], home=RecordHome.owners(), actor=StoryActor.OWNER
        )

    async def recalled(self, state: ActivationState) -> list[str]:
        first = await self.recall.recall(
            _CUE, sight=_sight(state), audience=_BOUNDED, deadline=math.inf
        )
        again = await self.recall.recall_again(
            _CUE,
            (),
            sight=_sight(state),
            audience=_BOUNDED,
            deadline=math.inf,
            passed_over=frozenset(),
            cap=RECALL_LIMIT,
        )
        return _ids(first) + _ids(again)

    async def windowed(self, state: ActivationState) -> tuple[Windows, list[str]]:
        windows = await self.windows.assemble(
            TranscriptWindow(_CONVERSATION, ()),
            sight=_sight(state),
            audience=_BOUNDED,
            episodes=True,
        )
        fetched = await self.windows.fetch(
            sight=_sight(state),
            episode_ids=windows.episode_ids,
            recalled_ids=(_FACT.id,),
            audience=_BOUNDED,
        )
        return windows, [one.id for one in (*(fetched.episodes or ()), *fetched.recalled)]


def _ids(recalled: Recalled) -> list[str]:
    return [item.id for item in recalled.result.items]


async def _seeded(mode: SightMode) -> _Reads:
    reads = _Reads(mode)
    await reads.seed(_FACT, _EARLIER)
    return reads


# --- the sight: made at admission, made again at each join (§6:4 to §6:6) ----------------


def test_admission_makes_the_works_sight_from_its_facts_and_every_sender() -> None:
    state = _admitted(_OWNER)
    assert state.work_facts is not None
    assert state.sight == Sight.of_work(state.work_facts, (_OWNER,), activation=_ID)
    assert _sight(state).reader is SightReader.WORK
    assert _sight(state).activation == _ID
    assert _sight(state).homes_seen == {RecordHome.owners(), RecordHome.shared()}


@pytest.mark.parametrize("sender", [_OWNER, _OWNER_WEAK], ids=["normal", "weak"])
def test_the_owners_work_sees_the_owners_domain_at_every_level(sender: InputSender) -> None:
    """§6:9 and §6's first row: no level enters a sight."""
    assert _sight(_admitted(sender)).bounds == (SightBound.person(OWNER_PERSON_ID),)


def test_an_unidentified_senders_work_carries_an_anyone_bound_and_sees_no_home() -> None:
    """§6's second row: for the owner, whose connection it came by, and anyone."""
    sight = _sight(_admitted(_UNIDENTIFIED))
    assert SightBound.anyone() in sight.bounds
    assert sight.homes_seen == frozenset()


def test_a_join_narrows_the_sight_and_a_later_one_never_widens_it() -> None:
    """§6:6: the meet of the sight it had and the one its facts now give; the senders are
    every input's, not only those whose authority it carries (§6:4)."""
    state = _admitted(_OWNER)
    before = _sight(state)
    state.take_inputs((_joining(_UNIDENTIFIED),), merged=("act-other",))
    narrowed = _sight(state)
    assert SightBound.anyone() in narrowed.bounds
    assert narrowed.homes_seen == frozenset()
    assert narrowed.activation == before.activation
    state.take_inputs((_joining(_OWNER),), merged=("act-third",))
    assert _sight(state) == narrowed


def test_a_work_whose_facts_were_not_recorded_sees_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A defect deciding the facts: §6:7's anyone bound alone, and the log says so."""

    def _raises(*_: object, **__: object) -> None:
        raise RuntimeError("a defect")

    monkeypatch.setattr(work_facts_module, "started", _raises)
    with capture_logs() as logs:
        state = _admitted(_OWNER)
    assert state.work_facts is None
    assert _sight(state).bounds == (SightBound.anyone(),)
    assert _sight(state).homes_seen == frozenset()
    assert {"event": "work_sight_degraded", "at": "start", "reason": "facts"} in [
        {key: one[key] for key in ("event", "at", "reason") if key in one} for one in logs
    ]


def test_a_work_whose_activation_was_not_minted_reads_by_its_facts_with_nothing_its_own() -> None:
    state = _admitted(_OWNER, id_factory="not-a-uuid")
    assert state.activation_id is None
    assert _sight(state).bounds == (SightBound.person(OWNER_PERSON_ID),)
    assert _sight(state).activation is None


def test_a_stage_reads_the_sight_of_the_work_running_here_and_none_without_one() -> None:
    state = _admitted(_OWNER)
    token = CURRENT_ACTIVATION.set(ActivationScope(state))
    try:
        assert work_sight() == state.sight
    finally:
        CURRENT_ACTIVATION.reset(token)
    with pytest.raises(RuntimeError, match="sight"):
        work_sight()


# --- what the work reads, with stores that withhold (§6's table, §7:2) ---------------------


@pytest.mark.parametrize("sender", [_OWNER, _OWNER_WEAK], ids=["normal", "weak"])
async def test_the_owners_work_reads_as_today(sender: InputSender) -> None:
    reads = await _seeded(SightMode.WITHHOLD)
    state = _admitted(sender)
    recalled = await reads.recalled(state)
    assert set(recalled) == {_FACT.id, address("a-earlier")}
    windows, fetched = await reads.windowed(state)
    assert windows.episode_ids == (address("a-earlier"),)
    assert fetched == [address("a-earlier"), _FACT.id]


async def test_an_unidentified_senders_work_recalls_nothing_and_its_windows_are_empty() -> None:
    reads = await _seeded(SightMode.WITHHOLD)
    state = _admitted(_UNIDENTIFIED)
    assert await reads.recalled(state) == []
    windows, fetched = await reads.windowed(state)
    assert windows.episode_ids == ()
    assert fetched == []


async def test_a_join_that_narrows_the_sight_narrows_the_next_read() -> None:
    reads = await _seeded(SightMode.WITHHOLD)
    state = _admitted(_OWNER)
    assert await reads.recalled(state) != []
    state.take_inputs((_joining(_UNIDENTIFIED),), merged=("act-other",))
    assert await reads.recalled(state) == []
    windows, fetched = await reads.windowed(state)
    assert windows.episode_ids == ()
    assert fetched == []


# --- the counting build: as today, and each read counted (§11:1) ---------------------------


def _counted(
    logs: Sequence[MutableMapping[str, Any]],
) -> Iterator[tuple[object, object, object]]:
    for one in logs:
        if one["event"] == "sight_counted":
            yield one["store"], one["member"], one["reader"]


async def test_in_the_counting_build_every_read_answers_as_today_and_writes_its_count() -> None:
    reads = await _seeded(SightMode.COUNT)
    state = _admitted(_UNIDENTIFIED)
    with capture_logs() as logs:
        recalled = await reads.recall.recall(
            _CUE, sight=_sight(state), audience=_BOUNDED, deadline=math.inf
        )
        windows, fetched = await reads.windowed(state)
    # An unidentified sender's work reads what every work reads today.
    assert set(_ids(recalled)) == {_FACT.id, address("a-earlier")}
    assert windows.episode_ids == (address("a-earlier"),)
    assert fetched == [address("a-earlier"), _FACT.id]
    counted = list(_counted(logs))
    assert set(counted) == {
        ("memory", "search", "work"),
        ("stories", "stories_of", "work"),
        ("memory", "episodes", "work"),
        ("memory", "get_many", "work"),
    }
    # Each band's search is a read of its own (ADR-0281 §3).
    assert counted.count(("memory", "search", "work")) == 3
    withheld = [one for one in logs if one["event"] == "sight_counted" and one["given"]]
    assert all(one["other_home"] == 0 and one["sees_nothing"] == one["given"] for one in withheld)


async def test_the_engines_pass_reads_by_its_admitted_works_sight() -> None:
    """The engine hands recall and the windows the sight its pass carries: on a chat turn
    from the owner's linked device every count names a work's reader bound to the owner."""
    from test_phases_recall import _BOOKED, _harness, _seeded  # noqa: PLC0415 — one harness

    harness = _harness(await _seeded(_BOOKED))
    with capture_logs() as logs:
        await chat_turn(harness, "book the campsite at Pine Flat")
    counts = [one for one in logs if one["event"] == "sight_counted"]
    members = {(one["store"], one["member"]) for one in counts}
    assert {("memory", "search"), ("memory", "episodes"), ("memory", "get_many")} <= members
    assert all(one["reader"] == "work" for one in counts)
    assert all(one["bounds"] == ["person_owner"] for one in counts)
    assert all(one["other_home"] == one["no_home"] == one["sees_nothing"] == 0 for one in counts)
