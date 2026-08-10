"""Tests for the backup tool's entry point (ADR-0123 §1, §2, §3, §9, §11).

Named ``_tool`` rather than mirroring ``service/backup.py`` exactly, for the
reason ``test_reembed_tool.py`` states: ``tests/`` carries no ``__init__.py`` and
two test modules with one basename collide at collection.

Every test runs at a low scrypt work factor. ADR-0123 §4 puts the format's work
factor in the artifact's own header, so a reader spends what the artifact declares
— the real default costs half a gigabyte and a second per artifact, and buys this
suite nothing that ``test_agev1.py`` does not already prove.

**What is on test is the decision's refusals**, which is most of it. Each one is
asserted together with what it leaves behind: a refused backup publishes nothing
and removes its temporary file, which is a property no assertion on the exit code
alone can see.
"""

from __future__ import annotations

import errno
import inspect
import os
import resource
import socket
import sqlite3
import stat
from pathlib import Path

import pytest

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.service import artifact, backup
from ai_assistant.service.artifact import materialise, verify_materialised
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock
from ai_assistant.service.refusal import RefusalError
from ai_assistant.wire.address import SOCKET_FILENAME

pytestmark = pytest.mark.integration

_KEYPHRASE = "a phrase the operator holds"
_TEST_WORK_FACTOR = 8


@pytest.fixture(autouse=True)
def cheap_key_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Write artifacts at a work factor a test suite can afford."""
    monkeypatch.setattr(backup, "DEFAULT_WORK_FACTOR", _TEST_WORK_FACTOR)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A data directory with the shape the hub leaves behind: databases and a lock."""
    directory = tmp_path / "hub-data"
    directory.mkdir(mode=0o700)
    _database(directory / "memory.db", "a memory")
    _database(directory / "traces.db", "a trace")
    (directory / "notes.txt").write_bytes(b"hello")
    (directory / LOCK_FILENAME).write_text("4242\n")
    return directory


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
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
    return loaded


def _database(path: Path, value: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (x)")
    connection.execute("INSERT INTO t VALUES (?)", (value,))
    connection.commit()
    connection.close()


def _run(destination: Path, keyphrase_file: Path) -> int:
    return backup.main([str(destination), "--passphrase-file", str(keyphrase_file)])


def _contents(archive: Path, staging: Path) -> dict[str, bytes]:
    """Open an artifact and return what it carries, keyed by relative path."""
    manifest = materialise(archive, passphrase=_KEYPHRASE, staging=staging)
    verify_materialised(staging, manifest)
    return {entry.path: (staging / entry.path).read_bytes() for entry in manifest.files}


def _leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


# --------------------------------------------------------------------------- #
# §1 and §3 — what a backup carries
# --------------------------------------------------------------------------- #


def test_a_backup_carries_every_regular_file_at_any_depth(
    settings: Settings, data_dir: Path, out_dir: Path, keyphrase_file: Path, tmp_path: Path
) -> None:
    """§1's unit is the directory, and it walks to any depth."""
    nested = data_dir / "sub" / "deeper"
    nested.mkdir(parents=True, mode=0o700)
    (nested / "grants.db").write_bytes(b"not really a database")

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_OK

    staging = tmp_path / "check"
    staging.mkdir(mode=0o700)
    assert set(_contents(out_dir / "a.age", staging)) == {
        "memory.db",
        "notes.txt",
        "sub/deeper/grants.db",
    }


def test_the_trace_store_the_lock_and_the_socket_are_excluded(
    settings: Settings, data_dir: Path, out_dir: Path, keyphrase_file: Path, tmp_path: Path
) -> None:
    """§3's three exclusions, with the socket present as a real socket.

    The trace store is excluded because ADR-0119 §12 is absolute; the lock and the
    socket because they are process state and not data. The socket is bound for
    real rather than faked, because §1's second clause refuses an entry that is
    "neither a regular file, nor a directory" — so if the exclusion did not cover
    it, a socket left behind by a killed hub "would otherwise refuse every backup
    taken before the next clean start".
    """
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(data_dir / SOCKET_FILENAME))
    try:
        assert _run(out_dir / "a.age", keyphrase_file) == EXIT_OK
    finally:
        listener.close()

    staging = tmp_path / "check"
    staging.mkdir(mode=0o700)
    carried = set(_contents(out_dir / "a.age", staging))
    assert carried == {"memory.db", "notes.txt"}
    assert "traces.db" not in carried
    assert LOCK_FILENAME not in carried
    assert SOCKET_FILENAME not in carried


