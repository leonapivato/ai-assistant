"""ADR-0321 §3 and ADR-0322: understanding reads which earlier questions an input approves.

The stage alone, over a scripted model and hand-built windows. The model's readings
(ADR-0321 §3:4-§3:11, ADR-0322 §2:2-§2:4) cannot be unit-tested for quality, so these
cases pin what code owns. Every message that is a question is marked, with its parts and
a ``Q`` label of its own, wherever understanding is shown it, and a message that asked
only in words is not (ADR-0322 §4). Each pointer names a question by its ``Q`` label
alone and resolves on its own, to the asking activation and round (§2:6, §4:5). A
pointer that cannot be recorded, or two naming one question, record nothing and gain a
code-owned unresolved matter, while the others stand (§2:6-§2:7). A reply the model
reads as approving nothing records no pointer.
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
    Memory,
    MemoryKind,
    MessageAuthor,
    PlanningRound,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    TranscriptMessage,
    UnresolvedMatter,
)
from ai_assistant.orchestration import phase_path
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.story_links import Candidates, ShortView
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    AskedIn,
    SuppliedWindow,
    TranscriptWindow,
    UnderstandingStage,
    _place_of,
)
from ai_assistant.testing import FakeModelProvider, default_prompt, with_phase_declaration
from ai_assistant.testing.memories import memory, remembered_support

#: Understanding's shipped template, as the composition root hands it the stage.
_UNDERSTANDING = default_prompt(UNDERSTANDING_PROMPT)

if TYPE_CHECKING:
    from ai_assistant.core.types import ActivationUnderstanding, EpisodicMemory
    from ai_assistant.orchestration.understanding import ChannelWindow

BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
_NO_WINDOW: Final = SuppliedWindow(ChannelContext())
_PLACE: Final = "conversation:c-1"

#: The matters the stage adds for a pointer it does not record.
_NO_SUCH_QUESTION: Final = "is not the Q label of a question the assistant asked"
_NO_SUCH_PART: Final = "did not show every part"
_TWICE: Final = "one earlier question twice over"
_FITS_SEVERAL: Final = "a yes that does not say which question it approves"


def _proposal(**fields: Any) -> str:
    return json.dumps({"meaning": "The user says yes.", "meaning_ground": "stated"} | fields)


def _pointers(*questions: str | tuple[str, list[int]]) -> list[dict[str, Any]]:
    """``answers`` naming each question, with the parts where a pair gives them."""
    return [
        {"question": one} if isinstance(one, str) else {"question": one[0], "parts": one[1]}
        for one in questions
    ]


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


def _round(
    round_id: str, *, asked: int = 0, follows: str | None = None, text: str | None = None
) -> PlanningRound:
    """A round whose message asks about ``asked`` calls, parts 1 to ``asked``."""
    return PlanningRound(
        id=round_id,
        follows=follows,
        recorded_at=AT,
        text=text if text is not None else (f"Shall I book {round_id}?" if asked else "Looking."),
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


#: A conversation: the user asked; the assistant (activation a-1, round r-1) asked back
#: with two exact lines, which the reader brought as a question of two parts; the
#: assistant then asked in words only, in a message a-1 also wrote; and an older
#: assistant message nothing records the writer of.
_CHAT: Final = TranscriptWindow(
    CONVERSATION,
    (
        _message(1, "Book a table for six."),
        _message(
            2,
            "Shall I book it?\n1. book_table people=5\n2. book_table people=6",
            author=MessageAuthor.ASSISTANT,
        ),
        _message(3, "Or would you rather I booked it for later?", author=MessageAuthor.ASSISTANT),
        _message(4, "An older reply.", author=MessageAuthor.ASSISTANT),
    ),
    input_messages=(),
    links={1: "a-1", 2: "a-1", 3: "a-1"},
    asked={2: AskedIn(round="r-1", parts=(1, 2))},
)


async def _understand(  # noqa: PLR0913 — one knob per section a case renders
    model: FakeModelProvider,
    *,
    window: ChannelWindow = _NO_WINDOW,
    episodes: tuple[EpisodicMemory, ...] | None = (),
    recalled: tuple[EpisodicMemory | Memory, ...] = (),
    stories: Candidates | None = None,
    channel: Any = CONVERSATION,
) -> ActivationUnderstanding:
    recall = None
    if recalled:
        recall = ActivationRecall(
            outcome=RecallOutcome.FOUND,
            cues=(RecallCue.ACTIVATION_INPUT,),
            items=tuple(_item(record.id, MemoryKind(record.kind)) for record in recalled),
        )
    return await UnderstandingStage(
        model=model, excerpt_chars=2000, prompt=_UNDERSTANDING
    ).understand(
        "yes",
        channel=channel,
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


def _shown(model: FakeModelProvider) -> dict[str, Any]:
    shown: dict[str, Any] = json.loads(model.calls[0].messages[-1].content)
    return shown


def _marks(model: FakeModelProvider) -> list[tuple[str, str, list[int]]]:
    """Every question mark the first call rendered, in order.

    As ``(Q label, label of the item that shows it, parts)``: a place-window message's
    own mark is ``question``, an episode's are ``questions_asked``, each giving its ``Q``
    label as ``answer_label``; a story's episodes take no label, so the item that shows
    them is the story.
    """
    found: list[tuple[str, str, list[int]]] = []

    def walk(value: object, holder: str) -> None:
        if isinstance(value, dict):
            asked = value.get("answer_label")
            if isinstance(asked, str):
                found.append((asked, holder, value["parts"]))
                return
            label = value.get("label")
            if isinstance(label, str):
                holder = label
            for one in value.values():
                walk(one, holder)
        elif isinstance(value, list):
            for one in value:
                walk(one, holder)

    walk(_shown(model), "")
    return found


def _matters(understood: ActivationUnderstanding) -> list[str]:
    return [one.matter for one in understood.unresolved]


# --- the mark's Q label (ADR-0322 §4, #3081) -------------------------------------------


async def test_a_mark_gives_its_q_label_as_answer_label_never_as_label() -> None:
    """#3081: ``label`` keys the items a reference may cite; a mark's Q label is not one."""
    record = _asking("a-7", _round("r-7", asked=1))
    model = FakeModelProvider(_proposal())

    await _understand(model, window=_CHAT, episodes=(record,))

    labels: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if isinstance(label := value.get("label"), str):
                labels.append(label)
            for one in value.values():
                walk(one)
        elif isinstance(value, list):
            for one in value:
                walk(one)

    walk(_shown(model))
    assert _marks(model) == [("Q1", "H2", [1, 2]), ("Q2", "P1", [1])]
    assert labels == ["H1", "H2", "H3", "H4", "P1"]


