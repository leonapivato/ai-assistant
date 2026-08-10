"""The hub-local entry point for the owner's device acts (ADR-0124 §6, §8).

The record's own promises are in ``test_enrolment.py``; what is here is the door
they are performed through — that it exists on the hub's own machine, that it is
owner-only, that the credential crosses it once, and that a revocation performed
through it reaches the running hub's connections.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import stat
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.service.admin import ADMIN_FRAME_BYTES, ADMIN_TIMEOUT, AdminListener
from ai_assistant.service.device import _perform, _render
from ai_assistant.service.enrolment import (
    ENROLMENTS_FILENAME,
    LISTING_LIMIT,
    DeviceRegistry,
    EnrolmentStore,
)
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART
from ai_assistant.wire.address import ADMIN_SOCKET_FILENAME
from ai_assistant.wire.credential import is_well_formed, verifier_for
from ai_assistant.wire.framing import read_frame, write_frame

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

_MOMENT: Final = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
_HUB_ID: Final = "nHUBAAAACNTRL"
_DEVICE: Final = "nLAPTOP1CNTRL"


def _clock() -> datetime:
    """A fixed instant, so a recorded date is an assertion rather than an approximation."""
    return _MOMENT


@contextlib.asynccontextmanager
async def _admin(tmp_path: Path) -> AsyncIterator[tuple[AdminListener, DeviceRegistry]]:
    """One control socket, bound and unbound around the body."""
    store = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    registry = DeviceRegistry(store, hub_identity=_HUB_ID)
    listener = AdminListener(registry, data_dir=tmp_path, now=_clock)
    await listener.start()
    try:
        yield listener, registry
    finally:
        await listener.stop_accepting()
        await listener.aclose()
        store.close()


async def _act(listener: AdminListener, request: dict[str, Any]) -> Any:
    """Perform one act the way the console script does, and read the answer."""
    reader, writer = await asyncio.open_unix_connection(str(listener.path))
    try:
        await write_frame(
            writer, json.dumps(request).encode("utf-8"), max_frame_bytes=ADMIN_FRAME_BYTES
        )
        body = await read_frame(
            reader,
            max_frame_bytes=ADMIN_FRAME_BYTES,
            timeout=ADMIN_TIMEOUT,
            idle_timeout=ADMIN_TIMEOUT,
        )
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
    return json.loads(body)


async def test_the_control_socket_is_inside_the_data_directory_and_owner_only(
    tmp_path: Path,
) -> None:
    """ADR-0124 §6: the act is performed "at the hub — on the hub's own machine".

    A Unix socket in the data directory is what makes "on this machine" a property of
    the address family rather than of a check, and ``0600`` is ADR-0004 §4's posture
    applied to it — the same bit that makes ``hub.sock`` "reuse a ratified access
    control where a TCP loopback port has none" (ADR-0084 §1). Read off the file the
    listener bound, so a bind under a permissive umask that forgot the ``chmod``
    fails here.
    """
    async with _admin(tmp_path) as (listener, _):
        assert listener.path == tmp_path / ADMIN_SOCKET_FILENAME
        assert stat.S_IMODE(listener.path.stat().st_mode) == 0o600


async def test_the_socket_is_removed_when_the_hub_stops_accepting(tmp_path: Path) -> None:
    """The same rule ADR-0084 §1 gives ``hub.sock``: unlinked at the start of phase A.

    A stale control socket left behind would have the device command hang against
    nothing rather than saying the hub is not running, which is the failure ADR-0083's
    ruling 4 exists to prevent.
    """
    async with _admin(tmp_path) as (listener, _):
        assert listener.path.exists()
        await listener.stop_accepting()
        assert not listener.path.exists()


async def test_an_enrolment_discloses_the_credential_and_the_hub_identity(
    tmp_path: Path,
) -> None:
    """ADR-0124 §6: minted, "disclosed to the owner once at enrolment and never
    again", with "the hub's own overlay identity" beside it.

    The credential is checked to be a value of the scheme rather than merely
    non-empty, because a surface that returned a placeholder would satisfy the weaker
    assertion and hand the owner something no listener will ever admit.
    """
    async with _admin(tmp_path) as (listener, registry):
        reply = await _act(listener, {"act": "enrol", "identity": _DEVICE})
        assert reply["ok"]
        assert is_well_formed(reply["credential"])
        assert reply["hub_identity"] == _HUB_ID
        assert reply["rotated"] is False
        assert registry.verify(_DEVICE, reply["credential"]).enrolment_id is not None


async def test_the_credential_is_disclosed_once_and_no_act_reads_it_back(
    tmp_path: Path,
) -> None:
    """ADR-0124 §6: "never again", which is a property of the surface as well as of
    the store.

    A listing that carried the credential — or the verifier, which §7 forbids in a
    refusal for the same reason — would make "once" false without any change to what
    the record holds.
    """
    async with _admin(tmp_path) as (listener, _):
        minted = await _act(listener, {"act": "enrol", "identity": _DEVICE})
        listed = await _act(listener, {"act": "list"})
    rendered = json.dumps(listed)
    assert minted["credential"] not in rendered
    assert "verifier" not in rendered
    assert "credential" not in rendered


async def test_re_enrolling_reports_that_it_rotated(tmp_path: Path) -> None:
    """ADR-0124 §6's single act, reported so the surface can say what it did.

    An owner who runs the enrolment twice must be told the first credential is now
    dead — otherwise a device still holding it looks broken for a reason nobody
    recorded.
    """
    async with _admin(tmp_path) as (listener, registry):
        first = await _act(listener, {"act": "enrol", "identity": _DEVICE})
        second = await _act(listener, {"act": "enrol", "identity": _DEVICE})
        assert second["rotated"] is True
        assert second["credential"] != first["credential"]
        assert registry.verify(_DEVICE, first["credential"]).enrolment_id is None


async def test_a_revocation_through_the_socket_reaches_the_running_hubs_record(
    tmp_path: Path,
) -> None:
    """ADR-0124 §8's act, performed by the hub rather than beside it.

    This is why the entry point is a socket to the running process and not an offline
    tool that takes the instance lock: the acts have to reach a hub that is *serving*,
    because "revoking a device closes any connection that device currently holds" and
    a stopped hub has none to close.
    """
    expelled: list[tuple[str, str]] = []
    async with _admin(tmp_path) as (listener, registry):
        registry.when_expelled(lambda identity, reason: expelled.append((identity, reason)))
        await _act(listener, {"act": "enrol", "identity": _DEVICE})
        reply = await _act(listener, {"act": "revoke", "identity": _DEVICE})
        assert reply == {"ok": True, "revoked": True}
        assert expelled == [(_DEVICE, "revoked")]


async def test_revoking_a_device_that_holds_nothing_says_so(tmp_path: Path) -> None:
    """Reported rather than refused, and reported honestly: the surface says nothing
    changed instead of claiming an act it did not perform."""
    async with _admin(tmp_path) as (listener, _):
        assert await _act(listener, {"act": "revoke", "identity": _DEVICE}) == {
            "ok": True,
            "revoked": False,
        }


async def test_the_listing_keeps_revoked_enrolments_and_dates_them(tmp_path: Path) -> None:
    """ADR-0124 §6: "a revocation is recorded rather than erasing the enrolment it
    revokes, so the record says what the owner actually decided and when".

    A listing that showed only live devices would make the record's own point
    unreadable — the owner could not tell "I never enrolled this" from "I revoked it".
    """
    async with _admin(tmp_path) as (listener, _):
        await _act(listener, {"act": "enrol", "identity": _DEVICE})
        await _act(listener, {"act": "revoke", "identity": _DEVICE})
        listed = await _act(listener, {"act": "list"})
    assert listed["hub_identity"] == _HUB_ID
    (device,) = listed["devices"]
    assert device["overlay_identity"] == _DEVICE
    assert device["enrolled_at"] == _MOMENT.isoformat()
    assert device["revoked_at"] == _MOMENT.isoformat()
    assert device["live"] is False


@pytest.mark.parametrize(
    "request_body",
    [
        {"act": "enrol"},
        {"act": "enrol", "identity": "   "},
        {"act": "enrol", "identity": 7},
        {"act": "purge", "identity": _DEVICE},
        {"identity": _DEVICE},
    ],
)
async def test_a_malformed_act_is_refused_and_changes_nothing(
    request_body: dict[str, Any], tmp_path: Path
) -> None:
    """The surface refuses rather than guessing, and the record is untouched.

    ADR-0124 §6 puts a hard fence around what may create an enrolment — "no model,
    plan, tool, scheduler job, ``Settings`` value, migration or upgrade may create
    one" — so a request the hub cannot read must not become one by default.
    """
    async with _admin(tmp_path) as (listener, registry):
        reply = await _act(listener, request_body)
        assert reply["ok"] is False
        assert registry.enrolments() == ([], 0)


async def test_a_request_that_is_not_json_is_abandoned_without_taking_the_hub_down(
    tmp_path: Path,
) -> None:
    """One act's fault is never the resident process's, which is the same rule
    ``serve_connection`` keeps for a spoke (ADR-0084 §3)."""
    async with _admin(tmp_path) as (listener, registry):
        reader, writer = await asyncio.open_unix_connection(str(listener.path))
        try:
            await write_frame(writer, b"\xff\xfe not json", max_frame_bytes=ADMIN_FRAME_BYTES)
            body = await read_frame(
                reader,
                max_frame_bytes=ADMIN_FRAME_BYTES,
                timeout=ADMIN_TIMEOUT,
                idle_timeout=ADMIN_TIMEOUT,
            )
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        assert json.loads(body)["ok"] is False
        # Still serving: the next act succeeds on the same listener.
        assert (await _act(listener, {"act": "enrol", "identity": _DEVICE}))["ok"]
        assert registry.enrolments()[1] == 1


def test_the_command_prints_the_credential_and_says_it_is_shown_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The operator-facing half of ADR-0124 §6's "once".

    An owner who is not told that the value will not be shown again is an owner who
    closes the terminal, and the hub keeps only a verifier — so the instruction is
    part of the act rather than documentation elsewhere.
    """
    code = _render(
        {
            "ok": True,
            "credential": "a" * 43,
            "hub_identity": _HUB_ID,
            "overlay_identity": _DEVICE,
            "rotated": True,
        },
        "enrol",
    )
    printed = capsys.readouterr().out
    assert code == EXIT_OK
    assert "a" * 43 in printed
    assert _HUB_ID in printed
    assert "once and never again" in printed
    assert "revoked" in printed


