"""Tests for ADR-0027 — what a review covers when the base moves.

`ship` used to invalidate a review artifact whenever the PR's base moved at all.
With branch protection `strict: true` every merge to `main` forces a rebase on
every open PR, which moves the base, which discarded a valid review and cost a
full Codex run. ADR-0027 separates **coverage** — did a review actually read this
content, which only the artifact can attest — from **currency** — does the change
still hold on today's base, which the gate re-establishes on every rebase and
every push.

The acceptance rule is a fail-closed surface, so this module owes a test per
branch of it rather than a happy path. It is organised the way the ADR's own
Consequences section enumerates them:

- §2's falsifiable prediction, which is the *first* test and not an assumption:
  #118's two rebases must classify the way the operator classified them by hand.
  The #116 rebase changed `scripts/ship.sh` in the same function region the diff
  touched, so the identity moves and the re-review fires; the #117 rebase changed
  a file the diff's hunks never cite, so the identity holds.
- That `--verbatim` and not `--stable` is the mechanism, shown by the case that
  separates them: a base move re-indenting a context line inside a reviewed hunk.
- Every refusal: a moved identity, an identity with nothing to hash, each floor
  path in each of the four ways a base move can touch it, a non-ancestor base, a
  reviewed edit relocated between two identical regions, and a drift record too
  large to publish whole.
- The two acceptances that stop a fail-closed implementation from satisfying the
  list by refusing everything: the #117 rebase, and the same-file off-hunk case.
- §4's disclosure, including the reversible Markdown-safe pathname encoding
  (issue #165) that makes "published whole" true of names git permits and
  Markdown does not.

The helpers are shared with ``test_ship.py`` rather than re-derived: an artifact
written by a second, subtly different fake is how #45 shipped a no-op with green
tests.
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).parent))
from test_ship import (
    _VERDICT,
    _fake_gh,
    _git,
    _patch_id,
    _raw_patch_id,
    _record_review,
    _record_snapshot,
    _run_ship,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# The reviewed file, big enough that a base move can land far from the hunk as
# well as inside it. `scripts/ship.sh` is the path #118's diff actually touched.
_REVIEWED = "scripts/ship.sh"
_REVIEWED_LINE = 60
# Two lines apart: inside the reviewed hunk's three lines of context, and far
# enough that the rebase applies cleanly rather than conflicting. One line apart
# conflicts, which would test git's merge rather than the acceptance rule.
_NEAR_LINE = _REVIEWED_LINE - 2
_FAR_LINE = 100

# Every path ADR-0027 §3 fixes as the floor, plus one that is deliberately not on
# it. `scripts/ship.sh` is excluded by name: the boundary is "what the reviewer
# read", and ship shapes no prompt — it applies whatever version of the
# acceptance rule is on disk at ship time, so a stale copy cannot exist to be
# reused.
_FLOOR = (
    "src/ai_assistant/core/protocols.py",
    "src/ai_assistant/core/types.py",
    "docs/review/adversarial.md",
    "docs/review/guide.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "scripts/codex-review.sh",
    "docs/adr/0001-record-architecture-decisions.md",
)


def _lines(marker: str = "") -> str:
    """A 120-line file whose lines are individually addressable."""
    return "".join(f"line {i}{marker}\n" for i in range(1, 121))


def _edit_line(repo: Path, path: str, line: int, text: str) -> None:
    target = repo / path
    body = target.read_text().splitlines()
    body[line - 1] = text
    target.write_text("\n".join(body) + "\n")


def _init_repo(repo: Path, *, touches_core: bool = False) -> str:
    """A repo on a feature branch with an `origin` holding `main`.

    The tree carries every §3 floor path plus the ordinary files a base move can
    land in, so a floor case and a non-floor case differ only in which path the
    base move touches.
    """
    origin = repo.parent / "origin.git"
    assert shutil.which("git") is not None
    subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [str(shutil.which("git")), "init", "-q", "--bare", "-b", "main", str(origin)], check=True
    )
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    for path in (*_FLOOR, _REVIEWED, "src/ai_assistant/orchestration/loop.py", "notes/thing.md"):
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_lines())
    (repo / ".gitignore").write_text(".review/\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "main")

    _git(repo, "checkout", "-qb", "feature")
    _edit_line(repo, _REVIEWED, _REVIEWED_LINE, "line 60 — the reviewed change")
    if touches_core:
        _edit_line(repo, "src/ai_assistant/core/protocols.py", 10, "line 10 — a new Protocol")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return _git(repo, "rev-parse", "HEAD")


def _advance_base(
    repo: Path, mutate: Callable[[Path], object], *, rebase: bool = True, stage: bool = True
) -> None:
    """Land a commit on `origin/main`, then rebase the feature branch onto it.

    This is the sequence branch protection's `strict: true` forces on every open
    PR whenever anything merges. The rebase moves the whole repository tree as
    well as the base, which is why relaxing the base comparison alone would have
    changed no outcome at all.
    """
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "checkout", "-q", "main")
    mutate(repo)
    if stage:
        _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the base moves")
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", branch)
    if rebase:
        _git(repo, "rebase", "-q", "main")


def _review_then_move(
    repo: Path,
    tmp_path: Path,
    mutate: Callable[[Path], object],
    *,
    personas: tuple[str, ...] = ("adversarial",),
    stage: bool = True,
) -> str:
    """Record a review, then move the base under it. Returns the rebased HEAD.

    Recorded first and moved second, in that order, because that is the order it
    happens in: the review covers the pre-rebase range, and the artifact keeps
    naming it afterwards.
    """
    sha = _git(repo, "rev-parse", "HEAD")
    _fake_gh(tmp_path / "bin")
    old_base = _git(repo, "merge-base", "main", sha)
    for persona in personas:
        _record_review(repo, sha, persona, f"a real finding\n{_VERDICT}\n", base_sha=old_base)
    _advance_base(repo, mutate, stage=stage)
    return _git(repo, "rev-parse", "HEAD")


def _decode_path(encoded: str) -> str:
    """Reverse `ship`'s published-pathname encoding: entities, then backslashes.

    The decode is spelled out here rather than imported so it is an independent
    statement of the contract — a round trip through this and the shell encoder
    is what makes "published whole" checkable (issue #165).
    """
    text = html.unescape(encoded)
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] != "\\":
            out.append(text[i])
            i += 1
            continue
        kind = text[i + 1]
        if kind == "x":
            out.append(chr(int(text[i + 2 : i + 4], 16)))
            i += 4
            continue
        out.append({"\\": "\\", "n": "\n", "r": "\r", "t": "\t"}[kind])
        i += 2
    return "".join(out)


def _published_paths(comment: str) -> list[str]:
    """Every pathname in the drift record, decoded back to its bytes on disk."""
    return [_decode_path(m) for m in re.findall(r"<code>(.*?)</code>", comment)]


# --- §2's falsifiable prediction: #118's two rebases -------------------------


def test_the_117_rebase_holds_the_identity_and_ships(tmp_path: Path) -> None:
    """#118's #117 rebase: a base move the diff's hunks never cite.

    ADR-0027 §2 predicts this classifies as covered. It is one of the two cases
    that must ACCEPT, and it is not decoration: without it a fail-closed
    implementation could satisfy every refusal below by refusing everything. #124
    measured this exact run — a full Codex round that could not have produced a
    finding.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo,
        tmp_path,
        lambda r: _edit_line(r, "src/ai_assistant/orchestration/loop.py", 40, "line 40 — moved"),
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "a real finding" in posted


def test_the_116_rebase_moves_the_identity_and_refuses(tmp_path: Path) -> None:
    """#118's #116 rebase: a base move in the same function region as the diff.

    The base edits a line inside the reviewed hunk's context, so the text the
    reviewer read is not the text being shipped. ADR-0027 §2 predicts the
    identity moves and the re-review fires — the case the anchor exists for, and
    the one the operator judged legitimate by hand.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, _REVIEWED, _NEAR_LINE, "line 58 — the base moved")
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode != 0
    assert "reviewed patch is no longer" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_a_base_move_off_the_hunk_in_a_touched_file_still_ships(tmp_path: Path) -> None:
    """The same-file off-hunk case — the benefit this whole decision is for.

    #118 does not cover it, and an implementation folding the `index` blob IDs
    into the identity would fail it: the base edits a region of a file the PR
    also touches, without entering any reviewed hunk. Ignoring hunk offsets is
    §2's first property, so this must hold.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, _REVIEWED, _FAR_LINE, "line 100 — far away")
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode == 0, result.stderr
    assert "a real finding" in (tmp_path / "comment.md").read_text()


# --- §2's mechanism: --verbatim, and specifically not --stable ---------------


def test_a_whitespace_only_base_move_inside_a_hunk_refuses(tmp_path: Path) -> None:
    """Re-indenting a context line inside a reviewed hunk must invalidate.

    This is the case that separates the two spellings of the mechanism, and the
    reason ADR-0027 §2 fixes the flag rather than leaving it to the
    implementation: `--stable` strips whitespace, so the identity would not move
    and a review of content that is no longer there would be reused. Indentation
    is semantic in Python, so "only whitespace" is not "only cosmetic".

    Both halves are asserted — that `ship` refuses, and that the unsafe spelling
    would not have noticed — so the flag choice is pinned by evidence rather than
    by a comment.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    sha = _git(repo, "rev-parse", "HEAD")
    old_base = _git(repo, "merge-base", "main", sha)
    before_verbatim = _raw_patch_id(repo, old_base, sha)
    before_stable = _raw_patch_id(repo, old_base, sha, "--stable")

    rebased = _review_then_move(
        repo,
        tmp_path,
        lambda r: _edit_line(r, _REVIEWED, _NEAR_LINE, "        line 58"),
    )
    new_base = _git(repo, "merge-base", "main", rebased)

    assert _raw_patch_id(repo, new_base, rebased) != before_verbatim, (
        "--verbatim must see the re-indented context line"
    )
    assert _raw_patch_id(repo, new_base, rebased, "--stable") == before_stable, (
        "--stable must NOT see it — that is why it is the unsafe spelling"
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode != 0
    assert "reviewed patch is no longer" in result.stderr


# --- §2: an entry with nothing to hash makes path (b) unavailable ------------


def test_a_rename_only_diff_across_a_moved_base_refuses(tmp_path: Path) -> None:
    """A 100%-similarity rename is anchored on its PATHS ALONE.

    git emits `similarity index 100% / rename from / rename to` and no `index`
    line, so the identity of such an entry is a function of its paths. A reviewed
    PR that only renames `f` to `g`, rebased onto a base that changed `f`'s
    contents, therefore presents a byte-identical identity while `g` now holds
    content no reviewer saw. The hazard is asserted directly, then the refusal.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "reset", "-q", "--hard", "main")
    _git(repo, "mv", "notes/thing.md", "notes/renamed.md")
    _git(repo, "commit", "-qm", "rename only")
    sha = _git(repo, "rev-parse", "HEAD")
    old_base = _git(repo, "merge-base", "main", sha)
    before = _raw_patch_id(repo, old_base, sha)

    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, "notes/thing.md", 5, "line 5 — rewritten by base")
    )
    new_base = _git(repo, "merge-base", "main", rebased)

    assert _raw_patch_id(repo, new_base, rebased) == before, (
        "the hazard: an unguarded identity is unchanged though the content is not"
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode != 0
    assert "identity that can be trusted" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_a_mode_only_diff_across_a_moved_base_refuses(tmp_path: Path) -> None:
    """A mode change emits `old mode / new mode` and no `index` line either."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "reset", "-q", "--hard", "main")
    (repo / "notes" / "thing.md").chmod(0o755)
    _git(repo, "add", "notes/thing.md")
    _git(repo, "commit", "-qm", "mode only")

    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, "notes/thing.md", 5, "line 5 — rewritten by base")
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode != 0
    assert "identity that can be trusted" in result.stderr


def test_an_artifact_predating_the_patch_id_field_refuses(tmp_path: Path) -> None:
    """No recorded identity is "nothing to hash", never a match.

    An artifact written before ADR-0027 carries no `patch_id`, so it cannot say
    what it read across a moved base. Unverifiable is not the same as matching.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    old_base = _git(repo, "merge-base", "main", sha)
    _record_review(repo, sha, "adversarial", base_sha=old_base, patch_id="")
    _advance_base(
        repo, lambda r: _edit_line(r, "src/ai_assistant/orchestration/loop.py", 40, "moved")
    )

    result = _run_ship(repo, tmp_path, pr_sha=_git(repo, "rev-parse", "HEAD"))

    assert result.returncode != 0
    assert "identity that can be trusted" in result.stderr


# --- §3: the floor -----------------------------------------------------------


def _touching(path: str) -> Callable[[Path], object]:
    """A base move that edits ``path`` — one closure per floor entry."""

    def mutate(repo: Path) -> None:
        _edit_line(repo, path, 5, "line 5 — moved")

    return mutate


def _assert_floor_refusal(repo: Path, tmp_path: Path, mutate: Callable[[Path], object]) -> None:
    rebased = _review_then_move(repo, tmp_path, mutate)
    result = _run_ship(repo, tmp_path, pr_sha=rebased)
    assert result.returncode != 0, "a floor breach must refuse"
    assert "floor" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_every_floor_path_changed_by_the_base_move_refuses(tmp_path: Path) -> None:
    """Each floor path in turn: the contract surface, the contracts, the ADRs.

    Enumerated rather than sampled because the floor is the part of §3 that has
    to be sound — a single missing entry fails open on exactly the class of base
    move the gate cannot see.
    """
    for i, floor_path in enumerate(_FLOOR):
        # One case per directory: `_init_repo` puts the bare `origin` beside the
        # clone, so sharing a parent would share a remote across cases.
        case = tmp_path / f"case-{i}"
        case.mkdir()
        _init_repo(case / "repo")
        _assert_floor_refusal(case / "repo", case, _touching(floor_path))


def test_a_deleted_floor_path_refuses(tmp_path: Path) -> None:
    """Deletion is a breach: the rubric the review was conducted under is gone."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _assert_floor_refusal(repo, tmp_path, lambda r: (r / "docs/review/adversarial.md").unlink())


def test_a_floor_path_renamed_out_of_the_floor_refuses(tmp_path: Path) -> None:
    """The SOURCE endpoint is read, not only the destination.

    A plain `--name-only` listing reports only where a detected rename landed, so
    a base move renaming `docs/review/adversarial.md` out of that tree would clear
    a floor it plainly breaches — and the listing would never say so.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _assert_floor_refusal(
        repo, tmp_path, lambda r: _git(r, "mv", "docs/review/adversarial.md", "notes/old-rubric.md")
    )


def test_a_path_renamed_into_the_floor_refuses(tmp_path: Path) -> None:
    """The DESTINATION endpoint is read too: a new ADR arriving by rename."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _assert_floor_refusal(
        repo, tmp_path, lambda r: _git(r, "mv", "notes/thing.md", "docs/adr/0099-a-decision.md")
    )


def test_the_floor_applies_to_the_architecture_lens_too(tmp_path: Path) -> None:
    """`docs/adr/**` is in the floor for EVERY persona, not only architecture.

    A per-persona floor was considered and withdrawn: `guide.md`'s authority
    hierarchy is not scoped by persona, and "adversarial would probably not have
    noticed" is a prediction about a reviewer rather than a property of the
    content. A floor built on that prediction fails open.
    """
    repo = tmp_path / "repo"
    _init_repo(repo, touches_core=True)
    rebased = _review_then_move(
        repo,
        tmp_path,
        lambda r: _edit_line(r, "docs/adr/0001-record-architecture-decisions.md", 5, "moved"),
        personas=("adversarial", "architecture"),
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode != 0
    assert "floor" in result.stderr


def test_ship_sh_is_not_in_the_floor(tmp_path: Path) -> None:
    """Deliberately excluded: ship shapes no prompt, so no stale copy can exist.

    The boundary is "what the reviewer read", not "what the review loop touches".
    A base move to `scripts/ship.sh` — which is what #118's #116 rebase was — must
    therefore be governed by the patch identity alone, and here it lands nowhere
    near the reviewed hunk.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, _REVIEWED, _FAR_LINE, "line 100 — ship moved")
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode == 0, result.stderr


