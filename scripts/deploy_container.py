#!/usr/bin/env python3
"""Deploy one person's hub container to a box: build, back up, replace, verify (#3160).

    uv run python scripts/deploy_container.py PERSON HOST [--port N] [--image REF]
    uv run python scripts/deploy_container.py PERSON --local [--port N] [--image REF]

**One act, and it is a cutover** (ADR-0326 §2:6): the person's container is replaced by
one running a new image, on the same data and keyring volumes (§3:1), after a verified
backup of the data volume taken with the image that wrote it (§6:1). It is
``scripts/deploy_hub.py``'s procedure for a hub in a container instead of a venv, and it
is scriptable end to end: the person, the box and the paths are arguments, nothing is
prompted for, and the exit status is ``0`` only when the new container is up and
verified.

**The box.** It has Docker Engine 28 or later, systemd, ``curl`` and ``iptables``, and
ssh logs in as a user that may run them, ``root`` by default. Every box command is one
argv, quoted for the remote shell by :func:`shlex.join` and never assembled from text.
``--local`` makes this machine the box, its commands run as root through ``sudo -n``;
that is how the ``container`` workflow deploys to its own runner. Per person, under
``--hubs-dir`` (``/srv/hubs``):

* ``<person>/hub.env``: the container's environment, Docker's ``--env-file`` format,
  holding the model key. The operator writes it; mode ``0600``, read by the docker
  client as root.
* ``<person>/keyring-passphrase`` and ``<person>/backup-passphrase``: one passphrase
  each, owned by the container's user (uid 10001, the image's) and readable by it alone.
  **The operator creates both, by hand; nothing here creates, reads, prints or sends
  either.** The deploy examines their owner and mode, mounts them read-only into the
  container that needs each, and refuses before stopping anything when one is wrong.
* ``<person>/unit.env``: what the unit runs, ``HUB_IMAGE`` (an image id, so a moved tag
  cannot change it) and ``HUB_PORT``, and ``HUB_RELAY_MAPPING`` for a relayed hub
  (below). Written by this deploy alone, and only once the backup is verified, so until
  then the unit's next start is the earlier image.
* ``<person>/backups/``: each deploy's artifact, ``pre-deploy-<UTC>-<run>.age``, outside
  the data volume and never deleted (ADR-0326 §6:3). Pruning is the operator's act.
* The volumes ``hub-<person>-data`` and ``hub-<person>-keyring``, the container and
  bridge network ``hub-<person>``, and the unit ``hub@<person>.service``, from
  ``deploy/container/hub@.service``, which every deploy installs as it is in this tree.
  The unit is one template for every person, so ``--hubs-dir`` is one root per box, and
  a deploy naming another is refused.

**Where the image is built.** On the box, from a context staged here: ``build.sh
--context`` refuses a dirty tree, builds the wheel and exports ``uv.lock``'s runtime set
exactly as ``just container-image`` does, and the context goes to the box over the same
ssh and is built there, labelled with the commit (§3:2). Nothing is pushed to or pulled
from a registry but the pinned base images. An image already built for the commit is
used again, so a box serving several people builds each commit once. ``--image REF``
deploys an image already on the box, which must carry ``build.sh``'s commit label.

**The order, and what each failure leaves.**

1. Everything that can be refused is refused while the hub still serves: the files and
   their modes, the volumes, the earlier image, the port, the box's network (below),
   the new image built and labelled, its commit ruled on (below), the unit installed.
   *Nothing is stopped.*
2. On a person whose hub has served data, the unit is stopped, and the earlier image's
   own ``ai-assistant-backup`` copies the data volume to the artifact, in a container
   of its own with no network. A backup that fails, or is written but unverified,
   leaves ``unit.env`` as it was and the unit is started again: *the earlier image
   runs, and the new one never has* (§6:2).
3. ``unit.env`` names the new image and the unit starts it. From here the new image has
   run on the data, so whatever fails, the earlier one is never started on it again
   (ADR-0326 §5:4). Undoing the deploy is a later image or a restore of the backup.
4. The new container is verified: healthy, running the new image, the door answering
   ``403`` on the published loopback port, and the reachability check below. One that
   never becomes healthy is left to its unit only where that check passes; otherwise,
   and whenever the door or the check fails, it is stopped and disabled, so a boot does
   not start it either, and a stop that cannot be confirmed is said to be one.

**An earlier build is refused before the unit is touched** (ADR-0326 §5:4). Over a
person whose hub has served, the new image's commit must be the earlier image's revision
label or a later one, by this clone's history. An earlier commit is refused, and so is
one that has diverged from it, and so is any commit when the label names none this clone
holds: that is *unknown*, not *earlier*, and unknown is not clean. The refusal names the
way back, a later build or the backup restored into a new path and served by the
earlier build. ``--allow-earlier`` overrides it, and is the operator's word that no
schema change lies between the two releases; nothing here computes that.

**What the backup copies** is the hub's own directory by construction: the data volume
mounted at ``/data``, the directory the image pins, and ``supervise.py`` refuses an
environment that moves it. So the backup runs with the image's environment and not the
person's ``hub.env``, whose hosted settings the tool's settings would refuse with no
hosted address. Its exclusions are the tool's own, ADR-0123 §3's and ADR-0314 §7:5's,
each derived from the data directory alone; this script adds none and removes none
(ADR-0326 §6:4).

**Reachability, ADR-0327 §5:2.** No other machine may reach the hosted listener, by the
published loopback port or by the container's address on the bridge. What this deploy
establishes, and refuses or fails loudly without:

* the container is on the person's own bridge network, ``hub-<person>``, which the unit
  makes, and not the host's network, and it publishes
  exactly one port, ``8423/tcp``, to ``127.0.0.1`` alone, and has no IPv6 address;
* ``route_localnet`` is ``0`` for ``all`` and for every interface that is not the
  loopback or Docker's own (``docker0``, ``br-*``, ``veth*``), so the kernel drops a
  packet for ``127.0.0.0/8`` that arrives from another machine;
* the raw table's ``PREROUTING`` chain drops what arrives for the hosted listener at
  the container's address on any interface but its bridge, by the rule Docker Engine 28
  and later writes for a published port (``-d <address>/32 ! -i <bridge> -p tcp -m tcp
  --dport 8423 -j DROP``), and no rule before it can accept the packet first.

The check runs as soon as the container runs, before it is healthy, and again on every
start the deploy makes, the earlier image's after a failed backup among them; the
version floor is what it rests on before then. What it cannot see: a firewall that is
not iptables' (Docker's nftables backend is
refused, not read), the network beyond the box, and any process on the box that
forwards the port itself, which is the box's own act. Every process *on* the box can
reach the listener, as ADR-0327 §6 expects: the edge's signature stands between them.

**A relayed hub resolves the relay on the box** (ADR-0330 §8:2). A hub whose
``hub.env`` sets ``ASSISTANT_TELEGRAM_RELAY_ORIGIN`` reaches the relay by that origin's
host name, and its container is on a bridge of its own, where nothing else resolves it.
So the deploy reads that one setting from ``hub.env``, by ``grep``, and nothing else
in it, and the unit runs the container with ``--add-host <host>:<address>``. The
address is ``--relay-address``, the operator's word for where the relay listens on this
box, never looked up: a name resolved to find it would be the very lookup the mapping
replaces. A relayed hub deployed without it is refused before anything is stopped,
since it would start only to fail at its first poll. A hub that sets no origin is in
direct mode, and its run is as it was: ``--relay-address`` is not used for it.

**One deploy per person at a time, and one unit install per box.** Each is a ``flock``
on a box file, ``<person>/.deploy-lock`` for the whole deploy and
``/run/hub-deploy-unit.lock`` while the unit is installed, which every person's deploy
writes. The box commands are separate ssh sessions, so the lock is held by one more: a
``flock`` on the box whose holder reads its standard input, a pipe from this process
alone, to its end. The deploy releases it by closing the pipe; a deploy killed outright
closes it by dying, the holder ends, and the kernel releases the lock with its
descriptor. So no run ever finds a dead deploy's lock, and the files themselves mean
nothing: an earlier deploy's lock directory serves as the file.

The ssh link can drop under the holder alone. Its ssh then exits, and the deploy refuses
to change anything more: it looks before it installs the unit, before it stops the hub
for the backup, and before it names the new image. On the box, sshd ends the holder
when it sees the link gone, which may be the TCP keepalive's two hours, and until then
another deploy refuses and is told how to find the holder. A box command already running
when its own link drops runs to its end unwatched, as one always has; the next deploy's
checks are what meet it: a backup container still mounting the data volume is refused by
the check that the volume is still.

**A first install that ends early is resumed** (#3185). It records itself in
``<person>/.first-install`` before it makes the volumes and removes the record once
``unit.env`` is written and before the unit is enabled or started, each step synced to
the box's disk. While the record stands nothing can have run on the volumes, so the next
deploy finds the record, keeps the volumes, and installs again, writing ``unit.env``
over any the interrupted run wrote. Volumes with neither a record nor ``unit.env`` are
still refused: that may be a person's data with nothing to say which image wrote it
(ADR-0326 §6:1).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from ipaddress import IPv4Address, ip_address
from pathlib import Path, PurePosixPath
from typing import IO, TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

# From deploy_hub, one source for whichever deploy reads it: the backup tool's own words,
# held to its source by deploy_hub's tests, for what "written and verified" looks like;
# and ADR-0326 §5:4's ruling on the commit, whose git lookups can raise deploy_hub's own
# error, which main() reports as this script's.
from deploy_hub import (
    _BACKUP_DISCLOSES,
    _BACKUP_UNVERIFIED,
    _BACKUP_VERIFIED,
    ALLOW_EARLIER_HELP,
    HISTORY_WAY_BACK,
    history_refusal,
)
from deploy_hub import DeployError as HubDeployError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: The repository this script builds from, and the unit it installs.
REPO = Path(__file__).resolve().parents[1]
UNIT_SOURCE = REPO / "deploy" / "container" / "hub@.service"
BUILD_SCRIPT = REPO / "deploy" / "container" / "build.sh"

#: Defaults for the box.
DEFAULT_SSH_USER = "root"
DEFAULT_HUBS_DIR = "/srv/hubs"
#: The person-directory root the shipped unit names, replaced when ``--hubs-dir`` differs.
UNIT_HUBS_DIR = "/srv/hubs"
UNIT_PATH = "/etc/systemd/system/hub@.service"
#: The box's lock on installing the unit, which every person's deploy shares.
UNIT_LOCK = "/run/hub-deploy-unit.lock"
#: How long a deploy waits for another to finish installing the unit.
_UNIT_LOCK_SECONDS = 60
#: What a lock's holder prints once it holds the lock, and the exit status of one that
#: could not have it: ``flock --conflict-exit-code``'s, sysexits' ``EX_TEMPFAIL``.
HELD = b"held\n"
_BUSY = 75
#: How long a released holder has to end before it is killed.
_RELEASE_SECONDS = 30
DOCKER = "/usr/bin/docker"
#: Where a staged build context is unpacked on the box, root's alone.
BOX_STAGE_PARENT = "/var/tmp"  # noqa: S108  # root-owned staging, made 0700 per run
#: The image's user, which every mounted passphrase must belong to (the Dockerfile's).
CONTAINER_UID = 10001
#: What ``build.sh`` names and labels an image with.
IMAGE_REPOSITORY = "ai-assistant-hub"
REVISION_LABEL = "org.opencontainers.image.revision"
SOURCE_LABEL = "org.opencontainers.image.source"
SOURCE_URL = "https://github.com/leonapivato/ai-assistant"
#: The hosted listener's port inside the container (the Dockerfile's ``EXPOSE``).
HOSTED_PORT = 8423
#: How long the new container has to become healthy: the image's health check allows a
#: ten-minute start period.
DEFAULT_READY_TIMEOUT = 600
_POLL_SECONDS = 2.0
#: A person's name names a unit instance, two volumes, a container and a directory.
_PERSON = re.compile(r"[a-z][a-z0-9-]{0,30}[a-z0-9]|[a-z]")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
#: The first Docker Engine that writes the raw-table drop for a published port.
_DOCKER_MAJOR = 28
_PLAIN_PATH = re.compile(r"/[A-Za-z0-9._/-]*")
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]*")
#: Interfaces Docker makes for its bridges, whose ``route_localnet`` is Docker's own.
_DOCKER_INTERFACE = re.compile(r"docker0|br-[0-9a-f]+|veth[0-9a-f]+")
#: Raw-table targets that never accept a packet, and so cannot let one past a drop.
_NON_ACCEPTING_TARGETS = frozenset({"DROP", "CT", "NOTRACK", "LOG", "MARK", "TRACE", "NFLOG"})
#: The options that send a packet to a target or a chain: a rule has one, or is refused.
_JUMPS = frozenset({"-j", "--jump", "-g", "--goto"})
#: The setting that sizes ADR-0083's D2, which the unit's stop timeout is fixed against.
_DRAIN_SETTING = "ASSISTANT_SHUTDOWN_DRAIN_SECONDS"
#: The setting that puts the hub's Telegram line in relayed mode (ADR-0330 §3), whose
#: host the container must resolve to the relay on the box (§8:2).
_RELAY_SETTING = "ASSISTANT_TELEGRAM_RELAY_ORIGIN"
#: A DNS host name, as the origin's host must be to be mapped: dot-separated labels.
_HOST_NAME = re.compile(
    r"(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*"
)
#: The template ``docker inspect`` fills for a container: the fields this deploy reads
#: and nothing else, so the environment (the model key) never crosses the link.
_CONTAINER_FIELDS = (
    '{"status":{{json .State.Status}},'
    '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},'
    '"image":{{json .Image}},'
    '"mode":{{json .HostConfig.NetworkMode}},'
    '"ports":{{json .NetworkSettings.Ports}},'
    '"networks":{{json .NetworkSettings.Networks}}}'
)
_UNTOUCHED = "Nothing has been stopped or changed."
#: How much of a failed command's output a message carries.
_SHOWN_LINES = 40


class DeployError(Exception):
    """The deploy could not proceed, or could not be verified."""


# --------------------------------------------------------------------------- #
# The box                                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Result:
    """One box command's exit status and output."""

    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        """Whether it exited ``0``."""
        return self.code == 0

    def said(self) -> str:
        """What it printed, standard error first, for an operator's message.

        Returns:
            The text, or a placeholder when it printed nothing.
        """
        return self.err.strip() or self.out.strip() or "(no output)"


