"""The stages before planning, driven through the engine on the phase path (ADR-0309 §3).

ADR-0309 §3's table keeps rows 1-5 as their own decisions placed them: the conversation,
the windows, recall, understanding and the story links run before planning on the
phases exactly as they do today. ``test_engine_understanding``, ``test_engine_windows``,
``test_engine_story_links`` and ``test_engine_recall_stories`` drove these cases through
the old table, which the switch lane retired; each case here is one of them run with
the phases wired, so it stays pinned once the switch lands. Recall's own cases are in
``test_phases_recall.py``.
"""

from __future__ import annotations

import json
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final

from phases_support import chat_turn, entries, event, phases_harness, processing, written
from story_support import activation, address, episode, failing, memory_of, story
from structlog.testing import capture_logs
from test_engine import AT
from understanding_support import (
    EPISODE_LIMIT,
    STATED_PROPOSAL,
    recall_stage,
    understanding_stage,
)

from ai_assistant.core.types import (
    ControllerRule,
    ControllerStage,
    RecallOutcome,
    StageOutcome,
    StoryActor,
    StoryChange,
    UnderstandingProducer,
)
from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage
from ai_assistant.orchestration.understanding import RecentEpisodes, Windows, WindowsStage
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakeStoryStore,
    FakeToolCallingCompleter,
)
from ai_assistant.testing.tool_calling import DEFAULT_ROUND_TEXT

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from test_engine import Harness

    from ai_assistant.core.types import (
        Message,
        OfferedTool,
        RoundResponse,
        StoryMember,
    )
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.understanding import ChannelWindow

_S = ControllerStage
_R = ControllerRule
_DONE = StageOutcome.DONE

_UTTERANCE: Final = "Is our camping trip still on?"
_TURN: Final = "The canoe is booked for Sunday."
#: The episode window's one episode on recall's cases: recent, and sharing no word
#: recall would keep it by.
_WINDOWED: Final = "Plan the drive to Riverside."
_SEEDED: Final = (address("a-old"), address("a-new"))


def _sent(model: FakeModelProvider, call: int = -1) -> dict[str, Any]:
    """What understanding's call ``call`` was sent."""
    payload: dict[str, Any] = json.loads(model.calls[call].messages[1].content)
    return payload


def _episode_window(model: FakeModelProvider, call: int) -> Any:
    return _sent(model, call)["episode_window"]


def _proposal(**fields: Any) -> str:
    return json.dumps(json.loads(STATED_PROPOSAL) | fields)


def _stories() -> FakeStoryStore:
    ids = count(1)
    return FakeStoryStore(now=lambda: AT, new_id=lambda: f"{next(ids)}")


async def _seeded() -> FakeMemoryStore:
    """A store holding one earlier activation's episode, ``a-1``, at the harness's instant."""
    return await memory_of(episode("a-1", at=AT), now=AT)


async def _recall_seeded() -> FakeMemoryStore:
    """``a-old``, which recall keeps by the turn's words, and ``a-new``, the window's one."""
    return await memory_of(
        episode("a-old", at=AT - timedelta(days=3), text=_TURN),
        episode("a-new", at=AT - timedelta(hours=1), text=_WINDOWED),
        now=AT,
    )


async def _story(stories: FakeStoryStore, activation_id: str) -> str:
    story_id = (await stories.create([activation(activation_id)], actor=StoryActor.OWNER)).story_id
    assert story_id is not None
    return story_id


def _texts(view: dict[str, Any]) -> str:
    return json.dumps(view["latest_episodes"])


async def _members(stories: FakeStoryStore, story_id: str) -> list[tuple[StoryMember, StoryActor]]:
    view = await stories.view(story_id)
    assert view is not None
    return [(entry.member, entry.actor) for entry in view.entries]


