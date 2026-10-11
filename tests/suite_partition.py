"""CI's partition of the suite across parallel test jobs (ADR-0310).

CI's ``gate`` workflow runs its ``pytest`` step as several jobs. Every job collects
the whole suite and keeps one share of it, so the jobs' union is the suite and no
item runs twice. This module is that partition. It is inert unless a run names it:
with none of its options on the command line it registers nothing, and a local
``uv run pytest`` or ``just test-fast`` runs exactly as it did before it existed.

**One assignment, computed identically in every job** (§1:2). :func:`assign` maps
every collected item to one job index. It reads the collection and the job count
and never the index of the job computing it, so the shares cannot overlap or leave
a gap: the job holding index *i* keeps exactly the items assigned *i*. The index
and the count come from the matrix's own ``strategy.job-index`` and
``strategy.job-total``, which is what makes every index the assignment can produce
a job the workflow runs (§1:3).

**The triad's evidence stays in index 0** (§2:1). An item is evidence when its
class is one :func:`test_protocol_triad.static_candidacy` names a Protocol for, or
when it is an item of that module. This module calls that function rather than
restating it, so a change to what counts as a binding moves the partition with it.
Every other item goes by a hash of its node id, or of its ``xdist_group`` where the
group is kept whole. Index 0's share of those is weighted down by the evidence it
already holds, so every job carries about the same number of items.

**Index 0 is whole for the triad, and every other index is narrowed** (§2:2 and §2:3).
:func:`holds_the_triad_evidence` is what ``tests/conftest.py`` reads when it asks
whether a session ran the whole suite. The evidence job answers yes, so ADR-0179
§2:1 binds it exactly as it binds an unfiltered session: both checks are decided,
and a run that hands neither over fails. Every other job answers no, so it decides
neither check and is not failed for handing none over.

**The partition is the only selection** (§1:3). A partitioned run that is also
narrowed by an option or a path argument is refused before it collects anything.
In the evidence job that is §2:2's last clause: narrowing it would leave the
checks to skip, and a refused run cannot report a skip as a pass.

**Each job records its whole collection** for ``gate`` to compare (§1:4). An item
whose node id differed between jobs could hash to a different job in each and run
in none, and nothing inside one session would notice. The record is a list of
names and is not triad evidence; ``scripts/check_partition_collections.py`` reads
the jobs' records together.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

#: The index whose job holds every item of the triad's evidence (ADR-0310 §2:1). It
#: exists at every job count, so it cannot be left out of the workflow.
EVIDENCE_INDEX: Final = 0

#: ``xdist_group`` names whose items the partition divides among jobs rather than
#: keeping whole. ADR-0310 §3 lets the browser layer be divided, one browser per job
#: holding a share. Every other group is kept whole, because dividing one repeats
#: its shared session setup in every job that holds a part of it.
DIVIDED_GROUPS: Final = frozenset({"gateway_browser"})

#: How many hash points the unit interval is cut into. A key's point is its hash
#: modulo this, scaled into ``[0, 1)``.
_HASH_SPACE: Final = 2**64

#: The plugin's name in pytest's plugin manager, so a test can find the live one.
PLUGIN_NAME: Final = "suite-partition"


@dataclass(frozen=True)
class Partition:
    """One job's place in the partition, as its command line names it.

    Attributes:
        index: This job's index, ``0 <= index < count``.
        count: How many test jobs the workflow runs.
        manifest: Where to record the whole collection for ``gate`` (§1:4), or
            ``None`` to record nothing.
    """

    index: int
    count: int
    manifest: Path | None


@dataclass(frozen=True)
class Unit:
    """The smallest thing the partition places: one item, or one whole group.

    Attributes:
        key: What is hashed to place the unit: the node id of a lone item, or the
            name of a group kept whole.
        node_ids: Every collected item the unit holds.
        evidence: Whether any of them is triad evidence, which sends the whole
            unit to :data:`EVIDENCE_INDEX`.
    """

    key: str
    node_ids: tuple[str, ...]
    evidence: bool


def add_options(parser: pytest.Parser) -> None:
    """Register the partition's options. ``tests/conftest.py`` calls this."""
    group = parser.getgroup("partition", "CI's partition of the suite (ADR-0310)")
    group.addoption(
        "--partition-index",
        type=int,
        default=None,
        help="This job's index in CI's partition of the suite. Needs --partition-count.",
    )
    group.addoption(
        "--partition-count",
        type=int,
        default=None,
        help="How many jobs CI's partition divides the suite among.",
    )
    group.addoption(
        "--partition-manifest",
        default=None,
        help=(
            "Record this job's whole collection and the partition's assignment of it "
            "here, as JSON, for the workflow to compare across jobs."
        ),
    )


