#!/usr/bin/env python3
"""Check what the ADRs cite against the repository — ADR-0088 §6's checker.

ADR-0088 §1 defines three citation *forms*; §2 defines what "resolves" means for
each; §6 says which of them a tool may report and which of them it may fail on.
This module is that tool, and its whole design is a restatement of §6's three
prohibitions:

- **The input set is §1's forms; the checker does not infer its own.** Only a
  decision citation (``ADR-NNNN``), a tracker citation (``#NNN``) and the two
  *selectable* code sub-forms — b1 a rooted module path, b2 a dotted symbol —
  are extracted. A bare backticked token (b3) is never selected: the corpus
  backticks status vocabulary, enum members, Python literals and git refs in the
  same shape as a class name, and separating them is the inference §6 forbids.
  §6 puts a number on the difference: 479 false positives against 3 defects.
- **The checker does not infer document structure.** Section references (``§K``)
  are extracted by nobody and checked by nothing. The natural implementation —
  read ``###`` headings — is wrong on 92 citations, because three ADRs number
  their sections in bold and twelve number none at all.
- **A miss is benign; a false report is not.** Every unevaluable citation passes
  silently, and every judgement call in this file resolves toward *not*
  reporting. That is why symbol resolution indexes dotted suffixes generously
  (over-resolving costs a miss, under-resolving costs a false report), and why
  a path whose anchoring directory is absent is dropped rather than reported.

Two tiers, per §6:

- **Tier 1 may fail** — and holds exactly two things, a decision citation naming
  an ADR file that does not exist and a tracker citation naming an issue number
  that does not exist. Neither has a legitimate non-resolving case.
- **Tier 2 is reported and never fails** — unresolved b1/b2 code citations (§3:
  an append-only corpus correctly cites what the tree does not contain) and
  liveness disagreements (§4).

Run via ``just citations`` (or ``python3 scripts/check_citations.py``). ``--root``
points at a different checkout, which is how the tests drive it.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

#: The three roots a b1 module path may lie under (ADR-0088 §2(b)). All three,
#: not ``src/`` alone: conformance suites and their factories live under
#: ``tests/`` by CONTRIBUTING.md's "Adding a Protocol", and the corpus cites
#: ``scripts/`` by name. A path under any other root is a *document* reference
#: and nothing resolves it against the code.
_CODE_ROOTS = ("src/ai_assistant", "tests", "scripts")

#: Prefixes a citation may carry when it is written in full rather than relative
#: to one of the roots above. ``src/`` rather than ``src/ai_assistant/`` so that
#: ``src/ai_assistant/core/protocols.py`` anchors on its own first segment.
_FULL_PREFIXES = ("src/", "tests/", "scripts/")

#: File suffixes that make a dotted token a *document* name rather than a symbol
#: (ADR-0088 §1(b): ``CONTRIBUTING.md`` and ``CLAUDE.md`` share b2's shape and
#: are not code). ``.py`` is here too: a bare ``store.py`` carries no root, so it
#: is not b1 either, and reading it as a dotted symbol would invent a citation.
_DOCUMENT_SUFFIXES = frozenset(
    {
        "md",
        "txt",
        "toml",
        "yml",
        "yaml",
        "json",
        "lock",
        "cfg",
        "ini",
        "env",
        "example",
        "sh",
        "py",
        "db",
        "sqlite",
        "sqlite3",
        "log",
        "html",
        "css",
        "js",
        "gitignore",
    }
)

#: A decision citation (ADR-0088 §1(a)). The optional ``§K`` that may follow is
#: deliberately not captured: §6 leaves section references unchecked, because a
#: ``§K`` in prose cannot be told apart from a restatement of a supersession
#: scope (ADR-0074's "ADR-0076 §9's obligation set" names ADR-0074's own §9).
_DECISION_RE = re.compile(r"\bADR-(\d{4})\b")

#: A tracker citation (ADR-0088 §1(c)). The lookaround excludes a markdown
#: heading (``#`` then a space), an anchor (``](#slug)``), and a hex colour.
_TRACKER_RE = re.compile(r"(?<![\w#])#(\d{1,6})(?![\w#])")

#: An inline code span. Longest run of backticks first, so ``` ``a `b` c`` ```
#: is read as one span rather than two. Spans do not cross a line here: a
#: multi-line span is dropped, which is a miss and therefore benign (§6).
_CODE_SPAN_RE = re.compile(r"(?P<ticks>`+)(?P<content>[^\n]+?)(?P=ticks)")

#: A fence line. ADR-0088 §1: everything inside a fence is display, not citation
#: — which is what lets an ADR exhibit a form it forbids, including a reference
#: to an ADR that does not exist (§4 fences ``ADR-0090`` for exactly this).
_FENCE_RE = re.compile(r"^(?P<indent> {0,3})(?P<ticks>`{3,}|~{3,})(?P<info>.*)$")

#: A trailing line number on a legacy citation (ADR-0088 §5): the rule is
#: forward-only, and "a legacy citation is handled by stripping the line number
#: and resolving the path", so ``testing/memory.py:41`` is checked as
#: ``testing/memory.py``. A comma-joined list of lines is the same form.
_LINE_SUFFIX_RE = re.compile(r":\d+(?:[-,]\d+)*$")

#: A pytest node id's test selector. Stripped for the same reason as a line
#: number: what is left is a path under ``tests/``, which is b1 and checkable,
#: where the selector is a position inside the file.
_NODE_ID_RE = re.compile(r"::.*$")

#: Characters that stop a backticked span being read as a path at all. A span
#: carrying one is not a module path in any reading, so it is dropped rather
#: than reported — ADR-0085 backticks ``\/`` inside a regex, and no filesystem
#: question is being asked about it.
_NOT_IN_A_PATH = frozenset("\\*?<>|\"'()[]{}=$!;&`")

#: A dotted symbol (ADR-0088 §1(b), b2): a qualified name whose tail is an
#: identifier. At least one dot, so a bare token stays b3 and unselected.
_DOTTED_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$")

#: An ADR filename, e.g. ``0088-a-citation-is-a-checkable-form.md``.
_ADR_FILENAME_RE = re.compile(r"^(\d{4})-.*\.md$")

#: A level-2 ATX heading, which is where an ADR's header ends. Markdown's own
#: rule, not a guess at one: up to three leading spaces, and the marker is
#: closed by a space, a tab, or the end of the line. ``###`` is a *third* ``#``
#: rather than whitespace, so a level-3 heading does not end the header.
_HEADING_2_RE = re.compile(r"^ {0,3}##(?:[ \t].*)?$")

#: The two tiers of ADR-0088 §6.
_TIER_FAILING = 1
_TIER_REPORTED = 2

#: A module path names at least one directory plus a leaf.
_MIN_PATH_SEGMENTS = 2

#: ``Owner.member`` — the shortest qualified name a b2 citation can be.
_QUALIFIED_PAIR = 2

#: The ``Status`` field, read as a whole *field* rather than a first line:
#: ADR-0070 §4 requires every physical line, since a legacy value may wrap. The
#: continuation rule is markdown's own and is lifted from
#: ``scripts/project_status.py``: a following line belongs to the bullet when it
#: is indented to the bullet's content column.
_STATUS_RE = re.compile(
    r"^(?P<indent>[ \t]*)-[ \t]*Status:[ \t]*(?P<value>.+(?:\n(?P=indent)(?:\t|[ \t]{2,})\S.*)*)",
    re.IGNORECASE | re.MULTILINE,
)

#: The reverse supersession record (ADR-0088 §4), read with the same wrapping
#: rule as ``Status``. ADR-0088 ratifies this header line as "the canonical
#: machine-readable form" of a supersession.
_SUPERSEDES_RE = re.compile(
    r"^(?P<indent>[ \t]*)-[ \t]*(?P<kind>Partially\s+supersedes|Supersedes):[ \t]*"
    r"(?P<value>.+(?:\n(?P=indent)(?:\t|[ \t]{2,})\S.*)*)",
    re.IGNORECASE | re.MULTILINE,
)

#: ADR-0070 §4's canonical supersession vocabulary, matched case-insensitively —
#: which ADR-0088 §4 records as required rather than incidental: the token leads
#: the line in ``Superseded by ADR-0015`` and follows a grandfathered
#: ``Accepted,`` in ``partially superseded by ADR-0020``.
_SUPERSESSION_TOKEN_RE = re.compile(r"(?:partially\s+)?superseded\s+by\b", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    """One thing the checker has to say about one citation.

    Attributes:
        tier: 1 if this may fail a change, 2 if it is reported and never fails.
        kind: Which rule produced it — ``decision``, ``tracker``, ``module-path``,
            ``dotted-symbol`` or ``liveness``.
        path: The ADR the citation was written in, relative to the repo root.
        line: 1-based line number of the citation.
        citation: The citation exactly as written.
        detail: What is wrong with it, in one sentence.
    """

    tier: int
    kind: str
    path: str
    line: int
    citation: str
    detail: str

    def as_dict(self) -> dict[str, object]:
        """Return the finding as JSON-ready primitives."""
        return {
            "tier": self.tier,
            "kind": self.kind,
            "path": self.path,
            "line": self.line,
            "citation": self.citation,
            "detail": self.detail,
        }

    def location(self) -> str:
        """Return ``path:line`` for display."""
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class Citation:
    """A citation selected out of an ADR, before anything is resolved.

    Attributes:
        kind: ``decision``, ``tracker``, ``module-path`` or ``dotted-symbol``.
        text: The citation as written, with a legacy ``:NNN`` already stripped
            from a module path (ADR-0088 §5).
        path: The ADR it appears in, relative to the repo root.
        line: 1-based line number.
    """

    kind: str
    text: str
    path: str
    line: int


@dataclass(frozen=True)
class Report:
    """Everything one run of the checker found.

    Attributes:
        findings: Every finding, Tier 1 first.
        counts: How many citations of each kind were *selected* — the denominator
            a reader needs to judge the numerator.
        tracker_checked: Whether tracker citations could be resolved at all. When
            GitHub is unreachable they are unevaluable and pass silently (§6).
        notes: Anything the run could not do, for the reader.
    """

    findings: tuple[Finding, ...]
    counts: dict[str, int]
    tracker_checked: bool
    notes: tuple[str, ...]

    @property
    def tier1(self) -> tuple[Finding, ...]:
        """Findings that may fail a change."""
        return tuple(f for f in self.findings if f.tier == _TIER_FAILING)

    @property
    def tier2(self) -> tuple[Finding, ...]:
        """Findings that are reported and never fail."""
        return tuple(f for f in self.findings if f.tier == _TIER_REPORTED)

    def as_dict(self) -> dict[str, object]:
        """Return the report as JSON-ready primitives."""
        return {
            "findings": [f.as_dict() for f in self.findings],
            "counts": dict(self.counts),
            "tracker_checked": self.tracker_checked,
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------- #
# Reading an ADR: fences out, citations in
# --------------------------------------------------------------------------- #


def iter_prose_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(lineno, line)`` for every line outside a fenced block.

    ADR-0088 §1 excludes fenced content from the input set *by form*, which is
    the mechanism rather than a courtesy: it is what lets an ADR exhibit a form
    it forbids without failing its own check. The fence line itself is excluded
    too — its info string is display, not prose.

    Args:
        text: The whole document.

    Yields:
        One ``(1-based lineno, line)`` pair per line outside any fence.
    """
    open_fence: tuple[str, int, int] | None = None
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _FENCE_RE.match(line)
        if open_fence is None:
            if match is not None:
                ticks = match.group("ticks")
                open_fence = (ticks[0], len(ticks), len(match.group("indent")))
                continue
            yield lineno, line
            continue
        char, length, _indent = open_fence
        if match is not None and match.group("ticks")[0] == char:
            closes = len(match.group("ticks")) >= length and not match.group("info").strip()
            if closes:
                open_fence = None
    # An unterminated fence swallows the rest of the file. That is the
    # conservative direction: excluding too much costs misses, which §6 calls
    # benign, where including display text costs false reports, which it does not.


