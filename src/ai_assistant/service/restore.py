"""``ai-assistant-restore``: build a fresh data directory out of an artifact.

ADR-0123 §7 gives this tool a shape rather than a procedure, and every clause
falls out of it: **it builds beside the target and replaces nothing.** "Nothing
that exists is modified, so there is no path — including a crash — on which a
half-restored directory becomes something a hub serves: before the rename the
target path does not exist … after the rename the directory is complete and has
passed every check §8 requires."

**It takes no instance lock, and that is a decision** (§7). The lock serialises
processes over a *shared* directory; this run's staging directory is one it just
created, in a parent only its owner may write, that nothing is configured to look
at. Taking one anyway would cost more than it bought: the lock would have to live
inside the target, which means creating the target, which is the state the first
refusal exists to prevent — and it could not be cleaned up, because
``InstanceLock.release`` deliberately does not unlink its file. It also makes a
retry ordinary: a mistyped passphrase leaves nothing at the target, so the
operator simply runs the command again.

**It refuses the live data directory by name** (§7), because that is the one
target where the gap between the refusal check and the rename is not harmless: a
supervised hub can start in it, find an absent directory, create it, initialise an
empty store — and the rename then fails, leaving "a hub serving an empty model and
a recovery that will not land".

**And it leaves compatibility to the hub** (§8). A restored store this build
cannot serve is detected at startup as an ``IncompatibleStateError``, exit ``78``,
with ADR-0104 as the remedy. Answering the same question here would mean
reimplementing that detection over a directory this tool has not opened, and
refusing restores the hub would have handled.

**A restored directory is not a working installation, and that is the correct
trade** (§6). Tier 0 lives in the OS keyring and never enters an artifact, so the
hub comes up with the accumulated model intact and its provider credentials
absent. Neither is the trace store there: §3 excludes it under ADR-0119 §12, and
ADR-0120 §8 already rules what a report over an empty stream says.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import AssistantError, ConfigurationError
from ai_assistant.service import artifact, passphrase
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART, classify
from ai_assistant.service.refusal import RefusalError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.service.artifact import Manifest

_DESCRIPTION = """
Restore a backup artifact into a fresh directory (ADR-0123).

It never writes where a hub is expected to look. The artifact is unpacked into a
staging directory beside the target you name, checked file by file against the
manifest it carries, and only then renamed into place — so a failed restore
leaves the target untouched and a successful one is complete the moment it
appears. Moving the result into service is your act, not this tool's.

It needs nothing from the machine that took the backup: no keyring, no
configuration, only the passphrase. What it does not restore is the machine's
credentials, which live in the OS keyring and never enter an artifact — the hub
comes up with the accumulated model intact and its provider keys to re-provision.
"""

_EPILOG = """
example:
  ai-assistant-restore ~/backups/assistant-2026-08-09.age ~/restored-assistant
