#!/usr/bin/env python3
"""Print a derived snapshot of project status — packages, Protocols, ADRs.

Onboarding to "what exists" otherwise means stitching together the source tree,
``core/protocols.py``, and every ADR header (TODO #4). This derives that view
fresh from the repository on each run, so it cannot go stale. The *human*-declared
state — who owns which lane and which ADR numbers are in flight — deliberately
stays in ``WORKING.md`` (its rightful home); this points there rather than
duplicating it.

Run via ``just status`` (or ``python3 scripts/project_status.py``). Pass
``--root`` to point at a different checkout (used by the tests).
"""

from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path

_STATUS_RE = re.compile(r"^\s*-\s*Status:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_HEADING_RE = re.compile(r"^#\s*(\d+)\.\s*(.+?)\s*$", re.MULTILINE)
_ADR_FILE_RE = re.compile(r"^(\d+)-.*\.md$")

# Modules that export the ``Protocol`` marker; a base is only a Protocol if it
# resolves to one of these (not any class merely spelled ``Protocol``).
_TYPING_MODULES = frozenset({"typing", "typing_extensions"})


@dataclass(frozen=True)
class Package:
    """A package under ``src/ai_assistant`` and how many modules it has.

    ``modules`` is the count of ``.py`` files other than ``__init__.py`` — a
    rough progress proxy (a package with no modules is contract-only), not a
    claim that any module is complete.
    """

    name: str
    modules: int


@dataclass(frozen=True)
class Adr:
    """A decision record: its number, status, and title.

    ``number`` comes from the filename and ``heading_number`` from the ``# N.``
    heading; they should agree, and a mismatch is a numbering-integrity error the
    status view surfaces.
    """

    number: int
    status: str
    title: str
    heading_number: int | None


def discover_packages(pkg_root: Path) -> list[Package]:
    """Return the packages under ``pkg_root``, each with its module count.

    Args:
        pkg_root: The ``ai_assistant`` package directory.

    Returns:
        One :class:`Package` per child directory that has an ``__init__.py``,
        sorted by name.
    """
    packages: list[Package] = []
    for child in sorted(pkg_root.iterdir()):
        if not child.is_dir() or not (child / "__init__.py").exists():
            continue
        # Recurse, so implementation in a nested subpackage still counts.
        modules = sum(1 for p in child.rglob("*.py") if p.name != "__init__.py")
        packages.append(Package(name=child.name, modules=modules))
    return packages


@dataclass(frozen=True)
class _ProtocolBindings:
    """The local names that resolve to ``typing.Protocol`` in one module.

    Attributes:
        direct: Names bound to ``Protocol`` itself (``from typing import
            Protocol`` → ``Protocol``; ``... as P`` → ``P``).
        modules: Names bound to a typing module (``import typing`` → ``typing``;
            ``import typing as t`` → ``t``), for ``<module>.Protocol`` bases.
    """

    direct: frozenset[str]
    modules: frozenset[str]


def _protocol_bindings(tree: ast.Module) -> _ProtocolBindings:
    """Resolve which local names refer to ``Protocol`` from the module's imports."""
    direct: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in _TYPING_MODULES:
            direct.update(a.asname or a.name for a in node.names if a.name == "Protocol")
        elif isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name in _TYPING_MODULES)
    return _ProtocolBindings(direct=frozenset(direct), modules=frozenset(modules))


def _base_is_protocol(base: ast.expr, bound: _ProtocolBindings) -> bool:
    """Whether a class base resolves to ``typing.Protocol`` under ``bound``.

    Matches an alias (``class X(P)``) and a qualified base (``typing.Protocol``),
    and rejects an unrelated class merely spelled ``Protocol`` (e.g.
    ``vendor.Protocol``).
    """
    if isinstance(base, ast.Name):
        return base.id in bound.direct
    return (
        isinstance(base, ast.Attribute)
        and base.attr == "Protocol"
        and isinstance(base.value, ast.Name)
        and base.value.id in bound.modules
    )


def protocol_names(protocols_path: Path) -> list[str]:
    """Return the names of the ``Protocol`` classes defined in ``protocols_path``.

    Import bindings are resolved first, so an aliased import is found and an
    unrelated ``*.Protocol`` base is not misreported.

    Args:
        protocols_path: Path to ``core/protocols.py``.

    Returns:
        Protocol class names, in source order.
    """
    tree = ast.parse(protocols_path.read_text(encoding="utf-8"))
    bound = _protocol_bindings(tree)
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and any(_base_is_protocol(b, bound) for b in node.bases)
    ]


