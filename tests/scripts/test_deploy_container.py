"""Tests for ``scripts/deploy_container.py``, the container deploy path (#3160).

The deploy is driven against :class:`FakeBox`, which keeps what a box would — files with
owners and modes, volumes, images, the unit and its container — and answers the argv the
deploy sends the way Docker, systemd and coreutils would. Nothing here runs Docker or ssh;
the ``container`` workflow drives the same script against a real runner.
"""

from __future__ import annotations

import io
import json
import re
import shlex
import sys
import tarfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO, TYPE_CHECKING, Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _operator_recipes import SCRIPTS, load

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

sys.path.insert(0, str(SCRIPTS))
dc = load("deploy_container")
REPO = Path(__file__).parents[2]

HUBS = PurePosixPath("/srv/hubs")
PERSON = dc.Person("alice", HUBS)
OLD_COMMIT = "a" * 40
NEW_COMMIT = "b" * 40
OLD_ID = "sha256:" + "1" * 64
ADDRESS = "172.17.0.2"
DOCKER_DROP = (
    f"-A PREROUTING -d {ADDRESS}/32 ! -i br-0123456789ab -p tcp -m tcp --dport 8423 -j DROP"
)
LOOPBACK_DROP = "-A PREROUTING -d 127.0.0.1/32 ! -i lo -p tcp -m tcp --dport 8501 -j DROP"
LOCALNET = "\n".join(
    f"/proc/sys/net/ipv4/conf/{name}/route_localnet:0"
    for name in ("all", "default", "eth0", "lo", "docker0")
)


@dataclass
class File:
    uid: int
    mode: int
    data: bytes = b""
    directory: bool = False


