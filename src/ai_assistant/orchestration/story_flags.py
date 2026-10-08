"""The flags a story store's records hold, and the decisions recorded on them (ADR-0302 §§2-3).

Read by the matters pass (§5) and by the tidy-up (§6); neither is a Protocol, and this
module is the one place both work the two questions out from the store's own records.

**What names a flag** (§2). A tidy-up's flag is named by the story whose page version
recorded it, that version's number and the flag as recorded. Understanding's is named
by its activation, and exists where ``added`` lines naming that activation, with the
actor ``understanding`` and that activation as trigger, stand on two or more stories.
The stories a flag **concerns** are, for a tidy-up's, the story that raised it and
then, on ``like_another``, the story it names; for understanding's, each story holding
one of those lines, in the order of their sequence numbers; each followed through
merges to the story it was merged into, and each counted once, at its first place.

**The decisions recorded for a story** (§3:6) are the ``decided`` lines on its own
change log and on the change log of every story merged into it, directly or through a
chain of merges, as its ``absorbed`` lines and theirs name them. One decision writes a
line on each story its flag concerned, so the lines are gathered into one decision per
flag answered: a flag is decided once (§5:1), so its lines are one decision's.

**No store read answers either question**, and ADR-0302 left the read of undecided
flags open (*What stays open*): the stories holding understanding's lines for an
activation are found only by reading change logs. So :func:`read_records` reads every
story's header and change log, and, for the pass, its version log, page by page. What
that costs grows with the store, which the test hub is where to measure.

**It holds identities and instants only**: no story's page text and no note is read
here, so nothing of it can reach a log line (ADR-0275 §8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    StoryActor,
    StoryChange,
    StoryFlagName,
    StoryMemberKind,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from ai_assistant.core.protocols import StoryStore
    from ai_assistant.core.types import (
        StoryDecision,
        StoryFlag,
        StoryHeader,
        StoryLogLine,
        StoryPageVersion,
    )

__all__ = [
    "RaisedFlag",
    "RecordedDecision",
    "StoryRecords",
    "decisions_of",
    "read_records",
    "recorded_decisions",
    "reread",
]


@dataclass(frozen=True, slots=True)
class RaisedFlag:
    """A flag the store's records hold (ADR-0302 §2).

    Attributes:
        name: The flag's name, as a decision answers it.
        raised: The stories it concerns as raised, before any is followed through a
            merge: for a tidy-up's flag the story that raised it, then on
            ``like_another`` the story it names; for understanding's the stories
            holding its lines, by their first line's sequence number.
        at: When it was raised: the version's instant for a tidy-up's flag, and for
            understanding's the instant of the line that made it a flag, its second
            story's first.
        sequence: A tie-break in the order flags were raised: the version number for
            a tidy-up's, and that line's sequence number for understanding's.
    """

    name: StoryFlagName
    raised: tuple[str, ...]
    at: datetime
    sequence: int

    @property
    def kind(self) -> StoryFlag | None:
        """The flag a tidy-up raised, or ``None`` for understanding's."""
        return self.name.flag


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """One decision recorded on a flag (ADR-0302 §3).

    Attributes:
        flag: The flag it answers.
        outcome: What was decided.
        at: When it was recorded: its lines' instant.
        sequence: The newest sequence number among the lines of it that were read,
            which orders decisions newest first.
    """

    flag: StoryFlagName
    outcome: StoryDecision
    at: datetime
    sequence: int


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _is_understandings_line(line: StoryLogLine) -> bool:
    """Whether ``line`` is one of understanding's lines for its activation (§2:2)."""
    return (
        line.change is StoryChange.ADDED
        and line.member is not None
        and line.member.kind is StoryMemberKind.ACTIVATION
        and line.actor is StoryActor.UNDERSTANDING
        and line.trigger == line.member.id
    )


