"""Tests for scripts/ship.sh — the merge-readiness step (ADR-0015 §1).

With review no longer running in CI, `ship` is the only thing standing between
"a review happened" and "the review on the PR covers the code being merged".
Its refusals are the mechanism the ADR trades the CI-posted record for, so each
one is pinned here: a review of different content, an unpushed HEAD, a dirty
tree, and a missing adversarial lens must all fail *closed* rather than post a
misleading record.

ADR-0020 §3 re-anchors acceptance from the commit SHA to the reviewed *content* —
the recorded base and tree. That is a safety check, so the negative cases below
are pinned harder than the positive one: a different tree and a different base
must each still refuse, and in particular a genuine content change must refuse
even though it is exactly the case an over-broad implementation would let
through. The ADR is explicit that §3 covers unchanged content only.

Which *lens* an artifact represents is checked the same way, against the
recorded ``persona=`` rather than the filename (issue #99): a renamed
architecture review passes every content check, so the filename alone is not
evidence that the adversarial lens ran.

Driven as a subprocess with a fake ``gh`` on ``PATH``, so nothing reaches
GitHub.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "scripts" / "ship.sh"
_BASH = shutil.which("bash")
_GIT = shutil.which("git")

# The closing line every genuine review carries; ship.sh verifies it.
_VERDICT = "Verdict: APPROVE"


def _git(repo: Path, *args: str) -> str:
    assert _GIT is not None
    return subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [_GIT, *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(repo: Path, *, touches_core: bool = False) -> str:
    """A repo on a feature branch, with an `origin` holding `main`.

    A real remote is needed because ship.sh fetches the PR's base branch to
    decide whether the diff touches the shared contract surface. ``touches_core``
    puts the change in ``core/protocols.py`` instead of an ordinary file, which
    is what should demand the architecture lens.
    """
    origin = repo.parent / "origin.git"
    subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [str(_GIT), "init", "-q", "--bare", "-b", "main", str(origin)], check=True
    )
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "f.txt").write_text("one\n")
    # Mirrors the real repo: .review/ is ignored, so the dirty-tree check does
    # not trip over the artifacts it is about to read.
    (repo / ".gitignore").write_text(".review/\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "main")

    _git(repo, "checkout", "-qb", "feature")
    if touches_core:
        core = repo / "src" / "ai_assistant" / "core"
        core.mkdir(parents=True)
        (core / "protocols.py").write_text("class Thing: ...\n")
    else:
        (repo / "f.txt").write_text("two\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return _git(repo, "rev-parse", "HEAD")


def _fake_gh(bin_dir: Path) -> None:
    """A fake ``gh`` answering the calls ship.sh makes.

    ``GH_PR_SHA`` is what the PR head reports; ``GH_COMMENT_OUT`` is where a
    posted comment body is captured so a test can assert on it.

    Comments are modelled as files in ``GH_COMMENTS_DIR`` named by their id, so
    the idempotency path has real state to converge on: `gh pr comment` creates
    one, the `gh api` GET lists them, and the `gh api` PATCH rewrites one in
    place. ``GH_COMMENT_EXIT`` makes the create *report* failure after storing
    the comment — the lost-response window this guards. ``GH_API_FAIL`` makes
    the listing call fail.
    """
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "pr" && "$2" == "view" ]]; then\n'
        '  for a in "$@"; do\n'
        '    case "$a" in\n'
        # GH_PR_SHA_2, when set, is returned from the *second* headRefOid call
        # onward — the pre-post re-check sees a head that moved mid-run.
        "      headRefOid)\n"
        # GH_PR_SHA_AFTER_LOOKUP moves the head only once the comment listing
        # has happened, which pins the *ordering* of the pre-write head check
        # rather than merely its existence.
        '        if [[ -n "${GH_PR_SHA_AFTER_LOOKUP:-}" && -f "$GH_LOOKUP_MARK" ]]; then\n'
        '          printf "%s\\n" "$GH_PR_SHA_AFTER_LOOKUP"; exit 0\n'
        "        fi\n"
        '        if [[ -n "${GH_PR_SHA_2:-}" && -f "$GH_CALL_MARK" ]]; then\n'
        '          printf "%s\\n" "$GH_PR_SHA_2"; exit 0\n'
        "        fi\n"
        '        touch "$GH_CALL_MARK"; printf "%s\\n" "$GH_PR_SHA"; exit 0 ;;\n'
        "      number) printf '42\\n'; exit 0 ;;\n"
        "      baseRefName) printf 'main\\n'; exit 0 ;;\n"
        # Only fields real `gh pr view` actually supports are answered here.
        # An earlier fake invented `baseRepository`, which does not exist — so
        # its test passed while the real check silently never ran. Anything
        # unrecognised now exits non-zero, exactly as gh does.
        '      isCrossRepository) printf "%s\\n" "${GH_CROSS_REPO:-false}"; exit 0 ;;\n'
        "    esac\n"
        "  done\n"
        "fi\n"
        'if [[ "$1" == "pr" && "$2" == "comment" ]]; then\n'
        '  prev=""\n'
        '  for a in "$@"; do\n'
        # Appended, plus a per-call marker, so a test can assert both what was
        # posted and how many API calls it took.
        '    if [[ "$prev" == "--body-file" ]]; then\n'
        '      cat "$a" >>"$GH_COMMENT_OUT"\n'
        '      printf "call\\n" >>"$GH_COMMENT_CALLS"\n'
        '      id=$(( $(find "$GH_COMMENTS_DIR" -type f -not -name "*.author" | wc -l) + 1 ))\n'
        '      cp "$a" "$GH_COMMENTS_DIR/$id"\n'
        '      printf "%s\\n" "${GH_LOGIN:-shipper}" >"$GH_COMMENTS_DIR/$id.author"\n'
        "    fi\n"
        '    prev="$a"\n'
        "  done\n"
        # The comment is stored first, then the exit status is reported: that is
        # exactly the created-but-response-lost case.
        '  exit "${GH_COMMENT_EXIT:-0}"\n'
        "fi\n"
        'if [[ "$1" == "api" ]]; then\n'
        '  [[ -n "${GH_API_FAIL:-}" ]] && { echo "api unreachable" >&2; exit 1; }\n'
        '  method=GET; endpoint=""; body_file=""; prev=""\n'
        '  for a in "$@"; do\n'
        '    [[ "$prev" == "--method" ]] && method="$a"\n'
        '    [[ "$prev" == "-F" ]] && body_file="${a#body=@}"\n'
        '    case "$a" in repos/*|user) endpoint="$a" ;; esac\n'
        '    prev="$a"\n'
        "  done\n"
        '  if [[ "$endpoint" == "user" ]]; then\n'
        '    printf "%s\\n" "${GH_LOGIN:-shipper}"; exit 0\n'
        "  fi\n"
        # The GET emits what ship.sh's --jq asks for: id, author, and the first
        # two body lines, tab-separated, one comment per line.
        '  if [[ "$method" == "GET" ]]; then\n'
        '    touch "$GH_LOOKUP_MARK"\n'
        '    for f in "$GH_COMMENTS_DIR"/*; do\n'
        '      [[ -e "$f" ]] || continue\n'
        '      case "$f" in *.author) continue ;; esac\n'
        '      l1="$(sed -n "1p" "$f")"; l2="$(sed -n "2p" "$f")"\n'
        # Real `@tsv` cannot emit a raw carriage return without breaking its
        # one-record-per-line format, so it escapes it as the two characters
        # `\` and `r`. Reproduced here, or a CRLF body would be handed to
        # ship.sh in a form the real gh never produces.
        "      l1=\"${l1//$'\\r'/\\\\r}\"; l2=\"${l2//$'\\r'/\\\\r}\"\n"
        '      printf "%s\\t%s\\t%s\\t%s\\n" "$(basename "$f")" \\\n'
        '        "$(cat "$f.author" 2>/dev/null)" "$l1" "$l2"\n'
        "    done\n"
        "    exit 0\n"
        "  fi\n"
        '  if [[ "$method" == "PATCH" ]]; then\n'
        '    id="${endpoint##*/}"\n'
        # GH_PATCH_FAIL_ID fails the update of one specific comment while
        # leaving the others writable — the partial-failure case of issue #76,
        # which needs a *later* write to fail after an earlier one succeeded.
        '    if [[ "$id" == "${GH_PATCH_FAIL_ID:-}" ]]; then\n'
        '      echo "patch failed" >&2\n'
        '      printf "patch-failed %s\\n" "$id" >>"$GH_COMMENT_CALLS"\n'
        "      exit 1\n"
        "    fi\n"
        # GH_PATCH_LOSE_ID applies the update and *then* reports failure — the
        # lost-response case, where a non-zero exit is no evidence that the
        # comment is stale. Distinct from GH_PATCH_FAIL_ID, which fails before
        # mutating; ship cannot tell the two apart, which is the point.
        '    if [[ "$id" == "${GH_PATCH_LOSE_ID:-}" ]]; then\n'
        '      cat "$body_file" >"$GH_COMMENTS_DIR/$id"\n'
        '      echo "response lost" >&2\n'
        "      exit 1\n"
        "    fi\n"
        '    [[ -f "$GH_COMMENTS_DIR/$id" ]] || exit 1\n'
        '    cat "$body_file" >"$GH_COMMENTS_DIR/$id"\n'
        '    printf "patch %s\\n" "$id" >>"$GH_COMMENT_CALLS"\n'
        "    exit 0\n"
        "  fi\n"
        "  exit 1\n"
        "fi\n"
        "exit 1\n"
    )
    gh.chmod(0o755)


def _record_review(  # noqa: PLR0913  # one parameter per provenance field the real script emits
    repo: Path,
    sha: str,
    persona: str,
    body: str = f"a finding\n{_VERDICT}\n",
    *,
    base_sha: str | None = None,
    tree: str | None = None,
    recorded_persona: str | None = None,
    churn_bound: str = "exact",
    binary_files: int = 0,
    binary_churn: int = 0,
) -> None:
    """Write an artifact exactly as codex-review.sh would.

    The provenance line reproduces what the real script emits, aggregate fields
    and all. #45's CRLF bug shipped a no-op precisely because a fake produced a
    form the real tool never does, and its tests passed anyway.

    ``base_sha`` defaults to the real merge base with ``main``; pass a different
    commit to simulate a review run against a narrower base. ``tree`` defaults to
    the tree of ``sha`` itself — what a genuine review of that commit records —
    so pass a different one to simulate a review of different content. A ``body``
    without a closing ``_VERDICT`` simulates an artifact truncated mid-write.

    ``recorded_persona`` defaults to ``persona``, which is what a genuine run
    records — the filename and the field agree. Pass a different value (or the
    empty string, to omit the field) to simulate an artifact whose filename
    claims a lens its provenance does not.

    ``churn_bound``, ``binary_files`` and ``binary_churn`` are the aggregate
    caveats ship renders into the comment. A zero omits its field entirely,
    which is what the real script does when there is nothing to report — the
    field's presence is what marks the caveat, so a recorded zero would be
    wrong. The two binary counts are independent: work reverted within the
    branch is in ``binary_churn`` and not in ``binary_files``.
    """
    if base_sha is None:
        base_sha = _git(repo, "merge-base", "main", sha)
    if tree is None:
        tree = _git(repo, "rev-parse", f"{sha}^{{tree}}")
    if recorded_persona is None:
        recorded_persona = persona
    review_dir = repo / ".review"
    review_dir.mkdir(exist_ok=True)
    persona_field = f"persona={recorded_persona} " if recorded_persona else ""
    binary_field = f"binary_files={binary_files} " if binary_files else ""
    if binary_churn:
        binary_field = f"{binary_field}binary_churn={binary_churn} "
    (review_dir / f"{sha}-{persona}.md").write_text(
        f"<!-- {persona_field}base=main base_sha={base_sha} sha={sha} "
        f"branch=feature tree={tree} round=1 net_lines=2 churn_lines=2 "
        f"churn_ratio=1.0 churn_bound={churn_bound} commits=1 {binary_field}-->\n{body}"
    )


def _run_ship(
    repo: Path,
    tmp_path: Path,
    *,
    pr_sha: str,
    pr_sha_after: str | None = None,
    gh_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ship.sh against the fake gh.

    ``gh_env`` overrides what the fake reports (e.g. ``GH_CROSS_REPO=true`` to
    simulate a PR from a fork).
    """
    assert _BASH is not None
    env = os.environ.copy()
    env.update(gh_env or {})
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env['PATH']}"
    env["GH_PR_SHA"] = pr_sha
    env["GH_CALL_MARK"] = str(tmp_path / "gh-called")
    env["GH_LOOKUP_MARK"] = str(tmp_path / "gh-comments-listed")
    if pr_sha_after is not None:
        env["GH_PR_SHA_2"] = pr_sha_after
    env["GH_COMMENT_OUT"] = str(tmp_path / "comment.md")
    env["GH_COMMENT_CALLS"] = str(tmp_path / "gh-comment-calls")
    comments = tmp_path / "comments"
    comments.mkdir(exist_ok=True)
    env["GH_COMMENTS_DIR"] = str(comments)
    return subprocess.run(  # noqa: S603  # resolved bash, in-repo script, test-controlled env
        [_BASH, str(_SCRIPT)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_posts_the_review_when_it_matches_the_pr_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"a real finding\n{_VERDICT}\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "a real finding" in posted
    assert sha[:12] in posted
    # The provenance header is script metadata, not something a reader wants.
    assert "<!-- sha=" not in posted


def test_refuses_when_the_review_covers_different_content(tmp_path: Path) -> None:
    """The stale-paste this guards: a review of an earlier, different tree.

    Under ADR-0020 §3 the anchor is content rather than the commit, so what makes
    this stale is that ``HEAD~1`` holds different content — not merely that it is
    a different commit. Same content under a different commit is accepted; that
    is pinned separately below.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, _git(repo, "rev-parse", "HEAD~1"), "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "no adversarial review" in result.stderr
    assert "different content" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_when_the_pr_head_is_behind_local_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=_git(repo, "rev-parse", "HEAD~1"))

    assert result.returncode != 0
    assert "push first" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_on_a_dirty_working_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")
    (repo / "f.txt").write_text("uncommitted\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "dirty" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_when_only_the_architecture_lens_was_run(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "architecture")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "no adversarial review" in result.stderr


def test_refuses_an_artifact_whose_filename_contradicts_its_persona(tmp_path: Path) -> None:
    """Issue #99: the filename is a label, the provenance field is the claim.

    An architecture review renamed to ``<sha>-adversarial.md`` carries a matching
    base, a matching tree and a real verdict, so every other check passes. If the
    persona is read off the filename alone it satisfies the mandatory adversarial
    requirement without that lens ever having run.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", recorded_persona="architecture")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "no adversarial review" in result.stderr
    assert "recorded persona does not match its filename" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_an_artifact_with_no_recorded_persona(tmp_path: Path) -> None:
    """A provenance line missing the field cannot corroborate the filename.

    Unverifiable is not the same as matching — the same rule the base and tree
    fields already fail closed under.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", recorded_persona="")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "no adversarial review" in result.stderr
    assert "no recorded persona/base/tree" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_ignores_an_artifact_naming_a_lens_ship_does_not_know(tmp_path: Path) -> None:
    """A self-consistent artifact for an undefined lens is not posted.

    It satisfies no requirement, so posting it would put a heading on the PR
    claiming a review nobody defined a rubric for. The valid adversarial record
    alongside it still ships.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"adversarial finding\n{_VERDICT}\n")
    _record_review(repo, sha, "vibes", f"vibes finding\n{_VERDICT}\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "adversarial finding" in posted
    assert "vibes" not in posted


def test_posts_every_persona_recorded_for_the_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"adversarial finding\n{_VERDICT}\n")
    _record_review(repo, sha, "architecture", f"architecture finding\n{_VERDICT}\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "adversarial finding" in posted
    assert "architecture finding" in posted


def test_refuses_a_core_change_without_the_architecture_lens(tmp_path: Path) -> None:
    """A contract change needs both lenses — previously documented, not checked."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo, touches_core=True)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "architecture" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_posts_a_core_change_carrying_both_lenses(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo, touches_core=True)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")
    _record_review(repo, sha, "architecture")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "comment.md").exists()


def test_a_non_core_change_needs_only_the_adversarial_lens(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr


def test_refuses_when_an_untracked_file_is_present(tmp_path: Path) -> None:
    """An untracked file is unreviewed work; `git diff --quiet` alone misses it."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")
    (repo / "sneaky.py").write_text("unreviewed = True\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "dirty" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_a_review_run_against_a_narrower_base(tmp_path: Path) -> None:
    """Right SHA, wrong range — the artifact covers only part of the PR diff."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    # A second commit, so HEAD~1 is genuinely inside the PR rather than being
    # the merge base itself — otherwise this asserts nothing.
    (repo / "f.txt").write_text("three\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second")
    sha = _git(repo, "rev-parse", "HEAD")
    _fake_gh(tmp_path / "bin")
    # Reviewed only the last commit, not main...HEAD.
    _record_review(repo, sha, "adversarial", base_sha=_git(repo, "rev-parse", "HEAD~1"))

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "different base" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_when_the_pr_head_moves_before_posting(tmp_path: Path) -> None:
    """A push landing mid-run would leave a review that reads as current."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha, pr_sha_after="0" * 40)

    assert result.returncode != 0
    assert "moved" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_an_artifact_with_no_recorded_base_or_tree(tmp_path: Path) -> None:
    """Unverifiable is not the same as matching, so it fails closed.

    An artifact predating ADR-0020 records no tree, and one predating the base
    recording no base. Either way its content cannot be checked — and the whole
    guarantee is that the check is mechanical rather than a matter of care.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    (repo / ".review").mkdir()
    (repo / ".review" / f"{sha}-adversarial.md").write_text(f"<!-- sha={sha} -->\nold\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "no recorded persona/base/tree" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_core_check_survives_a_diff_larger_than_the_pipe_buffer(tmp_path: Path) -> None:
    """The architecture requirement must not fail *open* on a big diff.

    Piping `git diff --name-only` into `grep -q` lets grep close the pipe on its
    first match; with a file list larger than the ~64KB pipe buffer git then
    dies of SIGPIPE, and `pipefail` turns that into a false condition — silently
    skipping the check. This diff is deliberately far past that threshold.
    """
    repo = tmp_path / "repo"
    _init_repo(repo, touches_core=True)
    # The padding must sort *after* src/ai_assistant/core/, since
    # `git diff --name-only` emits sorted paths: grep has to match early and
    # close the pipe while git still has plenty left to write. Padding that
    # sorted first would be fully consumed before the match, and the test would
    # pass against the very bug it exists to catch (it did, before this).
    padding = repo / "zzz-padding"
    padding.mkdir()
    for i in range(3000):
        (padding / f"a-rather-long-generated-file-name-number-{i:05d}.txt").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "a large diff")
    sha = _git(repo, "rev-parse", "HEAD")

    name_bytes = len(_git(repo, "diff", "--name-only", "main...HEAD"))
    assert name_bytes > 65_536, f"diff name list is only {name_bytes} bytes; test is toothless"

    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "architecture" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_fails_closed_on_a_review_too_large_to_post_intact(tmp_path: Path) -> None:
    """Truncating would drop the tail — where the findings and verdict live.

    A silently-shortened review posted as a successful ship is worse than no
    comment: it reads as the whole record while potentially missing the verdict.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", "x" * 80_000 + f"\n{_VERDICT}\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "cannot be posted intact" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_posts_the_whole_report_in_a_single_comment(tmp_path: Path) -> None:
    """One API call, so a retry cannot duplicate a partially-posted report."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"adversarial finding\n{_VERDICT}\n")
    _record_review(repo, sha, "architecture", f"architecture finding\n{_VERDICT}\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "gh-comment-calls").read_text().count("call") == 1


def test_refuses_an_artifact_truncated_before_its_verdict(tmp_path: Path) -> None:
    """Valid metadata is not proof of a finished review.

    An interrupt partway through writing leaves a header and a partial body.
    ship is the last point before that becomes the record.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", "half a fin\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "does not end in a verdict" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_a_header_only_artifact(tmp_path: Path) -> None:
    """The narrowest form of the same failure: nothing but provenance."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", "")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert not (tmp_path / "comment.md").exists()


def test_refuses_a_pr_from_a_fork(tmp_path: Path) -> None:
    """From a fork, origin/<base> is the fork's copy — the wrong diff to check."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha, gh_env={"GH_CROSS_REPO": "true"})

    assert result.returncode != 0
    assert "comes from a fork" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_when_the_fork_check_cannot_run(tmp_path: Path) -> None:
    """A check that cannot answer must stop the ship, not be waved through.

    The first version of this check queried a `gh` field that does not exist and
    suppressed the error, so it silently never ran at all.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    bin_dir = tmp_path / "bin"
    _fake_gh(bin_dir)
    _record_review(repo, sha, "adversarial")
    # A gh that rejects the field, the way the real one rejects an unknown key.
    gh = bin_dir / "gh"
    gh.write_text(
        gh.read_text().replace(
            '      isCrossRepository) printf "%s\\n" "${GH_CROSS_REPO:-false}"; exit 0 ;;\n',
            '      isCrossRepository) echo "Unknown JSON field" >&2; exit 1 ;;\n',
        )
    )

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "could not determine" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def _stored_comments(tmp_path: Path) -> list[str]:
    """Every comment body the fake `gh` currently holds for the PR."""
    return [
        p.read_text() for p in sorted((tmp_path / "comments").iterdir()) if p.suffix != ".author"
    ]


def _ship_comment_opening(sha: str) -> str:
    """The two lines ship.sh uses to recognise a comment as its own."""
    return f"<!-- ship:{sha} -->\n🔍 **Local Codex review** — commit `{sha[:12]}`\n"


def _seed_comment(tmp_path: Path, comment_id: str, body: str, author: str) -> None:
    """Put a comment on the PR that ship.sh did not write.

    Ids are chosen above the range the fake allocates, so seeding cannot collide
    with a comment ship goes on to create.
    """
    comments = tmp_path / "comments"
    comments.mkdir(exist_ok=True)
    (comments / comment_id).write_text(body)
    (comments / f"{comment_id}.author").write_text(f"{author}\n")


def test_marks_the_comment_with_the_commit_it_reviews(tmp_path: Path) -> None:
    """The hidden marker is what makes a re-run recognise its own comment."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "comment.md").read_text().startswith(f"<!-- ship:{sha} -->\n")


def test_a_rerun_updates_the_existing_comment_rather_than_duplicating(tmp_path: Path) -> None:
    """Shipping the same commit twice converges on one comment."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"first finding\n{_VERDICT}\n")

    assert _run_ship(repo, tmp_path, pr_sha=sha).returncode == 0
    # A re-review of the same commit, with a different body to prove the
    # existing comment is rewritten rather than merely left alone.
    _record_review(repo, sha, "adversarial", f"second finding\n{_VERDICT}\n")
    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    stored = _stored_comments(tmp_path)
    assert len(stored) == 1
    assert "second finding" in stored[0]
    assert "first finding" not in stored[0]
    calls = (tmp_path / "gh-comment-calls").read_text()
    assert calls.count("call") == 1
    assert calls.count("patch") == 1


def test_a_lost_response_does_not_leave_a_duplicate_on_the_next_run(tmp_path: Path) -> None:
    """The failure #45 is about: GitHub created the comment, `gh` reported failure.

    The naive retry posts an identical second review. Finding the marker turns
    the retry into an update of the comment that did land.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    failed = _run_ship(repo, tmp_path, pr_sha=sha, gh_env={"GH_COMMENT_EXIT": "1"})

    assert failed.returncode != 0
    assert len(_stored_comments(tmp_path)) == 1, "the comment was created before the failure"

    retried = _run_ship(repo, tmp_path, pr_sha=sha)

    assert retried.returncode == 0, retried.stderr
    assert len(_stored_comments(tmp_path)) == 1


def test_a_review_of_a_later_commit_gets_its_own_comment(tmp_path: Path) -> None:
    """The marker keys on the SHA, so it must not overwrite an earlier review."""
    repo = tmp_path / "repo"
    first_sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, first_sha, "adversarial", f"on the first commit\n{_VERDICT}\n")
    assert _run_ship(repo, tmp_path, pr_sha=first_sha).returncode == 0

    (repo / "f.txt").write_text("three\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-qm", "more")
    second_sha = _git(repo, "rev-parse", "HEAD")
    _record_review(repo, second_sha, "adversarial", f"on the second commit\n{_VERDICT}\n")

    result = _run_ship(repo, tmp_path, pr_sha=second_sha)

    assert result.returncode == 0, result.stderr
    stored = _stored_comments(tmp_path)
    assert len(stored) == 2
    assert any("on the first commit" in c for c in stored)
    assert any("on the second commit" in c for c in stored)


def test_never_edits_a_marked_comment_written_by_someone_else(tmp_path: Path) -> None:
    """The marker is public text; anyone can write or quote it.

    Patching on the marker alone would rewrite another author's comment where
    permissions allow it, and fail the ship where they do not.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"my finding\n{_VERDICT}\n")
    foreign = _ship_comment_opening(sha) + "\nsomeone else's comment\n"
    _seed_comment(tmp_path, "900", foreign, author="not-the-shipper")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "comments" / "900").read_text() == foreign
    stored = _stored_comments(tmp_path)
    assert len(stored) == 2, "the review is posted as a new comment, not into theirs"
    assert any("my finding" in c for c in stored)


def test_does_not_edit_a_comment_of_ours_that_merely_quotes_the_marker(tmp_path: Path) -> None:
    """Same author, same marker, but not a ship comment — it must be left alone.

    Quoting a marker while discussing a review is the realistic way this
    collides. Requiring ship's own header on the following line separates a
    comment *about* the marker from a comment ship wrote.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"my finding\n{_VERDICT}\n")
    quoted = f"<!-- ship:{sha} -->\nwhy does ship write that marker above?\n"
    _seed_comment(tmp_path, "900", quoted, author="shipper")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "comments" / "900").read_text() == quoted
    assert len(_stored_comments(tmp_path)) == 2


