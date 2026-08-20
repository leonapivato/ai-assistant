"""Tests for ``scripts/adr_ratify.py`` and the ratification exemption in ``ship``.

ADR-0165 exempts exactly one commit shape from a fresh review round: one ADR
file, one changed line, ``- Status: Proposed`` becoming ``- Status: Accepted``,
and no other byte — the ``- Date:`` line included. The exemption is worth exactly
what the recognition is worth, and this file is weighted accordingly. The
positive case is one test; most of what follows is a commit that *looks* like a
ratification and is not — a second path, one further byte, a ratification note
appended, the date restamped, two ADRs at once, a rename — and every one of them
must come back **unrecognised**. A recogniser that is generous by one case is a
way to merge unreviewed content while ``ship`` reports a green review, which is
the failure ADR-0020 and ADR-0027 exist to prevent.

The last group closes the loop through ``ship.sh`` itself rather than through the
shape function alone: the exemption is only real if the script that refuses the
ship honours it, only safe if an ordinary commit on the same branch still costs
its round, and only bounded if the re-anchoring stops after one commit.
"""

from __future__ import annotations

import importlib.util
import os
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
# 101. A decision worth recording

- Status: Proposed
- Date: 2026-01-01

## Context

ADR-0101 exists because of something. ADR-0001 already said a related thing.

## Decision

ADR-0101 §1 rules. A body line quoting a header field, `- Status: Proposed`,
which is not this ADR's own and must survive untouched.

## Consequences

Refs ADR-0101.
"""

_ADR_PATH = "docs/adr/0101-a-decision-worth-recording.md"


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


def _run(
    repo: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the script's CLI inside ``repo``."""
    full = os.environ.copy()
    full.update(env or {})
    return subprocess.run(  # noqa: S603  # fixed argv, no shell
        [sys.executable, str(_SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=full,
    )


# --- The transform: what "exactly that shape" means --------------------------


def test_flips_the_one_status_line_and_nothing_else() -> None:
    out = _MODULE.render_ratified(_PROPOSED)

    assert out.count("- Status: Accepted") == 1
    # Exactly one line differs, and it is that one.
    differing = [
        (before, after)
        for before, after in zip(_PROPOSED.split("\n"), out.split("\n"), strict=True)
        if before != after
    ]
    assert differing == [("- Status: Proposed", "- Status: Accepted")]


def test_leaves_the_date_line_alone() -> None:
    """ADR-0165 §2 excluded the date stamp from the shape, on its own review."""
    assert "- Date: 2026-01-01" in _MODULE.render_ratified(_PROPOSED)


def test_leaves_a_quoted_status_line_in_the_body_alone() -> None:
    """The header ends at the first ``## ``; ADRs quote each other constantly."""
    out = _MODULE.render_ratified(_PROPOSED)

    assert "`- Status: Proposed`," in out


def test_refuses_a_document_that_does_not_stand_proposed() -> None:
    already = _PROPOSED.replace("- Status: Proposed\n- Date", "- Status: Accepted\n- Date", 1)

    with pytest.raises(_MODULE.ShapeError, match="expected exactly 1"):
        _MODULE.render_ratified(already)


@pytest.mark.parametrize(
    "status",
    [
        "- Status: Proposed, pending the operator's ruling",
        "- Status: Proposed (do not merge)",
        "- Status: Proposed ",
        "- Status: Proposed | Accepted | Withdrawn",
    ],
)
def test_refuses_a_status_line_that_is_not_exactly_proposed(status: str) -> None:
    """A prefix match here would silently delete the caveat, which is the point of it.

    ``Proposed`` is a bare token (ADR-0070 §4), so anything after it on that line
    is a qualifier — a condition, a note to the merger — and it is exactly the
    text most likely to say "not yet". Rewriting the whole line would delete it
    while the reconstruction still agreed, which is the defect PR #1242's sixth
    round found.
    """
    caveated = _PROPOSED.replace("- Status: Proposed\n- Date", status + "\n- Date", 1)

    with pytest.raises(_MODULE.ShapeError, match="expected exactly 1"):
        _MODULE.render_ratified(caveated)


@pytest.mark.parametrize(
    "path",
    ["docs/adr/template.md", "docs/adr/a-slug.md", "docs/adr/10000-past-the-form.md", "README.md"],
)
def test_only_a_numbered_adr_document_carries_a_number(path: str) -> None:
    with pytest.raises(_MODULE.ShapeError, match="not a numbered ADR"):
        _MODULE.adr_number(path)


def test_the_run_offers_no_way_to_allocate_or_rename() -> None:
    """The numbering half of #1226 §5 is repealed, so none of its escapes exist."""
    help_text = _run(Path(__file__).parents[2], "ratify", "--help").stdout

    for repealed in ("--number", "--base-branch", "--no-fetch", "--date"):
        assert repealed not in help_text


# --- Recognition, over real commits ------------------------------------------


def _adr_repo(repo: Path) -> Path:
    """A repo on a branch carrying one ADR standing ``Proposed``."""
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / "docs" / "adr" / "0100-already-here.md").write_text(
        "# 100. Already here\n\n- Status: Accepted\n- Date: 2026-01-01\n\n## Context\n\nx\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")

    _git(repo, "checkout", "-qb", "adr/a-decision")
    (repo / _ADR_PATH).write_text(_PROPOSED)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): draft the decision")
    return repo


