"""Child process for the cross-process ``BEGIN IMMEDIATE`` integration test.

Run as ``python _begin_immediate_child.py <db_path>``. It opens a
:class:`SqliteMemoryStore` over a database whose record ``T`` already exists and
re-adds ``T``, which drives :meth:`SqliteMemoryStore._persist_record` down its
overwrite branch: ``SELECT rowid`` → ``UPDATE`` → ``DELETE`` the old vector →
``INSERT`` the new one.

It pauses **between the rowid read and the first write**, announcing itself on
stdout first, so the parent can attempt the interleaving on every run rather than
whenever the scheduler happens to arrange it. That window is precisely what
``BEGIN IMMEDIATE`` closes: with it, the write lock is already held when the
``SELECT`` runs and the parent's deletion has to wait; without it, the parent's
deletion lands in the middle and the ``INSERT INTO vec_records`` below writes a
vector row against a ``rowid`` that no longer names a record (#526).

The pause is hung off ``sqlite3``'s trace callback rather than a seam in the
store, so the production module carries nothing that exists only for this test.
The callback fires as each statement starts, so keying it on the ``UPDATE``
places the hold after the ``SELECT`` has already returned.

Not a pytest module (leading underscore, no ``test_`` prefix), so it is never
collected; it is only ever spawned as a subprocess.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime

from ai_assistant.core.types import MemorySource, Provenance, SemanticMemory, Validity
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
#: How long the child holds the window open once it has announced itself. A
#: *bound* on how long the parent is given to arrive and collide, not a
#: synchronisation primitive — the ordering comes from the announcement, not from
#: this. Comfortably under ``sqlite3.connect``'s 5.0 s default busy timeout, so
#: the parent's blocked ``BEGIN IMMEDIATE`` waits it out rather than giving up.
_HOLD_SECONDS = 1.0
#: stdout marker meaning "I am inside the window". The parent acts on this line.
_INSIDE = "inside"
#: Exit code meaning the hold never fired — the write took a path this child does
#: not recognise, so the parent's deletion raced nothing and the case proved
#: nothing. The parent asserts against it rather than reading a pass into it.
_WINDOW_NEVER_REACHED = 43


def _semantic(record_id: str, content: str) -> SemanticMemory:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN),
        validity=Validity(),
    )


async def _main() -> None:
    path = sys.argv[1]
    store = SqliteMemoryStore(
        traces_sink=FakeTraceSink(), path=path, embedder=HashingEmbedder(dimensions=8)
    )
    reached = False

    def hold(statement: str) -> None:
        nonlocal reached
        if reached or not statement.lstrip().upper().startswith("UPDATE RECORDS"):
            return
        reached = True
        # Flushed, because the parent is blocked on this exact line.
        print(_INSIDE, flush=True)
        time.sleep(_HOLD_SECONDS)

    connection = store._conn  # the trace hook has to be on the store's own connection
    connection.set_trace_callback(hold)
    try:
        await store.add(_semantic("T", "coffee target, revised"))
    finally:
        connection.set_trace_callback(None)
        store.close()
    sys.exit(0 if reached else _WINDOW_NEVER_REACHED)


if __name__ == "__main__":
    asyncio.run(_main())
