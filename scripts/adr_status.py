#!/usr/bin/env python3
"""The ADR header fields two tools read — one statement of one rule.

``scripts/project_status.py`` renders the ``Status`` field into a status table.
``scripts/check_citations.py`` reads that same field to decide whether an ADR's
own header agrees with the supersession another ADR records against it, and
reads the ``Supersedes`` / ``Partially supersedes`` record that raises the
question (ADR-0088 §4). Three readings, one grammar for how far a header field
reaches, and — until this module — three spellings of it.

Those spellings are what this module exists to end. ``check_citations.py`` said
in a comment that its continuation rule was "lifted from
``scripts/project_status.py``", and it was: the two regexes were
character-for-character identical. So when the rule was corrected in one of them
(#519) the copy in the other kept the defect (#2017), and the reverse record's
own copy of the same two-column floor kept it after that (#2018) — the failure
issue #751 records about hand-copied statements of this repository's rules and
the reason ``scripts/citations.py`` exists in the same directory. A caller that
imports the rule cannot drift from it.

Where a field *begins* stays each caller's decision, because the callers differ
on it for a reason: ADR-0088 §4 pins the reverse record to column zero, where a
``Status`` bullet is read wherever it is indented. That is the ``allow_indent``
argument, and it is the only thing about a header field this module leaves open.

Nothing here reads the filesystem or decides anything: it takes text and returns
the fields. Each caller chooses its own input — ``check_citations.py`` passes an
ADR's header alone, because ADR-0088 §4 legislates a *header* field — and each
does its own work with the values.

Stdlib only, and importable by name: both callers are run as scripts
(``uv run python scripts/<name>.py``), so ``scripts/`` is ``sys.path[0]`` and
neither needs an installed package to find this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Tab stops are four columns wide, which is how CommonMark expands a tab.
_TAB_STOP = 4


@dataclass(frozen=True)
class FieldRecord:
    """One header field of an ADR, read whole.

    Attributes:
        lineno: The 1-based line of the bullet the field was written on, counted
            in the text that was passed in.
        name: The field name as written, folded onto one line.
        value: The field's value, continuation lines folded in.
    """

    lineno: int
    name: str
    value: str


def _field_line_re(names: Sequence[str], *, allow_indent: bool) -> re.Pattern[str]:
    """Return the pattern matching the bullet line of any of ``names``.

    Whitespace *inside* a name matches any run of spaces or tabs, so
    ``Partially supersedes`` is found however it was spaced; everything else in
    a name is matched literally. The names are the only part of the line a
    caller supplies, and they are escaped, so no caller writes a pattern here.

    Args:
        names: The field names to match, case-insensitively.
        allow_indent: Whether the bullet may carry leading whitespace. ``False``
            pins it to column zero.

    Returns:
        The compiled pattern, with ``indent``, ``padding``, ``name`` and
        ``value`` groups. Compilation is memoised by :mod:`re`'s own cache.
    """
    alternation = "|".join(
        r"[ \t]+".join(re.escape(word) for word in name.split()) for name in names
    )
    indent = r"(?P<indent>[ \t]*)" if allow_indent else r"(?P<indent>)"
    return re.compile(
        rf"^{indent}-(?P<padding>[ \t]*)(?P<name>{alternation}):[ \t]*(?P<value>.+)$",
        re.IGNORECASE,
    )


def _expanded_width(text: str, start: int = 0) -> int:
    """Return the column reached after ``text``, expanding tabs to four-column stops.

    Args:
        text: The run of characters to measure, normally an indent or a marker.
        start: The column ``text`` begins at, since a tab's width depends on it.

    Returns:
        The column immediately after ``text``.
    """
    column = start
    for char in text:
        column = column + _TAB_STOP - column % _TAB_STOP if char == "\t" else column + 1
    return column


def _content_column(indent: str, padding: str) -> int:
    """Return the content column of a ``- Name:`` bullet written with this marker.

    The content column is where the field's own text begins: past the bullet's
    indent, past the ``-``, and past whatever whitespace was written after it,
    with tabs expanded to four-column stops. A marker with no whitespace at all
    is not a list item under CommonMark; it is measured as the canonical ``- ``
    it was meant to be.

    CommonMark's rule that whitespace wider than four columns makes the content
    an indented code block — pulling the content column back to one past the
    marker — is deliberately not applied. This reads a metadata field rather
    than rendering a document, and the wider column errs toward *ending* the
    field: folding a sibling in corrupts the value (#519, #2018), where stopping
    early at most truncates one, and no ADR wraps a header field under a padded
    marker.

    Args:
        indent: The whitespace before the ``-`` marker.
        padding: The whitespace between the ``-`` and the field name.

    Returns:
        The column a continuation line must reach to belong to the bullet.
    """
    marker_end = _expanded_width(indent) + 1  # the ``-`` occupies one column
    return max(marker_end + 1, _expanded_width(padding, marker_end))


def _fold(value: str) -> str:
    """Collapse a wrapped field onto a single line.

    Continuation lines still carry their own indentation; fold each whitespace
    run (including line breaks) to a single space so the full field renders on
    one row. A single-line field is returned trimmed and otherwise unchanged.

    Args:
        value: The raw text, possibly spanning several lines.

    Returns:
        The text on one line.
    """
    return re.sub(r"\s+", " ", value).strip()


def field_records(text: str, names: Sequence[str], *, allow_indent: bool) -> list[FieldRecord]:
    """Return every ``- Name: value`` header field in ``text``, in document order.

    A field may wrap across continuation lines. The bullet is located first and
    its **content column** computed from the marker as it was actually written;
    the lines that follow are folded into the value only while they are indented
    to at least that column. A blank line, or a line shallower than the content
    column, ends the field — and a line folded into one field's value is never
    read as the start of another.

    Depth is the whole rule, and it is markdown's own: a line indented to the
    bullet's content column belongs to that bullet (a wrapped prose line, or a
    nested list item such as ``- migration completed``), and one indented less
    starts a new sibling field (``- Date:``, ``- Amends on ratification:``).
    Two consequences the previous lexical guard got wrong in opposite directions
    (#417): a nested item may carry a colon of its own without being mistaken for
    the next field, and a metadata label may carry punctuation no field-name
    pattern anticipates without being folded into the value.

    The column is computed rather than assumed, which is what a single regex
    could not do (#519, #2018): a floor fixed at the bullet's indent plus two is
    the content column of a canonical ``- `` marker only, so under a *padded*
    marker (``-   Status:``) it sits too shallow and swallows the sibling field
    beneath. Computing it also subsumes tabs exactly rather than approximating
    them: a sibling written with a *single* leading space still ends the field,
    because one space does not reach the content column, while a lone tab does
    reach it.

    Args:
        text: The text to read — a whole ADR, or the header alone where the
            caller's rule is a header rule (ADR-0088 §4).
        names: The field names to look for, case-insensitively.
        allow_indent: Whether an indented bullet counts. ``False`` accepts a
            marker at column zero only, which is what ADR-0088 §4 requires of
            the reverse supersession record.

    Returns:
        One :class:`FieldRecord` per bullet found, values folded onto one line.
    """
    pattern = _field_line_re(names, allow_indent=allow_indent)
    lines = text.split("\n")
    records: list[FieldRecord] = []
    index = 0
    while index < len(lines):
        match = pattern.match(lines[index])
        if match is None:
            index += 1
            continue
        column = _content_column(match.group("indent"), match.group("padding"))
        captured = [match.group("value")]
        following = index + 1
        while following < len(lines):
            line = lines[following]
            stripped = line.lstrip(" \t")
            if not stripped or _expanded_width(line[: len(line) - len(stripped)]) < column:
                break
            captured.append(stripped)
            following += 1
        records.append(
            FieldRecord(
                lineno=index + 1,
                name=_fold(match.group("name")),
                value=_fold(" ".join(captured)),
            )
        )
        index = following
    return records


def status_value(text: str) -> str | None:
    """Return the folded ``Status`` field of an ADR, or ``None`` if it has none.

    The first ``- Status:`` bullet wins, at whatever indent it was written, and
    the lines beneath it are folded in while they reach the bullet's own content
    column (see :func:`field_records`).

    Args:
        text: The text to read — a whole ADR, or the header alone where the
            caller's rule is a header rule (ADR-0088 §4).

    Returns:
        The Status value on one line, or ``None`` when no Status bullet is found.
    """
    records = field_records(text, ("Status",), allow_indent=True)
    return records[0].value if records else None
