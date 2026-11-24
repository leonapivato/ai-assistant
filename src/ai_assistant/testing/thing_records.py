"""A canonical :class:`~ai_assistant.core.protocols.ThingRecordStore` fake (ADR-0381 §3).

The shared test double for the records of whose each connection and source is, so the
lanes that read one (ADR-0381 §6: the card for a grant that asks, and the Connections
section's filter) can exercise a thing with a record, one with none and a store that
fails, without a file. It keeps everything in memory and follows the contract's every
rule, so a consumer's test sees what the store would do.

**It starts empty**, unless built with ``held``, which records each of those things as
the owner's at one reading of the clock, as the hub's start does (§4:1).

**What only a test can ask of it.** :meth:`FakeThingRecordStore.fail_next` makes the next
member called raise :class:`~ai_assistant.core.errors.ThingRecordStoreError` before it
reads or writes anything, as a store fault would, which ADR-0381 §5:1 has a reader read as
no record.

Every member runs to its end without awaiting, so on one event loop each is one
indivisible step, which is the exclusion the contract asks of it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, final

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ThingRecordStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ThingKey,
    ThingRecord,
    ThingRecording,
    ThingRecordingKind,
    describe_untrusted,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ["FakeThingRecordStore"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _key(value: object) -> ThingKey:
    """``value`` as a ``ThingKey`` whose every field passes validation, or a ``ValueError``.

    An instance is not proof of its own validity: ``model_copy(update=…)`` and
    ``model_construct`` skip validation, so the instance's contents are validated again.
    """
    if not isinstance(value, ThingKey):
        msg = f"key must be a ThingKey, got {describe_untrusted(value)}"
        raise ValueError(msg)
    try:
        return ThingKey.model_validate(value.model_dump())
    except ValidationError as exc:
        msg = "key is not a valid ThingKey"
        raise ValueError(msg) from exc


def _person(value: object) -> str:
    """The owner's identity, or a ``ValueError`` before anything is read (ADR-0381 §3:3)."""
    if value != OWNER_PERSON_ID:
        msg = (
            "in this milestone a record names the owner's identity alone (ADR-0381 §3:3), "
            f"got {describe_untrusted(value)}"
        )
        raise ValueError(msg)
    return OWNER_PERSON_ID


@final
class FakeThingRecordStore:
    """An in-memory store of whose each thing is (ADR-0381 §3)."""

    def __init__(
        self,
        *,
        held: Sequence[ThingKey] = (),
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Build the store, recording each of ``held`` as the owner's.

        Args:
            held: Things to record as the owner's as the store is built, in the order
                given, at one reading of the clock, as the hub's start does (§4:1); none
                by default.
            now: The clock every instant the store records is read from.

        Raises:
            ValueError: If an entry of ``held`` is not a valid ``ThingKey``.
            ThingRecordStoreError: If ``held`` names a thing and the clock's reading is
                not an aware instant.
        """
        keys = tuple(_key(one) for one in held)
        # ADR-0026 §2: every reading aware and converted to UTC, checked where it is read.
        self._clock = checked_clock(now, owner="FakeThingRecordStore")
        self._records: dict[ThingKey, ThingRecord] = {}
        self._fail = False
        if keys:
            at = self._now()
            for key in keys:
                self._records.setdefault(
                    key, ThingRecord(key=key, person=OWNER_PERSON_ID, recorded_at=at)
                )

    def fail_next(self) -> None:
        """Make the next member called raise ``ThingRecordStoreError``, touching nothing."""
        self._fail = True

    def _fault(self) -> None:
        if self._fail:
            self._fail = False
            msg = "the fake thing record store was told to fail"
            raise ThingRecordStoreError(msg)

    def _now(self) -> datetime:
        """One reading of the clock, taken before the write it dates changes anything.

        Raises:
            ThingRecordStoreError: If the reading is not an aware instant (ADR-0026 §4).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = f"the thing record store cannot record its clock's reading: {exc}"
            raise ThingRecordStoreError(msg) from exc

    async def whose(self, key: ThingKey) -> ThingRecord | None:
        """Read the record of the thing ``key`` names, or ``None`` where it has none.

        Raises:
            ValueError: If ``key`` is malformed.
            ThingRecordStoreError: If told to fail.
        """
        held = _key(key)
        self._fault()
        return self._records.get(held)

    async def record_whose(self, key: ThingKey, *, person: str) -> ThingRecording:
        """Record that ``key``'s thing is ``person``'s, where no record stands.

        Raises:
            ValueError: If an argument is malformed, or ``person`` is not the owner's.
            ThingRecordStoreError: If told to fail, or the clock's reading is not an aware
                instant; nothing is changed.
        """
        held = _key(key)
        whose = _person(person)
        self._fault()
        standing = self._records.get(held)
        if standing is not None:
            return ThingRecording(kind=ThingRecordingKind.ALREADY_RECORDED, record=standing)
        record = ThingRecord(key=held, person=whose, recorded_at=self._now())
        self._records[held] = record
        return ThingRecording(kind=ThingRecordingKind.RECORDED, record=record)

    async def export(self) -> tuple[ThingRecord, ...]:
        """Every record, in the order recorded.

        Raises:
            ThingRecordStoreError: If told to fail.
        """
        self._fault()
        return tuple(self._records.values())
