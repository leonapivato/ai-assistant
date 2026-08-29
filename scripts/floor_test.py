#!/usr/bin/env python3
"""ADR-0209 §§1-6 — does a base move's floor actually bind this pull request?

ADR-0027 §3 put nine paths in a floor and said a base move touching any of them
invalidates every review artifact outright. The floor is a **path** test standing
in for a **relation** — "the moved text bears on this PR" — chosen in July 2026
because the relation was not mechanically checkable. ADR-0209 narrows half of it:
the ``docs/adr/**`` and contract-surface entries now bind only where one of four
tests binds, and this module is those tests.

What it decides, per entry of the base move's file set:

- **§1, absolute.** ``docs/review/**``, ``CLAUDE.md``, ``CONTRIBUTING.md`` and
  ``scripts/codex-review.sh`` bind unconditionally, for every persona. Those are
  the instructions the reviewer is conducted under, so they bind *every* diff by
  construction and no test is consulted.
- **§3, a moved ADR.** Binds where the PR's text writes that ADR's number, or
  where the ADR's own text names a path this PR's diff touches or a symbol an
  added or removed line of that diff carries. A **symbol** is a backticked
  token that names a definition this repository's Python carries, or that a
  changed line of one of its non-Python source files carries — see below.
  Both endpoints of a rename are read, because §3's listing is rename-aware and
  an ADR renamed out of the tree is still the decision the review was taken
  under.
- **§4, a moved contract file.** ``core/protocols.py`` binds unconditionally
  where the move adds a ``Protocol`` or widens any ``Protocol``'s *effective*
  member surface — the members it declares plus those it inherits from its
  ``Protocol`` bases — because "a diff that now *should* consume it" is a
  relation the PR's own text cannot witness. Otherwise, and for
  ``core/types.py``, it binds where this PR's diff touches ``core/`` or where a
  name whose definition the move changed occurs in the PR's text.
- **§6, fail closed.** Any test that cannot be evaluated binds. A parse failure,
  an unresolvable base, an unreadable endpoint, a missing PR description, an
  entry whose status this module does not know — each of them costs the round.
  §6 is a *rule*, not a list, so the fallback is a bare ``except`` around each
  entry rather than an enumeration of the failures anyone thought of.

**What §3's word "symbol" means, and why the shape of a token is not it.**
ADR-0088 §1(b) defines a code citation as "a backticked name **identifying
something in the repository**", and ADR-0209 §3 rests on exactly that form: a
decision that governs a PR "is written in ADR-0088's citation form: it names the
paths it governs and the symbols it constrains". §5 reuses `brief_check.py`'s
extraction for the naming, and that extraction is two halves. :func:`classify`
is the first — a *triage* by shape, whose own contract is ":data:`SYMBOL` for
something **shaped like** a Python name" and whose comment says a dot, an
underscore or a capital "is what makes a token worth searching for". The search
is the second half, and `brief_check` does it: :func:`brief_check.grep_symbols`
looks each candidate up in the tree and reports one found nowhere as absent.
ADR-0088 §1's b3 says why both halves are needed — a bare backticked token is
"**not mechanically separable** from the vocabulary the corpus also backticks".

This module used to stop at the triage, and issue #1799 is what that cost: on
PR #1795 five ADRs bound because they name ``None``, ``Status`` and ``Proposed``
— ADR-0070 §4's header vocabulary and a Python literal, carried by essentially
every ADR and written into every ADR PR's own diff — and PR #1786 bound on
``ai_assistant``, the package name. Any two ADR lanes matched unconditionally, so
the narrowing was inert for the lane type ADR-0209's Consequences names as the
clearest case it relieves ("a process or docs lane"). So a ``symbol`` token is
tested here for what §3 asks of it: its **member** — the token, or the last part
of a dotted one — must name a definition in this repository's source at either
endpoint §5 gives for the PR. A package or module name is deliberately not a
definition: whether the PR changes that module is the *path* test's question, and
answering it twice would restore the match this closes.

**That is an evaluation, not a failure to evaluate.** §6 binds a test that
*cannot* be evaluated; a token searched for and demonstrably found nowhere has
been evaluated, and the answer is that it is not a symbol. What binds under §6 is
the resolver failing — an endpoint git will not read, or a Python file that will
not parse — and it does, through the same ``except`` every other test here falls
into. The search is deliberately generous in every other direction, per ADR-0209
§5's asymmetry.

**Python is resolved; the other two languages are answered from the diff side
instead.** All but four of this repository's source files are Python, and those
are read with :mod:`ast`, so what counts as a definition is decided by the
language rather than by an enumeration of it. Both endpoints are read,
deduplicated by blob, so a definition the PR itself deletes still resolves on the
side that has it. The four that are left — one JavaScript file and three shell
scripts — are not resolved at all. A token naming no Python definition is still a
symbol where a changed line of one of the PR's **non-Python source** files
carries it as a word: the rule this module applied to every token before #1799,
kept here as the fallback.

**The fallback is what ends an enumeration, and dropping those files would
under-bind.** Four consecutive rounds of PR #1803's own review each found a
definition form the line pattern of the day did not have — ``export function``,
``async function*``, ``type UtcInstant = ...``, then a class method written
behind ``async``/``static``/``get`` — so the pattern is deleted rather than
extended a fifth time. Reading only Python was the other way to delete it, and it
is the direction ADR-0209 §5 forbids: an ADR naming a function in ``app.js`` that
a PR's diff changes would clear, and §3's path test answers for a cited *path*,
never for a function inside one. What is left over-binds only where a moved ADR
names a word some JavaScript or shell line of the diff happens to carry — the
priced direction, and rare on four tracked files. Prose is still not source,
which is the whole of what #1799 was matching.

**No pattern is left anywhere in this path, and that is the point.** The line
reader for a Python file :mod:`ast` refuses was the last one, and adversarial
review found it short of `type Widget = object` — the same defect a fifth time,
now in the fallback rather than in the reader. So a file that will not parse binds
under §6, which names a parse failure as its own first instance, instead of being
read by a grammar nobody can finish enumerating.

**One implementation, called from one place.** ADR-0209 §6 requires that
``scripts/ship.sh``'s acceptance loop and its ``--drill`` share it, and issue
#751 records what two statements of one acceptance rule cost: a hand-built
replica returned "floor clear" for a base move that in fact breached the floor,
twice. ``ship.sh`` calls this module once per base move and both paths read the
same answer, per entry, with the reason it was reached.

The interface is deliberately blunt so the shell caller cannot mis-parse it.
Every string crossing it is NUL-terminated, because git permits a pathname
containing a newline and a line-oriented protocol would split one such name into
two apparent records:

- **stdin** — the base move's file set as ``git diff --name-status -M -z`` gives
  it, three NUL-terminated fields per entry: status, source, destination (empty
  where the status carries no second path).
- **stdout** — three NUL-terminated fields per *input* entry, in the same order:
  ``1``/``0`` for whether any endpoint is a floor path, ``bind``/``free``/``-``,
  and the reason. Position is the join, never the pathname, so a name this module
  echoed back could not be mistaken for one git reported.
- **exit status** — 0 when every entry was judged, 2 when the invocation itself
  was malformed. A non-zero exit is the caller's cue to bind the whole move;
  every failure this module can attribute to an entry is reported as that entry
  binding under §6 instead, so the caller learns *which* path cost the round.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from citations import FILE, PATH, SYMBOL, adr_numbers, classified_tokens, word_in

if TYPE_CHECKING:
    from collections.abc import Sequence

# --- ADR-0027 §3's floor, split by ADR-0209 §§1-2 -----------------------------
#
# The union of these two sets is ADR-0027 §3's enumeration exactly, and this is
# now the only place in the repository that states it: `ship.sh` used to carry
# its own `_is_floor_path` and no longer does, because a second spelling of the
# membership test is the shape issue #751 is about. What ADR-0209 changes is not
# the membership but what a member *costs* — §1's four bind outright, §2's
# three bind only where a test in §§3-4 binds.
_ABSOLUTE_PREFIXES = ("docs/review/",)
_ABSOLUTE_PATHS = frozenset({"CLAUDE.md", "CONTRIBUTING.md", "scripts/codex-review.sh"})
_ADR_PREFIX = "docs/adr/"
_PROTOCOLS = "src/ai_assistant/core/protocols.py"
_TYPES = "src/ai_assistant/core/types.py"
_CORE_PREFIX = "src/ai_assistant/core/"

# `docs/adr/0209-a-floor-....md` → 209. A file under `docs/adr/` that does not
# carry a number is not a decision this rule can test §3's first limb against,
# and falls to §6.
_ADR_FILE_RE = re.compile(r"^(\d{3,4})-.*\.md$")

# A definition in one of the two contract files: a class, a `def`, or a bound
# name — which is what an enum member and an annotated attribute look like.
# ADR-0209 §4's second limb turns on "a name whose *definition* the move
# changed", never on every identifier a hunk happens to contain. Nothing in §3's
# symbol path reads it: a Python file `ast` refuses binds under §6 rather than
# falling back to a pattern.
# `--- a/path`, `+++ b/path`, `--- /dev/null`. The prefixes are pinned by the
# caller's `_diff_opts` (`diff.noprefix=false`, `diff.mnemonicPrefix=false`), so
# these are the only three shapes the rendered patch can carry.
_FILE_HEADER_RE = re.compile(r"^(?:\+\+\+|---) (?:a/|b/|/dev/null)")

_DEFINITION_RE = re.compile(
    r"^\s*(?:async\s+)?def\s+(?P<def>[^\W\d]\w*)"
    r"|^\s*class\s+(?P<cls>[^\W\d]\w*)"
    r"|^\s*(?P<bound>[^\W\d]\w*)\s*(?::[^=\n]+)?=(?!=)",
    re.UNICODE,
)

# --- §3's "symbol": what the repository actually defines -----------------------
#
# The source this repository writes, split by how each half is read. A definition
# in a language it does not write is not one it can have, and a `docs/**` or `.md`
# "definition" is prose — which is the whole of what #1799 was matching, and the
# reason the fallback below is scoped to source rather than to "not Python".
_PYTHON_SUFFIX = ".py"
_OTHER_SOURCE_SUFFIXES = (".js", ".sh")

#: Fields in one `git ls-tree -r -z` record's first half, and in one
#: `git cat-file --batch` header: `<mode> <type> <oid>` and `<oid> <type> <size>`.
#: Fewer than three of either is git answering something this cannot read, and §6
#: binds rather than guessing at the boundary.
_GIT_RECORD_FIELDS = 3

# **Python is read with `ast`, not with a pattern**, because a pattern here is an
# enumeration of a grammar and the grammar keeps winning. Four successive rounds
# of PR #1803's own review found a form the enumeration of the day did not have —
# `export function`, `async function*`, `type UtcInstant = ...`, a class method
# behind `async` — and each miss is silent and one-directional: a name the resolver
# cannot see is a symbol judged not to be one, so a floor path clears and an owed
# round is not charged. ADR-0209 §6 makes exactly this argument about its own tests
# ("an enumeration is a proxy for the property that is wanted, and it decays"), and
# `ast` is the property itself: every name Python *binds*, decided by Python.
#
# There is no second pattern for the other two languages. A name in one of the four
# JavaScript and shell files is reached by `Pr.non_python_changed_lines` instead —
# the diff side of the same question, which needs no grammar at all.

# What a `Store` context does not cover, because Python's own node types carry the
# name instead of a `Name` node.
_NAMED_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# `--- a/path` and `+++ b/path`, with the path captured. The `a/`/`b/` prefixes are
# pinned by the caller's `_diff_opts`, and a `diff --git` line resets the section,
# so a patch is attributed to files without any second git invocation. A pathname
# git chose to quote does not match, and its lines are then admitted to the
# fallback — over-binding, which is the priced direction.
_DIFF_PATH_RE = re.compile(r"^(?:\+\+\+|---) [ab]/(?P<path>.*)$")

# Resolved once: `subprocess.run` with a bare "git" is a partial executable path,
# and this module runs inside `ship`, which has already established that git is
# where it is.
_GIT = shutil.which("git") or "git"

BIND = "bind"
FREE = "free"
NOT_FLOOR = "-"

_REASON_MAX = 200


def _clean(text: str) -> str:
    """Return ``text`` fit to cross the shell boundary and land in a report.

    A reason quotes a pathname or a citation, and git permits a pathname
    containing a newline, a NUL is the field separator, and an ESC repaints an
    operator's terminal. Control bytes become spaces here rather than being
    escaped, because a reason is prose about the evidence and the evidence itself
    is published beside it under ADR-0027 §4's own encoder.

    Args:
        text: The reason as this module built it.

    Returns:
        A single-line string of at most :data:`_REASON_MAX` characters.
    """
    flat = "".join(" " if ch < " " or ch == "\x7f" else ch for ch in text)
    flat = " ".join(flat.split())
    return flat if len(flat) <= _REASON_MAX else flat[: _REASON_MAX - 1] + "…"


@dataclass(frozen=True)
class Entry:
    """One entry of a file set, read at both of the endpoints it has.

    Attributes:
        status: git's ``--name-status`` letter, ``R100`` and friends included.
        src: The source pathname.
        dst: The destination pathname, empty where the status carries none.
    """

    status: str
    src: str
    dst: str

    def endpoints(self, old: str, new: str) -> list[tuple[str, str]] | None:
        """Return ``(path, commit)`` for each endpoint this entry has.

        ADR-0209 §5: an endpoint that does not exist is not a failure to read
        one. A file the move adds has no old-side endpoint, one it deletes no
        new-side endpoint, and a rename has one of each under two names.

        Args:
            old: The commit the base moved from.
            new: The commit it moved to.

        Returns:
            The endpoints, or None where the status is one this module does not
            know — which §6 binds on rather than guessing at.
        """
        letter = self.status[:1]
        if letter in {"R", "C"}:
            return [(self.src, old), (self.dst, new)]
        if letter == "A":
            return [(self.src, new)]
        if letter == "D":
            return [(self.src, old)]
        if letter in {"M", "T"}:
            return [(self.src, old), (self.src, new)]
        return None


class UnevaluableError(Exception):
    """A test could not be evaluated, so ADR-0209 §6 binds the base move."""


def _run_git(repo: Path, args: list[str], *, stdin: bytes | None = None) -> bytes:
    """Return a git command's stdout, raising :class:`UnevaluableError` on failure.

    Args:
        repo: The checkout to run in.
        args: The command, without the leading ``git``.
        stdin: Bytes to write to the command, for the one that reads a request
            list rather than taking it in argv.
    """
    try:
        result = subprocess.run(  # noqa: S603  # resolved git path, no shell
            [_GIT, *args], cwd=repo, capture_output=True, check=False, input=stdin
        )
    except OSError as exc:  # pragma: no cover - git is on PATH wherever ship runs
        raise UnevaluableError(f"git could not be run ({exc})") from exc
    if result.returncode != 0:
        raise UnevaluableError(f"`git {' '.join(args[:2])}` failed for this endpoint")
    return result.stdout


def _blob(repo: Path, commit: str, path: str) -> str:
    """Return one endpoint's whole content, or raise :class:`UnevaluableError`."""
    raw = _run_git(repo, ["show", f"{commit}:{path}"])
    return raw.decode("utf-8", errors="replace")