# --- the marks and the Q labels (ADR-0322 §4:1-§4:4) -------------------------------------


async def test_a_question_in_the_place_window_carries_its_mark_on_its_message() -> None:
    """§4:1-§4:2: the parts the reader brought, and a Q label; prose and others carry none."""
    model = FakeModelProvider(_proposal())

    await _understand(model, window=_CHAT)

    items = _shown(model)["channel_window"]
    assert [item.get("question") for item in items] == [
        None,
        {"answer_label": "Q1", "parts": [1, 2]},
        None,
        None,
    ]
    assert _marks(model) == [("Q1", "H2", [1, 2])]


async def test_a_question_an_episode_asked_is_marked_on_its_round() -> None:
    """§4:2-§4:3: the round's message, its parts, its label; a round that asked nothing none."""
    record = _asking("a-1", _round("r-1"), _round("r-2", asked=2, follows="r-1"))
    model = FakeModelProvider(_proposal())

    await _understand(model, episodes=(record,))

    (rendered,) = _shown(model)["episode_window"]
    assert rendered["questions_asked"] == [
        {
            "answer_label": "Q1",
            "parts": [1, 2],
            "message": "Shall I book r-2?",
            "message_cut_to_first_chars": False,
        }
    ]


async def test_an_episode_that_asked_nothing_shows_no_questions() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, episodes=(_asking("a-1", _round("r-1")),))

    (rendered,) = _shown(model)["episode_window"]
    assert "questions_asked" not in rendered


async def test_a_round_that_asked_in_no_text_carries_no_mark() -> None:
    """§4:3: a mark rides only where the projection carries the round's message."""
    model = FakeModelProvider(_proposal())

    await _understand(model, episodes=(_asking("a-1", _round("r-1", asked=1, text=" ")),))

    assert _marks(model) == []


