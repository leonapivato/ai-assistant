# 269. A `serves` link is checked against every revision the goal holds, not the one current at the append

- Status: Accepted
- Date: 2026-09-15
- **Partially supersedes** [ADR-0265](0265-an-intended-action-has-a-stable-identity-minted-once-and-linked-to-the-goal-elements-it-serves.md)
  — **one scope, and it is one refusal conjunct of §5, stated there and once more as an arm.
  §5's third conjunct**: *"refuses a `serves` value that is not the `id` of an element of the
  goal's **current** interpretation at the instant of the append"* becomes a membership test over
  **every revision the goal holds at that instant**, so a link §3 already calls *"stale, truthful
  and harmless"* is admitted where it was refused, and the conjunct keeps the whole of its job —
  refusing *"a dangling or foreign identifier"*. A reader holding only §5 builds a store that
  refuses the minting of every turn that opens a goal and then restates the element it minted
  against, which is ADR-0070 §1's test on the supersession side and **partial** in its §3 sense.
  **And §10 arm 5's `serves`-refusal limb**, *"a `serves` value naming an identifier of **no**
  element of the goal's current interpretation"*, which states the same rule as an arm and
  narrows with it to an identifier of no element of **any** revision the goal holds. That one
  conjunct, and nothing else in this ADR: §5's refusal of an `id` the goal already holds, its
  `MAX_INTENDED_ACTIONS` refusal, its **all-or-nothing** rule, its error-class rule and its
  compare-and-swap discipline all bind entire; arm 5's other-goal limb, its two-action shape, its
  byte-for-byte assertions and its error-class assertion bind entire; §1's append-only rule, its
  bound, its opening-write clause and its `A`-disjointness are relied on and are what make the
  state forced; §2's minting rule, its per-call ordering and its all-or-nothing bound bind
  entire and are **relied on**; **§3 binds entire** and is the ground this narrowing is taken on;
  §4's label space and its step-label refusal are untouched, and the asymmetry §3 draws between
  them is preserved; and §§6-11 stand entire.

## Context

### Where this comes from

The adversarial round on PR #2411 — ADR-0265's L2, the loop — found a turn on which no
conforming `orchestration` can persist what it correctly computed. It was verified against the
texts, **waived on that PR with #2414 as its record** because the defect is in the contracts
rather than in that lane's code, and pinned there as a test,
`test_an_opening_turn_that_mints_then_restates_is_refused_at_the_append`, so that the state is
explicit rather than rediscovered. #2414 names two directions and leaves both to an ADR, *"a
decision about ADR-0265's or ADR-0249's own surface"*. This is that decision, and it takes the
first.

### The state, quoted rather than re-derived

A turn that **opens** a goal, makes **two** planner calls, mints an intended action on call 1
whose `serves` names an element call 1 proposed, and whose call 2 records a revision that does
not retain that element fails at persistence with a `PlanningError`, leaving the goal row
written and no plan and no attempt. Four ratified clauses meet, and #2414's own enumeration is
the argument:

- **ADR-0265 §2** resolves each `ProposedAction.serves` against *"the sequence in force on that
  call"* and orders a turn's writes so that `orchestration` *"(a) records this call's
  `understanding`, if any, minting its element ids; (b) records this call's `actions`"*.
- **ADR-0265 §3** then makes the resulting link, once a later revision moves past it, *"stale,
  truthful and harmless"* — *"not rewritten, not recomputed, not dropped and not refreshed"*,
  with *"no mechanism reads the staleness at all"*.
- **ADR-0249 §11** defers every write to one persistence site at the end of the turn — *"no lane
  adds a second persistence site"* — and **§12** makes `save_goal` *"the opening write alone"*,
  carrying the goal's whole interpretation chain in one call. ADR-0228 §5 is absolute in the
  same direction: the loop holds no `PlanStore`.
- **ADR-0265 §1** rules that *"**The goal's opening write mints none**"* and §2 that *"The only
  route to a new `IntendedAction` is a `ProposedAction` recorded by the member §5 adds"*, so on
  an opening turn the minting **must** be a second write, after the whole chain is stored.
- **ADR-0265 §5** then refuses that write, because its conjunct reads the *current*
  interpretation and by then the current revision is call 2's.