def _python_blobs(repo: Path, commits: Sequence[str]) -> list[tuple[str, bytes]]:
    """Every distinct Python blob across ``commits``, with a path it appears under.

    Deduplicated by object id, which is what makes reading two endpoints cost one
    pass and a little: the base and the head of a pull request share every file the
    PR does not touch, and git names those files by the same blob.

    Args:
        repo: The checkout to read.
        commits: The commits to read, in the order their duplicates should resolve.

    Returns:
        ``(path, content)`` per distinct blob.

    Raises:
        UnevaluableError: git would not list or read a tree (ADR-0209 §6).
    """
    wanted: dict[str, str] = {}
    for commit in commits:
        listing = _run_git(repo, ["ls-tree", "-r", "-z", commit]).split(b"\0")
        for record in listing:
            if not record:
                continue
            info, _, raw_path = record.partition(b"\t")
            name = raw_path.decode("utf-8", errors="surrogateescape")
            fields = info.split(b" ")
            if len(fields) < _GIT_RECORD_FIELDS or not name.endswith(_PYTHON_SUFFIX):
                continue
            wanted.setdefault(fields[2].decode(), name)

    if not wanted:
        return []
    # One `cat-file --batch`, NUL-delimited in both directions: a pathname is never
    # written into it (object ids are), and the answer is read back by length.
    raw = _run_git(
        repo,
        ["cat-file", "--batch", "-z"],
        stdin=b"".join(oid.encode() + b"\0" for oid in wanted),
    )
    blobs: list[tuple[str, bytes]] = []
    offset = 0
    for name in wanted.values():
        # `<oid> <type> <size>\n<contents>\n`, one record per requested object.
        end = raw.index(b"\n", offset)
        header = raw[offset:end].split(b" ")
        if len(header) < _GIT_RECORD_FIELDS:
            raise UnevaluableError(f"`git cat-file` would not read a blob ({header!r})")
        size = int(header[2])
        start = end + 1
        blobs.append((name, raw[start : start + size]))
        offset = start + size + 1
    return blobs


