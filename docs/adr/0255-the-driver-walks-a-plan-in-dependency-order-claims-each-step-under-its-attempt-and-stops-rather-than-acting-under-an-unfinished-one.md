# 255. The driver walks a plan in dependency order, claims each step under its attempt, and stops rather than acting under an unfinished one

- Status: Partially superseded by ADR-0265 (one scope, and it is a count. §15 item 19's enumeration of what §13's rule requires before a consequential capability is wired — "five conditions and not three, the fourth assigned to none of those three lanes and the fifth assigned to A8 but outside the reconciliation guarantee the gate names" — becomes six. The sixth is a containment for a wrongly minted intended action: a deterministic or user-authorised ruling that a proposed act is a second act the user asked for and not the act this goal already performed. It is assigned to none of the three lanes the gate names and is reached by none of their guarantees, because the duplicate it admits is a correctly claimed, correctly authorised and correctly verified dispatch of an effect the goal already holds — nothing downstream of the mint can see that it was one act and not two, so a reader holding only item 19 wires an integration after five and is wrong. That one count, and nothing else in this ADR: §13's rule itself binds verbatim and is relied on, its statement that that decision adds two prerequisites stays true of that decision, and the two it adds are untouched; §7's obligation that an effect is performed at most once across every plan of a goal binds entire and is what the new identity serves; §7's refusal of an identity derived from capability and parameters is honoured rather than lifted; §12's booking of whether an attempt's executions are projected into the planner's input is untouched and no projection is taken; and §§1-6, §§8-12, §14 and §§16-17 stand entire) and ADR-0259 (the identity §7's and §12's at-most-once obligation is stated over, and nothing else. §7 rules that an effect is "performed at most once across every plan of that goal" and §12 states the acceptance requirement over "a plan whose step would perform the same effect"; the superseding decision lands an identity in two parts — the intended action a step is an attempt at, which the effect row is scoped to, and the authorised call within it, identified by the bound tool's id, the digest of the supplied arguments and the binding's account, transport endpoint and canonical destination set. The guarantee is therefore narrower than "the same effect" in one direction, because two calls meaning one thing while spelling it differently carry two keys and the second is dispatched, and deliberately narrower in another, because two intended actions carrying one key are two acts and both happen. A reader holding only §7 reads its obligation more widely than it now holds. Every other clause of §7 and §12 binds entire: §7's keeps-everything-it-recorded rule, its extension of the not-driven rule to a plan superseded after driving, its sweep and that sweep's stated residual, its one-plan-per-walk rule, its stale-`targets_revision` refusal and its no-licence-to-repeat prohibition; §12's every other entry, both acceptance requirements' other halves — the modifying-and-fresh demonstration, the paired `INDETERMINATE` case, and the resolved-but-unapplied answer entire — and its firing conditions. §§1-6 and §§8-17 are untouched, and the deferrals §12 books are fired rather than replaced)
- **Partially supersedes [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md),
  in two narrowly stated scopes**, and §16 shows the working for both.
  **§14's where-phase-4-leaves-an-attempt enumeration**, in its two-case shape alone: *"**Every
  check passed** — the attempt's `phase` advances to `AttemptPhase.EXECUTE`"* and *"**A
  deterministic check failed on the plan** — the attempt stays `RUNNING` and the plan is replanned
  within the attempt"* gain a **third** case. A check **of a step** at least one of whose operands
  **this same plan** will produce before that step is dispatched, and has not produced yet, and
  **every one of whose operands already available at phase 4 is satisfied**, is **deferred**,
  not failed — **a known failure dominating a deferral**, so a check with an operand available now
  and failing now stays a **failed** check whatever else it waits on — and the plan has exactly
  two such producers: **a step earlier in `steps` that has
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
  **And §17's carried-and-discharged sentence**, in the **discharge** half alone: *"it is carried
  by A5, A6 and A7 and **discharged by A8, A9 and A10**"* gains **two further** conditions, because
  §13 forbids wiring a consequential capability until the **evidence-to-claim window** §1 states
  is closed — a window assigned to none of those three lanes — and until §3's
  **resolved-but-unapplied answer** is durably recoverable — a confirmation resolved at ADR-0037
  §4's step 5 whose claim §3 then refused at step 6 — which §12 assigns to **A8** but which is
  **no part of the reconciliation guarantee the gate names**, so A8's landing does not by itself
  discharge it either. So a reader holding
  only §17 would read A8's, A9's and A10's guarantees landing as releasing a deployment §13 still
  refuses, on either condition.
  **§17's rule itself is untouched and is quoted verbatim** — the verification, uncertain-outcome
  and cancellation guarantees, the milestone clause and the *"wiring one is what this rule binds"*
  sentence — as is the **carry** half naming A5, A6 and A7, and §17's second normative clause that
  that decision's own lane wires nothing.
- **Partially supersedes [ADR-0251](0251-an-attempt-investigates-in-bounded-rounds-over-typed-read-outcomes-and-keeps-a-reserve-to-answer-with.md),
  in two narrowly stated scopes**, and §16 shows the working for both.
  **§4's trigger group** — the read conditions **(b)**, **(c)** and **(d)** together with **(j)**,
  *"The attempt's `phase` is `AttemptPhase.INVESTIGATE`"* — is satisfied, in place of a serviced
  read, by a **re-investigation licence**: a typed outcome of a plan-driving walk that ran to the
  end of the plan, skipped at least one step because the world did not meet what the plan
  declared, and **dispatched no sibling branch the plan had declared for the other reading of that
  same basis** — so a conditional plan that declared both readings and took one carries no licence
  at all (ADR-0253 §9). **And §1's occupancy clause**, in one term: *"Every round of one attempt's
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
- **Partially superseded: 2026-09-13 by ADR-0265 — §15 item 19's condition count alone.
  Nothing else in this ADR.** The owner's correction of 2026-09-13 on #2255 requires a stable
  identity for an intended action; ADR-0265 mints it and obliges an at-most-once effect claim to
  scope itself to that identity rather than to the goal and the call's arguments.

  **Why the count moves.** Scoping the claim to the intended action is what lets *"book two
  identical rooms"* dispatch twice — the owner's *"an earlier booking must not count as fulfilling
  'book another one'"* — and the price is that an action a planner mints **wrongly** makes an
  otherwise duplicate claim fresh. §13's three named guarantees do not reach that path and neither
  do the two prerequisites this ADR adds to it: verification, uncertain-outcome handling,
  cancellation, the evidence-to-claim window and the resolved-but-unapplied answer could each land
  and leave it exactly where it stands, because the duplicate is a **correctly claimed, correctly
  authorised, correctly verified** dispatch of an effect the goal already holds. So ADR-0265 adds
  a sixth condition — a deterministic or user-authorised ruling that a proposed act is a second
  act the user asked for — and a reader holding only item 19 would wire an integration after five
  and be wrong. That is ADR-0070 §1's test on the supersession side and **partial** in §3's sense.

  **What does not move.** §13's rule is quoted and relied on unchanged, and its own sentence —
  *"this decision adds **two** prerequisites to that gate, and the count is stated so a reader
  does not take the first for the whole"* — stays true of **this** decision; it is the **gate's
  total** that item 19 enumerates and that grows. §7 is **relied on and superseded in nothing**:
  its obligation that an effect is performed at most once across every plan of one goal is what
  ADR-0265 exists to make reachable, and its refusal of an identity *"derived"* from capability
  and parameters — *"A driver that compared capability and parameters would be inventing an
  identity nobody declared"* — is **honoured**, because the identity ADR-0265 mints is declared
  and never derived. §12's booking of an executions projection into the planner's input is
  untouched. Appended dated note per ADR-0070 §1. Refs #2255.
- **Partially superseded: 2026-09-13 by ADR-0259 — the identity §7's and §12's at-most-once
  obligation is stated over. Nothing else in this ADR.** §7 rules that an effect is *"performed
  **at most once across every plan of that goal**"* and §12 states the acceptance requirement over
  *"a plan whose step would perform **the same effect**"*, and neither names the identity that
  makes two steps one effect — §7 says in terms that *"this decision lands no mechanism"*.
  ADR-0259 §§1-2 land one, in two parts. The **intended action** a step is an attempt at — minted
  once and retained across a revision — is what the effect row is scoped to; the **authorised
  call** within it, identified by the bound tool's id, the digest of the **supplied** arguments
  and the binding's account, transport endpoint and canonical destination set, is what the row
  compares. The guarantee is therefore narrower than *"the same effect"* in **two** directions,
  and both are deliberate. It does not recognise two calls that mean the same thing while spelling
  it differently — `alice@Example.com` in one plan and `alice@example.com` in the next carry two
  keys. And it does not refuse a repeat the user asked for: two intended actions carrying one key
  are two acts, two rows and two dispatches, which is what *"book two identical rooms"* requires
  and what an identity over the call alone would have refused. **A reader
  holding only §7 reads its obligation more widely than it now holds**, which is why the record is
  written rather than the difference being left to be discovered.

  **Every other clause of §7 and §12 binds entire and is relied on**: §7's
  keeps-everything-it-recorded rule, its extension of ADR-0228 §5's not-driven rule to a plan
  superseded after driving, its sweep from both source statuses and that sweep's stated residual,
  its one-plan-per-walk rule, its stale-`targets_revision` refusal and its no-licence-to-repeat
  prohibition; and §12's every other entry, both acceptance requirements' other halves — the
  modifying-and-fresh demonstration, the paired `INDETERMINATE` case, and the resolved-but-unapplied
  answer entire — and its firing conditions. **§§1-6 and §§8-17 are untouched**, and the deferrals
  §12 books to A8 are **fired rather than replaced**, which earns no record under ADR-0082 §1.

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
> claim order is untouched, and **`StepExecutor` gains no collaborator** (ADR-0058). **The one
> change either takes to *what it is handed* is §3's threaded `attempt_id`; the one change
> `StepRunner` takes to *what it builds* is the reference resolution stated below**, and the
> enumeration is closed at those two. Neither touches what the sentence above preserves: the
> disposal contract, the `PENDING`-only entry and the order of the ruling each bind entire under
> both.

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

> **Normative — what an interpretation call that does not return a verdict leaves, stated rather
> than inherited.** Where an interpretation call **raises** — a provider failure, a transport
> failure, a timeout of its own — or **returns anything that is not one of
> `InterpretationVerdict`'s three members**, ADR-0253 §8's declared output schema being *"exactly
> one member of `InterpretationVerdict`"*, **no `GoalEvidence` row is written for it**, no step
> conditioned on what it settles is dispatched or skipped, and **the turn fails** exactly as a
> turn whose model call raised already fails today. **Everything already committed stands**: the
> steps this walk dispatched keep their transitions and their outputs, nothing is undone, nothing
> is re-dispatched and no step is moved to `SKIPPED` — the same residual §6 and §7 state for their
> own partial writes, one seam over.

> **Normative — the working interval the walk consumed is charged *before* the failure
> propagates.** §9 states the charging rule of **every** working interval rather than of
> successful ones, so the elapsed interval up to the instant of the failure **accumulates into
> `AttemptEffort.working` through `commit_attempt`** before the exception leaves the driver — on
> §6's own footing, the attempt being in hand with its version known. **Without it a provider call
> that spent thirty seconds and raised would cost the attempt nothing**, and the next turn would
> be handed an allowance it has already spent, which is the one thing ADR-0251 §13's monotone
> ledger exists to prevent. **Where that commit does not land either** — a stale
> `expected_version`, a store failure — the residual is a ledger that **undercounts**, the turn
> fails as it would have anyway, **no lane retries it from a later turn**, and A8 owns the repair:
> §6's residual one field over, and stated rather than inherited.

> **Normative — which failure surfaces when both do, and the driver writes on neither exception.**
> Where the interpretation raised **and** the `commit_attempt` that charges the interval then
> raises too, **the interpretation's exception is the one that propagates, and the driver does not
> touch it at all**: it is not wrapped, not re-raised, not given a cause, and **no attribute of it
> is set — `BaseException.add_note` included**. Its `__cause__`, `__context__` and `__notes__`
> stay exactly as they stood, so a transport failure underneath a provider error is still the
> cause a reader sees. **The ledger failure is recorded where the driver owns the state**: a
> structured log warning, carrying the **ledger** failure's class and **nothing at all** taken
> from the interpretation's exception. **The turn failed on the interpretation**, and an
> implementation whose accounting cleanup masked that
> cause would report a store problem for a provider outage and send the next reader to the wrong
> subsystem. **No lane swallows either, and no lane rewrites either.**

> **Normative — what that warning may carry, and it carries nothing the provider controls.** The
> warning carries **exactly two things**. The **ledger** failure's class, which is **this
> project's** (`PlanningError`, `core/errors.py`), named as it stands. And a **fixed literal**
> naming what else failed — that an interpretation call did not return a verdict — which is this
> decision's own text and not a value read off any object at run time. **Nothing whatever is taken
> from the interpretation's exception**: not its class, not a class derived or mapped from it, not
> its message, and none of ADR-0029 §3's channels — no `str()`, `repr()`, `args`, `__notes__`,
> `__cause__` or `__context__` — and the same holds of the ledger exception's message (ADR-0004
> §5, and ADR-0029 §3's channel enumeration as ADR-0032 §5 and ADR-0145 §7 restate it). §10's rule
> that the driver renders no plan, no step, no execution, no `SkipReason` and no verdict to a log
> binds entire.

**Why the interpretation's class is dropped rather than made safe, which an earlier revision of
this section required.** *"A route may be any `ModelProvider`, so `type(exc).__name__` is
provider-controlled text"* (ADR-0013 §5), so the provider's class cannot be named as it stands.
The instrument that section uses to make it safe — `_classify` against a set frozen at import,
*"the nearest ancestor in the exception's MRO that is one of our `ModelError` subclasses, matched
by **object identity**"* — is **private to `models.routing` and unreachable from
`orchestration`**: golden rule 1 and the `lint-imports` contract *subsystems are independent of
each other* both forbid that import, and a copy would stand up a second authority for a classifier
whose whole value is being the only one. A project-owned classification surface in `core` is not
the answer either: §11 adds *"no new model, no new enumeration, no new constant"*, and moving a
`models` concern into `core` to serve one log line would widen this decision past its own
boundary (§4). **So the driver carries no provider-derived text at all**, which closes ADR-0013
§5's hazard **by construction** rather than by a rule an implementation has to keep. The cost is
stated rather than hidden: this warning is **strictly less informative** than a mapped class would
be. The operator learns *an interpretation call failed and the ledger write failed too*; **the
provider's own diagnosis is not this system's to repeat here**, and it is not lost — it reaches
the caller on the propagating exception, which the driver leaves untouched.

