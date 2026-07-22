# 37. Joining selection, the permission check and execution

- Status: Accepted
- Date: 2026-07-22
- **Not a contract change.** No Protocol is added or altered, no `core` type
  moves, and `core/config.py` is untouched. Every contract this needs —
  `ToolRegistry`, `ActionPolicy`, `AuditTrail`, `PlanStore`, `ToolInvoker` — was
  ratified by ADR-0016, ADR-0021, ADR-0014 and ADR-0029. Golden rule 5's
  separate-PR requirement therefore does not apply and this ADR merges with the
  implementation it authorises.
- **No ratified text changes here.** Everything below chooses among options the
  contracts left open, or records that an option is *not* being chosen.

## Context

`CLAUDE.md` names the pipeline `orchestration` owns: intent → context assembly →
memory retrieval → planning → **tool selection → permission check → execute** →
learn. `LearningLoop.respond` runs the first four stages and returns an
`ActionPlan`. `StepExecutor.execute` runs the last one, given an authorised
`ToolCall`. Nothing turned a `PlanStep` into that call.

Every piece needed to do so had landed within a day of this change:
`ToolRegistry.find(capability)` answers which tools advertise a capability;
`ThresholdActionPolicy.decide` returns a `PermissionRuling`;
`PermissionDecision.from_request` binds that ruling to the request; and
`SqliteAuditTrail.record` appends it. What was missing is the object that runs
them in an order, and the order is the whole decision — ADR-0014 §4 constrains
when a step may be claimed, ADR-0021 §3 deliberately left the recording of a
decision to the caller, and issue #107 records the cost of that.

Three questions the ratified contracts decline to settle land here, and one they
do settle is worth restating because it does most of the work.

## Decision

We will ship `StepRunner` in `orchestration/`, the stage between the planner and
the executor. Given an `ExecutionState` and a `PlanStep` it selects a tool, rules
on it, records the decision, and either hands `StepExecutor` an authorised call
or disposes of the step without running it. It returns a `StepDisposition`
saying which of those happened.

### 1. Selection is defined for exactly one candidate, and this ADR invents no ranking

`ToolRegistry.find` returns *every* tool advertising a capability, ordered by
`id`. ADR-0016 §5 is explicit that the ordering is by `id` "because some total
order must be specified", that "ordering by risk would be the beginning of
ranking, and callers would come to depend on it", and that **the registry does
not choose**. ADR-0016 §7 defers "ranking and selection" to "the selection stage
in `orchestration`, informed by `permissions`" — which is this object.

So the question is genuinely ours, and the answer is: **we do not answer it
here.** `StepRunner` runs a step when `find` returns exactly one candidate. Three
cases, three dispositions:

| `find` returns | Disposition | Durable effect |
| --- | --- | --- |
| nothing | `NO_CAPABLE_TOOL` | `PENDING → SKIPPED`, `skip_reason=NO_CAPABLE_TOOL` |
| one tool | the permission check decides (§2) | see §2 |
| several | `AMBIGUOUS_CAPABILITY` | **none** — the step stays `PENDING` |

The empty case is ADR-0014's, reserved for exactly this and taken as written.

**The several-candidates case is a refusal, not a tie-break, and the refusal is
the point.** Taking `candidates[0]` is the obvious implementation and it is a
ranking rule in disguise: `find`'s order is by `id`, `id` is a name, and a rule
that picks by name would silently prefer `a_deleter` over `b_archiver` for the
same capability — choosing between two side-effecting actions on an alphabetical
accident, and then being depended upon, which is precisely what ADR-0016 §5
declined to let the registry do. Doing it one layer up does not make it a
decision; it makes it an undocumented one. ADR-0016 §7 says the trade-off
involves "how risk, cost and latency trade off", and none of those is settled.

