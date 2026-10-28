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
from datetime import UTC, datetime
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


def test_the_memory_writer_writes_a_record_naming_its_taker(written: tuple[Path, Path]) -> None:
    """ADR-0352 §5:2, §6:5: a frozen record carrying ``taken_over_by``, so a later base
    writes one and a later head reads it back."""
    episode = _records(_snapshot(written[1]), "memory")["record/mem-episode-taken-over"]
    assert isinstance(episode, dict)
    record = episode["processing_record"]
    assert isinstance(record, dict)
    assert (record["reason"], record["taken_over_by"]) == ("stopped", "act-upgrade-2")


def test_the_memory_writer_writes_the_shapes_adr_0332_adds(written: tuple[Path, Path]) -> None:
    """ADR-0332 §7:1 to §7:5: an episode carrying each, so a later base writes them too.

    The base's copy of the writer is what the next pull request's check runs, so the
    record's ``joined``, an understanding's ``continues`` and the takeover's stage and rule
    are each read back here, by this build, from what it wrote.
    """
    episode = _records(_snapshot(written[1]), "memory")["record/mem-episode-joined"]
    assert isinstance(episode, dict)
    record = episode["processing_record"]
    assert isinstance(record, dict)
    joined = record["joined"]
    assert isinstance(joined, list)
    # ADR-0349 §10:7: the inputs an absorbed activation held, each naming it, side by side.
    assert [one["taken_over_from"] for one in joined if isinstance(one, dict)] == [
        None,
        "act-upgrade-line",
        "act-upgrade-line",
    ]
    understanding = record["understanding"]
    assert isinstance(understanding, list)
    # ADR-0349 §10:2: a sequence, empty, of one, and of two.
    assert [one["continues"] for one in understanding if isinstance(one, dict)] == [
        [],
        ["act-upgrade-line"],
        ["act-upgrade-line", "act-upgrade-web"],
    ]
    stages = record["stages"]
    assert isinstance(stages, list)
    assert {"stage": "takeover", "due": "takeover_undecided"}.items() <= next(
        one.items() for one in stages if isinstance(one, dict) and one["stage"] == "takeover"
    )


def test_the_memory_writer_writes_a_pins_support(written: tuple[Path, Path]) -> None:
    """ADR-0338 §4:4: a memory carrying a pinned support, so a later base writes one too.

    The base's copy of the writer is what the next pull request's check runs, so the
    ``pin`` part and the ``pinned`` origin are read back here, by this build, from what it
    wrote.
    """
    record = _records(_snapshot(written[1]), "memory")["record/mem-pinned"]
    assert isinstance(record, dict)
    supports = record["supports"]
    assert isinstance(supports, list)
    pinned = [one for one in supports if isinstance(one, dict) and one["origin"] == "pinned"]
    assert [one["points_at"] for one in pinned] == [{"part": "pin", "pin": "pin-upgrade"}]
    assert {"direction": "for", "backs_as_worded": True, "how_sure": "sure"}.items() <= (
        pinned[0].items()
    )


def _occurrences(task: Json) -> list[tuple[Json, Json]]:
    """A scheduled task's occurrences as read back, each as its number and state."""
    assert isinstance(task, dict)
    occurrences = task["occurrences"]
    assert isinstance(occurrences, list)
    return [(one["number"], one["state"]) for one in occurrences if isinstance(one, dict)]


