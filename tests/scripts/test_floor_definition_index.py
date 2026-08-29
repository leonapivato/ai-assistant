"""ADR-0209 §3's word "symbol": what this repository's Python actually defines.

`scripts/floor_test.py` binds a moved ADR that names "a symbol occurring in an
added or removed line of the PR's diff". A token is a symbol when it names a
definition this repository carries — ADR-0088 §1(b)'s "a backticked name
identifying something in the repository" — and `floor_test.defined_names` is what
answers that for Python.

It answers it for Python **only**. The four JavaScript and shell files this
repository tracks are not resolved at all: a name of theirs is reached from the
diff side, by `Pr.non_python_changed_lines`, and is pinned end-to-end through
`ship` in `tests/scripts/test_ship_floor_citation.py` rather than here. That split
is the point of this module's scope, not an omission from it.

**The failure this module guards is silent and one-directional.** A name the
resolver cannot see is a symbol judged not to be one, so a floor path clears and a
round that was owed is not charged, and nothing anywhere says so. ADR-0209 §5
prices the other direction as acceptable and forbids this one, so every assertion
below runs that way: a definition must reach the index, and the index may hold
more.

Four names were missed in four successive rounds of PR #1803's own review, each in
a form the pattern of the day did not have — `export function`,
`async function* streamValues`, `type UtcInstant = ...`, and a class method behind
`async` — and one more was every shell function whose name contains the letter
`t`, because POSIX ERE has no tab escape and glibc read the backslash-t in a
bracket expression as the letter itself. That run is why Python is read with `ast`
and why the other two languages are no longer read by a pattern at all: a pattern
over a grammar is an enumeration of it, and the grammar kept winning.

So the two groups here answer two different questions, and the split is not
arbitrary:

- **Python, by form.** `_python_definitions` is checked against small sources, one
  per binding form the language has and one per binding it must *not* treat as a
  definition. A line-oriented reader cannot serve as the independent check here at
  all — a docstring that wraps "…a class for reading…" onto its own line reads as
  `class for` — which is itself the argument for `ast`.
- **The corpus, both directions.** Real symbols this repository is built on must
  resolve, and issue #1799's ADR-header vocabulary must not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
from floor_test import UnevaluableError, _python_definitions, defined_names  # noqa: E402

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
    assert "render" in _python_definitions(_BINDS[form].encode(), "m.py"), form


@pytest.mark.parametrize("form", _DOES_NOT_BIND)
def test_a_name_python_only_uses_is_not_a_definition(form: str) -> None:
    """Binding a name locally is not defining the thing the citation names."""
    assert "render" not in _python_definitions(_DOES_NOT_BIND[form].encode(), "m.py"), form


def test_a_python_file_that_will_not_parse_binds_under_section_6() -> None:
    """A parse failure is §6's own first named instance, not a cue to guess.

    This module carried a line-oriented fallback for exactly this case, and
    adversarial review of PR #1803 found it short of `type Widget = object`: the
    file's real definition drops out of the index, so a moved ADR citing it clears
    a floor that was owed. That is the fifth appearance of one defect — a grammar
    read by a pattern the pattern does not have — and the answer is to stop
    reading the grammar. Raising binds, which is loud and is the priced direction.
    """
    with pytest.raises(UnevaluableError, match="will not parse"):
        _python_definitions(b"type Widget = object\ndef (:\n", "src/pkg/broken.py")


# --- The corpus, both directions ----------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        # One per language and per form, named rather than derived: if any of these
        # is renamed the assertion fails and says so, which is the whole cost.
        "MemoryStore",  # a Protocol class
        "PROTOCOL_VERSION",  # a module-level constant
        "UtcInstant",  # a `type` alias in `core/types.py`
        "judge",  # a module-level `def`, in `scripts/floor_test.py` itself
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