def _python_definitions(source: bytes, path: str) -> set[str]:
    """Every name a Python module binds, decided by Python.

    ``Store`` context is the language's own statement of "a name is being bound
    here", so it reaches an assignment, an annotated attribute, a `for` target, a
    `with ... as`, a walrus and a comprehension target without any of them being
    enumerated. What is added beside it is every node type that carries its bound
    name as a plain ``str`` rather than as a :class:`ast.Name`: a `def`, a `class`,
    a `type` alias, `global`/`nonlocal`, a `case` capture and an `except ... as`.

    **An import is not a definition.** ``from ai_assistant.core import types`` binds
    two names that this module defines nowhere, and reading them as definitions is
    PR #1786's shape exactly — the package name matching every diff that mentions
    it. Where an imported name is a real symbol, the file that defines it is in this
    same tree and supplies it. A parameter is excluded for the same reason: it binds
    a name without defining anything ADR-0088 §1's citation form could name.

    **A file that will not parse binds, and is not read by a pattern instead.**
    ADR-0209 §6 names "a parse failure at either endpoint" as its own first
    instance, and the alternative was tried in this module and failed on its own
    terms: a line-oriented fallback is another enumeration of Python's grammar, and
    a form it lacks — `type Widget = object` was the one adversarial review found —
    drops a real definition out of the index silently, which clears a floor that
    was owed. Binding is loud, is the priced direction, and needs no grammar.

    Args:
        source: One file's bytes.
        path: The name it was read under, for the reason §6 publishes.

    Returns:
        Every name the module binds.

    Raises:
        UnevaluableError: the file will not parse, so the test over it is
            undecidable and ADR-0209 §6 binds.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise UnevaluableError(f"`{path}` will not parse: {exc}") from exc
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, _NAMED_DEFINITIONS):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
            names.add(node.name.id)
        elif isinstance(node, ast.Global | ast.Nonlocal):
            names.update(node.names)
        elif isinstance(node, ast.MatchAs | ast.MatchStar | ast.MatchMapping):
            # A `case` capture binds through a `str` field rather than a `Name`.
            captured = node.rest if isinstance(node, ast.MatchMapping) else node.name
            if captured is not None:
                names.add(captured)
        elif isinstance(node, ast.ExceptHandler) and node.name is not None:
            names.add(node.name)
    return names


def defined_names(repo: Path, commits: Sequence[str]) -> set[str]:
    """Every name this repository's **Python** defines across ``commits``.

    The set is over-inclusive by construction — a local counts, a name under a
    `TYPE_CHECKING` guard counts — because it decides whether a backticked token is
    a *symbol* at all, and ADR-0209 §5 prices over-binding as acceptable and
    forbids the converse. A file that will not parse is the one case it cannot be
    generous about, so that one raises and §6 binds.

    JavaScript and shell are deliberately absent: nothing resolves them, and a
    name of theirs reaches §3 through :attr:`Pr.non_python_changed_lines` instead.

    Args:
        repo: The checkout to read.
        commits: The commits to read it at.

    Returns:
        The names, bare and unqualified.

    Raises:
        UnevaluableError: git would not read a tree, or a file it read will not
            parse. Both are ADR-0209 §6's case.
    """
    names: set[str] = set()
    for path, blob in _python_blobs(repo, commits):
        names |= _python_definitions(blob, path)
    return names


# --- The two texts (ADR-0209 §5) ---------------------------------------------


@dataclass
class Pr:
    """The PR's diff, text and files — §5's three inputs, read once.

    Every attribute is computed lazily, because a base move whose file set holds
    no floor path at all asks none of these questions and should pay for none of
    them.

    Attributes:
        repo: The checkout to read.
        base: The PR's merge base — the left edge of §5's range.
        head: The content commit, re-anchored to ``HEAD``'s parent where
            ADR-0165 §3 re-anchors the acceptance loop.
        diff_text: The rendered patch, as ``ship`` computed it under its pinned
            options.
        listing: The same range's ``--name-status -M -z`` entries.
        descriptions: The PR description(s) admitted to §5's text.
    """

    repo: Path
    base: str
    head: str
    diff_text: str
    listing: list[Entry]
    descriptions: list[str] = field(default_factory=list)

    @cached_property
    def changed_lines(self) -> str:
        """The added and removed lines of the PR's diff, and nothing else.

        The ``+++``/``---`` file headers are dropped: they carry pathnames, not
        content, and §5's tests about "a symbol an added or removed line
        carries" would otherwise be satisfied by the *filename* of every file
        the PR touches. They are recognised by their whole shape rather than by
        their first three characters, because a *removed* line whose own content
        begins with ``--`` renders as ``---…`` and is content, not a header.
        """
        kept = [
            line
            for line in self.diff_text.splitlines()
            if line[:1] in {"+", "-"} and _FILE_HEADER_RE.match(line) is None
        ]
        return "\n".join(kept)

    @cached_property
    def text(self) -> str:
        """§5's **PR's text**: the changed lines plus the description(s)."""
        return "\n".join([self.changed_lines, *self.descriptions])

    @cached_property
    def adrs(self) -> set[int]:
        """Every ADR number the PR's text cites."""
        return adr_numbers(self.text)

    @cached_property
    def endpoints(self) -> list[str]:
        """Every endpoint pathname of every entry of the PR's diff."""
        seen: list[str] = []
        for entry in self.listing:
            for path in (entry.src, entry.dst):
                if path and path not in seen:
                    seen.append(path)
        return seen

    @cached_property
    def path_components(self) -> set[str]:
        """Each directory name, and each filename's stem, of those endpoints.

        §5 lets a dotted citation's *qualifier* be satisfied by a path component
        as well as by a word in one of the PR's files, because a module path is
        written in the filename rather than in the file: a PR adding
        ``class SqliteStore`` to ``src/ai_assistant/memory/store.py`` need never
        write the words ``memory`` or ``store`` inside it.
        """
        components: set[str] = set()
        for path in self.endpoints:
            parts = path.split("/")
            components.update(parts[:-1])
            components.add(parts[-1])
            components.add(parts[-1].rpartition(".")[0] or parts[-1])
        return components

    @cached_property
    def files_text(self) -> str:
        """§5's **PR's files**: every touched path's whole content, both sides.

        An endpoint that does not exist is skipped — that is what adding or
        deleting a file looks like — while an endpoint that exists and will not
        be read raises, and §6 binds.
        """
        chunks: list[str] = []
        for entry in self.listing:
            endpoints = entry.endpoints(self.base, self.head)
            if endpoints is None:
                raise UnevaluableError(f"the PR's diff carries an unknown status '{entry.status}'")
            chunks.extend(_blob(self.repo, commit, path) for path, commit in endpoints)
        return "\n".join(chunks)

    @cached_property
    def defined_names(self) -> frozenset[str]:
        """Every name this repository's Python defines at either of §5's endpoints.

        Both, and not only the head: a PR that *deletes* a definition the moved
        ADR cites carries that name on a removed line and defines it nowhere at
        head, and reading the head alone would clear the floor on precisely the
        PR the moved ADR is about.
        """
        return frozenset(defined_names(self.repo, [self.base, self.head]))

    @cached_property
    def non_python_changed_lines(self) -> str:
        """The changed lines lying in a source file this module does not resolve.

        §3's symbol test still needs an answer for JavaScript and shell, and a
        resolver for them is an enumeration of two more grammars — the shape four
        rounds of PR #1803's own review kept defeating, one form at a time. So
        those languages are answered from the *diff* side instead: a token no
        Python definition accounts for is a symbol where a line this PR adds or
        removes in one of them carries it as a word. That is the rule this module
        applied to every token before #1799, narrowed to where it is still the
        best available reading.

        **Scoped to source, and not to "every file that is not Python."** Prose is
        what #1799 was matching: `docs/adr/template.md` puts `- Status: Proposed`
        at the head of every ADR, so admitting `.md` here would restore the
        unconditional match between any two ADR lanes that the resolver closed.

        The attribution is read off the patch's own `--- a/…` / `+++ b/…` headers
        rather than by asking git a second time: `ship` renders the patch once,
        under pinned options, and this module is handed that text.
        """
        kept: list[str] = []
        admitted = False
        for line in self.diff_text.splitlines():
            if line.startswith("diff --git "):
                admitted = False
            elif (header := _DIFF_PATH_RE.match(line)) is not None:
                admitted = admitted or header["path"].endswith(_OTHER_SOURCE_SUFFIXES)
            elif _FILE_HEADER_RE.match(line) is not None:
                continue
            elif admitted and line[:1] in {"+", "-"}:
                kept.append(line)
        return "\n".join(kept)

    def is_symbol(self, member: str) -> bool:
        """Whether ``member`` is a name ADR-0209 §3 can be about at all.

        ADR-0088 §1(b) is "a backticked name identifying something in the
        repository", and there are two ways to identify something here: a
        definition this repository's Python carries at either of §5's endpoints,
        or a word a changed line of one of the PR's JavaScript or shell files
        carries. The resolver is asked first, so a resolver that will not answer
        raises and §6 binds rather than the fallback quietly standing in for it.
        """
        return member in self.defined_names or word_in(member, self.non_python_changed_lines)

    def touches_under(self, prefix: str) -> bool:
        """Whether any endpoint of the PR's diff lies under ``prefix``."""
        return any(path.startswith(prefix) for path in self.endpoints)

    def names_path(self, token: str) -> bool:
        """Whether a ``path`` token names a path the PR's diff touches.

        §5: it does when it *equals*, or is a *directory prefix of*, either
        endpoint of an entry of that diff. A trailing ``/`` and a trailing glob
        are cut back to the directory they anchor first — ``docs/adr/**`` is how
        the corpus writes a tree, and ADR-0088 §1's form is what this extraction
        reads — which can only widen the match, the direction ADR-0209 §5 prices
        as acceptable and the opposite of the one it forbids.
        """
        cleaned = token.rstrip("/")
        if "*" in cleaned:
            cleaned = cleaned[: cleaned.index("*")].rpartition("/")[0]
        if not cleaned:
            return False
        return any(path == cleaned or path.startswith(cleaned + "/") for path in self.endpoints)

    def names_file(self, token: str) -> bool:
        """Whether a ``file`` token equals the basename of a touched endpoint."""
        return any(path.rpartition("/")[2] == token for path in self.endpoints)

    def names_symbol(self, token: str) -> bool:
        """Whether a ``symbol`` token is one this PR's diff carries (§5).

        The whole token in an added or removed line satisfies it outright. A
        *dotted* token is otherwise split, because a definition never carries its
        own qualification: a PR adding ``MemoryStore.ingest`` writes
        ``async def ingest``, and no line of its diff holds the dotted string.
        So the **member** must be touched — its name in a changed line — while
        each **qualifier** need only be *present*, in one of the PR's files or as
        a component of a path the diff touches. Matching the whole token clears
        the floor on exactly the PR the moved ADR is about; matching the last
        part alone would bind almost every diff.

        Before any of that, the token has to *be* a symbol. `classify` triages by
        shape and says so; §3 asks for a symbol, ADR-0088 §1(b) defines a code
        citation as a backticked name "identifying something in the repository",
        and the **member** is what must identify one — a package or module
        qualifier is the path test's question, asked and answered there. A token
        identifying nothing, by either reading :meth:`is_symbol` gives, has been
        *evaluated* and is not a symbol (#1799); a resolver that will not answer
        raises, and §6 binds.
        """
        if not self.is_symbol(token.rpartition(".")[2]):
            return False
        if word_in(token, self.changed_lines):
            return True
        if "." not in token:
            return False
        *qualifiers, member = token.split(".")
        if not word_in(member, self.changed_lines):
            return False
        return all(
            part in self.path_components or word_in(part, self.files_text) for part in qualifiers
        )


