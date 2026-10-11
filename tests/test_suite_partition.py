"""CI's partition of the suite across test jobs (ADR-0310 §1, §2).

``tests/suite_partition.py`` splits the suite among CI's test jobs. These tests pin
what ADR-0310 makes normative about it:

- **§1, completeness.** The jobs' shares are one partition of the whole
  collection: their union is every item, each item is in exactly one share, and
  every index the assignment produces is a job.
- **§1, stability.** The assignment is computed identically in every job: it reads
  the collection and the job count, never the index of the job computing it, and
  not the order the items arrive in.
- **§2, the evidence job.** Every item of the triad's evidence is assigned to index
  0. That job is whole for the triad, so both checks are decided there and a run
  that hands neither over fails. Every other job is a narrowed run, which decides
  neither check. Narrowing a partitioned run any other way is refused rather than
  left to skip the checks.

Most of it is asked of small, synthetic collections, where the answer is known.
The last tests ask it of this run's own collection, which is the real suite, and
in CI the live partition's own record of it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
import test_protocol_triad

import conftest
import suite_partition
from suite_partition import EVIDENCE_INDEX, Partition, PartitionPlugin, Unit, assign

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The repository root, from which a nested run reads this project's own
#: ``pyproject.toml`` and ``tests/conftest.py``.
_ROOT = Path(__file__).resolve().parents[1]

#: The triad module, whose every item is evidence.
_TRIAD_MODULE = Path(test_protocol_triad.__file__).resolve()

#: pytest's exit status for a usage error, which is what a refused run is.
_USAGE_ERROR = 4

#: The two checks whose subject is the whole record (ADR-0179 §2).
_EVIDENCE_CHECKS = (
    test_protocol_triad.test_every_protocols_fake_is_bound_by_a_contract_subclass_that_ran.__name__,
    test_protocol_triad.test_no_exemption_is_stale.__name__,
)


# ---------------------------------------------------------------------------
# Synthetic collections
# ---------------------------------------------------------------------------


@dataclass
class _Item:
    """As much of a ``pytest.Item`` as the partition reads."""

    nodeid: str
    path: Path = field(default_factory=lambda: _ROOT / "tests" / "test_elsewhere.py")
    cls: type | None = None
    groups: tuple[str, ...] = ()

    def iter_markers(self, name: str | None = None) -> Iterator[pytest.Mark]:
        if name != "xdist_group":
            return iter(())
        return iter(pytest.mark.xdist_group(group).mark for group in self.groups)


def _items(count: int, *, prefix: str = "tests/test_x.py::test_") -> list[pytest.Item]:
    return [cast("pytest.Item", _Item(nodeid=f"{prefix}{n}")) for n in range(count)]


def _units(total: int, evidence: int) -> list[Unit]:
    """A collection of ``total`` lone items, the first ``evidence`` of them evidence."""
    return [
        Unit(
            key=f"tests/test_x.py::test_{n}",
            node_ids=(f"tests/test_x.py::test_{n}",),
            evidence=n < evidence,
        )
        for n in range(total)
    ]


@pytest.mark.parametrize("count", [1, 2, 3, 4, 7])
def test_every_item_is_assigned_to_exactly_one_index_and_every_index_is_a_job(count: int) -> None:
    """§1: the shares' union is the collection, and no item is in two of them."""
    units = _units(3000, evidence=360)
    expected = {nodeid for unit in units for nodeid in unit.node_ids}

    assignment = assign(units, count)

    assert set(assignment) == expected
    assert set(assignment.values()) <= set(range(count))
    shares = [
        {nodeid for nodeid, index in assignment.items() if index == job} for job in range(count)
    ]
    assert sum(len(share) for share in shares) == len(expected)
    assert set().union(*shares) == expected


@pytest.mark.parametrize("count", [1, 2, 3, 4, 7])
def test_every_evidence_item_is_assigned_to_the_evidence_job(count: int) -> None:
    """§2:1: whatever the job count, the evidence is all in index 0."""
    units = _units(3000, evidence=360)

    assignment = assign(units, count)

    assert all(assignment[unit.node_ids[0]] == EVIDENCE_INDEX for unit in units if unit.evidence)


