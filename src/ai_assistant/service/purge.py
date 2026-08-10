"""``ai-assistant-purge``: destroy the contents of the data directory (ADR-0126).

The **fifth** member of the offline-tool family, here for the family's reason and
for one more of its own. The family's: "the tool's subject is
``Settings.data_dir``, the lock is ``service/lock.py``, ``lint-imports`` means the
entry point has to *be* in ``service/``, and ``service`` may import ``app`` and
``core`` (ADR-0083 §8)" (§2). Its own: an ``AssistantEngine`` method would be
derived into the wire's method set by ``wire/surface.py`` and therefore reachable
from an enrolled device, and ADR-0124 §6 forbids a remote connection modifying an
enrolment — let alone every enrolment there is (§2).

**The unit is the directory, not a set of stores** (§1). Every entry in the
resolved ``Settings.data_dir``, to any depth, with exactly one exception: the
instance lock file this act is holding. No inclusion list, no exclusion list
beyond that one entry, and no store is opened to empty it — "a delete assembled
from per-store ``clear`` calls is incomplete in exactly the same way" a backup
assembled from per-store exports is, "and its incompleteness is a privacy failure
rather than a durability one".

**What it refuses, it refuses before anything burns** (§1). A descendant mount
point of any kind — including a same-device bind mount, which is why the platform's
own mount table is consulted rather than a device comparison inferred from
``stat``; a platform that will not let this process enumerate its mount points at
all, because "an act that cannot see its own boundary does not get to guess where
it is"; an entry it would not be able to destroy, named with what about it fails,
because a ``lost+found`` met halfway through is a delete that "has destroyed data
and reported nothing"; and a contended instance lock.

**``devices.db`` goes first, and it is the one entry a failure stops the act at**
(§1, §5). Everything else is best effort: the act destroys what it can, names every
path that survived, and exits with a failure status. The enrolment record is exempt
because for it the trade runs the other way — stores destroyed with live verifiers
left behind is "a device left holding a credential to a store that no longer
exists", the outcome ADR-0124 §8 exists to prevent, produced by the act meant to
satisfy it.

**And it says what it did not reach** (§6, §7). A hub-side delete cannot touch a
credential on another machine, cannot touch a keyring it holds no face of, and
cannot touch a backup artifact ADR-0123 §11 requires to be written outside this
directory. The report names each, before the act and again after it, and it never
claims to have purged everything.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import stat
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import AssistantError, ConfigurationError
from ai_assistant.service import datadir
from ai_assistant.service.backup import SIDECAR_SUFFIXES
from ai_assistant.service.enrolment import ENROLMENTS_FILENAME, EnrolmentStore
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART, classify
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock
from ai_assistant.service.refusal import RefusalError

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from ai_assistant.service.enrolment import Enrolment

#: The act at an enrolled device that removes the credential this one cannot reach
#: (ADR-0124 §8, shipped in ``interfaces/cli.py`` as ``device unenrol``). §7
#: requires the report to name it for each device, and a report that named nothing
#: would satisfy ADR-0124 §8's first clause while breaching its second.
DEVICE_PURGE_ACT: Final = "assistant device unenrol"

#: Where Linux publishes the mount table this act's boundary test needs. §1 puts
#: the obligation over ``data_dir`` rather than over a filesystem precisely so that
#: a bind mount is caught: ``mount --bind`` produces a mount point whose source is
#: on the same device, "so a rule phrased over *filesystems* does not reach it and
#: a check that compares a directory's device with its parent's — which is what a
#: portable ``ismount`` reduces to — returns false for it".
MOUNT_TABLE: Final = Path("/proc/self/mountinfo")

#: Where the mount point sits on a ``mountinfo`` line, and the minimum field count
#: a line must have for that index to mean anything. The fields before it are the
#: mount id, the parent id, the device number and the root of the mount.
_MOUNT_POINT_FIELD: Final = 4
_MOUNT_POINT_FIELDS: Final = 5

#: ``mountinfo`` escapes four characters as a backslash and three octal digits, so
#: a mount point containing a space is one field rather than two.
_OCTAL_ESCAPE: Final = re.compile(r"\\([0-7]{3})")

#: Whether this platform can answer an access question about the *effective* user.
#: ``os.access`` asks about the real one by default, and a tool run under ``sudo -u``
#: would then be told about the wrong identity.
_EFFECTIVE_IDS: Final = os.access in os.supports_effective_ids

#: The three permissions §1's pre-check needs on every directory the act must
#: descend into, and the word each failure is reported with. Search is checked
#: beside the two §1 names because a directory cannot be *read into* without it,
#: which is the property the clause exists to establish.
_REQUIRED_ACCESS: Final = (
    (os.R_OK, "readable"),
    (os.W_OK, "writable"),
    (os.X_OK, "searchable"),
)

_DESCRIPTION = """
Destroy everything in this deployment's data directory (ADR-0126).

