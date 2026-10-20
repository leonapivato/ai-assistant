"""The template form (ADR-0334 §4), its version (§8:1), and the defects it refuses (§5:1).

Every template here is the test's own: none reads a shipped default, so nothing here
depends on what any instruction says (§9:1).
"""

from __future__ import annotations

import hashlib

import pytest

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.prompts import PromptDeclaration, PromptOrigin, PromptTemplate

_DECLARED = PromptDeclaration(
    name="sample",
    package="ai_assistant.core",
    flags=frozenset({"left", "right"}),
    values=frozenset({"tool", "cap"}),
)
_VALUES = {"tool": "remember", "cap": "240"}


def _parse(text: str | bytes) -> PromptTemplate:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return PromptTemplate.parse(_DECLARED, data, origin=PromptOrigin.OVERRIDE)


def _render(text: str, *, left: bool = False, right: bool = False) -> str:
    return _parse(text).render(flags={"left": left, "right": right}, values=_VALUES)


# --- §4:1: the form ----------------------------------------------------------------------


def test_a_value_is_printed_bare_or_braced_and_a_doubled_dollar_is_one() -> None:
    rendered = _render("Call $tool, at most ${cap}chars, for $$5.")

    assert rendered == "Call remember, at most 240chars, for $5."


def test_a_printed_value_is_not_read_again_as_template_text() -> None:
    template = _parse("Use $tool.")

    rendered = template.render(
        flags={"left": False, "right": False}, values={"tool": "$cap ${cap} $$", "cap": "x"}
    )

    assert rendered == "Use $cap ${cap} $$."


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (False, False, "top\nnot left\nend"),
        (True, False, "top\nleft\nend"),
        (False, True, "top\nnot left\nend"),
        (True, True, "top\nleft\nleft and right\nend"),
    ],
)
def test_blocks_include_their_lines_where_the_flag_says_and_nest(
    *, left: bool, right: bool, expected: str
) -> None:
    text = "top\n$if left\nleft\n$if right\nleft and right\n$end\n$else\nnot left\n$end\nend\n"

    assert _render(text, left=left, right=right) == expected


def test_if_not_includes_its_block_where_the_flag_is_false() -> None:
    text = "$if not right\nno right\n$else\nright\n$end"

    assert _render(text, right=False) == "no right"
    assert _render(text, right=True) == "right"


def test_a_final_line_break_is_no_part_of_the_text_and_blank_lines_are() -> None:
    """A line break ends a line; the rendered text joins the included lines."""
    assert _render("one\n\ntwo\n") == "one\n\ntwo"
    assert _render("one\n\ntwo") == "one\n\ntwo"
    assert _render("one\n\ntwo\n\n") == "one\n\ntwo\n"


def test_a_directive_line_is_removed_with_its_line_break() -> None:
    assert _render("a\n$if left\nb\n$end\nc") == "a\nc"
    assert _render("a\n$if left\nb\n$end\n") == "a"


def test_a_template_may_name_fewer_flags_and_values_than_its_prompt_declares() -> None:
    """§4:3: naming none at all is a template too."""
    assert _render("plain text") == "plain text"


def test_text_that_only_resembles_a_directive_is_text() -> None:
    """A directive is a line holding only one, so ``$if`` mid-line is a substitution."""
    with pytest.raises(ConfigurationError, match="line 1"):
        _parse("say $if left")


# --- §4:2: the code supplies every flag and value ------------------------------------------


@pytest.mark.parametrize(
    ("flags", "values"),
    [
        ({"left": True}, _VALUES),
        ({"left": True, "right": False, "other": True}, _VALUES),
        ({"left": True, "right": False}, {"tool": "x"}),
        ({"left": True, "right": False}, {**_VALUES, "other": "x"}),
    ],
    ids=["flag missing", "flag extra", "value missing", "value extra"],
)
def test_rendering_takes_exactly_the_declared_flags_and_values(
    flags: dict[str, bool], values: dict[str, str]
) -> None:
    with pytest.raises(ValueError, match="exactly"):
        _parse("text").render(flags=flags, values=values)


# --- §8:1: the version ---------------------------------------------------------------------