ADR-0265 §5's justification is what the opening route falsifies: *"The `serves` conjunct is checkable
exactly once, and that instant is the only one at which it is true by construction. §2's
ordering records this call's revision **before** its actions"*. That holds on a goal the store
already holds, where revisions reach the store one at a time through `record_interpretation` and
the two kinds of write interleave in the order the turn made them. It does not hold on the
opening route, where one call writes the chain entire and every minting of the turn follows it.

### Reach, and why it is still worth deciding now

The state is **unreachable in production until ADR-0265's L3 lands**: `PlannerOutput.actions` is
filled by the planning seam, which is L3's, so every envelope today carries `actions=()` and no
minting exists. The failure is **fail-closed** — nothing recorded, no plan saved, no step
dispatched. It is decided now because L3 is the next lane of that decision and would land the
producer on top of a store that refuses its first opening turn.

### What this ADR is not allowed to settle

It settles the reading of one conjunct. It decides nothing else about ADR-0265, nothing about
at-most-once effect claims, nothing about the planning seam, and nothing about what a turn tells
the user (§6).

## Decision

### 1. The conjunct is a membership test over every revision the goal holds

> **Normative — ADR-0265 §5's third refusal conjunct becomes goal-wide, and this is a BREAKING
> contract change under golden rule 5.** `record_intended_actions` refuses a `serves` value that
> is not the `id` of an element of **any revision the goal's `interpretation` holds at the
> instant of the append** — the current revision and every earlier one it still holds alike —
> and writes nothing. **An implementation that keeps the current-instant refusal is
> non-conforming**, which is what makes it breaking: no member is added and no signature moves,
> and a behaviour a caller may rely on does. The refusal keeps ADR-0265 §5's error class, keeps
> its all-or-nothing rule, and stays an **invariant breach at the current version** rather than a
> lost race.

> **Normative — the test reads what the goal holds, and an elided revision is not held.** An
> `id` whose only revision ADR-0249 §2 has elided resolves to nothing and is refused, exactly as
> a fabricated one is. No lane reconstructs an elided revision, keeps a side index of dropped
> element ids, or reads `Goal.interpretation_elided` to soften the refusal.

> **Normative — the test is strictly wider, so nothing that was admitted is now refused.** Every
> `serves` value ADR-0265 §5's reading accepted is an element of the goal's current revision and
> therefore of a revision the goal holds. **No stored goal becomes non-conforming, no stored
> `IntendedAction` is re-checked, and no migration is owed.**

> **Normative — the conjunct is still taken exactly once, at the append, and never again.**
> ADR-0265 §3 binds entire: a recorded `serves` entry is *"not rewritten, not recomputed, not
> dropped and not refreshed"*, and **no lane re-runs this test over a stored action**, at read
> time, at projection time, at dispatch or on a later revision.

**What the conjunct refuses is unchanged in kind, and the first clause is the whole of it.** An
identifier of no element of this goal — a fabricated value, an element of a **different** goal,
an element of a revision this goal has elided — is an identifier of no revision the goal holds,
so each is refused, which is the whole of *"a caller reaching past `orchestration` with a
dangling or foreign identifier"*. What the conjunct stops refusing is an identifier of **this
goal's own earlier reading of itself**, which ADR-0265 §3 already rules is a legitimate record.

**The conjunct's job survives whole, and that is the test that decides the direction.** ADR-0265
§5 states what the check is for — a dangling or foreign identifier — and ADR-0265 §3 states, in
terms, that an identifier of a superseded element is neither. The current-instant reading was
chosen because it was *"checkable exactly once"*, and a goal-wide membership test is checkable
exactly once at the same instant; what it gives up is the property that every admitted link is
live at the append, and ADR-0265 §3 already gives that property up one moment later and says
so.

**The elision edge is named because the word "holds" is load-bearing, and the refusal is right
whichever way the figures go.** `orchestration` resolves a `ProposedAction.serves` label against
the sequence in force on that call (ADR-0265 §3), which is a revision **this same turn wrote**,
and ADR-0249 §2 elides the **oldest** revision on the write that would exceed its bound. So the
revision a minting was computed against is elided under it only where that one turn wrote
`MAX_GOAL_INTERPRETATIONS` further revisions after it — a turn writing one per planner call,
under an allowance ADR-0251 §4 admits a further call against. **This decision states no figure
and depends on none**, because the two branches agree: while a turn's calls stay under that
bound the case is unreachable from the seam, and where they do not, the goal genuinely no longer
holds the element and the refusal is the truthful answer. What the conjunct exists for — a
caller reaching past the loop — is reached either way.

