# 253. The plan declares what a step waits on, what fills its arguments and what must be evidenced before it is dispatched, and an interpretation settles one proposition over one record

- Status: Proposed
- **Partially supersedes [ADR-0249](0249-the-goal-carries-its-interpretation-the-attempt-carries-the-phase-and-the-planner-returns-its-understanding.md),
  in three narrowly stated scopes**, and §13 shows the working for all three.
  **§1's `GoalElement` field enumeration**, as ADR-0252 §1 already widened it — the model gains
  **`id`**, an `Identifier | None` naming this element durably across the revisions that retain
  it, and **`applicability`**, an `EvidenceApplicability | None` stating what the element is
  about in the one form ADR-0252 §2 can compare. Without the first, ADR-0252 §8's refresh test
  can never hold across two plans, because *"a re-reading necessarily interprets a **new**
  record"* and nothing else on an element survives a re-plan; without the second, ADR-0252 §9's
  invalidation predicate has no operands and that section's *"`GoalRevision.invalidates` is empty
  on every revision"* would be permanent. §1's every other clause binds **verbatim**: the
  append-only interpretation sequence, `Ground`'s closure at three members, the four-absences
  clause, the `version` clause, and `GoalElement`'s rule that the type expresses the
  correspondence rather than a rule to remember.
  **§7's `ProposedElement` enumeration and its four-shape validator** — *"a frozen model with
  `extra="forbid"` carrying exactly `text`, `ground`, `evidence_label`, `span` and `retains`. A
  **model validator** refuses every shape but **four**"* — gains one optional member on the
  **new**-element shape alone, the four axes an element's applicability is composed from, so that
  a planner can say what a condition it proposes is about. A **retaining** element still carries
  `retains` **and nothing else**, and §7's every other clause binds **verbatim**: the
  retained-or-restated validator, the retention-copies-forward clause, the ground-resolution
  rules and their refusals, the minted-record clause, the silent drop of an element whose ground
  does not resolve, the no-identifier-crosses-the-seam clause and the
  interpretation-is-the-model's asymmetry.
  **And §8's two-field clause**, in the field count alone: *"the fields any other component sets
  are `supersedes` and `targets_revision`"* becomes four, gaining each `StepCondition.about` and
  each `PlanInterpretation.settles`, under §5's identical discipline — taken by the loop, taken
  once, at the same moment — because an element's `id` is minted by `orchestration` after the
  planner returns and a plan conditioned on an element that same call proposed is otherwise
  inexpressible. §8's every other clause binds **verbatim**: `targets_revision`'s type and
  default, the loop-sets-it-once rule, the stamp-after-recording ordering and its argument,
  `save_plan`'s refusal of an unstamped plan, the not-driven rule, `commit_transition`'s claim
  condition, the store-not-the-driver argument and the not-a-second-`supersedes` clause.
- **Partially supersedes [ADR-0252](0252-evidence-is-what-a-response-supports-sufficiency-to-act-is-four-mechanical-tests-and-a-refresh-supersedes-the-row-it-displaces.md),
  in one term of one clause.** §14's writer clause lists *"an identifier, an instant, an
  **applicability**, a standing, a basis, a read kind, a source, a declaration, a count or a
  verdict of a read"* as values **no model supplies**. The `applicability` term stops being true
  on the **`INTERPRETATION`** basis alone, because §3's second source composes such a row's
  `supported` from *"the one region the interpretation step **declared**"* and only a plan can
  declare one — the two clauses of that decision are in tension and the specific rule governs
  (§7). **Every other term of §14 binds entire on both bases**, and every other clause of ADR-0252
  binds **verbatim**: the row's shape, the four sufficiency tests, the affirmative partition, the
  conflict and refresh rules, the invalidation predicate, the digest and the store widening.
- **No other ADR is superseded in whole or in part**, and §13 shows the working for each one a
  reader would expect to be — ADR-0014, ADR-0037, ADR-0145, ADR-0148, ADR-0152, ADR-0181,
  ADR-0226 and ADR-0251 among them. **ADR-0014 §7 is *fired* and not
  superseded**, which is the one a reader should check first: a deferral is a statement that a
  decision was not taken, so taking it leaves nothing to replace, and §13 records the one place
  this decision declines the shape that deferral sketched.
- Date: 2026-09-12

## Context

### Where this comes from

This is **A5** of #2255, the first ADR of milestone 33, and it covers phases **3 Plan** and
**4 Validate/authorize** of the six-phase lifecycle. ADR-0249 §13 defers to it by name:

> **`ActionPlan`'s step fields — `depends_on`, engine-resolved result references, the `when`
> vocabulary and `verifies`.** A5, which also fires ADR-0014 §7's output-references and
> step-dependencies deferrals.

ADR-0252 §15 repeats the assignment and adds to it, in three entries that this decision is
written to discharge: *"The step's declared condition, its declared applicability, its declared
recency requirement, its declared `basis`, and — on the `INTERPRETATION` basis — its declared
`declaration` and the member of that enumeration it requires"*; *"What a revision **requires**,
and therefore §9's two operands"*; and *"The interpretation step: the form of `declaration`, its
enumeration's members, its declared output schema, the call that produces a verdict, and which
record is its whole input."*

The design direction is revision 1 of the report on #2255 — part 2 §G.1 and §G.2, and part 1
§B.2's phase-3 and phase-5 rows. Each is treated as a concrete contract to ratify or to correct
against the tree, and §§1–8 below say which happened to each.

**Three owner rulings of 2026-09-12 (#2255) bind this decision.** Correction 2 — *"Producing a
reply never by itself establishes that the goal was achieved; completion criteria concern the
requested outcome"* — is why §4 separates the step-level predicate this decision lands from the
verification against the goal's criteria that A10 lands, and why nothing here writes
`GoalStatus.ACHIEVED`. Correction 3 — *"When understanding changes during investigation,
subsequent planning receives the updated goal view and identifies the interpretation revision it
targets"* — is ADR-0249 §8's `targets_revision`, already landed and **relied on here** as the
value that makes a plan's conditions resolvable against one revision's elements. And the answer
to **Q4** carries a rule this decision states in §3:

> No consequential capability is wired into a production deployment until the verification,
> uncertain-outcome and cancellation guarantees for its class are implemented and demonstrated. A
> milestone may demonstrate dependent execution against controlled integrations with no such
> capability wired; **wiring one is what this rule binds.**

### What the tree holds today, read rather than assumed, at `origin/main` `f0b8132d`

ADR-0249's L1 and L2 have merged and its L3 is in flight; **ADR-0250, ADR-0251 and ADR-0252 are
ratified and not implemented**, so every type of theirs this document names is a ratified
contract and not a value in the tree. `EvidenceDigest` and `EvidenceStanding` **are** in
`core/types.py`, because ADR-0249 §10 landed them; `GoalEvidence`, `EvidenceBasis`,
`EvidenceApplicability`, `MAX_EVIDENCE_RECORDS`, `ReadOutcomeKind`, `AttemptKind`, `TopicLabel`
and `GoalQuestion` are **not**, and §12 orders the implementing lanes against that.

- **`PlanStep`** carries exactly `id` (an `Identifier`), `intent`, `capability` and `parameters`
  (a `FrozenJsonMapping`, deep-frozen at validation). It has no dependency, no condition and no
  verification, and nothing on it refers to another step.
- **`ActionPlan`** carries `id`, `goal_id`, `steps`, `created_at`, `rationale`, `read_request`,
  `supersedes` and `targets_revision`. `steps` is validated for id uniqueness and is **not
  bounded**.
- **`SkipReason`** is closed at four members, and `UNMET_DEPENDENCY` **has no producer**: it
  appears under `src/` only in `planning/execution.py`'s legal-skip table and
  `testing/planning.py`'s copy of it, exactly as ADR-0014 §7 wrote it into the vocabulary
  *"from the start so the durable vocabulary does not have to change when it lands"*.
- **`StepExecution.output`** is written by `orchestration/executor.py` on a `SUCCEEDED` step and
  is **read by nothing**: no site under `src/` consumes one, which is the gap ADR-0014 §3 named
  — *"a later step that needs the booking reference produced by an earlier one has no way to
  continue but to re-run the earlier step"*.
- **`orchestration/engine.py` drives `turn.plan.steps[0]` and nothing else.** There is no driver,
  no dependency order and no second step.
- **`planning/planner.py` mints every step id itself** (`_step_payload` calls
  `self._id_factory()`), and the prompt says so in terms: *"Do not include step ids; they are
  assigned downstream."* The extraction reads exactly `intent`, `capability` and `parameters` off
  a raw step and refuses anything else as an `_ExtractionError`, which the planner answers with
  one repair prompt and then a decline.
- **`GoalElement`** carries `text`, `ground`, `evidence_id` and `span`, and has **no identity**:
  two revisions' copies of one retained element are equal values with nothing to tell them apart
  and nothing to name either by.
- **`PROTOCOL_VERSION` is 38**, `PlanExport.schema_version` is `Literal[8]`, and the plan store's
  `_SCHEMA_VERSION` is `2`.

### The gap this closes, stated as the failure the corpus has today

**A plan cannot express a decision that depends on anything.** Three of #2255's acceptance rows
are unreachable and each is unreachable for its own reason. *"Booking depends on the weather
condition being satisfied"* has no field to declare a condition on and no vocabulary to state one
in. *"Conditional plan spans multiple decisions"* has no way for a later finding to select
between two branches without discarding and re-planning the whole plan, which loses the record of
what was decided. And a step that needs the value an earlier step produced has, in ADR-0014 §3's
own words, *"no way to continue but to re-run the earlier step, which for a non-idempotent tool
means acting twice"* — the output is stored and nothing can name it.

**The pieces that would carry each are already ratified and already in the vocabulary, which is
what makes this additive rather than structural.** `SkipReason.UNMET_DEPENDENCY` has waited for a
producer since ADR-0014. `StepExecution.output` has been written and unread since the same
decision. ADR-0252 landed the evidence row, the four sufficiency tests and the applicability
algebra, and left exactly the declarations a step makes to this lane. What is missing is the
plan's half of each pair.

### What this ADR is not allowed to settle

**It drives nothing.** No lane of this decision dispatches a step, claims one, evaluates a
condition, resolves a reference, makes an interpretation call or writes a `SkipReason`. The
plan-driving stage is **A7's**; authorization coverage is **A6's**; retry, reconciliation and
`EFFECT_UNRESOLVED` are **A8's**; cancellation at the claim boundary is **A9's**; verification
against the goal's criteria and the producer of `GoalStatus.ACHIEVED` are **A10's**. §11
enumerates each with the condition that fires it, and §3's rule is what keeps the gap safe rather
than merely admitted.

## Decision

### 1. `depends_on`: earlier steps of this plan, backwards only, so a cycle is unconstructible

> **Normative.** `PlanStep` gains **`depends_on`**, a possibly-empty `tuple[Identifier, ...]`
> defaulting to empty, each member the `id` of a step **of the same `ActionPlan`** that appears
> **strictly earlier** in that plan's `steps` tuple.

> **Normative — `ActionPlan` refuses every other shape at construction.** A member naming a step
> the plan does not carry, naming the declaring step itself, naming a step at or after the
> declaring step's position, or repeating another member of the same tuple, makes the plan
> **not constructible**. The refusal is a validator on `ActionPlan` and not on `PlanStep`,
> because a step cannot see the tuple it sits in.

**Backwards only, so acyclicity is a property of the type rather than a check somebody
remembered to write.** A tuple in which every reference points strictly earlier admits no cycle
at all: any cycle needs at least one edge pointing forward or at itself, and both are refused one
member at a time by a comparison of two positions. The alternative — admitting forward references
and detecting cycles by traversal — buys nothing a plan needs and costs a graph algorithm whose
failure mode is a plan that validates and never terminates. It also costs nothing in
expressiveness: a planner emits an **ordered** list, ADR-0014 §3 makes `ExecutionState.steps`
*"one per PlanStep, same order"*, and two independent steps followed by one that waits on both is
expressible exactly as it is in any topological order.

> **Normative — the planner names a step by its position in its own emission, never by an id.**
> The envelope carries, per step, an optional `after` key whose value is a list of **1-based
> integer ordinals** into the `steps` list of that same envelope. The implementation that mints
> the step ids resolves each ordinal to the id it minted for the step at that position, and the
> `PlanStep` carries ids. **No step identifier is rendered to a model and none is accepted from
> one**, which is ADR-0228 §8's statement of ADR-0226 §3's namer rule binding this field, and it
> is the rule the tree's own prompt already keeps: *"Do not include step ids; they are assigned
> downstream."*

> **Normative.** An ordinal that is **not an integer**, is **less than 1**, is **not strictly
> less than** the declaring step's own ordinal, exceeds the number of steps in the envelope, or
> repeats another ordinal of the same list is an **extraction failure** for that envelope, on the
> same footing as a step missing its `capability`. It is not silently dropped and it is not
> repaired.

**A dropped dependency and a dropped element are not the same kind of loss, which is why the
disposal differs from ADR-0249 §7's.** That section drops an element whose ground does not
resolve *"silently and without failing the turn"*, and it can, because elements are independent
of one another — a revision missing one is a smaller true statement. A step's dependency is an
edge of a graph the rest of the plan is stated over: dropping it turns *"book only after the
cancellation succeeded"* into *"book"*, which is not a smaller plan but a different and more
dangerous one. So the envelope is refused and the planner's existing repair prompt is what
answers it; where repair also fails, the existing decline path is reached and no plan is produced
at all.

> **Normative.** **An empty `depends_on` means the step waits on no other step**, and it is the
> value on every step of every plan written before this decision. It does **not** mean *after the
> previous step*.

**This is the one place this decision declines the shape ADR-0014 §7 sketched, and the reason is
that the sketched default makes independence inexpressible.** That deferral reads *"A `depends_on`
DAG is additive later (an optional field defaulting to the implicit 'after the previous step')"*.
A default that manufactures an edge would mean no plan could ever declare two steps that may be
disposed of in either order, and it would silently attach a dependency to every step of every
plan already on disk — a claim about those plans that nobody made when they were written. A
deferral is a statement that a decision was **not** taken (ADR-0070 §1), so departing from its
parenthetical sketch replaces nothing and no supersession is owed; §13 records it as the note it
is.

> **Normative.** **`depends_on` narrows what may be dispatched and never widens it, and no lane
> reads it as a licence to execute two steps concurrently.** ADR-0014 §7's deferral names *"Step
> dependencies / parallel execution"* in one bullet; this decision fires the **first** half and
> leaves the second entirely untouched. A plan's steps remain an ordered sequence, the tuple order
> is preserved, and whether a driver may ever run two of them at once is a separate decision with
> its own concurrency, lease and store obligations.

### 2. `UNMET_DEPENDENCY` gets its first producer, and the rule is stated here and enforced by A7

> **Normative — the dependency rule.** A step's dependency on a producing step is **satisfied**
> only where that producing step's `StepExecution.status` is **`SUCCEEDED`** **and** the
> producing step's `verifies` predicate (§4) **holds over its `output`**. A producing step that
> is `FAILED` or `SKIPPED` **fails** it. A producing step that is `INDETERMINATE` **fails it and
> stops the branch**: neither the dependent step nor any step that depends on it, transitively,
> is dispatched, skipped or resolved, and each stays `PENDING` until the `INDETERMINATE` step is
> resolved explicitly.

**`INDETERMINATE` is treated differently from `FAILED` because a skip would assert something the
state exists to say we do not know.** ADR-0014 §4's words are the reason and are quoted rather
than restated: *"Automatically retrying it would risk acting twice; automatically failing it would
risk reporting a completed action as failed. So recovery does neither."* Skipping the dependent
step with `UNMET_DEPENDENCY` would record that the producer did not act, which is exactly the
half of the ambiguity that state refuses to pick; driving it would record that the producer did.
Leaving the branch `PENDING` is the only disposal that asserts neither, and **resolving an
`INDETERMINATE` step is A8's** (§11).

> **Normative.** A step whose dependency **fails** on a `FAILED` or `SKIPPED` producer, and a
> step whose condition (§5) is not satisfied, are each moved `PENDING → SKIPPED` with
> **`skip_reason=UNMET_DEPENDENCY`**. `SkipReason` gains **no member**, and ADR-0014 §4's
> `PENDING → SKIPPED` row and ADR-0041's addition to it are untouched.

**One reason for both, because both are the same fact about the step.** ADR-0014 §4 describes
that transition's trigger as *"nothing can run it"*, and a condition a plan declared and evidence
never satisfied is a dependency that was never met — on the goal's evidence rather than on a
sibling step. Minting a fifth member would widen a durable vocabulary carried in
`StepExecution`, `StepTransition`, `PlanExport` and the wire, to distinguish two cases whose
disposal, whose audit and whose recovery are identical.

> **Normative.** **No lane of this decision dispatches a step, claims one, evaluates this rule or
> writes a `SkipReason`.** The stage that walks a plan in dependency order is **A7's**, and it is
> the lane that takes this section as its contract. **At which moment a never-eligible step is
> moved to `SKIPPED`** — at the end of the plan's driving, at the end of the attempt, or not at
> all within a turn — is A7's and A9's; **which reason it takes** is decided here.

### 3. Nothing consequential is wired until the guarantees exist, and that is a rule rather than a note

> **Normative.** **No consequential capability is wired into a production deployment until the
> verification, uncertain-outcome and cancellation guarantees for its class are implemented and
> demonstrated.** A milestone may demonstrate dependent execution against controlled integrations
> with no such capability wired; **wiring one is what this rule binds.**

This is the owner's ruling on Q4 (2026-09-12, #2255) carried into the decision that first makes
dependent execution expressible, exactly as that ruling directs — *"A5, A6 and A7 each carry it,
and A8, A9 and A10 discharge it."* The construction has a precedent the corpus already uses:
ADR-0188 gates a capability on a record existing — *"no cloud embedder is wired until it is"* —
and ADR-0236 fails closed on a missing declaration. What it buys here is that the interval in
which a plan can express a dependency and the system cannot yet recover from an uncertain one is
an interval with **no real consequential integration in it**, rather than an interval whose
safety rests on nobody having wired one yet.

### 4. `verifies`: a mechanical predicate over the step's own output, and never the verification A10 lands

> **Normative.** `PlanStep` gains **`verifies`**, a **`StepVerification | None`** defaulting to
> `None`. `core/types.py` gains **`StepVerification`**, a frozen model with `extra="forbid"`
> carrying exactly `kind` (a `VerificationKind`), `field` (an `EncodableText | None`) and
> `equals` (a `FrozenJsonValue`, defaulting to `None`).

> **Normative.** `core/types.py` gains **`VerificationKind`**, a `StrEnum` valued by lower-cased
> member name and **closed at exactly three members**. The vocabulary is **added to and never
> renamed**, on `Ground`'s own rule (ADR-0249 §1, itself ADR-0226 §4's).
>
> - **`OUTPUT_PRESENT`** — the producing step's `output` is not `None`.
> - **`FIELD_PRESENT`** — the `output` is a JSON **object** carrying the key `field`, whose value
>   is not JSON `null`. An `output` that is not an object, an absent key, and a key whose value is
>   `null` each fail it.
> - **`FIELD_EQUALS`** — `FIELD_PRESENT` holds **and** that key's value equals `equals`
>   **byte-exactly**, compared as ADR-0148 §2 compares a canonical destination: *"comparison
>   against it is byte-exact. No canonicaliser folds case, strips, reorders or rewrites a form on
>   any ground weaker than the protocol saying those two forms are one recipient."* No lane folds
>   case, coerces a number to a string, compares a float by tolerance, or treats `1` as `true`.

