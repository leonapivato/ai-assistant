"""Stand-ins for the container's four children, for ``test_container_supervise.py``.

    python _fake_children.py ROLE

Each behaves as the supervisor needs its real counterpart to, and no further: the bus
makes its socket path exist, the keyring records the passphrase it was given on its
standard input, the hub accepts on ``<data_dir>/hub.sock`` and drains on ``SIGTERM``,
and the gateway accepts on the hosted address and stops on ``SIGINT``. What each does
differently is read from ``FAKE_*`` variables, and what it saw is written under
``FAKE_RECORD``.
"""

from __future__ import annotations

import os
import signal
import socket
import sys
import time
from pathlib import Path


def _record(name: str, text: str) -> None:
    (Path(os.environ["FAKE_RECORD"]) / name).write_text(text, encoding="utf-8")


def _park(stop_signal: signal.Signals, *, role: str, code: int) -> None:
    """Wait for ``stop_signal``, record it, and exit ``code``."""

    def stop(signum: int, _frame: object) -> None:
        _record(f"{role}.signal", signal.Signals(signum).name)
        sys.exit(code)

    signal.signal(stop_signal, stop)
    exit_after = os.environ.get(f"FAKE_{role.upper()}_EXIT_AFTER")
    started = time.monotonic()
    while True:
        if exit_after is not None:
            seconds, _, status = exit_after.partition(":")
            if time.monotonic() - started >= float(seconds):
                sys.exit(int(status))
        time.sleep(0.05)


def main(role: str) -> None:
    """Behave as ``role``."""
    if role == "bus":
        Path(os.environ["FAKE_BUS"]).write_text("", encoding="utf-8")
        _park(signal.SIGTERM, role=role, code=0)
    elif role == "keyring":
        _record("passphrase", sys.stdin.buffer.read().decode("utf-8"))
        _park(signal.SIGTERM, role=role, code=0)
    elif role == "hub":
        if os.environ.get("FAKE_HUB_NEVER_ACCEPTS"):
            _park(signal.SIGTERM, role=role, code=0)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(Path(os.environ["ASSISTANT_DATA_DIR"]) / "hub.sock"))
        listener.listen()
        _park(signal.SIGTERM, role=role, code=int(os.environ.get("FAKE_HUB_STOP_CODE", "0")))
    elif role == "gateway":
        if os.environ.get("FAKE_GATEWAY_REFUSES"):
            sys.exit(1)
        if os.environ.get("FAKE_GATEWAY_KILLED"):
            os.kill(os.getpid(), signal.SIGKILL)
        listener = socket.create_server(
            (os.environ["ASSISTANT_GATEWAY_HOSTED_ADDRESS"], int(os.environ["FAKE_PORT"]))
        )
        listener.listen()
        _park(signal.SIGINT, role=role, code=0)
    elif role == "settings-refused":
        print("invalid configuration: the hub says why", file=sys.stderr)
        sys.exit(78)


if __name__ == "__main__":
    main(sys.argv[1])
