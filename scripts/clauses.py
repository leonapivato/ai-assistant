#!/usr/bin/env python3
"""Marked clauses and their identifiers — ADR-0277's one extractor.

ADR-0277 §1 gives every marked clause an address, ``ADR-NNNN §S:k``: the *k*-th
marked clause of ADR-NNNN within section *S*, counted from 1 in file order. §2
requires that the address be computed by **one** implementation, shared by
``scripts/check_citations.py`` (which fails an identifier that does not resolve),
``scripts/brief_check.py`` (which reports one in a dispatch brief) and
``just adr-rules`` (which prints an ADR's clauses under their identifiers). This
module is that implementation, and nothing else in ``scripts/`` states the mark's
grammar, the section rule or the identifier's form.

What it reads, in the order the rules are stated:

- **The mark** is ADR-0089 §2's grammar with ADR-0257 §1's widened first line. A
  clause is a run of consecutive column-0 lines, each ``> `` followed by text or a
  bare ``>``, whose first line opens ``> **Normative`` followed by ``.**``, or by a
  label separator (``. `` or `` — ``) and a non-space character; the first line is
  immediately preceded by a blank line or the start of the file; the run ends at
  the first line of neither shape; a token line inside a fence is display; and a
  run that holds a fenced block fails the grammar and is no clause at all.
- **The section** *S* is ADR-0277 §1's second clause: the label of the nearest
  numbered heading above the clause (``### 5.`` → ``5``, ``#### 10a.`` → ``10a``),
  or, where no numbered heading precedes it within its level-2 section, the first
  word of that level-2 heading (``Context``, ``Consequences``). An unnumbered
  heading below level 2 starts no section.
- **The identifier** is ADR-0277 §1's third clause: ``ADR-NNNN §S:k``, or
  ``§S:j-k`` for a range, with several sharing one ADR prefix separated by commas.

**A heading is numbered when its text opens with a label and a full stop**
(``5.``, ``10a.``). That is the shape every numbered heading of every marked ADR
takes, and the one ``scripts/brief_check.py``'s section finder already matches; a
heading opening ``§4`` or ``#829`` names someone else's section and numbers none.

Nothing here reads the filesystem, runs git, or decides a tier. It extracts and
resolves; each caller judges what it found. Stdlib only, and importable by name:
every caller is run as a script, so ``scripts/`` is ``sys.path[0]``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

#: A fence line: up to three spaces, then three or more backticks or tildes. The
#: one fence rule the citation checker and the clause scan share, so the two can
#: never disagree about whether a line is display (ADR-0088 §1, ADR-0089 §2).
#: CommonMark's one further condition is applied in :func:`_fence`: a backtick
#: fence's info string carries no backtick, so a line opening with an inline
#: span such as ````x``` y`` is prose and opens nothing.
_FENCE_RE = re.compile(r"^(?P<indent> {0,3})(?P<ticks>`{3,}|~{3,})(?P<info>.*)$")

#: A clause's first line (ADR-0089 §2 as ADR-0257 §1 widens it): the token closed
#: by ``.**``, or followed by a label separator and a non-space character.
_MARK_OPEN_RE = re.compile(r"^> \*\*Normative(?:\.\*\*|(?:\. | — )\S)")

#: A line that continues a run: ``> `` followed by text, or a bare ``>``. A ``>``
#: followed only by whitespace is read as bare, because a trailing space is
#: invisible and ending the run on one would silently truncate a clause.
_RUN_LINE_RE = re.compile(r"^>(?: .*|\s*)$")

#: A fence opened inside a block quote — which a clause may not contain. The same
#: two openers as :data:`_FENCE_RE`, with the same backtick condition, so a
#: continuation line that merely starts with an inline code span is clause text.
#: Whatever containers the clause nests inside its quote — a further ``>``, a list
#: item — are read through, because a fence inside them is still a fenced block
#: inside the clause.
_QUOTED_FENCE_RE = re.compile(
    r"^(?:>[ \t]*)+(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)*(?:`{3,}[^`]*|~{3,}.*)$"
)

#: An ATX heading: up to three spaces, one to six ``#``, then whitespace or the
#: end of the line.
_HEADING_RE = re.compile(r"^ {0,3}(?P<hashes>#{1,6})(?:[ \t]+(?P<text>.*?))?[ \t]*$")

#: A numbered heading's label: digits, an optional lower-case letter, a full stop.
_NUMBERED_RE = re.compile(r"^(?P<label>\d+[a-z]?)\.(?:\s|$)")

#: The first word of a level-2 heading.
_WORD_RE = re.compile(r"[^\W_]\w*")

#: The level-2 heading, the level below which an unnumbered heading starts nothing.
_TOP_LEVEL = 2

#: One section label in an identifier: a numbered label, or a heading's word.
_SECTION = r"(?:\d+[a-z]?|[^\W\d_]\w*)"

#: One ``§S:k`` or ``§S:j-k``. The range separator is a hyphen, or an en or em
#: dash — the three ``scripts/brief_check.py`` already reads between sections —
#: written with no space either side, so ``§5:2`` followed by a spaced dash is one clause and not a
#: range.
_DASH = "[-\u2013\u2014]"
_ONE_ID = rf"§(?P<section>{_SECTION}):(?P<first>\d+)(?:{_DASH}(?P<last>\d+))?(?![\w:])"

#: Where an identifier may wrap: spaces and tabs, and at most one line break
#: followed by the block-quote markers and indent of the next line. ADRs are
#: hard-wrapped and a marked clause is a block quote, so a comma list — or the
#: prefix and its first ``§`` — broken across ``> `` lines is still one citation.
_BREAK = r"[ \t]*(?:\n(?:[ \t]*>)*[ \t]*)?"

#: A clause identifier with its ADR prefix, and any further ``§S:k`` sharing it.
#: The ADR number is ADR-0088 §1(a)'s four digits, the decision citation's form.
IDENTIFIER_RE = re.compile(
    rf"\bADR-(?P<adr>\d{{4}})(?:[ \t]+|[ \t]*\n(?:[ \t]*>)*[ \t]*)"
    rf"(?P<ids>§{_SECTION}:\d+(?:{_DASH}\d+)?(?![\w:])"
    rf"(?:,{_BREAK}§{_SECTION}:\d+(?:{_DASH}\d+)?(?![\w:]))*)"
)
_ONE_ID_RE = re.compile(_ONE_ID)

#: The longest ordinal converted as written. A longer one names no clause any ADR
#: could carry, and converting it unbounded would let a citation crash the tool
#: reading it — CPython refuses an integer literal of a few thousand digits.
_LARGEST_ORDINAL_DIGITS = 9
_BEYOND_EVERY_ORDINAL: int = 10**_LARGEST_ORDINAL_DIGITS


@dataclass(frozen=True)
class Clause:
    """One marked clause of one ADR.

    Attributes:
        section: *S* — the numbered label, or the level-2 heading's first word,
            or ``None`` where the clause stands above every level-2 heading and
            ADR-0277 §1 gives it no section.
        ordinal: *k* — its position among the clauses of ``section``, from 1.
        heading: The heading line *S* was read from, verbatim, or ``None``.
        lineno: The 1-based line the clause starts on.
        lines: The clause's physical lines, verbatim.
    """

    section: str | None
    ordinal: int
    heading: str | None
    lineno: int
    lines: tuple[str, ...]

    def identifier(self, number: int) -> str | None:
        """Return ``ADR-NNNN §S:k`` for this clause of ADR ``number``, if it has one."""
        if self.section is None:
            return None
        return f"ADR-{number:04d} §{self.section}:{self.ordinal}"

    def normalised(self) -> str:
        """Return the clause's text with block-quote markers and whitespace normalised.

        ADR-0277 §2's duplicate test compares this: each line loses its ``>`` and
        the one space after it, and every whitespace run becomes one space.
        """
        return " ".join(" ".join(line[1:] for line in self.lines).split())


@dataclass(frozen=True)
class Reference:
    """One ``§S:k`` or ``§S:j-k`` a text cites, with the ADR it names.

    Attributes:
        adr: The ADR number.
        section: *S* as written.
        first: *j* (or *k* for a single clause). An ordinal longer than
            :data:`_LARGEST_ORDINAL_DIGITS` digits is held as a value no clause
            reaches, so it resolves to nothing without being converted whole.
        last: *k* for a range, ``None`` for a single clause.
        lineno: The 1-based line of the text the reference sits on.
        span: The ordinals as written, a range's dash normalised to a hyphen.
    """

    adr: int
    section: str
    first: int
    last: int | None
    lineno: int
    span: str = ""

    def text(self) -> str:
        """Render the reference in its canonical form, ADR prefix included."""
        span = self.span or (f"{self.first}" if self.last is None else f"{self.first}-{self.last}")
        return f"ADR-{self.adr:04d} §{self.section}:{span}"


def _ordinal(digits: str) -> int:
    """Return an ordinal's value, or one beyond every clause for an absurd magnitude.

    Leading zeros are dropped before the length is judged: ``0000000002`` is the
    second clause, and only the significant digits say how large a number is.
    """
    significant = digits.lstrip("0") or "0"
    if len(significant) > _LARGEST_ORDINAL_DIGITS:
        return _BEYOND_EVERY_ORDINAL
    return int(significant)


def _fence(line: str) -> re.Match[str] | None:
    """Return the fence match for ``line``, or ``None`` where it opens no fence."""
    match = _FENCE_RE.match(line)
    if match is None:
        return None
    if match.group("ticks")[0] == "`" and "`" in match.group("info"):
        return None
    return match


def fenced_flags(lines: Sequence[str]) -> list[bool]:
    """Return, per line, whether it is a fence line or inside a fenced block.

    A closing fence is the opener's character, at least as long, with nothing
    after it. An unterminated fence runs to the end of the document, which is the
    conservative direction for both readers: excluding too much is a miss.

    Args:
        lines: The document's physical lines.

    Returns:
        One flag per line: ``True`` for display, ``False`` for prose.
    """
    flags: list[bool] = []
    open_fence: tuple[str, int] | None = None
    for line in lines:
        match = _fence(line)
        if open_fence is None:
            if match is not None:
                ticks = match.group("ticks")
                open_fence = (ticks[0], len(ticks))
                flags.append(True)
            else:
                flags.append(False)
            continue
        flags.append(True)
        char, length = open_fence
        if (
            match is not None
            and match.group("ticks")[0] == char
            and len(match.group("ticks")) >= length
            and not match.group("info").strip()
        ):
            open_fence = None
    return flags


def iter_prose_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(lineno, line)`` for every line outside a fenced block.

    Args:
        text: The whole document.

    Yields:
        One ``(1-based lineno, line)`` pair per line outside any fence.
    """
    lines = text.splitlines()
    for index, (line, fenced) in enumerate(zip(lines, fenced_flags(lines), strict=True)):
        if not fenced:
            yield index + 1, line


