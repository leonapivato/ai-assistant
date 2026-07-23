"""Child process for the ``write_atomic`` crash-recovery integration test.

Run as ``python _atomic_crash_child.py <db_path>``. It opens a
:class:`SqliteMemoryStore`, commits an open target ``T``, then starts a
two-element ``write_atomic`` batch — an ``UPSERT`` that closes ``T``'s window and
an ``INSERT_IF_ABSENT`` of a correction ``P`` — but kills the process *mid
transaction*, after the first element's write and before ``COMMIT``, via
``os._exit``. The parent reopens the database and asserts neither mutation
survived (ADR-0046 §4's durability obligation).

Not a pytest module (leading underscore, no ``test_`` prefix), so it is never
collected; it is only ever spawned as a subprocess.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from typing import cast

import sqlite_vec

from ai_assistant.core.types import (
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Provenance,
    SemanticMemory,
    Validity,
)
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.models import HashingEmbedder

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_PAST = datetime(2000, 1, 1, tzinfo=UTC)
_DIED_MID_BATCH = 42  # the parent asserts this exact code: died at the injection point


def _semantic(record_id: str, content: str, validity: Validity | None = None) -> SemanticMemory:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN),
        validity=validity or Validity(),
    )


async def _main() -> None:
    path = sys.argv[1]
    store = SqliteMemoryStore(path=path, embedder=HashingEmbedder(dimensions=8))
    await store.add(_semantic("T", "coffee target"))  # committed, window open

    # After T is committed, make the *second* element's vector write kill the
    # process: the first element (T's window-close) is then already written into
    # the still-open transaction, so a correct backend must roll it back on reopen.
    real = sqlite_vec.serialize_float32
    calls = {"n": 0}

    def crash_on_second(vector: object) -> bytes:
        calls["n"] += 1
        if calls["n"] >= 2:
            os._exit(_DIED_MID_BATCH)
        return cast("bytes", real(vector))

    sqlite_vec.serialize_float32 = crash_on_second

    await store.write_atomic(
        [
            MemoryWrite(
                record=_semantic("T", "coffee target", Validity(valid_until=_PAST)),
                mode=MemoryWriteMode.UPSERT,
            ),
            MemoryWrite(record=_semantic("P", "coffee correction"), mode=MemoryWriteMode.UPSERT),
        ]
    )
    os._exit(99)  # unreachable: we expected to die inside the batch above


if __name__ == "__main__":
    asyncio.run(_main())
