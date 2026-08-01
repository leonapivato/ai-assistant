"""Tests for the ADR citation checker (scripts/check_citations.py).

Driven as a subprocess against a constructed fixture checkout via ``--root``, in
the shape ``test_project_status.py`` established, so every assertion pins the
*rule* rather than whatever the live corpus happens to contain this week.

The cases are organised the way ADR-0088 is: what a citation *is* (§1), what
"resolves" means (§2), why no code citation may fail (§3), the one liveness
report (§4), and — the longest group — what §6 forbids the checker to do. That
last group is the point of this file. A checker that reports nothing is easy;
the expensive mistake ADR-0088 exists to prevent is a confident false finding,
so most of what is asserted below is *silence*.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "check_citations.py"

_PROTOCOLS = '''\
"""Contracts."""

from typing import Protocol


class MemoryStore(Protocol):
    """A store."""

    limit: int

    def get_many(self, ids: list[str]) -> list[str]:
        """Fetch many."""
        ...


class MemoryDecisionKind:
    """A kind."""

    SUPERSEDE = "supersede"


class Engine:
    """An engine."""

    def _project(self) -> None:
        """Project."""


class ToolResult:
    """A result."""

    failure: str
'''


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_repo(root: Path, adrs: dict[str, str], *, extra: dict[str, str] | None = None) -> None:
    """Build a checkout: the three code roots, a small package, and the ADRs given."""
    package = root / "src" / "ai_assistant"
    _write(package / "__init__.py", "")
    _write(package / "core" / "__init__.py", "")
    _write(package / "core" / "protocols.py", _PROTOCOLS)
    _write(package / "memory" / "__init__.py", "")
    _write(package / "memory" / "ingest.py", "class MemoryIngestor:\n    pass\n")
    _write(package / "orchestration" / "__init__.py", "")
    _write(
        package / "testing" / "__init__.py",
        "from ai_assistant.testing.planner import FakePlanner\n",
    )
    _write(package / "testing" / "planner.py", "class FakePlanner:\n    pass\n")
    _write(root / "tests" / "memory" / "test_ingest.py", "def test_x() -> None:\n    pass\n")
    _write(root / "scripts" / "ship.sh", "#!/bin/sh\n")
    for name, body in adrs.items():
        _write(root / "docs" / "adr" / name, body)
    for name, body in (extra or {}).items():
        _write(root / name, body)


def _run(
    root: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    argv = [sys.executable, str(_SCRIPT), "--root", str(root), "--format", "json", *args]
    return subprocess.run(  # noqa: S603  # fixed argv, no shell
        argv, capture_output=True, text=True, check=False, env=env
    )


def _report(root: Path, *args: str, env: dict[str, str] | None = None) -> dict[str, object]:
    result = _run(root, *args, env=env)
    assert result.returncode in (0, 1), result.stderr
    report = json.loads(result.stdout)
    assert isinstance(report, dict)
    return report


def _findings(report: dict[str, object], kind: str) -> list[dict[str, object]]:
    entries = report["findings"]
    assert isinstance(entries, list)
    return [f for f in entries if f["kind"] == kind]


def _citations(report: dict[str, object], kind: str) -> list[str]:
    return [str(f["citation"]) for f in _findings(report, kind)]


def _fake_gh(directory: Path, numbers: list[int]) -> dict[str, str]:
    """Put a ``gh`` on PATH that reports ``numbers`` and never touches the network."""
    script = directory / "gh"
    body = "\n".join(str(n) for n in numbers)
    script.write_text(f'#!/bin/sh\ncat <<"EOF"\n{body}\nEOF\n', encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    env = dict(os.environ)
    env["PATH"] = f"{directory}{os.pathsep}{env.get('PATH', '')}"
    return env


# --------------------------------------------------------------------------- #
# §1 / §6 Tier 1 — a decision citation naming an ADR file that does not exist
# --------------------------------------------------------------------------- #


def test_decision_citation_to_a_missing_adr_fails(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"0001-one.md": "# 1. One\n\nSee ADR-0002 for the rest.\n"})

    result = _run(tmp_path, "--no-tracker")

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert _citations(report, "decision") == ["ADR-0002"]


def test_decision_citation_to_a_present_adr_is_silent(tmp_path: Path) -> None:
    _make_repo(
        tmp_path,
        {"0001-one.md": "# 1. One\n\nSee ADR-0002.\n", "0002-two.md": "# 2. Two\n"},
    )

    report = _report(tmp_path, "--no-tracker")

    assert _findings(report, "decision") == []


def test_a_fenced_reference_to_a_missing_adr_is_not_a_citation(tmp_path: Path) -> None:
    """ADR-0088 §4 fences ``ADR-0090 replaces …`` precisely so §1 excludes it.

    This is the mechanism rather than a courtesy: without it the rule's own ADR
    fails the rule, and `main` is red on a document that is entirely correct.
    """
    body = "# 1. One\n\n```text\nADR-0090 replaces ADR-0080's retry rule.\n```\n"
    _make_repo(tmp_path, {"0001-one.md": body})

    result = _run(tmp_path, "--no-tracker")

    assert result.returncode == 0
    assert _findings(json.loads(result.stdout), "decision") == []


@pytest.mark.parametrize(
    "fence",
    ["```", "````", "~~~", "   ```", "```text"],
    ids=["backticks", "longer-run", "tildes", "indented", "info-string"],
)
def test_every_fence_style_excludes_its_content(tmp_path: Path, fence: str) -> None:
    close = fence.strip()[0] * len(fence.strip())
    body = f"# 1. One\n\n{fence}\nADR-0090 is not real.\n{close}\n"
    _make_repo(tmp_path, {"0001-one.md": body})

    assert _findings(_report(tmp_path, "--no-tracker"), "decision") == []


def test_a_placeholder_that_is_not_four_digits_is_not_a_citation(tmp_path: Path) -> None:
    body = "# 1. One\n\n- Status: Superseded by ADR-XXXX\n\nAlso ADR-123 and ADR-01234.\n"
    _make_repo(tmp_path, {"0001-one.md": body})

    assert _findings(_report(tmp_path, "--no-tracker"), "decision") == []


# --------------------------------------------------------------------------- #
# §6 — a section number is not checked at all, in either tier
# --------------------------------------------------------------------------- #


def test_a_section_reference_into_an_adr_without_that_section_is_silent(tmp_path: Path) -> None:
    """§6: not Tier 1, not Tier 2. Two drafts put it in each tier and both were wrong."""
    _make_repo(
        tmp_path,
        {
            "0001-one.md": "# 1. One\n\nADR-0002 §9 says so, and ADR-0002 §§3-5 too.\n",
            "0002-two.md": "# 2. Two\n\n### 1. Only section\n",
        },
    )

    report = _report(tmp_path, "--no-tracker")

    assert report["findings"] == []


def test_a_bold_numbered_section_is_never_read_as_absent(tmp_path: Path) -> None:
    """§2(a): 72 ADRs number sections with headings, three in bold, twelve not at all.

    A heading-only checker reports 92 false defects on `main`, 78 of them into
    ADR-0015 alone. This checker extracts no structure, so all three shapes are
    equally silent.
    """
    _make_repo(
        tmp_path,
        {
            "0001-one.md": "# 1. One\n\nGolden rule 5 is ADR-0002 §5.\n",
            "0002-two.md": "# 2. Two\n\n**5. ADR numbers are assigned at dispatch.**\n",
        },
    )

    assert _report(tmp_path, "--no-tracker")["findings"] == []


def test_a_supersession_scope_restatement_is_not_reported(tmp_path: Path) -> None:
    """ADR-0074's "ADR-0076 §9's obligation set" names ADR-0074's own §9.

    No mechanical rule separates it from a citation of ADR-0076 §9, which is why
    §6 checks no section reference. The script written for ADR-0088 walked into
    this twice on its first run.
    """
    _make_repo(
        tmp_path,
        {
            "0001-one.md": "# 1. One\n\nADR-0002 §9's obligation set moved.\n",
            "0002-two.md": "# 2. Two\n\n### 1. Only section\n",
        },
    )

    assert _report(tmp_path, "--no-tracker")["findings"] == []


# --------------------------------------------------------------------------- #
# §1(c) / §2(c) — a tracker citation resolves when the number exists, and that
# is the whole of it
# --------------------------------------------------------------------------- #


def test_a_tracker_citation_to_a_missing_number_fails(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"0001-one.md": "# 1. One\n\nTracked by #999.\n"})
    env = _fake_gh(tmp_path, [1, 2, 3])

    result = _run(tmp_path, env=env)

    assert result.returncode == 1
    assert _citations(json.loads(result.stdout), "tracker") == ["#999"]


def test_a_tracker_citation_to_a_present_number_is_silent(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"0001-one.md": "# 1. One\n\nTracked by #2.\n"})
    env = _fake_gh(tmp_path, [1, 2, 3])

    report = _report(tmp_path, env=env)

    assert _findings(report, "tracker") == []
    assert report["tracker_checked"] is True


def test_an_unreachable_tracker_passes_silently_rather_than_failing(tmp_path: Path) -> None:
    """§6's asymmetry: a checker that could not ask has learned nothing."""
    _make_repo(tmp_path, {"0001-one.md": "# 1. One\n\nTracked by #999.\n"})
    empty = tmp_path / "nowhere"
    empty.mkdir()
    env = dict(os.environ)
    env["PATH"] = str(empty)

    result = _run(tmp_path, env=env)

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert _findings(report, "tracker") == []
    assert report["tracker_checked"] is False
    assert report["notes"]


