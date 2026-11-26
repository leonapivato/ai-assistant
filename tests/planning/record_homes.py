"""What the plan store's step past label 21 does to a stored record's row (ADR-0383 §5:1).

The step writes the owner's domain into every effect record and every observation record
a file holds: ``home`` in its blob, and the home's kind and identifier in two columns it
adds to the row's end (``home_kind``, ``home_id``). It changes nothing else, and no other
table. A legacy test written before that step, which held such a row to be carried byte
for byte, holds it instead to be carried with the home alone added: :func:`homeless` takes
the home off the rows the head left, checking it is the owner's, and :func:`decoded` reads
the rows the file held, so the two compare as the values the records hold.
:func:`owners_effect` and :func:`owners_observation` read a record the file held as the
head reads it after the step.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

from ai_assistant.core.types import ActivationEffect, ObservationRecord, RecordHome

if TYPE_CHECKING:
    from collections.abc import Iterable

#: The tables whose rows the step rewrites, each with its blob's place in the row as
#: ``SELECT *`` reads it.
HOMED: Final = {"activation_effects": 3, "observations": 3}

#: The home the step writes, in the blob and in the two columns.
OWNERS_JSON: Final = RecordHome.owners().model_dump(mode="json")
OWNERS_COLUMNS: Final = (RecordHome.owners().kind.value, RecordHome.owners().id)


def decoded(table: str, rows: Iterable[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Each row of a homed ``table`` as the file held it, its blob decoded."""
    blob = HOMED[table]
    return [(*row[:blob], json.loads(str(row[blob])), *row[blob + 1 :]) for row in rows]


def homeless(table: str, rows: Iterable[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Each row of a homed ``table`` as the head left it, with its home taken off.

    Raises:
        AssertionError: If a row's two home columns, or its blob's home, are not the
            owner's domain, which is what the step writes on every record.
    """
    blob = HOMED[table]
    held = []
    for row in rows:
        *columns, kind, home_id = row
        assert (kind, home_id) == OWNERS_COLUMNS, row
        record = json.loads(str(columns[blob]))
        assert record.pop("home") == OWNERS_JSON, record
        columns[blob] = record
        held.append(tuple(columns))
    return held


def owners_effect(blob: object) -> ActivationEffect:
    """An effect record the file held, as the head reads it once the step gave it a home."""
    return ActivationEffect.model_validate({**json.loads(str(blob)), "home": OWNERS_JSON})


def owners_observation(blob: object) -> ObservationRecord:
    """An observation record the file held, as the head reads it with its home."""
    return ObservationRecord.model_validate({**json.loads(str(blob)), "home": OWNERS_JSON})


def decoded_tables(dumped: dict[str, list[tuple[Any, ...]]]) -> dict[str, list[tuple[Any, ...]]]:
    """A dump of the file as it was, each homed table's rows read by :func:`decoded`."""
    return {
        table: decoded(table, rows) if table in HOMED else rows for table, rows in dumped.items()
    }


def homeless_tables(dumped: dict[str, list[tuple[Any, ...]]]) -> dict[str, list[tuple[Any, ...]]]:
    """A dump of the file the head left, each homed table's rows read by :func:`homeless`."""
    return {
        table: homeless(table, rows) if table in HOMED else rows for table, rows in dumped.items()
    }
