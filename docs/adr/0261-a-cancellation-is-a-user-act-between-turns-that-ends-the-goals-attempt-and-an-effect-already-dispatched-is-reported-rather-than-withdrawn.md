# 261. A cancellation is a user act between turns that ends the goal's attempt, the claim it races is decided by the store, and an effect already dispatched is reported rather than withdrawn

- Status: Proposed
- Date: 2026-09-15
- **Partially supersedes** [ADR-0249](0249-the-goal-carries-its-interpretation-the-attempt-carries-the-phase-and-the-planner-returns-its-understanding.md)
  — **one scope, stated in a count and a division, both of §5, and §12 shows the working.**
  **§5's `AttemptOutcome` closure**: *"a `StrEnum` valued by lower-cased member name and **closed
  at exactly six members**: `VERIFIED`, `CONDITION_PREVENTED`, `PARTIAL`, `FAILED`, `UNCERTAIN`
  and `ANSWERED`"* becomes **seven**, gaining `CANCELLED` — *the attempt produced nothing and
  nothing of it is outstanding* — because §5's own validator requires an `AttemptOutcome` on
  every terminal state, `CANCELLED` is one of its two terminal states, and none of the six is
  true of an attempt a user ended before it produced anything. A reader holding only §5 cannot
  construct the `GoalAttempt` this decision's act writes. **And §5's division of which member an
  attempt earns**, together with §13's *"which `AttemptOutcome` member an attempt earns, … A10"*:
  the division becomes *every attempt but a cancelled one*. A10 keeps every member for every
  attempt it can reach, and it reaches no cancelled attempt — §5's own *"no transition leaves a
  terminal member"* is what makes that true rather than a courtesy. **That one scope, and nothing
  else in this ADR**: §5's *"The vocabulary is added to and never renamed"* is **exercised rather
  than superseded** and every one of the six keeps its name, its value and its meaning; §5's
  two-shape validator, its terminal-member closure at `CANCELLED` and `ENDED`, its
  no-transition-leaves-a-terminal-member rule, its `ANSWERED`-is-not-a-weaker-`VERIFIED` clause,
  its attempt-is-opened-only-by-a-user-act rule, its no-interpretation-on-an-attempt rule, its
  `AttemptEffort` clauses and its *paused* derivation all bind **entire** and are the grounds
  this decision reasons from; §8's `targets_revision` clauses and its `commit_transition` claim
  condition are **relied on** and extended by nothing; §4's *"An attempt reaching a terminal state
  **does not** move the goal's status"* binds entire and is obeyed in the direction it is stated
  (§2); §12's append-only reference tuples, its commands-not-snapshots rule and its
  compare-and-swap discipline are untouched; and §§1-3, §§6-7, §§9-11 and §§13-17 stand entire.
- **Partially supersedes** [ADR-0250](0250-a-turn-finds-its-goal-before-it-plans-and-a-material-ambiguity-becomes-one-durable-question-bound-to-that-goal.md)
  — **two scopes, and §12 shows the working for both.**
  **§12's two abandonment clauses, and only those two.** Its *"and does nothing else"* sentence —
  *"**Abandoning writes the goal's status through `PlanStore.set_goal_status` (§9) and settles its
  open question `WITHDRAWN`, and does nothing else.** It does **not** move the attempt's state,
  does not write an `AttemptOutcome`"* — becomes false: the act **does** move the attempt's state
  and **does** write an `AttemptOutcome`, which is the half that same clause books here by name,
  *"what becomes of an attempt on an abandoned goal is A9's"*. And its `GoalAbandonment` closure —
  *"**closed at exactly three members**: `ABANDONED`, `ALREADY_CLOSED` and `NO_SUCH_GOAL`"* —
  becomes **four**, gaining `ABANDONED_EFFECT_IN_FLIGHT`, so that the one act reports which of the
  two things it did, on ADR-0244 §11's own construction. **The remainder of that clause binds
  verbatim and is what this decision builds on**: the act *"does not end an execution"* (§4 — no
  `StepTransition` is written), an abandoned goal still *"leaves the open set … so nothing
  associates to it and nothing plans for it"*, the act is still the **only** writer of
  `ABANDONED`, `GoalStatus.BLOCKED` still gains no producer here, `ACHIEVED` still gains none, and
  §12's every other clause — the settled-not-inferred expiry, the still-paused-and-still-resumable
  rule, `withdraw_clarification` and `ClarificationWithdrawal`, `SUPERSEDED`'s one producer, the
  no-terminal-disposition-from-silence rule, the **three** user acts that open an attempt and the
  new-attempt-at-`UNDERSTAND` rule — binds **entire**.
  **And §15's `GoalSummary` field enumeration, in the field list alone**: *"a frozen model with
  `extra="forbid"` whose fields are exactly: `id` … `paused`, a `bool`; `last_engaged_at` … and
  `clarification`"* gains **`effect_in_flight`**, a `bool` defaulting to `False`, so a reader
  holding only §15 authors a listing that cannot say an effect of a goal is outstanding and R78's
  *"any completed or uncertain in-flight effect is reported accurately"* has no carrier on the one
  surface a user reads to find out where a goal stands. **§15's every other clause binds entire**,
  and the new member is added **under** them: the *"carries no attempt id, no revision number, no
  element, no ground, no evidence reference and no plan"* rule is untouched and satisfied — a
  `bool` is none of those — and `effect_in_flight` takes `paused`'s own clause one fact over,
  **computed and never stored**, computed by the engine, and derived by no adapter.
- **No other ADR is superseded in whole or in part**, and §12 says why none of the further
  ADRs this decision reaches owes a record.

## Context

### Where this comes from

