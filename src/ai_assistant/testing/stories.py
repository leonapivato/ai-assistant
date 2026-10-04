"""The canonical ``StoryStore`` fake (ADR-0289 §1).

The triad's third artifact. A non-persistent store over dictionaries, holding every
clause the SQLite store holds and refusing everything it refuses, so a consumer
verified against this one is verified against the contract rather than against a
convenience: the clean view and the change log, the five reads, merge and split
with their exceptions, and the loop refusal.

**Atomic by construction.** Every write computes its refusal and applies its changes
with no ``await`` in between, so on one event loop a write is never interleaved with
another — the property the durable store buys with one transaction. A merge whose
result would close a loop is applied to a copy and discarded, so a refused write
leaves nothing behind.
"""

from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, final
from uuid import uuid4

from pydantic import TypeAdapter

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    STORY_ID_PREFIX,
    Identifier,
    StoryActor,
    StoryChange,
    StoryEntry,
    StoryHeader,
    StoryLogLine,
    StoryLogPage,
    StoryMember,
    StoryMemberKind,
    StoryOutcome,
    StoryPage,
    StoryRefusal,
    StoryRefusalReason,
    StoryViewPage,
    check_story_page,
    story_members,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.clock import Clock

__all__ = ["FakeStoryStore"]

_IDENTIFIER: TypeAdapter[str] = TypeAdapter(Identifier)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _checked_id(value: object) -> str:
    if not isinstance(value, str):
        msg = f"a story id must be a string, got {type(value).__name__}"
        raise ValueError(msg)
    return _IDENTIFIER.validate_python(value)


def _checked_write(actor: object, trigger: object) -> tuple[StoryActor, str | None]:
    if not isinstance(actor, str):
        msg = f"a story actor must be a StoryActor, got {type(actor).__name__}"
        raise ValueError(msg)
    return StoryActor(actor), None if trigger is None else _checked_id(trigger)


def _unique(members: Sequence[StoryMember]) -> list[StoryMember]:
    return list(dict.fromkeys(members))


@dataclass
class _Story:
    """One story's own record: its header fields and its ordered entries."""

    created_seq: int
    created_at: datetime
    merged_into: str | None = None
    entries: dict[StoryMember, StoryEntry] = field(default_factory=dict)


@dataclass
class _State:
    """Everything the store holds, copied whole for a write that may be refused."""

    sequence: int = 0
    stories: dict[str, _Story] = field(default_factory=dict)
    log: list[StoryLogLine] = field(default_factory=list)


@dataclass(frozen=True)
class _Stamp:
    actor: StoryActor
    trigger: str | None
    at: datetime


class _Refused(Exception):  # noqa: N818 — a control-flow signal, not an error a caller sees
    def __init__(self, refusal: StoryRefusal) -> None:
        super().__init__(refusal.reason.value)
        self.refusal = refusal


