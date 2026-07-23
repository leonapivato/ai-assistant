# 44. Durable confirmation: binding a parked CONFIRM to its execution, recoverable after restart

- Status: Proposed
- Date: 2026-07-22
- **This is a contract change, and a cross-subsystem one.** It adds a field to
  `ActionRequest` and `PermissionDecision` in `core/types.py` (read by
  `authorises`), extends `AuditTrail.record`'s resolution invariant, adds one
  query method to the `AuditTrail` Protocol in `core/protocols.py`, adds a guard
  in `orchestration/executor.py`, **and depends on a `planning` contract
  guarantee of execution-id non-reuse** (§1) — the review of this ADR established
  that last one is required, not optional. Golden rule 5 therefore governs it: the
  ADR is ratified in its own PR and merges **before** the triad that implements it
  (the extended conformance suite, the canonical fake, and `SqliteAuditTrail`),
  and the `planning` non-reuse guarantee lands **with or ahead of** that triad.
  It touches the two highest-collision files in the repository and reaches into
  `planning`, so the dispatcher sequences it against in-flight `core/types.py`
  work and the `planning` change rather than racing either.

## Context

PR #249 (ADR-0037) made execution able to *park*. When `ActionPolicy.decide`
returns `CONFIRM`, `StepRunner` records the decision, commits the step
`PENDING → AWAITING_APPROVAL` carrying `bound_tool`, and returns the recorded
decision's id in its `StepDisposition`. `StepRunner.resume` later takes a
human's answer, hands it to `ActionPolicy.resolve`, and records a resolving
decision whose `resolves` names the confirmation.

ADR-0037 §4 named two gaps in that design as out of its fence, and both are now
live:

