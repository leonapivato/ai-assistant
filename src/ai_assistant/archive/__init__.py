"""The transcript archive: what was said, kept as text, read only by the user.

A leaf package (ADR-0225 §10). It depends on ``ai_assistant.core`` and on nothing
else in ``ai_assistant``, and **no other package may import it** —
``ai_assistant.app`` alone excepted, as the composition root — which is the shape
ADR-0119 §7 already uses for ``ai_assistant.evaluation`` and the first of the three
independent properties ADR-0225 §4 enforces its never-list with. An
``import-linter`` contract in ``pyproject.toml`` fails the gate on a violation.

**Its own package rather than a corner of** ``memory/`` (§10). An ``import-linter``
contract can forbid importing a package; it cannot forbid importing part of one, so
putting the archive inside ``memory/`` would leave every pipeline subsystem that
legitimately imports ``memory`` one attribute away from the store the never-list is
about, and gate 1's mechanical enforcement would be unavailable.

**Named for what it holds rather than for this producer**, deliberately: a later
ADR deciding source-material custody may place its store beside this one, inside
this package, without a rename (§11).
"""

from __future__ import annotations

from ai_assistant.archive.sqlite_store import SqliteTranscriptArchive

__all__ = ["SqliteTranscriptArchive"]
