"""The About you panel's words, read against the command line's (ADR-0338 §8:2).

``test_bundle.py``'s instrument, for its reason: what a reading decides — that the page
and the terminal say one sentence for one fact, totally over ``core``'s enumerations —
is decided here over the shipped script's text. What the page *does* with them is
``test_browser_about.py``'s.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from test_bundle import _code, _functions, _joined, _markup

from ai_assistant.core.types import (
    DEFAULT_ASSISTANT_NAME,
    OWNER_PERSON_ID,
    Belief,
    LeftOutReason,
    PersonActHow,
    PersonModelEditRefusal,
    PersonModelRefusal,
    ProfileField,
    SupportOrigin,
    belief_view,
)
from ai_assistant.interfaces import cli, person_inspection
from ai_assistant.testing.memories import confirmed_support, memory, pinned_support

#: One double-quoted JavaScript literal, escapes and all.
_LITERAL = r'"(?:[^"\\]|\\.)*"'


def _table(script: str, name: str) -> dict[str, str]:
    """A ``const NAME = { key: "..." + "...", ... }`` table, each value its sentence."""
    opened = script.index(f"const {name} = {{")
    block = script[opened : script.index("\n};", opened)]
    pieces = re.split(r"\n  (\w+):\s+", block)[1:]
    return {key: _joined(value) for key, value in zip(pieces[::2], pieces[1::2], strict=True)}


def _member(entry: str, name: str) -> str:
    """The sentence one member of an object literal renders, by the member's name."""
    found = re.search(rf"{name}:\s*((?:{_LITERAL}\s*\+?\s*)+)", entry)
    assert found is not None, (name, entry)
    return _joined(found.group(1))


def test_the_page_names_the_hubs_one_person_as_core_does() -> None:
    """ADR-0338 §2:1: the page names the person whose model it shows, by core's id."""
    assert f'const OWNER_PERSON_ID = "{OWNER_PERSON_ID}";' in _code("app.js")


def test_every_field_is_called_and_said_unset_in_the_terminals_words() -> None:
    """§3's table and §3:9, totally over ``ProfileField``, in its order."""
    script = _code("app.js")
    opened = script.index("const PROFILE_FIELDS = [")
    block = script[opened : script.index("\n];", opened)]
    entries = re.split(r"(?=\{\s*field: )", block)[1:]
    title = re.search(r"<title>([^<]+)</title>", _markup("index.html"))

    assert title is not None
    assert title.group(1) == DEFAULT_ASSISTANT_NAME
    assert [_member(one, "field") for one in entries] == [field.value for field in ProfileField]
    for field, entry in zip(ProfileField, entries, strict=True):
        assert _member(entry, "label") == person_inspection.FIELD_WORDS[field], field
        unset = re.search(r'unset: (?:"([^"]*)"|`([^`]*)`)', entry)
        assert unset is not None, field
        said = (unset.group(1) or unset.group(2)).replace("${document.title}", title.group(1))
        assert said == person_inspection.UNSET_WORDS[field], field


def test_every_way_a_change_is_made_is_said_in_the_terminals_words() -> None:
    """§3:5's four ways, totally over ``PersonActHow``."""
    table = _table(_code("app.js"), "CHANGE_HOW_WORDS")

    assert table == {how.value: person_inspection.HOW_WORDS[how] for how in PersonActHow}


def test_a_yes_on_a_card_is_said_in_the_terminals_words() -> None:
    """ADR-0362 §2:1: a change naming a request is said as a yes on its card, both places."""
    assert f'const CARD_YES_WORDS = "{person_inspection.CARD_YES_WORDS}";' in _code("app.js")


def test_every_reason_the_slot_leaves_a_memory_out_is_said_in_the_terminals_words() -> None:
    """§6:2 and §6:4, totally over ``LeftOutReason``."""
    table = _table(_code("app.js"), "LEFT_OUT_WORDS")

    assert table == {
        reason.value: person_inspection.LEFT_OUT_WORDS[reason] for reason in LeftOutReason
    }


def test_every_refusal_is_said_in_words_and_in_the_terminals() -> None:
    """A refusal is shown in words (§8:7's spirit on the panel), never as a code: every
    refusal the store gives and both the engine gives before a write."""
    table = _table(_code("app.js"), "EDIT_REFUSALS")
    names = [one.value for one in PersonModelRefusal] + [
        one.value for one in PersonModelEditRefusal
    ]

    assert sorted(table) == sorted(names)
    assert table == dict(person_inspection.REFUSAL_WORDS)


def test_what_each_act_did_is_said_in_the_terminals_words() -> None:
    script = _code("app.js")
    opened = script.index("const EDIT_DONE = {")
    block = script[opened : script.index("\n};", opened)]
    pieces = re.split(r"\n  (\w+):\s+", block)[1:]
    done = {
        act: (_member(entry, "written"), _member(entry, "unchanged"))
        for act, entry in zip(pieces[::2], pieces[1::2], strict=True)
    }

    assert done == dict(person_inspection.DONE_WORDS)


def test_a_hub_with_no_person_model_is_said_alike_on_both_surfaces() -> None:
    script = _code("app.js")
    opened = script.index("const PERSON_MODEL_OFF =")
    said = _joined(script[opened : script.index(";", opened)])

    assert said == person_inspection.OFF


def test_the_pin_control_says_that_pinning_confirms_the_wording_shown() -> None:
    """§8:2: "a pin control that says that pinning confirms the wording shown"."""
    offering = _functions(_code("app.js"))["offerPinning"]

    assert 'control("Pin: confirms this wording", () =>' in offering
    assert 'checkedBeliefEdit(belief, "/person/pin", "pin")' in offering
    assert 'checkedBeliefEdit(belief, "/person/unpin", "unpin")' in offering
    assert 'belief.status !== "current"' in offering, "on each current memory alone"


def _confirmed(*origins: SupportOrigin) -> Belief:
    """A confirmed memory's single view, resting on one counted ``for`` support each."""
    supports = [
        pinned_support() if origin is SupportOrigin.PINNED else confirmed_support()
        for origin in origins
    ]
    held = memory("m:1", "Eats no meat.", *supports)
    return belief_view(held, now=datetime(2026, 10, 21, tzinfo=UTC), contents={})


def test_a_pinned_memory_says_the_person_pinned_it_on_both_surfaces() -> None:
    """#3333: a ``pinned`` support is a pin, not a yes to a question; the listing, which
    carries no supports, names neither."""
    how = _functions(_code("app.js"))["confirmedHow"]
    cases = [
        (SupportOrigin.PINNED,),
        (SupportOrigin.CONFIRMATION,),
        (SupportOrigin.CONFIRMATION, SupportOrigin.PINNED),
    ]
    page = re.findall(r'return "([^"]*)";', how)

    for origins in cases:
        sentence = cli._confirmed_why(_confirmed(*origins))
        assert sentence[0].upper() + sentence[1:] in page, origins
    assert cli._confirmed_why(_confirmed(SupportOrigin.PINNED)) == (
        "you confirmed this wording by pinning it."
    )
    assert "You confirmed this wording." in page
    assert "when I asked you" not in _functions(_code("app.js"))["whyHeld"]
    assert "confirmedHow(belief)" in _functions(_code("app.js"))["whyHeld"]