**The step is left `PENDING` rather than skipped, deliberately.** No `SkipReason`
is true of it: `NO_CAPABLE_TOOL` is a lie when two tools are capable,
`UNMET_DEPENDENCY` and `SUPERSEDED` describe other things, and writing a
falsehood into durable state to make a return value tidier is the failure
ADR-0014 §4's `_LEGAL_SKIP_REASONS` table exists to prevent. `PENDING` is
already the truth — nothing has happened to this step — and it is the state a
real selection rule, or a user asked to choose, can still run it from. The
disposition is what tells the caller, and it is terminal for *this* turn only.

**Rejected: a `select` hook or an injected ranker.** Handing the choice to a
caller-supplied callable would ship the extension point instead of the decision,
and ADR-0036 §1 already made the argument against injectable predicates in the
adjacent seam — a knob whose values are not all safe is a guarantee given away.
The selection rule is issue #241; when it exists it is a rule, not a parameter.

**Rejected: validating `step.parameters` against `tool.parameters_schema`.**
ADR-0016 §7 defers it explicitly, pending a JSON Schema runtime dependency. The
parameters flow into the `ActionRequest` unvalidated, exactly as they flow into
the plan; a tool that dislikes them fails at the seam with a `ToolResult`, which
is a supported outcome.

### 2. The order is decide → record → read back → claim, and every branch records

The permission stage's ordering is fixed at both ends and this ADR fixes the
middle.

At one end, **ADR-0014 §4 refuses `→ RUNNING` without an `approval_ref`** and
requires the claim to be committed before the tool is invoked; ADR-0029 §8
restates it. So a decision must exist, and have an id, before anything is
claimed.

At the other, **ADR-0021 §3 makes the policy a pure function**: it returns a
`PermissionRuling` and the caller mints the id, reads the clock, constructs the
`PermissionDecision` and records it. That is deliberate — a policy recording its
own rulings would put half the trail in `permissions`, since a `CONFIRM` is
answered long after `decide` returns — and issue #107 records the accepted cost:
nothing mechanically forces the decision to reach the trail.

**The step itself is read from the plan, not accepted from the caller.** Both
entry points take a `step_id` and load the `PlanStep` from
`PlanStore.get_plan(state.plan_id)`. A `PlanStep` parameter would let a caller
hand over one sharing the planned step's id and naming a different capability or
different arguments: the gate would rule on *that* action and the executor would
run it, while the `ActionPlan` the execution belongs to went on recording an
action nobody performed. Nothing downstream notices, because `PlanStore` accepts
a transition by step id and version. Naming the step removes the substitution
rather than checking for it — the same move ADR-0021 §3 made when it took the
subject out of `PermissionRuling`, "removing the capability rather than
forbidding it". The step is still detached on the way out, because `PlanStore` —
unlike `MemoryStore`, `ToolRegistry` and `AuditTrail` — contracts no snapshot,
and this stage holds the value across four awaits.

`StepRunner` therefore runs, for a single candidate:

1. build the `ActionRequest` from the tool, the step's parameters and the step id;
2. `policy.decide(request)`;
3. `PermissionDecision.from_request(...)` with an id from the injected factory
   and a `decided_at` from the injected clock;
4. `trail.record(decision)` — **before any transition is committed, on every
   branch, including `DENY`**;
5. then, and only then, dispose of the step per the ruling.

**Recording precedes the claim rather than following it**, and the alternative is
worth naming because it is cheaper. Claiming first and recording after would let
a step be durably `RUNNING`, and a tool be running with it, while the trail says
nothing was ever approved — the exact hole #107 describes, made larger by the
fact that the failure window contains a live side effect. Recording first costs
a trail entry for a call that then fails to be claimed (a lost CAS race), and an
audit trail with an entry for an action that did not happen is strictly better
than an action with no entry: ADR-0004 §7 asks for reviewability, and the
over-recording direction is reviewable while the other is not.

**A `DENY` is recorded too.** ADR-0004 §7 gates every side-effecting call and
says nothing about only recording the permitted ones; a refusal the user is never
shown a trace of is the half of the trail that answers "what did the assistant
decline to do", and the step's `approval_ref` needs something to point at (§3).

