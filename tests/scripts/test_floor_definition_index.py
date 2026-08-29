"""ADR-0209 §3's word "symbol", checked against this repository's own source.

`scripts/floor_test.py` binds a moved ADR that names "a symbol occurring in an
added or removed line of the PR's diff". A token is a symbol when it names a
definition this repository carries — ADR-0088 §1(b)'s "a backticked name
identifying something in the repository" — and `floor_test.defined_names_at` is
what answers that.

**This module is a differential test, and the duplication in it is the point.**
Everywhere else, a second statement of one rule is the defect #751 records; here
the implementation's reader is deliberately compared against an independently
written one, over every `*.py`, `*.js` and `*.sh` file this repository tracks, as
they actually are, because the failure this guards is *silent and one-directional*.
A name the resolver cannot see is a symbol judged not to be one, so the floor
clears and a round that was owed is not charged — and nothing anywhere says so.
Two such names were found by exactly this comparison during PR #1803's own review:
`async function* streamValues` in the gateway's `app.js`, and every shell function
whose name contains the letter `t`, because POSIX ERE has no `\\t` escape and glibc
reads it as a literal `t` inside a bracket expression.

The other direction is pinned too, and it is issue #1799: the ADR header
vocabulary the corpus backticks in every file must resolve to nothing, or the
narrowing ADR-0209 exists for is inert for every ADR lane.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
from floor_test import defined_names_at  # noqa: E402  # after the path insert

#: One independently written reader per language, deliberately *not* sharing a
#: line with `floor_test`'s. Each is the plainest statement of "this line defines
#: a name" for its language, and a name any of them finds must be in the index.
_READERS = {
    ".py": (
        re.compile(r"^[ \t]*(?:async[ \t]+)?(?:def|class)[ \t]+([A-Za-z_]\w*)", re.M),
        re.compile(r"^[ \t]*([A-Za-z_]\w*)[ \t]*(?::[^=\n]+)?=(?!=)", re.M),
    ),
    ".js": (
        re.compile(
            r"^[ \t]*(?:export[ \t]+(?:default[ \t]+)?)?(?:async[ \t]+)?"
            r"(?:function[ \t]*\*?[ \t]*|class[ \t]+|const[ \t]+|let[ \t]+|var[ \t]+)"
            r"([A-Za-z_$][\w$]*)",
            re.M,
        ),
    ),
    ".sh": (
        re.compile(r"^[ \t]*(?:function[ \t]+)?([A-Za-z_]\w*)[ \t]*\(\)", re.M),
        re.compile(
            r"^[ \t]*(?:local|readonly|export|typeset|declare(?:[ \t]+-\w+)*)"
            r"[ \t]+([A-Za-z_]\w*)=",
            re.M,
        ),
        re.compile(r"^[ \t]*([A-Za-z_]\w*)=(?!=)", re.M),
    ),
}


def _git(*args: str) -> bytes:
    """Run one git command in this repository and return its stdout."""
    return subprocess.run(  # noqa: S603  # fixed argv, this repository
        ["git", *args],  # noqa: S607
        cwd=_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _source_at_head() -> list[tuple[str, str]]:
    """Every file `floor_test` searches, **as `HEAD` holds it**.

    `HEAD` and not the working tree, because `defined_names_at` is asked for
    `HEAD` and a comparison between two different trees is not a comparison of
    two readers: it would fail on any uncommitted edit and say nothing about the
    rule. One `cat-file --batch`, because 667 `git show` calls to answer one
    question is the shape a lane waits on.
    """
    listing = _git("ls-tree", "-r", "-z", "--name-only", "HEAD").split(b"\0")
    paths = [name for name in listing if name.endswith((b".py", b".js", b".sh"))]
    raw = subprocess.run(  # fixed argv, this repository
        ["git", "cat-file", "--batch", "-z"],  # noqa: S607
        cwd=_ROOT,
        check=True,
        capture_output=True,
        input=b"".join(b"HEAD:" + name + b"\0" for name in paths),
    ).stdout

    out: list[tuple[str, str]] = []
    offset = 0
    for name in paths:
        # `<oid> <type> <size>\n<contents>\n`, one record per requested name.
        end = raw.index(b"\n", offset)
        size = int(raw[offset:end].split(b" ")[2])
        start = end + 1
        out.append((name.decode(), raw[start : start + size].decode("utf-8", "replace")))
        offset = start + size + 1
    return out


def test_every_definition_this_repository_writes_reaches_the_index() -> None:
    """The one-directional failure, asserted over the real corpus.

    A missing name never raises and never prints: it makes `names_symbol` answer
    False, which clears a floor path ADR-0209 §3 requires to bind. §5 states the
    asymmetry this repository runs on — "over-binding is the cost this ADR accepts
    and prices; under-binding is the failure it must not have" — so the index is
    allowed to hold names no reader below finds, and never the reverse.
    """
    index = defined_names_at(_ROOT, "HEAD")
    assert index, "the resolver found no definitions at all, which cannot be right"

    missing: dict[str, str] = {}
    for path, text in _source_at_head():
        for reader in _READERS[Path(path).suffix]:
            for name in reader.findall(text):
                if name not in index:
                    missing.setdefault(name, path)

    assert not missing, (
        "these definitions are invisible to ADR-0209 §3's symbol test, so a moved "
        f"ADR naming one would clear the floor: {sorted(missing.items())}"
    )


@pytest.mark.parametrize(
    "token",
    [
        # ADR-0070 §4's status vocabulary, which `docs/adr/template.md` puts at the
        # head of every ADR and every ADR PR therefore writes into its own diff.
        "Status",
        "Proposed",
        "Accepted",
        # The literals the corpus spells an absent or boolean value with.
        "None",
        "True",
        "False",
        # The package name (PR #1786). It identifies a tree, and whether the PR
        # changes that tree is the *path* test's question, asked and answered there.
        "ai_assistant",
    ],
)
def test_the_corpus_boilerplate_names_no_definition(token: str) -> None:
    """Issue #1799: the tokens that made ADR-0209's narrowing inert for ADR lanes.

    Each of these is backticked somewhere in nearly every ADR and written into
    nearly every ADR PR's diff, so a shape-only reading matched between any two
    ADR lanes. None of them names anything this repository defines, which is what
    makes each an *evaluated* not-a-symbol rather than an unevaluable test.
    """
    assert token not in defined_names_at(_ROOT, "HEAD")
