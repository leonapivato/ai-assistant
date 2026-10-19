"""Supervise one person's hub and its gateway, inside the container that holds them (#3142).

The container is one person's unit: their hub, the gateway in front of it, and the
keyring ``assistant connect`` writes to. This program is what runs those four
processes, and its own exit is the container's exit. ``tini`` is PID 1 and reaps;
this is its one child.

**What it promises, in ADR-0083 §3's terms.** S1: it runs in the foreground and every
child logs to the container's stdout and stderr. S2: it exits ``0`` only after a stop
was asked for and the hub drained. S3: it exits ``78`` only when the deployment must
change before a start can succeed, and it prints the cause and the operator action
first. S4: any other exit is ``1``, and means "start me again". It restarts nothing
itself, so the one supervisor that decides is the one outside the container, and
``docs/guide/container.md`` names what that must be: Docker's restart policies cannot
leave a ``78`` down, which is ADR-0083's D1, so the reference is a systemd unit around
``docker run`` with ``RestartPreventExitStatus=78``.

**The order is fixed, and readiness is the last thing in it.**

1. The checks that need nothing running: the keyring passphrase is mounted, the data
   directory and the keyring are volumes rather than the container's own layer
   (ADR-0326 §3:1), the hosted listener has an address only the host's loopback
   reaches (ADR-0327 §5:4), and no remote listener or remote hub is configured, so
   the gateway reaches the hub over the local socket and the hub's remote listener
   stays off. A failure is a ``78``.
2. A session bus and a headless ``gnome-keyring-daemon`` on it, unlocked with the
   passphrase: a genuine SecretService keyring, the only kind ADR-0125 §7 lets the
   secret store use. A passphrase that leaves the login keyring locked is a ``78``.
3. The hub, until its socket accepts (ADR-0083 §3 step 6).
4. The gateway, until its hosted listener accepts. A gateway that stops before it
   ever accepted passes its ``78`` through, since it exits ``78`` only for a refusal
   no restart changes (#3167); any other stop is a ``1``.
5. ``/run/assistant/ready``, which the image's health check reads.

**A stop is one signal to each.** ``SIGTERM`` or ``SIGINT`` here sends ``SIGINT`` to
the gateway, which is its clean stop (``assistant gateway`` installs no ``SIGTERM``
handler), and ``SIGTERM`` to the hub, which drains (ADR-0083 §4), and then waits for
both with no deadline of its own: the deadline is the runtime's stop timeout, and
ADR-0083's D2 sizes it. A second stop signal changes nothing. Any child stopping
unasked stops the rest, the same way.

**Admin acts run beside it, not through it.** ``docker exec <name> assistant connect
…`` and ``docker exec <name> ai-assistant-device …`` run as the same user in the same
working directory, so they read the same settings — the ``.env`` this program writes
there holds the one value only it can know, the container's own address — and reach
the same keyring, on the bus at the fixed address the image names.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import ipaddress
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, MutableMapping, Sequence
    from types import FrameType

#: ADR-0083 §5's three exit codes, the container's as they are the hub's. Restated
#: rather than imported from ``ai_assistant.service.exits``, which ADR-0083 §8 keeps
#: every importer out of; the tests hold the two equal.
EXIT_OK: Final = 0
EXIT_RESTART: Final = 1
EXIT_DEPLOYMENT: Final = 78

#: The setting the hosted listener binds (ADR-0327 §5:1).
HOSTED_ADDRESS: Final = "ASSISTANT_GATEWAY_HOSTED_ADDRESS"

#: The settings that would give the hub a remote listener, give the gateway a remote
#: browser listener, or send the gateway to a hub somewhere else. In this container
#: the gateway reaches the hub over the local socket and nothing else listens.
REMOTE_SETTINGS: Final = ("hub_remote_address", "gateway_remote_address", "remote_hub_address")

#: The ``ioctl`` that reads one interface's IPv4 address (``<linux/sockios.h>``).
_SIOCGIFADDR: Final = 0x8915

#: How often a wait looks again, in seconds.
_POLL: Final = 0.2

#: How long the bus and the keyring have to come up, and to go down, in seconds.
#: Both are local and quick; a deadline here bounds nothing the hub depends on.
_AUXILIARY_DEADLINE: Final = 30.0

#: The private-use IPv4 ranges (RFC 1918) ADR-0327 §5:3 admits for the hosted address.
_PRIVATE_USE: Final = tuple(
    ipaddress.ip_network(block) for block in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def say(message: str) -> None:
    """Write one line of this program's own to the container's log.

    Args:
        message: Operational text: settings names, paths and addresses, never a value
            from the keyring or the environment's secrets (ADR-0004 §5).
    """
    print(f"hub-container: {message}", file=sys.stderr, flush=True)


class DeploymentError(Exception):
    """The deployment must change before a start can succeed: exit ``78``.

    The message is the cause and the operator action, which ADR-0083 §5 requires every
    ``78`` to print before it exits.
    """


class StartError(Exception):
    """A start that failed in a way a restart may clear: exit ``1``."""


@dataclass(frozen=True)
class Layout:
    """Where the image puts each thing. The defaults are the image's; tests move them."""

    data_dir: Path = Path("/data")
    keyrings: Path = Path("/home/assistant/.local/share/keyrings")
    runtime_dir: Path = Path("/run/assistant")
    passphrase: Path = Path("/run/secrets/keyring-passphrase")
    venv_bin: Path = Path("/opt/assistant/venv/bin")
    bus_config: Path = Path("/opt/assistant/session-bus.conf")

    @property
    def bus(self) -> Path:
        """The session bus's socket, at the address the image's environment names."""
        return self.runtime_dir / "bus"

    @property
    def dotenv(self) -> Path:
        """The ``.env`` ``Settings`` reads from the working directory, for every process."""
        return self.runtime_dir / ".env"

    @property
    def ready(self) -> Path:
        """The marker the health check reads: present only while everything is up."""
        return self.runtime_dir / "ready"


