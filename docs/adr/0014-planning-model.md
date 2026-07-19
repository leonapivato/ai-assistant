# 14. Planning model: `Goal`, `ActionPlan`, and a separate `ExecutionState`

- Status: Accepted
- Date: 2026-07-19

## Context

The request pipeline (`CLAUDE.md`) runs `intent → context assembly → memory
retrieval → planning → tool selection → permission check → execute → learn`.
The `planning` subsystem owns the fourth step and has no contract today: neither
a `Planner` Protocol nor any of `Goal`, `ActionPlan`, `ExecutionState` exists.
`Goal` and `ActionPlan` are two of the seven first-vertical artifacts
(`docs/roadmap.md`), and `orchestration` cannot be wired until they exist.

Two constraints from [VISION](../../VISION.md) shape this more than anything
else:

- **§7, "Deterministic Systems Own Critical State"** names *state transitions*,
  *retries*, and *execution status* as things deterministic services must
  control. A model may propose what to do; it must not be the thing that decides
  a step succeeded.
- **§3, "Trust Must Be Built Into the Architecture"** means an action the system
  took must be auditable after the fact — which requires knowing both what was
  planned and what actually happened, separately.

The roadmap states the design constraint directly: *separate the static plan
from durable, resumable execution state*. This ADR is mostly about taking that
seriously.

Two boundaries constrain the shape:

- **Planning is not tool selection.** They are distinct pipeline stages. A plan
  says what must be accomplished; selecting *which* tool accomplishes it is a
  later stage that weighs the registry's risk/reversibility metadata.
- **`ToolDefinition` does not exist yet** — it is the next lane (issue #30,
  Lane B). Planning must not depend on the `tools` subsystem's shape, both
  because golden rule 1 forbids the import and because this lane must not block
  on that one.

This adds new `core` types and Protocols, so it is ADR-worthy (golden rule 5).

## Decision

We will model planning as three distinct artifacts — a **goal** (why), a
**frozen plan** (what was decided), and **execution state** (what has actually
happened) — plus a `Planner` Protocol and a planning-owned `PlanStore`.

### 1. `Goal` — the durable objective, separate from the request

`core/types.py` gains:

```python
class GoalStatus(StrEnum):
    ACTIVE; ACHIEVED; ABANDONED; BLOCKED

class Goal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    statement: str            # canonical text rendering, used for retrieval
    status: GoalStatus = GoalStatus.ACTIVE
    provenance: Provenance    # user-asserted vs inferred (ADR-0005)
    created_at: datetime      # tz-aware
    deadline: datetime | None = None
```

A `Goal` is deliberately **not** the same thing as a user utterance. A request
("book me a flight") is transient; a goal ("relocate to Lisbon in September")
outlives any one conversation and is what makes a plan resumable and a
notification justifiable. It carries `Provenance` for the same reason every
memory does (ADR-0005): a goal the system *inferred* must never be
indistinguishable from one the user *stated*.

`Goal` is a `core` type rather than a memory kind. A goal is planning input,
not a retrieval record; projecting goals into memory (or the reverse) is a
follow-on decision, not a prerequisite (§7).

### 2. `ActionPlan` — frozen, and expressed in capabilities, not tools

```python
class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    intent: str                             # human-readable "what this is for"
    capability: str                         # what must be done, not what does it
    parameters: Mapping[str, JsonValue] = {}

class ActionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    goal_id: str
    steps: tuple[PlanStep, ...]
    created_at: datetime
    rationale: str | None = None
```

Two properties matter:

**A step names a capability, not a tool.** `capability` is an abstract
requirement — `"send_email"`, `"search_calendar"` — that one or more registered
tools may satisfy. It is *not* a registry key. This keeps the pipeline's
`planning → tool selection` boundary intact: the planner decides what must
happen, and the later tool-selection stage picks the concrete tool by weighing
the `risk_level`/`reversibility`/`cost` metadata that Lane B's `ToolDefinition`
will carry. Baking a tool id into planner output would collapse those two
stages and make the risk-aware selection VISION §3 calls for impossible —
the plan would have already chosen.

It also means `planning` depends on the `tools` subsystem neither by import nor
in spirit: `capability` is a vocabulary term, and a plan referencing a
capability nothing implements is a legitimate, detectable outcome of the
selection stage, not a broken plan.