# --- §2: the unmoved base stays governed by (a) ------------------------------


def test_a_relocated_edit_on_an_unmoved_base_is_refused_by_the_tree(tmp_path: Path) -> None:
    """PROPER is the load-bearing word: an equal base never reaches path (b).

    In a file with two identical regions, moving the reviewed edit from one to the
    other leaves the patch identity intact and the tree changed. (b) admitting an
    equal base would let the weaker instrument govern a case (a) already covers;
    (a)'s whole-tree comparison is what refuses it.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    twin = "alpha\nbravo\ncharlie\nMARK\ndelta\necho\nfoxtrot\n"
    _git(repo, "checkout", "-q", "main")
    (repo / "twin.txt").write_text(twin * 2)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "two identical regions")
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", "-B", "feature", "main")

    def _mark(first: bool) -> str:
        body = (twin * 2).splitlines()
        body[3 if first else 10] = "MARKED"
        return "\n".join(body) + "\n"

    (repo / "twin.txt").write_text(_mark(first=True))
    _git(repo, "commit", "-qam", "edit the first region")
    reviewed = _git(repo, "rev-parse", "HEAD")
    _fake_gh(tmp_path / "bin")
    _record_review(repo, reviewed, "adversarial", base_sha=_git(repo, "merge-base", "main", "HEAD"))

    (repo / "twin.txt").write_text(_mark(first=False))
    _git(repo, "commit", "-qam", "relocate the edit to the second region")
    relocated = _git(repo, "rev-parse", "HEAD")
    base = _git(repo, "merge-base", "main", relocated)

    assert _patch_id(repo, base, relocated) == _patch_id(repo, base, reviewed), (
        "the identity cannot see the relocation — that is the residual §2 states"
    )

    result = _run_ship(repo, tmp_path, pr_sha=relocated)

    assert result.returncode != 0
    assert "different content" in result.stderr


# --- §4: the drift is published whole, never truncated -----------------------


def test_an_accepted_moved_base_publishes_the_drift(tmp_path: Path) -> None:
    """The evidence the merge reviewer gets in exchange for the saved round.

    Both bases and the whole file set, computed rather than assembled by hand.
    The judgement stays human; what stops being human is the bookkeeping.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    sha = _git(repo, "rev-parse", "HEAD")
    old_base = _git(repo, "merge-base", "main", sha)

    def two_files(r: Path) -> None:
        _edit_line(r, "src/ai_assistant/orchestration/loop.py", 40, "moved")
        _edit_line(r, "notes/thing.md", 7, "also moved")

    rebased = _review_then_move(repo, tmp_path, two_files)
    new_base = _git(repo, "merge-base", "main", rebased)

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "base drift" in posted
    assert old_base[:12] in posted
    assert new_base[:12] in posted
    assert _published_paths(posted) == [
        "notes/thing.md",
        "src/ai_assistant/orchestration/loop.py",
    ]
    # #153: the marker and the header it keys on are untouched, and the drift is
    # a new block later in the body.
    lines = posted.splitlines()
    assert lines[0] == f"<!-- ship:{rebased} -->"
    assert lines[1].startswith("🔍 **Local Codex review**")
    assert posted.index("base drift") > posted.index("round 1")


