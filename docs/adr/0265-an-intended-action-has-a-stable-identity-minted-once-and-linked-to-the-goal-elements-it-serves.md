# 265. An intended action has a stable identity, minted once, linked to the goal elements it serves

- Status: Proposed
- Date: 2026-09-13
- **Partially supersedes** [ADR-0249](0249-the-goal-carries-its-interpretation-the-attempt-carries-the-phase-and-the-planner-returns-its-understanding.md)
  — **three narrowly stated scopes, and §8 shows the working for all three. §1's `Goal` model
  declaration, in the field count alone**: `Goal` gains `intended_actions`, a possibly-empty
  `tuple[IntendedAction, ...]`, append-only and oldest first, so a reader holding only §1 authors
  a goal that can never hold the identity §6 requires of an effect claim. **§7's `PlannerOutput`
  field enumeration, in the field count alone**: *"carrying exactly two fields"* becomes three,
  `plan`, `understanding` and `actions`, because a planner that cannot propose an intended action
  cannot mint one and the record has no other author. **And §9's `GoalBrief` field enumeration
  together with its label scheme's sequence count**: the brief gains `actions`, a possibly-empty
  `tuple[BriefAction, ...]`, and the scheme *"applied to three sequences"* is applied to a fourth
  under the letter `A`. §1's append-only interpretation rule, its `statement`-as-projection rule,
  its four-absences clause and its `version` clause bind entire; §7's `Planner.plan` roster, its
  retained-or-restated validator, its retention-copies-forward clause, its `ProposedElement`
  shapes, its ground-resolution rules and their refusals, its no-identifier-crosses-the-seam
  clause and its interpretation-is-the-model's asymmetry all bind entire and are the grounds §2
  and §4 reason from; §9's no-ground-reference rule, its no-identifier rule, its
  projected-from-the-current-interpretation-alone rule and its element-free-brief clause bind
  entire; and §§2-6, §8 and §§10-17 stand entire.
- **Partially supersedes** [ADR-0253](0253-the-plan-declares-what-a-step-waits-on-what-fills-its-arguments-and-what-must-be-evidenced-before-it-is-dispatched.md)
  — **one scope, stated in two counts of one section. §9's label-space count and its
  fields-any-other-component-sets clause.** *"There are exactly three spaces"* — the step ordinal,
  the `M` label and the condition label — becomes four, the fourth being the `A` label of §4; and
  that section's four-field clause becomes a five-field clause, adding `PlanStep.intended_action`
  under the identical discipline it states for `StepCondition.about`. A reader holding only §9
  builds a loop that resolves no action label and therefore a plan whose steps cannot name the
  intent they serve. §9's every-value-is-an-ordinal-or-a-label rule is **relied on and widened by
  one space rather than loosened**; its resolve-once-immediately-on-return ordering, its
  resolution-is-not-authorship argument, its strict-extraction rule, its refusal of a plan
  carrying a label that resolves to nothing and its `save_plan` window-closing rule are each
  adopted whole by §4; and §§1-8 and §§10-15 stand entire. **§7 is relied on and superseded in
  nothing**: its element-id minting rule, its retention-does-not-re-mint rule, its
  restatement-mints-a-new-id rule and its id-is-never-a-label disjointness are the four clauses §1
  and §3 are built on.

## Context

### Where this comes from

Issue #2255 is the owner's six-phase task lifecycle, and this decision is a limb of A8 cut off
from it. [ADR-0259](0259-an-effect-is-claimed-once-per-goal-before-it-is-dispatched-and-a-turn-start-pass-reconciles-what-an-earlier-turn-left-uncertain-or-unfinished.md)
takes A8's first half — an effect is claimed once per goal — and keys that claim on the authorised
call's own arguments. The owner's correction of 2026-09-13 is that the key is not enough:

> *"A goal element and an action are not necessarily the same unit. One element could require two
> bookings; one booking could satisfy several elements. Linking actions to goal elements is
> useful, but that relationship alone does not establish action identity. … I would want a stable
> identity for the intended action, linked to the goal elements it serves. Rewording or splitting
> an element must not accidentally permit a duplicate booking. Reusing a completed result also
> requires checking that it still satisfies the current request."*

And, of the shape this document takes: *"treat 'goal-element-scoped identity' as a candidate to
test, not an already settled answer."* §10's arms are that test and the Consequences name what
would falsify it.

**The owner's sequencing ruling of 2026-09-13 fixes the interaction model every case here is
stated under.** The workflow is finished and demonstrated on the **existing** interaction model:
**a correction arrives as a subsequent turn**, and a pause is for clarification or approval. Live
steering, mid-run interruption and message queuing are a separate follow-up. So *"book two
identical rooms"*, *"change our booking to Sunday"*, and an intentional second action as against a
retry or a modification are each **a correction accepted between turns**, and **no clause of this
decision designs for a message reaching a running turn** — §7 books where one would enter and
states nothing more. Two requirements are carried verbatim and are what §6 and §10 are measured
against: *"an earlier booking must not count as fulfilling 'book another one'"*, and *"preserve
completed actions and reuse their results where they still satisfy the request"*.

### What the tree holds today, read rather than assumed, at `origin/main` `41ccbe76`

