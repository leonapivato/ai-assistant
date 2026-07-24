# 49. A durable `PlanStore`: what a SQLite backend persists, and how it survives a restart

- Status: Accepted
- Date: 2026-07-23
- **Not a contract change.** The `PlanStore` Protocol
  (`core/protocols.py`) is ratified by ADR-0014 and strengthened by ADR-0044 §1
  (#303); this ADR adds an *implementation* of it and touches no Protocol, no
  `core` type, and no `Settings` field. Golden rule 5's separate-PR ratification
  does not apply, so this ADR is **Accepted on merge**. It is landed ahead of
  the implementation only as lane hygiene (the ADR is the smaller, more
  reviewable half), not because the contract must ratify first.
- **No ratified text changes here.** Everything below either chooses among
  options ADR-0014 and ADR-0044 left to implementations, or follows what those
  ADRs already settled. Where ADR-0044 §1 made execution-id non-reuse normative,
  this ADR discharges that obligation for a *persistent* store, which #303 named
  as "a separate future lane" that "will model restart as reopening its backing
  file".

## Context

Today the only production `PlanStore` is `InMemoryPlanStore` — dicts in process
memory, explicitly "not persistent" (ADR-0014 §5) — paired in the composition
root (`app/composition.py`) with a **persistent** `SqliteAuditTrail`. Everything
built on top of the ADR-0044 confirmation-recovery cluster (#303, #307) and the
#243 confirmation-lifetime rule is therefore only *theoretically* durable: the
audit trail survives a restart, but the execution state the trail's recovery
query keys against does not. A parked `AWAITING_APPROVAL` step, and the whole
notion that `StepRunner.resume` recovers it after a crash, evaporates on the
next process start. `memory` and `permissions` both have SQLite backends; the
planning subsystem's durable half is the missing one.

`SqliteMemoryStore` and `SqliteAuditTrail` set the house style this ADR follows
rather than reinvents: one owned `sqlite3` connection opened at construction
(`check_same_thread=False`), each async method taking an `asyncio.Lock` and
running its SQL in `asyncio.to_thread`, records stored as their pydantic JSON
dump and **rebuilt on every read** (which is how the "detached, validated
snapshot" obligation is met without a copy step to forget), an owner-only
(`0o600`) database file, and subsystem-native error translation at the boundary.
The design questions this ADR records are the ones that style does *not* answer
for planning specifically:

1. **What the durable schema is**, and how execution state — which moves only
   through the compare-and-swap `commit_transition` path — is stored so a
   version race is still lost by the writer that read a stale version.
2. **What is guaranteed to survive a restart and what is not** — the whole point
   of the store, and the load-bearing claim ADR-0044's recovery path rests on.
3. **How execution-id non-reuse (ADR-0044 §1, #280, #305) is met by a store
   that reopens a file** rather than by the in-memory store's per-incarnation
   random nonce — the mechanism the Protocol docstring already anticipates ("a
   store that instead keys on durable state it reopens … meets the same bar
   without a nonce").
4. **Whether #308** — a pre-ADR-0044 confirmation parked with `execution_id =
   NULL` across the upgrade boundary — is handled here or deferred.

## Decision

We will add `SqlitePlanStore` under `planning/`, a persistent `PlanStore` that
passes the existing conformance suite unchanged and follows the
`SqliteMemoryStore`/`SqliteAuditTrail` house style. The store delegates every
transition to the same `PlanExecution` tracker `InMemoryPlanStore` uses, so the
ADR-0014 §4 transition graph is authoritative in exactly one place and the two
stores cannot drift on it. What is new is persistence, and the decisions below
are only about that.

### 1. The schema and the migration

Four tables, created `IF NOT EXISTS` at construction inside one transaction,
with `PRAGMA foreign_keys = ON` set on every connection:

```sql
meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)
goals(id TEXT PRIMARY KEY, data TEXT NOT NULL)
plans(
    id       TEXT PRIMARY KEY,
    goal_id  TEXT NOT NULL REFERENCES goals(id),
    data     TEXT NOT NULL
)
executions(
    id       TEXT PRIMARY KEY,
    plan_id  TEXT NOT NULL REFERENCES plans(id),
    version  INTEGER NOT NULL,
    active   INTEGER NOT NULL,   -- 1 iff ExecutionState.is_active, maintained on write
    created_seq INTEGER NOT NULL,-- the allocation ordinal (see §3), for oldest-first order
    data     TEXT NOT NULL
)
```

**The foreign keys are enforced, not decorative, and they close a cross-process
orphan race.** `save_plan`'s app-level orphan check (ADR-0014 §5 rejects a plan
whose goal is unknown, so `export` can promise referential integrity without
repair) is a read; on its own it leaves a window in which one connection deletes
goal `g` between another's check and its insert, committing a plan whose
`goal_id` no longer resolves — the export-integrity violation the contract
forbids, and the same race between `start_execution` and `delete_goal`. The
`REFERENCES` constraints make that window unreachable: with foreign keys on, an
insert of a plan or execution whose parent has been deleted is refused by SQLite
and rolls back, rather than committing an orphan. This is the DB enforcing the
binding, beneath the app-level check that gives the caller the ADR-0014 error
shape.

The `data` column is the record: each row stores the pydantic model's
`model_dump_json()` and is rebuilt with `model_validate_json` on read, exactly as
the audit trail stores a `PermissionDecision`. The columns beside it exist only
so SQLite can index, order, cascade and compare-and-swap without decoding every
blob:

- `plans.goal_id` lets `delete_goal` find a goal's plans, and `export`/integrity
  reason about orphans, without scanning.
- `executions.version` is the compare-and-swap token. `commit_transition` reads
  the stored row, hands the decoded `ExecutionState` and the `StepTransition` to
  the tracker (which raises `StaleExecutionError` when `expected_version` no
  longer matches, `IllegalTransitionError` for an illegal move), and writes the
  new blob and version back — **all inside one `BEGIN IMMEDIATE` transaction**,
  so a second writer that read the same version cannot also commit: it reads the
  already-advanced version inside its own immediate transaction and the tracker
  rejects it. The `asyncio.Lock` serialises writers within one process; the
  immediate transaction serialises them across processes sharing the file.
- `executions.active` is `ExecutionState.is_active` computed and stored on every
  write, so `active_executions` selects `WHERE active = 1` and decodes only
  outstanding executions rather than the whole table.
- `executions.created_seq` is the allocation ordinal from §3, so
  `active_executions` returns oldest-first (`ORDER BY created_seq`) — the
  insertion order the contract requires — deterministically and without relying
  on rowid reuse behaviour.

**Every operation that reads-then-writes runs its whole read-check-write in one
`BEGIN IMMEDIATE` transaction** — not only `commit_transition` and
`start_execution`, but `save_goal` (its identity-change check), `save_plan` (its
orphan check), `delete_goal` (its live-step check and the cascade), and `clear`
(its live-step check). The immediate transaction takes SQLite's write lock at the
start, so no second connection can mutate what the check just read before the
write lands; the per-instance `asyncio.Lock` serialises writers within one
process, and the immediate transaction serialises them across processes sharing
the file. `delete_goal`'s cascade deletes children before parents — executions,
then plans, then the goal — so the enforced foreign keys are satisfied at each
step while the live-execution refusal still runs first, before anything is
removed.

**The migration is table creation only.** There is no prior persistent
`PlanStore` and therefore no on-disk schema to evolve: a fresh database is the
only starting state this store has ever had. A durable `meta("schema_version")`
row is written at creation so a *future* schema change has the version marker
`SqliteMemoryStore` had to backfill after the fact; this store starts with it.
Opening a database whose `schema_version` is newer than the code understands is a
loud `PlanningError`, not a silent best-effort read — a downgrade is a fault to
report, matching how the audit trail treats a row that no longer validates.

### 2. Crash and restart recovery semantics

**What is guaranteed across a restart.** Every state that a `commit_transition`
(or `save_goal`/`save_plan`/`start_execution`) *returned* has been committed to
disk before the call returned, so it survives a process exit at any later point.
Concretely:

- A goal, a plan, and an execution, once saved, reload identically.
- An execution parked at `AWAITING_APPROVAL` reloads with its `bound_tool`,
  `version`, `attempts`, and every other `StepExecution` field intact. This is
  the state ADR-0044 §3's recovery rests on: a restarted `StepRunner` reads the
  reloaded step, sees `AWAITING_APPROVAL`, and asks the persistent audit trail
  for `pending_confirmation(execution_id=state.id, step_id=…)` — and both
  `execution_id` (the reloaded execution's id, durable and non-reused per §3)
  and `step_id` are exactly the durable key that query needs. #243's lifetime
  rule reads the same reloaded `decided_at` from the trail. So the two halves of
  the confirmation cluster — the trail (already durable) and the execution state
  (durable here) — line up across a restart, which is the property that made the
  whole cluster only theoretical until now.
- An execution left `active` reloads as active and is found by
  `active_executions`, so a restarting system finds work left in flight (ADR-0014
  §5).

**What is not guaranteed, by design.** Durability of *recorded state* is not the
same as recovery of an *in-flight side effect*, and this store does not claim the
latter:

- A step found `RUNNING` after a crash may or may not have caused its side
  effect — the store cannot tell, and does not guess. Reloading it leaves it
  `RUNNING`; driving it to `INDETERMINATE` is `PlanExecution.abandon_running`'s
  job, invoked by recovery code above this store (ADR-0014 §4, ADR-0039 §7). The
  store's guarantee is that the `RUNNING` record *survives* to be recovered, not
  that it self-heals.
- A transition interrupted mid-commit is rolled back by SQLite's transaction —
  the store never reloads a half-applied version, a version without its blob, or
  a blob without its version. This is atomicity, not side-effect recovery.
- The `#257` window (a resolving decision recorded whose transition never
  committed) is made *safe* by ADR-0044 §2(b)/§3 in the trail, not *recovered*
  here; this store persisting execution state does not change that boundary.

### 3. Execution-id non-reuse: a per-incarnation nonce *and* a durable ordinal (#280, #305)

ADR-0044 §1 makes it normative that an execution id is never handed to a second
execution for the life of the audit trail — otherwise a stale parked `CONFIRM`
from a prior incarnation could recover onto a freshly-created execution with the
same id. The `PlanStore.start_execution` docstring names two acceptable
mechanisms: minted entropy (a nonce or uuid), or keying on durable state the
store reopens. This store uses **both**, and each earns its place because neither
alone covers every mode this store can be constructed in. The id is
`{plan_id}-exec-{incarnation}-{ordinal}`, matching `InMemoryPlanStore`'s format:

- **`incarnation` is a per-construction random nonce** (`uuid4().hex`), minted
  once when the store object is built, exactly as `InMemoryPlanStore` does. It is
  what makes non-reuse hold when the backing store is **not** durable — a
  `SqlitePlanStore(path=":memory:")`, whose database is fresh per connection and
  whose counter therefore rewinds to zero on every new instance just as the
  in-memory store's does. Two such instances get two different nonces, so
  `p-exec-<nonce-a>-1` and `p-exec-<nonce-b>-1` never collide. **This is the
  reason `:memory:` remains a safe construction** rather than a hole: the ordinal
  is worthless there, and the nonce carries non-reuse alone.
- **`ordinal` is a durable monotonic counter** in `meta("exec_counter")`,
  read-incremented inside the *same* `BEGIN IMMEDIATE` transaction that inserts
  the execution row. It carries the two guarantees the nonce cannot:
  - **Monotonic within one incarnation, never reset.** `delete_goal` and `clear`
    delete rows from `goals`/`plans`/`executions` but never touch
    `meta("exec_counter")`, so a deleted or bulk-erased execution's id is never
    re-minted — which the conformance suite already pins
    (`test_a_deleted_executions_id_is_never_reused`,
    `test_an_execution_id_is_not_reused_after_clear`). The nonce is constant
    within an incarnation, so intra-incarnation uniqueness is the ordinal's job.
  - **Fork- and multi-process-safe (the #305 hazard).** #305's fork case is two
    children inheriting one parent's in-memory nonce (copied by `fork`) and each
    starting a private counter at zero, so a nonce copied across the fork does
    *not* save them. A durable ordinal does: it is allocated by a read-increment
    under SQLite's write lock, so two processes — or two forked children — opening
    the same file are serialised and receive distinct ordinals, even sharing a
    copied nonce. So on a **file-backed** store the ordinal closes #305's fork
    hazard by construction rather than parking it, and additionally never rewinds
    across a restart (a reopened file resumes the counter, so a pre-restart id
    cannot recur even before the fresh nonce is considered — belt and braces).

So the two mechanisms are not redundant: on a file the ordinal gives fork-safety
and cross-restart monotonicity while the nonce is spare entropy; on `:memory:` the
nonce gives cross-instance non-reuse while the ordinal is spare. Every
construction mode is covered by at least one, and the sharp `:memory:` case — a
fresh in-memory instance paired with a persistent audit trail — is covered by the
nonce, not left open. #305's second item (injecting the nonce for deterministic
tests) is a follow-up on the in-memory/fake stores, out of this fence; the
file-backed restart test here asserts non-reuse by reopening the same file, where
the durable ordinal alone already proves it without depending on nonce entropy.

### 4. #308 is deferred, and this store neither closes nor widens it

#308 is a pre-ADR-0044 `CONFIRM` written with `execution_id = NULL`, parked on a
step that was already `AWAITING_APPROVAL` at the instant the app upgraded to the
ADR-0044 code; after a restart, `pending_confirmation` keyed on a concrete
`(execution_id, step_id)` returns `None` for it, so it is recoverable only via
the in-process path. That edge lives entirely in `permissions`/`orchestration` —
it is about a `PermissionDecision` in the audit trail and the query over it, not
about anything `planning` stores. This store persists execution state and its
durable execution ids; it does not store confirmation records and cannot resolve
a `NULL`-execution confirmation without reintroducing the cross-execution
substitutability #253 closed (the two obvious fixes #308 already rejects). So
#308 is **deferred**, left open, and unaffected by this lane: a durable
`PlanStore` is a prerequisite for any real upgrade-boundary scenario but not the
place the fix belongs (#308 routes it to the durable-continuation design in
#287/#242). No new state is added here to pre-empt it.

### 5. Tests: the durable behaviour the conformance suite cannot reach

Passing the shared `PlanStore` conformance suite unchanged is necessary but not
sufficient: that suite is instantiated for `InMemoryPlanStore` and the fake, and
by its own note "restart" is persistence-model-specific, so it deliberately does
*not* exercise reopening a file. The durable guarantees in §§2–3 therefore get
their own SQLite-specific, deterministic tests in the implementation PR, opening a
real database at a temp path (not `:memory:`, which shares nothing across
connections):

- **Close/reopen state recovery** — save a goal and plan, park an execution at
  `AWAITING_APPROVAL` with a `bound_tool`, drop the store object, reopen against
  the same file, and assert the reloaded step's status, `bound_tool`, `version`
  and other fields are intact and the step is resumable (a `RUNNING` transition
  commits).
- **Execution-id non-reuse across a reopen** — start an execution, `delete_goal`
  (and, separately, `clear`), reopen the file, start another execution, and
  assert the new id differs from the first: the durable `exec_counter` did not
  rewind.
- **Execution-id non-reuse across two fresh `:memory:` instances** — the mode
  where the durable counter is *worthless* (a `:memory:` database is fresh per
  instance), so this is what proves the per-incarnation nonce (§3) actually
  carries non-reuse there. Two independently-constructed
  `SqlitePlanStore(path=":memory:")` stores each start `p1`; assert the two ids
  differ. Mirrors `InMemoryPlanStore`'s own fresh-instance test.
- **Atomic rollback of an interrupted write** — a `commit_transition` whose
  transaction does not complete leaves the store reloading the prior version, never
  a half-applied one (no version without its blob, no blob without its version).
- **Concurrent-connection CAS and allocation** — two connections on one file:
  two writers computing a transition against the same version leave exactly one
  committing and the other seeing `StaleExecutionError`; two `start_execution`
  calls receive distinct ids; and the foreign keys refuse an orphaning insert.

These sit in an impl-level test module (as #303's restart tests do), not in the
shared suite, because they assert this store's persistence model rather than the
contract every store owes.

## Consequences

- **The ADR-0044 cluster and #243 become genuinely durable.** With this store
  wired in, a parked confirmation and its execution survive a restart, so
  `StepRunner.resume`'s recovery path and the confirmation lifetime are real
  rather than theoretical. That is the whole reason the lane exists.
- **The composition root is not switched in this lane.** `app/composition.py`
  still constructs `InMemoryPlanStore`, and switching the production default to
  `SqlitePlanStore` is left as a follow-up so the shipped default is not
  destabilised inside this fence (composition is `app/`, outside `planning/`).
  The follow-up carries the wiring obligations ADR-0042 §2 already documents
  (one store shared by runner, executor, and façade; its `close` on the shutdown
  path) and the `data_dir`/path question. Tracked as a GitHub issue.
- **Where the DB file lives is the composition root's call, not the store's.**
  Like `SqliteMemoryStore` and `SqliteAuditTrail`, the store takes an explicit
  `path` with no default — durability is the reason it exists, so an ephemeral
  `:memory:` store must be asked for by name, never produced by omitting an
  argument. `Settings` gains nothing here (ADR-0036 §3's precedent: a filesystem
  location is the composition root's, not a `Settings` field), which also keeps
  this ADR off `core/`.
- **#305 does not gate this store and is not reopened by it.** Its hazards are
  structurally absent from a durable counter (§3); it remains an in-memory/fake
  concern outside the fence.
- **#308 stays open** (§4), a narrow upgrade-instant edge in `permissions`, to be
  settled with the durable-continuation work (#287), not here.
- **Revisit when** the composition root switches its default to this store (the
  follow-up), or when a second durable schema version is needed — at which point
  the `meta("schema_version")` marker written from day one is the seam a real
  migration hangs off, rather than a column backfilled after the fact.
