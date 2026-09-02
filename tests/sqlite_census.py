"""Record every SQLite connection a build opens, so a shutdown can be swept.

Two composition roots in this tree open a set of connection-owning stores and hand
the closes to something that runs them at teardown: ``app/composition.py`` to
``Engine(closers=…)``, and ``benchmarks/memory/wiring.py`` to ``Harness.close``. Both
have shipped a store registered in one place and not the other — the transcript
archive (#1902) and the two stores #1903 names — and in each case the omission was
invisible to every check this project runs, because a closer list looks complete
until you compare it against something.

**This is the something.** :func:`connection_census` records the connections a block
of code opens, and :func:`is_open` asks a recorded connection whether it still works.
A test that opens a root inside the census and sweeps it after teardown is then
asserting over the roster the build *actually* opened rather than over a list a test
would have to be kept in step with — so the next store added without a closer fails
on the day it is added, and names its own database file when it does.

Lives beside ``collection_guard`` as a top-level module under ``tests/`` because two
test packages use it. Both roots' cases would otherwise carry the same fifteen lines,
and a guard that is copied is a guard that can be fixed in one copy.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest import mock

if TYPE_CHECKING:
    from collections.abc import Iterator

#: What SQLite says when a connection has been closed. Matched on rather than taking
#: every ``ProgrammingError`` for a closure, because the same class also carries
#: "SQLite objects created in a thread can only be used in that same thread" — a live
#: connection reached from the wrong thread, which read as a closure would make a
#: sweep pass for the wrong reason.
CLOSED_MESSAGE = "closed database"


@contextmanager
def connection_census() -> Iterator[list[tuple[str, sqlite3.Connection]]]:
    """Record ``(database, connection)`` for every :func:`sqlite3.connect` inside.

    Patched on the ``sqlite3`` module itself, which is where every store in this tree
    resolves the name at call time, so nothing has to be enumerated for the recording
    to cover it — including a store that does not exist yet.

    Yields:
        The list being recorded into, in the order the connections were opened. It is
        live: entries appear as the block runs, and the list is readable afterwards.
    """
    recorded: list[tuple[str, sqlite3.Connection]] = []
    real_connect = sqlite3.connect

    def recording(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection: sqlite3.Connection = real_connect(database, *args, **kwargs)
        recorded.append((str(database), connection))
        return connection

    with mock.patch.object(sqlite3, "connect", recording):
        yield recorded


def is_open(connection: sqlite3.Connection) -> bool:
    """Ask the connection itself, rather than any flag a store keeps beside it.

    Args:
        connection: A connection from a :func:`connection_census` recording.

    Returns:
        Whether a statement can still be executed on it.

    Raises:
        sqlite3.ProgrammingError: If the driver refuses for any reason other than the
            connection being closed — a misuse this must not silently read as one.
    """
    try:
        connection.execute("SELECT 1")
    except sqlite3.ProgrammingError as exc:
        if CLOSED_MESSAGE in str(exc).lower():
            return False
        raise
    return True
