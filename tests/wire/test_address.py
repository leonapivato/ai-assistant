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
    check_socket_path,
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
