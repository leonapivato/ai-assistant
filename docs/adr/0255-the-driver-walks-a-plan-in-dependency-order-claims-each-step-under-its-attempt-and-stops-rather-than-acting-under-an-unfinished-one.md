# 255. The driver walks a plan in dependency order, claims each step under its attempt, and stops rather than acting under an unfinished one

- Status: Proposed
- **Partially supersedes [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md),
  in one narrowly stated scope**, and §16 shows the working.
  **§14's where-phase-4-leaves-an-attempt enumeration**, in its two-case shape alone: *"**Every
  check passed** — the attempt's `phase` advances to `AttemptPhase.EXECUTE`"* and *"**A
  deterministic check failed on the plan** — the attempt stays `RUNNING` and the plan is replanned
  within the attempt"* gain a **third** case. A check **of a step** whose operands **this same
  plan** will produce before that step is dispatched, and has not produced yet, is **deferred**,
  not failed — and the plan has exactly two such producers: **a step earlier in `steps` that has
  not been disposed of**, and **an interpretation of this plan that has not been performed,
  including one carrying a `record`**, which is performed before the plan's first step is
  dispatched and therefore after phase 4. A deferred check neither blocks the advance to `EXECUTE`
  nor triggers a replan, and the attempt advances where every check either **passed or was
  deferred**. Without it every plan carrying a `depends_on` replans forever, and a one-step plan
  conditioned on its own record-backed interpretation never runs it. **§14's every other clause
  binds verbatim**: the four checks and their order, the no-fifth-check rule, the
  no-capability-vocabulary-check and no-spend-ceiling clauses, the `MONEY`-bound clause, the
  advisory-in-one-direction rule for an intent-match assessment, **the uncovered-arguments limb
  and its `CONFIRM` park**, which is neither a deferral nor a failure and which this decision
  routes nothing away from, the failed-check limb for every check that is **not** deferred, the
  no-phase-moves-backwards clause and the supplying-an-authorization-opens-no-attempt clause.
- **Partially supersedes [ADR-0251](0251-an-attempt-investigates-in-bounded-rounds-over-typed-read-outcomes-and-keeps-a-reserve-to-answer-with.md),
  in two narrowly stated scopes**, and §16 shows the working for both.
  **§4's trigger group** — the read conditions **(b)**, **(c)** and **(d)** together with **(j)**,
  *"The attempt's `phase` is `AttemptPhase.INVESTIGATE`"* — is satisfied, in place of a serviced
  read, by a **re-investigation licence**: a typed outcome of a plan-driving walk that ran to the
  end of the plan and skipped at least one step because the world did not meet what the plan
  declared. **And §1's occupancy clause**, in one term: *"Every round of one attempt's
  investigation sits inside one occupancy of `AttemptPhase.INVESTIGATE`"* becomes *"inside one
  occupancy of `AttemptPhase.INVESTIGATE` **or** under a re-investigation licence"*. Without the
  pair, an attempt that executed and learned something may make its turn's one ungated planner
  call and may **not** iterate over what it learned, while the decisions fixing which acts open an
  attempt forbid opening a fresh one to escape the bar — so investigating an alternative is
  unreachable inside that attempt. **§4's every guard binds verbatim and is checked** — (a), (g),
  (f′)'s planner-call allowance, (h)'s working allowance less the reserve, and (i)'s
  unproductive-rounds test — so a licensed round is charged from the same ledger and stops on the
  same guards; **§1's clauses that no round moves the phase and that there is no re-entry into
  `INVESTIGATE` from a later phase bind verbatim and are obeyed rather than lifted**, a licensed
  round re-entering no phase at all; and §4's never-gated-first-call clause, its (e)-is-dissolved
  clause and (j)'s own `NOT_ITERATED` record are untouched.
- **Partially supersedes [ADR-0228](0228-a-serviced-read-may-revise-the-plan-once-and-the-turn-stops-looking-at-a-bound-or-a-deadline.md),
  in three narrowly stated scopes, every one of them §5's**, and §16 shows the working for each.
  **The first is §5's two per-turn clauses, in their subject** — *"**Every plan of the turn is
  persisted before anything is driven.** The whole sequence of `save_plan` calls precedes
  `start_execution`"* and *"**Exactly
  one plan of a turn is driven and it is the last**"* — become statements over a **walk**: the
  plans produced for a walk are all persisted before that walk's `start_execution`, and exactly
  one plan is driven per walk and it is the last produced for it. A turn makes at most **two**
  walks, its first and one after a licensed investigation, so it drives at most two plans.
  Without the scope a licensed investigation cannot persist the plan it produces, because that
  save necessarily follows the first walk's `start_execution`. **§5's reason is kept rather than
  weakened**: the ordering protects a turn that *"has driven nothing: no execution is open, no
  capacity slot is spent on a step and no side effect has been reached"*, which is true before a
  turn's first walk and false before its second, so the per-turn reading would forbid the
  investigation while buying nothing. **The second and third scopes are two further clauses of
  §5**, and they are named rather than left inside the first. **The second is the
  superseded-plan-drives-nothing rule, in the moment it binds at**: *"A superseded plan **drives
  nothing** … reaches no `StepRunner`"* binds of a plan superseded **before its walk began** and
  does not retrospectively forbid a walk that had already run when the supersession was recorded.
  **The third is the no-new-failure-mode clause**, which held because every `save_plan` preceded
  every drive, which a licensed round's save no longer does, so §10 states what a second walk's
  persistence failure leaves behind. **§5's remaining clauses bind
  verbatim**: the every-plan-is-persisted rule, the oldest-first order, the one-persistence-site
  rule and the turn-that-ends-early-persists-nothing rule.
- **No other ADR is superseded in whole or in part**, and §16 shows the working for each one a
  reader would expect to be — ADR-0014, ADR-0037, ADR-0249, ADR-0042 and ADR-0253 among them.
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
> 3. **That every result reference is resolvable** — every member of `resolves`, against
>    ADR-0253 §6's six unresolvable cases, over the `PlanStep` read from `PlanStore.get_plan` and
>    the `ExecutionState` read from `PlanStore.get_execution`. **This is the predicate and not the
>    substitution** (below).
> 4. **`StepRunner.run`, once.** The driver passes the execution, the step id, the remaining
>    budget (§9), the selection origin and the `attempt_id` (§3), **and no parameter mapping, no
>    resolved value and no step.**
>
> **Authorization coverage is not a fifth evaluation of the driver's**: ADR-0254 §13 puts the
> comparison *"at `ActionPolicy.decide`, on the concrete request, at every dispatch"*, which is
> inside step 4. The driver **reaches** that test and does not take it.

> **Normative — the substitution happens where ADR-0253 §6 already puts it, inside the request
> construction, and the driver hands over nothing.** A resolved value is placed at its
> `parameter` **by the stage that builds the `ActionRequest`**, from the two values that section
> names — *"the `PlanStep` read from `PlanStore.get_plan` and the `ExecutionState` read from
> `PlanStore.get_execution`"* — and **`StepRunner` is that stage**. ADR-0253 §6 binds verbatim and
> is satisfied rather than worked around: *"**no caller supplies a resolved value, a parameter
> mapping or a substituted step**, and no entry point of the permission stage gains a parameter
> for one."* **No clause of this decision gives `StepRunner.run` or `StepExecutor.execute` a
> parameter mapping**, and §3's `attempt_id` stays the only argument either gains.

**The driver evaluating resolvability and the runner performing the resolution are one total
function read twice, not two carriers for one fact.** ADR-0253 §6 states it as *"a total function
of two values both read from the `PlanStore`"*, so two evaluations over the same stored values
return the same answer by construction — there is no state between them to disagree about, and
ADR-0254 §13 already requires exactly this of coverage, which *"is taken at `ActionPolicy.decide`
… at every dispatch"* with *"no cached coverage verdict anywhere"*. What the driver needs is the
**predicate**, because §2's skip is its to write and ADR-0037 §6 keeps `StepRunner` disposing of
*"one step, once"* rather than reporting a fourth kind of refusal. What the request needs is the
**value**, and ADR-0148 §1 requires it to be there before `ActionPolicy.decide` — which is inside
the runner and after the driver has handed over.

> **Normative — `StepRunner`'s request construction changes, and that is permitted here rather
> than assumed.** The stage reads the step from the plan and the execution from the store exactly
> as ADR-0037 §2 requires — *"The step itself is read from the plan, not accepted from the
> caller"* — and now also resolves that step's `resolves` from the same two stored values before
> building the request. **ADR-0037 §6's *"This object disposes of one step, once"* is untouched**,
> no entry point gains a parameter for a resolved value, no collaborator is added (ADR-0058), and
> the substitution reaches no other stage: ADR-0253 §6's ordering clauses — the schema check, the
> canonicalisation, `bind`, and ADR-0021 §1's digest — all run over the resolved mapping at the
> slots they already occupy.

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

> **Normative — a check whose operands a later step will produce is *deferred*, and a deferred
> check is not a failed one. This partially supersedes ADR-0254 §14** in the one scope §16
> states. A phase-4 check **of a step** is **deferred** where any operand it reads is a value
> **this same plan will produce before that step is dispatched** and has not produced yet. There
> are exactly two such producers, and both are the plan's own:
>
> - **a step of this plan appearing earlier in `steps`** that has not been disposed of — a
>   `depends_on` member still `PENDING`, a `resolves` naming such a step's `output`, a `when` over
>   an element an interpretation settles from such a step's output, and the coverage comparison
>   over a request such a reference completes;
> - **an interpretation of this plan that has not been performed** — including one carrying a
>   **`record`**, which ADR-0253 §8 performs *"before the plan's first step is dispatched"* and
>   which §1 places **inside the walk** and therefore **after** phase 4. A `when` over an element
>   such an interpretation settles is deferred **on the first step of the plan** exactly as it is
>   on a later one.
>
> **A deferred check neither blocks the advance to `AttemptPhase.EXECUTE` nor triggers a
> replan**, and it is decided at that step's own dispatch, by §1's evaluation, on ADR-0252 §6's
> *"at the moment of dispatch"*.

> **Normative — every other check keeps ADR-0254 §14's rule entire, and an uncovered argument
> keeps its own limb.** A check whose operands are all available at phase 4 and that **fails** is
> a failed deterministic check, and §14's limb binds unchanged: *"the attempt stays `RUNNING` and
> the plan is replanned within the attempt … Where no replan can satisfy the check, the attempt is
> left for A3's `BLOCKED` producer."* A `when` that **no row of the goal satisfies** on a step
> waiting for nothing this plan will produce, a `resolves` naming a step outside its `depends_on`,
> and an argument neither literal nor referenced nor system-supplied are each **failures** and none
> is deferred.

> **Normative — an uncovered argument is neither a failure nor a deferral, and ADR-0254 §14's
> coverage limb binds entire.** That section rules it separately and this decision does not touch
> it: *"**A step's arguments are not covered** — the user is asked through the ordinary `CONFIRM`
> park (ADR-0037 §4), and the attempt's move to `AttemptState.AWAITING_AUTHORIZATION` is **the one
> ADR-0249's own lane already makes**."* **No lane replans on an uncovered argument**, and no
> clause of this decision routes one to §14's failure limb — replanning could not supply the
> authorization the check is missing, so it would loop on a question only the user can answer.

> **Normative — phase 4 therefore has four dispositions and not two.** A check **passed**; a check
> **deferred** (above); a check **failed**, which is §14's replan limb; and an argument **not
> covered**, which is §14's `CONFIRM` limb. **The attempt advances to `AttemptPhase.EXECUTE` where
> every check either passed or was deferred**, and not otherwise.