class _Order:
    """One list every seam a case orders appends to, so the sequence is one fact."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def model(
        self, name: str, reply: str | Callable[[Sequence[Message]], str]
    ) -> FakeModelProvider:
        def answer(messages: Sequence[Message]) -> str:
            self.seen.append(name)
            return reply(messages) if callable(reply) else reply

        return FakeModelProvider(answer)


class _ForgetsWhatItChose(WindowsStage):
    """A windows stage whose chosen episodes are deleted before understanding fetches them."""

    def __init__(self, memory: FakeMemoryStore) -> None:
        super().__init__(episodes=RecentEpisodes(memory=memory, limit=EPISODE_LIMIT))
        self._memory = memory
        self.chosen: list[tuple[str, ...] | None] = []

    async def assemble(
        self, channel: ChannelWindow, *, audience: TurnSupply, episodes: bool
    ) -> Windows:
        windows = await super().assemble(channel, audience=audience, episodes=episodes)
        self.chosen.append(windows.episode_ids)
        for episode_id in windows.episode_ids or ():
            await self._memory.delete(episode_id)
        return windows


# --- understanding (ADR-0276) ----------------------------------------------------------------


class _OrderedCompleter(FakeToolCallingCompleter):
    """The default planning round, appending ``plan`` to the case's one order first."""

    def __init__(self, order: _Order) -> None:
        super().__init__()
        self._order = order

    async def respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        self._order.seen.append("plan")
        return await super().respond(messages, tools, model=model)


async def test_a_turn_records_version_one_understood_before_it_was_planned() -> None:
    """§5: once the conversation resolved, and before planning's first round."""
    order = _Order()
    model = order.model("understand", STATED_PROPOSAL)
    harness = phases_harness(
        _OrderedCompleter(order), understanding=understanding_stage(model=model)
    )
    _, episode = await chat_turn(harness, _UTTERANCE)
    assert order.seen == ["understand", "plan"]
    assert _sent(model)["input"]["text"] == _UTTERANCE
    record = processing(episode)
    (understood,) = record.understanding
    assert understood.version == 1
    assert understood.producer is UnderstandingProducer.INTERPRETATION
    assert understood.meaning == "The input means what it says."
    assert record.understanding_omitted is None
    assert record.understanding_elided == 0


async def test_an_event_is_understood_before_planning_over_its_supplied_window() -> None:
    order = _Order()
    model = order.model("understand", STATED_PROPOSAL)
    harness = phases_harness(
        _OrderedCompleter(order), understanding=understanding_stage(model=model)
    )
    result, episode = await event(harness)
    assert result.capture.state == "recorded"
    assert order.seen == ["understand", "plan"]
    sent = _sent(model)
    assert sent["input"]["received_as"].startswith("a report received on informational_event")
    assert [item["label"] for item in sent["channel_window"]] == ["H1"]
    record = processing(episode)
    assert [u.version for u in record.understanding] == [1]
    assert record.understanding_omitted is None


async def test_an_event_captured_on_one_channel_is_in_a_conversations_episode_window() -> None:
    """§4: across every channel, attributed from the record as a report received."""
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = phases_harness(understanding=understanding_stage(model=model))
    await event(harness)
    await chat_turn(harness, _UTTERANCE)
    (episode,) = _sent(model)["episode_window"]
    assert episode["label"] == "P1"
    assert episode["input"] == "The thermostat entered eco mode at 18:00."
    assert episode["item"].startswith("a report received on informational_event:thermostat-1")
    assert episode["understood_then"]["meaning"] == "The input means what it says."


async def test_a_second_turn_sees_the_first_under_h_and_not_again_under_p() -> None:
    """§3's same-exchange rule, end to end: the earlier turn is not in the P window (#2899).

    The reader links the first message to the activation that took it in and the reply
    to the one that wrote it (ADR-0303 §7:1), so both are identified by that
    activation's episode: the exchange is rendered once, as its two messages.
    """
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = phases_harness(understanding=understanding_stage(model=model))
    conversation, _ = await chat_turn(harness, "Find a campsite.")
    await chat_turn(harness, _UTTERANCE, conversation=conversation, message_id="m-2")
    sent = _sent(model)
    # The window is the transcript: the first message, then the reply planning wrote.
    asked, replied = sent["channel_window"]
    assert [asked["label"], replied["label"]] == ["H1", "H2"]
    assert (asked["author"], replied["author"]) == ("the user", "the assistant")
    # The first message carries what the episode window would have added about it.
    assert asked["also_in_episode_window"] is True
    assert asked["understood_then"]["meaning"] == "The input means what it says."
    assert replied["also_in_episode_window"] is True
    assert "understood_then" not in replied
    assert sent["episode_window"].startswith("missing")


