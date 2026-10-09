"""Understanding links an activation to stories (ADR-0300 §6).

Two orchestration-local pieces, neither a Protocol, of the kind the windows stage and
recall are.

**The candidates** (:class:`StoryCandidates`, §6:1-§6:4). Before the understanding
stage renders, the understanding phase assembles up to
``UNDERSTANDING_STORY_CANDIDATES`` candidate stories (ADR-0303 §7:9): first the stories
of the activations the place window's items link to, newest item first; then the
stories the episode window's episodes belong to, in the window's order, each looked up
with ``StoryStore.stories_of``; then the stories recall's kept episodes belong to, which
a caller hands in already in ADR-0300 §6:1's order. A story already a candidate is not
repeated. Each candidate
is read as a **short view**: the first lines of its current page and the page's mark,
its newest pending notes and its latest episodes by occurrence, the episodes fetched
with ``MemoryStore.get_many`` under ADR-0282 §2:6-§2:8. The page and notes are kept
under ADR-0303 §3's default (:mod:`~ai_assistant.orchestration.story_privacy`): a note
is shown only where the pass's audience admits a record placed for the owner alone
(§3:9), and the page only where everything behind it may be shown to that audience
(§3:11), which is looked up in the same read, through the same predicate, as the
members' episodes the latest are chosen from; otherwise the view says the page was
withheld. A ``StoryStoreError`` leaves no candidates, and the decision says the stories
could not be read.

**The story-links stage** (:class:`StoryLinksStage`, §6:12-§6:14). Once understanding
is a recorded version, the stage writes its links through the story store with the
actor ``understanding`` and the activation as trigger: the activation is linked into
each linked story, following a story merged since to the story it was merged into; it
is linked into every story a linked earlier episode belongs to by then; and the earlier
episodes that belong to no story by then start one new story, holding them and the
activation. One activation's links are recorded at a time, so two activations linking
the same unstoried episode start one story, not two. It is failure-tolerant: a
``StoryStoreError`` records the decision ``failed``. What it records is bookkeeping, as
the hub records understanding's own record, and not an action planning chooses (§6:14).

Neither is saved with the episode (§12:3): the candidates are the understanding phase's
part of the working episode, the decision the stage's, and both live for the pass.

**It logs stage and code-owned counts only** — no story id, no note, no line and no
episode content (ADR-0275 §8).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    EpisodicMemory,
    StageOutcome,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    StoryRefusalReason,
)
from ai_assistant.orchestration.disclosure import admits_owner_placed, admitted_to_understanding
from ai_assistant.orchestration.episode_reads import without_open_episodes
from ai_assistant.orchestration.stories import episode_address
from ai_assistant.orchestration.story_privacy import (
    Behind,
    PageVisibility,
    activation_of,
    behind,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ai_assistant.core.protocols import MemoryStore, StoryStore
    from ai_assistant.core.types import (
        StoryNote,
        StoryPageLine,
        StoryPageState,
        StoryRefusal,
    )
    from ai_assistant.orchestration.disclosure import TurnSupply

__all__ = [
    "Candidates",
    "ShortView",
    "StoryCandidates",
    "StoryLinksDecision",
    "StoryLinksStage",
]

_log = structlog.get_logger(__name__)


# --- the candidates --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShortView:
    """One candidate story as understanding is shown it (ADR-0300 §6:2, §6:3).

    Attributes:
        story_id: The candidate story.
        lines: The first lines of its current page, in page order, where the page may
            be shown; empty where no page has been written or it may not be shown.
        notes: Its newest pending notes that may be shown, newest first.
        episodes: Its latest episodes by occurrence among those fetched and admitted,
            newest first.
        outside: The page's mark (ADR-0303 §3:4), wherever the page is shown (§3:8).
        withheld: A page has been written and was withheld from this reader, since
            not everything behind it may be shown to it (§3:11): the view carries
            neither its lines nor its mark, and the reader is told.
    """

    story_id: str
    lines: tuple[StoryPageLine, ...]
    notes: tuple[StoryNote, ...]
    episodes: tuple[EpisodicMemory, ...]
    outside: bool = False
    withheld: bool = False


@dataclass(frozen=True, slots=True)
class Candidates:
    """The understanding phase's candidate stories for one pass (ADR-0300 §6:1-§6:4).

    Attributes:
        views: The candidates' short views, in §6:1's order.
        unreadable: A story-store read raised ``StoryStoreError``, so there are no
            candidates and the section says the stories could not be read (§6:4).
        fetched: The ids the views were fetched for — the latest episodes chosen — in
            order, each once (ADR-0282 §2:7). Each
            was admitted for the pass when it was chosen, so no id the audience
            predicate refuses enters here (§2:8).
        missing: The fetched ids that came back with no episode, an open one, or one
            the predicate refused on the second application (§2:6, §2:8).
    """

    views: tuple[ShortView, ...] = ()
    unreadable: bool = False
    fetched: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Read:
    """What the store answered for one candidate, before the episodes are fetched.

    ``behind`` is what stands behind its current page (ADR-0303 §3:10), or ``None``
    where no page has been written.
    """

    story_id: str
    lines: tuple[StoryPageLine, ...]
    outside: bool
    notes: tuple[StoryNote, ...]
    members: tuple[str, ...]
    behind: Behind | None

    def addresses(self) -> list[str]:
        """The episodes this view's choice of episodes reads, in link order."""
        return [episode_address(member) for member in self.members]

    def behind_addresses(self) -> list[str]:
        """The episodes behind its page, which decide whether the page is shown."""
        if self.behind is None:
            return []
        return [episode_address(activation) for activation in sorted(self.behind.episodes)]

    def latest(self, admitted: dict[str, EpisodicMemory], *, episodes: int) -> tuple[str, ...]:
        """The ids of the latest ``episodes`` members by occurrence, among those admitted.

        ``(occurred_at, id)`` descending, ADR-0276 §4's recency order, and never link
        order, which a merge or a move makes say nothing about time (ADR-0289 §3: a
        merge appends the absorbed story's members).
        """
        held = [
            record
            for activation in self.members
            if (record := admitted.get(episode_address(activation))) is not None
        ]
        held.sort(key=lambda record: (record.occurred_at, record.id), reverse=True)
        return tuple(record.id for record in held[:episodes])

    def view(
        self,
        visibility: PageVisibility,
        latest: tuple[str, ...],
        fetched: dict[str, EpisodicMemory],
    ) -> ShortView:
        """The short view: its page and notes under ADR-0303 §3's default, its latest as fetched."""
        written = self.behind is not None
        shown = self.behind is not None and visibility.page(self.behind)
        return ShortView(
            story_id=self.story_id,
            lines=self.lines if shown else (),
            outside=self.outside and shown,
            withheld=written and not shown,
            notes=tuple(note for note in self.notes if visibility.note(note)),
            episodes=tuple(record for id_ in latest if (record := fetched.get(id_)) is not None),
        )