**Without this scope ADR-0254 §14 refuses every dependent plan there is, which is the one thing
it cannot have meant.** Step 2's dependency on step 1 is unsatisfied at phase 4 for *every* plan
that has one, because step 1 has not run; its `when` over an element step 1's output will settle
is unsatisfied for the same reason. Read as written — *"advances to `AttemptPhase.EXECUTE`"* only
when *"Every check passed"*, and *"the plan is replanned"* when one failed — the two-step plan
ADR-0253 exists to make expressible would replan forever and never dispatch. **An earlier draft of
this section called that reading an evaluation "over what is knowable then" and left §14's text
alone.** That is an interpretation, not an exemption: a reader holding ADR-0254 §14 and this
document would still find one clause requiring a replan and the other requiring a dispatch, and
ADR-0070 §1's test comes out on the supersession side. So the scope is taken explicitly and §16
shows the working.

**The distinction is already in the corpus one level down, which is why it is a narrow scope and
not a new idea.** ADR-0253 §2 rules that an `INDETERMINATE` producer *"**fails it and stops the
branch**: neither the dependent step nor any step that depends on it, transitively, is dispatched,
skipped or resolved, and each stays `PENDING` until the `INDETERMINATE` step is resolved
explicitly"* — a dependency that is neither satisfied nor failed, left pending on a producer's
disposal. **A producer that has simply not run yet is the same shape with a cheaper resolution**,
and ADR-0254 §14 wrote its enumeration before any lane could walk a plan and meet one.

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

> **Normative.** **A step the walk did not reach is `PENDING` when the walk ends**, and **the
> walk itself never skips it**. No lane sweeps the remainder of a stopped walk into `SKIPPED`,
> writes a `SkipReason` for a step nothing evaluated, or reads `PENDING` after a stopped walk as
> a terminal state. **Exactly one later event disposes of such a step, and it is not the walk**:
> §7's supersession, on a different ground, at a different moment, and forbidden by §6 behind an
> `INDETERMINATE` step.

> **Normative — what re-enters a stopped walk, and this decision provides no automatic route.** A
> stopped walk is re-entered by **exactly one** route: `StepRunner.resume` answering a park of
> that plan, after which the driver **walks that plan again from its first position** (§5).
> **There is no
> sweep, no timer, no queue, no background continuation and no automatic re-drive** of a plan the
> walk stopped on any of the other four triggers. A later turn of the same attempt **plans
> again** — which produces a **new** plan, driven over a **new** execution, and §7 governs what
> becomes of the old one — rather than resuming the old walk. **What causes that later turn is a
> user act** (ADR-0250 §12), and **what the user is told about the stopped plan is A9's report**.

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
> **at the moment the walk reaches it**, in exactly **four** cases — all four ADR-0253's, none
> minted here, and the first two the two limbs of that section's one dependency rule:
>
> - its dependency **fails on a `FAILED` or `SKIPPED` producer** (ADR-0253 §2);
> - its dependency is **unsatisfied on a `SUCCEEDED` producer whose `verifies` does not hold**
>   over that producer's stored `output` (ADR-0253 §2's second conjunct, §4);
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
> transition is accepted only where the `GoalAttempt` its `attempt_id` names **exists**, carries
> the transition's own **`execution_id` among its `execution_ids`**, is in a **non-terminal
> `AttemptState`**, and is the **only** attempt of that goal naming that execution. **The refusal
> takes one of two classes, and which it takes is decided by whether a corrected claim or a later
> turn could ever satisfy the limb.** A claim naming **no attempt**, an **unknown** attempt, an
> attempt that **did not open this execution**, or an attempt whose `state` is **`CANCELLED` or
> `ENDED`**, is **refused with the
> error class a stale `expected_version` already raises** (`StaleExecutionError`), which is
> ADR-0249 L1's precedent for the revision conjunct: each of those four names a row the caller
> could have named correctly, or a state a later turn under a live attempt reaches. A claim
> against an execution **more than one attempt names** is refused with the **non-stale
> `PlanningError`** the two ownership refusals below take, because that limb is **permanent** and
> no re-read, corrected claim or later turn makes it claimable. This is a **strengthening of an
> existing member** rather than a new one, exactly as ADR-0249 §12 classifies the first added
> condition.

> **Normative — the binding is the execution's membership and never the goal's, and this is the
> conjunct's whole strength.** A goal may carry many attempts (ADR-0249 §5, ADR-0250 §12), so a
> check that the attempt merely **belongs to the same goal** would accept a claim for an
> execution of an **ended** attempt A that named a **live** attempt B of that same goal — every
> stated condition satisfied, the plan still targeting the current revision, and the cancellation
> of A defeated by naming B. **`GoalAttempt.execution_ids` is the authoritative binding**: it is
> appended by `commit_attempt` (ADR-0249 §12) at the moment the execution is opened, it is
> append-only — *"an `add_*` member appends its identifier … and no member of `AttemptTransition`
> removes, reorders or replaces an identifier"* — and membership in it is a comparison against
> one stored row rather than a scan.

> **Normative — an execution belongs to exactly one attempt, and **both** attempt-writing members
> are where that is made true.** `PlanStore.commit_attempt` **refuses an `add_execution_id` naming
> an execution that any attempt of that goal already carries**, and `PlanStore.open_attempt`
> **refuses a `GoalAttempt` whose `execution_ids` names an execution any attempt of that goal
> already carries** — because `open_attempt` takes a whole `GoalAttempt` and that tuple may arrive
> non-empty, so a caller could otherwise open a live attempt carrying an ended attempt's execution
> and defeat the conjunct without ever calling `commit_attempt`. **Each decides it in the same
> indivisible step as its own write.**

> **Normative — an ownership conflict raises `PlanningError` and never `StaleExecutionError`, and
> the distinction is what the class means to a caller.** `StaleExecutionError` is *"A write [that]
> lost the optimistic-concurrency race"* (ADR-0014 §5), and its whole contract is that re-reading
> and retrying can succeed. **An ownership conflict is permanent**: no re-read makes an execution
> owned by attempt A valid for attempt B, so a caller conforming to that class's contract would
> retry a write that can never land. **Three refusals therefore raise a `PlanningError` that is
> **not** the stale class** — `commit_attempt`'s, `open_attempt`'s, and `commit_transition`'s
> **duplicate-ownership limb** — and §3's `→ RUNNING` conjunct keeps `StaleExecutionError` for its
> **other four** limbs alone, each of which **is** retryable in the sense that class names: a
> claim naming no attempt or the wrong one succeeds when corrected, and a claim under an ended
> attempt succeeds on a later turn under a live one. **The duplicate is the one limb no
> correction reaches**: with execution E named by attempts A and B, every claim for E is refused
> whichever attempt it supplies (below), so handing the caller a class whose contract is *re-read
> and retry* would be telling it to loop forever against a state this decision deliberately
> refuses to repair. This
> is a second **strengthening of an existing member** on ADR-0249 §12's own footing, and it is
> what makes §3's conjunct a binding rather than a coincidence: ADR-0249 §12's append-only rule —
> *"an identifier the tuple already holds is ignored rather than duplicated or refused"* — governs
> a **repeat of the same append on the same attempt** and says nothing about two attempts, so
> without this clause one execution could sit in both an ended attempt A and a live attempt B and
> a claim naming B would pass every stated check. **Append-only prevents removal, not multiple
> ownership**, and the conjunct needs the second.

> **Normative — a store written before this decision may already hold the state it forbids, and
> that is answered rather than assumed away.** Both members admitted two attempts of one goal
> naming one execution before this decision, so a `schema_version` 2 database may carry one.
> **The refusals above bind on every write and change no stored row**, so no migration is owed and
> the store's `schema_version` does not move (§11). **What a reader does with a legacy duplicate
> is fixed here, and it is to refuse**: `commit_transition`'s conjunct requires **exactly one**
> attempt of that goal to name the execution, so a claim against an execution **two** attempts
> name is refused whichever is supplied — on the **non-stale `PlanningError`** above, because no
> correction reaches it — and **§5's recovered resume refuses** on the same state for the same
> reason. **No lane repairs, rewrites or deletes a legacy duplicate**, and none reads
> `PlanExport`'s closure rule as excluding one.

**Refusing rather than migrating, and refusing at the claim and not only at the resume.** A
migration would have to choose which attempt owns an execution two attempts name, and nothing in
the record says — the append order is not retained and ADR-0249 §12's tuples carry no instant — so
it would invent an ownership nobody recorded, which is the fabrication ADR-0249 §12's own
migration clause refuses for a ground it cannot show. **And accepting either owner would hand back
the exact bypass this conjunct exists to close**: an execution under a `CANCELLED` attempt A and a
live attempt B is the cancellation-defeating state named above, and a claim naming B would start a
step after A ended. So ambiguity fails closed **everywhere it is read**, not only where a single
value had to be chosen. The cost is a refusal on a state no code this system ships can newly
create; the alternative is a silent hole in the one guarantee §3 is for.

> **Normative — the exclusivity is what makes §5's recovered resume total.** That section resolves
> a parked step's attempt as *"the attempt whose `execution_ids` names that execution"*; with
> ownership exclusive there is **exactly one** such attempt or none, so the resolution is a
> function rather than a choice and §5's refusal covers the only other case. **No lane resolves an
> ambiguous ownership by picking the live one, the newest one or any one**, and a store that
> somehow holds two is a store this clause makes unreachable through `commit_attempt`.

> **Normative — the append precedes the first claim, and a lane that reverses the order finds
> every claim refused rather than a gap.** `orchestration` commits `add_execution_id` for an
> execution **before** any step of it is dispatched, which is where ADR-0249 §12 already puts it
> — *"referenced by id and never inlined, appended at the moment the execution exists"* — and is
> what `engine.py` already does today, immediately after `start_execution` and before the runner
> is called. **The ordering fails closed**: an execution whose append has not landed carries no
> attempt that names it, so the conjunct refuses and nothing is invoked.

> **Normative — how the value reaches the claim, and it is threaded rather than fetched.**
> **`StepRunner.run` and `StepRunner.resume` each gain one required keyword parameter,
> `attempt_id`, and `StepExecutor.execute` gains the same one**; each passes it through to the
> `StepTransition` its claim builds and reads it for nothing else. **The driver supplies it from
> the `GoalAttempt` it is driving under**, which is the value ADR-0249 §12 already has
> `orchestration` holding in memory from the instant the attempt is opened. **No stage of the
> walk fetches the attempt to fill it**, `StepExecutor` gains **no `PlanStore` read it does not
> already have and no collaborator** (ADR-0058), and no other parameter of either entry point
> moves. **The one path on which `orchestration` has no attempt to supply is ADR-0052's recovered
> resume, and §5 states what it does there.**

> **Normative — this is not the substitution hazard ADR-0037 §2 and ADR-0253 §6 close, and the
> distinction is what the store's own refusal makes true.** Those clauses refuse a caller-supplied
> **step**, **parameter mapping** or **resolved value** — *"no caller supplies a resolved value, a
> parameter mapping or a substituted step, and no entry point of the permission stage gains a
> parameter **for one**"* — because each would let a caller change **the subject the gate rules
> on**. `attempt_id` is not a subject: it is not read into the `ActionRequest`, not shown to the
> policy, not carried into the `PermissionDecision`, not used to select a tool or fill an
> argument, and not compared against anything the caller supplied. It names a row, and **a caller
> that names the wrong row is refused rather than obeyed** — the store checks the row's own
> `execution_ids` and its state against values only the store holds. That is exactly
> `approval_ref`'s shape under
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
not.** What the store derives for the revision, it derives from a chain that **names exactly one
value at each hop**: execution → plan → goal → `revision`. **Which attempt a claim is made under is
not that shape.** One goal may carry many attempts (ADR-0249 §5, ADR-0250 §12) and one execution
sits under exactly one of them, so a store deriving the attempt would be **selecting** rather than
following — searching `attempts_of(goal_id)` for the row whose `execution_ids` names this
execution, on the hot path of every claim, and then comparing its own choice against nothing.
**The caller names the row and the store checks it**, which is the division `approval_ref` already
uses: ADR-0014 §4 has the caller name the decision and the store refuse a `→ RUNNING` without one.

