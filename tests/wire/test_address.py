"""The socket's path, and the budget no socket can be bound outside of (#554).

ADR-0084 §1's fourth step-2 condition, which had no socket to check until this
change. The three that landed with the hub protect the seven databases; this one
"bears on nothing until something binds", and something binds now.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.wire.address import (
    SOCKET_FILENAME,
    SOCKET_MODE,
    LoopbackDestination,
    RemoteDestination,
    check_remote_address,
    check_socket_path,
    destination,
    socket_path,
    sun_path_limit,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_the_socket_sits_inside_the_data_directory(tmp_path: Path) -> None:
    """ADR-0084 §9: one setting locates both the data and the door.

    "A client that can find the data directory can find the hub", which is what
    makes a hub and a client unable to disagree about where to look — they read the
    same field and derive the same path.
    """
    assert socket_path(tmp_path) == tmp_path / SOCKET_FILENAME


def test_the_socket_is_owner_only() -> None:
    """§1: ``0600``, which is ADR-0004 §4's posture applied to a new object.

    On Linux the kernel enforces it at ``connect()``, so this is "a ratified access
    control reused" rather than a new one — and it is the whole reason a Unix socket
    was chosen over a TCP loopback port, which "is reachable by **every** local
    process and every local user".
    """
    assert SOCKET_MODE == 0o600


def test_the_limit_is_the_running_platform_s_own() -> None:
    """§1: "The check uses **the running platform's own limit** rather than a
    constant."

    "Hardcoding 108 would let a 104-byte path pass validation on macOS and then fail
    at ``bind()``, which is precisely the late, opaque failure this rule exists to
    prevent, reintroduced by the check itself."
    """
    expected = {"linux": 108, "darwin": 104}.get(sys.platform, 104)
    assert sun_path_limit() == expected


def test_an_unknown_platform_gets_the_smaller_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed, because the two directions of a wrong guess are not alike.

    Too small refuses a path that would have worked and says exactly why; too large
    passes validation and fails inside ``bind()`` with an errno — the failure this
    check exists to replace.
    """
    monkeypatch.setattr(sys, "platform", "plan9")
    assert sun_path_limit() == 104


def test_a_path_that_fits_is_accepted(tmp_path: Path) -> None:
    """The discriminating half: the check refuses what it must and nothing else.

    Without it, a check that refused everything would pass every test below and
    make the hub unstartable everywhere.
    """
    check_socket_path(tmp_path)


def test_a_path_too_long_for_the_socket_is_a_stay_down_fault(tmp_path: Path) -> None:
    """§1: "a path that cannot hold the socket **exits 78**, naming the limit, the
    encoded length and the directory".

    A ``ConfigurationError`` because ADR-0083 §5's test applies without strain:
    "restarting unchanged never succeeds, and a human must move the data directory".
    Left unchecked the failure lands at step 6 instead — "after the lock is held,
    the seven stores are open and the start-up sweeps have run: the latest and least
    legible moment available".
    """
    deep = tmp_path
    while len(str(deep).encode()) < sun_path_limit():
        deep = deep / "aaaaaaaaaa"
    with pytest.raises(ConfigurationError) as caught:
        check_socket_path(deep)
    message = str(caught.value)
    assert str(sun_path_limit()) in message
    assert str(deep) in message
    assert "ASSISTANT_DATA_DIR" in message


def test_the_budget_is_counted_in_bytes_and_not_in_characters(tmp_path: Path) -> None:
    """§1: "because a directory named in a non-ASCII script spends more of the
    budget than it looks like it does".

    The two directories below have the *same* character count and different byte
    counts, and the check separates them — which a character-count implementation
    could not do.
    """
    budget = sun_path_limit() - len(str(tmp_path).encode()) - len(SOCKET_FILENAME) - 3
    if budget < 8:  # pragma: no cover - only on an unusually deep tmp_path
        pytest.skip("the temporary directory leaves no room to demonstrate the difference")
    characters = budget // 2 + 2
    ascii_dir = tmp_path / ("a" * characters)
    wide_dir = tmp_path / ("é" * characters)
    assert len(ascii_dir.name) == len(wide_dir.name)
    check_socket_path(ascii_dir)
    with pytest.raises(ConfigurationError):
        check_socket_path(wide_dir)