**The plan is frozen.** `frozen=True` is not decoration — it is what makes the
plan an auditable record of a decision. Re-planning produces a *new*
`ActionPlan` with a new `id` (the previous one stays referenced by the
`ExecutionState` that ran it), rather than mutating a plan out from under an
in-flight execution. "What did the system decide to do, and when" stays
answerable.

`parameters` is untyped-but-**serialisable**: `Mapping[str, JsonValue]`, using
pydantic's recursive JSON type. Argument *schemas* belong to `ToolDefinition`,
so validating a step's parameters against the selected tool's schema happens at
selection time, in Lane B — but the value space cannot be plain `object`. Plan
state is persisted and exported (§5), and `object` admits values that cannot
round-trip through SQLite or `PlanExport` (a `datetime`, an open file handle),
which would make persistence behaviour depend on which planner produced the
plan. `JsonValue` makes "this is storable and portable" a property the type
system checks at construction rather than a hope the store discovers at write
time. The same reasoning applies to `StepExecution.output` (§3).

**`frozen=True` is not enough on its own, so parameters are deep-frozen at
validation.** Pydantic's `frozen=True` blocks field *reassignment*; it does not
freeze what a field contains, so `step.parameters["recipient"] = ...` would
still mutate a supposedly immutable decision record — and an audit record that
can be edited after the fact, or between plan and execution, is not an audit
record. `PlanStep` therefore runs a recursive validator converting the incoming
JSON value into an immutable one (mappings to `MappingProxyType`, lists to
`tuple`) before storing it. The guarantee is then depth-independent rather than
true only at the top level. This is why `parameters` is typed `Mapping`, not
`dict`: callers get a read-only view, and pydantic still serialises it as a
JSON object.

### 3. `ExecutionState` — the durable half, owned by deterministic code

```python
class StepStatus(StrEnum):
    PENDING; AWAITING_APPROVAL; RUNNING; SUCCEEDED; FAILED; SKIPPED; INDETERMINATE

class SkipReason(StrEnum):
    APPROVAL_DENIED; UNMET_DEPENDENCY; NO_CAPABLE_TOOL; SUPERSEDED

class StepExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    bound_tool: str | None = None      # the tool selection actually chose
    output: JsonValue | None = None
    approval_ref: str | None = None    # id of the permissions/ decision
    skip_reason: SkipReason | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None

class ExecutionState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    plan_id: str
    steps: tuple[StepExecution, ...]   # one per PlanStep, same order
    version: int = 0                   # optimistic-concurrency token (§5)
    updated_at: datetime
```

Splitting this out of `ActionPlan` is the whole point of the ADR. Fusing them —
a plan with mutable per-step status — is the tempting shape and it fails three
ways: the audit record mutates as execution proceeds, resuming after a crash
means reconstructing a plan rather than loading state, and re-planning mid-run
has nowhere to put "these three steps already ran".

For this to be genuinely resumable, the snapshot must carry everything a
restarted executor needs to *not redo work*:

- **`output`** — a succeeded step's result. Without it, a later step that needs
  the booking reference produced by an earlier one has no way to continue but to
  re-run the earlier step, which for a non-idempotent tool means acting twice.
  Storing the output is what makes "resume" mean resume. (How a later step
  *references* a prior output — templating, binding — is deferred; §7.)
- **`approval_ref`** — a *reference* to the permission subsystem's durable
  decision, so a restart neither re-prompts for consent already given nor
  silently proceeds past a denial. It is deliberately a foreign key and not a
  copy of the decision: ADR-0004 §7 assigns the audit trail to `permissions/`,
  and duplicating the ruling here would create a second authority that can
  drift from it. Execution state keeps only what is execution's own business —
  the resulting `status`, and `skip_reason=APPROVAL_DENIED` when the ruling was
  no.
- **`bound_tool`** — which tool the selection stage chose. The plan records the
  capability; execution records what actually ran. Both halves are needed to
  answer "what did the system do".

`ExecutionState` has no plan-level status field: it is derivable from the steps,
and storing it would create a second source of truth that can disagree with
them.

### 4. The transition graph, in full

Transitions live in `planning/`, not on the types: `core/types.py` is data-only
by convention, and VISION §7 says deterministic code owns state transitions. So
`PlanExecution` — a deterministic tracker in `planning/` — owns the legal moves
and rejects everything else with `PlanningError`:

