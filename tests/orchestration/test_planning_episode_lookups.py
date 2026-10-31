"""How planning is shown what its episode look-ups read, and what a call's entry keeps.

ADR-0358 §6-§11, driven directly over the planning stage, each outcome built by hand as
the phases' glue hands it over: a search of past episodes, each as its short view with
the matters it belongs to; the origin's older history; one episode's full record, each
record it names shown again as it is held now; and :func:`call_showed`, what a done
call's entry keeps of what its result showed, by reference and cut to a bound.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from test_planning import _AT, _TOOLS, _earlier, _episode, _inputs, _remembered, _sent, _stage
from test_planning_stories import _short, _story

from ai_assistant.core.episode_encoding import project_episode
from ai_assistant.core.types import (
    CallShowed,
    EpisodeProcessingRecord,
    EpisodicMemory,
    LabelKind,
    MemorySource,
    PlanningLabel,
    ProposedCall,
    RecordedCall,
    RoundResponse,
    ShownRecord,
    ShownRecordKind,
    ShownText,
)
from ai_assistant.orchestration.lookups import LOOK_UP_LABEL_ARGUMENTS, READ_STORY, SEARCH_EPISODES
from ai_assistant.orchestration.planning import (
    CallOutcome,
    CallOutcomeKind,
    EpisodeRead,
    EpisodesFound,
    EpisodeShown,
    MatterShown,
    OlderHistory,
    PlaceAuthor,
    PlaceItem,
    call_showed,
    full_view_parts,
)
from ai_assistant.testing.parties import UNIDENTIFIED_WORDS


def _looked(name: str, **arguments: Any) -> tuple[Any, ProposedCall]:
    call = ProposedCall(call_id="c1", name=name, arguments=arguments)
    return _earlier(calls=(call,)), call


async def _shown(name: str, outcome_fields: dict[str, Any], **inputs: Any) -> Any:
    """What the briefing shows of one look-up's result, and what the round recorded."""
    earlier, _ = _looked(name)
    outcome = CallOutcome(
        earlier.id, "c1", CallOutcomeKind.DONE, result_id="result:1", **outcome_fields
    )
    stage, completer, _ = _stage(RoundResponse(text="ok"))
    planned = await stage.plan(_inputs(rounds=(earlier,), outcomes=(outcome,), **inputs))
    (call,) = _sent(completer)["rounds"][0]["calls"]
    return call["result"]["value"], planned


# --- §7, §8:1: a search of past episodes ----------------------------------------------------


async def test_a_found_episode_is_its_short_view_with_the_matters_it_belongs_to() -> None:
    """§7:2, §8:1: an E label and its short view; each matter's S label and first line.

    A matter shown again is named by its label alone; a withheld summary says so.
    """
    first = _episode("activation:one", outcome="Booked the dentist.")
    second = _episode("activation:two", outcome="Moved the dentist.")
    trip = MatterShown(story_id="story:dentist", summary_version=2, first_line="The dentist.")
    hidden = MatterShown(story_id="story:hidden", summary_version=1, withheld=True)
    found = EpisodesFound(
        episodes=(
            EpisodeShown(record=first, matters=(trip, hidden)),
            EpisodeShown(record=second, matters=(trip,)),
        ),
        more=True,
    )

    value, planned = await _shown("search_episodes", {"episodes": found})

    one, two = value["episodes"]
    assert one["label"] == "E1"
    assert one["response"] == "Booked the dentist."
    assert one["in_matters"] == [
        {"label": "S1", "summary": "The dentist."},
        {
            "label": "S2",
            "summary": "withheld: this story has a summary, which this audience may not be shown",
        },
    ]
    assert two["label"] == "E2"
    assert two["in_matters"] == ["S1"]
    assert value["page"] == 1
    assert "page 2" in value["more"]
    assert PlanningLabel(label="E1", kind=LabelKind.EPISODE, id="activation:one") in planned.labels
    assert PlanningLabel(label="S1", kind=LabelKind.STORY, id="story:dentist") in planned.labels


async def test_a_search_on_an_unbounded_pass_found_none() -> None:
    """§7:3: on a pass of unbounded audience the search asks for no episode."""
    value, _ = await _shown("search_episodes", {"episodes": EpisodesFound(unbounded=True)})

    assert value == {"page": 1, "episodes": "none"}