def test_recognises_its_own_comment_when_github_returns_it_with_crlf(tmp_path: Path) -> None:
    """GitHub stores comment bodies with CRLF line endings.

    `@tsv` cannot emit a raw carriage return, so it arrives as the two-character
    escape `\\r`. Matching against a control byte instead would miss every real
    comment and duplicate the review on every re-run.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"current finding\n{_VERDICT}\n")
    crlf = (_ship_comment_opening(sha) + "\nsuperseded finding\n").replace("\n", "\r\n")
    _seed_comment(tmp_path, "900", crlf, author="shipper")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    stored = _stored_comments(tmp_path)
    assert len(stored) == 1, "the CRLF comment is updated, not duplicated"
    assert "current finding" in stored[0]


def test_refuses_when_the_pr_head_moves_during_the_comment_lookup(tmp_path: Path) -> None:
    """The head check must sit after the lookup, not before it.

    Reading the PR's comments is itself a round trip; a push landing during it
    would otherwise be written up as a review of the current head.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha, gh_env={"GH_PR_SHA_AFTER_LOOKUP": "0" * 40})

    assert result.returncode != 0
    assert "PR head moved" in result.stderr
    assert _stored_comments(tmp_path) == []


def test_updates_every_duplicate_it_owns_for_the_commit(tmp_path: Path) -> None:
    """Check-then-create is not atomic, so a duplicate can exist.

    It cannot be prevented without conditional creation GitHub does not offer.
    What it must not become is a *stale* duplicate — so every owned match is
    rewritten, not just the first.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"current finding\n{_VERDICT}\n")
    stale = _ship_comment_opening(sha) + "\nsuperseded finding\n"
    _seed_comment(tmp_path, "901", stale, author="shipper")
    _seed_comment(tmp_path, "902", stale, author="shipper")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    stored = _stored_comments(tmp_path)
    assert len(stored) == 2, "both duplicates are updated; no third comment is created"
    assert all("current finding" in c for c in stored)
    assert all("superseded finding" not in c for c in stored)


def test_a_failed_update_still_attempts_the_rest_and_names_the_split(tmp_path: Path) -> None:
    """Issue #76: the update loop is not failure-atomic, so it must report.

    The *first* write is the one made to fail, which pins both halves of the
    fix. Under a bare ``set -e`` the loop would abort there and leave the second
    comment stale as well, having never tried it — so the second comment
    carrying the current review is what shows every comment is attempted. And
    the exit has to name which comments now disagree, because a bare ``gh``
    error tells the operator nothing about the state left behind.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"current finding\n{_VERDICT}\n")
    stale = _ship_comment_opening(sha) + "\nsuperseded finding\n"
    _seed_comment(tmp_path, "901", stale, author="shipper")
    _seed_comment(tmp_path, "902", stale, author="shipper")

    result = _run_ship(repo, tmp_path, pr_sha=sha, gh_env={"GH_PATCH_FAIL_ID": "901"})

    assert result.returncode != 0
    # The failure did not stop the loop: 902 was still attempted, and succeeded.
    comments = tmp_path / "comments"
    assert "superseded finding" in (comments / "901").read_text()
    assert "current finding" in (comments / "902").read_text()
    # And the message says exactly which comment is lying, rather than passing
    # gh's error through.
    assert "902" in result.stderr, "the comment that was written is named"
    assert "901" in result.stderr, "the comment whose write failed is named"
    assert "just ship" in result.stderr, "the recovery is stated"