# --- §4's structural limb: the effective Protocol member surface -------------


@dataclass(frozen=True)
class _Bases:
    """What a module's own imports bind ``typing.Protocol`` to.

    Attributes:
        names: Bare names bound to ``typing.Protocol`` (``from typing import
            Protocol``, or ``... as P``).
        modules: Names bound to the ``typing`` module itself (``import typing``,
            ``import typing as t``).
    """

    names: frozenset[str]
    modules: frozenset[str]


def _typing_bindings(tree: ast.Module) -> _Bases:
    """Read a module's imports for the two spellings §4 recognises.

    ADR-0209 §4: a base resolves to ``typing.Protocol`` when the name it is
    written under is bound to it by that module's own imports — the bare name,
    an alias, or an attribute access on a name bound to the ``typing`` module.
    ``typing_extensions`` is read as ``typing`` wherever the clause names it.
    Identity is decided by that resolution and never by the base's spelling, and
    the reason is in the clause: a rewrite to ``from typing import Protocol as P``
    is a base move on which **both endpoints parse perfectly**, so a
    bare-identifier reading would clear the floor for an open lane whose required
    interface had just grown.
    """
    names: set[str] = set()
    modules: set[str] = set()
    for node in _module_level(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"typing", "typing_extensions"}:
            names.update(
                alias.asname or alias.name for alias in node.names if alias.name == "Protocol"
            )
        elif isinstance(node, ast.Import):
            modules.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in {"typing", "typing_extensions"}
            )
    return _Bases(frozenset(names), frozenset(modules))


