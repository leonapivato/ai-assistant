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
split across lines is still one node.
"""

from __future__ import annotations

import ast
from pathlib import Path

import ai_assistant

_PACKAGE = Path(ai_assistant.__file__).parent


def _constructions(tree: ast.AST) -> list[ast.Call]:
    """Every ``MemoryWrite(...)`` call in ``tree``.

    Matched on the callee's name, so both ``MemoryWrite(...)`` and a qualified
    ``types.MemoryWrite(...)`` are found. Anything else named ``MemoryWrite`` would
    have to be a second class with the same name, which this repository does not
    have and which would be its own problem.
    """
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == "MemoryWrite":
            found.append(node)
    return found


def _declares_mode(call: ast.Call) -> bool:
    """Whether ``call`` names ``mode``, by keyword or by ``**`` unpacking.

    ``**kwargs`` counts as declaring: the check cannot see inside it, and a caller
    building the mapping deliberately is not the caller this rule is aimed at — the
    one that wrote ``MemoryWrite(record=r)`` and got a destructive write for free.
    Failing closed there would block a legitimate construction with no way to
    satisfy the rule.
    """
    return any(keyword.arg in {"mode", None} for keyword in call.keywords)


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
    unpacked = ast.parse("MemoryWrite(**write_kwargs)")
    qualified = ast.parse("types.MemoryWrite(record=r)")

    assert [_declares_mode(call) for call in _constructions(accepted)] == [True]
    assert [_declares_mode(call) for call in _constructions(bare)] == [False]
    assert [_declares_mode(call) for call in _constructions(unpacked)] == [True]
    assert [_declares_mode(call) for call in _constructions(qualified)] == [False]


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