This is the delete right at the hub's own machine, and it is not undoable. It
destroys every file and directory inside the configured data directory, the
enrolment record first, leaving nothing but the instance lock it holds while it
works. The only way back is restoring a backup you took beforehand.

Run it with the hub stopped: it takes the same instance lock, so it cannot run
beside one. It shows what it is about to destroy and which devices you must
still visit, and it destroys nothing until you type the directory's path back.
"""

_EPILOG = """
examples:
  ai-assistant-purge
  ai-assistant-purge --confirm /home/you/.local/share/ai-assistant
"""


@dataclass(frozen=True, slots=True)
class _Survivor:
    """One path the act did not destroy, and what stopped it.

    Attributes:
        path: The entry that remains, as an operator would name it.
        error: Why it remains. Kept as the exception rather than as a string so
            :func:`~ai_assistant.service.exits.classify` decides the exit code from
            the same fault an operator reads about.
        opaque: Whether the failure also hid whatever is inside it — true for a
            directory the act could not open or list, where naming the contents is
            not possible and pretending otherwise would be a silent omission.
    """

    path: Path
    error: OSError
    opaque: bool = False


@dataclass(slots=True)
class _Level:
    """One level of the destroying walk: a held directory and what is left in it.

    Attributes:
        descriptor: The directory, opened ``O_NOFOLLOW`` from its parent's own
            descriptor — so the entry that was checked is the entry that is
            emptied, which a path re-resolved between the two would not be.
        relative: Its data-directory-relative path, ``""`` for the root.
        name: Its own name, ``""`` for the root.
        parent: The parent's descriptor, or ``None`` at the root — which is also
            what marks the one directory this act never removes (§1).
        children: The subdirectories still to descend into.
        listed: Whether its entries could be read at all. A directory that could
            not be listed is already reported, and attempting to remove it would
            report the same path a second time under a different errno.
    """

    descriptor: int
    relative: str
    name: str
    parent: int | None
    children: deque[str] = field(default_factory=deque)
    listed: bool = True


@dataclass(frozen=True, slots=True)
class _Devices:
    """§7's device list, and why it is empty when it is.

    Attributes:
        live: Every device holding a live enrolment, complete and unbounded.
        note: What to say instead of a list, when there is a reason rather than
            simply no devices. §7 forbids omitting the subject: "the report says so
            plainly — that this installation has enrolled no device — rather than
            omitting the subject".
    """

    live: tuple[Enrolment, ...]
    note: str | None = None


def main(argv: Sequence[str] | None = None) -> int:
    """Destroy the data directory's contents and return the process's exit code.

    Args:
        argv: Command-line arguments, for tests. ``None`` reads ``sys.argv``.

    Returns:
        ``0`` when the directory holds nothing but the instance lock, ``78`` for
        every refusal ADR-0126 defines and for a destruction that failed in a way
        a rerun cannot survive unchanged, and ``1`` for a contended lock or a
        failure a later attempt might get past. The vocabulary is the hub's
        (:mod:`ai_assistant.service.exits`), which is ADR-0083 §5's test rather
        than a table.
    """
    args = _parse_args(argv)
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        return _report(exc)
    try:
        return _purge(settings.data_dir, confirmation=args.confirm)
    except RefusalError as exc:
        print(f"the purge was refused: {exc}", file=sys.stderr)
        return EXIT_DEPLOYMENT
    except KeyboardInterrupt:
        # Deliberately claims nothing about what is left. An interrupt before the
        # confirmation is answered by `_confirm`, which can honestly say nothing
        # was destroyed; one that arrives mid-destruction cannot, and §1 forbids
        # reporting a delete as complete or passing over an entry silently.
        print("\ninterrupted.", file=sys.stderr)
        return EXIT_RESTART
    except (AssistantError, OSError) as exc:
        return _report(exc)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Read how the confirmation arrives, and nothing else.

    **There is no argument that widens the act**, and that is one of ADR-0004 §7's
    three replacements rather than a small surface: §11 grants the gate exemption
    only to an act "confined to one purpose and one path, destroying the resolved
    ``data_dir`` and nothing else, with no argument that widens it". The directory
    comes from configuration for the reason every offline tool gives — a tool that
    could be pointed at another deployment's store is a way to destroy one
    deployment's data while believing it was another's.
    """
    parser = argparse.ArgumentParser(
        prog="ai-assistant-purge",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--confirm",
        type=Path,
        default=None,
        metavar="DATA_DIR",
        help=(
            "confirm without a prompt by naming the data directory to destroy; "
            "it must be the configured one (ADR-0126 §7)"
        ),
    )
    return parser.parse_args(argv)


