"""Pilot: check that a design doc accounts for every marked clause of its ADRs.

A design doc under ``docs/design/`` restates the current design of one area.
This prototype tests whether that restatement can be made *complete* by a
mechanical check, so that an obligation the fold missed fails loudly instead of
silently ceasing to bind (the risk recorded on #597).

Every ADR-0089 marked clause in the ADRs the ledger names must be either cited
by the design doc or given a disposition in the ledger. A clause is identified
as ``ADR-NNNN §S:k``: ``S`` is the nearest numbered heading above it (``5``,
``10a``) or the name of the unnumbered section (``Context``), and ``k`` is the
clause's ordinal within that section, counted from 1.

Citations in the design doc take the forms ``ADR-0094 §5:2``, ``§5:1-3`` (a
range) and ``§5:*`` (every clause of the section); a bare ``§5`` covers
nothing. Several may share one ADR prefix: ``ADR-0094 §2:1, §3:1-2``.

The ledger is a text file: an ``adrs:`` line naming the ADR numbers in scope,
then one line per clause not cited, ``ADR-NNNN §S:k  <disposition>  [note]``,
where the disposition is ``other`` (belongs to another area; the note names
it), ``spent`` (discharged or no longer binding), or ``superseded`` (the note
names the successor).

Usage: ``python scripts/design_coverage.py DOC LEDGER``. Exits 1 when any
clause is unaccounted for or any citation names a clause that does not exist.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ADR_DIR = Path("docs/adr")
DISPOSITIONS = frozenset({"other", "spent", "superseded"})
_TOP_LEVEL = 2  # "## Context" names a section; deeper unnumbered headings do not

_HEADING = re.compile(r"^(#{2,4})\s+(?:(\d+[a-z]?)\.\s|(.+))")
_MARK = re.compile(r"^> \*\*Normative[.\s—]")
_FENCE = re.compile(r"^\s*(```|~~~)")
_CITE_GROUP = re.compile(r"ADR-(\d{4})((?:\s*,?\s*§[\w]+:(?:\*|\d+(?:-\d+)?))+)")
_CITE_ONE = re.compile(r"§(\w+):(\*|\d+(?:-\d+)?)")
_LEDGER_LINE = re.compile(r"^ADR-(\d{4})\s+§(\w+):(\d+)\s+(\w+)(?:\s+(.*))?$")


@dataclass(frozen=True, order=True)
class Clause:
    """One marked clause, by ADR number, section and ordinal."""

    adr: str
    section: str
    ordinal: int

    def __str__(self) -> str:
        """Render as ``ADR-NNNN §S:k``."""
        return f"ADR-{self.adr} §{self.section}:{self.ordinal}"


def extract_clauses(adr: str) -> list[Clause]:
    """Return every marked clause of one ADR, in file order.

    Args:
        adr: The four-digit ADR number.

    Returns:
        The clauses, following ADR-0089 §2's grammar (and ADR-0257's labelled
        forms): a blank-line-preceded column-0 blockquote run, outside any
        fence, whose first line carries the token.
    """
    (path,) = ADR_DIR.glob(f"{adr}-*.md")
    clauses: list[Clause] = []
    section = "Header"
    counts: Counter[str] = Counter()
    in_fence = False
    previous = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            heading = _HEADING.match(line)
            if heading:
                number, name = heading.group(2), heading.group(3)
                if number:
                    section = number
                elif len(heading.group(1)) == _TOP_LEVEL:
                    section = name.split()[0]
            elif _MARK.match(line) and previous.strip() == "":
                counts[section] += 1
                clauses.append(Clause(adr, section, counts[section]))
        previous = line
    return clauses


def parse_citations(text: str) -> set[tuple[str, str, str]]:
    """Return every (adr, section, selector) cited in a design doc."""
    found: set[tuple[str, str, str]] = set()
    for group in _CITE_GROUP.finditer(text):
        for one in _CITE_ONE.finditer(group.group(2)):
            found.add((group.group(1), one.group(1), one.group(2)))
    return found


def expand(cites: set[tuple[str, str, str]], known: set[Clause]) -> tuple[set[Clause], list[str]]:
    """Resolve citations to clauses, returning the covered set and bad cites."""
    covered: set[Clause] = set()
    bad: list[str] = []
    for adr, section, selector in sorted(cites):
        in_section = {c for c in known if c.adr == adr and c.section == section}
        if selector == "*":
            hits = in_section
        elif "-" in selector:
            low, high = (int(x) for x in selector.split("-"))
            hits = {c for c in in_section if low <= c.ordinal <= high}
            if len(hits) != high - low + 1:
                bad.append(f"ADR-{adr} §{section}:{selector}")
        else:
            hits = {c for c in in_section if c.ordinal == int(selector)}
        if not hits:
            bad.append(f"ADR-{adr} §{section}:{selector}")
        covered |= hits
    return covered, bad


def main(argv: list[str]) -> int:
    """Report coverage for one design doc and its ledger."""
    doc, ledger = Path(argv[1]), Path(argv[2])
    adrs: list[str] = []
    disposed: dict[Clause, str] = {}
    problems: list[str] = []
    for raw in ledger.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("adrs:"):
            adrs = line.removeprefix("adrs:").split()
            continue
        entry = _LEDGER_LINE.match(line)
        if not entry or entry.group(4) not in DISPOSITIONS:
            problems.append(f"unreadable ledger line: {line}")
            continue
        clause = Clause(entry.group(1), entry.group(2), int(entry.group(3)))
        disposed[clause] = entry.group(4)

    known = {c for adr in adrs for c in extract_clauses(adr)}
    cites = {c for c in parse_citations(doc.read_text(encoding="utf-8")) if c[0] in adrs}
    covered, bad = expand(cites, known)
    problems += [f"cites a clause that does not exist: {b}" for b in bad]
    problems += [
        f"ledger names a clause that does not exist: {c}" for c in disposed if c not in known
    ]
    problems += [f"both cited and disposed: {c}" for c in sorted(covered & disposed.keys())]
    missing = sorted(known - covered - disposed.keys())

    by_disposition = Counter(disposed[c] for c in disposed if c in known)
    print(f"ADRs in scope: {len(adrs)}; marked clauses: {len(known)}")
    print(f"  cited by the design doc: {len(covered)}")
    for name in sorted(DISPOSITIONS):
        print(f"  ledger {name}: {by_disposition[name]}")
    print(f"  unaccounted for: {len(missing)}")
    for adr in adrs:
        mine = [c for c in known if c.adr == adr]
        done = sum(1 for c in mine if c in covered or c in disposed)
        print(f"    ADR-{adr}: {done}/{len(mine)}")
    for clause in missing:
        print(f"MISSING {clause}")
    for problem in problems:
        print(f"ERROR {problem}")
    return 1 if missing or problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
