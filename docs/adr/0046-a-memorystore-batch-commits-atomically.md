# 46. A `MemoryStore` batch commits atomically, or not at all

- Status: Proposed
- Date: 2026-07-23
- **Contract change.** This adds one method — `write_atomic` — to the
  `MemoryStore` Protocol in `core/protocols.py`, plus a `MemoryWrite` value
  object and a `MemoryWriteMode` enum in `core/types.py` (both cross subsystem
  boundaries) and a `MemoryStoreConflictError` in `core/errors.py`. It therefore
  ships as its **own PR** and is ratified before anything implements against it
  (golden rule 5, ADR-0015 §5, `CONTRIBUTING.md` → "Contract ADRs land before
  their implementation"). **No code changes with it.** Extending the `MemoryStore`
  triad (the `MemoryStoreContract` obligations, the canonical `FakeMemoryStore`,
  and the two real backends) is a separate later lane.
- **Discharges** [ADR-0045](0045-memory-records-carry-a-validity-window.md) §8,
  which makes the window-closing `SUPERSEDE` applier two writes and rules #104 a
  hard prerequisite, deferring the primitive's *design* to "#104's lane and
  Protocol change." This ADR is that design. It is the answer to issue **#104**.
- **Refers to** [ADR-0028](0028-the-memory-write-path-is-a-contract.md) §7, which
  filed #104 and ruled that atomicity "has to come from the store," rejecting a
  batch method that is "a loop with a better name"; and to
  [ADR-0014](0014-planning-model.md)'s `PlanStore.commit_transition`, the
  in-repo prior art for a conditional store write.
- **Does not amend any prior ADR's body.** ADR-0045 §10 anticipated #104 closing
  issue #248 "alongside" this primitive; §5 of this ADR **declines** that,
  grounded in the design, and re-scopes #248 rather than editing ADR-0045 (which
  is itself `Proposed`, and which delegated the decision to this lane). No
  ratified text is rewritten; ADR-0001 keeps ADRs append-only.

## Context

[ADR-0045](0045-memory-records-carry-a-validity-window.md) §4 turns supersession
from one destructive upsert into **two** writes: close the target `T`'s validity
window (write `T` back with `valid_until = now`), and write the correction `P` as
a *new* record at a freshly-minted, previously-absent id. ADR-0045 §8 rules,
rather than assumes, that these two writes **must be atomic**: a failure or crash
between them leaves `T` retired with no live replacement — the belief vanishes
from reads, a regression from today's atomic single-upsert supersession. It names
two consumer requirements and then explicitly defers the primitive's design here:

1. **Atomic multi-write** — the window-close and the new-record write commit
   together or not at all.
2. **Insert-if-absent** — the new record's minted id, being probabilistic
   (`uuid4`), may collide; a collision must be **rejected**, not blind-upserted,
   so the applier can mint again rather than silently clobber the colliding
   record (ADR-0045 §4).

