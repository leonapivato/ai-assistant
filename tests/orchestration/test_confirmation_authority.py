"""ADR-0078 §3's third composition-root obligation, held structurally.

*No production module produces a* ``UserConfirmation`` (ADR-0329 §5, §20, which
supersede ADR-0321 §5:2's yes path as its producer).

**The answer path retired with ``orchestration/questions.py`` (ADR-0309 §5)**, and
for a while no production module constructed a ``UserConfirmation`` at all, while
``memory/policy.py`` still honoured one as the user's own authority (ADR-0078 §5).
The authority milestone gave it one producer: ``remember``'s runner under ADR-0328
§13's interim built it from the approval a yes to a remember's question made and the
asked call that question showed. That runner retired with the interim (#3391): a
``remember`` now records a candidate, and a yes to its *confirm* is read from the
records the observer reads (ADR-0329 §5:5), so again nothing constructs one. The
guard pins **exactly none**: any producer is a new holder of that authority. **Any
change of producer is an authority change**, and it has to change this test
deliberately rather than pass it on its first appearance.

ADR-0078 §10 item 3 is why the check is structural: "Nothing in the writer's six
checks looks for a claim, so a helper that assembled a confirmation from a pending
deferral's id, key and conflict ids — all of which reads expose — could retire a
``USER_ASSERTED`` record while every answer-path test still passed." A behavioural
test cannot see a producer that nothing happens to call yet; a structural one can.

So this reads the source. ``tests/core/test_protocol_triad.py`` is the shape it
copies — parse rather than import, and require *evidence* rather than a name.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

import ai_assistant

#: The production tree. Deliberately **not** ``tests/``: a test constructing a
#: confirmation to drive the writer's floor is exercising ADR-0028 §8's conformance
#: clause, which is a different obligation and a legitimate thing for a test to do.
#: What may not exist is any *production* producer of the authority.
_SRC: Final = Path(ai_assistant.__file__).resolve().parent

#: The value whose construction is the authority. Named rather than discovered,
#: because the obligation is about this one type.
_AUTHORITY: Final = "UserConfirmation"


@dataclass(frozen=True)
class _Construction:
    """One place production code builds the authority."""

    module: str
    function: str


def _constructions(tree: ast.Module, module: str) -> list[_Construction]:
    """Every ``UserConfirmation(...)`` call in one module, with its enclosing function.

    A *call* rather than a mention: an import, a type annotation, a docstring and an
    ``isinstance`` check all name the type without producing one, and none of them
    delegates the authority. A call outside any function — at module level or in a
    class body — counts too, named ``<module>``: the guard is that none exists, so
    a construction no function encloses may not slip past it.
    """
    enclosing: dict[ast.AST, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for inner in ast.walk(node):
                if inner is not node:
                    enclosing.setdefault(inner, node.name)
    found: list[_Construction] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        named = (
            callee.id
            if isinstance(callee, ast.Name)
            else callee.attr
            if isinstance(callee, ast.Attribute)
            else None
        )
        if named == _AUTHORITY:
            found.append(_Construction(module=module, function=enclosing.get(node, "<module>")))
    return found


def _production_modules() -> list[Path]:
    """Every module the scan parses: the whole production tree."""
    return sorted(_SRC.rglob("*.py"))


def _production_constructions() -> list[_Construction]:
    """Every place in ``src/ai_assistant`` that constructs the authority."""
    found: list[_Construction] = []
    for path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found.extend(_constructions(tree, module=str(path.relative_to(_SRC))))
    return found


def test_no_production_module_produces_a_user_confirmation() -> None:
    """A producer is a holder of the one authority that has never been delegable.

    ``memory/policy.py`` honours a ``UserConfirmation`` as the user's own act, so
    whoever may construct one may retire a user's assertion. ADR-0078 §3 made one
    claimed producer, which retired (ADR-0309 §5); ADR-0321 §5:2 made ``remember``'s
    yes path the next, which retired with ADR-0328 §13's interim. Any producer is an
    authority change, made by changing this assertion on purpose.
    """
    found = _production_constructions()

    assert found == [], (
        f"{[(one.module, one.function) for one in found]} constructs a {_AUTHORITY}, "
        f"which no production module produces since ADR-0328 §13's interim retired; a "
        f"producer is an authority change and has to change this test deliberately."
    )


# --------------------------------------------------------------------------- #
# The check's own false-positive paths                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("source", "constructs", "label"),
    [
        (
            "def make(claim: DeferralClaim):\n    return UserConfirmation(deferral_id=claim.x)",
            True,
            "a construction by its bare name",
        ),
        (
            "def make(deferral: DeferredProposal):\n    return t.UserConfirmation(deferral_id=1)",
            True,
            "a construction through a module attribute",
        ),
        (
            "CONFIRMED = UserConfirmation(deferral_id=1)",
            True,
            "a construction no function encloses",
        ),
        (
            "def make(claim: DeferralClaim) -> UserConfirmation:\n    return other()",
            False,
            "an annotation naming the type without producing one",
        ),
        (
            'def make(claim: DeferralClaim):\n    """UserConfirmation is built elsewhere."""',
            False,
            "a docstring mentioning it",
        ),
        (
            "def make(claim: DeferralClaim):\n    return isinstance(x, UserConfirmation)",
            False,
            "an isinstance check",
        ),
    ],
    ids=["bare-name", "attribute", "module-level", "annotation-only", "docstring", "isinstance"],
)
def test_only_a_call_counts_as_producing_the_authority(
    source: str, constructs: bool, label: str
) -> None:
    """Guard the predicate itself: a check that finds nothing passes vacuously."""
    found = _constructions(ast.parse(source), module="probe.py")

    assert bool(found) is constructs, label


def test_the_check_reads_the_production_tree_it_is_meant_to_guard() -> None:
    """Guard the discovery step: a check pointed at nothing proves nothing.

    A scan that finds no producer passes whether or not it looked, so this proves it
    looked where the authority lives: the module that defines the type and the one
    that honours it (ADR-0078 §5) are both among the files the scan parses.
    """
    scanned = {path.relative_to(_SRC).as_posix(): path for path in _production_modules()}

    defined = ast.parse(scanned["core/types.py"].read_text(encoding="utf-8"))
    assert any(
        isinstance(node, ast.ClassDef) and node.name == _AUTHORITY for node in ast.walk(defined)
    )
    honoured = ast.parse(scanned["memory/policy.py"].read_text(encoding="utf-8"))
    assert any(isinstance(node, ast.Name) and node.id == _AUTHORITY for node in ast.walk(honoured))
    assert len(scanned) > 20