def test_a_drift_record_too_large_to_publish_refuses_rather_than_truncating(
    tmp_path: Path,
) -> None:
    """§4's one forbidden outcome: truncating and shipping.

    The file set is not context for a decision here, it IS the decision, so an
    omitted tail is exactly where the contradicting `docs/adr/` entry hides. A
    list that does not fit makes path (b) unavailable, on the same footing as an
    unhashable identity.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, "src/ai_assistant/orchestration/loop.py", 40, "m")
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased, gh_env={"CODEX_SHIP_DRIFT_BUDGET": "10"})

    assert result.returncode != 0
    assert "publish whole" in result.stderr
    assert not (tmp_path / "comment.md").exists()


# --- §4 / issue #165: pathnames git permits and Markdown does not ------------


def _drift_path_round_trips(tmp_path: Path, name: str) -> None:
    """A base move adding ``name`` must publish it recoverably and inertly."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(repo, tmp_path, lambda r: (r / name).write_text("x\n"))

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert _published_paths(posted) == [name]
    # One list item per path, whatever the name contains: a newline inside a
    # pathname must not become a second apparent path.
    assert len([ln for ln in posted.splitlines() if ln.startswith("- `A`")]) == 1


def test_a_pathname_containing_a_newline_survives_publication(tmp_path: Path) -> None:
    """git permits it; a line-oriented renderer would emit two apparent paths."""
    _drift_path_round_trips(tmp_path, "notes/two\nlines.md")