def test_the_plan_writer_writes_scheduled_tasks_and_a_rule(
    written: tuple[Path, Path],
) -> None:
    """ADR-0350 §12:3, ADR-0340 §9: so a later base writes them, and its head reads them.

    The base's copy of the writer is what the next pull request's check runs, so each
    when, each occurrence state a push and a settle leave, and the rule's skipped and
    successor occurrences are read back here, by this build, from what it wrote. No
    cascade record is written or read back (ADR-0352 §6:1, §6:3).
    """
    plans = _records(_snapshot(written[1]), "plans")
    tasks = {key: value for key, value in plans.items() if key.startswith("task/")}
    assert sorted(tasks) == [
        "task/task-upgrade-after",
        "task/task-upgrade-at",
        "task/task-upgrade-now",
        "task/task-upgrade-rule",
    ]
    whens = {key: value["when"] for key, value in tasks.items() if isinstance(value, dict)}
    assert {key: when["kind"] for key, when in whens.items() if isinstance(when, dict)} == {
        "task/task-upgrade-after": "tasks_ending",
        "task/task-upgrade-at": "instant",
        "task/task-upgrade-now": "now",
        "task/task-upgrade-rule": "rule",
    }
    assert _occurrences(tasks["task/task-upgrade-now"]) == [(1, "done")]
    assert _occurrences(tasks["task/task-upgrade-at"]) == [(1, "pending")]
    assert _occurrences(tasks["task/task-upgrade-after"]) == [(1, "pending")]
    assert _occurrences(tasks["task/task-upgrade-rule"]) == [
        (1, "skipped"),
        (2, "skipped"),
        (3, "pushed"),
        (4, "pending"),
    ]
    rule = whens["task/task-upgrade-rule"]
    assert isinstance(rule, dict)
    assert {
        "repeats": "weekly",
        "days": ["tuesday", "thursday"],
        "zone": "America/New_York",
    }.items() <= (rule.items())
    assert not [key for key in plans if key.startswith("cascade/")]
    assert all(f"effect/effect-{key.removeprefix('task/')}" in plans for key in tasks)


def test_the_plan_stores_cascade_carry_is_what_its_upgrade_does(
    written: tuple[Path, Path],
) -> None:
    """ADR-0352 §2:6, §6:3: the carry from shape 4 drops the cascade records, and only them.

    The base before ADR-0352 writes what this build's writer writes and one cascade record
    more, ``act-upgrade-cascade``, naming an activation outside every lineage; its
    read-back is this build's with that one key added. The head's upgrade retires the
    record with nothing below it to reach, so the carried read-back is this build's
    exactly, and an uncarried one differs.
    """
    head = _records(_snapshot(written[1]), "plans")
    base: Records = {**head, "cascade/act-upgrade-cascade": "act-upgrade-cascade"}
    (plans,) = [one for one in STORES if one.name == "plans"]

    carried = plans.carries[4](base)

    assert plans.shape == 5
    assert carried == head
    assert upgrade_check.compare_records("plans", carried, head) == []
    assert upgrade_check.compare_records("plans", base, head) != []


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


def _vectors(directory: Path) -> sqlite3.Connection:
    """A connection to the memory store's file that can read and write its vectors."""
    import sqlite_vec  # noqa: PLC0415  # only the cases that edit the index need it

    conn = sqlite3.connect(directory / "memory.db")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    return conn


def test_a_memory_store_that_loses_its_vectors_fails_the_check(
    written: tuple[Path, Path], tmp_path: Path
) -> None:
    """Every row kept and the vector index lost: ``search`` finds nothing, and the check says so."""
    directory, snapshot = _copy(written, tmp_path)
    conn = _vectors(directory)
    with conn:
        conn.execute("DELETE FROM vec_records")
    conn.close()
    problems = read(directory, snapshot)
    # One per record with content: three memories and four episodes.
    assert len(problems) == 7, problems
    assert all(p.startswith("memory nearest/") for p in problems), problems
    assert all(p.endswith(", the head reads []") for p in problems), problems


def test_a_memory_store_whose_vectors_moved_fails_the_check(
    written: tuple[Path, Path], tmp_path: Path
) -> None:
    """Two records' vectors exchanged: each is still found, and neither is its own nearest."""
    directory, snapshot = _copy(written, tmp_path)
    conn = _vectors(directory)
    rows = dict(conn.execute("SELECT id, rowid FROM records").fetchall())
    one, other = rows["mem-said"], rows["mem-remembered"]
    vectors = dict(conn.execute("SELECT rowid, embedding FROM vec_records").fetchall())
    with conn:
        conn.execute("DELETE FROM vec_records WHERE rowid IN (?, ?)", (one, other))
        conn.execute(
            "INSERT INTO vec_records(rowid, embedding) VALUES (?, ?), (?, ?)",
            (one, vectors[other], other, vectors[one]),
        )
    conn.close()
    assert sorted(read(directory, snapshot)) == [
        'memory nearest/mem-remembered: [0]: the base read "mem-remembered", '
        'the head reads "mem-said"',
        'memory nearest/mem-said: [0]: the base read "mem-said", the head reads "mem-remembered"',
    ]


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


