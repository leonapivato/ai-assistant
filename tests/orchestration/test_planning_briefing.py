"""Planning's briefing, its short view and its news (ADR-0356 §3, §4, §9; ADR-0359, ADR-0360).

The stage alone, over the canonical ``FakeToolCallingCompleter``: the briefing is the
sections §3:1 names, in order, each empty one with a note giving one of ADR-0353 §8:1's
reasons; an item one section shows is pointed at, never repeated; an episode is shown by
its short view, which lists its notes, each call with an effect and what came of it, and
each input it took in, in the order recorded, and no look-up; an episode recorded before
ADR-0356 shows its messages as ``did``s; its notes past the bound are cut oldest first, the
count said; a pass that may not be shown owner-only records shows no notes and no call; a
withheld item is an empty tag; and the instruction declares no flag and no value. A later
round's news says the time, and what changed of the memories, matters and works the
exchange showed, each once.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from exchange_support import section, tag, tags

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActivationUnderstanding,
    CallOutcomeKind,
    ChannelContext,
    ChannelIdentity,
    ControllerRule,
    ControllerStage,
    DeliveryStatus,
    EpisodeProcessingRecord,
    EpisodicMemory,
    JoinedInput,
    LabelKind,
    Memory,
    MemorySource,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    Profile,
    ProposedCall,
    Provenance,
    RecordedCall,
    RecordedChannelTrigger,
    RecordedDelivery,
    RecordedInputMessage,
    RecordedTextInput,
    RoundResponse,
    StageEntry,
    StageOutcome,
    StoryHeader,
    StorySummary,
    StorySummaryLine,
    StorySummaryState,
    SupportHolder,
    UnderstandingProducer,
    WholeTextReply,
)
from ai_assistant.orchestration.matters import EntryInput, InProgressEntry
from ai_assistant.orchestration.person_block import KeptInMind, PersonBlock
from ai_assistant.orchestration.planning import (
    BRIEFING_HEADINGS,
    NEWS_OPENING,
    NOTE_REASONS,
    NOTHING_NEW,
    PLANNING_PROMPT,
    CallOutcome,
    DigestedEvidence,
    DigestItem,
    PeerShown,
    PersonNow,
    PlaceAuthor,
    PlaceItem,
    PlaceWindow,
    PlanningInputs,
    PlanningStage,
    PlanningStories,
    PlanningStory,
)
from ai_assistant.testing import FakeToolCallingCompleter, default_prompt
from ai_assistant.testing.memories import memory, said_support

pytestmark = pytest.mark.anyio

NOW: Final = datetime(2026, 10, 29, 17, 40, tzinfo=UTC)
LEO: Final = SupportHolder.person(OWNER_PERSON_ID)
CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="chat-1")
TELEGRAM: Final = ChannelIdentity(channel_type="telegram", instance_id="leo")
MAREN: Final = memory("m:maren", "Maren is Leo's partner.", said_support(when=NOW, added_at=NOW))


class _Recorder:
    async def record(self, planning_round: Any, labels: Any, *, questions: Any = None) -> None:
        del planning_round, labels, questions


def _stage(
    *responses: RoundResponse, notes: int = 6
) -> tuple[PlanningStage, FakeToolCallingCompleter]:
    completer = FakeToolCallingCompleter.scripted(*responses, RoundResponse(), RoundResponse())
    ids = iter(f"round:{n}" for n in range(1, 100))
    stage = PlanningStage(
        prompt=default_prompt(PLANNING_PROMPT),
        completer=completer,
        recorder=_Recorder(),
        excerpt_chars=300,
        now=lambda: NOW,
        timezone="Europe/Lisbon",
        new_id=lambda: next(ids),
        short_view_notes=notes,
    )
    return stage, completer


def _trigger(
    text: str,
    *,
    channel: ChannelIdentity | None = CHAT,
    parties: tuple[SupportHolder, ...] | None = (LEO,),
    at: datetime = NOW,
) -> RecordedChannelTrigger:
    return RecordedChannelTrigger(
        target=channel or CHAT,
        channel=channel,
        payload=RecordedTextInput(text=text),
        context=ChannelContext(),
        reply=WholeTextReply(),
        parties=parties,
        messages=(
            (RecordedInputMessage(text=text, sent_at=at, party=parties[0]),)
            if parties and len(parties) == 1
            else ()
        ),
    )


def _understood(
    meaning: str, *, relayed: bool = False, version: int = 1
) -> ActivationUnderstanding:
    return ActivationUnderstanding(
        version=version,
        recorded_at=NOW,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning=meaning,
        relayed=relayed,
    )


def _block(*kept: KeptInMind, **profile: str) -> PersonBlock:
    return PersonBlock(
        person_id=OWNER_PERSON_ID,
        profile=Profile(name="Leo", time_zone="Europe/Lisbon", **profile),
        kept=(KeptInMind(memory=MAREN, pinned=True), *kept),
    )


def _inputs(**fields: Any) -> PlanningInputs:
    values: dict[str, Any] = {
        "activation_id": "now",
        "place": PlaceWindow(takes_message=True, description="the hub chat"),
        "understanding": _understood("Leo asks what is on tonight."),
        "trigger": _trigger("What's on tonight?"),
        "received_at": NOW,
        "person": _block(),
        "person_id": OWNER_PERSON_ID,
        "owner_records": True,
        "stories": PlanningStories(),
    }
    values.update(fields)
    return PlanningInputs(**values)


def _call(call_id: str, name: str, **arguments: Any) -> ProposedCall:
    return ProposedCall(call_id=call_id, name=name, arguments=arguments)


def _episode(  # noqa: PLR0913 — one knob per part a short view shows
    activation: str,
    *,
    text: str = "Book Luigi's for Friday",
    rounds: tuple[PlanningRound, ...] = (),
    calls: tuple[RecordedCall, ...] = (),
    channel: ChannelIdentity = CHAT,
    at: datetime = NOW - timedelta(hours=2),
    joined: tuple[Any, ...] = (),
) -> EpisodicMemory:
    end = StageEntry(
        stage=ControllerStage.END,
        due=ControllerRule.NOTHING_DUE,
        started_at=at + timedelta(minutes=1),
        ended_at=at + timedelta(minutes=1),
        outcome=StageOutcome.DONE,
    )
    record = EpisodeProcessingRecord(
        activation_id=activation,
        started_at=at,
        ended_at=at + timedelta(minutes=1),
        trigger=_trigger(text, channel=channel, at=at),
        status=ProcessingStatus.COMPLETED,
        reason=ProcessingReason.RETURNED,
        understanding=(_understood("Leo asks for a table at Luigi's on Friday."),),
        stages=(end,),
        rounds=rounds,
        call_records=calls,
        joined=joined,
    )
    return EpisodicMemory(
        id=f"activation:{activation}",
        content="",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=at),
        occurred_at=at,
        outcome=None,
        processing_record=record,
    )


def _round(
    round_id: str, *calls: ProposedCall, notes: str | None = None, follows: str | None = None
) -> PlanningRound:
    return PlanningRound(
        id=round_id, follows=follows, recorded_at=NOW - timedelta(hours=2), calls=calls, notes=notes
    )


def _entry(  # noqa: PLR0913 — one knob per fact an entry records
    round_id: str,
    call_id: str,
    capability: str,
    *,
    effect: bool = True,
    outcome: CallOutcomeKind = CallOutcomeKind.DONE,
    delivered: RecordedDelivery | None = None,
) -> RecordedCall:
    return RecordedCall(
        round=round_id,
        call_id=call_id,
        capability=capability,
        effect=effect,
        outcome=outcome,
        delivered=delivered,
        recorded_at=NOW - timedelta(hours=2),
        marked=False,
    )


async def _briefing(given: PlanningInputs) -> str:
    stage, completer = _stage(RoundResponse())
    await stage.plan(given)
    return completer.last_call.exchange.briefing


# --- §3:1, §4:1: every section, in order, each empty one with a note ---------------------


def _headings(briefing: str) -> list[str]:
    return [line for line in briefing.split("\n") if line.startswith("#")]


@pytest.mark.parametrize(
    "given",
    [
        pytest.param(_inputs(), id="a person's chat"),
        pytest.param(
            _inputs(
                person=None,
                person_id=None,
                understanding=None,
                stories=None,
                episodes_read=False,
                place=PlaceWindow(takes_message=False),
                trigger=_trigger(
                    "the hallway door opened",
                    channel=ChannelIdentity(channel_type="informational_event", instance_id="door"),
                    parties=(SupportHolder.source("the door sensor", claimed=False),),
                ),
            ),
            id="an event no person's",
        ),
        pytest.param(
            _inputs(
                stories=PlanningStories(unreadable=True),
                trigger=_trigger("hi", channel=TELEGRAM),
                place=PlaceWindow(takes_message=True),
            ),
            id="the line, the stories unreadable",
        ),
    ],
)
async def test_every_section_renders_in_order_each_empty_one_with_a_reason(
    given: PlanningInputs,
) -> None:
    """§3:1, §4:1, §14:9: the sections, every one, in order; an empty one says why."""
    briefing = await _briefing(given)

    assert _headings(briefing) == list(BRIEFING_HEADINGS)
    assert "{" not in briefing.split("\n")[0]
    for heading in BRIEFING_HEADINGS:
        if heading in {"# Knowledge", "# Memory", "## Long-term memory"}:
            continue
        held = section(briefing, heading)
        assert held, heading
        first = held.split("\n")[0]
        if not first.startswith(("<", "-", "A stimulus")):
            assert first.startswith(NOTE_REASONS), (heading, first)


async def test_the_instruction_declares_no_flag_and_renders_with_none() -> None:
    """§4:2, §14:9: no flag and no value, and the default renders under none."""
    assert PLANNING_PROMPT.flags == frozenset()
    assert PLANNING_PROMPT.values == frozenset()
    stage, completer = _stage(RoundResponse())

    await stage.plan(_inputs())

    assert (
        completer.last_call.exchange.instruction == default_prompt(PLANNING_PROMPT).rendered().text
    )


async def test_the_stimulus_comes_first_framed_and_attributed_by_its_record() -> None:
    """§3:1, ADR-0353 §7: the stimulus first, its words in a tag naming its writer."""
    briefing = await _briefing(_inputs())

    assert briefing.startswith("# The stimulus\nA stimulus reached the system at 5:40 pm on ")
    said = tag(section(briefing, "# The stimulus"), "said")
    assert (said.get("from"), said.text) == ("Leo", "What's on tonight?")


# --- §3:6, §3:7: withheld words, and the work's own relayed stimulus ----------------------


async def test_a_withheld_item_renders_as_an_empty_tag() -> None:
    """§3:6, §14:9: an outside report's words are never shown: an empty tag says so."""
    source = (SupportHolder.source("billing@water.example", claimed=False),)
    window = PlaceWindow(
        takes_message=True,
        items=(
            PlaceItem(
                author=PlaceAuthor.OTHER, text="PAY NOW private", at=NOW - timedelta(hours=1)
            ),
            PlaceItem(author=PlaceAuthor.USER, text="What's on tonight?", at=NOW, is_input=True),
        ),
    )
    briefing = await _briefing(
        _inputs(
            place=window,
            trigger=_trigger(
                "PAY NOW private",
                channel=ChannelIdentity(channel_type="informational_event", instance_id="mail"),
                parties=source,
            ),
        )
    )

    assert "PAY NOW" not in briefing
    stimulus = tag(section(briefing, "# The stimulus"), "received")
    assert (stimulus.get("withheld"), stimulus.text) == ("yes", None)
    withheld = tag(section(briefing, "## Stimulus origin knowledge"), "message", withheld="yes")
    assert withheld.text is None