def adr_entries(adr_dir: Path) -> list[Adr]:
    """Return the ADRs in ``adr_dir`` (excluding the template), sorted by number.

    Args:
        adr_dir: The ``docs/adr`` directory.

    Returns:
        One :class:`Adr` per numbered record.
    """
    entries: list[Adr] = []
    for path in adr_dir.glob("*.md"):
        match = _ADR_FILE_RE.match(path.name)
        if match is None:
            continue  # template.md and other non-numbered files
        text = path.read_text(encoding="utf-8")
        status = _STATUS_RE.search(text)
        heading = _HEADING_RE.search(text)
        entries.append(
            Adr(
                number=int(match.group(1)),
                status=status.group(1) if status else "?",
                title=heading.group(2) if heading else path.stem,
                heading_number=int(heading.group(1)) if heading else None,
            )
        )
    return sorted(entries, key=lambda a: a.number)


def missing_numbers(numbers: list[int], *, start: int | None = None) -> list[int]:
    """Return the numbers absent between ``start`` and the maximum.

    Args:
        numbers: The numbers present.
        start: Lower bound to check from; defaults to ``min(numbers)``. Pass a
            fixed start (e.g. ``1`` for ADRs) to also catch a *leading* gap.

    Returns:
        The missing numbers, ascending.
    """
    if not numbers:
        return []
    low = min(numbers) if start is None else start
    present = set(numbers)
    return [n for n in range(low, max(numbers) + 1) if n not in present]


def duplicate_numbers(numbers: list[int]) -> list[int]:
    """Return numbers that appear more than once (a shared-counter collision)."""
    return sorted({n for n in numbers if numbers.count(n) > 1})


def render(root: Path) -> str:
    """Build the full status report for the checkout at ``root``."""
    packages = discover_packages(root / "src" / "ai_assistant")
    protocols = protocol_names(root / "src" / "ai_assistant" / "core" / "protocols.py")
    adrs = adr_entries(root / "docs" / "adr")
    numbers = [a.number for a in adrs]
    gaps = missing_numbers(numbers, start=1)  # from 1, so a missing 0001 shows too
    duplicates = duplicate_numbers(numbers)
    mismatched = [a for a in adrs if a.heading_number is not None and a.heading_number != a.number]

    lines = [
        "ai-assistant — project status",
        "(generated by `just status`; derived from the repo, never hand-edited)",
        "",
        "Packages (src/ai_assistant/) — module count (a rough progress proxy)",
    ]
    width = max((len(p.name) for p in packages), default=0)
    for pkg in packages:
        detail = f"{pkg.modules} module(s)" if pkg.modules else "contract only (no modules yet)"
        lines.append(f"  {pkg.name.ljust(width)}  {detail}")

    lines += ["", "Protocols (core/protocols.py)"]
    lines += [f"  {name}" for name in protocols] or ["  (none)"]

    lines += ["", "ADRs (docs/adr/)"]
    for adr in adrs:
        lines.append(f"  {adr.number:04d}  {adr.status.ljust(8)}  {adr.title}")
    if gaps:
        pretty = ", ".join(f"{n:04d}" for n in gaps)
        lines.append(
            f"  ! gap(s): {pretty} — no ADR here for this number "
            "(in flight on a branch, or retired); see WORKING.md"
        )
    if duplicates:
        pretty = ", ".join(f"{n:04d}" for n in duplicates)
        lines.append(f"  ! duplicate number(s): {pretty} — a shared-counter collision to resolve")
    if mismatched:
        pretty = ", ".join(f"{a.number:04d} (heading says {a.heading_number})" for a in mismatched)
        lines.append(f"  ! number mismatch: {pretty} — filename and heading disagree")

    lines += [
        "",
        "Ownership & work in flight",
        "  Lane owners and in-flight ADR numbers are human-maintained in WORKING.md.",
    ]
    return "\n".join(lines)


def main() -> None:
    """Parse ``--root`` and print the status report."""
    parser = argparse.ArgumentParser(description="Print a derived project-status snapshot.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to inspect (defaults to this checkout).",
    )
    args = parser.parse_args()
    print(render(args.root))


if __name__ == "__main__":
    main()
