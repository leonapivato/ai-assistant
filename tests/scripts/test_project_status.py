"""Tests for the derived project-status view (scripts/project_status.py).

Driven as a subprocess against a constructed fixture checkout via ``--root``, so
the assertions pin the *derivation* logic and never depend on the live repo's
evolving state (which packages are built, which ADRs exist).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "scripts" / "project_status.py"


_DEFAULT_ADRS = (
    ("0001-first.md", "# 1. First decision\n\n- Status: Accepted\n"),
    ("0003-third.md", "# 3. Third decision\n\n- Status: Proposed\n"),
)

_DEFAULT_PROTOCOLS = (
    "from typing import Protocol\n\n\n"
    "class AlphaStore(Protocol):\n    ...\n\n\n"
    "class BetaProvider(Protocol):\n    ...\n\n\n"
    "class _Helper:\n    ...\n"
)


def _make_repo(
    root: Path,
    adrs: tuple[tuple[str, str], ...] = _DEFAULT_ADRS,
    protocols_src: str = _DEFAULT_PROTOCOLS,
) -> None:
    """Build a minimal checkout: two packages (one built, one stub) and the given ADRs."""
    pkg = root / "src" / "ai_assistant"
    (pkg / "core").mkdir(parents=True)
    (pkg / "core" / "__init__.py").write_text("")
    (pkg / "core" / "types.py").write_text("")
    (pkg / "core" / "protocols.py").write_text(protocols_src)
    (pkg / "memory").mkdir()
    (pkg / "memory" / "__init__.py").write_text("")
    (pkg / "memory" / "store.py").write_text("")
    (pkg / "planning").mkdir()
    (pkg / "planning" / "__init__.py").write_text("")  # stub: only __init__

    adr_dir = root / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    for name, body in adrs:
        (adr_dir / name).write_text(body)
    (adr_dir / "template.md").write_text("# N. Template\n\n- Status: n/a\n")  # not numbered


def _run(root: Path) -> str:
    result = subprocess.run(  # noqa: S603  # fixed interpreter + in-repo script
        [sys.executable, str(_SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _line_with(out: str, token: str) -> str:
    """Return the single output line containing ``token`` (assert there is one)."""
    matches = [line for line in out.splitlines() if token in line]
    assert len(matches) == 1, f"expected exactly one line with {token!r}, got {len(matches)}"
    return matches[0]


def test_reports_packages_with_module_counts(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    out = _run(tmp_path)

    # Assertions are tied to the specific package's row, not "anywhere in output".
    assert "module(s)" in _line_with(out, "memory")  # built: has store.py
    assert "contract only" in _line_with(out, "planning")  # stub: only __init__


def test_lists_only_protocol_classes(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    out = _run(tmp_path)

    assert "AlphaStore" in out
    assert "BetaProvider" in out
    assert "_Helper" not in out  # a non-Protocol class is not listed


def test_reports_adrs_with_status_and_excludes_template(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    out = _run(tmp_path)

    # number, status, and title must appear on the *same* row, not just somewhere.
    first = _line_with(out, "First decision")
    assert "0001" in first
    assert "Accepted" in first
    third = _line_with(out, "Third decision")
    assert "0003" in third
    assert "Proposed" in third
    assert "Template" not in out  # template.md is not a numbered ADR


def test_flags_gaps_in_the_adr_numbering(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    out = _run(tmp_path)

    # 0002 is absent between 0001 and 0003 — surfaced as a gap.
    assert "0002" in out
    assert "gap" in out.lower()


def test_flags_a_leading_gap(tmp_path: Path) -> None:
    # Only 0003 present: gap detection starts from 1, so 0001 and 0002 are flagged.
    _make_repo(tmp_path, adrs=(("0003-third.md", "# 3. Third\n\n- Status: Accepted\n"),))
    out = _run(tmp_path)

    assert "0001" in out
    assert "0002" in out
    assert "gap" in out.lower()


def test_flags_duplicate_adr_numbers(tmp_path: Path) -> None:
    # Two files claiming 0002 — a shared-counter collision — must be surfaced.
    _make_repo(
        tmp_path,
        adrs=(
            ("0002-a.md", "# 2. Alpha\n\n- Status: Accepted\n"),
            ("0002-b.md", "# 2. Beta\n\n- Status: Proposed\n"),
        ),
    )
    out = _run(tmp_path)

    assert "duplicate" in out.lower()
    assert "0002" in out


def test_flags_filename_heading_number_mismatch(tmp_path: Path) -> None:
    # Filename says 0002 but the heading says 3 — a numbering-integrity error.
    _make_repo(tmp_path, adrs=(("0002-example.md", "# 3. Example\n\n- Status: Accepted\n"),))
    out = _run(tmp_path)

    assert "mismatch" in out.lower()
    assert "0002" in out


def test_counts_modules_in_nested_subpackages(tmp_path: Path) -> None:
    # A package whose only implementation lives in a nested subpackage is still
    # counted (not mislabeled contract-only).
    _make_repo(tmp_path)
    nested = tmp_path / "src" / "ai_assistant" / "planning" / "feature"
    nested.mkdir()
    (nested / "__init__.py").write_text("")
    (nested / "handler.py").write_text("")

    out = _run(tmp_path)

    assert "module(s)" in _line_with(out, "planning")


def test_protocol_discovery_resolves_aliases_and_rejects_lookalikes(tmp_path: Path) -> None:
    _make_repo(
        tmp_path,
        protocols_src=(
            "import typing\n"
            "from typing import Protocol as P\n\n\n"
            "class Aliased(P):\n    ...\n\n\n"
            "class Qualified(typing.Protocol):\n    ...\n\n\n"
            "class Lookalike(vendor.Protocol):\n    ...\n"  # unrelated .Protocol
        ),
    )
    out = _run(tmp_path)

    assert "Aliased" in out  # `Protocol as P` alias resolved
    assert "Qualified" in out  # `typing.Protocol` qualified base resolved
    assert "Lookalike" not in out  # unrelated `vendor.Protocol` not misreported