def test_the_command_reports_a_refused_act_as_a_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A refusal exits non-zero and says why, rather than printing nothing and
    looking as though the act was performed."""
    code = _render({"ok": False, "error": "no such device act: 'purge'"}, "enrol")
    assert code == EXIT_DEPLOYMENT
    assert "purge" in capsys.readouterr().err


def test_the_command_says_a_revocation_is_prospective(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ADR-0124 §8: "no surface may present it as though it did" retract what was
    already sent.

    "A surface that rendered it as 'this device no longer has your data' would be
    asserting something the hub cannot know and did not do." So the rendering says
    what a revocation *is* — a statement about the door.
    """
    code = _render({"ok": True, "revoked": True}, "revoke")
    printed = capsys.readouterr().out
    assert code == EXIT_OK
    assert "already received, it keeps" in printed
    assert "no longer has your data" not in printed


def test_an_admin_timeout_is_short_because_both_ends_are_on_this_machine() -> None:
    """A figure named rather than left to the implementation (ADR-0083 §7's rule).

    It bounds a local act over a handful of SQLite rows; a long one would let a
    device command that met a wedged hub look like a hub that is thinking.
    """
    assert timedelta(seconds=1) <= ADMIN_TIMEOUT <= timedelta(seconds=30)


# --- the record grows without end, and the surface over it must not ----------