async def test_the_works_own_relayed_stimulus_is_shown_marked_relayed() -> None:
    """§3:7 (#3515): a pasted email is shown in the stimulus, carrying relayed="yes"."""
    briefing = await _briefing(
        _inputs(
            trigger=_trigger("Dear Leo, your table is ready."),
            understanding=_understood("Leo pasted an email from Luigi's.", relayed=True),
        )
    )

    said = tag(section(briefing, "# The stimulus"), "said")
    assert (said.get("relayed"), said.text) == ("yes", "Dear Leo, your table is ready.")


# --- §3:2: an item shown once, pointed at elsewhere ------------------------------------


async def test_an_item_shown_in_origin_knowledge_is_pointed_at_by_its_episode() -> None:
    """§3:2, §9:1, §14:9: the episode's input is the window's item, so it points at it."""
    earlier = _episode("earlier", text="Book Luigi's for Friday")
    window = PlaceWindow(
        takes_message=True,
        items=(
            PlaceItem(
                author=PlaceAuthor.USER,
                text="Book Luigi's for Friday",
                at=NOW - timedelta(hours=2),
                episode_id=earlier.id,
            ),
            PlaceItem(author=PlaceAuthor.USER, text="What's on tonight?", at=NOW, is_input=True),
        ),
    )

    briefing = await _briefing(_inputs(place=window, episodes=(earlier,)))

    knowledge = section(briefing, "## Stimulus origin knowledge")
    item = tag(knowledge, "message", episode="E1")
    assert item.text == "Book Luigi's for Friday"
    episode = tag(section(briefing, "## Short-term memory"), "episode", label="E1")
    (pointer,) = episode.held("input")
    assert pointer.get("shown_in") == "stimulus origin knowledge"
    assert briefing.count("Book Luigi's for Friday") == 1


