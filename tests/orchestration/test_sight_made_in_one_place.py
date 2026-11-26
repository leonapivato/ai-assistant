"""ADR-0383 §9:2's named test: a sight is made under ``orchestration/`` in one place.

**What it fails on.** A module under ``src/ai_assistant/orchestration/`` that constructs
a sight outside the places that hold one by §6:4 to §6:8. Today there is one: the work's
sight, made when its facts are first recorded and made again each time they are recorded
again (§6:4 to §6:6), in :meth:`ActivationState._see
<ai_assistant.orchestration.activation_state.ActivationState>`. A producer's sight
(§6:7), a run's and a tidy-up's (§6:8) are made where milestone 22's B9 and B8c put them,
each adding its place here.

**How it reads "constructs".** Any call of ``Sight`` or ``SightBound`` or of one of their
members (``Sight.of_work``, ``Sight.model_validate``, ``SightBound.person`` …); any call of
``meet`` or ``of_tidy_up``, which make a sight from one held; any import of either name
under another; and any assignment to a ``_sight`` attribute, the field the work's sight is
held in. A stage reads the sight its pass carries (``ActivationState.sight``,
``activation_state.work_sight``) and makes none.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import ai_assistant.orchestration

#: The types a sight is made of.
_SIGHT_TYPES: Final = frozenset({"Sight", "SightBound"})
#: The members that make a sight from one held.
_MAKING_MEMBERS: Final = frozenset({"meet", "of_tidy_up"})
#: The attribute the work's sight is held in.
_HELD_IN: Final = "_sight"

#: The places that hold one by §6:4 to §6:8, as ``<module path>:<qualified name>``.
PLACES: Final = frozenset({"activation_state.py:ActivationState._see"})

_ROOT: Final = Path(ai_assistant.orchestration.__file__).parent


class _Makers(ast.NodeVisitor):
    """Each place in one module that makes a sight, by its qualified name."""

    def __init__(self, module: str) -> None:
        self._module = module
        self._scope: list[str] = []
        self.found: set[str] = set()

    def _here(self) -> str:
        return f"{self._module}:{'.'.join(self._scope) or '<module>'}"

    def _scoped(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    visit_FunctionDef = _scoped  # noqa: N815 — the visitor's protocol names them
    visit_AsyncFunctionDef = _scoped  # noqa: N815
    visit_ClassDef = _scoped  # noqa: N815

    def visit_Call(self, node: ast.Call) -> None:
        called = node.func
        if (isinstance(called, ast.Name) and called.id in _SIGHT_TYPES) or (
            isinstance(called, ast.Attribute)
            and (
                called.attr in _MAKING_MEMBERS
                or (isinstance(called.value, ast.Name) and called.value.id in _SIGHT_TYPES)
            )
        ):
            self.found.add(self._here())
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if any(
            one.name in _SIGHT_TYPES and one.asname not in {None, one.name} for one in node.names
        ):
            self.found.add(self._here())

    def _assigned(self, targets: list[ast.expr]) -> None:
        for target in targets:
            for one in ast.walk(target):
                if isinstance(one, ast.Attribute) and one.attr == _HELD_IN:
                    self.found.add(self._here())

    def visit_Assign(self, node: ast.Assign) -> None:
        self._assigned(node.targets)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._assigned([node.target])
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._assigned([node.target])
        self.generic_visit(node)


def sight_makers(root: Path = _ROOT) -> frozenset[str]:
    """Every place under ``root`` that makes a sight, ``<module path>:<qualified name>``."""
    found: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        makers = _Makers(path.relative_to(root).as_posix())
        makers.visit(ast.parse(path.read_text(encoding="utf-8")))
        found |= makers.found
    return frozenset(found)


def test_a_sight_is_made_only_where_a_work_s_facts_are_recorded() -> None:
    """§9:2: no stage makes a sight; it reads the one its pass carries."""
    assert sight_makers() == PLACES


def test_the_reading_sees_every_way_a_sight_is_made(tmp_path: Path) -> None:
    source = """
from ai_assistant.core.types import Sight as Seen, SightBound
def direct() -> None:
    Sight(reader="work", bounds=())
class Stage:
    def run(self, sight) -> None:
        sight.meet(sight)
    def bound(self) -> None:
        SightBound.anyone()
def widened(state) -> None:
    state._sight = None
def reads(state) -> None:
    return state.sight
"""
    (tmp_path / "stage.py").write_text(source, encoding="utf-8")
    assert sight_makers(tmp_path) == {
        "stage.py:<module>",
        "stage.py:direct",
        "stage.py:Stage.run",
        "stage.py:Stage.bound",
        "stage.py:widened",
    }
