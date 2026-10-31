"""The upgrade of an episode stored before ADR-0356 into its record (ADR-0356 §13:5).

Mechanical, with no model (ADR-0326 §4:1). A stored processing record at
``schema_version`` 11 is carried to 12, the version that gains ``call_records``, and
holds no entry: no build before ADR-0356 recorded what came of a call, so the field is
left out and reads back empty, and every other field of the record, and of the episode,
is carried whole (§13:5, ADR-0326 §4:4). No episode, memory or other record is dropped,
and no support is rewritten.

A pure function of the stored record, so the store applies it inside its own
transaction and a test applies it to a dict. It is **idempotent**: a record already at
version 12 comes back unchanged and reports no change.
"""

from __future__ import annotations

from typing import Any, Final

#: The processing record's version before ADR-0356, and the version it is carried to.
_BEFORE: Final = 11
_AFTER: Final = 12


def called_episode(stored: dict[str, Any]) -> bool:
    """Carry the processing record ``stored`` holds to ADR-0356's version, in place.

    Args:
        stored: One stored record, decoded from its JSON. A record with no processing
            record, or one at another version, is left alone: the store's decode, which
            follows, judges a shape this does not know.

    Returns:
        Whether anything changed, so the store rewrites only a record that moved.
    """
    processing = stored.get("processing_record")
    if not isinstance(processing, dict) or processing.get("schema_version") != _BEFORE:
        return False
    processing["schema_version"] = _AFTER
    return True
