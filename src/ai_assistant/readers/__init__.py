"""Concrete readers: the read-only seam's implementations (ADR-0093, ADR-0095).

A :class:`~ai_assistant.core.protocols.Reader` opens a source the hub can read and
returns one bounded :class:`~ai_assistant.core.types.SourceReading` of what that
source currently says. The **contract** lives in `core`; the implementations live
here, and this package is a leaf:

    It may import ``core`` and nothing else in ``ai_assistant``; no subsystem may
    import it. (ADR-0093 §2, restated by ADR-0095 §2.)

Both halves are enforced by ``lint-imports`` rather than asserted — the two
contracts in ``pyproject.toml`` carry the argument. **The split is the point**,
and ADR-0095 §3 refuses to collapse it: the contract sits in `core` where every
subsystem may name it, because two of them hold the type — `orchestration` by
injection, and later `context/` through its facet adapter — while the
implementations sit in a package nothing imports. Making ``Reader`` an internal
seam here would require exactly the ``orchestration -> ai_assistant.readers`` edge
the second contract forbids in as many words.

**Why a top-level package rather than a subsystem's**, re-tested rather than
inherited when the dedicated-always-on-box premise arrived (ADR-0095 §2):
`context/` is advisory and non-durable, so a reader living there would need a
``MemoryWriter`` to reach memory; `memory/` owns the store and the gate, and a
producer beside the policy ruling on it is what ADR-0028's propose/dispose split
exists to prevent; `learning/` is model-backed distillation and a reader infers
nothing; and `tools/` owns ADR-0017 §1's undesignated egress seam, which is the
rejection the deployment change makes *more* load-bearing rather than less — a
co-located fetcher is the pattern that most resembles a connector, and it is not
one. The fetcher does the network; the reader reads its output off disk.

The one reader today is :class:`~ai_assistant.readers.calendar.CalendarReader`.
**It has no caller yet**, which is how ADR-0093 §10's closing paragraph sequences
the work: the ``context/`` facet, the ingestion stage, the ``Engine`` operation
and the scheduler job are each a later lane.
"""

from __future__ import annotations

from ai_assistant.readers.calendar import (
    CALENDAR_READER_NAME,
    DEFAULT_CALENDAR_MAX_BYTES,
    DEFAULT_CALENDAR_MAX_CONTENT_BYTES,
    DEFAULT_CALENDAR_MAX_ENTRIES,
    DEFAULT_CALENDAR_MAX_EXPANSION,
    DEFAULT_CALENDAR_READ_TIMEOUT,
    DEFAULT_CALENDAR_WINDOW_FUTURE,
    DEFAULT_CALENDAR_WINDOW_PAST,
    MAX_CALENDAR_COUNT,
    MAX_CALENDAR_WINDOW,
    CalendarReader,
)

__all__ = [
    "CALENDAR_READER_NAME",
    "DEFAULT_CALENDAR_MAX_BYTES",
    "DEFAULT_CALENDAR_MAX_CONTENT_BYTES",
    "DEFAULT_CALENDAR_MAX_ENTRIES",
    "DEFAULT_CALENDAR_MAX_EXPANSION",
    "DEFAULT_CALENDAR_READ_TIMEOUT",
    "DEFAULT_CALENDAR_WINDOW_FUTURE",
    "DEFAULT_CALENDAR_WINDOW_PAST",
    "MAX_CALENDAR_COUNT",
    "MAX_CALENDAR_WINDOW",
    "CalendarReader",
]