async def test_a_listing_stays_inside_one_frame_however_long_the_record_is(
    tmp_path: Path,
) -> None:
    """The record only ever grows, and the surface that reads it is what breaks first.

    ADR-0124 §6 keeps every revocation, so a device re-enrolled on a schedule leaves
    rows without end. An unbounded listing eventually builds a reply larger than the
    frame it has to travel in, and ``write_frame`` refuses it — so the act an owner
    uses to *check* the record would fail as a closed connection, which is both the
    least legible failure available and the one the record's own growth guarantees.

    Driven past the frame ceiling rather than near it: at ~139 bytes a row, one
    mebibyte is a few thousand, so ten thousand acts is comfortably over.
    """
    store = EnrolmentStore(tmp_path / ENROLMENTS_FILENAME)
    verifier = verifier_for("x" * 43)
    for index in range(10_000):
        store.enrol(f"n{index:012d}", verifier=verifier, now=_MOMENT)
    registry = DeviceRegistry(store, hub_identity=_HUB_ID)
    listener = AdminListener(registry, data_dir=tmp_path, now=_clock)
    await listener.start()
    try:
        listed = await _act(listener, {"act": "list"})
    finally:
        await listener.stop_accepting()
        await listener.aclose()
        store.close()

    assert listed["ok"]
    assert len(json.dumps(listed).encode()) < ADMIN_FRAME_BYTES
    assert len(listed["devices"]) == LISTING_LIMIT
    assert listed["omitted"] == 10_000 - LISTING_LIMIT


