"""Tests for ``deploy/container/supervise.py``, the container's supervisor (#3142).

Two layers. The checks that run before anything starts are pure, and each refusal is
held to its ``78`` and to a message naming the operator's action. The supervision is
driven with stand-in children (``_fake_children.py``) that are real processes, so the
signals, the exits and the order are the operating system's and not a mock's: what is
proven is the exit code each ending gives the container, which signal reaches which
child, and that nothing is started past a fault.

The real bus, keyring, hub and gateway are proven in the image, by the container
workflow's smoke test (``deploy/container/smoke.py``).
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import signal
import socket
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.core.config import Settings
from ai_assistant.interfaces.gateway import exits as gateway_exits
from ai_assistant.service import exits
from ai_assistant.wire.address import socket_path

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Iterator

_ROOT = Path(__file__).parents[2]
_FAKES = Path(__file__).with_name("_fake_children.py")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "supervise", _ROOT / "deploy" / "container" / "supervise.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["supervise"] = module
    spec.loader.exec_module(module)
    return module


supervise = _load()


@pytest.fixture
def layout() -> Iterator[Any]:
    """The image's layout under a short temporary root, so a Unix socket fits in it."""
    root = Path(tempfile.mkdtemp(prefix="hc-"))
    for name in ("data", "keyrings", "run", "secrets"):
        (root / name).mkdir()
    (root / "secrets" / "passphrase").write_text("open sesame\n", encoding="utf-8")
    yield supervise.Layout(
        data_dir=root / "data",
        keyrings=root / "keyrings",
        runtime_dir=root / "run",
        passphrase=root / "secrets" / "passphrase",
        venv_bin=root / "bin",
    )
    shutil.rmtree(root)


# --- The contract with the rest of the repository ---------------------------------


def test_the_exit_codes_are_the_hubs() -> None:
    assert supervise.EXIT_OK == exits.EXIT_OK
    assert supervise.EXIT_RESTART == exits.EXIT_RESTART
    assert supervise.EXIT_DEPLOYMENT == exits.EXIT_DEPLOYMENT


def test_the_gateways_exit_codes_are_the_hubs() -> None:
    # #3167: the gateway restates ADR-0083 §5's codes rather than importing them, and
    # the supervisor passes its `78` through, so all three must agree.
    assert gateway_exits.EXIT_OK == exits.EXIT_OK
    assert gateway_exits.EXIT_RESTART == exits.EXIT_RESTART
    assert gateway_exits.EXIT_DEPLOYMENT == exits.EXIT_DEPLOYMENT


def test_readiness_waits_on_the_socket_the_hub_binds(layout: Any) -> None:
    source = (_ROOT / "deploy" / "container" / "supervise.py").read_text(encoding="utf-8")
    assert f'"{socket_path(layout.data_dir).name}"' in source


def test_the_remote_settings_it_refuses_are_settings() -> None:
    for name in supervise.REMOTE_SETTINGS:
        assert name in Settings.model_fields
    assert supervise.HOSTED_ADDRESS.removeprefix("ASSISTANT_").lower() in Settings.model_fields


# --- 1. The checks that need nothing running --------------------------------------


@pytest.mark.parametrize(
    ("written", "read"),
    [
        (b"open sesame\n", b"open sesame"),
        (b"open sesame", b"open sesame"),
        (b"open sesame\r\n", b"open sesame"),
        (b"open sesame\n\n", b"open sesame\n"),
    ],
)
def test_one_trailing_newline_is_dropped_from_the_passphrase(
    layout: Any, written: bytes, read: bytes
) -> None:
    layout.passphrase.write_bytes(written)
    assert supervise.read_passphrase(layout.passphrase) == read


def test_a_missing_passphrase_is_a_deployment_fault(layout: Any) -> None:
    layout.passphrase.unlink()
    with pytest.raises(supervise.DeploymentError, match="Mount a file holding it"):
        supervise.read_passphrase(layout.passphrase)


@pytest.mark.parametrize("written", [b"", b"\n"])
def test_an_empty_passphrase_is_a_deployment_fault(layout: Any, written: bytes) -> None:
    layout.passphrase.write_bytes(written)
    with pytest.raises(supervise.DeploymentError, match="is empty"):
        supervise.read_passphrase(layout.passphrase)


def test_both_volumes_mounted_pass(layout: Any) -> None:
    supervise.check_volumes(layout, is_mount=lambda _path: True)