| From | To | Trigger | Also sets |
| --- | --- | --- | --- |
| `PENDING` | `RUNNING` | selection + permission cleared it outright | `bound_tool`, `approval_ref`, `started_at` |
| `PENDING` | `AWAITING_APPROVAL` | permission check requires confirmation | `bound_tool` |
| `PENDING` | `SKIPPED` | nothing can run it | `skip_reason` ∈ {`UNMET_DEPENDENCY`, `NO_CAPABLE_TOOL`, `SUPERSEDED`} |
| `AWAITING_APPROVAL` | `RUNNING` | `permissions/` granted | `approval_ref`, `started_at` |
| `AWAITING_APPROVAL` | `SKIPPED` | `permissions/` denied | `approval_ref`, `skip_reason=APPROVAL_DENIED` |
| `AWAITING_APPROVAL` | `SKIPPED` | cancelled while queued for approval | `skip_reason=SUPERSEDED` |
| `RUNNING` | `SUCCEEDED` | tool returned | `output`, `finished_at` |
| `RUNNING` | `FAILED` | tool raised | `error`, `finished_at` |
| `FAILED` | `RUNNING` | retry | `attempts += 1`, `started_at` |
| `RUNNING` | `INDETERMINATE` | recovery found it running after a crash | `finished_at` |

**Every transition into `RUNNING` carries an `approval_ref`** — including the
common case where the permission layer cleared the step automatically, without
prompting. ADR-0004 §7 gates *every* side-effecting call, so "no prompt was
shown" must still mean "a decision was recorded and can be pointed at". If
`approval_ref` were set only on the `AWAITING_APPROVAL` path, precisely the
silent, automatic actions — the ones a user is least able to recall consenting
to — would be the ones that could not be correlated with their authorisation.
`PlanExecution` rejects a `→ RUNNING` transition without one.

**The `→ RUNNING` transition is a claim, and must be committed before the tool
is invoked.** This ordering is the point of the CAS in §5: two workers racing
the same step both attempt the claim, one's `commit_transition` fails with
`StaleExecutionError`, and the loser has not yet acted. Committing *after*
invocation would make CAS useless — it would reject a write only once both side
effects had already happened.

`SUCCEEDED` and `SKIPPED` are terminal. `FAILED` is terminal *unless* retried,
and the retry ceiling is enforced by the tracker, not by a model — retries are
named in VISION §7 as deterministic state. `AWAITING_APPROVAL` is a durable
state rather than an in-memory pause precisely so a restart preserves it.

**We do not claim exactly-once execution, and `INDETERMINATE` is where we say
so.** A crash between a tool's side effect and the commit of `RUNNING →
SUCCEEDED` leaves a durable `RUNNING` that cannot, from planning's vantage
point, be distinguished from a crash *before* the effect. Automatically
retrying it would risk acting twice; automatically failing it would risk
reporting a completed action as failed. So recovery does neither: it moves such
a step to `INDETERMINATE`, which is never auto-retried and must be resolved
explicitly — by reconciling with the tool or by asking the user. Making the
ambiguity a first-class durable state is the deterministic answer VISION §7
asks for; guessing would not be.

Recovery scans `active_executions()` at startup, which presumes no executor is
live for those states — true for a single-user local app with one executor. A
lease (`RUNNING` with an expiry, reclaimable by a peer) is the generalisation
and is deferred with the rest of concurrent execution. Genuine exactly-once
needs the *tool* to dedupe against an idempotency key, so it is Lane B's to
offer and this ADR's to consume later (§7).

`PlanExecution` takes an injectable `now: Callable[[], datetime]`, matching
`memory` and `context`, so timestamps are deterministic in tests. Each
transition returns a *new* `ExecutionState` rather than mutating in place, so a
caller cannot half-apply a transition and persist it.

`core/errors.py` gains `PlanningError(AssistantError)`.

### 5. `PlanStore` — planning owns its durable state

Durable planning state belongs to `planning`, not to the wiring layer:
`CLAUDE.md` assigns progress tracking to `planning` and limits `orchestration`
to injecting implementations. Goals, plans, parameters, outputs and errors are
all personal data, so this state is squarely within ADR-0004's scope.
`core/protocols.py` therefore gains:

```python
class PlanStore(Protocol):
    async def save_goal(self, goal: Goal) -> str: ...
    async def get_goal(self, goal_id: str) -> Goal | None: ...
    async def save_plan(self, plan: ActionPlan) -> str: ...
    async def get_plan(self, plan_id: str) -> ActionPlan | None: ...
    async def start_execution(self, plan_id: str) -> ExecutionState: ...
    async def commit_transition(self, transition: StepTransition) -> ExecutionState: ...
    async def get_execution(self, execution_id: str) -> ExecutionState | None: ...
    async def active_executions(self) -> list[ExecutionState]: ...
    async def export(self) -> PlanExport: ...
    async def delete_goal(self, goal_id: str) -> GoalDeletion: ...
    async def clear(self) -> int: ...