async def test_every_place_understanding_is_shown_a_question_marks_it_in_order() -> None:
    """§4:2, §4:4: the place window, the episode window, recall and a story, Q1 onward."""
    window = TranscriptWindow(
        CONVERSATION,
        (_message(1, "Shall I book it?", author=MessageAuthor.ASSISTANT),),
        links={1: "a-1"},
        asked={1: AskedIn(round="r-1", parts=(1,))},
    )
    shown = _asking("a-2", _round("r-2", asked=1))
    recalled = _asking(
        "a-3",
        _round("r-3", asked=1),
        _round("r-4", asked=2, follows="r-3"),
        channel=CONVERSATION.model_copy(update={"instance_id": "c-other"}),
    )
    told = _asking("a-5", _round("r-5", asked=1))
    model = FakeModelProvider(_proposal())

    await _understand(
        model,
        window=window,
        episodes=(shown,),
        recalled=(recalled,),
        stories=Candidates(views=(_view("story:trip", told),)),
    )

    assert _marks(model) == [
        ("Q1", "H1", [1]),
        ("Q2", "P1", [1]),
        ("Q3", "M1", [1]),
        ("Q4", "M1", [1, 2]),
        ("Q5", "S1", [1]),
    ]


async def test_a_question_rendered_in_two_places_keeps_one_label() -> None:
    """§4:4: the question a message is, shown again in a story's latest episode."""
    asking = _asking("a-1", _round("r-1", asked=1))
    window = TranscriptWindow(
        CONVERSATION,
        (_message(1, "Shall I book r-1?", author=MessageAuthor.ASSISTANT),),
        links={1: "a-1"},
        asked={1: AskedIn(round="r-1", parts=(1,))},
    )
    model = FakeModelProvider(_proposal(answers=_pointers("Q1")))

    understood = await _understand(
        model, window=window, stories=Candidates(views=(_view("story:dinner", asking),))
    )

    assert _marks(model) == [("Q1", "H1", [1]), ("Q1", "S1", [1])]
    assert understood.answers == (
        AnsweredQuestion(activation_id="a-1", round="r-1", place=_PLACE, position=1),
    )


async def test_an_exchange_shown_in_the_place_window_leaves_its_question_to_the_message() -> None:
    """§4:4: the episode one exchange with the window shows only questions no message carries."""
    record = _asking(
        "a-1", _round("r-1", asked=1), _round("r-2", asked=1, follows="r-1", text="And r-2?")
    )
    window = TranscriptWindow(
        CONVERSATION,
        (
            _message(1, "Book it."),
            _message(2, "Shall I book r-1?", author=MessageAuthor.ASSISTANT),
        ),
        links={1: "a-1", 2: "a-1"},
        asked={2: AskedIn(round="r-1", parts=(1,))},
    )
    model = FakeModelProvider(_proposal())

    await _understand(model, window=window, episodes=(record,))

    first, second = _shown(model)["channel_window"]
    assert [one["message"] for one in first["questions_asked"]] == ["And r-2?"]
    assert second["question"] == {"answer_label": "Q2", "parts": [1]}
    assert _marks(model) == [("Q1", "H1", [1]), ("Q2", "H2", [1])]


async def test_a_supplied_item_one_exchange_with_an_episode_shows_its_questions() -> None:
    record = _asking("a-1", _round("r-1", asked=1))
    window = SuppliedWindow(
        ChannelContext(history=(ChannelContextItem(text="Shall I book it?", item_id=record.id),))
    )
    model = FakeModelProvider(_proposal(answers=_pointers("Q1")))

    understood = await _understand(model, window=window, episodes=(record,))

    assert _marks(model) == [("Q1", "H1", [1])]
    assert understood.answers == (AnsweredQuestion(activation_id="a-1", round="r-1"),)


# --- the pointers (ADR-0322 §2:1, §2:6, §4:5) --------------------------------------------


async def test_a_yes_to_a_place_window_question_points_at_its_round_and_message() -> None:
    model = FakeModelProvider(_proposal(answers=_pointers("Q1")))

    understood = await _understand(model, window=_CHAT)

    assert understood.answers == (
        AnsweredQuestion(activation_id="a-1", round="r-1", place=_PLACE, position=2),
    )
    assert understood.unresolved == ()
    assert understood.grounding_dropped == 0


