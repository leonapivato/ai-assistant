#!/usr/bin/env python3
"""Check that every ADR, section, symbol and path a dispatch brief names exists.

A brief arrives carrying the dispatcher's authority and is read before any
skepticism exists, so a lane that reads a wrong citation as an instruction edits
the wrong thing and reports success. `.claude/skills/dispatch-agents/SKILL.md`
§2 answers that with prose — treat the brief's factual claims as hypotheses —
and this script answers the mechanical half of it in the seconds before
dispatch: *does the thing the brief names exist in the tree at all*.

It says nothing about whether the brief is **right**. A section reference can
resolve and still decide something else; a symbol can exist in a subsystem the
lane will never touch. The report is a list of names that do not resolve, and
its silence is not an endorsement.

What it extracts, from the brief with fenced code blocks removed:

- every ``ADR-NNNN`` → a ``docs/adr/NNNN-*.md`` must exist;
- every section reference (``§9``, ``§8a``, a ``§§3-5`` range, ``section 9``) written
  directly against an ``ADR-NNNN`` → that ADR must carry the section. ADRs
  number their Decision sections in
  three shapes, all of which count: a numbered heading (``### 9.``, ``#### 8a.``
  for a lettered sub-section), a bold decision paragraph (``**5.** ...``, the
  older corpus's form), and a numbered list item inside ``## Decision``. The
  report prints the line it matched, so a weak match is visible as one;
- every backticked token that is a Python identifier, or a dotted run of them,
  and carries a dot, an underscore or a capital → a word-boundary
  search over ``src/`` and ``tests/``, reporting the file that holds it and
  saying so when that file only *mentions* it rather than defining it. A dotted
  path resolves leniently: only the last component is searched, so
  ``memory.store.SqliteStore`` is found wherever ``SqliteStore`` is;
- every backticked path under a top-level directory of this repository → it must
  exist. A trailing glob is cut back to the directory before it.

Anything it cannot judge — a section reference with no ADR named before it, a
bare filename with no directory — is reported separately and never counted as
absent, because a checker that cries wolf is one a dispatcher learns to skip.

Run it bare: no dependencies, no network, and no git — it reads the checkout as
it stands, so fetch and check out the tree the lane will branch from first.

    python3 scripts/brief_check.py path/to/brief.md
    ... | python3 scripts/brief_check.py --quiet

Pass ``--root`` to check against a different checkout (used by the tests). Exit
status is 1 when anything is absent, 0 otherwise.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_FENCE_OPEN_RE = re.compile(r"`{3,}|~{3,}")

_ADR_RE = re.compile(r"\bADR-(\d{3,4})\b")

# ``§9``, ``§§3-5``, ``section 9``, ``§8a``; the separator may be a hyphen, an en
# dash or an em dash. A range is expanded only between plain numbers, so a
# lettered range binds its first section and leaves the rest, which
# is the conservative direction for a checker that must not invent citations.
# The digit run is unbounded: a capped one truncates a longer label silently
# and then reports a section nobody cited as absent.
_SECTION_RE = re.compile(
    r"(?:§§?\s*|\bsections?\s+)(?P<first>\d+[a-z]?)"
    r"(?:\s*(?:[-\u2013\u2014]|to)\s*(?P<last>\d+[a-z]?))?",
    re.IGNORECASE,
)
_LARGEST_RANGE = 20
# CPython refuses to convert an integer literal beyond a few thousand digits, so
# a label is length-bounded before any `int()` reaches it. Nothing in the corpus
# is close; what the bound buys is that a brief cannot hand this script a
# traceback in place of a report.
_LARGEST_LABEL = 9

_BACKTICK_RE = re.compile(r"`([^`\n]+)`")

# A backticked token is a path only when it names one of these trees. Requiring
# the prefix is what keeps ``origin/main`` and ``feat(scope)`` out of the report:
# a token that merely contains a slash is not evidence of a path, and a checker
# that guesses here spends its credibility on false absences.
_PATH_PREFIXES = (
    "src/",
    "tests/",
    "docs/",
    "scripts/",
    "benchmarks/",
    ".claude/",
    ".github/",
)
_FILE_SUFFIXES = frozenset(
    {"py", "md", "toml", "yml", "yaml", "sh", "json", "txt", "cfg", "ini", "lock", "sql"}
)

ABSENT = "absent"
PRESENT = "present"
UNCHECKED = "not checked"


@dataclass(frozen=True)
class Finding:
    """One name the brief made, and what the tree says about it.

    Attributes:
        kind: ``ADR``, ``section``, ``symbol``, ``path`` or ``file``.
        cited: The name as the brief wrote it, which is what a dispatcher
            searches the brief for when fixing it.
        status: :data:`ABSENT`, :data:`PRESENT` or :data:`UNCHECKED`.
        detail: Where it was found, or why it was not.
    """

    kind: str
    cited: str
    status: str
    detail: str


def strip_code_blocks(text: str) -> str:
    """Return ``text`` with fenced code blocks removed.

    A brief's code blocks are full of paths, flags and placeholder names that
    are illustrations rather than claims about the tree, and checking them
    produces noise that buries the real findings.

    The scan is line-based rather than a regex over the whole document, so it
    can follow the two rules that decide where a block ends: a closing fence is
    the **same** delimiter character, at least as long as the opener, and alone
    on its line; and a fence that is never closed runs to the end of the file.
    A regex that ends a block early reads a code sample as brief content, and
    one that ends it late reads brief content as a code sample.
    """
    kept: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if fence is None:
            opener = _FENCE_OPEN_RE.match(stripped)
            if opener is not None:
                fence = opener.group(0)
            else:
                kept.append(line)
        elif len(stripped) >= len(fence) and set(stripped) == {fence[0]}:
            fence = None
    return "".join(kept)


def _line_at(text: str, pos: int) -> tuple[int, str]:
    """Return the 1-based line number containing ``pos`` and that line, stripped."""
    line_no = text.count("\n", 0, pos) + 1
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return line_no, text[start : end if end != -1 else len(text)].strip()


def adr_file(root: Path, number: str) -> Path | None:
    """Return the ADR file for ``number`` under ``root``, or None if there is none."""
    matches = sorted((root / "docs" / "adr").glob(f"{int(number):04d}-*.md"))
    return matches[0] if matches else None


def _decision_part(text: str) -> tuple[int, str] | None:
    """Return the offset and body of the ``## Decision`` section, if there is one."""
    heading = re.search(r"^##[ \t]+Decision\b.*$", text, re.MULTILINE)
    if heading is None:
        return None
    rest = text[heading.end() :]
    nxt = re.search(r"^##[ \t]", rest, re.MULTILINE)
    return heading.end(), rest[: nxt.start()] if nxt else rest