> **Normative — a model validator refuses every shape but three.** `OUTPUT_PRESENT` carries
> neither `field` nor `equals`; `FIELD_PRESENT` carries `field` and no `equals`; `FIELD_EQUALS`
> carries both, and its `equals` may be JSON `null` only in the sense that `null` is not a legal
> `equals` at all — a predicate asserting that a present field equals `null` contradicts
> `FIELD_PRESENT`'s own requirement and is refused. The kind and the arguments it takes travel
> together or the value does not construct, which is ADR-0249 §1's move applied to one more type.

> **Normative — there is no path language, and the depth is one.** `field` names a **key of the
> output object** and never a path, a dotted expression, an index, a wildcard or a selector. A
> nested value is not addressable, and no lane adds an addressing syntax to this field.

**One level, because the alternative is the substitution language ADR-0014 §7 warned about.**
That deferral's own words for why output references waited are *"it is a substitution language
with real injection-safety questions"*. A path expression is that language: it is a string a
model wrote, interpreted by the engine against a structure a tool returned, and every
interpreter of an attacker-influenceable string is a surface. A single key is not an interpreter
— it is a lookup in a mapping, whose whole failure mode is *absent*, which is a case this section
already names.

> **Normative — `verifies` is evaluated in code and never by a model.** ADR-0249 §7's asymmetry
> binds it by name: *"A model may never clear a permission, a coverage test, a prerequisite or a
> **dependency**, and no clause of this decision or of any lane implementing it takes one on a
> model's word."* `verifies` is the second conjunct of §2's dependency rule, so a model evaluating
> it would be a model clearing a dependency. What a model supplies is the **declaration** — a
> member of a closed enumeration, a key name and a literal — and the comparison is arithmetic.

> **Normative — a step declaring no `verifies` imposes none, and `SUCCEEDED` alone satisfies the
> dependency.** This is ADR-0252 §6's own posture toward the recency figure — *"a step that
> declares no recency requirement imposes none"* — and it is not the fail-closed case ADR-0228
> §2(a) governs, because there is no absent **member of a closed vocabulary** here to read as a
> default. A mandatory `verifies` would oblige a planner to invent a predicate about a tool's
> return shape on every step of every plan, and an invented predicate is worse than none: it
> fails steps that succeeded and passes steps that did not, on a guess nobody recorded.

> **Normative — this is not the verification A10 lands, and the two are never conflated.** This
> predicate is about **one step's own output** and answers *did this step produce what the plan
> said it would*. **Verification against the goal's criteria** — whether the requested outcome was
> reached, with strength proportional to consequence, and the producer of `GoalStatus.ACHIEVED` —
> is A10's, is stated over the goal's `criteria` rather than over a step's output, and is **not
> this field**. **Nothing in this decision writes `GoalStatus.ACHIEVED`, `BLOCKED` or
> `ABANDONED`**, and ADR-0249 §4's clause that `ACHIEVED` gets no producer there is unchanged
> here.

**This is the owner's correction 2 made structural rather than remembered.** The correction reads
*"Producing a reply never by itself establishes that the goal was achieved; completion criteria
concern the requested outcome."* A field named `verifies` on a step is exactly the value a later
lane would reach for when asked whether a goal was achieved, and the answer would be *every step
returned what it said it would* — which is a statement about the plan's internal consistency and
not about the world. Saying so here, in the decision that mints the field, is cheaper than
discovering it in A10.

**Revision 1 of the report has `verifies` evaluated at two moments and this decision keeps both,
with the same evaluator.** §G.2 has the driver read it at dispatch as the dependency's second
conjunct; §B.2's phase-6 row has verification read *"the observed outputs and the goal's success
criteria"*. Those are two reads of two things: A7 reads **this** predicate over **this** step's
output, mechanically; A10 reads the goal's criteria, and whether that act makes a model call at
all is A10's to decide. Neither is the other, and this section fixes only the first.

### 5. `when`: what a step requires of the goal's evidence, in ADR-0252 §6's own operands

> **Normative.** `PlanStep` gains **`when`**, a possibly-empty `tuple[StepCondition, ...]`
> defaulting to empty, and **`evidence_recency`**, a `timedelta | None` with `gt=timedelta(0)`
> defaulting to `None`.

> **Normative.** A step is **eligible for dispatch** only where **every** member of `when` is
> satisfied for that goal by ADR-0252 §6's four tests, evaluated at the moment of dispatch. An
> **empty** `when` imposes no evidential requirement, and it is the value on every step of every
> plan written before this decision.

> **Normative.** `core/types.py` gains **`StepCondition`**, a frozen model with `extra="forbid"`
> whose fields are exactly:
>
> - **`about`**, an `Identifier`, **required** — on the value the store holds, the `id` (§7) of a
>   **condition element** of the `GoalInterpretation` the plan's `targets_revision` names; on the
>   value a planner returns, the **condition label** §9 fixes. **The loop substitutes one for the
>   other, once, and `PlanStore.save_plan` refuses a plan on which it has not** (§9).
> - **`basis`**, an `EvidenceBasis`, **required**.
> - **`requires`**, an `InterpretationVerdict | None` (§8) — **required** exactly on the
>   `INTERPRETATION` basis, **forbidden** on `READ_OUTCOME`, and **never** the does-not-settle
>   member.
> - **`read_kind`**, a `ReadKind | None` — admitted only on the `READ_OUTCOME` basis and
>   **forbidden** on `INTERPRETATION`.
>
> A **model validator** refuses every other shape, so a condition of the wrong shape is **not
> constructible**.

