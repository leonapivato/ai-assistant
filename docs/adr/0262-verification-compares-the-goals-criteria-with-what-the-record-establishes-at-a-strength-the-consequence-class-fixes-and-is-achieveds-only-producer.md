# 262. Verification compares the goal's criteria with what the goal's own records establish, at a strength the consequence class fixes, and it is the only producer of `GoalStatus.ACHIEVED`

- Status: Proposed
- Date: 2026-09-15
- **No ADR is superseded in whole or in part.** §10 states the test for every ADR this
  decision reaches and shows the working: six documents **book this subject here by name** and a
  booking **discharged** is not a clause made false; the one Protocol strengthening is the move
  ADR-0261 §12 already ruled owes ADR-0250 §9 no record; and the one `TurnOutcome` widening is the
  move ADR-0242 §9 made and recorded nothing for.

## Context

### Where this comes from

This is **A10** of the six-phase task lifecycle design ([#2255](https://github.com/leonapivato/ai-assistant/issues/2255)),
and the last of its ten. Its row in revision 1 of the fit report is exact about the subject —
*"Verification against the goal's criteria, **strength proportional to consequence**, the
six-member report vocabulary"* — and equally exact about what it takes from earlier decisions:
*"Nothing. Reads strength off ADR-0016 §1's required declarations, ordered by §2."*

The six requirements, quoted:

| | |
|---|---|
| **R48** | The observed outcome is compared against the success criteria established in phase 1. |
| **R49** | Verification uses the strongest practical evidence the integration supports, and mandates no redundant read where the returned evidence already establishes the outcome. |
| **R50** | An ambiguous acceptance is never reported as a verified outcome. |
| **R51** | The report distinguishes success verified / condition prevented action / partial completion / failure established / outcome uncertain. |
| **R52** | Verification may reopen earlier work, and a repair or cancellation is **itself an action** whose authority is established rather than assumed. |
| **R53** | Closing an attempt never falsely marks the intended outcome achieved: an attempt ending is not the same event as the task completing. |

**The owner's correction of 2026-09-12 binds every clause below and has been carried unchanged by
three decisions since**: *"Producing a reply never by itself establishes that the goal was
achieved; completion criteria concern the requested outcome."* ADR-0249 §4 states it as a
prohibition, ADR-0253 §4 and ADR-0255 §8 each state it as a boundary around `verifies`, and this
decision is where the positive half is written.

**And decision 4 of the same ruling** — *"every reassignment explicit, production consequential
workflows carry verification/unknown-outcome/cancellation guarantees as a rule"* — is what §7
answers: this ADR is the **verification** guarantee of ADR-0255 §13's gate.

### What is booked here, verbatim

- **ADR-0249 §4**: *"**`GoalStatus.ACHIEVED` gets no producer in this decision.** … A10 of #2255 —
  verification against the goal's criteria — is `ACHIEVED`'s only producer, and it is named here so
  that no later lane supplies one by inference."*
- **ADR-0249 §5**: *"**Which member a given attempt earns is A10's**; this decision fixes the
  vocabulary, because a field typed by an enum nobody has written is not a contract."*
- **ADR-0250 §12**: *"**`GoalStatus.ACHIEVED` likewise gains none**, which is A10's and the owner's
  correction 2."*
- **ADR-0253 §4**, which mints `verifies` and fences it: *"**this is not the verification A10
  lands, and the two are never conflated.** This predicate is about **one step's own output** …
  **Verification against the goal's criteria** — whether the requested outcome was reached, with
  strength proportional to consequence, and the producer of `GoalStatus.ACHIEVED` — is A10's, is
  stated over the goal's `criteria` rather than over a step's output, and is **not this field**."*
  **ADR-0255 §8 carries the same fence onto the driver** and adds *"nothing writes an
  `AttemptOutcome`"*.
- **ADR-0255 §12**: *"**Verification against the goal's criteria, strength proportional to
  consequence, which `AttemptOutcome` an attempt earns, and the producer of `GoalStatus.ACHIEVED`.**
  **A10.** §8 fixes that `verifies` is not it."*
- **ADR-0261 §11**, which leaves this decision one question it must answer rather than inherit:
  *"Whether `set_goal_status` should refuse an `→ ACHIEVED` write over a live attempt, as §2 makes
  it refuse an `→ ABANDONED` one. **Not decided** … the producer of `ACHIEVED` is **A10's** and so
  is the question of what becomes of an attempt under a goal it verifies. **Fired by that
  decision.**"* §5 takes it.
- **ADR-0266 §10**: *"**What the verification phase does with a quote, and coverage's other
  conditions.** The owner's ruling makes the actual charge confirmed after the act and a mismatch
  *"a reported finding"*; **no clause here verifies anything, compares a charge, or writes a
  finding**, and `AttemptPhase.VERIFY` is A10's … **Fired by A10**."* §2 and §3 take it.

**And one addition the owner made after ADR-0255's waivers were reviewed** (2026-09-13, recorded on
#2255): the closing offer of a report on an unfinished goal — *"Shall I try again later?"* —
*"is the part not yet pinned by a ratified rule; it belongs to A10 (ADR-0262: what a report says
about an unfinished goal)"*. §6 takes it.

### The three owner rulings of 2026-09-14 that bound this decision, and which half of each is taken

- **The authorisation's lifetime.** *"A request is judged against the world as it is now. Forecast
  dry → booking executes → **verification confirms** → goal complete → **the authorisation ends
  with the goal**."* **The ending itself is not written here**: the owner disposed of it as *"a
  short superseding ADR, one edge + one clause, sequenced after [ADR-0266]"*, and this decision
  contradicts it in no clause — what this decision supplies is the antecedent that ruling names,
  *verification confirms*, and the act that makes the goal terminal (§5). **The one case the ruling
  keeps open is preserved by §4**: the **uncertain-outcome** case, where the attempt does not end
  and the goal stays open until the uncertainty is resolved through the phases.
- **The charge is confirmed afterwards.** *"The actual charge is confirmed by the verification
  phase afterward; a quote/charge mismatch is a reported finding."* §2 takes it as an operand rule
  and §3 states honestly that the operand does not exist yet (ADR-0266 §10, [#2387](https://github.com/leonapivato/ai-assistant/issues/2387)).
- **The walkthrough runs on a simulated booking service.** M33's campsite walkthrough runs against
  an in-tree fake provider behind the real hub, phases, authorisation store and evidence; *"the
  first real consequential booking integration is M34"*. §7's gate is therefore about M34 and
  §12's arms run against fakes.

### The sequencing ruling, which binds this decision as it binds A9

The owner's ruling of 2026-09-13: *"Finish the six-phase workflow … and demonstrate it end to end
**using the existing interaction model** (subsequent turns; pauses for clarification or approval).
**Live message queuing, mid-run steering and general interruption are a separate follow-up.**"* So
verification here is a stage of a turn the user started, reading records the turn and its
predecessors wrote. **Nothing below schedules, polls, wakes, or runs outside a turn**, and the
owner's ruling of the same day is stated in the same words: *"Nothing checks on its own
initiative."*

### What the tree holds today, read rather than assumed, at `origin/main` `c92712c9`

- **`GoalInterpretation`** carries `outcome`, `outcome_ground` and its arguments, and
  `constraints`, `criteria` and `conditions`, each a `tuple[GoalElement, ...]`. **`criteria` is
  read by nothing that decides anything**: it is written by ADR-0249 §7's revision path, compared
  element-wise for ADR-0250 §5's `added` and `removed` (`orchestration/interpretation.py`), and
  projected onto `GoalBrief` under ADR-0249 §9's `S` labels (`planning/planner.py`) — three
  readers, none of which settles anything about the goal.
- **`AttemptOutcome`** is the six members ADR-0249 §5 fixed. **`AttemptOutcome.ANSWERED` is the
  only member any code writes**, at three sites in `orchestration/engine.py`, each guarded by a
  helper whose docstring says so in terms: *"a pass failing any of them ends no attempt — **which
  member it earns instead is A10's**"*. **The other five have no producer.**
- **`GoalStatus.ACHIEVED` has no producer**: `set_goal_status` is called at exactly two sites in
  `orchestration/engine.py`, writing `ABANDONED` and ADR-0250 §13's reopen to `ACTIVE`. **So two
  of the four members have a producer today**, and neither of the two says *this was reached*;
  `BLOCKED` is A3's and `ACHIEVED` is this decision's.
- **`GoalAttempt`'s validator** admits two shapes and no others: a terminal `state` with both
  `outcome` and `ended_at` present, a non-terminal one with both absent. **So an `AttemptOutcome`
  cannot be written except in the transition that ends the attempt**, which is why §4 states the
  two together rather than separately.
- **ADR-0261's lanes have not landed**: `DriveWithheld`, `ClaimRefused`, `effect_in_flight`,
  `close_goal_abandoned` and `has_outstanding_effect` are in no file of `src/`.
- As dated observations: `wire/envelope.py`'s `PROTOCOL_VERSION` reads **43**;
  `PlanExport.schema_version` reads `Literal[12]`; the plan store's `_SCHEMA_VERSION` reads **4**.

### The gap this closes, stated as the failure the corpus has today

**A goal that was fully served stays `ACTIVE` for ever.** ADR-0249 §4 states the cost in terms and
takes it deliberately — *"Until A10 lands, a goal that was fully served stays `ACTIVE` … That is a
legible gap and an honest one; a status that claimed achievement nothing verified would be
neither."* Two of `GoalStatus`'s four members have a producer, and neither of the two says *this
was reached*, so a completed objective is indistinguishable on every surface from one nobody has
started.

**And an attempt says only that it answered.** The one `AttemptOutcome` any code writes is the one
ADR-0249 §5 defines as *"the attempt produced an answer and **nothing was verified**"*. A booking
that succeeded, a booking that failed and a booking whose fate is unknown are all reported as
*answered* or as nothing at all, because the pass that would have said otherwise ends no attempt.
**R48 is unmet not because the comparison is hard but because nothing reads `criteria`.**

**The consequence, named because it is the one that costs.** ADR-0255 §13's gate holds a
consequential capability out of production until its **verification**, uncertain-outcome and
cancellation guarantees exist. A8's is ratified (ADR-0259) and A9's is ratified (ADR-0261); this is
the third, and until it lands the gate cannot be met by any capability at all.

### What this decision is not allowed to settle

Golden rule 5's Protocol change is stated and argued here and implemented by the lanes §11 cuts,
and nothing else. This decision **writes no retry policy** (A8's, ADR-0259 §10), **registers no
booking integration** (ADR-0154, and §7's gate), **designs no quote** (ADR-0266 §10, #2387),
**writes no `GoalStatus.BLOCKED`** (A3's), and **does not write the goal-terminal ending of an
authorisation** the owner ruled on 2026-09-14 — that is a later ADR's, whose number is not yet
issued and is therefore elided rather than cited (ADR-0088 §6 Tier 1), its lane being
[#2376](https://github.com/leonapivato/ai-assistant/issues/2376).

## Decision

### 1. What a goal's criteria are, and the order that makes the circularity unreachable

> **Normative.** **A goal's completion criteria are the `criteria` tuple of that goal's *current*
> `GoalInterpretation`** (ADR-0249 §1), read at the instant verification runs, **and nothing else
> is one.** Not an earlier revision's criteria — ADR-0249 §7 makes *"omission is removal"* and a
> criterion the user's later words dropped is not a criterion the goal still has; not the plan's
> own expectations; not a step's `verifies` (ADR-0253 §4); not a `constraints` or `conditions`
> element, each of which ADR-0266 §1 already distinguishes — *"a criterion states what success
> would be and a condition when a step may run"*.

> **Normative — the requested outcome is the interpretation's `outcome`, and it is what the
> criteria are criteria *of* rather than a criterion itself.** No clause below evaluates
> `outcome` against anything: it is a `NonBlankEncodableText` stating an objective in prose, and
> comparing prose is the thing §2 refuses. **What the report names is the outcome** (§6); what
> verification compares is the criteria.

> **Normative — nothing the reply says is a criterion, and the order is what makes that
> unreachable rather than forbidden.** Verification runs in the turn's **`AttemptPhase.VERIFY`**
> (ADR-0249 §6), **after the walk has ended** (ADR-0255 §1) and **wholly before the composing
> stage** (ADR-0170 §1). At the instant every clause below is evaluated **no reply exists**, so no
> implementation can compare one against a criterion, take one as an operand, or infer a verdict
> from one. **No lane moves verification after composing, re-runs it over a composed reply, or
> passes a `ComposedReply` into it.**

**The owner's correction is made structural here rather than restated.** ADR-0253 §4 observed that
*"A field named `verifies` on a step is exactly the value a later lane would reach for when asked
whether a goal was achieved"*, and answered it by fencing the field. The same reach exists one
level up: the cheapest thing to verify against is the answer the system just wrote. Stating the
**order** — the reply does not exist yet — closes it by construction, which is what a prohibition
alone would not, and it costs nothing, because ADR-0249 §6 already puts `VERIFY` after `EXECUTE`
and the composing stage already runs at the end of the turn.

> **Normative — verification writes no interpretation and reads no model output.** It records no
> `GoalInterpretation` revision, rewrites no `GoalElement`, marks no `GoalEvidence` row, and calls
> no `Planner.plan`. ADR-0252 §10's rule binds unchanged — a revision *"is a statement of what was
> understood **when it was recorded**"* — so a criterion that turned out not to hold is **not**
> edited, dropped or re-grounded; what changes is the attempt's outcome and the goal's status, and
> nothing else.

> **Normative — a goal carrying no criterion is not thereby verified.** An empty `criteria` tuple
> is the ordinary shape of a goal at revision 1 (ADR-0249 §3 mints revision 1 with every element
> tuple empty), and §4's function reaches `ANSWERED` for it and **never `VERIFIED`**. **No lane
> mints a criterion, synthesises one, or reads an empty tuple as *every criterion met*.**

**An empty tuple could be read as a vacuous truth and that reading is refused by §4's order rather
than by a special case.** *"What is two plus two"* opens a goal whose criteria are empty and whose
attempt answers it; the honest report is that an answer was produced, which is exactly what the fit
report's §I.3 concluded — *"it does not claim the answer was **verified**, because on a
no-consequence attempt nothing verified it. … This is a smaller claim than revision 0 made and it
is the honest one."* `VERIFIED` requires a criterion to have been compared, and §4's limb 5 says so.

### 2. How a criterion is established: three results over two typed operands, and prose is neither

> **Normative — a criterion is, at the instant verification runs, exactly one of three, and the
> three are total by construction.** **Met** — an operand below establishes it. **Unmet** — an
> operand below establishes that it does **not** hold. **Unestablished** — neither, which is the
> residue and needs no test of its own. **No fourth result exists, no result is a degree, and no
> lane reads *unestablished* as either of the other two.**

> **Normative — exactly two kinds of record are operands, and every other value in this system is
> not one.** **(a) A `GoalEvidence` row of that goal** which satisfies **ADR-0252 §6's four
> mechanical tests** against the criterion's declared applicability, basis, declaration and
> required member — coverage, the evidence the condition declared, `STANDING`, and recency —
> evaluated exactly as that section states them and with **no test added, removed or reordered**.
> **(b) A `StepExecution` of an execution the attempt opened** whose step declares a `verifies`
> predicate (ADR-0253 §4) and whose stored `output` satisfies it, evaluated as ADR-0255 §8
> evaluates it — in code, over that step's own output, mechanically.

> **Normative — model prose is not an operand, and neither is a status.** **No criterion is
> established from a `GoalElement.text`, a `GoalInterpretation.outcome`, an `IntendedAction.intent`,
> a `StepFailure.message`, a tool description, a composed reply, or any other free text**, and
> **none from `StepStatus.SUCCEEDED` alone**. ADR-0244 §2's discipline is the ground, quoted one
> record over: *"`APPROVED` records what the user said and asserts nothing about what followed …
> a lane reading a disposition as evidence of a send has read the wrong record."* A `SUCCEEDED`
> step records that the tool returned; **what it returned** is the operand, through (a) or (b).

> **Normative — which of the two operands a criterion takes, and with which arguments, is
> **declared** and is never chosen at verification time.** The declarations are the ones A5 already
> landed and this decision **mints none**: a step's **`when`** carries ADR-0253 §5's typed
> `StepCondition`s, whose operands ADR-0252 §6 fixes, and a step's **`verifies`** carries ADR-0253
> §4's three-member predicate. **`GoalElement` gains no field, `GoalInterpretation` gains no field,
> and no new declaration surface is added anywhere.** A criterion for which the goal's records
> carry no such declaration is **unestablished**, which is a result and not a pass.

**Reusing ADR-0252 §6 rather than minting a second predicate is the whole economy of this section,
and the alternative is two authorities for one question.** That section already decides what it
means for a record to establish a proposition about a goal, over a closed vocabulary, with a model
forbidden from clearing any of it — *"Each is a comparison of values or of members of a closed
vocabulary; **none is a judgement, and no model output settles any of them.**"* A verification
predicate of its own would be a second such rule, free to disagree with the first about the same
row on the same turn, with nothing that fails when they do. **What this decision contributes is a
second caller of that predicate and a second moment** — at the attempt's end rather than at
dispatch — and the corpus's own reason for one rule read at two moments is ADR-0253 §4's, which
says of `verifies` that *"Those are two reads of two things"*.

> **Normative — a model's judgement reaches a criterion through exactly one route, and it is the
> route ADR-0252 already admits.** A `GoalEvidence` row on the **`INTERPRETATION`** basis carries
> the verdict of an interpretation step over one recorded record (ADR-0252 §1, §5), and such a row
> is an operand under (a) **like any other row and on the same four tests**. **This decision admits
> no other route**: it makes no model call, adds no verifying model seam, and takes no prose
> verdict. ADR-0249 §7's asymmetry is why — *"A model may never clear a permission, a coverage
> test, a **prerequisite** or a dependency"* — and establishing that a goal was achieved is the
> `ACHIEVED` write's prerequisite in exactly that sense, so what a model supplies stays the
> **declaration** and the **verdict over one record**, while the comparison stays arithmetic.

> **Normative — an unestablished criterion is never reported as met, which is R50 and is a
> property of the three results rather than a rule about ambiguity.** An operand that returns an
> ambiguous answer either satisfies ADR-0252 §6's tests or does not; where it does not, the
> criterion is **unestablished**, and §4's function admits no path from an unestablished criterion
> to `VERIFIED` or to `GoalStatus.ACHIEVED`. **No lane resolves an ambiguity by a second guess, by
> a model, by a default, or by reading a non-answering row (ADR-0252 §5) as answering.**

> **Normative — where the record already establishes a criterion nothing further is read, and that
> is R49 discharged by the phase performing no call at all** (§3). **No lane makes a redundant read
> here, because no lane makes any read here beyond the goal's own stored records.**

> **Normative — what a *charge* is compared against, and the honest state of that operand today.**
> Where a criterion of the goal is about what the act cost, its operand is the record of the
> **charge** read back after the act, through (a) or (b), compared against the ceiling the user
> stated — the owner's ruling of 2026-09-14, *"The actual charge is confirmed by the verification
> phase afterward; a quote/charge mismatch is a reported finding."* **The mismatch is a finding in
> this decision's own vocabulary and not a new one**: the criterion is **unmet**, §4's function
> yields `FAILED` or `PARTIAL`, and §6's statement is what reports it. **This decision mints no
> quote, no charge record and no carrier for either** — ADR-0266 §10 books the whole of that
> machinery to #2387 and records that *"until it lands §7's evidence route has no operand"* — so
> until that decision lands such a criterion is **unestablished** and §3 states what that costs.

### 3. Strength proportional to consequence: three rungs off the declarations, and the phase calls nothing

> **Normative — the strength a goal's verification owes is fixed by the consequence class of what
> the attempt **actually did**, and the class is read off declarations that already exist.** The
> class is computed over **every step of every execution `GoalAttempt.execution_ids` names that
> reached a committed `→ RUNNING` claim** — ADR-0148 §9's boundary, *"There is no egress outside a
> claimed step"*, with ADR-0014 §4's ordering — and over no other step. **A step a plan declared
> and no walk claimed contributes nothing**, because nothing happened.

> **Normative — the three rungs, and they are read off `ToolDefinition`'s required declarations.**
> For each such step, the `ToolDefinition` recorded for its committed **`bound_tool`** and the
> `PermissionDecision` its **`approval_ref`** names:
>
> - **Rung 2 — a consequential act ran.** Some such step's definition is **`side_effecting`** and
>   at least one of: its **`reversibility` is more severe than `REVERSIBLE`**; its **`discloses` is
>   non-empty**; or its decision carries an **`egress_binding`**.
> - **Rung 1 — an act ran that is not rung 2's.** Some such step exists and no step reaches rung 2
>   — a read, or a side-effecting act the tool declares `REVERSIBLE` that discloses nothing and
>   transmits nothing.
> - **Rung 0 — nothing was claimed at all.** No such step exists: the attempt composed an answer
>   and did nothing else.

> **Normative — `reversibility` is compared on ADR-0016 §2's severity ordering and never
> lexicographically, and the trap is named at the one site this decision creates.** That section
> overrides all four comparison operators for exactly this reason — *"`StrEnum` members **are**
> strings, so they already compare — **lexicographically**, which makes `RiskLevel.CRITICAL <
> RiskLevel.LOW` evaluate to `True`"* — and the same inversion sits under `Reversibility`, where
> `IRREVERSIBLE < RECOVERABLE < REVERSIBLE` reads in the exactly wrong direction. **The comparison
> is `definition.reversibility > Reversibility.REVERSIBLE`** under those overridden operators, and
> **no lane substitutes a rank table, a membership test against a hand-written set, or a string
> comparison.**

> **Normative — `discloses` is read beside `reversibility` and neither stands alone**, which is
> ADR-0016 §2's own conclusion binding here: *"a `REVERSIBLE` tool with a non-empty `discloses`
> performed an irrevocable disclosure while making a revocable change, and a policy that reads only
> the scale would auto-grant it. Reading both fields is not an implementation detail."*

> **Normative — `risk_level` is not read, and the narrowing is stated rather than left to be
> noticed.** Risk is the scale a *policy* thresholds to decide **whether to ask** — ADR-0016 §2's
> own sentence for it, *"The canonical policy sentence is a threshold — 'confirm anything at or
> above `MEDIUM`'"* — and the question here is **what an act did**, which `side_effecting`,
> `reversibility`, `discloses` and the binding answer directly. **No lane adds a `risk_level` limb
> to the ladder**, and a deployment that wants a stricter rung declares a stricter
> `reversibility` — which is a declaration ADR-0016 §1 already requires with no default.

> **Normative — what each rung owes, stated over the criteria and never over a call.**
>
> - **Rung 0** owes nothing beyond §4's function. Its attempt earns `ANSWERED`,
>   `CONDITION_PREVENTED` or `FAILED` and **never `VERIFIED`**, whatever the criteria say, because
>   nothing was done for a criterion to be about.
> - **Rung 1** owes the criteria §2's operands establish from what the attempt already recorded,
>   and **nothing more**. An unestablished criterion there leaves the attempt `ANSWERED` or
>   `PARTIAL` and **not `UNCERTAIN`** — nothing happened in the world for the record to be
>   uncertain about.
> - **Rung 2** owes verification against the criteria, and an unestablished one is **uncertainty**:
>   §4's limb 4 yields `UNCERTAIN`, and **an unverified consequential effect earns no `VERIFIED`,
>   no `ACHIEVED` and no statement that the outcome was reached.**

> **Normative — verification performs no call of any kind, and this is the whole of how R49 and the
> owner's ruling are one rule.** This phase **makes no model call, no tool call, no read through
> any seam, no `StepRunner` or `StepExecutor` entry and no `ToolInvoker.invoke`**; it reads the
> goal's own stored records and writes at most the two commits §4 and §5 name. **An independent
> read that a criterion needs is a step of a later attempt**, planned, authorised and claimed
> through the standard phases, which is the owner's ruling of 2026-09-13 stated for this phase —
> *"Nothing checks on its own initiative."* **No lane gives this phase a collaborator that calls
> anything, a budget, a deadline or a retry.**

**Making the rung decide what is *owed* rather than what is *performed* is what keeps S1 at one
planner call, and it is a stronger rule than the fit report's.** Revision 1 §I.2 named the tension
exactly — *"a mandatory second model call to verify would break the one-pass case"* — and answered
it by tiering the call. The owner's later ruling removes the call entirely, and the result is
better in both directions: the cheap case costs nothing at all, and the expensive case does not
quietly make an unbudgeted egress call in a phase nobody is watching. What rung 2 buys is not a
lookup; it is the **refusal to say verified**.

> **Normative — the guarantee this decision provides is met for a class only where that class's
> criteria have operands, and the one class that has none today is named.** §7's gate requires the
> verification guarantee *"for its class"*. A criterion about a **charge** has no operand until
> #2387 lands (§2), so **no consequential capability whose acts make a charge is wired on the
> strength of this decision alone**. **This adds no condition to ADR-0255 §15 item 19's count**,
> which ADR-0265 §8 made six: it states what this decision's own guarantee covers, which is what
> that gate already asks of it.

### 4. Which `AttemptOutcome` an attempt earns, when it is written, and when the attempt ends

> **Normative — the attempt ends where the turn produced a report, and stays live where it did
> not.** The `VERIFY` phase commits the attempt **`→ ENDED`** through **`PlanStore.commit_attempt`**
> (ADR-0249 §12), carrying the outcome the limbs below yield and `ended_at` at the turn's own
> instant, **exactly where all three of the following hold** at that moment, and **on no other
> turn**:
>
> 1. the turn **composed a reply that completed** — a `ComposedReply` carrying text and not
>    degraded (ADR-0173 §6);
> 2. the attempt is **not paused** — its `state` is none of `AWAITING_CLARIFICATION`,
>    `AWAITING_AUTHORIZATION` or `BLOCKED` (ADR-0249 §5's *paused* derivation), and no step of its
>    executions stands `AWAITING_APPROVAL`;
> 3. **no step of any of its executions stands `INDETERMINATE` or `RUNNING`** — the same two
>    statuses ADR-0259 §4 and ADR-0261 §3 read, so *outstanding* means one thing in the corpus and
>    not three.
>
> **Every other turn ends no attempt and writes no `AttemptOutcome` at all**, which ADR-0249 §5's
> validator already compels: an outcome is constructible only beside a terminal state.

**Limb 3 is the owner's ruling of 2026-09-14 made structural, and it is the clause that keeps the
reconciliation route open.** That ruling names one exception to a goal ending when its work is
done: *"The only case an authorisation must outlive a turn is the **uncertain-outcome** case
(timeout leaves the fate unknown; goal stays open until resolved through the phases with
permission)."* An attempt this phase ended would be terminal, and ADR-0259 §4's acts 3 and 4 move
an attempt between `RUNNING` and `EFFECT_UNRESOLVED` — **neither reachable from a terminal
member** (ADR-0249 §5). Ending such an attempt would sever the only route by which an uncertain
effect is ever resolved, leave ADR-0259 §3's reconciliation with nothing to repair, and report a
goal as finished whose act may or may not have happened. **So limb 3 is not a courtesy to the
report; it is what makes A8's guarantee reachable at all.**

> **Normative — which member the attempt earns, decided by the three results §2 yields over the
> criteria §1 fixes and by the record of the attempt's own steps, in this order and over nothing
> else.** At the instant of the write:
>
> 1. **`CONDITION_PREVENTED`** — **no** criterion is met, **no** step of the attempt reached a
>    committed `→ RUNNING` claim, and at least one step of its executions stands **`SKIPPED`**
>    carrying `SkipReason.UNMET_DEPENDENCY` or `SkipReason.APPROVAL_DENIED`, whichever source
>    status it was committed from. The plan's own declared conditions, or the user's own refusal,
>    refused the work before anything was done.
> 2. **`FAILED`** — some criterion is **unmet** and **none** is met.
> 3. **`PARTIAL`** — some criterion is **met** and some is not.
> 4. **`UNCERTAIN`** — every criterion is met or unestablished, **at least one is unestablished**,
>    and the attempt is at **rung 2** (§3): a consequential act ran whose outcome the record does
>    not settle.
> 5. **`VERIFIED`** — the goal carries **at least one** criterion and **every** one of them is met.
> 6. **`ANSWERED`** — otherwise, which is exactly ADR-0249 §5's own definition of the member: a
>    reply exists, no step failed and no condition blocked, and nothing was verified.
>
> **The six limbs are total over the results and the statuses and no input is left undecided**, and
> **no seventh limb, reordering or override is added.** `AttemptOutcome` gains **no member**: the
> vocabulary is ADR-0249 §5's six as ADR-0261 §3 made them **seven**, this decision reaches **six**
> of those seven — the clause below says which one it does not — and of those six it gives **five**
> the producer they have never had.

> **Normative — the order is the rule, and two of its positions are load-bearing.**
> `CONDITION_PREVENTED` precedes everything because such an attempt also has every criterion
> unestablished and would otherwise read `ANSWERED`, reporting *the question was answered* about a
> turn that refused to act. And **`VERIFIED` sits below `PARTIAL` and `UNCERTAIN` rather than
> above**, so that no combination of met criteria can outvote an unmet or an unestablished one —
> which is R53 read at the member level, *"Closing an attempt never falsely marks the intended
> outcome achieved"*.

> **Normative — `CANCELLED` is reached by no limb, and A9 keeps it entire.** ADR-0261's header
> states this decision's division in terms: *"the division becomes **every attempt but a cancelled
> one**. A10 keeps every member for every attempt it can reach, and it reaches no cancelled
> attempt"*. A cancelled attempt is terminal and ADR-0249 §5's *"no transition leaves a terminal
> member"* is what makes that true rather than a courtesy. **No lane writes `AttemptOutcome.CANCELLED`
> from this phase, and no lane reads §4's function as a general outcome rule for the act ADR-0261
> §2 performs.**

> **Normative — `orchestration` computes this and the store decides nothing about it.**
> `PlanStore` gains **no member** for it, `commit_attempt` gains **no conjunct**, and **no query,
> projection or collaborator is added to the engine** (ADR-0058). The criteria, the rows and the
> executions are values the engine already reads for the turn; the limbs are arithmetic over them.
> **This is deliberately not ADR-0261 §3's shape**, where the store computes a cancelled attempt's
> outcome inside its own write: that decision put it there because a claim can land between a
> caller's read and its commit *"and the attempt's own compare-and-swap cannot see one land"*.
> **Limb 3 of the ending rule removes that race here rather than guarding it** — an attempt with a
> claimable or claimed step does not end at all — so the value this phase computes cannot be
> falsified by a claim landing beside it, and the commit's own `expected_version` refuses anything
> that moved the attempt.

> **Normative — the write is one `AttemptTransition` and the phase takes no second bite.** A
> `StaleExecutionError` from that commit means another writer moved the attempt; the phase
> **writes nothing further, does not retry, does not recompute and does not fail the turn**, and
> the turn composes its reply with `attempt_report` **absent** (§6). **No lane loops here**, and
> the next turn that engages the goal reaches `VERIFY` again over whatever is then true.

### 5. `GoalStatus.ACHIEVED`'s one producer, and the conjunct that keeps a closed goal free of live attempts

> **Normative — `GoalStatus.ACHIEVED` has exactly one producer and it is the act below.** In the
> **same `VERIFY` phase**, and **only** where §4's function yielded **`VERIFIED`** on the attempt it
> has just ended, `orchestration` writes **`GoalStatus.ACHIEVED`** through
> **`PlanStore.set_goal_status`** (ADR-0250 §9) under the `version` it read, **and writes nothing
> else**. **No expiry, no silence, no timeout, no sweep, no reclaim, no model output, no inference
> and no other member of any Protocol writes `ACHIEVED`**, which is ADR-0250 §12's clause for
> `ABANDONED` stated for the member it reserved to this decision.

> **Normative — the two writes are ordered, the attempt first, and the order is what makes the
> conjunct below satisfiable.** The attempt's `commit_attempt` commits before the goal's
> `set_goal_status`, so at the instant the status write is taken the attempt this turn drove is
> terminal. **No lane writes the status first**, which would leave an `ACHIEVED` goal carrying a
> live, claimable attempt for the width of a store call — R53's failure with a window in it.

> **Normative — `PlanStore.set_goal_status` refuses an `→ ACHIEVED` write where the goal has an
> attempt in a non-terminal `AttemptState`**, decided **in the same indivisible step as the
> write**, and refuses it with **`StaleExecutionError`** — the caller's correct response being to
> end that attempt and write again. This is a **strengthening of a member that already exists**, on
> ADR-0255 §3's own footing, and it is the **exact mirror** of ADR-0261 §2's `→ ABANDONED` limb,
> which ADR-0261 §11 books here by name. **It binds on `ACHIEVED` alone**: `ABANDONED` keeps
> ADR-0261 §2's limb, `BLOCKED` is A3's and is constrained by neither, and `ACTIVE` on ADR-0250
> §13's reopen is untouched.

> **Normative — that conjunct and `open_attempt`'s existing closed-goal limb are exhaustive over
> the interleaving, and the second is already ratified.** ADR-0261 §2 refuses an `open_attempt` on
> a goal that is closed — *"`ACHIEVED` or `ABANDONED`, ADR-0250 §1's division"* — so an attempt
> opened **before** this act's status write is one the conjunct above sees and refuses the write
> for, and one opened **after** it meets a closed goal and is refused. **There is no third case**,
> and **no lane closes this with a read in the engine, a re-read after the write, a sweep or a
> lock.**

> **Normative — a refusal is re-read and retried once, and a second refusal leaves the goal
> `ACTIVE`.** On a `StaleExecutionError` the act re-reads the goal and, where it is still open and
> holds no non-terminal attempt, writes again under the version it has just read; where the re-read
> finds the goal **closed** or finds **none**, it writes nothing. **A second refusal propagates no
> further than the phase**: nothing is written, the turn does not fail, and the attempt stays
> `ENDED`/`VERIFIED` under an `ACTIVE` goal. **No lane retries a third time or loops.**

**The residual is legible and self-healing, and stating it is cheaper than a new store member.**
A goal whose criteria verified and whose status write lost twice carries an `ENDED` attempt with
`VERIFIED` beside an `ACTIVE` status — which is *the attempt established the outcome and the goal's
disposition has not caught up*, not a false claim in either direction. The next turn that engages
that goal opens a new attempt (ADR-0250 §12's third act), plans afresh, finds the goal's completed
effects claimed (ADR-0259 §2) and reaches `VERIFY` with the same criteria met, and the write lands
then. **The alternative is a `close_goal_achieved` member mirroring ADR-0261 §2**, refused under
Alternatives: that act had to compute an outcome the store could see, and this one's outcome is a
comparison against criteria the store has no business reading.

> **Normative — an attempt reaching a terminal state still moves no goal status, and this act is
> not an exception to ADR-0249 §4.** That clause binds entire and is obeyed in the direction it is
> stated: **nothing here infers a status from an attempt's state.** One act of one phase takes both
> writes because one comparison decided both, and **an attempt that ends `ANSWERED`, `PARTIAL`,
> `FAILED`, `UNCERTAIN` or `CONDITION_PREVENTED` moves no status at all** — the goal stays open and
> is engageable, resumable and plannable exactly as before.

> **Normative — R53 is the distance between §4's write and this one, and the two are never
> collapsed.** *"An attempt ending is not the same event as the task completing."* Five of the six
> members end an attempt and close nothing; **`VERIFIED` is the only one that reaches this section**,
> and it reaches it because a comparison was made rather than because an attempt stopped. **No lane
> derives a `GoalStatus` from an `AttemptOutcome`, reads `ENDED` as completion, or writes `ACHIEVED`
> from any fact but §4's limb 5.**

### 6. The report: six members, one fixed statement each, and the offer that continues an unfinished goal

> **Normative.** **`core/types.py` gains `AttemptReport`**, a frozen model with `extra="forbid"`
> carrying **exactly two fields**: **`outcome`**, an `AttemptOutcome`, required; and
> **`continues`**, a `bool`. It carries **no goal id, no attempt id, no criterion, no criterion
> text, no count, no evidence reference, no step id, no instant and no prose** — the containment
> ADR-0249 §9 argues for `GoalBrief` and ADR-0250 §5 for `GoalEngagement`, reached here for the
> same reason: *"an implementation that rendered every field of every value it was handed …
> discloses none of those, because there is none on the value to disclose."*

> **Normative.** **`TurnOutcome` gains exactly one field, `attempt_report`, typed
> `AttemptReport | None` and defaulting to `None`**, and its docstring names this ADR. It is
> **non-`None` exactly on a turn that ended an attempt under §4** and `None` on every other
> returned outcome — a turn that engaged no goal, a routed operation (ADR-0197 §7), ADR-0198 §1's
> restatement, and every turn whose attempt stayed live. That adds a value to ADR-0198 §2's
> enumeration **without changing any value it fixes**, and it is ADR-0242 §9's widening one member
> over.

> **Normative — `continues` says that the goal's work is unfinished and the user may take it
> further, and it is computed from two facts and never by a model.** It is **`True`** exactly where
> the outcome is **`PARTIAL`**, **`FAILED`** or **`UNCERTAIN`** **and** the goal is **open**
> (ADR-0250 §1: `ACTIVE` or `BLOCKED`). It is **`False`** on `VERIFIED`, on `ANSWERED` and on
> `CONDITION_PREVENTED`. **No lane derives it from a model's opinion, makes it configurable, or
> sets it on a closed goal.**

> **Normative — the composing stage is told both, and its instruction requires the offer where
> `continues` is set.** ADR-0170 §5's construction binds and its limit is adopted with it: the
> stage is **given** the outcome member and `continues`, and its instruction **requires the answer
> to end with an offer to continue** where `continues` is set, and **requires it not to narrate as
> verified an outcome that was not**. **No clause of this section is a guarantee about model
> output**; where a reply asserts otherwise, §6's fixed statement beside it is the record and the
> reply is wrong, which is ADR-0170 §5's own closing clause read here.

**The offer is in the reply rather than on the surface, and the reason is the binding it buys.**
The owner's addendum of 2026-09-13 states the mechanism it is for: the reply ends *"Shall I try
again later?"*, and the next turn's bare *"Yes"* **binds to the goal by reply reference** (ADR-0250
§3's first rule, which takes no model call). A statement rendered by an adapter beside the reply is
not something a user answers, and an offer a surface printed would reach neither the browser's
transcript nor the spoken channel as part of what was said. So the **reply** carries the offer and
the **surface** carries the outcome word — ADR-0242 §9's own split, *"the model says **what was not
done** and the surface says **what would enable it**"*, one fact over.

> **Normative — one fixed statement per member, rendered beside the reply and never in place of
> it, on ADR-0242 §9's construction.** For **`VERIFIED`**, that the goal's stated criteria were
> checked and hold, naming `assistant goals` as where the goal's state is read; for **`ANSWERED`**,
> that an answer was produced and **nothing was verified** — never that it is correct; for
> **`PARTIAL`**, that part of what was asked was done and part was not; for **`FAILED`**, that what
> was asked was established not to have happened; for **`UNCERTAIN`**, that an action was taken and
> **its outcome is not established**, naming `assistant goals`; and for **`CONDITION_PREVENTED`**,
> that a stated condition did not hold so nothing was done. **The exact wording is the lane's; what
> is fixed is which fact each names.**

> **Normative — no statement asserts anything the record does not carry.** None says that the goal
> is complete unless the member is `VERIFIED`; none says an effect did not happen; none names a
> criterion, a tool, a destination, a figure, a `Settings` field or a cause; and **`UNCERTAIN`'s
> says nothing about whether the call left** — ADR-0261 §6's *"no caller assumes the query did not
> leave"* binding on one more statement. **A surface that renders no statement for a member has not
> implemented this section and is not a permitted degradation** (ADR-0242 §9).

> **Normative — this is not ADR-0250 §5's announcement and neither displaces the other.** §5's
> sentence is about **which goal a turn is about** and is owed on a resumption, a reopen or a
> revision that moved a word; this statement is about **what the attempt produced**. A turn may owe
> both, one or neither, they are two `None`-defaulting members on ADR-0244 §9's rule, and **no lane
> derives either from the other or collapses them.** §5's rule that an `OPENED` or `CONTINUED` turn
> which moved no word *"says nothing about goals at all"* stays true word for word: a statement
> about what this attempt produced is not a sentence about the goal's identity.

> **Normative — a meaningful completion is announced once, and the record is what says it
> afterwards.** The statement is rendered on the one turn `attempt_report` is non-`None`. **No lane
> repeats it on a later turn, re-renders it from the stored `AttemptOutcome`, or makes the value
> durable on any other record**: where a user asks later how a goal stands, `assistant goals` reads
> the goal's status and the attempt's own stored outcome, which is why each statement that needs a
> route names that command.

### 7. Q4's gate: this decision is the third guarantee, and all six conditions still stand

> **Normative — ADR-0255 §13's rule is carried unchanged and is not weakened here.** *"No
> consequential capability is wired into a production deployment until the verification,
> uncertain-outcome and cancellation guarantees for its class are implemented and demonstrated."*
> **The lanes of this decision wire no consequential capability**, register no booking integration
> and enable nothing in a production deployment; §12's arms run against controlled fakes, and
> M33's campsite walkthrough runs against the simulated booking service the owner ruled on
> 2026-09-14.

> **Normative — this decision is the gate's **verification** guarantee and meets that condition for
> a class exactly as §3 states it.** §2's operands and §4's function are the mechanism; §3's rungs
> are the strength; and the guarantee covers a class whose criteria have operands, which today
> excludes a criterion about a charge (§3, ADR-0266 §10, #2387).

> **Normative — the count is ADR-0255 §15 item 19's as ADR-0265 §8 made it, it is **six**, and
> **all six still stand** on the day this decision is ratified.** Named by ADR and by issue so that
> no reader mistakes this document for the last of them: **(1)** A8's reconciliation guarantee
> (ADR-0259), **(2)** A9's cancellation guarantee (ADR-0261) and **(3)** this decision's
> verification guarantee are each **ratified and not yet implemented**, and the gate asks for
> *"implemented and demonstrated"*; **(4)** ADR-0255 §13's first added prerequisite — the durable
> recovery of a resolved confirmation whose claim was refused — which ADR-0259 §5 takes the `DENY`
> half of and leaves the `ALLOW` half standing ([#2380](https://github.com/leonapivato/ai-assistant/issues/2380));
> **(5)** ADR-0255 §13's second — the evidence-to-claim window ([#2309](https://github.com/leonapivato/ai-assistant/issues/2309));
> and **(6)** ADR-0265 §6's containment for a wrongly minted intended action. **This decision adds
> no condition to that count and removes none**, and **no lane reads this ADR's ratification, or
> the merging of its L1, as the gate being met.**

**The gate is nearest to being met here and that is exactly when it is most worth restating.** All
three of its named guarantees are designed once this document ratifies, so the natural reading is
*one more merge and the gate is open* — and it is wrong twice over: **ratification is not
implementation**, none of the three has landed a line of code, and two of the six conditions are
assigned to lanes that have not started. ADR-0255 §13 anticipated exactly this arithmetic — *"a
deployment reading the three could wire a booking"* — and ADR-0265 §8 found a sixth by the same
reasoning. Counting them in the decision that completes the third is the cheapest place to be
right about it, and it is the last place the count can be stated before somebody acts on it.

### 8. The `core` surface, the wire, the stored shapes, and the export

> **Normative — what `core/types.py` gains.** **One model**, `AttemptReport`, with exactly two
> fields (§6); and **one field on `TurnOutcome`**, `attempt_report` (§6). **Nothing else** — **no
> new enumeration**, no new constant, no `Settings` field, and no widening of `Goal`,
> `GoalInterpretation`, `GoalElement`, `GoalAttempt`, `AttemptTransition`, `StepTransition`,
> `StepExecution`, `ExecutionState`, `ActionPlan`, `PlanStep`, `GoalEvidence` or `IntendedAction`.
> **`AttemptOutcome`, `GoalStatus`, `AttemptState`, `AttemptPhase` and `SkipReason` each gain no
> member.** **`core/errors.py` gains no class.**

> **Normative — what any Protocol gains: one strengthening and nothing else.**
> `PlanStore.set_goal_status` gains §5's single `→ ACHIEVED` limb, with its `planning`
> implementation. **No member is added to any Protocol, no argument is added to any existing
> member, `commit_attempt` gains no conjunct (§4), `commit_transition` gains none, and no new
> Protocol is created** — so **no new conformance suite and no new canonical fake is owed**, and
> the existing shared `PlanStore` conformance suite and the canonical fake in `ai_assistant.testing`
> gain the one obligation **in the same change that adds it** (`CONTRIBUTING.md` → "Adding a
> Protocol": *"The triad is what a Protocol **change** is measured against too"*), which is §12's
> arm 8. This is a **BREAKING** contract change under golden rule 5.

> **Normative — the breakage is for the wire rather than for a constructor, and no caller that
> enumerates a vocabulary is invalidated.** `attempt_report` defaults, so no existing construction
> stops validating, and **this decision adds no enum member for an exhaustive caller to miss**. What
> breaks is the peer contract: `TurnOutcome` is returned by promoted-surface methods, sets
> `extra="forbid"`, and `wire/codec.py` renders a model by `model_dump()` — so a newer hub emits an
> `attempt_report` member an older client refuses. That is **ADR-0124 §9's second limb** and
> **ADR-0178 §6 is the precedent for stating the bump in the deciding ADR**. **`PROTOCOL_VERSION`
> therefore moves by exactly one, in the lane that lands the `core` change**, together with
> `wire/envelope.py`'s log entry naming this ADR. **No integer is fixed here**: the figure is the
> tree's, and as a dated observation at `c92712c9` it reads **43**. **No compatibility shim,
> negotiation or lenient decode is added** — ADR-0084 §3's exact-match handshake is the mechanism.

> **Normative — `PlanExport.schema_version` does not move, and the ground is stated rather than
> assumed from a sibling.** ADR-0261 moved it because it added a **value** — an `AttemptOutcome`
> member — that a pre-decision reader refuses. **This decision adds no value to any vocabulary a
> stored record carries**: `AttemptOutcome`'s six and `GoalStatus`'s four are each ratified,
> present in every build since ADR-0014 and ADR-0249, and decodable by any reader of the current
> shape. A document written after this decision differs only in **which** of those already-legal
> values appear. **`AttemptReport` is carried by no stored record and by no export**, riding
> `TurnOutcome` alone. As dated observations `PlanExport.schema_version` reads `Literal[12]` and
> the plan store's `_SCHEMA_VERSION` reads **4**, and **neither moves**.

> **Normative — the plan store owes no migration, and nothing is repaired.** No stored row changes
> shape, no value is re-encoded, and **no lane sweeps, repairs or re-verifies a goal stored before
> this decision**: such a goal is `ACTIVE` with no criteria compared, which is true of it, and the
> next turn that engages it reaches `VERIFY` like any other. **No lane back-fills an
> `AttemptOutcome` onto an attempt this decision's phase did not end**, which would be a verdict
> nobody computed written onto a record nobody was looking at.

> **Normative — nothing else under `wire/` changes, and retention, deletion and export are
> untouched.** The connect exchange gains no member, no frame's encoding changes, no `FrameKind` or
> codec entry is registered, the promoted method set does not move, no gateway route is added, and
> the error mapping gains nothing. Every value this decision writes rides a `GoalAttempt` or a
> `Goal` the plan store already holds, so ADR-0014 §5's deletion and export obligations and
> ADR-0249 §12's `delete_goal` cascade bind as they stand: **no retention rule, sweep, expiry,
> second store or new durable record is minted.**

### 9. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward any
> of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling, and each
> carries the condition that fires it.

- **The goal-terminal ending of an authorisation.** The owner's ruling of 2026-09-14, whose own
  disposition is *"a short superseding ADR, one edge + one clause, sequenced after [ADR-0266]"* —
  the number elided for the reason ADR-0261 §8 gives, its lane being
  [#2376](https://github.com/leonapivato/ai-assistant/issues/2376). **Not this decision's**, and no
  clause here contradicts it: §5 supplies the act that makes a goal terminal, which is the
  antecedent that ruling reads, and **nothing here asserts that an authorisation survives it or
  ends with it**. The **uncertain-outcome** exception the ruling keeps open is preserved by §4's
  limb 3.
- **Retry across turns, reconciliation, idempotency keys, modify-before-replace, and how an
  `INDETERMINATE` step is resolved.** **A8**, as ADR-0255 §12 and ADR-0259 §10 book them. §4's limb
  3 keeps the uncertainty on the record and resolves nothing.
- **The quote, the charge record, and every carrier either would need.** **ADR-0266 §10's entry**,
  [#2387](https://github.com/leonapivato/ai-assistant/issues/2387), untouched: no type, no field,
  no store member, no Protocol, no expiry and no freshness rule. §2 states what verification does
  with one **when one exists** and §3 states what its absence costs. Fired by that decision.
- **A verification that calls a model.** **Not decided, and §2 states why not rather than leaving
  it to be inferred**: establishing a goal's achievement is the `ACHIEVED` write's prerequisite, and
  ADR-0249 §7 forbids a model clearing one. The one route by which a model's judgement reaches a
  criterion — an `INTERPRETATION`-basis `GoalEvidence` row through ADR-0252 §6's four tests —
  **already exists and is admitted**, so a decision wanting more owes ADR-0249 §7's bar an argument
  it does not have today. Fired by a decision that lifts that bar.
- **Whether a criterion may carry a typed check of its own**, so that verification need not depend
  on a plan having declared one. **Not decided**: §2 reads the declarations A5 landed and
  `GoalElement` gains nothing. **The cost is stated**: a goal whose planner declared no `when` and
  no `verifies` bearing on a criterion leaves it unestablished for ever, so such a goal never
  reaches `VERIFIED` and never reaches `ACHIEVED`. Fired by a measured case in which a real plan's
  declarations cannot express a real criterion, which would widen `GoalElement` and owe its own
  containment argument against ADR-0249 §7.
- **Distinguishing the four causes `SkipReason.UNMET_DEPENDENCY` carries.** ADR-0255 §2 gives all
  four one member, so §4's limb 1 cannot tell an unsatisfied `when` from an unresolvable
  `resolves`. **`SkipReason` gains no member here.** Fired by a surface that needs to tell a user
  which of the four, which would owe the vocabulary and the migration for it.
- **`GoalStatus.BLOCKED`'s producer.** **A3**, as ADR-0249 §4 and ADR-0250 §12 reserve it. Nothing
  here writes a `GoalStatus` but the `ACHIEVED` §5 writes.
- **An act that ends an attempt while leaving its goal open, and whether a store enforces *at most
  one live attempt per goal*.** **ADR-0261 §11's entries, untouched.** §5's conjunct refuses a
  **write** where a live attempt stands and refuses **no attempt on account of another**, so the
  two-opener state that decision names is neither introduced nor repaired here.
- **What a report says about a **cancelled** attempt.** **A9's** (ADR-0261 §3, §6). `attempt_report`
  is written by §4's act alone and by no other, so an attempt ADR-0261 §2's act ended carries none.
- **Whether `PlanStore` should answer the criteria comparison.** **Not decided**, and §4 states why
  it is `orchestration`'s. Fired by a measured cost this decision's own arms do not predict.
- **The retention, export or rendering of a per-criterion result.** **Not decided, and none is
  minted**: §2's three results are computed and discarded, exactly as ADR-0252 §6's four tests are.
  Fired by a surface that must show a user which criterion failed, which would owe a durable record
  with its own retention and export obligations.

### 10. Records owed on earlier ADRs, under ADR-0082 §1

**The test is ADR-0070 §1's, applied to the earlier ADR's text, and ADR-0082 §1 is where it is
stated in those words**: *"Would a reader holding only the earlier ADR now act differently, or read
one of its clauses more widely than it now holds?"*

**No ADR owes a record**, and the entries below are the whole of what this decision reaches, each
decided by that test.

- **ADR-0249 §4 and §5** — *no*, and the text is explicit about why. §4 says *"`GoalStatus.ACHIEVED`
  gets no producer **in this decision**"* and names A10 as its only producer; §5 says *"**Which
  member a given attempt earns is A10's**"*. Both are **statements about that decision's own
  change** and both stay true word for word: a reader holding only ADR-0249 builds the vocabulary,
  the validator and the absence, and acts **identically**. A booking **discharged** is not a clause
  made false (ADR-0261 §12's own words). §5's two-shape validator is **relied on** and is what §4
  of this decision reasons from; its *"no transition leaves a terminal member"*, its
  attempt-opened-only-by-a-user-act rule and its *paused* derivation each bind entire.
- **ADR-0249 §6** — *no*. The phase vocabulary, its order, its writer clause and its
  *"stamped and left in the same instant"* rule are each **relied on**; this decision gives `VERIFY`
  work and adds no phase, no member and no writer.
- **ADR-0249 §7** — *no*, and it is the clause §2 reasons **from**. Its asymmetry is applied
  unaltered and widened in nothing.
- **ADR-0250 §9** — *no*, for §5's conjunct. That section declares `set_goal_status` as the goal's
  only status-mutation route and fixes what it writes and what it refuses on a stale
  `expected_version`; **its one sentence about refusals is about which *member* may be written** —
  *"which acts may write which member is the caller's rule, not this member's"* — and §5 refuses no
  member: `ACHIEVED` stays writable, by this act and by it alone. What is added is a **consistency
  conjunct** between two records, which is the identical move ADR-0261 §2 made on the same member
  for `ABANDONED` and which **ADR-0261 §12 ruled owes ADR-0250 §9 no record**, on ADR-0255 §3's
  footing that such a thing is *"a strengthening of an existing member rather than a new one"*.
  §9's version advance, its stale refusal and its *"writes nothing else"* rule each stay true.
- **ADR-0250 §12** — *no*. Its *"`GoalStatus.ACHIEVED` likewise gains none, which is A10's"* is a
  statement about that decision and stays true; its three user acts that open an attempt, its
  `SUPERSEDED` producer and its abandonment clauses are untouched and are **relied on** by §5's
  residual.
- **ADR-0250 §5** — *no*, twice over. Its *"`TurnOutcome` gains **four** `None`-defaulting
  members"* stays true of a reader who builds those four — **ADR-0242 §9's own precedent for the
  identical move**, which recorded nothing — and its announcement rule is untouched, §6 stating a
  different fact on a different member. That ADR-0254 recorded against §5 for its own addition does
  not decide this, ADR-0082 §1 forbidding a record demanded *"on book-keeping grounds alone"*.
- **ADR-0170 §4, §5, §5a and §6** — *no*. §4's three `reply`-`None` shapes and its one
  `reply_degraded` shape are untouched (ADR-0242 §9's precedent again); §5's construction and its
  honest limit are **adopted whole** by §6; §5a's deterministic-local-summary rule is what §6's
  fixed statements already satisfy, the outcome being a member of a closed vocabulary this system
  owns; §6's render-beside-never-instead rule binds entire.
- **ADR-0198 §2** — *no*. A value is added to its enumeration without changing any value it fixes,
  which is ADR-0242 §9's own reading of the same move.
- **ADR-0252 §5, §6, §10 and §11** — *no*. §6's four tests are **called** rather than altered: no
  test is added, removed, reordered or reworded, and §2 states them by citation. §5's affirmative
  partition and its `EMPTY` clause bind entire and are why an unestablished criterion cannot be read
  as a met one. §10's *"what happens to an element when its row is marked: nothing"* is **obeyed**
  by §1. §11's digest is untouched. A reader holding only ADR-0252 builds the identical predicate.
- **ADR-0253 §2, §4 and §5** — *no*. §4's *"this is not the verification A10 lands"* is
  **fulfilled**: this decision is that verification, is stated over the goal's criteria, and reads
  `verifies` only as §2 of this document admits it — over one step's own output, as an operand and
  never as the comparison. §2's dependency rule and §5's `when` vocabulary are **relied on** and
  widened in nothing.
- **ADR-0255 §8, §12 and §13** — *no*. §8's fence is fulfilled in the same way; §12's A10 entry and
  §13's gate are **bookings discharged in part**, and §13's rule is carried verbatim by §7 with its
  two added prerequisites left standing and its count untouched.
- **ADR-0259 §3 and §4** — *no*. §4's acts 3 and 4 are **relied on** and are what §4's limb 3 keeps
  reachable; §3's reconciliation is neither widened nor narrowed, and nothing here resolves an
  `INDETERMINATE` step or reads one as establishing anything.
- **ADR-0261 §3, §6 and §11** — *no*. §3's limbs stay the rule for a **cancelled** attempt and §4
  of this decision reaches none; §6's in-flight statements are untouched; §11's booked question
  about `→ ACHIEVED` is **fired** by §5, which is a booking discharged rather than a clause made
  false, and §11's two-live-attempt entry is left exactly where it stands.
- **ADR-0265 §1, §6 and §8** — *no*. `IntendedAction` gains nothing, is read by nothing here, and
  §8's sixth gate condition is named by §7 and neither discharged nor moved.
- **ADR-0266 §1, §6 and §10** — *no*. §1's rule that a `criteria` element mints no coverage member
  is **relied on** and is what keeps the two decisions' subjects disjoint; §6's quote interface is
  cited and authored in nothing; §10's entry booking the verification phase's use of a quote is
  **fired**.
- **ADR-0016 §1 and §2, ADR-0014 §4 and §5, ADR-0148 §9, ADR-0242 §9, ADR-0244 §2 and §9** — *no*.
  Each is cited for a rule it already states and gains no clause; every sentence of each stays true.

### 11. The lane cut

**Three lanes, one subsystem each, and the first is the only one that moves a contract.**

- **L1 — `core` (with `wire`, `planning` and `testing`).** `AttemptReport`;
  `TurnOutcome.attempt_report` with the docstring naming this ADR; `PROTOCOL_VERSION` **+1** with
  its `wire/envelope.py` log entry; **§5's `→ ACHIEVED` conjunct on `PlanStore.set_goal_status`**
  with its `planning` implementation, the shared conformance suite case and the canonical fake in
  `ai_assistant.testing` (§12, arm 8). **This is the lane that moves the wire**, and it lands
  alone — golden rule 5, and `CONTRIBUTING.md` → "Adding a Protocol" for the suite and the fake
  riding the same change. It moves **no** stored-schema marker (§8).
- **L2 — `orchestration`.** The `VERIFY` phase: §3's rung over the attempt's claimed steps, §2's
  three results over the goal's criteria, §4's function, the `commit_attempt` that ends the attempt
  with its outcome, §5's `set_goal_status` with its single retry, `attempt_report`, and the two
  values §6 hands the composing stage. **It replaces the unconditional `AttemptOutcome.ANSWERED` at
  the three sites that write it today** — that value becoming §4's limb 6 rather than the only
  answer — and it adds no member, query, projection or collaborator to the engine. **It moves no
  contract**: every collaborator it touches is a concrete class.
- **L3 — `interfaces`.** §6's six fixed statements, on the CLI and on the browser — **both
  surfaces**, since a member rendered on one and not the other is the parity failure M4 recorded.
  **Thin, by golden rule 3**: it renders values L2 computed and derives none.

**Merge order is L1 → L2 → L3**, and each is one PR (the owner's *one lane, one PR* rule).

### 12. The arms this decision owes

**Nine.** Each is stated over the lane that owes it, and each runs against controlled fakes (§7).

1. **S1, end to end, unchanged in cost (L2).** *"What is two plus two?"*: a goal whose `criteria`
   are empty, one `Planner.plan` call and one composing call, no step claimed, and the attempt's
   stored row ending at `VERIFY`/`ENDED`/**`ANSWERED`** with the goal's status still **`ACTIVE`** —
   ADR-0249 §16's arm 1 asserted verbatim and still passing. **And the negative half**: no
   `set_goal_status` call is made, `attempt_report.outcome` is `ANSWERED` and `continues` is
   `False`.
2. **The criteria are read and the reply is not (L2).** A goal carrying one criterion that a stored
   `GoalEvidence` row satisfies under ADR-0252 §6 ends `VERIFIED` and the goal reaches `ACHIEVED`;
   **and the same goal with the row marked `SUPERSEDED`** ends not-`VERIFIED` and the goal stays
   `ACTIVE`, which is the arm that pins the comparison to §6's third test. **And the order**: the
   phase is driven with a composing stage that records whether it was entered, asserting it was
   **not** entered before the outcome was computed — the arm that fails against an implementation
   verifying over a composed reply.
3. **The three results, and R50 (L2).** One arm per result over one criterion: **met** (an operand
   establishes it), **unmet** (an operand establishes it does not hold), **unestablished** (no
   operand). **And prose is not an operand**: a goal whose criterion text is word-for-word satisfied
   by the composed reply, by a `GoalElement.text`, and by an `IntendedAction.intent`, and by no
   evidence row and no `verifies` — asserted **unestablished**, the attempt not `VERIFIED` and the
   goal not `ACHIEVED`.
4. **The ladder, asserted over the declarations and over the ordering (L2).** Rung 0, rung 1 and
   rung 2 each produced by the declaration that names it, over a claimed step; **and a step a plan
   declared and no walk claimed leaves the rung where it was**. **And the ordering trap
   explicitly**: a step whose tool is `side_effecting` with `reversibility=IRREVERSIBLE` and empty
   `discloses` reaches **rung 2** — the arm that fails against a lexicographic comparison, under
   which `"irreversible" > "reversible"` is `False`. **And `discloses` alone**: a `side_effecting`,
   `REVERSIBLE` tool with non-empty `discloses` reaches rung 2.
5. **§4's six limbs, and the order (L2).** One arm per member. **And one arm per precedence
   boundary**, because the single-member cases are all passed by an implementation testing the
   limbs in the wrong order: a met **and** an unmet criterion → `PARTIAL`, never `VERIFIED`; an
   unestablished criterion at **rung 2** → `UNCERTAIN`, and the **same state at rung 1** →
   `ANSWERED`; a skipped `UNMET_DEPENDENCY` step with no claim and every criterion unestablished →
   `CONDITION_PREVENTED`, never `ANSWERED`; and an unmet criterion beside a met one → `PARTIAL`,
   never `FAILED`.
6. **The attempt does not end, in all three limbs (L2).** A turn whose attempt is
   `AWAITING_AUTHORIZATION`; one whose execution holds an `INDETERMINATE` step; and one whose
   composition returned no text or came back degraded — **each writes no `AttemptOutcome`, leaves
   the attempt non-terminal, writes no `GoalStatus`, and returns `attempt_report` `None`**. **And
   the reconciliation route stays open**: after the `INDETERMINATE` case, ADR-0259 §4's act 3
   commits the attempt `EFFECT_UNRESOLVED` and its act 4 later commits it `RUNNING` — the arm that
   fails against an implementation that ended the attempt, and the one the owner's uncertain-outcome
   exception rests on.
7. **`ACHIEVED`'s producer and R53 (L2).** `set_goal_status(…, ACHIEVED)` is called **exactly** on
   limb 5 and on no other member, **after** the attempt's commit; and each of the other five ends
   an attempt while the goal's status is **unchanged** — the arm that pins R53's *"an attempt ending
   is not the same event as the task completing"*. **And the retry**: where a second attempt of the
   goal is opened between the act's read and its write, the status write is refused, the act
   re-reads once, the refusal repeats, **nothing is written**, the turn does not fail, and the
   attempt still reads `ENDED`/`VERIFIED` under an `ACTIVE` goal.
8. **The store conjunct (L1, shared suite).** Asserted against every conforming `PlanStore`: an
   `→ ACHIEVED` write is refused with `StaleExecutionError` and **writes nothing** where the goal
   has a non-terminal attempt — **including one opened after the caller read the goal** — and is
   accepted where every attempt is terminal and where the goal has no attempt at all.
   **`→ ABANDONED`, `→ BLOCKED` and `→ ACTIVE` are unaffected**, `→ ACTIVE` over a live attempt
   being ADR-0250 §13's reopen and asserted to still succeed. **And `open_attempt`'s closed-goal
   limb is asserted beside it** over an `ACHIEVED` goal, so the pair §5 calls exhaustive is shown
   to be.
9. **The report, on both surfaces (L2, L3).** Each of the six members produces its own fixed
   statement, on the CLI and in the browser, **beside the reply and never in place of it**;
   `continues` is `True` on exactly `PARTIAL`, `FAILED` and `UNCERTAIN` over an open goal and
   `False` on the other three; the composing stage's instruction **carries the offer** where
   `continues` is set; and **`attempt_report` is `None`** on ADR-0198 §1's restatement and on a
   routed operation. **The statements are asserted by their facts rather than their prose** —
   `ANSWERED`'s says nothing was verified, `UNCERTAIN`'s asserts no outcome and names
   `assistant goals` — and **no arm fixes the wording**, which is the lane's (§6).

**No arm demonstrates a real consequential integration**, which §7's gate forbids and M33's
walkthrough runs against a simulated booking service instead.

### 13. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**A new decision that supersedes nothing**, in whole or in part (§10), and a **stacked addition**
against every ADR it reaches. It is **marked** under ADR-0089 §2 as ADR-0257 §1 admits the label
and its §3 carries that grammar across the corpus, so the marked clauses are the whole of what it
obligates.

## Consequences

**What becomes easier.** `GoalStatus.ACHIEVED` gains its producer, so a completed objective stops
being indistinguishable from an unstarted one on every surface, and
`GoalInterpretation.criteria` gains its first reader. Five `AttemptOutcome` members gain
producers, so an attempt's stored row starts saying what the attempt produced rather than only
that it answered. R53's distinction becomes a property of
where two writes sit rather than a rule to remember. And ADR-0255 §13's gate acquires its third
guarantee, with §7 naming what still stands so that the arithmetic is on the record.

**What becomes harder.** A peer at the old `PROTOCOL_VERSION` refuses a peer at the new one, which
is intended and loud. A goal that reaches `ACHIEVED` can no longer open an attempt at all
(ADR-0261 §2), so a caller must reopen it first (ADR-0250 §13). A goal whose criteria no
declaration bears on never reaches `VERIFIED`, which is the cost §9 states rather than hides. And a
goal with an unresolved effect now deliberately **does not** end its attempt, so such a goal stays
open until A8's reconciliation reaches it — the owner's ruling, and a state a user sees on
`assistant goals` rather than one the system quietly closes.

**What would trigger revisiting this.** A measured case in which real plans' `when` and `verifies`
declarations cannot express a real goal's criteria would fire §9's `GoalElement` entry. The quote
decision (#2387) landing would give a charge criterion its operand and narrow §3's stated gap. And
a deployment in which `VERIFIED` is reached so rarely that `ANSWERED` is the effective terminal
member would say the declarations, and not this comparison, are where the work is missing.

## Alternatives considered

**Minting a per-criterion verdict enumeration — `ESTABLISHED`/`NOT_ESTABLISHED`/`AMBIGUOUS`, as
revision 0 of the fit report proposed.** Refused. The three results §2 needs are computed and
consumed inside one function, exactly as ADR-0252 §6's four tests are, and a `core` enumeration for
them would be a wire-carried, exported, durably-storable value with no consumer — *"a field with no
consumer is surface"* (ADR-0253 §6). Revision 1 of the fit report had already dropped it: its A10
row names *"the six-member report vocabulary"* and no verdict vocabulary at all.

**A `PlanStore.close_goal_achieved` mirroring ADR-0261 §2's `close_goal_abandoned`.** Refused, and
the asymmetry is the reason rather than the economy. That member exists because the answer R78 owes
— whether anything was outstanding — is a fact about the instant the goal closed, and because the
outcome of a cancelled attempt is a function of statuses **the store can read**. This decision's
outcome is a comparison against the goal's **criteria**, which would put ADR-0252 §6's four tests,
a clock and a plan's conditions inside a store write. §4's limb 3 removes the race a mirrored member
would have been bought to close, by refusing to end an attempt that has anything outstanding at all.

**Verification making a model call where the criteria are not otherwise checkable.** Refused (§2,
§9). It is the `ACHIEVED` write's prerequisite and ADR-0249 §7 forbids a model clearing one, and
#2096 item 8's principle is why the asymmetry runs one way — *"A model is a safe denier and an
unsafe allower."* A model that wrongly leaves a goal unverified costs a goal the user asks about
again; one that wrongly verifies it tells them a booking happened. The route that **is** open —
an `INTERPRETATION`-basis evidence row through ADR-0252 §6 — keeps the model's contribution a
verdict over one record and keeps the clearing in code.

**Verification performing the independent read itself at rung 2.** Refused after the owner's ruling
of 2026-09-13, which the fit report's §I.2 predates: *"Nothing checks on its own initiative."* A
read taken inside `VERIFY` would be an unplanned, unauthorised call made after the walk ended, on
a budget §3 would have had to invent, in a phase no park can interrupt. Making it a step of a later
attempt costs one turn and buys the whole of the phase machinery for free.

**Deriving `GoalStatus.ACHIEVED` from `AttemptOutcome.VERIFIED` at read time.** Refused. ADR-0249
§4 rules that *"An attempt reaching a terminal state **does not** move the goal's status"*, and a
derived status would be a second authority that can disagree with the stored one — ADR-0249 §5's
own argument against *paused* as a status member. The two writes are two facts and §5 takes both in
one act because one comparison decided both.

**Reading `risk_level` into the ladder.** Refused (§3). Risk is what a policy thresholds to decide
whether to **ask**; reversibility, disclosure and the binding are what describe what an act **did**.
One scale answering two questions is how a deployment that tightened its approval threshold would
silently change what counts as verified.

**Announcing the outcome through `GoalEngagement` rather than a member of its own.** Refused.
ADR-0250 §5's four facets are *what this turn did with the goal it engaged* and its announcement
rule is about resumptions and revisions; what an attempt produced is a different fact, owed on
turns §5's rule is silent about and absent on turns it fires on. ADR-0244 §9's rule — one
`None`-defaulting member per fact — is the ratified shape, and collapsing the two would make one
field mean two things a client must discriminate before rendering either.

**Putting the offer to continue on the surface rather than in the reply.** Refused (§6). Its whole
purpose is that a bare *"yes"* on the next turn binds by reply reference (ADR-0250 §3), and a
sentence an adapter printed is not part of what was said — it reaches neither the browser's
transcript nor the spoken channel, where ADR-0200 §4 makes `spoken` the rendering of
`outcome.reply` *"and of nothing else"*.
