"""Tests for parted review rounds in scripts/codex-review.sh (ADR-0331).

A round whose single-turn prompt would exceed the 240,000-byte turn budget reads
the rendered diff in parts, one turn each, in the persona's one conversation, and
closes with a verdict turn that is handed every part turn's message. Under the
budget nothing changes, byte for byte. These pin ADR-0331 §11's obligations:

* §11:1 — an under-budget round builds the prompt it built before;
* §11:2 — the parts reproduce the rendered diff and no turn prompt exceeds the
  budget;
* §11:3 — a hunk, or a hunkless entry, that cannot fit fails before any turn;
* §11:4 — any failed turn, unproven turn, or moved checkout records nothing;
* §11:5 — on the bypass path every turn is a cold bypass invocation;
* §11:6 — the verdict turn carries every part message verbatim, and drops
  re-injected dispositions, never part messages, when the budget requires it.

Driven with the shared fake ``codex`` (``_fake_codex``), which numbers each
invocation and keeps its argv and prompt under ``FAKE_CODEX_STATE_DIR``, so no
test contacts the service.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _fake_codex import (
    SCRIPT,
    artifact_for,
    bash,
    install_fake_codex,
    require_artifact,
    review_env,
    run_review,
)
from _repo_template import seed_repo

_GIT = shutil.which("git")

#: ADR-0331 §3:1.
TURN_BUDGET = 240_000

#: The driver's pinned `_diff_opts`, so a test renders the diff the round reads.
_DIFF_OPTS = (
    "-c",
    "core.quotePath=false",
    "-c",
    "color.ui=false",
    "-c",
    "diff.renames=true",
    "-c",
    "diff.renameLimit=4000",
    "-c",
    "diff.algorithm=myers",
    "-c",
    "diff.context=3",
    "-c",
    "diff.interHunkContext=0",
    "-c",
    "diff.indentHeuristic=true",
    "-c",
    "diff.noprefix=false",
    "-c",
    "diff.mnemonicPrefix=false",
)
_DIFF_FLAGS = ("--no-color", "--ignore-submodules=none", "--no-ext-diff", "--no-textconv")

#: The ADR-0020 §1 prose qualification, as a single-turn round has always sent it.
_PROSE = """In the prose files above, a fenced code block is by default **illustrative**: an
example shown to a human reader, not a program this repository runs, ships, or
tests. Judge such a block on whether it would **mislead the reader who follows
it** — a command that does not work, a wrong path or flag, a claim the
repository contradicts. Do **not** judge it for runtime correctness, error
handling, edge cases, concurrency, or test coverage, and do not ask for tests
on it. Findings of that kind on an illustrative snippet are noise; drop them.

**This exemption does not extend to a normative snippet.** Where a fenced block
*states a contract the repository will implement against* — a Protocol or type
definition, an interface signature, a schema, a required file format or
provenance line, a rule stated as the decision itself — the snippet **is** the
decision, and its internal validity is the subject of the review. Judge it as
strictly as you would the same text in a source file: correctness, internal
consistency, completeness, and whether an implementation could satisfy it.
ADR-0016 defines the `ToolRegistry` Protocol in exactly such a block.

Decide this **per block, not per file**: one document can carry both kinds, and
which one a block is depends on whether something is meant to be built against
it. If a block's status is genuinely ambiguous, review it as normative and say
that you did.
"""

#: The header mechanism (b) puts above a re-injected snapshot.
_INJECTION_HEADER = (
    "## Prior findings of THIS review (re-injected — the live session was unavailable)\n"
    """
You have already reviewed earlier states of this same change in this review
loop. Below are the findings you raised and their current disposition. Do NOT
blindly re-raise a finding marked retired or already answered — engage it or
leave it retired. You MAY re-raise a finding you still hold after reading the
history; that is a deliberate, informed signal, not noise.