`Goal` carries an append-only `interpretation` and a `version` compare-and-swap token.
`GoalElement` carries an `id` minted once by `orchestration`, copied unchanged by a revision that
**retains** it and minted afresh by one that **restates** it (ADR-0253 §7). `PlanStep` carries
`id`, `intent`, `capability`, `parameters`, `depends_on`, `resolves`, `when`, `verifies` and
`evidence_recency`, and **not one of them names an act the goal intends**: `StepCondition.about`
names a *precondition* element, `verifies` is *"a predicate over this step's **own output**"* and
in terms *"never verification against the goal's criteria"*, and `resolves` is refused outside
`depends_on` and is therefore intra-plan. `PlannerOutput` carries `plan` and `understanding`.
`GoalBrief` carries the outcome, three labelled element tuples, a status, a deadline and the open
questions. `planning/planner.py` renders the `C`/`S`/`D` blocks and derives the `M` and `E`
labels; the label spaces in force are `M`, `F`, `C`, `S`, `D`, `E` and `G`, and **`A` collides
with none of them**.

### The gap this closes, stated as the failure the corpus has today

ADR-0255 §7 states the obligation and states honestly that it could not discharge it: *"Across two
plans of one goal this decision lands no mechanism"*, because *"a goal records no completed effect
that a driver could compare against"*. It also names the trap in the obvious repair — *"A driver
that compared capability and parameters would be inventing an identity nobody declared, and would
refuse a legitimate second booking of two different nights as readily as a duplicate."*

An argument key closes half of that and opens the other half. Two identical rooms on one goal are
**one** tool, **one** parameter digest and **one** binding, so an at-most-once rule scoped to the
goal alone dispatches the first and satisfies the second from it — the user asked twice and was
booked once. And a goal whose date moves from Saturday to Sunday carries a *different* digest, so
the same rule sees no earlier effect at all, dispatches a second booking, and leaves the first
standing — the user asked for a change and got a duplicate. The two failures are opposite and they
have one cause: **nothing on the record says which act a step is an attempt at.**

Nor can the elements supply it. An element is restated by a revision that rewords it and is minted
a **new** id when it is (ADR-0253 §7), so an identity derived from elements would be re-minted by a
rewording — which is the owner's *"rewording or splitting an element must not accidentally permit a
duplicate booking"* stated as a mechanism rather than as a wish.

### What this ADR is not allowed to settle

At-most-once itself and the effect key are ADR-0259's. Retry, modify-before-replace and
reconciliation are A8's second ADR's. Verification against the goal's criteria is A10's.
Cancellation is A9's. §7 names every deferral with what fires it, and no lane cites this decision
toward any of them.

## Decision

### 1. `IntendedAction`: a record the goal holds, minted once, and never an instruction to act

> **Normative.** `core/types.py` gains **`IntendedAction`**, a frozen model with `extra="forbid"`
> whose fields are exactly three: **`id`**, an `Identifier`; **`intent`**, a
> `NonBlankEncodableText` stating in the system's own words the act this goal intends; and
> **`serves`**, a possibly-empty `tuple[Identifier, ...]` of `GoalElement.id` values (§3). **It
> carries no fourth field**: no capability, no tool, no parameters, no step id, no plan id, no
> attempt, no instant, no status and no count.

> **Normative.** `Goal` gains **`intended_actions`**, a possibly-empty
> `tuple[IntendedAction, ...]`, **oldest first and append-only**. No lane edits a member in place,
> reorders the tuple, removes a member, or writes two members carrying one `id`. **The goal's
> opening write mints none**: a goal is opened carrying revision 1 alone (ADR-0249 §3), which
> `orchestration` mints from the request without a planner call, so `intended_actions` is empty on
> every goal at the moment it is opened.

> **Normative — an `IntendedAction` is a record of an intent and never an instruction to act.**
> **No lane walks `intended_actions` and dispatches, plans, schedules or reports from it.** An
> action nothing has named in a plan sits in the record and causes nothing; an action a plan named
> once and no later plan names again sits in the record and causes nothing. The tuple is read by
> §4's label resolution, by §5's export, and by the effect claim §6 obliges, and by nothing else.

> **Normative — the record carries no standing, and that is decided rather than deferred by
> omission.** Nothing in this decision withdraws, cancels, completes or retires an intended
> action, and the clause above is what makes an un-withdrawn one harmless. A two-member enum with
> no producer for its second member would be a box a later lane must reopen to say what it means,
> which is the empty-box failure ADR-0249 §10 refuses for `GoalEvidence`; **§7 books withdrawal
> with what fires it** instead.

> **Normative — an `IntendedAction.id` is never an action label, and the type refuses one.** An
> `IntendedAction` whose `id` matches §4's action-label grammar — the ASCII letter `A` followed by
> one or more decimal digits and nothing else — is **not constructible**. This is ADR-0253 §7's
> construction for `GoalElement.id` reused without alteration and for its reason: `Identifier`
> admits any non-blank encodable string, so without the rule an unsubstituted label could equal
> some action's id and pass §4's membership check **as a reference to a different action**,
> silently scoping an effect claim to the wrong act instead of refusing.

> **Normative — an identity is a minted record and is never derived.** **No lane computes an
> intended action from a goal's elements, from a step's `capability`, from its `parameters`, from
> a plan's shape, or from any comparison of two of them.** The record exists because
> `orchestration` wrote it (§2), and where it does not exist there is no intended action —
> not one a later reader may infer.

**Deriving it is the thing ADR-0255 §7 names and refuses, and stating the refusal here is what
keeps a later lane from reaching for it.** That section's *"inventing an identity nobody
declared"* is exactly what a capability-and-parameters comparison would be, and it is why this
record carries **no capability**: a capability is a planner-supplied string chosen from the
`capabilities` sequence of one call, and ADR-0253 §8 has already ruled that a plan's own spellings
are not durable declarations — *"A re-plan mints new step ids, so a fresh reading of the same
proposition in a later plan would carry a different declaration"*. What the record carries is an
**`intent` in prose**, which no mechanism compares, and an **`id`**, which every mechanism
compares and nothing can re-derive.

