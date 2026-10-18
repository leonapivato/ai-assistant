"""ADR-0326 §7's upgrade check: the head opens what the base wrote.

On every pull request, CI's ``gate`` workflow runs this script's ``run`` command. It
writes a data directory with the build at the pull request's base, through every store
a person's hub keeps, and opens it with the build at the head. It fails where a store
refuses that directory (§7:1), where the head reads back other than what the base
wrote, as the head's upgrades carry it (§7:2), or where the directory holds a file no
store in ``scripts/upgrade_stores.py`` claims, which is how a store added without being
added to the check is caught (§7:3).

Three commands, and the two that touch the stores are the contract between builds:

- ``write DIR SNAPSHOT`` — run by the **base** build. Composes a hub's stores over the
  empty ``DIR``, writes each store's records through its own API, and saves what each
  store reads back to ``SNAPSHOT``.
- ``read DIR SNAPSHOT`` — run by the **head** build. Composes the stores over ``DIR``,
  reads every store back, and compares it with ``SNAPSHOT``.
- ``run [--base REV]`` — the driver. Checks ``REV`` (default ``origin/main``) out into a
  temporary worktree with its own environment, runs that build's ``write``, then runs
  this build's ``read``. A base with no copy of this script (the pull request that adds
  it, or one stacked on a branch that predates it) is written by **this** copy under
  the base's code, and the run says so.

Each command's reads are taken from a throwaway copy of ``DIR``, so a read that leases
(the outbox's) never changes the directory under test.

Exit status: 0 when the head opens and reads back everything, 1 when it does not, 2 on
a usage or environment error.
"""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from upgrade_stores import Json, Records, Store

#: The snapshot file's own format. A change to its layout raises it, and ``read``
#: refuses a format it does not know rather than comparing past it.
SNAPSHOT_FORMAT: Final = 1

#: The repository this copy of the script belongs to.
_ROOT: Final = Path(__file__).resolve().parent.parent

#: SQLite's sidecar suffixes; each belongs to the store whose file it follows.
_SIDECARS: Final = ("-wal", "-shm", "-journal")

#: Where the vendored models live in a tree. ``uv sync`` fetches them when they are
#: absent, so the base worktree is seeded with the head's to avoid a second download.
_VENDOR: Final = Path("src/ai_assistant/models/_vendor")


class CheckError(Exception):
    """The check could not be run: a usage or environment fault, not a finding."""


# --- what is read back, and how two read-backs compare -----------------------------------


def coverage(directory: Path, stores: Sequence[Store], not_stores: frozenset[str]) -> list[str]:
    """Every way ``directory``'s files and ``stores`` fail to match one another.

    Args:
        directory: A data directory the composition and the writers have filled.
        stores: The stores the check covers.
        not_stores: The entries under a data directory that are not stores.

    Returns:
        One line per file no store claims, and per store that left no file.
    """
    problems: list[str] = []
    claimed: set[str] = set()
    for entry in sorted(directory.iterdir()):
        if entry.name in not_stores:
            continue
        name = entry.name
        for suffix in _SIDECARS:
            name = name.removesuffix(suffix)
        owners = [
            store.name
            for store in stores
            if entry.is_file() and any(fnmatch.fnmatchcase(name, p) for p in store.files)
        ]
        if not owners:
            problems.append(
                f"{entry.name}: the hub keeps it under the data directory and no store in "
                "scripts/upgrade_stores.py claims it; a pull request that adds a store adds "
                "it to the upgrade check (ADR-0326 §7:3)"
            )
        claimed.update(owners)
    problems.extend(
        f"{store.name}: no file under the data directory matches {', '.join(store.files)}"
        for store in stores
        if store.name not in claimed
    )
    return problems


def _differs(expected: Json, actual: Json, where: str) -> str:
    """The message for a value the head reads back otherwise than the base did."""
    return f"{where}: the base read {json.dumps(expected)}, the head reads {json.dumps(actual)}"