def _base_name(node: ast.expr, bindings: _Bases, declared: set[str]) -> str | None:
    """Return what one base resolves to, or None where nothing binds it.

    Returns:
        ``""`` for ``typing.Protocol`` itself, the class name for a base the same
        file declares, and None for everything else — a wildcard import, a
        subscripted base, a ``Protocol`` re-exported through another module. §4's
        last sentence sends each of those to §6, deliberately: over-binding on a
        file that changes rarely and behind its own merged ADR is the cost this
        rule accepts, and under-binding is the failure it must not have.
    """
    if isinstance(node, ast.Name):
        if node.id in bindings.names:
            return ""
        if node.id in declared:
            return node.id
        return None
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "Protocol"
        and isinstance(node.value, ast.Name)
        and node.value.id in bindings.modules
    ):
        return ""
    return None


def _declared_members(node: ast.ClassDef) -> set[str]:
    """The members a class declares: a method, a property, an attribute.

    A property is a decorated ``def`` and needs no separate case. An annotated
    attribute and a plain binding are both taken, because ADR-0209 §4's limb is
    about *every* new structural requirement on an implementation, and a member
    counted here can only ever make a widening more visible.
    """
    members: set[str] = set()
    # `if TYPE_CHECKING:` and `try:` blocks inside a class body are descended
    # into: a member declared under a guard is a member. Nothing deeper is —
    # a name bound inside a method is a local, not surface.
    pending: list[ast.stmt] = list(node.body)
    while pending:
        stmt = pending.pop()
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            members.add(stmt.name)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            members.add(stmt.target.id)
        elif isinstance(stmt, ast.Assign):
            members.update(t.id for t in stmt.targets if isinstance(t, ast.Name))
        elif isinstance(stmt, ast.If | ast.Try):
            pending.extend(stmt.body)
            pending.extend(stmt.orelse)
            if isinstance(stmt, ast.Try):
                pending.extend(stmt.finalbody)
                for handler in stmt.handlers:
                    pending.extend(handler.body)
    return members