def test_a_failed_update_does_not_claim_the_comment_is_stale(tmp_path: Path) -> None:
    """A non-zero PATCH is not evidence that the write was not applied.

    The request can succeed and its response be lost — the same ambiguity ship
    already documents for comment *creation*. Here the update lands and the call
    still reports failure, so a message asserting the comment shows a superseded
    review would be stating something ship cannot know. It must name the
    uncertainty instead; the recovery is the same re-run either way.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"current finding\n{_VERDICT}\n")
    stale = _ship_comment_opening(sha) + "\nsuperseded finding\n"
    _seed_comment(tmp_path, "901", stale, author="shipper")

    result = _run_ship(repo, tmp_path, pr_sha=sha, gh_env={"GH_PATCH_LOSE_ID": "901"})

    assert result.returncode != 0
    # The write did land, so any claim that 901 is superseded would be false.
    assert "current finding" in (tmp_path / "comments" / "901").read_text()
    assert "may or may not have been updated" in result.stderr
    assert "showing a superseded" not in result.stderr


def test_a_rerun_converges_after_a_partly_failed_update(tmp_path: Path) -> None:
    """The divergence lasts only until the next ship — which the failure prompts.

    This is why #76 is a `minor` rather than a defect that needs a transaction:
    the state is self-healing, provided the operator is told to re-run.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"current finding\n{_VERDICT}\n")
    stale = _ship_comment_opening(sha) + "\nsuperseded finding\n"
    _seed_comment(tmp_path, "901", stale, author="shipper")
    _seed_comment(tmp_path, "902", stale, author="shipper")

    assert _run_ship(repo, tmp_path, pr_sha=sha, gh_env={"GH_PATCH_FAIL_ID": "901"}).returncode != 0
    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    stored = _stored_comments(tmp_path)
    assert len(stored) == 2, "no third comment is created by the recovery"
    assert all("current finding" in c for c in stored)
    assert all("superseded finding" not in c for c in stored)