def test_the_memory_carry_reads_a_users_assertion_as_its_upgrade_does() -> None:
    """A user's assertion marked ``derived_from_external`` migrates as ``legacy`` (§16:4).

    The core predicate's band guard (ADR-0106 §2) says a user's own assertion never
    rests on external content, so the head's upgrade gives it the origin ``legacy``,
    and the carry must say the same rather than reading the flag on its own.
    """
    from ai_assistant.memory._legacy import memory_from_legacy  # noqa: PLC0415

    at = "2026-10-01T12:00:00Z"
    record: dict[str, upgrade_stores.Json] = {
        "id": "asserted-flagged",
        "kind": "semantic",
        "content": "The user's sister is called Ada.",
        "provenance": {
            "source": "user_asserted",
            "confidence": 1.0,
            "last_updated": at,
            "derived_from_external": True,
        },
    }
    (memory,) = [one for one in STORES if one.name == "memory"]

    carried = memory.carries[1]({"record/asserted-flagged": record})["record/asserted-flagged"]
    upgraded = memory_from_legacy(
        record, occurred_at=lambda _: None, now=datetime(2026, 10, 2, tzinfo=UTC)
    )

    assert isinstance(carried, dict)
    supports = carried["supports"]
    assert isinstance(supports, list)
    assert isinstance(supports[0], dict)
    assert supports[0]["origin"] == "legacy"
    assert upgraded.supports[0].origin.value == "legacy"


@pytest.mark.integration
def test_the_memory_stores_carry_is_what_its_upgrade_does(tmp_path: Path) -> None:
    """ADR-0328 §16:9: the carry from shape 1 says what the head's upgrade writes.

    Taken over the file the previous release wrote (``tests/memory/legacy``), so the
    carry is held to the store's real upgrade rather than to a hand-built record: every
    record that release read back, carried to shape 2, is read back by this build
    after opening the file. The base's read-back is the stored blob with its revision,
    which is what that release's ``export`` returned.
    """
    import shutil  # noqa: PLC0415

    from ai_assistant.memory import SqliteMemoryStore  # noqa: PLC0415
    from ai_assistant.models import HashingEmbedder  # noqa: PLC0415
    from ai_assistant.testing import FakeTraceSink  # noqa: PLC0415

    legacy = Path(__file__).resolve().parents[1] / "memory" / "legacy"
    path = tmp_path / "memory.db"
    shutil.copyfile(legacy / "memory-before-adr-0328.db", path)
    with sqlite3.connect(path) as conn:
        base: Records = {
            f"record/{record_id}": json.loads(data) | {"revision": revision}
            for record_id, data, revision in conn.execute("SELECT id, data, revision FROM records")
        }
    # The day after the previous release wrote the file, before any retention deadline
    # it holds passes: the carry keeps every row, so the store must read them all back.
    store = SqliteMemoryStore(
        traces_sink=FakeTraceSink(),
        path=path,
        embedder=HashingEmbedder(dimensions=8),
        now=lambda: datetime(2026, 10, 2, 12, tzinfo=UTC),
    )
    try:
        head: Records = {
            f"record/{record.id}": upgrade_stores.to_json(record)
            for record in asyncio.run(store.export())
        }
    finally:
        store.close()
    (memory,) = [one for one in STORES if one.name == "memory"]

    # Carried on through ADR-0345 §13's shape, ADR-0349 §10:6's, ADR-0351 §9's and
    # ADR-0353 §9:6's, which the head's upgrades reach next.
    carried = memory.carries[5](
        memory.carries[4](memory.carries[3](memory.carries[2](memory.carries[1](base))))
    )

    assert memory.shape == 6
    assert set(carried) == set(head)
    assert {
        key: first_difference(value, head[key]) for key, value in carried.items()
    } == dict.fromkeys(carried)