def find_section(text: str, section: str) -> tuple[int, str] | None:
    """Return the line number and text of the heading introducing ``section``.

    Args:
        text: The ADR's full text.
        section: A section label such as ``9`` or ``8a``.

    Returns:
        The 1-based line number and the matched line, or None if no shape
        matches. The three shapes are the ones the corpus uses; see the module
        docstring.
    """
    label = re.escape(section)
    for pattern in (rf"^#{{2,6}}[ \t]+{label}\.[ \t]", rf"^\*\*{label}\.[ \t*]"):
        match = re.search(pattern, text, re.MULTILINE)
        if match is not None:
            return _line_at(text, match.start())
    decision = _decision_part(text)
    if decision is not None:
        offset, body = decision
        match = re.search(rf"^ {{0,3}}{label}\.[ \t]", body, re.MULTILINE)
        if match is not None:
            return _line_at(text, offset + match.start())
    return None


def _expand(first: str, last: str | None) -> list[str]:
    """Expand a section range to its members, or return just ``first``."""
    if last is None or not first.isdigit() or not last.isdigit():
        return [first]
    if len(first) > _LARGEST_LABEL or len(last) > _LARGEST_LABEL:
        return [first]
    low, high = int(first), int(last)
    if not 0 < high - low <= _LARGEST_RANGE:
        return [first]
    return [str(n) for n in range(low, high + 1)]


