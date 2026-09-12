# 255. The driver walks a plan in dependency order, claims each step under its attempt, and stops rather than acting under an unfinished one

- Status: Proposed
- Date: 2026-09-12

## Context

### Where this comes from

This is **A7** of #2255, the third ADR of milestone 33, and it covers phase **5 Execute** of the
six-phase lifecycle. Four ratified documents defer the plan-driving stage to it by name.

ADR-0228 §14 is the deferral this decision fires:

> **The plan-driving stage, and with it a revision that follows a *driven* step's output.**
> ADR-0037 named it — *"Step ordering, dependencies (`UNMET_DEPENDENCY` has no producer yet),
> cancellation and the loop over `ActionPlan.steps` are the next slice"* — and ADR-0042 §3
> attached an overall decrementing per-request deadline to it. It additionally needs a rule for
> parking mid-plan (#257 is open on a ruling outliving its transition) and for an
> `INDETERMINATE` step in the middle of a plan (ADR-0014 §4). Fired by its own ADR, on
> `track:planning` or beside it.

ADR-0249 §13 reserves two halves of it: *"**The plan-driving stage, and what a refused stale
claim then causes** — a replan, a typed refusal, a report, a step left `PENDING` and later
`SKIPPED`/`SUPERSEDED`. A7 and A9"*, and *"Whether `StepTransition` carries the attempt id it is
claimed under is still A7's and A9's."*

ADR-0253 §2 states a rule and hands its enforcement here — *"The stage that walks a plan in
dependency order is **A7's**, and it is the lane that takes this section as its contract. **At
which moment a never-eligible step is moved to `SKIPPED`** … is A7's and A9's"* — and §11 adds
*"performing its interpretations, evaluating §2's rule and §5's conditions, resolving §6's
references"*. ADR-0253 §9 reserves one more: *"**the mechanism by which an attempt re-enters an
earlier phase is A7's**"*, which ADR-0254 §19 repeats.

ADR-0254 §19 reserves a third: *"A driver that walks a plan's steps **outside** [a turn] is
**A7's**, as §19 already reserves the plan-driving stage."*

The design direction is revision 1 of the report on #2255 — part 2 **§G.1**, **§G.2**, **§H.1**
and **§H.3**, and part 1 §B.2's phase-5 row. Each is treated as a concrete contract to ratify or
to correct against the tree, and §§1–11 below say which happened to each. **§H.1's construction
is corrected** (§3), and **§K.2 step 6's claim about what the goal records is corrected** (§7).

**Three owner rulings of 2026-09-12 (#2255) bind this decision.** The answer to **Q4** is carried
in §12 in the words ADR-0253 §3 and ADR-0254 §17 already carry it. **Correction 2** — *"Producing
a reply never by itself establishes that the goal was achieved; completion criteria concern the
requested outcome"* — is why §8 draws the line at `verifies` and why nothing here writes
`GoalStatus.ACHIEVED`. **Correction 3** — *"When understanding changes during investigation,
subsequent planning receives the updated goal view and identifies the interpretation revision it
targets"* — is ADR-0249 §8's `targets_revision` and its `commit_transition` refusal, **relied on
here and not re-landed** (§3).

### What the tree holds today, read rather than assumed, at `origin/main` `b1d265c1`

ADR-0249 has merged and is implemented; **ADR-0250 M1 and ADR-0251 L2 are in flight**, so types
of theirs may appear under this document; **ADR-0252, ADR-0253 and ADR-0254 are ratified and not
implemented**, so every type of theirs named here is a ratified contract and not a value in the
tree. `ReadAskOutcome`, `ReadOutcomeKind`, `AttemptKind`, `AttemptEffort.kind`, `EvidenceDigest`,
`EvidenceStanding`, `GoalInterpretation`, `GoalAttempt`, `AttemptPhase`, `AttemptState` and
`AttemptOutcome` **are** in `core/types.py`; `GoalEvidence`, `EvidenceBasis`, `StepCondition`,
`PlanInterpretation`, `StepOutputRef`, `StepVerification`, `Authorization` and
`PlanStep.depends_on`/`.when`/`.verifies`/`.resolves` are **not**.

- **`orchestration/engine.py` drives `turn.plan.steps[0]` and nothing else.** `_run_turn` reads
  `first = turn.plan.steps[0]` and makes the one `self._runner.run(state, first.id, …)` call in
  the module. Its own docstring says so in terms: *"a turn drives **at most one** step, the
  plan's first, through the already-built `StepRunner`; the rest await that stage."* **No loop
  over a plan's steps dispatches anywhere under `src/`** — every `for … in …steps` under `src/`
  filters, inspects or renders.
- **Every step but the driven one is reported as undriven and nothing more.** `_compose` passes
  `tuple(one for one in turn.plan.steps if one.id != step.step_id)` to the composing stage, and
  `composing.py` records why: *"a model told only 'here is a three-step plan' would narrate all
  three as attempted."*
- **`StepRunner.run(state, step_id, *, timeout, origin, on_ruled) -> StepDisposition`** is the
  per-step stage, in `orchestration/runner.py`. `Disposition` is closed at **seven** members
  (`core/types.py`). **Four commit a transition** — `EXECUTED`, `DENIED`,
  `AWAITING_CONFIRMATION` and `NO_CAPABLE_TOOL`, the last through `runner.py`'s
  `self._skip(state, step, SkipReason.NO_CAPABLE_TOOL)` — and **three commit nothing**:
  `AMBIGUOUS_CAPABILITY`, `INVALID_PARAMETERS` and `EGRESS_UNBINDABLE`, each documented as
  leaving the step *"`PENDING` at its stored version … terminal for the turn that met it and for
  nothing beyond it"*. As a dated observation rather than a rule, `Disposition`'s own class
  docstring counts the split the other way — *"the four that commit nothing … the three that
  do"* — which the `NO_CAPABLE_TOOL` skip contradicts; the code is what this document reads.
- **`StepExecutor._claim` is the one `→ RUNNING` claim**, built as a `StepTransition` carrying
  `execution_id`, `step_id`, `to_status`, `expected_version`, `bound_tool` and `approval_ref`,
  committed through `_commit_shielded` **before** `execute`'s retry loop reaches
  `ToolInvoker.invoke`.
- **`StepTransition` carries exactly nine fields** — the six above plus `output`, `skip_reason`
  and `failure` — and **is a command, never a row**. `planning/sqlite_store.py` has tables
  `goals`, `plans`, `executions` and `attempts` and **no transitions table**: the store persists
  the post-`apply` `ExecutionState` and nothing else. `StepTransition` appears in no module under
  `wire/` or `interfaces/`.
- **`Goal.revision` is a property**, `self.interpretation[-1].revision`, not a field.
- **`SkipReason.UNMET_DEPENDENCY` still has no producer**: it appears under `src/` only in
  `planning/execution.py`'s `_LEGAL_SKIP_REASONS` and `testing/planning.py`'s copy.
  `StepExecution.output` is written by `orchestration/executor.py` and `planning/execution.py`
  and is **read by nothing**.
- **`AttemptState.EFFECT_UNRESOLVED` has no producer** — one hit under `src/`, its own member
  definition. `AttemptState.AWAITING_AUTHORIZATION` **has** one: `engine.py`'s `ruled` closure
  commits it when a `CONFIRM` is recorded.
- **`orchestration/recovery.py` moves exactly one status**: it finds a step `RUNNING` with
  nothing executing it and commits `RUNNING → INDETERMINATE`, completing the open invocation
  claims under that step's `approval_ref` first. It touches no other status and no attempt.
- **`PROTOCOL_VERSION` is 39**, `PlanExport.schema_version` is `Literal[9]`, and the plan store's
  `_SCHEMA_VERSION` is `2`.

### The gap this closes, stated as the failure the corpus has today

**A plan with two steps drives one of them, and that is the system as ratified.** ADR-0228 §14
says so explicitly — the deferral is *"**Not** fired by a lane finding a two-step plan drives
only its first step, which is the system as ratified."* Everything ADR-0253 landed is therefore
inert: a `depends_on` nothing reads, a `when` nothing evaluates, a `resolves` nothing resolves, a
`verifies` nothing checks, and an `interpretations` tuple nothing performs. ADR-0254 landed the
coverage test a dispatch must pass and a phase-4 evaluation that runs *"Before any step of a plan
is dispatched"* — with no stage that dispatches a second step for it to run before.

**Three of #2255's acceptance rows are unreachable for one reason each.** *"First action
succeeds, dependent action has not yet run"* needs a second dispatch. *"Conditional plan spans
multiple decisions"* needs an interpretation performed between two dispatches. *"Restart during
approval"* needs a park in the **middle** of a plan, which today cannot happen because the middle
is never reached.

**And the claim is guarded against one write and not against two.** ADR-0249 §8 put the
stale-revision refusal inside `commit_transition`, so a claim against a plan targeting a
superseded understanding is refused. Nothing refuses a claim made under an attempt that has
**ended** — and an attempt ending is exactly what a cancellation is, so the guarantee #2255's
addendum asks for (*"Handle the sequence 'check revision → user cancels → action starts'"*) is
half-built.

### What this ADR is not allowed to settle

**It reconciles nothing and cancels nothing.** No lane of this decision retries a `FAILED` step
across turns, resolves an `INDETERMINATE` one, mints an idempotency key, modifies an existing
effect, cancels an attempt, decides which write wins against a dispatch, verifies against the
goal's criteria, writes an `AttemptOutcome` or writes `GoalStatus.ACHIEVED`, `BLOCKED` or
`ABANDONED`. Retry, reconciliation and modify-before-replace are **A8's**; cancellation's
semantics and three of the report's four §H.4 tests are **A9's**; verification is **A10's**. §12
enumerates each with the condition that fires it, and §13's carried Q4 rule is what keeps the
interval safe rather than merely admitted.

## Decision

### 1. The driver: one stage, one pass, four evaluations per step in one order

> **Normative.** `orchestration` gains a **plan-driving stage**: a concrete collaborator that
> walks the steps of **one** `ActionPlan` over **one** `ExecutionState`, in the order the plan's
> `steps` tuple carries them, calling **`StepRunner.run` once per step it dispatches**.
> **`StepRunner`'s behaviour is not changed**: ADR-0037 §6's *"This object disposes of one step,
> once"* and its `PENDING`-only entry bind entire, ADR-0037 §2's decide → record → read back →
> claim order is untouched, and **`StepExecutor` gains no collaborator** (ADR-0058). The one
> change either takes is §3's threaded `attempt_id`.

> **Normative.** **The walk is sequential and dispatches one step at a time.** No lane reads this
> decision as licence to dispatch two steps concurrently: ADR-0014 §7's parallel-execution
> deferral and ADR-0253 §1's clause that *"`depends_on` narrows what may be dispatched and never
> widens it, and no lane reads it as a licence to execute two steps concurrently"* both bind
> **verbatim** and are untouched.

> **Normative — position order is dependency order, and the driver computes no graph.** ADR-0253
> §1 makes every `depends_on` member name a step *"that appears **strictly earlier** in that
> plan's `steps` tuple"*, and ADR-0253 §8 refuses a plan whose conditioned step sits at or before
> the step an interpretation reads. **So a single forward pass over `steps` visits every producer
> before every consumer**, and the driver performs **no topological sort, no traversal and no
> cycle detection**. A cycle has no spelling (ADR-0253 §1), so there is nothing to detect.

> **Normative — what the driver evaluates for each step, in this order and in code.** On reaching
> a step whose stored `StepExecution.status` is `PENDING`, the driver evaluates, stopping at the
> first that refuses:
>
> 1. **The dependency rule** — ADR-0253 §2, over the stored `StepExecution` of each member of
>    `depends_on` and that step's `verifies` over its stored `output`.
> 2. **The step's conditions** — every member of `when`, by ADR-0252 §6's four tests over the
>    goal's `GoalEvidence` rows, **at this moment** and not earlier.
> 3. **The result references** — every member of `resolves`, by ADR-0253 §6's total function of
>    the `PlanStep` read from `PlanStore.get_plan` and the `ExecutionState` read from
>    `PlanStore.get_execution`.
> 4. **`StepRunner.run`, once**, with the resolved `parameters`.
>
> **Authorization coverage is not a fifth evaluation of the driver's**: ADR-0254 §13 puts the
> comparison *"at `ActionPolicy.decide`, on the concrete request, at every dispatch"*, which is
> inside step 4. The driver **reaches** that test and does not take it.

**The order is fixed rather than left to an implementation, and correctness fixes it before cost
does.** ADR-0148 §1 requires the `ActionRequest` a policy rules on to be complete — *"Nothing in
it is resolved, canonicalised, defaulted, expanded or added after `ActionPolicy.decide` has been
reached"* — and ADR-0253 §6 resolves a reference *"Before the `ActionRequest` for a step is
built"*. So reference resolution **must** precede the ruling, and the ruling is where coverage is
compared. That alone rules out any order in which coverage is taken before references are
resolved: there would be no concrete request to compare. Cost agrees: the dependency rule reads
one execution the driver already holds, the conditions read the goal's rows, resolution reads the
producing execution, and the ruling is the only step that can reach a model, a registry or the
world.

**This corrects the lane brief's ordering and not the report's.** The brief for this lane listed
the evaluations as dependency, `when`, coverage, references. Revision 1 of the report does not:
§G.2 has the driver read `verifies` at dispatch and leaves the ruling where ADR-0037 §2 puts it.
ADR-0254 §14's own enumeration — *"1. Dependency validity … 2. Arguments present or referenced …
3. Sufficiency to act … 4. Coverage"* — orders coverage last, and this section agrees with it.

> **Normative — where the plan's interpretations are performed.** The driver performs the plan's
> `interpretations` (ADR-0253 §8) at the two moments that section fixes and at no other: one
> carrying a **`record`** is performed **before the plan's first step is dispatched**; one
> carrying a **`reads`** is performed **after** its producing step is `SUCCEEDED` and its
> `verifies` holds, and **before** any step whose `when` reads its verdict is evaluated. **The
> rows an interpretation writes are the only `GoalEvidence` rows written during a walk.**

> **Normative — the driver performs no read, makes no `Planner.plan` call and opens no
> investigation round.** ADR-0251 §1's rounds are phase 2 and the walk is phase 5. **The only
> model call the walk makes is an interpretation**, whose whole input and whose output schema are
> ADR-0253 §8's, and which *"is **not** a `Planner.plan` call"*.

**That is what makes a condition's verdict at the moment of dispatch stable for the rest of the
pass, and it is the argument §2's skip rule rests on.** ADR-0252 §6 evaluates recency and every
other test *"at the moment of dispatch"*, so a step evaluated early and dispatched late could be
evaluated against rows that moved. Inside one walk they cannot: the only writer of a row during
the walk is an interpretation the plan declared, ADR-0253 §8's ordering rule puts every such
interpretation before every step conditioned on what it settles, and nothing else writes a row
because nothing else reads the world. **Between walks they can**, which is why the evaluation is
per dispatch and not per plan.

> **Normative — the driver re-evaluates, and phase 4 is not thereby moved or duplicated.**
> ADR-0254 §14's phase-4 evaluation runs once over the plan before the walk begins and is that
> decision's lane's. The driver's per-step evaluation is **the same predicates re-evaluated
> against the state as it then stands**, which is what ADR-0254 §13 requires of coverage —
> *"There is **no cached coverage verdict anywhere**"* — applied to the other three for the same
> reason. **No lane caches a dependency verdict, a condition verdict or a resolved value across
> two dispatches**, and no lane satisfies a dispatch from a verdict phase 4 took.

**A plan's later step cannot be validated before its earlier step runs, and pretending otherwise
is the one thing a phase-4-only reading would do.** Step 2's dependency on step 1 is unsatisfied
at phase 4 for every plan that has one, because step 1 has not run; its `when` over an element
step 1's output will settle is unsatisfied for the same reason. Read as a gate, phase 4 would
refuse every dependent plan there is. Read as ADR-0254 §14 writes it — *"deterministically and
over stored values alone"* — it is an evaluation over what is knowable then, and the dispatch-time
evaluation is what decides a dispatch.

### 2. The stop rule and the skip rule: one stops the walk, the other disposes of a step

> **Normative — the stop rule.** **The walk stops at the first step whose disposal leaves that
> step neither terminal nor skipped**, and every step after it in `steps` order is left
> **`PENDING`**. Five outcomes trigger it, and the driver treats them alike:
>
> - the step's dependency **fails on an `INDETERMINATE` producer** (ADR-0253 §2, §6);
> - `StepRunner` returns **`AWAITING_CONFIRMATION`** and the step is durably `AWAITING_APPROVAL`;
> - `StepRunner` returns a disposition that **commits nothing** — `AMBIGUOUS_CAPABILITY`,
>   `INVALID_PARAMETERS` or `EGRESS_UNBINDABLE` — and the step stays `PENDING` at its stored
>   version;
> - the step's own outcome is **`INDETERMINATE`** (§6);
> - the **request deadline** has no strictly positive remainder (§9).

> **Normative.** **A step the walk did not reach is `PENDING` and is never `SKIPPED` by this
> decision.** No lane sweeps the remainder of a stopped walk into `SKIPPED`, writes a
> `SkipReason` for a step nothing evaluated, or reads `PENDING` after a stopped walk as a
> terminal state.

**Stopping rather than skipping past is the whole of this rule, and the reason is that every one
of the five says the same thing: nothing has decided that the remaining steps will not run.** A
skip is a durable claim, carried in `StepExecution`, `PlanExport` and the wire, that a step was
disposed of; ADR-0014 §4 describes the `PENDING → SKIPPED` trigger as *"nothing can run it"*, and
in all five cases something still can. Three of the seven `Disposition` members say so in the
tree's own words — `EGRESS_UNBINDABLE` is *"terminal for the turn that met it and for nothing
beyond it"* — and `AWAITING_CONFIRMATION` is a question the user has not answered yet. Skipping
the remainder would convert *we stopped* into *we decided*, in a durable record, on no decision.

**And it does not continue past an independent step, which is the reading a "stop the branch"
rule most invites.** ADR-0253 §2's `INDETERMINATE` clause stops *"neither the dependent step nor
any step that depends on it, transitively"*, which leaves a step independent of the uncertain one
formally dispatchable. This decision does not dispatch it, for three reasons the corpus already
holds. **Independence is a planner's declaration and not a fact about the world**: ADR-0253 §1's
`depends_on` is what a model wrote, and a planner that omitted an edge hands the driver a false
independence at exactly the moment a real one would matter. **A second call under the first's
uncertainty compounds it**: revision 1 §G.4's own words are that *"two sequential calls have two
[unknowns], and the second is dispatched under the first's uncertainty"*. And **the user is
already being answered**: on a park, the turn returns a question, and dispatching further acts
while a question about a different act is on screen makes the answer be given in a world that
moved under it — which ADR-0148 §8 and ADR-0178 render precisely to prevent.

**The park case is also the one the attempt's own state settles.** ADR-0249 §5 derives *"A goal is
paused when its status is `ACTIVE` and its current attempt's state is `AWAITING_CLARIFICATION`,
`AWAITING_AUTHORIZATION` or `BLOCKED`"*, and ADR-0254 §14 commits `AWAITING_AUTHORIZATION` the
moment the `CONFIRM` is recorded. A paused attempt that went on dispatching would make *paused*
false of a system that is acting, in the one surface a user reads to find out whether anything is
happening.

> **Normative — the skip rule, and the moment it fires.** A step the walk **reached** and whose
> evaluation refuses it is moved **`PENDING → SKIPPED`** with **`skip_reason=UNMET_DEPENDENCY`**,
> **at the moment the walk reaches it**, in exactly three cases — all three ADR-0253's, none
> minted here:
>
> - its dependency **fails on a `FAILED` or `SKIPPED` producer** (ADR-0253 §2);
> - a member of its `when` is **not satisfied** by any row of the goal (ADR-0253 §2, §5);
> - one of its `resolves` is **unresolvable**, by any of ADR-0253 §6's six cases (ADR-0253 §6).
>
> **`SkipReason` gains no member**, and `APPROVAL_DENIED` and `NO_CAPABLE_TOOL` stay
> `StepRunner`'s alone.

> **Normative.** **`SUPERSEDED` is not written by a walk.** The only step a walk moves to
> `SKIPPED` takes `UNMET_DEPENDENCY`; §7 is the one place this decision writes `SUPERSEDED`, and
> it is written to a plan the driver has stopped driving rather than to a step it reached.

**At the moment the walk reaches it, because by then every input to the refusal is fixed and
cannot change before the walk ends.** ADR-0253 §2's rule reads the producers' stored statuses,
and every producer sits strictly earlier and has already been disposed of or has stopped the walk.
ADR-0252 §6's tests read the goal's rows, and §1 above establishes that the only rows written
during a walk are the interpretations the plan declared, every one of which ADR-0253 §8 orders
before the steps conditioned on it. ADR-0253 §6's resolution reads the producing execution's
`output`, which is written once when that step succeeds and is never rewritten. **So deferring
the skip to the end of the walk would record the same fact later, and deferring it to the end of
the attempt would leave a step `PENDING` that nothing will ever dispatch** — indistinguishable, in
the durable record, from a step the walk stopped short of, which is precisely the distinction the
stop rule above exists to keep.

**The two rules together are what makes "why did this step not run" answerable from the store
alone.** A `SKIPPED`/`UNMET_DEPENDENCY` step says *this plan's own conditions refused it*; a
`PENDING` step says *the walk did not get there*; and which it is, is decided by whether anything
was settled about the step rather than by where in the plan it sat.

### 3. The claim's second conjunct: the attempt, and not a caller-supplied revision

> **Normative.** `core/types.py`'s **`StepTransition` gains exactly one field**:
> **`attempt_id`, an `Identifier | None`, defaulting to `None`**, naming the `GoalAttempt` the
> claim is being made under. A **model validator** requires it on a transition whose `to_status`
> is **`RUNNING`** and **forbids** it on every other `to_status`, which is ADR-0039 §2's own
> shape — *"required when the status is `FAILED` or `INDETERMINATE`, and forbidden on every other
> status"* — applied to one more field.

> **Normative.** **`PlanStore.commit_transition` gains one claim condition**: a `→ RUNNING`
> transition is accepted only where the `GoalAttempt` its `attempt_id` names **exists**, belongs
> to the **same goal** as the plan the execution runs, and is in a **non-terminal
> `AttemptState`**. A claim naming no attempt, an unknown attempt, an attempt of another goal, or
> an attempt whose `state` is `CANCELLED` or `ENDED` is **refused with the error class a stale
> `expected_version` already raises** (`StaleExecutionError`), which is ADR-0249 L1's precedent
> for the revision conjunct. This is a **strengthening of an existing member** rather than a new
> one, exactly as ADR-0249 §12 classifies the first added condition.

> **Normative — how the value reaches the claim, and it is threaded rather than fetched.**
> **`StepRunner.run` and `StepRunner.resume` each gain one required keyword parameter,
> `attempt_id`, and `StepExecutor.execute` gains the same one**; each passes it through to the
> `StepTransition` its claim builds and reads it for nothing else. **The driver supplies it from
> the `GoalAttempt` it is driving under**, which is the value ADR-0249 §12 already has
> `orchestration` holding in memory from the instant the attempt is opened. **No stage fetches
> the attempt to fill it**, `StepExecutor` gains **no `PlanStore` read it does not already have
> and no collaborator** (ADR-0058), and no other parameter of either entry point moves.

> **Normative — this is not the substitution hazard ADR-0037 §2 and ADR-0253 §6 close, and the
> distinction is what the store's own refusal makes true.** Those clauses refuse a caller-supplied
> **step**, **parameter mapping** or **resolved value** — *"no caller supplies a resolved value, a
> parameter mapping or a substituted step, and no entry point of the permission stage gains a
> parameter **for one**"* — because each would let a caller change **the subject the gate rules
> on**. `attempt_id` is not a subject: it is not read into the `ActionRequest`, not shown to the
> policy, not carried into the `PermissionDecision`, not used to select a tool or fill an
> argument, and not compared against anything the caller supplied. It names a row, and **a caller
> that names the wrong row is refused rather than obeyed** — the store checks the row's goal and
> its state against values only the store holds. That is exactly `approval_ref`'s shape under
> ADR-0014 §4 and ADR-0058: the caller names the record, the store refuses a claim without one,
> and the resolution property is the path's.

> **Normative.** **The store reads the attempt inside the same indivisible step as the claim.**
> There is **no separate read of the attempt on which a decision is taken**, and no lane satisfies
> this rule by a read of the attempt taken outside the claim — ADR-0249 §8's clause for the
> revision, binding one conjunct over.

> **Normative — `StepTransition` gains no revision field, and ADR-0249 §8's refusal of one binds
> entire.** That section rules: *"**`StepTransition` gains no member for this.** The execution
> names its plan and the plan names its goal, so the store already holds every value the
> comparison needs; adding a caller-supplied revision would put the decision back in the caller's
> hands and re-open the gap the clause above closes."* **The revision conjunct is ADR-0249 §8's,
> is already ratified, and is relied on here rather than re-landed**, and no lane of this decision
> adds a revision to a transition, to a request, or to any caller-supplied value.

**This ratifies the report's §H.1 property and corrects its construction, and the correction is
the clause's own argument turned on it.** §H.1's shape is *"`StepTransition` carries the **goal
revision and the attempt id** the step is being claimed under"*, and its reason is exactly right:
*"revision 0's version was a read-then-claim, which is a time-of-check-to-time-of-use gap. The fix
is to make it not a check."* But a **caller-supplied revision** is a check with an extra step: the
caller reads the goal, copies a number, and the store compares the copy. A user act landing
between the read and the claim moves the stored revision and the copy still matches itself.
ADR-0249 §8 saw that and put the comparison where the compared value lives. So the property §H.1
wants — one write, no separate read, the store adjudicating — is bought **by the store deriving
the revision**, and a field would spend the property to buy it.

**The attempt id is a different kind of value, and that is why it is a field where the revision is
not.** What the store derives, it derives from a chain it holds: execution → plan → goal.
**Which attempt a claim is made under is not on that chain.** One goal may carry many attempts
(ADR-0249 §5, ADR-0250 §12), and `GoalAttempt.execution_ids` is appended by `commit_attempt` at
the moment an execution is opened — so a reverse lookup would work only where an earlier write
landed, would make the conjunct's strength depend on a write the driver must remember to make,
and would have the **store** choosing which attempt is claiming. The driver is the one component
that knows. **So the caller supplies the identity and the store reads the state**, which is the
division `approval_ref` already uses: ADR-0014 §4 has the caller name the decision and the store
refuse a `→ RUNNING` without one, and the `approval_ref` does not thereby become a value the
caller can stale. There is nothing here for a time-of-check-to-time-of-use gap to open on: the
caller's value is an id, and an id does not go stale.

**And the conjunct is not redundant with the revision's, which is the first objection to it.** A
cancellation of an **attempt** is not a revision of an **understanding**: it commits the attempt
to a terminal `AttemptState` and moves the goal's `revision` not at all — ADR-0249 §6 is explicit
that *"Recording an interpretation revision does not move the phase"* and §4 that an attempt
reaching a terminal state does not move the goal's status, and nothing anywhere makes ending an
attempt advance the goal's revision. So the revision conjunct alone lets a step of a cancelled
attempt claim and act. **The attempt conjunct is what makes revision 1 §H.2's closing sentence
true** — *"after an acknowledged cancellation **no later step starts**"* — for the cancellations
that end an attempt rather than revise a goal.

> **Normative — what the refused claim then causes is not decided here in full, and what is
> decided is stated.** A refused claim leaves the step **`PENDING` at its stored version** with
> **nothing invoked**, and the walk **stops** under §2's rule. **Which report the turn composes,
> whether it replans, and what a user is told** are recovery policy and are **A9's**, which is
> ADR-0249 §13's own division for a refused stale claim.

> **Normative — the four tests of revision 1 §H.4, and which of them is owed here.** **Test 3 —
> the store-level invariant in the shared `PlanStore` conformance suite — is this decision's**,
> and it is owed for **both** conjuncts: no `→ RUNNING` transition is ever accepted whose goal
> revision is not the stored one, and none whose attempt is terminal. **Tests 1, 2 and 4 —
> interleaved cancel before the claim, interleaved cancel after it, and the exhaustive two-writer
> interleaving — are A9's**, because each is stated over a cancellation whose semantics that lane
> decides. **No lane reads this decision as having established them.**

### 4. The boundary: what is already ruled, and that this decision adds only the conjunct

> **Normative.** **The committed `→ RUNNING` claim is the boundary**, and this decision states it
> rather than moves it. ADR-0148 §9 binds entire: *"Every transmission through the seam happens
> under a committed `→ RUNNING` claim on a plan step whose `approval_ref` is the authorising
> decision's id … **There is no egress outside a claimed step**."* ADR-0014 §4 binds entire: the
> claim *"must be committed before the tool is invoked"*, and *"Committing **after** invocation
> would make CAS useless"*. **The driver introduces no second boundary, no pre-claim reservation,
> no post-claim window and no reachability fact.**

> **Normative.** **The interval between the committed claim and entering `invoke` is ADR-0034
> §1's and is unchanged**: *"An attempt that ends after the claim is committed, and that nothing
> could have run under, commits `RUNNING → FAILED`, and is never retried."* **After `invoke` is
> entered the answer is ADR-0029 §4's** — `INDETERMINATE` for a side-effecting non-`NATURAL` tool
> — and ADR-0034 §1's limit binds: *"`ToolInvoker` exposes no 'the callable was reached' fact and
> this ADR introduces none"*, and **this one introduces none either**.

> **Normative.** **What this decision adds to the boundary is the attempt conjunct of §3 and
> nothing else.** No clause here changes what a claim is, when it is committed, what it carries
> besides `attempt_id`, what the executor does after it, or what any of the three intervals above
> mean. **`StepExecutor` keeps its four-collaborator construction contract** (ADR-0058), and
> ADR-0254 §13's clause that *"**No collaborator is added to `StepExecutor`**"* binds entire: a
> keyword argument threaded to the transition it already builds is not one.

> **Normative — the scope is in-process and is stated rather than overclaimed.** A stop reaches a
> walk running in the process that holds it; **there is no cross-process signal, no cancellation
> queue and no lease**. **ADR-0083 §1's** one-resident-process-per-data-directory posture is what
> makes that enough, and ADR-0244 §11's honesty is adopted in its own direction: **no caller
> assumes a call that was invoked did not leave.** ADR-0014 §7's execution-lease deferral is
> untouched.

**The posture is cited to ADR-0083 §1 deliberately, because two documents this decision is built
on cite it elsewhere.** ADR-0244 §11 attributes it to *"ADR-0043's
one-resident-process-per-data-directory posture"* and revision 1 §H.3 repeats that attribution.
ADR-0043 is *"Explicit review markers: a grounded withdrawal and a tagged proposal replace
inference"* and states nothing about processes; the rule is ADR-0083 §1's, as ADR-0074, ADR-0125
and ADR-0194 each cite it. The substance is unaffected in every one of them and no clause moves;
the citation is corrected here and filed rather than propagated.

**The honest half of this is that the conjunct bounds what starts and not what is already
running.** A claim that has committed has committed; an attempt cancelled a microsecond later
finds a tool already invoked, and the step's outcome is one of its own three — `SUCCEEDED`,
`FAILED` or `INDETERMINATE` — and **never** `SKIPPED`. That is revision 1 §H.2's second bullet,
and it is a statement about the world rather than about this design: ADR-0029 §4 is where the
system says it cannot know how far a call got, and no conjunct on a store write changes that.

### 5. Mid-plan park: the walk stops, and the resume re-enters from the stored execution

> **Normative.** A step whose ruling is `CONFIRM` parks exactly as ADR-0037 §4 already parks one —
> the decision recorded, the step committed `PENDING → AWAITING_APPROVAL` carrying `bound_tool`,
> the disposition `AWAITING_CONFIRMATION` carrying the decision id — and the attempt's move to
> `AttemptState.AWAITING_AUTHORIZATION` is **ADR-0249's lane's**, which ADR-0254 §14 already
> relies on. **This decision adds no second asking mechanism, no second writer of that state, no
> park queue and no `core` type for a parked step.**

> **Normative.** **The walk stops at the park** (§2), and **nothing of that plan is dispatched
> again until the park is answered**. No step independent of the parked one is dispatched, no
> second `CONFIRM` is put in one turn, and no lane collects several parks into one prompt.

> **Normative — resumption drives that exact step, and the driver re-enters after it.**
> `StepRunner.resume` disposes of the parked step on ADR-0037 §4's unchanged sequence. Where it
> returns `EXECUTED`, the driver **resumes the walk**; where it returns `DENIED`, the step is
> `SKIPPED`/`APPROVAL_DENIED` and the driver **resumes the walk**, which will then dispose of
> that step's dependents by §2's skip rule. **The resumed claim carries the same conjunct** — it
> is a `→ RUNNING` transition and §3 binds it — so a park answered after the goal moved on, or
> after the attempt ended, is refused and nothing is invoked.

> **Normative — the driver holds no cursor, and re-entry is computed from durable state.** The
> position the walk resumes at is **the first step of the plan whose stored
> `StepExecution.status` is `PENDING`**, read from `PlanStore.get_execution`. **No lane carries a
> step index across a park, a turn or a restart, and no lane persists one.**

**A cursor would be a second authority that can disagree with the executions, which is the defect
ADR-0014 §3 splits `ExecutionState` out of `ActionPlan` to avoid.** That section's whole argument
is that *"the snapshot must carry everything a restarted executor needs to **not redo work**"*,
and it refuses a plan-level status field for the same reason — *"it is derivable from the steps,
and storing it would create a second source of truth that can disagree with them"*. A resume
position is derivable from the steps in exactly that sense; storing one would create a value a
restart could lose, a park could stale and a replan could point past the end of a different plan.

> **Normative — a mid-plan park survives a restart through the mechanism that already exists.**
> ADR-0052 §1's `pending_confirmations()` enumerates `active_executions()` and recovers each
> `AWAITING_APPROVAL` step's still-pending `CONFIRM` by its `(execution_id, step_id)` binding
> (ADR-0044 §3), re-minting a continuation token. **A step in the middle of a plan is recovered by
> that enumeration on exactly the same terms as a first step**, because the enumeration is over
> steps and not over positions, and **this decision adds no recovery path, no second store read
> and no `Engine` member**. ADR-0052 §2's idempotence and its `_parked` reconciliation bind
> unchanged.

> **Normative — #257, answered for the driver and deferred in its remaining half.** A step the
> walk finds **`AWAITING_APPROVAL`** for which `AuditTrail.pending_confirmation(execution_id,
> step_id)` returns **`None`** — the binding is already resolved, so ADR-0044 §2(b) has decided it
> and the ruling did not reach the step — is **left exactly as it stands**: the walk **stops**,
> nothing is claimed, nothing is skipped, and no ruling is authored. **The driver never re-asks
> and never re-rules a resolved binding**, which is ADR-0052 §1's own posture — *"A binding
> already resolved returns `None` … and is skipped — the `#257` hazard §2b closes is not
> re-presented"* — read at the driving seam instead of the recovery seam.

**Leaving it is the only disposal that asserts nothing false, and it is cheap because ADR-0044 §3
already landed the query ADR-0037's Consequences called missing.** That passage named two
closures, *"carrying `approval_ref` on the `→ AWAITING_APPROVAL` transition, or a by-step query on
`AuditTrail`"*, and said both were *"changes to contracts this change does not own"*. The second
has since landed and is what `pending_confirmations` reads. So the driver can **see** a stranded
step; what it still cannot do is finish it, because ADR-0036 §2's unique index on `resolves` and
ADR-0044 §2(b)'s per-binding rule make the confirmation unanswerable a second time. **Skipping it
would record a disposition nobody decided; claiming it would act on a ruling the trail says is
spent.** #257's remaining half is the atomicity of the ruling and the transition, which needs a
`PlanStore` that accepts more than one transition in a commit — a contract change with a much
wider blast radius, filed there and **not taken here** (§12).

### 6. Mid-plan `INDETERMINATE`: the branch stops, the walk stops, and the attempt says so

> **Normative.** A step whose own outcome is **`INDETERMINATE`** stops the walk (§2). **Its
> dependents, transitively, stay `PENDING`** — ADR-0253 §2 binds verbatim: *"neither the dependent
> step nor any step that depends on it, transitively, is dispatched, skipped or resolved, and each
> stays `PENDING` until the `INDETERMINATE` step is resolved explicitly."* **Every other step the
> walk did not reach stays `PENDING` too**, under §2's stop rule and for §2's reasons.

> **Normative.** **No step of a plan carrying an `INDETERMINATE` step is ever moved to `SKIPPED`
> by this decision — not with `UNMET_DEPENDENCY`, not with `SUPERSEDED`, and not on a later
> turn.** ADR-0014 §4's reason is the whole of it and is quoted rather than restated:
> *"Automatically retrying it would risk acting twice; automatically failing it would risk
> reporting a completed action as failed. So recovery does neither."* A skip records that the
> producer did not act, which is exactly the half of the ambiguity that state refuses to pick.
> **This rule overrides §7's supersession clause** where the two would meet: a plan superseded
> after driving whose walk stopped on an `INDETERMINATE` step leaves that step's branch `PENDING`
> and moves no step of it to `SKIPPED`/`SUPERSEDED`.

> **Normative — the driver is `AttemptState.EFFECT_UNRESOLVED`'s one producer, for a step it
> drove.** The attempt's `state` is committed `EFFECT_UNRESOLVED` through `PlanStore.commit_attempt`
> at the instant a step of the plan it is driving is recorded `INDETERMINATE`, in the same turn
> and before the turn composes. `EFFECT_UNRESOLVED` is a **non-terminal** member (ADR-0249 §5), so
> a later claim of that attempt is **not** refused by §3's conjunct on that ground alone.

> **Normative.** **Nothing else writes `EFFECT_UNRESOLVED` under this decision.** In particular
> the startup recovery scan does not: it moves a stranded step `RUNNING → INDETERMINATE`
> (ADR-0014 §4) and touches no attempt today, and **whether it should is A8's**, together with
> everything else about resolving an `INDETERMINATE` step. **No lane infers the state from a
> step's status at read time** — ADR-0249 §6's writer clause binds, and a derived state would be
> the second authority ADR-0249 §5 refuses for *paused*.

**Naming a producer here rather than leaving the member unwritten is what stops the state being a
vocabulary nobody reaches.** ADR-0249 §5 minted `EFFECT_UNRESOLVED` and wrote no producer; today
it appears under `src/` exactly once, in its own definition. The driver is the first component in
this system that can hold the fact the member states — *this attempt has an effect it cannot
account for* — at the instant it becomes true, with the attempt in hand and its version known.
Deferring the write to A8 would mean the attempt sat in `RUNNING` through the composing call, and
the turn would report an uncertain effect while the durable record said the attempt was working.

**And it is committed before composing rather than after, because composing is what reads it.**
ADR-0251 §6 rules that *"**Composing and verification are not gated on the attempt's allowance at
all**"* and §7 gives the composing stage what it is told; a state written after the answer was
composed is a state the answer could not mention.

> **Normative — the driver reconciles nothing.** It performs no reconciliation call, mints no
> idempotency key, retries no step across turns and resolves no `INDETERMINATE` step. **A8 takes
> all four**, on ADR-0014 §7's own deferral, and §12 names it.

### 7. Replan after partial execution: the executions are kept, and at-most-once across plans is not bought here

> **Normative.** **A plan superseded *after* it was driven keeps everything it recorded.** Its
> `ExecutionState`s are not deleted, rewound, re-opened or re-derived; `start_execution` is not
> called on it again; the outputs of its `SUCCEEDED` steps stay exactly where ADR-0014 §3 puts
> them; and `GoalAttempt.execution_ids` names every execution the attempt drove, superseded or
> not, by ADR-0249 §12's append-only rule. **No lane deletes or rewrites an execution to make a
> replan tidy.**

> **Normative — ADR-0228 §5's not-driven rule is extended to the after-driving case.** That
> section rules *"A superseded plan **drives nothing**"* of a plan superseded before anything was
> driven. **A plan superseded after driving drives nothing further**: the driver dispatches no
> further step of it, and its still-`PENDING` steps are moved **`PENDING → SKIPPED` with
> `skip_reason=SUPERSEDED`** — ADR-0014 §4's own row, taken for the case it was written for.
> **§6's rule overrides this one** where a branch is stopped behind an `INDETERMINATE` step.

> **Normative — one plan is driven per walk, and it is the plan the turn holds.** The driver is
> handed one `ActionPlan` and one `ExecutionState` and walks that plan's steps. **It never
> dispatches a step of a plan it was not handed**, never merges two plans' steps, and never
> resumes a walk over a plan a later plan supersedes.

> **Normative — a plan whose `targets_revision` is not the goal's current revision is not driven,
> and that refusal is ADR-0249 §8's.** The driver adds no second check of it: the claim is
> refused inside `commit_transition` where the compared value lives, and §3's stop applies.

> **Normative — the driver enforces at-most-once within one execution and nothing wider, and this
> decision states the limit rather than claiming the property.** Within one `ExecutionState`, a
> step already `RUNNING`, `SUCCEEDED`, `FAILED`, `SKIPPED` or `INDETERMINATE` is **never
> re-dispatched by the walk**, which is `StepRunner`'s existing guard — ADR-0037 §6's *"`run`
> enters only at `PENDING`"* — relied on rather than re-implemented. **Across two plans of one
> goal, nothing in this system prevents an effect being performed twice**, and no clause here
> creates such a prevention.

**This corrects revision 1 §K.2 step 6 against the tree, and the correction is that the record it
names does not exist.** That step reads *"the driver refuses to plan or drive a step whose effect
the goal records as completed"*. **A goal records no completed effect.** What the store holds is a
`StepExecution` whose `status` is `SUCCEEDED` and whose `output` is a `JsonValue`, keyed on a
`step_id` that a **re-plan mints afresh** — ADR-0253 §8's own reason for refusing a step id as a
durable declaration, *"A re-plan mints new step ids, so a fresh reading of the same proposition in
a later plan would carry a different declaration"*, applies identically here. So *the same
effect* has no name: two plans that both book a campsite carry two step ids, two capabilities that
may be spelled the same, and two parameter mappings that may or may not be equal, and nothing in
`Goal`, `GoalAttempt`, `ActionPlan` or `ExecutionState` says they are one act. A driver that
compared capability and parameters would be inventing an identity nobody declared, and would
refuse a legitimate second booking of two different nights as readily as it refused a duplicate.

**ADR-0253 §5 already says this in terms, and this decision does not reach past it.** That section
rules: *"**Nothing in this decision makes an act at-most-once**, and no lane reads a condition as
if it did … Making an intended effect happen at most once is a different mechanism entirely — it
is the idempotency key and the `INDETERMINATE` reconciliation ADR-0014 §7 defers and **A8**
takes."* The driver is not that mechanism either, and saying so here is cheaper than discovering
it in A8.

> **Normative — the two routes that would buy the property are named rather than opened.** Making
> a replan not redo a completed effect needs **either** an idempotency key the tool dedupes
> against — **A8's**, on ADR-0014 §7's own deferral — **or** the planner being able to see what
> already ran, which needs a projection of the attempt's executions into the planner's input and
> is a widening of `GoalBrief` that **ADR-0253 §10 declines to take** (*"Whether a brief ever
> renders an element's applicability is not decided here"*, and it renders no execution at all).
> **Neither is taken here**, and §12 carries both with their triggers.

**What the goal does preserve is progress, which is the requirement #2255 actually states.**
*"Preserve the real booking"* and *"preserve progress"* are requirements about **not discarding
what happened**, and every clause of this section is that: the executions stay, the outputs stay,
the attempt's references stay, and the superseded plan stays in the store as the auditable record
ADR-0014 §2 makes it. What they are not is a requirement that the system detect a repeat, which is
a different mechanism with a different owner.

### 8. `verifies` is evaluated where it is read, and it is never the verification A10 lands

> **Normative.** The driver evaluates a step's **`verifies`** predicate (ADR-0253 §4) at exactly
> the two places ADR-0253 reads it, over that step's own stored `output`, mechanically and never
> by a model:
>
> - as the **second conjunct of the dependency rule** (ADR-0253 §2), when a dependent step is
>   evaluated;
> - as the **gate on an interpretation's `reads` input** (ADR-0253 §8), when an interpretation
>   over that step's output is about to be performed.

> **Normative.** **A `verifies` that no dependency and no interpretation reads is evaluated by
> nothing and imposes nothing**, and **this decision mints no durable record of a `verifies`
> result**: no field on `StepExecution`, no field on `StepTransition`, no evidence row, no log
> line. ADR-0253 §6's own ground for declining a field binds — *"a field with no consumer is
> surface"* — and the consumers are exactly the two above.

> **Normative — this is not the verification A10 lands and the two are never conflated.**
> ADR-0253 §4's clause binds entire: `verifies` *"is about **one step's own output**"*, where
> **verification against the goal's criteria** — *"whether the requested outcome was reached, with
> strength proportional to consequence, and the producer of `GoalStatus.ACHIEVED`"* — is A10's.
> **Nothing in this decision writes `GoalStatus.ACHIEVED`, `BLOCKED` or `ABANDONED`, and nothing
> writes an `AttemptOutcome`.** This is the owner's correction 2 kept where ADR-0253 §4 put it.

**Evaluating it only where it is read is a containment and not an economy, and the alternative is
a record nobody ruled on.** A driver that evaluated `verifies` on every succeeded step would hold
a boolean it had nowhere to put: writing it to `StepExecution` widens a durable, exported,
wire-carried type for a value ADR-0253 §10 does not name; discarding it computes and throws away;
and rendering it would put a predicate's verdict in front of a user as if it were verification,
which is exactly the conflation ADR-0253 §4 mints the field's scope to prevent. **A `verifies` a
plan declared on a terminal step is inert rather than unsafe**: the step has already succeeded,
nothing depends on it, and no act follows — so nothing fails open.

### 9. The deadline: one clock the driver reads, and what a walk charges

> **Normative.** **ADR-0042 §3's per-request deadline is attached here, and it is the driver's.**
> The `timeout` an adapter supplies to `converse` or `resume` is the **whole request's** budget.
> The driver reads the injected clock **once**, at the instant it begins the walk, to fix the
> deadline, and passes each `StepRunner.run` call the **remaining** duration rather than the whole
> figure. **No lane passes the adapter's figure unchanged to more than one step.**

> **Normative — it gates starting and never cancels what is running.** Immediately before it
> begins a step's disposal, the driver reads the injected clock and computes the remainder. Where
> the remainder is **not strictly positive** it **starts no further step** and the walk stops
> (§2). **A step already begun runs to its own completion**, which is ADR-0228 §4's posture in its
> own words — *"a planner call already begun runs to its own completion, and a turn's total
> duration may therefore exceed its budget"* — one level over. **The figure passed to
> `StepRunner` is therefore always strictly positive**, which ADR-0029 §4 requires: *"a zero or
> negative duration is refused rather than treated as an instantly-expired deadline"*.

> **Normative.** **A step the deadline stopped is `PENDING` and is never `SKIPPED`** (§2), and the
> remainder is never rounded up, clamped to a minimum, borrowed from a later turn or topped up.

> **Normative — three clocks, and the driver reads exactly one.** ADR-0042 §3's per-request
> deadline bounds **one user's wait** and is this section's. **ADR-0251 §5's working allowance
> bounds one attempt's consumption across turns and does not gate execution**: its gate is
> §4(h)'s investigation gate, which admits **rounds of investigation** in phase 2, and ADR-0251
> §6 rules that *"**Composing and verification are not gated on the attempt's allowance at all**"*
> — **execution is not gated on it either**, and the driver takes no check against
> `AttemptEffort`, admits no step on the ground that the allowance has room, and refuses none on
> the ground that it does not. **ADR-0228 §4's PT20S planning budget is the planner's** and is not
> read here.

> **Normative — what a walk charges, and to what.** Every working interval a walk consumes
> **accumulates into `AttemptEffort.working`** like every other working interval, which is
> ADR-0251 §6's own clause applied rather than extended, and it reaches the ledger through the
> `commit_attempt` route ADR-0249 §12 already makes the attempt's only mutation. **A walk advances
> `AttemptEffort.planner_calls` by nothing**, because it makes no `Planner.plan` call. **An
> interpretation call the plan declares is charged the same way**: ADR-0253 §8 rules it outside
> ADR-0251 §5's planner-call allowance and outside ADR-0228 §3's bound, and *"What bounds the
> number of interpretation calls a turn makes is the plan"*, which declares at most
> `MAX_INTERPRETATION_STEPS` of them.

**The two quantities are kept apart for ADR-0251 §5's own stated reason, one level over.** That
section declines to re-key ADR-0228 §4's budget on the attempt because *"an attempt **spans
turns**"* and *"the honest reading is that ADR-0228 §4 measures **one user's wait** and the
attempt's allowance measures **one attempt's consumption**, and that these are two quantities with
two jobs."* A driver gated on the attempt's working allowance would refuse to dispatch the second
step of a plan on the third turn of a long conversation, having spent the allowance on
investigation two turns earlier — and would refuse it silently, with a durable act half-performed.
**What bounds a walk is the request the user is waiting on**; what bounds investigation is the
attempt.

> **Normative — no figure of this section is configurable and none is minted here.** The deadline
> is the caller's budget (ADR-0029 §4, ADR-0042 §3), **no `Settings` field is added**, no
> per-step minimum is declared, and no deployment flag is read.

### 10. The writer clauses

> **Normative.** **The driver stamps no `AttemptPhase`.** It receives the attempt at
> `AttemptPhase.EXECUTE`, which ADR-0254 §14 stamps when phase 4's checks pass, and leaves it
> there. **Who stamps `VERIFY` is A10's**, and no lane of this decision stamps it.

> **Normative — the mechanism by which an attempt re-enters an earlier phase, settling the
> deferral ADR-0253 §9 and ADR-0254 §19 reserve here: there is none, and this decision mints
> none.** `AttemptPhase` is a **high-water mark and not a cursor**. A later turn of the same
> attempt that plans again does that work with the attempt standing where it stands; **no
> implementation moves a phase backwards, re-stamps a phase the attempt has left, or reads the
> phase as naming the work a turn is about to do.** ADR-0249 §6 binds verbatim — *"Within one
> attempt, `phase` **advances in that order and never moves backwards**"* — and so does §12's
> *"an attempt records its position, not its itinerary."*

**Declining the mechanism is the decision, and the alternative is a field that would have to mean
two things.** ADR-0253 §9 asks that *"An unexpected finding returns the work to an earlier phase
rather than improvising in this one"*, and it answers itself in the next clause: *"A plan **may
express** the alternative, so that the answer to an unexpected verdict is a branch the plan
already declared rather than a model asked at dispatch what to do next."* **The work returning is
a property of the plan, not a transition on the attempt.** An attempt whose phase could move
backwards would make *the phases an attempt has passed are exactly those at or before its current
one* (ADR-0249 §12) false, and that derivation is the whole reason ADR-0249 keeps no per-phase
event log. Where a turn genuinely needs to record that it re-understood, the mechanism that exists
is the goal's **interpretation revision** (ADR-0249 §1) — appended, provenanced and monotone — and
ADR-0249 §6 already rules that recording one *"does not move the phase"*.

> **Normative.** **Every step outcome the driver records comes from a typed result, and no model
> output decides whether to proceed.** The driver writes a `StepStatus` and a `SkipReason` from
> the predicates §§1–2 name and from `StepRunner`'s `Disposition`, and from nothing else. **No
> model is asked whether to dispatch a step, whether to skip one, whether to stop the walk,
> whether a dependency is satisfied or whether a condition holds** — ADR-0249 §7's asymmetry binds
> by name: *"A model may never clear a permission, a coverage test, a prerequisite or a
> **dependency**."*

> **Normative — the one model output a walk reads, and what it may do.** An interpretation returns
> **one member of `InterpretationVerdict`** (ADR-0253 §8). What that member does is **what the
> plan declared before the walk began** (ADR-0253 §9): it can enable a branch the plan already
> carries and it can enable nothing else. **It never stops the walk, never skips a step, never
> selects a capability, never supplies an argument and never clears a check.** ADR-0254 §14's
> optional phase-4 intent-match assessment is advisory in one direction only and binds unchanged:
> it *"may raise a question and it may never clear a check, a prerequisite, a dependency, a
> sufficiency test or a coverage test"*.

> **Normative.** **No model writes an id, a resolved value, a `StepStatus`, a `SkipReason`, an
> `AttemptState`, an `AttemptPhase`, an `AttemptOutcome`, a `GoalStatus` or an evidence row's
> field**, and **no identifier of any kind is rendered to a model by the driver and none is
> accepted from one** (ADR-0228 §8). The driver renders no plan, no step, no execution, no
> `SkipReason` and no verdict to a log: ADR-0004 §5's rule that Tier 0/1 data must never be logged
> binds unchanged.

> **Normative.** **The driver edits no plan.** ADR-0253 §10's four-field clause is untouched:
> `supersedes`, `targets_revision` and each `StepCondition.about` and `PlanInterpretation.settles`
> are the fields another component sets, all four at the `Planner.plan` seam's return, and **the
> driver sets none of them**. A resolved reference is placed in the `parameters` the request
> carries and is **never written back into the stored `PlanStep`** — ADR-0014 §2's frozen plan
> binds, and a plan that recorded its own resolutions would stop being the record of a decision
> and become a record of a run.

### 11. The `core` surface, the wire, the stored shapes, and the export

> **Normative — what `core/types.py` gains.** **One field**: `StepTransition.attempt_id`, an
> `Identifier | None` defaulting to `None`, with the model validator §3 states. **Nothing else.**
> No new model, no new enumeration, no new constant, and no widening of `StepExecution`,
> `ExecutionState`, `ActionPlan`, `PlanStep`, `GoalAttempt` or `Goal`.

> **Normative — this is a BREAKING contract change under golden rule 5**, and it is breaking for
> the Protocol rather than for the constructor. `StepRunner` and `StepExecutor` are concrete
> `orchestration` classes and **not** Protocols, so §3's threaded keyword changes no contract
> surface at all. `PlanStore`'s signatures do **not** move and `PlanStore` gains **no member**;
> what changes is what a conforming implementation must
> **refuse** — §3 adds one conjunct to `commit_transition`, which is a **strengthening of an
> existing member**, exactly as ADR-0249 §12 classifies the first one. **The existing `PlanStore`
> conformance suite and the canonical fake in `ai_assistant.testing` gain the new obligation in
> the same change that adds it** (`CONTRIBUTING.md` → "Adding a Protocol": *"The triad is what a
> Protocol *change* is measured against too"*). **No new Protocol is created**, so no new
> conformance suite and no new canonical fake is owed.

> **Normative — `PROTOCOL_VERSION` does not move for this, and the reason is read off the tree
> rather than assumed.** `StepTransition` is a **command to `PlanStore`** and crosses no frame: as
> a dated observation at `b1d265c1`, it is named in `orchestration/`, `planning/`, `core/` and
> `testing/` and in **no module under `wire/` or `interfaces/`**, and `PlanStore` is not on the
> promoted surface. ADR-0124 §9's second limb is therefore not reached — no value one peer emits
> becomes invalid for the other. **A lane that finds the tree disagrees moves the version by
> exactly one in the same change and adds `wire/envelope.py`'s log entry naming this ADR**, and
> **no integer is fixed here**: the figure is the tree's, and it reads **39** at `b1d265c1`.

> **Normative — `PlanExport.schema_version` does not move, and no migration is owed.**
> `PlanExport` carries `tuple[ExecutionState, ...]` and **not** `StepTransition`, which the plan
> store persists nowhere: as a dated observation at `b1d265c1`, `planning/sqlite_store.py` holds
> `goals`, `plans`, `executions` and `attempts` and no transitions table, and a
> `commit_transition` rewrites the post-`apply` `ExecutionState`. **So no stored row changes
> shape, the plan store's `schema_version` stays where it is, and ADR-0049 §1's loud refusal is
> not reached.** As dated observations, the export reads `Literal[9]` and the store's
> `_SCHEMA_VERSION` reads `2`.

> **Normative — nothing else under `wire/` changes.** The connect exchange gains no member, no
> frame's encoding changes, no `FrameKind` is added, no codec entry is registered, the error
> mapping is untouched, the promoted method set does not move, and no gateway route is added.
> **No `Settings` field is added and no figure of this decision is configurable.**

> **Normative — retention, deletion and export are untouched, and no new durable record is
> minted.** Every value this decision writes rides an `ExecutionState` or a `GoalAttempt` the plan
> store already holds, so ADR-0014 §5's deletion obligation and its live-step refusal, ADR-0249
> §12's `delete_goal` cascade and its extension to attempts, and ADR-0014 §5's export closure rule
> all bind exactly as they stand. **No lane adds a retention rule, a sweep, an expiry or a second
> store.**

> **Normative — the engine's single-step path is retired, and it is replaced rather than
> supplemented.** `orchestration/engine.py`'s `first = turn.plan.steps[0]` drive and the two
> `turn.plan.steps[0]` reads in its confirmation assembly are **removed** in the lane that lands
> the driver. **No lane leaves both paths in the tree**, and no flag, setting or capability
> selects between them: two drives over one plan is the lost-update ADR-0014 §5's
> compare-and-swap exists to make detectable, arrived at deliberately.

> **Normative.** **The composing stage's `undriven` argument keeps its meaning and gains no
> member.** After a walk it is the steps the walk left `PENDING` and the steps it skipped, which
> is what it already is; **no lane reads this decision as widening what composing is told.** What
> composing is told about a stopped walk is **A9's** report and **A10's** verification, and this
> decision adds neither.

### 12. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling, and
> each carries the condition that fires it.

- **Cancellation's semantics** — what a user's cancellation is, which write wins against a
  dispatch, what an `AttemptTransition` to `CANCELLED` requires, and **revision 1 §H.4's tests 1,
  2 and 4**. **A9.** §3 lands the conjunct a cancellation bites through and test 3 that pins it;
  everything about the act that ends an attempt is A9's. Fired by this ADR landing.
- **What a refused claim causes at the user's surface** — the report, the replan, whether the turn
  composes without acting. **A9**, which is ADR-0249 §13's own division. §2 and §3 fix the durable
  state and nothing about the reply.
- **Retry across turns, reconciliation, idempotency keys, modify-before-replace, and how an
  `INDETERMINATE` step is resolved.** **A8**, which takes ADR-0014 §7's deferral. §6 stops the
  branch and writes the attempt's state; it resolves nothing.
- **Whether the startup recovery scan writes `EFFECT_UNRESOLVED` on the attempt of a step it
  found `RUNNING`.** **A8.** §6 gives the state one producer — the driver, for a step it drove —
  and the scan runs outside a turn with no attempt in hand. Fired by the lane that gives the scan
  an attempt to write to.
- **Verification against the goal's criteria, strength proportional to consequence, which
  `AttemptOutcome` an attempt earns, and the producer of `GoalStatus.ACHIEVED`.** **A10.** §8
  fixes that `verifies` is not it.
- **`GoalStatus.BLOCKED`'s producer.** **A3**, as ADR-0249 §4 and ADR-0250 §12 reserve it. A walk
  that stops writes no `GoalStatus` at all.
- **At-most-once for an effect across two plans of one goal.** **Not decided**, and §7 states the
  limit rather than claiming the property. Fired by **either** A8's idempotency key **or** a
  decision that projects an attempt's executions into the planner's input, which is a `GoalBrief`
  widening ADR-0253 §10 declines and which would carry its own containment argument.
- **#257's remaining half — making the ruling and the transition atomic.** **Not decided.** §5
  answers what the driver does when it meets a stranded step, using the by-step query ADR-0044 §3
  landed. Making the pair atomic needs a `PlanStore` that accepts more than one transition in a
  commit, which #257 itself calls *"a contract change with a much wider blast radius, and arguably
  the wrong shape for a store whose whole write API is a single compare-and-swap."* Fired by an
  ADR that takes it.
- **Parallel execution of two steps, and the leases, in-process synchronisation and recovery it
  would need.** ADR-0014 §7's second half and ADR-0253 §1's clause, **untouched** (§1). Fired by a
  decision that takes it.
- **A driver that walks a plan's steps outside a turn** — a background or scheduled drive — and
  how an authority opened there reaches the user (ADR-0254 §19). **Not decided.** Every walk this
  decision describes runs inside a turn, on a `timeout` an adapter supplied (§9), and the park it
  produces is offered on that turn's `TurnOutcome`. **No lane reads this decision as licence to
  drive outside a turn.** Fired by a decision that states the deadline, the announcement and the
  cancellation posture for one.
- **Whether a second `CONFIRM` of one turn may ever be put**, so that a walk could park two steps
  and ask about both. **Not decided**, and §5 forbids it today. Fired by a decision that gives the
  façade a park queue and states what an answer to one of two parks means for the other.
- **A bound on how many steps one walk may dispatch.** **Not decided**, and ADR-0253 §8's clause
  that *"`ActionPlan.steps` is **not** bounded by this decision"* binds. A step is selected, ruled
  on and claimed one at a time, so a long plan is expensive in a way the corpus already gates
  (ADR-0004 §7, ADR-0194 §3) and bounded in wall-clock by §9. Fired by a consumer that needs one.
- **A per-phase event log for an attempt.** ADR-0249 §13's entry, untouched; §10's high-water-mark
  clause is what makes it unnecessary rather than what forecloses it. Fired by a lane that needs
  the timings and carries its own retention and export obligations.

### 13. Q4's rule, carried and not discharged

> **Normative.** **No consequential capability is wired into a production deployment until the
> verification, uncertain-outcome and cancellation guarantees for its class are implemented and
> demonstrated.** A milestone may demonstrate dependent execution against controlled integrations
> with no such capability wired; **wiring one is what this rule binds.**

> **Normative.** **The lanes of this decision wire no consequential capability**, register no
> booking integration, and enable nothing in a production deployment. §15's M33 arms are stated
> over controlled fakes for exactly that reason.

This is the owner's ruling of 2026-09-12 (#2255) carried in the words ADR-0253 §3 and ADR-0254 §17
already carry it — *"A5, A6 and A7 each carry it, and A8, A9 and A10 discharge it"* — and **this
is the third and last carrying**. What it buys here is sharper than in either of the first two,
because this is the decision that makes a dependent plan actually dispatch: the interval in which
a plan can express a dependency, the system can walk it, and A8's reconciliation and A9's
cancellation are not yet in is an interval with **no real consequential integration in it**, rather
than one whose safety rests on nobody having wired one yet. ADR-0188's gate on a record existing
and ADR-0236's fail-closed on a missing declaration are the corpus's own shape for this.

### 14. The lane cut

> **Normative.** This decision is implemented in **two lanes**, in this order.

- **L1 — the conjunct.** `core/types.py`'s one field and its validator; `commit_transition`'s
  added claim condition in `InMemoryPlanStore` and `SqlitePlanStore`; the shared `PlanStore`
  conformance suite arm (§3's test 3) and the canonical fake in `ai_assistant.testing`; and the
  `wire/envelope.py` log entry and version bump **only if** the tree contradicts §11's dated
  observation; and §3's threading — the `attempt_id` keyword on `StepRunner.run`,
  `StepRunner.resume` and `StepExecutor.execute`, supplied by `engine.py`'s existing single-step
  drive from the `GoalAttempt` it already holds. It **drives nothing** and changes no behaviour of
  a turn: the one `→ RUNNING` claim in the tree is `StepExecutor._claim`, and after L1 it carries
  the attempt the engine opened.
- **L2 — the driver.** The plan-driving stage in `orchestration/`, the walk, §1's four
  evaluations, §2's stop and skip rules, §5's park and re-entry, §6's `EFFECT_UNRESOLVED` commit,
  §7's supersession skip, §9's deadline, and the retirement of `engine.py`'s single-step path.
  **It adds no `core` type and no field**, both being L1's.

> **Normative — L2 lands after ADR-0253's L1 and L2 and after ADR-0254's Lane 1 and Lane 2.** The
> walk reads `depends_on`, `when`, `resolves`, `verifies` and `interpretations`, which ADR-0253
> has decided and no lane has implemented; it reaches the coverage comparison, which ADR-0254's
> Lane 1 lands in the policy and Lane 2 reaches at phase 4; and §1's conditions are evaluated by
> ADR-0252 §6's tests over `GoalEvidence` rows, which ADR-0252's own lane mints. **A lane that
> minted a placeholder for any of them would be the *"two carriers for one fact"* defect ADR-0251
> §3 names**, so the ordering is a dependency rather than a preference. **L1 depends on none of
> them** — `GoalAttempt` and `AttemptState` are in the tree — and may land first.

### 15. The arms this decision owes: thin in M33, full in M34

> **Normative — what M33 demonstrates and what M34 owes, and the division is the owner's Q4
> ruling applied rather than invented.** **M33 demonstrates dependent execution on controlled
> fakes**: the arms 1–9 below, every one over `ai_assistant.testing`'s canonical fakes with no
> consequential integration wired. **M34 owes arms 10–14**, and no lane reads an M33 arm as having
> established one of them.

**Thin — M33, on controlled fakes.**

1. **ADR-0253 §14's dynamic plan, driven end to end** — the arm #2255's *"Conditional plan spans
   multiple decisions"* is owed in its own shape, and ADR-0253 asserted it as predicates over
   constructed values because no lane of that decision drives. Here it is **driven**: one goal
   carrying the condition element, one plan with step 1 (`refresh_forecast`), interpretation 1
   (`reads` step 1's output at `"summary"`, `settles` that element) and step 2 (`book_campsite`,
   `when` on the `INTERPRETATION` basis requiring `QUALIFIES`). The arm asserts that the driver
   dispatches step 1, performs interpretation 1 **after** step 1 is `SUCCEEDED` and its `verifies`
   holds and **before** step 2 is evaluated, writes the row, and dispatches step 2; and that on
   `DOES_NOT_QUALIFY` and on `INCONCLUSIVE` step 2 is `SKIPPED`/`UNMET_DEPENDENCY` and **the plan
   is intact and unreplanned**.
2. **"First action succeeds, dependent action has not yet run"** — the same plan, asserted at the
   moment between the two dispatches: step 1 `SUCCEEDED` with its output stored, the interpretation
   row written, step 2 still `PENDING`, and **the `ActionRequest` for step 2 not yet built**.
3. **`UNMET_DEPENDENCY` gets its first producer**, parameterized over the three cases §2's skip
   rule names: a `FAILED` producer, a `SKIPPED` producer, an unsatisfied `when`, and each of
   ADR-0253 §6's six unresolvable-reference cases. Each asserts the step is `SKIPPED` with that
   reason **at the moment the walk reached it** and that no request was built.
4. **A result reference reaches the ruling as itself** — a two-step plan where step 2's
   `resolves` fills a parameter from step 1's output; the arm asserts the resolved value is in the
   `ActionRequest.parameters` **before `ActionPolicy.decide` is reached** (ADR-0148 §1) and in the
   digest, and that no caller supplied it.
5. **A stale-revision claim is refused through the driver** — the goal's revision advances between
   step 1's success and step 2's claim; `commit_transition` refuses, **`ToolInvoker` is never
   entered** (a fake that records entry), step 2 is `PENDING` at its stored version, and the walk
   stops.
6. **A terminal-attempt claim is refused** — the attempt is committed `ENDED` between step 1's
   success and step 2's claim; same four assertions. A paired arm asserts the **goal's revision
   did not move**, which is what makes this conjunct not redundant with the previous arm's.
7. **The store-level invariant, in the shared `PlanStore` conformance suite** (§3's test 3), over
   both implementations and the canonical fake: no `→ RUNNING` transition is ever accepted whose
   goal revision is not the stored one, and none whose attempt is absent, of another goal, or
   terminal. **And `attempt_id` on any other `to_status` is not constructible.**
8. **A parked middle step, answered and resumed** — a three-step plan whose **second** step rules
   `CONFIRM`: the walk stops, step 3 is `PENDING` and **not** `SKIPPED`, no third step is
   dispatched, the attempt is `AWAITING_AUTHORIZATION`, and the turn carries the confirmation.
   `resume` then disposes of step 2 and the driver **re-enters at step 3**, computed from the
   stored execution and not from a carried index. A paired arm answers `DENY`: step 2 is
   `SKIPPED`/`APPROVAL_DENIED`, and step 3 — declaring `depends_on` step 2 — is
   `SKIPPED`/`UNMET_DEPENDENCY`.
9. **"Restart during approval"** — the same plan parked at its second step; a **fresh** engine over
   the same durable state recovers it through `pending_confirmations()` (ADR-0052 §1), answers it,
   and the driver re-enters at step 3. The arm asserts the recovery is over steps and not
   positions, by parking at a middle step rather than a first.

**Full — M34, owed there and not established here.**

10. **Mid-plan `INDETERMINATE`** — a three-step plan whose second step returns `INDETERMINATE`:
    the walk stops, step 3 stays **`PENDING`** whether or not it depends on step 2, **no step is
    `SKIPPED`**, and the attempt's `state` is `EFFECT_UNRESOLVED` **before** the turn composes. A
    paired arm asserts a plan superseded in that state moves **no** step to `SKIPPED`/`SUPERSEDED`
    (§6's override of §7).
11. **Replan after partial execution** — a plan driven to its second step, superseded on a later
    turn: the first plan's `ExecutionState` and its `SUCCEEDED` step's `output` are unchanged, the
    attempt's `execution_ids` names both executions, the superseded plan's still-`PENDING` steps
    are `SKIPPED`/`SUPERSEDED`, and **the new plan's booking step dispatches** — which is the arm
    that records §7's stated limit rather than a property, and is why it is M34's beside A8's
    idempotency work.
12. **The deadline, decremented across steps** — a three-step plan under a budget that two steps
    exhaust: each `StepRunner.run` receives a **strictly smaller and strictly positive** remainder,
    the third step is never started, it is `PENDING` and not `SKIPPED`, and a step already begun
    ran to completion past the deadline. A paired arm asserts `AttemptEffort.working` advanced by
    the walk and `planner_calls` did not.
13. **A9's tests 1, 2 and 4**, stated here so the set is legible and **owed on A9's lane**.
14. **Real integrations**, under §13's rule: a consequential capability is wired only once A8's,
    A9's and A10's guarantees are implemented and demonstrated.

### 16. Records owed on earlier ADRs, under ADR-0082 §1

**Nothing is superseded, in whole or in part**, and §§below show the working for each document a
reader would expect to be — ADR-0037, ADR-0228, ADR-0249, ADR-0014, ADR-0042 and ADR-0253 among
them. ADR-0082 §1's test is applied to each earlier ADR's **text**.

**ADR-0037 §6 — relied on and not superseded, and the report's cut table is corrected.** Revision
1's §L.1 row for A7 reads *"partially supersedes ADR-0037 §6's 'terminal for this turn'"*.
**ADR-0037 contains no such phrase** — the string appears nowhere in that document — and §6's
actual clauses are *"`run` enters only at `PENDING`"*, *"`FAILED` is deliberately not a second
entry point"* and *"This object disposes of one step, once."* Every one of them binds here: §1
calls `StepRunner.run` once per step, §7 relies on the `PENDING`-only entry as the within-execution
at-most-once guarantee, and cross-turn retry stays A8's exactly as §6 assigns it — *"cross-turn
retry belongs to whatever drives a whole `ActionPlan`"*, which is this stage declining it. **A
later ratified ADR has already ruled the same way**: ADR-0253 §13 states *"§6's *'This object
disposes of one step, once'* is untouched, because the driver A7 lands calls `StepRunner` once per
step rather than changing what `StepRunner` does."* This decision agrees with ADR-0253 and not with
the report's table, and records the disagreement rather than leaving a reader to find it.

**ADR-0228 §14's deferral is fired, and that is a record and not a supersession.** A deferral
states that a decision was **not** taken (ADR-0070 §1), so firing one replaces nothing and
`Accepted` is not dropped. Both halves of the entry's own list are taken: *"a rule for parking
mid-plan (#257 …)"* is §5, and *"an `INDETERMINATE` step in the middle of a plan (ADR-0014 §4)"* is
§6. ADR-0042 §3's follow-on, which that entry names, is §9.

**ADR-0228 §5 — relied on and extended, and the extension is new ground rather than a
replacement.** §5 rules *"A superseded plan **drives nothing**"* and *"Exactly one plan of a turn
is driven and it is the last"*, both stated of a turn that revises **before** driving; both stay
true of a walk, which drives one plan per turn and drives the last one produced. What §5 never
states is what becomes of an **already-driven** plan's remaining `PENDING` steps when a later turn
supersedes it, and §7 states it. A reader holding only §5 builds a system in which those steps sit
`PENDING` forever, indistinguishable from a walk that stopped — a smaller gap than a contradiction,
and ADR-0070 §1's test comes out on the record side. Its persistence clauses are relied on entire:
*"Every plan of the turn is persisted before anything is driven"* is what makes the plan the walk
reads a stored one.

**ADR-0249 §8 — relied on entire, and its refusal of a `StepTransition` member is kept, not
narrowed.** That clause reads *"**`StepTransition` gains no member for this.**"* Its scope is
*"for this"* — for the stale-revision comparison — and §3 adds no member for that comparison: the
revision conjunct stays the store's derivation from execution → plan → goal, exactly as §8 rules
it. A reader could take the sentence for a rule that `StepTransition` gains no member ever; it is
not one, and §3 states the distinction the clause's own argument draws — a value the store already
holds, supplied by a caller, re-opens a gap, where the identity of the claimant is a value the
store does **not** hold and cannot derive without choosing it. **`attempt_id` is answered by
ADR-0249 §13's own reservation** — *"Whether `StepTransition` carries the attempt id it is claimed
under is still A7's and A9's"* — which is a deferral fired, not a clause replaced.

**ADR-0249 §5, §6, §12 and §13 — relied on entire.** §5's `EFFECT_UNRESOLVED` member gains its
producer in §6, which is a deferral's condition met rather than a clause changed; §6's writer
clause and its monotonic phase order are what §10 rests on and declines to weaken; §12's
`commit_attempt` is the only mutation route §6 and §9 use; and §13's plan-driving entry is
discharged, which is the entry spent rather than replaced.

**ADR-0014 — relied on entire, and the two deferrals it still holds are named.** §3's
`ExecutionState` and its resumability argument are what §5 computes re-entry from; §4's transition
graph, its `→ RUNNING`-before-invoke ordering, its `approval_ref` rule, its `PENDING → SKIPPED` row
with `SUPERSEDED`, and its `INDETERMINATE` treatment are each taken as written; §5's
compare-and-swap and its commands-not-snapshots argument are what §3 strengthens by one conjunct.
**`SkipReason` gains no member** and **`StepStatus` gains no member**, so §3's and §4's
vocabularies are untouched. §7's **execution leases** and the **parallel-execution** half of its
step-dependencies bullet stay deferred and are named in §12; §7's **idempotency and
`INDETERMINATE`-resolution** deferral is A8's and is not taken here.

**ADR-0034, ADR-0029 and ADR-0039 — relied on and not superseded.** ADR-0034 §1's window rule and
its two qualifying grounds, ADR-0029 §4's deadline enforcement and its `INDETERMINATE`
classification, ADR-0029 §5's retry mechanism, and ADR-0039 §2's `failure`-required rule over
`{FAILED, INDETERMINATE}` each bind exactly as they stand; §4 states them rather than moving them,
and §11's validator is ADR-0039 §2's shape borrowed for a different field.

**ADR-0037 §2, §4, ADR-0044, ADR-0052 and ADR-0058 — relied on and not superseded.** §2's
decide → record → read back → claim ordering is untouched and is where coverage is compared
(ADR-0254 §13); §4's park sequence and its `resume` entry point are what §5 calls; ADR-0044 §2's
per-binding resolution rule and §3's `pending_confirmation` query are what §5's stranded-step
answer rests on; ADR-0052 §1's recovery enumeration is what arm 9 drives; ADR-0058's ruling that
*"`StepExecutor` does not validate trail presence"* and its four-collaborator construction contract
are untouched, and ADR-0254 §13's clause that **no collaborator is added to `StepExecutor`** binds
this decision entire.

**ADR-0148 and ADR-0152 — relied on and not superseded.** ADR-0148 §1's completeness rule is what
§1 orders the resolution against and §9 is why the driver builds no request after a ruling;
ADR-0148 §9's no-egress-outside-a-claimed-step clause is §4's whole statement of the boundary;
ADR-0152 §7's `rebind` takes *"**exactly one** thing"* from `approved` and **gains nothing** here.

**ADR-0042 §3 — its named follow-on is discharged, which is a record and not a supersession.** That
section says the distinction between a per-attempt and a per-request budget *"is dormant today"*
and that bounding a whole multi-step request *"is a decision that belongs with that plan-driving
stage, and is named here as a follow-on rather than pretended to be solved"*. §9 takes it. The
`timeout`'s keyword-only, no-default, caller's-budget character is unchanged, and nothing about
§3's two call shapes moves.

**ADR-0251, ADR-0252, ADR-0253 and ADR-0254 — relied on and not superseded.** ADR-0251 §5's
figures and §6's ungated-composing clause are read as written in §9 and no figure moves;
ADR-0252 §6's four tests are evaluated by §1 and not restated; ADR-0253's §§1, 2, 4, 5, 6, 8 and 9
are each taken as the contract this lane was handed, and **the three questions ADR-0253 hands here
by name are answered** — the moment a never-eligible step is skipped (§2), the mechanism by which
an attempt re-enters an earlier phase (§10), and the driver's performance of the plan's
interpretations (§1). ADR-0254 §13's recheck, §14's phase-4 evaluation and its no-backwards-phase
clause, and §17's Q4 rule are each relied on; §13's reservation of *"What happens to a call already
claimed when a revocation lands"* to A9 is untouched.

### 17. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**A reader acts differently, so this is a decision and not a clarification.** A reader holding the
corpus without it builds a system that drives one step of every plan — which ADR-0228 §14 says in
terms is *"the system as ratified"* — leaves `depends_on`, `when`, `resolves`, `verifies` and
`interpretations` inert, has no producer for `UNMET_DEPENDENCY` or `EFFECT_UNRESOLVED`, accepts a
`→ RUNNING` claim under an attempt that has ended, and has no rule for what becomes of the steps
after a park, an uncertain effect or an expired budget. That is ADR-0070 §1's test met, and a new
ADR is the instrument.

**It supersedes nothing, in whole or in part** (ADR-0070 §3), so its `Status` line carries no
supersession pair and ADR-0070 §4's extraction invariant is not engaged. Every ADR it touches is
**relied on**, three deferrals are **fired** — ADR-0228 §14's, ADR-0249 §13's two, and ADR-0042
§3's named follow-on — and §16 shows the working for each rather than leaving a reader to check.

**The records it owes are dated notes and no `Status` line moves** (ADR-0082 §7): the entries §16
states are written with this document and not after it.

## Consequences

**A plan becomes a thing that runs, and the audit record stays two values.** What was decided is
the frozen `ActionPlan` ADR-0014 §2 already makes it; what happened is the `ExecutionState`. A
walk writes only the second, so *"why did this step not run"* is answered by joining them — a
`SKIPPED`/`UNMET_DEPENDENCY` step says the plan's own conditions refused it, a `PENDING` step says
the walk did not reach it, and nothing needs a log or a reconstruction of a model's reasoning.

**`UNMET_DEPENDENCY` and `EFFECT_UNRESOLVED` stop being vocabulary with no producer**, and
`StepExecution.output` stops being a field nothing reads. All three have sat in the durable types
for this lane — the first two since ADR-0014 and ADR-0249 — which is why none of them needs a
vocabulary change now.

**A cancellation that ends an attempt now stops the next step, where before it stopped only the
next understanding.** That is one conjunct, in one store, on one write, and it is the half of
#2255's cancellation requirement that a driver can establish on its own. The other half — what
happens to a call already in flight — is A9's and is honestly out of reach: ADR-0029 §4 is where
this system says it cannot know how far a call got.

**The cost is that a walk stops more often than a reader expects, and every stop leaves work
undone.** A park, an uncertain effect, an ambiguous capability, an unbindable egress, invalid
parameters and an expired budget each halt a plan with steps still `PENDING`. That is deliberate —
§2's argument is that none of them has decided anything about those steps — but it means a user
will see *"two of your four steps ran"* and the system will not, on its own, finish the other two.
What finishes them is A8's retry and reconciliation, A9's report, and the user asking again.

**Nothing consequential is wired yet, and §13 is what makes that an interval rather than a
hazard.** A5 landed the plan's half, A6 the authorization half and A7 the driver; until A8, A9 and
A10 have discharged the guarantees, no consequential capability is wired into a production
deployment.

**Revisit when** A8 lands reconciliation (does the recovery scan write the attempt's state?), when
A9 lands cancellation (do tests 1, 2 and 4 pass against §3's conjunct as written?), when a
scheduled or background drive is wanted (§12's outside-a-turn entry), when two parks in one turn
are wanted (§12), or when a measured planner failure shows that a replan redoing a completed effect
is a real loss rather than a hypothetical one (§7).

## Alternatives considered

**`StepTransition` carries the goal revision, as revision 1 §H.1 shapes it.** Rejected, and it is
the alternative this decision most had to argue with. It is refused by ADR-0249 §8 in terms — a
caller-supplied revision *"would put the decision back in the caller's hands and re-open the gap
the clause above closes"* — and the gap is real rather than formal: a user act between the caller's
read and the caller's claim moves the stored revision while the copy the caller carries goes on
matching itself. §H.1's property is right and its construction spends it; deriving the revision in
the store buys the property outright.

**The store derives the attempt too, by scanning `GoalAttempt.execution_ids`.** Rejected. It works
only where `commit_attempt` already appended the execution id, so a conjunct meant to be a
guarantee would silently be a no-op on any path that had not; it makes the store choose which
attempt a claim belongs to, which is a fact only the driver holds; and it is an unindexed reverse
scan over every attempt of a goal on the hot path of every claim. The caller supplies an identity
and the store reads the state, which is `approval_ref`'s own division.

**The walk continues past a park, an uncertain effect or a commits-nothing disposition, driving
steps that are independent of the stopped one.** Rejected on three grounds §2 states: independence
is a planner's declaration rather than a fact about the world; a second call dispatched under the
first's uncertainty compounds it; and a paused attempt (ADR-0249 §5's own derivation) that went on
acting would make the one surface a user reads to find out whether anything is happening say the
opposite of the truth. The cost is a plan that could have finished and did not, which is visible
and recoverable.

**Every step the walk did not reach is swept to `SKIPPED` at the end of the walk.** Rejected. A
skip is a durable claim that *nothing can run it* (ADR-0014 §4), and in every case §2 lists
something still can — the user has not answered, the tool's ambiguity is a deployment fix, the
`INDETERMINATE` step awaits A8. Sweeping would make a stopped walk and a refused step
indistinguishable in the one record that has to tell them apart.

**A never-eligible step is skipped at the end of the attempt rather than when the walk reaches
it.** Rejected. Nothing about the refusal can change between the two moments — §2 shows every
input is fixed once the walk passes the step — so the later write records the same fact later, and
in the interval the step is `PENDING`, which the stop rule needs to mean something else.

**The driver carries a cursor across a park, a turn or a restart.** Rejected on ADR-0014 §3's own
argument for splitting `ExecutionState` out of `ActionPlan`: a second source of truth that can
disagree with the steps. A restart loses it, a replan points it past the end of a different plan,
and the correct value is a one-line derivation from state the store already holds.

**The driver evaluates `verifies` on every succeeded step and records the verdict.** Rejected. The
record would be a new field on a durable, exported, wire-carried type for a value ADR-0253 §10
does not name, and a verdict rendered to a user would read as verification — the exact conflation
ADR-0253 §4 scopes the field to prevent, and the owner's correction 2 in the place it is most
likely to be got wrong.

**An attempt re-enters an earlier phase, with a backwards edge on `commit_attempt`.** Rejected. It
would falsify ADR-0249 §12's derivation that *"the phases an attempt has passed are exactly those
at or before its current one"*, which is the whole reason that decision keeps no per-phase event
log; and the thing it is wanted for — an unexpected finding returning the work — is already a
property of the **plan** under ADR-0253 §9, which answers with a branch the plan declared rather
than with a transition on the attempt.

**The driver refuses a step whose effect the goal records as completed, as revision 1 §K.2 step 6
has it.** Rejected because the record does not exist: a re-plan mints new step ids, `Goal` and
`GoalAttempt` carry no effect identity, and a comparison over capability and parameters would
invent one — refusing a legitimate second booking of two different nights as readily as a
duplicate. §7 states the limit and names the two routes that would close it.

**The driver is gated on `AttemptEffort`'s working allowance as well as on the request deadline.**
Rejected on ADR-0251 §5's own reasoning about why ADR-0228 §4's key does not move to the attempt:
the two figures measure different quantities, and an attempt that spent its investigation share on
turn 1 would find its turn-3 plan refused mid-walk, with a durable act half-performed.

**A new `SkipReason` for a step the walk did not reach, or for a step a deadline stopped.**
Rejected. It widens a durable vocabulary carried in `StepExecution`, `PlanExport` and the wire to
name a state `PENDING` already names truthfully, and ADR-0253 §5 refused a fifth member on the same
ground one level up.

**A `PlanStore` member that commits several transitions in one write, closing #257 along the way.**
Rejected as out of scope and probably wrong in shape — #257's own words are that it is *"arguably
the wrong shape for a store whose whole write API is a single compare-and-swap"*. §5 answers what
the driver does when it meets a stranded step using the query ADR-0044 §3 already landed, which
costs no contract change.