def test_refuses_when_the_existing_comments_cannot_be_read(tmp_path: Path) -> None:
    """Posting blind would give up the guarantee the lookup exists to provide."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha, gh_env={"GH_API_FAIL": "1"})

    assert result.returncode != 0
    assert "existing comments" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_on_main(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _git(repo, "checkout", "-q", "main")

    result = _run_ship(repo, tmp_path, pr_sha=_git(repo, "rev-parse", "HEAD"))

    assert result.returncode != 0
    assert "on main" in result.stderr


# --- ADR-0020 §3: the anchor is the reviewed content, not the commit ---------
#
# The safety property must survive exactly: a review of different content, or
# against a different base, still fails mechanically. What is removed is only the
# forced round on a commit that changes no reviewed byte.


def test_accepts_a_review_filed_under_a_different_commit_with_the_same_tree(
    tmp_path: Path,
) -> None:
    """The case §3 exists for: an amended commit reviewed before the amend.

    `git commit --amend -m` produces a new SHA over an identical tree. Under the
    old commit anchor that cost a full review round for a message edit; the
    content the reviewer read is byte-for-byte what is being shipped.
    """
    repo = tmp_path / "repo"
    reviewed_sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, reviewed_sha, "adversarial", f"reviewed this tree\n{_VERDICT}\n")

    # Amend the message only; the tree is untouched.
    _git(repo, "commit", "-q", "--amend", "-m", "change (reworded)")
    amended_sha = _git(repo, "rev-parse", "HEAD")
    assert amended_sha != reviewed_sha, "the amend must produce a new commit"
    assert _git(repo, "rev-parse", f"{amended_sha}^{{tree}}") == _git(
        repo, "rev-parse", f"{reviewed_sha}^{{tree}}"
    ), "the amend must leave the tree identical"

    result = _run_ship(repo, tmp_path, pr_sha=amended_sha)

    assert result.returncode == 0, result.stderr
    assert "reviewed this tree" in (tmp_path / "comment.md").read_text()


def test_refuses_when_the_tree_changed_even_under_the_same_base(tmp_path: Path) -> None:
    """A review of different content is stale, however it is filed.

    The artifact here names the current commit and the correct base — only the
    recorded tree differs. Dropping the tree check would accept it.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", tree="0" * 40)

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "different content" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_refuses_when_the_base_moved_even_though_the_tree_matches(tmp_path: Path) -> None:
    """Both conditions are required; the tree alone is not enough.

    A rebase onto a moved base genuinely changes the diff under review, so it
    correctly re-reviews. The artifact here records the right tree and a base
    that is no longer this PR's merge base.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", base_sha="0" * 40)

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert "different base" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_the_failure_message_distinguishes_content_moved_from_base_moved(
    tmp_path: Path,
) -> None:
    """ADR-0020's "Harder" note: a generic error reads as the old one.

    The tree comparison is a second thing ship can refuse on, and an author who
    cannot tell which condition failed cannot tell whether to re-review or to
    rebase.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", tree="0" * 40)
    tree_only = _run_ship(repo, tmp_path, pr_sha=sha).stderr

    shutil.rmtree(repo / ".review")
    _record_review(repo, sha, "adversarial", base_sha="0" * 40)
    base_only = _run_ship(repo, tmp_path, pr_sha=sha).stderr

    assert "different content" in tree_only
    assert "different base" not in tree_only
    assert "different base" in base_only
    assert "different content" not in base_only


