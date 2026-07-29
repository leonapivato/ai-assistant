"""Memory: persistent user model and long-term memory.

Stores and retrieves what the assistant knows about the user (goals,
preferences, routines, relationships) and past interactions, across
conversations and projects. The persistent backend is local-first SQLite with
``sqlite-vec`` for embedding search (:class:`SqliteMemoryStore`);
:class:`InMemoryMemoryStore` is a dependency-free lexical store for tests.

Also home to two stores whose contracts are their own Protocols rather than
extensions of ``MemoryStore`` — the conversation index (ADR-0074) and the
deferred-question queue (:class:`SqliteDeferralStore`, ADR-0078) — which share
this package because the architecture map names no subsystem for either and
inventing one is an ADR's decision, not an implementation lane's.

Implements: ``MemoryStore``, ``MemoryPolicy``, ``MemoryWriter``,
``ConversationStore`` and ``DeferralStore``.
"""

from __future__ import annotations

from ai_assistant.memory.deferral_store import SqliteDeferralStore
from ai_assistant.memory.ingest import MemoryIngestor
from ai_assistant.memory.policy import DefaultMemoryPolicy
from ai_assistant.memory.sqlite_store import SqliteMemoryStore
from ai_assistant.memory.store import InMemoryMemoryStore

__all__ = [
    "DefaultMemoryPolicy",
    "InMemoryMemoryStore",
    "MemoryIngestor",
    "SqliteDeferralStore",
    "SqliteMemoryStore",
]
