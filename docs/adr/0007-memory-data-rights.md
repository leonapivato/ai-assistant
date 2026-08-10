# 7. Memory data rights and retention

- Status: Accepted, §3 amended by ADR-0045 (export returns window-closed records); Consequences' post-filter caveat amended by ADR-0128 (the expiry predicate binds before the ranking cut)
- Date: 2026-07-17
- Amended: 2026-07-23 by ADR-0045 — §3's "live (non-expired) snapshot" is
  widened to a **retained** snapshot. Once a superseded belief is retired by
  closing its validity window rather than overwritten (ADR-0045), it is data the
  store still holds, so a data-rights `export` must include it. `export` therefore
  returns every record whose `expires_at` has not passed, **whether its validity
  window is open or closed** — only *expired* records are excluded, because
  retention (a privacy deadline) still wins over history. The one clause this
  narrows is §3's "an export never resurfaces a memory that `get`/`search` would
  hide": that now holds only for the *expiry* axis, not the validity window,
  which `get`/`search` hide but `export` deliberately keeps (ADR-0045 §6). The
  §3 text below is unchanged (ADR-0001 append-only); every other ruling here —
  read-time retention, `clear`'s tier scope, the deferrals — stands.
- Amended: 2026-08-10 by ADR-0128 — **the Consequences bullet "Search inherits the
  existing expiry/kind post-filter caveat" describes a pass that stops existing.**
  [ADR-0128](0128-every-eligibility-predicate-binds-before-the-ranking-cut.md) §1
  rules that every read-time eligibility predicate `search` applies — `kinds`, §2's
  `expires_at`, and both ends of ADR-0045 §6's validity window — binds **before**
  the ranking cut, joining the band predicate ADR-0113 §2 already binds there. So
  the expiry predicate is no longer applied after the vector KNN, no over-fetch is
  required to pad for it, and the "tracked limitation" the bullet records is not
  narrowed or corrected but retired: an expired record never becomes a candidate
  at all.

  **Nothing this ADR decided moves, which is why this is an amendment and not a
  supersession** (ADR-0070 §1, ADR-0082 §1). §1's four data-rights operations, §2's
  read-time retention guarantee, §3's export snapshot and §4's tier scope are
  untouched, and §2 is if anything stronger — an expired record is still never
  returned by `get` or `search`, and now is never even ranked. The bullet is a
  statement of fact about the implementation at the time of writing rather than a
  rule an implementer obeys, which is how ADR-0112 §11 and ADR-0113 §11 each read
  it ("the residue it describes … read no more widely than it holds"). A reader
  acting on this ADR acts identically before and after.

  **This closes #792**, which asked whether the bullet's two-predicate count owed
  a record now that the pass carries three (the validity window having been added
  by ADR-0045 §6 and given a second producer by ADR-0110 §3). The answer is that
  the count is not corrected, because the pass it counts no longer runs; ADR-0128
  §8 argues it at the site. No text below is rewritten (ADR-0001 append-only), and
  the `Status` line's qualifier accumulates in the shape ADR-0082 §2 permits on a
  line carrying no leading supersession token. Refs #792, #457, #824, #922.

## Context

[ADR-0004](0004-privacy-and-data-handling.md) §6 requires, **from day one**,
that the user can view, export, and delete their data, and that memory support
retention rules (e.g. TTLs) so it does not accumulate indefinitely.
[ADR-0005](0005-memory-model.md) §4 deferred the exact signatures of those
operations to the slice that builds the persistent store — this one — and that
store now exists ([ADR-0006](0006-embedding-seam.md)): `SqliteMemoryStore` has
`add`, `get`, and `search`, and every record already carries an `expires_at`
retention deadline in `core.types.MemoryBase`.

But `expires_at` is only *stamped* — the policy sets it on a `STORE_TEMPORARY`
decision and the ingestor writes it, yet nothing ever reads it. An expired
record is still returned by `get` and `search`, and there is no way to delete a
record, delete everything, or export the store. So the persistent store, though
functional, does **not** yet meet ADR-0004 §6. This was flagged by the
architecture review as the one binding-ADR obligation left open.

Three forces make this a decision worth recording rather than an implementation
detail:

1. **It is a Protocol change.** `view/export/delete` and retention enforcement
   must be reachable by future callers (a CLI "export my data" / "forget this"
   command lives in `interfaces/`, which may depend only on `core` contracts —
   golden rule 1). So these operations belong on the `MemoryStore` Protocol, not
   on the concrete class. Adding to a Protocol is a breaking change (golden rule
   5) and needs an ADR.