# --- §9: the short view -----------------------------------------------------------------


def _booking_episode(**fields: Any) -> EpisodicMemory:
    first = _round(
        "r1",
        _call("c1", "search_memory", query="Luigi's"),
        _call("c2", "book_table", restaurant="Luigi's"),
        notes="Found Luigi's in memory; booking it.",
    )
    second = _round(
        "r2", _call("c3", "text", to="Leo", words="Booked."), notes="Told him.", follows="r1"
    )
    sent = RecordedDelivery(words="Booked.", went=CHAT, status=DeliveryStatus.SENT)
    calls = (
        _entry("r1", "c1", "search_memory", effect=False),
        _entry("r1", "c2", "book_table"),
        _entry("r2", "c3", "text", delivered=sent),
    )
    return _episode("booking", rounds=(first, second), calls=calls, channel=TELEGRAM, **fields)


async def test_a_short_view_lists_notes_and_effectful_calls_in_order_and_no_look_up() -> None:
    """§9:1-§9:2, §14:9: notes, each call with an effect with what came of it, in order."""
    briefing = await _briefing(_inputs(episodes=(_booking_episode(),)))

    episode = tag(section(briefing, "## Short-term memory"), "episode", label="E1")
    parts = [(one.name, one.text) for one in episode.tags if one.name in {"notes", "did"}]
    assert [name for name, _ in parts] == ["notes", "did", "notes", "did"]
    assert parts[0][1] == "Found Luigi's in memory; booking it."
    booked, told = str(parts[1][1]), str(parts[3][1])
    assert booked.startswith("book_table ")
    assert booked.endswith("Done.")
    assert "Booked." in told
    assert "search_memory" not in str(episode.text)