def _purge(data_dir: Path, *, confirmation: Path | None) -> int:
    """Refuse what can be refused before the lock, then take it and do the work.

    **ADR-0083 §3's step 2 runs in full, and that is §1's own choice rather than
    this tool's.** §1 describes the surviving directory as carrying "the permissions
    ADR-0083 §3's preparation gives it", which is the state
    :func:`~ai_assistant.service.datadir.prepare` establishes — it validates the
    leaf's ownership and mode and every ancestor's, which is also where §11's second
    replacement for ADR-0004 §7's gate gets its substance ("custody is the operating
    system's own access control"). It is what the backup tool does with the same
    subject.

    It carries one condition §1 does not enumerate: #554's ``sun_path`` budget on
    the socket this act will never bind. That is accepted rather than skipped
    because a data directory failing it is one no hub in this deployment can ever
    have served, so there is no installation whose delete right it withholds — and
    it exits ``78`` naming the remedy, after which the same command succeeds.
    """
    # Preparation also creates the directory when it is absent, which is §1's own
    # end state — an installation with no data in it — arrived at with nothing
    # destroyed.
    datadir.prepare(data_dir)
    _refuse_descendant_mounts(data_dir)

    lock = InstanceLock(data_dir / LOCK_FILENAME)
    if not lock.acquire():
        return _report_contention(lock)
    try:
        return _run_locked(data_dir, confirmation=confirmation)
    finally:
        lock.release()


def _run_locked(data_dir: Path, *, confirmation: Path | None) -> int:
    """Everything §5 requires to happen under one instance lock.

    The lock is taken before the record is read and held past the last
    destruction, which is what makes "as part of the same act" a fact rather than
    a hope: while it is held no hub can start, so no process exists that could
    read a half-destroyed directory or admit a device against a record that is
    gone.
    """
    devices = _live_enrolments(data_dir)
    _refuse_unremovable(data_dir)
    _state_before(data_dir, devices)
    _confirm(data_dir, given=confirmation)

    survivors = _destroy(data_dir)
    return _state_after(data_dir, devices, survivors)