async def test_a_marked_summary_a_search_shows_is_outside_content_read() -> None:
    """§6:4, ADR-0303 §3:6: a marked summary shown marks the round's notes."""
    marked = MatterShown(
        story_id="story:venue", summary_version=1, first_line="The venue wrote", outside=True
    )
    found = EpisodesFound(
        episodes=(EpisodeShown(record=_episode("activation:one"), matters=(marked,)),)
    )
    value, planned = await _shown("search_episodes", {"episodes": found})

    (episode,) = value["episodes"]
    assert "summary_outside_content" in episode["in_matters"][0]
    assert planned.round.notes_marked


async def test_an_outside_episode_a_search_shows_is_withheld_and_read() -> None:
    """§6:4, §7:2: an outside episode's input is withheld, and it is outside content read."""
    outside = _episode("activation:mail", parties=UNIDENTIFIED_WORDS, text="the mail's own words")
    found = EpisodesFound(episodes=(EpisodeShown(record=outside),))
    value, planned = await _shown("search_episodes", {"episodes": found})

    assert "the mail's own words" not in json.dumps(value)
    assert value["episodes"][0]["label"] == "E1"
    assert planned.round.notes_marked


# --- §9: the origin's older history ----------------------------------------------------------


async def test_an_older_history_that_cannot_be_read_says_so() -> None:
    """§9:4: a place with no window, or no member to read it, cannot be read here."""
    value, _ = await _shown("read_older_history", {"history": OlderHistory(readable=False)})

    assert value == "this place's older history cannot be read here"


async def test_an_older_history_with_nothing_older_says_so() -> None:
    """§9:4: where the window already showed all its source holds, nothing is older."""
    value, _ = await _shown("read_older_history", {"history": OlderHistory(readable=True)})

    assert value.startswith("nothing older")


async def test_older_items_are_shown_as_the_place_window_shows_items() -> None:
    """§9:3: by author, linked to an episode by label, someone else's withheld."""
    history = OlderHistory(
        readable=True,
        items=(
            PlaceItem(author=PlaceAuthor.USER, text="book it", episode_id="activation:old"),
            PlaceItem(author=PlaceAuthor.OTHER, text="a forward's own words"),
        ),
        more=True,
    )
    value, _ = await _shown("read_older_history", {"history": history})

    mine, forwarded = value["items"]
    assert (mine["from"], mine["text"], mine["episode"]) == ("the user", "book it", "E1")
    assert "a forward's own words" not in json.dumps(value)
    assert forwarded["text"] != "a forward's own words"
    assert "page 2" in value["more"]


async def test_earlier_episodes_of_an_episode_window_are_shown_as_short_views() -> None:
    """§9:2: each earlier episode by its E label and short view."""
    history = OlderHistory(readable=True, episodes=(_episode("activation:old"),))
    value, _ = await _shown("read_older_history", {"history": history})

    (episode,) = value["episodes"]
    assert episode["label"] == "E1"
    assert episode["response"] == "Booked a table earlier."


# --- §10: one episode's full record ---------------------------------------------------------


def _with_calls(record: EpisodicMemory, *entries: RecordedCall) -> EpisodicMemory:
    processing = record.processing_record
    assert processing is not None
    whole = EpisodeProcessingRecord.model_validate(
        {**processing.model_dump(), "call_records": [one.model_dump() for one in entries]}
    )
    return record.model_copy(update={"processing_record": whole})


def _entry(round_id: str, call_id: str, capability: str, **fields: Any) -> RecordedCall:
    return RecordedCall(
        round=round_id,
        call_id=call_id,
        capability=capability,
        effect=False,
        recorded_at=_AT,
        **fields,
    )