class Lease(Protocol):
    """A lock on the box, held by a box process that lives as long as this deploy."""

    def held(self) -> bool:
        """Whether the process holding it is still running.

        Returns:
            ``False`` once it has ended, the lock with it.
        """
        ...

    def release(self) -> None:
        """End the holding process, and the lock with it. Never raises."""
        ...


class Box(Protocol):
    """Where the person's container runs."""

    def run(self, argv: Sequence[str], *, stdin: IO[bytes] | None = None) -> Result:
        """Run one command there.

        Args:
            argv: The command, one argument per element.
            stdin: What to feed it, or nothing.

        Returns:
            Its exit status and output.
        """
        ...

    def hold(self, argv: Sequence[str]) -> Lease | Result:
        """Start a command that holds a lock until its standard input ends.

        Args:
            argv: The command: one that prints :data:`HELD` once it holds the lock,
                then reads its standard input to its end.

        Returns:
            The lease while it holds the lock, or its exit status and output once it
            has ended without printing :data:`HELD`.
        """
        ...


def _execute(argv: Sequence[str], stdin: IO[bytes] | None) -> Result:
    """Run a local process to its end and decode what it printed.

    Args:
        argv: The process.
        stdin: Its standard input, or ``None`` for none.

    Returns:
        Its exit status and output.

    Raises:
        DeployError: If the executable cannot be started.
    """
    try:
        completed = subprocess.run(  # noqa: S603  # an argv, never a shell line
            list(argv),
            stdin=stdin if stdin is not None else subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise DeployError(f"could not run {argv[0]}: {exc.strerror or exc}") from exc
    return Result(
        completed.returncode,
        completed.stdout.decode("utf-8", "replace"),
        completed.stderr.decode("utf-8", "replace"),
    )


@dataclass(frozen=True, slots=True)
class ProcessLease:
    """A lock held by a local process: ``ssh`` or ``sudo`` running the box's holder.

    Its standard input is a pipe from this process alone, so it ends when this deploy
    does, however it ends: a kill closes the pipe, the holder on the box reads its end
    and exits, and the kernel releases the lock with its descriptor.
    """

    process: subprocess.Popen[bytes]

    def held(self) -> bool:
        """Whether the holder still runs.

        Returns:
            ``False`` once it has exited, as it does when its link to the box drops.
        """
        return self.process.poll() is None

    def release(self) -> None:
        """Close the holder's standard input and wait for it to end."""
        try:
            self.process.communicate(timeout=_RELEASE_SECONDS)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate()


def _hold(argv: Sequence[str]) -> ProcessLease | Result:
    """Start a local process that holds a lock, and wait until it holds it or has ended.

    Args:
        argv: The process.

    Returns:
        Its lease once it prints :data:`HELD`, else its exit status and output.

    Raises:
        DeployError: If the executable cannot be started.
    """
    try:
        process = subprocess.Popen(  # noqa: S603  # an argv, never a shell line
            list(argv), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except OSError as exc:
        raise DeployError(f"could not run {argv[0]}: {exc.strerror or exc}") from exc
    assert process.stdout is not None  # noqa: S101  # a pipe, asked for above
    said = b""
    while line := process.stdout.readline():
        if line == HELD:
            return ProcessLease(process)
        said += line
    out, err = process.communicate()
    return Result(
        process.returncode,
        (said + out).decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
    )


@dataclass(frozen=True, slots=True)
class SshBox:
    """A box reached over ssh, with no prompt: a key, or nothing."""

    host: str
    user: str = DEFAULT_SSH_USER

    def argv(self, argv: Sequence[str]) -> list[str]:
        """The local argv that runs ``argv`` on the box.

        Args:
            argv: The box command.

        Returns:
            The ssh invocation, carrying the command as one quoted line.
        """
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=30",
            "-o",
            "ServerAliveInterval=30",
            "--",
            f"{self.user}@{self.host}",
            shlex.join(argv),
        ]

    def run(self, argv: Sequence[str], *, stdin: IO[bytes] | None = None) -> Result:
        """Run one command on the box.

        Args:
            argv: The command.
            stdin: What to feed it.

        Returns:
            Its exit status and output. ssh's own failure is ``255``.
        """
        return _execute(self.argv(argv), stdin)

    def hold(self, argv: Sequence[str]) -> ProcessLease | Result:
        """Hold a lock on the box for as long as this deploy's ssh session to it lasts.

        Args:
            argv: The holder.

        Returns:
            Its lease, or how it ended. ssh's own failure is ``255``.
        """
        return _hold(self.argv(argv))


@dataclass(frozen=True, slots=True)
class LocalBox:
    """This machine as the box, its commands run as root, as ssh runs them on one."""

    root: bool = field(default_factory=lambda: os.geteuid() == 0)

    def argv(self, argv: Sequence[str]) -> list[str]:
        """The local argv that runs ``argv`` as root.

        Args:
            argv: The box command.

        Returns:
            ``argv`` itself when this process is root, else under ``sudo -n``.
        """
        return list(argv) if self.root else ["sudo", "-n", "--", *argv]

    def run(self, argv: Sequence[str], *, stdin: IO[bytes] | None = None) -> Result:
        """Run one command here, as root.

        Args:
            argv: The command.
            stdin: What to feed it.

        Returns:
            Its exit status and output.
        """
        return _execute(self.argv(argv), stdin)

    def hold(self, argv: Sequence[str]) -> ProcessLease | Result:
        """Hold a lock here, as root, for as long as this deploy runs.

        Args:
            argv: The holder.

        Returns:
            Its lease, or how it ended.
        """
        return _hold(self.argv(argv))


# --------------------------------------------------------------------------- #
# What the deploy reads and writes                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Person:
    """Everything on the box that is one person's, named from their name."""

    name: str
    hubs_dir: PurePosixPath

    @property
    def dir(self) -> PurePosixPath:
        """The person's directory."""
        return self.hubs_dir / self.name

    @property
    def env_file(self) -> PurePosixPath:
        """The container's environment, the model key's file."""
        return self.dir / "hub.env"

    @property
    def keyring_passphrase(self) -> PurePosixPath:
        """The keyring's passphrase, mounted into the hub's container."""
        return self.dir / "keyring-passphrase"

    @property
    def backup_passphrase(self) -> PurePosixPath:
        """The backup's passphrase, mounted into the backup's container."""
        return self.dir / "backup-passphrase"

    @property
    def unit_env(self) -> PurePosixPath:
        """What the unit runs."""
        return self.dir / "unit.env"

    @property
    def backups(self) -> PurePosixPath:
        """Where each deploy's artifact is kept."""
        return self.dir / "backups"

    @property
    def lock(self) -> PurePosixPath:
        """The file a deploy in progress holds a ``flock`` on; its existence means nothing."""
        return self.dir / ".deploy-lock"

    @property
    def first_install(self) -> PurePosixPath:
        """Present while a first install's volumes have had no hub run on them."""
        return self.dir / ".first-install"

    @property
    def container(self) -> str:
        """The hub's container."""
        return f"hub-{self.name}"

    @property
    def unit(self) -> str:
        """The unit that runs it."""
        return f"hub@{self.name}.service"

    @property
    def network(self) -> str:
        """The person's own bridge network, which the unit creates."""
        return f"hub-{self.name}"

    @property
    def data_volume(self) -> str:
        """The data directory's volume."""
        return f"hub-{self.name}-data"

    @property
    def keyring_volume(self) -> str:
        """The keyring's volume."""
        return f"hub-{self.name}-keyring"


def relay_host(lines: str) -> str | None:
    """The host a relayed hub's container must resolve, from ``hub.env``'s origin line.

    Args:
        lines: The lines of ``hub.env`` that set ``ASSISTANT_TELEGRAM_RELAY_ORIGIN``.

    Returns:
        The origin's host name, or ``None`` when no line sets it: a direct-mode hub.

    Raises:
        DeployError: If more than one line sets it, or its host is not a host name.
    """
    values = [line.partition("=")[2].strip() for line in lines.splitlines() if line.strip()]
    if not values:
        return None
    if len(values) > 1:
        raise DeployError(
            f"hub.env sets {_RELAY_SETTING} {len(values)} times. Keep one.\n{_UNTOUCHED}"
        )
    try:
        host = urlsplit(values[0]).hostname
    except ValueError:
        host = None
    if host is None or _HOST_NAME.fullmatch(host) is None or _is_address(host):
        raise DeployError(
            f"hub.env sets {_RELAY_SETTING}={values[0]}, which names no host name for the\n"
            "container to resolve to the relay. Write https://telegram-relay:8443: a host\n"
            f"name, never an address, and a port (docs/guide/telegram-relay.md).\n{_UNTOUCHED}"
        )
    return host


def _is_address(host: str) -> bool:
    try:
        ip_address(host)
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class Installed:
    """What ``unit.env`` says the unit runs."""

    image: str
    port: int


@dataclass(frozen=True, slots=True)
class Image:
    """An image on the box: its id, the commit it is labelled with, and a name for it."""

    id: str
    commit: str
    name: str


@dataclass(frozen=True, slots=True)
class FileState:
    """What ``stat`` reports of one path on the box."""

    uid: int
    mode: int
    size: int
    kind: str


def parse_unit_env(text: str) -> Installed:
    """Read ``unit.env``.

    Args:
        text: Its content.

    Returns:
        The image and port it names.

    Raises:
        DeployError: If either is missing or malformed.
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        if sep:
            values[key] = value
    image = values.get("HUB_IMAGE", "")
    port = values.get("HUB_PORT", "")
    if _IMAGE_ID.fullmatch(image) is None or not port.isdigit():
        raise DeployError(
            "unit.env does not name an image id and a port (HUB_IMAGE=sha256:…, HUB_PORT=…);\n"
            f"it is written by this deploy alone, so restore it or remove it.\n{_UNTOUCHED}"
        )
    return Installed(image=image, port=int(port))


def render_unit_env(image: Image, port: int, stamp: str, relay: str | None = None) -> str:
    """Write ``unit.env``.

    Args:
        image: The image the unit is to run.
        port: The person's loopback port.
        stamp: When, for the reader.
        relay: ``<host>:<address>`` for a relayed hub, or ``None`` for a direct one,
            whose mapping is set empty: the unit then runs it with no argument for it,
            and systemd has no unset variable to warn of.

    Returns:
        The file's content.
    """
    mapping = "" if relay is None else f"--add-host={relay}"
    return (
        f"# Written by scripts/deploy_container.py at {stamp}: {image.name},\n"
        f"# commit {image.commit}. Read by hub@.service; edited by nothing else.\n"
        f"HUB_IMAGE={image.id}\n"
        f"HUB_PORT={port}\n"
        f"HUB_RELAY_MAPPING={mapping}\n"
    )


def render_unit(template: str, hubs_dir: PurePosixPath) -> str:
    """The unit as installed: the shipped file, with the person-directory root in it.

    Args:
        template: ``deploy/container/hub@.service``.
        hubs_dir: Where the person directories are on this box.

    Returns:
        The unit's text.
    """
    return template.replace(f"{UNIT_HUBS_DIR}/%i/", f"{hubs_dir}/%i/")


def parse_stat(out: str) -> FileState:
    """Read ``stat --format='%u %a %s %F'``.

    Args:
        out: Its output.

    Returns:
        The owner, mode, size and kind.

    Raises:
        DeployError: If it is not that shape.
    """
    parts = out.strip().split(" ", 3)
    if len(parts) != 4 or not parts[0].isdigit() or not parts[2].isdigit():  # noqa: PLR2004
        raise DeployError(f"stat printed {out.strip()!r}, not owner, mode, size and kind")
    try:
        mode = int(parts[1], 8)
    except ValueError as exc:
        raise DeployError(f"stat printed the mode {parts[1]!r}") from exc
    return FileState(uid=int(parts[0]), mode=mode, size=int(parts[2]), kind=parts[3])


def backup_outcome(result: Result, artifact: PurePosixPath) -> None:
    """Hold the backup to ADR-0326 §6:1: written, verified, and of ``/data``.

    Args:
        result: The backup container's exit status and output.
        artifact: Where it was told to write, on the box.

    Raises:
        DeployError: If the tool failed, did not say it verified the artifact, said it
            could not, or did not say it copied ``/data``.
    """
    said = f"{result.out}\n{result.err}"
    shown = said.strip() or "(no output)"
    if not result.ok:
        raise DeployError(f"ai-assistant-backup failed (exit {result.code}):\n{shown}")
    if _BACKUP_UNVERIFIED in said or _BACKUP_VERIFIED not in said:
        raise DeployError(
            f"the backup was written to {artifact} but is not verified, and an\n"
            f"unverified backup does not admit an install (ADR-0326 §6:2):\n{shown}"
        )
    if f"{_BACKUP_DISCLOSES}/data" not in said.splitlines():
        raise DeployError(f"the backup did not say it copied /data, the data volume:\n{shown}")


def route_localnet_problems(out: str) -> list[str]:
    """Rule on ``grep -H . /proc/sys/net/ipv4/conf/*/route_localnet``.

    Args:
        out: Its output, one ``<path>:<value>`` per interface.

    Returns:
        A sentence per interface that would route ``127.0.0.0/8`` from another machine.
    """
    problems: list[str] = []
    seen = False
    for line in out.splitlines():
        path, _, value = line.rpartition(":")
        parts = path.split("/")
        if len(parts) < 3:  # noqa: PLR2004
            continue
        interface = parts[-2]
        seen = True
        if interface == "lo" or _DOCKER_INTERFACE.fullmatch(interface):
            continue
        if value.strip() != "0":
            problems.append(
                f"route_localnet is {value.strip()} for {interface}, so a packet for the\n"
                "loopback port that arrives from another machine is routed, not dropped"
            )
    if not seen:
        problems.append("route_localnet could not be read for any interface")
    return problems


def accepting_rule(rules: str) -> str | None:
    """Find a rule in the raw table's ``PREROUTING`` chain that may accept a packet.

    Docker appends its drops to the chain, so a rule that may accept and is already there
    comes before every drop Docker writes, and lets past it what the drop would stop. Any
    such rule is refused, wherever it stands: none is needed on a box that runs hubs.

    Args:
        rules: ``iptables -t raw -S PREROUTING``.

    Returns:
        The first line that is not a policy, a chain's name or a rule with one jump to a
        target that never accepts, or ``None``. A line that cannot be read is returned.
    """
    for line in rules.splitlines():
        words = _rule_words(line)
        if words is not None and (not words or words[0] in {"-P", "-N"}):
            continue
        if words is None or words[0] != "-A" or _target(words) not in _NON_ACCEPTING_TARGETS:
            return line.strip()
    return None


def _rule_words(line: str) -> list[str] | None:
    """Split a line of ``iptables -S`` as iptables quotes it, or ``None`` if it cannot be."""
    try:
        return shlex.split(line)
    except ValueError:
        return None


def _target(words: list[str]) -> str | None:
    """A rule's one ``-j`` target, or ``None`` if it has none, several, or a ``-g``."""
    jumps = [at for at, word in enumerate(words) if word in _JUMPS]
    if len(jumps) != 1 or words[jumps[0]] not in {"-j", "--jump"} or jumps[0] + 1 == len(words):
        return None
    return words[jumps[0] + 1]


def raw_rule_problem(rules: str, address: str, bridge: str) -> str | None:
    """Find the drop that keeps other machines off the hosted listener's bridge address.

    Docker Engine 28.0 and 28.1 write it per published port, as
    ``-d <address>/32 ! -i <bridge> -p tcp -m tcp --dport 8423 -j DROP``; 28.2 and later
    drop the whole address, as ``-d <address>/32 ! -i <bridge> -j DROP``. Either is
    accepted. The hosted listener is the one thing listening on the container's address,
    so a drop of its port is a drop of the door.

    Args:
        rules: ``iptables -t raw -S PREROUTING``.
        address: The container's IPv4 address on its bridge.
        bridge: The bridge's interface.

    Returns:
        ``None`` when the chain drops what arrives for the listener on any other
        interface and nothing in it may accept, or why it cannot be shown to.
    """
    accepting = accepting_rule(rules)
    if accepting is not None:
        return (
            f"the raw table's PREROUTING chain has {accepting!r}, which may accept a packet\n"
            "for the container from elsewhere before Docker's drop"
        )
    whole = ["-A", "PREROUTING", "-d", f"{address}/32", "!", "-i", bridge]
    port = [*whole, "-p", "tcp", "-m", "tcp", "--dport", str(HOSTED_PORT)]
    wanted = ([*whole, "-j", "DROP"], [*port, "-j", "DROP"])
    if any(_rule_words(line) in wanted for line in rules.splitlines()):
        return None
    return (
        f"the raw table's PREROUTING chain has no `{' '.join(whole[2:])} -j DROP`.\n"
        "Docker Engine 28 and later write it for each container, on the iptables\n"
        "firewall backend; without it another machine may route to the container"
    )


def container_problems(fields: dict[str, object], port: int, network: str) -> list[str]:
    """Rule on the network half of :data:`_CONTAINER_FIELDS`.

    Args:
        fields: The decoded inspect fields.
        port: The person's loopback port.
        network: The person's own bridge network.

    Returns:
        A sentence per way the container is reachable other than as published.
    """
    problems: list[str] = []
    if fields.get("mode") != network:
        problems.append(f"the container's network is {fields.get('mode')!r}, not {network!r}")
    expected = {f"{HOSTED_PORT}/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]}
    ports = fields.get("ports")
    published = (
        {key: value for key, value in ports.items() if value} if isinstance(ports, dict) else ports
    )
    if published != expected:
        problems.append(
            f"the container publishes {json.dumps(published)}, not {HOSTED_PORT}/tcp to "
            f"127.0.0.1:{port} alone"
        )
    networks = fields.get("networks")
    if not isinstance(networks, dict) or list(networks) != [network]:
        names = list(networks) if isinstance(networks, dict) else networks
        problems.append(f"the container is on the networks {names}, not on {network!r} alone")
        return problems
    attached = networks[network]
    if isinstance(attached, dict) and attached.get("GlobalIPv6Address"):
        problems.append(
            "the container has an IPv6 address on the bridge, which this deploy does not check"
        )
    return problems


def container_address(fields: dict[str, object], network: str) -> str:
    """The container's IPv4 address on the person's network.

    Args:
        fields: The decoded inspect fields.
        network: The person's own bridge network.

    Returns:
        The address, or ``""`` when it has none.
    """
    networks = fields.get("networks")
    attached = networks.get(network) if isinstance(networks, dict) else None
    address = attached.get("IPAddress") if isinstance(attached, dict) else None
    return address if isinstance(address, str) else ""


# --------------------------------------------------------------------------- #
# The deploy                                                                   #
# --------------------------------------------------------------------------- #


def say(message: str) -> None:
    """One progress line for the operator, on standard error.

    Args:
        message: The line.
    """
    print(f"deploy-container: {message}", file=sys.stderr, flush=True)


@dataclass
class Deployment:
    """One run against one person on one box."""

    box: Box
    person: Person
    port: int | None = None
    image_ref: str | None = None
    ready_timeout: float = DEFAULT_READY_TIMEOUT
    repo: Path = REPO
    token: str = field(default_factory=lambda: secrets.token_hex(4))
    stamp: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    stage_context: Callable[[Path, Path], str] | None = None
    allow_earlier: bool = False
    history: Callable[[Path, str, str], str | None] = history_refusal
    relay_address: str | None = None
    #: ``<host>:<address>`` once the preflight finds the hub relayed, else ``None``.
    relay: str | None = None

    # -- small helpers --------------------------------------------------------

    def _ok(self, argv: Sequence[str], what: str, *, stdin: IO[bytes] | None = None) -> str:
        result = self.box.run(argv, stdin=stdin)
        if not result.ok:
            # The tail: a failed build prints thousands of lines, and its cause is last.
            shown = "\n".join(result.said().splitlines()[-_SHOWN_LINES:])
            raise DeployError(f"{what} failed (exit {result.code}):\n{shown}")
        return result.out

    def _stat(self, path: PurePosixPath) -> FileState | None:
        result = self.box.run(["stat", "--format=%u %a %s %F", "--", str(path)])
        if result.ok:
            return parse_stat(result.out)
        if "No such file or directory" in result.err:
            return None
        raise DeployError(f"could not examine {path} on the box:\n{result.said()}\n{_UNTOUCHED}")

    def _read(self, path: PurePosixPath) -> str | None:
        if self._stat(path) is None:
            return None
        return self._ok(["cat", "--", str(path)], f"reading {path}")

    def _write(self, path: PurePosixPath, text: str, *, mode: str = "0644") -> None:
        """Replace a box file whole, so a reader sees the old text or the new."""
        partial = f"{path}.{self.token}.partial"
        with tempfile.TemporaryFile() as handle:
            handle.write(text.encode("utf-8"))
            handle.seek(0)
            self._ok(
                ["install", "-m", mode, "-o", "0", "-g", "0", "/dev/stdin", partial],
                f"writing {path}",
                stdin=handle,
            )
        self._ok(["mv", "-f", "--", partial, str(path)], f"writing {path}")

    def _volume_exists(self, name: str) -> bool:
        return self.box.run([DOCKER, "volume", "inspect", "--format", "{{.Name}}", name]).ok

    def _image(self, ref: str) -> Image | None:
        result = self.box.run(
            [
                DOCKER,
                "image",
                "inspect",
                "--format",
                f'{{{{.Id}}}} {{{{index .Config.Labels "{REVISION_LABEL}"}}}}',
                ref,
            ]
        )
        if not result.ok:
            return None
        image_id, _, commit = result.out.strip().partition(" ")
        return Image(id=image_id, commit=commit, name=ref)

    def _unit_state(self) -> dict[str, str]:
        out = self._ok(
            [
                "systemctl",
                "show",
                self.person.unit,
                "--property=ActiveState,SubState,ExecMainStatus,NRestarts",
            ],
            f"reading {self.person.unit}'s state",
        )
        state: dict[str, str] = {}
        for line in out.splitlines():
            key, sep, value = line.partition("=")
            if sep:
                state[key] = value
        return state

    def _container(self) -> dict[str, object] | None:
        result = self.box.run(
            [DOCKER, "container", "inspect", "--format", _CONTAINER_FIELDS, self.person.container]
        )
        if not result.ok:
            return None
        try:
            fields = json.loads(result.out)
        except json.JSONDecodeError as exc:
            raise DeployError(f"docker inspect printed {result.out.strip()!r}") from exc
        if not isinstance(fields, dict):
            raise DeployError(f"docker inspect printed {result.out.strip()!r}")
        return fields

    def _journal(self) -> str:
        result = self.box.run(
            [
                "journalctl",
                "--unit",
                self.person.unit,
                "--lines",
                "400",
                "--no-pager",
                "--output",
                "cat",
            ]
        )
        # The supervisor's lines and the hub's refusals name the cause and the action
        # (ADR-0083 §5); the rest of the journal is the operator's to read in place.
        lines = [
            line for line in result.out.splitlines() if line.startswith(("hub-container:", "hub: "))
        ]
        shown = "\n".join(f"    {line}" for line in lines[-15:]) or "    (none)"
        return f"its last lines, from `journalctl --unit {self.person.unit}`:\n{shown}"

    # -- 1. everything that can be refused while the hub still serves ---------

    def preflight(self) -> Installed | None:
        """Refuse whatever would stop the deploy, before anything is stopped.

        Returns:
            What the unit runs now, or ``None`` on a first install.

        Raises:
            DeployError: If anything here means the deploy cannot be completed.
        """
        person = self.person
        version = self._ok(
            [DOCKER, "version", "--format", "{{.Server.Version}}"], "asking Docker its version"
        ).strip()
        say(f"the box runs Docker {version}")
        major = version.split(".", 1)[0]
        if not major.isdigit() or int(major) < _DOCKER_MAJOR:
            raise DeployError(
                f"the box runs Docker {version or '(no version)'}. Docker Engine "
                f"{_DOCKER_MAJOR} is the first to drop,\nbefore a container starts, what "
                "other machines send to its published ports at its bridge\naddress, which "
                f"ADR-0327 §5:2 rests on here. Upgrade it.\n{_UNTOUCHED}"
            )
        for tool in (["systemctl", "--version"], ["curl", "--version"], ["iptables", "--version"]):
            self._ok(tool, f"{tool[0]} on the box")
        self._check_env_file()
        self.relay = self._rule_on_relay()
        self._check_passphrase(person.keyring_passphrase, "keyring")
        installed = self._installed()
        served = self._volume_exists(person.data_volume)
        if installed is None and served and self._stat(person.first_install) is None:
            raise DeployError(
                f"the volume {person.data_volume} exists but {person.unit_env} does not, so a\n"
                "hub has served data here and nothing says which image wrote it: no backup can\n"
                "be taken with that image before installing (ADR-0326 §6:1). Back the volume\n"
                "up by hand, write unit.env naming that image, and deploy again. Only if you\n"
                "know no hub ever ran on it (a first install interrupted by a deploy older\n"
                f"than {person.first_install}), remove {person.data_volume} and\n"
                f"{person.keyring_volume} instead, and deploy again.\n{_UNTOUCHED}"
            )
        if installed is not None and not served:
            raise DeployError(
                f"{person.unit_env} names an image but the volume {person.data_volume} is\n"
                "missing: the person's data is not where the unit mounts it. Find it before\n"
                f"deploying; this deploy never starts a hub on a new volume over one.\n{_UNTOUCHED}"
            )
        if installed is not None and not self._volume_exists(person.keyring_volume):
            raise DeployError(
                f"{person.unit_env} names an image but the volume {person.keyring_volume} is\n"
                "missing: the unit would start on a new, empty keyring, and every credential\n"
                f"the person's connections stored would be gone. Find it first.\n{_UNTOUCHED}"
            )
        if installed is not None:
            if self._image(installed.image) is None:
                raise DeployError(
                    f"the image the unit runs, {installed.image}, is not on the box, so the\n"
                    "backup cannot be taken with the image that wrote the data. Load it\n"
                    f"again, and never prune the image a person runs.\n{_UNTOUCHED}"
                )
            self._check_passphrase(person.backup_passphrase, "backup")
        self.port = self._rule_on_port(installed)
        self._check_unit_root()
        self._check_box_network()
        return installed

    def _installed(self) -> Installed | None:
        """What the unit runs, or ``None`` when no hub has run on the person's volumes.

        A first install records itself before it makes the volumes and removes the
        record before anything starts on them, so while the record stands the volumes
        hold nothing a hub wrote, whatever ``unit.env`` says: the install is resumed.

        Returns:
            What ``unit.env`` names, or ``None`` for a first install, new or resumed.
        """
        if self._stat(self.person.first_install) is not None:
            say(f"{self.person.first_install}: a first install that ran nothing; resuming it")
            return None
        text = self._read(self.person.unit_env)
        return None if text is None else parse_unit_env(text)

    def _check_unit_root(self) -> None:
        """Refuse a person-directory root other than the one the box's unit reads.

        The unit is one template for every person on the box, so moving its root for
        one person would move it for all of them.
        """
        installed = self._read(PurePosixPath(UNIT_PATH))
        if installed is None:
            return
        wanted = f"EnvironmentFile={self.person.hubs_dir}/%i/unit.env"
        if wanted not in installed.splitlines():
            named = [line for line in installed.splitlines() if line.startswith("EnvironmentFile=")]
            raise DeployError(
                f"{UNIT_PATH} reads {', '.join(named) or 'no EnvironmentFile'}, not\n"
                f"{wanted}. The unit serves every person on this box, so the person\n"
                f"directories have one root per box: pass that --hubs-dir.\n{_UNTOUCHED}"
            )

    def _check_person_dir(self) -> None:
        path = self.person.dir
        state = self._stat(path)
        if state is None or state.kind != "directory":
            raise DeployError(
                f"{path} is not a directory on the box. The operator makes it, with\n"
                f"hub.env, keyring-passphrase and backup-passphrase in it\n"
                f"(docs/guide/container.md).\n{_UNTOUCHED}"
            )
        # Root reads hub.env and unit.env from here to run the container, so whoever
        # could write here could choose what root runs.
        if state.uid != 0 or state.mode & 0o022:
            raise DeployError(
                f"{path} is owned by uid {state.uid} with mode {state.mode:o}; it must be\n"
                f"root's, and writable by root alone (chown root: and chmod 700).\n{_UNTOUCHED}"
            )

    def _check_env_file(self) -> None:
        path = self.person.env_file
        state = self._stat(path)
        if state is None or state.kind != "regular file" or state.size == 0:
            raise DeployError(
                f"{path} is missing or empty. It is the container's environment, the model\n"
                f"key's file, and the operator writes it (docs/guide/container.md).\n{_UNTOUCHED}"
            )
        if state.uid != 0 or state.mode & 0o077:
            raise DeployError(
                f"{path} is owned by uid {state.uid} with mode {state.mode:o}; it holds the\n"
                f"model key, so it is root's alone (chown root: and chmod 600).\n{_UNTOUCHED}"
            )
        counted = self.box.run(
            [
                "grep",
                "--count",
                "--ignore-case",
                "--extended-regexp",
                f"^[[:space:]]*{_DRAIN_SETTING}=",
                "--",
                str(path),
            ]
        )
        if counted.code not in {0, 1}:
            raise DeployError(f"could not read {path}:\n{counted.said()}\n{_UNTOUCHED}")
        if counted.out.strip() != "0":
            raise DeployError(
                f"{path} sets {_DRAIN_SETTING}. The unit's stop timeout is sized for the\n"
                "default drain (ADR-0083 §3's D2, sixty seconds, under Docker's ninety), and\n"
                f"this deploy does not read another. Remove it, or change the unit.\n{_UNTOUCHED}"
            )

    def _rule_on_relay(self) -> str | None:
        """Find whether the hub is relayed, and so what its container must resolve.

        Returns:
            ``<host>:<address>`` for a relayed hub, ``None`` for a direct one.

        Raises:
            DeployError: If ``hub.env`` cannot be read, its origin names no host, or
                the hub is relayed and ``--relay-address`` was not given.
        """
        path = self.person.env_file
        found = self.box.run(
            [
                "grep",
                "--ignore-case",
                "--extended-regexp",
                f"^[[:space:]]*{_RELAY_SETTING}=",
                "--",
                str(path),
            ]
        )
        if found.code not in {0, 1}:
            raise DeployError(f"could not read {path}:\n{found.said()}\n{_UNTOUCHED}")
        host = relay_host(found.out)
        if host is None:
            return None
        if self.relay_address is None:
            raise DeployError(
                f"{path} sets {_RELAY_SETTING}, so the hub's Telegram line is relayed and\n"
                f"its container must resolve {host} to the relay on this box (ADR-0330\n"
                "§8:2). Pass --relay-address, the address the relay listens on here; this\n"
                f"deploy never looks it up.\n{_UNTOUCHED}"
            )
        say(f"the line is relayed: {host} resolves to {self.relay_address} in the container")
        return f"{host}:{self.relay_address}"

    def _check_passphrase(self, path: PurePosixPath, which: str) -> None:
        state = self._stat(path)
        if state is None or state.kind != "regular file" or state.size == 0:
            raise DeployError(
                f"the {which} passphrase file {path} is missing or empty on the box. The\n"
                "operator creates it, once, by hand; this deploy never does:\n\n"
                f"  install -m 0400 -o {CONTAINER_UID} -g {CONTAINER_UID} /dev/stdin {path}\n\n"
                "then type the passphrase, Enter and Ctrl-D, and keep a copy off the box\n"
                f"(ADR-0123 §5).\n{_UNTOUCHED}"
            )
        if state.uid != CONTAINER_UID or state.mode & 0o077 or not state.mode & 0o400:
            raise DeployError(
                f"the {which} passphrase file {path} is owned by uid {state.uid} with mode\n"
                f"{state.mode:o}; the container's user, uid {CONTAINER_UID}, must own it and\n"
                f"read it, and nobody else read it (chown {CONTAINER_UID}:{CONTAINER_UID},\n"
                "chmod 400).\n"
                f"{_UNTOUCHED}"
            )

    def _rule_on_port(self, installed: Installed | None) -> int:
        if installed is not None:
            if self.port is not None and self.port != installed.port:
                raise DeployError(
                    f"--port {self.port}, but the person's port is {installed.port}: moving the\n"
                    f"door is not this act, and the edge forwards to the old one.\n{_UNTOUCHED}"
                )
            return installed.port
        if self.port is None:
            raise DeployError(
                f"a first install needs --port, the person's port on the box's loopback,\n"
                f"which the edge forwards their requests to.\n{_UNTOUCHED}"
            )
        taken = self.box.run(
            [
                "find",
                str(self.person.hubs_dir),
                "-mindepth",
                "2",
                "-maxdepth",
                "2",
                "-name",
                "unit.env",
                "-exec",
                "grep",
                "-lx",
                f"HUB_PORT={self.port}",
                "{}",
                "+",
            ]
        )
        # A resumed first install's own unit.env is the one it replaces.
        own = str(self.person.unit_env)
        others = [line for line in taken.out.splitlines() if line.strip() and line != own]
        if others:
            raise DeployError(
                f"port {self.port} is already another person's: {', '.join(others)}.\n{_UNTOUCHED}"
            )
        return self.port

    def _check_box_network(self) -> None:
        localnet = self._ok(
            ["sh", "-c", "grep -H . /proc/sys/net/ipv4/conf/*/route_localnet"],
            "reading route_localnet",
        )
        problems = route_localnet_problems(localnet)
        rules = self._ok(["iptables", "-t", "raw", "-S", "PREROUTING"], "reading the raw table")
        # Docker appends a container's drop while connecting it to its network, before its
        # process starts. A rule already here that may accept would stand before that drop,
        # so it is refused now, and the drop is in force when the gateway binds.
        accepting = accepting_rule(rules)
        if accepting is not None:
            problems.append(
                f"the raw table's PREROUTING chain has {accepting!r}, which may accept a\n"
                "packet, and Docker appends the drop that keeps other machines off a\n"
                "container after it"
            )
        if problems:
            raise DeployError(
                "ADR-0327 §5:2 cannot be established on this box:\n"
                + "\n".join(problems)
                + f"\n{_UNTOUCHED}"
            )

    # -- the image and the unit -----------------------------------------------

    def prepare_image(self) -> Image:
        """Build the new image on the box, or find the one named.

        Returns:
            The image to install.

        Raises:
            DeployError: If it cannot be built, or is not a labelled build.
        """
        if self.image_ref is not None:
            if _REFERENCE.fullmatch(self.image_ref) is None:
                raise DeployError(f"--image {self.image_ref!r} is not an image reference")
            image = self._image(self.image_ref)
            if image is None:
                raise DeployError(f"--image {self.image_ref} is not on the box.\n{_UNTOUCHED}")
            if _COMMIT.fullmatch(image.commit) is None:
                raise DeployError(
                    f"--image {self.image_ref} carries no commit label ({REVISION_LABEL}),\n"
                    "so it is not a build.sh build of a clean tree (ADR-0326 §3:2).\n"
                    f"{_UNTOUCHED}"
                )
            say(f"deploying {image.name}, built from {image.commit}")
            return image
        return self._build()

    def _build(self) -> Image:
        commit = _git(self.repo, "rev-parse", "HEAD")
        tag = f"{IMAGE_REPOSITORY}:{commit[:12]}"
        existing = self._image(tag)
        if existing is not None and existing.commit == commit:
            say(f"{tag} is already built on the box from {commit}; using it")
            return existing
        stage = f"{BOX_STAGE_PARENT}/hub-deploy-{self.token}"
        with tempfile.TemporaryDirectory(prefix="hub-deploy-") as scratch:
            context = Path(scratch) / "context"
            staged = (self.stage_context or _stage_context)(self.repo, context)
            if staged != commit:
                raise DeployError(f"HEAD moved from {commit} to {staged} while staging")
            archive = Path(scratch) / "context.tar"
            with tarfile.open(archive, "w") as tar:
                for entry in sorted(context.iterdir()):
                    tar.add(entry, arcname=entry.name, filter=_owned_by_root)
            self._ok(["mkdir", "-m", "0700", "--", stage], "making the box's staging directory")
            try:
                with archive.open("rb") as handle:
                    self._ok(
                        ["tar", "-x", "--no-same-owner", "-f", "-", "-C", stage],
                        "sending the build context",
                        stdin=handle,
                    )
                say(f"building {tag} on the box from {commit}")
                self._ok(
                    [
                        DOCKER,
                        "build",
                        "--file",
                        f"{stage}/Dockerfile",
                        "--label",
                        f"{REVISION_LABEL}={commit}",
                        "--label",
                        f"{SOURCE_LABEL}={SOURCE_URL}",
                        "--tag",
                        tag,
                        stage,
                    ],
                    f"building {tag}",
                )
            finally:
                self.box.run(["rm", "-rf", "--", stage])
        built = self._image(tag)
        if built is None or built.commit != commit:
            raise DeployError(f"{tag} is not on the box labelled {commit} after its build")
        return built

    def rule_on_history(self, installed: str, deploying: str) -> None:
        """Refuse a commit earlier than the one the unit runs, or not known to be later.

        Args:
            installed: The revision label of the image the unit runs now.
            deploying: The new image's.

        Raises:
            DeployError: If ADR-0326 §5:4 refuses it and ``--allow-earlier`` was not
                passed.
        """
        refusal = self.history(self.repo, installed, deploying)
        if refusal is None:
            return
        if not self.allow_earlier:
            raise DeployError(f"{refusal}.\n{HISTORY_WAY_BACK}\n{_UNTOUCHED}")
        say(f"{refusal};\ndeploying it, as --allow-earlier says")

    def install_unit(self) -> None:
        """Install the unit as this tree has it, reloading systemd when it changed.

        The unit is every person's, so it is installed under a lock of the box's, and
        its root is checked again inside it: two deploys to two people cannot both pass
        the preflight and then each install a different root.

        Raises:
            DeployError: If the lock cannot be had, the root differs, or the unit cannot
                be written or systemd cannot reload.
        """
        wanted = render_unit(UNIT_SOURCE.read_text(encoding="utf-8"), self.person.hubs_dir)
        lease = self._lock(UNIT_LOCK, wait=_UNIT_LOCK_SECONDS)
        if isinstance(lease, Result):
            raise DeployError(
                f"another deploy on this box held {UNIT_LOCK}, installing the unit, for\n"
                f"{_UNIT_LOCK_SECONDS}s. {_holder_hint(UNIT_LOCK, lease)}\n{_UNTOUCHED}"
            )
        try:
            self._check_unit_root()
            if self._read(PurePosixPath(UNIT_PATH)) == wanted:
                return
            self._write(PurePosixPath(UNIT_PATH), wanted)
            self._ok(["systemctl", "daemon-reload"], "reloading systemd")
            say(f"installed {UNIT_PATH}")
        finally:
            lease.release()

    def _lock(self, path: str | PurePosixPath, *, wait: int) -> Lease | Result:
        """Take a ``flock`` on a box file, held until released or this deploy ends.

        Args:
            path: The file, made if missing; an earlier deploy's lock directory serves.
            wait: Seconds to wait for another holder, or ``0`` not to wait.

        Returns:
            The lease, or how the holder ended: exit :data:`_BUSY` when another holds it.
        """
        argv = ["flock", f"--conflict-exit-code={_BUSY}"]
        argv += ["--nonblock"] if wait == 0 else [f"--wait={wait}"]
        # The holder prints once it holds the lock and then reads its standard input to
        # its end, which comes when this deploy releases it or ends, however it ends.
        return self.box.hold([*argv, "--", str(path), "sh", "-c", "echo held && exec cat"])

    # -- 2. the backup --------------------------------------------------------

    def back_up(self, earlier: Installed) -> PurePosixPath:
        """Stop the hub and back its volume up with the image that wrote it.

        On any failure the unit is started again on that image, and the failure names
        how that went.

        Args:
            earlier: What the unit runs.

        Returns:
            The artifact, written and verified.

        Raises:
            DeployError: If the backup is not written and verified.
        """
        person = self.person
        artifact = person.backups / f"pre-deploy-{self.stamp}-{self.token}.age"
        self._ok(
            [
                "install",
                "-d",
                "-o",
                str(CONTAINER_UID),
                "-g",
                str(CONTAINER_UID),
                "-m",
                "0700",
                "--",
                str(person.backups),
            ],
            f"making {person.backups}",
        )
        try:
            say(f"stopping {person.unit} for its backup")
            self._ok(["systemctl", "stop", person.unit], f"stopping {person.unit}")
            self._assert_stopped()
            say(f"backing {person.data_volume} up to {artifact}")
            result = self.box.run(
                [
                    DOCKER,
                    "run",
                    "--rm",
                    "--pull",
                    "never",
                    "--network",
                    "none",
                    "--name",
                    f"{person.container}-backup-{self.token}",
                    "--volume",
                    f"{person.data_volume}:/data",
                    "--volume",
                    f"{person.backups}:/backups",
                    "--volume",
                    f"{person.backup_passphrase}:/run/secrets/backup-passphrase:ro",
                    "--entrypoint",
                    "/opt/assistant/venv/bin/ai-assistant-backup",
                    earlier.image,
                    f"/backups/{artifact.name}",
                    "--passphrase-file",
                    "/run/secrets/backup-passphrase",
                ]
            )
            backup_outcome(result, artifact)
            state = self._stat(artifact)
            if state is None or state.size == 0:
                raise DeployError(f"the backup reported success, but {artifact} is absent or empty")
        except DeployError as exc:
            raise DeployError(
                f"{exc}\nNothing was installed. {self.restart_earlier(earlier)}"
            ) from exc
        except KeyboardInterrupt as exc:
            raise DeployError(
                f"interrupted during the backup. Nothing was installed, and no artifact was\n"
                f"verified. {self.restart_earlier(earlier)}"
            ) from exc
        say(f"{artifact} written and verified")
        return artifact

    def _assert_stopped(self) -> None:
        state = self._unit_state().get("ActiveState")
        if state not in {"inactive", "failed"}:
            raise DeployError(f"{self.person.unit} is {state} after its stop, not stopped")
        running = self._ok(
            [DOCKER, "ps", "--quiet", "--filter", f"volume={self.person.data_volume}"],
            "asking what uses the data volume",
        ).split()
        if running:
            raise DeployError(
                f"{self.person.data_volume} is still mounted by a running container"
                f" ({', '.join(running)}), so it is not still for a backup"
            )

    def restart_earlier(self, earlier: Installed) -> str:
        """Start the unit again on the image it ran, and say how that went.

        Never raises: it runs on the way out of a failure, which is what the operator
        must see.

        Args:
            earlier: What the unit ran, which ``unit.env`` still names.

        Returns:
            A sentence for the operator.
        """
        # unit.env is read again rather than trusted: a replacement interrupted after
        # its rename has already named the new image, and starting the unit then would
        # run that image with nothing checking who reaches it.
        try:
            text = self._read(self.person.unit_env)
            named = None if text is None else parse_unit_env(text).image
        except DeployError as exc:
            named = f"unreadable ({exc})"
        if named != earlier.image:
            self.box.run(["systemctl", "disable", self.person.unit])
            return (
                f"{self.person.unit_env} no longer names the earlier image {earlier.image}\n"
                f"(it names {named}), so nothing was started, and {self.person.unit} is\n"
                "stopped and disabled. Write the earlier image back into it and enable it,\n"
                "or deploy again."
            )
        # The earlier image is held to the same checks, and the same outcomes, as a new
        # one: a box that lost its isolation since it last ran is no reason to serve.
        try:
            _door, established = self.serve(earlier.image)
        except DeployError as exc:
            return f"The hub could NOT be started again on its earlier image, checked:\n{exc}"
        return (
            f"The hub was started again on its earlier image, {earlier.image}, healthy, its\n"
            f"door refusing, and {established}."
        )

    # -- 3 and 4. the cutover and its verification ----------------------------

    def _start(self) -> None:
        self.box.run(["systemctl", "reset-failed", self.person.unit])
        self._ok(["systemctl", "start", self.person.unit], f"starting {self.person.unit}")

    def serve(self, image_id: str) -> tuple[str, str]:
        """Start the unit on the image ``unit.env`` names, and verify it serves.

        The one path every start takes, the new image's and the earlier one's alike.

        Args:
            image_id: The image ``unit.env`` names, which the container must run.

        Returns:
            What the door answered, and what reachability established.

        Raises:
            DeployError: If it does not verify, saying what was left running: a start
                that is not ready is kept only if no other machine reaches it, and a
                door or reachability that fails is stopped and disabled.
        """
        say(f"starting {self.person.unit} on {image_id}")
        try:
            self._start()
            self.await_ready(image_id)
        except (DeployError, KeyboardInterrupt) as exc:
            raise DeployError(f"{_reason(exc)}\n{self._contain()}") from exc
        try:
            established = self.reachability()
            door = self._door()
        except (DeployError, KeyboardInterrupt) as exc:
            raise DeployError(f"{_reason(exc)}\n{self.stop_new()}") from exc
        return door, established

    def name_new_image(self, image: Image, *, first: bool) -> None:
        """Name the new image in ``unit.env`` and enable the unit, starting nothing.

        Args:
            image: The image to run.
            first: Whether this is the person's first install, whose volumes are made.

        Raises:
            DeployError: If the volumes, the unit or ``unit.env`` cannot be set up.
        """
        if first:
            self._install_first(image)
            return
        self._ok(["systemctl", "enable", self.person.unit], f"enabling {self.person.unit}")
        # Replaced whole, so until this lands the unit's next start is the earlier image.
        self._write_unit_env(image)

    def _install_first(self, image: Image) -> None:
        """Make a first install's volumes and ``unit.env``, recorded until they are made.

        :attr:`Person.first_install` is written before the volumes are made, and removed
        once ``unit.env`` is written and before the unit is enabled or started. While it
        stands nothing can run on the volumes, so a run that fails or is killed with it
        standing leaves volumes that hold nothing a hub wrote, and the next deploy
        resumes the install on them.

        Args:
            image: The image to run.
        """
        person = self.person
        self._write(
            person.first_install,
            f"# Written by scripts/deploy_container.py at {self.stamp}: a first install\n"
            f"# that has run nothing on {person.data_volume} or {person.keyring_volume}.\n",
            mode="0600",
        )
        self._sync(person.first_install, person.dir)
        say(f"a first install, recorded in {person.first_install}; making its volumes")
        for volume in (person.data_volume, person.keyring_volume):
            if not self._volume_exists(volume):
                self._ok([DOCKER, "volume", "create", volume], f"creating {volume}")
        self._write_unit_env(image)
        self._sync(person.unit_env, person.dir)
        self._ok(["rm", "-f", "--", str(person.first_install)], "removing the record")
        self._sync(person.dir)
        self._ok(["systemctl", "enable", person.unit], f"enabling {person.unit}")

    def _write_unit_env(self, image: Image) -> None:
        assert self.port is not None  # noqa: S101  # set by the preflight
        self._write(self.person.unit_env, render_unit_env(image, self.port, self.stamp, self.relay))

    def _sync(self, *paths: PurePosixPath) -> None:
        """Put files and directory entries on the box's disk, so a crash keeps them."""
        self._ok(["sync", "--", *map(str, paths)], "syncing the person's directory")

    def await_ready(self, image_id: str) -> None:
        """Wait for the unit's container to be healthy on ``image_id``.

        Args:
            image_id: The image it must run.

        Raises:
            DeployError: If the unit stops, the container runs another image, or it is
                not healthy within the deadline.
        """
        give_up = self.clock() + self.ready_timeout
        checked: object = None
        while True:
            state = self._unit_state()
            if state.get("ActiveState") in {"failed", "inactive"}:
                raise DeployError(
                    f"{self.person.unit} stopped (exit {state.get('ExecMainStatus')}) before"
                    f" its container was healthy; {self._journal()}"
                )
            fields = self._container()
            if fields is not None and fields.get("status") == "running":
                if fields.get("image") != image_id:
                    raise DeployError(
                        f"{self.person.container} runs {fields.get('image')}, not {image_id}"
                    )
                # Checked as soon as the container runs, not once it is healthy: the
                # gateway binds before the health check passes. Again after a restart,
                # which is a new address and new rules.
                address = container_address(fields, self.person.network)
                if address != checked:
                    self.reachability()
                    checked = address
                if fields.get("health") == "healthy":
                    return
            if self.clock() >= give_up:
                raise DeployError(
                    f"{self.person.container} was not healthy within {self.ready_timeout:g}s"
                    f" ({state.get('NRestarts', '?')} restarts); {self._journal()}"
                )
            self.sleep(_POLL_SECONDS)

    def reachability(self) -> str:
        """Establish ADR-0327 §5:2 on the running container.

        Returns:
            What was established, for the report.

        Raises:
            DeployError: If it cannot be established.
        """
        fields = self._container()
        if fields is None:
            raise DeployError(f"{self.person.container} is gone")
        network = self.person.network
        problems = container_problems(fields, self.port or 0, network)
        address = container_address(fields, network)
        if not problems:
            if not address:
                problems.append("the container has no IPv4 address on the bridge")
            else:
                bridge = self._bridge_interface(network, problems)
                rules = self._ok(
                    ["iptables", "-t", "raw", "-S", "PREROUTING"], "reading the raw table"
                )
                problem = raw_rule_problem(rules, address, bridge) if bridge else None
                if problem:
                    shown = "\n".join(f"    {line}" for line in rules.splitlines()) or "    (empty)"
                    problems.append(f"{problem}. The chain:\n{shown}")
        if problems:
            raise DeployError("ADR-0327 §5:2 cannot be established:\n" + "\n".join(problems))
        return (
            f"reachability: published to 127.0.0.1:{self.port} alone, on {network} at"
            f" {address}, whose {HOSTED_PORT} the raw table closes to every other interface"
        )

    def stop_new(self) -> str:
        """Stop the unit on the new image, and say whether it is stopped.

        Never raises: it runs on the way out of a failure.

        Returns:
            A sentence for the operator.
        """
        unit = self.person.unit
        # Disabled as well as stopped: a boot would otherwise start what this deploy could
        # not show unreachable, with nothing checking it.
        disabled = self.box.run(["systemctl", "disable", unit])
        stopped = self.box.run(["systemctl", "stop", unit])
        try:
            state = self._unit_state().get("ActiveState")
            running = self._ok(
                [DOCKER, "ps", "--quiet", "--filter", f"name=^{self.person.container}$"],
                "asking whether the container runs",
            ).split()
        except DeployError as exc:
            state, running = f"unknown ({exc})", ["?"]
        if disabled.ok and stopped.ok and state in {"inactive", "failed"} and not running:
            return (
                f"{unit} is stopped and disabled: it does not serve, at boot or before, until\n"
                "a deploy verifies it, and the earlier image is not started on its data\n"
                "(ADR-0326 §5:4)."
            )
        return (
            f"{unit} could NOT be shown stopped and disabled (disable exit {disabled.code},\n"
            f"stop exit {stopped.code}, state {state},\n"
            f"container {'running' if running else 'gone'}): it may still serve where this\n"
            f"deploy could not establish who reaches it. Stop it by hand: systemctl stop {unit}"
        )

    def _contain(self) -> str:
        """After a start that did not become ready: keep it only if no other machine reaches it.

        Returns:
            A sentence for the operator.
        """
        try:
            established = self.reachability()
        except DeployError as exc:
            return f"{exc}\n{self.stop_new()}"
        return (
            f"{established}; so the unit keeps the image it started as its supervisor rules,\n"
            "and no other image is started on data that one has served (ADR-0326 §5:4)."
        )

    def _bridge_interface(self, network: str, problems: list[str]) -> str:
        """The person's network's interface on the host, when it is a bridge.

        Args:
            network: The network.
            problems: Where to say why it is not one.

        Returns:
            The interface, or ``""`` with a problem recorded.
        """
        out = (
            self._ok(
                [
                    DOCKER,
                    "network",
                    "inspect",
                    "--format",
                    '{{.Driver}}|{{.Id}}|{{index .Options "com.docker.network.bridge.name"}}',
                    network,
                ],
                f"reading the network {network}",
            )
            .strip()
            .split("|")
        )
        if len(out) < 2 or out[0] != "bridge":  # noqa: PLR2004
            problems.append(f"the network {network} is {'|'.join(out)!r}, not a bridge")
            return ""
        # Docker names a user-defined bridge's interface br-<the id's first twelve>,
        # unless the network was made with a name of its own.
        named = out[2] if len(out) > 2 and out[2] != "<no value>" else ""  # noqa: PLR2004
        return named or f"br-{out[1][:12]}"

    def _door(self) -> str:
        host = self._ok(
            [
                DOCKER,
                "exec",
                self.person.container,
                "printenv",
                "ASSISTANT_GATEWAY_HOSTED_HOST_NAME",
            ],
            "reading the hosted host name",
        ).strip()
        argv = ["curl", "--silent", "--output", "/dev/null", "--max-time", "10"]
        argv += ["--write-out", "%{http_code}", "--header", f"Host: {host}"]
        argv += [f"http://127.0.0.1:{self.port}/"]
        answered = ""
        for attempt in range(3):
            answered = self.box.run(argv).out.strip()
            if answered == "403":
                return answered
            if attempt < 2:  # noqa: PLR2004
                self.sleep(_POLL_SECONDS)
        raise DeployError(
            f"a request to 127.0.0.1:{self.port} without the edge's assertion was answered"
            f" {answered or 'with nothing'}, not refused with 403 by the gateway"
        )

    # -- the whole act ---------------------------------------------------------

    def run(self) -> list[str]:
        """Deploy, and verify.

        Returns:
            The report.

        Raises:
            DeployError: On any failure, saying what it left running.
        """
        person = self.person
        self._check_person_dir()
        lease = self._lock(person.lock, wait=0)
        if isinstance(lease, Result):
            raise DeployError(
                f"another deploy to {person.name} holds {person.lock}.\n"
                f"{_holder_hint(str(person.lock), lease)}\n{_UNTOUCHED}"
            )
        try:
            return self._run(lease)
        finally:
            lease.release()

    def _run(self, lease: Lease) -> list[str]:
        installed = self.preflight()
        image = self.prepare_image()
        before = "none, a first install"
        if installed is not None:
            earlier = self._image(installed.image)
            commit = earlier.commit if earlier is not None else ""
            self.rule_on_history(commit, image.commit)
            before = f"{installed.image} (commit {commit or 'unlabelled'})"
        _still_held(lease, self.person.lock, _UNTOUCHED)
        self.install_unit()
        _still_held(lease, self.person.lock, "Nothing has been stopped.")
        artifact = None if installed is None else self.back_up(installed)
        try:
            _still_held(lease, self.person.lock, "Nothing was installed.")
            self.name_new_image(image, first=installed is None)
        except (DeployError, KeyboardInterrupt) as exc:
            if installed is None:
                raise
            raise DeployError(
                f"{_reason(exc)}\nThe new image never ran. {self.restart_earlier(installed)}\n"
                f"{_backup_line(artifact)}"
            ) from exc
        try:
            door, reachability = self.serve(image.id)
        except DeployError as exc:
            raise DeployError(f"{exc}\n{_backup_line(artifact)}") from exc
        verified = [
            f"door: 127.0.0.1:{self.port} answers {door} without the edge's assertion",
            reachability,
        ]
        relay = "none, the line is direct" if self.relay is None else f"--add-host {self.relay}"
        return [
            f"person: {self.person.name}, {self.person.unit}, port {self.port}",
            f"before: {before}",
            f"after:  {image.id} ({image.name}, commit {image.commit}), healthy",
            *verified,
            f"relay:  {relay}",
            _backup_line(artifact),
        ]