def _iter_code_spans(line: str) -> Iterator[str]:
    """Yield the content of each inline code span on one line, trimmed."""
    for match in _CODE_SPAN_RE.finditer(line):
        content = match.group("content").strip()
        if content:
            yield content


def top_level_names(root: Path) -> frozenset[str]:
    """Return the names a dotted citation's *head* may legitimately be.

    Every package and module directly under one of the three code roots, plus
    the distribution package itself. This is what tells ``memory.MemoryIngestor``
    (head is a package here) from ``asyncio.timeout`` (head is not).
    """
    names = {"ai_assistant", "src"}
    for code_root in _CODE_ROOTS:
        base = root / code_root
        if not base.is_dir():
            continue
        names.add(base.name)
        for child in base.iterdir():
            if child.name.startswith((".", "_")):
                continue
            if child.is_dir():
                names.add(child.name)
            elif child.suffix == ".py":
                names.add(child.stem)
    return frozenset(names)


def classify_code_span(content: str, top_names: frozenset[str]) -> tuple[str, str] | None:
    """Classify one backticked span as a b1 path, a b2 symbol, or neither.

    ADR-0088 §1(b) separates the three code sub-forms by *whether a machine can
    tell them apart from ordinary prose*. b3 — a bare single token — is not
    separable and therefore never returned here; selecting it is the inference
    §6 forbids.

    **Two mechanical narrowings, both of them toward silence.** A path must carry
    a directory component and no character that stops it being a path; a dotted
    name's head must be a class name or a package that exists here. Without the
    second, ``typing.Protocol``, ``datetime.min`` and ``cost.amount`` are all
    selected and all reported — 32% of b2 rather than the ~4% ADR-0088 §2
    measured, which is the "usable check" boundary §6 draws. Narrowing costs
    misses, and §6 is explicit that a miss is benign where a false report is not.

    Args:
        content: The span's content, already trimmed of surrounding whitespace.
        top_names: Package and module names that exist under the code roots.

    Returns:
        ``(kind, text)`` for a selectable citation, or ``None``.
    """
    if any(ch.isspace() or ch in _NOT_IN_A_PATH for ch in content):
        return None
    if "/" in content:
        return _as_module_path(content)
    return _as_dotted_symbol(content, top_names)


