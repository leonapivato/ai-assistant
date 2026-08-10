"""Asking this machine's overlay agent who holds an address (ADR-0124 §4).

Driven against a real Unix socket speaking real HTTP/1.1, because the module's own
argument is that a fixed ``GET`` is smaller than the dependency that would perform
it (ADR-0124 §3: the agent "is not imported by, embedded in, linked into or
launched by ``ai_assistant``"). A test that mocked the request would leave the
hand-written half — the status line, the ``Connection: close`` body, the ceiling —
unexercised, which is the half that can be wrong.

Marked ``integration`` for the reason ``CONTRIBUTING.md`` gives: a Unix socket is
the filesystem. Nothing here reaches a network or a real daemon.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING

import pytest

from ai_assistant.wire.errors import OverlayIdentityUnavailableError
from ai_assistant.wire.overlay import (
    MAX_OVERLAY_IDENTITY_BYTES,
    TAILSCALE_SOCKETS,
    TailscaleAgent,
    local_agent,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

pytestmark = pytest.mark.integration

HUB = "nQ8xYt2CNTRL"


class FakeLocalApi:
    """A daemon socket that answers one request however a case asks.

    Attributes:
        requested: The request lines it received, so a case can assert what was
            asked rather than only what came back.
    """

    def __init__(self, respond: Callable[[str], bytes]) -> None:
        self.requested: list[str] = []
        self._respond = respond

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        line = head.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        self.requested.append(line)
        writer.write(self._respond(line))
        await writer.drain()
        writer.close()


@contextlib.asynccontextmanager
async def _agent(path: Path, respond: Callable[[str], bytes]) -> AsyncIterator[TailscaleAgent]:
    """Run a fake local API on ``path`` and hand back an agent pointed at it."""
    api = FakeLocalApi(respond)
    server = await asyncio.start_unix_server(api._serve, path=str(path))
    try:
        agent = TailscaleAgent(path)
        agent.api = api  # type: ignore[attr-defined]  # the case reads what was asked
        yield agent
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()


def _ok(body: object) -> bytes:
    """A 200 with a JSON body, closed at the end so the body's end is unambiguous."""
    encoded = json.dumps(body).encode("utf-8")
    return (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n" + encoded
    )


async def test_a_known_node_answers_with_its_stable_identity(tmp_path: Path) -> None:
    """The ordinary path, and the identity is the stable one."""
    async with _agent(tmp_path / "d.sock", lambda _line: _ok({"Node": {"StableID": HUB}})) as agent:
        assert await agent.identify("100.64.1.7", 50084) == HUB


async def test_the_address_asked_about_is_the_one_it_was_given(tmp_path: Path) -> None:
    """The question is about the destination, which is what makes the answer mean anything.

    An agent asked about the wrong address would answer about the wrong node, and
    the comparison against the enrolled identity would then be a check on nothing.
    """
    async with _agent(tmp_path / "d.sock", lambda _line: _ok({"Node": {"StableID": HUB}})) as agent:
        await agent.identify("100.64.1.7", 50084)
        assert "addr=100.64.1.7:50084" in agent.api.requested[0]  # type: ignore[attr-defined]


async def test_an_ipv6_address_is_bracketed(tmp_path: Path) -> None:
    """The form the local API's ``addr`` expects, and the form an overlay v6 range meets."""
    async with _agent(tmp_path / "d.sock", lambda _line: _ok({"Node": {"StableID": HUB}})) as agent:
        await agent.identify("fd7a:115c:a1e0::1", 50084)
        assert "addr=[fd7a:115c:a1e0::1]:50084" in agent.api.requested[0]  # type: ignore[attr-defined]


async def test_a_node_the_agent_does_not_know_is_a_refusal(tmp_path: Path) -> None:
    """ "A client refuses a destination it cannot name rather than dialling it" (§4)."""
    async with _agent(tmp_path / "d.sock", lambda _line: _ok({})) as agent:
        with pytest.raises(OverlayIdentityUnavailableError):
            await agent.identify("100.64.1.7", 50084)


async def test_a_node_with_no_stable_identity_is_refused_rather_than_guessed(
    tmp_path: Path,
) -> None:
    """**No fallback to a name or an address**, and that is the security property.

    An enrolment recorded against a renameable value would follow a rename, and one
    recorded against an address would follow a reassignment — so a client comparing
    against either would accept a node that had merely acquired the hub's name.
    """
    answer = {"Node": {"Name": "hub.example.ts.net", "TailscaleIPs": ["100.64.1.7"]}}
    async with _agent(tmp_path / "d.sock", lambda _line: _ok(answer)) as agent:
        with pytest.raises(OverlayIdentityUnavailableError) as raised:
            await agent.identify("100.64.1.7", 50084)
        assert "name or an address" in str(raised.value)


async def test_a_refusal_from_the_daemon_is_a_refusal_here(tmp_path: Path) -> None:
    """A non-200 is not an answer, and is not treated as one."""
    forbidden = b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n"
    async with _agent(tmp_path / "d.sock", lambda _line: forbidden) as agent:
        with pytest.raises(OverlayIdentityUnavailableError) as raised:
            await agent.identify("100.64.1.7", 50084)
        assert "403" in str(raised.value)


