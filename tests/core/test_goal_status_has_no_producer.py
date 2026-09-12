"""``GoalStatus.ACHIEVED`` gets no producer, asserted over the shipped tree.

ADR-0249 §16 item 7 asks for this as "a test over the shipped tree, not as a review
convention, so that a later lane cannot supply one without the ADR that decides it".
§4 is the decision: "**``GoalStatus.ACHIEVED`` gets no producer in this decision.** No
clause of this ADR, and no lane implementing it, writes ``ACHIEVED``, and **producing a
reply never by itself establishes that a goal was achieved**" — A10 of #2255 is its only
producer, and it is named there so no later lane supplies one by inference.

**What this costs is stated rather than hidden** (§4): until A10 lands, a goal that was
fully served stays ``ACTIVE``. That is a legible gap and an honest one.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

_SRC: Final = Path(__file__).resolve().parents[2] / "src" / "ai_assistant"

#: The one file that may name the member: its own declaration.
_DECLARATION: Final = "core/types.py"


def test_no_source_file_but_the_declaration_writes_achieved() -> None:
    """``GoalStatus.ACHIEVED`` appears nowhere under ``src/`` but where it is declared.

    Read as **source text** rather than as an attribute access, so a lane spelling it
    ``GoalStatus("achieved")`` or assigning the bare string to ``Goal.status`` is caught
    by the same assertion: what §4 refuses is the *producer*, however it is spelled.
    """
    offenders = sorted(
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if path.relative_to(_SRC).as_posix() != _DECLARATION
        and ("GoalStatus.ACHIEVED" in path.read_text(encoding="utf-8"))
    )

    assert offenders == [], (
        "ADR-0249 §4 gives ACHIEVED no producer, and A10 of #2255 is its only one: a "
        "composed reply establishes nothing about the requested outcome, so a status "
        "claiming otherwise would assert a comparison nothing performed"
    )


def test_the_declaration_writes_it_only_as_an_enum_member() -> None:
    """And the one file that names it declares it rather than assigns it.

    A declaration is an assignment inside the ``GoalStatus`` class body; anything else
    in that module — a default, a comparison folded into a helper — would be a producer
    hiding in the one file this scan exempts.
    """
    tree = ast.parse((_SRC / _DECLARATION).read_text(encoding="utf-8"))
    classes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "GoalStatus"
    ]
    assert len(classes) == 1

    inside = {
        target.id
        for statement in classes[0].body
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Name)
    }
    assert "ACHIEVED" in inside

    elsewhere = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "ACHIEVED"
        and isinstance(node.value, ast.Name)
        and node.value.id == "GoalStatus"
    ]
    assert elsewhere == [], "the module declares the member and reads it nowhere"
