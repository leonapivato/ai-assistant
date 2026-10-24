"""The upgrade of a memory stored before ADR-0345 into its record (ADR-0345 §13).

Mechanical, with no model and nothing dropped (ADR-0326 §4:1): every support gains the
holder ADR-0345 §2's table gives it, from the record it points at as the store holds it
(§13:1), or from its origin alone where that record is gone (§13:2); ``about_person``
becomes ``subjects`` holding that one name, or ``None`` where it named none, with
``involved`` ``None`` either way; each topic becomes a situation label added by
``migration`` (§10:2); and the memory gains no other label and no mark. Every support
keeps its direction and whether it backs the claim as worded (§13:4), so a support the
upgrade gives the assistant's statement as its holder keeps backing what it backed.

A pure function of the stored record and the episodes it reads, so the store applies it
inside its own transaction and a test applies it to a dict. It is **idempotent**: a
record already in ADR-0345's shape, as one ADR-0328 §16's upgrade writes on this build,
comes back as it went in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ai_assistant.core.types import (
    Memory,
    MemorySupport,
    MemoryWriterName,
    SituationLabel,
    part_episode,
    support_holder,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import datetime

    from ai_assistant.core.types import EpisodicMemory

__all__ = ["placed_memory", "topic_labels"]


def topic_labels(topics: object, *, now: datetime) -> list[SituationLabel]:
    """The situation labels a record's topics become (ADR-0345 §10:2).

    Each topic, in its stored order, as a label added by ``migration`` at the upgrade's
    instant and suggested by no episode.

    Args:
        topics: The record's stored ``topics``, or anything else where it held none.
        now: The upgrade's instant.

    Returns:
        The labels.
    """
    if not isinstance(topics, list | tuple):
        return []
    return [
        SituationLabel(text=str(topic), added_at=now, added_by=MemoryWriterName.MIGRATION)
        for topic in topics
    ]


def placed_memory(
    record: Mapping[str, Any],
    *,
    episode: Callable[[str], EpisodicMemory | None],
    now: datetime,
) -> Memory:
    """The memory one stored record becomes under ADR-0345 (§13).

    Args:
        record: The memory exactly as it was stored, decoded from its JSON blob.
        episode: The episode the store holds at an id, or ``None`` where it holds none.
        now: The upgrade's instant, at which a carried topic is added as a label.

    Returns:
        The memory, its supports each carrying a holder, its subject carried over, and
        its topics carried as labels.

    Raises:
        ValueError: If the record does not decode as a memory once upgraded.
    """
    upgraded = dict(record)
    about = upgraded.pop("about_person", None)
    topics = upgraded.pop("topics", None)
    if "subjects" not in upgraded:
        upgraded["subjects"] = None if about is None else [about]
    upgraded.setdefault("involved", None)
    labels = list(upgraded.get("labels") or [])
    carried = {str(label["text"]) if isinstance(label, dict) else label.text for label in labels}
    labels.extend(label for label in topic_labels(topics, now=now) if label.text not in carried)
    upgraded["labels"] = labels
    upgraded.setdefault("marks", [])
    supports = []
    for stored in upgraded.get("supports") or ():
        support = MemorySupport.model_validate(stored)
        if support.holder is None:
            address = part_episode(support.points_at)
            held = None if address is None else episode(address)
            support = support.model_copy(update={"holder": support_holder(support, held)})
        supports.append(support)
    upgraded["supports"] = supports
    return Memory.model_validate(upgraded)