def test_the_version_is_twelve_hex_digits_of_the_files_sha256() -> None:
    data = b"one\n$if left\ntwo\n$end\n"

    template = _parse(data)

    assert template.version == hashlib.sha256(data).hexdigest()[:12]
    assert template.provenance() == {
        "name": "sample",
        "version": template.version,
        "origin": "override",
    }


def test_the_version_is_of_the_bytes_so_two_files_rendering_alike_differ() -> None:
    plain, ended = _parse("text"), _parse("text\n")

    assert plain.render(flags={"left": False, "right": False}, values=_VALUES) == ended.render(
        flags={"left": False, "right": False}, values=_VALUES
    )
    assert plain.version != ended.version


def test_a_default_carries_its_origin() -> None:
    template = PromptTemplate.parse(_DECLARED, b"text", origin=PromptOrigin.DEFAULT)

    assert template.provenance()["origin"] == "default"
    assert template.name == "sample"


# --- §5:1, §5:2: the defects, named by line and never quoted --------------------------------

#: A name no prompt declares, which no refusal may repeat (§5:2).
_UNDECLARED = "pumpkin_ledger_7c3e"


@pytest.mark.parametrize(
    ("text", "line"),
    [
        (f"ok\nuse ${_UNDECLARED} here", 2),
        (f"ok\nuse ${{{_UNDECLARED}}} here", 2),
        (f"$if {_UNDECLARED}\nx\n$end", 1),
        (f"$if not {_UNDECLARED}\nx\n$end", 1),
        ("$if tool\nx\n$end", 1),
        ("print $left", 1),
        ("a\nb\ncosts 5$", 3),
        ("a $1 b", 1),
        ("a ${} b", 1),
        ("a ${tool b", 1),
        ("$else", 1),
        ("$end", 1),
        ("$if left\na\n$else\nb\n$else\nc\n$end", 5),
        ("x\n$if left\na", 2),
        ("$if left\n$if right\na\n$end", 1),
        ("$if\nx\n$end", 1),
        ("$if left right\nx\n$end", 1),
        (" $end", 1),
    ],
    ids=[
        "undeclared value",
        "undeclared braced value",
        "undeclared flag",
        "undeclared negated flag",
        "a value branched on",
        "a flag printed",
        "a trailing dollar",
        "a dollar before a digit",
        "empty braces",
        "unclosed braces",
        "an else in no block",
        "an end closing nothing",
        "two elses",
        "an unclosed block",
        "an unclosed outer block",
        "an if naming nothing",
        "an if naming two",
        "an indented directive",
    ],
)
def test_a_malformed_template_is_refused_naming_its_line(text: str, line: int) -> None:
    with pytest.raises(ConfigurationError) as refused:
        _parse(text)

    message = str(refused.value)
    assert message.startswith(f"line {line}: ")
    assert _UNDECLARED not in message


def test_bytes_that_are_not_utf8_are_refused() -> None:
    with pytest.raises(ConfigurationError, match="not UTF-8"):
        _parse(b"caf\xe9")


@pytest.mark.parametrize("text", ["", " ", "\n\n", " \t\n\N{EM SPACE}"])
def test_a_template_of_only_whitespace_is_refused(text: str) -> None:
    with pytest.raises(ConfigurationError, match="only whitespace"):
        _parse(text)


# --- the declaration -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "two words"},
        {"name": "1st"},
        {"flags": frozenset({"if"})},
        {"values": frozenset({"end"})},
        {"flags": frozenset({"else"})},
        {"flags": frozenset({"both"}), "values": frozenset({"both"})},
    ],
)
def test_a_declaration_no_template_could_be_checked_against_is_refused(
    fields: dict[str, object],
) -> None:
    arguments: dict[str, object] = {"name": "sample", "package": "ai_assistant.core"} | fields
    with pytest.raises(ValueError, match=r"cannot name|both a flag and a value"):
        PromptDeclaration(**arguments)  # type: ignore[arg-type]  # each field as a module spells it


def test_a_declarations_file_is_its_name_with_txt() -> None:
    assert _DECLARED.filename == "sample.txt"