def test_the_place_is_named_as_the_phase_path_names_a_messages_place() -> None:
    """The pointer reaches the delivery record by its place (ADR-0321 §4:4, ADR-0306 §6).

    Two private writers of one name, the phase path's and understanding's, pinned equal.
    """
    assert _place_of(CONVERSATION) == phase_path._place_id(CONVERSATION.instance_id)


async def test_a_partial_yes_records_the_parts_named_ascending_each_once() -> None:
    model = FakeModelProvider(_proposal(answers=_pointers(("Q1", [2, 1, 2]))))

    understood = await _understand(model, window=_CHAT)

    (answer,) = understood.answers
    assert answer.parts == (1, 2)


async def test_both_records_one_pointer_per_question_each_resolved_on_its_own() -> None:
    """§2:1-§2:2: "both", given to two waiting questions, one seen only through a story."""
    asked = _asking("a-2", _round("r-2", asked=1))
    model = FakeModelProvider(_proposal(answers=_pointers("Q2", "Q1")))

    understood = await _understand(
        model, window=_CHAT, stories=Candidates(views=(_view("story:dinner", asked),))
    )

    assert understood.answers == (
        AnsweredQuestion(activation_id="a-2", round="r-2"),
        AnsweredQuestion(activation_id="a-1", round="r-1", place=_PLACE, position=2),
    )
    assert understood.unresolved == ()


async def test_two_questions_one_story_shows_take_a_label_each() -> None:
    """§4:4: a story's episodes take no label, so each question takes its own."""
    stories = Candidates(
        views=(
            _view(
                "story:dinner",
                _asking("a-1", _round("r-1", asked=1)),
                _asking("a-2", _round("r-2", asked=1)),
            ),
        )
    )
    model = FakeModelProvider(_proposal(answers=_pointers("Q2")))

    understood = await _understand(model, stories=stories)

    assert _marks(model) == [("Q1", "S1", [1]), ("Q2", "S1", [1])]
    assert understood.answers == (AnsweredQuestion(activation_id="a-2", round="r-2"),)


async def test_a_yes_to_a_question_from_another_conversation_resolves_through_recall() -> None:
    elsewhere = _asking(
        "a-9",
        _round("r-9", asked=1),
        channel=CONVERSATION.model_copy(update={"instance_id": "c-other"}),
    )
    model = FakeModelProvider(_proposal(answers=_pointers("Q1")))

    understood = await _understand(model, episodes=(), recalled=(elsewhere,))

    assert understood.answers == (AnsweredQuestion(activation_id="a-9", round="r-9"),)


async def test_a_mixed_message_records_its_yes_beside_the_request() -> None:
    record = _asking("a-1", _round("r-1", asked=1))
    model = FakeModelProvider(
        _proposal(
            meaning="The user approves the booking and asks for the weather.",
            answers=_pointers("Q1"),
        )
    )

    understood = await _understand(model, episodes=(record,))

    assert understood.answers == (AnsweredQuestion(activation_id="a-1", round="r-1"),)
    assert understood.meaning == "The user approves the booking and asks for the weather."


async def test_a_yes_on_an_event_channel_is_read_like_any_other() -> None:
    """ADR-0321 §3:3: whose input approves is authorizing's check; this is a reading."""
    record = _asking("a-1", _round("r-1", asked=1))
    model = FakeModelProvider(_proposal(answers=_pointers("Q1")))

    understood = await _understand(model, episodes=(record,), channel=EVENTS)

    assert understood.answers == (AnsweredQuestion(activation_id="a-1", round="r-1"),)


# --- what records no pointer (ADR-0322 §2:6-§2:7, §4:5; ADR-0321 §3:5, §3:7-§3:9) -------


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
    model = FakeModelProvider(_proposal(meaning=meaning, answers=[]))

    understood = await _understand(model, episodes=(record,))

    assert understood.answers == ()
    assert understood.unresolved == ()