> **Normative — how each field feeds ADR-0252 §6's tests, stated once so no lane re-derives it.**
>
> 1. **Coverage.** The applicability the condition declares is the **`applicability` of the
>    element `about` names** (§7). A row's `supported` must cover it by ADR-0252 §2's
>    tuple-covers-applicability relation. Where that element carries **no** applicability, the
>    condition **imposes no coverage requirement** and the test is satisfied by any row whose
>    `supported` is non-empty — ADR-0252 §6 test 1 word for word, reached through the element
>    rather than restated.
> 2. **The evidence the condition declared.** The row's `basis` equals `basis`. On the
>    `INTERPRETATION` basis, the row's `declaration` equals `about` and its `verdict` **is**
>    `requires`. On the `READ_OUTCOME` basis, the row's `verdict` is **answering** in ADR-0252
>    §5's sense, and where `read_kind` is declared the row's `read_kind` equals it.
> 3. **Standing.** The row's `standing` is `STANDING`. Nothing on a `StepCondition` bears on it.
> 4. **Recency.** The **step's** `evidence_recency`, applied to **every** condition of that step,
>    evaluated at the moment of dispatch against the row's `as_of` where the source declared one
>    and its `read_at` otherwise. **A step declaring none imposes none** (ADR-0252 §6).

**One field carries the declaration and the coverage operand, and that is one carrier for one
fact rather than an economy.** `about` names a proposition of the goal — *the weather over the
trip permits it* — and the element that states it is the one place this system records both what
that proposition **says** (its `text`) and what it is **about** (its `applicability`, §7). A
condition that carried an applicability of its own beside a declaration naming an element would
be ADR-0251 §3's *"two carriers for one fact"*, with the first implementation to disagree with
itself being right in one of them; and it would leave ADR-0252 §9's invalidation predicate
without operands, because §9 compares what two **revisions** require and a value on a step is not
on a revision.

**`about` is required on both bases even though only one of them compares a `declaration`, and
the asymmetry is deliberate.** On the `INTERPRETATION` basis the element is the declaration
ADR-0252 §6 test 2 compares and ADR-0252 §§7–8 use to keep two propositions apart. On the
`READ_OUTCOME` basis a row carries **no** `declaration` (ADR-0252 §1) and test 2 compares none —
but test 1 still needs an applicability, and the condition still needs to say what it is about so
that ADR-0252 §9 can mark it stale when the goal's requirement moves. So the field does one job
on both bases and a second job on one of them, and nothing reads it as a declaration on a basis
whose rows carry none.

> **Normative — recency lives on the step and not on the condition**, which is ADR-0252 §6's
> clause taken as written: *"recency is the plan's declaration and never the evidence's property.
> The figure lives on the step, A5 lands the field."* **Evidence never expires by itself**, no
> sweep marks a row for age, and **no `Settings` figure, deployment flag or per-request parameter
> supplies a default** — that clause binds here entire.

> **Normative — a condition may require a `read_kind` and may never require a `source`.**
> ADR-0252 §6 leaves both to this lane, *"neither required nor forbidden here"*. `read_kind` is
> admitted because it is a member of a closed vocabulary present on every `READ_OUTCOME` row.
> `source` is **refused** because ADR-0252 §1 rules it *"absent on every row this decision's
> producers write"*, so a condition requiring one could be satisfied by no row that exists — a
> step that can never be dispatched, declared by a planner that had no way to know it. **The
> field returns to the table only with a producer**, which is decision 8's reader (ADR-0252 §15),
> and a lane that lands one may add it.

> **Normative — there is no negation, no disjunction and no nesting.** `when` is a **conjunction
> of positive requirements** and nothing else. No condition requires that a row **not** exist,
> that a verdict be **other than** a member, that a proposition be **unsupported**, or that two
> conditions be satisfied **alternatively**; and no condition contains another.

**Negation is refused because a requirement of absence is an assertion of absence, which the
corpus already forbids one level down.** ADR-0237 §7 binds it in terms: *"No consumer composes an
assertion of absence from an empty or short structured result — not to the owner, not into a
record, and not into a plan."* A condition reading *no row says the trip is unsafe* would dispatch
an act on the strength of a read nobody performed, of a source nobody asked, and of a proposition
nobody settled — which is exactly the reading ADR-0252 §5 refuses `EMPTY` for.

> **Normative — general disjunction is not expressible, and no lane reaches it by declaring two
> steps.** Two steps carrying conditions about **two different elements** are **not** alternatives
> and are **not** mutually exclusive: where both propositions are evidenced, **both** steps are
> eligible, and a plan whose two steps perform the same act performs it twice. §9's exclusivity is
> over **different verdicts of one element** and over nothing else. **Nothing in this decision
> makes an act at-most-once**, and no lane reads a condition as if it did.

**That is stated as a prohibition because the natural reading of §9 is that two branches are
always alternatives, and for two elements they are not.** *"Book if the site is available **or**
if the neighbouring site is"* written as two conditioned booking steps books twice on the day both
are available — a plan-level defect the condition vocabulary cannot detect, because each step's
requirement is independently true. A planner that means *either* means one proposition, and it
says so by naming the proposition it actually requires. **Making an intended effect happen at most
once is a different mechanism entirely** — it is the idempotency key and the `INDETERMINATE`
reconciliation ADR-0014 §7 defers and **A8** takes (§11), and no clause here stands in for it.

> **Normative — a `when` condition narrows and never clears.** A condition is a **requirement the
> plan adds** to a dispatch, and a step with no condition is exactly a step of the plans this
> system writes today. **Nothing a plan declares clears a permission, an authorization or a
> coverage test**, and a plan declaring fewer conditions authorises nothing: ADR-0004 §7's gate
> rules on every side-effecting call whatever a step's `when` says, and **authorization coverage
> is A6's** and is a second test a dispatch must pass (ADR-0252 §15).

**This is what keeps a model-declared condition on the safe side of ADR-0249 §7's asymmetry.**
That section forbids a model **clearing** a prerequisite, and #2096 item 8 gives the reason —
*"A model is a safe denier and an unsafe allower"*. A condition is the denying direction: a model
that declares one costs a dispatch, and a model that declares none has bought nothing it did not
already have, because the permission gate is where an act is cleared and no clause of this
decision reaches it.

### 6. Result references: a typed triple the engine resolves before the request is built, and no substitution language

> **Normative.** `PlanStep` gains **`resolves`**, a possibly-empty `tuple[ResultReference, ...]`
> defaulting to empty. `core/types.py` gains **`ResultReference`**, a frozen model with
> `extra="forbid"` carrying exactly `parameter` (an `EncodableText`, the key of `parameters` this
> reference fills), `step` (an `Identifier`, the producing step) and `field` (an
> `EncodableText | None`, a key of the producing step's `output`, absent meaning the whole
> `output`).

> **Normative — `ActionPlan` refuses every other shape at construction**, and each refusal names
> a state that would otherwise have to be resolved at dispatch by a rule somebody remembered:
>
> - `step` **must be a member of the declaring step's `depends_on`**. A reference is a dependency
>   and is not a second way of saying so.
> - `parameter` **must not be a key of the declaring step's `parameters`**. There is never a
>   literal and a reference competing for one argument, so no precedence rule exists to get wrong.
> - **No two references of one step name the same `parameter`.**
> - `field` is a **key name and never a path** — the depth is one, exactly as `verifies`' is (§4),
>   and no lane adds an addressing syntax.

> **Normative — the resolution, stated as a total function of two values both read from the
> `PlanStore`.** Before the `ActionRequest` for a step is built, each of its references is
> resolved: the producing step's `StepExecution.output` is read from the **stored execution**,
> the named `field` is taken from it where one is named, and the resulting `JsonValue` is placed
> at `parameter` in the mapping the request will carry. The **whole** input of that function is
> the `PlanStep` read from `PlanStore.get_plan` and the `ExecutionState` read from
> `PlanStore.get_execution`; **no caller supplies a resolved value, a parameter mapping or a
> substituted step**, and no entry point of the permission stage gains a parameter for one.

**That containment is ADR-0037 §2's property kept rather than re-argued.** That section refuses a
`PlanStep` parameter in terms: *"A `PlanStep` parameter would let a caller hand over one sharing
the planned step's id and naming a different capability or different arguments: the gate would
rule on *that* action and the executor would run it, while the `ActionPlan` the execution belongs
to went on recording an action nobody performed."* A resolver that took a caller-supplied mapping
would reopen exactly that, through the one input nobody would think to check. Reading both halves
from the store keeps the stage's whole argument intact: *"everything it decides about what has
already happened … is read from `PlanStore`"*.

> **Normative — the resolution is **before** the ruling, and nothing moves after it.** ADR-0148
> §1 is satisfied rather than worked around: *"The `ActionRequest` a policy rules on for an egress
> call is already complete… Nothing in it is resolved, canonicalised, defaulted, expanded or
> added after `ActionPolicy.decide` has been reached."* The resolved value is in `parameters`
> before the request is constructed, so ADR-0145 §1's schema check runs over the value that will
> actually be sent, ADR-0148 §2's canonicalisation of a destination-bearing argument runs over it,
> ADR-0152 §1's `bind` receives it — *"`parameters` is the `FrozenJsonMapping` the `ActionRequest`
> will carry, unaltered"* — and ADR-0021 §1's digest pins it.

> **Normative — an unresolvable reference is `UNMET_DEPENDENCY`, and never a default, a blank, an
> omission or a `null`.** Each of the following makes the reference unresolvable and the step is
> disposed of by §2's rule: the producing step is not `SUCCEEDED`; its `verifies` does not hold;
> its `output` is `None`; a `field` is named and the `output` is not a JSON object; a `field` is
> named and the object does not carry that key; the value at that key is JSON `null`. **No lane
> substitutes an empty string, a zero, an empty object, the parameter's absence, or a value from
> anywhere else.**

