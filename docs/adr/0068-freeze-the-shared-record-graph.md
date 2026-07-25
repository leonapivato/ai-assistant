# 68. Freeze the shared record graph: immutability is a property of the types

- Status: Proposed
- Date: 2026-07-25
- **This is a contract change.** It makes deep immutability a property of the
  boundary-crossing pydantic models in `core/types.py` — a `core` type change
  that touches every subsystem exchanging a memory record, a goal, or an
  execution state. Golden rule 5 therefore applies: this ADR ships as **its own
  PR, ratified ahead of any implementation** (ADR-0015 §5). It is reviewed while
  still `Proposed`, so a finding can still change the decision, and flipped to
  `Accepted` on merge — `CONTRIBUTING.md`, "Contract ADRs land before their
  implementation". This PR is docs-only; the implementation is a separate lane,
  and until it lands the types are unchanged.
- Refs: ADR-0065 (the read-once clause this is the deferred follow-through of —
  see §4), ADR-0060 (the sibling module-level clause, cited only as a precedent
  for *where* a cross-cutting property is stated, **not** conflated — different
  axis), ADR-0014 (froze `ActionPlan`/`PlanStep` and left the surrounding graph
  mutable — the era this closes), ADR-0045 §4 and ADR-0056 (the `score`-on-read
  and torn-write paths this must stay compatible with), ADR-0018 §3 (the
  `__dict__` bypass, which freezing does **not** close — see Consequences).
- Source: issue #41. Also closes the immutability half of #40 and moots the
  element-mutation exploits in #381 and #386.

## Context

Issue #41 is the root, and it names a fork rather than a bug. Adversarial review
of the planning slice (ADR-0014) observed that `PlanStore` enforces immutability
where state is *held* — it copies every record in and out — but `Goal` and
`ExecutionState` are mutable pydantic models, so a caller can edit its own
handed-out copy, including records inside a `PlanExport`, and produce a snapshot
whose `goal_id`/`plan_id` references no longer resolve even though the store only
ever emits consistent ones. ADR-0014 declined to fix it, with a reason recorded
in its Consequences: closing it means **freezing the whole reachable graph**, and
`Goal` carries `Provenance`, which every `MemoryRecord` also carries — a
cross-subsystem change touching `memory`, not a quiet widening of a planning
slice. The issue leaves two ways open:

> either freeze `Provenance` and the record types across `core` (adjusting
> `memory` accordingly), or state in the ADRs that immutability is a property of
> stored state and not of handed-out copies, so the next reviewer does not
> re-raise it.

The owner has taken the first fork. This ADR records that choice, argues it, and
specifies it precisely enough that the implementation lane has no open question.

### The split in `core/types.py` is by build era, not principle

`core/types.py` holds 31 `BaseModel`s. They divide almost exactly in half
between frozen and mutable, and the line is chronological: the later subsystems
(`tools`, `permissions`, the invocation seam) froze everything they added; the
earlier ones (the conversation, memory records, planning state) did not. The
survey, taken mechanically against `origin/main`:

**Frozen today (15)** — `model_config` carries `frozen=True`:

`MemoryWrite`, `PlanStep`, `ActionPlan`, `StepFailure`, `StepTransition`,
`GoalDeletion`, `PlanExport`, `ToolCost`, `ToolDefinition`, `ActionRequest`,
`PermissionRuling`, `PermissionDecision`, `ToolFailure`, `ToolResult`,
`ToolCall`.

**Mutable today (16)** — no `frozen=True`:

| model | `model_config` | crosses a seam via |
| --- | --- | --- |
| `Message` | *(none)* | `ModelProvider.complete` argument |
| `Provenance` | *(none)* | inside every `MemoryRecord` **and** `Goal` |
| `Validity` | *(none)* | inside every `MemoryBase` |
| `MemoryBase` | *(none)* | base of the four record kinds |
| `EpisodicMemory` | *(none)* | `MemoryRecord` union member |
| `SemanticMemory` | *(none)* | `MemoryRecord` union member |
| `PreferenceMemory` | *(none)* | `MemoryRecord` union member |
| `ProceduralMemory` | *(none)* | `MemoryRecord` union member |
| `MemoryUpdateProposal` | *(none)* | `MemoryWriter.ingest`, `MemoryPolicy.decide` |
| `MemoryDecision` | *(none)* | returned by `MemoryPolicy.decide` |
| `MemoryIngestResult` | *(none)* | returned by `MemoryWriter.ingest` |
| `CurrentContext` | `extra="forbid"` | `Planner.plan` argument, `ContextProvider.assemble` return |
| `FeedbackEvent` | *(none)* | `FeedbackProcessor.process` argument |
| `Goal` | `extra="forbid"` | `Planner.plan`, `PlanStore.save_goal`, inside `PlanExport` |
| `StepExecution` | *(none)* | inside `ExecutionState` |
| `ExecutionState` | `extra="forbid"` | `PlanStore` return, inside `PlanExport` |