def test_issue_state_is_not_checked(tmp_path: Path) -> None:
    """§2(c): "issue *state* is not checked at all"."""
    body = "# 1. One\n\n**#2 is discharged** and #3 tracks the conversion.\n"
    _make_repo(tmp_path, {"0001-one.md": body})
    env = _fake_gh(tmp_path, [1, 2, 3])

    assert _findings(_report(tmp_path, env=env), "tracker") == []


@pytest.mark.parametrize(
    "line",
    [
        "#### 4. A heading",
        "See the [anchor](#some-heading).",
        "See the [section](#123).",
        'See the [section](#123 "title").',
        "The colour #abc123 is wrong.",
        "Item ##7 is odd.",
        "See <https://example.test/docs/#123>.",
        "See https://example.test/docs/#123 for detail.",
        "See http://example.test/#123.",
        "See //example.test/docs/#123.",
        "See the [section](/docs/#123).",
        "See the [section](../adr/#123).",
        "See the [section](#2/#3).",
        "See the [link](https://example.test/x/#123) too.",
    ],
    ids=[
        "heading",
        "slug-anchor",
        "numeric-anchor",
        "titled-anchor",
        "hex-colour",
        "doubled-hash",
        "autolink-fragment",
        "bare-url-fragment",
        "http-fragment",
        "protocol-relative",
        "root-relative-destination",
        "relative-destination",
        "slash-joined-destination",
        "absolute-destination",
    ],
)
def test_a_hash_that_is_not_a_tracker_citation_is_not_selected(tmp_path: Path, line: str) -> None:
    """Tier 1 is the tier that *fails*, so a false selection here is the costly one."""
    _make_repo(tmp_path, {"0001-one.md": f"# 1. One\n\n{line}\n"})
    env = _fake_gh(tmp_path, [1])

    result = _run(tmp_path, env=env)

    assert result.returncode == 0
    assert _findings(json.loads(result.stdout), "tracker") == []