@pytest.mark.integration
def test_the_memory_stores_carry_from_shape_2_is_what_its_upgrade_does(tmp_path: Path) -> None:
    """ADR-0345 §13:3: the carry from shape 2 says what the head's upgrade writes.

    Taken over the file the release before ADR-0345 wrote (``tests/memory/legacy``):
    every record that release read back, carried to shape 3, is read back by this build
    after opening the file, a memory's ``about_person`` as ``subjects`` and its topics
    as labels added by ``migration``, and every support with its holder beside.
    """
    import shutil  # noqa: PLC0415

    from ai_assistant.memory import SqliteMemoryStore  # noqa: PLC0415
    from ai_assistant.models import HashingEmbedder  # noqa: PLC0415
    from ai_assistant.testing import FakeTraceSink  # noqa: PLC0415

    legacy = Path(__file__).resolve().parents[1] / "memory" / "legacy"
    path = tmp_path / "memory.db"
    shutil.copyfile(legacy / "memory-before-adr-0345.db", path)
    with sqlite3.connect(path) as conn:
        base: Records = {
            f"record/{record_id}": json.loads(data) | {"revision": revision}
            for record_id, data, revision in conn.execute("SELECT id, data, revision FROM records")
        }
    store = SqliteMemoryStore(
        traces_sink=FakeTraceSink(),
        path=path,
        embedder=HashingEmbedder(dimensions=8),
        now=lambda: datetime(2026, 10, 23, 12, tzinfo=UTC),
    )
    try:
        head: Records = {
            f"record/{record.id}": upgrade_stores.to_json(record)
            for record in asyncio.run(store.export())
        }
    finally:
        store.close()
    (memory,) = [one for one in STORES if one.name == "memory"]

    # Carried on through ADR-0349 §10:6's shape, ADR-0351 §9's and ADR-0353 §9:6's, which
    # the head's upgrades reach next.
    carried = memory.carries[5](memory.carries[4](memory.carries[3](memory.carries[2](base))))

    assert set(carried) == set(head)
    assert {
        key: first_difference(value, head[key]) for key, value in carried.items()
    } == dict.fromkeys(carried)
    said = head["record/mem-said"]
    assert isinstance(said, dict)
    assert said["subjects"] == ["Ada"]


def test_the_memory_stores_carry_from_shape_3_is_what_its_upgrade_does(tmp_path: Path) -> None:
    """ADR-0349 §10:6: the carry from shape 3 says what the head's upgrade writes.

    Taken over the file the release before ADR-0349 wrote (``tests/memory/legacy``):
    every record that release read back, carried to shape 4, is read back by this build
    after opening the file, each understanding's ``continues`` a sequence, of one where
    it named an activation and empty where it named none, an open episode's included.
    """
    import shutil  # noqa: PLC0415

    from ai_assistant.memory import SqliteMemoryStore  # noqa: PLC0415
    from ai_assistant.models import HashingEmbedder  # noqa: PLC0415
    from ai_assistant.testing import FakeTraceSink  # noqa: PLC0415

    legacy = Path(__file__).resolve().parents[1] / "memory" / "legacy"
    path = tmp_path / "memory.db"
    shutil.copyfile(legacy / "memory-before-adr-0349.db", path)
    with sqlite3.connect(path) as conn:
        base: Records = {
            f"record/{record_id}": json.loads(data) | {"revision": revision}
            for record_id, data, revision in conn.execute("SELECT id, data, revision FROM records")
        }
    store = SqliteMemoryStore(
        traces_sink=FakeTraceSink(),
        path=path,
        embedder=HashingEmbedder(dimensions=8),
        now=lambda: datetime(2026, 10, 26, 13, tzinfo=UTC),
    )
    try:
        head: Records = {
            f"record/{record.id}": upgrade_stores.to_json(record)
            for record in asyncio.run(store.export())
        }
    finally:
        store.close()
    (memory,) = [one for one in STORES if one.name == "memory"]

    # Carried on through ADR-0351 §9's shape and ADR-0353 §9:6's, which the head's
    # upgrades reach next.
    carried = memory.carries[5](memory.carries[4](memory.carries[3](base)))

    assert set(carried) == set(head)
    assert {
        key: first_difference(value, head[key]) for key, value in carried.items()
    } == dict.fromkeys(carried)
    # And it is the carry that holds the head to the sequence: the base read one id or
    # null, which the head reading back unchanged would differ from.
    for key, value in (
        ("record/mem-episode-joined", [[], ["act-upgrade-line"]]),
        ("record/mem-episode-open", [["act-upgrade-web"]]),
    ):
        record = head[key]
        assert isinstance(record, dict)
        processing = record["processing_record"]
        assert isinstance(processing, dict)
        versions = processing["understanding"]
        assert isinstance(versions, list)
        assert [one["continues"] for one in versions if isinstance(one, dict)] == value
        assert first_difference(base[key], record) is not None