def test_refuses_a_genuine_content_change_the_adr_does_not_cover(tmp_path: Path) -> None:
    """The `05ca4fe` case ADR-0020 §3 is explicit about *not* covering.

    A scope cut changes the tree, so it produces a different diff and genuinely
    warrants a fresh review. An implementation that accepted a review across a
    real content change would break the guarantee while appearing to work — the
    remedy for that case is §2's terminal-state rule, not this clause.
    """
    repo = tmp_path / "repo"
    reviewed_sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, reviewed_sha, "adversarial")

    # A real edit on top of the reviewed commit — the scope cut.
    (repo / "f.txt").write_text("two\nplus a scope cut\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-qm", "cut scope as asked")
    cut_sha = _git(repo, "rev-parse", "HEAD")

    result = _run_ship(repo, tmp_path, pr_sha=cut_sha)

    assert result.returncode != 0
    assert "different content" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_accepts_a_revert_that_returns_the_tree_to_a_reviewed_state(tmp_path: Path) -> None:
    """A revert back to reviewed content costs no round: no byte differs.

    Three commits, where the third undoes the second — the tree at HEAD equals
    the tree at the reviewed first commit, so the review still covers it.
    """
    repo = tmp_path / "repo"
    reviewed_sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, reviewed_sha, "adversarial", f"covers this content\n{_VERDICT}\n")

    (repo / "f.txt").write_text("an experiment\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-qm", "try something")
    _git(repo, "revert", "--no-edit", "HEAD")
    head_sha = _git(repo, "rev-parse", "HEAD")

    assert _git(repo, "rev-parse", f"{head_sha}^{{tree}}") == _git(
        repo, "rev-parse", f"{reviewed_sha}^{{tree}}"
    ), "the revert must restore the reviewed tree"

    result = _run_ship(repo, tmp_path, pr_sha=head_sha)

    assert result.returncode == 0, result.stderr
    assert "covers this content" in (tmp_path / "comment.md").read_text()