def _full_record() -> EpisodicMemory:
    searched = _earlier(
        "round:one",
        notes="looking for the dentist",
        calls=(
            ProposedCall(call_id="c1", name="search_memory", arguments={"query": "dentist"}),
            ProposedCall(call_id="c2", name="read_story", arguments={"story": "S1"}),
        ),
    )
    booked = _earlier(
        "round:two",
        follows="round:one",
        recorded_at=_AT + timedelta(seconds=1),
        notes="booking it",
        calls=(ProposedCall(call_id="c3", name="book", arguments={"slot": "9"}),),
    )
    showed = CallShowed(
        parts=(
            ShownRecord(kind=ShownRecordKind.MEMORY, id="said"),
            ShownRecord(kind=ShownRecordKind.MEMORY, id="forgotten"),
            ShownRecord(kind=ShownRecordKind.EPISODE, id="activation:other"),
        ),
        cut=True,
    )
    return _with_calls(
        _episode("activation:full", rounds=(searched, booked)),
        _entry("round:one", "c1", "search_memory", outcome=CallOutcomeKind.DONE, showed=showed),
        _entry(
            "round:one",
            "c2",
            "read_story",
            outcome=CallOutcomeKind.DONE,
            showed=CallShowed(
                parts=(
                    ShownRecord(kind=ShownRecordKind.STORY, id="story:dentist", summary_version=1),
                )
            ),
        ),
        _entry("round:two", "c3", "book", outcome=CallOutcomeKind.DONE),
    )


def _read(record: EpisodicMemory, *, owner_records: bool = True, **fields: Any) -> EpisodeRead:
    values: dict[str, Any] = {
        "episode_id": record.id,
        "record": record,
        "projection": project_episode(
            record, excerpt_chars=500, owner_records=owner_records, full_view=True
        ),
        "page_size": 20,
    }
    values.update(fields)
    return EpisodeRead(**values)


async def test_a_full_view_shows_its_parts_in_order_and_records_as_held_now() -> None:
    """§10:3, §10:6-§10:7, §10:9: notes and calls in order; records read again.

    A memory forgotten since is left out with nothing said; a story is shown by its label
    and its summary's first line, an episode by its label alone, each as held now; what a
    call showed past the bound, and a call whose entry kept nothing of it, say so.
    """
    record = _full_record()
    said = _remembered("said", MemorySource.USER_ASSERTED, "dentist with Dr Rao")
    read = _read(
        record,
        memories={"said": said},
        stories={
            "story:dentist": MatterShown(
                story_id="story:dentist", summary_version=3, first_line="The dentist, now."
            )
        },
        episodes=frozenset({"activation:other"}),
    )

    value, _ = await _shown("read_episode", {"full": read}, owner_records=True)

    assert value["label"] == "E1"
    assert value["response"] == "Booked a table earlier."
    notes, searched, story, booking_notes, booked = value["parts"]
    assert notes == {"round": 1, "notes": "looking for the dentist"}
    assert searched["capability"] == "search_memory"
    memory, episode, rest = searched["showed"]
    assert (memory["label"], memory["fact"]) == ("M1", "dentist with Dr Rao")
    assert memory["shown"].startswith("as it is held now")
    assert episode == {"label": "E2", "shown": "as it is held now, not as it was then"}
    assert rest == "the rest of what it showed is no longer kept"
    assert "forgotten" not in json.dumps(value)
    assert story["showed"][0]["summary"] == "The dentist, now."
    assert booking_notes["round"] == 2
    assert booked["showed"] == "no longer kept"


async def test_a_full_view_on_a_pass_without_owner_records_shows_no_part() -> None:
    """§10:5: the input, the meaning and how it ended, and nothing of notes or calls."""
    read = _read(_full_record(), owner_records=False)

    value, _ = await _shown("read_episode", {"full": read})

    assert "parts" not in value
    assert "looking for the dentist" not in json.dumps(value)
    assert value["ended"] == "completed: returned"


async def test_a_full_view_comes_in_pages() -> None:
    """§6:6: the call names a page, and the result says whether there are more."""
    read = _read(_full_record(), page_size=2)

    value, _ = await _shown("read_episode", {"full": read}, owner_records=True)

    assert len(value["parts"]) == 2
    assert "page 2" in value["more"]
    later = _read(_full_record(), page_size=2, page=3)
    value, _ = await _shown("read_episode", {"full": later}, owner_records=True)
    assert len(value["parts"]) == 1
    assert "more" not in value