def _holder_hint(path: str, refused: Result) -> str:
    """Say why a lock could not be had, and how to find who holds it.

    Args:
        path: The lock file.
        refused: How its holder ended.

    Returns:
        The sentences for the operator.
    """
    if refused.code != _BUSY:
        return f"Taking it failed (exit {refused.code}):\n{refused.said()}"
    return (
        "A deploy holds it for as long as it runs, and the kernel releases it when the\n"
        "deploy ends, however it ends, so a deploy that was killed holds nothing. Wait for\n"
        f"the one running, or find it on the box with `fuser -v {path}`."
    )


def _still_held(lease: Lease, path: PurePosixPath, untouched: str) -> None:
    """Refuse to go on once the person's lock has been lost.

    Its holder ends early only when its link to the box drops, and then another deploy
    may take the lock: so this deploy changes nothing more.

    Args:
        lease: The person's lock.
        path: Its file, for the message.
        untouched: What has not been changed, for the message.

    Raises:
        DeployError: If the lock is no longer held.
    """
    if not lease.held():
        raise DeployError(
            f"the session holding {path} on the box ended, so another deploy may now hold\n"
            f"it: the link to the box dropped. Deploy again once it is back.\n{untouched}"
        )


def _reason(exc: BaseException) -> str:
    """Say what stopped the deploy, an interrupt included."""
    if isinstance(exc, KeyboardInterrupt):
        return "interrupted once the new image was being named in unit.env or started."
    return str(exc)