def first_difference(expected: Json, actual: Json, path: str = "") -> str | None:
    """Where ``actual`` stops holding everything ``expected`` holds, or ``None``.

    An object may gain members, since a field added to a stored model reads back with
    its default; every member ``expected`` has must be there and hold the same. Lists
    are compared item by item, and every other value must be equal and of one type.

    Args:
        expected: What the base read back, carried to the head's shape.
        actual: What the head reads back.
        path: Where in the record these two values sit, for the message.

    Returns:
        A description of the first difference, or ``None`` where there is none.
    """
    where = path or "the record"
    pairs: list[tuple[Json, Json, str]]
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return _differs(expected, actual, where)
        missing = next((key for key in expected if key not in actual), None)
        if missing is not None:
            held = json.dumps(expected[missing])
            return f"{path}/{missing}: the base read {held}, the head reads nothing"
        pairs = [(value, actual[key], f"{path}/{key}") for key, value in expected.items()]
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return _differs(expected, actual, where)
        pairs = [
            (one, other, f"{path}[{index}]")
            for index, (one, other) in enumerate(zip(expected, actual, strict=True))
        ]
    else:
        same = type(expected) is type(actual) and expected == actual
        return None if same else _differs(expected, actual, where)
    return next(
        (found for one, other, at in pairs if (found := first_difference(one, other, at))),
        None,
    )


def compare_records(name: str, expected: Records, actual: Records) -> list[str]:
    """Every record of one store the head does not read back as the base did.

    Args:
        name: The store, for the messages.
        expected: The base's read-back, carried to the head's shape.
        actual: The head's read-back.

    Returns:
        One line per record missing, differing, or read back with no record behind it.
    """
    problems: list[str] = []
    for key, value in expected.items():
        if key not in actual:
            problems.append(f"{name} {key}: the base wrote it and the head reads back none")
            continue
        found = first_difference(value, actual[key])
        if found is not None:
            problems.append(f"{name} {key}: {found}")
    problems.extend(
        f"{name} {key}: the head reads back a record the base never wrote"
        for key in actual
        if key not in expected
    )
    return problems


def carried(store: Store, shape: int, records: Records) -> tuple[Records | None, str | None]:
    """The base's read-back of ``store`` at ``shape``, carried to the head's shape.

    Args:
        store: The head's entry for the store.
        shape: The shape the base read back at.
        records: What it read back.

    Returns:
        The carried records, or ``None`` and why they cannot be carried.
    """
    if shape > store.shape:
        return None, (
            f"{store.name}: the base reads it back at shape {shape} and the head only knows "
            f"shapes up to {store.shape}"
        )
    for step in range(shape, store.shape):
        carry = store.carries.get(step)
        if carry is None:
            return None, (
                f"{store.name}: the head reads it back at shape {store.shape} and has no carry "
                f"from shape {step}; scripts/upgrade_stores.py says how the head's upgrade "
                "carries what the base wrote (ADR-0326 §7:2)"
            )
        records = carry(records)
    return records, None


def compare(
    snapshot: Mapping[str, Json], head: Mapping[str, Records], stores: Sequence[Store]
) -> list[str]:
    """Every way the head's read-back differs from the base's, store by store.

    Args:
        snapshot: The base's snapshot, as ``write`` saved it.
        head: Each store's read-back by the head.
        stores: The head's stores.

    Returns:
        One line per difference; empty where the head reads back what the base wrote.
    """
    from upgrade_stores import cast_records  # noqa: PLC0415  # needs the package; see _stores

    if snapshot.get("format") != SNAPSHOT_FORMAT:
        return [
            f"the snapshot is format {snapshot.get('format')!r}; this build reads {SNAPSHOT_FORMAT}"
        ]
    sections = snapshot.get("stores")
    if not isinstance(sections, dict):
        return ["the snapshot holds no stores"]
    table = {store.name: store for store in stores}
    problems: list[str] = []
    for name, section in sections.items():
        store = table.get(name)
        if store is None:
            problems.append(
                f"{name}: the base wrote this store and the head checks no store of that name"
            )
            continue
        if not isinstance(section, dict) or not isinstance(section.get("shape"), int):
            problems.append(f"{name}: the snapshot's section is malformed")
            continue
        shape = section["shape"]
        assert isinstance(shape, int)  # noqa: S101  # checked just above
        expected, why = carried(store, shape, cast_records(section.get("records")))
        if expected is None:
            problems.append(why or name)
            continue
        if name not in head:
            continue  # the head's read refused, which is reported where it was read
        problems.extend(compare_records(name, expected, head[name]))
    return problems


