"""The canonical ``StoryStore`` fake (ADR-0289 §1, ADR-0300 §3, ADR-0303 §§2-8).

The triad's third artifact. A non-persistent store over dictionaries, holding every
clause the SQLite store holds and refusing everything it refuses, so a consumer
verified against this one is verified against the contract rather than against a
convenience: the clean view and the change log, the five membership reads, merge,
split and move with their exceptions and the notes they carry, logged on both stories
by a split or a move (ADR-0304 §9), a move of notes alone, the loop refusal,
each story's notes and summary — its summary with its mark, its version log and
what is pending on it — and the decisions on flags, written as ``decided`` lines
with the change they record (ADR-0302 §§2-4), ``left`` or ``not_applied`` where none
changed (ADR-0303 §8), and a summary write refused over what its story does not hold
(ADR-0302 §7).

**Atomic by construction.** Every write computes its refusal and applies its changes
with no ``await`` in between, so on one event loop a write is never interleaved with
another — the property the durable store buys with one transaction. A merge whose
result would close a loop is applied to a copy and discarded, so a refused write
leaves nothing behind.

**One counter for the notes' and the summary's records**, as the durable store keeps: a note's
identity, a version's, and the moment a note or an activation member became pending
on a story are drawn from it, and a summary read reports it as its ``as_of``.
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
    STORY_SUMMARY_CAP_CHARS,
    Identifier,
    StoryActor,
    StoryChange,
    StoryDecision,
    StoryEntry,
    StoryFlagName,
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
    StoryRefusal,
    StoryRefusalReason,
    StorySummary,
    StorySummaryDraft,
    StorySummaryOutcome,
    StorySummaryRefusal,
    StorySummaryRefusalReason,
    StorySummaryState,
    StorySummaryVersion,
    StorySummaryVersionList,
    StoryViewPage,
    check_story_as_of,
    check_story_page,
    story_members,
    story_note_ids,
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


def _unique[T](items: Sequence[T]) -> list[T]:
    return list(dict.fromkeys(items))


def _answers(answers: object) -> StoryFlagName | None:
    """Snapshot the flag a write answers by revalidation, or ``None`` for none."""
    if answers is None:
        return None
    if not isinstance(answers, StoryFlagName):
        msg = f"a write answers a StoryFlagName, got {type(answers).__name__}"
        raise ValueError(msg)
    return StoryFlagName.model_validate(answers.model_dump())


def _grouping(members: Sequence[StoryMember], answers: StoryFlagName | None) -> None:
    """Refuse an activation member on a create or a link answering a flag (ADR-0302 §4:3)."""
    if answers is not None and any(m.kind is not StoryMemberKind.STORY for m in members):
        msg = "a create or a link answering a flag names story members only"
        raise ValueError(msg)


# The notes' and the summary's argument checks and the cap rule, held here as the
# durable store holds its own: they are the contract's admission rules, not semantics
# intrinsic to the types (ADR-0016 §2), and the conformance suite keeps the two copies
# in step.


def _note_args(
    text: object, *, author: object, written_during: object, outside: object
) -> tuple[str, StoryNoteAuthor, str | None, bool]:
    """Check a note an append writes; nothing writes one as ``tidy_up`` (ADR-0303 §2:1)."""
    if not isinstance(author, str):
        msg = f"a note's author must be a StoryNoteAuthor, got {type(author).__name__}"
        raise ValueError(msg)
    if StoryNoteAuthor(author) is StoryNoteAuthor.TIDY_UP:
        msg = "the tidy-up writes no note"
        raise ValueError(msg)
    checked = StoryNote(
        note_id=1,
        text=text,  # type: ignore[arg-type]  # validated by the model, which is the point
        author=StoryNoteAuthor(author),
        written_during=written_during,  # type: ignore[arg-type]  # validated by the model
        outside=outside,  # type: ignore[arg-type]  # validated by the model
        written_at=datetime(1970, 1, 1, tzinfo=UTC),
    )
    return checked.text, checked.author, checked.written_during, checked.outside


def _summary_draft(story_id: str, draft: object) -> StorySummaryDraft:
    """Snapshot a summary write's draft, refusing a flag or a summary read naming its story."""
    if not isinstance(draft, StorySummaryDraft):
        msg = f"a summary write takes a StorySummaryDraft, got {type(draft).__name__}"
        raise ValueError(msg)
    snapshot = StorySummaryDraft.model_validate(draft.model_dump())
    if any(flag.story == story_id for flag in snapshot.flags):
        msg = "a flag names another story, never the one whose summary it is raised on"
        raise ValueError(msg)
    if any(read.story == story_id for read in snapshot.read_pages):
        msg = "a summary version read is another story's, never the one whose summary is written"
        raise ValueError(msg)
    return snapshot


