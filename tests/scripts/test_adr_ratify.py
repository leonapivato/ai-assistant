"""Tests for ``scripts/adr_ratify.py`` and the ratify exemption in ``ship``.

ADR-0165 moves an ADR's number and its ratification to merge time: the lane's PR
is the ADR alone, unnumbered and ``Proposed``, and one mechanical commit at merge
takes ``max(main) + 1``, renames the file, substitutes the ``ADR-XXXX``
self-references, flips ``Status`` and stamps the date. That commit is exempt from
a fresh review round **iff its diff is exactly that shape**.

So the exemption is worth exactly what the recognition is worth, and this file is
weighted accordingly. The positive case is one test; most of what follows is a
commit that looks like a ratification and is not — a second path touched, one
further byte in the ADR, a number already taken, a slug that moved — and each of
those must come back *unrecognised*. A recogniser that is generous by one case is
a way to merge unreviewed content while `ship` reports a green review, which is
the failure ADR-0020 and ADR-0027 exist to prevent.

The last two tests close the loop through ``ship.sh`` itself rather than through
the shape function alone: the exemption is only real if the script that refuses
the ship honours it, and only safe if an ordinary commit on the same branch still
costs its round.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_ship import _VERDICT, _fake_gh, _git, _init_repo, _record_review, _run_ship

if TYPE_CHECKING:
    from types import ModuleType

_SCRIPT = Path(__file__).parents[2] / "scripts" / "adr_ratify.py"

_PROPOSED = """\
# XXXX. A decision worth recording

- Status: Proposed
- Date: 2026-01-01

## Context

ADR-XXXX exists because of something. ADR-0001 already said a related thing.

## Decision

ADR-XXXX §1 rules. A body line quoting a header field, `- Status: Proposed`,
which is not this ADR's own and must survive untouched.

## Consequences