def _heading(line: str) -> tuple[int, str] | None:
    """Return ``(level, text)`` for an ATX heading line, or ``None``."""
    match = _HEADING_RE.match(line)
    if match is None:
        return None
    return len(match.group("hashes")), (match.group("text") or "").strip()


class _Sections:
    """The headings in force at one point of a scan, and the *S* they give.

    ADR-0277 §1: a numbered heading at any level from 2 down sets *S* to its
    label; a level-2 heading starts a new top-level section, whose first word is
    *S* until a numbered heading is met inside it; an unnumbered heading below
    level 2 changes nothing; and a level-1 heading — the title — leaves no
    section in force, so a clause above every level-2 heading has no *S*.
    """

    def __init__(self) -> None:
        self._top: tuple[str, str] | None = None  # (first word, heading line)
        self._numbered: tuple[str, str] | None = None  # (label, heading line)

    def see(self, level: int, heading_text: str, line: str) -> None:
        """Account for one heading line."""
        label = _NUMBERED_RE.match(heading_text)
        if level < _TOP_LEVEL:
            self._top, self._numbered = None, None
            return
        if level == _TOP_LEVEL:
            word = _WORD_RE.search(heading_text)
            self._top = (word.group(0), line) if word else None
            self._numbered = None
        if label is not None:
            self._numbered = (label.group("label"), line)

    def current(self) -> tuple[str | None, str | None]:
        """Return *S* and the heading line it was read from, or ``(None, None)``."""
        if self._numbered is not None:
            return self._numbered
        if self._top is not None:
            return self._top
        return None, None