# --- the windows (ADR-0282) ----------------------------------------------------------------


async def test_understanding_renders_the_episodes_the_windows_stage_chose() -> None:
    memory = FakeMemoryStore(now=lambda: AT)
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = phases_harness(memory=memory, understanding=understanding_stage(model=model))
    await chat_turn(harness, "My dentist is Dr Rao.")
    await chat_turn(harness, "Who is my dentist?")
    (shown,) = _episode_window(model, 1)
    assert shown["label"] == "P1"
    assert shown["input"] == "My dentist is Dr Rao."


async def test_a_window_episode_forgotten_before_understanding_is_not_rendered() -> None:
    """ADR-0282 §2, §5: a fetch returns current versions; a missing id is recorded and
    left out, and is not an error."""
    memory = FakeMemoryStore(now=lambda: AT)
    model = FakeModelProvider(STATED_PROPOSAL)
    await chat_turn(
        phases_harness(memory=memory, understanding=understanding_stage(model=model)),
        "My dentist is Dr Rao.",
    )
    windows = _ForgetsWhatItChose(memory)
    harness = phases_harness(
        memory=memory, understanding=understanding_stage(model=model), windows=windows
    )
    with capture_logs() as logs:
        await chat_turn(harness, "Who is my dentist?")
    (chosen,) = windows.chosen
    assert chosen is not None
    assert len(chosen) == 1
    assert _episode_window(model, 1) == "missing: there are no other recent episodes to show"
    (fetch,) = [
        log for log in logs if log["event"] == "stage_fetch" and log["stage"] == "understanding"
    ]
    assert (fetch["fetched"], fetch["missing"]) == (1, 1)


# --- the story links (ADR-0300 §6) ---------------------------------------------------------


def _linked(
    memory: FakeMemoryStore,
    stories: FakeStoryStore,
    *,
    model: FakeModelProvider,
    wired: bool = True,
) -> Harness:
    return phases_harness(
        memory=memory,
        understanding=understanding_stage(model=model),
        stories=stories,
        story_candidates=StoryCandidates(
            stories=stories, memory=memory, limit=5, lines=3, notes=2, episodes=2
        )
        if wired
        else None,
        story_links=StoryLinksStage(stories=stories) if wired else None,
    )


async def test_a_turn_links_its_activation_into_the_story_it_named() -> None:
    stories = _stories()
    trip = (await stories.create([activation("a-1")], actor=StoryActor.OWNER)).story_id
    assert trip is not None
    model = FakeModelProvider(_proposal(belongs_to=["S1"]))
    harness = _linked(await _seeded(), stories, model=model)

    _, episode = await chat_turn(harness, _TURN)

    record = processing(episode)
    assert entries(record)[2:4] == [
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
        (_S.STORY_LINKS, _R.STORY_LINKS_UNRECORDED, _DONE),
    ]
    assert record.understanding[-1].story_links == (story(trip),)
    now = activation(record.activation_id)
    assert (now, StoryActor.UNDERSTANDING) in await _members(stories, trip)
    log = await stories.log(trip)
    assert log is not None
    assert (log.lines[-1].change, log.lines[-1].trigger) == (
        StoryChange.ADDED,
        record.activation_id,
    )
    # §6:5: the candidate was shown under its label.
    (shown,) = json.loads(model.calls[0].messages[1].content)["stories"]
    assert shown["label"] == "S1"


async def test_an_earlier_episode_in_no_story_starts_one_with_the_activation() -> None:
    stories = _stories()
    harness = _linked(
        await _seeded(), stories, model=FakeModelProvider(_proposal(belongs_to=["P1"]))
    )

    _, episode = await chat_turn(harness, _TURN)

    record = processing(episode)
    assert record.understanding[-1].story_links == (activation("a-1"),)
    (started,) = (await stories.stories()).stories
    assert await _members(stories, started.story_id) == [
        (activation("a-1"), StoryActor.UNDERSTANDING),
        (activation(record.activation_id), StoryActor.UNDERSTANDING),
    ]


