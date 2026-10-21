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

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.channel_validation import establishes_the_user
from ai_assistant.core.errors import MemoryStoreError, PersonModelStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ChannelIdentity,
    Memory,
    MemoryStatus,
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
    "ShownSuggestion",
    "activation_person",
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

#: How many successors a pin or mark is followed through before it is taken to reach no
#: current memory: a bound on the reads, never reached by a chain the writer builds.
_SUCCESSOR_HOPS: Final = 16


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
    if establishes_the_user(kind) or kind in _PUSHED_BY_A_CONNECTED_SOURCE:
        return OWNER_PERSON_ID
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
        successor is one this chain has already reached. The chains are walked together:
        one live read per step, and one history read where that live read missed.

        A live read returning a memory whose status is not current, a state the writer
        never builds (a retired memory's window is closed, ADR-0328 §3:4, §5:9), is
        taken as a miss, so even then no retired memory is shown as current (ADR-0342
        §5:1).
        """
        at = {start: start for start in dict.fromkeys(starts)}
        reached: dict[str, Memory] = {}
        visited: dict[str, set[str]] = {start: {start} for start in at}
        for _ in range(_SUCCESSOR_HOPS):
            if not at:
                break
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
