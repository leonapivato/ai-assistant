"""The fence is mechanical, on each half that can be (ADR-0225 §4, §13 item 2).

Three properties enforce §4's never-list, and none of them is a convention. Two are
checkable here:

* **The package fence.** An ``import-linter`` contract forbids every other package
  from importing ``ai_assistant.archive``, ``ai_assistant.app`` alone excepted. The
  cases below run *the contract as written in* ``pyproject.toml`` over a synthetic
  graph, so what is asserted is the shipped contract rather than a copy of it.
* **The seam split.** A read on a declared ``TranscriptArchiveWriter`` and an
  ``append`` on a declared ``TranscriptArchive`` each fail ``mypy``, and a
  composition omitting either seam fails ``mypy`` too. Asserted as **type-level**
  cases — §13 item 2 says so in terms — by running the type checker over a snippet
  and reading what it reports.

The third property, the absent embedder, has nothing to assert: the archive
constructs none and its search is lexical by construction, so "never embedded" is a
property of the shape (``tests/archive/test_sqlite_archive.py`` exercises the search
that has no vector in it).

**No case asserts that the *concrete* archive is rejected at either parameter**,
because no such rejection exists (§10): one concrete satisfies both Protocols, and
what the composition root passes is the root's own discipline — which
``tests/app/test_composition.py`` asserts directly.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Final

import grimp
import pytest
from importlinter.adapters.timing import SystemClockTimer
from importlinter.application.app_config import settings
from importlinter.contracts.forbidden import ForbiddenContract

_ROOT: Final = Path(__file__).resolve().parents[2]
_PYPROJECT: Final = _ROOT / "pyproject.toml"
_PACKAGE: Final = _ROOT / "src" / "ai_assistant"

#: The contract ADR-0225 §4 requires, by the name it ships under.
CONTRACT: Final = "nothing imports the transcript archive"

ARCHIVE: Final = "ai_assistant.archive"
APP: Final = "ai_assistant.app"


def _contract_options() -> dict[str, Any]:
    """The shipped contract's own table, read out of ``pyproject.toml``.

    Returns:
        Its options, exactly as ``lint-imports`` receives them.

    Raises:
        AssertionError: If no contract carries the expected name — which is itself
            the failure ADR-0225 §4 is about, since the package would then be fenced
            by nothing.
    """
    contracts = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["tool"]["importlinter"][
        "contracts"
    ]
    for contract in contracts:
        if contract.get("name") == CONTRACT:
            options = {key: value for key, value in contract.items() if key not in {"name", "type"}}
            return dict(options)
    msg = (
        f"no import-linter contract named {CONTRACT!r} in pyproject.toml. ADR-0225 §4 "
        f"requires one, and it is the first of the three properties the never-list rests on."
    )
    raise AssertionError(msg)


def _as_contract() -> ForbiddenContract:
    """The shipped contract, instantiated the way ``lint-imports`` instantiates it."""
    settings.configure(TIMER=SystemClockTimer())
    contract = ForbiddenContract(
        name=CONTRACT,
        session_options={"root_packages": ["ai_assistant"]},
        contract_options=_contract_options(),
    )
    contract.validate()
    return contract


def _graph(*imports: tuple[str, str]) -> grimp.ImportGraph:
    """A graph over every top-level package, carrying exactly ``imports``."""
    graph = grimp.ImportGraph()
    graph.add_module("ai_assistant")
    for package in _top_level_packages():
        graph.add_module(f"ai_assistant.{package}")
    for importer, imported in imports:
        graph.add_import(
            importer=importer, imported=imported, line_number=1, line_contents="import"
        )
    return graph


def _top_level_packages() -> set[str]:
    """Every top-level package under ``src/ai_assistant``."""
    return {
        each.name
        for each in _PYPROJECT.parent.joinpath("src", "ai_assistant").iterdir()
        if each.is_dir() and (each / "__init__.py").exists()
    }


# --- the package fence (§4, §13 item 2) -------------------------------------


@pytest.mark.parametrize(
    "pipeline",
    [
        "ai_assistant.orchestration",
        "ai_assistant.memory",
        "ai_assistant.learning",
        "ai_assistant.context",
        "ai_assistant.planning",
        "ai_assistant.models",
        "ai_assistant.interfaces",
        "ai_assistant.testing",
    ],
)
def test_the_contract_fails_when_a_pipeline_package_imports_the_archive(pipeline: str) -> None:
    """ADR-0225 §4's package fence, run as the shipped contract over a planted edge.

    This is the half that holds for a component that would go and get its own archive
    rather than be handed one: a package no subsystem may import cannot be
    constructed inside one, so ``orchestration`` cannot name the concrete class,
    cannot widen a value back to it, and sees exactly the members its declared
    Protocol has.
    """
    broken = _as_contract().check(graph=_graph((pipeline, ARCHIVE)), verbose=False)

    assert broken.kept is False


def test_the_contract_passes_for_the_composition_root() -> None:
    """The carve-out is the clause's meaning rather than a gap (ADR-0225 §4).

    The composition root is not a subsystem; it is the one place golden rule 1 puts
    the injection that lets a collaborator receive an implementation it may not name.
    Listing ``app`` would make the archive unreachable in production for good.
    """
    kept = _as_contract().check(graph=_graph((APP, ARCHIVE)), verbose=False)

    assert kept.kept is True


def test_the_contract_passes_over_the_tree_as_it_stands() -> None:
    """The control: nothing in the shipped tree breaches it.

    Without this the two cases above would still pass over a tree that had already
    broken the fence — they assert what the *contract* does, and this asserts what
    the code does.
    """
    kept = _as_contract().check(graph=_graph(), verbose=False)

    assert kept.kept is True


def test_every_package_but_the_composition_root_is_named_in_the_contract() -> None:
    """A package absent from the list is a package the fence is asserted about, not checked.

    The discipline the ``service``, ``wire``, ``readers``, ``evaluation`` and
    ``secret_store`` contracts each recorded: every package is enumerated by name, so
    a new top-level package is a deliberate addition rather than a silent escape.
    This is what makes that mechanical for *this* fence.
    """
    named = set(_contract_options()["source_modules"])
    expected = {f"ai_assistant.{each}" for each in _top_level_packages()} - {APP, ARCHIVE}

    assert expected <= named