async def test_a_follow_up_links_the_conversation_s_earlier_turn_through_its_h_label() -> None:
    """ADR-0301 §1: the earlier turn reaches the call only as H1, and still starts a story."""
    stories = _stories()
    model = FakeModelProvider.scripted(STATED_PROPOSAL, _proposal(belongs_to=["H1"]))
    harness = _linked(FakeMemoryStore(now=lambda: AT), stories, model=model)
    conversation, first = await chat_turn(harness, "Plan the camping trip.")
    earlier = processing(first).activation_id

    _, episode = await chat_turn(harness, _TURN, conversation=conversation, message_id="m-2")

    item, *_ = json.loads(model.calls[1].messages[1].content)["channel_window"]
    assert item["label"] == "H1"
    record = processing(episode)
    assert record.understanding[-1].story_links == (activation(earlier),)
    (started,) = (await stories.stories()).stories
    assert await _members(stories, started.story_id) == [
        (activation(earlier), StoryActor.UNDERSTANDING),
        (activation(record.activation_id), StoryActor.UNDERSTANDING),
    ]


async def test_an_input_linked_to_nothing_still_records_the_decision() -> None:
    stories = _stories()
    harness = _linked(
        FakeMemoryStore(now=lambda: AT), stories, model=FakeModelProvider(STATED_PROPOSAL)
    )

    _, episode = await chat_turn(harness, _TURN)

    record = processing(episode)
    assert (_S.STORY_LINKS, _R.STORY_LINKS_UNRECORDED, _DONE) in entries(record)
    assert record.understanding[-1].story_links == ()
    assert (await stories.stories()).stories == ()


async def test_a_deployment_without_the_story_pieces_runs_as_before() -> None:
    stories = _stories()
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _linked(FakeMemoryStore(now=lambda: AT), stories, model=model, wired=False)

    _, episode = await chat_turn(harness, _TURN)

    assert _S.STORY_LINKS not in [entry.stage for entry in processing(episode).stages]
    assert "stories" not in json.loads(model.calls[0].messages[1].content)


async def test_an_event_s_links_are_recorded_before_planning() -> None:
    stories = _stories()
    trip = (await stories.create([activation("a-1")], actor=StoryActor.OWNER)).story_id
    assert trip is not None
    harness = _linked(
        await _seeded(), stories, model=FakeModelProvider(_proposal(belongs_to=["S1"]))
    )

    _, episode = await event(harness)

    record = processing(episode)
    assert entries(record)[:4] == [
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE),
        (_S.STORY_LINKS, _R.STORY_LINKS_UNRECORDED, _DONE),
        (_S.PLANNING, _R.FIRST_ROUND_DUE, _DONE),
    ]
    assert (activation(record.activation_id), StoryActor.UNDERSTANDING) in await _members(
        stories, trip
    )


async def test_a_story_store_failure_in_the_stage_is_tolerated_and_the_turn_goes_on() -> None:
    stories = _stories()
    trip = (await stories.create([activation("a-1")], actor=StoryActor.OWNER)).story_id
    assert trip is not None
    stories = failing(stories, "link")
    harness = _linked(
        await _seeded(), stories, model=FakeModelProvider(_proposal(belongs_to=["S1"]))
    )

    conversation, episode = await chat_turn(harness, _TURN)

    assert [one.text for one in await written(harness, conversation)][-1] == DEFAULT_ROUND_TEXT
    record = processing(episode)
    assert (_S.STORY_LINKS, _R.STORY_LINKS_UNRECORDED, StageOutcome.FAILED) in entries(record)
    assert entries(record)[-1] == (_S.END, _R.NOTHING_DUE, _DONE)


async def test_unreadable_candidates_say_so_and_understanding_proceeds() -> None:
    stories = failing(_stories(), "stories_of")
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _linked(await _seeded(), stories, model=model)

    _, episode = await chat_turn(harness, _TURN)

    section = json.loads(model.calls[0].messages[1].content)["stories"]
    assert section == "missing: the stories could not be read, so none is shown"
    assert (_S.STORY_LINKS, _R.STORY_LINKS_UNRECORDED, _DONE) in entries(processing(episode))