def test_a_core_change_still_needs_the_architecture_lens_under_the_tree_anchor(
    tmp_path: Path,
) -> None:
    """ADR-0020 relaxes neither required lens — only what counts as covering.

    An adversarial review matching the tree is not sufficient for a contract
    change, whatever commit it is filed under.
    """
    repo = tmp_path / "repo"
    reviewed_sha = _init_repo(repo, touches_core=True)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, reviewed_sha, "adversarial")
    _git(repo, "commit", "-q", "--amend", "-m", "reworded")
    amended_sha = _git(repo, "rev-parse", "HEAD")

    result = _run_ship(repo, tmp_path, pr_sha=amended_sha)

    assert result.returncode != 0
    assert "architecture" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_a_core_change_ships_when_both_lenses_cover_the_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    reviewed_sha = _init_repo(repo, touches_core=True)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, reviewed_sha, "adversarial")
    _record_review(repo, reviewed_sha, "architecture")
    _git(repo, "commit", "-q", "--amend", "-m", "reworded")
    amended_sha = _git(repo, "rev-parse", "HEAD")

    result = _run_ship(repo, tmp_path, pr_sha=amended_sha)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "comment.md").exists()


def test_prefers_the_artifact_filed_under_the_current_head(tmp_path: Path) -> None:
    """Several commits can carry a review of one tree; the current one wins.

    A reader comparing the posted comment against the PR head should not see a
    discrepancy when there is a review filed under that exact commit.
    """
    repo = tmp_path / "repo"
    old_sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, old_sha, "adversarial", f"the older record\n{_VERDICT}\n")
    _git(repo, "commit", "-q", "--amend", "-m", "reworded")
    head_sha = _git(repo, "rev-parse", "HEAD")
    _record_review(repo, head_sha, "adversarial", f"the current record\n{_VERDICT}\n")

    result = _run_ship(repo, tmp_path, pr_sha=head_sha)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "the current record" in posted
    assert "the older record" not in posted