@pytest.mark.parametrize(
    "line",
    [
        "The fix (#2) landed.",
        "Tracked by #2.",
        "See #2/#3.",
        "#2 is the one.",
        "See https://example.test/x and #2.",
        "See the [guide](https://example.test/g) and #2.",
    ],
    ids=[
        "parenthesised",
        "trailing",
        "slash-joined",
        "leading",
        "beside-a-url",
        "beside-a-link",
    ],
)
def test_a_tracker_citation_in_prose_is_still_selected(tmp_path: Path, line: str) -> None:
    """The exclusions above must not swallow the form the corpus actually writes."""
    _make_repo(tmp_path, {"0001-one.md": f"# 1. One\n\n{line}\n"})
    env = _fake_gh(tmp_path, [1])

    assert _citations(_report(tmp_path, env=env), "tracker")


# --------------------------------------------------------------------------- #
# §1(b) b1 / §2(b) — a module path, defined by root rather than by shape
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "cited",
    [
        "memory/ingest.py",
        "src/ai_assistant/core/protocols.py",
        "tests/memory/test_ingest.py",
        "scripts/ship.sh",
        "core/protocols.py",
    ],
    ids=["relative", "full", "tests-root", "scripts-root", "relative-core"],
)
def test_a_module_path_that_exists_is_silent(tmp_path: Path, cited: str) -> None:
    _make_repo(tmp_path, {"0001-one.md": f"# 1. One\n\nSee `{cited}`.\n"})

    assert _findings(_report(tmp_path, "--no-tracker"), "module-path") == []


def test_a_module_path_that_is_anchored_but_absent_is_reported_never_failed(
    tmp_path: Path,
) -> None:
    """§3: ADR-0015 §1 removes `scripts/codex_review_decision.py` and is correct to name it."""
    body = "# 1. One\n\nRemoved `scripts/codex_review_decision.py`, weighed `core/invocation.py`.\n"
    _make_repo(tmp_path, {"0001-one.md": body})

    result = _run(tmp_path, "--no-tracker")

    assert result.returncode == 0, "no code citation may fail a check (ADR-0088 §3)"
    report = json.loads(result.stdout)
    assert sorted(_citations(report, "module-path")) == [
        "core/invocation.py",
        "scripts/codex_review_decision.py",
    ]
    assert all(f["tier"] == 2 for f in _findings(report, "module-path"))


