"""Shared conformance suite for the StoryStore Protocol (ADR-0289 §§1-3).

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
    StoryActor,
    StoryChange,
    StoryLogLine,
    StoryMember,
    StoryMemberKind,
    StoryOutcome,
    StoryRefusalReason,
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
    """Every story's header, view and log: the whole observable state."""
    page = await store.stories(limit=MAX_STORY_PAGE)
    assert page.next_cursor is None
    state: list[Any] = []
    for header in page.stories:
        state.append(header)
        state.append(await store.view(header.story_id, limit=MAX_STORY_PAGE))
        state.append(await store.log(header.story_id, limit=MAX_STORY_PAGE))
    return tuple(state)


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
