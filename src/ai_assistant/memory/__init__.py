"""Memory: persistent user model and long-term memory.

Stores and retrieves what the assistant knows about the user (goals,
preferences, routines, relationships) and past interactions, across
conversations and projects. The persistent backend is local-first SQLite with
``sqlite-vec`` for embedding search (:class:`SqliteMemoryStore`);
:class:`InMemoryMemoryStore` is a dependency-free lexical store for tests.

Also home to three stores whose contracts are their own Protocols rather than
extensions of ``MemoryStore`` — the conversation index (ADR-0074), the
deferred-question queue (:class:`SqliteDeferralStore`, ADR-0078) and the held
notifications (:class:`SqliteNotificationStore`, ADR-0130) — which share this
package because the architecture map names no subsystem for any of them and
inventing one is an ADR's decision, not an implementation lane's. Every
top-level package this tree has gained was minted by a clause of its own ADR
naming the ``lint-imports`` edit; ADR-0130 §9 mints none.
:class:`DefaultNotificationPolicy` sits beside the store it rules for, exactly as
:class:`DefaultMemoryPolicy` does.

Implements: ``MemoryStore``, ``MemoryPolicy``, ``MemoryWriter``,
``ConversationStore``, ``DeferralStore``, ``NotificationStore`` and
``NotificationPolicy``.
"""

from __future__ import annotations

from ai_assistant.memory.deferral_store import SqliteDeferralStore
from ai_assistant.memory.ingest import MemoryIngestor
from ai_assistant.memory.notification_policy import DefaultNotificationPolicy
from ai_assistant.memory.notification_store import SqliteNotificationStore
from ai_assistant.memory.policy import DefaultMemoryPolicy
from ai_assistant.memory.sqlite_store import SqliteMemoryStore
from ai_assistant.memory.store import InMemoryMemoryStore

__all__ = [
    "DefaultMemoryPolicy",
    "DefaultNotificationPolicy",
    "InMemoryMemoryStore",
    "MemoryIngestor",
    "SqliteDeferralStore",
    "SqliteMemoryStore",
    "SqliteNotificationStore",
]
