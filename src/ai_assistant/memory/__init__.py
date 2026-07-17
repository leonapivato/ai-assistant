"""Memory: persistent user model and long-term memory.

Stores and retrieves what the assistant knows about the user (goals,
preferences, routines, relationships) and past interactions, across
conversations and projects. The persistent backend is local-first SQLite with
``sqlite-vec`` for embedding search (:class:`SqliteMemoryStore`);
:class:`InMemoryMemoryStore` is a dependency-free lexical store for tests.

Implements: ``MemoryStore`` and ``MemoryPolicy``.
"""

from __future__ import annotations

from ai_assistant.memory.ingest import MemoryIngestor
from ai_assistant.memory.policy import DefaultMemoryPolicy
from ai_assistant.memory.sqlite_store import SqliteMemoryStore
from ai_assistant.memory.store import InMemoryMemoryStore

__all__ = [
    "DefaultMemoryPolicy",
    "InMemoryMemoryStore",
    "MemoryIngestor",
    "SqliteMemoryStore",
]