def _live_enrolments(data_dir: Path) -> _Devices:
    """Read every live enrolment, completely, without creating the record (§7).

    **Complete rather than bounded**, which is why this reads the record instead
    of reusing the control socket's listing: that surface stops at
    ``LISTING_LIMIT`` and returns an omitted count, and "a report that named the
    first two hundred devices and counted the rest would be a delete presenting
    itself as complete for every device it did not name".

    **And it never creates the record to report on it** (§7). ``EnrolmentStore``
    creates the file it is pointed at, and every loopback-only hub — which is every
    hub shipped so far — holds a full data directory and no ``devices.db``. So the
    entry is examined first, and only a regular file is opened.

    Args:
        data_dir: The data directory whose record to read.

    Returns:
        The live enrolments, or an empty list with the reason it is empty.

    Raises:
        RefusalError: If the record exists and cannot be read. §7's list has to be
            complete, and an unreadable record is a list this act cannot state —
            so it refuses before destroying anything rather than destroying
            everything behind a report it knows to be silent.
    """
    record = data_dir / ENROLMENTS_FILENAME
    try:
        info = record.lstat()
    except FileNotFoundError:
        return _Devices(live=())
    except OSError as exc:
        msg = (
            f"{record} could not be examined, so this act cannot state which devices are "
            f"enrolled: {exc}"
        )
        raise RefusalError(msg) from exc

    if not stat.S_ISREG(info.st_mode):
        # §1 decides an entry's type on the entry and never on what it resolves
        # to, and what a link names "is not read". So the record is not opened
        # through it; the entry is still destroyed, as the entry it is.
        note = (
            f"{record} is not a regular file, so it was not opened and not read — this act "
            f"never follows a link. The entry is destroyed as the entry it is, and whatever "
            f"it may name is neither read nor destroyed"
        )
        return _Devices(live=(), note=note)

    try:
        store = EnrolmentStore(record)
    except sqlite3.Error as exc:
        msg = (
            f"{record} could not be opened as the enrolment record, so this act cannot state "
            f"which devices are enrolled: {exc}. Move it aside and run this again"
        )
        raise RefusalError(msg) from exc
    try:
        live = tuple(store.live_enrolments())
    except sqlite3.Error as exc:
        msg = (
            f"{record} could not be read, so this act cannot state which devices are "
            f"enrolled: {exc}. Move it aside and run this again"
        )
        raise RefusalError(msg) from exc
    finally:
        store.close()
    return _Devices(live=live)


def _refuse_descendant_mounts(data_dir: Path) -> None:
    """Refuse a mount point *strictly beneath* the boundary, of any kind (§1).

    **Strictly beneath, because the difference is a whole supported deployment.**
    ``ASSISTANT_DATA_DIR`` pointed at the root of a dedicated local volume is a
    mount point and a good arrangement; "a mount point *at* the boundary is the
    boundary, and destroying everything inside it is the act". What the clause is
    for is a mount point that lets the act reach storage the boundary does not
    contain, and only a descendant can do that.

    Args:
        data_dir: The boundary, resolved here for the reason every other
            containment test in this package resolves: two spellings of one
            directory would otherwise compare unequal.

    Raises:
        RefusalError: On a descendant mount point, or when the table cannot be
            enumerated.
    """
    boundary = data_dir.resolve()
    for point in _mount_points():
        if point != boundary and point.is_relative_to(boundary):
            msg = (
                f"{point} is a mount point beneath the data directory {boundary}, so it names "
                f"storage this directory holds rather than contains and destroying through it "
                f"would destroy data this act has no claim on; unmount it and run this again"
            )
            raise RefusalError(msg)


def _mount_points() -> Iterator[Path]:
    """Every mount point this process can see, from the platform's own table.

    Yields:
        Each mount point, unescaped.

    Raises:
        RefusalError: If the table cannot be read or a line cannot be parsed.
            Both are the same conservative close: §1 says that "where the platform
            gives an implementation no way to enumerate its mount points, the act
            refuses to run rather than proceeding on a test it knows to be
            incomplete", and a line this parser does not understand is a mount
            point it cannot see.
    """
    try:
        table = MOUNT_TABLE.read_text(encoding="utf-8")
    except OSError as exc:
        msg = (
            f"the mount table {MOUNT_TABLE} could not be read ({exc}), so this act cannot tell "
            f"whether anything is mounted inside the data directory; it will not guess, and "
            f"this platform is not one it can run on"
        )
        raise RefusalError(msg) from exc
    for line in table.splitlines():
        fields = line.split(" ")
        if len(fields) < _MOUNT_POINT_FIELDS:
            msg = (
                f"a line of the mount table {MOUNT_TABLE} could not be read, so the list of "
                f"mount points is incomplete and this act will not proceed on it: {line!r}"
            )
            raise RefusalError(msg)
        point = fields[_MOUNT_POINT_FIELD]
        yield Path(_OCTAL_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), point))