def _module_level(tree: ast.Module) -> list[ast.stmt]:
    """The statements at a module's own scope, in source order.

    ``if``/``try`` blocks are descended into and **function and class bodies are
    not**, because Python's binding rules are lexical and this reader's whole job
    is to say what a name at module scope is bound to. A bare ``ast.walk`` reads
    every nested statement as though it bound at module scope, which is a
    fail-OPEN on the one question §4's structural limb asks: a module whose real
    ``Protocol`` comes from somewhere else, plus a ``from typing import Protocol``
    inside some helper function, would have every ``class X(Protocol)`` in it
    resolved to ``typing.Protocol`` and judged as a Protocol — so a move that
    widened nothing would clear a floor §4's last sentence and §6 require it to
    bind. Adversarial review of PR #1755, round 1, blocker 2.
    """
    out: list[ast.stmt] = []
    pending: list[ast.stmt] = list(reversed(tree.body))
    while pending:
        stmt = pending.pop()
        out.append(stmt)
        if isinstance(stmt, ast.If | ast.Try):
            nested = [*stmt.body, *stmt.orelse]
            if isinstance(stmt, ast.Try):
                nested += stmt.finalbody
                for handler in stmt.handlers:
                    nested += handler.body
            pending.extend(reversed(nested))
    return out