def test_the_assignment_does_not_depend_on_the_order_items_arrive_in() -> None:
    """§1:2: every job computes the same assignment, however its items are ordered."""
    units = _units(2000, evidence=200)
    reordered = [*units[1::2], *units[::2]][::-1]

    assert assign(units, 3) == assign(reordered, 3)


def test_the_shares_are_about_equal_with_the_evidence_job_weighted_down() -> None:
    """Index 0's share of the rest is cut by the evidence it already holds."""
    units = _units(30_000, evidence=3_600)

    assignment = assign(units, 3)

    sizes = [list(assignment.values()).count(index) for index in range(3)]
    assert all(abs(size - 10_000) < 400 for size in sizes), sizes


def test_a_group_kept_whole_lands_in_one_job_and_a_divided_one_is_spread() -> None:
    """§3: the browser layer may be divided; every other group stays in one job."""
    whole = [
        cast("pytest.Item", _Item(nodeid=f"tests/test_corpus.py::test_{n}", groups=("corpus",)))
        for n in range(40)
    ]
    divided = [
        cast(
            "pytest.Item",
            _Item(nodeid=f"tests/test_page.py::test_{n}", groups=("gateway_browser",)),
        )
        for n in range(40)
    ]
    units = suite_partition.units_of([*whole, *divided, *_items(200)], lambda _item: False)

    assignment = assign(units, 3)

    assert len({assignment[item.nodeid] for item in whole}) == 1
    assert len({assignment[item.nodeid] for item in divided}) == 3


def test_a_group_holding_evidence_goes_whole_to_the_evidence_job() -> None:
    """A group kept whole is not split to honour §2:1; it moves to index 0 entire."""

    class Bound:
        pass

    grouped = [
        cast(
            "pytest.Item",
            _Item(
                nodeid=f"tests/test_g.py::test_{n}", groups=("g",), cls=Bound if n == 0 else None
            ),
        )
        for n in range(10)
    ]
    units = suite_partition.units_of(grouped, lambda item: getattr(item, "cls", None) is Bound)

    assignment = assign(units, 3)

    assert set(assignment.values()) == {EVIDENCE_INDEX}


def test_the_point_of_a_key_is_the_same_in_every_process() -> None:
    """Not ``hash()``, which is salted per process: a fresh interpreter agrees."""
    key = "tests/test_x.py::test_0"
    script = (
        "import sys; sys.path.insert(0, 'tests'); import suite_partition; "
        f"print(repr(suite_partition.point_of({key!r})))"
    )
    elsewhere = subprocess.run(  # noqa: S603  # fixed interpreter, fixed arguments
        [sys.executable, "-c", script],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(_ROOT), "PYTHONHASHSEED": "random"},
    )

    assert float(elsewhere.stdout) == suite_partition.point_of(key)


# ---------------------------------------------------------------------------
# The plugin, across every job of one partition
# ---------------------------------------------------------------------------


class _Hooks:
    def __init__(self) -> None:
        self.deselected: list[pytest.Item] = []

    def pytest_deselected(self, items: list[pytest.Item]) -> None:
        self.deselected.extend(items)


def _collection() -> list[pytest.Item]:
    """A synthetic suite with items of the triad module among ordinary ones."""
    triad = [
        cast(
            "pytest.Item",
            _Item(nodeid=f"tests/core/test_protocol_triad.py::test_{n}", path=_TRIAD_MODULE),
        )
        for n in range(5)
    ]
    grouped = [
        cast(
            "pytest.Item",
            _Item(nodeid=f"tests/test_page.py::test_{n}", groups=("gateway_browser",)),
        )
        for n in range(30)
    ]
    return [*_items(600), *triad, *grouped]


