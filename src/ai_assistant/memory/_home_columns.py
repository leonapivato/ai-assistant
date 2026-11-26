"""A sight over a store that keeps each record's home in two columns (ADR-0383 §7, §11).

The story store and the notification store each keep a record's home as two columns of
the record's own row, ``home_kind`` and ``home_id`` (ADR-0383 §2:2), and this module is
what a store bound to a sight needs of them, shared by both:

- :func:`stored_home`, **the one reading of the two columns**, which each store's record
  decoder reads a home by and which nothing else may re-spell;
- :func:`seen_sql`, the sight expressed in the store's own query over those columns, a
  positive match against the homes the sight sees, which answers as
  :meth:`~ai_assistant.core.types.Sight.withheld` does over :func:`stored_home`'s reading
  on every row (§7:3);
- :func:`count_homes`, the count event a read through a store bound in the counting mode
  writes (§11:1 to §11:3).

**Why the reading is strict.** A home is stored exactly as the store wrote it: the kind's
text and the identifier's text, or ``NULL`` for the shared things' identifier. A row whose
columns hold anything else, a ``NULL`` kind, a value stored as bytes, a kind no build
writes, a blank identifier, was altered outside the store, and its home is one the store
cannot read: the home of no one, withheld from every sight and never read as
the owner's or anyone else's (§5:3). Reading it strictly on both sides, in Python by type
and exact value and in SQL by ``typeof`` and exact comparison, is what makes the
statement and the decoder agree by construction, rather than by re-implementing a lax
coercion in SQL one corner at a time.

Nothing here decides what a sight sees: that is
:meth:`~ai_assistant.core.types.Sight.withheld`'s alone. Neither store records a record as
made by an activation (§7:4 names an activation's episode, its effects and the approvals it
asked, and none is held here), so a record is seen by its home alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog
from pydantic import ValidationError

from ai_assistant.core.types import RecordHome

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import Sight

_log = structlog.get_logger(__name__)

#: The event a read through a store bound in the counting mode writes (ADR-0383 §11:1),
#: the name the memory stores give it.
SIGHT_COUNTED: Final = "sight_counted"


def stored_home(kind: object, home_id: object) -> RecordHome | None:
    """The home two stored columns hold, or ``None`` where they hold none it can read.

    **The one reading** (ADR-0383 §2:2, §5:3): the kind is text naming a
    :class:`~ai_assistant.core.types.RecordHomeKind`, the identifier text, or ``NULL`` for
    the shared things, and the two make a valid home **exactly as stored**, with nothing
    coerced or normalised. Any other pair is a home the store cannot read.

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


def seen_sql(
    sight: Sight, *, kind_column: str = "home_kind", id_column: str = "home_id"
) -> tuple[str, list[object]]:
    """The store's expression of ``sight`` over a row's two home columns (ADR-0383 §7:3).

    **A positive match**: a row is seen where its columns hold, exactly and as text, one
    of the homes the sight sees (:attr:`~ai_assistant.core.types.Sight.homes_seen`), the
    shared things' identifier being ``NULL``. Each term compares ``typeof`` and the value,
    so a row is matched exactly where :func:`stored_home` reads a home the sight sees: a
    row with no home, or one the store cannot read, matches nothing (§5:3), and an
    identifier is never normalised, so a padded or re-cased one names another identity,
    as it does to the reading. A sight that sees no home is ``0``.

    The condition is ``0`` or ``1`` on every row and never ``NULL``, so its negation
    selects exactly the rows it does not. Only placeholders and the column names given
    are written into the text; every value is bound.

    Args:
        sight: The sight the store is bound to.
        kind_column: The kind's column, qualified where the statement joins.
        id_column: The identifier's column, qualified alike.

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
    if not terms:
        return "0", []
    matched = " OR ".join(terms)
    return f"coalesce((typeof({kind_column}) = 'text' AND ({matched})), 0)", params


def count_homes(
    sight: Sight, *, store: str, member: str, homes: Iterable[RecordHome | None]
) -> None:
    """Write §11:1's event for one read: what it gave back, and what ``sight`` withholds.

    To the hub's log alone, in numbers and codes (§11:3): no record's text and no
    identifier reach it, since :class:`~ai_assistant.core.types.SightCount` carries none.

    Args:
        sight: The sight the store is bound to.
        store: The store's code.
        member: The read member's name.
        homes: The home of each record the read gave back, ``None`` where it has none
            the store can read; no record here is made by an activation.
    """
    count = sight.count(store=store, member=member, given=((home, None) for home in homes))
    _log.info(SIGHT_COUNTED, **count.model_dump(mode="json"))
