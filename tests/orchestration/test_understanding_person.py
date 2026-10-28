"""Understanding's person section (ADR-0338 §7:2, §7:6-§7:7).

The stage alone, over a scripted model and a hand-built block: the section comes first;
it carries the five fields, each said as the person's own choice and a field not set
said to be not set; and it carries the pinned memories and nothing else of the block,
under the first ``M`` labels, with recall's labels following on and a recalled record the
section shows rendered there only. A label naming a pinned memory resolves to a
``memory`` referent, and the template's ``person`` flag is set exactly where the section
renders. With no block, nothing of the person model reaches the call.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest

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
    prompt_from,
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
_FLAG_ECHO: Final = prompt_from(
    UNDERSTANDING_PROMPT,
    "$if recalled\nrecalled\n$end\n$if stories\nstories\n$end\n$if person\nperson\n$end\n",
)

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
        model=model, excerpt_chars=2000, prompt=prompt, diagnostics=diagnostics
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


def _payload(model: FakeModelProvider, call: int = 0) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(model.calls[call].messages[1].content)
    return loaded


async def test_no_block_renders_nothing_of_the_person_model() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, person=None)

    assert "person" not in _payload(model)


async def test_the_person_section_comes_first_with_the_fields_as_the_persons_own() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, person=BLOCK)

    payload = _payload(model)
    assert next(iter(payload)) == "person"
    section = payload["person"]
    assert "own current choice" in section["item"]
    assert "never an instruction" in section["item"]
    profile = section["profile"]
    assert list(profile) == [one.value for one in ProfileField]
    assert profile["name"]["value"] == "Robin Vale"
    assert profile["address"]["value"] == "Robin"
    assert profile["time_zone"]["value"] == "not set"
    # §3:9: an assistant's name not set is not set, never Aether presented as their choice.
    assert profile["assistant_name"]["value"].startswith("not set")
    # §3:11: understanding is shown the language as a hint for reading their input.
    assert "hint for reading what they write" in profile["language"]["is"]


async def test_the_section_names_whom_the_work_is_for_and_leaves_authorship_to_the_input() -> None:
    """ADR-0284 §2:3: a connected source's event is the owner's, and never their words."""
    model = FakeModelProvider(_proposal())

    await _understand(model, person=BLOCK)

    payload = _payload(model)
    assert "working for" in payload["person"]["item"]
    assert "Who wrote the input is said with the input" in payload["person"]["item"]
    assert "never something the user said" in payload["input"]["received_as"]


async def test_understanding_is_shown_the_pinned_memories_and_nothing_else_of_the_block() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, person=BLOCK)

    section = _payload(model)["person"]
    assert [(one["label"], one["fact"]) for one in section["kept_in_mind"]] == [
        ("M1", "Eats no meat."),
        ("M2", "Has a sister called Ada."),
    ]
    assert all(one["not_linkable"] for one in section["kept_in_mind"])
    rendered = json.dumps(section)
    assert "Likes short answers." not in rendered  # a style memory (§7:2)
    assert 'Rob"' not in rendered  # a suggestion
    assert "left_out" not in section


async def test_a_block_with_no_pins_says_so() -> None:
    model = FakeModelProvider(_proposal())
    block = PersonBlock(person_id=OWNER_PERSON_ID, profile=Profile())

    await _understand(model, person=block)

    assert _payload(model)["person"]["kept_in_mind"].startswith("missing:")


async def test_recalls_labels_follow_the_pins_and_a_pinned_memory_is_rendered_once() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, person=BLOCK, recalled=(SISTER, CANOE))

    payload = _payload(model)
    assert [one["label"] for one in payload["person"]["kept_in_mind"]] == ["M1", "M2"]
    assert [(one["label"], one["fact"]) for one in payload["recalled"]] == [
        ("M3", "The canoe holds two.")
    ]


async def test_everything_recalled_already_shown_above_says_so() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, person=BLOCK, recalled=(DIET,))

    assert _payload(model)["recalled"] == "missing: everything recalled is already shown above"


async def test_a_pinned_memorys_label_resolves_to_its_memory_once() -> None:
    model = FakeModelProvider(_proposal(cites=["M2", "M2"]))

    understood = await _understand(model, person=BLOCK)
    [referent] = understood.meaning_referents
    assert (referent.kind, referent.id) == ("memory", "m:sister")
    assert understood.grounding_dropped == 0


async def test_a_label_past_the_person_sections_is_repaired_naming_its_sequence() -> None:
    model = FakeModelProvider.scripted(_proposal(cites=["M3"]), _proposal())

    await _understand(model, person=BLOCK)
    alongside = FakeModelProvider.scripted(_proposal(cites=["M9"]), _proposal())
    await _understand(alongside, person=BLOCK, recalled=(CANOE,))

    assert "M1 to M2 (the person section)" in model.calls[1].messages[-1].content
    assert "M1 to M3 (the person and recalled sections)" in alongside.calls[1].messages[-1].content


async def test_the_person_flag_is_set_exactly_where_the_section_renders() -> None:
    for person, handed in ((None, set()), (BLOCK, {"person"})):
        model = FakeModelProvider(_proposal())
        sink = FakeDiagnosticSink()

        await _understand(model, person=person, prompt=_FLAG_ECHO, diagnostics=sink)

        assert set(model.calls[0].messages[0].content.split("\n")) - {""} == handed
        # ADR-0335 §9:1: the given entry records the flag as the stage computed it.
        (given,) = sink.of(DiagnosticSource.UNDERSTANDING, DiagnosticKind.GIVEN)
        flags = given.model_dump(mode="json")["body"]["prompt"]["flags"]
        assert flags["person"] is (person is not None)
