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


#: A ``records`` row's home as the decoder reads it, rendered in the compact form
#: ``RecordHome.model_dump_json()`` gives, or ``NULL`` where the row has none the
#: decoder could read (ADR-0383 §5:3, §7:3).
#:
#: It reads the row's JSON as the record decoder does, so the expression and the
#: predicate over a decoded record agree on every row: the **last** top-level ``home``
#: key where one is given twice, as the decoder keeps the last; an object holding no
#: key but ``kind`` and ``id``, in any order, the last of each where one is given
#: twice; and ``id`` absent read as ``null``. The rendered text equals a valid home's
#: only where the decoder would read that home, since a value of another type renders
#: otherwise (a number unquoted, an object as a string). Invalid JSON has no home.
STORED_HOME_SQL: Final = (
    "(SELECT CASE WHEN h.type = 'object' "
    "AND NOT EXISTS (SELECT 1 FROM json_each(h.value) e WHERE e.key NOT IN ('kind', 'id')) "
    "THEN json_object("
    "'kind', (SELECT e.value FROM json_each(h.value) e WHERE e.key = 'kind' "
    "ORDER BY e.id DESC LIMIT 1), "
    "'id', (SELECT e.value FROM json_each(h.value) e WHERE e.key = 'id' "
    "ORDER BY e.id DESC LIMIT 1)) END "
    "FROM json_each(CASE WHEN json_valid(data) THEN data END) h "
    "WHERE h.key = 'home' ORDER BY h.id DESC LIMIT 1)"
)


def seen_sql(sight: Sight) -> tuple[str, list[object]]:
    """The persistent store's expression of ``sight`` over a ``records`` row (§7:3).

    A row is seen where its home, read as the record decoder reads it
    (:data:`STORED_HOME_SQL`), is one every bound sees
    (:attr:`~ai_assistant.core.types.Sight.homes_seen`), or where it is the episode of
    the sight's activation (§7:4). A row with no home the decoder could read is seen by
    no sight (§5:3).

    The condition is ``0`` or ``1`` on every row and never ``NULL``, so its negation
    selects exactly the rows it does not, which the write refusals read (§7:5). Only
    placeholders are written into the text; every value is bound.

    Returns:
        The SQL condition and its parameters, in order.
    """
    terms: list[str] = []
    params: list[object] = []
    homes = sorted(home.model_dump_json() for home in sight.homes_seen)
    if homes:
        terms.append(f"{STORED_HOME_SQL} IN ({', '.join('?' * len(homes))})")
        params.extend(homes)
    if sight.activation is not None:
        terms.append("(kind = ? AND id = ?)")
        params.extend([MemoryKind.EPISODIC.value, episode_of(sight.activation)])
    if not terms:
        return "0", []
    return f"coalesce(({' OR '.join(terms)}), 0)", params