> **Normative — the warning is best-effort, and a logging failure never becomes the turn's
> failure.** The warning is emitted **inside a guard**. Where emitting it raises — an installed
> processor, a handler, a sink — **that exception is caught and discarded, and the interpretation's
> exception still propagates as the same instance, unchanged**: not replaced, not masked, and the
> logging failure is not set as its cause, its context or a note on it, the clause above binding
> here too. A diagnostic never becomes the failure it is a diagnostic of. The residual is one line
> of operator detail lost, against a turn whose caller would otherwise be told its provider call
> failed for a reason belonging to a log sink.

**Every instrument that writes on the caught exception is refused, and ADR-0013 §5 is where this
project already worked that out.** That section records `add_note` on a caught provider exception
as one of two wrong turns found by adversarial review — *"mutates an exception the router does not
own. A provider that raises a cached instance accumulates one note per call, unbounded, and
concurrent routers sharing that object leak each other's route labels into it"* — and states the
through-line this decision adopts word for word: the caught exception *"belongs to the provider
that raised it, and may be shared, cached, or concurrently in flight elsewhere."* **The driver is
in exactly the router's position.** `raise … from` is refused for its own two reasons besides:
`raise interpretation from ledger` **overwrites** the interpretation's own `__cause__`, destroying
the transport failure underneath it, and `raise ledger from interpretation` propagates the wrong
exception so that every caller's `except` clause sees a store error for a provider outage. The
corpus uses `raise … from` where one failure genuinely **caused** another — ADR-0029 §4's digest
case — and these two did not cause each other: they are **two independent failures of one turn**,
so the representation must not invent a causal edge. An `ExceptionGroup` would say that correctly
and would change what every caller catches, which is a contract change this decision has no reason
to make. **So the diagnostics go where the driver owns the state**, which is ADR-0013 §5's own
resolution: *"the diagnostics go where the router does own the state — a structured log
warning."*

> **Normative — a failed interpretation is never defaulted, and this is not a sixth stop trigger.**
> **No lane substitutes `INCONCLUSIVE`, `DOES_NOT_QUALIFY` or any other member for a call that did
> not return one**, writes a row with a fabricated verdict, retries the call, or proceeds as if the
> element were unsettled: ADR-0249 §7's asymmetry forbids a model's silence clearing a dependency
> as firmly as it forbids its speech doing so, and a defaulted verdict would be a model output with
> no model behind it. **And §2's stop enumeration stays closed at five**: a *stop* leaves a turn
> that composes an answer over what ran, and a raised call leaves a turn that fails — two different
> outcomes, and no lane reads either as the other.

> **Normative — the driver performs no read, makes no `Planner.plan` call and opens no
> investigation round.** ADR-0251 §1's rounds are phase 2 and the walk is phase 5. **The only
> model call the walk makes is an interpretation**, whose whole input and whose output schema are
> ADR-0253 §8's, and which *"is **not** a `Planner.plan` call"*.

**That is what makes a condition's verdict stable against *this turn's* writing for the rest of
the pass, and it is the argument §2's skip rule rests on — stated at exactly the strength it
holds.** ADR-0252 §6 evaluates recency and every
other test *"at the moment of dispatch"*, so a step evaluated early and dispatched late could be
evaluated against rows that moved. **Against this turn's own writing they cannot**: the only row
this turn writes during the walk is an interpretation the plan declared, ADR-0253 §8's ordering
rule puts every such interpretation before every step conditioned on what it settles, and no other
stage of this turn reads the world. **Between walks they can**, which is why the evaluation is
per dispatch and not per plan.

> **Normative — a *concurrent turn's* evidence write is outside that argument, and the window it
> leaves is stated rather than claimed away.** Two turns of one conversation are **not**
> serialized (§3, and ADR-0014's and ADR-0029's notes of 2026-08-25), and ADR-0252 §8's **refresh**
> supersedes a `STANDING` row **without moving the goal's `revision`** — ADR-0252 §9 makes an
> *invalidation* atomic with the revision that occasions it, and a refresh is a different write.
> **So a row that satisfied a step's `when` when §1's evaluation read it can be `SUPERSEDED` by
> another turn before that step's claim commits**, and none of §3's three claim conditions refuses
> the claim: the revision has not moved, the attempt has not changed, and no successor was
> persisted. **The window is the interval between §1's evaluation and the committed claim**, and
> **no lane reads §1's stability argument, §2's fixed-inputs argument or §3's conjuncts as
> excluding it.**

> **Normative — what this decision does about that window, and what it declines.** It **states**
> it, it adds **no mechanism**, and **§13's Q4 rule is what makes the interval safe rather than a
> hazard**: no consequential capability is wired into a production deployment until A8's, A9's and
> A10's guarantees are implemented and demonstrated, so the acts the window governs cannot be
> performed while it stands — the construction §7 uses for cross-plan at-most-once, applied to one
> more obligation. **And §13 states the window's closure as a prerequisite of that gate in its own
> right**, because the gate's three guarantees are A8's, A9's and A10's and **none of them is this
> window**: without the added prerequisite all three could land and leave it open, and the
> interval argument would expire exactly when a consequential capability was wired. **The two
> mechanisms that would close it are named in §12 and neither is taken
> here**: a value the claim carries, which §3's argument against a caller-supplied revision
> applies to in full; or ADR-0252 §6's four tests evaluated inside `commit_transition`, which puts
> a clock and a plan's conditions inside the store. **Choosing between them is not this decision's
> to do**, and no lane reads this silence as a ruling that the window does not exist.

> **Normative — the driver re-evaluates, and phase 4 is not thereby moved or duplicated.**
> ADR-0254 §14's phase-4 evaluation runs once over the plan before the walk begins and is that
> decision's lane's. The driver's per-step evaluation is **the same predicates re-evaluated
> against the state as it then stands**, which is what ADR-0254 §13 requires of coverage —
> *"There is **no cached coverage verdict anywhere**"* — applied to the other three for the same
> reason. **No lane caches a dependency verdict, a condition verdict or a resolved value across
> two dispatches**, and no lane satisfies a dispatch from a verdict phase 4 took.

> **Normative — a check whose operands a later step will produce is *deferred*, and a deferred
> check is not a failed one. This partially supersedes ADR-0254 §14** in the one scope §16
> states. A phase-4 check **of a step** is **deferred** where **at least one** operand it reads
> is a value **this same plan will produce before that step is dispatched** and has not produced
> yet, **and every operand that check reads which is already available at phase 4 is satisfied**.
> **A known failure dominates a deferral**: a check with an operand that is available now and
> **fails** now is a **failed** deterministic check whatever else it waits on, and ADR-0254 §14's
> replan limb binds it unchanged. **The unit is the operand and never the check**, so a step's
> `when` carrying one condition no row satisfies and one awaiting an interpretation of this plan
> **fails** rather than defers. There
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

> **Normative — what an *operand* is, per check, so that neither *available* nor *dominates* is
> read loosely.** The dominance rule above turns on which operands a check reads, and this
> decision states them rather than leaving an implementation to choose: for **check 1** they are
> the stored `StepExecution` status and `output` of each `depends_on` member; for **check 2** the
> step's literal arguments and, for each `ResultReference`, its producing step; for **check 3**
> **one operand per member of `when`** — the goal's rows for the element that member names; and
> for **check 4** the operand is the step's **complete concrete `ActionRequest`**, which is **one
> operand and not several**.

> **Normative — coverage is therefore deferred *entire* while any argument of the step is filled
> by an unresolved reference, and the dominance rule has nothing to bite on there.** ADR-0148 §1
> makes the request the thing a ruling is taken on — *"Nothing in it is resolved, canonicalised,
> defaulted, expanded or added after `ActionPolicy.decide` has been reached"* — and ADR-0254 §3's
> comparison is over **that** request. So where a step carries a `resolves` naming a step of this
> plan that has not produced, **there is no concrete request to compare and no available operand
> to fail**: the coverage check defers, and **no lane routes such a step to §14's `CONFIRM` limb
> at phase 4**. A step whose every argument is a **literal** has its concrete request at phase 4,
> so an uncovered argument there is available and refuses, and §14's `CONFIRM` limb takes it
> exactly as it does today.

**Stating the operands is what stops *known failure dominates* becoming *ask the user early*.**
The dominance rule exists so a refusal nothing can change is not hidden behind a value the plan
will supply; it is not a licence to decide a check whose subject does not exist yet. Coverage's
subject is a whole request, and a request missing a resolved value is not a request that fails
coverage — it is a request ADR-0148 §1 forbids ruling on at all. **Parking it would ask the user
to authorise arguments the plan has not filled**, and the answer would bind a request different
from the one that is finally built — which is exactly the substitution ADR-0037 §2 and ADR-0021 §1
close by embedding the definition and digesting the parameters.

**Deferring only what the plan's own production could change is what keeps ADR-0254 §14's failure
limb alive rather than swallowing it.** A check defers because its answer is **not yet
determined** — the producer has not run, the interpretation has not been performed — and that
reason reaches exactly the operands this plan will produce. It does not reach an operand that is
available now and refuses now: nothing this plan produces revises it, so the answer at that step's
dispatch is the answer phase 4 already has, and a plan that carries it is a plan ADR-0254 §14
replans rather than drives. **Deferring the whole check on one unavailable operand would hide a
settled failure behind an unsettled one** — the plan would advance to `EXECUTE`, its earlier steps
would act, and the step whose refusal was known before any of it happened would be skipped at the
end. That is the one outcome §14's failed limb exists to prevent, and it costs a side effect to
reach.

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

> **Normative — the stop rule, stated as a closed list and not as a predicate over *terminal*.**
> **The walk stops on the first of the five outcomes below**, and every step after it in `steps`
> order is left **`PENDING`**. **The list is the whole of the rule**, the driver treats its members
> alike, and no lane derives a sixth from a property of a status:
>
> - the step's dependency **fails on an `INDETERMINATE` producer** (ADR-0253 §2, §6);
> - `StepRunner` returns **`AWAITING_CONFIRMATION`** and the step is durably `AWAITING_APPROVAL`;
> - `StepRunner` returns a disposition that **commits nothing** — `AMBIGUOUS_CAPABILITY`,
>   `INVALID_PARAMETERS` or `EGRESS_UNBINDABLE` — and the step stays `PENDING` at its stored
>   version;
> - the step's own outcome is **`INDETERMINATE`** (§6);
> - the **request deadline** has no strictly positive remainder (§9).

> **Normative — a `FAILED` step does not stop the walk, and the closed list above is how that is
> said.** An earlier revision stated the rule as a predicate — *the disposal leaves the step
> neither terminal nor skipped* — which is **false against the only definition of *terminal* this
> tree carries**: `TERMINAL_STEP_STATUSES` is `frozenset({SUCCEEDED, SKIPPED})` (`core/types.py`),
> whose own comment says *"`FAILED` is not among them (it may still be retried)"*. On that
> definition the predicate stopped the walk at every failed step, contradicting §5's pass-over and
> the skip rule below. **It is deleted rather than repaired**, and the list is the rule.

**Disposed-of and terminal are two different predicates, and this decision uses the first.**
`TERMINAL_STEP_STATUSES` answers *may this execution still be worked on* — which is why `FAILED`
sits outside it, why `PlanExecution.has_open_work` is true of one, and why a restarting system
finds it through `active_executions`. **The walk asks a narrower question**: *did this step's
disposal settle what the walk needs to know to go on*. A `FAILED` step's did — `StepExecutor`
spent its retries inside the `run` that returned (`DEFAULT_MAX_ATTEMPTS`) and committed a
transition — so the walk **passes over it** (§5) and its dependents are `SKIPPED`/`UNMET_DEPENDENCY`
under the skip rule below, which is arm 3's first case. **A walk that re-dispatched one would be
retrying past a budget the tree already enforces**, and one that stopped on one would leave every
dependent `PENDING` with no producer that will ever run.