**A default here is the failure this whole family of mechanisms exists to prevent.** The
alternative shapes are each worse in a way the corpus has already ruled on: omitting the
parameter would send a call the schema check may still admit and the user was never asked about
(ADR-0145 §1's *"a check after the ruling asks the user about an action that cannot be
performed"*, arriving before it); substituting a blank would send an act at an argument nobody
chose. Refusing costs a skipped step the user can see. ADR-0148 §1's third clause is the same
direction on the same reasoning: *"Refusing costs a recoverable error the user sees; proceeding
costs a disclosure nobody can detect afterwards."*

> **Normative — the engine carries the value and the model never rewrites it.** No model is shown
> a producing step's `output`, no model is asked to restate a value it produced, and no resolved
> value passes through a model on its way into a request. **This is the whole of the reference
> mechanism**: a model wires a producer to a consumer and a piece of deterministic code moves the
> bytes.

**This is #2096 item 3's property bought by construction rather than asserted:** *"its lineage is
recoverable **by construction**, not by inspection."* The plan records which step and which field
fill which argument; the execution records what that step returned; the decision records the
arguments the policy ruled on. So *where did this argument come from* is answered by joining
three durable records, and **no new field is added to carry it** — a field with no consumer is
surface, which is ADR-0045 §1's and ADR-0028 §7's rule and the one ADR-0181 §1 cites for
declining a richer marker of its own.

> **Normative — the injection-safety question ADR-0014 §7 left open, answered.** That deferral
> withheld output references because *"it is a substitution language with real injection-safety
> questions and no consumer until an executor exists"*. **There is no substitution language.** A
> reference is a typed triple of three named values, never a string the engine interpolates into
> another string; a resolved value replaces **a whole parameter value** and never part of one; no
> template is parsed, no delimiter is scanned for, and no value a tool returned is ever
> concatenated into, embedded in, or used to select among, anything. The injection surface a
> template language has is **absent by construction** rather than mitigated.

> **Normative — a resolved value reaches the ruling and the confirmation as itself.** Because the
> request is complete before `ActionPolicy.decide` (ADR-0148 §1), a value a tool produced is in
> the arguments the policy rules on, in the digest ADR-0021 §1 pins, and in the payload
> description ADR-0148 §6 makes inspectable and ADR-0178 renders to a user being asked. **No value
> a tool produced is ever authorised unseen.**

> **Normative — `CarriedProvenance.planned_with_external_content` is not widened, and no lane
> reads a resolved reference into it.** ADR-0181 §2 states that fact over *"the material this
> system **selected** into the model call whose output produced that request's arguments"*, and a
> resolved value is not selected material and did not come from a model call — reading it in
> would make the field mean two things and would make ADR-0181 §3's comparison clause, which
> compares the binding *"as one whole"*, disagree with a `rebind` that has no execution to
> recompute it from. **Whether a dependency's own origin is a further input to authorization is
> A6's** (§11), and ADR-0181 §2's marked limit binds this decision entire: no clause here states
> or implies that anything detects external content embedded in text whose recorded origin is not
> external.

### 7. What a revision requires: an element gains an identity and an applicability

> **Normative.** `GoalElement` gains **`id`**, an `Identifier | None` defaulting to `None`, and
> **`applicability`**, an `EvidenceApplicability | None` defaulting to `None`.

> **Normative — `orchestration` mints the id, once, at the instant the element is first
> recorded.** Every element of every revision `orchestration` records after this decision carries
> one. It is **not** re-minted on a later revision that **retains** the element: ADR-0249 §7's
> retention copies an element *"whole and unchanged — its `text`, its `ground`, its `evidence_id`
> and its `span` exactly as the earlier revision recorded them"*, and the id and the applicability
> travel in that copy. A **restated** element is a new element and is minted a new id, because a
> revision that restates a proposition has stated a different one.

> **Normative — `None` is reachable by exactly one route and no lane writes it.** An element
> carrying no `id` is one recorded **before this decision** — by ADR-0249's implementation, on a
> tree between its lanes and this one — and it decodes. **Such an element is named by no
> `StepCondition` and settled by no interpretation**, so no condition over it is ever satisfied,
> and that is the fail-closed direction. This is ADR-0249 §8's own construction for
> `targets_revision`, word for word: the unstamped state exists for one interval, a row already
> on disk carrying it decodes, and the rule that reads it refuses to act on it.

> **Normative — no migration and no stored-record version moves for this.** The plan store's
> `schema_version` does **not** move: the clause above makes a stored element carrying no `id`
> and no `applicability` a conforming value rather than a row to repair, and a migration that
> minted an id for one would be inventing nothing but would also buy nothing — an element nothing
> can name is an element no condition was ever written against.

> **Normative — the element's `applicability` is what a revision requires, and it is ADR-0252
> §9's two operands.** That section's predicate — *"a `STANDING` row of that goal is marked
> `INAPPLICABLE` if and only if its `supported` covered the requirement the revision supersedes
> and does not cover the requirement the revision states"* — reads, for each condition element of
> the two revisions, that element's `applicability`. ADR-0252 §9's statement that *"until A5
> lands, `GoalRevision.invalidates` is empty on every revision and no row is invalidated"* is
> what this section ends.

> **Normative — the computation lands no later than the lane that can first dispatch against
> evidence.** This decision lands the operands and **no lane of it computes `invalidates`**,
> because §3's rule and §11's deferral mean no lane of it dispatches. ADR-0252 §9's own safety
> argument is the obligation and is taken as binding on the lanes after this one: *"the first
> lane that can dispatch against evidence is the lane that can also invalidate it."* **No lane
> lands the plan-driving stage on a tree where `GoalRevision.invalidates` is still empty by
> construction.**

> **Normative — the planner proposes the applicability and `orchestration` records it.**
> `ProposedElement` gains the four axes of an `EvidenceApplicability` — a window and the three
> label axes — on the **new**-element shape alone; a **retaining** element still carries `retains`
> and nothing else (ADR-0249 §7). `orchestration` composes an `EvidenceApplicability` from them
> under ADR-0252 §2's own validator.

> **Normative — declaring nothing and declaring something malformed are two different states, and
> only the first records an absent applicability.** An element proposing **no axis at all** is
> recorded with `applicability` **absent**, and §1 already makes such an element a legal element
> that imposes no coverage requirement (ADR-0252 §6 test 1). An element proposing **one or more
> axes that do not compose an `EvidenceApplicability`** — an empty sequence axis, a window with
> both ends unset, or a window whose `end` is not strictly after its `start` — is an **extraction
> failure for that envelope**, on §1's footing and reaching the planner's existing repair prompt;
> it is **never** recorded as an element with an absent applicability.

**Recording a malformed requirement as no requirement would silently widen every condition written
against it, which is the fail-open direction.** An element whose proposed window ran Sunday to
Saturday states a Sunday requirement its author meant mechanically; recorded with `applicability`
absent, ADR-0252 §6 test 1 imposes no coverage requirement at all and a standing, answering
**Saturday** row satisfies the condition — so a reversed pair of instants would enable a dispatch
the correct pair forbids. The element's `text` surviving does not preserve its mechanical
restriction, because no test reads the text. Refusing the envelope costs a repair prompt and, at
worst, a decline; recording it costs a dispatch on evidence about the wrong day. ADR-0148 §1's
third clause is the same direction on the same reasoning — *"Refusing costs a recoverable error
the user sees; proceeding costs a disclosure nobody can detect afterwards"* — and it is why §9
extracts every other vocabulary of this decision strictly rather than repairing it.

**The axes are the ones the planner already composes an ask from, so the seam gains no new
vocabulary.** As a dated observation at `f0b8132d` rather than a rule, `planning/planner.py`
already extracts a window and the three label axes out of a planner envelope for ADR-0240's
`StructuredAsk` (`_structured_window`, `_structured_axis`, `_iso_instant`), and ADR-0252 §11
already renders those same axes back to the planner on every evidence digest. An element's
applicability is therefore a value the planner can both read and write today, spelled the one way
this system spells it.

**Silently absent rather than dropped, and the asymmetry with ADR-0249 §7's ground resolution is
deliberate.** That section drops an element whose **ground** does not resolve, because a ground
is a warrant and an element stating one it cannot show is a false record. An applicability is not
a warrant — it is a comparison operand, and an element without one still says what it says.
Dropping the element would lose the user's stated constraint over a malformed window, which is
the downgrade §7's retention clause exists to refuse, arriving through a different field.

> **Normative — what a model supplies toward an **element** and what a model supplies toward a
> **row** are two questions, and this decision touches only the first.** ADR-0252 §14 rules that
> *"**No model supplies an identifier, an instant, an applicability, a standing, a basis, a read
> kind, a source, a declaration, a count or a verdict of a read**"*, and that clause is scoped
> *"toward evidence"* — it governs what composes a `GoalEvidence` **row**, whose `supported` is
> composed by `orchestration` from the records a response returned and from nothing else
> (ADR-0252 §3). **Nothing a `StepCondition` declares is ever copied into a row**: no lane
> composes a row's `requested`, `supported`, `basis`, `declaration`, `verdict` or `read_kind` from
> a condition. What a condition declares is a **requirement**; what a row carries is what a
> response **established**; the whole of ADR-0252 §6 is the comparison between them.

> **Normative — an element's `applicability` reaches a row on exactly one basis, and it is
> ADR-0252 §3's own second source.** On the **`READ_OUTCOME`** basis a row's `supported` is
> composed from the **records the ask returned** and from nothing else, and **no lane composes one
> from an element's `applicability`** — ADR-0252 §3's first source and its prohibition list bind
> entire. On the **`INTERPRETATION`** basis ADR-0252 §3's **second** source is *"the one region the
> interpretation step declared, over the one record its whole input was"*, and the region this
> decision declares is the `applicability` of the element the interpretation settles (§8). The two
> bases compose from two sources, which is what `basis` exists to say, and neither rule reaches
> the other's rows.

> **Normative — ADR-0252 §14 is partially superseded in one term, and only on that basis.** Its
> writer clause enumerates *"an identifier, an instant, an applicability, a standing, a basis, a
> read kind, a source, a declaration, a count or a verdict of a read"* as things **no model
> supplies**. On the `INTERPRETATION` basis the **applicability** term stops being true, because
> ADR-0252 §3's second source requires the **step** to have declared the region and only a plan
> can declare one — the two clauses of that decision are in tension and the specific rule governs.
> **Every other term of §14 binds entire**, on both bases: no model supplies an identifier, an
> instant, a standing, a basis, a read kind, a source, a declaration, a count or a verdict of a
> read, and §14's *"exactly one thing"* — one member of the closed enumeration over one recorded
> record — is still the whole of what a model supplies **at the interpretation call itself** (§8).
> What a plan declares is declared a call earlier, is recorded by `orchestration` into a durable
> interpretation under ADR-0249 §7's discipline, and is a **requirement of the goal** before it is
> ever the region of a row.

### 8. An interpretation is not a step: one recorded record in, one member of a closed enumeration out

> **Normative.** `ActionPlan` gains **`interpretations`**, a possibly-empty
> `tuple[PlanInterpretation, ...]` defaulting to empty. `core/types.py` gains
> **`PlanInterpretation`**, a frozen model with `extra="forbid"` carrying exactly `id` (an
> `Identifier`), `settles` (an `Identifier` — on the value the store holds, the `id` of a
> **condition element** of the `GoalInterpretation` the plan's `targets_revision` names; on the
> value a planner returns, the **condition label** §9 fixes) and `record` (an `Identifier` — one
> record of the labelled supply of the call that produced this plan). **`ActionPlan` refuses two
> interpretations sharing an `id` and two sharing a `settles`**, exactly as it already refuses two
> steps sharing an id.

> **Normative — an interpretation is not a `PlanStep`, and ADR-0226 §4's reasoning is adopted
> whole rather than re-derived.** That section rules of a `ReadAsk`: *"A `ReadAsk` is not a
> `PlanStep` and nothing drives it. It is not selected against the capability vocabulary, not
> resolved to a tool, not ruled on by the permission gate, and never reaches `StepExecutor` or
> `ExecutionState`: reading the owner's own store is not an act in the world, so no lane routes
> it through the machinery that decides acts."* **A model reading one record the user already
> holds and returning a member of a closed enumeration is not an act in the world either.** So an
> interpretation is **not selected against the capability vocabulary, not resolved to a tool, not
> ruled on by `ActionPolicy`, not bound by `EgressBinder`, and never reaches `StepExecutor`,
> `ExecutionState` or `StepExecution`.** `PlanStep.capability` stays **required**, `StepStatus`
> gains no member, `SkipReason` gains no member, and ADR-0014 §3's *"one per PlanStep, same
> order"* is untouched.

**Putting it on `steps` would have collided with ADR-0014 §4 in a way no validator could
repair.** *"Every transition into `RUNNING` carries an `approval_ref`"*, and `PlanExecution`
*"rejects a `→ RUNNING` transition without one"* — so an interpretation routed through
`ExecutionState` would need a permission decision for a call the permission layer has no business
ruling on, and the only ways out are a manufactured `approval_ref` for a decision nobody made,
which ADR-0037's unconditional check exists to prevent, or a second entry into `RUNNING` that
ADR-0014 §4's graph does not admit. It would also have obliged `capability` to become optional on
every step in the system, to accommodate the one kind of step that names none.

> **Normative — every interpretation of a plan is over a record the turn already holds, so none
> of them waits on anything.** `record` names a record of the `memories` sequence passed on the
> call that produced the plan; that sequence is what the investigation phase assembled before
> planning. **An interpretation therefore carries no `depends_on`, no `when` and no `verifies`,
> and every interpretation of a plan is performed before the plan's first step is dispatched.**

> **Normative — the record is named by a label and the identifier is authored at the planning
> seam.** The envelope carries a label of the `memories` sequence rendered on that call, in
> ADR-0226 §3's own scheme (`M` followed by the record's 1-based index). The implementation that
> rendered those labels resolves it against **the very sequence it was passed on this call** and
> the `PlanInterpretation` carries the resolved identifier. A label outside the shown range, and a
> label naming a record ADR-0231 §1's search or ADR-0230 §5's fetch **minted** — each of which
> ADR-0252 §1 forbids a row's `records` from naming, because such a record *"resolves in no
> store"* — is an **extraction failure** for that envelope, on §1's footing and for §1's reason.
> **No record identifier is rendered to a model and none is accepted from one** (ADR-0228 §8): the
> identifier is resolved by the component that rendered the label, exactly as ADR-0249 §7 has
> `orchestration` stamp a `FROM_EVIDENCE` element's `evidence_id` from the label the planner
> wrote.

> **Normative — `orchestration` checks and never rewrites.** The loop verifies that each
> interpretation's `record` is the `id` of a record of the `memories` sequence **it** passed on
> that call, and that each `settles` names a condition element, carrying an `id`, of the revision
> the plan targets. **A plan failing either check is not driven**: nothing performs its
> interpretations, nothing dispatches a step of it and nothing claims a step of it. It is still
> **persisted**, because ADR-0014 §2 makes a plan *"an auditable record of a decision"* and a
> refused plan is a decision that was taken. This is ADR-0249 §8's not-driven rule in its own
> shape, and **no lane satisfies it by editing the plan**: ADR-0228 §1's authored-at-the-seam
> clause, as ADR-0249 §8 restates it, admits exactly `supersedes` and `targets_revision` as fields
> another component sets, and `steps` is named among the fields no implementation authors or edits
> anywhere but at the `Planner.plan` seam.

> **Normative — an interpretation whose element carries no `applicability` is not performed**, it
> records no row, and every `StepCondition` naming that element on the `INTERPRETATION` basis is
> therefore unsatisfied and its step is disposed of by §2's rule. ADR-0252 §3 composes such a row's
> `supported` from *"the one region the interpretation step declared"*, and the region this
> decision declares is **the `applicability` of the element it settles** (§7); an element carrying
> none declares no region, an empty `supported` supports nothing (ADR-0252 §3), and a row that
> could satisfy nothing is better not written than written to sit in the digest asserting a
> verdict about no applicability at all.

> **Normative — the verdict vocabulary.** `core/types.py` gains **`InterpretationVerdict`**, a
> `StrEnum` valued by lower-cased member name and **closed at exactly three members**:
> **`QUALIFIES`**, **`DOES_NOT_QUALIFY`** and **`INCONCLUSIVE`**. The vocabulary is **added to and
> never renamed**. **`INCONCLUSIVE` is the does-not-settle member** ADR-0252 §5 requires such an
> enumeration always to carry, and **a row carrying it satisfies nothing, refreshes nothing and
> conflicts with nothing** — ADR-0252 §5's and §7's clauses, which bind here and are not restated
> as rules of this decision.