# --- 1. The checks that need nothing running -------------------------------------


def read_passphrase(path: Path) -> bytes:
    """Read the keyring passphrase from its mounted file.

    One trailing newline is dropped, as ``$(cat file)`` would drop it, so a file
    written by ``echo`` and one written by ``printf`` unlock the same keyring.

    Args:
        path: Where the run instructions mount it.

    Returns:
        The passphrase, which goes to the keyring daemon's standard input and nowhere
        else: not the environment, not an argument, not the log.

    Raises:
        DeploymentError: If it is absent, unreadable or empty.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        msg = (
            f"no keyring passphrase is mounted at {path}. The container's keyring is "
            f"unlocked with it at every start (ADR-0125 §7). Mount a file holding it "
            f"there, readable by uid {os.getuid()}"
        )
        raise DeploymentError(msg) from None
    except OSError as exc:
        msg = (
            f"the keyring passphrase at {path} cannot be read ({exc.strerror}). Make it "
            f"readable by uid {os.getuid()}"
        )
        raise DeploymentError(msg) from None
    passphrase = raw.removesuffix(b"\n").removesuffix(b"\r")
    if not passphrase:
        msg = f"the keyring passphrase at {path} is empty. Write a passphrase into it"
        raise DeploymentError(msg)
    return passphrase


def check_volumes(layout: Layout, *, is_mount: Callable[[Path], bool] = os.path.ismount) -> None:
    """Refuse to start on a data directory or a keyring the container's layer holds.

    A directory that is not a mount point lives in the container's own writable layer,
    which is deleted with the container. ADR-0326 §3:1 makes every cutover restart the
    hub on the directory it served before, so the data directory has to outlive the
    container, and the keyring holds the credentials the person's connections use.
    The image declares no ``VOLUME``, so no anonymous volume can hide a missing mount.

    Args:
        layout: The image's paths.
        is_mount: Whether a path is a mount point.

    Raises:
        DeploymentError: If either is not a mount point.
    """
    for path, what in ((layout.data_dir, "data directory"), (layout.keyrings, "keyring")):
        if not is_mount(path):
            msg = (
                f"nothing is mounted at {path}, so the {what} would live in this "
                f"container's own layer and be lost when the container is replaced "
                f"(ADR-0326 §3:1). Mount a volume there"
            )
            raise DeploymentError(msg)


def setting(environ: MutableMapping[str, str], name: str) -> str | None:
    """Read one setting the way ``Settings`` reads it: by name, ignoring case.

    Args:
        environ: The environment.
        name: The variable's name.

    Returns:
        The value, or ``None`` where no variable of that name is set.
    """
    wanted = name.casefold()
    for key, value in environ.items():
        if key.casefold() == wanted:
            return value
    return None


def interface_addresses() -> list[tuple[str, str]]:
    """Every IPv4 address this network namespace's interfaces hold.

    Returns:
        ``(interface, address)`` pairs, the loopback interface's among them.
    """
    found: list[tuple[str, str]] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        for _, name in socket.if_nameindex():
            request = struct.pack("256s", name.encode()[:15])
            try:
                reply = fcntl.ioctl(probe.fileno(), _SIOCGIFADDR, request)
            except OSError:
                continue  # an interface with no IPv4 address
            found.append((name, socket.inet_ntoa(reply[20:24])))
    return found


def settle_hosted_address(
    environ: MutableMapping[str, str],
    layout: Layout,
    *,
    addresses: Callable[[], list[tuple[str, str]]] = interface_addresses,
) -> str:
    """Decide what the hosted listener binds, and tell every process in the container.

    ADR-0327 §5:4: a gateway in a network namespace of its own binds its own
    private-use address, and the port is published to the host's loopback alone. The
    container's address is assigned when it starts, so the operator cannot write it
    down beforehand: where the settings name none, it is read here, from the
    namespace's one non-loopback interface, and written to the ``.env`` ``Settings``
    reads from the working directory, for the processes ``docker exec`` starts as well
    as for the children.

    **More than one address is refused rather than chosen among**, and that is also
    what refuses ``--network host``: on the host's own network there is an address for
    each of its interfaces, a public or overlay one among them, and binding any of them
    would let some other machine reach the listener (§5:2).

    Args:
        environ: The environment the children inherit, updated in place.
        layout: The image's paths.
        addresses: The namespace's interface addresses.

    Returns:
        The address the hosted listener binds.

    Raises:
        DeploymentError: If the address configured is a loopback one, or none can be
            read off the namespace unambiguously, or the one read is not private-use.
    """
    configured = setting(environ, HOSTED_ADDRESS)
    if configured is not None and not configured.strip():
        # Not read as unset: the blank stays in the container's own environment, where
        # it outranks the `.env` for every `docker exec`, and `Settings` refuses it.
        msg = (
            f"{HOSTED_ADDRESS} is set but blank. Remove it from the env file, and the "
            f"container binds its own private-use address"
        )
        raise DeploymentError(msg)
    if configured is not None:
        address = configured.strip()
        with contextlib.suppress(ValueError):
            if ipaddress.ip_address(address).is_loopback:
                msg = (
                    f"{HOSTED_ADDRESS}={address} is a loopback address, and a port the "
                    f"runtime publishes reaches the container's own interface, never its "
                    f"loopback (ADR-0327 §5:4). Unset it, and the container binds its own "
                    f"private-use address"
                )
                raise DeploymentError(msg)
        layout.dotenv.unlink(missing_ok=True)
        return address
    held = [(name, address) for name, address in addresses() if not _is_loopback(address)]
    if len(held) != 1:
        listed = ", ".join(f"{address} on {name}" for name, address in held) or "none"
        msg = (
            f"the hosted listener binds this container's own address, and the container "
            f"holds {len(held)} besides loopback ({listed}). Run it on a bridge network, "
            f"never the host's (--network host), or set {HOSTED_ADDRESS} to the one "
            f"address to bind"
        )
        raise DeploymentError(msg)
    name, address = held[0]
    if not any(ipaddress.ip_address(address) in block for block in _PRIVATE_USE):
        msg = (
            f"this container's address {address} on {name} is not a private-use address, "
            f"so the hosted listener may not bind it (ADR-0327 §5:3). Run the container "
            f"on a bridge network, whose addresses are private-use"
        )
        raise DeploymentError(msg)
    environ[HOSTED_ADDRESS] = address
    _write_private(layout.dotenv, f"{HOSTED_ADDRESS}={address}\n")
    return address


def _is_loopback(address: str) -> bool:
    return ipaddress.ip_address(address).is_loopback


def _write_private(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` owner-only, replacing whatever was there."""
    scratch = path.with_name(f"{path.name}.partial")
    descriptor = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    scratch.replace(path)