def partition_of(config: pytest.Config) -> Partition | None:
    """Return the partition this run names, or ``None`` for an ordinary run.

    Raises:
        pytest.UsageError: If the options name a partition only partly, or an
            index the count cannot hold.
    """
    index = config.getoption("partition_index", default=None)
    count = config.getoption("partition_count", default=None)
    manifest = config.getoption("partition_manifest", default=None)
    if index is None and count is None and manifest is None:
        return None
    if index is None or count is None:
        raise pytest.UsageError(
            "--partition-index and --partition-count name one partition together; "
            "give both or neither (ADR-0310 §1)."
        )
    if count < 1 or not 0 <= index < count:
        raise pytest.UsageError(
            f"--partition-index {index} --partition-count {count} names no job: the "
            f"index must be at least 0 and less than a count of at least 1."
        )
    path = None if manifest is None else config.invocation_params.dir / manifest
    return Partition(index=int(index), count=int(count), manifest=path)


def holds_the_triad_evidence(config: pytest.Config) -> bool:
    """Report whether this run holds every item of the triad's evidence.

    True for an ordinary run, and for the partition's evidence job. False for every
    other job of a partition, which is therefore a narrowed run for the triad
    (ADR-0310 §2:3).
    """
    partition = partition_of(config)
    return partition is None or partition.index == EVIDENCE_INDEX


def configure(config: pytest.Config, *, narrowed: bool) -> None:
    """Register the partition for a run that names one, and refuse a narrowed one.

    Args:
        config: The session's configuration.
        narrowed: Whether something other than the partition narrows the run: a
            filtering option or a path argument. ``tests/conftest.py`` owns that
            question and answers it.

    Raises:
        pytest.UsageError: If the run names a partition and is also narrowed.
    """
    partition = partition_of(config)
    if partition is None:
        return
    if narrowed:
        raise pytest.UsageError(
            "a partitioned run is narrowed by an option or a path argument, and "
            "ADR-0310 §1 makes the partition the only selection. In the evidence job "
            "a narrowed run would leave the Protocol-triad checks to skip, which §2 "
            "forbids: they are decided there, or the run fails. Drop the narrowing, "
            "or drop --partition-index and --partition-count."
        )
    config.pluginmanager.register(PartitionPlugin(partition), PLUGIN_NAME)


def group_of(item: pytest.Item) -> str | None:
    """Return the ``xdist_group`` an item belongs to, as xdist names it, or ``None``.

    xdist joins every group marker an item carries, sorted, which is the name its
    ``loadgroup`` scheduling keeps on one worker. Reading it the same way keeps a
    group the partition holds whole on one worker within its job too.
    """
    names = {
        str(mark.args[0] if mark.args else mark.kwargs.get("name", "default"))
        for mark in item.iter_markers("xdist_group")
    }
    return "_".join(sorted(names)) if names else None


def units_of(
    items: Iterable[pytest.Item], is_evidence: Callable[[pytest.Item], bool]
) -> list[Unit]:
    """Gather the collected items into the units the partition places.

    An item of a group kept whole joins that group's unit, so the group lands in
    one job. Every other item is a unit of its own, keyed by its node id. A unit is
    evidence when any item in it is.
    """
    members: dict[str, list[str]] = {}
    evidence: dict[str, bool] = {}
    for item in items:
        group = group_of(item)
        key = f"group:{group}" if group is not None and group not in DIVIDED_GROUPS else item.nodeid
        members.setdefault(key, []).append(item.nodeid)
        evidence[key] = evidence.get(key, False) or is_evidence(item)
    return [
        Unit(key=key, node_ids=tuple(ids), evidence=evidence[key]) for key, ids in members.items()
    ]