def test_a_pathname_containing_markdown_delimiters_survives_publication(tmp_path: Path) -> None:
    """Every character GitHub's inline Markdown or HTML would read as structure."""
    _drift_path_round_trips(tmp_path, "notes/a<b>&c*d_e[f]g|h~i`j\\k.md")


def test_a_non_ascii_pathname_survives_publication(tmp_path: Path) -> None:
    """Unicode is preserved as itself: the encoding escapes bytes, not letters."""
    _drift_path_round_trips(tmp_path, "notes/café-日本語.md")


def test_a_pathname_with_a_control_character_survives_publication(tmp_path: Path) -> None:
    """A tab and a bell: escaped by name and by `\\xHH`, both reversible."""
    _drift_path_round_trips(tmp_path, "notes/tab\there\x07bell.md")


def test_both_rename_endpoints_are_encoded(tmp_path: Path) -> None:
    """§3 reads both endpoints, so §4 must publish both — encoded identically."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _git(r, "mv", "notes/thing.md", "notes/re<named>.md")
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert _published_paths(posted) == ["notes/thing.md", "notes/re<named>.md"]
    assert "notes/re<named>.md" not in posted, "the raw delimiters must not reach the body"


def test_dispositions_still_publish_alongside_an_accepted_moved_base(tmp_path: Path) -> None:
    """ADR-0025 §4's snapshot is selected by the artifact's own anchor.

    Path (b) accepts an artifact whose recorded base and tree are no longer the
    PR's, so the snapshot lookup must keep using what the artifact records rather
    than what HEAD carries — otherwise it would fail closed on a valid ship and
    the merge reviewer would lose the verdict-changing history.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    old_base = _git(repo, "merge-base", "main", sha)
    tree = _git(repo, "rev-parse", f"{sha}^{{tree}}")
    _record_review(
        repo, sha, "adversarial", f"a real finding\n{_VERDICT}\n", base_sha=old_base, loop_id="l1"
    )
    _record_snapshot(
        repo,
        "adversarial",
        tree,
        [("major", "retired", "an earlier round raised this")],
        sha=sha,
        base_sha=old_base,
        loop_id="l1",
    )
    _advance_base(
        repo, lambda r: _edit_line(r, "src/ai_assistant/orchestration/loop.py", 40, "moved")
    )

    result = _run_ship(repo, tmp_path, pr_sha=_git(repo, "rev-parse", "HEAD"))

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "base drift" in posted
    assert "an earlier round raised this" in posted