### 2. Minting: proposed at the planning seam, recorded by `orchestration`, once

> **Normative.** `core/types.py` gains **`ProposedAction`**, a frozen model with `extra="forbid"`
> carrying exactly two fields: **`intent`**, a `NonBlankEncodableText`; and **`serves`**, a
> possibly-empty `tuple[EncodableText, ...]` of **labels** of the brief or the understanding in
> force on that call (§3). It carries **no id**: a planner names no identifier and mints none,
> which is ADR-0228 §8's namer rule binding this field as it binds every other.

> **Normative.** `PlannerOutput` gains **`actions`**, a possibly-empty
> `tuple[ProposedAction, ...]` defaulting to empty. **Empty means the planner proposes no new
> intended action**, and it is the semantically correct answer for a planner that knows nothing of
> this envelope and for every turn that acts on an intent the goal already holds. No implementation
> reads an empty `actions` as an error, a degradation or an instruction to re-plan.

> **Normative — it rides on `PlannerOutput` and never inside `ProposedUnderstanding`, and the
> reason is that decision's own completeness rule.** ADR-0249 §7 makes a revision *"a complete
> statement of an understanding"* and rules that an element it *"neither retains nor replaces is
> **not** in the new revision"* — **omission is removal**. An intended action must survive every
> revision that does not mention it, because surviving a restatement is the whole of what it is
> for, so a carrier whose omission rule is removal is the one carrier it may not have. Minting is
> therefore **independent of revising**: a turn may propose an action without proposing an
> understanding, and an understanding that mentions no action removes none.

> **Normative — `orchestration` mints the `id`, once, at the instant the action is first
> recorded, and no lane re-mints it.** A later revision that restates, splits, merges or removes
> any element mints **no** new intended action and changes **no** existing one. A later plan that
> names an existing action by label (§4) mints none. The only route to a new `IntendedAction` is a
> `ProposedAction` recorded by the member §5 adds.

> **Normative — the ordering on a turn, and it is ADR-0253 §9's ordering with one step added.**
> On every `PlannerOutput` a planner returns, `orchestration` (a) records this call's
> `understanding`, if any, minting its element ids; (b) records this call's `actions`, minting an
> `id` for each and resolving its `serves` (§3); (c) stamps ADR-0249 §8's `targets_revision`; and
> (d) resolves each `StepCondition.about`, each `PlanInterpretation.settles` and each
> `PlanStep.intended_action` (§4), **before any other component observes the plan**. **A plan is
> therefore resolvable against actions the same call proposed**, which is the ordinary shape of
> *"book two rooms"* on the turn the user says it and not an exotic one — ADR-0253 §9's own
> argument for ordering its substitution after its recording, applied to a second minted record.

> **Normative — a model may propose a new intended action only from the interpretation's own
> elements, and never from a plan's convenience.** A `ProposedAction` is warranted where the
> user's words require an act the goal does not already hold an action for; **"book two identical
> rooms" mints two because the user asked for two**, and a planner that splits one intended act
> across two steps for its own reasons mints none. This is ADR-0249 §7's asymmetry observed rather
> than extended — interpretation is the model's — and §6's obligation is what keeps a wrong
> proposal from becoming an unauthorised effect: **a wrongly minted action costs a duplicate claim
> that stalls, never a duplicate dispatch**, because the effect claim is still taken and still
> compares the call's own key.

**Minting from the user's words rather than from the plan is what makes the two-rooms case a fact
about the request instead of a property of a plan nobody reviewed.** A count derived from the plan
would move whenever the planner re-planned, so the second room would exist on one turn and not the
next, and the record of what the user asked for would be a record of what a model most recently
produced. #2255's own framing is that the goal is what outlives a turn; the count of acts the user
asked for belongs on the goal for the same reason the understanding does.

### 3. `serves` links, and never identifies: a stale link withdraws nothing

> **Normative — `serves` is provenance and is not the identity.** It names, by
> `GoalElement.id`, the elements the intended action was minted to serve. **No lane derives an
> intended action from `serves`, compares two intended actions by their `serves`, gates a dispatch
> on a `serves` entry, re-mints an action because a `serves` entry changed, or withdraws one
> because every entry did.** The owner's sentence is the rule: *"Linking actions to goal elements
> is useful, but that relationship alone does not establish action identity."*

> **Normative — the resolution is ADR-0249 §7's and ADR-0253 §9's, unchanged.** Each entry of a
> `ProposedAction.serves` is a `C`, `S` or `D` label of the sequence in force on that call —
> ADR-0253 §9's rule decides which, and this decision states no second rule — and `orchestration`
> replaces it with the `GoalElement.id` that label resolves to, by the correspondence the loop
> itself holds. **No identifier crosses the seam in either direction.**

> **Normative — a `serves` label that resolves to nothing is dropped, and the action is recorded
> anyway.** An ordinal outside the range, a value that is not such a label, a label naming an
> element ADR-0249 §7 dropped, and a label naming an element carrying no `id` each resolve to
> nothing and are omitted from the recorded tuple. An action **all** of whose labels drop is
> recorded with an empty `serves` and is a well-formed intended action. **This is not the refusal
> §4 takes for a step's action label**, and the asymmetry is exact: `serves` gates nothing, so
> losing an entry costs legibility; a step's action label scopes an effect claim, so losing one
> would cost a dispatch nothing could recognise.