def _as_module_path(content: str) -> tuple[str, str] | None:
    """Read a slash-carrying span as a b1 module path, or not at all."""
    cited = _LINE_SUFFIX_RE.sub("", _NODE_ID_RE.sub("", content)).rstrip("/")
    segments = cited.split("/")
    # A single segment names no directory, so no root can contain it: `.review/`
    # and `/review` are not module paths in any reading, and an empty segment
    # means a leading or doubled slash.
    if len(segments) < _MIN_PATH_SEGMENTS or not all(segments):
        return None
    return ("module-path", cited)


def _as_dotted_symbol(content: str, top_names: frozenset[str]) -> tuple[str, str] | None:
    """Read a dotted span as a b2 symbol, or not at all."""
    if not _DOTTED_RE.match(content):
        return None
    head, tail = content.split(".", 1)
    if tail.rsplit(".", 1)[-1].lower() in _DOCUMENT_SUFFIXES:
        return None  # `CONTRIBUTING.md` shares b2's shape and is not code.
    if not (head[:1].isupper() or head in top_names):
        return None
    return ("dotted-symbol", content)


def extract_citations(path: str, text: str, top_names: frozenset[str]) -> list[Citation]:
    """Select every citation ADR-0088 §1 defines out of one document.

    Args:
        path: The document's path relative to the repo root, for the finding.
        text: The document's whole text.
        top_names: Package and module names that exist under the code roots.

    Returns:
        Every selected citation, in document order.
    """
    found: list[Citation] = []
    for lineno, line in iter_prose_lines(text):
        for match in _DECISION_RE.finditer(line):
            found.append(Citation("decision", match.group(0), path, lineno))
        for match in _TRACKER_RE.finditer(line):
            found.append(Citation("tracker", match.group(0), path, lineno))
        for content in _iter_code_spans(line):
            classified = classify_code_span(content, top_names)
            if classified is not None:
                found.append(Citation(classified[0], classified[1], path, lineno))
    return found


