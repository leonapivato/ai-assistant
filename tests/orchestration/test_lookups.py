"""Planning's look-ups, driven directly over fakes (ADR-0307 §6:6, ADR-0308 §6).

The declarations, which of their arguments are labels, and the runner: a memory search
routed record by record under the pass's audience, a story's full view held for the
glue, and the follow-up naming the result it asks about. Acting's half of the follow-up,
and of holding a search's outside records by id, is ``test_acting``'s.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.errors import MemoryStoreError, PlanningError, StoryStoreError
from ai_assistant.core.types import (
    ActionRequest,
    Attestation,
    BeliefBand,
    CapabilityEffect,
    CapabilityResult,
    LabelKind,
    Memory,
    MemorySearchResult,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    ToolCall,
    ToolDefinition,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.acting import HeldByIds, NamedResult
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply, UnboundedAudienceSupply
from ai_assistant.orchestration.lookups import (
    FOLLOW_UP,
    FOLLOW_UP_CAPABILITY,
    LOOK_UP_CAPABILITIES,
    LOOK_UP_LABEL_ARGUMENTS,
    LOOK_UPS,
    OLDER_NOTES_PAGE_ARGUMENT,
    READ_STORY,
    READ_STORY_CAPABILITY,
    SEARCH_MEMORY,
    SEARCH_MEMORY_CAPABILITY,
    LookUps,
    searched_ids,
)
from ai_assistant.orchestration.planning import LOOKING_FOR, PlanningStory, offered_tools
from ai_assistant.testing import FakeMemoryStore
from ai_assistant.testing.memories import memory, remembered_support, said_support, sourced_support

if TYPE_CHECKING:
    from ai_assistant.orchestration.acting import OwnRecordsAnswer
    from ai_assistant.orchestration.disclosure import TurnSupply

_AT: Final = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())


def _fact(memory_id: str, fact: str, *, outside: bool = False, **fields: Any) -> Memory:
    """A remembered fact: the user's word, or what a source reported."""
    support = (
        sourced_support(Attestation(reported_by="mail", reported_at=_AT), when=_AT, added_at=_AT)
        if outside
        else said_support(when=_AT, added_at=_AT)
    )
    return memory(memory_id, fact, support, **fields)


def _call(tool: ToolDefinition, *, decision: str = "d1", **parameters: Any) -> ToolCall:
    request = ActionRequest(tool=tool, parameters=parameters)
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    allowed = PermissionDecision.from_request(request, ruling, id=decision, decided_at=_AT)
    return ToolCall(request=request, decision=allowed)


class _Views:
    """A ``StoryViews`` stub: one view per story id, or what ``raises`` raises."""

    def __init__(
        self,
        views: dict[str, PlanningStory] | None = None,
        *,
        raises: Exception | None = None,
    ) -> None:
        self.views = views or {}
        self.raises = raises
        self.reads: list[tuple[str, TurnSupply, bool]] = []
        self.pages: list[int] = []

    async def view(
        self, story_id: str, *, audience: TurnSupply, owner_records: bool, older_page: int = 1
    ) -> PlanningStory | None:
        self.reads.append((story_id, audience, owner_records))
        self.pages.append(older_page)
        if self.raises is not None:
            raise self.raises
        return self.views.get(story_id)


async def _store(*records: Memory) -> FakeMemoryStore:
    store = FakeMemoryStore(now=lambda: _AT)
    for record in records:
        await store.add(record)
    return store


def _failed(answer: OwnRecordsAnswer, kind: ToolFailureKind) -> None:
    assert isinstance(answer, ToolResult)
    assert answer.outcome is ToolOutcome.FAILED
    assert answer.failure is not None
    assert answer.failure.kind is kind


# --- the declarations --------------------------------------------------------------------


def test_each_look_up_reads_the_assistants_own_records_and_writes_nothing() -> None:
    """ADR-0306 §3:1, ADR-0308 §6:6: own records, never leaving the hub, never unknown."""
    assert [str(one.capability) for one in LOOK_UPS] == list(LOOK_UP_CAPABILITIES)
    # ADR-0364 §8:1: under their names now; §3:7: and the connections search.
    assert LOOK_UP_CAPABILITIES == (
        "search_memories",
        "read_matter",
        "reread_result",
        # ADR-0358 §6:1: the episode look-ups, each a read of the assistant's own records.
        "search_episodes",
        "read_episode",
        "read_origin_history",
        "search_connections",
    )
    for one in LOOK_UPS:
        assert one.effect is CapabilityEffect.OWN_RECORDS
        assert one.leaves_hub is False
        assert one.outcome_can_be_unknown is False
        assert one.safe_to_repeat is True
        assert one.writes == ()
        assert one.discloses == ()
        assert one.reversibility is Reversibility.REVERSIBLE
        assert one.system_supplied == ()


