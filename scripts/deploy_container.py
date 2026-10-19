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

**The box.** It has Docker and systemd, ``curl`` and ``iptables``, and ssh logs in as a
user that may run them, ``root`` by default. Every box command is one argv, quoted for
the remote shell by :func:`shlex.join` and never assembled from text. ``--local`` makes
this machine the box, its commands run as root through ``sudo -n``; that is how the
``container`` workflow deploys to its own runner. Per person, under ``--hubs-dir``
(``/srv/hubs``):

* ``<person>/hub.env``: the container's environment, Docker's ``--env-file`` format,
  holding the model key. The operator writes it; mode ``0600``, read by the docker
  client as root.
* ``<person>/keyring-passphrase`` and ``<person>/backup-passphrase``: one passphrase
  each, owned by the container's user (uid 10001, the image's) and readable by it alone.
  **The operator creates both, by hand; nothing here creates, reads, prints or sends
  either.** The deploy examines their owner and mode, mounts them read-only into the
  container that needs each, and refuses before stopping anything when one is wrong.
* ``<person>/unit.env``: what the unit runs, ``HUB_IMAGE`` (an image id, so a moved tag
  cannot change it) and ``HUB_PORT``. Written by this deploy alone, and only once the
  backup is verified, so until then the unit's next start is the earlier image.
* ``<person>/backups/``: each deploy's artifact, ``pre-deploy-<UTC>-<run>.age``, outside
  the data volume and never deleted (ADR-0326 §6:3). Pruning is the operator's act.
* The volumes ``hub-<person>-data`` and ``hub-<person>-keyring``, the container
  ``hub-<person>`` and the unit ``hub@<person>.service``, from
  ``deploy/container/hub@.service``, which every deploy installs as it is in this tree.

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
   the new image built and labelled, the unit installed. *Nothing is stopped.*
2. On a person whose hub has served data, the unit is stopped, and the earlier image's
   own ``ai-assistant-backup`` copies the data volume to the artifact, in a container
   of its own with no network. A backup that fails, or is written but unverified,
   leaves ``unit.env`` as it was and the unit is started again: *the earlier image
   runs, and the new one never has* (§6:2).
3. ``unit.env`` names the new image and the unit starts it. From here the new image has
   run on the data, so whatever fails, the earlier one is never started on it again
   (ADR-0326 §5:4). Undoing the deploy is a later image or a restore of the backup.
4. The new container is verified: healthy, running the new image, the door answering
   ``403`` on the published loopback port, and the reachability check below. A
   container that never becomes healthy is left to its unit; one whose reachability
   cannot be established is stopped.

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

* the container is on Docker's default bridge, not the host's network, and publishes
  exactly one port, ``8423/tcp``, to ``127.0.0.1`` alone, and has no IPv6 address;
* ``route_localnet`` is ``0`` for ``all`` and for every interface that is not the
  loopback or Docker's own (``docker0``, ``br-*``, ``veth*``), so the kernel drops a
  packet for ``127.0.0.0/8`` that arrives from another machine;
* the raw table's ``PREROUTING`` chain drops what arrives for the container's address
  on any interface but its bridge, by the rule Docker Engine 28 and later writes
  (``-d <address>/32 ! -i <bridge> -j DROP``), and no rule before it can accept the
  packet first.

What it cannot see: a firewall that is not iptables' (Docker's nftables backend is
refused, not read), the network beyond the box, and any process on the box that
forwards the port itself, which is the box's own act. Every process *on* the box can
reach the listener, as ADR-0327 §6 expects: the edge's signature stands between them.

**One deploy per person at a time.** ``<person>/.deploy-lock`` is made at the start and
removed at the end; a run that cannot make it refuses, and one killed outright leaves it
for the operator to remove.
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
from pathlib import Path, PurePosixPath
from typing import IO, TYPE_CHECKING, Protocol

