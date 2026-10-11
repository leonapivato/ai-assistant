"""Tests for ``scripts/check_partition_collections.py``, ``gate``'s collection check.

ADR-0310 §1:4: every test job's whole collection is the same set of node ids, and
``gate`` fails where two test jobs' collections differ. The script also holds the
records to one partition: one record per index the job count allows (§1:3), and
one assignment computed identically by every job (§1:2).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

_SCRIPT = Path(__file__).parents[2] / "scripts" / "check_partition_collections.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_partition_collections", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MODULE = _load()

_SUITE = ["tests/test_a.py::test_one", "tests/test_a.py::test_two", "tests/test_b.py::test_three"]
_ASSIGNMENT = [0, 1, 2]


def _write(
    directory: Path,
    index: int,
    *,
    count: int = 3,
    node_ids: list[str] | None = None,
    assignment: list[int] | None = None,
) -> None:
    """Write one job's record the way a test job's upload lays it out."""
    target = directory / f"collection-{index}" / "collection.json"
    target.parent.mkdir(parents=True)
    record = {
        "index": index,
        "count": count,
        "node_ids": _SUITE if node_ids is None else node_ids,
        "assignment": _ASSIGNMENT if assignment is None else assignment,
    }
    target.write_text(json.dumps(record), encoding="utf-8")


def _run(directory: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    status = _MODULE.main([str(directory)])
    captured = capsys.readouterr()
    return int(status), captured.out + captured.err


def test_agreeing_records_pass_and_say_each_jobs_share(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for index in range(3):
        _write(tmp_path, index)

    status, output = _run(tmp_path, capsys)

    assert status == 0, output
    assert "3 test job(s) collected the same 3 items" in output
    assert "job 0: 1, job 1: 1, job 2: 1" in output


def test_a_job_that_collected_a_different_suite_fails_and_names_the_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The case §1:4 exists for: a node id that differs between jobs."""
    _write(tmp_path, 0)
    _write(tmp_path, 1)
    moved = [
        "tests/test_a.py::test_one",
        "tests/test_a.py::test_two[host-b]",
        "tests/test_b.py::test_three",
    ]
    _write(tmp_path, 2, node_ids=moved)

    status, output = _run(tmp_path, capsys)

    assert status == 1
    assert "job 0 and job 2 collected different suites" in output
    assert "only in job 0: tests/test_a.py::test_two" in output
    assert "only in job 2: tests/test_a.py::test_two[host-b]" in output


@pytest.mark.parametrize("present", [[0, 1], [0, 2], [1, 2]], ids=["no-2", "no-1", "no-0"])
def test_a_missing_record_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], present: list[int]
) -> None:
    """§1:3: every index the count allows is a job, and every job reported."""
    for index in present:
        _write(tmp_path, index)

    status, output = _run(tmp_path, capsys)

    assert status == 1
    assert "needs one record for each of indices [0, 1, 2]" in output


def test_two_records_for_one_index_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, 0)
    _write(tmp_path, 1)
    (tmp_path / "again").mkdir()
    _write(tmp_path / "again", 1)
    _write(tmp_path, 2)

    status, output = _run(tmp_path, capsys)

    assert status == 1
    assert "it has records for [0, 1, 1, 2]" in output


def test_records_naming_different_job_counts_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, 0, count=2, assignment=[0, 1, 1])
    _write(tmp_path, 1, count=3)

    status, output = _run(tmp_path, capsys)

    assert status == 1
    assert "different job counts: [2, 3]" in output


def test_a_job_that_assigned_the_suite_differently_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§1:2: the same collection assigned two ways is not one partition."""
    _write(tmp_path, 0)
    _write(tmp_path, 1, assignment=[0, 2, 1])
    _write(tmp_path, 2)

    status, output = _run(tmp_path, capsys)

    assert status == 1
    assert "job 1 assigned the suite differently from job 0" in output


def test_an_assignment_to_an_index_no_job_holds_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for index in range(3):
        _write(tmp_path, index, assignment=[0, 1, 3])

    status, output = _run(tmp_path, capsys)

    assert status == 1
    assert "indices no job holds: [3]" in output


def test_no_records_at_all_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    status, output = _run(tmp_path, capsys)

    assert status == 1
    assert "no test job recorded its collection" in output


@pytest.mark.parametrize(
    "record",
    [
        "not json",
        json.dumps([1, 2]),
        json.dumps({"index": "0", "count": 3, "node_ids": [], "assignment": []}),
        json.dumps({"index": 0, "count": 3, "node_ids": ["b", "a"], "assignment": [0, 0]}),
        json.dumps({"index": 0, "count": 3, "node_ids": ["a"], "assignment": [0, 0]}),
        json.dumps({"index": 0, "count": 3, "node_ids": [1], "assignment": [0]}),
    ],
    ids=["not-json", "not-a-record", "index-not-int", "unsorted", "lengths-differ", "id-not-str"],
)
def test_a_malformed_record_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], record: str
) -> None:
    (tmp_path / "collection.json").write_text(record, encoding="utf-8")

    status, output = _run(tmp_path, capsys)

    assert status == 1
    assert "check_partition_collections:" in output
