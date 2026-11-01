"""The person block: who an activation is for, and what the models are shown of them.

ADR-0338 §2, §6 and §7, built against :class:`~ai_assistant.core.protocols.PersonModelStore`
and the memory store, with no model call. This module decides *what* the block holds;
understanding and planning each render it into their own data (§7:6), so neither phase
module reads a store for it.

**Whose activation it is** (§2:2-§2:4) is read from the recorded trigger and never from
its content (ADR-0292 §5:8): the owner's where its place's kind establishes the user as
its author (ADR-0292 §5:4, the line's forwards included, since a forward is its
forwarder's input), or where it was pushed by a source on a channel the owner connected
(ADR-0292 §6:3); no person's otherwise. A reminder or timer the user set is the owner's
too (§2:2), and no kind of one stands on this tree yet, so the register names none: the
kind that brings one adds it here.

**What the block holds** (§6, §7:1, §7:9). The person's five fields; the kept-in-mind
slot — their pinned memories, oldest pin first, then the memories marked as how they
want to be spoken to, the most recently marked first, each memory once, a pin or mark
showing its chain's current end alone (§4:8, §5:3; ADR-0342 §5:2-§5:5), never a retired
memory as current (ADR-0342 §5:1) — within a character budget
over the wordings it shows, stopping before the first that would exceed it and counting
what it left out (§6:1-§6:2); and their pending suggestions that rest on no outside
content, newest first, up to a count, a pin suggestion's memory only where it is
current. No memory resting on outside content enters the slot (§6:4), and the record
rule (ADR-0217 §2) is applied to the slot's memories and a pin suggestion's, here, as
:func:`~ai_assistant.orchestration.disclosure.admitted_to_understanding` applies it to
recall's records (§6:5). A pin or mark whose memory the store no longer holds is shown
nowhere (§4:10).

**A chain is walked live read first** (ADR-0342 §5:3). At each memory, a live read
(``get_many``) that returns it current ends the walk there, at the chain's current end;
only where it does not is the memory read through the history read (``get_history``),
after that live read, and the walk goes on to the successor the latest operation naming
one names (§5:2). The history read only says where to look next: whether a memory is
current is the live read's answer alone (ADR-0342 §4:4, §5:1).

**Once per activation, before understanding** (§7:1), and the same block reaches every
planning round, less what :func:`still_held` drops before each one: a memory the memory
store no longer holds (§7:10), which is one the history read no longer returns
(ADR-0342 §5:4).

**A store that cannot be read gives no block**, and the activation goes on without one:
the fault is logged under a fixed event name with a code-owned reason, and never a
field's value or a memory's words (ADR-0275 §8).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from ai_assistant.core.channel_validation import APPROVALS, TASK_SCHEDULER, establishes_the_user
from ai_assistant.core.errors import MemoryStoreError, PersonModelStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ChannelIdentity,
    Memory,
    MemoryStatus,
    PersonModelWriteKind,
    SuggestionKind,
)
from ai_assistant.orchestration.disclosure import admitted_to_understanding

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from datetime import datetime

    from ai_assistant.core.protocols import MemoryStore, PersonModelStore
    from ai_assistant.core.types import (
        MemoryRecord,
        PersonModel,
        PersonModelAct,
        PersonModelWrite,
        PersonSuggestion,
        Pin,
        Profile,
        ProfileField,
        RecordedChannelTrigger,
        StyleMark,
    )
    from ai_assistant.orchestration.disclosure import TurnSupply

__all__ = [
    "KEPT_IN_MIND_CHARS",
    "PLANNING_SUGGESTIONS",
    "KeptInMind",
    "PersonBlock",
    "PersonBlocks",
    "PinRefusal",
    "Pinned",
    "ShownSuggestion",
    "Unpinned",
    "activation_person",
    "person_zone",
    "still_held",
]

_log = structlog.get_logger(__name__)

#: ADR-0338 §6:1's budget: the kept-in-mind slot's character bound, measured over the
#: wordings it shows, about 400 tokens. A composition-root constant: the root hands it to
#: :class:`PersonBlocks`.
KEPT_IN_MIND_CHARS: Final = 1600

#: ADR-0338 §7:3's count: how many pending suggestions planning is shown at most, newest
#: first. A composition-root constant, handed to :class:`PersonBlocks`.
PLANNING_SUGGESTIONS: Final = 5

#: The channel kinds whose input is pushed by a source on a channel the owner connected
#: (ADR-0338 §2:2's third limb, ADR-0292 §6:3): an informational event, which a source
#: pushes on a channel that exists because it is built in or the user connected it.
_PUSHED_BY_A_CONNECTED_SOURCE: Final = frozenset({"informational_event"})

#: ADR-0350 §6:4, the addition to ADR-0338 §2:2: an activation the Task Scheduler starts is
#: for the person its task is for, and a task is for the person its spawner was (§3:5).
#: Every activation that is a person's is the owner's (the hub serves one person), so a
#: task's activation is the owner's; a household's people would need the trigger to name
#: its task's person (ADR-0350 §14, #691). An approval's activation is for its request's
#: person (ADR-0361 §6:1), today the owner, by the same reading.
_FOR_ITS_TASKS_PERSON: Final = frozenset({TASK_SCHEDULER, APPROVALS})


def activation_person(trigger: RecordedChannelTrigger | None) -> str | None:
    """The person an activation is for, from its recorded trigger (ADR-0338 §2:2-§2:4).

    Args:
        trigger: The activation's recorded trigger, or ``None`` for a pass no channel
            admitted.

    Returns:
        :data:`~ai_assistant.core.types.OWNER_PERSON_ID` where the activation is the
        owner's, and ``None`` where it is no person's.
    """
    if trigger is None:
        return None
    channel = trigger.channel
    target = trigger.target
    if channel is not None:
        kind = channel.channel_type
    elif isinstance(target, ChannelIdentity):
        kind = target.channel_type
    else:
        # A new conversation: a ``conversation`` channel not yet allocated (ADR-0284 §2:2).
        kind = "conversation"
    if (
        establishes_the_user(kind)
        or kind in _PUSHED_BY_A_CONNECTED_SOURCE
        or kind in _FOR_ITS_TASKS_PERSON
    ):
        return OWNER_PERSON_ID
    return None


def person_zone(profile: Profile | None, *, stage: str) -> ZoneInfo | None:
    """The person's own zone, or ``None`` where ``Settings.timezone`` governs (ADR-0338 §3:6).

    The one reading of a profile's zone, for every read of time code makes for a person:
    planning's current time (ADR-0307 §6:1) and the quiet windows (ADR-0130 §6:4). Each
    caller holds the hub's default and uses it where this answers ``None``: where the
    profile sets no zone, or there is no profile to read, as for an activation that is no
    person's (§2:3). The store validates a zone on every write (§3:2), so one that does
    not resolve is a store's defect: it is logged under a fixed event name, never with
    the value, and the hub's zone governs.

    Args:
        profile: The person's profile, or ``None`` where there is none to read.
        stage: The caller, named in the log entry of a zone that does not resolve.

    Returns:
        The person's zone; ``None`` where the hub's default governs.
    """
    held = None if profile is None else profile.time_zone
    if held is None:
        return None
    try:
        return ZoneInfo(held)
    except ZoneInfoNotFoundError, ValueError:
        _log.warning("person_zone_unresolved", stage=stage, reason="person_zone")
        return None


@dataclass(frozen=True, slots=True)
class KeptInMind:
    """One memory of the kept-in-mind slot, and why it is there (ADR-0338 §6:2).

    Attributes:
        memory: The memory shown: the pinned or marked one, or the current successor
            its chain reached (§4:8).
        pinned: ``True`` for a pinned memory, ``False`` for a style memory.
    """

    memory: Memory
    pinned: bool


@dataclass(frozen=True, slots=True)
class ShownSuggestion:
    """A pending suggestion planning is shown (ADR-0338 §7:3, §7:9).

    Attributes:
        kind: What it proposes.
        field: A field suggestion's field.
        value: A field suggestion's value.
        memory: A pin suggestion's memory, as the memory store holds it.
        recorded_at: When it was recorded.
    """

    kind: SuggestionKind
    recorded_at: datetime
    field: ProfileField | None = None
    value: str | None = None
    memory: Memory | None = None


@dataclass(frozen=True, slots=True)
class PersonBlock:
    """One activation's person block (ADR-0338 §7:1).

    Attributes:
        person_id: Whose.
        profile: Their five fields, each set or not.
        kept: The kept-in-mind slot, in its order: the pinned memories, then the style
            memories.
        left_out: How many memories the budget left out of the slot (§6:2).
        suggestions: The pending suggestions planning is shown, newest first.
    """

    person_id: str
    profile: Profile
    kept: tuple[KeptInMind, ...] = ()
    left_out: int = 0
    suggestions: tuple[ShownSuggestion, ...] = ()

    @property
    def pinned(self) -> tuple[Memory, ...]:
        """The slot's pinned memories: what understanding is shown of it (§7:2)."""
        return tuple(one.memory for one in self.kept if one.pinned)

    @property
    def memories(self) -> tuple[Memory, ...]:
        """Every memory the block shows, in the slot or with a pin suggestion."""
        return (
            *(one.memory for one in self.kept),
            *(one.memory for one in self.suggestions if one.memory is not None),
        )

    @property
    def memory_ids(self) -> frozenset[str]:
        """Every memory the block shows, in the slot or with a pin suggestion."""
        return frozenset(
            {one.memory.id for one in self.kept}
            | {one.memory.id for one in self.suggestions if one.memory is not None}
        )