2. **Retention has a correctness dimension, not just housekeeping.** An expired
   memory is one the system decided to forget; continuing to surface it in
   retrieval is a *privacy* regression, not merely stale data. Enforcement must
   therefore hold at read time, independently of whether any cleanup job has run.
3. **"Delete everything" spans tiers, but the store owns only one.** ADR-0004 §6
   says deleting the user's data purges Tier 0 (keyring secrets) and Tier 1 (DB
   rows) *together*. The `MemoryStore` owns Tier 1 rows only; coordinating a
   cross-tier purge is a higher-layer concern. This ADR must draw that boundary
   so the store's `clear` is not mistaken for a whole-system erase.

## Decision

We will extend the `MemoryStore` Protocol with four data-rights operations and
define retention as a read-time guarantee backed by an explicit purge.

### 1. Contract surface

`core/protocols.py` — `MemoryStore` gains:

```python
async def delete(self, record_id: str) -> bool:
    """Delete one record. Return True if a record was removed, else False."""

async def clear(self) -> int:
    """Delete all records. Return the number removed."""

async def export(self) -> list[MemoryRecord]:
    """Return a portable snapshot of all live (non-expired) records."""

async def purge_expired(self) -> int:
    """Physically remove records past their expires_at. Return the number removed."""
```

`add`, `get`, and `search` keep their existing names and async shape. This is an
**additive** Protocol change: existing callers are unaffected; new callers gain
the data-rights surface.

### 2. Retention is enforced at read time, and reclaimed by purge

A record whose `expires_at` is in the past is treated as **already forgotten**:

- `get` returns `None` for it; `search` never includes it.
- This holds regardless of whether `purge_expired` has run, so the privacy
  guarantee does not depend on a background job.

`purge_expired` is the *physical* reclaim — it deletes expired rows and reports
the count, so callers (a future scheduler) can reclaim space without changing
observable behaviour. "Now" is supplied by an injected clock on the store
(defaulting to UTC wall-clock), mirroring `MemoryIngestor`, so expiry is
deterministically testable.

### 3. Export is a portable, live snapshot

`export` returns the live records as `MemoryRecord` values. Because
`MemoryRecord` is a discriminated pydantic union, the caller serialises it to
JSON with `model_dump(mode="json")`; the store does not invent a bespoke format.
Export is **one-way** — it reflects what the store holds and will use; it does
not carry embeddings (they are re-derivable and model-specific), and importing a
snapshot back is out of scope here. Expired-but-not-yet-purged rows are excluded,
so an export never resurfaces a memory that `get`/`search` would hide.

### 4. `clear` deletes Tier-1 rows only

`clear` empties this store — its Tier 1 database rows. It is **not** a
whole-system erase: purging Tier 0 keyring secrets alongside the database (ADR-0004
§6) is a cross-tier operation owned by a higher layer once `permissions`/secrets
exist. This ADR deliberately scopes `MemoryStore.clear` to the memory tier and
records that the cross-tier coordinator is future work.

### 5. Deferred

- **Size/count caps.** ADR-0004 lists caps as an *example* retention rule
  alongside TTLs. Which records to evict when a cap is hit (oldest,
  lowest-confidence, least-recently-used) is a genuine policy decision that
  deserves its own slice; this ADR enforces TTLs only.
- **Import / restore** of an exported snapshot.
- **Cross-tier "delete everything"** (keyring + database), per §4.

## Consequences

- **The persistent store meets ADR-0004 §6.** Users can export and delete their
  memory, and expired memories genuinely stop influencing the system — closing
  the open architecture-review finding.
- **`interfaces/` can offer data-rights commands against the contract**, not a
  concrete class, keeping golden rule 1 intact.
- **Every `MemoryStore` implementation must now provide four more methods.**
  `InMemoryMemoryStore` gains them too (cheap dict operations), so downstream
  subsystems keep testing against a complete contract. This is the breaking part
  of the change and is why it is ADR-backed.
- **Search inherits the existing expiry/kind post-filter caveat.** As with the
  `kinds` filter, `search` applies the expiry predicate after the vector KNN
  (sqlite-vec cannot cleanly pre-filter joined columns within a KNN), so an
  over-fetch is used and remains a tracked limitation, not a regression.
- **Revisit if** we add size caps (an eviction policy decision), build import,
  or introduce the cross-tier purge coordinator — each is a follow-on ADR or
  amendment.