def _backup_line(artifact: PurePosixPath | None) -> str:
    if artifact is None:
        return "backup: none, a first install has served no data"
    return f"backup: {artifact} (verified, and kept)"


def _owned_by_root(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    return info


def _git(repo: Path, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise DeployError("git is not on PATH")
    result = _execute([git, "-C", str(repo), *args], None)
    if not result.ok:
        raise DeployError(f"git {' '.join(args)} failed: {result.said()}")
    return result.out.strip()


def _stage_context(repo: Path, into: Path) -> str:
    """Stage the image's build context with ``build.sh --context``.

    Args:
        repo: The repository.
        into: A directory that does not exist yet.

    Returns:
        The commit it staged.

    Raises:
        DeployError: If the tree is dirty or the staging fails.
    """
    result = _execute([str(BUILD_SCRIPT), "--context", str(into)], None)
    if not result.ok:
        raise DeployError(f"staging the build context failed:\n{result.said()}\n{_UNTOUCHED}")
    return _git(repo, "rev-parse", "HEAD")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build, back up, replace and verify one person's hub container on a box"
            " (issue #3160, ADR-0326 §6)."
        )
    )
    parser.add_argument("person", help="the person's name: lowercase letters, digits and -")
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("host", nargs="?", help="the box, reached over ssh")
    where.add_argument("--local", action="store_true", help="this machine is the box (sudo -n)")
    parser.add_argument("--ssh-user", default=DEFAULT_SSH_USER, help="ssh's login user")
    parser.add_argument("--hubs-dir", default=DEFAULT_HUBS_DIR, help="the person directories")
    parser.add_argument("--port", type=int, help="the person's loopback port; a first install")
    parser.add_argument("--image", help="deploy this image, already on the box, unbuilt")
    parser.add_argument("--allow-earlier", action="store_true", help=ALLOW_EARLIER_HELP)
    parser.add_argument(
        "--relay-address",
        help=(
            "the IPv4 address the Telegram relay listens on, on this box; a relayed hub's"
            " container resolves its origin's host to it (ADR-0330 §8:2)"
        ),
    )
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=DEFAULT_READY_TIMEOUT,
        help="seconds the new container has to become healthy",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` when the new container is up and verified, else ``1``.
    """
    args = _parser().parse_args(argv)
    try:
        if _PERSON.fullmatch(args.person) is None:
            raise DeployError(f"{args.person!r} is not a person's name: a-z, 0-9 and -, ≤32")
        if args.host is not None and (args.host.startswith("-") or not args.host.strip()):
            raise DeployError(f"{args.host!r} is not a host")
        if args.port is not None and not 1024 <= args.port <= 65535:  # noqa: PLR2004
            raise DeployError(f"--port {args.port} is not an unprivileged TCP port")
        hubs = PurePosixPath(args.hubs_dir)
        # The root goes into the unit's command lines, where systemd splits on spaces
        # and expands `%`, so it is held to characters both read literally.
        if not hubs.is_absolute() or _PLAIN_PATH.fullmatch(args.hubs_dir) is None:
            raise DeployError(
                f"--hubs-dir {args.hubs_dir!r} is not an absolute path of letters, digits, '.',"
                " '_', '-' and '/'"
            )
        if args.relay_address is not None:
            try:
                IPv4Address(args.relay_address)
            except ValueError as exc:
                raise DeployError(
                    f"--relay-address {args.relay_address!r} is not an IPv4 address"
                ) from exc
        box: Box = LocalBox() if args.local else SshBox(args.host, args.ssh_user)
        deployment = Deployment(
            box=box,
            person=Person(args.person, hubs),
            port=args.port,
            image_ref=args.image,
            ready_timeout=args.ready_timeout,
            allow_earlier=args.allow_earlier,
            relay_address=args.relay_address,
        )
        report = deployment.run()
    except (DeployError, HubDeployError) as exc:
        print(f"deploy-container: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("deploy-container: interrupted; read the lines above for where.", file=sys.stderr)
        return 1
    for line in report:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
