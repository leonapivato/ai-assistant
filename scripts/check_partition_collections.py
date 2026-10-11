"""Check that every CI test job collected the same suite (ADR-0310 §1:4).

CI's ``gate`` workflow runs its test step as several jobs, each keeping one share of
a partition of the suite (``tests/suite_partition.py``). Each job records its whole
collection and the partition's assignment of it, and ``gate`` hands every record to
this script. It fails unless:

- the records name one job count, and there is exactly one record for every index
  that count allows, so every share was run by a job that reported (§1:3);
- every record holds the same set of node ids (§1:4). An item whose node id
  differed between jobs could hash to a different job in each and run in none, and
  no single job could see that;
- every record holds the same assignment, so every job kept its share of one
  partition (§1:2), and every index it assigns is one of the jobs.

The records are lists of names and not triad evidence (ADR-0310 §1, closing
paragraph). Stdlib only, so ``gate`` can run it without the project's environment.

Exit status: 0 when the records agree, 1 when they do not, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: How many differing node ids a disagreement names, each way. Enough to say which
#: tests moved; the counts say how many.
_NAMED = 5


class RecordError(Exception):
    """A record that cannot be read as one job's collection."""


@dataclass(frozen=True)
class Record:
    """One test job's collection, as it recorded it.

    Attributes:
        source: The file it was read from.
        index: The job's index in the partition.
        count: How many jobs the partition named.
        node_ids: The job's whole collection, sorted.
        assignment: The index assigned to each node id, in the same order.
    """

    source: Path
    index: int
    count: int
    node_ids: tuple[str, ...]
    assignment: tuple[int, ...]


def read_record(path: Path) -> Record:
    """Read one job's record.

    Raises:
        RecordError: If the file is not a well-formed record.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RecordError(f"{path}: not readable as JSON ({error})") from error
    if not isinstance(raw, dict):
        raise RecordError(f"{path}: not a record")
    index, count = raw.get("index"), raw.get("count")
    node_ids, assignment = raw.get("node_ids"), raw.get("assignment")
    if not isinstance(index, int) or not isinstance(count, int):
        raise RecordError(f"{path}: index and count must be integers")
    if not isinstance(node_ids, list) or not all(isinstance(n, str) for n in node_ids):
        raise RecordError(f"{path}: node_ids must be a list of strings")
    if not isinstance(assignment, list) or not all(isinstance(a, int) for a in assignment):
        raise RecordError(f"{path}: assignment must be a list of integers")
    if len(assignment) != len(node_ids):
        raise RecordError(f"{path}: {len(node_ids)} node ids but {len(assignment)} assignments")
    if node_ids != sorted(set(node_ids)):
        raise RecordError(f"{path}: node_ids must be sorted and distinct")
    return Record(path, index, count, tuple(node_ids), tuple(assignment))


def _difference(first: Record, other: Record) -> str:
    """Say which node ids two records disagree on, a few each way."""
    left, right = set(first.node_ids), set(other.node_ids)
    only_first, only_other = sorted(left - right), sorted(right - left)
    lines = [
        f"job {first.index} and job {other.index} collected different suites: "
        f"{len(only_first)} node id(s) only in job {first.index}, "
        f"{len(only_other)} only in job {other.index}."
    ]
    lines += [f"  only in job {first.index}: {nodeid}" for nodeid in only_first[:_NAMED]]
    lines += [f"  only in job {other.index}: {nodeid}" for nodeid in only_other[:_NAMED]]
    return "\n".join(lines)


def check(records: Sequence[Record]) -> list[str]:
    """Return every way the records fail to describe one partition of one suite.

    An empty list means they agree.
    """
    if not records:
        return ["no test job recorded its collection, so nothing says the jobs ran one suite"]
    counts = sorted({record.count for record in records})
    if len(counts) != 1:
        return [f"the records name different job counts: {counts}"]
    (count,) = counts
    failures: list[str] = []
    indices = sorted(record.index for record in records)
    if indices != list(range(count)):
        failures.append(
            f"the partition names {count} job(s), so it needs one record for each of "
            f"indices {list(range(count))}; it has records for {indices}"
        )
    first = min(records, key=lambda record: record.index)
    failures.extend(
        _difference(first, other)
        for other in records
        if other is not first and other.node_ids != first.node_ids
    )
    if failures:
        return failures
    failures.extend(
        f"job {other.index} assigned the suite differently from job {first.index}, so the "
        f"two did not keep shares of one partition"
        for other in records
        if other is not first and other.assignment != first.assignment
    )
    stray = sorted({index for index in first.assignment if not 0 <= index < count})
    if stray:
        failures.append(f"the partition assigns items to indices no job holds: {stray}")
    return failures


def summary(records: Sequence[Record]) -> str:
    """Describe agreeing records: the suite's size and each job's share of it."""
    first = min(records, key=lambda record: record.index)
    shares = [first.assignment.count(index) for index in range(first.count)]
    described = ", ".join(f"job {index}: {size}" for index, size in enumerate(shares))
    return (
        f"{len(records)} test job(s) collected the same {len(first.node_ids)} items "
        f"and assigned them identically ({described})."
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Read every record under the given directory and check them together."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("directory", type=Path, help="where the jobs' records were gathered")
    args = parser.parse_args(argv)
    directory: Path = args.directory
    try:
        records = [read_record(path) for path in sorted(directory.rglob("*.json"))]
    except RecordError as error:
        print(f"check_partition_collections: {error}", file=sys.stderr)
        return 1
    failures = check(records)
    if failures:
        for failure in failures:
            print(f"check_partition_collections: {failure}", file=sys.stderr)
        return 1
    print(summary(records))
    return 0


if __name__ == "__main__":
    sys.exit(main())