@final
class FakeStoryStore:
    """A non-persistent, conforming ``StoryStore`` test double.

    Structurally implements :class:`~ai_assistant.core.protocols.StoryStore`.
    """

    def __init__(
        self, *, now: Clock = _utcnow, new_id: Callable[[], str] = lambda: uuid4().hex
    ) -> None:
        """Build an empty store.

        Args:
            now: The clock every change is stamped with, guarded as the durable
                store's is.
            new_id: The source a minted story id's suffix is drawn from.
        """
        self._clock = checked_clock(now, owner="FakeStoryStore")
        self._new_id = new_id
        self._state = _State()

    # --- internals -----------------------------------------------------------

    def _stamp(self, actor: StoryActor, trigger: str | None) -> _Stamp:
        try:
            at = self._clock()
        except ClockReadingError as exc:
            raise StoryStoreError(str(exc)) from exc
        return _Stamp(actor=actor, trigger=trigger, at=at)

    @staticmethod
    def _header_of(story_id: str, story: _Story) -> StoryHeader:
        return StoryHeader(
            story_id=story_id, created_at=story.created_at, merged_into=story.merged_into
        )

    @staticmethod
    def _story_refusal(state: _State, story_id: str) -> StoryRefusal | None:
        story = state.stories.get(story_id)
        if story is None:
            return StoryRefusal(reason=StoryRefusalReason.UNKNOWN_STORY, story_id=story_id)
        if story.merged_into is not None:
            return StoryRefusal(
                reason=StoryRefusalReason.MERGED_STORY,
                story_id=story_id,
                merged_into=story.merged_into,
            )
        return None

    def _members_refusal(
        self, state: _State, members: Sequence[StoryMember]
    ) -> StoryRefusal | None:
        for member in members:
            if member.kind is StoryMemberKind.STORY and (
                refused := self._story_refusal(state, member.id)
            ):
                return refused
        return None

    @staticmethod
    def _children(state: _State, story_id: str) -> list[str]:
        return [
            member.id
            for member in state.stories[story_id].entries
            if member.kind is StoryMemberKind.STORY
        ]

    def _path_down(self, state: _State, start: str, target: str) -> list[str] | None:
        """A shortest chain of stories from ``start`` down to ``target``, or ``None``."""
        parents: dict[str, str | None] = {start: None}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            if current == target:
                chain = [current]
                while (above := parents[chain[-1]]) is not None:
                    chain.append(above)
                return chain[::-1]
            for child in self._children(state, current):
                if child not in parents:
                    parents[child] = current
                    queue.append(child)
        return None

    @staticmethod
    def _append(  # noqa: PLR0913 — the state, the line's story and change, and its fields
        state: _State,
        story_id: str,
        change: StoryChange,
        stamp: _Stamp,
        *,
        member: StoryMember | None = None,
        other: str | None = None,
    ) -> int:
        state.sequence += 1
        state.log.append(
            StoryLogLine(
                sequence=state.sequence,
                story_id=story_id,
                change=change,
                member=member,
                other_story=other,
                actor=stamp.actor,
                trigger=stamp.trigger,
                at=stamp.at,
            )
        )
        return state.sequence

    def _add(self, state: _State, story_id: str, member: StoryMember, stamp: _Stamp) -> None:
        position = self._append(state, story_id, StoryChange.ADDED, stamp, member=member)
        state.stories[story_id].entries[member] = StoryEntry(
            position=position, member=member, linked_at=stamp.at, actor=stamp.actor
        )

    def _remove(self, state: _State, story_id: str, member: StoryMember, stamp: _Stamp) -> None:
        del state.stories[story_id].entries[member]
        self._append(state, story_id, StoryChange.REMOVED, stamp, member=member)

    def _mint(self, state: _State, stamp: _Stamp) -> str:
        suffix = self._new_id()
        if type(suffix) is not str or not suffix.strip():
            msg = f"the story id source returned an unusable id: {suffix!r}"
            raise StoryStoreError(msg)
        story_id = _checked_id(STORY_ID_PREFIX + suffix.strip())
        if story_id in state.stories:
            msg = f"the story id source minted {story_id!r}, which the store already holds"
            raise StoryStoreError(msg)
        sequence = self._append(state, story_id, StoryChange.CREATED, stamp)
        state.stories[story_id] = _Story(created_seq=sequence, created_at=stamp.at)
        return story_id

    # --- writes --------------------------------------------------------------

    async def create(
        self,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
    ) -> StoryOutcome:
        """Mint a story holding ``members`` (ADR-0289 §3)."""
        named = story_members(members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        if not named:
            return StoryOutcome(refusal=StoryRefusal(reason=StoryRefusalReason.NO_MEMBERS))
        state = self._state
        if refused := self._members_refusal(state, named):
            return StoryOutcome(refusal=refused)
        stamp = self._stamp(checked_actor, checked_trigger)
        story_id = self._mint(state, stamp)
        unique = _unique(named)
        for member in unique:
            self._add(state, story_id, member, stamp)
        return StoryOutcome(story_id=story_id, logged=1 + len(unique))

    async def link(
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
    ) -> StoryOutcome:
        """Add ``members`` to a story (ADR-0289 §3)."""
        target = _checked_id(story_id)
        named = story_members(members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        if not named:
            return StoryOutcome(refusal=StoryRefusal(reason=StoryRefusalReason.NO_MEMBERS))
        state = self._state
        if refused := self._story_refusal(state, target) or self._members_refusal(state, named):
            return StoryOutcome(refusal=refused)
        held = state.stories[target].entries
        fresh = [member for member in _unique(named) if member not in held]
        for member in fresh:
            if member.kind is StoryMemberKind.STORY:
                chain = self._path_down(state, member.id, target)
                if chain is not None:
                    return StoryOutcome(
                        refusal=StoryRefusal(
                            reason=StoryRefusalReason.LOOP,
                            story_id=target,
                            loop=(target, *chain[:-1]),
                        )
                    )
        stamp = self._stamp(checked_actor, checked_trigger)
        for member in fresh:
            self._add(state, target, member, stamp)
        return StoryOutcome(story_id=target, logged=len(fresh))

    async def unlink(
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
    ) -> StoryOutcome:
        """Remove ``members`` from a story (ADR-0289 §3)."""
        target = _checked_id(story_id)
        named = story_members(members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        if not named:
            return StoryOutcome(refusal=StoryRefusal(reason=StoryRefusalReason.NO_MEMBERS))
        state = self._state
        if refused := self._story_refusal(state, target) or self._members_refusal(state, named):
            return StoryOutcome(refusal=refused)
        held = state.stories[target].entries
        present = [member for member in _unique(named) if member in held]
        stamp = self._stamp(checked_actor, checked_trigger)
        for member in present:
            self._remove(state, target, member, stamp)
        return StoryOutcome(story_id=target, logged=len(present))

    async def merge(
        self,
        story_id: Identifier,
        into: Identifier,
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
    ) -> StoryOutcome:
        """Merge story ``story_id`` into story ``into`` (ADR-0289 §3)."""
        absorbed = _checked_id(story_id)
        target = _checked_id(into)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        if refused := self._story_refusal(self._state, absorbed) or self._story_refusal(
            self._state, target
        ):
            return StoryOutcome(refusal=refused)
        if absorbed == target:
            return StoryOutcome(
                refusal=StoryRefusal(reason=StoryRefusalReason.SELF_MERGE, story_id=absorbed)
            )
        stamp = self._stamp(checked_actor, checked_trigger)
        # Applied to a copy and kept only if no loop closed, so a refusal writes nothing.
        state = copy.deepcopy(self._state)
        try:
            logged = self._merge_writes(state, absorbed, target, stamp)
        except _Refused as refused_merge:
            return StoryOutcome(refusal=refused_merge.refusal)
        self._state = state
        return StoryOutcome(story_id=target, logged=logged)

    def _merge_writes(self, state: _State, absorbed: str, target: str, stamp: _Stamp) -> int:
        self._append(state, absorbed, StoryChange.MERGED_INTO, stamp, other=target)
        self._append(state, target, StoryChange.ABSORBED, stamp, other=absorbed)
        logged = 2
        target_member = StoryMember(kind=StoryMemberKind.STORY, id=target)
        for member in list(state.stories[absorbed].entries):
            self._remove(state, absorbed, member, stamp)
            logged += 1
            if member == target_member or member in state.stories[target].entries:
                continue
            self._add(state, target, member, stamp)
            logged += 1
        absorbed_member = StoryMember(kind=StoryMemberKind.STORY, id=absorbed)
        holders = sorted(
            (
                (story.entries[absorbed_member].position, holder)
                for holder, story in state.stories.items()
                if absorbed_member in story.entries
            ),
        )
        for _, holder in holders:
            self._remove(state, holder, absorbed_member, stamp)
            logged += 1
            if holder == target or target_member in state.stories[holder].entries:
                continue
            self._add(state, holder, target_member, stamp)
            logged += 1
        state.stories[absorbed].merged_into = target
        for child in self._children(state, target):
            chain = self._path_down(state, child, target)
            if chain is not None:
                raise _Refused(
                    StoryRefusal(
                        reason=StoryRefusalReason.LOOP,
                        story_id=target,
                        loop=(target, *chain[:-1]),
                    )
                )
        return logged

    async def split(
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
    ) -> StoryOutcome:
        """Move a non-empty subset of a story's members into a new story (ADR-0289 §3)."""
        source = _checked_id(story_id)
        named = story_members(members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        if not named:
            return StoryOutcome(refusal=StoryRefusal(reason=StoryRefusalReason.NO_MEMBERS))
        state = self._state
        if refused := self._story_refusal(state, source) or self._members_refusal(state, named):
            return StoryOutcome(refusal=refused)
        held = state.stories[source].entries
        for member in named:
            if member not in held:
                return StoryOutcome(
                    refusal=StoryRefusal(
                        reason=StoryRefusalReason.NOT_A_MEMBER, story_id=source, member=member
                    )
                )
        moving = set(named)
        moved = [member for member in held if member in moving]
        stamp = self._stamp(checked_actor, checked_trigger)
        split_off = self._mint(state, stamp)
        self._append(state, source, StoryChange.SPLIT_OFF, stamp, other=split_off)
        self._append(state, split_off, StoryChange.SPLIT_OFF, stamp, other=source)
        for member in moved:
            self._remove(state, source, member, stamp)
            self._add(state, split_off, member, stamp)
        return StoryOutcome(story_id=split_off, logged=3 + 2 * len(moved))

    # --- reads ---------------------------------------------------------------

    async def header(self, story_id: Identifier) -> StoryHeader | None:
        """Read a story's header (ADR-0289 §3)."""
        target = _checked_id(story_id)
        story = self._state.stories.get(target)
        return None if story is None else self._header_of(target, story)

    async def view(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryViewPage | None:
        """Read a page of a story's clean view, in link order (ADR-0289 §3)."""
        target = _checked_id(story_id)
        check_story_page(cursor, limit)
        story = self._state.stories.get(target)
        if story is None:
            return None
        after = -1 if cursor is None else cursor
        ordered = sorted(story.entries.values(), key=lambda entry: entry.position)
        rest = [entry for entry in ordered if entry.position > after]
        page = rest[:limit]
        return StoryViewPage(
            story=self._header_of(target, story),
            member_count=len(ordered),
            entries=tuple(page),
            next_cursor=page[-1].position if len(rest) > limit else None,
        )

    async def log(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryLogPage | None:
        """Read a page of a story's change log, in sequence order (ADR-0289 §3)."""
        target = _checked_id(story_id)
        check_story_page(cursor, limit)
        story = self._state.stories.get(target)
        if story is None:
            return None
        after = -1 if cursor is None else cursor
        rest = [
            line for line in self._state.log if line.story_id == target and line.sequence > after
        ]
        page = rest[:limit]
        return StoryLogPage(
            story=self._header_of(target, story),
            lines=tuple(page),
            next_cursor=page[-1].sequence if len(rest) > limit else None,
        )

    async def stories(
        self,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryPage:
        """Read a page of every story the store holds, newest first (ADR-0289 §3)."""
        check_story_page(cursor, limit)
        ordered = sorted(
            self._state.stories.items(), key=lambda item: item[1].created_seq, reverse=True
        )
        rest = [item for item in ordered if cursor is None or item[1].created_seq < cursor]
        page = rest[:limit]
        return StoryPage(
            stories=tuple(self._header_of(story_id, story) for story_id, story in page),
            next_cursor=page[-1][1].created_seq if len(rest) > limit else None,
        )

    async def stories_of(self, member: StoryMember) -> tuple[StoryHeader, ...]:
        """Read the stories ``member`` belongs to directly, newest first (ADR-0289 §3)."""
        (named,) = story_members((member,))
        holding = sorted(
            (
                (story_id, story)
                for story_id, story in self._state.stories.items()
                if named in story.entries
            ),
            key=lambda item: item[1].created_seq,
            reverse=True,
        )
        return tuple(self._header_of(story_id, story) for story_id, story in holding)
