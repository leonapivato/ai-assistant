#!/usr/bin/env python3
"""The ADR ``Status`` field two tools read — one statement of one rule.

``scripts/project_status.py`` renders the field into a status table.
``scripts/check_citations.py`` reads it to decide whether an ADR's own header
agrees with the supersession another ADR records against it (ADR-0088 §4). Two
questions, one field, and — until now — two spellings of how far that field
reaches.

The second spelling is what this module exists to end. ``check_citations.py``
said in a comment that its continuation rule was "lifted from
``scripts/project_status.py``", and it was: the two regexes were
character-for-character identical. So when the rule was corrected in one of them
(#519) the copy in the other kept the defect (#2017), which is the failure issue
#751 records about hand-copied statements of this repository's rules and the
reason ``scripts/citations.py`` exists in the same directory. A caller that
imports the rule cannot drift from it.

Nothing here reads the filesystem or decides anything: it takes text and returns
the field. Both callers choose their own input — ``check_citations.py`` passes an
ADR's header alone, because ADR-0088 §4 legislates a *header* field — and both
do their own work with the value.

Stdlib only, and importable by name: both callers are run as scripts
(``uv run python scripts/<name>.py``), so ``scripts/`` is ``sys.path[0]`` and
neither needs an installed package to find this module.
"""

from __future__ import annotations

import re

#: Tab stops are four columns wide, which is how CommonMark expands a tab.
_TAB_STOP = 4

# The Status field may wrap across continuation lines. The bullet is located
# first and its **content column** computed from the marker as it was actually
# written; the lines that follow are folded into the value only while they are
# indented to at least that column. A blank line, or a line shallower than the
# content column, ends the field. The captured lines are folded into one by
# :func:`_fold` before use.
#
# Depth is the whole rule, and it is markdown's own: a line indented to the
# bullet's content column belongs to that bullet (a wrapped prose line, or a
# nested list item such as ``- migration completed``), and one indented less
# starts a new sibling field (``- Date:``, ``- Amends on ratification:``).
# Two consequences the previous lexical guard got wrong in opposite directions
# (#417): a nested item may carry a colon of its own without being mistaken for
# the next field, and a metadata label may carry punctuation no field-name
# pattern anticipates without being folded into the value.
#
# The column is computed rather than assumed, which is what a single regex could
# not do (#519): a floor fixed at the bullet's indent plus two is the content
# column of a canonical ``- `` marker only, so under a *padded* marker
# (``-   Status:``) it sits too shallow and swallows the sibling field beneath.
# Computing it also subsumes tabs exactly rather than approximating them: a
# sibling written with a *single* leading space still ends the field, because one
# space does not reach the content column, while a lone tab does reach it.
_STATUS_LINE_RE = re.compile(
    r"^(?P<indent>[ \t]*)-(?P<padding>[ \t]*)Status:[ \t]*(?P<value>.+)$",
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
    """Return the content column of a ``- Status:`` bullet written with this marker.

    The content column is where the field's own text begins: past the bullet's
    indent, past the ``-``, and past whatever whitespace was written after it,
    with tabs expanded to four-column stops. A marker with no whitespace at all
    is not a list item under CommonMark; it is measured as the canonical ``- ``
    it was meant to be.

    CommonMark's rule that whitespace wider than four columns makes the content
    an indented code block — pulling the content column back to one past the
    marker — is deliberately not applied. This reads a metadata field rather
    than rendering a document, and the wider column errs toward *ending* the
    field: folding a sibling in corrupts the value (#519), where stopping early
    at most truncates one, and no ADR wraps a Status under a padded marker.

    Args:
        indent: The whitespace before the ``-`` marker.
        padding: The whitespace between the ``-`` and ``Status:``.

    Returns:
        The column a continuation line must reach to belong to the bullet.
    """
    marker_end = _expanded_width(indent) + 1  # the ``-`` occupies one column
    return max(marker_end + 1, _expanded_width(padding, marker_end))


def _fold(value: str) -> str:
    """Collapse a wrapped Status field into a single line.

    Continuation lines still carry their own indentation; fold each whitespace
    run (including line breaks) to a single space so the full field renders on
    one row. A single-line status is returned trimmed and otherwise unchanged.

    Args:
        value: The raw Status value, possibly spanning several lines.

    Returns:
        The Status text on one line.
    """
    return re.sub(r"\s+", " ", value).strip()


def status_value(text: str) -> str | None:
    """Return the folded ``Status`` field of an ADR, or ``None`` if it has none.

    The first ``- Status:`` bullet wins, and the lines beneath it are folded in
    while they reach the bullet's own content column (see
    :func:`_content_column`).

    Args:
        text: The text to read — a whole ADR, or the header alone where the
            caller's rule is a header rule (ADR-0088 §4).

    Returns:
        The Status value on one line, or ``None`` when no Status bullet is found.
    """
    lines = text.split("\n")
    for index, line in enumerate(lines):
        match = _STATUS_LINE_RE.match(line)
        if match is None:
            continue
        column = _content_column(match.group("indent"), match.group("padding"))
        captured = [match.group("value")]
        for following in lines[index + 1 :]:
            stripped = following.lstrip(" \t")
            indent = following[: len(following) - len(stripped)]
            if not stripped or _expanded_width(indent) < column:
                break
            captured.append(stripped)
        return _fold(" ".join(captured))
    return None
