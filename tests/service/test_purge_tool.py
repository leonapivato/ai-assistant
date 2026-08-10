"""Tests for the whole-store delete's entry point (ADR-0126).

Named ``_tool`` rather than mirroring ``service/purge.py`` exactly, for the reason
``test_backup_tool.py`` states: ``tests/`` carries no ``__init__.py`` and two test
modules with one basename collide at collection.

**What is on test is the decision's refusals and its ordering**, which between them
are most of it. Each refusal is asserted together with what it leaves behind — a
refused purge that destroyed something is a breach no assertion on the exit code
alone can see — and each ordering clause is asserted against the state a crash at
that instant would leave, which is the only thing §5's guarantee is about.

The mount table is faked in every test by an autouse fixture. The real one is a
property of the machine the suite runs on, and a test whose meaning depends on
whether the developer's ``/tmp`` happens to be a mount is not a test.
"""

from __future__ import annotations

import ast
import errno
import os
import shutil
import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.service import purge
from ai_assistant.service.backup import SIDECAR_SUFFIXES
from ai_assistant.service.enrolment import ENROLMENTS_FILENAME, LISTING_LIMIT, EnrolmentStore
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _mountinfo(*points: Path) -> str:
    """A ``/proc/self/mountinfo`` naming the root and whatever else is asked for."""
    lines = []
    for index, point in enumerate((Path("/"), *points)):
        escaped = str(point).replace("\\", r"\134").replace(" ", r"\040")
        lines.append(f"{36 + index} 35 98:0 / {escaped} rw,relatime shared:1 - ext4 /dev/sda1 rw")
    return "\n".join(lines) + "\n"


@pytest.fixture(autouse=True)
def mount_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A mount table with nothing in it but the root, unless a test says otherwise."""
    table = tmp_path / "mountinfo"
    table.write_text(_mountinfo())
    monkeypatch.setattr(purge, "MOUNT_TABLE", table)
    return table


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A data directory with the shape a hub leaves behind."""
    directory = tmp_path / "hub-data"
    directory.mkdir(mode=0o700)
    _database(directory / "memory.db", "a memory")
    _database(directory / "traces.db", "a trace")
    (directory / "notes.txt").write_bytes(b"hello")
    nested = directory / "vectors" / "shards"
    nested.mkdir(parents=True)
    (nested / "0.bin").write_bytes(b"\x00\x01")
    (directory / LOCK_FILENAME).write_text("4242\n")
    return directory


