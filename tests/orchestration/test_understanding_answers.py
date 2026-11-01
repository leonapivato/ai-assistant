"""ADR-0353 §11, ADR-0361 §8:5: understanding sees no question, whatever a stored round holds.

The stage alone, over a scripted model and hand-built windows. Understanding is shown no
question mark and no ``Q`` label wherever it is shown a message that asked, its stored
round holding the asked calls a round recorded before the question path retired, read as
it was (ADR-0361 §8:6); no window brings a question with a message (§8:5); the reply carries no
answer pointer, and whatever the reply holds no version records one (§11:2, §16:4). A
reply that still holds ``answers`` names a key its shape does not, so it does not parse
and costs the one repair (ADR-0354 §8:3, §10:1); and a ``Q`` label cited in ``cites``
resolves to nothing, as any label the call did not render, and earns the one repair
(§9:10).
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any, Final

import pytest
from story_support import AT, CONVERSATION, episode
from understanding_support import Rendered, TextAsStructured

from ai_assistant.core.types import (
    ActivationRecall,
    AskedCall,
    BeliefBand,
    ChannelContext,
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
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.story_links import Candidates, ShortView
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    SuppliedWindow,
    TranscriptWindow,
    UnderstandingStage,
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


def _proposal(**fields: Any) -> str:
    return json.dumps({"understanding": "The user says yes."} | fields)


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
        model=TextAsStructured(model), excerpt_chars=2000, prompt=_UNDERSTANDING
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


def _rendered(model: FakeModelProvider) -> str:
    """The first call's user message, as sent."""
    return model.calls[0].messages[1].content


def _marks(model: FakeModelProvider) -> list[str]:
    """Every question mark the first call rendered: a ``Q`` label, or a marking attribute."""
    rendered = _rendered(model)
    return re.findall(r"\bQ[0-9]+\b|answer_label|questions_asked|question=", rendered)


# --- no question is marked (ADR-0353 §11:1) ----------------------------------------------


async def test_no_place_understanding_is_shown_a_question_carries_a_mark_or_a_q_label() -> None:
    """§11:1: the place window's question, an episode's, a recalled one's and a story's,
    each brought with its records, render with no mark and no ``Q`` label."""
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
        window=_CHAT,
        episodes=(shown,),
        recalled=(recalled,),
        stories=Candidates(views=(_view("story:trip", told),)),
    )

    assert _marks(model) == []
    # The messages themselves are still shown, as the window brought them.
    assert "Shall I book it?" in _rendered(model)


async def test_an_exchange_shown_in_the_place_window_carries_no_question_of_its_episode() -> None:
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
    )
    model = FakeModelProvider(_proposal())

    await _understand(model, window=window, episodes=(record,))

    first, second = Rendered(_rendered(model)).tags("Stimulus origin knowledge", "message")
    assert (first.text, second.text) == ("Book it.", "Shall I book r-1?")
    assert _marks(model) == []
    assert "And r-2?" not in _rendered(model)


# --- no pointer is recorded (ADR-0353 §11:2, §9:14, §16:4) -------------------------------


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param([{"question": "Q1"}], id="a-pointer-at-a-question-once-marked"),
        pytest.param([{"question": "Q1", "parts": [1, 2]}], id="parts"),
        pytest.param([{"question": "Q9", "parts": "all"}], id="a-malformed-pointer"),
        pytest.param([], id="none"),
        pytest.param("yes", id="not-a-list"),
    ],
)
async def test_no_version_records_an_answer_pointer_whatever_the_reply_holds(
    answers: object,
) -> None:
    """§11:2: ``answers`` is a key the reply shape does not name, so a reply holding it,
    whatever it holds, does not parse and costs the one repair (ADR-0354 §8:3), and no
    version records a pointer."""
    record = _asking("a-1", _round("r-1", asked=2))
    model = FakeModelProvider.scripted(_proposal(answers=answers), _proposal())

    understood = await _understand(model, window=_CHAT, episodes=(record,))

    assert len(model.calls) == 2
    assert understood.meaning == "The user says yes."
    assert "answers" not in understood.model_dump()
    assert understood.grounding_dropped == 0


async def test_a_recalled_fact_carries_no_question() -> None:
    fact = memory("fact-1", "Dinner is at eight.", remembered_support(when=AT, added_at=AT))
    model = FakeModelProvider(_proposal())

    await _understand(model, recalled=(fact,))

    assert _marks(model) == []


# --- a Q label names nothing (ADR-0353 §9:10) --------------------------------------------


async def test_a_q_label_cited_in_cites_names_nothing_and_is_repaired() -> None:
    """No call renders a ``Q`` label, so one cited resolves to nothing, as any unrendered
    label of a form other than ``R``'s, and earns the one repair; the repair statement
    names no ``Q`` sequence."""
    record = _asking("a-1", _round("r-1", asked=1))
    bad = _proposal(cites=["Q1"])
    model = FakeModelProvider.scripted(bad, bad)

    understood = await _understand(model, episodes=(record,))

    assert len(model.calls) == 2
    statement = model.calls[1].messages[-1].content
    assert '"Q1"' in statement
    assert "Q1 (" not in statement
    assert understood.meaning_referents == ()
    assert understood.grounding_dropped == 1
