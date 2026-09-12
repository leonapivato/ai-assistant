"""``GoalStatus.ACHIEVED`` gets no producer, asserted over the shipped tree.

ADR-0249 §16 item 7 asks for this as "a test over the shipped tree, not as a review
convention, so that a later lane cannot supply one without the ADR that decides it".
§4 is the decision: "**``GoalStatus.ACHIEVED`` gets no producer in this decision.** No
clause of this ADR, and no lane implementing it, writes ``ACHIEVED``, and **producing a
reply never by itself establishes that a goal was achieved**" — A10 of #2255 is its only
producer, and it is named there so no later lane supplies one by inference.

**What this costs is stated rather than hidden** (§4): until A10 lands, a goal that was
fully served stays ``ACTIVE``. That is a legible gap and an honest one.

**The scan is over shapes, not over one spelling.** What §4 refuses is the *producer*,
however it is written, so a guard keyed on ``GoalStatus.ACHIEVED`` alone would go green
while ``GoalStatus("achieved")`` or ``status="achieved"`` did the same thing one
character class away. :func:`producers_in` is the shape reader, and it is exercised
against each of those spellings below so that the tree scan's coverage is demonstrated
rather than claimed.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from ai_assistant.core.types import GoalStatus

_SRC: Final = Path(__file__).resolve().parents[2] / "src" / "ai_assistant"

#: The one file that may name the member: its own declaration.
_DECLARATION: Final = "core/types.py"

#: The member's own value, read off the enum rather than written out, so a rename of
#: the value — which ADR-0249 §4's vocabulary forbids, but which this scan must not
#: silently stop covering — moves this guard with it.
_VALUE: Final = GoalStatus.ACHIEVED.value


def producers_in(source: str) -> list[str]:
    """Every way ``source`` writes the achieved status, as readable descriptions.

    Three shapes, because three are reachable and a guard that read one would let the
    other two through:

    * ``GoalStatus.ACHIEVED`` — the member access;
    * ``GoalStatus("achieved")`` — the enum's own constructor over the value, which is
      the spelling a scan for the attribute misses entirely;
    * ``status="achieved"`` or ``"status": "achieved"`` — the bare value reaching a
      status field, which pydantic coerces into the member at validation.

    Read as an AST rather than as text, so a mention inside a docstring or a comment —
    of which this corpus has many, ADR-0249 §4's own account among them — is not a
    producer and is not reported as one.

    Args:
        source: One module's text.

    Returns:
        One description per producer found, empty where there is none.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "ACHIEVED"
            and isinstance(node.value, ast.Name)
            and node.value.id == "GoalStatus"
        ):
            found.append(f"line {node.lineno}: GoalStatus.ACHIEVED")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "GoalStatus"
            and any(_is_achieved(argument) for argument in node.args)
        ):
            found.append(f'line {node.lineno}: GoalStatus("{_VALUE}")')
        elif isinstance(node, ast.keyword) and node.arg == "status" and _is_achieved(node.value):
            found.append(f'line {node.lineno}: status="{_VALUE}"')
        elif isinstance(node, ast.Dict):
            found.extend(
                f'line {node.lineno}: {{"status": "{_VALUE}"}}'
                for key, value in zip(node.keys, node.values, strict=True)
                if isinstance(key, ast.Constant) and key.value == "status" and _is_achieved(value)
            )
    return found


def _is_achieved(node: ast.expr) -> bool:
    """Whether ``node`` is the literal value the achieved member carries."""
    return isinstance(node, ast.Constant) and node.value == _VALUE


@pytest.mark.parametrize(
    "spelling",
    [
        pytest.param("goal = Goal(status=GoalStatus.ACHIEVED)", id="member-access"),
        pytest.param('goal = Goal(status=GoalStatus("achieved"))', id="enum-constructor"),
        pytest.param('goal = Goal(status="achieved")', id="bare-value-keyword"),
        pytest.param('goal = Goal.model_validate({"status": "achieved"})', id="bare-value-mapping"),
        pytest.param("stored = goal.model_copy(update={'status': 'achieved'})", id="model-copy"),
    ],
)
def test_the_scan_detects_every_spelling_a_producer_could_take(spelling: str) -> None:
    """The guard's own coverage, demonstrated rather than claimed.

    Each of these writes the achieved status, and a scan that missed any of them would
    stay green while ADR-0249 §4's refusal was broken — which is the failure this
    parametrisation exists to make impossible.
    """
    assert producers_in(spelling), f"the scan must see {spelling!r}"


@pytest.mark.parametrize(
    "innocent",
    [
        pytest.param('"""GoalStatus.ACHIEVED gets no producer (ADR-0249 §4)."""', id="docstring"),
        pytest.param("# GoalStatus.ACHIEVED is A10's to write\nx = 1", id="comment"),
        pytest.param("ACHIEVED = 'achieved'", id="the-declaration-itself"),
        pytest.param("status = other.status", id="a-status-read"),
    ],
)
def test_the_scan_reports_no_producer_where_there_is_none(innocent: str) -> None:
    """And it does not fire on prose, which this corpus is full of.

    A text scan would report ADR-0249 §4's own account of the refusal as a breach of
    it; reading the AST is what separates a mention from a write.
    """
    assert producers_in(innocent) == []


def test_no_source_file_but_the_declaration_writes_achieved() -> None:
    """``GoalStatus.ACHIEVED`` is produced nowhere under ``src/``."""
    offenders = {
        path.relative_to(_SRC).as_posix(): producers_in(path.read_text(encoding="utf-8"))
        for path in sorted(_SRC.rglob("*.py"))
        if path.relative_to(_SRC).as_posix() != _DECLARATION
    }

    assert {name: found for name, found in offenders.items() if found} == {}, (
        "ADR-0249 §4 gives ACHIEVED no producer, and A10 of #2255 is its only one: a "
        "composed reply establishes nothing about the requested outcome, so a status "
        "claiming otherwise would assert a comparison nothing performed"
    )


def test_the_declaration_writes_it_only_as_an_enum_member() -> None:
    """And the one file that names it declares it rather than produces it.

    A declaration is an assignment inside the ``GoalStatus`` class body; anything else
    in that module — a default, a comparison folded into a helper — would be a producer
    hiding in the one file the tree scan exempts.
    """
    source = (_SRC / _DECLARATION).read_text(encoding="utf-8")
    tree = ast.parse(source)
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

    assert producers_in(source) == [], "the module declares the member and produces it nowhere"