@pytest.mark.integration
def test_the_memory_stores_carry_from_shape_4_is_what_its_upgrade_does(tmp_path: Path) -> None:
    """ADR-0351 §9: the carry from shape 4 says what the head's upgrade writes.

    Taken over the file the release before ADR-0351 wrote (``tests/memory/legacy``):
    every record that release read back, carried to shape 5, is read back by this build
    after opening the file, each trigger's ``origin`` given way to its parties, an
    uncovered record's and an open episode's included.
    """
    import shutil  # noqa: PLC0415

    from ai_assistant.memory import SqliteMemoryStore  # noqa: PLC0415
    from ai_assistant.models import HashingEmbedder  # noqa: PLC0415
    from ai_assistant.testing import FakeTraceSink  # noqa: PLC0415

    legacy = Path(__file__).resolve().parents[1] / "memory" / "legacy"
    path = tmp_path / "memory.db"
    shutil.copyfile(legacy / "memory-before-adr-0351.db", path)
    with sqlite3.connect(path) as conn:
        base: Records = {
            f"record/{record_id}": json.loads(data) | {"revision": revision}
            for record_id, data, revision in conn.execute("SELECT id, data, revision FROM records")
        }
    store = SqliteMemoryStore(
        traces_sink=FakeTraceSink(),
        path=path,
        embedder=HashingEmbedder(dimensions=8),
        now=lambda: datetime(2026, 10, 27, 13, tzinfo=UTC),
    )
    try:
        head: Records = {
            f"record/{record.id}": upgrade_stores.to_json(record)
            for record in asyncio.run(store.export())
        }
    finally:
        store.close()
    (memory,) = [one for one in STORES if one.name == "memory"]

    # Carried on through ADR-0353 §9:6's shape, which the head's upgrade reaches next.
    carried = memory.carries[5](memory.carries[4](base))

    assert set(carried) == set(head)
    assert {
        key: first_difference(value, head[key]) for key, value in carried.items()
    } == dict.fromkeys(carried)
    # And it is the carry that holds the head to the parties: the base read an origin,
    # which the head reading back would differ from without it.
    record = head["record/mem-episode-door"]
    assert isinstance(record, dict)
    processing = record["processing_record"]
    assert isinstance(processing, dict)
    trigger = processing["trigger"]
    assert isinstance(trigger, dict)
    assert "origin" not in trigger
    assert trigger["parties"] is None
    assert first_difference(base["record/mem-episode-door"], record) is not None


@pytest.mark.integration
def test_the_memory_stores_carry_from_shape_5_is_what_its_upgrade_does(tmp_path: Path) -> None:
    """ADR-0353 §9:6, §15:3: the carry from shape 5 says what the head's upgrade writes.

    Taken over the file the release before ADR-0353 wrote (``tests/memory/legacy``):
    every record that release read back, carried to shape 6, is read back by this build
    after opening the file, each understanding version without its retired fields, the
    referents of its references and relationships added to its ``meaning_referents``
    each once, an open episode's included.
    """
    import shutil  # noqa: PLC0415

    from ai_assistant.memory import SqliteMemoryStore  # noqa: PLC0415
    from ai_assistant.models import HashingEmbedder  # noqa: PLC0415
    from ai_assistant.testing import FakeTraceSink  # noqa: PLC0415

    legacy = Path(__file__).resolve().parents[1] / "memory" / "legacy"
    path = tmp_path / "memory.db"
    shutil.copyfile(legacy / "memory-before-adr-0353.db", path)
    with sqlite3.connect(path) as conn:
        base: Records = {
            f"record/{record_id}": json.loads(data) | {"revision": revision}
            for record_id, data, revision in conn.execute("SELECT id, data, revision FROM records")
        }
    store = SqliteMemoryStore(
        traces_sink=FakeTraceSink(),
        path=path,
        embedder=HashingEmbedder(dimensions=8),
        now=lambda: datetime(2026, 10, 28, 10, 10, tzinfo=UTC),
    )
    try:
        head: Records = {
            f"record/{record.id}": upgrade_stores.to_json(record)
            for record in asyncio.run(store.export())
        }
    finally:
        store.close()
    (memory,) = [one for one in STORES if one.name == "memory"]

    carried = memory.carries[5](base)

    assert set(carried) == set(head)
    assert {
        key: first_difference(value, head[key]) for key, value in carried.items()
    } == dict.fromkeys(carried)
    # And it is the carry that holds the head to the form: the base read a ground and
    # references, which the head reading back would differ from without it.
    record = head["record/mem-episode-understood"]
    assert isinstance(record, dict)
    processing = record["processing_record"]
    assert isinstance(processing, dict)
    versions = processing["understanding"]
    assert isinstance(versions, list)
    first = versions[0]
    assert isinstance(first, dict)
    assert "meaning_ground" not in first
    referents = first["meaning_referents"]
    assert isinstance(referents, list)
    assert len(referents) == 4
    assert first_difference(base["record/mem-episode-understood"], record) is not None