### 2. The opening route stands, and the announcement is why

> **Normative — no lane resolves #2414 by moving a write.** ADR-0249 §11's single persistence
> site, §12's `save_goal`-as-the-opening-write-carrying-the-chain, ADR-0228 §5's prohibition on a
> second persistence site and ADR-0265 §1's opening write that mints none each bind **entire**.
> No lane routes an opened turn's later revisions through `record_interpretation`, splits
> `save_goal` into a chain of writes, defers the opening write past the turn's mintings, or
> reorders the site's calls to make the conjunct true at the old instant.

**Direction 2 is declined on #2414's own ground, and it is a user-visible one.** `RecordedGoal`
carries an opened turn's revisions inside the goal rather than beside it, and what a turn routes
through `record_interpretation` is exactly what ADR-0250 §5 computes `revised` from: *"It is
`True` exactly where this turn recorded a `GoalInterpretation` through
`PlanStore.record_interpretation`"*. That section then makes a reply *"carry one sentence naming
the goal it is about where, and only where, the `disposition` is `RESUMED` or `REOPENED`, or
`revised` is `True` **and** at least one of `outcome_changed`, `added` and `removed` says
something moved"* — and the #2414 case is a restatement, so something moved. Routing an opened
turn's second-call revision that way would make an `OPENED` turn announce a revision, and
announce it **only on the turns that happened to mint**, which is a persistence detail deciding
what the user is told. ADR-0250 §5's own rule for that disposition is the opposite: *"A turn
whose disposition is `OPENED` or `CONTINUED` and which moved no word says nothing about goals at
all"*.

**And the cost is asymmetric.** Direction 2 changes a write order, a durable announcement rule
and a projection; this decision changes one conjunct in one store member and the arm that pins
it, and leaves every other sentence of both decisions standing.

### 3. The lane that implements it

> **Normative — one lane, and it is ADR-0265 §9's L1 shape without the wire.** The lane lands
> `core/protocols.py`'s statement of the conjunct on `PlanStore.record_intended_actions`,
> `planning`'s `PlanStore` implementation of it, the shared conformance suite for that member,
> the canonical fake in `ai_assistant.testing`, and the four arms of §4. It is briefed after this
> decision merges, and **ADR-0265's L3 is briefed after it merges**.

> **Normative — the flip of the pinned test rides in the same lane and adds no second
> subsystem.** PR #2411's `test_an_opening_turn_that_mints_then_restates_is_refused_at_the_append`
> becomes an acceptance (§4, arm 1). It is an edit under `tests/orchestration/` alone: **no file
> under `src/ai_assistant/orchestration/` moves**, and a lane that finds itself changing the loop
> has left its fence and has misread this decision.

> **Normative — `PROTOCOL_VERSION` does not move and `wire/envelope.py`'s log gains no entry,
> and that is compatible with §1's breaking flag rather than in tension with it.** Golden rule
> 5's *breaking* is about the **contract** — an implementation of it stops conforming —
> while `PROTOCOL_VERSION` answers ADR-0124 §9's wire question, *"a change to a wire-carried
> `core` type that makes a value one peer emits invalid for the other"*. No `core` type gains,
> loses or narrows a field here and no wire-carried value changes validity: what changes is one
> store member's refusal condition, which crosses no frame.

### 4. The arms this decision owes

> **Normative.** **The lane §3 names ships the four arms below, each over controlled fakes, and
> the lane is not complete without them.** Arms 2 and 3 are asserted at the store, against the
> shared conformance suite, so that every `PlanStore` implementation and the canonical fake carry
> them. No arm is demonstrated against a live integration.

1. **The opening turn that mints and then restates now records**, which is #2414's case and PR
   #2411's pinned arm turned over. A turn opens a goal, mints on call 1 an action whose `serves`
   names an element call 1 proposed, and records on call 2 a revision that does **not** retain
   that element. Assert: the turn completes, the goal holds **one** `IntendedAction`, its
   `serves` names the **call-1** element's `id` byte for byte, the stored `interpretation`
   carries both calls' revisions, and the plan is saved. The arm keeps the shape of the test it
   replaces — the same two-call fake planner — so that what changed is the verdict and not the
   case.