# --- the two commands each build runs ------------------------------------------------------


def _stores() -> tuple[Sequence[Store], frozenset[str]]:
    """This build's stores. Imported late: ``run`` needs no ``ai_assistant`` at all."""
    import upgrade_stores  # noqa: PLC0415  # the base's or the head's package, as invoked

    return upgrade_stores.STORES, upgrade_stores.NOT_STORES


def _refuse_ambient_settings() -> None:
    """Refuse to run where an ``ASSISTANT_*`` variable could steer the composition."""
    ambient = sorted(name for name in os.environ if name.startswith("ASSISTANT_"))
    if ambient:
        msg = (
            f"{', '.join(ambient)} set; the check composes its own settings, so run it "
            "through `upgrade_check.py run`, which clears them"
        )
        raise CheckError(msg)


async def compose(directory: Path) -> str | None:
    """Open every store a hub opens over ``directory``, then close them.

    The composition root opens all but one; the device roster is opened by the hub
    itself (``service/hub.py``), so it is opened here the same way.

    Args:
        directory: The data directory, absolute.

    Returns:
        ``None``, or why the build refused the directory.
    """
    from upgrade_stores import check_settings  # noqa: PLC0415  # see _stores

    from ai_assistant.app import build_composition  # noqa: PLC0415  # see _stores
    from ai_assistant.service.enrolment import (  # noqa: PLC0415  # see _stores
        ENROLMENTS_FILENAME,
        EnrolmentStore,
    )

    try:
        composition = build_composition(check_settings(directory), data_dir=directory)
        await composition.engine.aclose()
        EnrolmentStore(directory / ENROLMENTS_FILENAME).close()
    except Exception as exc:  # any refusal is the finding, whatever its class
        return f"the build refuses the data directory: {type(exc).__name__}: {exc}"
    return None


async def read_back(
    directory: Path, stores: Sequence[Store]
) -> tuple[dict[str, Records], list[str]]:
    """Every store's records, read from a throwaway copy of ``directory``.

    Args:
        directory: The data directory.
        stores: The stores to read.

    Returns:
        Each store's records, and one line per store whose read refused.
    """
    records: dict[str, Records] = {}
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="upgrade-read-") as scratch:
        copy = Path(scratch) / "data"
        shutil.copytree(directory, copy, symlinks=True)
        for store in stores:
            try:
                records[store.name] = await store.read(copy)
            except Exception as exc:  # any refusal is the finding
                problems.append(f"{store.name}: refuses to read back: {type(exc).__name__}: {exc}")
    return records, problems


def write(directory: Path, snapshot_path: Path) -> list[str]:
    """Fill the empty ``directory`` through every store, and save what each reads back.

    Args:
        directory: Where to write; absent or empty.
        snapshot_path: Where to save the snapshot.

    Returns:
        What went wrong, which is the writer's own failure rather than the head's.

    Raises:
        CheckError: If ``directory`` holds anything.
    """
    if directory.exists() and any(directory.iterdir()):
        msg = f"{directory} is not empty; the base writes into an empty data directory"
        raise CheckError(msg)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    problems, snapshot = asyncio.run(_fill(directory.resolve()))
    snapshot_path.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n")
    return problems


