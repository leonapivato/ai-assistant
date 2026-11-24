"""What the plan store's step past label 19 does to a stored task's row (ADR-0368 §6:3).

The step rewrites each scheduled task's blob to add who set it, ``author_person``,
``setting_level`` and ``setting_connection``, and changes nothing else. A legacy test
written before that step, which held a task's row to be carried byte for byte, holds it
instead to be carried with those three fields alone added: :func:`unset` takes them off
the rows the head left, and :func:`decoded` reads the rows the file held, so the two
compare as the values the records hold.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

#: The fields the step past label 19 adds to every task's blob.
SETTER_FIELDS: Final = ("author_person", "setting_level", "setting_connection")


def decoded(rows: Iterable[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Each ``scheduled_tasks`` row, its blob (the last column) decoded."""
    return [(*row[:-1], json.loads(str(row[-1]))) for row in rows]


def unset(rows: Iterable[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Each row as :func:`decoded` reads it, with the three setter fields taken off.

    Raises:
        AssertionError: If a row lacks any of them, which the step writes on every task.
    """
    held = []
    for *columns, record in decoded(rows):
        assert all(one in record for one in SETTER_FIELDS), record
        held.append((*columns, {k: v for k, v in record.items() if k not in SETTER_FIELDS}))
    return held
