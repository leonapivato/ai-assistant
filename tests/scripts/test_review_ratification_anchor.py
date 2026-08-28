"""The reviewer and ``ship`` anchor a ratification flip on the same commit.

ADR-0165 §3 is normative that where a PR's ``HEAD`` is a ratification flip,
"ADR-0027 §2's acceptance loop is evaluated against ``HEAD``'s parent — its tree
and its patch identity — and paths (a) and (b) then run exactly as written".
``scripts/ship.sh`` has done that since the exemption landed. The producer did
not: ``scripts/codex-review.sh`` reviewed and recorded ``HEAD``, so a round that
was genuinely owed after the flip landed on a tree the recogniser is required to
look past — the round covered strictly more content than the rule asks for and
``ship`` refused it anyway (issue #1672, PR #1660).

The order that reaches it is the documented one, not an exotic one: ``just
adr-ratify`` runs before ``just ship``, so ``HEAD`` is already the flip when the
base moves, and every ADR merge landing on the base breaches ADR-0027 §3's floor
and genuinely owes the round. The last test here drives that whole sequence
through both real scripts, because the defect existed in neither of them alone.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _fake_codex import require_artifact, run_review
from test_codex_review_start_wait import _env, _run
from test_ship import _fake_gh, _git, _run_ship

_RATIFY = Path(__file__).parents[2] / "scripts" / "adr_ratify.py"
_GIT = shutil.which("git")

_ADR_PATH = "docs/adr/0101-a-decision-worth-recording.md"
_PROPOSED = """\
# 101. A decision worth recording

- Status: Proposed
- Date: 2026-01-01

## Context

ADR-0101 exists because of something.

## Decision

ADR-0101 §1 rules.

## Consequences

Refs ADR-0101.
"""


def _ratify(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the real ``adr_ratify.py`` CLI inside ``repo``."""
    return subprocess.run(  # noqa: S603  # fixed argv, no shell
        [sys.executable, str(_RATIFY), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _adr_repo(tmp_path: Path) -> Path:
    """An ADR PR branch that both scripts can run in.

    ``ship`` needs a real ``origin`` to fetch the PR's base branch from;
    ``codex-review.sh`` needs the persona's rubric and a clean tree; and both
    resolve ``scripts/adr_ratify.py`` under the repository they run in, so the
    fixture carries a real copy rather than a stub — a stub would prove nothing
    about the shape actually being recognised.
    """
    assert _GIT is not None
    repo = tmp_path / "repo"
    origin = tmp_path / "origin.git"
    subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, "init", "-q", "--bare", "-b", "main", str(origin)], check=True
    )
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "docs" / "review").mkdir(parents=True)
    (repo / "docs" / "review" / "adversarial.md").write_text("# rubric\n")
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / "scripts").mkdir()
    shutil.copy(_RATIFY, repo / "scripts" / "adr_ratify.py")
    (repo / ".gitignore").write_text(".review/\n")
    (repo / "f.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "main")

    _git(repo, "checkout", "-qb", "feature")
    (repo / _ADR_PATH).write_text(_PROPOSED)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): draft the decision")
    return repo


def _land_an_adr_on_main(repo: Path) -> None:
    """Move the base into ADR-0027 §3's floor and rebase onto it.

    Every ADR merge does this to every lane behind it in the merge order, which
    is why issue #1672 calls the composition reachable rather than exotic.

    The landed decision names the path this PR's diff touches, so it binds under
    ADR-0209 §3's second test and the round is genuinely owed. That citation is
    load-bearing rather than decorative: since ADR-0209 a `docs/adr/**` base move
    the PR neither names nor is named by clears the floor, and this test needs an
    owed round to have anything to say about where the paid one is anchored.
    """
    _git(repo, "checkout", "-q", "main")
    (repo / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "adr" / "0100-something-else.md").write_text(
        _PROPOSED.replace("101", "100").replace("- Status: Proposed", "- Status: Accepted")
        + f"\nThis decision governs `{_ADR_PATH}`.\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): land another decision")
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "rebase", "-q", "main")


def test_a_round_on_a_flip_records_the_parents_tree(tmp_path: Path) -> None:
    """ADR-0165 §3: the parent's tree is the content coverage is judged over."""
    repo = _adr_repo(tmp_path)
    assert _ratify(repo, "ratify").returncode == 0
    flip = _git(repo, "rev-parse", "HEAD")
    parent_tree = _git(repo, "rev-parse", "HEAD~1^{tree}")

    result = run_review(repo, tmp_path, "adversarial", "main")

    assert result.returncode == 0, result.stderr
    assert "ratification flip" in result.stderr
    artifact = require_artifact(repo, flip)
    assert f"tree={parent_tree} " in artifact.read_text().splitlines()[0]