> **Normative — this list is what a disposal *this walk performed* leaves; §5's list is what a
> walk *finds already stored*. Both are closed, and they answer different questions.** A stored
> **`RUNNING`** step stops a walk (§5) and appears as no trigger here, because **no disposal this
> decision makes leaves one** — the committing-nothing limb above leaves `PENDING`, and a `RUNNING`
> a walk meets was left by something else (ADR-0014 §4's recovery case, §5). **No lane reads §5's
> list as a sixth trigger of this one, and no lane reads this one as licence to walk past a stored
> `RUNNING`.**

> **Normative.** **A step the walk did not reach is `PENDING` when the walk ends**, and **the
> walk itself never skips it**. No lane sweeps the remainder of a stopped walk into `SKIPPED`,
> writes a `SkipReason` for a step nothing evaluated, or reads `PENDING` after a stopped walk as
> a terminal state. **Two later events dispose of such a step, and neither is the walk that left
> it `PENDING`**: **a fresh walk of the same plan**, which is reached by the one route the block
> below names — `StepRunner.resume` answering a park of that plan, after which the driver walks
> that plan again from its first position (§5) and disposes of the step as any other `PENDING`
> one; and **§7's supersession**, on a different ground, at a different moment, and forbidden by
> §6 behind an `INDETERMINATE` step. **The list is closed at those two**: no sweep, no timer and
> no background continuation disposes of one, which is the block below stated from the step's side
> rather than the walk's.

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
ADR-0252 §6's tests read the goal's rows, and §1 above establishes that the only rows **this turn**
writes during a walk are the interpretations the plan declared, every one of which ADR-0253 §8
orders before the steps conditioned on it — **a concurrent turn's refresh being the window §1
states and this argument does not cover**. ADR-0253 §6's resolution reads the producing execution's
`output`, which is written once when that step succeeds and is never rewritten. **So deferring
the skip to the end of the walk would record the same fact later, and deferring it to the end of
the attempt would leave a step `PENDING` that nothing will ever dispatch** — indistinguishable, in
the durable record, from a step the walk stopped short of, which is precisely the distinction the
stop rule above exists to keep.

**The two rules together are what makes "why did this step not run" answerable from the store
alone.** A `SKIPPED`/`UNMET_DEPENDENCY` step says *this plan's own conditions refused it*; a
`PENDING` step says *the walk did not get there*; and which it is, is decided by whether anything
was settled about the step rather than by where in the plan it sat.

### 3. The claim's two further conjuncts: the attempt, the successor, not a supplied revision

> **Normative.** `core/types.py`'s **`StepTransition` gains exactly one field**:
> **`attempt_id`, an `Identifier | None`, defaulting to `None`**, naming the `GoalAttempt` the
> claim is being made under. A **model validator** requires it on a transition whose `to_status`
> is **`RUNNING`** and **forbids** it on every other `to_status`, which is ADR-0039 §2's own
> shape — *"required when the status is `FAILED` or `INDETERMINATE`, and forbidden on every other
> status"* — applied to one more field.

> **Normative.** **`PlanStore.commit_transition` gains two claim conditions, and this is the
> first**: a `→ RUNNING`
> transition is accepted only where the `GoalAttempt` its `attempt_id` names **exists**, carries
> the transition's own **`execution_id` among its `execution_ids`**, is in an `AttemptState`
> that is **neither terminal nor paused**, and is the **only** attempt of that goal naming that
> execution. **This conjunct refuses
> on exactly four limbs, and the case a reader would expect as a fifth is removed at construction
> rather than refused here**: a `→ RUNNING` transition carrying **no** `attempt_id` is **not
> constructible** under the validator above, so `commit_transition` never receives one and this
> decision requires no store to refuse it. Naming the absent case as a store limb as well would
> be a rule no conforming implementation could be shown to obey, and would put the boundary in
> two places — which is the `to_status` shape the store already declines to re-check.

> **Normative — the state limb disqualifies five of `AttemptState`'s seven members, because
> *paused* is as disqualifying as *ended*.** It refuses a claim under an attempt whose `state` is
> `CANCELLED` or `ENDED` — ADR-0249 §5's two terminal members — **and** under one whose `state` is
> `AWAITING_CLARIFICATION`, `AWAITING_AUTHORIZATION` or `BLOCKED`, which are the three members
> ADR-0249 §5 derives *paused* from: *"A goal is **paused** when its status is `ACTIVE` and its
> current attempt's state is `AWAITING_CLARIFICATION`, `AWAITING_AUTHORIZATION` or `BLOCKED`"*.
> **The seventh member, `EFFECT_UNRESOLVED`, is accepted** (§6). **The limb is not a `RUNNING`
> whitelist and no lane implements it as one**, because §6 lands a producer for the seventh member
> and a claim under it is exactly what that clause admits.

**Naming the three rather than requiring `RUNNING` is what keeps §6's own member reachable, and
refusing them is what keeps *paused* true of a paused system.** §2's park argument states the
hazard in terms — *"A paused attempt that went on dispatching would make *paused* false of a
system that is acting, in the one surface a user reads to find out whether anything is
happening"* — and a store that accepted every non-terminal state would let a step reach the tool
under an attempt the system is reporting as paused. **The driver's own stop rule does not close
it, because the walk is not the only writer of the attempt's state.** Two turns of one
conversation are **not** serialized: ADR-0014's note of 2026-08-25 and ADR-0029's amendment of the
same date both state it — *"`Engine.converse` takes no lock … `Engine._admit_and_reserve` is
written for the **Nth concurrent turn** … so two turns can each be driving a step"* — so a
clarification or an authorization park recorded by one turn can land while another turn's walk
sits between two steps, and only a check inside the claim sees it.

> **Normative — the paused limb strands no answered park, and the ordering that makes that true
> is already ruled rather than added here.** ADR-0254 §14 rules that an answer establishing an
> `Authorization` *"resumes the attempt it paused by the path that already exists: ADR-0249's lane
> commits the attempt out of `AWAITING_AUTHORIZATION` to `RUNNING` at `EXECUTE` the moment the
> resolving ruling reaches the trail, in one `commit_attempt` with the decision that answer was
> recorded under"*, and ADR-0037 §4's `resume` sequence records that ruling at its **step 5** and
> claims at its **step 6**. So the attempt a resumed claim names stands at `RUNNING` by the time
> that claim is made, and **this decision adds no writer, no second commit and no ordering of its
> own** (§5, ADR-0254 §14's own clause). **A resume that nevertheless finds the attempt paused is
> refused rather than excused**, which is the fail-closed direction and the same answer §5 already
> gives a resume whose predicates no longer hold.

> **Normative — the paused limb raises the same non-stale `PlanningError`, and it is the one limb
> whose ground is not permanent.** A paused attempt can become `RUNNING` again, so the argument
> below does not reach it through permanence — it reaches it through what a caller can do.
> **Nothing the caller can do makes this claim land**: what lifts the pause is a **user act**
> answering the question the attempt is paused on, and §3's own rule governs it in terms —
> *"Naming a different attempt or acting on a later turn is a different claim, not a retry of this
> one"*. A caller obeying `StaleExecutionError`'s re-read-and-retry contract would spin against a
> store waiting on a human, which is the failure the class rule exists to prevent.

> **Normative — every limb of this conjunct raises a `PlanningError` that is *not*
> `StaleExecutionError`, and the class is decided by what the class means rather than by which
> refusal it sits beside.** `StaleExecutionError` means *"the stored execution has advanced since
> the caller read it"* and directs a caller to **re-read and retry** (`core/errors.py`, ADR-0014
> §5). **No limb of this conjunct is that**: an unknown attempt stays unknown however many times
> the caller re-reads; an attempt that did not open this execution can **never** acquire it, since
> `execution_ids` is append-only and §3 makes ownership exclusive; a `CANCELLED` or `ENDED`
> attempt never becomes live again; a **paused** attempt becomes live only by a user act and never
> by a re-read (above); and a duplicated ownership is refused whichever attempt is
> supplied. **Naming a different attempt or acting on a later turn is a different claim, not a
> retry of this one** — so a caller obeying the stale class's contract would loop against a write
> that cannot land, on every limb and not only on the duplicate. This is a **strengthening of an
> existing member** rather than a new one, exactly as ADR-0249 §12 classifies the first added
> condition.

> **Normative — ADR-0249 §8's stale-revision refusal keeps `StaleExecutionError` and is not
> touched, and the two are different questions.** That refusal compares a value the store derives
> — execution → plan → goal — against one that **moves**, so a claim refused there was computed
> against a state that has genuinely advanced and re-reading is exactly what a caller should do.
> The attempt conjunct compares a claim's own named row against membership and a state that **do
> not move under it**. **ADR-0249 L1 is this decision's precedent for where the conjunct lives —
> inside `commit_transition`, in the same indivisible step — and not for which class it
> raises**, and no lane reads the two refusals as one class because they sit in one member.

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

> **Normative — the two attempt-writing members refuse on the same class, for the same reason.**
> `commit_attempt`'s and `open_attempt`'s ownership refusals raise the same non-stale
> `PlanningError` the conjunct above does: no re-read makes an execution owned by attempt A valid
> for attempt B, so **all six refusals this decision adds are permanent and none of them is an
> optimistic-concurrency loss**. The absent-attempt case is not among them at all, because §3's
> validator makes that transition unconstructible and the store never receives one. Each is
> a **strengthening of an existing member** on ADR-0249 §12's own footing, and it is
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

> **Normative — `commit_transition` gains a *second* claim condition, and it is §7's supersession
> made atomic with the claim.** A `→ RUNNING` transition is accepted only where **no plan the
> store holds names this transition's plan in its `supersedes`** — this transition's plan being
> the one its `execution_id` names, by the execution → plan chain the store already follows for
> the revision. **The store derives it and no caller supplies it**, exactly as ADR-0249 §8 derives
> the revision and for that clause's own reason, and it is decided **in the same indivisible step
> as the write**. It refuses on the same **non-stale `PlanningError`** every limb of the attempt
> conjunct raises, and its ground is permanent in the plainest way: **a persisted successor is
> never un-persisted**, so no re-read makes the claim land. **It is one condition and not a fifth
> limb of the conjunct above**, because it compares a different row — the plan's, not the
> attempt's — and the two are refused independently.

> **Normative — what it closes, and it is a race no serial rule closes.** §7 rules that **a plan
> superseded after driving drives nothing further** and ADR-0228 §5 that a plan superseded before
> driving *"**drives nothing** … reaches no `StepRunner`"*. **Neither is enforced by anything the
> tree holds.** Two turns of one conversation are **not** serialized — ADR-0014's note of
> 2026-08-25 and ADR-0029's amendment of the same date both state it, *"`Engine.converse` takes no
> lock … `Engine._admit_and_reserve` is written for the **Nth concurrent turn** … so two turns can
> each be driving a step"* — and **saving a successor moves neither the goal's `revision` nor the
> attempt's `state`**, so turn B's `save_plan` of P2 carrying `supersedes=P` leaves turn A's next
> claim on P satisfying the revision conjunct and the attempt conjunct alike. §7's sweep is
> several compare-and-swaps over the old plan's steps and **cannot be atomic with a claim another
> turn is making**; a driver-side check would be a read-then-claim, which is the
> time-of-check-to-time-of-use gap §3 refuses for the revision. **So the rule is put where the
> claim is decided**, which is ADR-0249 §8's answer for the revision and §3's for the attempt,
> reached a third time for the third value and for the same reason.

> **Normative — this adds no `core` field, no `PlanStore` member and no second authority.**
> `ActionPlan.supersedes` is the value the check reads and ADR-0228 §5 already put it there;
> **`PlanStore` gains no member**, no query is promoted to the wire, and the derivation is the
> store's own over rows it already holds — `save_plan` refuses a `supersedes` naming a plan under
> a different `goal_id`, so the only plans that can name this one are the plans of its own goal.
> **No lane exposes an is-superseded fact on `ActionPlan`, on `ExecutionState`, on the wire or in
> the export**, and none reads this conjunct as licence to sweep, to repair, or to infer
> `SUPERSEDED` at read time (§7).

> **Normative — it refuses the claim and changes nothing else about a superseded plan.** §7 binds
> entire: the superseded plan's executions, its `SUCCEEDED` steps' outputs and the attempt's
> `execution_ids` stay exactly as they stand, its still-`PENDING` steps are disposed of by §7's
> sweep and by nothing here, **§6's override still forbids that sweep behind an `INDETERMINATE`
> step**, and **a walk that had already run when the supersession was recorded is not undone** —
> what this conjunct refuses is the **next** claim, which is what *"drives nothing further"*
> says. A claim it refuses leaves its step **at the entry status the clause below fixes**, with
> nothing invoked and the walk stopped, exactly as every other refused claim does.

> **Normative — a refused claim leaves the step at its *entry* status, and there are exactly two
> entry statuses.** A `→ RUNNING` claim is made from **`PENDING`**, by a walk, and from
> **`AWAITING_APPROVAL`**, by `resume` (ADR-0037 §4). A refused claim leaves the step **at the one
> it was made from, at its stored version**, with **nothing invoked**, and the walk **stops** under
> §2's rule. **An earlier revision of this clause said `PENDING` for both and was wrong about the
> second**, which is the status a park leaves.

> **Normative — on the resume path the ruling is already recorded when the claim is refused, and
> the one-shot approval is spent. This decision does not reorder that, and states what it
> leaves.** ADR-0037 §4's `resume` sequence is ordered *"5. record the resolving decision with
> `resolves` set;"* then *"6. `ALLOW` → read back and execute (§3); `DENY` → `AWAITING_APPROVAL →
> SKIPPED`."* — and the claim §3 adds conjuncts to lives in **step 6**. So a claim this decision
> refuses is refused **after** step 5 has committed: the confirmation is **resolved**,
> `AuditTrail.pending_confirmation` no longer returns it, and the step stands
> **`AWAITING_APPROVAL` with a ruling that resolved nothing it could apply**. **Making steps 5 and
> 6 atomic is #257's remaining half and is not taken here** (§12), and **no lane reorders
> ADR-0037 §4**: that sequence binds verbatim, and a decision about walking a plan is not where a
> confirmation protocol is rewritten.

> **Normative — the two refusal grounds leave residuals of different weight, and only one of them
> is a loss.**
>
> - **The successor conjunct — a plan a stored plan supersedes.** The step **never runs again**
>   under any future state of the store: the supersession is permanent and §7's sweep disposes of
>   the plan. **The spent approval costs nothing**, because there is no dispatch it could ever
>   have authorised, and re-asking would be asking a user to approve a step of a plan that has
>   been replaced. This is the ordinary case, it is not a defect, and it is stated so that no lane
>   builds recovery for it.
> - **The attempt conjunct — an attempt terminal or paused.** **This is the real residual.** A
>   *paused* attempt becomes `RUNNING` again by a user act (§3), so the step **could** have run
>   later, and the approval that would have authorised it is **spent on a claim that never
>   landed**. The user answered, the system recorded the answer, and nothing it authorises will
>   happen. **Re-asking is not available to this decision**: a second `CONFIRM` is a second
>   recorded act, and §11 mints no mechanism for reissuing one.
>
> **The durable recovery of a resolved-but-unapplied answer is A8's and is booked by name** (§12,
> §13), on the same footing as §7's at-most-once obligation: stated here as an acceptance
> requirement of that lane rather than left for someone to meet.

> **Normative — what the refused claim then causes beyond that is not decided here.** **Which
> report the turn composes, whether it replans, and what a user is told** are recovery policy and
> are **A9's**, which is ADR-0249 §13's own division for a refused stale claim.

> **Normative — the four tests of revision 1 §H.4, and which of them is owed here.** **Test 3 —
> the store-level invariant in the shared `PlanStore` conformance suite — is this decision's**,
> and it is owed for **all three** conjuncts: no `→ RUNNING` transition is ever accepted whose
> goal revision is not the stored one; none whose attempt is **unknown**, **does not name this
> execution**, or is in a state that is **terminal or paused**; none naming an execution **more
> than one attempt names**; and **none whose plan a stored plan supersedes** — §3's four attempt
> limbs and its successor condition, each asserting the **non-stale `PlanningError`** §3 fixes.
> **The absent case is not among them**: §3's validator makes a `→ RUNNING` transition carrying
> no `attempt_id` unconstructible, so it is asserted unconstructible rather than refused (§3,
> arm 7). **Tests 1, 2 and 4 —
> interleaved cancel before the claim, interleaved cancel after it, and the exhaustive two-writer
> interleaving — are A9's**, because each is stated over a cancellation whose semantics that lane
> decides. **No lane reads this decision as having established them.**

### 4. The boundary: what is already ruled, and that this decision adds only the two conjuncts

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

> **Normative.** **What this decision adds to the boundary is §3's two claim conditions — the
> attempt conjunct and the successor conjunct — and nothing else.** No clause here changes what
> a claim is, when it is committed, what it carries
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

> **Normative — the resumed claim carries the same conjuncts** — it is a `→ RUNNING` transition
> and **both** of §3's claim conditions bind it — so a park answered after the goal moved on,
> under an attempt that has **ended or is paused**, or **on a plan a later plan supersedes**, is
> refused and nothing is invoked.

> **Normative — a whole fresh walk follows the resumed step.** Where `resume` returns `EXECUTED`,
> the driver **walks that plan again**; where it returns `DENIED`, the step is
> `SKIPPED`/`APPROVAL_DENIED` and the driver **walks that plan again**, which will then dispose of
> that step's dependents by §2's skip rule.

