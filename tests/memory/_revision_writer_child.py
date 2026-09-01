"""Child process for the cross-process conditional-write test (ADR-0219 §7).

Run as ``python _revision_writer_child.py <db_path> <record_id> <content>``. It
opens a :class:`SqliteMemoryStore` over the given file, stores one record at the
given id, and closes — an ordinary committed write from a **second process**,
which is the whole point: the parent read that record's ``revision`` before this
ran, and the conditional write it makes afterwards must be refused.

That is the half of #248's residual an in-process lock cannot close. "An
in-process lock says nothing about two processes sharing a store file", as
``MemoryIngestor.ingest``'s own docstring puts it, so the case has to be driven
across the boundary the claim is about.

Not a pytest module (leading underscore, no ``test_`` prefix), so it is never
collected; it is only ever spawned as a subprocess.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from ai_assistant.core.types import MemorySource, Provenance, SemanticMemory
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.models import HashingEmbedder
from ai_assistant.testing import FakeTraceSink

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


async def _main() -> None:
    path, record_id, content = sys.argv[1], sys.argv[2], sys.argv[3]
    store = SqliteMemoryStore(
        traces_sink=FakeTraceSink(), path=path, embedder=HashingEmbedder(dimensions=8)
    )
    try:
        await store.add(
            SemanticMemory(
                id=record_id,
                content=content,
                fact=content,
                provenance=Provenance(
                    source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN
                ),
            )
        )
    finally:
        store.close()


if __name__ == "__main__":
    asyncio.run(_main())
