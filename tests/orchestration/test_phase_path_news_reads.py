"""What the phases read again before a report, for the news (ADR-0359, ADR-0360).

The re-reads, driven on their own over stand-ins for the engine's state and the memory
store. A work shown running that has ended is read as its frozen episode. Where the
memory store cannot be read, nothing is taken as established, so the work stays to be
checked before the next report rather than being named ended with nothing shown. A
record the news brings is held among what the activation was given (ADR-0309 §5:10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from test_planning import _episode

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.orchestration.disclosure import UnboundedAudienceSupply
from ai_assistant.orchestration.phase_path import PhasePath
from ai_assistant.orchestration.planning import NewsShown, PlanningWork

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ai_assistant.core.types import EpisodicMemory

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