async def test_a_running_episode_and_one_no_longer_kept_say_so() -> None:
    """§10:2, §10:9: an open episode's work is still running; a gone one is not kept."""
    running, _ = await _shown(
        "read_episode", {"full": EpisodeRead(episode_id="activation:live", running=True)}
    )
    gone, _ = await _shown("read_episode", {"full": EpisodeRead(episode_id="activation:gone")})

    assert "still running" in running["full_record"]
    assert gone["full_record"] == "its record is no longer kept"


def test_the_full_view_places_each_call_after_its_rounds_notes() -> None:
    """§10:3: in the order they happened, a round's notes before its calls."""
    projection = project_episode(
        _full_record(), excerpt_chars=500, owner_records=True, full_view=True
    )

    kinds = [type(part).__name__ for part in full_view_parts(projection)]

    assert kinds == [
        "ProjectedRound",
        "ProjectedCall",
        "ProjectedCall",
        "ProjectedRound",
        "ProjectedCall",
    ]


# --- §11:2-§11:4: what a done call's entry keeps ----------------------------------------------


def test_a_search_keeps_the_records_it_showed_by_id_and_nothing_of_the_digests() -> None:
    """§11:2-§11:3: record by record, never a copy; an outside one leaves nothing."""
    said = _remembered("said", MemorySource.USER_ASSERTED, "dentist with Dr Rao")
    turned = _remembered("turned", MemorySource.EXTERNAL, "dentist moved to 3pm")
    outcome = CallOutcome(
        "r", "c1", CallOutcomeKind.DONE, result_id="x", digested=True, records=(said, turned)
    )

    showed = call_showed(outcome, bound=100)

    assert showed == CallShowed(parts=(ShownRecord(kind=ShownRecordKind.MEMORY, id="said"),))
    assert "Dr Rao" not in showed.model_dump_json()


def test_a_digested_result_keeps_nothing_and_a_raw_one_its_own_words() -> None:
    """§11:3: a result held for a digest keeps nothing; one shown whole keeps its words."""
    digested = CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", digested=True)
    raw = CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", result={"free": ["9:00"]})

    assert call_showed(digested, bound=100) == CallShowed()
    assert call_showed(raw, bound=100) == CallShowed(parts=(ShownText(text='{"free": ["9:00"]}'),))


def test_a_story_read_keeps_the_story_by_the_summary_version_it_showed() -> None:
    """§11:2: a story also by its summary version, and the episodes its view showed."""
    view = _story(summary_version=4)
    outcome = CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", story=view)

    showed = call_showed(outcome, bound=1000)

    assert showed is not None
    assert showed.parts[0] == ShownRecord(
        kind=ShownRecordKind.STORY, id=view.story_id, summary_version=4
    )


def test_a_search_of_episodes_keeps_each_episode_and_its_matters() -> None:
    matter = MatterShown(story_id="story:dentist", summary_version=2, first_line="The dentist.")
    found = EpisodesFound(
        episodes=(EpisodeShown(record=_episode("activation:one"), matters=(matter,)),)
    )
    outcome = CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", episodes=found)

    assert call_showed(outcome, bound=1000) == CallShowed(
        parts=(
            ShownRecord(kind=ShownRecordKind.EPISODE, id="activation:one"),
            ShownRecord(kind=ShownRecordKind.STORY, id="story:dentist", summary_version=2),
        )
    )


def test_what_a_call_showed_is_cut_to_the_bound_and_the_cut_carried() -> None:
    """§11:4: past the bound the rest is left out, a text cut to what fits."""
    raw = CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", result="a" * 50)

    showed = call_showed(raw, bound=10)

    assert showed == CallShowed(parts=(ShownText(text='"aaaaaaaaa'),), cut=True)


def test_a_call_not_done_keeps_nothing_of_what_it_showed() -> None:
    """§11:2: only a done call's entry keeps what its result showed."""
    refused = CallOutcome("r", "c1", CallOutcomeKind.REFUSED, reason="no")

    assert call_showed(refused, bound=10) is None


def test_a_full_views_page_keeps_the_episode_and_each_record_shown_again() -> None:
    """§11:2: the episode by reference, then each record its page showed as held now."""
    said = _remembered("said", MemorySource.USER_ASSERTED, "dentist with Dr Rao")
    read = _read(_full_record(), memories={"said": said})
    outcome = CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", full=read)

    showed = call_showed(outcome, bound=1000)

    assert showed == CallShowed(
        parts=(
            ShownRecord(kind=ShownRecordKind.EPISODE, id="activation:full"),
            ShownRecord(kind=ShownRecordKind.MEMORY, id="said"),
        )
    )