> **Normative — a `serves` entry naming an element not in the current revision is stale, truthful
> and harmless.** ADR-0253 §7 mints a **new** id for a restated element, so a rewording leaves the
> action naming the element it was minted against. **The entry is not rewritten, not recomputed,
> not dropped and not refreshed**, the action stays live and is rendered on the brief exactly as
> before, and **no mechanism reads the staleness at all**. A goal whose every element has been
> restated holds intended actions whose `serves` names no current element, and that goal is
> conforming.

**This is the whole of the owner's rewording requirement, and it is bought by not building the
thing that would break it.** A duplicate booking after a rewording needs a mechanism that treats a
reworded element as a *new* act; since nothing here derives an act from an element, no rewording
and no split can produce one. What a split actually produces is one element becoming two, each
minted a new id, with the intended action unchanged and still naming the id the first one had —
which the arms in §10 demonstrate rather than assert.

**Refreshing the link was considered and is refused because there is no mechanism to refresh it
with.** ADR-0249 §7's `retains` label is a declared correspondence between a retained element and
its predecessor; a **restatement** declares no correspondence at all — that section rules
restating is *"stating a different proposition"* — so a refresh would have to ask a model each turn
which old element each new one replaces, and re-point a durable record on the answer. That is a
model silently re-scoping an act's provenance, which is the direction ADR-0249 §7's asymmetry
refuses, and it would be bought to keep a field nothing reads accurate.

### 4. Selection, never invention: the `A` label space and `PlanStep.intended_action`

> **Normative.** `core/types.py` gains **`BriefAction`**, a frozen model with `extra="forbid"`
> carrying exactly `intent` (`NonBlankEncodableText`) and `serves` (a possibly-empty
> `tuple[EncodableText, ...]`), and `GoalBrief` gains **`actions`**, a possibly-empty
> `tuple[BriefAction, ...]` holding one entry per member of `Goal.intended_actions` in that
> tuple's own order. **A `BriefAction.serves` carries `C`/`S`/`D` **labels** of the current
> revision and never an identifier**: an entry whose element is not in the current revision (§3)
> is **omitted from the rendering**, so the brief shows the link where it is still true and shows
> nothing where it is not.

> **Normative.** **The label of the action at 1-based index *n* of `GoalBrief.actions` is the
> ASCII string `A` followed by *n* in decimal with no padding.** That is the whole of the scheme,
> it is the same on both sides of the seam, both sides derive it from the value they hold and
> neither consults the other, and **no label survives the call that rendered it and none is
> persisted as a reference.** It is ADR-0226 §3's scheme applied to one more sequence, and **`A`
> is not `M`, `F`, `C`, `S`, `D`, `E` or `G`** — the seven letters this corpus has already spent, so
> no lane spells this space with one of them and no later lane spells another space `A`.

> **Normative — the brief renders the action's `intent` and its live links and nothing else.** It
> carries **no `IntendedAction.id`**, no effect, no execution, no step, no outcome and no
> indication of whether the action has already been performed. ADR-0249 §9's containment argument
> binds this field as it binds every other — *"there is none on the value to disclose"* — and
> **ADR-0255 §12's booking of whether an attempt's executions are projected into the planner's
> input is untouched**: this decision projects none.

> **Normative.** `PlanStep` gains **`intended_action`**, an `Identifier | None` defaulting to
> `None`. The planner's step object gains one optional key, `action`, carrying an **`A` label**;
> **the loop resolves it once**, in §2's step (d), replacing the label with the `IntendedAction.id`
> it names, under ADR-0253 §9's identical discipline — taken by the loop, taken once, immediately
> on return, in place of whatever came back. **A planner mints no action here and names no
> identifier**: a step selects from the supply the brief rendered, or names none.

> **Normative — an action label that resolves to nothing refuses the plan.** An ordinal outside
> the range, a value that is not such a label, and a label naming an action carrying no `id` each
> resolve to nothing; the loop **refuses the plan** with the `PlanningError` class
> `PlanStore.save_plan` raises, it is not passed to `save_plan`, no step of it is dispatched and no
> interpretation of it is performed. **No lane drops the field instead**, because a step whose
> action was dropped is a step whose effect claim would be scoped to nothing — the fail-open
> direction, and the one ADR-0253 §9 refuses for a dropped condition for the same reason.

> **Normative — the window is closed at the store as well as at the loop.** `PlanStore.save_plan`
> **refuses a plan any of whose `PlanStep.intended_action` values is not the `id` of a member of
> `Goal.intended_actions` of the plan's own goal**, with the same error class ADR-0253 §9 gives an
> unresolvable condition label and for the same reason: the unresolved state exists only between
> the planner's return and the loop's substitution, and a window is closed at the store rather
> than trusted to close itself. This is a **strengthening of an existing member** rather than a new
> one, on ADR-0249 §12's own classification of `commit_transition`'s added claim condition.

> **Normative — a step naming no intended action is held to nothing by this decision**, and
> **whether an effect-bearing dispatch must name one is decided where the effect claim is taken**
> (§6). A read step, a composition step and every step of every plan written before this decision
> carry `None`, and that is a conforming plan rather than a degraded one.

**One label space and not two, and the reason is that an intended action is a goal-level record
rather than a per-revision one.** A condition label indexes *"the sequence that describes the
revision the plan will target"* (ADR-0253 §9), and needs the two-case rule because a revision may
be proposed on the same call. `Goal.intended_actions` is not revised: it is appended to, and §2's
ordering records this call's actions **before** the plan's labels are resolved, so the brief's
`actions` tuple plus this call's own proposals is one sequence with one indexing. The action label
indexes `GoalBrief.actions` extended by this call's `PlannerOutput.actions` in order, and that is
the whole of it.