@pytest.fixture
def settings(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    loaded = Settings(data_dir=data_dir, embedder=EmbedderKind.HASHING)
    monkeypatch.setattr(purge, "load_settings", lambda: loaded)
    return loaded


def _database(path: Path, value: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (x)")
    connection.execute("INSERT INTO t VALUES (?)", (value,))
    connection.commit()
    connection.close()


def _enrol(data_dir: Path, *identities: str) -> None:
    """Put live enrolments in the record, creating it the way the hub would."""
    store = EnrolmentStore(data_dir / ENROLMENTS_FILENAME)
    try:
        for identity in identities:
            store.enrol(identity, verifier=f"verifier-for-{identity}", now=_NOW)
    finally:
        store.close()


def _run(data_dir: Path) -> int:
    return purge.main(["--confirm", str(data_dir)])


def _remaining(data_dir: Path) -> set[str]:
    """Every path left under the data directory, relative and posix-spelled."""
    found: set[str] = set()
    for root, directories, files in os.walk(data_dir):
        for name in (*directories, *files):
            found.add(Path(root, name).relative_to(data_dir).as_posix())
    return found


# ---------------------------------------------------------------------------
# §1: the unit is the directory, and the lock file is the sole survivor
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("settings")
def test_destroys_every_entry_to_any_depth_and_leaves_only_the_lock(data_dir: Path) -> None:
    assert _run(data_dir) == EXIT_OK
    assert _remaining(data_dir) == {LOCK_FILENAME}
    assert data_dir.is_dir()


@pytest.mark.usefixtures("settings")
def test_an_empty_data_directory_is_not_a_fault(tmp_path: Path, data_dir: Path) -> None:
    for entry in data_dir.iterdir():
        if entry.name != LOCK_FILENAME:
            entry.unlink() if entry.is_file() else None
    (data_dir / "vectors" / "shards" / "0.bin").unlink()
    (data_dir / "vectors" / "shards").rmdir()
    (data_dir / "vectors").rmdir()
    assert _run(data_dir) == EXIT_OK
    assert _remaining(data_dir) == {LOCK_FILENAME}
    assert tmp_path.exists()


@pytest.mark.usefixtures("settings")
def test_a_symbolic_link_is_destroyed_as_a_link_and_never_followed(
    tmp_path: Path, data_dir: Path
) -> None:
    """§1: "what it names is not read, not descended into and not destroyed"."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("the owner never named this")
    (data_dir / "to-a-directory").symlink_to(outside)
    (data_dir / "to-a-file").symlink_to(outside / "keep.txt")
    (data_dir / "dangling").symlink_to(tmp_path / "nothing-here")

    assert _run(data_dir) == EXIT_OK
    assert _remaining(data_dir) == {LOCK_FILENAME}
    assert (outside / "keep.txt").read_text() == "the owner never named this"


@pytest.mark.usefixtures("settings")
def test_a_socket_or_fifo_is_destroyed_like_anything_else(data_dir: Path) -> None:
    """§1 carries "no inclusion list and no exclusion list beyond that one entry"."""
    os.mkfifo(data_dir / "hub.fifo")
    assert _run(data_dir) == EXIT_OK
    assert _remaining(data_dir) == {LOCK_FILENAME}


# ---------------------------------------------------------------------------
# §1: mount points beneath the boundary
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("settings")
def test_refuses_a_descendant_mount_point_before_destroying_anything(
    data_dir: Path, mount_table: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mounted = data_dir / "vectors"
    mount_table.write_text(_mountinfo(mounted))

    before = _remaining(data_dir)
    assert _run(data_dir) == EXIT_DEPLOYMENT
    assert _remaining(data_dir) == before
    assert str(mounted) in capsys.readouterr().err


@pytest.mark.usefixtures("settings")
def test_refuses_a_bind_mount_on_the_same_device(data_dir: Path, mount_table: Path) -> None:
    """The case a device comparison misses, which is why the table is consulted."""
    mounted = data_dir / "vectors" / "shards"
    same_device = f"{36} 35 98:0 /home/owner/photos {mounted} rw - ext4 /dev/sda1 rw"
    mount_table.write_text(f"{_mountinfo()}{same_device}\n")

    assert data_dir.stat().st_dev == mounted.stat().st_dev
    assert _run(data_dir) == EXIT_DEPLOYMENT
    assert (mounted / "0.bin").exists()


@pytest.mark.usefixtures("settings")
def test_the_boundary_being_a_mount_point_is_not_a_refusal(
    data_dir: Path, mount_table: Path
) -> None:
    """§1: "a mount point *at* the boundary is the boundary"."""
    mount_table.write_text(_mountinfo(data_dir))
    assert _run(data_dir) == EXIT_OK
    assert _remaining(data_dir) == {LOCK_FILENAME}


@pytest.mark.usefixtures("settings")
def test_a_sibling_with_a_shared_prefix_is_not_a_descendant(
    data_dir: Path, mount_table: Path
) -> None:
    mount_table.write_text(_mountinfo(data_dir.parent / f"{data_dir.name}-elsewhere"))
    assert _run(data_dir) == EXIT_OK


@pytest.mark.usefixtures("settings")
def test_refuses_when_the_mount_table_cannot_be_read(
    data_dir: Path, mount_table: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§1: an act that cannot see its own boundary does not get to guess where it is."""
    mount_table.unlink()
    before = _remaining(data_dir)
    assert _run(data_dir) == EXIT_DEPLOYMENT
    assert _remaining(data_dir) == before
    assert str(mount_table) in capsys.readouterr().err


@pytest.mark.usefixtures("settings")
def test_refuses_a_mount_table_line_it_cannot_parse(data_dir: Path, mount_table: Path) -> None:
    mount_table.write_text(f"{_mountinfo()}36 35 98:0\n")
    before = _remaining(data_dir)
    assert _run(data_dir) == EXIT_DEPLOYMENT
    assert _remaining(data_dir) == before


@pytest.mark.usefixtures("settings")
def test_a_mount_point_with_an_escaped_space_is_still_compared(
    data_dir: Path, mount_table: Path
) -> None:
    mount_table.write_text(_mountinfo(data_dir / "a shard"))
    assert _run(data_dir) == EXIT_DEPLOYMENT


# ---------------------------------------------------------------------------
# §1: the removability pre-check
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("settings")
def test_refuses_an_unreadable_subdirectory_and_destroys_nothing(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ``lost+found`` case: a walk would meet it having destroyed most of the stores."""
    lost = data_dir / "lost+found"
    lost.mkdir(mode=0o000)
    try:
        before = _remaining(data_dir)
        assert _run(data_dir) == EXIT_DEPLOYMENT
        assert _remaining(data_dir) == before
        assert (data_dir / "memory.db").exists()
        assert str(lost) in capsys.readouterr().err
    finally:
        lost.chmod(0o700)


@pytest.mark.usefixtures("settings")
def test_the_refusal_names_every_failing_path_not_just_the_first(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = data_dir / "lost+found"
    second = data_dir / "vectors" / "sealed"
    first.mkdir(mode=0o000)
    second.mkdir(mode=0o000)
    try:
        assert _run(data_dir) == EXIT_DEPLOYMENT
        printed = capsys.readouterr().err
        assert str(first) in printed
        assert str(second) in printed
    finally:
        first.chmod(0o700)
        second.chmod(0o700)


@pytest.mark.usefixtures("settings")
def test_a_directory_that_cannot_be_written_is_named_as_unwritable(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sealed = data_dir / "vectors" / "shards"
    sealed.chmod(0o500)
    try:
        assert _run(data_dir) == EXIT_DEPLOYMENT
        assert f"{sealed} is not writable" in capsys.readouterr().err
    finally:
        sealed.chmod(0o700)


# ---------------------------------------------------------------------------
# §5: the enrolment record goes first, and its sidecars immediately after
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("settings")
def test_the_record_and_its_sidecars_are_destroyed_before_anything_else(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5 fixes the order *inside* the group too: the main file is what a hub opens."""
    _enrol(data_dir, "device-a")
    for suffix in SIDECAR_SUFFIXES:
        (data_dir / f"{ENROLMENTS_FILENAME}{suffix}").write_bytes(b"pages")

    order: list[str] = []
    real = os.unlink

    def spy(path: object, *, dir_fd: int | None = None) -> None:
        order.append(str(path))
        real(path, dir_fd=dir_fd)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "unlink", spy)
    assert _run(data_dir) == EXIT_OK

    group = [ENROLMENTS_FILENAME, *(f"{ENROLMENTS_FILENAME}{s}" for s in SIDECAR_SUFFIXES)]
    assert order[: len(group)] == group


@pytest.mark.usefixtures("settings")
def test_a_record_that_cannot_be_destroyed_stops_the_act_with_nothing_else_touched(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """§1's one exception to best effort, and §5 is why it runs the other way."""
    _enrol(data_dir, "device-a")
    real = os.unlink

    def refuse(path: object, *, dir_fd: int | None = None) -> None:
        if str(path) == ENROLMENTS_FILENAME:
            raise OSError(errno.EPERM, "operation not permitted", str(path))
        real(path, dir_fd=dir_fd)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "unlink", refuse)
    before = _remaining(data_dir)
    assert _run(data_dir) == EXIT_DEPLOYMENT
    assert _remaining(data_dir) == before
    printed = capsys.readouterr().out
    assert str(data_dir / ENROLMENTS_FILENAME) in printed
    assert "did not complete" in printed


@pytest.mark.usefixtures("settings")
def test_a_sidecar_that_resists_does_not_stop_the_act(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5: "a ``-wal`` left without it is pages no process in this system can open".

    Set up as exactly that state — a sidecar with no ``devices.db`` beside it — for
    a reason worth recording: SQLite owns all three sidecar names whenever the
    record exists, so a planted one is checkpointed away by the very read §7's
    device list is composed from, and a test that planted one beside a live record
    would assert against a file the reader had already taken.
    """
    stubborn = f"{ENROLMENTS_FILENAME}-wal"
    (data_dir / stubborn).write_bytes(b"pages of a crashed hub")
    assert not (data_dir / ENROLMENTS_FILENAME).exists()
    real = os.unlink

    def refuse(path: object, *, dir_fd: int | None = None) -> None:
        if str(path) == stubborn:
            raise OSError(errno.EIO, "I/O error", str(path))
        real(path, dir_fd=dir_fd)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "unlink", refuse)
    assert _run(data_dir) == EXIT_RESTART
    assert _remaining(data_dir) == {LOCK_FILENAME, stubborn}


@pytest.mark.usefixtures("settings")
def test_an_installation_with_no_record_destroys_the_rest_and_creates_nothing(
    data_dir: Path,
) -> None:
    """§4: every loopback-only hub holds a full data directory and no ``devices.db``."""
    assert not (data_dir / ENROLMENTS_FILENAME).exists()
    assert _run(data_dir) == EXIT_OK
    assert _remaining(data_dir) == {LOCK_FILENAME}


# ---------------------------------------------------------------------------
# §1: best-effort continuation past a late failure
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("settings")
def test_a_late_failure_destroys_everything_else_and_names_what_remains(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """§1: "it does not stop at the first failure"."""
    real = os.unlink

    def refuse(path: object, *, dir_fd: int | None = None) -> None:
        if str(path) == "memory.db":
            raise OSError(errno.EPERM, "operation not permitted", str(path))
        real(path, dir_fd=dir_fd)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "unlink", refuse)
    assert _run(data_dir) == EXIT_DEPLOYMENT
    assert _remaining(data_dir) == {LOCK_FILENAME, "memory.db"}
    printed = capsys.readouterr().out
    assert str(data_dir / "memory.db") in printed
    assert "destroyed. " not in printed


@pytest.mark.usefixtures("settings")
def test_a_failure_a_rerun_might_survive_asks_for_a_rerun_rather_than_a_human(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0083 §5's default: "a spurious restart is recoverable and a spurious 78 is an outage"."""
    real = os.unlink

    def refuse(path: object, *, dir_fd: int | None = None) -> None:
        if str(path) == "notes.txt":
            raise OSError(errno.EIO, "I/O error", str(path))
        real(path, dir_fd=dir_fd)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "unlink", refuse)
    assert _run(data_dir) == EXIT_RESTART
    assert _remaining(data_dir) == {LOCK_FILENAME, "notes.txt"}


@pytest.mark.usefixtures("settings")
def test_a_directory_that_could_not_be_emptied_survives_with_its_parent(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.unlink

    def refuse(path: object, *, dir_fd: int | None = None) -> None:
        if str(path) == "0.bin":
            raise OSError(errno.EPERM, "operation not permitted", str(path))
        real(path, dir_fd=dir_fd)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "unlink", refuse)
    assert _run(data_dir) == EXIT_DEPLOYMENT
    assert _remaining(data_dir) == {
        LOCK_FILENAME,
        "vectors",
        "vectors/shards",
        "vectors/shards/0.bin",
    }


# ---------------------------------------------------------------------------
# §2: the lock, and the shape of the entry point
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("settings")
def test_refuses_a_contended_lock_and_destroys_nothing(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    holder = InstanceLock(data_dir / LOCK_FILENAME)
    assert holder.acquire()
    try:
        before = _remaining(data_dir)
        assert _run(data_dir) == EXIT_RESTART
        assert _remaining(data_dir) == before
        assert "Nothing was destroyed" in capsys.readouterr().err
    finally:
        holder.release()


@pytest.mark.usefixtures("settings")
def test_the_lock_is_held_across_the_whole_act(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5: "no hub can start, so there is no process that could read a half-destroyed directory"."""
    seen: list[bool] = []
    real = os.unlink

    def watch(path: object, *, dir_fd: int | None = None) -> None:
        contender = InstanceLock(data_dir / LOCK_FILENAME)
        seen.append(contender.acquire())
        contender.release()
        real(path, dir_fd=dir_fd)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "unlink", watch)
    assert _run(data_dir) == EXIT_OK
    assert seen
    assert not any(seen)


def test_the_console_script_is_its_own_entry_point_and_not_a_subcommand() -> None:
    """§2: "It is not an ``assistant`` subcommand"."""
    root = Path(__file__).resolve().parents[2]
    scripts = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'ai-assistant-purge = "ai_assistant.service.purge:main"' in scripts


def test_no_bare_affirmative_flag_exists(data_dir: Path) -> None:
    """§7: "a bare affirmative flag does not satisfy this clause"."""
    with pytest.raises(SystemExit):
        purge.main(["--yes"])
    with pytest.raises(SystemExit):
        purge.main(["-y"])
    assert _remaining(data_dir) != set()


# ---------------------------------------------------------------------------
# §7: the report, and the confirmation
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("settings")
def test_the_confirmation_must_name_the_data_directory(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _remaining(data_dir)
    assert purge.main(["--confirm", str(tmp_path / "somewhere-else")]) == EXIT_DEPLOYMENT
    assert _remaining(data_dir) == before
    assert "nothing was destroyed" in capsys.readouterr().err


@pytest.mark.usefixtures("settings")
def test_an_interactive_confirmation_that_names_the_directory_proceeds(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: f" {data_dir} ")
    assert purge.main([]) == EXIT_OK
    assert _remaining(data_dir) == {LOCK_FILENAME}


@pytest.mark.usefixtures("settings")
def test_an_interactive_confirmation_that_does_not_stops_the_act(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _remaining(data_dir)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    assert purge.main([]) == EXIT_DEPLOYMENT
    assert _remaining(data_dir) == before


@pytest.mark.usefixtures("settings")
def test_an_empty_confirmation_is_never_the_working_directory(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _remaining(data_dir)
    monkeypatch.setattr("builtins.input", lambda _prompt: "   ")
    assert purge.main([]) == EXIT_DEPLOYMENT
    assert _remaining(data_dir) == before


@pytest.mark.usefixtures("settings")
def test_no_confirmation_at_all_destroys_nothing(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_prompt: str) -> str:
        raise EOFError

    before = _remaining(data_dir)
    monkeypatch.setattr("builtins.input", refuse)
    assert purge.main([]) == EXIT_DEPLOYMENT
    assert _remaining(data_dir) == before


@pytest.mark.usefixtures("settings")
def test_the_device_list_is_stated_before_the_act_and_restated_after(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§7: the first statement is the guarantee, because a crash removes the record."""
    _enrol(data_dir, "laptop.example.ts.net", "phone.example.ts.net")
    assert _run(data_dir) == EXIT_OK
    printed = capsys.readouterr().out

    first = printed.index("laptop.example.ts.net")
    destroyed = printed.index("destroyed. ")
    last = printed.rindex("laptop.example.ts.net")
    assert first < destroyed < last
    assert printed.count("phone.example.ts.net") == 2
    assert printed.count(purge.DEVICE_PURGE_ACT) == 2


@pytest.mark.usefixtures("settings")
def test_the_device_list_is_complete_past_the_control_sockets_bound(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§7: "no bound, no page and no omission count"."""
    identities = [f"device-{index:04d}.example.ts.net" for index in range(LISTING_LIMIT + 5)]
    _enrol(data_dir, *identities)
    assert _run(data_dir) == EXIT_OK
    printed = capsys.readouterr().out
    assert all(identity in printed for identity in identities)


@pytest.mark.usefixtures("settings")
def test_a_revoked_device_is_not_named_as_one_to_visit(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = EnrolmentStore(data_dir / ENROLMENTS_FILENAME)
    try:
        store.enrol("live.example.ts.net", verifier="v", now=_NOW)
        store.enrol("gone.example.ts.net", verifier="v", now=_NOW)
        store.revoke("gone.example.ts.net", now=_NOW)
    finally:
        store.close()

    assert _run(data_dir) == EXIT_OK
    printed = capsys.readouterr().out
    assert "live.example.ts.net" in printed
    assert "gone.example.ts.net" not in printed


@pytest.mark.usefixtures("settings")
def test_an_absent_record_says_so_plainly_rather_than_omitting_the_subject(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(data_dir) == EXIT_OK
    assert "has enrolled no device" in capsys.readouterr().out


@pytest.mark.usefixtures("settings")
def test_the_record_is_never_created_in_order_to_report_on_it(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: an implementation that opened it "would write a database in the moment before
    destroying everything", and a crashed run leaves a file the installation never had."""
    real = os.unlink

    def refuse(path: object, *, dir_fd: int | None = None) -> None:
        if str(path) == "notes.txt":
            raise OSError(errno.EIO, "I/O error", str(path))
        real(path, dir_fd=dir_fd)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "unlink", refuse)
    assert _run(data_dir) == EXIT_RESTART
    assert not (data_dir / ENROLMENTS_FILENAME).exists()


@pytest.mark.usefixtures("settings")
def test_a_record_that_is_not_a_regular_file_is_not_read_through(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§1 decides an entry's type on the entry, and "what it names is not read"."""
    elsewhere = tmp_path / "another-record.db"
    _enrol(tmp_path, "somewhere-elses-device.example.ts.net")
    (tmp_path / ENROLMENTS_FILENAME).rename(elsewhere)
    (data_dir / ENROLMENTS_FILENAME).symlink_to(elsewhere)

    assert _run(data_dir) == EXIT_OK
    printed = capsys.readouterr().out
    assert "somewhere-elses-device.example.ts.net" not in printed
    assert "is a symbolic link" in printed
    assert elsewhere.exists()
    assert _remaining(data_dir) == {LOCK_FILENAME}


@pytest.mark.usefixtures("settings")
def test_an_unreadable_record_is_a_refusal_rather_than_an_empty_list(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (data_dir / ENROLMENTS_FILENAME).write_bytes(b"not a database at all, not remotely")
    before = _remaining(data_dir)
    assert _run(data_dir) == EXIT_DEPLOYMENT
    assert _remaining(data_dir) == before
    assert ENROLMENTS_FILENAME in capsys.readouterr().err


@pytest.mark.usefixtures("settings")
def test_the_report_states_the_three_things_it_may_not_claim(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(data_dir) == EXIT_OK
    printed = capsys.readouterr().out.lower()
    assert "does not purge everything" in printed
    assert "reaches nothing on an enrolled device" in printed
    assert "what a device received before this act, it keeps" in printed


@pytest.mark.usefixtures("settings")
def test_the_report_names_the_backup_artifact_it_does_not_reach(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§7: ADR-0123 §11 writes the artifact outside ``data_dir``, so it survives this act."""
    assert _run(data_dir) == EXIT_OK
    assert "backup" in capsys.readouterr().out.lower()


@pytest.mark.usefixtures("settings")
def test_the_report_names_the_tier_0_credential_it_cannot_reach(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§6's replacement for ADR-0004 §6's Tier 0 purge clause, which it partially supersedes."""
    assert _run(data_dir) == EXIT_OK
    printed = capsys.readouterr().out
    assert "no keyring" in printed
    assert "shell profile" in printed


@pytest.mark.usefixtures("settings")
def test_the_report_states_the_resolved_data_directory(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(data_dir) == EXIT_OK
    assert str(data_dir) in capsys.readouterr().out


# ---------------------------------------------------------------------------
# §6, §8, §11: what this act does not hold, add or leave behind
# ---------------------------------------------------------------------------


def _imported_by(module: object) -> set[str]:
    """Every module name the module's source imports, over its own statements.

    Over the import graph rather than over the text, because the text of this one
    says "no keyring" repeatedly and a substring search would read a promise as a
    breach of it.
    """
    source = Path(module.__file__).read_text(encoding="utf-8")  # type: ignore[attr-defined]
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_the_act_reaches_no_keyring() -> None:
    """§6: ADR-0125 §8 names ``service`` among the packages that "hold neither" face."""
    imported = _imported_by(purge)
    assert not [name for name in imported if "keyring" in name]
    assert not [name for name in imported if "secret" in name.lower()]


def test_the_act_adds_no_core_surface() -> None:
    """§8: no Protocol changes, no type is added, and nothing here crosses a boundary."""
    imported = _imported_by(purge)
    assert not [name for name in imported if name.startswith("ai_assistant.core.protocols")]
    assert not [name for name in imported if name.startswith("ai_assistant.core.types")]


@pytest.mark.usefixtures("settings")
def test_no_record_of_the_act_survives_anywhere(tmp_path: Path, data_dir: Path) -> None:
    """§11: "The act writes no audit record anywhere", and that is required not tolerated."""
    before = {path for path in tmp_path.rglob("*") if not path.is_relative_to(data_dir)}
    assert _run(data_dir) == EXIT_OK
    after = {path for path in tmp_path.rglob("*") if not path.is_relative_to(data_dir)}
    assert after == before


@pytest.mark.usefixtures("settings")
def test_the_surviving_directory_keeps_the_mode_preparation_gives_it(data_dir: Path) -> None:
    """§1's end state: what a hub started afterwards finds is a first-start installation."""
    assert _run(data_dir) == EXIT_OK
    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700


# ---------------------------------------------------------------------------
# The failure boundary
# ---------------------------------------------------------------------------


def test_a_configuration_that_will_not_load_is_a_stay_down_exit(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path
) -> None:
    def refuse() -> Settings:
        msg = "ASSISTANT_DATA_DIR is not set to anything usable"
        raise ConfigurationError(msg)

    monkeypatch.setattr(purge, "load_settings", refuse)
    assert purge.main(["--confirm", str(data_dir)]) == EXIT_DEPLOYMENT
    assert _remaining(data_dir) != set()


@pytest.mark.usefixtures("settings")
def test_a_data_directory_other_users_may_write_to_is_refused(data_dir: Path) -> None:
    """ADR-0083 §3's step 2, which §11 leans on for its custody replacement."""
    data_dir.chmod(0o707)
    try:
        assert _run(data_dir) == EXIT_DEPLOYMENT
        assert (data_dir / "memory.db").exists()
    finally:
        data_dir.chmod(0o700)


# ---------------------------------------------------------------------------
# The boundary holds where the act's own machinery writes, and where a directory
# moves under it
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("settings")
def test_a_symbolic_link_at_the_lock_path_is_refused_before_it_is_written_through(
    tmp_path: Path, data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§1: the act "destroys nothing whose path is outside the resolved ``data_dir``".

    Taking the lock truncates the file and writes a pid into it, so following a
    link here destroys a file outside the boundary — before the owner has confirmed
    anything — and then exempts the link from destruction and reports success.
    """
    outside = tmp_path / "precious.txt"
    outside.write_text("the owner never named this")
    (data_dir / LOCK_FILENAME).unlink()
    (data_dir / LOCK_FILENAME).symlink_to(outside)

    before = _remaining(data_dir)
    assert _run(data_dir) == EXIT_DEPLOYMENT
    assert outside.read_text() == "the owner never named this"
    assert _remaining(data_dir) == before
    assert str(data_dir / LOCK_FILENAME) in capsys.readouterr().err


@pytest.mark.usefixtures("settings")
def test_a_directory_removed_between_listing_and_descent_is_not_a_survivor(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """§1 asks for "every path that remains", and one that has gone does not remain.

    The instance lock excludes a second hub, not an unrelated process in the
    owner's own directory, so the window between listing an entry and entering it
    is real rather than theoretical.
    """
    real_open = purge._open_directory
    vanished = data_dir / "vectors" / "shards"

    def vanishing(directory: int | None, name: str) -> int:
        if name == vanished.name and vanished.exists():
            shutil.rmtree(vanished)
        return real_open(directory, name)

    monkeypatch.setattr(purge, "_open_directory", vanishing)
    assert _run(data_dir) == EXIT_OK
    assert _remaining(data_dir) == {LOCK_FILENAME}
    assert "did not complete" not in capsys.readouterr().out


@pytest.mark.usefixtures("settings")
def test_a_record_swapped_for_a_link_around_the_read_is_refused(
    tmp_path: Path,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§1: "what it names is not read". SQLite opens a path, so the entry is pinned.

    The swap is staged where the real race would land it — after the entry has been
    examined and before the record is opened by name — which is the window an
    ``lstat``-then-open pair leaves and the descriptor closes.
    """
    elsewhere = tmp_path / "another-record.db"
    _enrol(tmp_path, "somewhere-elses-device.example.ts.net")
    (tmp_path / ENROLMENTS_FILENAME).rename(elsewhere)
    _enrol(data_dir, "this-installations-device.example.ts.net")

    record = data_dir / ENROLMENTS_FILENAME
    real_store = EnrolmentStore

    def swap_then_open(path: Path) -> EnrolmentStore:
        if path == record and record.exists() and not record.is_symlink():
            record.unlink()
            record.symlink_to(elsewhere)
        return real_store(path)

    monkeypatch.setattr(purge, "EnrolmentStore", swap_then_open)
    before = _remaining(data_dir)
    assert _run(data_dir) == EXIT_DEPLOYMENT
    assert _remaining(data_dir) == before
    printed = capsys.readouterr()
    assert "was replaced while it was being read" in printed.err
    assert "somewhere-elses-device.example.ts.net" not in printed.out


@pytest.mark.usefixtures("settings")
def test_a_record_that_is_a_fifo_does_not_hang_the_act(data_dir: Path) -> None:
    """Opening a FIFO ``O_RDONLY`` blocks until a writer arrives; ``O_NONBLOCK`` is why."""
    os.mkfifo(data_dir / ENROLMENTS_FILENAME)
    assert _run(data_dir) == EXIT_OK
    assert _remaining(data_dir) == {LOCK_FILENAME}


@pytest.mark.usefixtures("settings")
def test_the_preflight_never_reads_a_tree_a_swapped_directory_names(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§1's type decisions are the entry's, in the preflight as much as in the act.

    A directory replaced by a link to an unreadable tree used to make the preflight
    scan that tree and refuse over permissions found outside the boundary. Now the
    link is passed over here and unlinked by the act, and the external tree is
    neither read nor destroyed.
    """
    outside = tmp_path / "not-ours"
    outside.mkdir()
    (outside / "sealed").mkdir(mode=0o000)
    swapped = data_dir / "vectors"
    real_open = purge._open_directory

    def swapping(directory: int | None, name: str) -> int:
        if name == swapped.name and not swapped.is_symlink():
            shutil.rmtree(swapped)
            swapped.symlink_to(outside)
        return real_open(directory, name)

    monkeypatch.setattr(purge, "_open_directory", swapping)
    try:
        assert _run(data_dir) == EXIT_OK
        assert _remaining(data_dir) == {LOCK_FILENAME}
        assert (outside / "sealed").is_dir()
    finally:
        (outside / "sealed").chmod(0o700)