async def test_a_bare_yes_read_as_fitting_two_questions_records_none_and_says_so() -> None:
    first = _asking("a-1", _round("r-1", asked=1))
    second = _asking("a-2", _round("r-2", asked=1))
    matter = {
        "matter": "The yes could answer the booking in Q1 or the one in Q2.",
        "why_it_matters": "Which action the user approves is unknown.",
    }
    model = FakeModelProvider(_proposal(unresolved=[matter]))

    understood = await _understand(model, episodes=(first, second))

    assert understood.answers == ()
    assert understood.unresolved == (UnresolvedMatter.model_validate(matter),)


#: #3080's two questions: the 27th's, on its message in the place window (Q1), whose
#: words promise both nights above the 27th's line alone, and the 26th's, asked in
#: another conversation and shown only through recall (Q2).
_PROMISED_BOTH: Final = TranscriptWindow(
    CONVERSATION,
    (
        _message(1, "Can you also book the 27th? As well as the 26th, not instead."),
        _message(
            2,
            "Shall I book the 27th? Say the word and I'll book both.\nbook_table people=5",
            author=MessageAuthor.ASSISTANT,
        ),
    ),
    input_messages=(),
    links={1: "a-27", 2: "a-27"},
    asked={2: AskedIn(round="r-27", parts=(1,))},
)
_THE_26TH: Final = (
    _asking(
        "a-26",
        _round("r-26", asked=1),
        channel=CONVERSATION.model_copy(update={"instance_id": "c-other"}),
    ),
)
_ITS_OWN_MATTER: Final = {
    "matter": "The yes could approve Q1 (the 27th, whose message promised both) or Q2.",
    "why_it_matters": "Which booking the user approves is unknown.",
}


def _matter(text: str, why: str = "Which booking is meant is unknown.") -> dict[str, str]:
    return {"matter": text, "why_it_matters": why}


@pytest.mark.parametrize(
    "guess",
    [
        pytest.param(("Q1",), id="the-question-whose-words-promised-both"),
        pytest.param(("Q2",), id="the-other-question"),
        pytest.param(("Q1", "Q2"), id="both"),
    ],
)
async def test_a_yes_whose_own_matter_names_two_questions_records_none_whatever_it_points_at(
    guess: tuple[str, ...],
) -> None:
    """ADR-0321 §3:5, ADR-0322 §2:3, #3080: the reading says it fits several, and points.

    Code acts on the reading's own matter: no pointer is recorded, and a code-owned
    matter after the model's own says why, so planning asks which was meant.
    """
    model = FakeModelProvider(_proposal(answers=_pointers(*guess), unresolved=[_ITS_OWN_MATTER]))

    understood = await _understand(model, window=_PROMISED_BOTH, recalled=_THE_26TH)

    assert [label for label, _, _ in _marks(model)] == ["Q1", "Q2"]
    assert understood.answers == ()
    own, code = _matters(understood)
    assert own == _ITS_OWN_MATTER["matter"]
    assert _FITS_SEVERAL in code
    assert understood.grounding_dropped == 0


@pytest.mark.parametrize(
    "matters",
    [
        pytest.param([_matter("Q1 or Q2?")], id="in-one-matters-words"),
        pytest.param([_matter("Unsure.", why="It could be Q2, or Q1.")], id="in-why-it-matters"),
        pytest.param([_matter("Maybe Q1."), _matter("Maybe Q2.")], id="across-two-matters"),
        pytest.param([_matter("(Q1/Q2), or both")], id="set-off-by-punctuation"),
    ],
)
async def test_two_rendered_q_labels_anywhere_in_the_models_matters_record_none(
    matters: list[dict[str, str]],
) -> None:
    model = FakeModelProvider(_proposal(answers=_pointers("Q1"), unresolved=matters))

    understood = await _understand(model, window=_PROMISED_BOTH, recalled=_THE_26TH)

    assert understood.answers == ()
    assert _FITS_SEVERAL in _matters(understood)[-1]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("The yes fits Q1 alone.", id="one-q-label"),
        pytest.param("Q1, and Q1 again.", id="one-q-label-twice"),
        pytest.param("Q1 or Q3.", id="a-q-label-the-call-did-not-render"),
        pytest.param("Q1 or Q01.", id="a-padded-index"),
        pytest.param("Q1 or q2.", id="another-case"),
        pytest.param("Q1 or Q2x.", id="part-of-a-longer-token"),
        pytest.param("Q1 or FAQ2.", id="the-end-of-a-longer-token"),
        pytest.param("The yes could fit P1 or P2.", id="other-labels"),
    ],
)
async def test_a_matter_naming_fewer_than_two_rendered_q_labels_leaves_the_pointer(
    text: str,
) -> None:
    """Only a ``Q`` label the call rendered, exactly and standing alone, counts."""
    model = FakeModelProvider(_proposal(answers=_pointers("Q1"), unresolved=[_matter(text)]))

    understood = await _understand(model, window=_PROMISED_BOTH, recalled=_THE_26TH)

    assert understood.answers == (
        AnsweredQuestion(activation_id="a-27", round="r-27", place=_PLACE, position=2),
    )
    assert _matters(understood) == [text]


