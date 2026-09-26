#!/usr/bin/env python3
"""Print one ADR's rulings without its argument — ``just adr-rules NNNN`` (ADR-0277 §4).

The view is the ADR's title, its complete ``Status`` line, and every marked
clause verbatim, each under its section heading and prefixed by its clause
identifier. Nothing else of the body is printed: no Context, no argument, no
worked example. An ADR with no marked clause prints its title, its ``Status``
line and a statement that it is unmarked and binds as prose (ADR-0089 §4).

**It states nothing about whether a clause is in force.** A supersession scope
is prose ("only as it reaches…"), so an annotation computed from it would be a
guessed second statement of the law in front of the reader. The ``Status`` line
is shown whole instead, and the reading is left to the reader and to the ADRs it
names (§4's third clause).

The clauses and their identifiers come from ``scripts/clauses.py``, the one
extractor ADR-0277 §2 allows; the ``Status`` field from
``scripts/check_citations.py``'s header reading, which is where the checker reads
it too.

    uv run python scripts/adr_rules.py 94
    just adr-rules ADR-0094

Exit status is 0 when the ADR was printed, and 2 when the argument names no ADR.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import clauses
from check_citations import DuplicateAdrNumberError, numbered_adr_files, status_field

if TYPE_CHECKING:
    from collections.abc import Sequence

_NUMBER_RE = re.compile(r"^(?:ADR-)?(\d{1,4})$", re.IGNORECASE)
_TITLE_RE = re.compile(r"^ {0,3}#[ \t]+\S")


def title_of(text: str) -> str:
    """Return the ADR's level-1 heading line, or its first line where it has none."""
    for _, line in clauses.iter_prose_lines(text):
        if _TITLE_RE.match(line):
            return line.strip()
    return text.splitlines()[0].strip() if text.strip() else ""


def render(number: int, text: str) -> str:
    """Return the rules view of ADR ``number``, whose whole text is ``text``.

    Args:
        number: The ADR's number, for the identifiers.
        text: The ADR's whole text.

    Returns:
        The view, as ADR-0277 §4 specifies it, without a trailing newline.
    """
    status = status_field(text)
    lines = [title_of(text), f"- Status: {status}" if status else "- Status: (none found)"]
    marked = clauses.clauses(text)
    if not marked:
        lines += [
            "",
            f"ADR-{number:04d} is unmarked: it carries no marked clause, so it binds as "
            "prose, read whole (ADR-0089 §4).",
        ]
        return "\n".join(lines)
    heading: str | None = None
    for index, clause in enumerate(marked):
        if index == 0 or clause.heading != heading:
            heading = clause.heading
            lines += ["", heading if heading is not None else "(above every section)"]
        lines += [
            "",
            clause.identifier(number) or f"ADR-{number:04d} (no section, line {clause.lineno})",
            *clause.lines,
        ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Print the rules view of the ADR named on the command line.

    Returns:
        0 when the ADR was printed, 2 when the argument names none.
    """
    parser = argparse.ArgumentParser(description="Print one ADR's marked clauses (ADR-0277 §4).")
    parser.add_argument("adr", help="The ADR: 94, 0094 or ADR-0094.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to read (defaults to this checkout).",
    )
    args = parser.parse_args(argv)
    match = _NUMBER_RE.match(args.adr.strip())
    if match is None:
        print(f"adr-rules: {args.adr!r} is not an ADR number", file=sys.stderr)
        return 2
    number = int(match.group(1))
    try:
        path = numbered_adr_files(args.root.resolve()).get(number)
    except DuplicateAdrNumberError as error:
        print(error, file=sys.stderr)
        return 2
    if path is None:
        print(f"adr-rules: no docs/adr/{number:04d}-*.md", file=sys.stderr)
        return 2
    print(render(number, path.read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