def _refuse_unremovable(data_dir: Path) -> None:
    """Refuse, destroying nothing, if any entry found is one it could not destroy (§1).

    The case that showed this was owed is ``lost+found``: ``mkfs`` puts a
    root-owned, mode-``0700`` directory at the root of an ext filesystem, it
    survives an operator ``chown``ing that root to themselves, and a walk meets its
    ``PermissionError`` "partway through, having already destroyed the enrolment
    record and most of the stores".

    Every directory is checked rather than every entry, and that covers both halves
    of the clause: the directories to descend into are exactly the directories
    checked, and every entry's parent is one of them.

    Args:
        data_dir: The directory whose contents will be destroyed.

    Raises:
        RefusalError: Naming each path that fails and what about it fails.
    """
    failures: list[str] = []
    for directory in _directories(data_dir, failures):
        for mode, word in _REQUIRED_ACCESS:
            if not os.access(directory, mode, effective_ids=_EFFECTIVE_IDS):
                failures.append(f"{directory} is not {word} by this process")
    if not failures:
        return
    listed = "\n  ".join(failures)
    msg = (
        f"nothing was destroyed, because {len(failures)} thing(s) about the data directory "
        f"{data_dir} would have stopped the act partway through:\n  {listed}\n"
        f"Deal with each, then run this again. Where the path is a filesystem's own "
        f"lost+found, the usual remedy is to point ASSISTANT_DATA_DIR at a directory "
        f"inside the mount rather than at its root"
    )
    raise RefusalError(msg)


def _directories(data_dir: Path, failures: list[str]) -> Iterator[Path]:
    """The data directory and every real directory beneath it, breadth first.

    A symbolic link is never descended into, whatever it names: §1 makes every
    decision about an entry's type on the entry itself.

    Args:
        data_dir: The root of the walk.
        failures: Collects directories that could not be listed, which are as much
            a reason to refuse as one that fails an access check.

    Yields:
        Each directory, including ``data_dir`` itself.
    """
    pending = deque([data_dir])
    while pending:
        directory = pending.popleft()
        yield directory
        try:
            with os.scandir(directory) as scan:
                entries = sorted(scan, key=lambda item: item.name)
        except OSError as exc:
            failures.append(f"{directory} could not be listed: {exc}")
            continue
        pending.extend(Path(entry.path) for entry in entries if entry.is_dir(follow_symlinks=False))


def _state_before(data_dir: Path, devices: _Devices) -> None:
    """§7's statement, made before anything is destroyed.

    **Before, because of the crash.** After the act the record naming the devices
    is gone, so "an implementation that composed its report from the record and
    printed it at the end would, on a crash between the two, destroy the enrolment
    record and leave the owner with no way to learn which devices they must still
    visit". The restatement afterwards is a convenience; this is the guarantee.
    """
    print(f"about to destroy everything in {data_dir}")
    print("  every file and directory inside it, to any depth, the enrolment record first.")
    print(f"  only {LOCK_FILENAME}, the instance lock this act holds, survives.")
    print("  there is no undo. The only way back is restoring a backup you already took.")
    print()
    _state_devices(devices, heading="devices you must still visit:")
    print()
    print("what this act does not reach:")
    print(
        f"  no keyring. A model provider credential you hold in your environment or a shell "
        f"profile is not in the keyring, is not in {data_dir}, and is not removed here — "
        f"remove it where you set it."
    )
    print(
        "  no backup artifact. A backup is written outside the data directory, so a complete "
        "encrypted copy of everything destroyed here may still exist; deal with it yourself."
    )
    print()
    print("what this act may not claim, so it does not:")
    print("  it does not purge everything.")
    print("  it reaches nothing on an enrolled device.")
    print(
        "  it does not retract what a device already holds. What a device received before "
        "this act, it keeps."
    )
    print()


def _state_devices(devices: _Devices, *, heading: str) -> None:
    """Name every live enrolment, and the act at each that this one cannot perform.

    §7 requires the act at each device to be named, and ADR-0126 §9 sequences this
    whole tool behind that act existing: "a report that cannot name one does not
    satisfy ADR-0124 §8's second clause".
    """
    if devices.note is not None:
        print(f"enrolments: {devices.note}")
        return
    if not devices.live:
        print("enrolments: this installation has enrolled no device.")
        return
    print(heading)
    for enrolment in devices.live:
        print(f"  {enrolment.overlay_identity}  (enrolled {enrolment.enrolled_at.isoformat()})")
    print(
        f"  a delete performed here cannot reach any of them. Run `{DEVICE_PURGE_ACT}` on each "
        f"one to remove the credential it still holds."
    )