class _Settings(Protocol):
    """The settings this program reads, as ``ai_assistant.core.config.Settings`` has them."""

    @property
    def data_dir(self) -> Path: ...

    @property
    def gateway_hosted_port(self) -> int: ...


def check_settings(settings: _Settings, layout: Layout) -> None:
    """Refuse settings that would move the data off the volume, or open another door.

    Args:
        settings: The loaded settings.
        layout: The image's paths.

    Raises:
        DeploymentError: If ``data_dir`` is not the volume, or a remote listener or a
            remote hub is configured.
    """
    # `Settings` holds the canonical path (ADR-0083 §2), so the volume's is compared so.
    if settings.data_dir != layout.data_dir.resolve():
        msg = (
            f"ASSISTANT_DATA_DIR is {settings.data_dir}, but the data volume is mounted at "
            f"{layout.data_dir}; anywhere else is the container's own layer (ADR-0326 "
            f"§3:1). Remove ASSISTANT_DATA_DIR from the env file"
        )
        raise DeploymentError(msg)
    configured = [name for name in REMOTE_SETTINGS if getattr(settings, name, None) is not None]
    if configured:
        names = ", ".join(f"ASSISTANT_{name.upper()}" for name in configured)
        msg = (
            f"{names} configured. In this container the gateway reaches the hub over the "
            f"local socket and the hosted listener is the only door; remove them from the "
            f"env file"
        )
        raise DeploymentError(msg)


