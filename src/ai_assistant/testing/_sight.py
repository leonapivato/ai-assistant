"""The canonical fake's side of a sight (ADR-0383 §7, §11).

Duplicated from ``ai_assistant.memory._sight`` for the reason every shared piece of the
fake is: ``ai_assistant.testing`` may not import a subsystem (golden rule 1). The shared
``MemoryStore`` suite runs the same cases against the fake and both memory stores, so
the copies cannot drift unseen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.types import EpisodicMemory

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import MemoryRecord, Sight

_log = structlog.get_logger(__name__)

#: The store's code in ADR-0383 §11:1's event, as the memory stores write it.
STORE_CODE: Final = "memory"

#: The event a read through a store bound in the counting mode writes (§11:1).
SIGHT_COUNTED: Final = "sight_counted"

#: An activation's episode's id is this prefix and the activation's id (ADR-0283 §2:1).
_EPISODE_PREFIX: Final = "activation:"


def made_by(record: MemoryRecord) -> str | None:
    """The activation the store records as having made ``record`` (ADR-0383 §7:4).

    An activation's episode, by its id; ``None`` for a memory.
    """
    if isinstance(record, EpisodicMemory) and record.id.startswith(_EPISODE_PREFIX):
        return record.id.removeprefix(_EPISODE_PREFIX)
    return None


def count_records(sight: Sight, member: str, records: Iterable[MemoryRecord]) -> None:
    """Write §11:1's event for one read that gave back ``records``, as the stores do."""
    count = sight.count(
        store=STORE_CODE,
        member=member,
        given=((record.home, made_by(record)) for record in records),
    )
    _log.info(SIGHT_COUNTED, **count.model_dump(mode="json"))