async def test_the_matter_for_a_bare_yes_replaces_the_reasons_its_pointers_failed() -> None:
    """No pointer is recorded, so the one matter says why, and labels still count."""
    model = FakeModelProvider(
        _proposal(answers=_pointers("H2", ("Q1", [9]), "Q2"), unresolved=[_ITS_OWN_MATTER])
    )

    understood = await _understand(model, window=_PROMISED_BOTH, recalled=_THE_26TH)

    assert understood.answers == ()
    own, code = _matters(understood)
    assert own == _ITS_OWN_MATTER["matter"]
    assert _FITS_SEVERAL in code
    assert understood.grounding_dropped == 1


async def test_a_bare_yes_to_the_one_question_shown_still_points_at_it() -> None:
    """ADR-0321 §3:5 is about several questions: with one rendered, the reading stands."""
    model = FakeModelProvider(_proposal(answers=_pointers("Q1"), unresolved=[_ITS_OWN_MATTER]))

    understood = await _understand(model, window=_PROMISED_BOTH)

    assert understood.answers == (
        AnsweredQuestion(activation_id="a-27", round="r-27", place=_PLACE, position=2),
    )
    assert _matters(understood) == [_ITS_OWN_MATTER["matter"]]


async def test_both_given_to_the_two_questions_records_both() -> None:
    """ADR-0322 §2:2: "both" says which, so the reading leaves nothing unresolved."""
    model = FakeModelProvider(_proposal(answers=_pointers("Q1", "Q2")))

    understood = await _understand(model, window=_PROMISED_BOTH, recalled=_THE_26TH)

    assert understood.answers == (
        AnsweredQuestion(activation_id="a-27", round="r-27", place=_PLACE, position=2),
        AnsweredQuestion(activation_id="a-26", round="r-26"),
    )
    assert understood.unresolved == ()


async def test_a_reply_to_one_questions_message_points_at_it_beside_another() -> None:
    """A reply to one question's message says which, even with another question shown."""
    window = TranscriptWindow(
        CONVERSATION,
        _PROMISED_BOTH.messages,
        input_messages=(
            TranscriptMessage(
                conversation_id="c-1",
                position=3,
                written_at=AT,
                author=MessageAuthor.USER,
                text="Yes, go ahead.",
                device_id="phone",
                message_id="m-3",
                replies_to=2,
            ),
        ),
        links=_PROMISED_BOTH.links,
        asked=_PROMISED_BOTH.asked,
    )
    model = FakeModelProvider(_proposal(answers=_pointers("Q1")))

    understood = await _understand(model, window=window, recalled=_THE_26TH)

    assert _shown(model)["input"]["messages"][0]["replies_to"] == 2
    assert understood.answers == (
        AnsweredQuestion(activation_id="a-27", round="r-27", place=_PLACE, position=2),
    )
    assert understood.unresolved == ()


@pytest.mark.parametrize(
    "label",
    [
        pytest.param("H2", id="the-label-of-the-marked-message-itself"),
        pytest.param("H3", id="a-message-that-asked-only-in-words"),
        pytest.param("H1", id="the-users-own-message"),
        pytest.param("P1", id="an-episode"),
        pytest.param("Q9", id="a-q-label-the-call-did-not-render"),
    ],
)
async def test_a_pointer_naming_anything_but_a_rendered_q_label_records_nothing(
    label: str,
) -> None:
    """§4:5: a yes never lands on an unmarked message, and is never repaired onto one."""
    model = FakeModelProvider(_proposal(answers=_pointers(label)))

    understood = await _understand(model, window=_CHAT, episodes=(_asking("a-7", _round("r-7")),))

    assert understood.answers == ()
    assert len(model.calls) == 1, "a pointer's label is not repaired"
    assert understood.grounding_dropped == 1
    (matter,) = _matters(understood)
    assert _NO_SUCH_QUESTION in matter


