"""The overlay agent, spoken to over a socket that behaves like the real one.

ADR-0124 §3 and §4 fix what this seam may and may not do, and both are testable
here because the daemon is reached over a Unix socket: a fake one that speaks the
same HTTP/1.1 answers exercises the parsing, the refusals and the "never from the
peer" rule without a Tailscale installation.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.service.overlay import (
    MAX_OVERLAY_IDENTITY_BYTES,
    TAILSCALE_SOCKETS,
    OverlayIdentityUnavailableError,
    TailscaleAgent,
    local_agent,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

_HUB_ID: Final = "nHUBAAAACNTRL"
_DEVICE: Final = "nLAPTOP1CNTRL"

_STATUS: Final[dict[str, Any]] = {
    "Self": {"StableID": _HUB_ID, "TailscaleIPs": ["100.64.0.9", "fd7a:115c:a1e0::9"]},
}
_WHOIS: Final[dict[str, Any]] = {
    "Node": {"StableID": _DEVICE, "Name": "laptop.example.ts.net"},
    "UserProfile": {"LoginName": "owner@example.com"},
}


@contextlib.asynccontextmanager
async def _daemon(
    tmp_path: Path, answers: dict[str, tuple[int, bytes]]
) -> AsyncIterator[tuple[TailscaleAgent, list[str]]]:
    """A fake local API on a Unix socket, and the paths it was asked for."""
    asked: list[str] = []

    async def _serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.readuntil(b"\r\n\r\n")
        path = request.split(b"\r\n", 1)[0].split(b" ")[1].decode()
        asked.append(path)
        status, body = answers.get(path.split("?")[0], (404, b""))
        head = f"HTTP/1.1 {status} X\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        writer.write(head.encode())
        # Written in two pieces so a client that read one packet and called it the
        # body fails here rather than on a machine with more overlay members.
        writer.write(body[: len(body) // 2])
        await writer.drain()
        await asyncio.sleep(0)
        writer.write(body[len(body) // 2 :])
        await writer.drain()
        writer.close()

    path = tmp_path / "tailscaled.sock"
    server = await asyncio.start_unix_server(_serve, path=str(path))
    try:
        yield TailscaleAgent(path), asked
    finally:
        server.close()
        await server.wait_closed()


def _ok(payload: dict[str, Any]) -> tuple[int, bytes]:
    """A 200 carrying one JSON object."""
    return 200, json.dumps(payload).encode()


def _ok_lenient(payload: dict[str, Any]) -> tuple[int, bytes]:
    """A 200 whose body carries a value only a decoder will produce.

    ``json.dumps`` escapes a lone surrogate as ``\\ud800``, which is what a real
    agent's encoder would emit and what ``json.loads`` turns back into an unencodable
    string — so the fixture has to write the *escape* rather than the character.
    """
    return 200, json.dumps(payload).encode("ascii", errors="backslashreplace")


async def test_the_hubs_own_identity_and_addresses_are_read_from_the_daemon(
    tmp_path: Path,
) -> None:
    """ADR-0124 §3: "the hub binds an address the agent provides".

    Both halves of the answer are used: the identity §6 discloses beside a credential,
    and the addresses §2's bind restriction is checked against.
    """
    async with _daemon(tmp_path, {"/localapi/v0/status": _ok(_STATUS)}) as (agent, _):
        reported = await agent.hub_identity()
    assert reported.identity == _HUB_ID
    assert reported.addresses == frozenset({"100.64.0.9", "fd7a:115c:a1e0::9"})


async def test_a_peer_is_identified_by_the_address_it_connected_from(tmp_path: Path) -> None:
    """ADR-0124 §4: the identity is obtained "from the overlay agent running on the
    hub's own machine, over a local interface".

    The query the agent is asked is part of the property: the *address the socket
    reports* is what is looked up, so there is nothing a peer could have said that
    changes the answer.
    """
    async with _daemon(tmp_path, {"/localapi/v0/whois": _ok(_WHOIS)}) as (agent, asked):
        assert await agent.identify("100.64.0.11", 41234) == _DEVICE
    assert asked == ["/localapi/v0/whois?addr=100.64.0.11:41234"]


async def test_an_ipv6_peer_is_asked_about_in_the_form_the_local_api_expects(
    tmp_path: Path,
) -> None:
    """The bracketed form, which is what a hub on an overlay's IPv6 range meets.

    An unbracketed address would make the port ambiguous and the daemon would answer
    about nobody, which would read as "this peer is unknown" — a refusal for the
    wrong reason, and one that would only appear on a v6 deployment.
    """
    async with _daemon(tmp_path, {"/localapi/v0/whois": _ok(_WHOIS)}) as (agent, asked):
        await agent.identify("fd7a:115c:a1e0::11", 41234)
    assert asked == ["/localapi/v0/whois?addr=[fd7a:115c:a1e0::11]:41234"]


async def test_an_identity_is_never_guessed_from_a_name_or_an_address(tmp_path: Path) -> None:
    """ADR-0124 §6 records an enrolment against an identity that has to survive a
    rename and a reassignment.

    The node here has a ``Name`` and no ``StableID``, which is exactly the record a
    fallback would happily use — and an enrolment keyed on it would follow a rename,
    or worse a reused name, and admit a device the owner never enrolled. So the agent
    refuses, and §4's answer to not knowing is to refuse the connection.
    """
    nameless = {"Node": {"Name": "laptop.example.ts.net"}}
    async with _daemon(tmp_path, {"/localapi/v0/whois": _ok(nameless)}) as (agent, _):
        with pytest.raises(OverlayIdentityUnavailableError, match="no stable identity"):
            await agent.identify("100.64.0.11", 41234)


@pytest.mark.parametrize(
    "answer",
    [
        (404, b""),
        (200, b"not json"),
        (200, b'"a string"'),
        (200, json.dumps({"Node": "not an object"}).encode()),
    ],
)
async def test_every_way_of_not_knowing_is_one_refusal(
    answer: tuple[int, bytes], tmp_path: Path
) -> None:
    """ADR-0124 §4: "a connection whose overlay identity cannot be obtained is
    refused".

    One condition rather than a taxonomy, because "the hub's response to all of them
    is identical and a taxonomy would only invite one branch to become 'admit
    anyway'".
    """
    async with _daemon(tmp_path, {"/localapi/v0/whois": answer}) as (agent, _):
        with pytest.raises(OverlayIdentityUnavailableError):
            await agent.identify("100.64.0.11", 41234)


async def test_a_daemon_that_is_not_there_is_a_refusal_rather_than_a_crash(
    tmp_path: Path,
) -> None:
    """The commonest case in practice: the overlay agent is not running.

    It is the same refusal, which is what lets the hub answer §2's bind question and
    §4's admission question with one rule each rather than with a special case.
    """
    agent = TailscaleAgent(tmp_path / "nothing-here.sock")
    with pytest.raises(OverlayIdentityUnavailableError, match="did not answer"):
        await agent.hub_identity()


async def test_a_status_naming_no_node_for_this_machine_is_refused(tmp_path: Path) -> None:
    """The hub cannot disclose an identity it does not have (ADR-0124 §6), and cannot
    check its own bind address against a list it was not given (§2)."""
    async with _daemon(tmp_path, {"/localapi/v0/status": _ok({})}) as (agent, _):
        with pytest.raises(OverlayIdentityUnavailableError, match="names no node"):
            await agent.hub_identity()


async def test_a_status_with_no_addresses_is_refused(tmp_path: Path) -> None:
    """The discriminating half of the clause above: an identity alone does not let
    the hub decide whether the address it was configured with is on the overlay."""
    async with _daemon(tmp_path, {"/localapi/v0/status": _ok({"Self": {"StableID": _HUB_ID}})}) as (
        agent,
        _,
    ):
        with pytest.raises(OverlayIdentityUnavailableError, match="no usable addresses"):
            await agent.hub_identity()


def test_the_agent_is_located_and_never_launched(tmp_path: Path) -> None:
    """ADR-0124 §3: the agent "is not imported by, embedded in, linked into or
    **launched by** ``ai_assistant``".

    :func:`local_agent` looks at the two paths the daemon is packaged to use and
    otherwise points at the first of them — so a missing daemon becomes a refusal at
    the first query, which is §4's answer, rather than an attempt to start one.
    """
    explicit = local_agent(str(tmp_path / "custom.sock"))
    assert explicit.socket_path == str(tmp_path / "custom.sock")
    assert local_agent().socket_path in TAILSCALE_SOCKETS


async def test_an_identity_with_no_utf8_form_is_refused_rather_than_raised(
    tmp_path: Path,
) -> None:
    """A string a JSON decoder produced is not always a string that can be encoded.

    ``"\\ud800"`` is a lone surrogate: it survives ``json.loads``, passes every type
    and emptiness check, and then raises ``UnicodeEncodeError`` — a ``ValueError``,
    so nothing watching for :class:`OverlayIdentityUnavailableError` catches it.
    An identity that cannot be encoded cannot be recorded, compared or reported, so
    not knowing it is the same condition as not being told it, and takes ADR-0124
    §4's same answer.
    """
    surrogate = {"Node": {"StableID": "\ud800"}}
    async with _daemon(tmp_path, {"/localapi/v0/whois": _ok_lenient(surrogate)}) as (agent, _):
        with pytest.raises(OverlayIdentityUnavailableError, match="no UTF-8 form"):
            await agent.identify("100.64.0.11", 41234)


async def test_this_machines_identity_with_no_utf8_form_is_refused_too(
    tmp_path: Path,
) -> None:
    """The same value on the startup path, where it would otherwise escape the
    configuration-error clause and turn a legible stay-down refusal into an
    unclassified fault."""
    surrogate = {"Self": {"StableID": "\ud800", "TailscaleIPs": ["100.64.0.9"]}}
    async with _daemon(tmp_path, {"/localapi/v0/status": _ok_lenient(surrogate)}) as (agent, _):
        with pytest.raises(OverlayIdentityUnavailableError, match="no UTF-8 form"):
            await agent.hub_identity()


async def test_an_identity_no_overlay_would_produce_is_refused(tmp_path: Path) -> None:
    """The bound, at the seam that produces an identity.

    Refusing here is what keeps every value downstream — the record's rows, the
    enrolment reply, the listing — bounded without each of them re-deriving the
    rule.
    """
    huge = {"Node": {"StableID": "n" * (MAX_OVERLAY_IDENTITY_BYTES + 1)}}
    async with _daemon(tmp_path, {"/localapi/v0/whois": _ok(huge)}) as (agent, _):
        with pytest.raises(OverlayIdentityUnavailableError, match="bytes"):
            await agent.identify("100.64.0.11", 41234)


async def test_an_identity_at_the_bound_is_accepted(tmp_path: Path) -> None:
    """The discriminating half: a bound that refused everything would pass above."""
    longest = {"Node": {"StableID": "n" * MAX_OVERLAY_IDENTITY_BYTES}}
    async with _daemon(tmp_path, {"/localapi/v0/whois": _ok(longest)}) as (agent, _):
        assert await agent.identify("100.64.0.11", 41234) == "n" * MAX_OVERLAY_IDENTITY_BYTES
