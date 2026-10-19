"""The gateway's exit code: ADR-0083 §5's table, applied to the gateway (#3167).

``assistant gateway`` used to exit ``1`` for every fault it rendered, so a supervisor
could not leave a gateway that refused a setting down. It now answers the hub's
question — *would restarting, unchanged, ever succeed?* — with the hub's codes:
``78`` where it would not, and ``1`` where it would, even eventually.

Two layers. :func:`exits.exit_code` is held to the verdict each kind of refusal is
raised with; and the command is driven end to end for one refusal of each class the
issue names, so what is proven is the code a supervisor actually reads and the words
an operator reads beside it.
"""

from __future__ import annotations

import errno
import socket
import sys
from io import StringIO
from typing import TYPE_CHECKING, Any

import pytest
from gateway_edge import FakeEdge
from gateway_ports import free_port
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import AssistantError, ConfigurationError
from ai_assistant.interfaces import cli
from ai_assistant.interfaces.gateway import Disclosure, exits
from ai_assistant.wire import HubUnavailableError
from ai_assistant.wire.overlay import MAX_OVERLAY_IDENTITY_BYTES

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=100))
    return buffer


def _flat(rendered: str) -> str:
    """Collapse the console's wrapping and its continuation marker (#2072)."""
    return " ".join(rendered.replace("↳", " ").split())


