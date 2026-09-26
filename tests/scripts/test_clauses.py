"""Tests for the one clause-identifier extractor (scripts/clauses.py, ADR-0277 §§1-2).

The module is imported directly: it reads no filesystem and runs no process, so
each rule is pinned against a constructed ADR text. The callers —
``check_citations.py``, ``brief_check.py`` and ``adr_rules.py`` — are driven as
subprocesses in their own test modules, which is where the claim that they share
this extractor is exercised end to end.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from clauses import Clause, Reference, clauses, mask, references, resolve

_ADR = """\
# 300. A decision

- Status: Accepted

## Context

> **Normative.** A clause in Context.

Prose.

> **Normative.** A second clause in Context.

## Decision

> **Normative.** Before any numbered heading.

### 1. First

> **Normative.** One-one, first line
> continues here.
>
> and a second paragraph of the same clause.

Prose between.

> **Normative — a label.** One-two, labelled with a dash.

### Why this is so

> **Normative. A full-stop label.** One-three, under an unnumbered heading.

#### 1a. Lettered

> **Normative.** One-a-one.

### 2. Second

```text
> **Normative.** Fenced: display, not a mark.
```

> **Normative.** Two-one.
Not a run line, so the clause ended above.

## Consequences

> **Normative.** A clause in Consequences.
"""


def _ids(text: str, number: int = 300) -> list[str | None]:
    return [clause.identifier(number) for clause in clauses(text)]


def test_every_clause_gets_the_section_and_ordinal_adr_0277_assigns() -> None:
    """§1's section rule, end to end over one document."""
    assert _ids(_ADR) == [
        "ADR-0300 §Context:1",
        "ADR-0300 §Context:2",
        "ADR-0300 §Decision:1",
        "ADR-0300 §1:1",
        "ADR-0300 §1:2",
        "ADR-0300 §1:3",
        "ADR-0300 §1a:1",
        "ADR-0300 §2:1",
        "ADR-0300 §Consequences:1",
    ]


def test_a_run_ends_at_the_first_line_of_neither_shape() -> None:
    """ADR-0089 §2: `> ` text or a bare `>` continue the run; nothing else does."""
    found = {clause.identifier(300): clause for clause in clauses(_ADR)}
    assert found["ADR-0300 §1:1"].lines == (
        "> **Normative.** One-one, first line",
        "> continues here.",
        ">",
        "> and a second paragraph of the same clause.",
    )
    assert found["ADR-0300 §2:1"].lines == ("> **Normative.** Two-one.",)


def test_the_heading_a_clause_sits_under_is_carried_for_display() -> None:
    """The unnumbered `### Why` starts no section, so §1:3 sits under `### 1.`."""
    found = {clause.identifier(300): clause for clause in clauses(_ADR)}
    assert found["ADR-0300 §1:3"].heading == "### 1. First"
    assert found["ADR-0300 §1a:1"].heading == "#### 1a. Lettered"
    assert found["ADR-0300 §Context:1"].heading == "## Context"


@pytest.mark.parametrize(
    "near_mark",
    [
        pytest.param("Prose.\n> **Normative.** Not blank-preceded.\n", id="not-blank-preceded"),
        pytest.param("\n  > **Normative.** Indented.\n", id="indented"),
        pytest.param("\n> **Normative —** No label.\n", id="dash-without-label"),
        pytest.param("\n> **Normative—x** No spaces.\n", id="dash-without-spaces"),
        pytest.param("\n> **Normatively** so.\n", id="normatively"),
        pytest.param("\n```\n> **Normative.** Fenced.\n```\n", id="fenced"),
        pytest.param("\n~~~~\n\n> **Normative.** Unterminated fence.\n", id="unterminated-fence"),
    ],
)
def test_a_near_mark_fails_closed(near_mark: str) -> None:
    """ADR-0089 §2 and ADR-0257 §1: a line failing any part of the grammar is no mark."""
    assert clauses("## Decision\n" + near_mark) == []