def test_the_terminator_counts(tmp_path: Path) -> None:
    """§1: the figure is "terminator included in both".

    An off-by-one here is a path that validates and then fails at ``bind()``, which
    is the one outcome the check exists to make impossible. Driven at exactly the
    boundary: a path whose encoded length equals the budget is one byte too long,
    because the NUL has to go somewhere.
    """
    limit = sun_path_limit()
    room = limit - len(str(tmp_path).encode()) - len("/") - len(SOCKET_FILENAME) - len("/")
    if room < 2:  # pragma: no cover - only on an unusually deep tmp_path
        pytest.skip("the temporary directory leaves no room to reach the boundary")
    exact = tmp_path / ("a" * room)
    assert len(str(socket_path(exact)).encode()) == limit
    with pytest.raises(ConfigurationError):
        check_socket_path(exact)
    check_socket_path(tmp_path / ("a" * (room - 1)))


# --- naming a hub on another machine (ADR-0124 §1) --------------------------


def test_no_remote_address_means_the_hub_on_this_machine(tmp_path: Path) -> None:
    """The address is the switch, in the shape ADR-0124 §2 gave the hub's listener.

    Unset means the loopback socket, and there is no separate boolean — "two
    settings that can disagree about which transport is in use is one more state
    than a deployment has".
    """
    where = destination(data_dir=tmp_path, remote_address=None, remote_port=50084)

    assert where == LoopbackDestination(socket_path(tmp_path))


def test_a_remote_address_names_a_hub_on_another_machine(tmp_path: Path) -> None:
    """And carries the port with it, because a destination is both."""
    where = destination(data_dir=tmp_path, remote_address="100.64.1.7", remote_port=50084)

    assert where == RemoteDestination(host="100.64.1.7", port=50084)


def test_the_destination_never_falls_back_between_transports(tmp_path: Path) -> None:
    """ADR-0084 §9's rule applied to the *choice* rather than to the outcome.

    A remote hub that is down is reported (:mod:`ai_assistant.wire.remote`), never
    quietly replaced by the one on this machine — which would serve the wrong store
    from the wrong device while looking like success.
    """
    where = destination(data_dir=tmp_path, remote_address="100.64.1.7", remote_port=50084)

    assert not isinstance(where, LoopbackDestination)


def test_a_name_is_refused_rather_than_resolved() -> None:
    """ADR-0124 §1: the destination never comes "from a discovery mechanism".

    ``Settings`` already applies this to the hub's own bind and says why — "a name
    would make the bound address a fact about a resolver" — and §1's rule "is the
    same principle on the other end of the hop".
    """
    with pytest.raises(ConfigurationError) as raised:
        check_remote_address("hub.example.ts.net")

    assert "discovery mechanism" in str(raised.value)
    assert "ASSISTANT_REMOTE_HUB_ADDRESS" in str(raised.value)


@pytest.mark.parametrize(
    ("address", "reason"),
    [
        ("0.0.0.0", "wildcard"),  # noqa: S104 - the value under test, never bound
        ("::", "wildcard, v6"),
        ("127.0.0.1", "loopback"),
        ("::1", "loopback, v6"),
        ("224.0.0.1", "multicast"),
        ("169.254.4.4", "link-local"),
        ("8.8.8.8", "globally routable"),
        ("2001:4860:4860::8888", "globally routable, v6"),
    ],
)
def test_an_address_no_conforming_listener_holds_is_refused(address: str, reason: str) -> None:
    """The same five refusals the hub applies to its own bind, from the other end.

    ADR-0124 §2 forbids the listener to bind any of these, so a client pointed at
    one is pointed at something that is not a conforming hub's remote listener.
    Saying so costs a message; discovering it costs a connection attempt to whatever
    *is* there.
    """
    del reason

    with pytest.raises(ConfigurationError):
        check_remote_address(address)


@pytest.mark.parametrize("address", ["100.64.1.7", "fd7a:115c:a1e0::1", "10.2.0.9"])
def test_an_overlay_address_is_accepted(address: str) -> None:
    """The addresses an overlay actually hands out, in both families."""
    assert check_remote_address(address) == address


def test_surrounding_whitespace_is_stripped_and_nothing_else_is() -> None:
    """A value pasted out of a terminal, accepted; a value rewritten, never.

    ``Settings`` strips the hub's own address for the same reason, and neither end
    normalises further: an address this client silently rewrote would be a
    destination the owner did not configure.
    """
    assert check_remote_address("  100.64.1.7  ") == "100.64.1.7"