> **Normative — the driver holds no cursor, and a resumed walk starts where every walk starts.**
> **Every walk visits the plan's steps from the first position**, reading each step's stored
> `StepExecution.status` from `PlanStore.get_execution`, and disposes of it by that status:
> **`SUCCEEDED`, `FAILED` and `SKIPPED`** are already disposed of and are **passed over without
> re-dispatch** — **`FAILED` included, and it is named rather than left to a reader, because
> `TERMINAL_STEP_STATUSES` does not carry it** (§2): the retries are `StepExecutor`'s and were
> spent inside the `run` that returned it, so a walk that re-dispatched one would retry past a
> budget the tree already enforces. Their dependents are governed by ADR-0253 §2 when the walk
> reaches them;
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
> after driving whose walk stopped on an `INDETERMINATE` step leaves **that step durably
> `INDETERMINATE`** — the transition it committed is a record §7's first clause preserves, not a
> status the sweep may move — and leaves **its dependent branch and every step behind it
> `PENDING`**, moving none of the three to `SKIPPED`/`SUPERSEDED`.

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
> and before the turn composes. `EFFECT_UNRESOLVED` is **neither a terminal member nor one of the
> three ADR-0249 §5 derives *paused* from**, so a later claim of that attempt is **not** refused
> by §3's state limb on that ground alone — which is the member's whole point: an attempt holding
> an effect it cannot account for is neither finished nor waiting on anybody.

