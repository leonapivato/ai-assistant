"""The upgrade of an episode stored before ADR-0349 into its record (ADR-0349 §10:6).

Mechanical, with nothing dropped (ADR-0326 §4:1, §4:4): each understanding version's
``continues``, which a build before ADR-0349 stored as one activation's id or ``null``,
becomes the sequence ADR-0349 §10:2 makes it, a one-element sequence for one and an
empty one for ``null``. An understanding that records no ``continues``, as one written
before ADR-0332 added it, is left as it is, since it reads as the empty sequence.
Nothing else in the record moves.

A pure function of the stored record, so the store applies it inside its own
transaction and a test applies it to a dict. It is **idempotent**: a record already in
ADR-0349's shape comes back unchanged and reports no change.
"""

from __future__ import annotations

from typing import Any


def continuing_episode(stored: dict[str, Any]) -> bool:
    """Carry ``stored``'s understandings' ``continues`` to a sequence, in place.

    Args:
        stored: One stored record, decoded from its JSON. A record with no processing
            record, or whose understandings are not a list of objects, is left alone:
            the store's decode, which follows, judges a shape this does not know.

    Returns:
        Whether anything changed, so the store rewrites only a record that moved.
    """
    processing = stored.get("processing_record")
    if not isinstance(processing, dict):
        return False
    understanding = processing.get("understanding")
    if not isinstance(understanding, list):
        return False
    changed = False
    for version in understanding:
        if not isinstance(version, dict) or "continues" not in version:
            continue
        held = version["continues"]
        if held is None:
            version["continues"] = []
            changed = True
        elif isinstance(held, str):
            version["continues"] = [held]
            changed = True
    return changed