async def _fill(directory: Path) -> tuple[list[str], dict[str, Json]]:
    """:func:`write`'s stores: compose, write each, check the files, read each back."""
    from upgrade_stores import Moment  # noqa: PLC0415  # see _stores

    stores, not_stores = _stores()
    refused = await compose(directory)
    if refused is not None:
        return [refused], {"format": SNAPSHOT_FORMAT, "stores": {}}
    moment = Moment(now=datetime.now(UTC).replace(microsecond=0))
    for store in stores:
        await store.write(directory, moment)
    problems = coverage(directory, stores, not_stores)
    records, unread = await read_back(directory, stores)
    problems.extend(unread)
    sections: dict[str, Json] = {
        store.name: {"shape": store.shape, "records": records[store.name]}
        for store in stores
        if store.name in records
    }
    return problems, {"format": SNAPSHOT_FORMAT, "stores": sections}


def read(directory: Path, snapshot_path: Path) -> list[str]:
    """Open ``directory`` with this build and compare it with the base's snapshot.

    Args:
        directory: The data directory the base wrote.
        snapshot_path: The snapshot the base saved.

    Returns:
        Every finding; empty where the head opens and reads back what the base wrote.

    Raises:
        CheckError: If the snapshot cannot be read.
    """
    try:
        snapshot = json.loads(snapshot_path.read_text())
    except (OSError, ValueError) as exc:
        msg = f"cannot read the base's snapshot {snapshot_path}: {exc}"
        raise CheckError(msg) from exc
    if not isinstance(snapshot, dict):
        msg = f"the base's snapshot {snapshot_path} is not an object"
        raise CheckError(msg)
    return asyncio.run(_check(directory.resolve(), snapshot))


async def _check(directory: Path, snapshot: Mapping[str, Json]) -> list[str]:
    """:func:`read`'s stores: compose, check the files, read each back, compare."""
    stores, not_stores = _stores()
    problems: list[str] = []
    refused = await compose(directory)
    if refused is not None:
        problems.append(refused)
    problems.extend(coverage(directory, stores, not_stores))
    records, unread = await read_back(directory, stores)
    problems.extend(unread)
    problems.extend(compare(snapshot, records, stores))
    return problems


# --- the driver ------------------------------------------------------------------------------


def _clean_environment() -> dict[str, str]:
    """This process's environment, less what would steer the other build."""
    return {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("ASSISTANT_") and name not in {"VIRTUAL_ENV", "PYTHONPATH"}
    }


def _call(argv: Sequence[str], *, cwd: Path | None = None) -> int:
    """Run ``argv`` to completion with :func:`_clean_environment`, and return its status."""
    return subprocess.run(  # noqa: S603  # fixed argv, no shell
        argv, cwd=cwd, env=_clean_environment(), check=False
    ).returncode


def _git(*args: str) -> str:
    """``git`` in this repository, its output stripped."""
    git = shutil.which("git")
    if git is None:
        msg = "git is not on PATH"
        raise CheckError(msg)
    completed = subprocess.run(  # noqa: S603  # resolved binary, fixed argv, no shell
        [git, "-C", str(_ROOT), *args], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        msg = f"git {' '.join(args)}: {completed.stderr.strip()}"
        raise CheckError(msg)
    return completed.stdout.strip()


def _seed_vendor(base: Path) -> None:
    """Give the base worktree this tree's vendored models, linked where the disk allows."""
    source = _ROOT / _VENDOR
    if not source.is_dir():
        return

    def link(src: str, dst: str) -> None:
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)

    shutil.copytree(source, base / _VENDOR, copy_function=link, dirs_exist_ok=True)


