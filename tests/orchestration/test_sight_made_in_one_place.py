"""ADR-0383 §9:2's named test: a sight is made under ``orchestration/`` in one place.

**What it fails on.** A module under ``src/ai_assistant/orchestration/`` that constructs
a sight outside the places that hold one by §6:4 to §6:8: the work's sight, made when its
facts are first recorded and made again each time they are recorded again (§6:4 to §6:6),
in :meth:`ActivationState._see
<ai_assistant.orchestration.activation_state.ActivationState>`; and the producer's sight,
made by the observer's run once for each episode it reads, from the facts and senders that
episode records (§6:7), in ``observer/stage.py``'s ``_sight_of``. A run's and a tidy-up's
(§6:8) are made where milestone 22's B9b and B8c put them, each adding its place here.

**How it reads "constructs".** Any reference to ``Sight`` or ``SightBound`` outside an
annotation, by its own name or as an attribute (``Sight(...)``, ``Sight.of_work``,
``types.Sight.of_work``, ``ai_assistant.core.types.SightBound.person``, a reference kept
to call later), since naming the type at run time is how one is made; any call of
``meet`` or ``of_tidy_up``, which make a sight from one held; any import of either name
under another; and any assignment to a ``_sight`` attribute, the field the work's sight is
held in. A stage reads the sight its pass carries (``ActivationState.sight``,
``activation_state.work_sight()``) and makes none. Reaching the type by a string
(``getattr(types, "Sight")``) is not read.
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
PLACES: Final = frozenset(
    {
        # §6:4 to §6:6: a work's.
        "activation_state.py:ActivationState._see",
        # §6:7: a producer's, the observer's for an ended work.
        "observer/stage.py:_sight_of",
    }
)

_ROOT: Final = Path(ai_assistant.orchestration.__file__).parent


def _annotations_of(tree: ast.Module) -> list[ast.expr]:
    """Every annotation in ``tree``: parameters', returns' and annotated names'."""
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            found.append(node.annotation)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns:
            found.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            found.append(node.annotation)
    return found


class _Makers(ast.NodeVisitor):
    """Each place in one module that makes a sight, by its qualified name."""

    def __init__(self, module: str, tree: ast.Module) -> None:
        self._module = module
        self._scope: list[str] = []
        self.found: set[str] = set()
        # Every node inside an annotation, where naming a type makes nothing.
        self._annotations = {
            id(inner) for annotation in _annotations_of(tree) for inner in ast.walk(annotation)
        }

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
        if isinstance(called, ast.Attribute) and called.attr in _MAKING_MEMBERS:
            self.found.add(self._here())
        self.generic_visit(node)

    def _referred(self, node: ast.Name | ast.Attribute) -> None:
        named = node.id if isinstance(node, ast.Name) else node.attr
        if named in _SIGHT_TYPES and id(node) not in self._annotations:
            self.found.add(self._here())

    def visit_Name(self, node: ast.Name) -> None:
        self._referred(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._referred(node)
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
        tree = ast.parse(path.read_text(encoding="utf-8"))
        makers = _Makers(path.relative_to(root).as_posix(), tree)
        makers.visit(tree)
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
def reads(state, sight: Sight) -> SightBound:
    held: Sight = state.sight
    return held
from ai_assistant.core import types
def qualified(facts) -> None:
    types.Sight.of_work(facts, (), activation="a")
def kept() -> None:
    make = ai_assistant.core.types.SightBound.person
    make("p")
"""
    (tmp_path / "stage.py").write_text(source, encoding="utf-8")
    assert sight_makers(tmp_path) == {
        "stage.py:<module>",
        "stage.py:direct",
        "stage.py:Stage.run",
        "stage.py:Stage.bound",
        "stage.py:widened",
        "stage.py:qualified",
        "stage.py:kept",
    }
