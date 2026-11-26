"""The memory store's side of a sight (ADR-0383 §7, §11).

What both memory stores share about a bound store: which activation the store records
as having made a record (§7:4), the count event a read through a store bound in the
counting mode writes (§11:1 to §11:3), and the persistent store's expression of a sight
in its own query (§7:3). What a sight sees is :meth:`~ai_assistant.core.types.Sight.withheld`'s
alone; nothing here decides it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.types import EpisodicMemory, MemoryKind

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import MemoryRecord, RecordHome, Sight

_log = structlog.get_logger(__name__)

#: The store's code in §11:1's event.
STORE_CODE: Final = "memory"

#: The event a read through a store bound in the counting mode writes (§11:1).
SIGHT_COUNTED: Final = "sight_counted"

#: An activation's episode's id is this prefix and the activation's id (ADR-0283 §2:1).
_EPISODE_PREFIX: Final = "activation:"


def episode_of(activation: str) -> str:
    """The id of ``activation``'s episode, ``activation:<activation_id>`` (ADR-0283 §2:1)."""
    return f"{_EPISODE_PREFIX}{activation}"


def made_by(record: MemoryRecord) -> str | None:
    """The activation this store records as having made ``record`` (ADR-0383 §7:4).

    An activation's episode, by its id; ``None`` for a memory, which the store records
    as made by no activation, whatever its supports name.
    """
    if isinstance(record, EpisodicMemory) and record.id.startswith(_EPISODE_PREFIX):
        return record.id.removeprefix(_EPISODE_PREFIX)
    return None


def made_by_id(kind: str, record_id: str) -> str | None:
    """:func:`made_by` from a stored row's kind and id, before the record is decoded."""
    if kind == MemoryKind.EPISODIC.value and record_id.startswith(_EPISODE_PREFIX):
        return record_id.removeprefix(_EPISODE_PREFIX)
    return None


def count_given(
    sight: Sight, member: str, given: Iterable[tuple[RecordHome | None, str | None]]
) -> None:
    """Write §11:1's event for one read: what it gave back, and what ``sight`` withholds.

    To the hub's log alone, in numbers and codes (§11:3): no record's text and no
    identifier reach it, since :class:`~ai_assistant.core.types.SightCount` carries
    none.

    Args:
        sight: The sight the store is bound to.
        member: The read member's name.
        given: Each record the read gave back, as its home and the activation the store
            records as having made it.
    """
    count = sight.count(store=STORE_CODE, member=member, given=given)
    _log.info(SIGHT_COUNTED, **count.model_dump(mode="json"))


def count_records(sight: Sight, member: str, records: Iterable[MemoryRecord]) -> None:
    """:func:`count_given` for a read that gave back whole records."""
    count_given(sight, member, ((record.home, made_by(record)) for record in records))


def seen_sql(sight: Sight) -> tuple[str, list[object]]:
    """The persistent store's expression of ``sight`` over a ``records`` row (§7:3).

    A row is seen where its stored home's kind and identifier are those of a home every
    bound sees (:attr:`~ai_assistant.core.types.Sight.homes_seen`), or where it is the
    episode of the sight's activation (§7:4). A row whose JSON is not valid, or carries
    no home, matches no home and is seen only as an activation's own episode, which is
    :meth:`~ai_assistant.core.types.Sight.withheld`'s answer for a home the store cannot
    read (§5:3). Only placeholders are written into the text; every value is bound.

    Returns:
        The SQL condition and its parameters, in order.
    """
    terms: list[str] = []
    params: list[object] = []
    for home in sorted(sight.homes_seen, key=lambda one: (one.kind.value, one.id or "")):
        terms.append(
            "(json_extract(CASE WHEN json_valid(data) THEN data END, '$.home.kind') = ? "
            "AND json_extract(CASE WHEN json_valid(data) THEN data END, '$.home.id') IS ?)"
        )
        params.extend([home.kind.value, home.id])
    if sight.activation is not None:
        terms.append("(kind = ? AND id = ?)")
        params.extend([MemoryKind.EPISODIC.value, episode_of(sight.activation)])
    if not terms:
        return "0", []
    return f"({' OR '.join(terms)})", params
