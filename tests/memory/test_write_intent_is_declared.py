"""Mechanical enforcement of ADR-0108 §1: a write states its mode.

ADR-0108 §1 rules that every ``MemoryStore`` write under ``src/ai_assistant/``
declares its collision intent as a ``MemoryWriteMode`` at the call site, so that
"which writes here can destroy a standing record" is answerable by reading the
code rather than by knowing what each verb defaults to.

``MemoryWrite.mode`` defaults to ``MemoryWriteMode.UPSERT`` (ADR-0046 §2), which
makes ``MemoryWrite(record=r)`` a **destructive write containing no word to find**
— the second silent default beside ``MemoryStore.add``, and the one that arrives at
the very door ADR-0108 §2 routes every ingestor write through. §5 requires this
check rather than leaving that to review.

**Why this default gets a check and ``add`` does not**, which ADR-0108 §7 states
and is repeated here because it is the obvious question: a ``MemoryWrite``
construction names a unique class in a parseable expression, so the check is sound.
"Is this call ``MemoryStore.add``?" is not decidable from the source in a duck-typed
tree — ``add`` is the name every ``set`` and every ``TaskGroup`` uses, and
``self._store`` is Protocol-typed at some call sites and untyped at others — so a
check there would be a name heuristic with false positives, or a type-directed one
failing open exactly where a new caller is likeliest to be careless. ADR-0108 §1 is
therefore checked where a check can be sound, and rests on §2 having left no ``add``
callers where it cannot.

The check reads the **parsed source**, not a grep: a comment, a docstring, or a
string literal mentioning ``MemoryWrite`` is not a construction, and a construction
split across lines is still one node. It resolves every **static binding form** that
renames the class — import alias, assignment, parameter default — and refuses to
treat an opaque ``**mapping`` as a declaration. All four were ways past an earlier
draft of this module, and each has a negative case below. A check that accepts
everything is indistinguishable from a sound one on the tree it is pointed at, so
what it *rejects* is proved rather than assumed — including the false positives it
must not produce, which are the failure that gets a check like this deleted.

What it deliberately does **not** chase is indirection through a value the source
does not spell; :func:`_local_names` gives the reasoning and why that boundary is
where it is.
"""

from __future__ import annotations

import ast
from pathlib import Path

import ai_assistant

_PACKAGE = Path(ai_assistant.__file__).parent


def _names_the_class(node: ast.expr, known: set[str]) -> bool:
    """Whether ``node`` refers to the class: a known name, or ``*.MemoryWrite``."""
    if isinstance(node, ast.Name):
        return node.id in known
    return isinstance(node, ast.Attribute) and node.attr == "MemoryWrite"


def _local_names(tree: ast.AST) -> set[str]:
    """Every local name bound to ``MemoryWrite`` in ``tree``, aliases included.

    Two ways to rename it, and a check that missed either would report a clean tree
    while a destructive default sat in it:

    - ``from ai_assistant.core.types import MemoryWrite as W``, then ``W(record=r)``;
    - ``Write = MemoryWrite``, then ``Write(record=r)``.

    Three ways to rename it, and a check that missed any would report a clean tree
    while a destructive default sat in it:

    - ``from ai_assistant.core.types import MemoryWrite as W``, then ``W(record=r)``;
    - ``Write = MemoryWrite``, then ``Write(record=r)``;
    - ``def build(factory=MemoryWrite): return factory(record=r)``.

    All three are **static binding forms** — the class is named in the syntax that
    creates the binding — so all three resolve, and they resolve to a fixed point so
    an alias of an alias does too.

    **Where this stops is a design boundary, not an omission.** Once a reference
    reaches a name through a *value* the source does not spell — a function's return,
    a container element, a class attribute read at runtime, ``functools.partial``,
    ``getattr`` — no AST check follows it, and chasing each form in turn has no
    terminus. This check is aimed at the **accidental** default: the caller who wrote
    ``MemoryWrite(record=r)`` because the field has one, which is the whole of what
    ADR-0108 §7 says is checkable. Reaching the same effect through indirection means
    constructing the bypass deliberately — visible in review, and no longer something
    a reader does without noticing. That is the same boundary §7 draws around ``add``,
    and it is stated here so a later reader can tell a deliberate limit from a gap.
    """
    names = {"MemoryWrite"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name.rsplit(".", 1)[-1] == "MemoryWrite"
            )
    while True:
        before = len(names)
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign) and _names_the_class(node.value, names):
                targets = list(node.targets)
            elif (
                isinstance(node, ast.AnnAssign)
                and node.value is not None
                and _names_the_class(node.value, names)
            ):
                targets = [node.target]
            elif isinstance(node, ast.arguments):
                # A parameter whose *default* is the class is bound to it on every
                # call that does not override it, so the parameter name constructs
                # `MemoryWrite` exactly as an assignment alias does.
                positional = node.posonlyargs + node.args
                names.update(
                    parameter.arg
                    for parameter, default in zip(
                        positional[len(positional) - len(node.defaults) :],
                        node.defaults,
                        strict=True,
                    )
                    if _names_the_class(default, names)
                )
                names.update(
                    parameter.arg
                    for parameter, default in zip(node.kwonlyargs, node.kw_defaults, strict=True)
                    if default is not None and _names_the_class(default, names)
                )
            names.update(target.id for target in targets if isinstance(target, ast.Name))
        if len(names) == before:
            return names