> **Normative — the three values are disjoint from `ReadOutcomeKind`'s seven**, which is the
> constraint ADR-0252 §5 puts on *"the later vocabulary, which is the one not yet minted"*:
> `qualifies`, `does_not_qualify` and `inconclusive` collide with none of `returned_records`,
> `empty`, `duplicate`, `truncated`, `refused`, `failed` and `expired`, so a digest's `verdict`
> identifies which vocabulary it is drawn from without the digest carrying a `basis`.

> **Normative — one enumeration over many propositions, and the `declaration` is what tells them
> apart.** There is **no per-declaration vocabulary**: every interpretation row's `verdict` is a
> member of `InterpretationVerdict`, and what separates two readings of two propositions is
> ADR-0252 §7's comparison of `declaration`s, which that section states in terms — *"Two
> interpretation steps of one attempt may examine the same record, under the same enumeration,
> about two different propositions; their verdicts are then two answers to two questions and are
> **not** a disagreement."*

**A vocabulary a model authored could not be compared, retained or audited.** Members invented per
plan would be unprovenanced strings in a durable row — the ground ADR-0226 §9 refused even to
**log** `ActionPlan.id` on — and two plans about one proposition would almost never agree on a
spelling, so ADR-0252 §8's refresh could never hold and correction 1's *"retained historical
disagreements do not permanently block progress"* would be unreachable.

> **Normative — the `declaration` a row carries is the element's `id`, and this is the form
> ADR-0252 §1 left to this lane.** That section requires it to be *"durable"*, *"stable across
> turns"*, to *"resolve within the plan store"*, to be *"never a `MemoryStore` identifier and
> never a minted one"*, and rules that *"a plan id alone does not suffice, because one plan may
> declare two interpretation steps"*. A `GoalElement.id` satisfies every one: it is minted by
> `orchestration` into the goal's interpretation, it resolves through the plan store's goal, it
> survives every revision that retains the element, and two interpretations of one plan settling
> two conditions carry two.

**A step id would satisfy the first requirement and fail the second, and ADR-0252 §8 says why in
its own words.** A re-plan mints new step ids, so a fresh reading of the same proposition in a
later plan would carry a different declaration and limb 3 of the refresh test — *"`L.declaration`
**equals** `E.declaration`"* — could never hold. That section has already rejected the nearby
proxy for the same reason: *"Requiring `L` and `E` to interpret the **same** member of `records`
would mean that reading again never retires anything, because a re-reading necessarily interprets
a **new** record — and a three-day-old disagreement would block the goal forever, which is exactly
what correction 1 forbids."* The element's identity is the one value in this system that is about
the **proposition** rather than about the plan, the record or the turn.

> **Normative — the call, its input and its declared output schema.** An interpretation is
> performed by **one model call whose whole input is the one record `record` names and the text of
> the element `settles` names**, and whose **declared output schema is exactly one member of
> `InterpretationVerdict` and nothing else**. It is handed **no** utterance, no conversation, no
> other memory, no context facet, no plan, no capability vocabulary, no goal brief beyond that one
> element's text, and no evidence digest. It returns **no prose, no rationale, no confidence, no
> citation, no identifier and no second value**, and a reply carrying one has it discarded
> silently — ADR-0249 §6's posture and ADR-0228 §5's before it. **It is not a `Planner.plan` call**
> and no `Planner` implementation makes it.

**This is #2096 item 7's quarantined extractor bought for exactly the property that item names:**
*"A model whose entire input is one recorded span and whose output is typed fields produces values
whose origin is known **by construction** — they came from that span and carry its source's writer
set."* Every widening of that input gives the value a second possible origin, which is why the
enumeration is small, the input is one record, and the schema admits nothing beside the member.

> **Normative — what a model supplies here is the one thing ADR-0252 §14 admits.** That clause
> reads: *"**What a model supplies toward evidence is exactly one thing**: on an `INTERPRETATION`
> row, one member of the closed enumeration its declaration names, over one recorded record."*
> Every other field of the row — its `id`, its `goal_id`, its `attempt_id`, its `basis`, its
> `declaration`, its `supported`, its `read_at`, its `as_of`, its `records`, its counts and its
> `standing` — is `orchestration`'s, composed under ADR-0252 §§1, 3 and 4, and **no clause of this
> decision takes any of them from a model.**

> **Normative — `MAX_INTERPRETATION_STEPS`, a fixed constant valued 4**, bounds how many
> interpretations one `ActionPlan` may declare, and a plan declaring more is **refused at
> construction** rather than truncated. It is **not** a `Settings` field, a constructor knob or a
> per-deployment value, on ADR-0086 §1's rule as ADR-0213 §4 states it — *"a knob that raises the
> ceiling is a knob that re-opens it"*. **Refused rather than truncated**, because dropping an
> interpretation would silently delete a branch of a plan the rest of which is stated over it,
> which is §1's argument for refusing a malformed dependency.

**Four, and where the figure comes from.** An interpretation is an ungated model call that no
permission stage rules on, so a plan declaring them without bound would be a per-turn cost nobody
reviewed — ADR-0228 §3's ground for refusing a configurable planner-call bound, *"a plan count is
a count of model calls, so a configurable one is a configurable per-turn cost with no ceiling
anyone reviewed"*, reached one level over. Four is ADR-0251 §5's planner-call allowance, taken
because it is the one figure this corpus has judged for model calls within one attempt, and it is
**a first declaration and is labelled as one**: the bound exists to stop a plan multiplying
ungated calls, not to express a judgement about how many propositions a plan should settle.

> **Normative — `ActionPlan.steps` is **not** bounded by this decision**, and that is stated
> rather than left to inference. It is unbounded at `f0b8132d` and stays so: a step is bound to a
> capability, selected, ruled on by the permission gate and claimed one at a time, so a long plan
> is expensive in a way the corpus already gates, where an interpretation is not. **Whether a plan
> needs a step bound of its own is a separate question with its own consumer**, and it is filed
> rather than decided here (§11).

> **Normative — ADR-0251's allowance does not gate an interpretation, and its working time
> accumulates.** An interpretation call is **not a planner call**, so it is outside ADR-0251 §5's
> planner-call allowance and outside ADR-0228 §3's bound; and it is performed in phase 5 rather
> than in an investigation round, so ADR-0251 §4(h)'s investigation gate and §6's investigation
> share do not reach it. ADR-0251 §6's clause is the one it falls under, unchanged: *"**Composing
> and verification are not gated on the attempt's allowance at all**: the working time they
> consume accumulates into `AttemptEffort.working` like every other working interval."* **What
> bounds the number of interpretation calls a turn makes is the plan**, which declares at most
> `MAX_INTERPRETATION_STEPS` of them and is itself produced by a bounded number of planner calls.

### 9. Permitted branches, and the planner's side of every field

> **Normative.** **Which branch a later step is on is a function of the conditions the plan
> declared and the verdicts that were observed, and no model decides at execution time whether to
> proceed.** Two steps declaring conditions that name the **same** element on the `INTERPRETATION`
> basis and require **different** members of `InterpretationVerdict` are two branches.

> **Normative — eligibility is ADR-0252 §6 evaluated over the goal's rows, and never over one
> row.** A branch is eligible where **some** row of that goal satisfies its condition's four
> tests; it is not eligible where none does. **A single interpretation returning `INCONCLUSIVE`
> enables no branch by itself** — a condition may never require the does-not-settle member
> (ADR-0252 §6 test 2) and a row carrying it satisfies nothing (ADR-0252 §5) — and **it disables
> nothing either**: where the goal already holds a `STANDING` settling row that passes all four
> tests for one branch, that branch **stays eligible**, because ADR-0252 §7 rules that a
> does-not-settle row *"neither satisfies, nor refreshes, nor blocks"* and ADR-0252 §8 limb 5
> refuses it a supersession. **No lane of this decision reads a new verdict as retiring an old
> one**; which rows stand, which are superseded and which are inapplicable is ADR-0252 §§8–9's
> alone.

> **Normative — at most one of two opposite branches is eligible only where the goal's standing
> rows for that declaration agree.** Two `STANDING` settling rows carrying **different** members
> over overlapping applicabilities are a **conflict** under ADR-0252 §7, and that section is what
> governs: the condition is not satisfied, the disagreement is reported, and **no rule of this
> decision picks a winner** — not recency, not source, not a count. So a plan's two branches are
> mutually exclusive by construction only where one member is evidenced and the other is not, and
> where both are, **neither branch dispatches** and the obstacle is what the turn reports.

**Branching falls out of positive membership and needs no negation at all, which is why §5 could
refuse one.** A closed enumeration, one verdict per row, and a conjunction of positive
requirements give mutually exclusive branches for free, with the third member as the case in which
the plan does nothing rather than guessing. That is the acceptance row *"Conditional plan spans
multiple decisions"* satisfied in the shape #2255 asks for: **a later verdict enables only the
permitted branch without discarding the plan**, so the plan stays the auditable record ADR-0014 §2
makes it and the branch not taken is visible in it as a step that was skipped.

> **Normative.** **An unexpected finding returns the work to an earlier phase rather than
> improvising in this one.** A plan may declare that it does so — by declaring branches, of which
> one may be a branch that acts and one a branch that does not — and **the mechanism by which an
> attempt re-enters an earlier phase is A7's** (ADR-0249 §6 fixes the phase order and its writer
> clause). What this decision fixes is that a plan **may express** the alternative, so that the
> answer to an unexpected verdict is a branch the plan already declared rather than a model asked
> at dispatch what to do next.

> **Normative — the planner's envelope, per field.** The plan envelope's step object gains
> **five** optional keys and the envelope gains one: `after` (§1), `resolves` (§6), `when` (§5),
> `verifies` (§4) and `evidence_recency` (§5) on the step, and `interpretations` (§8) beside
> `steps`. **`evidence_recency` crosses as an ISO-8601 duration string**, and a value that is not
> one, or that is not strictly positive, is an extraction failure for that envelope rather than a
> figure rounded, clamped or defaulted into range.

> **Normative — every value a model writes in any of them is an ordinal or a label of something
> rendered or returned on that call**: a step's position in the envelope's own list (§1), an `M`
> label of the supply (§8), and a **condition label** for a `when` condition's `about` and an
> interpretation's `settles`. **No identifier of any kind is rendered to the model and none is
> accepted from it** (ADR-0228 §8). A step's ordinal and an `M` label are resolved by the
> implementation that rendered them, against the very sequence it was passed on that call; the
> condition label is resolved by the loop, below.

> **Normative — the condition label, and the one space in force per call.** A condition label is
> the ASCII string **`D`** followed by a 1-based ordinal in decimal with no padding, ADR-0249 §9's
> scheme unchanged. **Which sequence it indexes is decided by the envelope and by nothing else:**
> where the envelope carries an `understanding`, it indexes that understanding's `conditions`
> tuple; where it does not, it indexes the `GoalBrief.conditions` the call received. **Exactly one
> of the two is in force per call**, and it is always the sequence that describes the revision the
> plan will target.

**One label space per call falls out of ADR-0249 §7's completeness rule rather than being imposed
on top of it.** That section makes a revision *"a complete statement of an understanding"*: an
element the `ProposedUnderstanding` neither retains nor replaces *"is **not** in the new
revision"*. So where an understanding is returned, **every** condition of the revision the plan
will target is at some position of that understanding's `conditions` — retained ones by their
`retains` label, new ones stated in full — and the brief's own tuple describes the revision the
plan is about to stop targeting. Where no understanding is returned, ADR-0249 §8's stamp is the
current revision and the brief describes it exactly. The two cases never overlap, so one letter
carries both and neither needs a second.

> **Normative — the loop resolves the label, once, and the planner never does.** On every plan a
> planner returns, the loop takes each `StepCondition.about` and each `PlanInterpretation.settles`
> for its own: it reads the label the field came back carrying and replaces it with the
> `GoalElement.id` that label resolves to. It does this **once** per plan, immediately on return,
> **after** this same call's `understanding` — if any — has been recorded and its element ids
> minted, and **after** ADR-0249 §8's `targets_revision` stamp, and before any other component
> observes the plan. Resolution is against the sequence the clause above names, **by the
> correspondence the loop itself holds** between each proposed element and the element it
> recorded — so a proposed element ADR-0249 §7 **dropped** resolves to nothing rather than to its
> neighbour.

