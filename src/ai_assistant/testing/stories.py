"""The canonical ``StoryStore`` fake (ADR-0289 §1, ADR-0300 §3).

The triad's third artifact. A non-persistent store over dictionaries, holding every
clause the SQLite store holds and refusing everything it refuses, so a consumer
verified against this one is verified against the contract rather than against a
convenience: the clean view and the change log, the five membership reads, merge,
split and move with their exceptions, the loop refusal, and each story's page — its
notes, its current page, its version log and what is pending on it.

**Atomic by construction.** Every write computes its refusal and applies its changes
with no ``await`` in between, so on one event loop a write is never interleaved with
another — the property the durable store buys with one transaction. A merge whose
result would close a loop is applied to a copy and discarded, so a refused write
leaves nothing behind.

**One counter for the page's records**, as the durable store keeps: a note's
identity, a version's, and the moment a note or an activation member became pending
on a story are drawn from it, and a page read reports it as its ``as_of``.
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
    STORY_PAGE_CAP_CHARS,
    Identifier,
    StoryActor,
    StoryChange,
    StoryCurrentPage,
    StoryEntry,
    StoryHeader,
    StoryLogLine,
    StoryLogPage,
    StoryMember,
    StoryMemberKind,
    StoryNote,
    StoryNoteAuthor,
    StoryNoteId,
    StoryNoteList,
    StoryNoteOutcome,
    StoryOutcome,
    StoryPage,
    StoryPageDraft,
    StoryPageLine,
    StoryPageOutcome,
    StoryPageRefusal,
    StoryPageRefusalReason,
    StoryPageState,
    StoryPageVersion,
    StoryPageVersionList,
    StoryRefusal,
    StoryRefusalReason,
    StoryViewPage,
    check_story_as_of,
    check_story_page,
    story_members,
    story_note_ids,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

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


def _unique[T](items: Sequence[T]) -> list[T]:
    return list(dict.fromkeys(items))


# The page's argument checks and its cap rule, held here as the durable store holds
# its own: they are the contract's admission rules, not semantics intrinsic to the
# types (ADR-0016 §2), and the conformance suite keeps the two copies in step.


def _note_args(
    text: object, *, author: object, rests_on: object, outside: object
) -> tuple[str, StoryNoteAuthor, str | None, bool]:
    """Check a note an append writes; a tidy-up's are never appended (ADR-0300 §5:4)."""
    if not isinstance(author, str):
        msg = f"a note's author must be a StoryNoteAuthor, got {type(author).__name__}"
        raise ValueError(msg)
    if StoryNoteAuthor(author) is StoryNoteAuthor.TIDY_UP:
        msg = "a tidy-up's notes are written with its page, never appended"
        raise ValueError(msg)
    checked = StoryNote(
        note_id=1,
        text=text,  # type: ignore[arg-type]  # validated by the model, which is the point
        author=StoryNoteAuthor(author),
        rests_on=rests_on,  # type: ignore[arg-type]  # validated by the model
        outside=outside,  # type: ignore[arg-type]  # validated by the model
        written_at=datetime(1970, 1, 1, tzinfo=UTC),
    )
    return checked.text, checked.author, checked.rests_on, checked.outside


def _page_draft(story_id: str, draft: object) -> StoryPageDraft:
    """Snapshot a page write's draft by revalidation, refusing a flag on its own story."""
    if not isinstance(draft, StoryPageDraft):
        msg = f"a page write takes a StoryPageDraft, got {type(draft).__name__}"
        raise ValueError(msg)
    snapshot = StoryPageDraft.model_validate(draft.model_dump())
    if any(flag.story == story_id for flag in snapshot.flags):
        msg = "a flag names another story, never the one whose page it is raised on"
        raise ValueError(msg)
    return snapshot


def _move_members(source: str, target: str, members: object) -> tuple[StoryMember, ...]:
    """Snapshot a move's members: activation members, between two stories."""
    if source == target:
        msg = "a move is from one story to another"
        raise ValueError(msg)
    named = story_members(members)
    if any(member.kind is not StoryMemberKind.ACTIVATION for member in named):
        msg = "a move carries activation members only"
        raise ValueError(msg)
    return named


def _page_size(draft: StoryPageDraft, owner_notes: Mapping[int, str]) -> int:
    """The characters counted against the cap: every line but the user's own notes."""
    return sum(
        len(line.text)
        for line in draft.lines
        if not any(owner_notes.get(note) == line.text for note in line.cites)
    )