async def test_a_short_view_shows_an_input_taken_in_where_it_was_taken() -> None:
    """§9:1: a ``took_in`` for each input the episode took in, in the order recorded."""
    joined = JoinedInput(
        joined_at=NOW - timedelta(hours=2),
        channel=TELEGRAM,
        messages=(
            RecordedInputMessage(text="make it 3", sent_at=NOW - timedelta(hours=2), party=LEO),
        ),
    )
    record = _booking_episode(joined=(joined,))

    briefing = await _briefing(_inputs(episodes=(record,)))

    episode = tag(section(briefing, "## Short-term memory"), "episode", label="E1")
    took = episode.held("took_in")
    assert took
    assert took[0].tags[0].text == "make it 3"


async def test_an_episode_recorded_before_adr_0356_shows_its_messages_as_dids() -> None:
    """§9:3, §14:9: a round's text, its message then, is shown as a ``did``."""
    old = _round("r1", notes="Looked it up.")
    old = old.model_copy(update={"text": "It opens at nine."})
    record = _episode("old", rounds=(old,), channel=TELEGRAM)

    briefing = await _briefing(_inputs(episodes=(record,)))

    episode = tag(section(briefing, "## Short-term memory"), "episode", label="E1")
    (did,) = episode.held("did")
    assert did.text == "a message: It opens at nine."
    (notes,) = episode.held("notes")
    assert notes.text == "Looked it up."