def test_what_each_look_up_returns() -> None:
    """A memory search and a follow-up may carry outside text; a story read does not."""
    assert SEARCH_MEMORY.result is CapabilityResult.MAY_CARRY_OUTSIDE_TEXT
    assert FOLLOW_UP.result is CapabilityResult.MAY_CARRY_OUTSIDE_TEXT
    assert READ_STORY.result is CapabilityResult.NO_OUTSIDE_TEXT


def test_the_look_ups_are_offered_with_looking_for_where_outside_text_may_come_back() -> None:
    """ADR-0306 §2:9: a required *looking for*, and no *deliberate repeat* mark."""
    offered = {one.name: one.model_dump()["parameters"] for one in offered_tools(LOOK_UPS)}
    assert set(offered) == set(LOOK_UP_CAPABILITIES)
    assert offered[SEARCH_MEMORY_CAPABILITY]["required"] == ["query", LOOKING_FOR]
    assert offered[FOLLOW_UP_CAPABILITY]["required"] == ["result", LOOKING_FOR]
    assert offered[READ_STORY_CAPABILITY]["required"] == ["matter"]
    # #2893: which page of the story's older notes, optional, a whole number from 1.
    older = offered[READ_STORY_CAPABILITY]["properties"][OLDER_NOTES_PAGE_ARGUMENT]
    assert (older["type"], older["minimum"]) == ("integer", 1)
    assert all("deliberate_repeat" not in schema["properties"] for schema in offered.values())


def test_a_story_read_names_a_story_and_a_follow_up_a_result_by_label() -> None:
    """ADR-0307 §5:2, ADR-0308 §6:6: the follow-up's one planner argument is an R label."""
    assert LOOK_UP_LABEL_ARGUMENTS == {
        READ_STORY_CAPABILITY: {"matter": LabelKind.STORY},
        FOLLOW_UP_CAPABILITY: {"result": LabelKind.RESULT},
        # ADR-0358 §10:1: the episode look-up names its episode by its E label.
        "read_episode": {"episode": LabelKind.EPISODE},
    }
    assert set(FOLLOW_UP.model_dump()["parameters_schema"]["properties"]) == {"result"}


def test_the_ids_a_search_lists_for_planning_are_read_back() -> None:
    assert searched_ids({"records": ("a", "b")}) == ("a", "b")
    assert searched_ids({"records": ["a", 3]}) == ("a",)
    assert searched_ids({"story": "s1"}) == ()
    assert searched_ids(None) == ()


def test_a_search_keeps_at_least_one_record() -> None:
    with pytest.raises(ValueError, match="at least one"):
        LookUps(memory=FakeMemoryStore(), views=None, search_limit=0)


# --- the memory search -------------------------------------------------------------------


async def test_a_search_splits_what_it_found_into_shown_and_held_by_id() -> None:
    """ADR-0306 §5:16, ADR-0308 §6:2: by each record's stored source.

    The user's fact goes to planning by its id; the fact a source reported is held by
    id, for a digest to fetch.
    """
    store = await _store(
        _fact("said", "dentist with Dr Rao"),
        _fact("reported", "dentist moved to 3pm", outside=True),
        _fact("other", "the car is red"),
    )
    look_ups = LookUps(memory=store, views=None, search_limit=5)

    with look_ups.scope(audience=BOUNDED, owner_records=True):
        answer = await look_ups.run(_call(SEARCH_MEMORY, query="dentist"))

    assert isinstance(answer, HeldByIds)
    assert searched_ids(answer.output) == ("said",)
    assert answer.outside == ("reported",)


async def test_a_search_applies_the_audience_predicate_at_the_search() -> None:
    """ADR-0282 §2:8: an id enters the working episode only once its record is admitted.

    On an unbounded audience a fact about someone else and a fact from a source this
    audience may not hear are not kept, shown or held.
    """
    store = await _store(
        _fact("said", "dentist with Dr Rao"),
        _fact("about-sam", "dentist for Sam on Monday", subjects=("Sam",)),
        _fact("reported", "dentist moved to 3pm", outside=True),
    )
    look_ups = LookUps(memory=store, views=None, search_limit=5)

    with look_ups.scope(audience=UNBOUNDED, owner_records=False):
        answer = await look_ups.run(_call(SEARCH_MEMORY, query="dentist"))

    assert isinstance(answer, HeldByIds)
    assert searched_ids(answer.output) == ("said",)
    assert answer.outside == ()