@dataclass
class _Story:
    """One story's own record: its header fields and its ordered entries.

    ``pending`` holds its activation members pending on it, by activation id, with
    the counter's reading when each became pending.
    """

    created_seq: int
    created_at: datetime
    merged_into: str | None = None
    entries: dict[StoryMember, StoryEntry] = field(default_factory=dict)
    pending: dict[str, int] = field(default_factory=dict)


@dataclass
class _Held:
    """A note, the story holding it, and since when it is pending there, if it is."""

    note: StoryNote
    story_id: str
    pending_since: int | None


@dataclass
class _State:
    """Everything the store holds, copied whole for a write that may be refused."""

    sequence: int = 0
    tick: int = 0
    stories: dict[str, _Story] = field(default_factory=dict)
    log: list[StoryLogLine] = field(default_factory=list)
    notes: dict[int, _Held] = field(default_factory=dict)
    pages: dict[str, StoryCurrentPage] = field(default_factory=dict)
    versions: list[tuple[str, StoryPageVersion]] = field(default_factory=list)


@dataclass(frozen=True)
class _Stamp:
    actor: StoryActor
    trigger: str | None
    at: datetime


class _Refused(Exception):  # noqa: N818 — a control-flow signal, not an error a caller sees
    def __init__(self, refusal: StoryRefusal) -> None:
        super().__init__(refusal.reason.value)
        self.refusal = refusal