@pytest.mark.parametrize("missing", ["data_dir", "keyrings"])
def test_a_directory_in_the_containers_own_layer_is_refused(layout: Any, missing: str) -> None:
    unmounted = getattr(layout, missing)
    with pytest.raises(supervise.DeploymentError, match=f"nothing is mounted at {unmounted}"):
        supervise.check_volumes(layout, is_mount=lambda path: path != unmounted)


def test_a_setting_is_read_ignoring_case() -> None:
    environ = {"assistant_gateway_hosted_address": "10.0.0.2"}
    assert supervise.setting(environ, supervise.HOSTED_ADDRESS) == "10.0.0.2"
    assert supervise.setting({}, supervise.HOSTED_ADDRESS) is None


def test_the_one_private_address_is_bound_and_written_for_exec(layout: Any) -> None:
    environ: dict[str, str] = {}
    address = supervise.settle_hosted_address(
        environ, layout, addresses=lambda: [("lo", "127.0.0.1"), ("eth0", "172.17.0.2")]
    )
    assert address == "172.17.0.2"
    assert environ[supervise.HOSTED_ADDRESS] == "172.17.0.2"
    assert layout.dotenv.read_text(encoding="utf-8") == f"{supervise.HOSTED_ADDRESS}=172.17.0.2\n"
    assert stat.S_IMODE(layout.dotenv.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("held", "match"),
    [
        ([("lo", "127.0.0.1")], "holds 0 besides loopback"),
        ([("eth0", "172.17.0.2"), ("docker0", "172.18.0.1")], "--network host"),
        ([("eth0", "203.0.113.7")], "not a private-use address"),
        ([("tailscale0", "100.101.102.103")], "not a private-use address"),
    ],
)
def test_an_address_that_is_not_one_private_one_is_refused(
    layout: Any, held: list[tuple[str, str]], match: str
) -> None:
    environ: dict[str, str] = {}
    with pytest.raises(supervise.DeploymentError, match=match):
        supervise.settle_hosted_address(environ, layout, addresses=lambda: held)
    assert supervise.HOSTED_ADDRESS not in environ
    assert not layout.dotenv.exists()


def test_a_configured_address_is_kept_and_nothing_is_written(layout: Any) -> None:
    layout.dotenv.write_text("stale\n", encoding="utf-8")
    environ = {supervise.HOSTED_ADDRESS: " 10.88.0.5 "}

    def unasked() -> list[tuple[str, str]]:
        raise AssertionError

    assert supervise.settle_hosted_address(environ, layout, addresses=unasked) == "10.88.0.5"
    assert not layout.dotenv.exists()


@pytest.mark.parametrize("configured", ["", "  "])
def test_a_blank_configured_address_is_refused_rather_than_read_as_unset(
    layout: Any, configured: str
) -> None:
    # The blank would stay in the container's environment and outrank the `.env` for
    # every `docker exec`, whose `Settings` would then refuse it.
    with pytest.raises(supervise.DeploymentError, match="set but blank"):
        supervise.settle_hosted_address(
            {supervise.HOSTED_ADDRESS: configured},
            layout,
            addresses=lambda: [("eth0", "172.17.0.2")],
        )
    assert not layout.dotenv.exists()


@pytest.mark.parametrize("configured", ["127.0.0.1", "::1"])
def test_a_configured_loopback_address_is_refused(layout: Any, configured: str) -> None:
    with pytest.raises(supervise.DeploymentError, match="never its loopback"):
        supervise.settle_hosted_address(
            {supervise.HOSTED_ADDRESS: configured}, layout, addresses=list
        )


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "data_dir": Path("/data"),
        "gateway_hosted_port": 8423,
        "hub_remote_address": None,
        "gateway_remote_address": None,
        "remote_hub_address": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_settings_on_the_volume_with_no_remote_door_pass() -> None:
    supervise.check_settings(_settings(), supervise.Layout())


def test_a_data_directory_off_the_volume_is_refused() -> None:
    with pytest.raises(supervise.DeploymentError, match="Remove ASSISTANT_DATA_DIR"):
        supervise.check_settings(_settings(data_dir=Path("/srv/elsewhere")), supervise.Layout())


@pytest.mark.parametrize(
    "name", ["hub_remote_address", "gateway_remote_address", "remote_hub_address"]
)
def test_a_remote_door_or_a_remote_hub_is_refused(name: str) -> None:
    with pytest.raises(supervise.DeploymentError, match=f"ASSISTANT_{name.upper()}"):
        supervise.check_settings(_settings(**{name: "100.101.102.103"}), supervise.Layout())