# --------------------------------------------------------------------------- #
# Resolving a code citation (ADR-0088 §2(b))
# --------------------------------------------------------------------------- #


def _module_path_candidates(root: Path, cited: str) -> Iterator[Path]:
    """Yield the filesystem paths a b1 citation could mean.

    A path is a code citation "when it lies under ``src/ai_assistant/``,
    ``tests/`` or ``scripts/``, written either in full or relative to one of
    them" (ADR-0088 §1(b)), so both readings are candidates for each root.

    **A candidate that does not normalise to somewhere inside its own root is
    discarded**, which is the whole content of "defined by root". Without it
    ``src/ai_assistant/../../docs/missing.md`` reads as a full-form citation,
    normalises to ``docs/missing.md``, anchors on the existing ``docs/`` — and
    is reported as an absent module path, when §1(b) says in terms that a path
    under ``docs/`` is a document reference nothing resolves against the code.
    Containment in the *repository* is not enough to catch that; containment in
    the candidate's own root is.
    """
    for code_root in _CODE_ROOTS:
        base = (root / code_root).resolve()
        readings = [base / cited]
        if cited == code_root or cited.startswith(f"{code_root}/"):
            readings.append(root / cited)
        for candidate in readings:
            if candidate.resolve().is_relative_to(base):
                yield candidate


def _is_anchored(candidate: Path) -> bool:
    """Whether a candidate reading is anchored by an existing directory.

    This is what makes root membership *mechanical* rather than shape-based
    (ADR-0088 §1(b)): ``docs/review/guide.md`` reads as no directory under any
    code root and is therefore a document reference, where ``testing/store.py``
    anchors on ``src/ai_assistant/testing/`` and is a code citation whether or
    not the file is there. A citation nothing anchors is unevaluable and is
    dropped rather than reported (§6).
    """
    return candidate.parent.is_dir()


def resolve_module_path(root: Path, cited: str) -> bool | None:
    """Resolve a b1 module path against the tree.

    Args:
        root: The checkout root.
        cited: The path as written, with any legacy ``:NNN`` already stripped.

    Returns:
        ``True`` if it resolves, ``False`` if it is anchored but absent, and
        ``None`` if nothing anchors it — in which case it is not a code citation
        and nothing is reported.
    """
    candidates = list(_module_path_candidates(root, cited))
    if any(candidate.exists() for candidate in candidates):
        return True
    if any(_is_anchored(candidate) for candidate in candidates):
        return False
    return None


def _bound_names(node: ast.Assign | ast.AnnAssign) -> Iterator[str]:
    """Yield the plain names an assignment binds — a class-body field included."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    for target in targets:
        if isinstance(target, ast.Name):
            yield target.id


def _reexported_names(node: ast.ImportFrom | ast.Import) -> Iterator[str]:
    """Yield the names an import binds in the importing module's namespace."""
    for alias in node.names:
        bound = alias.asname or alias.name.split(".", 1)[0]
        if bound != "*":
            yield bound


def _definition_names(tree: ast.Module, *, package_init: bool) -> Iterator[str]:
    """Yield every dotted name defined in one module, relative to the module.

    A definition, per ADR-0088 §2(b), is "a ``class``, a ``def``, an assignment
    or a class-body annotation" — not any occurrence of the word, which is why
    this reads the AST instead of grepping. A free-text search would let
    ``Status`` "resolve" against a docstring.

    A name re-exported from a package's ``__init__.py`` is bound at that path and
    is the name the corpus writes: ``ai_assistant.testing.FakePlanner`` is how
    CONTRIBUTING.md names the canonical fake, and it would otherwise be reported
    against a fake that plainly exists. Re-exports are taken only from a package
    ``__init__``, so an ordinary module's imports never masquerade as its own
    surface.

    Args:
        tree: The parsed module.
        package_init: Whether this module is a package's ``__init__.py``.
    """

    def walk(node: ast.AST, prefix: str) -> Iterator[str]:
        for child in ast.iter_child_nodes(node):
            match child:
                case ast.ClassDef():
                    yield f"{prefix}{child.name}"
                    yield from walk(child, f"{prefix}{child.name}.")
                case ast.FunctionDef() | ast.AsyncFunctionDef():
                    yield f"{prefix}{child.name}"
                case ast.Assign() | ast.AnnAssign():
                    yield from (f"{prefix}{name}" for name in _bound_names(child))
                case ast.ImportFrom() | ast.Import() if package_init and not prefix:
                    yield from _reexported_names(child)
                case _:
                    pass

    yield from walk(tree, "")