async def test_a_pointer_not_recorded_leaves_the_others_standing() -> None:
    """§2:6: each pointer resolves on its own."""
    model = FakeModelProvider(_proposal(answers=_pointers("H3", "Q1")))

    understood = await _understand(model, window=_CHAT)

    assert understood.answers == (
        AnsweredQuestion(activation_id="a-1", round="r-1", place=_PLACE, position=2),
    )
    (matter,) = _matters(understood)
    assert _NO_SUCH_QUESTION in matter


async def test_two_pointers_naming_one_question_record_neither() -> None:
    """§2:7: neither is recorded, the matter says so once, and the other pointer stands."""
    other = _asking("a-2", _round("r-2", asked=1))
    model = FakeModelProvider(_proposal(answers=_pointers("Q1", ("Q1", [2]), "Q2")))

    understood = await _understand(model, window=_CHAT, episodes=(other,))

    assert understood.answers == (AnsweredQuestion(activation_id="a-2", round="r-2"),)
    (matter,) = _matters(understood)
    assert _TWICE in matter


async def test_a_part_the_question_did_not_show_records_that_pointer_alone_not() -> None:
    other = _asking("a-2", _round("r-2", asked=1))
    model = FakeModelProvider(_proposal(answers=_pointers(("Q1", [1, 3]), "Q2")))

    understood = await _understand(model, window=_CHAT, episodes=(other,))

    assert understood.answers == (AnsweredQuestion(activation_id="a-2", round="r-2"),)
    (matter,) = _matters(understood)
    assert _NO_SUCH_PART in matter


async def test_each_reason_a_pointer_is_not_recorded_is_said_once() -> None:
    model = FakeModelProvider(_proposal(answers=_pointers("H1", "H3", ("Q1", [9]))))

    understood = await _understand(model, window=_CHAT)

    assert understood.answers == ()
    assert len(_matters(understood)) == 2
    assert _NO_SUCH_QUESTION in _matters(understood)[0]
    assert _NO_SUCH_PART in _matters(understood)[1]


async def test_a_bare_yes_with_nothing_to_connect_it_to_records_no_pointer() -> None:
    matter = {
        "matter": "The yes answers no question shown.",
        "why_it_matters": "It is unknown what the user agrees to.",
    }
    model = FakeModelProvider(_proposal(unresolved=[matter]))

    understood = await _understand(model, episodes=None)

    assert understood.answers == ()
    assert understood.unresolved == (UnresolvedMatter.model_validate(matter),)


async def test_a_recalled_fact_carries_no_question() -> None:
    fact = memory("fact-1", "Dinner is at eight.", remembered_support(when=AT, added_at=AT))
    model = FakeModelProvider(_proposal())

    await _understand(model, recalled=(fact,))

    assert _marks(model) == []


# --- a Q label names no referent (ADR-0322 §4:6) -----------------------------------------


async def test_a_q_label_cited_outside_a_pointer_names_nothing_and_is_repaired() -> None:
    """§4:6: cited as a referent it resolves to nothing, as any unrendered label does."""
    record = _asking("a-1", _round("r-1", asked=1))
    bad = _proposal(meaning_ground="supplied", meaning_labels=["Q1"], answers=_pointers("Q1"))
    model = FakeModelProvider.scripted(bad, bad)

    understood = await _understand(model, episodes=(record,))

    assert len(model.calls) == 2
    statement = model.calls[1].messages[-1].content
    assert '"Q1"' in statement
    assert "Q1 (the questions, cited only in `answers`)" in statement
    assert understood.meaning_referents == ()
    assert understood.grounding_dropped == 1
    # The pointer itself stands: a Q label is what a pointer names.
    assert understood.answers == (AnsweredQuestion(activation_id="a-1", round="r-1"),)
