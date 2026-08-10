"""Tests for the restore tool's entry point (ADR-0123 §7, §8).

The round trip these tests drive is the one ADR-0123 §9 proves on *one* machine:
backup, verify, restore into fresh staging, and a directory a hub could be pointed
at. §9's second-machine drill is deliberately not here — it "discharges the
decision" and is an operating act an operator runs, not something a test suite can
stand in for. What is here is everything a test can settle: the refusals, the
publication, and the fact that a refused restore leaves the target untouched.

**Every refusal is asserted together with what it leaves behind.** §7 requires
that a failed run "removes the staging directory and everything it placed in it,
touches the target path not at all, and removes nothing outside the staging
directory", and none of that is visible in an exit code.
"""

from __future__ import annotations

import shutil
import sqlite3
import stat
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.service import artifact, backup, restore
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK
from ai_assistant.service.lock import LOCK_FILENAME

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_KEYPHRASE = "a phrase the operator holds"
_TEST_WORK_FACTOR = 8


@pytest.fixture(autouse=True)
def cheap_key_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Write artifacts at a work factor a test suite can afford."""
    monkeypatch.setattr(backup, "DEFAULT_WORK_FACTOR", _TEST_WORK_FACTOR)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "hub-data"
    directory.mkdir(mode=0o700)
    connection = sqlite3.connect(directory / "memory.db")
    connection.execute("CREATE TABLE t (x)")
    connection.execute("INSERT INTO t VALUES ('a memory')")
    connection.commit()
    connection.close()
    (directory / "notes.txt").write_bytes(b"hello")
    (directory / "sub").mkdir(mode=0o700)
    (directory / "sub" / "plans.db").write_bytes(b"not really a database")
    (directory / LOCK_FILENAME).write_text("4242\n")
    return directory


@pytest.fixture
def keyphrase_file(tmp_path: Path) -> Path:
    path = tmp_path / "phrase"
    path.write_text(f"{_KEYPHRASE}\n")
    return path


@pytest.fixture
def settings(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    loaded = Settings(data_dir=data_dir, embedder=EmbedderKind.HASHING)
    monkeypatch.setattr(backup, "load_settings", lambda: loaded)
    monkeypatch.setattr(restore, "load_settings", lambda: loaded)
    return loaded


@pytest.fixture
def written(settings: Settings, tmp_path: Path, keyphrase_file: Path) -> Path:
    """A real artifact, taken by the real backup tool."""
    destination = tmp_path / "backups" / "a.age"
    destination.parent.mkdir(mode=0o700)
    assert backup.main([str(destination), "--passphrase-file", str(keyphrase_file)]) == EXIT_OK
    return destination


def _restore(written: Path, target: Path, keyphrase_file: Path) -> int:
    return restore.main([str(written), str(target), "--passphrase-file", str(keyphrase_file)])


def _staging_left(parent: Path) -> list[str]:
    return sorted(p.name for p in parent.iterdir() if p.name.startswith("."))


# --------------------------------------------------------------------------- #
# The round trip
# --------------------------------------------------------------------------- #


def test_a_restored_directory_holds_exactly_what_the_backup_carried(
    written: Path, data_dir: Path, tmp_path: Path, keyphrase_file: Path
) -> None:
    """ADR-0123 §1: "Restoring a backup restores every file the artifact carries"."""
    target = tmp_path / "restored"

    assert _restore(written, target, keyphrase_file) == EXIT_OK

    restored = {str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()}
    assert restored == {"memory.db", "notes.txt", "sub/plans.db"}
    assert (target / "memory.db").read_bytes() == (data_dir / "memory.db").read_bytes()
    assert (target / "sub" / "plans.db").read_bytes() == b"not really a database"


def test_a_restored_database_opens_and_holds_what_it_held(
    written: Path, tmp_path: Path, keyphrase_file: Path
) -> None:
    """The point of a whole-file copy: the store the hub would serve, not an export."""
    target = tmp_path / "restored"

    assert _restore(written, target, keyphrase_file) == EXIT_OK

    connection = sqlite3.connect(f"file:{target / 'memory.db'}?mode=ro", uri=True)
    try:
        assert connection.execute("SELECT x FROM t").fetchall() == [("a memory",)]
    finally:
        connection.close()


def test_a_restored_directory_carries_no_lock_and_no_socket(
    written: Path, tmp_path: Path, keyphrase_file: Path
) -> None:
    """§3 keeps process state out, and §7 adds none of its own: "Restore takes no
    instance lock, and creates no lock file".
    """
    target = tmp_path / "restored"

    assert _restore(written, target, keyphrase_file) == EXIT_OK

    assert not (target / LOCK_FILENAME).exists()
    assert not (target / "hub.sock").exists()


def test_a_restored_file_is_owner_only(written: Path, tmp_path: Path, keyphrase_file: Path) -> None:
    """What lands is the plaintext Tier 1 store (ADR-0004 §4, ADR-0123 §7)."""
    target = tmp_path / "restored"

    assert _restore(written, target, keyphrase_file) == EXIT_OK

    assert stat.S_IMODE((target / "memory.db").stat().st_mode) == 0o600
    assert not (target / "sub").stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO)


def test_the_restore_says_what_landed_and_what_is_still_missing(
    written: Path, tmp_path: Path, keyphrase_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§6: "a restored directory is not a working installation, and that is the correct trade"."""
    assert _restore(written, tmp_path / "restored", keyphrase_file) == EXIT_OK

    reported = capsys.readouterr().out
    assert "restored 3 file(s)" in reported
    assert "keyring" in reported


