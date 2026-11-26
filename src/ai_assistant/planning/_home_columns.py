"""A sight over the plan store's records (ADR-0383 §3, §7, §11).

The plan store keeps two kinds of record whose home is two columns of their own row,
``home_kind`` and ``home_id`` (ADR-0383 §2:2): an activation's effect records and the
observation records. It keeps two kinds whose home is the person a column already names
(§3, §5:2): a scheduled task and an approval request, whose ``person`` is whom each is
for, and whose domain is its home. A stop record carries none, and no bound store gives
one back, counts it or names it (§3:3). This module is what a store bound to a sight
needs of them:

- :func:`stored_home` and :func:`person_home`, **the one reading** of what a row's
  columns say its home is, which nothing else may re-spell;
- :func:`register_readers`, which gives the store's connection those two readings as SQL
  functions, so a statement asks whether a row's home is readable by the same code;
- :func:`seen_sql` and :func:`seen_person_sql`, the sight expressed in the store's own
  query over those columns, a positive match against the homes the sight sees
  (:attr:`~ai_assistant.core.types.Sight.homes_seen`), or against the activation the
  store records as having made the row (§7:4), which answers as
  :meth:`~ai_assistant.core.types.Sight.withheld` does over the reading above on every
  row (§7:3);
- :func:`count_given`, the count event a read through a store bound in the counting mode
  writes (§11:1 to §11:3).

**Why the reading is strict.** A home is stored exactly as the store wrote it: the kind's
text and the identifier's text, or ``NULL`` for the shared things' identifier; a person
as the text the record names. A row whose columns hold anything else was altered outside
the store, and its home is one the store cannot read: the home of no one, withheld from
every sight, its own activation's included, and never read as the owner's or anyone
else's (§5:3). Reading it strictly on both sides, in Python by type and exact value and
in SQL by ``typeof`` and exact comparison, is what makes the statement and the reading
agree by construction. For a row altered outside the store the columns are the store's
record of its home, and every statement decides by them (the coordinator's ruling on
#3742).

The same small thing for the story and notification stores is
``ai_assistant.memory._home_columns``, which ``planning`` may not import (golden rule
1); the two are kept alike by hand. Nothing here decides what a sight sees: that is
:meth:`~ai_assistant.core.types.Sight.withheld`'s alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog
from pydantic import ValidationError

from ai_assistant.core.types import RecordHome, RecordHomeKind

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable

    from ai_assistant.core.types import Sight

_log = structlog.get_logger(__name__)

#: This store's code in ADR-0383 §11:1's count event.
STORE_CODE: Final = "plans"

#: The event a read through a store bound in the counting mode writes (ADR-0383 §11:1),
#: the name every bound store gives it.
SIGHT_COUNTED: Final = "sight_counted"

#: The SQL function :func:`register_readers` gives a connection: ``1`` where two home
#: columns hold a home :func:`stored_home` reads, ``0`` otherwise.
HOME_READER: Final = "plan_home_readable"

#: The SQL function :func:`register_readers` gives a connection: ``1`` where a person
#: column holds a person :func:`person_home` reads, ``0`` otherwise.
PERSON_READER: Final = "plan_person_readable"


def stored_home(kind: object, home_id: object) -> RecordHome | None:
    """The home two stored columns hold, or ``None`` where they hold none it can read.

    **The one reading** of an effect's or an observation's two home columns (ADR-0383
    §2:2, §5:3): the kind is text naming a :class:`~ai_assistant.core.types.RecordHomeKind`,
    the identifier text, or ``NULL`` for the shared things, and the two make a valid home
    **exactly as stored**, with nothing coerced or normalised. Any other pair is a home
    the store cannot read.

    Args:
        kind: The ``home_kind`` column's value, as the driver gave it.
        home_id: The ``home_id`` column's value, as the driver gave it.

    Returns:
        The home, or ``None`` where the columns hold no home this reading accepts.
    """
    if type(kind) is not str or (home_id is not None and type(home_id) is not str):
        return None
    try:
        home = RecordHome.model_validate({"kind": kind, "id": home_id})
    except ValidationError:
        return None
    if home.kind.value != kind or home.id != home_id:
        return None
    return home


def person_home(person: object) -> RecordHome | None:
    """The home a scheduled task's or an approval request's stored person names (§3, §5:2).

    **The one reading**: that person's domain, exactly as stored, where the column holds
    text that names a person; ``None`` otherwise, a home the store cannot read (§5:3).

    Args:
        person: The ``person`` column's value, as the driver gave it, or the record's.

    Returns:
        The home, or ``None`` where it names none this reading accepts.
    """
    if type(person) is not str:
        return None
    try:
        home = RecordHome.person(person)
    except ValidationError:
        return None
    return home if home.id == person else None


#: What :func:`_stored_value` gives for a column that holds no text it can read: not a
#: ``str``, so the readings refuse it.
_UNREADABLE: Final = object()


def _stored_value(storage: object, raw: object) -> object:
    """A column's value as the readings take it, from its storage class and its bytes.

    The statement hands the storage class (``typeof``) and the value cast to a blob, so no
    text reaches Python's own decoding of a callback's argument, which raises on bytes
    that are not UTF-8. Text is decoded strictly here, and text that is not UTF-8 is
    :data:`_UNREADABLE`; ``NULL`` is ``None``; anything else is :data:`_UNREADABLE` too,
    since no reading accepts a value that is not text.
    """
    if storage == "null":
        return None
    if storage != "text" or not isinstance(raw, bytes):
        return _UNREADABLE
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return _UNREADABLE


def _home_readable(kind_type: object, kind: object, id_type: object, home_id: object) -> int:
    """``1`` where :func:`stored_home` reads a home in the two columns, ``0`` otherwise."""
    home = stored_home(_stored_value(kind_type, kind), _stored_value(id_type, home_id))
    return int(home is not None)


def _person_readable(person_type: object, person: object) -> int:
    """``1`` where :func:`person_home` reads a person in the column, ``0`` otherwise."""
    return int(person_home(_stored_value(person_type, person)) is not None)


def register_readers(conn: sqlite3.Connection) -> None:
    """Give ``conn`` :data:`HOME_READER` and :data:`PERSON_READER`, the one reading in SQL.

    A row of a sight's own activation is held only where its home is one the store can
    read (§5:3, §7:4). Whether it is turns on whether an identifier is blank or encodable,
    which SQL cannot decide as the model does, so the statement asks
    :func:`stored_home` and :func:`person_home` themselves. Each function takes a column
    as its storage class and its value cast to a blob (:func:`_stored_value`), so a value
    no reading accepts, text that is not UTF-8 included, answers ``0`` and never raises.
    Each is deterministic and reads nothing but its arguments.

    Raises:
        sqlite3.Error: If the connection refuses a function.
    """
    conn.create_function(HOME_READER, 4, _home_readable, deterministic=True)
    conn.create_function(PERSON_READER, 2, _person_readable, deterministic=True)


def _reader_args(*columns: str) -> str:
    """The arguments a reader takes for ``columns``: each one's storage class and blob."""
    return ", ".join(f"typeof({one}), CAST({one} AS BLOB)" for one in columns)


