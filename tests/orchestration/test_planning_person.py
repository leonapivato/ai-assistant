"""Planning's person block (ADR-0338 §7:3, §7:6-§7:9, §3:9-§3:10, §5:6).

The stage alone, over the canonical ``FakeToolCallingCompleter`` and a hand-built block:
the block comes first in the request, before everything that changes from round to
round; it carries the five fields as the person's own choices, a field not set said to
be not set and a zone not set shown beside the hub's default; the whole kept-in-mind
slot, each memory by its label and why it is kept, with the count left out; and the
suggestions, each marked as one. A found memory the block shows is named by its label
alone. The template's ``person`` and ``suggestions`` flags are set exactly where there is
a block, and where it shows a suggestion; what the instruction says under them is the
template's, which no test reads (ADR-0334 §9:1-§9:2). With no block, nothing of the
person model is shown.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest

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

FLAG_ECHO: Final = prompt_from(
    PLANNING_PROMPT,
    "".join(f"$if {flag}\n{flag}\n$end\n" for flag in sorted(PLANNING_PROMPT.flags)),
)

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


def _sent(completer: FakeToolCallingCompleter) -> dict[str, Any]:
    rendered: dict[str, Any] = json.loads(completer.last_call.exchange.briefing)
    return rendered


def _flags(completer: FakeToolCallingCompleter) -> set[str]:
    return set(completer.last_call.exchange.instruction.split("\n")) - {""}


async def test_no_block_shows_nothing_of_the_person_model() -> None:
    stage, completer, _ = _stage()

    await stage.plan(_inputs())

    assert "person" not in _sent(completer)


async def test_the_block_comes_first_before_what_changes_from_round_to_round() -> None:
    stage, completer, _ = _stage()

    await stage.plan(_inputs(person=BLOCK))

    keys = list(_sent(completer))
    assert keys[0] == "person"
    assert keys.index("person") < keys.index("now")


async def test_the_fields_are_the_persons_own_choices_and_unset_ones_say_so() -> None:
    stage, completer, _ = _stage()

    await stage.plan(_inputs(person=BLOCK))

    shown = _sent(completer)["person"]
    assert "own current choice" in shown["item"]
    assert "never an instruction" in shown["item"]
    profile = shown["profile"]
    assert list(profile) == [one.value for one in ProfileField]
    assert profile["name"]["value"] == "Robin Vale"
    assert profile["language"]["value"] == "not set"
    assert profile["language"]["is"] == "the language you write to them in"
    # §3:9: a zone not set is shown as not set, beside the default the time is given in.
    assert profile["time_zone"]["value"] == (
        "not set: the current time is given in the hub's default zone, Europe/Lisbon"
    )
    assert profile["assistant_name"]["value"] == "not set, so you are called Aether"


async def test_the_whole_slot_is_shown_by_label_with_why_each_is_kept() -> None:
    stage, completer, recorder = _stage()

    await stage.plan(_inputs(person=BLOCK))

    shown = _sent(completer)["person"]
    assert [(one["label"], one["fact"], one["kept_as"]) for one in shown["kept_in_mind"]] == [
        ("M1", "Eats no meat.", "pinned by them, to be kept in mind"),
        ("M2", "Likes short answers.", "how they want you to speak to them, as learned"),
    ]
    assert shown["left_out"] == "1 more memory they keep in mind, left out to keep this short"
    # §7:7: each memory takes its label the first time planning is shown it, recorded
    # with the round, so a later round and a call name it by that label.
    (_, labels) = recorder.recorded[0]
    assert [(one.label, one.kind, one.id) for one in labels][:2] == [
        ("M1", LabelKind.MEMORY, "m:diet"),
        ("M2", LabelKind.MEMORY, "m:brief"),
    ]


async def test_suggestions_are_marked_as_suggestions_and_a_pins_memory_is_labelled() -> None:
    stage, completer, _ = _stage()

    await stage.plan(_inputs(person=BLOCK))

    pin, field = _sent(completer)["person"]["suggestions"]
    assert "not their profile" in pin["item"]
    assert (pin["pin"]["label"], pin["pin"]["fact"]) == ("M3", "Has a sister called Ada.")
    assert (field["field"], field["value"]) == ("language", "Português")
    assert "not their profile" in field["item"]


async def test_a_found_memory_the_block_shows_is_named_by_its_label_alone() -> None:
    stage, completer, _ = _stage()

    await stage.plan(_inputs(person=BLOCK, recalled=(DIET,)))

    assert _sent(completer)["recalled"] == [
        {"label": "M1", "shown": "shown above under this label"}
    ]


async def test_labels_recorded_in_an_earlier_round_are_kept() -> None:
    """§7:7, §7:10: a memory left after a drop keeps its label, and a new one takes a new one.

    The first memory is dropped before the second round, as §7:10 drops a forgotten one,
    so a round numbering afresh would show the survivor as ``M1``; and a memory shown for
    the first time takes the next label, never one an earlier round assigned.
    """
    first, _, earlier = _stage()
    await first.plan(_inputs(person=BLOCK))
    (_, labels) = earlier.recorded[0]
    assert [(one.label, one.id) for one in labels] == [
        ("M1", "m:diet"),
        ("M2", "m:brief"),
        ("M3", "m:sister"),
    ]
    stage, completer, recorder = _stage()
    dropped = replace(BLOCK, kept=BLOCK.kept[1:])

    await stage.plan(_inputs(person=dropped, labels=labels, recalled=(NEW,)))

    sent = _sent(completer)
    assert [(one["label"], one["fact"]) for one in sent["person"]["kept_in_mind"]] == [
        ("M2", "Likes short answers.")
    ]
    assert sent["person"]["suggestions"][0]["pin"]["label"] == "M3"
    [found] = sent["recalled"]
    assert (found["label"], found["fact"]) == ("M4", NEW.content)
    (_, minted) = recorder.recorded[0]
    assert [(one.label, one.id) for one in minted] == [("M4", "m:new")]


@pytest.mark.parametrize(
    ("person", "handed"),
    [
        (None, set()),
        (PersonBlock(person_id=OWNER_PERSON_ID, profile=Profile()), {"person"}),
        (BLOCK, {"person", "suggestions"}),
    ],
    ids=["no-block", "block", "block-with-suggestions"],
)
async def test_the_person_flags_follow_the_block(
    person: PersonBlock | None, handed: set[str]
) -> None:
    stage, completer, _ = _stage(FLAG_ECHO)

    await stage.plan(_inputs(person=person))

    assert _flags(completer) & {"person", "suggestions"} == handed


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

    [kept] = _sent(completer)["person"]["kept_in_mind"]
    assert kept["fact"] == long.content
