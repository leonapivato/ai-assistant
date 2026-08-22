"""Tests for ``scripts/clone_sync.py`` (issue #1390).

Two refusals carry the whole safety story, and both are asserted here in the
direction that costs something when it is wrong: a clone that is not on ``main``
and clean is never written to, and a path git *tracks* in the target is never
overwritten. The second is an error rather than a skip, because it means the
documented list has come to name a checked-in file.

The cleanliness test excludes the synced files themselves — they are exactly what
is expected to differ between clones — and that exclusion is the one that could
quietly turn "clean" into "clean enough", so it is pinned from both sides.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _operator_recipes import git, init_repo, load, run

_MODULE = load("clone_sync")


def _clones(tmp_path: Path, *numbers: int) -> tuple[Path, list[Path]]:
    """A primary clone and the numbered siblings beside it."""
    projects = tmp_path / "projects"
    source = projects / "ai-assistant"
    init_repo(source)
    (source / ".env").write_text("ASSISTANT_X=1\n")
    (source / ".mcp.json").write_text('{"servers": {}}\n')
    siblings = []
    for n in numbers:
        sibling = projects / f"ai-assistant-{n}"
        init_repo(sibling)
        siblings.append(sibling)
    return source, siblings


def _list_file(tmp_path: Path, *entries: str) -> Path:
    """A per-clone file list naming ``entries``."""
    path = tmp_path / "files.txt"
    path.write_text("# a comment\n\n" + "\n".join(entries) + "\n")
    return path


def _sync(source: Path, listing: Path, *args: str) -> tuple[int, str, str]:
    """Run the sync from ``source`` and return status, stdout and stderr."""
    result = run("clone_sync", ["--from", str(source), "--list", str(listing), *args])
    return result.returncode, result.stdout, result.stderr


def test_copies_the_listed_files_into_a_free_sibling(tmp_path: Path) -> None:
    source, (sibling,) = _clones(tmp_path, 2)
    listing = _list_file(tmp_path, ".env", ".mcp.json")

    status, out, _ = _sync(source, listing)

    assert status == 0, out
    assert (sibling / ".env").read_text() == "ASSISTANT_X=1\n"
    assert (sibling / ".mcp.json").read_text() == '{"servers": {}}\n'
    assert "copied .env" in out


def test_a_sibling_on_a_branch_is_not_written_to(tmp_path: Path) -> None:
    source, (sibling,) = _clones(tmp_path, 2)
    git(sibling, "switch", "-qc", "some/lane")
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing)

    assert status == 0
    assert "SKIPPED — on some/lane, not main" in out
    assert not (sibling / ".env").exists()


def test_a_sibling_with_uncommitted_work_is_not_written_to(tmp_path: Path) -> None:
    source, (sibling,) = _clones(tmp_path, 2)
    (sibling / "f.txt").write_text("someone's work\n")
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing)

    assert status == 0
    assert "uncommitted change(s)" in out
    assert not (sibling / ".env").exists()


def test_the_synced_files_do_not_themselves_make_a_clone_dirty(tmp_path: Path) -> None:
    source, (sibling,) = _clones(tmp_path, 2)
    (sibling / ".env").write_text("stale\n")  # untracked, and on the list
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing)

    assert status == 0, out
    assert "SKIPPED" not in out
    assert (sibling / ".env").read_text() == "ASSISTANT_X=1\n"


def test_a_named_sibling_that_is_not_free_fails_the_run(tmp_path: Path) -> None:
    source, (sibling,) = _clones(tmp_path, 2)
    git(sibling, "switch", "-qc", "some/lane")
    listing = _list_file(tmp_path, ".env")

    status, _, err = _sync(source, listing, "2")

    assert status == 1
    assert "SKIPPED" in err


def test_a_found_sibling_that_is_not_free_is_only_reported(tmp_path: Path) -> None:
    source, (busy, free) = _clones(tmp_path, 2, 3)
    git(busy, "switch", "-qc", "some/lane")
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing)

    assert status == 0
    assert "SKIPPED" in out
    assert (free / ".env").exists()


def test_a_tracked_path_in_the_target_is_never_overwritten(tmp_path: Path) -> None:
    source, (sibling,) = _clones(tmp_path, 2)
    (sibling / ".env").write_text("checked in\n")
    git(sibling, "add", "-f", ".env")
    git(sibling, "commit", "-qm", "track it")
    listing = _list_file(tmp_path, ".env")

    status, _, err = _sync(source, listing)

    assert status == 1
    assert "git tracks .env" in err
    assert (sibling / ".env").read_text() == "checked in\n"


def test_a_symlink_at_the_target_path_is_never_written_through(tmp_path: Path) -> None:
    # `is_tracked` guards a checked-in file, and everything on the list is ignored
    # by definition — so it says nothing about an ignored symlink pointing out of
    # the clone. `shutil.copy2` would follow it and write to the far end.
    source, (sibling,) = _clones(tmp_path, 2)
    outside = tmp_path / "outside.txt"
    outside.write_text("not yours\n")
    (sibling / ".env").symlink_to(outside)
    listing = _list_file(tmp_path, ".env")

    status, _, err = _sync(source, listing)

    assert status == 1
    assert "is a symlink" in err
    assert outside.read_text() == "not yours\n"


def test_a_symlinked_ancestor_is_refused_too(tmp_path: Path) -> None:
    source, (sibling,) = _clones(tmp_path, 2)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    # Ignored, so the clone still reads as clean and the escape check is what
    # has to stop this rather than the freshness test.
    (sibling / ".gitignore").write_text(".review/\nconf\n")
    git(sibling, "commit", "-aqm", "ignore conf")
    (sibling / "conf").symlink_to(outside, target_is_directory=True)
    listing = _list_file(tmp_path, "conf/.env")
    (source / "conf").mkdir()
    (source / "conf" / ".env").write_text("x\n")

    status, _, err = _sync(source, listing)

    assert status == 1
    assert "outside the clone" in err
    assert not (outside / ".env").exists()


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    source, (sibling,) = _clones(tmp_path, 2)
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing, "--dry-run")

    assert status == 0
    assert "would copy .env" in out
    assert not (sibling / ".env").exists()


def test_an_unchanged_file_is_reported_and_not_recopied(tmp_path: Path) -> None:
    source, (sibling,) = _clones(tmp_path, 2)
    (sibling / ".env").write_text("ASSISTANT_X=1\n")
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing)

    assert status == 0
    assert "same .env" in out


def test_a_file_absent_from_the_source_is_reported_not_an_error(tmp_path: Path) -> None:
    source, (sibling,) = _clones(tmp_path, 2)
    listing = _list_file(tmp_path, ".nvmrc")

    status, out, _ = _sync(source, listing)

    assert status == 0
    assert "skip .nvmrc: absent" in out
    assert not (sibling / ".nvmrc").exists()


def test_the_source_clone_is_never_its_own_target(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    source = projects / "ai-assistant-4"
    init_repo(source)
    (source / ".env").write_text("from four\n")
    other = projects / "ai-assistant-2"
    init_repo(other)
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing)

    assert status == 0, out
    assert str(source) not in out
    assert (other / ".env").read_text() == "from four\n"


def test_no_siblings_is_not_a_failure(tmp_path: Path) -> None:
    source, _ = _clones(tmp_path)
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing)

    assert status == 0
    assert "no sibling clones" in out


def test_the_list_refuses_a_path_that_escapes_the_clone(tmp_path: Path) -> None:
    source, _ = _clones(tmp_path, 2)
    listing = _list_file(tmp_path, "../outside")

    status, _, err = _sync(source, listing)

    assert status == 1
    assert "not a path inside a clone" in err


def test_the_shipped_list_names_only_ignored_files() -> None:
    # The list's own promise: nothing in it is committed. A path that became
    # tracked would make every sync fail on the first target, so assert it here
    # rather than discovering it at dispatch time.
    repo = Path(__file__).parents[2]
    for relative in _MODULE.read_list(_MODULE.DEFAULT_LIST):
        assert not _MODULE.is_tracked(repo, relative), relative