`MemoryStore` today offers neither. `add` is an unconditional upsert
(`core/protocols.py`: "Adding a record whose `id` already exists overwrites the
previous one") and there is no way to make two `add` calls one unit. Issue #104
filed this originally for the learning loop (ADR-0022 §4: multi-proposal learning
cannot be atomic), and ADR-0028 §7 ruled the fix must live on the store: a batch
method over a store with no transaction "is a loop with a better name — an
atomicity guarantee that holds only when nothing else writes." So the primitive
must be a genuine store-level transaction, not a convenience wrapper.

The in-repo prior art is `PlanStore.commit_transition` (ADR-0014 §5): the sole
write path for execution state, applied against the stored snapshot so an illegal
move is rejected rather than persisted, with a compare-and-swap on
`expected_version` and a distinct `StaleExecutionError` the caller catches to
retry. This ADR reuses two of its shapes — a single owned write path and a
distinct catchable error for the recoverable-and-retryable case — while
deliberately *not* reusing its `expected_version` compare-and-swap, for the
reason §5 gives.

The force against is the same one ADR-0045 weighed against its own field
additions: `MemoryStore` is a `core` contract with two production backends
(`InMemoryMemoryStore`, `SqliteMemoryStore`) plus the canonical `FakeMemoryStore`,
and every new capability is owed by all three. This ADR adopts the **minimum**
that discharges ADR-0045 §8's two requirements and stages the rest, exactly the
discipline ADR-0028 §7 and ADR-0040 §4 each applied in their own lane.

## Decision

### 1. One method, `write_atomic`, on `MemoryStore`

`core/protocols.py`'s `MemoryStore` gains a single method — the whole of the
Protocol surface change:

```python
async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
    """Apply every write in one atomic unit — all commit, or none do.

    The batch is ordered and all-or-nothing. On any element's failure — an
    ``INSERT_IF_ABSENT`` whose id already names a stored record, or any backend
    error — nothing in the batch is committed and the store is left exactly as it
    was. On success every record is persisted.

    Returns the ids written, in the order of ``writes``. An empty batch is a
    no-op and returns an empty sequence.

    Raises:
        MemoryStoreConflictError: an ``INSERT_IF_ABSENT`` element's id already
            names a stored record. Nothing is written; the caller may re-mint and
            retry.
        MemoryStoreError: any other backend failure, or a malformed batch (two
            writes to the same id, §3). Nothing is written.
    """
    ...
```

It is `async` like every other I/O method here, `@runtime_checkable` follows the
class, and the parameter is positional-or-keyword named `writes`. This is an
**addition to an existing Protocol**, not a new Protocol: `MemoryStore` already
has its triad (`MemoryStoreContract`, `FakeMemoryStore`, and the
`Test…Contract` bindings for the fake and both backends). No new store *verb* for
retirement is introduced — retirement remains an ordinary upsert (ADR-0045 §6);
`write_atomic` is the atomicity wrapper ADR-0045 §8 delegated here, and a
window-close rides it as an `UPSERT` element, not as a special `retire()` call.

### 2. Each element carries its own write mode

`core/types.py` gains a small value object and an enum. Both cross subsystem
boundaries (the applier in `memory` constructs them; the store in `memory`
consumes them; the contract in `core` names them), so they are `core` types
(`CLAUDE.md` → "Public data that crosses subsystem boundaries is a pydantic model
in `core/types.py`"):

```python
class MemoryWriteMode(StrEnum):
    """How one write in a batch treats a colliding id."""

    UPSERT = "upsert"                    # overwrite if present, insert if absent
    INSERT_IF_ABSENT = "insert_if_absent"  # fail the whole batch if present


class MemoryWrite(BaseModel):
    """One write within an atomic MemoryStore batch."""

    record: MemoryRecord
    mode: MemoryWriteMode = MemoryWriteMode.UPSERT
```

The two modes are exactly the two ADR-0045 §8 requires and no more:

- **`UPSERT`** reproduces today's `add` semantics — overwrite an existing id,
  insert an absent one. It is what a window-close is: the target `T` already
  exists, and the applier means to overwrite it with its window-closed form.
- **`INSERT_IF_ABSENT`** is requirement 2: write the record only if its id names
  no stored record; otherwise the **whole batch** fails with
  `MemoryStoreConflictError` and nothing is committed. It is what the new
  correction `P` is: a minted id that must not clobber an existing record
  (ADR-0045 §4).

The `SUPERSEDE` batch is therefore exactly two elements:
`[MemoryWrite(record=T_closed, mode=UPSERT), MemoryWrite(record=P, mode=INSERT_IF_ABSENT)]`.
A batch of one is legal and degenerates to a single atomic write (an `UPSERT`
batch of one is equivalent to `add`); it is not the intended shape but is not
forbidden, because forbidding it would be surface with no benefit.

No `DELETE` mode and no compare-and-swap mode are added — see §5 and §6. The
mode set is the minimum the one in-scope consumer (the ADR-0045 §4 applier)
needs.

### 3. "Absent" is physical presence, not read-visibility; a repeated id is rejected

Two semantics an implementer could get wrong, pinned here so the two backends and
the fake cannot diverge (the "consumer test passes on state the production writer
refuses" trap ADR-0045 §4 names):

- **`INSERT_IF_ABSENT` tests physical presence, not read-visibility.** An id is
  "present" iff a row is *stored* under it, regardless of whether that row is
  expired (ADR-0007) or window-closed (ADR-0045 §6). This is load-bearing: after
  a `SUPERSEDE`, the retained target `T` is window-closed and so is hidden from
  `get`/`search`, but its row still occupies `T`'s id. An `INSERT_IF_ABSENT`
  whose minted id happened to equal a retired record's id **must fail**, not
  succeed on the strength of the record being invisible to reads — otherwise the
  insert would clobber retained history, the exact loss ADR-0045 §4's absent-id
  obligation exists to prevent. Presence is "would a raw fetch by that id find a
  row," the same physical sense in which `add`'s upsert already overwrites an
  expired row rather than treating it as absent.
- **A batch containing two writes to the same id is rejected** as
  `MemoryStoreError`, before anything is written. The ordering-and-precondition
  semantics of "does the second element's `INSERT_IF_ABSENT` see the first
  element's write" is exactly where a sequential SQLite apply and a
  build-then-swap in-memory fake would diverge; the in-scope batch never repeats
  an id (`T` and `P` differ, ADR-0045 §4), so the ambiguous case is forbidden
  rather than defined. This is a property of the batch, checked before the
  transaction opens.

### 4. Failure is all-or-nothing, and the recoverable case is a distinct error

`core/errors.py` gains one error:

```python
class MemoryStoreConflictError(MemoryStoreError):
    """An INSERT_IF_ABSENT write's id already named a stored record.

    The batch was rolled back — nothing was written. The caller minted a
    colliding id and should re-mint and retry (ADR-0045 §4).
    """
```

It subclasses `MemoryStoreError` so every existing `except MemoryStoreError`
still catches it (the writer boundary already documents `MemoryStoreError` as the
only error that crosses the seam, ADR-0028 §5), while the ADR-0045 §4 applier
catches the **narrower** `MemoryStoreConflictError` to distinguish "id collided,
mint again" from "the store is broken, abort." This mirrors
`StaleExecutionError <: PlanningError` (ADR-0014 §5): a distinct, catchable,
recoverable-and-retryable failure under the general store error.

**A present id must surface as `MemoryStoreConflictError`, deterministically,
within the single-writer scope §5 fixes.** The contract pins the *observable* — a
stored id ⇒ `MemoryStoreConflictError` — not the mechanism; the durable backend is
obliged to reach it reliably rather than by luck. `SqliteMemoryStore` therefore
enforces `INSERT_IF_ABSENT` with a **uniqueness constraint / presence check inside
the batch's transaction** and maps a duplicate-key integrity error to
`MemoryStoreConflictError`, so a collision is never misreported as a generic
fatal `MemoryStoreError` (which would wrongly abort the applier's re-mint instead
of triggering it, ADR-0045 §4). The *cross-process* insert race — two
`SqliteMemoryStore` handles on one file both finding the id absent, the loser
getting `SQLITE_BUSY` or a stale-snapshot error rather than a clean uniqueness
error — is **§5's out-of-scope concurrency**, not this error-mapping obligation:
under the one-event-loop composition model a single writer observes an
unambiguous collision, and the cross-process case is the deferred compare-and-swap
lane (§5), which is where a busy/raced insert is linearised. A retry loop that
also caught a raced duplicate is a robustness the SQLite lane may add, but this
ADR does not require it, because it belongs to the cross-process story §5 defers.

The atomicity guarantee has **two obligations, scoped by durability**, because a
non-durable store has no post-crash state to protect and conflating the two would
hand the in-memory fake a contract it cannot meet:

- **In-call all-or-nothing — every backend, the fake included.** On **any**
  element's failure — a conflict, a repeated id (§3), or a backend error
  part-way through the batch — the store commits **nothing** and is left
  byte-for-byte as it was before the call. This is a purely in-process guarantee
  (the failure is observed and the partial work discarded before `write_atomic`
  returns), so `InMemoryMemoryStore` and `FakeMemoryStore` satisfy it by staging
  and only-then-applying (§Consequences), no persistence required.
- **Crash / durability atomicity — durable backends only.** Across a process
  **crash** between the notional two writes, a durable store must recover to
  *neither* write committed, never to the window-close alone — the ADR-0045 §8
  regression this primitive exists to prevent (a window-close that survives while
  its paired insert is lost would retire a belief with no replacement).
  `SqliteMemoryStore` meets this by wrapping the batch in one transaction, so a
  crash before `COMMIT` leaves nothing on disk. The obligation is **vacuous for a
  non-durable store**: a crash wipes an `InMemoryMemoryStore` in its entirety, so
  there is no half-applied on-disk state for it to guard, and requiring crash
  atomicity of it would be a contract term nothing can satisfy or test. Crash
  atomicity is therefore a property of the *durable* backend, not of the Protocol
  method uniformly.

### 5. Ruling on #248: this primitive does **not** close the cross-process lost update

ADR-0045 §10 lists, among what it does not decide, "the lost-update window in
`MemoryIngestor.ingest` (issue #248)," adding "#104 closes it alongside the
atomicity primitive this ADR depends on." Designing the primitive forces the
question to a decision, and the honest answer — grounded in *what #248's race
actually is* — is **no, `write_atomic` does not close it**, and here is exactly
why, so a later lane does not assume otherwise.

#248 is a read-modify-write race on the **`REINFORCE`/merge** path, not the
`SUPERSEDE` path: two concurrent `ingest`s both `search` for conflicts, both
snapshot the same target `T`, both `_merge` into their **stale** snapshot, and the
second `add` overwrites the first — one proposal's content and evidence silently
lost. Closing that needs the *write* to be **conditional on `T` being unchanged
since it was read** — a compare-and-swap, or a transaction whose scope spans the
conflict `search` itself.

`write_atomic` provides neither, by design:

- It makes a **write-set** atomic. The conflict `search` that produced the
  records happened *before* the batch is assembled and is not inside it, so a
  concurrent writer that changed `T` between the read and the `write_atomic` is
  still lost. Atomic-write-set is orthogonal to read-modify-write isolation.
- It carries **no compare-and-swap**. Adding one — a `MemoryWriteMode.IF_UNCHANGED`
  or an `expected_version` à la `commit_transition` — would need a concurrency
  token on `MemoryRecord`. `MemoryRecord` has no version field, and ADR-0045
  weighed and *avoided* the blast radius of adding envelope fields ("construction
  sites across `memory`, `learning`, `orchestration`, the two canonical fakes,
  and every test"). Overloading `Provenance.last_updated` as the token is barred
  too: ADR-0045 §3 keeps it "renaming nothing and changing no value."

The decisive point is that **#248 has no in-scope consumer to justify that
surface.** The system composes on one event loop (`CLAUDE.md`), and #248's
in-process race is **already closed** — PR #262 serialised `MemoryIngestor.ingest`
on an `asyncio.Lock`, which is the composition-model guarantee. The only residual
is two *processes* sharing one SQLite file, which the issue itself flags as out of
that lock's reach. Building a compare-and-swap with its record-level token for a
cross-process consumer that does not yet exist is precisely the "surface without a
consumer" ADR-0028 §7 and ADR-0040 §4 each declined — and, pointedly, the reason
ADR-0028 §7 rejected `ingest_all` in the first place.

So this ADR delivers the atomic write-set ADR-0045 §8 depends on, and rules that
**#248's cross-process lost update is not subsumed by it.** #248 stays open,
re-scoped from "closed by #104" to "a compare-and-swap extension of `write_atomic`
(a `MemoryRecord` concurrency token plus an `IF_UNCHANGED` mode), gated on a real
cross-process consumer." The in-process lock (#262) remains the answer under the
one-event-loop composition model. This refines ADR-0045 §10's loose "closes it
alongside" from the very lane §10 delegated it to; it does not relitigate a
ratified decision (ADR-0045 is `Proposed`), and it edits no ADR body (§Consequences
records the re-scoping as issue-tracker work, not an ADR amendment).

### 6. What this ADR does not decide

- **A compare-and-swap / conditional-on-unchanged write** (§5). Deferred with
  #248 until a cross-process consumer exists; it needs a `MemoryRecord`
  concurrency token this ADR does not add.
- **A `DELETE` element in a batch.** The one in-scope consumer (ADR-0045 §4)
  never deletes inside its atomic unit — it upserts a window-close and inserts a
  new record. A batched atomic delete has no consumer; `delete` stays the single
  unconditional verb it is. Added when a caller needs a delete atomic with other
  writes.
- **A cross-store / distributed transaction.** `write_atomic` is atomic within
  one `MemoryStore` instance. The composition-root obligation that the writer and
  its reader share one store instance (ADR-0028 §4) is unchanged and unrelated;
  two store instances are two transactions.
- **Batch *ingestion*** (`ingest_all` over `MemoryWriter`). ADR-0028 §7 rejected
  it and this ADR does not revive it: `MemoryWriter.ingest` keeps taking one
  proposal. `write_atomic` is a `MemoryStore` primitive the *applier* uses
  internally; it is not a multi-proposal writer surface.

## Consequences

- **Supersession can be implemented without regressing.** ADR-0045 §4's
  window-close-plus-insert becomes one `write_atomic` call, so a crash between the
  two writes commits neither — the regression ADR-0045 §8 refused to ship is
  structurally impossible, and the ADR-0045 §4 applier lane is unblocked.
- **This is a breaking `core` change**, flagged per golden rule 5. It is
  *additive* — no existing caller of `MemoryStore` breaks, since nothing calls
  `write_atomic` until the ADR-0045 §4 applier does — but it is contract surface
  all the same: every `MemoryStore` implementation (`InMemoryMemoryStore`,
  `SqliteMemoryStore`, and the canonical `FakeMemoryStore`) must now provide the
  method, which is why it is an ADR, why it merges alone ahead of any
  implementation, and why it carries the architecture review as well as the
  adversarial one.
- **The implementation owes**, in a later lane:
  - `core/types.py` — `MemoryWriteMode` (a `StrEnum`) and `MemoryWrite`
    (`record: MemoryRecord`, `mode: MemoryWriteMode = UPSERT`).
  - `core/protocols.py` — `MemoryStore.write_atomic` (§1); the class docstring
    gains the atomic-batch rule beside the expiry (ADR-0007) and window
    (ADR-0045) rules.
  - `core/errors.py` — `MemoryStoreConflictError(MemoryStoreError)` (§4).
  - `memory/sqlite_store.py` — `write_atomic` over a real SQLite transaction
    (`BEGIN`/`COMMIT`, rollback on any failure), with `INSERT_IF_ABSENT` enforced
    on physical presence (§3) and the whole batch inside one transaction so a
    crash before commit leaves nothing.
  - `memory/store.py` — `InMemoryMemoryStore.write_atomic` must **emulate**
    atomicity, since a `dict` has no transaction: validate the whole batch first
    (repeated ids, `INSERT_IF_ABSENT` presence) and stage all mutations, then
    apply them only if every check passed, so a mid-batch failure mutates nothing.
  - `testing/memory.py` — `FakeMemoryStore.write_atomic`, emulating atomicity the
    same way, so the fake honours the contract the two real backends do.
  - `memory/ingest.py` — ADR-0045 §4's `_supersede`/`_apply` build the two-element
    batch and call `write_atomic`, catching `MemoryStoreConflictError` to re-mint
    the id (bounded retry, ADR-0045 §4) and any other `MemoryStoreError` to abort
    with the target left live and unchanged (rollback guarantees it, §4).
  - `MemoryStoreContract` — extended with the `write_atomic` obligations (below);
    the existing `Test…Contract` bindings for the fake and both backends already
    run the extended suite.
- **The triad is extended, not created.** `MemoryStore`'s triad exists; this is a
  Protocol *change*, so `CONTRIBUTING.md` → "Adding a Protocol" applies as
  "extend the suite in the same change." The implementing PR extends
  `MemoryStoreContract` and the canonical fake and both backends together — one
  unit of work — so the new obligation is enforced, not assumed. The obligations
  the suite gains: an all-`UPSERT` batch commits every record and returns their
  ids in order; an `INSERT_IF_ABSENT` on an absent id succeeds; an
  `INSERT_IF_ABSENT` on a present id — including a window-closed or expired row
  (§3) — raises `MemoryStoreConflictError` and leaves the store unchanged (nothing
  from the batch committed); a batch that fails part-way (a valid element followed
  by a colliding one, in either order) commits nothing — the shared suite's in-call
  all-or-nothing case, driving a rollback after the first element is otherwise
  applicable; a batch with a repeated id raises `MemoryStoreError` and writes
  nothing; an empty batch is a no-op returning an empty sequence. Those logical
  failures are all the *shared* suite can drive uniformly across the fake and both
  backends. The **durable backend additionally owes a fault-injection test**,
  outside the shared suite: `SqliteMemoryStore` made to fail on the *second*
  element's physical write (a stubbed cursor error mid-transaction), asserting the
  first element's row **and its vector row** did not persist. Without it, an
  implementation that accidentally commits per element passes every logical case
  above while violating §4's all-or-nothing guarantee. That fault-injection test
  proves rollback on an *observed* error but not recovery after **process death**,
  which §4's durability obligation is separately about; the durable backend
  therefore also owes a **crash-recovery integration test** — a subprocess killed
  after the first transactional write, the database reopened, asserting **neither**
  batch mutation is visible (`T` not left window-closed, `P` not present) — since a
  per-element-commit or premature-`COMMIT` bug can survive the cursor-exception
  test yet leave `T` retired on reopen.
- **Issue #104 is answered**, not merely referenced: `MemoryStore` gets the atomic
  multi-write ADR-0022 §4 and ADR-0028 §7 filed. **Issue #248 is re-scoped**, not
  closed (§5): the cross-process lost update needs a compare-and-swap extension,
  gated on a cross-process consumer; the in-process lock (#262) stands.
- **Revisit if** a cross-process consumer needs the compare-and-swap (§5), if a
  caller needs a batched atomic `delete` (§6), or if a second-store atomic write
  is ever required (§6).

## Alternatives considered

- **A compare-and-swap primitive now (`expected_version` / `IF_UNCHANGED`),
  closing #248 in one move.** Rejected in §5. It is the `PlanStore.commit_transition`
  shape and would close #248's cross-process residual, but it needs a concurrency
  token on `MemoryRecord` — the envelope-field blast radius ADR-0045 deliberately
  avoided — for a consumer that does not exist (the system composes on one event
  loop; #262's lock already closes the in-process race). It is the "surface without
  a consumer" ADR-0028 §7 rejects. The atomic write-set is the strictly smaller
  capability ADR-0045 §8 actually requires, and the compare-and-swap remains a
  clean later extension of it.
- **A transaction *handle* spanning reads and writes**
  (`async with store.transaction() as tx: await tx.search(...); await tx.add(...)`).
  Rejected: it *would* close #248 (the conflict read is inside the transaction),
  but it is a far larger surface — a transaction context object, every read and
  write re-exposed on it, an isolation-level contract, and an in-memory fake that
  must emulate read isolation, not just write atomicity. ADR-0045 §8 requires
  atomicity of a *write-set*, not read-isolation; a handle buys the unneeded half
  at a large cost.
- **A `batch/transaction` method that is a loop with a better name** — apply the
  writes in sequence with no rollback. Rejected by ADR-0028 §7 already and again
  here: "an atomicity guarantee that holds only when nothing else writes" is worse
  than the documented absence, because the ADR-0045 §4 applier would report a
  successful supersession over a half-applied pair. The all-or-nothing guarantee
  (§4) is the whole point.
- **`ingest_all(proposals)` on `MemoryWriter` instead of a store primitive.**
  Rejected: ADR-0028 §7 already ruled atomicity must come from the store, not a
  writer wrapper. A batch of proposals over a non-atomic store is the same illusion
  as the previous alternative, one layer up. `write_atomic` is a `MemoryStore`
  verb the applier consumes; `MemoryWriter.ingest` stays single-proposal.
- **An `add(..., if_absent: bool = False)` flag plus a separate transaction, rather
  than a mode on batch elements.** Rejected: requirement 2's insert-if-absent must
  execute *inside* the atomic unit (an insert-if-absent outside the batch is not
  atomic with the window-close), so the condition belongs on the batch element,
  not on a standalone `add`. Folding it into `add` would leave the mode reachable
  outside the transaction, where it means less and tests differently.
- **A dedicated `retire(record_id, at)` verb for window-closing.** Rejected, and
  ADR-0045 §6 already did: retirement is an ordinary upsert of the record with its
  window closed, "not a new store verb." A `retire` verb would also not be atomic
  with the paired insert without the batch anyway, so it solves nothing the batch
  does not.
