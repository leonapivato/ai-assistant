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

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import EpisodicMemory, MemoryKind, RecordHome

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Iterable

    from ai_assistant.core.types import MemoryRecord, Sight

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


#: The SQL function the persistent store's connection carries (``register_home_reader``):
#: a row's home as the store's own record decoder reads it.
HOME_READER: Final = "assistant_record_home"

#: A ``records`` row's home, read by the store's record decoder over the row's whole
#: JSON and rendered as ``RecordHome.model_dump_json()`` renders it, or ``NULL`` where
#: the decoder reads no record there, and so no home (ADR-0383 §5:3, §7:3).
STORED_HOME_SQL: Final = f"{HOME_READER}(CAST(data AS BLOB))"


def register_home_reader(conn: sqlite3.Connection, decode: Callable[[str], MemoryRecord]) -> None:
    """Give ``conn`` :data:`HOME_READER`: the store's record decoder, as a SQL function.

    The function takes a row's bytes, reads them as UTF-8 as the driver reads a row,
    decodes the whole JSON with ``decode``, the very decoder every read of the store
    decodes a row with, and answers the home the record carries; a row that is not
    UTF-8, or that the decoder refuses, has none. So nothing re-implements how the decoder reads a
    repeated key, a key's order, a value's type, an escape or a malformed record, and
    a statement that compares the function's value with the homes a sight sees agrees
    with the predicate over the decoded record on every row by construction (§7:3).
    Deterministic, so SQLite may evaluate it once per distinct row.

    Args:
        conn: The store's connection.
        decode: The store's record decoder; it raises ``MemoryStoreError`` on a row it
            refuses.
    """

    def home_of(stored: object) -> str | None:
        # The row's bytes, decoded here as the driver decodes a row it hands the store,
        # so a payload that is not UTF-8 is a row the decoder never reads, answered as
        # no home rather than raised inside SQLite (§5:3, §11:1).
        if not isinstance(stored, bytes):
            return None
        try:
            return decode(stored.decode("utf-8")).home.model_dump_json()
        except UnicodeDecodeError, MemoryStoreError:
            return None

    conn.create_function(HOME_READER, 1, home_of, deterministic=True)


def read_home(rendered: object) -> RecordHome | None:
    """A home :data:`STORED_HOME_SQL` rendered, read back; ``None`` where it rendered none."""
    if not isinstance(rendered, str):
        return None
    return RecordHome.model_validate_json(rendered)


def seen_sql(sight: Sight) -> tuple[str, list[object]]:
    """The persistent store's expression of ``sight`` over a ``records`` row (§7:3).

    A row is seen where its home, read by the store's own record decoder
    (:data:`STORED_HOME_SQL`, on a connection :func:`register_home_reader` prepared),
    is one every bound sees (:attr:`~ai_assistant.core.types.Sight.homes_seen`), or
    where it is the episode of the sight's activation (§7:4) and carries a home the
    decoder reads. A row with no home the decoder reads is seen by no sight, its own
    activation's included (§5:3).

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
        terms.append(f"(kind = ? AND id = ? AND {STORED_HOME_SQL} IS NOT NULL)")
        params.extend([MemoryKind.EPISODIC.value, episode_of(sight.activation)])
    if not terms:
        return "0", []
    return f"coalesce(({' OR '.join(terms)}), 0)", params
