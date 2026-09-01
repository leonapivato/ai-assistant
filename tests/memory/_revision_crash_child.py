"""Child process for the revision issuer's crash-survival test (ADR-0219 §7).

Run as ``python _revision_crash_child.py <db_path>``. It opens a
:class:`SqliteMemoryStore`, stores two records, **deletes the one holding the
highest revision**, prints that revision, and then dies via ``os._exit`` without
closing the store.

The deletion is the whole design of the case. An implementation holding the
issuer in memory and flushing it on ``close`` passes every reopen arm — the rows
do read back at their stamps — and reissues after a kill. Reconstructing the
issuer from the rows currently present is what ADR-0219 §1 forbids by name, and
the deleted row is precisely the value no surviving row records: rebuild from
``MAX(revision)`` and the next write after the crash takes the stamp the deleted
row had, so the parent's conditional write against it *lands* where it must be
refused.

Not a pytest module (leading underscore, no ``test_`` prefix), so it is never
collected; it is only ever spawned as a subprocess.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime

from ai_assistant.core.types import MemorySource, Provenance, SemanticMemory
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
#: Exit code the parent asserts: died where this child meant to, after the delete
#: committed and with nothing closed. Any other code means the run took a path the
#: parent's assertions do not describe.
_DIED_UNCLOSED = 42


def _semantic(record_id: str, content: str) -> SemanticMemory:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN),
    )


async def _main() -> None:
    path = sys.argv[1]
    store = SqliteMemoryStore(
        traces_sink=FakeTraceSink(), path=path, embedder=HashingEmbedder(dimensions=8)
    )
    await store.add(_semantic("kept", "a record that survives the crash"))
    await store.add(_semantic("doomed", "the record holding the highest stamp"))
    doomed = await store.get("doomed")
    assert doomed is not None
    await store.delete("doomed")
    # Flushed, because the parent reads this line to know which stamp must never be
    # issued again. Printed *after* the delete committed, so it names a value no
    # surviving row records.
    print(doomed.revision, flush=True)
    os._exit(_DIED_UNCLOSED)  # no close, no flush of anything held only in memory


if __name__ == "__main__":
    asyncio.run(_main())