### 3. The authority handed to the executor is the trail's copy, which closes #107

Issue #107 says nothing forces a decision to actually be recorded, and that
closing it "needs the invocation contract — the executor is the place that has
both the `approval_ref` and a reason to look it up". The contract has landed and
the executor does not look anything up: `StepExecutor` takes an authorised
`ToolCall` and pins `approval_ref = call.decision.id`.

**We close it one stage earlier, structurally, and without touching the
executor.** `StepRunner` is the only thing in the pipeline that constructs a
`ToolCall`, and it constructs one **only from a `PermissionDecision` it has read
back out of the `AuditTrail`**:

```text
record(decision) -> id
get(id)          -> the trail's own copy, whose own `id` must equal `id`
ToolCall(request=request, decision=that copy)
```

**The identity check on the way back is load-bearing, not tidiness.** `get` is
contracted to answer the decision *with* that id, and a store keys the row and
serialises the record separately (ADR-0036 §2) — so a row keyed `d-1` whose
stored JSON carries `id="d-2"` round-trips and validates. Nothing downstream
would catch it: `authorises` compares the subject and not the id, the `ToolCall`
constructs, and the executor commits `approval_ref="d-2"` — an id that need not
be a key in the trail at all. That is exactly the property this section claims,
failing silently one field away from where it is established. The same swap on
the resolution path would point `resolves` at a decision nobody was shown. So the
record must call itself what it was asked for, or it is refused.

The in-memory decision is discarded at that point. The consequence is the
property #107 asks for, by construction rather than by discipline: the
`approval_ref` on a `RUNNING` step is the id of a decision the trail returned,
because the call that produced it was built out of what the trail returned.
There is no execution path that reaches `ToolInvoker.invoke` from an unrecorded
decision, because there is no other constructor of a `ToolCall`.

It is stronger than checking that `record` did not raise, and the difference is
exactly the ambiguity ADR-0036 §2 built the trail to expose. A trail that
accepted the write and lost it answers `None`, and `StepRunner` refuses with
`AuditError` having claimed nothing — the step is untouched and no tool ran. A
trail whose row no longer validates raises `AuditError` from `get` itself
(ADR-0036 §2), which propagates unchanged: "never recorded" and "corrupted" stay
distinguishable, which is what makes refusing on either of them honest.

The round trip is also a real comparison rather than a ceremony. `ToolCall`'s
validator runs `PermissionDecision.authorises`, so a copy that came back with a
different tool, a different parameters digest or a different step cannot become
a call at all. That is translated to `AuditError` — the trail returned something
that is not a record of this request — rather than being allowed out as a
`ValidationError`.

**Rejected: giving `StepExecutor` an `AuditTrail` and having it resolve
`approval_ref`.** This is #107's own suggested shape and it is the more invasive
one. It adds a fifth collaborator and a failure mode to a module that merged
after sixteen review rounds, and it would check *later* than this does — after
the claim, with the step already durably `RUNNING`, so the only available
response to "the decision is not there" is to close a step that should never have
been opened. Verifying before the claim means a missing record costs nothing.
The executor's own guarantee is unchanged and still needed: it pins
`approval_ref` to `call.decision.id`, so the id it commits is the id we read.

**Rejected: minting the decision id from the step id.** A derived id would make
`record`'s write-once check fire on a retry of the same step, and ADR-0021 §4's
duplicate rule is not a de-duplication service. Ids come from the injected
factory, as `LearningLoop`'s goal ids do.

### 4. `CONFIRM` parks the step; the turn never answers on the user's behalf

`ActionPolicy.decide` can return `CONFIRM`, and the answer arrives from a human
long after `decide` returns — ADR-0021 §3 names that asymmetry as its reason for
splitting policy from recording. `StepRunner` has no way to ask: it has no
interface, and `interfaces/` is where a prompt belongs (golden rule 3).

