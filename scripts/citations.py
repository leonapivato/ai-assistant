#!/usr/bin/env python3
"""The citation extraction two tools share — one statement, read from both ends.

``scripts/brief_check.py`` reads a dispatch brief and asks *does the thing this
names exist*. ``scripts/floor_test.py`` reads an ADR and a pull request and asks
*do these two texts name each other* (ADR-0209 §§3-5). They are different
questions over the same corpus, written in the same form: ADR-0088 §1 requires a
code citation to name the symbol and §5 forbids a line number, so what both tools
read is a ``ADR-NNNN`` token, a backticked token, and a classification of that
token into a repository path, a bare filename or a Python symbol.

ADR-0209 §5 is explicit that the second tool's extraction is "``scripts/
brief_check.py``'s, **reused and not restated**". That is why this module exists
rather than a second regex: issue #751 records what a hand-copied replica of one
of this repository's acceptance rules cost, and the same discipline is owed here
before the second reader is written rather than after.

Nothing here reads the filesystem, runs git, or decides anything. It extracts and
classifies; both callers do their own matching, because the *question* differs
even where the extraction does not.

**Fenced code blocks are not stripped here**, and that is deliberate: the two
callers want opposite things from a fence. ``brief_check`` strips them, because
its expensive direction is a false absence reported against an illustration, and
it does that with its own :func:`brief_check.strip_code_blocks` before calling
in. ``floor_test`` reads the text whole, because its expensive direction is a
missed binding — a round not charged (ADR-0209 §5). A module that stripped for
both would silently pick one of those two, so it strips for neither.
"""

from __future__ import annotations

import re

# ``ADR-0209``, ``ADR-209``. The capture is the digits, unpadded, so a caller
# comparing against a filename's number normalises both through ``int``.
ADR_RE = re.compile(r"\bADR-(\d{3,4})\b")

# One pair of backticks, on one line. A citation spanning a line break is not a
# form ADR-0088 §1 defines, and matching across one would swallow prose.
BACKTICK_RE = re.compile(r"`([^`\n]+)`")

# A backticked token is a path only when it names one of these trees. Requiring
# the prefix is what keeps ``origin/main`` and ``feat(scope)`` out: a token that
# merely contains a slash is not evidence of a path.
PATH_PREFIXES = (
    "src/",
    "tests/",
    "docs/",
    "scripts/",
    "benchmarks/",
    ".claude/",
    ".github/",
)

FILE_SUFFIXES = frozenset(
    {"py", "md", "toml", "yml", "yaml", "sh", "json", "txt", "cfg", "ini", "lock", "sql"}
)

PATH = "path"
FILE = "file"
SYMBOL = "symbol"


def classify(token: str) -> tuple[str, str] | None:
    """Return ``(kind, cleaned token)`` for a backticked token, or None to ignore it.

    Args:
        token: The text between one pair of backticks.

    Returns:
        :data:`PATH` for a token naming one of this repository's trees,
        :data:`FILE` for a bare filename, :data:`SYMBOL` for something shaped
        like a Python name, and None for prose, commands and flags.
    """
    cleaned = token.strip().removesuffix("()")
    if not cleaned or any(c.isspace() for c in cleaned):
        return None
    if cleaned.startswith(PATH_PREFIXES):
        return PATH, cleaned
    # Python's own rule for what a name may be, rather than an ASCII imitation of
    # it, so a Unicode identifier is checked instead of silently skipped.
    if not all(part.isidentifier() for part in cleaned.split(".")):
        return None
    last = cleaned.rsplit(".", maxsplit=1)[-1]
    if last.lower() in FILE_SUFFIXES:
        return FILE, cleaned
    # A bare lowercase word (``main``, ``pytest``, ``ship``) is prose far more
    # often than it is a symbol; a dot, an underscore or a capital is what makes
    # a token worth searching for.
    if "." in cleaned or "_" in cleaned or any(c.isupper() for c in cleaned):
        return SYMBOL, cleaned
    return None


def adr_numbers(text: str) -> set[int]:
    """Return every ADR number ``text`` cites, unpadded.

    Args:
        text: Any prose.

    Returns:
        The numbers as integers, so ``ADR-209`` and ``ADR-0209`` are one number
        and a caller comparing against ``docs/adr/0209-*.md`` needs no padding
        rule of its own.
    """
    return {int(match.group(1)) for match in ADR_RE.finditer(text)}


def classified_tokens(text: str) -> list[tuple[str, str]]:
    """Return each distinct backticked token ``text`` carries, classified.

    Args:
        text: Any prose.

    Returns:
        ``(kind, token)`` pairs in first-appearance order, de-duplicated, with
        the tokens :func:`classify` declines to judge dropped.
    """
    results: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in BACKTICK_RE.findall(text):
        result = classify(raw)
        if result is None or result in seen:
            continue
        seen.add(result)
        results.append(result)
    return results


def word_in(name: str, text: str) -> bool:
    """Whether ``name`` occurs in ``text`` as a whole word.

    The boundary is the Python identifier alphabet rather than a regex word
    boundary, so ``ingest`` does not match inside ``reingest`` and a dotted
    token's dots are matched literally rather than as wildcards.

    Args:
        name: The word to look for.
        text: The text to look in.

    Returns:
        True where ``name`` appears bounded by something that is not an
        identifier character.
    """
    if not name:
        return False
    pattern = rf"(?<![0-9A-Za-z_]){re.escape(name)}(?![0-9A-Za-z_])"
    return re.search(pattern, text) is not None