### 5. `PlanStore` gains one member, and the wire, the export and the stored shapes

> **Normative.** `PlanStore` gains **one** member, and this is a **BREAKING** contract change
> under golden rule 5: **`record_intended_actions(minting: IntendedActionMinting) -> Goal`** —
> appends one or more `IntendedAction`s to the named goal's `intended_actions`, advances
> `version`, and returns the stored goal. `core/types.py` gains **`IntendedActionMinting`**, a
> frozen command carrying exactly `goal_id`, `actions` (a **non-empty** `tuple[IntendedAction,
> ...]`) and the `expected_version` it was computed against.

> **Normative — the write is compare-and-swap and the store takes a command, not a snapshot.**
> ADR-0014 §5's discipline binds unchanged and ADR-0249 §12's statement of it is adopted whole:
> the member succeeds only where the stored `Goal.version` still equals `expected_version`, a
> stale write raises the `PlanningError` class `StaleExecutionError` occupies for executions, and
> **the read, the comparison and the write are one indivisible step** with no separate read on
> which a decision is taken. **Two actions minted on one turn are appended in one call**, so the
> two-rooms case takes one compare-and-swap and not two.

> **Normative — the member refuses an id the goal already holds**, with the same error class, and
> writes nothing. §1's append-only rule is closed at the store rather than trusted to close
> itself, on §4's own footing.

> **Normative — `PlanExport` gains no member and `schema_version` moves for the record's shape
> alone.** `IntendedAction` rides **inside `Goal`**, which `PlanExport.goals` already carries, so
> ADR-0014 §5's closure rule — *"every `goal_id`/`plan_id` referenced by an included record
> resolves within the same export"* — is satisfied by construction and is **extended by nothing**.
> `schema_version` moves on ADR-0039 §10's own mechanism, because `Goal` is inside the export and
> its shape changing is exactly what the version exists to announce.

> **Normative — `delete_goal`'s cascade reaches the actions because they are inside the goal**,
> and ADR-0014 §5's *"a goal the user deletes must not leave its plan history behind"* needs no
> extension: deleting the goal row deletes them. Its live-step refusal is unchanged and an
> intended action is not a reason to refuse a deletion.

> **Normative — no new Protocol is created**, so no new conformance suite and no new canonical
> fake is owed. The existing `PlanStore` and `Planner` conformance suites, `InMemoryPlanStore` and
> the canonical fakes in `ai_assistant.testing` each gain the new obligations **in the same change
> that adds them** (`CONTRIBUTING.md` → "Adding a Protocol").

> **Normative — `PROTOCOL_VERSION` moves by exactly one, in the lane that lands the `core`
> surface**, and `wire/envelope.py`'s log gains an entry naming this ADR and the reason. `Goal`
> gains a field and `PlanStep` gains a field; `Goal` is carried on `TurnResult.goal`, `PlanStep`
> inside `ActionPlan`, both set `extra="forbid"`, and `wire/codec.py` renders a model by
> `model_dump()` — so each on its own makes a hub's turn undecodable by a client at the previous
> version. §9 cuts the lanes so that **exactly one** lane is that ground.

> **Normative — every stored row stays readable, and the migration is an addition with a total
> default.** A `Goal` written before this decision decodes with `intended_actions` empty and a
> `PlanStep` with `intended_action` absent, which §4's last clause already makes a conforming
> plan. **No lane invents an intended action for a stored goal**: an act nothing declared is an
> act no claim was ever scoped to, and minting one would state a history the row does not hold.

### 6. What this identity obliges of an at-most-once effect claim

> **Normative — an at-most-once effect claim is scoped to the intended action and never to the
> goal alone.** A decision that records a goal's completed effects keys its row on the
> **`(goal, intended action, effect key)`** triple, not on the pair. **No lane scopes such a claim
> to a goal and an argument key alone**, and a decision that does has reintroduced the two-rooms
> defect §10's arm 1 exhibits.

> **Normative — a completed effect under this intended action carrying a different key is a
> distinguishable state, and it is not a fresh claim.** Where the goal holds a completed effect
> claimed under **this** intended action whose key is **not** this call's key, the answer is
> neither *claimed* nor *completed*: **the step is not dispatched**, and the work returns to
> investigation — modify-before-replace, which A8's second ADR owns. **A decision that lands the
> claim owes an answer for this state**, and until one exists §7's gate is what keeps the interval
> safe.

> **Normative — the effect record names the interpretation revision the claiming plan targeted.**
> A decision that records a completed effect carries on that record the `targets_revision`
> (ADR-0249 §8) of the plan the claim was taken under, so that *"the understanding moved since
> this act"* is a mechanical fact a later turn reads rather than a judgement it makes. **It is not
> a second identity**: it is compared by no clause of this decision and scopes no claim.

> **Normative — key equality, the goal's evidence and the step's `verifies` are necessary for
> reuse and are not sufficient, and what they do not check is named.** ADR-0252 §6's four tests are
> about **the goal's evidence** — whether a proposition is supported, by a row standing, covering
> and recent enough — and ADR-0253 §4's `verifies` is *"a predicate over this step's **own
> output**"* and in terms *"never verification against the goal's criteria"*. **Neither asks
> whether the completed act satisfies the current interpretation**, which is verification against
> the criteria and is **A10's by name**. So the three conditions bound reuse and do not establish
> it, and **no lane reads them as establishing it**.

