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

And ADR-0300 §3's page: notes, immutable and never removed; the current page and
its version log; pending, including what becomes pending while a run is out and what
a merge, a split or a move brings; the page write refused when the version it was
built on is no longer current, writing nothing; the move; the notes merge, split
and move carry; and the actors §3:15 adds.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    STORY_ID_PREFIX,
    STORY_NOTE_MAX_CHARS,
    STORY_PAGE_CAP_CHARS,
    StoryActor,
    StoryChange,
    StoryDraftLine,
    StoryFlag,
    StoryFlagKind,
    StoryLogLine,
    StoryMember,
    StoryMemberKind,
    StoryNote,
    StoryNoteAuthor,
    StoryNoteOutcome,
    StoryOutcome,
    StoryPageDraft,
    StoryPageLine,
    StoryPageOutcome,
    StoryPageRefusalReason,
    StoryPageState,
    StoryPageVersion,
    StoryRefusalReason,
    StorySafetyNetNote,
    StorySupersession,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import StoryStore

#: The instant every subject's clock reads.
STORY_AT = datetime(2026, 10, 4, 12, tzinfo=UTC)

_OWNER = StoryActor.OWNER


def act(activation_id: str) -> StoryMember:
    """An activation member."""
    return StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)


def sub(story_id: str) -> StoryMember:
    """A story member."""
    return StoryMember(kind=StoryMemberKind.STORY, id=story_id)


async def made(store: StoryStore, *members: StoryMember) -> str:
    """Create a story holding ``members`` and return its id, failing on a refusal."""
    outcome = await store.create(members, actor=_OWNER)
    assert outcome.refusal is None, outcome
    assert outcome.story_id is not None
    return outcome.story_id


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


def refused(outcome: StoryOutcome, reason: StoryRefusalReason) -> None:
    """Assert ``outcome`` is a refusal for ``reason`` that wrote nothing."""
    assert outcome.story_id is None
    assert outcome.logged == 0
    assert outcome.refusal is not None
    assert outcome.refusal.reason is reason


async def everything(store: StoryStore) -> tuple[Any, ...]:
    """Every story's header, view, log and page: the whole observable state."""
    page = await store.stories(limit=MAX_STORY_PAGE)
    assert page.next_cursor is None
    state: list[Any] = []
    for header in page.stories:
        state.append(header)
        state.append(await store.view(header.story_id, limit=MAX_STORY_PAGE))
        state.append(await store.log(header.story_id, limit=MAX_STORY_PAGE))
        state.append(await store.current_page(header.story_id))
        state.append(await store.notes(header.story_id, limit=MAX_STORY_PAGE))
        state.append(await store.page_versions(header.story_id, limit=MAX_STORY_PAGE))
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
    """Append a note and return it, failing on a refusal; ``on=None`` for ``owner``."""
    outcome = await store.append_note(
        story_id,
        text,
        author=author,
        rests_on=None if author is StoryNoteAuthor.OWNER else on,
        outside=outside,
    )
    assert outcome.refusal is None, outcome
    assert outcome.note is not None
    return outcome.note


async def state_of(store: StoryStore, story_id: str) -> StoryPageState:
    """A story's current page with what is pending on it."""
    state = await store.current_page(story_id)
    assert state is not None
    return state


def line(
    text: str, *cites: int, new: tuple[int, ...] = (), outside: bool = False
) -> StoryDraftLine:
    """A draft line citing ``cites`` and the safety-net notes at indexes ``new``."""
    return StoryDraftLine(text=text, cites=cites, cites_new=new, outside=outside)


def draft(*lines: StoryDraftLine, **rest: Any) -> StoryPageDraft:
    """A draft of ``lines`` and whatever else it writes."""
    return StoryPageDraft(lines=lines, **rest)


async def written(
    store: StoryStore, story_id: str, page: StoryPageDraft, *, as_of: int
) -> StoryPageVersion:
    """Write a page and return its version, failing on a refusal."""
    outcome = await store.write_page(story_id, page, as_of=as_of)
    assert outcome.refusal is None, outcome
    assert outcome.version is not None
    return outcome.version


async def versions_of(store: StoryStore, story_id: str) -> list[StoryPageVersion]:
    """A story's whole version log."""
    page = await store.page_versions(story_id, limit=MAX_STORY_PAGE)
    assert page is not None
    assert page.next_cursor is None
    return list(page.versions)