def _binding_adr(text: str, match: re.Match[str], adrs: list[tuple[int, int, str]]) -> str | None:
    """Return the ADR number a section reference belongs to, if one can be read.

    Binding is **adjacency only**: the reference must sit directly against an
    ``ADR-NNNN`` — ``ADR-0124 §9``, ``ADR-0124, §9``, ``ADR-0124's §9`` — or be
    written as ``§9 of ADR-0124``. Carrying the last ADR named anywhere earlier
    forward was tried and rejected: on this repository's own documents it bound
    a quoted ``§9`` to the ADR named later in the sentence, and bound ``#1226
    §6`` to an ADR entirely. Both are reported as absent by a checker that
    guesses, and a false absence is the failure that gets a checker skipped. A
    reference nothing binds is reported as unchecked instead.
    """
    before = [(end, number) for _, end, number in adrs if end <= match.start()]
    if before:
        end, number = before[-1]
        if re.fullmatch(r"(?:['\u2019]s)?[ \t,;]{0,4}", text[end : match.start()]):
            return number
    linking = re.match(r"[ \t]*of[ \t]+", text[match.end() : match.end() + 8])
    if linking is not None:
        ahead = _ADR_RE.match(text, match.end() + linking.end())
        if ahead is not None:
            return ahead.group(1)
    return None


def section_citations(text: str) -> list[tuple[str | None, str]]:
    """Return ``(adr number or None, section label)`` for every section reference."""
    adrs = [(m.start(), m.end(), m.group(1)) for m in _ADR_RE.finditer(text)]
    citations: list[tuple[str | None, str]] = []
    for match in _SECTION_RE.finditer(text):
        number = _binding_adr(text, match, adrs)
        citations.extend(
            (number, section) for section in _expand(match.group("first"), match.group("last"))
        )
    return citations


def classify(token: str) -> tuple[str, str] | None:
    """Return ``(kind, cleaned token)`` for a backticked token, or None to ignore it.

    Args:
        token: The text between one pair of backticks.

    Returns:
        ``("path", ...)`` for a token naming one of this repository's trees,
        ``("file", ...)`` for a bare filename, ``("symbol", ...)`` for something
        shaped like a Python name, and None for prose, commands and flags.
    """
    cleaned = token.strip().removesuffix("()")
    if not cleaned or any(c.isspace() for c in cleaned):
        return None
    if cleaned.startswith(_PATH_PREFIXES):
        return "path", cleaned
    # Python's own rule for what a name may be, rather than an ASCII imitation of
    # it, so a Unicode identifier is checked instead of silently skipped.
    if not all(part.isidentifier() for part in cleaned.split(".")):
        return None
    last = cleaned.rsplit(".", maxsplit=1)[-1]
    if last.lower() in _FILE_SUFFIXES:
        return "file", cleaned
    # A bare lowercase word (``main``, ``pytest``, ``ship``) is prose far more
    # often than it is a symbol; a dot, an underscore or a capital is what makes
    # a token worth searching for.
    if "." in cleaned or "_" in cleaned or any(c.isupper() for c in cleaned):
        return "symbol", cleaned
    return None


