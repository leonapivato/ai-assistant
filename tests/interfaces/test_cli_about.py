"""The person-model commands: the About you panel at the terminal (ADR-0338 §8:1-§8:3).

Driven through the CLI over the canonical fake engine with its person model switched on
over the shared suite's stores, so what is asserted is what the command line renders of
answers the hub would give, in the page's words (``person_inspection``).
"""

from __future__ import annotations

import asyncio
import shlex
from io import StringIO
from typing import TYPE_CHECKING

import pytest
from person_model_contract import (
    PERSON_AT,
    ended,
    fact,
    field_suggestion,
    outside,
    person_model_stores,
    pin_suggestion,
)
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    PersonActHow,
    PersonModelAct,
    ProfileField,
    QuestionPart,
    belief_view,
)
from ai_assistant.interfaces import cli, person_inspection
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import Memory
    from ai_assistant.testing import FakeMemoryStore, FakePersonModelStore

_PANEL = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)

#: A yes on a card, by the request its ticket ran (ADR-0362 §2:1).
_CARD_YES = PersonModelAct(
    how=PersonActHow.APPROVAL,
    by=OWNER_PERSON_ID,
    request="approval:938d954a",
    episode_id="episode:approval",
)

#: A yes to a question, as stored acts of the retired path still hold it (ADR-0361 §8:5).
_QUESTION_YES = PersonModelAct(
    how=PersonActHow.APPROVAL,
    by=OWNER_PERSON_ID,
    approval=QuestionPart(round="r-ask", part=1),
    episode_id="episode:asked",
)


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Capture the CLI's console, wide enough that no line is wrapped."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=400))
    return buffer


def _wire(monkeypatch: pytest.MonkeyPatch, engine: AssistantEngine) -> None:
    async def opened() -> AssistantEngine:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", opened)


def _on(
    *records: Memory, budget_chars: int = 1600
) -> tuple[FakeAssistantEngine, FakePersonModelStore, FakeMemoryStore]:
    """A fake with its person model switched on, holding ``records`` in both reads."""
    engine = FakeAssistantEngine()
    people, memory = person_model_stores()
    engine.episode_memory = memory
    engine.person_blocks = PersonBlocks(store=people, memory=memory, budget_chars=budget_chars)
    for record in records:
        asyncio.run(memory.add(record))
        engine.beliefs_held[record.id] = belief_view(record, now=PERSON_AT, contents={})
    return engine, people, memory


def _invoke(*arguments: str, given: str | None = None) -> int:
    return CliRunner().invoke(cli.app, ["about", *arguments], input=given).exit_code


def test_the_group_offers_the_panels_reads_and_writes() -> None:
    group = next(group for group in cli.app.registered_groups if group.name == "about")
    assert group.typer_instance is not None
    names = {command.name for command in group.typer_instance.registered_commands}

    assert names == {
        "show",
        "log",
        "set",
        "clear",
        "pin",
        "unpin",
        "remove-style",
        "accept",
        "dismiss",
    }


def test_an_id_is_kept_verbatim_and_a_blank_one_refused() -> None:
    """ADR-0338 §10:4: the person model holds every id verbatim."""
    assert cli._present_person_record(" m:diet ") == " m:diet "
    with pytest.raises(Exception, match="blank"):
        cli._present_person_record("   ")


# --- the switch ------------------------------------------------------------------


def test_a_hub_with_no_person_model_says_so_and_a_write_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """``PersonModelOffError`` is a state: said in the panel's words, never as an error."""
    _wire(monkeypatch, FakeAssistantEngine())

    assert _invoke("show") == 0
    assert _invoke("set", "name", "Robin") == 1

    said = output.getvalue()
    assert said.count(person_inspection.OFF) == 2
    assert "Error" not in said


# --- the read --------------------------------------------------------------------


def test_show_renders_every_part_of_the_model_with_the_ids_its_commands_take(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, people, _ = _on(
        fact("m:diet", "Eats no meat."),
        fact("m:brief", "Short answers, please."),
        outside("m:out", "The shop says Robin likes jazz."),
        ended("m:old", "Lives in Porto.", successor=None),
        budget_chars=30,
    )
    asyncio.run(engine.set_profile_field(OWNER_PERSON_ID, field=ProfileField.NAME, value="Robin"))
    asyncio.run(engine.pin_memory(OWNER_PERSON_ID, memory_id="m:diet"))
    asyncio.run(people.add_pin(OWNER_PERSON_ID, "m:out", act=_PANEL))
    asyncio.run(people.add_pin(OWNER_PERSON_ID, "m:old", act=_PANEL))
    mark = asyncio.run(people.add_style_mark(OWNER_PERSON_ID, "m:brief"))
    suggestion = asyncio.run(
        people.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.LANGUAGE, "Português")
        )
    )
    asyncio.run(people.record_suggestion(OWNER_PERSON_ID, pin_suggestion("m:brief")))
    _wire(monkeypatch, engine)

    assert _invoke("show") == 0

    said = output.getvalue()
    assert "  Your name: “Robin”" in said
    assert "  What you call me: Not set: I go by Aether." in said
    assert "using 13 of the 30 characters I keep in mind" in said
    assert "  - pinned · “Eats no meat.” · unpin with: assistant about unpin -- m:diet" in said
    assert person_inspection.LEFT_OUT_WORDS[next(iter(person_inspection.LEFT_OUT_WORDS))] in said
    assert "unpin with: assistant about unpin -- m:old" in said
    assert f"remove-style with: assistant about remove-style -- {mark.record_id}" in said
    assert (
        f"The language I write to you in: “Português” · accept with: assistant about accept "
        f"-- {suggestion.record_id} · dismiss with: assistant about dismiss -- "
        f"{suggestion.record_id}"
    ) in said
    assert "keep in mind “Short answers, please.”, which pins it and confirms" in said