def test_the_patch_identity_block_is_byte_identical_in_both_scripts() -> None:
    """The one divergence that would not fail loudly.

    `codex-review.sh` records the identity and `ship.sh` recomputes it. If the
    two spellings drift apart they compute two different identities for one
    patch, so every moved base would silently cost a review round again — the
    exact tax ADR-0027 exists to remove, reintroduced with no error message. The
    duplication is deliberate (these are two standalone scripts, as
    `artifact_has_verdict` already is); this is what makes it safe.
    """
    begin = "# >>> shared-patch-identity"
    end = "# <<< shared-patch-identity"
    scripts = Path(__file__).parents[2] / "scripts"
    blocks = []
    for name in ("ship.sh", "codex-review.sh"):
        text = (scripts / name).read_text()
        assert text.count(begin) == 1, f"{name} must carry exactly one shared block"
        blocks.append(text.split(begin, 1)[1].split(end, 1)[0])
    assert blocks[0] == blocks[1]
    assert "--verbatim" in blocks[0]
    assert "--stable" not in blocks[0].replace("`--stable`", "")


def _failing_drift_git(bin_dir: Path, *, emit_prefix: bool) -> None:
    """A `git` that fails the drift listing, optionally after emitting a prefix.

    The producer failing *after* output is the case a process substitution
    cannot report: `mapfile` succeeds, and a truncated listing is read as a
    complete one. Only the `--name-status` call is intercepted; everything else
    is the real git, so the rest of `ship` behaves normally.
    """
    real = shutil.which("git")
    assert real is not None
    bin_dir.mkdir(parents=True, exist_ok=True)
    prefix = r"""printf 'M\0notes/thing.md\0'""" if emit_prefix else ":"
    shim = bin_dir / "git"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        '  if [[ "$a" == "--name-status" ]]; then\n'
        f"    {prefix}\n"
        '    echo "fatal: unable to read blob" >&2\n'
        "    exit 1\n"
        "  fi\n"
        "done\n"
        f'exec {real} "$@"\n'
    )
    shim.chmod(0o755)


