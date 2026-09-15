# 262. Verification compares the goal's criteria with what the goal's own records establish, at a strength the consequence class fixes, and it is the only producer of `GoalStatus.ACHIEVED`

- Status: Partially superseded by ADR-0271 (two scopes. §2's `MONEY` clause, which rules that a criterion whose confirmed member is a `MONEY` one is `unestablished` outright — such a criterion now takes §2's own three results, over §2's own calls and decisive steps, with one further conjunct on its satisfying and contradicting tests: the charge the act reported agrees with the quote that decision pins to the dispatch, which is the operand §9 reassigns to it by name. And §7's gate statement, in the limb *"the guarantee does not cover a capability whose acts make a charge"* alone — it covers one, for a deployment that declares where its acts report a charge. Every other clause of both sections binds entire; the first dated note below states both scopes in full)
- Date: 2026-09-15
- **Partially supersedes** [ADR-0016](0016-tool-definition-and-registry.md)
  — **one scope, in §1, and it is the scope three records already take there reaching one further
  field**: the `ToolDefinition` model declaration, and the required-field clause in the application
  to **`postconditions`** alone — a possibly-empty `tuple[StepVerification, ...]` defaulting to the
  empty tuple, declared by whoever registers the tool and stating what a **successful** invocation
  establishes about its own output. §2's comparison holds an act's stored output against those
  declarations and authors no predicate of its own, so a reader holding only §1 authors a
  definition against which nothing can be held and every criterion resting on that tool is
  unestablished for want of an operand. **The required-field clause takes a fourth recorded
  exception, on its own fail-closed ground and not on the field being outside a permission
  decision's reach**: *"Every field that a permission decision depends on is required"* is
  unconditional and **this field is one such** — ADR-0254 §3's condition 3 compares the request's
  declaration with the row's **by value**, so a `postconditions` edit moves a route-(d) coverage
  answer exactly as a severity or schema edit does. The default is an exception because the empty
  tuple makes the **opposite** claim to the one §1 refuses — the ground `system_supplied` and
  `quoted_output` are recorded on, while `bounded_arguments` states a different one for itself and
  neither is restated here: it declares nothing, so **nothing is verified**, no criterion
  resting on that tool is ever met and no goal of it reaches `ACHIEVED` — a value that can only
  **refuse** to establish and never establish, which is the direction §1 exists to protect.
  **And the coupling is stated rather than left to be found**: an author who adds or edits a
  postcondition changes the declaration's value, so a row established over the earlier declaration
  stops covering a call built under the new one and that call **asks** — the consequence every
  declaration edit already carries under §3's condition 3, and the fail-closed direction. **No row
  changes coverage when this field lands**: LA's migration decodes stored declarations with the
  empty tuple and a registry definition declaring none carries the same value, so the comparison
  is between two empty tuples until an author writes one. **The exception is this one further
  field on this one argument**, and no lane reads the four records together as licence to default
  a safety field. Every other clause of §1 binds entire, §2's ordering of the
  declarations is read by §3 and moved by nothing, and §§3-7 are untouched — §4's
  `parameters_schema` included, the new declaration being a field **beside** that schema and never
  a keyword inside it.
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **one scope, in §16's *"the face a trail holds"* sentence together with §7's clause
  constructing `AuditTrail` implementations with one, in their application to *who may hold and
  read that Protocol* alone**: §3 of this decision gives the same face to the verification phase,
  to read the row a step's own pinned route-(d) decision points at. **That is a change to
  `AuthorizationResolution`'s contract even though its shape does not move**, and §8 classifies it
  as one rather than as a use: a reader holding only §16 builds a system in which the trail is the
  sole holder and `record` the sole reader. **The Protocol's shape *is* untouched** — `resolve(id)`
  and nothing else, the eight signatures unmoved, no member added to it or to
  `GoalAuthorizationStore`, `live_for` and `record` still out of reach — and §16's
  structural-typing argument binds entire and is what keeps the widening narrow. **Every other
  clause of ADR-0254 binds entire**, §7's ten-condition refusal and §13's no-cached-verdict rule
  conspicuously so (§10).