def _constructions(tree: ast.AST) -> list[ast.Call]:
    """Every ``MemoryWrite(...)`` call in ``tree``, however it is spelled.

    Matches a bare or aliased name (:func:`_local_names`) and the qualified
    attribute form ``types.MemoryWrite(...)``. Anything else ending in
    ``MemoryWrite`` would have to be a second class of that name, which this
    repository does not have and which would be its own problem.
    """
    local = _local_names(tree)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _names_the_class(node.func, local)
    ]


def _declares_mode(call: ast.Call) -> bool:
    """Whether ``call`` names ``mode`` in a way this check can actually read.

    A literal ``mode=`` keyword, or a ``**{...}`` whose dict *display* carries a
    literal ``"mode"`` key. **An opaque ``**mapping`` does not count**, and that is
    the whole point of stating it: ``MemoryWrite(record=r, **{})`` and
    ``MemoryWrite(record=r, **kwargs)`` both take ``MemoryWriteMode.UPSERT`` from
    the field default, so a check that waved them through would fail open on
    exactly the construction it exists to catch — while looking, on today's tree,
    identical to one that did not.

    Failing closed costs nothing here and is not a guess about the future: nothing
    under ``src/ai_assistant/`` builds a ``MemoryWrite`` this way, and a caller that
    one day needs to can pass ``mode`` alongside the unpack. A check whose only
    bypass requires writing the bypass deliberately is the strongest one available
    without type inference.
    """
    for keyword in call.keywords:
        if keyword.arg == "mode":
            return True
        if (
            keyword.arg is None
            and isinstance(keyword.value, ast.Dict)
            and any(
                isinstance(key, ast.Constant) and key.value == "mode" for key in keyword.value.keys
            )
        ):
            return True
    return False


