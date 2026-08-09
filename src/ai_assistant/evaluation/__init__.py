"""The evaluation slice: where a trace is stored, and nothing that reads one back.

Leg 8's instrument. An :class:`~ai_assistant.core.types.EvaluationTrace` records
that a named event occurred at a named seam — its instant, its duration, its
outcome, the ids it is about and the numbers it observed — and a *measure* is a
query over the stream rather than a field on a row (ADR-0119 §1). The
**contracts** live in `core`; the one implementation lives here, and this package
is a leaf:

    It may import ``core`` and nothing else in ``ai_assistant``; no subsystem may
    import it.

Both halves are enforced by ``lint-imports`` rather than asserted, in the shape
``readers/`` established — and here the leaf-ness is doing a second job. ADR-0119
§7 rules that **no component of the request pipeline may hold a seam carrying the
walk**, because "an instrument whose readings change behaviour is measuring a
system that includes the instrument" and leg 8's exit test would be circular. A
concrete store in a package no subsystem may import makes that mechanical instead
of reviewed: what you cannot reach, you cannot misuse. It also closes an egress
question by construction — a trace the pipeline cannot read is a trace `models/`
cannot send, so ADR-0004 §2 needs no new exception.

**Why a top-level package rather than an existing subsystem's.** No subsystem
owns telemetry, and each candidate misassigns it: `memory/` owns the Tier 1 store
whose reads this observes, and ADR-0119 §6 refuses to put traces in ``memory.db``
for the reason a trace about a failed write inside the failed write's own
database is lost exactly when it is wanted; `permissions/` owns the **Tier 1**
audit trail, and ADR-0119 §11 forbids merging the two stores in either direction;
`orchestration/` and every other pipeline package are the ones §7 forbids the
walk to. `service/` cannot hold it because nothing may import `service`
(ADR-0083 §8), so the composition root could not construct one.

The one store here is
:class:`~ai_assistant.evaluation.sqlite_store.SqliteTraceStore`, the **seventh**
SQLite database under ``Settings.data_dir`` (ADR-0119 §6). ADR-0083 ruling 4's
exclusivity needs nothing new for it: it lives inside the directory the instance
lock already covers, is opened by the same process, is closed in the same ordered
shutdown, and is reached only through the API.

It satisfies all three trace Protocols structurally, so the composition root
hands each collaborator exactly the seam it is entitled to — a ``TraceSink`` to
every emitter, a ``TraceRetention`` to the ``Engine``'s maintenance operation,
and the store itself to nothing in the pipeline.
"""

from __future__ import annotations

from ai_assistant.evaluation.sqlite_store import SqliteTraceStore

__all__ = ["SqliteTraceStore"]