# --- §8:2: a story read reads any story planning holds a label for ---------------------------


async def test_a_story_read_names_a_matter_an_episode_search_showed() -> None:
    """§8:2: a matter planning was not shown, named by a search's result, reads by its label.

    Planning's check maps any S label it holds to the story's id, whichever result gave it.
    """
    earlier, _ = _looked("search_episodes", query="dentist")
    matter = MatterShown(story_id="story:dentist", summary_version=1, first_line="The dentist.")
    found = EpisodesFound(
        episodes=(EpisodeShown(record=_episode("activation:one"), matters=(matter,)),)
    )
    outcome = CallOutcome(earlier.id, "c1", CallOutcomeKind.DONE, result_id="r:1", episodes=found)
    read = ProposedCall(call_id="c2", name="read_story", arguments={"story": "S1"})
    stage, _, _ = _stage(RoundResponse(calls=(read,)))

    planned = await stage.plan(
        _inputs(
            rounds=(earlier,),
            outcomes=(outcome,),
            capabilities=(*_TOOLS, READ_STORY, SEARCH_EPISODES),
            label_arguments=LOOK_UP_LABEL_ARGUMENTS,
        )
    )

    (call,) = planned.calls
    assert call.call.arguments["story"] == "story:dentist"


# --- review round 1: what a relayed item, and a full view's matters, show --------------------


async def test_an_older_item_of_a_relayed_input_is_withheld_and_kept_by_nothing() -> None:
    """ADR-0351 §5:7, §9:3, §11:2: withheld as a forward is, and never kept as shown."""
    history = OlderHistory(
        readable=True,
        items=(
            PlaceItem(
                author=PlaceAuthor.USER, text="the dentist's own words", episode_id="activation:r"
            ),
            PlaceItem(author=PlaceAuthor.ASSISTANT, text="noted", episode_id="activation:r"),
        ),
        relayed=frozenset({"activation:r"}),
    )
    value, _ = await _shown("read_older_history", {"history": history})
    outcome = CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", history=history)

    assert "the dentist's own words" not in json.dumps(value)
    assert value["items"][1]["text"] == "noted"
    showed = call_showed(outcome, bound=1000)
    assert showed is not None
    assert "the dentist's own words" not in showed.model_dump_json()
    assert showed.parts == (
        ShownText(text='{"from": "assistant", "text": "noted"}'),
        ShownRecord(kind=ShownRecordKind.EPISODE, id="activation:r"),
    )


async def test_a_full_view_names_the_matters_its_episode_belongs_to() -> None:
    """§8:1: the episode look-up names the episode's matters, as a search does."""
    matter = MatterShown(story_id="story:dentist", summary_version=2, first_line="The dentist.")
    read = _read(_full_record(), matters=(matter,))
    outcome = CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", full=read)

    value, planned = await _shown("read_episode", {"full": read}, owner_records=True)

    assert value["in_matters"] == [{"label": "S1", "summary": "The dentist."}]
    assert PlanningLabel(label="S1", kind=LabelKind.STORY, id="story:dentist") in planned.labels
    showed = call_showed(outcome, bound=1000)
    assert showed is not None
    assert (
        ShownRecord(kind=ShownRecordKind.STORY, id="story:dentist", summary_version=2)
        in showed.parts
    )


def test_a_task_listing_keeps_its_activations_by_episode_and_none_of_their_words() -> None:
    """§11:2, §10:6: a list pull's activations by reference, never their inputs' words."""
    from ai_assistant.orchestration.task_scheduler import (  # noqa: PLC0415
        ActivationEntry,
        TaskListing,
    )

    entry = ActivationEntry(
        activation_id="busy",
        started="09:00",
        place="the hub chat",
        status="running",
        input="My private appointment details",
        outside=False,
    )
    listing = TaskListing(running=(entry,), listed=True)
    outcome = CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", tasks=listing)

    showed = call_showed(outcome, bound=1000)

    assert showed == CallShowed(
        parts=(ShownRecord(kind=ShownRecordKind.EPISODE, id="activation:busy"),)
    )


