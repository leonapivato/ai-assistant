"""Decoding ``struct ucred``, for the uids that do not fit in a signed int.

ADR-0084 §1 and ADR-0131 §7 both phrase their rule as an *admission*: the peer is
refused "unless the peer's effective uid is ``0`` or its own". Reading ``uid_t`` as
signed cannot open an admission hole — a misdecoded uid comes out negative and
matches neither — but it closes the admission half on any host whose uids reach
2\\ :sup:`31`, where the process would refuse its own hub or its own overlay agent.

The credentials are built here rather than obtained from a real socket because a
test cannot be run as a uid above the signed limit; the bytes are assembled field by
field from integers, so nothing about the module's own format string is assumed by
the thing that checks it.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, cast

import pytest

from ai_assistant.wire.errors import ProtocolError
from ai_assistant.wire.peer import check_peer_is_self, peer_uid

if TYPE_CHECKING:
    import socket

# Above 2**31 - 1, so a signed decode of these returns a negative number. Real ones
# arrive from directory-service id mapping and some container uid remappings.
BIG_UID = 3_000_000_000
BIG_GID = 3_000_000_001


def _ucred_bytes(pid: int, uid: int, gid: int) -> bytes:
    """The twelve bytes the kernel writes for ``struct ucred``.

    ``{ pid_t pid; uid_t uid; gid_t gid; }`` in native order: one signed 32-bit
    field then two unsigned ones. Assembled from :meth:`int.to_bytes` rather than
    :mod:`struct` so that the packing side of this test shares no format string with
    the unpacking side under test.
    """
    return b"".join(
        (
            pid.to_bytes(4, sys.byteorder, signed=True),
            uid.to_bytes(4, sys.byteorder),
            gid.to_bytes(4, sys.byteorder),
        )
    )


class _StubCredentialSocket:
    """A connected socket whose ``SO_PEERCRED`` answer is chosen, not observed."""

    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.requested: int | None = None

    def getsockopt(self, level: int, optname: int, buflen: int = 0) -> bytes:
        self.requested = buflen
        return self.raw


def _peer(uid: int, gid: int = BIG_GID, pid: int = 1234) -> _StubCredentialSocket:
    return _StubCredentialSocket(_ucred_bytes(pid, uid, gid))


def test_a_uid_above_the_signed_limit_is_read_back_as_the_kernel_wrote_it() -> None:
    """The defect itself: ``uid_t`` is unsigned, so ``3i`` misreads it (#962).

    Under the old format this returns ``-1294967296``, which is not any uid on any
    host. ``struct.calcsize`` is 12 for both formats, so the read stays well-formed
    and only the value changes — which is why the buffer width is asserted too: the
    fix must correct the signedness without disturbing the layout.
    """
    sock = _peer(BIG_UID)

    assert peer_uid(cast("socket.socket", sock)) == BIG_UID
    assert sock.requested == 12


def test_the_hub_is_admitted_when_our_own_uid_is_above_the_signed_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0084 §1's admission half, on a host where it used to fail.

    ``os.geteuid()`` is always correct and non-negative, so a signed decode leaves
    the comparison unsatisfiable: the user's own hub, running as the user, is
    refused as though another user had replaced its socket. The euid is injected
    because a test cannot be run under such a uid; the rule under test is the
    comparison, not the syscall.
    """
    monkeypatch.setattr(os, "geteuid", lambda: BIG_UID)

    check_peer_is_self(cast("socket.socket", _peer(BIG_UID)))


def test_a_different_user_above_the_signed_limit_is_still_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal is what §1 exists for, and it must survive the widening.

    Two uids that a signed decode would both mangle — into different negatives, so
    the old code refused this by luck as much as by rule. It is refused here because
    the two genuinely differ, and the refusal names the peer as the kernel reported
    it rather than as a negative number no operator could match to an account.
    """
    monkeypatch.setattr(os, "geteuid", lambda: BIG_UID + 1)

    with pytest.raises(ProtocolError) as raised:
        check_peer_is_self(cast("socket.socket", _peer(BIG_UID)))

    assert f"uid {BIG_UID}" in str(raised.value)


def test_an_ordinary_uid_is_unaffected() -> None:
    """The common case, pinned against a fix that shifts the fields around.

    ``iII`` and ``3i`` agree on every uid below 2\\ :sup:`31`, so this passes before
    and after; what it would catch is a format that changed the width or order of
    the three fields rather than only their signedness.
    """
    assert peer_uid(cast("socket.socket", _peer(1000, gid=1000))) == 1000
