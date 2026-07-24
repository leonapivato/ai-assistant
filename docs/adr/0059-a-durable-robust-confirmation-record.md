# 59. A durable, robust confirmation record: a lifetime deadline, resolution recovery, and the legacy park narrowed

- Status: Proposed
- Date: 2026-07-24
- **This is a contract change.** It adds a field to `PermissionDecision` in
  `core/types.py` (with a matching parameter on `PermissionDecision.from_request`
  and a validator), and adds one query method to the `AuditTrail` Protocol in
  `core/protocols.py`. Golden rule 5 therefore governs it: **the contract must be
  ratified — this ADR must be flipped to `Accepted` (it stands `Proposed` on this
  PR) — and merged as its own PR before anything implements against it**. The
  implementation lands later as a triad — the extended `AuditTrail` conformance
  suite, the updated `FakeAuditTrail`, and `SqliteAuditTrail` (with a nullable-
  column migration) — one unit of work, plus the within-contract `orchestration`
  changes that consume the new field and query. `core/types.py` and
  `core/protocols.py` are the two highest-collision files in the repository, so
  the dispatcher sequences the implementation wave against other `core/` work
  (CONTRIBUTING's "two agents needing `core/` at once are not independent").
- **Status is `Proposed` on this PR, deliberately, and is the gate — not the
  authorisation — for the triad.** This ADR proposes the contract surface for a
  design question earlier ADRs deferred (ADR-0037 §4, ADR-0044); it does not
  implement it, and while it stands `Proposed` it does **not** authorise the
  implementation. Golden rule 5's ratified-before-implementation ordering is
  satisfied by the flip to `Accepted` that ratifies this surface (the review-then-
  ratify step CONTRIBUTING's "Contract ADRs land before their implementation"
  describes); only then may the triad land. So no triad implements against a
  merely-`Proposed` contract — ratification is the explicit intervening gate. The
  surface is stated precisely enough to review and ratify, and precise enough that
  the triad has no open design fork to settle beyond the storage mechanics each ADR
  already leaves to its implementer.

## Context

Three open issues are facets of one design question the confirmation ADRs
deferred to a `core` change: **what a durably-parked confirmation record must
carry, and what queries the trail must answer over it, so a parked step is
robustly bounded in time and always recoverable.** A fourth, #287, is already
closed (ADR-0052) but names the same design frame, and #308 ties itself to it
explicitly.

### The parked-confirmation machinery today

`StepRunner` (ADR-0037 §4) parks a step by recording a `CONFIRM`
`PermissionDecision`, committing the step `PENDING → AWAITING_APPROVAL` carrying
`bound_tool`, and returning `AWAITING_CONFIRMATION`. `resume` later takes a
human answer, calls `ActionPolicy.resolve`, records a **resolving** decision
whose `resolves` names the confirmation, and drives the step to its disposition
(`ALLOW → claim/execute`; `DENY → SKIPPED`). ADR-0044 bound the confirmation to
its execution (`execution_id` on `ActionRequest`/`PermissionDecision`, a fourth
conjunct of `authorises`, an execution conjunct in the resolution invariant, and
a per-`(execution_id, step_id)`-binding single-resolution rule), and added
`AuditTrail.pending_confirmation(execution_id, step_id)` so a restarted process
recovers the *unresolved* `CONFIRM` from the trail without the decision id it no
longer holds. ADR-0052 wired that into the `Engine` façade: it enumerates
`plans.active_executions()`, recovers each parked `CONFIRM` by binding, and
re-mints a continuation — re-deriving the reference from durable state rather
than storing one.

### The three gaps this ADR settles

- **#277 — the confirmation lifetime is a best-effort wall-clock bound, not
  robust to clock correction or restart.** `StepRunner._check_fresh` (the opt-in
  lifetime shipped in #274 for #243) computes `age = _now() - decided_at` over
  two wall-clock readings (ADR-0026) and refuses an answer past
  `confirmation_ttl`. A backward clock correction can carry `_now()` behind
  `decided_at`, making `age` negative and an expired question answerable again;
  and because the bound is *recomputed at answer time* rather than fixed when the
  question was asked, "stale is unanswerable" does not hold across a correction.
  The failure direction is safe (a real approval honoured late, never an action
  without one — the single-resolution index still binds one approval to one
  resolution), which is why #274 shipped it as best-effort. A lifetime robust to
  correction and restart needs the **deadline fixed on the durable record**, not
  a difference of two live readings. ADR-0037 §4 and ADR-0044 §Alternatives named
  this "deadline-on-the-record" shape as the deferred `core` change; the
  `_check_fresh` docstring points here.

- **#257 — a recorded ruling can outlive the transition that should have applied
  it.** ADR-0037 §2 records the `PermissionDecision` *before* any transition
  commits, `PlanStore` offers no multi-step transaction, and `AuditTrail.record`
  makes a resolution single-use. So on the `resume` path a failure or
  cancellation between "the resolution is durable" and "the step's disposition is
  durable" strands the step `AWAITING_APPROVAL` with its ruling recorded but
  unapplied — a resolved `ALLOW` whose claim never committed, or a resolved
  `DENY` whose skip never committed. `resume` cannot retry, because the binding
  is already resolved (ADR-0044 §2b) and re-authoring is refused. **Nothing has
  acted** in either window — no tool is reached — so unlike a stranded `RUNNING`
  (which recovery reads as `INDETERMINATE`, ADR-0014 §4) no side effect is in
  doubt; the state is durable and every fact needed to finish it is in the trail.
  What is missing is a way *back to it*: a query that returns the resolution the
  binding already carries, so the stranded step can be driven to the disposition
  already decided. ADR-0044 made this state **safe** (§2b forbids a second,
  opposite resolution; `pending_confirmation` returns `None` on it) but explicitly
  **did not recover** it. The recovery it named as a prerequisite is the by-binding
  resolution lookup below.

- **#308 — a pre-ADR-0044 confirmation parked across the upgrade boundary is not
  restart-recoverable by binding.** A `CONFIRM` written before ADR-0044 has
  `execution_id = NULL` (`SqliteAuditTrail._migrate` correctly leaves it NULL —
  a non-concrete binding §2b never constrains). If a step was already
  `AWAITING_APPROVAL` at the upgrade instant, then after a restart
  `pending_confirmation(execution_id=state.id, step_id)` requires a non-NULL
  execution match, gets `None`, and the step is recoverable only via the
  in-process path — the pre-#242 situation. #308 rules out the two obvious fixes:
  **loosening the query** to match NULL-execution `CONFIRM`s by `step_id` alone
  reintroduces the cross-execution substitutability #253 closed; **an
  `approval_ref` on the `AWAITING_APPROVAL` step** is the alternative ADR-0044
  §Alternatives explicitly rejected. #308 places the fix with #287: a durable,
  safe reference should cover the legacy-upgrade edge and cross-process re-entry
  together, scoped single-user local-first (ADR-0002) and to the narrow
  upgrade-instant window.

- **#287 — a durably-parked step unresumable via the façade — is closed
  (ADR-0052)** by *re-deriving* the continuation from durable state
  (`active_executions()` + `pending_confirmation()`), chosen over encoding
  durable identity into the token. It is context here because #308 is the one
  binding ADR-0052's re-derivation cannot reach — the pre-0044 record whose
  binding is incomplete.

## Decision

We will make the durable confirmation record carry an explicit **expiry
deadline**, and add one **resolution-recovery query** to `AuditTrail`, closing
#277 and #257 as contract changes. For #308 we settle the *design*, not a fourth
contract field: ADR-0044's `execution_id`-in-`authorises` rule makes a
NULL-execution confirmation unexecutable in a concrete execution, so no record
field or query loosening can safely bind a legacy park — and neither can the
"re-decide the step" shortcut. So #308 is **narrowed and conservatively
refused**, not auto-recovered: the two queries route a *trail-unanswerable* park
(both return `None` — a legacy park, but also a cleared-trail or missing-audit
one, which the trail cannot tell apart) to refusal rather than re-present or
re-decide it, and its active recovery is deferred with the exact hazards that
constrain it recorded.

### 1. `expires_at` on `PermissionDecision` — the lifetime fixed on the record (#277)

Add one optional field to `PermissionDecision`:

```python
expires_at: UtcInstant | None = Field(
    default=None,
    description=(
        "The instant past which this CONFIRM is no longer answerable, fixed "
        "when the question was asked (ADR-0059 §1). None for a decision with no "
        "lifetime — every non-CONFIRM decision, and a CONFIRM parked by a "
        "deployment that set no confirmation lifetime."
    ),
)
```

and a construction parameter on the one construction path:

```python
@classmethod
def from_request(
    cls,
    request: ActionRequest,
    ruling: PermissionRuling,
    *,
    id: Identifier,
    decided_at: datetime,
    resolves: Identifier | None = None,
    expires_at: datetime | None = None,   # NEW — the caller-supplied deadline
) -> PermissionDecision: ...
```

**The record carries a fact, not a policy — which is what reconciles this with
ADR-0044 §Alternatives' rejection of "put #243's deadline on the record".** That
rejection stands *for the best-effort within-contract lifetime* #274 shipped:
that lifetime needed no durable state, so keeping the deadline out of `core` is
what let #243 ship without waiting on a contract change. #277 is its robust
successor, and the reasons ADR-0044 gave against a `core` field do not hold for
it:

- *"The deadline is a policy the deployment sets, not a fact the record carries."*
  What is stored is not the policy — it is the **deadline instant derived from the
  policy at ask time**, `decided_at + confirmation_ttl`, computed once and frozen.
  The *policy* (the duration, and whether any lifetime applies at all) stays the
  deployment's `StepRunner` construction parameter, exactly as `confirmation_ttl`
  is today. Snapshotting the derived instant is the same move `decided_at` already
  makes: a clock-derived fact, stored so the record is self-describing across a
  restart. A confirmation asked under a one-hour lifetime *is a question that
  expires at a specific instant*, and that instant is a property of the question,
  not of the deployment reading it back.
- *"Enforcing it needs a clock the record has no business holding."* Enforcement
  stays in `orchestration`: `StepRunner._check_fresh` keeps its injected, guarded
  clock (ADR-0026) and becomes the single comparison
  `confirmed.expires_at is not None and self._now() > confirmed.expires_at`.
  **`expires_at is None` means the confirmation has no lifetime — it does not
  expire** (a deployment that set no `confirmation_ttl`, so no deadline was
  computed). There is deliberately **no answer-time recompute**: nothing recovers
  a duration the record does not carry, which is what keeps `None` unambiguous
  (see the migration note in §Consequences for the one behavioural consequence, a
  bounded upgrade-window limitation). The `>` is deliberate and specified:
  `expires_at` is the **last answerable instant**, so a question is refused
  *strictly after* it — matching the shipped `age > confirmation_ttl` (which
  accepts at exactly the ttl) and ADR-0044's "equal timestamps are fine … a fast
  confirmation at a coarse clock resolution is real". The record holds only a
  passive instant and never reads a clock. ADR-0036 §1's "staleness is
  `orchestration`'s to enforce" is unchanged; what moves into `core` is the
  *anchor* the enforcement compares against, not the enforcement.

**What this closes — the restart half of #277 — and what it deliberately does
not.** The bound is no longer a difference of two live wall-clock readings; it is
one reading compared against a deadline fixed at ask time and made durable. Be
precise about which of #277's two failures that fixes:

- *Across a restart* the anchor **persists**, and this is the half a `core` change
  can actually fix. `expires_at` survives in the trail and is **not recomputed**,
  so "past its lifetime is unanswerable" is preserved across a restart *under a
  clock that is not rewound* — the durable-persistence property #277 says the
  recomputed bound lacks. The qualifier matters: a restart *combined with* a
  backward correction that lands `_now()` before the deadline still re-opens the
  question, and that is the correction caveat below, not a restart guarantee. What
  the field buys is that the deadline is not *lost or re-derived* by the restart
  itself.
- *Across a clock correction* it is **no better than the subtraction, and the ADR
  does not claim otherwise.** Because `expires_at == decided_at + ttl`, the
  comparison `_now() > expires_at` and the subtraction `_now() - decided_at > ttl`
  re-open on the *identical* condition (`_now() < decided_at + ttl`), so any
  backward correction that carries `_now()` back across the deadline — of any
  size, not merely a large one — makes an expired confirmation answerable again,
  exactly as today. The deadline moves the fragility from a *recompute* to a
  *stored anchor*, which is what restart-stability needs; it does not move
  wall-clock to monotonic time, which is what correction-immunity would need. That
  immunity needs a **monotonic** component, and a monotonic reading
  (`time.monotonic`) is defined only within one process/boot and resets across the
  restart this field must survive — so it cannot *be* the durable anchor. It is
  therefore **not** a record field (Alternatives), and correction-immunity is
  **deferred**: a deployment that wants it layers a process-local monotonic check
  in `orchestration` on top of the durable deadline. The failure direction remains
  the safe one ADR-0044 relied on — a genuine approval honoured late, never an
  action without one — which is why #277 shipped the wall-clock bound in the first
  place and why deferring the correction half is tolerable.

**Validation.** `expires_at`, when set, must be strictly after `decided_at` (a
deadline at or before the ask instant would expire the question the moment it is
recorded — a `ValueError` at construction, the same shape as `confirmation_ttl`'s
strictly-positive check). And a `model_validator` permits `expires_at` **only on
a `CONFIRM`** — a lifetime is a property of an open question, and a resolving
`ALLOW`/`DENY` or a direct grant carries none, the same "only the coherent
outcome may carry this" shape `PermissionRuling` uses for `authorised_by`. The
field is serialisable by construction (a `UtcInstant`), which the
`PermissionDecision` round-trip obligation (ADR-0021 §4) already requires of every
field. It is a caller-supplied `from_request` parameter — like `decided_at` and
`resolves`, not transcribed from the request — because the deadline is the
*recorder's* concern (`StepRunner`'s deployment lifetime), not a fact the policy
authored; this keeps the policy clock-free (ADR-0036 §1, ADR-0021 §3).

**The recorder computes the deadline under bounded arithmetic, with a single
specified outcome.** `StepRunner` forms `expires_at = decided_at + confirmation_ttl`
only when a `confirmation_ttl` is configured, and both operands reach the edge of
representability — `UtcInstant` admits an aware `datetime.max`, and
`confirmation_ttl` admits any strictly-positive `timedelta` — so a clock reading
near `datetime.max` makes the sum raise a bare `OverflowError`, which is neither an
`AssistantError` nor a specified refusal. The recorder guards it with **one**
outcome, not a choice: a deadline that is **not representable** is recorded as
`expires_at` unset (`None`) — i.e. treated exactly as "no lifetime", the same as a
no-`confirmation_ttl` deployment. There is no answer-time recompute to overflow
either, because there is none at all (above). This is the safe direction — a
question that would have expired only at the end of representable time is, for
every practical purpose, one that does not expire — and it keeps `None` a single
meaning ("no lifetime") rather than reintroducing a duration the record does not
hold. Specifying it here is what makes the triad *test* the boundary rather than
*discover* the crash.

`authorises` does **not** read `expires_at`. `authorises` is a pure comparison of
what a decision is *about* — tool, digest, step, execution (ADR-0016 §2, ADR-0044
§1) — and expiry is a time-varying question the resuming stage owns, not an
intrinsic of the two records. Reading a clock inside `authorises` would break
exactly the "same answer for every consumer, independent of clock" property
ADR-0016 §2 requires of it.

**The test floor for the field** the implementation wave must carry, so an
implementation cannot keep the old recompute while passing: a configured
`confirmation_ttl` is **captured as `expires_at` at ask time** and the recorded
`CONFIRM` carries the deadline (not the duration); `_check_fresh` **accepts at
exactly `expires_at`** and **refuses strictly after** it (the `>` boundary); the
deadline **survives a restart and a `confirmation_ttl` config change without
recomputation** (a new record keeps its stored deadline; a legacy `NULL` record
reads as no lifetime — the migration case); and construction **rejects**
`expires_at <= decided_at` and `expires_at` on a non-`CONFIRM` decision, and an
unrepresentable ask-time deadline is recorded as `None` (no lifetime), not raised.

### 2. `AuditTrail.resolution_of` — recovering the applied ruling for a parked step (#257)

Add one query to the `AuditTrail` Protocol, the mirror of `pending_confirmation`:

```python
async def resolution_of(
    self, *, execution_id: str, step_id: str
) -> PermissionDecision | None:
    """The recorded resolution of this binding's confirmation, or None.

    The complement of ``pending_confirmation``. Where that method answers "what
    unresolved CONFIRM does this binding still await?", this answers "what
    resolution has this binding already received?" — the ALLOW or DENY whose
    ``resolves`` names a CONFIRM of the concrete ``(execution_id, step_id)``
    binding (ADR-0044 §2). It exists so a step stranded ``AWAITING_APPROVAL``
    with its ruling durable but its disposition transition uncommitted (#257) can
    be driven to the disposition already decided — idempotently, authoring
    nothing new — rather than re-authored, which the single-resolution rule
    (§2b) refuses.

    Returns None **only for a successful read of a binding that carries no
    resolution** (it is genuinely pending — ``pending_confirmation`` answers it —
    or carries no confirmation at all); None never stands in for a failure to
    read. By §2b a concrete binding carries at most one resolution, so when a
    resolution exists it is unique and this returns it. Query-only and returns a
    detached snapshot, like every other ``AuditTrail`` read (ADR-0018 §3).

    Raises:
        AuditError: If the trail cannot be read (a closed or corrupt store, an
            I/O error). This is the same boundary ``pending_confirmation`` draws,
            and it is load-bearing: a read failure returned as None would let
            recovery classify a still-resolved step as trail-unanswerable and
            route it to cancellation, discarding a durable ruling. The cause is
            preserved.
    """
```

**`resolution_of` promises an `ALLOW` or a `DENY`, and no new invariant is needed
to make that true — the existing model invariant already guarantees it.**
`PermissionDecision._a_resolution_is_not_itself_a_question`
(`core/types.py`) rejects, at model construction, any decision with `resolves` set
whose own ruling is `CONFIRM` ("a resolving decision may not itself be a
`CONFIRM`"). A resolving decision is therefore an `ALLOW` or a `DENY` before it can
ever reach `AuditTrail.record`, so a resolving-`CONFIRM` can never occupy the
binding's sole resolution slot (§2b) and `resolution_of` cannot return one. The
two-branch replay (§ above) is total on that guarantee, which already holds — this
ADR relies on it rather than adding a redundant `record` conjunct, and the case is
tested where the invariant lives (model construction), not at a record boundary it
cannot reach. What the ADR's *own* new query does require of the conformance suite,
for `resolution_of` in both the fake and `SqliteAuditTrail`, is coverage to the
same standard `pending_confirmation` already carries — not merely the two failure
cases. At least: **an `ALLOW` resolution and a `DENY` resolution are both returned**
(not only `ALLOW`); **`None` for a pending or unparked binding** (no resolution, or
no confirmation); **binding isolation** — a resolution under `(E, s)` is not
returned for `(E', s)` or `(E, s')`, the same execution/step key `record`'s §2a
conjunct enforces, so recovery can never replay another execution's ruling;
**a resolution of a *sibling* `CONFIRM`** under the binding is found (§2b makes the
binding, not a single confirmation, the unit); the **detachment** case — mutate the
returned decision's reachable data, re-read, assert unchanged (ADR-0018 §3); and the
**`AuditError`-on-unreadable-trail** case. The list is the floor the implementer
extends, not a ceiling.

**Why the binding, not the confirmation id.** `resume` on the restart path no
longer holds the confirmation id (that is the whole of #242), so the recovery key
must be the durable binding ADR-0044 established, exactly as `pending_confirmation`
uses it. Together the two queries partition **what the trail records** for a
concrete binding — they are trail observations, not statements about the step's
state, which lives in the `PlanStore`: `pending_confirmation` non-`None` → the
trail holds an askable question; `resolution_of` non-`None` → the trail holds a
decision, possibly unapplied; **both `None` → the trail holds neither *for this
concrete `(execution_id, step_id)` binding***. That last case does not mean the
trail is empty of related records — a pre-0044 `CONFIRM` and its resolution can
sit in the trail with `execution_id = NULL`, invisible to a concrete-binding query
(§3) — nor that "nothing is parked": a step the `PlanStore` still reports
`AWAITING_APPROVAL` while the trail answers both `None` is a *live* park the trail
cannot speak to (a cleared trail, a legacy row, §3), which §3 routes to
refusal-to-present — the enumerator combines the trail observation *with* the
`PlanStore` step state, and never reads two `None`s as "skip, nothing here". A
by-`resolves` form keyed on a confirmation id is derivable but redundant — the
in-process caller
that still holds the id already holds the disposition it returned, and the
restart caller does not have the id — so the contract carries the binding form
only.

**What it provides, and what it does not.** `resolution_of` is the *missing
capability* #257 named — a way to **find** the recorded resolution for a parked
binding. It does not by itself close #257 end to end; closing it needs a recovery
*operation* that consumes the query, and that operation — its entry point, budget,
result contract, and admission-slot handling — is a within-contract
`orchestration`/façade change of a later wave (or a follow-up that revises
ADR-0052), **not** delivered or fully specified by this contract ADR. What the
query makes possible, and what that later operation will do, is: on a reloaded
`AWAITING_APPROVAL` step for which `pending_confirmation` returns `None` (the
binding is resolved), ask `resolution_of`; if it returns an `ALLOW`, re-drive
claim/execute (the first action on this step — #257 establishes nothing has acted,
so this is safe and not a re-execution); if a `DENY`, re-drive
`AWAITING_APPROVAL → SKIPPED`. Each
transition is the compare-and-swap the original attempt failed to commit, so the
replay does not double-apply — but idempotence here is **by reconciliation, not
by the CAS being a literal no-op**: a concurrent recovery worker or a repeat that
loses the swap observes the store's stale-version rejection
(`StaleExecutionError`, or an illegal-transition error after a re-read), which the
replay must reconcile by re-reading the step and treating **the disposition
transition as already made** — the step is no longer `AWAITING_APPROVAL` — so its
own replay is *not needed* rather than *failed*. What the replay must **not** do
is read that as "the action completed": for a `DENY` the target `SKIPPED` is
terminal and the reconciliation ends there, but for an `ALLOW` a step observed
`RUNNING` proves only that the claim committed, not that the tool finished, so the
step's ultimate fate is left to the normal execution recovery — `SUCCEEDED` if it
completed, `INDETERMINATE` if it stranded mid-run (ADR-0014 §4), never asserted as
success by the replay. The implementation wave owns that retry/re-read
reconciliation and its concurrency tests; the ADR requires only that an
already-advanced disposition is not re-driven and not surfaced as a replay
failure.

**The `ALLOW` replay executes a tool, so it needs an execution budget — supplied
by the *action-capable* path that drives it, never by the query-only enumerator.**
`StepExecutor.execute` requires a strictly-positive per-attempt timeout (ADR-0029
§4). The replay therefore runs where a budget already exists or is explicitly
supplied: on `resume`, which already takes a caller `timeout` (ADR-0042 §4), or on
a distinct recovery operation that carries a **configured recovery execution
budget** — a construction parameter of that operation, same shape and ownership as
`resume`'s `timeout` and `confirmation_ttl`, defaulting to the deployment's ordinary
per-attempt budget. It is **not** driven from `Engine.pending_confirmations`, whose
query-only signature carries no budget and must stay side-effect-free (ADR-0052, §3
below). A `DENY` replay needs no budget (it only commits `→ SKIPPED`). Defining that
operation, its budget and its result contract is the within-contract
`orchestration`/façade work of the implementation wave (or a follow-up that revises
ADR-0052 deliberately), with restart-recovery tests for both an `ALLOW` (executes
under the budget) and a `DENY` (skips); this ADR adds only the query that makes the
stranded resolution *findable*.

This is the `resume`-path strand (resolved `ALLOW`/`DENY`) #257's live cases
describe; the `run`-path `DENY` window #257 also lists is already closed by
ADR-0037 §5's single-commit denial over ADR-0041's direct edge, and needs no query.
The transition-replay logic itself is a within-contract `orchestration` change in
the implementation wave; this ADR adds only the query that makes it reachable.

### 3. The legacy park (#308) is conservatively refused, not auto-recovered

We add **no** field and **no** query for #308, and we do not adopt either fix it
forbids — nor a third "re-decide the step" shortcut that a first draft of this
ADR proposed and that does not survive scrutiny (below). The reason a durable
*reference* cannot close #308 is a wall ADR-0044 already built: a NULL-execution
confirmation cannot be safely resolved *in a concrete execution* at all, so any
scheme that let one be resolved would violate the very property #253 closed.

**The wall.** ADR-0044 §1 made `execution_id` a conjunct of `authorises`, and §2a
requires a resolution's `execution_id` to equal its confirmation's. A legacy
`CONFIRM` has `execution_id = NULL`; a resolution of it must therefore also carry
`execution_id = NULL`; and `authorises(request)` for a reloaded step in execution
`E` — whose request carries `execution_id = E.id` — then returns `False`
(`E.id ≠ None`). The executor's own guard `call.request.execution_id == state.id`
(ADR-0044 §1) rejects it identically. So even if a legacy `CONFIRM` were handed
back, resolving-and-executing it for `E` is impossible without *rebinding* it to
`E` — and every way of rebinding it is unsafe or forbidden:

- **Loosen `pending_confirmation` to match NULL by `step_id`** would let one
  execution answer under a `CONFIRM` that could belong to another execution of
  the same plan — the cross-execution substitutability #253 closed. Rejected by
  #308 and here.
- **Carry the confirmation id on the `AWAITING_APPROVAL` step (`approval_ref`)**
  is the ADR-0044 §Alternatives rejection: it conflates the question with the
  clearance and spreads one fact across two stores. Rejected by #308 and here.
- **Backfill `execution_id` onto the legacy record** is impossible twice over:
  the `AuditTrail` is append-only and write-once ("nobody may tear out a page" —
  §protocols), so mutating a recorded decision is forbidden; and the information
  is not recoverable anyway — a migration that could not know the execution at
  upgrade time (which is *why* `_migrate` left it NULL) cannot know it later.

**Re-deciding the step in its own execution does not work either, and the two
reasons are worth recording because they constrain any future recovery.** The
tempting move — since a reloaded `AWAITING_APPROVAL` step looks undecided, run
the permission check for it again in `E`, minting a fresh `E`-bound `CONFIRM`
(the ADR-0052 "re-derive from durable state" spirit) — is **unsound**:

- *A legacy park is not necessarily undecided.* #257 crossed with #308 is
  reachable: before the upgrade a user answered, a legacy resolution `R` was
  recorded (`resolves` naming legacy `CONFIRM C`, both `execution_id = NULL`),
  and the `→ SKIPPED`/claim transition then crashed, leaving the step
  `AWAITING_APPROVAL`. After the restart *both* concrete-binding queries return
  `None` for `(E.id, step_id)` — `R` and `C` carry `NULL`, not `E.id`, so
  `resolution_of(E.id, step_id)` cannot see `R` — and ADR-0044 §2b's per-binding
  single-resolution rule does **not** fire, because the legacy binding
  `(NULL, step_id)` is not concrete. A re-decide would then record a fresh bound
  `ALLOW` and execute an action the user had already declined. The claim that an
  `AWAITING_APPROVAL` step is necessarily undecided is false for a legacy park.
- *A re-decide can mint an unresumable `CONFIRM`.* The parked step carries
  `bound_tool` (an `Identifier`), and `StepRunner._check_parked` refuses any
  confirmation whose `tool.id` is not equal to it (`runner.py`). Re-running
  capability selection may return a different tool than the one the step is
  parked on (a registry that moved `smtp-v1 → smtp-v2` under selection), so the
  fresh `CONFIRM` would bind a tool the step can never accept — parked forever.
  A re-decide would have to re-permission the step's *own* `bound_tool` rather
  than re-select, and even then needs the current registry to still serve that
  declaration — neither guaranteed. This is not the normal `run` path (which
  acts on `PENDING`, and refuses to run an `AWAITING_APPROVAL` step before a
  decision is recorded); it is a new, unspecified re-park operation.

**So this ADR does not auto-recover a legacy park; it folds it into a *trail-
unanswerable* bucket the recovery enumerator conservatively refuses.** The two
queries do **not** single out a legacy park: a step `AWAITING_APPROVAL` for which
`pending_confirmation(E.id, step_id)` and `resolution_of(E.id, step_id)` both
return `None` is not *provably* a pre-0044 park. The same two-`None` signature is
produced by an ordinary post-0059 concrete park whose trail rows were legitimately
erased — `AuditTrail.clear()` is a data-rights operation (ADR-0004 §6) a user may
run while a plan is still `AWAITING_APPROVAL` — and by any other missing-audit
state. No query the trail can offer distinguishes "legacy NULL binding" from
"binding whose rows were cleared" from provenance alone, and this ADR does not
pretend one can: it would need a provenance the append-only trail does not carry.

The point is that it does not need to, because the **safe action is identical for
all of them**. Two consumers use the queries, and keeping them apart is what keeps
this ADR from silently re-defining ADR-0052:

- **Enumeration stays query-only; how it presents an *expired* park is an
  ADR-0052 question this ADR does not settle.** `pending_confirmations` *lists*
  confirmations and mutates nothing, and that query-only nature is untouched here.
  But `expires_at` introduces a state ADR-0052's enumeration predates — a durably
  parked `CONFIRM` that is *past its deadline*, i.e. surfaced by
  `pending_confirmation` yet unanswerable by `resume._check_fresh` (§1). ADR-0052
  pulls two ways on it: its anti-stranding rule says *surface every parked step*,
  while its "confirmations a user may still answer" framing says *don't present a
  dud*, and its `Confirmation` DTO carries no expired/stale flag to do both. This
  ADR deliberately does **not** pick — excluding expired parks, or surfacing them
  flagged as expired via a DTO field, is a **deliberate ADR-0052 revision** the
  consuming wave must make, and this ADR does not claim ADR-0052 is unchanged *in
  this respect*. What it does fix is upstream of that choice: the deadline is on
  the record and enforced at `resume` (§1), so *whichever* presentation ADR-0052
  adopts, an expired park is never answered. What enumeration unambiguously omits —
  no ADR-0052 tension — is a *stranded-resolved* binding (`resolution_of`
  non-`None`, already decided) and a *trail-unanswerable* one (both queries
  `None`); neither carries an answerable `CONFIRM` for ADR-0052 to surface.
- **Replay and reconciliation are the action-capable *resume/recovery* path, and
  are separately budgeted.** Driving a stranded-resolved binding to its decided
  disposition (§2), and reconciling a stale token against a concurrently-resolved
  binding, execute and mutate plan state, so they belong to `resume` — which
  already carries a caller/deployment execution budget (§2, ADR-0042 §4) — or to a
  distinct, explicitly-budgeted recovery operation, **never** to
  `pending_confirmations`. If the façade needs to *drive* (not merely list)
  recovery of a stranded binding, that is a new budgeted façade method with its own
  result contract, defined by the implementation wave or a follow-up that revises
  ADR-0052 deliberately — not a behaviour folded into enumeration. This ADR adds
  only the query that makes the stranded resolution *findable*; it does not add or
  redefine an execution entry point.

Beyond that decoupling, this ADR does **not** specify the recovery/reconciliation
mechanism, and deliberately so — it is orchestration/ADR-0052 territory, and
pinning its branch table here would only duplicate (and risk contradicting) the
actual `StepRunner._confirmation_for`, `Engine._resume`, and `_parked`-table code
paths the consuming wave owns. What this ADR fixes are the **properties** that
mechanism must have, each discharged by the contract it adds rather than by prose:

- *One clock, so freshness is decided the same way wherever it is checked.*
  Freshness is `StepRunner`'s single predicate (§1: `expires_at is None`, or
  `now <= expires_at`); any consumer that needs a fresh/stale verdict takes it from
  `StepRunner`, never a clock of its own, and the composition-root single-instance
  obligation ADR-0052 §1 draws for the shared `AuditTrail` extends to the `Clock`.
- *Every stale, expired, or concurrently-resolved token is made **decidable from
  durable state** — the reconciliation that acts on it is the consuming wave's, not
  this ADR's.* This ADR does not promise a particular outcome or slot-cleanup; it
  supplies the query that makes one *reachable*. Concretely: when a second caller
  wins the binding and the loser's `record(resolves=id)` raises
  `InvalidResolutionError` (or a recovered `resume` finds `pending_confirmation`
  now `None`), `resolution_of` returns the winning ruling, so the loser *can* be
  reconciled — replay the already-applied disposition or refuse the stale token —
  rather than left with a bare error; when it returns `None` the binding is
  trail-unanswerable; when it raises `AuditError` the trail is unreadable. Turning
  those observations into a caught branch, a returned outcome, and a released
  `max_outstanding_confirmations` slot — and testing the interleaving — is the
  consuming wave's reconciliation to build (§ decoupling above). The contract's job
  is only that the winning ruling is *findable*, which `resolution_of` discharges.

Designing the branches, entry points, budgets, eviction, and their
clear-after-issue / expiry / interleaving tests against the real code is the
consuming wave's; this ADR's claim is only that `resolution_of` and `expires_at`
make all of them *buildable and safe*, not that it builds them.

A trail-unanswerable park is not listed, an expired one is refused at answer
(however ADR-0052 chooses to present it, above), and **neither is ever
auto-answered or re-decided** — that refusal-to-*act* is the whole of what this ADR
delivers for it. **Durable *reclamation* of a
permanently-parked step — cancelling it so it stops being rediscovered — is
explicitly out of scope and deferred.** No
contract exposes it today: `PlanStore` offers only a single-step
`commit_transition` and `Engine` no cancellation entry point, so a step left
`AWAITING_APPROVAL` with an unanswerable question stays active and is re-surfaced
(harmlessly, as unpresented) on each recovery pass until a future plan-level
cancellation sweep clears it. The `_check_fresh` docstring already names that sweep
as a separate concern, and this ADR keeps it separate rather than inventing a
cancellation path it has no room to design or test. What this ADR *does*
guarantee is that such a park is never presented as resumable and never
mis-resolved — the safety property — not that it is promptly reclaimed.

A legacy park in particular has **no** safe resume at all: not re-decide (unsound,
above), and not an in-process resume by a retained id, which fails too — `resume`
rebuilds the request with `execution_id = state.id` (runner.py) and records a
resolution carrying it, so `record`'s §2a conjunct (resolution execution equals
confirmation execution) rejects it against a legacy `CONFIRM`'s `NULL` execution
with `InvalidResolutionError`. #308's own "resumable via the in-process path"
predates that conjunct and does not survive it. So a legacy park is simply left
unpresented until the deferred sweep, within the "transient, narrow window …
single-user local-first" #308 scopes as tolerable. Conservative refusal is correct
for *every* member of the bucket: the legacy case because both re-deciding and the
retained-id resume are unsound (above), the cleared case because there is no
recorded question left to answer safely, and any missing-audit case because acting
without the audit record is precisely what the permission layer refuses.

**#308 is therefore narrowed and made safe here, not closed.** It needs
**nothing** from this ADR's contract surface beyond the two queries that let the
enumerator route a trail-unanswerable park to refusal rather than re-present it.
Actively *recovering* a legacy park — a guarded re-park that re-permissions the
step's own `bound_tool` and fires only once the binding is *proven*, from a
provenance the trail does not yet carry, to carry no resolution — is a separate
design constrained by exactly the two hazards above,
and is deferred to a follow-up (§Consequences).

### 4. Deferrals this resolves

- **ADR-0037 §4 and ADR-0044 §Alternatives'** deferral of the
  "deadline-on-the-record" lifetime → resolved by §1 (`expires_at`), which closes
  the **restart** half of #277 (the best-effort bound #274 shipped for #243 was
  restart-fragile); the **clock-correction** half stays deferred, because its fix
  is a monotonic anchor that cannot be durable (§1, Alternatives).