@dataclass
class FakeBox:
    """A box: what is on it, and what it answers. Every argv it ran is in ``ran``."""

    files: dict[str, File] = field(default_factory=dict)
    volumes: set[str] = field(default_factory=set)
    images: dict[str, tuple[str, str]] = field(default_factory=dict)
    ran: list[list[str]] = field(default_factory=list)
    active: str = "inactive"
    exit_status: int = 0
    container_image: str | None = None
    #: How a start of each image goes: "healthy", "78", or "never".
    starts: dict[str, str] = field(default_factory=dict)
    #: How the backup goes: "verified", "unverified", "refused", "silent" or "elsewhere".
    backup: str = "verified"
    localnet: str = LOCALNET
    raw_rules: str = f"-P PREROUTING ACCEPT\n{LOOPBACK_DROP}\n{DOCKER_DROP}"
    door: str = "403"
    ports: object = None
    mode: str = "hub-alice"
    contexts: list[set[str]] = field(default_factory=list)
    built: int = 0
    driver: str = "bridge"
    health: str = "healthy"
    stop_fails: bool = False
    #: The link drops after the new image starts: every later stop fails.
    stop_fails_once_started: bool = False
    #: A unit another deploy installs while this one builds.
    unit_installed_meanwhile: bytes | None = None
    #: The link drops just after unit.env's rename lands.
    interrupt_after_rename: bool = False
    #: Whether the unit starts at boot.
    enabled: bool = False
    #: The next write of unit.env fails, once.
    fail_unit_env_write: bool = False

    def run(self, argv: Sequence[str], *, stdin: IO[bytes] | None = None) -> Any:
        argv = list(argv)
        self.ran.append(argv)
        handler = self._handler(argv)
        code, out, err = handler(argv, stdin.read() if stdin is not None else b"")
        return dc.Result(code, out, err)

    # -- dispatch -------------------------------------------------------------

    def _handler(self, argv: list[str]) -> Callable[[list[str], bytes], tuple[int, str, str]]:
        head = argv[0]
        name = f"docker_{argv[1]}" if head == dc.DOCKER else f"cmd_{head}"
        handler: Callable[[list[str], bytes], tuple[int, str, str]] = getattr(self, name)
        return handler

    def _missing(self, path: str) -> tuple[int, str, str]:
        return 1, "", f"stat: cannot statx '{path}': No such file or directory"

    # -- coreutils and friends -------------------------------------------------

    def cmd_systemctl(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        verb = argv[1]
        if verb == "--version":
            return 0, "systemd 255\n", ""
        if verb == "show":
            state = (
                f"ActiveState={self.active}\nSubState=x\n"
                f"ExecMainStatus={self.exit_status}\nNRestarts=0\n"
            )
            return 0, state, ""
        if verb == "stop":
            if self.stop_fails:
                return 255, "", "ssh: connection closed"
            self.active = "inactive"
            self.container_image = None
            return 0, "", ""
        if verb == "start":
            self.stop_fails = self.stop_fails_once_started
            env = dc.parse_unit_env(self.files[str(PERSON.unit_env)].data.decode())
            outcome = self.starts.get(env.image, "healthy")
            if outcome == "78":
                self.active, self.exit_status, self.container_image = "failed", 78, None
            else:
                self.active, self.container_image = "active", env.image
            return 0, "", ""
        if verb in {"enable", "disable"}:
            self.enabled = verb == "enable"
        return 0, "", ""  # daemon-reload, reset-failed

    def cmd_curl(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        return (0, "curl 8\n", "") if argv[1] == "--version" else (0, self.door, "")

    def cmd_iptables(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        return (0, "iptables v1.8\n", "") if argv[1] == "--version" else (0, self.raw_rules, "")

    def cmd_sh(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        assert "route_localnet" in argv[2]
        return 0, self.localnet, ""

    def cmd_stat(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        path = argv[-1]
        entry = self.files.get(path)
        if entry is None:
            return self._missing(path)
        kind = "directory" if entry.directory else "regular file"
        return 0, f"{entry.uid} {entry.mode:o} {len(entry.data)} {kind}\n", ""

    def cmd_cat(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        return 0, self.files[argv[-1]].data.decode(), ""

    def cmd_mkdir(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        path = argv[-1]
        if path in self.files:
            return 1, "", f"mkdir: cannot create directory '{path}': File exists"
        self.files[path] = File(0, 0o700, directory=True)
        return 0, "", ""

    def cmd_rmdir(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        self.files.pop(argv[-1], None)
        return 0, "", ""

    def cmd_rm(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        self.files.pop(argv[-1], None)
        return 0, "", ""

    def cmd_tar(self, argv: list[str], data: bytes) -> tuple[int, str, str]:
        assert argv[-1] in self.files, "the context is unpacked into the staging directory"
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            self.contexts.append({member.name for member in tar.getmembers()})
        return 0, "", ""

    def cmd_install(self, argv: list[str], data: bytes) -> tuple[int, str, str]:
        if argv[1] == "-d":
            self.files[argv[-1]] = File(int(argv[3]), int(argv[-3], 8), directory=True)
        else:
            if self.fail_unit_env_write and argv[-1].startswith(str(PERSON.unit_env)):
                self.fail_unit_env_write = False
                return 1, "", "install: cannot create regular file: No space left on device"
            self.files[argv[-1]] = File(0, int(argv[2], 8), data)
        return 0, "", ""

    def cmd_mv(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        self.files[argv[-1]] = self.files.pop(argv[-2])
        if self.interrupt_after_rename and argv[-1] == str(PERSON.unit_env):
            raise KeyboardInterrupt
        return 0, "", ""

    def cmd_grep(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        pattern = re.compile(argv[4].replace("[[:space:]]", r"\s"), re.IGNORECASE)
        lines = self.files[argv[-1]].data.decode().splitlines()
        count = sum(1 for line in lines if pattern.search(line))
        return (0 if count else 1), f"{count}\n", ""

    def cmd_find(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        wanted = argv[argv.index("-lx") + 1]
        hits = [
            path
            for path, entry in self.files.items()
            if path.endswith("/unit.env") and wanted in entry.data.decode().splitlines()
        ]
        return 0, "".join(f"{hit}\n" for hit in hits), ""

    def cmd_journalctl(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        return 0, "noise\nhub-container: the passphrase does not unlock (exit 78)\n", ""

    # -- docker ------------------------------------------------------------------

    def docker_version(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        return 0, "28.3.0\n", ""

    def docker_volume(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        name = argv[-1]
        if argv[2] == "create":
            self.volumes.add(name)
            return 0, f"{name}\n", ""
        if argv[2] == "rm":
            self.volumes.discard(name)
            return 0, f"{name}\n", ""
        return (0, f"{name}\n", "") if name in self.volumes else (1, "", "no such volume")

    def docker_image(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        found = self.images.get(argv[-1])
        if found is None:
            return 1, "", f"Error: No such image: {argv[-1]}"
        return 0, f"{found[0]} {found[1]}\n", ""

    def docker_build(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        if self.unit_installed_meanwhile is not None:
            self.files[dc.UNIT_PATH] = File(0, 0o644, self.unit_installed_meanwhile)
        self.built += 1
        commit = argv[argv.index("--label") + 1].split("=", 1)[1]
        tag = argv[argv.index("--tag") + 1]
        image_id = "sha256:" + f"{self.built + 1}" * 64
        self.images[tag] = self.images[image_id] = (image_id, commit)
        return 0, "built\n", ""

    def docker_ps(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        return 0, ("c0ffee\n" if self.container_image else ""), ""

    def docker_run(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        assert self.container_image is None, "the backup runs with the hub stopped"
        assert argv[argv.index("--network") + 1] == "none"
        artifact = argv[argv.index("--passphrase-file") - 1]
        disclosure = f"about to write a complete encrypted copy of {'/data'}\n"
        if self.backup == "elsewhere":
            disclosure = "about to write a complete encrypted copy of /elsewhere\n"
        if self.backup == "refused":
            return 78, disclosure, "the backup was refused: a sidecar is present\n"
        written = disclosure + f"wrote {artifact}\n"
        if self.backup == "unverified":
            return 0, written, "warning: the artifact is written but unverified: no room\n"
        if self.backup != "silent":
            name = PurePosixPath(artifact).name
            self.files[str(PERSON.backups / name)] = File(10001, 0o600, b"age")
        return 0, written + dc._BACKUP_VERIFIED + "\n", ""

    def docker_container(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        if self.container_image is None:
            return 1, "", "Error: No such container"
        fields = {
            "status": "running",
            "health": self.health,
            "image": self.container_image,
            "mode": self.mode,
            "ports": self.ports or {"8423/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8501"}]},
            "networks": {"hub-alice": {"IPAddress": ADDRESS, "GlobalIPv6Address": ""}},
        }
        return 0, json.dumps(fields), ""

    def docker_network(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        assert argv[-1] == "hub-alice"
        return 0, f"{self.driver}|0123456789abcdef|<no value>\n", ""

    def docker_exec(self, argv: list[str], _: bytes) -> tuple[int, str, str]:
        return 0, "alice.example.com\n", ""


def person_files(*, served: bool) -> dict[str, File]:
    """The person directory an operator prepares, and what a deploy left, if any."""
    files = {
        str(HUBS): File(0, 0o755, directory=True),
        str(PERSON.dir): File(0, 0o700, directory=True),
        str(PERSON.env_file): File(0, 0o600, b"ANTHROPIC_API_KEY=sk-ant-x\n"),
        str(PERSON.keyring_passphrase): File(10001, 0o400, b"k\n"),
        str(PERSON.backup_passphrase): File(10001, 0o400, b"b\n"),
    }
    if served:
        files[str(PERSON.unit_env)] = File(
            0, 0o644, f"HUB_IMAGE={OLD_ID}\nHUB_PORT=8501\n".encode()
        )
    return files


def served_box(**overrides: object) -> FakeBox:
    """A box whose hub has served data, running the earlier image."""
    box = FakeBox(files=person_files(served=True), **overrides)  # type: ignore[arg-type]
    box.volumes = {PERSON.data_volume, PERSON.keyring_volume}
    box.images = {OLD_ID: (OLD_ID, OLD_COMMIT)}
    box.active, box.container_image = "active", OLD_ID
    return box


def fake_stage(_repo: Path, into: Path) -> str:
    into.mkdir()
    for name in ("Dockerfile", "ai_assistant-0.1.0-py3-none-any.whl", "requirements.txt"):
        (into / name).write_text(name)
    return NEW_COMMIT


def deployment(box: FakeBox, **overrides: object) -> Any:
    settings: dict[str, object] = {
        "box": box,
        "person": PERSON,
        "token": "t0k3n",
        "stamp": "20261018T120000Z",
        "clock": iter(range(10_000)).__next__,
        "sleep": lambda _seconds: None,
        "stage_context": fake_stage,
        "ready_timeout": 5,
    }
    settings.update(overrides)
    return dc.Deployment(**settings)


@pytest.fixture(autouse=True)
def _head_is_new_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    real = dc._git

    def fake(repo: Path, *args: str) -> str:
        return NEW_COMMIT if args == ("rev-parse", "HEAD") else real(repo, *args)

    monkeypatch.setattr(dc, "_git", fake)


def verbs(box: FakeBox) -> list[str]:
    """The systemctl and docker verbs the deploy sent, in order."""
    shown = []
    for argv in box.ran:
        if argv[0] == "systemctl" and argv[1] in {"stop", "start", "enable"}:
            shown.append(f"systemctl {argv[1]}")
        elif argv[0] == dc.DOCKER and argv[1] in {"build", "run"}:
            shown.append(f"docker {argv[1]}")
        elif argv[0] == "mv" and argv[-1] == str(PERSON.unit_env):
            shown.append("unit.env")
    return shown


# --------------------------------------------------------------------------- #
# The whole act                                                                #
# --------------------------------------------------------------------------- #


def test_deploy_upgrade_backs_up_with_the_earlier_image_before_the_new_one_runs() -> None:
    box = served_box()

    report = deployment(box).run()

    assert verbs(box) == [
        "docker build",
        "systemctl stop",
        "docker run",
        "systemctl enable",
        "unit.env",
        "systemctl start",
    ]
    backup = next(argv for argv in box.ran if argv[:2] == [dc.DOCKER, "run"])
    assert backup[backup.index("--entrypoint") + 2] == OLD_ID
    assert f"{PERSON.data_volume}:/data" in backup
    assert f"{PERSON.backup_passphrase}:/run/secrets/backup-passphrase:ro" in backup
    assert "--env-file" not in backup, "the backup runs with the image's settings alone"
    artifact = PERSON.backups / "pre-deploy-20261018T120000Z-t0k3n.age"
    assert str(artifact) in box.files
    assert f"backup: {artifact} (verified, and kept)" in report
    env = dc.parse_unit_env(box.files[str(PERSON.unit_env)].data.decode())
    assert env.image == box.images[f"ai-assistant-hub:{NEW_COMMIT[:12]}"][0]
    assert env.port == 8501
    assert box.container_image == env.image
    assert str(PERSON.lock) not in box.files


def test_deploy_upgrade_keeps_the_artifact_outside_the_data_volume() -> None:
    box = served_box()

    deployment(box).run()

    backups = box.files[str(PERSON.backups)]
    assert (backups.uid, backups.mode) == (10001, 0o700)
    assert not str(PERSON.backups).startswith("/data")
    assert not any(argv[0] == "rm" and "backups" in argv[-1] for argv in box.ran)


def test_deploy_first_install_creates_volumes_and_takes_no_backup() -> None:
    box = FakeBox(files=person_files(served=False))

    report = deployment(box, port=8501).run()

    assert "docker run" not in verbs(box)
    assert box.volumes == {PERSON.data_volume, PERSON.keyring_volume}
    assert "backup: none, a first install has served no data" in report
    assert box.active == "active"


def test_deploy_ships_the_staged_context_and_builds_it_labelled() -> None:
    box = served_box()

    deployment(box).run()

    assert box.contexts == [
        {"Dockerfile", "ai_assistant-0.1.0-py3-none-any.whl", "requirements.txt"}
    ]
    build = next(argv for argv in box.ran if argv[:2] == [dc.DOCKER, "build"])
    assert f"{dc.REVISION_LABEL}={NEW_COMMIT}" in build
    assert build[build.index("--tag") + 1] == f"ai-assistant-hub:{NEW_COMMIT[:12]}"
    stage = build[-1]
    assert ["rm", "-rf", "--", stage] in box.ran


def test_deploy_reuses_an_image_already_built_for_the_commit() -> None:
    box = served_box()
    tag = f"ai-assistant-hub:{NEW_COMMIT[:12]}"
    new_id = "sha256:" + "9" * 64
    box.images[tag] = box.images[new_id] = (new_id, NEW_COMMIT)

    deployment(box).run()

    assert box.built == 0
    assert box.container_image == new_id


@pytest.mark.parametrize(
    ("outcome", "said"),
    [
        ("refused", "ai-assistant-backup failed (exit 78)"),
        ("unverified", "is not verified"),
        ("elsewhere", "did not say it copied /data"),
        ("silent", "is absent or empty"),
    ],
)
def test_deploy_failed_backup_restarts_the_earlier_image(outcome: str, said: str) -> None:
    box = served_box(backup=outcome)
    env_before = box.files[str(PERSON.unit_env)].data

    with pytest.raises(dc.DeployError) as caught:
        deployment(box).run()

    message = str(caught.value)
    assert said in message
    assert "Nothing was installed." in message
    assert f"started again on its earlier image, {OLD_ID}, healthy" in message
    assert box.files[str(PERSON.unit_env)].data == env_before
    assert box.container_image == OLD_ID
    assert "unit.env" not in verbs(box)
    assert str(PERSON.lock) not in box.files


def test_deploy_says_when_the_earlier_image_does_not_come_back() -> None:
    box = served_box(backup="refused", starts={OLD_ID: "78"})

    with pytest.raises(dc.DeployError, match="could NOT be started again"):
        deployment(box).run()


def test_deploy_new_image_that_stays_down_is_not_rolled_back() -> None:
    box = served_box(starts={})
    tag = f"ai-assistant-hub:{NEW_COMMIT[:12]}"
    new_id = "sha256:" + "9" * 64
    box.images[tag] = box.images[new_id] = (new_id, NEW_COMMIT)
    box.starts[new_id] = "78"

    with pytest.raises(dc.DeployError) as caught:
        deployment(box).run()

    message = str(caught.value)
    assert "stopped (exit 78)" in message
    assert "hub-container: the passphrase does not unlock (exit 78)" in message
    assert "noise" not in message
    assert "ADR-0326 §5:4" in message
    starts = [argv for argv in box.ran if argv[:2] == ["systemctl", "start"]]
    assert len(starts) == 1, "the earlier image is never started on data the new one served"


def test_deploy_uncontained_is_stopped_before_it_is_healthy() -> None:
    box = served_box(health="starting", raw_rules="-P PREROUTING ACCEPT\n")
    slept: list[float] = []

    with pytest.raises(dc.DeployError) as caught:
        deployment(box, sleep=slept.append).run()

    message = str(caught.value)
    assert slept == [], "the check runs on the first sight of the running container"
    assert "ADR-0327 §5:2 cannot be established" in message
    assert "hub@alice.service is stopped" in message
    assert box.active == "inactive"


def test_deploy_not_ready_but_contained_is_left_to_its_unit() -> None:
    box = served_box(health="starting")

    with pytest.raises(dc.DeployError) as caught:
        deployment(box).run()

    message = str(caught.value)
    assert "so the unit keeps the image it started as its supervisor rules" in message
    assert box.active == "active"
    assert [argv[:2] for argv in box.ran].count(["systemctl", "stop"]) == 1


def test_deploy_interrupted_while_starting_is_checked_before_it_is_left() -> None:
    box = served_box(health="starting")

    def interrupt(_seconds: float) -> None:
        box.raw_rules = "-P PREROUTING ACCEPT\n"  # the box changed under the start
        raise KeyboardInterrupt

    with pytest.raises(dc.DeployError) as caught:
        deployment(box, sleep=interrupt).run()

    message = str(caught.value)
    assert message.startswith("interrupted once the new image")
    assert "hub@alice.service is stopped and disabled" in message
    assert box.active == "inactive"
    assert str(PERSON.lock) not in box.files


def test_deploy_recovery_start_is_held_to_the_same_checks() -> None:
    box = served_box(backup="refused", enabled=True)
    box.raw_rules = "-P PREROUTING ACCEPT\n"

    with pytest.raises(dc.DeployError) as caught:
        deployment(box).run()

    message = str(caught.value)
    assert "could NOT be started again on its earlier image, checked" in message
    assert "is stopped and disabled" in message
    assert box.active == "inactive"
    assert not box.enabled


def test_deploy_recovery_door_that_does_not_refuse_is_stopped() -> None:
    box = served_box(backup="refused", enabled=True, door="200")

    with pytest.raises(dc.DeployError) as caught:
        deployment(box).run()

    message = str(caught.value)
    assert "could NOT be started again on its earlier image, checked" in message
    assert "answered 200, not refused with 403" in message
    assert "is stopped and disabled" in message
    assert box.active == "inactive"
    assert not box.enabled


def test_deploy_first_install_interrupted_after_its_record_is_undone_whole() -> None:
    box = FakeBox(files=person_files(served=False), interrupt_after_rename=True)

    with pytest.raises(KeyboardInterrupt):
        deployment(box, port=8501).run()

    assert ["systemctl", "enable", PERSON.unit] in box.ran
    created = [argv[-1] for argv in box.ran if argv[:3] == [dc.DOCKER, "volume", "create"]]
    assert created == [PERSON.data_volume, PERSON.keyring_volume]
    assert verbs(box)[-1] == "unit.env", "interrupted on unit.env's rename, and nothing after"
    assert str(PERSON.unit_env) not in box.files
    assert box.volumes == set()
    assert not box.enabled
    assert str(PERSON.lock) not in box.files

    box.interrupt_after_rename = False
    deployment(box, port=8501).run()

    assert box.volumes == {PERSON.data_volume, PERSON.keyring_volume}
    assert box.active == "active"
    assert box.enabled  # last: mypy reads the earlier `not box.enabled` as still holding


def test_deploy_refuses_a_raw_chain_that_may_accept_before_dockers_drop() -> None:
    box = served_box(
        raw_rules=f"-P PREROUTING ACCEPT\n-A PREROUTING -i eth0 -j ACCEPT\n{DOCKER_DROP}"
    )
    _refused_untouched(box, "-i eth0 -j ACCEPT', which may accept")


def test_deploy_refuses_docker_before_28() -> None:
    box = served_box()
    box.docker_version = lambda _argv, _data: (0, "27.5.1\n", "")  # type: ignore[assignment]
    _refused_untouched(box, "Docker Engine 28 is the first")


def test_deploy_interrupted_after_naming_the_new_image_starts_nothing() -> None:
    box = served_box(interrupt_after_rename=True)

    with pytest.raises(dc.DeployError) as caught:
        deployment(box).run()

    message = str(caught.value)
    assert "no longer names the earlier image" in message
    assert "nothing was started" in message
    assert box.active == "inactive"
    assert box.container_image is None
    assert ["systemctl", "start", PERSON.unit] not in box.ran


def test_deploy_says_when_an_uncontained_container_cannot_be_stopped() -> None:
    box = served_box(raw_rules="-P PREROUTING ACCEPT\n")
    box.stop_fails_once_started = True

    with pytest.raises(dc.DeployError) as caught:
        deployment(box).run()

    message = str(caught.value)
    assert "could NOT be shown stopped and disabled (disable exit 0,\nstop exit 255" in message
    assert "Stop it by hand: systemctl stop hub@alice.service" in message
    assert "is stopped: it does not serve" not in message


def test_deploy_contained_container_does_not_start_at_boot() -> None:
    box = served_box(raw_rules="-P PREROUTING ACCEPT\n", enabled=True)

    with pytest.raises(dc.DeployError, match="is stopped and disabled"):
        deployment(box).run()

    assert not box.enabled


def test_deploy_first_install_that_fails_can_be_retried() -> None:
    box = FakeBox(files=person_files(served=False), fail_unit_env_write=True)

    with pytest.raises(dc.DeployError, match="No space left"):
        deployment(box, port=8501).run()
    assert box.volumes == set(), "volumes made for a start that never came are removed"

    deployment(box, port=8501).run()

    assert box.volumes == {PERSON.data_volume, PERSON.keyring_volume}
    assert box.active == "active"


def test_deploy_unreachability_not_established_stops_the_new_container() -> None:
    box = served_box(raw_rules="-P PREROUTING ACCEPT\n")

    with pytest.raises(dc.DeployError) as caught:
        deployment(box).run()

    assert "ADR-0327 §5:2 cannot be established" in str(caught.value)
    assert box.active == "inactive"
    assert [argv[:2] for argv in box.ran].count(["systemctl", "start"]) == 1


def test_deploy_names_the_chain_when_the_drop_is_missing() -> None:
    box = served_box(raw_rules="-P PREROUTING ACCEPT\n-A PREROUTING -j CT --notrack\n")

    with pytest.raises(dc.DeployError) as caught:
        deployment(box).run()

    assert "The chain:\n    -P PREROUTING ACCEPT\n    -A PREROUTING -j CT --notrack" in str(
        caught.value
    )


def test_deploy_refuses_a_person_network_that_is_not_a_bridge() -> None:
    box = served_box(driver="macvlan")

    with pytest.raises(dc.DeployError, match="not a bridge"):
        deployment(box).run()
    assert box.active == "inactive"


def test_deploy_door_that_does_not_refuse_fails() -> None:
    box = served_box(door="200")

    with pytest.raises(dc.DeployError, match="answered 200, not refused with 403"):
        deployment(box).run()


# --------------------------------------------------------------------------- #
# Refusals before anything is stopped                                          #
# --------------------------------------------------------------------------- #


def _refused_untouched(box: FakeBox, match: str, **overrides: object) -> None:
    with pytest.raises(dc.DeployError, match=match) as caught:
        deployment(box, **overrides).run()
    assert "Nothing has been stopped or changed." in str(caught.value)
    touched = {"systemctl stop", "docker run", "unit.env", "systemctl start"}
    assert not touched & set(verbs(box))
    assert str(PERSON.lock) not in box.files


def test_deploy_refuses_a_missing_backup_passphrase() -> None:
    box = served_box()
    del box.files[str(PERSON.backup_passphrase)]
    _refused_untouched(box, "backup passphrase file .* is missing")


@pytest.mark.parametrize(
    ("uid", "mode"),
    [(0, 0o400), (10001, 0o440), (10001, 0o604), (10001, 0o000), (10001, 0o200)],
)
def test_deploy_refuses_a_passphrase_anyone_else_can_read(uid: int, mode: int) -> None:
    box = served_box()
    box.files[str(PERSON.keyring_passphrase)] = File(uid, mode, b"k\n")
    _refused_untouched(box, "keyring passphrase file")


def test_deploy_refuses_an_env_file_others_can_read() -> None:
    box = served_box()
    box.files[str(PERSON.env_file)].mode = 0o644
    _refused_untouched(box, "holds the\nmodel key")


def test_deploy_refuses_a_person_dir_others_can_write() -> None:
    box = served_box()
    box.files[str(PERSON.dir)] = File(1000, 0o700, directory=True)
    _refused_untouched(box, "it must be\nroot's")


def test_deploy_refuses_a_changed_drain() -> None:
    box = served_box()
    box.files[str(PERSON.env_file)].data += b"assistant_shutdown_drain_seconds=PT2M\n"
    _refused_untouched(box, "ASSISTANT_SHUTDOWN_DRAIN_SECONDS")


def test_deploy_refuses_a_served_volume_with_no_record_of_its_image() -> None:
    box = served_box()
    del box.files[str(PERSON.unit_env)]
    _refused_untouched(box, "nothing says which image wrote it", port=8501)


def test_deploy_refuses_a_record_with_no_volume() -> None:
    box = served_box()
    box.volumes.discard(PERSON.data_volume)
    _refused_untouched(box, "never starts a hub on a new volume")


def test_deploy_refuses_a_record_with_no_keyring_volume() -> None:
    box = served_box()
    box.volumes.discard(PERSON.keyring_volume)
    _refused_untouched(box, "a new, empty keyring")


def test_deploy_refuses_a_root_other_than_the_installed_units() -> None:
    box = served_box()
    unit = dc.render_unit(dc.UNIT_SOURCE.read_text(encoding="utf-8"), PurePosixPath("/opt/people"))
    box.files[dc.UNIT_PATH] = File(0, 0o644, unit.encode())
    _refused_untouched(box, "one root per box")


def test_deploy_rechecks_the_root_under_the_box_lock() -> None:
    other = dc.render_unit(dc.UNIT_SOURCE.read_text(encoding="utf-8"), PurePosixPath("/opt/x"))
    box = served_box(unit_installed_meanwhile=other.encode())

    _refused_untouched(box, "one root per box")

    assert box.files[dc.UNIT_PATH].data == other.encode()
    assert dc.UNIT_LOCK not in box.files


def test_deploy_waits_for_the_box_lock_and_then_refuses() -> None:
    box = served_box()
    box.files[dc.UNIT_LOCK] = File(0, 0o700, directory=True)

    _refused_untouched(box, "installing\nthe unit")

    assert dc.UNIT_LOCK in box.files, "another deploy's lock is not removed"


def test_deploy_keeps_an_installed_unit_of_the_same_root() -> None:
    box = served_box()
    unit = dc.render_unit(dc.UNIT_SOURCE.read_text(encoding="utf-8"), HUBS)
    box.files[dc.UNIT_PATH] = File(0, 0o644, unit.encode())

    deployment(box).run()

    assert ["systemctl", "daemon-reload"] not in box.ran


def test_deploy_refuses_when_the_earlier_image_is_gone() -> None:
    box = served_box()
    del box.images[OLD_ID]
    _refused_untouched(box, "never prune the image a person runs")


def test_deploy_first_install_needs_a_port() -> None:
    _refused_untouched(FakeBox(files=person_files(served=False)), "needs --port")


def test_deploy_refuses_another_persons_port() -> None:
    box = FakeBox(files=person_files(served=False))
    box.files["/srv/hubs/bob/unit.env"] = File(0, 0o644, b"HUB_IMAGE=x\nHUB_PORT=8501\n")
    _refused_untouched(box, "already another person's: /srv/hubs/bob/unit.env", port=8501)


def test_deploy_refuses_moving_the_door() -> None:
    _refused_untouched(served_box(), "moving the\ndoor is not this act", port=8502)


def test_deploy_refuses_a_box_that_routes_localnet() -> None:
    box = served_box(localnet=LOCALNET + "\n/proc/sys/net/ipv4/conf/eth1/route_localnet:1")
    _refused_untouched(box, "route_localnet is 1 for eth1")


def test_deploy_refuses_while_another_deploy_holds_the_lock() -> None:
    box = served_box()
    box.files[str(PERSON.lock)] = File(0, 0o700, directory=True)
    with pytest.raises(dc.DeployError, match="another deploy to alice"):
        deployment(box).run()
    assert str(PERSON.lock) in box.files, "someone else's lock is not removed"
    assert len(box.ran) == 2  # the directory's stat, and the mkdir


def test_deploy_refuses_an_unlabelled_image() -> None:
    box = served_box()
    box.images["mine:latest"] = ("sha256:" + "7" * 64, "<no value>")
    _refused_untouched(box, "carries no commit label", image_ref="mine:latest")


def test_deploy_an_image_on_the_box_is_not_built() -> None:
    box = served_box()
    new_id = "sha256:" + "7" * 64
    box.images["received:1"] = (new_id, NEW_COMMIT)

    deployment(box, image_ref="received:1").run()

    assert box.built == 0
    assert box.container_image == new_id


# --------------------------------------------------------------------------- #
# The pieces                                                                   #
# --------------------------------------------------------------------------- #


def test_ssh_box_quotes_the_command_as_one_line_with_no_prompt() -> None:
    argv = dc.SshBox("box.example", "root").argv(["grep", "-c", "a b; rm -rf /", "--", "/x"])

    assert argv[:2] == ["ssh", "-o"]
    assert "BatchMode=yes" in argv
    assert argv[-3:-1] == ["--", "root@box.example"]
    assert shlex.split(argv[-1]) == ["grep", "-c", "a b; rm -rf /", "--", "/x"]


def test_local_box_runs_through_sudo_unless_root() -> None:
    assert dc.LocalBox(root=False).argv(["id"]) == ["sudo", "-n", "--", "id"]
    assert dc.LocalBox(root=True).argv(["id"]) == ["id"]


def test_render_unit_moves_every_person_path() -> None:
    template = dc.UNIT_SOURCE.read_text(encoding="utf-8")

    rendered = dc.render_unit(template, PurePosixPath("/opt/people"))

    assert "/srv/hubs/" not in rendered
    assert rendered.count("/opt/people/%i/") == template.count("/srv/hubs/%i/") == 3


def test_parse_unit_env_refuses_what_the_deploy_does_not_write() -> None:
    with pytest.raises(dc.DeployError, match="does not name an image id"):
        dc.parse_unit_env("HUB_IMAGE=ai-assistant-hub:latest\nHUB_PORT=8501\n")


def test_unit_env_round_trips() -> None:
    image = dc.Image(id=OLD_ID, commit=OLD_COMMIT, name="ai-assistant-hub:aaaaaaaaaaaa")

    parsed = dc.parse_unit_env(dc.render_unit_env(image, 8501, "now"))

    assert parsed == dc.Installed(image=OLD_ID, port=8501)


@pytest.mark.parametrize(
    ("rules", "found"),
    [
        (f"-P PREROUTING ACCEPT\n{LOOPBACK_DROP}\n{DOCKER_DROP}", None),
        (f"-A PREROUTING -d {ADDRESS}/32 ! -i br-0123456789ab -j DROP", None),
        (DOCKER_DROP.replace("8423", "8424"), "has no `-d 172.17.0.2/32"),
        (f"-A PREROUTING -j CT --notrack\n{DOCKER_DROP}", None),
        (f"-A PREROUTING -i eth0 -j ACCEPT\n{DOCKER_DROP}", "may accept"),
        (f"{DOCKER_DROP}\n-A PREROUTING -i eth0 -j ACCEPT", "may accept"),
        (f"-A PREROUTING -i eth0 -g MYCHAIN\n{DOCKER_DROP}", "may accept"),
        (f"-A PREROUTING -j MYCHAIN\n{DOCKER_DROP}", "may accept"),
        ("-P PREROUTING ACCEPT\n", "has no `-d 172.17.0.2/32"),
        (DOCKER_DROP.replace("br-0123456789ab", "docker0"), "has no"),
    ],
)
def test_raw_rule_problem(rules: str, found: str | None) -> None:
    problem = dc.raw_rule_problem(rules, ADDRESS, "br-0123456789ab")

    assert problem is None if found is None else found in (problem or "")


def test_route_localnet_ignores_docker_and_loopback_but_not_all() -> None:
    docker_only = "\n".join(
        f"/proc/sys/net/ipv4/conf/{name}/route_localnet:1"
        for name in ("lo", "docker0", "br-0a1b", "veth12ab")
    )

    assert dc.route_localnet_problems(docker_only) == []
    assert dc.route_localnet_problems("/proc/sys/net/ipv4/conf/all/route_localnet:1")
    assert dc.route_localnet_problems("")


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"mode": "host"}, "not 'hub-alice'"),
        ({"ports": {"8423/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8501"}]}}, "publishes"),  # noqa: S104
        (
            {
                "ports": {
                    "8423/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8501"}],
                    "22/tcp": [{"HostIp": "127.0.0.1", "HostPort": "2222"}],
                }
            },
            "publishes",
        ),
        ({"networks": {"hub-alice": {}, "bridge": {}}}, "not on 'hub-alice' alone"),
        (
            {"networks": {"hub-alice": {"IPAddress": ADDRESS, "GlobalIPv6Address": "fd00::2"}}},
            "IPv6",
        ),
    ],
)
def test_container_problems(change: dict[str, object], said: str) -> None:
    fields: dict[str, object] = {
        "mode": "hub-alice",
        "ports": {"8423/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8501"}], "9/udp": None},
        "networks": {"hub-alice": {"IPAddress": ADDRESS, "GlobalIPv6Address": ""}},
    }
    assert dc.container_problems(fields, 8501, "hub-alice") == []

    fields.update(change)

    assert any(said in problem for problem in dc.container_problems(fields, 8501, "hub-alice"))


@pytest.mark.parametrize(
    "argv",
    [
        ["Alice", "box"],
        ["alice", "--", "-box"],
        ["alice", "box", "--port", "80"],
        ["alice", "box", "--hubs-dir", "srv"],
        ["alice", "box", "--hubs-dir", "/srv/hub data"],
        ["alice", "box", "--hubs-dir", "/srv/100%"],
    ],
)
def test_main_refuses_bad_arguments_before_contacting_anything(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert dc.main(argv) == 1
    assert "deploy-container:" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# What the script restates, held to where it is stated                         #
# --------------------------------------------------------------------------- #


def test_container_uid_is_the_images() -> None:
    dockerfile = (REPO / "deploy" / "container" / "Dockerfile").read_text(encoding="utf-8")

    assert f"useradd --uid {dc.CONTAINER_UID} --gid {dc.CONTAINER_UID}" in dockerfile
    assert f"EXPOSE {dc.HOSTED_PORT}" in dockerfile
    assert "ENV PATH=/opt/assistant/venv/bin" in dockerfile
    assert "ASSISTANT_DATA_DIR=/data" in dockerfile


def test_labels_and_tag_are_build_shs() -> None:
    build = dc.BUILD_SCRIPT.read_text(encoding="utf-8")

    assert f'--label "{dc.REVISION_LABEL}=$commit"' in build
    assert f'--label "{dc.SOURCE_LABEL}={dc.SOURCE_URL}"' in build
    assert f"{dc.IMAGE_REPOSITORY}:${{commit:0:12}}" in build


def test_the_backup_tool_is_where_the_image_installs_it() -> None:
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")

    assert 'ai-assistant-backup = "ai_assistant.service.backup:main"' in pyproject
