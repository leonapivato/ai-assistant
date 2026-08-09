"""Child process for ``get_many``'s cross-process snapshot test (ADR-0086 §8).

Run as ``python _get_many_snapshot_child.py <db_path>``. It opens a
:class:`SqliteMemoryStore` over the database the parent seeded, announces itself
on stdout, waits for a go-signal on stdin, and then overwrites record ``b``.

The handshake is what makes the collision deterministic. The parent releases the
signal from *between two chunks* of one ``get_many`` — the boundary a chunked
read introduces and the only place the tear can appear — so the write is
attempted inside that window on every run rather than whenever the scheduler
arranges it. Opening the store *before* the window matters too: opening it inside
would contend on ``_setup``'s ``BEGIN IMMEDIATE`` instead of on the write under
test, and the case would prove something else.

With ``get_many`` reading inside one transaction the parent holds a read lock
across both chunks, so this write cannot commit until the parent's call is done
and the parent's second chunk sees the value its first chunk was consistent with.
Without one, this write lands between the chunks and the parent returns an old
``a`` beside a new ``b`` — two values that never coexisted.

Not a pytest module (leading underscore, no ``test_`` prefix), so it is never
collected; it is only ever spawned as a subprocess.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from ai_assistant.core.types import MemorySource, Provenance, SemanticMemory, Validity
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
#: stdout marker meaning "the store is open and I am waiting for the go-signal".
_READY = "ready"
#: The content this child writes over record ``b``. The parent asserts it did
#: **not** see it, so the string has to be one nothing else produces.
REVISED = "b as another process revised it"


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
    try:
        print(_READY, flush=True)  # flushed: the parent is blocked on this line
        sys.stdin.readline()  # the go-signal, sent from between the parent's chunks
        await store.add(_semantic("b", REVISED))
    finally:
        store.close()


if __name__ == "__main__":
    asyncio.run(_main())