async def test_a_body_that_is_not_json_is_a_refusal(tmp_path: Path) -> None:
    """Because an answer that does not parse is the same condition as no answer."""
    garbage = b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nnot json at all"
    async with _agent(tmp_path / "d.sock", lambda _line: garbage) as agent:
        with pytest.raises(OverlayIdentityUnavailableError) as raised:
            await agent.identify("100.64.1.7", 50084)
        assert "not JSON" in str(raised.value)


async def test_a_json_body_that_is_not_an_object_is_a_refusal(tmp_path: Path) -> None:
    """A list decodes cleanly and answers nothing, which is a different failure."""
    async with _agent(tmp_path / "d.sock", lambda _line: _ok([1, 2, 3])) as agent:
        with pytest.raises(OverlayIdentityUnavailableError):
            await agent.identify("100.64.1.7", 50084)


async def test_a_body_arriving_in_pieces_is_read_whole(tmp_path: Path) -> None:
    """``read(n)`` returns whatever one packet carried, which is not "the body".

    A single read is a fragment that then fails to parse as JSON, and the failure is
    intermittent — it depends on how the kernel happened to split the write, so it
    passes in CI and refuses a real daemon on a slow machine.
    """
    identity = "N" * 32
    padding = "x" * 20_000  # a real ``whois`` answer carries far more than the id
    body = json.dumps({"Node": {"StableID": identity, "Name": padding}}).encode("utf-8")

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n")
        await writer.drain()
        for start in range(0, len(body), 512):
            writer.write(body[start : start + 512])
            await writer.drain()
            await asyncio.sleep(0)
        writer.close()

    path = tmp_path / "d.sock"
    server = await asyncio.start_unix_server(serve, path=str(path))
    try:
        assert await TailscaleAgent(path).identify("100.64.1.7", 50084) == identity
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()


async def test_no_daemon_at_the_path_is_a_refusal(tmp_path: Path) -> None:
    """And it says what to do, because this is what a device with no overlay hits."""
    agent = TailscaleAgent(tmp_path / "nothing.sock")

    with pytest.raises(OverlayIdentityUnavailableError) as raised:
        await agent.identify("100.64.1.7", 50084)

    assert "start the" in str(raised.value)
    assert "sends nothing" in str(raised.value)


def test_the_agent_is_pointed_at_a_path_without_probing(tmp_path: Path) -> None:
    """Constructing one asks nothing, so "is the overlay up" is asked when a command chose.

    :class:`~ai_assistant.wire.client.HubEngineClient` takes the same shape for the
    same reason, and here it also keeps a device with no overlay from failing at
    import time.
    """
    chosen = local_agent([str(tmp_path / "absent.sock")])

    assert chosen.socket_path == str(tmp_path / "absent.sock")


def test_the_first_existing_socket_wins(tmp_path: Path) -> None:
    """Two packaging layouts, tried in order."""
    second = tmp_path / "second.sock"
    second.touch()

    chosen = local_agent([str(tmp_path / "first.sock"), str(second)])

    assert chosen.socket_path == str(second)


def test_where_none_exists_the_first_candidate_names_the_refusal(tmp_path: Path) -> None:
    """So the message names a path rather than an absence."""
    first = str(tmp_path / "first.sock")

    chosen = local_agent([first, str(tmp_path / "second.sock")])

    assert chosen.socket_path == first


def test_the_default_candidates_are_the_two_packaged_layouts() -> None:
    """Pinned so a lane that adds a third has to say so."""
    assert TAILSCALE_SOCKETS == (
        "/var/run/tailscale/tailscaled.sock",
        "/run/tailscale/tailscaled.sock",
    )


async def test_an_identity_no_overlay_produces_is_refused(tmp_path: Path) -> None:
    """Bounded where it is produced, so nothing downstream re-derives the bound.

    An identity this client cannot compare against the enrolled one is one it does
    not know, and §4's answer to not knowing is that the destination is refused.
    """
    huge = {"Node": {"StableID": "N" * (MAX_OVERLAY_IDENTITY_BYTES + 1)}}
    async with _agent(tmp_path / "d.sock", lambda _line: _ok(huge)) as agent:
        with pytest.raises(OverlayIdentityUnavailableError) as raised:
            await agent.identify("100.64.1.7", 50084)
        assert str(MAX_OVERLAY_IDENTITY_BYTES) in str(raised.value)


async def test_an_identity_with_no_utf8_form_is_refused(tmp_path: Path) -> None:
    """A lone surrogate survives ``json.loads`` and has no byte form at all.

    It is the case that survives every other check — non-blank, one character, and
    with no length — so measuring it *is* encoding it, and a bound written as
    ``len(x.encode())`` would raise ``UnicodeEncodeError`` out of the seam.
    """
    body = b'HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n{"Node": {"StableID": "\\ud800"}}'
    async with _agent(tmp_path / "d.sock", lambda _line: body) as agent:
        with pytest.raises(OverlayIdentityUnavailableError) as raised:
            await agent.identify("100.64.1.7", 50084)
        assert "UTF-8" in str(raised.value)