```

**The store accepts transitions, not snapshots.** The write API takes a
`StepTransition` — a `core` command naming the execution, the step, the target
status, the fields it sets, and the `expected_version` it was computed against
— rather than a caller-built `ExecutionState`:

```python
class StepTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    execution_id: str
    step_id: str
    to_status: StepStatus
    expected_version: int
    bound_tool: str | None = None
    approval_ref: str | None = None
    output: JsonValue | None = None
    skip_reason: SkipReason | None = None
    error: str | None = None
```

`start_execution` takes a `plan_id`, not a caller-built snapshot, for the same
reason: the initial state is *derived* — one `PENDING` `StepExecution` per
`PlanStep`, in order, at `version` 0 — and deriving it inside the store is what
guarantees the positional correspondence with the plan that everything else
assumes. A caller handing in an `ExecutionState` could open one already marked
`RUNNING`, or with steps that do not match the plan it names.

This is what makes §4's transition graph *authoritative* rather than merely
conventional. Had the store taken a whole `ExecutionState`, any consumer of the
Protocol could commit `PENDING → SUCCEEDED` directly and the claim that
deterministic code owns state transitions (VISION §7) would rest on nobody
choosing to bypass it. Implementations apply the transition against the stored
snapshot via `PlanExecution` and reject an illegal one with `PlanningError`;
they can, because `PlanStore` implementations live in `planning/` alongside the
tracker, so no boundary is crossed to reuse it.

**Writes are compare-and-swap.** `ExecutionState` carries a `version`;
`commit_transition` succeeds only if the stored version still matches
`expected_version`, and returns the state with `version` incremented. A stale
write raises `StaleExecutionError` (a `PlanningError`). Without this, two
workers can load the same `PENDING` snapshot, both claim the same
non-idempotent step, and both save — a lost update that also means the side
effect happened twice. Optimistic concurrency turns that into a detectable,
retryable failure, and it belongs to the store because the store is the only
place with a total order over writes.

The data-rights obligations are part of the contract, not an afterthought,
mirroring what ADR-0007 did for `MemoryStore`:

- **Local residency.** Implementations persist locally only (ADR-0004 §1); no
  implementation may write plan state to a remote service.
- **Exportable.** `export` returns a portable snapshot of goals, plans and
  execution state. This is how planning discharges ADR-0004 §6, so the shape is
  part of the contract — an unspecified return type is not something an
  independent store can conform to or an interface can consume:

```python
class PlanExport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: int = 1
    exported_at: datetime
    goals: tuple[Goal, ...]
    plans: tuple[ActionPlan, ...]
    executions: tuple[ExecutionState, ...]
