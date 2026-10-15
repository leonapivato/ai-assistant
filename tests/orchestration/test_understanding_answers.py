"""ADR-0321 §3: understanding reads whether an input approves an earlier question.

The stage alone, over a scripted model and hand-built windows. The model's readings
(§3:4-§3:11) cannot be unit-tested for quality, so these cases pin what code owns: the
instruction carries the readings, ``answers`` parses, each kind of label that can name
a question resolves to the asking activation with its round or its place and position,
and every path that cannot name exactly one question records **no pointer** (§3:5),
gaining a code-owned unresolved matter so planning can ask which question was meant.
A reply the model reads as approving nothing is a null ``answers``, and records none.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, Final

import pytest
from story_support import AT, CONVERSATION, EVENTS, episode

from ai_assistant.core.types import (
    ActivationRecall,
    AnsweredQuestion,
    AskedCall,
    BeliefBand,
    ChannelContext,
    ChannelContextItem,
    CostBasis,
    Idempotency,
    MemoryKind,
    MemorySource,
    MessageAuthor,
    PlanningRound,
    Provenance,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    Reversibility,
    RiskLevel,
    SemanticMemory,
    ToolCost,
    ToolDefinition,
    TranscriptMessage,
    UnresolvedMatter,
)
from ai_assistant.orchestration import phase_path
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.story_links import Candidates, ShortView
from ai_assistant.orchestration.understanding import (
    SuppliedWindow,
    TranscriptWindow,
    UnderstandingStage,
    _place_of,
)
from ai_assistant.testing import FakeModelProvider, with_phase_declaration

if TYPE_CHECKING:
    from ai_assistant.core.types import ActivationUnderstanding, EpisodicMemory
    from ai_assistant.orchestration.understanding import ChannelWindow

BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
_NO_WINDOW: Final = SuppliedWindow(ChannelContext())
_PLACE: Final = "conversation:c-1"


def _proposal(**fields: Any) -> str:
    return json.dumps({"meaning": "The user says yes.", "meaning_ground": "stated"} | fields)


def _tool() -> ToolDefinition:
    """A booking: it acts in the world and stays in the hub, so it is ruled on unbound."""
    fields: dict[str, object] = {
        "id": "booking",
        "capability": "book_table",
        "description": "Book a table.",
        "risk_level": RiskLevel.HIGH,
        "reversibility": Reversibility.IRREVERSIBLE,
        "side_effecting": True,
        "leaves_hub": False,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NONE,
        "parameters_schema": {
            "type": "object",
            "properties": {"people": {"type": "integer"}},
            "required": ["people"],
        },
    }
    return ToolDefinition(**with_phase_declaration(fields))  # type: ignore[arg-type]  # heterogeneous test kwargs


def _round(round_id: str, *, asked: int = 0, follows: str | None = None) -> PlanningRound:
    """A round whose message asks about ``asked`` calls, parts 1 to ``asked``."""
    return PlanningRound(
        id=round_id,
        follows=follows,
        recorded_at=AT,
        text="Shall I book it?" if asked else "Looking into it.",
        asked=tuple(
            AskedCall(part=part, tool=_tool(), values={"people": 4 + part})
            for part in range(1, asked + 1)
        ),
    )


def _asking(activation_id: str, *rounds: PlanningRound, **fields: Any) -> EpisodicMemory:
    """``activation_id``'s frozen episode, its processing record holding ``rounds``."""
    record = episode(activation_id, **fields)
    processing = record.processing_record
    assert processing is not None
    return record.model_copy(
        update={"processing_record": processing.model_copy(update={"rounds": rounds})}
    )


def _message(
    position: int, text: str, *, author: MessageAuthor = MessageAuthor.USER
) -> TranscriptMessage:
    return TranscriptMessage(
        conversation_id="c-1",
        position=position,
        written_at=AT,
        author=author,
        text=text,
        device_id="phone" if author is MessageAuthor.USER else None,
        message_id=f"m-{position}" if author is MessageAuthor.USER else None,
    )


#: A conversation: the user asked, the assistant (activation a-1) asked back with two
#: exact lines, and an older assistant message nothing records the writer of.
_CHAT: Final = TranscriptWindow(
    CONVERSATION,
    (
        _message(1, "Book a table for six."),
        _message(
            2,
            "Shall I book it?\n1. book_table people=5\n2. book_table people=6",
            author=MessageAuthor.ASSISTANT,
        ),
        _message(3, "An older reply.", author=MessageAuthor.ASSISTANT),
    ),
    input_messages=(),
    links={1: "a-1", 2: "a-1"},
)


