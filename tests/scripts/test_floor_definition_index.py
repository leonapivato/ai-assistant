"""What this repository's Python defines, and which definition a moved line makes.

Two questions ADR-0209 asks of the same grammar, and `scripts/floor_test.py`
answers both with `ast`. §3's is *whether a token is a symbol at all*, answered
across the whole tree by `defined_names`, and it is what the first half of this
module covers. §4's second limb asks *whose definition this base move changed*,
answered per line by `moved_definitions`, and it is what the second half covers.

**§3's.** `floor_test` binds a moved ADR that names "a symbol occurring in an
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

So the groups here answer different questions, and the split is not arbitrary:

- **Python, by form.** `_python_definitions` is checked against small sources, one
  per binding form the language has and one per binding it must *not* treat as a
  definition. A line-oriented reader cannot serve as the independent check here at
  all — a docstring that wraps "…a class for reading…" onto its own line reads as
  `class for` — which is itself the argument for `ast`.
- **The corpus, both directions.** Real symbols this repository is built on must
  resolve, and issue #1799's ADR-header vocabulary must not.
- **§4, by move.** `moved_definitions` is checked against pairs of endpoints, each
  paired with what the line pattern it replaced returned over the same pair —
  which is the whole of issue #2049, where that docstring-wrapping *did* happen,
  in `core/types.py`, and bound every open lane on `for`.
"""

from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
from floor_test import (  # noqa: E402
    UnevaluableError,
    _python_definitions,
    defined_names,
    moved_definitions,
)

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


# --- §4's second limb: which definition a *moved line* makes ------------------
#
# `defined_names` above answers §3's "is this token a symbol at all". `moved_
# definitions` answers a different question on the same grammar — "whose
# definition did this base move change" — and it is asked per line, because a move
# that changes a signature or an enum member's value changes that name's
# definition while renaming nothing. So a set difference between the two endpoints
# is not the reading; a per-line one is.
#
# Every case below is mutation-checked against the pattern this replaced, quoted
# here so the comparison is on the page rather than in a commit:
#
#     ^\s*(?:async\s+)?def\s+(?P<def>[^\W\d]\w*)
#     |^\s*class\s+(?P<cls>[^\W\d]\w*)
#     |^\s*(?P<bound>[^\W\d]\w*)\s*(?::[^=\n]+)?=(?!=)
#
# and the check is stated as `_REPLACED_PATTERN` so each parametrised case says
# for itself which direction the pattern got wrong: it *matched* three lines of
# docstring prose (issue #2049, the over-binding this closes), and it *missed* a
# bare annotated field, a `type` alias, a decorator, and every multi-line header
# and value whose changed part is not the line the name is on (under-binding, the
# direction ADR-0209 §5 forbids). The cases where it agreed are marked so too, so
# that the assertions below are not silently testing only the disagreements.

_REPLACED_PATTERN = re.compile(
    r"^\s*(?:async\s+)?def\s+(?P<def>[^\W\d]\w*)"
    r"|^\s*class\s+(?P<cls>[^\W\d]\w*)"
    r"|^\s*(?P<bound>[^\W\d]\w*)\s*(?::[^=\n]+)?=(?!=)",
    re.UNICODE,
)


def _pattern_names(old: str, new: str) -> set[str]:
    """What the line pattern this change replaced would have returned."""
    names: set[str] = set()
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), n=0, lineterm="")
    for line in diff:
        if line[:1] not in {"+", "-"} or line.startswith(("+++", "---")):
            continue
        match = _REPLACED_PATTERN.match(line[1:])
        if match is not None:
            names.add(match.group("def") or match.group("cls") or match.group("bound"))
    return names