"""


def main(argv: Sequence[str] | None = None) -> int:
    """Restore an artifact and return the process's exit code.

    Args:
        argv: Command-line arguments, for tests. ``None`` reads ``sys.argv``.

    Returns:
        ``0`` when a restored directory was published, ``78`` for every refusal
        ADR-0123 defines, and ``1`` for a fault a later attempt might survive.
    """
    args = _parse_args(argv)
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        return _report(exc)
    try:
        return _restore(args, live_data_dir=settings.data_dir)
    except RefusalError as exc:
        print(f"the restore was refused: {exc}", file=sys.stderr)
        return EXIT_DEPLOYMENT
    except KeyboardInterrupt:
        # The staging directory is removed by `_restore`'s own `finally`, and the
        # target was never touched: §7's retry is just running this again.
        print(
            "\ninterrupted. Nothing was restored — run this again when you like.", file=sys.stderr
        )
        return EXIT_RESTART
    except (AssistantError, OSError) as exc:
        return _report(exc)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Read the artifact, the target, and how the passphrase arrives.

    There is no ``--force`` and no way to name a subset: §1 rules that restore
    "restores every file the artifact carries. The tool offers no way to restore a
    subset of them, and no way to restore part of any one file", and §7 rules that
    it "replaces nothing" — so neither has a flag to turn off.
    """
    parser = argparse.ArgumentParser(
        prog="ai-assistant-restore",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("artifact", type=Path, help="the backup artifact to read")
    parser.add_argument("target", type=Path, help="the directory to create; it must not exist")
    parser.add_argument(
        "--passphrase-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="read the passphrase from this file's first line, for an unattended run",
    )
    return parser.parse_args(argv)


def _restore(args: argparse.Namespace, *, live_data_dir: Path) -> int:
    """Refuse what §7 refuses, then stage, check, and publish by one rename."""
    named = Path(args.target)
    parent = named.parent.resolve()
    target = parent / named.name

    _refuse_missing_artifact(Path(args.artifact))
    _refuse_existing_target(target)
    _refuse_live_data_dir(target, live_data_dir=live_data_dir)
    _refuse_shared_parent(parent)

    # Read after the refusals, so a mistyped target costs no prompt (§5's
    # `confirm=False`: a typo here is a refusal, not an unopenable artifact).
    secret = passphrase.resolve(source=args.passphrase_file, generated=False, confirm=False)

    staging = Path(tempfile.mkdtemp(dir=parent, prefix=f".{target.name}.restoring-"))
    try:
        manifest = artifact.materialise(Path(args.artifact), passphrase=secret, staging=staging)
        artifact.verify_materialised(staging, manifest)
        _publish(staging, target)
    except BaseException:
        # §7: remove the staging directory and everything in it, touch the target
        # path not at all, and remove nothing outside the staging directory.
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _announce(target, manifest)
    return EXIT_OK


def _publish(staging: Path, target: Path) -> None:
    """Rename the staging directory into place, as the last act (§7).

    Raises:
        RefusalError: If the target exists at that moment. Publication fails rather
            than replacing anything — a non-empty directory at the target makes
            the rename itself fail, and the check before it is what covers an
            empty one. §7 is explicit that this narrows the window rather than
            closing it, and that closing it needs a descriptor-relative shared
            mechanism rather than one tool's hardening (#889).
    """
    if target.exists() or target.is_symlink():
        msg = (
            f"{target} came into existence while the restore was running, so nothing was "
            f"published — publishing would have replaced whatever is there now"
        )
        raise RefusalError(msg)
    try:
        os.rename(staging, target)  # noqa: PTH104 - `Path.rename` is the same call
    except OSError as exc:
        msg = f"the restored directory could not be published to {target}: {exc}"
        raise RefusalError(msg) from exc


def _refuse_missing_artifact(path: Path) -> None:
    """A missing or unreadable artifact is a refusal, not a traceback."""
    if not path.is_file():
        msg = f"{path} is not a file this tool can read as a backup artifact"
        raise RefusalError(msg)


def _refuse_existing_target(target: Path) -> None:
    """§7's first clause: restore refuses a target path that already exists."""
    if target.exists() or target.is_symlink():
        msg = (
            f"{target} already exists; restore never writes into or over an existing path, "
            f"so name a directory that does not exist yet and move it into place yourself"
        )
        raise RefusalError(msg)


def _refuse_live_data_dir(target: Path, *, live_data_dir: Path) -> None:
    """§7's second clause, naming both paths.

    "A restored directory enters service by the operator moving it, never by a
    restore writing where a hub is expected to look."
    """
    if target == live_data_dir.resolve():
        msg = (
            f"{target} is the data directory this environment resolves "
            f"({live_data_dir}), which is where a hub is expected to look; restore into a "
            f"path that does not exist yet and move it into place once you have looked at it"
        )
        raise RefusalError(msg)


def _refuse_shared_parent(parent: Path) -> None:
    """§7's third clause: the plaintext store may not land under a shared parent.

    Named with its mode because that is what an operator needs to fix it. The
    reason is stated in §7 and is worth keeping beside the check: "this is where
    the **plaintext** store lands, and a directory whose parent strangers may
    write is not a place to unpack every belief the user has accumulated." §11's
    artifact destination is deliberately *not* held to this — an artifact is
    ciphertext — and that asymmetry is why the two paths have different rules.
    """
    try:
        info = parent.stat()
    except OSError as exc:
        msg = f"the target's parent {parent} cannot be examined: {exc}"
        raise RefusalError(msg) from exc
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        msg = (
            f"the target's parent {parent} is mode {stat.S_IMODE(info.st_mode):04o} and "
            f"writable by other users, who could rename it away while the store is being "
            f"unpacked into it; chmod it to 0700, or restore somewhere you own alone"
        )
        raise RefusalError(msg)


def _announce(target: Path, manifest: Manifest) -> None:
    """Say what landed, and what the operator still has to do."""
    print(f"restored {len(manifest.files)} file(s) into {target}")
    print(f"  taken:  {manifest.taken_at.isoformat()}")
    print(f"  by:     ai-assistant {manifest.project_version}")
    print(
        "\nThis is not yet a working installation. Provider credentials live in the OS "
        "keyring and are not in a backup, and the trace store is not either. Point a hub "
        "at this directory — by moving it into place — once you have looked at it."
    )


def _report(exc: BaseException) -> int:
    """Print a failure and return the code ADR-0083 §5's test gives it."""
    code, action = classify(exc)
    print(f"the restore did not run: {exc}", file=sys.stderr)
    if action:
        print(f"what to do: {action}", file=sys.stderr)
    return code
