"""What the phases read again before a report, for the news (ADR-0359, ADR-0360).

The re-reads, driven on their own over stand-ins for the engine's state and the memory
store. A work shown running that has ended is read as its frozen episode. Where the
memory store cannot be read, nothing is taken as established, so the work stays to be
checked before the next report rather than being named ended with nothing shown. A
record the news brings is held among what the activation was given (ADR-0309 §5:10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from test_planning import _episode

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import ChannelIdentity, Profile
from ai_assistant.orchestration.disclosure import UnboundedAudienceSupply
from ai_assistant.orchestration.phase_path import PhasePath
from ai_assistant.orchestration.planning import NewsShown, PlanningWork
from ai_assistant.testing.memories import memory

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ai_assistant.core.types import EpisodicMemory, Memory

pytestmark = pytest.mark.anyio

_SUPPLY: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())


@dataclass
class _Memory:
    """A memory store holding ``held``, or one that cannot be read."""

    held: dict[str, EpisodicMemory] = field(default_factory=dict)
    fails: bool = False

    async def get_many(self, ids: Sequence[str]) -> dict[str, EpisodicMemory]:
        if self.fails:
            msg = "the store cannot be read"
            raise MemoryStoreError(msg)
        return {one: self.held[one] for one in ids if one in self.held}

    async def get_history(self, ids: Sequence[str]) -> list[str]:
        return [one for one in ids if one in self.held]


class _Matters:
    """The engine's running work: none still runs, and none is newly running."""

    def in_progress(self, state: object, *, supply: object) -> tuple[tuple[()], int]:
        del state, supply
        return (), 0

    def state_of(self, activation_id: str) -> None:
        del activation_id


@dataclass
class _Supplied:
    obtained_records: list[object] = field(default_factory=list)

    def obtained(self, records: Iterable[object]) -> None:
        self.obtained_records.extend(records)


def _path(memory: _Memory) -> PhasePath:
    path = PhasePath.__new__(PhasePath)
    path._memory = cast("Any", memory)
    path._matters = cast("Any", _Matters())
    path._story_reads = None
    path._person_blocks = None
    return path


def _working(running: frozenset[str]) -> Any:
    work = cast("PlanningWork", SimpleNamespace(shown=NewsShown(running=running)))
    return SimpleNamespace(work=work, supplied=_Supplied())


async def test_an_ended_work_is_read_as_its_frozen_episode_and_supplied() -> None:
    """ADR-0360 §3:2, ADR-0309 §5:10: its short view's record is held as given."""
    record = _episode("activation:other")
    path = _path(_Memory(held={record.id: record}))
    working = _working(frozenset({"other"}))

    reread = await path._shown_now(
        working, cast("Any", object()), cast("Any", SimpleNamespace(supply=_SUPPLY))
    )

    assert reread.ended == {"other": record}
    assert working.supplied.obtained_records == [record]


async def test_a_store_that_cannot_be_read_names_no_work_ended() -> None:
    """Review round 1: a failed read establishes nothing; the work is checked again."""
    path = _path(_Memory(fails=True))
    working = _working(frozenset({"other"}))

    reread = await path._shown_now(
        working, cast("Any", object()), cast("Any", SimpleNamespace(supply=_SUPPLY))
    )

    assert reread.ended == {}
    assert working.supplied.obtained_records == []


@dataclass
class _Blocks:
    """The person blocks: one person, whose pins reach ``ends``, and the slot's budget."""

    pins: Sequence[object]
    ends: dict[str, Memory]
    budget_chars: int = 1600

    @property
    def store(self) -> Any:
        async def read(person_id: str) -> object:
            del person_id
            return SimpleNamespace(standing_pins=self.pins, profile=Profile(name="Leo"))

        return SimpleNamespace(read=read)

    async def current_ends(self, memory_ids: Iterable[str]) -> dict[str, Memory]:
        return {one: self.ends[one] for one in memory_ids if one in self.ends}


async def test_a_pin_past_the_slots_budget_is_not_shown_and_still_reached() -> None:
    """ADR-0360 §4:1, ADR-0338 §6:1-§6:2, review round 3: what the slot would now show.

    Pins of 800 and 700 characters fit 1,600; the first superseded by one of 1,700, the
    slot stops before it, so neither shows, and both are still reached, not unpinned.
    """
    grown = memory("m:grown", "x" * 1700)
    kept = memory("m:kept", "y" * 700)
    at = datetime(2026, 10, 1, tzinfo=UTC)
    pins = [
        SimpleNamespace(memory_id="m:first", pinned_at=at),
        SimpleNamespace(memory_id="m:kept", pinned_at=at + timedelta(days=1)),
    ]
    path = _path(_Memory())
    path._person_blocks = cast("Any", _Blocks(pins, {"m:first": grown, "m:kept": kept}))
    state = SimpleNamespace(
        person_block=object(),
        trigger=SimpleNamespace(
            channel=ChannelIdentity(channel_type="conversation", instance_id="chat"), target=None
        ),
    )

    person = await path._person_now(
        cast("Any", state), cast("Any", SimpleNamespace(supply=_SUPPLY))
    )

    assert person is not None
    assert person.pinned == ()
    assert person.reached == frozenset({"m:grown", "m:kept"})


@dataclass
class _StoryReads:
    """The story reads: which stories were read whole, each held with no summary."""

    read: list[str] = field(default_factory=list)

    async def states(self, story_ids: Sequence[str]) -> dict[str, None]:
        self.read.extend(story_ids)
        return dict.fromkeys(story_ids)

    async def members(self, story_ids: Sequence[str]) -> dict[str, int]:
        return dict.fromkeys(story_ids, 1)


async def test_a_matter_a_short_view_shows_is_read_whole_beside_the_briefing() -> None:
    """ADR-0359 §2:2, review round 3: a bounded view's baseline is the store's whole."""
    path = _path(_Memory())
    reads = _StoryReads()
    path._story_reads = cast("Any", reads)
    view = SimpleNamespace(story_id="story:cited")
    stories = SimpleNamespace(
        stories=(SimpleNamespace(story_id="story:own", inherited=()),), cited=(view,)
    )

    reread = await path._shown_now(
        cast("Any", SimpleNamespace(work=None, supplied=_Supplied())),
        cast("Any", object()),
        cast("Any", SimpleNamespace(supply=_SUPPLY)),
        cast("Any", stories),
    )

    assert reads.read == ["story:cited"]
    assert reread.matters == {"story:cited": None}


async def test_an_ended_work_whose_episode_is_not_frozen_is_read_again() -> None:
    """Review round 2: an episode still open names no work ended, so it is read again."""
    record = _episode("activation:other")
    processing = record.processing_record
    assert processing is not None
    still_open = record.model_copy(
        update={
            "processing_record": processing.model_copy(
                update={"ended_at": None, "status": None, "reason": None}
            )
        }
    )
    path = _path(_Memory(held={record.id: still_open}))
    working = _working(frozenset({"other"}))

    reread = await path._shown_now(
        working, cast("Any", object()), cast("Any", SimpleNamespace(supply=_SUPPLY))
    )

    assert reread.ended == {}