def _run_end(lines: Sequence[str], fenced: Sequence[bool], start: int) -> int:
    """Return the index one past the run of block-quote lines opened at ``start``."""
    end = start + 1
    while end < len(lines) and not fenced[end] and _RUN_LINE_RE.match(lines[end]):
        end += 1
    return end


def clauses(text: str) -> list[Clause]:
    """Return every marked clause of one ADR, in file order, with its identifier parts.

    Args:
        text: The ADR's whole text.

    Returns:
        Each clause ADR-0089 §2 (as ADR-0257 §1 widens it) selects, carrying the
        section and ordinal ADR-0277 §1 assigns it. A run whose first line is a
        mark but which holds a fenced block fails ADR-0089 §2's grammar ("A clause
        contains no fenced block") and is no clause, so it takes no ordinal.
    """
    lines = text.splitlines()
    fenced = fenced_flags(lines)
    sections = _Sections()
    found: list[Clause] = []
    counts: dict[str, int] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        heading = None if fenced[index] else _heading(line)
        if heading is not None:
            sections.see(heading[0], heading[1], line)
        opens = (
            not fenced[index]
            and _MARK_OPEN_RE.match(line) is not None
            and (index == 0 or not lines[index - 1].strip())
        )
        if not opens:
            index += 1
            continue
        end = _run_end(lines, fenced, index)
        run = lines[index:end]
        if not any(_QUOTED_FENCE_RE.match(member) for member in run):
            section, heading_line = sections.current()
            ordinal = 1
            if section is not None:
                key = section.casefold()
                ordinal = counts[key] = counts.get(key, 0) + 1
            found.append(Clause(section, ordinal, heading_line, index + 1, tuple(run)))
        index = end
    return found


