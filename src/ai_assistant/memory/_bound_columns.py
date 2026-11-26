"""A store's side of a sight where each record keeps its home in columns (ADR-0383 §7, §11).

What the conversation store and the person-model store share about a bound store: the
SQL condition that keeps a row whose home a sight sees, read from the row's own stored
columns (§7:3); the home a row's columns hold, read exactly as that condition reads them
(§5:3); and the count event a read through a store bound in the counting mode writes
(§11:1 to §11:3). What a sight sees is :meth:`~ai_assistant.core.types.Sight.withheld`'s
alone; nothing here decides it.

**Exact, so never wider** (§5:3, §7:3). A row is seen only where its columns hold,
byte for byte, the kind and the identifier of a home the sight sees, as
:meth:`~ai_assistant.core.types.RecordHome.model_dump` writes them; :func:`home_of_columns`
reads a row's home by the same rule, so the condition a withholding store applies and
the home a counting store counts by agree on every row. A row whose columns are missing,
of another type, or anything a write of this store would not have written, has no home a
bound store reads, and is withheld from every sight.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog
from pydantic import ValidationError

from ai_assistant.core.types import RecordHome, RecordHomeKind

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import Sight

__all__ = [
    "SIGHT_COUNTED",
    "count_given",
    "home_of_columns",
    "home_of_person",
    "persons_seen_sql",
    "seen_sql",
]

_log = structlog.get_logger(__name__)

#: The event a read through a store bound in the counting mode writes (§11:1); the
#: memory store's own module writes the same name.
SIGHT_COUNTED: Final = "sight_counted"


def home_of_columns(kind: object, ident: object) -> RecordHome | None:
    """The home a row's two home columns hold, or ``None`` where they hold none (§5:3).

    Read exactly: the kind is a ``str`` naming a :class:`RecordHomeKind`, the identifier
    a ``str`` or, for the shared things, ``NULL``, and the home they make dumps back to
    the very same two values. Anything else is no home, withheld from every sight, and
    never read as a wider one; :func:`seen_sql` selects by the same rule.
    """
    if not isinstance(kind, str) or not (ident is None or isinstance(ident, str)):
        return None
    try:
        home = RecordHome(kind=RecordHomeKind(kind), id=ident)
    except ValidationError, ValueError:
        return None
    if home.kind.value != kind or home.id != ident:
        return None
    return home


def home_of_person(person_id: object) -> RecordHome | None:
    """The home of a record keyed by ``person_id``: that person's domain (§3, §5:2).

    ``None`` where the stored id does not read back, byte for byte, as a person's id,
    as :func:`persons_seen_sql` selects.
    """
    return home_of_columns(RecordHomeKind.PERSON.value, person_id)


def seen_sql(sight: Sight, *, kind: str, ident: str) -> tuple[str, list[object]]:
    """``sight`` over a row whose home is in the columns ``kind`` and ``ident`` (§7:3).

    A row is seen where its two columns equal those of a home every bound sees
    (:attr:`~ai_assistant.core.types.Sight.homes_seen`). The condition is ``0`` or ``1``
    on every row and never ``NULL``, so its negation selects exactly the rows it does
    not. Only placeholders are written into the text; every value is bound.

    Args:
        sight: The sight the store is bound to.
        kind: The column, qualified as the statement needs, holding the home's kind.
        ident: The column holding the home's identifier.

    Returns:
        The SQL condition and its parameters, in order.
    """
    terms: list[str] = []
    params: list[object] = []
    for home in sorted(sight.homes_seen, key=lambda one: (one.kind.value, one.id or "")):
        terms.append(f"({kind} = ? AND {ident} IS ?)")
        params.extend([home.kind.value, home.id])
    if not terms:
        return "0", []
    return f"coalesce(({' OR '.join(terms)}), 0)", params


def persons_seen_sql(sight: Sight, *, column: str) -> tuple[str, list[object]]:
    """``sight`` over a row keyed by a person's id in ``column`` (§5:2, §7:3).

    A row is seen where the person's domain is a home every bound sees. ``0`` or ``1``
    on every row, never ``NULL``.

    Returns:
        The SQL condition and its parameters, in order.
    """
    persons = sorted(
        str(home.id) for home in sight.homes_seen if home.kind is RecordHomeKind.PERSON
    )
    if not persons:
        return "0", []
    return f"coalesce({column} IN ({', '.join('?' * len(persons))}), 0)", list(persons)


def count_given(
    sight: Sight, *, store: str, member: str, given: Iterable[RecordHome | None]
) -> None:
    """Write §11:1's event for one read: what it gave back, and what ``sight`` withholds.

    To the hub's log alone, in numbers and codes (§11:3): no record's text and no
    identifier reach it, since :class:`~ai_assistant.core.types.SightCount` carries none.
    No record of these stores is made by an activation (§7:4), so none is counted as
    the sight's own.

    Args:
        sight: The sight the store is bound to.
        store: The store's code.
        member: The read member's name.
        given: The home of each record the read gave back, ``None`` where it has none
            a bound store reads.
    """
    count = sight.count(store=store, member=member, given=((home, None) for home in given))
    _log.info(SIGHT_COUNTED, **count.model_dump(mode="json"))