async def _understand(
    model: FakeModelProvider,
    *,
    window: ChannelWindow = _NO_WINDOW,
    episodes: tuple[EpisodicMemory, ...] | None = (),
    recalled: tuple[EpisodicMemory | SemanticMemory, ...] = (),
    stories: Candidates | None = None,
) -> ActivationUnderstanding:
    recall = None
    if recalled:
        recall = ActivationRecall(
            outcome=RecallOutcome.FOUND,
            cues=(RecallCue.ACTIVATION_INPUT,),
            items=tuple(_item(record.id, MemoryKind(record.kind)) for record in recalled),
        )
    return await UnderstandingStage(model=model, excerpt_chars=2000).understand(
        "yes",
        channel=CONVERSATION,
        window=window,
        audience=BOUNDED,
        episodes=episodes,
        version=1,
        now=lambda: AT,
        deadline=asyncio.get_running_loop().time() + 60,
        recall=recall,
        recalled=recalled,
        stories=stories,
    )


def _item(record_id: str, kind: MemoryKind) -> RecalledItem:
    return RecalledItem(
        kind=kind,
        id=record_id,
        excerpt="x",
        provenance=RecallProvenance.USER,
        standing=BeliefBand.DERIVED,
        rests_on_recorded_external_content=False,
        found_by=(RecallCue.ACTIVATION_INPUT,),
    )


def _view(story_id: str, *episodes: EpisodicMemory) -> ShortView:
    return ShortView(story_id=story_id, lines=(), notes=(), episodes=episodes)


def _instruction(model: FakeModelProvider) -> str:
    return model.calls[0].messages[0].content


def _matters(understood: ActivationUnderstanding) -> list[str]:
    return [one.matter for one in understood.unresolved]


# --- the instruction (§3:4-§3:11) ------------------------------------------------------


async def test_the_instruction_carries_the_readings_and_the_shape() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model)

    instruction = _instruction(model)
    assert '"answers": null or {"question":' in instruction
    for reading in (
        "a strong hint",  # §3:4
        "A bare yes that could fit more than one question approves nothing",  # §3:5
        "A yes approves every part the question showed: leave `parts` empty",  # §3:6
        "A yes to some parts only names those parts",  # §3:6
        "A no approves nothing",  # §3:7
        "A later yes to the same question still approves it",  # §3:7
        "a conditional yes, which counts as a change",  # §3:8
        "An unclear reply approves nothing",  # §3:9
        "A question does not expire",  # §3:10
        "mixes a yes with a request records the yes",  # §3:11
        "record that in `unresolved`",
        "grants nothing",
    ):
        assert reading in instruction


async def test_a_pass_with_stories_carries_answers_in_its_shape_too() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, stories=Candidates(views=()))

    instruction = _instruction(model)
    assert '"story_labels"' in instruction
    assert '"answers": null or {"question":' in instruction


# --- the place window (§3:2) -------------------------------------------------------------


async def test_a_yes_in_the_place_window_points_at_the_message_by_writer_place_and_position() -> (
    None
):
    model = FakeModelProvider(_proposal(answers={"question": "H2"}))

    understood = await _understand(model, window=_CHAT)

    assert understood.answers == AnsweredQuestion(
        activation_id="a-1", place=_PLACE, position=2, parts=()
    )
    assert understood.unresolved == ()
    assert understood.grounding_dropped == 0


def test_the_place_is_named_as_the_phase_path_names_a_messages_place() -> None:
    """The pointer reaches the delivery record by its place (ADR-0321 §4:4, ADR-0306 §6).

    Two private writers of one name, the phase path's and understanding's, pinned equal.
    """
    assert _place_of(CONVERSATION) == phase_path._place_id(CONVERSATION.instance_id)


async def test_a_partial_yes_records_the_parts_named_ascending_each_once() -> None:
    model = FakeModelProvider(_proposal(answers={"question": "H2", "parts": [2, 1, 2]}))

    understood = await _understand(model, window=_CHAT)

    assert understood.answers is not None
    assert understood.answers.parts == (1, 2)


