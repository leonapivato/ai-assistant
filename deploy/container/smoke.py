"""Drive a built hub image end to end, as the container workflow does (#3142).

    uv run --no-project --with cryptography python deploy/container/smoke.py IMAGE

It needs a container runtime and nothing of this repository's environment: the one
library it takes is ``cryptography``, to sign an assertion as the sign-in edge would
(ADR-0327 §6). Everything it creates is named ``hub-smoke-<this run's suffix>`` and
removed at the end, and nothing it did not create is.

What it proves, in order:

1. **Readiness on a fresh volume.** The container reports healthy, which it does only
   once the hub's socket and the gateway's hosted listener both accept.
2. **The gateway answers on the published port, and only there.** The port is
   published to the host's loopback alone; a request without an assertion is refused
   with ``403``, and one the edge's key signed is served the page.
3. **The admin acts run through ``exec``.** ``ai-assistant-device list`` reaches the
   hub's admin socket, ``assistant start-conversation`` writes a conversation over the
   local socket, and the secret store's own backend selection finds the SecretService
   keyring and writes to it, as ``assistant connect`` would.
4. **A restart carries the data**, two ways: ``restart`` of the same container, and a
   new container on the same volumes, which is what an image upgrade is. Each time
   the conversation and the keyring entry are still there.
5. **A stop drains to ``0``, and a deployment fault is ``78``**: no passphrase, a data
   directory moved off the volume, no data volume, the wrong passphrase for the
   keyring, and the host's own network.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

RUNTIME: Final = os.environ.get("CONTAINER_RUNTIME", "docker")
#: This run's own suffix, so two runs on one machine never name, or remove, each
#: other's container and volumes.
_RUN: Final = secrets.token_hex(4)
NAME: Final = f"hub-smoke-{_RUN}"
DATA: Final = f"hub-smoke-{_RUN}-data"
KEYRING: Final = f"hub-smoke-{_RUN}-keyring"
PORT: Final = 18423
HOST_NAME: Final = "hub.smoke.test"
ISSUER: Final = "https://edge.smoke.test"
AUDIENCE: Final = "hub-smoke"
SUBJECT: Final = "account-smoke"
#: A conversation's id, as ``assistant start-conversation`` prints it.
_CONVERSATION: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
READY_DEADLINE: Final = 600.0
EXIT_DEPLOYMENT: Final = 78

#: The secret store's own backend selection, and a write and a read through it. The
#: module path is the point: ADR-0125 §7's allow-list admits SecretService.
_KEYRING_WRITE: Final = (
    "from ai_assistant.secret_store import select_backend as s; b = s(); "
    "print(type(b).__module__); b.set_password('hub-smoke', 'probe', 'carried')"
)
_KEYRING_READ: Final = (
    "from ai_assistant.secret_store import select_backend as s; "
    "print(s().get_password('hub-smoke', 'probe'))"
)


class SmokeError(Exception):
    """A check failed."""


def runtime(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one runtime command and return what it printed.

    Args:
        *args: The arguments after the runtime's name.
        check: Whether a non-zero exit is a failure.

    Returns:
        The completed process.

    Raises:
        SmokeError: If ``check`` and it exited non-zero.
    """
    completed = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [RUNTIME, *args], capture_output=True, text=True, check=False
    )
    if check and completed.returncode != 0:
        msg = f"{RUNTIME} {' '.join(args)} exited {completed.returncode}:\n{completed.stderr}"
        raise SmokeError(msg)
    return completed


def step(text: str) -> None:
    """Say which check is running."""
    print(f"smoke: {text}", flush=True)


class Edge:
    """The sign-in edge's part: a key, and assertions signed with it (ADR-0327 §6)."""

    def __init__(self) -> None:
        """Make a fresh key."""
        self._key = Ed25519PrivateKey.generate()

    @property
    def public(self) -> str:
        """The public key in the form the gateway's setting takes: RFC 8037's ``x``."""
        raw = self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return _segment(raw)

    def assertion(self) -> str:
        """One assertion for this hub's account, valid for thirty seconds from now."""
        now = int(time.time())
        header = {"alg": "EdDSA", "typ": "JWT"}
        claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": SUBJECT, "iat": now, "exp": now + 30}
        signing = f"{_json_segment(header)}.{_json_segment(claims)}"
        return f"{signing}.{_segment(self._key.sign(signing.encode('ascii')))}"