**Naming and checking in two components is what gives the conjunct something to refuse, and it is
why the check is `execution_ids` membership rather than a goal comparison.** A derivation is its
own answer and cannot be wrong about itself; a supplied id can be, and the store holds the fact
that decides it — the attempt's own `execution_ids`, appended by `commit_attempt` before any step
of that execution is dispatched (ADR-0249 §12) and never removed or reordered. There is no
time-of-check-to-time-of-use gap for a caller's value to open, because the caller's value is an
**id**: an id does not go stale, and everything that can go stale about the row it names — the
membership and the state — is read inside the same indivisible step as the claim.

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
> revision is not the stored one, and none whose attempt is **absent**, **does not name this
> execution**, or is **terminal**. **Tests 1, 2 and 4 —
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

### 5. Mid-plan park: the walk stops, and the answered park is followed by another whole walk

> **Normative.** A step whose ruling is `CONFIRM` parks exactly as ADR-0037 §4 already parks one —
> the decision recorded, the step committed `PENDING → AWAITING_APPROVAL` carrying `bound_tool`,
> the disposition `AWAITING_CONFIRMATION` carrying the decision id — and the attempt's move to
> `AttemptState.AWAITING_AUTHORIZATION` is **ADR-0249's lane's**, which ADR-0254 §14 already
> relies on. **This decision adds no second asking mechanism, no second writer of that state, no
> park queue and no `core` type for a parked step.**

> **Normative.** **The walk stops at the park** (§2), and **nothing of that plan is dispatched
> again until the park is answered**. No step independent of the parked one is dispatched, no
> second `CONFIRM` is put in one turn, and no lane collects several parks into one prompt.

> **Normative — an approval is re-evaluated before it is resolved, because a resumed dispatch is
> a dispatch.** Before `StepRunner.resume` is called with `approved=True`, the driver re-evaluates
> §1's first three predicates for the parked step — the dependency rule, every member of `when` by
> ADR-0252 §6's four tests, and the resolvability of every `resolves` — **against the state as it
> then stands**. Where any of them refuses, **`resume` is not called at all**: no ruling is
> resolved, no claim is made, nothing is invoked, the step stays `AWAITING_APPROVAL` at its stored
> version, and the walk stops (§2).

> **Normative — a denial is never gated on any of them.** `resume` with `approved=False` is called
> whatever those predicates say, and the step is committed `AWAITING_APPROVAL → SKIPPED` with
> `skip_reason=APPROVAL_DENIED` exactly as ADR-0037 §4 rules. **A refusal to act needs no evidence
> and no dependency**, and a user's *no* is never withheld from the record because a forecast went
> stale.

> **Normative — the step is left parked rather than skipped, and the reason is the transition
> graph.** ADR-0014 §4's table admits `AWAITING_APPROVAL → SKIPPED` on `APPROVAL_DENIED` and
> `SUPERSEDED` **and on nothing else**, which `planning/execution.py`'s `_LEGAL_SKIP_REASONS`
> already enforces — so `UNMET_DEPENDENCY` is **not a legal disposal from a parked step**, and no
> lane widens that table to make one. Leaving the park standing also leaves the user's answer
> **unconsumed**, which matters because ADR-0036 §2's unique index and ADR-0044 §2(b)'s
> per-binding rule make a resolution **single-use**: resolving it into a dispatch that cannot
> happen would spend the one answer the binding admits and strand the step exactly as #257
> describes. **What the turn tells the user is A9's report** (§12).

**A park is the one place a dispatch's inputs are guaranteed to age, which is why this is stated
rather than left to the general rule.** Every other dispatch in a walk is evaluated and made in
the same pass; a parked one is evaluated, then waits for a human, and is made minutes or days
later. ADR-0252 §6 puts recency *"at **the moment of dispatch**"* and ADR-0254 §13 rules that
*"Coverage and sufficiency are two tests and neither clears the other"* — so an approval, which is
the coverage half arriving late, establishes nothing about the sufficiency half. A step declaring
a fifteen-minute recency requirement that parks on fresh evidence and is approved an hour later
would otherwise dispatch on a forecast ADR-0252 §6 test 4 refuses, with the user's *yes* as the
only thing anyone checked.

> **Normative — the resumed claim carries the same conjunct** — it is a `→ RUNNING` transition
> and §3 binds it — so a park answered after the goal moved on, or under an attempt that has
> ended, is refused and nothing is invoked.

> **Normative — a whole fresh walk follows the resumed step.** Where `resume` returns `EXECUTED`,
> the driver **walks that plan again**; where it returns `DENIED`, the step is
> `SKIPPED`/`APPROVAL_DENIED` and the driver **walks that plan again**, which will then dispose of
> that step's dependents by §2's skip rule.

> **Normative — the driver holds no cursor, and a resumed walk starts where every walk starts.**
> **Every walk visits the plan's steps from the first position**, reading each step's stored
> `StepExecution.status` from `PlanStore.get_execution`, and disposes of it by that status:
> **`SUCCEEDED`, `FAILED` and `SKIPPED`** are already disposed of and are **passed over without
> re-dispatch** — their dependents are governed by ADR-0253 §2 when the walk reaches them;
> **`PENDING`** is evaluated under §1; and **`AWAITING_APPROVAL`, `RUNNING` or `INDETERMINATE`
> stops the walk** where it stands. **No lane carries a step index across a park, a turn or a
> restart, no lane persists one, and no lane computes a resume position at all.**

**Re-walking from the first position rather than seeking to a resume point is what makes the
cursor unnecessary instead of merely derived, and it is also what stops a resumed walk
overtaking.** The obvious rule — resume at the first step still `PENDING` — is wrong on the very
shape §5 exists for: a plan whose **second** step is `AWAITING_APPROVAL` and whose **third** is
`PENDING` has its first `PENDING` step at position three, so that rule would dispatch step three
**past an unanswered question about step two**. Starting at position one cannot: the walk meets
step two first and stops there. The pass costs one store read and a status comparison per step,
against a durable state that ADR-0014 §3 already guarantees carries *"everything a restarted
executor needs to **not redo work**"*.

**Each of the three stopping statuses is a stop for a reason already ruled, and none is new
here.** `AWAITING_APPROVAL` is the park, and driving past it is what §2's park argument refuses.
`INDETERMINATE` is ADR-0014 §4's ignorance and §6's branch stop. **`RUNNING` is a step this
process is not executing** — every walk is sequential and in-process (§1, §4), so a stored
`RUNNING` the walk meets was left by something else, which is exactly the state ADR-0014 §4 gives
the **startup recovery scan** and which `ExecutionState.has_live_step` already marks for
`delete_goal`. The driver resolves none of them: it stops, and A8 and the recovery scan own what
happens next (§12).

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
> steps and not over positions, and **this decision adds no recovery path and no `Engine`
> member**. ADR-0052 §2's idempotence and its `_parked` reconciliation bind
> unchanged.

