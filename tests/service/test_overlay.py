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
import os
import socket
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.service.overlay import (
    MAX_OVERLAY_IDENTITY_BYTES,
    TAILSCALE_SOCKETS,
    OverlayIdentityUnavailableError,
    TailscaleAgent,
    local_agent,
)
from ai_assistant.wire.address import sun_path_limit
from ai_assistant.wire.errors import ProtocolError

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
        try:
            request = await reader.readuntil(b"\r\n\r\n")
        except asyncio.IncompleteReadError:
            # A hub that refuses its peer (ADR-0131 §7) closes without writing, which
            # is the property those cases assert. Swallowed so the refusal reads as a
            # refusal rather than as an unretrieved task exception.
            writer.close()
            return
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


# --- The custody conditions on a configured socket (#918) -------------------
#
# ADR-0124 §4 makes this socket's answer the identity every remote admission turns
# on, and `TAILSCALE_SOCKETS`' two defaults are trusted because "the operating
# system's own access control" protects them. A path an operator can name has to
# earn the same trust, and these are the conditions that make it do so — which is
# what keeps exposing the setting a matter of implementation rather than a change
# to §4's posture.


def _bind(path: Path) -> socket.socket:
    """A real Unix socket at ``path``, so ``S_ISSOCK`` is answered by the kernel."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    return sock


def test_a_configured_socket_under_a_directory_you_own_is_accepted(tmp_path: Path) -> None:
    """The case the setting exists for, and the one #919 had to build a namespace
    to reach: an agent socket the running uid owns, in a directory it owns.
    """
    path = tmp_path / "tailscaled.sock"
    with contextlib.closing(_bind(path)):
        assert local_agent(str(path)).socket_path == str(path)


def test_a_configured_socket_that_is_absent_is_accepted(tmp_path: Path) -> None:
    """The custody check asks who *could* answer, never whether anybody does.

    Refusing an absent socket would contradict :func:`local_agent`'s contract —
    "whether the daemon is actually there is answered by the first query" — and
    would turn a hub that started a moment before its agent into a stay-down
    fault. Nothing is given up: an absent socket answers for nobody, and the
    ancestry walk is what bounds who may place one there later.
    """
    absent = tmp_path / "not-yet.sock"
    assert not absent.exists()

    assert local_agent(str(absent)).socket_path == str(absent)


@pytest.mark.skipif(os.geteuid() == 0, reason="root satisfies every ownership check")
def test_a_configured_socket_whose_ancestor_is_replaceable_is_refused(tmp_path: Path) -> None:
    """A socket anybody can replace answers for the overlay, which is the identity
    ADR-0124 §4 admits every device by — the end the clause exists to prevent,
    reached by the filesystem instead of by the peer.
    """
    loose = tmp_path / "shared"
    loose.mkdir()
    path = loose / "tailscaled.sock"
    with contextlib.closing(_bind(path)):
        loose.chmod(0o777)
        try:
            with pytest.raises(ConfigurationError, match="not sticky"):
                local_agent(str(path))
        finally:
            loose.chmod(0o755)


def test_a_configured_socket_whose_directory_is_missing_is_a_configuration_fault(
    tmp_path: Path,
) -> None:
    """The ordinary typo, and it must not arrive as a defect.

    ADR-0083 §5 maps ``ConfigurationError`` to a stay-down exit; a raw
    ``FileNotFoundError`` out of the composition root would instead be reported as
    an unexpected fault — the hub telling an operator who mistyped a path that the
    hub is broken. The walk cannot establish custody of a directory it cannot read,
    so it says exactly that.
    """
    missing = tmp_path / "no-such-dir" / "tailscaled.sock"

    with pytest.raises(ConfigurationError, match="cannot be read"):
        local_agent(str(missing))


def test_a_configured_path_that_is_not_a_socket_is_refused(tmp_path: Path) -> None:
    """The agent's local API is a Unix socket, so nothing can be asked of a file.

    Refused here rather than left to ``connect``, which would report it as the
    agent declining to answer — a diagnosis that sends the operator to look at
    their daemon instead of at their setting.
    """
    path = tmp_path / "not-a-socket"
    path.write_text("")

    with pytest.raises(ConfigurationError, match="is not a socket"):
        local_agent(str(path))


def test_a_configured_socket_over_the_sun_path_budget_is_refused(tmp_path: Path) -> None:
    """``sun_path`` bounds the path a socket can be *connected* to as much as bound.

    Left unchecked this lands as a bare ``AF_UNIX path too long`` out of
    ``connect``, which is the same failure #554 made legible for the data
    directory.
    """
    path = tmp_path / ("x" * sun_path_limit()) / "tailscaled.sock"

    with pytest.raises(ConfigurationError, match="sun_path budget"):
        local_agent(str(path))


def test_the_packaged_defaults_are_not_held_to_the_configured_conditions() -> None:
    """Unset changes nothing, which is what makes this additive.

    The two packaged paths keep their existing behaviour exactly: they are looked
    at in order, and one of them is returned whether or not a daemon is there. A
    guard that also ran here would refuse every machine with no Tailscale
    installed — including this test run.
    """
    assert local_agent().socket_path in TAILSCALE_SOCKETS


def test_an_absent_configured_socket_in_a_sticky_world_writable_directory_is_refused(
    tmp_path: Path,
) -> None:
    """Adversarial review, round 1: the sticky exception does not extend to a name
    nobody has taken.

    ``/tmp`` is mode ``1777``, and the ancestry walk accepts it — rightly, because
    the sticky bit stops a user renaming or removing an entry they do not own. An
    entry that does not exist yet is neither owned nor removable, so any local user
    can be the first to create ``/tmp/tailscaled.sock``, and whoever creates it
    answers ``whois`` for every device the hub admits (ADR-0124 §4). The window is
    between this check and the first query, and nothing later closes it: the
    connection is a Unix socket with no peer credential check on the hub's side.
    """
    sticky = tmp_path / "shared"
    sticky.mkdir()
    absent = sticky / "tailscaled.sock"
    sticky.chmod(0o1777)

    try:
        with pytest.raises(ConfigurationError, match="could create that socket first"):
            local_agent(str(absent))
    finally:
        sticky.chmod(0o755)


def test_a_socket_that_already_exists_under_a_sticky_directory_is_accepted(
    tmp_path: Path,
) -> None:
    """The discriminating half, and the reason the rule is not simply "no sticky".

    Once the socket exists, the sticky bit is doing exactly the job the ancestry
    walk credits it with: no other user can rename it away and put their own there.
    A rule that refused this too would reject a real deployment for no gain.
    """
    sticky = tmp_path / "shared"
    sticky.mkdir()
    path = sticky / "tailscaled.sock"
    with contextlib.closing(_bind(path)):
        sticky.chmod(0o1777)
        try:
            assert local_agent(str(path)).socket_path == str(path)
        finally:
            sticky.chmod(0o755)


@pytest.mark.skipif(os.geteuid() == 0, reason="root traverses every directory")
def test_a_configured_socket_in_a_non_traversable_directory_is_a_configuration_fault(
    tmp_path: Path,
) -> None:
    """Adversarial review, round 1: the leaf ``stat`` leaked ``PermissionError``.

    A directory the hub's own uid owns but cannot traverse (mode ``0600``) is
    stat-able as a directory, so the ancestry walk passes; the ``stat`` of the
    socket inside it is what fails. Only ``FileNotFoundError`` was caught, so this
    arrived as an unexpected fault — the hub reporting a defect for what is an
    operator's mistyped mode, and skipping ADR-0083 §5's stay-down mapping.
    """
    private = tmp_path / "private"
    private.mkdir()
    private.chmod(0o600)

    try:
        with pytest.raises(ConfigurationError, match="cannot be read"):
            local_agent(str(private / "tailscaled.sock"))
    finally:
        private.chmod(0o755)


def test_a_dangling_symlink_cannot_smuggle_in_an_untrusted_target(tmp_path: Path) -> None:
    """Adversarial review, round 2: the checks must decide about the path that will
    be opened, not the name that was written.

    A symlink at a trusted path pointing at an absent name in a world-writable
    directory passed every condition: ``stat`` follows the link and reports the
    target missing, and the unclaimed-name check then examined the *link's*
    directory, which is trusted. An untrusted user creates the target, the
    connection follows the link, and their process answers for the overlay.
    """
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    loose = tmp_path / "loose"
    loose.mkdir()
    link = trusted / "tailscaled.sock"
    link.symlink_to(loose / "attacker.sock")
    loose.chmod(0o1777)

    try:
        with pytest.raises(ConfigurationError, match="could create that socket first"):
            local_agent(str(link))
    finally:
        loose.chmod(0o755)


def test_a_symlink_to_a_trustworthy_socket_is_accepted_and_canonicalised(
    tmp_path: Path,
) -> None:
    """The discriminating half, and the reason the rule is not "no symlinks".

    A link whose target is as trustworthy as the link is fine — and the agent is
    pointed at the *resolved* path, because connecting to the name would leave the
    gap between what was checked and what is opened that ADR-0084 §1 canonicalises
    ``data_dir`` to close.
    """
    real = tmp_path / "run"
    real.mkdir()
    target = real / "tailscaled.sock"
    link = tmp_path / "link.sock"
    with contextlib.closing(_bind(target)):
        link.symlink_to(target)

        assert local_agent(str(link)).socket_path == str(target)


def test_a_configured_path_that_is_not_a_usable_pathname_is_a_configuration_fault(
    tmp_path: Path,
) -> None:
    """Adversarial review, round 2: an embedded NUL leaked a raw ``ValueError``.

    It survives every string operation — including the ``sun_path`` budget, which
    is a length — and fails inside the first syscall as a ``ValueError`` that no
    ``OSError`` handler catches. A pathname the OS will not accept is an operator's
    mistake, so it takes ADR-0083 §5's stay-down mapping like every other one.
    """
    with pytest.raises(ConfigurationError, match="not a usable pathname"):
        local_agent(f"{tmp_path}/\0agent.sock")


def test_a_pathname_with_non_utf8_bytes_is_measured_and_not_crashed_on(
    tmp_path: Path,
) -> None:
    """Adversarial review, round 3: a valid filename need not be UTF-8.

    A non-UTF-8 byte in the environment reaches Python as a surrogate (PEP 383).
    Measuring the ``sun_path`` budget with ``str.encode("utf-8")`` refuses those,
    so a perfectly valid pathname became a ``UnicodeEncodeError`` that no handler
    caught — a crash instead of a verdict. ``os.fsencode`` round-trips the
    surrogates back to the bytes the kernel is actually handed, which is what the
    budget is about in the first place.
    """
    surrogate = f"{tmp_path}/\udcff.sock"

    agent = local_agent(surrogate)

    assert agent.socket_path == surrogate


def test_a_non_utf8_pathname_over_the_budget_is_still_refused(tmp_path: Path) -> None:
    """The discriminating half: measured, not merely tolerated.

    Two bytes per surrogate is the point — a name that fits as characters can
    still overrun ``sun_path`` as bytes, which is the case a UTF-8 measurement
    would have got wrong even where it did not raise.
    """
    long_name = "\udcff" * sun_path_limit()

    with pytest.raises(ConfigurationError, match="sun_path budget"):
        local_agent(f"{tmp_path}/{long_name}.sock")


def test_a_missing_non_utf8_ancestor_is_reported_and_not_crashed_on(tmp_path: Path) -> None:
    """Adversarial review, round 4: escaping the argument was not enough.

    The path handed in was rendered safely, but the ``OSError`` raised for a
    missing ancestor carries its *own* pathname, and that was interpolated raw —
    so the refusal for a mistyped non-UTF-8 path could not be constructed, and the
    same ``ValueError`` escaped from one line away from where it was fixed. Every
    value the OS hands back now goes through the same rendering, ``strerror``
    included.
    """
    missing = f"{tmp_path}/\udcff/gone/agent.sock"

    with pytest.raises(ConfigurationError, match="cannot be read") as caught:
        local_agent(missing)

    # The refusal names the path in an encodable form rather than omitting it.
    assert R"\xff" in str(caught.value)


async def test_an_agent_socket_a_third_user_answers_is_refused_before_anything_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0131 §7, on the *hub's* request path — the one every admission turns on.

    The custody checks above walk the filesystem, and ADR-0084 §1 says why that is
    not enough: "a walk can be wrong — a bind mount, an ACL, a symlinked ancestor".
    PR #936's review exhibited the attack concretely, an untrusted user replacing
    the socket through a POSIX ACL after every mode has been inspected. So the
    daemon here answers correctly and what is wrong is who is answering, which only
    the kernel can say. Nothing is written to that socket first, so the peer never
    learns which address the hub was asking about either.
    """
    monkeypatch.setattr("ai_assistant.wire.overlay.peer_uid", lambda _sock: os.geteuid() + 1)
    async with _daemon(tmp_path, {"/localapi/v0/whois": _ok(_WHOIS)}) as (agent, asked):
        with pytest.raises(OverlayIdentityUnavailableError, match="runs as uid"):
            await agent.identify("100.64.0.11", 41234)
        assert asked == []