@pytest.mark.parametrize(
    "cited",
    [
        "docs/review/guide.md",
        ".github/workflows/gate.yml",
        "docs/adr/template.md",
        ".review/",
        "/review",
        "/srv/shared",
        "some/where/else.py",
    ],
    ids=["docs", "workflow", "adr-doc", "dot-dir", "slash-command", "absolute", "unrooted"],
)
def test_a_path_under_no_code_root_is_not_a_code_citation(tmp_path: Path, cited: str) -> None:
    """§1(b): "Root membership is mechanical, where "contains a `/`" is not"."""
    _make_repo(tmp_path, {"0001-one.md": f"# 1. One\n\nSee `{cited}`.\n"})

    assert _findings(_report(tmp_path, "--no-tracker"), "module-path") == []


@pytest.mark.parametrize(
    "cited",
    [
        "src/ai_assistant/../../docs/missing.md",
        "memory/../../../docs/adr/missing.md",
        "../docs/review/guide.md",
        "tests/../docs/missing.py",
    ],
    ids=["full-form", "relative-form", "leading", "root-escape"],
)
def test_a_path_that_normalises_out_of_its_root_is_not_a_code_citation(
    tmp_path: Path, cited: str
) -> None:
    """§1(b) is about where a path *lies*, and `..` decides that as much as the prefix does.

    Containment in the repository is not the test: ``docs/`` exists here, so a
    traversal out of a code root anchors on it and would be reported as an
    absent module path — against a document reference §1(b) says nothing
    resolves against the code.
    """
    _write(tmp_path / "docs" / "review" / "guide.md", "# guide\n")
    # The directory that makes the *second* reading of `tests/../docs/…`
    # anchored: without the explicit-root rule the checker would report there.
    _write(tmp_path / "tests" / "docs" / "conftest.py", "")
    _make_repo(tmp_path, {"0001-one.md": f"# 1. One\n\nSee `{cited}`.\n"})

    assert _findings(_report(tmp_path, "--no-tracker"), "module-path") == []


def test_an_explicit_root_prefix_is_not_re_read_as_a_relative_path(tmp_path: Path) -> None:
    """A citation that names a root gets that reading and no other.

    ``tests/memory/gone.py`` is absent under ``tests/`` and present nowhere; a
    second reading relative to each root would look for
    ``tests/tests/memory/gone.py`` and, if it anchored, report a path the author
    did not write.
    """
    _write(tmp_path / "tests" / "tests" / "memory" / "gone.py", "")
    _make_repo(tmp_path, {"0001-one.md": "# 1. One\n\nSee `tests/memory/gone.py`.\n"})

    assert _citations(_report(tmp_path, "--no-tracker"), "module-path") == ["tests/memory/gone.py"]


def test_a_legacy_line_number_is_stripped_and_the_path_resolved(tmp_path: Path) -> None:
    """§5: "`testing/memory.py:41` is checked as `testing/memory.py`"."""
    body = (
        "# 1. One\n\nSee `memory/ingest.py:41`, `memory/ingest.py:12-30` "
        "and `memory/ingest.py:149,539,548`.\n"
    )
    _make_repo(tmp_path, {"0001-one.md": body})

    assert _findings(_report(tmp_path, "--no-tracker"), "module-path") == []


def test_a_pytest_node_id_resolves_on_its_path(tmp_path: Path) -> None:
    body = "# 1. One\n\nSee `tests/memory/test_ingest.py::test_x`.\n"
    _make_repo(tmp_path, {"0001-one.md": body})

    assert _findings(_report(tmp_path, "--no-tracker"), "module-path") == []


def test_a_span_carrying_regex_punctuation_is_not_read_as_a_path(tmp_path: Path) -> None:
    """ADR-0085 backticks ``\\/`` inside a regex; no filesystem question is asked."""
    _make_repo(tmp_path, {"0001-one.md": "# 1. One\n\nThe escape `\\/` and `a|b/c`.\n"})

    assert _findings(_report(tmp_path, "--no-tracker"), "module-path") == []