2. **An element of an older still-retained revision is admitted, at the store and without the
   loop, with revisions intervening.** Over a goal the store already holds: record **three**
   further revisions after the one carrying the element, each restating it afresh so ADR-0253 §7
   mints a new `id` every time, then call `record_intended_actions` with a `serves` naming the
   element `id` of the **oldest retained** revision — **not** the current one and **not** the one
   before it. Assert: the action records, its stored `serves` names that `id` unchanged, and the
   goal's `version` advances once. The intervening revisions are the whole point of the arm: an
   implementation that searched only the current revision, or only the current and the one
   before it, would pass every other arm here and fail this one.
3. **The conjunct still refuses what it is for, all-or-nothing.** Over a **two**-action command
   whose **second** action carries the bad value, assert a refusal for each of: an identifier of
   no element of any revision the goal holds; an identifier of an element of a **different**
   goal; and an identifier whose only revision has been elided past `MAX_GOAL_INTERPRETATIONS`.
   In each case the goal's `intended_actions` and its `version` are **byte-for-byte what they
   were** — neither action recorded — and the class raised is the same non-stale `PlanningError`
   ADR-0265 §5 gives the other two refusals.
4. **Nothing else of ADR-0265 §5 moved.** Over the same store: a minting carrying an `id` the
   goal already holds is refused, a minting that would carry the goal past
   `MAX_INTENDED_ACTIONS` is refused whole, and a stale `expected_version` raises the
   **stale-write** class while the three refusals of arm 3 do not. Each writes nothing.

### 5. Records owed on earlier ADRs, under ADR-0082 §1

**ADR-0265 — partially superseded in one scope, stated on this document's header.** §5's third
refusal conjunct fails ADR-0070 §1's test on the supersession side: a reader holding only §5
builds a store that refuses a minting this decision requires it to record, and would act
differently before and after. §10 arm 5's `serves`-refusal limb is the same rule written as an
arm, so it moves with it rather than forming a second scope — a reader holding only that arm
writes a test asserting the refusal this decision forbids. **§5's unmarked paragraph** reasoning
that the conjunct *"is checkable exactly once, and that instant is the only one at which it is
true by construction"* is named for the reader's sake and is **not** a third scope: under
ADR-0089 §3 unmarked text in a marked ADR *"states what a marked clause means and supplies no
obligation"*, so it binds nothing either before or after, and §1 above states the reason the
conjunct now carries. **Everything else of ADR-0265 binds entire and is what this decision
reasons from** — ADR-0265 §3 is the ground, its §2's ordering is relied on unchanged, its §1's
opening-write clause is what makes the state forced rather than chosen, and its §4's step-label
refusal keeps the asymmetry its §3 draws against it.

**ADR-0249 §11 and §12 — relied on and superseded in nothing.** The single persistence site,
`save_goal` as the opening write carrying the chain, the compare-and-swap discipline and the
commands-not-snapshots rule each stay literally true; §2 above binds in the direction they are
stated. What moves is a refusal condition inside one member ADR-0265 added, which is not a
sentence either section wrote. ADR-0249 §2's elision is **relied on**, and §1 above reads its
bound rather than changing it.

**ADR-0228 §5 — relied on and superseded in nothing.** *"No lane adds a second persistence site,
gives `LearningLoop` a `PlanStore`, or carries a plan out of a failing turn in order to write
it"* is the clause direction 2 would have pressed against, and this decision leaves it untouched.

**ADR-0250 §5 — relied on and superseded in nothing.** Its `revised` clause, its
`EngagementDisposition` closure and its announcement rule are the grounds §2 above declines
direction 2 on. No sentence of it becomes false or over-wide: an `OPENED` turn keeps announcing nothing, and
this decision adds no engagement field and no disposition.

**ADR-0253 §7 — relied on.** Its rule that a restated element is minted a **new** id is what
creates the stale link in the first place, and §3 of ADR-0265 is built on it.

**ADR-0089 §2 — this ADR is marked**, and every obligation it imposes is inside a mark. Unmarked
text here states what a marked clause means and supplies no obligation (ADR-0089 §3).