def _confirm(data_dir: Path, *, given: Path | None) -> None:
    """Take the owner's confirmation against the resolved path (§7, §11).

    **A bare affirmative flag does not satisfy the clause**, so there is none: a
    non-interactive confirmation names the directory, and naming it is the one
    part of the ceremony a script cannot pass by accident. It is also the third of
    ADR-0004 §7's replacements — "the owner's confirmation against the resolved
    path is taken before anything is destroyed, in person, at that machine" — so
    weakening it would take the gate exemption §11 grants with it.

    Args:
        data_dir: The directory the confirmation must name.
        given: What ``--confirm`` carried, or ``None`` to prompt.

    Raises:
        RefusalError: If the confirmation names something else, or cannot be read.
    """
    if given is not None:
        if _names(given, data_dir):
            return
        msg = (
            f"--confirm named {given}, which is not the data directory this act would destroy "
            f"({data_dir}); nothing was destroyed"
        )
        raise RefusalError(msg)
    try:
        typed = input(f"type {data_dir} to destroy it, or anything else to stop: ")
    except (EOFError, KeyboardInterrupt) as exc:
        msg = "no confirmation was given, so nothing was destroyed"
        raise RefusalError(msg) from exc
    if not _names(Path(typed.strip()) if typed.strip() else None, data_dir):
        msg = f"the confirmation did not name {data_dir}, so nothing was destroyed"
        raise RefusalError(msg)


def _names(given: Path | None, data_dir: Path) -> bool:
    """Whether a path an operator supplied is this deployment's data directory.

    Compared as typed and again resolved, so a spelling through a symbolic link or
    a ``~`` counts — and an empty string never does, which it would if it reached
    ``Path("").resolve()`` and became the working directory.
    """
    if given is None:
        return False
    candidate = given.expanduser()
    if candidate == data_dir:
        return True
    try:
        return candidate.resolve() == data_dir.resolve()
    except OSError:
        return False


def _destroy(data_dir: Path) -> list[_Survivor]:
    """Destroy the directory's contents, the enrolment record first (§1, §5).

    Args:
        data_dir: The directory to empty.

    Returns:
        Every path that remains, and why. Empty on a complete act.

    Raises:
        OSError: If the data directory itself cannot be opened. Left to propagate:
            nothing has been destroyed, and ``classify`` is what decides whether a
            later attempt could get past it.
    """
    root = _open_directory(None, str(data_dir))
    try:
        blocked = _destroy_record(root, data_dir=data_dir)
        if blocked is not None:
            # §1's one exception to best-effort continuation. Continuing past a
            # failed enrolment record "reconstructs precisely the state §5's
            # ordering exists to make unreachable": live verifiers on disk with
            # the stores around them gone, so the next hub start rebuilds empty
            # stores and admits every enrolled device to them.
            return [blocked]
        survivors = _destroy_sidecars(root, data_dir=data_dir)
        reserved = {LOCK_FILENAME, ENROLMENTS_FILENAME}
        reserved.update(f"{ENROLMENTS_FILENAME}{suffix}" for suffix in SIDECAR_SUFFIXES)
        survivors.extend(_destroy_tree(root, data_dir=data_dir, reserved=frozenset(reserved)))
    finally:
        os.close(root)
    return survivors


def _destroy_record(root: int, *, data_dir: Path) -> _Survivor | None:
    """Destroy ``devices.db`` first, and say if that is where the act stops (§5).

    **First, because the order is the one place a crash could produce a genuinely
    bad state.** Stores destroyed first and a crash before the record leaves live
    enrolments against a hub that will start, rebuild empty stores and admit every
    enrolled device — the exact outcome ADR-0124 §8 exists to prevent. The other
    way round leaves data no device can reach, and the owner reruns the command.

    Returns:
        ``None`` when the record is gone or was never there — §4's installation
        that "has never configured a remote listener holds no enrolment record,
        and there the clause is satisfied with nothing to destroy" — or the
        failure that stops the act.
    """
    try:
        os.unlink(ENROLMENTS_FILENAME, dir_fd=root)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return _Survivor(path=data_dir / ENROLMENTS_FILENAME, error=exc)
    return None