def load_settings() -> _Settings | None:
    """Load the settings every process here loads, or ``None`` where they do not load.

    Returns:
        The settings, or ``None``: the hub then renders the refusal itself, in its own
        words, and exits ``78`` (ADR-0083 §3 step 1).
    """
    # Imported here, once the environment is settled, and not at the top: the checks
    # above it and the tests of them need no package.
    from ai_assistant.core.config import load_settings as load  # noqa: PLC0415
    from ai_assistant.core.errors import ConfigurationError  # noqa: PLC0415

    try:
        return load()
    except ConfigurationError:
        return None


# --- 2 to 5. The processes ---------------------------------------------------------


class KeyringState(Enum):
    """What the session bus says about the login keyring."""

    ABSENT = "absent"
    LOCKED = "locked"
    UNLOCKED = "unlocked"


#: How long one look at the keyring may take, in seconds, before it counts as "not yet".
_PROBE_DEADLINE: Final = 5.0

#: The flag that runs :func:`ask_the_bus` and prints its answer, for :func:`keyring_state`.
_PROBE_FLAG: Final = "--keyring-state"


def keyring_state(
    *, command: Sequence[str] | None = None, deadline: float = _PROBE_DEADLINE
) -> KeyringState:
    """Look at the keyring from a child process that can be abandoned.

    The bus library's calls take no deadline, so a bus that accepted the connection
    and then stopped answering would hold an in-process look forever: past the
    keyring's own deadline, and past a stop signal, which only sets a flag this
    program reads between looks. A child is killed at ``deadline`` instead, and its
    silence is "not yet".

    Args:
        command: The child's command line, or ``None`` for this program's own
            ``--keyring-state``.
        deadline: How long it may take, in seconds.

    Returns:
        The state, ``ABSENT`` where the child did not answer with one in time.
    """
    argv = command or (sys.executable, "-I", str(Path(__file__).resolve()), _PROBE_FLAG)
    try:
        completed = subprocess.run(  # noqa: S603 — this program's own command line
            argv, capture_output=True, text=True, timeout=deadline, check=False
        )
    except subprocess.TimeoutExpired:
        return KeyringState.ABSENT
    try:
        return KeyringState(completed.stdout.strip())
    except ValueError:
        return KeyringState.ABSENT


