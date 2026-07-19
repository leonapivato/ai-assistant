# 14. Planning model: `Goal`, `ActionPlan`, and a separate `ExecutionState`

- Status: Proposed
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

There is also a sequencing constraint. `ToolDefinition` does not exist yet — it
is the next lane (issue #30, Lane B). Planning must therefore be designed so it
does not depend on the `tools` subsystem's shape, both because golden rule 1
forbids a cross-subsystem import and because this lane must not block on that
one.

This adds new `core` types and a new Protocol, so it is ADR-worthy (golden
rule 5).

## Decision

We will model planning as three distinct artifacts — a **goal** (why), a
**frozen plan** (what was decided), and **execution state** (what has actually
happened) — plus one `Planner` Protocol.

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
follow-on decision, not a prerequisite (§6).

### 2. `ActionPlan` — frozen, versioned, and tool-agnostic

```python
class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    intent: str               # human-readable "what this step is for"
    tool_name: str            # resolved against the registry at execution time
    arguments: Mapping[str, object] = {}

class ActionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    goal_id: str
    steps: tuple[PlanStep, ...]
    created_at: datetime
    rationale: str | None = None
```

Two properties matter:

**The plan is frozen.** `frozen=True` is not decoration — it is what makes the
plan an auditable record of a decision. Re-planning produces a *new*
`ActionPlan` with a new `id` (the previous one stays referenced by the
`ExecutionState` that ran it), rather than mutating a plan out from under an
in-flight execution. "What did the system decide to do, and when" stays
answerable.

**Steps name tools by string, not by `ToolDefinition`.** `tool_name: str` is
resolved against the tool registry at execution time. This is the seam that
keeps `planning` from depending on `tools` (golden rule 1) and keeps this lane
unblocked by Lane B. The cost is honest: an unknown `tool_name` is caught at
execution, not at plan construction. That is the correct place anyway — tool
availability is a runtime property (a tool can be revoked, rate-limited, or
permission-denied between planning and execution), so validating it at plan time
would be a false guarantee.

`arguments` is `Mapping[str, object]` because argument schemas belong to
`ToolDefinition`, which does not exist yet; validating a step's arguments
against its tool's schema is Lane B's job at registry-resolution time.

### 3. `ExecutionState` — the durable half, owned by deterministic code

```python
class StepStatus(StrEnum):
    PENDING; RUNNING; SUCCEEDED; FAILED; SKIPPED; AWAITING_APPROVAL

class StepExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None

class ExecutionState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    plan_id: str
    steps: tuple[StepExecution, ...]   # one per PlanStep, same order
    updated_at: datetime
```

Splitting this out of `ActionPlan` is the whole point of the ADR. Fusing them —
a plan with mutable per-step status — is the tempting shape and it fails three
ways: the audit record mutates as execution proceeds, resuming after a crash
means reconstructing a plan rather than loading state, and re-planning mid-run
has nowhere to put "these three steps already ran".

Concretely, this separation is what lets execution be **resumable**:
`ExecutionState` is a complete, serialisable snapshot, so recovering after a
restart is loading one record and continuing — not replaying or re-planning.

`AWAITING_APPROVAL` is present from the start because the pipeline has a
permission step before execute; a step blocked on a user confirmation is a
first-class durable state, not an in-memory pause (VISION §3, and ADR-0004's
audit requirement).

### 4. Transitions live in `planning/`, not on the types

`core/types.py` is data-only by convention, and VISION §7 says deterministic
code owns state transitions. So `PlanExecution` — a small deterministic tracker
in `planning/` — owns the legal moves (`PENDING → RUNNING → SUCCEEDED | FAILED`,
retry as `FAILED → RUNNING` with `attempts` incremented) and rejects illegal
ones with `PlanningError`. It takes an injectable `now: Callable[[], datetime]`,
matching `memory` and `context`, so timestamps are deterministic in tests.

It returns a new `ExecutionState` per transition rather than mutating in place,
so a caller cannot half-apply a transition and persist it.

`core/errors.py` gains `PlanningError(AssistantError)`.

### 5. One `core` Protocol

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

Per the Protocol-triad practice, this lands with a canonical `FakePlanner` in
`testing/` and a shared `PlannerContract` conformance suite, not just the
Protocol.

### 6. Deferred

- **A model-backed planner.** This slice lands the contract, the deterministic
  execution tracker, and a fake. Decomposing a goal into steps with an LLM is a
  follow-on, and wants its own ADR (prompt shape, validation of model output,
  failure modes).
- **A `PlanStore` persistence Protocol.** `ExecutionState` is designed to be
  serialisable and resumable; *where* it is persisted is `orchestration`'s
  concern once there is a pipeline to persist it from. Deciding it now would be
  a contract with no consumer.
- **Step dependencies / parallel execution.** Steps are an ordered sequence.
  A `depends_on` DAG is additive later (an optional field, defaulting to the
  implicit "after the previous step"), and is not worth the executor complexity
  before an executor exists.
- **Argument-schema validation** against `ToolDefinition` — Lane B (§2).
- **Goals in memory.** Whether goals are retrievable records, and how they are
  reconciled with `PreferenceMemory`, is a follow-on (§1).

## Consequences

- **The pipeline gets its planning step**, and `orchestration` gets the two
  first-vertical artifacts it was missing, without waiting on `tools`.
- **The audit story holds:** a frozen `ActionPlan` records what was decided, a
  separate `ExecutionState` records what happened, and re-planning adds a plan
  rather than editing one. VISION §3 becomes expressible instead of aspirational.
- **Execution is resumable by construction** — recovery is loading an
  `ExecutionState`, not reconstructing intent.
- **State transitions stay deterministic** (VISION §7): the model produces an
  `ActionPlan` and nothing else; no model output ever sets a `StepStatus`.
- **New `core` surface:** `Goal`, `GoalStatus`, `PlanStep`, `ActionPlan`,
  `StepStatus`, `StepExecution`, `ExecutionState`, `PlanningError`, and the
  `Planner` Protocol. That is a lot of surface at once — it is the smallest set
  that expresses the plan/state split; a smaller one would have to fuse the two.
- **`tool_name: str` is a deliberately loose reference.** A plan can name a tool
  that does not exist, and only execution finds out. Lane B's registry is where
  that resolves; until it lands, nothing validates step tools at all.
- **Two ordered sequences must stay aligned** — `ExecutionState.steps` is
  positionally one-to-one with `ActionPlan.steps`. `PlanExecution` constructs
  state from a plan so callers do not hand-build the correspondence, and
  `plan_id` makes a mismatched pairing detectable.
- **Revisit when** a model-backed planner lands (does `ActionPlan` need
  confidence or alternatives?), when steps need to run in parallel (§6), or when
  `ToolDefinition` makes argument validation possible at plan time.
