"""What the plan store's step past label 20 does to a stored request's row (ADR-0377 §4:3).

The step rewrites each answered request's blob to give its answer who tapped, ``person``
the request's person and ``level`` not recorded, and changes nothing else. A legacy test
written before that step, which held a request's row to be carried byte for byte, holds
it instead to be carried with those two fields alone added to its answer: :func:`untapped`
takes them off the rows the head left, checking they are what the step writes, and
:func:`decoded` reads the rows the file held, so the two compare as the values the
records hold.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

#: The fields the step past label 20 adds to every answer.
TAPPER_FIELDS: Final = ("person", "level")


def decoded(rows: Iterable[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Each ``approval_requests`` row, its blob (the last column) decoded."""
    return [(*row[:-1], json.loads(str(row[-1]))) for row in rows]


def untapped(rows: Iterable[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Each row as :func:`decoded` reads it, with its answer's two tapper fields taken off.

    Raises:
        AssertionError: If an answer lacks either, or holds other than the request's
            person at no recorded level, which is what the step writes on every answer.
    """
    held = []
    for *columns, record in decoded(rows):
        answer = record.get("answer")
        if answer is None:
            held.append((*columns, record))
            continue
        assert all(one in answer for one in TAPPER_FIELDS), answer
        assert {one: answer[one] for one in TAPPER_FIELDS} == {
            "person": record["person"],
            "level": None,
        }, answer
        stripped = {k: v for k, v in answer.items() if k not in TAPPER_FIELDS}
        held.append((*columns, {**record, "answer": stripped}))
    return held
