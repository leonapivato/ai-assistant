"""The resident process — the hub itself (ADR-0083 §8).

A top-level package rather than a corner of an existing one, because cadence and
lifecycle are properties of a *deployment* and every existing package owns
something else: ``orchestration`` owns the request pipeline, ``interfaces`` holds
thin adapters, and ``app`` is the composition root.

**The dependency rule is one-directional and mechanically enforced.** This package
may import ``app`` (for ``build_engine``), the ``Engine`` type it returns, and
``core``; **nothing may import ``service``**. The ``lint-imports`` contract in
``pyproject.toml`` is that rule, and it is what forces the hub to be its own
console script rather than an ``assistant hub`` subcommand — a subcommand would
put the import edge in ``interfaces`` (ADR-0084 §6).

The entry point is :func:`main`.
"""

from __future__ import annotations

from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART
from ai_assistant.service.hub import main, serve
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock

__all__ = [
    "EXIT_DEPLOYMENT",
    "EXIT_OK",
    "EXIT_RESTART",
    "LOCK_FILENAME",
    "InstanceLock",
    "main",
    "serve",
]
