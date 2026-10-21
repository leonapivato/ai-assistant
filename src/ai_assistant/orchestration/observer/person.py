"""What the observer reads and writes of the person model (ADR-0338 §9, ADR-0342 §5:6).

The observer holds the person-model store by injection (§9:8), beside what ADR-0329
§15:1 names, and only where the composition root wires one: where
``Settings.person_model`` is off, it holds none, and nothing here runs (§11:2).

**Whose episode it is** (§2:5) is read from the leaving episode's recorded trigger, by the
rule understanding's and planning's person block reads an activation's by
(:func:`~ai_assistant.orchestration.person_block.activation_person`), never from its
content. An episode that is no person's is given no fields, and nothing is written to the
person model for it.

**What both steps are given** (§7:4, §9:1): that person's five fields and nothing else of
the person model, each as the person set it or as not set (§3:9), rendered by code into
the step's data as quoted source data, never into its instruction (§7:6, ADR-0334).

**What it writes** (§9:7): only suggestions and style marks, each one call of the store,
which refuses what the contract says is unchanged — a value the profile already holds,
an equal suggestion pending or dismissed, a memory already pinned, marked or whose mark
was removed — so the observer never decides those itself. It writes no field, no pin and
no change-log entry.

**The pin pass** (§9:6) adds a ``pinned`` support (§4:4) for every pin a person made on
their own profile, removed since or not, whose memory the memory store holds, and which
no support of that memory points at yet. Each pin's memory is read through the history
read, whatever its status, and the support is added to the memory that read returned,
conditionally on the revision it returned (ADR-0342 §5:4, §5:6), by the write stage's
operation member, one add support each (ADR-0328 §11:3). It makes no model call and
counts toward no budget (ADR-0329 §16:9). A write that fails is left for the next run,
which tries it again: the pass is a query over what the two stores hold, never a queue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import MemoryStoreError, PersonModelStoreError
from ai_assistant.core.types import (
    MemoryChange,
    MemoryOperation,
    MemoryOperationKind,
    MemorySupport,
    MemoryWriterName,
    PinPart,
    ProfileField,
    ReadingCertainty,
    SupportDirection,
    SupportOrigin,
)
from ai_assistant.orchestration.person_block import activation_person

if TYPE_CHECKING:
    from collections.abc import Callable, Collection
    from datetime import datetime

    from ai_assistant.core.protocols import MemoryStore, PersonModelStore
    from ai_assistant.core.types import EpisodicMemory, FrozenJson, Memory, Pin, Profile
    from ai_assistant.orchestration.writes import MemoryWriteStage

__all__ = ["PIN_NOTE", "PersonFields", "PinConfirmations", "person_of", "pinned_support"]

_log = structlog.get_logger(__name__)

#: Why a pin's support was added, on the support and its add support: code-owned words.
PIN_NOTE: Final = "the user pinned this memory on their own profile, confirming its wording"


@dataclass(frozen=True, slots=True)
class PersonFields:
    """The five fields of a leaving episode's person, as the store read them (§7:4).

    Attributes:
        person_id: Whose.
        profile: Their five fields, each set or not.
    """

    person_id: str
    profile: Profile

    def rendered(self) -> dict[str, FrozenJson]:
        """The fields as both steps are shown them: each value, or ``None`` where not set.

        An empty field is shown as not set, never as a default presented as the person's
        own (§3:9): an empty assistant's name is ``None`` here, not ``Aether``.
        """
        return {one.value: self.profile.value(one) for one in ProfileField}


async def person_of(store: PersonModelStore, episode: EpisodicMemory) -> PersonFields | None:
    """The fields of the person ``episode`` is for, or ``None`` where it is no person's.

    Args:
        store: The person-model store.
        episode: The leaving episode, as stored.

    Returns:
        The person's fields; ``None`` where the episode's recorded trigger makes it no
        person's (§2:5), or the store holds no such person.

    Raises:
        PersonModelStoreError: If the store cannot be read: the attempt fails and is
            retried, so no step decides without the fields it is owed (§9:3).
    """
    processing = episode.processing_record
    person_id = activation_person(None if processing is None else processing.trigger)
    if person_id is None:
        return None
    model = await store.read(person_id)
    if model is None:
        return None
    return PersonFields(person_id=person_id, profile=model.profile)


def pinned_support(pin: Pin, *, at: datetime) -> MemorySupport:
    """The support a pin earns its memory (ADR-0338 §4:3-§4:4).

    ``for``, backing the memory as worded and ``sure``; its ``when`` the instant the pin
    was made, with no about-when and no source details; added by the observer (§4:6).

    Args:
        pin: The pin, as the person-model store holds it.
        at: When the support is added.

    Returns:
        The support.
    """
    return MemorySupport(
        points_at=PinPart(pin=pin.id),
        origin=SupportOrigin.PINNED,
        direction=SupportDirection.FOR,
        note=PIN_NOTE,
        backs_as_worded=True,
        how_sure=ReadingCertainty.SURE,
        when=pin.pinned_at,
        added_at=at,
        added_by=MemoryWriterName.OBSERVER,
    )


def _own(pin: Pin) -> bool:
    """Whether the person made the pin on their own profile (§4:3): it confirms."""
    return pin.act.by == pin.person_id


class PinConfirmations:
    """The pin pass (§9:6), and the retirement guard's run of it on one memory (§9:9)."""

    def __init__(
        self,
        *,
        people: PersonModelStore,
        memory: MemoryStore,
        writes: MemoryWriteStage,
        now: Callable[[], datetime],
    ) -> None:
        """Wire the pass.

        Args:
            people: The person-model store the pins are read from.
            memory: The memory store each pin's memory is read from, through the
                history read.
            writes: The write stage every support is added through (ADR-0329 §12:1).
            now: The clock each support and operation is stamped from.
        """
        self._people = people
        self._memory = memory
        self._writes = writes
        self._now = now

    async def confirm(self, memory_ids: Collection[str] | None = None) -> dict[str, int]:
        """Add the ``pinned`` support every own pin lacks, on ``memory_ids`` or on all.

        Every pin is read from the store's export, which carries every person's pins,
        removed ones included (§10:5), so the store holds each pin the pass adds a
        support for when it reads it (§4:5). A memory's pins are added in the order made,
        each conditionally on the revision the history read last returned for it.

        Args:
            memory_ids: The memories whose pins to confirm, for the retirement guard
                (§9:9); every pinned memory where ``None``, for the run's pass (§9:6).

        Returns:
            How many supports were added, by memory. A write that failed is left out,
            and a later run tries it again.

        Raises:
            PersonModelStoreError: If the pins cannot be read.
            MemoryStoreError: If the history read fails.
        """
        export = await self._people.export()
        pins = [
            pin
            for pin in export.pins
            if _own(pin) and (memory_ids is None or pin.memory_id in memory_ids)
        ]
        if not pins:
            return {}
        held = await self._memory.get_history(list(dict.fromkeys(pin.memory_id for pin in pins)))
        added: dict[str, int] = {}
        for memory_id, current in held.items():
            mine = [pin for pin in pins if pin.memory_id == memory_id]
            count = await self._confirmed(current, mine)
            if count:
                added[memory_id] = count
        return added

    async def _confirmed(self, held: Memory, pins: list[Pin]) -> int:
        """Add each of ``pins``' missing supports to one memory; how many were added.

        ``held`` is the memory as the history read returned it, whatever its status; after
        each support lands it is read again the same way, so the next is added on the
        revision the store then holds (ADR-0342 §5:6).
        """
        added = 0
        current: Memory | None = held
        for pin in pins:
            part = PinPart(pin=pin.id)
            if current is None:
                return added  # forgotten since: a pin on it is shown nowhere (§4:10)
            if current.support_at(part) is not None:
                continue
            now = self._now()
            change = MemoryChange(
                memory=current,
                operation=MemoryOperation(
                    kind=MemoryOperationKind.ADD_SUPPORT,
                    cites=part,
                    note=PIN_NOTE,
                    at=now,
                    by=MemoryWriterName.OBSERVER,
                ),
                support=pinned_support(pin, at=now),
            )
            try:
                await self._writes.apply(change)
            except MemoryStoreError as exc:
                # §9:6: tried again on the next run. Logged with a code-owned reason only
                # (ADR-0329 §15:7): never the memory, the pin or the wording.
                _log.info("observer_pins", stage="pin", result="not_written", reason=_named(exc))
                return added
            added += 1
            current = (await self._memory.get_history([held.id])).get(held.id)
        return added

    async def run_pass(self) -> int:
        """The run's pin pass, before its episodes (§9:6): how many supports it added.

        A store that cannot be read leaves every pin for the next run.
        """
        try:
            added = await self.confirm()
        except (PersonModelStoreError, MemoryStoreError) as exc:
            _log.info("observer_pins", stage="pass", result="not_read", reason=_named(exc))
            return 0
        total = sum(added.values())
        if total:
            _log.info("observer_pins", stage="pass", result="added", supports=total)
        return total


def _named(exc: Exception) -> str:
    """A failure's code-owned name: its class, never its message (ADR-0329 §15:7)."""
    return type(exc).__name__
