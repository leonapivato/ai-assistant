"""The flags a story store's records hold, and the decisions recorded on them (ADR-0302 §§2-3).

Read by the matters pass (§5) and by the tidy-up (§6); neither is a Protocol, and this
module is the one place both work the two questions out from the store's own records.

**What names a flag** (§2, ADR-0303 §8:1-§8:3). A tidy-up's flags are the only flags:
each is named by the story whose page version recorded it, that version's number and
the flag as recorded. Understanding linking one input to two stories is that many links
and raises none, so no flag is ever read from the change logs. A ``decided`` line that
already answers a flag named by an activation, written before ADR-0303, stays in the
log and is still read as a decision. The stories a flag **concerns** are, for a
tidy-up's, the story that raised it and then, on ``like_another``, the story it names;
for one named by an activation, as an earlier decision answering it names them, each
story holding an ``added`` line naming that activation with the actor
``understanding`` and that activation as trigger, in the order of their sequence
numbers; each followed through merges to the story it was merged into, and each counted
once, at its first place.

**The decisions recorded for a story** (§3:6) are the ``decided`` lines on its own
change log and on the change log of every story merged into it, directly or through a
chain of merges, as its ``absorbed`` lines and theirs name them. One decision writes a
line on each story its flag concerned, so the lines are gathered into one decision per
flag answered: a flag is decided once (§5:1), so its lines are one decision's.

**No store read answers either question**, and ADR-0302 left the read of undecided
flags open (*What stays open*): which flags a ``decided`` line answers, and the stories
an earlier decision on an activation's flag concerns, are found only by reading change
logs. So :func:`read_records` reads every story's header and change log, and, for the
pass, its version log, page by page. What that costs grows with the store, which the
test hub is where to measure.

**It holds identities and instants only**: no story's page text and no note is read
here, so nothing of it can reach a log line (ADR-0275 §8).
"""

from __future__ import annotations

from dataclasses import dataclass
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
    """A flag the store's records hold: a tidy-up's (ADR-0302 §2, ADR-0303 §8:3).

    Attributes:
        name: The flag's name, as a decision answers it.
        raised: The stories it concerns as raised, before any is followed through a
            merge: the story that raised it, then on ``like_another`` the story it
            names.
        at: When it was raised: the instant of the version that recorded it.
        sequence: A tie-break in the order flags were raised: that version's number.
    """

    name: StoryFlagName
    raised: tuple[str, ...]
    at: datetime
    sequence: int

    @property
    def kind(self) -> StoryFlag | None:
        """The flag the tidy-up raised; never ``None`` from :meth:`StoryRecords.flags`."""
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
    """Whether ``line`` is one of understanding's lines for its activation (§2:2).

    Read only for the stories an earlier decision answering an activation's flag
    concerns: such lines raise no flag (ADR-0303 §8:1).
    """
    return (
        line.change is StoryChange.ADDED
        and line.member is not None
        and line.member.kind is StoryMemberKind.ACTIVATION
        and line.actor is StoryActor.UNDERSTANDING
        and line.trigger == line.member.id
    )


class StoryRecords:
    """What one read of the story store holds of its flags and decisions.

    Its indexes, understanding's lines by activation and the set of flags a decision
    answers, are each built once, on first use, in one walk of the logs; a copy with
    fresh headers (:meth:`with_headers`) shares them, since headers carry no line.

    Attributes:
        headers: Every story's header, by id.
        logs: Every story's change log, by id, in sequence order.
        versions: Every story's version log, by id, oldest first; empty where the
            read did not ask for them.
    """

    __slots__ = ("_decided", "_understanding", "headers", "logs", "versions")

    def __init__(
        self,
        *,
        headers: dict[str, StoryHeader],
        logs: dict[str, tuple[StoryLogLine, ...]],
        versions: dict[str, tuple[StoryPageVersion, ...]] | None = None,
    ) -> None:
        """Hold one read's records; nothing is walked until a question needs it."""
        self.headers = headers
        self.logs = logs
        self.versions = {} if versions is None else versions
        self._understanding: dict[str, list[StoryLogLine]] | None = None
        self._decided: frozenset[StoryFlagName] | None = None

    def with_headers(self, headers: dict[str, StoryHeader]) -> StoryRecords:
        """These records with ``headers`` in place of their own, sharing their indexes."""
        fresh = StoryRecords(headers=headers, logs=self.logs, versions=self.versions)
        fresh._understanding = self._understanding
        fresh._decided = self._decided
        return fresh

    def _lines(self) -> dict[str, list[StoryLogLine]]:
        """Understanding's lines by their activation, in sequence order, built once."""
        if self._understanding is None:
            index: dict[str, list[StoryLogLine]] = {}
            for lines in self.logs.values():
                for line in lines:
                    if _is_understandings_line(line):
                        assert line.member is not None  # noqa: S101 — _is_understandings_line's own test
                        index.setdefault(line.member.id, []).append(line)
            for indexed in index.values():
                indexed.sort(key=lambda line: line.sequence)
            self._understanding = index
        return self._understanding

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
            return _unique(line.story_id for line in self._lines().get(flag.activation, ()))
        assert flag.story is not None  # noqa: S101 — StoryFlagName's own rule
        assert flag.flag is not None  # noqa: S101 — StoryFlagName's own rule
        named = flag.flag.story
        return (flag.story,) if named is None else _unique((flag.story, named))

    def concerned(self, flag: StoryFlagName) -> tuple[str, ...]:
        """The stories ``flag`` concerns, followed through merges, each once (§2:3)."""
        return _unique(self.followed(story_id) for story_id in self.raised(flag))

    def flags(self) -> list[RaisedFlag]:
        """Every flag these records hold, in the order they were raised (§2).

        A tidy-up's flags only (ADR-0303 §8): understanding linking one input to two
        stories is that many links and no flag, so its lines raise none, and the store
        refuses a write answering one ``unknown_flag``. They are still read for the
        stories a ``decided`` line already answering one concerns (:meth:`raised`).
        """
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
        raised.sort(key=lambda flag: (flag.at, flag.sequence))
        return raised

    def decided(self) -> frozenset[StoryFlagName]:
        """Every flag a ``decided`` line answers, worked out once."""
        if self._decided is None:
            self._decided = frozenset(
                line.answers
                for lines in self.logs.values()
                for line in lines
                if line.change is StoryChange.DECIDED and line.answers is not None
            )
        return self._decided

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
    """``records`` with ``story_ids`` read again, and every story merged into them.

    The header and change log of each story named, then of each story its ``absorbed``
    lines name, and theirs in turn, each once: the decisions recorded for a story are
    on all of their logs (§3:6), so none of them is left as an earlier read had it. A
    story ``records`` did not hold, such as one a split or a create minted since, is
    added. Version logs are kept as they were: no membership write appends a version.

    Raises:
        StoryStoreError: If the store cannot be read.
    """
    headers = dict(records.headers)
    logs = dict(records.logs)
    versions = dict(records.versions)
    done: set[str] = set()
    queue = list(dict.fromkeys(story_ids))
    while queue:
        story_id = queue.pop(0)
        if story_id in done:
            continue
        done.add(story_id)
        header = await stories.header(story_id)
        if header is None:
            continue
        headers[story_id] = header
        logs[story_id] = await read_log(stories, story_id)
        versions.setdefault(story_id, ())
        queue.extend(_absorbed(logs[story_id]))
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