def ask_the_bus() -> KeyringState:
    """Ask the session bus whether the default collection is there and unlocked.

    The default collection is the one the ``keyring`` library's SecretService backend
    writes to, and ``gnome-keyring-daemon --unlock`` creates the login keyring that
    answers for it. Run by :func:`keyring_state`'s child, never in the supervisor.

    Returns:
        The state, ``ABSENT`` where the service has not registered on the bus yet.
    """
    import secretstorage  # noqa: PLC0415 — the image's, and only once the bus is up
    from secretstorage.collection import get_collection_by_alias  # noqa: PLC0415
    from secretstorage.exceptions import (  # noqa: PLC0415
        ItemNotFoundException,
        SecretServiceNotAvailableException,
    )

    try:
        connection = secretstorage.dbus_init()
    except SecretServiceNotAvailableException, OSError:
        return KeyringState.ABSENT
    with contextlib.closing(connection):
        try:
            if not secretstorage.check_service_availability(connection):
                return KeyringState.ABSENT
            collection = get_collection_by_alias(connection, "default")
            locked = collection.is_locked()
        except ItemNotFoundException:
            return KeyringState.ABSENT
        except Exception:  # a bus still settling answers in many ways, all of them 'not yet'
            return KeyringState.ABSENT
        return KeyringState.LOCKED if locked else KeyringState.UNLOCKED


def unix_accepts(path: Path) -> bool:
    """Whether something accepts a connection on the Unix socket at ``path``."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        probe.settimeout(2.0)
        try:
            probe.connect(str(path))
        except OSError:
            return False
    return True


def tcp_accepts(address: str, port: int) -> bool:
    """Whether something accepts a TCP connection at ``address``:``port``."""
    try:
        with socket.create_connection((address, port), timeout=2.0):
            return True
    except OSError:
        return False


@dataclass(frozen=True)
class Machine:
    """What this program asks of the machine it runs on. The defaults are the real ones.

    Each is a seam, so that the tests drive the whole sequence with stand-ins.
    """

    addresses: Callable[[], list[tuple[str, str]]] = interface_addresses
    """The namespace's interface addresses."""

    is_mount: Callable[[Path], bool] = os.path.ismount
    """Whether a path is a mount point."""

    settings: Callable[[], _Settings | None] = load_settings
    """Loads the settings, or ``None`` where they do not load."""

    spawn: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen
    """Starts one child."""

    keyring: Callable[[], KeyringState] = keyring_state
    """Reads the keyring's state off the bus."""

    auxiliary_deadline: float = _AUXILIARY_DEADLINE
    """How long the bus and the keyring each have to come up and to go down, in seconds."""

    stop_signals: tuple[signal.Signals, ...] = (signal.SIGTERM, signal.SIGINT)
    """The signals that mean drain and stop, identically (ADR-0083 §4)."""

    ignored_signals: tuple[signal.Signals, ...] = (signal.SIGHUP,)
    """The signals ignored: there is no configuration reload (ADR-0083 §4)."""


@dataclass(frozen=True)
class Commands:
    """The four children's command lines. The defaults are the image's."""

    bus: Sequence[str]
    keyring: Sequence[str]
    hub: Sequence[str]
    gateway: Sequence[str]

    @classmethod
    def for_layout(cls, layout: Layout) -> Commands:
        """The image's command lines, for ``layout``.

        Args:
            layout: The image's paths.

        Returns:
            The commands.
        """
        return cls(
            bus=(
                "dbus-daemon",
                # Not `--session`: the distribution's session configuration would start
                # a second, locked keyring on the first request (session-bus.conf).
                f"--config-file={layout.bus_config}",
                "--nofork",
                "--nopidfile",
                f"--address=unix:path={layout.bus}",
            ),
            keyring=("gnome-keyring-daemon", "--foreground", "--components=secrets", "--unlock"),
            hub=(str(layout.venv_bin / "ai-assistant-hub"),),
            gateway=(str(layout.venv_bin / "assistant"), "gateway"),
        )


class _Outcome(Enum):
    READY = "ready"
    STOP = "stop"
    EXITED = "exited"
    TIMEOUT = "timeout"


@dataclass
class _Child:
    name: str
    process: subprocess.Popen[bytes]
    stop_signal: signal.Signals