def seen_sql(
    sight: Sight,
    *,
    kind_column: str = "home_kind",
    id_column: str = "home_id",
    made_by: str | None = None,
) -> tuple[str, list[object]]:
    """The store's expression of ``sight`` over a row's two home columns (ADR-0383 §7:3).

    **A positive match**: a row is seen where its columns hold, exactly and as text, one of
    the homes the sight sees, the shared things' identifier being ``NULL``; or, where
    ``made_by`` is given and the sight is a work's, where the row is that work's own
    (§7:4) and :data:`HOME_READER` reads a home in its columns. A row with no home, or one
    the store cannot read, matches nothing (§5:3), and an identifier is never normalised.
    The connection must carry :func:`register_readers`'s functions.

    The condition is ``0`` or ``1`` on every row and never ``NULL``, so its negation
    selects exactly the rows it does not. Only placeholders, the enumeration's values and
    the column expressions given are written into the text; every other value is bound.

    Args:
        sight: The sight the store is bound to.
        kind_column: The kind's column.
        id_column: The identifier's column.
        made_by: A column holding the activation the store records as having made the
            row, or ``None`` where it records none.

    Returns:
        The SQL condition and its parameters, in order.
    """
    terms: list[str] = []
    params: list[object] = []
    for home in sorted(sight.homes_seen, key=lambda one: (one.kind.value, one.id or "")):
        if home.id is None:
            terms.append(f"({kind_column} = ? AND {id_column} IS NULL)")
            params.append(home.kind.value)
        else:
            terms.append(
                f"({kind_column} = ? AND typeof({id_column}) = 'text' AND {id_column} = ?)"
            )
            params.extend([home.kind.value, home.id])
    if made_by is not None and sight.activation is not None:
        terms.append(
            f"(typeof({made_by}) = 'text' AND {made_by} = ? AND "
            f"{HOME_READER}({_reader_args(kind_column, id_column)}))"
        )
        params.append(sight.activation)
    if not terms:
        return "0", []
    matched = " OR ".join(terms)
    return f"coalesce((typeof({kind_column}) = 'text' AND ({matched})), 0)", params


