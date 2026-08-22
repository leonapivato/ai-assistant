"""Tests for the dispatch-brief checker (scripts/brief_check.py).

Driven as a subprocess against a constructed fixture checkout via ``--root``, as
``test_project_status.py`` is, so the assertions pin the *extraction and
matching* logic and never depend on the live repo's ADRs, symbols or paths.

The section fixtures are the three shapes the corpus actually uses — a numbered
heading, a lettered sub-heading, a bold decision paragraph, and an ordered item
inside ``## Decision`` — because matching only the modern one would report every
``ADR-0015 §5`` in `CONTRIBUTING.md` as absent.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "scripts" / "brief_check.py"

_MODERN_ADR = """# 1. First decision

- Status: Accepted

## Context

Prose that mentions 5 things and section 9 of nothing.

## Decision

### 1. A numbered heading

Body.

#### 2a. A lettered sub-heading

Body.

### 1000. A section whose label is longer than three digits

Body.

## Consequences
"""

_OLDER_ADR = """# 2. Second decision

- Status: Accepted

## Decision

**3. A bold decision paragraph.** The older corpus numbers its Decision this
way rather than with headings.

4. An ordered item, the third shape.

## Consequences
"""

_ENGINE = '''"""A module that defines one class and merely mentions another."""


class Engine:
    """The real thing."""

    # Widget is discussed here and defined nowhere.


class \u0394Engine:
    """A Unicode identifier, which Python permits and briefs may name."""
'''

_CONFIG = """PROTOCOL_VERSION = 9
"""


def _make_repo(root: Path) -> None:
    """Build a checkout with two ADRs, two source modules and one test module."""
    adr = root / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "0001-first.md").write_text(_MODERN_ADR)
    (adr / "0002-second.md").write_text(_OLDER_ADR)

    pkg = root / "src" / "ai_assistant"
    (pkg / "orchestration").mkdir(parents=True)
    (pkg / "orchestration" / "engine.py").write_text(_ENGINE)
    (pkg / "core").mkdir()
    (pkg / "core" / "config.py").write_text(_CONFIG)
    (root / "tests" / "orchestration").mkdir(parents=True)
    (root / "tests" / "orchestration" / "test_engine.py").write_text("from x import Engine\n")


def _run(root: Path, brief: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # fixed interpreter + in-repo script
        [sys.executable, str(_SCRIPT), "--root", str(root), *args],
        input=brief,
        capture_output=True,
        text=True,
        check=False,
    )


def _row(out: str, token: str) -> str:
    """Return the single report row containing ``token``."""
    matches = [line for line in out.splitlines() if token in line]
    assert len(matches) == 1, f"expected exactly one row with {token!r}, got {matches}"
    return matches[0]


def _section_of(out: str, row: str) -> str:
    """Return the group heading (``absent``/``present``/``not checked``) a row sits under."""
    heading = ""
    for line in out.splitlines():
        if line and not line.startswith(" "):
            heading = line
        if line == row:
            return heading
    raise AssertionError(f"row not found: {row!r}")


def test_a_present_adr_names_the_file_and_an_absent_one_is_reported(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    result = _run(tmp_path, "Read ADR-0001 and ADR-0009 before starting.")

    assert "0001-first.md" in _row(result.stdout, "ADR-0001")
    assert _section_of(result.stdout, _row(result.stdout, "ADR-0001")).startswith("present")
    assert _section_of(result.stdout, _row(result.stdout, "ADR-0009")).startswith("absent")


def test_every_section_shape_the_corpus_uses_resolves(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    result = _run(
        tmp_path,
        "ADR-0001 §1 and ADR-0001 §2a, plus ADR-0002 §3 and ADR-0002 §4.",
    )

    assert "A numbered heading" in _row(result.stdout, "ADR-0001 §1")
    assert "A lettered sub-heading" in _row(result.stdout, "ADR-0001 §2a")
    assert "A bold decision paragraph" in _row(result.stdout, "ADR-0002 §3")
    assert "An ordered item" in _row(result.stdout, "ADR-0002 §4")
    assert result.returncode == 0


def test_a_section_the_adr_does_not_carry_is_absent(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    result = _run(tmp_path, "Follow ADR-0001 §7 exactly.")

    assert _section_of(result.stdout, _row(result.stdout, "ADR-0001 §7")).startswith("absent")
    assert result.returncode == 1


def test_a_section_range_is_expanded_and_a_forward_reference_binds(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    # The en dash is the separator briefs actually use, spelled as an escape so
    # the literal does not trip ruff's ambiguous-character rule.
    result = _run(tmp_path, "ADR-0001 §§1\u20132 apply, and section 3 of ADR-0002.")

    assert _section_of(result.stdout, _row(result.stdout, "ADR-0001 §1")).startswith("present")
    assert _section_of(result.stdout, _row(result.stdout, "ADR-0001 §2")).startswith("absent")
    assert _section_of(result.stdout, _row(result.stdout, "ADR-0002 §3")).startswith("present")


def test_a_section_bound_to_no_adr_is_not_checked_rather_than_absent(tmp_path: Path) -> None:
    # A bare §N carried forward to the last ADR named anywhere earlier misbinds —
    # over CONTRIBUTING.md it bound a quoted §9 to the ADR named later in the
    # sentence, and bound "#1226 §6" to an ADR entirely. A false absence is what
    # gets a checker skipped, so an unbound reference fails towards silence.
    _make_repo(tmp_path)

    result = _run(tmp_path, "ADR-0001 governs. The skill's §6 also matters, and #1226 §6.")

    assert _section_of(result.stdout, _row(result.stdout, "§6")).startswith("not checked")
    assert result.returncode == 0


def test_a_symbol_is_reported_with_the_file_that_defines_it(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    result = _run(tmp_path, "The class is `Engine`, and `PROTOCOL_VERSION` is the constant.")

    assert "orchestration/engine.py" in _row(result.stdout, "Engine")
    assert "core/config.py" in _row(result.stdout, "PROTOCOL_VERSION")
    assert result.returncode == 0


def test_a_symbol_nothing_defines_says_so_rather_than_naming_a_mention(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    result = _run(tmp_path, "Look at `Widget` while you are there.")

    row = _row(result.stdout, "Widget")
    assert _section_of(result.stdout, row).startswith("present")
    assert "mentioned, not defined" in row


def test_an_absent_symbol_is_reported_and_exits_1(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    result = _run(tmp_path, "The class is `AssistantEngineImpl` in `orchestration.engine`.")

    assert _section_of(result.stdout, _row(result.stdout, "AssistantEngineImpl")).startswith(
        "absent"
    )
    assert result.returncode == 1


def test_a_dotted_symbol_resolves_on_its_last_component(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    result = _run(tmp_path, "Use `ai_assistant.orchestration.engine.Engine` here.")

    row = _row(result.stdout, "engine.Engine")
    assert _section_of(result.stdout, row).startswith("present")
    assert "orchestration/engine.py" in row


def test_paths_are_checked_and_a_non_path_slash_token_is_not(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    result = _run(
        tmp_path,
        "Touch `src/ai_assistant/orchestration/engine.py`, never `src/ai_assistant/memory/`. "
        "Branch from `origin/main`.",
    )

    assert _section_of(result.stdout, _row(result.stdout, "engine.py")).startswith("present")
    assert _section_of(result.stdout, _row(result.stdout, "memory/")).startswith("absent")
    assert "origin/main" not in result.stdout


def test_a_glob_is_cut_back_to_its_directory_and_a_placeholder_is_not_checked(
    tmp_path: Path,
) -> None:
    _make_repo(tmp_path)

    result = _run(
        tmp_path,
        "Fence: `tests/orchestration/**` and `docs/adr/NNNN-*.md`, not `tests/<pkg>/test_*.py`.",
    )

    assert _section_of(result.stdout, _row(result.stdout, "tests/orchestration/**")).startswith(
        "present"
    )
    assert _section_of(result.stdout, _row(result.stdout, "docs/adr/NNNN")).startswith("present")
    assert _section_of(result.stdout, _row(result.stdout, "<pkg>")).startswith("not checked")


def test_fenced_code_blocks_are_not_extracted(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    result = _run(tmp_path, "Run it:\n\n```bash\ngit switch -c x ADR-0009 `Nonexistent`\n```\n")

    assert "ADR-0009" not in result.stdout
    assert "Nonexistent" not in result.stdout
    assert result.returncode == 0


def test_quiet_prints_only_absences_and_nothing_when_there_are_none(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    clean = _run(tmp_path, "ADR-0001 §1 and `Engine`.", "--quiet")
    dirty = _run(tmp_path, "ADR-0009 and `Engine`.", "--quiet")

    assert clean.stdout.strip() == ""
    assert clean.returncode == 0
    assert dirty.stdout.strip().startswith("ADR-0009")
    assert "Engine" not in dirty.stdout
    assert dirty.returncode == 1


def test_a_brief_read_from_a_file_gives_the_same_answer_as_stdin(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    brief = tmp_path / "brief.md"
    brief.write_text("Read ADR-0009.\n")

    from_file = subprocess.run(  # noqa: S603  # fixed interpreter + in-repo script
        [sys.executable, str(_SCRIPT), "--root", str(tmp_path), str(brief)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert _section_of(from_file.stdout, _row(from_file.stdout, "ADR-0009")).startswith("absent")
    assert from_file.returncode == 1


def test_a_name_made_twice_is_reported_once(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    result = _run(tmp_path, "ADR-0001 §1, and again ADR-0001 §1, and `Engine` twice: `Engine`.")

    _row(result.stdout, "ADR-0001 §1")  # asserts exactly one row
    _row(result.stdout, "Engine")


def test_a_fence_longer_than_three_delimiters_is_still_a_fence(tmp_path: Path) -> None:
    # A brief quoting backticked names inside a code block has to open with four,
    # and that block's contents are illustrations like any other fence's.
    _make_repo(tmp_path)

    result = _run(tmp_path, "Example:\n\n````md\nSee ADR-0009 and `Nonexistent`.\n````\n")

    assert "ADR-0009" not in result.stdout
    assert "Nonexistent" not in result.stdout
    assert result.returncode == 0


def test_a_path_resolving_outside_the_checkout_is_not_checked(tmp_path: Path) -> None:
    # A repository-relative prefix is not proof the path stays inside the
    # checkout, and `exists()` above the root answers a question this check
    # makes no claim over.
    _make_repo(tmp_path)

    result = _run(tmp_path, "Touch `src/../../elsewhere`.")

    assert _section_of(result.stdout, _row(result.stdout, "elsewhere")).startswith("not checked")
    assert result.returncode == 0


def test_a_unicode_identifier_is_checked_rather_than_skipped(tmp_path: Path) -> None:
    # Python permits it, so a brief may name it; skipping it silently would let a
    # brief citing an absent one pass with exit 0.
    _make_repo(tmp_path)

    present = _run(tmp_path, "The class is `\u0394Engine`.")
    absent = _run(tmp_path, "The class is `\u0394Widget`.")

    assert "orchestration/engine.py" in _row(present.stdout, "\u0394Engine")
    assert _section_of(absent.stdout, _row(absent.stdout, "\u0394Widget")).startswith("absent")
    assert absent.returncode == 1


def test_a_closer_of_the_wrong_delimiter_does_not_end_the_block(tmp_path: Path) -> None:
    # A closing fence is the same character as the opener and alone on its line.
    # Ending the block on anything else reads the rest of the code sample as if
    # the brief had claimed it.
    _make_repo(tmp_path)

    result = _run(tmp_path, "````\n````~~~~\nADR-0009 and `Nonexistent`\n````\n")

    assert "ADR-0009" not in result.stdout
    assert "Nonexistent" not in result.stdout


def test_an_unclosed_fence_runs_to_the_end_of_the_brief(tmp_path: Path) -> None:
    # Markdown's rule, and the conservative one: a typo in a fence must not turn
    # the rest of a code sample into claims about the tree.
    _make_repo(tmp_path)

    result = _run(tmp_path, "Run:\n\n```bash\ngit switch -c x\nADR-0009\n")

    assert "ADR-0009" not in result.stdout
    assert result.returncode == 0


def test_a_long_section_label_is_not_truncated(tmp_path: Path) -> None:
    # A capped digit run reads `§1000` as `§100` and then reports a section
    # nobody cited as absent, which is the false absence this checker must not
    # produce.
    _make_repo(tmp_path)

    result = _run(tmp_path, "ADR-0001 §1000 governs.")

    assert "§100 " not in result.stdout
    assert "longer than three digits" in _row(result.stdout, "ADR-0001 §1000")
    assert result.returncode == 0


def test_an_absurd_section_range_reports_rather_than_crashing(tmp_path: Path) -> None:
    # CPython refuses to convert an integer literal beyond a few thousand
    # digits. A brief must not be able to hand this script a traceback in place
    # of a report, however unlikely the brief.
    _make_repo(tmp_path)
    huge = "1" * 4301

    result = _run(tmp_path, f"ADR-0001 §§{huge}-{huge} governs.")

    assert "Traceback" not in result.stderr
    assert result.returncode in (0, 1)