def test_ratify_makes_a_flip_the_shape_check_recognises(tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path / "repo")

    produced = _run(repo, "ratify")

    assert produced.returncode == 0, produced.stderr
    assert "- Status: Accepted" in (repo / _ADR_PATH).read_text()

    checked = _run(repo, "check-shape", "HEAD")
    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.strip() == _ADR_PATH


def test_the_flip_commit_message_names_the_number_and_refs_the_adr(tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path / "repo")
    _run(repo, "ratify")

    message = _git(repo, "log", "-1", "--pretty=%B")

    assert message.startswith("docs(adr): ratify ADR-0101")
    assert "Refs: ADR-0101" in message


def test_the_draft_commit_itself_is_not_a_ratification(tmp_path: Path) -> None:
    """An addition is not a modification: the parent has no blob to rebuild from."""
    repo = _adr_repo(tmp_path / "repo")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "not a modification" in checked.stderr


def test_a_second_path_in_the_same_commit_is_not_a_ratification(tmp_path: Path) -> None:
    """The exemption's whole premise is that nothing else rides along."""
    repo = _adr_repo(tmp_path / "repo")
    _run(repo, "ratify")
    (repo / "smuggled.py").write_text("PASSWORD = 'hunter2'\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--amend", "--no-edit")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "expected exactly 1" in checked.stderr


