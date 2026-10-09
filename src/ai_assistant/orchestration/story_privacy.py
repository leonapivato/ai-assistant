"""The privacy default for a story's notes and summary: which of them a reader sees.

ADR-0303 §3 rules it until privacy is designed. A note is shown to a reader only where
a record placed for the owner alone may be shown to that reader, whoever wrote it
(§3:9). The summary is shown only where **everything behind it** may be shown,
and otherwise none of it is, the reader being told that a summary was withheld (§3:11).
A note rests on nothing and a line cites nothing, so ADR-0300 §11:1's tests, which read
the episode a note rested on and the notes a line cited, are gone.

**What stands behind a summary version** (:func:`behind`, §3:10) is every note and every
episode it took in, and everything behind each summary version its run read: the summary it
replaced, which is its story's previous version, and each other story's summary the run
was shown for its flags (``StorySummaryVersion.read_pages``, §3:3). So it is cumulative
over the story's own versions, and it follows other stories' summaries however many
stories that reaches. It is read from the version logs alone, through
``StoryStore.summary_versions``, and each version is visited once, since a story's summary
can reach its own earlier versions through another's. No line's or note's text is
read.

**Each reader decides the rest with its own answers** (:class:`SummaryVisibility`): which
of the episodes behind the summary it may be shown, fetched and admitted by its own rule,
and whether it may be shown a record placed for the owner alone, which decides every
note. An episode behind the summary that the reader's caller cannot establish may be shown
— open where the reader is never shown an open one, forgotten, no longer held, or not
looked up — withholds the summary (§3:12), and so does a version the walk cannot read.

**The rule is decided here once, for every reader of a summary**: understanding's short
views and the owner's story summary view today, and planning's views once the phases build
them. Nothing of ADR-0300's summary is live outside a test hub until the phases' cutover
(ADR-0300 §13).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.types import MAX_STORY_PAGE

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.protocols import StoryStore
    from ai_assistant.core.types import EpisodicMemory, StoryNote, StorySummaryVersion

__all__ = ["Behind", "SummaryVisibility", "activation_of", "behind"]


def activation_of(record: EpisodicMemory) -> str | None:
    """The activation an episode records, or ``None`` for one that records none.

    Read off the episode's processing record (ADR-0275), never parsed out of its id:
    an episode written before activations were recorded has no processing record,
    and is the episode of no activation a story could hold.
    """
    processing = record.processing_record
    return None if processing is None else processing.activation_id


@dataclass(frozen=True, slots=True)
class Behind:
    """What stands behind one summary version (ADR-0303 §3:10), by identity alone.

    Attributes:
        notes: Every note a version behind it took in, by note id.
        episodes: Every episode a version behind it took in, by activation id.
        complete: Whether every version the walk reached could be read. A version the
            store no longer answers for — of a story it no longer holds, or one its
            story's log does not hold — stands behind the summary unread, and withholds
            it.
    """

    notes: frozenset[int]
    episodes: frozenset[str]
    complete: bool


async def behind(stories: StoryStore, story_id: str, version: int) -> Behind:
    """Walk everything behind ``story_id``'s summary ``version`` (ADR-0303 §3:10).

    The version and each earlier version on its story's log are behind it, because each
    run reads the summary it replaces; and so is everything behind each other story's summary
    version any of them read. One counter numbers every story's versions, so a story's
    earlier versions are those its log holds numbered below it. Each story's log is read
    once, and each version on it is visited at most once, however many paths reach it.
    The log is append-only, so a version read once is read for good, and a walk made
    after the summary was read answers for that summary.

    Args:
        stories: The story store whose version logs are read.
        story_id: The story whose summary is asked about.
        version: The version that wrote that summary.

    Returns:
        What stands behind it.

    Raises:
        ValueError: If ``story_id`` is malformed.
        StoryStoreError: If a version log cannot be read.
    """
    notes: set[int] = set()
    episodes: set[str] = set()
    complete = True
    logs: dict[str, dict[int, StorySummaryVersion] | None] = {}
    walked: dict[str, int] = {}
    wanted: list[tuple[str, int]] = [(story_id, version)]
    while wanted:
        story, upto = wanted.pop()
        start = walked.get(story, 0)
        if upto <= start:
            continue
        walked[story] = upto
        if story not in logs:
            logs[story] = await _log(stories, story)
        log = logs[story]
        if log is None or upto not in log:
            complete = False
        if log is None:
            continue
        for number, found in log.items():
            if not start < number <= upto:
                continue
            notes.update(found.took_in_notes)
            episodes.update(found.took_in_episodes)
            wanted.extend((name.story, name.version) for name in found.read_pages)
    return Behind(notes=frozenset(notes), episodes=frozenset(episodes), complete=complete)


async def _log(stories: StoryStore, story_id: str) -> dict[int, StorySummaryVersion] | None:
    """A story's whole version log by version number, or ``None`` where it holds none."""
    found: dict[int, StorySummaryVersion] = {}
    cursor: int | None = None
    while True:
        listed = await stories.summary_versions(story_id, cursor=cursor, limit=MAX_STORY_PAGE)
        if listed is None:
            return None if cursor is None else found
        found.update((entry.version, entry) for entry in listed.versions)
        following = listed.next_cursor
        if following is None or following == cursor:
            return found
        cursor = following


@dataclass(frozen=True, slots=True)
class SummaryVisibility:
    """Which of a story's notes, and whether its summary, one reader may be shown.

    Attributes:
        activations: The activations whose episodes the reader may be shown: each
            fetched and admitted by the reader's own rule — for a model-facing
            reader never open (ADR-0286 §6) and through its audience predicate, and
            for the owner reading directly every episode the store holds.
        owner_notes: Whether a record placed for the owner alone may be shown to the
            reader, which decides every note (ADR-0303 §3:9).
    """

    activations: frozenset[str]
    owner_notes: bool

    @classmethod
    def of(cls, episodes: Iterable[EpisodicMemory], *, owner_notes: bool) -> SummaryVisibility:
        """The visibility for a reader who may be shown exactly ``episodes``.

        Args:
            episodes: The episodes the reader may be shown, already through its
                predicate. One recording no activation contributes nothing.
            owner_notes: Whether a record placed for the owner alone may be shown.

        Returns:
            The reader's visibility.
        """
        return cls(
            activations=frozenset(
                activation for record in episodes if (activation := activation_of(record))
            ),
            owner_notes=owner_notes,
        )

    def note(self, note: StoryNote) -> bool:  # noqa: ARG002 — §3:9 reads nothing of the note
        """Whether ``note`` may be shown: where an owner record may be, whoever wrote it."""
        return self.owner_notes

    def summary(self, behind: Behind) -> bool:
        """Whether a summary may be shown: where everything ``behind`` it may be (§3:11).

        Every note behind it may be shown exactly where an owner record may be
        (§3:9). Every episode behind it must be one the reader was found able to be
        shown, so one not looked up withholds the summary as surely as one refused
        (§3:12); and a version the walk could not read withholds it too.
        """
        if not behind.complete:
            return False
        if behind.notes and not self.owner_notes:
            return False
        return behind.episodes <= self.activations