So the turn **stops**, and it stops in a durable state rather than in memory:

- the `CONFIRM` decision is recorded, like every other (§2);
- the step is committed `PENDING → AWAITING_APPROVAL`, carrying `bound_tool`;
- the disposition is `AWAITING_CONFIRMATION` and carries the decision id.

`AWAITING_APPROVAL` "is a durable state rather than an in-memory pause precisely
so a restart preserves it" (ADR-0014 §4), and this is the first thing to put a
step into it. Nothing blocks, nothing sleeps, and no default answer is invented —
a `CONFIRM` auto-resolved to `ALLOW` because nobody could be asked would make the
prompt theatre, which ADR-0021 §3 calls the single worst failure available to
this subsystem.

**Resuming is a second entry point, `StepRunner.resume`, on the same object.** It
takes the recorded confirmation's id and the user's boolean answer, and it is
what makes the parked step reachable rather than merely honest:

1. load the confirmation from the trail; absent → `AuditError`;
2. refuse it if it was not a `CONFIRM`, or if its `step_id` is not this step's —
   `PermissionDeniedError`, before anything is authored;
3. rebuild the `ActionRequest` from the **confirmation's own embedded
   `ToolDefinition`** and the step's parameters;
4. `policy.resolve(confirmed, approved=...)`;
5. record the resolving decision with `resolves` set;
6. `ALLOW` → read back and execute (§3); `DENY` → `AWAITING_APPROVAL → SKIPPED`.