def test_a_drift_listing_that_fails_partway_refuses(tmp_path: Path) -> None:
    """A truncated listing must never be read as a complete one.

    `git diff` can fail after emitting a prefix — an unreadable blob in a partial
    clone, a broken pipe — and the failure is invisible through a process
    substitution. Accepting the prefix would clear the floor whenever the
    breaching path was in the part that never arrived, and publish as "whole" a
    set that is not: both are exactly what §§3-4 fail closed against.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, "src/ai_assistant/orchestration/loop.py", 40, "m")
    )
    _failing_drift_git(tmp_path / "bin", emit_prefix=True)

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode != 0
    assert "could not be parsed" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_a_drift_listing_that_fails_with_no_output_refuses(tmp_path: Path) -> None:
    """The same failure with an empty stream — which reads as "nothing moved"."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, "src/ai_assistant/orchestration/loop.py", 40, "m")
    )
    _failing_drift_git(tmp_path / "bin", emit_prefix=False)

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode != 0
    assert "could not be parsed" in result.stderr


def test_the_identity_survives_git_config_changing_between_review_and_ship(
    tmp_path: Path,
) -> None:
    """The identity must be a function of the two commits, not of local config.

    `diff.interHunkContext` merges two nearby hunks into one, `color.ui=always`
    emits ANSI escapes even off a terminal, and `diff.renameLimit` can silently
    disable rename detection — each renders a different patch from the same pair
    of commits. Set here *after* the review is recorded, so the recording run and
    the ship run genuinely disagree about config; the pinned options are what make
    them agree about the patch anyway.

    The diff carries two hunks a few lines apart precisely so the inter-hunk
    setting has something to merge.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _edit_line(repo, _REVIEWED, _REVIEWED_LINE + 6, "line 66 — a second hunk")
    _git(repo, "commit", "-qam", "a second nearby hunk")

    rebased = _review_then_move(
        repo,
        tmp_path,
        lambda r: _edit_line(r, "src/ai_assistant/orchestration/loop.py", 40, "moved"),
    )
    _git(repo, "config", "diff.interHunkContext", "10")
    _git(repo, "config", "color.ui", "always")
    _git(repo, "config", "diff.renameLimit", "1")
    _git(repo, "config", "diff.algorithm", "histogram")
    _git(repo, "config", "diff.context", "7")

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "base drift" in posted
    # And the drift listing itself is not decorated by `color.ui=always`, which
    # would corrupt the very set §4 requires published exactly.
    assert "\x1b[" not in posted
    assert _published_paths(posted) == ["src/ai_assistant/orchestration/loop.py"]


_GITLINK_A = "1" * 40
_GITLINK_B = "2" * 40


def _set_gitlink(repo: Path, commit: str, path: str = "vendor/lib") -> None:
    """Stage a submodule gitlink pointing at ``commit``.

    Written through the index rather than by cloning a real submodule: the diff
    machinery under test reads the gitlink entry, and nothing here needs the
    pointed-at commit to exist.
    """
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{commit},{path}")


def test_a_submodule_the_base_moved_is_published_under_ignore_submodules(
    tmp_path: Path,
) -> None:
    """`diff.ignoreSubmodules=all` must not delete a path from the §4 record.

    This is the second of the two options that STRIP information rather than
    re-render it, and the one config can reach two ways: `diff.ignoreSubmodules`
    and a narrower `submodule.<name>.ignore` that outranks it. Under either, a
    changed gitlink vanishes from the patch, from `--raw`, and from the
    `--name-status` listing — so ship would publish as "whole" a drift set with a
    file missing from it, which is precisely what §4 forbids.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "checkout", "-q", "main")
    _set_gitlink(repo, _GITLINK_A)
    _git(repo, "commit", "-qm", "add a gitlink")
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "rebase", "-q", "main")
    _git(repo, "config", "diff.ignoreSubmodules", "all")
    _git(repo, "config", "submodule.vendor/lib.ignore", "all")

    rebased = _review_then_move(repo, tmp_path, lambda r: _set_gitlink(r, _GITLINK_B), stage=False)

    result = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert result.returncode == 0, result.stderr
    assert _published_paths((tmp_path / "comment.md").read_text()) == ["vendor/lib"]