> **Normative — this decision takes no effect claim, computes no key, and refuses no dispatch.**
> It mints an identity and states what a claim owes it. **No lane cites this section as authority
> for dispatching a step, for refusing one, for writing a `GoalStatus`, or for reading an effect
> row.**

**Stating the obligation rather than the mechanism is what the ordering requires, and it is golden
rule 5's ordinary shape.** The claim's own contract is not on the tree: the decision that lands it
is not merged, so this document cannot add a member to its vocabulary or a field to its row without
deciding that ADR's surface from outside it. What it can do is fix the identity that decision keys
on, which is the thing that has to exist first — and that is why this is its own ADR rather than a
limb of the other one.

**And the interval is safe for the reason ADR-0253 §3 and ADR-0255 §13 already state.** *"No
consequential capability is wired into a production deployment until the verification,
uncertain-outcome and cancellation guarantees for its class are implemented and demonstrated"*, so
the window in which the second clause's answer does not yet exist is a window with no real
consequential integration in it. A normative requirement a lane cannot yet satisfy is not a
contradiction where the acts it governs cannot yet be performed.

### 7. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling.

- **At-most-once itself** — the effect key, the claim, its vocabulary and where it is taken. The
  reconciliation decision's, which this identity is a prerequisite of. **Fired by that ADR.**
- **The answer a claim gives for §6's second clause**, and the member or shape that carries it.
  **The same decision's**, on golden rule 5's ordering. **Fired by that ADR.**
- **Retry, and modify-before-replace** — investigating a change to an existing booking rather than
  replacing it. **A8's second ADR.** This decision establishes *which act* a step is an attempt
  at; that one decides *what to do about one that already happened*. **Fired by that ADR.**
- **Verification against the goal's criteria** — whether a completed act satisfies the current
  request. **A10**, exactly as ADR-0255 §12 books it, and §6's fourth clause is the operand it
  inherits. **Fired by A10 landing.**
- **Withdrawing, cancelling or completing an intended action** — and therefore any standing field
  on the record. **Not decided** (§1). **Fired by A9's cancellation semantics, or by a measured
  case in which a live-but-unnamed action causes a wrong act** — which §1's
  never-an-instruction-to-act clause is what makes hard to reach.
- **Two goals sharing one intended action.** **Not decided.** The record lives inside a `Goal` and
  no clause admits a cross-goal reference; a second goal that means the same act mints its own.
  **Fired by a decision that states what a shared act's deletion, export and permission trail
  mean**, which ADR-0004's per-goal export and deletion rights make the hard half.
- **Merging two intended actions into one**, or splitting one into two after minting. **Not
  decided**, and §1's append-only rule forbids both today. **Fired by a measured case in which a
  user's revision genuinely joins two acts** — the falsifier the Consequences book.
- **Whether a side-effecting step must name an intended action, and what refuses one that does
  not.** **Not decided here** (§4), and §6 puts it where `side_effecting` is known. **Fired by the
  decision that lands the effect claim.**
- **Where a live correction would enter** — a message reaching a turn that is already running,
  mid-run interruption, and message queuing. **Not decided**, on the owner's sequencing ruling of
  2026-09-13: every correction this decision is stated under arrives as a subsequent turn, and
  §2's minting is reached only on a `PlannerOutput` a completed call returned. Were a live
  correction admitted, it would enter at exactly one place — **between a planner's return and
  §2's recording of its `actions`** — because that is the only interval in which a proposed act
  has been stated and not yet minted. **Fired by the follow-up that takes live steering.**

### 8. Records owed on earlier ADRs, under ADR-0082 §1

**ADR-0249 — partially superseded in three scopes, stated on this document's header.** §1's `Goal`
declaration: a reader holding only §1 authors a goal with no place for an act, and §6's obligation
has no operand — ADR-0070 §1's test on the supersession side and **partial** in §3's sense. §7's
`PlannerOutput`: *"carrying exactly two fields"* becomes false, and a reader building the two-field
model builds a seam across which no action can be proposed. §9's `GoalBrief`: *"whose fields are
exactly"* becomes false, and its label scheme *"applied to three sequences"* is applied to a
fourth. **Everything else of ADR-0249 binds entire and is what this decision reasons from** — §7's
retention clause is the mechanism §3 relies on, §7's asymmetry is §2's ground, §8's
`targets_revision` is §6's third clause's operand, and §9's containment argument is §4's.

**ADR-0253 — partially superseded in one scope, in two counts of §9.** *"There are exactly three
spaces"* becomes four and the four-field clause becomes five. A reader holding only §9 builds a
loop that resolves no action label, and therefore a plan that cannot name the act its step
attempts. **§7 is relied on and superseded in nothing**, and it is the section this decision is
built on: its element-id minting rule is what makes a retained element's id survive a revision, its
restatement rule is what makes a **derived** identity unusable, and its `D`-label disjointness is
the construction §1 reuses for `A`.

**ADR-0255 §7 — its obligation is unchanged and its named absence is filled in one half.** That
section's *"a goal records no completed effect that a driver could compare against"* stays true:
this decision records no effect. What it lands is the missing **identity** that section says a
comparison would otherwise have to invent — *"A driver that compared capability and parameters
would be inventing an identity nobody declared"* — so §7's refusal is **honoured rather than
lifted**, and §12's booking of an executions projection into the planner's input is untouched
(§4). **No supersession is owed**: every sentence of §7 stays true, joined by an obligation stated
elsewhere, which ADR-0082 §1 calls a stacked addition.