def test_renders_the_aggregate_into_the_posted_comment(tmp_path: Path) -> None:
    """ADR-0020 §2: the human at merge sees the aggregate the author saw.

    ship strips the provenance line before posting, so without explicit
    rendering the round count and churn ratio would never reach the PR.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    review_dir = repo / ".review"
    review_dir.mkdir(exist_ok=True)
    base_sha = _git(repo, "merge-base", "main", sha)
    tree = _git(repo, "rev-parse", f"{sha}^{{tree}}")
    (review_dir / f"{sha}-adversarial.md").write_text(
        f"<!-- persona=adversarial base=main base_sha={base_sha} sha={sha} tree={tree} "
        f"round=7 net_lines=320 churn_lines=2560 churn_ratio=8.0 commits=58 "
        f"supersedes=ADR-0004:175 -->\na finding\n{_VERDICT}\n"
    )

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "round 7" in posted
    assert "320 lines net" in posted
    assert "58 commit(s)" in posted
    assert "churn 8.0" in posted
    assert "ADR-0004 (175 lines)" in posted
    # Still no raw provenance line — the aggregate is rendered, not leaked.
    assert "base_sha=" not in posted


def test_carries_the_lower_bound_caveat_to_the_pr(tmp_path: Path) -> None:
    """Issue #97: a churn figure computed after a rewrite is a floor.

    The whole point of §2 is that the reviewer at merge holds the aggregate the
    author held. A ratio that silently counts only the work since the squash
    reads as "little rework happened" on exactly the branch that was reworked
    enough to be worth squashing, so the caveat has to travel with the number.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", churn_bound="lower")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "churn ≥1.0" in posted, "the ratio is shown as a floor, not a measurement"
    assert "lower bound" in posted
    assert "history rewritten" in posted


def test_reports_the_churn_ratio_plainly_when_no_history_was_rewritten(tmp_path: Path) -> None:
    """The caveat must be absent where false, or it stops carrying meaning."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "churn 1.0" in posted, "the plain ratio, with no floor marker before it"
    assert "churn ≥" not in posted
    assert "lower bound" not in posted


def test_carries_the_unmeasured_binary_count_to_the_pr(tmp_path: Path) -> None:
    """Issue #100: a binary change must not read on the PR as a no-op either."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", binary_files=3)

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    assert "3 binary file(s) unmeasured" in (tmp_path / "comment.md").read_text()