**Ordering the resolution after the recording is what makes a first turn's plan expressible, and
it is ADR-0249 §8's own argument for ordering its stamp that way.** A goal at revision 1 carries
*"no elements"* (ADR-0249 §9), and a planner decides the understanding and the plan *"in one
pass"* (ADR-0249 §7) — so on the turn a condition first exists, it exists only in the
`ProposedUnderstanding` that same call returned, and its `GoalElement.id` is minted by
`orchestration` a moment later. A loop that resolved before recording could never let a plan
condition on a condition that call proposed, which is the ordinary shape of *"book only if the
forecast qualifies"* rather than an exotic one. ADR-0249 §8 reaches the same ordering for the same
reason: stamping the **input** revision *"would leave every turn on which the planner revised its
understanding holding a plan §8 forbids driving"*.

> **Normative — a label that resolves to nothing is refused, and the plan is neither saved nor
> driven.** An ordinal outside the range, a value that is not such a label, an ordinal naming a
> proposed element the loop dropped, and a label naming an element carrying no `id` (§7) each
> resolve to nothing. The loop **refuses the plan**: it is not passed to `PlanStore.save_plan`, no
> step of it is dispatched and no interpretation of it is performed, and the turn proceeds as one
> whose planner produced no usable plan. **No lane drops the condition instead**, because a step
> whose condition was dropped is a step with fewer requirements than the plan declared — the
> fail-open direction, and the one §1 refuses for a dropped dependency for the same reason.

> **Normative — the window is closed at the store as well as at the loop.**
> `PlanStore.save_plan` **refuses a plan any of whose `StepCondition.about` or
> `PlanInterpretation.settles` values is not the `id` of a condition element of the interpretation
> that plan's `targets_revision` names**, with the same error class ADR-0249 §8 gives an unstamped
> `targets_revision` and ADR-0228 §5 gives an unresolvable `supersedes`, and for the same reason:
> the unresolved state exists only between the planner's return and the loop's substitution, and a
> window is closed at the store rather than trusted to close itself. This is a **strengthening of
> an existing member** rather than a new one, exactly as ADR-0249 §12 classifies
> `commit_transition`'s added claim condition.

> **Normative — ADR-0249 §8's two-field clause becomes a four-field clause, and nothing else about
> it moves.** That section rules that ADR-0228 §1's *"The **one** field any other component ever
> sets is `supersedes`"* and §5's *"Every other field is **exactly as the planner returned it**"*
> become a two-field clause, `supersedes` and `targets_revision`. The fields any other component
> sets are now those two **and**, inside `steps` and `interpretations`, each `StepCondition.about`
> and each `PlanInterpretation.settles` — every one under §5's identical discipline: taken by the
> loop, taken once, at the same moment, in place of whatever came back. **Every remaining field of
> every plan, of every step and of every interpretation is still exactly as the planner returned
> it**, and §1's authored-at-the-seam clause is narrowed in exactly that scope and in no other: no
> implementation authors or edits a plan's `id`, `goal_id`, `rationale` or `read_request`, or a
> step's `id`, `intent`, `capability`, `parameters`, `depends_on`, `resolves`, `verifies`,
> `evidence_recency` or a condition's `basis`, `requires` or `read_kind`, anywhere but at the
> `Planner.plan` seam.

**The substitution is a resolution and not an authorship, which is the distinction ADR-0228 §5
already draws for `supersedes`.** The loop is not choosing which element a condition is about — the
planner chose, by naming a position in a sequence the loop rendered or the planner returned. What
the loop supplies is the **name** of the thing chosen, which is a value only it holds because only
it mints element ids. That is ADR-0249 §7's ground resolution in its own shape: *"an element's
ground crosses as a **label**, never as a record identifier, and the loop never parses an
identifier out of a planner's output."* Here too the loop parses no identifier — it reads an
ordinal and indexes a sequence it holds.

> **Normative — every member of every vocabulary is spelled in the prompt and extracted
> strictly.** The `basis`, the `requires` member, the `verifies` kind and the `read_kind` are each
> a member of a closed enumeration the prompt states; a value outside it is an **extraction
> failure** for that envelope and is never coerced, case-folded, aliased or repaired into a
> member. This is ADR-0176 §1's strictness applied to five more vocabularies — that section's
> marker *"is the JSON boolean `true` and nothing else"*, refusing `1`, `"true"` and `"yes"` — and
> the implementing lane ships the same parameterized test over each.

> **Normative — what `orchestration` refuses, gathered in one place.** A plan is **refused before
> it is saved** — neither persisted, nor driven, nor interpreted — where a condition label
> resolves to nothing (above), or where an interpretation's `record` is not the id of a record the
> loop passed on that call. A plan **already saved** is **not driven** where ADR-0249 §8's
> existing rule refuses it, because `targets_revision` is not the goal's current revision. A plan
> is **not constructible** where §1's, §4's, §5's, §6's or §8's shape rules are breached. The
> first set is checked by the loop because it needs the goal and the call's own supply; the second
> is a validator on the type, because everything it compares is inside the value.

**Refused before the save rather than persisted and then ignored, and the two cases are kept apart
deliberately.** A plan whose `targets_revision` went stale was a readable decision when it was
written and became undriveable afterwards, so ADR-0249 §8 keeps it and refuses the claim. A plan
carrying a label nothing resolves is a decision **nobody can read at all** — its conditions name
elements that do not exist — and persisting one would put a value in the audit trail no later
reader could interpret. ADR-0249 §8's `save_plan` refusal of an unstamped `targets_revision` is
the precedent for closing that kind of window at the store.

### 10. The `core` surface, the wire, the stored shapes, the export, and the writer clauses

> **Normative — what `core/types.py` gains.** Five models and two enumerations —
> `ResultReference`, `StepVerification`, `StepCondition`, `PlanInterpretation`, and the widenings
> of `PlanStep`, `ActionPlan`, `GoalElement` and `ProposedElement`; `VerificationKind` and
> `InterpretationVerdict`; and one constant, `MAX_INTERPRETATION_STEPS`. **`PlanStep` gains
> `depends_on`, `resolves`, `when`, `verifies` and `evidence_recency`; `ActionPlan` gains
> `interpretations`.** Every new field is **defaulted**, so every existing constructor call still
> builds a conforming value.

