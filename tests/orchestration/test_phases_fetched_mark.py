"""A fetched record resting on outside content marks the episode from then on (#3270).

ADR-0223's value for an episode is a disjunction over what its pass was given, so a
record the pass fetched resting on outside content makes it true the moment it is seen.
The pass holds it from there, and ADR-0286 §4:3 carries it into every append after: the
episode is marked on its stored record while the activation still runs, not only by the
freezing write. A restart's close keeps what the episode stored (ADR-0286 §7), so an
activation the hub's stop cut off before its freeze is marked too, and the observer,
which reads the stored record alone, reads it as having read outside content (ADR-0306
§4:5, ADR-0328 §4:3).

Each case has one outside thing, and no digest or outside trigger. In the first two
it is a past episode marked as resting on outside content, which recall's second run
finds and planning is shown, so the mark is set before planning. In the last it is a
marked note a tidy-up took in, which only a story read during acting shows, so the mark
is set from what that read read (#3273).
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from test_engine import AT, Harness
from test_engine_phases import (
    _BOOK,
    _DENTIST,
    _NOTHING_DIGESTED,
    _call,
    _conversation,
    _GatedCompleter,
    _no_episode_window,
    _phases,
    _running_activation,
    _say,
    _settled,
)
from test_planning import _episode as _past_episode
from understanding_support import recall_stage, understanding_stage

from ai_assistant.core.types import (
    EpisodicMemory,
    ProcessingReason,
    ProcessingStatus,
    RoundResponse,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    StorySummaryDraft,
    StorySummaryLine,
)
from ai_assistant.orchestration.activation_writer import ActivationWriter
from ai_assistant.orchestration.authorizer import (
    OutsideGround,
    WorkingRecord,
    read_outside_content,
)
from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage
from ai_assistant.orchestration.understanding import WindowsStage
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakeStoryStore,
    FakeToolCallingCompleter,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import MemoryStore

_PAST: Final = "activation:past"
_SETTLE: Final = 5.0


async def _harness(completer: FakeToolCallingCompleter) -> Harness:
    """A test hub whose store holds one past episode resting on outside content."""
    store = FakeMemoryStore(now=lambda: AT)
    past = _past_episode(_PAST).model_copy(update={"content": f"{_DENTIST} booked for Friday"})
    await store.add(
        past.model_copy(
            update={
                "provenance": past.provenance.model_copy(update={"derived_from_external": True})
            }
        )
    )
    understanding = FakeModelProvider(reply=json.dumps({"understanding": _DENTIST}))
    return Harness(
        understanding=understanding_stage(model=understanding),
        tools=(_BOOK,),
        memory=store,
        windows=WindowsStage(episodes=_no_episode_window),
        recall=recall_stage(store),
        phases=_phases(completer, digests=FakeModelProvider(reply=_NOTHING_DIGESTED)),
    )


async def _read_as_the_observer(memory: MemoryStore, episode: EpisodicMemory) -> list[str]:
    """The grounds that hold over the stored record alone, as the observer reads it.

    No working set outlives its activation, so nothing it held is handed in.
    """
    record = episode.processing_record
    assert record is not None
    grounds: list[OutsideGround] = []
    assert await read_outside_content(
        memory, record.activation_id, working=WorkingRecord(), grounds=grounds
    )
    return [one.ground for one in grounds if one.record == episode.id]


async def test_an_activation_whose_one_ground_is_a_fetched_record_freezes_marked() -> None:
    """ADR-0286 §4:2-§4:3: the frozen episode carries the mark, and reads as outside.

    The round writes no text, so it has no notes to carry a mark of their own (ADR-0356
    §7:2): the fetched record is the one ground.
    """
    completer = FakeToolCallingCompleter.scripted(RoundResponse())
    harness = await _harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when?")
    episode = await _settled(harness, conversation, seeded=frozenset({_PAST}))

    record = episode.processing_record
    assert record is not None
    assert record.recall_second_run is not None
    assert [one.id for one in record.recall_second_run.items] == [_PAST]
    assert record.digests == ()
    assert not any(one.notes_marked for one in record.rounds)
    assert episode.provenance.derived_from_external
    # Its own mark, read off the stored record, is a ground of its own.
    assert await _read_as_the_observer(harness.memory, episode) == ["episode_marked"]


async def test_an_activation_cut_off_after_the_fetch_is_closed_marked() -> None:
    """#3270, ADR-0286 §4:3, §7: the append after the fetch is marked, and the close keeps it.

    The first round books, and the second waits on its model call. The hub's stop
    leaves the episode open, as a crash leaves it, and the next process's close freezes
    it ``interrupted`` / ``hub_stopped`` with the provenance it stored.
    """
    completer = _GatedCompleter(
        RoundResponse(text="Booking it.", calls=(_call("c1", "book", date="2026-10-12"),)),
        RoundResponse(text="Booked."),
        gated=2,
    )
    harness = await _harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "book it")
    await asyncio.wait_for(completer.entered.wait(), _SETTLE)
    activation = await _running_activation(harness)
    address = f"activation:{activation}"
    stored = await harness.memory.get(address)
    assert isinstance(stored, EpisodicMemory)
    assert stored.processing_record is not None
    assert stored.processing_record.is_open
    assert stored.processing_record.rounds
    assert stored.provenance.derived_from_external

    closed = await _closed_by_a_restart(harness, address)
    assert closed.provenance.derived_from_external
    assert await _read_as_the_observer(harness.memory, closed) == ["episode_marked"]
    # The cut-off pass is let go and left to end; what it does then is not this case's.
    completer.gate.set()
    await _ended(harness, conversation)


async def _story_read_harness(completer: FakeToolCallingCompleter) -> Harness:
    """A test hub whose one outside thing is a marked note only a story read shows.

    A clean past episode in the episode window makes its story understanding's one
    candidate, ``S1``, and understanding links the activation into it. The story's one
    note, written by planning and marked, was taken in by a tidy-up whose summary is not
    marked, so the views each round is shown carry no outside content: only the story's
    full view, which a ``read_story`` call reads, shows the note (ADR-0307 §6, #2893).
    """
    memory = FakeMemoryStore(now=lambda: AT)
    await memory.add(_past_episode(_PAST))
    stories = FakeStoryStore(now=lambda: AT)
    trip = (
        await stories.create(
            [StoryMember(kind=StoryMemberKind.ACTIVATION, id="past")], actor=StoryActor.OWNER
        )
    ).story_id
    assert trip is not None
    await stories.append_note(
        trip,
        "The venue says Saturday.",
        author=StoryNoteAuthor.PLANNING,
        written_during="past",
        outside=True,
    )
    state = await stories.current_summary(trip)
    assert state is not None
    draft = StorySummaryDraft(
        lines=(StorySummaryLine(text="A trip to Porto."),),
        took_in_notes=tuple(note.note_id for note in state.pending_notes),
        took_in_episodes=state.pending_episodes,
        outside=False,
    )
    assert (await stories.write_summary(trip, draft, as_of=state.as_of)).refusal is None
    understanding = FakeModelProvider(
        reply=json.dumps({"understanding": "the user asks about the trip"} | {"belongs_to": ["S1"]})
    )
    return Harness(
        understanding=understanding_stage(model=understanding),
        tools=(_BOOK,),
        memory=memory,
        stories=stories,
        story_candidates=StoryCandidates(
            stories=stories, memory=memory, limit=5, lines=3, notes=2, episodes=2
        ),
        story_links=StoryLinksStage(stories=stories),
        phases=_phases(
            completer,
            digests=FakeModelProvider(reply=_NOTHING_DIGESTED),
            stories=stories,
            look_ups=True,
        ),
    )


async def test_an_activation_cut_off_after_a_story_read_of_a_marked_note_is_closed_marked() -> None:
    """#3273, ADR-0286 §4:3, §7: a story read's marked note marks the append after acting.

    The first round reads story ``S1``, and the second waits on its model call, so the
    last append is acting's. Nothing planning was shown before the read rests on outside
    content, so only the read's pages can have marked the pass: the open episode is
    marked, and the next process's close keeps it.
    """
    completer = _GatedCompleter(
        RoundResponse(calls=(_call("c1", "read_story", story="S1"),)),
        RoundResponse(text="Saturday."),
        gated=2,
    )
    harness = await _story_read_harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when is the trip?")
    await asyncio.wait_for(completer.entered.wait(), _SETTLE)
    activation = await _running_activation(harness)
    address = f"activation:{activation}"
    stored = await harness.memory.get(address)
    assert isinstance(stored, EpisodicMemory)
    record = stored.processing_record
    assert record is not None
    assert record.is_open
    # The first round was shown the story, with nothing of it outside content, and
    # nothing else this pass was given rests on any.
    request = json.loads(completer.calls[0].exchange.briefing)
    (shown,) = request["stories"]
    assert shown["summary"] == ["A trip to Porto."]
    assert shown["notes_since_tidied"] == "none"
    (first,) = record.rounds
    assert not first.notes_marked
    assert record.recall_second_run is None
    assert record.digests == ()
    assert stored.provenance.derived_from_external

    closed = await _closed_by_a_restart(harness, address)
    assert closed.provenance.derived_from_external
    assert await _read_as_the_observer(harness.memory, closed) == ["episode_marked"]
    completer.gate.set()
    await _ended(harness, conversation)


async def _closed_by_a_restart(harness: Harness, address: str) -> EpisodicMemory:
    """Close what is open as the next process does, and read the episode at ``address``.

    The episode closes ``interrupted`` / ``hub_stopped``, with the provenance it stored.
    """
    restarted = ActivationWriter(
        memory=harness.memory,
        conversations=harness.conversation_store,
        retention=timedelta(days=30),
        now=lambda: AT,
    )
    await restarted.close_open(stage_limit=64, payload_limit=1 << 20)
    closed = await harness.memory.get(address)
    assert isinstance(closed, EpisodicMemory)
    assert closed.processing_record is not None
    assert (closed.processing_record.status, closed.processing_record.reason) == (
        ProcessingStatus.INTERRUPTED,
        ProcessingReason.HUB_STOPPED,
    )
    return closed


async def _ended(harness: Harness, conversation: str) -> None:
    """Wait for the conversation's activation to end."""
    deadline = asyncio.get_running_loop().time() + _SETTLE
    while True:
        state = await harness.engine.conversation(conversation)
        if state is not None and not state.state.working:
            return
        if asyncio.get_running_loop().time() > deadline:
            msg = "the activation did not end"
            raise AssertionError(msg)
        await asyncio.sleep(0.001)
