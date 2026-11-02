"""Planning's person block (ADR-0338 §7:3, §7:6-§7:9, §3:9-§3:10, §5:6).

The stage alone, over the canonical ``FakeToolCallingCompleter`` and a hand-built block:
the block comes first in the request, before everything that changes from round to
round; it carries the five fields as the person's own choices, a field not set said to
be not set and a zone not set shown beside the hub's default; the whole kept-in-mind
slot, each memory by its label and why it is kept, with the count left out; and the
suggestions, each marked as one. A found memory the block shows is not shown again
under recalled memories (ADR-0356 §3:2). The instruction declares no flag (ADR-0356
§4:2), so it renders the same text whatever the block holds. With no block, nothing of
the person model is shown.

The block renders under the briefing's "always in mind" heading (ADR-0356 §3:2), in
tagged text, read here through ``exchange_support``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest
from exchange_support import section, tag, tags

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    LabelKind,
    PlanningRound,
    Profile,
    ProfileField,
    RoundResponse,
    SuggestionKind,
)
from ai_assistant.orchestration.person_block import KeptInMind, PersonBlock, ShownSuggestion
from ai_assistant.orchestration.planning import (
    PLANNING_PROMPT,
    PlaceWindow,
    PlanningInputs,
    PlanningStage,
)
from ai_assistant.testing import FakeToolCallingCompleter, default_prompt, prompt_from
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from ai_assistant.core.prompts import PromptTemplate
    from ai_assistant.core.types import PlanningLabel

pytestmark = pytest.mark.anyio

AT: Final = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
CHAT: Final = PlaceWindow(takes_message=True, description="the hub chat")

INSTRUCTION: Final = "an instruction of the test's own"
FLAG_ECHO: Final = prompt_from(PLANNING_PROMPT, f"{INSTRUCTION}\n")

DIET: Final = memory("m:diet", "Eats no meat.", said_support(when=AT, added_at=AT))
BRIEF: Final = memory("m:brief", "Likes short answers.", said_support(when=AT, added_at=AT))
SISTER: Final = memory("m:sister", "Has a sister called Ada.", said_support(when=AT, added_at=AT))
NEW: Final = memory("m:new", "Walks to work.", said_support(when=AT, added_at=AT))

BLOCK: Final = PersonBlock(
    person_id=OWNER_PERSON_ID,
    profile=Profile(name="Robin Vale", address="Robin"),
    kept=(KeptInMind(memory=DIET, pinned=True), KeptInMind(memory=BRIEF, pinned=False)),
    left_out=1,
    suggestions=(
        ShownSuggestion(kind=SuggestionKind.PIN, recorded_at=AT, memory=SISTER),
        ShownSuggestion(
            kind=SuggestionKind.FIELD,
            recorded_at=AT,
            field=ProfileField.LANGUAGE,
            value="Português",
        ),
    ),
)


class _Recorder:
    def __init__(self) -> None:
        self.recorded: list[tuple[PlanningRound, tuple[PlanningLabel, ...]]] = []

    async def record(
        self,
        planning_round: PlanningRound,
        labels: tuple[PlanningLabel, ...],
        *,
        questions: object = None,
    ) -> None:
        del questions
        self.recorded.append((planning_round, labels))


def _stage(
    prompt: PromptTemplate | None = None,
) -> tuple[PlanningStage, FakeToolCallingCompleter, _Recorder]:
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="Hello, Robin."))
    recorder = _Recorder()
    stage = PlanningStage(
        prompt=default_prompt(PLANNING_PROMPT) if prompt is None else prompt,
        completer=completer,
        recorder=recorder,
        excerpt_chars=200,
        now=lambda: AT,
        timezone="Europe/Lisbon",
        new_id=lambda: "round:1",
    )
    return stage, completer, recorder


def _inputs(**fields: Any) -> PlanningInputs:
    values: dict[str, Any] = {
        "activation_id": "a1",
        "place": CHAT,
    }
    values.update(fields)
    return PlanningInputs(**values)


def _sent(completer: FakeToolCallingCompleter) -> str:
    """The briefing the round was asked with."""
    return completer.last_call.exchange.briefing


def _always(completer: FakeToolCallingCompleter) -> str:
    """The briefing's always-in-mind section, where the block renders (ADR-0356 §3:2)."""
    return section(_sent(completer), "## Always in mind")


async def test_no_block_shows_nothing_of_the_person_model() -> None:
    stage, completer, _ = _stage()

    await stage.plan(_inputs())

    always = _always(completer)
    assert always.startswith("The system does not have it")
    assert tags(always, "memory") == []
    assert "Aether" not in always


async def test_the_block_is_briefed_once_and_nothing_that_changes_is_in_it() -> None:
    """ADR-0356 §3:1, §5:3: the block is part of the briefing, rendered once; a later
    round's changes come as news after it, never by re-rendering the briefing."""
    stage, completer, _ = _stage()

    await stage.plan(_inputs(person=BLOCK))

    exchange = completer.last_call.exchange
    assert exchange.steps == ()
    always = _always(completer)
    assert [one.get("label") for one in tags(always, "memory")] == ["M1", "M2", "M3"]