> **Normative — this is a BREAKING contract change under golden rule 5**, and it is breaking for
> the Protocol and not for the constructor. `Planner.plan`'s **signature does not move**: it takes
> the same parameters and returns the same `PlannerOutput`. What changes is what a conforming
> implementation must **produce and refuse** — a planner that emitted a reference to a step
> outside its plan, a condition with no basis, or a fifth interpretation would have built values
> this decision makes unconstructible — and what a conforming `PlanStore` must round-trip **and
> refuse**: §9 adds one conjunct to `save_plan`, which is a **strengthening of an existing member**
> rather than a new one, exactly as ADR-0249 §12 classifies `commit_transition`'s added claim
> condition. `PlanStore` gains **no member**. **The
> existing `Planner` and `PlanStore` conformance suites and the canonical fakes in
> `ai_assistant.testing` gain the new obligations in the same change that adds them**
> (`CONTRIBUTING.md` → "Adding a Protocol": *"The triad is what a Protocol *change* is measured
> against too"*). **No new Protocol is created**, so no new conformance suite and no new canonical
> fake is owed.

> **Normative — `PROTOCOL_VERSION` moves by exactly one, in the same change that makes a
> wire-carried value one peer emits invalid for the other**, and `wire/envelope.py`'s log gains an
> entry naming this ADR and the reason. That is ADR-0124 §9's second limb quoted rather than
> restated — *"a change to a wire-carried `core` type that makes a value one peer emits invalid
> for the other, whether the change widens or narrows the type"*. `PlanStep` gains five fields and
> `ActionPlan` gains one; `ActionPlan` rides `TurnResult.plan`, `TurnResult` rides
> `TurnOutcome.turn`, `TurnOutcome` is what the promoted surface returns, all three models set
> `extra="forbid"`, and `wire/codec.py` renders a model by `model_dump()` — so a hub's turn
> becomes undecodable by a client at the previous version. **§12 cuts the lanes so that exactly
> one satisfies it**, which is what makes the bump singular rather than a property of the cut.
> **The figure is the tree's and not this decision's**: a lane reads `PROTOCOL_VERSION` where it
> lives in `wire/envelope.py` and adds one. As a dated observation rather than a rule, it reads
> **38** at `f0b8132d`.

> **Normative — `GoalElement` gaining two fields is not a second wire ground.** `TurnResult.goal`
> is a `GoalBrief` after ADR-0249 §11, `BriefElement` carries *"exactly `text` and `ground`"*, and
> **this decision adds nothing to either**. A `GoalInterpretation` crosses no frame; it is carried
> in the plan store and in `PlanExport`, and neither is a wire surface (ADR-0249 §12).

> **Normative — `GoalBrief` and `BriefElement` gain nothing, and the containment is kept as
> ADR-0249 §9 argues it.** The brief carries an element's text and the **kind** of its ground and
> nothing else; it does **not** carry an element's `id`, its `applicability`, or any reference. The
> planner names an element by its **`D` label** (ADR-0249 §9), which is what makes the resolvable
> set exactly what the loop chose to render. **Whether a brief ever renders an element's
> applicability is not decided here**, is fired by a planner that demonstrably needs it, and is
> named in §11.

> **Normative — `PlanExport.schema_version` moves by exactly one**, on ADR-0039 §10's own
> mechanism as ADR-0249 §12 applies it: *"`StepExecution` is inside the export, so its shape
> changing is exactly what the version exists to announce."* The document carries
> `tuple[ActionPlan, ...]` and `tuple[Goal, ...]`; `PlanStep` and `ActionPlan` change shape and
> `GoalElement` changes shape inside a `Goal`, and each is an independent ground. It is a
> **stored-record version and not a second wire ground** — `PlanExport` crosses no frame and is
> emitted by no peer — and the log records that separation as it already does. As a dated
> observation, it reads `Literal[8]` at `f0b8132d`.

> **Normative — the plan store's `schema_version` does not move, and no migration is owed.**
> Every new field is defaulted, so a stored plan written before this decision decodes with
> `depends_on` empty, `resolves` empty, `when` empty, `verifies` absent, `evidence_recency`
> absent and `interpretations` empty — which is exactly the plan it was: no dependency, no
> reference, no condition, no verification and no interpretation. **Such a plan's steps are
> eligible and it drives exactly as it drives today.** A stored `GoalElement` written before this
> decision decodes with `id` and `applicability` absent, and §7's clause is what makes that a
> conforming value rather than a row to repair. ADR-0049 §1's loud refusal is stated of a database
> *"whose `schema_version` is **newer** than the code understands"*, and no store here is.

> **Normative — no compatibility shim, negotiation or lenient decode.** ADR-0084 §3's exact-match
> handshake is the mechanism and the refusal naming both versions is the intended user-visible
> outcome.

> **Normative — nothing else under `wire/` changes.** The connect exchange gains no member, no
> existing frame's encoding changes, no `FrameKind` is added, no codec entry is registered, the
> error mapping is untouched, the promoted method set does not move, and no gateway route is
> added. **No `Settings` field is added**, no deployment flag is read, and **no figure of this
> decision is configurable**: `MAX_INTERPRETATION_STEPS` is a `core` constant, and the recency
> requirement is a value the **plan** declares rather than a value a deployment supplies
> (ADR-0252 §6).

> **Normative — retention, deletion and elision are untouched, and no new durable record is
> minted.** Every value this decision adds rides an `ActionPlan` or a `GoalInterpretation` that
> the plan store already holds, so ADR-0014 §5's deletion obligation and its live-step refusal,
> ADR-0249 §12's `delete_goal` cascade, ADR-0249 §2's interpretation elision and its
> `interpretation_elided` disclosure, and ADR-0252 §13's evidence retention all bind exactly as
> they stand. **No lane adds a retention rule, a sweep, an expiry or a second store.**

> **Normative — a `declaration` whose element is gone resolves to nothing and satisfies
> nothing.** An element a later revision neither retains nor replaces is not in that revision
> (ADR-0249 §7), and a revision ADR-0249 §2 elided is gone with the rest of its elements. A
> `GoalEvidence` row whose `declaration` named one **keeps it** — ADR-0252 §9's rule that
> invalidation is *"a marking and never a deletion"* binds, and nothing rewrites a row's
> `declaration` — and no `StepCondition` can name it, because §5 requires `about` to name an
> element of the revision the plan targets. So such a row is retained, exported and rendered in
> the digest, and satisfies no condition. **No lane repairs, re-points or deletes one.**

> **Normative — no new class of content crosses any seam.** A `StepCondition` carries a member of
> a closed vocabulary and two identifiers; a `ResultReference` carries two names and an
> identifier; a `PlanInterpretation` carries three identifiers; an element's `applicability`
> carries instants and the label vocabularies ADR-0237 and ADR-0213 already fix, which are the
> same values ADR-0252 §11 rules already cross to the planner on a digest. **ADR-0004 §5's rule
> that "Tier 0/1 data must never be logged" binds unchanged and nothing here logs a plan, a
> condition, an element or a verdict**, and `_render_request` prints no identifier (ADR-0249 §9).

> **Normative — the writer clauses.** `orchestration` mints a `GoalElement.id`, records an
> element's `applicability`, and substitutes each condition label for the element id it resolves
> to (§9); the planner's implementation mints step and interpretation ids and resolves step
> ordinals and `M` labels to them; **no model writes an id, a resolved value, a `standing`, a
> `GoalStatus`, a `SkipReason`, a `StepStatus` or an evidence row's field**, and a planner envelope
> coming back carrying one has it **discarded silently** — ADR-0249 §6's posture and ADR-0228 §5's
> before it. The fields another component sets on a plan are **exactly four**: `supersedes`,
> `targets_revision`, and each `StepCondition.about` and `PlanInterpretation.settles` (§9). **Every
> other field of every plan, step and interpretation is authored at the `Planner.plan` seam and
> nowhere else**, and no lane of this decision edits any of them.

### 11. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling, and
> each carries the condition that fires it.

- **The plan-driving stage** — walking a plan in dependency order, performing its interpretations,
  evaluating §2's rule and §5's conditions, resolving §6's references, and at which moment a
  never-eligible step is moved to `SKIPPED`. **A7.** Fired by this ADR landing; §3's rule is what
  makes the interval safe.
- **Authorization coverage** — fixed values, permitted ranges, the basis triple, coverage from
  several acts, and whether a dependency's own origin is a further input to a ruling (§6).
  **A6.** A dispatch needs both tests and nothing here clears an authorization or is cleared by
  one (ADR-0252 §15).
- **Retry, reconciliation, `EFFECT_UNRESOLVED`, idempotency keys and modify-before-replace** —
  including how an `INDETERMINATE` producer §2 stops a branch on is resolved. **A8**, which takes
  ADR-0014 §7's idempotency and `INDETERMINATE`-resolution deferral.
- **Cancellation at the claim boundary**, and which write wins against a dispatch this decision's
  conditions made eligible. **A9.**
- **Verification against the goal's criteria, strength proportional to consequence, which
  `AttemptOutcome` member an attempt earns, and the producer of `GoalStatus.ACHIEVED`.** **A10.**
  §4 fixes that `verifies` is not it.
- **Parallel execution of two steps**, and the leases, in-process synchronisation and recovery it
  would need. ADR-0014 §7's second half, **untouched** (§1). Fired by a decision that takes it.
- **A bound on `ActionPlan.steps`.** Filed as a follow-up rather than decided (§8): it is a
  pre-existing property of the type, no consumer of this decision needs it, and a bound minted
  without one would be a figure nobody measured.
- **Whether `GoalBrief` renders an element's `applicability`**, and whether a planner needs to see
  it to write a condition. **Not decided** (§10); fired by a measured planner failure that naming
  by label alone cannot explain.
- **Whether a condition may require a `source`.** **Not decided**; §5 refuses it today because no
  producer fills the field, and it is fired by the lane that lands one — decision 8's reader
  (ADR-0252 §15).
- **Whether an interpretation may ever take more than one record, or a record this system did not
  store.** **Refused here and not deferred**: ADR-0252 §1 admits *"**exactly one** member of
  `records`"* and forbids a minted one, and widening either is that decision's to reopen.

### 12. The lane cut, and the one lane that moves the wire

> **Normative.** This decision is implemented in **two lanes**, and **neither drives**.

- **L1 — the contract.** `core/types.py`'s four new models, two enumerations and one constant;
  `PlanStep`'s five fields and `ActionPlan`'s one; `GoalElement`'s two and `ProposedElement`'s
  four axes; every validator §§1, 4, 5, 6, 7 and 8 states; the `Planner` and `PlanStore`
  conformance suites and the canonical fakes in `ai_assistant.testing`; `wire/envelope.py`'s log
  entry and **the single `PROTOCOL_VERSION` bump**; and `PlanExport.schema_version`. **This is the
  lane that moves the wire**, and it moves it once.
- **L2 — the planning seam.** The prompt blocks for the five new keys and `interpretations`, the
  strict extraction and its refusals, the step-ordinal and `M`-label resolution in the planner
  implementation, **the loop's substitution of each condition label for an element id (§9)**, and
  `orchestration`'s structural checks and refusals. `_render_request` already renders the brief's
  `D` labels (ADR-0249 §9) and gains nothing. **It changes no behaviour of a plan that declares
  none of the new keys**, because a plan with no condition and no interpretation has no label to
  substitute.

> **Normative — L1 lands after ADR-0252's contract lane.** `StepCondition` names an
> `EvidenceBasis` and a `ReadKind`, and `GoalElement.applicability` is an
> `EvidenceApplicability`; two of the three are ADR-0252's to mint and are **not in the tree at
> `f0b8132d`**. A lane that minted a placeholder for either would be the *"two carriers for one
> fact"* defect ADR-0251 §3 names, so the ordering is a dependency rather than a preference.

> **Normative — no lane of this decision performs an interpretation call, evaluates a condition,
> resolves a reference, computes `GoalRevision.invalidates`, dispatches a step or writes a
> `SkipReason`.** Each has its lane named in §11, and §3's rule is what makes the interval between
> them safe.

### 13. Records owed on earlier ADRs, under ADR-0082 §1

**ADR-0249 — partially superseded in two scopes, and the header records both.** The scopes are
stated on this document's own `Status` line and the reasoning is §7's. A reader holding only
ADR-0249 builds a `GoalElement` with four fields and a `ProposedElement` whose new-element shape
carries no applicability, and therefore builds a goal no `StepCondition` can name and no
invalidation predicate has operands over — ADR-0070 §1's test coming out on the supersession side,
and **partial** in ADR-0070 §3's sense. **ADR-0249 §13's A5 entry is discharged**, which is a
record and not a supersession: that section names what this ADR settles, and settling it is the
entry being spent rather than replaced.

**ADR-0014 — §7's two deferrals are fired, and that is a record and not a supersession.** *"Output
references between steps"* and the dependency half of *"Step dependencies / parallel execution"*
are each taken by §§1, 2 and 6. A deferral states that a decision was **not** taken, so firing one
replaces nothing and `Accepted` is not dropped (ADR-0070 §1, ADR-0082 §1). Two things about that
bullet are recorded with it, because a reader would otherwise act differently. **First, its
parenthetical default is declined**: §7 sketches *"an optional field defaulting to the implicit
'after the previous step'"* and §1 rules an empty `depends_on` means the step waits on nothing, for
the reason §1 gives. **Second, only half the bullet is fired**: parallel execution is untouched and
no lane reads `depends_on` as a licence for it. Everything else of ADR-0014 binds entire and is
relied on — §2's frozen plan and its `JsonValue` reasoning, §3's `output` and its resumability
argument, §4's transition graph, its retry ceiling and its `INDETERMINATE` treatment, and §5's
compare-and-swap discipline — and `SkipReason` gains no member, so §4's `PENDING → SKIPPED` row and
ADR-0041's addition to it stand as ratified.

**ADR-0249 §8 — partially superseded in the field count alone, and the argument is §8's own.**
That section made ADR-0228 §1's one-field clause a two-field clause and said *"nothing else about
it moves"*; §9 makes it four, adding each `StepCondition.about` and each
`PlanInterpretation.settles` under §5's identical discipline. A reader holding only ADR-0249 §8
builds a loop that resolves nothing on a returned plan, and therefore a system in which a plan can
never condition on an element the same call proposed — which is the ordinary first turn of every
conditional goal, since a goal at revision 1 carries no elements at all (ADR-0249 §9). The
ordering is §8's own: the substitution runs **after** the recording, for the reason §8 orders its
stamp that way. **Everything else of §8 binds verbatim**, including its not-driven rule, its
`save_plan` refusal — which §9 extends by one conjunct on the same footing ADR-0249 §12 gives
`commit_transition`'s — and its statement that `targets_revision` is not a second `supersedes`.

**ADR-0252 §14 — partially superseded in one term, and the tension is inside ADR-0252 rather than
introduced here.** §14 rules that no model supplies an **applicability**; §3's second source
requires an `INTERPRETATION` row's `supported` to be *"the one region the interpretation step
declared"*, and a step is a thing a plan declares. A reader holding §14 alone composes no
`INTERPRETATION` row at all, because §3 offers no other source — ADR-0070 §1's test coming out on
the supersession side. §7 states the resolution, the scope is that one term on that one basis, and
**every other term of §14 binds entire on both bases**.

**ADR-0252 — three pushed clauses discharged, and a record is owed on its header.** §6's push
(*"A step's condition declares a required `basis`, and on the `INTERPRETATION` basis a
`declaration` and the member of its enumeration the condition requires"*) is §5; its
`read_kind`/`source` question is answered there; its recency clause (*"The figure lives on the
step, A5 lands the field"*) is §5's `evidence_recency`. §9's operand (*"What a revision requires …
is the declared applicability A5 lands"*) is §7, and that section's *"until A5 lands,
`GoalRevision.invalidates` is empty"* ends with it. §1's *"What form the identifier takes is A5's"*
is §8's element id, and §5's *"Which enumeration it is, what its members are called"* is §8's
`InterpretationVerdict`. **Nothing of ADR-0252 is superseded**: every one of those is a clause that
named this lane and left a hole in the shape of its answer, and filling it is the clause working.
§14's writer clause is **relied on and not narrowed** — §7 states why a condition's declaration is
not a row's.

**ADR-0037 — relied on and not superseded.** §2's *"The step itself is read from the plan, not
accepted from the caller"* is the ground §6 puts the resolver on, and its argument binds entire;
§6's *"This object disposes of one step, once"* is untouched, because the driver A7 lands calls
`StepRunner` once per step rather than changing what `StepRunner` does. No entry point of that
stage gains a parameter.

**ADR-0148, ADR-0152 and ADR-0145 — relied on and not superseded.** ADR-0148 §1's completeness
rule is what §6 orders the resolution against, and §2's exactness default is what §4's
`FIELD_EQUALS` compares by; ADR-0152 §1's *"`parameters` is the `FrozenJsonMapping` the
`ActionRequest` will carry, unaltered"* is true of the resolved mapping exactly as it is of a
literal one, and the seam is handed no reference; ADR-0145 §1's check runs over the resolved
mapping, at the slot it already occupies. **None of the three needs a clause changed to admit a
resolved value**, which is the point of resolving before the request is built rather than after.

**ADR-0181 — relied on and not superseded**, and §6 states the clause that keeps it so:
`planned_with_external_content` is not widened, its `rebind` transcription is untouched, and its
§2 marked limit binds this decision entire.

**ADR-0226 and ADR-0228 — relied on and not superseded.** ADR-0226 §3's label scheme and §4's
*"A `ReadAsk` is not a `PlanStep`"* reasoning are each adopted whole (§8, §9); ADR-0228 §8's namer
rule binds every field this decision adds; ADR-0228 §2(a)'s fail-closed rule is what §5 makes
`basis` required for, and §4 states why `verifies` is **not** a case it governs. ADR-0228 §1's
authored-at-the-seam clause, as ADR-0249 §8 restates it, is what §8 and §10 keep: no component
edits `steps` or `interpretations`.

**ADR-0251 — relied on and not superseded.** §5's allowance and §6's investigation share are each
read as written in §8, and the conclusion that an interpretation call falls under §6's
*"Composing and verification are not gated on the attempt's allowance at all"* is that clause
applied rather than extended. No figure of ADR-0251 moves and `AttemptEffort` gains no member.

### 14. The arms this decision owes

The two lanes ship these, and #2255's acceptance rows are named where an arm carries one.

**Shape and construction (L1).**

1. A plan whose step declares `depends_on` naming a **later** step, **itself**, a step **not in
   the plan**, or the **same step twice** is refused at construction — four cases, one per
   refusal (§1). The arm records that a cycle has no other spelling and is therefore
   unconstructible rather than detected.
2. A `ResultReference` whose `step` is **not** in the declaring step's `depends_on`, whose
   `parameter` is **already a key** of that step's `parameters`, or which shares a `parameter`
   with a second reference of the same step, is refused at construction (§6).
3. `StepVerification` admits exactly §4's three shapes and refuses every other, including
   `FIELD_EQUALS` with no `field` and `OUTPUT_PRESENT` with one.
4. `StepCondition` with **no `basis`** is not constructible; with `basis` `INTERPRETATION` and no
   `requires`, or with `requires` `INCONCLUSIVE`, or with a `read_kind`, is refused; with `basis`
   `READ_OUTCOME` and a `requires` is refused (§5).
5. A plan declaring **five** interpretations is refused; four is accepted; two sharing a `settles`
   or an `id` are refused (§8).
6. `InterpretationVerdict`'s three values are **disjoint** from `ReadOutcomeKind`'s seven — a
   parameterized arm over both vocabularies, so a later member of either cannot silently collide
   (ADR-0252 §5).
7. A `GoalElement` round-trips its `id` and its `applicability`; a **retained** element copied by
   ADR-0249 §7's retention carries the **same** `id`, and a **restated** one carries a different
   one (§7).
8. **A stored plan written before this decision decodes**, with all six new fields at their
   defaults, and is byte-identical on re-dump but for them; a stored `GoalElement` decodes with
   `id` and `applicability` absent (§10).
9. `PROTOCOL_VERSION` and `PlanExport.schema_version` each moved by exactly one in L1, asserted
   against the log entry that names this ADR.

**The seam (L2).**

10. **A model-supplied step id is refused.** An envelope whose step object carries an `id` key is
    an extraction failure, and the arm asserts the plan's ids are the factory's (§1, §9).
11. An `after` ordinal that is zero, negative, non-integer, out of range, **not strictly less
    than** the declaring step's own ordinal, or repeated, is an extraction failure and reaches the
    repair prompt — not a dropped edge (§1).
12. A `when` `basis`, a `requires`, a `verifies` kind and a `read_kind` outside their vocabularies
    are each extraction failures, parameterized over `1`, `"true"`, a case-variant and a near-miss
    spelling, on ADR-0176 §1's own arm shape (§9). An `evidence_recency` that is not an ISO-8601
    duration, is zero, or is negative is an extraction failure and is never clamped (§9).
13. A `ProposedElement` proposing **no axis at all** records an element with `applicability`
    **absent**; one proposing axes that **do not compose** an `EvidenceApplicability` — an empty
    sequence axis, a window with both ends unset, a window whose `end` is not after its `start` —
    is an **extraction failure**, and neither case silently records a malformed requirement as no
    requirement (§7). A paired arm asserts the consequence: a `READ_OUTCOME` condition over an
    element with a **Sunday** applicability is **not** satisfied by an answering Saturday row,
    where the same condition over an element with **absent** applicability is — which is ADR-0252
    §6 test 1 as ratified and is why the malformed case may not reach it.
14. An interpretation naming an `M` label **out of range**, or a label naming a **search-minted**
    or **fetch-minted** record, is an extraction failure (§8).
15. A plan whose interpretation's `record` is not a record the loop passed on that call is
    **refused before it is saved** — `save_plan` is not reached, no step is dispatched and no
    interpretation is performed (§9).
16. **The condition label resolves against the brief where no understanding is returned**: a brief
    carrying two conditions renders `D1` and `D2`; an envelope naming `D2` produces a plan whose
    `about` is the **second element's `id`**; `D3` resolves to nothing.
17. **The condition label resolves against the understanding where one is returned**, which is the
    first-turn case: a goal at revision 1 with **no** elements, an envelope proposing one
    condition and a step naming `D1`, produces a plan whose `about` is the `id` `orchestration`
    minted for that element **a moment earlier** — and the ordering is asserted, not inferred
    (§9).
18. **A label naming a proposed element ADR-0249 §7 dropped resolves to nothing and does not
    resolve to its neighbour**: an envelope proposing two conditions of which the first is dropped
    for an unresolvable ground, with a step naming `D2`, **refuses the plan** rather than pointing
    it at the surviving element.
19. `PlanStore.save_plan` **refuses** a plan carrying an unsubstituted label, or an `about` naming
    an element of a revision the plan does not target, with the error class ADR-0249 §8 gives an
    unstamped `targets_revision` (§9) — a conformance-suite arm over both stores and the canonical
    fake.

**The predicates, asserted as predicates because no lane drives them (L1).**

20. **"Booking depends on the weather condition being satisfied"** — a step whose `when` names a
    condition for which **no** row of the goal satisfies ADR-0252 §6's four tests is **not
    eligible**, asserted as the predicate over a constructed goal, a constructed evidence row set
    and a constructed plan.
21. **"Conditional plan spans multiple decisions"** — two steps naming one element and requiring
    `QUALIFIES` and `DOES_NOT_QUALIFY`, over a goal holding **no** other row for that
    declaration: with a `QUALIFIES` row exactly one is eligible; with a `DOES_NOT_QUALIFY` row
    exactly the other; with an `INCONCLUSIVE` row **neither**; and the plan is intact in every
    case (§9).
22. **An `INCONCLUSIVE` row disables nothing**: over a goal already holding a `STANDING`
    `QUALIFIES` row that passes all four tests, adding an `INCONCLUSIVE` row of the same
    declaration leaves the qualifying branch **eligible** — the row neither satisfies, nor
    refreshes, nor blocks (ADR-0252 §5, §7, §8 limb 5).
23. **Two `STANDING` settling rows carrying different members over overlapping applicabilities
    satisfy neither branch**, and no rule of this decision picks a winner (ADR-0252 §7, §9).
24. **Two steps about two different elements are both eligible where both are evidenced** — the
    arm that records that §9's exclusivity does not generalise to disjunction and that nothing
    here makes an act at-most-once (§5).
25. An **unresolvable reference** is `UNMET_DEPENDENCY`, over each of §6's six unresolvable cases,
    and **never** a default, a blank, an omitted parameter or a `null`.
26. A **resolved reference is in the `ActionRequest` before `ActionPolicy.decide` is reached** —
    asserted at the seam, against ADR-0148 §1's completeness clause, with the resolved value
    present in the request's `parameters` and in the digest.
27. A dependency on a `SUCCEEDED` producer whose `verifies` **fails** is unsatisfied; on a `FAILED`
    or `SKIPPED` producer it is unsatisfied; on an **`INDETERMINATE`** producer the dependent step
    is **neither dispatched nor skipped** (§2).
28. A step declaring **no** `verifies` is satisfied by `SUCCEEDED` alone, and a step declaring
    **no** `evidence_recency` is satisfied by a row of any age that passes the other three tests
    (§4, §5).

### 15. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**A reader acts differently, so this is a decision and not a clarification.** A reader holding the
corpus without it builds a `PlanStep` with four fields, an `ActionPlan` with no interpretations, a
`GoalElement` with no identity, and a plan that cannot express a dependency, a reference or a
condition — and cannot implement ADR-0252 §6 at all, because every operand of its four tests is
missing. That is ADR-0070 §1's test met, and a new ADR is the instrument.

**It is a partial supersession of exactly two documents** (ADR-0070 §3) — **ADR-0249** in three
scopes (§1's `GoalElement` enumeration, §7's `ProposedElement` enumeration, §8's field count) and
**ADR-0252** in one term of one clause (§14's `applicability`, on the `INTERPRETATION` basis) —
and the `Status` line names each without an `ADR-NNNN` token inside the parentheses, so ADR-0070
§4's extraction invariant holds. Every other ADR it touches is **relied on**, and §13 shows the
working for each rather than leaving a reader to check.

**The records it owes land in the same change as this document** (ADR-0082 §7): ADR-0249's `Status`
pair, ADR-0252's `Status` pair and its dated note, and ADR-0014's dated note are written with it
and not after it.

## Consequences

**A plan becomes a graph with conditions, and the audit record stays one value.** What was
decided, what it waited on, what filled its arguments and what had to be true before it ran are
all in the one frozen `ActionPlan` that ADR-0014 §2 already makes the record of a decision — so
"why did this step not run" is answerable from the plan and the execution together, without a log
and without reconstructing a model's reasoning.

**`UNMET_DEPENDENCY` and `StepExecution.output` stop being vocabulary with no producer and no
consumer.** Both have sat in the durable types since ADR-0014 for exactly this lane, which is why
neither needs a vocabulary change now.

**Two model calls a turn may now make are shaped very differently, and the smaller one is the
point.** The planner sees everything the turn assembled; an interpretation sees one record and a
sentence, and can answer with one of three words. The second is the kind of model call #2096 item
7 argues for, and the first time this system has one.

**The cost is one more thing a planner can get wrong, and the disposal is stated per field.** A
malformed dependency, vocabulary member, recency figure or applicability costs an envelope and a
repair prompt; a condition label that resolves to nothing costs the whole plan, before it is
saved; an unresolvable reference costs a skipped step; a condition nothing satisfies costs a
skipped step; an element deliberately proposing no applicability costs an interpretation that is
not performed. **Every one of them fails closed**, and none of them dispatches an act on a value
nobody chose — the one thing none of them buys is an act performed **at most once**, which is
A8's and which §5 says so in terms.

**Nothing dispatches yet, and §3 is what makes that interval an interval rather than a hazard.**
A5 lands the plan's half, A6 the authorization half and A7 the driver; until all three are in and
A8, A9 and A10 have discharged the guarantees, no consequential capability is wired into a
production deployment.

## Alternatives considered

**A substitution language in `parameters` — a sentinel object, or `${step1.output.ref}` in a
string.** Rejected, and it is the alternative ADR-0014 §7 named when it deferred this. A sentinel
object makes every ordinary JSON object a potential reference and puts this system's control
vocabulary inside a tool's own argument space, where a legitimate argument can collide with it. A
string template is an interpreter of a model-written string over a tool-returned structure, which
is a surface with no upper bound on what it admits. The typed triple beside `parameters` has
neither property and costs one field.

**An expression language for `when` — booleans, negation, comparison.** Rejected. Negation is a
requirement of absence and the corpus already forbids composing an assertion of absence
(ADR-0237 §7); disjunction is two branches, which §9 expresses with no new machinery; and every
operator is a thing an implementation and a reviewer must evaluate identically. A conjunction of
positive requirements over closed vocabularies is checkable by reading.

**A `when` condition carrying its own applicability instead of naming a goal element.** Rejected,
and it is the reading ADR-0252 §6 test 1's wording most invites. It leaves ADR-0252 §9 with no
operands — §9 compares what two **revisions** require, and a value on a step is not on a revision
— so invalidation would stay permanently inert and a goal's dates could move with its evidence
still satisfying the old requirement. It is also two carriers for one fact (ADR-0251 §3).

**The `declaration` as the interpretation step's own id, or as the plan's.** Rejected on ADR-0252
§8's own words: a re-plan mints new ids, so limb 3's *"`L.declaration` equals `E.declaration`"*
could never hold across two plans and a *"three-day-old disagreement would block the goal
forever"*. ADR-0252 itself already rules out the plan id, for the different reason that one plan
may declare two.

**An interpretation as a `PlanStep` with an optional `capability`.** Rejected. It would oblige
`capability` to become optional on every step in the system for the one kind that names none, and
it would route a model call through `ExecutionState`, where ADR-0014 §4's unconditional
`approval_ref` on every `→ RUNNING` transition has no honest value to take. ADR-0226 §4 already
decided the shape for the nearest thing — a read the loop performs — and this follows it.

**Resolving the condition label in the planner implementation instead of in the loop.** Rejected.
It needs the element's `id` on `BriefElement`, which is buildable — ADR-0249 §9's `goal_id`
carve-out would cover it — but it cannot reach an element the **same call** proposes, whose id
does not exist until `orchestration` records the revision. The only repair is to have the planner
implementation mint element ids, which puts a durable interpretation's identifiers outside the
component ADR-0249 §6 gives every stamp to, and leaves orchestration accepting or rejecting ids it
did not mint. Resolving in the loop costs one clause of ADR-0249 §8 and keeps every durable id in
one place.

**Carrying the condition's target as an ordinal into the targeted revision rather than as an id.**
Rejected, and it is the route that looks cheapest. An ordinal needs no substitution and no
supersession — but ADR-0249 §7 **drops** an element whose ground does not resolve, so a dropped
element shifts every later position and an ordinal still resolves, to the **wrong** element. A
silent misresolution is worse than a refusal, and an id cannot shift.

**A per-declaration verdict enumeration, whose members the plan declares.** Rejected. The members
would be unprovenanced strings a model wrote into a durable row, and two plans about one
proposition would rarely spell them the same way, so ADR-0252 §8's refresh could not hold.
ADR-0252 §7 already contemplates one enumeration over several propositions in terms.

**A fifth `SkipReason` for a condition that was never satisfied.** Rejected. It widens a durable
vocabulary carried in `StepExecution`, `StepTransition`, `PlanExport` and the wire, to distinguish
two cases whose disposal, audit and recovery are identical — and ADR-0014 §4 already describes the
transition's trigger as *"nothing can run it"*.

**Making `verifies` mandatory.** Rejected. A predicate about a tool's return shape that a planner
was obliged to invent on every step would fail steps that succeeded and pass steps that did not,
on a guess nobody recorded. ADR-0252 §6's recency clause is the precedent for the other direction:
*"a step that declares no recency requirement imposes none."*

**Widening `CarriedProvenance.planned_with_external_content` to cover a resolved reference.**
Rejected. ADR-0181 §2 states that fact over a **selection into a model call**, and a value a tool
returned is neither; reading it in would make the field mean two things and would make ADR-0181
§3's `rebind` transcription — which has no execution to recompute from — disagree with every
approved binding. The protection that matters is already structural: the request is complete
before the ruling (ADR-0148 §1), so the resolved value is in what the policy rules on and in what
the user is shown.