def test_the_identity_sees_a_gitlink_under_ignore_submodules(tmp_path: Path) -> None:
    """Two ranges differing only in a gitlink must not share an identity.

    If they did, a base move into the submodule would be absorbed silently: the
    reviewer read one pointer and the merge would carry another, with the whole
    difference invisible to the acceptance rule.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "checkout", "-q", "main")
    _set_gitlink(repo, _GITLINK_A)
    _git(repo, "commit", "-qm", "add a gitlink")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-B", "feature", "main")
    _git(repo, "config", "diff.ignoreSubmodules", "all")

    _set_gitlink(repo, _GITLINK_B)
    _git(repo, "commit", "-qm", "bump the gitlink")
    bumped = _patch_id(repo, base, _git(repo, "rev-parse", "HEAD"))

    assert bumped, "a gitlink change must have an identity, not be invisible"
    assert bumped != _patch_id(repo, base, base)


def test_a_malformed_drift_budget_refuses_with_a_configuration_error(tmp_path: Path) -> None:
    """`[[ -gt ]]` evaluates an arithmetic *expression*, not a number.

    An operator override of `not-a-number` or `1/0` would otherwise abort inside
    the shell rather than refuse the ship, and a negative one would make path (b)
    unavailable under a message blaming the drift set for the operator's typo.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, "src/ai_assistant/orchestration/loop.py", 40, "m")
    )

    for bad in ("not-a-number", "1/0", "-1", ""):
        result = _run_ship(repo, tmp_path, pr_sha=rebased, gh_env={"CODEX_SHIP_DRIFT_BUDGET": bad})
        if bad == "":
            # An empty override is indistinguishable from an unset one to `:-`,
            # so it takes the default rather than failing — stated, not assumed.
            assert result.returncode == 0, result.stderr
            continue
        assert result.returncode != 0, f"{bad!r} was accepted"
        assert "CODEX_SHIP_DRIFT_BUDGET must be" in result.stderr
