"""Drive the container deploy path on this machine, as the container workflow does (#3160).

    uv run --no-project --with cryptography python deploy/container/deploy_smoke.py

It runs on a GitHub runner: Docker, a running systemd and passwordless ``sudo``, from a
clean checkout. It plays the operator, writing one person's directory by hand as
``docs/guide/container.md`` says, and deploys that person to this machine with
``scripts/deploy_container.py --local``, three times over three commits. Everything it
makes is the person ``ci``'s, under ``/srv/hubs/ci``, and is removed at the end.

What it proves, in order:

0. **A first install killed outright resumes** (#3185). The deploy is killed with
   ``SIGKILL`` once it says it has recorded the install, mid-way through making the
   volumes and ``unit.env``; the lock it held is free again at once, and the first
   install below, run again over what it left, finishes.
1. **A first install.** The unit starts the image the deploy built, the door refuses an
   unsigned request and serves a signed one, and an admin act and a keyring write land.
2. **An upgrade.** The deploy backs the volume up before the new image runs, the artifact
   restores, and the conversation and the keyring entry are there on the new image.
3. **A failed backup.** A stray SQLite sidecar in the data volume makes the backup refuse;
   the deploy fails, ``unit.env`` is as it was, and the earlier image is running, healthy.
4. **The unit is the supervisor ADR-0083's D1 asks for.** A container killed outright is
   started again; one that exits ``78`` (the wrong keyring passphrase) is left down; a
   stop drains to ``0``.
5. **A relayed hub resolves the relay** (ADR-0330 §8:2). With the relay's settings in
   ``hub.env``, a deploy without ``--relay-address`` is refused and changes nothing, and
   one with it runs a container that resolves the relay's host to that address. No
   relay listens there: resolution is what the deploy owes, and the direct hub of step
   1 resolves no such name.
"""

from __future__ import annotations

import http.client
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke import AUDIENCE, HOST_NAME, ISSUER, SUBJECT, Edge

if TYPE_CHECKING:
    from collections.abc import Sequence

REPO: Final = Path(__file__).resolve().parents[2]
DEPLOY: Final = REPO / "scripts" / "deploy_container.py"
PERSON: Final = "ci"
SUDO: Final = shutil.which("sudo") or "/usr/bin/sudo"
GIT: Final = shutil.which("git") or "/usr/bin/git"
PORT: Final = 18501
DIRECTORY: Final = Path("/srv/hubs") / PERSON
UNIT: Final = f"hub@{PERSON}.service"
CONTAINER: Final = f"hub-{PERSON}"
CONTAINER_UID: Final = "10001"
DEADLINE: Final = 600.0
#: The deploy's line once a first install has recorded itself and is making its volumes.
RECORDED: Final = "; making its volumes"
_CONVERSATION: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_KEYRING_WRITE: Final = (
    "from ai_assistant.secret_store import select_backend as s; "
    "s().set_password('deploy-smoke', 'probe', 'carried')"
)
#: Where the relay listens on the private repository's box, and its origin there.
RELAY_ADDRESS: Final = "10.254.0.1"
RELAY_HOST: Final = "telegram-relay"
#: A CA certificate for the relay's settings, which the hub loads at start (ADR-0330
#: §3:8): tests/app/test_composition_telegram_relay.py's, as nothing here dials it.
RELAY_CA: Final = (
    "-----BEGIN CERTIFICATE-----"
    "MIIBfTCCASOgAwIBAgIUVBNdEQURzbiRkUNtd9FKXpiqROkwCgYIKoZIzj0EAwIw"
    "GzEZMBcGA1UEAwwQRXhhbXBsZSBSZWxheSBDQTAeFw0yNjEwMTkwMDAwMDBaFw0z"
    "NjEwMTYwMDAwMDBaMBsxGTAXBgNVBAMMEEV4YW1wbGUgUmVsYXkgQ0EwWTATBgcq"
    "hkjOPQIBBggqhkjOPQMBBwNCAATLIYTcOBiLZXvnSdy9Ce/9GnVvplpNdlezdpAM"
    "bcben+U/yVbz+KAWeaeHaVN3AI6iseuT/BwUAeh710TXUWnWo0UwQzASBgNVHRMB"
    "Af8ECDAGAQH/AgEAMA4GA1UdDwEB/wQEAwIBBjAdBgNVHQ4EFgQUrhyCO524DfbQ"
    "rJ+pjaVMzcCtBpcwCgYIKoZIzj0EAwIDSAAwRQIgIHw06X8kxeupJqfPwjMzL7l0"
    "qogQOM3T9lHgnxRu7mQCIQCY4s5g3sYKk3LN4ToEodOoIUGyONE0iAJYZVNdlhG6"
    "JA=="
    "-----END CERTIFICATE-----"
)
_KEYRING_READ: Final = (
    "from ai_assistant.secret_store import select_backend as s; "
    "print(s().get_password('deploy-smoke', 'probe'))"
)


