"""Mechanical enforcement of ADR-0108 §1: a write states its mode.

ADR-0108 §1 rules that every ``MemoryStore`` write under ``src/ai_assistant/``
declares its collision intent as a ``MemoryWriteMode`` at the call site, so that
"which writes here can destroy a standing record" is answerable by reading the code
rather than by knowing what each verb defaults to.

``MemoryWrite.mode`` defaults to ``MemoryWriteMode.UPSERT`` (ADR-0046 §2), which
makes ``MemoryWrite(record=r)`` a **destructive write containing no word to find** —
the second silent default beside ``MemoryStore.add``, and the one that arrives at
the very door ADR-0108 §2 routes every ingestor write through. §5 requires this
check rather than leaving that to review.

**Why this default gets a check and ``add`` does not**, which ADR-0108 §7 states and
is repeated here because it is the obvious question: a ``MemoryWrite`` construction
names a unique class in a parseable expression, so the check is sound. "Is this call
``MemoryStore.add``?" is not decidable from the source in a duck-typed tree — ``add``
is the name every ``set`` and every ``TaskGroup`` uses — so a check there would be a
name heuristic with false positives, or a type-directed one failing open exactly
where a new caller is likeliest to be careless.

## Two checks, because one of them makes the other sound

The obvious check — "every ``MemoryWrite(...)`` call names its mode" — is only as
good as its ability to recognise the call, and a name can be renamed:
``from ... import MemoryWrite as W``; ``Write = MemoryWrite``;
``def build(f=MemoryWrite)``. An earlier draft chased those by resolving aliases,
and each round of that produced a new one to chase — then, once the resolver grew
scopes, a new way for it to be *wrong* about unrelated code, which is the worse
failure: a check that invents violations in code its author never touched gets
deleted rather than fixed.

So the alias question is not answered, it is **removed**. The second check asserts
the class is **never bound to another name** anywhere under ``src/ai_assistant/``.
Given that, every construction is spelled ``MemoryWrite(...)`` or
``<module>.MemoryWrite(...)``, and a literal finder is complete — no scope analysis,
no name resolution, and nothing to be wrong about. The two together are sound in a
way neither is alone.

This is deliberately a *convention* enforced mechanically, in the shape
``tests/core/test_protocol_triad.py`` uses for the triad's naming: a lane that has a
real reason to alias the class should change this check in the same PR, on purpose,
rather than discover that aliasing quietly disabled the other one.

**Where it stops.** Indirection through a value the source never spells — a
function's return, a container element, ``functools.partial``, ``getattr`` — is not
reachable by any AST check and is not chased. That boundary is the same one
ADR-0108 §7 draws around ``add``: the check is aimed at the **accidental** default,
the caller who wrote ``MemoryWrite(record=r)`` because the field has one. Reaching
the same effect through indirection means building the bypass deliberately.

Both checks read the **parsed source**, never a grep: a comment, a docstring, or a
string mentioning ``MemoryWrite`` is not a construction, and a call split across
lines is still one node. What each check *rejects* is proved below, because a
predicate that accepted everything would look identical on the tree it is pointed
at — which is the failure this module exists to prevent one layer up.
"""

from __future__ import annotations

import ast
from pathlib import Path

import ai_assistant

_PACKAGE = Path(ai_assistant.__file__).parent
_CLASS = "MemoryWrite"


def _sources() -> list[Path]:
    return sorted(_PACKAGE.rglob("*.py"))


def _where(source: Path, node: ast.AST) -> str:
    return f"{source.relative_to(_PACKAGE.parent)}:{getattr(node, 'lineno', 0)}"


def _names_the_class(node: ast.expr) -> bool:
    """Whether ``node`` is a reference to the class, plainly spelled.

    Only the literal name and the qualified ``<module>.MemoryWrite`` form. It never
    has to decide what an arbitrary name refers to, which is the property that keeps
    both checks free of false positives.
    """
    if isinstance(node, ast.Name):
        return node.id == _CLASS
    return isinstance(node, ast.Attribute) and node.attr == _CLASS


def _constructions(tree: ast.AST) -> list[ast.Call]:
    """Every ``MemoryWrite(...)`` call in ``tree``.

    Complete only because :func:`_renamings` is empty — see the module docstring.
    """
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _names_the_class(node.func)
    ]


def _renamings(tree: ast.AST) -> list[ast.AST]:
    """Every node that binds the class to some other name.

    The three static binding forms, which are the three ways to make a construction
    that :func:`_constructions` cannot see:

    - ``from ai_assistant.core.types import MemoryWrite as W``
    - ``Write = MemoryWrite`` (and the annotated form)
    - ``def build(factory=MemoryWrite): ...``

    A plain ``import MemoryWrite`` is not a renaming and is what every module here
    already does.
    """
    found: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            found.extend(
                node
                for alias in node.names
                if alias.name.rsplit(".", 1)[-1] == _CLASS
                and alias.asname is not None
                and alias.asname != _CLASS
            )
        elif (isinstance(node, ast.Assign) and _names_the_class(node.value)) or (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _names_the_class(node.value)
        ):
            found.append(node)
        elif isinstance(node, ast.arguments):
            defaults = [*node.defaults, *(d for d in node.kw_defaults if d is not None)]
            found.extend(default for default in defaults if _names_the_class(default))
    return found