def references(text: str) -> list[Reference]:
    """Return every clause identifier ``text`` carries, a comma list expanded.

    Fenced lines are not stripped here — as ``scripts/citations.py`` does not —
    because the callers want different things from a fence; each passes the
    text it means to be read.

    Args:
        text: Any prose.

    Returns:
        One :class:`Reference` per ``§S:k`` or ``§S:j-k``, in text order.
    """
    found: list[Reference] = []
    for match in IDENTIFIER_RE.finditer(text):
        number = int(match.group("adr"))
        offset = match.start("ids")
        for one in _ONE_ID_RE.finditer(match.group("ids")):
            first, last = one.group("first"), one.group("last")
            found.append(
                Reference(
                    adr=number,
                    section=one.group("section"),
                    first=_ordinal(first),
                    last=None if last is None else _ordinal(last),
                    lineno=text.count("\n", 0, offset + one.start()) + 1,
                    span=first if last is None else f"{first}-{last}",
                )
            )
    return found


def resolve(reference: Reference, marked: Sequence[Clause]) -> str | None:
    """Return why ``reference`` does not resolve against ``marked``, or ``None``.

    ADR-0277 §2: an identifier resolves only when every clause it names exists —
    for ``§S:k`` the *k*-th marked clause of *S*, for ``§S:j-k`` every clause from
    *j* to *k* — and a range whose *j* is 0, or exceeds its *k*, never resolves.
    Section labels compare case-insensitively, which can only resolve more.

    Args:
        reference: The identifier to resolve.
        marked: The cited ADR's clauses, as :func:`clauses` returned them.

    Returns:
        ``None`` when every named clause exists, else one sentence saying which
        does not.
    """
    if reference.last is not None:
        if reference.first == 0:
            return "a range whose first member is 0 names no clause"
        if reference.first > reference.last:
            return "a reversed range: its first member exceeds its last"
    key = reference.section.casefold()
    available = sum(1 for clause in marked if clause.section and clause.section.casefold() == key)
    wanted = reference.first if reference.last is None else reference.last
    if reference.first >= 1 and wanted <= available:
        return None
    where = f"ADR-{reference.adr:04d} §{reference.section}"
    if available == 0:
        return f"{where} has no marked clause"
    written = reference.span or (
        f"{reference.first}" if reference.last is None else f"{reference.first}-{reference.last}"
    )
    if reference.last is None or reference.first > available:
        shown = f":{written}"
    else:
        last = written.rsplit("-", 1)[-1]
        shown = (
            f":{available + 1}" if available + 1 == reference.last else f":{available + 1}-{last}"
        )
    return f"{where} has {available} marked clause(s); {shown} does not exist"


def mask(text: str) -> str:
    """Return ``text`` with every clause identifier's ``§`` part blanked, same length.

    For a reader of section references (``scripts/brief_check.py``), so that the
    ``§5`` inside ``ADR-0094 §5:2`` is read once, as the clause identifier it is,
    and a comma-joined ``§6:1`` is not read as a section no ADR is bound to.
    """

    def blank(match: re.Match[str]) -> str:
        start = match.start("ids") - match.start()
        whole = match.group(0)
        return whole[:start] + re.sub(r"[^\n]", " ", whole[start:])

    return IDENTIFIER_RE.sub(blank, text)