def point_of(key: str) -> float:
    """Return where ``key`` falls in ``[0, 1)``: the same answer in every process.

    A keyed digest rather than ``hash()``, which is salted per process.
    """
    digest = hashlib.blake2b(key.encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / _HASH_SPACE


def assign(units: Sequence[Unit], count: int) -> dict[str, int]:
    """Assign every item to one job index: the partition itself (ADR-0310 §1 and §2).

    Evidence goes to :data:`EVIDENCE_INDEX`. Every other unit goes by its hash
    point against cut points that give each job about ``total / count`` items:
    index 0 takes what is left of that after the evidence, and the others split the
    remainder equally.

    It takes no job index, so it cannot answer differently in different jobs, and
    nothing it reads depends on the order the items arrive in.

    Args:
        units: The whole collection, as :func:`units_of` gathers it.
        count: How many jobs the partition divides it among.

    Returns:
        Every node id the units hold, mapped to the index of the one job that runs
        it.
    """
    total = sum(len(unit.node_ids) for unit in units)
    pinned = sum(len(unit.node_ids) for unit in units if unit.evidence)
    rest = total - pinned
    first = max(0.0, total / count - pinned) / rest if count > 1 and rest else 1.0
    width = (1.0 - first) / (count - 1) if count > 1 else 0.0
    assignment: dict[str, int] = {}
    for unit in units:
        if unit.evidence or count == 1:
            index = EVIDENCE_INDEX
        else:
            point = point_of(unit.key)
            index = 0 if point < first else min(count - 1, 1 + int((point - first) / width))
        assignment.update(dict.fromkeys(unit.node_ids, index))
    return assignment


def evidence_predicate() -> Callable[[pytest.Item], bool]:
    """Return the test of whether an item is triad evidence (ADR-0310 §2:1).

    It asks :func:`test_protocol_triad.static_candidacy` of the item's class, once
    per class, and treats every item of that function's own module as evidence too.

    Imported here and not at module scope: ``test_protocol_triad`` is a test module,
    and pytest has to import (and assertion-rewrite) it before anything else does.
    By the time the partition runs, collection has done that.
    """
    from test_protocol_triad import static_candidacy  # noqa: PLC0415 — see docstring

    module = Path(inspect.getfile(static_candidacy)).resolve()
    candidacy: dict[type, bool] = {}

    def is_evidence(candidate: pytest.Item) -> bool:
        if Path(candidate.path).resolve() == module:
            return True
        cls = getattr(candidate, "cls", None)
        if cls is None:
            return False
        if cls not in candidacy:
            candidacy[cls] = bool(static_candidacy(cls))
        return candidacy[cls]

    return is_evidence


class PartitionPlugin:
    """Keep this job's share of the collection, and record the whole of it.

    Registered only when a run names a partition (see :func:`configure`).
    """

    def __init__(self, partition: Partition) -> None:
        self.partition = partition
        #: The whole collection's assignment, once collection has finished.
        self.assignment: dict[str, int] = {}
        #: The node ids the partition took as triad evidence.
        self.evidence: frozenset[str] = frozenset()

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(
        self, config: pytest.Config, items: list[pytest.Item]
    ) -> None:
        """Assign the whole collection, keep this job's share, and deselect the rest.

        ``tryfirst``, so it sees the collection whole and before any other hook
        reorders it, hands items over, or (on an xdist worker) suffixes a node id
        with its group. ``tests/conftest.py``'s own hook then sees only the share.
        """
        if not items:
            return
        is_evidence = evidence_predicate()
        units = units_of(items, is_evidence)
        self.assignment = assign(units, self.partition.count)
        self.evidence = frozenset(
            nodeid for unit in units if unit.evidence for nodeid in unit.node_ids
        )
        if self.partition.manifest is not None:
            write_manifest(self.partition.manifest, self.partition, self.assignment)
        keep = [item for item in items if self.assignment[item.nodeid] == self.partition.index]
        drop = [item for item in items if self.assignment[item.nodeid] != self.partition.index]
        items[:] = keep
        if drop:
            config.hook.pytest_deselected(items=drop)


def write_manifest(target: Path, partition: Partition, assignment: dict[str, int]) -> None:
    """Record the whole collection and its assignment where ``gate`` will read it.

    Every xdist worker of a job collects the same suite and writes the same bytes,
    so each writes beside the target and renames over it: whichever lands last, the
    file is whole.
    """
    node_ids = sorted(assignment)
    record = {
        "index": partition.index,
        "count": partition.count,
        "node_ids": node_ids,
        "assignment": [assignment[nodeid] for nodeid in node_ids],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    staging.write_text(json.dumps(record), encoding="utf-8")
    staging.replace(target)
