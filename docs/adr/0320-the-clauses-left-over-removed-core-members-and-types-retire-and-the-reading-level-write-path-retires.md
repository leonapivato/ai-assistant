# 320. The clauses left standing over the residue lanes' removed members and types retire, and the reading-level write path retires

- Status: Proposed
- Date: 2026-10-14
- Scope: the phases after understanding, milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)): the records [#3018](https://github.com/leonapivato/ai-assistant/issues/3018) asks for, for the ratified clauses that bind the `core` members and types the residue lanes removed after ADR-0319's survey, and the decision [#2685](https://github.com/leonapivato/ai-assistant/issues/2685) asks for on its `MemoryWriter` half.
- Dependency: [ADR-0294](0294-readers-no-longer-ingest-into-memory-and-what-they-wrote-stays.md), [ADR-0309](0309-the-phases-are-built-beside-the-old-path-and-one-cutover-switches-the-controller-over-deletes-the-old-path-and-goes-live-in-one-deploy.md) and [ADR-0319](0319-the-decisions-the-cutover-left-standing-over-deleted-code-retire-the-stamp-drops-recalls-limit-and-an-unasked-memory-question-is-logged.md), all Accepted.
- Authorization: the dispatcher assigned 0320 and authorized ratifying this decision once its reviews are green; §2 is the dispatcher's ruling on #2685's `MemoryWriter` half.
- **Changes `core`: §2 removes a `Protocol` member, `MemoryWriter.ingest_reading`, a breaking change under golden rule 5.** Nothing the wire carries changes, since `MemoryWriter` is not on `AssistantEngine`'s surface. The records of §3–§5 change no code: the members and types they concern left `core` in the residue lanes, under ADR-0309 §5:1.

## Context

TODO

## Decision

TODO

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the dispatcher's authorization to ratify stands.

### 2. The reading-level write path retires

> **Normative.** `MemoryWriter.ingest_reading` leaves the `MemoryWriter` Protocol, with
> `MemoryIngestor.ingest_reading`, the canonical fake's member and the
> `MemoryWriterContract` cases that pin it. `MemoryWriter.ingest` is unchanged.

## Consequences

TODO

## Alternatives considered

TODO