class StoryCandidates:
    """Assemble understanding's candidate stories and their short views (ADR-0300 §6).

    It holds the story store and the memory store, and the four composition-root
    numbers. It reads the stories of what the windows and recall already chose, and the
    records of those stories; it searches nothing and calls no model.
    """

    def __init__(  # noqa: PLR0913 — the two stores and §6's four numbers
        self,
        *,
        stories: StoryStore,
        memory: MemoryStore,
        limit: int,
        lines: int,
        notes: int,
        episodes: int,
    ) -> None:
        """Wire the assembler to its stores and its bounds.

        Args:
            stories: The story store the candidates are read from.
            memory: The store a candidate's episodes are fetched from.
            limit: ``UNDERSTANDING_STORY_CANDIDATES`` (§6:1).
            lines: How many of a current page's first lines a short view takes (§6:2).
            notes: How many of the newest pending notes it takes, at most two.
            episodes: How many of the latest episodes it takes, at most two.

        Raises:
            ValueError: If a bound is below 1, or ``notes`` or ``episodes`` above two.
        """
        if min(limit, lines, notes, episodes) < 1:
            msg = "the candidates' bounds are each at least 1 (ADR-0300 §6:1, §6:2)"
            raise ValueError(msg)
        if max(notes, episodes) > 2:  # noqa: PLR2004 — §6:2's "at most two"
            msg = "a short view takes at most two entries and two episodes (ADR-0300 §6:2)"
            raise ValueError(msg)
        self._stories = stories
        self._memory = memory
        self._limit = limit
        self._lines = lines
        self._notes = notes
        self._episodes = episodes

    async def assemble(
        self,
        window: Sequence[EpisodicMemory],
        *,
        audience: TurnSupply,
        recalled: Sequence[str] = (),
        place: Sequence[str] = (),
    ) -> Candidates:
        """The candidates for one pass, each read as a short view.

        Args:
            window: The episode window's records as the understanding phase fetched
                them, in the window's order: already admitted for the pass.
            audience: The pass's audience posture, which decides what of each view
                may be shown (§6:3, ADR-0303 §3:9-§3:12).
            recalled: The stories recall's kept episodes belong to, already in §6:1's
                order — the item with the higher recorded search score first, as
                :meth:`~ai_assistant.orchestration.recall.Recalled.stories` gives them.
                They join after the window's (§7).
            place: The activations the place window's items link to, newest item
                first, as
                :func:`~ai_assistant.orchestration.understanding.place_window_links`
                gives them. Their stories come first (ADR-0303 §7:9).

        Returns:
            The candidates, or none with ``unreadable`` set where a story-store read
            raised ``StoryStoreError``.

        Raises:
            MemoryStoreError: If the episodes cannot be fetched, as the window's own
                fetch would.
        """
        try:
            chosen = await self._chosen(place, window, recalled)
            reads = [read for story_id in chosen if (read := await self._read(story_id))]
        except StoryStoreError:
            _log.warning("story_candidates_unreadable", stage="understanding")
            return Candidates(unreadable=True)
        # ADR-0282 §2:5, §2:8: the reads that choose, and only admitted ids chosen. Every
        # member is read once, through the audience predicate, to choose which members are
        # the latest; nothing refused is chosen or recorded. ADR-0303 §3:11-§3:12: in the
        # same read, the episodes behind each page, through the same predicate, which
        # decide whether the page may be shown and are neither chosen nor recorded.
        chosen_from = await self._admitted(
            dict.fromkeys(
                address
                for read in reads
                for address in (*read.addresses(), *read.behind_addresses())
            ),
            audience,
        )
        latest = [read.latest(chosen_from, episodes=self._episodes) for read in reads]
        # §2:6-§2:8: the chosen ids fetched for their current versions, the predicate
        # applied again, and what came back missing recorded beside what was fetched.
        fetched = tuple(dict.fromkeys(id_ for ids in latest for id_ in ids))
        held = await self._admitted(fetched, audience)
        # ADR-0303 §3:12: the latest answer about each episode decides the page, so one
        # the second fetch found gone or refused withholds it as surely as one the first
        # read did.
        answers = dict(chosen_from)
        for id_ in fetched:
            answers.pop(id_, None)
        answers |= held
        visibility = PageVisibility.of(answers.values(), owner_notes=admits_owner_placed(audience))
        views = tuple(
            read.view(visibility, ids, held) for read, ids in zip(reads, latest, strict=True)
        )
        _log.info(
            "story_candidates",
            stage="understanding",
            candidates=len(views),
            fetched=len(fetched),
        )
        return Candidates(
            views=views,
            fetched=fetched,
            missing=tuple(id_ for id_ in fetched if id_ not in held),
        )

    async def _admitted(
        self, addresses: Iterable[str], audience: TurnSupply
    ) -> dict[str, EpisodicMemory]:
        """The frozen episodes at ``addresses`` the audience admits, by address."""
        wanted = list(addresses)
        if not wanted:
            return {}
        found = without_open_episodes(await self._memory.get_many(wanted))
        episodes = [
            record for address in wanted if isinstance(record := found.get(address), EpisodicMemory)
        ]
        return {record.id: record for record in admitted_to_understanding(audience, episodes)}

    async def _chosen(
        self, place: Sequence[str], window: Sequence[EpisodicMemory], recalled: Sequence[str]
    ) -> list[str]:
        """ADR-0303 §7:9's order: the place window's, the episode window's, recall's, once.

        An activation still running may be linked (§7:7), so a place-window item's is
        looked up as any other.
        """
        chosen: dict[str, None] = {}
        windowed = (activation_of(record) for record in window)
        activations = dict.fromkeys([*place, *(one for one in windowed if one is not None)])
        for activation in activations:
            if len(chosen) >= self._limit:
                break
            member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation)
            for header in await self._stories.stories_of(member):
                chosen.setdefault(header.story_id)
        for story_id in recalled:
            chosen.setdefault(story_id)
        return list(chosen)[: self._limit]

    async def _read(self, story_id: str) -> _Read | None:
        """One candidate's current page's first lines and its mark, its notes and members.

        And what stands behind its page (ADR-0303 §3:10), walked from the version that
        wrote it: the log is append-only, so a walk made after the page was read answers
        for that page.
        """
        state = await self._stories.current_page(story_id)
        if state is None:
            return None
        page = state.page
        newest = tuple(reversed(state.pending_notes[-self._notes :]))
        return _Read(
            story_id=story_id,
            lines=() if page is None else page.lines[: self._lines],
            outside=page is not None and page.outside,
            notes=newest,
            members=await self._members(story_id, state),
            behind=None if page is None else await behind(self._stories, story_id, page.version),
        )

    async def _members(self, story_id: str, state: StoryPageState) -> tuple[str, ...]:
        """The story's activation members, every one: its latest are chosen by occurrence.

        Link order says nothing about when an episode occurred once a merge or a move
        has appended older members (ADR-0289 §3), so the whole membership is read and
        the episodes' own instants decide which are the latest.
        """
        if state.story.merged_into is not None:
            return ()
        # Each once: a member unlinked and linked again while the pages are read comes
        # back at its new position on a later page.
        members: dict[str, None] = {}
        cursor: int | None = None
        while True:
            page = await self._stories.view(story_id, cursor=cursor, limit=MAX_STORY_PAGE)
            if page is None:
                break
            members |= dict.fromkeys(
                entry.member.id
                for entry in page.entries
                if entry.member.kind is StoryMemberKind.ACTIVATION
            )
            if page.next_cursor is None or page.next_cursor == cursor:
                break
            cursor = page.next_cursor
        return tuple(members)


