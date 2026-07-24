# 58. An executor does not police an authority the trail never held

- Status: Accepted
- Date: 2026-07-24

## Context

`StepExecutor` is exported from `ai_assistant.orchestration` and its
`execute` accepts any valid `ToolCall` (issue #259). A `ToolCall` is valid when
its `decision.authorises(request)` holds, and `authorises` compares a
`PermissionDecision` to an `ActionRequest` — tool, parameters digest, step id
and, since ADR-0044 §1, execution id. It asks nothing about *provenance*: it
does not ask whether the decision it is comparing was ever recorded in the
`AuditTrail`.

So a caller can hand-build an `ALLOW` `PermissionDecision` with a fresh
`Identifier` that no trail ever held, construct a valid `ToolCall` around it,
invoke `StepExecutor.execute` directly, and have the executor pin
`approval_ref = call.decision.id` onto the claimed step (`executor.py`,
`_claim`). The step's `approval_ref` is then a foreign key into the audit trail
that resolves to nothing — exactly the "silent, automatic action that cannot be
correlated with its authorisation" that ADR-0014 §4 requires `approval_ref` to
make impossible, and that ADR-0004 §7's gate-and-record rule exists to prevent.

This ADR does not implement anything. It **decides whether that gap is closed or
accepted**, and records the decision so #259 can be resolved either way rather
than left open indefinitely.

### What is and is not already closed

The gap is a property of the *type*, not of the *pipeline path*. ADR-0037 §3
established that no execution *through the pipeline* can rest on an unrecorded
authority: `StepRunner` is the only thing in the pipeline that constructs a
`ToolCall`, and it constructs one only from a `PermissionDecision` it has read
back out of the `AuditTrail`, with an identity check on the way back. ADR-0037
§3 stated the residue in its own words and handed it to this issue:

> `StepExecutor` is exported and takes any valid `ToolCall` … A caller that
> hand-builds an `ALLOW` `PermissionDecision` with an id nobody recorded can
> therefore construct a valid call, hand it to the executor, and have that id
> committed as `approval_ref`. This change does not close that … Issue #259
> carries it, and §3's guarantee should be read as scoped to the pipeline until
> it lands.

So the only thing #259 leaves open is a caller that **bypasses the pipeline** to
drive the exported executor with a call it built by hand. The recovery paths do
not: ADR-0044 §3's restart recovery re-reaches a parked step through
`StepRunner.resume`, which loads the confirmation from the trail
(`pending_confirmation`) and rebuilds the call from the trail's own copy before
handing it on — the same read-back that closes the pipeline path in the first
place.

### The executor as it actually stands (2026-07-24)

`StepExecutor` has evolved since #259 was filed, and the decision must account
for the current module, not the one the issue described:

- It is constructed from **four** injected collaborators — `plans`, `registry`,
  `invoker`, `now` (`executor.py`, `__init__`). It holds no `AuditTrail`.
- Its **pre-claim path already reads the registry**: after
  `_checked_timeout`, `_detached`, the `step_id` guard and ADR-0044 §1's
  `execution_id` guard, it calls `await self._registry.get(...)` *before*
  `_claim`. A trail-presence check has a natural home there — a missing record
  would be refused before the claim, costing no durable state, exactly as the
  two existing pre-claim guards do.
- ADR-0051's returned-result revalidation (#311) and ADR-0044 §1's execution-id
  binding (#307) have both landed since #259; the module is more heavily guarded
  and more heavily composed than when the issue was written, which raises, not
  lowers, the cost of a fifth collaborator and a new construction contract.

### The two forces

**Accept the residue.** ADR-0021 §1 already ruled on the identical shape one
level down — a caller hand-constructing a `PermissionDecision` field by field:

> that is a caller falsifying its own audit trail, not a policy subverting a
> gate, and no producer can prevent it.

The party that can reach `StepExecutor.execute` directly and hand it a call it
built by hand is, under ADR-0002's single-user local-first architecture, the
assistant's *own* orchestration code (or a test, or a direct embedder) — the
principal the permission layer makes **transparent**, not an adversary it
**gates**. ADR-0004 §7 assigns the audit trail the job of "making the
assistant's behaviour transparent and reviewable"; it is a transparency record
of what the assistant did, not a defence of the user's process against itself. A
caller that drives the executor with an unrecorded decision is choosing to write
a false entry in its own transparency log — the same falsification ADR-0021 §1
holds a producer's contract cannot meaningfully police, because the falsifier is
the principal.

**Fix it.** The executor *is* a chokepoint, unlike a bare `core` type — so
unlike ADR-0021 §1's case, a check here is technically possible for a caller
using the composed executor, and ADR-0037 §3 named the shape: "validate trail
presence before its claim." The placement exists (the pre-claim registry read),
and ADR-0014 §4 states the invariant plainly — `approval_ref` is "a *reference*
to the permission subsystem's durable decision", a foreign key, and a foreign
key that resolves to nothing is a broken one. Closing the gap would make trail
presence an invariant of the module rather than a property of the one pipeline
path.

The fix's cost is the counterweight, and it is the cost ADR-0037 §3 already
priced when it rejected the same shape as an executor concern:

- a **fifth injected collaborator** (`AuditTrail`) and a change to the
  executor's **construction contract**, touching every composition root and
  every test that builds a `StepExecutor`;
- a **new failure mode on a module that merged after sixteen review rounds** and
  has since taken on ADR-0044 §1 and ADR-0051 guards;
- a **golden-rule-5 contract change**: the executor's construction surface is
  part of how `orchestration` is wired, so ratifying it belongs in a Proposed
  ADR ahead of any implementation;
- a **mandatory trail read on every re-drive, including recovery**. The trail is
  durable (ADR-0004 §7, a Tier 1 store), so a decision that predates a restart
  is still present and the check would *not* wrongly reject a legitimate
  recovery on staleness grounds — but it would convert "the trail is transiently
  unavailable or a row failed to validate" into "a legitimately-authorised,
  already-recorded, mid-recovery step cannot be claimed", a new liveness failure
  on precisely the recovery path ADR-0044 works to keep drivable. On the pipeline
  recovery path it is worse than costly, it is redundant: `StepRunner.resume`
  has *just* read the same confirmation out of the trail before building the
  call.

## Decision

**We accept the residue. `StepExecutor` does not validate trail presence, and
#259 is resolved as WONTFIX.** We do not add an `AuditTrail` collaborator to the
executor, and its four-collaborator construction contract stands.

The governing reason is ADR-0021 §1, applied one level up. The caller that
reaches the exported executor and hands it a hand-built, unrecorded
`PermissionDecision` is not defeating a gate — under ADR-0002's single-user
local-first model there is no second party in the process for the gate to defend
the user against. It is the principal ADR-0004 §7's audit trail exists to make
transparent, choosing to falsify its own transparency record. A producer's
contract cannot meaningfully prevent the principal from lying about itself:
ADR-0021 §1 settled that this class of "falsifying its own audit trail" is
accepted residue, and the executor case is the same class.

That the executor is a *chokepoint* where ADR-0021 §1's "no producer can prevent
it" does not strictly hold — a check here *would* bind a caller using the
composed executor — does not change the decision. It sharpens it: the question
stops being "can we?" and becomes "should we, given the threat model and the
cost?", and the answer is no. The pipeline path #259 actually protects is
already closed by ADR-0037 §3's read-back; the confirmation-recovery path is
closed the same way through `StepRunner.resume` (ADR-0044 §3). What remains is a
threat outside ADR-0002's declared model, and closing it would spend a
contract-surface construction change, a fifth collaborator on a
sixteen-round-hardened module, and a redundant trail read (with a new liveness
failure) on every recovery re-drive — defence-in-depth against the principal
itself, which even when landed does not make the authority unforgeable against a
principal that also controls the injected trail and the durable store beneath
it.

`StepExecutor`'s own guarantee is unchanged and is the one that matters: it pins
`approval_ref = call.decision.id`, so the id it commits is the id it was handed
(ADR-0037 §3). The pipeline guarantees that id came from the trail; the residue
is that a caller stepping outside the pipeline can hand it one that did not, and
that caller is the party the trail records rather than an adversary it stops.

### Rejected alternative: the pre-claim trail-presence check

Inject `AuditTrail` as a fifth collaborator and, on the pre-claim path where the
registry is already read, refuse a `ToolCall` whose `decision.id` the trail does
not resolve to an equal record — the shape ADR-0037 §3 described and the
narrower cousin of #107's "resolve `approval_ref` in the executor" that ADR-0037
§3 also rejected. Rejected here for the reasons above: it is a golden-rule-5
construction-contract change touching every composition and test, adds a failure
mode to a heavily-guarded module, imposes a mandatory — and on the pipeline
recovery path redundant — trail read on every re-drive with a new recovery
liveness failure, and buys defence-in-depth against the single-user principal
that ADR-0002 and ADR-0004 §7 place inside the trust boundary rather than an
adversary outside it. Had we recommended it, this ADR would be **Proposed** and
would merge alone ahead of the implementation (golden rule 5); we do not, so it
is **Accepted** and closes #259.

Note that this rejection is scoped to the *unconditional executor-level check*.
ADR-0021 §6's standing-grant revisit, or a future multi-principal deployment
that steps outside ADR-0002's single-user assumption, would change the threat
model and reopen the question on its own terms (below).

## Consequences

- **#259 is closed WONTFIX**, with this ADR as the recorded rationale. The
  residue is documented as accepted, not forgotten: an `approval_ref` on a step
  the *pipeline* claimed still resolves to a recorded decision by construction
  (ADR-0037 §3, ADR-0044 §3), and only a caller that bypasses the pipeline can
  produce one that does not.
- **`StepExecutor`'s construction contract is unchanged** — four collaborators,
  no `AuditTrail`. Every existing composition root and test stands, and the
  module keeps the guard surface it hardened over ADR-0037, ADR-0044 §1 and
  ADR-0051 without a new failure mode.
- **The type/path distinction ADR-0037 §3 drew is now ratified as intentional**,
  not a deferred bug: `ToolCall` validity is a subject-and-authority check, not a
  provenance check, and provenance is a property the pipeline supplies rather
  than one the type or the executor enforces.
- **This decision is scoped to ADR-0002's single-user local-first model.** It
  should be revisited when that assumption changes — a multi-principal or
  multi-tenant deployment where the caller of the executor is no longer
  identical to the principal the trail records would move this threat inside the
  model and could justify the rejected check. ADR-0021 §6's standing grants,
  which would have `decide` answer from a stored authorisation, are the other
  trigger: a grant read from durable state changes what "recorded" means at the
  seam.
- **No contract, protocol, or code changes here.** This ADR touches only
  `docs/adr/`; being Accepted, it merges on its own without gating any
  implementation.