@pytest.mark.parametrize(
    "label",
    [
        pytest.param("H1", id="the-users-own-message"),
        pytest.param("H3", id="an-assistant-message-nothing-links"),
    ],
)
async def test_an_item_that_is_no_checkable_question_records_no_pointer(label: str) -> None:
    model = FakeModelProvider(_proposal(answers={"question": label}))

    understood = await _understand(model, window=_CHAT)

    assert understood.answers is None
    assert len(model.calls) == 1  # the label resolved: no repair
    assert understood.grounding_dropped == 0
    (matter,) = understood.unresolved
    assert "names no question the assistant asked" in matter.matter


async def test_a_supplied_item_names_the_question_its_episode_asked() -> None:
    record = _asking("a-1", _round("r-1", asked=1))
    window = SuppliedWindow(
        ChannelContext(history=(ChannelContextItem(text="Shall I book it?", item_id=record.id),))
    )
    model = FakeModelProvider(_proposal(answers={"question": "H1"}))

    understood = await _understand(model, window=window, episodes=(record,))

    assert understood.answers == AnsweredQuestion(activation_id="a-1", round="r-1")


# --- the episode window, recall and the story (§3:2) --------------------------------------


async def test_a_yes_to_an_episode_points_at_the_round_whose_message_asked() -> None:
    record = _asking("a-1", _round("r-1"), _round("r-2", asked=2, follows="r-1"))
    model = FakeModelProvider(_proposal(answers={"question": "P1", "parts": [2]}))

    understood = await _understand(model, episodes=(record,))

    assert understood.answers == AnsweredQuestion(activation_id="a-1", round="r-2", parts=(2,))


async def test_a_yes_to_a_question_from_another_conversation_resolves_through_recall() -> None:
    elsewhere = _asking(
        "a-9",
        _round("r-9", asked=1),
        channel=CONVERSATION.model_copy(update={"instance_id": "c-other"}),
    )
    model = FakeModelProvider(_proposal(answers={"question": "M1"}))

    understood = await _understand(model, episodes=(), recalled=(elsewhere,))

    assert understood.answers == AnsweredQuestion(activation_id="a-9", round="r-9")


async def test_a_yes_to_a_question_a_story_shows_resolves_through_its_latest_episodes() -> None:
    asked = _asking("a-1", _round("r-1", asked=1))
    model = FakeModelProvider(_proposal(answers={"question": "S1"}))

    understood = await _understand(
        model, stories=Candidates(views=(_view("story:dinner", episode("a-0"), asked),))
    )

    assert understood.answers == AnsweredQuestion(activation_id="a-1", round="r-1")


async def test_a_mixed_message_records_its_yes_beside_the_request() -> None:
    record = _asking("a-1", _round("r-1", asked=1))
    model = FakeModelProvider(
        _proposal(
            meaning="The user approves the booking and asks for the weather.",
            answers={"question": "P1"},
        )
    )

    understood = await _understand(model, episodes=(record,))

    assert understood.answers == AnsweredQuestion(activation_id="a-1", round="r-1")
    assert understood.meaning == "The user approves the booking and asks for the weather."


# --- what records no pointer (§3:5, §3:7-§3:9) --------------------------------------------


@pytest.mark.parametrize(
    "meaning",
    [
        pytest.param("The user declines the booking.", id="a-no"),
        pytest.param("The user wants the booking for 8 instead.", id="a-change"),
        pytest.param("The user's reply is unclear.", id="an-unclear-reply"),
    ],
)
async def test_a_reply_read_as_approving_nothing_records_no_pointer(meaning: str) -> None:
    record = _asking("a-1", _round("r-1", asked=1))
    model = FakeModelProvider(_proposal(meaning=meaning, answers=None))

    understood = await _understand(model, episodes=(record,))

    assert understood.answers is None
    assert understood.unresolved == ()


async def test_a_bare_yes_read_as_fitting_two_questions_records_no_pointer_and_says_so() -> None:
    first = _asking("a-1", _round("r-1", asked=1))
    second = _asking("a-2", _round("r-2", asked=1))
    matter = {
        "matter": "The yes could answer the booking in P1 or the email in P2.",
        "why_it_matters": "Which action the user approves is unknown.",
    }
    model = FakeModelProvider(_proposal(answers=None, unresolved=[matter]))

    understood = await _understand(model, episodes=(first, second))

    assert understood.answers is None
    assert understood.unresolved == (UnresolvedMatter.model_validate(matter),)


async def test_an_episode_that_asked_twice_records_no_pointer() -> None:
    record = _asking("a-1", _round("r-1", asked=1), _round("r-2", asked=1, follows="r-1"))
    model = FakeModelProvider(_proposal(answers={"question": "P1"}))

    understood = await _understand(model, episodes=(record,))

    assert understood.answers is None
    (matter,) = understood.unresolved
    assert "holds more than one question" in matter.matter