- **Partially supersedes** [ADR-0266](0266-a-coverage-member-records-the-constraint-the-user-stated-and-the-bound-is-proved-against-the-quote-for-the-intended-action.md)
  — **one scope, in §10's *"What the verification phase does with a quote, and coverage's other
  conditions"* entry: its *"Fired by A10"* clause, in the application to the **charge confirmation
  and the quote/charge mismatch finding** alone.** This decision has no operand for either — the
  quote a dispatch was proved against is recorded nowhere (§9) — so both are fired instead by the
  decision that pins that quote to that dispatch
  ([#2409](https://github.com/leonapivato/ai-assistant/issues/2409)), and a reader holding only §10
  waits on A10 for a comparison A10 cannot make. **Nothing else of that entry or that ADR moves**:
  *coverage's other conditions* stay fired by the decisions those clauses already name,
  `AttemptPhase.VERIFY` stays A10's by ADR-0255 §17's assignment, its three refusals bind entire,
  and §7's proof of the bound **before** the act — the proof that actually binds spending — is
  relied on here and weakened in no part.
- **Partially supersedes** [ADR-0267](0267-a-quote-is-a-record-the-goal-holds-in-order-read-from-the-output-its-declaration-names.md)
  — **one scope, in §10's first entry: the clause naming *"A10's verification of the charge
  afterwards, which is a finding rather than a prevention"*, in the application to *which decision
  performs that verification* alone.** That clause offers a reader one of the two safeguards
  standing today against a declaration naming less than the whole charge, and this decision
  performs no such verification, so a reader holding only §10 counts a safeguard that is not there;
  it is #2409's. **The finding itself is untouched** — a charge confirmed afterwards is still a
  finding rather than a prevention, and the decision that rules what such a finding does still
  fires it — and **every other clause of ADR-0267 binds entire**, §1's obligation, §3's
  declaration, §4's mint and §7's *"`quoted` is provenance"* conspicuously so, this decision
  reading no field of any of them.
- **No other ADR is superseded in whole or in part** — **ADR-0249 is not, in any scope**, this
  decision adding no field to `GoalElement`, to `ProposedElement` or to anything a planner returns
  (§2); **ADR-0265 is not**, every record §2 reads being one that decision already writes and
  enumerates; and **neither ADR-0266 nor ADR-0267 is touched in any scope but the two residual
  bookings above** — no clause of either about a member, a bound, a quote or a proof moves. §10 states the test for each ADR this decision
  reaches and shows the working: seven documents **book this subject here by name** and a
  booking **discharged** is not a clause made false; the two Protocol strengthenings are the move
  ADR-0261 §12 already ruled owes ADR-0250 §9 no record; and the one `TurnOutcome` widening is the
  move ADR-0242 §9 made and recorded nothing for.

- **Partially superseded: 2026-09-15 by ADR-0271 — two scopes, §2's `MONEY` clause and §7's gate
  statement. Nothing else in this ADR.** **The first** is §2's clause ruling that *"a criterion whose
  confirmed member is a `MONEY` one is `unestablished`"* and that *"no criterion about an amount is
  ever `met` here and no goal resting on one reaches `ACHIEVED`"*. Its stated ground is that *"the
  charge is not an operand this decision has"* — the quote a dispatch was proved against being
  recorded nowhere ([#2409](https://github.com/leonapivato/ai-assistant/issues/2409)) — and the
  superseding decision **lands that operand**, pinning the quote `ActionPolicy.decide` took the
  evidence route over to the dispatch, by value, on the ruling that dispatch was allowed by. Such a
  criterion is then **met**, **unmet** or **unestablished** on §2's own machinery, its satisfying and
  contradicting tests each gaining **one conjunct**: a charge read from the bound step's own stored
  output, at a key the operative declaration names, whose currency equals the pinned quote's byte for
  byte, whose amount is not greater than the pinned quote's, and which satisfies the confirmed
  member. **§2's `BoundKind.MONEY` limb of its `unestablished` list goes with the clause**; its five
  other limbs, its authorising rows, its confirmed member, its bound steps, its operative
  declaration, its grouping by `parameters_digest`, its ambiguity rule, its *"no fourth result
  exists"*, its *"a `FAILED` bound step is never decisive"* and every no-model-operand clause bind
  entire, and the new conjunct is stated **inside** them. The clause's closing *"No lane reads this
  as licence to compare a charge against a ceiling, a quote or anything else"* is **kept in the
  direction it was written**: the comparison is against the **pinned** quote and only then against
  the member, never against a ceiling alone and never against a quote the goal's tuple holds now.
  **The second** is §7's statement that *"the guarantee does not cover a capability whose acts make a
  charge"*, whose ground is the same missing operand: it **does** cover one, and a deployment wiring
  such a capability does a **third** thing as part of wiring it beside §7's two — it declares where
  its acts report a charge, a declaration carrying no such key satisfying this guarantee for no
  `MONEY` criterion at all. **§7's other two obligations are unchanged**, its count of **seven**
  conditions stands with none added and none removed — ADR-0267 §6's provider-side hold, condition
  (7), binding exactly that class — and its *"ratification is not implementation"* is true of the
  superseding decision on the day it ratifies. **Three further places where the replaced reading is
  available are left standing and are named so that no reader takes them for the scope**: §3's rung
  clause — *"A criterion about an amount is no longer the exception it was … what this decision does
  **not** add is the *post-hoc* comparison, and §9 names it with what fires it — **reassigned**
  there"* — stays true **word for word**, stating what *this* document does not add while the
  superseding decision adds it elsewhere, which is what the reassignment anticipates; §9's
  reassignment entry is **fired** rather than falsified, a booking discharged not being a clause made
  false, which is §10's own test; and §12's **arms 3 and 4**, each asserting a `MONEY` criterion
  `unestablished`, are **restated** by the implementing lane under the new conjunct — an agreeing
  charge yielding `met`, a disagreeing one `unmet` — each arm's other criteria, its negative half and
  its `ACHIEVED` assertions unmoved. **Every other clause of this ADR binds entire**, §§1, 2a, 3-6,
  8, 10, 11 and 13 included: the report's two fields and its fixed statements, which the superseding decision reports
  the finding through and neither widens nor renames.

## Context

### Where this comes from

This is **A10** of the six-phase task lifecycle design ([#2255](https://github.com/leonapivato/ai-assistant/issues/2255)),
and the last of its ten. Its row in revision 1 of the fit report is exact about the subject —
*"Verification against the goal's criteria, **strength proportional to consequence**, the
six-member report vocabulary"* — and about what it takes: *"Nothing. Reads strength off ADR-0016
§1's required declarations, ordered by §2."*

The six requirements, quoted:

| | |
|---|---|
| **R48** | The observed outcome is compared against the success criteria established in phase 1. |
| **R49** | Verification uses the strongest practical evidence the integration supports, and mandates no redundant read where the returned evidence already establishes the outcome. |
| **R50** | An ambiguous acceptance is never reported as a verified outcome. |
| **R51** | The report distinguishes success verified / condition prevented action / partial completion / failure established / outcome uncertain. |
| **R52** | Verification may reopen earlier work, and a repair or cancellation is **itself an action** whose authority is established rather than assumed. |
| **R53** | Closing an attempt never falsely marks the intended outcome achieved: an attempt ending is not the same event as the task completing. |

**The owner's correction of 2026-09-12 binds every clause below**: *"Producing a reply never by
itself establishes that the goal was achieved; completion criteria concern the requested outcome."*
ADR-0249 §4 states it as a prohibition and ADR-0253 §4 and ADR-0255 §8 as a boundary around
`verifies`; this decision is where the positive half is written.

**And decision 4 of the same ruling** — *"production consequential workflows carry
verification/unknown-outcome/cancellation guarantees as a rule"* — is what §7 answers.

### What is booked here, verbatim

- **ADR-0249 §4**: *"**`GoalStatus.ACHIEVED` gets no producer in this decision.** … A10 of #2255 —
  verification against the goal's criteria — is `ACHIEVED`'s only producer, and it is named here so
  that no later lane supplies one by inference."*
- **ADR-0249 §5**: *"**Which member a given attempt earns is A10's**."*
- **ADR-0253 §4**, which mints `verifies` and fences it: *"**this is not the verification A10
  lands, and the two are never conflated.** This predicate is about **one step's own output** …
  **Verification against the goal's criteria** — whether the requested outcome was reached, with
  strength proportional to consequence, and the producer of `GoalStatus.ACHIEVED` — is A10's, is
  stated over the goal's `criteria` rather than over a step's output, and is **not this field**."*
  **ADR-0255 §8 carries the same fence onto the driver** and adds *"nothing writes an
  `AttemptOutcome`"*.
- **ADR-0255 §12**: *"**Verification against the goal's criteria … and the producer of
  `GoalStatus.ACHIEVED`.** **A10.**"*
- **ADR-0261 §11**: *"Whether `set_goal_status` should refuse an `→ ACHIEVED` write over a live
  attempt … **Not decided** … the producer of `ACHIEVED` is **A10's**. **Fired by that
  decision.**"* §5 takes it.
- **ADR-0266 §10**: *"**What the verification phase does with a quote, and coverage's other
  conditions.** The owner's ruling makes the actual charge confirmed after the act and a mismatch
  *"a reported finding"*; **no clause here verifies anything, compares a charge, or writes a
  finding**, and `AttemptPhase.VERIFY` is A10's … **Fired by A10**."* §2 takes it.
- **ADR-0267 §10**, which names this decision as the other half of its own residual: *"A10's
  verification of the charge afterwards, which is a finding rather than a prevention"*. **§9
  answers it and the answer is *not here*** — the operand does not exist — with what fires it.

**And one addition the owner made after ADR-0255's waivers were reviewed** (2026-09-13, recorded on
#2255): the closing offer of a report on an unfinished goal — *"Shall I try again later?"* —
*"is the part not yet pinned by a ratified rule; it belongs to A10 (ADR-0262: what a report says
about an unfinished goal)"*. §6 takes it.

### The three owner rulings of 2026-09-14 that bound this decision, and which half of each is taken

- **The authorisation's lifetime.** *"A request is judged against the world as it is now. Forecast
  dry → booking executes → **verification confirms** → goal complete → **the authorisation ends
  with the goal**."* **The ending itself is not written here**: the owner disposed of it as *"a
  short superseding ADR, one edge + one clause"*, and this decision contradicts it in no clause —
  what it supplies is the antecedent that ruling names and the act that makes the goal terminal
  (§5). **The one case the ruling keeps open is preserved by §4**: the **uncertain-outcome** case,
  where the attempt does not end.
- **The charge is confirmed afterwards.** *"The actual charge is confirmed by the verification
  phase afterward; a quote/charge mismatch is a reported finding."* **§9 takes it and does not
  discharge it**: the quote a dispatch was proved against is recorded nowhere, so the comparison
  has no operand, and that section says so with what fires it.
- **The walkthrough runs on a simulated booking service.** M33's campsite walkthrough runs against
  an in-tree fake provider behind the real hub, phases, authorisation store and evidence; *"the
  first real consequential booking integration is M34"*. §7's gate is therefore about M34 and
  §12's arms run against fakes.

### The sequencing ruling, which binds this decision as it binds A9

The owner's ruling of 2026-09-13: *"Finish the six-phase workflow … and demonstrate it end to end
**using the existing interaction model** (subsequent turns; pauses for clarification or approval).
**Live message queuing, mid-run steering and general interruption are a separate follow-up.**"* So
verification here is a stage of a turn the user started. **Nothing below schedules, polls, wakes,
or runs outside a turn** — *"Nothing checks on its own initiative."*

### What the tree holds today, read rather than assumed, at `origin/main` `58f0797f`

- **`GoalInterpretation`** carries `constraints`, `criteria` and `conditions`, each a
  `tuple[GoalElement, ...]`. **`criteria` is read by nothing that decides anything**: ADR-0249 §7's
  revision path writes it, ADR-0250 §5's `added`/`removed` compares it element-wise, and ADR-0249
  §9's `S` labels project it — three readers, none settling anything about the goal.
- **`AttemptOutcome`** is the six members ADR-0249 §5 fixed. **`AttemptOutcome.ANSWERED` is the
  only member any code writes**, at three sites in `orchestration/engine.py`, each guarded by a
  helper whose docstring says so in terms: *"a pass failing any of them ends no attempt — **which
  member it earns instead is A10's**"*. **The other five have no producer.**
- **`GoalStatus.ACHIEVED` has no producer**: `set_goal_status` is called at exactly two sites in
  `orchestration/engine.py`, writing `ABANDONED` and ADR-0250 §13's reopen to `ACTIVE` — **two of
  the four members**, neither of which says *this was reached*.
- **`GoalAttempt`'s validator** admits a terminal `state` with both `outcome` and `ended_at`
  present and a non-terminal one with both absent — **so an `AttemptOutcome` cannot be written
  except in the transition that ends the attempt**, which is why §4 states the two together.
- **`CoverageMember` still carries `argument` and no `kind`**, and `PermissionRuling` carries no
  `authorised_goal`: ADR-0254 and ADR-0266 are **ratified and not implemented**, so §2's operands
  are contracts rather than code today, which §11 states as a sequencing fact rather than leaves
  to be discovered.
- **ADR-0261's lanes have not landed**: `DriveWithheld`, `ClaimRefused`, `effect_in_flight`,
  `close_goal_abandoned` and `has_outstanding_effect` are in no file of `src/`.
- As dated observations: `wire/envelope.py`'s `PROTOCOL_VERSION` reads **44**;
  `PlanExport.schema_version` reads `Literal[12]`; the plan store's `_SCHEMA_VERSION` reads **4**;
  the audit trail's reads **2**, openable from `{1, 2}`.

### The gap this closes, stated as the failure the corpus has today

**A goal that was fully served stays `ACTIVE` for ever.** ADR-0249 §4 states the cost in terms and
takes it deliberately — *"Until A10 lands, a goal that was fully served stays `ACTIVE` … That is a
legible gap and an honest one; a status that claimed achievement nothing verified would be
neither."* So a completed objective is indistinguishable on every surface from one nobody has
started.

**And an attempt says only that it answered.** The one `AttemptOutcome` any code writes is
ADR-0249 §5's *"the attempt produced an answer and **nothing was verified**"*, so a booking that
succeeded, one that failed and one whose fate is unknown are reported alike. **R48 is unmet not
because the comparison is hard but because nothing reads `criteria`.**

**The consequence, named because it is the one that costs.** ADR-0255 §13's gate holds a
consequential capability out of production until its **verification**, uncertain-outcome and
cancellation guarantees exist. A8's and A9's are ratified (ADR-0259, ADR-0261); this is the third,
and until it lands the gate cannot be met by any capability at all.

### What this decision is not allowed to settle

Golden rule 5's Protocol change is stated and argued here and implemented by the lanes §11 cuts,
and nothing else. This decision **writes no retry policy** (A8's, ADR-0259 §10), **registers no
booking integration** (ADR-0154, and §7's gate), **designs no quote** (ADR-0267),
**writes no `GoalStatus.BLOCKED`** (A3's), and **does not write the goal-terminal ending of an
authorisation** the owner ruled on 2026-09-14 — a later ADR's, its number elided rather than cited
(ADR-0088 §6 Tier 1) and its lane
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

> **Normative — the comparison and the commits are two moments, and separating them is what makes
> the circularity unreachable rather than merely forbidden.** The **comparison** — §2's three
> results over every criterion, and §3's rung — is evaluated in the turn's
> **`AttemptPhase.VERIFY`** (ADR-0249 §6), **after the walk has ended** (ADR-0255 §1) and **wholly
> before the composing stage** (ADR-0170 §1). At that instant **no reply exists**, so no
> implementation can take one as an operand. **The commits §4 and §5 name are taken after the
> composing stage**, from the values the comparison already fixed and from **no value the reply
> produced**, which is ADR-0249 §16's arm 1 stating the same sequence for the member the tree
> writes today — *"written first at §11's site and moved there by a same-turn `commit_attempt`
> once the answer exists"*.

> **Normative — the only fact the commits read about the reply is **that one exists**.** §4's
> ending rule reads whether the turn composed a reply that completed (ADR-0173 §6) and **reads
> nothing of its content**. **No lane passes a `ComposedReply` or any part of one into the
> comparison, re-runs the comparison after composing, or lets a composing failure change which
> member §4's limbs yield** — a composition that did not complete ends no attempt at all.

**The owner's correction is made structural here rather than restated.** ADR-0253 §4 fenced
`verifies` because it is *"exactly the value a later lane would reach for when asked whether a goal
was achieved"*. The same reach exists one level up, the cheapest thing to verify against being the
answer the system just wrote; stating the **order** — the reply does not exist yet — closes it by
construction and costs nothing, ADR-0249 §6 already putting `VERIFY` after `EXECUTE`.

> **Normative — verification writes no interpretation and reads no model output.** It records no
> `GoalInterpretation` revision, rewrites no `GoalElement`, marks no `GoalEvidence` row, and calls
> no `Planner.plan`. ADR-0252 §10's rule binds unchanged, so a criterion that turned out not to
> hold is **not** edited, dropped or re-grounded; what changes is the attempt's outcome and the
> goal's status.

> **Normative — a goal carrying no criterion is not thereby verified.** An empty `criteria` tuple
> is the ordinary shape of a goal at revision 1, and §4's `fully_met` requires **at least one**
> criterion, so such an attempt reaches `ANSWERED` at rung 0 or 1 and `UNCERTAIN` at rung 2 and
> **never `VERIFIED`**. **No lane mints a criterion, synthesises one, or reads an empty tuple as
> *every criterion met*.**

**An empty tuple could be read as a vacuous truth and that reading is refused by §4's order rather
than by a special case.** *"What is two plus two"* opens a goal whose criteria are empty; the
honest report is that an answer was produced, which the fit report's §I.3 concluded — *"it does not
claim the answer was **verified** … This is a smaller claim than revision 0 made and it is the
honest one."*

### 2. What establishes a criterion: three conjuncts, and no model authors any of them

> **Normative — the postcondition is the *tool's* declaration and never the model's.**
> **`ToolDefinition` gains `postconditions`**, a possibly-empty `tuple[StepVerification, ...]`
> (ADR-0253 §4) defaulting to the empty tuple, **declared by whoever registers the tool** and
> stating what a **successful** invocation establishes about its own output. It is ADR-0016 §1's
> own shape — *"Declared, not inferred"* — and the empty tuple is the **fail-closed** claim: a tool
> declaring none establishes nothing here, so no criterion resting on it is ever **met**. **A
> member whose `kind` is `VerificationKind.OUTPUT_PRESENT` is not constructible here**: *"the
> producing step's `output` is not `None`"* is the circularity R48 exists to close, one level down
> from the reply. **`FIELD_PRESENT` and `FIELD_EQUALS` are admitted**, each naming a key of the
> output object and, for the second, the literal it must equal **byte-exactly** as ADR-0253 §4
> compares it. **No lane adds a kind, relaxes the comparison, mints a postcondition for a tool that
> declared none, infers one from a `parameters_schema`, or reads the `OUTPUT_PRESENT` refusal as a
> criticism of `verifies`'s own vocabulary** (ADR-0253 §4).

> **Normative — no model supplies any operand of this comparison, and the way that is achieved is
> that there is nothing for one to supply.** **`GoalElement` gains no field, `ProposedElement`
> gains none, `Planner.plan`'s roster and return do not move, and no value a planner returns is
> read by any clause of this decision.** A criterion is not *bound* to an act by anything a model
> wrote: **it is established, or it is not, by three facts the record already carries** — **the
> user's own confirmation** of a typed value, **the authorisation** that proved the concrete call
> against that value, and **the tool author's own declaration** of what its success establishes.
> **No lane adds a field, a label, an index, a predicate or a pointer by which a model could
> associate a criterion with an act**, and **no lane reads `IntendedAction.serves`** — ADR-0265 §3
> obeyed word for word, *"a stale entry … truthful and harmless"* staying true because nothing
> here reads one (§2a).

> **Normative — the attempt's authorising rows, which are exactly the rows its own steps name.**
> Let the attempt's **authorising rows** be the `Authorization` rows obtained by taking every step
> of every execution `GoalAttempt.execution_ids` names whose pinned `PermissionDecision` (below)
> carries a **route-(d) `ALLOW`** — ADR-0254 §7's discriminator, *"`resolves` unset,
> `authorised_by` set, `authorised_subject` set, `authorised_goal` **set**"* — whose
> `authorised_goal` is this goal, resolving each distinct `authorised_by` through
> **`AuthorizationResolution.resolve`** (§3), and keeping the rows that come back with `origin`
> **`CONFIRMED`** — ADR-0254 §1's path (i), *"put to the user as a question and answered"*, the
> only route on which the user saw the rendered values and assented (ADR-0254 §11). **The
> disposition is *not* re-tested here, and that is deliberate**: ADR-0254 §7 makes `record` refuse
> a route-(d) row unless the store's row was `ESTABLISHED` and live at `decided_at`, so the pinned
> decision **is** the proof of the row's standing at the moment the act ran, and a row **revoked or
> superseded afterwards** must not retract a verification of something that already happened. **No
> lane reads a present disposition as evidence about a past dispatch, in either direction**, and
> `origin` is the field ADR-0254 §1 has a correction transcribe unchanged, so it is stable under
> every later edge. **The set is enumerable from the attempt alone and
> this decision reaches no further**: a row **no step of this attempt acted under** is not an
> authorising row, is not looked for, and establishes and refuses nothing — **no lane enumerates
> the goal's rows, calls `standing`, `recent` or `live_for`, or reads a row by any route but a
> pinned decision's own pointer.** **A step whose decision is a route-(a), (b) or (c) `ALLOW`, or
> carries no `authorised_by` at all, contributes no row** — the cost §2a states.

> **Normative — the criterion's confirmed member, which is *unique* among those rows or there is
> none.** Let a criterion's **matching members** be every `CoverageMember` **M** of every
> authorising row **R** whose **`basis.span` equals the criterion's own `span` byte for byte**, no
> fold applied, as ADR-0237 §3 compares a stated string. **The criterion has a confirmed member
> exactly where it has *one* matching member**, which is then that M, its row that R and **its
> `kind` the criterion's kind** (ADR-0266 §3).
>
> **Where the criterion has no matching member, and equally where it has more than one, it is
> `unestablished`**, and the second half is the load-bearing one. ADR-0254 refuses two live rows
> only for one goal **and one declaration**, so two rows the attempt acted under — a quote tool's
> and a booking tool's — may each carry a member on one span; and ADR-0266 §3's *"No two members of
> one `Authorization` carry the same `kind`"* leaves two members of **one** row free to rest on one
> span at two kinds. **A precedence rule between them would be this decision inventing which of the
> user's own statements governs**, which is R50's *"An ambiguous acceptance is never reported as a
> verified outcome"* read at the operand rather than at the verdict. **No lane orders the rows,
> unions them, prefers the earliest, the narrowest or the one whose step succeeded, or evaluates
> the criterion once per matching member.** A criterion carrying no `span` at all — every ground
> but `USER_STATED` (ADR-0249 §1) — has no matching member by construction. **No lane matches a
> span by prefix, containment, normalisation, similarity or a model call.**

> **Normative — the criterion's bound steps, and what the record already proved about them.** Let
> the criterion's **bound steps** be every step that contributed **R** to the authorising rows —
> those whose route-(d) `authorised_by` is R's `id` — **and no other step of any execution**.
> **That the call's own arguments fit M is proved where it is decided and not here**: ADR-0254 §13 takes the coverage comparison *"at `ActionPolicy.decide`, on the concrete
> request, at every dispatch"*, and ADR-0254 §7 makes `AuditTrail.record` **refuse** a route-(d)
> row unless ten conditions hold over the row the store returned — the established disposition,
> both ends of liveness, the by-value declaration, the account, the destination set, the goal and
> the recomputed subject digest among them. **Reading that record afterwards is not a cached
> verdict and no lane treats it as one**: ADR-0254 §13's prohibition is on **reusing** a verdict to
> authorise a further dispatch, and nothing here authorises anything.

> **Normative — the operative declaration is the one *pinned to the act that ran*, and never the
> registry's.** The `ToolDefinition` a bound step is compared against is the **whole definition
> embedded by value in the `PermissionDecision` the step's `approval_ref` names** (ADR-0021 §1:
> *"There is no name left to rebind"*), read through the audit trail the engine already holds —
> **never a definition the registry holds now**, which a restart may have re-registered under the
> same id, and which would make a stored output change verdict without any record changing. **For
> a step satisfied from an earlier completed effect** — `SUCCEEDED` with `satisfied_by_execution`
> and `satisfied_by_step` and possibly **no `bound_tool` of its own** (ADR-0259 §2, §9) — the
> operative definition, **and the decision whose route and `authorised_by` are read above**, are
> the **holder's**, followed by exactly the provenance §3 follows for the rung, and the borrowed
> `output` is the operand. **A bound step naming no decision, or naming one the trail does not
> hold, establishes nothing** — fail-closed and not an error. **A store *failure* is never
> converted into a verdict**: an `AuthorizationError`, an `AuditError` or any other failure of the
> two reads propagates with its cause, and **no lane reports a broken trail or an unreadable
> authorization as `UNCERTAIN` or `ANSWERED`.**

> **Normative — a criterion is, at the instant the comparison runs, exactly one of three, and the
> three are total by construction.** Over the criterion's bound steps, and over no other step of
> any execution:
>
> Call a bound step **satisfying** where it stands `SUCCEEDED`, its operative definition declares
> **at least one** postcondition, and **every** declaration of that definition holds over its
> stored `output`. Call it **contradicting** where it stands `SUCCEEDED` and **some** declaration
> of its operative definition does **not** hold — **and in no other case**. **A `FAILED` bound step
> is never decisive**: it neither satisfies nor contradicts, and a criterion resting on it alone is
> `unestablished`. **Only an act's own answer establishes or refuses a criterion**, which is this
> section's rule read to its end — *"a `SUCCEEDED` step records that the tool returned, and **what
> it returned** is the operand"* — and a failure returns nothing, ADR-0029 §3 requiring that a
> failed result carry no output. **Two distinct facts make a failure indecisive and neither is a
> caveat.** For a **side-effecting** call, no failure proves non-occurrence: ADR-0029 §4 commits a
> timed-out `NATURAL` call `FAILED` on the ground that *"whether it acted does not change what a
> repeat does"* — **not** that it did not act — and §3 makes *"an exception escaping the tool
> implementation"* an `INTERNAL` failure, which a booking tool raises as readily **after** the
> provider created the reservation, while parsing its answer, as before it called. For a **read**,
> the failure is about the **observation** and not about the world: a status check that cannot
> reach its provider — `UNAVAILABLE`, `RATE_LIMITED` — establishes neither that the reservation
> holds nor that it does not, and §1 fixes a criterion as a proposition about the **outcome**
> rather than about the work. **The cost is stated and booked**: a booking a provider genuinely
> refused reads `unestablished` and its attempt `UNCERTAIN` rather than `FAILED`, the record
> carrying no fact that separates *refused* from *acted and then crashed* (§9). **An established
> failure stays reachable and on better evidence** — a step that stands `SUCCEEDED` under an answer
> its own tool's declarations refuse, which is the path a provider's *"rejected"* takes. **Nothing
> a planner returns is read by either test**: not a label, not an `intended_action`, not a step's
> position, not its `verifies`. **A step is satisfying, contradicting or neither on what the
> tool's author declared and on what the provider returned, and on nothing else.**
>
> **The bound steps are grouped by *the call each made*, the grouping is the policy's rather than
> the planner's, and a group that does not agree with itself establishes nothing.** Two bound steps
> are of **one call** where their pinned decisions carry the same
> **`ActionRequest.parameters_digest`** (ADR-0021 §1's embedded value, computed by the policy over
> the concrete request and written by no model), and of **different calls** otherwise. Call a bound
> step **decisive** where it is satisfying or contradicting, and every other one — `PENDING`,
> `SKIPPED`, `RUNNING`, `INDETERMINATE`, **every `FAILED` step**, and a `SUCCEEDED` step under a
> definition declaring nothing — is not. A call is then **satisfying** where it
> has a decisive step and **every** one of its decisive steps is satisfying, **contradicting**
> where it has one and every one is contradicting, and **ambiguous** where it has both — **no order
> breaks the tie, and the last step does not govern**.
>
> - **Unmet** — **some** call is contradicting.
> - **Met** — no call is contradicting, **no call is ambiguous**, and **some** call is satisfying.
> - **Unestablished** — otherwise: **some call is ambiguous**; the criterion's kind is
>   **`BoundKind.MONEY`** (below); it has no confirmed member; it has no bound step; or no bound
>   step is satisfying or contradicting — every one `PENDING`, `SKIPPED`, `RUNNING` or
>   `INDETERMINATE`, or `SUCCEEDED` under a definition declaring **nothing** or none this decision
>   can read.

**The digest groups the steps, and a group whose own answers disagree establishes nothing.** Two
*successful* dispatches of one call whose answers disagree — one satisfying its declarations, one
refusing them — cannot be ordered into a verdict without this decision choosing which answer of the
provider's governs, so the group is **ambiguous** and its criterion `unestablished`, R50 read at the
operand. **A failure inside a group settles nothing either way** (above), so a failure beside a
success leaves the call satisfying: what that leaves open is whether the failed dispatch **also**
took effect — a possible **duplicate**, which is A8's idempotency question (§9) and not a claim
about whether the outcome holds — and whether a criterion's proposition needed a **second** act,
which §9 books as the arity residual. **A second, *different* act** — two rooms on different
dates — is a different call, so its success clears nothing of the first. **`PlanStep.intended_action`
would answer the grouping question and is refused**: a planner writes it, and a verdict turning on
it is the allow ADR-0249 §7 forbids (§2a).

> **Normative — a criterion whose confirmed member is a `MONEY` one is `unestablished`, and this
> decision states it as a rule rather than as a caveat.** What such a member states is a **ceiling
> on what the act charges**, and **the charge is not an operand this decision has**: the quote a
> dispatch was proved against is recorded nowhere (§9), and holding the charge against the ceiling
> alone would pass a charge that exceeded the quote while staying under it — the mismatch the
> owner's ruling of 2026-09-14 calls a finding. **So no criterion about an amount is ever `met`
> here and no goal resting on one reaches `ACHIEVED`**, which is fail-closed, is why §7 says the
> gate's verification guarantee does **not** cover a capability whose acts make a charge, and is
> booked in §9 — where it is **reassigned** to the decision that lands the operand, by the two
> scopes the header states. **No lane reads this as licence to compare a charge against a
> ceiling, a quote or anything else.**
>
> **No fourth result exists, no result is a degree, and no lane reads *unestablished* as either of
> the other two**; and **no step of another goal, another row, another route or no route at all is
> ever a bound step.**

> **Normative — the predicate is evaluated in code over a step's own stored `output`, and neither
> prose nor a status is ever an operand.** ADR-0253 §4's *"the comparison is arithmetic"* binds
> word for word, so **no lane evaluates a declared postcondition by a model call, a prompt, a
> similarity measure, a fold, a coercion or a tolerance**. **And no criterion is established from
> a `GoalElement.text`, a `GoalInterpretation.outcome`, an `IntendedAction.intent`, a
> `StepFailure.message`, a tool description, a composed reply or any other free text, nor from
> `StepStatus.SUCCEEDED` alone** — a `SUCCEEDED` step records that the tool returned, and **what it
> returned** is the operand.

> **Normative — `PlanStep.verifies` is read here by nothing, and the three values are three
> facts.** ADR-0255 §8 fixes that a step's own `verifies` is evaluated at **exactly two** places,
> and **this decision adds no third reader of that field**. A step's `verifies` is the **plan's**
> expectation of that step; a tool's `postconditions` are the **definition's** statement of what
> its own success establishes; a confirmed coverage member is the **user's** statement of what they
> asked for. **Sharing one field would be one carrier for two facts**, ADR-0251 §3's defect read in
> the other direction.

### 2a. Why no model holds an allow here, what a met criterion establishes, and what it does not

> **Normative — the three conjuncts have three authors and none of them is a model, which is how
> ADR-0249 §7 is obeyed rather than argued around.** *"A model may never clear a permission, a
> coverage test, a **prerequisite** or a dependency"* is categorical, and establishing that the
> goal was achieved is the `ACHIEVED` write's prerequisite. **The user** confirmed the typed value
> (ADR-0254 §1's path (i), ADR-0254 §11's rendered values and the answer that settles the row);
> **the policy and the trail** proved the concrete call against it (ADR-0254 §13, §7); **the tool's
> author** declared what a success establishes (ADR-0016 §1). **So no model authors the association
> between a criterion and the act that establishes it, and nothing a planner writes about a plan,
> a step or an act moves any criterion from `unestablished` to `met`** — not a label, an index, a
> predicate, an `intended_action` or a `serves` entry — which is the property the earlier drafts
> argued for and did not have (Alternatives).

> **Normative — what that guarantee does *not* reach is the interpretation itself, and this
> decision states the limit rather than overclaiming past it.** §1 fixes that a goal's criteria
> **are** its current `GoalInterpretation.criteria`, and ADR-0249 §7 gives the model the
> interpretation: a `USER_STATED` criterion's **text and its `span` are both the planner's**, and
> §7 validates only that the span occurs in the user's own words. So a planner may pair a span the
> user really spoke — *"Sunday"* — with a criterion text about **another fact**, and §2 will find
> the confirmed member on that span and report the criterion **met** though its text was never
> compared to anything. **That is a misinterpretation of the goal, not a verification of an act
> that did not happen**: everything §2 establishes about the act — the user's confirmed value, the
> proof of the call against it, the tool's own declaration — remains true, and what is wrong is
> *which criterion the goal was taken to have*, which is ADR-0249 §7's own asymmetry and ADR-0250
> §5's announcement and revision path, never this comparison's. **ADR-0249 §7 is obeyed on its own
> words rather than read past them**: the sentence *"A model may never clear a permission, a
> coverage test, a prerequisite or a dependency"* stands beside, in the same clause, *"A model may
> interpret meaning, **resolve a reference**, assess whether a record supports a proposition, and
> **raise** a question"* — and a `USER_STATED` element's `span` is a reference the model resolves
> and **code checks**, ADR-0249 §7 dropping any span that is not a span of this turn's own request.
> **Reading a model-authored criterion as a cleared prerequisite would make §7 contradict itself**,
> since the same section gives the model the interpretation the criteria are part of; what §7
> forbids is taking a prerequisite *on a model's word*, and no conjunct of §2 is a model's word.
> **No lane closes the residual here by reading a criterion's text**, which would be the prose
> comparison §2 refuses, **and no lane reads §2a as a claim that a planner cannot affect a verdict
> at all**: it cannot affect *this* one, given the criteria; the criteria are the model's own
> reading, and §9 books what would put them beyond it.

> **Normative — `IntendedAction.serves` is read by nothing here, and ADR-0265 §3 is left entire.**
> That section rules that *"`serves` gates nothing"*, that **no lane** *"derives an intended action
> from `serves`"*, and that a stale entry is *"truthful and harmless"* **because no mechanism reads
> the staleness at all**. **This decision reads no `serves` entry and no `PlanStep.intended_action`
> either**: the **row** the act was authorised against and the **pinned decision** that names it
> are the whole of the binding, and the call's own `parameters_digest` is the whole of the
> grouping. **ADR-0265 gains no reader anywhere**, of `Goal.intended_actions`, of `serves` or of a
> step's action label.

> **Normative — what a met criterion establishes, and what it does not.** A met criterion
> establishes **three** things and no fourth: that the user **confirmed** the typed value it rests
> on; that the call which ran was **proved against that value** before it ran; and that the act
> **took effect in the terms its own author declared**. **It does not establish that the provider
> did what it said it did** — a booking service answering `{"status": "confirmed"}` for a stay it
> never made satisfies every declaration its author could write — **and no lane reads `VERIFIED`
> as a statement about the world beyond the act's own answer.** An independent confirmation is a
> **read of a later attempt** (§3), and **no lane takes one inside this phase.**

> **Normative — an act confirmed for itself rather than against a row establishes no criterion,
> and the cost is stated rather than discovered.** A step authorised by route (a) — the user asked
> about **that concrete call** and answered (ADR-0254 §7's partition) — carries no `Authorization`
> and therefore no confirmed member, so every criterion of that goal is `unestablished` and the
> attempt reaches `UNCERTAIN` at rung 2. **That is fail-closed and deliberate**: a per-call
> confirmation records a **digest** of the arguments and not a typed value a criterion can agree
> with, so a comparison over it would have no operand. **No lane widens the bound steps to another
> route, reads a route-(a) confirmation as a coverage member, or synthesises one from a
> `parameters_digest`**, and §9 books what closing this would take.

> **Normative — an unestablished criterion is never reported as met, which is R50 and is a
> property of the three results rather than a rule about ambiguity.** An answer no declared
> postcondition holds over leaves the criterion **unmet** or **unestablished**, and §4's function
> admits **no path** from either to `VERIFIED` or to `GoalStatus.ACHIEVED`. **No lane resolves an
> ambiguity by a second guess, by a model, by a default, or by widening the comparison.**

### 3. Strength proportional to consequence: three rungs off the declarations, and the phase calls nothing

> **Normative — the strength a goal's verification owes is fixed by the consequence class of what
> the attempt **actually did**, and the class is read off declarations that already exist.** The
> class is computed over **every step of every execution `GoalAttempt.execution_ids` names that
> either reached a committed `→ RUNNING` claim** — ADR-0148 §9's boundary, *"There is no egress
> outside a claimed step"*, with ADR-0014 §4's ordering — **or stands `SUCCEEDED` carrying
> ADR-0259 §2's satisfaction identifiers** (below), and over no other step. **A step a plan
> declared and no walk claimed contributes nothing**, because nothing happened.

> **Normative — a step satisfied from an effect the goal already completed contributes the
> consequence of the act it was satisfied from, and the provenance is followed rather than
> assumed.** ADR-0259 §2 commits such a step **`→ SUCCEEDED` with no `→ RUNNING` claim of its
> own**, carrying **`satisfied_by_execution`** and **`satisfied_by_step`** (ADR-0259 §9). Its rung
> — and, under §2, its operative declaration — comes from **the step those identifiers name**, and
> **where that step cannot be read the attempt is at rung 2**. **Reading it at rung 0 is the error
> this clause closes**: its borrowed `output` is an operand under §2, so an attempt could verify
> against a consequential act's answer while classified as having done nothing.

> **Normative — a claimed step whose own pinned decision cannot be read is at rung 2, which is the
> same fail-closed answer the clause above gives for an unreadable holder.** Where a step reached a
> `→ RUNNING` claim and its `approval_ref` names a decision the trail does not hold, or names none
> at all, **neither its definition nor its `egress_binding` can be read**, so nothing says the act
> was not irreversible or disclosing: the step **contributes rung 2**, which is the whole of what
> it contributes. **§2's silence about such a step is not in tension with this**: there
> it establishes no criterion, which is a statement about *evidence*, and here it withholds no
> consequence, which is a statement about *strength* — both fail closed, in the directions their own
> sections run. **No lane reads an unreadable decision as rung 0 or rung 1**, and a store *failure*
> is still propagated rather than classified (below).

> **Normative — the three rungs, and they are read off `ToolDefinition`'s required declarations.**
> For each such step whose pinned decision *can* be read, the `ToolDefinition` recorded for its
> committed **`bound_tool`** and the `PermissionDecision` its **`approval_ref`** names:
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
> lexicographically.** That section overrides all four comparison operators for exactly this
> reason — *"`StrEnum` members **are** strings, so they already compare — **lexicographically**,
> which makes `RiskLevel.CRITICAL < RiskLevel.LOW` evaluate to `True`"* — and the same inversion
> sits under `Reversibility`. **The comparison is `definition.reversibility >
> Reversibility.REVERSIBLE`** under those overridden operators, and **no lane substitutes a rank
> table, a membership test against a hand-written set, or a string comparison.**

> **Normative — `discloses` is read beside `reversibility` and neither stands alone**, ADR-0016
> §2's own conclusion: *"a `REVERSIBLE` tool with a non-empty `discloses` performed an irrevocable
> disclosure while making a revocable change … Reading both fields is not an implementation
> detail."*

> **Normative — `risk_level` is not read.** Risk is the scale a *policy* thresholds to decide
> **whether to ask** — ADR-0016 §2's *"The canonical policy sentence is a threshold"* — and the
> question here is **what an act did**, which `side_effecting`, `reversibility`, `discloses` and
> the binding answer directly. **No lane adds a `risk_level` limb to the ladder**, and a deployment
> that wants a stricter rung declares a stricter `reversibility`.

> **Normative — what each rung owes, stated over the criteria and never over a call.**
>
> - **Rung 0** owes nothing beyond §4's function. Its attempt earns `ANSWERED`,
>   `CONDITION_PREVENTED` or `FAILED` and **never `VERIFIED`**, whatever the criteria say, because
>   nothing was done for a criterion to be about.
> - **Rung 1** owes the criteria §2's three conjuncts establish from what the attempt already
>   recorded, and
>   **nothing more**. An unestablished criterion there leaves the attempt `ANSWERED` or `PARTIAL`
>   and **not `UNCERTAIN`** — nothing happened in the world for the record to be uncertain about.
>   **§4's limb 3 says the same thing from the other side and no clause qualifies either**:
>   `UNCERTAIN` turns on **the rung and on nothing else**, so it is unreachable here.
> - **Rung 2** owes verification against the criteria, and an unestablished one is **uncertainty**:
>   §4's limb 3 yields `UNCERTAIN`, and **an unverified consequential effect earns no `VERIFIED`,
>   no `ACHIEVED` and no statement that the outcome was reached.** **`unverified` has exactly one
>   sense here and it is the criteria's**: an effect the goal's own criteria establish (§2) *is*
>   verified, which is limb 5's whole condition — and an effect the record leaves genuinely
>   *possible* is an `INDETERMINATE` step, beside which no attempt ends at all (§4).

> **Normative — verification performs no call *on the world*, and this is the whole of how R49 and
> the owner's ruling are one rule.** This phase **makes no model call, no tool call, no
> `StepRunner` or `StepExecutor` entry and no `ToolInvoker.invoke`**; it reads the system's own
> stored records — the plan store's; the audit trail's ruling, for §2's pinned declaration and its
> route; and the `Authorization` row that ruling names, through **`AuthorizationResolution`**, the
> `resolve(id)`-and-nothing-else face ADR-0254 §16 already mints for the trail and which **cannot
> name `record`, `settle` or `live_for`** — and writes at most the two commits §4 and §5 name.
> **That read seam is the one collaborator this decision adds to the engine, and it is a read**:
> ADR-0058's construction contract is about `StepExecutor`, gains nothing here and is untouched,
> and §11 says which lane wires it. **Reading the record of an act that
> already happened is not checking on one's own initiative**: what the owner's ruling of 2026-09-13
> forbids is the system going and looking, and **an independent read that a criterion needs is a
> step of a later attempt**, planned, authorised and claimed through the standard phases. **No lane
> gives this phase a collaborator that calls anything, a budget, a deadline or a retry.**

**Making the rung decide what is *owed* rather than what is *performed* is what keeps S1 at one
planner call.** Revision 1 §I.2 named the tension — *"a mandatory second model call to verify would
break the one-pass case"* — and tiered the call; the owner's later ruling removes it entirely. What
rung 2 buys is not a lookup; it is the **refusal to say verified**.

> **Normative — the guarantee this decision provides is met for a class only where that class's
> acts are authorised the way §2 reads, and the case that is not is named.** §7's gate requires the
> verification guarantee *"for its class"*. **A capability whose consequential acts are authorised
> per call rather than against a confirmed row establishes no criterion at all** (§2a), so its
> attempts reach `UNCERTAIN` at rung 2 and never `VERIFIED` — the guarantee is *met* for such a
> class in the sense that the decision never claims what it cannot establish, and it buys that
> class nothing. **A criterion about an amount is no longer the exception it was**: the user's
> `MONEY` member is proved against a quote **before** the act (ADR-0266 §7), which is the
> guarantee that binds the charge; what this decision does **not** add is the *post-hoc*
> comparison, and §9 names it with what fires it — **reassigned** there to the decision
> that lands its operand. **This adds no condition to ADR-0255 §15 item 19's count**, which §7
> reads as **seven**: it states what this decision's own guarantee covers, which is what that gate
> already asks of it.

### 4. Which `AttemptOutcome` an attempt earns, when it is written, and when the attempt ends

> **Normative — three derived facts the limbs are stated over, named once so the limbs read as one
> rule.** Over every step of every execution `GoalAttempt.execution_ids` names, and over the
> criteria §1 fixes with §2's three results: **`failed`** is true where any such step stands
> **`FAILED`**; **`blocked`** is true where any such step stands **`SKIPPED`** carrying
> `SkipReason.UNMET_DEPENDENCY` or `SkipReason.APPROVAL_DENIED`, whichever source status it was
> committed from; and **`fully_met`** is true where the goal carries **at least one** criterion,
> **every** one **met**. **None of the three is stored, none is a field and no consumer reads
> any** — ADR-0252 §6's own posture toward its four tests, computed where they are used.
>
> **And there is no fourth, because whether a failed call may have acted is a fact this phase
> *reads* and never *derives*: the step's stored status already is it.** ADR-0032 §2 rules that question at
> the seam that knows, in one line — the outcome of a translated `ClassifiedToolError` is
> **`INDETERMINATE`** where the tool reported `effect_may_have_committed` **and** the registry's
> `definition.interrupted_outcome` is `INDETERMINATE`, and **`FAILED`** otherwise — over a fact
> that is *"keyword-only and has no default … The raiser answers it explicitly, every time"*; and
> that section refuses a second copy of it in terms: *"A residual boolean on `ToolFailure` would be
> a second spelling of the same thing, free to disagree with the field the executor actually
> reads."* ADR-0014 §4 is the direction the rule runs in and the one ADR-0032 §2 cites — `False`
> *"silently records a possibly-committed effect as certainly-nothing-happened — the one direction
> ADR-0014 §4 refuses to guess in"*. **So this phase reads the status the seam committed and adds
> nothing to it**, in both directions:
>
> - a step standing **`FAILED`** is one the seam **ruled** against the tool author's own
>   declaration, and the limbs treat it exactly as §2 already does — **an absent answer, never a
>   disproof**, and never an effect this phase manufactures. **Deriving *a possible effect* from
>   every side-effecting `FAILED` step is what would collapse ADR-0032 §2's ratified
>   `FAILED`/`INDETERMINATE` distinction**, making a definite refusal and an unknown outcome reach
>   one representation. **No lane restores such a fact**, in limb 1, in limb 3, or anywhere else.
> - a step standing **`INDETERMINATE`** is the corpus's own spelling of *a possible effect*, and it
>   reaches **no limb at all**: the **third ending condition** below refuses to end an attempt
>   naming one, `PlanStore.commit_attempt` refuses the transition in the same indivisible step, and
>   **no `AttemptOutcome` is written on that turn**. **`VERIFIED` is therefore unreachable beside a
>   possible effect, and with it `ACHIEVED` (§5)** — reached by the attempt not ending rather than
>   by a conjunct on limbs 4 and 5, which is also what keeps ADR-0259 §4's acts 3 and 4 reachable
>   and is why **this decision never writes `EFFECT_UNRESOLVED`** and never reads a `FAILED` step
>   as a trigger for one.
>
> **This decision therefore adds no `core` field, no conjunct to limb 4 or limb 5 and no
> prerequisite to §7's gate.** The one case the corpus genuinely leaves open — a `side_effecting`
> call whose **unclassified** escaping exception became `INTERNAL`/`FAILED` (ADR-0029 §3 as
> ADR-0032 amended it: *"a fact that is absent or not a bool refuses the whole carrier for INTERNAL
> and FAILED"*), so that no raiser answered the question at all — is **ADR-0032's to close and not
> this decision's to guess**, and §9 books it by name with the issue that fires it.

> **Normative — which member the attempt earns, decided by §2's three results over the criteria §1
> fixes, by §3's rung, and by those three facts, in this order and over nothing else.**
>
> 1. **`FAILED`** — **no** criterion is met, and either **some** criterion is **unmet**, or
>    **`failed`** and the attempt is **not at rung 2**.
> 2. **`CONDITION_PREVENTED`** — **no** criterion is met, **no** criterion is **unmet**,
>    **`blocked`**, **not `failed`**, and the attempt is **not at rung 2**. The plan's own declared
>    conditions, or the user's own refusal, refused the work, and nothing consequential ran.
> 3. **`UNCERTAIN`** — the attempt is at **rung 2** (§3), **no**
>    criterion is **unmet**, and **not `fully_met`**: a consequential act ran and the
>    record does not establish that every criterion holds.
> 4. **`PARTIAL`** — **some** criterion is met and **some** criterion is **not met**.
> 5. **`VERIFIED`** — **`fully_met`**.
> 6. **`ANSWERED`** — otherwise, which is exactly ADR-0249 §5's own definition of the member: a
>    reply exists, **no step failed** and **no condition blocked**, and nothing was verified.
>
> **The six limbs are total over the three results, the rung and the three facts.** **No seventh
> limb, reordering or override is added.** `AttemptOutcome` gains **no member**: the vocabulary is
> ADR-0249 §5's six as ADR-0261 §3 made them **seven**, this decision reaches **six** — the clause
> below says which one it does not — and of
> those six it gives **five** the producer they have never had.

> **Normative — a step is not a criterion, and `failed` decides nothing where the criteria decide
> it.** Limbs 4 and 5 read the criteria alone. **A `FAILED` step of a criterion's own call leaves
> that criterion `unestablished` rather than `unmet`** (§2), a failure returning no
> answer to hold a declaration against — **so what limb 1 reports as an established failure is a
> criterion some *successful* step's own answer refused**, and a failed step is reported by limb 1
> only where no criterion is met, no side-effecting step may have acted, and the attempt is at rung
> 0 or 1; a `FAILED` step **no
> criterion is about** says that a step of the *plan* did not
> complete, and §1 fixes that a goal's criteria *"and nothing else"* are what success means. **So
> an attempt whose every criterion is met is `VERIFIED` though a step failed beside it** — the
> record is that the requested outcome was reached, which is what §6's statement for that member
> says and all it says — and **`failed` is read only by limb 1, which needs it because an attempt
> with no criterion at all must not report ADR-0249 §5's *"no step failed"*.** **No lane adds a
> `failed` conjunct to limb 4 or limb 5**, which would make §6's `PARTIAL` statement false of an
> attempt that established everything it was asked to.

> **Normative — the order is the rule, and five of its positions are load-bearing.**
> **`FAILED` and `CONDITION_PREVENTED` precede everything** because such an attempt may also have
> every criterion unestablished and would otherwise fall to `ANSWERED`, whose ratified definition
> asserts *"that no step failed and that no condition blocked"* — the member would be reporting
> two things the record contradicts. **`FAILED` is first and `CONDITION_PREVENTED` second**, so
> that where both predicates hold — a bound step reporting a mismatching value beside another step
> skipped `UNMET_DEPENDENCY` — the established failure is reported and the condition does not
> suppress it; and **both are refused at rung 2 unless a criterion is actually `unmet`**,
> because a consequential act ran: *a condition prevented action* would be false of it, and
> so would *what was asked was established not to have happened* where the **only** failure on the
> record is a step about something else. **An unrelated `FAILED` or `SKIPPED` step therefore does
> not convert a rung-2 attempt whose criteria are merely unestablished into a claim about them.**
> **And the member does not turn on whether a criterion happened to have a confirmed member**: a
> `FAILED` step contradicts **no** criterion (§2), so the same record earns the same member bound
> or unbound. **Below rung 2 limb 1 is reached and is honest there**: a reversible,
> non-disclosing, non-transmitting side-effecting call the seam committed **`FAILED`** is one the
> tool author's own declaration ruled left no effect (the clause above), so *the work failed* is
> what the record says — and where that author declared otherwise the step stands `INDETERMINATE`
> and the attempt does not end at all. What limb 1's first arm keeps reachable is the criterion
> **established not to hold** by a successful act's own answer, which is `FAILED` at every rung. **`UNCERTAIN` precedes
> `PARTIAL`** so that a rung-2 attempt with a **met** criterion and an **unestablished** one is
> reported as uncertain rather than as partly not done: the record establishes only that the rest
> is unknown, and §3's rule that an unestablished criterion at rung 2 **is** uncertainty would
> otherwise be unreachable. It also precedes it for a goal carrying **no criterion at all** at
> rung 2 — a consequential act ran and nothing verified it, which is what `UNCERTAIN` says and what
> `ANSWERED` would deny. And **`VERIFIED` sits below `PARTIAL`** so that no combination of met
> criteria outvotes an unmet one, which is R53 read at the member level. **`ANSWERED` is therefore
> reachable only at rung 0 or rung 1 and only where **no** step failed, side-effecting or not**,
> which is its honest scope — ADR-0249 §5's *"no step failed"* being what it asserts, and **`PARTIAL` is reached
> exactly where some criterion is met and some is not** — `unmet` or `unestablished` — so §6's
> statement for it is true wherever it is rendered.

> **Normative — `CANCELLED` is reached by no limb, and A9 keeps it entire.** ADR-0261's header
> states this decision's division in terms: *"the division becomes **every attempt but a cancelled
> one**. A10 keeps every member for every attempt it can reach, and it reaches no cancelled
> attempt"*. A cancelled attempt is terminal and ADR-0249 §5's *"no transition leaves a terminal
> member"* is what makes that true rather than a courtesy. **No lane writes
> `AttemptOutcome.CANCELLED` from this phase, and no lane reads §4's function as a general outcome
> rule for the act ADR-0261 §2 performs.**

> **Normative — the attempt ends where the turn produced a report, and stays live where it did
> not.** After the composing stage (§1), `orchestration` commits the attempt **`→ ENDED`** through
> **`PlanStore.commit_attempt`** (ADR-0249 §12), carrying the member the limbs above yielded and
> `ended_at` at the turn's own instant, **exactly where all three of the following hold**, and on
> **no other turn**:
>
> 1. the turn **composed a reply that completed** — a `ComposedReply` carrying text and not
>    degraded (ADR-0173 §6), read as the one `bool` §1 admits;
> 2. the attempt is **not paused** — its `state` is none of `AWAITING_CLARIFICATION`,
>    `AWAITING_AUTHORIZATION` or `BLOCKED` (ADR-0249 §5's *paused* derivation), and no step of its
>    executions stands `AWAITING_APPROVAL`;
> 3. **every step of every execution it names stands `SUCCEEDED`, `FAILED` or `SKIPPED`** — so
>    none stands `PENDING`, `AWAITING_APPROVAL`, `RUNNING` or `INDETERMINATE`. That covers the two
>    statuses ADR-0259 §4 and ADR-0261 §3 read for *outstanding*, and the two a claim can still be
>    made from.
>
> **Every other turn ends no attempt and writes no `AttemptOutcome` at all**, which ADR-0249 §5's
> validator already compels: an outcome is constructible only beside a terminal state.

**Limb 3 is the owner's ruling of 2026-09-14 made structural, and it keeps the reconciliation route
open**: *"The only case an authorisation must outlive a turn is the **uncertain-outcome** case."*
An attempt this phase ended would be terminal, and ADR-0259 §4's acts 3 and 4 move an attempt
between `RUNNING` and `EFFECT_UNRESOLVED` — **neither reachable from a terminal member** (ADR-0249
§5). **So the third condition is not a courtesy to the report; it is what makes A8's guarantee
reachable.**

> **Normative — the third ending condition is the *store's* to enforce and not the engine's,
> because a claim landing beside the engine's read is invisible to the attempt's own
> compare-and-swap.**
> **`PlanStore.commit_attempt` refuses an `AttemptTransition` whose `to_state` is `ENDED` where
> any step of any execution that attempt names stands `PENDING`, `AWAITING_APPROVAL`, `RUNNING` or
> `INDETERMINATE`**, decided **in the same indivisible step as the write**, and refuses it with
> **`StaleExecutionError`** — the class that means *re-read and recompute*, which is exactly the
> caller's correct response. This is a **strengthening of a member that already exists**, on
> ADR-0255 §3's own footing, and it is the shape ADR-0261 §3 uses for the same race one member
> over. **Every other `AttemptTransition` is untouched** — `→ CANCELLED` most of all, which
> ADR-0261 §2's act takes over exactly the outstanding steps this one refuses — and **no lane reads
> it as a general outcome check.**

> **Normative — and the ending transition carries the versions the comparison was computed
> against, which is what closes the window the status set only narrows.** **`AttemptTransition`
> gains `execution_versions`**, a possibly-empty `tuple[tuple[Identifier, int], ...]` defaulting to
> the empty tuple, each pair an execution id and the **`ExecutionState.version` the caller read**
> when it computed the comparison. **Each version is validated on the model itself as a
> **non-negative** integer**, `ExecutionState.version`'s own `ge=0` domain, so a pair carrying a
> value no execution can hold is refused where every other malformed field of a command is —
> **at construction, with the `ValueError` a frozen model raises** — and never reaches the store to
> be reported as a lost race. **No lane widens the domain, coerces a value into it, or reads a
> version this decision does not compare.** **`PlanStore.commit_attempt` refuses a `to_state` of `ENDED`,
> in the same indivisible step as the write, where the pairs' ids are not *exactly* the attempt's
> `execution_ids`** — a missing id, an extra id or a duplicate each refuse — **or where any pair's
> `version` is not the one stored**. **The two refusals raise different classes, and the
> difference is which of them the caller could have avoided.** A pair whose `version` is not the
> stored one is the **race** the field exists for, and it refuses with **`StaleExecutionError`**,
> whose documented meaning — *"the stored execution has advanced since the caller read it … the
> caller should re-read and retry"* — is exactly what happened. **An id set that is not the
> attempt's is a malformed command and refuses with `ValueError`**, no write taken: nothing
> advanced, so a class promising a fruitful retry would be a false statement about the store. **The
> order is fixed and is what keeps the two apart**: the attempt's own `expected_version`
> compare-and-swap is decided **first**, so an execution appended after the caller's read is
> reported as the race it is and never as a malformed set — the set can only be wrong because the
> caller built it wrongly. **The completeness half is the load-bearing one**: a subset would leave
> the omitted execution free to move between the comparison and the commit, which is the whole of
> the race, so the field is a **snapshot of the set the comparison read** rather than a list of the
> ones the caller chose to protect. An attempt naming no execution therefore takes an empty tuple
> and nothing else. **It is the `ENDED` limb
> alone that reads the field**: every other transition ignores it, `→ CANCELLED` included — so
> ADR-0261 §2's act is unaffected whatever it passes, and every caller this decision does not
> touch, a phase stamp, an effort counter, an append, writes exactly as it does today. **No lane
> reads the field as a claim check, a general optimistic lock, or a licence to re-read and retry
> *within this turn***: the engine's answer to a refusal is §4's no-second-bite rule, which defers
> the re-read the error class asks for to the **next** turn's own comparison rather than declining
> it — a turn that re-reads everything and recomputes from the then-current criteria (§5, §6).

**Two conjuncts because the race has two halves, and neither is redundant.** A
`commit_transition` **does not advance `GoalAttempt.version`**, so the attempt's own
compare-and-swap cannot see a claim land: an engine that read a step `PENDING` and then committed
would record a terminal — possibly `VERIFIED` — attempt over a step a concurrent driver had taken
`PENDING → RUNNING → SUCCEEDED`, whose answer the comparison never saw. **The status set refuses
that on sight**, reaching `PENDING` and `AWAITING_APPROVAL` because a set testing only `RUNNING`
and `INDETERMINATE` is silent by the time it runs. **What it alone would not close is the retry**:
`FAILED` is outside `TERMINAL_STEP_STATUSES` *"(it may still be retried)"*, so a
`FAILED → RUNNING → SUCCEEDED` retry landing between the comparison and the commit leaves every
step terminal at both instants — **the version pairs close it**. **Neither conjunct subsumes the
other**: the versions say nothing about a step nobody has moved yet, the statuses nothing about a
step moved twice.

**The cost is one turn and is bounded by an act that already runs.** An attempt whose walk stopped
leaving a step `PENDING` — ADR-0255 §2's three triggers — does not end on that turn; the next turn
runs ADR-0259 §4's reconciliation **before planning**, whose act 1 disposes of exactly those steps.
**No lane adds a sweep, a timer or a repair pass**, and a goal the user never returns to keeps a
live attempt — which is what `abandon_goal` is for (ADR-0261 §2).

> **Normative — the write is one `AttemptTransition` and the phase takes no second bite.** A
> refusal from that commit means the ground moved under the comparison. The phase **writes nothing
> further, does not retry, does not recompute, takes no `GoalStatus` write (§5) and does not fail
> the turn**, and the turn returns with `attempt_report` **absent** (§6). **No lane loops here.**

> **Normative — `orchestration` computes the comparison and the store decides nothing about it.**
> `PlanStore` gains **no member and no query or projection**, and **the only collaborator this
> decision adds to the engine is §3's `AuthorizationResolution` read** — `resolve(id)` and nothing
> else (ADR-0254 §16), which can name neither `record` nor `live_for`. **The store's one job here
> is the refusal above**: it never chooses a member and never reads a criterion.

### 5. `GoalStatus.ACHIEVED`'s one producer, and the conjunct that keeps a closed goal free of live attempts

> **Normative — `GoalStatus.ACHIEVED` has exactly one producer and it is the act below.**
> Immediately after the `commit_attempt` §4 names has committed, and **only** where §4's function
> yielded **`VERIFIED`** — §4's limb 5 — on the attempt it has just ended, `orchestration` writes
> **`GoalStatus.ACHIEVED`** through **`PlanStore.set_goal_status`** (ADR-0250 §9) under the
> `version` it read **before the comparison ran**, **and writes nothing else**. **No expiry, no
> silence, no timeout, no sweep, no reclaim, no model output, no inference and no other member of
> any Protocol writes `ACHIEVED`**, which is ADR-0250 §12's clause for `ABANDONED` stated for the
> member it reserved to this decision.

> **Normative — the two writes are ordered, the attempt first, and the order is what makes the
> conjunct below satisfiable.** **No lane writes the status first**, which would leave an
> `ACHIEVED` goal carrying a live, claimable attempt for the width of a store call — R53's failure
> with a window in it.

> **Normative — `PlanStore.set_goal_status` refuses an `→ ACHIEVED` write where the goal has an
> attempt in a non-terminal `AttemptState`**, decided **in the same indivisible step as the
> write**, and refuses it with **`StaleExecutionError`**. This is a **strengthening of a member
> that already exists**, on ADR-0255 §3's own footing, and it is the **exact mirror** of ADR-0261
> §2's `→ ABANDONED` limb, which ADR-0261 §11 books here by name. **It binds on `ACHIEVED`
> alone**: `ABANDONED` keeps ADR-0261 §2's limb, `BLOCKED` is A3's and is constrained by neither,
> and `ACTIVE` on ADR-0250 §13's reopen is untouched.

> **Normative — that conjunct and `open_attempt`'s closed-goal limb are exhaustive over the
> interleaving, and the second half is ADR-0261's and is not in the tree yet.** ADR-0261 §2 refuses
> an `open_attempt` on a goal that is closed — *"`ACHIEVED` or `ABANDONED`, ADR-0250 §1's
> division"* — so an attempt opened **before** this act's status write is one the conjunct sees and
> refuses the write for, and one opened **after** meets a closed goal. **There is no third case
> once that limb exists**, which is why §11 makes ADR-0261's implementing lane a **prerequisite**
> of the lane that writes `ACHIEVED` rather than an assumption, and **no lane closes this with a
> read in the engine, a re-read after the write, a sweep or a lock.**

> **Normative — a refusal writes nothing and is never retried, because a retry could close a goal
> against criteria nothing compared.** On **any** refusal of that write — `StaleExecutionError`
> from a lost `Goal.version`, or from the conjunct above — the act **writes nothing, takes no
> re-read, makes no second call**, does not fail the turn, and leaves the attempt `ENDED`/`VERIFIED`
> under an open goal, which §6's `VERIFIED` statement is worded to stay true of. **A lost
> `Goal.version` means the goal moved**, and it moves when a turn records a new
> `GoalInterpretation` revision (ADR-0249 §1, §12) — which may carry a **criterion this comparison
> never saw**. **No lane retries this write, re-reads and writes again, or re-runs the comparison
> inside the same turn.**

**The residual is legible and self-healing, and refusing to retry is what keeps it honest.**
A goal whose criteria verified and whose status write lost carries an `ENDED` attempt with
`VERIFIED` beside an open status — *the attempt established the outcome as the goal then stood, and
the goal has since moved* — not a false claim in either direction. The next turn opens a new
attempt (ADR-0250 §12's third act) and reaches `VERIFY` with the **then-current** criteria.

> **Normative — an attempt reaching a terminal state still moves no goal status, and this act is
> not an exception to ADR-0249 §4.** **Nothing here infers a status from an attempt's state.** One
> act takes both writes because one comparison decided both, and **an attempt that ends `ANSWERED`,
> `PARTIAL`, `FAILED`, `UNCERTAIN` or `CONDITION_PREVENTED` moves no status at all**.

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
> text, no count, no evidence reference, no step id, no instant and no prose** — ADR-0249 §9's
> containment reached for its own reason: *"an implementation that rendered every field of every
> value it was handed … discloses none of those, because there is none on the value to
> disclose."*

> **Normative.** **`TurnOutcome` gains exactly one field, `attempt_report`, typed
> `AttemptReport | None` and defaulting to `None`**, and its docstring names this ADR. It is
> **non-`None` exactly on a turn that ended an attempt under §4** and `None` on every other
> returned outcome — a turn that engaged no goal, a routed operation (ADR-0197 §7), ADR-0198 §1's
> restatement, and every turn whose attempt stayed live. That adds a value to ADR-0198 §2's
> enumeration **without changing any value it fixes**: ADR-0242 §9's widening one member over.

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

> **Normative — what the report and the reply speak of is the *comparison*, and neither claims
> anything about the two commits, which have not happened yet.** §1 puts the comparison **before**
> the composing stage and the commits **after** it, so the values this section hands the stage and
> renders beside the reply are the comparison's and **nothing more**: `outcome` is the member §4's
> limbs yielded, `continues` is computed from it and the goal's status **as the comparison read
> them**, and **no statement of this section asserts that an attempt was ended, that a status was
> written, or that a goal is now closed**. **Where either commit is then refused (§4, §5), the
> turn corrects nothing, re-renders nothing and appends nothing**: the refusal leaves a record that
> is true — an attempt still live, or an `ENDED`/`VERIFIED` attempt under an open goal — and **the
> next turn that engages the goal reports what is then true** through this same section, which is
> ADR-0255's outcome route and adds no second one. **This is why `VERIFIED`'s statement speaks of
> *the criteria this attempt compared* and why none of the six names the goal's status**: a
> statement that could be falsified by a commit taken after it was composed is one this decision
> does not write.

> **Normative — what a refused `commit_attempt` leaves on the surface is a silence, and the cost is
> stated here rather than discovered.** §4 returns `attempt_report` **absent** on that turn, so
> **no fixed statement is rendered at all** — the reply the stage already composed is what the user
> reads, and it stands **as composed**. **That reply is not falsified by the refusal**: the stage
> was given the comparison's own two values, the clause above fixes that every statement and the
> instruction behind it speak of the comparison alone, and the comparison **was** made and its
> result does not move. What the user does not get is the outcome word beside it, which is a
> **silence rather than a false claim** and is the fail-closed direction — a surface asserting an
> outcome for a turn whose attempt did not end would be the claim this decision refuses. **The next
> turn that engages the goal compares afresh against the then-current criteria and renders the
> statement for what is then true** (§5's residual, and ADR-0250 §12's third act opening the
> attempt it compares) — **a correction that is a fresh comparison and never a replay of this
> one**. **No lane re-renders the refused turn's statement, stores it for a later turn, retracts
> the reply, appends a second message, or reports the refusal to the user as a fault**: the ground
> moved under a comparison, which the record already shows, and `assistant goals` is where a user
> reads how the goal stands.

**The offer is in the reply rather than on the surface, and the reason is the binding it buys.**
The owner's addendum of 2026-09-13 states the mechanism: the reply ends *"Shall I try again
later?"*, and the next turn's bare *"Yes"* **binds to the goal by reply reference** (ADR-0250 §3's
first rule, which takes no model call). An offer a surface printed would reach neither the
browser's transcript nor the spoken channel as part of what was said. So the **reply** carries the
offer and the **surface** the outcome word — ADR-0242 §9's own split, one fact over.

> **Normative — one fixed statement per member, rendered beside the reply and never in place of
> it, on ADR-0242 §9's construction.** For **`VERIFIED`**, that the criteria **this attempt
> compared** were checked and hold — a statement about the comparison and never a claim that the
> goal is closed, since a revision landing beside it leaves the goal open (§5) — naming
> `assistant goals` as where the goal's state is read; for **`ANSWERED`**,
> that an answer was produced and **nothing was verified** — never that it is correct; for
> **`PARTIAL`**, that part of what was asked was established and part was **not established**; for
> **`FAILED`**, that the work failed and **no criterion of this goal was established** — which
> limb 1's *"no criterion is met"* conjunct makes true of both of its arms, the established
> contradiction and the failed step, without claiming that a criterion nothing compared was
> disproved. **It speaks of the criteria and never of the acts**: where one call satisfied and
> another contradicted, the criterion is `unmet` and the member is `FAILED` though an act did take
> effect, so a statement saying *nothing was done* would be false of the record and this one is
> not; for **`UNCERTAIN`**, that an action was taken and
> **its outcome is not established**, naming `assistant goals`; and for **`CONDITION_PREVENTED`**,
> that the action was **prevented before it ran** — which covers both of `blocked`'s sources (§4)
> without asserting either, since `SkipReason.UNMET_DEPENDENCY` is a stated condition that did not
> hold and `SkipReason.APPROVAL_DENIED` is the user's own refusal, and since a read may well have
> succeeded first. **The exact wording is the lane's; what
> is fixed is which fact each names.**

> **Normative — no statement asserts anything the record does not carry.** None says that the goal
> is complete unless the member is `VERIFIED`; none says an effect did not happen; none names a
> criterion, a tool, a destination, a figure, a `Settings` field or a cause; and **`UNCERTAIN`'s
> says nothing about whether the call left** — ADR-0261 §6's *"no caller assumes the query did not
> leave"* binding on one more statement. **A surface that renders no statement for a member has not
> implemented this section and is not a permitted degradation** (ADR-0242 §9).

> **Normative — this is not ADR-0250 §5's announcement and neither displaces the other.** §5's
> sentence is about **which goal a turn is about**; this statement is about **what the attempt
> produced**. A turn may owe both, one or neither — two `None`-defaulting members on ADR-0244 §9's
> rule — and **no lane derives either from the other or collapses them.** §5's rule that an
> `OPENED` or `CONTINUED` turn which moved no word *"says nothing about goals at all"* stays true
> word for word.

> **Normative — a meaningful completion is announced once, and the record is what says it
> afterwards.** The statement is rendered on the one turn `attempt_report` is non-`None`. **No lane
> repeats it on a later turn, re-renders it from the stored `AttemptOutcome`, or makes the value
> durable on any other record**: where a user asks later how a goal stands, `assistant goals` reads
> the goal's status and the attempt's stored outcome.

### 7. Q4's gate: this decision is the third guarantee, and all seven conditions still stand

> **Normative — ADR-0255 §13's rule is carried unchanged and is not weakened here.** *"No
> consequential capability is wired into a production deployment until the verification,
> uncertain-outcome and cancellation guarantees for its class are implemented and demonstrated."*
> **The lanes of this decision wire no consequential capability**, register no booking integration
> and enable nothing in a production deployment; §12's arms run against controlled fakes, and
> M33's campsite walkthrough runs against the simulated booking service the owner ruled on
> 2026-09-14.

> **Normative — this decision is the gate's **verification** guarantee, and the class it does
> *not* cover is named rather than left to be discovered.** §2's conjuncts and §4's function are
> the mechanism and §3's rungs are the strength. **A deployment wiring a covered capability does
> two things as part of wiring it** (§2, §2a): it **declares its tools' `postconditions`**, a tool
> declaring none satisfying this guarantee for no criterion at all; and it authorises that
> capability's consequential acts **against a confirmed `Authorization`** rather than per call,
> since a route-(a) confirmation establishes no criterion. **And the guarantee does not cover a
> capability whose acts make a charge**: §2 makes every `MONEY` criterion `unestablished`, because
> the quote a dispatch was proved against is recorded nowhere (§9), so such a goal reaches
> `UNCERTAIN` at rung 2 and never `VERIFIED` — **ADR-0255 §13's gate is therefore *not met* for
> that class by this decision**, and condition (7) below is where the corpus books the rest of it.
> **None of the three is a condition this decision adds to the gate**: each states what its own
> guarantee covers, which is what ADR-0255 §13 asks of it.

> **Normative — the count is ADR-0255 §15 item 19's as ADR-0265 §8 and then ADR-0267 made it, it
> is **seven**, and **all seven still stand** on the day this decision is ratified.** Named so that
> no reader mistakes this document for the last of them: **(1)** A8's reconciliation guarantee
> (ADR-0259), **(2)** A9's cancellation guarantee (ADR-0261) and **(3)** this decision's
> verification guarantee are each **ratified and not yet implemented**, and the gate asks for
> *"implemented and demonstrated"*; **(4)** ADR-0255 §13's first added prerequisite — the durable
> recovery of a resolved confirmation whose claim was refused — which ADR-0259 §5 takes the `DENY`
> half of and leaves the `ALLOW` half standing ([#2380](https://github.com/leonapivato/ai-assistant/issues/2380));
> **(5)** ADR-0255 §13's second — the evidence-to-claim window ([#2309](https://github.com/leonapivato/ai-assistant/issues/2309));
> **(6)** ADR-0265 §6's containment for a wrongly minted intended action; and **(7)** ADR-0267 §6's
> freshness prerequisite — the provider-side hold or conditional execution a capability authorised
> through a `MONEY` ceiling owes, which that decision added to item 19 while this one was being
> drafted. **This decision adds no condition to that count and removes none**, and **no lane reads
> this ADR's ratification, or the merging of its L1, as the gate being met.**

**The gate is nearest to being met here and that is exactly when it is most worth restating.** The
natural reading once this document ratifies is *one more merge and the gate is open*, and it is
wrong twice over: **ratification is not implementation**, and **four of the seven** conditions —
(4) through (7) — are held by decisions and lanes this document does not touch, **none of which has
landed**.
ADR-0255 §13 anticipated this arithmetic — *"a deployment reading the three could wire a
booking"*.

### 8. The `core` surface, the wire, the stored shapes, and the export

> **Normative — what `core/types.py` gains.** **One model** — `AttemptReport`, with exactly two
> fields (§6); and **three fields** — `postconditions` on `ToolDefinition` (§2),
> `execution_versions` on `AttemptTransition` (§4), and `attempt_report` on `TurnOutcome` (§6).
> **Nothing else** — **no new enumeration**, no new
> constant, no `Settings` field, and no widening of `Goal`, `GoalInterpretation`, `GoalElement`,
> `ProposedElement`, `GoalAttempt`, `StepTransition`, `StepExecution`, `ExecutionState`,
> `ActionPlan`, `PlanStep`, `GoalEvidence`, `GoalBrief`, `BriefElement`, `EvidenceDigest`,
> `IntendedAction`, `Authorization`, `CoverageMember`, `AuthorizationBasis`, `ActionQuote`,
> `PermissionRuling` or `ValueBound` — **`ActionRequest` and `PermissionDecision` gain no field of
> their own** and carry the new one only inside the `ToolDefinition` they already embed.
> **`AttemptOutcome`, `GoalStatus`, `AttemptState`, `AttemptPhase`, `VerificationKind`,
> `BoundKind`, `AuthorizationOrigin`, `AuthorizationDisposition` and `SkipReason` each gain no
> member**, and **`core/errors.py` gains no class.**

> **Normative — `ToolDefinition` *is* a stored shape, and the audit trail's `schema_version` moves
> by exactly one.** `ActionRequest.tool` and `PermissionDecision.tool` embed the **whole**
> definition by value — ADR-0021 §1's *"There is no name left to rebind"*, which §2 relies on — and
> `SqliteAuditTrail` persists each decision as a JSON record under a `meta("schema_version")`
> marker. A definition carrying `postconditions` is therefore written into that file, and
> `ToolDefinition` sets `extra="forbid"`, so **code at the current marker could not decode a record
> newer code had written while the marker still said it could**. **`_SCHEMA_VERSION` therefore
> moves by exactly one and the previous value stays openable**, on ADR-0049 §1's own mechanism as
> ADR-0192 §2 already applied it to this store — an additive create-and-migrate that restamps, so
> no trail on disk becomes unopenable and a **downgrade is refused loudly at open** rather than at
> the first unreadable row. **No integer is fixed here**: as dated observations at `58f0797f` the
> marker reads **2** and the openable set `{1, 2}`. **No record is rewritten, back-filled or
> re-decided**: a decision written before this decision decodes with `postconditions` empty, which
> is the fail-closed claim §2 states, and **no tool in this tree declares one until its own
> integration does** (§7). **`PlanExport` carries no `ToolDefinition`**, so no export version
> moves for it.

> **Normative — what any Protocol gains: two strengthenings and nothing else.**
> `PlanStore.set_goal_status` gains §5's single `→ ACHIEVED` limb and `PlanStore.commit_attempt`
> gains §4's `→ ENDED` limb — one limb in **two conjuncts**, the live-step set and the execution
> versions, refused by one class — each with its `planning` implementation. **No member is added
> to any Protocol, no argument is added to any existing member, `commit_transition` gains no
> conjunct, `save_plan` gains none, `Planner.plan`'s signature does not move, and no new Protocol
> is created** — so **no new conformance suite and no new canonical fake is owed**, and the
> existing shared `PlanStore` conformance suite and the canonical fake in `ai_assistant.testing`
> gain both obligations **in the same change that adds them** (`CONTRIBUTING.md` → "Adding a
> Protocol": *"The triad is what a Protocol **change** is measured against too"*), which is §12's
> arm 8. **And `AuthorizationResolution` takes a third strengthening, of its *contract* and not of
> its shape**: §3's read is `resolve(id)` exactly as ADR-0254 §16 declares it — no member, no
> argument, no widened return — but that Protocol is declared *the face a trail holds*, read by
> `AuditTrail.record`, and this decision gives it a second holder and a second reader. **It is
> therefore carried as a contract change**, its docstring naming this ADR and this decision's
> supersession recorded on ADR-0254, in the same lane as the two `PlanStore` limbs (§11). **No
> conformance case and no fake changes for it**: a holder is not behaviour a suite can assert, and
> the member's signature, return and detached-snapshot discipline are untouched. All three are
> **BREAKING** contract changes under golden rule 5.

> **Normative — what a conforming `Planner` must now produce: *nothing new at all*.**
> `Planner.plan`'s roster, its `PlannerOutput` and every shape a planner returns are **untouched**,
> so the `Planner` conformance suite and its canonical fake gain **no case and no obligation**, and
> a planner conforming today conforms after this decision. **That is the whole of how ADR-0249 §7's
> asymmetry is obeyed** (§2a): there is no field on which a model could supply an operand of this
> comparison, so no conformance case has to police one. **No conformance case obliges a
> `ToolDefinition` to declare a postcondition** either, an empty tuple being a conforming and
> honest declaration (§2).

> **Normative — the breakage is for the wire rather than for a constructor.** Every field added
> defaults, so no existing construction stops validating, and **this decision adds no enum member
> for an exhaustive caller to miss**. What breaks is the peer contract: `TurnOutcome` is returned
> by promoted-surface methods, sets `extra="forbid"`, and `wire/codec.py` renders a model by
> `model_dump()` — so a newer hub emits an `attempt_report` member an older client refuses. That is
> **ADR-0124 §9's second limb**, and **ADR-0178 §6 is the precedent for stating the bump in the
> deciding ADR**. **`PROTOCOL_VERSION` therefore moves by exactly one, in the lane that lands the
> `core` change**, with `wire/envelope.py`'s log entry naming this ADR. **No integer is fixed
> here**: as a dated observation it reads **44**. **No compatibility shim, negotiation or lenient
> decode is added** — ADR-0084 §3's exact-match handshake is the mechanism.

> **Normative — the plan store's `schema_version` does not move, `PlanExport.schema_version` does
> not move, no migration is owed in either, and nothing is repaired.** **No shape the plan store
> persists changes** — `Goal`, `GoalInterpretation`, `GoalElement` and `GoalAttempt` are each
> untouched, and `AttemptTransition` is a **command** rather than a stored record (ADR-0249 §12) —
> so a document written after this decision decodes for a reader at the previous version and a
> stored goal decodes unchanged. **No lane sweeps, repairs, back-fills or re-verifies a goal
> stored before this decision**, and **no lane back-fills an `AttemptOutcome` onto an attempt this
> phase did not end**, which would be a verdict nobody computed written onto a record nobody was
> looking at. **`AttemptReport` is carried by no stored record and by no export**, riding
> `TurnOutcome` alone, and **§2's three results are computed and discarded** — no value of this
> comparison outlives the turn. As
> dated observations `PlanExport.schema_version` reads `Literal[12]`, the plan store's
> `_SCHEMA_VERSION` reads **4** and its `_UPGRADABLE_FROM` `{1, 2, 3}`, and none moves.

> **Normative — nothing else under `wire/` changes, and retention, deletion and export are
> untouched.** The connect exchange gains no member, no frame's encoding changes, no `FrameKind` or
> codec entry is registered, the promoted method set does not move, no gateway route is added, and
> the error mapping gains nothing. Every value this decision writes rides a `GoalAttempt` the plan
> store already holds, so ADR-0014 §5's obligations and ADR-0249 §12's `delete_goal` cascade bind
> as they stand: **no retention rule, sweep, expiry, second store or new durable record is
> minted.**

> **Normative — no new class of content crosses any seam.** A `ToolDefinition`'s `postconditions`
> carry the same kind, key
> and literal ADR-0253 §4 already puts on a `PlanStep`, inside a record the audit trail already
> keeps whole.
> **ADR-0004 §5's rule that "Tier 0/1 data must never be logged" binds unchanged and nothing here
> logs a criterion, a coverage member, a span, an output or a verdict**, and `_render_request`
> prints no identifier
> (ADR-0249 §9).

### 9. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward any
> of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling, and each
> carries the condition that fires it.

- **The goal-terminal ending of an authorisation.** The owner's ruling of 2026-09-14, disposed of
  as *"a short superseding ADR, one edge + one clause, sequenced after [ADR-0266]"* — the number
  elided for the reason ADR-0261 §8 gives, its lane being
  [#2376](https://github.com/leonapivato/ai-assistant/issues/2376). **Not this decision's**: §5
  supplies the act that makes a goal terminal, which is the antecedent that ruling reads, and
  **nothing here asserts that an authorisation survives it or ends with it**. The
  **uncertain-outcome** exception it keeps open is preserved by §4's third ending condition.
- **A declared postcondition that is an inequality, a range or any comparison other than presence
  and byte-exact equality.** **Not decided**: ADR-0253 §4's kinds express presence and equality,
  and a ceiling — *"under 150 euros"* — is neither, which is why a **ceiling** is proved where
  ADR-0266 §7 proves it and never by a declaration here. **No lane adds a `VerificationKind`
  member, a numeric reading or a currency comparison to `postconditions` on this decision's
  authority**. Fired by a decision that states the wider reading with its own totality argument.
- **Confirming the *actual charge* after the act, which the owner ruled on 2026-09-14 and which
  ADR-0266 §10 and ADR-0267 §10 each booked here by name.** **Not decided, and — unlike every
  other entry of this section — *reassigned*: the two scopes the header states move it off this
  decision and onto the one that lands its operand** ([#2409](https://github.com/leonapivato/ai-assistant/issues/2409)),
  because the reason is an operand rather than a rule and no round of this document can supply one.
  The comparison the ruling asks for is against **the quote the dispatch was proved against**, and
  that quote is recorded **nowhere**: ADR-0254 §13 rules there is *"no cached coverage verdict
  anywhere"*, ADR-0267 §7's `Authorization.quoted` is the **proposal's** read, which a refresh may
  correctly leave behind, and the goal's `quotes` tuple carries the reading the **acting step
  itself appended** (ADR-0267 §4). **Comparing against the user's own ceiling instead is not that
  comparison either**: it passes a charge that exceeds the quote while staying under the ceiling,
  which is the mismatch the ruling calls a finding. **So no lane compares a charge against any of
  the three, and none invents a fourth**, and §2 makes a `MONEY` criterion `unestablished` outright
  rather than comparing the one operand it has. What binds a charge today is the proof ADR-0266 §7
  takes **before** the act, which is unweakened, and #2409 is sequenced **before** M33's campsite
  walkthrough for that reason. **And the shape a stronger confirmation takes is stated here so that
  the reassignment does not smuggle one into this phase** (the owner's direction of 2026-09-15,
  recorded on [#2255](https://github.com/leonapivato/ai-assistant/issues/2255)): evidence stronger
  than the act's own answer — a receipt in email, a line on a statement — **may take hours to
  arrive, so reading it is a *later act***, in its own turn or as a background check, and **the
  end-of-turn phase reports what the record establishes *now* and names what is unconfirmed**,
  which is `UNCERTAIN` and its statement (§4, §6). **That is the shape #2409 and any later
  verification decision take, and no lane reads it as licence for this phase to wait, poll or
  schedule** — the sequencing ruling above forbids all three.
- **A criterion stating a *count*.** **Not decided, and it is `unestablished` by construction
  rather than by a rule here**: ADR-0254 §2 closes the coverage vocabulary at `MONEY`, `PERIOD` and
  `TERMS` and rules that *"a **count** … takes a fixed value or no member at all"*, so *"two
  rooms"* mints no member, §2 finds none resting on that span, and the criterion never reaches
  `met`. **No lane infers an arity from a criterion's text, from a plan's step count or from a
  model.** Fired by a decision that adds a `BoundKind` for a count with its own totality argument.
- **Whether every act a criterion's *proposition* needs was performed.** **Not decided**: §2 reads
  a criterion as met where every call that acted agrees and one satisfies, so a criterion whose
  member is typed and whose first act succeeded reads `met` though a plan meant to make a second
  call never made it. **That is §1's rule read honestly** — a criterion is a proposition about the
  outcome and not a work list, and R48 asks for the comparison against the criteria — and §4's
  other limbs still report an incomplete walk. Fired by a decision that gives a criterion a
  machine-readable arity.
- **Whether a criterion's own text is what it is verified *against*.** **Not decided, and §2a
  states the limit**: the join is the criterion's `span`, both the span and the text are the
  planner's (ADR-0249 §7), and a criterion whose text describes one fact while its span is another
  of the user's own words is verified against the **span**. **No lane compares the text**, which is
  the prose comparison §2 refuses. Fired by a decision that puts a goal's **criteria** to the user
  the way ADR-0254 §11 puts a row's values — an assent to the rendered criterion, after which the
  text is the user's and not a reading of it — or by one that binds a criterion's span to its own
  text by an authority that is not a model.
- **Establishing a criterion from a `GoalEvidence` row.** **Not decided**: the corpus carries **no
  association from a criterion to an evidence row** (Alternatives), so a criterion only an
  interpretation over a read's output could settle is **unestablished**. Fired by a decision that
  widens `settles` to a criterion element, which would owe ADR-0253 §8's ordering rule its own
  argument.
- **Establishing a criterion for an act authorised per call rather than against a confirmed row.**
  **Not decided, and §2a states the cost**: a route-(a) confirmation records a `parameters_digest`
  and no **typed value**, so there is nothing a criterion could agree with by kind, and every
  criterion of such a goal is `unestablished`. **No lane widens §2's bound steps to another route
  or synthesises a member from a digest.** Fired by a decision that gives a per-call confirmation a
  typed record of what the user assented to — ADR-0254 §11's rendered values in a shape a
  comparison can read — which would owe that record's own retention, export and supersession
  rules their argument.
- **Whether the act the provider *performed* matches what it reported.** **Not decided, and §2a
  states it plainly**: a declaration is about the act's own answer, and no clause here reaches past
  it. **The corpus proves the *request* elsewhere and this decision neither repeats nor weakens
  it** — ADR-0254 §13's recheck at every dispatch, ADR-0266 §7's two routes, and ADR-0247 §1's
  confirmation for exactly the acts §3 puts at rung 2 — and **ADR-0266 §10 books the one gap that
  leaves** in its own words: *"What pins an *undeclared* user-facing argument to the user's own act
  … `IntendedAction` cannot close the gap"*. Fired by a decision that plans an **independent
  confirming read** as a step of a later attempt, which is where §3 puts one and which would owe
  its own authority, budget and reporting rules.
- **A verification that calls a model.** **Not decided**: establishing a goal's achievement is the
  `ACHIEVED` write's prerequisite and ADR-0249 §7 forbids a model clearing one. Fired by a decision
  that lifts that bar.
- **Retry across turns, reconciliation, idempotency keys, modify-before-replace, and how an
  `INDETERMINATE` step is resolved.** **A8**, as ADR-0255 §12 and ADR-0259 §10 book them. **And
  with them, whether a *failed* consequential call left an effect** — **in the one route the seam
  does not already rule**. ADR-0032 §2 rules the **classified** route and §4 reads its answer
  rather than a fact of its own: `INDETERMINATE` is *a possible effect* and `FAILED` is the tool
  author's own declaration that there is none, over an argument that *"has no default"*. What no
  clause anywhere reaches is the **unclassified** one: an exception escaping a `side_effecting`
  implementation becomes `INTERNAL`/`FAILED` (ADR-0029 §3 as ADR-0032 amended it — *"a fact that is
  absent or not a bool refuses the whole carrier for INTERNAL and FAILED"*), a tool raises it as
  readily after the provider acted as before it called, and **no raiser answered the question**, so
  no field of the record separates that from a refusal. **`FAILED` is still not a disproof at the
  criterion**: §2 reads **no** `FAILED` step as an answer at all, a failed result carrying no
  output (ADR-0029 §3), so such a criterion is `unestablished` and never `unmet` — which is the
  fail-closed direction, and all this decision can say. **This decision does not close the gap and
  does not guess at it**: it adds no `core` field, no limb conjunct and no gate prerequisite (§4).
  **Fired, and filed, as [#2415](https://github.com/leonapivato/ai-assistant/issues/2415)**, which
  would extend ADR-0029's own vocabulary at the seam that knows — never infer it at this one.
  **The same silence leaves a possible
  duplicate**: where a failed dispatch and a later successful one share a `parameters_digest`, §2
  reads the criterion `met` on the success, and whether the failure **also** took effect — two
  bookings where the user asked for one — is A8's idempotency question and is answered by no clause
  here. **So a booking a provider genuinely declined
  is `unestablished`, and its attempt — a booking being rung 2 — is `UNCERTAIN` and not
  `FAILED`** (§4 limb 3), fail-closed, and the direction a user's next turn and A8's reconciliation
  resolve. **No lane infers effect absence, or effect *presence*, from a failure kind, a
  `retryable` flag, an idempotency declaration or `side_effecting`.** **And with it the
  reconciliation route the unclassified case has none of**: ADR-0259 §4 reconciles an
  **`INDETERMINATE`** step, and a step committed `FAILED` is terminal, so an attempt that ends
  leaves the goal **open** and nothing later resolves whether that effect exists. **That is a gap
  in the corpus this decision reports rather than closes** — it writes no `EFFECT_UNRESOLVED`,
  holds no attempt open and schedules nothing (the sequencing ruling) — and #2415 is what would
  give A8 a failed-but-possibly-effecting step to reconcile at all. **And with it the identity that would tell a retry
  from a second identical act**: two identical acts share one `parameters_digest`, so §2 cannot
  tell a re-dispatch from a second act of the same shape. **That does not move any criterion** —
  the criterion reads `met` on the successful dispatch either way (§2) — and what it leaves open is
  the **duplicate** above and the arity residual below. **No lane closes it by reading a step
  order, a timestamp or a planner's label.** Fired by the decision that gives a dispatch a per-call
  identity, which ADR-0266 §10 books as an opaque per-call reference.
- **Distinguishing the four causes `SkipReason.UNMET_DEPENDENCY` carries.** ADR-0255 §2 gives all
  four one member, so §4's `blocked` fact cannot tell an unsatisfied `when` from an unresolvable
  `resolves`. **`SkipReason` gains no member here.** Fired by a surface that must tell a user
  which.
- **`GoalStatus.BLOCKED`'s producer.** **A3**, as ADR-0249 §4 and ADR-0250 §12 reserve it.
- **An act that ends an attempt while leaving its goal open, and whether a store enforces *at most
  one live attempt per goal*.** **ADR-0261 §11's entries, untouched.** §5's conjunct refuses a
  **write** and **no attempt on account of another**.
- **What a report says about a **cancelled** attempt, and the retention, export or rendering of a
  per-criterion result.** The first is **A9's** (ADR-0261 §3, §6): `attempt_report` is written by
  §4's act alone, so an attempt ADR-0261 §2's act ended carries none. The second is **not decided
  and none is minted** — §2's three results are computed and discarded, exactly as ADR-0252 §6's
  four tests are, and **no value names which act or which confirmed member established a
  criterion**. Fired by a surface that must show which criterion failed, or by an audit that must
  say which act closed a goal, either of which would owe a durable record with its own retention
  and export obligations.

### 10. Records owed on earlier ADRs, under ADR-0082 §1

**The test is ADR-0070 §1's, applied to the earlier ADR's text, and ADR-0082 §1 is where it is
stated in those words**: *"Would a reader holding only the earlier ADR now act differently, or read
one of its clauses more widely than it now holds?"*

**Exactly four documents owe a record — ADR-0016, ADR-0254, ADR-0266 and ADR-0267, one scope
each** — and the header states all four in full. **ADR-0249 owes none, and that is the largest single change between this decision and its
earlier drafts**: those added a `check` field to `GoalElement` and to `ProposedElement`, and §2 now
adds neither, so §1's field enumeration, §7's `ProposedElement` shapes and §7's four-shape
validator each stay true word for word and a reader holding only ADR-0249 builds exactly what it
says and acts identically.

- **ADR-0016 §1** — *yes*, in one scope: **its `ToolDefinition` model declaration together with
  its required-field clause, in the application to `postconditions` alone**, which the header
  states in full. A reader holding only §1 authors a definition stating **nothing about what its
  own success establishes**, and §2's third conjunct has then nothing to hold an output against:
  every criterion resting on that tool is unestablished, and the verification ADR-0255 §12 books
  here has no operand for any act at all.
  **Nothing else of §1 fails the test**: every other field stays required, `frozen=True` and its
  audit-record argument, `description`'s non-blank refusal and the registry's detached-snapshot
  discipline each stay true word for word. **And the required-field clause's own subject does
  reach this field**, which the header states: ADR-0254 §3's condition 3 compares the declaration
  **by value**, so the exception rests on the empty tuple's claim being the fail-closed one and
  never on the field being outside a permission decision's reach.

**Every other ADR this decision reaches owes no record**, and the entries below are the whole of
them, each decided by the same test.

- **ADR-0249 §4 and §5** — *no*. §4's *"`GoalStatus.ACHIEVED` gets no producer **in this
  decision**"* and §5's *"**Which member a given attempt earns is A10's**"* are **statements about
  that decision's own change** and stay true word for word, and a booking **discharged** is not a
  clause made false (ADR-0261 §12's own words). §5's two-shape validator, its *"no transition
  leaves a terminal member"* and its *paused* derivation bind entire and are what §4 reasons from.
- **ADR-0249 §1 and §7** — *no*, which is the entry a reader of this decision's earlier drafts
  would expect to go the other way. §1's `GoalElement` field enumeration and §7's `ProposedElement`
  enumeration, four-shape validator, `Planner.plan` roster, ground-resolution rules, silent drop
  and no-identifier-crosses-the-seam clause each **gain nothing**, and §7's
  **interpretation-is-the-model's asymmetry** is not merely left true but is the clause §2a reasons
  from: a reader holding only ADR-0249 authors the same element, returns the same envelope and
  refuses the same shapes.
- **ADR-0249 §6 and §9** — *no*. The phase vocabulary, its order and its writer clause are
  **relied on**; this decision gives `VERIFY` work and adds no phase, member or writer. §9's
  `GoalBrief`/`BriefElement` enumerations gain **nothing** (§8).
- **ADR-0250 §9** — *no*, for §5's conjunct. **Its one sentence about refusals is about which
  *member* may be written** — *"which acts may write which member is the caller's rule, not this
  member's"* — and §5 refuses no member: `ACHIEVED` stays writable, by this act alone. What is
  added is a **consistency conjunct** between two records, the identical move ADR-0261 §2 made on
  the same member for `ABANDONED`, which **ADR-0261 §12 ruled owes ADR-0250 §9 no record** on
  ADR-0255 §3's footing that such a thing is *"a strengthening of an existing member rather than a
  new one"*.
- **ADR-0249 §12, for §4's conjuncts** — *no*, on that same footing and precedent: §12 does not
  enumerate what `commit_attempt` refuses, and **ADR-0261 §3 added an outcome conjunct to that very
  member and recorded nothing against §12 for it**. Its commands-not-snapshots rule, its
  append-only reference tuples and its compare-and-swap discipline all stay true, and
  `execution_versions` is a field of the **command** under that same discipline rather than a
  second route.
- **ADR-0250 §5 and §12** — *no*. §5's *"`TurnOutcome` gains **four** `None`-defaulting members"*
  stays true of a reader who builds those four — **ADR-0242 §9's own precedent for the identical
  move**, which recorded nothing — and its announcement rule is untouched; §12's *"`ACHIEVED`
  likewise gains none, which is A10's"* is a statement about that decision and stays true, its
  three user acts and abandonment clauses **relied on** by §5.
- **ADR-0170 §4, §5, §5a and §6** — *no*. §4's shapes are untouched; §5's construction and its
  honest limit are **adopted whole** by §6; §5a's deterministic-local-summary rule is what §6's
  fixed statements satisfy, the outcome being a member of a closed vocabulary this system owns;
  §6's render-beside-never-instead rule binds entire.
- **ADR-0198 §2** — *no*: a value is added to its enumeration without changing any value it fixes,
  ADR-0242 §9's own reading of the same move.
- **ADR-0252 §6, §9, §10 and §11** — *no*. §2 **does not call §6's four tests at all** and states
  why (§9); §9's invalidation predicate, §10's fourth `GoalElement` shape and §11's digest each
  gain nothing, this decision adding no field to `GoalElement` at all.
- **ADR-0253 §2, §4, §5, §7, §8, §9 and §10** — *no*. §4's *"this is not the verification A10
  lands"* is **fulfilled**: this decision is that verification, is stated over the goal's criteria,
  and **reuses `StepVerification` as a value** rather than adding a reader of `PlanStep.verifies`.
  §5's `StepCondition` and §8's `PlanInterpretation` keep their condition-element restriction
  **entire**; §7's `GoalElement.id`, its `D`-label reservation and its no-migration clause stay
  true. **§9's label scheme is not extended** — no value here carries a label — so **the fields
  another component sets on a plan stay *exactly four***, and **this decision adds no field to
  `PlanStep`**.
- **ADR-0255 §3, §8, §12 and §13** — *no*. §3's claim conjuncts are **relied on**; §8's fence is
  fulfilled as ADR-0253 §4's is, its *"exactly the two places"* rule staying true because this
  decision adds no reader of `verifies`; §12's A10 entry and §13's gate are **bookings discharged
  in part**, §13's rule carried verbatim by §7 with its prerequisites and count untouched.
- **ADR-0259 §2, §3, §4 and §9** — *no*. §2's satisfied-step commit and §9's
  `satisfied_by_execution`/`satisfied_by_step` are **read** by §2 and §3 and gain no clause; §4's
  acts 3 and 4 are what §4's third ending condition keeps reachable; nothing here resolves an
  `INDETERMINATE` step.
- **ADR-0261 §2, §3, §6 and §11** — *no*. §3's limbs stay the rule for a **cancelled** attempt,
  which §4 reaches none of; §2's `open_attempt` closed-goal limb is **relied on** (§5, §11); §6's
  in-flight statements are untouched; §11's booked question about `→ ACHIEVED` is **fired** by §5.
- **ADR-0265 §1, §3, §4 and §8** — *no*, and §2a is written to keep it so. `IntendedAction` gains
  **no field**; §1's enumeration of what reads `Goal.intended_actions` — *"§4's `GoalBrief.actions`
  projection and its label resolution, §5's export, and the effect claim §6 obliges, and … nothing
  else"* — **stays true because this decision reads that tuple not at all**, and
  **`PlanStep.intended_action` is read no more than `serves` is**, the binding being the row a
  step's own pinned route-(d) decision names and the grouping the call's own digest (§2, §2a);
  §3's *"`serves` gates nothing"*, its refusal of a
  lane that *"derives an intended action from `serves`"* and its *"no mechanism reads the staleness
  at all"* each **stay true word for word** (§2a); §4's `A` label space is neither used nor
  extended, no value here carrying a label at all; and §8's sixth gate condition is named by §7 and
  neither discharged nor moved.
- **ADR-0254 §1, §2, §7, §11 and §13** — *no*, and this is the group §2's conjuncts lean on
  hardest. **No row, member, basis, disposition, origin or digest changes shape**, and no member is
  added to `GoalAuthorizationStore` or `AuthorizationResolution`. §1's three write paths, its
  never-edited coverage and its per-goal scoping are **read** exactly as written; §7's four-route
  partition is **read** as the discriminator it already is, on the row alone and with no store read
  to tell the routes apart; §11's rendered values are what §2's *confirmed* means. **§13's
  no-cached-verdict rule is the one a reader might expect to fail and does not**: its subject is
  **reusing** a verdict to authorise a dispatch — *"would go on authorising sends after its
  authorisation stopped being checkable"* — and this decision authorises nothing, dispatches
  nothing and reaches no policy; what it reads is the **record** ADR-0254 §7 obliges `record` to
  refuse unless ten conditions held.
- **ADR-0254 §16, with §7's construction clause** — *yes*, in one scope, and the header states it:
  **the sentences naming `AuthorizationResolution` the trail's face and its reader**. §3's
  comparison holds that same face, so a reader holding only them builds a system in which the trail
  is its only holder and would refuse the construction L4 needs. **Nothing else of either moves**: the member is `resolve(id)` and nothing
  else, the eight signatures, the detached-snapshot discipline, `live_for`'s and `record`'s
  restriction to the policy and the composition root, and the structural-typing argument that makes
  the division sound each bind entire — a verification phase can name neither `record` nor
  `live_for`, for exactly the reason that argument gives.
- **ADR-0266 §10** — *yes*, in one scope, and the header states it: **its *"What the verification
  phase does with a quote, and coverage's other conditions"* entry, in the *"Fired by A10"* clause
  and in its application to the charge confirmation and the mismatch finding alone**. A reader
  holding only §10 waits on this decision for a comparison this decision cannot make — the operand
  does not exist (§9) — and so reads that entry more widely than it now holds. **Nothing else of
  §10 moves**: *coverage's other conditions* stay fired by the decisions those clauses already
  name, `AttemptPhase.VERIFY` stays A10's by ADR-0255 §17's assignment, and the entry's own
  refusals — no clause there verifies anything, compares a charge or writes a finding — bind
  entire.
- **ADR-0266 §1, §3 and §7** — *no*. §1's rule that a `criteria` element mints no coverage
  member is **relied on** and keeps the two decisions' subjects disjoint — this decision mints no
  coverage member anywhere and writes no row; §3's `kind` and its one-member-per-kind refusal are
  **read** and gain nothing, this decision adding no `BoundKind` member; and §7's proof of a bound
  against the quote is **relied on** and repeated by nothing — it is what binds a charge today, and
  the scope above weakens no part of it.
- **ADR-0267 §10** — *yes*, in one scope, and the header states it: **its first entry, in the
  clause naming *"A10's verification of the charge afterwards, which is a finding rather than a
  prevention"*, and in its application to *which decision performs that verification* alone**. That
  clause offers a reader one of the two safeguards standing today against a declaration naming less
  than the whole charge, and this decision performs **no** such verification (§9) — so a reader
  holding only §10 counts a safeguard that is not there. **The finding is not weakened and neither
  is the residual**: a charge confirmed afterwards is still a finding rather than a prevention, the
  decision that rules what such a finding does still fires it, and the optional `MONEY` argument
  declaration beside it is untouched.
- **ADR-0267 otherwise, entire** — *no*, and this is the entry rounds 8-10 of this document would
  each have had go a different way. **No clause of this decision reads an `ActionQuote`, a `quoted`, a
  `quoted_output` or any field of any of them**, so §1's *"`plan`, `read_from` and `read_at` are
  read by no clause"*, §3's declaration, §4's mint and §7's *"`quoted` is provenance"* and
  no-reader clauses each stay true **word for word**, and every other residual §10 books is left
  standing by name.
- **ADR-0021 §1 and ADR-0192 §2** — *no*. §2 **relies on** ADR-0021 §1's embedded definition rather
  than widening it — *"There is no name left to rebind"* is what makes a pinned comparison possible
  — and adds no field to `ActionRequest`, `PermissionDecision` or `PermissionRuling`. ADR-0192 §2's
  *"Version 2 is the invocation shape"* is a statement about that decision's own bump and stays
  true; the marker moving again is that section's **mechanism exercised** (ADR-0049 §1).
- **ADR-0029 §3 and ADR-0032 §2** — *no*. §4 **reads** the ruling ADR-0032 §2 already makes and
  states no rule of its own about it: it adds no field to `ToolResult` or `ToolFailure` — which
  that section refuses in terms — reclassifies no outcome, and leaves *"an exception escaping the
  tool implementation becomes INTERNAL"* exactly where ADR-0032's own amendment record put it. The
  route neither section rules is booked in §9 and filed as #2415, **against ADR-0032 and not
  against this decision**.
- **ADR-0016 §2, ADR-0014 §4 and §5, ADR-0039 §10, ADR-0049 §1, ADR-0148 §9, ADR-0173 §6,
  ADR-0193 §6 and §11, ADR-0237 §3, ADR-0242 §9, ADR-0244 §2 and §9** — *no*. Each is cited for a rule it already states and gains no
  clause; every sentence of each stays true.

### 11. The lane cut

**Six lanes, exactly one production subsystem each, and the order is what keeps `main` both green
and safe at every point in it.**

- **LA — `permissions`, first.** The audit trail's `_SCHEMA_VERSION` **+1** with its openable set
  and its additive create-and-migrate restamp (§8), so that code predating L1 refuses a trail
  carrying the new declaration at **open** rather than at the first unreadable row (ADR-0049 §1).
  It adds no member, no type and no clause of its own.
- **L1 — `core` (with `wire` and `testing`).** `ToolDefinition.postconditions` with its
  `OUTPUT_PRESENT` refusal; `AttemptTransition.execution_versions` **as a field with its non-negative validator and nothing
  more**, no store refusal of its own;
  `AttemptReport`; `TurnOutcome.attempt_report`; the docstrings naming this ADR;
  `PROTOCOL_VERSION` **+1** with its `wire/envelope.py` log entry; and the canonical fakes carrying
  the new field. **It states no Protocol refusal**, so every existing caller still commits.
- **L2 — `orchestration`, compatibility only.** The three existing `commit_attempt(→ ENDED)` call
  sites pass the **complete** `execution_versions` snapshot, read where they read the attempt.
  **It computes no verdict, writes no `GoalStatus` and changes no behaviour** — it teaches the
  callers the shape L3 is about to require.
- **L3 — `planning` (with `core/protocols.py`, the shared conformance suite and the canonical
  fake).** **§5's `→ ACHIEVED` conjunct on `PlanStore.set_goal_status` and §4's `→ ENDED` conjuncts
  on `PlanStore.commit_attempt`** — the Protocol strengthening, its `planning` implementation, the
  suite cases and the fake's refusals, **in one change**, which is `CONTRIBUTING.md` → "Adding a
  Protocol" read for a **change** to one: *"The triad is what a Protocol change is measured against
  too"*, travelling with its one primary production implementation. **It also carries
  `AuthorizationResolution`'s docstring change** (§8) — a contract edit in the same
  `core/protocols.py` file, with no implementation, suite case or fake to move. These are the
  **BREAKING** contract changes under golden rule 5.
- **L4 — `orchestration`, the phase.** The `VERIFY` comparison: §3's rung, §2's three results,
  and §4's six limbs — all **before** the composing stage; then, after it, the
  `commit_attempt` that ends the attempt with its outcome, §5's `set_goal_status` with its
  no-retry rule, `attempt_report`, and the two values §6 hands the composing stage. **It replaces
  the unconditional `AttemptOutcome.ANSWERED` at the three sites that write it today** — that value
  becoming §4's limb 6 rather than the only answer. **It takes one new collaborator**, the
  `AuthorizationResolution` ADR-0254 §16 declares (§3), and no other. **It records nothing on an
  interpretation and resolves no label**: §2 adds no field a planner proposes.
- **L5 — `interfaces`.** §6's six fixed statements, on the CLI and on the browser — **both
  surfaces**, since a member rendered on one and not the other is the parity failure M4 recorded.
  **Thin, by golden rule 3**: it renders values L4 computed and derives none.

**Merge order is LA → L1 → L2 → L3 → L4 → L5**, each one PR (the owner's *one lane, one PR* rule),
and **the middle of it is the part that is not tidiness**. A refusal that lands before its callers
puts `main` red; a comparison that lands before its refusals puts `main` **unsafe**, running §4's
verdict and §5's `ACHIEVED` write over the two races §4 and §5 say the conjuncts close. **L2 then
L3 then L4 is the only order in which neither happens**: the callers learn the shape, the store
begins refusing, and only then does anything compute a verdict. **No lane changes production code
in two subsystems**; L1's and L3's `testing`/`tests` files are test-only, and L3's
`core/protocols.py` edit is the contract half of the triad that rule's own exception names.

**What L4 waits for besides L3, stated rather than discovered.** §2's operands are
`CoverageMember.kind` (ADR-0266 §3), `PermissionRuling.authorised_goal` and the route partition
(ADR-0254 §7) and `AuthorizationResolution` (ADR-0254 §16) — **both ratified and neither
implemented** at `58f0797f`. **And §5's exhaustiveness
needs ADR-0261's implementing lane**: that section's *"there is no third case"* rests on
ADR-0261 §2's `open_attempt` refusal over a **closed** goal, which the tree does not yet make, and
without it an attempt can be opened after the status write. **So L4 lands after ADR-0254's,
ADR-0266's and ADR-0261's implementing lanes**; LA, L1, L2, L3 and L5 depend on none of them and
are ordered only by each other.

### 12. The arms this decision owes

**Ten.** Each is stated over the lane that owes it, and each runs against controlled fakes (§7).

1. **S1, end to end, unchanged in cost (L4).** *"What is two plus two?"*: a goal whose `criteria`
   are empty, one `Planner.plan` call and one composing call, no step claimed, and the attempt's
   stored row ending at `VERIFY`/`ENDED`/**`ANSWERED`** with the goal's status still **`ACTIVE`** —
   ADR-0249 §16's arm 1 asserted verbatim and still passing. **And the negative half**: no
   `set_goal_status` call is made, `attempt_report.outcome` is `ANSWERED` and `continues` is
   `False`.
2. **The two moments, asserted as an order (L4).** A goal with one criterion whose bound step
   stands `SUCCEEDED` over an output every declared postcondition holds over ends `VERIFIED`, its
   goal `ACHIEVED`, and the turn carries a report. **And the order is forced, not assumed**: the
   phase is driven with a composing stage that
   records whether it was entered, asserting it was **not** entered when the comparison ran and
   **was** entered before either commit; and with a composing stage returning text that carries
   every declared postcondition's key and value, asserting the criterion is still
   **unestablished** — the arm that fails against an implementation verifying over a composed
   reply.
3. **The three results, R50, and the per-criterion comparison (L4, L1).** One arm per result over
   a criterion whose confirmed member stands and whose bound tool declares **two** postconditions:
   **met** (a `SUCCEEDED` bound step's output satisfies both), **unmet** (it satisfies one and
   refuses the other), **unestablished** (the tool declares **none**; and, separately, no bound
   step succeeded). **And no `FAILED` step is read as an answer**: a bound step `FAILED` under a
   `side_effecting` tool → **unestablished** under `NATURAL`, `KEYED` and `NONE` alike, and a bound
   step `FAILED` under a tool that is **not** `side_effecting` — a status read that could not reach
   its provider — → **unestablished** likewise, **never `unmet`** in either case; while the **same
   criterion refused by a `SUCCEEDED` step's own output** → **unmet** — the three arms that fail
   against an implementation reading a failure as proof the outcome does not hold, which ADR-0029
   §3's escaping exception and its no-output rule each falsify. **And the per-criterion half is asserted in both directions**: a goal carrying
   a `PERIOD` criterion and a `TERMS` criterion whose spans are the two the confirmed row's two
   members rest on, over one booking step → **both met**; the same goal where the row carries a
   `PERIOD` member alone → **met and unestablished** respectively, the arm that fails against any
   rule giving one verdict to every criterion of a goal. **And the grouping by
   `parameters_digest` is asserted in every direction**: two bound steps of **one call** — the same
   digest — one **satisfying** and one **contradicting**, both `SUCCEEDED` → **unestablished**, the
   ambiguous-group arm, and the same pair in the other order → **unestablished** likewise, the arm
   that fails against any implementation letting a step order break the tie; two bound steps of
   **one call both** satisfying → **met**, and both contradicting → **unmet**; a `FAILED` step of
   one call **beside** a satisfying step of that same call → **met**, the arm that fails against a
   rule reading a failure as an answer; two bound steps of **different calls** — different digests,
   the two rooms — the first **contradicting** and the later satisfying → **unmet**, and neither
   `VERIFIED` nor `ACHIEVED`; and an ambiguous call **beside** a contradicting one → **unmet**, the
   arm that pins the order of the three results. **And a `MONEY` criterion is
   `unestablished` whatever else holds**: a confirmed `MONEY` member over a booking step every
   declaration holds over → **unestablished**, the attempt `UNCERTAIN` at rung 2 and the goal not
   `ACHIEVED`. **And
   `OUTPUT_PRESENT` is unconstructible** as a declared postcondition (L1) — the arm that fails
   against a model-authored predicate. **And prose is not an operand**: the same criterion
   satisfied word for word by the composed reply, by a `GoalElement.text` and by an
   `IntendedAction.intent` and by no bound step's output — **unestablished** likewise. In every
   failing case the attempt is not `VERIFIED` and the goal is not `ACHIEVED`.
4. **No model can move any criterion to *met*, and the campsite case end to end (L4).** A goal
   whose criteria are *Riverside*, *Sunday* and *up to 150 euros*, a confirmed row carrying the
   three members those spans rest on, and a booking step authorised route-(d) against it whose
   declared postconditions hold → the first two **met**, the third **unestablished** because it is
   a `MONEY` criterion (§2), so **not `fully_met`**, the attempt **`UNCERTAIN`** at rung 2 and the
   goal **not `ACHIEVED`** — which is the whole of what this decision can honestly say about a
   booking that charges; **and the same goal without the third criterion → `VERIFIED` and
   `ACHIEVED`**, the pair that shows the mechanism works and shows exactly what §7 says it does not
   cover. **And each conjunct removed in
   turn leaves the criterion unestablished**: the row's `origin` `OPENING_ACT`; the row belonging
   to **another goal**; the step's
   decision a route-(a), (b) or (c) `ALLOW`, or carrying no `authorised_by`; the member's
   `basis.span` differing from the criterion's `span` by one character; the criterion carrying **no
   `span`** at all. **And a row
   `REVOKED` or `SUPERSEDED` *after* the dispatch still establishes** — the arm that fails against
   an implementation re-testing the disposition at `VERIFY`. **And the
   join is asserted to be unique or nothing**: two `ESTABLISHED`/`CONFIRMED` rows of this goal for
   **two declarations**, each carrying a member on that one span, one row's bound step satisfying
   its declarations and the other's contradicting them → **unestablished**, whichever order the
   rows are read in, and neither `met` nor `unmet`; the same over **two members of one row** at two
   kinds resting on one span → **unestablished** likewise — the arms that fail against any
   implementation that picks a row, unions them, or lets read order decide. **And a row the attempt
   never acted under is not an authorising row**: an `ESTABLISHED`/`CONFIRMED` row of this goal for
   a third declaration, carrying a member on that same span and named by no step's decision, leaves
   the criterion **met** — the arm that fails against an implementation enumerating the goal's rows
   rather than resolving the ones its own steps point at. **And the
   Saturday case**: a request the row's `PERIOD` member does not fit is never dispatched — the step
   is committed `AWAITING_APPROVAL` (ADR-0254 §13) — so no bound step succeeds and the criterion is
   **unestablished**, the arm that fails against any implementation reading a provider's
   `{"status": "ok"}` as agreement with the date. **And a planner that returns every value it can
   return changes no result**: the same goal replanned with different `serves` links, with the
   step's `intended_action` **changed and then removed entirely**, and with the criterion's text
   restated yields the **same** three results — the second half being the arm that fails against a
   satisfaction test reading a planner-supplied action at all — the arm that fails against any
   model-authored binding. **And the one planner-written value that does change a result is
   asserted as §9's residual rather than as a guarantee**: the same goal whose criterion text
   describes an unrelated fact while its `span` stays the one the row's member rests on reads
   **met**, and the arm records that §2 compared the span and never the text.
5. **The ladder, asserted over the declarations and over the ordering (L4).** Rung 0, rung 1 and
   rung 2 each produced by the declaration that names it, over a claimed step; **and a step a plan
   declared and no walk claimed leaves the rung where it was**. **And the ordering trap
   explicitly**: a step whose tool is `side_effecting` with `reversibility=IRREVERSIBLE` and empty
   `discloses` reaches **rung 2** — the arm that fails against a lexicographic comparison, under
   which `"irreversible" > "reversible"` is `False`. **And `discloses` alone**: a `side_effecting`,
   `REVERSIBLE` tool with non-empty `discloses` reaches rung 2. **And the satisfied step**: a step
   committed `SUCCEEDED` from an earlier completed effect — no `→ RUNNING` claim of its own,
   carrying `satisfied_by_execution` and `satisfied_by_step` — reaches the rung of **the step those
   name**, and reaches **rung 2** where that step cannot be read; the arm that fails against an
   implementation reading it as rung 0 while §2 verifies against its borrowed output. **And the
   same step establishes its criterion**: with **no `bound_tool` of its own** (its source status
   was `PENDING`), the holder's pinned declarations **and the holder's own route and
   `authorised_by`** are followed and the criterion reads **met** — the arm that fails against an
   implementation reading the target's absent tool as unestablished.
   **And the declaration is the pinned one**: after the registry re-registers that tool id with
   declarations the stored output would fail, the recorded verdict is **unchanged** (L1). **And a
   store failure is not a verdict**: an audit read and an `AuthorizationResolution.resolve` that
   each raise propagate, while a decision the trail does not hold and a row the resolution returns
   as `None` are each `unestablished`. **And an unreadable pinned decision is rung 2, not rung 1**:
   a **claimed** `SUCCEEDED` step whose `approval_ref` names a decision the trail does not hold,
   with every criterion unestablished, reaches **rung 2** and ends
   **`UNCERTAIN`** — never `ANSWERED` — the arm that fails against an implementation defaulting an
   unreadable definition to the harmless rung. **And LA's own arm**: a trail at the previous marker opens,
   migrates and is restamped, its existing decisions decoding with `postconditions` empty; a trail
   at the new marker is **refused at open** by code at the previous one, before any read.
6. **§4's six limbs, and the order (L4).** One arm per member. **And one arm per precedence
   boundary**, because the single-member cases are all passed by an implementation testing the
   limbs in the wrong order: a met **and** an unmet criterion → `PARTIAL`, never `VERIFIED`; a
   failed **read** at **rung 0 or 1** with **every criterion unestablished** → `FAILED`, **never
   `ANSWERED`**, which is the arm that pins limb 1 to ADR-0249 §5's *"no step failed"*; a `FAILED`
   step **beside** a met criterion → `PARTIAL`; a skipped `UNMET_DEPENDENCY` step with no claim, no
   failure and every criterion unestablished → `CONDITION_PREVENTED`, never `ANSWERED`; a **rung 2**
   attempt whose consequential step **succeeded** and whose goal carries **no criterion at all** →
   `UNCERTAIN`; the same with one criterion **met** and one **unestablished** → `UNCERTAIN`,
   **never `PARTIAL`**; **an unrelated `FAILED` step beside that successful consequential act,
   every criterion unestablished** → `UNCERTAIN`, **never `FAILED`**, and **the same beside a
   `SKIPPED` one** → `UNCERTAIN`, **never `CONDITION_PREVENTED`** — the two arms that fail against
   limbs 1 and 2 reading a failure about something else as a verdict about the criteria. **And the
   member does not turn on the criterion join, which is the pair that pins §2's `FAILED` rule**: a
   rung-2 attempt whose **only** consequential step stands `FAILED`, every criterion
   **unestablished**, → **`UNCERTAIN`**, and the identical record with that step **bound** to a
   criterion → **`UNCERTAIN`** likewise, never `FAILED` — the arms that fail against an
   implementation reading a side-effecting failure as a disproof, whatever its `idempotency`.
   **And `UNCERTAIN` turns on the rung and on nothing else, which is the pair that pins §4's
   reading of the seam's own ruling**: a **rung-1** attempt whose only step is `side_effecting`
   with `reversibility=REVERSIBLE`, empty `discloses` and no egress binding, standing **`FAILED`**,
   with every criterion **unestablished** → **`FAILED`**, **never `UNCERTAIN`**, identically to the
   same attempt whose only step is a failed **read**; while the identical record with that step
   standing **`INDETERMINATE`** ends **no attempt at all** (item 7) — the pair that fails against
   any implementation deriving a possible effect from `side_effecting` and `FAILED`, which is the
   derivation ADR-0032 §2 already ruled out. **And a criterion is refused only by an
   answer**: a criterion whose bound step **`SUCCEEDED`** under an output its declarations refuse →
   `FAILED` at every rung, the arm that keeps *established not to hold* reachable. **And the
   satisfied step carries the rung**: an attempt whose only step is **satisfied from an earlier
   effect** at a rung-2 holder, with every criterion **unestablished** and no failure and no skip,
   → **`UNCERTAIN`**, **never `ANSWERED`**, and **the same where the holder cannot be read** →
   `UNCERTAIN` likewise — the pair that would otherwise let ADR-0249 §5's *"nothing was verified,
   no step failed"* be asserted of an attempt that borrowed a consequential act's own answer; a **rung 2** attempt with **every criterion
   met** beside an unrelated `FAILED` step → **`VERIFIED`**, and its goal `ACHIEVED` — the arm that pins limbs 4 and 5 to the criteria
   alone and keeps §6's `PARTIAL` statement true of every attempt that reaches it; a rung-2 attempt
   with a criterion **unmet** → `FAILED` whatever else stands; a **read that succeeded** followed
   by a step skipped
   `APPROVAL_DENIED`, every criterion unestablished → `CONDITION_PREVENTED`, the arm that pins
   `blocked` to the skip rather than to the absence of any claim; and the **same state at rung 1
   with no skip** → `ANSWERED`.
7. **The attempt does not end, in every limb of the ending rule (L4).** A turn whose attempt is
   `AWAITING_AUTHORIZATION`; one whose execution holds an `INDETERMINATE` step — **and the same
   attempt with every criterion `met`**, which is the arm that pins `VERIFIED` and `ACHIEVED` out
   of reach beside a possible effect without a conjunct on limbs 4 and 5; one holding a step
   still `PENDING` after ADR-0255 §2's `AMBIGUOUS_CAPABILITY` stop — **and the paired assertion
   that the next turn's ADR-0259 §4 act 1 sweeps it and the attempt then ends**, which bounds the
   cost to one turn; and one whose composition returned no text or came back degraded — **each
   writes no `AttemptOutcome`, leaves the attempt non-terminal, writes no `GoalStatus`, and returns
   `attempt_report` `None`**. **And the reconciliation route stays open**: after the
   `INDETERMINATE` case, ADR-0259 §4's act 3 commits the attempt `EFFECT_UNRESOLVED` and its act 4
   later commits it `RUNNING` — the arm the owner's uncertain-outcome exception rests on.
8. **The two store conjuncts (L3, shared suite).** Asserted against every conforming `PlanStore`.
   ***`commit_attempt`***: a `→ ENDED` transition is refused with `StaleExecutionError` and
   **writes nothing** where any step of any execution the attempt names stands `PENDING`,
   `AWAITING_APPROVAL`, `RUNNING` or `INDETERMINATE`, and is accepted where every such step stands
   `SUCCEEDED`, `FAILED` or `SKIPPED`. **And the three interleavings it exists for**: a step
   `PENDING` when the caller read it and **claimed** before the commit is refused; an execution
   **appended** to the attempt after the caller read it advances `GoalAttempt.version`, so the
   transition is refused on its `expected_version`; and a step **`FAILED`** when the caller read
   it, taken `RUNNING` and `SUCCEEDED` before the commit — every step terminal at both instants
   and the status conjunct silent — refused with **`StaleExecutionError`** on
   `execution_versions`, the arm that fails against an implementation carrying the field and not
   comparing it. **And the field's own limbs, each refused with `ValueError` and not with
   `StaleExecutionError`**: a pair naming an execution the attempt does not name, a **missing**
   id, a **duplicate** id and a **partial** snapshot — the arm that fails against a subset the
   omitted execution could move under, and the one that pins a malformed command apart from a lost
   race — **and a pair carrying a negative `version` is refused at construction (L1)**, before any
   store sees it, the arm that fails against a field typed `int` and validated nowhere; an **empty** tuple is accepted for an attempt naming no execution and refused for one
   that does; **an execution appended after the caller's read is refused on `expected_version`**,
   not as a malformed set, the arm that pins the order of the two tests; and a `→ CANCELLED`
   transition carrying a stale pair still commits.
   **`→ CANCELLED` and every other `AttemptTransition` are unaffected**, ADR-0261 §3's own
   `(CANCELLED, UNCERTAIN)` case asserted to still commit over an `INDETERMINATE` step.
   ***`set_goal_status`***: an `→ ACHIEVED` write is refused with `StaleExecutionError` and **writes
   nothing** where the goal has a non-terminal attempt — **including one opened after the caller
   read the goal** — and is accepted where every attempt is terminal and where the goal has no
   attempt at all. **`→ ABANDONED`, `→ BLOCKED` and `→ ACTIVE` are unaffected**, `→ ACTIVE` over a
   live attempt being ADR-0250 §13's reopen and asserted to still succeed. **And `open_attempt`'s
   closed-goal limb is asserted beside it** over an `ACHIEVED` goal, so the pair §5 calls
   exhaustive is shown to be.
9. **`ACHIEVED`'s producer, R53, and the no-retry rule (L4).** `set_goal_status(…, ACHIEVED)` is
   called **exactly** on limb 5 and on no other member, **after** the attempt's commit; and each of
   the other five ends an attempt while the goal's status is **unchanged** — the arm that pins
   R53's *"an attempt ending is not the same event as the task completing"*. **And the refusal**:
   where a concurrent turn records a new interpretation revision between the act's read and its
   write, the status write is refused, **nothing further is written and no second call is made**,
   the turn does not fail, and the attempt still reads `ENDED`/`VERIFIED` under an open goal — the
   arm that fails against a retrying implementation, which would write `ACHIEVED` over a criterion
   the comparison never saw. **And the paired refusal one commit earlier**: where the
   `commit_attempt` §4 names is refused after the reply was composed, **nothing further is
   written** — no second commit, no `set_goal_status` call — the turn does not fail, the reply that
   already went is **not** re-rendered or retracted, `attempt_report` comes back `None` so **no
   fixed statement is rendered on that turn** (§6), and **the next turn that engages the goal runs
   its own comparison and renders its own statement** — the arm that fails against an
   implementation replaying the stored verdict, and the one that pins the cost §6 names to a
   silence rather than to a false outcome word.
10. **The report, on both surfaces (L4, L5).** Each of the six members produces its own fixed
    statement, on the CLI and in the browser, **beside the reply and never in place of it**;
    `continues` is `True` on exactly `PARTIAL`, `FAILED` and `UNCERTAIN` over an open goal and
    `False` on the other three; the composing stage's instruction **carries the offer** where
    `continues` is set; and **`attempt_report` is `None`** on ADR-0198 §1's restatement and on a
    routed operation. **The statements are asserted by their facts rather than their prose** —
    `ANSWERED`'s says nothing was verified, `VERIFIED`'s speaks of the criteria **this attempt
    compared**, `CONDITION_PREVENTED`'s is asserted true of **both** of `blocked`'s sources — an
    `UNMET_DEPENDENCY` skip, and an `APPROVAL_DENIED` one after a read that succeeded — and
    `FAILED`'s true of **both** of limb 1's arms, an unmet criterion and an unrelated failed step
    with every criterion unestablished, **and true of a criterion made `unmet` by one call while
    another call of the same criterion satisfied** — the arm that fails against a statement
    denying work the same comparison established — and **no arm fixes the wording**, which is the
    lane's (§6).

**No arm demonstrates a real consequential integration** (§7's gate); M33's walkthrough runs
against a simulated booking service.

### 13. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**A new decision that partially supersedes four ADRs** (§10), in one narrow scope each — a field
enumeration, a sentence naming a Protocol's holder, and two residual bookings that named this
decision as what fires them — **none of them a rule**, the last two reassigning a question to the
decision that lands its operand rather than answering it differently; and a **stacked addition**
against every other ADR it reaches, each of which it **reads** without widening a clause of any.
It is
**marked** under ADR-0089 §2 as ADR-0257 §1 admits the label, so the marked clauses are the whole
of what it obligates.

## Consequences

**What becomes easier.** `GoalStatus.ACHIEVED` gains its producer, so a completed objective stops
being indistinguishable from an unstarted one, and `GoalInterpretation.criteria` gains its first
reader that settles anything. Five `AttemptOutcome` members gain producers. The records the user's
own confirmation already leaves acquire a **second reader** — one that can only refuse to say
*verified* — so R48 is met without a new field, a new label or a new thing for a model to get
right. R53's distinction becomes a property of where two writes sit. And ADR-0255 §13's gate
acquires its third guarantee.

**What becomes harder.** A peer at the old `PROTOCOL_VERSION` refuses a peer at the new one —
intended and loud. A goal that reaches `ACHIEVED` can no longer open an attempt at all (ADR-0261
§2), so a caller must reopen it first (ADR-0250 §13). An integration author now has one more thing
to declare, and a tool that declares nothing verifies nothing. **And the bar is high by
construction**: a goal reaches `VERIFIED` only where the user's own constraint was put to them and
confirmed, the act ran under **that row**, and the tool declared what its success establishes — so
a capability authorised per call, a criterion the user never stated in words a member rests on, a
criterion stating an **amount**, and a goal whose acts nobody bounded each reach `UNCERTAIN` at
rung 2 and stay open. **That is the deliberate direction and it is where a falsifier would show up
first** (below). And a goal whose step stands
**`INDETERMINATE`** now deliberately **does not** end its attempt, so it stays open until A8's
reconciliation reaches it — the owner's ruling, and a state a user sees on `assistant goals` rather
than one the system quietly closes.

**What would trigger revisiting this.** A corpus of goals in which **no** criterion's `span` ever
equals a confirmed member's would say the span is the wrong join. A booking capability whose goals
all stop at `UNCERTAIN` because every one of their criteria is about an amount would say the
charge operand §9 books is the next thing to build rather than a residual. A corpus of integrations declining to declare any postcondition
would say the declaration is in the wrong place. And a deployment in which `UNCERTAIN` is the
effective terminal member for every consequential goal would say the conjuncts are too strong — the
first place to look being §2a's route-(a) cost, which §9 books.

## Alternatives considered

**Any model-authored association between a criterion and the act that establishes it — a `check`
on the `GoalElement`, an `establishes` on the `PlanStep`, a read of `IntendedAction.serves`.**
**Refused, and this is the decision the first six revisions of this document got wrong.** Each
shape was narrowed until the model could only *choose which act* and never *choose the predicate*,
and each still left the model the **existence allow** ADR-0249 §7 forbids: without an association a
criterion is unestablished, so adding one is the act that creates the path to `VERIFIED`. The
narrowings were real and none of them reached the objection, which is about the binding rather than
the comparison. **What closes it is not a better narrowing but a different question**: *what does
the record already say the user asked for, and was the act proved against it?* — which ADR-0254 and
ADR-0266 answer in full, for their own reasons, with no field this decision adds. **Reading
`serves` is refused for a second reason besides**: ADR-0265 §3 rules in terms that **no lane**
*"derives an intended action from `serves`"*, and its harmless-stale-link clause is bought
precisely by nothing reading one — reading it here would turn a rewording into a silent
mis-association of a criterion with an act, and would put the owner's rewording requirement at risk
to buy a link §2 does not need.

**Establishing a criterion from a `GoalEvidence` row through ADR-0252 §6's four tests.** Refused
(§9), and it was this decision's first shape. Those tests are stated over a `StepCondition`, whose
`about` ADR-0253 §5 requires to name a **condition** element, and `PlanInterpretation.settles` is
condition-only too — so there is **no ratified association from a criterion to a row**, and a
verification reading "the goal's rows" would apply any qualifying row to any criterion.
**`IntendedAction.serves` is not that association either**, and ADR-0265 §3 refuses it in terms:
*"`serves` gates nothing"*, and **no lane** *"gates a dispatch on a `serves` entry"* — a stale entry
after a rewording is *"truthful and harmless"* precisely because nothing reads it, and reading it
here would turn a rewording into a silent mis-association of a criterion with an act.

**A planner-authored predicate as the check — a `StepVerification` the interpretation carries.**
Refused (§2), on a concrete case: a planner declaring `FIELD_EQUALS` on `status == "ok"` for a
criterion about a **date** produces `VERIFIED` and `ACHIEVED` over a booking made for the wrong day
— R53 failing on exactly the case R48 exists for. Reusing `PlanStep.verifies` itself is refused
twice over — one predicate answering two questions, and a third reader of ADR-0255 §8's *"exactly
the two places"* — and `OUTPUT_PRESENT` is refused anywhere here because *"the step returned
something"* is R48's circularity one level down.

**Selecting among a tool's declared postconditions at all — by index, or by a key the criterion
names.** Refused with the association above. A key can only *narrow*, since **met** requires the
whole declared set to hold; what it cannot do is stop a criterion the user never confirmed from
becoming **met** over an act that happens to declare that key. **§2 needs no selector**: a
criterion is told from its neighbours by the **member the user confirmed**, and the whole declared
set is required of every bound step.

**Widening the bound steps past a route-(d) `ALLOW`.** Refused (§2a, §9). A route-(a)
confirmation is the user assenting to a **concrete call**, and what it records is a
`parameters_digest` — a fingerprint, not a typed value, so a criterion has nothing to agree with by
kind. Treating a digest as agreement would be reading *the user approved this call* as *the user's
constraint was met*, which is the inference R48 exists to refuse.

**Reading the declaration from the registry at verification time.** Refused. ADR-0021 §1 embeds
the whole definition in the decision precisely so that *"There is no name left to rebind"*, and a
registry read would let a restart change a recorded act's verdict.

**Minting a per-criterion verdict enumeration in `core` — `ESTABLISHED`/`NOT_ESTABLISHED`/
`AMBIGUOUS`, as revision 0 of the fit report proposed.** Refused. The three results §2 needs are
computed and consumed inside one function, as ADR-0252 §6's four tests are, and a `core`
enumeration would be a wire-carried, exported, storable value with no consumer — *"a field with no
consumer is surface"*. **The `CriterionCheck` naming the establishing act and its kind, which
rounds 7-10 of this document carried, is refused for a second reason**: naming the act needs an act
identity, the only one the corpus has is `PlanStep.intended_action`, a **planner** writes it, and
a verdict that turned on its presence handed a model the allow §2a says it does not have.

**A `PlanStore.close_goal_achieved` mirroring ADR-0261 §2's `close_goal_abandoned`, including the
variant carrying the already-computed verdict so the store evaluates nothing.** Refused twice over.
The plain member would put a JSON predicate evaluator inside a store write; the verdict-carrying
one buys only the case where a revision lands between the comparison and the status write — where
**the refusal is already the right answer** (§5) — at the price of a **second** exception to
ADR-0250 §9's *"every change goes through this member"*, a sentence ADR-0261 §12 records as made
false **once**.

**Retrying the `ACHIEVED` write after a lost `Goal.version`.** Refused. A goal's version moves when
a turn records a new interpretation revision, so the re-read could return criteria the comparison
never saw, and the retry would write `ACHIEVED` over one of them — R53's failure arriving through
the recovery path.

**Verification making a model call where a criterion is unestablished.** Refused (§2, §9). It is
the `ACHIEVED` write's prerequisite and ADR-0249 §7 forbids a model clearing one, and #2096 item
8's principle is why the asymmetry runs one way — *"A model is a safe denier and an unsafe
allower."*

**Verification performing the independent read itself at rung 2.** Refused on the owner's ruling
of 2026-09-13: *"Nothing checks on its own initiative."* A read inside `VERIFY` would be an
unplanned, unauthorised call after the walk ended, on a budget §3 would have invented.

**Deriving `GoalStatus.ACHIEVED` from `AttemptOutcome.VERIFIED` at read time.** Refused. ADR-0249
§4 rules that *"An attempt reaching a terminal state **does not** move the goal's status"*, and a
derived status would be a second authority that can disagree with the stored one.

**Reading `risk_level` into the ladder.** Refused (§3). Risk is what a policy thresholds to decide
whether to **ask**; reversibility, disclosure and the binding describe what an act **did**. One
scale answering two questions would let a tightened approval threshold silently change what counts
as verified.

**Announcing the outcome through `GoalEngagement` rather than a member of its own.** Refused.
ADR-0250 §5's four facets are *what this turn did with the goal it engaged*; what an attempt
produced is a different fact, and ADR-0244 §9's one-member-per-fact rule is the ratified shape.

**Putting the offer to continue on the surface rather than in the reply.** Refused (§6). Its whole
purpose is that a bare *"yes"* on the next turn binds by reply reference (ADR-0250 §3), and a
sentence an adapter printed reaches neither the browser's transcript nor the spoken channel, where
ADR-0200 §4 makes `spoken` the rendering of `outcome.reply` *"and of nothing else"*.