This is **A9** of the six-phase task lifecycle design (#2255). Its row in the fit report is
exact about the subject — *"Cancellation at the claim boundary: which write wins, what is in
flight, and the four tests"* — and its next cell about the inheritance: *"Generalises ADR-0244
§11, whose §20 hands the general case to #2173 L7 by name."* Its lane-table row names the scope —
*"The task-revision compare-and-swap, the irreversibility boundary at the claim, the
post-cancellation prohibition, and authority invalidation on correction"* — and, in its own cell,
the requirements: **R76–R79**.

The four requirements, quoted:

| | |
|---|---|
| **R76** | A user correction invalidates affected pending work **and authority** before dispatch. |
| **R77** | The boundary after which an in-flight effect cannot be withdrawn is defined. |
| **R78** | After an acknowledged cancellation no later action begins, and any completed or uncertain in-flight effect is reported accurately. |
| **R79** | One consistent rule governs a user edit or revocation racing validation or dispatch: an old plan or approval never executes against a newer interpretation merely because it finished validating first. |

**ADR-0255 §12 books three things here, verbatim**, and this decision takes all three:

- *"**Cancellation's semantics** — what a user's cancellation is, which write wins against a
  dispatch, what an `AttemptTransition` to `CANCELLED` requires, and **revision 1 §H.4's tests 1,
  2 and 4**. **A9.** §3 lands the conjunct a cancellation bites through and test 3 that pins it;
  everything about the act that ends an attempt is A9's."*
- *"**What a refused claim causes at the user's surface** — the report, the replan, whether the
  turn composes without acting. **A9**, which is ADR-0249 §13's own division."*
- §11's two cases that return no `StepDisposition` — a driver skip and a refused claim — of which
  *"what they cause at the user's surface is **A9's**"*.

**ADR-0253 §11 books the same subject**: *"**Cancellation at the claim boundary**, and which write
wins against a dispatch this decision's conditions made eligible. **A9.**"* **ADR-0250 §12** books
the other half: *"what becomes of an attempt on an abandoned goal is **A9's**"*. And **ADR-0244
§20** defers the general case — *"Cancelling a dispatch running in another process. §11's act
reaches the process that received it. **What fires it:** #2173's L7 obligation"* — which this
decision does not take either (§11).

**Revision 1 §H.4's four tests**, quoted whole because they are the acceptance of this decision:

> 1. **Interleaved cancel before claim.** A cancellation commits between the driver's decision to
>    run a step and its claim; assert that the claim is refused, that the `ToolInvoker` was
>    **never entered** (a fake that records entry), that the step is `PENDING` at its stored
>    version, and that the cancellation reports the withdrawal.
> 2. **Interleaved cancel after claim.** The claim commits first; assert that the step's terminal
>    status is one of `SUCCEEDED`/`FAILED`/`INDETERMINATE`, **never `SKIPPED`**, that
>    `approval_ref` is set, and that the cancellation reports an in-flight effect.
> 3. **A store-level invariant, in the shared `PlanStore` conformance suite** so both
>    implementations carry it: **no `→ RUNNING` transition is ever accepted whose goal revision is
>    not the stored one.**
> 4. **An exhaustive two-writer interleaving test** over the cancel/claim pair asserting that in
>    every ordering **exactly one** of {the step was claimed, the cancellation was effective}
>    holds — never both, never neither.

**Test 3 is already landed and is relied on rather than re-decided.** Its revision half is
ADR-0249 §8's `commit_transition` conjunct — *"accepts a **`→ RUNNING`** claim only where the plan
the execution runs carries a `targets_revision` **equal to the current `revision` of that plan's
goal**"* — and its attempt half is ADR-0255 §3's, whose §11 puts both in the shared suite: *"The
existing `PlanStore` conformance suite and the canonical fake in `ai_assistant.testing` gain the
new obligation in the same change that adds it"*. **Tests 1, 2 and 4 are this decision's** (§14).

### The sequencing ruling, which binds every clause below

The owner's ruling of 2026-09-13, recorded for every lane of this design: *"Finish the six-phase
workflow … and demonstrate it end to end **using the existing interaction model** (subsequent
turns; pauses for clarification or approval). **Live message queuing, mid-run steering and general
interruption are a separate follow-up.**"* Its dispatch consequence names this decision: *"A9
(ADR-0261) is cancellation as a between-turns act at the claim boundary"*.

So **a cancellation here is an act between turns** — one that meets a claim the next walk would
make, or an effect a previous turn left in flight. It is **not** a message that reaches a running
turn. *"Existing cancellation behaviour and interruption accounting are preserved"*: **ADR-0060
§1's propagation rule, ADR-0029 §4's classification of a cancelled invocation, ADR-0034 §1's
pre-invocation window and ADR-0244 §11's `cancel_read` bind unchanged**, and nothing below adds a
clause to any of them. And *"checkpoints for future steering are left, not built"* — §11 names
where a live cancellation would enter and states nothing more.

### What the tree holds today, read rather than assumed, at `origin/main` `8dbfddf0`

- **`AttemptState`** is the seven members ADR-0249 §5 fixed, with `TERMINAL_ATTEMPT_STATES` the
  frozen set `{CANCELLED, ENDED}`. **`GoalAttempt`'s validator** admits exactly two shapes: a
  terminal `state` with both `outcome` and `ended_at` present, a non-terminal one with both
  absent. **`AttemptTransition`** is the only route that mutates an attempt.
- **`AssistantEngine.abandon_goal`** exists and is implemented: it reads the goal, answers
  `NO_SUCH_GOAL` or `ALREADY_CLOSED`, settles the open question `WITHDRAWN`, writes
  `GoalStatus.ABANDONED` through `set_goal_status` under the goal's `version`, and settles the
  open question a second time over the window the goal's compare-and-swap does not cover. **It
  touches no attempt**, exactly as ADR-0250 §12 rules and books.
- **`AssistantEngine.cancel_read`** exists and is ADR-0244 §11's act for one operation kind.
- **`GoalSummary`** carries `id`, `outcome`, `status`, `paused`, `last_engaged_at` and
  `clarification`; `paused` is computed by the engine.
- **`StaleExecutionError` is a subclass of `PlanningError`** (`core/errors.py`), so the refusals
  ADR-0249 §8 and ADR-0255 §3 raise are one family with two classes.
- As dated observations: `wire/envelope.py`'s `PROTOCOL_VERSION` reads **43**;
  `PlanExport.schema_version` reads `Literal[12]`; the plan store's `_SCHEMA_VERSION` reads **4**.

### The gap this closes, stated as the failure the corpus has today

**There is no act that ends an attempt.** `AttemptState.CANCELLED` is a ratified member with **no
producer**: nothing in the tree writes it, `abandon_goal` is forbidden from writing it by the very
clause that books it here, and `AttemptOutcome` has no member an implementation could put beside
it. So a user who gives up on a goal today leaves a `RUNNING` attempt on an `ABANDONED` goal —
and ADR-0255 §3's claim conjunct, which is the whole mechanism by which a cancellation bites,
**never fires**, because the state it fires on is unreachable. R78's *"after an acknowledged
cancellation no later action begins"* is unmet not by a race but by there being nothing to
acknowledge.

**And nothing tells the user what happened.** ADR-0255 §11 leaves both the refused claim and the
driver skip carrying nothing on `TurnOutcome`; `GoalSummary` cannot say an effect of a goal is
outstanding; and `GoalAbandonment` cannot say that the goal it closed had one in flight. R77's
boundary is defined in the corpus (ADR-0148 §9, ADR-0014 §4) and **nothing renders it**.

### What this decision is not allowed to settle

Golden rule 5's Protocol change is stated and argued here and implemented by the lanes §13 cuts,
and nothing else. This decision **takes no entry ADR-0255 §12 books elsewhere** — parallel steps,
a background drive, a second `CONFIRM`, retry, reconciliation, idempotency keys and
modify-before-replace stay A8's and their own. It **designs no replay** of a parked `ALLOW`
(§9, #2380). It **does not write the authorisation-lifetime ending** the owner ruled on
2026-09-14, which is a later ADR's (§8, §11).

## Decision

### 1. What a cancellation is: two shapes, and the corpus already holds a write for each

> **Normative.** **A cancellation is a user act, recorded durably, and it takes exactly one of two
> shapes.** **(a) Cancelling the goal**: the user gives the objective up, which is
> `AssistantEngine.abandon_goal` (ADR-0250 §12) as §2 completes it. **(b) Cancelling a course of
> action while keeping the goal**: the user replaces what they asked for, which is a **correction**
> recorded as a new `GoalInterpretation` revision (ADR-0249 §1, §3) with ADR-0254 §5's superseding
> authority record. **There is no third shape, no new `AssistantEngine` member, no new durable
> record and no cancellation queue.**

> **Normative — shape (b) is not this decision's to build, and it is named here so that a reader
> does not look for one.** Its bite at the claim is ADR-0249 §8's revision conjunct, its authority
> is ADR-0254 §5's, and **this decision adds nothing to either**: no clause below revises an
> interpretation, writes an `Authorization`, or reads one. §8 states which of R76 and R79 that
> discharges and what is left.

> **Normative — what a cancellation is *not*, and every one of these binds unchanged.** It is
> **not** a message delivered into a running turn; it is **not** `asyncio` cancellation of a call
> in flight (ADR-0060 §1, which *"is delivered onward, never absorbed"*, and ADR-0029 §4, whose
> outcome for a cancelled side-effecting non-`NATURAL` invocation is `INDETERMINATE`); and it is
> **not** ADR-0244 §11's `cancel_read`, which is that operation kind's own act and keeps its three
> members, its atomicity and its scope. **No lane reads this decision as widening, narrowing or
> re-deciding any of the three**, and no clause below is cited toward a deadline, an interruption
> accounting rule or a `ToolInvoker` argument.

> **Normative — cancellation is abandonment of the goal, and the attempt ends because the goal
> did.** The act is stated over the **goal** and never over an attempt, so there is **no act that
> ends an attempt while leaving its goal open** and no lane adds one. ADR-0249 §4's *"An attempt
> reaching a terminal state **does not** move the goal's status"* binds **entire** and is obeyed
> in the direction it is stated: the user's act moves the goal, and the attempt follows from that
> one act — nothing infers a goal's status from an attempt's state anywhere in §2.

**Two shapes rather than one, because the user's two sentences mean different things and the
corpus already separates them.** *"Forget the campsite"* gives up the objective; *"not that one,
find another"* keeps it and replaces what it means. ADR-0244 §11 draws exactly this line for a
parked question — *"a denial is the user answering *no* and is a ruling; a cancellation is the
user withdrawing the question and is not one"* — and the mistake a single act would make is the
same in both directions: an abandonment recorded for a correction discards a goal the user still
wants, and a correction recorded for an abandonment leaves an open goal nobody will work.

**And neither shape needs a new record, which is the whole economy of this decision.** Shape (a)
has `abandon_goal` and the two terminal `AttemptState` members; shape (b) has the interpretation
sequence and ADR-0254 §5. What is missing is one commit, one enum member and the report — not a
mechanism.

### 2. The act: `abandon_goal` ends the goal's current attempt, and the attempt is written first

> **Normative.** **`AssistantEngine.abandon_goal` gains one write and keeps every other.** On the
> path that reaches `ABANDONED` — and on no other — it commits the goal's **current attempt**,
> where that attempt is in a non-terminal `AttemptState`, to **`AttemptState.CANCELLED`** through
> `PlanStore.commit_attempt`, in **one** `AttemptTransition` carrying `to_state=CANCELLED`, the
> `outcome` §3 fixes, `ended_at` at the engine's clock reading, and the `expected_version` the
> attempt was read at. **Where the goal has no attempt, or its current attempt is already terminal,
> no attempt write is made and the act is otherwise unchanged.** The goal's *current* attempt is
> the most recently opened one, which is the value ADR-0249 §5's *paused* derivation and ADR-0250
> §15's `paused` already read.

> **Normative — the attempt commit is taken first, before the question settlement and before the
> status write, and the order is the fail-closed one rather than a preference.** A call that ends
> between the two writes leaves, **in this order**, an `ACTIVE` goal whose current attempt is
> `CANCELLED` — from which **no claim can land**, because ADR-0255 §3's state limb refuses every
> `→ RUNNING` transition naming a terminal attempt, and from which the user's next turn opens a
> new attempt by ADR-0250 §12's third act. **In the reverse order it would leave an `ABANDONED`
> goal whose attempt is still `RUNNING`** — a goal nobody is pursuing under which a claim still
> lands and a step still dispatches, which is R78's *"no later action begins"* broken by exactly
> the partial write the ordering is chosen to make harmless. **No lane reverses it**, and the
> residual the chosen order leaves is repaired by the ordinary act, not by a sweep.

> **Normative — the act writes no `StepTransition`, moves no step and ends no execution.** It
> disposes of no `PENDING` step, writes no `SkipReason`, commits nothing to `SKIPPED`,
> `SUPERSEDED` or any other status, and does not call `StepRunner`, `StepExecutor` or
> `ToolInvoker`. ADR-0250 §12's *"does not end an execution and does not cancel anything in
> flight"* binds **verbatim** for every one of those. **A step a claim already carried keeps the
> status its own disposal gives it**, which is §H.4 test 2's *"never `SKIPPED`"* made a property
> of there being no writer rather than a rule a driver is trusted to keep.

> **Normative — the act takes no new store member, and `PlanStore` gains exactly one refusal.**
> `commit_attempt` and `set_goal_status` are the members ADR-0249 §12 and ADR-0250 §9 already
> landed; **`PlanStore` gains no member and no argument**, and **`commit_transition` gains no
> conjunct** (§4). What it gains is §3's outcome conjunct on `commit_attempt` — one refusal on one
> member, on ADR-0255 §3's own footing that such a thing is **a strengthening of an existing
> member rather than a new one**.

> **Normative — a `StaleExecutionError` from `commit_attempt` is re-read and retried **once**,
> and the handling is one rule over both of its causes rather than two.** The act re-reads the
> attempt and its executions, recomputes §3's outcome, and commits again; **a second
> `StaleExecutionError` propagates** and the act ends there. **No lane retries a third time, loops,
> translates the refusal into a `NOTHING_TO_CANCEL`-shaped member, or reports an abandonment that
> did not land** — and where the re-read finds the attempt already terminal, the act takes no
> attempt write at all and proceeds, which is this section's own rule.

**One rule rather than two, because the caller cannot tell the causes apart and does not need to.**
`commit_attempt` can refuse for a lost `expected_version` (ADR-0014 §5) or for §3's outcome
conjunct, and **both raise `StaleExecutionError` on purpose**: the class means *"the stored
execution has advanced since the caller read it"* and directs a caller to **re-read and retry**
(`core/errors.py`), which is the correct response to either. So no second class is minted, no
member distinguishes them, and **the bound is what keeps the shared handling safe** — one
recomputation covers the single store round-trip the window is, and an unbounded loop would spin
against a concurrent driver for as long as it kept claiming. **A distinct typed refusal is
refused by name** (Alternatives): the wire encodes an error as `type(exc).__name__` and rebuilds
it by that name (ADR-0085 §10a), so a new class is a value a client at the old version cannot
reconstruct, bought to distinguish two cases with one correct response.

> **Normative — `set_goal_status`'s own refusal is unchanged.** A `StaleExecutionError` from the
> status write propagates exactly as it does today (ADR-0250 §12) and **is not retried**: by then
> the attempt is terminal, nothing can claim under it, and the residual is the one §2's ordering
> already rules harmless.

**Why `abandon_goal` and not a new operation.** ADR-0250 §12 makes it *"the only thing in this
system that writes `ABANDONED`"* and, in the same clause, books its missing half here by name.
A second act would be a second writer of the user's *I give up* — two surfaces, two audit shapes,
and a question at every call site about which one the user performed. The act already exists, is
already on the promoted surface, already has a CLI command, and already reads the goal it needs;
what it lacked was the attempt.

**The window the second question-settlement narrows is not widened by the new write**, because the
attempt commit precedes both settlements and moves nothing the question path reads. ADR-0250 §12's
own residual — a question admitted onto a goal the store already holds as `ABANDONED` — is
untouched, and the `PlanStore` refusal that would close it stays that decision's issue and not
this one's.

### 3. What an `AttemptTransition` to `CANCELLED` requires: four limbs, and one new member

> **Normative.** **`AttemptOutcome` gains one member and closes at seven**: **`CANCELLED`**, valued
> `"cancelled"`, meaning **no step of the attempt succeeded, none failed, and none is
> outstanding** — the attempt produced nothing. Every
> existing member keeps its name, its value and its meaning. ADR-0249 §5's *"The vocabulary is
> added to and never renamed"* is what admits it, and the vocabulary is **not** reopened: no
> implementation, setting or later lane adds an eighth without the ADR that decides it.

> **Normative — the outcome a cancelled attempt earns, decided by what its own executions hold, in
> this order and over nothing else.** At the instant of the write, over every step of every
> execution `GoalAttempt.execution_ids` names:
>
> 1. **`UNCERTAIN`** where any such step stands **`INDETERMINATE`** or **`RUNNING`** — the same two
>    statuses ADR-0259 §4's act 4 reads for the same question, so *outstanding* means one thing in
>    the corpus and not two.
> 2. Otherwise **`PARTIAL`** where any such step stands **`SUCCEEDED`** — part of what was asked
>    was done and nothing is outstanding.
> 3. Otherwise **`FAILED`** where any such step stands **`FAILED`** — the attempt reached a step
>    that failed and produced nothing else. ADR-0255 §2 makes this reachable rather than
>    hypothetical: *"a `FAILED` step does not stop the walk"*, so a walk can pass over one and the
>    user can then cancel an attempt whose only disposal is a failure.
> 4. Otherwise **`CANCELLED`**.
>
> **The four limbs are total over `StepStatus`'s seven members and no input is left undecided**:
> `PENDING`, `AWAITING_APPROVAL` and `SKIPPED` reach limb 4, which is the state `CANCELLED`
> describes — nothing succeeded, nothing failed, nothing is outstanding. **No fifth limb, ordering
> or override is added.**

> **Normative — the limbs are evaluated inside the same indivisible step as the write, because a
> caller's read of them is not ordered against a claim.** **`PlanStore.commit_attempt` accepts an
> `AttemptTransition` whose `to_state` is `CANCELLED` only where its `outcome` is the member the
> four limbs above yield over that attempt's executions read inside that same step**, and refuses
> every other with **`StaleExecutionError`**. **The caller re-reads and recomputes**, which is
> exactly what that class means and directs (`core/errors.py`, ADR-0014 §5) — and is why this
> refusal takes the stale class where ADR-0255 §3's permanent ones do not.

**Why the store and not the engine, in the words the corpus already uses for it.** A claim writes
an `ExecutionState` and **does not advance `GoalAttempt.version`**, so the attempt's own
compare-and-swap cannot see one land: an engine that read the steps, chose `CANCELLED`, and then
committed would record *nothing was outstanding* about a step a concurrent claim had just taken
to `RUNNING` — a read-then-write with the time-of-check-to-time-of-use gap revision 1 §H.1
identifies and ADR-0014 §5 assigns to the store, *"because the store is the only place with a
total order over writes."* The construction is `commit_transition`'s own, one member over, and
**it puts no policy in the store that the caller does not also compute**: the caller proposes the
outcome and the store refuses a wrong one, which is `expected_version`'s shape and
`approval_ref`'s.

> **Normative — the conjunct binds on `to_state=CANCELLED` and on nothing else.** Every other
> `AttemptTransition` is untouched — `ENDED`, the phase stamps, the effort counters and the three
> `add_*` appends each behave exactly as ADR-0249 §12 rules — and **no lane reads this conjunct as
> a general outcome check**. Which member a non-cancelled attempt earns stays A10's (§11).

> **Normative — the outcome is not a second record of the state, and the rule above is what makes
> that true.** `AttemptState.CANCELLED` says **why the attempt stopped**; `AttemptOutcome` says
> **what it produced**, and the four limbs make it carry a fact the state does not — whether
> anything landed, and whether anything is outstanding. **No consumer derives either from the
> other**, which is ADR-0259 §4's *"No status of any record is computed from another record by any
> consumer"* binding one model over, and **no lane reads `outcome == CANCELLED` as the test for
> whether an attempt was cancelled**; the state is that test.

> **Normative — the read is bounded and is the act's own.** The engine reads the attempt's
> executions through the `PlanStore` it already holds, by `execution_ids` and `get_execution`, and
> reads nothing else for this. **`PlanStore` gains no query, no projection and no member**, and
> **no collaborator is added to the engine** (ADR-0058).

**Why a seventh member rather than one of the six.** ADR-0249 §5's validator makes an
`AttemptOutcome` **compulsory** on a terminal state, so the write cannot be made without choosing
one, and an attempt a user ended before it produced anything is none of them. `FAILED` would report
a failure the system did not have; `CONDITION_PREVENTED` would name a condition nobody evaluated;
`PARTIAL` would claim part of the work was done; `ANSWERED` asserts *"that a reply exists, that no
step failed and that no condition blocked"*, which asserts three things this attempt does not
support; `VERIFIED` and `UNCERTAIN` are plainly false. **Choosing the least wrong of six is the
guess ADR-0014 §4 refuses in its own domain** — *"Automatically retrying it would risk acting
twice; automatically failing it would risk reporting a completed action as failed"* — and the
corpus's own answer to a vocabulary with a missing member is to add one with a record, which is
what ADR-0251 §7 did to `StopReason` *"in that count alone"*.

**And the limbs rather than a flat `CANCELLED`, because a flat member would carry nothing.** With
the state already saying *cancelled*, an outcome that always said the same word would be the *two
records of one fact* ADR-0249 §1 refuses, applying ADR-0244 §2's argument *"without change"* — a
field a reader could delete without
losing anything. The four limbs make the pair informative: `(CANCELLED, UNCERTAIN)` is the goal
whose fate the user must still be told about, `(CANCELLED, PARTIAL)` is the goal something was
done for, and `(CANCELLED, CANCELLED)` is the goal nothing happened on.

### 4. Which write wins: the store decides it, and this decision adds no conjunct

> **Normative.** **This decision adds no claim condition, no field to `StepTransition`, no
> caller-supplied value and no check in the driver.** The cancellation bites through **conjuncts
> that are already ratified**: ADR-0255 §3's attempt conjunct, whose state limb *"refuses a claim
> under an attempt whose `state` is `CANCELLED` or `ENDED`"*, and ADR-0249 §8's revision conjunct
> for shape (b). **No lane implements a cancellation check anywhere but in the writes §2 makes.**

> **Normative — the ordering rule, stated over the store's total order and not over a driver.**
> The cancellation's `commit_attempt` and the claim's `commit_transition` are two writes to one
> store, and ADR-0014 §5's ground decides between them: *"it belongs to the store because the store
> is the only place with a total order over writes."* The two cases are therefore exhaustive and
> exclusive:
>
> - **The cancellation lands first.** The claim's attempt conjunct refuses, on the non-stale
>   `PlanningError` ADR-0255 §3 fixes; **nothing is invoked**; the step keeps the status and the
>   stored version it was entered at; and §7 governs what the turn says.
> - **The claim lands first.** The claim stands, the step is `RUNNING` with its `approval_ref`
>   set, and its outcome is one of the step's own — **never `SKIPPED`**, because §2 writes no step
>   status at all. The cancellation reports an effect in flight (§6).

> **Normative — §H.4 test 4's invariant is stated over **one claim**, and that reading is fixed
> here so the test and the claim-first case agree.** The invariant is: for the claim in question,
> exactly one of **{this claim landed, this claim was refused by the cancellation}** holds — never
> both, never neither. **It is not a statement that a cancellation and a claim cannot both be
> effective**: the claim-first case above is precisely one in which the claim landed *and* the
> cancellation then ended the attempt, which is revision 1 §H.2's own answer — *"The claim stands
> and the action starts. The cancellation answers that there was something in flight"*. A reading
> under which no conforming implementation could satisfy both is refused, and **no lane implements
> test 4 as a mutual exclusion of the two acts.**

> **Normative — the property is the store's to keep and not `orchestration`'s.**
> `commit_transition` reads the attempt *"inside the same indivisible step as the claim"* (ADR-0255
> §3) and `commit_attempt` writes it under its own compare-and-swap, so a conforming `PlanStore`
> **serialises the two**: there is no interleaving in which one claim both lands and is refused,
> and none in which it does neither. **§14's arm 3 is where a conforming implementation shows
> it.**

> **Normative — *"check revision → user cancels → action starts" cannot occur*, and the ground is
> that there is no check.** Revision 1 §H.2's finding binds as written: the real sequence is
> *claim → cancel* or *cancel → claim*. **No lane closes this window with a read of the goal, the
> attempt or the interpretation taken outside the claim**, which is ADR-0249 §8's clause —
> *"there is **no separate read** on which a decision is taken"* — and ADR-0255 §3's, stated one
> value over: *"There is **no separate read of the attempt on which a decision is taken**"*.

**This is where the decision is smallest and where it would most easily have grown.** Revision 1
§H.1 proposed carrying the goal revision and the attempt id on `StepTransition`; ADR-0255 §3 took
the attempt half and **refused the revision half by name**, because *"adding a caller-supplied
revision would put the decision back in the caller's hands and re-open the gap"*. With both
conjuncts landed, the cancellation needs nothing at the claim: it needs only to be a write the
conjunct already tests, and §2 makes it one. **A decision that added a third conjunct here would
be adding a second authority for a fact the store already holds**, and would owe ADR-0255 §3's own
argument against itself.

### 5. The post-cancellation prohibition, and how a later turn proceeds

> **Normative — nothing of the cancelled attempt is dispatched afterwards, and three ratified
> clauses are what make it hold rather than one new rule.** Every subsequent claim of a step of any
> execution the cancelled attempt opened **names that attempt** — `StepTransition.attempt_id` is
> required on a `→ RUNNING` transition and the store checks the execution's membership — so
> ADR-0255 §3's state limb refuses it permanently. **Naming a different attempt does not evade
> it**: that section makes ownership exclusive — *"an execution belongs to exactly one attempt"* —
> and refuses `commit_attempt` and `open_attempt` writes that would give a live attempt a cancelled
> one's execution. **And the refusal is permanent**: a `CANCELLED` attempt never becomes live
> again, which is why ADR-0255 §3 gives it the non-stale class.

> **Normative — what the cancelled attempt leaves is kept, entire.** ADR-0255 §7 binds verbatim:
> its `ExecutionState`s *"are not deleted, rewound, re-opened or re-derived"*, the outputs of its
> `SUCCEEDED` steps stay where ADR-0014 §3 puts them, and `GoalAttempt.execution_ids` still names
> every execution it drove. **No lane deletes, rewrites or tidies a cancelled attempt's record**,
> and none reads the cancellation as licence to discard what happened.

> **Normative — how a later turn on the goal proceeds, and it is by the acts that already exist.**
> An `ABANDONED` goal has left the open set, so nothing associates to it and nothing plans for it
> (ADR-0250 §1, §12). The user **reopens it by explicit reference** (ADR-0250 §13), which writes
> `ACTIVE` and **opens a new attempt at `UNDERSTAND`** carrying no reference to the one it follows
> (ADR-0250 §12). That attempt **plans afresh**: ADR-0255 §2's *"A later turn of the same attempt
> **plans again** — which produces a **new** plan, driven over a **new** execution"* is the shape,
> and no walk of the cancelled attempt's plan is re-entered, resumed or re-driven.

> **Normative — an effect that did land is never repeated, and the record that stops it is
> already written.** ADR-0259 §2 keys an effect row on `(goal_id, intended_action_id, effect_key)`
> and **a cancellation releases no row and deletes none** — §2 writes no effect row and §4 adds no
> release — so a step of the new attempt's plan under the same intended action answers
> **`COMPLETED`**, **`COMPLETED_OTHERWISE`** or **`UNCERTAIN`** and is not dispatched. **ADR-0255
> §7's at-most-once obligation is therefore unweakened by a cancellation**, and **no lane reads a
> reopened goal, a new attempt or a fresh plan as licence to repeat an act.**

**The prohibition is a property of the claim rather than a rule the driver obeys, which is the
only form in which it is worth having.** A driver-side *"do not dispatch after a cancellation"*
would be a read-then-dispatch with the gap revision 1 §H found; a store-side conjunct that is
already ratified and already tested refuses the claim whichever turn, process or lane makes it.
**What this decision contributes is that the state the conjunct tests is now reachable.**

### 6. What is in flight, at the surface: the act says it, the listing keeps saying it

> **Normative.** **`GoalAbandonment` gains one member and closes at four**:
> **`ABANDONED_EFFECT_IN_FLIGHT`**, valued by lower-cased member name like the other three. It is
> returned **exactly** where §3's limb 1 fired — the cancelled attempt held a step standing
> `INDETERMINATE` or `RUNNING` — and **`ABANDONED` is returned in every other abandoning case**.
> `ALREADY_CLOSED` and `NO_SUCH_GOAL` keep their meaning exactly.

> **Normative.** **`GoalSummary` gains one field, `effect_in_flight`, a `bool` defaulting to
> `False`, computed and never stored.** It is **true** where **any step of any execution any
> attempt of that goal opened stands `INDETERMINATE` or `RUNNING`**, and **false** otherwise — the
> same two statuses §3's limb 1 and ADR-0259 §4's act 4 read, so *outstanding* means one thing in
> the corpus. **The engine computes it**, so that two surfaces cannot render it differently, and
> **no adapter derives it** — ADR-0250 §15's own clause for `paused`, one fact over.

> **Normative — it is derived from the authoritative record and never from an `AttemptOutcome`,
> and that is what lets it clear.** ADR-0255 §6 makes the step's `INDETERMINATE` status *"the
> authoritative record of the uncertainty"*, and **a terminal attempt's `outcome` is immutable**:
> ADR-0249 §5's *"no transition leaves a terminal member"* means a cancelled attempt recorded
> `UNCERTAIN` carries that word for ever, truthfully, as a fact about **what that attempt
> produced**. A flag derived from it could never go false, so the listing would tell a user an
> action was outstanding long after ADR-0259 §3 resolved it. **No lane derives this field, or any
> other live-state fact, from a terminal `AttemptOutcome`**, and the resolution ADR-0259's act
> lands — `INDETERMINATE → SUCCEEDED` — is exactly what makes it false again.

> **Normative — it is a report assembled from several reads and is not a snapshot, and nothing
> decides on it.** The attempts and their executions are read one at a time, so a listing that
> races a concurrent walk can assemble a `False` from reads taken either side of a step's claim.
> **That is accepted rather than closed**, on ADR-0250 §15's own footing for `paused` — computed
> from a separate read of the attempt and equally unordered against a concurrent write — and on
> ADR-0259 §6's for a derived hint: *"the next engagement of that goal repairs it; nothing is lost
> but the ordering of one candidate set"*. **No lane reads `effect_in_flight` to take, refuse,
> retry or skip anything**: it is rendered, the durable record it summarises is unaffected, and
> the next listing shows the state that then holds. **What is never lost is the record itself** —
> the step's own `INDETERMINATE` status is authoritative (ADR-0255 §6) and no read of this field
> changes or hides it. A **decision** taken on this fact would owe the snapshot; a **rendering**
> does not, and §11 names what would reopen it.

> **Normative — what the derivation costs, stated rather than hidden.** It reads the goal's
> attempts and their executions, which is one level deeper than the read `paused` already takes
> and is bounded by the listing's page (ADR-0250 §15, ADR-0085 §3). **`PlanStore` gains no member
> and no projection for it** — `attempts_of`, `execution_ids` and `get_execution` are what it
> uses — and **no lane caches, stores or denormalises the value.** A measured cost on a wide
> listing is what would reopen this, and is named in §11.

> **Normative — what each surface states, and it is one fixed statement rather than a rendering
> each adapter invents.** On ADR-0242 §9's construction: a surface renders, beside the reply and
> never in place of it, for `ABANDONED_EFFECT_IN_FLIGHT` that the goal was given up **and that an
> action of it was already claimed and may have been sent, with its outcome unknown**, naming
> `assistant goals` as where that goal's state is read; and for a listing row whose
> `effect_in_flight` is true, that an action of this goal **is outstanding — claimed, possibly
> sent, outcome unknown**. **No statement says that the action did not happen, that it did, or
> that anything the user does will withdraw it** — which is ADR-0244 §11's *"no caller assumes the
> **query** did not leave"* generalised as revision 1 §H.3 generalises it, rendered rather than
> merely recorded. **The exact wording is the lane's;
> what is fixed is which fact each names and that neither asserts an outcome.**

> **Normative — *in flight* means the claim landed, and never that the call left, and both names
> that carry the word are read that way.** `ABANDONED_EFFECT_IN_FLIGHT` and `effect_in_flight`
> assert that a step is **claimed** — `RUNNING` or `INDETERMINATE` — and assert **nothing** about
> whether `ToolInvoker.invoke` was entered. ADR-0014 §4 puts the commit **before** the invocation
> and ADR-0034 §1 names the window between them in which *"nothing could have run under"* the
> claim; ADR-0029 §4's `INDETERMINATE` is *"the state whose whole meaning is ignorance"*. **No
> lane renders either as *the action was sent*, and no lane infers transmission from a status** —
> which is the same refusal ADR-0014 §4 makes for recovery, *"a crash between a tool's side effect
> and the commit … cannot be distinguished from a crash **before** the effect"*.

> **Normative — the boundary R77 asks for is defined and is cited rather than restated.** It is
> the **committed `→ RUNNING` claim**: ADR-0148 §9's *"There is no egress outside a claimed step"*
> with ADR-0014 §4's requirement that the claim be committed **before** the tool is invoked. **This
> decision moves it nowhere and adds no clause to either**, and the interval between the commit and
> `invoke` stays ADR-0034 §1's while the interval after `invoke` stays ADR-0029 §4's.

> **Normative — the outcome is stated once it is known, through the records that already carry
> it, and no second record is minted.** An `INDETERMINATE` step's status stays *"the authoritative
> record of the uncertainty"* (ADR-0255 §6); resolving it is A8's (ADR-0259 §3), and where a
> resolution lands the step becomes `SUCCEEDED` and `effect_in_flight` becomes false by the same
> derivation. **No mark, field, flag or store member is added for an in-flight effect**, which is
> ADR-0259 §4's clause binding one surface over.

> **Normative — a goal abandoned while an effect is unresolved is closed, and the reconciliation it
> is owed is reached by the reopen act and by nothing added here.** The act is **not refused** and
> **not deferred**: a user who cannot cancel is worse served than one who is told accurately. The
> step stays `INDETERMINATE`, §5's records are kept, and **ADR-0259 §4's pass runs over the goal on
> any turn that engages it** — which a reopen is (ADR-0250 §13). **No sweep, job, scheduler or
> background pass is added for an abandoned goal**, and ADR-0259 §4's *"nothing schedules it,
> queues it, retries it out of band or runs it for a goal no turn engaged"* binds entire.

**One act whose answer reports which of two things it did, rather than two acts.** ADR-0244 §11
made exactly this choice and stated the reason: *"A separate `withdraw` and `interrupt` would ask
the caller to know which state the park is in before it acts — a race by construction … One
operation whose answer *reports* which of the two happened puts the discrimination where the
atomicity already is."* Here the atomicity is `commit_attempt`, and the discrimination is §3's
limb 1 — computed from the same read the outcome is computed from, so the answer and the record
cannot disagree.

**And the listing carries it because the act's answer is heard once.** `abandon_goal` answers a
caller at one instant; a user who comes back tomorrow asking *"did that booking go through?"* reads
`assistant goals`, and a listing that showed an `ABANDONED` goal with nothing beside it would have
lost the one fact R78 requires be reported accurately. `paused` is the precedent in the same model
for the same reason — a derived fact the engine computes so two surfaces cannot disagree.

### 7. What a refused claim causes at the user's surface

> **Normative — a refused claim ends the walk, and it is not a sixth member of ADR-0255 §2's stop
> list.** The driver **catches the `PlanningError` raised by the `commit_transition` call its own
> claim made**, and that call alone: it commits nothing, leaves the step at the status and version
> it stood at, dispatches no further step of the plan, and **does not retry the claim**.
> ADR-0255 §2's list is *"what a disposal **this walk performed** leaves"*, and a refused claim
> leaves no disposal at all: it **is** dispatched — *"§3 puts that claim inside the run, after the
> request and the ruling"* — and **returns none because it raises** (ADR-0255 §11). So **no lane
> reads this clause as widening that list, deriving a sixth trigger from it, or admitting a
> `Disposition` member for it.**

> **Normative — the turn composes without acting, and it does not replan — where a cause is
> established, and only there.** Where the read below establishes one of the four causes, the turn
> returns a `TurnOutcome` with a composed reply and the refusal **does not fail the turn**.
> **Where it establishes none, the `PlanningError` propagates unchanged**, exactly as it does on
> the tree today: a refusal no ratified conjunct explains is a compare-and-swap loss, an unknown
> execution or a defect, and **a turn that reported it as a withheld drive would assert something
> about the step that nothing established.** No lane converts such a refusal into a
> `DriveWithheld`, and none reports a step as unstarted on the strength of an exception class. **No second `Planner.plan` call is taken on account of it**, no walk
> is re-entered and no plan is selected: ADR-0255 §2's *"A stopped walk is re-entered by **exactly
> one** route: `StepRunner.resume` answering a park of that plan"* and *"A later turn of the same
> attempt **plans again**"* both bind entire, and *"What causes that later turn is a user act"*
> is what follows a refusal.

> **Normative.** **`core/types.py` gains `DriveWithheld`**, a `StrEnum` valued by lower-cased
> member name and **closed at exactly seven members**: **`GOAL_CANCELLED`**, **`GOAL_ACHIEVED`**,
> **`GOAL_BLOCKED`**, **`ATTEMPT_ENDED`**, **`ATTEMPT_PAUSED`**, **`PLAN_SUPERSEDED`** and
> **`UNDERSTANDING_CHANGED`**. The vocabulary is added to and never renamed. **Each member names
> exactly one stored fact and no family of them**, and there is deliberately **no member for a
> refusal nothing explains** — that case propagates (above) rather than being given a name it
> could not support.

> **Normative.** **`TurnOutcome` gains exactly one field, `drive_withheld`, typed `DriveWithheld |
> None` and defaulting to `None`**, and its docstring names this ADR. It is **non-`None` exactly on
> a turn whose walk ended on a refused claim**, and `None` on every other outcome — every turn that
> dispatched, stopped on one of ADR-0255 §2's five, or drove nothing at all, and **`None` on
> ADR-0198 §1's restatement**, which drives nothing and claims nothing. That adds a value to
> ADR-0198 §2's enumeration **without changing any value it fixes**.

> **Normative — how the member is chosen: one test per stored fact, in this order, and no test
> stands for a family.** After the refusal the engine takes **one** read of the goal and the
> attempt the claim named and answers: **`GOAL_CANCELLED`** where the goal's `status` is
> `ABANDONED` **or** the attempt's `state` is `CANCELLED`; **`GOAL_ACHIEVED`** where the goal's
> `status` is `ACHIEVED`; **`GOAL_BLOCKED`** where the goal's `status` is `BLOCKED`;
> **`ATTEMPT_PAUSED`** where the attempt's `state` is `AWAITING_CLARIFICATION`,
> `AWAITING_AUTHORIZATION` or `BLOCKED`; **`ATTEMPT_ENDED`** where the attempt's `state` is
> `ENDED`; **`UNDERSTANDING_CHANGED`** where the plan's `targets_revision` is not the goal's
> current `revision`; and **`PLAN_SUPERSEDED`** where a stored plan supersedes the plan. **Where
> none holds, no member is chosen and the refusal propagates.**

> **Normative — the goal's own two tests are taken before the attempt's, and the attempt's paused
> test before its ended one.** The order matters only where two hold at once, and it is chosen so
> that the member names the **act furthest upstream**: a goal the user abandoned reports
> `GOAL_CANCELLED` whatever its attempt reads, and a paused attempt reports `ATTEMPT_PAUSED`
> rather than `ATTEMPT_ENDED`, which is unreachable together in any case since the two are
> different `AttemptState` members.

> **Normative — no member asserts that the goal is closed unless it is, and the four states that
> are not closure each keep their own.** ADR-0250 §1 rules that *"A goal is **open** where its
> `GoalStatus` is `ACTIVE` or `BLOCKED`, and **closed** where it is `ACHIEVED` or `ABANDONED` …
> and **`BLOCKED` is open**"*, and ADR-0249 §4 rules that *"An attempt reaching a terminal state
> **does not** move the goal's status"* — so a `BLOCKED` goal is open, and an `ACTIVE` goal whose
> attempt is `ENDED` is open and takes a new attempt by ADR-0250 §12's third act. **`GOAL_BLOCKED`
> and `ATTEMPT_ENDED` therefore say what is true of each and never that the goal is closed or
> cancelled**, and **no lane collapses any two of the seven members.**

> **Normative — the read is a report and never a decision.** **Nothing is dispatched, claimed,
> committed or decided on it** — it fills a report after the store has already refused — so it is
> not the read-then-claim ADR-0249 §8 and ADR-0255 §3 forbid, and **no lane uses this read to take
> a claim, to retry one, or to skip a step.**

> **Normative — one fixed statement per member, and none of them asserts an outcome.** On ADR-0242
> §9's construction a surface renders, beside the reply: for `GOAL_CANCELLED`, that the goal was
> cancelled and **this turn did nothing further for it**; for `GOAL_ACHIEVED`, that the goal is
> already reached; for `GOAL_BLOCKED`, that the goal **cannot currently be reached and is still
> open**, naming `assistant goals`; for `ATTEMPT_PAUSED`, that the goal is waiting on the user,
> naming `assistant goals`; for `ATTEMPT_ENDED`, that the attempt this plan belonged to is over
> and that **the goal is not thereby closed**, asking again starting a new one; and for
> `PLAN_SUPERSEDED` and `UNDERSTANDING_CHANGED`, that the plan no longer matches what the goal now
> asks and that asking again plans afresh. **No statement says that the step would have
> succeeded, that the effect did not happen, that no step of this plan was ever started, or why a
> store refused** — what each asserts is what this turn did, which is the only thing the read
> establishes.

> **Normative — a driver skip needs no carrier and gains none.** A step the walk moved
> `PENDING → SKIPPED`/`UNMET_DEPENDENCY`, and a step swept `SUPERSEDED`, **already reach composing
> through `undriven`**, which ADR-0255 §11 fixes as *"the steps the walk left `PENDING` and the
> steps it skipped"*. §11's exclusion is from **`TurnOutcome.step`** alone — a field carrying a
> `Disposition` a gate gave — and **`drive_withheld` is never written for a skip**. **No lane adds
> a second carrier for a driver skip, and `SkipReason` gains no member.**

**Seven members because seven states are establishable and each is a different thing to tell a
user, and the classification is the read's rather than the exception's.** The store refuses a claim on ADR-0255 §3's attempt conjunct (four limbs),
on its successor conjunct, and on ADR-0249 §8's revision conjunct — and the classes it raises are
**shared with refusals that are not claim guards at all**: `StaleExecutionError` is also an
ordinary compare-and-swap loss (ADR-0014 §5), `IllegalTransitionError` is also a transition no
correct driver builds, and a bare `PlanningError` is also an unknown execution. **So the exception
cannot name the cause**, and a decision that classified from it would report *this turn withheld
the step* for a race another worker won. The read is what classifies, it names only states a user
act produced, and where it names none the refusal is left to propagate — which keeps the field
total over what it asserts rather than total over what can be raised.

**And it composes rather than raising because a refused claim is not a fault.** Every cause above
is *the user changed something*, and a turn that raised a `PlanningError` at the adapter would
present the user's own correction as an internal error. ADR-0255 §11 already establishes that
nothing is lost from the record — every step's status, `skip_reason`, `failure` and `output` stays
on the `ExecutionState` its walk opened — so what the reply owes is the fact, not the exception.

### 8. Authority on correction: R76 and R79, and what this decision adds

> **Normative — R79 is discharged by ADR-0249 §8 and needs nothing here.** Its *"an old plan or
> approval never executes against a newer interpretation merely because it finished validating
> first"* **is** that section's conjunct: a plan whose `targets_revision` is not the goal's current
> revision is refused **inside** `commit_transition`, so a validation that finished first cannot
> overtake a revision that landed after it. **This decision adds no clause to it**, and the fit
> report's own reading is the one adopted: *"R79 **needs bending, with the rule already chosen**"*.

> **Normative — R76's *authority* half is ADR-0254 §5's and ADR-0256's, and this decision adds
> nothing to either.** A correction *"supersedes rather than composes"*, the superseded record
> *"stops being live in the same act"*, and a correction that would **widen** takes path (i),
> is refused at the write and is confirmed (ADR-0254 §5). **No clause of this decision writes,
> reads, revokes or supersedes an `Authorization`**, and none cites ADR-0254 or ADR-0256 toward a
> ruling of its own.

> **Normative — R76's *pending work* half is what §4 and §5 state, and it is the claim.** *"Before
> dispatch"* is the committed `→ RUNNING` claim (§6), and what invalidates the pending work is the
> conjunct the correction's revision defeats — not a sweep, not a cancellation of a plan, and
> nothing this decision adds. **A step of a stale plan is left where it stands**: ADR-0249 §8's
> *"What the refusal causes — a replan, a report, a step left `PENDING` and later
> `SKIPPED`/`SUPERSEDED`"* is answered by §7 for the report and by ADR-0255 §7 for the sweep.

> **Normative — the goal-terminal ending of an authorisation is not written here.** The owner ruled
> on 2026-09-14 that *"an authorisation lasts for its request, and a request ends when the action
> is done … **the authorisation ends with the goal**"*, and that the change is *"a **short
> superseding ADR, one edge + one clause, sequenced after [the coverage-minting decision]**"* —
> the number that ruling names is **not yet issued**, so it is elided here rather than cited
> (ADR-0088 §6 Tier 1), and the lane drafting it is
> [#2376](https://github.com/leonapivato/ai-assistant/issues/2376). **This decision does not
> write that ending**, adds no ending to the four the ruling itself reads off ADR-0254 §1 —
> *"expiry, revoked, superseded, recipient grant lapsed"* — and **no clause of it contradicts the
> ruling**: a cancellation is a terminal state of a goal, so an authorisation of a cancelled goal
> ends under that ADR when it lands, and nothing here asserts that it survives. **The one case the
> ruling keeps open is preserved by §6**: *"The only case an authorisation must outlive a turn is
> the **uncertain-outcome** case (timeout leaves the fate unknown; goal stays open until resolved
> through the phases with permission)"* — §6 keeps the uncertainty on the record, keeps the
> reconciliation reachable through the reopen act, and takes no authority for it.

**Naming what is already discharged is most of this section's value.** The fit report scored R76
and R79 as *needs bending*, and a decision that re-answered them would land a second rule beside
ADR-0249 §8's and ADR-0254 §5's for the same question — which is how two authorities that can
disagree get built. What A9 actually owed on them was to say where they were met and to leave
them alone.

### 9. The signal #2380 asks for: it is the claim, and this decision mints no gate

> **Normative — a cross-turn eligibility test for a parked `ALLOW` needs no new predicate, and the
> signal ADR-0259 §5 found missing is the one §2 writes.** ADR-0259 §5 states the gap exactly —
> *"A gate that worked would need a revocation signal this corpus does not have, which is **A9's**
> to mint"* — because `ActionPlan.supersedes` is a **same-turn** mark (ADR-0228 §5) and *"a turn
> saying 'cancel that booking' would plan, supersede nothing, and leave the earlier park
> eligible"*. **After this decision that turn writes three durable facts, each a user act**: the
> attempt that owns the parked step's execution is **terminal** (§2), the goal's status is not
> `ACTIVE` (§2), or — on shape (b) — the plan's `targets_revision` is no longer the goal's current
> revision (§1, ADR-0249 §8).

> **Normative — and the test that reads them is the claim itself, not a second gate.** Each of the
> three is a conjunct `commit_transition` **already** refuses on, so a replay that simply took the
> `→ RUNNING` claim would be refused by the store with nothing invoked — which is the
> time-of-check-to-time-of-use-free form, and the only form ADR-0249 §8 and ADR-0255 §3 admit. **No
> lane builds a separate eligibility predicate, a pre-claim read of the goal, or a liveness field
> on a park.**

> **Normative — this decision designs no replay and takes none of what #2380 carries with it.** It
> **replays no recorded `ALLOW`**, re-asks no parked step, calls `StepRunner.resume` for none, and
> authors no permission record; ADR-0259 §5's *"A parked `ALLOW` whose dispatch never happened is
> left standing"* binds **entire**, and so does its rule that the goal's next turn *"plans again,
> and the step that work reaches goes through the standard phases like any other"*. **The
> deterministic selection rule, the ordering and the at-most-one semantics several parks would
> need stay #2380's**, undecided here, and **no lane reads this section as licence to dispatch out
> of a stored answer.**

**Recording the signal without designing the consumer is the whole of what the booking asked for**,
and the finding worth recording is that the consumer is smaller than #2380 assumed: the issue asks
for *"anything that decides whether a parked `ALLOW` is still live across a turn boundary"*, and
the answer is that liveness is not a property a replay should read — it is a claim a replay should
attempt. A gate that read the three facts and then claimed would re-introduce exactly the gap
revision 1 §H.1 identified.

### 10. The `core` surface, the wire, the stored shapes, and the export

> **Normative — what `core/types.py` gains.** **One enumeration member on `AttemptOutcome`**
> (`CANCELLED`, §3); **one enumeration member on `GoalAbandonment`**
> (`ABANDONED_EFFECT_IN_FLIGHT`, §6); **one new enumeration**, `DriveWithheld`, closed at seven
> (§7); **one field on `GoalSummary`** (`effect_in_flight`, §6); and **one field on `TurnOutcome`**
> (`drive_withheld`, §7). **Nothing else** — no new model, no new constant, no widening of
> `GoalAttempt`, `AttemptTransition`, `Goal`, `StepTransition`, `StepExecution`, `ExecutionState`,
> `ActionPlan` or `PlanStep`. **`PlanStore` gains no member and no argument**, and the whole of
> what any Protocol gains is **one refusal on `commit_attempt`** (§3) — a strengthening of an
> existing member, on ADR-0255 §3's and ADR-0249 §12's own classification of the same move.

> **Normative — this is a BREAKING contract change under golden rule 5, and it is breaking for the
> wire rather than for a constructor.** Every field added defaults, and both enumerations are
> *added to*, so **no existing construction stops validating** and no caller's code is invalidated.
> What breaks is the peer contract, **on the two model fields and not on either enumeration
> member**. `GoalSummary` and `TurnOutcome` are both returned by promoted-surface methods, both set
> `extra="forbid"`, and `wire/codec.py` renders a model by `model_dump()` — so a newer hub emits an
> `effect_in_flight` member and a `drive_withheld` member an older client refuses. That is
> **ADR-0124 §9's second limb** — *"a change to a wire-carried `core` type that makes a value one
> peer emits invalid for the other"* — and **ADR-0178 §6 is the precedent for stating
> the bump in the deciding ADR**.

> **Normative — neither new enumeration member is a wire ground, and that is read off the tree
> rather than assumed.** `AttemptOutcome` rides `GoalAttempt`, and as a dated observation at
> `8dbfddf0` **`GoalAttempt` is named in the `PlanStore` Protocol alone** — `open_attempt`,
> `get_attempt`, `attempts_of`, `commit_attempt` — and nowhere in the `AssistantEngine` Protocol
> or under `wire/` but in two prose comments; `PlanStore` is **not** on the promoted surface
> (ADR-0255 §11). **So no peer emits a `GoalAttempt` and the new value reaches no client**, and its
> version ground is the **export** alone. `GoalAbandonment` is returned by `abandon_goal`, which
> **is** promoted, so its new member would be a wire ground on its own — the bump already owed
> covers it, and no second bump is taken. **A lane that finds the tree disagrees — a promoted
> method that returns a `GoalAttempt` — changes nothing about the bump, which is already owed, and
> records the correction in `wire/envelope.py`'s entry.** The stale ADR-0251-era entry in that file
> saying `GoalAttempt` *"is what the promoted surface's attempt-facing methods return"* is **not**
> true of the tree at `8dbfddf0` and no lane of this decision relies on it.

> **Normative — `PROTOCOL_VERSION` moves by exactly one, in the lane that lands the `core` change,
> together with `wire/envelope.py`'s log entry naming this ADR.** **No integer is fixed here**: the
> figure is the tree's, and as a dated observation at `8dbfddf0` it reads **43**. **No
> compatibility shim, negotiation or lenient decode is added** — ADR-0084 §3's exact-match
> handshake is the mechanism and the refusal naming both versions is the intended outcome.

> **Normative — `PlanExport.schema_version` moves by exactly one, and the ground is stated
> honestly as an extension rather than borrowed.** `PlanExport` carries `tuple[GoalAttempt, ...]`,
> so a document written after this decision may carry an `AttemptOutcome` value an earlier reader
> refuses. **ADR-0039 §10's mechanism is what moves it** — *"`StepExecution` is inside the export,
> so its shape changing is exactly what the version exists to announce"* — **applied for the first
> time to a value rather than to a shape**, on ADR-0014 §5's own reason for the field: *"an export
> outlives the code that wrote it … a reader must be able to tell which shape it is holding."* A
> document a v9 reader cannot decode is exactly what the label exists to warn it about, and the
> direction of the extension is the announcing one. **It is a stacked addition and owes ADR-0039
> no record** (§12): §10's sentence says a shape change announces itself, not that only a shape
> change does. It is a **stored-record version and not a second wire ground** — `PlanExport`
> crosses no frame and is emitted by no peer. As a dated observation it reads `Literal[12]`.

> **Normative — the plan store's `schema_version` moves by exactly one, and the migration writes
> the `meta` row and nothing else.** No stored row changes shape and every attempt already on disk
> decodes unchanged under the new contract, so **no row is read, rewritten or re-encoded**; what
> moves is the marker, and `_UPGRADABLE_FROM` gains the version it moves from. As a dated
> observation `_SCHEMA_VERSION` reads **4**. `ConversationExport` is untouched.

> **Normative — the ground is ADR-0049 §1's loud refusal read in the downgrade direction, which is
> the direction it was written for.** The plan store persists a `GoalAttempt` as its
> `model_dump_json()`, so **the set of values `AttemptOutcome` admits is part of what a database
> holds** even though no field is added. Leaving the marker at 4 would let new code write
> `"cancelled"` into a database an **older** binary still accepts as version 4 — and that binary
> would then fail while decoding a row, rather than refusing the database. ADR-0049 §1 fixes the
> intended behaviour: *"Opening a database whose `schema_version` is newer than the code
> understands is a **loud `PlanningError`**, not a silent best-effort read — a downgrade is a
> fault to report"*. **A version marker that does not move makes that refusal unreachable**, which
> is the failure rather than the cost. **This is a rule about this decision's own value and
> reaches no other lane**: no lane reads it as a record against, or a criticism of, any earlier
> decision that added a member to a stored vocabulary without moving the marker, and none re-opens
> one. What binds here is this change.

> **Normative — nothing else under `wire/` changes, and no setting is added.** The connect exchange
> gains no member, no existing frame's encoding changes, no `FrameKind` is added, no codec entry is
> registered, the error mapping is untouched, the promoted method set does not move, no gateway
> route is added, and **no `Settings` field is added — no figure of this decision is
> configurable.**

> **Normative — retention, deletion and export are untouched, and no new durable record is
> minted.** Every value this decision writes rides a `GoalAttempt` or a `Goal` the plan store
> already holds, so ADR-0014 §5's deletion obligation and export closure rule and ADR-0249 §12's
> `delete_goal` cascade bind exactly as they stand. **No lane adds a retention rule, a sweep, an
> expiry or a second store.**

> **Normative — no new Protocol is created, so no new conformance suite and no new canonical fake
> is owed; and `PlanStore`'s existing obligations do not move.** `PlanStore` gains **nothing** —
> §2's act uses `commit_attempt` and `set_goal_status` as they stand, and §4 adds no conjunct — so
> the shared suite's growth for this decision is **two cases** (§14): §H.4 test 4's interleaving
> invariant, which pins a property the two ratified conjuncts already require of a conforming
> store, and §3's outcome conjunct, which is the one refusal this decision adds. **The canonical
> fake in `ai_assistant.testing` gains the same obligation in the same change that adds it**
> (`CONTRIBUTING.md` → "Adding a Protocol": *"The triad is what a Protocol *change* is measured
> against too"*).

### 11. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward any
> of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling, and each
> carries the condition that fires it.

- **A live cancellation that reaches a running turn**, and the message queue, steering surface and
  in-turn delivery it would need. **Not decided**, by the owner's sequencing ruling of 2026-09-13.
  **The checkpoint that ruling asks be left is exactly the boundary §4 draws**: a live cancellation
  enters at the same place a between-turns one does — as a write that makes the `→ RUNNING` claim's
  attempt conjunct fail — and what would fire it is a decision that states how such a write is
  delivered into a turn already running, together with what becomes of an `invoke` already entered
  (ADR-0029 §4, ADR-0060 §1). **Nothing more is stated, and no lane builds toward it here.**
- **Cancelling a dispatch running in another process.** ADR-0244 §20's entry, **untouched**: *"§11's
  act reaches the process that received it. What fires it: #2173's L7 obligation."* This decision
  adds no cross-process signal, no durable cancellation record and no cancellation queue, and
  **ADR-0083**'s one-resident-process-per-data-directory posture is what makes that honest.
  (ADR-0244 §11 attributes that posture to ADR-0043, which is *"Explicit review markers"* and is
  **Withdrawn**; the decision that makes the hub a resident process with exclusivity is ADR-0083,
  as ADR-0125 and ADR-0194 both cite it. The misattribution is corrected here and **nothing else
  of ADR-0244 §11 or §20 is touched** — this is a citation repair, not an amendment, §12.)
- **An act that ends an attempt while leaving its goal open.** **Not decided** (§1). Fired by a
  surface that needs one, which would owe the vocabulary for what such an attempt produced and the
  rule for what opens the next one against ADR-0250 §12's three acts.
- **The goal-terminal ending of an authorisation.** The owner's ruling of 2026-09-14, whose own
  disposition is *"a short superseding ADR, one edge + one clause, **sequenced after [the
  coverage-minting decision]**"* — the number elided for the reason §8 gives, its lane
  being [#2376](https://github.com/leonapivato/ai-assistant/issues/2376).
  **Not this decision's**, and §8 states that nothing here contradicts it.
- **The cross-turn replay of a parked `ALLOW`**, its deterministic selection rule among several
  parks, and its at-most-one semantics. **#2380**, and §9 records the signal and takes none of the
  three. Fired by a decision that takes the replay.
- **Retry across turns, reconciliation, idempotency keys, modify-before-replace, and how an
  `INDETERMINATE` step is resolved.** **A8**, as ADR-0255 §12 and ADR-0259 §10 book them. §6 keeps
  the uncertainty on the record and resolves nothing.
- **Which `AttemptOutcome` member a non-cancelled attempt earns, verification against the goal's
  criteria, and the producer of `GoalStatus.ACHIEVED`.** **A10**, undiminished: this decision earns
  a member for a cancelled attempt alone, a state A10 reaches through no transition (§3).
- **`GoalStatus.BLOCKED`'s producer.** **A3**, as ADR-0249 §4 and ADR-0250 §12 reserve it. Nothing
  here writes a `GoalStatus` but the `ABANDONED` ADR-0250 §12 already writes.
- **Parallel execution of two steps, a driver that walks a plan outside a turn, and whether a
  second `CONFIRM` of one turn may be put.** ADR-0255 §12's entries, **untouched** and left exactly
  where they stand. Fired by the decisions that take them.
- **A projection or index that answers *does this goal hold an outstanding effect* in one read.**
  **Not decided.** §6 derives it from the executions the goal's attempts opened, which is bounded
  by the listing's page and needs no new store surface. Fired by a **measured** cost on a wide
  listing — and a decision taking it would owe the write-time invariant that keeps the projection
  true, which is a second record of a fact a status already carries (ADR-0259 §4).
- **Whether a `PlanStore` refuses a question admitted onto a closed goal.** ADR-0250 §12's own
  residual, filed against that decision. §2's new write neither widens nor narrows that window.

### 12. Records owed on earlier ADRs, under ADR-0082 §1

**The test is ADR-0070 §1's, applied to the earlier ADR's text, and ADR-0082 §1 is where it is
stated in those words**: *"What decides which of the two it is, is ADR-0070 §1's test, unchanged,
applied to the earlier ADR's **text**. Would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds?"*

**Two ADRs owe a record**, and the header states each scope in full.

- **ADR-0249 §5** — *yes*, twice over and in one scope. A reader holding only §5 reads
  `AttemptOutcome` as **closed at six** and cannot build the `GoalAttempt` §2 writes, because §5's
  own validator compels an outcome on a terminal state and none of the six is true of an attempt
  that produced nothing. And a reader holding only §5 and §13 reads *which member an attempt earns*
  as wholly A10's, which is now over-wide by one state. **Nothing else of §5 fails the test**: the
  *added to and never renamed* clause is exercised by the addition rather than contradicted, and
  the terminal-member closure, the validator's two shapes, the `ANSWERED` clause, the
  user-act clause and the *paused* derivation stay true word for word.
- **ADR-0250 §12 and §15** — *yes*, in two scopes. §12's *"and does nothing else"* sentence becomes
  **false** of the act, and its `GoalAbandonment` three-member closure becomes over-wide by one;
  §15's *"whose fields are exactly"* enumeration becomes over-wide by one field. Every other clause
  of both sections stays true, including §12's *"does not end an execution and does not cancel
  anything in flight"*, which §2 obeys.

**Every other ADR this decision reaches owes no record**, and the nine entries below are the
whole of them, each decided by the same test.

- **ADR-0255** — *no*. §12 books three subjects here by name and §11 books two; a booking
  **discharged** is not a clause made false. §3's conjuncts, §2's stop list, §7's preservation
  rules and §11's `TurnOutcome.step` clause are each **relied on** and none is widened: §7 adds
  `drive_withheld` beside `step` rather than to it, and §11's own sentence — *"what they cause at
  the user's surface is A9's"* — is fulfilled.
- **ADR-0242 §9** — *no*, and its own text is the precedent. That section added a field to
  `TurnOutcome` and wrote: *"a widening rather than a change … neither [ADR-0235 §4 nor ADR-0197]
  recorded a supersession of ADR-0170 for the identical move, so this one records none either."*
  §7's field is the identical move and records none either. **ADR-0250 §5's *"`TurnOutcome` gains
  **four** `None`-defaulting members"* likewise stays true of ADR-0250's own change**: a reader
  holding it builds those four and is not made to act differently by a fifth or a sixth stated
  elsewhere. **That ADR-0254 recorded against §5 for its own addition does not decide this**, and
  ADR-0082 §1 is explicit that it may not: *"What a reviewer may not do is demand a record … on
  book-keeping grounds alone: … that a sibling ADR was recorded differently."*
- **ADR-0249 §4** — *no*. *"An attempt reaching a terminal state does not move the goal's status"*
  stays true: §2's one user act moves both, and nothing infers either from the other (§1).
- **ADR-0244 §11 and §20** — *no*. `cancel_read` keeps its three members, its scope and its
  atomicity; §20's general-case deferral is left standing with its firing condition (§11).
- **ADR-0259 §5 and §10** — *no*. §9 **records** the signal §5 says A9 must mint and takes none of
  the replay §5 declines; *"A parked `ALLOW` … is left standing"* stays true.
- **ADR-0249 §12** — *no*, for §3's conjunct on `commit_attempt`. That section declares the member
  and its append-only discipline; it does not enumerate what the member refuses, and **ADR-0255 §3
  added an execution-ownership refusal to the same member and recorded nothing against it**,
  classifying the move as *"a **strengthening of an existing member** rather than a new one"*.
  This is the identical move and records nothing either. §12's commands-not-snapshots rule, its
  append-only tuples and its compare-and-swap discipline all stay true.
- **ADR-0039 §10** — *no*. Its *"`StepExecution` is inside the export, so its shape changing is
  exactly what the version exists to announce"* says that a shape change announces itself; it does
  **not** say that only a shape change does. §10 extends the mechanism to a **value** an earlier
  reader refuses, which is a **stacked addition** recorded in this ADR and nowhere else.
- **ADR-0049 §1** — *no*. §10 **relies on** its refusal — *"Opening a database whose
  `schema_version` is newer than the code understands is a loud `PlanningError`"* — and moves the
  marker so that the refusal is reachable. Its migration clause was already superseded by
  ADR-0249 §12, which landed that store's first migration; a second one makes no further sentence
  of §1 false.
- **ADR-0014, ADR-0029, ADR-0034, ADR-0060, ADR-0148** — *no*. §§1 and 6 cite each for the
  boundary and the intervals either side of it and add no clause to any; every sentence of each
  stays true.

### 13. The lane cut

**Three lanes, one subsystem each, and the first is the only one that moves a contract.**

- **L1 — `core` (with `wire` and `testing`).** The two enumeration members, `DriveWithheld`, the
  two model fields, and the docstrings that name this ADR; `PROTOCOL_VERSION` **+1** with its
  `wire/envelope.py` log entry; `PlanExport.schema_version` **+1**; the plan store's
  `_SCHEMA_VERSION` **+1** with the `meta`-row migration §10 states; **§3's outcome conjunct on
  `PlanStore.commit_attempt`** with its `planning` implementation; and the canonical fakes in
  `ai_assistant.testing` together with the shared `PlanStore` conformance suite's two cases (§14,
  arms 3 and 4). **This is the lane that moves the wire**, and it lands alone — golden rule 5, and
  `CONTRIBUTING.md` → "Adding a Protocol" for the suite and the fake riding the same change.
- **L2 — `orchestration`.** §2's attempt commit inside `abandon_goal` with its ordering, §3's
  four-limb outcome, §6's `GoalAbandonment` answer and `GoalSummary.effect_in_flight`
  computation, and §7's refusal catch, walk end, ordered read and `drive_withheld`. **It moves no
  contract**: `StepRunner` and `StepExecutor` are concrete classes, not Protocols.
- **L3 — `interfaces`.** The fixed statements §6 and §7 name, on the CLI's abandon and goals
  surfaces and on the reply. **Thin, by golden rule 3**: it renders values L2 computed and derives
  none.

**Merge order is L1 → L2 → L3**, and each is one PR (the owner's *one lane, one PR* rule).

### 14. The arms this decision owes

**Ten, and three of them are revision 1 §H.4's by name.** Each is stated over the lane that owes
it.

1. **§H.4 test 1 — cancel before claim (L2).** A cancellation commits between the driver's decision
   to run a step and its claim — stated, per the sequencing ruling, over a cancellation **recorded
   before the walk**; assert the claim is refused, that a `ToolInvoker` fake **records no entry**,
   that the step stands `PENDING` at its stored version, and that the act answered `ABANDONED`.
2. **§H.4 test 2 — cancel after claim (L2).** Stated over a claim **an earlier turn committed**:
   assert the step's status is one of `SUCCEEDED`/`FAILED`/`INDETERMINATE` and **never `SKIPPED`**,
   that its `approval_ref` is set, that the act answered `ABANDONED_EFFECT_IN_FLIGHT` over an
   `INDETERMINATE` step, and that the cancelled attempt's outcome is `UNCERTAIN`.
3. **§H.4 test 4 — the interleaving invariant (L1, shared suite).** For **one** claim, in every
   ordering against a cancellation, exactly one of {this claim landed, this claim was refused}
   holds — never both, never neither — asserted against every conforming `PlanStore`. **It does
   not assert that a claim and a cancellation are mutually exclusive acts** (§4).
4. **§3's outcome conjunct (L1, shared suite).** A `→ CANCELLED` `AttemptTransition` whose
   `outcome` is not the member the four limbs yield is refused with `StaleExecutionError` and
   **writes nothing**; a claim landing between the caller's read and its commit produces exactly
   that refusal, and the caller's recomputed `UNCERTAIN` then lands. Every other
   `AttemptTransition` is unaffected.
5. **The four-limb outcome (L2).** One arm per limb: an attempt holding an `INDETERMINATE` step →
   `UNCERTAIN`; one holding only a `SUCCEEDED` step → `PARTIAL`; one holding only a `FAILED` step →
   `FAILED`; and one whose every step is `PENDING`, `AWAITING_APPROVAL` or `SKIPPED` → `CANCELLED`.
6. **The ordering (L2).** A failure injected after the attempt commit and before the status write
   leaves an `ACTIVE` goal with a terminal attempt, **no claim lands under it**, and the next turn
   opens a new attempt.
7. **The post-cancellation prohibition (L2).** After a cancellation, a claim of a step of the
   cancelled attempt's execution is refused whether it names that attempt or another, and an effect
   the attempt completed answers `COMPLETED`/`UNCERTAIN` to a later plan of the goal rather than
   being dispatched again.
8. **The refused-claim surface (L2, L3).** Each of `DriveWithheld`'s seven members is produced by
   the state that names it, the turn **composes a reply**, and no `Planner.plan` call is taken on
   account of the refusal. **And the negative arm**: a refusal the read explains by none of the
   five — a compare-and-swap loss to a concurrent claimant — **propagates**, sets no
   `drive_withheld`, and asserts nothing about the step.
9. **The listing (L2, L3).** `effect_in_flight` is true where any step of any execution of any
   attempt of the goal stands `INDETERMINATE` or `RUNNING`, false otherwise, and **no adapter
   derives it**. It is asserted over store states constructed directly, because as a dated
   observation at `8dbfddf0` `AttemptState.EFFECT_UNRESOLVED` has **no producer in `src/`** —
   ADR-0259 §4's act 3 and ADR-0255 §6 are its two, on their own lanes — and an arm that waited
   for one would be an arm this decision's lanes could not run.
10. **The listing clears (L2).** A goal whose attempt was cancelled at `UNCERTAIN` and whose
    `INDETERMINATE` step is then resolved `SUCCEEDED` reads `effect_in_flight` **false**, while
    that attempt's `outcome` still reads `UNCERTAIN` — the arm that pins the flag to the
    authoritative record rather than to the immutable terminal outcome (§6).

**No arm demands a duplicate dispatch be demonstrated**, which is A8's acceptance requirement on
A8's lane (ADR-0255 §12), and **ADR-0255 §13's Q4 rule is what makes the interval safe**: no
consequential capability is wired, so the acts arm 6 governs cannot be performed against a real
integration.

### 15. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**A new decision that partially supersedes two ADRs** (§12), stated in three narrow scopes, and a
**stacked addition** against every other ADR it reaches. It is **marked** under ADR-0089 §2 as
ADR-0257 **§1** admits the label and its §3 carries that grammar across the corpus, so the marked
clauses are the whole of what it obligates.

## Consequences

**What becomes easier.** `AttemptState.CANCELLED` gains its producer, so ADR-0255 §3's claim
conjunct — the mechanism the whole design rests on — becomes reachable rather than hypothetical.
R78's *no later action begins* becomes a property of the store rather than a rule a driver keeps.
A user is told, once at the act and thereafter on the listing, that an effect of a cancelled goal
may have left. And #2380's eligibility question is answered in a form that needs no new predicate.

**What becomes harder.** A peer at the old `PROTOCOL_VERSION` refuses a peer at the new one, and an
export reader at schema 12 refuses a document written after L1, and an engine at plan-store
schema 4 refuses a database an engine at 5 has written — all three intended, all three loud.
`AttemptOutcome` grows a member every future reader of the enum must handle. And an attempt is now
ended by an act stated over the **goal**, so a surface that wants to stop the work without giving
up the objective has no act and must ask for one (§11).

**What would trigger revisiting this.** A deployment that runs two engines over one data directory,
which ADR-0083's exclusivity posture does not admit, would make §4's serialisation argument
insufficient and
fire ADR-0244 §20. A live-steering decision would put a second writer at the same boundary. And a
measured case in which §7's ordered read usually establishes no member — so that refusals
propagate where a report was wanted — would say the boundary is racing more than the read can
see.

## Alternatives considered

**A new `AssistantEngine.cancel_goal` beside `abandon_goal`.** Refused. ADR-0250 §12 makes
`abandon_goal` *"the only thing in this system that writes `ABANDONED`"* and books its missing half
here; a second act would be a second surface for *I give up*, and every call site would owe a rule
for which one the user performed. The act already exists, is promoted, and already reads the goal.

**Making a cancellation a new `GoalStatus` member.** Refused. `ABANDONED` already means *was given
up*, and ADR-0249 §4 fixes the four members; a fifth would be a second authority that can disagree
with the first, which is the argument ADR-0249 §5 makes against *paused* as a status member.

**Adding a cancellation conjunct to `commit_transition`.** Refused. ADR-0255 §3's attempt conjunct
and ADR-0249 §8's revision conjunct already refuse exactly the claims a cancellation must defeat;
a third would be a second authority for one fact, and §3's own argument against a caller-supplied
revision applies to it unchanged.

**Choosing one of the six existing `AttemptOutcome` members for a cancelled attempt.** Refused, and
§3 gives the reason member by member: each of the six asserts something the record does not
support, and the corpus's answer to a compulsory field with no true value is a member and a record
(ADR-0251 §7's precedent), not the least wrong guess.

**A flat `CANCELLED` outcome on every cancelled attempt.** Refused. With the state already saying
*cancelled*, the field would carry nothing a reader could not delete — the *two records of one
fact* defect ADR-0244 §2 and ADR-0249 §1 refuse — and it would lose exactly the distinction R78
requires between a goal with an outstanding effect and one without.

**Refusing the cancellation while an effect is unresolved.** Refused (§6). It would make a goal
uncancellable for as long as a tool is silent, which is a worse answer to *"stop"* than an accurate
one, and it would put the system in the position of declining a user act on the ground that it does
not know something.

**Reporting the refused claim by raising out of the turn.** Refused (§7). Every cause is *the user
changed something*, and an exception at the adapter would render the user's own correction as an
internal error. Composing with a named fact is what ADR-0242 §9 established for the same shape.

**Deriving `DriveWithheld` from the exception class alone.** Refused. The store refuses across two
classes over six limbs, so the class cannot name the cause; a field that guessed would be the
fabricated verdict ADR-0255 §11 refuses for `Disposition`.

**Deriving `effect_in_flight` from the cancelled attempt's `AttemptOutcome`.** Refused after
round 1, which is where it was found: a terminal attempt's outcome is immutable under ADR-0249 §5,
so a flag derived from `UNCERTAIN` could never go false and the listing would tell a user an action
was outstanding for ever — the opposite of the accuracy R78 asks for. The authoritative record is
the step's status (ADR-0255 §6), and §6 derives from that.

**Computing the cancelled attempt's outcome in the engine and committing it with the attempt's
own compare-and-swap.** Refused after round 1. A claim writes an `ExecutionState` and does not
advance `GoalAttempt.version`, so that compare-and-swap cannot see one land between the engine's
read and its commit: the act would record *nothing outstanding* about a step just taken to
`RUNNING`. §3 puts the comparison inside the write, which is ADR-0014 §5's own assignment of a
race to the store.

**Classifying `drive_withheld` from the exception the store raised.** Refused after round 1. The
claim guards share `StaleExecutionError` with an ordinary compare-and-swap loss and a bare
`PlanningError` with an unknown execution, so the class cannot name the cause and a turn that read
it would report *this turn withheld the step* for a race another worker won. §7 classifies from a
read of states a user act produced, and lets anything it cannot explain propagate.

**A distinct typed refusal for §3's outcome conjunct.** Refused after round 2, where the shared
`StaleExecutionError` was raised as an ambiguity. The wire encodes an error as
`type(exc).__name__` and a client rebuilds it *"by calling the named type"* (ADR-0085 §10a), so a
new class is a value an older peer cannot reconstruct — bought to distinguish two refusals whose
correct response is the same one. §2 takes the bound instead.

**Buying a snapshot for `effect_in_flight`.** Refused after round 2. A consistent existential over
a goal's executions needs either a store projection maintained at write time — a second record of
a fact a status already carries, which ADR-0259 §4 refuses — or a validate-and-retry loop inside
a listing. The field is rendered and never decided on, and `paused` already has the identical
property under ADR-0250 §15; §6 states the property rather than paying for it, and §11 names the
measurement that would reopen it.

**A durable cancellation record, queue or cross-process signal.** Refused. ADR-0244 §11 states the
honest scope and §20 defers the general case to #2173's L7; the writes §2 makes are already durable
and already ordered, so a second record would be a second authority with its own retention and
export obligations.