- **#242 — the confirmation's decision id does not survive a restart.**
  ADR-0014 §4's `→ AWAITING_APPROVAL` transition sets `bound_tool` and nothing
  else, and `StepExecution`'s validator actively *forbids* `approval_ref` on an
  `AWAITING_APPROVAL` step ("an AWAITING_APPROVAL step is undecided, so it has no
  approval_ref"). So a reloaded step says *that* it is awaiting an answer and
  *which tool* it is about, but not *which recorded `PermissionDecision`* to hand
  to `ActionPolicy.resolve`. `resume` therefore takes the id from its caller, and
  after a restart the only recovery is to scan `AuditTrail.recent()` by hand.

- **#253 — a confirmation is not bound to the execution that parked it.**
  ADR-0021 §1 binds an approval to the tool, the parameters and the *step*, and
  `ActionRequest` has no field for an execution. `PlanStore.start_execution`
  opens one execution per call, so one plan can have several concurrently.
  ADR-0037 §4's `_check_parked` closed the sharp half — a confirmation parked in
  execution A cannot release the same step in execution B while B still holds it
  `PENDING`, because `resume` requires the step to be `AWAITING_APPROVAL` **in
  the stored execution**, bound to the confirmation's own tool. What remains: two
  executions of one plan, *both* genuinely parked on the same step, are mutually
  substitutable. The trail's single-resolution index bounds the damage — one
  confirmation authorises exactly one resolution — so what is at stake is *which*
  of two identical parked executions proceeds, not whether an unapproved one
  does.

ADR-0037 §4 recorded that these are "the same missing capability … an argument
for settling them together", and the composition is why: recovering a parked
confirmation after a restart is a *query* against durable state, and the key
that query needs — which execution, which step — is exactly the binding #253 is
missing. Settle the binding and the recovery query becomes well-defined; settle
the recovery query alone and it has no unique key to return.

A third gap, #243 (a pending confirmation has no lifetime), is **not** settled
here. It needs no durable-state change — `PermissionDecision.decided_at` already
records when the question was asked, and the resuming stage already holds an
injected clock — so it is an `orchestration`-internal rule, not a contract
change, and lands separately. ADR-0036 §1 already placed it there
("staleness … is `orchestration`'s to enforce"). This ADR only notes the seam it
will use, so the cluster is accounted for.

## Decision

We will make the confirmation record carry the execution it was made in, extend
the resolution invariant to bind on it, and add a by-binding query to
`AuditTrail` so a restarted process can recover the parked confirmation from the
trail — the store that already holds it.

### 1. `execution_id` on the request and the decision (#253)

Add an optional field to `ActionRequest`:

```python
execution_id: DurableIdentifier | None = Field(
    default=None, description="The execution this action belongs to, if any."
)
```

and transcribe it onto `PermissionDecision` the same way `step_id` is — copied
by `PermissionDecision.from_request`, never asserted by a caller — so a decision
naming a different execution than the one the policy saw cannot be produced by
following the contract. `StepRunner` fills it from the `ExecutionState` it is
already holding (the detached snapshot, so it is the execution the caller named
before the first await).

`DurableIdentifier | None`, not required, for the same reason `step_id` is
optional: an `ActionRequest` can be ruled on outside a plan execution (a direct
tool call has no execution), and a decision made there simply carries `None`.
The field is serialisable by construction, which the `PermissionDecision`
round-trip obligation (ADR-0021 §4) already requires of every field.

**`authorises` reads it too, and this is the half that actually closes #253's
execution seam.** `PermissionDecision.authorises(request)` compares `tool`,
`parameters_digest` and `step_id` today; it gains `execution_id` as a fourth
conjunct. This is load-bearing, not symmetry: `authorises` is the check
`ToolCall`'s validator runs before the executor claims a step, so it is where a
decision is bound to *what it may run*. Without `execution_id` in it, a decision
resolved (or auto-granted) for execution A — same tool, same digest, same step id
as B's — answers `authorises` `True` for a request naming execution B, and an
executor handed B's state and that decision would run B under A's approval,
never resolving B's own parked question. That is exactly the cross-execution
substitutability #253 is about, at the seam that runs the tool rather than the
one that records a resolution, so binding only the resolution invariant (§2)
would leave it open. It still satisfies ADR-0016 §2's test for living on the type
— computable from the two values alone, independent of policy, config, context
and clock — because an execution id is a value on both records, not a decision.

**But `authorises` binds the decision to the *request*, not to the *state* the
executor claims — so the executor must close the last gap.** `ToolCall`'s
validator checks decision ↔ request, and a `ToolCall` whose request *and*
decision both name execution A is internally consistent; nothing there stops a
caller passing that call to `StepExecutor.execute(state=B, step_id=…)`, where the
executor today checks only `call.request.step_id == step_id` before claiming.
It would then claim B's step under a call bound to A. So the executor gains one
conjunct to the guard it already runs: **`call.request.execution_id == state.id`,
checked before the claim.** With that, the three seams line up — the decision is
bound to the request (`authorises`), the request is bound to the state being
claimed (the executor), and the resolution is bound to the confirmation (§2) —
and none of the three alone is sufficient. This is a change to
`orchestration/executor.py`, specified here and landing in the implementation PR.

An earlier draft kept `execution_id` *out* of `authorises` and argued the
substitutability was purely a resolution-time question; that was wrong, and the
review that found it is the reason this section now reads the other way. §2 stops
a *wrong resolution being recorded*, `authorises` stops a *right-looking decision
being executed against the wrong request*, and the executor's new conjunct stops
a *right-looking call being claimed against the wrong execution*.

**The recovery binding requires execution ids to be non-reusable, and that is a
`planning` contract change this decision *depends on* — not an assumption a
composition root can discharge.** `(execution_id, step_id)` identifies one
execution instance only if an id is never handed to a second execution within the
audit trail's retention; otherwise `pending_confirmation(E, step)` could return a
stale `CONFIRM` from a prior incarnation of `E` for a freshly-created one, and its
old answer, matching tool and parameters, could resolve and run the new action.
It is tempting to push this onto the composition root, but the composition root
*cannot* enforce it: `PlanStore.start_execution` owns creation of the
`ExecutionState` and accepts no caller-supplied id, so non-reuse is entirely the
store's behaviour. A conforming store may delete execution `E` and later create
another named `E`, and nothing in the current contract forbids it.

So this ADR makes non-reuse **normative**, and that is part of the decision: the
implementation depends on **`PlanStore.start_execution` guaranteeing that an
execution id is unique for the life of the audit trail** — either by contract
(the minimal change, since minted uuids already satisfy it, so it ratifies
existing behaviour rather than changing it) or, if that guarantee is judged too
strong, by carrying a durable execution-*incarnation* id in the binding that
`PlanStore` guarantees unique. Either is a `planning` change, so under golden
rule 5 it is its own contract decision, sequenced **with or ahead of** this one;
the implementation of ADR-0044 must not land until it holds. Tracked in the
follow-up issue (below). This is called out in the decision, not buried in an
assumption, precisely because the review that found it showed the assumption was
one no in-scope party could keep.

### 2. The resolution invariant binds on the execution, and a binding resolves once

`AuditTrail.record` already refuses a resolving decision unless the confirmation
it names matches on `tool`, `parameters_digest` and `step_id` (ADR-0021 §1,
ADR-0036 §2). This section extends the invariant twice.

**(a) The resolution's `execution_id` must equal the confirmation's (#253).**
Today two executions A and B of one plan, both parked on the same step, produce
two `CONFIRM` records identical in tool, digest and step but differing in
`execution_id`. A resolving decision built for B can name A's confirmation and
pass every current check. With the added conjunct it cannot: the resolution is
bound to the confirmation whose execution it shares, so A's answer resolves A's
question and B's resolves B's.

**(b) A *concrete* binding `(execution_id, step_id)` may carry at most one
resolution — a per-*binding* rule that sits *on top of*, not in place of,
ADR-0036 §2's per-*confirmation* one.** This is the load-bearing correction over
the first draft. ADR-0036 §2's unique index on `resolves` stops the *same*
confirmation being resolved twice, and it stays exactly as it is — it is what
keeps two unrelated *direct* confirmations (each with `execution_id` and
`step_id` unset) independent, since they share no binding to collide on. The new
rule is an *additional* constraint that fires **only when both `execution_id` and
`step_id` are present**: for a parked plan step, ADR-0037 §2 *accepts* several
unresolved `CONFIRM`s under one binding (a `run` that lost the
`PENDING → AWAITING_APPROVAL` compare-and-swap still leaves its `CONFIRM`
recorded, §3), and those are the *same action* — one step of one execution — so
they must share one *fate*. The per-confirmation index alone does not give that:
with it, a step whose confirmation `C2` was answered `DENY` could still have a
sibling orphan `C1` answered `ALLOW`, and if `C2`'s skip transition had not yet
applied (the #257 window, where the step is still `AWAITING_APPROVAL`) the `ALLOW`
would execute the very action the user just refused. So when the binding is
concrete: once *any* confirmation for it is resolved, the binding is decided, and
no second resolution — of that confirmation or a sibling — can be recorded. One
step, one answer. When it is not concrete, only ADR-0036 §2's per-confirmation
rule applies, so a `(None, None)` "binding" never makes two independent direct
confirmations mutually exclusive.

`StepRunner.resume`'s `_check_parked` guard is not removed — it still refuses a
step not `AWAITING_APPROVAL` in the stored execution, which fails *before*
anything is authored and is the cheaper rejection. The invariant is the durable
floor beneath it: `_check_parked` reasons about live execution state, the
invariant about the records in hand, and the by-binding query (§3) reads the same
per-binding fact this rule enforces.

### 3. `AuditTrail.pending_confirmation` — recovering the parked question (#242)

Add one query to the `AuditTrail` Protocol:

```python
async def pending_confirmation(
    self, *, execution_id: str, step_id: str
) -> PermissionDecision | None:
    """The confirmation this binding still awaits, or None.

    None when the binding carries no CONFIRM, or when any CONFIRM for it is
    already resolved (the binding is decided). Otherwise the newest unresolved
    CONFIRM, by decided_at then id.
    """
```

A restarted process reads the reloaded step, sees it is `AWAITING_APPROVAL`, and
asks the trail for the confirmation that step is waiting on — by the binding §1
and §2 established, not by an id it no longer has. `resume` then proceeds exactly
as it does today, including `_check_parked`'s existing check that the returned
confirmation's `tool` equals the reloaded step's `bound_tool`.

**A binding is *pending* only while it carries no resolution at all, and the
query keys on that — not on any single confirmation's state.** A binding can hold
more than one unresolved `CONFIRM`: ADR-0037 §2 *accepts* a `CONFIRM` recorded for
a `run` that then loses the `PENDING → AWAITING_APPROVAL` compare-and-swap ("an
audit trail with an entry for an action that did not happen is strictly better"),
so two racing `run` calls each record a `CONFIRM` before either transition
commits, and the CAS loser's `CONFIRM` stays in the trail, unresolved. So the
query works in two steps, in this order:

1. **If any `CONFIRM` for `(execution_id, step_id)` is already resolved, return
   `None`.** By §2(b) the binding is decided and no further resolution may be
   recorded — the pipeline should not present it as answerable. This is the case
   an earlier draft got wrong by falling back to a sibling orphan.
2. **Otherwise return the newest unresolved `CONFIRM`** by the trail's own order
   (`decided_at` descending, `id` ascending). None exists → `None` (nothing is
   parked). One or more exist and none is resolved → they are the same action
   (selection is deterministic and single-candidate, ADR-0037 §1), so any is a
   correct question to re-present; the newest is returned deterministically, and
   `_check_parked` then confirms it is bound to the reloaded step's `bound_tool`
   before anything is authored.

The order matters: step 1 before step 2 is exactly the "a binding with any
recorded resolution is non-pending" rule the review that shaped this asked for.
The query does not raise on multiple unresolved `CONFIRM`s, because that is a
reachable, accepted state (ADR-0037 §2), not a corrupt one.

The method is **query-only and returns a detached snapshot**, like every other
`AuditTrail` read (ADR-0018 §3): it adds no write path and no way to mutate the
trail, so the append-only, single-resolution guarantees are untouched.

**This keeps the fact where the record is.** The confirmation *is* a
`PermissionDecision` in the trail; asking the trail to find it by its binding is
the honest shape (ADR-0037 §4 called it exactly that). The alternative — copying
the id onto the step — puts half of one fact in `planning`'s execution state and
half in `permissions`' trail, two stores that can then disagree (§Alternatives).

### 4. #243's lifetime is enforced in `orchestration`, not here

For completeness of the cluster: expiring a stale confirmation needs no field
added by this ADR. `PermissionDecision.decided_at` already says when the question
was asked, `StepRunner` already holds an injected, guarded clock, and ADR-0036 §1
already ratified that staleness "is `orchestration`'s to enforce". So `resume`
gains a rule that refuses an answer arriving past a configured lifetime, with the
lifetime a `StepRunner` construction parameter (a deployment's setting, defaulting
to "no expiry", exactly as `ThresholdActionPolicy`'s thresholds are the
deployment's and default to unremarkable). That is a within-contract change and
ships on its own branch; this ADR records only that #243 does **not** wait on the
contract change here, so the two do not block each other.

## Alternatives considered

- **Carry the id on the step (`approval_ref` on `→ AWAITING_APPROVAL`).**
  ADR-0037 §4 named this as #242's other candidate: widen the transition and
  store the confirmation id on the `AWAITING_APPROVAL` `StepExecution`. Rejected
  on three counts. It **conflates the question with the clearance**:
  `approval_ref` means "the decision that *cleared* this step" and a parked step
  is undecided, so reusing the field breaks its meaning and a new field
  duplicates state the trail already holds. It **spreads one fact across two
  stores** — `planning`'s execution state and `permissions`' trail — which can
  then drift, the failure ADR-0014 §3 keeps execution state clear of the ruling's
  content to avoid. And it **touches `planning/` as well as `core/types.py`** (the
  `StepExecution` validator that forbids `approval_ref` here, `StepTransition`,
  and `PlanExecution._to_awaiting_approval`), a wider blast radius than the query,
  for a fact the trail can already answer once #253 gives it the key.

- **Leave `execution_id` out of `authorises`** (keeping it a resolution-invariant
  concern only). This was the first draft's choice and it is **rejected** (§1): it
  leaves cross-execution substitutability open at the execution seam, where A's
  resolved or auto-granted ALLOW authorises B's identical step. `authorises` is
  the binding the executor checks, so the fourth conjunct belongs there.

- **Forbid concurrent executions of one plan (`PlanStore.start_execution`).**
  #253's own stated alternative: if a plan may not have two live executions, two
  parked-on-the-same-step executions cannot exist. Rejected as the wrong layer
  and too broad — concurrent executions of one plan are a legitimate `planning`
  capability (`active_executions` exists to resume several), and forbidding them
  to fix a permissions-binding gap would foreclose that to remove a case the
  binding closes directly. It is also a `planning` contract change, no cheaper
  than this one and further from where the gap actually is.

- **A `PendingConfirmation` type in `core`.** ADR-0037 §4 already rejected
  carrying the parked state as a new `core` model: `AWAITING_APPROVAL` plus the
  trail hold every fact, and the missing piece is a *query*, not a new record.

- **Put #243's deadline on the record (a `core` field).** Rejected for #243 in §4
  — the deadline is a policy the deployment sets, not a fact the record carries,
  and enforcing it needs a clock the record has no business holding (ADR-0036 §1).
  Keeping it out of this ADR is also what lets #243 ship without waiting on the
  contract.

## Consequences

- **The confirmation record gains an execution binding, enforced at three
  seams.** #253's residual substitutability closes on every path: A's decision can
  no longer *execute* B's identical step (`execution_id` in `authorises`, §1),
  nor be *claimed* against B's state (the executor's `call.request.execution_id
  == state.id` conjunct, §1), nor be *recorded* as B's resolution (§2a). This is
  a `core/types.py` change (`ActionRequest`, `PermissionDecision.from_request`
  and `authorises`), a guard added in `orchestration/executor.py`, and two
  additions to the resolution invariant — the `execution_id` conjunct (§2a) and,
  **only for a concrete `(execution_id, step_id)` binding**, a per-binding
  single-resolution rule (§2b) layered on top of ADR-0036 §2's unchanged
  per-confirmation `resolves` index. How `SqliteAuditTrail` enforces the added
  rule — a partial index or a checked read inside the existing `record`
  transaction — is the triad PR's to settle.
- **This decision depends on a `planning` contract change and cannot be
  implemented alone (§1).** The recovery binding is sound only if
  `PlanStore.start_execution` guarantees execution-id non-reuse (or a durable
  incarnation id) — and because the store, not the composition root, mints the
  id, that guarantee must be ratified in `planning`, not merely assumed. So the
  ADR-0044 cluster is **two** contract PRs, not one: the `planning` non-reuse
  guarantee lands with or ahead of the `permissions`/`core` triad, and the
  dispatcher sequences them. Tracked in the follow-up issue.
- **A parked confirmation survives a restart.** #242 closes: a reloaded
  `AWAITING_APPROVAL` step is resumable by asking the trail for its pending
  confirmation, no caller-carried id required. `StepRunner.resume` can drop its
  reliance on a caller-supplied `confirmation_id` for the restart path (the
  in-process path may keep it as an optimisation, or route through the query
  uniformly — an implementation choice for the triad PR).
- **The #257 state is made *safe* here, but not *recovered*.** ADR-0037's
  recoverable gap — a resolving `ALLOW`/`DENY` recorded whose transition never
  committed, leaving the step `AWAITING_APPROVAL` with its binding already
  *resolved* — is out of scope to *recover*, but §2(b) and §3 make it no longer
  *dangerous*: the per-binding rule forbids a second resolution, so a step stuck
  in that window cannot be re-answered the other way, and `pending_confirmation`
  returns `None` on it (step 1) rather than handing back a sibling orphan to
  resolve. An earlier draft claimed this query "gives #257 a handle" and that a
  sibling orphan could be returned; both were wrong — the first is withdrawn, the
  second was the review's blocker and is fixed. Recovering #257 (re-applying the
  unapplied transition, or reading the confirmation *with* its resolution) still
  needs a mechanism this ADR does not provide; the execution binding (§1) is a
  prerequisite any such recovery will want. This ADR closes only #242 and #253.
- **This lands as a triad, after this ADR merges.** The `AuditTrail` Protocol
  change requires its conformance suite extended, `FakeAuditTrail` updated, and
  `SqliteAuditTrail` implementing `pending_confirmation` — one unit of work under
  golden rule 5's stage 2. The `execution_id` field and the invariant conjunct
  ride in the same implementation PR, since they are the key that query needs.
- **It collides on the contract surface.** `core/types.py` and
  `core/protocols.py` are the two highest-collision files, and `core/types.py`
  work was in flight when this was written (ADR-0039). The dispatcher sequences
  the implementation PR behind whatever holds `core/types.py`, per
  CONTRIBUTING's "two agents needing `core/` at once are not independent".
- **#243 is unblocked, not blocked.** Its lifetime rule needs nothing here, so it
  ships in parallel on its own branch.
- **Revisit when** standing grants (ADR-0021 §6) make `decide` answer from a
  stored authorisation — an execution-scoped grant would read the same binding —
  or when #257's recovery procedure is designed against the query this adds.