def _segment(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _json_segment(value: Mapping[str, object]) -> str:
    return _segment(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def get(path: str, *, assertion: str | None) -> tuple[int, bytes]:
    """GET ``path`` from the published port, as the edge would forward it.

    Args:
        path: The request path.
        assertion: The ``Edge-Assertion`` header's value, or ``None`` for none.

    Returns:
        The status and the body.
    """
    connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    headers = {"Host": HOST_NAME}
    if assertion is not None:
        headers["Edge-Assertion"] = assertion
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


class Smoke:
    """The run: its files, its volumes, and the containers it starts."""

    def __init__(self, image: str, work: Path) -> None:
        """Write the env file and the passphrase.

        Args:
            image: The image to drive.
            work: A scratch directory for the env file and the passphrase.
        """
        self.image = image
        self.edge = Edge()
        self.conversation = ""
        self.env_file = work / "hub.env"
        self.env_file.write_text(
            "\n".join(
                (
                    # The hub refuses to start with no credential for its model; nothing
                    # here asks the model anything, so this is never sent anywhere.
                    "ANTHROPIC_API_KEY=sk-ant-smoke-not-a-key",
                    f"ASSISTANT_GATEWAY_HOSTED_HOST_NAME={HOST_NAME}",
                    "ASSISTANT_GATEWAY_HOSTED_DEVICE=smoke-browser",
                    f"ASSISTANT_GATEWAY_EDGE_PUBLIC_KEYS={self.edge.public}",
                    f"ASSISTANT_GATEWAY_EDGE_ISSUER={ISSUER}",
                    f"ASSISTANT_GATEWAY_EDGE_AUDIENCE={AUDIENCE}",
                    f"ASSISTANT_GATEWAY_EDGE_SUBJECT={SUBJECT}",
                    "",
                )
            ),
            encoding="utf-8",
        )
        self.passphrase = work / "keyring-passphrase"
        self.passphrase.write_text("smoke-passphrase\n", encoding="utf-8")
        self.wrong = work / "wrong-passphrase"
        self.wrong.write_text("not-the-passphrase\n", encoding="utf-8")
        # Read by the container's uid, which is not this one.
        for path in (self.env_file, self.passphrase, self.wrong):
            path.chmod(0o644)

    def mounts(self, *, data: str | None = DATA, passphrase: Path | None = None) -> list[str]:
        """The ``--volume`` arguments for a run.

        Args:
            data: The data volume, or ``None`` for none.
            passphrase: The passphrase file, or ``None`` for this run's own.

        Returns:
            The arguments.
        """
        arguments = ["--volume", f"{KEYRING}:/home/assistant/.local/share/keyrings"]
        if data is not None:
            arguments += ["--volume", f"{data}:/data"]
        source = passphrase or self.passphrase
        arguments += ["--volume", f"{source}:/run/secrets/keyring-passphrase:ro"]
        return arguments

    def start(self) -> None:
        """Start the hub's container, detached, the way the guide runs it."""
        runtime(
            "run",
            "--detach",
            "--name",
            NAME,
            "--env-file",
            str(self.env_file),
            *self.mounts(),
            "--publish",
            f"127.0.0.1:{PORT}:8423",
            "--stop-timeout",
            "90",
            self.image,
        )

    def await_healthy(self) -> None:
        """Wait for the health check to pass, and fail if the container stops first.

        Raises:
            SmokeError: If it stops, or is not healthy within the deadline.
        """
        give_up = time.monotonic() + READY_DEADLINE
        while time.monotonic() < give_up:
            state = runtime(
                "inspect", "--format", "{{.State.Status}} {{.State.Health.Status}}", NAME
            ).stdout.split()
            if state[0] != "running":
                msg = f"the container stopped before it was ready: {' '.join(state)}"
                raise SmokeError(msg)
            if state[-1] == "healthy":
                return
            time.sleep(2)
        msg = f"the container was not healthy within {READY_DEADLINE:g} seconds"
        raise SmokeError(msg)

    def exec(self, *args: str) -> str:
        """Run one command in the container, as ``docker exec`` runs an admin act.

        Args:
            *args: The command line.

        Returns:
            What it printed.
        """
        return runtime("exec", NAME, *args).stdout

    def check_the_door(self) -> None:
        """The published port is loopback alone, and the hosted listener answers on it.

        Raises:
            SmokeError: If any of it does not hold.
        """
        published = runtime("port", NAME, "8423/tcp").stdout.split()
        if published != [f"127.0.0.1:{PORT}"]:
            msg = f"8423 is published to {published}, not to the host's loopback alone"
            raise SmokeError(msg)
        status, _ = get("/", assertion=None)
        if status != 403:  # noqa: PLR2004 — ADR-0327 §7:6's refusal
            msg = f"a request with no assertion was answered {status}, not refused with 403"
            raise SmokeError(msg)
        status, body = get("/", assertion=self.edge.assertion())
        if status != 200 or b"<html" not in body.lower():  # noqa: PLR2004
            msg = f"a request the edge signed was answered {status}, not served the page"
            raise SmokeError(msg)

    def check_carried(self) -> None:
        """The conversation the first run started, and the keyring entry, are still there.

        Raises:
            SmokeError: If either is gone.
        """
        if self.conversation not in self.exec("assistant", "conversations"):
            msg = f"the conversation {self.conversation} is gone from the hub's store"
            raise SmokeError(msg)
        carried = self.exec("python", "-c", _KEYRING_READ).strip()
        if carried != "carried":
            msg = f"the keyring entry was {carried!r} after the restart, not 'carried'"
            raise SmokeError(msg)

    def refused(self, why: str, *args: str) -> None:
        """Run the image in the foreground, and require it to exit ``78``.

        Args:
            why: What is wrong with the deployment.
            *args: The ``run`` arguments before the image.

        Raises:
            SmokeError: If it exits any other way.
        """
        step(f"refused: {why}")
        completed = runtime("run", "--rm", *args, self.image, check=False)
        if completed.returncode != EXIT_DEPLOYMENT:
            msg = (
                f"{why}: the container exited {completed.returncode}, not "
                f"{EXIT_DEPLOYMENT}\n{completed.stderr}"
            )
            raise SmokeError(msg)
        print(completed.stderr.strip().splitlines()[-1], flush=True)

    def run(self) -> None:
        """Every check, in order.

        Raises:
            SmokeError: At the first that fails.
        """
        step("a fresh volume reaches readiness")
        runtime("volume", "create", DATA)
        runtime("volume", "create", KEYRING)
        self.start()
        self.await_healthy()

        step("the gateway answers on the published port, and only there")
        self.check_the_door()

        step("admin acts run through exec")
        self.exec("ai-assistant-device", "list")
        started = _CONVERSATION.search(self.exec("assistant", "start-conversation"))
        if started is None:
            msg = "assistant start-conversation printed no conversation id"
            raise SmokeError(msg)
        self.conversation = started.group()
        backend = self.exec("python", "-c", _KEYRING_WRITE).strip()
        if backend != "keyring.backends.SecretService":
            msg = f"the secret store chose {backend}, not the SecretService keyring"
            raise SmokeError(msg)

        step("a restart of the same container carries the data")
        runtime("restart", NAME)
        self.await_healthy()
        self.check_carried()
        self.check_the_door()

        step("a stop drains to 0, and a new container on the same volumes carries it")
        runtime("stop", NAME)
        code = runtime("inspect", "--format", "{{.State.ExitCode}}", NAME).stdout.strip()
        if code != "0":
            msg = f"a stop ended the container with {code}, not 0"
            raise SmokeError(msg)
        runtime("rm", NAME)
        self.start()
        self.await_healthy()
        self.check_carried()
        runtime("stop", NAME)
        runtime("rm", NAME)

        env = ["--env-file", str(self.env_file)]
        keyring = ["--volume", f"{KEYRING}:/home/assistant/.local/share/keyrings"]
        passphrase = ["--volume", f"{self.passphrase}:/run/secrets/keyring-passphrase:ro"]
        self.refused("no passphrase", *env, *keyring, "--volume", f"{DATA}:/data")
        self.refused(
            "a data directory off the volume",
            *env,
            *self.mounts(),
            "--env",
            "ASSISTANT_DATA_DIR=/home/assistant/elsewhere",
        )
        self.refused("no data volume", *env, *keyring, *passphrase)
        self.refused("the wrong passphrase", *env, *self.mounts(passphrase=self.wrong))
        self.refused("the host's own network", *env, *self.mounts(), "--network", "host")

    def clean(self) -> None:
        """Remove what the run made, and show the container's log if it is still there."""
        logs = runtime("logs", NAME, check=False)
        if logs.returncode == 0:
            print(logs.stdout + logs.stderr, flush=True)
        runtime("rm", "--force", NAME, check=False)
        runtime("volume", "rm", "--force", DATA, KEYRING, check=False)


def main(argv: Sequence[str]) -> int:
    """Run the smoke test against one image.

    Args:
        argv: ``[IMAGE]``.

    Returns:
        ``0`` when every check passed, ``1`` otherwise.
    """
    if len(argv) != 1 or shutil.which(RUNTIME) is None:
        print(f"usage: smoke.py IMAGE, with {RUNTIME} on PATH", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="hub-smoke-") as scratch:
        return drive(Smoke(argv[0], Path(scratch)))


class _Run(Protocol):
    def run(self) -> None: ...

    def clean(self) -> None: ...


def drive(smoke: _Run) -> int:
    """Run every check, and clean up however the run ends.

    A failed check is reported and is a ``1``. Anything else — a refused connection,
    a timeout, a runtime that went away — is left to raise with its traceback, after
    the cleanup, so that a later run does not find this run's container and volumes.

    Args:
        smoke: The run.

    Returns:
        ``0`` when every check passed, ``1`` when one failed.
    """
    try:
        smoke.run()
    except SmokeError as failure:
        print(f"smoke: FAILED: {failure}", file=sys.stderr, flush=True)
        return 1
    finally:
        smoke.clean()
    print("smoke: every check passed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