def test_one_further_byte_in_the_adr_is_not_a_ratification(tmp_path: Path) -> None:
    """The test is a reconstruction, so an extra edit cannot hide inside it."""
    repo = _adr_repo(tmp_path / "repo")
    _run(repo, "ratify")
    adr = repo / _ADR_PATH
    adr.write_text(adr.read_text().replace("ADR-0101 §1 rules.", "ADR-0101 §1 rules!"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--amend", "--no-edit")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "some other byte changed" in checked.stderr


def test_a_ratification_note_in_the_flip_commit_is_not_a_ratification(tmp_path: Path) -> None:
    """ADR-0165 §6's first not-exempted case, and the tempting one.

    A note is free text of unbounded length carrying the author's account of the
    review — exactly the material a reviewer is for. An author who wants the note
    pays the round; both outcomes are correct.
    """
    repo = _adr_repo(tmp_path / "repo")
    _run(repo, "ratify")
    adr = repo / _ADR_PATH
    adr.write_text(
        adr.read_text().replace(
            "- Date: 2026-01-01",
            "- Date: 2026-01-01\n- **Note (2026-01-02): ratified.** Adversarial returned APPROVE.",
        )
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--amend", "--no-edit")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "some other byte changed" in checked.stderr


def test_restamping_the_date_with_the_flip_is_not_a_ratification(tmp_path: Path) -> None:
    """§2 excluded the date line, so a two-line flip is outside the shape.

    A date-*shaped* second line is a value an unreviewed commit chooses, and
    binding it to the commit's author date does not repair that: ``git commit
    --date=…`` and ``GIT_AUTHOR_DATE`` both set the author date, so the trusted
    source is the same hand writing the line.
    """
    repo = _adr_repo(tmp_path / "repo")
    _run(repo, "ratify")
    adr = repo / _ADR_PATH
    adr.write_text(adr.read_text().replace("- Date: 2026-01-01", "- Date: 1970-01-01"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--amend", "--no-edit")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "some other byte changed" in checked.stderr


def test_flipping_two_adrs_at_once_is_not_a_ratification(tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path / "repo")
    second = repo / "docs" / "adr" / "0102-another-decision.md"
    second.write_text(_PROPOSED.replace("# 101.", "# 102.").replace("ADR-0101", "ADR-0102"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): draft another")
    for path in (repo / _ADR_PATH, second):
        path.write_text(path.read_text().replace("- Status: Proposed\n", "- Status: Accepted\n", 1))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): ratify both")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "expected exactly 1" in checked.stderr


def test_a_rename_carrying_the_flip_is_not_a_ratification(tmp_path: Path) -> None:
    """A rename's identity is a function of its paths, so it can cover unseen content."""
    repo = _adr_repo(tmp_path / "repo")
    renamed = repo / "docs" / "adr" / "0101-a-renamed-decision.md"
    renamed.write_text(_PROPOSED.replace("- Status: Proposed\n", "- Status: Accepted\n", 1))
    (repo / _ADR_PATH).unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): ratify and rename")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "expected exactly 1" in checked.stderr


def test_the_same_one_line_flip_outside_docs_adr_is_not_a_ratification(tmp_path: Path) -> None:
    """The shape is not "a file with a Status line"; it is an ADR document."""
    repo = _adr_repo(tmp_path / "repo")
    stray = repo / "notes.md"
    stray.write_text("# A note\n\n- Status: Proposed\n\n## Context\n\nx\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add a note")
    stray.write_text(stray.read_text().replace("Proposed", "Accepted"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "flip the note")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "not a numbered ADR" in checked.stderr


def test_a_binary_adr_is_not_a_ratification(tmp_path: Path) -> None:
    """ADR-0165 §2 excludes a binary change, and a UTF-8 decode does not enforce it.

    ``0x00`` is a valid encoding of U+0000, so a blob carrying an ADR header and
    a NUL in its body decodes cleanly and reconstructs byte for byte — while git
    classifies it as binary and renders no hunks for it.
    """
    repo = _adr_repo(tmp_path / "repo")
    adr = repo / _ADR_PATH
    adr.write_bytes(_PROPOSED.encode().replace(b"## Consequences", b"\x00## Consequences"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): a blob git reads as binary")
    adr.write_bytes(
        adr.read_bytes().replace(b"- Status: Proposed\n- Date", b"- Status: Accepted\n- Date", 1)
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): flip it")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "binary" in checked.stderr


def test_a_merge_commit_is_not_a_ratification(tmp_path: Path) -> None:
    """Two parents means no single blob to rebuild from, so the shape is undefined."""
    repo = _adr_repo(tmp_path / "repo")
    _git(repo, "checkout", "-qb", "side", "main")
    (repo / "side.txt").write_text("side\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "side")
    _git(repo, "checkout", "-q", "adr/a-decision")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")

    checked = _run(repo, "check-shape", "HEAD")

    assert checked.returncode == 1
    assert "2 parents" in checked.stderr


# --- Production: the refusals that keep a bad commit from existing -----------


def test_refuses_to_ratify_from_a_dirty_tree(tmp_path: Path) -> None:
    """The transform reads the *committed* blob, so uncommitted work would be lost.

    An uncommitted edit would be left out of the flip commit while
    ``check-shape`` — which rebuilds from that same committed content — still
    passed. Refusing up front says so.
    """
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


def test_refuses_when_the_branch_carries_no_single_proposed_adr(tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path / "repo")
    second = repo / "docs" / "adr" / "0102-another-decision.md"
    second.write_text(_PROPOSED.replace("# 101.", "# 102."))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): draft another")

    produced = _run(repo, "ratify")

    assert produced.returncode == 1
    assert "expected exactly one ADR standing 'Proposed'" in produced.stderr

    # ...and naming one resolves it, which is what --adr is for.
    named = _run(repo, "ratify", "--adr", _ADR_PATH)
    assert named.returncode == 0, named.stderr


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path / "repo")
    before = _git(repo, "rev-parse", "HEAD")

    produced = _run(repo, "ratify", "--dry-run")

    assert produced.returncode == 0, produced.stderr
    assert _ADR_PATH in produced.stdout
    assert _git(repo, "rev-parse", "HEAD") == before
    assert "- Status: Proposed" in (repo / _ADR_PATH).read_text()


def test_a_hook_that_rejects_the_commit_leaves_dirt_reported_not_deleted(
    tmp_path: Path,
) -> None:
    """The recovery restores the branch and *reports* what it did not make.

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

    produced = _run(repo, "ratify")

    assert produced.returncode == 1
    assert _git(repo, "rev-parse", "HEAD") == before
    # The ADR is back as it was, uncommitted edit and all.
    assert "- Status: Proposed" in (repo / _ADR_PATH).read_text()
    # The hook's file survives, and the message says so rather than claiming a
    # clean tree.
    assert (repo / "hook-scratch.txt").exists()
    assert "left in the working tree" in produced.stderr


def test_a_write_failure_before_the_commit_restores_the_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recovery covers the filesystem, not only the shape self-check.

    A full disk on the one write would leave the file edited with no commit — the
    half-applied state the recovery exists to undo, arriving as an ``OSError``
    rather than a ``ShapeError``.
    """
    repo = _adr_repo(tmp_path / "repo")
    before = _git(repo, "rev-parse", "HEAD")
    monkeypatch.chdir(repo)

    def _no_space(*_args: object, **_kwargs: object) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", _no_space)
    args = _MODULE._parser().parse_args(["ratify"])

    with pytest.raises(_MODULE.ShapeError, match="branch is restored"):
        _MODULE._ratify(args)

    assert _git(repo, "rev-parse", "HEAD") == before
    assert _git(repo, "status", "--porcelain") == ""


# --- The ready guard (ADR-0165 §5, issue #1044) ------------------------------


def _pr_repo(repo: Path, tmp_path: Path, body: str = _PROPOSED) -> Path:
    """A branch whose PR adds one ADR, with a fake ``gh`` answering for it."""
    _init_repo(repo)
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / _ADR_PATH).write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): draft the decision")
    _fake_gh(tmp_path / "bin")
    return repo


def _run_guard(
    repo: Path, tmp_path: Path, *, pr_sha: str | None = None, pr_sha_after: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``check-ready`` with the fake ``gh`` on PATH.

    ``pr_sha`` is what the PR reports as its head; it defaults to local ``HEAD``,
    which is the pushed state the recipe is meant to run in. ``pr_sha_after`` is
    what it reports from the *second* ``headRefOid`` query onward — a head that
    moves while the guard is gathering its evidence.
    """
    env = {
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "GH_PR_SHA": pr_sha or _git(repo, "rev-parse", "HEAD"),
        "GH_CALL_MARK": str(tmp_path / "gh-called"),
    }
    if pr_sha_after is not None:
        env["GH_PR_SHA_2"] = pr_sha_after
    return _run(repo, "check-ready", env=env)


def test_the_ready_guard_refuses_and_names_the_unratified_adr(tmp_path: Path) -> None:
    repo = _pr_repo(tmp_path / "repo", tmp_path)

    guard = _run_guard(repo, tmp_path)

    assert guard.returncode == 1
    assert _ADR_PATH in guard.stderr
    assert "just adr-ratify" in guard.stderr


def test_the_ready_guard_passes_once_the_flip_is_made(tmp_path: Path) -> None:
    repo = _pr_repo(tmp_path / "repo", tmp_path)
    produced = _run(repo, "ratify")
    assert produced.returncode == 0, produced.stderr

    guard = _run_guard(repo, tmp_path)

    assert guard.returncode == 0, guard.stderr


def test_the_ready_guard_refuses_a_flip_that_was_never_pushed(tmp_path: Path) -> None:
    """The guard reads local ``HEAD``, so it must refuse to speak for a PR ahead of it.

    Ratify locally, do not push, and every path below would certify a file only
    this clone holds while GitHub still shows the ADR standing ``Proposed`` — the
    permissive direction, and issue #1044's failure with one extra step.
    """
    repo = _pr_repo(tmp_path / "repo", tmp_path)
    unpushed = _git(repo, "rev-parse", "HEAD")
    assert _run(repo, "ratify").returncode == 0

    guard = _run_guard(repo, tmp_path, pr_sha=unpushed)

    assert guard.returncode == 1
    assert "push first" in guard.stderr


def test_the_ready_guard_refuses_a_head_that_moves_while_it_looks(tmp_path: Path) -> None:
    """The evidence is about the tree the fetch began on; the act is about now.

    So the head is read again immediately before the guard returns success, the
    way ``ship`` re-reads it before its own external write. The window is
    narrowed rather than closed — the recipe is two commands and nothing here can
    observe a push landing after this process exits — which is exactly why the
    read that *can* happen does.
    """
    repo = _pr_repo(tmp_path / "repo", tmp_path)
    assert _run(repo, "ratify").returncode == 0

    guard = _run_guard(repo, tmp_path, pr_sha_after="0" * 40)

    assert guard.returncode == 1
    assert "push first" in guard.stderr


def test_the_ready_guard_still_refuses_a_caveated_proposed_line(tmp_path: Path) -> None:
    """The guard matches by prefix where the transform demands exact equality.

    Both fail closed, in opposite directions: the transform must not rewrite a
    line carrying a caveat, and the guard must not wave one through.
    """
    caveated = _PROPOSED.replace(
        "- Status: Proposed\n- Date", "- Status: Proposed, pending a ruling\n- Date", 1
    )
    repo = _pr_repo(tmp_path / "repo", tmp_path, body=caveated)

    guard = _run_guard(repo, tmp_path)

    assert guard.returncode == 1
    assert _ADR_PATH in guard.stderr


def test_the_ready_guard_sees_an_adr_replaced_by_a_symlink(tmp_path: Path) -> None:
    """A type change is a modification; naming only ``A``/``M`` was the fail-open spelling.

    Git reports an ADR replaced by a symlink as ``T``, and the symlink's blob is
    its target text — which can carry the header line the guard is looking for.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    # The ADR has to be on the BASE for the branch's change to be a type change
    # rather than an addition.
    _git(repo, "checkout", "-q", "main")
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / _ADR_PATH).write_text(_PROPOSED.replace("- Status: Proposed", "- Status: Accepted", 1))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): the ratified decision")
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "rebase", "-q", "main")
    adr = repo / _ADR_PATH
    adr.unlink()
    adr.symlink_to("- Status: Proposed")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): replace it with a link")
    _fake_gh(tmp_path / "bin")

    assert "T" in _git(repo, "diff", "--name-status", "main...HEAD")
    guard = _run_guard(repo, tmp_path)

    assert guard.returncode == 1
    assert _ADR_PATH in guard.stderr