Refs ADR-XXXX.
"""


def _load() -> ModuleType:
    """Import the script as a module so its functions can be called directly."""
    spec = importlib.util.spec_from_file_location("adr_ratify", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MODULE = _load()


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the script's CLI inside ``repo``."""
    return subprocess.run(  # noqa: S603  # fixed argv, no shell
        [sys.executable, str(_SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


# --- The transform: what "exactly that shape" means --------------------------


def test_renders_the_four_edits_and_nothing_else() -> None:
    out = _MODULE.render_ratified(_PROPOSED, 166, "2026-08-20")

    assert out.splitlines()[0] == "# 166. A decision worth recording"
    assert "- Status: Accepted" in out
    assert "- Date: 2026-08-20" in out
    assert "ADR-0166 §1 rules." in out
    # The heading takes the number unpadded and the citations take it padded,
    # which is the corpus's own split, not a preference.
    assert "# 0166." not in out
    assert "ADR-166" not in out
    # Everything the transform does not name is byte-identical.
    assert "ADR-0001 already said a related thing." in out


def test_leaves_a_quoted_status_line_in_the_body_alone() -> None:
    """The header ends at the first ``## ``; ADRs quote each other constantly."""
    out = _MODULE.render_ratified(_PROPOSED, 166, "2026-08-20")

    assert out.count("- Status: Accepted") == 1
    assert "`- Status: Proposed`," in out


def test_refuses_a_document_that_is_already_numbered() -> None:
    already = _PROPOSED.replace("# XXXX.", "# 166.")

    with pytest.raises(_MODULE.ShapeError, match="unnumbered ADR heading"):
        _MODULE.render_ratified(already, 166, "2026-08-20")


def test_refuses_a_document_that_does_not_stand_proposed() -> None:
    accepted = _PROPOSED.replace("- Status: Proposed\n", "- Status: Accepted\n", 1)

    with pytest.raises(_MODULE.ShapeError, match="expected exactly 1"):
        _MODULE.render_ratified(accepted, 166, "2026-08-20")


def test_refuses_when_a_placeholder_survives_the_substitution() -> None:
    """``XXXX`` is reserved for the ADR's own number, and the refusal is loud.

    A half-numbered document is the one outcome worth failing over: it merges
    looking ratified while still carrying a placeholder nobody will resolve.
    """
    displays_the_form = _PROPOSED.replace(
        "## Consequences",
        "## Consequences\n\nThe template writes `Superseded by ADR-` plus XXXX.\n",
    )

    with pytest.raises(_MODULE.ShapeError, match="survives the substitution"):
        _MODULE.render_ratified(displays_the_form, 166, "2026-08-20")


def test_refuses_a_date_that_is_not_an_iso_date() -> None:
    with pytest.raises(_MODULE.ShapeError, match="not YYYY-MM-DD"):
        _MODULE.render_ratified(_PROPOSED, 166, "20 August 2026")


@pytest.mark.parametrize(
    "path",
    ["docs/adr/0166-a-slug.md", "docs/adr/template.md", "docs/other/a-slug.md", "a-slug.md"],
)
def test_only_an_unnumbered_adr_file_has_a_slug(path: str) -> None:
    with pytest.raises(_MODULE.ShapeError):
        _MODULE.slug_of(path)


# --- Recognition, over real commits ------------------------------------------


def _adr_repo(repo: Path, *, existing: int = 100) -> Path:
    """A repo on a branch carrying one numbered ADR and one unnumbered draft."""
    origin = repo.parent / "origin.git"
    git = shutil.which("git")
    assert git is not None
    subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
        [git, "init", "-q", "--bare", "-b", "main", str(origin)], check=True
    )
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / "docs" / "adr" / f"{existing:04d}-already-here.md").write_text(
        f"# {existing}. Already here\n\n- Status: Accepted\n- Date: 2026-01-01\n\n## Context\n\nx\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "main")

    _git(repo, "checkout", "-qb", "adr/a-decision")
    (repo / "docs" / "adr" / "a-decision-worth-recording.md").write_text(_PROPOSED)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): draft the decision")
    return repo


def test_ratify_takes_the_next_number_and_the_shape_check_recognises_it(tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path / "repo")

    produced = _run(repo, "ratify", "--date", "2026-08-20")

    assert produced.returncode == 0, produced.stderr
    assert (repo / "docs" / "adr" / "0101-a-decision-worth-recording.md").exists()
    assert not (repo / "docs" / "adr" / "a-decision-worth-recording.md").exists()

    checked = _run(repo, "check-shape", "HEAD")
    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.strip() == "docs/adr/0101-a-decision-worth-recording.md"


def test_the_ratify_commit_message_names_the_number_it_took(tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path / "repo")
    _run(repo, "ratify", "--date", "2026-08-20")

    message = _git(repo, "log", "-1", "--pretty=%B")

    assert message.startswith("docs(adr): ratify ADR-0101")
    assert "Refs: ADR-0101" in message


def test_the_draft_commit_itself_is_not_a_ratification(tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path / "repo")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "expected exactly 2" in checked.stderr


def test_a_second_path_in_the_same_commit_is_not_a_ratification(tmp_path: Path) -> None:
    """The exemption's whole premise is that nothing else rides along."""
    repo = _adr_repo(tmp_path / "repo")
    _run(repo, "ratify", "--date", "2026-08-20")
    (repo / "docs" / "adr" / "0101-a-decision-worth-recording.md").write_text(
        (repo / "docs" / "adr" / "0101-a-decision-worth-recording.md").read_text()
    )
    (repo / "smuggled.py").write_text("PASSWORD = 'hunter2'\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--amend", "--no-edit")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "expected exactly 2" in checked.stderr


def test_one_further_byte_in_the_adr_is_not_a_ratification(tmp_path: Path) -> None:
    """The test is a reconstruction, so an extra edit cannot hide inside it."""
    repo = _adr_repo(tmp_path / "repo")
    _run(repo, "ratify", "--date", "2026-08-20")
    ratified = repo / "docs" / "adr" / "0101-a-decision-worth-recording.md"
    ratified.write_text(ratified.read_text().replace("ADR-0101 §1 rules.", "ADR-0101 §1 rules!"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--amend", "--no-edit")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "some other byte changed" in checked.stderr


def test_a_rename_that_leaves_the_status_proposed_is_not_a_ratification(tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path / "repo")
    _git(
        repo,
        "mv",
        "docs/adr/a-decision-worth-recording.md",
        "docs/adr/0101-a-decision-worth-recording.md",
    )
    _git(repo, "commit", "-qm", "docs(adr): number it")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "some other byte changed" in checked.stderr


@pytest.mark.parametrize(("number", "why"), [(100, "a duplicate"), (102, "a skipped gap")])
def test_only_max_plus_one_is_a_ratification(tmp_path: Path, number: int, why: str) -> None:
    """``--number`` asserts the allocation; it does not choose one.

    Both directions matter and only one of them is a collision. 0100 is already
    taken, so it would produce a duplicate that is invisible in the diff and
    silent in every consumer keyed by number. 0102 collides with *nothing* — it
    is unused, which is exactly why a bare collision test would let it through —
    and it strands 0101 permanently.
    """
    repo = _adr_repo(tmp_path / "repo")

    produced = _run(repo, "ratify", "--number", str(number), "--date", "2026-08-20")

    assert produced.returncode == 1, why
    assert "is not the next number" in produced.stderr

    # And the recogniser refuses one built behind the producer's back, which is
    # what the ship exemption actually rests on.
    (repo / "docs" / "adr" / "a-decision-worth-recording.md").unlink()
    (repo / "docs" / "adr" / f"{number:04d}-a-decision-worth-recording.md").write_text(
        _MODULE.render_ratified(_PROPOSED, number, "2026-08-20")
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): take a number that is not the next one")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "is not the next number" in checked.stderr


@pytest.mark.parametrize("adds_an_adr", [True, False], ids=["adr-landed", "anything-landed"])
def test_refuses_to_ratify_from_a_branch_behind_its_base(
    tmp_path: Path, *, adds_an_adr: bool
) -> None:
    """Staleness is ancestry, not a comparison of ADR numbers.

    The ADR-landing case is the one that changes the number outright. The other
    is the one an ADR-number comparison silently accepts: `main` moved, the
    branch is exactly as stale, and the two number sets are equal — while
    ADR-0165 §2 puts this commit after the final rebase for the whole tree.
    """
    repo = _adr_repo(tmp_path / "repo")
    other = tmp_path / "other"
    _git(repo, "worktree", "add", "-q", "-b", "other", str(other), "main")
    if adds_an_adr:
        (other / "docs" / "adr" / "0101-landed-first.md").write_text(
            "# 101. Landed first\n\n- Status: Accepted\n- Date: 2026-01-01\n\n## Context\n\nx\n"
        )
    else:
        (other / "notes.txt").write_text("something that is not an ADR\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-qm", "chore: land something on main")
    _git(other, "push", "-q", "origin", "other:main")

    produced = _run(repo, "ratify", "--date", "2026-08-20")

    assert produced.returncode == 1
    assert "does not contain it — rebase first" in produced.stderr
    assert not list((repo / "docs" / "adr").glob("01*-a-decision-worth-recording.md"))


def test_a_stale_tracking_ref_does_not_let_the_ratification_through(tmp_path: Path) -> None:
    """The base is fetched live, and it is `main`, with no way to say otherwise.

    A stale `origin/main` passes the ancestry test while `main` itself has moved,
    and the number computed under it is then wrong in a way ``check_commit``
    cannot see — it reads the commit's parent, which is the same stale tree. So
    the run has no ``--no-fetch`` and no ``--base-branch`` to reach for, and this
    pins that: `main` moves on the remote only, the tracking ref is left behind,
    and the run still refuses.
    """
    repo = _adr_repo(tmp_path / "repo")
    stale = _git(repo, "rev-parse", "origin/main")
    other = tmp_path / "other"
    _git(repo, "worktree", "add", "-q", "-b", "other", str(other), "main")
    (other / "docs" / "adr" / "0101-landed-first.md").write_text(
        "# 101. Landed first\n\n- Status: Accepted\n- Date: 2026-01-01\n\n## Context\n\nx\n"
    )
    _git(other, "add", "-A")
    _git(other, "commit", "-qm", "docs(adr): land first")
    _git(other, "push", "-q", "origin", "other:main")
    # The remote has moved; this clone's tracking ref has not been updated.
    _git(repo, "update-ref", "refs/remotes/origin/main", stale)

    produced = _run(repo, "ratify", "--date", "2026-08-20")

    assert produced.returncode == 1
    assert "does not contain it — rebase first" in produced.stderr
    assert not any(p.name.startswith("0101-a-decision") for p in (repo / "docs" / "adr").iterdir())


def test_a_hook_that_rejects_the_commit_leaves_dirt_reported_not_deleted(
    tmp_path: Path,
) -> None:
    """The recovery removes what it made and *reports* what it did not.

    A commit hook that writes a file and then rejects the commit leaves that file
    untracked, so ``git reset --hard`` preserves it and the next run refuses on a
    dirty tree. Saying "restored" and stopping there is misleading. Deleting the
    untracked set to make it true is worse: the clean-tree precondition is a
    point-in-time check, so a file that appeared after it — an editor, a person,
    another process — would be destroyed to tidy up after a failed commit.
    """
    repo = _adr_repo(tmp_path / "repo")
    before = _git(repo, "rev-parse", "HEAD")
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nprintf 'x\\n' > hook-scratch.txt\nexit 1\n")
    hook.chmod(0o755)

    produced = _run(repo, "ratify", "--date", "2026-08-20")

    assert produced.returncode == 1
    assert _git(repo, "rev-parse", "HEAD") == before
    # This run's own artifact is gone, and the ADR is back where it was.
    assert not list((repo / "docs" / "adr").glob("0101-*.md"))
    assert (repo / "docs" / "adr" / "a-decision-worth-recording.md").exists()
    # The hook's file survives, and the message says so rather than claiming a
    # clean tree.
    assert (repo / "hook-scratch.txt").exists()
    assert "left in the working tree" in produced.stderr


def test_the_run_offers_no_way_to_choose_a_different_base() -> None:
    """Every escape here is an escape from the property the exemption rests on."""
    help_text = _run(Path(__file__).parents[2], "ratify", "--help").stdout

    assert "--no-fetch" not in help_text
    assert "--base-branch" not in help_text


def test_a_write_failure_after_the_rename_restores_the_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recovery covers the filesystem, not only the shape self-check.

    Between ``git mv`` and the commit there is one write, and a full disk there
    would leave the rename staged with no commit — the half-applied state the
    recovery exists to undo, arriving as an ``OSError`` rather than a
    ``ShapeError``.
    """
    repo = _adr_repo(tmp_path / "repo")
    before = _git(repo, "rev-parse", "HEAD")
    monkeypatch.chdir(repo)

    def _no_space(*_args: object, **_kwargs: object) -> str:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", _no_space)
    args = _MODULE._parser().parse_args(["ratify", "--date", "2026-08-20"])

    with pytest.raises(_MODULE.ShapeError, match="branch is restored"):
        _MODULE._ratify(args)

    assert _git(repo, "rev-parse", "HEAD") == before
    assert _git(repo, "status", "--porcelain") == ""
    assert (repo / "docs" / "adr" / "a-decision-worth-recording.md").exists()


# --- Production: the refusals that keep a bad commit from existing -----------


def test_refuses_to_ratify_from_a_dirty_tree(tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path / "repo")
    (repo / "stray.txt").write_text("uncommitted\n")

    produced = _run(repo, "ratify")

    assert produced.returncode == 1
    assert "dirty" in produced.stderr
    assert _git(repo, "log", "-1", "--pretty=%s") == "docs(adr): draft the decision"


def test_refuses_to_ratify_on_main(tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "main")

    produced = _run(repo, "ratify")

    assert produced.returncode == 1
    assert "on main" in produced.stderr


def test_refuses_when_the_branch_carries_no_single_unnumbered_adr(tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path / "repo")
    (repo / "docs" / "adr" / "a-second-draft.md").write_text(_PROPOSED)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): a second draft")

    produced = _run(repo, "ratify")

    assert produced.returncode == 1
    assert "expected exactly one unnumbered ADR" in produced.stderr


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path / "repo")
    before = _git(repo, "rev-parse", "HEAD")

    produced = _run(repo, "ratify", "--dry-run", "--date", "2026-08-20")

    assert produced.returncode == 0, produced.stderr
    assert "0101-a-decision-worth-recording.md" in produced.stdout
    assert _git(repo, "rev-parse", "HEAD") == before
    assert (repo / "docs" / "adr" / "a-decision-worth-recording.md").exists()


# --- The exemption, through ship.sh itself -----------------------------------


def _reviewed_adr_branch(repo: Path, tmp_path: Path) -> str:
    """A reviewed ADR branch in ship's own fixture, with the script available.

    ``ship`` resolves ``scripts/adr_ratify.py`` under the repository it is run
    in, so the fixture carries a real copy: a test that stubbed it would prove
    nothing about the shape actually being recognised.
    """
    _init_repo(repo)
    (repo / "scripts").mkdir()
    shutil.copy(_SCRIPT, repo / "scripts" / "adr_ratify.py")
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / "docs" / "adr" / "a-decision-worth-recording.md").write_text(_PROPOSED)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): draft the decision")
    sha = _git(repo, "rev-parse", "HEAD")
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"a real finding\n{_VERDICT}\n")
    return sha


def test_ship_accepts_the_ratify_commit_without_a_fresh_round(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _reviewed_adr_branch(repo, tmp_path)
    produced = _run(repo, "ratify", "--date", "2026-08-20")
    assert produced.returncode == 0, produced.stderr
    ratified = _git(repo, "rev-parse", "HEAD")

    result = _run_ship(repo, tmp_path, pr_sha=ratified)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "a real finding" in posted
    # The comment claims a review covering the head's PARENT, and says so.
    assert "ADR ratification" in posted
    assert "0001-a-decision-worth-recording.md" in posted


def test_ship_still_refuses_an_ordinary_commit_on_the_same_branch(tmp_path: Path) -> None:
    """The control: the exemption is for one shape, not for ADR branches."""
    repo = tmp_path / "repo"
    _reviewed_adr_branch(repo, tmp_path)
    (repo / "docs" / "adr" / "a-decision-worth-recording.md").write_text(
        _PROPOSED.replace("ADR-XXXX §1 rules.", "ADR-XXXX §1 rules, and §2 does too.")
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): fold a finding")
    changed = _git(repo, "rev-parse", "HEAD")

    result = _run_ship(repo, tmp_path, pr_sha=changed)

    assert result.returncode != 0
    assert "different content" in result.stderr


def test_the_drill_reports_the_exemption_it_granted(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _reviewed_adr_branch(repo, tmp_path)
    _run(repo, "ratify", "--date", "2026-08-20")
    ratified = _git(repo, "rev-parse", "HEAD")

    result = _run_ship(repo, tmp_path, pr_sha=ratified, args=("--drill",))

    assert result.returncode == 0, result.stderr
    assert "ADR ratification" in result.stderr
    assert "computed but not posted" in result.stderr
    # A drill writes nothing, so the exemption is reported before it is spent.
    assert not (tmp_path / "comment.md").exists()
