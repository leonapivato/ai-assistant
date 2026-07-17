# 5. Memory model: typed memory, provenance, and update proposals

- Status: Accepted
- Date: 2026-07-16

## Context

The `memory` subsystem currently exposes a `MemoryStore` Protocol over a single,
flat `MemoryRecord` (`id`, `content`, `metadata`, `created_at`, `score`) and one
in-memory implementation. That was enough to give downstream subsystems a real
contract to build against, but it is not the memory model the product needs, and
`docs/roadmap.md` flags this as the decision that must land before the persistent
store is built.

Three problems with a flat, untyped blob:

1. **No structure.** An episode ("discussed internships with Prof. Smith"), a
   durable fact ("Prof. Smith teaches quantum computing"), a preference ("prefers
   concise emails"), and a workflow ("organise interview notes by question") have
   different fields, lifetimes, and retrieval semantics. Collapsing them into one
   shape loses all of that.
2. **No provenance.** Without knowing *how confident* we are and *why*, a single
   unusual interaction can harden into a permanent, wrong "preference." There is
   also no principled way to distinguish facts the user **asserted** from beliefs
   the assistant **inferred**.
3. **Unmediated writes.** If the model can write arbitrary statements straight
   into permanent memory, memory becomes an unbounded, unreviewable side effect —
   exactly the risk `docs/roadmap.md`'s "the LLM proposes; deterministic services
   dispose" principle exists to contain.

This decision defines the memory *domain model* and the *write path*. It does not
choose the storage backend — [ADR-0002](0002-foundational-stack-and-architecture.md)
already commits to local-first SQLite (+ vector search), and the concrete backend
is a later slice. It works within the data-handling rules of
[ADR-0004](0004-privacy-and-data-handling.md) (Tier 1 personal data, retention,
export/delete).

Per golden rule 5 in `CLAUDE.md`, this is a **breaking Protocol/`core` change**
and is flagged as such.

## Decision

### 1. Memory is typed, not a flat blob

`MemoryRecord` becomes a **discriminated union** (pydantic, on a `kind` field —
named `kind` rather than `type` to avoid shadowing the builtin) of four record
types, each sharing a common envelope and adding its own payload:

- **`EpisodicMemory`** — something that happened: `occurred_at`, `participants`,
  `outcome`, `importance`.
- **`SemanticMemory`** — a durable fact: `fact`, optional `valid_until`.
- **`PreferenceMemory`** — a user preference: `preference`, `context`,
  `strength`.
- **`ProceduralMemory`** — a learned workflow: `situation`, `steps`.

The shared envelope on every record:

- `id: str`
- `kind: Literal["episodic" | "semantic" | "preference" | "procedural"]`
- `content: str` — a canonical text rendering of the record, used for lexical and
  (later) embedding retrieval. Structured payload and retrieval text coexist.
- `provenance: Provenance` (see §2)
- `score: float | None` — relevance, populated by retrieval, `None` when stored.

### 2. Every record carries provenance; profile vs. model is a provenance query

A `Provenance` value is attached to every record:

- `source: MemorySource` — one of `USER_ASSERTED`, `OBSERVED`, `INFERRED`,
  `EXTERNAL`.
- `confidence: float` in `[0.0, 1.0]`. `USER_ASSERTED` records are `1.0`.
- `evidence: list[str]` — references (e.g. episode ids) supporting the record.
- `last_updated: datetime` (timezone-aware, per the `DTZ` lint rule).

The **User Profile vs. User Model** distinction is expressed *through* provenance,
not through separate stores or Protocols:

- The **profile** is the set of `USER_ASSERTED` records (`confidence == 1.0`) —
  what the user told us directly.
- The **user model** is the set of inferred records (`OBSERVED`/`INFERRED`,
  `confidence < 1.0`) — what we believe about them.

We deliberately keep **one** `MemoryStore` seam and treat the profile/model split
as a query concern (filter by `source`/`confidence`). Two storage Protocols would
duplicate the contract for a difference that is really about data provenance.

### 3. The model proposes; a deterministic policy disposes

Memory is never written directly by the model. Instead:

- A `MemoryUpdateProposal` carries a candidate record plus the metadata a policy
  needs to judge it: `proposed: MemoryRecord`, `sensitivity: DataTier` (the
  ADR-0004 tier), `rationale: str`, and `conflicts: list[str]` (ids of existing
  records the proposal contradicts, filled by the conflict check).
- A deterministic `MemoryPolicy` decides the outcome, one of: **accept**,
  **reject**, **merge** (into an existing record), **ask the user** (defer for
  confirmation), or **store temporarily** (accept with an expiration). This is
  the memory-specific instance of the roadmap's propose/dispose principle.

Responsibilities split across subsystems (each its own later slice):

- `learning` turns feedback/observations into `MemoryUpdateProposal`s.
- `memory` owns conflict detection, applies accepted proposals, and enforces
  retention/expiration.
- The `MemoryPolicy` Protocol lives in `core` so both can depend on it.

### 4. Protocol surface and migration

New/changed contracts in `core`:

- `core/types.py` gains `MemorySource`, `Provenance`, the four memory models, the
  `MemoryRecord` discriminated union, `MemoryUpdateProposal`, and a
  `MemoryDecision` describing the policy outcomes above.
- `core/protocols.py`: `MemoryStore.search` gains an optional `kinds` filter;
  `MemoryStore` gains `get(id) -> MemoryRecord | None`. A new `MemoryPolicy`
  Protocol is added. (`add`/`search` keep their existing names and async shape.)
- Export/delete/retention operations required by ADR-0004 are implemented on the
  concrete persistent store; this ADR does not fix their exact signatures.

Migration is sequenced as small slices, not one commit:

1. **Types + contract** — land the typed models and the updated `MemoryStore`;
   update the existing `InMemoryMemoryStore` (its lexical `search` keeps working
   on the envelope `content`) and its tests.
2. **Proposals + policy** — `MemoryUpdateProposal`, `MemoryDecision`,
   `MemoryPolicy`, and a first deterministic policy, driven from `learning`.
3. **Persistent store** — SQLite + vector backend (needs the embedding seam) with
   ADR-0004 file permissions, retention, and export/delete.

## Consequences

- **Retrieval and reasoning get richer.** Callers can filter by `kind`, weigh
  results by `confidence`, and explain *why* a memory exists from its `evidence`.
- **Memory stops being an unbounded side effect.** Every write goes through a
  reviewable proposal → policy path, and false or oversensitive memories can be
  rejected, expired, or bounced to the user.
- **This is a breaking change.** `MemoryRecord` is no longer a plain
  `content`-string record; existing construction sites (the in-memory store and
  its tests) must be updated in the first migration slice. Callers already depend
  only on the `MemoryStore` Protocol, which limits the blast radius.
- **More types to maintain.** Four record types plus provenance and proposal
  models are more surface than one blob — accepted as the cost of not conflating
  four different things.
- **A new `MemoryPolicy` seam** must be designed and tested before automated
  memory writes are enabled; until it exists, memory writes stay explicit/manual.
- **Embedding dependency deferred but implied.** Semantic retrieval over these
  records needs an embedding capability; introducing that seam is its own ADR,
  triggered when slice 3 begins.
- **Revisit if** the four-kind taxonomy proves too coarse or too fine in
  practice, or if the single-store/provenance-query approach to profile-vs-model
  turns out to need physically separate stores (e.g. for differing encryption or
  retention policy).
