"""Tests for ``scripts/clone_sync.py`` (issue #1390).

Two refusals carry the whole safety story, and both are asserted here in the
direction that costs something when it is wrong: a clone that is not on ``main``
and clean is never written to, and a path git *tracks* in the target is never
overwritten. The second is an error rather than a skip, because it means the
documented list has come to name a checked-in file.

The cleanliness test excludes the synced files themselves — they are exactly what
is expected to differ between clones — and that exclusion is the one that could
quietly turn "clean" into "clean enough", so it is pinned from both sides.

Both refusals are decided and then acted on, and issue #1409 is about the gap
between the two. Three things are pinned here, each against a different actor in
that gap: the lock is *held while the copy writes*, a second sync *waits* for it,
and a target that stops being free between the decision and the first byte — a
person, who holds no lock — is refused. The hooks stand in for those actors in
one process, because what has to be observed is the ordering rather than a second
interpreter.
"""

from __future__ import annotations

import fcntl
import os
import sys
import threading
from pathlib import Path

import pytest

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


def _in_process(source: Path, listing: Path, *args: str) -> int:
    """Run the sync in this interpreter, so a hook can be planted in it."""
    return int(_MODULE.main(["--from", str(source), "--list", str(listing), *args]))


def _open_lock(clone: Path) -> int:
    """Open the clone's sync lock on a descriptor of this test's own."""
    return os.open(clone / ".git" / _MODULE.LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)


def _lock_is_held(clone: Path) -> bool:
    """Whether something else holds the clone's sync lock right now.

    ``flock`` is per open file description, not per process, so a descriptor
    opened here contends with the sync's own even inside one interpreter.
    """
    fd = _open_lock(clone)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


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


def test_a_refusal_on_a_later_path_leaves_the_target_untouched(tmp_path: Path) -> None:
    # Copying as it checks would leave a clone half-synced, disagreeing with both
    # the primary and itself — the drift this recipe exists to remove.
    source, (sibling,) = _clones(tmp_path, 2)
    (sibling / ".mcp.json").write_text("checked in\n")
    git(sibling, "add", "-f", ".mcp.json")
    git(sibling, "commit", "-qm", "track the second one")
    listing = _list_file(tmp_path, ".env", ".mcp.json")

    status, _, err = _sync(source, listing)

    assert status == 1
    assert "git tracks .mcp.json" in err
    assert not (sibling / ".env").exists()


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    source, (sibling,) = _clones(tmp_path, 2)
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing, "--dry-run")

    assert status == 0
    assert "would copy .env" in out
    assert not (sibling / ".env").exists()


def test_a_copy_leaves_no_temporary_behind_and_replaces_atomically(tmp_path: Path) -> None:
    # `shutil.copy2` straight onto the destination truncates before it writes, so
    # an agent already running in the target can read a half-written `.env`.
    source, (sibling,) = _clones(tmp_path, 2)
    (sibling / ".env").write_text("old\n")
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing)

    assert status == 0, out
    assert (sibling / ".env").read_text() == "ASSISTANT_X=1\n"
    assert [p.name for p in sibling.iterdir() if "clone-sync" in p.name] == []


def test_the_temporary_file_is_created_by_the_sync_and_not_claimed(tmp_path: Path) -> None:
    # A temporary named from the destination is predictable, so it can be
    # pre-created as a symlink out of the clone — reintroducing one step later
    # exactly what the destination check stops. The name is unguessable and the
    # file is opened O_EXCL, so a squatted name cannot be the one written to.
    source, (sibling,) = _clones(tmp_path, 2)
    outside = tmp_path / "outside.txt"
    outside.write_text("not yours\n")
    # Ignored, so the squatted names do not simply make the clone read as dirty —
    # the temporary's own construction is what has to stop this.
    (sibling / ".gitignore").write_text(".review/\n.env.clone-sync*\n")
    git(sibling, "commit", "-aqm", "ignore the squat")
    for guess in (f".env.clone-sync.{os.getpid()}", ".env.clone-sync"):
        (sibling / guess).symlink_to(outside)
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing)

    assert status == 0, out
    assert outside.read_text() == "not yours\n"
    assert (sibling / ".env").read_text() == "ASSISTANT_X=1\n"


def test_a_copied_file_keeps_the_sources_mode(tmp_path: Path) -> None:
    # mkstemp creates at 0600, which is not the mode the file should land with.
    source, (sibling,) = _clones(tmp_path, 2)
    (source / ".env").chmod(0o640)
    listing = _list_file(tmp_path, ".env")

    _sync(source, listing)

    assert (sibling / ".env").stat().st_mode & 0o777 == 0o640


def test_a_large_file_is_streamed_rather_than_read_whole(tmp_path: Path) -> None:
    # Not a size test — a content test that the streaming path is byte-exact.
    source, (sibling,) = _clones(tmp_path, 2)
    payload = bytes(range(256)) * 8192
    (source / ".env").write_bytes(payload)
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing)

    assert status == 0, out
    assert (sibling / ".env").read_bytes() == payload


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


def test_an_explicit_selector_cannot_escape_the_sibling_root(tmp_path: Path) -> None:
    # A selector is pasted straight into a path, and `<base>-../../victim`
    # resolves clean out of the sibling root — which would copy credentials into
    # any unrelated checkout that happens to be on `main` and clean.
    source, _ = _clones(tmp_path, 2)
    victim = tmp_path / "victim"
    init_repo(victim)
    listing = _list_file(tmp_path, ".env")

    status, _, err = _sync(source, listing, "../../victim")

    assert status == 1
    assert "not a clone number" in err
    assert not (victim / ".env").exists()