Step 2 checks the *execution* as well as the step, and the reason is that the
transition graph does not. `PlanStore` opens an execution per `start_execution`
call, so one plan may have several, and a `PermissionDecision` carries no
execution id — ADR-0021 §1 binds an approval to the tool, the parameters and the
*step*, and `ActionRequest` has no field for anything wider. A confirmation
parked in execution A, replayed against execution B where the same step is still
`PENDING`, would therefore find `PENDING → RUNNING` perfectly legal: B's step
would run on an answer given about A's, while A stayed parked. Nothing
downstream catches it, because the tool, the digest and the step id all match —
it is the same step of the same plan. So `resume` requires the step to be
`AWAITING_APPROVAL` **in the state it was handed**, bound to the confirmation's
own tool. The residue is named rather than closed: two executions of one plan
*both* parked on the same step are mutually substitutable, and closing that
needs an execution id on the permission record, which is a `core` change with
its own ADR (#253). The trail's single-resolution index bounds it — one
confirmation authorises one resolution — so what is at stake is which of two
identical parked executions proceeds, not whether an unapproved one does.

Step 3 is why the definition is embedded by value at all (ADR-0021 §1, issue
#54): the tool that runs after the confirmation is the declaration the user was
shown, read out of the record, never re-resolved through the registry — which
may have been rebuilt, and whose `id` may since mean something else. Step 5 needs
no check of its own, because `AuditTrail.record` holds both records and enforces
the whole invariant: the request digest must match the confirmation's, so a step
whose parameters changed between the prompt and the answer is refused with
`InvalidResolutionError`, and the unique index on `resolves` (ADR-0036 §2) means
one confirmation authorises one resolution.

**Rejected: a pending-confirmation type in `core`.** Carrying the parked state as
a new `core` model is a contract change with its own ADR and its own PR
(golden rule 5), and it is not needed: `AWAITING_APPROVAL` plus the trail already
hold every fact, and `StepDisposition` is a frozen dataclass in `orchestration`
for `TurnResult`'s reason — it crosses no subsystem boundary.

**Rejected: a confirmation TTL here.** ADR-0036 §1 declined to put one in the
policy and said staleness "is `orchestration`'s to enforce". It is, and it is not
enforced in this change: expiring a prompt needs a policy about how long a
question stands, and inventing one at the moment the answer arrives would refuse
a user's legitimate reply on an unratified rule. Issue #243.

**Known limitation: the `CONFIRM`'s decision id does not survive a restart.**
ADR-0014 §4's `AWAITING_APPROVAL` transition sets `bound_tool` and nothing else,
so a restarted process can see that a step is awaiting an answer and which tool
it is about, but not which recorded decision to resolve. `resume` therefore takes
the id from its caller. Closing it means either widening that transition to carry
`approval_ref` (a `planning` change) or a by-step query on `AuditTrail` (a
contract change); both were outside this change's fence. Issue #242.

### 5. A denial passes through `AWAITING_APPROVAL`, because that is the only truthful path

ADR-0014 §4 permits `SkipReason.APPROVAL_DENIED` **only** from
`AWAITING_APPROVAL` — `_LEGAL_SKIP_REASONS` refuses it from `PENDING`, on the
reasoning that "a step that was never queued for approval cannot have been denied
one". A `DENY` from `decide` arrives while the step is still `PENDING`.

So a denied step is committed twice: `PENDING → AWAITING_APPROVAL` with
`bound_tool`, then `AWAITING_APPROVAL → SKIPPED` with `skip_reason=
APPROVAL_DENIED` and `approval_ref` naming the recorded `DENY`. Two versions,
one disposition.

That reads oddly — the step "awaited" an approval nobody was asked for — and it
is nonetheless the accurate record. What the intermediate state means is *queued
for the permission gate with a specific tool bound*, which is precisely what
happened; the gate then answered without needing a human, exactly as it does for
the automatic `ALLOW` that ADR-0014 §4 insists must still carry an
`approval_ref`. The alternatives are worse in the way that matters: skipping from
`PENDING` as `SUPERSEDED` records a false reason and loses the `approval_ref`
entirely, and widening `_LEGAL_SKIP_REASONS` to admit `APPROVAL_DENIED` from
`PENDING` edits ADR-0014's graph, in another lane's subsystem, to make a record
shorter.

The denial therefore satisfies ADR-0014 §4's own rule for the automatic case: a
decision was recorded and can be pointed at.

## Consequences

- **The pipeline `CLAUDE.md` describes exists end to end.** A plan step now
  reaches a tool, or is disposed of with a durable reason, without anything
  outside `orchestration` being imported concretely: `StepRunner` sees five
  Protocols and one same-package collaborator.
- **Issue #107 closes.** No `ToolCall` in this system can carry an unrecorded
  authority, because the only constructor of one builds it from a decision the
  trail returned. The guarantee is a property of the construction path rather
  than of a check somebody must remember to run.
- **A trail that will not answer stops the pipeline.** `AuditError` from `get`,
  and a missing record, both refuse before the claim. That is a new way for a
  turn to fail, and it fails with nothing claimed and nothing run.
- **Ambiguous capabilities do not execute.** A deployment that registers two
  tools for one capability gets `AMBIGUOUS_CAPABILITY` and a step that stays
  `PENDING`, not a coin flip. This will surface as "my plan did nothing" the
  first time it happens, which is the intended cost of not guessing; issue #241
  is the rule that ends it.
- **`StepExecutor` is unchanged.** Nothing in this change edits it — the module
  that merged after sixteen review rounds keeps its contract, and the new object
  sits in front of it.
- **A parked confirmation needs its id carried by the caller** until #242 lands.
  A restart loses the pointer, and the step sits in `AWAITING_APPROVAL` until it
  is cancelled or the id is recovered from `AuditTrail.recent()` by hand.
- **`StepRunner` does not drive a whole plan.** It disposes of one step. Step
  ordering, dependencies (`UNMET_DEPENDENCY` has no producer yet), cancellation
  and the loop over `ActionPlan.steps` are the next slice, and keeping them out
  is what let this one be about the join.
- **Revisit when** the selection rule lands (#241), when a confirmation acquires
  durable identity (#242) or a lifetime (#243), or when standing grants
  (ADR-0021 §6) make `decide` answer from a stored authorisation.