def test_the_ready_guard_ignores_the_adr_template(tmp_path: Path) -> None:
    """``template.md`` is the form, not an ADR, and its header carries the menu."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / "docs" / "adr" / "template.md").write_text(
        "# NNNN. <title>\n\n- Status: Proposed | Accepted | Withdrawn\n- Date: YYYY-MM-DD\n"
        "\n## Context\n\nx\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): adjust the template")
    _fake_gh(tmp_path / "bin")

    guard = _run_guard(repo, tmp_path)

    assert guard.returncode == 0, guard.stderr


# --- The exemption, through ship.sh itself -----------------------------------


def _reviewed_adr_branch(repo: Path, tmp_path: Path) -> str:
    """A reviewed ADR branch in ship's own fixture, with the script available.

    ``ship`` resolves ``scripts/adr_ratify.py`` under the repository it runs in,
    so the fixture carries a real copy: a test that stubbed it would prove
    nothing about the shape actually being recognised.
    """
    _init_repo(repo)
    (repo / "scripts").mkdir()
    shutil.copy(_SCRIPT, repo / "scripts" / "adr_ratify.py")
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / _ADR_PATH).write_text(_PROPOSED)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): draft the decision")
    sha = _git(repo, "rev-parse", "HEAD")
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"a real finding\n{_VERDICT}\n")
    return sha


def test_ship_accepts_the_flip_without_a_fresh_round(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _reviewed_adr_branch(repo, tmp_path)
    produced = _run(repo, "ratify")
    assert produced.returncode == 0, produced.stderr
    ratified = _git(repo, "rev-parse", "HEAD")

    result = _run_ship(repo, tmp_path, pr_sha=ratified)

    assert result.returncode == 0, result.stderr
    posted = (tmp_path / "comment.md").read_text()
    assert "a real finding" in posted
    # ADR-0165 §4: the comment claims a review covering the head's PARENT, and
    # says so — the merge reviewer is the only reader positioned to notice.
    assert "ADR ratification" in posted
    assert _ADR_PATH in posted


def test_ship_still_refuses_an_ordinary_commit_on_the_same_branch(tmp_path: Path) -> None:
    """The control: the exemption is for one shape, not for ADR branches."""
    repo = tmp_path / "repo"
    _reviewed_adr_branch(repo, tmp_path)
    (repo / _ADR_PATH).write_text(_PROPOSED.replace("§1 rules.", "§1 rules, and §2 does too."))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): fold a finding")
    changed = _git(repo, "rev-parse", "HEAD")

    result = _run_ship(repo, tmp_path, pr_sha=changed)

    assert result.returncode != 0
    assert "different content" in result.stderr


def test_the_re_anchoring_is_not_recursive(tmp_path: Path) -> None:
    """ADR-0165 §3: a flip whose parent is a flip earns it for the head alone.

    Two ADRs, flipped in two commits. The review covers the draft tree, which is
    the grandparent — so ``ship`` must refuse, because it re-anchors by exactly
    one commit and then judges that parent on its own content.
    """
    repo = tmp_path / "repo"
    _reviewed_adr_branch(repo, tmp_path)
    second = repo / "docs" / "adr" / "0102-another-decision.md"
    second.write_text(_PROPOSED.replace("# 101.", "# 102.").replace("ADR-0101", "ADR-0102"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs(adr): draft another")
    drafted = _git(repo, "rev-parse", "HEAD")
    _record_review(repo, drafted, "adversarial", f"a real finding\n{_VERDICT}\n")
    assert _run(repo, "ratify", "--adr", _ADR_PATH).returncode == 0
    assert _run(repo, "ratify", "--adr", "docs/adr/0102-another-decision.md").returncode == 0

    result = _run_ship(repo, tmp_path, pr_sha=_git(repo, "rev-parse", "HEAD"))

    assert result.returncode != 0
    assert "different content" in result.stderr


def test_the_drill_reports_the_exemption_it_granted(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _reviewed_adr_branch(repo, tmp_path)
    _run(repo, "ratify")
    ratified = _git(repo, "rev-parse", "HEAD")

    result = _run_ship(repo, tmp_path, pr_sha=ratified, args=("--drill",))

    assert result.returncode == 0, result.stderr
    assert "ADR ratification" in result.stderr
    assert "computed but not posted" in result.stderr
    # A drill writes nothing, so the exemption is reported before it is spent.
    assert not (tmp_path / "comment.md").exists()