async def test_notes_past_the_bound_are_cut_oldest_first_with_the_count_said() -> None:
    """§9:4, §14:9: the newest notes are kept, and the view says how many were left out."""
    rounds: list[PlanningRound] = []
    for number in range(1, 5):
        rounds.append(
            _round(
                f"r{number}",
                notes=f"note {number}",
                follows=None if number == 1 else f"r{number - 1}",
            )
        )
    record = _episode("long", rounds=tuple(rounds), channel=TELEGRAM)
    stage, completer = _stage(RoundResponse(), notes=2)

    await stage.plan(_inputs(episodes=(record,)))

    briefing = completer.last_call.exchange.briefing
    episode = tag(section(briefing, "## Short-term memory"), "episode", label="E1")
    assert [one.text for one in episode.held("notes")] == ["note 3", "note 4"]
    assert episode.get("notes_left_out") == "2 older rounds' notes, which an episode look-up reads"


async def test_a_pass_that_may_not_show_owner_records_shows_no_notes_and_no_call() -> None:
    """§9:5, §14:9: input, meaning and ending alone where owner-only records may not show."""
    briefing = await _briefing(_inputs(episodes=(_booking_episode(),), owner_records=False))

    episode = tag(section(briefing, "## Short-term memory"), "episode", label="E1")
    assert episode.held("notes") == []
    assert episode.held("did") == []
    assert episode.held("understood")
    assert episode.get("ended") == "completed, returned"


# --- the news (ADR-0356 §5:5, ADR-0359, ADR-0360) -------------------------------------


async def _next_round(given: PlanningInputs, first: RoundResponse, **changes: Any) -> str:
    """The news of the report after ``first``, with the inputs changed as ``changes`` say."""
    stage, completer = _stage(first)
    planned = await stage.plan(given)
    outcomes = tuple(
        CallOutcome(round_id=planned.round.id, call_id=one.call_id, kind=CallOutcomeKind.DONE)
        for one in first.calls
    )
    later = replace(
        given,
        work=planned.work,
        rounds=(planned.round,),
        labels=planned.labels,
        outcomes=outcomes,
        **changes,
    )
    await stage.plan(later)
    return completer.last_call.exchange.steps[-1].report.news


async def test_a_report_says_its_time_and_that_nothing_changed() -> None:
    """ADR-0360: every report says when it was made; where nothing changed, it says so."""
    news = await _next_round(_inputs(), RoundResponse(calls=(_call("c1", "list_tasks"),)))

    assert news == f"Now: Thursday 29 October 2026, 5:40 pm.\n{NOTHING_NEW}"


