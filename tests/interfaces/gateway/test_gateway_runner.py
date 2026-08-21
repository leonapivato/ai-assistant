"""Composing the gateway process: mint, disclose, then bind (ADR-0168 §1, §5).

The order is the subject. §5 requires that "a gateway that cannot disclose its
bootstrap value does not start, and reports why", which is only a rule if the
disclosure happens *before* the listener — a gateway that bound first and then
failed to print would be answering a port with a value nobody can present.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import sys

import pytest
import structlog
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.interfaces import cli
from ai_assistant.interfaces.gateway import run_gateway
from ai_assistant.testing import FakeAssistantEngine

pytestmark = pytest.mark.integration


def _free_port() -> int:
    """A port nothing is listening on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def _is_listening(port: int) -> bool:
    """Whether anything answers on that loopback port."""
    try:
        _, writer = await asyncio.open_connection("127.0.0.1", port)
    except OSError:
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


async def _wait_until_listening(port: int) -> None:
    """Give the bind a bounded number of turns to happen, then give up.

    Bounded rather than open-ended so a gateway that never binds fails the case
    instead of hanging it.
    """
    for _ in range(200):
        if await _is_listening(port):
            return
        await asyncio.sleep(0.01)
    pytest.fail(f"nothing bound {port}")


async def test_a_gateway_that_cannot_disclose_its_bootstrap_value_does_not_start() -> None:
    """§5's refusal, and the check that it fires *before* the bind."""
    settings = Settings(gateway_port=_free_port())

    def refuse(_value: str, _origin: str) -> None:
        msg = "standard output is not writable"
        raise ConfigurationError(msg)

    with pytest.raises(ConfigurationError, match="not writable"):
        await run_gateway(settings=settings, engine=FakeAssistantEngine(), disclose=refuse)

    assert not await _is_listening(settings.gateway_port)


async def test_the_value_is_disclosed_once_with_the_origin_before_the_listener_binds() -> None:
    """What the owner is handed: one value, and where to present it."""
    settings = Settings(gateway_port=_free_port())
    disclosed: list[tuple[str, str]] = []

    async def run() -> None:
        await run_gateway(
            settings=settings,
            engine=FakeAssistantEngine(),
            disclose=lambda value, origin: disclosed.append((value, origin)),
        )

    task = asyncio.create_task(run())
    await _wait_until_listening(settings.gateway_port)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert len(disclosed) == 1
    value, origin = disclosed[0]
    assert origin == f"http://127.0.0.1:{settings.gateway_port}"
    assert value


def test_the_bootstrap_value_is_written_to_standard_output_and_not_logged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§5: disclosed "on its own standard output… not in a log record".

    The clause "buys less than it looks like, and saying so is better than letting
    a later reader over-read it" — the structured records go to standard output
    too, so what it keeps the value out of is the *structured* stream, "out of
    anything that parses those records, and out of the redaction chain's reach
    where a missed key would be the failure".
    """
    with structlog.testing.capture_logs() as records:
        cli._disclose_bootstrap("the-value", "http://127.0.0.1:8422")

    written = capsys.readouterr().out
    assert "the-value" in written
    assert "http://127.0.0.1:8422" in written
    assert not [record for record in records if "the-value" in str(record)]


def test_a_disclosure_that_cannot_be_written_reports_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of §5's clause: it "reports why" rather than failing bare.

    A process whose standard output cannot be written to cannot hand the owner the
    one value that admits a browser, so it does not go on to bind a port nobody
    can use.
    """

    class _Closed:
        """A stream that refuses every write, as a closed one does."""

        def write(self, _text: str) -> int:
            """Refuse."""
            msg = "closed"
            raise OSError(msg)

        def flush(self) -> None:
            """Never reached."""

    monkeypatch.setattr(sys, "stdout", _Closed())

    with pytest.raises(ConfigurationError, match="standard output"):
        cli._disclose_bootstrap("value", "origin")


def test_the_gateway_is_a_subcommand_of_the_assistant_script() -> None:
    """ADR-0168 §1: "a subcommand of the existing ``assistant`` console script, not
    a new one" — the first time ADR-0084 §6's rule has been found not to fire."""
    result = CliRunner().invoke(cli.app, ["gateway", "--help"])

    assert result.exit_code == 0
    assert "browsers" in result.stdout