#: `(old, new, expected, what the replaced pattern returned)`. The fourth field is
#: asserted, not documented: it is what makes each case a regression test rather
#: than a restatement of the implementation.
_MOVES = {
    # Issue #2049 verbatim: `core/types.py`'s own prose, wrapped so that a
    # sentence begins "class for all of them". `word_in("for", pr.text)` is true
    # of essentially every PR, so this bound every open lane on the day it landed.
    "prose in a docstring": (
        'class Refusal:\n    """A reason.\n\n    One\n    """\n',
        'class Refusal:\n    """A reason.\n\n    One\n    class for all of them rather\n    """\n',
        set(),
        {"for"},
    ),
    # The same shape one line lower down, and the same for `def` and for a bound
    # name: a docstring is a string literal and `ast` cannot see into one.
    "a def in a docstring": (
        'def render():\n    """Do it.\n\n    Old.\n    """\n',
        'def render():\n    """Do it.\n\n    def not really a function\n    """\n',
        set(),
        {"not"},
    ),
    "an assignment in a docstring": (
        'def render():\n    """Do it.\n\n    Old.\n    """\n',
        'def render():\n    """Do it.\n\n    version = whatever the caller passed\n    """\n',
        set(),
        {"version"},
    ),
    # A comment is invisible to `ast` for a second reason: the tokenizer drops it
    # before a tree exists. The pattern missed it only because `#` is not
    # whitespace and every one of its three alternatives is anchored — so this
    # case is pinned to say that a comment must stay invisible under both
    # readings, not to record a disagreement.
    "prose in a comment": (
        "VERSION = 1\n",
        "VERSION = 1\n# class for the whole set, or a def for each\n",
        set(),
        set(),
    ),
    # The four the pattern and the parse agree on, which is most real traffic.
    "a class added": ("x = 1\n", "x = 1\n\n\nclass Widget:\n    pass\n", {"Widget"}, {"Widget"}),
    "a class removed": ("class Widget:\n    pass\n", "", {"Widget"}, {"Widget"}),
    "a def added": ("x = 1\n", "x = 1\n\n\ndef render():\n    ...\n", {"render"}, {"render"}),
    "an async def added": (
        "x = 1\n",
        "x = 1\n\n\nasync def render():\n    ...\n",
        {"render"},
        {"render"},
    ),
    "a nested def added": (
        "class C:\n    def a(self) -> None: ...\n",
        "class C:\n    def a(self) -> None: ...\n\n    def render(self) -> None: ...\n",
        {"render"},
        {"render"},
    ),
    "an enum member added": (
        "class R(StrEnum):\n    ONE = 'one'\n",
        "class R(StrEnum):\n    ONE = 'one'\n    TOO_LARGE = 'too-large'\n",
        {"TOO_LARGE"},
        {"TOO_LARGE"},
    ),
    # A signature change renames nothing, so a set difference between the two
    # endpoints clears it. §4 binds on it: the definition of `render` changed.
    "a signature changed, the name kept": (
        "def render(a: int) -> None: ...\n",
        "def render(a: int, b: int) -> None: ...\n",
        {"render"},
        {"render"},
    ),
    # `@property` above an otherwise untouched `def` changes what that name is, so
    # the header span reaches down to the first decorator. The pattern read the
    # decorator's own line and matched nothing on it.
    "a decorator added above an untouched def": (
        "class C:\n    def render(self) -> None: ...\n",
        "class C:\n    @property\n    def render(self) -> None: ...\n",
        {"render"},
        set(),
    ),
    # Adversarial review of PR #2054, round 1, blocker 1: a multi-line header or
    # value can change without the line carrying the name changing at all. Each of
    # the next four is an under-bind the pattern had too — it reads one line, and
    # `value: str,` on its own line matches none of its three alternatives.
    "a parameter annotation on its own line": (
        "def render(\n    value: int,\n) -> None: ...\n",
        "def render(\n    value: str,\n) -> None: ...\n",
        {"render"},
        set(),
    ),
    "a return annotation on its own line": (
        "def render(\n    a: int,\n) -> None:\n    ...\n",
        "def render(\n    a: int,\n) -> str:\n    ...\n",
        {"render"},
        set(),
    ),
    "a base class on its own line": (
        "class Model(\n    Base,\n):\n    a: int\n",
        "class Model(\n    Other,\n):\n    a: int\n",
        {"Model"},
        set(),
    ),
    "a multi-line value gaining an entry": (
        "FIELDS = (\n    'a',\n)\n",
        "FIELDS = (\n    'a',\n    'b',\n)\n",
        {"FIELDS"},
        set(),
    ),
    # And the boundary the same widening must not cross. `end_lineno` on a
    # `ClassDef` is the last line of its *body*, so a whole-statement span would
    # put every docstring line inside the definition of the class — which is
    # #2049's move exactly (`class FetchRefusal`), read as a bind on a name PRs
    # actually write instead of on `for`. The header stops at the signature.
    "a docstring changed inside a multi-line class": (
        'class Model:\n    """One.\n\n    Old.\n    """\n\n    a: int\n',
        'class Model:\n    """One.\n\n    class for all of them rather\n    """\n\n    a: int\n',
        set(),
        {"for"},
    ),
    # The two the pattern *missed*. Both are under-binding, which ADR-0209 §5
    # names as the failure it must not have — a pydantic field and a `Protocol`
    # member are exactly what `core/types.py` and `core/protocols.py` carry.
    "a bare annotated field added": (
        "class Model(BaseModel):\n    a: int\n",
        "class Model(BaseModel):\n    a: int\n    render: str\n",
        {"render"},
        set(),
    ),
    "a type alias added": ("x = 1\n", "x = 1\ntype Render = int\n", {"Render"}, set()),
}


@pytest.mark.parametrize("move", _MOVES)
def test_a_moved_line_defines_what_python_says_it_defines(move: str) -> None:
    """ADR-0209 §4's second limb, read off the parse rather than off the line."""
    old, new, expected, _ = _MOVES[move]
    assert moved_definitions(old, new) == expected, move


@pytest.mark.parametrize("move", _MOVES)
def test_the_replaced_pattern_is_what_each_case_is_measured_against(move: str) -> None:
    """Pin the mutation: without this, ten of the cases above prove nothing.

    A case the pattern already got right is worth keeping — it is what says the
    narrowing did not throw the real answers out with the false one — but a case
    it got *wrong* is the regression, and this is what distinguishes them.
    """
    old, new, _, by_pattern = _MOVES[move]
    assert _pattern_names(old, new) == by_pattern, move


def test_an_endpoint_that_will_not_parse_binds_under_section_6() -> None:
    """§6's own first named instance: "a parse failure at either endpoint".

    Not a fallback to the pattern. A fallback would be the pattern back under
    another name, on precisely the input nobody can vouch for, and it fails open:
    where its names miss the PR's text `_contract_binding` returns None and the
    floor clears. `_python_definitions` carried such a fallback and adversarial
    review of PR #1803 found it short of `type Widget = object`. Raising binds,
    and `_judge_conditional` publishes the reason.
    """
    for old, new in (("def (:\n", "x = 1\n"), ("x = 1\n", "def (:\n")):
        with pytest.raises(UnevaluableError, match="will not parse"):
            moved_definitions(old, new)


def test_a_form_feed_does_not_shift_the_line_numbering() -> None:
    """`str.splitlines` breaks on a form feed and Python's tokenizer does not.

    The reading joins a diff's line numbers to `ast`'s `lineno` on equality, so a
    splitter more generous than the tokenizer puts every definition after the form
    feed one line out — and the name that then reads as moved is a *different*
    one, which is wrong in both directions at once.
    """
    old = "x = 1\n\x0cdef render() -> None: ...\n"
    new = "x = 2\n\x0cdef render() -> None: ...\n"
    assert moved_definitions(old, new) == {"x"}