class PinRefusal(StrEnum):
    """Why a pin was refused before any write (ADR-0338 §4:2, §6:3)."""

    NOT_CURRENT = "not_current"
    """Only a current memory may be pinned (§4:2)."""
    OVER_BUDGET = "over_budget"
    """The pins' wordings, with the new one's, would exceed the slot's budget (§6:3)."""
    UNKNOWN_PERSON = "unknown_person"
    """The person-model store holds no such person."""


@dataclass(frozen=True, slots=True)
class Pinned:
    """What :meth:`PersonBlocks.pin` did: the store's write, or why it was refused first.

    Attributes:
        write: The store's write: ``written``, ``unchanged`` or its own refusal.
        refused: Why the pin was refused before any write.
    """

    write: PersonModelWrite | None = None
    refused: PinRefusal | None = None


@dataclass(frozen=True, slots=True)
class Unpinned:
    """What :meth:`PersonBlocks.unpin` did (ADR-0338 §4:7).

    Attributes:
        showing: How many standing pins showed the memory.
        removed: How many of them were removed.
        refused: The store's refusal that stopped the removal, where one did.
        faulted: Whether a store fault stopped it after a pin was removed.
        unknown_person: Whether the store holds no such person.
    """

    showing: int = 0
    removed: int = 0
    refused: PersonModelWrite | None = None
    faulted: bool = False
    unknown_person: bool = False


