"""Tests for ``just adr-rules NNNN`` (scripts/adr_rules.py, ADR-0277 §4).

Driven as a subprocess over a constructed ``--root``, so the pinned output is
exactly what the recipe prints. The whole view is asserted rather than sampled:
§4's second sentence — "It prints nothing else of the ADR's body" — is a claim
about everything that is *not* on the page, and only a whole-output comparison
can hold it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "adr_rules.py"

_MARKED = """\
# 300. A marked decision

- Status: Partially superseded by ADR-0301 (§1's second clause, in its
  wording alone)
- Date: 2026-09-26

## Context

Argument nobody should see in the view.

> **Normative.** A clause in Context.

## Decision

Prose before the first section.

### 1. One

> **Normative.** One-one,
> over two lines.

An argument between the clauses.

> **Normative — labelled.** One-two.

### Why

More argument.

> **Normative.** One-three, under an unnumbered heading.

```text
> **Normative.** Fenced: display.
```

### 2. Two

> **Normative.** Two-one.

## Consequences

Nothing marked here.
"""

_EXPECTED = """\
# 300. A marked decision
- Status: Partially superseded by ADR-0301 (§1's second clause, in its wording alone)

## Context

ADR-0300 §Context:1
> **Normative.** A clause in Context.

### 1. One

ADR-0300 §1:1
> **Normative.** One-one,
> over two lines.

ADR-0300 §1:2
> **Normative — labelled.** One-two.

ADR-0300 §1:3
> **Normative.** One-three, under an unnumbered heading.

### 2. Two

ADR-0300 §2:1
> **Normative.** Two-one.
"""

_UNMARKED = """\
# 12. An old decision

- Status: Accepted
- Date: 2026-07-01

## Decision

> **A bold-led quote.** Not a mark.

We will do the thing.
"""


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # fixed interpreter + in-repo script
        [sys.executable, str(_SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _repo(root: Path) -> Path:
    adr = root / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "0300-marked.md").write_text(_MARKED, encoding="utf-8")
    (adr / "0012-unmarked.md").write_text(_UNMARKED, encoding="utf-8")
    return root


def test_the_view_is_title_status_and_every_clause_under_its_identifier(tmp_path: Path) -> None:
    """§4's first clause, whole: nothing of the argument, the fence or Consequences."""
    result = _run(_repo(tmp_path), "300")

    assert result.returncode == 0, result.stderr
    assert result.stdout == _EXPECTED


def test_the_status_line_is_shown_whole_and_nothing_is_said_about_force(tmp_path: Path) -> None:
    """§4's third clause: the wrapped Status is folded, not cut, and no clause is annotated."""
    out = _run(_repo(tmp_path), "300").stdout

    assert "in its wording alone" in out.splitlines()[1]
    for word in ("superseded", "in force", "replaced", "narrowed"):
        assert word not in "\n".join(out.splitlines()[2:]).lower()


def test_an_unmarked_adr_says_it_binds_as_prose_and_prints_no_clause(tmp_path: Path) -> None:
    """§4's second clause."""
    result = _run(_repo(tmp_path), "12")

    assert result.returncode == 0
    assert result.stdout == (
        "# 12. An old decision\n- Status: Accepted\n\n"
        "ADR-0012 is unmarked: it carries no marked clause, so it binds as prose, "
        "read whole (ADR-0089 §4).\n"
    )


@pytest.mark.parametrize("spelling", ["300", "0300", "ADR-0300", "adr-300"])
def test_the_adr_may_be_named_in_any_usual_spelling(tmp_path: Path, spelling: str) -> None:
    assert _run(_repo(tmp_path), spelling).stdout == _EXPECTED


@pytest.mark.parametrize("argument", ["999", "ADR-X", "12345"])
def test_an_argument_naming_no_adr_exits_2(tmp_path: Path, argument: str) -> None:
    result = _run(_repo(tmp_path), argument)

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("adr-rules: ")


def test_the_real_adr_0277_lists_its_own_work_order(tmp_path: Path) -> None:
    """Over the real corpus: ADR-0277 §5's three clauses are addressable as §5:1-3."""
    del tmp_path
    out = subprocess.run(  # noqa: S603  # fixed interpreter + in-repo script
        [sys.executable, str(_SCRIPT), "0277"], capture_output=True, text=True, check=True
    ).stdout

    assert "ADR-0277 §5:3" in out
    assert "ADR-0277 §5:4" not in out
    assert "## Context" not in out