class SmokeError(Exception):
    """A check failed."""


def step(text: str) -> None:
    """Say which check is running."""
    print(f"deploy-smoke: {text}", flush=True)


def root(*argv: str, stdin: bytes | None = None, check: bool = True) -> str:
    """Run one command as root, as the operator does on the box.

    Args:
        *argv: The command.
        stdin: What to feed it.
        check: Whether a non-zero exit is a failure.

    Returns:
        What it printed.

    Raises:
        SmokeError: If ``check`` and it exited non-zero.
    """
    completed = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [SUDO, "-n", "--", *argv], input=stdin, capture_output=True, check=False
    )
    if check and completed.returncode != 0:
        msg = f"{' '.join(argv)} exited {completed.returncode}:\n{completed.stderr.decode()}"
        raise SmokeError(msg)
    return completed.stdout.decode()


def deploy(*extra: str) -> subprocess.CompletedProcess[str]:
    """Run the deploy, as the operator would, and show what it said.

    Args:
        *extra: Arguments after the person and ``--local``.

    Returns:
        The completed process.
    """
    completed = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, str(DEPLOY), PERSON, "--local", *extra],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    print(completed.stderr + completed.stdout, flush=True)
    return completed


def commit(message: str) -> str:
    """Make an empty commit, so the next deploy builds a new release, and return it."""
    subprocess.run(  # noqa: S603 — fixed argv, no shell
        [
            GIT,
            "-c",
            "user.name=deploy-smoke",
            "-c",
            "user.email=deploy-smoke@example.invalid",
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            message,
        ],
        cwd=REPO,
        check=True,
    )
    return subprocess.run(  # noqa: S603 — fixed argv, no shell
        [GIT, "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def unit_state() -> dict[str, str]:
    """The unit's state, as ``systemctl show`` gives it."""
    out = root("systemctl", "show", UNIT, "--property=ActiveState,ExecMainStatus,NRestarts")
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def running_image() -> str:
    """The image id the person's container runs."""
    return root("docker", "container", "inspect", "--format", "{{.Image}}", CONTAINER).strip()


def await_healthy() -> None:
    """Wait for the person's container to be healthy.

    Raises:
        SmokeError: If it is not within the deadline.
    """
    give_up = time.monotonic() + DEADLINE
    while time.monotonic() < give_up:
        health = root(
            "docker",
            "container",
            "inspect",
            "--format",
            "{{.State.Health.Status}}",
            CONTAINER,
            check=False,
        ).strip()
        if health == "healthy":
            return
        time.sleep(2)
    msg = f"{CONTAINER} was not healthy within {DEADLINE:g} seconds"
    raise SmokeError(msg)


def await_state(active: str, *, seconds: float = 120.0) -> dict[str, str]:
    """Wait for the unit to reach ``active``, and return its state then.

    Raises:
        SmokeError: If it does not.
    """
    give_up = time.monotonic() + seconds
    while time.monotonic() < give_up:
        state = unit_state()
        if state.get("ActiveState") == active:
            return state
        time.sleep(1)
    msg = f"{UNIT} did not become {active}: {unit_state()}"
    raise SmokeError(msg)


def get(path: str, *, assertion: str | None) -> int:
    """GET ``path`` from the person's loopback port, as the edge forwards it.

    Returns:
        The status.
    """
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    headers = {"Host": HOST_NAME}
    if assertion is not None:
        headers["Edge-Assertion"] = assertion
    try:
        connection.request("GET", path, headers=headers)
        return connection.getresponse().status
    finally:
        connection.close()


def exec_in(*argv: str) -> str:
    """Run an admin act in the person's container.

    Returns:
        What it printed.
    """
    return root("docker", "exec", CONTAINER, *argv)


def resolved(host: str) -> str:
    """What the person's container resolves ``host`` to, or ``""`` if nothing."""
    out = root("docker", "exec", CONTAINER, "getent", "hosts", host, check=False)
    return out.split()[0] if out.split() else ""


def backups() -> list[str]:
    """The artifacts in the person's backup directory."""
    out = root(
        "find", str(DIRECTORY / "backups"), "-name", "*.age", "-printf", "%f\\n", check=False
    )
    return sorted(out.split())


class Run:
    """The run's person, its edge key and what it wrote."""

    def __init__(self) -> None:
        """Make the edge's key."""
        self.edge = Edge()
        self.conversation = ""
        self.env = ""

    def write_person(self) -> None:
        """Write the person's directory as the operator does, by hand."""
        self.env = "\n".join(
            (
                "ANTHROPIC_API_KEY=sk-ant-deploy-smoke-not-a-key",
                f"ASSISTANT_GATEWAY_HOSTED_HOST_NAME={HOST_NAME}",
                "ASSISTANT_GATEWAY_HOSTED_DEVICE=smoke-browser",
                f"ASSISTANT_GATEWAY_EDGE_PUBLIC_KEYS={self.edge.public}",
                f"ASSISTANT_GATEWAY_EDGE_ISSUER={ISSUER}",
                f"ASSISTANT_GATEWAY_EDGE_AUDIENCE={AUDIENCE}",
                f"ASSISTANT_GATEWAY_EDGE_SUBJECT={SUBJECT}",
                "",
            )
        )
        root("install", "-d", "-m", "0755", str(DIRECTORY.parent))
        root("install", "-d", "-m", "0700", str(DIRECTORY))
        self.write_env(self.env)
        for name in ("keyring-passphrase", "backup-passphrase"):
            self.passphrase(name, secrets.token_urlsafe(24))

    def write_env(self, env: str) -> None:
        """Write the person's ``hub.env``, the model key's file."""
        root("install", "-m", "0600", "/dev/stdin", str(DIRECTORY / "hub.env"), stdin=env.encode())

    def passphrase(self, name: str, value: str) -> None:
        """Write one passphrase file, the container user's alone."""
        root(
            "install",
            "-m",
            "0400",
            "-o",
            CONTAINER_UID,
            "-g",
            CONTAINER_UID,
            "/dev/stdin",
            str(DIRECTORY / name),
            stdin=f"{value}\n".encode(),
        )

    def check_door(self) -> None:
        """The door refuses an unsigned request and serves a signed one.

        Raises:
            SmokeError: If either does not hold.
        """
        unsigned = get("/", assertion=None)
        signed = get("/", assertion=self.edge.assertion())
        if (unsigned, signed) != (403, 200):
            msg = f"the door answered {unsigned} unsigned and {signed} signed, not 403 and 200"
            raise SmokeError(msg)

    def check_carried(self) -> None:
        """The conversation and the keyring entry are still there.

        Raises:
            SmokeError: If either is gone.
        """
        if self.conversation not in exec_in("assistant", "conversations"):
            msg = f"the conversation {self.conversation} is gone"
            raise SmokeError(msg)
        carried = exec_in("python", "-c", _KEYRING_READ).strip()
        if carried != "carried":
            msg = f"the keyring entry is {carried!r}, not 'carried'"
            raise SmokeError(msg)

    def killed_first_install(self) -> None:
        """Kill a first install outright once it has recorded itself.

        Raises:
            SmokeError: If it ended before that, or its lock outlived it.
        """
        step("a first install killed outright once it has recorded itself")
        process = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
            [sys.executable, str(DEPLOY), PERSON, "--local", "--port", str(PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            cwd=REPO,
        )
        assert process.stderr is not None  # noqa: S101 — a pipe, asked for above
        for line in process.stderr:
            print(line, end="", flush=True)
            if RECORDED in line:
                process.kill()
                break
        process.wait()
        process.stderr.close()
        if process.returncode != -signal.SIGKILL:
            msg = f"the deploy ended (exit {process.returncode}) before it recorded the install"
            raise SmokeError(msg)
        step(f"it left: {' '.join(root('ls', '-A', str(DIRECTORY)).split())}")
        lock = DIRECTORY / ".deploy-lock"
        try:
            # Its holder ends once it reads the end of the dead deploy's pipe.
            root("flock", "--wait", "10", "--", str(lock), "true")
        except SmokeError as exc:
            msg = f"the killed deploy's lock on {lock} was not released"
            raise SmokeError(msg) from exc

    def first_install(self) -> None:
        """Deploy a person with nothing on the box yet, or what a killed install left."""
        step("a first install")
        if deploy("--port", str(PORT)).returncode != 0:
            msg = "the first install failed"
            raise SmokeError(msg)
        if ".first-install" in root("ls", "-A", str(DIRECTORY)).split():
            msg = "the first install left its record"
            raise SmokeError(msg)
        if backups():
            msg = f"a first install took a backup: {backups()}"
            raise SmokeError(msg)
        self.check_door()
        if resolved(RELAY_HOST):
            msg = f"a direct hub's container resolves {RELAY_HOST} to {resolved(RELAY_HOST)}"
            raise SmokeError(msg)
        started = _CONVERSATION.search(exec_in("assistant", "start-conversation"))
        if started is None:
            msg = "assistant start-conversation printed no conversation id"
            raise SmokeError(msg)
        self.conversation = started.group()
        exec_in("python", "-c", _KEYRING_WRITE)

    def upgrade(self) -> None:
        """Deploy a later release over the first, carrying the data."""
        step("an upgrade backs up, verifies and carries the data across")
        earlier = running_image()
        release = commit("deploy-smoke: a later release")
        if deploy().returncode != 0:
            msg = "the upgrade failed"
            raise SmokeError(msg)
        artifacts = backups()
        if len(artifacts) != 1:
            msg = f"the upgrade left {artifacts}, not one artifact"
            raise SmokeError(msg)
        now = running_image()
        label = root(
            "docker",
            "image",
            "inspect",
            "--format",
            '{{index .Config.Labels "org.opencontainers.image.revision"}}',
            now,
        ).strip()
        if now == earlier or label != release:
            msg = f"the container runs {now} labelled {label}, not a build of {release}"
            raise SmokeError(msg)
        self.check_carried()
        self.check_door()
        step("the artifact restores")
        root(
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--volume",
            f"{DIRECTORY / 'backups'}:/backups:ro",
            "--volume",
            f"{DIRECTORY / 'backup-passphrase'}:/run/secrets/backup-passphrase:ro",
            "--entrypoint",
            "/opt/assistant/venv/bin/ai-assistant-restore",
            now,
            f"/backups/{artifacts[0]}",
            "/home/assistant/restored",
            "--passphrase-file",
            "/run/secrets/backup-passphrase",
        )

    def failed_backup(self) -> None:
        """A backup that refuses leaves the earlier image running."""
        step("a failed backup leaves the earlier image running")
        earlier = running_image()
        recorded = root("cat", str(DIRECTORY / "unit.env"))
        exec_in("sh", "-c", ": > /data/deploy-smoke.db-wal")
        commit("deploy-smoke: a release whose deploy cannot back up")
        try:
            completed = deploy()
        finally:
            exec_in("rm", "-f", "/data/deploy-smoke.db-wal")
        said = completed.stderr
        if completed.returncode == 0 or "ai-assistant-backup failed" not in said:
            msg = f"the deploy did not fail on its backup (exit {completed.returncode})"
            raise SmokeError(msg)
        if "started again on its earlier image" not in said:
            msg = "the deploy did not report the earlier image started again"
            raise SmokeError(msg)
        if root("cat", str(DIRECTORY / "unit.env")) != recorded:
            msg = "unit.env changed although the backup failed"
            raise SmokeError(msg)
        if running_image() != earlier or unit_state().get("ActiveState") != "active":
            msg = f"the container runs {running_image()}, not the earlier {earlier}"
            raise SmokeError(msg)
        await_healthy()
        self.check_carried()

    def supervisor(self) -> None:
        """Restart on a crash, stay down on 78, and drain to 0 on a stop."""
        step("a container killed outright is started again")
        before = int(unit_state().get("NRestarts", "0"))
        root("docker", "kill", "--signal", "KILL", CONTAINER)
        give_up = time.monotonic() + 120
        while int(unit_state().get("NRestarts", "0")) == before:
            if time.monotonic() > give_up:
                msg = f"{UNIT} was not restarted after its container was killed"
                raise SmokeError(msg)
            time.sleep(1)
        await_healthy()

        step("a container that exits 78 is left down")
        root("systemctl", "stop", UNIT)
        right = root("cat", str(DIRECTORY / "keyring-passphrase"))
        self.passphrase("keyring-passphrase", "not-the-passphrase")
        root("systemctl", "reset-failed", UNIT, check=False)
        root("systemctl", "start", UNIT)
        state = await_state("failed")
        time.sleep(15)
        later = unit_state()
        if state.get("ExecMainStatus") != "78" or later.get("ActiveState") != "failed":
            msg = f"a 78 was not left down: {state} then {later}"
            raise SmokeError(msg)
        if later.get("NRestarts") != "0":
            msg = f"a 78 was restarted: {later}"
            raise SmokeError(msg)
        self.passphrase("keyring-passphrase", right.removesuffix("\n"))

        step("a stop drains to 0")
        root("systemctl", "reset-failed", UNIT, check=False)
        root("systemctl", "start", UNIT)
        await_healthy()
        root("systemctl", "stop", UNIT)
        # Inactive, not failed: systemd counts the docker client's 0, or the SIGTERM it
        # sends a client still exiting after `docker stop`, as a clean end.
        state = await_state("inactive")
        step(f"stopped: {state}")

    def relayed(self) -> None:
        """A relayed hub is refused without the relay's address, and resolves it with one."""
        step("a relayed hub without the relay's address is refused")
        self.write_env(
            self.env
            + "ASSISTANT_TELEGRAM_CONNECTION=conn-relay\n"
            + "ASSISTANT_TELEGRAM_USER_ID=424242\n"
            + f"ASSISTANT_TELEGRAM_RELAY_ORIGIN=https://{RELAY_HOST}:8443\n"
            + f"ASSISTANT_TELEGRAM_RELAY_CERTIFICATES={RELAY_CA}\n"
        )
        recorded = root("cat", str(DIRECTORY / "unit.env"))
        refused = deploy()
        if refused.returncode == 0 or "Pass --relay-address" not in refused.stderr:
            msg = f"a relayed hub with no relay address was not refused ({refused.returncode})"
            raise SmokeError(msg)
        if root("cat", str(DIRECTORY / "unit.env")) != recorded:
            msg = "unit.env changed although the deploy was refused"
            raise SmokeError(msg)

        step(f"a relayed hub's container resolves {RELAY_HOST} to {RELAY_ADDRESS}")
        if deploy("--relay-address", RELAY_ADDRESS).returncode != 0:
            msg = "the relayed deploy failed"
            raise SmokeError(msg)
        if resolved(RELAY_HOST) != RELAY_ADDRESS:
            msg = f"the container resolves {RELAY_HOST} to {resolved(RELAY_HOST) or 'nothing'}"
            raise SmokeError(msg)
        self.check_door()
        self.check_carried()

    def run(self) -> None:
        """Every check, in order."""
        step(f"Docker {root('docker', 'version', '--format', '{{.Server.Version}}').strip()}")
        self.write_person()
        self.killed_first_install()
        self.first_install()
        print(root("iptables", "-t", "raw", "-S", "PREROUTING"), flush=True)
        self.upgrade()
        self.failed_backup()
        self.supervisor()
        self.relayed()

    def clean(self) -> None:
        """Show the unit's journal and the raw table, and remove the person from the box."""
        print(root("iptables", "-t", "raw", "-S", check=False), flush=True)
        print(root("journalctl", "--unit", UNIT, "--no-pager", "--lines", "200", check=False))
        root("systemctl", "disable", "--now", UNIT, check=False)
        root("docker", "rm", "--force", CONTAINER, check=False)
        root("docker", "volume", "rm", "--force", f"hub-{PERSON}-data", check=False)
        root("docker", "volume", "rm", "--force", f"hub-{PERSON}-keyring", check=False)
        root("docker", "network", "rm", f"hub-{PERSON}", check=False)
        root("rm", "-rf", "--", str(DIRECTORY), check=False)


def main(argv: Sequence[str]) -> int:
    """Run every check.

    Args:
        argv: No arguments.

    Returns:
        ``0`` when every check passed, ``1`` otherwise.
    """
    if argv or os.geteuid() == 0:
        print("usage: deploy_smoke.py, as a user with passwordless sudo", file=sys.stderr)
        return 2
    run = Run()
    try:
        run.run()
    except SmokeError as failure:
        print(f"deploy-smoke: FAILED: {failure}", file=sys.stderr, flush=True)
        return 1
    finally:
        run.clean()
    print("deploy-smoke: every check passed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