- **ADR-0044's** "recovering #257 still needs a mechanism this ADR does not
  provide; the execution binding is a prerequisite" → the *contract* half is
  provided by §2 (`resolution_of`), the by-binding lookup #257 named, built on the
  binding ADR-0044 added. The recovery *operation* that consumes it is a later
  orchestration wave (§2), so #257 is *unblocked*, not closed here.
- **The #287 family** (#287 closed by ADR-0052; #308 open) → §3 records why no
  durable reference can safely close #308 (the `execution_id`-in-`authorises`
  wall), narrows it to a conservatively-refused trail-unanswerable state, and
  rejects the two fixes #308 forbids plus the re-decide shortcut. #308 stays open,
  but safe.

## Alternatives considered

- **A monotonic anchor field on the record (#277's "or a monotonic anchor").**
  Rejected as a *field*: `time.monotonic` is defined only within a process/boot
  and resets across the restart the durable lifetime must survive, so it cannot
  be the durable anchor. The durable half is the absolute deadline (§1); a
  within-process monotonic refinement for correction-immunity is an
  `orchestration` layer on top, not a contract field.
- **Keep the lifetime a recomputed wall-clock bound (leave it in
  `orchestration`).** This is the #274 status quo and #277 is precisely the case
  that it is not robust — negative `age` on a backward correction, no property
  across restart. The robust version needs the deadline durable, which is a
  `core` change by construction.
- **Put the deadline on the record as a `timedelta` (the duration) rather than an
  instant.** Then the answer-time check still recomputes `decided_at + ttl` vs
  `_now()` — no better than today across a correction, and it stores the policy
  (the duration) rather than the fact (the deadline), the shape ADR-0044 rightly
  refused. The instant is the fact; store the instant.
- **A by-`resolves(confirmation_id)` query for #257** instead of the by-binding
  `resolution_of`. Redundant: the caller that holds a confirmation id is
  in-process and already holds the disposition; the restart caller has no id.
  The binding form serves both and mirrors `pending_confirmation`.
- **Loosen `pending_confirmation` for #308** (match NULL by `step_id`). Rejected
  — reintroduces #253's cross-execution substitutability. (#308's forbidden fix.)
- **`approval_ref` on the `AWAITING_APPROVAL` step for #308.** Rejected — the
  ADR-0044 §Alternatives rejection (conflates question with clearance, splits one
  fact across two stores). (#308's forbidden fix.)
- **Backfill `execution_id` onto legacy records.** Rejected — forbidden by the
  append-only trail, and the execution is unknowable after the fact.
- **A `PendingConfirmation`/`ParkedStep` type in `core`.** ADR-0037 §4 and
  ADR-0044 already rejected carrying parked state as a new `core` model:
  `AWAITING_APPROVAL` plus the trail hold every fact, and the missing pieces are a
  *field* and *queries*, not a new record.

## Consequences

- **The confirmation record becomes self-describing about its lifetime.** A
  parked `CONFIRM` carries `expires_at`, so its "still answerable?" is a single
  durable comparison whose anchor persists across a restart (§1, under a
  non-rewound clock) — the restart half of #277. `StepRunner._check_fresh` becomes
  `expires_at is not None and _now() > expires_at`, with **no answer-time
  recompute**: `None` means "no lifetime", uniformly. The `confirmation_ttl`
  construction parameter stays, now used at *ask* time to compute the deadline for
  new records rather than at *answer* time to recompute it — so a new record's
  lifetime in force is the one promised when the question was asked, the more
  defensible semantics, and it survives a later config change. It does **not**
  improve clock-correction robustness (§1): the correction half of #277 stays
  deferred to an optional process-local monotonic layer, since a monotonic anchor
  cannot be durable.
- **Legacy confirmations parked across the upgrade lose their best-effort
  staleness bound — a bounded, stated migration limitation, not a silent strip.**
  A confirmation parked before this ADR has `expires_at = NULL` (the migration adds
  the column `NULL`, §migration), and since `None` means "no lifetime" with no
  recompute, such a confirmation is answerable regardless of the pre-0059
  best-effort `confirmation_ttl` bound it would once have been checked against.
  This is deliberate: the alternative — recomputing against the *live*
  `confirmation_ttl` for `NULL` records — would make `None` mean two contradictory
  things at once ("this new confirmation is explicitly unbounded" *vs* "this legacy
  row needs the live ttl"), since a new no-`confirmation_ttl` deployment also
  records `None`. Rather than carry a second durable bit to tell those apart for a
  transient population, this ADR accepts the loss, which is (a) confined to
  confirmations parked *before* the 0059 upgrade and answered after — the same
  narrow upgrade-instant window #308 scopes — (b) in the safe direction (a genuine
  approval honoured late, never an action without one), and (c) stated here rather
  than silent. Only records parked *after* this ADR carry a deadline. A deployment
  that cannot tolerate even that window drains parked confirmations before
  upgrading.
- **The #257 stranded-resolution state becomes *recoverable in principle* — the
  query it lacked now exists.** ADR-0044 made it safe (no opposite re-resolution)
  but not recoverable; `resolution_of` (§2) supplies the by-binding lookup that
  makes the stranded resolution *findable*, which was the missing capability. The
  recovery *operation* that finds and replays it — its entry point, budget, result
  contract, and admission-slot handling — is a within-contract `orchestration`
  change of a later wave, not delivered by this contract ADR; so #257 is unblocked
  here, and closed there.
- **The legacy-upgrade park (#308) is narrowed and conservatively refused, not
  closed.** The ADR-0044 `execution_id`-in-`authorises` wall makes any "durable
  safe reference" to a NULL-execution confirmation unresolvable in a concrete
  execution, and re-deciding the step is unsound (it can overturn a crashed
  legacy resolution, and can mint a `bound_tool`-mismatched `CONFIRM` that
  `_check_parked` rejects forever). The two queries cannot single out a legacy
  park — a cleared trail (ADR-0004 §6 `clear()`) or any missing-audit state under
  a live park gives the same two-`None` signature — so §3 leaves a legacy park
  *unlisted* (enumeration omits a both-`None` binding) and **never** auto-answered
  or re-decided; the retained-id in-process path fails too (a legacy resolution
  trips `record`'s §2a execution conjunct, §3). **Durable reclamation of such a
  park (a plan-level cancellation sweep) is explicitly out of scope and deferred**
  — no contract exposes cancellation today (`PlanStore` has only single-step
  `commit_transition`, `Engine` no cancellation op), so the step stays active until
  that sweep exists.
  Active recovery — a guarded re-park that re-permissions the step's own
  `bound_tool` and fires only once the binding is proven, from a provenance the
  trail does not yet carry, to hold no resolution — is likewise a deferred
  follow-up, constrained by those hazards. **Follow-up issues to file: the
  cancellation/reclamation sweep, and the guarded re-park.**
- **This is a contract change and lands in stages (golden rule 5).** This ADR is
  reviewed at `Proposed`, then ratified — flipped to `Accepted` — and merged as
  its own contract-only PR ahead of the implementation; nothing is built against
  it while it is merely `Proposed` (header). The implementation follows as a triad
  — the extended
  `AuditTrail` conformance suite, `FakeAuditTrail`, and `SqliteAuditTrail`
  implementing `resolution_of` — together with the `PermissionDecision` field and
  its validator, and the within-contract `orchestration` changes (`_check_fresh`
  reads `expires_at`; `resume` replays a `resolution_of` result to finish a #257
  strand; the enumerator uses both queries to route a *trail-unanswerable* park to
  refusal — never re-decide). `SqliteAuditTrail` gains a **nullable `expires_at`
  column**;
  the migration adds it defaulting `NULL`, the same shape the ADR-0044
  `execution_id` migration used. A `NULL` deadline means **"no lifetime"** — the
  single, uniform meaning `_check_fresh` reads (above) — so a legacy row parked
  across the upgrade is answerable regardless of its old best-effort bound, the
  bounded migration limitation stated two bullets up. `resolution_of` adds no
  schema (it reads). How the column and the query are indexed is the triad's to
  settle, as ADR-0044 left its own to its triad.
- **One ADR settles the contract surface; it does not by itself *close* the
  behaviours the surface enables.** #277 (a field) and #257 (a query) are the
  genuine `core` *additions* this ADR delivers. But only #277's **restart** half is
  actually closed here (the durable deadline); its correction half is deferred, and
  #257 is *unblocked* — the query it lacked now exists — while its end-to-end
  recovery is the consuming orchestration wave's, not this ADR's. #287 is already
  closed (ADR-0052). #308 is **not** closed: this ADR narrows it to a
  conservatively-refused trail-unanswerable state and rejects every unsafe fix
  (its two, plus the re-decide shortcut), but its active recovery is deferred — so
  #308 shares this ADR's *design frame* without adding to its *surface*. The honest
  summary: this ADR delivers **two contract additions** and closes **one and a
  half** behaviours; the rest is unblocked-and-deferred, by design for a
  contract-surface proposal. Splitting #277 and #257
  into two ADRs was considered and rejected: they are the same record read at the
  two ends of a park's life (asked, then decided), share the binding key and the
  "keep the fact where the record is" discipline, and neither is large; one
  decision keeps the pair coherent. #308 earns its place in the same ADR because
  its wall is only visible *once the field and the query are decided together* —
  folding it in is what lets this ADR reject its forbidden fixes and the
  re-decide shortcut with a reason rather than a citation.
- **It collides on the contract surface.** `core/types.py` and
  `core/protocols.py` are the highest-collision files; the dispatcher sequences
  the implementation wave against other `core/` work.
- **Revisit when** standing grants (ADR-0021 §6) let `decide` answer from a
  stored authorisation (an execution-scoped grant would want the same binding and
  perhaps the same deadline); if a deployment needs correction-immune expiry
  strong enough to justify a process-local monotonic layer over the durable
  deadline; or when #308's active recovery is designed (the guarded re-park §3
  and the consequences above constrain it).
```