"""
)


def _git(repo: Path, *args: str) -> str:
    assert _GIT is not None
    return subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _git_bytes(repo: Path, *args: str) -> bytes:
    assert _GIT is not None
    return subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, *args], cwd=repo, check=True, capture_output=True
    ).stdout


def _init_repo(repo: Path, rubric: str = "# rubric\n") -> None:
    """A repository on `main` with a rubric, then a `feature` branch to change."""
    repo.mkdir()
    seed_repo(repo)
    (repo / "docs" / "review").mkdir(parents=True)
    (repo / "docs" / "review" / "adversarial.md").write_text(rubric)
    (repo / ".gitignore").write_text(".review/\n")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "feature")


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


def _filler(lines: int, tag: str) -> str:
    """Distinct lines of about sixty bytes, so a diff of them is predictable."""
    return "".join(
        f"{tag} line {i:06d} of filler text, long enough to matter\n" for i in range(lines)
    )


def _build_two_part_change(repo: Path) -> None:
    """Two new files that each fit a part but not together: a two-part round."""
    _init_repo(repo)
    (repo / "one.txt").write_text(_filler(2200, "one"))
    (repo / "two.txt").write_text(_filler(2200, "two"))
    _commit_all(repo, "two big files")


def _build_large_change(repo: Path) -> None:
    """A change over the budget carrying every shape of file entry git renders.

    One file is too large for any part and is split between its hunks; the rest
    are small entries of each kind — a binary change, a pure rename, a mode-only
    change, a type change, a deletion, prose, and awkward paths.
    """
    _init_repo(repo)
    big = [f"line {i:05d} of the big file, which is long enough to matter\n" for i in range(9000)]
    (repo / "split").mkdir()
    (repo / "split" / "big.py").write_text("".join(big))
    (repo / "old_name.txt").write_text(_filler(40, "rename"))
    (repo / "run.sh").write_text("echo run\n")
    (repo / "blob.bin").write_bytes(b"\x00\x01binary")
    (repo / "gone.txt").write_text("going\n")
    (repo / "link").symlink_to("base.txt")
    _commit_all(repo, "seed the entries")
    for i in range(0, len(big), 10):
        big[i] = f"line {i:05d} CHANGED on the feature branch, to make one hunk here\n"
    (repo / "split" / "big.py").write_text("".join(big))
    _git(repo, "mv", "old_name.txt", "new_name.txt")
    (repo / "run.sh").chmod(0o755)
    (repo / "blob.bin").write_bytes(b"\x00\x02binary")
    (repo / "gone.txt").unlink()
    (repo / "link").unlink()
    (repo / "link").write_text("a file now\n")
    (repo / "docs" / "notes.md").write_text("# Notes\n\nprose\n")
    (repo / "sp ace.txt").write_text("a path with a space\n")
    (repo / "café.txt").write_text("non-ascii path\n")
    (repo / "after.txt").write_text(_filler(300, "after"))
    _commit_all(repo, "the large change")
    # The base the review measures against is `main`, so the seed commit must
    # be part of it: move `main` up to the seed and leave the change on top.
    _git(repo, "branch", "-f", "main", "HEAD^")


def _rendered_diff(repo: Path, base: str = "main") -> bytes:
    """The rendered diff as the round holds it: `$(git diff …)` plus one newline."""
    merge_base = _git(repo, "merge-base", base, "HEAD")
    raw = _git_bytes(repo, *_DIFF_OPTS, "diff", *_DIFF_FLAGS, f"{merge_base}...HEAD")
    return raw.rstrip(b"\n") + b"\n"


def _changed_paths(repo: Path, base: str = "main") -> list[str]:
    merge_base = _git(repo, "merge-base", base, "HEAD")
    listing = _git_bytes(
        repo, *_DIFF_OPTS, "diff", *_DIFF_FLAGS, "-z", "--name-only", f"{merge_base}...HEAD"
    )
    return [p.decode() for p in listing.split(b"\0") if p]


def _bash_quote(text: str) -> str:
    """Bash's own `printf %q`, which the driver uses for a control-character path."""
    return subprocess.run(  # noqa: S603  # resolved bash, constant script
        [bash(), "-c", 'printf %q "$1"', "_", text], check=True, capture_output=True, text=True
    ).stdout


def _render_path(path: str) -> str:
    if any(c in path for c in "\n\t\r"):
        return f"- `{_bash_quote(path)}` (control characters escaped)\n"
    return f"- `{path}`\n"


def _expected_single_prompt(repo: Path, rubric: str, inject: str = "") -> bytes:
    """A single-turn round's prompt, rebuilt independently of the driver.

    This is the format `_write_prompt` produced before ADR-0331, written out by
    hand, so a change to what an under-budget round sends fails here (§4, §11:1).
    """
    head = _git(repo, "rev-parse", "HEAD")
    paths = _changed_paths(repo)
    prose = [p for p in paths if p.endswith((".md", ".rst"))]
    other = [p for p in paths if not p.endswith((".md", ".rst"))]
    text = f"{inject}\n" if inject else ""
    text += rubric + "\n"
    text += "## Change under review\n\n"
    text += f"Review ONLY the committed diff below ({head} vs main). You may read full\n"
    text += "files in the repo for context, but do not modify anything. Output exactly the\n"
    text += "ranked findings and verdict from docs/review/guide.md.\n\n"
    text += "### What these paths are\n\n"
    if prose:
        text += "**Prose** — documentation read by a human operator, not executed or tested:\n\n"
        text += "".join(_render_path(p) for p in prose) + "\n"
    if other:
        text += "**Code, scripts, config, and tests** — machine-consumed, and judged as such:\n\n"
        text += "".join(_render_path(p) for p in other) + "\n"
    if prose:
        text += _PROSE + "\n"
    return text.encode() + b"```diff\n" + _rendered_diff(repo) + b"```\n"