class _Searched(FakeMemoryStore):
    """A store recording each search's arguments."""

    def __init__(self) -> None:
        super().__init__(now=lambda: _AT)
        self.searches: list[dict[str, Any]] = []

    async def search(self, query: str, **kwargs: Any) -> MemorySearchResult:
        self.searches.append({"query": query, **kwargs})
        return await super().search(query, **kwargs)


async def test_a_search_asks_for_remembered_facts_alone_each_band_on_its_own() -> None:
    """ADR-0072 §5: each band read on its own, in precedence order, up to the limit."""
    store = _Searched()
    look_ups = LookUps(memory=store, views=None, search_limit=4)

    with look_ups.scope(audience=BOUNDED, owner_records=True):
        await look_ups.run(_call(SEARCH_MEMORY, query="dentist"))

    assert [search["query"] for search in store.searches] == ["dentist"] * 3
    assert all(search["limit"] == 4 for search in store.searches)
    assert all([kind.value for kind in one["kinds"]] == ["memory"] for one in store.searches)
    assert [tuple(one["bands"]) for one in store.searches] == [
        (BeliefBand.ASSERTED,),
        (BeliefBand.ATTESTED,),
        (BeliefBand.DERIVED,),
    ]


async def test_inferences_never_displace_an_assertion_below_the_limit() -> None:
    """ADR-0072 §5: precedence is by band, so a closer inference cannot cut the user's word.

    At a limit of one, the user's own fact is kept over an inference that matches the
    query more closely, and the later bands are not searched once the limit is filled.
    """
    inferred = memory(
        "inferred",
        "dentist appointment probably with Dr Lee",
        remembered_support(when=_AT, added_at=_AT),
    )
    store = _Searched()
    for record in (inferred, _fact("said", "my dentist is Dr Rao")):
        await store.add(record)
    look_ups = LookUps(memory=store, views=None, search_limit=1)

    with look_ups.scope(audience=BOUNDED, owner_records=True):
        answer = await look_ups.run(_call(SEARCH_MEMORY, query="dentist appointment"))

    assert isinstance(answer, HeldByIds)
    assert searched_ids(answer.output) == ("said",)
    assert [tuple(one["bands"]) for one in store.searches] == [(BeliefBand.ASSERTED,)]


class _Down(FakeMemoryStore):
    async def search(self, query: str, **kwargs: Any) -> MemorySearchResult:
        del query, kwargs
        msg = "the store is down"
        raise MemoryStoreError(msg)


async def test_a_search_the_store_cannot_answer_is_not_done() -> None:
    look_ups = LookUps(memory=_Down(), views=None, search_limit=5)

    with look_ups.scope(audience=BOUNDED, owner_records=True):
        answer = await look_ups.run(_call(SEARCH_MEMORY, query="dentist"))

    _failed(answer, ToolFailureKind.UNAVAILABLE)


async def test_a_search_outside_a_scope_reads_nothing_and_is_not_done() -> None:
    """A look-up reads under the pass's audience; with none given it reads nothing."""
    store = _Searched()
    look_ups = LookUps(memory=store, views=None, search_limit=5)

    answer = await look_ups.run(_call(SEARCH_MEMORY, query="dentist"))

    _failed(answer, ToolFailureKind.INTERNAL)
    assert store.searches == []


async def test_a_blank_query_is_not_done() -> None:
    look_ups = LookUps(memory=_Searched(), views=None, search_limit=5)

    with look_ups.scope(audience=BOUNDED, owner_records=True):
        answer = await look_ups.run(_call(SEARCH_MEMORY, query="  "))

    _failed(answer, ToolFailureKind.INVALID_REQUEST)


# --- a story's full view ---------------------------------------------------------------


async def test_a_story_read_reads_the_view_under_the_scope_and_holds_it_for_the_glue() -> None:
    """ADR-0307 §6:4, §6:6: the view under the pass's audience and owner-only placement."""
    view = PlanningStory(story_id="story-1", tidied_at=None, changes=2)
    views = _Views({"story-1": view})
    look_ups = LookUps(memory=FakeMemoryStore(), views=views, search_limit=5)

    with look_ups.scope(audience=UNBOUNDED, owner_records=False) as scope:
        answer = await look_ups.run(_call(READ_STORY, decision="d7", matter="story-1"))

    assert isinstance(answer, ToolResult)
    assert answer.outcome is ToolOutcome.SUCCEEDED
    assert answer.output == {"story": "story-1"}
    assert views.reads == [("story-1", UNBOUNDED, False)]
    assert views.pages == [1]
    assert scope.views == {"d7": view}