def _run_job(index: int, count: int, manifest: Path | None = None) -> tuple[list[str], list[str]]:
    """Run one job's partition over the synthetic suite: (kept, deselected) node ids."""
    plugin = PartitionPlugin(Partition(index=index, count=count, manifest=manifest))
    hooks = _Hooks()
    items = _collection()
    turn = 97 * index % len(items)
    items = [*items[turn:], *items[:turn]][:: -1 if index % 2 else 1]  # each its own order
    plugin.pytest_collection_modifyitems(cast("pytest.Config", SimpleNamespace(hook=hooks)), items)
    return [item.nodeid for item in items], [item.nodeid for item in hooks.deselected]


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_the_jobs_of_one_partition_run_every_item_exactly_once(count: int) -> None:
    """§1: each job keeps its share and deselects the rest; together they are the suite."""
    whole = sorted(item.nodeid for item in _collection())
    kept: list[str] = []
    for index in range(count):
        share, deselected = _run_job(index, count)
        assert sorted([*share, *deselected]) == whole
        kept.extend(share)

    assert sorted(kept) == whole


def test_the_triad_module_is_kept_by_the_evidence_job_alone() -> None:
    """§2:1: every item of the triad module is evidence, through the module itself."""
    triad = {
        item.nodeid
        for item in _collection()
        if Path(str(getattr(item, "path", ""))) == _TRIAD_MODULE
    }
    evidence_job, _ = _run_job(EVIDENCE_INDEX, 3)
    others = [_run_job(index, 3)[0] for index in (1, 2)]

    assert triad <= set(evidence_job)
    assert not any(triad & set(share) for share in others)


def test_each_job_records_the_same_collection_and_assignment(tmp_path: Path) -> None:
    """§1:4's record: every job writes the whole collection, not its share."""
    records = []
    for index in range(3):
        manifest = tmp_path / f"job-{index}" / "collection.json"
        _run_job(index, 3, manifest)
        records.append(json.loads(manifest.read_text(encoding="utf-8")))

    assert [record["index"] for record in records] == [0, 1, 2]
    assert {record["count"] for record in records} == {3}
    assert all(
        record["node_ids"] == sorted(item.nodeid for item in _collection()) for record in records
    )
    assert all(record["assignment"] == records[0]["assignment"] for record in records)


# ---------------------------------------------------------------------------
# What a run names, and what the triad makes of it
# ---------------------------------------------------------------------------


class _Config:
    """As much of a ``pytest.Config`` as option reading and ``_is_unfiltered`` use."""

    def __init__(
        self, options: dict[str, object] | None = None, *, args: tuple[str, ...] = ("tests",)
    ) -> None:
        self.options = options or {}
        self.args = list(args)
        self.rootpath = _ROOT
        self.invocation_params = SimpleNamespace(dir=_ROOT)
        self.registered: list[str] = []
        self.pluginmanager = SimpleNamespace(register=self._register)
        self.hook = SimpleNamespace(pytest_runtest_logreport=self._report)
        self.reports: list[pytest.TestReport] = []

    def _register(self, plugin: object, name: str) -> None:
        del plugin
        self.registered.append(name)

    def _report(self, report: pytest.TestReport) -> None:
        self.reports.append(report)

    def getoption(self, name: str, default: object = None) -> object:
        return self.options.get(name, default)

    def getini(self, name: str) -> list[str]:
        assert name == "testpaths"
        return ["tests"]


def _partitioned(index: int, count: int = 3) -> pytest.Config:
    return cast("pytest.Config", _Config({"partition_index": index, "partition_count": count}))


def test_an_ordinary_run_names_no_partition_and_registers_nothing() -> None:
    """A local run without the options is untouched: no plugin, whole for the triad."""
    config = _Config()

    suite_partition.configure(cast("pytest.Config", config), narrowed=False)

    assert suite_partition.partition_of(cast("pytest.Config", config)) is None
    assert config.registered == []
    assert conftest._is_unfiltered(cast("pytest.Config", config))