async def test_a_memory_forgotten_mid_work_is_named_once_as_forgotten() -> None:
    """#3536, ADR-0359: a memory shown and no longer held is named, and not to be used."""
    given = _inputs()
    stage, completer = _stage(
        RoundResponse(calls=(_call("c1", "list_tasks"),)),
        RoundResponse(calls=(_call("c2", "list_tasks"),)),
    )
    planned = await stage.plan(given)
    second = replace(
        given,
        work=planned.work,
        rounds=(planned.round,),
        labels=planned.labels,
        outcomes=(CallOutcome(round_id=planned.round.id, call_id="c1", kind=CallOutcomeKind.DONE),),
        still_held=frozenset(),
    )
    planned_two = await stage.plan(second)
    news = completer.last_call.exchange.steps[-1].report.news
    third = replace(
        second,
        work=planned_two.work,
        rounds=(planned.round, planned_two.round),
        labels=(*planned.labels, *planned_two.labels),
        outcomes=(
            *second.outcomes,
            CallOutcome(round_id=planned_two.round.id, call_id="c2", kind=CallOutcomeKind.DONE),
        ),
    )
    await stage.plan(third)
    later = completer.last_call.exchange.steps[-1].report.news

    assert "- M1 is forgotten: the system no longer holds it, so do not use it." in news
    assert "forgotten" not in later
    assert "Maren is Leo's partner." in completer.last_call.exchange.briefing


def _story(story_id: str = "story:dinner") -> PlanningStory:
    return PlanningStory(
        story_id=story_id,
        tidied_at=NOW - timedelta(days=1),
        changes=0,
        written=True,
        lines=(StorySummaryLine(text="Dinner at Luigi's on Friday."),),
    )


def _state(
    *lines: str,
    merged_into: str | None = None,
    story_id: str = "story:dinner",
    written_at: datetime = NOW - timedelta(days=1),
) -> StorySummaryState:
    return StorySummaryState(
        story=StoryHeader(
            story_id=story_id, created_at=NOW - timedelta(days=3), merged_into=merged_into
        ),
        summary=StorySummary(
            version=2,
            lines=tuple(StorySummaryLine(text=one) for one in lines),
            written_at=written_at,
            outside=False,
        )
        if lines
        else None,
        pending_notes=(),
        pending_episodes=(),
        as_of=3,
    )


async def test_a_matter_shown_that_has_changed_is_named_with_what_changed() -> None:
    """ADR-0359: a rewritten summary's first line, and a merge by the other's label."""
    given = _inputs(stories=PlanningStories(stories=(_story(),)))
    first = RoundResponse(calls=(_call("c1", "list_tasks"),))

    rewritten = await _next_round(
        given,
        first,
        matters_now={"story:dinner": _state("Dinner moved to Saturday.", written_at=NOW)},
    )
    merged = await _next_round(
        given,
        first,
        matters_now={
            "story:dinner": _state("Dinner at Luigi's on Friday.", merged_into="story:week")
        },
    )
    gone = await _next_round(given, first, matters_now={"story:dinner": None})

    assert (
        "- S1 changed: its summary was rewritten, and now begins: Dinner moved to Saturday."
    ) in rewritten
    assert "- S1 changed: it was merged into S2." in merged
    assert "- S1 is gone: the system no longer holds it." in gone


async def test_other_work_starting_and_ending_is_named() -> None:
    """ADR-0360: a work newly running, with its meaning; one shown running that has ended."""
    running = InProgressEntry(
        activation_id="other",
        channel=TELEGRAM,
        input="book the dentist",
        acted=False,
        parties=(LEO,),
        arrived_at=NOW,
        inputs=(EntryInput(brief="book the dentist", parties=(LEO,)),),
    )
    shown = _inputs(running=(running,))
    first = RoundResponse(calls=(_call("c1", "list_tasks"),))

    started = await _next_round(
        _inputs(),
        first,
        running=(running,),
        meanings={"other": "Leo asks to book the dentist."},
    )
    ended = await _next_round(shown, first, running=(), ended={"other": _booking_episode()})

    assert "- Being worked on separately:" in started
    stimulus = tag(started, "stimulus")
    assert stimulus.get("label") == "E1"
    assert [one.text for one in stimulus.held("understood")] == ["Leo asks to book the dentist."]
    assert "- E1 has ended:" in ended
    episode = tag(ended, "episode")
    assert episode.get("ended") == "completed, returned"
    # ADR-0360 §3:2: its input points at where the exchange showed it.
    (pointer,) = episode.held("input")
    assert pointer.get("shown_in") == "concurrent stimuli"
    assert "Book Luigi's for Friday" not in ended