> **Normative — a recovered resume has no attempt in memory, so `orchestration` resolves one
> before it claims, and a resume with none is refused rather than claimed without one.** ADR-0052
> §3 rules that a park recovered from durable state has **no live turn** — *"context and retrieved
> memories are ephemeral and were never persisted"* — so §3's `attempt_id` is not a value the
> resuming path is holding. On that path alone, `orchestration` resolves it **once, before the
> resume**, from values the plan store already holds: `get_execution` names the plan, the plan
> names the goal, and `attempts_of(goal_id)` carries the attempt whose `execution_ids` names that
> execution (ADR-0249 §12's append). **Where no attempt names it, and where more than one does —
> the legacy state §3 describes — the resume is refused, before any ruling is resolved and before
> anything is claimed.** §3's exclusivity makes the second case unreachable through either
> attempt-writing member, so it survives only in a store written before this decision.

**Resolving it in `orchestration` is not the store-side derivation §3 refuses, and the difference
is which of the two is the check.** §3 declines to have the **store** find the attempt because
there the derivation *would be* the conjunct: a store that chose the attempt would be comparing a
value against one it had just selected, and nothing would be left to refuse. Here the resolution
is `orchestration`'s, taken once on the one path where the driver genuinely does not hold the
value, and its result is then **checked** by the store's own conjunct against the goal and the
state — so a wrong resolution is refused rather than obeyed, which is exactly the direction
ADR-0037 §2 means by *"Naming the step removes the substitution rather than checking for it"*, with
the naming and the checking in two components. **Refusing where none is found is the fail-closed
direction**: ADR-0044 §3's recovery already returns `None` rather than raising for a binding it
cannot answer, and a resume that could not name its attempt would otherwise be a claim §3 refuses
anyway, one store round-trip and one authored resolution later — which on ADR-0036 §2's
single-resolution rule is an authored resolution that cannot be taken back.

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

> **Normative.** **No step the uncertainty reaches is ever moved to `SKIPPED` by this decision —
> not with `UNMET_DEPENDENCY`, not with `SUPERSEDED`, and not on a later turn.** The prohibition
> is stated over exactly three sets of steps and over no others: the **`INDETERMINATE` step
> itself**, **its dependents, transitively**, and **every step the walk did not reach**, which
> behind an `INDETERMINATE` step is every step after it in `steps` order (§2). ADR-0014 §4's
> reason is the whole of it and is quoted rather than restated:
> *"Automatically retrying it would risk acting twice; automatically failing it would risk
> reporting a completed action as failed. So recovery does neither."* A skip records that the
> producer did not act, which is exactly the half of the ambiguity that state refuses to pick.
> **This rule overrides §7's supersession clause** where the two would meet: a plan superseded
> after driving whose walk stopped on an `INDETERMINATE` step leaves that step, its dependent
> branch and every step behind it `PENDING`, and moves none of them to `SKIPPED`/`SUPERSEDED`.

> **Normative — a step already `SKIPPED` before the uncertainty arose stays `SKIPPED`, and this
> section does not reach backwards.** A walk that moved an independent step `PENDING → SKIPPED`
> under §2's skip rule and **then** met an `INDETERMINATE` step later in `steps` order has
> **committed** that skip, at the moment it reached that step, on inputs §2 establishes were
> fixed then and are fixed still. **It stays exactly as it stands, with the `UNMET_DEPENDENCY`
> reason it was written with**, and no lane of this decision reverts it, rewrites its reason, or
> reads the later uncertainty as bearing on it.

> **Normative — the driver is `AttemptState.EFFECT_UNRESOLVED`'s one producer, for a step it
> drove.** The attempt's `state` is committed `EFFECT_UNRESOLVED` through `PlanStore.commit_attempt`
> at the instant a step of the plan it is driving is recorded `INDETERMINATE`, in the same turn
> and before the turn composes. `EFFECT_UNRESOLVED` is a **non-terminal** member (ADR-0249 §5), so
> a later claim of that attempt is **not** refused by §3's conjunct on that ground alone.

> **Normative — the two writes are not one, and what a failure between them leaves is stated.**
> The step's `→ INDETERMINATE` transition and the attempt's `commit_attempt` are **two writes
> under two compare-and-swaps**, and `PlanStore` offers no multi-write commit (#257's own
> observation, one store over). Where the attempt write does not land — a stale
> `expected_version`, a store failure — **the step stays durably `INDETERMINATE` and the attempt
> stays `RUNNING`**, the turn fails as a turn whose store write raised already fails, **nothing is
> re-dispatched and no step is skipped**. **The step's status is the authoritative record of the
> uncertainty** and the attempt's state is the derived convenience, so the residual is a record
> that is *less* informative rather than one that is wrong.

> **Normative — repairing that residual is A8's, and no lane derives around it.** A8's
> reconciliation reads `INDETERMINATE` steps and is the lane that can write the attempt's state
> from one; **no lane infers `EFFECT_UNRESOLVED` at read time** (below), and **no lane retries the
> attempt write from a later turn on its own authority**. §12 carries it.

> **Normative.** **Nothing else writes `EFFECT_UNRESOLVED` under this decision.** In particular
> the startup recovery scan does not: it moves a stranded step `RUNNING → INDETERMINATE`
> (ADR-0014 §4) and touches no attempt today, and **whether it should is A8's**, together with
> everything else about resolving an `INDETERMINATE` step. **No lane infers the state from a
> step's status at read time** — ADR-0249 §6's writer clause binds, and a derived state would be
> the second authority ADR-0249 §5 refuses for *paused*.

**Scoping the prohibition rather than stating it over the whole plan is what keeps it a rule an
implementation can obey.** A skip already committed records what that step's own dependency,
`when` or `resolves` settled about the world, and §2 establishes that every input to that refusal
was fixed when the walk reached it; an uncertainty about a **different** step's effect neither
revises those inputs nor contradicts what they settled. §10 reads the same durable state from the
other side, ruling that a walk carries no licence *"whatever it skipped before stopping"* — which
presupposes exactly the state a blanket prohibition would forbid. **And a prohibition over every
step of such a plan would demand a committed transition have never happened**, which no lane can
deliver: `PlanStore`'s write API is a compare-and-swap over a transition graph in which
`SKIPPED` is terminal (ADR-0014 §4), so the only way to honour it would be to undo a durable
record, which is the fabrication §7 refuses for the same reason.

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

> **Normative — the sweep is several writes, and what a sweep that stops part-way leaves is
> stated rather than inherited.** Each `PENDING → SKIPPED`/`SUPERSEDED` is **its own
> compare-and-swap** and `PlanStore` offers no multi-write commit (#257's own observation, §12),
> so a sweep over two or more `PENDING` steps can land some and not the rest — a stale
> `expected_version`, a store failure. **The residual is exactly what landed**: the steps swept
> are durably `SKIPPED`/`SUPERSEDED`, the steps not swept stay durably `PENDING`, **nothing is
> undone, nothing is re-dispatched, no step is moved to any other status and no `SkipReason` is
> rewritten**, and the turn fails as a turn whose store write raised already fails. **No lane
> retries the sweep, resumes it from a later turn, or reads the mixed state as a plan still
> driving**, and **§6's override binds inside the sweep as it binds outside it** — a sweep that
> meets a step of an `INDETERMINATE` branch skips none of that branch and is not thereby partial.

> **Normative — repairing that residual is A8's, on exactly §6's footing.** A8's reconciliation
> is the lane that reads a plan's leftover statuses and is the only one that may complete a
> sweep; **no lane of this decision derives around the residual, infers `SUPERSEDED` at read
> time, or reads an unswept `PENDING` step as licence to dispatch it.** §12 carries it.

**Leaving the residual rather than retrying it is §6's precedent taken for the same reason, and
the unswept step is not a step anything will run.** What a sweep records is a fact about a plan
**nobody will drive again** — §7's other clauses and §2's stop rule have already put that beyond
the driver — so a half-finished sweep is a record that is *less* complete rather than one that is
wrong, which is exactly the shape §6's partial write leaves. A retry from a later turn would be a
sweep nobody asked for over a plan nobody is driving, and it would have to decide afresh whether
§6's override had come to apply in the interval; that is reconciliation, and A8 owns it. An
atomic sweep would need a `PlanStore` that accepts several transitions in one commit, which is
#257's remaining half and is **not taken here** (§12).

> **Normative — one plan is driven per walk, and it is the plan the turn holds.** The driver is
> handed one `ActionPlan` and one `ExecutionState` and walks that plan's steps. **It never
> dispatches a step of a plan it was not handed**, never merges two plans' steps, and never
> resumes a walk over a plan a later plan supersedes.

> **Normative — a plan whose `targets_revision` is not the goal's current revision is not driven,
> and that refusal is ADR-0249 §8's.** The driver adds no second check of it: the claim is
> refused inside `commit_transition` where the compared value lives, and §3's stop applies.

> **Normative — returning to planning never automatically repeats completed work, and that is a
> requirement on the driver rather than a property of the records.** **A step whose effect the
> goal records as completed or as uncertain is never dispatched a second time**: an effect a
> `SUCCEEDED` and verified step produced, and an effect an `INDETERMINATE` step may have produced,
> are each performed **at most once across every plan of that goal**, whether the later plan
> modifies the earlier one or is planned afresh. **No lane reads a replan as licence to repeat
> an act.**

> **Normative — until A8 lands, the obligation is discharged by §13's Q4 gate and by nothing
> else, so no implementation of this decision is asked to satisfy what it cannot.** No
> consequential capability is wired in that interval, so the acts the obligation governs cannot be
> performed, and **no arm of this decision requires a duplicate dispatch to be demonstrated** —
> that demonstration is part of A8's acceptance requirement (§12), on the lane that lands the
> mechanism.

> **Normative — the obligation is undischarged until A8, and §13's rule is what makes that
> interval safe rather than a hazard.** **L2 does not discharge it**, and no lane reads its
> landing as having done so. What stops the interval being a live duplicate-booking risk is the
> rule §13 carries: **no consequential capability is wired into a production deployment until the
> verification, uncertain-outcome and cancellation guarantees for its class are implemented and
> demonstrated** — and A8's key is one of those guarantees. So the requirement is stated, its
> discharge is named, and the window in which it is unmet is a window with **no real consequential
> integration in it**, which is ADR-0253 §3's construction applied to one more obligation. **A
> normative requirement a lane cannot yet satisfy is not a contradiction where the acts it governs
> cannot yet be performed**, and this decision states both halves rather than softening the first.

> **Normative — the driver discharges it within one execution today, and the mechanism that
> discharges it across plans is A8's, by name.** Within one `ExecutionState` a step already
> `RUNNING`, `SUCCEEDED`, `FAILED`, `SKIPPED` or `INDETERMINATE` is **never re-dispatched by the
> walk**, which is `StepRunner`'s existing guard — ADR-0037 §6's *"`run` enters only at
> `PENDING`"* — relied on rather than re-implemented. **Across two plans of one goal this decision
> lands no mechanism**, and §12 carries the obligation to **A8** with its acceptance requirement.
> **No lane reads this decision as having discharged the requirement across plans**, and no lane
> reads the gap as permission to repeat an act.

**Stating it as an obligation rather than as a description is the point, and the reason is that
the record the obvious mechanism would read does not exist.** #2255's requirement is about the
world — *preserve the real booking* — and it is not satisfied by preserving the **records** of
what happened, which is all §7's other clauses do. So the requirement is written here as what the
driver owes, and the honest part is stated beside it: **a goal records no completed effect** that
a driver could compare against. What the store holds is a `StepExecution` whose `status` is
`SUCCEEDED` and whose `output` is a `JsonValue`, keyed on a `step_id` that a **re-plan mints
afresh** — ADR-0253 §8's own reason for refusing a step id as a durable declaration, *"A re-plan
mints new step ids, so a fresh reading of the same proposition in a later plan would carry a
different declaration"*, applying identically. Two plans that both book a campsite carry two step
ids, two capabilities that may be spelled the same, and two parameter mappings that may or may not
be equal, and nothing in `Goal`, `GoalAttempt`, `ActionPlan` or `ExecutionState` says they are one
act. **A driver that compared capability and parameters would be inventing an identity nobody
declared**, and would refuse a legitimate second booking of two different nights as readily as a
duplicate.

**Planner visibility of what already ran is a help and never the guarantee.** A projection of the
attempt's executions into the planner's input would let a planner *avoid* planning the repeat, and
that is worth having; it is not the property, because a planner is a model and ADR-0249 §7's
asymmetry forbids taking a prerequisite on a model's word — *"A model may never clear a
permission, a coverage test, a prerequisite or a **dependency**"*. **The guarantee has to be
mechanical**, which is what makes it A8's idempotency key rather than a brief widening.

**This is where revision 1 §K.2 step 6 is corrected against the tree.** That step reads *"the
driver refuses to plan or drive a step whose effect the goal records as completed"* — the
requirement is right and the mechanism it names is not available, which is why the clauses above
separate the two.

**ADR-0253 §5 already says this in terms, and this decision does not reach past it.** That section
rules: *"**Nothing in this decision makes an act at-most-once**, and no lane reads a condition as
if it did … Making an intended effect happen at most once is a different mechanism entirely — it
is the idempotency key and the `INDETERMINATE` reconciliation ADR-0014 §7 defers and **A8**
takes."* The driver is not that mechanism either, and saying so here is cheaper than discovering
it in A8.

> **Normative — the route that buys it is A8's idempotency key, and the other is an aid.** The
> mechanical guarantee needs a key the tool dedupes against, which is **A8's** on ADR-0014 §7's
> own deferral. A projection of the attempt's executions into the planner's input would help a
> planner avoid planning the repeat and is a widening against ADR-0253 §10's *"**`GoalBrief` and
> `BriefElement` gain nothing** … The brief carries an element's text and the **kind** of its
> ground and nothing else"* — a brief renders no execution and no step outcome at all. **Neither
> is taken here**, and §12 carries the obligation, A8's acceptance requirement, and the aid's
> trigger.

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

### 9. The deadline: one budget the driver reads, on a monotonic source, and what a walk charges

> **Normative.** **ADR-0042 §3's per-request deadline is attached here, and it is the driver's.**
> The `timeout` an adapter supplies to `converse` or `resume` is the **whole request's** budget.
> **The deadline is fixed once per adapter call**, from the **monotonic** source §9 names below
> at the instant
> `orchestration` enters that call's driving — **before** the resumed step's disposal on a
> `resume`, and before the first step's on a `converse` — and every disposal that call makes,
> **the resumed one and every step of every walk that follows it**, is passed the **remaining**
> duration rather than the whole figure. **No lane passes the adapter's figure unchanged to more
> than one disposal, and no lane fixes a second deadline inside one call.**

> **Normative — it gates starting and never cancels what is running.** Immediately before it
> begins a step's disposal, the driver reads that same monotonic source and computes the
> remainder. Where
> the remainder is **not strictly positive** it **starts no further step** and the walk stops
> (§2). **A step already begun runs to its own completion**, which is ADR-0228 §4's posture in its
> own words — *"a planner call already begun runs to its own completion, and a turn's total
> duration may therefore exceed its budget by one planner call and one servicing"*, read one level
> over as one step's disposal. **The figure passed to
> `StepRunner` is therefore always strictly positive**, which ADR-0029 §4 requires: *"a zero or
> negative duration is refused rather than treated as an instantly-expired deadline"*.

> **Normative — the deadline is an elapsed duration, so it is measured on a monotonic source and
> never on the injected `Clock`.** The driver takes both the deadline and every remainder from
> **the event loop's monotonic clock** (`asyncio.get_running_loop().time()`), which is
> `orchestration/consolidation.py`'s own construction for its run budget and is taken rather than
> re-argued. `core.clock.Clock` is scoped to **wall-clock instants** and ADR-0026's Consequences
> rule the other contract out in terms — *"measuring an elapsed duration across a DST transition
> or an NTP step is a different contract this one does not provide and should not be stretched
> to"*. **A wall-clock reading moved backwards by NTP or an operator would make the computed
> remainder larger**, topping the request's budget up for as long as the correction lasted and
> making a later step's remainder **not** strictly smaller — the two things the clauses above
> forbid, reached through the instrument meant to enforce them.

> **Normative — and no seam, type or collaborator is added for it.** The source is read from the
> running loop at the point of use: **no `core` type is added, no `Clock` is injected for it, no
> constructor parameter is added to `StepRunner`, `StepExecutor` or the driver (ADR-0058), and no
> `Settings` field is minted** (§11, and the no-configurable-figure clause below). **What the
> injected `Clock` is still read for is unchanged and is not this section's**: an instant a rule
> compares against a stored one — ADR-0253 §5's `evidence_recency` among them (§1, §5) — where a
> wall-clock instant is exactly the right contract.

> **Normative.** **A step the deadline stopped is `PENDING` and is never `SKIPPED`** (§2), and the
> remainder is never rounded up, clamped to a minimum, borrowed from a later turn or topped up.

> **Normative — three budgets, and the driver reads exactly one. These are budgets and not time
> sources**: which source measures this one is the clause above, and the count here is of the
> budgets a walk could be gated on. ADR-0042 §3's per-request
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

**Fixing the deadline per adapter call rather than per walk is what stops a resume replenishing
it, and §5's fresh walk is exactly the shape that would.** A `resume(timeout=PT30S)` whose parked
step takes twenty-nine seconds is followed by a whole new walk (§5); a deadline fixed when *that
walk* begins would hand its first step another thirty seconds, so one adapter call carrying one
budget would have spent nearly two. The budget belongs to **the request the user is waiting on**
(ADR-0042 §3), and a request is one `converse` or one `resume` — not one walk, of which a single
`resume` may produce one after the step it answered.

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

### 10. The writer clauses, and how an attempt investigates again after it has executed

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

> **Normative — the furthest phase an attempt reached and what it is doing now are two facts,
> and only the first is `AttemptPhase`.** The stamp stays exactly what §10's clauses above make
> it: monotone, never moved backwards, a high-water mark. **What licenses work is the attempt's
> current activity**, which is not on the stamp and is not derived from it. **No lane reads
> `AttemptPhase` as naming the work an attempt may now do**, and no lane moves it to license any.

> **Normative — the walk returns a typed outcome, and one member of it is an unexpected finding.**
> `orchestration` gains a **frozen stage type carrying the walk's outcome**, on ADR-0037 §4's own
> precedent for `StepDisposition` — *"a frozen dataclass in `orchestration` … it crosses no
> subsystem boundary"* — so **no `core` type is added, `GoalAttempt` gains no field, and nothing
> durable is minted**. A walk ended with an **unexpected finding** when it **ran to the end of
> the plan** and moved **at least one step `PENDING → SKIPPED` under §2's skip rule**: the plan
> declared a requirement about the world — a dependency, a `verifies`, a `when`, a resolvable
> reference — and the world did not meet it.

> **Normative — a walk that stopped carries no licence, whatever it skipped before stopping.**
> Each of §2's five stop triggers leaves a question outstanding or an effect unaccounted for — a
> park the user has not answered, an `INDETERMINATE` nobody has resolved, a disposition that
> committed nothing, a budget that ran out — and **investigating alternatives while one of those
> stands is the hazard §2's park argument names**, reached from the other side: the turn would be
> asking the user about one act and planning a replacement for another in the same breath.
> **The licence is therefore carried only by a walk that finished**, which is the fail-closed
> direction and the one a reader cannot mistake.

> **Normative — an unexpected finding licenses one further investigation round within the same
> attempt, and it satisfies ADR-0251 §4's whole trigger group in place of a serviced read.**
> ADR-0251 §4 admits a further round on a **read** trigger — (b) *"The plan carried a
> `read_request`"*, (c) it was serviced, (d) the servicing completed — and on (j) *"The attempt's
> `phase` is `AttemptPhase.INVESTIGATE`"*. **A re-investigation licence satisfies (b), (c), (d)
> and (j) together**, because the fact it carries is of the same kind those four exist to
> establish: **this attempt has learned something since it last planned**, here from a completed
> walk rather than from a serviced read.

> **Normative — every guard of ADR-0251 §4 binds verbatim and is checked unchanged.** **(a)** the
> turn's operation declares a planning budget; **(g)** the turn is within that budget at the
> moment of the check; **(f′)** the attempt has made fewer `Planner.plan` calls than its kind's
> planner-call allowance; **(h)** its `working` is strictly below the working allowance **less the
> reserve**; **(i)** it has not just completed its second consecutive unproductive round. **A
> licence lifts no budget and no allowance**, and an attempt whose ledger is spent gets no
> licensed round.

> **Normative — the licence places the turn's investigation and is not spent by a round.** It
> satisfies (j) and §1's occupancy **for every round of that turn**, so a round the licence
> admitted that returns a `read_request` is serviced and the **next** round is admitted by (b),
> (c) and (d) as written, with (j) satisfied by the same licence. **Whether there is a further
> round is (b), (c), (d) and the guards' question, and never the licence's**; the licence answers
> *where* the loop is placed and nothing about *how far* it goes.

> **Normative — one licence per turn, and a walk under it carries none.** A turn holds **at most
> one** re-investigation licence however many walks it makes: **a second walk carries no licence**,
> whatever it skipped, so a turn cannot alternate walking and investigating without bound.
> **No implementation re-derives a licence from a walk that already ran under one.**

> **Normative — ADR-0251 §1's occupancy clause is partially superseded, and it is the second of
> this decision's two scopes on that ADR rather than part of the first.** That
> section rules *"**Every round of one attempt's investigation sits inside one occupancy of
> `AttemptPhase.INVESTIGATE`**"* and *"There is no re-entry into `INVESTIGATE` from a later phase,
> and no clause of this decision creates one."* **A round sits inside one occupancy of
> `INVESTIGATE` *or* under a re-investigation licence**, and **no round moves the phase in either
> case** — §1's own rule, and the clause forbidding re-entry into `INVESTIGATE` binds **verbatim**
> and is obeyed rather than lifted: a licensed round **does not re-enter that phase**, which is
> exactly why the licence and not the phase is what places it. **§1's every other clause binds
> entire**: a round is one planner call with its servicing, the turn is assembled once, the supply
> stays monotone across a turn's rounds and is inherited by no later turn, and each round's call
> receives the `GoalBrief` as it stands.

> **Normative — the allowance is charged and never reset, and no attempt is opened.** ADR-0251
> §13 binds entire: *"**A replan never resets an allowance.** A revision within an attempt
> consumes from the same `AttemptEffort`; so does a recovery, a branch, a phase transition and a
> later turn of the same attempt."* ADR-0250 §12 binds entire: **no act of this decision opens an
> attempt**, and a licensed round runs inside the attempt that executed. **An attempt whose
> allowance is spent gets no licensed round**, and what it does instead is compose and report.

> **Normative — the phase does not move, and nothing about §10's monotonicity is weakened.** An
> attempt that investigates again after executing stays stamped at the furthest phase it reached;
> **it does not return to `INVESTIGATE`**, no lane re-stamps a phase it has left, and ADR-0249 §6
> binds exactly as §10 states it. **The licence is the carrier and the phase is the record**, and
> keeping them apart is the whole of this section.

> **Normative — a turn that investigates again drives again, and ADR-0228 §5's two per-turn
> clauses become per-walk. This partially supersedes ADR-0228 §5** in the **first** of the three
> scopes §16 states.
> That section rules *"**Every plan of the turn is persisted before anything is driven.** The whole
> sequence of `save_plan` calls precedes `start_execution`"* and *"**Exactly one plan of a turn is
> driven and it is the last**"*. Both are stated over a **turn** and both become statements over a
> **walk**: the plans produced for a walk are **all persisted before that walk's
> `start_execution`**, and **exactly one plan is driven per walk and it is the last of the plans
> produced for it**. A turn makes **at most two** walks — its first, and one after a licensed
> investigation — so it drives at most two plans and persists each set before the drive it
> precedes.

> **Normative — two further clauses of §5 are this decision's second and third scopes on it, and
> they are named rather than assumed to survive.** *"A superseded plan **drives nothing**. It
> starts no execution, reaches no `StepRunner`…"* is stated of a plan that **is** superseded, and
> a first plan becomes superseded by the licensed round's successor **after** it has driven. It
> binds **of a plan superseded before its walk began**, which is every plan ADR-0228 §5 was
> written about; **it does not retrospectively forbid a walk that had already run when the
> supersession was recorded**, and no lane reads it as requiring a driven plan's execution to be
> undone. And §5's **no-new-failure-mode** clause — *"A `save_plan` that raises on a superseded
> plan fails the turn exactly as one raising on any other plan does today"* — held because every
> `save_plan` preceded every drive; a licensed round's save can now fail **after** a side effect,
> which is a failure mode §5 did not admit.

> **Normative — what a second walk's persistence failure leaves behind, stated rather than
> inherited.** Where the licensed round's `save_plan` raises, **the first walk's execution and its
> effects stand exactly as they are** — nothing is undone, no step is re-dispatched and no
> `SkipReason` is written — **no second walk begins**, and the turn fails as a turn whose
> persistence raised already fails today. **The durable record is complete about what happened**:
> the first plan, its execution and its outcomes are on disk because §5's own oldest-first rule
> put them there before the drive. What is lost is the plan nobody could persist, which is the
> same loss §5 accepts for a turn's second plan today, arriving one walk later.

> **Normative — §5's remaining clauses bind verbatim, and its reason is kept rather than
> weakened.** The every-plan-of-the-turn-is-persisted rule itself, the oldest-first order, the
> a-turn-that-ends-before-that-site-persists-nothing rule and the one-persistence-site rule each
> bind entire. **§5's reason for the ordering is that a turn whose second
> `save_plan` raises *"has driven nothing: no execution is open, no capacity slot is spent on a
> step and no side effect has been reached"*** — a protection for a turn that **has not yet
> acted**. Before a turn's first walk that is the whole turn and the clause binds exactly as
> written. Before a second walk the turn **has** acted, an execution **is** open and a side effect
> **has** been reached, so there is no such state left to protect and the per-turn reading would
> forbid the licensed investigation while buying nothing at all.

> **Normative — the licensed round is admitted before the turn composes, and composing is what
> it displaces.** The licence is read at the instant the walk returns, and the round it admits
> runs **before** the composing call — which is the only ordering that buys anything, because a
> round after the answer is composed is a round the answer could not mention. Where no round is
> admitted, for any of §4's guards or because no licence was carried, **the turn composes exactly
> as it does today**: ADR-0251 §6's *"**Composing and verification are not gated on the attempt's
> allowance at all**"* binds entire, and **no clause of this decision can stop a turn answering**.

> **Normative — what is preserved across a licensed round.** Every `GoalEvidence` row the attempt
> holds, every `ExecutionState` it drove, and every `SUCCEEDED` step's `output` **stay exactly as
> they stand**; ADR-0252 §§8–9 alone decide which rows are superseded or invalidated, and §7's
> clauses decide what becomes of the executions. **A licensed round discards nothing and re-runs
> nothing.**

**This is ADR-0253 §9's re-entry, stated in the one form the corpus admits.** That section rules
*"An unexpected finding returns the work to an earlier phase rather than improvising in this
one"*, and §10's clauses above decline to move the attempt backwards because ADR-0249 §6 forbids
it and §12's derivation depends on it. The resolution is that *"returns the work"* is about **what
the attempt may do next**, not about **which stamp it carries** — and once those are two facts,
both clauses hold at once. ADR-0251 §4(j)'s own reasoning is what makes the scope narrow rather
than invented: it bars iteration outside `INVESTIGATE` because *"iterating there would either run
the loop in a phase §1 does not place it in, or move the phase backwards, which ADR-0249 §6
forbids"*, and it reserves the rest in terms — *"**How a later turn's planning relates to an
attempt that is authorizing, executing or verifying is A7's and A9's**"*. Neither of its two
hazards is reached here: the phase does not move, and the loop is placed by the licence rather
than by a phase it does not occupy.

**Without this an attempt that acts and learns something is finished, and the system's own rules
would make it so.** The campsite case is the ordinary one: the walk checks availability, the
interpretation returns `DOES_NOT_QUALIFY`, the booking step is `SKIPPED`/`UNMET_DEPENDENCY`, and
the attempt now knows something it did not know when it planned. Under (j) unamended it may make
its turn's one ungated planner call and then **may not iterate over what it just learned** — so
*investigate alternative sites* is unreachable inside that attempt, while ADR-0249 §5 and
ADR-0250 §12 forbid the system opening a new attempt to escape the bar. The user would have to
ask again to get a system that had already found the answer. **The bound that matters is not lost
by lifting it**: (f′), (h) and (i) all still bind, so a licensed round is spent from the same
ledger and stops on the same three guards.

> **Normative.** **The driver edits no plan.** ADR-0253 §10's four-field clause is untouched:
> `supersedes`, `targets_revision` and each `StepCondition.about` and `PlanInterpretation.settles`
> are the fields another component sets, all four at the `Planner.plan` seam's return, and **the
> driver sets none of them**. A resolved reference is placed in the `parameters` the request
> carries and is **never written back into the stored `PlanStep`** — ADR-0014 §2's frozen plan
> binds, and a plan that recorded its own resolutions would stop being the record of a decision
> and become a record of a run.

### 11. The `core` surface, the wire, the stored shapes, and the export

> **Normative — what `core/types.py` gains.** **One field**: `StepTransition.attempt_id`, an
> `Identifier | None` defaulting to `None`, with the model validator §3 states. **Nothing else** —
> and in particular **§10's walk outcome is an `orchestration` stage type and not a `core` one**,
> on ADR-0037 §4's precedent for `StepDisposition`, so it crosses no subsystem boundary, rides no
> frame, enters no export and is not persisted.
> No new model, no new enumeration, no new constant, and no widening of `StepExecution`,
> `ExecutionState`, `ActionPlan`, `PlanStep`, `GoalAttempt` or `Goal`.

> **Normative — this is a BREAKING contract change under golden rule 5, and it is breaking in two
> ways rather than one.** **For the constructor**: `StepTransition`'s validator requires
> `attempt_id` on every `→ RUNNING` transition, so **every existing construction of one without it
> stops validating** — `StepExecutor._claim` and every test, fixture and canonical fake that builds
> a claim — and **L1 migrates each of them in the same change**. **And for the Protocol**: what a
> conforming `PlanStore` must refuse moves on three members (below). Transitions to every other
> status are untouched, `recovery.py`'s `→ INDETERMINATE` among them, because the field is
> forbidden there and absent there today. `StepRunner` and `StepExecutor` are concrete
> `orchestration` classes and **not** Protocols, so §3's threaded keyword changes no contract
> surface at all. `PlanStore`'s signatures do **not** move and `PlanStore` gains **no member**;
> what changes is what a conforming implementation must **refuse**, on **three** members. §3 adds
> one conjunct to **`commit_transition`**, and the execution-ownership refusal to
> **`commit_attempt`** and to **`open_attempt`**. Each is a **strengthening of an existing
> member** rather than a new one, exactly as ADR-0249 §12 classifies the first one. **The existing `PlanStore`
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
- **Repairing an attempt left `RUNNING` beside an `INDETERMINATE` step**, where §6's second write
  did not land. **A8**, which reads `INDETERMINATE` steps and is the only lane that can write the
  attempt's state from one. §6 states what the residual is and that nothing re-dispatches or
  derives around it; nothing here retries that write from a later turn. Fired by A8's
  reconciliation landing.
- **Completing a supersession sweep that stopped part-way**, where §7's second or a later
  `PENDING → SKIPPED`/`SUPERSEDED` commit did not land. **A8**, which reads a plan's leftover
  statuses and is the only lane that may finish one. §7 states what the residual is and that
  nothing is undone, re-dispatched or retried; nothing here sweeps again from a later turn, and
  the atomic alternative is #257's remaining half, also not taken. Fired by A8's reconciliation
  landing.
- **Whether the startup recovery scan writes `EFFECT_UNRESOLVED` on the attempt of a step it
  found `RUNNING`.** **A8.** §6 gives the state one producer — the driver, for a step it drove —
  and the scan runs outside a turn with no attempt in hand. Fired by the lane that gives the scan
  an attempt to write to.
- **Verification against the goal's criteria, strength proportional to consequence, which
  `AttemptOutcome` an attempt earns, and the producer of `GoalStatus.ACHIEVED`.** **A10.** §8
  fixes that `verifies` is not it.
- **`GoalStatus.BLOCKED`'s producer.** **A3**, as ADR-0249 §4 and ADR-0250 §12 reserve it. A walk
  that stops writes no `GoalStatus` at all.
- **The mechanism that makes an effect at most once across two plans of one goal, and the arm
  that establishes it.** **A8.** §7 states the **obligation** — a step whose effect the goal
  records as completed or as uncertain is never dispatched a second time, across a modified plan
  and a freshly planned one alike — and this decision lands no mechanism that could enforce it, so
  **A8's acceptance requirement is stated here and is owed on that lane**: *no duplicate dispatch
  of a completed or uncertain effect across a replan, demonstrated over **both** a plan that
  modifies the earlier one and a plan produced afresh.*

  **The arm is A8's and is written here so that lane inherits it rather than invents it**: a plan
  driven to a `SUCCEEDED` and verified step, superseded on a later turn by a plan whose step would
  perform the same effect, where the later step is **not dispatched**; and the paired case over an
  **`INDETERMINATE`** first step, where it is likewise not dispatched, because an effect that may
  have happened is not an effect to repeat. **It is deliberately absent from §15.** An arm
  demanding a demonstration a decision's own lanes cannot make is a demonstration nobody can give,
  and ADR-0255's lanes land no key — so §15 asserts what a walk preserves and asserts nothing
  about a second dispatch. **Until A8 lands, §13's Q4 gate is what discharges the obligation**: no
  consequential capability is wired, so the acts it governs cannot be performed.
- **Whether an attempt's executions are projected into the planner's input**, so a planner can
  avoid planning a repeat. **Not decided**, and §7 states why it is an aid rather than the
  guarantee — a planner is a model, and ADR-0249 §7 forbids taking a prerequisite on a model's
  word. It is a widening against ADR-0253 §10's *"`GoalBrief` and `BriefElement` gain nothing"*
  and would carry its own containment argument. Fired by a measured planner failure that A8's key
  does not already prevent.
- **#257's remaining half — making the ruling and the transition atomic.** **Not decided.** §5
  answers what the driver does when it meets a stranded step, using the by-step query ADR-0044 §3
  landed. Making the pair atomic needs a `PlanStore` that accepts more than one transition in a
  commit, which #257 itself calls *"a contract change with a much wider blast radius, and arguably
  the wrong shape for a store whose whole write API is a single compare-and-swap."* Fired by an
  ADR that takes it.
- **An automatic re-drive of a stopped walk** — continuing a plan after an `INDETERMINATE` step
  is resolved, or re-reaching a step an `AMBIGUOUS_CAPABILITY`, `INVALID_PARAMETERS` or
  `EGRESS_UNBINDABLE` disposition left `PENDING`. **A8** for the first, which is the lane that
  resolves an `INDETERMINATE` step and is the only one with something new to drive on; **not
  decided** for the rest, each of which is a deployment or a plan defect corrected by the user
  asking again rather than by a mechanism. §2 leaves every such step `PENDING` and adds no route
  back to it beyond §5's resume. Fired by A8's reconciliation landing.
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

- **L1 — the conjunct and the ownership invariant.** `core/types.py`'s one field and its
  validator; **all three** of §3's strengthenings in `InMemoryPlanStore` and `SqlitePlanStore` —
  `commit_transition`'s added claim condition, and the execution-ownership refusal on
  `commit_attempt` **and** on `open_attempt`; the shared `PlanStore` conformance suite arms for
  each (§3's test 3, arm 6's two serial ownership cases, its two **dispatched-together** arms and
  its class assertions) and the canonical fake in
  `ai_assistant.testing`; and the
  `wire/envelope.py` log entry and version bump **only if** the tree contradicts §11's dated
  observation; and §3's threading — the `attempt_id` keyword on `StepRunner.run`,
  `StepRunner.resume` and `StepExecutor.execute`, supplied by `engine.py`'s existing single-step
  drive from the `GoalAttempt` it already holds. It **drives nothing** and changes no behaviour of
  a turn: the one `→ RUNNING` claim in the tree is `StepExecutor._claim`, and after L1 it carries
  the attempt the engine opened.
- **L2 — the driver, and the runner's request construction.** The plan-driving stage in
  `orchestration/`, the walk, §1's three driver evaluations and **`StepRunner`'s resolution of a
  step's `resolves` from the stored plan and execution while it builds the request** (§1), §2's
  stop and skip rules, §5's park re-evaluation and the fresh walk that follows it, §6's
  `EFFECT_UNRESOLVED` commit, §7's supersession skip, §9's one deadline per adapter call, **§10's
  walk outcome and the licensed investigation round it admits — which is where ADR-0251 §4's (j)
  is read with its new alternative** — and the retirement of `engine.py`'s single-step path.
  **It adds no `core` type and no field**, both
  being L1's, and **it gives no entry point a parameter for a resolved value** (ADR-0253 §6).

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
> fakes**: the arms 1–13 below, every one over `ai_assistant.testing`'s canonical fakes with no
> consequential integration wired. **M34 owes arms 14–18**, and no lane reads an M33 arm as having
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
3. **`UNMET_DEPENDENCY` gets its first producer**, parameterized over every case §2's skip rule
   names — a `FAILED` producer and a `SKIPPED` producer for the first; a **`SUCCEEDED` producer
   whose `verifies` does not hold** for the second, over a step declaring `FIELD_PRESENT` whose
   output is `{}` and carrying **no** `resolves`, so the dependency alone refuses it; an
   unsatisfied `when` for the third; and each of ADR-0253 §6's **six** unresolvable-reference
   cases for the fourth — ten inputs over four rules. Each asserts the step is `SKIPPED` with
   that reason **at the
   moment the walk reached it** and that no request was built.
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
   did not move**, which is what makes this conjunct not redundant with the previous arm's. **And
   the arm that pins the binding**: with execution E opened under attempt A, A committed `ENDED`,
   and a second attempt **B non-terminal on the same goal**, a claim for E naming **B** is
   **refused** — every goal-level fact about B is satisfactory and B's `execution_ids` does not
   carry E, which is the only thing that decides it (§3). **And the arm that closes the bypass**,
   in the shared `PlanStore` conformance suite: `commit_attempt(add_execution_id=E)` on **B**
   after A already holds E is **refused**, so the state in which E belongs to two attempts —
   under which a claim naming B would pass every conjunct — **cannot be reached through the
   store** (§3). **And every ownership refusal asserts its class, not merely that it refused**:
   `StaleExecutionError` **subclasses** `PlanningError` (`core/errors.py`), so an arm asserting
   only `PlanningError` is satisfied by the retryable class §3 forbids here — a caller obeying
   that class's contract would then retry a permanently invalid write forever. Each of the three
   ownership paths — `commit_attempt`'s, `open_attempt`'s, and `commit_transition`'s
   duplicate-ownership limb, the seeded legacy claim included — asserts a `PlanningError` that is
   **not** a `StaleExecutionError`, and the four retryable limbs of §3's conjunct assert
   `StaleExecutionError` positively, so an implementation cannot satisfy the set by collapsing the
   two. **And the same case through the other door**: `open_attempt` with a
   `GoalAttempt` whose `execution_ids` already names E is **refused** on the same terms, because
   that member takes a whole attempt and the tuple may arrive non-empty — a caller could otherwise
   reach the forbidden state without calling `commit_attempt` at all. A paired arm asserts the
   append is still idempotent on the attempt that owns it, which is ADR-0249 §12's own clause and
   is untouched. **And the legacy arm**: a store seeded — beneath the refusals, as only a
   pre-decision store could be — with execution E named by both a `CANCELLED` attempt A and a live
   attempt B, where a `→ RUNNING` claim for E is **refused whichever attempt it names**, and §5's
   recovered resume refuses on the same state. The arm is what stops the cancellation bypass
   surviving in a database written before this decision. **And the arms that pin the
   indivisibility**, in the same suite and on its own existing construction — ADR-0249 §12's
   `test_two_interpretations_dispatched_together_leave_one_loser` and its `commit_attempt` twin,
   which dispatch both commands before either completes: `commit_attempt(add_execution_id=E)` on
   **A** and on **B** dispatched together over an execution **no attempt yet owns**, and
   `open_attempt` carrying E raced against `commit_attempt(add_execution_id=E)`, each asserting
   **exactly one write lands** and the loser raises the **non-stale `PlanningError`**. §3 states
   that each member decides exclusivity *"in the same indivisible step as its own write"*, and the
   serial arms above cannot see the interleaving that rule is stated about: an implementation that
   read, compared and then wrote across a suspension passes every one of them while letting both
   appends land — reaching, through the door this decision closes, exactly the legacy duplicate the
   arm above is reduced to refusing.
7. **The store-level invariant, in the shared `PlanStore` conformance suite** (§3's test 3), over
   both implementations and the canonical fake: no `→ RUNNING` transition is ever accepted whose
   goal revision is not the stored one, and none whose attempt is absent, does not carry this
   execution in its `execution_ids`, or is terminal. **And `attempt_id` on any other `to_status`
   is not constructible.**
8. **A parked middle step, answered and resumed** — a three-step plan whose **second** step rules
   `CONFIRM`: the walk stops, step 3 is `PENDING` and **not** `SKIPPED`, no third step is
   dispatched, the attempt is `AWAITING_AUTHORIZATION`, and the turn carries the confirmation.
   `resume` then disposes of step 2 and the driver **walks the plan again**, passing over the now
   terminal steps 1 and 2 and reaching step 3 — from the stored execution and not from a carried
   index. A paired arm answers `DENY`: step 2 is
   `SKIPPED`/`APPROVAL_DENIED`, and step 3 — declaring `depends_on` step 2 — is
   `SKIPPED`/`UNMET_DEPENDENCY`. **And the arm that pins the overtake**: with step 2 durably
   `AWAITING_APPROVAL` and step 3 `PENDING`, a walk started afresh over that execution — the shape
   a restart produces — dispatches **nothing**, because it meets step 2 first. A driver that
   sought to the first `PENDING` step would dispatch step 3, which is the defect §5's
   start-at-position-one rule makes unreachable rather than checks for.
9. **"Restart during approval"** — the same plan parked at its second step; a **fresh** engine over
   the same durable state recovers it through `pending_confirmations()` (ADR-0052 §1), answers it,
   and the driver's next walk reaches step 3. The arm asserts the recovery is over steps and not
   positions, by parking at a middle step rather than a first.

10. **A commits-nothing disposition stops the walk** — a three-step plan whose **second** step
    draws `AMBIGUOUS_CAPABILITY`: the walk stops, step 2 is `PENDING` **at its stored version**
    with no ruling recorded and no audit entry written, step 3 is `PENDING` and **not** `SKIPPED`,
    and no `ActionRequest` is built for step 3. Parameterized over `INVALID_PARAMETERS` and
    `EGRESS_UNBINDABLE`, which §2 treats alike and whose member docstrings assert the same durable
    state. The arm is what distinguishes this trigger from `NO_CAPABLE_TOOL`, which **does** commit
    a skip and whose dependents are therefore disposed of by §2's skip rule rather than left.

11. **A park answered after its evidence went stale dispatches nothing** — step 2 declares a
    fifteen-minute `evidence_recency` and a `when` the goal's one row satisfies; the step parks;
    the clock advances past the requirement with the confirmation still unresolved and the goal's
    revision and the attempt both unmoved. On `approved=True`: **`StepRunner.resume` is never
    called**, no resolving decision is recorded, `ToolInvoker` is **never entered**, the step is
    still `AWAITING_APPROVAL` at its stored version, the confirmation is still **unresolved** and
    answerable, and the walk stopped. The paired arm answers **`approved=False`** on the same
    state and asserts the opposite: `resume` **is** called and the step is
    `SKIPPED`/`APPROVAL_DENIED`, because a denial is gated on nothing (§5).
12. **Phase 4's four dispositions, one arm each.** **Deferred**: the two-step dependent plan of
    arm 1 passes phase 4 and the attempt advances to `AttemptPhase.EXECUTE`, **with step 2's
    dependency and `when` both unsatisfied at that moment**; and — the case a step-only rule
    misses — a **one-step** plan whose single step's `when` requires the verdict of an
    interpretation of that same plan carrying a **`record`**, over a goal holding **no**
    qualifying row, **also passes**, because ADR-0253 §8 performs that interpretation before the
    first step is dispatched and §1 places it inside the walk. **Failed**: a one-step plan whose
    `when` no row satisfies and which waits on nothing this plan produces is replanned under
    ADR-0254 §14's unchanged limb. **Not covered**: a one-step transmitting plan with complete
    literal arguments and no covering authorization takes §14's `CONFIRM` park and the attempt
    commits `AWAITING_AUTHORIZATION` — **and is not replanned**, which is the disposition this
    decision routes nothing away from. **Passed**: a one-step plan needing none of it advances.
    Arm 1's plan is driven **through** phase 4 rather than around it.

13. **An unexpected finding is investigated inside the same attempt, and the ledger is charged**
    — the concrete case, end to end on fakes. A goal to book a campsite; a plan whose step 1
    checks availability, whose interpretation settles *the site is available* and whose step 2
    books it. Step 1 succeeds, the interpretation returns `DOES_NOT_QUALIFY`, and step 2 is
    `SKIPPED`/`UNMET_DEPENDENCY` — so the walk's outcome carries an **unexpected finding** (§10).
    The arm asserts, in this order: the investigation loop **runs again inside the same attempt**,
    admitted by ADR-0251 §4 with (j) satisfied by the licence; **`AttemptEffort.planner_calls` and
    `working` both advanced and neither was reset** (ADR-0251 §13); **no new attempt was opened**
    (ADR-0250 §12), asserted against `attempts_of(goal_id)`; the attempt's `phase` is **still**
    where it stood and did **not** return to `INVESTIGATE` (ADR-0249 §6, §10); and **every
    `GoalEvidence` row and every `ExecutionState` the attempt already held is unchanged**,
    including step 1's `output`. Three paired arms: with the allowance **spent**, no further round
    is admitted and the turn composes instead; with the walk **stopped** rather than skipped — a
    park, an `INDETERMINATE`, a deadline — **no licence is carried and no round is admitted**; and
    with the attempt's phase at `INVESTIGATE`, the round is admitted by (j)'s original limb with no
    licence needed. **And the arm that pins the trigger group**: the driven plan carries
    **`read_request=None`**, so ADR-0251 §4's (b), (c) and (d) are each unsatisfied on their own
    terms and the round is admitted by the licence alone — which is what a supersession of (j)
    by itself would not have bought. A further paired arm asserts the licence admits **one** round:
    where the round it admitted returns a plan carrying a `read_request` that is serviced, the next
    round is admitted by (b), (c) and (d) as written **with (j) satisfied by the same licence**,
    and where it returns none, no second round is admitted. **And the arm that pins what the turn
    then does with the plan**: the licensed investigation's last plan is persisted **after** the
    first walk's `start_execution` and is driven by a **second walk**, the first walk's plan and
    execution are unchanged, and the turn drove **two** plans and no more — which is ADR-0228 §5's
    two clauses read per walk (§10) — **and the second plan passes phase 4 before that walk
    starts**, asserted by a paired case in which the licensed round returns a plan whose first
    step's `when` no row satisfies and which waits on nothing that plan produces: phase 4 **fails**
    it under ADR-0254 §14's unchanged limb, **`start_execution` is never called** and no
    `ActionRequest` is built, so the second walk is gated exactly as the first. A final paired arm
    asserts **one licence per turn**: the second walk carries none, whatever it skipped. **And a
    persistence arm**: where the licensed round's `save_plan` raises, the first walk's execution
    and its `SUCCEEDED` step are unchanged, no second walk begins, and nothing is re-dispatched.

**Full — M34, owed there and not established here.**

14. **Mid-plan `INDETERMINATE`, and the residual when its second write does not land** — a
    three-step plan whose second step returns `INDETERMINATE`:
    the walk stops, step 3 stays **`PENDING`** whether or not it depends on step 2, **no step is
    `SKIPPED`**, and the attempt's `state` is `EFFECT_UNRESOLVED` **before** the turn composes. A
    paired arm asserts a plan superseded in that state moves **no** step to `SKIPPED`/`SUPERSEDED`
    (§6's override of §7). **And two arms over the partial write** (§6): with the step's
    `→ INDETERMINATE` transition committed and the following `commit_attempt` failing — once on a
    stale `expected_version`, once on a store failure — the arm asserts the exact residual, that
    **the step stays `INDETERMINATE`**, **the attempt stays `RUNNING`**, the turn **fails**, **no
    later step is dispatched and none is skipped**, and the committed step transition is **not
    lost or retried**. They are what stop an implementation composing over the failure, sweeping
    the remainder, or re-driving the step. **And the arm that pins the scope of the no-skip
    rule** (§6): a three-step plan whose **first** step is independent of the others and is
    `SKIPPED`/`UNMET_DEPENDENCY` on an unsatisfied `when`, whose **second** returns
    `INDETERMINATE`, and whose **third** the walk never reaches. The arm asserts that after the
    uncertainty is recorded the first step is **still** `SKIPPED` with its original
    `UNMET_DEPENDENCY` reason, that nothing reverted or rewrote it, that the second and third are
    `PENDING` and neither is skipped, and — on a paired case that supersedes that plan — that the
    sweep moves the first step not at all and the second and third not at all (§6's override of
    §7). It is what stops an implementation reading §6 as a rule over the whole plan and trying
    to undo a committed transition.
15. **Replan after partial execution preserves what happened** — a plan driven to its second
    step, superseded on a later turn: the first plan's `ExecutionState` and its `SUCCEEDED` step's
    `output` are unchanged, the attempt's `execution_ids` names both executions, and the
    superseded plan's still-`PENDING` steps are `SKIPPED`/`SUPERSEDED`. **The arm asserts
    preservation and asserts nothing about a second dispatch**: whether the later plan's act
    happens at most once is §7's obligation, whose mechanism and whose demonstration are **A8's**
    (§12). **No arm of this decision requires a duplicate dispatch to be shown**, because no lane
    of this decision can prevent one. **And two arms over the partial sweep** (§7): a superseded
    plan with **two** still-`PENDING` steps where the first `PENDING → SKIPPED`/`SUPERSEDED`
    commit lands and the second raises — once on a stale `expected_version`, once on a store
    failure — asserting the exact residual, that the **first step stays `SKIPPED`/`SUPERSEDED`**,
    the **second stays `PENDING`**, no step takes any other status and no `SkipReason` is
    rewritten, the turn **fails**, nothing is re-dispatched, and the committed skip is **not lost
    or retried**. They are what stop an implementation rolling the sweep back, sweeping again
    from a later turn, or reading the mixed state as a plan still driving.
16. **The deadline, decremented across steps and not replenished by a resume** — a three-step
    plan under a budget that two steps exhaust: each `StepRunner.run` receives a **strictly
    smaller and strictly positive** remainder, the third step is never started, it is `PENDING`
    and not `SKIPPED`, and a step already begun ran to completion past the deadline. **The arm
    that pins the resume**: a `resume(timeout=PT30S)` whose parked step takes PT29S leaves the
    following walk's first step approximately **PT1S** and not PT30S, so one adapter call spends
    one budget (§9). **And the arm that pins it across a licensed investigation**: a first walk
    and the licensed round together exhaust the `converse` deadline, and the **second walk starts
    no step** — asserted on the injected monotonic source, against an implementation that would
    otherwise fix a fresh deadline when the second walk begins. A paired arm asserts
    `AttemptEffort.working` advanced by both walks and by the licensed round, and `planner_calls`
    by the round alone. **And the arm that pins which clock is read** (§9): with the injected
    `Clock` moved **backwards** between two steps — and, on a paired case, returning the **same**
    instant twice — the second step's remainder is still **strictly smaller** than the first's and
    the budget is **not** topped up, so a driver that computed the remainder from the wall clock
    fails it. It is what stops ADR-0026's reserved contract being reached for here by accident.
17. **A9's tests 1, 2 and 4**, stated here so the set is legible and **owed on A9's lane**.
18. **Real integrations**, under §13's rule: a consequential capability is wired only once A8's,
    A9's and A10's guarantees are implemented and demonstrated.

### 16. Records owed on earlier ADRs, under ADR-0082 §1

**Exactly three documents are partially superseded — ADR-0254 in one scope, ADR-0251 in two and
ADR-0228 in three** — and the entries below
show the working for it and for each other document a reader would expect to be superseded and is
not: ADR-0037, ADR-0249, ADR-0014, ADR-0042 and ADR-0253 among them — the same list the `Status`
line's no-other-ADR clause names. ADR-0082 §1's test
is applied to each earlier ADR's **text**.

**ADR-0254 §14 — partially superseded in the field of one enumeration, and the scope is on this
document's `Status` line.** A reader holding only §14 evaluates a dependent plan's second step at
phase 4, finds its `depends_on` unsatisfied because the producer has not run, reads *"A
deterministic check failed on the plan"*, and replans — producing a plan whose second step is
unsatisfied for the same reason, forever. So that reader **never dispatches a dependent plan at
all**, which is ADR-0070 §1's test met and **partial** in ADR-0070 §3's sense: the scope is §14's
two-case enumeration and nothing else. §1 states the third case and the test that sorts a
**deferred** check from a **failed** one, and ADR-0253 §2's `INDETERMINATE` treatment is the
precedent — a dependency *"neither dispatched, skipped nor resolved"* while its producer's
disposal is outstanding. **Every other clause of ADR-0254 binds entire and is relied on**: §3's
coverage conditions, §13's recheck-at-`decide` and its no-cached-verdict rule, §14's other clauses
as the `Status` line enumerates them, §17's Q4 rule (§13 of this document), and §19's reservation
of the re-entry mechanism to A7, which §10 discharges.

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
`ExecutionState` and its resumability argument are what §5 reads each walk's dispositions from;
§4's transition graph, its `→ RUNNING`-before-invoke ordering, its `approval_ref` rule, its
`PENDING → SKIPPED` row with `SUPERSEDED`, and its `INDETERMINATE` treatment are each taken as
written; §5's
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

**ADR-0251 §4 and §1 — partially superseded in two scopes, each on this document's `Status`
line.** A reader holding only §4 builds an attempt that executes, learns from a
`SKIPPED`/`UNMET_DEPENDENCY` step that the world is not as it planned, makes its turn's one
ungated call, and **cannot iterate over what it just learned**: (j) is false because the phase has
advanced, and (b), (c) and (d) are false because the finding came from an executed step rather
than from a serviced read. A reader holding only §1 refuses the round on a second ground — every
round *"sits inside one occupancy of `AttemptPhase.INVESTIGATE`"*. Meanwhile the decisions fixing
which acts open an attempt forbid opening a fresh one to escape either bar, so *investigate
alternatives* is unreachable inside that attempt without the user asking again. **Both are
ADR-0070 §1's test met and both are partial in ADR-0070 §3's sense**: the scopes are §4's four
trigger conditions and §1's one occupancy term, and nothing else. §10 states the licence, the
typed walk outcome that carries it and the guards that still bind. **(j)'s own two hazards are
each avoided rather than accepted** — the phase does not move, and the loop is placed by the
licence rather than by a phase it does not occupy — and §1's no-re-entry clause is obeyed rather
than lifted, a licensed round re-entering no phase at all. **(j)'s own reservation is the
warrant**: *"**How a later turn's planning relates to an attempt that is authorizing, executing or
verifying is A7's and A9's**"*. §10 takes the **executing** limb; §12 leaves the authorizing and
verifying limbs to A9. **Every other clause of ADR-0251 binds entire and is relied on** — §4's
(a), (e), (f′), (g), (h) and (i), its never-gated first call and its `NOT_ITERATED` record; §1's
round definition, its no-round-moves-the-phase rule, its turn-assembled-once rule, its
monotone-supply rule and its brief-as-it-stands rule; §5's figures; §6's reserve and its
ungated-composing clause (§9, §10); and §13's *"A replan never resets an allowance"*, which is what
makes a licensed round **charge** rather than refresh.

**ADR-0228 §5 — partially superseded in three scopes, every one of them §5's, and each is on this
document's `Status` line**: its **two per-turn clauses**, in their subject; its
**superseded-plan-drives-nothing rule**, in the moment it binds at; and its **no-new-failure-mode
clause**. A reader holding only §5 requires *"The whole sequence of `save_plan` calls precedes
`start_execution`"* and *"Exactly one plan of a turn is driven and it is the last"* of a **turn**
— so a turn whose licensed investigation produces a plan after its first walk may neither persist
that plan nor drive it, and the investigation §10 licenses can change nothing. That is ADR-0070
§1's test met and **partial** in ADR-0070 §3's sense: the **first** scope is those two clauses'
subject, which becomes the **walk**, and nothing else of them. **§5's reason is what decides the
scope rather than being set aside by it**: the ordering exists so that a turn whose second
`save_plan` raises *"has driven nothing: no execution is open, no capacity slot is spent on a step
and no side effect has been reached"* — a state that obtains before a turn's first walk and cannot
obtain before its second, so the per-turn reading forbids the investigation and protects nothing.
**The second and third scopes are two further clauses of §5**, named rather than left inside the
first, and §10 states both: *"A superseded plan **drives nothing** … reaches no `StepRunner`"*
binds of a plan superseded **before its walk began** and does not retrospectively forbid a walk
that had already run, and the **no-new-failure-mode** clause held because every `save_plan`
preceded every drive — which a licensed round's save no longer does, so §10 states what a second
walk's persistence failure leaves behind. **Every remaining clause of ADR-0228 binds entire and is
relied on**: §5's every-plan-is-persisted rule, its oldest-first order, its one-persistence-site
rule and its turn-that-ends-early-persists-nothing rule all stand, and §14's plan-driving deferral
is **fired** rather than superseded (above).

**ADR-0252, ADR-0253 and ADR-0254's remainder — relied on and not superseded.**
ADR-0252 §6's four tests are evaluated by §1 and §5 and not restated; ADR-0253's §§1, 2, 4, 5, 6,
8 and 9 are each taken as the contract this lane was handed, and **the three questions ADR-0253
hands here by name are answered** — the moment a never-eligible step is skipped (§2), the
mechanism by which the work returns to an earlier phase (§10), and the driver's performance of the
plan's interpretations (§1). ADR-0254 §13's recheck and §17's Q4 rule are relied on entire, §14 is
superseded in the one scope above and relied on in every other, and §13's reservation of *"What
happens to a call already claimed when a revocation lands"* to A9 is untouched.

### 17. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**A reader acts differently, so this is a decision and not a clarification.** A reader holding the
corpus without it builds a system that drives one step of every plan — which ADR-0228 §14 says in
terms is *"the system as ratified"* — leaves `depends_on`, `when`, `resolves`, `verifies` and
`interpretations` inert, has no producer for `UNMET_DEPENDENCY` or `EFFECT_UNRESOLVED`, accepts a
`→ RUNNING` claim under an attempt that has ended, and has no rule for what becomes of the steps
after a park, an uncertain effect or an expired budget. That is ADR-0070 §1's test met, and a new
ADR is the instrument.

**It is a partial supersession of exactly three documents** (ADR-0070 §3) — **ADR-0254** in
§14's two-case enumeration, **ADR-0251** in §4's trigger group and §1's occupancy clause, and
**ADR-0228** in three scopes of §5 — its two per-turn clauses, in their subject; its
superseded-plan-drives-nothing rule, in the moment it binds at; and its no-new-failure-mode
clause — and each record it writes names its scope without an
`ADR-NNNN` token inside the parentheses, so ADR-0070 §4's extraction invariant holds. Every other
ADR it touches is
**relied on**, and what it takes it takes by **firing deferrals** rather than by replacing
clauses: ADR-0228 §14's, ADR-0249 §13's two, ADR-0042 §3's named follow-on, and the three
questions ADR-0253 hands here by name in §2, §9 and §11. §16 shows the working for each rather
than leaving a reader to check.

**The records it owes land in the same change as this document** (ADR-0082 §7): **ADR-0254's,
ADR-0251's and ADR-0228's `Status` records** — each carrying its scope, and the first two dropping
`Accepted` so a prefix match cannot misread the replaced part as live while ADR-0228's is appended
beside the pairs it already carries, under ADR-0070 §4's accumulation rule (ADR-0070 §3,
ADR-0001) — are written with it and not after it, and so is **the appended dated note each of the
three carries**, which ADR-0082 §1 makes *"the invariant half of the record"*. That is the atomic
pair ADR-0082 §7 permits while this decision stands `Proposed`, and it is why this PR touches
**four** files where its predecessors touched one.

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

**The store derives the attempt itself, by searching `attempts_of(goal_id)` for the row whose
`execution_ids` names this execution.** Rejected — and note that the **field** is the one §3's
conjunct checks against, so what is rejected is the store **choosing** the attempt rather than the
field's authority. A derivation is its own answer: it cannot be wrong about itself, so the
conjunct would have nothing to refuse and a caller claiming under the wrong attempt would be
silently corrected rather than stopped. It also makes the store select where it otherwise follows,
on the hot path of every claim, and puts a fact only the driver holds — which attempt is driving —
inside the component that is meant to adjudicate it. Where `orchestration`
itself has no attempt to supply — ADR-0052's recovered resume, the one such path — it does take
that lookup, and §5 states why its result being **checked** by the store's conjunct is what makes
the same query safe there and unsafe inside the claim.

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