async def notes_of(store: StoryStore, story_id: str) -> list[StoryNote]:
    """Every note a story holds, in the order they were written."""
    page = await store.notes(story_id, limit=MAX_STORY_PAGE)
    assert page is not None
    assert page.next_cursor is None
    return list(page.notes)


def page_refused(
    outcome: StoryPageOutcome | StoryNoteOutcome, reason: StoryPageRefusalReason
) -> None:
    """Assert a page write or a note append was refused for ``reason``."""
    assert outcome.refusal is not None, outcome
    assert outcome.refusal.reason is reason


class StoryStoreContract:
    """The behavioural contract every ``StoryStore`` must satisfy (ADR-0289 §§1-3)."""

    @pytest.fixture
    def store(self) -> StoryStore:
        """Override in a subclass: an empty store whose clock reads ``STORY_AT``."""
        raise NotImplementedError

    # --- create (§3) ---------------------------------------------------------

    async def test_create_mints_a_story_with_its_members_in_order(self, store: StoryStore) -> None:
        """Create mints a ``story:`` id, logs ``created`` then each member ``added``."""
        outcome = await store.create([act("a1"), act("a2")], actor=_OWNER)
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
        refused(await store.create([], actor=_OWNER), StoryRefusalReason.NO_MEMBERS)
        assert (await store.stories()).stories == ()

    async def test_a_member_named_twice_is_added_once(self, store: StoryStore) -> None:
        outcome = await store.create([act("a"), act("a"), act("b")], actor=_OWNER)
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
        outcome = await store.create([act("a"), sub("story:nowhere")], actor=_OWNER)
        refused(outcome, StoryRefusalReason.UNKNOWN_STORY)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == "story:nowhere"
        assert (await store.stories()).stories == ()

    async def test_a_trigger_is_recorded_on_every_line(self, store: StoryStore) -> None:
        outcome = await store.create([act("a")], actor=_OWNER, trigger="activation-7")
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
            store.create([sub(absorbed)], actor=_OWNER),
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
            await store.create(members, actor=_OWNER)  # type: ignore[arg-type]
        assert (await store.stories()).stories == ()

    async def test_a_blank_story_id_or_unknown_actor_is_a_value_error(
        self, store: StoryStore
    ) -> None:
        with pytest.raises(ValueError):  # noqa: PT011 — any validation message will do
            await store.link("  ", [act("a")], actor=_OWNER)
        with pytest.raises(ValueError):  # noqa: PT011 — any validation message will do
            await store.create([act("a")], actor="planner")  # type: ignore[arg-type]
        assert (await store.stories()).stories == ()

    # --- the actors ADR-0300 adds (§3:15) ------------------------------------

    @pytest.mark.parametrize(
        "actor", [StoryActor.UNDERSTANDING, StoryActor.PLANNING, StoryActor.MATTERS_PASS]
    )
    async def test_each_new_actor_is_recorded_as_it_writes(
        self, store: StoryStore, actor: StoryActor
    ) -> None:
        outcome = await store.create([act("a")], actor=actor, trigger="a")
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
        assert first.rests_on == "a1"
        assert first.outside is True
        assert first.written_at == STORY_AT
        assert second.rests_on is None
        assert second.outside is False
        assert second.note_id > first.note_id
        assert await notes_of(store, story_id) == [first, second]
        state = await state_of(store, story_id)
        assert state.pending_notes == (first, second)
        assert state.page is None

    async def test_a_note_keeps_its_text_byte_for_byte(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        text = "  Sister would prefer Saturday (her message).\n"
        note = await noted(store, story_id, text, author=StoryNoteAuthor.OWNER)
        assert note.text == text
        assert (await notes_of(store, story_id))[0].text == text

    @pytest.mark.parametrize(
        ("author", "rests_on", "outside"),
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
        self, store: StoryStore, author: object, rests_on: object, outside: object
    ) -> None:
        story_id = await made(store, act("a1"))
        before = await everything(store)
        with pytest.raises(ValueError):  # noqa: PT011 — any validation message will do
            await store.append_note(
                story_id,
                "a note",
                author=author,  # type: ignore[arg-type]
                rests_on=rests_on,  # type: ignore[arg-type]
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
                rests_on="a1",
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
            "story:nowhere", "n", author=StoryNoteAuthor.PLANNING, rests_on="a"
        )
        page_refused(unknown, StoryPageRefusalReason.UNKNOWN_STORY)
        assert unknown.refusal is not None
        assert unknown.refusal.story_id == "story:nowhere"
        merged = await store.append_note(absorbed, "n", author=StoryNoteAuthor.OWNER)
        page_refused(merged, StoryPageRefusalReason.MERGED_STORY)
        assert merged.refusal is not None
        assert merged.refusal.merged_into == target
        assert await everything(store) == before

    async def test_a_note_may_rest_on_an_activation_the_story_does_not_hold(
        self, store: StoryStore
    ) -> None:
        """Planning may write to any story by id (ADR-0300 §10); the store reads no other."""
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "From elsewhere.", on="elsewhere")
        assert note.rests_on == "elsewhere"

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

    async def test_an_unknown_story_has_no_page(self, store: StoryStore) -> None:
        assert await store.current_page("story:nowhere") is None
        assert await store.notes("story:nowhere") is None
        assert await store.page_versions("story:nowhere") is None

    # --- pending (ADR-0300 §3:8) ---------------------------------------------

    async def test_activation_members_are_pending_in_link_order(self, store: StoryStore) -> None:
        inner = await made(store, act("x"))
        story_id = await made(store, act("a2"), sub(inner), act("a1"))
        await store.link(story_id, [act("a3")], actor=_OWNER)
        state = await state_of(store, story_id)
        assert state.pending_episodes == ("a2", "a1", "a3")

    async def test_a_page_write_takes_in_what_it_names(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"), act("a2"))
        note = await noted(store, story_id, "Camping at Riverside.")
        before = await state_of(store, story_id)
        version = await written(
            store,
            story_id,
            draft(
                line("A camping trip to Riverside.", note.note_id),
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
        assert after.page is not None
        assert after.page.version == version.version
        assert after.page.written_at == STORY_AT
        assert after.page.lines == (
            StoryPageLine(
                text="A camping trip to Riverside.", cites=(note.note_id,), outside=False
            ),
        )

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
                line("The matter.", first.note_id),
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
        note = await noted(store, story_id, "Note.")
        read = await state_of(store, story_id)
        await store.unlink(story_id, [act("a1")], actor=_OWNER)
        await store.link(story_id, [act("a1")], actor=_OWNER)
        version = await written(
            store,
            story_id,
            draft(line("The matter.", note.note_id), took_in_episodes=("a1",)),
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
                line("The matter.", note.note_id),
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
                line("The matter.", note.note_id),
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
        note = await noted(store, first, "Note.", on="shared")
        read = await state_of(store, first)
        await written(
            store,
            first,
            draft(line("The matter.", note.note_id), took_in_episodes=("shared",)),
            as_of=read.as_of,
        )
        assert (await state_of(store, first)).pending_episodes == ()
        assert (await state_of(store, second)).pending_episodes == ("shared",)

    # --- the page write (ADR-0300 §3:6, §3:7, §3:10) -------------------------

    async def test_a_page_write_adds_its_safety_net_notes_cited_by_identity(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"), act("a2"))
        note = await noted(store, story_id, "Riverside.")
        read = await state_of(store, story_id)
        page = draft(
            line("A camping trip to Riverside.", note.note_id),
            line("Booked for Sunday.", new=(0,), outside=True),
            line("Both.", note.note_id, new=(1, 0)),
            safety_net=(
                StorySafetyNetNote(text="Booked Sunday.", rests_on="a2", outside=True),
                StorySafetyNetNote(text="Dog allowed.", rests_on="a1", outside=False),
            ),
            took_in_notes=(note.note_id,),
            took_in_episodes=("a1", "a2"),
        )
        version = await written(store, story_id, page, as_of=read.as_of)
        net = version.safety_net
        assert len(net) == 2
        assert net[0] < net[1] < version.version
        assert version.lines == ((note.note_id,), (net[0],), (note.note_id, net[1], net[0]))
        notes = await notes_of(store, story_id)
        assert [n.note_id for n in notes] == [note.note_id, *net]
        added = notes[1:]
        assert [n.author for n in added] == [StoryNoteAuthor.TIDY_UP] * 2
        assert [(n.text, n.rests_on, n.outside) for n in added] == [
            ("Booked Sunday.", "a2", True),
            ("Dog allowed.", "a1", False),
        ]
        assert all(n.written_at == STORY_AT for n in added)
        state = await state_of(store, story_id)
        assert state.pending_notes == ()
        assert state.page is not None
        assert [ln.cites for ln in state.page.lines] == list(version.lines)
        assert [ln.outside for ln in state.page.lines] == [False, True, False]
        assert await versions_of(store, story_id) == [version]

    async def test_a_version_records_its_marks_and_flags(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        other = await made(store, act("a9"))
        mine = await noted(store, story_id, "No Saturdays.", author=StoryNoteAuthor.OWNER)
        read = await state_of(store, story_id)
        marks = (StorySupersession(note=mine.note_id, episode="a1"),)
        flags = (
            StoryFlag(kind=StoryFlagKind.TWO_MATTERS),
            StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other),
        )
        version = await written(
            store,
            story_id,
            draft(line("Saturday's fine now.", mine.note_id), supersessions=marks, flags=flags),
            as_of=read.as_of,
        )
        assert version.supersessions == marks
        assert version.flags == flags
        assert version.written_at == STORY_AT
        assert await versions_of(store, story_id) == [version]

    async def test_a_new_page_replaces_the_old_and_the_log_keeps_both(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Note.")
        first = await written(
            store,
            story_id,
            draft(line("Old line.", note.note_id)),
            as_of=(await state_of(store, story_id)).as_of,
        )
        second = await written(
            store,
            story_id,
            draft(line("New line.", note.note_id), line("Another.", note.note_id)),
            as_of=(await state_of(store, story_id)).as_of,
        )
        assert second.version > first.version
        state = await state_of(store, story_id)
        assert state.page is not None
        assert [ln.text for ln in state.page.lines] == ["New line.", "Another."]
        assert await versions_of(store, story_id) == [first, second]

    async def test_the_version_log_pages_oldest_first(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Note.")
        made_versions = [
            await written(
                store,
                story_id,
                draft(line(f"Line {n}.", note.note_id)),
                as_of=(await state_of(store, story_id)).as_of,
            )
            for n in range(5)
        ]
        seen: list[StoryPageVersion] = []
        cursor: int | None = None
        while True:
            page = await store.page_versions(story_id, cursor=cursor, limit=2)
            assert page is not None
            seen.extend(page.versions)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        assert seen == made_versions

    async def test_a_page_built_on_a_stale_read_is_refused_and_writes_nothing(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Note.")
        stale = await state_of(store, story_id)
        await written(store, story_id, draft(line("First.", note.note_id)), as_of=stale.as_of)
        before = await everything(store)
        outcome = await store.write_page(
            story_id,
            draft(
                line("Second.", note.note_id),
                safety_net=(StorySafetyNetNote(text="Net.", rests_on="a1", outside=False),),
                took_in_episodes=("a1",),
            ),
            as_of=stale.as_of,
        )
        page_refused(outcome, StoryPageRefusalReason.PAGE_MOVED_ON)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == story_id
        assert await everything(store) == before

    async def test_a_write_built_on_a_read_after_a_merge_is_not_stale(
        self, store: StoryStore
    ) -> None:
        """Only a version of the story's own page moves it on."""
        target = await made(store, act("a1"))
        absorbed = await made(store, act("a2"))
        note = await noted(store, target, "Note.")
        read = await state_of(store, target)
        await store.merge(absorbed, target, actor=_OWNER)
        await written(store, target, draft(line("The matter.", note.note_id)), as_of=read.as_of)

    @pytest.mark.parametrize("where", ["line", "mark"])
    async def test_a_page_naming_a_note_the_store_does_not_hold_is_refused(
        self, store: StoryStore, where: str
    ) -> None:
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Note.")
        read = await state_of(store, story_id)
        missing = note.note_id + 10_000
        page = (
            draft(line("Line.", note.note_id, missing))
            if where == "line"
            else draft(
                line("Line.", note.note_id),
                supersessions=(StorySupersession(note=missing, episode="a1"),),
            )
        )
        before = await everything(store)
        outcome = await store.write_page(story_id, page, as_of=read.as_of)
        page_refused(outcome, StoryPageRefusalReason.UNKNOWN_NOTE)
        assert outcome.refusal is not None
        assert outcome.refusal.note == missing
        assert await everything(store) == before

    async def test_a_page_may_cite_a_note_of_another_story(self, store: StoryStore) -> None:
        """Whether a cited note is this story's is the hub's check (§5), not the store's."""
        story_id = await made(store, act("a1"))
        other = await made(store, act("a2"))
        foreign = await noted(store, other, "Elsewhere.", on="a2")
        read = await state_of(store, story_id)
        version = await written(
            store, story_id, draft(line("Line.", foreign.note_id)), as_of=read.as_of
        )
        assert version.lines == ((foreign.note_id,),)

    async def test_a_flag_naming_an_unknown_story_is_refused(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Note.")
        read = await state_of(store, story_id)
        before = await everything(store)
        outcome = await store.write_page(
            story_id,
            draft(
                line("Line.", note.note_id),
                flags=(StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story="story:nowhere"),),
            ),
            as_of=read.as_of,
        )
        page_refused(outcome, StoryPageRefusalReason.UNKNOWN_STORY)
        assert outcome.refusal is not None
        assert outcome.refusal.story_id == "story:nowhere"
        assert await everything(store) == before

    async def test_a_flag_naming_its_own_story_is_a_value_error(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Note.")
        read = await state_of(store, story_id)
        with pytest.raises(ValueError, match="another story"):
            await store.write_page(
                story_id,
                draft(
                    line("Line.", note.note_id),
                    flags=(StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=story_id),),
                ),
                as_of=read.as_of,
            )

    async def test_a_page_to_an_unknown_or_merged_story_is_refused(self, store: StoryStore) -> None:
        absorbed = await made(store, act("a"))
        target = await made(store, act("b"))
        note = await noted(store, absorbed, "Note.", on="a")
        read = await state_of(store, absorbed)
        await store.merge(absorbed, target, actor=_OWNER)
        before = await everything(store)
        page = draft(line("Line.", note.note_id))
        unknown = await store.write_page("story:nowhere", page, as_of=read.as_of)
        page_refused(unknown, StoryPageRefusalReason.UNKNOWN_STORY)
        merged = await store.write_page(absorbed, page, as_of=read.as_of)
        page_refused(merged, StoryPageRefusalReason.MERGED_STORY)
        assert merged.refusal is not None
        assert merged.refusal.merged_into == target
        assert await everything(store) == before

    async def test_the_cap_binds_every_line_but_the_users_own_notes(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        long = "y" * STORY_NOTE_MAX_CHARS
        theirs = [
            await noted(store, story_id, f"{n}{long[1:]}", author=StoryNoteAuthor.OWNER)
            for n in range(5)
        ]
        planning = await noted(store, story_id, "Planning's note.")
        read = await state_of(store, story_id)
        own_lines = [line(n.text, n.note_id) for n in theirs]
        budget = STORY_PAGE_CAP_CHARS // STORY_NOTE_MAX_CHARS
        other_lines = [line(long, planning.note_id) for _ in range(budget)]
        version = await written(store, story_id, draft(*own_lines, *other_lines), as_of=read.as_of)
        assert len(version.lines) == len(theirs) + budget
        before = await everything(store)
        outcome = await store.write_page(
            story_id,
            draft(*own_lines, *other_lines, line("z", planning.note_id)),
            as_of=(await state_of(store, story_id)).as_of,
        )
        page_refused(outcome, StoryPageRefusalReason.OVER_CAP)
        assert await everything(store) == before

    async def test_a_line_altering_the_users_note_counts_against_the_cap(
        self, store: StoryStore
    ) -> None:
        story_id = await made(store, act("a1"))
        long = "y" * STORY_NOTE_MAX_CHARS
        budget = STORY_PAGE_CAP_CHARS // STORY_NOTE_MAX_CHARS
        theirs = [
            await noted(store, story_id, f"{n}{long[1:]}", author=StoryNoteAuthor.OWNER)
            for n in range(budget + 1)
        ]
        read = await state_of(store, story_id)
        reworded = [line(n.text[:-1] + "!", n.note_id) for n in theirs]
        outcome = await store.write_page(story_id, draft(*reworded), as_of=read.as_of)
        page_refused(outcome, StoryPageRefusalReason.OVER_CAP)

    @pytest.mark.parametrize("as_of", [-1, 2**63, True, "0", None])
    async def test_a_malformed_as_of_is_a_value_error(
        self, store: StoryStore, as_of: object
    ) -> None:
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Note.")
        with pytest.raises(ValueError, match="as_of"):
            await store.write_page(
                story_id,
                draft(line("Line.", note.note_id)),
                as_of=as_of,  # type: ignore[arg-type]
            )

    async def test_an_as_of_no_read_returned_is_a_value_error(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Note.")
        read = await state_of(store, story_id)
        before = await everything(store)
        with pytest.raises(ValueError, match="as_of"):
            await store.write_page(
                story_id, draft(line("Line.", note.note_id)), as_of=read.as_of + 1
            )
        assert await everything(store) == before

    async def test_a_draft_that_is_not_one_is_a_value_error(self, store: StoryStore) -> None:
        story_id = await made(store, act("a1"))
        with pytest.raises(ValueError, match="StoryPageDraft"):
            await store.write_page(story_id, {"lines": []}, as_of=0)  # type: ignore[arg-type]

    # --- merge, split and move carry notes (ADR-0300 §3:12-§3:14) ------------

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
            draft(line("A's page.", taken.note_id), took_in_notes=(taken.note_id,)),
            as_of=read.as_of,
        )
        target_read = await state_of(store, target)
        await written(
            store,
            target,
            draft(line("B's page.", taken.note_id), took_in_episodes=("shared", "t")),
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

    async def test_a_split_carries_the_notes_on_what_it_moves_and_those_it_names(
        self, store: StoryStore
    ) -> None:
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
                line("Page.", on_x.note_id),
                took_in_notes=(on_x.note_id, on_y.note_id, named.note_id, kept.note_id),
                took_in_episodes=("x", "y"),
            ),
            as_of=read.as_of,
        )
        outcome = await store.split(
            source,
            [act("x")],
            actor=_OWNER,
            notes=[named.note_id, on_y.note_id, foreign.note_id, 999_999],
        )
        assert outcome.refusal is None
        assert outcome.logged == 5
        split_off = outcome.story_id
        assert split_off is not None
        assert await notes_of(store, split_off) == [on_x, named]
        assert await notes_of(store, source) == [on_y, kept]
        assert await notes_of(store, elsewhere) == [foreign]
        state = await state_of(store, split_off)
        assert state.pending_notes == (on_x, named)
        assert state.pending_episodes == ("x",)
        assert (await state_of(store, source)).pending_notes == ()

    @pytest.mark.parametrize("notes", ["1", [0], [True], [1.0], 3])
    async def test_a_split_naming_malformed_notes_is_a_value_error(
        self, store: StoryStore, notes: object
    ) -> None:
        source = await made(store, act("x"))
        before = await everything(store)
        with pytest.raises(ValueError, match="note"):
            await store.split(source, [act("x")], actor=_OWNER, notes=notes)  # type: ignore[arg-type]
        assert await everything(store) == before

    async def test_a_move_carries_members_and_their_notes(self, store: StoryStore) -> None:
        source = await made(store, act("x"), act("y"), act("both"))
        target = await made(store, act("both"), act("t"))
        on_x = await noted(store, source, "On x.", on="x")
        on_y = await noted(store, source, "On y.", on="y")
        on_both = await noted(store, source, "On both.", on="both")
        theirs = await noted(store, source, "The user's.", author=StoryNoteAuthor.OWNER)
        target_view = await store.view(target)
        assert target_view is not None
        outcome = await store.move(source, target, [act("both"), act("x")], actor=_OWNER)
        assert outcome.refusal is None
        assert outcome.story_id == target
        assert outcome.logged == 3
        assert await held(store, source) == [act("y")]
        assert await held(store, target) == [act("both"), act("t"), act("x")]
        after_view = await store.view(target)
        assert after_view is not None
        assert after_view.entries[0] == target_view.entries[0]
        assert shape(await logged(store, source))[-2:] == [
            (StoryChange.REMOVED, "x"),
            (StoryChange.REMOVED, "both"),
        ]
        assert shape(await logged(store, target))[-1:] == [(StoryChange.ADDED, "x")]
        assert await notes_of(store, source) == [on_y, theirs]
        assert await notes_of(store, target) == [on_x, on_both]
        state = await state_of(store, target)
        assert state.pending_notes == (on_x, on_both)
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
            draft(line("Page.", note.note_id), took_in_notes=(note.note_id,)),
            as_of=read.as_of,
        )
        await store.move(source, target, [act("x")], actor=_OWNER)
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

    async def test_a_move_naming_no_member_is_refused(self, store: StoryStore) -> None:
        source = await made(store, act("x"))
        target = await made(store, act("t"))
        refused(await store.move(source, target, [], actor=_OWNER), StoryRefusalReason.NO_MEMBERS)

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

    async def test_an_unlink_leaves_the_notes_on_the_story(self, store: StoryStore) -> None:
        story_id = await made(store, act("x"), act("y"))
        note = await noted(store, story_id, "On x.", on="x")
        await store.unlink(story_id, [act("x")], actor=_OWNER)
        assert await notes_of(store, story_id) == [note]
        state = await state_of(store, story_id)
        assert state.pending_notes == (note,)
        assert state.pending_episodes == ("y",)
