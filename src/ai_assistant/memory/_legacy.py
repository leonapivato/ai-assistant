"""The upgrade of a record stored before ADR-0328 into a memory (ADR-0328 §16).

One pure function, :func:`memory_from_legacy`, applies §16's table to one stored
semantic, preference or procedural record: the memory keeps the record's id, its
envelope fields, and one legacy support carrying the record whole as it was stored;
its create is dated at the record's ``last_updated``; and a record whose validity end
is at or before the upgrade's instant is ended there. No model, and nothing dropped
(§16:1, ADR-0326 §4:4).

Kept apart from the store that calls it, so the store's upgrade and the test that
upgrades a file the previous release wrote read the same table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from ai_assistant.core.types import (
    LegacyPart,
    Memory,
    MemoryOperation,
    MemoryOperationKind,
    MemoryStatus,
    MemorySupport,
    MemoryWriterName,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    SupportDirection,
    SupportOrigin,
    rests_on_recorded_external_content,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import datetime

#: The kinds §16 upgrades. An episode is unchanged (§16's table, §16:7).
LEGACY_KINDS: Final = frozenset({"semantic", "preference", "procedural"})

#: The legacy support's note, in words (§4:1).
LEGACY_NOTE: Final = "carried over whole from the record stored before ADR-0328"


def legacy_wording(record: Mapping[str, Any]) -> str:
    """A memory's wording from a stored record (ADR-0328 §16:3).

    The record's ``content``, followed, for a preference record carrying a ``context``,
    by `` (context: `` + its context + ``)``, and, for a procedural record carrying
    steps, by `` Steps: `` + its steps in order, each preceded by its number, a full
    stop and a space, joined by ``; ``. A preference's ``strength`` is a number, which
    no wording carries; it stays on the legacy support alone.

    Args:
        record: The record as it was stored.

    Returns:
        The wording.
    """
    wording = str(record["content"])
    context = record.get("context")
    if record.get("kind") == "preference" and context:
        wording += f" (context: {context})"
    steps = record.get("steps") or ()
    if record.get("kind") == "procedural" and steps:
        numbered = "; ".join(f"{number}. {step}" for number, step in enumerate(steps, 1))
        wording += f" Steps: {numbered}"
    return wording


def _placement(record: Mapping[str, Any]) -> Placement:
    """The record's placement, as its envelope decoded it (ADR-0217 §9)."""
    stored = record.get("placement")
    if stored is not None:
        return Placement.model_validate(stored)
    provenance = record.get("provenance") or {}
    if provenance.get("supplied_withheld_content", False):
        return Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)
    return Placement()


def legacy_support_when(
    provenance: Provenance, occurred_at: Callable[[str], datetime | None]
) -> datetime | None:
    """A legacy support's ``when`` (ADR-0328 §16:5).

    The latest ``occurred_at`` among the episodes the store holds that the record's
    ``evidence`` names; the record's ``last_confirmed_at`` where it names none the store
    holds; and unknown where neither is set.

    Args:
        provenance: The record's provenance, as stored.
        occurred_at: The ``occurred_at`` of the episode the store holds at an id, or
            ``None`` where it holds none there.

    Returns:
        The instant, or ``None`` for unknown.
    """
    held = [instant for cited in provenance.evidence if (instant := occurred_at(cited)) is not None]
    if held:
        return max(held)
    return provenance.last_confirmed_at


def memory_from_legacy(
    record: Mapping[str, Any],
    *,
    occurred_at: Callable[[str], datetime | None],
    now: datetime,
) -> Memory:
    """The memory one stored semantic, preference or procedural record becomes (§16).

    Args:
        record: The record exactly as it was stored, decoded from its JSON blob.
        occurred_at: The ``occurred_at`` of the episode the store holds at an id, or
            ``None`` where it holds none there.
        now: The upgrade's instant.

    Returns:
        The memory at the record's id, carrying its ``validity``, ``placement``,
        ``expires_at``, ``about_person`` and ``topics`` unchanged (§16:2), its wording
        (§16:3), one legacy support carrying the record whole (§16:4, §16:5), a create
        by ``migration`` at the record's ``last_updated``, and an end at its validity end
        where that is at or before ``now`` (§16:6).

    Raises:
        ValueError: If the record is not one §16 upgrades, or does not decode.
    """
    if record.get("kind") not in LEGACY_KINDS:
        msg = f"a {record.get('kind')!r} record is not one ADR-0328 §16 upgrades"
        raise ValueError(msg)
    provenance = Provenance.model_validate(record["provenance"])
    outside = rests_on_recorded_external_content(provenance)
    part = LegacyPart(record=str(record["id"]))
    support = MemorySupport(
        points_at=part,
        origin=SupportOrigin.LEGACY_OUTSIDE if outside else SupportOrigin.LEGACY,
        direction=SupportDirection.FOR,
        note=LEGACY_NOTE,
        backs_as_worded=True,
        when=legacy_support_when(provenance, occurred_at),
        source_details=provenance.attestation,
        added_at=now,
        added_by=MemoryWriterName.MIGRATION,
        carries=dict(record),
    )
    operations = [
        MemoryOperation(
            kind=MemoryOperationKind.CREATE,
            cites=part,
            note=LEGACY_NOTE,
            at=provenance.last_updated,
            by=MemoryWriterName.MIGRATION,
        )
    ]
    envelope = {
        key: record[key]
        for key in ("validity", "expires_at", "about_person", "topics")
        if key in record
    }
    memory = Memory.model_validate(
        {
            **envelope,
            "id": record["id"],
            "content": legacy_wording(record),
            "placement": _placement(record),
            "supports": (support,),
            "operations": tuple(operations),
        }
    )
    end = memory.validity.valid_until
    if end is None or end > now:
        return memory
    operations.append(
        MemoryOperation(
            kind=MemoryOperationKind.END,
            cites=part,
            note="its validity had ended before the upgrade",
            at=end,
            by=MemoryWriterName.MIGRATION,
        )
    )
    return Memory.model_validate(
        memory.model_dump() | {"operations": tuple(operations), "status": MemoryStatus.ENDED}
    )