# --------------------------------------------------------------------------- #
# §1(b) b2 / §2(b) — a dotted symbol resolves against a definition site
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "cited",
    [
        "MemoryStore.get_many",
        "MemoryStore.limit",
        "Engine._project",
        "ai_assistant.core.protocols.MemoryStore",
        "core.protocols.MemoryStore",
        "ai_assistant.testing.FakePlanner",
    ],
    ids=["method", "annotation", "private", "fully-qualified", "package-relative", "re-export"],
)
def test_a_dotted_symbol_with_a_definition_is_silent(tmp_path: Path, cited: str) -> None:
    _make_repo(tmp_path, {"0001-one.md": f"# 1. One\n\nSee `{cited}`.\n"})

    assert _findings(_report(tmp_path, "--no-tracker"), "dotted-symbol") == []


def test_a_removed_enum_member_is_reported_never_failed(tmp_path: Path) -> None:
    """§3 class 2, and §Consequences: "`MemoryDecisionKind.MERGE` will be on it forever"."""
    body = "# 1. One\n\nA later ADR replaced `MemoryDecisionKind.MERGE` with two members.\n"
    _make_repo(tmp_path, {"0001-one.md": body})

    result = _run(tmp_path, "--no-tracker")

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert _citations(report, "dotted-symbol") == ["MemoryDecisionKind.MERGE"]
    assert _findings(report, "dotted-symbol")[0]["tier"] == 2


def test_resolution_is_a_definition_lookup_not_a_text_search(tmp_path: Path) -> None:
    """§2(b): a free-text search lets `Status` "resolve" against a docstring."""
    package = tmp_path / "src" / "ai_assistant"
    _make_repo(tmp_path, {"0001-one.md": "# 1. One\n\nSee `MemoryStore.mentioned_only`.\n"})
    _write(
        package / "memory" / "prose.py",
        '"""A docstring mentioning MemoryStore.mentioned_only and nothing else."""\n',
    )

    assert _citations(_report(tmp_path, "--no-tracker"), "dotted-symbol") == [
        "MemoryStore.mentioned_only"
    ]


@pytest.mark.parametrize(
    "cited",
    [
        "CONTRIBUTING.md",
        "CLAUDE.md",
        "typing.Protocol",
        "asyncio.timeout",
        "np.linalg.norm",
        "cost.amount",
        "googleapis.com",
    ],
    ids=["doc", "doc-2", "stdlib", "stdlib-2", "vendor", "instance-attr", "domain"],
)
def test_a_dotted_token_that_is_not_a_repository_symbol_is_not_selected(
    tmp_path: Path, cited: str
) -> None:
    _make_repo(tmp_path, {"0001-one.md": f"# 1. One\n\nSee `{cited}`.\n"})

    assert _findings(_report(tmp_path, "--no-tracker"), "dotted-symbol") == []


def test_a_member_of_a_class_defined_elsewhere_is_unevaluable(tmp_path: Path) -> None:
    """`Agent.run` and `Device.AUTO` ask about a vendor's class; nothing here answers it."""
    body = "# 1. One\n\n`Agent.run` awaits, `Device.AUTO` selects, and `P.id` is prose.\n"
    _make_repo(tmp_path, {"0001-one.md": body})

    assert _findings(_report(tmp_path, "--no-tracker"), "dotted-symbol") == []


def test_a_chain_through_a_resolved_definition_is_unevaluable(tmp_path: Path) -> None:
    """Following `.message` off `ToolResult.failure` needs type inference, which §6 forbids."""
    _make_repo(tmp_path, {"0001-one.md": "# 1. One\n\nSee `ToolResult.failure.message`.\n"})

    assert _findings(_report(tmp_path, "--no-tracker"), "dotted-symbol") == []


def test_a_dotted_module_path_that_does_not_exist_is_still_reported(tmp_path: Path) -> None:
    """A chain of modules is evaluable — only a chain through a *definition* is not."""
    body = "# 1. One\n\nADR-0031 weighed `ai_assistant.tools.invocation.interrupted_outcome`.\n"
    _make_repo(tmp_path, {"0001-one.md": body})

    assert _citations(_report(tmp_path, "--no-tracker"), "dotted-symbol") == [
        "ai_assistant.tools.invocation.interrupted_outcome"
    ]


def test_a_bare_backticked_token_is_never_selected(tmp_path: Path) -> None:
    """§1(b) b3, and §6: reporting `ConversationService` means reporting `Status` too."""
    body = (
        "# 1. One\n\nThe class is `ConversationService`; the vocabulary is `Status`, "
        "`Accepted`, `MERGE`, `None`, `DTZ` and `HEAD`.\n"
    )
    _make_repo(tmp_path, {"0001-one.md": body})

    assert _report(tmp_path, "--no-tracker")["findings"] == []


# --------------------------------------------------------------------------- #
# §4 — the one liveness report, driven by the reverse record
# --------------------------------------------------------------------------- #