class Supervisor:
    """Start the four children in order, watch them, and stop them together."""

    def __init__(  # noqa: PLR0913 — each is a different fact the start needs, all keyword-only
        self,
        layout: Layout,
        *,
        commands: Commands,
        environ: MutableMapping[str, str],
        hosted: tuple[str, int],
        passphrase: bytes,
        machine: Machine,
    ) -> None:
        """Hold what the start needs.

        Args:
            layout: The image's paths.
            commands: The children's command lines.
            environ: The environment every child gets.
            hosted: The hosted listener's address and port.
            passphrase: The keyring passphrase.
            machine: What is asked of the machine.
        """
        self._layout = layout
        self._commands = commands
        self._environ = environ
        self._hosted = hosted
        self._passphrase = passphrase
        self._spawn_one = machine.spawn
        self._keyring = machine.keyring
        self._deadline = machine.auxiliary_deadline
        self._children: list[_Child] = []
        self._stopping = False
        self.exited: _Child | None = None

    def request_stop(self, signum: int, _frame: FrameType | None = None) -> None:
        """Note a stop signal. The first one is acted on; a later one changes nothing.

        Args:
            signum: The signal received.
            _frame: Unused.
        """
        if self._stopping:
            say(f"{signal.Signals(signum).name} received; already stopping")
            return
        say(f"{signal.Signals(signum).name} received; stopping the gateway and the hub")
        self._stopping = True

    def serve(self) -> int:
        """Start, watch and stop the children.

        **A fault is said after everything has stopped**, so that it is the last line
        of the log: once the hub has started, stopping it writes its drain after
        anything said before it, and ADR-0083 §5 has every ``78`` end on its cause
        and the operator action.

        Returns:
            The container's exit code (ADR-0083 §5).
        """
        self._layout.ready.unlink(missing_ok=True)
        said: str | None = None
        try:
            code = self._run()
        except _StopRequestedError:
            code = EXIT_OK
        except DeploymentError as fault:
            said = f"{fault} (exit {EXIT_DEPLOYMENT})"
            code = EXIT_DEPLOYMENT
        except StartError as fault:
            said = f"{fault} (exit {EXIT_RESTART})"
            code = EXIT_RESTART
        finally:
            self._layout.ready.unlink(missing_ok=True)
            self._stop_everything()
        if said is not None:
            say(said)
        hub = next((c.process.returncode for c in self._children if c.name == "hub"), None)
        return code if hub is None else _settle(code, hub)

    def _run(self) -> int:
        self._start_keyring()
        hub = self._start("hub", self._commands.hub, signal.SIGTERM)
        # ADR-0084 §9: `<data_dir>/hub.sock`, as `ai_assistant.wire.address` derives it.
        socket_path = self._layout.data_dir / "hub.sock"
        outcome = self._wait(lambda: unix_accepts(socket_path))
        if outcome is not _Outcome.READY:
            return self._ended(outcome)
        say(f"the hub accepts on {socket_path}")
        gateway = self._start("gateway", self._commands.gateway, signal.SIGINT)
        address, port = self._hosted
        outcome = self._wait(lambda: tcp_accepts(address, port))
        if outcome is _Outcome.EXITED and self.exited is gateway:
            self._gateway_did_not_start(gateway, address, port)
        if outcome is not _Outcome.READY:
            return self._ended(outcome)
        _write_private(self._layout.ready, f"{hub.process.pid} {gateway.process.pid}\n")
        say(f"ready: the gateway's hosted listener accepts on {address}:{port}")
        return self._ended(self._wait(lambda: False))

    def _gateway_did_not_start(self, gateway: _Child, address: str, port: int) -> None:
        """Report a gateway that exited before its hosted listener ever accepted.

        **Its ``78`` is the container's ``78``.** ``assistant gateway`` uses ADR-0083
        §5's codes as the hub does (#3167): it exits ``78`` for a refusal restarting
        unchanged never gets past — a setting it refused, an edge key that will not
        load, a hosted address this container does not hold — after printing the
        cause and what to change, and ``1`` for a fault that may clear. So a ``78``
        here is a deployment to fix, and restarting the container would only meet the
        same refusal again.

        **Every other status is a ``1``**: the gateway's own ``1``, a signal, or a
        code it does not use. §5's tie-break is the reason — "a spurious restart is
        recoverable and a spurious ``78`` is an outage".

        Args:
            gateway: The gateway, which has exited.
            address: The hosted address it was to bind.
            port: The hosted port.

        Raises:
            DeploymentError: If the gateway exited ``78``.
            StartError: Otherwise.
        """
        status = gateway.process.returncode
        if status == EXIT_DEPLOYMENT:
            msg = (
                f"the gateway refused to start before its hosted listener accepted on "
                f"{address}:{port}. Its own message above names what to change; the "
                f"container starts once that is changed"
            )
            raise DeploymentError(msg)
        msg = (
            f"the gateway exited {status} before its hosted listener accepted on "
            f"{address}:{port}; its own message above says why"
        )
        raise StartError(msg)

    def _start_keyring(self) -> None:
        self._layout.bus.unlink(missing_ok=True)
        self._start("dbus-daemon", self._commands.bus, signal.SIGTERM)
        if self._wait(self._layout.bus.exists, deadline=self._deadline) is not _Outcome.READY:
            self._auxiliary_failed("the session bus")
        keyring = self._start(
            "gnome-keyring-daemon", self._commands.keyring, signal.SIGTERM, stdin=True
        )
        stdin = keyring.process.stdin
        if stdin is not None:
            with contextlib.suppress(BrokenPipeError):
                stdin.write(self._passphrase)
            with contextlib.suppress(BrokenPipeError):
                stdin.close()
        states: list[KeyringState] = []

        def registered() -> bool:
            states.append(self._keyring())
            return states[-1] is not KeyringState.ABSENT

        if self._wait(registered, deadline=self._deadline) is not _Outcome.READY:
            self._auxiliary_failed("the keyring")
        if states[-1] is KeyringState.LOCKED:
            msg = (
                f"the passphrase at {self._layout.passphrase} does not unlock the login "
                f"keyring in the keyring volume at {self._layout.keyrings}. Mount the "
                f"passphrase that keyring was created with"
            )
            raise DeploymentError(msg)
        say("the keyring is unlocked")

    def _auxiliary_failed(self, what: str) -> None:
        if self._stopping:
            raise _StopRequestedError
        if self.exited is not None:
            msg = f"{self.exited.name} exited with {self.exited.process.returncode}"
            raise StartError(msg)
        msg = f"{what} did not come up within {self._deadline:g} seconds"
        raise StartError(msg)

    def _start(
        self, name: str, args: Sequence[str], stop_signal: signal.Signals, *, stdin: bool = False
    ) -> _Child:
        if self._stopping:
            raise _StopRequestedError
        process = self._spawn_one(
            args,
            stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
            env=self._environ,
            cwd=self._layout.runtime_dir,
            # Its own process group, so a terminal's Ctrl-C reaches this program and
            # not each child behind its back: one decision about stopping, made here.
            process_group=0,
        )
        child = _Child(name=name, process=process, stop_signal=stop_signal)
        self._children.append(child)
        return child

    def _wait(self, ready: Callable[[], bool], *, deadline: float | None = None) -> _Outcome:
        """Wait for ``ready``, a stop, or a child's exit, whichever comes first."""
        give_up = None if deadline is None else time.monotonic() + deadline
        while True:
            if self._stopping:
                return _Outcome.STOP
            for child in self._children:
                if child.process.poll() is not None:
                    self.exited = child
                    return _Outcome.EXITED
            if ready():
                return _Outcome.READY
            if give_up is not None and time.monotonic() >= give_up:
                return _Outcome.TIMEOUT
            time.sleep(_POLL)

    def _ended(self, outcome: _Outcome) -> int:
        """The run's own exit code where it ended on ``outcome`` rather than on a fault.

        A stop is ``0``, and so is the hub's own exit: the hub's status then decides,
        through :func:`_settle`, exactly as it would have outside a container. Any
        other child stopping unasked is a ``1``.
        """
        child = self.exited
        if outcome is _Outcome.STOP:
            return EXIT_OK
        if child is not None:
            say(f"{child.name} exited with {child.process.returncode}; stopping the rest")
            if child.name == "hub":
                return EXIT_OK
        return EXIT_RESTART

    def _signal(self, child: _Child) -> bool:
        """Send ``child`` its stop signal if it is still running; say whether it was."""
        if child.process.poll() is not None:
            return False
        with contextlib.suppress(ProcessLookupError):
            child.process.send_signal(child.stop_signal)
        return True

    def _stop_everything(self) -> None:
        """Stop the gateway and the hub together, then the keyring and the bus.

        The gateway and the hub are waited on with no deadline: the hub's drain is
        ADR-0083 §4's to bound, and the runtime's stop timeout is the backstop (D2).
        The bus and the keyring hold nothing that outlives them, so they are given a
        deadline and then killed.
        """
        principals = [child for child in self._children if child.name in {"hub", "gateway"}]
        for child in principals:
            self._signal(child)
        for child in principals:
            child.process.wait()
        for child in reversed(self._children):
            if child in principals:
                continue
            self._signal(child)
            try:
                child.process.wait(timeout=self._deadline)
            except subprocess.TimeoutExpired:
                child.process.kill()
                child.process.wait()