**ADR-0014 §5 — extended by nothing and superseded in nothing.** The record rides inside `Goal`,
which the export already carries, so the closure rule is satisfied by construction and `PlanExport`
gains no member; §5's compare-and-swap discipline, its commands-not-snapshots rule and its deletion
obligation are each adopted whole by §5 of this decision.

**ADR-0249 §12, ADR-0250 §9 and ADR-0252 §12 — relied on and not superseded.** Each widened
`PlanStore` and none of them enumerates the Protocol's members as closed, so adding one member
contradicts no sentence any of them wrote and is a **stacked addition** recorded here and nowhere
else (ADR-0082 §1). ADR-0252 §12's `GoalRevision` widening is the precedent §5 declines to reuse,
and §2 states why.

**ADR-0226, ADR-0228 and ADR-0230 — relied on and not superseded.** ADR-0226 §3's label scheme is
applied to one more sequence without alteration; ADR-0228 §8's namer rule binds every field this
decision adds, and §5's authored-at-the-seam discipline is what §4's substitution observes.
ADR-0230 §4's *"a property of the types rather than a rule a planner is trusted to keep"* is the
ground `BriefAction` carries no identifier on.

**ADR-0089 §2 — this ADR is marked**, and every obligation it imposes is inside a mark. Unmarked
text states what a marked clause means and supplies no obligation (§3).

### 9. The lane cut, and the one lane that moves the wire

> **Normative.** This decision is implemented in **two lanes**, in this order, each one subsystem
> plus its tests, and **no lane of this decision wires a consequential capability** or enables
> anything in a production deployment.

- **L1 — the contract and the store.** `core/types.py`'s `IntendedAction`, `ProposedAction`,
  `BriefAction` and `IntendedActionMinting`; `Goal.intended_actions`, `PlannerOutput.actions`,
  `GoalBrief.actions` and `PlanStep.intended_action`; `core/protocols.py`'s
  `record_intended_actions` and `save_plan`'s added conjunct; `planning`'s `PlanStore`
  implementation with its schema migration and export, the shared conformance suite for the new
  member and the added conjunct, and the canonical fake in `ai_assistant.testing`. **L1 moves
  `PROTOCOL_VERSION`** (§5). Arms 1, 5, 6, 7.
- **L2 — the loop.** `orchestration`'s recording of `PlannerOutput.actions` in §2's order, the
  `serves` resolution and its drops (§3), the brief's `actions` projection and its live-link
  rendering, `planning/planner.py`'s `A`-labelled block and its prompt, and the loop's resolution
  and refusal of a step's action label (§4). Arms 2, 3, 4, 8.

> **Normative — L1 lands before L2**, and no arm of L2 is demonstrated against L1's absence.
> **Neither lane implements an effect claim, a reuse check or a retry** (§7), and a lane that
> finds itself needing one has left its fence.

### 10. The arms this decision owes

The two lanes ship these eight, over controlled fakes, and the owner's two cases are arms 1 and 2.

Every arm states its correction as a **subsequent turn**, on the owner's sequencing ruling; none
drives a message into a running turn.

1. **Two identical rooms are two intended actions on one goal**, and *"an earlier booking must not
   count as fulfilling 'book another one'"*. A goal whose request is *"book
   two identical rooms"*; the planner returns two `ProposedAction`s and a plan whose two steps
   carry the **same** capability and byte-identical `parameters` and name `A1` and `A2`. Assert:
   two `IntendedAction`s are recorded with **distinct** ids; both steps resolve; and the triple
   §6's first clause requires is **distinct for the two steps** while the argument key is equal —
   which is the fact an at-most-once claim scoped to the goal alone cannot see.
2. **"Change our booking to Sunday" mints no second action.** From arm 1's goal at a revision
   whose element reads Saturday, record a revision restating it Sunday. Assert: the element's `id`
   is **new** (ADR-0253 §7); `Goal.intended_actions` is **byte-identical** before and after; the
   action's `serves` still names the **old** element id and is unchanged; the brief renders the
   action with its `serves` **empty**, because the element it names is not in the current
   revision; and the action resolves from an `A` label on the next plan exactly as before.
3. **A split element leaves the identity alone.** Replace one element with two that between them
   say what it said. Assert: two new element ids, `intended_actions` unchanged, and `serves`
   naming neither of the two new ids — and that no clause of the implementation reads that as a
   reason to mint, withdraw or re-point anything.
4. **Selection and refusal at the seam.** A plan naming `A1` where the goal holds one action
   resolves to that action's id; a plan naming `A2` where it holds one, a plan naming `A0`, and a
   plan naming `banana` are each **refused** with the `PlanningError` class `save_plan` raises,
   are not passed to `save_plan`, and dispatch nothing. A plan whose step names no action is saved
   and carries `None`.
5. **The store closes the window and the append is atomic.** `save_plan` refuses a plan whose
   `intended_action` is not a member of that goal's `intended_actions`; `record_intended_actions`
   refuses a stale `expected_version`, refuses an `id` the goal already holds, and appends **two**
   actions in one compare-and-swap. Each refusal writes nothing.
6. **The record round-trips and the export closes.** A goal carrying two intended actions
   round-trips through `model_dump()` and construction; `PlanExport` carries them inside `goals`
   with no new member; `delete_goal` removes them with the goal; and a stored goal written before
   this decision decodes with `intended_actions` empty.
7. **The two disjointness refusals.** An `IntendedAction` whose `id` is `A1` is not constructible;
   an `IntendedActionMinting` carrying an empty `actions` is not constructible; and a
   `ProposedAction` carrying no `intent` is not constructible.
