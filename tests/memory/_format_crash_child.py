"""Crash after dirty pages spill, leaving a genuinely hot rollback journal."""

from __future__ import annotations

import os
import sqlite3
import sys


def main() -> None:
    """The parent seeds committed rows and checks this exact crash exit code."""
    conn = sqlite3.connect(sys.argv[1], isolation_level=None)
    conn.execute("PRAGMA cache_size=4")
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("UPDATE crash_probe SET value=zeroblob(8192)")
    os._exit(42)


if __name__ == "__main__":
    main()