def test_a_run_holding_a_fenced_block_is_no_clause_and_takes_no_ordinal() -> None:
    """ "A clause contains no fenced block" — so the run is not a mark at all.

    The ordinal of the next clause is what that decides: were the fenced run a
    clause, the one after it would be §1:2.
    """
    text = (
        "## Decision\n\n### 1. One\n\n"
        "> **Normative.** Shows a sample:\n>\n> ```python\n> x = 1\n> ```\n\n"
        "> **Normative.** The next clause.\n"
    )
    found = clauses(text)
    assert [c.identifier(1) for c in found] == ["ADR-0001 §1:1"]
    assert found[0].lines == ("> **Normative.** The next clause.",)


def test_a_mark_at_the_start_of_the_file_is_a_mark_without_a_section() -> None:
    """Blank-line precedence admits the start of the file; no level-2 heading is above it."""
    found = clauses("> **Normative.** First line of the file.\n")
    assert len(found) == 1
    assert found[0].section is None
    assert found[0].identifier(5) is None


def test_a_level_2_heading_ends_the_numbered_section_above_it() -> None:
    """§1: a numbered heading reaches no further than its own top-level section."""
    text = "## Decision\n\n### 4. Four\n\n## Alternatives considered\n\n> **Normative.** No.\n"
    assert _ids(text) == ["ADR-0300 §Alternatives:1"]


def test_a_numbered_heading_is_a_label_and_a_full_stop() -> None:
    """`### §4 …` and `### #829 …` name someone else's section and number none."""
    text = (
        "## Context\n\n### §4 says three things\n\n> **Normative.** A.\n\n"
        "### #829 fixes the order\n\n> **Normative.** B.\n\n"
        "### 2026 was a year\n\n> **Normative.** C.\n"
    )
    assert _ids(text) == ["ADR-0300 §Context:1", "ADR-0300 §Context:2", "ADR-0300 §Context:3"]


def test_normalised_text_drops_quote_markers_and_folds_whitespace() -> None:
    """§2's duplicate test compares clauses after this normalisation."""
    clause = Clause("1", 1, None, 1, ("> **Normative.** A  rule", ">", ">   that   wraps."))
    assert clause.normalised() == "**Normative.** A rule that wraps."


# --- references --------------------------------------------------------------


def _refs(text: str) -> list[str]:
    return [reference.text() for reference in references(text)]


def test_references_read_single_ranges_and_comma_lists() -> None:
    """§1's third clause: a range, and several identifiers sharing one prefix."""
    text = "See ADR-0094 §5:2, §6:1-3 and §Context:1; also ADR-0277 §2:3."
    assert _refs(text) == [
        "ADR-0094 §5:2",
        "ADR-0094 §6:1-3",
        "ADR-0277 §2:3",
    ]


def test_a_reference_is_read_whole_and_never_as_a_prefix() -> None:
    """`§5:12` is clause 12, not clause 1 followed by a stray digit."""
    assert _refs("ADR-0094 §5:12") == ["ADR-0094 §5:12"]
    assert _refs("ADR-0094 §10a:3") == ["ADR-0094 §10a:3"]
    assert _refs("ADR-0094 §5:2 \u2013 see below") == ["ADR-0094 §5:2"]
    assert _refs("ADR-0094 §5:1\u20133") == ["ADR-0094 §5:1-3"]


@pytest.mark.parametrize(
    "not_an_identifier",
    ["ADR-0094 §5", "ADR-094 §5:2", "§5:2 alone", "ADR-0094 §5.2", "ADR-NNNN §S:k"],
)
def test_other_shapes_are_not_identifiers(not_an_identifier: str) -> None:
    """Only the §1 form is selected; a bare section stays unchecked (ADR-0088 §6)."""
    assert references(not_an_identifier) == []


def test_a_reference_carries_its_line() -> None:
    assert [r.lineno for r in references("one\ntwo ADR-0001 §1:1\nthree")] == [2]


def test_mask_blanks_the_section_part_and_keeps_offsets() -> None:
    """brief_check reads section references over this, so `§5` is read once."""
    text = "ADR-0094 §5:2, §6:1 and ADR-0094 §7."
    masked = mask(text)
    assert len(masked) == len(text)
    assert "§5" not in masked
    assert "§6" not in masked
    assert masked.startswith("ADR-0094 ")
    assert masked.endswith("and ADR-0094 §7.")


# --- resolve -----------------------------------------------------------------


def _ref(section: str, first: int, last: int | None = None) -> Reference:
    return Reference(adr=300, section=section, first=first, last=last, lineno=1)