### 6. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them.

- **Carrying the revision a minting was computed against on `IntendedActionMinting`** — #2414's
  other half of direction 1. **Not decided**, and the Alternatives say why it is not needed.
  **Fired by a case in which the goal-wide test admits a value that provably should not be
  recorded**, which would need a caller other than the loop.
- **Anything else in ADR-0265** — its L3 seam, the effect claim ADR-0265 §6 obliges, withdrawal,
  retirement, the `MAX_INTENDED_ACTIONS` exhaustion and the wrongly-minted-action residual. Each
  stays exactly where that decision left it, with the trigger it books.
- **Whether `serves` is ever refreshed, repaired or re-read** — ADR-0265 §3 rules it is not, and
  this decision relies on that rule rather than reopening it. **Fired by nothing here.**
- **What a turn tells the user about a goal it opened** — ADR-0250 §5's, entire. **Fired by that
  decision's own successors.**

## Consequences

**The opening route becomes ordinary, which is what L3 needs.** Once the planning seam fills
`PlannerOutput.actions`, the commonest first turn of a goal — the user states an objective, the
turn services a read, the second call sharpens the wording — records its intended action instead
of failing the turn. Until the lane §3 names merges, the pinned test stands as the record of the
state, and L3 is not briefed before it.

**A `serves` link admitted at the append may already be superseded**, and a reader of a stored
goal cannot tell from the record whether a link was live when it was written. That is the
property ADR-0265 §3 already established one moment later, and the cost is legibility of the
audit trail at exactly one instant. Nothing reads it: ADR-0265 §3's *"no mechanism reads the staleness at
all"* is what makes the cost bounded, and `GoalBrief` still renders only the links that are
currently true (ADR-0265 §4).

**The conjunct is weaker against a broken caller than it was.** A caller that reached past
`orchestration` with an identifier of a *superseded element of the right goal* is now admitted.
It is the narrowest widening available that admits the legitimate case: the identifier must
still be an element this goal itself minted and still holds, which no other goal's id and no
fabricated value can be.

**What would reopen this.** A measured case in which a goal-wide `serves` value is recorded that
a reader of the goal cannot account for; a later decision that gives an intended action a
standing field, since a withdrawal rule may want to know which reading an action was minted
against; or a change to ADR-0249 §11's one-site persistence that makes the interleaved order
available on an opening turn, which would make the current-instant reading satisfiable again —
though not, on its own, preferable, since ADR-0265 §3 would still call the stale link
legitimate.

## Alternatives considered

**Carrying the revision the minting was computed against on `IntendedActionMinting`**, and
checking `serves` against that revision. Rejected: it makes the command carry a second authority
that can disagree with the goal, it adds a field the seam never sees and the loop must not get
wrong, and it buys a narrower test for a check that ADR-0265 §3 already says gates nothing. The
goal-wide test needs no new field, no migration and no new failure mode.

**Dropping the conjunct entirely**, on the ground that `serves` *"gates nothing"* (ADR-0265 §3).
Rejected in §1: a dangling or foreign identifier is *"a warrant the goal could never show"*, and
ADR-0265 §5's reason for closing it at the store rather than trusting the caller — ADR-0249 §7's
own reason for dropping an element whose ground does not resolve — is untouched by this
decision.

**Routing an opened turn's later revisions through `record_interpretation`** — the reviewer's
direction on PR #2411, and #2414's direction 2. Rejected in §2: it makes an `OPENED` turn
announce a revision, conditionally on whether the turn minted, which is a persistence detail
deciding what the user is told.

**Making the store drop an unresolvable `serves` entry rather than refuse the command**, by
analogy with ADR-0265 §3's drop rule at the seam. Rejected: ADR-0265 §3's drop is `orchestration`
resolving a *label* it showed the planner, where a miss is an index outside a range; the store's
refusal is over *identifiers* no seam produced, and silently dropping one would let a caller's
mistake become a well-formed record nobody could question afterwards.

**Deferring the decision until L3 lands.** Rejected: L3 is the lane that makes the state
reachable, so deciding afterwards means landing a producer onto a store that refuses its first
opening turn, and the fix would then compete with a live defect rather than precede it.

Refs: ADR-0265, ADR-0249, ADR-0250, ADR-0228, #2414