@dataclass(frozen=True, slots=True)
class StoryRecords:
    """What one read of the story store holds of its flags and decisions.

    Attributes:
        headers: Every story's header, by id.
        logs: Every story's change log, by id, in sequence order.
        versions: Every story's version log, by id, oldest first; empty where the
            read did not ask for them.
    """

    headers: dict[str, StoryHeader]
    logs: dict[str, tuple[StoryLogLine, ...]]
    versions: dict[str, tuple[StoryPageVersion, ...]] = field(default_factory=dict)
    _understanding: dict[str, list[StoryLogLine]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Index understanding's lines by their activation, in sequence order."""
        index: dict[str, list[StoryLogLine]] = {}
        for lines in self.logs.values():
            for line in lines:
                if _is_understandings_line(line):
                    assert line.member is not None  # noqa: S101 — _is_understandings_line's own test
                    index.setdefault(line.member.id, []).append(line)
        for indexed in index.values():
            indexed.sort(key=lambda line: line.sequence)
        object.__setattr__(self, "_understanding", index)

    def followed(self, story_id: str) -> str:
        """The story ``story_id`` was merged into, through every merge, or itself.

        A story these records do not hold is answered as itself: nothing here says
        where it went.
        """
        seen = {story_id}
        while (header := self.headers.get(story_id)) is not None and (
            onward := header.merged_into
        ) is not None:
            if onward in seen:  # pragma: no cover — a merged story is never merged into
                return story_id
            seen.add(onward)
            story_id = onward
        return story_id

    def raised(self, flag: StoryFlagName) -> tuple[str, ...]:
        """The stories ``flag`` concerns as raised, before following merges (§2:3)."""
        if flag.activation is not None:
            return _unique(line.story_id for line in self._understanding.get(flag.activation, ()))
        assert flag.story is not None  # noqa: S101 — StoryFlagName's own rule
        assert flag.flag is not None  # noqa: S101 — StoryFlagName's own rule
        named = flag.flag.story
        return (flag.story,) if named is None else _unique((flag.story, named))

    def concerned(self, flag: StoryFlagName) -> tuple[str, ...]:
        """The stories ``flag`` concerns, followed through merges, each once (§2:3)."""
        return _unique(self.followed(story_id) for story_id in self.raised(flag))

    def flags(self) -> list[RaisedFlag]:
        """Every flag these records hold, in the order they were raised (§2)."""
        raised: list[RaisedFlag] = []
        for story_id, versions in self.versions.items():
            for version in versions:
                for flag in version.flags:
                    name = StoryFlagName(story=story_id, version=version.version, flag=flag)
                    raised.append(
                        RaisedFlag(
                            name=name,
                            raised=self.raised(name),
                            at=version.written_at,
                            sequence=version.version,
                        )
                    )
        for activation, lines in self._understanding.items():
            firsts: dict[str, StoryLogLine] = {}
            for line in lines:
                firsts.setdefault(line.story_id, line)
            if len(firsts) < 2:  # noqa: PLR2004 — §2:2's "two or more stories"
                continue
            second = list(firsts.values())[1]
            raised.append(
                RaisedFlag(
                    name=StoryFlagName(activation=activation),
                    raised=tuple(firsts),
                    at=second.at,
                    sequence=second.sequence,
                )
            )
        raised.sort(key=lambda flag: (flag.at, flag.sequence))
        return raised

    def decided(self) -> frozenset[StoryFlagName]:
        """Every flag a ``decided`` line answers."""
        return frozenset(
            line.answers
            for lines in self.logs.values()
            for line in lines
            if line.change is StoryChange.DECIDED and line.answers is not None
        )

    def decisions_for(self, story_id: str) -> list[RecordedDecision]:
        """The decisions recorded for ``story_id`` (§3:6), one per flag, newest first."""
        lineage: dict[str, None] = {}
        queue = [story_id]
        while queue:
            current = queue.pop(0)
            if current not in lineage:
                lineage[current] = None
                queue.extend(_absorbed(self.logs.get(current, ())))
        return decisions_of(line for current in lineage for line in self.logs.get(current, ()))


def decisions_of(lines: Iterable[StoryLogLine]) -> list[RecordedDecision]:
    """The ``decided`` lines among ``lines``, one decision per flag, newest first."""
    found: dict[StoryFlagName, RecordedDecision] = {}
    for line in lines:
        if line.change is not StoryChange.DECIDED or line.answers is None or line.outcome is None:
            continue
        held = found.get(line.answers)
        if held is None or line.sequence > held.sequence:
            found[line.answers] = RecordedDecision(
                flag=line.answers, outcome=line.outcome, at=line.at, sequence=line.sequence
            )
    return sorted(found.values(), key=lambda decision: decision.sequence, reverse=True)


def _absorbed(lines: Iterable[StoryLogLine]) -> list[str]:
    """The stories ``lines`` name as absorbed by a merge."""
    return [
        line.other_story
        for line in lines
        if line.change is StoryChange.ABSORBED and line.other_story is not None
    ]


# --- reading the store ---------------------------------------------------------------


async def read_log(stories: StoryStore, story_id: str) -> tuple[StoryLogLine, ...]:
    """Every line of ``story_id``'s change log, page by page; empty for no such story."""
    lines: list[StoryLogLine] = []
    cursor: int | None = None
    while True:
        page = await stories.log(story_id, cursor=cursor, limit=MAX_STORY_PAGE)
        if page is None:
            return tuple(lines)
        lines.extend(page.lines)
        if page.next_cursor is None or page.next_cursor == cursor:
            return tuple(lines)
        cursor = page.next_cursor


async def read_versions(stories: StoryStore, story_id: str) -> tuple[StoryPageVersion, ...]:
    """Every version of ``story_id``'s page, oldest first; empty for no such story."""
    versions: list[StoryPageVersion] = []
    cursor: int | None = None
    while True:
        page = await stories.page_versions(story_id, cursor=cursor, limit=MAX_STORY_PAGE)
        if page is None:
            return tuple(versions)
        versions.extend(page.versions)
        if page.next_cursor is None or page.next_cursor == cursor:
            return tuple(versions)
        cursor = page.next_cursor


async def read_headers(stories: StoryStore) -> dict[str, StoryHeader]:
    """Every story's header, merged stories included, by id."""
    headers: dict[str, StoryHeader] = {}
    cursor: int | None = None
    while True:
        page = await stories.stories(cursor=cursor, limit=MAX_STORY_PAGE)
        headers |= {header.story_id: header for header in page.stories}
        if page.next_cursor is None or page.next_cursor == cursor:
            return headers
        cursor = page.next_cursor


async def read_records(stories: StoryStore, *, versions: bool) -> StoryRecords:
    """Read every story's header and change log, and its version log where asked.

    Args:
        stories: The story store.
        versions: Whether to read every version log too, where a tidy-up's flags
            are recorded.

    Returns:
        The records.

    Raises:
        StoryStoreError: If the store cannot be read.
    """
    headers = await read_headers(stories)
    logs = {story_id: await read_log(stories, story_id) for story_id in headers}
    read = (
        {story_id: await read_versions(stories, story_id) for story_id in headers}
        if versions
        else {}
    )
    return StoryRecords(headers=headers, logs=logs, versions=read)


async def reread(
    records: StoryRecords, stories: StoryStore, story_ids: Iterable[str]
) -> StoryRecords:
    """``records`` with the headers and change logs of ``story_ids`` read again.

    A story ``records`` did not hold, such as one a split or a create minted since, is
    added. Version logs are kept as they were: no membership write appends a version.

    Raises:
        StoryStoreError: If the store cannot be read.
    """
    headers = dict(records.headers)
    logs = dict(records.logs)
    versions = dict(records.versions)
    for story_id in dict.fromkeys(story_ids):
        header = await stories.header(story_id)
        if header is None:
            continue
        headers[story_id] = header
        logs[story_id] = await read_log(stories, story_id)
        versions.setdefault(story_id, ())
    return StoryRecords(headers=headers, logs=logs, versions=versions)


async def recorded_decisions(stories: StoryStore, story_id: str) -> list[RecordedDecision]:
    """The decisions recorded for ``story_id`` (§3:6), read from its lineage alone.

    Its own change log, then the change log of every story its ``absorbed`` lines name,
    and theirs in turn, each once. Cheaper than :func:`read_records` and enough to say
    whether any decision is recorded for the story, though not which stories each
    decision's flag concerns, which needs every log for understanding's flags.

    Raises:
        StoryStoreError: If the store cannot be read.
    """
    logs: dict[str, tuple[StoryLogLine, ...]] = {}
    queue = [story_id]
    while queue:
        current = queue.pop(0)
        if current in logs:
            continue
        logs[current] = await read_log(stories, current)
        queue.extend(_absorbed(logs[current]))
    return decisions_of(line for lines in logs.values() for line in lines)