```

  Relationships are carried by the ids already on the records (`ActionPlan.
  goal_id`, `ExecutionState.plan_id`) rather than by nesting, so the export is
  flat, and a plan whose goal was deleted is representable instead of
  unserialisable. The export is **complete and internally consistent**: every
  `goal_id`/`plan_id` referenced by an included record resolves within the same
  export. `schema_version` is explicit because an export outlives the code that
  wrote it — that is the point of an export — and a reader must be able to tell
  which shape it is holding. The caller serialises with
  `model_dump(mode="json")`, matching `MemoryStore.export` (ADR-0007 §3).
- **Deletable.** `delete_goal` cascades to that goal's plans and their execution
  state — a goal the user deletes must not leave its plan history behind.
  `clear` empties this store's own rows (a Tier 1 erase, not a whole-system
  one). `clear` is bound by the same in-flight rule as `delete_goal` below —
  it raises `ActiveExecutionError` (a `PlanningError`) while any execution has a
  non-terminal step, rather than emptying the store out from under a live tool
  call. A bulk erase is not a licence to orphan a side effect that a
  goal-scoped one refuses to orphan.

  **Deleting a goal with work in flight is refused, not forced.** Erasing an
  execution while a step is `RUNNING` would destroy the CAS record the executor
  is about to commit against: the step could then neither complete nor be
  reconciled, and a side effect already in progress would lose the only evidence
  it happened. The store cannot prevent that by "quiescing" the execution
  itself, because stopping a live tool call is not something a persistence layer
  can do — only whoever owns the running execution can. So `delete_goal` refuses
  while any step is non-terminal and names the offending executions in its
  result. The executor cancels them (driving `PENDING`/`AWAITING_APPROVAL` to
  `SKIPPED`/`SUPERSEDED`, and a `RUNNING` step to `INDETERMINATE` once it stops
  chasing it), and the caller re-issues the delete, which then succeeds.

  This defers the user's erasure right by one round-trip, which ADR-0004 permits
  — it requires deletion to be *available*, not instantaneous while an action is
  mid-flight. The alternative, deleting underneath a live tool call, would leave
  a side effect in the world with nothing anywhere recording it.

  Deletion is not silent either: `GoalDeletion` reports any `INDETERMINATE`
  steps it erased, so the user learns an action may have completed before its
  record went away.

```python
class GoalDeletion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    deleted: bool
    plans_removed: int = 0
    executions_removed: int = 0
    blocked_by: tuple[str, ...] = ()        # active execution ids; deleted=False
    indeterminate_steps: tuple[str, ...] = ()   # erased, possibly-completed
```

  A bare `bool` could not carry either message — an ordinary deletion and one
  that erased a possibly-completed side effect would be indistinguishable, and
  an interface built on this Protocol would have no way to warn the user the
  decision above promises.
- **Retention** follows ADR-0007's read-time model when plan records gain
  deadlines; no retention deadline is modelled in this slice (§7).

`active_executions` is what makes resumption possible at all: it is the query a
restarting system issues to find work left in flight.

This slice ships an in-memory `InMemoryPlanStore` plus the conformance suite;
a SQLite-backed implementation follows the precedent `memory` already set
(ADR-0006 slice 2). Until it lands, plan state does not survive a restart — the
*contract* is resumable, one implementation is not yet, and that gap is named
here rather than hidden.

### 6. The `Planner` Protocol

```python
class Planner(Protocol):
    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan: ...