def _leave_outcome(outcome: object) -> StoryDecision:
    """The outcome a ``leave_flag`` records: ``left`` or ``not_applied`` (ADR-0303 §8)."""
    if not isinstance(outcome, str):
        msg = f"a decision's outcome must be a StoryDecision, got {type(outcome).__name__}"
        raise ValueError(msg)
    checked = StoryDecision(outcome)
    if checked not in {StoryDecision.LEFT, StoryDecision.NOT_APPLIED}:
        msg = "leave_flag records left or not_applied, the outcomes that change no story"
        raise ValueError(msg)
    return checked


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


def _summary_size(draft: StorySummaryDraft) -> int:
    """The characters counted against the cap: every line (ADR-0303 §4:5)."""
    return sum(len(line.text) for line in draft.lines)


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
    summaries: dict[str, StorySummary] = field(default_factory=dict)
    versions: list[tuple[str, StorySummaryVersion]] = field(default_factory=list)


def _not_held(state: _State, story_id: str, draft: StorySummaryDraft) -> StorySummaryRefusal | None:
    """The first thing a draft takes in that its story does not hold (ADR-0302 §7).

    The episodes taken in, then the notes taken in, each against what the story holds
    as the write runs.
    """
    entries = state.stories[story_id].entries
    for activation in draft.took_in_episodes:
        if StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation) not in entries:
            return StorySummaryRefusal(
                reason=StorySummaryRefusalReason.NOT_HELD, story_id=story_id, activation=activation
            )
    for note_id in draft.took_in_notes:
        held = state.notes.get(note_id)
        if held is None or held.story_id != story_id:
            return StorySummaryRefusal(
                reason=StorySummaryRefusalReason.NOT_HELD, story_id=story_id, note=note_id
            )
    return None


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
        decision: tuple[StoryFlagName, StoryDecision] | None = None,
        note: int | None = None,
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
                answers=None if decision is None else decision[0],
                outcome=None if decision is None else decision[1],
                note=note,
            )
        )
        return state.sequence

    # --- decisions on flags (ADR-0302 §§2-4) ---------------------------------

    @staticmethod
    def _followed(state: _State, story_id: str) -> str:
        """The story ``story_id`` was merged into, through every merge, or itself."""
        seen = {story_id}
        while (onward := state.stories[story_id].merged_into) is not None:
            if onward in seen:  # pragma: no cover — a merged story is never merged into
                msg = f"story {story_id!r} is merged into a chain that loops"
                raise StoryStoreError(msg)
            seen.add(onward)
            story_id = onward
        return story_id

    def _flag_refusal(self, state: _State, flag: StoryFlagName) -> StoryRefusal | None:
        """``unknown_flag``, then ``already_decided`` (ADR-0302 §4:4, §4:5).

        A flag named by an activation is never held (ADR-0303 §8).
        """
        if flag.activation is not None:
            held = False
        else:
            held = any(
                story_id == flag.story
                and version.version == flag.version
                and flag.flag in version.flags
                for story_id, version in state.versions
            )
        if not held:
            return StoryRefusal(reason=StoryRefusalReason.UNKNOWN_FLAG, flag=flag)
        if any(line.change is StoryChange.DECIDED and line.answers == flag for line in state.log):
            return StoryRefusal(reason=StoryRefusalReason.ALREADY_DECIDED, flag=flag)
        return None

    def _concerned(self, state: _State, flag: StoryFlagName) -> list[str]:
        """The stories a held flag concerns, followed through merges, each once (§2:3)."""
        assert flag.story is not None  # noqa: S101 — a held flag is a tidy-up's (§8)
        assert flag.flag is not None  # noqa: S101 — a held flag is a tidy-up's (§8)
        raised = [flag.story] if flag.flag.story is None else [flag.story, flag.flag.story]
        return _unique([self._followed(state, story_id) for story_id in raised])

    def _decide(
        self, state: _State, flag: StoryFlagName, outcome: StoryDecision, stamp: _Stamp
    ) -> list[str]:
        """Write one ``decided`` line on each story the flag concerns (§3:4)."""
        decided = _Stamp(actor=stamp.actor, trigger=None, at=stamp.at)
        concerned = self._concerned(state, flag)
        for story_id in concerned:
            self._append(state, story_id, StoryChange.DECIDED, decided, decision=(flag, outcome))
        return concerned

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

    def _carry_logged(
        self, state: _State, note_ids: Sequence[int], source: str, target: str, stamp: _Stamp
    ) -> int:
        """Carry notes a split or a move names, logging each on both stories (ADR-0304 §9:6).

        Each note is logged ``note_moved_out`` on ``source`` and ``note_moved_in`` on
        ``target``, in note order, and returns how many lines that appended.
        """
        for note_id in note_ids:
            self._append(
                state, source, StoryChange.NOTE_MOVED_OUT, stamp, other=target, note=note_id
            )
            self._append(
                state, target, StoryChange.NOTE_MOVED_IN, stamp, other=source, note=note_id
            )
        self._carry(state, note_ids, target)
        return 2 * len(note_ids)

    @staticmethod
    def _named_notes(state: _State, story_id: str, named: Sequence[int]) -> list[int]:
        """The notes named that ``story_id`` holds, whoever wrote them (ADR-0303 §6:2)."""
        return sorted(
            note_id
            for note_id in set(named)
            if (held := state.notes.get(note_id)) is not None and held.story_id == story_id
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
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Mint a story holding ``members`` (ADR-0289 §3, ADR-0302 §4)."""
        named = story_members(members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        flag = _answers(answers)
        _grouping(named, flag)
        if not named:
            return StoryOutcome(refusal=StoryRefusal(reason=StoryRefusalReason.NO_MEMBERS))
        state = self._state
        if refused := self._members_refusal(state, named):
            return StoryOutcome(refusal=refused)
        if flag is not None and (refused := self._flag_refusal(state, flag)):
            return StoryOutcome(refusal=refused)
        stamp = self._stamp(checked_actor, checked_trigger)
        story_id = self._mint(state, stamp)
        unique = _unique(named)
        for member in unique:
            self._add(state, story_id, member, stamp)
        decided = [] if flag is None else self._decide(state, flag, StoryDecision.GROUPED, stamp)
        return StoryOutcome(story_id=story_id, logged=1 + len(unique) + len(decided))

    async def link(
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Add ``members`` to a story (ADR-0289 §3, ADR-0302 §4)."""
        target = _checked_id(story_id)
        named = story_members(members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        flag = _answers(answers)
        _grouping(named, flag)
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
        if flag is not None and (refused := self._flag_refusal(state, flag)):
            return StoryOutcome(refusal=refused)
        stamp = self._stamp(checked_actor, checked_trigger)
        for member in fresh:
            self._add(state, target, member, stamp)
        decided = [] if flag is None else self._decide(state, flag, StoryDecision.GROUPED, stamp)
        return StoryOutcome(story_id=target, logged=len(fresh) + len(decided))

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
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Merge story ``story_id`` into story ``into`` (ADR-0289 §3, ADR-0300 §3)."""
        absorbed = _checked_id(story_id)
        target = _checked_id(into)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        flag = _answers(answers)
        if refused := self._story_refusal(self._state, absorbed) or self._story_refusal(
            self._state, target
        ):
            return StoryOutcome(refusal=refused)
        if absorbed == target:
            return StoryOutcome(
                refusal=StoryRefusal(reason=StoryRefusalReason.SELF_MERGE, story_id=absorbed)
            )
        # The flag is read off the records before the merge writes anything, and
        # reported only after the merge's own loop check (ADR-0302 §4:5).
        flag_refused = None if flag is None else self._flag_refusal(self._state, flag)
        stamp = self._stamp(checked_actor, checked_trigger)
        # Applied to a copy and kept only if no loop closed, so a refusal writes nothing.
        state = copy.deepcopy(self._state)
        try:
            logged = self._merge_writes(state, absorbed, target, stamp)
        except _Refused as refused_merge:
            return StoryOutcome(refusal=refused_merge.refusal)
        if flag_refused is not None:
            return StoryOutcome(refusal=flag_refused)
        if flag is not None:
            logged += len(self._decide(state, flag, StoryDecision.MERGED, stamp))
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

    async def split(  # noqa: PLR0913 — ADR-0302 §4:2 adds ``answers`` as a keyword to this operation
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
        notes: Sequence[StoryNoteId] = (),
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Move a non-empty subset of a story's members into a new story (ADR-0289 §3)."""
        source = _checked_id(story_id)
        named = story_members(members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        named_notes = story_note_ids(notes)
        flag = _answers(answers)
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
        carried = self._named_notes(state, source, named_notes)
        if flag is not None and (refused := self._flag_refusal(state, flag)):
            return StoryOutcome(refusal=refused)
        stamp = self._stamp(checked_actor, checked_trigger)
        split_off = self._mint(state, stamp)
        self._append(state, source, StoryChange.SPLIT_OFF, stamp, other=split_off)
        self._append(state, split_off, StoryChange.SPLIT_OFF, stamp, other=source)
        for member in moved:
            self._remove(state, source, member, stamp)
            self._add(state, split_off, member, stamp)
        noted = self._carry_logged(state, carried, source, split_off, stamp)
        decided = [] if flag is None else self._decide(state, flag, StoryDecision.SPLIT, stamp)
        return StoryOutcome(story_id=split_off, logged=3 + 2 * len(moved) + noted + len(decided))

    async def move(  # noqa: PLR0913 — ADR-0302 §4:2 and ADR-0303 §6:2 add keywords to this operation
        self,
        story_id: Identifier,
        to: Identifier,
        members: Sequence[StoryMember] = (),
        *,
        actor: StoryActor,
        trigger: Identifier | None = None,
        notes: Sequence[StoryNoteId] = (),
        answers: StoryFlagName | None = None,
    ) -> StoryOutcome:
        """Move activation members, notes, or both (ADR-0300 §3, ADR-0303 §6, ADR-0304 §9)."""
        source = _checked_id(story_id)
        target = _checked_id(to)
        named = _move_members(source, target, members)
        checked_actor, checked_trigger = _checked_write(actor, trigger)
        named_notes = story_note_ids(notes)
        flag = _answers(answers)
        # A move naming no member is a note move where it names a note (ADR-0304 §9:1-§9:2).
        if not named and not named_notes:
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
        carried = self._named_notes(state, source, named_notes)
        if not named and not carried:
            return StoryOutcome(
                refusal=StoryRefusal(reason=StoryRefusalReason.NO_NOTES, story_id=source)
            )
        if flag is not None and (refused := self._flag_refusal(state, flag)):
            return StoryOutcome(refusal=refused)
        stamp = self._stamp(checked_actor, checked_trigger)
        logged = 0
        for member in moved:
            self._remove(state, source, member, stamp)
            logged += 1
            if member in state.stories[target].entries:
                continue
            self._add(state, target, member, stamp)
            logged += 1
        logged += self._carry_logged(state, carried, source, target, stamp)
        if flag is not None:
            logged += len(self._decide(state, flag, StoryDecision.MOVED, stamp))
        return StoryOutcome(story_id=target, logged=logged)

    async def leave_flag(
        self,
        flag: StoryFlagName,
        *,
        actor: StoryActor,
        outcome: StoryDecision = StoryDecision.LEFT,
    ) -> StoryOutcome:
        """Record a decision on a flag that changed no story (ADR-0302 §4:1, ADR-0303 §8)."""
        checked = _answers(flag)
        if checked is None:
            msg = "leave_flag takes the flag it decides"
            raise ValueError(msg)
        checked_actor, _ = _checked_write(actor, None)
        recorded = _leave_outcome(outcome)
        state = self._state
        if refused := self._flag_refusal(state, checked):
            return StoryOutcome(refusal=refused)
        decided = self._decide(state, checked, recorded, self._stamp(checked_actor, None))
        return StoryOutcome(story_id=decided[0], logged=len(decided))

    # --- the notes and the summary: writes (ADR-0300 §3) ----------------------

    def _summary_refusal(self, story_id: str) -> StorySummaryRefusal | None:
        story = self._state.stories.get(story_id)
        if story is None:
            return StorySummaryRefusal(
                reason=StorySummaryRefusalReason.UNKNOWN_STORY, story_id=story_id
            )
        if story.merged_into is not None:
            return StorySummaryRefusal(
                reason=StorySummaryRefusalReason.MERGED_STORY,
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
        written_during: Identifier | None = None,
        outside: bool = False,
    ) -> StoryNoteOutcome:
        """Write a note to a story, pending there (ADR-0303 §2, §4:7)."""
        target = _checked_id(story_id)
        checked_text, checked_author, checked_during, checked_outside = _note_args(
            text, author=author, written_during=written_during, outside=outside
        )
        if refused := self._summary_refusal(target):
            return StoryNoteOutcome(refusal=refused)
        at = self._now()
        state = self._state
        note = StoryNote(
            note_id=_tick(state),
            text=checked_text,
            author=checked_author,
            written_during=checked_during,
            outside=checked_outside,
            written_at=at,
        )
        state.notes[note.note_id] = _Held(note=note, story_id=target, pending_since=note.note_id)
        return StoryNoteOutcome(note=note)

    async def write_summary(
        self,
        story_id: Identifier,
        draft: StorySummaryDraft,
        *,
        as_of: int,
    ) -> StorySummaryOutcome:
        """Write a new summary and its version, and no note (ADR-0303 §4)."""
        target = _checked_id(story_id)
        checked = _summary_draft(target, draft)
        basis = check_story_as_of(as_of)
        if refused := self._summary_refusal(target):
            return StorySummaryOutcome(refusal=refused)
        state = self._state
        if basis > state.tick:
            msg = "a summary's as_of is one no read of this store has returned"
            raise ValueError(msg)
        if refused := self._draft_refusal(state, target, checked, basis):
            return StorySummaryOutcome(refusal=refused)
        at = self._now()
        return StorySummaryOutcome(version=self._summary_writes(state, target, checked, basis, at))

    @staticmethod
    def _draft_refusal(
        state: _State, story_id: str, draft: StorySummaryDraft, as_of: int
    ) -> StorySummaryRefusal | None:
        """The summary's refusals after the story's own, in ADR-0303 §4:4's order."""
        if any(sid == story_id and v.version > as_of for sid, v in state.versions):
            return StorySummaryRefusal(
                reason=StorySummaryRefusalReason.SUMMARY_MOVED_ON, story_id=story_id
            )
        for flag in draft.flags:
            if flag.story is not None and flag.story not in state.stories:
                return StorySummaryRefusal(
                    reason=StorySummaryRefusalReason.UNKNOWN_STORY, story_id=flag.story
                )
        for read in draft.read_pages:
            if read.story not in state.stories:
                return StorySummaryRefusal(
                    reason=StorySummaryRefusalReason.UNKNOWN_STORY, story_id=read.story
                )
            if not any(
                sid == read.story and v.version == read.version for sid, v in state.versions
            ):
                msg = "a summary version read names a version its story's log does not hold"
                raise ValueError(msg)
        if refused := _not_held(state, story_id, draft):
            return refused
        if _summary_size(draft) > STORY_SUMMARY_CAP_CHARS:
            return StorySummaryRefusal(reason=StorySummaryRefusalReason.OVER_CAP, story_id=story_id)
        return None

    @staticmethod
    def _summary_writes(
        state: _State, story_id: str, draft: StorySummaryDraft, as_of: int, at: datetime
    ) -> StorySummaryVersion:
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
        version = StorySummaryVersion(
            version=_tick(state),
            written_at=at,
            took_in_notes=tuple(took_notes),
            took_in_episodes=tuple(took_episodes),
            read_pages=tuple(_unique(draft.read_pages)),
            flags=draft.flags,
            outside=draft.outside,
        )
        state.versions.append((story_id, version))
        state.summaries[story_id] = StorySummary(
            version=version.version, written_at=at, lines=draft.lines, outside=draft.outside
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

    # --- the notes and the summary: reads (ADR-0300 §3) -----------------------

    async def current_summary(self, story_id: Identifier) -> StorySummaryState | None:
        """Read a story's summary with the notes and episodes pending on it."""
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
        return StorySummaryState(
            story=self._header_of(target, story),
            summary=state.summaries.get(target),
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

    async def summary_versions(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StorySummaryVersionList | None:
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
        return StorySummaryVersionList(
            story=self._header_of(target, story),
            versions=tuple(page),
            next_cursor=page[-1].version if len(rest) > limit else None,
        )
