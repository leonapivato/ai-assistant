"""ADR-0349 §10:6's carry, as an earlier upgrade's test reads a file the chain then carries.

Every memory-store upgrade chains (ADR-0326 §4:5), so a test of an earlier upgrade opens
its file with this build and the chain runs on to ADR-0349 §10:6's, which rewrites each
episode whose understandings record ``continues``. These say what that rewrite does,
stated here on its own rather than read off the upgrade, so an earlier test holds the
store to it: one id becomes a one-element sequence, ``null`` an empty one, and nothing
else in the episode moves.
"""

from __future__ import annotations

import copy
import json
from typing import Any


def continues_recorded(data: str) -> bool:
    """Whether a stored row's understandings record ``continues``, so the chain rewrites it.

    Args:
        data: The row's stored blob.

    Returns:
        Whether any understanding version of its processing record holds the key.
    """
    stored = json.loads(data)
    processing = stored.get("processing_record") if isinstance(stored, dict) else None
    versions = processing.get("understanding") if isinstance(processing, dict) else None
    return isinstance(versions, list) and any(
        isinstance(one, dict) and "continues" in one for one in versions
    )


def carried(stored: dict[str, Any]) -> dict[str, Any]:
    """``stored`` as ADR-0349 §10:6's upgrade carries it, as a new dict.

    Args:
        stored: A stored record, decoded.

    Returns:
        A copy whose understandings' ``continues`` are sequences.
    """
    result = copy.deepcopy(stored)
    processing = result.get("processing_record")
    versions = processing.get("understanding") if isinstance(processing, dict) else None
    for version in versions if isinstance(versions, list) else ():
        if isinstance(version, dict) and "continues" in version:
            held = version["continues"]
            version["continues"] = [] if held is None else [held]
    return result