def _module_dotted_names(root: Path, file: Path) -> list[str]:
    """Return the dotted module names one file may legitimately be written as."""
    relative = file.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    if not parts:
        return []
    names = [".".join(parts)]
    if parts[:2] == ["src", "ai_assistant"]:
        names.append(".".join(parts[1:]))
        names.append(".".join(parts[2:]))
    return [name for name in names if name]


def _dotted_suffixes(name: str) -> Iterator[str]:
    """Yield every dotted suffix of a qualified name, longest first.

    Indexing suffixes is what lets ``Engine._project`` resolve against
    ``ai_assistant.orchestration.engine.Engine._project``, which ADR-0088 §2(b)
    requires ("``Engine._project`` **resolves**"). It over-resolves by design:
    over-resolving costs a miss, which §6 calls benign, and under-resolving
    costs a false report, which it does not.
    """
    parts = name.split(".")
    for index in range(len(parts)):
        yield ".".join(parts[index:])


@dataclass(frozen=True)
class DefinitionIndex:
    """Every dotted name a b2 citation may resolve against.

    Attributes:
        definitions: Dotted names — and every dotted suffix of them — ending at
            a real definition site.
        modules: Dotted module and package names, and their suffixes.
    """

    definitions: frozenset[str]
    modules: frozenset[str]

    def resolves(self, cited: str) -> bool:
        """Whether the cited name is a definition or a module here."""
        return cited in self.definitions or cited in self.modules

    def is_evaluable(self, cited: str) -> bool:
        """Whether a *non*-resolving citation is evidence of anything.

        Two shapes are unevaluable rather than absent, and ADR-0088 §6 requires
        an unevaluable citation to pass silently rather than be reported:

        - **The head is not defined here.** ``Agent.run`` and ``Device.AUTO``
          name members of a vendor's class; ``P.id`` names a variable an ADR
          introduced in its own prose. Whether the member exists is a question
          about a class this repository does not define, and the checker has not
          answered it. On the corpus this silences 8 distinct citations, every
          one of them a false report, and no true one.
        - **The citation walks through a definition.** ``ToolResult.failure``
          resolves and ``.message`` is a member of whatever type it holds;
          following that needs type inference, which is exactly the reading §6
          keeps out of the tool. A two-part name is left alone, so
          ``MemoryDecisionKind.MERGE`` is still reported — correctly, and
          forever (ADR-0088 §3).
        """
        parts = cited.split(".")
        if len(parts) == _QUALIFIED_PAIR and parts[0] not in self.definitions:
            return False
        return not any(
            ".".join(parts[:stop]) in self.definitions
            for stop in range(_QUALIFIED_PAIR, len(parts))
        )


def build_definition_index(root: Path) -> DefinitionIndex:
    """Index every dotted name defined under the three code roots.

    Args:
        root: The checkout root.

    Returns:
        The index a b2 citation is resolved against.
    """
    definitions: set[str] = set()
    modules: set[str] = set()
    for code_root in _CODE_ROOTS:
        base = root / code_root
        if not base.is_dir():
            continue
        for file in sorted(base.rglob("*.py")):
            if "__pycache__" in file.parts:
                continue
            try:
                tree = ast.parse(file.read_text(encoding="utf-8"))
            except OSError, SyntaxError:
                continue
            module_names = _module_dotted_names(root, file)
            for defined in _definition_names(tree, package_init=file.name == "__init__.py"):
                definitions.update(_dotted_suffixes(defined))
                for module in module_names:
                    definitions.update(_dotted_suffixes(f"{module}.{defined}"))
            for module in module_names:
                modules.update(_dotted_suffixes(module))
    return DefinitionIndex(frozenset(definitions), frozenset(modules))


# --------------------------------------------------------------------------- #
# Liveness (ADR-0088 §4)
# --------------------------------------------------------------------------- #


def _fold(value: str) -> str:
    """Collapse a wrapped header field into one line."""
    return " ".join(value.split())


def header(text: str) -> str:
    """Return an ADR's header — everything above its first ``## `` section.

    §4 legislates a **header** line, and ADR-0070 §4 forbids discovering a
    supersession by reading prose. A body list item may legitimately look like a
    record: an ADR explaining the rule writes ``- Supersedes: ADR-A`` as an
    illustration, and comparing that as a record reports a pair nobody declared.
    The boundary is markdown's own level-2 heading and needs no numbering
    scheme, so it is not the document-structure inference §6 forbids — and it is
    measured, not assumed: every ADR on `main` carries a ``## `` heading and all
    nine reverse records sit above theirs. It is matched by markdown's rule
    rather than by the one spelling this corpus happens to use, because a
    heading written with leading spaces, or with a tab after the marker, that
    the boundary did not recognise would put the whole body back in scope — and
    the body is where an illustrative bullet lives.

    Fenced lines are blanked rather than dropped — §1's exclusion is general, so
    a fenced example inside the header is display too — and one blank line per
    fenced line keeps the newline count intact, so a match's line number is
    still the line number in the file.
    """
    kept = dict(iter_prose_lines(text))
    lines = [kept.get(number, "") for number in range(1, len(text.splitlines()) + 1)]
    for index, line in enumerate(lines):
        if _HEADING_2_RE.match(line):
            return "\n".join(lines[:index])
    return "\n".join(lines)


