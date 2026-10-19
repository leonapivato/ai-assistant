"""The shipped unit, ``deploy/container/hub@.service``, against what ADR-0083 asks of it (#3160).

The unit is the supervisor outside the container: D1 (restart on 1, never on 78), D2 (a
stop timeout above the drain), D4 (start at boot). The ``container`` workflow runs it under
a real systemd; these hold its text to the numbers it is sized against.
"""

from __future__ import annotations

import re
from pathlib import Path

from ai_assistant.core.config import Settings

UNIT = Path(__file__).parents[2] / "deploy" / "container" / "hub@.service"


def _unit() -> str:
    # Continuation lines joined, as systemd reads them.
    return UNIT.read_text(encoding="utf-8").replace("\\\n", " ")


def _directive(name: str) -> str:
    found = re.findall(rf"^{name}=(.*)$", _unit(), flags=re.MULTILINE)
    assert len(found) == 1, f"{name}= appears {len(found)} times"
    return str(found[0]).strip()


def test_unit_restarts_on_failure_and_leaves_78_down() -> None:
    assert _directive("Restart") == "on-failure"
    assert _directive("RestartPreventExitStatus") == "78"


def test_unit_runs_docker_in_the_foreground_so_its_exit_is_the_containers() -> None:
    start = _directive("ExecStart")

    assert start.startswith("/usr/bin/docker run ")
    assert "--detach" not in start
    assert " -d " not in start
    assert "--rm" in start
    assert "--pull never" in start
    assert _directive("Type") == "exec"


def test_unit_stop_timeouts_sit_above_the_drain_bound() -> None:
    drain = Settings.model_fields["shutdown_drain_seconds"].default.total_seconds()
    d2 = drain + 30  # ADR-0083 §3's reference margin
    run_timeout = int(re.search(r"--stop-timeout (\d+)", _directive("ExecStart")).group(1))  # type: ignore[union-attr]
    stop_timeout = int(re.search(r"--time (\d+)", _directive("ExecStop")).group(1))  # type: ignore[union-attr]

    assert run_timeout == stop_timeout > d2
    assert int(_directive("TimeoutStopSec")) > stop_timeout


def test_unit_mounts_what_the_guide_runs_and_publishes_to_loopback_alone() -> None:
    start = _directive("ExecStart")

    assert "--volume hub-%i-data:/data" in start
    assert "--volume hub-%i-keyring:/home/assistant/.local/share/keyrings" in start
    assert "--volume /srv/hubs/%i/keyring-passphrase:/run/secrets/keyring-passphrase:ro" in start
    assert "--env-file /srv/hubs/%i/hub.env" in start
    assert "--network bridge" in start
    assert re.findall(r"--publish (\S+)", start) == ["127.0.0.1:${HUB_PORT}:8423"]
    assert start.rstrip().endswith("${HUB_IMAGE}")
    assert _directive("EnvironmentFile") == "/srv/hubs/%i/unit.env"


def test_unit_starts_at_boot_after_docker() -> None:
    assert _directive("WantedBy") == "multi-user.target"
    assert "docker.service" in _directive("Requires")
    assert "docker.service" in _directive("After")