def _pair(status: str, record: str) -> dict[str, str]:
    return {
        "0001-one.md": f"# 1. One\n\n- Status: {status}\n- Date: 2026-01-01\n",
        "0002-two.md": f"# 2. Two\n\n- Status: Accepted\n{record}- Date: 2026-01-02\n",
    }


def test_a_matching_pair_of_records_is_silent(tmp_path: Path) -> None:
    _make_repo(tmp_path, _pair("Superseded by ADR-0002", "- Supersedes: ADR-0001 (all of it)\n"))

    assert _findings(_report(tmp_path, "--no-tracker"), "liveness") == []


def test_the_supersession_token_matches_case_insensitively(tmp_path: Path) -> None:
    """§4: capitalised when it leads the line, lower-case after a grandfathered `Accepted,`."""
    _make_repo(
        tmp_path,
        _pair(
            "Accepted, partially superseded by ADR-0002 and ADR-0003",
            "- Partially supersedes: ADR-0001 — §3's clause only\n",
        ),
    )

    assert _findings(_report(tmp_path, "--no-tracker"), "liveness") == []


def test_a_missing_forward_record_is_reported(tmp_path: Path) -> None:
    _make_repo(tmp_path, _pair("Accepted", "- Supersedes: ADR-0001 (all of it)\n"))

    result = _run(tmp_path, "--no-tracker")

    assert result.returncode == 0, "a liveness disagreement never fails (ADR-0088 §4)"
    findings = _findings(json.loads(result.stdout), "liveness")
    assert len(findings) == 1
    assert findings[0]["path"] == "docs/adr/0002-two.md"
    assert findings[0]["tier"] == 2


def test_a_bare_mention_without_the_token_is_reported(tmp_path: Path) -> None:
    """§4: a status recording only an amendment would silence a weaker test."""
    _make_repo(tmp_path, _pair("Accepted, §1 amended by ADR-0002", "- Supersedes: ADR-0001\n"))

    assert len(_findings(_report(tmp_path, "--no-tracker"), "liveness")) == 1


def test_only_the_first_adr_in_a_reverse_record_is_the_target(tmp_path: Path) -> None:
    """§4: "one record names one ADR"; the scope after it cites others freely."""
    adrs = _pair(
        "Superseded by ADR-0002",
        "- Supersedes: ADR-0001 — the clause ADR-0003 later relied on, cf. ADR-0004\n",
    )
    adrs["0003-three.md"] = "# 3. Three\n\n- Status: Accepted\n"
    adrs["0004-four.md"] = "# 4. Four\n\n- Status: Accepted\n"
    _make_repo(tmp_path, adrs)

    assert _findings(_report(tmp_path, "--no-tracker"), "liveness") == []


def test_an_absent_reverse_record_is_silence_not_a_report(tmp_path: Path) -> None:
    """§4: "an absent one is silence, not a report" — the corpus is quiet by construction."""
    _make_repo(tmp_path, _pair("Superseded by ADR-0002", ""))

    assert _findings(_report(tmp_path, "--no-tracker"), "liveness") == []


def test_a_wrapped_status_field_is_read_whole(tmp_path: Path) -> None:
    """ADR-0070 §4: every physical line, since a legacy value may wrap."""
    adrs = {
        "0001-one.md": (
            "# 1. One\n\n- Status: Accepted, and then later\n"
            "  partially superseded by ADR-0002 for the parts §3 named\n- Date: 2026-01-01\n"
        ),
        "0002-two.md": "# 2. Two\n\n- Status: Accepted\n- Supersedes: ADR-0001\n",
    }
    _make_repo(tmp_path, adrs)

    assert _findings(_report(tmp_path, "--no-tracker"), "liveness") == []


def test_a_body_list_item_that_looks_like_a_record_is_not_one(tmp_path: Path) -> None:
    """§4 legislates a *header* line; ADR-0070 §4 forbids reading a supersession out of prose.

    An unfenced body bullet is the case a fence exclusion alone does not cover,
    and an ADR explaining the rule writes exactly this.
    """
    adrs = {
        "0001-one.md": "# 1. One\n\n- Status: Accepted\n\n## Context\n\nStands.\n",
        "0002-two.md": (
            "# 2. Two\n\n- Status: Accepted\n\n## Decision\n\n"
            "A superseding ADR writes a record like this one:\n\n"
            "- Supersedes: ADR-0001 (its whole §3)\n"
        ),
    }
    _make_repo(tmp_path, adrs)

    assert _findings(_report(tmp_path, "--no-tracker"), "liveness") == []