def test_an_identifier_resolves_when_its_clause_exists() -> None:
    marked = clauses(_ADR)
    assert resolve(_ref("1", 3), marked) is None
    assert resolve(_ref("1", 1, 3), marked) is None
    assert resolve(_ref("context", 2), marked) is None  # a word compares case-insensitively


def test_a_missing_clause_does_not_resolve() -> None:
    problem = resolve(_ref("1", 4), clauses(_ADR))
    assert problem == "ADR-0300 §1 has 3 marked clause(s); :4 does not exist"


def test_a_range_with_a_missing_member_does_not_resolve() -> None:
    """§2: a range resolves only when *every* member exists, not on its first."""
    problem = resolve(_ref("1", 2, 999), clauses(_ADR))
    assert problem == "ADR-0300 §1 has 3 marked clause(s); :4-999 does not exist"


def test_a_range_with_a_zero_endpoint_does_not_resolve() -> None:
    assert resolve(_ref("1", 0, 2), clauses(_ADR)) == (
        "a range whose first member is 0 names no clause"
    )


def test_a_reversed_range_does_not_resolve() -> None:
    assert resolve(_ref("1", 3, 1), clauses(_ADR)) == (
        "a reversed range: its first member exceeds its last"
    )


def test_clause_zero_does_not_resolve() -> None:
    assert resolve(_ref("1", 0), clauses(_ADR)) is not None


def test_a_section_with_no_clause_does_not_resolve() -> None:
    assert resolve(_ref("9", 1), clauses(_ADR)) == "ADR-0300 §9 has no marked clause"


# --- round-1 regressions -------------------------------------------------------


def test_an_inline_code_span_opening_a_continuation_line_is_clause_text() -> None:
    """A backtick fence's info string carries no backtick, so this opens no fence."""
    text = (
        "## Decision\n\n### 1. One\n\n"
        "> **Normative.** A rule using\n> ```inline code``` in its continuation.\n\n"
        "> **Normative.** The next clause.\n"
    )
    found = clauses(text)
    assert [c.identifier(1) for c in found] == ["ADR-0001 §1:1", "ADR-0001 §1:2"]
    assert found[0].lines[1] == "> ```inline code``` in its continuation."


def test_a_prose_line_opening_with_an_inline_span_opens_no_fence() -> None:
    """The same condition at column 0, where a phantom fence would swallow the clauses below."""
    text = "## Decision\n\n```x``` is inline.\n\n> **Normative.** Still a clause.\n"
    assert _ids(text) == ["ADR-0300 §Decision:1"]


def test_an_identifier_list_wrapped_across_lines_is_read_whole() -> None:
    """ADRs are hard-wrapped: a soft break after a comma, or after the prefix, is whitespace."""
    text = "See ADR-0094 §5:2,\n§5:999 and ADR-0094\n§6:1."
    found = references(text)
    assert [(r.text(), r.lineno) for r in found] == [
        ("ADR-0094 §5:2", 1),
        ("ADR-0094 §5:999", 2),
        ("ADR-0094 §6:1", 3),
    ]


def test_an_identifier_list_wrapped_inside_a_block_quote_is_read_whole() -> None:
    text = "> **Normative.** Under ADR-0094 §5:2,\n> §5:3 and ADR-0094\n> §6:1, nothing moves."
    assert _refs(text) == ["ADR-0094 §5:2", "ADR-0094 §5:3", "ADR-0094 §6:1"]


def test_a_blank_line_ends_an_identifier_list() -> None:
    """One line break is a wrap; a blank line is a paragraph, and `§5:3` there is unbound."""
    assert _refs("ADR-0094 §5:2,\n\n§5:3") == ["ADR-0094 §5:2"]


def test_mask_blanks_a_wrapped_list_and_keeps_its_line_breaks() -> None:
    text = "ADR-0094 §5:2,\n> §6:1 and ADR-0094 §7."
    masked = mask(text)
    assert masked.count("\n") == 1
    assert "§5" not in masked
    assert "§6" not in masked