# --- the story-links stage ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoryLinksDecision:
    """The story-links stage's decision for one pass (ADR-0300 §6:10, §6:13).

    Present once the stage has made it, a failed one included, so the rule that made
    it due does not answer again. It is never saved with the episode (§12:3): the
    links are kept in the understanding record and in the story store's change log.

    Attributes:
        outcome: ``done``, or ``failed`` where the story store raised.
        linked: The stories the activation was linked into, in the order linked,
            each once, a story it already belonged to included.
        started: The story the rule start minted, where it started one.
        refused: The refusals the store answered, each an outcome rather than an
            error: what the store refused, it wrote nothing for.
        error: The ``StoryStoreError`` a ``failed`` decision carries; never recorded.
    """

    outcome: StageOutcome
    linked: tuple[str, ...] = ()
    started: str | None = None
    refused: tuple[StoryRefusal, ...] = ()
    error: StoryStoreError | None = None


class StoryLinksStage:
    """Record an understanding's story links in the story store (ADR-0300 §6:12).

    It holds the story store and nothing else; what it writes, it writes with the
    actor ``understanding`` and the activation as trigger (ADR-0289 §4:4 as ADR-0300
    supersedes it).

    **One activation's links are recorded at a time.** "The earlier episodes that
    belong to no story by then" (§6:12) is a read and then a create, two transactions;
    two activations linking the same unstoried episode at once would each read *none*
    and start two stories where the rule starts one. The stage holds one lock across
    each run, so the second reads the story the first started and links into it. The
    hub is one resident process per data directory, so a lock in the process is the
    whole of the serialization the rule needs.
    """

    def __init__(self, *, stories: StoryStore) -> None:
        """Wire the stage to the story store it writes.

        Args:
            stories: The story store the engine surface writes too.
        """
        self._stories = stories
        self._serial = asyncio.Lock()

    async def record(
        self, links: Sequence[StoryMember], *, activation_id: str
    ) -> StoryLinksDecision:
        """Write the links of one activation's latest recorded understanding.

        Args:
            links: The understanding's ``story_links``, in proposal order.
            activation_id: The activation the understanding is of.

        Returns:
            The decision: ``done`` with what was linked, started and refused, or
            ``failed`` carrying the ``StoryStoreError`` the store raised. Writes made
            before a failure stand, each its own transaction.
        """
        writes = _Writes(self._stories, activation_id)
        try:
            async with self._serial:
                unstoried: list[StoryMember] = []
                for member in links:
                    if member.kind is StoryMemberKind.STORY:
                        await writes.link(member.id)
                        continue
                    stories = await self._stories.stories_of(member)
                    if not stories:
                        unstoried.append(member)
                    for header in stories:
                        await writes.link(header.story_id)
                if unstoried:
                    await writes.start(unstoried)
        except StoryStoreError as exc:
            _log.warning("story_links_failed", stage="story_links")
            return writes.decision(StageOutcome.FAILED, error=exc)
        _log.info(
            "story_links",
            stage="story_links",
            links=len(links),
            linked=len(writes.linked),
            started=writes.started is not None,
            refused=len(writes.refused),
        )
        return writes.decision(StageOutcome.DONE)