@pytest.mark.integration
def test_the_plan_stores_carry_is_what_its_upgrade_does(tmp_path: Path) -> None:
    """ADR-0329 §16:10: the carry from shape 1 says what the head's upgrade reads back.

    Taken over the file the previous release wrote (``tests/planning/legacy``), so the
    carry is held to the store's real upgrade rather than to a hand-built record. The
    base's read-back is the stop records and each effect record as that release
    exported them, which is the stored blob; carried to shape 2, every record of it is
    read back by this build after the upgrade, and nothing more.
    """
    import shutil  # noqa: PLC0415

    legacy = Path(__file__).resolve().parents[1] / "planning" / "legacy"
    shutil.copyfile(legacy / "plans-before-adr-0329.db", tmp_path / "plans.db")
    with sqlite3.connect(tmp_path / "plans.db") as conn:
        base: Records = {
            "stopped": [
                str(one)
                for (one,) in conn.execute(
                    "SELECT activation_id FROM stopped_activations ORDER BY activation_id"
                )
            ],
            **{
                f"effect/{effect_id}": json.loads(data)
                for effect_id, data in conn.execute("SELECT id, data FROM activation_effects")
            },
        }
    (plans,) = [one for one in STORES if one.name == "plans"]

    carried = plans.carries[2](plans.carries[1](base))
    head = asyncio.run(plans.read(tmp_path))

    assert plans.shape == 5
    assert carried["observations"] == []
    assert upgrade_check.compare_records("plans", carried, head) == []


@pytest.mark.integration
def test_the_plan_stores_finding_carry_is_what_its_upgrade_does(tmp_path: Path) -> None:
    """#3205 (ADR-0329 §16:1): the carry from shape 2 says what the head's upgrade reads back.

    Taken over the file the previous release wrote with observation records in it
    (``tests/planning/legacy``). The base's read-back is the stop record, the effect
    record and each observation record as that release exported them, which is the
    stored blob; carried to shape 3, every finding gains ``supply`` and ``written``
    empty, and every record of it is read back by this build after the upgrade — the
    carry's empty values held to what the head actually reads, not just tolerated.
    """
    import shutil  # noqa: PLC0415

    legacy = Path(__file__).resolve().parents[1] / "planning" / "legacy"
    shutil.copyfile(legacy / "plans-before-observation-carry.db", tmp_path / "plans.db")
    with sqlite3.connect(tmp_path / "plans.db") as conn:
        base: Records = {
            "stopped": [
                str(one) for (one,) in conn.execute("SELECT activation_id FROM stopped_activations")
            ],
            **{
                f"effect/{effect_id}": json.loads(data)
                for effect_id, data in conn.execute("SELECT id, data FROM activation_effects")
            },
            "observations": [
                json.loads(data)
                for (data,) in conn.execute("SELECT data FROM observations ORDER BY episode_id")
            ],
        }
    (plans,) = [one for one in STORES if one.name == "plans"]

    carried = plans.carries[2](base)
    head = asyncio.run(plans.read(tmp_path))

    observations = carried["observations"]
    assert isinstance(observations, list)
    findings = [
        one
        for record in observations
        if isinstance(record, dict) and isinstance(record["findings"], list)
        for one in record["findings"]
    ]
    assert findings
    assert all(isinstance(one, dict) and one["supply"] is None for one in findings)
    assert all(isinstance(one, dict) and one["written"] == [] for one in findings)
    assert upgrade_check.compare_records("plans", carried, head) == []
    # And it is the carry that holds the head to empty values: a head inventing a supply
    # differs from the carried read-back where it would pass the bare base's.
    invented = json.loads(json.dumps(head))
    invented["observations"][0]["findings"][0]["supply"] = {"reach": "owner"}
    assert upgrade_check.compare_records("plans", base, invented) == []
    assert upgrade_check.compare_records("plans", carried, invented) != []