def test_the_reviewer_is_shown_the_parents_range(tmp_path: Path) -> None:
    """The `- Status: Accepted` line is the one line ADR-0165 §2 exempts.

    So it is not in the range the round reads: the reviewer is handed the
    decision text, which is what a reviewer could have judged differently.
    """
    repo = _adr_repo(tmp_path)
    assert _ratify(repo, "ratify").returncode == 0
    prompt_copy = tmp_path / "prompt.md"

    result = run_review(
        repo, tmp_path, "adversarial", "main", FAKE_CODEX_PROMPT_COPY=str(prompt_copy)
    )

    assert result.returncode == 0, result.stderr
    prompt = prompt_copy.read_text()
    assert "ADR-0101 §1 rules." in prompt
    assert "- Status: Accepted" not in prompt


def test_an_ordinary_head_is_still_reviewed_as_itself(tmp_path: Path) -> None:
    """The control: the re-anchoring is for one shape, not for ADR branches."""
    repo = _adr_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")

    result = run_review(repo, tmp_path, "adversarial", "main")

    assert result.returncode == 0, result.stderr
    assert "ratification flip" not in result.stderr
    artifact = require_artifact(repo, head)
    own_tree = _git(repo, "rev-parse", "HEAD^{tree}")
    assert f"tree={own_tree} " in artifact.read_text().splitlines()[0]


def test_the_round_owed_after_the_flip_satisfies_ship(tmp_path: Path) -> None:
    """Issue #1672 end to end, through both real scripts.

    Draft, review, ratify, then land an ADR on the base — which breaches
    ADR-0027 §3's floor, so the round is genuinely owed — and pay it. Before the
    producer was re-anchored, the artifact that round recorded named the flip's
    own tree, and ``ship`` (correctly, per ADR-0165 §3) looked for the parent's
    and refused.
    """
    repo = _adr_repo(tmp_path)
    drafted = _git(repo, "rev-parse", "HEAD")
    assert run_review(repo, tmp_path, "adversarial", "main").returncode == 0
    require_artifact(repo, drafted)
    assert _ratify(repo, "ratify").returncode == 0
    _land_an_adr_on_main(repo)
    _fake_gh(tmp_path / "bin")
    ratified = _git(repo, "rev-parse", "HEAD")

    refused = _run_ship(repo, tmp_path, pr_sha=ratified)
    assert refused.returncode != 0, "the floor breach should make a round owed"

    paid = run_review(repo, tmp_path, "adversarial", "main")
    assert paid.returncode == 0, paid.stderr
    accepted = _run_ship(repo, tmp_path, pr_sha=ratified)

    assert accepted.returncode == 0, accepted.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "ADR ratification" in posted
    assert _ADR_PATH in posted


def _flip_only_repo(tmp_path: Path) -> Path:
    """A PR carrying nothing but the ratification flip.

    The draft is already on ``main``, so the flip's parent *is* the merge base —
    and re-anchoring therefore makes the reviewed range empty. This shape is not
    coverable at all: ADR-0165 §3 anchors ``ship`` on that same parent, so no
    artifact can name content the PR adds. What is pinned here is that the harness
    says so, rather than spending the grace and then blaming the round.
    """
    repo = _adr_repo(tmp_path)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feature")
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-qb", "flip-only")
    assert _ratify(repo, "ratify").returncode == 0
    return repo


def test_a_flip_only_branch_is_refused_by_start_rather_than_waited_out(
    tmp_path: Path,
) -> None:
    """Round 1 of PR #1722 found this: the child exits before it can be observed.

    A round exits 0 on an empty range, and it does so *before* publishing the
    marker ``--start`` polls for — so a detached start would wait out the whole
    grace and then report a failure naming the wrong thing entirely.
    """
    repo = _flip_only_repo(tmp_path)

    started = _run(repo, _env(tmp_path), "--start", "adversarial", "main")

    assert started.returncode == 1
    assert "nothing to review" in started.stderr
    assert "ratification flip" in started.stderr
    assert "No round has been started." in started.stderr


def test_the_foreground_round_says_the_same_thing(tmp_path: Path) -> None:
    """The round's own answer on the same branch, for the same reader."""
    repo = _flip_only_repo(tmp_path)

    result = run_review(repo, tmp_path, "adversarial", "main", check=False)

    assert "no changes between" in result.stderr
    assert "nothing but the flip" in result.stderr