class _Writes:
    """One stage run's writes, and what they did."""

    def __init__(self, stories: StoryStore, activation_id: str) -> None:
        self._stories = stories
        self._trigger = activation_id
        self._activation = StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)
        self.linked: dict[str, None] = {}
        self.started: str | None = None
        self.refused: list[StoryRefusal] = []

    async def link(self, story_id: str) -> None:
        """Link the activation into ``story_id``, following a merge to where it went.

        Every merge is followed, however long the chain: a merged story is never written
        and never a merge target, so a chain ends at a story that is not merged. A
        target named twice is a store contradicting itself, and its refusal is recorded
        rather than followed for ever.
        """
        target = story_id
        followed: set[str] = set()
        refusal: StoryRefusal | None = None
        while target not in followed:
            followed.add(target)
            outcome = await self._stories.link(
                target,
                [self._activation],
                actor=StoryActor.UNDERSTANDING,
                trigger=self._trigger,
            )
            refusal = outcome.refusal
            if refusal is None:
                assert outcome.story_id is not None  # noqa: S101 — an applied write names its story
                self.linked.setdefault(outcome.story_id)
                return
            if refusal.reason is not StoryRefusalReason.MERGED_STORY or refusal.merged_into is None:
                self.refused.append(refusal)
                return
            target = refusal.merged_into
        if refusal is not None:
            self.refused.append(refusal)

    async def start(self, members: Sequence[StoryMember]) -> None:
        """Start one story holding the earlier episodes in no story, and the activation."""
        outcome = await self._stories.create(
            [*members, self._activation], actor=StoryActor.UNDERSTANDING, trigger=self._trigger
        )
        if outcome.refusal is not None:
            self.refused.append(outcome.refusal)
            return
        self.started = outcome.story_id

    def decision(
        self, outcome: StageOutcome, *, error: StoryStoreError | None = None
    ) -> StoryLinksDecision:
        """What the run did, as the stage's decision."""
        return StoryLinksDecision(
            outcome=outcome,
            linked=tuple(self.linked),
            started=self.started,
            refused=tuple(self.refused),
            error=error,
        )