# The backup tool's own words, held to its source by deploy_hub's tests: one source for
# what "written and verified" looks like, whichever deploy reads it.
from deploy_hub import _BACKUP_DISCLOSES, _BACKUP_UNVERIFIED, _BACKUP_VERIFIED

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
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]*")
#: Interfaces Docker makes for its bridges, whose ``route_localnet`` is Docker's own.
_DOCKER_INTERFACE = re.compile(r"docker0|br-[0-9a-f]+|veth[0-9a-f]+")
#: Raw-table targets that never accept a packet, and so cannot let one past a drop.
_NON_ACCEPTING_TARGETS = frozenset({"DROP", "CT", "NOTRACK", "LOG", "MARK", "TRACE", "NFLOG"})
#: The setting that sizes ADR-0083's D2, which the unit's stop timeout is fixed against.
_DRAIN_SETTING = "ASSISTANT_SHUTDOWN_DRAIN_SECONDS"
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
        """The directory whose existence is a deploy in progress."""
        return self.dir / ".deploy-lock"

    @property
    def container(self) -> str:
        """The hub's container."""
        return f"hub-{self.name}"

    @property
    def unit(self) -> str:
        """The unit that runs it."""
        return f"hub@{self.name}.service"

    @property
    def data_volume(self) -> str:
        """The data directory's volume."""
        return f"hub-{self.name}-data"

    @property
    def keyring_volume(self) -> str:
        """The keyring's volume."""
        return f"hub-{self.name}-keyring"


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