def test_an_excluded_paths_sidecars_are_excluded_with_it(settings: Settings) -> None:
    """§3: "A protected store's sidecars are part of the store and never enter an artifact"."""
    excluded = backup._excluded_paths(settings)

    assert {"traces.db", "traces.db-wal", "traces.db-shm", "traces.db-journal"} <= excluded
    assert {LOCK_FILENAME, SOCKET_FILENAME} <= excluded


def test_the_trace_stores_path_comes_from_the_composition_root(
    settings: Settings, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3: the name is read from the module that owns it, never restated here.

    Moving the store at the composition root moves the exclusion with it, which is
    the property §3 asks for — "a later lane renaming the trace store, or splitting
    it, would leave a copier still excluding a file that no longer exists".
    """
    from ai_assistant.app import build_measure_reader  # noqa: PLC0415 - the seam under test

    monkeypatch.setattr(
        backup,
        "build_measure_reader",
        lambda loaded: type(build_measure_reader(loaded))(store=data_dir / "renamed-traces.db"),
    )

    assert "renamed-traces.db" in backup._excluded_paths(settings)
    assert "traces.db" not in backup._excluded_paths(settings)


def test_a_symbolic_link_in_the_data_directory_refuses_the_backup(
    settings: Settings, data_dir: Path, out_dir: Path, keyphrase_file: Path
) -> None:
    """§1: an entry that is not a regular file or a directory refuses, links included."""
    (data_dir / "elsewhere").symlink_to(data_dir / "notes.txt")

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_DEPLOYMENT
    assert _leftovers(out_dir) == []


def test_a_fifo_in_the_data_directory_refuses_the_backup(
    settings: Settings, data_dir: Path, out_dir: Path, keyphrase_file: Path
) -> None:
    """Nothing that is not a regular file can be copied "byte for byte"."""
    os.mkfifo(data_dir / "pipe")

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_DEPLOYMENT
    assert _leftovers(out_dir) == []


# --------------------------------------------------------------------------- #
# §2 — the lock, the sidecars, the fingerprints, the publication
# --------------------------------------------------------------------------- #


def test_a_held_lock_is_refused_immediately(
    settings: Settings,
    data_dir: Path,
    out_dir: Path,
    keyphrase_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§2: "A contended lock is refused immediately … the tool does not retry"."""
    holder = InstanceLock(data_dir / LOCK_FILENAME)
    assert holder.acquire()
    try:
        assert _run(out_dir / "a.age", keyphrase_file) == EXIT_RESTART
    finally:
        holder.release()

    reported = capsys.readouterr().err
    assert str(data_dir / LOCK_FILENAME) in reported
    assert "Stop the hub" in reported
    assert _leftovers(out_dir) == []


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_a_sidecar_anywhere_refuses_the_backup(
    settings: Settings, data_dir: Path, out_dir: Path, keyphrase_file: Path, suffix: str
) -> None:
    """§2: a sidecar means a live or dead-mid-transaction writer, and a torn copy."""
    (data_dir / f"memory.db{suffix}").write_bytes(b"")

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_DEPLOYMENT
    assert _leftovers(out_dir) == []


def test_a_sidecar_beside_an_excluded_store_still_refuses(
    settings: Settings,
    data_dir: Path,
    out_dir: Path,
    keyphrase_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§3 widens §2's scan for this exact case.

    "A sidecar beside an *excluded* file was outside a refusal phrased over files
    the tool would copy, which left the crashed trace store as the one state that
    could reach an artifact."
    """
    (data_dir / "traces.db-wal").write_bytes(b"committed pages")

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_DEPLOYMENT

    assert "Start the hub and stop it cleanly" in capsys.readouterr().err
    assert _leftovers(out_dir) == []


def test_a_file_that_changes_across_the_copy_refuses_the_backup(
    settings: Settings,
    data_dir: Path,
    out_dir: Path,
    keyphrase_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§2's before-and-after fingerprint, with a writer that does not cooperate."""
    original = artifact.write_artifact

    def write_then_meddle(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        (data_dir / "notes.txt").write_bytes(b"world")

    monkeypatch.setattr(artifact, "write_artifact", write_then_meddle)

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_DEPLOYMENT
    assert _leftovers(out_dir) == []


def test_a_sidecar_that_appears_during_the_copy_refuses_the_backup(
    settings: Settings,
    data_dir: Path,
    out_dir: Path,
    keyphrase_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second scan catches what the fingerprints cannot see.

    §2: "a non-cooperating writer that switches a database to WAL and then commits
    puts that commit in a newly created ``-wal``, leaving the main file's length,
    timestamps and change counter where they were".
    """
    original = artifact.write_artifact

    def write_then_meddle(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        (data_dir / "memory.db-wal").write_bytes(b"committed pages")

    monkeypatch.setattr(artifact, "write_artifact", write_then_meddle)

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_DEPLOYMENT
    assert _leftovers(out_dir) == []


def test_a_destination_that_already_exists_is_refused_and_left_alone(
    settings: Settings, out_dir: Path, keyphrase_file: Path
) -> None:
    """§2's fast refusal: what an operator who mistyped a filename should get."""
    existing = out_dir / "a.age"
    existing.write_bytes(b"last week's backup")

    assert _run(existing, keyphrase_file) == EXIT_DEPLOYMENT
    assert existing.read_bytes() == b"last week's backup"


def test_a_destination_that_appears_during_the_run_is_not_replaced(
    settings: Settings,
    out_dir: Path,
    keyphrase_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§2: "the publication itself refuses an existing destination rather than trusting
    the earlier check, which makes the guarantee structural instead of a race".
    """
    destination = out_dir / "a.age"
    original = artifact.write_artifact

    def write_then_race(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        destination.write_bytes(b"a backup taken in between")

    monkeypatch.setattr(artifact, "write_artifact", write_then_race)

    assert _run(destination, keyphrase_file) == EXIT_DEPLOYMENT

    assert destination.read_bytes() == b"a backup taken in between"
    assert _leftovers(out_dir) == ["a.age"]


# --------------------------------------------------------------------------- #
# §11 — where the artifact may be written, and what is said first
# --------------------------------------------------------------------------- #


def test_a_destination_inside_the_data_directory_is_refused(
    settings: Settings, data_dir: Path, keyphrase_file: Path
) -> None:
    """§11: "a destination inside the source puts a growing encrypted file into the
    tree being walked, and a copy that reaches it is copying its own output".
    """
    assert backup.main([str(data_dir / "a.age"), "--passphrase-file", str(keyphrase_file)]) == (
        EXIT_DEPLOYMENT
    )
    assert not (data_dir / "a.age").exists()


def test_a_destination_reaching_the_data_directory_through_a_symlink_is_refused(
    settings: Settings, data_dir: Path, tmp_path: Path, keyphrase_file: Path
) -> None:
    """§11: the test is over resolved paths, because "a lexical one is not a
    containment test at all".
    """
    (tmp_path / "safe").symlink_to(data_dir)

    assert _run(tmp_path / "safe" / "a.age", keyphrase_file) == EXIT_DEPLOYMENT
    assert not (data_dir / "a.age").exists()


def test_the_tool_states_what_it_is_writing_and_where_before_it_writes(
    settings: Settings,
    data_dir: Path,
    out_dir: Path,
    keyphrase_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§11's disclosure: "what they may not have in mind is the size of what lands there"."""
    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_OK

    reported = capsys.readouterr().out
    assert "complete encrypted copy" in reported
    assert str(data_dir) in reported
    assert str(out_dir / "a.age") in reported


def test_a_run_using_a_supplied_passphrase_states_the_custody_obligation(
    settings: Settings,
    out_dir: Path,
    keyphrase_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§5 keeps the operator's obligation in front of them rather than in a document."""
    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_OK

    assert "does not survive losing this machine" in capsys.readouterr().err


def test_a_generated_passphrase_is_shown_and_opens_the_artifact(
    settings: Settings, out_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§5: "Displaying a generated passphrase is a refusal, not a courtesy"."""
    assert backup.main([str(out_dir / "a.age"), "--generate-passphrase"]) == EXIT_OK

    shown = capsys.readouterr().err
    minted = next(line.strip() for line in shown.splitlines() if line.strip().count("-") == 7)
    staging = tmp_path / "check"
    staging.mkdir(mode=0o700)
    manifest = materialise(out_dir / "a.age", passphrase=minted, staging=staging)
    assert {entry.path for entry in manifest.files} == {"memory.db", "notes.txt"}


# --------------------------------------------------------------------------- #
# §9 — verification by restoring
# --------------------------------------------------------------------------- #


def test_a_published_artifact_has_been_verified_by_restoring_it(
    settings: Settings,
    out_dir: Path,
    keyphrase_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_OK

    assert "verified by restoring it" in capsys.readouterr().out


def test_a_verification_failure_is_a_failed_backup_and_the_artifact_is_removed(
    settings: Settings,
    out_dir: Path,
    keyphrase_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§9: "an artifact nobody could check is worth keeping, and one that was checked
    and did not pass is not".
    """

    def refuse(*_args: object, **_kwargs: object) -> None:
        msg = "the restored memory.db does not match the manifest"
        raise RefusalError(msg)

    monkeypatch.setattr(artifact, "verify_materialised", refuse)

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_DEPLOYMENT
    assert _leftovers(out_dir) == []


def test_an_unverifiable_backup_is_published_and_reported_as_unverified(
    settings: Settings,
    out_dir: Path,
    keyphrase_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§9's other outcome: the artifact is sound as far as anything can tell."""
    monkeypatch.setattr(backup, "_verification_namespace", lambda _data_dir: None)

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_OK

    assert "written but unverified" in capsys.readouterr().err
    assert _leftovers(out_dir) == ["a.age"]


def test_the_verification_directory_is_removed_when_the_run_ends(
    settings: Settings, data_dir: Path, out_dir: Path, keyphrase_file: Path
) -> None:
    """§9's guarantee, at the size a process can keep it.

    Asked through the path-only helper rather than through the one that sweeps,
    because the sweeping one would destroy the very thing being looked for.
    """
    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_OK

    assert not backup._namespace_for(data_dir).exists()


def test_a_later_run_sweeps_what_an_earlier_one_left_in_its_own_namespace(
    settings: Settings, data_dir: Path, out_dir: Path, keyphrase_file: Path
) -> None:
    """§9: the window "is bounded by the next backup rather than by nothing"."""
    abandoned = backup._verification_namespace(data_dir)
    assert abandoned is not None
    (abandoned / "store").mkdir(mode=0o700)
    (abandoned / "store" / "memory.db").write_bytes(b"a plaintext store nobody remembers")

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_OK

    assert not (abandoned / "store" / "memory.db").exists()
    assert not backup._namespace_for(data_dir).exists()


def test_the_sweep_does_not_reach_another_sources_namespace(
    settings: Settings, data_dir: Path, out_dir: Path, keyphrase_file: Path, tmp_path: Path
) -> None:
    """§9: "an unnamespaced sweep would let the second run recognise the first run's
    *live* verification tree as abandoned and delete it underneath it".
    """
    other = tmp_path / "another-deployment"
    other.mkdir(mode=0o700)
    theirs = backup._verification_namespace(other)
    assert theirs is not None
    (theirs / "live").mkdir(mode=0o700)

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_OK

    assert (theirs / "live").exists()


def test_the_verification_directory_is_owner_only(settings: Settings, data_dir: Path) -> None:
    """§9: what is being unpacked is the plaintext Tier 1 store."""
    namespace = backup._verification_namespace(data_dir)

    assert namespace is not None
    assert stat.S_IMODE(namespace.stat().st_mode) == 0o700
    assert not namespace.parent.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH)


def test_two_spellings_of_one_data_directory_are_one_namespace(
    data_dir: Path, tmp_path: Path
) -> None:
    """§9: resolved rather than as typed, "and the sweep would never reach half of
    what it is for" otherwise.
    """
    alias = tmp_path / "alias"
    alias.symlink_to(data_dir)

    assert backup._namespace_for(alias) == backup._namespace_for(data_dir)


# --------------------------------------------------------------------------- #
# The manifest, and the exit vocabulary
# --------------------------------------------------------------------------- #


def test_the_manifest_records_the_version_the_instant_and_every_digest(
    settings: Settings, data_dir: Path, out_dir: Path, keyphrase_file: Path, tmp_path: Path
) -> None:
    """§6, and nothing beyond it: four fields and one entry per copied file."""
    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_OK

    staging = tmp_path / "check"
    staging.mkdir(mode=0o700)
    manifest = materialise(out_dir / "a.age", passphrase=_KEYPHRASE, staging=staging)

    assert manifest.format_version == artifact.FORMAT_VERSION
    assert manifest.taken_at.tzinfo is not None
    assert manifest.project_version
    digests = {entry.path: entry.sha256 for entry in manifest.files}
    expected, _ = artifact.digest_and_length(data_dir / "notes.txt")
    assert digests["notes.txt"] == expected


def test_a_configuration_failure_asks_a_human_to_act(
    monkeypatch: pytest.MonkeyPatch, out_dir: Path, keyphrase_file: Path
) -> None:
    def refuse() -> Settings:
        msg = "ASSISTANT_DATA_DIR is not readable"
        raise ConfigurationError(msg)

    monkeypatch.setattr(backup, "load_settings", refuse)

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_DEPLOYMENT


def test_an_empty_passphrase_file_is_refused_before_the_lock_is_taken(
    settings: Settings, data_dir: Path, out_dir: Path, tmp_path: Path
) -> None:
    """The lock is not held across a failure the tool can see coming."""
    empty = tmp_path / "empty"
    empty.write_text("")

    assert _run(out_dir / "a.age", empty) == EXIT_DEPLOYMENT

    probe = InstanceLock(data_dir / LOCK_FILENAME)
    assert probe.acquire()
    probe.release()


def test_a_file_that_becomes_a_symlink_after_the_walk_is_refused(
    settings: Settings,
    data_dir: Path,
    out_dir: Path,
    keyphrase_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§1's "It never follows a symbolic link" has to hold at the open, not the listing.

    The static case — a link already there when the walk runs — is covered above.
    This is the one that made it a defect rather than a hardening: a regular file
    replaced by a link *between* being listed and being opened was followed, and
    because both fingerprints were then the link's, they agreed and the artifact
    was published carrying a file from outside the data directory under a
    data-directory-relative path.

    The swap is driven deterministically rather than raced, by performing it in
    exactly the window the walk leaves.
    """
    outside = out_dir.parent / "outside-the-data-directory.txt"
    outside.write_bytes(b"a file the artifact must never carry")
    original = backup._measure

    def swap_then_measure(directory: Path, source: object) -> object:
        target = directory / source.relative  # type: ignore[attr-defined]
        if target.name == "notes.txt" and not target.is_symlink():
            target.unlink()
            target.symlink_to(outside)
        return original(directory, source)  # type: ignore[arg-type]

    monkeypatch.setattr(backup, "_measure", swap_then_measure)

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_DEPLOYMENT
    assert _leftovers(out_dir) == []


def test_a_file_that_becomes_a_symlink_after_the_scan_is_refused_at_the_copy(
    settings: Settings,
    data_dir: Path,
    out_dir: Path,
    keyphrase_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same window, one pass later: the copy opens the path a second time.

    §1's clause is about what the artifact ends up carrying, so the second open
    is held to it too — a scan that passed does not license the copy to follow a
    link that appeared afterwards.
    """
    outside = out_dir.parent / "outside-the-data-directory.txt"
    outside.write_bytes(b"a file the artifact must never carry")
    original = artifact.write_artifact

    def swap_then_write(*args: object, **kwargs: object) -> None:
        target = data_dir / "notes.txt"
        if not target.is_symlink():
            target.unlink()
            target.symlink_to(outside)
        original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(artifact, "write_artifact", swap_then_write)

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_DEPLOYMENT
    assert _leftovers(out_dir) == []


def test_a_directory_swapped_for_a_symlink_is_refused_rather_than_followed(
    settings: Settings,
    data_dir: Path,
    out_dir: Path,
    keyphrase_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§1's clause covers every component of the path, not only the last one.

    ``O_NOFOLLOW`` on the *file* says nothing here: the file at the far end of a
    swapped directory is a real regular file, and every check on it passes. The
    swap is driven deterministically, in the window between the directory being
    listed and the files under it being read.
    """
    (data_dir / "sub").mkdir(mode=0o700)
    (data_dir / "sub" / "plans.db").write_bytes(b"the real plans")
    elsewhere = out_dir.parent / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    (elsewhere / "plans.db").write_bytes(b"a file the artifact must never carry")
    original = backup._scan

    def swap_then_scan(directory: Path, *, excluded: frozenset[str]) -> object:
        # Renamed away rather than deleted, which is #889's own shape: the real
        # directory survives and its *name* now points somewhere else entirely.
        (directory / "sub").rename(elsewhere.parent / "moved-away")
        (directory / "sub").symlink_to(elsewhere)
        return original(directory, excluded=excluded)

    monkeypatch.setattr(backup, "_scan", swap_then_scan)

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_DEPLOYMENT
    assert _leftovers(out_dir) == []


def test_a_file_is_read_through_the_directory_descriptor_that_was_verified(
    data_dir: Path, tmp_path: Path
) -> None:
    """The mechanism itself, without the entry point around it.

    A directory renamed away and replaced by a symlink *after* the walk has opened
    it is still reached through the descriptor the walk holds — so the bytes read
    are the ones that were checked, not the ones the name now points at. This is
    what makes the refusal above a consequence rather than a coincidence.
    """
    (data_dir / "sub").mkdir(mode=0o700)
    (data_dir / "sub" / "plans.db").write_bytes(b"the real plans")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    (elsewhere / "plans.db").write_bytes(b"a file the artifact must never carry")

    # Closing the generator is what runs the `finally` releasing its descriptors.
    walker = backup._walk(data_dir, excluded=frozenset())
    try:
        measured = None
        for source in walker:
            if source.relative != "sub/plans.db":
                continue
            (data_dir / "sub").rename(tmp_path / "moved-away")
            (data_dir / "sub").symlink_to(elsewhere)
            _fingerprint, sha256, length = backup._measure(data_dir, source)
            measured = (sha256, length)
            break
    finally:
        walker.close()

    assert measured is not None
    expected, _ = artifact.digest_and_length(tmp_path / "moved-away" / "plans.db")
    assert measured == (expected, len(b"the real plans"))


def test_a_wide_tree_costs_descriptors_by_depth_not_by_directory_count(
    settings: Settings, data_dir: Path, out_dir: Path, keyphrase_file: Path, tmp_path: Path
) -> None:
    """§1 copies "at any depth", which a descriptor-per-directory walk cannot do.

    Retaining one descriptor per directory makes the backup's cost a function of
    how many directories exist, and past ``RLIMIT_NOFILE`` an ordinary wide tree
    produces no artifact at all. The limit is lowered for the call rather than
    trusted to be low, so this fails against a tree-retaining walk and passes
    against a depth-bounded one.
    """
    for index in range(200):
        directory = data_dir / f"shard-{index:03d}"
        directory.mkdir(mode=0o700)
        (directory / "part.db").write_bytes(b"x" * 16)
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, hard))
    try:
        assert _run(out_dir / "a.age", keyphrase_file) == EXIT_OK
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))

    staging = tmp_path / "check"
    staging.mkdir(mode=0o700)
    assert len(_contents(out_dir / "a.age", staging)) == 202


def test_a_deep_tree_costs_no_interpreter_stack(
    settings: Settings,
    data_dir: Path,
    out_dir: Path,
    keyphrase_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The traversal is iterative, so depth is a descriptor question and not a frame one.

    Asserted by measuring the call stack at each level rather than by provoking a
    ``RecursionError``: lowering the recursion limit far enough to catch a
    recursive descent also breaks unrelated library code, so the failure it
    produces would not be evidence about this walk. A recursive descent grows the
    stack by a frame per level; this one does not grow it at all.
    """
    directory = data_dir
    for level in range(40):
        directory = directory / f"d{level}"
        directory.mkdir(mode=0o700)
    (directory / "deep.db").write_bytes(b"the deepest file")
    depths: list[int] = []
    original = backup._level

    def record_depth(*args: object, **kwargs: object) -> object:
        depths.append(len(inspect.stack(0)))
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(backup, "_level", record_depth)

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_OK

    assert len(depths) >= 41  # the root and every level below it, on each walk
    # The small spread is the difference between `_walk`'s two call sites, not
    # growth with nesting: a recursive descent over 40 levels would span 40.
    assert max(depths) - min(depths) <= 4
    staging = out_dir.parent / "check"
    staging.mkdir(mode=0o700)
    carried = _contents(out_dir / "a.age", staging)
    nested = "/".join(f"d{level}" for level in range(40))
    assert carried[f"{nested}/deep.db"] == b"the deepest file"


def test_running_out_of_descriptors_names_the_limit_and_stays_restartable(
    settings: Settings, data_dir: Path, out_dir: Path, keyphrase_file: Path
) -> None:
    """§1 says "at any depth" and authorises no depth policy, so this is not a refusal.

    One descriptor is held per level of nesting and that is not removable —
    dropping an ancestor's means re-finding it by name, which is the
    re-resolution the descriptors exist to avoid. So a tree deep enough to
    exhaust the limit fails, and the only questions left are *how*: with the
    remedy named, and as a restartable fault (``1``) rather than a refusal
    (``78``), because unlike a refusal a later run with a higher ``ulimit -n``
    really does succeed.
    """
    directory = data_dir
    for level in range(200):
        directory = directory / f"d{level}"
        directory.mkdir(mode=0o700)
    (directory / "deep.db").write_bytes(b"too far in for this limit")
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (96, hard))
    try:
        code = _run(out_dir / "a.age", keyphrase_file)
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))

    assert code == EXIT_RESTART
    assert _leftovers(out_dir) == []


def test_a_tree_deeper_than_the_descriptor_budget_still_backs_up_when_it_fits(
    settings: Settings, data_dir: Path, out_dir: Path, keyphrase_file: Path
) -> None:
    """No depth policy means depth is bounded by the environment and nothing else."""
    directory = data_dir
    for level in range(80):
        directory = directory / f"d{level}"
        directory.mkdir(mode=0o700)
    (directory / "deep.db").write_bytes(b"eighty levels down")

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_OK

    staging = out_dir.parent / "check"
    staging.mkdir(mode=0o700)
    nested = "/".join(f"d{level}" for level in range(80))
    assert _contents(out_dir / "a.age", staging)[f"{nested}/deep.db"] == b"eighty levels down"


def test_an_exhausted_disk_is_restartable_and_not_a_refusal(
    settings: Settings,
    out_dir: Path,
    keyphrase_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0083 §5 puts an exhausted disk on the restartable side, and it stays there.

    Wrapping every failure of the write as a refusal would give ``ENOSPC`` the
    stay-down code, which tells an operator a human must act when what actually
    has to happen is space appearing.
    """

    def out_of_space(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(artifact, "write_artifact", out_of_space)

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_RESTART
    assert _leftovers(out_dir) == []


def test_a_refused_backup_leaks_no_descriptor(
    settings: Settings, data_dir: Path, out_dir: Path, keyphrase_file: Path
) -> None:
    """The walk owns every descriptor it opens from the moment it opens one.

    A refusal raised by the scan of a directory the walk had just opened left that
    descriptor behind, because the frame holding it was only pushed once the scan
    had returned. One leak per refused backup is invisible; a process that takes
    them in a loop runs out.
    """
    open_descriptors = Path("/proc/self/fd")
    if not open_descriptors.is_dir():
        pytest.skip("counting open descriptors needs /proc")
    (data_dir / "sub").mkdir(mode=0o700)
    (data_dir / "sub" / "elsewhere").symlink_to(data_dir / "notes.txt")

    assert _run(out_dir / "a.age", keyphrase_file) == EXIT_DEPLOYMENT
    before = len(list(open_descriptors.iterdir()))
    for _ in range(20):
        assert _run(out_dir / "a.age", keyphrase_file) == EXIT_DEPLOYMENT

    assert len(list(open_descriptors.iterdir())) == before