def status_field(text: str) -> str | None:
    """Return one ADR's whole ``Status`` field, folded onto one line."""
    match = _STATUS_RE.search(header(text))
    return None if match is None else _fold(match.group("value"))


def reverse_records(text: str) -> list[tuple[int, str, str]]:
    """Return the ``Supersedes`` / ``Partially supersedes`` records in a header.

    Returns:
        ``(lineno, kind, folded value)`` per record, in document order.
    """
    records: list[tuple[int, str, str]] = []
    head = header(text)
    for match in _SUPERSEDES_RE.finditer(head):
        lineno = head.count("\n", 0, match.start()) + 1
        records.append((lineno, _fold(match.group("kind")), _fold(match.group("value"))))
    return records


def supersessors_named(status: str) -> set[int]:
    """Return the ADR numbers a status field names *in a supersession token*.

    ADR-0088 §4 requires the token, not a bare mention: a later ADR may amend one
    clause of an earlier one and supersede another, so a status reading
    ``Accepted, §1 amended by ADR-B`` would silence a test that merely asked
    whether ``ADR-B`` appeared in the field — and miss exactly the omitted
    supersession record ADR-0070 requires.

    Extracting every ``ADR-NNNN`` after a token is safe because ADR-0070 §4's
    authoring invariant guarantees it: "a scope names a clause, not another ADR:
    it carries no ``ADR-NNNN`` token". Where the invariant is broken the effect
    is a *missed* report, which §6 prefers to a false one.
    """
    numbers: set[int] = set()
    for token in _SUPERSESSION_TOKEN_RE.finditer(status):
        for match in _DECISION_RE.finditer(status, token.end()):
            numbers.add(int(match.group(1)))
    return numbers


def _liveness_findings(adrs: dict[int, tuple[str, str]]) -> Iterator[Finding]:
    """Yield §4's one liveness report, driven by the reverse record.

    For every ADR ``B`` carrying a reverse record naming ``ADR-A``: if ``A``'s
    whole ``Status`` field does not name ``B`` in a supersession token, report
    the disagreement. Otherwise, silence — and an absent reverse record is
    silence too, never a report, which is what keeps the check quiet on a corpus
    that predates the rule.

    Args:
        adrs: ADR number -> (path relative to the repo root, whole text).
    """
    for number in sorted(adrs):
        path, text = adrs[number]
        for lineno, kind, value in reverse_records(text):
            # "The target is the first ``ADR-NNNN`` in the record, and one record
            # names one ADR" (§4). Everything after it is scope prose: the
            # corpus's scopes cite other ADRs freely, and extracting every token
            # turns three correct records into false reports.
            target = _DECISION_RE.search(value)
            if target is None:
                continue
            earlier = int(target.group(1))
            if earlier not in adrs:
                continue  # Tier 1 already has the dangling file; say it once.
            status = status_field(adrs[earlier][1])
            if status is not None and number in supersessors_named(status):
                continue
            yield Finding(
                tier=_TIER_REPORTED,
                kind="liveness",
                path=path,
                line=lineno,
                citation=f"{kind}: ADR-{earlier:04d}",
                detail=(
                    f"ADR-{number:04d} records the supersession, but ADR-{earlier:04d}'s "
                    f"Status field does not name ADR-{number:04d} in a supersession token "
                    f"— read both before trusting either"
                ),
            )


# --------------------------------------------------------------------------- #
# Tracker citations (ADR-0088 §2(c))
# --------------------------------------------------------------------------- #


def fetch_tracker_numbers(root: Path) -> frozenset[int] | None:
    """Return every issue and PR number GitHub knows, or ``None`` if unreachable.

    GitHub's REST issues endpoint returns pull requests too, so one paginated
    call covers the shared number space a ``#NNN`` citation lives in.

    Returns ``None`` — unevaluable, therefore silent (ADR-0088 §6) — when ``gh``
    is missing, unauthenticated, the call fails, or it succeeds while naming no
    number at all. That last case is deliberate: a repository always holds at
    least the issue an ADR cites, so an empty answer is a broken call rather than
    an empty tracker, and reading it as "every citation is dangling" would fail
    the whole corpus on a transport fault. A checker that cannot reach the
    tracker has learned nothing about the citation, and inventing a failure from
    that is the false report §6 forbids.
    """
    argv = [
        "gh",
        "api",
        "repos/{owner}/{repo}/issues?state=all&per_page=100",
        "--paginate",
        "--jq",
        ".[].number",
    ]
    try:
        result = subprocess.run(  # noqa: S603  # fixed argv, no shell
            argv, capture_output=True, text=True, check=True, cwd=root, timeout=120
        )
    except OSError, subprocess.SubprocessError:
        return None
    numbers = {int(line) for line in result.stdout.split() if line.strip().isdigit()}
    return frozenset(numbers) if numbers else None


# --------------------------------------------------------------------------- #
# The check
# --------------------------------------------------------------------------- #


