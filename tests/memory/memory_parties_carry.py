"""ADR-0351 §9's carry, as an earlier upgrade's test reads a file the chain then carries.

Every memory-store upgrade chains (ADR-0326 §4:5), so a test of an earlier upgrade opens
its file with this build and the chain runs on to ADR-0351 §9's, which rewrites each
episode whose trigger records an ``origin``. These say what that rewrite does to what
was stored, stated here on its own rather than read off the upgrade, so an earlier test
holds the store to it: the trigger's ``origin`` is computed from its parties and stored
nowhere (§10:2), and nothing else that was stored moves. What the rewrite adds, the
parties and each message's party, an earlier test reads as a field added; ADR-0351's own
upgrade test holds what they are.

The chain runs on past it to ADR-0353 §9:6's, which rewrites each understanding version
holding a retired field: :func:`parties_carried` carries that too, stated here on its own
in the same way, so every earlier upgrade's test reads what the whole chain leaves.
ADR-0353's own upgrade test holds that rewrite field by field. And it ends in ADR-0356
§13:5's, which carries every processing record to version 12: :func:`parties_carried`
carries that too, and :func:`calls_carried` says which rows it rewrites.
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


#: ADR-0353 §9:5's retired fields, which its upgrade drops from every stored version.
_RETIRED = ("meaning_ground", "references", "relationships", "unresolved", "answers")


def parties_carried(stored: dict[str, Any]) -> dict[str, Any]:
    """``stored`` as ADR-0351 §9's upgrade, and ADR-0353 §9:6's after it, leave it.

    Args:
        stored: A stored record, decoded.

    Returns:
        A copy whose trigger holds no ``origin``, and each of whose understanding
        versions holds no retired field, its references' and relationships' referents
        added to its ``meaning_referents`` after its own, each once.
    """
    result = copy.deepcopy(stored)
    processing = result.get("processing_record")
    trigger = processing.get("trigger") if isinstance(processing, dict) else None
    if isinstance(trigger, dict):
        trigger.pop("origin", None)
    versions = processing.get("understanding") if isinstance(processing, dict) else None
    for version in versions if isinstance(versions, list) else []:
        held = list(version.get("meaning_referents", []))
        for name in ("references", "relationships"):
            for one in version.get(name, []):
                held.extend(r for r in one.get("referents", []) if r not in held)
        for name in _RETIRED:
            version.pop(name, None)
        version["meaning_referents"] = held
    # ADR-0356 §13:5: the chain ends in carrying every processing record to version 12.
    if isinstance(processing, dict) and processing.get("schema_version") == _BEFORE_CALLS:
        processing["schema_version"] = _AFTER_CALLS
    return result


#: The processing record's version before ADR-0356 §13:5's upgrade, and after it.
_BEFORE_CALLS = 11
_AFTER_CALLS = 12


def calls_carried(data: str) -> bool:
    """Whether ADR-0356 §13:5's upgrade, at the chain's end, rewrites a stored row.

    It carries every processing record at version 11 to 12, so it rewrites every episode
    that has one.

    Args:
        data: The row's stored blob.

    Returns:
        Whether its processing record is at version 11.
    """
    stored = json.loads(data)
    processing = stored.get("processing_record") if isinstance(stored, dict) else None
    return isinstance(processing, dict) and processing.get("schema_version") == _BEFORE_CALLS