def test_a_partitioned_run_registers_the_plugin() -> None:
    config = _partitioned(1)

    suite_partition.configure(config, narrowed=False)

    assert cast("_Config", config).registered == [suite_partition.PLUGIN_NAME]


@pytest.mark.parametrize(
    "options",
    [
        {"partition_index": 0},
        {"partition_count": 3},
        {"partition_manifest": "collection.json"},
        {"partition_index": 3, "partition_count": 3},
        {"partition_index": -1, "partition_count": 3},
        {"partition_index": 0, "partition_count": 0},
    ],
)
def test_a_partition_named_partly_or_out_of_range_is_refused(options: dict[str, object]) -> None:
    with pytest.raises(pytest.UsageError):
        suite_partition.partition_of(cast("pytest.Config", _Config(options)))


def test_the_evidence_job_is_whole_for_the_triad_and_the_others_are_narrowed() -> None:
    """§2:2 and §2:3, as ``tests/conftest.py`` reads them."""
    assert conftest._is_unfiltered(_partitioned(EVIDENCE_INDEX))
    assert not conftest._is_unfiltered(_partitioned(1))
    assert not conftest._is_unfiltered(_partitioned(2))


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize(
    ("narrowing", "args"),
    [
        ({"keyword": "contract"}, ("tests",)),
        ({"markexpr": "integration"}, ("tests",)),
        ({"deselect": ["tests/test_smoke.py"]}, ("tests",)),
        ({"maxfail": 1}, ("tests",)),
        ({}, ("tests/core",)),
    ],
    ids=["-k", "-m", "--deselect", "-x", "path"],
)
def test_a_partitioned_run_narrowed_any_other_way_is_refused(
    index: int, narrowing: dict[str, object], args: tuple[str, ...]
) -> None:
    """§1:3 and §2:2: the partition is the only selection, so nothing can skip the checks.

    In the evidence job, narrowing would turn the triad's record partial and the
    checks to skips. Refused before collection, neither check can reach a skip.
    """
    options = {"partition_index": index, "partition_count": 3, **narrowing}
    config = cast("pytest.Config", _Config(options, args=args))

    with pytest.raises(pytest.UsageError, match="ADR-0310"):
        suite_partition.configure(config, narrowed=not conftest._collects_the_whole_suite(config))


@pytest.fixture
def no_halves(monkeypatch: pytest.MonkeyPatch) -> None:
    """A controller to which no worker's half of the record has arrived."""
    monkeypatch.setattr(conftest, "_WORKER_HALVES", [])
    monkeypatch.setattr(conftest, "_WORKERS_LOST", [])


def _controller_session(config: pytest.Config) -> pytest.Session:
    return cast("pytest.Session", SimpleNamespace(config=config, exitstatus=pytest.ExitCode.OK))


@pytest.mark.usefixtures("no_halves")
def test_an_evidence_job_that_hands_neither_check_over_fails() -> None:
    """§2:2: ADR-0179 §2:1 binds the evidence job as it binds an unfiltered session."""
    config = _partitioned(EVIDENCE_INDEX)
    session = _controller_session(config)

    conftest._report_evidence_checks(session)

    reports = cast("_Config", config).reports
    assert [report.outcome for report in reports] == ["failed"]
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED


@pytest.mark.usefixtures("no_halves")
@pytest.mark.parametrize("index", [1, 2])
def test_another_job_hands_nothing_over_and_is_not_failed_for_it(index: int) -> None:
    """§2:3: the clause about an unfiltered session handing nothing over does not reach it."""
    config = _partitioned(index)
    session = _controller_session(config)

    conftest._report_evidence_checks(session)

    assert cast("_Config", config).reports == []
    assert session.exitstatus == pytest.ExitCode.OK