def grep_symbols(root: Path, names: set[str]) -> dict[str, tuple[str, bool]]:
    """Find each name under ``src/`` and ``tests/``, preferring a definition.

    A word-boundary hit is what the check promises, but *where* it hit is the
    part a dispatcher acts on: a name found only in a comment or a docstring is
    a different answer from one found as a ``class``, and reporting them alike
    is how a lane is sent after a symbol that is merely discussed.

    Args:
        root: The checkout to search.
        names: Bare identifiers (a dotted citation contributes its last
            component only).

    Returns:
        One entry per name found, valued by the repository-relative file and
        whether that file defines it rather than merely mentioning it.
    """
    if not names:
        return {}
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    # A definition is a `def`/`class` statement or a module- or class-level
    # binding, which is what a constant such as `PROTOCOL_VERSION` looks like.
    # The binding form excludes a line ending in a comma, which is how a keyword
    # argument and an annotated parameter are written and neither is a definition.
    define = re.compile(
        rf"^[ \t]*(?:(?:async[ \t]+)?def|class)[ \t]+({alt})\b"
        rf"|^[ \t]*({alt})[ \t]*(?::[^=\n]+)?=(?![^\n]*,[ \t]*$)",
        re.MULTILINE,
    )
    mention = re.compile(rf"\b({alt})\b")
    defined: dict[str, str] = {}
    mentioned: dict[str, str] = {}
    for tree in ("src", "tests"):
        for path in sorted((root / tree).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            relative = path.relative_to(root).as_posix()
            for match in define.finditer(text):
                defined.setdefault(match.group(1) or match.group(2), relative)
            for match in mention.finditer(text):
                mentioned.setdefault(match.group(1), relative)
            if len(defined) == len(names):
                break
    return {
        name: (defined[name], True) if name in defined else (where, False)
        for name, where in mentioned.items()
    }


def _check_path(root: Path, token: str) -> Finding:
    """Check one backticked path.

    A glob is cut back to the directory that contains it, so ``tests/wire/**``
    and ``docs/adr/NNNN-*.md`` are checked as the directories they name rather
    than as filenames nothing can match. A token carrying an angle-bracket
    placeholder (``tests/<pkg>/test_*.py``) names a shape, not a file, and is
    reported as unchecked.
    """
    if "<" in token or ">" in token:
        return Finding("path", token, UNCHECKED, "a placeholder, not a path")
    cleaned = token.rstrip("/")
    if "*" in cleaned:
        cleaned = cleaned[: cleaned.index("*")].rpartition("/")[0]
    if not cleaned:
        return Finding("path", token, UNCHECKED, "no directory before the glob")
    target = root / cleaned
    # A repository-relative prefix is not proof the path stays inside the
    # checkout: `src/../..` starts with `src/` and resolves above the root, where
    # `exists()` answers about a directory this check makes no claim over.
    if not target.resolve().is_relative_to(root.resolve()):
        return Finding("path", token, UNCHECKED, "resolves outside the checkout")
    exists = target.exists()
    detail = f"{cleaned} exists" if exists else f"{cleaned} does not exist"
    return Finding("path", token, PRESENT if exists else ABSENT, detail)


def _check_file(root: Path, token: str) -> Finding:
    """Check a bare filename, which is only judged when it sits at the root."""
    if (root / token).exists():
        return Finding("file", token, PRESENT, f"{token} exists")
    return Finding("file", token, UNCHECKED, "a bare filename — write its path to have it checked")


def _adr_findings(root: Path, text: str) -> tuple[list[Finding], dict[str, Path]]:
    """Check every ``ADR-NNNN`` mention, returning the findings and the files found."""
    findings: list[Finding] = []
    files: dict[str, Path] = {}
    for number in dict.fromkeys(m.group(1) for m in _ADR_RE.finditer(text)):
        path = adr_file(root, number)
        cited = f"ADR-{int(number):04d}"
        if path is None:
            findings.append(Finding("ADR", cited, ABSENT, f"no docs/adr/{int(number):04d}-*.md"))
        else:
            files[number] = path
            findings.append(Finding("ADR", cited, PRESENT, path.relative_to(root).as_posix()))
    return findings, files


def _section_findings(text: str, files: dict[str, Path]) -> list[Finding]:
    """Check every section reference against the ADR it binds to."""
    findings: list[Finding] = []
    bodies: dict[str, str] = {}
    for number, section in section_citations(text):
        if number is None:
            findings.append(Finding("section", f"§{section}", UNCHECKED, "no ADR named before it"))
            continue
        cited = f"ADR-{int(number):04d} §{section}"
        if number not in files:
            findings.append(Finding("section", cited, UNCHECKED, "the ADR itself is absent"))
            continue
        body = bodies.setdefault(number, files[number].read_text(encoding="utf-8"))
        hit = find_section(body, section)
        if hit is None:
            findings.append(Finding("section", cited, ABSENT, "no section with that number"))
        else:
            findings.append(Finding("section", cited, PRESENT, f"line {hit[0]}: {hit[1]}"))
    return findings


def _symbol_finding(token: str, where: tuple[str, bool] | None) -> Finding:
    """Turn one symbol search result into a finding."""
    if where is None:
        return Finding("symbol", token, ABSENT, "no word-boundary hit in src/ or tests/")
    path, defined = where
    return Finding(
        "symbol", token, PRESENT, path if defined else f"{path} (mentioned, not defined)"
    )


def _token_findings(root: Path, text: str) -> list[Finding]:
    """Check every backticked path, filename and symbol."""
    classified = [
        result
        for result in (classify(t) for t in dict.fromkeys(_BACKTICK_RE.findall(text)))
        if result is not None
    ]
    symbols = [token for kind, token in classified if kind == "symbol"]
    found = grep_symbols(root, {s.rsplit(".", maxsplit=1)[-1] for s in symbols})
    findings: list[Finding] = []
    for kind, token in classified:
        if kind == "path":
            findings.append(_check_path(root, token))
        elif kind == "file":
            findings.append(_check_file(root, token))
        else:
            findings.append(_symbol_finding(token, found.get(token.rsplit(".", maxsplit=1)[-1])))
    return findings


def check(brief: str, root: Path) -> list[Finding]:
    """Return one finding per distinct name the brief makes.

    Args:
        brief: The brief's text.
        root: The checkout to check it against.

    Returns:
        Findings in the order the names first appear, de-duplicated.
    """
    text = strip_code_blocks(brief)
    adrs, files = _adr_findings(root, text)
    findings = adrs + _section_findings(text, files) + _token_findings(root, text)
    seen: dict[tuple[str, str], Finding] = {}
    for finding in findings:
        seen.setdefault((finding.kind, finding.cited), finding)
    return list(seen.values())


def render(findings: list[Finding], *, source: str, root: Path, quiet: bool = False) -> str:
    """Build the report, absent first.

    Args:
        findings: What :func:`check` returned.
        source: How the brief was named on the command line.
        root: The checkout that was checked.
        quiet: Print only the absences, and nothing at all when there are none.

    Returns:
        The report text.
    """
    absent = [f for f in findings if f.status == ABSENT]
    if quiet:
        return "\n".join(f"  {f.cited}  —  {f.detail}" for f in absent)
    width = min(max((len(f.cited) for f in findings), default=0), 44)
    lines = [f"brief-check — {source} against {root}"]
    for status in (ABSENT, PRESENT, UNCHECKED):
        group = [f for f in findings if f.status == status]
        if not group:
            continue
        lines += ["", f"{status} ({len(group)})"]
        lines += [f"  {f.cited.ljust(width)}  {f.detail}" for f in group]
    lines += ["", f"{len(absent)} absent of {len(findings)} name(s) checked."]
    if absent:
        lines.append("Fix the brief, or say in it why the name is one the lane will create.")
    return "\n".join(lines)


def main() -> None:
    """Read a brief, check it against ``--root``, and exit 1 if anything is absent."""
    parser = argparse.ArgumentParser(
        description="Check that every ADR, section, symbol and path a brief names exists."
    )
    parser.add_argument("brief", nargs="?", default="-", help="Brief file, or '-' for stdin.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to check against (defaults to this checkout).",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Print only what is absent, and nothing if none is."
    )
    args = parser.parse_args()
    text = sys.stdin.read() if args.brief == "-" else Path(args.brief).read_text(encoding="utf-8")
    findings = check(text, args.root)
    report = render(
        findings,
        source="stdin" if args.brief == "-" else args.brief,
        root=args.root,
        quiet=args.quiet,
    )
    if report:
        print(report)
    sys.exit(1 if any(f.status == ABSENT for f in findings) else 0)


if __name__ == "__main__":
    main()
