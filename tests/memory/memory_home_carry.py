"""ADR-0383 §5:1's carry, as an earlier upgrade's test reads a file the chain then carries.

Every memory-store upgrade chains (ADR-0326 §4:5), so a test of an earlier upgrade opens
its file with this build and the chain runs on to the home's upgrade, which writes the
owner's domain into every record the file holds and moves nothing else: a row no earlier
upgrade rewrote keeps every byte, with ``"home"`` set last. :func:`homed` is that row, and
:func:`without_home` takes the home away from a decoded record, so an earlier test holds
the rest of the record to what its own upgrade did, and nothing else is let through.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Final

from ai_assistant.core.types import RecordHome

#: The owner's domain as a stored record carries it (ADR-0383 §5:1).
OWNERS_HOME: Final[dict[str, Any]] = RecordHome.owners().model_dump(mode="json")


def homed(data: str) -> str:
    """A stored row's JSON as the home's upgrade leaves a row it rewrites nothing else of.

    Args:
        data: The row's JSON as an earlier build stored it.

    Returns:
        The same bytes, with the owner's home set as the record's last member.
    """
    assert data.endswith("}"), data
    return data[:-1] + ',"home":' + json.dumps(OWNERS_HOME, separators=(",", ":")) + "}"


def without_home(stored: dict[str, Any]) -> dict[str, Any]:
    """A decoded record less its home, which must be the owner's domain.

    Args:
        stored: A stored or read-back record, as a dict.

    Returns:
        A new dict without ``home``.
    """
    held = copy.deepcopy(stored)
    assert held.pop("home") == OWNERS_HOME, stored
    return held


def homed_row[T: tuple[object, ...]](row: T) -> T:
    """A raw row ``(kind, data, ...)`` read out of band, its ``data`` :func:`homed`.

    Args:
        row: The row as an earlier build stored it, its JSON at index 1.

    Returns:
        The row as the home's upgrade leaves it, every other column the same.
    """
    data = row[1]
    assert isinstance(data, str), row
    return type(row)((row[0], homed(data), *row[2:]))