def test_the_evidence_job_decides_both_checks_and_skips_neither(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§2:2: in the evidence job the checks come back decided, never skipped.

    The halves arrive from the evidence job's own workers, each marked whole for
    the triad because ``_is_unfiltered`` read the job that way. Empty records, so
    every Protocol is unbound and the binding check fails: what matters here is
    that each check is answered.
    """
    config = _partitioned(EVIDENCE_INDEX)
    items = [
        conftest._ItemPayload(
            nodeid=f"{conftest._TRIAD_CHECK}::{name}",
            path=conftest._TRIAD_CHECK,
            lineno=0,
            domain="",
        )
        for name in _EVIDENCE_CHECKS
    ]
    # The decision parses every test file for its declared classes; which suites
    # exist is beside the point here, and an empty answer keeps this test quick.
    monkeypatch.setattr(test_protocol_triad, "_declared_class_names", set)
    half = conftest._TriadPayload(
        classes={}, items=items, unfiltered=conftest._is_unfiltered(config)
    )
    monkeypatch.setattr(conftest, "_WORKER_HALVES", [half])
    monkeypatch.setattr(conftest, "_WORKERS_LOST", [])

    conftest._report_evidence_checks(_controller_session(config))

    outcomes = {
        report.nodeid.rpartition("::")[2]: report.outcome
        for report in cast("_Config", config).reports
    }
    assert set(outcomes) == set(_EVIDENCE_CHECKS)
    assert "skipped" not in outcomes.values()


def _nested_collect(*args: str) -> subprocess.CompletedProcess[str]:
    """Try to collect in a pytest of its own, with a bare environment."""
    return subprocess.run(  # noqa: S603  # fixed interpreter, fixed arguments
        [sys.executable, "-m", "pytest", "--collect-only", "-p", "no:cacheprovider", "-q", *args],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": str(_ROOT)},
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "narrowing", [("tests/test_smoke.py",), ("-k", "smoke")], ids=["path", "-k"]
)
def test_a_narrowed_evidence_job_is_refused_by_the_real_conftest(
    narrowing: tuple[str, ...],
) -> None:
    """The refusal above, wired: the real conftest refuses before it collects anything."""
    refused = _nested_collect(*narrowing, "--partition-index", "0", "--partition-count", "3")

    assert refused.returncode == _USAGE_ERROR, refused.stdout + refused.stderr
    assert "ADR-0310" in refused.stdout + refused.stderr


# ---------------------------------------------------------------------------
# The real suite
# ---------------------------------------------------------------------------


def test_the_real_suites_evidence_is_assigned_to_the_evidence_job(
    request: pytest.FixtureRequest,
) -> None:
    """§2:1 over this run's own collection, and in CI over the live partition's record.

    In a partitioned run the plugin recorded the whole collection's assignment
    before anything else touched it, so that record must hold both checks whose
    subject is the whole record: a partition that ran after the handover would
    have seen neither. In an ordinary run there is no live partition, and the
    assignment is computed here over what this session collected -- which is the
    suite only when nothing narrowed the run, so a narrowed one skips, as the
    triad checks themselves do.
    """
    live = request.config.pluginmanager.get_plugin(suite_partition.PLUGIN_NAME)
    if live is None and not conftest._collects_the_whole_suite(request.config):
        pytest.skip("the run was narrowed, so this session's collection is not the suite")
    if isinstance(live, PartitionPlugin):
        assignment, evidence, count = live.assignment, live.evidence, live.partition.count
        checks = {f"{conftest._TRIAD_CHECK}::{name}" for name in _EVIDENCE_CHECKS}
        assert checks <= evidence
    else:
        units = suite_partition.units_of(
            request.session.items, suite_partition.evidence_predicate()
        )
        count = 3
        assignment = assign(units, count)
        evidence = frozenset(nodeid for unit in units if unit.evidence for nodeid in unit.node_ids)

    assert any(nodeid.startswith(conftest._TRIAD_CHECK) for nodeid in evidence)
    assert any("Contract::" in nodeid for nodeid in evidence), (
        "no binding class was taken as evidence"
    )
    assert {assignment[nodeid] for nodeid in evidence} == {EVIDENCE_INDEX}
    assert set(assignment.values()) == set(range(count))