def load_adrs(root: Path) -> dict[int, tuple[str, str]]:
    """Return every numbered ADR: number -> (relative path, whole text)."""
    adrs: dict[int, tuple[str, str]] = {}
    directory = root / "docs" / "adr"
    if not directory.is_dir():
        return adrs
    for file in sorted(directory.rglob("*.md")):
        match = _ADR_FILENAME_RE.match(file.name)
        if match is None:
            continue
        adrs[int(match.group(1))] = (
            file.relative_to(root).as_posix(),
            file.read_text(encoding="utf-8"),
        )
    return adrs


def _adr_documents(root: Path) -> list[tuple[str, str]]:
    """Return every document under ``docs/adr`` — the template included.

    The template is scanned like any other ADR: ADR-0088 §1's forms are defined
    over what an ADR file contains, and the template contains real decision
    citations (``ADR-0070``, ``ADR-0001``) alongside its ``ADR-XXXX``
    placeholders, which are not four digits and therefore not citations.
    """
    directory = root / "docs" / "adr"
    if not directory.is_dir():
        return []
    return [
        (file.relative_to(root).as_posix(), file.read_text(encoding="utf-8"))
        for file in sorted(directory.rglob("*.md"))
    ]


def check(root: Path, *, tracker_numbers: Iterable[int] | None) -> Report:
    """Run every check ADR-0088 §6 permits over one checkout.

    Args:
        root: The checkout root.
        tracker_numbers: Every issue/PR number that exists, or ``None`` when the
            tracker could not be read — in which case tracker citations are
            unevaluable and pass silently (§6).

    Returns:
        The whole report, Tier 1 findings first.
    """
    adrs = load_adrs(root)
    known_trackers = None if tracker_numbers is None else frozenset(tracker_numbers)
    definitions = build_definition_index(root)
    top_names = top_level_names(root)

    findings: list[Finding] = []
    counts = {"decision": 0, "tracker": 0, "module-path": 0, "dotted-symbol": 0}

    for path, text in _adr_documents(root):
        for citation in extract_citations(path, text, top_names):
            counts[citation.kind] = counts.get(citation.kind, 0) + 1
            finding = _judge(citation, adrs, known_trackers, definitions, root)
            if finding is not None:
                findings.append(finding)

    findings.extend(_liveness_findings(adrs))

    notes: list[str] = []
    if known_trackers is None:
        notes.append(
            "Tracker citations were not checked: `gh` is unavailable or the call failed. "
            "An unevaluable citation passes silently (ADR-0088 §6)."
        )

    findings.sort(key=lambda f: (f.tier, f.path, f.line, f.citation))
    return Report(
        findings=tuple(findings),
        counts=counts,
        tracker_checked=known_trackers is not None,
        notes=tuple(notes),
    )


#: The one sentence every Tier 2 code finding carries. §3 is the whole reason
#: these are reported rather than failed, so the finding says so where it is
#: read rather than only in the ADR.
_APPEND_ONLY = "which an append-only corpus may write correctly (ADR-0088 §3)"


def _finding(citation: Citation, tier: int, detail: str) -> Finding:
    """Build a finding for one citation."""
    return Finding(
        tier=tier,
        kind=citation.kind,
        path=citation.path,
        line=citation.line,
        citation=citation.text,
        detail=detail,
    )


def _judge(
    citation: Citation,
    adrs: dict[int, tuple[str, str]],
    known_trackers: frozenset[int] | None,
    definitions: DefinitionIndex,
    root: Path,
) -> Finding | None:
    """Return the finding one citation earns, or ``None`` if it is silent."""
    match citation.kind:
        case "decision":
            return _judge_decision(citation, adrs)
        case "tracker":
            return _judge_tracker(citation, known_trackers)
        case "module-path":
            return _judge_module_path(citation, root)
        case "dotted-symbol":
            return _judge_dotted_symbol(citation, definitions)
        case _:  # pragma: no cover - the kinds are closed
            return None


def _judge_decision(citation: Citation, adrs: dict[int, tuple[str, str]]) -> Finding | None:
    """Tier 1: an ADR file is never deleted, so a missing one is always a defect."""
    number = int(citation.text.removeprefix("ADR-"))
    if number in adrs:
        return None
    return _finding(citation, _TIER_FAILING, f"no docs/adr/{number:04d}-*.md exists")


def _judge_tracker(citation: Citation, known: frozenset[int] | None) -> Finding | None:
    """Tier 1: an issue number once assigned stays assigned (ADR-0088 §2(c)).

    Issue *state* is not read. Recognising "``#NNN`` tracks the conversion" as a
    claim about state means separating an assertion from a quotation or a
    negation, which is the prose inference §6 forbids — ADR-0088 quotes another
    ADR's "#281 is discharged" in order to call it false, and a phrase-matching
    check would report the refutation as the claim.
    """
    if known is None or int(citation.text.removeprefix("#")) in known:
        return None
    return _finding(citation, _TIER_FAILING, "no issue or pull request with this number exists")