# --- recall's stories (ADR-0300 §7) ----------------------------------------------------------


def _recalling(
    memory: FakeMemoryStore,
    stories: FakeStoryStore,
    *,
    model: FakeModelProvider,
    recall_stories: FakeStoryStore | None = None,
) -> Harness:
    """The engine over one memory store and one story store, recall's unless named."""
    return phases_harness(
        memory=memory,
        understanding=understanding_stage(model=model),
        windows=WindowsStage(episodes=RecentEpisodes(memory=memory, limit=1)),
        recall=recall_stage(memory, stories=stories if recall_stories is None else recall_stories),
        stories=stories,
        story_candidates=StoryCandidates(
            stories=stories, memory=memory, limit=5, lines=3, notes=2, episodes=2
        ),
        story_links=StoryLinksStage(stories=stories),
    )


def _shown(model: FakeModelProvider) -> Any:
    return json.loads(model.calls[0].messages[1].content)


async def test_recalls_story_is_recorded_and_joins_the_candidates_after_the_windows() -> None:
    stories = _stories()
    windowed = await _story(stories, "a-new")
    recalled = await _story(stories, "a-old")
    model = FakeModelProvider(_proposal(belongs_to=["S2"]))
    harness = _recalling(await _recall_seeded(), stories, model=model)

    _, episode = await chat_turn(harness, _TURN)

    record = processing(episode)
    assert episode.id not in _SEEDED
    assert record.recall is not None
    assert record.recall.outcome is RecallOutcome.FOUND
    kept = {item.id: item.stories for item in record.recall.items}
    # §7:2: the kept episode carries its story; the window's episode is not recalled.
    assert kept[address("a-old")] == (recalled,)
    assert address("a-new") not in kept
    # §6:1: the window's story first, then recall's.
    first, second = _shown(model)["stories"]
    assert (first["label"], second["label"]) == ("S1", "S2")
    assert _WINDOWED in _texts(first)
    assert _TURN in _texts(second)
    # The S2 label resolves to recall's story, and the stage links the activation there.
    assert record.understanding[-1].story_links == (story(recalled),)
    view = await stories.view(recalled)
    assert view is not None
    assert activation(record.activation_id) in [entry.member for entry in view.entries]
    assert windowed != recalled


async def test_a_story_already_a_candidate_through_the_window_is_not_repeated() -> None:
    stories = _stories()
    both = (
        await stories.create([activation("a-new"), activation("a-old")], actor=StoryActor.OWNER)
    ).story_id
    assert both is not None
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _recalling(await _recall_seeded(), stories, model=model)

    _, episode = await chat_turn(harness, _TURN)

    record = processing(episode)
    assert record.recall is not None
    assert {item.id: item.stories for item in record.recall.items}[address("a-old")] == (both,)
    (only,) = _shown(model)["stories"]
    assert only["label"] == "S1"


async def test_a_story_store_failure_in_recall_is_tolerated_and_the_turn_goes_on() -> None:
    stories = _stories()
    await _story(stories, "a-old")
    model = FakeModelProvider(STATED_PROPOSAL)
    # Recall's own reads of the story store fail; the candidates' still answer.
    harness = _recalling(
        await _recall_seeded(),
        stories,
        model=model,
        recall_stories=failing(_stories(), "stories_of"),
    )

    conversation, episode = await chat_turn(harness, _TURN)

    assert [one.text for one in await written(harness, conversation)][-1] == DEFAULT_ROUND_TEXT
    record = processing(episode)
    assert record.recall is not None
    assert record.recall.outcome is RecallOutcome.FAILED
    stages = entries(record)
    assert (_S.RECALL, _R.NOT_RECALLED, StageOutcome.FAILED) in stages
    assert (_S.UNDERSTANDING, _R.NOT_UNDERSTOOD, _DONE) in stages
    # Recall's failure brings no candidate, and the window's episode is in no story.
    assert _shown(model)["stories"] == (
        "missing: none of the earlier episodes shown belongs to a story"
    )