def seen_person_sql(
    sight: Sight, *, person_column: str = "person", made_by: str | None = None
) -> tuple[str, list[object]]:
    """The store's expression of ``sight`` over a row's ``person`` column (ADR-0383 §7:3).

    **A positive match**: a row is seen where its column holds, exactly and as text, a
    person whose domain is a home the sight sees; or, where ``made_by`` is given and the
    sight is a work's, where the row is that work's own (§7:4) and :data:`PERSON_READER`
    reads a person in its column. A shared or group home names no person, so no task or
    request is seen by it. The connection must carry :func:`register_readers`'s functions.

    The condition is ``0`` or ``1`` on every row and never ``NULL``.

    Args:
        sight: The sight the store is bound to.
        person_column: The person's column.
        made_by: An expression giving the activation the store records as having made
            the row, ``NULL`` where it cannot be read, or ``None`` where it records none.

    Returns:
        The SQL condition and its parameters, in order.
    """
    persons = sorted(
        str(home.id) for home in sight.homes_seen if home.kind is RecordHomeKind.PERSON
    )
    terms: list[str] = []
    params: list[object] = []
    if persons:
        marks = ", ".join("?" for _ in persons)
        terms.append(f"({person_column} IN ({marks}))")
        params.extend(persons)
    if made_by is not None and sight.activation is not None:
        terms.append(f"({made_by} = ? AND {PERSON_READER}({_reader_args(person_column)}))")
        params.append(sight.activation)
    if not terms:
        return "0", []
    matched = " OR ".join(terms)
    return f"coalesce((typeof({person_column}) = 'text' AND ({matched})), 0)", params


def count_given(
    sight: Sight, *, member: str, given: Iterable[tuple[RecordHome | None, str | None]]
) -> None:
    """Write §11:1's event for one read: what it gave back, and what ``sight`` withholds.

    To the hub's log alone, in numbers and codes (§11:3): no record's text and no
    identifier reach it, since :class:`~ai_assistant.core.types.SightCount` carries none.

    Args:
        sight: The sight the store is bound to.
        member: The read member's name.
        given: Each record the read gave back, as its home (``None`` where it has none
            the store can read, a stop record's among them) and the activation the
            store records as having made it.
    """
    count = sight.count(store=STORE_CODE, member=member, given=given)
    _log.info(SIGHT_COUNTED, **count.model_dump(mode="json"))