async def test_the_hubs_own_startup_query_authenticates_its_peer_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both questions the hub asks go through one request path, so both are covered.

    Worth pinning separately because ``hub_identity`` is the startup query: a hub
    that bound an address a replaced socket named would be listening where an
    untrusted user chose, before any device had connected at all.
    """
    monkeypatch.setattr("ai_assistant.wire.overlay.peer_uid", lambda _sock: os.geteuid() + 1)
    async with _daemon(tmp_path, {"/localapi/v0/status": _ok(_STATUS)}) as (agent, asked):
        with pytest.raises(OverlayIdentityUnavailableError, match="runs as uid"):
            await agent.hub_identity()
        assert asked == []


async def test_a_daemon_running_as_root_is_admitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Root or us" (ADR-0131 §7): ``tailscaled`` runs as root in the ordinary
    deployment, so a rule demanding the hub's own uid would refuse every real
    installation. The other half — our own euid — is what every other case in this
    file exercises, since the fake daemon runs as the test process.
    """
    monkeypatch.setattr("ai_assistant.wire.overlay.peer_uid", lambda _sock: 0)
    async with _daemon(tmp_path, {"/localapi/v0/whois": _ok(_WHOIS)}) as (agent, _):
        assert await agent.identify("100.64.0.11", 41234) == _DEVICE


async def test_a_platform_with_no_peer_credential_call_refuses_as_the_hub_catches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fail-closed direction, and the *class* is the property (ADR-0131 §7).

    :func:`ai_assistant.wire.peer.peer_uid` fails closed with a ``ProtocolError``,
    and ``service/remote.py`` catches only this module's
    :class:`OverlayIdentityUnavailableError` at its two admission sites — a
    different class from the wire package's identically named one. So a refusal
    reaching a caller as either of those other types is the check firing and the
    refusal it was written for never happening. ``pytest.raises`` here is that
    assertion: neither sibling would satisfy it.
    """

    def _unavailable(_sock: object) -> int:
        raise ProtocolError("this platform exposes no peer-credential call")

    monkeypatch.setattr("ai_assistant.wire.overlay.peer_uid", _unavailable)
    async with _daemon(tmp_path, {"/localapi/v0/whois": _ok(_WHOIS)}) as (agent, asked):
        with pytest.raises(OverlayIdentityUnavailableError, match="peer-credential"):
            await agent.identify("100.64.0.11", 41234)
        assert asked == []