def _tick(state: _State) -> int:
    state.tick += 1
    return state.tick


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

    def _now(self) -> datetime:
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise StoryStoreError(str(exc)) from exc

    def _stamp(self, actor: StoryActor, trigger: str | None) -> _Stamp:
        return _Stamp(actor=actor, trigger=trigger, at=self._now())

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
        story = state.stories[story_id]
        story.entries[member] = StoryEntry(
            position=position, member=member, linked_at=stamp.at, actor=stamp.actor
        )
        if member.kind is StoryMemberKind.ACTIVATION:
            story.pending[member.id] = _tick(state)

    def _remove(self, state: _State, story_id: str, member: StoryMember, stamp: _Stamp) -> None:
        story = state.stories[story_id]
        del story.entries[member]
        if member.kind is StoryMemberKind.ACTIVATION:
            story.pending.pop(member.id, None)
        self._append(state, story_id, StoryChange.REMOVED, stamp, member=member)

    @staticmethod
    def _carry(state: _State, note_ids: Sequence[int], to: str) -> None:
        """Move notes to story ``to``, each pending there from now (ADR-0300 §3:8)."""
        for note_id in note_ids:
            held = state.notes[note_id]
            held.story_id = to
            held.pending_since = _tick(state)

    @staticmethod
    def _notes_resting_on(state: _State, story_id: str, activations: set[str]) -> list[int]:
        return sorted(
            note_id
            for note_id, held in state.notes.items()
            if held.story_id == story_id and held.note.rests_on in activations
        )

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
        """Merge story ``story_id`` into story ``into`` (ADR-0289 §3, ADR-0300 §3)."""
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
        # The absorbed story's notes go with it (ADR-0300 §3:12).
        self._carry(
            state,
            sorted(note_id for note_id, held in state.notes.items() if held.story_id == absorbed),
            target,
        )
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
        notes: Sequence[StoryNoteId] = (),
    ) -> StoryOutcome:
        """Move a non-empty subset of a story's members into a new story (ADR-0289 §3)."""
        source = _checked_id(story_id)
        named = story_members(members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        named_notes = story_note_ids(notes)
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
        activations = {m.id for m in moved if m.kind is StoryMemberKind.ACTIVATION}
        carried = set(self._notes_resting_on(state, source, activations))
        for note_id in named_notes:
            note = state.notes.get(note_id)
            if (
                note is not None
                and note.story_id == source
                and note.note.author is StoryNoteAuthor.OWNER
            ):
                carried.add(note_id)
        stamp = self._stamp(checked_actor, checked_trigger)
        split_off = self._mint(state, stamp)
        self._append(state, source, StoryChange.SPLIT_OFF, stamp, other=split_off)
        self._append(state, split_off, StoryChange.SPLIT_OFF, stamp, other=source)
        for member in moved:
            self._remove(state, source, member, stamp)
            self._add(state, split_off, member, stamp)
        self._carry(state, sorted(carried), split_off)
        return StoryOutcome(story_id=split_off, logged=3 + 2 * len(moved))

    async def move(
        self,
        story_id: Identifier,
        to: Identifier,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
    ) -> StoryOutcome:
        """Move activation members from one story to another (ADR-0300 §3)."""
        source = _checked_id(story_id)
        target = _checked_id(to)
        named = _move_members(source, target, members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        if not named:
            return StoryOutcome(refusal=StoryRefusal(reason=StoryRefusalReason.NO_MEMBERS))
        state = self._state
        if refused := self._story_refusal(state, source) or self._story_refusal(state, target):
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
        carried = self._notes_resting_on(state, source, {m.id for m in moved})
        stamp = self._stamp(checked_actor, checked_trigger)
        logged = 0
        for member in moved:
            self._remove(state, source, member, stamp)
            logged += 1
            if member in state.stories[target].entries:
                continue
            self._add(state, target, member, stamp)
            logged += 1
        self._carry(state, carried, target)
        return StoryOutcome(story_id=target, logged=logged)

    # --- the page: writes (ADR-0300 §3) --------------------------------------

    def _page_refusal(self, story_id: str) -> StoryPageRefusal | None:
        story = self._state.stories.get(story_id)
        if story is None:
            return StoryPageRefusal(reason=StoryPageRefusalReason.UNKNOWN_STORY, story_id=story_id)
        if story.merged_into is not None:
            return StoryPageRefusal(
                reason=StoryPageRefusalReason.MERGED_STORY,
                story_id=story_id,
                merged_into=story.merged_into,
            )
        return None

    async def append_note(
        self,
        story_id: Identifier,
        text: str,
        *,
        author: StoryNoteAuthor,
        rests_on: Identifier | None = None,
        outside: bool = False,
    ) -> StoryNoteOutcome:
        """Write a note to a story's page, pending there (ADR-0300 §3)."""
        target = _checked_id(story_id)
        checked_text, checked_author, checked_rests, checked_outside = _note_args(
            text, author=author, rests_on=rests_on, outside=outside
        )
        if refused := self._page_refusal(target):
            return StoryNoteOutcome(refusal=refused)
        at = self._now()
        state = self._state
        note = StoryNote(
            note_id=_tick(state),
            text=checked_text,
            author=checked_author,
            rests_on=checked_rests,
            outside=checked_outside,
            written_at=at,
        )
        state.notes[note.note_id] = _Held(note=note, story_id=target, pending_since=note.note_id)
        return StoryNoteOutcome(note=note)

    async def write_page(
        self,
        story_id: Identifier,
        draft: StoryPageDraft,
        *,
        as_of: int,
    ) -> StoryPageOutcome:
        """Write a new current page with its safety-net notes and its version."""
        target = _checked_id(story_id)
        checked = _page_draft(target, draft)
        basis = check_story_as_of(as_of)
        if refused := self._page_refusal(target):
            return StoryPageOutcome(refusal=refused)
        state = self._state
        if basis > state.tick:
            msg = "a page's as_of is one no read of this store has returned"
            raise ValueError(msg)
        if refused := self._draft_refusal(state, target, checked, basis):
            return StoryPageOutcome(refusal=refused)
        at = self._now()
        return StoryPageOutcome(version=self._page_writes(state, target, checked, basis, at))

    @staticmethod
    def _draft_refusal(
        state: _State, story_id: str, draft: StoryPageDraft, as_of: int
    ) -> StoryPageRefusal | None:
        if any(sid == story_id and v.version > as_of for sid, v in state.versions):
            return StoryPageRefusal(reason=StoryPageRefusalReason.PAGE_MOVED_ON, story_id=story_id)
        named = [note for line in draft.lines for note in line.cites]
        named += [mark.note for mark in draft.supersessions]
        owners: dict[int, str] = {}
        for note_id in _unique(named):
            held = state.notes.get(note_id)
            if held is None:
                return StoryPageRefusal(
                    reason=StoryPageRefusalReason.UNKNOWN_NOTE, story_id=story_id, note=note_id
                )
            if held.note.author is StoryNoteAuthor.OWNER:
                owners[note_id] = held.note.text
        for flag in draft.flags:
            if flag.story is not None and flag.story not in state.stories:
                return StoryPageRefusal(
                    reason=StoryPageRefusalReason.UNKNOWN_STORY, story_id=flag.story
                )
        if _page_size(draft, owners) > STORY_PAGE_CAP_CHARS:
            return StoryPageRefusal(reason=StoryPageRefusalReason.OVER_CAP, story_id=story_id)
        return None

    @staticmethod
    def _page_writes(
        state: _State, story_id: str, draft: StoryPageDraft, as_of: int, at: datetime
    ) -> StoryPageVersion:
        safety_net: list[int] = []
        for added in draft.safety_net:
            note = StoryNote(
                note_id=_tick(state),
                text=added.text,
                author=StoryNoteAuthor.TIDY_UP,
                rests_on=added.rests_on,
                outside=added.outside,
                written_at=at,
            )
            # Taken in by the version that adds it, so never pending on this story.
            state.notes[note.note_id] = _Held(note=note, story_id=story_id, pending_since=None)
            safety_net.append(note.note_id)
        took_notes: list[int] = []
        for note_id in _unique(draft.took_in_notes):
            held = state.notes.get(note_id)
            if (
                held is not None
                and held.story_id == story_id
                and held.pending_since is not None
                and held.pending_since <= as_of
            ):
                held.pending_since = None
                took_notes.append(note_id)
        pending = state.stories[story_id].pending
        took_episodes: list[str] = []
        for activation in _unique(draft.took_in_episodes):
            since = pending.get(activation)
            if since is not None and since <= as_of:
                del pending[activation]
                took_episodes.append(activation)
        lines = tuple(
            StoryPageLine(
                text=line.text,
                cites=tuple(_unique([*line.cites, *(safety_net[i] for i in line.cites_new)])),
                outside=line.outside,
            )
            for line in draft.lines
        )
        version = StoryPageVersion(
            version=_tick(state),
            written_at=at,
            lines=tuple(line.cites for line in lines),
            safety_net=tuple(safety_net),
            took_in_notes=tuple(took_notes),
            took_in_episodes=tuple(took_episodes),
            supersessions=draft.supersessions,
            flags=draft.flags,
        )
        state.versions.append((story_id, version))
        state.pages[story_id] = StoryCurrentPage(
            version=version.version, written_at=at, lines=lines
        )
        return version

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

    # --- the page: reads (ADR-0300 §3) ---------------------------------------

    async def current_page(self, story_id: Identifier) -> StoryPageState | None:
        """Read a story's current page with the notes and episodes pending on it."""
        target = _checked_id(story_id)
        state = self._state
        story = state.stories.get(target)
        if story is None:
            return None
        notes = sorted(
            (
                held.note
                for held in state.notes.values()
                if held.story_id == target and held.pending_since is not None
            ),
            key=lambda note: note.note_id,
        )
        episodes = [
            entry.member.id
            for entry in sorted(story.entries.values(), key=lambda entry: entry.position)
            if entry.member.kind is StoryMemberKind.ACTIVATION and entry.member.id in story.pending
        ]
        return StoryPageState(
            story=self._header_of(target, story),
            page=state.pages.get(target),
            pending_notes=tuple(notes),
            pending_episodes=tuple(episodes),
            as_of=state.tick,
        )

    async def notes(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryNoteList | None:
        """Read a page of the notes a story holds, in the order they were written."""
        target = _checked_id(story_id)
        check_story_page(cursor, limit)
        story = self._state.stories.get(target)
        if story is None:
            return None
        after = -1 if cursor is None else cursor
        rest = sorted(
            (
                held.note
                for held in self._state.notes.values()
                if held.story_id == target and held.note.note_id > after
            ),
            key=lambda note: note.note_id,
        )
        page = rest[:limit]
        return StoryNoteList(
            story=self._header_of(target, story),
            notes=tuple(page),
            next_cursor=page[-1].note_id if len(rest) > limit else None,
        )

    async def page_versions(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryPageVersionList | None:
        """Read a page of a story's version log, oldest first."""
        target = _checked_id(story_id)
        check_story_page(cursor, limit)
        story = self._state.stories.get(target)
        if story is None:
            return None
        after = -1 if cursor is None else cursor
        rest = [
            version
            for sid, version in self._state.versions
            if sid == target and version.version > after
        ]
        page = rest[:limit]
        return StoryPageVersionList(
            story=self._header_of(target, story),
            versions=tuple(page),
            next_cursor=page[-1].version if len(rest) > limit else None,
        )
