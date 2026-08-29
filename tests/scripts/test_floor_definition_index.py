"""ADR-0209 §3's word "symbol": what this repository actually defines.

`scripts/floor_test.py` binds a moved ADR that names "a symbol occurring in an
added or removed line of the PR's diff". A token is a symbol when it names a
definition this repository carries — ADR-0088 §1(b)'s "a backticked name
identifying something in the repository" — and `floor_test.defined_names` is what
answers that.

**The failure this module guards is silent and one-directional.** A name the
resolver cannot see is a symbol judged not to be one, so a floor path clears and a
round that was owed is not charged, and nothing anywhere says so. ADR-0209 §5
prices the other direction as acceptable and forbids this one, so every assertion
below runs that way: a definition must reach the index, and the index may hold
more.

Three names were missed in three successive rounds of PR #1803's own review, each
in a form the pattern of the day did not have — `export function`,
`async function* streamValues`, `type UtcInstant = ...` — and a fourth was every
shell function whose name contains the letter `t`, because POSIX ERE has no tab
escape and glibc read the backslash-t in a bracket expression as the letter
itself. That run is why Python is now read with `ast`: a pattern over Python is an
enumeration of a grammar, and the grammar kept winning.

So the three groups here answer three different questions, and the split is not
arbitrary:

- **Python, by form.** `_python_definitions` is checked against small sources, one
  per binding form the language has and one per binding it must *not* treat as a
  definition. A line-oriented reader cannot serve as the independent check here at
  all — a docstring that wraps "…a class for reading…" onto its own line reads as
  `class for` — which is itself the argument for `ast`.
- **JavaScript and shell, over the corpus.** These two are still read by a
  pattern, so the pattern is compared against an independently written reader over
  the real files: one JavaScript file and three shell scripts.
- **The corpus, both directions.** Real symbols this repository is built on must
  resolve, and issue #1799's ADR-header vocabulary must not.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
from floor_test import _python_definitions, _source_blobs, defined_names  # noqa: E402

# --- Python: one case per binding form ----------------------------------------

_BINDS = {
    "def": "def render(): ...",
    "async def": "async def render(): ...",
    "class": "class render: ...",
    "type alias": "type render = int",
    "generic type alias": "type render[T] = list[T]",
    "assignment": "render = 1",
    "annotated assignment": "render: int = 1",
    # A `Protocol` member and a dataclass field, which carry no value at all.
    "annotation only": "class C:\n    render: int",
    "augmented target": "render = 0\nrender += 1",
    "tuple unpacking": "render, other = 1, 2",
    "starred unpacking": "*render, other = [1, 2]",
    "for target": "for render in ():\n    pass",
    "with target": "with open('f') as render:\n    pass",
    "comprehension target": "[render for render in ()]",
    "walrus": "if (render := 1):\n    pass",
    "match capture": "match 1:\n    case [render]:\n        pass",
    "match star": "match []:\n    case [*render]:\n        pass",
    "match mapping rest": "match {}:\n    case {**render}:\n        pass",
    "except capture": "try:\n    pass\nexcept ValueError as render:\n    pass",
    "global declaration": "def f():\n    global render",
    "decorated def": "@staticmethod\ndef render(): ...",
    "nested def": "def outer():\n    def render(): ...",
    "under a TYPE_CHECKING guard": "if TYPE_CHECKING:\n    render = 1",
}

_DOES_NOT_BIND = {
    # PR #1786's shape: a moved ADR naming the package matched every diff that
    # mentioned it. An import binds a name without defining anything, and where the
    # name is a real symbol the file that defines it is in this same tree.
    "a plain import": "import render",
    "a dotted import": "import render.sub",
    "a from-import": "from pkg import render",
    "an aliased import": "from pkg import thing as render",
    # A parameter names nothing ADR-0088 §1's citation form could cite.
    "a parameter": "def f(render): ...",
    "a keyword argument": "f(\n    render=1,\n)",
    # A mention is not a definition — ADR-0209 §4's second limb says so in its own
    # words, and §3's test is the same shape.
    "an attribute access": "other.render()",
    "a call": "render()",
    "a string": "'render'",
}


@pytest.mark.parametrize("form", _BINDS)
def test_every_python_binding_form_reaches_the_index(form: str) -> None:
    """Each is a definition Python makes, so each must be a symbol §3 can bind on."""
    assert "render" in _python_definitions(_BINDS[form].encode()), form


@pytest.mark.parametrize("form", _DOES_NOT_BIND)
def test_a_name_python_only_uses_is_not_a_definition(form: str) -> None:
    """Binding a name locally is not defining the thing the citation names."""
    assert "render" not in _python_definitions(_DOES_NOT_BIND[form].encode()), form


def test_a_python_file_that_will_not_parse_falls_back_rather_than_failing() -> None:
    """One unparseable file is not an unevaluable test (ADR-0209 §6).

    §6 binds a *test* that cannot be evaluated. A single file of several hundred
    that will not parse is not that: the reader falls back to the line-oriented
    one, which is the generous direction, and the rest of the tree still answers.
    """
    assert "render" in _python_definitions(b"render = 1\ndef (:\n")


# --- JavaScript and shell: the pattern, against an independent reader ----------

#: One independently written reader per line-oriented language, deliberately not
#: sharing a line with `floor_test`'s. Each is the plainest statement of "this line
#: defines a name", and a name either finds must be in the index.
_READERS = {
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


def test_every_javascript_and_shell_definition_reaches_the_index() -> None:
    """The two languages still read by a pattern, over the files that carry them.

    `src/ai_assistant/interfaces/gateway/assets/app.js` and the three scripts are
    first-party source with real symbols in them, and they are where every miss
    this module records was found. Comparing readers over the *real* files is what
    made the tab-escape defect visible: it was invisible in every hand-written
    example, because none of them happened to hold a name containing a `t`.
    """
    index = defined_names(_ROOT, ["HEAD"])
    assert index, "the resolver found no definitions at all, which cannot be right"

    missing: dict[str, str] = {}
    checked = 0
    for path, blob in _source_blobs(_ROOT, ["HEAD"]):
        readers = _READERS.get(Path(path).suffix)
        if readers is None:
            continue
        checked += 1
        text = blob.decode("utf-8", errors="replace")
        for reader in readers:
            for name in reader.findall(text):
                if name not in index:
                    missing.setdefault(name, path)

    assert checked, "no JavaScript or shell file was read, so nothing was compared"
    assert not missing, (
        "these definitions are invisible to ADR-0209 §3's symbol test, so a moved "
        f"ADR naming one would clear the floor: {sorted(missing.items())}"
    )


# --- The corpus, both directions ----------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        # One per language and per form, named rather than derived: if any of these
        # is renamed the assertion fails and says so, which is the whole cost.
        "MemoryStore",  # a Protocol class
        "PROTOCOL_VERSION",  # a module-level constant
        "UtcInstant",  # a `type` alias in `core/types.py`
        "streamValues",  # `async function*` in the gateway's `app.js`
    ],
)
def test_a_real_symbol_of_this_repository_resolves(token: str) -> None:
    """The direction ADR-0209 §3 needs: a citation of real code still binds."""
    assert token in defined_names(_ROOT, ["HEAD"])


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

    Each is backticked somewhere in nearly every ADR and written into nearly every
    ADR PR's diff, so a shape-only reading matched between any two ADR lanes. None
    of them names anything this repository defines, which is what makes each an
    *evaluated* not-a-symbol rather than an unevaluable test.
    """
    assert token not in defined_names(_ROOT, ["HEAD"])
