"""Understanding's always in mind (ADR-0338 §7:2, §7:6-§7:7; ADR-0353 §2, §4).

The stage alone, over a scripted model and a hand-built block. Always in mind says who the
person is to the system, by their name, and three more of their fields, each said as
theirs and a field not set said to be not set (ADR-0353 §4:2, §4:5); the zone is the
situation's alone. It carries the pinned memories and nothing else of the block, under
the first ``M`` labels, with recall's labels following on and a recalled record it shows
rendered there only. A label naming a pinned memory resolves to a ``memory`` referent.
With no block it says the system does not have it, and the template takes no flag
(§8:1, §8:3).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest
from understanding_support import Rendered, TextAsStructured

from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActivationRecall,
    BeliefBand,
    ChannelContext,
    ChannelIdentity,
    DiagnosticKind,
    DiagnosticSource,
    MemoryKind,
    Profile,
    ProfileField,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    SuggestionKind,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.person_block import KeptInMind, PersonBlock, ShownSuggestion
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    SuppliedWindow,
    UnderstandingStage,
)
from ai_assistant.testing import (
    FakeDiagnosticSink,
    FakeModelProvider,
    default_prompt,
)
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from ai_assistant.core.prompts import PromptTemplate
    from ai_assistant.core.types import ActivationUnderstanding, Memory

pytestmark = pytest.mark.anyio

AT: Final = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
EVENTS: Final = ChannelIdentity(channel_type="informational_event", instance_id="calendar")
BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
WINDOW: Final = SuppliedWindow(ChannelContext())

_UNDERSTANDING = default_prompt(UNDERSTANDING_PROMPT)

DIET: Final = memory("m:diet", "Eats no meat.", said_support(when=AT, added_at=AT))
SISTER: Final = memory("m:sister", "Has a sister called Ada.", said_support(when=AT, added_at=AT))
BRIEF: Final = memory("m:brief", "Likes short answers.", said_support(when=AT, added_at=AT))
CANOE: Final = memory("m:canoe", "The canoe holds two.", said_support(when=AT, added_at=AT))

BLOCK: Final = PersonBlock(
    person_id=OWNER_PERSON_ID,
    profile=Profile(name="Robin Vale", address="Robin", language="English"),
    kept=(
        KeptInMind(memory=DIET, pinned=True),
        KeptInMind(memory=SISTER, pinned=True),
        KeptInMind(memory=BRIEF, pinned=False),
    ),
    left_out=2,
    suggestions=(
        ShownSuggestion(
            kind=SuggestionKind.FIELD, recorded_at=AT, field=ProfileField.NAME, value="Rob"
        ),
    ),
)


def _proposal(**fields: Any) -> str:
    return json.dumps({"understanding": "Asks about dinner."} | fields)


def _item(record_id: str) -> RecalledItem:
    return RecalledItem(
        kind=MemoryKind.MEMORY,
        id=record_id,
        excerpt="x",
        provenance=RecallProvenance.USER,
        standing=BeliefBand.ASSERTED,
        rests_on_recorded_external_content=False,
        found_by=(RecallCue.ACTIVATION_INPUT,),
    )


async def _understand(
    model: FakeModelProvider,
    *,
    person: PersonBlock | None,
    recalled: tuple[Memory, ...] = (),
    prompt: PromptTemplate = _UNDERSTANDING,
    diagnostics: FakeDiagnosticSink | None = None,
) -> ActivationUnderstanding:
    recall = None
    if recalled:
        recall = ActivationRecall(
            outcome=RecallOutcome.FOUND,
            cues=(RecallCue.ACTIVATION_INPUT,),
            items=tuple(_item(record.id) for record in recalled),
        )
    stage = UnderstandingStage(
        model=TextAsStructured(model), excerpt_chars=2000, prompt=prompt, diagnostics=diagnostics
    )
    with diagnosed_activation("a-0", clock=lambda: AT):
        return await stage.understand(
            "What should I cook for my sister tonight?",
            channel=EVENTS,
            window=WINDOW,
            audience=BOUNDED,
            episodes=(),
            version=1,
            now=lambda: AT,
            deadline=asyncio.get_running_loop().time() + 60,
            recall=recall,
            recalled=recalled,
            person=person,
        )


def _payload(model: FakeModelProvider, call: int = 0) -> Rendered:
    return Rendered(model.calls[call].messages[1].content)


def _always(model: FakeModelProvider) -> list[str]:
    """Always in mind's lines, as rendered."""
    return _payload(model).section("Always in mind").split("\n")


async def test_no_block_says_the_system_does_not_have_it() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, person=None)

    (note,) = _always(model)
    assert note.startswith("The system does not have it")


