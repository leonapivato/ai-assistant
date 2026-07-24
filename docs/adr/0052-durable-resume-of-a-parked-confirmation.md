# 52. Durable resume of a parked confirmation through the façade

- Status: Accepted
- Date: 2026-07-24
- **This is not a contract change.** `Engine` is the concrete `orchestration`
  façade ADR-0042 §1 deliberately did *not* make a Protocol; it has one
  implementation and one class of consumer. So this ADR is Accepted on merge and
  lands **with** its implementation (golden rule 5 governs a `core/protocols.py`
  or `core/types.py` change, and this touches neither). It injects one existing
  Protocol (`AuditTrail`) into the façade, adds one façade method, and widens two
  of the façade's *own* `orchestration`-level DTOs (`TurnOutcome`, and the private
  `_Parked`). No subsystem boundary moves.

## Context

The durable pieces of restart-time confirmation recovery are already on `main`:

- `SqlitePlanStore` (ADR-0049) persists goals, plans and execution state, and its
  `active_executions()` returns every execution with a non-terminal step — the
  query "a restarting system issues to find work left in flight" (`protocols.py`).
- `AuditTrail.pending_confirmation(execution_id, step_id)` (ADR-0044 §3) recovers
  the parked `CONFIRM` for a binding *from the store that already holds it*,
  without the decision id a restart no longer has (#242).
- `StepRunner.resume(state, step_id, confirmation_id=None, ...)` already drives
  the **restart path**: with no caller-carried id it recovers the confirmation by
  binding and proceeds exactly as in-process (ADR-0044 §3, #242).

Two things stopped any of that being reachable by a real user:

1. **The production composition still wired the non-durable `InMemoryPlanStore`**
   (#318). Plan and execution state — including a parked `AWAITING_APPROVAL`
   step — did not survive a restart at all, so there was nothing durable to
   recover.

2. **The façade could not resume a durably-parked step it did not itself park**
   (#287). `Engine.resume` only accepts a `ContinuationToken` naming an entry in
   the engine's *in-process* `_parked` table. That table is empty after a restart,
   is never populated if `converse` raised *after* the runner durably parked the
   step (e.g. a faulty trail whose read fails on the second `get`), and is
   unrecoverable if the process-scoped token was dropped before it reached the
   adapter. ADR-0042 §4's "Revisit if … a token needs to outlive a process" and
   the issue itself name the fix as durable-resume work deferred to this lane.

The runner half of restart recovery exists; the façade never grew the door to it.
This ADR adds that door and flips the production default, so `ask → park → exit →
restart → resume` works end to end.

## Decision

### 1. The façade recovers parked confirmations from durable state

`Engine` gains one collaborator and one method.

**The collaborator: the `AuditTrail` the runner already holds.** The façade needs
the recorded `CONFIRM` to *display* a recovered confirmation — the ruling `reason`
and the tool declaration live only in the trail (ADR-0042 §4 makes the reason
non-optional), and after a restart the façade has no in-process disposition to
read them from. So the composition root injects the **same** `AuditTrail` instance
it already gives the runner. This is a composition-root single-instance obligation
of the same shape as ADR-0042 §2's `plans` rule: no type expresses it, and a
façade wired to a *second* trail would recover confirmations the runner's own
resume cannot resolve. The façade reads the trail **query-only** — it records
nothing; authoring rulings stays the runner's (ADR-0042 §6).

**The method:**

```python
async def pending_confirmations(self) -> list[Confirmation]
```

It reconstructs, from durable state alone, the confirmations a user may still
answer:

1. Enumerate `plans.active_executions()`.
2. For each execution, for each step in `AWAITING_APPROVAL`, recover the still-
   pending `CONFIRM` via `trail.pending_confirmation(execution_id, step_id)`. A
   binding already resolved returns `None` (ADR-0044 §3 step 1) and is skipped —
   the `#257` hazard §2b closes is not re-presented.
3. Read the raw parameters from the plan step (`plans.get_plan(plan_id)`), because
   the trail holds only a `parameters_digest`, not the values a user judges.
4. Assemble a `Confirmation` (tool id/description and reason from the recovered
   `CONFIRM`, parameters from the plan step) carrying a continuation token, and
   register the private `_Parked` entry that token names — so a subsequent
   `resume(token, ...)` resolves it through the **existing** in-process code path.

This is the "enumerate parked executions and re-mint a continuation" option #287
names, chosen over encoding durable identity *into* the token: the token stays a
meaningless opaque handle (ADR-0042 §4 forbids the adapter from interpreting or
constructing it), and durability comes from the fact that the handle is
*re-derivable from durable state on demand*, not from making the adapter carry a
structured value across a restart.

**One mechanism covers all three failure modes of #287** — a restart (the new
process enumerates and re-mints), a `converse` that raised after parking, and a
dropped token (both recovered in-process by the same call against the same durable
state). No separate in-process recovery path is needed.

### 2. Recovery is idempotent and bounded

`pending_confirmations()` reconciles against the `_parked` table rather than
appending to it: a binding `(execution_id, step_id)` already named by an entry
reuses that entry's handle instead of minting a second. So repeated calls return
stable tokens for the same parked steps and cannot grow the table without bound —
the table stays bounded by the number of *distinct durably-parked bindings*, which
is bounded by durable state, not by how often recovery is called. (The
`converse`-path ceiling `max_outstanding_confirmations` throttles *new* parks;
recovery presents parks that already happened and are already durable, so it does
not consult that ceiling — refusing to surface an already-parked step would strand
it, the exact failure §287 round 7 warns against.)

### 3. A recovered resume has no live turn

`Engine.resume` returns a `TurnOutcome`, whose `turn` is the originating
`TurnResult` (goal, context, retrieved memories, plan). A confirmation recovered
from durable state has **no** live turn: context and retrieved memories are
ephemeral and were never persisted (only the goal and plan are, in the
`PlanStore`). Rather than fabricate a `TurnResult` with empty context and
memories — which would misrepresent what the turn saw — `TurnOutcome.turn` and the
private `_Parked.turn` become **optional**. A resume driven from a recovered park
returns `TurnOutcome(turn=None, step=<resolution>)`; the in-process path is
unchanged and still carries the real turn. The step outcome — `EXECUTED` or
`DENIED`, and the durable state after it — is what a resume is *for*, and it is
always present.

This widens two of the façade's own DTOs, not a contract: `TurnOutcome` "crosses
no *subsystem* boundary, only `interfaces`" (ADR-0042 §1), and `_Parked` is
private to the engine. The recovered `_Parked` also carries `confirmation_id =
None`, routing `resume` through the runner's documented restart path
(`confirmation_id=None` → recover by binding, ADR-0044 §3) rather than caching a
decision id that a concurrent resolution could have staled.

### 4. The composition root wires the durable store, and the CLI exposes recovery

- `build_engine` constructs `SqlitePlanStore(path=directory / "plans.db")` in
  place of `InMemoryPlanStore()` (#318), reading its path from the same
  `data_dir` plumbing as `SqliteMemoryStore`/`SqliteAuditTrail` — no environment
  read, no hardcoded path. It is connection-owning, so it is opened alongside the
  other two (tracked for build-failure cleanup) and its `close` joins the façade's
  ordered shutdown path (ADR-0042 §2). The *same* instance is injected into the
  runner, the executor and the façade (the single-instance obligation ADR-0042 §2
  already documents for the plan store).
- `interfaces/cli.py` gains a `resume` command: it builds the engine, calls
  `pending_confirmations()`, renders each recovered action, collects the human's
  yes/no, and relays the opaque token via `engine.resume`. This is the adapter
  half of restart recovery — thin, authoring nothing (ADR-0042 §6). `ask` is
  unchanged: it still resolves a confirmation in-process when the same process
  parked it.

## Consequences

- A user can `ask` for a confirmable action, be parked, exit the process, restart,
  run `resume`, and answer it — the parked step survives on disk and resolves
  against the same durable execution. The `#287` gap is closed for the real
  failure modes (restart, post-park failure, dropped token), not merely narrowed.
- The production default is now durable: `SqlitePlanStore` (#318). Execution state,
  not only the audit trail, survives a restart.
- The façade reads the audit trail (query-only). It still authors no ruling; the
  read is exactly the recovery `pending_confirmation` was added for (ADR-0044 §3).
- `TurnOutcome.turn` is now `Optional`. Adapters that render a resume outcome must
  tolerate `turn=None` (the CLI does). The in-process `converse`/`resume` paths
  are unchanged.

**Revisit if** the plan-driving stage (#242) makes a turn drive more than one
step: recovery then enumerates several parked steps per execution (the method
already iterates all `AWAITING_APPROVAL` steps), and the CLI may want to present
them as a set rather than one at a time. And if a second engine implementation is
ever needed, the façade — including this method — promotes to a Protocol as a
triad (ADR-0042 §1's own Revisit clause), at which point `pending_confirmations`
joins the contract surface.

## Alternatives considered

- **Encode `(execution_id, step_id)` into the continuation token so `resume`
  reconstructs from the token alone, with no `pending_confirmations` call.**
  Rejected: it makes the token a structured value the adapter carries across a
  restart, and ADR-0042 §4 forbids the adapter from interpreting or constructing
  the token — a durable structured token invites exactly that. Enumerate-and-re-
  mint keeps the token opaque and meaningless outside the engine, deriving
  durability from re-queryable durable state instead.
- **Reconstruct a full `TurnResult` on recovery** (re-plan, or synthesise empty
  context/memories). Rejected: re-planning would run the model again and could
  return a *different* plan than the one parked; synthesising empties would
  misrepresent what the turn saw. `turn=None` is the honest representation of "no
  live turn, only durable state".
- **Give the façade its own audit-trail-free recovery** (store display content in
  the plan store at park time). Rejected: it would duplicate the `CONFIRM`'s
  reason and tool declaration into planning state, and reaching into `planning`'s
  schema is out of this lane's fence; the trail already holds them and
  `pending_confirmation` already returns them.
- **A new `AuditTrail` or `PlanStore` query method.** Not needed:
  `active_executions` + `pending_confirmation` + `get_plan` already compose into
  recovery. Had one been required, golden rule 5 would have made it a separate
  contract ADR first — it was not.
```
