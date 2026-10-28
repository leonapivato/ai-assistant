"""ADR-0351 §9's carry, as an earlier upgrade's test reads a file the chain then carries.

Every memory-store upgrade chains (ADR-0326 §4:5), so a test of an earlier upgrade opens
its file with this build and the chain runs on to ADR-0351 §9's, which rewrites each
episode whose trigger records an ``origin``. These say what that rewrite does to what
was stored, stated here on its own rather than read off the upgrade, so an earlier test
holds the store to it: the trigger's ``origin`` is computed from its parties and stored
nowhere (§10:2), and nothing else that was stored moves. What the rewrite adds, the
parties and each message's party, an earlier test reads as a field added; ADR-0351's own
upgrade test holds what they are.
"""

from __future__ import annotations

import copy
import json
from typing import Any


def origin_recorded(data: str) -> bool:
    """Whether a stored row's trigger records ``origin``, so the chain rewrites it.

    Args:
        data: The row's stored blob.

    Returns:
        Whether its processing record's trigger holds the key.
    """
    stored = json.loads(data)
    processing = stored.get("processing_record") if isinstance(stored, dict) else None
    trigger = processing.get("trigger") if isinstance(processing, dict) else None
    return isinstance(trigger, dict) and "origin" in trigger


def holds(read: object, written: object) -> None:
    """``read`` holds everything ``written`` held, unchanged, and may add fields to it.

    Args:
        read: What the store reads back, as JSON.
        written: What was stored, carried, as JSON.
    """
    if isinstance(written, dict):
        assert isinstance(read, dict)
        for key, value in written.items():
            assert key in read, key
            holds(read[key], value)
    elif isinstance(written, list):
        assert isinstance(read, list)
        assert len(read) == len(written)
        for one, other in zip(read, written, strict=True):
            holds(one, other)
    else:
        assert read == written


def parties_carried(stored: dict[str, Any]) -> dict[str, Any]:
    """``stored`` as ADR-0351 §9's upgrade leaves what it stored, as a new dict.

    Args:
        stored: A stored record, decoded.

    Returns:
        A copy whose trigger holds no ``origin``.
    """
    result = copy.deepcopy(stored)
    processing = result.get("processing_record")
    trigger = processing.get("trigger") if isinstance(processing, dict) else None
    if isinstance(trigger, dict):
        trigger.pop("origin", None)
    return result
