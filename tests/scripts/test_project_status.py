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


def _make_repo(root: Path) -> None:
    """Build a minimal checkout: two packages (one built, one stub), two ADRs."""
    pkg = root / "src" / "ai_assistant"
    (pkg / "core").mkdir(parents=True)
    (pkg / "core" / "__init__.py").write_text("")
    (pkg / "core" / "types.py").write_text("")
    (pkg / "core" / "protocols.py").write_text(
        "from typing import Protocol\n\n\n"
        "class AlphaStore(Protocol):\n    ...\n\n\n"
        "class BetaProvider(Protocol):\n    ...\n\n\n"
        "class _Helper:\n    ...\n"
    )
    (pkg / "memory").mkdir()
    (pkg / "memory" / "__init__.py").write_text("")
    (pkg / "memory" / "store.py").write_text("")
    (pkg / "planning").mkdir()
    (pkg / "planning" / "__init__.py").write_text("")  # stub: only __init__

    adr = root / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "0001-first.md").write_text("# 1. First decision\n\n- Status: Accepted\n")
    (adr / "0003-third.md").write_text("# 3. Third decision\n\n- Status: Proposed\n")
    (adr / "template.md").write_text("# N. Template\n\n- Status: n/a\n")  # not numbered


def _run(root: Path) -> str:
    result = subprocess.run(  # noqa: S603  # fixed interpreter + in-repo script
        [sys.executable, str(_SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_reports_packages_with_built_and_stub_states(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    out = _run(tmp_path)

    assert "memory" in out
    assert "module(s)" in out  # memory is built (has store.py)
    assert "planning" in out
    assert "contract only" in out  # planning is a stub (only __init__)


def test_lists_only_protocol_classes(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    out = _run(tmp_path)

    assert "AlphaStore" in out
    assert "BetaProvider" in out
    assert "_Helper" not in out  # a non-Protocol class is not listed


def test_reports_adrs_with_status_and_excludes_template(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    out = _run(tmp_path)

    assert "0001" in out
    assert "Accepted" in out
    assert "Proposed" in out
    assert "Template" not in out  # template.md is not a numbered ADR


def test_flags_gaps_in_the_adr_numbering(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    out = _run(tmp_path)

    # 0002 is absent between 0001 and 0003 — surfaced as a gap.
    assert "0002" in out
    assert "gap" in out.lower()