async def test_a_work_this_works_stop_ended_is_not_named_again() -> None:
    """ADR-0360 §3:4: the stop call's result already reported it."""
    running = InProgressEntry(
        activation_id="other", channel=TELEGRAM, input="x", acted=True, parties=(LEO,)
    )
    given = _inputs(running=(running,))
    stage, completer = _stage(
        RoundResponse(calls=(_call("c1", "stop_activation", activation="E1"),))
    )
    planned = await stage.plan(given)
    stopped = CallOutcome(
        round_id=planned.round.id,
        call_id="c1",
        kind=CallOutcomeKind.DONE,
        result_id="r1",
        peer=PeerShown(activation_id="other", ended=True, stopped=True),
    )
    await stage.plan(
        replace(
            given,
            work=planned.work,
            rounds=(planned.round,),
            labels=planned.labels,
            outcomes=(stopped,),
            running=(),
            ended={"other": _booking_episode()},
        )
    )

    assert "has ended" not in completer.last_call.exchange.steps[-1].report.news


def _now(*pinned: Memory, **profile: str) -> PersonNow:
    return PersonNow(
        profile=Profile(name="Leo", time_zone="Europe/Lisbon", **profile),
        pinned=(MAREN, *pinned),
    )


BEACH: Final = memory(
    "m:beach", "Leo goes to the beach on Sundays.", said_support(when=NOW, added_at=NOW)
)


async def test_a_pin_added_and_a_field_changed_are_named_once() -> None:
    """ADR-0360 §4:1, §8:2: a new pin with its words, a field with its new value."""
    news = await _next_round(
        _inputs(),
        RoundResponse(calls=(_call("c1", "list_tasks"),)),
        person_now=_now(BEACH, address="Lee"),
    )

    assert NEWS_OPENING in news
    assert "- Leo's address is now Lee." in news
    (pinned,) = tags(news, "memory")
    assert (pinned.get("pinned"), pinned.text) == ("yes", "Leo goes to the beach on Sundays.")


async def test_a_pin_removed_is_named_once_no_pin_reaches_its_memory() -> None:
    """ADR-0360 §4:1-§4:2, §8:2: pinned is per memory: while a pin reaches it, it stays."""
    given = _inputs(person=_block(KeptInMind(memory=BEACH, pinned=True)))
    first = RoundResponse(calls=(_call("c1", "list_tasks"),))

    still = await _next_round(given, first, person_now=_now(BEACH))
    gone = await _next_round(given, first, person_now=_now())

    assert still.endswith(NOTHING_NEW)
    assert "- M2 is no longer pinned." in gone


async def test_a_changed_time_zone_is_named_and_the_works_times_stay() -> None:
    """ADR-0360 §2:3, §4:3: the new zone named; this work's times stay in the briefing's."""
    news = await _next_round(
        _inputs(),
        RoundResponse(calls=(_call("c1", "list_tasks"),)),
        person_now=PersonNow(profile=Profile(name="Leo", time_zone="Asia/Tokyo"), pinned=(MAREN,)),
    )

    assert news.startswith("Now: Thursday 29 October 2026, 5:40 pm.")
    assert "- Leo's time zone is now Asia/Tokyo; this work's times stay in Europe/Lisbon." in news