class PersonBlocks:
    """Assemble an activation's person block, with no model call (ADR-0338 §7:1)."""

    def __init__(
        self,
        *,
        store: PersonModelStore,
        memory: MemoryStore,
        budget_chars: int = KEPT_IN_MIND_CHARS,
        suggestions: int = PLANNING_SUGGESTIONS,
    ) -> None:
        """Wire the assembly to the two stores it reads and its two bounds.

        Args:
            store: The person-model store.
            memory: The memory store the slot's memories are read from.
            budget_chars: ``KEPT_IN_MIND_CHARS``, §6:1's budget.
            suggestions: ``PLANNING_SUGGESTIONS``, §7:3's count.

        Raises:
            ValueError: If ``budget_chars`` is below 1 or ``suggestions`` below 0.
        """
        if budget_chars < 1:
            msg = "the kept-in-mind slot's budget is at least one character (ADR-0338 §6:1)"
            raise ValueError(msg)
        if suggestions < 0:
            msg = "planning is shown no fewer than no suggestions (ADR-0338 §7:3)"
            raise ValueError(msg)
        self._store = store
        self._memory = memory
        self._budget = budget_chars
        self._suggestions = suggestions
        self._pinning: dict[str, asyncio.Lock] = {}

    @property
    def store(self) -> PersonModelStore:
        """The person-model store the block is read from, which planning's calls write."""
        return self._store

    @property
    def memory(self) -> MemoryStore:
        """The memory store the slot's memories are read from."""
        return self._memory

    @property
    def budget_chars(self) -> int:
        """The kept-in-mind slot's budget, which a pin is checked against (ADR-0338 §6:3)."""
        return self._budget

    async def pin(self, person_id: str, memory_id: str, *, act: PersonModelAct) -> Pinned:
        """Pin a current memory where the pins' wordings stay within the budget (§4:2, §6:3).

        The one place a pin is checked and written, for every caller: planning's ``pin``
        under the person's yes, and the panel's (§8:2). The store leaves both checks to
        its caller, against the memory store, before the write (§4:2, §6:3):

        - the memory is read live, and pinned only where it is current;
        - the wordings of the memories the person's standing pins show in the slot, each
          once, at its chain's current end and not resting on outside content (§4:8,
          §6:4), together with the new one's where it is not among them already, must
          stay within the slot's budget.

        The read, the checks and the write are made under one lock per person, so two
        pins checked at once cannot both pass a budget only one of them fits. The hub is
        one process per data directory, so the lock serializes every caller through this
        assembly. A write the store makes accepts any pending pin suggestion of that
        memory in the same step (§8:8).

        Args:
            person_id: Whose pin.
            memory_id: The memory, by id.
            act: Who pinned it, and how: on the panel, or by a yes.

        Returns:
            The store's write, or why the pin was refused before any write.

        Raises:
            PersonModelStoreError: If the person-model store cannot be read or written.
            MemoryStoreError: If the memory store cannot be read.
            ValueError: If ``memory_id`` is blank.
        """
        async with self._pinning.setdefault(person_id, asyncio.Lock()):
            live = await self._memory.get_many([memory_id])
            record = live.get(memory_id)
            if not isinstance(record, Memory) or record.status is not MemoryStatus.CURRENT:
                return Pinned(refused=PinRefusal.NOT_CURRENT)
            model = await self._store.read(person_id)
            if model is None:
                return Pinned(refused=PinRefusal.UNKNOWN_PERSON)
            ends = await self._reached(pin.memory_id for pin in model.standing_pins)
            shown = {end.id: end for end in ends.values() if not end.rests_on_outside_content}
            shown.setdefault(record.id, record)
            if sum(len(one.content) for one in shown.values()) > self._budget:
                return Pinned(refused=PinRefusal.OVER_BUDGET)
            return Pinned(write=await self._store.add_pin(person_id, memory_id, act=act))

    async def unpin(self, person_id: str, memory_id: str) -> Unpinned:
        """Remove every standing pin that shows the memory, erasing nothing (§4:7).

        The one place an unpin is resolved and written, for every caller. A memory a pin
        shows is the one it was made on or the current successor its chain reached
        (§4:8), so every standing pin whose memory, or whose chain's current end, is
        ``memory_id`` is removed, under the person's pinning lock. Where one cannot be
        removed after another was, the removal stops there and says how far it got.

        Args:
            person_id: Whose pins.
            memory_id: The memory, by id.

        Returns:
            How many pins showed the memory, how many were removed, and the store's
            refusal or fault that stopped it, where one did.

        Raises:
            PersonModelStoreError: If the person-model store cannot be read, or fails
                before any pin is removed.
            MemoryStoreError: If the memory store cannot be read.
        """
        async with self._pinning.setdefault(person_id, asyncio.Lock()):
            model = await self._store.read(person_id)
            if model is None:
                return Unpinned(unknown_person=True)
            standing = model.standing_pins
            ends = await self._reached(pin.memory_id for pin in standing)
            showing = [
                pin
                for pin in standing
                if pin.memory_id == memory_id
                or (pin.memory_id in ends and ends[pin.memory_id].id == memory_id)
            ]
            for removed, pin in enumerate(showing):
                try:
                    written = await self._store.remove_pin(person_id, pin.id)
                except PersonModelStoreError:
                    if not removed:
                        raise
                    return Unpinned(showing=len(showing), removed=removed, faulted=True)
                if written.kind is PersonModelWriteKind.REFUSED:
                    return Unpinned(showing=len(showing), removed=removed, refused=written)
            return Unpinned(showing=len(showing), removed=len(showing))

    async def current_ends(self, memory_ids: Iterable[str]) -> dict[str, Memory]:
        """Each memory's chain's current end, where it has one (ADR-0338 §4:8).

        What a pin or a mark on each of ``memory_ids`` shows, walked as the block walks
        it (ADR-0342 §5:2-§5:3), keyed by the memory the pin or mark was made on. A
        chain that reaches no current memory, or a memory the store no longer holds, is
        absent.

        Args:
            memory_ids: The memories pins or marks were made on.

        Returns:
            Each one's current end, by the memory it starts from.

        Raises:
            MemoryStoreError: If the memory store cannot be read.
        """
        return await self._reached(memory_ids)

    async def assemble(self, person_id: str | None, *, supply: TurnSupply) -> PersonBlock | None:
        """The block for ``person_id``, or ``None`` where there is none to give.

        Args:
            person_id: The activation's person, as :func:`activation_person` read it;
                ``None`` for an activation that is no person's, which is given no block
                (§2:3).
            supply: The pass's audience posture, whose predicate the slot's memories
                and a pin suggestion's pass (§6:5).

        Returns:
            The block; ``None`` for no person, a person the store does not hold, or a
            store that could not be read.
        """
        if person_id is None:
            return None
        try:
            model = await self._store.read(person_id)
            if model is None:
                _log.warning("person_block_unread", stage="person_block", reason="no_person")
                return None
            block = await self._assembled(model, supply)
        except PersonModelStoreError:
            _log.warning("person_block_unread", stage="person_block", reason="store_fault")
            return None
        except MemoryStoreError:
            _log.warning("person_block_unread", stage="person_block", reason="memory_fault")
            return None
        _log.info(
            "person_block",
            stage="person_block",
            pinned=len(block.pinned),
            kept=len(block.kept),
            left_out=block.left_out,
            suggestions=len(block.suggestions),
        )
        return block

    async def _assembled(self, model: PersonModel, supply: TurnSupply) -> PersonBlock:
        # The store reads each in the order made, so its position breaks a tie in time:
        # oldest pin first, and the most recent mark and suggestion first (§6:2, §7:3).
        pins = [pin for _, pin in sorted(enumerate(model.standing_pins), key=_made(_pinned))]
        marks = [
            mark
            for _, mark in sorted(enumerate(model.standing_marks), key=_made(_marked), reverse=True)
        ]
        pending = [
            one
            for _, one in sorted(enumerate(model.suggestions), key=_made(_recorded), reverse=True)
        ]
        suggested = [
            one.proposed.memory_id
            for one in pending
            if one.proposed.kind is SuggestionKind.PIN and one.proposed.memory_id is not None
        ]
        reached = await self._reached(
            [*(pin.memory_id for pin in pins), *(mark.memory_id for mark in marks)]
        )
        held = await self._memory.get_many(list(dict.fromkeys(suggested))) if suggested else {}
        candidates: list[KeptInMind] = []
        seen: set[str] = set()
        for start, pinned in [
            *((pin.memory_id, True) for pin in pins),
            *((mark.memory_id, False) for mark in marks),
        ]:
            memory = reached.get(start)
            if memory is None or memory.id in seen or memory.rests_on_outside_content:
                continue
            seen.add(memory.id)
            candidates.append(KeptInMind(memory=memory, pinned=pinned))
        admitted = {
            one.id for one in admitted_to_understanding(supply, [one.memory for one in candidates])
        }
        kept, left_out = self._budgeted([one for one in candidates if one.memory.id in admitted])
        return PersonBlock(
            person_id=model.person.id,
            profile=model.profile,
            kept=kept,
            left_out=left_out,
            suggestions=self._shown(pending, held, supply),
        )

    def _budgeted(self, candidates: Sequence[KeptInMind]) -> tuple[tuple[KeptInMind, ...], int]:
        """The slot within the budget, and how many it left out (ADR-0338 §6:1-§6:2)."""
        spent = 0
        for index, one in enumerate(candidates):
            spent += len(one.memory.content)
            if spent > self._budget:
                return tuple(candidates[:index]), len(candidates) - index
        return tuple(candidates), 0

    def _shown(
        self,
        pending: Sequence[PersonSuggestion],
        held: Mapping[str, MemoryRecord],
        supply: TurnSupply,
    ) -> tuple[ShownSuggestion, ...]:
        """The pending suggestions §7:9 admits, newest first, up to the count (§7:3)."""
        shown: list[ShownSuggestion] = []
        for one in pending:
            if len(shown) == self._suggestions:
                break
            proposed = one.proposed
            if proposed.kind is SuggestionKind.FIELD:
                if proposed.rests_on_outside_content:
                    continue
                shown.append(
                    ShownSuggestion(
                        kind=proposed.kind,
                        recorded_at=one.recorded_at,
                        field=proposed.field,
                        value=proposed.value,
                    )
                )
                continue
            record = held.get(proposed.memory_id or "")
            if (
                not isinstance(record, Memory)
                or record.status is not MemoryStatus.CURRENT
                or record.rests_on_outside_content
                or not admitted_to_understanding(supply, [record])
            ):
                continue
            shown.append(
                ShownSuggestion(kind=proposed.kind, recorded_at=one.recorded_at, memory=record)
            )
        return tuple(shown)

    async def _reached(self, starts: Iterable[str]) -> dict[str, Memory]:
        """Each start's chain's current end, where it has one (ADR-0342 §5:2-§5:3).

        A pin or mark on a memory that is ended or wrong and names a successor shows the
        successor, followed to a current memory; a chain that reaches no current memory,
        or a memory the store no longer holds, shows nothing (ADR-0338 §4:8, §4:10).

        At each memory a chain reaches, the live read is asked first, and where it
        returns the memory current, the walk ends there. Only the memories it does not
        return are read through the history read, made after it, so a memory retired
        between the two is read retired and its successor is followed rather than lost
        (ADR-0342 §5:3's order). The walk ends with no current memory where the history
        read omits the memory, where its record names no successor, or where the
        successor is one this chain has already reached, and at no other length: each
        step adds a memory the chain had not reached, so the walk ends however long the
        chain. The chains are walked together: one live read per step, and one history
        read where that live read missed.

        A live read returning a memory whose status is not current, a state the writer
        never builds (a retired memory's window is closed, ADR-0328 §3:4, §5:9), is
        taken as a miss, so even then no retired memory is shown as current (ADR-0342
        §5:1).
        """
        at = {start: start for start in dict.fromkeys(starts)}
        reached: dict[str, Memory] = {}
        visited: dict[str, set[str]] = {start: {start} for start in at}
        while at:
            live = await self._memory.get_many(list(dict.fromkeys(at.values())))
            missed: dict[str, str] = {}
            for start, memory_id in at.items():
                record = live.get(memory_id)
                if isinstance(record, Memory) and record.status is MemoryStatus.CURRENT:
                    reached[start] = record
                else:
                    missed[start] = memory_id
            if not missed:
                break
            history = await self._memory.get_history(list(dict.fromkeys(missed.values())))
            following: dict[str, str] = {}
            for start, memory_id in missed.items():
                retired = history.get(memory_id)
                if retired is None:
                    continue
                successor = _successor(retired)
                if successor is None or successor in visited[start]:
                    continue
                visited[start].add(successor)
                following[start] = successor
            at = following
        return reached