@pytest.mark.parametrize(
    "heading",
    ["## Decision", "  ## Decision", "   ##\tDecision", "##\tDecision", "##"],
    ids=["plain", "indented", "indented-tab", "tab", "bare"],
)
def test_the_header_boundary_follows_markdown_not_one_spelling(
    tmp_path: Path, heading: str
) -> None:
    """A heading the boundary did not recognise puts the whole body back in scope."""
    adrs = {
        "0001-one.md": "# 1. One\n\n- Status: Accepted\n\n## Context\n\nStands.\n",
        "0002-two.md": (
            f"# 2. Two\n\n- Status: Accepted\n\n{heading}\n\n"
            "A record is written like this:\n\n- Supersedes: ADR-0001\n"
        ),
    }
    _make_repo(tmp_path, adrs)

    assert _findings(_report(tmp_path, "--no-tracker"), "liveness") == []


@pytest.mark.parametrize(
    "record",
    ["    - Supersedes: ADR-0001", "  - Supersedes: ADR-0001", "\t- Supersedes: ADR-0001"],
    ids=["four-spaces", "nested-two", "tab"],
)
def test_an_item_nested_under_a_header_field_is_not_a_record(tmp_path: Path, record: str) -> None:
    """§4 makes the reverse record a header *field*; a nested item is not one.

    An ADR explaining the rule hangs the illustration under its own ``Status``,
    and reading that as a field declares a supersession nobody wrote.
    """
    adrs = {
        "0001-one.md": "# 1. One\n\n- Status: Accepted\n\n## Context\n\nStands.\n",
        "0002-two.md": (
            f"# 2. Two\n\n- Status: Accepted\n{record}\n- Date: 2026-01-02\n\n"
            "## Context\n\nExplains the form.\n"
        ),
    }
    _make_repo(tmp_path, adrs)

    assert _findings(_report(tmp_path, "--no-tracker"), "liveness") == []


def test_a_commented_out_record_is_display_not_a_record(tmp_path: Path) -> None:
    """An HTML comment is display for the same reason a fence is (§1).

    ``docs/adr/template.md`` documents the supersession form inside one.
    """
    adrs = {
        "0001-one.md": "# 1. One\n\n- Status: Accepted\n\n## Context\n\nStands.\n",
        "0002-two.md": (
            "# 2. Two\n\n- Status: Accepted\n"
            "<!-- Write the record like this:\n- Supersedes: ADR-0001 (its §3)\n-->\n"
            "- Date: 2026-01-02\n\n## Context\n\nExplains the form.\n"
        ),
    }
    _make_repo(tmp_path, adrs)

    assert _findings(_report(tmp_path, "--no-tracker"), "liveness") == []


def test_a_setext_heading_ends_the_header_too(tmp_path: Path) -> None:
    """``Decision`` over ``-------`` is a level-2 heading; the corpus writes none, and it counts."""
    adrs = {
        "0001-one.md": "# 1. One\n\n- Status: Accepted\n\n## Context\n\nStands.\n",
        "0002-two.md": (
            "# 2. Two\n\n- Status: Accepted\n\nDecision\n--------\n\n"
            "A record is written like this:\n\n- Supersedes: ADR-0001\n"
        ),
    }
    _make_repo(tmp_path, adrs)

    assert _findings(_report(tmp_path, "--no-tracker"), "liveness") == []


def test_a_dashed_line_under_a_record_is_not_a_setext_heading(tmp_path: Path) -> None:
    """CommonMark needs a *paragraph* above the underline; a list item is not one.

    Reading one as a heading would end the header above a real record and drop
    it — the opposite failure, and the reason the guard is asserted rather than
    assumed.
    """
    adrs = {
        "0001-one.md": "# 1. One\n\n- Status: Accepted\n\n## Context\n\nStands.\n",
        "0002-two.md": (
            "# 2. Two\n\n- Status: Accepted\n- Supersedes: ADR-0001\n---\n\n"
            "## Context\n\nReplaces it.\n"
        ),
    }
    _make_repo(tmp_path, adrs)

    assert len(_findings(_report(tmp_path, "--no-tracker"), "liveness")) == 1


def test_a_level_three_heading_does_not_end_the_header(tmp_path: Path) -> None:
    """``###`` closes its marker with a third ``#``, not with whitespace."""
    adrs = {
        "0001-one.md": "# 1. One\n\n- Status: Accepted\n\n## Context\n\nStands.\n",
        "0002-two.md": (
            "# 2. Two\n\n- Status: Accepted\n### A subsection in the header\n"
            "- Supersedes: ADR-0001\n\n## Context\n\nReplaces it.\n"
        ),
    }
    _make_repo(tmp_path, adrs)

    assert len(_findings(_report(tmp_path, "--no-tracker"), "liveness")) == 1