async def test_a_story_read_asks_for_the_page_of_older_notes_it_names() -> None:
    """#2893: a read naming a page of the story's older notes reads that page."""
    views = _Views({"story-1": PlanningStory(story_id="story-1", tidied_at=None, changes=0)})
    look_ups = LookUps(memory=FakeMemoryStore(), views=views, search_limit=5)

    with look_ups.scope(audience=BOUNDED, owner_records=True):
        answer = await look_ups.run(_call(READ_STORY, matter="story-1", older_notes_page=3))

    assert isinstance(answer, ToolResult)
    assert answer.outcome is ToolOutcome.SUCCEEDED
    assert views.pages == [3]


@pytest.mark.parametrize("page", [0, -1, True, "2", 1.5])
async def test_a_story_read_naming_no_page_of_one_or_more_is_not_done(page: object) -> None:
    views = _Views({"story-1": PlanningStory(story_id="story-1", tidied_at=None, changes=0)})
    look_ups = LookUps(memory=FakeMemoryStore(), views=views, search_limit=5)

    # The offered schema refuses it first; the runner refuses it again.
    loose = READ_STORY.model_copy(update={"parameters_schema": {"type": "object"}})
    with look_ups.scope(audience=BOUNDED, owner_records=True) as scope:
        answer = await look_ups.run(_call(loose, matter="story-1", older_notes_page=page))

    _failed(answer, ToolFailureKind.INVALID_REQUEST)
    assert views.reads == []
    assert scope.views == {}


async def test_a_story_read_of_a_story_not_held_is_not_done() -> None:
    look_ups = LookUps(memory=FakeMemoryStore(), views=_Views(), search_limit=5)

    with look_ups.scope(audience=BOUNDED, owner_records=True) as scope:
        answer = await look_ups.run(_call(READ_STORY, matter="gone"))

    _failed(answer, ToolFailureKind.INVALID_REQUEST)
    assert scope.views == {}


@pytest.mark.parametrize(
    "error",
    [StoryStoreError("down"), PlanningError("down"), MemoryStoreError("down")],
    ids=["stories", "plans", "memory"],
)
async def test_a_story_read_whose_stores_cannot_be_read_is_not_done(error: Exception) -> None:
    look_ups = LookUps(memory=FakeMemoryStore(), views=_Views(raises=error), search_limit=5)

    with look_ups.scope(audience=BOUNDED, owner_records=True) as scope:
        answer = await look_ups.run(_call(READ_STORY, matter="story-1"))

    _failed(answer, ToolFailureKind.UNAVAILABLE)
    assert scope.views == {}


async def test_a_story_read_with_no_views_or_no_scope_is_not_done() -> None:
    views = _Views({"story-1": PlanningStory(story_id="story-1", tidied_at=None, changes=0)})
    unwired = LookUps(memory=FakeMemoryStore(), views=None, search_limit=5)
    with unwired.scope(audience=BOUNDED, owner_records=True):
        _failed(await unwired.run(_call(READ_STORY, matter="story-1")), ToolFailureKind.INTERNAL)

    wired = LookUps(memory=FakeMemoryStore(), views=views, search_limit=5)
    _failed(await wired.run(_call(READ_STORY, matter="story-1")), ToolFailureKind.INTERNAL)
    assert views.reads == []


# --- the follow-up -------------------------------------------------------------------------


async def test_a_follow_up_answers_the_result_it_names() -> None:
    """ADR-0308 §6:6-§6:7: acting runs it against the held results."""
    look_ups = LookUps(memory=FakeMemoryStore(), views=None, search_limit=5)

    answer = await look_ups.run(_call(FOLLOW_UP, result="result:abc"))

    assert answer == NamedResult(result_id="result:abc")


async def test_a_follow_up_naming_no_result_is_not_done() -> None:
    look_ups = LookUps(memory=FakeMemoryStore(), views=None, search_limit=5)

    # The offered schema refuses it first; the runner refuses it again.
    loose = FOLLOW_UP.model_copy(update={"parameters_schema": {"type": "object"}})
    answer = await look_ups.run(_call(loose, result=""))

    _failed(answer, ToolFailureKind.INVALID_REQUEST)


async def test_a_call_that_is_no_look_up_is_not_done() -> None:
    other = SEARCH_MEMORY.model_copy(update={"id": "other", "capability": "other"})
    look_ups = LookUps(memory=FakeMemoryStore(), views=None, search_limit=5)

    _failed(await look_ups.run(_call(other, query="x")), ToolFailureKind.INVALID_REQUEST)