def _destroy_sidecars(root: int, *, data_dir: Path) -> list[_Survivor]:
    """Destroy the record's sidecars immediately after it, before anything else (§5).

    **Named because a database is not one file**: a ``-wal`` "holds committed
    pages" of the store it belongs to, so ``devices.db-wal`` can hold a live
    verifier after ``devices.db`` is gone.

    **And they are not under the record's exemption.** §5 is explicit that "a
    ``-wal`` left without it is pages no process in this system can open as a
    database, and the rerun removes it", so a sidecar that resists is best effort
    like everything else — it is the *main file* that makes an enrolment live.
    """
    survivors: list[_Survivor] = []
    for suffix in SIDECAR_SUFFIXES:
        name = f"{ENROLMENTS_FILENAME}{suffix}"
        try:
            os.unlink(name, dir_fd=root)
        except FileNotFoundError:
            continue
        except OSError as exc:
            survivors.append(_Survivor(path=data_dir / name, error=exc))
    return survivors


def _destroy_tree(root: int, *, data_dir: Path, reserved: frozenset[str]) -> list[_Survivor]:
    """Empty the directory depth-first, holding one descriptor per *level*.

    **Descriptors, because a name is not an object**, which matters more for a
    destruction than for the copy ADR-0123 §1 argued it for: a directory that was a
    directory when it was listed can be a symlink by the time an entry inside it is
    unlinked, and the unlink would then reach outside the boundary §1 states the
    obligation over. Each directory is opened ``O_NOFOLLOW`` from its parent's
    descriptor, and every removal is made relative to that descriptor.

    **Per level rather than per directory**, so the cost is the tree's depth and
    not its width — the shape a wide directory turned into ``EMFILE`` for the
    backup tool's first walk.

    Args:
        root: The data directory's own descriptor. Not closed here: the caller
            opened it and the enrolment record went through it first.
        data_dir: The data directory, for the paths a report names.
        reserved: Root-level names this walk leaves alone — the instance lock this
            act holds, and the enrolment record and sidecars already dealt with.

    Returns:
        Every path that remains, and why.
    """
    survivors: list[_Survivor] = []
    levels = [_Level(descriptor=root, relative="", name="", parent=None)]
    _fill(levels[0], data_dir=data_dir, reserved=reserved, survivors=survivors)
    try:
        while levels:
            level = levels[-1]
            if level.children:
                _descend(levels, data_dir=data_dir, survivors=survivors)
                continue
            levels.pop()
            if level.parent is None:
                # The data directory itself survives, holding nothing but the
                # lock file this act is holding (§1). It is never removed and its
                # descriptor belongs to the caller.
                continue
            os.close(level.descriptor)
            _remove_directory(level, data_dir=data_dir, survivors=survivors)
    finally:
        for level in levels:
            if level.parent is not None:
                os.close(level.descriptor)
    return survivors


def _descend(levels: list[_Level], *, data_dir: Path, survivors: list[_Survivor]) -> None:
    """Enter the next subdirectory of the innermost level, or record why not."""
    level = levels[-1]
    name = level.children.popleft()
    relative = f"{level.relative}/{name}" if level.relative else name
    try:
        descriptor = _open_directory(level.descriptor, name)
    except OSError as exc:
        survivors.append(_Survivor(path=data_dir / relative, error=exc, opaque=True))
        return
    child = _Level(descriptor=descriptor, relative=relative, name=name, parent=level.descriptor)
    levels.append(child)
    _fill(child, data_dir=data_dir, reserved=frozenset(), survivors=survivors)


def _fill(
    level: _Level, *, data_dir: Path, reserved: frozenset[str], survivors: list[_Survivor]
) -> None:
    """Unlink everything in one directory that is not a directory, and queue those that are.

    Every type decision is ``follow_symlinks=False``, so a symbolic link naming a
    directory is unlinked here as the link it is rather than descended into (§1) —
    "``data_dir/x -> /home/owner/photos`` turns 'destroy every entry, to any depth'
    into the destruction of a directory the owner never named".
    """
    try:
        with os.scandir(level.descriptor) as scan:
            entries = sorted(scan, key=lambda item: item.name)
    except OSError as exc:
        level.listed = False
        survivors.append(_Survivor(path=data_dir / level.relative, error=exc, opaque=True))
        return
    for entry in entries:
        if entry.name in reserved:
            continue
        if entry.is_dir(follow_symlinks=False):
            level.children.append(entry.name)
            continue
        relative = f"{level.relative}/{entry.name}" if level.relative else entry.name
        try:
            os.unlink(entry.name, dir_fd=level.descriptor)
        except FileNotFoundError:
            continue
        except OSError as exc:
            survivors.append(_Survivor(path=data_dir / relative, error=exc))


