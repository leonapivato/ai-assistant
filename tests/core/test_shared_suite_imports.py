"""A narrowed run imports the same shared suites the gate does (issue #3337).

The test corpus has no packages: under pytest's ``prepend`` import mode each test
module is imported by its basename, with its *own* directory put on ``sys.path``
and no other test directory's. So a bare ``from chat_surface_contract import ...``
in ``tests/wire/`` resolves in a whole-suite run only because
``tests/orchestration/`` was collected first, and not at all when ``tests/wire/`` is
run on its own. The one conftest pins the directories other directories import
from, and these tests hold what those pins rest on:

- the pins, read off the conftest's own ``sys.path.insert`` calls, include both
  directories other directories import from;
- every bare import of a test module resolves from the importer's own directory,
  from ``tests/`` itself, or from a pinned directory;
- no two modules under ``tests/`` share a basename, so a pin cannot shadow one
  test module with another;
- no module in a pinned directory is named like a module importable without the
  pin, so a pin cannot shadow an installed or standard-library one.

The last test is the ground truth the import check stands in for: the directory whose
narrowed run failed, collected in a pytest of its own.
"""

from __future__ import annotations

import ast
import importlib.machinery
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest

import conftest

_TESTS = Path(conftest.__file__).resolve().parent
_ROOT = _TESTS.parent


def _is_sys_path_insert(node: ast.stmt) -> bool:
    """Whether a statement is a bare ``sys.path.insert(...)`` call."""
    match node:
        case ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    attr="insert", value=ast.Attribute(attr="path", value=ast.Name(id="sys"))
                )
            )
        ):
            return True
    return False


def _pinned() -> frozenset[Path]:
    """The directories the conftest pins: its module-level ``sys.path.insert`` calls.

    Each call names its directory as the last string joined onto the conftest's own
    directory, ``Path(__file__).resolve().parent / "<name>"``.
    """
    tree = ast.parse(Path(conftest.__file__).read_text(encoding="utf-8"))
    pinned: set[Path] = set()
    for statement in tree.body:
        if not _is_sys_path_insert(statement):
            continue
        names = [
            node.right.value
            for node in ast.walk(statement)
            if isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant)
            and isinstance(node.right.value, str)
        ]
        assert names, ast.unparse(statement)
        pinned.add(_TESTS / names[-1])
    return frozenset(pinned)


_PINNED = _pinned()


@cache
def _modules() -> dict[str, tuple[Path, ...]]:
    """Every module under ``tests/``, by basename, with the files that carry it."""
    found: dict[str, list[Path]] = {}
    for path in sorted(_TESTS.rglob("*.py")):
        found.setdefault(path.stem, []).append(path)
    return {name: tuple(paths) for name, paths in found.items()}


def _imported_names(path: Path) -> list[tuple[int, str]]:
    """The top-level names a module imports absolutely, wherever the import sits."""
    names: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append((node.lineno, node.module.partition(".")[0]))
        elif isinstance(node, ast.Import):
            names.extend((node.lineno, alias.name.partition(".")[0]) for alias in node.names)
    return names


def test_every_bare_import_of_a_test_module_resolves_in_a_narrowed_run() -> None:
    """An importer run alone finds the module beside it, in ``tests/``, or pinned."""
    modules = _modules()
    unresolved: list[str] = []
    for path in sorted(_TESTS.rglob("*.py")):
        reachable = {path.parent, _TESTS, *_PINNED}
        for line, name in _imported_names(path):
            carriers = modules.get(name)
            if carriers is not None and not any(c.parent in reachable for c in carriers):
                where = ", ".join(str(c.parent.relative_to(_ROOT)) for c in carriers)
                unresolved.append(f"{path.relative_to(_ROOT)}:{line}: {name} (in {where})")

    assert not unresolved, (
        "a bare import of a test module that a run of the importer's directory alone "
        "cannot resolve; move the module under a pinned directory, or pin its "
        "directory in `tests/conftest.py`:\n" + "\n".join(unresolved)
    )


def test_the_pins_are_the_shared_suite_directories() -> None:
    """The pins read off the conftest are on ``sys.path``, the two shared ones among them.

    The other tests here are only as good as this reading, so a reading that came
    back empty, or lost a directory other directories import from, fails here.
    """
    shared = {_TESTS / "core", _TESTS / "orchestration"}
    assert shared <= _PINNED
    assert all(directory.is_dir() for directory in _PINNED)
    assert all(str(directory) in sys.path for directory in _PINNED)


def test_no_two_test_modules_share_a_basename() -> None:
    """A pinned directory cannot shadow one test module with another."""
    shared = {
        name: [str(p.relative_to(_ROOT)) for p in paths]
        for name, paths in _modules().items()
        if len(paths) > 1 and name != "__init__"
    }

    assert not shared, shared


def test_no_pinned_module_shadows_an_importable_one() -> None:
    """A pin goes first on ``sys.path``; nothing it carries may hide a real module."""
    unpinned = [
        entry for entry in sys.path if not Path(entry or ".").resolve().is_relative_to(_TESTS)
    ]
    shadowing = sorted(
        str(path.relative_to(_ROOT))
        for directory in _PINNED
        for path in directory.glob("*.py")
        if path.stem in sys.builtin_module_names
        or importlib.machinery.PathFinder.find_spec(path.stem, unpinned) is not None
    )

    assert not shadowing, shadowing


@pytest.mark.integration
def test_the_wire_directory_collects_on_its_own() -> None:
    """``tests/wire/`` run alone collects, where it once failed to import its suite."""
    collected = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-p",
            "no:cacheprovider",
            "-q",
            "tests/wire",
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": str(_ROOT)},
    )

    assert collected.returncode == 0, collected.stdout + collected.stderr
