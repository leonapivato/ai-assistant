"""Fresh-state memory format boundary for ADR-0275."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.errors import IncompatibleStateError

if TYPE_CHECKING:
    import sqlite3


def check_format(conn: sqlite3.Connection, *, allow_empty: bool = False) -> bool:
    """Refuse pre-M36 state before mutation; return whether a marker exists."""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not tables and allow_empty:
        return False
    if "episode_record_format" in tables:
        rows = conn.execute("SELECT version FROM episode_record_format").fetchall()
        if rows == [(1,)]:
            return True
    raise IncompatibleStateError(
        "memory store requires a fresh M36 data directory",
        expected="episode record format 1",
        found="missing or unsupported episode record format",
        operator_action="Stop the old hub and configure a new empty development data directory.",
    )