def _remove_directory(level: _Level, *, data_dir: Path, survivors: list[_Survivor]) -> None:
    """Remove an emptied directory from its parent, unless it is already reported."""
    if not level.listed:
        # Its contents could not be read, so it is not empty and the failure that
        # made it unreadable is already in the report. A second entry under
        # ``ENOTEMPTY`` would name the same path for a consequence rather than a
        # cause (§1 asks for every path that remains *and why*).
        return
    assert level.parent is not None  # noqa: S101 - the root never reaches here (`parent is None`)
    try:
        os.rmdir(level.name, dir_fd=level.parent)
    except FileNotFoundError:
        return
    except OSError as exc:
        survivors.append(_Survivor(path=data_dir / level.relative, error=exc))


def _open_directory(directory: int | None, name: str) -> int:
    """Open a directory no-follow, relative to its parent's descriptor.

    Args:
        directory: The parent's descriptor, or ``None`` to open ``name`` as an
            absolute path — which is only ever the walk's root.
        name: The directory's own name, or the root's path.

    Returns:
        A descriptor for the directory.

    Raises:
        OSError: If it cannot be opened, including because it is a symbolic link
            (``ELOOP``) or stopped being a directory (``ENOTDIR``). Left as the raw
            fault, where the backup tool converts the same errno into a refusal:
            §1 destroys a link rather than refusing one, so there is nothing here
            to convert it into, and the caller records the path with its own errno.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    if directory is None:
        return os.open(name, flags)
    return os.open(name, flags, dir_fd=directory)


def _state_after(data_dir: Path, devices: _Devices, survivors: list[_Survivor]) -> int:
    """Say what remains, restate the devices, and return the act's exit code (§1, §7).

    Args:
        data_dir: The directory the act emptied.
        devices: §7's list, read before the record was destroyed.
        survivors: Every path that remains, and why.

    Returns:
        ``0`` when nothing remains, and otherwise the code ADR-0083 §5's test gives
        the failures — ``78`` when at least one of them is a fault a rerun would
        meet unchanged, ``1`` when every one of them might clear.
    """
    print()
    if not survivors:
        print(f"destroyed. {data_dir} now holds nothing but {LOCK_FILENAME}.")
    else:
        print(f"the purge did not complete. {len(survivors)} path(s) remain in {data_dir}:")
        for survivor in survivors:
            inside = " (and everything inside it)" if survivor.opaque else ""
            print(f"  {survivor.path}{inside}: {survivor.error}")
        print("Deal with each, then run this again — the act is repeatable.")
    print()
    _state_devices(devices, heading="devices you must still visit:")
    if not survivors:
        return EXIT_OK
    return _failure_code(survivors)


def _failure_code(survivors: list[_Survivor]) -> int:
    """Map a partial destruction onto ADR-0083 §5's two failure codes.

    §5's test is one question — "would restarting, unchanged, ever succeed?" — and
    a partial destruction answers it once per surviving path. One path that a
    rerun would meet unchanged is enough to make the whole act one a human must act
    on, which is what ``78`` says; every other failure keeps §5's default, where "a
    spurious restart is recoverable and a spurious ``78`` is an outage".
    """
    for survivor in survivors:
        code, action = classify(survivor.error)
        if code == EXIT_DEPLOYMENT:
            print(f"what to do: {action}", file=sys.stderr)
            return EXIT_DEPLOYMENT
    return EXIT_RESTART


def _report_contention(lock: InstanceLock) -> int:
    """Say that something else holds the lock, hedging the pid exactly as ADR-0083 §1 does."""
    pid = lock.recorded_pid()
    hint = f" (the lock file records pid {pid}, which may be stale)" if pid is not None else ""
    print(
        f"{lock.path} is held by another instance{hint}. Nothing was destroyed — stop the hub, "
        f"then run this again.",
        file=sys.stderr,
    )
    return EXIT_RESTART


def _report(exc: BaseException) -> int:
    """Print a failure and return the code ADR-0083 §5's test gives it."""
    code, action = classify(exc)
    print(f"the purge did not run: {exc}", file=sys.stderr)
    if action:
        print(f"what to do: {action}", file=sys.stderr)
    return code