def test_nothing_is_left_beside_the_target_after_a_successful_restore(
    written: Path, tmp_path: Path, keyphrase_file: Path
) -> None:
    """The staging directory becomes the target by one rename, so nothing is orphaned."""
    assert _restore(written, tmp_path / "restored", keyphrase_file) == EXIT_OK

    assert _staging_left(tmp_path) == []


# --------------------------------------------------------------------------- #
# §7's refusals
# --------------------------------------------------------------------------- #


def test_a_target_that_already_exists_is_refused_and_left_alone(
    written: Path, tmp_path: Path, keyphrase_file: Path
) -> None:
    """§7's first clause: restore "replaces nothing"."""
    target = tmp_path / "restored"
    target.mkdir(mode=0o700)
    (target / "important.txt").write_bytes(b"somebody's work")

    assert _restore(written, target, keyphrase_file) == EXIT_DEPLOYMENT

    assert (target / "important.txt").read_bytes() == b"somebody's work"
    assert _staging_left(tmp_path) == []


def test_the_live_data_directory_is_refused_by_name(
    written: Path, data_dir: Path, keyphrase_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§7: "the live path is the one an operator in a hurry actually types".

    The refusal names both paths, and it fires even though the first clause would
    have caught this one too — because the case it exists for is the one where the
    directory does *not* exist and a supervised hub can start in the gap.
    """
    assert _restore(written, data_dir, keyphrase_file) == EXIT_DEPLOYMENT

    reported = capsys.readouterr().err
    assert str(data_dir) in reported
    assert "data directory this environment resolves" in reported


def test_the_live_data_directory_is_refused_even_when_it_does_not_exist(
    written: Path, data_dir: Path, keyphrase_file: Path
) -> None:
    """The case §7's clause is actually written for.

    "Between the refusal check and the rename the target path does not exist,
    which is harmless for an arbitrary fresh path and is not harmless for *the*
    path a supervisor's hub is configured to serve: that hub can start in the gap,
    find an absent directory, and do the documented normal thing — create it and
    initialise an empty store."
    """
    shutil.rmtree(data_dir)

    assert _restore(written, data_dir, keyphrase_file) == EXIT_DEPLOYMENT
    assert not data_dir.exists()


def test_a_target_whose_parent_others_may_write_is_refused_with_its_mode(
    written: Path, tmp_path: Path, keyphrase_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§7: "a directory whose parent strangers may write is not a place to unpack
    every belief the user has accumulated".
    """
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)  # `mkdir`'s mode is masked by the umask; `chmod` is not

    assert _restore(written, shared / "restored", keyphrase_file) == EXIT_DEPLOYMENT

    reported = capsys.readouterr().err
    assert str(shared) in reported
    assert "0777" in reported
    assert not (shared / "restored").exists()


def test_a_wrong_passphrase_leaves_nothing_at_the_target(written: Path, tmp_path: Path) -> None:
    """§7: "a mistyped passphrase … leaves nothing at the target, because nothing was
    ever written there; the staging directory is removed whole".
    """
    wrong = tmp_path / "wrong"
    wrong.write_text("not the phrase\n")
    target = tmp_path / "restored"

    assert _restore(written, target, wrong) == EXIT_DEPLOYMENT

    assert not target.exists()
    assert _staging_left(tmp_path) == []


def test_an_artifact_that_is_not_there_is_refused(tmp_path: Path, keyphrase_file: Path) -> None:
    assert _restore(tmp_path / "absent.age", tmp_path / "restored", keyphrase_file) == (
        EXIT_DEPLOYMENT
    )
    assert not (tmp_path / "restored").exists()


def test_a_damaged_artifact_leaves_nothing_at_the_target(
    written: Path, tmp_path: Path, keyphrase_file: Path
) -> None:
    """§4's authenticated format, reaching the operator as a refusal."""
    damaged = bytearray(written.read_bytes())
    damaged[-1] ^= 0x01
    written.write_bytes(bytes(damaged))
    target = tmp_path / "restored"

    assert _restore(written, target, keyphrase_file) == EXIT_DEPLOYMENT

    assert not target.exists()
    assert _staging_left(tmp_path) == []


def test_a_target_that_appears_during_the_restore_is_not_replaced(
    written: Path, tmp_path: Path, keyphrase_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: "Publication fails rather than replacing anything if the target exists at
    that moment."
    """
    target = tmp_path / "restored"
    original = artifact.verify_materialised

    def verify_then_race(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        target.mkdir(mode=0o700)
        (target / "somebody-elses.txt").write_bytes(b"work")

    monkeypatch.setattr(artifact, "verify_materialised", verify_then_race)

    assert _restore(written, target, keyphrase_file) == EXIT_DEPLOYMENT

    assert sorted(p.name for p in target.iterdir()) == ["somebody-elses.txt"]
    assert _staging_left(tmp_path) == []


def test_the_restore_needs_nothing_from_the_machine_that_took_the_backup(
    written: Path, tmp_path: Path, keyphrase_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5: "Restore never reads the OS keyring, and never requires anything from the
    machine that took the backup."

    Modelled by pointing the environment's data directory somewhere the artifact
    knows nothing about — which is what a recovery machine is — and checking the
    restore still lands.
    """
    elsewhere = tmp_path / "a-different-deployment"
    elsewhere.mkdir(mode=0o700)
    monkeypatch.setattr(
        restore,
        "load_settings",
        lambda: Settings(data_dir=elsewhere, embedder=EmbedderKind.HASHING),
    )
    target = tmp_path / "restored"

    assert _restore(written, target, keyphrase_file) == EXIT_OK

    assert (target / "notes.txt").read_bytes() == b"hello"