async def test_the_fields_are_the_persons_own_choices_and_unset_ones_say_so() -> None:
    stage, completer, _ = _stage()

    await stage.plan(_inputs(person=BLOCK))

    lines = _always(completer).split("\n")
    assert lines[:4] == [
        # ADR-0364 §4:2: always in mind says who each P label is.
        "- P1 is Robin Vale, the one the system serves, and has not set a name for it, so it "
        "is called Aether.",
        "- How Robin Vale likes to be addressed: Robin.",
        "- Robin Vale has not set the language they write in.",
        "- These fields are Robin Vale's current choice, and outweigh any memory stating "
        "another value for them.",
    ]
    # §3:9: a zone not set is shown as not set, beside the default the time is given in.
    (now,) = [
        line
        for line in section(_sent(completer), "## The situation").split("\n")
        if line.startswith("- Now:")
    ]
    assert "in the hub's time zone (Europe/Lisbon)" in now
    assert "Robin Vale has not set a time zone" in now


async def test_the_whole_slot_is_shown_by_label_with_why_each_is_kept() -> None:
    stage, completer, recorder = _stage()

    await stage.plan(_inputs(person=BLOCK))

    always = _always(completer)
    kept = [one for one in tags(always, "memory") if one.get("suggested") is None]
    assert [
        (one.get("label"), one.text, one.get("pinned"), one.get("preference")) for one in kept
    ] == [
        ("M1", "Eats no meat.", "yes", None),
        ("M2", "Likes short answers.", None, "yes"),
    ]
    assert "- 1 more memory Robin Vale keeps in mind, left out to keep this short." in (
        always.split("\n")
    )
    # §7:7: each memory takes its label the first time planning is shown it, recorded
    # with the round, so a later round and a call name it by that label.
    (_, labels) = recorder.recorded[0]
    memories = [one for one in labels if one.kind is LabelKind.MEMORY]
    assert [(one.label, one.kind, one.id) for one in memories][:2] == [
        ("M1", LabelKind.MEMORY, "m:diet"),
        ("M2", LabelKind.MEMORY, "m:brief"),
    ]


async def test_suggestions_are_marked_as_suggestions_and_a_pins_memory_is_labelled() -> None:
    stage, completer, _ = _stage()

    await stage.plan(_inputs(person=BLOCK))

    always = _always(completer)
    pin = tag(always, "memory", suggested="pin")
    assert (pin.get("label"), pin.text) == ("M3", "Has a sister called Ada.")
    assert pin.get("pinned") is None
    (field,) = [line for line in always.split("\n") if "Português" in line]
    assert field == (
        "- A suggestion the system noticed on Wed 21 Oct 2026, 10:00 am, which Robin Vale "
        "has not taken up: their language set to Português."
    )


async def test_a_found_memory_the_block_shows_is_not_shown_again() -> None:
    """ADR-0356 §3:2: recalled memories render what no other section renders."""
    stage, completer, _ = _stage()

    await stage.plan(_inputs(person=BLOCK, recalled=(DIET,)))

    sent = _sent(completer)
    recalled = section(sent, "### Recalled memories")
    assert tags(recalled, "memory") == []
    assert recalled.startswith("Nothing is shown")
    assert sent.count("Eats no meat.") == 1


async def test_labels_recorded_in_an_earlier_round_are_kept() -> None:
    """§7:7, §7:10: a memory left after a drop keeps its label, and a new one takes a new one.

    The first memory is dropped before the second round, as §7:10 drops a forgotten one,
    so a round numbering afresh would show the survivor as ``M1``; and a memory shown for
    the first time takes the next label, never one an earlier round assigned.
    """
    first, _, earlier = _stage()
    await first.plan(_inputs(person=BLOCK))
    (_, labels) = earlier.recorded[0]
    assert [(one.label, one.id) for one in labels if one.kind is LabelKind.MEMORY] == [
        ("M1", "m:diet"),
        ("M2", "m:brief"),
        ("M3", "m:sister"),
    ]
    stage, completer, recorder = _stage()
    dropped = replace(BLOCK, kept=BLOCK.kept[1:])

    await stage.plan(_inputs(person=dropped, labels=labels, recalled=(NEW,)))

    always = _always(completer)
    kept = [one for one in tags(always, "memory") if one.get("suggested") is None]
    assert [(one.get("label"), one.text) for one in kept] == [("M2", "Likes short answers.")]
    assert tag(always, "memory", suggested="pin").get("label") == "M3"
    found = tag(section(_sent(completer), "### Recalled memories"), "memory")
    assert (found.get("label"), found.text) == ("M4", NEW.content)
    (_, minted) = recorder.recorded[0]
    assert [(one.label, one.id) for one in minted if one.kind is LabelKind.MEMORY] == [
        ("M4", "m:new")
    ]


@pytest.mark.parametrize(
    "person",
    [None, PersonBlock(person_id=OWNER_PERSON_ID, profile=Profile()), BLOCK],
    ids=["no-block", "block", "block-with-suggestions"],
)
async def test_the_instruction_renders_under_no_flag_whatever_the_block(
    person: PersonBlock | None,
) -> None:
    """ADR-0356 §4:2: the instruction declares no flag, so the block sets none."""
    stage, completer, _ = _stage(FLAG_ECHO)

    await stage.plan(_inputs(person=person))

    assert PLANNING_PROMPT.flags == frozenset()
    assert completer.last_call.exchange.instruction == INSTRUCTION


async def test_a_kept_memory_is_shown_whole_however_long_beside_the_excerpt_bound() -> None:
    """§6:1: the slot's budget bounds its wordings, so none is cut to the excerpt bound."""
    stage, completer, _ = _stage()
    long = memory("m:long", "x" * 250 + " Must avoid all nuts.", said_support(when=AT, added_at=AT))
    block = PersonBlock(
        person_id=OWNER_PERSON_ID,
        profile=Profile(),
        kept=(KeptInMind(memory=long, pinned=True),),
    )

    await stage.plan(_inputs(person=block))

    kept = tag(_always(completer), "memory", pinned="yes")
    assert kept.text == long.content