def render_unit_env(image: Image, port: int, stamp: str) -> str:
    """Write ``unit.env``.

    Args:
        image: The image the unit is to run.
        port: The person's loopback port.
        stamp: When, for the reader.

    Returns:
        The file's content.
    """
    return (
        f"# Written by scripts/deploy_container.py at {stamp}: {image.name},\n"
        f"# commit {image.commit}. Read by hub@.service; edited by nothing else.\n"
        f"HUB_IMAGE={image.id}\n"
        f"HUB_PORT={port}\n"
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


def raw_rule_problem(rules: str, address: str, bridge: str) -> str | None:
    """Find the drop that keeps other machines off the container's bridge address.

    Args:
        rules: ``iptables -t raw -S PREROUTING``.
        address: The container's IPv4 address on its bridge.
        bridge: The bridge's interface.

    Returns:
        ``None`` when the chain drops what arrives for ``address`` on any other
        interface before anything can accept it, or why it cannot be shown to.
    """
    wanted = ["-A", "PREROUTING", "-d", f"{address}/32", "!", "-i", bridge, "-j", "DROP"]
    for line in rules.splitlines():
        words = line.split()
        if not words or words[0] != "-A":
            continue
        if words == wanted:
            return None
        target = words[words.index("-j") + 1] if "-j" in words[:-1] else None
        if target is None or target not in _NON_ACCEPTING_TARGETS:
            return (
                f"the raw table's PREROUTING chain has {line.strip()!r} before any drop for\n"
                f"{address}, and it may accept a packet for the container from elsewhere"
            )
    return (
        f"the raw table's PREROUTING chain has no `-d {address}/32 ! -i {bridge} -j DROP`.\n"
        "Docker Engine 28 and later write it for each container on a bridge, on the\n"
        "iptables firewall backend; without it another machine may route to the container"
    )


def container_problems(fields: dict[str, object], port: int) -> list[str]:
    """Rule on the network half of :data:`_CONTAINER_FIELDS`.

    Args:
        fields: The decoded inspect fields.
        port: The person's loopback port.

    Returns:
        A sentence per way the container is reachable other than as published.
    """
    problems: list[str] = []
    if fields.get("mode") != "bridge":
        problems.append(f"the container's network is {fields.get('mode')!r}, not Docker's bridge")
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
    if not isinstance(networks, dict) or list(networks) != ["bridge"]:
        names = list(networks) if isinstance(networks, dict) else networks
        problems.append(f"the container is on the networks {names}, not on 'bridge' alone")
        return problems
    bridge = networks["bridge"]
    if isinstance(bridge, dict) and bridge.get("GlobalIPv6Address"):
        problems.append(
            "the container has an IPv6 address on the bridge, which this deploy does not check"
        )
    return problems


def container_address(fields: dict[str, object]) -> str:
    """The container's IPv4 address on the default bridge.

    Args:
        fields: The decoded inspect fields.

    Returns:
        The address, or ``""`` when it has none.
    """
    networks = fields.get("networks")
    bridge = networks.get("bridge") if isinstance(networks, dict) else None
    address = bridge.get("IPAddress") if isinstance(bridge, dict) else None
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
        for tool in (["systemctl", "--version"], ["curl", "--version"], ["iptables", "--version"]):
            self._ok(tool, f"{tool[0]} on the box")
        self._check_env_file()
        self._check_passphrase(person.keyring_passphrase, "keyring")
        text = self._read(person.unit_env)
        installed = None if text is None else parse_unit_env(text)
        served = self._volume_exists(person.data_volume)
        if installed is None and served:
            raise DeployError(
                f"the volume {person.data_volume} exists but {person.unit_env} does not, so a\n"
                "hub has served data here and nothing says which image wrote it: no backup can\n"
                "be taken with that image before installing (ADR-0326 §6:1). Back the volume\n"
                f"up by hand, write unit.env naming that image, and deploy again.\n{_UNTOUCHED}"
            )
        if installed is not None and not served:
            raise DeployError(
                f"{person.unit_env} names an image but the volume {person.data_volume} is\n"
                "missing: the person's data is not where the unit mounts it. Find it before\n"
                f"deploying; this deploy never starts a hub on a new volume over one.\n{_UNTOUCHED}"
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
        self._check_box_network()
        return installed

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
        if state.uid != CONTAINER_UID or state.mode & 0o077:
            raise DeployError(
                f"the {which} passphrase file {path} is owned by uid {state.uid} with mode\n"
                f"{state.mode:o}; the container's user, uid {CONTAINER_UID}, must own it and\n"
                f"nobody else read it (chown {CONTAINER_UID}:{CONTAINER_UID}, chmod 400).\n"
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
        others = [line for line in taken.out.splitlines() if line.strip()]
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
        if problems:
            raise DeployError(
                "ADR-0327 §5:2 cannot be established on this box:\n"
                + "\n".join(problems)
                + f"\n{_UNTOUCHED}"
            )
        self._ok(["iptables", "-t", "raw", "-S", "PREROUTING"], "reading the raw table")

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

    def install_unit(self) -> None:
        """Install the unit as this tree has it, reloading systemd when it changed.

        Raises:
            DeployError: If it cannot be written or systemd cannot reload.
        """
        wanted = render_unit(UNIT_SOURCE.read_text(encoding="utf-8"), self.person.hubs_dir)
        if self._read(PurePosixPath(UNIT_PATH)) == wanted:
            return
        self._write(PurePosixPath(UNIT_PATH), wanted)
        self._ok(["systemctl", "daemon-reload"], "reloading systemd")
        say(f"installed {UNIT_PATH}")

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
        try:
            self._start()
            self.await_ready(earlier.image)
        except DeployError as exc:
            return f"The hub could NOT be started again on its earlier image:\n{exc}"
        return f"The hub was started again on its earlier image, {earlier.image}, and is healthy."

    # -- 3 and 4. the cutover and its verification ----------------------------

    def _start(self) -> None:
        self.box.run(["systemctl", "reset-failed", self.person.unit])
        self._ok(["systemctl", "start", self.person.unit], f"starting {self.person.unit}")

    def name_new_image(self, image: Image, *, first: bool) -> None:
        """Enable the unit and name the new image in ``unit.env``, starting nothing.

        Args:
            image: The image to run.
            first: Whether this is the person's first install, whose volumes are made.

        Raises:
            DeployError: If the volumes, the unit or ``unit.env`` cannot be set up.
        """
        person = self.person
        if first:
            for volume in (person.data_volume, person.keyring_volume):
                if not self._volume_exists(volume):
                    self._ok([DOCKER, "volume", "create", volume], f"creating {volume}")
        self._ok(["systemctl", "enable", person.unit], f"enabling {person.unit}")
        assert self.port is not None  # noqa: S101  # set by the preflight
        # Replaced whole, so until this lands the unit's next start is the earlier image.
        self._write(person.unit_env, render_unit_env(image, self.port, self.stamp))

    def await_ready(self, image_id: str) -> None:
        """Wait for the unit's container to be healthy on ``image_id``.

        Args:
            image_id: The image it must run.

        Raises:
            DeployError: If the unit stops, the container runs another image, or it is
                not healthy within the deadline.
        """
        give_up = self.clock() + self.ready_timeout
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
                if fields.get("health") == "healthy":
                    return
            if self.clock() >= give_up:
                raise DeployError(
                    f"{self.person.container} was not healthy within {self.ready_timeout:g}s"
                    f" ({state.get('NRestarts', '?')} restarts); {self._journal()}"
                )
            self.sleep(_POLL_SECONDS)

    def verify(self) -> list[str]:
        """Check the door and ADR-0327 §5:2 on the running container.

        Returns:
            What was established, one line each, for the report.

        Raises:
            DeployError: If either cannot be established.
        """
        fields = self._container()
        if fields is None:
            raise DeployError(f"{self.person.container} is gone")
        problems = container_problems(fields, self.port or 0)
        address = container_address(fields)
        if not problems:
            if not address:
                problems.append("the container has no IPv4 address on the bridge")
            else:
                bridge = self._ok(
                    [
                        DOCKER,
                        "network",
                        "inspect",
                        "--format",
                        '{{index .Options "com.docker.network.bridge.name"}}',
                        "bridge",
                    ],
                    "reading the bridge's interface",
                ).strip()
                rules = self._ok(
                    ["iptables", "-t", "raw", "-S", "PREROUTING"], "reading the raw table"
                )
                problem = raw_rule_problem(rules, address, bridge)
                if problem:
                    problems.append(problem)
        if problems:
            raise DeployError("ADR-0327 §5:2 cannot be established:\n" + "\n".join(problems))
        door = self._door()
        return [
            f"door: 127.0.0.1:{self.port} answers {door} without the edge's assertion",
            f"reachability: published to 127.0.0.1:{self.port} alone, on the bridge at"
            f" {address}, which the raw table closes to every other interface",
        ]

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
        lock = self.box.run(["mkdir", "-m", "0700", "--", str(person.lock)])
        if not lock.ok:
            raise DeployError(
                f"could not make {person.lock}: another deploy to {person.name} is running,\n"
                f"or one was killed. Remove it once none is.\n{lock.said()}\n{_UNTOUCHED}"
            )
        try:
            return self._run()
        finally:
            self.box.run(["rmdir", "--", str(person.lock)])

    def _run(self) -> list[str]:
        installed = self.preflight()
        image = self.prepare_image()
        self.install_unit()
        before = "none, a first install"
        if installed is not None:
            earlier = self._image(installed.image)
            commit = earlier.commit if earlier is not None else "unlabelled"
            before = f"{installed.image} (commit {commit})"
        artifact = None if installed is None else self.back_up(installed)
        try:
            self.name_new_image(image, first=installed is None)
        except DeployError as exc:
            if installed is None:
                raise
            raise DeployError(
                f"{exc}\nThe new image never ran. {self.restart_earlier(installed)}\n"
                f"{_backup_line(artifact)}"
            ) from exc
        try:
            say(f"starting {self.person.unit} on {image.name}")
            self._start()
            self.await_ready(image.id)
        except DeployError as exc:
            raise DeployError(
                f"{exc}\nThe new image has started on the data, so the earlier one is not\n"
                "started again (ADR-0326 §5:4); the unit keeps the new one as its supervisor\n"
                f"rules. {_backup_line(artifact)}"
            ) from exc
        try:
            verified = self.verify()
        except DeployError as exc:
            self.box.run(["systemctl", "stop", self.person.unit])
            raise DeployError(
                f"{exc}\n{self.person.unit} is stopped: it does not serve while this is so,\n"
                f"and the earlier image is not started on its data (ADR-0326 §5:4).\n"
                f"{_backup_line(artifact)}"
            ) from exc
        return [
            f"person: {self.person.name}, {self.person.unit}, port {self.port}",
            f"before: {before}",
            f"after:  {image.id} ({image.name}, commit {image.commit}), healthy",
            *verified,
            _backup_line(artifact),
        ]


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
        if not hubs.is_absolute():
            raise DeployError(f"--hubs-dir {args.hubs_dir} is not an absolute path")
        box: Box = LocalBox() if args.local else SshBox(args.host, args.ssh_user)
        deployment = Deployment(
            box=box,
            person=Person(args.person, hubs),
            port=args.port,
            image_ref=args.image,
            ready_timeout=args.ready_timeout,
        )
        report = deployment.run()
    except DeployError as exc:
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