@pytest.mark.parametrize("selector", ["2a", "-1", "", "1/2"])
def test_only_digits_name_a_clone(tmp_path: Path, selector: str) -> None:
    source, _ = _clones(tmp_path, 2)
    listing = _list_file(tmp_path, ".env")

    status, _, err = _sync(source, listing, selector)

    assert status == 1
    assert "not a clone number" in err


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


def test_the_lock_is_held_while_the_copy_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The decision and the write have to be one turn per target. Asserted at the
    # moment of the write itself, because a lock taken and released around the
    # decision would leave exactly the window this closes.
    source, (sibling,) = _clones(tmp_path, 2)
    listing = _list_file(tmp_path, ".env")
    replace = _MODULE._replace_atomically
    held: list[bool] = []

    def watching(src: Path, dst: Path) -> None:
        held.append(_lock_is_held(sibling))
        replace(src, dst)

    monkeypatch.setattr(_MODULE, "_replace_atomically", watching)

    assert _in_process(source, listing) == 0
    assert held == [True]
    assert not _lock_is_held(sibling)


def test_a_second_sync_of_one_target_waits_for_the_first(tmp_path: Path) -> None:
    # Two syncs from different source clones could each read one target as free
    # and interleave their files, leaving it with `.env` from one and `.mcp.json`
    # from the other. A thread rather than a second process: the lock is on the
    # descriptor, so holding it here is holding it against the sync.
    source, (sibling,) = _clones(tmp_path, 2)
    listing = _list_file(tmp_path, ".env")
    finished: list[int] = []
    fd = _open_lock(sibling)
    fcntl.flock(fd, fcntl.LOCK_EX)
    waiting = threading.Thread(target=lambda: finished.append(_in_process(source, listing)))
    try:
        waiting.start()
        waiting.join(0.5)
        assert waiting.is_alive(), "the second sync did not wait for the lock"
        assert not (sibling / ".env").exists()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    waiting.join(30)
    assert not waiting.is_alive()
    assert finished == [0]
    assert (sibling / ".env").read_text() == "ASSISTANT_X=1\n"


def test_a_target_that_stops_being_free_before_the_write_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The lock keeps another sync out, but nobody else takes it: a person working
    # in the target holds nothing. So the freshness test is taken again at the
    # last moment before the first byte, and this is that moment arriving on a
    # clone that has since become someone's.
    source, (sibling,) = _clones(tmp_path, 2)
    listing = _list_file(tmp_path, ".env", ".mcp.json")
    tracked = _MODULE.is_tracked

    def busying(clone: Path, relative: str) -> bool:
        (sibling / "someones-work.txt").write_text("mid-flight\n")
        return bool(tracked(clone, relative))

    monkeypatch.setattr(_MODULE, "is_tracked", busying)

    assert _in_process(source, listing) == 1
    assert "stopped being free" in capsys.readouterr().err
    assert not (sibling / ".env").exists()
    assert not (sibling / ".mcp.json").exists()


def test_a_file_of_the_same_size_but_different_bytes_is_still_copied(tmp_path: Path) -> None:
    # The size check is a fast reject, never the answer on its own.
    source, (sibling,) = _clones(tmp_path, 2)
    (sibling / ".env").write_text("ASSISTANT_X=2\n")
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing)

    assert status == 0, out
    assert "copied .env" in out
    assert (sibling / ".env").read_text() == "ASSISTANT_X=1\n"


def test_a_difference_past_the_first_chunk_is_still_a_difference(tmp_path: Path) -> None:
    source, (sibling,) = _clones(tmp_path, 2)
    payload = b"x" * (_MODULE._COMPARE_CHUNK * 2 + 7)
    (source / ".env").write_bytes(payload)
    (sibling / ".env").write_bytes(payload[:-1] + b"y")
    listing = _list_file(tmp_path, ".env")

    status, out, _ = _sync(source, listing)

    assert status == 0, out
    assert "copied .env" in out
    assert (sibling / ".env").read_bytes() == payload


def test_deciding_not_to_copy_never_reads_either_file_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Loading two whole files into memory to conclude that nothing needs doing is
    # a cost with no purchase: the comparison is a skip optimisation, and its
    # worst case should not exceed the copy it avoids (issue #1409).
    source, (sibling,) = _clones(tmp_path, 2)
    (sibling / ".env").write_text("ASSISTANT_X=1\n")
    listing = _list_file(tmp_path, ".env")

    def refuse(self: Path) -> bytes:
        raise AssertionError(f"{self} was read whole to decide whether to copy it")

    monkeypatch.setattr(Path, "read_bytes", refuse)

    assert _in_process(source, listing) == 0
    assert "same .env" in capsys.readouterr().out


def test_the_re_test_narrows_the_window_it_cannot_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The disclosure, pinned. A person working in a target holds no lock, so every
    # check before a write is check-then-act against them: someone arriving during
    # the copy is not caught, and the module says that rather than implying it has
    # been closed. This fails the day the claim grows past what the code does.
    source, (sibling,) = _clones(tmp_path, 2)
    listing = _list_file(tmp_path, ".env")
    replace = _MODULE._replace_atomically

    def arriving(src: Path, dst: Path) -> None:
        (sibling / "someones-work.txt").write_text("arrived mid-copy\n")
        replace(src, dst)

    monkeypatch.setattr(_MODULE, "_replace_atomically", arriving)

    assert _in_process(source, listing) == 0
    assert (sibling / ".env").read_text() == "ASSISTANT_X=1\n"
