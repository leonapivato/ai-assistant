"""ADR-0368 §2's carry, as an earlier upgrade's test reads a file the chain then carries.

Every memory-store upgrade chains (ADR-0326 §4:5), so a test of an earlier upgrade opens
its file with this build and the chain runs on to the three facts' upgrade, the last,
which rewrites every episode with a processing record: its trigger gains ``senders``,
each message it or a join records gains ``sender``, and the record and each joined input
gain ``facts``. :func:`without_facts` takes exactly those away, so an earlier test holds
the rest of the record to what its own upgrade did, and nothing else is let through.
"""

from __future__ import annotations

import copy
from typing import Any


def without_facts(processing: dict[str, Any]) -> dict[str, Any]:
    """A processing record as a dict, less what the three facts' upgrade added to it.

    Args:
        processing: A processing record, dumped or decoded.

    Returns:
        A new dict, without the trigger's ``senders``, any message's ``sender``, and the
        record's and each joined input's ``facts``.
    """
    held = copy.deepcopy(processing)
    held.pop("facts", None)
    trigger = held.get("trigger")
    if isinstance(trigger, dict):
        trigger.pop("senders", None)
        for message in trigger.get("messages") or []:
            message.pop("sender", None)
    for one in held.get("joined") or []:
        one.pop("facts", None)
        for message in one.get("messages") or []:
            message.pop("sender", None)
    return held


def episode_without_facts(stored: dict[str, Any]) -> dict[str, Any]:
    """A stored episode as a dict, its processing record :func:`without_facts`.

    Args:
        stored: A stored record, decoded.

    Returns:
        A new dict; a record with no processing record comes back as it was.
    """
    held = copy.deepcopy(stored)
    processing = held.get("processing_record")
    if isinstance(processing, dict):
        held["processing_record"] = without_facts(processing)
    return held