class _StopRequestedError(Exception):
    """A stop arrived between two starts; nothing further is started."""


def _settle(code: int, hub: int) -> int:
    """Combine the run's own exit code with the hub's.

    A hub that said ``78`` keeps it whatever else happened, and a hub that drained to
    ``0`` after a stop keeps the stop's ``0``; a hub that ended any other way asks to
    be started again (ADR-0083 §5).

    Args:
        code: The run's own code, from the faults and the outcome.
        hub: The hub's exit status, negative where a signal ended it.

    Returns:
        The container's exit code.
    """
    if hub == EXIT_DEPLOYMENT:
        return EXIT_DEPLOYMENT
    if code != EXIT_OK:
        return code
    return EXIT_OK if hub == EXIT_OK else EXIT_RESTART


def run(
    layout: Layout,
    environ: MutableMapping[str, str],
    *,
    machine: Machine | None = None,
    commands: Commands | None = None,
) -> int:
    """Check the deployment, then supervise the children until they stop.

    Args:
        layout: The image's paths.
        environ: The environment, updated in place with the hosted address.
        machine: What is asked of the machine, or ``None`` for the real one.
        commands: The children's command lines, or ``None`` for the image's.

    Returns:
        The container's exit code (ADR-0083 §5).
    """
    machine = machine or Machine()
    commands = commands or Commands.for_layout(layout)
    try:
        passphrase = read_passphrase(layout.passphrase)
        check_volumes(layout, is_mount=machine.is_mount)
        address = settle_hosted_address(environ, layout, addresses=machine.addresses)
        loaded = machine.settings()
        if loaded is None:
            say("the settings do not load; the hub says why")
            return _hub_alone(commands, environ, layout)
        check_settings(loaded, layout)
    except DeploymentError as fault:
        say(f"{fault} (exit {EXIT_DEPLOYMENT})")
        return EXIT_DEPLOYMENT
    supervisor = Supervisor(
        layout,
        commands=commands,
        environ=environ,
        hosted=(address, loaded.gateway_hosted_port),
        passphrase=passphrase,
        machine=machine,
    )
    for signum in machine.stop_signals:
        signal.signal(signum, supervisor.request_stop)
    for signum in machine.ignored_signals:
        signal.signal(signum, signal.SIG_IGN)
    return supervisor.serve()


def _hub_alone(commands: Commands, environ: MutableMapping[str, str], layout: Layout) -> int:
    """Run the hub by itself, so that it renders a settings refusal in its own words."""
    completed = subprocess.run(  # noqa: S603 — the image's own command line, no shell
        commands.hub, env=environ, cwd=layout.runtime_dir, check=False
    )
    return _settle(EXIT_OK, completed.returncode)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the container.

    Args:
        argv: The arguments, or ``None`` for the process's. There are none an
            operator passes; ``--keyring-state`` is :func:`keyring_state`'s child.

    Returns:
        The container's exit code.
    """
    parser = argparse.ArgumentParser(
        prog="supervise.py",
        description="Supervise one person's hub and its gateway in their container.",
    )
    parser.add_argument(_PROBE_FLAG, action="store_true", help=argparse.SUPPRESS)
    if parser.parse_args(argv).keyring_state:
        print(ask_the_bus().value)
        return EXIT_OK
    return run(Layout(), os.environ)


if __name__ == "__main__":
    sys.exit(main())