async def test_a_story_whose_episodes_asked_two_questions_records_no_pointer() -> None:
    stories = Candidates(
        views=(
            _view(
                "story:dinner",
                _asking("a-1", _round("r-1", asked=1)),
                _asking("a-2", _round("r-2", asked=1)),
            ),
        )
    )
    model = FakeModelProvider(_proposal(answers={"question": "S1"}))

    understood = await _understand(model, stories=stories)

    assert understood.answers is None
    assert "holds more than one question" in _matters(understood)[0]


async def test_a_bare_yes_with_nothing_to_connect_it_to_records_no_pointer() -> None:
    matter = {
        "matter": "The yes answers no question shown.",
        "why_it_matters": "It is unknown what the user agrees to.",
    }
    model = FakeModelProvider(_proposal(answers=None, unresolved=[matter]))

    understood = await _understand(model, episodes=None)

    assert understood.answers is None
    assert understood.unresolved == (UnresolvedMatter.model_validate(matter),)


@pytest.mark.parametrize(
    ("label", "kwargs"),
    [
        pytest.param("P1", {"episodes": (episode("a-1"),)}, id="an-episode-that-asked-nothing"),
        pytest.param(
            "M1",
            {
                "recalled": (
                    SemanticMemory(
                        id="fact-1",
                        content="Dinner is at eight.",
                        fact="Dinner is at eight.",
                        provenance=Provenance(
                            source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT
                        ),
                    ),
                )
            },
            id="a-recalled-fact",
        ),
        pytest.param(
            "S1",
            {"stories": Candidates(views=(_view("story:quiet", episode("a-1")),))},
            id="a-story-whose-episodes-asked-nothing",
        ),
    ],
)
async def test_a_label_naming_no_question_records_no_pointer(
    label: str, kwargs: dict[str, Any]
) -> None:
    model = FakeModelProvider(_proposal(answers={"question": label}))

    understood = await _understand(model, **kwargs)

    assert understood.answers is None
    assert len(model.calls) == 1
    (matter,) = understood.unresolved
    assert "names no question the assistant asked" in matter.matter


async def test_a_part_the_question_did_not_show_records_no_pointer() -> None:
    record = _asking("a-1", _round("r-1", asked=2))
    model = FakeModelProvider(_proposal(answers={"question": "P1", "parts": [1, 3]}))

    understood = await _understand(model, episodes=(record,))

    assert understood.answers is None
    (matter,) = understood.unresolved
    assert "did not show every part" in matter.matter


async def test_a_label_naming_nothing_is_repaired_once_then_records_no_pointer() -> None:
    record = _asking("a-1", _round("r-1", asked=1))
    bad = _proposal(answers={"question": "P7"})
    model = FakeModelProvider.scripted(bad, bad)

    understood = await _understand(model, episodes=(record,))

    assert len(model.calls) == 2
    assert '"P7"' in model.calls[1].messages[-1].content
    assert understood.answers is None
    assert understood.grounding_dropped == 1
    (matter,) = understood.unresolved
    assert "names no question the assistant asked" in matter.matter


async def test_a_repaired_label_records_the_pointer() -> None:
    record = _asking("a-1", _round("r-1", asked=1))
    model = FakeModelProvider.scripted(
        _proposal(answers={"question": "p1"}), _proposal(answers={"question": "P1"})
    )

    understood = await _understand(model, episodes=(record,))

    assert len(model.calls) == 2
    assert understood.answers == AnsweredQuestion(activation_id="a-1", round="r-1")
    assert understood.grounding_dropped == 0


async def test_a_yes_on_an_event_channel_is_read_like_any_other() -> None:
    """§3:3: whose input approves is authorizing's check; understanding records a reading."""
    record = _asking("a-1", _round("r-1", asked=1))
    model = FakeModelProvider(_proposal(answers={"question": "P1"}))

    understood = await UnderstandingStage(model=model, excerpt_chars=2000).understand(
        "yes",
        channel=EVENTS,
        window=_NO_WINDOW,
        audience=BOUNDED,
        episodes=(record,),
        version=1,
        now=lambda: AT,
        deadline=asyncio.get_running_loop().time() + 60,
    )

    assert understood.answers == AnsweredQuestion(activation_id="a-1", round="r-1")