@pytest.mark.parametrize(
    ("written", "shown"),
    [
        pytest.param(f"§5:{'9' * 5000}", f":{'9' * 5000}", id="single"),
        pytest.param(f"§5:1-{'9' * 5000}", f":3-{'9' * 5000}", id="range-last"),
        pytest.param(f"§5:{'9' * 5000}-1", None, id="range-first"),
    ],
)
def test_an_absurdly_long_ordinal_resolves_to_nothing_without_crashing(
    written: str, shown: str | None
) -> None:
    """CPython refuses to convert a few thousand digits; the tool must report, not raise."""
    (reference,) = references(f"ADR-0300 {written}")
    assert reference.text() == f"ADR-0300 {written}"
    marked = [Clause("5", k, None, k, ("> **Normative.** x",)) for k in (1, 2)]
    problem = resolve(reference, marked)
    assert problem is not None
    if shown is not None:
        assert problem.endswith(f"{shown} does not exist")


# --- round-2 regressions -------------------------------------------------------


@pytest.mark.parametrize(
    "fence",
    [
        pytest.param("> > ```python\n> > x = 1\n> > ```", id="nested-quote"),
        pytest.param("> >~~~\n> >x\n> >~~~", id="nested-quote-unspaced"),
        pytest.param("> - ```python\n>   x = 1\n>   ```", id="list-item"),
        pytest.param("> 1. ```\n>    x\n>    ```", id="ordered-list-item"),
    ],
)
def test_a_fence_nested_inside_the_quote_still_disqualifies_the_run(fence: str) -> None:
    """ADR-0089 §2: a clause contains no fenced block, whatever container holds it."""
    text = (
        "## Decision\n\n### 1. One\n\n"
        f"> **Normative.** Example:\n>\n{fence}\n\n"
        "> **Normative.** The next clause.\n"
    )
    found = clauses(text)
    assert [c.identifier(1) for c in found] == ["ADR-0001 §1:1"]
    assert found[0].lines == ("> **Normative.** The next clause.",)


def test_a_nested_quote_or_list_without_a_fence_is_clause_text() -> None:
    text = "## Decision\n\n> **Normative.** A rule:\n> > quoted ``x`` text\n> - an item\n"
    assert len(clauses(text)[0].lines) == 3


@pytest.mark.parametrize(
    ("written", "resolves"),
    [
        ("§1:0000000002", True),
        ("§1:0000000000000000000002", True),
        ("§1:001-0003", True),
        ("§1:0000000004", False),
        ("§1:0-02", False),
    ],
)
def test_leading_zeros_do_not_change_an_ordinal(written: str, resolves: bool) -> None:
    """Only significant digits bound the conversion; the spelling is kept for the report."""
    (reference,) = references(f"ADR-0300 {written}")
    assert reference.text() == f"ADR-0300 {written}"
    assert (resolve(reference, clauses(_ADR)) is None) is resolves


# --- round-3 regressions -------------------------------------------------------


@pytest.mark.parametrize(
    "literal",
    [
        pytest.param(">     ```python\n>     x = 1\n>     ```", id="indented-code"),
        pytest.param("> \t\t```python", id="two-tabs"),
        pytest.param("> -      ```python", id="list-item-indented-code"),
    ],
)
def test_fence_text_inside_indented_code_is_clause_text(literal: str) -> None:
    """Four spaces into its container is an indented code block, not a fenced block."""
    text = (
        "## Decision\n\n### 1. One\n\n"
        f"> **Normative.** Preserve this literal example:\n>\n{literal}\n\n"
        "> **Normative.** The next clause.\n"
    )
    assert [c.identifier(1) for c in clauses(text)] == ["ADR-0001 §1:1", "ADR-0001 §1:2"]


@pytest.mark.parametrize(
    "fence",
    [
        pytest.param(">    ```python", id="three-spaces-after-the-marker-space"),
        pytest.param("> - item\n>   ```python", id="list-continuation"),
        pytest.param(">  >  ```python", id="spaced-nested-quote"),
        pytest.param("> \t```python", id="a-tab-reaches-the-next-stop"),
    ],
)
def test_a_fence_up_to_three_spaces_into_its_container_disqualifies(fence: str) -> None:
    text = (
        "## Decision\n\n### 1. One\n\n"
        f"> **Normative.** Example:\n>\n{fence}\n\n"
        "> **Normative.** The next clause.\n"
    )
    assert [c.identifier(1) for c in clauses(text)] == ["ADR-0001 §1:1"]