@pytest.mark.integration
def test_the_plan_stores_annotation_carry_is_what_its_upgrade_does(tmp_path: Path) -> None:
    """ADR-0346 §4:5, §4:6: the carry from shape 3 says what the head's upgrade reads back.

    Taken over the file the release before ADR-0346 wrote (``tests/planning/legacy``).
    Carried to shape 4, every record gains no ``declines``, every finding no
    ``annotations``, and every outcome no ``unclear`` and nothing ``asked``, and every
    record of it is read back by this build after the upgrade.
    """
    import shutil  # noqa: PLC0415

    legacy = Path(__file__).resolve().parents[1] / "planning" / "legacy"
    shutil.copyfile(legacy / "plans-before-annotations.db", tmp_path / "plans.db")
    with sqlite3.connect(tmp_path / "plans.db") as conn:
        base: Records = {
            "stopped": [
                str(one) for (one,) in conn.execute("SELECT activation_id FROM stopped_activations")
            ],
            **{
                f"effect/{effect_id}": json.loads(data)
                for effect_id, data in conn.execute("SELECT id, data FROM activation_effects")
            },
            "observations": [
                json.loads(data)
                for (data,) in conn.execute("SELECT data FROM observations ORDER BY episode_id")
            ],
        }
    (plans,) = [one for one in STORES if one.name == "plans"]

    carried = plans.carries[3](base)
    head = asyncio.run(plans.read(tmp_path))

    observations = carried["observations"]
    assert isinstance(observations, list)
    assert all(isinstance(one, dict) and one["declines"] == [] for one in observations)
    findings = [
        one
        for record in observations
        if isinstance(record, dict) and isinstance(record["findings"], list)
        for one in record["findings"]
    ]
    assert findings
    assert all(isinstance(one, dict) and one["annotations"] is None for one in findings)
    assert upgrade_check.compare_records("plans", carried, head) == []
    # The carry holds the head to empty values: a head inventing a decline differs.
    invented = json.loads(json.dumps(head))
    invented["observations"][0]["declines"] = [{"candidate": "effect-x", "reason": "x"}]
    assert upgrade_check.compare_records("plans", base, invented) == []
    assert upgrade_check.compare_records("plans", carried, invented) != []


@pytest.mark.integration
def test_the_story_stores_carry_is_what_its_upgrade_does(tmp_path: Path) -> None:
    """ADR-0347 §5: the carry from shape 1 says what the head's upgrade reads back.

    Taken over the file the previous release wrote (``tests/memory/legacy``), with what
    that release's own reader read back from it beside it, so both halves are the
    previous release's code. Carried to shape 2, each story's current summary is kept
    at the version that wrote it and no earlier version gains text, which is what this
    build reads back after the upgrade, and nothing more.
    """
    import shutil  # noqa: PLC0415

    legacy = Path(__file__).resolve().parents[1] / "memory" / "legacy"
    shutil.copyfile(legacy / "stories-before-adr-0347.db", tmp_path / "stories.db")
    base = upgrade_stores.cast_records(
        json.loads((legacy / "stories-before-adr-0347.json").read_text())
    )
    (stories,) = [one for one in STORES if one.name == "stories"]

    carried = stories.carries[1](base)
    head = asyncio.run(stories.read(tmp_path))

    assert stories.shape == 2
    assert carried["position"] == 17
    trip = carried["kept/story:legacy-1"]
    assert isinstance(trip, list)
    assert [one["summary"] is None for one in trip if isinstance(one, dict)] == [
        True,
        True,
        False,
    ]
    assert upgrade_check.compare_records("stories", carried, head) == []
    # And the carry holds the head to no text for an earlier version: a head inventing
    # one differs from the carried read-back.
    invented = json.loads(json.dumps(head))
    invented["kept/story:legacy-1"][0]["summary"] = invented["kept/story:legacy-1"][2]["summary"]
    assert upgrade_check.compare_records("stories", carried, invented) != []


def test_the_story_writer_leaves_a_replaced_summary_kept(written: tuple[Path, Path]) -> None:
    """ADR-0347 §2: the writer replaces a summary, so a later build reads a kept one back.

    A story whose log holds two versions with text has a summary a later write replaced.
    """
    _, snapshot = written
    records = _records(_snapshot(snapshot), "stories")
    with_text = [
        sum(1 for one in value if isinstance(one, dict) and one["summary"] is not None)
        for key, value in records.items()
        if key.startswith("kept/") and isinstance(value, list)
    ]
    assert max(with_text) >= 2
    assert isinstance(records["position"], int)


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