def test_every_memorywrite_in_the_package_names_its_mode() -> None:
    """ADR-0108 §1, mechanically: no write inherits ``MemoryWrite``'s upsert default.

    The failure message names file and line, because the fix is one keyword and the
    only hard part is finding which construction it belongs on.
    """
    undeclared: list[str] = []
    for source in sorted(_PACKAGE.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        undeclared.extend(
            f"{source.relative_to(_PACKAGE.parent)}:{call.lineno}"
            for call in _constructions(tree)
            if not _declares_mode(call)
        )

    assert not undeclared, (
        "a MemoryWrite is constructed without naming its mode, so it inherits "
        "MemoryWriteMode.UPSERT and destroys whatever stands at that id with no "
        "word in the call to say so (ADR-0108 §1, §7). Add mode=... at: " + ", ".join(undeclared)
    )


def test_the_check_can_see_an_undeclared_construction() -> None:
    """The negative case, because a check that accepts everything looks identical.

    A predicate that always passed would make the case above green forever while
    enforcing nothing — the failure mode this whole module exists to prevent one
    layer up, so it is proved rather than assumed.
    """
    accepted = ast.parse("MemoryWrite(record=r, mode=MemoryWriteMode.UPSERT)")
    bare = ast.parse("MemoryWrite(record=r)")
    qualified = ast.parse("types.MemoryWrite(record=r)")

    assert [_declares_mode(call) for call in _constructions(accepted)] == [True]
    assert [_declares_mode(call) for call in _constructions(bare)] == [False]
    assert [_declares_mode(call) for call in _constructions(qualified)] == [False]


def test_an_opaque_unpacking_does_not_count_as_declaring() -> None:
    """The bypass a first draft of this check allowed, closed and pinned.

    ``MemoryWrite(record=r, **{})`` takes ``MemoryWriteMode.UPSERT`` from the field
    default exactly as ``MemoryWrite(record=r)`` does. A check that accepted any
    ``**`` because it "cannot see inside" would pass both while claiming to enforce
    ADR-0108 §1 — failing open on the one construction that most looks like it was
    written to get past a rule.

    A dict *display* is different: ``**{"mode": m}`` is readable, so it is read.
    """
    empty = ast.parse("MemoryWrite(record=r, **{})")
    opaque = ast.parse("MemoryWrite(record=r, **write_kwargs)")
    literal = ast.parse('MemoryWrite(record=r, **{"mode": m})')
    literal_without = ast.parse('MemoryWrite(**{"record": r})')

    assert [_declares_mode(call) for call in _constructions(empty)] == [False]
    assert [_declares_mode(call) for call in _constructions(opaque)] == [False]
    assert [_declares_mode(call) for call in _constructions(literal)] == [True]
    assert [_declares_mode(call) for call in _constructions(literal_without)] == [False]


def test_a_renamed_class_is_still_found() -> None:
    """Neither way of renaming the class is a way past the finder.

    ``from ... import MemoryWrite as W`` and ``Write = MemoryWrite`` are the same
    destructive default under a different spelling, and a check keyed on the literal
    name reports a clean tree for both. Aliases of aliases resolve too, which is why
    the resolution runs to a fixed point rather than in one pass.

    The negative half matters as much: an unrelated ``W`` in a module that never
    imported the class must **not** match, or the check acquires false positives and
    gets loosened until it catches nothing.
    """
    imported = ast.parse("from ai_assistant.core.types import MemoryWrite as W\nW(record=r)\n")
    assigned = ast.parse("Write = MemoryWrite\nWrite(record=r)\n")
    chained = ast.parse("A = MemoryWrite\nB = A\nB(record=r)\n")
    qualified_alias = ast.parse("W = types.MemoryWrite\nW(record=r)\n")
    positional_default = ast.parse("def build(f=MemoryWrite):\n    return f(record=r)\n")
    keyword_default = ast.parse("def build(*, f=MemoryWrite):\n    return f(record=r)\n")
    unrelated = ast.parse("from somewhere import Widget as W\nW(record=r)\n")

    for tree in (
        imported,
        assigned,
        chained,
        qualified_alias,
        positional_default,
        keyword_default,
    ):
        assert [_declares_mode(call) for call in _constructions(tree)] == [False]
    assert _constructions(unrelated) == []


def test_an_unrelated_parameter_default_is_not_an_alias() -> None:
    """A parameter defaulting to something else must not poison the name set.

    ``_local_names`` grows a set of names that then match *every* call, so a wrong
    entry does not merely miss a construction — it reports constructions that are
    not there, in unrelated code. That failure is worse than the one the check
    exists for, because it lands on a contributor who touched nothing relevant.
    """
    other = ast.parse("def build(f=Widget, *, g=None):\n    return f(record=r)\n")
    no_default = ast.parse("def build(f):\n    return f(record=r)\n")

    assert _constructions(other) == []
    assert _constructions(no_default) == []


def test_a_lexical_mention_is_not_a_construction() -> None:
    """Reading the parse tree is the point: prose about ``MemoryWrite`` is not one.

    Both this module's own docstring and several contract docstrings discuss
    ``MemoryWrite`` at length, and a grep-based check would fail on all of them —
    then be "fixed" by loosening it until it caught nothing.
    """
    prose = ast.parse('"""A MemoryWrite(record=r) is what this paragraph describes."""')
    commented = ast.parse("x = 1  # MemoryWrite(record=r)")

    assert _constructions(prose) == []
    assert _constructions(commented) == []
