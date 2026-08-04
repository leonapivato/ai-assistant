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

The one reader here is :class:`~ai_assistant.readers.calendar.CalendarReader`, and
a reading of it has the **two consumers ADR-0093 §3 gives one, reading at their
own cadences**: the ``context/`` facet reads at assembly time, ingestion reads on
its schedule, and neither derives its answer from the other's reading. The two are
not meant to agree — a facet read at 10:00 and a belief written from an 09:00 run
*should* state different things — which is what a reading's own instants are for.

**Each consumer holds its own reader instance rather than sharing one**
(ADR-0096 §5), because ADR-0093 §7 bounds a reader at one outstanding worker *per
instance*: a shared one would let a scheduled ingestion read suppress the
request-path facet for as long as it ran, coupling a request cadence to a periodic
job in the direction that makes an advisory facet wait.

Which objects hold those two ends is deliberately not named here. This package
imports nothing above ``core`` and nothing imports it, so it cannot see its own
callers — and a list of them here would be a snapshot, going stale silently rather
than loudly (`CONTRIBUTING.md` → "No state claims in living documents"). Each side
asserts its own wiring in its own tests.
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
