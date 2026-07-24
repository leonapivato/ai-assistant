# 56. A SqliteMemoryStore write snapshots its record before the first await

- Status: Accepted
- Date: 2026-07-24
- **Not a contract change.** This ADR touches no Protocol in
  `core/protocols.py`, no `core` type, and no `Settings` field. It fixes the
  *internals* of one durable-store implementation (`SqliteMemoryStore.add`) so its
  observable behaviour matches what the `MemoryStore` write contract already
  implies. Golden rule 5's separate-PR ratification does not apply, so this ADR is
  **Accepted on merge**, landed together with the implementation.

## Context

`SqliteMemoryStore` embeds a record's content *before* it serialises the record,
with an `await` in between:

```python
async def add(self, record: MemoryRecord) -> str:
    vector = await self._embed_one(record.content)   # await: the caller can run
    async with self._lock:
        await _run_to_completion(self._add_sync, record, vector)  # reads record now
    return record.id
```

`MemoryBase` models are mutable. The stored JSON (`record.model_dump_json()`), the
row's `id`, and the persisted vector are read at three different points, straddling
the embedder await. A caller that keeps a reference to the submitted record and
mutates it while the embedding coroutine is suspended can make those three reads
disagree: the backend persists a JSON payload — and an `id` — for the record's
*new* state, alongside a vector computed from its *old* content. A later `search`
then matches on a vector that has nothing to do with the stored text. This is a
torn write, surfaced by the adversarial review of PR #283 and parked as issue #286
against unchanged, pre-existing behaviour.

The batch path already solved the same problem. `write_atomic` (ADR-0046 §3)
`model_copy(deep=True)`s every submitted record before its first await and reads
only those copies thereafter, precisely so a caller aliasing a submitted record
and mutating it mid-embed cannot change the id its duplicate-id check validated or
desync content from the embedding. `add` — the older, single-record path — never
gained that guard, so the two write paths observed their input at different times.

The question this records: *when* does a `SqliteMemoryStore` write read the caller's
record, and can a mutation of the caller's object while the write is in flight tear
what is stored.

## Decision

We will take a **snapshot at the start of the awaited write** on every
`SqliteMemoryStore` write path. `add` deep-copies the submitted record on the first
line of its coroutine — *before the first await* — and derives the stored JSON, the
row `id`, the embedded content, and the returned id all from that one immutable
snapshot:

```python
async def add(self, record: MemoryRecord) -> str:
    snapshot = record.model_copy(deep=True)
    vector = await self._embed_one(snapshot.content)
    async with self._lock:
        await _run_to_completion(self._add_sync, snapshot, vector)
    return snapshot.id
```

This is the shape `write_atomic` already uses; the decision is to make `add` match
it, so **both** of the store's write paths observe their input at one instant —
before the first suspension point — and everything committed derives from that one
copy.

The snapshot boundary is precisely the coroutine's **first executed line**, not the
`add(record)` call expression. `add` is `async def`: calling it only builds a
coroutine; the body — and the `model_copy` — runs when the coroutine is first
awaited (or driven). The guarantee this buys is therefore exact and worth stating
without overclaim:

- A mutation made **while the write is in flight** — once the coroutine has started
  and is suspended on the embedder await, or later — cannot affect the write. This
  is the #286 tear: the embedder runs against the snapshot's content, and the same
  snapshot is serialised, so the persisted JSON and the persisted vector always
  agree. This is the property that matters and the one #286 is about.
- A mutation made in the narrow window **after the coroutine is constructed but
  before it is first awaited** *is* captured by the snapshot — the body has not run
  yet, so `model_copy` copies the already-mutated record. Crucially this is **not a
  tear**: the whole state is captured together, so the id, JSON, and vector still
  agree; the caller simply persisted the state as of the moment the write actually
  began. This matches `write_atomic` (also `async def`, also snapshotting on its
  first line) exactly, so the two paths keep identical semantics. We do **not**
  claim invocation-time capture, and deliberately do not restructure `add` into a
  synchronous wrapper returning an inner coroutine to obtain it: that would diverge
  from `write_atomic` and the other stores for a window that carries no torn write.

A deep copy is sufficient and no re-validation is added: the input is an
already-validated `MemoryRecord`, and the integrity the snapshot protects is
*internal agreement* among the id, JSON, and vector, not re-checking fields the type
already guarantees.

**We deliberately keep this a `SqliteMemoryStore` behaviour, not a universal
`MemoryWriter` obligation.** Promoting call-time-snapshot to a contract clause that
*every* `MemoryStore` implementation must honour — with the conformance suite and
the canonical fake asserting it in lockstep — is a larger, contract-surface change
(the shape of issue #314) that would ratify as its own ADR ahead of any
implementation (golden rule 5). This ADR does not do that. It records the input-
ownership decision for the persistent store and notes the universal obligation as
**deferred** to that separate lane. In practice the other writers already do not
tear: `InMemoryMemoryStore` and the canonical fake deep-copy on store and have no
embedder await between reading and storing, so they have no torn-write window to
close; only the SQLite store, which awaits an external embedder mid-write, did.

## Consequences

- **`add` and `write_atomic` observe their input identically.** Both snapshot on
  their coroutine's first line, so the store's two write paths read the caller's
  record at the same relative instant. A caller mutating a submitted record while
  the write is in flight — during the embedder await, or later — cannot change the
  stored id, desync the stored JSON from the persisted vector, or otherwise tear the
  committed write.
- **Two deterministic regression tests pin the semantics.** One drives a mutating
  embedder that rewrites the caller-held record's `id` and `content` from inside
  `embed()` (i.e. during the in-flight await); it asserts `add` returns the
  snapshot's id, does not relocate the row to the mutated id, and stores content
  that agrees with the vector computed for it — this fails on the pre-fix code and
  passes on the fix. A second mutates the record in the construct-then-await window
  and asserts the captured state is stored *consistently* (JSON and vector still
  agree), documenting the coroutine-start boundary so a later change cannot silently
  narrow or widen it.
- **The universal-obligation question is left open, on purpose.** If a future
  `MemoryStore` implementation introduces an await between reading and storing a
  record without snapshotting, it could reintroduce the tear at its own boundary.
  Closing that for *all* implementations — a contract clause plus conformance and
  fake parity — is tracked as the separate contract lane (issue #314's shape) and
  is the thing to do if a second awaiting writer appears; this ADR is the reference
  for why the persistent store snapshots and why the obligation was not universalised
  here.
- **No signature or contract change.** `add`'s signature, return value, and error
  behaviour are unchanged; only *when* it reads the record moved earlier. Nothing
  downstream needs to adapt.