> **Normative — the two writes are not one, and what a failure between them leaves is stated.**
> The step's `→ INDETERMINATE` transition and the attempt's `commit_attempt` are **two writes
> under two compare-and-swaps**, and `PlanStore` offers no multi-write commit (#257's own
> observation, one store over). Where the attempt write does not land, **the step stays durably
> `INDETERMINATE`**, the turn fails as a turn whose store write raised already fails, and
> **nothing is re-dispatched and no step is skipped**. **What the attempt is left holding depends
> on which failure it was, and the two are not alike**:
>
> - **A store failure** — the write never reached a decision. The attempt stays **`RUNNING`**, as
>   it stood when the driver read it.
> - **A stale `expected_version`** — the compare-and-swap was *decided*, against the driver.
>   Another writer moved the attempt between the driver's read and this write, and **the attempt
>   holds whatever that writer committed** — which may be `CANCELLED`, `ENDED` or any of the three
>   §3 derives *paused* from. **No lane states that it stays `RUNNING` here and no lane restores
>   it**: the driver lost the race and **writes nothing**, so the concurrent writer's state stands
>   exactly as committed. Two turns of one conversation are not serialized (§3, ADR-0014's and
>   ADR-0029's notes of 2026-08-25), which is what makes this limb reachable at all.
>
> **The step's status is the authoritative record of the uncertainty** and the attempt's state is
> the derived convenience, so on the first limb the residual is a record that is *less* informative
> rather than one that is wrong; on the second it is a record that is *differently* informative,
> and the loser of a compare-and-swap overwriting the winner would be the worse outcome by far.

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
> further step of it, and its **undisposed** steps are moved to **`SKIPPED` with
> `skip_reason=SUPERSEDED`** — ADR-0014 §4's own row, taken for the case it was written for.
> **`AWAITING_APPROVAL` steps are swept as well as `PENDING` ones, and that is stated rather than
> left to the word *pending***: `planning/execution.py`'s `_LEGAL_SKIP_REASONS` admits
> `SUPERSEDED` from **both** statuses, so the store permits it, and a plan superseded while one of
> its steps is parked has exactly one such step. **§6's rule overrides this one** where a branch
> is stopped behind an `INDETERMINATE` step.

**Sweeping the parked step is what stops a superseded plan spending a user's approval, and the
seam probe found it by asking what each entry status leaves.** A sweep that moved only `PENDING`
steps would leave the park standing `AWAITING_APPROVAL` on a plan nothing will drive; the user's
answer would then arrive, `resume` would record the resolving decision at ADR-0037 §4's **step 5**,
and §3's successor conjunct would refuse the claim at **step 6** — spending a one-shot approval on
a step that could never have run. **With the parked step swept, `resume` refuses before step 5**:
the confirmation's step is `SKIPPED`, not `AWAITING_APPROVAL`, so the sequence never reaches the
recording. §3's superseded-plan residual is therefore the **partial-sweep** case alone — the sweep
that did not land this step — rather than the ordinary one, and it costs nothing there for the
reason §3 gives.

> **Normative — §3's successor conjunct is what makes *drives nothing further* mechanical rather
> than a rule the driver is trusted to obey.** `commit_transition` refuses a `→ RUNNING` claim
> whose plan a stored plan supersedes, in the same indivisible step as the write, so a claim
> racing a successor's persistence **from another turn** is refused rather than won — which the
> sweep below cannot do, being several compare-and-swaps in a turn that does not hold the claim.
> **This decision adds no other enforcement**: the sweep still records what it records, and A8
> still owns the residual.

> **Normative — the sweep is several writes, and what a sweep that stops part-way leaves is
> stated rather than inherited.** Each `→ SKIPPED`/`SUPERSEDED` is **its own compare-and-swap**
> and `PlanStore` offers no multi-write commit (#257's own observation, §12), so a sweep over two
> or more undisposed steps can land some and not the rest — a stale `expected_version`, a store
> failure. **The residual is exactly what landed**: the steps swept are durably
> `SKIPPED`/`SUPERSEDED`, and **the steps not swept stay at the status the sweep found them at —
> `PENDING` or `AWAITING_APPROVAL`**, the two the sweep takes as sources. **An unswept
> `AWAITING_APPROVAL` step keeps its live confirmation**, so the resume path and §3's
> superseded-plan residual stay reachable on exactly this failure and on no other, **nothing is
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

> **Normative.** **ADR-0042 §3's named follow-on is discharged here, and the per-request deadline
> it books is the driver's.** §3 does not already carry one: it ratifies the `timeout` as the
> **per-attempt** budget and says in terms that it is *"**not** an overall wall-clock deadline for
> the whole request"*, booking the overall one as *"a decision that belongs with that plan-driving
> stage"*. **This is that stage and this section is that decision** (§16), so the figure's meaning
> is **fixed here** rather than read off §3. **The `timeout` an adapter supplies to `converse` or
> `resume` is the whole request's budget.**
> **The deadline is fixed once per adapter call**, from the **monotonic** source §9 names below,
> **at the entry to that call and immediately after the `timeout` is validated** — before
> routing, before context assembly, before the turn's first `Planner.plan` call, and therefore
> long before anything is driven — and every disposal that call makes,
> **the resumed one and every step of every walk that follows it**, is passed the **remaining**
> duration rather than the whole figure. **No lane passes the adapter's figure unchanged to more
> than one disposal, and no lane fixes a second deadline inside one call.**

> **Normative — it gates starting and never cancels what is running, and what it gates is every
> unit of work the walk starts.** Immediately before it begins **any** of them — **a step's
> disposal**, and **an interpretation call the plan declares** (§1), which is a model call the
> walk makes between two dispatches — the driver reads that same monotonic source and computes
> the remainder. Where
> the remainder is **not strictly positive** it **starts neither**, the walk stops (§2), and the
> steps after it stay `PENDING` exactly as on any other stop trigger — an interpretation the walk
> did not make leaves its row unwritten and the steps conditioned on it **`PENDING` and not
> `SKIPPED`**, because nothing settled them. **Gating the dispatch alone would leave the budget
> bounding only part of the walk**: ADR-0253 §8 bounds the *number* of interpretation calls by
> the plan and says nothing about their duration, so a plan declaring several could spend a
> multiple of the user's wait without ever starting a second step. **A step or an interpretation
> already begun runs to its own completion**, which is ADR-0228 §4's posture in its
> own words — *"a planner call already begun runs to its own completion, and a turn's total
> duration may therefore exceed its budget by one planner call and one servicing"*, read one level
> over as one step's disposal. **The figure passed to
> `StepRunner` is therefore always strictly positive**, which ADR-0029 §4 requires: *"a zero or
> negative duration is refused rather than treated as an instantly-expired deadline"*.

> **Normative — the adapter's figure is validated at the entry to the adapter call, and a
> never-positive budget is refused rather than stopped.** **ADR-0029 §4's own test** — a
> `timedelta`, **strictly positive** — is applied to the `timeout` **at the first statement of
> each public entry point that takes one** (`converse`, `converse_spoken`, `resume` and the
> streaming pair), raising `ValueError` where it fails, which is
> `orchestration/executor.py`'s existing `_checked_timeout` applied at a second seam rather than
> a new rule. **At the entry and not where the deadline is fixed**, because a `converse` reaches
> routing, context assembly and `Planner.plan` before anything is driven: a check placed at the
> driver would let a zero budget spend a model call first, which is the outcome the arm below
> forbids, and a path that restates or routes without entering the driver would bypass it
> altogether. **So it runs before routing, before planning and before any I/O**, and **the
> monotonic deadline is fixed at that
> same instant** (above) — so the planning the turn does before it drives **consumes** the user's
> budget rather than preceding it. **A deadline fixed when driving began would replenish it**: a
> `converse(timeout=PT1S)` whose first planner call took twenty seconds would then hand its first
> step a fresh second, and the call would spend twenty-one against a budget of one, which is false
> of *"the **whole request's** budget"* and of the one-user's-wait quantity §9 keeps apart from
> the other two. **The two cases are
> not the same and must not collapse into one**: a budget that **expires during** the walk stops
> it and leaves the remaining steps `PENDING` (§2), while a budget that was **never** positive —
> `timedelta(0)`, a negative one, or a value that is not a `timedelta` at all — is a caller fault
> ADR-0029 §4 rules *"refused rather than treated as an instantly-expired deadline"*. Without
> this clause the driver's stop rule would swallow it: the first remainder would be non-positive,
> the walk would stop having started nothing, and the `ValueError` `StepExecutor` raises today
> would never be reached, turning a refusal into a silent empty turn. **It is checked once per
> adapter call**, and no stage re-checks it.

> **Normative — the deadline is an elapsed duration, so it is measured on a monotonic source and
> never on the injected `Clock`.** The driver takes both the deadline and every remainder from
> **the event loop's monotonic clock** (`asyncio.get_running_loop().time()`), which is
> `orchestration/consolidation.py`'s own construction for its run budget and is taken rather than
> re-argued. `core.clock.Clock` is scoped to **wall-clock instants** and ADR-0026's Consequences
> rule the other contract out in terms — *"measuring an elapsed duration across a DST transition
> or an NTP step is a different contract this one does not provide and should not be stretched
> to"*. **A wall-clock reading moved backwards by NTP or an operator would make the computed
> remainder larger**, topping the request's budget up for as long as the correction lasted and
> making a later remainder **exceed** an earlier one — the two things the clauses above forbid,
> reached through the instrument meant to enforce them. **The monotonic source is what makes the
> non-increasing rule true**; it does not make the sequence strictly decreasing, and nothing here
> asks it to.

> **Normative — and no seam, type or collaborator is added for it.** The source is read from the
> running loop at the point of use: **no `core` type is added, no `Clock` is injected for it, no
> constructor parameter is added to `StepRunner`, `StepExecutor` or the driver (ADR-0058), and no
> `Settings` field is minted** (§11, and the no-configurable-figure clause below). **What the
> injected `Clock` is still read for is unchanged and is not this section's**: an instant a rule
> compares against a stored one — ADR-0253 §5's `evidence_recency` among them (§1, §5) — where a
> wall-clock instant is exactly the right contract.

> **Normative — the remainders are *non-increasing*, and the strictness lives on the gate rather
> than on the sequence.** Every remainder is computed from **one** deadline fixed once per adapter
> call, so no later one exceeds an earlier one; **two consecutive ones may be equal**, because a
> monotonic source guarantees only that it does not go backwards and a platform whose resolution
> is coarser than the work between two readings — or a conversion that lands both in the same
> microsecond — returns the same figure twice. **What is strict is the gate**: a step or an
> interpretation starts only on a remainder that is **strictly positive** (above), which is
> ADR-0029 §4's requirement and does not depend on the sequence decreasing at all. **A
> requirement that each remainder be strictly smaller would be a platform-dependent contract**
> — true on one host and false on another for the same correct implementation — which is why it
> is not stated and why the arm below tests a strict decrease only over a **controlled** source
> advanced by known intervals.

> **Normative — *two* units of work the remainder does not gate, and both are named rather than
> left for a reader to find.** **The first is the turn's first `Planner.plan` call**: ADR-0251 §4's
> never-gated-first-call clause is ratified, binds entire and is relied on here (§16), so a turn
> whose routing and context assembly consumed the whole `timeout` still makes it. **The second is
> ADR-0254 §14's optional phase-4 model call, where a deployment lands one** — the clause below
> and **issue #2312**, which is where whether it should be gated is decided. **Everything else is
> gated**: every step's disposal, every interpretation the walk makes, and every **licensed** round
> (§10) are each admitted only on a strictly positive remainder. **The count is two and not one**,
> and no lane reads the first-call clause as the whole of the exception.
> So *"the whole request's budget"* means that this decision's driver spends nothing
> outside it — **not** that a `converse` can never exceed it, which ADR-0228 §4 already says it
> can: *"a planner call already begun runs to its own completion, and a turn's total duration may
> therefore exceed its budget by one planner call and one servicing."* **This decision gates the
> first call no more than ADR-0251 §4 does and no lane reads §9 as gating it**; whether it should
> be gated is that decision's question and not this one's (§12).

> **Normative — phase 4's evaluation is *inside* the request's budget and is not *gated* by it,
> and the difference is stated rather than left to a reader.** §9 fixes the deadline at the entry
> to the adapter call, **before** routing, planning and ADR-0254 §14's phase-4 evaluation, so
> whatever phase 4 spends is **charged** to the remainder the walk then reads. **It is not
> stopped part-way**: no clause of this decision interrupts phase 4, and a plan whose validation
> outlives the budget reaches a walk whose first remainder is not strictly positive and which
> therefore **starts no step** — the stop rule working rather than a gap in it. **What that costs
> is bounded and is stated, and it is bounded *conditionally***: ADR-0254 §14's **four checks**
> evaluate *"deterministically and over stored values alone"*, so **where a deployment takes no
> phase-4 model call** the evaluation makes none and reaches no egress, and its cost is linear in
> the plan's steps over reads the store already serves. **Where a deployment does take one, that
> bound does not hold and this decision does not supply another.** ADR-0254 §14's second normative
> block licenses exactly such a call — *"A **phase-4 model call**, where a deployment makes one, is
> given the plan and the `GoalBrief`"* — and this document's `Status` record keeps that block
> binding verbatim. So a deployment that lands one can begin a provider call at phase 4 **after
> the request deadline has already expired**, and the walk that follows correctly starts no step
> while the user has waited out a call nothing gated. **That is booked, not solved**: whether the
> optional call is gated on the remainder, bounded by a timeout of its own, or left ungated with
> the cost accepted is **issue #2312**, and **gating phase 4 itself is ADR-0254 §14's to decide
> and is not taken here** (§12). **No lane reads this section as having bounded that call.**

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

> **Normative — a cancellation delivered from outside is charged and delivered onward, and it is
> stated once here for every seam this decision adds.** `CancelledError` is a `BaseException`, so
> it passes an `except Exception` untouched. **Every working interval a walk consumed before a
> cancellation reached it is charged to `AttemptEffort.working` exactly as an interval ended by a
> raise is** — the rule above says *every* working interval and not every interval that ended
> well — and the `commit_attempt` that charges it runs **while the resources are being made safe**,
> which is the window ADR-0060 §1 allows: *"A method may defer delivery while it makes its
> resources safe, but it re-raises."* **The cancellation is then delivered onward, never absorbed**
> — not converted to a return value, not swallowed by the accounting, and not replaced by a
> failure of the accounting itself (§1's guard, one seam over). **No lane catches it to compose an
> answer over what ran, to sweep the remainder, or to skip a step.** Where the charging
> `commit_attempt` itself raises under cancellation, §1's precedence binds unchanged: the
> cancellation reaches the caller and the ledger **undercounts** (§6, §12).

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
> durable is minted**. A walk ended with an **unexpected finding** when **all three** of the
> following hold: it **ran to the end of the plan**; it moved **at least one step
> `PENDING → SKIPPED` under §2's skip rule**; and **at least one step it so skipped is one the
> plan declared no alternative for that the walk took** (below). The plan declared a requirement
> about the world — a dependency, a `verifies`, a `when`, a resolvable reference — the world did
> not meet it, **and the plan said nothing about what to do then**.

> **Normative — what it is for the plan to have declared the alternative, in ADR-0253 §9's own
> terms; the test is that a sibling branch was *dispatched* rather than merely declared, and it is
> taken **per refusal ground** and never over one of them.** The alternative to a skipped step was
> **taken** only where **both** hold: the step was skipped under §2's **third** case alone — a
> member of its `when` not satisfied — and **every** member of that step's `when` that was not
> satisfied has a **sibling the walk dispatched**. A **sibling** is a step of the same plan
> declaring a condition that names the **same** element on the **same** basis and requiring a
> **different** member of `InterpretationVerdict`, whose own `when` that same verdict satisfied.
> That is
> ADR-0253 §9's own definition of the relation, taken rather than invented: *"Two steps declaring
> conditions that name the **same** element on the `INTERPRETATION` basis and require
> **different** members of `InterpretationVerdict` are two branches."*

> **Normative — one unanswered ground is enough, and the driver evaluates every member to know
> it.** ADR-0253 §5 lets a `when` carry several conditions and makes a step eligible only where
> **every** one is satisfied, so a step may be refused on two grounds at once. **A plan that
> declared a branch for one of them and nothing for the other has answered half of what the walk
> found**, and the half it did not answer is exactly what a licensed round exists to learn about —
> so **one unsatisfied member with no dispatched sibling leaves the finding standing**, however
> many of the others have one. **The driver evaluates every member of a skipped step's `when`
> rather than stopping at the first unsatisfied one**, which is §1's own wording — *"every member
> of `when`, by ADR-0252 §6's four tests"* — and is what makes the predicate computable at all.

> **Normative.** **A step skipped on any of
> §2's other three cases has no declared alternative by construction** — a `FAILED` or `SKIPPED`
> producer, a `verifies` that does not hold over a `SUCCEEDED` producer's output, and an
> unresolvable `resolves` are none of them a branch ADR-0253 §9 lets a plan condition a sibling
> on — so a skip on one of those **always** carries the finding.

> **Normative — declaring a branch is not taking it, and a plan whose branches were all refused
> carries the licence.** Where the plan declared both readings and **neither** sibling was
> dispatched, the licence **fires**: the `INCONCLUSIVE` case, which ADR-0253 §9 rules *"enables no
> branch by itself"*, and the case where the sibling's own `when` failed one of ADR-0252 §6's
> other three tests. **No lane reads a declared-but-untaken branch as an expected outcome**, and
> no lane reads the predicate off the plan's text: it is read off **what the walk did**.

**A skip the plan anticipated is an expected outcome; a skip it did not is a finding.** ADR-0253
§9 draws exactly that line and this clause reads it at the walk's end: *"A plan **may express**
the alternative, so that the answer to an unexpected verdict is a branch the plan already declared
rather than a model asked at dispatch what to do next."* Where the plan expressed it and the walk
took it, **the answer to the verdict is the step that ran** — the goal's outcome was reached by a
route the plan declared for it, and there is nothing a further round could learn that the plan did
not already hold. Where the plan anticipated the **check** but not the **consequence of its
answer**, the walk ends with the goal's outcome unreached and nothing declared in its place, which
is the state §10 licenses one round over. **Without the third conjunct the ordinary conditional
plan would carry a licence**: ADR-0253 §14's dynamic plan skips its untaken branch on every run,
so *every* completed conditional walk would license a planner call, and the *"intact and
unreplanned"* property ADR-0253 §9's branch contract exists to buy would be reachable only by a
plan that declared no branches at all. **The narrowing changes the trigger and not the scope**:
what §10 supersedes in ADR-0251 is §4's four trigger conditions and §1's one occupancy term,
exactly as §16 and the `Status` line state them, over a licence that fires in fewer cases.

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

> **Normative — a licensed round is gated on §9's remainder as well as on ADR-0251 §4's guards,
> and it is the third unit of work the request's budget bounds.** A licensed round is a
> `Planner.plan` call with its servicing, made inside the same adapter call as the walk that
> licensed it, so **it is admitted only where §9's remainder is strictly positive at the moment
> of the check**, read from the same monotonic source and the same deadline. Where it is not,
> **no round is admitted and no second walk begins**: the turn composes over the first walk's
> outcome, which is what it does when the ledger is spent. ADR-0251 §4's (a) and (g) gate the
> round on the **planning** budget, which is ADR-0228 §4's and is a different quantity (§9); a
> round admitted by those and unbounded by the request's deadline would let one `converse` spend
> its user's whole wait and then start a model call, which is the guarantee §9's first clause
> states of *"the **whole request's** budget"*.

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
> what changes is what a conforming implementation must **refuse**, on **three** members, in
> **four** strengthenings. §3 adds **two** claim conditions to **`commit_transition`** — the
> attempt conjunct and the successor conjunct — and the execution-ownership refusal to
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

> **Normative — a walk drives several steps and `TurnOutcome.step` stays the one field `core`
> already has, so this states which step it carries.** `StepOutcome` is singular and **gains no
> member and loses none**. **`TurnOutcome.step` carries the last step *of the turn* that
> *returned* a `StepDisposition`** — across **both** the walks §10 permits and not the last walk's
> alone — and is **`None` where no step of the turn returned one**, which is what the field already
> carries for a turn of one walk. **Where a walk stopped at a step that returned one, that step is
> the last of the turn that did**, so the stopping step is what the field carries: the step that
> parked, the step that returned `INDETERMINATE`, the step whose disposition commits nothing (§2).
> **A stopped walk is the turn's last**, because §10 carries a licence only from a walk that *ran
> to the end of the plan*, so no second walk follows one that stopped and nothing later displaces
> its step. **The ground is what a spoke renders: where the goal stands**, which is the step the
> user must act on. **Two cases return no `StepDisposition`, and they differ in whether the step
> was dispatched at all**: a step the driver **skipped** is **not dispatched**, since §1 makes
> dispatching a step *calling `StepRunner.run`* on it and a skip calls it never; a step whose claim
> `commit_transition` **refused** **is** dispatched — §3 puts that claim inside the run, after the
> request and the ruling — and returns none because it **raises**. **Neither is carried here**:
> `Disposition` is the gate's verdict and holds no member for either, so naming one would fabricate
> a verdict no gate gave — and **what they cause at the user's surface is A9's**, which §12 books
> by name and this decision does not take. **No step's outcome is lost from the record**: every
> step's `status`, `skip_reason`, `failure` and `output` is on the `ExecutionState` its own walk
> opened, every one of those is durable in the plan store, and all of them are reachable from the
> goal — `attempts_of` to the attempt, its `execution_ids` to each execution its walks opened, and
> `get_execution` to the state — addressable within one by `step_id`, which is that model's own
> documented idiom. **What the returned
> `StepOutcome` carries is the projection**: `TurnOutcome.step` is the turn's last step to return
> a disposition and `StepOutcome.state` is that step's own execution, so where a turn made two
> walks (§10) the other walk's execution is read from the store rather than from the result.
> **Widening the result to carry both is refused here** — it is the sequence-valued `TurnOutcome`
> the Alternatives entry rejects as a breaking `core` change under golden rule 5, owed its own
> ADR. **This mints no `core` shape, no field and no
> enumeration, and supersedes nothing**: `StepOutcome`'s clauses bind verbatim — the disposition is
> still the gate's verdict and not the step's own result, and `step_id` is still required and still
> addresses a step of the returned `state`.

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
  `→ SKIPPED`/`SUPERSEDED` commit did not land, **from either source status** — `PENDING` and
  `AWAITING_APPROVAL` alike, the two §7 sweeps. **A8**, which reads a plan's leftover
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
- **The durable recovery of a resolved-but-unapplied answer.** **A8**, and this is an
  **acceptance requirement of that lane stated here** rather than a gap left to be met, on the same
  footing as the at-most-once one above. §3 states the residual: on the resume path ADR-0037 §4
  records the resolving decision at its **step 5** and claims at its **step 6**, so a claim §3's
  **attempt** conjunct refuses leaves the confirmation **resolved**, absent from
  `AuditTrail.pending_confirmation`, and its step standing **`AWAITING_APPROVAL`** — a user's
  answer that authorises a dispatch which never happened, on an attempt that can become `RUNNING`
  again. **A8's acceptance requirement is**: *a resolved confirmation whose claim was refused is
  durably recoverable — the step is re-askable or the answer is re-appliable — demonstrated over a
  paused attempt that later resumes.* **The superseded-plan ground is excluded by name**, because
  §7's sweep disposes of that step and the approval authorises nothing (§3, §7). **This decision
  lands no mechanism for it**: re-asking mints a second `CONFIRM` and re-applying needs the
  ruling and the transition to be atomic, which is #257's remaining half below. Fired by A8's
  reconciliation landing.

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
- **A bound on how many steps one walk may dispatch, and whether phase 4's own evaluation is
  gated on the deadline.** **Not decided**, and ADR-0253 §8's clause
  that *"`ActionPlan.steps` is **not** bounded by this decision"* binds. A step is selected, ruled
  on and claimed one at a time, so a long plan is expensive in a way the corpus already gates
  (ADR-0004 §7, ADR-0194 §3), and **§9 bounds the *walk* in wall-clock and not ADR-0254 §14's
  validation**: phase 4's cost is charged to the remainder but phase 4 is not stopped part-way,
  so a very long plan can spend its budget there and reach a walk that dispatches nothing (§9).
  Whether that evaluation should itself be gated is **ADR-0254 §14's**, which owns the phase.
  Fired by a consumer that needs a bound, or by a decision that gates the phase.
- **Evidence that moves between a step's evaluation and its committed claim.** **Not decided**,
  and §1 states the window rather than closing it: a concurrent turn's ADR-0252 §8 refresh
  supersedes a `STANDING` row without moving the goal's `revision`, so a step whose `when` the
  driver found satisfied can be claimed and invoked against evidence that is superseded by then.
  Closing it needs either **a value the claim carries** — which §3's argument against a
  caller-supplied revision applies to unchanged — or **ADR-0252 §6's four tests evaluated inside
  `commit_transition`**, which needs a clock and a plan's conditions in the store. §13's Q4 rule
  bounds the interval meanwhile — **and §13 makes closing this window a prerequisite of that gate
  in its own right**, because none of the gate's three guarantees is this one. **Fired by a
  decision that chooses between the two**, and no lane reads this entry as licence to add either
  on its own authority. Filed as
  [#2309](https://github.com/leonapivato/ai-assistant/issues/2309).
- **A per-phase event log for an attempt.** ADR-0249 §13's entry, untouched; §10's high-water-mark
  clause is what makes it unnecessary rather than what forecloses it. Fired by a lane that needs
  the timings and carries its own retention and export obligations.

### 13. Q4's rule, carried and not discharged

> **Normative.** **No consequential capability is wired into a production deployment until the
> verification, uncertain-outcome and cancellation guarantees for its class are implemented and
> demonstrated.** A milestone may demonstrate dependent execution against controlled integrations
> with no such capability wired; **wiring one is what this rule binds.**

> **Normative — this decision adds *two* prerequisites to that gate, and the count is stated so a
> reader does not take the first for the whole. The first is §3's resolved-but-unapplied
> answer.** **No consequential capability is wired until the durable recovery of a resolved
> confirmation whose claim was refused is implemented and demonstrated** (§3, §12). **The gate's
> own three guarantees do not reach this one either**: it is A8's by §12, but it is not part of
> A8's *reconciliation* guarantee as the gate names it, so a deployment reading the three could
> wire a booking whose user says *yes*, whose attempt is paused at that instant, and whose answer
> is then consumed with nothing dispatched and no way to ask again. **It is stated here for the
> same reason the window below is** — the honest half of stating a residual rather than closing
> it — and is discharged by A8 and not by this decision.

> **Normative — the second prerequisite is the evidence-to-claim window §1
> states.** **No consequential capability is wired until the evidence-to-claim window is closed**
> — the interval §1 names, in which a concurrent turn's ADR-0252 §8 refresh can supersede a row
> between a step's evaluation and its committed claim (§1, §12, issue #2309). **The gate's own
> three guarantees do not reach it**: it is assigned to no lane by §12, so A8's reconciliation,
> A9's cancellation and A10's verification could each land and leave it exactly where it stands,
> and a deployment reading only the three would wire a booking that can be dispatched on evidence
> ADR-0252 §6 no longer counts as standing. **So the prerequisite is stated here rather than
> inferred**, and it is discharged by a decision that closes the window and not by this one.

**Adding the prerequisites is the honest half of stating a residual rather than closing it, and
without them the gate would be the argument that each residual is safe *and* would stop being able
to make it.** §1 declines the two mechanisms that would close the window because each is a contract
surface of its own; what makes that declension safe is precisely that nothing consequential is
wired while it stands. A gate whose conditions could all be met with the window open would give
that argument away at the moment it mattered — which is what both review lenses found at round 15,
and they were right. **The same shape is already in this document**: §7 states an obligation whose
mechanism is A8's and names A8's acceptance requirement as what discharges it, rather than leaving
the interval to be noticed.

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

- **L1 — the conjuncts and the ownership invariant.** `core/types.py`'s one field and its
  validator; **all four** of §3's strengthenings in `InMemoryPlanStore` and `SqlitePlanStore` —
  `commit_transition`'s **two** added claim conditions, the attempt conjunct with its widened
  state limb and the **successor conjunct**, and the execution-ownership refusal on
  `commit_attempt` **and** on `open_attempt`; the shared `PlanStore` conformance suite arms for
  each (§3's test 3, arm 6's two serial ownership cases, its paused and `EFFECT_UNRESOLVED` cases,
  its **three** dispatched-together arms — the successor race among them — and
  its class assertions) and the canonical fake in
  `ai_assistant.testing`; and the
  `wire/envelope.py` log entry and version bump **only if** the tree contradicts §11's dated
  observation; and §3's threading — the `attempt_id` keyword on `StepRunner.run`,
  `StepRunner.resume` and `StepExecutor.execute`, supplied by `engine.py`'s existing single-step
  drive from the `GoalAttempt` it already holds. It **drives nothing** and changes no behaviour of
  a turn: the one `→ RUNNING` claim in the tree is `StepExecutor._claim`, and after L1 it carries
  the attempt the engine opened. **The successor conjunct changes no behaviour of a turn either**,
  because ADR-0228 §5 drives *"exactly one plan of a turn … and it is the last"*, which nothing
  has superseded at the moment it is driven.
- **L2 — the driver, and the runner's request construction.** The plan-driving stage in
  `orchestration/`, the walk, §1's three driver evaluations and **`StepRunner`'s resolution of a
  step's `resolves` from the stored plan and execution while it builds the request** (§1), §2's
  stop and skip rules, §5's park re-evaluation and the fresh walk that follows it, §6's
  `EFFECT_UNRESOLVED` commit, §7's supersession skip, **§9's one deadline per adapter call —
  `timeout` validated and the monotonic deadline fixed at each public entry point, before routing
  or planning, and threaded from there rather than fixed when driving begins** — **§10's
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
> consequential integration wired. **M34 owes arms 14–19**, and no lane reads an M33 arm as having
> established one of them.

> **Normative — an arm is owed by the lane that lands the clause it tests, and the division above
> is about what a *milestone* demonstrates rather than a licence to ship a clause untested.**
> **No lane lands §6's `EFFECT_UNRESOLVED` commit and its partial-write residual, §7's
> supersession sweep and its partial-sweep residual, or §9's deadline and its validation without
> arms 14, 15 and 16 respectively**, and **no lane lands any seam this decision opens — §1's
> interpretation call and ledger commit, §3's claim, §5's resume, §6's second write — without
> arm 17**, which is §9's cancellation clause driven at each of them. **All four are
> controlled-fake arms needing no integration**, so nothing about them waits on a milestone.
> Where **L2** (§14) lands in M33 they land with it and the M34 list reduces to arms 18 and 19;
> where L2 lands in M34 they land there with it. **Arms 18 and 19 are the two that genuinely
> cannot move**: 18 is A9's lane's, and 19 needs a real integration §13 forbids until A8's, A9's
> and A10's guarantees are demonstrated. Without this clause an implementation could swallow §6's
> failed `commit_attempt`, resume §7's half-finished sweep, refix §9's deadline at each step, or
> let a `CancelledError` past its accounting, and still pass every arm its own lane owed — which
> is the gap the thin/full division exists to describe rather than to create.

**Thin — M33, on controlled fakes.**

1. **ADR-0253 §14's dynamic plan, driven end to end** — the arm #2255's *"Conditional plan spans
   multiple decisions"* is owed in its own shape, and ADR-0253 asserted it as predicates over
   constructed values because no lane of that decision drives. Here it is **driven**: one goal
   carrying the condition element, one plan with step 1 (`refresh_forecast`), interpretation 1
   (`reads` step 1's output at `"summary"`, `settles` that element) and step 2 (`book_campsite`,
   `when` on the `INTERPRETATION` basis requiring `QUALIFIES`). **And the plan declares the
   alternative**, which is what makes it ADR-0253 §9's branching plan rather than a one-sided one:
   a **step 3** (`search_nearby_sites`) whose `when` names the **same** element on the **same**
   basis and requires `DOES_NOT_QUALIFY`. The arm asserts that the driver
   dispatches step 1, performs interpretation 1 **after** step 1 is `SUCCEEDED` and its `verifies`
   holds and **before** step 2 is evaluated, and writes the row; and then, per verdict: on
   **`QUALIFIES`** step 2 is dispatched and step 3 is `SKIPPED`/`UNMET_DEPENDENCY`; on
   **`DOES_NOT_QUALIFY`** step 2 is `SKIPPED`/`UNMET_DEPENDENCY` and **step 3 is dispatched**; and
   in both cases **the plan is intact and unreplanned** and **the walk carries no licence**
   (§10), a sibling branch the same verdict satisfied having been dispatched. On
   **`INCONCLUSIVE`** **both** conditioned steps are `SKIPPED`/`UNMET_DEPENDENCY` — ADR-0253 §9's
   *"enables no branch by itself"* — the plan is **intact**, no step's record is revised,
   rewritten or re-dispatched, and the walk **does** carry a licence, which is arm 13's case
   reached through a plan that declared an alternative no verdict took.
   **And three paired arms over an interpretation that returns no verdict** (§1): where a
   `record`-backed interpretation performed before the first dispatch **raises**, no step is
   dispatched, **no `ActionRequest` is built**, no row is written and the turn **fails**; where the
   `reads`-backed interpretation 1 raises **after** step 1 is `SUCCEEDED`, step 1's transition and
   its `output` stand unchanged, no row is written, steps 2 and 3 are **`PENDING`** and neither is
   `SKIPPED`, nothing is re-dispatched and the turn **fails**; and where the call **returns a value
   outside `InterpretationVerdict`'s three members**, the same two assertions hold and **no row
   carrying a defaulted `INCONCLUSIVE` is written** — which is what stops an implementation reading
   a failed call as a does-not-settle answer. **Each of the three asserts the ledger**:
   `AttemptEffort.working` has **advanced by the interval the walk consumed up to the failure**,
   over a controlled monotonic source advanced by a known amount across the raising call, and
   `planner_calls` has not moved — against an implementation that commits elapsed time only after
   a call returns and would hand the next turn an allowance it has already spent (§1, §9). **And
   two arms over the double failure** (§1): with the interpretation raising and the charging
   `commit_attempt` then raising too — once on a stale `expected_version`, once on a store
   failure — the arm asserts that **the interpretation's failure is the exception that reaches the
   caller**, that the ledger failure is **not discarded but recorded in the driver's own
   structured log warning** — carrying the ledger failure's class and this decision's fixed
   literal, and nothing taken from the interpretation's exception — and that the residual
   is the stated one: `working` **undercounts**, the steps already dispatched stand, no step is
   skipped and nothing is re-dispatched. **And each is run with *both* exceptions already carrying
   a cause** — a transport error under the interpretation's, a database error under the ledger's —
   **and the interpretation's already carrying a `__context__` of its own**, a distinct sentinel
   exception set on it before the walk begins: each asserts that the propagating exception is the
   **same instance** the fake interpreter raised, that its `__cause__` is **still the transport
   error**, that its **`__context__` is still that same sentinel instance**, and that its
   `__notes__` is **unchanged**. **The `__context__` assertion is not implied by the other
   three**: `raise exc` inside an active `except` block rebinds `__context__` to the exception
   being handled and leaves identity, an explicit `__cause__` and `__notes__` exactly as they
   stood, so a driver that re-raised the interpretation from inside its ledger handler satisfies
   every other assertion here and still hands a reader **a store failure as the chain underneath a
   provider outage** — the one substitution §1 states these arms exist to stop, reached through
   the one channel they did not read. **And the two arms ADR-0013 §5's own wrong turn earns**: a
   fake whose
   interpretation calls raise **one cached exception instance**, failed **twice**, asserting
   `__notes__` is unchanged and no longer after the second failure than after the first; and **two
   walks failing concurrently over that one instance**, asserting neither leaves anything on it
   for the other to read.
   **And the two arms the warning's own two rules earn** (§1): a fake interpreter raising an
   exception **whose class name carries a sentinel string appearing nowhere else in the
   fixture** — ADR-0194 §11's sentinel construction, one seam over — asserting the sentinel
   appears in **no field of the emitted warning**, which a mapped class, a bare
   `type(exc).__name__` and an interpolated message would each fail while satisfying every arm
   above, since none of them reads what the warning carries; and an **installed log processor that
   raises** on that warning, run over the same construction, asserting the interpretation's
   exception still reaches the caller **as the same instance with `__cause__`, `__context__` — the
   sentinel instance above, against the same rebinding — and `__notes__` each unchanged**, that
   the turn fails on it, and that the processor's own exception reaches no caller. They
   are what stop an accounting cleanup masking a provider outage as a store problem, what
   stop a `raise … from` overwriting the cause a reader needs, and what stop the driver writing on
   an object the provider owns.
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
   moment the walk reached it** and that no request was built. **And the `FAILED`-producer case
   asserts the walk did not stop there** (§2): it **reached** the dependent at all, which a walk
   stopping on the failed step never would, and the dependent is `SKIPPED`/`UNMET_DEPENDENCY`
   rather than `PENDING`. That single assertion is what separates the closed five-trigger stop
   rule from the deleted *neither terminal nor skipped* predicate, under which `FAILED` — absent
   from `TERMINAL_STEP_STATUSES` — would have stopped the walk and left this dependent untouched.
4. **A result reference reaches the ruling as itself** — a two-step plan where step 2's
   `resolves` fills a parameter from step 1's output; the arm asserts the resolved value is in the
   `ActionRequest.parameters` **before `ActionPolicy.decide` is reached** (ADR-0148 §1) and in the
   digest, and that no caller supplied it.
5. **A stale-revision claim is refused through the driver** — the goal's revision advances between
   step 1's success and step 2's claim; `commit_transition` refuses, **`ToolInvoker` is never
   entered** (a fake that records entry), step 2 is `PENDING` at its stored version, and the walk
   stops. **And the arm that puts the ledger on this path** (§9): over a controlled monotonic
   source advanced by a known interval across the refused claim, `AttemptEffort.working` has
   **advanced by the interval the walk consumed up to the refusal** and `planner_calls` has not
   moved. §9 states the charging rule of **every** working interval a walk consumes rather than of
   the intervals that end well, and an implementation charging only normal dispositions and §1's
   interpretation failures passes every other arm of this list while handing the next turn an
   allowance it has already spent. **Parameterized over the failure paths that reach it**: a
   `StepRunner.run` that consumes the interval and then **raises** — an audit failure, a planning
   store failure, and the refused claim above — and, over each, **the paired case in which the
   charging `commit_attempt` then raises too**, asserting §1's own precedence one seam over: the
   **originating** exception is the one that reaches the caller, the driver does not touch it, and
   the residual is a `working` that **undercounts**.
6. **A claim under an attempt that is not driving is refused** — the attempt is committed
   `ENDED` between step 1's success and step 2's claim; same four assertions. A paired arm asserts
   the **goal's revision did not move**, which is what makes this conjunct not redundant with the
   previous arm's. **And the arm that pins the binding**: with execution E opened under attempt
   A, A committed `ENDED`, and a second attempt **B on the same goal, neither terminal nor
   paused**, a claim for E naming **B** is **refused** — every goal-level fact about B is
   satisfactory and B's `execution_ids` does not carry E, which is the only thing that decides it
   (§3). **And the arm that closes the bypass**,
   in the shared `PlanStore` conformance suite: `commit_attempt(add_execution_id=E)` on **B**
   after A already holds E is **refused**, so the state in which E belongs to two attempts —
   under which a claim naming B would pass every conjunct — **cannot be reached through the
   store** (§3). **And every refusal this decision adds asserts its class, not merely that it
   refused**: `StaleExecutionError` **subclasses** `PlanningError` (`core/errors.py`), so an arm
   asserting only `PlanningError` is satisfied by the retryable class §3 forbids — a caller
   obeying that class's contract would then retry a permanently invalid write forever. **All
   seven** — `commit_attempt`'s and `open_attempt`'s ownership refusals, each of the attempt
   conjunct's four limbs, the seeded legacy claim included, and the **successor** condition —
   assert a `PlanningError` that is **not** a
   `StaleExecutionError`. **And the arm that keeps the two questions apart**: ADR-0249 §8's
   stale-revision refusal, reached through the same member, still raises `StaleExecutionError`,
   so an implementation cannot satisfy the set by making `commit_transition` raise one class for
   everything. **And the same case through the other door**: `open_attempt` with a
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
   **And the arms that pin the state limb's five members**: with the attempt committed
   `AWAITING_AUTHORIZATION` between step 1's success and step 2's claim, the claim is **refused**,
   `ToolInvoker` is **never entered**, step 2 is `PENDING` at its stored version and the walk
   stops; parameterized over `AWAITING_CLARIFICATION` and `BLOCKED`, which §3 treats alike. **And
   the paired arm that stops the limb being read as a `RUNNING` whitelist**: on the same
   construction with the attempt committed **`EFFECT_UNRESOLVED`**, the claim is **accepted** and
   the step runs — §6's own member, which a `RUNNING`-only rule would make unreachable. **And the
   arm that pins the resume ordering and the residual it leaves** (§3, §5): a park answered while
   the attempt still stands `AWAITING_AUTHORIZATION` is **refused**, `ToolInvoker` is **never
   entered**, and the walk **stops**. **The arm asserts what ADR-0037 §4's order actually
   leaves, and not that nothing was recorded**: that sequence is *"5. record the resolving decision
   with `resolves` set;"* then *"6. `ALLOW` → read back and execute"*, and the claim is in step 6 —
   so the arm asserts the **resolving decision is recorded** with `resolves` set, that
   `AuditTrail.pending_confirmation` no longer returns the confirmation, that the step is **not
   claimed** and stands **`AWAITING_APPROVAL` at its stored version**, and that nothing was
   invoked. **An earlier revision asserted "no ruling resolved", which ADR-0037 §4's order makes
   unsatisfiable**, and an arm nobody can pass is worse than no arm: it would have been deleted by
   the first lane that met it. The residual it pins is §3's, and its durable recovery is A8's
   (§12, §13). And the paired case in which ADR-0254 §14's `commit_attempt` has moved the attempt
   to `RUNNING` first resumes and dispatches — which is what makes the limb a gate on the pause
   rather than on the park. **And the arm that pins the superseded-plan ground is not this one**:
   §7's sweep moves a parked step of a superseded plan to `SKIPPED`/`SUPERSEDED`, so `resume`
   refuses **before** step 5 and no approval is spent — asserted as the confirmation still being
   returned by `pending_confirmation` after the refusal, which is what separates the two grounds.
   **And the arms that pin the successor conjunct** (§3): with execution E open on plan P and a
   plan P2 carrying `supersedes=P` saved between step 1's success and step 2's claim, the claim is
   **refused** on the non-stale `PlanningError`, `ToolInvoker` is **never entered**, step 2 is
   `PENDING` at its stored version, **the goal's revision did not move and the attempt is not
   terminal** — which is what makes this condition not redundant with either of the others — and
   P's `SUCCEEDED` step 1 and its output are unchanged. A paired arm asserts a claim on **P2** is
   accepted, so the rule is *this plan has a successor* and not *this goal has two plans*. **And
   the two-writer arm**, in the same suite and on arm 6's dispatched-together construction:
   `save_plan(P2 with supersedes=P)` dispatched together with a `→ RUNNING` claim on a step of P.
   **The assertion is over which write linearized first and not over the final state**, because
   both records standing together is a *legitimate* outcome — the claim that won, followed by the
   save — and §4's committed-claim rule is what makes it one. So the arm asserts **exactly one of
   two histories**: the claim linearized **before** the successor's persistence, in which case it
   **lands** and the step is `RUNNING` and the save then lands too; or the successor's persistence
   linearized **first**, in which case the claim is **refused** on the non-stale `PlanningError`
   and `ToolInvoker` is never entered. **What no history may show is a claim that linearized after
   the successor was persisted and nevertheless landed**, which is the only state the conjunct
   forbids. The observation is made from the store rather than from the wall clock — the arm reads
   whether `get_plan(P2)` resolves at the instant the claim is decided, on the same controlled
   construction ADR-0249 §12's dispatched-together arms already use. The serial arms above cannot
   see that interleaving, and an implementation that read
   the plan's successors, compared and then wrote across a suspension passes every one of them
   while letting a claim that lost dispatch anyway, which is the race §7's sweep cannot close from
   another turn.
7. **The store-level invariant, in the shared `PlanStore` conformance suite** (§3's test 3), over
   both implementations and the canonical fake: no `→ RUNNING` transition is ever accepted whose
   goal revision is not the stored one; none whose attempt is unknown, does not carry this
   execution in its `execution_ids`, or is in a state that is **terminal or paused** — the five
   members §3 names, with `EFFECT_UNRESOLVED` asserted **accepted** in the same parameterization;
   none naming an execution more than one attempt names; and **none whose plan a stored plan
   supersedes**. **And two constructions are asserted
   unconstructible rather than refused**: `attempt_id` on any other `to_status`, and a
   `→ RUNNING` transition carrying **none** — which is why neither is a store limb (§3).
8. **A parked middle step, answered and resumed** — a three-step plan whose **second** step rules
   `CONFIRM`: the walk stops, step 3 is `PENDING` and **not** `SKIPPED`, no third step is
   dispatched, the attempt is `AWAITING_AUTHORIZATION`, and the turn carries the confirmation.
   `resume` then disposes of step 2 — the attempt having been committed back to `RUNNING` by
   ADR-0254 §14's own path when the resolving ruling reached the trail, without which §3's paused
   limb refuses the claim — and the driver **walks the plan again**, passing over the now
   terminal steps 1 and 2 and reaching step 3 — from the stored execution and not from a carried
   index. A paired arm answers `DENY`: step 2 is
   `SKIPPED`/`APPROVAL_DENIED`, and step 3 — declaring `depends_on` step 2 — is
   `SKIPPED`/`UNMET_DEPENDENCY`. **And the arm that pins the overtake**: with step 2 durably
   `AWAITING_APPROVAL` and step 3 `PENDING`, a walk started afresh over that execution — the shape
   a restart produces — dispatches **nothing**, because it meets step 2 first. A driver that
   sought to the first `PENDING` step would dispatch step 3, which is the defect §5's
   start-at-position-one rule makes unreachable rather than checks for. **And the arm that pins
   which step the turn reports** (§11): over that same plan, with step 1 `SUCCEEDED` and step 2
   parked, the turn's `TurnOutcome.step` names **step 2** — the last step of the turn that
   returned a `StepDisposition`, and the one the walk stopped at — and
   **not** step 1, against an implementation that kept the retired single-step path's habit of
   reporting the first step it drove.
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
    ADR-0254 §14's unchanged limb. **And the arm that pins that a known failure dominates a
    deferral** (§1): a two-step plan whose **second** step carries a `when` of **two** conditions —
    one over an element **interpretation 1 of this plan settles**, and one over an element **no
    step and no interpretation of this plan bears on**, which the goal's rows do not satisfy — is
    **failed** at phase 4 and **replanned**, `start_execution` is **never called** and step 1 is
    never dispatched, against an implementation that defers the whole check because one operand is
    unavailable and lets step 1 act under a plan already known to be refused. A paired case flips
    the second condition to one the goal's rows **do** satisfy and asserts the plan **passes** and
    the attempt advances, so the arm separates *one operand unavailable* from *one operand
    failing*. **And the arm that keeps coverage out of the dominance rule** (§1): a two-step plan
    whose **second** step carries one argument filled by a `resolves` naming step 1 and one
    **literal** argument no standing authorization covers — phase 4 **defers** the coverage check
    entire, the attempt advances to `EXECUTE`, **no `CONFIRM` is put and no park is recorded at
    phase 4**, and the coverage comparison is taken at that step's own `ActionPolicy.decide` over
    the complete request (ADR-0254 §13). The paired case makes **every** argument of that step a
    literal, so the concrete request exists at phase 4: coverage is **available and refuses**, and
    §14's `CONFIRM` limb takes it. Together they are what stop an implementation asking a user to
    authorise a request the plan has not finished building. **Not covered**: a one-step
    transmitting plan with complete
    literal arguments and no covering authorization takes §14's `CONFIRM` park and the attempt
    commits `AWAITING_AUTHORIZATION` — **and is not replanned**, which is the disposition this
    decision routes nothing away from. **Passed**: a one-step plan needing none of it advances.
    Arm 1's plan is driven **through** phase 4 rather than around it.

13. **An unexpected finding is investigated inside the same attempt, and the ledger is charged**
    — the concrete case, end to end on fakes. A goal to book a campsite; a plan whose step 1
    checks availability, whose interpretation settles *the site is available* and whose step 2
    books it — **and which declares no alternative**, so no sibling branch the verdict satisfied
    is dispatched and §10's third conjunct holds. Step 1 succeeds, the interpretation returns
    `DOES_NOT_QUALIFY`, and step 2 is
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
    licence needed. **And the arm that pins the third conjunct of §10's predicate**: the same
    campsite plan carrying a **step 3** whose `when` names the same element on the same basis and
    requires `DOES_NOT_QUALIFY`, so the walk skips step 2 and **dispatches step 3** — **no licence
    is carried, no round is admitted, `Planner.plan` is never entered again** (a fake planner that
    records entry) and the turn composes over the one walk. A paired case returns
    **`INCONCLUSIVE`** over that same three-step plan, dispatching **neither** conditioned step,
    and asserts the licence **is** carried — which is what stops an implementation reading the
    conjunct off the plan's declarations rather than off what the walk dispatched. **And the arm
    that pins the predicate as per-ground** (§10): a step S whose `when` carries **two**
    conditions, over two different elements on the `INTERPRETATION` basis, **both** unsatisfied,
    beside a step T the walk **dispatched** that declares the sibling of the **first** of them and
    nothing for the second — S is `SKIPPED`/`UNMET_DEPENDENCY`, T ran, and the walk **does** carry
    a licence, because the plan declared no response to the second ground. Against an
    implementation that suppresses the licence as soon as any one unsatisfied member has a
    dispatched sibling, which would lose the re-investigation on exactly the plans that branch
    most.
    **And the arm that pins the trigger group**: the driven plan carries
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
    `ActionRequest` is built, so the second walk is gated exactly as the first.
    **And the arm that pins which step *the turn* reports across two walks** (§11): over that
    same pair, where the first walk dispatched step A and the second walk dispatched nothing —
    because phase 4 failed its plan, or because §9's remainder was gone before its first step —
    the turn's `TurnOutcome.step` names **step A** and **not** `None`, against an implementation
    that projects the last walk rather than the turn. A final paired arm
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
    **the step stays `INDETERMINATE`**, the turn **fails**, **no later step is dispatched and none
    is skipped**, and the committed step transition is **not lost or retried**. **The two cases
    assert different things about the attempt, because §6 states different residuals for them**:
    on the **store failure** the attempt **stays `RUNNING`**; on the **stale `expected_version`**
    the arm moves the attempt to `ENDED` through a second writer *before* the driver's
    `commit_attempt`, and asserts the attempt **still reads `ENDED`** afterwards — that the
    driver wrote nothing and did not restore `RUNNING` over the winner of the race. An arm
    asserting `RUNNING` on that limb would be unsatisfiable, since the stale version is stale
    *because* another writer moved it. They are what stop an implementation composing over the
    failure, sweeping
    the remainder, or re-driving the step. **And the arm that pins the scope of the no-skip
    rule** (§6): a three-step plan whose **first** step is independent of the others and is
    `SKIPPED`/`UNMET_DEPENDENCY` on an unsatisfied `when`, whose **second** returns
    `INDETERMINATE`, and whose **third** the walk never reaches. The arm asserts that after the
    uncertainty is recorded the first step is **still** `SKIPPED` with its original
    `UNMET_DEPENDENCY` reason, that nothing reverted or rewrote it, that the **second is durably
    `INDETERMINATE`** and the **third `PENDING`**, and that neither is skipped — and, on a paired
    case that supersedes that plan, that the sweep moves none of the three, the second staying
    `INDETERMINATE` rather than becoming `PENDING` or `SKIPPED` (§6's override of §7). It is what
    stops an implementation reading §6 as a rule over the whole plan and trying to undo a
    committed transition.
15. **Replan after partial execution preserves what happened** — a plan driven to its second
    step, superseded on a later turn: the first plan's `ExecutionState` and its `SUCCEEDED` step's
    `output` are unchanged, the attempt's `execution_ids` names both executions, and the
    superseded plan's undisposed steps are `SKIPPED`/`SUPERSEDED`, **`PENDING` and
    `AWAITING_APPROVAL` alike** (§7). **The arm asserts
    preservation and asserts nothing about a second dispatch**: whether the later plan's act
    happens at most once is §7's obligation, whose mechanism and whose demonstration are **A8's**
    (§12). **No arm of this decision requires a duplicate dispatch to be shown**, because no lane
    of this decision can prevent one. **And two arms over the partial sweep** (§7),
    **parameterized over both source statuses**: a superseded plan with **two** undisposed steps
    where the first `→ SKIPPED`/`SUPERSEDED` commit lands and the second raises — once on a stale
    `expected_version`, once on a store failure — asserting the exact residual, that the **first
    step stays `SKIPPED`/`SUPERSEDED`**, the **second stays at the status the sweep found it at**,
    no step takes any other status and no `SkipReason` is rewritten, the turn **fails**, nothing
    is re-dispatched, and the committed skip is **not lost or retried**. **The
    `AWAITING_APPROVAL` case asserts the confirmation too**: the unswept parked step keeps a live
    `AuditTrail.pending_confirmation`, so a later answer reaches `resume`, and the arm asserts the
    §3 residual that follows — the ruling recorded, the claim refused by the successor conjunct,
    the step still `AWAITING_APPROVAL`. Without it an implementation that raised on the parked
    step would pass the `PENDING`-only arms while reopening the hazard §7's widened sweep exists
    to close. They are what stop an implementation rolling the sweep back, sweeping again from a
    later turn, or reading the mixed state as a plan still driving.
16. **The deadline, decremented across steps and not replenished by a resume** — a three-step
    plan under a budget that two steps exhaust, **over a controlled monotonic source advanced by
    known intervals**: each `StepRunner.run` receives a remainder that is **strictly positive**
    and **no larger than the previous one**, and — because the source is controlled and advanced
    between the steps — **strictly smaller** here; the third step is never started, it is
    `PENDING`
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
    instant twice — the second step's remainder is still **no larger** than the first's, and
    strictly smaller where the controlled monotonic source was advanced between them: **the budget
    is not topped up**, so a driver that computed the remainder from the wall clock fails it. It
    is what stops ADR-0026's reserved contract being reached for here by accident.
    **And the arm that pins when the budget starts** (§9): a `converse(timeout=PT10S)` whose
    first `Planner.plan` call consumes PT9S on a controlled monotonic source leaves the walk's
    first step approximately **PT1S** and not PT10S, and a second case in which that call
    consumes the whole budget **starts no step at all** — asserted against an implementation that
    fixed its deadline when driving began, which would hand that step a fresh PT10S and spend
    PT19S against a budget of ten. **And the arms that pin the ungated units** (§9): a
    `converse(timeout=PT1S)` whose routing and context assembly consume the whole second on the
    controlled monotonic source still **makes its first `Planner.plan` call** — ADR-0251 §4's
    never-gated-first-call clause — and then **starts no step, makes no interpretation call and
    admits no licensed round**. **Over a fixture whose phase 4 takes no optional model call the
    exception is exactly one call wide**, and the arm asserts that. **A paired arm over a fixture
    that does land ADR-0254 §14's optional phase-4 call asserts it is two**, both ungated, which
    is §9's stated count. Asserting "exactly one" unconditionally would contradict the clause the
    arm exists to drive; which of the two a deployment sees is #2312's to settle.
    **And the arm that pins what a long phase 4 costs** (§9): a plan
    whose ADR-0254 §14 validation consumes the whole `converse` budget on the controlled monotonic
    source **passes** phase 4, the attempt advances to `EXECUTE`, `start_execution` is called, and
    the walk **starts no step, makes no interpretation call and builds no `ActionRequest`** — the
    deadline charging phase 4 without interrupting it, which is what §9 states and is why a long
    plan cannot spend a second budget on its own validation. **And the arm that pins what the
    budget gates** (§9): a
    two-step plan with an interpretation
    between the steps, where the budget expires during step 1 — the **interpretation call is
    never made**, its row is unwritten, step 2 is `PENDING` and **not** `SKIPPED`, and the walk
    stopped; and the paired case where it expires during the walk that carried a licence — **no
    licensed round is admitted, `Planner.plan` is never entered** and no second walk begins (§10),
    asserted against a fake planner that records entry. **And the arms that pin a never-positive
    budget** (§9): `converse(timeout=timedelta(0))`, a negative `timedelta`, and a value that is
    not a `timedelta` each raise `ValueError` from the adapter call, with **no execution opened,
    no step claimed and no model call made** — and the same three over `resume`. They are what
    stop the stop rule swallowing ADR-0029 §4's refusal.
17. **Cancellation on every path this decision adds** (§9, ADR-0060 §1), over a controlled
    monotonic source advanced by a known interval before the cancellation is delivered. A
    `CancelledError` is raised from outside into each of the seams this decision opens — **an
    interpretation call** (§1), **a `StepRunner.run`** (§1), **the `commit_transition` claim**
    (§3), **the `resume` that answers a park** (§5), and **the `commit_attempt` that records
    `EFFECT_UNRESOLVED`** (§6) — and **every** case asserts three things: the charging
    **`commit_attempt` is reached**, and either **returns** — with `AttemptEffort.working`
    **advanced by the interval consumed up to the cancellation** — or **raises**, in which case
    §1's precedence binds and the ledger undercounts; the `CancelledError` **reaches the caller**,
    not converted to a value and not replaced by a failure of the accounting — **as the same
    instance wherever this decision's own code caught it and re-delivered it**, which is §1's
    accounting and its logging guard and is what the assertion exists to refute, and **as a
    `CancelledError` and nothing narrower wherever the cancellation passed through an interval
    `StepExecutor.execute` manages**, whose re-delivery is ADR-0034 §1's and ADR-0029 §4's and
    which §4 forbids this decision to change; and **no later step is dispatched and none is
    skipped**. **What is asserted beyond those, and what is committed inside the call one of these
    seams makes, is cited rather than restated.** §4 is the ground: *"The driver introduces no
    second boundary, no pre-claim reservation, no post-claim window and no reachability fact."*
    **The entry-status assertion is the claim seam's and the resume seam's**, those being the two
    that make a `→ RUNNING` claim from one of §3's entry statuses: where no write of that seam has
    begun the step stands at the one it was claimed from — **`PENDING`** by a walk and
    **`AWAITING_APPROVAL`** by a `resume`, §3's two and only two — which the fixture reaches by
    delivering before that seam's first write is dispatched. **At the `commit_attempt` that
    records `EFFECT_UNRESOLVED` the residual is §6's own and is not an entry status**: §6 commits
    the step's `→ INDETERMINATE` transition and the attempt's write under **two**
    compare-and-swaps, so there the step stands durably **`INDETERMINATE`** whether or not the
    attempt write landed, which is what §6 already fixes. **And at the interpretation call, no
    `GoalEvidence` row is written for it and every row the goal already held is unchanged** (§1) —
    the **cancelled** route of the same clause the three paired arms above drive for a call that
    raises and for one returning a non-member, against an implementation that charges and
    re-raises correctly and defaults an `INCONCLUSIVE` row on the way out. **What is committed
    once a write has begun, inside `StepExecutor.execute`, this arm cites by clause and does not
    restate**: **ADR-0034 §1** for the window between the committed claim and entering `invoke`,
    **ADR-0029 §4** for the interrupted-call classification once `invoke` has been entered, and
    **ADR-0014 §4** for what recovery reads from a durable `RUNNING`. Those three are ratified,
    their arms are owed on their own lanes, and **this decision adds no interval inside that call
    and asserts no durable state there** — which is §4's clause above, applied to the arm that
    drives these seams rather than stated only of the boundary. **The one interval this decision
    does own it asserts, and it is `resume`'s**: a cancellation absorbed **after ADR-0037 §4's
    step 5 has recorded the resolving decision and before the claim its step 6 makes begins**.
    There the arm asserts that the ruling is **durably recorded**, the confirmation is
    **resolved** and no longer returned by `AuditTrail.pending_confirmation`, the step still
    stands **`AWAITING_APPROVAL` at its stored version**, and **nothing is invoked** — which is
    **the same durable state §3 states for a refused claim**, reached by a cancellation instead.
    **It establishes that state and nothing about repairing it**: the durable recovery of a
    **resolved-but-unapplied** answer is **A8's** by §12, and because the state is the same one,
    the recovery A8 owes — *"the step is re-askable or the answer is re-appliable"* — recovers
    it whichever produced it. **So §12's acceptance requirement is unchanged and no second one is
    minted here**, and no lane of this decision re-asks the question or re-applies the answer.
    **What each arm refutes is an implementation that catches `Exception`**: `CancelledError` is a
    `BaseException`, so such an implementation lets it past the accounting untouched, charges
    nothing, and passes every other arm of this list — none of which delivers one. **And the
    converse arm**: with the charging `commit_attempt` itself raising under the cancellation, the
    **cancellation** is what reaches the caller and the ledger **undercounts** (§1's precedence,
    §9), asserting that no lane lets a broad catch inside the accounting or the logging guard
    absorb it.
18. **A9's tests 1, 2 and 4**, stated here so the set is legible and **owed on A9's lane**.
19. **Real integrations**, under §13's rule: a consequential capability is wired only once A8's,
    A9's and A10's guarantees are implemented and demonstrated, **the evidence-to-claim window §1
    states is closed** (§13, §12, issue #2309) **and the durable recovery of a resolved
    confirmation whose claim was refused is implemented and demonstrated** (§3, §12, §13) —
    **five** conditions and not three, the fourth assigned to none of those three lanes and the
    fifth assigned to A8 but outside the reconciliation guarantee the gate names.

### 16. Records owed on earlier ADRs, under ADR-0082 §1

**Exactly three documents are partially superseded — ADR-0254 in two scopes, ADR-0251 in two and
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
**deferred** check from a **failed** one — **the unit being the operand and never the check**, so
a check carrying one unavailable operand and one that is available and refuses is a **failed**
check and reaches §14's replan limb unchanged — and ADR-0253 §2's `INDETERMINATE` treatment is the
precedent — a dependency *"neither dispatched, skipped nor resolved"* while its producer's
disposal is outstanding. **Every other clause of ADR-0254 binds entire and is relied on**: §3's
coverage conditions, §13's recheck-at-`decide` and its no-cached-verdict rule, §14's other clauses
as the `Status` line enumerates them, §17's Q4 rule (§13 of this document), and §19's reservation
of the re-entry mechanism to A7, which §10 discharges.

**ADR-0254 §17 — partially superseded in the discharge half of one sentence, and the scope is on
this document's `Status` line.** That section's normative block ends *"it is carried by A5, A6 and
A7 and **discharged by A8, A9 and A10**"*. §13 adds **two further** conditions to the wiring
gate. The **evidence-to-claim window** §1 states, closed — assigned to **none** of those three
lanes by §12. And §3's **resolved-but-unapplied answer**, durably recoverable — which §12 assigns
to **A8**, but which is no part of the **reconciliation** guarantee the gate names, so A8's
landing does not discharge it. So a reader holding only §17 reads A8's reconciliation,
A9's cancellation and
A10's verification landing as releasing a deployment to wire a consequential capability, and §13
refuses it: ADR-0070 §1's test met, and **partial** in ADR-0070 §3's sense, the scope being that
sentence's discharge half and nothing else. **§17's rule itself binds verbatim and is relied on**
— the verification, uncertain-outcome and cancellation guarantees, the milestone clause and
*"wiring one is what this rule binds"* — as do its **carry** half naming A5, A6 and A7, which this
decision is the third and last of, and §17's second normative clause that that decision's own lane
dispatches nothing and wires nothing.

**ADR-0253 §3 — relied on and not superseded, and the difference from ADR-0254 §17 is which text
is normative.** A reader would expect the same record here, because §3 carries the same gate and
the same owner's ruling. It does not get one, and the working is this: §3's **normative block is
the rule alone** — *"No consequential capability is wired into a production deployment until the
verification, uncertain-outcome and cancellation guarantees for its class are implemented and
demonstrated"* — which §13 quotes unchanged and adds a condition beside rather than inside.
§3's *"A5, A6 and A7 each carry it, and A8, A9 and A10 discharge it"* sits in the **prose** that
follows, as a quotation of the owner's ruling about which lane does which job, and a reader does
not release a deployment on it. **ADR-0254 §17 states the same assignment inside a normative
block**, which is why that one is superseded and this one is not — ADR-0082 §1's test applied to
each document's own text rather than to the substance both discuss. **Every other clause of
ADR-0253 §3 binds entire**, its milestone clause and its ADR-0188/ADR-0236 precedent included.

**ADR-0252 §6 — relied on entire and not superseded, and the evidence-to-claim window is not a
weakening of it.** A reader would expect a record here too, because §1 states a window in which a
step is claimed after a row that satisfied its `when` has become `SUPERSEDED`. **It does not get
one, and the working is this.** §6 fixes **which rows satisfy a condition** — the four tests, over
`STANDING` rows, evaluated *"at the moment of dispatch"* — and the driver obeys it exactly: §1
takes all four tests, over the goal's rows, at that moment, and a `SUPERSEDED` row satisfies
nothing then as it satisfies nothing ever. **What §6 does not state, in any clause, is that the
evaluation is atomic with the store write that follows it**, and no clause of ADR-0252 says that
the world may not move between a check and an act. The window is therefore a fact about **two
turns running at once** — which ADR-0014's and ADR-0029's notes of 2026-08-25 establish and
neither ADR-0252 nor this decision creates — and not a second reading of §6's tests. **No clause
of §6 is replaced, narrowed or given an exception**: this decision states the window (§1), assigns
it to no lane, names the two mechanisms that would close it (§12), and makes closing it a
condition of wiring anything consequential (§13). **A decision that closes it will not have to
undo a clause of this one**, which is the test ADR-0070 §3 puts on a scope; and were the window
instead read as §6 being weakened, the honest record would be a supersession of §6 rather than the
silence — which is why the working is shown here rather than left for a reader to reconstruct.

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
compare-and-swap and its commands-not-snapshots argument are what §3 strengthens by two
conjuncts.
**`SkipReason` gains no member** and **`StepStatus` gains no member**, so §3's and §4's
vocabularies are untouched. §7's **execution leases** and the **parallel-execution** half of its
step-dependencies bullet stay deferred and are named in §12; §7's **idempotency and
`INDETERMINATE`-resolution** deferral is A8's and is not taken here.

**ADR-0034, ADR-0029 and ADR-0039 — relied on and not superseded.** ADR-0034 §1's window rule and
its two qualifying grounds, ADR-0029 §4's deadline enforcement and its `INDETERMINATE`
classification, ADR-0029 §5's retry mechanism, and ADR-0039 §2's `failure`-required rule over
`{FAILED, INDETERMINATE}` each bind exactly as they stand; §4 states them rather than moving them,
and §11's validator is ADR-0039 §2's shape borrowed for a different field. **ADR-0029 §4's
strictly-positive test is applied at one more seam and is not changed by it**: §9 runs it on the
adapter's `timeout` at each public entry point, which is the same rule `orchestration/executor.py`
already runs at the invocation seam, read earlier so that the walk's stop rule cannot swallow the
refusal it requires.

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

**And the sentence a reader would raise is quoted and disposed of rather than left standing**:
§3 also says *"This `timeout` is the **per-attempt** budget of ADR-0029 §4 … **not** an overall
wall-clock deadline for the whole request"*, and §9 makes it the whole request's. **That is the
follow-on firing and not ADR-0070 §1's test met**, because §3 states the per-attempt reading as a
description of the system *as ratified* and says so twice in the same paragraph — the distinction
*"is dormant today"* because *"a turn drives at most one call"*, and *"Once the plan-driving stage
across a plan's steps lands … a 10-second budget would not bound a two-step turn to 10 seconds"*.
**A reader holding only §3 is not led to build something §9 refuses; they are told in terms that
the decision is outstanding and is this lane's** — §3's own words, *"rather than pretended to be
solved by threading one figure through unchanged"*, refuse the threading an unwarned reader would
have chosen. A deferral fired by the lane it names is a **record** under ADR-0082 §1 and not a
supersession under ADR-0070 §3, which is how §17 classifies ADR-0228 §14's and ADR-0249 §13's two
alongside it.

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
typed walk outcome that carries it and the guards that still bind — **and the trigger is narrower
than *a walk that skipped something***: a walk whose every skipped step had an alternative the
plan declared and the walk dispatched carries **no** licence, on ADR-0253 §9's own branch
relation, so the reader holding only §4 is unaffected by this decision on every conditional plan
that declares both readings and takes one. **The narrowing changes the trigger and not the
scope** — what is superseded is still those four conditions and that one term and nothing else, a
trigger that fires in fewer cases replacing no further clause. **(j)'s own two hazards are
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
that had already run — and **that rule is now enforced rather than only stated**, §3's successor
conjunct refusing a `→ RUNNING` claim on a plan a stored plan supersedes, in the same indivisible
step as the write, which widens neither §5's rule nor §7's and reaches no walk that had already
run — and the **no-new-failure-mode** clause held because every `save_plan`
preceded every drive — which a licensed round's save no longer does, so §10 states what a second
walk's persistence failure leaves behind. **Every remaining clause of ADR-0228 binds entire and is
relied on**: §5's every-plan-is-persisted rule, its oldest-first order, its one-persistence-site
rule and its turn-that-ends-early-persists-nothing rule all stand, and §14's plan-driving deferral
is **fired** rather than superseded (above).

**ADR-0252, ADR-0253 and ADR-0254's remainder — relied on and not superseded.**
ADR-0252 §6's four tests are evaluated by §1 and §5 and not restated; ADR-0253's §§1, 2, 4, 5, 6,
8 and 9 are each taken as the contract this lane was handed — **and §14's acceptance row is met
rather than contradicted by §10's licence**: *"the plan is intact and unreplanned in every case"*
is a statement about **that plan**, which nothing here revises, discards or re-dispatches a step
of (§7), and §10's third conjunct is what keeps the ordinary branching case **unlicensed** as well
as unrevised, a plan that declared the alternative and took it carrying no licence at all — and
**the three questions ADR-0253
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
`→ RUNNING` claim under an attempt that has ended, one under an attempt the same system is
reporting as **paused**, and one on a plan another turn has already **superseded**, and has no
rule for what becomes of the steps after a park, an uncertain effect or an expired budget. That
is ADR-0070 §1's test met, and a new
ADR is the instrument.

**It is a partial supersession of exactly three documents** (ADR-0070 §3) — **ADR-0254** in
§14's two-case enumeration **and in §17's discharge half**, **ADR-0251** in §4's trigger group and
§1's occupancy clause, and
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

**`TurnOutcome` reports the walk's steps as a sequence rather than the one step §11 projects.**
Rejected **here**, and not on the merits — it is the better shape for a surface that wants to
render a whole walk, and §11's projection is chosen because it is available without moving a
`core` model. Making `TurnOutcome` sequence-valued replaces a cross-boundary shape every adapter
and every spoke reads, which is a **breaking `core` change under golden rule 5** and takes **its
own ADR, ratified and merged before anything implements against it** (ADR-0015 §5) — and this
decision is about walking a plan, not about what a turn reports. It costs nothing to defer:
§11's rule loses no step's **outcome**, since every step's `status`, `skip_reason`, `failure` and
`output` are on the persisted `ExecutionState` its own walk opened, addressable by `step_id` and
reachable from the goal by §11's route — and **not** on a `StepTransition`, which §11 records the
plan store persists nowhere. What the singular field leaves unsurfaced is the other steps'
**dispositions**, which are the gate's verdicts rather than the steps' own results and which no
stored row holds — and a commits-nothing disposition writes no transition at all, so there is
nothing there to read either. That, and not the outcomes, is what a sequence would buy: a later
decision that gives a surface the whole walk reads every step's outcome from the store as things
stand.
**Fired by a surface that needs the sequence.**

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
