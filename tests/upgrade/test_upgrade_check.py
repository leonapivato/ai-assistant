"""ADR-0326 §7's upgrade check, as this tree's build runs both halves of it.

CI's ``upgrade`` job runs ``scripts/upgrade_check.py run``: the base's build writes a
data directory and this build reads it. These cases run both halves with *this* build,
which is what the next pull request's base will run, so a writer that no longer works
against the package fails here, on the pull request that broke it, rather than on the
next one. They also pin what makes the check fail: a store refusing the directory, a
record read back otherwise, and a file no store claims (§7:1 to §7:3).
"""

from __future__ import annotations

import ast
import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import upgrade_check
import upgrade_stores
from upgrade_check import compare, coverage, first_difference, read, read_back, write
from upgrade_stores import NOT_STORES, STORES, Records, Store, check_settings

from ai_assistant.app import diagnostic_record_directory
from ai_assistant.service.lock import LOCK_FILENAME
from ai_assistant.wire.address import ADMIN_SOCKET_FILENAME, SOCKET_FILENAME

if TYPE_CHECKING:
    from upgrade_stores import Json

_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "ai_assistant"


@pytest.fixture(scope="module")
def written(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """One data directory this build wrote, with its snapshot, shared by the cases."""
    root = tmp_path_factory.mktemp("upgrade")
    directory, snapshot = root / "data", root / "snapshot.json"
    assert write(directory, snapshot) == []
    return directory, snapshot


def _copy(written: tuple[Path, Path], tmp_path: Path) -> tuple[Path, Path]:
    """A private copy of the written directory and its snapshot, for a case to change."""
    import shutil  # noqa: PLC0415

    directory, snapshot = written
    shutil.copytree(directory, tmp_path / "data")
    shutil.copy(snapshot, tmp_path / "snapshot.json")
    return tmp_path / "data", tmp_path / "snapshot.json"


def _snapshot(path: Path) -> dict[str, Json]:
    loaded = json.loads(path.read_text())
    assert isinstance(loaded, dict)
    return loaded


def _records(snapshot: dict[str, Json], store: str) -> dict[str, Json]:
    stores = snapshot["stores"]
    assert isinstance(stores, dict)
    section = stores[store]
    assert isinstance(section, dict)
    records = section["records"]
    assert isinstance(records, dict)
    return records


# --- the round trip ----------------------------------------------------------------------


def test_this_build_reads_back_what_it_wrote(written: tuple[Path, Path]) -> None:
    """The next pull request's base runs this writer; it must work today (§7:1)."""
    directory, snapshot = written
    assert read(directory, snapshot) == []


def test_every_store_is_written_and_read_back(written: tuple[Path, Path]) -> None:
    """A store the snapshot holds no record of would be checked for nothing."""
    snapshot = _snapshot(written[1])
    stores = snapshot["stores"]
    assert isinstance(stores, dict)
    assert sorted(stores) == sorted(store.name for store in STORES)
    for store in STORES:
        assert _records(snapshot, store.name), f"{store.name} reads back no record"


def test_the_reads_leave_the_directory_as_they_found_it(
    written: tuple[Path, Path], tmp_path: Path
) -> None:
    """Reads run on a copy, so the outbox's leasing read never reaches the directory."""
    directory, _ = _copy(written, tmp_path)
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    records, problems = asyncio.run(read_back(directory, STORES))
    assert problems == []
    assert records["outbox"], "the outbox's read claimed nothing"
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before


# --- what fails the check ----------------------------------------------------------------


def test_a_file_no_store_claims_fails_the_check(written: tuple[Path, Path], tmp_path: Path) -> None:
    """A store added to the hub and not to the check is caught by its file (§7:3)."""
    directory, snapshot = _copy(written, tmp_path)
    sqlite3.connect(directory / "wishes.db").close()
    problems = read(directory, snapshot)
    assert len(problems) == 1
    assert problems[0].startswith("wishes.db:")
    assert "ADR-0326 §7:3" in problems[0]


def test_a_store_that_refuses_the_directory_fails_the_check(
    written: tuple[Path, Path], tmp_path: Path
) -> None:
    """A label the head will not open is a refusal, reported where it happens (§7:1)."""
    directory, snapshot = _copy(written, tmp_path)
    with sqlite3.connect(directory / "stories.db") as conn:
        conn.execute("PRAGMA user_version = 99")
    conn.close()
    problems = read(directory, snapshot)
    assert any(
        p.startswith("the build refuses the data directory: StoryStoreError") for p in problems
    )
    assert any(p.startswith("stories: refuses to read back") for p in problems)


def test_a_record_read_back_otherwise_fails_the_check(
    written: tuple[Path, Path], tmp_path: Path
) -> None:
    """The base read one thing and the head another: §7:2's failure."""
    directory, snapshot_path = _copy(written, tmp_path)
    snapshot = _snapshot(snapshot_path)
    grant = _records(snapshot, "grants")["grant/grant-upgrade-1"]
    assert isinstance(grant, dict)
    grant["source"] = "mail"
    snapshot_path.write_text(json.dumps(snapshot))
    assert read(directory, snapshot_path) == [
        'grants grant/grant-upgrade-1: /source: the base read "mail", the head reads "calendar"'
    ]


def test_a_memory_store_that_loses_its_vectors_fails_the_check(
    written: tuple[Path, Path], tmp_path: Path
) -> None:
    """Every row kept and the vector index lost: ``search`` finds nothing, and the check says so."""
    import sqlite_vec  # noqa: PLC0415  # only this case edits the index

    directory, snapshot = _copy(written, tmp_path)
    conn = sqlite3.connect(directory / "memory.db")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    with conn:
        conn.execute("DELETE FROM vec_records")
    conn.close()
    problems = read(directory, snapshot)
    assert problems
    assert all(p.startswith("memory found/") for p in problems), problems
    assert all(p.endswith("the base read true, the head reads false") for p in problems)


def test_a_record_the_head_loses_fails_the_check(
    written: tuple[Path, Path], tmp_path: Path
) -> None:
    """A record the base wrote and the head no longer reads back."""
    directory, snapshot_path = _copy(written, tmp_path)
    snapshot = _snapshot(snapshot_path)
    _records(snapshot, "reads")["read/read-upgrade-9"] = {"id": "read-upgrade-9"}
    snapshot_path.write_text(json.dumps(snapshot))
    assert read(directory, snapshot_path) == [
        "reads read/read-upgrade-9: the base wrote it and the head reads back none"
    ]


def test_a_field_the_head_adds_passes(written: tuple[Path, Path], tmp_path: Path) -> None:
    """A field added with a default reads back where the base read none: no carry owed."""
    directory, snapshot_path = _copy(written, tmp_path)
    snapshot = _snapshot(snapshot_path)
    grant = _records(snapshot, "grants")["grant/grant-upgrade-2"]
    assert isinstance(grant, dict)
    del grant["revokes"]
    snapshot_path.write_text(json.dumps(snapshot))
    assert read(directory, snapshot_path) == []


def test_a_store_the_head_drops_fails_the_check(written: tuple[Path, Path], tmp_path: Path) -> None:
    """Every store the base wrote is one the head must still open and read."""
    directory, snapshot_path = _copy(written, tmp_path)
    snapshot = _snapshot(snapshot_path)
    stores = snapshot["stores"]
    assert isinstance(stores, dict)
    stores["wishes"] = {"shape": 1, "records": {}}
    snapshot_path.write_text(json.dumps(snapshot))
    assert read(directory, snapshot_path) == [
        "wishes: the base wrote this store and the head checks no store of that name"
    ]


# --- shapes and carries ------------------------------------------------------------------


async def _nothing(directory: Path, *_: object) -> None:
    del directory


async def _none(directory: Path) -> Records:
    del directory
    return {}


def _renamed(records: Records) -> Records:
    """Shape 1 to 2: the record's ``name`` became ``title``."""
    carried: Records = {}
    for key, value in records.items():
        assert isinstance(value, dict)
        carried[key] = {("title" if name == "name" else name): item for name, item in value.items()}
    return carried


def _snapshot_of(shape: int, records: Records) -> dict[str, Json]:
    return {"format": 1, "stores": {"things": {"shape": shape, "records": dict(records)}}}


def test_a_carry_turns_the_base_shape_into_the_head_shape() -> None:
    """A head that renames a field says how its upgrade carries it (§7:2)."""
    store = Store("things", ("things.db",), _nothing, _none, shape=2, carries={1: _renamed})
    snapshot = _snapshot_of(1, {"thing/1": {"name": "a"}})
    assert compare(snapshot, {"things": {"thing/1": {"title": "a"}}}, [store]) == []


def test_a_shape_with_no_carry_fails_the_check() -> None:
    store = Store("things", ("things.db",), _nothing, _none, shape=2)
    problems = compare(_snapshot_of(1, {}), {"things": {}}, [store])
    assert len(problems) == 1
    assert "no carry from shape 1" in problems[0]


def test_a_base_shape_the_head_does_not_know_fails_the_check() -> None:
    store = Store("things", ("things.db",), _nothing, _none, shape=1)
    problems = compare(_snapshot_of(2, {}), {"things": {}}, [store])
    assert problems == [
        "things: the base reads it back at shape 2 and the head only knows shapes up to 1"
    ]


def test_a_snapshot_format_the_head_does_not_know_fails_the_check() -> None:
    assert compare({"format": 99, "stores": {}}, {}, STORES) == [
        "the snapshot is format 99; this build reads 1"
    ]


@pytest.mark.parametrize(
    ("expected", "actual", "found"),
    [
        ({"a": 1}, {"a": 1, "b": 2}, None),
        ({"a": [1, {"b": 2}]}, {"a": [1, {"b": 2, "c": 3}]}, None),
        ({"a": 1}, {"a": True}, "/a: the base read 1, the head reads true"),
        ({"a": [1, 2]}, {"a": [1]}, "/a: the base read [1, 2], the head reads [1]"),
        ({"a": {"b": 1}}, {"a": {}}, "/a/b: the base read 1, the head reads nothing"),
        ({"a": [{"b": 1}]}, {"a": [{"b": 2}]}, "/a[0]/b: the base read 1, the head reads 2"),
        ("x", "x", None),
        (1, 1.0, "the record: the base read 1, the head reads 1.0"),
    ],
)
def test_the_head_may_read_back_more_and_nothing_else(
    expected: Json, actual: Json, found: str | None
) -> None:
    assert first_difference(expected, actual) == found


# --- what the data directory holds -------------------------------------------------------


def test_what_is_not_a_store_is_what_the_package_names(tmp_path: Path) -> None:
    """The lock, the sockets and the diagnostic record, by the package's own names (§2:2, §8)."""
    record = diagnostic_record_directory(check_settings(tmp_path), data_dir=tmp_path)
    assert record.parent == tmp_path
    assert (
        frozenset({LOCK_FILENAME, SOCKET_FILENAME, ADMIN_SOCKET_FILENAME, record.name})
        == NOT_STORES
    )


def test_coverage_names_a_store_that_left_no_file(tmp_path: Path) -> None:
    assert coverage(tmp_path, STORES[:1], NOT_STORES) == [
        "traces: no file under the data directory matches traces.db"
    ]


def test_coverage_counts_sidecars_and_skips_what_is_not_a_store(tmp_path: Path) -> None:
    for name in ("traces.db", "traces.db-wal", "traces.db-shm", "hub.lock", "diagnostics"):
        (tmp_path / name).touch()
    assert coverage(tmp_path, STORES[:1], NOT_STORES) == []


def _database_names(tree: ast.AST) -> set[str]:
    """Every literal file name ending ``.db`` in ``tree``, an f-string's fields as ``*``."""
    names: set[str] = set()
    parts = {
        id(part)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for part in node.values
    }
    for node in ast.walk(tree):
        if id(node) in parts:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        elif isinstance(node, ast.JoinedStr):
            text = "".join(
                str(part.value) if isinstance(part, ast.Constant) else "*" for part in node.values
            )
        else:
            continue
        if (
            text.endswith(".db")
            and text.replace("*", "x").replace("-", "_").replace(".", "_").isidentifier()
        ):
            names.add(text)
    return names


def test_every_database_file_the_package_names_is_a_store_the_check_covers() -> None:
    """A store that only a setting opens is caught here, where no composition opens it."""
    named: set[str] = set()
    for module in _PACKAGE.rglob("*.py"):
        named |= _database_names(ast.parse(module.read_text(), filename=str(module)))
    patterns = {pattern for store in STORES for pattern in store.files}
    assert named, "the scan found no database file names at all"
    assert named <= patterns, (
        f"{sorted(named - patterns)}: named in the package and covered by no store in "
        "scripts/upgrade_stores.py (ADR-0326 §7:3)"
    )


def test_store_names_and_files_are_distinct() -> None:
    names = [store.name for store in STORES]
    files = [pattern for store in STORES for pattern in store.files]
    assert len(set(names)) == len(names)
    assert len(set(files)) == len(files)


def test_the_check_refuses_ambient_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ``ASSISTANT_*`` variable could steer the composition; ``run`` clears them."""
    monkeypatch.setenv("ASSISTANT_DATA_DIR", "/elsewhere")
    assert upgrade_check.main(["read", "/nowhere", "/nowhere.json"]) == 2


def test_the_writer_refuses_a_directory_that_holds_anything(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "memory.db").touch()
    with pytest.raises(upgrade_check.CheckError, match="not empty"):
        write(tmp_path / "data", tmp_path / "snapshot.json")


def test_a_relative_keep_names_one_place_for_both_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The writer runs from the base's worktree, the reader from here: one absolute path."""
    monkeypatch.chdir(tmp_path)
    data, snapshot = upgrade_check._kept(Path("saved"), tmp_path / "scratch")
    assert data == tmp_path / "saved" / "data"
    assert snapshot == tmp_path / "saved" / "base-snapshot.json"
    assert data.parent.is_dir()


def _tree(root: Path, pin: bytes) -> Path:
    """A tree with the two pin modules and one vendored file."""
    for module in upgrade_check._PINS:
        (root / module).parent.mkdir(parents=True, exist_ok=True)
        (root / module).write_bytes(pin)
    (root / upgrade_check._VENDOR / "model").mkdir(parents=True)
    (root / upgrade_check._VENDOR / "model" / "weights").write_bytes(b"weights")
    return root


def test_the_base_gets_this_trees_models_only_where_both_pin_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model re-pinned here would fail the base's verification, so it is not seeded."""
    monkeypatch.setattr(upgrade_check, "_ROOT", _tree(tmp_path / "head", b"pins v2"))
    differing = tmp_path / "differing"
    for module in upgrade_check._PINS:
        (differing / module).parent.mkdir(parents=True, exist_ok=True)
        (differing / module).write_bytes(b"pins v1")
    assert upgrade_check._seed_vendor(differing) is False
    assert not (differing / upgrade_check._VENDOR).exists()
    alike = tmp_path / "alike"
    for module in upgrade_check._PINS:
        (alike / module).parent.mkdir(parents=True, exist_ok=True)
        (alike / module).write_bytes(b"pins v2")
    assert upgrade_check._seed_vendor(alike) is True
    assert (alike / upgrade_check._VENDOR / "model" / "weights").read_bytes() == b"weights"


def test_the_modules_say_what_they_are_for() -> None:
    """The two docstrings are where a lane changing a store learns what it owes."""
    assert "ADR-0326 §7:3" in (upgrade_stores.__doc__ or "")
    assert "ADR-0326 §7" in (upgrade_check.__doc__ or "")