8. **The seam discloses no identifier and no history.** Over a goal with two intended actions, one
   already performed in an earlier turn's execution, assert that the rendered request contains
   **no** `IntendedAction.id`, no execution, no step and no outcome — and that the `A` block
   carries the intents and the live `C`/`S`/`D` labels alone.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

A **new decision** that partially supersedes ADR-0249 in three scopes and ADR-0253 in one, each
named on the header and shown in §8. **Against every other ADR it cites, without exception, it is
a stacked addition** — no sentence of any of them becomes false or over-wide, and each is joined
by an obligation stated here; §8 shows the working for the ones a reader would expect to be
superseded, ADR-0014, ADR-0226, ADR-0228, ADR-0230, ADR-0249 §12, ADR-0250, ADR-0252 and ADR-0255
among them. It is **marked** under ADR-0089, and every obligation it imposes is inside a mark.

## Consequences

**What becomes possible.** A goal can say *how many acts it intends* and a step can say *which one
it is attempting*, so the two failures §-Context names come apart: two identical rooms are two
records and dispatch twice, and a changed date is one record with a completed effect under it,
which a claim can recognise as *this act already happened, differently*. ADR-0255 §7's honest
absence — *"a goal records no completed effect that a driver could compare against"* — is halved:
the comparison now has a subject, and the decision that records the effect supplies the predicate.

**What becomes harder.** A planner must say what it intends before it may act on it, which is one
more thing a model can get wrong; §2's mitigation is that a wrong proposal costs a stalled claim
and never a duplicate dispatch. And the corpus gains an eighth label space, which is a seam a
reader must now hold eight letters for.

**This identity is a candidate, and these are the cases that would falsify it.** The owner asked
that goal-element scoping be treated as a candidate to test. What is on trial is *a goal-scoped,
minted, element-linked record*, and each of the following would show it is the wrong unit. Each is
booked in §7.

- **A merged element.** A revision that genuinely joins two acts into one — *"actually, just book
  us one room for both of us"* — leaves two live intended actions where the user now intends one.
  Nothing here merges them and nothing withdraws one, so a later plan could name either. **What
  fires it: a measured case in which a user's revision joins two acts.** The cheap repair is a
  withdrawal; the expensive one is that an act's identity is per-revision after all, and the
  candidate is wrong.
- **A cancelled intent.** *"Cancel the second room"* leaves a live action whose effect has already
  been claimed. §1's never-an-instruction-to-act clause makes that harmless to the driver and does
  not make it truthful to a reader. **What fires it: A9's cancellation semantics.**
- **Two goals sharing one act.** One booking that satisfies elements of two goals is expressible
  today only as two actions, one per goal, which two claims would dispatch twice. **What fires it:
  a decision that states what a shared act's deletion, export and permission trail mean** — and
  ADR-0004's per-goal deletion right is what makes that the hard half rather than the obvious one.
- **An act the user never described.** An intended action is minted from the interpretation's
  elements (§2); an act the system must take to reach the outcome but which the user never named —
  a required deposit, a confirmation call — has no element to be minted from. If such acts are
  common, minting from the user's words is too narrow a rule. **What fires it: a measured case in
  which a needed act has no warrant in the user's words.**
- **A step that is half an act.** Two steps that together perform one effect — book, then confirm
  — both name one intended action, and a claim scoped to the triple would let the second reuse the
  first's completed effect. §6's fourth clause says the three reuse conditions do not establish
  satisfaction; A10 is what would catch it. **What fires it: A10 landing, or a measured
  two-step-one-effect case before it.**

## Alternatives considered

**Derive the identity from the goal's elements.** Rejected on the owner's own sentence and on
ADR-0253 §7: a restated element is minted a new id, so a rewording would re-mint the act and
permit exactly the duplicate booking the requirement forbids. The link survives as `serves`, which
§3 makes provenance and forbids every mechanism from reading.

**Carry the identity on the interpretation.** Rejected because ADR-0249 §7 makes a revision *"a
complete statement of an understanding"* and omission removal — so an act would be deleted by a
turn that failed to mention it, which is the opposite of durable. `Goal.intended_actions` is a
second append-only sequence beside the revisions, and nothing removes from it.

**Ride the minting on `GoalRevision`, atomically with the revision.** ADR-0252 §12 does exactly
this for `invalidates`, and it was the first shape drafted. Rejected because it ties minting to
revising: a turn that acts on an understanding it does not change could then mint nothing, and a
turn that minted would have to restate every element to avoid removing one. One store member with
its own compare-and-swap costs less than that coupling.

**Give the record a capability, so a claim could compare it.** Rejected on ADR-0255 §7 in terms —
*"A driver that compared capability and parameters would be inventing an identity nobody
declared"* — and on ADR-0253 §8's observation that a re-plan's spellings are not durable
declarations. The record carries prose no mechanism compares and an id every mechanism does.

**Refresh `serves` on every revision.** Rejected: ADR-0249 §7 gives a declared correspondence for a
**retained** element and none for a restated one, so a refresh would ask a model each turn which
old element each new one replaces and re-point a durable record on the answer — a model silently
re-scoping an act's provenance, to keep accurate a field §3 forbids anything from reading.

**Render the action's effect status on the brief, so the planner can avoid re-planning an act.**
Rejected here: ADR-0255 §12 books *"whether an attempt's executions are projected into the
planner's input"* as an open question and calls such a projection *"an aid rather than the
guarantee"*. This decision lands the identity the guarantee needs and leaves that booking exactly
where it found it.