def test_a_real_header_record_survives_the_header_boundary(tmp_path: Path) -> None:
    """The boundary must not silence the records §4 exists to compare."""
    adrs = {
        "0001-one.md": "# 1. One\n\n- Status: Accepted\n\n## Context\n\nStands.\n",
        "0002-two.md": (
            "# 2. Two\n\n- Status: Accepted\n- Supersedes: ADR-0001 (its whole §3)\n"
            "\n## Context\n\nReplaces it.\n"
        ),
    }
    _make_repo(tmp_path, adrs)

    findings = _findings(_report(tmp_path, "--no-tracker"), "liveness")

    assert len(findings) == 1
    assert findings[0]["line"] == 4


def test_a_fenced_reverse_record_is_an_example_not_a_record(tmp_path: Path) -> None:
    """§1's fence exclusion is general, so §4's header fields obey it too."""
    adrs = {
        "0001-one.md": "# 1. One\n\n- Status: Accepted\n",
        "0002-two.md": (
            "# 2. Two\n\n- Status: Accepted\n\n"
            "An ADR records a supersession like this:\n\n"
            "```text\n- Supersedes: ADR-0001 (its whole §3)\n```\n"
        ),
    }
    _make_repo(tmp_path, adrs)

    assert _findings(_report(tmp_path, "--no-tracker"), "liveness") == []


def test_a_reverse_record_naming_a_missing_adr_is_left_to_tier_1(tmp_path: Path) -> None:
    _make_repo(
        tmp_path, {"0002-two.md": "# 2. Two\n\n- Status: Accepted\n- Supersedes: ADR-0001\n"}
    )

    report = _report(tmp_path, "--no-tracker")

    assert _findings(report, "liveness") == []
    assert _citations(report, "decision") == ["ADR-0001"]


# --------------------------------------------------------------------------- #
# §6 — what the checker does not do, and how it exits
# --------------------------------------------------------------------------- #


def test_no_quotation_is_verified(tmp_path: Path) -> None:
    """§6 permits a quotation check and §9 declines to require one.

    Nothing here matches quoted text, so a misquotation is a miss — which §6
    calls benign — rather than the fragment-matched false confirmation it calls
    the one dangerous outcome.
    """
    adrs = {
        "0001-one.md": "# 1. One\n\n### 1. Rule\n\nThe store is authoritative.\n",
        "0002-two.md": '# 2. Two\n\nADR-0001 §1 says "the store is advisory and may be ignored".\n',
    }
    _make_repo(tmp_path, adrs)

    assert _report(tmp_path, "--no-tracker")["findings"] == []


def test_tier_2_alone_exits_zero(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"0001-one.md": "# 1. One\n\nRemoved `core/invocation.py`.\n"})

    result = _run(tmp_path, "--no-tracker")

    assert result.returncode == 0
    assert _findings(json.loads(result.stdout), "module-path")


def test_report_only_exits_zero_on_a_tier_1_finding(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"0001-one.md": "# 1. One\n\nSee ADR-0002.\n"})

    assert _run(tmp_path, "--no-tracker").returncode == 1
    assert _run(tmp_path, "--no-tracker", "--report-only").returncode == 0


def test_the_summary_file_receives_the_markdown_report(tmp_path: Path) -> None:
    _make_repo(tmp_path, {"0001-one.md": "# 1. One\n\nSee ADR-0002.\n"})
    summary = tmp_path / "summary.md"

    _run(tmp_path, "--no-tracker", "--summary", str(summary))

    written = summary.read_text(encoding="utf-8")
    assert "ADR citation check" in written
    assert "ADR-0002" in written


def test_the_text_report_names_what_is_not_checked(tmp_path: Path) -> None:
    """§Consequences: a standing non-zero Tier 2 has to be legible to whoever reads it."""
    _make_repo(tmp_path, {"0001-one.md": "# 1. One\n\nRemoved `core/invocation.py`.\n"})

    argv = [sys.executable, str(_SCRIPT), "--root", str(tmp_path), "--no-tracker"]
    result = subprocess.run(  # noqa: S603  # fixed argv, no shell
        argv, capture_output=True, text=True, check=True
    )

    assert "Tier 1 — fails the change (0)" in result.stdout
    assert "Tier 2 — reported, never fails (1)" in result.stdout
    assert "bare backticked tokens (b3), section numbers, issue state" in result.stdout
