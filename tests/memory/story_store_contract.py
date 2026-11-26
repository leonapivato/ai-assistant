"""Shared conformance suite for the StoryStore Protocol (ADR-0289 §§1-3, ADR-0300 §3).

Every ``StoryStore`` implementation must pass this suite. A concrete test
subclasses :class:`StoryStoreContract` and overrides the ``store`` fixture with an
implementation whose clock reads :data:`STORY_AT`; the suite asserts only behaviour
universal to the contract.

What it holds, clause by clause: the clean view and the append-only change log
written together (§2), the five operations and their exceptions (§3) — a member
passed over, a merge keeping an existing entry, a merge of a story holding its own
target, a merge rewiring the absorbed story's holders, a split keeping link order —
the loop refusal on a link and on a merge, refusals as typed outcomes that write
nothing, and the five reads with their paging.

And ADR-0300 §3's notes and summary as ADR-0303 §§2-6 remakes them: notes, immutable and never
removed, each recording the activation it was written during and its mark; the
summary, lines that cite nothing and the summary's mark, and its version log of
what each run took in, the other stories' summary versions it read, its flags and its
mark; pending, including what becomes pending while a run is out and what a merge, a
split or a move brings; the summary write, which writes no note, refused when the
version it was built on is no longer current, over a summary version read naming
nothing the store holds, and over the cap counting every line, writing nothing; the
move; the notes a merge carries (every one) and a split or a move carries (exactly
those named); and the actors ADR-0300 §3:15 adds.

And ADR-0302: what names a flag and which stories it concerns (§2), a tidy-up's flags
being the only ones (ADR-0303 §8); the ``decided`` line each decision writes, after
its change's lines and on the stories as they stand once it is applied (§3);
``leave_flag`` with ``left`` or ``not_applied``, the ``answers`` keyword and their
refusals, checked after every check the operation makes and writing nothing when
refused, one writer only answering a flag (§4); and the summary write refused over what
its story does not hold, in its fixed place in the order (§7).

And ADR-0304 §9: a move of notes alone, carrying exactly the named notes the story
moved from holds and keeping every field of each, refused ``no_members`` where it
names no note either and ``no_notes`` where the story holds none it names, in its
fixed place in the order; and each note a split or a move carries logged on both
stories, ``note_moved_out`` and ``note_moved_in``, where a merge logs none.

And ADR-0307 §5:4: a split or a move whose actor is ``planning``, naming a note the
story moved from does not hold when it runs, refused whole with ``note_not_held``,
a note moved away meanwhile included, where every other actor's passes it over.

And ADR-0347 §2: every summary a write makes kept after a later write replaces it,
read by its version through ``summary_at`` exactly as written — a merged story's by its
own id — and ``None`` for a version that is not the story's; and ``position``, the
sequence versions and reads' ``as_of`` lie on, at or above every version written
before it and below every version written after. A refused write moves neither, since
the whole observable state the refusals compare holds both.

And ADR-0386 §2 with ADR-0383 §§3-4: each story carries its home, which ``create``
writes as it is handed, a split's new story takes from the story it was split from, and
no write changes, a merge included; every read that gives back a header gives it, a
note, a summary, a version and a log line carrying none of their own; and a home
``home_may_be_written`` does not allow refused with ``ValueError`` before any check or
write (ADR-0386 §6:2), an empty create's included.

And ADR-0383 §4:7: a write stays in its home. A create, a link or a split naming a story
member of another home than the story it mints or writes, and a merge or a move between
two stories of two homes, are each refused ``another_home``, naming the story of the
other home, and write nothing, with the same write within one home beside each
succeeding; the refusal takes its place after the stories are found standing and before
the operation's own rule and the flag. A summary version naming a story of another home,
by a ``like_another`` flag or a summary version read, is refused ``another_home`` after
the named stories are found and before ``not_held``; a write answering a flag one of whose
stories is of another home than its own, ``leave_flag`` on a flag across two homes
included, is refused ``another_home`` after ``unknown_flag`` and ``already_decided``. Each
writes nothing; a bound store answers it only between two stories it holds.

And ADR-0385 §6:4, §11: the export, every story the store lists, a merged one included,
each with every part that takes its home exactly as the store's own reads give it, and
nothing store-wide (ADR-0383 §8:5); an empty store's holding no story; through a binding,
what that binding's reads give back, the owner's sight from one domain holding nothing of
the other in either build mode; and a frozen model that round-trips through its JSON. The
§9:3 battery carries it too, so a bound store's export answers as the same store holding
only what its sight sees.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
import structlog
from pydantic import ValidationError

from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    STORY_ID_PREFIX,
    STORY_NOTE_MAX_CHARS,
    STORY_SUMMARY_CAP_CHARS,
    ExportedStory,
    RecordHome,
    Sight,
    SightMode,
    StoryActor,
    StoryChange,
    StoryDecision,
    StoryExport,
    StoryFlag,
    StoryFlagKind,
    StoryFlagName,
    StoryHeader,
    StoryLogLine,
    StoryMember,
    StoryMemberKind,
    StoryNote,
    StoryNoteAuthor,
    StoryNoteOutcome,
    StoryOutcome,
    StoryRefusalReason,
    StorySummaryDraft,
    StorySummaryLine,
    StorySummaryOutcome,
    StorySummaryRefusalReason,
    StorySummaryState,
    StorySummaryVersion,
    StorySummaryVersionList,
    StorySummaryVersionName,
)
from sight_equivalence import SIGHTS, ReadCall, assert_answers_alike

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Collection

    from ai_assistant.core.protocols import StoryStore

#: The instant every subject's clock reads.
STORY_AT = datetime(2026, 10, 4, 12, tzinfo=UTC)

_OWNER = StoryActor.OWNER

#: The owner's sights, one for each domain an owner's act may name and one for none
#: (ADR-0385 §3:3), by name.
_OWNERS_ACTS: Final[dict[str, Sight]] = {
    "from-none": Sight.of_owners_act(None),
    "from-the-owners-domain": Sight.of_owners_act(RecordHome.owners()),
    "from-the-shared-things": Sight.of_owners_act(RecordHome.shared()),
}


def act(activation_id: str) -> StoryMember:
    """An activation member."""
    return StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)


def sub(story_id: str) -> StoryMember:
    """A story member."""
    return StoryMember(kind=StoryMemberKind.STORY, id=story_id)


async def made(store: StoryStore, *members: StoryMember) -> str:
    """Create a story holding ``members`` and return its id, failing on a refusal."""
    outcome = await store.create(members, home=RecordHome.owners(), actor=_OWNER)
    assert outcome.refusal is None, outcome
    assert outcome.story_id is not None
    return outcome.story_id


async def homed(store: StoryStore, home: RecordHome, *members: StoryMember) -> str:
    """Create a story in ``home`` holding ``members`` and return its id."""
    outcome = await store.create(members, home=home, actor=_OWNER)
    assert outcome.refusal is None, outcome
    assert outcome.story_id is not None
    return outcome.story_id


#: The two homes a write may carry (ADR-0383 §2:3), each against the other: a story's
#: own and another one, for the cases where a write would join the two (§4:7).
_TWO_HOMES = [
    (RecordHome.owners(), RecordHome.shared()),
    (RecordHome.shared(), RecordHome.owners()),
]
_TWO_HOMES_IDS = ["owners-and-shared", "shared-and-owners"]


async def held(store: StoryStore, story_id: str) -> list[StoryMember]:
    """A story's current members, in link order."""
    page = await store.view(story_id, limit=MAX_STORY_PAGE)
    assert page is not None
    return [entry.member for entry in page.entries]


async def logged(store: StoryStore, story_id: str) -> list[StoryLogLine]:
    """A story's whole change log."""
    page = await store.log(story_id, limit=MAX_STORY_PAGE)
    assert page is not None
    assert page.next_cursor is None
    return list(page.lines)


def shape(lines: list[StoryLogLine]) -> list[tuple[StoryChange, str | None]]:
    """Each line's change and what it names — the member's id or the other story."""
    named: list[tuple[StoryChange, str | None]] = []
    for line in lines:
        target = line.member.id if line.member is not None else line.other_story
        named.append((line.change, target))
    return named


def carried(lines: list[StoryLogLine]) -> list[tuple[StoryChange, int | None, str | None]]:
    """Each line recording a carried note: its change, the note and the other story."""
    return [
        (line.change, line.note, line.other_story)
        for line in lines
        if line.change in {StoryChange.NOTE_MOVED_OUT, StoryChange.NOTE_MOVED_IN}
    ]


def refused(outcome: StoryOutcome, reason: StoryRefusalReason) -> None:
    """Assert ``outcome`` is a refusal for ``reason`` that wrote nothing."""
    assert outcome.story_id is None
    assert outcome.logged == 0
    assert outcome.refusal is not None
    assert outcome.refusal.reason is reason


async def everything(store: StoryStore) -> tuple[Any, ...]:
    """Every story's header, view, log and summaries, and the store's position.

    The whole observable state: each story's kept summaries are read by every version
    its log holds (ADR-0347 §2:4), and the position is read last (§2:5).
    """
    page = await store.stories(limit=MAX_STORY_PAGE)
    assert page.next_cursor is None
    state: list[Any] = []
    for header in page.stories:
        state.append(header)
        state.append(await store.view(header.story_id, limit=MAX_STORY_PAGE))
        state.append(await store.log(header.story_id, limit=MAX_STORY_PAGE))
        state.append(await store.current_summary(header.story_id))
        state.append(await store.notes(header.story_id, limit=MAX_STORY_PAGE))
        versions = await store.summary_versions(header.story_id, limit=MAX_STORY_PAGE)
        state.append(versions)
        assert versions is not None
        for one in versions.versions:
            state.append(await store.summary_at(header.story_id, one.version))
    state.append(await store.position())
    return tuple(state)


async def noted(  # noqa: PLR0913 — the store, the story, the text, and the note's keywords
    store: StoryStore,
    story_id: str,
    text: str,
    *,
    on: str | None = "a1",
    author: StoryNoteAuthor = StoryNoteAuthor.PLANNING,
    outside: bool = False,
) -> StoryNote:
    """Append a note and return it, failing on a refusal; ``on`` is ignored for ``owner``."""
    outcome = await store.append_note(
        story_id,
        text,
        author=author,
        written_during=None if author is StoryNoteAuthor.OWNER else on,
        outside=outside,
    )
    assert outcome.refusal is None, outcome
    assert outcome.note is not None
    return outcome.note


async def state_of(store: StoryStore, story_id: str) -> StorySummaryState:
    """A story's summary with what is pending on it."""
    state = await store.current_summary(story_id)
    assert state is not None
    return state


def line(text: str) -> StorySummaryLine:
    """A line of a summary: its text, and nothing else (ADR-0303 §2:7)."""
    return StorySummaryLine(text=text)


def draft(*lines: StorySummaryLine, outside: bool = False, **rest: Any) -> StorySummaryDraft:
    """A draft of ``lines``, unmarked unless ``outside``, and whatever else it records."""
    return StorySummaryDraft(lines=lines, outside=outside, **rest)


async def written(
    store: StoryStore, story_id: str, summary: StorySummaryDraft, *, as_of: int
) -> StorySummaryVersion:
    """Write a summary and return its version, failing on a refusal."""
    outcome = await store.write_summary(story_id, summary, as_of=as_of)
    assert outcome.refusal is None, outcome
    assert outcome.version is not None
    return outcome.version


async def versions_of(store: StoryStore, story_id: str) -> list[StorySummaryVersion]:
    """A story's whole version log."""
    page = await store.summary_versions(story_id, limit=MAX_STORY_PAGE)
    assert page is not None
    assert page.next_cursor is None
    return list(page.versions)


async def notes_of(store: StoryStore, story_id: str) -> list[StoryNote]:
    """Every note a story holds, in the order they were written."""
    page = await store.notes(story_id, limit=MAX_STORY_PAGE)
    assert page is not None
    assert page.next_cursor is None
    return list(page.notes)


def summary_refused(
    outcome: StorySummaryOutcome | StoryNoteOutcome, reason: StorySummaryRefusalReason
) -> None:
    """Assert a summary write or a note append was refused for ``reason``."""
    assert outcome.refusal is not None, outcome
    assert outcome.refusal.reason is reason


_PASS = StoryActor.MATTERS_PASS


async def raised(store: StoryStore, story_id: str, flag: StoryFlag) -> StoryFlagName:
    """Write a summary of ``story_id`` raising ``flag``, and return the flag's name (§2:1)."""
    await noted(store, story_id, "Note.")
    read = await state_of(store, story_id)
    version = await written(store, story_id, draft(line("Line."), flags=(flag,)), as_of=read.as_of)
    return StoryFlagName(story=story_id, version=version.version, flag=flag)


async def linked_by_understanding(store: StoryStore, story_id: str | None, activation: str) -> str:
    """Link ``activation`` as understanding does, into ``story_id`` or a story it starts."""
    stamp: dict[str, Any] = {"actor": StoryActor.UNDERSTANDING, "trigger": activation}
    if story_id is None:
        outcome = await store.create([act(activation)], home=RecordHome.owners(), **stamp)
    else:
        outcome = await store.link(story_id, [act(activation)], **stamp)
    assert outcome.story_id is not None, outcome
    return outcome.story_id