def _plan(repo: Path, tmp_path: Path, persona: str = "adversarial") -> str:
    """`--plan`'s report, asserting it succeeded."""
    install_fake_codex(tmp_path / "bin")
    result = subprocess.run(  # noqa: S603  # resolved bash, in-repo script, test env
        [bash(), str(SCRIPT), "--plan", persona, "main"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=review_env(tmp_path, FAKE_CODEX_STATE_DIR=str(tmp_path / "plan-state")),
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _part_count(plan: str) -> int:
    match = re.search(r"in (\d+) part turn", plan)
    assert match, plan
    return int(match.group(1))


def _invocations(state: Path) -> int:
    count = state / "count"
    return int(count.read_text()) if count.exists() else 0


def _prompt(state: Path, n: int) -> bytes:
    return (state / f"prompt-{n}.md").read_bytes()


def _args(state: Path, n: int) -> list[str]:
    return (state / f"args-{n}").read_text().splitlines()


def _part_diff(prompt: bytes) -> bytes:
    """The verbatim part a part turn's prompt carries, after its preamble."""
    opening = b"```diff\n"
    start = prompt.index(opening, prompt.index(b"### What these paths are")) + len(opening)
    assert prompt.endswith(b"```\n")
    return prompt[start : -len(b"```\n")]


def _entries(diff: bytes) -> list[bytes]:
    """A rendered diff cut at each `diff --git` line, every byte kept."""
    lines = diff.splitlines(keepends=True)
    entries: list[bytes] = []
    for line in lines:
        if line.startswith(b"diff --git ") or not entries:
            entries.append(line)
        else:
            entries[-1] += line
    return entries


def _header(entry: bytes) -> bytes:
    """An entry's header lines: everything before its first hunk."""
    header = b""
    for line in entry.splitlines(keepends=True):
        if line.startswith(b"@@ "):
            break
        header += line
    return header


def _reassemble(parts: list[bytes]) -> bytes:
    """The parts concatenated with each continued entry's repeated header removed.

    A part that opens by continuing the previous part's last entry repeats that
    entry's header lines exactly (§5:3), and no two different entries share a
    whole header — it carries the paths and the blob ids — so equality is the
    test for a continuation.
    """
    out = b""
    previous: bytes | None = None
    for part in parts:
        entries = _entries(part)
        if previous is not None and _header(entries[0]) == previous:
            entries[0] = entries[0][len(previous) :]
        out += b"".join(entries)
        previous = _header(_entries(part)[-1])
    return out


def _round_state(repo: Path) -> dict[str, list[Path]]:
    review = repo / ".review"
    return {
        "artifacts": sorted(review.glob("*.md")),
        "threads": sorted((review / "session").glob("*.thread")),
        "snapshots": sorted((review / "dispositions").glob("*.md")),
        "parts": sorted((review / "parts").glob("*")),
    }


# --- §4, §11:1: under the budget, nothing changes -----------------------------


@pytest.mark.parametrize("path", ["persistent", "bypass"])
def test_an_under_budget_round_sends_todays_prompt_byte_for_byte(tmp_path: Path, path: str) -> None:
    """The single-turn prompt is exactly the pre-ADR-0331 format (§4, §11:1)."""
    repo = tmp_path / "repo"
    rubric = "# rubric\nbe adversarial\n"
    _init_repo(repo, rubric)
    (repo / "docs" / "x.md").write_text("# t\n```py\nx\n```\n")
    (repo / "src").mkdir()
    (repo / "src" / "b.py").write_text("y = 2\n")
    (repo / "café.rst").write_text("é\n")
    (repo / "we\tird.txt").write_text("t\n")
    _commit_all(repo, "change")
    state = tmp_path / "state"
    extra = {"GITHUB_ACTIONS": "true"} if path == "bypass" else {}

    run_review(repo, tmp_path, env={"FAKE_CODEX_STATE_DIR": str(state), **extra})

    assert _invocations(state) == 1
    assert _prompt(state, 1) == _expected_single_prompt(repo, rubric)
    assert not (repo / ".review" / "parts").exists()


def test_an_under_budget_round_with_reinjected_findings_is_unchanged(tmp_path: Path) -> None:
    """Mechanism (b) on a single-turn round keeps its place and its budget (§4)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "f.txt").write_text("one\n")
    _commit_all(repo, "round 1")
    run_review(repo, tmp_path, FAKE_CODEX_REVIEW="1. **major** finding A\nBLOCK\n")
    (repo / "f.txt").write_text("two\n")
    _commit_all(repo, "round 2")
    snapshot = next((repo / ".review" / "dispositions").glob("*.md")).read_text()
    state = tmp_path / "state"

    run_review(repo, tmp_path, FAKE_CODEX_RESUME_FAIL="1", FAKE_CODEX_STATE_DIR=str(state))

    assert _invocations(state) == 2  # the failed resume, then the fresh start
    expected = _expected_single_prompt(repo, "# rubric\n", _INJECTION_HEADER + snapshot)
    assert _prompt(state, 2) == expected


def _calibrated_boundary_repo(repo: Path, tmp_path: Path, over: int) -> None:
    """A two-file change whose single-turn prompt is exactly `TURN_BUDGET + over`.

    Lengthening the first line of a new file lengthens the prompt by exactly as
    many bytes, so one `--plan` measures the gap and one amend closes it.
    """
    _init_repo(repo)
    second = _filler(1800, "second")
    (repo / "a.txt").write_text("x\n" + _filler(1800, "first"))
    (repo / "b.txt").write_text(second)
    _commit_all(repo, "near the budget")
    found = re.search(r"its prompt is (\d+) bytes", _plan(repo, tmp_path))
    assert found, "the plan names the single-turn prompt's size"
    gap = TURN_BUDGET + over - int(found.group(1))
    assert gap > 0, "the filler must start under the target"
    (repo / "a.txt").write_text("x" * (1 + gap) + "\n" + _filler(1800, "first"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--amend", "--no-edit")


def test_a_prompt_exactly_at_the_budget_is_one_turn(tmp_path: Path) -> None:
    """Fitting is `<=`: a prompt of exactly 240,000 bytes is a single-turn round."""
    repo = tmp_path / "repo"
    _calibrated_boundary_repo(repo, tmp_path, over=0)
    assert "single-turn: its prompt is 240000 bytes" in _plan(repo, tmp_path)
    state = tmp_path / "state"

    run_review(repo, tmp_path, FAKE_CODEX_STATE_DIR=str(state))

    assert _invocations(state) == 1
    assert len(_prompt(state, 1)) == TURN_BUDGET


def test_one_byte_over_the_budget_is_a_parted_round(tmp_path: Path) -> None:
    """At 240,001 bytes the round reads its diff in parts (§5:1)."""
    repo = tmp_path / "repo"
    _calibrated_boundary_repo(repo, tmp_path, over=1)
    plan = _plan(repo, tmp_path)
    assert "as one turn its prompt would be 240001 bytes" in plan
    parts = _part_count(plan)
    state = tmp_path / "state"

    result = run_review(repo, tmp_path, FAKE_CODEX_STATE_DIR=str(state))

    assert parts == 2
    assert _invocations(state) == parts + 1
    assert f"as a parted round: {parts} part turns" in result.stderr


# --- §5, §11:2: the parts, and the turns that read them ------------------------


def test_a_parted_round_reads_every_hunk_once_within_the_budget(tmp_path: Path) -> None:
    """The parts reproduce the rendered diff and every turn fits (§5, §6, §11:2)."""
    repo = tmp_path / "repo"
    _build_large_change(repo)
    parts = _part_count(_plan(repo, tmp_path))
    assert parts >= 3, "the fixture must exercise packing and a split entry"
    state = tmp_path / "state"
    state.mkdir()
    messages = [f"1. **minor** finding from part {i}, unique-{i}\n" for i in range(1, parts + 1)]
    for i, message in enumerate(messages, start=1):
        (state / f"review-{i}.md").write_text(message)
    verdict = (
        "Part findings no longer held\n\n- None.\n\n"
        "1. **minor** the kept finding\nAPPROVE WITH NITS\n"
    )
    (state / f"review-{parts + 1}.md").write_text(verdict)

    result = run_review(repo, tmp_path, FAKE_CODEX_STATE_DIR=str(state))

    # k part turns and one verdict turn, every one of them within the budget.
    assert _invocations(state) == parts + 1
    for n in range(1, parts + 2):
        assert len(_prompt(state, n)) <= TURN_BUDGET, f"turn {n} is over the budget"
    # Every hunk exactly once: the parts, less repeated headers, ARE the diff.
    pieces = [_part_diff(_prompt(state, n)) for n in range(1, parts + 1)]
    assert _reassemble(pieces) == _rendered_diff(repo)
    # The split entry really was split, and each of its pieces opens with its header.
    big_header = _header(next(e for e in _entries(_rendered_diff(repo)) if b"split/big.py" in e))
    carrying = [p for p in pieces if big_header in p]
    assert len(carrying) >= 2
    # Each part turn says which part it is, and how to read the others.
    base, head = _git(repo, "merge-base", "main", "HEAD"), _git(repo, "rev-parse", "HEAD")
    for n in range(1, parts + 1):
        text = _prompt(state, n).decode()
        assert f"part {n} of {parts}" in text
        assert f"git diff {base} {head} -- <path>" in text
        assert "NO verdict line" in text
    # The verdict turn carries every part message verbatim, in part order.
    final = _prompt(state, parts + 1).decode()
    positions = [final.index(message) for message in messages]
    assert positions == sorted(positions)
    assert "Part findings no longer held" in final
    # One conversation: a fresh read-only start, then resumes of that thread.
    assert "resume" not in _args(state, 1)
    for n in range(2, parts + 2):
        assert _args(state, n)[:2] == ["exec", "resume"]
    # One artifact for the round — the verdict turn's message — and one round.
    sha = _git(repo, "rev-parse", "HEAD")
    artifact = require_artifact(repo, sha)
    assert artifact.read_text().split("\n", 1)[1] == verdict
    assert " round=1 " in artifact.read_text().splitlines()[0]
    assert len(_round_state(repo)["artifacts"]) == 1
    # The part messages are kept beside it, under its name (§5:11).
    kept = repo / ".review" / "parts" / artifact.stem
    assert sorted(p.read_text() for p in kept.iterdir()) == sorted(messages)
    assert f"{parts} part turns and one verdict turn" in result.stderr


def test_every_changed_path_is_listed_once_with_its_part(tmp_path: Path) -> None:
    """The preamble marks each path by the part, or parts, carrying it (§5:6)."""
    repo = tmp_path / "repo"
    _build_large_change(repo)
    parts = _part_count(_plan(repo, tmp_path))
    state = tmp_path / "state"

    run_review(repo, tmp_path, FAKE_CODEX_STATE_DIR=str(state))

    first = _prompt(state, 1).decode()
    preamble = first[first.index("### What these paths are") : first.index("```diff\n")]
    for path in _changed_paths(repo):
        assert preamble.count(f"- `{path}` (part") == 1, path
    big = re.search(r"- `split/big\.py` \(parts (\d+)-(\d+)\)", preamble)
    assert big, preamble
    assert int(big.group(1)) < int(big.group(2)) <= parts
    # Every part turn carries the same marked preamble for the whole change.
    for n in range(2, parts + 1):
        text = _prompt(state, n).decode()
        assert text[text.index("### What these paths are") : text.index("```diff\n")] == preamble


def test_every_persona_reads_the_same_parts(tmp_path: Path) -> None:
    """The parts depend on the diff and the budget, not the persona's rubric (§5:5)."""
    repo = tmp_path / "repo"
    _build_large_change(repo)
    (repo / "docs" / "review" / "architecture.md").write_text("# a longer rubric\n" * 600)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--amend", "--no-edit")
    pieces = {}
    for persona in ("adversarial", "architecture"):
        state = tmp_path / f"state-{persona}"
        run_review(repo, tmp_path, persona, FAKE_CODEX_STATE_DIR=str(state))
        count = _invocations(state)
        pieces[persona] = [_part_diff(_prompt(state, n)) for n in range(1, count)]

    assert pieces["adversarial"] == pieces["architecture"]
    sha = _git(repo, "rev-parse", "HEAD")
    require_artifact(repo, sha, "adversarial")
    require_artifact(repo, sha, "architecture")


# --- §5:7, §11:3: what cannot fit fails before any turn ------------------------


def _assert_nothing_recorded(repo: Path, state: Path, sha: str) -> None:
    recorded = _round_state(repo)
    assert artifact_for(repo, sha) is None
    assert recorded["artifacts"] == []
    assert recorded["threads"] == []
    assert recorded["snapshots"] == []
    assert recorded["parts"] == []
    del state  # the caller asserts on invocations, which differ by case


def test_a_hunk_too_large_for_any_part_fails_before_any_turn(tmp_path: Path) -> None:
    """One hunk that cannot fit beside the fixed content refuses the round (§5:7)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "huge.txt").write_text(_filler(4500, "huge"))
    _commit_all(repo, "one enormous hunk")
    state = tmp_path / "state"

    result = run_review(repo, tmp_path, check=False, FAKE_CODEX_STATE_DIR=str(state))

    assert result.returncode == 1
    assert "refusing to start a parted round" in result.stderr
    assert "does not fit: the hunk @@ -0,0 +1,4500 @@ of diff --git a/huge.txt" in result.stderr
    assert re.search(r"fixed content: \d+ bytes", result.stderr)
    assert "turn budget:   240000 bytes" in result.stderr
    assert _invocations(state) == 0
    _assert_nothing_recorded(repo, state, _git(repo, "rev-parse", "HEAD"))


def test_fixed_content_with_no_room_for_a_hunkless_entry_fails_before_any_turn(
    tmp_path: Path,
) -> None:
    """Fixed content that leaves no room for an entry without hunks refuses (§5:7)."""
    repo = tmp_path / "repo"
    _init_repo(repo, "# rubric\n" + "r" * 239_800 + "\n")
    (repo / "blob.bin").write_bytes(b"\x00\x01binary")
    _commit_all(repo, "a binary file, which renders with no hunk")
    state = tmp_path / "state"

    result = run_review(repo, tmp_path, check=False, FAKE_CODEX_STATE_DIR=str(state))

    assert result.returncode == 1
    assert "does not fit: the file entry diff --git a/blob.bin b/blob.bin (it has no hunk)" in (
        result.stderr
    )
    assert _invocations(state) == 0
    _assert_nothing_recorded(repo, state, _git(repo, "rev-parse", "HEAD"))


# --- §6:7, §6:8, §11:4: a failed turn records nothing --------------------------


@pytest.mark.parametrize(
    ("at", "knobs", "says", "stops_at"),
    [
        pytest.param(
            1,
            {"FAKE_CODEX_START_FAIL": "1"},
            "(the fresh read-only session, part 1 of 2) exited 1",
            1,
            id="start",
        ),
        pytest.param(
            2, {"FAKE_CODEX_RESUME_FAIL": "1"}, ", part 2 of 2) exited 1", 2, id="part-2-fails"
        ),
        pytest.param(
            3,
            {"FAKE_CODEX_RESUME_FAIL": "1"},
            ", the verdict turn) exited 1",
            3,
            id="verdict-fails",
        ),
        pytest.param(
            2,
            {"FAKE_CODEX_FORCE_SANDBOX": "danger-full-access"},
            "could not prove part 2 of 2 of this parted round ran read-only",
            2,
            id="part-2-unproven",
        ),
        pytest.param(
            3,
            {"FAKE_CODEX_FORCE_SANDBOX": "danger-full-access"},
            "could not prove the verdict turn of this parted round ran read-only",
            3,
            id="verdict-unproven",
        ),
        pytest.param(
            2,
            {"FAKE_CODEX_TURN_FAILED": "1"},
            "empty message for part 2 of 2",
            2,
            id="part-2-empty",
        ),
        pytest.param(
            1,
            {"FAKE_CODEX_PRE_CMD": "git commit -q --allow-empty -m moved"},
            "the checkout changed during part 1 of 2",
            1,
            id="head-moves",
        ),
        pytest.param(
            2,
            {"FAKE_CODEX_PRE_CMD": "touch stray.txt"},
            "the checkout changed during part 2 of 2",
            2,
            id="tree-dirtied",
        ),
    ],
)
def test_a_parted_round_records_nothing_when_a_turn_fails(
    tmp_path: Path, at: int, knobs: dict[str, str], says: str, stops_at: int
) -> None:
    """Any turn that fails, is unproven, or sees the checkout move fails the round."""
    repo = tmp_path / "repo"
    _build_two_part_change(repo)
    assert _part_count(_plan(repo, tmp_path)) == 2
    sha = _git(repo, "rev-parse", "HEAD")
    state = tmp_path / "state"

    result = run_review(
        repo,
        tmp_path,
        check=False,
        env={"FAKE_CODEX_STATE_DIR": str(state), "FAKE_CODEX_ONLY_AT": str(at), **knobs},
    )

    assert result.returncode != 0
    assert says in result.stderr
    assert _invocations(state) == stops_at, "no turn runs after the one that failed"
    _assert_nothing_recorded(repo, state, sha)


def test_a_part_turn_that_cannot_resume_its_own_thread_does_not_degrade(tmp_path: Path) -> None:
    """Only the loop's recorded thread degrades; losing this round's own is a failure."""
    repo = tmp_path / "repo"
    _build_two_part_change(repo)
    state = tmp_path / "state"

    result = run_review(
        repo,
        tmp_path,
        check=False,
        FAKE_CODEX_STATE_DIR=str(state),
        FAKE_CODEX_ONLY_AT="2",
        FAKE_CODEX_RESUME_FAIL="1",
    )

    assert result.returncode != 0
    assert "resume unavailable" not in result.stderr
    assert _invocations(state) == 2


# --- §8:2, §11:5: the bypass path ---------------------------------------------


def test_a_bypass_parted_round_makes_every_turn_cold(tmp_path: Path) -> None:
    """On the bypass path each turn is a cold bypass invocation, unproven (§8:2)."""
    repo = tmp_path / "repo"
    _build_two_part_change(repo)
    state = tmp_path / "state"

    run_review(repo, tmp_path, GITHUB_ACTIONS="true", FAKE_CODEX_STATE_DIR=str(state))

    assert _invocations(state) == 3
    for n in (1, 2, 3):
        args = _args(state, n)
        assert "--dangerously-bypass-approvals-and-sandbox" in args
        assert "resume" not in args
        assert "--json" not in args
    artifact = require_artifact(repo, _git(repo, "rev-parse", "HEAD"))
    header = artifact.read_text().splitlines()[0]
    assert "thread_id= " in header, "the bypass path records no thread"
    assert "loop_id= " in header
    assert not (repo / ".review" / "session").exists()
    assert len(list((repo / ".review" / "parts" / artifact.stem).iterdir())) == 2


# --- §6, §11:6: the verdict turn ----------------------------------------------


def _two_round_loop(repo: Path, tmp_path: Path, round_one_review: str) -> None:
    """Round 1: a small single-turn round recording a finding. Then a large change."""
    _init_repo(repo)
    (repo / "f.txt").write_text("one\n")
    _commit_all(repo, "round 1")
    state = tmp_path / "state-1"
    state.mkdir()
    (state / "review-1.md").write_text(round_one_review)
    run_review(repo, tmp_path, FAKE_CODEX_STATE_DIR=str(state), FAKE_CODEX_THREAD_ID="thread-1")
    (repo / "one.txt").write_text(_filler(2200, "one"))
    (repo / "two.txt").write_text(_filler(2200, "two"))
    _commit_all(repo, "round 2: over the budget")


def test_reinjected_findings_ride_in_the_verdict_turn_only(tmp_path: Path) -> None:
    """A degraded parted round re-injects in the verdict turn, not the parts (§6:3)."""
    repo = tmp_path / "repo"
    _two_round_loop(repo, tmp_path, "1. **major** finding A from round one\nBLOCK\n")
    state = tmp_path / "state-2"

    result = run_review(
        repo,
        tmp_path,
        FAKE_CODEX_STATE_DIR=str(state),
        FAKE_CODEX_ONLY_AT="1",
        FAKE_CODEX_RESUME_FAIL="1",
        FAKE_CODEX_THREAD_ID="thread-2",
    )

    assert "resume unavailable" in result.stderr
    # The failed resume, a fresh start for part 1, part 2 and the verdict turn.
    assert _invocations(state) == 4
    assert _args(state, 1)[:3] == ["exec", "resume", "thread-1"]
    assert "resume" not in _args(state, 2)
    assert _args(state, 3)[:3] == ["exec", "resume", "thread-2"]
    for n in (2, 3):
        assert b"Prior findings of THIS review" not in _prompt(state, n)
    verdict = _prompt(state, 4).decode()
    assert verdict.startswith("## Prior findings of THIS review")
    assert "finding A from round one" in verdict


def test_a_resumed_parted_round_reinjects_nothing(tmp_path: Path) -> None:
    """The warm session carries the history, so mechanism (b) stays out (§6:3)."""
    repo = tmp_path / "repo"
    _two_round_loop(repo, tmp_path, "1. **major** finding A from round one\nBLOCK\n")
    state = tmp_path / "state-2"

    run_review(repo, tmp_path, FAKE_CODEX_STATE_DIR=str(state))

    assert _invocations(state) == 3
    assert all(_args(state, n)[:3] == ["exec", "resume", "thread-1"] for n in (1, 2, 3))
    assert b"Prior findings of THIS review" not in _prompt(state, 3)


def test_findings_too_large_for_the_verdict_turn_are_dropped_whole(tmp_path: Path) -> None:
    """Re-injected dispositions that do not fit are dropped, never the parts (§6:3)."""
    repo = tmp_path / "repo"
    _two_round_loop(repo, tmp_path, "1. **major** " + "a very long finding " * 12_000 + "\nBLOCK\n")
    state = tmp_path / "state-2"
    state.mkdir()
    (state / "review-2.md").write_text("PART-ONE-MESSAGE\n")
    (state / "review-3.md").write_text("PART-TWO-MESSAGE\n")

    result = run_review(
        repo,
        tmp_path,
        FAKE_CODEX_STATE_DIR=str(state),
        FAKE_CODEX_ONLY_AT="1",
        FAKE_CODEX_RESUME_FAIL="1",
    )

    assert "dropping them whole" in result.stderr
    verdict = _prompt(state, 4).decode()
    assert "Prior findings of THIS review" not in verdict
    assert "PART-ONE-MESSAGE" in verdict
    assert "PART-TWO-MESSAGE" in verdict
    assert len(verdict.encode()) <= TURN_BUDGET
    require_artifact(repo, _git(repo, "rev-parse", "HEAD"))


def test_part_messages_too_large_for_the_verdict_turn_fail_the_round(tmp_path: Path) -> None:
    """No part message is ever cut: if they do not fit, the round fails (§6:2)."""
    repo = tmp_path / "repo"
    _build_two_part_change(repo)
    state = tmp_path / "state"
    state.mkdir()
    (state / "review-1.md").write_text("1. **minor** " + "x" * 125_000 + "\n")
    (state / "review-2.md").write_text("1. **minor** " + "y" * 125_000 + "\n")
    sha = _git(repo, "rev-parse", "HEAD")

    result = run_review(repo, tmp_path, check=False, FAKE_CODEX_STATE_DIR=str(state))

    assert result.returncode != 0
    assert "refusing to run the verdict turn" in result.stderr
    assert _invocations(state) == 2, "the verdict turn is never invoked"
    _assert_nothing_recorded(repo, state, sha)


# --- `--plan` ------------------------------------------------------------------


def test_plan_reports_a_single_turn_round_and_touches_nothing(tmp_path: Path) -> None:
    """`--plan` answers without calling Codex or writing under `.review/`."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "f.txt").write_text("small\n")
    _commit_all(repo, "small")

    plan = _plan(repo, tmp_path)

    assert "single-turn: its prompt is" in plan
    assert _invocations(tmp_path / "plan-state") == 0
    assert not (repo / ".review").exists()


def test_plan_reports_the_parts_of_a_parted_round(tmp_path: Path) -> None:
    """`--plan` lists each part turn prompt's size and the largest (ADR-0331 §8:3)."""
    repo = tmp_path / "repo"
    _build_two_part_change(repo)

    plan = _plan(repo, tmp_path)

    assert _part_count(plan) == 2
    sizes = [int(m) for m in re.findall(r"part +\d+/\d+ +(\d+)-byte turn prompt", plan)]
    assert len(sizes) == 2
    assert all(size <= TURN_BUDGET for size in sizes)
    assert f"a {max(sizes)}-byte turn prompt" in plan
    assert re.search(r"fixed content +\d+ bytes", plan)
    assert _invocations(tmp_path / "plan-state") == 0
    assert not (repo / ".review").exists()


# --- §5:11: a re-review never pairs a verdict with another attempt's parts -----

_REAL_MV = shutil.which("mv") or "/bin/mv"


def _install_interrupting_mv(bin_dir: Path, boundary: str) -> None:
    """An `mv` that SIGKILLs the round at one rename, standing in for an interruption.

    It sits ahead of the real one on `PATH`, passes every other rename through,
    and kills its parent — the round — at the boundary named:

    * ``parts`` — just before this round's part messages are renamed into place;
    * ``artifact-before`` — just before this round's artifact is renamed in;
    * ``artifact-after`` — just after it has been.
    """
    artifact_rename = '[[ "$dest" == */.review/*.md && "$src" == *.md.partial.* ]]'
    condition = {
        "parts": '[[ "$dest" == */.review/parts/* && "$src" == *.partial.* ]]',
        "artifact-before": artifact_rename,
        "artifact-after": artifact_rename,
    }[boundary]
    if boundary == "artifact-after":
        action = f'"{_REAL_MV}" "$@"; kill -9 "$PPID"; exit 0'
    else:
        action = 'kill -9 "$PPID"; exit 0'
    script = (
        "#!/usr/bin/env bash\n"
        'src="${@: -2:1}"\n'
        'dest="${@: -1}"\n'
        f"if {condition}; then\n"
        f"    {action}\n"
        "fi\n"
        f'exec "{_REAL_MV}" "$@"\n'
    )
    bin_dir.mkdir(parents=True, exist_ok=True)
    mv = bin_dir / "mv"
    mv.write_text(script)
    mv.chmod(0o755)


def _recorded_round(state: Path, label: str) -> None:
    """Steer a two-part round so its messages and verdict all carry `label`."""
    state.mkdir()
    (state / "review-1.md").write_text(f"{label} part one\n")
    (state / "review-2.md").write_text(f"{label} part two\n")
    (state / "review-3.md").write_text(f"{label} verdict body\n\nAPPROVE\n")


@pytest.mark.parametrize(
    ("boundary", "survives"),
    [("parts", None), ("artifact-before", None), ("artifact-after", "SECOND")],
)
def test_an_interrupted_rereview_never_mispairs_artifact_and_parts(
    tmp_path: Path, boundary: str, survives: str | None
) -> None:
    """Interrupted anywhere, a re-review leaves a matching pair or no artifact.

    A re-review of identical content reuses the artifact's name and its parts
    directory (ADR-0027 §6), and the two cannot be renamed as one. Whatever the
    interruption, `ship` must never find one attempt's verdict beside another
    attempt's part messages.
    """
    repo = tmp_path / "repo"
    _build_two_part_change(repo)
    sha = _git(repo, "rev-parse", "HEAD")
    first = tmp_path / "state-1"
    _recorded_round(first, "FIRST")
    run_review(repo, tmp_path, FAKE_CODEX_STATE_DIR=str(first))
    stem = require_artifact(repo, sha).stem
    second = tmp_path / "state-2"
    _recorded_round(second, "SECOND")
    install_fake_codex(tmp_path / "bin")
    _install_interrupting_mv(tmp_path / "bin", boundary)

    result = run_review(repo, tmp_path, check=False, FAKE_CODEX_STATE_DIR=str(second))

    assert result.returncode != 0, "the round was interrupted"
    artifact = artifact_for(repo, sha)
    if survives is None:
        assert artifact is None, "the earlier artifact is withdrawn before its parts change"
        return
    assert artifact is not None
    assert f"{survives} verdict body" in artifact.read_text()
    kept = repo / ".review" / "parts" / stem
    assert sorted(p.read_text() for p in kept.iterdir()) == [
        f"{survives} part one\n",
        f"{survives} part two\n",
    ]
