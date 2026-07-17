"""Memory: persistent user model and long-term memory.

Stores and retrieves what the assistant knows about the user (goals,
preferences, routines, relationships) and past interactions, across
conversations and projects. Default backend is local-first SQLite with
``sqlite-vec`` for embedding search (added when this package is implemented).

Implements: ``MemoryStore``.
"""

from __future__ import annotations

from ai_assistant.memory.policy import DefaultMemoryPolicy
from ai_assistant.memory.store import InMemoryMemoryStore

__all__ = ["DefaultMemoryPolicy", "InMemoryMemoryStore"]