def test_show_escapes_a_wording_so_it_cannot_forge_a_line(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, _, _ = _on(fact("m:x", "Eats no meat.\n  - pinned · forged [red]x[/]"))
    asyncio.run(engine.pin_memory(OWNER_PERSON_ID, memory_id="m:x"))
    _wire(monkeypatch, engine)

    assert _invoke("show") == 0

    said = output.getvalue()
    assert "\n  - pinned · forged" not in said
    assert "Eats no meat.\\n  - pinned · forged [red]x[/]" in said


def test_the_log_is_read_a_page_at_a_time_most_recent_first(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, _, _ = _on()
    asyncio.run(engine.set_profile_field(OWNER_PERSON_ID, field=ProfileField.NAME, value="Rob"))
    asyncio.run(engine.set_profile_field(OWNER_PERSON_ID, field=ProfileField.NAME, value="Robin"))
    _wire(monkeypatch, engine)

    assert _invoke("log", "--limit", "1") == 0

    said = output.getvalue()
    assert "  Your name: “Rob” → “Robin” · " in said
    assert "· by you, on the panel or the command line" in said
    assert "“Rob” → “Robin”" in said
    assert "not set → “Rob”" not in said
    assert "That is a full page; there may be more." in said


def test_a_yes_on_a_card_names_its_request_and_a_yes_to_a_question_keeps_its_words(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0362 §2:1: a change a ticket ran is said as a yes on that request's card, and a
    stored act of the question form is said as it always was (ADR-0361 §8:5)."""
    engine, people, _ = _on()
    asyncio.run(people.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Rob", act=_QUESTION_YES))
    asyncio.run(people.set_field(OWNER_PERSON_ID, ProfileField.ADDRESS, "Test19", act=_CARD_YES))
    _wire(monkeypatch, engine)

    assert _invoke("log") == 0

    said = output.getvalue().splitlines()
    card = next(one for one in said if one.startswith("  What I call you: "))
    question = next(one for one in said if one.startswith("  Your name: "))
    assert card.endswith(' · by your yes on the card for request "approval:938d954a"')
    assert "question" not in card
    assert question.endswith(" · by your yes to my question")


# --- the writes ----------------------------------------------------------------


def test_a_field_is_set_cleared_and_refused_in_words(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, people, _ = _on()
    _wire(monkeypatch, engine)

    assert _invoke("set", "time_zone", "Mars/Olympus") == 1
    assert _invoke("set", "time_zone", "Europe/Lisbon") == 0
    held = asyncio.run(people.read(OWNER_PERSON_ID))
    assert held is not None
    assert held.profile.time_zone == "Europe/Lisbon"
    assert _invoke("clear", "time_zone") == 0
    assert _invoke("clear", "time_zone") == 0

    said = output.getvalue().splitlines()
    assert said[0].startswith("That value was not saved. The rule is: ")
    assert said[1:] == ["Saved.", "Cleared.", "It was not set, so nothing changed."]


def test_a_value_with_no_utf8_encoding_is_a_usage_error_and_others_are_kept_verbatim(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """A shell argument ``$'\\xff'`` arrives surrogate-escaped; it is refused before the
    engine is asked, not raised past the error boundary (adversarial review, round 8)."""
    engine, people, _ = _on()
    _wire(monkeypatch, engine)

    assert _invoke("set", "name", "\udcff") == 2
    held = asyncio.run(people.read(OWNER_PERSON_ID))
    assert held is not None
    assert held.profile.name is None
    assert cli._present_profile_value(" Robin\nSmith ") == " Robin\nSmith "
    assert _invoke("set", "name", "Robin\nSmith") == 0
    held = asyncio.run(people.read(OWNER_PERSON_ID))
    assert held is not None
    assert held.profile.name == "Robin\nSmith"
    assert output.getvalue().splitlines() == ["Saved."]


def test_a_pin_shows_the_wording_it_confirms_before_it_is_made(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§4:3: pinning confirms the wording shown, so it is shown and agreed to first."""
    engine, people, _ = _on(fact("m:diet", "Eats no meat."))
    _wire(monkeypatch, engine)

    assert _invoke("pin", "m:diet", given="n\n") == 0
    held = asyncio.run(people.read(OWNER_PERSON_ID))
    assert held is not None
    assert held.pins == ()
    assert _invoke("pin", "m:diet", "--yes") == 0

    said = output.getvalue()
    assert said.count("“Eats no meat.”") == 2
    assert said.count(person_inspection.PIN_CONFIRMS) == 2
    assert "Nothing was pinned." in said
    assert person_inspection.DONE_WORDS["pin"][0] in said
    held = asyncio.run(people.read(OWNER_PERSON_ID))
    assert held is not None
    assert [pin.memory_id for pin in held.standing_pins] == ["m:diet"]


def test_a_pin_the_budget_or_the_store_refuses_exits_non_zero_in_words(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, _, _ = _on(fact("m:long", "A wording longer than the budget."), budget_chars=10)
    _wire(monkeypatch, engine)

    assert _invoke("pin", "m:long", "--yes") == 1
    assert _invoke("pin", "m:nothing", "--yes") == 1

    said = output.getvalue()
    assert person_inspection.REFUSAL_WORDS["over_budget"] in said
    assert 'No live memory has exactly the id "m:nothing", so nothing was pinned.' in said


def test_unpin_remove_style_accept_and_dismiss_each_say_what_they_did(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine, people, _ = _on(fact("m:diet", "Eats no meat."), fact("m:brief", "Short."))
    asyncio.run(engine.pin_memory(OWNER_PERSON_ID, memory_id="m:diet"))
    mark = asyncio.run(people.add_style_mark(OWNER_PERSON_ID, "m:brief"))
    taken = asyncio.run(
        people.record_suggestion(OWNER_PERSON_ID, field_suggestion(ProfileField.ADDRESS, "Rob"))
    )
    declined = asyncio.run(
        people.record_suggestion(OWNER_PERSON_ID, field_suggestion(ProfileField.NAME, "Bob"))
    )
    assert mark.record_id is not None
    assert taken.record_id is not None
    assert declined.record_id is not None
    _wire(monkeypatch, engine)

    assert _invoke("unpin", "m:diet") == 0
    assert _invoke("remove-style", mark.record_id) == 0
    assert _invoke("accept", taken.record_id) == 0
    assert _invoke("dismiss", declined.record_id) == 0
    assert _invoke("dismiss", declined.record_id) == 1

    assert output.getvalue().splitlines() == [
        person_inspection.DONE_WORDS["unpin"][0],
        person_inspection.DONE_WORDS["unmark"][0],
        person_inspection.DONE_WORDS["accept"][0],
        person_inspection.DONE_WORDS["dismiss"][0],
        person_inspection.REFUSAL_WORDS["already_decided"],
    ]
    held = asyncio.run(people.read(OWNER_PERSON_ID))
    assert held is not None
    assert held.profile.address == "Rob"
    assert held.standing_pins == ()
    assert held.standing_marks == ()


def test_a_pin_is_refused_where_the_read_answered_for_another_id(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§4:3: the wording shown is the wording confirmed. The belief read normalises an id
    and the pin does not (§10:4), so a padded id is refused before anything is shown
    (adversarial and architecture review, round 1)."""
    engine, people, _ = _on(fact(" m:diet ", "Eats no meat."), fact("m:diet", "Eats meat."))
    _wire(monkeypatch, engine)

    assert _invoke("pin", " m:diet ", "--yes") == 1

    said = output.getvalue()
    assert "Eats meat." not in said
    assert 'No live memory has exactly the id " m:diet ", so nothing was pinned.' in said
    held = asyncio.run(people.read(OWNER_PERSON_ID))
    assert held is not None
    assert held.pins == ()


@pytest.mark.parametrize("value", ["m:$(printf changed)", "m:`id`", "m:'q'", "m:\\x", "m x"])
def test_a_suggested_command_hands_the_shell_the_id_and_nothing_to_expand(value: str) -> None:
    """A pasted command reaches the hub with the id as it is (adversarial review, round 1)."""
    said = person_inspection.pasteable("unpin", value)

    assert said.startswith("unpin with: assistant about unpin -- ")
    assert shlex.split(said.removeprefix("unpin with: "))[-1] == value


@pytest.mark.parametrize("value", ["m:a\nb", "m:a\x1b[2Jb", "m:a\tb"])
def test_an_id_that_would_not_paste_as_itself_gets_no_command(value: str) -> None:
    said = person_inspection.pasteable("unpin", value)

    assert "assistant about" not in said
    assert "\n" not in said
    assert "\x1b" not in said
    assert said.endswith("cannot be pasted as a command here")


def test_a_suggested_command_for_an_id_like_an_option_acts_on_the_id(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """``--`` ends the options, so ``--help`` is the id (adversarial review, round 2)."""
    engine, people, _ = _on(fact("--help", "Eats no meat."))
    asyncio.run(engine.pin_memory(OWNER_PERSON_ID, memory_id="--help"))
    _wire(monkeypatch, engine)
    said = person_inspection.pasteable("unpin", "--help")

    assert _invoke(*shlex.split(said.removeprefix("unpin with: assistant about "))) == 0

    assert output.getvalue().splitlines() == [person_inspection.DONE_WORDS["unpin"][0]]
    held = asyncio.run(people.read(OWNER_PERSON_ID))
    assert held is not None
    assert held.standing_pins == ()