async def test_a_listing_says_what_it_did_not_show(tmp_path: Path) -> None:
    """A bound is only honest if the surface reports it (ADR-0083's ruling 4).

    "A listing that quietly stopped at a limit" would read as a complete record, and
    an owner checking which devices they enrolled would draw a conclusion from a
    partial answer. So ``omitted`` is on every reply — zero when nothing was — and
    the command prints it.
    """
    async with _admin(tmp_path) as (listener, _):
        await _act(listener, {"act": "enrol", "identity": _DEVICE})
        assert (await _act(listener, {"act": "list"}))["omitted"] == 0


def test_the_command_says_how_many_enrolments_it_did_not_show(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The operator-facing half of the clause above."""
    code = _render(
        {
            "ok": True,
            "hub_identity": _HUB_ID,
            "devices": [
                {
                    "overlay_identity": _DEVICE,
                    "enrolled_at": _MOMENT.isoformat(),
                    "revoked_at": None,
                    "live": True,
                }
            ],
            "omitted": 42,
        },
        "list",
    )
    assert code == EXIT_OK
    assert "42 older enrolment(s) not shown" in capsys.readouterr().out


async def test_a_hub_that_goes_away_mid_act_is_reported_rather_than_raised(
    tmp_path: Path,
) -> None:
    """The device command reports a transport failure; it does not traceback.

    ``read_frame`` reports a peer that closed as ``ConnectionClosedError``, which is
    this project's own hierarchy and is neither an ``OSError`` nor a ``ValueError``.
    A handler that named only those two would let it escape ``asyncio.run`` and
    print a stack trace — where ADR-0083's ruling 4 asks for a sentence and an exit
    code, and where the hub being mid-shutdown is the commonest way to meet it.
    """
    socket = tmp_path / ADMIN_SOCKET_FILENAME

    async def _hang_up(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        del reader
        writer.close()

    server = await asyncio.start_unix_server(_hang_up, path=str(socket))
    try:
        code = await _perform(socket, {"act": "list"})
    finally:
        server.close()
        await server.wait_closed()
    assert code == EXIT_RESTART


async def test_a_reply_that_does_not_decode_is_reported_rather_than_raised(
    tmp_path: Path,
) -> None:
    """The same handler's other limb, and the pair is what makes it a rule.

    A hub answering with bytes that are not JSON is the same class of failure as one
    that never answered: the act's outcome is unknown either way, and the command
    says so instead of failing inside the decode.
    """
    socket = tmp_path / ADMIN_SOCKET_FILENAME

    async def _gibberish(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await read_frame(
            reader,
            max_frame_bytes=ADMIN_FRAME_BYTES,
            timeout=ADMIN_TIMEOUT,
            idle_timeout=ADMIN_TIMEOUT,
        )
        await write_frame(writer, b"\xff\xfe not json", max_frame_bytes=ADMIN_FRAME_BYTES)
        writer.close()

    server = await asyncio.start_unix_server(_gibberish, path=str(socket))
    try:
        code = await _perform(socket, {"act": "list"})
    finally:
        server.close()
        await server.wait_closed()
    assert code == EXIT_RESTART


async def test_a_device_command_that_finds_no_hub_says_where_it_looked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Device acts are the running hub's, so "no hub" is the expected answer when it
    is stopped — and it names the socket and the command that starts one."""
    code = await _perform(tmp_path / ADMIN_SOCKET_FILENAME, {"act": "list"})
    assert code == EXIT_RESTART
    assert "ai-assistant-hub" in capsys.readouterr().err


async def test_a_client_that_hangs_up_mid_act_does_not_fault_the_hub(tmp_path: Path) -> None:
    """The mirror of the two cases above, on the hub's side.

    A device command interrupted between frames is the ordinary ending, not a fault:
    the hub logs it and goes on serving. Without the transport clause it would reach
    the catch-all and print a traceback for somebody pressing Ctrl-C.
    """
    async with _admin(tmp_path) as (listener, registry):
        reader, writer = await asyncio.open_unix_connection(str(listener.path))
        del reader
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        assert (await _act(listener, {"act": "enrol", "identity": _DEVICE}))["ok"]
        assert registry.enrolments()[1] == 1