def run(base_rev: str, keep: Path | None) -> int:
    """Write a data directory with the build at ``base_rev`` and read it with this one.

    Args:
        base_rev: The pull request's base, as any revision ``git`` resolves.
        keep: Where to leave the base's directory and snapshot, or ``None`` to discard
            them.

    Returns:
        The exit status: 0 when the head opens and reads back what the base wrote, 1
        when it does not or the base's writer fails, 2 when the check cannot be run.

    Raises:
        CheckError: If the base cannot be resolved, checked out or given its environment.
    """
    uv = shutil.which("uv")
    if uv is None:
        msg = "uv is not on PATH"
        raise CheckError(msg)
    sha = _git("rev-parse", "--verify", f"{base_rev}^{{commit}}")
    head = _git("rev-parse", "HEAD")
    scratch = Path(tempfile.mkdtemp(prefix="upgrade-check-"))
    base = scratch / "base"
    if keep is not None:
        keep.mkdir(parents=True, exist_ok=True)
    data = (keep or scratch) / "data"
    snapshot = (keep or scratch) / "base-snapshot.json"
    try:
        _git("worktree", "add", "--detach", str(base), sha)
        own = base / "scripts" / "upgrade_check.py"
        writer = own if own.is_file() else Path(__file__).resolve()
        print(f"upgrade check: base {sha[:12]}, head {head[:12]}", flush=True)
        if writer != own:
            print(
                f"upgrade check: the base has no {own.relative_to(base)}; this copy writes "
                "under the base's code (bootstrapping)",
                flush=True,
            )
        _seed_vendor(base)
        if _call([uv, "sync", "--locked", "--quiet"], cwd=base) != 0:
            msg = f"could not give the base {sha[:12]} its locked environment"
            raise CheckError(msg)
        python = [uv, "run", "--no-sync", "python", "-I"]
        if _call([*python, str(writer), "write", str(data), str(snapshot)], cwd=base) != 0:
            print(f"upgrade check: the base {sha[:12]}'s writer failed", file=sys.stderr)
            return 1
        reader = [sys.executable, "-I", str(Path(__file__).resolve())]
        status = _call([*reader, "read", str(data), str(snapshot)])
        if status == 1:
            print(
                f"upgrade check: the head {head[:12]} does not open what the base "
                f"{sha[:12]} wrote (ADR-0326 §7)",
                file=sys.stderr,
            )
        return status
    finally:
        git = shutil.which("git") or "git"
        subprocess.run(  # noqa: S603  # fixed argv, no shell
            [git, "-C", str(_ROOT), "worktree", "remove", "--force", str(base)],
            capture_output=True,
            check=False,
        )
        shutil.rmtree(scratch, ignore_errors=True)


def _report(problems: Sequence[str], *, role: str) -> int:
    """Print ``problems`` and say how the check ended, and which build ran."""
    import ai_assistant  # noqa: PLC0415  # see _stores

    built = Path(ai_assistant.__file__).parent.parent
    print(f"upgrade check ({role}): the build in {built}", flush=True)
    for problem in problems:
        print(f"upgrade check ({role}): {problem}", file=sys.stderr)
    if problems:
        print(f"upgrade check ({role}): {len(problems)} finding(s)", file=sys.stderr)
        return 1
    print(f"upgrade check ({role}): every store opens and reads back what the base wrote")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line and run one command.

    Args:
        argv: The arguments, without the program name.

    Returns:
        The exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("write", "read"):
        command = commands.add_parser(name)
        command.add_argument("directory", type=Path)
        command.add_argument("snapshot", type=Path)
    driver = commands.add_parser("run")
    driver.add_argument("--base", default="origin/main")
    driver.add_argument("--keep", type=Path, default=None)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        if args.command == "run":
            return run(args.base, args.keep)
        _refuse_ambient_settings()
        if args.command == "write":
            return _report(write(args.directory, args.snapshot), role="base")
        return _report(read(args.directory, args.snapshot), role="head")
    except CheckError as exc:
        print(f"upgrade check: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