def _serve(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> int:
    """Run ``assistant gateway`` on ``settings`` and return its exit code."""
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    return CliRunner().invoke(cli.app, ["gateway"]).exit_code


def _failing(exc: BaseException) -> Any:
    """A ``run_gateway`` that fails the way ``exc`` says, for an errno no case can
    provoke portably — a port below 1024 binds for root."""

    async def run(**_kwargs: object) -> None:
        raise exc

    return run


def _unheld_private_address() -> str:
    """A private-use address no interface of this machine holds, found by asking."""
    for candidate in ("10.231.58.199", "172.29.201.17", "192.168.251.233", "10.77.3.5"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((candidate, 0))
            except OSError:
                return candidate
    pytest.skip("every candidate private-use address is held by this machine")


# --- The verdict each refusal is raised with -------------------------------------


def test_a_configuration_refusal_stays_down() -> None:
    assert exits.exit_code(ConfigurationError("a setting")) == exits.EXIT_DEPLOYMENT


def test_a_refusal_that_may_clear_comes_back_though_it_is_a_configuration_error() -> None:
    refusal = exits.ClearableRefusalError("the clock has not reached it")

    assert isinstance(refusal, ConfigurationError)
    assert exits.exit_code(refusal) == exits.EXIT_RESTART


@pytest.mark.parametrize(
    "fault",
    [AssistantError("declined"), HubUnavailableError("no hub"), ValueError("anything else")],
)
def test_every_other_fault_comes_back(fault: BaseException) -> None:
    # §5's tie-break: "a spurious restart is recoverable and a spurious `78` is an outage".
    assert exits.exit_code(fault) == exits.EXIT_RESTART


def test_a_refusal_retyped_by_its_author_keeps_its_verdict() -> None:
    outer = AssistantError("could not start")
    outer.__cause__ = ConfigurationError("a setting")

    assert exits.exit_code(outer) == exits.EXIT_DEPLOYMENT


def test_a_refusal_merely_in_flight_does_not_decide() -> None:
    # `__context__` is whatever was being handled, not what this failure is.
    outer = AssistantError("unrelated")
    outer.__context__ = ConfigurationError("handled elsewhere")

    assert exits.exit_code(outer) == exits.EXIT_RESTART


@pytest.mark.parametrize(
    ("code", "verdict"),
    [
        (errno.EACCES, exits.EXIT_DEPLOYMENT),
        (errno.EPERM, exits.EXIT_DEPLOYMENT),
        (errno.EROFS, exits.EXIT_DEPLOYMENT),
        (errno.ENOTDIR, exits.EXIT_DEPLOYMENT),
        (errno.EISDIR, exits.EXIT_DEPLOYMENT),
        (errno.EADDRINUSE, exits.EXIT_RESTART),
        (errno.EADDRNOTAVAIL, exits.EXIT_RESTART),
        (errno.ENFILE, exits.EXIT_RESTART),
        (errno.EMFILE, exits.EXIT_RESTART),
        (errno.EIO, exits.EXIT_RESTART),
        (None, exits.EXIT_RESTART),
    ],
)
def test_an_operating_system_refusal_is_decided_by_its_errno(
    code: int | None, verdict: int
) -> None:
    fault = OSError(code, "refused") if code is not None else OSError("refused")

    refusal = cli._gateway_did_not_start(fault, port=8422, probes_an_address=False)

    assert isinstance(refusal, ConfigurationError)
    assert exits.exit_code(refusal) == verdict


@pytest.mark.parametrize(
    ("code", "verdict"),
    [
        (errno.EPIPE, exits.EXIT_RESTART),
        (errno.EBADF, exits.EXIT_RESTART),
        (errno.EACCES, exits.EXIT_DEPLOYMENT),
    ],
)
def test_a_standard_output_that_refuses_the_value_is_decided_by_its_errno(
    monkeypatch: pytest.MonkeyPatch, code: int, verdict: int
) -> None:
    # A stream that refused a write is most often a reader that went away, and the
    # next start is handed a new one; only an errno no restart changes stays down.
    class _Refusing:
        def write(self, _text: str) -> int:
            raise OSError(code, "refused")

        def flush(self) -> None:  # pragma: no cover — never reached
            pass

    monkeypatch.setattr(sys, "stdout", _Refusing())
    disclosure = Disclosure(
        value="v",
        origins=("http://127.0.0.1:8422",),
        live_sessions=0,
        max_sessions=8,
        mint_act=None,
    )

    with pytest.raises(ConfigurationError) as refused:
        cli._disclose_bootstrap(disclosure)

    assert exits.exit_code(refused.value) == verdict


# --- The command: each class of refusal, end to end -------------------------------


def test_settings_that_will_not_load_exit_78_and_say_it_stays_down(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    monkeypatch.setenv("ASSISTANT_GATEWAY_PORT", "not-a-port")

    result = CliRunner().invoke(cli.app, ["gateway"])
    rendered = _flat(output.getvalue())

    assert result.exit_code == exits.EXIT_DEPLOYMENT
    assert "gateway_port" in rendered
    # ADR-0083 §5: every `78` prints its cause and the operator action.
    assert "stays down (exit 78)" in rendered
    assert "Change what the line above names, then start it again" in rendered


def test_a_hosted_device_the_wire_cannot_name_exits_78(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, output: StringIO
) -> None:
    """A ``ConfigurationError`` from the hosted listener's start checks (ADR-0327 §10:3)."""
    settings = Settings(
        data_dir=tmp_path,
        gateway_port=free_port(),
        **FakeEdge().settings(
            gateway_hosted_port=free_port(),
            gateway_hosted_device="d" * (MAX_OVERLAY_IDENTITY_BYTES + 1),
        ),
    )

    assert _serve(monkeypatch, settings) == exits.EXIT_DEPLOYMENT
    rendered = _flat(output.getvalue())
    assert "gateway_hosted_device cannot be named on the wire" in rendered
    assert "stays down (exit 78)" in rendered


def test_an_edge_key_that_will_not_load_exits_78(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, output: StringIO
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        gateway_port=free_port(),
        **FakeEdge().settings(gateway_hosted_port=free_port()),
    )

    def refuse(_raw: bytes) -> None:
        msg = "not a point"
        raise ValueError(msg)

    monkeypatch.setattr(
        "ai_assistant.interfaces.gateway.edge.Ed25519PublicKey.from_public_bytes", refuse
    )

    assert _serve(monkeypatch, settings) == exits.EXIT_DEPLOYMENT
    rendered = _flat(output.getvalue())
    assert "gateway_edge_public_keys[0]" in rendered
    assert "stays down (exit 78)" in rendered


def test_a_hosted_address_this_machine_does_not_hold_exits_78(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, output: StringIO
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        gateway_port=free_port(),
        **FakeEdge().settings(
            gateway_hosted_address=_unheld_private_address(), gateway_hosted_port=free_port()
        ),
    )

    assert _serve(monkeypatch, settings) == exits.EXIT_DEPLOYMENT
    rendered = _flat(output.getvalue())
    assert "not an address of this machine" in rendered
    assert "ASSISTANT_GATEWAY_HOSTED_ADDRESS" in rendered
    assert "stays down (exit 78)" in rendered


def test_a_permission_the_operating_system_refuses_exits_78(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, output: StringIO
) -> None:
    monkeypatch.setattr(cli, "run_gateway", _failing(OSError(errno.EACCES, "permission denied")))

    assert _serve(monkeypatch, Settings(data_dir=tmp_path)) == exits.EXIT_DEPLOYMENT
    rendered = _flat(output.getvalue())
    assert "permission denied" in rendered
    assert "stays down (exit 78)" in rendered


def test_a_port_another_process_holds_exits_1_and_claims_nothing_stays_down(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, output: StringIO
) -> None:
    """Whatever holds the port is serving or stopping, and both resolve unattended."""
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = int(held.getsockname()[1])

        code = _serve(monkeypatch, Settings(data_dir=tmp_path, gateway_port=port))

    rendered = _flat(output.getvalue())
    assert code == exits.EXIT_RESTART
    assert f"could not bind port {port}" in rendered
    assert "stays down" not in rendered


def test_descriptors_exhausted_for_a_moment_exit_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, output: StringIO
) -> None:
    """The issue's own example of a fault that clears: ``ENFILE`` opening a listener."""
    monkeypatch.setattr(
        cli, "run_gateway", _failing(OSError(errno.ENFILE, "too many open files in system"))
    )

    assert _serve(monkeypatch, Settings(data_dir=tmp_path)) == exits.EXIT_RESTART
    assert "stays down" not in _flat(output.getvalue())