def test_every_episode_a_stop_or_a_listing_labelled_is_kept() -> None:
    """§11:2: each task's parent, and each activation a stopped one set up still live."""
    from ai_assistant.orchestration.planning import PeerShown  # noqa: PLC0415
    from ai_assistant.orchestration.task_scheduler import (  # noqa: PLC0415
        ActivationEntry,
        StillLive,
        TaskEntry,
        TaskListing,
    )

    def task(task_id: str, parent: str) -> TaskEntry:
        return TaskEntry(
            task_id=task_id,
            state="pending",
            falls_due="tomorrow 09:00",
            instruction="Remind them of the dentist",
            outside=False,
            places=(),
            author="the user",
            parent=parent,
            parent_text="the reminder they asked for",
        )

    child = ActivationEntry(
        activation_id="child",
        started="09:00",
        place="the hub chat",
        status="running",
        input="My private appointment details",
        outside=False,
    )
    stopped = PeerShown(
        activation_id="parent",
        stopped=True,
        set_up=StillLive(read=True, tasks=(task("t1", "planner"),), activations=(child,)),
    )
    listing = TaskListing(scheduled=(task("t2", "asker"),), listed=True)

    for value, expected in (
        ({"peer": stopped}, ("activation:parent", "activation:planner", "activation:child")),
        ({"tasks": listing}, ("activation:asker",)),
    ):
        outcome = CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", **value)
        showed = call_showed(outcome, bound=1000)
        assert showed == CallShowed(
            parts=tuple(ShownRecord(kind=ShownRecordKind.EPISODE, id=one) for one in expected)
        )
        assert "Remind them" not in showed.model_dump_json()
        assert "private appointment" not in showed.model_dump_json()


# --- the probe: what an entry keeps is what the rendering labels (diagnosis at R4) -----------


def _probe_cases() -> list[tuple[str, dict[str, Any]]]:
    """One result of each shape whose rendering names records under labels."""
    from ai_assistant.core.types import (  # noqa: PLC0415
        StoryHeader,
        StoryRelated,
        StoryRelation,
        StoryStanding,
        StoryStandingEpisode,
    )
    from ai_assistant.orchestration.planning import PeerShown  # noqa: PLC0415
    from ai_assistant.orchestration.task_scheduler import (  # noqa: PLC0415
        ActivationEntry,
        StillLive,
        TaskEntry,
        TaskListing,
    )

    def task(task_id: str, parent: str) -> TaskEntry:
        return TaskEntry(
            task_id=task_id,
            state="pending",
            falls_due="tomorrow",
            instruction="remind them",
            outside=False,
            places=(),
            parent=parent,
            parent_text="a reminder",
            author="the user",
        )

    def running(activation_id: str) -> ActivationEntry:
        return ActivationEntry(
            activation_id=activation_id,
            started="09:00",
            place="the hub chat",
            status="running",
            input="their words",
            outside=False,
        )

    standing = StoryStanding(
        story=StoryHeader(story_id="story:trip", created_at=_AT, merged_into=None),
        recent=(
            StoryStandingEpisode(
                activation_id="moment",
                occurred_at=_AT,
                meaning="went",
                in_progress=False,
                outside=False,
            ),
        ),
        related=(
            StoryRelated(relation=StoryRelation.PART_OF, story_id="story:year", member_count=2),
        ),
    )
    view = _story(
        summary_version=3,
        newer=(_episode("activation:newer"),),
        inherited=(
            _short("story:summer", episodes=(_episode("activation:inherited"),), summary_version=2),
        ),
        standing=standing,
    )
    said = _remembered("said", MemorySource.USER_ASSERTED, "dentist with Dr Rao")
    matter = MatterShown(story_id="story:dentist", summary_version=2, first_line="The dentist.")
    return [
        ("read_story", {"story": view}),
        (
            "list_tasks",
            {
                "tasks": TaskListing(
                    running=(running("busy"),),
                    scheduled=(task("t1", "asker"),),
                    recent=(running("done"),),
                    listed=True,
                )
            },
        ),
        (
            "stop_activation",
            {
                "peer": PeerShown(
                    activation_id="parent",
                    stopped=True,
                    set_up=StillLive(
                        tasks=(task("t2", "planner"),), activations=(running("child"),)
                    ),
                )
            },
        ),
        (
            "search_episodes",
            {
                "episodes": EpisodesFound(
                    episodes=(EpisodeShown(record=_episode("activation:one"), matters=(matter,)),)
                )
            },
        ),
        (
            "read_older_history",
            {
                "history": OlderHistory(
                    readable=True,
                    items=(
                        PlaceItem(author=PlaceAuthor.USER, text="hi", episode_id="activation:old"),
                    ),
                    episodes=(_episode("activation:earlier"),),
                )
            },
        ),
        (
            "read_episode",
            {
                "full": _read(
                    _full_record(),
                    memories={"said": said},
                    stories={"story:dentist": matter},
                    episodes=frozenset({"activation:other"}),
                    matters=(
                        MatterShown(story_id="story:in", summary_version=1, first_line="In."),
                    ),
                )
            },
        ),
    ]


