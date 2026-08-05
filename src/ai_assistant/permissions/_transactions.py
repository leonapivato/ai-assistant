"""The one shape a transaction takes in this package's SQLite stores.

Two stores here own a ``sqlite3`` connection, and both need the same four
things at every transaction boundary: ``BEGIN IMMEDIATE``, so a read the write
depends on cannot be interleaved by another process (#526); a ``COMMIT`` that no
arm can skip, an early ``return`` included; a ``ROLLBACK`` on the way out of
*any* exception, ``BaseException`` included, because ADR-0060's resource clause
is unconditional and a transaction left open on a shared connection is a
resource held with nothing running that will release it — the next ``BEGIN``
fails with "cannot start a transaction within a transaction" and the store is
poisoned for every later caller; and the backend's ``sqlite3.Error`` translated
into this seam's own error rather than leaked past it.

The seam's error class is the only thing that differs between the two, so it is
the only parameter. Each store keeps a thin ``_transaction`` method that binds
it, and keeps on that method the docstring saying what the exclusion buys *that*
store — the argument is store-specific even where the mechanism is not.

**Why this is duplicated in ``memory`` and ``planning`` rather than shared with
them.** Both own SQLite stores with the same need, and golden rule 1
forbids one subsystem importing another's module — ``lint-imports`` fails the
gate on it, so this is not a convention that could be bent. A single home would
have to be ``core``, which is the contract surface rather than a place for
concrete helpers; putting it there is an architecture decision owed its own ADR
(#563, and #506 for the same question about ``_restrict_permissions``). Three
copies of one function is what that boundary costs. It is the floor, not an
oversight, and it is two fewer than the five hand-rolled spellings it replaces.
"""

from __future__ import annotations

import contextlib
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from ai_assistant.core.errors import AssistantError


@contextlib.contextmanager
def transaction(
    conn: sqlite3.Connection,
    what: str,
    *,
    error: Callable[[str], AssistantError],
    immediate: bool = True,
) -> Iterator[sqlite3.Connection]:
    """Run the block inside one transaction, translating backend failures.

    ``IMMEDIATE`` takes the write lock up front, so a read-then-write mutation
    cannot interleave with another writer's — which is how a store's exclusion
    holds **across processes** and not merely across coroutines on one loop.
    ``immediate=False`` is the read form: a deferred transaction, so several
    ``SELECT``s in one block see one consistent snapshot rather than two states
    either side of a racing write.

    Anything other than a backend failure propagates unchanged, after the
    transaction is rolled back — which is how a store refuses a record it will
    not accept without leaving anything behind.

    Args:
        conn: The store's connection, held open for the length of the block.
        what: What the caller is doing, read as the tail of ``failed to {what}``.
        error: The seam's own error, built from that message on a backend fault.
        immediate: Whether to take the write lock at ``BEGIN`` (the write form).

    Yields:
        The same connection, with the transaction open on it.

    Raises:
        AssistantError: Whatever ``error`` builds, if the backend fails at any
            point — opening the transaction, running the block, or committing.
    """
    begin = "BEGIN IMMEDIATE" if immediate else "BEGIN"
    try:
        conn.execute(begin)
    except sqlite3.Error as exc:
        msg = f"failed to {what}: {exc}"
        raise error(msg) from exc
    try:
        yield conn
    except BaseException as exc:
        with contextlib.suppress(sqlite3.Error):
            conn.execute("ROLLBACK")
        if isinstance(exc, sqlite3.Error):
            msg = f"failed to {what}: {exc}"
            raise error(msg) from exc
        raise
    try:
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        with contextlib.suppress(sqlite3.Error):
            conn.execute("ROLLBACK")
        msg = f"failed to {what}: {exc}"
        raise error(msg) from exc