async def test_a_changed_matter_is_named_once_and_only_as_the_audience_may_see_it() -> None:
    """ADR-0359 §5:1-§5:3, §7:2: no line of a summary the pass may not show, and once."""
    given = _inputs(stories=PlanningStories(stories=(_story(),)), owner_records=False)
    first = RoundResponse(calls=(_call("c1", "list_tasks"),))
    changed = {
        "story:dinner": _state(
            "Dinner moved to Saturday.", merged_into="story:week", written_at=NOW
        )
    }

    news = await _next_round(given, first, matters_now=changed)

    assert "- S1 changed: it was merged into another matter; its summary was rewritten." in news
    assert "Saturday" not in news

    stage, completer = _stage(first, RoundResponse(calls=(_call("c2", "list_tasks"),)))
    planned = await stage.plan(given)
    second = replace(
        given,
        work=planned.work,
        rounds=(planned.round,),
        labels=planned.labels,
        outcomes=(CallOutcome(round_id=planned.round.id, call_id="c1", kind=CallOutcomeKind.DONE),),
        matters_now=changed,
    )
    planned_two = await stage.plan(second)
    third = replace(
        second,
        work=planned_two.work,
        rounds=(planned.round, planned_two.round),
        labels=(*planned.labels, *planned_two.labels),
        outcomes=(
            *second.outcomes,
            CallOutcome(round_id=planned_two.round.id, call_id="c2", kind=CallOutcomeKind.DONE),
        ),
    )
    await stage.plan(third)
    steps = completer.last_call.exchange.steps

    assert "S1 changed" in steps[0].report.news
    assert "S1 changed" not in steps[1].report.news


async def _two_reports(given: PlanningInputs, **changes: Any) -> tuple[str, str]:
    """The news of a work's first two reports, ``changes`` made before the first."""
    stage, completer = _stage(
        RoundResponse(calls=(_call("c1", "list_tasks"),)),
        RoundResponse(calls=(_call("c2", "list_tasks"),)),
    )
    planned = await stage.plan(given)
    second = replace(
        given,
        work=planned.work,
        rounds=(planned.round,),
        labels=planned.labels,
        outcomes=(CallOutcome(round_id=planned.round.id, call_id="c1", kind=CallOutcomeKind.DONE),),
        **changes,
    )
    planned_two = await stage.plan(second)
    await stage.plan(
        replace(
            second,
            work=planned_two.work,
            rounds=(planned.round, planned_two.round),
            labels=(*planned.labels, *planned_two.labels),
            outcomes=(
                *second.outcomes,
                CallOutcome(round_id=planned_two.round.id, call_id="c2", kind=CallOutcomeKind.DONE),
            ),
        )
    )
    steps = completer.last_call.exchange.steps
    return steps[0].report.news, steps[1].report.news


async def test_a_started_work_an_ended_one_a_pin_and_a_field_are_each_named_once() -> None:
    """ADR-0360 §8:2: each change is named in the next report, and not again."""
    running = InProgressEntry(
        activation_id="other", channel=TELEGRAM, input="x", acted=False, parties=(LEO,)
    )
    started = await _two_reports(_inputs(), running=(running,), meanings={"other": "Books."})
    ended = await _two_reports(
        _inputs(running=(running,)), running=(), ended={"other": _booking_episode()}
    )
    chosen = await _two_reports(_inputs(), person_now=_now(BEACH, address="Lee"))

    assert "Being worked on separately" in started[0]
    assert started[1].endswith(NOTHING_NEW)
    assert "has ended" in ended[0]
    assert ended[1].endswith(NOTHING_NEW)
    assert "Now pinned" in chosen[0]
    assert "address is now Lee" in chosen[0]
    assert chosen[1].endswith(NOTHING_NEW)


async def test_an_outside_concurrent_stimulus_is_outside_content_read() -> None:
    """ADR-0360 §6, ADR-0306 §4:5: shown, in the briefing or the news, it marks the notes."""
    running = InProgressEntry(
        activation_id="other", channel=TELEGRAM, input=None, acted=False, parties=None, outside=True
    )
    stage, _ = _stage(RoundResponse(text="noted"))

    planned = await stage.plan(_inputs(running=(running,)))

    assert planned.read_outside
    assert planned.round.notes_marked


async def test_a_memory_a_digest_named_is_announced_forgotten() -> None:
    """ADR-0359 §3:1: a memory shown only as a digest's source is re-read like any shown."""
    evidence = DigestedEvidence(
        None, answered=True, items=(DigestItem("a source said so", LabelKind.MEMORY, "m:src"),)
    )
    given = _inputs(evidence=(evidence,))

    news = await _next_round(
        given, RoundResponse(calls=(_call("c1", "list_tasks"),)), still_held=frozenset()
    )

    assert "is forgotten: the system no longer holds it, so do not use it." in news