async def test_an_entry_keeps_exactly_the_records_its_result_is_shown_under_labels() -> None:
    """§11:2: for every shape, the records kept are those the briefing labels in the result."""
    for name, fields in _probe_cases():
        _, planned = await _shown(name, fields, owner_records=True)
        earlier, _ = _looked(name)
        outcome = CallOutcome(
            earlier.id, "c1", CallOutcomeKind.DONE, result_id="result:1", **fields
        )
        labelled = {
            (one.kind.value, one.id)
            for one in planned.labels
            if one.kind in (LabelKind.MEMORY, LabelKind.EPISODE, LabelKind.STORY)
        }

        showed = call_showed(outcome, bound=10_000)

        assert showed is not None, name
        kept = {(one.kind.value, one.id) for one in showed.parts if isinstance(one, ShownRecord)}
        assert labelled, name
        assert kept == labelled, name
        assert not showed.cut, name


def test_a_story_read_keeps_each_story_by_the_version_its_view_showed() -> None:
    """§11:2: the story read and each larger story's short view, by their versions."""
    view = _story(summary_version=3, inherited=(_short("story:summer", summary_version=2),))
    outcome = CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", story=view)

    showed = call_showed(outcome, bound=1000)

    assert showed is not None
    versions = {
        one.id: one.summary_version
        for one in showed.parts
        if isinstance(one, ShownRecord) and one.kind is ShownRecordKind.STORY
    }
    assert versions == {view.story_id: 3, "story:summer": 2}


def test_a_story_shown_twice_keeps_the_version_it_was_first_shown_at() -> None:
    """§11:2: two episodes of one story, its summary rewritten between their reads."""
    first = MatterShown(story_id="story:dentist", summary_version=1, first_line="Version one.")
    later = MatterShown(story_id="story:dentist", summary_version=2, first_line="Version two.")
    hidden = MatterShown(story_id="story:hidden", summary_version=4, withheld=True)
    found = EpisodesFound(
        episodes=(
            EpisodeShown(record=_episode("activation:one"), matters=(first, hidden)),
            EpisodeShown(record=_episode("activation:two"), matters=(later,)),
        )
    )
    outcome = CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", episodes=found)

    showed = call_showed(outcome, bound=1000)

    assert showed is not None
    stories = [
        (one.id, one.summary_version)
        for one in showed.parts
        if isinstance(one, ShownRecord) and one.kind is ShownRecordKind.STORY
    ]
    assert stories == [("story:dentist", 1), ("story:hidden", None)]


def test_a_matter_planning_held_a_label_for_keeps_no_summary_version() -> None:
    """§8:1, §11:2: a matter already labelled is shown by its label alone, so it showed
    no summary, though its summary moved on since it was labelled."""
    matter = MatterShown(story_id="story:dentist", summary_version=2, first_line="Version two.")
    found = EpisodesFound(
        episodes=(EpisodeShown(record=_episode("activation:one"), matters=(matter,)),)
    )
    outcome = CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="x", episodes=found)

    showed = call_showed(outcome, bound=1000, held=frozenset({"story:dentist"}))

    assert showed == CallShowed(
        parts=(
            ShownRecord(kind=ShownRecordKind.EPISODE, id="activation:one"),
            ShownRecord(kind=ShownRecordKind.STORY, id="story:dentist"),
        )
    )