async def test_always_in_mind_says_who_the_person_is_and_their_fields_as_their_own() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, person=BLOCK)

    lines = _always(model)
    # ADR-0353 §4:2: named as the block names them; §3:9: the assistant's name not set is
    # said to be not set, never Aether presented as their choice.
    assert lines[:3] == [
        "- Robin Vale is the one the system serves, and has not set a name for it, so it is "
        "called Aether.",
        "- How Robin Vale likes to be addressed: Robin.",
        "- The language Robin Vale writes in: English.",
    ]
    # §4:5: the zone is the situation's alone.
    assert "zone" not in "\n".join(lines)
    situation = _payload(model).section("The situation")
    assert "Robin Vale has not set a time zone" in situation


async def test_the_stimulus_is_attributed_by_its_parties_and_the_person_named() -> None:
    """ADR-0284 §2:3: a connected source's event is the owner's, and never their words."""
    model = FakeModelProvider(_proposal())

    await _understand(model, person=BLOCK)

    (words,) = _payload(model).tags("The stimulus")
    assert (words.name, words.get("from")) == ("received", "informational_event:calendar")
    assert "Robin Vale's last stimulus" in _payload(model).section("The situation")


async def test_understanding_is_shown_the_pinned_memories_and_nothing_else_of_the_block() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, person=BLOCK)

    kept = _payload(model).tags("Always in mind", "memory")
    assert [(one.get("label"), one.get("pinned"), one.text) for one in kept] == [
        ("M1", "yes", "Eats no meat."),
        ("M2", "yes", "Has a sister called Ada."),
    ]
    rendered = _payload(model).section("Always in mind")
    assert "Likes short answers." not in rendered  # a style memory (§7:2)
    assert "Rob." not in rendered  # a suggestion
    assert "left" not in rendered


async def test_a_block_with_no_pins_says_so() -> None:
    model = FakeModelProvider(_proposal())
    block = PersonBlock(person_id=OWNER_PERSON_ID, profile=Profile())

    await _understand(model, person=block)

    lines = _always(model)
    assert lines == [
        "- The owner has not set a name, nor one for the system, so it is called Aether.",
        "- The owner has not set how they like to be addressed.",
        "- The owner has not set the language they write in.",
        "- The owner has pinned nothing for the system to keep in mind.",
    ]


async def test_recalls_labels_follow_the_pins_and_a_pinned_memory_is_rendered_once() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, person=BLOCK, recalled=(SISTER, CANOE))

    payload = _payload(model)
    assert payload.labelled("Always in mind") == ["M1", "M2"]
    assert [(one.get("label"), one.text) for one in payload.tags("Recalled memories")] == [
        ("M3", "The canoe holds two.")
    ]


async def test_everything_recalled_already_shown_above_says_so() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, person=BLOCK, recalled=(DIET,))

    assert _payload(model).section("Recalled memories") == (
        "Nothing is shown: everything recall found is already shown above."
    )


async def test_a_pinned_memorys_label_resolves_to_its_memory_once() -> None:
    model = FakeModelProvider(_proposal(cites=["M2", "M2"]))

    understood = await _understand(model, person=BLOCK)
    [referent] = understood.meaning_referents
    assert (referent.kind, referent.id) == ("memory", "m:sister")
    assert understood.grounding_dropped == 0


async def test_a_label_past_always_in_mind_is_repaired_naming_its_sequence() -> None:
    model = FakeModelProvider.scripted(_proposal(cites=["M3"]), _proposal())

    await _understand(model, person=BLOCK)
    alongside = FakeModelProvider.scripted(_proposal(cites=["M9"]), _proposal())
    await _understand(alongside, person=BLOCK, recalled=(CANOE,))

    named = "(always in mind and the recalled memories)"
    assert f"M1 to M2 {named}" in model.calls[1].messages[-1].content
    assert f"M1 to M3 {named}" in alongside.calls[1].messages[-1].content


async def test_the_template_takes_no_flag_with_a_block_or_without() -> None:
    """ADR-0353 §8:3: one instruction for every pass, its given entry recording no flag."""
    instructions = set()
    for person in (None, BLOCK):
        model = FakeModelProvider(_proposal())
        sink = FakeDiagnosticSink()

        await _understand(model, person=person, diagnostics=sink)

        instructions.add(model.calls[0].messages[0].content)
        (given,) = sink.of(DiagnosticSource.UNDERSTANDING, DiagnosticKind.GIVEN)
        assert given.model_dump(mode="json")["body"]["prompt"]["flags"] == {}
    assert len(instructions) == 1