def _made[R](when: Callable[[R], datetime]) -> Callable[[tuple[int, R]], tuple[datetime, int]]:
    """A sort key: a record's instant, then its place in the order the store made it."""
    return lambda pair: (when(pair[1]), pair[0])


def _pinned(pin: Pin) -> datetime:
    return pin.pinned_at


def _marked(mark: StyleMark) -> datetime:
    return mark.marked_at


def _recorded(suggestion: PersonSuggestion) -> datetime:
    return suggestion.recorded_at


def _successor(record: Memory) -> str | None:
    """The successor the latest operation in the memory's log naming one names (ADR-0342 §5:2).

    A memory may be retired twice, ended and later marked wrong (ADR-0328 §5:7), and
    each may name a successor or none: the latest that names one governs, so a later
    retirement naming none leaves an earlier one's successor standing.
    """
    for operation in reversed(record.operations):
        if operation.successor is not None:
            return operation.successor
    return None


async def still_held(block: PersonBlock, memory: MemoryStore) -> PersonBlock:
    """The block less every memory the memory store no longer holds (ADR-0338 §7:10).

    Read before each planning round, the first included, so a memory forgotten while
    the activation runs reaches no later request. The store holds a memory exactly
    where the history read returns it (ADR-0342 §5:4), so a memory forgotten or past
    its ``expires_at`` is dropped, and one retired since the block was assembled is
    not: the block is assembled once (§7:1), and this check walks no chain. A memory
    store that cannot be read leaves the block's fields and no memory of it, so nothing
    forgotten can slip through a failed check.

    Args:
        block: The activation's block, as it stood before this round.
        memory: The memory store.

    Returns:
        The block, its slot and its pin suggestions those still held.
    """
    ids = sorted(block.memory_ids)
    if not ids:
        return block
    try:
        held = set(await memory.get_history(ids))
    except MemoryStoreError:
        _log.warning("person_block_unread", stage="person_block", reason="memory_fault")
        held = set()
    if held.issuperset(ids):
        return block
    return replace(
        block,
        kept=tuple(one for one in block.kept if one.memory.id in held),
        suggestions=tuple(
            one for one in block.suggestions if one.memory is None or one.memory.id in held
        ),
    )