def _judge_module_path(citation: Citation, root: Path) -> Finding | None:
    """Tier 2: b1 resolves against the filesystem, and never fails (§3)."""
    if resolve_module_path(root, citation.text) is not False:
        return None
    return _finding(
        citation,
        _TIER_REPORTED,
        f"no such file under src/ai_assistant/, tests/ or scripts/ — {_APPEND_ONLY}",
    )


def _judge_dotted_symbol(citation: Citation, definitions: DefinitionIndex) -> Finding | None:
    """Tier 2: b2 resolves against a definition site, and never fails (§3)."""
    if definitions.resolves(citation.text) or not definitions.is_evaluable(citation.text):
        return None
    return _finding(
        citation,
        _TIER_REPORTED,
        f"no definition under src/ai_assistant/, tests/ or scripts/ — {_APPEND_ONLY}",
    )


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

_TIER2_HEADINGS = {
    "module-path": "Module paths that do not resolve (b1)",
    "dotted-symbol": "Dotted symbols that do not resolve (b2)",
    "liveness": "Liveness disagreements",
}


def format_text(report: Report) -> str:
    """Render the report for a terminal."""
    lines: list[str] = []
    counts = report.counts
    lines.append(
        "Citations selected: "
        f"{counts.get('decision', 0)} decision, "
        f"{counts.get('tracker', 0)} tracker, "
        f"{counts.get('module-path', 0)} module path (b1), "
        f"{counts.get('dotted-symbol', 0)} dotted symbol (b2)."
    )
    lines.append(
        "Not checked, by ADR-0088 §6: bare backticked tokens (b3), section "
        "numbers, issue state, anything inside a fence."
    )
    for note in report.notes:
        lines.append(f"note: {note}")

    lines.append("")
    lines.append(f"Tier 1 — fails the change ({len(report.tier1)})")
    if not report.tier1:
        lines.append("  none")
    for finding in report.tier1:
        lines.append(f"  {finding.location()}  {finding.citation} — {finding.detail}")

    lines.append("")
    lines.append(
        f"Tier 2 — reported, never fails ({len(report.tier2)}). "
        "A non-empty list is expected: ADR-0088 §3 records three classes an "
        "append-only corpus cites correctly and the tree does not hold."
    )
    for kind, heading in _TIER2_HEADINGS.items():
        group = [f for f in report.tier2 if f.kind == kind]
        lines.append(f"  {heading} ({len(group)})")
        for finding in group:
            lines.append(f"    {finding.location()}  {finding.citation} — {finding.detail}")
    return "\n".join(lines)


def format_markdown(report: Report) -> str:
    """Render the report as markdown, for a CI job summary."""
    lines = ["## ADR citation check (ADR-0088 §6)", ""]
    counts = report.counts
    lines.append(
        f"Selected **{counts.get('decision', 0)}** decision, "
        f"**{counts.get('tracker', 0)}** tracker, "
        f"**{counts.get('module-path', 0)}** module-path (b1) and "
        f"**{counts.get('dotted-symbol', 0)}** dotted-symbol (b2) citations. "
        "Bare tokens (b3), section numbers, issue state and fenced content are "
        "not checked."
    )
    for note in report.notes:
        lines.extend(["", f"> {note}"])

    lines.extend(["", f"### Tier 1 — fails the change ({len(report.tier1)})", ""])
    if not report.tier1:
        lines.append("None.")
    else:
        lines.extend(["| where | citation | detail |", "|---|---|---|"])
        lines.extend(f"| `{f.location()}` | `{f.citation}` | {f.detail} |" for f in report.tier1)

    lines.extend(["", f"### Tier 2 — reported, never fails ({len(report.tier2)})", ""])
    lines.append(
        "A non-empty list is expected. ADR-0088 §3 names three classes an "
        "append-only corpus cites correctly and the tree does not hold: not yet "
        "built, deliberately removed, and considered and declined."
    )
    for kind, heading in _TIER2_HEADINGS.items():
        group = [f for f in report.tier2 if f.kind == kind]
        lines.extend(["", f"**{heading} ({len(group)})**", ""])
        if not group:
            lines.append("None.")
            continue
        lines.extend(["| where | citation | detail |", "|---|---|---|"])
        lines.extend(f"| `{f.location()}` | `{f.citation}` | {f.detail} |" for f in group)
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="checkout to check (default: this script's repository)",
    )
    parser.add_argument(
        "--no-tracker",
        action="store_true",
        help="skip tracker citations instead of asking GitHub about them",
    )
    parser.add_argument(
        "--format",
        choices=("text", "markdown", "json"),
        default="text",
        help="output format (default: text)",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="also append the markdown report to this file (a CI job summary)",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="always exit 0, even on a Tier 1 finding",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check and print the report.

    Returns:
        1 when a Tier 1 finding exists and ``--report-only`` was not passed,
        else 0. Tier 2 never affects the exit code (ADR-0088 §3, §6).
    """
    args = _parse_args(argv)
    root = args.root.resolve()
    trackers = None if args.no_tracker else fetch_tracker_numbers(root)
    report = check(root, tracker_numbers=trackers)

    renderers = {"text": format_text, "markdown": format_markdown}
    if args.format == "json":
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print(renderers[args.format](report))

    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(format_markdown(report) + "\n")

    return 1 if report.tier1 and not args.report_only else 0


if __name__ == "__main__":
    sys.exit(main())