@pytest.mark.parametrize(
    ("code", "hub", "container"),
    [
        (0, 0, 0),
        (0, 78, 78),
        (0, 1, 1),
        (0, -9, 1),
        (1, 0, 1),
        (1, 78, 78),
        (78, 0, 78),
        (78, 1, 78),
    ],
)
def test_the_containers_exit_combines_the_runs_and_the_hubs(
    code: int, hub: int, container: int
) -> None:
    assert supervise._settle(code, hub) == container


# --- The keyring probe ------------------------------------------------------------


@pytest.mark.parametrize(
    ("printed", "state"),
    [
        ("unlocked", "UNLOCKED"),
        ("locked\n", "LOCKED"),
        ("absent", "ABSENT"),
        ("Traceback (most recent call last):", "ABSENT"),
        ("", "ABSENT"),
    ],
)
def test_the_probe_reads_the_childs_answer(printed: str, state: str) -> None:
    command = (sys.executable, "-c", f"print({printed!r})")
    assert supervise.keyring_state(command=command) is supervise.KeyringState[state]


def test_a_probe_that_stalls_is_abandoned_at_its_deadline() -> None:
    # A bus that accepted the connection and stopped answering: the child is killed,
    # and the supervisor gets "not yet" in time to read its deadline and a stop.
    command = (sys.executable, "-c", "import time; time.sleep(30)")
    started = time.monotonic()
    assert supervise.keyring_state(command=command, deadline=0.5) is supervise.KeyringState.ABSENT
    assert time.monotonic() - started < 10