def _declares_mode(call: ast.Call) -> bool:
    """Whether ``call`` names ``mode`` in a way this check can actually read.

    A literal ``mode=`` keyword, or a ``**{...}`` whose dict *display* carries a
    literal ``"mode"`` key. **An opaque ``**mapping`` does not count**, and that is
    worth stating: ``MemoryWrite(record=r, **{})`` and
    ``MemoryWrite(record=r, **kwargs)`` both take ``MemoryWriteMode.UPSERT`` from the
    field default, so a check that waved them through would fail open on exactly the
    construction that most looks written to get past a rule — while looking, on
    today's tree, identical to one that did not.

    Failing closed costs nothing and is not a guess about the future: nothing under
    ``src/ai_assistant/`` builds a ``MemoryWrite`` this way, and a caller that one
    day needs to can pass ``mode`` alongside the unpack.
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


def test_the_class_is_never_bound_to_another_name() -> None:
    """The check that makes the next one complete (module docstring, "Two checks").

    Not a style rule. Every renaming form is a construction the literal finder walks
    past, so an alias here does not merely obscure a call — it *disables* ADR-0108
    §1's enforcement for that module, silently and while the suite stays green.
    """
    renamed = [
        _where(source, node)
        for source in _sources()
        for node in _renamings(ast.parse(source.read_text(encoding="utf-8"), filename=str(source)))
    ]

    assert not renamed, (
        f"{_CLASS} is bound to another name, which hides every construction made "
        "through it from the mode check below and so disables ADR-0108 §1 for that "
        "module. Use the class directly, or change this check deliberately in the "
        "same PR. At: " + ", ".join(renamed)
    )


def test_every_construction_in_the_package_names_its_mode() -> None:
    """ADR-0108 §1, mechanically: no write inherits ``MemoryWrite``'s upsert default.

    The failure names file and line, because the fix is one keyword and the only
    hard part is finding which construction it belongs on.
    """
    undeclared = [
        _where(source, call)
        for source in _sources()
        for call in _constructions(
            ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        )
        if not _declares_mode(call)
    ]

    assert not undeclared, (
        f"a {_CLASS} is constructed without naming its mode, so it inherits "
        "MemoryWriteMode.UPSERT and destroys whatever stands at that id with no word "
        "in the call to say so (ADR-0108 §1, §7). Add mode=... at: " + ", ".join(undeclared)
    )


def test_the_mode_check_can_see_an_undeclared_construction() -> None:
    """The negative case, because a check that accepts everything looks identical."""
    accepted = ast.parse("MemoryWrite(record=r, mode=MemoryWriteMode.UPSERT)")
    bare = ast.parse("MemoryWrite(record=r)")
    qualified = ast.parse("types.MemoryWrite(record=r)")

    assert [_declares_mode(call) for call in _constructions(accepted)] == [True]
    assert [_declares_mode(call) for call in _constructions(bare)] == [False]
    assert [_declares_mode(call) for call in _constructions(qualified)] == [False]


def test_an_opaque_unpacking_does_not_count_as_declaring() -> None:
    """``**{}`` is the same destructive default as passing nothing, and reads as care.

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


def test_the_renaming_check_sees_every_binding_form() -> None:
    """Each form the literal finder would walk past is caught by the other check."""
    imported = ast.parse("from ai_assistant.core.types import MemoryWrite as W")
    assigned = ast.parse("Write = MemoryWrite")
    annotated = ast.parse("Write: type[MemoryWrite] = MemoryWrite")
    qualified_alias = ast.parse("W = types.MemoryWrite")
    positional_default = ast.parse("def build(f=MemoryWrite): ...")
    keyword_default = ast.parse("def build(*, f=MemoryWrite): ...")

    for tree in (
        imported,
        assigned,
        annotated,
        qualified_alias,
        positional_default,
        keyword_default,
    ):
        assert _renamings(tree), ast.dump(tree)


def test_the_renaming_check_leaves_unrelated_code_alone() -> None:
    """The false positives it must not produce, which is the other half of soundness.

    A check that fires on code its author never touched gets deleted rather than
    fixed, so what it *ignores* is pinned as deliberately as what it catches. Note
    the third case in particular: a same-named class from somewhere else is not this
    one, and no amount of name matching should pretend otherwise.
    """
    plain_import = ast.parse("from ai_assistant.core.types import MemoryWrite")
    same_name = ast.parse("from ai_assistant.core.types import MemoryWrite as MemoryWrite")
    unrelated_alias = ast.parse("from elsewhere import Widget as W\nWrite = Widget")
    unrelated_default = ast.parse("def build(f=Widget, *, g=None): ...")
    a_construction = ast.parse("MemoryWrite(record=r, mode=m)")

    for tree in (plain_import, same_name, unrelated_alias, unrelated_default, a_construction):
        assert _renamings(tree) == [], ast.dump(tree)


def test_a_lexical_mention_is_not_a_construction() -> None:
    """Reading the parse tree is the point: prose about ``MemoryWrite`` is not one.

    This module's own docstring and several contract docstrings discuss the class at
    length, and a grep-based check would fail on all of them — then be "fixed" by
    loosening it until it caught nothing.
    """
    prose = ast.parse('"""A MemoryWrite(record=r) is what this paragraph describes."""')
    commented = ast.parse("x = 1  # MemoryWrite(record=r)")

    assert _constructions(prose) == []
    assert _constructions(commented) == []
