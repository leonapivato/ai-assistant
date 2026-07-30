"""ADR-0078 §3's third composition-root obligation, held structurally.

*The answer path is the only producer of a* ``UserConfirmation``, *and it produces
one only from a deferral it has claimed.*

The first two obligations are instance-wiring and a wiring test covers them
(``tests/app/test_composition.py``). **This one is not**, and ADR-0078 §10 item 3 is
explicit about why: "Nothing in the writer's six checks looks for a claim, so a
helper that assembled a confirmation from a pending deferral's id, key and conflict
ids — all of which reads expose — could retire a ``USER_ASSERTED`` record while every
answer-path test still passed." A behavioural test cannot see a second producer that
nothing happens to call yet; a structural one can.

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
#: What may not exist is a second *production* producer of the authority.
_SRC: Final = Path(ai_assistant.__file__).resolve().parent

#: The value whose construction is the authority. Named rather than discovered,
#: because the obligation is about this one type.
_AUTHORITY: Final = "UserConfirmation"

#: The type whose presence in the enclosing signature proves the producer holds a
#: claim. ``DeferralClaim`` carries the token ``claim`` minted and returned to that
#: caller alone — and the token is on no other read, so holding it *is* holding the
#: claim (ADR-0078 §2). A function taking a ``DeferredProposal`` instead would be
#: reading something every enumeration publishes, which proves nothing.
_CLAIM: Final = "DeferralClaim"


@dataclass(frozen=True)
class _Construction:
    """One place production code builds the authority."""

    module: str
    function: str
    holds_a_claim: bool


def _annotation_names(node: ast.AST | None) -> set[str]:
    """Every bare name mentioned in an annotation, however it is nested.

    ``claim: DeferralClaim``, ``claim: DeferralClaim | None`` and
    ``claim: "DeferralClaim"`` all have to count: the module under test uses
    postponed annotations, so the annotation may be a string, and a defensive
    signature may make it optional. Walking names rather than matching a shape is
    what keeps the check about *what the function is handed*.
    """
    if node is None:
        return set()
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            try:
                names |= _annotation_names(ast.parse(child.value, mode="eval").body)
            except SyntaxError:  # pragma: no cover — not an annotation expression
                continue
    return names


def _takes_a_claim(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether ``function`` is handed a :data:`_CLAIM` by one of its parameters."""
    arguments = function.args
    every = [
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *([arguments.vararg] if arguments.vararg else []),
        *([arguments.kwarg] if arguments.kwarg else []),
    ]
    return any(_CLAIM in _annotation_names(argument.annotation) for argument in every)


def _constructions(tree: ast.Module, module: str) -> list[_Construction]:
    """Every ``UserConfirmation(...)`` call in one module, with its enclosing function.

    A *call* rather than a mention: an import, a type annotation, a docstring and an
    ``isinstance`` check all name the type without producing one, and none of them
    delegates the authority.
    """
    found: list[_Construction] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            callee = inner.func
            named = (
                callee.id
                if isinstance(callee, ast.Name)
                else callee.attr
                if isinstance(callee, ast.Attribute)
                else None
            )
            if named == _AUTHORITY:
                found.append(
                    _Construction(
                        module=module, function=node.name, holds_a_claim=_takes_a_claim(node)
                    )
                )
    return found


def _production_constructions() -> list[_Construction]:
    """Every place in ``src/ai_assistant`` that constructs the authority."""
    found: list[_Construction] = []
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found.extend(_constructions(tree, module=str(path.relative_to(_SRC))))
    return found


def test_a_user_confirmation_is_constructed_in_exactly_one_place() -> None:
    """A second producer is a second thing that can retire a user's assertion.

    That is the one authority in this system that has never been delegable, so
    ADR-0078 §3 makes it structural rather than a wiring rule. Nothing in the
    writer's checks looks for a claim — they verify what the *authority* covers, not
    who issued it — so a helper assembling one from a pending deferral's public fields
    would pass every behavioural test on the answer path.
    """
    found = _production_constructions()

    assert len(found) == 1, (
        f"expected exactly one production producer of {_AUTHORITY}, found "
        f"{[(one.module, one.function) for one in found]}. ADR-0078 §3: 'a second "
        f"producer of confirmations is a second thing that can authorise retiring a "
        f"user's assertion'."
    )


def test_the_one_place_that_constructs_it_holds_a_claim() -> None:
    """And it is handed the claim, not merely the deferral (ADR-0078 §2, §3).

    ``claim`` mints the token, returns it to that caller alone, and puts it on **no
    other read** — ``get``, ``pending``, ``interrupted`` and ``export`` all return a
    ``DeferredProposal``, which does not carry it. So a producer that takes a
    ``DeferralClaim`` cannot have been reached without a claim having been taken,
    while one that took a deferral id and a key would be reading what every
    enumeration publishes.
    """
    [one] = _production_constructions()

    assert one.holds_a_claim, (
        f"{one.module}::{one.function} constructs a {_AUTHORITY} without being handed a "
        f"{_CLAIM}. ADR-0078 §3: it 'produces one only from a deferral it has claimed'."
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
            "a construction from a claim",
        ),
        (
            "def make(deferral: DeferredProposal):\n    return UserConfirmation(deferral_id=1)",
            True,
            "a construction from something that is not a claim",
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
    ids=["from-a-claim", "without-a-claim", "annotation-only", "docstring", "isinstance"],
)
def test_only_a_call_counts_as_producing_the_authority(
    source: str, constructs: bool, label: str
) -> None:
    """Guard the predicate itself: a check that finds nothing passes vacuously."""
    found = _constructions(ast.parse(source), module="probe.py")

    assert bool(found) is constructs, label


@pytest.mark.parametrize(
    ("annotation", "holds"),
    [
        ("DeferralClaim", True),
        ("DeferralClaim | None", True),
        ('"DeferralClaim"', True),
        ("DeferredProposal", False),
        ("str", False),
    ],
    ids=["bare", "optional", "stringified", "a-deferral", "an-id"],
)
def test_a_claim_is_recognised_however_the_annotation_is_spelled(
    annotation: str, holds: bool
) -> None:
    """Postponed annotations make the parameter a string; optionality is legitimate.

    A check that only matched a bare ``ast.Name`` would pass the *positive* case
    above by luck and quietly stop working the day the signature changed shape — which
    is how a structural check becomes decoration.
    """
    node = ast.parse(f"def make(claim: {annotation}): ...").body[0]
    assert isinstance(node, ast.FunctionDef)

    assert _takes_a_claim(node) is holds


def test_the_check_reads_the_production_tree_it_is_meant_to_guard() -> None:
    """Guard the discovery step: a check pointed at nothing proves nothing."""
    assert (_SRC / "orchestration" / "questions.py").is_file()
    assert len(list(_SRC.rglob("*.py"))) > 20