```

`context` and `memories` are parameters rather than things the planner fetches
itself: the pipeline already assembles context and retrieves memory *before*
planning, and a planner that reached for them directly would import two
subsystems it has no business importing. Passing retrieved memory in is also
what makes plans personal rather than generic — the accumulated user model is
the product thesis, and planning is where it pays off.

`plan` is `async` because real planners call a model.

Per the Protocol-triad practice, `Planner` and `PlanStore` each land with a
canonical fake in `testing/` and a shared conformance suite, not just the
Protocol.

### 7. Deferred

- **A model-backed planner.** This slice lands the contracts, the deterministic
  execution tracker, and fakes. Decomposing a goal into steps with an LLM is a
  follow-on wanting its own ADR (prompt shape, validation of model output,
  failure modes).
- **A SQLite-backed `PlanStore`** — the durable implementation behind the
  contract defined in §5.
- **Output references between steps.** Outputs are stored (§3); the mechanism by
  which step 3 consumes step 1's output is a follow-on, because it is a
  substitution language with real injection-safety questions and no consumer
  until an executor exists.
- **Idempotency keys and `INDETERMINATE` resolution.** Turning at-most-once into
  exactly-once requires tools that dedupe against a caller-supplied key; that is
  Lane B's contract to offer. Automated reconciliation of an `INDETERMINATE`
  step waits on it (§4).
- **Execution leases**, which would let a peer reclaim a `RUNNING` step from a
  dead worker — unnecessary while one executor runs at a time (§4).
- **Step dependencies / parallel execution.** Steps are an ordered sequence.
  A `depends_on` DAG is additive later (an optional field defaulting to the
  implicit "after the previous step") and is not worth the executor complexity
  before an executor exists. `UNMET_DEPENDENCY` is in `SkipReason` from the
  start so the durable vocabulary does not have to change when it lands.
- **Retention deadlines on plan records** (§5), pending a policy on how long
  completed plan history should be kept.
- **What `approval_ref` points at.** It is an opaque id until `permissions/`
  lands its decision record (ADR-0004 §7); until then nothing dereferences it,
  and the `AWAITING_APPROVAL` transitions are exercised by tests, not by a real
  permission check.
- **Goals in memory.** Whether goals are retrievable records, and how they
  reconcile with `PreferenceMemory`, is a follow-on (§1).

## Consequences

- **The pipeline gets its planning step**, and `orchestration` gets the two
  first-vertical artifacts it was missing, without waiting on `tools`.
- **The `planning → tool selection` boundary survives contact with the type
  system.** Plans are capability-level, so tool selection remains a real stage
  that can reason about risk and reversibility rather than ratifying a choice
  the planner already made.
- **The audit story holds:** a frozen `ActionPlan` records what was decided; a
  separate `ExecutionState` records what happened, which tool ran, and what the
  user approved; re-planning adds a plan rather than editing one.
- **Execution is resumable by construction** — outputs and approvals are
  durable, so recovery re-runs nothing that already succeeded.
- **State transitions stay deterministic** (VISION §7): every legal move is
  enumerated in §4 and enforced by `PlanExecution`; no model output ever sets a
  `StepStatus`.
- **`planning` owns durable state it is accountable for**, with ADR-0004's
  export/delete obligations written into the `PlanStore` contract rather than
  deferred to whoever implements it.
- **Concurrent execution is safe by contract, not by convention:** claiming a
  step commits before the tool runs, so a racing worker loses with a
  `StaleExecutionError` before it acts, not after.
- **Exactly-once is explicitly out of scope.** A crash mid-effect yields an
  `INDETERMINATE` step requiring explicit resolution. This is a real operational
  cost — someone or something must adjudicate — accepted in preference to a
  system that silently double-books a flight or wrongly reports success.
- **The audit record is immutable in fact, not just in annotation** — plan
  parameters are deep-frozen, so what executes is what was decided.
- **The transition graph is enforced, not advisory:** the store's only write
  path is a `StepTransition`, so there is no Protocol-level way to persist a
  state `PlanExecution` would have rejected.
- **Every executed step is correlatable with its authorisation**, including
  silently auto-approved ones — the case ADR-0004 §7 most needs covered.
- **Deleting a goal can fail and need retrying** while its execution is live.
  That is a real ergonomic cost on the erasure path, accepted because the
  alternative erases the only record of an action still in flight.
- **Plan data is serialisable by construction.** `JsonValue` means an
  unpersistable parameter is rejected where it is built, not discovered by
  whichever store tries to write it.
- **New `core` surface is large:** `Goal`, `GoalStatus`, `PlanStep`,
  `ActionPlan`, `StepStatus`, `SkipReason`, `StepExecution`,
  `ExecutionState`, `StepTransition`, `PlanExport`, `GoalDeletion`,
  `PlanningError`, `StaleExecutionError`, `ActiveExecutionError`, and
  the `Planner` and `PlanStore` Protocols. That is a lot at once — it is the
  smallest set that
  expresses the plan/state split *and* discharges the data-rights obligation;
  a smaller one would have to fuse plan with state or leave durable personal
  data uncontracted.
- **`capability: str` is an uncontrolled vocabulary.** Nothing yet enforces that
  a planner's capability names match what tools advertise; a shared vocabulary
  (or its rejection in favour of matching on `ToolDefinition` metadata) is
  Lane B's to settle.
- **Persistence is contracted but not yet durable** (§5) — until the SQLite
  backend lands, resumption works within a process, not across a restart.
- **Two ordered sequences must stay aligned** — `ExecutionState.steps` is
  positionally one-to-one with `ActionPlan.steps`. `PlanExecution` constructs
  state from a plan so callers do not hand-build the correspondence, and
  `plan_id` makes a mismatched pairing detectable.
- **Revisit when** a model-backed planner lands (does `ActionPlan` need
  confidence or alternatives?), when steps need to run in parallel, or when
  Lane B settles the capability vocabulary.