def test_an_unmeasurable_ratio_on_a_rewritten_branch_is_not_rendered_as_a_number(
    tmp_path: Path,
) -> None:
    """The two caveats combine: no measurable lines *and* a rewritten history.

    A binary-only or rename-only state reports no ratio at all, so decorating
    `n/a` with a floor marker and a multiplication sign would put noise in the one
    line that exists to be read
    at a glance. The rewritten-history caveat is still true and is stated on its
    own.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", churn_bound="lower")
    # Rewrite the ratio to the unmeasurable form the real script emits when the
    # diff touches no text lines.
    artifact = repo / ".review" / f"{sha}-adversarial.md"
    artifact.write_text(artifact.read_text().replace("churn_ratio=1.0", "churn_ratio=n/a"))

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "churn n/a" in posted
    assert "≥n/a" not in posted
    assert "n/a\u00d7" not in posted
    # The rewrite is still reported — it is a separate fact from the ratio.
    assert "history rewritten" in posted


def test_carries_binary_churn_absent_from_the_final_diff(tmp_path: Path) -> None:
    """A binary added and reverted inside the branch is still unmeasured work.

    It leaves the net diff, so only the churn count records it — and §2 is that
    the reviewer at merge sees what the author saw.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", binary_churn=2)

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    assert "2 binary change(s) unmeasured" in (tmp_path / "comment.md").read_text()


def test_omits_the_binary_caveat_when_the_diff_has_no_binary_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    assert "unmeasured" not in (tmp_path / "comment.md").read_text()


def test_posts_without_an_aggregate_when_the_artifact_predates_it(tmp_path: Path) -> None:
    """An artifact with a base and tree but no aggregate still ships.

    The aggregate is advisory; a missing one must omit the line, not print
    blanks and not refuse.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    review_dir = repo / ".review"
    review_dir.mkdir(exist_ok=True)
    base_sha = _git(repo, "merge-base", "main", sha)
    tree = _git(repo, "rev-parse", f"{sha}^{{tree}}")
    (review_dir / f"{sha}-adversarial.md").write_text(
        f"<!-- persona=adversarial base=main base_sha={base_sha} sha={sha} tree={tree} -->\n"
        f"a finding\n{_VERDICT}\n"
    )

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "a finding" in posted
    assert "round" not in posted


def test_refuses_a_provenance_field_with_trailing_garbage(tmp_path: Path) -> None:
    """A malformed field must mismatch, not be silently trimmed to a valid hash.

    Capturing the value as `[0-9a-f]*` stops at the first non-hex byte, so
    `base_sha=<expected>junk` would yield exactly the expected hash and compare
    equal — accepting an artifact whose recorded field is not that hash at all.
    The field is read up to the next space for this reason.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")
    artifact = repo / ".review" / f"{sha}-adversarial.md"
    base_sha = _git(repo, "merge-base", "main", sha)
    artifact.write_text(
        artifact.read_text().replace(f"base_sha={base_sha}", f"base_sha={base_sha}junk")
    )

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert not (tmp_path / "comment.md").exists()


def test_refuses_a_tree_field_with_trailing_garbage(tmp_path: Path) -> None:
    """Same defect on the field that carries the content anchor itself."""
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial")
    artifact = repo / ".review" / f"{sha}-adversarial.md"
    tree = _git(repo, "rev-parse", f"{sha}^{{tree}}")
    artifact.write_text(artifact.read_text().replace(f"tree={tree}", f"tree={tree}junk"))

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode != 0
    assert not (tmp_path / "comment.md").exists()


def test_base_sha_is_never_read_as_the_sha_field(tmp_path: Path) -> None:
    """The field name is space-anchored, so `base_sha=` cannot match `sha=`.

    Without the anchor the two fields are confusable, and the base check would
    silently compare the wrong value.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    # A correct artifact: if `sha=` were read as the base, this would refuse.
    _record_review(repo, sha, "adversarial")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr


def test_prefers_a_complete_artifact_over_an_incomplete_one_for_the_same_tree(
    tmp_path: Path,
) -> None:
    """A superseded incomplete artifact must not refuse a ship a valid one covers.

    Two commits can carry a review of one tree. Taking whichever the glob yielded
    first meant a truncated older artifact blocked the ship even though a
    complete review of exactly this content existed. The verdict check is a test
    of the review, not a way to lose one.
    """
    repo = tmp_path / "repo"
    old_sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    # The stale artifact is the truncated one. This is the common shape of the
    # problem; the discriminating case — where the *HEAD-named* artifact is the
    # truncated one — is the test below, which is what actually fails if
    # completeness stops outranking the filename.
    _record_review(repo, old_sha, "adversarial", "half a fin\n")
    _git(repo, "commit", "-q", "--amend", "-m", "reworded")
    head_sha = _git(repo, "rev-parse", "HEAD")
    _record_review(repo, head_sha, "adversarial", f"the complete review\n{_VERDICT}\n")

    result = _run_ship(repo, tmp_path, pr_sha=head_sha)

    assert result.returncode == 0, result.stderr
    assert "the complete review" in (tmp_path / "comment.md").read_text()


def test_completeness_outranks_being_filed_under_the_head_commit(tmp_path: Path) -> None:
    """The HEAD-named artifact is preferred only among equally complete ones.

    Here the HEAD-named one is the truncated one, so the complete review filed
    under the pre-amend commit must win.
    """
    repo = tmp_path / "repo"
    old_sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, old_sha, "adversarial", f"the complete review\n{_VERDICT}\n")
    _git(repo, "commit", "-q", "--amend", "-m", "reworded")
    head_sha = _git(repo, "rev-parse", "HEAD")
    _record_review(repo, head_sha, "adversarial", "half a fin\n")

    result = _run_ship(repo, tmp_path, pr_sha=head_sha)

    assert result.returncode == 0, result.stderr
    assert "the complete review" in (tmp_path / "comment.md").read_text()


def test_still_refuses_when_every_covering_artifact_is_incomplete(tmp_path: Path) -> None:
    """Preferring a complete artifact must not become "accept an incomplete one"."""
    repo = tmp_path / "repo"
    old_sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, old_sha, "adversarial", "half a fin\n")
    _git(repo, "commit", "-q", "--amend", "-m", "reworded")
    head_sha = _git(repo, "rev-parse", "HEAD")
    _record_review(repo, head_sha, "adversarial", "also truncated\n")

    result = _run_ship(repo, tmp_path, pr_sha=head_sha)

    assert result.returncode != 0
    assert "does not end in a verdict" in result.stderr
    assert not (tmp_path / "comment.md").exists()