Three of the sixteen — `CurrentContext`, `Goal`, `ExecutionState` — already carry
`extra="forbid"` without `frozen=True`. That is the fingerprint of the era: an
author reached the config question, forbade unknown fields, and did not reach
immutability. **Every model in the mutable column crosses a subsystem boundary**,
which is not a coincidence — `core/types.py` is by charter the home of types that
"flow *between* subsystems" (its own module docstring). So the "deliberately left
mutable" set below is empty: there is no boundary-internal type here to exempt.

### The depth problem: `frozen=True` is shallow

`frozen=True` stops **field reassignment**. It does nothing about mutating the
object a field points at. `core/types.py` states this in its own comments
(`FrozenJson`'s docstring: "pydantic's `frozen=True` stops field *reassignment*
and does nothing about mutating a `dict` a field holds"), and ADR-0065 made it
the headline of its Rejected "freeze the types" bullet. So a shallow freeze of
the sixteen closes almost nothing. Two shapes leak:

**Mutable collection fields.** Five of the sixteen hold a `list`, which stays
`.append`-able on a frozen model:

- `Provenance.evidence: list[str]`
- `EpisodicMemory.participants: list[str]`
- `ProceduralMemory.steps: list[str]`
- `MemoryUpdateProposal.conflicts: list[str]`
- `FeedbackEvent.evidence: list[str]`

**Nested mutable models.** A frozen outer model with a mutable inner model is
frozen in name only. The reachable graph:

- `MemoryBase.provenance` → `Provenance` (mutable) → `evidence: list`
- `MemoryBase.validity` → `Validity` (mutable)
- `Goal.provenance` → `Provenance` (mutable) → `evidence: list`
- `MemoryUpdateProposal.proposed` → `MemoryRecord` (mutable) → `Provenance` → `list`
- `MemoryIngestResult.decision` → `MemoryDecision` (mutable)
- `ExecutionState.steps` → `tuple[StepExecution, ...]` — tuple is immutable, but
  each `StepExecution` element is mutable.

The tree already carries **two frozen-around-mutable counterexamples**, and both
are load-bearing, not hypothetical:

1. `MemoryWrite` is `frozen=True` around a mutable `MemoryRecord` — ADR-0065's
   own example of why "the argument is frozen" proves nothing.
2. `PlanExport` is `frozen=True` around `tuple[Goal, ...]` and
   `tuple[ExecutionState, ...]`, both mutable. This is **issue #41's cited
   scenario, already frozen and still broken**: a caller reaches
   `export.goals[0].statement` and rewrites it, and the frozen wrapper does not
   stop it. A shallow freeze of `Goal` and `ExecutionState` would not either;
   only freezing their fields all the way down does — at which point `PlanExport`
   becomes deeply immutable for free, without a line changing in `PlanExport`.

So the central technical content of this ADR is not "add `frozen=True`" — it is a
**depth rule** that closes the graph. The house already has the mechanism:
`FrozenDict`/`FrozenJson` (used by `ToolDefinition` and `PlanStep`) make a JSON
value immutable all the way down, and `ActionPlan.steps`/`ExecutionState.steps`/
`GoalDeletion.blocked_by` already use `tuple[..., ...]` where a `list` would
read naturally. Deep immutability is an established convention here, applied
unevenly; this ADR finishes it.

### The `score` wrinkle, verified not assumed

`MemoryBase.score` is documented "populated by retrieval; None when stored" —
the one field on these records that is written *after* construction. If retrieval
mutated it in place, freezing `MemoryBase` would break the read path. It does
not. Both production stores and the canonical fake build a **new** object:

- `memory/sqlite_store.py:594` — `self._decode(data).model_copy(update={"score": score})`
- `memory/store.py:207` — `record.model_copy(update={"score": score}, deep=True)`
- `testing/memory.py:221` — `record.model_copy(update={"score": ...}, deep=True)`

`model_copy(update=...)` constructs a fresh instance and works unchanged on a
frozen model (it deliberately bypasses validation). So freezing `MemoryBase` is
compatible with the retrieval path, and the impl lane must **keep**
`score`-on-read a copy-with-update, never an in-place set.

The claim "nothing mutates these types in place" is load-bearing, so it was
checked rather than asserted. Grepping `src/` for in-place assignment to any
field of these models, and for the `object.__setattr__` / `__dict__[...]` /
`setattr(` bypasses, returns:

- **No** in-place field assignment anywhere. Every hit for a bypass pattern is
  in a *docstring* documenting the bypass as a threat (`protocols.py`,
  `orchestration/executor.py`, `planning/store.py`), not code performing one.
- Planning rebuilds state functionally throughout: `execution.py` produces every
  new `StepExecution`/`ExecutionState` via `StepExecution(...)`,
  `model_copy(update=...)`, and `model_validate(...)`; `planner.py` snapshots a
  `Goal` with `model_copy(deep=True)` and builds plans via `model_validate`.
- `score` is populated only through the three `model_copy(update={"score": ...})`
  sites above.

Nothing in the tree depends on mutating these models, so freezing them breaks no
caller. The one caveat is the `__dict__` bypass, addressed in Consequences.

### Relationship to ADR-0065, #40, #381, #386

**ADR-0065** stated the read-once clause ("a call observes its inputs at one
instant, before its first await"). Its Rejected section weighed exactly this
change — "Freeze the types instead" — and declined it *for ADR-0065's own scope*
on two grounds this ADR must engage head-on: (a) `frozen=True` is shallow, so a
freeze would have to be deep and total, with `MemoryWrite` the in-tree
counterexample; and (b) freezing does nothing for the `Sequence` arguments, where
the container is the caller's and mutable whatever its elements are. ADR-0065
closed that bullet with: "Deep-freezing `core`'s mutable models may well be worth
doing; it is a large `core/types.py` change with its own blast radius and needs
its own ADR, not a paragraph in this one." **This is that ADR.** It does not
overturn ADR-0065 — §4 states precisely what residual ADR-0065 keeps.

**Issue #40** raises two separable things about the `MemoryPolicy` contract: (1)
input immutability of `decide`, and (2) a non-blank `MemoryDecision.reason`
(`reason=""` passes today). The first is answered by freezing; the second is an
orthogonal content validator, and §5 decides its disposition explicitly.

**Issues #381 and #386** are the two live exploits of the unfrozen state — an
injected `MemoryPolicy` mutating `proposal.proposed` to desync `ingest`'s write
(#381), and a wrapper's `Message` snapshot handed to a collaborator that rewrites
its `content`/`role` (#386). Both are the "reverse direction" ADR-0065 §5
explicitly left undecided. Freezing moots the *element-mutation* core of each;
Consequences states exactly what it closes and what residual it does not.

## Decision

### 1. Freeze the graph, deeply

We will make every boundary-crossing pydantic model in `core/types.py`
**deeply immutable**. The rule has two parts, and both are required — the first
alone is the shallow freeze this ADR rejects.

**(a) `frozen=True` on all sixteen mutable models.** Add `frozen=True` to the
`model_config` of: `Message`, `Provenance`, `Validity`, `MemoryBase` (inherited
by `EpisodicMemory`, `SemanticMemory`, `PreferenceMemory`, `ProceduralMemory`),
`MemoryUpdateProposal`, `MemoryDecision`, `MemoryIngestResult`, `CurrentContext`,
`FeedbackEvent`, `Goal`, `StepExecution`, `ExecutionState`. The three that carry
`extra="forbid"` keep it and gain `frozen=True` alongside. Setting `frozen=True`
on `MemoryBase` propagates to the four record subclasses through config
inheritance, so the subclasses need no separate change; the impl lane may set it
on `MemoryBase` only, or on each for legibility — that is a mechanism choice.

**(b) The depth rule for their fields.** A frozen model is deeply immutable only
if nothing it reaches is mutable:

- **Mutable collection fields become immutable collections.** Every `list[X]`
  field on a frozen model becomes `tuple[X, ...]`, matching the house form
  (`ActionPlan.steps`, `ExecutionState.steps`, `GoalDeletion.blocked_by`). The
  five fields: `Provenance.evidence`, `EpisodicMemory.participants`,
  `ProceduralMemory.steps`, `MemoryUpdateProposal.conflicts`,
  `FeedbackEvent.evidence`. `default_factory=list` becomes the empty-tuple
  default. pydantic coerces a caller's `list` to a `tuple` at validation, so
  construction with a list keeps working; what changes is that a **read** returns
  an immutable tuple. (Any JSON/mapping value already routes through
  `FrozenJson`/`FrozenDict` and is immutable already; no such field appears on
  the sixteen.)
- **Nested models are frozen, so nesting is closed.** Because all sixteen are
  frozen, every nested-model field — `MemoryBase.provenance`,
  `MemoryBase.validity`, `Goal.provenance`, `MemoryUpdateProposal.proposed`,
  `MemoryIngestResult.decision`, and the `StepExecution` elements of
  `ExecutionState.steps` — points at an immutable object. No separate change to
  the container is needed.
- **`model_copy(update=...)` sites must supply the immutable form.** This is the
  depth rule's one non-obvious edge, and it is load-bearing: changing a field's
  *annotation* to `tuple` is necessary but not sufficient, because
  `model_copy(update=...)` **deliberately skips validation** — it does not coerce
  the update dict — so a call that replaces a now-immutable field with a `list`
  installs a mutable `list` *past* the frozen model. The concrete in-tree case is
  `conflicts`: `memory/ingest.py:478` and `testing/writer.py:142` both repopulate
  it with `model_copy(update={"conflicts": [record.id for record in conflicts]})`.
  Left unchanged, that reinstalls a mutable `list` on the very
  `MemoryUpdateProposal` handed to `MemoryPolicy.decide`, so a policy could run
  `proposal.conflicts.append(...)` — defeating exactly the input-immutability this
  ADR claims for `decide` (§5) and reopening the #381 shape one field over. The
  impl lane must therefore convert every update-dict site that supplies a
  now-immutable field to build the immutable value (here, `tuple(...)`); the two
  `conflicts` sites are the only ones in the tree today (`score` supplies a
  `float`, and the `provenance`/`validity`/`id` update sites supply frozen models
  or strings, all unaffected). Construction through normal validation is safe —
  pydantic coerces a `list` to a `tuple` there; it is only the validation-skipping
  copy path that needs the caller to pre-build the immutable form. `model_copy`
  supplied a *canonical* value (a `tuple`, a frozen model, a `str`) preserves
  immutability, which is its every in-tree use; a caller that instead hands it a
  *non-canonical* value reintroduces a shallow-mutable field — the same
  validation-skipping construction bypass as `object.__setattr__`/`__dict__`
  (Consequences), identically available on all fifteen already-frozen types and
  therefore a pre-existing property of pydantic freezing, not a hole this change
  opens. The depth rule closes the *sanctioned* path (the two `conflicts` sites);
  the residual is that accepted, universal caveat, not a new one.

With both parts applied, the reachable graph of any **validly-constructed**
`MemoryRecord`, `Goal`, `ExecutionState`, `PlanExport`, `MemoryUpdateProposal`,
`MemoryDecision`, `MemoryIngestResult`, `CurrentContext`, `FeedbackEvent` or
`Message` is immutable end to end. `MemoryWrite` and `PlanExport` — frozen today
around mutable elements — become genuinely deeply immutable the moment their
element types freeze, with no edit of their own.

**The scope of the guarantee, stated precisely so it is not over-read — the one
authoritative statement of it.** Deep immutability holds for a value whose
**entire reachable graph was built through validation**: every node produced by
normal construction, `model_validate`, or `model_copy(update=...)` supplied
canonical values, so that field-level coercion (`list`→`tuple`) ran at every
level. It is **not** an absolute property of the Python type, and — this is the
subtlety that makes the guarantee *graph-granular* rather than per-instance — a
validated **outer** model does not launder a poisoned **nested** one. Two
pydantic facts bound it, neither closed here because both are the same accepted,
universal validation-skipping-construction caveat that sits identically on all
fifteen types frozen before this change (Consequences):

1. **`model_copy(update=...)` skips validation**, so it can install a
   non-canonical (mutable `list`) value in an otherwise-frozen model — as can
   `object.__setattr__` and `x.__dict__[...]`.
2. **`revalidate_instances="never"`** — pydantic's default, already relied on and
   documented in ADR-0032 §6 — means constructing an outer model does *not*
   re-validate a nested model instance handed to it. So a `MemoryRecord` poisoned
   by (1) (`record.model_copy(update={"participants": []})`) keeps its mutable
   `list` even when wrapped by a perfectly normal
   `MemoryUpdateProposal(proposed=record, ...)`; outer validation re-runs the
   outer's own validators, not the inner's field coercion.

Together these say the guarantee is exactly "no ordinary mutation, and no
validation-skipping construction **anywhere in the graph**." This ADR therefore
claims *deep immutability of every graph built wholly through validation*, and
closes #40/#41/#381 **on the conforming path** — where the whole graph is validly
constructed — not a guarantee that no caller can hand-build a shallow-mutable
graph through a validation-skipping API, which no `frozen=True` in this file
provides and this one does not pretend to add. Requiring recursive revalidation
at every nested boundary is explicitly **rejected** (Rejected): the codebase
applies that round-trip only at the specific durable boundaries that need it
(`_detached_tool`, `AuditTrail.record` — ADR-0032 §6), not universally, and
imposing it on every `core` type would be a far larger mechanism than the freeze
decision, for a residual the whole contract surface already accepts. The rule
states a **property** (deep immutability of a validly-built graph), enforced by a
**mechanism** the house already uses (`frozen=True` + immutable collection types).
No model is deliberately left mutable: `core/types.py` holds only
boundary-crossing types, and the choice is to freeze all of them.

### 2. `Provenance` is the cross-subsystem hinge

`Provenance` is why this is a `core` ADR and not a memory slice or a planning
slice. It is reached from **both** subsystems: every `MemoryRecord` embeds it
(`memory`), and every `Goal` embeds it (`planning`, and through `PlanExport` the
data-rights export). Freezing `Provenance` — and turning its `evidence` list into
a tuple — therefore changes a type that `memory` and `planning` construct and
read independently, in one edit. That is the blast radius ADR-0014 refused to
absorb into a planning slice, and it is the reason the change lands as a single
`core` contract PR ahead of the two subsystems, rather than as either subsystem's
own work. `Validity` is memory-only; `Provenance` is the shared one, and it is
the load-bearing edit of this ADR.

### 3. The `score` path stays copy-with-update

Freezing `MemoryBase` is explicitly compatible with retrieval populating `score`,
because retrieval already builds a new object via `model_copy(update={"score":
...})` at all three sites (Context, verified). The impl lane must **not** convert
these to an in-place set to "simplify" now that the field is the only
post-construction write — the copy-with-update is the contract-compatible form
and the only one a frozen model admits. No new field annotation is required for
`score`; it stays `float | None`, written only by copy.

### 4. What survives of ADR-0065

Freezing shrinks ADR-0065's scope sharply but **does not eliminate it.** The
read-once clause survives, intact, for the **`Sequence` arguments** — because a
`Sequence` argument is a *container the caller still owns*, and freezing its
elements does not freeze the container. Even with `Message`, `MemoryRecord`,
`MemoryWrite`, and `MemoryUpdateProposal` all immutable, these seams still take a
caller-owned mutable container whose contents can change *which* elements the
call sees if it re-reads after suspending:

- `Embedder.embed(texts: Sequence[str])`
- `MemoryStore.search(..., kinds: Sequence[MemoryKind] | None)`
- `MemoryStore.write_atomic(writes: Sequence[MemoryWrite])`
- `MemoryPolicy.decide(..., conflicts: Sequence[MemoryRecord])`
- `Planner.plan(..., memories: Sequence[MemoryRecord])`
- `ModelProvider.complete(messages: Sequence[Message])`

For these, ADR-0065's clause is exactly as binding after this change as before:
observe the container once, before the first await. This is precisely what
ADR-0065's own "Revisit" clause predicted — "the clause would survive for the
`Sequence` arguments but its scope would shrink sharply." What freezing **removes**
from ADR-0065's live surface is the single-argument mutable-value tear:
`MemoryStore.add(MemoryRecord)`, `MemoryWriter.ingest(MemoryUpdateProposal)`,
`PlanStore.save_goal(Goal)`, and the per-element tear inside `MemoryWrite` and
`Message`. Those arguments can no longer change under a suspended call, so a
conforming implementation's snapshot of them becomes belt-and-braces rather than
load-bearing — but ADR-0065 stays in force and is **not** superseded, because the
container residual is genuinely a different property from element immutability.
This ADR touches no `Protocol` and no conformance suite of ADR-0065's.

### 5. Issue #40's non-blank `reason`: split out, not folded in

The non-blank-`reason` validator **rides in its own change, not this one.** This
ADR is about one property — deep immutability of the types — and a
`MemoryDecision.reason` content validator is an orthogonal axis: it is a
field-level *value* constraint (like `_reason_is_present` on `PermissionRuling`),
not a structural immutability property, and it does not share this ADR's blast
radius (it touches only `MemoryDecision`, not the graph). Folding it in would
grow the impl lane's diff with an unrelated breaking change — a `MemoryDecision`
with `reason=""` that validates today would stop validating — and blur what the
freeze is answerable for. The project's own discipline points the same way:
ADR-0065 split "freeze the types" out of its scope for exactly this reason, and
`CONTRIBUTING.md`'s triage rule keeps a change from absorbing adjacent findings.

This does not drop #40. The **immutability half** of #40 (input immutability of
`MemoryPolicy.decide`) is answered here for what #40 actually asks — the real
write path. A **conforming producer** hands `decide` a validly-constructed
`MemoryUpdateProposal`, and §1's depth rule makes the ingestor supply `conflicts`
as a `tuple`, so the proposal `decide` receives is immutable and `decide` cannot
mutate it — the read-only expectation #40 records now holds by construction rather
than by an unwritten convention. This is a property of the value on the
conforming path, **not** an absolute guarantee that no caller could hand-build a
shallow-mutable proposal through `model_copy(update={"conflicts": [<list>]})` (the
accepted validation-bypass residual, §1 and Consequences); the shared
`MemoryPolicy` conformance suite asserts the input-immutability that every
conforming producer satisfies, which is where #40's assertions — today stranded in
each implementation's own tests — belong. The **non-blank-`reason` half** remains open on #40 as its
own small `core` change, needing its own ADR per ADR-0015 §5 (it is a contract
widening), and this ADR records that it was considered and deliberately deferred
so the next reviewer does not read the omission as an oversight.

### 6. What the implementation lane must carry

The implementation is **one follow-up lane**, dispatched after this ADR merges.
Because it edits `core/types.py`, it is inherently the cross-subsystem change §2
describes, landing as a single `core` contract PR (not split per subsystem). It
is a **breaking change** and must be flagged as such (`feat(core)!: ...`): reads
of the five list fields return tuples, and any code that mutated a handed-out
record now raises. No new `Protocol` is added, so no triad is created; the
conformance the change must carry is a set of **properties**, not a test design
(the lane owns the design):

- Each of the sixteen models rejects ordinary post-construction mutation:
  attribute assignment raises `ValidationError`, at the outer level **and**
  through every nested model (e.g. `record.provenance.confidence = ...` raises).
- The five ex-`list` fields are immutable collections: they reject in-place
  mutation (`.append`, item assignment) and round-trip
  `model_dump`/`model_validate` unchanged (a tuple serialises as a JSON array —
  no wire change).
- `conflicts` is immutable **on the real construction path**, not only at
  validation. A case must build a `MemoryUpdateProposal` the way `MemoryIngestor`
  does — populating `conflicts` via `model_copy(update=...)` after conflict
  detection — and assert the value handed to `MemoryPolicy.decide` cannot be
  `.append`-ed to. A test that only checks validation-time `list`→`tuple`
  coercion would pass over the `model_copy(update=...)` hole above; this property
  is what forces the ingestor and the canonical fake to supply a tuple.
- `PlanExport` and `MemoryWrite` are demonstrably deeply immutable now, i.e.
  issue #41's cited `export.goals[0].statement = ...` and ADR-0065's
  `write.record.content = ...` both raise.
- The `score`-on-read path still populates via `model_copy(update=...)`; the
  existing `MemoryStore` isolation/score cases still pass.
- The `MemoryPolicy` input-immutability assertions move from implementation tests
  into the shared conformance suite (§5).
**Test migration is a substantial part of the lane, and it is specified as a
*rule over classes of breakage*, not a hand-enumeration.** Enumeration is the
wrong tool here — it is the failure mode ADR-0065 §2 names, and a "complete list"
of test sites is exactly the claim that keeps proving one entry short. The lane's
own instruction is therefore: **run the gate; every red test falls into one of
the three classes below; recast it by that class's rule.** The gate is the
authority on completeness, not this ADR. The representative sites below are
examples of each class (verified against `origin/main`), not the full set.

- **Class A — mutation as a *stimulus*.** A test mutates one of these models in
  place to drive its assertion. Every such assignment raises once the model is
  frozen. Two sub-shapes, split on §4's element/container line (below): isolation
  cases become "assert the mutation raises"; ADR-0065 mid-flight cases keep only
  their container stimulus. Examples: `tests/memory/test_fake_store.py:111`/`:125`/
  `:139` (`.append` to a returned record's `provenance.evidence`; reassign
  `content`); `tests/memory/memory_store_contract.py:426`/`:431` (nested
  `Validity`); `:829-830` (`add` mid-flight torn-read); `:871-872` (`write_atomic`
  mid-flight); `tests/models/test_fake_provider.py:188`;
  `tests/models/test_routing.py:740` and `tests/models/test_retry.py:482`
  (`_rewrite_the_first_turn`); `tests/learning/test_fake_processor.py:279`, and
  `:303-304` (which builds an invalid script by mutating a valid proposal — recast
  to pass the bad value **at construction**).
- **Class B — list-equality *assertions*.** A test asserts a now-tuple field
  equals a `list`; `() == []` and `("ep-9",) == ["ep-9"]` are both `False` in
  Python, so the assertion fails on a correct implementation. Recast to a tuple
  (or order-insensitive) expectation. Examples: `tests/core/test_types.py:313`,
  `tests/learning/test_processor.py:70`, `tests/learning/test_fake_processor.py:124`,
  `tests/memory/memory_writer_contract.py:432`, and the assertion halves of the
  `test_fake_store.py` isolation cases (`:116`/`:129`/`:144`).
- **Class C — construction with a `list` literal.** Passing `evidence=["x"]` to a
  constructor keeps working (pydantic coerces to a tuple); no change needed, named
  only so the lane does not "fix" it. The read comes back a tuple — see Class B.

The Class A recast rule has two shapes, and which applies is exactly §4's
distinction:

- **Isolation cases** (a caller mutates a returned or passed object and asserts
  stored state is unaffected) become **assertions that the mutation raises**. The
  property they protected — a handed-out copy cannot reach stored state — is
  *subsumed* by immutability: there is no longer a mutation to isolate against.
  The intent is preserved, not deleted.
- **ADR-0065 mid-flight torn-read cases** split on §4's element/container line.
  The single-record `add` case (`:826-834`) drove its tear by mutating
  `record.id`/`record.content` while the write was suspended; freezing makes that
  stimulus **unrepresentable**, which is the point — the tear it guarded against
  cannot occur, so the case is retired or reduced to asserting the element cannot
  be mutated. The `write_atomic` case (`:868-875`) and the wrapper cases
  (`test_routing.py`/`test_retry.py`) keep a live tear on the **Sequence
  container**: `writes.append(...)` and appending a turn to the conversation
  remain valid mid-flight stimuli, because the container is the caller's and
  mutable whatever its elements are (§4, the ADR-0065 residual). So those cases
  keep their append parametrisation and drop only their element-rewrite one.

This is the impl lane's work to carry out. The ADR fixes the **classes** and the
recast rule for each — *how a retained property is exercised without mutating a
frozen value* — and leaves the completeness check to the gate, which is the only
thing that can be exhaustive. What the lane must not do is treat a red test as
license to relax the freeze; every one is a Class A/B/C recast.

The `__dict__` and `model_copy(update=...)` validation-bypass residuals are
explicitly **out of the lane's scope** (Consequences).

## Consequences

- **Issue #41 is closed at the type level.** The reachable graph from any
  handed-out record, goal, or plan-export is immutable, so the export whose
  references silently stop resolving is unrepresentable through ordinary mutation
  and validated construction. The next reviewer does not re-raise #41 because the
  illegal state is no longer reachable by mutating a validated instance — only by
  the validation-skipping construction bypasses every frozen type in the file
  already shares (below), which are out of scope for the same reason there as
  here.
- **The immutability half of #40 is closed on the conforming write path, the
  reason half is deferred (§5).** The proposal a conforming ingestor hands
  `MemoryPolicy.decide` is validly-constructed and (per §1) carries a `tuple`
  `conflicts`, so `decide` cannot mutate it; this is a property of the produced
  value, not an absolute type guarantee for a proposal hand-built through the
  `model_copy(update=...)` bypass. The non-blank-`reason` validator is its own
  future change.
- **#381 is closed on the conforming path.** Its exploit is element mutation —
  `proposal.proposed.content = B` inside `decide`. A frozen `MemoryUpdateProposal`
  and a frozen `MemoryRecord` make that raise on the validly-constructed proposal
  the ingestor observes, so `ingest` can no longer be desynced by a mutating
  policy in the real system. `FakeMemoryWriter`'s identical exposure closes with
  it. (A proposal a caller reconstructs through a validation-skipping copy is the
  accepted residual, not a live in-tree path.)
- **#386 is closed at its element-mutation half.** A frozen `Message` makes the
  "rewrites a `content`/`role`" exploit raise — including the `role`-flip that
  ADR-0065's amendment showed converts a retryable failure into a non-retryable
  one. Its **other half — a provider `.append`-ing to the caller/wrapper-owned
  `Sequence`** — is a *container* mutation freezing does not address; that is the
  ADR-0065 §5 reverse-direction-on-a-container question, still open (and already
  locally mitigated by #380's per-attempt snapshot). This ADR does not overclaim
  to close it.
- **ADR-0065 §5's reverse direction is mooted for element mutation, not for
  containers.** You cannot state a rule against mutating an immutable object, and
  after this change every *element* a callee is handed across these seams is
  immutable — so the element-mutation form of the reverse direction needs no
  clause. The container form (a callee mutating a caller's `Sequence`) is
  untouched and remains undecided, as ADR-0065 §5 left it.
- **`MemoryWrite` and `PlanExport` become genuinely deeply immutable** with no
  edit of their own — the two in-tree "frozen around mutable" counterexamples are
  resolved by freezing their element types.
- **The validation-skipping construction bypasses survive, and that is
  deliberate.** Issue #41 notes "even `frozen=True` yields to a `__dict__`
  write," and it is right: freezing stops *ordinary* mutation (attribute
  assignment, list mutation on a validated instance), not `object.__setattr__` /
  `x.__dict__[...] = ...`, and not `model_copy(update=...)` handed a value normal
  validation would have coerced or rejected. That last one is a *public* method
  that deliberately skips validation, so `frozen.model_copy(update={"conflicts":
  [<list>]})` yields a frozen instance around a mutable `list` — but only when
  handed a non-canonical value, and identically on all fifteen types frozen
  before this change (`ToolDefinition.model_copy(update={"reads": [...]})` is the
  same shape today), so it is a property of pydantic freezing rather than a hole
  this ADR opens. And because pydantic's default is `revalidate_instances="never"`
  (ADR-0032 §6), wrapping a value poisoned by any of these in a validated *outer*
  model does not clean it — outer construction re-runs the outer's validators, not
  the inner's field coercion — which is why §1 states the guarantee at graph
  granularity. All of these belong to one accepted category: validation-skipping
  construction is the caller's responsibility, inside the repository's threat
  model (ADR-0018 §3), and defended where it matters by revalidation at durable
  boundaries (`_detached_tool`, `AuditTrail.record` — the same ADR-0032 §6
  round-trip). This ADR raises the record types to exactly the bar every other
  frozen `core` type already sits at — no higher, and no lower. §1's depth rule
  accordingly fixes the two sanctioned in-tree `model_copy(update=...)` sites to
  supply canonical tuples rather than
  attempting to forbid a public method.
- **Blast radius.** `Provenance` (memory + planning), `Validity` and the memory
  record/decision/proposal types (memory), `Goal`/`StepExecution`/
  `ExecutionState` (planning), `CurrentContext` (context), `FeedbackEvent`
  (learning), `Message` (models). A single `core` PR, breaking, flagged
  `feat(core)!`. No `Protocol` surface moves.
- **A cost, stated plainly — most of it is test migration.** Five `list` fields
  become `tuple`, so any consumer that appended to a handed-out record's list must
  build a new record instead; reads that assumed `list` (indexing still works,
  `.append` does not) may need a one-line change. No `src/` consumer mutates these
  in place (verified by grep) — so no *production* code changes beyond the type
  edits and the two `model_copy` `conflicts` sites. The real cost lands in the
  **tests**: a spread of existing cases across `core`, `memory`, `models` and
  `learning` break in three named ways — mutation-as-stimulus (raises under the
  freeze), list-equality assertions (`tuple != list`), and harmless `list`-literal
  construction. §6 gives the recast rule per class and defers *completeness* to the
  gate rather than a hand-count, because a hand-count of test breakage is the
  enumeration ADR-0065 §2 warns keeps coming up one short. This is real work, and
  it is the expected shape of a breaking `core` change.
- **Revisit** if a genuinely un-snapshotable, inherently-mutable type ever has to
  cross a seam — a streaming handle, a live connection — where "freeze it" and
  "hold it immutably" stop being interchangeable. None exists today; every
  boundary type is a value.

## Rejected

- **State the invariant instead of freezing** (the other fork of #41; ADR-0065
  §5 / #381 option 1 / #386 option 1). Add a standing clause — "immutability is a
  property of stored state, not of handed-out copies," or "a call does not mutate
  its caller's arguments" — and leave the types mutable. Rejected on the facts,
  not by preference. First, a clause is an **unenforced promise every new
  consumer and every new Protocol must remember**; the paraphrase/enumeration
  failure ADR-0065 §2 documents is precisely this, and #381 and #386 are the
  clause being *re-raised twice already* — the outcome #41 wants to end. Second,
  and decisively, the clause form cannot even reach #41's cited case: a caller
  editing `export.goals[0].statement` is **not a call** — nothing is invoked, a
  field of a returned value is simply reassigned — so "a call does not mutate its
  argument" has no purchase on it. Freezing makes that reassignment raise;
  a sentence cannot. The clause is strictly weaker than the property.
- **Shallow `frozen=True` only** — add `frozen=True` to the sixteen and stop.
  Insufficient, and the tree already proves it: `MemoryWrite` is `frozen=True`
  around a mutable `MemoryRecord` and tore anyway (ADR-0065's headline), and
  `PlanExport` is `frozen=True` around mutable `Goal`/`ExecutionState` — issue
  #41's *exact* cited scenario, frozen today and still broken. A `list` field on
  a frozen model stays `.append`-able. Shallow freeze closes none of the leaks
  the depth rule closes; it must be deep (frozen all the way down + immutable
  collections), which is why §1 has two parts rather than one.
- **Freeze only the memory records, leave planning and context mutable.**
  Rejected because `Provenance` is shared (§2): a memory-only freeze either
  forks `Provenance` into two types or leaves the `Goal` path mutable, and #41's
  cited exploit lives in `PlanExport` (planning), not in `memory` at all. Half a
  freeze leaves the hinge mutable and the cited bug open.
- **Recursive revalidation at every nested-model boundary** — set
  `revalidate_instances="always"` (or round-trip through `model_validate(
  model_dump())`) on these models, so that wrapping a bypass-poisoned nested model
  in a validated outer one re-coerces it and closes the `revalidate_instances=
  "never"` gap (§1). Rejected as disproportionate to the residual it targets. The
  codebase already applies that round-trip at the *specific* durable boundaries
  that need it — `_detached_tool`, `AuditTrail.record` (ADR-0032 §6) — precisely
  because it is a real cost paid where a durable record must not carry a tampered
  value, not a default worth imposing on every construction of every record. The
  gap it would close is the same accepted validation-skipping-construction caveat
  every frozen type in the file already carries; spending recursive revalidation
  on it here would raise this ADR's types *above* the bar the rest of `core` sits
  at, for a caller-error class the threat model already assigns to the caller. The
  honest move is to state the guarantee at graph granularity (§1), not to buy a
  stronger one nothing else has.
- **A shared `freeze`/`snapshot` helper or a per-field read-only proxy.**
  Rejected for ADR-0065's reason against a shared snapshot helper: it makes every
  subsystem depend on a *mechanism* rather than on the *property*. `tuple` is the
  house form for an immutable sequence and `FrozenDict` for an immutable mapping;
  both are already in `core/types.py`. No new machinery is warranted.