class StoryStoreContract:
    """The behavioural contract every ``StoryStore`` must satisfy (ADR-0289 §§1-3)."""

    @pytest.fixture
    def store(self) -> StoryStore:
        """Override in a subclass: an empty store whose clock reads ``STORY_AT``."""
        raise NotImplementedError

    # --- a story's home (ADR-0386 §2, ADR-0383 §§3-4) --------------------------

    @pytest.mark.parametrize(
        "home", [RecordHome.owners(), RecordHome.shared()], ids=["owners", "shared"]
    )
    async def test_create_writes_the_home_it_is_handed_and_every_header_read_gives_it(
        self, store: StoryStore, home: RecordHome
    ) -> None:
        """ADR-0386 §2:1, §2:2: the header every read gives back carries it."""
        outcome = await store.create([act("a1")], home=home, actor=_OWNER)
        assert outcome.story_id is not None
        story_id = outcome.story_id
        await noted(store, story_id, "A note.")
        header = await store.header(story_id)
        assert header is not None
        assert header.home == home
        view = await store.view(story_id)
        log = await store.log(story_id)
        summary = await store.current_summary(story_id)
        notes = await store.notes(story_id)
        versions = await store.summary_versions(story_id)
        assert view is not None
        assert log is not None
        assert summary is not None
        assert notes is not None
        assert versions is not None
        assert {view.story, log.story, summary.story, notes.story, versions.story} == {header}
        assert (await store.stories()).stories == (header,)
        assert await store.stories_of(act("a1")) == (header,)

    async def test_a_split_mints_its_story_in_the_home_of_the_story_split_from(
        self, store: StoryStore
    ) -> None:
        """ADR-0386 §2:3: the new story takes its source's home; the split takes none."""
        source = await store.create([act("a1"), act("a2")], home=RecordHome.shared(), actor=_OWNER)
        assert source.story_id is not None
        split = await store.split(source.story_id, [act("a2")], actor=_OWNER)
        assert split.story_id is not None
        made_off = await store.header(split.story_id)
        assert made_off is not None
        assert made_off.home == RecordHome.shared()

    async def test_no_write_changes_a_storys_home_a_merge_included(self, store: StoryStore) -> None:
        """ADR-0383 §4:6: every write that changes a story leaves its home as it was.

        Each write here joins records of one home: a write joining two homes is refused
        (§4:7), as the cases under "a write stays in its home" hold.
        """
        shared = [
            await store.create([act(one)], home=RecordHome.shared(), actor=_OWNER)
            for one in ("a1", "a2", "a3")
        ]
        absorbed, target, moved = (one.story_id for one in shared)
        assert absorbed is not None
        assert target is not None
        assert moved is not None
        await store.link(target, [act("a4")], actor=_OWNER)
        await store.unlink(target, [act("a4")], actor=_OWNER)
        await noted(store, absorbed, "A note.", on="a1")
        await store.merge(absorbed, target, actor=_OWNER)
        await store.move(target, moved, [act("a1")], actor=_OWNER)
        for story_id in (absorbed, target, moved):
            header = await store.header(story_id)
            assert header is not None
            assert header.home == RecordHome.shared(), story_id
        merged = await store.header(absorbed)
        assert merged is not None
        assert merged.merged_into == target

    @pytest.mark.parametrize(
        "home",
        [RecordHome.person("person:sam"), RecordHome.group("group:house")],
        ids=["another-person", "a-group"],
    )
    @pytest.mark.parametrize("members", [[act("a1")], []], ids=["members", "no-members"])
    async def test_a_home_no_write_may_carry_is_refused_before_any_check_or_write(
        self, store: StoryStore, home: RecordHome, members: list[StoryMember]
    ) -> None:
        """ADR-0383 §2:3, §4:7, ADR-0386 §6:2: ``ValueError``, not a refusal outcome."""
        await made(store, act("a0"))
        before = await everything(store)

        with pytest.raises(ValueError, match="home"):
            await store.create(members, home=home, actor=_OWNER)

        assert await everything(store) == before

    # --- a write stays in its home (ADR-0383 §4:7) -----------------------------

    @pytest.mark.parametrize(("home", "other"), _TWO_HOMES, ids=_TWO_HOMES_IDS)
    async def test_a_create_naming_a_story_member_of_another_home_is_refused(
        self, store: StoryStore, home: RecordHome, other: RecordHome
    ) -> None:
        """§4:7, "as a member": refused ``another_home``, naming the member, writing nothing.

        A create naming a story member of its own home beside it succeeds.
        """
        elsewhere = await homed(store, other, act("a1"))
        alike = await homed(store, home, act("a2"))
        before = await everything(store)

        outcome = await store.create([act("a3"), sub(elsewhere)], home=home, actor=_OWNER)

        refused(outcome, StoryRefusalReason.ANOTHER_HOME)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == elsewhere
        assert await everything(store) == before
        same = await store.create([act("a3"), sub(alike)], home=home, actor=_OWNER)
        assert same.refusal is None, same

    @pytest.mark.parametrize(("home", "other"), _TWO_HOMES, ids=_TWO_HOMES_IDS)
    async def test_a_link_naming_a_story_member_of_another_home_is_refused(
        self, store: StoryStore, home: RecordHome, other: RecordHome
    ) -> None:
        """§4:7: a link adds no story of another home as a member; one of its own, it does."""
        story_id = await homed(store, home, act("a1"))
        elsewhere = await homed(store, other, act("a2"))
        alike = await homed(store, home, act("a3"))
        before = await everything(store)

        outcome = await store.link(story_id, [sub(alike), sub(elsewhere)], actor=_OWNER)

        refused(outcome, StoryRefusalReason.ANOTHER_HOME)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == elsewhere
        assert await everything(store) == before
        same = await store.link(story_id, [sub(alike)], actor=_OWNER)
        assert same.refusal is None, same
        assert await held(store, story_id) == [act("a1"), sub(alike)]

    @pytest.mark.parametrize(("home", "other"), _TWO_HOMES, ids=_TWO_HOMES_IDS)
    async def test_a_split_naming_a_story_member_of_another_home_is_refused(
        self, store: StoryStore, home: RecordHome, other: RecordHome
    ) -> None:
        """§4:7: the story a split mints takes its source's home (ADR-0386 §2:3).

        So a split naming a story member of another home is refused as a create naming
        one is, before ``not_a_member``: the story split need not hold it. A split of a
        story member of its own home succeeds.
        """
        alike = await homed(store, home, act("a1"))
        story_id = await homed(store, home, act("a2"), sub(alike))
        elsewhere = await homed(store, other, act("a3"))
        before = await everything(store)

        outcome = await store.split(story_id, [sub(alike), sub(elsewhere)], actor=_OWNER)

        refused(outcome, StoryRefusalReason.ANOTHER_HOME)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == elsewhere
        assert await everything(store) == before
        same = await store.split(story_id, [sub(alike)], actor=_OWNER)
        assert same.story_id is not None, same
        made_off = await store.header(same.story_id)
        assert made_off is not None
        assert made_off.home == home

    @pytest.mark.parametrize(("home", "other"), _TWO_HOMES, ids=_TWO_HOMES_IDS)
    async def test_a_merge_of_two_stories_of_two_homes_is_refused(
        self, store: StoryStore, home: RecordHome, other: RecordHome
    ) -> None:
        """§4:7, §3:2: a merge would carry every member and note of one into the other.

        Refused ``another_home``, naming the story it would merge into, and writing
        nothing: the absorbed story keeps its members, its notes and no merge target.
        A merge into a story of its own home succeeds.
        """
        absorbed = await homed(store, home, act("a1"))
        await noted(store, absorbed, "A note.", on="a1")
        elsewhere = await homed(store, other, act("a2"))
        alike = await homed(store, home, act("a3"))
        before = await everything(store)

        outcome = await store.merge(absorbed, elsewhere, actor=_OWNER)

        refused(outcome, StoryRefusalReason.ANOTHER_HOME)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == elsewhere
        assert await everything(store) == before
        same = await store.merge(absorbed, alike, actor=_OWNER)
        assert same.story_id == alike, same

    @pytest.mark.parametrize(("home", "other"), _TWO_HOMES, ids=_TWO_HOMES_IDS)
    @pytest.mark.parametrize("what", ["members", "notes", "both"])
    async def test_a_move_between_two_stories_of_two_homes_is_refused(
        self, store: StoryStore, home: RecordHome, other: RecordHome, what: str
    ) -> None:
        """§4:7, §3:2: a move puts members and notes of one story into another.

        Between two stories of two homes it is refused ``another_home``, naming the
        story moved to, members or notes alike, and writes nothing; between two of one
        home it moves them.
        """
        source = await homed(store, home, act("a1"), act("a2"))
        note = await noted(store, source, "A note.", on="a1")
        elsewhere = await homed(store, other, act("a3"))
        alike = await homed(store, home, act("a4"))
        members = [] if what == "notes" else [act("a1")]
        notes = [] if what == "members" else [note.note_id]
        before = await everything(store)

        outcome = await store.move(source, elsewhere, members, actor=_OWNER, notes=notes)

        refused(outcome, StoryRefusalReason.ANOTHER_HOME)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == elsewhere
        assert await everything(store) == before
        same = await store.move(source, alike, members, actor=_OWNER, notes=notes)
        assert same.story_id == alike, same

    async def test_another_home_is_checked_after_the_stories_are_found_and_before_the_rest(
        self, store: StoryStore
    ) -> None:
        """Its place in the fixed order: after ``unknown_story`` and ``merged_story``.

        And before the operation's own rule and the flag (ADR-0302 §4:5): a note move
        naming a note the story moved from does not hold is ``another_home``, not
        ``no_notes`` (ADR-0304 §9:4, read as a refusal for its stories as any move
        is); a link answering a flag no record holds, ``another_home``, not
        ``unknown_flag``; a merge into a merged story still ``merged_story``.
        """
        owners = await homed(store, RecordHome.owners(), act("a1"))
        shared = await homed(store, RecordHome.shared(), act("a2"))
        gone = await homed(store, RecordHome.shared(), act("a3"))
        await store.merge(gone, shared, actor=_OWNER)
        unknown = StoryFlagName(
            story=owners, version=1, flag=StoryFlag(kind=StoryFlagKind.TWO_MATTERS)
        )

        merged = await store.merge(owners, gone, actor=_OWNER)
        note_move = await store.move(owners, shared, actor=_OWNER, notes=[999])
        answering = await store.link(owners, [sub(shared)], actor=_PASS, answers=unknown)

        refused(merged, StoryRefusalReason.MERGED_STORY)
        refused(note_move, StoryRefusalReason.ANOTHER_HOME)
        refused(answering, StoryRefusalReason.ANOTHER_HOME)

    # --- a flag stays in its home (ADR-0383 §3:2, §4:7) --------------------------

    @pytest.fixture
    def set_story_home(self) -> Callable[[StoryStore, str, RecordHome], None]:
        """Override in a subclass: give a stored story another home, writing nothing else.

        **A test-only door**, which the Protocol has none of, standing for a file written
        before the store refused a name across homes: no write changes a story's home
        (ADR-0383 §4:6), so a flag whose stories span two homes is reached no other way.
        """
        raise NotImplementedError

    @pytest.mark.parametrize(("home", "other"), _TWO_HOMES, ids=_TWO_HOMES_IDS)
    async def test_a_summary_flag_naming_a_story_of_another_home_is_refused(
        self, store: StoryStore, home: RecordHome, other: RecordHome
    ) -> None:
        """§4:7: a version records no ``like_another`` flag naming a story of another home.

        Refused ``another_home``, naming that story, and nothing written: no version, no
        summary, nothing taken in, the position where it was. Naming a story of its own
        home, the same write lands.
        """
        story_id = await homed(store, home, act("a1"))
        elsewhere = await homed(store, other, act("a2"))
        alike = await homed(store, home, act("a3"))
        read = await state_of(store, story_id)
        before = await everything(store)

        outcome = await store.write_summary(
            story_id,
            draft(
                line("Line."),
                took_in_episodes=("a1",),
                flags=(StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=elsewhere),),
            ),
            as_of=read.as_of,
        )

        summary_refused(outcome, StorySummaryRefusalReason.ANOTHER_HOME)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == elsewhere
        assert outcome.version is None
        assert await everything(store) == before
        same = await written(
            store,
            story_id,
            draft(
                line("Line."),
                took_in_episodes=("a1",),
                flags=(StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=alike),),
            ),
            as_of=read.as_of,
        )
        assert same.flags == (StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=alike),)

    @pytest.mark.parametrize(("home", "other"), _TWO_HOMES, ids=_TWO_HOMES_IDS)
    async def test_a_summary_version_read_of_a_story_of_another_home_is_refused(
        self, store: StoryStore, home: RecordHome, other: RecordHome
    ) -> None:
        """§4:7: a version records no summary version read of a story of another home.

        ADR-0304 §4: nothing writes ``read_pages`` today, but the store's door takes it,
        so it is judged as a flag's story is. A version read of its own home lands.
        """
        story_id = await homed(store, home, act("a1"))
        elsewhere = await homed(store, other, act("a2"))
        alike = await homed(store, home, act("a3"))
        for one in (elsewhere, alike):
            await written(store, one, draft(line("Its matter.")), as_of=await store.position())
        elsewhere_read = StorySummaryVersionName(
            story=elsewhere, version=(await versions_of(store, elsewhere))[0].version
        )
        alike_read = StorySummaryVersionName(
            story=alike, version=(await versions_of(store, alike))[0].version
        )
        read = await state_of(store, story_id)
        before = await everything(store)

        outcome = await store.write_summary(
            story_id,
            draft(line("Line."), read_pages=(alike_read, elsewhere_read)),
            as_of=read.as_of,
        )

        summary_refused(outcome, StorySummaryRefusalReason.ANOTHER_HOME)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == elsewhere
        assert await everything(store) == before
        same = await written(
            store, story_id, draft(line("Line."), read_pages=(alike_read,)), as_of=read.as_of
        )
        assert same.read_pages == (alike_read,)

    async def test_a_summarys_another_home_comes_after_the_stories_are_known_and_before_the_rest(
        self, store: StoryStore
    ) -> None:
        """Its place in ADR-0303 §4's fixed order, which ADR-0302 §7:4 orders around.

        After ``summary_moved_on`` and after every named story's ``unknown_story``, the
        versions read included; before ``not_held`` and ``over_cap``; and the flags'
        stories before the versions read.
        """
        story_id = await made(store, act("a1"))
        flagged = await homed(store, RecordHome.shared(), act("a2"))
        read_one = await homed(store, RecordHome.shared(), act("a3"))
        await written(store, read_one, draft(line("Its matter.")), as_of=await store.position())
        across = StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=flagged)
        read_across = StorySummaryVersionName(
            story=read_one, version=(await versions_of(store, read_one))[0].version
        )
        stale = await state_of(store, story_id)
        await written(store, story_id, draft(line("Since.")), as_of=stale.as_of)
        read = await state_of(store, story_id)
        before = await everything(store)

        moved_on = await store.write_summary(
            story_id, draft(line("Line."), flags=(across,)), as_of=stale.as_of
        )
        unknown = await store.write_summary(
            story_id,
            draft(
                line("Line."),
                flags=(across,),
                read_pages=(StorySummaryVersionName(story="story:nowhere", version=1),),
            ),
            as_of=read.as_of,
        )
        flags_first = await store.write_summary(
            story_id,
            draft(line("Line."), flags=(across,), read_pages=(read_across,)),
            as_of=read.as_of,
        )
        not_held = await store.write_summary(
            story_id,
            draft(line("Line."), took_in_episodes=("a9",), read_pages=(read_across,)),
            as_of=read.as_of,
        )
        over_cap = await store.write_summary(
            story_id,
            draft(
                *(line("x" * STORY_NOTE_MAX_CHARS) for _ in range(5)),
                flags=(across,),
            ),
            as_of=read.as_of,
        )

        summary_refused(moved_on, StorySummaryRefusalReason.SUMMARY_MOVED_ON)
        summary_refused(unknown, StorySummaryRefusalReason.UNKNOWN_STORY)
        for outcome, named in ((flags_first, flagged), (not_held, read_one), (over_cap, flagged)):
            summary_refused(outcome, StorySummaryRefusalReason.ANOTHER_HOME)
            assert outcome.refusal is not None
            assert outcome.refusal.story_id == named
        assert await everything(store) == before

    @pytest.mark.parametrize(("home", "other"), _TWO_HOMES, ids=_TWO_HOMES_IDS)
    @pytest.mark.parametrize("operation", ["create", "link", "merge", "split", "move"])
    async def test_deciding_a_flag_writes_no_decided_line_into_a_story_of_another_home(
        self, store: StoryStore, home: RecordHome, other: RecordHome, operation: str
    ) -> None:
        """§3:2, §4:7: a write answering a flag of another home than its own is refused.

        The flag was raised by a story of the other home, so its ``decided`` line would be
        written there: refused ``another_home``, naming that story, and nothing written —
        no member moved, no line logged, no story minted, the position where it was, a
        merge's included, whose change is applied and rolled back. A write of the flag's
        own home then decides it.
        """
        flagged = await homed(store, other, act("f1"), act("f2"))
        flag = await raised(store, flagged, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
        first = await homed(store, home, act("a1"), act("a2"))
        second = await homed(store, home, act("b1"))
        before = await everything(store)
        position = await store.position()

        match operation:
            case "create":
                outcome = await store.create([sub(first)], home=home, actor=_PASS, answers=flag)
            case "link":
                outcome = await store.link(first, [sub(second)], actor=_PASS, answers=flag)
            case "merge":
                outcome = await store.merge(second, first, actor=_PASS, answers=flag)
            case "split":
                outcome = await store.split(first, [act("a1")], actor=_PASS, answers=flag)
            case _:
                outcome = await store.move(first, second, [act("a1")], actor=_PASS, answers=flag)

        refused(outcome, StoryRefusalReason.ANOTHER_HOME)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == flagged
        assert await held(store, first) == [act("a1"), act("a2")]
        assert await held(store, second) == [act("b1")]
        assert await store.position() == position
        assert await everything(store) == before
        decided = await store.split(flagged, [act("f1")], actor=_PASS, answers=flag)
        assert decided.refusal is None, decided
        assert [line.answers for line in await logged(store, flagged)][-1] == flag

    async def test_a_decisions_another_home_comes_after_the_operations_rule_and_the_flags(
        self, store: StoryStore
    ) -> None:
        """Its place: after the operation's own rule and ``unknown_flag``/``already_decided``.

        A link closing a loop, and a merge closing one, is ``loop``; a flag already
        decided is ``already_decided``; a flag no record holds ``unknown_flag``. Nothing
        is written by any of them.
        """
        flagged = await homed(store, RecordHome.shared(), act("f1"))
        flag = await raised(store, flagged, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
        decided_flag = await raised(store, flagged, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
        assert (await store.leave_flag(decided_flag, actor=_PASS)).refusal is None
        inner = await made(store, act("c1"))
        middle = await made(store, sub(inner))
        outer = await made(store, sub(middle))
        spare = await made(store, act("c2"))
        unknown = StoryFlagName(
            story=flagged, version=999, flag=StoryFlag(kind=StoryFlagKind.TWO_MATTERS)
        )
        before = await everything(store)

        link_loop = await store.link(inner, [sub(outer)], actor=_PASS, answers=flag)
        # ``outer`` merged into ``inner``: ``inner`` gains ``middle``, which holds it.
        merge_loop = await store.merge(outer, inner, actor=_PASS, answers=flag)
        already = await store.link(inner, [sub(spare)], actor=_PASS, answers=decided_flag)
        never = await store.link(inner, [sub(spare)], actor=_PASS, answers=unknown)

        refused(link_loop, StoryRefusalReason.LOOP)
        refused(merge_loop, StoryRefusalReason.LOOP)
        refused(already, StoryRefusalReason.ALREADY_DECIDED)
        refused(never, StoryRefusalReason.UNKNOWN_FLAG)
        assert await everything(store) == before

    @pytest.mark.parametrize("which", ["named", "raising"])
    async def test_a_flag_whose_stories_span_two_homes_is_decided_by_no_write(
        self,
        store: StoryStore,
        set_story_home: Callable[[StoryStore, str, RecordHome], None],
        which: str,
    ) -> None:
        """§3:2, §4:7: a flag across two homes in a file written before these refusals.

        A ``like_another`` flag whose two stories are of two homes is read back as it was
        recorded, and no write decides it: ``leave_flag`` is refused ``another_home``
        naming the story of another home than the first the flag concerns, and so is a
        write of either home answering it; nothing is written.
        """
        raising = await made(store, act("a1"))
        named = await made(store, act("a2"))
        flag_raised = StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=named)
        flag = await raised(store, raising, flag_raised)
        moved = named if which == "named" else raising
        stayed = raising if which == "named" else named
        set_story_home(store, moved, RecordHome.shared())
        alike = await made(store, act("a3"))
        lent = await homed(store, RecordHome.shared(), act("x1"))
        before = await everything(store)

        left = await store.leave_flag(flag, actor=_PASS, outcome=StoryDecision.NOT_APPLIED)
        owners_write = await store.create(
            [sub(alike)], home=RecordHome.owners(), actor=_PASS, answers=flag
        )
        shared_write = await store.split(lent, [act("x1")], actor=_PASS, answers=flag)

        for outcome, named_story in ((left, named), (owners_write, moved), (shared_write, stayed)):
            refused(outcome, StoryRefusalReason.ANOTHER_HOME)
            assert outcome.refusal is not None
            assert outcome.refusal.story_id == named_story
        assert await everything(store) == before
        assert (await versions_of(store, raising))[-1].flags == (flag_raised,)

    async def test_a_flag_whose_raiser_was_merged_across_homes_is_decided_by_no_write(
        self,
        store: StoryStore,
        set_story_home: Callable[[StoryStore, str, RecordHome], None],
    ) -> None:
        """§4:7: a ``decided`` line carries the flag, so names the story that raised it.

        In a file written before these refusals, a story of another home that raised a
        flag can have been merged into one of the owner's: the stories the flag concerns
        are then the owner's alone, but every ``decided`` line would name the raiser. So
        ``leave_flag`` and an owner's write answering it are refused ``another_home``
        naming the raiser, after the stories it concerns, and nothing is written.
        """
        raising = await made(store, act("a1"))
        named = await made(store, act("a2"))
        into = await made(store, act("a3"))
        alike = await made(store, act("a4"))
        flag = await raised(store, raising, StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=named))
        assert (await store.merge(raising, into, actor=_OWNER)).refusal is None
        set_story_home(store, raising, RecordHome.shared())
        before = await everything(store)

        left = await store.leave_flag(flag, actor=_PASS)
        answered = await store.link(into, [sub(alike)], actor=_PASS, answers=flag)

        for outcome in (left, answered):
            refused(outcome, StoryRefusalReason.ANOTHER_HOME)
            assert outcome.refusal is not None
            assert outcome.refusal.story_id == raising
        assert await everything(store) == before

    # --- create (§3) ---------------------------------------------------------

    async def test_create_mints_a_story_with_its_members_in_order(self, store: StoryStore) -> None:
        """Create mints a ``story:`` id, logs ``created`` then each member ``added``."""
        outcome = await store.create([act("a1"), act("a2")], home=RecordHome.owners(), actor=_OWNER)
        assert outcome.refusal is None
        assert outcome.logged == 3
        story_id = outcome.story_id
        assert story_id is not None
        assert story_id.startswith(STORY_ID_PREFIX)
        header = await store.header(story_id)
        assert header is not None
        assert header.story_id == story_id
        assert header.created_at == STORY_AT
        assert header.merged_into is None
        page = await store.view(story_id)
        assert page is not None
        assert page.member_count == 2
        assert [entry.member for entry in page.entries] == [act("a1"), act("a2")]
        assert all(entry.linked_at == STORY_AT for entry in page.entries)
        assert all(entry.actor is _OWNER for entry in page.entries)
        lines = await logged(store, story_id)
        assert shape(lines) == [
            (StoryChange.CREATED, None),
            (StoryChange.ADDED, "a1"),
            (StoryChange.ADDED, "a2"),
        ]
        assert all(line.story_id == story_id and line.at == STORY_AT for line in lines)
        assert all(line.actor is _OWNER and line.trigger is None for line in lines)

    async def test_a_story_of_one_member_is_a_story(self, store: StoryStore) -> None:
        """The store does not require two members; connecting is the linker's call."""
        story_id = await made(store, act("only"))
        assert await held(store, story_id) == [act("only")]

    async def test_create_with_no_members_is_refused_and_writes_nothing(
        self, store: StoryStore
    ) -> None:
        refused(
            await store.create([], home=RecordHome.owners(), actor=_OWNER),
            StoryRefusalReason.NO_MEMBERS,
        )
        assert (await store.stories()).stories == ()

    async def test_a_member_named_twice_is_added_once(self, store: StoryStore) -> None:
        outcome = await store.create(
            [act("a"), act("a"), act("b")], home=RecordHome.owners(), actor=_OWNER
        )
        assert outcome.logged == 3
        assert outcome.story_id is not None
        assert await held(store, outcome.story_id) == [act("a"), act("b")]

    async def test_the_kind_is_carried_never_inferred(self, store: StoryStore) -> None:
        """An activation member whose id looks like a story id is still an activation."""
        story_id = await made(store, act("x"))
        other = await made(store, act(story_id), sub(story_id))
        assert await held(store, other) == [act(story_id), sub(story_id)]
        assert [h.story_id for h in await store.stories_of(act(story_id))] == [other]
        assert [h.story_id for h in await store.stories_of(sub(story_id))] == [other]
        assert await store.stories_of(act("x")) != await store.stories_of(sub("x"))

    async def test_create_naming_an_unknown_story_is_refused(self, store: StoryStore) -> None:
        outcome = await store.create(
            [act("a"), sub("story:nowhere")], home=RecordHome.owners(), actor=_OWNER
        )
        refused(outcome, StoryRefusalReason.UNKNOWN_STORY)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == "story:nowhere"
        assert (await store.stories()).stories == ()

    async def test_a_trigger_is_recorded_on_every_line(self, store: StoryStore) -> None:
        outcome = await store.create(
            [act("a")], home=RecordHome.owners(), actor=_OWNER, trigger="activation-7"
        )
        assert outcome.story_id is not None
        lines = await logged(store, outcome.story_id)
        assert [line.trigger for line in lines] == ["activation-7", "activation-7"]

    # --- link and unlink (§3) -----------------------------------------------

    async def test_link_adds_and_passes_over_a_member_already_held(self, store: StoryStore) -> None:
        story_id = await made(store, act("a"))
        before = await store.view(story_id)
        assert before is not None
        outcome = await store.link(story_id, [act("a"), act("b")], actor=_OWNER)
        assert outcome.refusal is None
        assert outcome.story_id == story_id
        assert outcome.logged == 1
        after = await store.view(story_id)
        assert after is not None
        assert after.entries[0] == before.entries[0]
        assert [entry.member for entry in after.entries] == [act("a"), act("b")]
        assert shape(await logged(store, story_id))[-1] == (StoryChange.ADDED, "b")
        assert len(await logged(store, story_id)) == 3

    async def test_link_with_nothing_new_writes_nothing(self, store: StoryStore) -> None:
        story_id = await made(store, act("a"))
        before = await everything(store)
        outcome = await store.link(story_id, [act("a")], actor=_OWNER)
        assert outcome.story_id == story_id
        assert outcome.logged == 0
        assert await everything(store) == before

    async def test_unlink_removes_and_passes_over_a_member_not_held(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a"), act("b"))
        outcome = await store.unlink(story_id, [act("a"), act("zz")], actor=_OWNER)
        assert outcome.story_id == story_id
        assert outcome.logged == 1
        assert await held(store, story_id) == [act("b")]
        assert shape(await logged(store, story_id))[-1] == (StoryChange.REMOVED, "a")

    async def test_a_story_emptied_by_unlink_stays_a_story(self, store: StoryStore) -> None:
        story_id = await made(store, act("a"))
        await store.unlink(story_id, [act("a")], actor=_OWNER)
        header = await store.header(story_id)
        assert header is not None
        page = await store.view(story_id)
        assert page is not None
        assert page.member_count == 0
        assert page.entries == ()
        assert [h.story_id for h in (await store.stories()).stories] == [story_id]

    @pytest.mark.parametrize("operation", ["link", "unlink", "split"])
    async def test_a_write_naming_no_member_is_refused(
        self, store: StoryStore, operation: str
    ) -> None:
        story_id = await made(store, act("a"))
        before = await everything(store)
        outcome = await getattr(store, operation)(story_id, [], actor=_OWNER)
        refused(outcome, StoryRefusalReason.NO_MEMBERS)
        assert await everything(store) == before

    @pytest.mark.parametrize("operation", ["link", "unlink", "split"])
    async def test_a_write_to_an_unknown_story_is_refused(
        self, store: StoryStore, operation: str
    ) -> None:
        outcome = await getattr(store, operation)("story:nowhere", [act("a")], actor=_OWNER)
        refused(outcome, StoryRefusalReason.UNKNOWN_STORY)
        assert outcome.refusal.story_id == "story:nowhere"
        assert (await store.stories()).stories == ()

    @pytest.mark.parametrize("operation", ["link", "unlink"])
    async def test_a_write_naming_an_unknown_story_member_is_refused(
        self, store: StoryStore, operation: str
    ) -> None:
        story_id = await made(store, act("a"))
        before = await everything(store)
        outcome = await getattr(store, operation)(
            story_id, [act("b"), sub("story:nowhere")], actor=_OWNER
        )
        refused(outcome, StoryRefusalReason.UNKNOWN_STORY)
        assert outcome.refusal.story_id == "story:nowhere"
        assert await everything(store) == before

    async def test_linking_a_story_into_itself_is_a_loop(self, store: StoryStore) -> None:
        story_id = await made(store, act("a"))
        before = await everything(store)
        outcome = await store.link(story_id, [act("b"), sub(story_id)], actor=_OWNER)
        refused(outcome, StoryRefusalReason.LOOP)
        assert outcome.refusal is not None
        assert outcome.refusal.loop == (story_id,)
        assert await everything(store) == before

    async def test_a_link_closing_a_chain_is_refused_naming_the_loop(
        self, store: StoryStore
    ) -> None:
        """C inside B inside A: linking A into C would make each contain itself."""
        inner = await made(store, act("c"))
        middle = await made(store, sub(inner))
        outer = await made(store, sub(middle))
        before = await everything(store)
        outcome = await store.link(inner, [sub(outer)], actor=_OWNER)
        refused(outcome, StoryRefusalReason.LOOP)
        assert outcome.refusal is not None
        assert outcome.refusal.loop == (inner, outer, middle)
        assert await everything(store) == before

    async def test_a_story_may_belong_to_two_stories(self, store: StoryStore) -> None:
        """Sharing a member is not a loop: only containing oneself is."""
        shared = await made(store, act("s"))
        first = await made(store, sub(shared))
        second = await made(store, sub(shared))
        outcome = await store.link(second, [sub(first)], actor=_OWNER)
        assert outcome.refusal is None
        assert [h.story_id for h in await store.stories_of(sub(shared))] == [second, first]

    # --- merge (§3) ----------------------------------------------------------

    async def test_merge_moves_members_and_keeps_an_entry_the_target_holds(
        self, store: StoryStore
    ) -> None:
        absorbed = await made(store, act("x"), act("y"))
        target = await made(store, act("y"), act("z"))
        before = await store.view(target)
        assert before is not None
        outcome = await store.merge(absorbed, target, actor=_OWNER)
        assert outcome.refusal is None
        assert outcome.story_id == target
        after = await store.view(target)
        assert after is not None
        assert [entry.member for entry in after.entries] == [act("y"), act("z"), act("x")]
        assert after.entries[:2] == before.entries
        assert await held(store, absorbed) == []
        header = await store.header(absorbed)
        assert header is not None
        assert header.merged_into == target
        assert shape(await logged(store, absorbed))[3:] == [
            (StoryChange.MERGED_INTO, target),
            (StoryChange.REMOVED, "x"),
            (StoryChange.REMOVED, "y"),
        ]
        assert shape(await logged(store, target))[3:] == [
            (StoryChange.ABSORBED, absorbed),
            (StoryChange.ADDED, "x"),
        ]
        assert outcome.logged == 5

    async def test_merging_a_story_into_one_it_holds_drops_that_member(
        self, store: StoryStore
    ) -> None:
        """Where B is a member of A, A into B removes it and adds nothing for it."""
        target = await made(store, act("t"))
        absorbed = await made(store, sub(target), act("x"))
        outcome = await store.merge(absorbed, target, actor=_OWNER)
        assert outcome.refusal is None
        assert await held(store, target) == [act("t"), act("x")]
        assert await held(store, absorbed) == []
        assert await store.stories_of(sub(target)) == ()

    async def test_merge_rewires_the_absorbed_storys_holders(self, store: StoryStore) -> None:
        """A leaves every holder; B joins each that lacks it and is not B."""
        absorbed = await made(store, act("a"))
        target = await made(store, act("b"), sub(absorbed))
        lacking = await made(store, act("p"), sub(absorbed))
        holding_both = await made(store, sub(target), sub(absorbed))
        kept = await store.view(holding_both)
        assert kept is not None
        outcome = await store.merge(absorbed, target, actor=_OWNER)
        assert outcome.refusal is None
        assert await held(store, target) == [act("b"), act("a")]
        assert await held(store, lacking) == [act("p"), sub(target)]
        after = await store.view(holding_both)
        assert after is not None
        assert [entry.member for entry in after.entries] == [sub(target)]
        assert after.entries[0] == kept.entries[0]
        assert await store.stories_of(sub(absorbed)) == ()
        assert shape(await logged(store, lacking))[-2:] == [
            (StoryChange.REMOVED, absorbed),
            (StoryChange.ADDED, target),
        ]
        assert shape(await logged(store, holding_both))[-1:] == [
            (StoryChange.REMOVED, absorbed),
        ]

    async def test_a_merge_closing_a_loop_through_a_member_is_refused(
        self, store: StoryStore
    ) -> None:
        """A holds X, X holds B: A into B would give B a member that holds B."""
        target = await made(store, act("b"))
        middle = await made(store, sub(target))
        absorbed = await made(store, sub(middle))
        before = await everything(store)
        outcome = await store.merge(absorbed, target, actor=_OWNER)
        refused(outcome, StoryRefusalReason.LOOP)
        assert outcome.refusal is not None
        assert outcome.refusal.loop == (target, middle)
        assert await everything(store) == before

    async def test_a_merge_closing_a_loop_through_a_holder_is_refused(
        self, store: StoryStore
    ) -> None:
        """P holds A, B holds P: A into B would put B inside P inside B."""
        absorbed = await made(store, act("a"))
        holder = await made(store, sub(absorbed))
        target = await made(store, sub(holder))
        before = await everything(store)
        outcome = await store.merge(absorbed, target, actor=_OWNER)
        refused(outcome, StoryRefusalReason.LOOP)
        assert outcome.refusal is not None
        assert outcome.refusal.loop == (target, holder)
        assert await everything(store) == before

    async def test_a_merge_into_itself_is_refused(self, store: StoryStore) -> None:
        story_id = await made(store, act("a"))
        outcome = await store.merge(story_id, story_id, actor=_OWNER)
        refused(outcome, StoryRefusalReason.SELF_MERGE)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == story_id

    async def test_a_merge_naming_an_unknown_story_is_refused(self, store: StoryStore) -> None:
        story_id = await made(store, act("a"))
        before = await everything(store)
        refused(
            await store.merge(story_id, "story:nowhere", actor=_OWNER),
            StoryRefusalReason.UNKNOWN_STORY,
        )
        refused(
            await store.merge("story:nowhere", story_id, actor=_OWNER),
            StoryRefusalReason.UNKNOWN_STORY,
        )
        assert await everything(store) == before

    # --- merged stories (§3) -------------------------------------------------

    async def test_every_write_touching_a_merged_story_names_where_it_went(
        self, store: StoryStore
    ) -> None:
        absorbed = await made(store, act("a"))
        target = await made(store, act("b"))
        other = await made(store, act("c"))
        await store.merge(absorbed, target, actor=_OWNER)
        before = await everything(store)
        attempts = [
            store.link(absorbed, [act("d")], actor=_OWNER),
            store.unlink(absorbed, [act("a")], actor=_OWNER),
            store.split(absorbed, [act("a")], actor=_OWNER),
            store.merge(absorbed, other, actor=_OWNER),
            store.merge(other, absorbed, actor=_OWNER),
            store.create([sub(absorbed)], home=RecordHome.owners(), actor=_OWNER),
            store.link(other, [sub(absorbed)], actor=_OWNER),
        ]
        for attempt in attempts:
            outcome = await attempt
            refused(outcome, StoryRefusalReason.MERGED_STORY)
            assert outcome.refusal is not None
            assert outcome.refusal.story_id == absorbed
            assert outcome.refusal.merged_into == target
        assert await everything(store) == before

    async def test_a_merged_story_is_still_read(self, store: StoryStore) -> None:
        """Reading a merged story returns its header, so a caller follows it."""
        absorbed = await made(store, act("a"))
        target = await made(store, act("b"))
        await store.merge(absorbed, target, actor=_OWNER)
        page = await store.view(absorbed)
        assert page is not None
        assert page.story.merged_into == target
        assert page.entries == ()
        assert [h.story_id for h in (await store.stories()).stories] == [target, absorbed]

    # --- split (§3) ----------------------------------------------------------

    async def test_split_moves_members_into_a_new_story_in_link_order(
        self, store: StoryStore
    ) -> None:
        source = await made(store, act("x"), act("y"), act("z"))
        outcome = await store.split(source, [act("z"), act("x")], actor=_OWNER)
        assert outcome.refusal is None
        split_off = outcome.story_id
        assert split_off is not None
        assert split_off.startswith(STORY_ID_PREFIX)
        assert split_off != source
        assert outcome.logged == 7
        assert await held(store, split_off) == [act("x"), act("z")]
        assert await held(store, source) == [act("y")]
        assert await store.stories_of(sub(split_off)) == ()
        assert shape(await logged(store, source))[4:] == [
            (StoryChange.SPLIT_OFF, split_off),
            (StoryChange.REMOVED, "x"),
            (StoryChange.REMOVED, "z"),
        ]
        assert shape(await logged(store, split_off)) == [
            (StoryChange.CREATED, None),
            (StoryChange.SPLIT_OFF, source),
            (StoryChange.ADDED, "x"),
            (StoryChange.ADDED, "z"),
        ]

    async def test_a_split_may_take_every_member(self, store: StoryStore) -> None:
        source = await made(store, act("x"))
        outcome = await store.split(source, [act("x")], actor=_OWNER)
        assert outcome.story_id is not None
        assert await held(store, source) == []
        assert await held(store, outcome.story_id) == [act("x")]

    async def test_a_split_naming_a_non_member_is_refused(self, store: StoryStore) -> None:
        source = await made(store, act("x"), act("y"))
        before = await everything(store)
        outcome = await store.split(source, [act("x"), act("nope")], actor=_OWNER)
        refused(outcome, StoryRefusalReason.NOT_A_MEMBER)
        assert outcome.refusal is not None
        assert outcome.refusal.member == act("nope")
        assert await everything(store) == before

    # --- the change log (§2) -------------------------------------------------

    async def test_sequence_numbers_are_unique_across_the_store_and_ascending(
        self, store: StoryStore
    ) -> None:
        first = await made(store, act("a"))
        second = await made(store, act("b"))
        await store.link(first, [act("c")], actor=_OWNER)
        await store.merge(first, second, actor=_OWNER)
        sequences = [
            line.sequence for story_id in (first, second) for line in await logged(store, story_id)
        ]
        assert len(set(sequences)) == len(sequences)
        for story_id in (first, second):
            own = [line.sequence for line in await logged(store, story_id)]
            assert own == sorted(own)

    async def test_no_line_is_rewritten_by_a_later_change(self, store: StoryStore) -> None:
        source = await made(store, act("a"), act("b"))
        earlier = await logged(store, source)
        target = await made(store, act("c"))
        await store.split(source, [act("a")], actor=_OWNER)
        await store.merge(source, target, actor=_OWNER)
        assert (await logged(store, source))[: len(earlier)] == earlier

    # --- reads (§3) ----------------------------------------------------------

    async def test_an_unknown_story_reads_as_absent(self, store: StoryStore) -> None:
        assert await store.header("story:nowhere") is None
        assert await store.view("story:nowhere") is None
        assert await store.log("story:nowhere") is None

    async def test_the_view_pages_in_link_order(self, store: StoryStore) -> None:
        story_id = await made(store, *(act(f"m{n}") for n in range(5)))
        seen: list[StoryMember] = []
        cursor: int | None = None
        while True:
            page = await store.view(story_id, cursor=cursor, limit=2)
            assert page is not None
            assert page.member_count == 5
            assert len(page.entries) <= 2
            seen.extend(entry.member for entry in page.entries)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        assert seen == [act(f"m{n}") for n in range(5)]

    async def test_the_log_pages_in_sequence_order(self, store: StoryStore) -> None:
        story_id = await made(store, *(act(f"m{n}") for n in range(4)))
        whole = await logged(store, story_id)
        seen: list[StoryLogLine] = []
        cursor: int | None = None
        while True:
            page = await store.log(story_id, cursor=cursor, limit=2)
            assert page is not None
            seen.extend(page.lines)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        assert seen == whole

    async def test_stories_page_newest_first(self, store: StoryStore) -> None:
        made_ids = [await made(store, act(f"m{n}")) for n in range(5)]
        seen: list[str] = []
        cursor: int | None = None
        while True:
            page = await store.stories(cursor=cursor, limit=2)
            seen.extend(header.story_id for header in page.stories)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        assert seen == made_ids[::-1]

    async def test_the_reverse_lookup_is_direct_and_newest_first(self, store: StoryStore) -> None:
        first = await made(store, act("a"))
        second = await made(store, act("a"), act("b"))
        await made(store, sub(second))
        assert [h.story_id for h in await store.stories_of(act("a"))] == [second, first]
        assert [h.story_id for h in await store.stories_of(act("b"))] == [second]
        assert await store.stories_of(act("none")) == ()

    # --- arguments -----------------------------------------------------------

    @pytest.mark.parametrize("limit", [0, MAX_STORY_PAGE + 1, True, 1.0])
    async def test_a_page_limit_out_of_range_is_a_value_error(
        self, store: StoryStore, limit: object
    ) -> None:
        story_id = await made(store, act("a"))
        with pytest.raises(ValueError, match="limit"):
            await store.view(story_id, limit=limit)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="limit"):
            await store.stories(limit=limit)  # type: ignore[arg-type]

    @pytest.mark.parametrize("cursor", [-1, 2**63, True, "1"])
    async def test_a_cursor_out_of_range_is_a_value_error(
        self, store: StoryStore, cursor: object
    ) -> None:
        story_id = await made(store, act("a"))
        with pytest.raises(ValueError, match="cursor"):
            await store.log(story_id, cursor=cursor)  # type: ignore[arg-type]

    @pytest.mark.parametrize("members", ["a", [object()], [None], 7])
    async def test_malformed_members_are_a_value_error(
        self, store: StoryStore, members: object
    ) -> None:
        with pytest.raises(ValueError, match="member"):
            await store.create(members, home=RecordHome.owners(), actor=_OWNER)  # type: ignore[arg-type]
        assert (await store.stories()).stories == ()

    async def test_a_blank_story_id_or_unknown_actor_is_a_value_error(
        self, store: StoryStore
    ) -> None:
        with pytest.raises(ValueError):  # noqa: PT011 — any validation message will do
            await store.link("  ", [act("a")], actor=_OWNER)
        with pytest.raises(ValueError):  # noqa: PT011 — any validation message will do
            await store.create([act("a")], home=RecordHome.owners(), actor="planner")  # type: ignore[arg-type]
        assert (await store.stories()).stories == ()

    # --- the actors ADR-0300 adds (§3:15) ------------------------------------

    @pytest.mark.parametrize(
        "actor", [StoryActor.UNDERSTANDING, StoryActor.PLANNING, StoryActor.MATTERS_PASS]
    )
    async def test_each_new_actor_is_recorded_as_it_writes(
        self, store: StoryStore, actor: StoryActor
    ) -> None:
        outcome = await store.create([act("a")], home=RecordHome.owners(), actor=actor, trigger="a")
        assert outcome.story_id is not None
        view = await store.view(outcome.story_id)
        assert view is not None
        assert [entry.actor for entry in view.entries] == [actor]
        assert {line.actor for line in await logged(store, outcome.story_id)} == {actor}

    # --- notes (ADR-0300 §3:1-§3:4) ------------------------------------------

    async def test_a_note_is_written_with_its_fields_and_is_pending(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        first = await noted(store, story_id, "Leaning against Saturday.", outside=True)
        second = await noted(store, story_id, "No Saturdays.", author=StoryNoteAuthor.OWNER)
        assert first.text == "Leaning against Saturday."
        assert first.author is StoryNoteAuthor.PLANNING
        assert first.written_during == "a1"
        assert first.outside is True
        assert first.written_at == STORY_AT
        assert second.written_during is None
        assert second.outside is False
        assert second.note_id > first.note_id
        assert await notes_of(store, story_id) == [first, second]
        state = await state_of(store, story_id)
        assert state.pending_notes == (first, second)
        assert state.summary is None

    async def test_a_note_keeps_its_text_byte_for_byte(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        text = "  Sister would prefer Saturday (her message).\n"
        note = await noted(store, story_id, text, author=StoryNoteAuthor.OWNER)
        assert note.text == text
        assert (await notes_of(store, story_id))[0].text == text

    @pytest.mark.parametrize(
        ("author", "written_during", "outside"),
        [
            (StoryNoteAuthor.OWNER, "a1", False),
            (StoryNoteAuthor.OWNER, None, True),
            (StoryNoteAuthor.PLANNING, None, False),
            (StoryNoteAuthor.TIDY_UP, "a1", False),
            ("someone", "a1", False),
            (StoryNoteAuthor.PLANNING, "  ", False),
            (StoryNoteAuthor.PLANNING, "a1", 1),
        ],
    )
    async def test_a_note_its_author_does_not_admit_is_a_value_error(
        self, store: StoryStore, author: object, written_during: object, outside: object
    ) -> None:
        story_id = await made(store, act("a1"))
        before = await everything(store)
        with pytest.raises(ValueError):  # noqa: PT011 — any validation message will do
            await store.append_note(
                story_id,
                "a note",
                author=author,  # type: ignore[arg-type]
                written_during=written_during,  # type: ignore[arg-type]
                outside=outside,  # type: ignore[arg-type]
            )
        assert await everything(store) == before

    @pytest.mark.parametrize("text", ["", "   ", "x" * (STORY_NOTE_MAX_CHARS + 1), 7])
    async def test_a_note_text_out_of_bounds_is_a_value_error(
        self, store: StoryStore, text: object
    ) -> None:
        story_id = await made(store, act("a1"))
        with pytest.raises(ValueError):  # noqa: PT011 — any validation message will do
            await store.append_note(
                story_id,
                text,  # type: ignore[arg-type]
                author=StoryNoteAuthor.PLANNING,
                written_during="a1",
            )
        assert await notes_of(store, story_id) == []

    async def test_a_note_at_the_bound_is_written(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "x" * STORY_NOTE_MAX_CHARS)
        assert len(note.text) == STORY_NOTE_MAX_CHARS

    async def test_a_note_for_an_unknown_or_merged_story_is_refused(
        self, store: StoryStore
    ) -> None:
        absorbed = await made(store, act("a"))
        target = await made(store, act("b"))
        await store.merge(absorbed, target, actor=_OWNER)
        before = await everything(store)
        unknown = await store.append_note(
            "story:nowhere", "n", author=StoryNoteAuthor.PLANNING, written_during="a"
        )
        summary_refused(unknown, StorySummaryRefusalReason.UNKNOWN_STORY)
        assert unknown.refusal is not None
        assert unknown.refusal.story_id == "story:nowhere"
        merged = await store.append_note(absorbed, "n", author=StoryNoteAuthor.OWNER)
        summary_refused(merged, StorySummaryRefusalReason.MERGED_STORY)
        assert merged.refusal is not None
        assert merged.refusal.merged_into == target
        assert await everything(store) == before

    async def test_a_note_may_record_an_activation_the_story_does_not_hold(
        self, store: StoryStore
    ) -> None:
        """Planning may write to any story by id (ADR-0300 §10); the store reads no other."""
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "From elsewhere.", on="elsewhere")
        assert note.written_during == "elsewhere"

    async def test_notes_page_in_the_order_they_were_written(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        other = await made(store, act("a2"))
        mine = []
        for n in range(5):
            mine.append(await noted(store, story_id, f"note {n}"))
            await noted(store, other, f"other {n}")
        seen: list[StoryNote] = []
        cursor: int | None = None
        while True:
            page = await store.notes(story_id, cursor=cursor, limit=2)
            assert page is not None
            seen.extend(page.notes)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        assert seen == mine

    async def test_an_unknown_story_has_no_summary(self, store: StoryStore) -> None:
        assert await store.current_summary("story:nowhere") is None
        assert await store.notes("story:nowhere") is None
        assert await store.summary_versions("story:nowhere") is None

    # --- pending (ADR-0300 §3:8) ---------------------------------------------

    async def test_activation_members_are_pending_in_link_order(self, store: StoryStore) -> None:
        inner = await made(store, act("x"))
        story_id = await made(store, act("a2"), sub(inner), act("a1"))
        await store.link(story_id, [act("a3")], actor=_OWNER)
        state = await state_of(store, story_id)
        assert state.pending_episodes == ("a2", "a1", "a3")

    async def test_a_summary_write_takes_in_what_it_names(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"), act("a2"))
        note = await noted(store, story_id, "Camping at Riverside.")
        before = await state_of(store, story_id)
        version = await written(
            store,
            story_id,
            draft(
                line("A camping trip to Riverside."),
                took_in_notes=(note.note_id,),
                took_in_episodes=("a1",),
            ),
            as_of=before.as_of,
        )
        assert version.took_in_notes == (note.note_id,)
        assert version.took_in_episodes == ("a1",)
        after = await state_of(store, story_id)
        assert after.pending_notes == ()
        assert after.pending_episodes == ("a2",)
        assert after.summary is not None
        assert after.summary.version == version.version
        assert after.summary.written_at == STORY_AT
        assert after.summary.lines == (StorySummaryLine(text="A camping trip to Riverside."),)
        assert after.summary.outside is False
        assert version.outside is False

    async def test_what_becomes_pending_while_a_run_is_out_stays_pending(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        first = await noted(store, story_id, "First.")
        read = await state_of(store, story_id)
        late = await noted(store, story_id, "Late.")
        await store.link(story_id, [act("a2")], actor=_OWNER)
        version = await written(
            store,
            story_id,
            draft(
                line("The matter."),
                took_in_notes=(first.note_id, late.note_id),
                took_in_episodes=("a1", "a2"),
            ),
            as_of=read.as_of,
        )
        assert version.took_in_notes == (first.note_id,)
        assert version.took_in_episodes == ("a1",)
        after = await state_of(store, story_id)
        assert after.pending_notes == (late,)
        assert after.pending_episodes == ("a2",)

    async def test_an_episode_that_left_and_came_back_during_a_run_stays_pending(
        self, store: StoryStore
    ) -> None:
        """It came to the story again after the read, whatever its id says."""
        story_id = await made(store, act("a1"))
        await noted(store, story_id, "Note.")
        read = await state_of(store, story_id)
        await store.unlink(story_id, [act("a1")], actor=_OWNER)
        await store.link(story_id, [act("a1")], actor=_OWNER)
        version = await written(
            store,
            story_id,
            draft(line("The matter."), took_in_episodes=("a1",)),
            as_of=read.as_of,
        )
        assert version.took_in_episodes == ()
        assert (await state_of(store, story_id)).pending_episodes == ("a1",)

    async def test_a_name_not_pending_is_not_recorded_as_taken_in(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Note.")
        read = await state_of(store, story_id)
        version = await written(
            store,
            story_id,
            draft(
                line("The matter."),
                took_in_notes=(note.note_id, note.note_id),
                took_in_episodes=("a1", "a1"),
            ),
            as_of=read.as_of,
        )
        assert version.took_in_notes == (note.note_id,)
        assert version.took_in_episodes == ("a1",)
        again = await state_of(store, story_id)
        second = await written(
            store,
            story_id,
            draft(
                line("The matter."),
                took_in_notes=(note.note_id,),
                took_in_episodes=("a1",),
            ),
            as_of=again.as_of,
        )
        assert second.took_in_notes == ()
        assert second.took_in_episodes == ()

    async def test_one_storys_version_takes_in_nothing_on_another(self, store: StoryStore) -> None:
        first = await made(store, act("shared"))
        second = await made(store, act("shared"))
        await noted(store, first, "Note.", on="shared")
        read = await state_of(store, first)
        await written(
            store,
            first,
            draft(line("The matter."), took_in_episodes=("shared",)),
            as_of=read.as_of,
        )
        assert (await state_of(store, first)).pending_episodes == ()
        assert (await state_of(store, second)).pending_episodes == ("shared",)

    # --- the summary write (ADR-0300 §3:6, §3:7, §3:10) ----------------------

    async def test_a_summary_write_writes_no_note_and_records_its_mark(
        self, store: StoryStore
    ) -> None:
        """ADR-0303 §4:1: the summary's lines and its mark, as given, and no note."""
        story_id = await made(store, act("a1"), act("a2"))
        note = await noted(store, story_id, "Riverside.")
        read = await state_of(store, story_id)
        summary = draft(
            line("A camping trip to Riverside."),
            line("A parks notice said the lower loop closes on the 15th."),
            outside=True,
            took_in_notes=(note.note_id,),
            took_in_episodes=("a1", "a2"),
        )
        version = await written(store, story_id, summary, as_of=read.as_of)
        assert version.outside is True
        assert version.read_pages == ()
        assert await notes_of(store, story_id) == [note]
        state = await state_of(store, story_id)
        assert state.pending_notes == ()
        assert state.summary is not None
        assert state.summary.lines == summary.lines
        assert state.summary.outside is True
        assert await versions_of(store, story_id) == [version]

    async def test_a_summary_may_hold_no_line(self, store: StoryStore) -> None:
        """ADR-0303 §5:3: a version like any other, so what it read stops being pending."""
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Nothing worth a line.")
        read = await state_of(store, story_id)
        version = await written(
            store,
            story_id,
            draft(took_in_notes=(note.note_id,), took_in_episodes=("a1",)),
            as_of=read.as_of,
        )
        assert version.took_in_notes == (note.note_id,)
        state = await state_of(store, story_id)
        assert state.summary is not None
        assert state.summary.lines == ()
        assert (state.pending_notes, state.pending_episodes) == ((), ())

    async def test_a_version_records_its_flags_its_reads_and_its_mark(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        other = await made(store, act("a9"))
        merged = await made(store, act("a8"))
        theirs = await written(
            store,
            other,
            draft(line("The other matter.")),
            as_of=(await state_of(store, other)).as_of,
        )
        gone = await written(
            store,
            merged,
            draft(line("A merged matter.")),
            as_of=(await state_of(store, merged)).as_of,
        )
        await store.merge(merged, other, actor=_OWNER)
        read = await state_of(store, story_id)
        flags = (
            StoryFlag(kind=StoryFlagKind.TWO_MATTERS),
            StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other),
        )
        reads = (
            StorySummaryVersionName(story=other, version=theirs.version),
            StorySummaryVersionName(story=merged, version=gone.version),
            StorySummaryVersionName(story=other, version=theirs.version),
        )
        version = await written(
            store,
            story_id,
            draft(line("Saturday's fine now."), flags=flags, read_pages=reads, outside=True),
            as_of=read.as_of,
        )
        assert version.flags == flags
        assert version.read_pages == reads[:2]
        assert version.outside is True
        assert version.written_at == STORY_AT
        assert await versions_of(store, story_id) == [version]

    async def test_a_new_summary_replaces_the_old_and_the_log_keeps_both(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        await noted(store, story_id, "Note.")
        first = await written(
            store,
            story_id,
            draft(line("Old line.")),
            as_of=(await state_of(store, story_id)).as_of,
        )
        second = await written(
            store,
            story_id,
            draft(line("New line."), line("Another.")),
            as_of=(await state_of(store, story_id)).as_of,
        )
        assert second.version > first.version
        state = await state_of(store, story_id)
        assert state.summary is not None
        assert [ln.text for ln in state.summary.lines] == ["New line.", "Another."]
        assert await versions_of(store, story_id) == [first, second]

    async def test_the_version_log_pages_oldest_first(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        await noted(store, story_id, "Note.")
        made_versions = [
            await written(
                store,
                story_id,
                draft(line(f"Line {n}.")),
                as_of=(await state_of(store, story_id)).as_of,
            )
            for n in range(5)
        ]
        seen: list[StorySummaryVersion] = []
        cursor: int | None = None
        while True:
            page = await store.summary_versions(story_id, cursor=cursor, limit=2)
            assert page is not None
            seen.extend(page.versions)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        assert seen == made_versions

    async def test_a_summary_built_on_a_stale_read_is_refused_and_writes_nothing(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        await noted(store, story_id, "Note.")
        stale = await state_of(store, story_id)
        await written(store, story_id, draft(line("First.")), as_of=stale.as_of)
        before = await everything(store)
        outcome = await store.write_summary(
            story_id,
            draft(line("Second."), took_in_episodes=("a1",)),
            as_of=stale.as_of,
        )
        summary_refused(outcome, StorySummaryRefusalReason.SUMMARY_MOVED_ON)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == story_id
        assert await everything(store) == before

    async def test_a_write_built_on_a_read_after_a_merge_is_not_stale(
        self, store: StoryStore
    ) -> None:
        """Only a version of the story's own summary moves it on."""
        target = await made(store, act("a1"))
        absorbed = await made(store, act("a2"))
        await noted(store, target, "Note.")
        read = await state_of(store, target)
        await store.merge(absorbed, target, actor=_OWNER)
        await written(store, target, draft(line("The matter.")), as_of=read.as_of)

    async def test_a_summary_version_read_naming_an_unknown_story_is_refused(
        self, store: StoryStore
    ) -> None:
        """ADR-0303 §4:2: checked only as an identity the store holds."""
        story_id = await made(store, act("a1"))
        read = await state_of(store, story_id)
        before = await everything(store)
        outcome = await store.write_summary(
            story_id,
            draft(
                line("Line."),
                read_pages=(StorySummaryVersionName(story="story:nowhere", version=1),),
            ),
            as_of=read.as_of,
        )
        summary_refused(outcome, StorySummaryRefusalReason.UNKNOWN_STORY)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == "story:nowhere"
        assert await everything(store) == before

    @pytest.mark.parametrize("wrong", ["itself", "unreached", "another's"])
    async def test_a_summary_version_read_naming_nothing_held_is_a_value_error(
        self, store: StoryStore, wrong: str
    ) -> None:
        """Its own story, a version its story has not reached, or another story's version."""
        story_id = await made(store, act("a1"))
        other = await made(store, act("a2"))
        third = await made(store, act("a3"))
        theirs = await written(
            store, other, draft(line("Other.")), as_of=(await state_of(store, other)).as_of
        )
        mine = await written(
            store, story_id, draft(line("Mine.")), as_of=(await state_of(store, story_id)).as_of
        )
        named = {
            "itself": StorySummaryVersionName(story=story_id, version=mine.version),
            "unreached": StorySummaryVersionName(story=other, version=theirs.version + 10_000),
            "another's": StorySummaryVersionName(story=third, version=theirs.version),
        }[wrong]
        read = await state_of(store, story_id)
        before = await everything(store)
        with pytest.raises(ValueError, match="summary version read"):
            await store.write_summary(
                story_id, draft(line("Line."), read_pages=(named,)), as_of=read.as_of
            )
        assert await everything(store) == before

    async def test_a_flag_naming_an_unknown_story_is_refused(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        await noted(store, story_id, "Note.")
        read = await state_of(store, story_id)
        before = await everything(store)
        outcome = await store.write_summary(
            story_id,
            draft(
                line("Line."),
                flags=(StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story="story:nowhere"),),
            ),
            as_of=read.as_of,
        )
        summary_refused(outcome, StorySummaryRefusalReason.UNKNOWN_STORY)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == "story:nowhere"
        assert await everything(store) == before

    async def test_a_flag_naming_its_own_story_is_a_value_error(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        await noted(store, story_id, "Note.")
        read = await state_of(store, story_id)
        with pytest.raises(ValueError, match="another story"):
            await store.write_summary(
                story_id,
                draft(
                    line("Line."),
                    flags=(StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=story_id),),
                ),
                as_of=read.as_of,
            )

    async def test_a_summary_to_an_unknown_or_merged_story_is_refused(
        self, store: StoryStore
    ) -> None:
        absorbed = await made(store, act("a"))
        target = await made(store, act("b"))
        await noted(store, absorbed, "Note.", on="a")
        read = await state_of(store, absorbed)
        await store.merge(absorbed, target, actor=_OWNER)
        before = await everything(store)
        summary = draft(line("Line."))
        unknown = await store.write_summary("story:nowhere", summary, as_of=read.as_of)
        summary_refused(unknown, StorySummaryRefusalReason.UNKNOWN_STORY)
        merged = await store.write_summary(absorbed, summary, as_of=read.as_of)
        summary_refused(merged, StorySummaryRefusalReason.MERGED_STORY)
        assert merged.refusal is not None
        assert merged.refusal.merged_into == target
        assert await everything(store) == before

    async def test_the_cap_binds_every_line_the_users_own_included(self, store: StoryStore) -> None:
        """ADR-0303 §4:5: a line the user's note gave counts like any other (§2:6)."""
        story_id = await made(store, act("a1"))
        long = "y" * STORY_NOTE_MAX_CHARS
        budget = STORY_SUMMARY_CAP_CHARS // STORY_NOTE_MAX_CHARS
        theirs = [
            await noted(store, story_id, f"{n}{long[1:]}", author=StoryNoteAuthor.OWNER)
            for n in range(budget + 1)
        ]
        read = await state_of(store, story_id)
        fits = [line(n.text) for n in theirs[:budget]]
        await written(store, story_id, draft(*fits), as_of=read.as_of)
        before = await everything(store)
        outcome = await store.write_summary(
            story_id,
            draft(*fits, line("z")),
            as_of=(await state_of(store, story_id)).as_of,
        )
        summary_refused(outcome, StorySummaryRefusalReason.OVER_CAP)
        verbatim = await store.write_summary(
            story_id,
            draft(*(line(n.text) for n in theirs)),
            as_of=(await state_of(store, story_id)).as_of,
        )
        summary_refused(verbatim, StorySummaryRefusalReason.OVER_CAP)
        assert await everything(store) == before

    @pytest.mark.parametrize("as_of", [-1, 2**63, True, "0", None])
    async def test_a_malformed_as_of_is_a_value_error(
        self, store: StoryStore, as_of: object
    ) -> None:
        story_id = await made(store, act("a1"))
        await noted(store, story_id, "Note.")
        with pytest.raises(ValueError, match="as_of"):
            await store.write_summary(
                story_id,
                draft(line("Line.")),
                as_of=as_of,  # type: ignore[arg-type]
            )

    async def test_an_as_of_no_read_returned_is_a_value_error(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        await noted(store, story_id, "Note.")
        read = await state_of(store, story_id)
        before = await everything(store)
        with pytest.raises(ValueError, match="as_of"):
            await store.write_summary(story_id, draft(line("Line.")), as_of=read.as_of + 1)
        assert await everything(store) == before

    async def test_a_draft_that_is_not_one_is_a_value_error(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        with pytest.raises(ValueError, match="StorySummaryDraft"):
            await store.write_summary(story_id, {"lines": []}, as_of=0)  # type: ignore[arg-type]

    # --- merge, split and move carry notes (ADR-0300 §3:12, ADR-0303 §6) ------

    async def test_a_merge_carries_every_note_pending_into_the_target(
        self, store: StoryStore
    ) -> None:
        absorbed = await made(store, act("x"), act("shared"))
        target = await made(store, act("shared"), act("t"))
        taken = await noted(store, absorbed, "Taken in on A.", on="x")
        theirs = await noted(store, absorbed, "The user's.", author=StoryNoteAuthor.OWNER)
        read = await state_of(store, absorbed)
        await written(
            store,
            absorbed,
            draft(line("A's summary."), took_in_notes=(taken.note_id,)),
            as_of=read.as_of,
        )
        target_read = await state_of(store, target)
        await written(
            store,
            target,
            draft(line("B's summary."), took_in_episodes=("shared", "t")),
            as_of=target_read.as_of,
        )
        await store.merge(absorbed, target, actor=_OWNER)
        state = await state_of(store, target)
        assert [n.note_id for n in state.pending_notes] == [taken.note_id, theirs.note_id]
        assert state.pending_episodes == ("x",)
        assert await notes_of(store, absorbed) == []
        assert (await state_of(store, absorbed)).pending_notes == ()
        assert (await state_of(store, absorbed)).pending_episodes == ()
        assert await notes_of(store, target) == [taken, theirs]

    async def test_a_split_carries_exactly_the_notes_it_names(self, store: StoryStore) -> None:
        """Whoever wrote them, and none by the activation it was written during (§6:1-§6:2)."""
        source = await made(store, act("x"), act("y"))
        on_x = await noted(store, source, "On x.", on="x")
        on_y = await noted(store, source, "On y.", on="y")
        named = await noted(store, source, "The user's, named.", author=StoryNoteAuthor.OWNER)
        kept = await noted(store, source, "The user's, kept.", author=StoryNoteAuthor.OWNER)
        elsewhere = await made(store, act("z"))
        foreign = await noted(
            store, elsewhere, "The user's, elsewhere.", author=StoryNoteAuthor.OWNER
        )
        read = await state_of(store, source)
        await written(
            store,
            source,
            draft(
                line("Summary."),
                took_in_notes=(on_x.note_id, on_y.note_id, named.note_id, kept.note_id),
                took_in_episodes=("x", "y"),
            ),
            as_of=read.as_of,
        )
        outcome = await store.split(
            source,
            [act("x")],
            actor=_OWNER,
            notes=[named.note_id, on_y.note_id, foreign.note_id, 999_999, on_y.note_id],
        )
        assert outcome.refusal is None
        assert outcome.logged == 5 + 4
        split_off = outcome.story_id
        assert split_off is not None
        assert carried(await logged(store, source)) == [
            (StoryChange.NOTE_MOVED_OUT, on_y.note_id, split_off),
            (StoryChange.NOTE_MOVED_OUT, named.note_id, split_off),
        ]
        assert carried(await logged(store, split_off)) == [
            (StoryChange.NOTE_MOVED_IN, on_y.note_id, source),
            (StoryChange.NOTE_MOVED_IN, named.note_id, source),
        ]
        assert await notes_of(store, split_off) == [on_y, named]
        assert await notes_of(store, source) == [on_x, kept]
        assert await notes_of(store, elsewhere) == [foreign]
        state = await state_of(store, split_off)
        assert state.pending_notes == (on_y, named)
        assert state.pending_episodes == ("x",)
        assert (await state_of(store, source)).pending_notes == ()

    async def test_a_split_naming_no_note_carries_none(self, store: StoryStore) -> None:
        source = await made(store, act("x"), act("y"))
        on_x = await noted(store, source, "On x.", on="x")
        outcome = await store.split(source, [act("x")], actor=_OWNER)
        assert outcome.story_id is not None
        assert outcome.logged == 5
        assert await notes_of(store, outcome.story_id) == []
        assert await notes_of(store, source) == [on_x]
        assert carried(await logged(store, source)) == []
        assert carried(await logged(store, outcome.story_id)) == []

    @pytest.mark.parametrize("notes", ["1", [0], [True], [1.0], 3])
    async def test_a_split_or_a_move_naming_malformed_notes_is_a_value_error(
        self, store: StoryStore, notes: object
    ) -> None:
        source = await made(store, act("x"))
        target = await made(store, act("t"))
        before = await everything(store)
        with pytest.raises(ValueError, match="note"):
            await store.split(source, [act("x")], actor=_OWNER, notes=notes)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="note"):
            await store.move(source, target, [act("x")], actor=_OWNER, notes=notes)  # type: ignore[arg-type]
        assert await everything(store) == before

    async def test_a_move_carries_members_and_exactly_the_notes_it_names(
        self, store: StoryStore
    ) -> None:
        """Whoever wrote them, and none by the activation it was written during (§6:1-§6:2)."""
        source = await made(store, act("x"), act("y"), act("both"))
        target = await made(store, act("both"), act("t"))
        on_x = await noted(store, source, "On x.", on="x")
        on_y = await noted(store, source, "On y.", on="y")
        on_both = await noted(store, source, "On both.", on="both")
        theirs = await noted(store, source, "The user's.", author=StoryNoteAuthor.OWNER)
        foreign = await noted(store, target, "Already there.", on="t")
        target_view = await store.view(target)
        assert target_view is not None
        outcome = await store.move(
            source,
            target,
            [act("both"), act("x")],
            actor=_OWNER,
            notes=[theirs.note_id, on_y.note_id, foreign.note_id, 999_999],
        )
        assert outcome.refusal is None
        assert outcome.story_id == target
        assert outcome.logged == 3 + 4
        assert await held(store, source) == [act("y")]
        assert await held(store, target) == [act("both"), act("t"), act("x")]
        after_view = await store.view(target)
        assert after_view is not None
        assert after_view.entries[0] == target_view.entries[0]
        assert shape(await logged(store, source))[-4:] == [
            (StoryChange.REMOVED, "x"),
            (StoryChange.REMOVED, "both"),
            (StoryChange.NOTE_MOVED_OUT, target),
            (StoryChange.NOTE_MOVED_OUT, target),
        ]
        assert shape(await logged(store, target))[-3:] == [
            (StoryChange.ADDED, "x"),
            (StoryChange.NOTE_MOVED_IN, source),
            (StoryChange.NOTE_MOVED_IN, source),
        ]
        assert carried(await logged(store, source)) == [
            (StoryChange.NOTE_MOVED_OUT, on_y.note_id, target),
            (StoryChange.NOTE_MOVED_OUT, theirs.note_id, target),
        ]
        assert await notes_of(store, source) == [on_x, on_both]
        assert await notes_of(store, target) == [on_y, theirs, foreign]
        state = await state_of(store, target)
        assert state.pending_notes == (on_y, theirs, foreign)
        assert state.pending_episodes == ("both", "t", "x")

    async def test_a_moved_note_is_pending_on_its_new_story_though_taken_in_on_the_old(
        self, store: StoryStore
    ) -> None:
        source = await made(store, act("x"))
        target = await made(store, act("t"))
        note = await noted(store, source, "On x.", on="x")
        read = await state_of(store, source)
        await written(
            store,
            source,
            draft(line("Summary."), took_in_notes=(note.note_id,)),
            as_of=read.as_of,
        )
        await store.move(source, target, [act("x")], actor=_OWNER, notes=[note.note_id])
        assert (await state_of(store, target)).pending_notes == (note,)

    async def test_a_move_records_its_actor_and_trigger(self, store: StoryStore) -> None:
        source = await made(store, act("x"))
        target = await made(store, act("t"))
        await store.move(source, target, [act("x")], actor=StoryActor.MATTERS_PASS, trigger="act-9")
        for story_id in (source, target):
            last = (await logged(store, story_id))[-1]
            assert last.actor is StoryActor.MATTERS_PASS
            assert last.trigger == "act-9"

    async def test_a_move_naming_a_non_member_is_refused(self, store: StoryStore) -> None:
        source = await made(store, act("x"))
        target = await made(store, act("t"))
        before = await everything(store)
        outcome = await store.move(source, target, [act("x"), act("nope")], actor=_OWNER)
        refused(outcome, StoryRefusalReason.NOT_A_MEMBER)
        assert outcome.refusal is not None
        assert outcome.refusal.member == act("nope")
        assert await everything(store) == before

    async def test_a_move_naming_no_member_and_no_note_is_refused(self, store: StoryStore) -> None:
        """ADR-0304 §9:2: ``no_members``, before the stories are looked at."""
        source = await made(store, act("x"))
        target = await made(store, act("t"))
        await noted(store, source, "On x.", on="x")
        before = await everything(store)
        refused(await store.move(source, target, [], actor=_OWNER), StoryRefusalReason.NO_MEMBERS)
        refused(await store.move(source, target, actor=_OWNER), StoryRefusalReason.NO_MEMBERS)
        refused(
            await store.move("story:nowhere", target, actor=_OWNER, notes=()),
            StoryRefusalReason.NO_MEMBERS,
        )
        assert await everything(store) == before

    async def test_a_move_to_or_from_an_unknown_or_merged_story_is_refused(
        self, store: StoryStore
    ) -> None:
        source = await made(store, act("x"))
        absorbed = await made(store, act("a"))
        target = await made(store, act("t"))
        await store.merge(absorbed, target, actor=_OWNER)
        before = await everything(store)
        for args, reason, about in [
            (("story:nowhere", target), StoryRefusalReason.UNKNOWN_STORY, "story:nowhere"),
            ((source, "story:nowhere"), StoryRefusalReason.UNKNOWN_STORY, "story:nowhere"),
            ((absorbed, source), StoryRefusalReason.MERGED_STORY, absorbed),
            ((source, absorbed), StoryRefusalReason.MERGED_STORY, absorbed),
        ]:
            outcome = await store.move(*args, [act("x")], actor=_OWNER)
            refused(outcome, reason)
            assert outcome.refusal is not None
            assert outcome.refusal.story_id == about
        assert await everything(store) == before

    async def test_a_move_of_a_story_member_or_to_itself_is_a_value_error(
        self, store: StoryStore
    ) -> None:
        inner = await made(store, act("i"))
        source = await made(store, act("x"), sub(inner))
        target = await made(store, act("t"))
        before = await everything(store)
        with pytest.raises(ValueError, match="activation"):
            await store.move(source, target, [sub(inner)], actor=_OWNER)
        with pytest.raises(ValueError, match="another"):
            await store.move(source, source, [act("x")], actor=_OWNER)
        assert await everything(store) == before

    # --- a note moves on its own (ADR-0304 §9) ---------------------------------

    async def test_a_note_move_carries_exactly_the_held_notes_it_names(
        self, store: StoryStore
    ) -> None:
        """§9:1, §9:6, §9:8: no member moves, and each note keeps every field of its own."""
        source = await made(store, act("x"), act("y"))
        target = await made(store, act("t"))
        elsewhere = await made(store, act("z"))
        on_x = await noted(store, source, "On x.", on="x", outside=True)
        theirs = await noted(store, source, "The user's.", author=StoryNoteAuthor.OWNER)
        on_y = await noted(store, source, "On y.", on="y")
        foreign = await noted(store, elsewhere, "Elsewhere.", on="z")
        read = await state_of(store, source)
        await written(
            store,
            source,
            draft(line("Summary."), took_in_notes=(on_x.note_id,), took_in_episodes=("x", "y")),
            as_of=read.as_of,
        )
        source_members = await held(store, source)
        target_members = await held(store, target)
        outcome = await store.move(
            source,
            target,
            actor=_PASS,
            trigger="act-7",
            notes=[on_y.note_id, on_x.note_id, foreign.note_id, 999_999, on_x.note_id],
        )
        assert outcome == StoryOutcome(story_id=target, logged=4)
        assert await held(store, source) == source_members
        assert await held(store, target) == target_members
        assert await notes_of(store, source) == [theirs]
        assert await notes_of(store, target) == [on_x, on_y]
        assert await notes_of(store, elsewhere) == [foreign]
        state = await state_of(store, target)
        assert state.pending_notes == (on_x, on_y)
        assert state.pending_episodes == ("t",)
        assert (await state_of(store, source)).pending_notes == (theirs,)
        source_lines = (await logged(store, source))[-2:]
        target_lines = (await logged(store, target))[-2:]
        assert carried(source_lines) == [
            (StoryChange.NOTE_MOVED_OUT, on_x.note_id, target),
            (StoryChange.NOTE_MOVED_OUT, on_y.note_id, target),
        ]
        assert carried(target_lines) == [
            (StoryChange.NOTE_MOVED_IN, on_x.note_id, source),
            (StoryChange.NOTE_MOVED_IN, on_y.note_id, source),
        ]
        for each in (*source_lines, *target_lines):
            assert each.member is None
            assert each.actor is _PASS
            assert each.trigger == "act-7"
            assert each.at == STORY_AT
            assert (each.answers, each.outcome) == (None, None)

    async def test_a_note_move_holding_none_of_its_notes_is_refused(
        self, store: StoryStore
    ) -> None:
        """§9:3: ``no_notes``, naming the story moved from, and nothing changes."""
        source = await made(store, act("x"))
        target = await made(store, act("t"))
        kept = await noted(store, source, "Stays.", on="x")
        foreign = await noted(store, target, "Already there.", on="t")
        before = await everything(store)
        for notes in ([foreign.note_id], [999_999], [foreign.note_id, 999_999]):
            outcome = await store.move(source, target, actor=_OWNER, notes=notes)
            refused(outcome, StoryRefusalReason.NO_NOTES)
            assert outcome.refusal is not None
            assert outcome.refusal.story_id == source
        assert await everything(store) == before
        assert await notes_of(store, source) == [kept]

    async def test_a_note_move_repeated_is_refused_and_changes_nothing(
        self, store: StoryStore
    ) -> None:
        """ADR-0304 §9: the first story no longer holds the notes, so a repeat is safe."""
        source = await made(store, act("x"))
        target = await made(store, act("t"))
        note = await noted(store, source, "Goes.", on="x")
        first = await store.move(source, target, actor=_PASS, notes=[note.note_id])
        assert first == StoryOutcome(story_id=target, logged=2)
        before = await everything(store)
        refused(
            await store.move(source, target, actor=_PASS, notes=[note.note_id]),
            StoryRefusalReason.NO_NOTES,
        )
        assert await everything(store) == before

    async def test_a_note_move_is_refused_for_its_stories_before_its_notes(
        self, store: StoryStore
    ) -> None:
        """§9:4: ``unknown_story`` or ``merged_story`` for either side, the first first."""
        source = await made(store, act("x"))
        absorbed = await made(store, act("a"))
        target = await made(store, act("t"))
        await store.merge(absorbed, target, actor=_OWNER)
        before = await everything(store)
        for args, reason, about in [
            (
                ("story:nowhere", "story:elsewhere"),
                StoryRefusalReason.UNKNOWN_STORY,
                "story:nowhere",
            ),
            ((source, "story:nowhere"), StoryRefusalReason.UNKNOWN_STORY, "story:nowhere"),
            ((absorbed, "story:nowhere"), StoryRefusalReason.MERGED_STORY, absorbed),
            ((source, absorbed), StoryRefusalReason.MERGED_STORY, absorbed),
        ]:
            outcome = await store.move(*args, actor=_OWNER, notes=[999_999])
            refused(outcome, reason)
            assert outcome.refusal is not None
            assert outcome.refusal.story_id == about
        assert await everything(store) == before

    async def test_a_note_move_answering_records_moved_after_its_lines(
        self, store: StoryStore
    ) -> None:
        """§9:4, ADR-0302 §4:2: the decision ``moved``, after the notes' lines."""
        other = await made(store, act("b1"))
        story_id = await made(store, act("a1"))
        flag = await raised(
            store, story_id, StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other)
        )
        (note,) = await notes_of(store, story_id)
        outcome = await store.move(story_id, other, actor=_PASS, notes=[note.note_id], answers=flag)
        assert outcome == StoryOutcome(story_id=other, logged=2 + 2)
        assert await held(store, story_id) == [act("a1")]
        assert await notes_of(store, other) == [note]
        for each, change in (
            (story_id, StoryChange.NOTE_MOVED_OUT),
            (other, StoryChange.NOTE_MOVED_IN),
        ):
            last_two = (await logged(store, each))[-2:]
            assert [line.change for line in last_two] == [change, StoryChange.DECIDED]
            assert last_two[1].outcome is StoryDecision.MOVED

    @pytest.mark.parametrize("named", ["elsewhere", "nowhere"])
    @pytest.mark.parametrize("operation", ["split", "move", "note_move"])
    async def test_a_planning_split_or_move_naming_a_note_not_held_is_refused_whole(
        self, store: StoryStore, operation: str, named: str
    ) -> None:
        """ADR-0307 §5:4: ``note_not_held``, naming the story moved from; nothing moves."""
        source = await made(store, act("x"), act("y"))
        target = await made(store, act("t"))
        kept = await noted(store, source, "Held.", on="x")
        foreign = await noted(store, target, "Elsewhere.", on="t")
        missing = foreign.note_id if named == "elsewhere" else 999_999
        before = await everything(store)
        notes = [kept.note_id, missing]
        stamp: dict[str, Any] = {"actor": StoryActor.PLANNING, "trigger": "act-7", "notes": notes}
        if operation == "split":
            outcome = await store.split(source, [act("x")], **stamp)
        elif operation == "move":
            outcome = await store.move(source, target, [act("x")], **stamp)
        else:
            outcome = await store.move(source, target, **stamp)
        refused(outcome, StoryRefusalReason.NOTE_NOT_HELD)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == source
        assert await everything(store) == before

    async def test_a_note_moved_away_meanwhile_refuses_a_planning_move_whole(
        self, store: StoryStore
    ) -> None:
        """ADR-0307 §5:4: held when the hub looked, moved by the matters pass since."""
        source = await made(store, act("x"), act("y"))
        target = await made(store, act("t"))
        elsewhere = await made(store, act("z"))
        first = await noted(store, source, "First.", on="x")
        second = await noted(store, source, "Second.", on="y")
        # What the hub's check reads: both notes are on the story moved from.
        assert await notes_of(store, source) == [first, second]
        await store.move(source, elsewhere, actor=_PASS, notes=[second.note_id])
        before = await everything(store)
        for outcome in (
            await store.move(
                source,
                target,
                [act("x")],
                actor=StoryActor.PLANNING,
                notes=[first.note_id, second.note_id],
            ),
            await store.split(
                source,
                [act("x")],
                actor=StoryActor.PLANNING,
                notes=[first.note_id, second.note_id],
            ),
        ):
            refused(outcome, StoryRefusalReason.NOTE_NOT_HELD)
        assert await everything(store) == before
        assert await held(store, source) == [act("x"), act("y")]
        assert await notes_of(store, source) == [first]

    @pytest.mark.parametrize(
        "actor", [StoryActor.OWNER, StoryActor.UNDERSTANDING, StoryActor.MATTERS_PASS]
    )
    async def test_every_other_actor_passes_a_note_not_held_over(
        self, store: StoryStore, actor: StoryActor
    ) -> None:
        """ADR-0303 §6:2: only planning's split or move is refused over such a note."""
        source = await made(store, act("x"), act("y"), act("w"))
        target = await made(store, act("t"))
        on_x = await noted(store, source, "On x.", on="x")
        on_y = await noted(store, source, "On y.", on="y")
        moved = await store.move(
            source, target, [act("x")], actor=actor, notes=[on_x.note_id, 999_999]
        )
        assert moved == StoryOutcome(story_id=target, logged=2 + 2)
        split = await store.split(source, [act("y")], actor=actor, notes=[on_y.note_id, 999_999])
        assert split.story_id is not None
        assert await notes_of(store, target) == [on_x]
        assert await notes_of(store, split.story_id) == [on_y]

    async def test_a_planning_move_holding_every_note_it_names_is_written(
        self, store: StoryStore
    ) -> None:
        """ADR-0307 §5:4: the refusal is over a note not held, never over naming one twice."""
        source = await made(store, act("x"), act("y"))
        target = await made(store, act("t"))
        note = await noted(store, source, "Goes.", on="y")
        outcome = await store.move(
            source,
            target,
            [act("x")],
            actor=StoryActor.PLANNING,
            trigger="act-7",
            notes=[note.note_id, note.note_id],
        )
        assert outcome == StoryOutcome(story_id=target, logged=2 + 2)
        assert await notes_of(store, target) == [note]

    async def test_note_not_held_comes_after_not_a_member_and_before_the_flag(
        self, store: StoryStore
    ) -> None:
        """The fixed order: the operation's own rule in its place, the flag after it."""
        other = await made(store, act("b1"))
        source = await made(store, act("a1"), act("a2"))
        flag = await raised(store, source, StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other))
        before = await everything(store)
        refused(
            await store.move(
                source, other, [act("nope")], actor=StoryActor.PLANNING, notes=[999_999]
            ),
            StoryRefusalReason.NOT_A_MEMBER,
        )
        refused(
            await store.split(source, [act("nope")], actor=StoryActor.PLANNING, notes=[999_999]),
            StoryRefusalReason.NOT_A_MEMBER,
        )
        assert flag.version is not None
        unknown = flag.model_copy(update={"version": flag.version + 1})
        for outcome in (
            await store.move(
                source,
                other,
                [act("a1")],
                actor=StoryActor.PLANNING,
                notes=[999_999],
                answers=unknown,
            ),
            await store.split(
                source, [act("a1")], actor=StoryActor.PLANNING, notes=[999_999], answers=unknown
            ),
            await store.move(
                source, other, actor=StoryActor.PLANNING, notes=[999_999], answers=unknown
            ),
        ):
            refused(outcome, StoryRefusalReason.NOTE_NOT_HELD)
        assert await everything(store) == before

    async def test_a_merge_logs_no_line_for_the_notes_it_carries(self, store: StoryStore) -> None:
        """ADR-0304 §9: a merge says the two stories are one matter, and every note goes."""
        absorbed = await made(store, act("x"))
        target = await made(store, act("t"))
        note = await noted(store, absorbed, "Goes with the merge.", on="x")
        outcome = await store.merge(absorbed, target, actor=_OWNER)
        assert outcome == StoryOutcome(story_id=target, logged=2 + 2)
        assert await notes_of(store, target) == [note]
        assert carried(await logged(store, absorbed)) == []
        assert carried(await logged(store, target)) == []

    async def test_an_unlink_leaves_the_notes_on_the_story(self, store: StoryStore) -> None:
        story_id = await made(store, act("x"), act("y"))
        note = await noted(store, story_id, "On x.", on="x")
        await store.unlink(story_id, [act("x")], actor=_OWNER)
        assert await notes_of(store, story_id) == [note]
        state = await state_of(store, story_id)
        assert state.pending_notes == (note,)
        assert state.pending_episodes == ("y",)

    # --- decisions on flags (ADR-0302 §§2-4) ---------------------------------

    async def test_leave_flag_records_left_on_the_story_that_raised_it(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"), act("a2"))
        flag = await raised(store, story_id, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
        members = await held(store, story_id)
        outcome = await store.leave_flag(flag, actor=_PASS)
        assert outcome == StoryOutcome(story_id=story_id, logged=1)
        last = (await logged(store, story_id))[-1]
        assert last.change is StoryChange.DECIDED
        assert last.answers == flag
        assert last.outcome is StoryDecision.LEFT
        assert last.actor is _PASS
        assert (last.member, last.other_story, last.trigger) == (None, None, None)
        assert last.at == STORY_AT
        assert await held(store, story_id) == members

    async def test_leave_flag_records_not_applied_where_a_change_was_refused(
        self, store: StoryStore
    ) -> None:
        """ADR-0303 §8:4-§8:6: no story changed, and the flag is answered as ``left`` is."""
        story_id = await made(store, act("a1"), act("a2"))
        flag = await raised(store, story_id, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
        members = await held(store, story_id)
        outcome = await store.leave_flag(flag, actor=_PASS, outcome=StoryDecision.NOT_APPLIED)
        assert outcome == StoryOutcome(story_id=story_id, logged=1)
        last = (await logged(store, story_id))[-1]
        assert (last.change, last.answers, last.outcome) == (
            StoryChange.DECIDED,
            flag,
            StoryDecision.NOT_APPLIED,
        )
        assert await held(store, story_id) == members
        again = await store.leave_flag(flag, actor=_PASS)
        refused(again, StoryRefusalReason.ALREADY_DECIDED)

    @pytest.mark.parametrize(
        "outcome",
        [
            StoryDecision.MERGED,
            StoryDecision.SPLIT,
            StoryDecision.MOVED,
            StoryDecision.GROUPED,
            "left_alone",
            None,
        ],
    )
    async def test_leave_flag_with_an_outcome_that_changes_a_story_is_a_value_error(
        self, store: StoryStore, outcome: object
    ) -> None:
        story_id = await made(store, act("a1"))
        flag = await raised(store, story_id, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
        before = await everything(store)
        with pytest.raises(ValueError):  # noqa: PT011 — any validation message will do
            await store.leave_flag(flag, actor=_PASS, outcome=outcome)  # type: ignore[arg-type]
        assert await everything(store) == before

    async def test_a_like_another_decision_is_written_on_both_stories_in_order(
        self, store: StoryStore
    ) -> None:
        other = await made(store, act("b1"))
        story_id = await made(store, act("a1"))
        flag = await raised(
            store, story_id, StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other)
        )
        outcome = await store.leave_flag(flag, actor=_PASS)
        assert outcome == StoryOutcome(story_id=story_id, logged=2)
        first = (await logged(store, story_id))[-1]
        second = (await logged(store, other))[-1]
        assert first.sequence < second.sequence
        assert [line.answers for line in (first, second)] == [flag, flag]
        assert {line.outcome for line in (first, second)} == {StoryDecision.LEFT}

    async def test_a_flag_named_by_an_activation_is_never_held(self, store: StoryStore) -> None:
        """ADR-0303 §8:1-§8:2: one input linked to two stories is two links, not a flag."""
        first = await linked_by_understanding(store, None, "a1")
        second = await linked_by_understanding(store, None, "a1")
        await linked_by_understanding(store, first, "a2")
        await linked_by_understanding(store, second, "a2")
        before = await everything(store)
        flag = StoryFlagName(activation="a1")
        for attempt in (
            store.leave_flag(flag, actor=_PASS),
            store.leave_flag(flag, actor=_PASS, outcome=StoryDecision.NOT_APPLIED),
            store.merge(first, second, actor=_PASS, answers=flag),
            store.move(first, second, [act("a2")], actor=_PASS, answers=flag),
            store.create(
                [sub(first), sub(second)], home=RecordHome.owners(), actor=_PASS, answers=flag
            ),
        ):
            outcome = await attempt
            refused(outcome, StoryRefusalReason.UNKNOWN_FLAG)
            assert outcome.refusal is not None
            assert outcome.refusal.flag == flag
        assert await everything(store) == before

    @pytest.mark.parametrize("wrong", ["version", "story", "kind", "named"])
    async def test_a_flag_no_version_recorded_is_unknown(
        self, store: StoryStore, wrong: str
    ) -> None:
        other = await made(store, act("b1"))
        third = await made(store, act("c1"))
        story_id = await made(store, act("a1"))
        recorded = StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other)
        flag = await raised(store, story_id, recorded)
        assert flag.version is not None
        named = {
            "version": flag.model_copy(update={"version": flag.version + 1}),
            "story": flag.model_copy(update={"story": other}),
            "kind": flag.model_copy(update={"flag": StoryFlag(kind=StoryFlagKind.TWO_MATTERS)}),
            "named": flag.model_copy(
                update={"flag": StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=third)}
            ),
        }[wrong]
        before = await everything(store)
        outcome = await store.leave_flag(named, actor=_PASS)
        refused(outcome, StoryRefusalReason.UNKNOWN_FLAG)
        assert outcome.refusal is not None
        assert outcome.refusal.flag == named
        assert await everything(store) == before

    async def test_a_flag_answered_once_is_refused_as_already_decided(
        self, store: StoryStore
    ) -> None:
        other = await made(store, act("b1"))
        story_id = await made(store, act("a1"))
        flag = await raised(
            store, story_id, StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other)
        )
        await store.leave_flag(flag, actor=_PASS)
        before = await everything(store)
        for attempt in (
            store.leave_flag(flag, actor=_PASS),
            store.merge(story_id, other, actor=_PASS, answers=flag),
            store.link(other, [sub(story_id)], actor=_PASS, answers=flag),
        ):
            outcome = await attempt
            refused(outcome, StoryRefusalReason.ALREADY_DECIDED)
            assert outcome.refusal is not None
            assert outcome.refusal.flag == flag
        assert await everything(store) == before

    async def test_a_flag_raised_in_a_later_version_is_another_flag(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        first = await raised(store, story_id, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
        await store.leave_flag(first, actor=_PASS)
        again = await raised(store, story_id, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
        assert again != first
        assert (await store.leave_flag(again, actor=_PASS)).refusal is None

    async def test_two_writers_cannot_both_answer_one_flag(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"), act("a2"))
        flag = await raised(store, story_id, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
        outcomes = await asyncio.gather(
            store.leave_flag(flag, actor=_PASS),
            store.split(story_id, [act("a2")], actor=_PASS, answers=flag),
        )
        reasons = sorted(
            "applied" if outcome.refusal is None else outcome.refusal.reason.value
            for outcome in outcomes
        )
        assert reasons == ["already_decided", "applied"]
        decided = [line for line in await logged(store, story_id) if line.answers == flag]
        assert len(decided) == 1

    async def test_a_merge_answering_records_merged_on_the_story_merged_into_only(
        self, store: StoryStore
    ) -> None:
        other = await made(store, act("b1"))
        story_id = await made(store, act("a1"))
        flag = await raised(
            store, story_id, StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other)
        )
        plain = max([(await logged(store, each))[-1].sequence for each in (story_id, other)])
        outcome = await store.merge(story_id, other, actor=_PASS, trigger="t-1", answers=flag)
        assert outcome.refusal is None
        merged = [line for line in await logged(store, other) if line.sequence > plain]
        assert [line.change for line in merged][-1] is StoryChange.DECIDED
        assert StoryChange.DECIDED not in [line.change for line in merged[:-1]]
        decision = merged[-1]
        assert (decision.answers, decision.outcome) == (flag, StoryDecision.MERGED)
        assert decision.actor is _PASS
        assert decision.trigger is None
        assert all(line.trigger == "t-1" for line in merged[:-1])
        assert outcome.logged == len(
            [line for line in await logged(store, story_id) if line.sequence > plain]
        ) + len(merged)
        assert StoryChange.DECIDED not in [line.change for line in await logged(store, story_id)]

    async def test_a_split_answering_records_split_after_its_own_lines(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"), act("a2"))
        flag = await raised(store, story_id, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
        outcome = await store.split(story_id, [act("a2")], actor=_PASS, answers=flag)
        assert outcome.story_id is not None
        assert outcome.logged == 3 + 2 + 1
        lines = await logged(store, story_id)
        assert lines[-1].change is StoryChange.DECIDED
        assert lines[-1].outcome is StoryDecision.SPLIT
        assert lines[-1].sequence > max(
            line.sequence for line in await logged(store, outcome.story_id)
        )
        assert StoryChange.DECIDED not in [
            line.change for line in await logged(store, outcome.story_id)
        ]

    async def test_a_move_answering_records_moved_on_both_stories(self, store: StoryStore) -> None:
        other = await made(store, act("b1"))
        story_id = await made(store, act("a1"), act("a2"))
        flag = await raised(
            store, story_id, StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other)
        )
        outcome = await store.move(story_id, other, [act("a2")], actor=_PASS, answers=flag)
        assert outcome == StoryOutcome(story_id=other, logged=2 + 2)
        for each in (story_id, other):
            last = (await logged(store, each))[-1]
            assert (last.change, last.outcome) == (StoryChange.DECIDED, StoryDecision.MOVED)

    @pytest.mark.parametrize("operation", ["create", "link"])
    async def test_a_grouping_answering_records_grouped(
        self, store: StoryStore, operation: str
    ) -> None:
        other = await made(store, act("b1"))
        story_id = await made(store, act("a1"))
        larger = await made(store, act("z"))
        flag = await raised(
            store, story_id, StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other)
        )
        members = [sub(story_id), sub(other)]
        if operation == "create":
            outcome = await store.create(
                members, home=RecordHome.owners(), actor=_PASS, answers=flag
            )
            assert outcome.logged == 1 + 2 + 2
        else:
            outcome = await store.link(larger, members, actor=_PASS, answers=flag)
            assert outcome == StoryOutcome(story_id=larger, logged=2 + 2)
        assert outcome.story_id is not None
        for each in (story_id, other):
            last = (await logged(store, each))[-1]
            assert (last.change, last.outcome) == (StoryChange.DECIDED, StoryDecision.GROUPED)
        assert StoryChange.DECIDED not in [
            line.change for line in await logged(store, outcome.story_id)
        ]

    @pytest.mark.parametrize("operation", ["create", "link"])
    async def test_a_grouping_answering_with_an_activation_member_is_a_value_error(
        self, store: StoryStore, operation: str
    ) -> None:
        story_id = await made(store, act("a1"))
        flag = await raised(store, story_id, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
        before = await everything(store)
        attempt = (
            store.create(
                [sub(story_id), act("a9")], home=RecordHome.owners(), actor=_PASS, answers=flag
            )
            if operation == "create"
            else store.link(story_id, [act("a9")], actor=_PASS, answers=flag)
        )
        with pytest.raises(ValueError, match="story members only"):
            await attempt
        assert await everything(store) == before

    async def test_a_decision_follows_merges_to_where_the_stories_now_stand(
        self, store: StoryStore
    ) -> None:
        other = await made(store, act("b1"))
        story_id = await made(store, act("a1"))
        into = await made(store, act("c1"))
        flag = await raised(
            store, story_id, StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other)
        )
        await store.merge(story_id, into, actor=_OWNER)
        await store.merge(into, other, actor=_OWNER)
        outcome = await store.leave_flag(flag, actor=_PASS)
        assert outcome == StoryOutcome(story_id=other, logged=1)
        for gone in (story_id, into):
            assert StoryChange.DECIDED not in [line.change for line in await logged(store, gone)]

    async def test_the_flag_is_checked_after_every_check_the_operation_makes(
        self, store: StoryStore
    ) -> None:
        inner = await made(store, act("i"))
        outer = await made(store, act("o"), sub(inner))
        target = await made(store, act("t"))
        deepest = await made(store, act("b"))
        holds_x = await made(store, sub(await made(store, sub(deepest))))
        unknown = StoryFlagName(activation="never-raised")
        note = await noted(store, target, "On t.", on="t")
        before = await everything(store)
        for attempt, reason in [
            (
                store.create([], home=RecordHome.owners(), actor=_PASS, answers=unknown),
                StoryRefusalReason.NO_MEMBERS,
            ),
            (
                store.move(target, outer, actor=_PASS, answers=unknown),
                StoryRefusalReason.NO_MEMBERS,
            ),
            (
                store.link("story:nowhere", [sub(inner)], actor=_PASS, answers=unknown),
                StoryRefusalReason.UNKNOWN_STORY,
            ),
            (
                store.link(inner, [sub(outer)], actor=_PASS, answers=unknown),
                StoryRefusalReason.LOOP,
            ),
            (
                store.merge(target, target, actor=_PASS, answers=unknown),
                StoryRefusalReason.SELF_MERGE,
            ),
            (
                store.merge(holds_x, deepest, actor=_PASS, answers=unknown),
                StoryRefusalReason.LOOP,
            ),
            (
                store.split(target, [act("nope")], actor=_PASS, answers=unknown),
                StoryRefusalReason.NOT_A_MEMBER,
            ),
            (
                store.move(target, outer, [act("nope")], actor=_PASS, answers=unknown),
                StoryRefusalReason.NOT_A_MEMBER,
            ),
            (
                store.move(target, outer, [act("t")], actor=_PASS, answers=unknown),
                StoryRefusalReason.UNKNOWN_FLAG,
            ),
            (
                store.move(target, outer, actor=_PASS, notes=[999_999], answers=unknown),
                StoryRefusalReason.NO_NOTES,
            ),
            (
                store.move(target, outer, actor=_PASS, notes=[note.note_id], answers=unknown),
                StoryRefusalReason.UNKNOWN_FLAG,
            ),
        ]:
            refused(await attempt, reason)
        assert await everything(store) == before

    async def test_a_change_refused_over_its_flag_writes_nothing_of_itself(
        self, store: StoryStore
    ) -> None:
        other = await made(store, act("b1"))
        story_id = await made(store, act("a1"), act("a2"))
        flag = await raised(
            store, story_id, StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other)
        )
        await store.leave_flag(flag, actor=_PASS)
        before = await everything(store)
        for attempt in (
            store.create(
                [sub(story_id), sub(other)], home=RecordHome.owners(), actor=_PASS, answers=flag
            ),
            store.link(other, [sub(story_id)], actor=_PASS, answers=flag),
            store.merge(story_id, other, actor=_PASS, answers=flag),
            store.split(story_id, [act("a2")], actor=_PASS, answers=flag),
            store.move(story_id, other, [act("a2")], actor=_PASS, answers=flag),
        ):
            refused(await attempt, StoryRefusalReason.ALREADY_DECIDED)
        assert await everything(store) == before

    async def test_a_change_its_own_rule_refuses_leaves_the_flag_open(
        self, store: StoryStore
    ) -> None:
        deepest = await made(store, act("b"))
        holds_x = await made(store, sub(await made(store, sub(deepest))))
        flag = await raised(
            store, holds_x, StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=deepest)
        )
        before = await everything(store)
        refused(
            await store.merge(holds_x, deepest, actor=_PASS, answers=flag),
            StoryRefusalReason.LOOP,
        )
        assert await everything(store) == before
        assert (await store.leave_flag(flag, actor=_PASS)).refusal is None

    async def test_a_malformed_flag_is_a_value_error(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        before = await everything(store)
        with pytest.raises(ValueError, match="StoryFlagName"):
            await store.leave_flag("a1", actor=_PASS)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="StoryFlagName"):
            await store.split(story_id, [act("a1")], actor=_PASS, answers="a1")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="actor"):
            await store.leave_flag(StoryFlagName(activation="a1"), actor=7)  # type: ignore[arg-type]
        assert await everything(store) == before

    # --- a summary write refuses what its story does not hold (ADR-0302 §7) --

    async def test_a_summary_built_before_a_split_took_its_episode_is_refused(
        self, store: StoryStore
    ) -> None:
        """#2761's probe: the split lands while the tidy-up's model call is out."""
        story_id = await made(store, act("a-1"), act("a-2"))
        note = await noted(store, story_id, "On a-1.", on="a-1")
        read = await state_of(store, story_id)
        await store.split(story_id, [act("a-2")], actor=_OWNER)
        before = await everything(store)
        outcome = await store.write_summary(
            story_id,
            draft(
                line("The matter."),
                took_in_notes=(note.note_id,),
                took_in_episodes=("a-1", "a-2"),
            ),
            as_of=read.as_of,
        )
        summary_refused(outcome, StorySummaryRefusalReason.NOT_HELD)
        assert outcome.refusal is not None
        assert (outcome.refusal.activation, outcome.refusal.note) == ("a-2", None)
        assert outcome.refusal.story_id == story_id
        assert await everything(store) == before

    async def test_an_episode_taken_in_that_a_move_took_away_is_refused(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"), act("a2"))
        other = await made(store, act("b1"))
        await noted(store, story_id, "On a1.")
        read = await state_of(store, story_id)
        await store.move(story_id, other, [act("a2")], actor=_OWNER)
        before = await everything(store)
        outcome = await store.write_summary(
            story_id,
            draft(line("The matter."), took_in_episodes=("a1", "a2")),
            as_of=read.as_of,
        )
        summary_refused(outcome, StorySummaryRefusalReason.NOT_HELD)
        assert outcome.refusal is not None
        assert outcome.refusal.activation == "a2"
        assert await everything(store) == before

    @pytest.mark.parametrize("where", ["moved", "elsewhere", "missing"])
    async def test_a_note_taken_in_that_the_story_does_not_hold_is_refused(
        self, store: StoryStore, where: str
    ) -> None:
        story_id = await made(store, act("a1"), act("a2"))
        other = await made(store, act("b1"))
        kept = await noted(store, story_id, "On a1.", on="a1")
        moving = await noted(store, story_id, "On a2.", on="a2")
        foreign = await noted(store, other, "Elsewhere.", on="b1")
        read = await state_of(store, story_id)
        if where == "moved":
            await store.move(story_id, other, [act("a2")], actor=_OWNER, notes=[moving.note_id])
        named = {
            "moved": moving.note_id,
            "elsewhere": foreign.note_id,
            "missing": foreign.note_id + 10_000,
        }[where]
        before = await everything(store)
        outcome = await store.write_summary(
            story_id,
            draft(line("The matter."), took_in_notes=(kept.note_id, named)),
            as_of=read.as_of,
        )
        summary_refused(outcome, StorySummaryRefusalReason.NOT_HELD)
        assert outcome.refusal is not None
        assert (outcome.refusal.note, outcome.refusal.activation) == (named, None)
        assert await everything(store) == before

    async def test_not_held_reports_the_first_in_the_drafts_order(self, store: StoryStore) -> None:
        """The episodes taken in, then the notes taken in."""
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Note.")
        read = await state_of(store, story_id)
        missing = note.note_id + 10_000
        cases: list[tuple[dict[str, Any], str | int]] = [
            ({"took_in_episodes": ("a1", "n3", "n4"), "took_in_notes": (missing,)}, "n3"),
            ({"took_in_episodes": ("a1",), "took_in_notes": (note.note_id, missing)}, missing),
        ]
        for rest, first in cases:
            outcome = await store.write_summary(
                story_id, draft(line("Line."), **rest), as_of=read.as_of
            )
            summary_refused(outcome, StorySummaryRefusalReason.NOT_HELD)
            assert outcome.refusal is not None
            assert first in (outcome.refusal.activation, outcome.refusal.note)

    async def test_not_held_comes_after_the_stories_a_draft_names_and_before_the_cap(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        read = await state_of(store, story_id)
        unheld: dict[str, Any] = {"took_in_episodes": ("n1",)}
        unknown_flag_story = await store.write_summary(
            story_id,
            draft(
                line("Line."),
                flags=(StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story="story:nowhere"),),
                read_pages=(StorySummaryVersionName(story="story:elsewhere", version=1),),
                **unheld,
            ),
            as_of=read.as_of,
        )
        summary_refused(unknown_flag_story, StorySummaryRefusalReason.UNKNOWN_STORY)
        assert unknown_flag_story.refusal is not None
        assert unknown_flag_story.refusal.story_id == "story:nowhere"
        unknown_read_story = await store.write_summary(
            story_id,
            draft(
                line("Line."),
                read_pages=(StorySummaryVersionName(story="story:elsewhere", version=1),),
                **unheld,
            ),
            as_of=read.as_of,
        )
        summary_refused(unknown_read_story, StorySummaryRefusalReason.UNKNOWN_STORY)
        budget = STORY_SUMMARY_CAP_CHARS // STORY_NOTE_MAX_CHARS
        over = [line("y" * STORY_NOTE_MAX_CHARS) for _ in range(budget + 1)]
        not_held = await store.write_summary(story_id, draft(*over, **unheld), as_of=read.as_of)
        summary_refused(not_held, StorySummaryRefusalReason.NOT_HELD)

    async def test_a_summary_resting_on_what_the_story_holds_but_took_in_is_written(
        self, store: StoryStore
    ) -> None:
        """A name held but no longer pending is still passed over (ADR-0302 §7:5)."""
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Note.")
        first = await state_of(store, story_id)
        await written(
            store,
            story_id,
            draft(line("Line."), took_in_notes=(note.note_id,)),
            as_of=first.as_of,
        )
        again = await state_of(store, story_id)
        version = await written(
            store,
            story_id,
            draft(
                line("Line."),
                took_in_notes=(note.note_id,),
                took_in_episodes=("a1",),
            ),
            as_of=again.as_of,
        )
        assert version.took_in_notes == ()
        assert version.took_in_episodes == ("a1",)

    # --- every summary is kept, and the store's position (ADR-0347 §2) ----------

    async def test_every_summary_is_kept_and_read_by_its_version_as_written(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        await noted(store, story_id, "Note.")
        first = await written(
            store,
            story_id,
            draft(line("Old line."), outside=True),
            as_of=(await state_of(store, story_id)).as_of,
        )
        empty = await written(
            store, story_id, draft(), as_of=(await state_of(store, story_id)).as_of
        )
        third = await written(
            store,
            story_id,
            draft(line("New line."), line("Another.")),
            as_of=(await state_of(store, story_id)).as_of,
        )
        kept = await store.summary_at(story_id, first.version)
        assert kept is not None
        assert (kept.version, kept.written_at, kept.lines, kept.outside) == (
            first.version,
            STORY_AT,
            (line("Old line."),),
            True,
        )
        nothing = await store.summary_at(story_id, empty.version)
        assert nothing is not None
        assert (nothing.lines, nothing.outside) == ((), False)
        current = (await state_of(store, story_id)).summary
        assert current is not None
        assert current.version == third.version
        assert await store.summary_at(story_id, third.version) == current
        # A kept summary never changes, whatever is written after it.
        assert await store.summary_at(story_id, first.version) == kept

    async def test_a_version_not_the_storys_reads_no_summary(self, store: StoryStore) -> None:
        one = await made(store, act("a1"))
        other = await made(store, act("b1"))
        note = await noted(store, one, "Note.")
        version = await written(
            store, one, draft(line("One.")), as_of=(await state_of(store, one)).as_of
        )
        assert await store.summary_at(other, version.version) is None
        assert await store.summary_at("story:nowhere", version.version) is None
        assert await store.summary_at(one, note.note_id) is None
        assert await store.summary_at(one, version.version + 1) is None
        assert await store.summary_at(other, 1) is None

    async def test_a_merged_storys_summaries_are_read_by_its_own_id(
        self, store: StoryStore
    ) -> None:
        absorbed = await made(store, act("a"))
        target = await made(store, act("b"))
        await noted(store, absorbed, "Note.", on="a")
        version = await written(
            store, absorbed, draft(line("Before.")), as_of=(await state_of(store, absorbed)).as_of
        )
        await store.merge(absorbed, target, actor=_OWNER)
        kept = await store.summary_at(absorbed, version.version)
        assert kept is not None
        assert kept.lines == (line("Before."),)
        assert await store.summary_at(target, version.version) is None

    @pytest.mark.parametrize("version", [0, -1, 2**63, True, 1.0, "1", None])
    async def test_a_malformed_version_or_id_is_a_value_error(
        self, store: StoryStore, version: object
    ) -> None:
        story_id = await made(store, act("a"))
        with pytest.raises(ValueError, match="version"):
            await store.summary_at(story_id, version)  # type: ignore[arg-type]
        with pytest.raises(ValueError):  # noqa: PT011 — any validation message will do
            await store.summary_at("  ", 1)

    async def test_the_position_starts_at_nothing_written(self, store: StoryStore) -> None:
        assert await store.position() == 0

    async def test_the_position_divides_the_versions_written_before_from_those_after(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        await noted(store, story_id, "Note.")
        before = await written(
            store, story_id, draft(line("Before.")), as_of=(await state_of(store, story_id)).as_of
        )
        position = await store.position()
        assert position >= before.version
        assert (await state_of(store, story_id)).as_of == position
        assert await store.position() == position
        after = await written(
            store, story_id, draft(line("After.")), as_of=(await state_of(store, story_id)).as_of
        )
        assert after.version > position
        assert await store.position() >= after.version
        # The latest version at or below the position read is the summary it stood at.
        versions = await versions_of(store, story_id)
        then = max(one.version for one in versions if one.version <= position)
        kept = await store.summary_at(story_id, then)
        assert kept is not None
        assert kept.lines == (line("Before."),)

    async def test_a_refused_summary_write_keeps_nothing_and_moves_no_position(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        await noted(store, story_id, "Note.")
        stale = await state_of(store, story_id)
        await written(store, story_id, draft(line("First.")), as_of=stale.as_of)
        before = await everything(store)
        refused_write = await store.write_summary(
            story_id, draft(line("Built on a stale read.")), as_of=stale.as_of
        )
        summary_refused(refused_write, StorySummaryRefusalReason.SUMMARY_MOVED_ON)
        assert await everything(store) == before

    # --- a store bound to a sight (ADR-0383 §7, §8, §9:3, §11) ---------------------

    @pytest.fixture
    def sight_store_factory(self) -> Callable[[SightMode], StoryStore]:
        """Override in a subclass: a fresh, empty store in a mode, its ids from a counter.

        Each call is a new store of its own, on the fixed clock the ``store`` fixture uses,
        whose story ids are drawn from a counter starting afresh, so two stores given one
        history mint the same ids; its bindings withhold or count as the mode says
        (ADR-0383 §7:10).
        """
        raise NotImplementedError

    @pytest.fixture
    def remove_stories(self) -> Callable[[StoryStore, Collection[str]], None]:
        """Override in a subclass: remove stories whole from a store the factory built.

        **A test-only door**, which the Protocol has none of: the stories named go with
        every member row, note, summary, version and log line of theirs (ADR-0383 §3:2),
        and nothing else moves, the store's one sequence and every number it issued
        included, so the store left is *the same store holding only* the rest (§9:3).
        A member row of a story kept that names a story removed is the kept story's and
        stays.
        """
        raise NotImplementedError

    @pytest.mark.parametrize("sight_name", list(SIGHTS))
    async def test_a_bound_store_answers_as_the_same_store_holding_only_what_its_sight_sees(
        self,
        sight_store_factory: Callable[[SightMode], StoryStore],
        remove_stories: Callable[[StoryStore, Collection[str]], None],
        sight_name: str,
    ) -> None:
        """§9:3's shared obligation, for every read member (§7:2, §8:1, §8:2, §8:5).

        Two stores take one history; from the second every story the sight does not see
        is removed whole, which leaves every number the rest carry as it is. The first,
        bound to the sight and withholding, answers every call in the battery as the
        second does: the same headers, pages walked to their end, notes, versions, kept
        summaries, lists and reverse look-ups, the position, and "not found" for a story
        it does not hold.
        """
        sight = SIGHTS[sight_name]
        bound_store = sight_store_factory(SightMode.WITHHOLD)
        holding_only = sight_store_factory(SightMode.WITHHOLD)
        names = await _sight_history(bound_store)
        assert await _sight_history(holding_only) == names
        battery = await _sight_battery(bound_store, names)
        unheld = [
            header.story_id
            for header in await _all_headers(holding_only)
            if not sight.sees(header.home)
        ]
        remove_stories(holding_only, unheld)
        await assert_answers_alike(bound_store.bound(sight), holding_only, battery)

    async def test_the_sights_hold_the_stories_six_says(
        self, sight_store_factory: Callable[[SightMode], StoryStore]
    ) -> None:
        """The obligation above has something to bite on: each sight's held stories.

        The owner's work holds every story; a run over the owner's domain the owner's;
        one over the shared things, and a work for no one, the shared things'; an
        unidentified sender's work and a producer with no facts, none, since no story is
        recorded as made by an activation (§6, §7:4).
        """
        store = sight_store_factory(SightMode.WITHHOLD)
        names = await _sight_history(store)
        owners = {names[name] for name in _OWNERS_STORIES}
        shared = {names[name] for name in _SHARED_STORIES}
        held = {
            name: {header.story_id for header in await _all_headers(store.bound(sight))}
            for name, sight in SIGHTS.items()
        }
        assert held == {
            "owners-work": owners | shared,
            "unidentified-senders-work": set(),
            "work-for-no-one": shared,
            "producer-with-no-facts": set(),
            "run-over-the-shared-things": shared,
            "run-over-the-owners-domain": owners,
        }

    async def test_a_write_naming_a_story_a_bound_store_does_not_hold_is_as_for_one_never_written(
        self, sight_store_factory: Callable[[SightMode], StoryStore]
    ) -> None:
        """§4:8, §7:5, §8:2: ``unknown_story`` wherever a write names a story not held.

        Written to or named as a member, on every write, and before ``another_home`` in
        the fixed order; nothing is written. The same writes on stories it holds land.
        """
        store = sight_store_factory(SightMode.WITHHOLD)
        names = await _sight_history(store)
        owners, shared, other = names["owners-one"], names["shared-one"], names["shared-two"]
        bound = store.bound(SIGHTS["run-over-the-shared-things"])
        before = await everything(store)
        for outcome in (
            await bound.link(owners, [act("x")], actor=_OWNER),
            await bound.link(shared, [sub(owners)], actor=_OWNER),
            await bound.create([sub(owners)], home=RecordHome.shared(), actor=_OWNER),
            await bound.unlink(owners, [act("a1")], actor=_OWNER),
            await bound.merge(owners, shared, actor=_OWNER),
            await bound.merge(shared, owners, actor=_OWNER),
            await bound.split(owners, [act("a1")], actor=_OWNER),
            await bound.move(owners, shared, [act("a1")], actor=_OWNER),
            await bound.move(shared, owners, [act("s1")], actor=_OWNER),
        ):
            refused(outcome, StoryRefusalReason.UNKNOWN_STORY)
            assert outcome.refusal is not None
            assert outcome.refusal.story_id == owners
        note = await bound.append_note(owners, "Note.", author=StoryNoteAuthor.OWNER)
        summary_refused(note, StorySummaryRefusalReason.UNKNOWN_STORY)
        as_of = await store.position()
        for written_to, summary in (
            (owners, draft(line("Line."))),
            (
                shared,
                draft(
                    line("Line."), flags=(StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=owners),)
                ),
            ),
            (
                shared,
                draft(
                    line("Line."),
                    read_pages=(
                        StorySummaryVersionName(
                            story=owners, version=_first_version(before, owners)
                        ),
                    ),
                ),
            ),
        ):
            summary_outcome = await bound.write_summary(written_to, summary, as_of=as_of)
            summary_refused(summary_outcome, StorySummaryRefusalReason.UNKNOWN_STORY)
            assert summary_outcome.refusal is not None
            assert summary_outcome.refusal.story_id == owners
        assert await everything(store) == before
        landed = await bound.link(shared, [sub(other)], actor=_OWNER)
        assert landed.refusal is None, landed

    async def test_another_home_is_answered_only_between_two_stories_a_bound_store_holds(
        self, sight_store_factory: Callable[[SightMode], StoryStore]
    ) -> None:
        """§4:7, §4:8: the owner's work sees both homes, so it is told ``another_home``."""
        store = sight_store_factory(SightMode.WITHHOLD)
        names = await _sight_history(store)
        owners, shared = names["owners-one"], names["shared-one"]
        refusal = await store.bound(SIGHTS["owners-work"]).link(owners, [sub(shared)], actor=_OWNER)
        refused(refusal, StoryRefusalReason.ANOTHER_HOME)
        assert refusal.refusal is not None
        assert refusal.refusal.story_id == shared
        hidden = await store.bound(SIGHTS["run-over-the-owners-domain"]).link(
            owners, [sub(shared)], actor=_OWNER
        )
        refused(hidden, StoryRefusalReason.UNKNOWN_STORY)
        assert hidden.refusal is not None
        assert hidden.refusal.story_id == shared

    async def test_a_flag_concerning_a_story_a_bound_store_does_not_hold_is_one_never_raised(
        self,
        sight_store_factory: Callable[[SightMode], StoryStore],
        set_story_home: Callable[[StoryStore, str, RecordHome], None],
    ) -> None:
        """§4:8, §7:5, §8:2: ``unknown_flag``, and no ``decided`` line written anywhere.

        A flag a story it holds raised naming a story it does not hold, and a flag a story
        it does not hold raised, are each answered as never raised, by ``leave_flag``
        and by a write given it as ``answers``, before ``another_home``. The first can be
        held only in a file written before §4:7's refusals, so the door stands for one;
        unbound, it is held, and refused ``another_home`` for its two homes.
        """
        store = sight_store_factory(SightMode.WITHHOLD)
        names = await _sight_history(store)
        owners, shared, other = names["owners-one"], names["shared-one"], names["shared-two"]
        lent = await homed(store, RecordHome.shared(), act("l1"))
        naming = await raised(store, shared, StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=lent))
        set_story_home(store, lent, RecordHome.owners())
        owners_flag = await raised(store, owners, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
        bound = store.bound(SIGHTS["run-over-the-shared-things"])
        before = await everything(store)
        for flag in (naming, owners_flag):
            refused(await bound.leave_flag(flag, actor=_PASS), StoryRefusalReason.UNKNOWN_FLAG)
            refused(
                await bound.link(shared, [sub(other)], actor=_PASS, answers=flag),
                StoryRefusalReason.UNKNOWN_FLAG,
            )
        assert await everything(store) == before
        unbound = await store.leave_flag(naming, actor=_PASS)
        refused(unbound, StoryRefusalReason.ANOTHER_HOME)
        assert unbound.refusal is not None
        assert unbound.refusal.story_id == lent

    async def test_a_flag_across_homes_is_another_home_only_between_stories_a_bound_store_holds(
        self, sight_store_factory: Callable[[SightMode], StoryStore]
    ) -> None:
        """§4:7, §4:8: the owner's work sees both homes, so it is told ``another_home``.

        For a decision on a flag of the shared things written from the owner's domain, and
        for a summary of the owner's naming a story of the shared things. A run over the
        owner's domain holds no story of the shared things, so it is told the flag was
        never raised and the story never written. Nothing is written.
        """
        store = sight_store_factory(SightMode.WITHHOLD)
        names = await _sight_history(store)
        owners, alike, spare = names["owners-one"], names["owners-split"], names["shared-two"]
        flag = await raised(store, spare, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
        across = draft(
            line("Line."), flags=(StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=spare),)
        )
        before = await everything(store)
        as_of = await store.position()
        cases = (
            (
                SIGHTS["owners-work"],
                StoryRefusalReason.ANOTHER_HOME,
                StorySummaryRefusalReason.ANOTHER_HOME,
            ),
            (
                SIGHTS["run-over-the-owners-domain"],
                StoryRefusalReason.UNKNOWN_FLAG,
                StorySummaryRefusalReason.UNKNOWN_STORY,
            ),
        )
        for sight, decision_reason, summary_reason in cases:
            bound = store.bound(sight)
            decision = await bound.link(owners, [sub(alike)], actor=_PASS, answers=flag)
            refused(decision, decision_reason)
            summary = await bound.write_summary(owners, across, as_of=as_of)
            summary_refused(summary, summary_reason)
            assert summary.refusal is not None
            assert summary.refusal.story_id == spare
        assert await everything(store) == before

    async def test_a_story_minted_in_a_home_the_sight_does_not_see_is_then_one_it_does_not_hold(
        self, sight_store_factory: Callable[[SightMode], StoryStore]
    ) -> None:
        """§4:1, §7:4, §7:5: a create mints in the home it is handed, then is not held.

        An unidentified sender's work writes into the owner's domain (§4:4) and reads
        nothing of it (§6's second case): its second call on the story it made answers
        as for a story never written.
        """
        store = sight_store_factory(SightMode.WITHHOLD)
        bound = store.bound(SIGHTS["unidentified-senders-work"])
        outcome = await bound.create([act("x")], home=RecordHome.owners(), actor=_OWNER)
        assert outcome.refusal is None, outcome
        assert outcome.story_id is not None
        assert await bound.header(outcome.story_id) is None
        refused(
            await bound.link(outcome.story_id, [act("y")], actor=_OWNER),
            StoryRefusalReason.UNKNOWN_STORY,
        )
        header = await store.header(outcome.story_id)
        assert header is not None
        assert header.home == RecordHome.owners()

    async def test_a_store_bound_in_the_counting_mode_answers_as_unbound_and_counts(
        self, sight_store_factory: Callable[[SightMode], StoryStore]
    ) -> None:
        """§7:10, §11:1 to §11:3: counting changes no answer and writes one event a read.

        Every call in the battery answers through a counting binding as the unbound store
        does, and no write is refused for the sight. A read's event carries the store,
        the member, how many stories it gave back, how many the sight would have withheld
        by reason, and the reader and bounds as codes, and nothing else: no id, no text.
        """
        store = sight_store_factory(SightMode.COUNT)
        names = await _sight_history(store)
        sight = SIGHTS["unidentified-senders-work"]
        battery = await _sight_battery(store, names)
        await assert_answers_alike(store.bound(sight), store, battery)
        with structlog.testing.capture_logs() as events:
            page = await store.bound(sight).stories(limit=MAX_STORY_PAGE)
        counted = [event for event in events if event["event"] == "sight_counted"]
        assert len(page.stories) == len(names)
        assert counted == [
            {
                "event": "sight_counted",
                "log_level": "info",
                "store": "stories",
                "member": "stories",
                "given": len(names),
                "other_home": 0,
                "no_home": 0,
                "sees_nothing": len(names),
                "reader": "work",
                "bounds": ["anyone", "person_owner"],
            }
        ]
        outcome = await store.bound(SIGHTS["run-over-the-shared-things"]).link(
            names["owners-one"], [act("x")], actor=_OWNER
        )
        assert outcome.refusal is None, outcome

    async def test_every_read_member_writes_one_count_event_when_counting(
        self, sight_store_factory: Callable[[SightMode], StoryStore]
    ) -> None:
        """§11:1: one event for each read, named by its member, of what it gave back.

        A read of one story counts that story, and a list each header; ``position``,
        a store-wide figure, counts none. The writes write none.
        """
        store = sight_store_factory(SightMode.COUNT)
        names = await _sight_history(store)
        bound = store.bound(SIGHTS["run-over-the-owners-domain"])
        shared = names["shared-one"]
        version = _first_version(await everything(store), shared)
        # Each call, the member it counts, how many stories it gave back, and how many
        # of them are of another home than the owner's domain the run tends.
        calls: list[tuple[str, Callable[[StoryStore], Awaitable[object]], int, int]] = [
            ("header", lambda s: s.header(shared), 1, 1),
            ("view", lambda s: s.view(shared), 1, 1),
            ("log", lambda s: s.log(shared), 1, 1),
            ("current_summary", lambda s: s.current_summary(shared), 1, 1),
            ("notes", lambda s: s.notes(shared), 1, 1),
            ("summary_versions", lambda s: s.summary_versions(shared), 1, 1),
            ("summary_at", lambda s: s.summary_at(shared, version), 1, 1),
            ("stories", lambda s: s.stories(limit=MAX_STORY_PAGE), 6, 3),
            ("stories_of", lambda s: s.stories_of(act("a1")), 2, 1),
            ("export", lambda s: s.export(), 6, 3),
            ("position", lambda s: s.position(), 0, 0),
            ("header", lambda s: s.header("story:never"), 0, 0),
        ]
        for member, call, given, other_home in calls:
            with structlog.testing.capture_logs() as events:
                await call(bound)
            counted = [event for event in events if event["event"] == "sight_counted"]
            assert [
                (event["member"], event["given"], event["other_home"]) for event in counted
            ] == [(member, given, other_home)], member
            assert counted[0]["no_home"] == counted[0]["sees_nothing"] == 0
            assert counted[0]["bounds"] == ["domain", "person_owner"]
            assert counted[0]["reader"] == "run"
        with structlog.testing.capture_logs() as events:
            await bound.link(shared, [act("later")], actor=_OWNER)
            await bound.append_note(shared, "Later.", author=StoryNoteAuthor.OWNER)
        assert not [event for event in events if event["event"] == "sight_counted"]

    async def test_a_store_bound_twice_is_bound_to_the_meet_of_the_two_sights(
        self, sight_store_factory: Callable[[SightMode], StoryStore]
    ) -> None:
        """§6:6, §7:1: binding again never widens; two sights that do not meet are refused."""
        store = sight_store_factory(SightMode.WITHHOLD)
        await _sight_history(store)
        owners = SIGHTS["owners-work"]
        twice = store.bound(owners).bound(SIGHTS["unidentified-senders-work"])
        assert await _all_headers(twice) == []
        with pytest.raises(ValueError, match="meet"):
            store.bound(owners).bound(SIGHTS["run-over-the-shared-things"])

    async def test_a_bound_store_reads_what_the_unbound_store_writes_after_binding(
        self, sight_store_factory: Callable[[SightMode], StoryStore]
    ) -> None:
        """§7:1: a binding is over the store's own records, not a copy of them."""
        store = sight_store_factory(SightMode.WITHHOLD)
        bound = store.bound(SIGHTS["run-over-the-shared-things"])
        later = await homed(store, RecordHome.shared(), act("later"))
        assert await bound.header(later) is not None
        merged = await homed(store, RecordHome.shared(), act("merged"))
        assert (await bound.merge(merged, later, actor=_OWNER)).refusal is None
        header = await store.header(merged)
        assert header is not None
        assert header.merged_into == later
        assert await store.position() == await bound.position()

    # --- a store bound to the owner's sight (ADR-0385 §3:3 to §3:5) ----------------

    @pytest.mark.parametrize("mode", list(SightMode))
    @pytest.mark.parametrize("act_name", list(_OWNERS_ACTS))
    async def test_the_owners_sight_is_withheld_for_in_either_mode_and_counts_nothing(
        self,
        sight_store_factory: Callable[[SightMode], StoryStore],
        remove_stories: Callable[[StoryStore, Collection[str]], None],
        act_name: str,
        mode: SightMode,
    ) -> None:
        """ADR-0385 §3:5: bound to the owner's sight, a store withholds in either mode.

        §9:3's obligation, with the bound store built in ``mode``: it answers every call
        in the battery as the same store holding only what the owner's sight sees, in
        the counting build too, and writes no ``sight_counted`` event (ADR-0383 §11:1).
        """
        sight = _OWNERS_ACTS[act_name]
        bound_store = sight_store_factory(mode)
        holding_only = sight_store_factory(SightMode.WITHHOLD)
        names = await _sight_history(bound_store)
        assert await _sight_history(holding_only) == names
        battery = await _sight_battery(bound_store, names)
        unheld = [
            header.story_id
            for header in await _all_headers(holding_only)
            if not sight.sees(header.home)
        ]
        remove_stories(holding_only, unheld)
        with structlog.testing.capture_logs() as events:
            await assert_answers_alike(bound_store.bound(sight), holding_only, battery)
        assert not [event for event in events if event["event"] == "sight_counted"]

    @pytest.mark.parametrize("mode", list(SightMode))
    async def test_the_owners_sight_holds_the_domain_it_names_and_from_none_both(
        self, sight_store_factory: Callable[[SightMode], StoryStore], mode: SightMode
    ) -> None:
        """ADR-0385 §3:3, §3:4: from none both homes; from a domain that domain alone."""
        store = sight_store_factory(mode)
        names = await _sight_history(store)
        owners = {names[name] for name in _OWNERS_STORIES}
        shared = {names[name] for name in _SHARED_STORIES}
        held = {
            name: {header.story_id for header in await _all_headers(store.bound(sight))}
            for name, sight in _OWNERS_ACTS.items()
        }
        assert held == {
            "from-none": owners | shared,
            "from-the-owners-domain": owners,
            "from-the-shared-things": shared,
        }

    @pytest.mark.parametrize("mode", list(SightMode))
    async def test_the_owners_sight_refuses_a_write_naming_a_story_it_does_not_see(
        self, sight_store_factory: Callable[[SightMode], StoryStore], mode: SightMode
    ) -> None:
        """ADR-0383 §4:8, §7:5, §8:2 for the owner's sight, in either mode.

        A write to a story of the domain the act did not name, or naming one as a
        member, is refused ``unknown_story`` as for one never written, and nothing is
        written.
        """
        store = sight_store_factory(mode)
        names = await _sight_history(store)
        owners, shared = names["owners-one"], names["shared-one"]
        before = await everything(store)
        for act_name, unseen, seen in (
            ("from-the-shared-things", owners, shared),
            ("from-the-owners-domain", shared, owners),
        ):
            bound = store.bound(_OWNERS_ACTS[act_name])
            for outcome in (
                await bound.link(unseen, [act("x")], actor=_OWNER),
                await bound.link(seen, [sub(unseen)], actor=_OWNER),
            ):
                refused(outcome, StoryRefusalReason.UNKNOWN_STORY)
                assert outcome.refusal is not None
                assert outcome.refusal.story_id == unseen
            note = await bound.append_note(unseen, "Note.", author=StoryNoteAuthor.OWNER)
            summary_refused(note, StorySummaryRefusalReason.UNKNOWN_STORY)
            assert await bound.header(unseen) is None
        assert await everything(store) == before

    async def test_a_counting_store_bound_to_a_runs_sight_still_counts(
        self, sight_store_factory: Callable[[SightMode], StoryStore]
    ) -> None:
        """ADR-0383 §7:10, §11:1 stand for every other reader of a store built to count.

        Bound to the owner's sight, the store withholds and counts nothing; the same
        store bound to a run's sight answers as unbound and counts, as before.
        """
        store = sight_store_factory(SightMode.COUNT)
        names = await _sight_history(store)
        owners = names["owners-one"]
        with structlog.testing.capture_logs() as events:
            withheld = await store.bound(_OWNERS_ACTS["from-the-shared-things"]).header(owners)
            counted_read = await store.bound(SIGHTS["run-over-the-shared-things"]).header(owners)
        counted = [event for event in events if event["event"] == "sight_counted"]
        assert withheld is None
        assert counted_read is not None
        assert [(event["member"], event["reader"], event["other_home"]) for event in counted] == [
            ("header", "run", 1)
        ]

    # --- the export (ADR-0385 §6:4, §6:5, §11; ADR-0383 §3:2, §8:5) ----------------

    async def test_an_empty_store_exports_no_story(self, store: StoryStore) -> None:
        """§6:7's empty domain, at the store: unbound and through every binding, no story."""
        assert await store.export() == StoryExport()
        for sight in (*SIGHTS.values(), *_OWNERS_ACTS.values()):
            assert await store.bound(sight).export() == StoryExport()

    async def test_the_export_holds_every_story_whole_as_its_reads_give_it(
        self, sight_store_factory: Callable[[SightMode], StoryStore]
    ) -> None:
        """§11: every story with each part that takes its home, as the store's reads give it.

        Unbound, every story the store lists, newest first, a merged one included, each
        with its header, its members, log lines, notes, versions and kept summaries walked
        whole; and through every binding, the stories that binding's own reads give back,
        each as they give it (ADR-0383 §12:2).
        """
        store = sight_store_factory(SightMode.WITHHOLD)
        names = await _sight_history(store)
        exported = await store.export()
        assert [one.story.story_id for one in exported.stories] == [
            header.story_id for header in await _all_headers(store)
        ]
        assert {one.story.story_id for one in exported.stories} == set(names.values())
        assert exported == await _export_from_reads(store)
        standing = [one for one in exported.stories if one.story.merged_into is None]
        assert all(one.members and one.log for one in standing)
        assert any(one.notes for one in exported.stories)
        assert any(one.versions and one.summaries for one in exported.stories)
        for sight in (*SIGHTS.values(), *_OWNERS_ACTS.values()):
            bound = store.bound(sight)
            assert await bound.export() == await _export_from_reads(bound)

    async def test_a_merged_story_is_exported_as_its_reads_leave_it(
        self, store: StoryStore
    ) -> None:
        """ADR-0289 §3, ADR-0300 §3, ADR-0347 §2:4: a merged story is still a story.

        It is carried with its header naming the story it was merged into, no members,
        its own log lines, and its own versions and kept summaries as it was left; its
        notes are carried once, on the story merged into, which holds them now.
        """
        absorbed = await made(store, act("a1"))
        target = await made(store, act("a2"))
        note = await noted(store, absorbed, "A note.")
        as_of = (await state_of(store, absorbed)).as_of
        version = await written(store, absorbed, draft(line("Its matter.")), as_of=as_of)
        merged = await store.merge(absorbed, target, actor=_OWNER)
        assert merged.refusal is None, merged
        exported = {one.story.story_id: one for one in (await store.export()).stories}
        assert set(exported) == {absorbed, target}
        gone = exported[absorbed]
        assert gone.story.merged_into == target
        assert gone.members == ()
        assert gone.notes == ()
        assert list(gone.log) == await logged(store, absorbed)
        assert (StoryChange.MERGED_INTO, target) in shape(list(gone.log))
        assert gone.versions == (version,)
        assert gone.summaries == (await store.summary_at(absorbed, version.version),)
        assert exported[target].notes == (note,)
        assert [entry.member for entry in exported[target].members] == [act("a2"), act("a1")]

    @pytest.mark.parametrize("mode", list(SightMode))
    async def test_bound_to_the_owners_sight_the_export_holds_the_domain_it_names_alone(
        self, sight_store_factory: Callable[[SightMode], StoryStore], mode: SightMode
    ) -> None:
        """ADR-0385 §3:3, §3:5, §6:4: from the owner's domain nothing of the shared things.

        And from the shared things nothing of the owner's domain, from none both, in either
        build mode, with no count event. No story the export carries names, as a member,
        a log line's other story, a flag, a decision or a summary version read, a story it
        does not carry (ADR-0383 §8:3).
        """
        store = sight_store_factory(mode)
        names = await _sight_history(store)
        owners = {names[name] for name in _OWNERS_STORIES}
        shared = {names[name] for name in _SHARED_STORIES}
        expected = {
            "from-none": owners | shared,
            "from-the-owners-domain": owners,
            "from-the-shared-things": shared,
        }
        for act_name, sight in _OWNERS_ACTS.items():
            with structlog.testing.capture_logs() as events:
                exported = await store.bound(sight).export()
            carried = {one.story.story_id for one in exported.stories}
            assert carried == expected[act_name], act_name
            assert all(sight.sees(one.story.home) for one in exported.stories)
            assert _named_stories(exported) <= carried, act_name
            assert not [event for event in events if event["event"] == "sight_counted"]

    async def test_the_export_carries_nothing_store_wide(
        self, sight_store_factory: Callable[[SightMode], StoryStore]
    ) -> None:
        """ADR-0383 §8:5, ADR-0385 §11: no position, no reading's ``as_of``, no count.

        Two stores hold one history, and the second takes further writes on a story of the
        shared things alone, so its position stands elsewhere: bound to the owner's sight
        from the owner's domain, the two export alike.
        """
        assert set(StoryExport.model_fields) == {"stories"}
        assert set(ExportedStory.model_fields) == {
            "story",
            "members",
            "log",
            "notes",
            "versions",
            "summaries",
        }
        quiet = sight_store_factory(SightMode.WITHHOLD)
        busy = sight_store_factory(SightMode.WITHHOLD)
        names = await _sight_history(quiet)
        assert await _sight_history(busy) == names
        shared = names["shared-two"]
        await noted(busy, shared, "Later.", on="s2")
        as_of = (await state_of(busy, shared)).as_of
        await written(busy, shared, draft(line("Later.")), as_of=as_of)
        assert await busy.position() > await quiet.position()
        sight = _OWNERS_ACTS["from-the-owners-domain"]
        assert await busy.bound(sight).export() == await quiet.bound(sight).export()
        assert await busy.export() != await quiet.export()

    async def test_the_export_round_trips_through_its_model(
        self, sight_store_factory: Callable[[SightMode], StoryStore]
    ) -> None:
        """ADR-0385 §6:8: a frozen pydantic model, whole again from its JSON."""
        store = sight_store_factory(SightMode.WITHHOLD)
        await _sight_history(store)
        exported = await store.export()
        assert exported.stories
        assert StoryExport.model_validate_json(exported.model_dump_json()) == exported
        assert StoryExport.model_validate(exported.model_dump()) == exported
        with pytest.raises(ValidationError):
            exported.stories = ()


#: The stories :func:`_sight_history` writes, by name, in each home.
_OWNERS_STORIES = ("owners-one", "owners-two", "owners-split")
_SHARED_STORIES = ("shared-one", "shared-two", "shared-merged")


async def _sight_history(store: StoryStore) -> dict[str, str]:
    """Write one history of stories of both homes into ``store``, by the unbound doors.

    Members of each kind, an activation in a story of each home, notes, summaries
    raising flags and replaced, a decided flag, a merge, a split carrying a note and a
    move, so every read member has records of both homes to give back. Returns each
    story's id by name.
    """
    names: dict[str, str] = {}
    names["owners-one"] = await homed(store, RecordHome.owners(), act("a1"), act("a2"))
    names["shared-one"] = await homed(store, RecordHome.shared(), act("s1"), act("a1"))
    names["owners-two"] = await homed(
        store, RecordHome.owners(), sub(names["owners-one"]), act("a3")
    )
    names["shared-two"] = await homed(store, RecordHome.shared(), act("s2"))
    names["shared-merged"] = await homed(store, RecordHome.shared(), act("s3"))
    owners_note = await noted(store, names["owners-one"], "An owner's note.", on="a2")
    await noted(store, names["shared-one"], "A shared note.", on="s1")
    read = await state_of(store, names["owners-one"])
    await written(
        store,
        names["owners-one"],
        draft(
            line("The owner's matter."),
            took_in_notes=(owners_note.note_id,),
            took_in_episodes=("a1",),
            flags=(StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=names["owners-two"]),),
        ),
        as_of=read.as_of,
    )
    read = await state_of(store, names["shared-one"])
    shared_version = await written(
        store,
        names["shared-one"],
        draft(line("The shared matter."), flags=(StoryFlag(kind=StoryFlagKind.TWO_MATTERS),)),
        as_of=read.as_of,
    )
    read = await state_of(store, names["owners-one"])
    await written(store, names["owners-one"], draft(line("Again.")), as_of=read.as_of)
    merged = await store.merge(names["shared-merged"], names["shared-two"], actor=_OWNER)
    assert merged.refusal is None, merged
    split = await store.split(
        names["owners-one"],
        [act("a2")],
        actor=_OWNER,
        notes=(owners_note.note_id,),
    )
    assert split.story_id is not None, split
    names["owners-split"] = split.story_id
    moved = await store.move(names["shared-one"], names["shared-two"], [act("s1")], actor=_OWNER)
    assert moved.refusal is None, moved
    decided = await store.leave_flag(
        StoryFlagName(
            story=names["shared-one"],
            version=shared_version.version,
            flag=StoryFlag(kind=StoryFlagKind.TWO_MATTERS),
        ),
        actor=_PASS,
    )
    assert decided.refusal is None, decided
    await noted(store, names["owners-two"], "A later owner's note.", on="a3")
    return names


async def _all_headers(store: StoryStore) -> list[StoryHeader]:
    """Every story ``store`` lists, newest first, walking its pages one story at a time."""
    headers: list[StoryHeader] = []
    cursor: int | None = None
    while True:
        page = await store.stories(cursor=cursor, limit=1)
        headers.extend(page.stories)
        if page.next_cursor is None:
            return headers
        cursor = page.next_cursor


def _pages_of(
    read: Callable[..., Awaitable[Any]], story_id: str
) -> Callable[[int | None], Awaitable[Any]]:
    """A paged read of one story, two items a page, for :func:`_walked`."""
    return lambda cursor: read(story_id, cursor=cursor, limit=2)


async def _export_from_reads(store: StoryStore) -> StoryExport:
    """What ``store``'s export must be: every story it lists, each part read whole.

    The stories newest first, as :func:`_all_headers` lists them; each with its view's
    entries, its log lines, its notes and its versions, every page walked, and the kept
    summary of each of its versions that has one, by ``summary_at`` (ADR-0385 §11).
    """
    stories: list[ExportedStory] = []
    for header in await _all_headers(store):
        story_id = header.story_id
        views = await _walked(_pages_of(store.view, story_id))
        logs = await _walked(_pages_of(store.log, story_id))
        notes = await _walked(_pages_of(store.notes, story_id))
        versions = await _walked(_pages_of(store.summary_versions, story_id))
        written = [version for page in versions for version in page.versions]
        kept = [await store.summary_at(story_id, version.version) for version in written]
        stories.append(
            ExportedStory(
                story=header,
                members=tuple(entry for page in views for entry in page.entries),
                log=tuple(one for page in logs for one in page.lines),
                notes=tuple(note for page in notes for note in page.notes),
                versions=tuple(written),
                summaries=tuple(summary for summary in kept if summary is not None),
            )
        )
    return StoryExport(stories=tuple(stories))


def _named_stories(exported: StoryExport) -> set[str]:
    """Every story any part of ``exported`` names: a member, a line, a flag, a read."""
    named: set[str] = set()
    for one in exported.stories:
        members = [entry.member for entry in one.members]
        members += [entry.member for entry in one.log if entry.member is not None]
        named |= {member.id for member in members if member.kind is StoryMemberKind.STORY}
        for entry in one.log:
            if entry.other_story is not None:
                named.add(entry.other_story)
            flag = entry.answers
            if flag is not None and flag.story is not None:
                named.add(flag.story)
            if flag is not None and flag.flag is not None and flag.flag.story is not None:
                named.add(flag.flag.story)
        for version in one.versions:
            named |= {read.story for read in version.read_pages}
            named |= {flag.story for flag in version.flags if flag.story is not None}
    return named


def _first_version(state: tuple[Any, ...], story_id: str) -> int:
    """The first summary version :func:`everything` read off ``story_id``'s version log."""
    for item in state:
        if isinstance(item, StorySummaryVersionList) and item.story.story_id == story_id:
            return item.versions[0].version
    msg = f"no version log of {story_id!r} was read"
    raise AssertionError(msg)


async def _walked(read: Callable[[int | None], Awaitable[Any]]) -> list[Any]:
    """Every page a paged read gives, from the first to the one that says none follows."""
    pages: list[Any] = []
    cursor: int | None = None
    while True:
        page = await read(cursor)
        pages.append(page)
        if page is None or page.next_cursor is None:
            return pages
        cursor = page.next_cursor


def _on(member: str, *args: Any, **kwargs: Any) -> Callable[[StoryStore], Awaitable[object]]:
    """A call of ``member`` with these arguments, made on whichever store it is given."""

    def call(store: StoryStore) -> Awaitable[object]:
        return cast("Awaitable[object]", getattr(store, member)(*args, **kwargs))

    return call


def _walk(member: str, *args: Any, limit: int) -> Callable[[StoryStore], Awaitable[object]]:
    """A paged read of ``member`` walked to its end, ``limit`` items a page."""

    def call(store: StoryStore) -> Awaitable[object]:
        read = getattr(store, member)
        return _walked(lambda cursor: read(*args, cursor=cursor, limit=limit))

    return call


async def _sight_battery(store: StoryStore, names: dict[str, str]) -> list[ReadCall[StoryStore]]:
    """Every read member, with the arguments that reach its pages, order and "not found".

    Read off ``store`` unbound: each story's paged reads walked one item a page, its
    current summary, and every kept summary by every version any story wrote; every
    list walked, one story a page and whole; the reverse look-up of every member; a
    story never written; the position; and the export (ADR-0385 §11).
    """
    stories = [*names.values(), "story:never"]
    versions = sorted(
        {
            version.version
            for story_id in names.values()
            for version in await versions_of(store, story_id)
        }
    )
    calls: list[ReadCall[StoryStore]] = []
    for story_id in stories:
        calls += [
            ReadCall(f"header({story_id})", _on("header", story_id)),
            ReadCall(f"view({story_id}) walked", _walk("view", story_id, limit=1)),
            ReadCall(f"log({story_id}) walked", _walk("log", story_id, limit=2)),
            ReadCall(f"current_summary({story_id})", _on("current_summary", story_id)),
            ReadCall(f"notes({story_id}) walked", _walk("notes", story_id, limit=1)),
            ReadCall(
                f"summary_versions({story_id}) walked",
                _walk("summary_versions", story_id, limit=1),
            ),
        ]
        calls += [
            ReadCall(f"summary_at({story_id}, {version})", _on("summary_at", story_id, version))
            for version in versions
        ]
    members = [act(one) for one in ("a1", "a2", "a3", "s1", "s2", "s3", "x")]
    members += [sub(story_id) for story_id in stories]
    calls += [ReadCall(f"stories_of({member.id})", _on("stories_of", member)) for member in members]
    calls += [
        ReadCall("stories() walked", _walk("stories", limit=1)),
        ReadCall("stories(limit=2) walked", _walk("stories", limit=2)),
        ReadCall("stories(whole)", _on("stories", limit=MAX_STORY_PAGE)),
        ReadCall("position()", _on("position")),
        ReadCall("export()", _on("export")),
    ]
    return calls