def _classes_in(tree: ast.Module) -> dict[str, ast.ClassDef]:
    """Every ``ClassDef`` in the file, keyed by name.

    Read at **module scope**, descending through ``if``/``try`` blocks: a Protocol
    declared inside an ``if TYPE_CHECKING:`` block is still surface an
    implementation must satisfy, while one declared inside a *function* is a local
    and is not. A base written under a name that only a nested class defines
    therefore resolves to nothing here, and §6 binds — the safe direction.

    Raises:
        UnevaluableError: Two classes share a name. A base written under that name
            cannot be resolved to one of them, so the endpoint is undecidable and
            §6 binds — over-binding on a spelling `core/protocols.py` does not use.
    """
    classes: dict[str, ast.ClassDef] = {}
    for node in _module_level(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name in classes:
            raise UnevaluableError(f"two classes are named `{node.name}` in one endpoint")
        classes[node.name] = node
    return classes


def protocol_surfaces(source: str) -> dict[str, frozenset[str]]:
    """Return each ``Protocol``'s **effective** member surface in ``source``.

    Effective, not declared, because this repository composes Protocols:
    ``InvocationLedger(InvocationCompleter, Protocol)``,
    ``TraceStore(TraceSink, TraceRetention, Protocol)`` and
    ``SecretStore(Secrets, Protocol)`` each acquire their bases' members without
    declaring one. A base move adding a ``Protocol`` base to an existing
    ``Protocol`` therefore adds every member of that base to what an
    implementation must satisfy while declaring nothing in the child's body — a
    widening a declared-members comparison would clear.

    Args:
        source: One endpoint's whole content. The empty string is a file that
            does not exist at that endpoint, and has no Protocols.

    Returns:
        One entry per ``Protocol`` class, valued by its effective members.

    Raises:
        UnevaluableError: The endpoint will not parse, or a base resolves to nothing
            this module can follow (ADR-0209 §4, §6).
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise UnevaluableError(f"the endpoint will not parse ({exc.__class__.__name__})") from exc
    classes = _classes_in(tree)
    bindings = _typing_bindings(tree)
    declared = set(classes)

    resolved: dict[str, tuple[bool, frozenset[str]]] = {}

    def resolve(name: str, seen: frozenset[str]) -> tuple[bool, frozenset[str]]:
        """Whether ``name`` is a Protocol, and its effective member surface."""
        if name in resolved:
            return resolved[name]
        if name in seen:
            raise UnevaluableError(f"class `{name}` inherits from itself")
        node = classes[name]
        members = set(_declared_members(node))
        is_protocol = False
        for base in node.bases:
            target = _base_name(base, bindings, declared)
            if target is None:
                raise UnevaluableError(
                    f"a base of class `{name}` resolves neither to typing.Protocol "
                    "nor to a class this file declares"
                )
            if target == "":
                is_protocol = True
                continue
            base_is_protocol, base_members = resolve(target, seen | {name})
            members |= base_members
            is_protocol = is_protocol or base_is_protocol
        answer = (is_protocol, frozenset(members))
        resolved[name] = answer
        return answer

    surfaces: dict[str, frozenset[str]] = {}
    for name in classes:
        is_protocol, members = resolve(name, frozenset())
        if is_protocol:
            surfaces[name] = members
    return surfaces


def protocol_widening(old: str, new: str) -> str | None:
    """Return why §4's first limb binds this move, or None where it does not.

    Args:
        old: The whole content of the old endpoint (empty where none exists).
        new: The whole content of the new endpoint (empty where none exists).

    Returns:
        The reason a ``Protocol`` was added or widened, or None. A member's
        *removal* and a change to an existing one are not reached: the second
        limb and §3's tests judge those on their merits.
    """
    before = protocol_surfaces(old)
    after = protocol_surfaces(new)
    for name, members in after.items():
        if name not in before:
            return f"the move adds Protocol `{name}`"
        gained = sorted(members - before[name])
        if gained:
            return f"the move widens Protocol `{name}` — new member(s) {', '.join(gained)}"
    return None


def moved_definitions(old: str, new: str) -> set[str]:
    """Names whose *definition* the move changed, in one contract file.

    ADR-0209 §4's second limb reads a definition, not a mention: a mention that
    is not a definition tells a PR nothing it could act on. The hunks are
    computed here with :mod:`difflib` rather than by shelling out to ``git
    diff``, so what counts as "moved" does not depend on a rendering option this
    module would then have to pin against repository config; zero context lines,
    because a context line is precisely one the move did **not** touch.

    Args:
        old: The whole content of the old endpoint (empty where none exists).
        new: The whole content of the new endpoint (empty where none exists).

    Returns:
        Every name defined on a line the move added or removed.
    """
    names: set[str] = set()
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), n=0, lineterm="")
    for line in diff:
        if line[:1] not in {"+", "-"} or line.startswith(("+++", "---")):
            continue
        match = _DEFINITION_RE.match(line[1:])
        if match is None:
            continue
        names.add(match.group("def") or match.group("cls") or match.group("bound"))
    return names


# --- The tests, per floor endpoint --------------------------------------------


def _is_absolute_floor(path: str) -> bool:
    return path.startswith(_ABSOLUTE_PREFIXES) or path in _ABSOLUTE_PATHS


def _is_conditional_floor(path: str) -> bool:
    return path.startswith(_ADR_PREFIX) or path in {_PROTOCOLS, _TYPES}


def _adr_binding(repo: Path, pr: Pr, path: str, commit: str) -> str | None:
    """§3: why this moved ADR binds, or None where both of its tests clear."""
    match = _ADR_FILE_RE.match(path[len(_ADR_PREFIX) :].rpartition("/")[2])
    if match is None:
        raise UnevaluableError(
            f"`{path}` carries no ADR number, so §3's first test cannot be asked"
        )
    number = int(match.group(1))
    if number in pr.adrs:
        return f"§3 — the PR's text cites ADR-{number:04d}, the decision this move landed"
    text = _blob(repo, commit, path)
    for kind, token in classified_tokens(text):
        if kind == PATH and pr.names_path(token):
            return f"§3 — the moved ADR names `{token}`, a path this PR's diff touches"
        if kind == FILE and pr.names_file(token):
            return f"§3 — the moved ADR names `{token}`, a file this PR's diff touches"
        if kind == SYMBOL and pr.names_symbol(token):
            return f"§3 — the moved ADR names `{token}`, a symbol this PR's diff carries"
    return None


def _contract_binding(repo: Path, pr: Pr, entry: Entry, old: str, new: str) -> str | None:
    """§4: why this moved contract file binds, or None where every test clears.

    Both endpoints of the *entry* are read, under the names they have, so a
    rename into or out of ``core/`` is judged on the content it carried rather
    than on the name it landed under.
    """
    endpoints = entry.endpoints(old, new)
    if endpoints is None:  # pragma: no cover - the caller has already checked
        raise UnevaluableError(f"unknown base-move status '{entry.status}'")
    old_text = ""
    new_text = ""
    for path, commit in endpoints:
        if commit == old:
            old_text = _blob(repo, commit, path)
        else:
            new_text = _blob(repo, commit, path)

    if any(path == _PROTOCOLS for path, _ in endpoints):
        widened = protocol_widening(old_text, new_text)
        if widened is not None:
            return f"§4 — {widened}; new contract surface binds unconditionally"

    if pr.touches_under(_CORE_PREFIX):
        return f"§4 — this PR's diff touches a path under `{_CORE_PREFIX}`"
    for name in sorted(moved_definitions(old_text, new_text)):
        if word_in(name, pr.text):
            return f"§4 — the move changed the definition of `{name}`, which the PR's text names"
    return None


_ABSOLUTE_REASON = (
    "§1 — a standing review contract (docs/review/**, CLAUDE.md, "
    "CONTRIBUTING.md, scripts/codex-review.sh); no test is consulted"
)


def _judge_conditional(repo: Path, pr: Pr, entry: Entry, old: str, new: str) -> tuple[str, str]:
    """Judge one entry whose floor endpoints are all §2's conditional set.

    §6 is a rule and not a list, so every failure below is caught: the case that
    defeats a test written against today's text is by construction the one nobody
    thought of, and the cost of one is a round bought, never a review reused.
    """
    try:
        endpoints = entry.endpoints(old, new)
        if endpoints is None:
            raise UnevaluableError(f"unknown base-move status '{entry.status}'")
        for path, commit in endpoints:
            if path.startswith(_ADR_PREFIX):
                reason = _adr_binding(repo, pr, path, commit)
                if reason is not None:
                    return BIND, reason
        if any(path in {_PROTOCOLS, _TYPES} for path in (entry.src, entry.dst) if path):
            reason = _contract_binding(repo, pr, entry, old, new)
            if reason is not None:
                return BIND, reason
    except UnevaluableError as exc:
        return BIND, f"§6 — this test could not be evaluated: {exc}"
    except Exception as exc:  # §6: an unforeseen failure binds, whatever it turns out to be
        return BIND, f"§6 — the test failed: {exc.__class__.__name__}: {exc}"
    return FREE, "every ADR-0209 §3/§4 test cleared this path"


def judge(repo: Path, pr: Pr, entries: list[Entry], old: str, new: str) -> list[tuple[str, str]]:
    """Judge every entry of a base move. Returns ``(verdict, reason)`` per entry.

    Args:
        repo: The checkout to read both endpoints from.
        pr: The PR's three §5 inputs.
        entries: The base move's file set, in the order the caller read it.
        old: The commit the base moved from.
        new: The commit it moved to.

    Returns:
        One pair per entry: :data:`NOT_FLOOR` where no endpoint is a floor path,
        else :data:`BIND` or :data:`FREE` with the test that decided it.
    """
    verdicts: list[tuple[str, str]] = []
    for entry in entries:
        paths = [path for path in (entry.src, entry.dst) if path]
        if not any(_is_absolute_floor(p) or _is_conditional_floor(p) for p in paths):
            verdicts.append((NOT_FLOOR, ""))
        elif any(_is_absolute_floor(p) for p in paths):
            verdicts.append((BIND, _ABSOLUTE_REASON))
        else:
            verdicts.append(_judge_conditional(repo, pr, entry, old, new))
    return verdicts


# --- The shell boundary -------------------------------------------------------


def _read_entries(raw: bytes) -> list[Entry]:
    """Parse the base move's file set, as the caller wrote it to stdin.

    Three fields per entry, always — the caller has already parsed git's own
    listing into that shape, so the two sides join on *position* and this parser
    is not a second reading of the format ``ship`` read.
    """
    fields = raw.decode("utf-8", errors="surrogateescape").split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 3 != 0:
        message = "the base-move listing on stdin is not a whole number of 3-field entries"
        raise SystemExit(_fail(message))
    return [Entry(*fields[i : i + 3]) for i in range(0, len(fields), 3)]


def _read_git_listing(raw: bytes) -> list[Entry]:
    """Parse the PR's own ``git diff --name-status -M -z`` output.

    Two fields for an entry with one path and three for a rename or a copy, which
    is git's format rather than the caller's. It is read here because it is the
    one listing ``ship`` never parses: the base move's file set arrives already
    parsed on stdin, and re-reading *that* here would be the second statement of
    one rule that issue #751 is about.

    Raises:
        UnevaluableError: A record runs off the end. An unparsed listing is not a
            safe one, so §6 binds rather than guessing at the boundary.
    """
    fields = raw.decode("utf-8", errors="surrogateescape").split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    entries: list[Entry] = []
    i = 0
    while i < len(fields):
        status = fields[i]
        renamed = status[:1] in {"R", "C"}
        width = 3 if renamed else 2
        if i + width > len(fields):
            raise UnevaluableError("the PR's own file set is not a listing this can parse")
        entries.append(Entry(status, fields[i + 1], fields[i + 2] if renamed else ""))
        i += width
    return entries


def _all_floor_bind(entries: list[Entry], reason: str) -> list[tuple[str, str]]:
    """§6's answer where no test could be asked at all: every floor path binds."""
    return [
        (BIND, reason)
        if any(
            _is_absolute_floor(path) or _is_conditional_floor(path)
            for path in (entry.src, entry.dst)
            if path
        )
        else (NOT_FLOOR, "")
        for entry in entries
    ]


def _fail(message: str) -> int:
    print(f"floor_test: {message}", file=sys.stderr)
    return 2


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ADR-0209 §§1-6 — does the floor bind?")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--old-base", required=True, help="the commit the base moved from")
    parser.add_argument("--new-base", required=True, help="the commit it moved to")
    parser.add_argument("--pr-base", required=True, help="the PR's merge base (§5's left edge)")
    parser.add_argument("--pr-head", required=True, help="the PR's content commit")
    parser.add_argument("--pr-diff", type=Path, required=True, help="the rendered PR patch")
    parser.add_argument("--pr-listing", type=Path, required=True, help="its -z name-status set")
    parser.add_argument(
        "--description",
        type=Path,
        action="append",
        default=[],
        metavar="FILE",
        help="a PR description admitted to §5's text; repeatable",
    )
    parser.add_argument(
        "--unevaluable",
        metavar="REASON",
        help="an input §5 names could not be read — §6 binds every floor path, for REASON",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Judge one base move and write one record per entry to stdout."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    entries = _read_entries(sys.stdin.buffer.read())

    def emit(verdicts: list[tuple[str, str]]) -> int:
        out = sys.stdout.buffer
        for verdict, reason in verdicts:
            floor = "0" if verdict == NOT_FLOOR else "1"
            for value in (floor, verdict, _clean(reason)):
                out.write(value.encode("utf-8", errors="surrogateescape") + b"\0")
        out.flush()
        return 0

    if args.unevaluable:
        # §6, and the whole of it: the caller could not assemble an input §5 names
        # — the PR's own diff, its file set, or the description — so every test
        # over it is undecidable. Every floor path binds; every other path is
        # untouched, because §6 is about the tests and not about the listing.
        return emit(
            _all_floor_bind(entries, f"§6 — {args.unevaluable}, so §5's inputs are incomplete")
        )

    try:
        pr = Pr(
            repo=args.repo,
            base=args.pr_base,
            head=args.pr_head,
            diff_text=args.pr_diff.read_text(encoding="utf-8", errors="replace"),
            listing=_read_git_listing(args.pr_listing.read_bytes()),
            descriptions=[
                path.read_text(encoding="utf-8", errors="replace") for path in args.description
            ],
        )
    except (OSError, UnevaluableError) as exc:
        # §6 again, and the same shape: an input §5 names could not be assembled,
        # so every floor path binds and every other path is left alone. Reported
        # as a per-entry answer rather than as a non-zero exit, so the caller can
        # still say WHICH paths cost the round.
        return emit(_all_floor_bind(entries, f"§6 — {exc}"))

    return emit(judge(args.repo, pr, entries, args.old_base, args.new_base))


if __name__ == "__main__":
    sys.exit(main())