def test_the_probe_flag_prints_what_the_bus_says(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(supervise, "ask_the_bus", lambda: supervise.KeyringState.LOCKED)
    assert supervise.main(["--keyring-state"]) == supervise.EXIT_OK
    assert capsys.readouterr().out == "locked\n"


# --- 2 to 5. The supervision, with stand-in children --------------------------------


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


class _Run:
    """One supervised run of the stand-ins, on a thread, with what they recorded."""

    def __init__(self, layout: Any, *, state: Any = None, **variables: str) -> None:
        self.layout = layout
        self.record = layout.runtime_dir.parent / "record"
        self.record.mkdir()
        self.port = _free_port()
        environ = {
            **os.environ,
            "ASSISTANT_DATA_DIR": str(layout.data_dir),
            supervise.HOSTED_ADDRESS: "127.0.0.1",
            "FAKE_BUS": str(layout.bus),
            "FAKE_PORT": str(self.port),
            "FAKE_RECORD": str(self.record),
            **variables,
        }
        fake = (sys.executable, str(_FAKES))
        self.supervisor = supervise.Supervisor(
            layout,
            commands=supervise.Commands(
                bus=(*fake, "bus"),
                keyring=(*fake, "keyring"),
                hub=(*fake, "hub"),
                gateway=(*fake, "gateway"),
            ),
            environ=environ,
            hosted=("127.0.0.1", self.port),
            passphrase=b"open sesame",
            machine=supervise.Machine(
                keyring=lambda: state or supervise.KeyringState.UNLOCKED,
                auxiliary_deadline=3.0,
            ),
        )
        self.code: int | None = None
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        self.code = self.supervisor.serve()

    def until_ready(self) -> None:
        give_up = time.monotonic() + 30
        while not self.layout.ready.exists():
            assert self._thread.is_alive(), f"the run ended with {self.code} before ready"
            assert time.monotonic() < give_up, "the run was not ready in 30 seconds"
            time.sleep(0.05)

    def stop(self) -> None:
        self.supervisor.request_stop(signal.SIGTERM)

    def result(self) -> int:
        self._thread.join(timeout=30)
        assert not self._thread.is_alive(), "the run did not end within 30 seconds"
        assert self.code is not None
        return self.code

    def saw(self, name: str) -> str | None:
        path = self.record / name
        return path.read_text(encoding="utf-8") if path.exists() else None

    def all_ended(self) -> bool:
        children = self.supervisor._children
        return bool(children) and all(child.process.poll() is not None for child in children)


def test_a_stop_reaches_each_child_with_its_own_signal_and_exits_zero(layout: Any) -> None:
    run = _Run(layout)
    run.until_ready()
    run.stop()
    assert run.result() == supervise.EXIT_OK
    assert run.saw("passphrase") == "open sesame"
    assert run.saw("hub.signal") == "SIGTERM"
    assert run.saw("gateway.signal") == "SIGINT"
    assert run.saw("keyring.signal") == "SIGTERM"
    assert run.saw("bus.signal") == "SIGTERM"
    assert run.all_ended()
    assert not layout.ready.exists()


def test_a_second_stop_signal_changes_nothing(layout: Any) -> None:
    run = _Run(layout)
    run.until_ready()
    run.stop()
    run.stop()
    assert run.result() == supervise.EXIT_OK


def test_a_hub_that_drains_to_78_keeps_it(layout: Any) -> None:
    run = _Run(layout, FAKE_HUB_STOP_CODE="78")
    run.until_ready()
    run.stop()
    assert run.result() == supervise.EXIT_DEPLOYMENT


@pytest.mark.parametrize(("status", "container"), [("78", 78), ("1", 1), ("0", 0)])
def test_the_hub_exiting_on_its_own_is_the_containers_exit(
    layout: Any, status: str, container: int
) -> None:
    run = _Run(layout, FAKE_HUB_EXIT_AFTER=f"3:{status}")
    run.until_ready()
    assert run.result() == container
    assert run.saw("gateway.signal") == "SIGINT"
    assert run.all_ended()


def test_a_gateway_that_exits_1_before_it_listens_is_a_restart(layout: Any) -> None:
    # The gateway's `1` is a fault that may clear (#3167), so the container comes back.
    run = _Run(layout, FAKE_GATEWAY_REFUSES="1")
    assert run.result() == supervise.EXIT_RESTART
    assert run.saw("hub.signal") == "SIGTERM"
    assert run.all_ended()


def test_a_gateway_that_refuses_with_78_before_it_listens_is_the_containers_78(
    layout: Any, capfd: pytest.CaptureFixture[str]
) -> None:
    # #3167: the gateway exits `78` only where restarting unchanged never succeeds,
    # so restarting the container would meet the same refusal; it stays down.
    run = _Run(layout, FAKE_GATEWAY_REFUSES="78")
    assert run.result() == supervise.EXIT_DEPLOYMENT
    assert run.saw("hub.signal") == "SIGTERM"
    assert run.all_ended()
    # ADR-0083 §5: the cause and the action are the last thing said, after every
    # child's own last line, and the line carries the code a reader greps for.
    said = capfd.readouterr().err.strip().splitlines()
    assert "hub: stopped on SIGTERM" in said
    last = said[-1]
    assert last.startswith("hub-container: the gateway refused to start")
    assert "names what to change" in last
    assert last.endswith("(exit 78)")


@pytest.mark.parametrize("status", ["2", "77", "79"])
def test_a_gateway_exiting_with_a_code_it_does_not_use_is_a_restart(
    layout: Any, status: str
) -> None:
    # Only the gateway's `78` is a verdict; any other status gets §5's tie-break.
    run = _Run(layout, FAKE_GATEWAY_REFUSES=status)
    assert run.result() == supervise.EXIT_RESTART


def test_a_gateway_a_signal_ends_before_it_listens_is_a_restart(layout: Any) -> None:
    run = _Run(layout, FAKE_GATEWAY_KILLED="1")
    assert run.result() == supervise.EXIT_RESTART
    assert run.saw("hub.signal") == "SIGTERM"
    assert run.all_ended()


def test_a_gateway_that_stops_after_ready_restarts_the_container(layout: Any) -> None:
    run = _Run(layout, FAKE_GATEWAY_EXIT_AFTER="1.5:1")
    run.until_ready()
    assert run.result() == supervise.EXIT_RESTART
    assert run.saw("hub.signal") == "SIGTERM"


def test_a_keyring_the_passphrase_leaves_locked_starts_no_hub(layout: Any) -> None:
    run = _Run(layout, state=supervise.KeyringState.LOCKED)
    assert run.result() == supervise.EXIT_DEPLOYMENT
    assert [child.name for child in run.supervisor._children] == [
        "dbus-daemon",
        "gnome-keyring-daemon",
    ]
    assert run.all_ended()


def test_a_keyring_that_never_registers_is_a_restart(layout: Any) -> None:
    run = _Run(layout, state=supervise.KeyringState.ABSENT)
    assert run.result() == supervise.EXIT_RESTART
    assert "hub" not in [child.name for child in run.supervisor._children]


def test_a_stop_before_the_hub_accepts_drains_it_and_exits_zero(layout: Any) -> None:
    run = _Run(layout, FAKE_HUB_NEVER_ACCEPTS="1")
    give_up = time.monotonic() + 30
    while not any(child.name == "hub" for child in run.supervisor._children):
        assert time.monotonic() < give_up
        time.sleep(0.05)
    run.stop()
    assert run.result() == supervise.EXIT_OK
    assert "gateway" not in [child.name for child in run.supervisor._children]


# --- run(): the checks come before any child ----------------------------------------


def _refusing_spawn(*_args: object, **_kwargs: object) -> subprocess.Popen[bytes]:
    raise AssertionError


def test_a_failed_check_starts_nothing(layout: Any) -> None:
    layout.passphrase.unlink()
    machine = supervise.Machine(
        addresses=lambda: [("eth0", "10.0.0.2")],
        is_mount=lambda _path: True,
        settings=_settings,
        spawn=_refusing_spawn,
        stop_signals=(),
        ignored_signals=(),
    )
    assert supervise.run(layout, {}, machine=machine) == supervise.EXIT_DEPLOYMENT


def test_settings_that_do_not_load_are_left_to_the_hub_to_render(
    layout: Any, capfd: pytest.CaptureFixture[str]
) -> None:
    machine = supervise.Machine(
        addresses=lambda: [("eth0", "10.0.0.2")],
        is_mount=lambda _path: True,
        settings=lambda: None,
        spawn=_refusing_spawn,
        stop_signals=(),
        ignored_signals=(),
    )
    fake = (sys.executable, str(_FAKES))
    commands = supervise.Commands(
        bus=(*fake, "bus"),
        keyring=(*fake, "keyring"),
        hub=(*fake, "settings-refused"),
        gateway=(*fake, "gateway"),
    )
    code = supervise.run(layout, dict(os.environ), machine=machine, commands=commands)
    assert code == supervise.EXIT_DEPLOYMENT
    assert "the hub says why" in capfd.readouterr().err


def test_settings_that_move_the_data_are_refused_before_any_child(layout: Any) -> None:
    machine = supervise.Machine(
        addresses=lambda: [("eth0", "10.0.0.2")],
        is_mount=lambda _path: True,
        settings=lambda: _settings(data_dir=Path("/elsewhere")),
        spawn=_refusing_spawn,
        stop_signals=(),
        ignored_signals=(),
    )
    assert supervise.run(layout, {}, machine=machine) == supervise.EXIT_DEPLOYMENT


# --- The smoke test's own cleanup ---------------------------------------------------


def _load_smoke() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "container_smoke", _ROOT / "deploy" / "container" / "smoke.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["container_smoke"] = module
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke()


class _Smoke:
    def __init__(self, failure: BaseException | None) -> None:
        self.failure = failure
        self.cleaned = False

    def run(self) -> None:
        if self.failure is not None:
            raise self.failure

    def clean(self) -> None:
        self.cleaned = True


def test_each_smoke_run_names_its_own_container_and_volumes() -> None:
    # So a second run on one machine neither collides with the first nor removes what
    # the first created: the cleanup names only this run's resources.
    again = importlib.util.spec_from_file_location(
        "container_smoke_again", _ROOT / "deploy" / "container" / "smoke.py"
    )
    assert again is not None
    assert again.loader is not None
    other = importlib.util.module_from_spec(again)
    again.loader.exec_module(other)
    for name in ("NAME", "DATA", "KEYRING"):
        assert getattr(smoke, name).startswith(f"hub-smoke-{smoke._RUN}")
        assert getattr(smoke, name) != getattr(other, name)


def test_a_passing_smoke_run_cleans_up() -> None:
    run = _Smoke(None)
    assert smoke.drive(run) == 0
    assert run.cleaned


def test_a_failed_check_is_a_one_and_cleans_up() -> None:
    run = _Smoke(smoke.SmokeError("the door was shut"))
    assert smoke.drive(run) == 1
    assert run.cleaned


@pytest.mark.parametrize("failure", [ConnectionRefusedError(), TimeoutError()])
def test_a_transport_failure_raises_after_cleaning_up(failure: OSError) -> None:
    run = _Smoke(failure)
    with pytest.raises(type(failure)):
        smoke.drive(run)
    assert run.cleaned
