# 266. A coverage member records the constraint the user stated, and the bound is proved against
the quote for the intended action

- Status: Partially superseded by ADR-0262 (§10's *"What the verification phase does with a quote, and coverage's other conditions"* entry, in its *"Fired by A10"* clause and in the application of that clause to the charge confirmation and the quote/charge mismatch finding alone — the first dated note below states it in full) and ADR-0270 (two limbs: §7's last normative clause in the limb naming `ActionPolicy.decide` as the only site where condition 6 is taken, and §11's lane-ordering clause in its Lane-2 limb — the second dated note below states both in full)
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **twelve narrowly stated scopes, found by a sweep of that document rather than one at a time; §9
  shows the working for each and ADR-0254's own `Status` line carries them in full. §1, in four
  limbs**: its **proposal-completeness** condition, that a proposed row's coverage *"is complete for
  this request"*, is restated over §7's **condition 6** — condition 6 alone, because a proposal is
  written `PROPOSED` and §3's condition 1 asks for a live row — the ratified wording being stated
  over *"every user-facing argument … named by a member"*, which a member no longer names; **path
  (ii)'s trigger**, which fires on a span *"naming an argument"* a live row carries a member for,
  fires on a span minting a member of a **kind** it carries one of; **path (iii)'s trigger and its
  per-declaration member selection**, since the mint reads the goal and no declaration at all; and
  **path (iii)'s direct establishment, for a member this decision mints alone** — a reading of the
  user's words the user has not seen is proposed, never established. **§2's member shape**:
  `CoverageMember` carries a **`kind`** and no `argument`, so it records *what the user stated* and
  never *which slot it fills*; with `argument` go §2's depth-one clause, its
  no-two-members-name-one-argument rule (now **one member per kind**) and `currency_argument`,
  **with two further limbs of §2's `MONEY` currency clause** — its cross-member
  `fixed`-equals-`currency` refusal, not constructible once no member names an argument, and its *"A
  call whose declaration carries no currency argument takes no `MONEY` bound"* rule, which the
  owner's ruling of 2026-09-14 reverses — while the bound gains **`maximum_exclusive`** and a
  `fixed` value is validated against the member's kind. **`maximum` stays required and `minimum`
  stays optional**, §4 minting no floor. **§3's condition 6 and its field count**: the set equality
  over argument **keys** and the per-argument rule are replaced by **two routes** — a member is met
  against the **quote taken for the step's intended action**, or against a declared argument at its
  kind, a `MONEY` member needing the quote and the declared argument **as well** — the
  system-supplied validator's rule being preserved by a refusal on a new declaration field, and
  `ToolDefinition` gaining **one** further field, `bounded_arguments`, so *"`ToolDefinition` gains
  one field"* is over-narrow by one. **§4's `MONEY` reading, in two limbs**: the currency is read
  off the quote or the declaration, never the bound; and the `maximum` inequality is read strictly
  where `maximum_exclusive` is set. **§5's widening clause, in two limbs**: at **equal** `maximum`,
  clearing `maximum_exclusive` is a **widening** path (ii) refuses and setting it a narrowing, which
  a numeric comparison alone cannot see; and its *"naming an argument no member covers"* limb is
  restated over §7's condition 6. **§6's lineage-discharge clause, in the narrowing direction
  alone**: ADR-0181 §5's floor is discharged only where every user-facing argument is covered by a
  member on the **argument** route, never where §7's third conjunct let the quote's digest cover an
  undeclared one — a digest proves the call is the one quoted, not one the user bounded, so §6's
  stated ground does not reach it and the `CONFIRM` stands. **§9 clause (ii)**: *"an argument the
  act's own words bear on"* is given its mechanical test — kind agreement, never numeric fit and
  never a model's nomination. **§9 clause (iii)'s *"an argument no member names"* limb**, both times
  it is stated, restated as *an argument the row does not cover under §7's condition 6* — a member
  naming none, the ratified limb would make route (d) unreachable altogether — its force unchanged
  and every other limb binding entire. **§8's and §10's resolution enumeration, in the closure at
  three alone**: a fourth `ResolutionRule`, **`STATED_BOUND`**, which §19 books by name. **§11's
  `CoverageView`**, whose required `argument` field could be transcribed from nothing once a member
  carries none: it carries **`kind`** in its place, its required `span` — the user's own words
  beside the values — unchanged and load-bearing, since the user's assent to that rendering is where
  a stated bound now gets its authority; **and §11's listing, which names that same argument in the
  words it renders a member with, renders it by its `kind` instead**. **§16's roster, in three
  limbs**: `core/types.py` gains a
  **fourteenth** type, `BoundedArgument`, and a **sixth and seventh** field,
  `ToolDefinition.bounded_arguments` and `ActionRequest.intended_action`; and *"`PermissionDecision`
  gains no field"* gains one, `intended_action`, without which a decision recorded for one act
  authorises a request for another. **§20's arm enumeration, scoped by a decidable test and not by a
  list**: every arm of its seventy-one an implementation of §§3-7 cannot satisfy, which **six**
  mechanisms decide — a member *naming an argument* or condition 6 over key sets; a bound's
  `currency_argument` and its cross-member refusal; two members of one **kind** or a `fixed` value
  the kind validation refuses; a `MONEY` member met **without a quote**, or `ResolutionRule`'s
  closure at three; a **path-(iii) opening act carrying a member §4 mints**; and an act **stating a
  money bound** whose own words §4's four-form table does not match, which reaches **no** act a
  ratified resolution mints. §9 applies each and names examples, relying on no list as closed. **For
  five of the six the property each arm demonstrates is unchanged and only its value or its act
  moves, and no arm is dropped; for the path-(iii) one it is a supersession outright**, arms 64 and
  65 losing their no-question limb for a member §4 mints while their whole structure stands for an
  act §10's three ratified resolutions mint. §9 also records the arms the sweep cleared with their
  ground. **Every other clause of every section those twelve scopes touch binds entire**, §9 naming
  them scope by scope. **Partially superseded by ADR-0262** (one scope, in §10's *"What the
  verification phase does with a quote, and coverage's other conditions"* entry: its *"Fired by
  A10"* clause, in the application to the charge confirmation and the quote/charge mismatch finding
  alone, both of which that decision reassigns to the one that pins a dispatch's quote to that
  dispatch, issue #2409 — the note below states it in full).
- **Partially supersedes** [ADR-0016](0016-tool-definition-and-registry.md)
  — **one scope, in §1, and it is the scope already recorded there reaching one further field**:
  the `ToolDefinition` model declaration and the required-field clause in the application to
  `bounded_arguments` alone. A reader holding only §1 authors a definition that declares no
  argument's kind, so no member can meet any argument of it on the argument route. The
  empty-tuple default is an exception to *"Every field that a permission decision depends on is
  required"* on the same grounds already recorded for `system_supplied` — it makes the
  **opposite** claim to the one §1 refuses, since a declaration that declares nothing is met on
  that route nowhere. **The exception is this one further field on this one argument**, and no
  lane reads the two records together as licence to default a third safety field.
- Date: 2026-09-15
- **Partially superseded: 2026-09-15 by ADR-0262 — §10's *"What the verification phase does with a
  quote, and coverage's other conditions"* entry, in its *"Fired by A10"* clause and in the
  application of that clause to the **charge confirmation and the quote/charge mismatch finding**
  alone. Nothing else in this ADR.** The owner's ruling of 2026-09-14 makes the actual charge
  confirmed after the act and a mismatch *"a reported finding"*, and this entry fires both on A10.
  **A10 has no operand for either**: the quote a dispatch was proved against is recorded nowhere —
  §13 of ADR-0254 rules there is no cached coverage verdict, §7 of ADR-0267 makes `quoted` the
  **proposal's** read, and a goal's `quotes` tuple carries the reading the acting step itself
  appended — while comparing the charge against the user's own ceiling instead passes a charge that
  exceeds the quote while staying under it, which is the mismatch the ruling calls a finding. **So
  both are fired instead by the decision that pins that quote to that dispatch**, issue
  [#2409](https://github.com/leonapivato/ai-assistant/issues/2409), sequenced before M33's
  walkthrough; until it lands, ADR-0262 §2 makes every `MONEY` criterion **unestablished** and its
  §7 records that ADR-0255 §13's gate is not met for a capability whose acts charge. A reader
  holding only §10 waits on A10 for a comparison A10 cannot make. **Every other clause of §10 binds
  entire** — *coverage's other conditions* stay fired by the decisions those clauses already name,
  `AttemptPhase.VERIFY` stays A10's by ADR-0255 §17's assignment, and this ADR's own refusals, that
  no clause here verifies anything, compares a charge or writes a finding, are untouched — **and so
  does every other clause of this ADR**, §1's mint, §3's `kind` and §7's proof of the bound
  **before** the act conspicuously so: that proof is what binds spending and ADR-0262 relies on it.
- **Partially superseded: 2026-09-15 by ADR-0270 — two limbs, and nothing else in this ADR.**
  **§7's last normative clause, in the limb naming `ActionPolicy.decide` as the only site where
  condition 6 is taken.** That clause reads *"At `ActionPolicy.decide`, on the concrete request, at
  every dispatch, with no cached verdict anywhere … One implementation, in `permissions`, and §5's
  mint runs none of it."* Read whole it answers *where the comparison is taken* exhaustively, so a
  reader holding only §7 puts condition 6 behind `decide` and exposes no face — and the component
  ADR-0254 §15 obliges to write the row then cannot obtain the answer §7 itself makes that row's
  proposal conditional on, golden rule 1 forbidding the import that would
  ([#2401](https://github.com/leonapivato/ai-assistant/issues/2401)). The comparison is now taken at
  `decide` at every dispatch **and** at `ActionPolicy.coverage_met` before a row is written, over
  one implementation. **The one-implementation limb is kept and not weakened** — the new member is
  that implementation's face rather than a second one — and the **no-cached-verdict limb binds
  entire**, no answer that member returns being cached, carried to a dispatch or read by a later
  comparison. **And §11's lane-ordering clause, in its Lane-2 limb alone**: *"ADR-0254 §20's Lane 2
  is briefed after the quote decision (§10) rather than after these two"* now reads **after the
  quote decision and after ADR-0270's own lane**, Lane 2 being the lane that calls the new member
  and, briefed on §11's ordering alone, the lane that would evaluate condition 6 in `orchestration`.
  Every other limb of §11 binds entire — L1's and L2's surfaces and arms, *"two lanes and no
  third"* for this ADR's own implementation, L1's wait on ADR-0254 §20's Lane 3, the wire clause
  and the no-migration clause — and so does every other clause of this ADR, §7's two routes, its
  condition 6, its fault clause and its lineage narrowing conspicuously so: they are what the new
  member answers with.

## Context

### Where this comes from

Issue **#2373**, found in the pre-flight of ADR-0254 §20's **Lane 2** — the lane that makes
`orchestration` propose an `Authorization` on a `CONFIRM` and write path-(ii) corrections and
path-(iii) opening acts. That lane stopped before writing code: ADR-0254 states what a
`CoverageMember` must contain, but **no clause states how a recorded span is associated with an
argument key, nor how the member's shape is chosen**. The owner's Q1 ruling of 2026-09-12 is what
the answer has to serve: *"Bind authorization to explicitly fixed values and explicitly permitted
ranges. A price change within an approved limit should remain covered. A clear later instruction
such as 'make it Sunday' can supply authorization for that change … Ask only when the concrete
action introduces something not already covered."*

**The owner's ruling of 2026-09-14 decides where the bound is compared, and it is the frame of
this document.** *"The tool takes what the action needs (site, dates, party size). The price is
usually a consequence of those choices, not an argument the assistant supplies."* So the
investigation records the quote for the intended action, the authorisation phase compares the
bound against it before execution, and **nothing about the price is compared against an argument
of the call**; a declared money argument is compared **as well** where one exists, *"a filter is
not a charge"*; no quote means investigate or ask, which is feasibility rather than a restriction;
and the evidence covers a step **only where the step's arguments are the ones that were quoted**.

### The gap this closes, stated as the failure the corpus has today

Without the rule, **none of ADR-0254 §1's three write paths can write a row carrying a non-empty
`coverage`**, and §1's path-(i) completeness condition holds only **vacuously**. Four ratified
clauses each come close and none closes it. **§10**'s three resolutions each turn **a span into a
value** and none names what the value is for; **§9 clause (ii)** states the **property** the
association must have — a value *"for an argument the act's own words bear on"* — and a property
is not a procedure; **§8** closes `AuthorizationBasis` at `act`, `span` and `resolution`, none of
which names an argument; and **§1's path (iii)** points at the goal's interpretation, but
`GoalElement` carries **no typed value and no argument key**. **§9's no-model clause forecloses
the obvious source** — a planner envelope's *"coverage member, a bound, a basis"* is *"discarded
silently"* — and **the association is not among §19's bookings**, so that silence is a gap.

**Why a lane must not simply invent the rule.** §9 clause (ii) forbids adding *"a member for an
argument the act never mentioned"*, but only path (ii)'s widening is store-enforced, so a freshly
minted path-(i) member is checked by nothing and a wrong association is a **standing authority the
user never gave**.

### The tree, read rather than assumed, at `origin/main` `9fa8c110`

**ADR-0254's Lane 1 has landed and so has §20's route-(d) wiring; Lane 3 has not.** `CoverageView`,
`AuthorizationProjection`, `AuthorizationView`, `Confirmation.authorization`,
`TurnOutcome.authorizations` and `AssistantEngine`'s `standing_authorizations` and
`revoke_authorization` are **ratified in ADR-0254 §16 and in no merged tree** — Lane 3 is in flight
and lands them there, so every clause below that reads a projection reads ratified text and never
code. `core/types.py` carries `Authorization`, `CoverageMember`, `ValueBound`, `BoundKind`,
`AuthorizationBasis`, `ValueResolution`, `ResolutionRule` and `ToolDefinition.system_supplied`;
`CoverageMember` carries `argument`, **ADR-0254 §11 declares a `CoverageView` whose `argument` is
required and transcribed from it**, and `ValueBound`'s `MONEY` arm carries `currency_argument` and a
required `maximum`, all four of which this decision changes; `canonical_json_bytes` is public and is
the one encoding and
`ActionRequest.parameters_digest` is computed rather than supplied; `ActionRequest` carries `goal`,
`step_id`, `execution_id` and `egress_binding` and **no `intended_action`**, and
`PermissionDecision.authorises` compares those four and the tool and **nothing about which act a
request is an attempt at**; `permissions/_coverage.py`'s `covers`, `covers_arguments` and
`_argument_is_covered` all read `CoverageMember.argument`; `ToolDefinition` declares nothing about
what kind of value an argument takes; and **`IntendedAction`, `Goal.intended_actions` and
`PlanStep.intended_action` are ratified in ADR-0265 and in no lane's tree yet**, so this decision
is written against that contract and not against code.

**`Authorization` rows are written today, and every one of them carries an empty `coverage`.**
`orchestration/runner.py` records what `proposed_authorization` returns and `app/composition.py`
constructs the `SqliteGoalAuthorizationStore`, so a deployment does hold rows; but
`orchestration/authorizing.py` builds every one with `coverage=()` and returns `None` for any
request carrying a user-facing argument — the vacuous-completeness gate #2373 names — and no
`CoverageMember` is constructed in `src/` outside the canonical fake. **§11's migration clause is
written on that reading and on nothing carried forward**, and nothing records a quote.

### What this ADR is not allowed to settle

It decides what a member **records**, how a span **becomes** one, **what settles it** and **what
it is proved against** — and nothing beyond that. It leaves ADR-0254 §3's conditions 1-5, §7,
§12's expiry as ADR-0256 §1 leaves it and every clause of §11 but `CoverageView`'s field list and
the listing's per-member phrasing untouched, narrows §5 and §6 in one direction each and no
other, and opens no route, relaxes no
floor, lowers no threshold and moves no ruling. **And it does not decide where a quote is
carried, what records one, or how a policy obtains one**: §6 states the four facts and reads them
from nowhere concrete, the carrier and the producer being the **quote decision**'s (§10).

## Decision

### 1. The candidate act is a `USER_STATED` constraint of the goal, and there is no second source

> **Normative.** A coverage member is minted from a **`GoalElement` of the goal's *current*
> interpretation's `constraints` whose `ground` is `USER_STATED`**, and from nothing else. Its
> `span` is the member's; the act and the resolution are §2's. **No other value of this system mints
> one** — not a `criteria` or a `conditions` element, not the interpretation's `outcome`, not a plan
> step, not an evidence row, not a quote and not a memory.

> **Normative — a `FROM_EVIDENCE` element and an `INFERRED` element mint nothing, and the type is
> why rather than a rule to remember.** ADR-0249 §1's validator admits `USER_STATED` with a `span`
> and no `evidence_id`, `FROM_EVIDENCE` with an `evidence_id` and **no span**, and `INFERRED` with
> neither; ADR-0254 §8 requires a span on **every** basis and §9 clause (i) makes a member without
> one **not constructible**. So the two grounds carrying no span cannot reach a basis at all, and
> this states a consequence of two ratified types rather than a third refusal.

> **Normative — the three other exclusions, each a consequence of a ratified clause rather than a
> new refusal.** **`criteria` and `conditions` mint nothing**: a criterion states what success would
> be and a condition when a step may run (ADR-0249 §1, ADR-0253 §7), while ADR-0254 §1's path (iii)
> says where a bound lives in terms — *"the bound is an element of its `constraints`"*. **The
> interpretation's own `outcome` mints nothing**, carrying no identity: ADR-0249 §7 retains it by
> copying `outcome`, `outcome_ground` and `outcome_span` forward byte for byte, so two revisions
> carrying one outcome are indistinguishable from two that restated it and §2's act could not be
> named. **And the *current* interpretation alone**: an element a later revision neither retained
> nor replaced is not in it (*"omission is removal"*), and minting from an earlier revision would
> restore a constraint the user's own later words removed. The history is walked **only** to find
> the act (§2).

### 2. The act, the span and the resolution: what the basis is filled from, and when it refuses

> **Normative.** A member carries an `AuthorizationBasis` whose **`span` is that element's
> `span` byte for byte**, whose **`act` is the `raised_by` of the earliest revision of the
> goal's retained `interpretation` that carries an element with that element's `id`**, and whose
> `resolution` is §4's. Nothing is re-resolved, re-normalised or re-checked against a model:
> ADR-0249 §7 already checked that span against that turn's own `TurnResult.utterance` when the
> revision was recorded, which is exactly the check ADR-0254 §8 requires, and ADR-0254 §1
> re-takes it against the store before the row is built.

> **Normative — three absences each refuse the member, and each is fail-closed.** No member is
> minted where the element carries **no `id`** (a row written before ADR-0253 §7, which no history
> can locate), where the earliest carrying revision's **`raised_by` is `None`** (a row written
> before ADR-0249, whose act this system never recorded), or where the element's **`span` is
> absent** — ADR-0254 §10's *"A resolution the loop cannot take is not taken, and no member is
> minted"*.

> **Normative — an elided history refuses too, and the test is exact rather than approximate.**
> Where the earliest retained revision carrying the element's `id` is the **oldest retained
> revision** and `Goal.interpretation_elided` is **not 0**, no member is minted from that element:
> ADR-0249 §2 drops the **oldest** revisions, so a dropped one may have carried the element first
> and the act would name the wrong turn. Where the carrying revision has a retained predecessor not
> carrying the id it is the first, and where nothing was elided the oldest retained revision is.
> Both are decided from values on the goal, with **no store read**.

### 3. A member records the constraint and never the slot: it carries a kind and no argument key

> **Normative.** **`CoverageMember` loses `argument` and gains `kind`, a `BoundKind`, required.**
> A member states *what the user's words fixed or bounded* — an amount, a period, a named term —
> and states **nothing about which argument of which declaration carries it**. Its `fixed`,
> `bound` and `basis` are unchanged, and a `bound` it carries has a `kind` equal to the member's,
> refused at construction otherwise. **A `fixed` value is validated against the member's `kind`
> too, and a `MONEY` one is refused outright**: an amount carries no currency on a `fixed` member
> and ADR-0254 §4's `MONEY` reading compares none without one, so such a member states an amount
> nothing can denominate. A `PERIOD` member's `fixed` is a value that reading accepts and a
> `TERMS` member's is a JSON string, each refused at construction otherwise — without which
> arbitrary JSON could be labelled at a kind and compared under a reading it does not fit.

> **Normative.** **No two members of one `Authorization` carry the same `kind`**, refused at
> construction — ADR-0254 §2's no-two-members rule stated over the value that now identifies a
> member, and for that clause's own reason: *"A precedence rule between two members about one
> argument is a rule somebody would have to remember at the comparison."*

> **Normative — `ValueBound` changes in two respects and no others.** A **`MONEY`** bound gains
> **`maximum_exclusive`, a `bool` defaulting to `False`**, `MONEY`-only, **so a ceiling the user
> stated strictly is representable as one**: *"under 100"* excludes `100` and *"at most 100"*
> includes it, and the two stop being one value. And **`currency_argument` is removed**: the key
> carrying an amount's currency is a fact about a **declaration**, not about an act, and §7 reads
> it there. **`maximum` stays required and `minimum` stays optional, exactly as ratified**; nothing
> here mints a `MONEY` `minimum` (§4), so no floor is representable through it, and `PERIOD` and
> `TERMS` are unchanged.

> **Normative — `maximum_exclusive` is ordered for ADR-0254 §5's narrowing test, and the
> direction is stated rather than left to a numeric comparison.** §5 refuses a path-(ii)
> correction that **raises a ceiling**, and at **equal** `maximum` the flag is the whole of the
> difference: **setting it narrows** (*"at most 100"* corrected to *"under 100"* withdraws the
> endpoint) and **clearing it widens** (*"under 100"* corrected to *"at most 100"* adds a call at
> exactly `100` that the live row refused). **A clearing at an equal `maximum` is therefore a
> widening §5 refuses**, path (ii) writes no row, and the act asks and is established by path (i)
> carrying `supersedes` — §5's own disposition, unweakened. A lane that compared `maximum` alone
> would read the second as a correction and establish a wider authority with no confirmation,
> which is the permissive direction ADR-0254 §2's asymmetry names.

> **Normative — ADR-0254 §4's `MONEY` comparison is restated over the one flag and in no other
> respect.** The amount satisfies the bound where it is **less than** `maximum` if
> `maximum_exclusive` and **less than or equal to** it otherwise. Every other conjunct is unmoved
> — the `minimum`, the `Decimal`-accepting shapes, the finite-and-not-negative refusal, the
> no-float rule and the currency conjunct §7 relocates — and **`PERIOD` stays half-open and
> `TERMS` stays equality of stated characters**.

**Why the argument key was the defect rather than the rule that chose it.** A value that *fits* an
argument is not one the act's words *bear on*, so no rule selecting an argument at the mint could
satisfy ADR-0254 §9 clause (ii): a hotel's star rating has a number in it and would fit a price,
while *"four stars"* has no `MONEY` reading at all (§4). **A member is still not portable across
tools**: ADR-0254 §3's condition 3 compares the request's `tool` against the row's **by value**,
left entire here — the rebinding #54 closed. What a member survives is an argument renamed inside
one declaration.

### 4. The reading: how a span becomes a proposal, and the user's answer is the authority

> **Normative — `core/types.py` gains a fourth `ResolutionRule`, `STATED_BOUND`, taking neither
> argument.** The span is read **as a bound**. ADR-0254 §19 books *"A fourth `ResolutionRule`"* by
> name and this decision fires it; §10's other three are untouched and remain the only readings
> that produce a **value**.

> **Normative — what is read is the element's span, normalised, and a question mints nothing.**
> **A span carrying a `?` anywhere mints no member of any kind**, before any other step: *"under
> 100 euros?"* asks whether a price is below a figure and grants nothing, and ADR-0254 §9 clause
> (iii)'s posture on an ambiguous act is to ask rather than to guess. Otherwise fold to lower
> case, collapse runs of ASCII whitespace to one space and trim **one** trailing `.` or `!` —
> normalisation *"part of the resolution … recorded with it"* (ADR-0254 §10), never applied at
> the comparison — and match the result **in full** against the table below. **Nothing outside
> the span is read**: there is no negation vocabulary, no adjacency test, no requirement that the
> span be a clause or be the act's whole utterance, and **no lane adds one**. What the text
> around the span meant is settled by the user and never by a rule (below).

> **Normative — the `STATED_BOUND` table is closed, is stated here whole, and is the entire
> reading.** The normalised span is matched **in full** against exactly these forms, in which
> `<amount>` is a decimal figure ADR-0254 §4's `MONEY` reading accepts together with one word of
> the currency table below, in either order:
>
> - **exclusive** — `under <amount>`, `below <amount>`;
> - **inclusive** — `at most <amount>`, `up to <amount>`.
>
> **Four forms and no fifth**, and **every form mints a `maximum`**, the table stating no other
> direction. *"at least 150 euros"*, *"more than 150 euros"* and *"over 150 euros"* are not forms
> of it; and **no negated form is a row of it** — *"never spend over 100 euros"* mints nothing, its
> reading being an inversion a rule would have to perform on the user's behalf, which §10 books.
>
> The currency table is `euro`/`euros`/`eur`/`€` → `EUR`, `dollar`/`dollars`/`usd`/`$` → `USD`,
> `pound`/`pounds`/`gbp`/`£` → `GBP`. **A span matching no form mints no member**, and no lane
> adds a form, a currency or a language without its own ratified decision.

> **Normative — a strict word mints a strict bound, and the endpoint is never widened.** *"under
> 100 euros"* mints `maximum` `100` with `maximum_exclusive`, so a call at exactly `100` is **not**
> covered; *"at most 100 euros"* mints the same `maximum` without it, and a call at `100` is. **No
> reading rounds, quantises, nudges or relaxes an endpoint in either direction**, and no lane reads
> a strict word as inclusive *"because the difference is a cent"* — the difference is a cent in the
> direction that authorises a call the user did not authorise (ADR-0254 §2).

> **Normative — this decision's mint takes `STATED_BOUND` and no other reading.** `AS_STATED`,
> `DATE_FROM_CONTEXT` and `FROM_SHOWN_RECORD` mint nothing through §§1-5 and are **untouched**
> wherever ADR-0254 §10 already fires them, so the only member this decision mints is a **`MONEY`
> ceiling** and there is no ordering between readings to state. `FROM_SHOWN_RECORD` could not
> reach an element in any case: ADR-0249 §1's validator gives a `USER_STATED` element a span and
> **no** `evidence_id`, so none carries both a span and the record its reference resolved to.
> §10 books the other two with what fires each.

> **Normative — a member this decision mints is `PROPOSED` and is never established from a span,
> and the authority is the assent to the rendered text.** A `STATED_BOUND` member reaches a
> durable row **only** through ADR-0254 §1's **path (i)**: the row is written `PROPOSED` before
> the question is put, §11's `AuthorizationProjection` renders it, and the user's answer settles
> it — **yes establishes it and no declines it** (`PROPOSED → ESTABLISHED` and
> `PROPOSED → DECLINED`, §1's edges unchanged). **It reaches a path-(iii) opening act in no
> case**, that path writing `ESTABLISHED` directly with no question put; a path-(ii) correction
> may carry one forward or narrow it, the row it corrects having been established by an answer
> and §5's refusal of every widening standing. **The span is evidence shown with the proposal and
> carries no authority of its own** — `CoverageView` transcribes it beside the values (§9), so
> the user reads the words the reading rests on next to the ceiling it produced. **A reading that
> got the polarity wrong is therefore shown and declined rather than silently established**:
> *"avoid booking hotels under 100 euros"* proposes a ceiling of `100` `EUR`, the user reads *"up
> to 100 euros"* beside their own words, answers no, and **no authority exists**. That is the
> owner's principle applied — asserted authority is assent to the rendered text — and it is why
> this section needs no rule that can see what the words around a span meant.

> **Normative — the quote precedes the proposal, because the completeness condition requires it,
> and that fixes the order of the phases.** ADR-0254 §1 proposes a row only where the coverage it
> would carry is complete for the request, which §7 restates over condition 6, whose first
> conjunct is that **every member of the row is met** — and a `MONEY` member is met only against
> a quote for the step's intended action (§7). **So no proposal carrying a `STATED_BOUND` member
> is constructible before the investigation has recorded that quote**, and the order is fixed:
> the investigation quotes the intended action over that step's own arguments, then the
> authorisation phase proposes the row and puts the question, then execution. **Where no quote
> has been recorded, no row is proposed**, `Confirmation.authorization` is absent, and route (a)
> **asks** — §1's own disposition and the owner's *"No quote → cannot prove the price →
> investigate first or ask"*. **What that answer authorises is the one concrete call and nothing
> else**: it establishes no standing authority, is not a path-(iii) opening act, and leaves the
> user's ceiling proved against nothing, so the exposure is bounded by the call the user was
> shown rather than by the bound they stated. **What such a confirmation renders about a charge
> is not decided here** and is §10's booking: no clause of this decision puts a price in front of
> a user, there being no typed quote to render until that decision lands a carrier.
>
> **What the proposal renders, and the one thing it does not carry.** The projection renders the
> row: each member's `kind`, its `fixed` or its `bound` — the `maximum`, its `currency` and
> whether `maximum_exclusive` withdraws the endpoint — the `expires_at` ADR-0256 §1's ladder
> yielded, and `CoverageView`'s `span`. **That is the whole of what the user assents to.** The
> **quoted figure the completeness condition was satisfied against is not carried by that
> projection, and this decision adds no member to it**: there is no typed quote to transcribe
> until §10's booked decision lands a carrier, and minting untyped members for it here would be
> that carrier under another name. **Where that decision lands it, the figure is rendered beside
> the ceiling**; until then the user assents to the kind, the ceiling, the horizon and their own
> words.

**What it costs, and what a matching span buys.** A span the table does not match mints nothing and
the act asks — a floor, a negated ceiling, a figure written in words, another language and every
kind but `MONEY` among them, each booked in §10. A span it matches buys **one question**, put once
in the authorisation phase, after which every later call whose quote sits under the ceiling is
covered with no second question. **Minting only a ceiling has a mechanical ground rather than a
judgement about polarity**: §7's evidence route is `MONEY`-only because a quote states a price and
nothing else, so a member of another kind could be proposed and never **met**, and §1's
completeness condition would refuse the proposal carrying it.

### 5. One member per kind, and the mint reads the goal and nothing else

> **Normative — where two candidate elements of one goal would mint members of one `kind`, neither
> is minted.** No precedence, no ordering, no most-recent rule and no narrowest-wins rule: ADR-0254
> §2 refuses a row carrying two members about one thing, and choosing between two constraints the
> user stated is an interpretation of which one they meant. A later constraint that **replaces** an
> earlier one is §1's path (ii); two standing at once is an ambiguity, and §9 clause (iii)'s answer
> to an ambiguity is that the user is asked.

> **Normative — the mint reads the goal's own current interpretation and its retained history, and
> nothing else.** **No request, no plan, no step, no declaration, no registry, no quote, no
> utterance beyond the element's own `span` and no clock.** A member is therefore the same value
> whatever call was being built when the row was written, which is what makes *"the authorization
> records the constraint as the user stated it"* true of the record — and why no plan a model
> produced can shape the **content** of an authority.

### 6. What a `MONEY` ceiling is proved against: the quote, stated as an interface and read from nowhere concrete

> **Normative — a quote is a record of what the intended action will cost in full, it supplies
> exactly four facts, and it carries no kind.** §7 is written over four facts alone: the
> **`IntendedAction`** (ADR-0265 §1) it was taken for, by `id`; the **arguments it was quoted
> over**, as the digest below compares; an **amount** and its **currency**, the amount in the form
> ADR-0254 §4's `MONEY` reading accepts and that reading's ISO-4217 code; and the **step output it
> was read from**, provenance compared by nothing. **The amount is the whole charge the act will
> make and never a component of it** — not a fee, not a deposit, not a per-unit rate, not one leg of
> a transfer — because §7 proves the user's ceiling against it and against nothing else: a quote of
> a €1 fee for a €200 transfer satisfies a €150 ceiling while the act breaches it. **That is an
> obligation on the quote decision** (§10), and a record stating a component is not a quote under
> this interface rather than a conforming one. **A quote states a price and nothing of any other
> kind**, so it carries no `BoundKind`: §7's evidence route is `MONEY`-only for that reason. The
> quotes of one goal are **totally ordered**, so a second reading of one price is legible as a
> **refresh** of the first rather than as a second act of the user — ADR-0252 §7's *"a refresh
> supersedes the row it displaces"*, which §7's governing-quote rule is taken under.

> **Normative — this decision states that interface and nothing else about a quote.** No type, no
> field of any existing model, no store member, no Protocol, no bound on how many a goal holds, no
> rule about which component records one, no expiry and no face by which a policy obtains one —
> all the **quote decision**'s (§10), and **no lane here authors any of them**.

> **Normative — the arguments a quote was taken over are compared by one digest, over one key set,
> and it is not a second canonicalisation.** The digest is `sha256` over the canonical JSON
> encoding `ActionRequest.parameters_digest` is taken over (ADR-0021 §1), taken on both sides over
> **every argument of the call except those the declaration classifies as a per-call identity** —
> and **no declaration classifies any today**, `ToolDefinition.system_supplied` naming keys
> `orchestration` fills and saying nothing about which of them a price depends on, so **every**
> system-supplied key is inside the digest until the decision §10 books draws that line. **An
> extra argument, a missing one and a changed one each change the digest**, which is the owner's
> rule that the quote covers the booking only where *"the step's arguments are the ones that were
> quoted"*.
>
> **The cost is stated rather than hidden**: `orchestration` fills a system-supplied key **per
> call**, so a declaration that fills one is covered by **no** quote and every act under it asks.
> The permissive spelling is the defect — excluding such keys by kind would let a quote taken under
> one **locale** authorise a charge priced under another — and §10 books the classification.

### 7. The two routes, and what covers a request

> **Normative.** `core/types.py` gains **`BoundedArgument`**, a frozen model with
> `extra="forbid"` whose fields are exactly three: **`argument`**, an `EncodableText` naming a
> key of `parameters` at depth **one**; **`kind`**, a `BoundKind`; and **`currency_argument`**,
> an `EncodableText | None` naming the key that carries this amount's currency. A **model
> validator** admits exactly two shapes — `MONEY` with a `currency_argument`, or `PERIOD` or
> `TERMS` with none — and refuses `argument` equal to `currency_argument`. This is a **BREAKING**
> contract change to `core/types.py` under golden rule 5 and is flagged as one.

> **Normative.** **`ToolDefinition` gains one field, `bounded_arguments: tuple[BoundedArgument,
> ...]`**, possibly empty, **defaulting to the empty tuple**, duplicate-free on `argument`, and
> naming **no key of that declaration's own `system_supplied`** — refused at construction. It is the
> whole of what a declaration says about which of its arguments takes an amount, a period or a named
> term. **Declaring a money argument is a safeguard and not a requirement** — the owner's ruling
> makes the quote the primary route at every tool — so a declaration omitting one keeps its ceiling
> proved against the quote and forgoes only the second comparison, at the cost §10 books. **The
> refusal is what preserves ADR-0254 §3's system-supplied protection after the validator stating it
> is gone**: that section made a row whose coverage names a system-supplied argument not
> constructible by reading `CoverageMember.argument`, which no longer exists, so a system-supplied
> key being declarable at no kind is what keeps *"a user is never asked to approve an idempotency
> key"* true one field over. This is a **BREAKING** contract change to `core/types.py` under golden
> rule 5 and is flagged as one.

> **Normative.** **`ActionRequest` gains `intended_action`, an `Identifier | None` defaulting to
> `None`** — the `IntendedAction` (ADR-0265 §1) the step this request serves is an attempt at,
> which is `ActionRequest.goal`'s shape one field over and is how a request says which act it is.
> A request carrying `None` is met by the evidence route in no case. **And
> `PermissionDecision` carries it too**: `from_request` transcribes it as it transcribes the
> ruling, and **`authorises` gains a sixth conjunct comparing it** beside the tool, the
> parameters, the `step_id`, the `execution_id` and the `egress_binding`. Without that conjunct a
> decision taken for one act authorises a later request differing only in the act it is an
> attempt at — and the whole of this decision's proof is that the amount was quoted **for that
> act**, so the value the coverage was proved through would be the one value the trail could not
> compare. **That is why it is transcribed where `ActionRequest.goal` deliberately is not**
> (ADR-0254 §16): a goal id is a value the trail *"cannot compare against the arguments"*, and an
> intended action is precisely what selects the quote the comparison was taken against. Both are
> **BREAKING** contract changes to `core/types.py` under golden rule 5 and are flagged as such.

> **Normative — the evidence route is `MONEY`-only, the governing quote is selected before its
> digest is tested, and a `MONEY` member is met by it where all three hold.** The request carries
> an `intended_action`; **the governing quote** — of the quotes available to the policy (§6) that
> name **that** action, the one **latest in §6's order**, and no other — has an arguments-digest
> equal to the digest of **this request's** arguments, taken exactly as §6 takes it; and that
> quote's amount satisfies the member under ADR-0254 §3's fixed comparison or §4's `MONEY`
> reading, with that reading's **currency conjunct taken at the quote's own currency** and at no
> key of the request. **An earlier quote is consulted in no case**: a re-quote is a refresh of one
> fact and the current price is the later reading, so a request returning to arguments a
> superseded quote was taken over is **uncovered and the act asks**, rather than reviving a
> reading the re-quote displaced. That is the restrictive direction ADR-0254 §2 asks for, and it
> leaves the staleness of the governing quote itself exactly where §10 books it. **No member of
> any other kind is met by this route in any case** — a quote states a price and carries no other
> value (§6), so there is nothing for a `PERIOD` or a `TERMS` member to be compared against, and
> §4 mints no member of either kind for this decision to need one for. **Where no quote governs,
> or the governing one's digest differs, the member is not met**, the request is uncovered, and
> the user is asked or the act is investigated first — the owner's *"no quote → cannot prove the
> price"*, which is feasibility rather than a restriction on the tool.
>
> **A fault is never an absence.** Where the read behind §6's quotes fails, the request is treated
> as **not covered** and the fault is reported; **no implementation converts a fault into an absence
> of quotes** and none falls through to the argument route — ADR-0254's own distinction between
> `AuthorizationError` and absence.

> **Normative — the argument route, available only where the declaration declares, and it never
> stands in for a quote.** A member of kind *k* is met by it where the declaration carries
> **exactly one** `BoundedArgument` at *k*, the request carries a value at that argument, and the
> value satisfies the member under ADR-0254 §3's and §4's readings, with a `MONEY` bound's currency
> conjunct taken at that `BoundedArgument`'s **`currency_argument`** in the concrete request, which
> is what makes that currency key **covered** rather than unexamined. **Where the
> declaration declares no argument at *k*, or declares more than one, no member of kind *k* is met
> by this route** — no default kind, no inference from a value's JSON type, no schema keyword and
> no fallback to an exact comparison, ADR-0254 §4's *"No reading consults a schema to decide what
> an argument means, and there is no exception"* binding this rule as every other. **A `MONEY`
> member needs the evidence route in every case, and the argument route as well where the
> declaration declares an argument at `MONEY`** — both holding, because a `max_price` constrains
> what a search returns and a transfer amount is one leg of a call, and *"a filter is not a
> charge"*. A `PERIOD` or a `TERMS` member — which §4 mints none of — is met by this route alone.
> **Where a value is supplied into a declared money argument as a safeguard, its source is the
> member's own `maximum` and there is no other**; which declarations admit such a fill is booked
> (§10).

> **Normative — ADR-0254 §3's condition 6 is restated, and it keeps both its directions.** An
> `Authorization` satisfies condition 6 for an `ActionRequest` where **all three** hold: **every
> member of the row is met**, by the routes above; **every user-facing argument of the request
> that the declaration declares in a `BoundedArgument` is covered** by the member of that
> argument's kind, a request carrying no member of that kind being **uncovered**; and — where the
> request carries **any** user-facing argument the declaration declares at no kind — **at least
> one member of the row is met through the evidence route**, whose digest pins every argument the
> request carries. **A key a `BoundedArgument` names as its `currency_argument` is not such an
> argument — but only where the comparison that consumes it was actually taken**: it is exempt
> where the request carries a value at that `BoundedArgument`'s own `argument`, the row carries a
> `MONEY` member, and that member is met on the argument route against it, whose §4 comparison
> reads the currency key there. **In every other case it is an ordinary user-facing argument the
> declaration declares at no kind** — a request carrying the currency and no amount, or one whose
> row holds no `MONEY` member, leaves it compared by nothing, so the third conjunct reaches it and
> the request is uncovered without a quote; an unconditional exemption would let
> `{"currency": "EUR"}` and `{"currency": "USD"}` both pass an empty row. A member met by no route
> leaves the request uncovered, which is §3's second direction — *"an act that fixed
> `refundable_only` to `true` authorised a call **carrying** that value"* — and an argument the
> row cannot meet leaves it uncovered, which is §3's first. **There is no default, no wildcard and
> no omission that reads as consent.** **The third conjunct is what keeps an undeclared argument
> from going unexamined**: without it a
> row fixing `subject` to *"urgent"* would cover a later `send_message` carrying a different
> `body`, and with it the owner's booking case, whose `site`, `dates` and `party` are declared
> nowhere, is covered through its quote while a tool with no quote and undeclared arguments asks.
> **What the digest pins is that the call is the one quoted, not that the user chose each of its
> arguments** — the cost §10 books.
>
> **And ADR-0254 §1's completeness condition is restated over condition 6 alone**, as *the row the
> proposal would write satisfies condition 6 for this request* — condition 6 and not `covers`,
> because a proposal is written `PROPOSED` and condition 1 asks for a live row. §9 shows the
> working. **Where it fails, no row is proposed**, `Confirmation.authorization` is absent and the
> one call is authorised by route (a) — §1's own disposition, unweakened.

> **Normative — ADR-0181 §5's lineage floor is not discharged by a coverage the evidence route
> supplied, and that is a narrowing of ADR-0254 §6 rather than a reading of it.** §6 discharges
> that floor for a request a live row covers *"in full"*, and its stated ground is that where
> every user-facing argument is covered by *"the user's own fixed values and permitted ranges"*,
> outside content *"cannot have steered anything the user did not bound"*. **The digest does not
> supply that ground**: it proves the call is the one that was quoted, and both the quoted
> arguments and the quoting output passed through a plan and a tool. So a request whose
> `egress_binding` carries `planned_with_external_content` is discharged **only where every
> user-facing argument it carries is covered by a member on the argument route**, and never where
> condition 6's third conjunct did the work. **Where it is not, the floor binds unrelaxed and the
> ruling is the `CONFIRM` the table reached** — §6's own *"Partial coverage still asks"*, reached
> by one further case. Every other limb of §6 binds entire, its five conditions included.

> **Normative — where the comparison is taken, and it is one implementation.** **At
> `ActionPolicy.decide`, on the concrete request, at every dispatch, with no cached verdict
> anywhere**, which is where ADR-0254 §13 puts it — *"nothing is compared at dispatch"* in the
> owner's ruling names the **price**, proved against the quote and against no argument of the
> call. **One implementation, in `permissions`**, and §5's mint runs none of it.

**The worked case, because the rule is easier to check against one, and it is the owner's own.**
*"Book Riverside if it is dry Saturday, up to 150 euros."* The interpretation carries a
`USER_STATED` constraint whose span is *"up to 150 euros"*; §4 reads it as a `MONEY` ceiling of
`150` `EUR`, inclusive, and **mints a proposal and not an authority**. The investigation quotes the
site for Saturday at `120`/`EUR` over *(site, dates, party)* — which it must, §1's completeness
condition being unsatisfiable until it has — and the authorisation phase proposes the row and asks
**once**: the projection renders *up to 150 euros*, the horizon ADR-0256 §1's ladder yielded, and
the user's own words beside them. **Yes establishes the row**; the booking request carries the same
intended action and the same three arguments, the digest matches, `120 ≤ 150`, and route (d)
`ALLOW`s with **no second question**. *"Make it Sunday"* replans and the re-quote is `135`: that
quote governs, `135 ≤ 150`, and **still no question**; a Sunday price of `170` is covered by nothing
and the user is asked. **One confirmation, in the phase the owner named** — and had §4 read the
polarity of that first turn wrongly, the wrong ceiling would have been on the screen the user
answered, which is the whole of why the reading needs no rule about the words around the span.

### 8. Writer clauses, and what no model does

> **Normative.** **`orchestration` mints every coverage member, and nothing else does.** No
> `ActionPolicy`, no `ToolRegistry`, no store, no reader, no interface adapter, no tool and no model
> **constructs, writes or repairs** one — ADR-0254 §15's writer clause reaching the values §§1-5
> add, every input the mint reads being on the goal already (§5).

> **Normative — no durable value of this decision is ever taken from a model, and the list is
> exact.** A planner envelope carrying a **`CoverageMember`**, a **`ValueBound`**, an
> **`AuthorizationBasis`**, a `BoundKind`, an argument key or a **`BoundedArgument`** has those
> values **discarded silently** — not an error, not a park, not a degradation of the turn — which is
> ADR-0254 §9's posture over the values this decision adds: a value a model wrote into a durable
> audit chain is unprovenanced.

> **Normative — a model contributes exactly one thing to this decision, and it is the span.** An
> element's span is checked against that turn's own utterance by ADR-0249 §7, and §4 bounds what a
> differently chosen one can do in two ways. **The first is total: what a span mints is a `PROPOSED`
> member the user is shown and answers**, so a span chosen wrongly produces a ceiling on the screen
> rather than an authority in the store, and the user's no is the whole refusal. **The second is
> that the table mints a ceiling or nothing**, so a form it does not carry is refused rather than
> guessed at. **Nothing else a model produces reaches any input of §§1-5 or §7** as a selector or a
> written value: the argument a member meets is the **declaration's** (§7) and the identifiers are
> the loop's. **A model names no argument key, no currency key and no identifier anywhere in this
> decision.**

### 9. What this records against earlier ADRs, clause by clause, under ADR-0082 §1

ADR-0082 §1's test is applied to the earlier ADR's **text** and is shown rather than asserted:
*"Would a reader holding only the earlier ADR now act differently, or read one of its clauses more
widely than it now holds?"* **Two documents come out yes** — ADR-0254 in twelve scopes and ADR-0016
in one; every other ADR cited comes out **no** and takes none, which ADR-0082 §1 requires as
firmly. **The twelve were found by one sweep of ADR-0254 rather than one clause at a time**: every
clause naming a `CoverageMember`'s `argument`, a `ValueBound`'s `currency_argument` or a member
*naming* an argument, every clause treating a span as **establishing** rather than proposing, §16's
`core`-surface roster and §20's landed arms.

**ADR-0254 §1 — in four limbs, three of them the sweep's.** **Its proposal-completeness condition**
reads that the coverage is *"**complete for this request**: every **user-facing** argument of the
request (§3) is named by a member … **or** the request carries no user-facing argument at all"*. A
member names no argument once §3 above lands, so only the second limb could be satisfied and **no
row carrying a non-empty coverage could ever be proposed** — the inert outcome this decision exists
to remove. §7 restates it over condition 6; its purpose, disposition and cost are unchanged. **Path
(ii)'s trigger** fires on *"a later recorded turn of the same goal whose span **names an argument**
a **live** row of that goal already carries a member for"*; it is restated as *a later recorded turn
whose span mints a member of a **kind** a live row of that goal already carries a member of*, its
liveness requirement, its transcription list and its `origin` rule binding entire. **Path (iii)'s
trigger and its per-declaration member selection** fire on a span stating a value *"over an argument
of the request being built"* and rule that *"A row carries members for the arguments of its **own**
declaration that the act's words bear on"*. §5 above makes the mint read the goal and **no
declaration at all**, so members are not selected per declaration and two rows of one act carry the
same members; §1's own *"up to fifty pounds for the train and a hundred for the hotel"* illustration
now **mints nothing**, one member per kind reaching both `MONEY` constraints. **The limb gets no
replacement selection rule** — there is none, and §10 books the reading that would need one. **And
path (iii)'s direct establishment, for a member this decision mints alone**: it writes `ESTABLISHED`
with `confirmation` unset, and §4 forbids a `STATED_BOUND` member there — **which adds no refusal to
§10's three ratified resolutions** and leaves path (iii) as inert as today. **Every other clause of
§1 binds entire**: the three write paths themselves, the row written before the question is put, the
never-edited coverage, the conditional supersession and §1's other proposal conditions.

**ADR-0254 §2 — in the member's shape and in two further limbs of its `MONEY` currency clause.** §2
declares `CoverageMember`'s fields *"exactly: `argument`, an `EncodableText`; `fixed`; `bound`; and
`basis`"*, rules that *"No two members of one `Authorization` name the same `argument`"*, gives a
`MONEY` bound a `currency_argument` as *"the whole of the association between an amount and the
currency it is denominated in"*, and makes `maximum` required. §3 above replaces `argument` with
`kind`, restates the no-two-members rule over the kind, moves the currency key to the declaration
and the quote, gives `maximum` an **exclusivity flag** and validates a `fixed` value against the
kind; `maximum` stays required and `minimum` stays optional, §4 minting no floor. **Its depth-one
clause goes with the field it governs** and is stated once more on `BoundedArgument.argument` (§7).
**Two further limbs of the `MONEY` currency clause go with `currency_argument`, and the sweep found
them**: its cross-member refusal — that a `fixed` member naming the bound's own `currency_argument`
*"equals the bound's `currency`"* — is not constructible once no member names an argument; and its
*"**A call whose declaration carries no currency argument takes no `MONEY` bound**"* rule is
**reversed** by the owner's ruling of 2026-09-14, such a call taking one and proving it against the
quote. **Its no-inference limb is kept
and restated one field over**: §7 infers no association from a field name, a type, a schema keyword
or a neighbour, and reads a currency key only where a `BoundedArgument` declares it. A reader
holding only §2 authors a member claiming to know which slot it fills, records *"under 100"* as a
bound a call at exactly 100 satisfies, and refuses a money bound at every declaration naming no
currency argument. **Every other clause binds entire**: the two-shapes validator, `BoundKind` and
its vocabulary rule, the three kinds' fields and refusals, and the permissive-direction asymmetry
§§3, 4 and 7 serve.

**ADR-0254 §3 — in condition 6 and in the field count.** Condition 6 reads that *"the request's
user-facing arguments and the row's coverage name the same set of keys"*, with an argument covered
*"where the row carries a member naming it"*, and §3 ties the two as *"the whole of condition 6"*.
§7 replaces that whole with two routes and three conjuncts, keeping both of its directions in
substance. A reader holding only §3 builds a comparison in which a price must be an argument of the
call, refusing every booking whose price is a consequence of the site and the dates. With the
`argument` field goes the validator making a row whose coverage names a system-supplied argument not
constructible; **its rule is preserved** by §7's refusal on `bounded_arguments`. And
`ToolDefinition` gains **one** further field, `bounded_arguments` (§7), so *"`ToolDefinition` gains
**one** field"* is over-narrow by one, and a reader implementing from §3's inventory alone authors a
declaration no member can ever be held against. **Every other clause binds entire**: conditions 1-5
— condition 3's by-value declaration comparison conspicuously so — the user-facing classification
and its empty default, the fill-before-the-fit-test and `parameters_digest` clauses, the seam/policy
split, the coverage-never-widens rule, the resolved-reference clause with its *"a value a tool
produced can satisfy a bound and can never supply one"* arm, and §7's canonical encoding.

**ADR-0254 §4 — in two limbs of the `MONEY` reading.** Its **currency conjunct** reads *"the request
carries, at the bound's `currency_argument`, a JSON string equal to the bound's `currency`"*, and
the bound no longer carries that key; §7 takes it at the `BoundedArgument`'s `currency_argument` or
at the quote's own currency, its force unchanged. And its **two `maximum` inequality** is read
strictly where `maximum_exclusive` is set — **its `minimum` conjunct is unmoved and binds entire** —
a reader holding only §4 otherwise covering a call at exactly the endpoint the user excluded.
**Every other clause binds entire**: the `MONEY` reading in every other conjunct, `PERIOD` and
`TERMS` whole, the no-float and no-naive-instant rules, the totality clause, the `reason` discipline
and the no-schema clause.

**ADR-0254 §5 — in the widening clause, in two limbs.** §5 rules that *"A correction that would
widen takes path (i) and asks"*, listing *"An instruction raising a ceiling, adding a term,
lengthening a period, naming a destination the row does not carry, **or naming an argument no
member covers**"*. **In its raising-a-ceiling limb**: §3 above gives `maximum` an exclusivity
flag, so at **equal** `maximum` the flag is the whole of the difference and a numeric comparison
alone reads a clearing as no change. Setting it **narrows** and clearing it **widens** (§3), so a
clearing at an equal `maximum` is a widening §5 refuses, path (ii) writes no row, and the act asks
and is established by path (i) carrying `supersedes` — §5's own disposition. A reader holding only
§5 would let path (ii) write it and establish a wider authority with no confirmation, the
permissive direction §2's asymmetry names. **In its *"naming an argument no member covers"* limb**:
a member covers no argument once §3 lands, so it is restated as **an argument the row would not
cover under §7's condition 6 once the correction is applied**, its force kept and only its test
moved. **Every other limb binds entire** — adding a term, lengthening a period, naming a
destination the row does not carry, the store's refusal, the *"no standing route at all"*
disposition and the path-(i) establishment.

**ADR-0254 §6 — in the lineage-discharge clause alone, and in the narrowing direction.** That clause
discharges ADR-0181 §5's floor for a request a live row covers *"in full"*, on the ground that where
every user-facing argument is covered by *"the user's own fixed values and permitted ranges"*,
outside content *"cannot have steered anything the user did not bound"*. §7's third conjunct lets an
**undeclared** argument be covered by the quote's digest instead, which proves the call is the one
quoted rather than one the user bounded — so a reader holding only §6 would discharge the floor for
a tainted request whose arguments a plan and a tool between them chose. §7 refuses it: the discharge
is available **only where every user-facing argument is covered by a member on the argument route**.
**Every other limb binds entire** — the five conditions, condition 4's unrelaxed form, the
no-extension-to-ADR-0233-§9 asymmetry and *"Partial coverage still asks"* — and **ADR-0181 §5 itself
is not touched**. **§6's bar takes no scope of its own**, and the sweep says why: it is stated over
*"§3's condition 6 and that condition alone"*, so its test moves with condition 6, and its *"names
it in no member at all"* wording describes a case rather than adding a test.

**ADR-0254 §9 clause (ii) — in the test of *"bear on"* alone.** The clause states the property and
no procedure, so a reader holding only §9 either invents a test or, as #2373 did, stops. **Its test
is kind agreement between the constraint and the thing the member is proved against** — a quote,
which is a price and so meets a `MONEY` member and no other, or a `BoundedArgument` at the member's
own kind — never numeric fit, a nomination or a schema. **Its prohibitions bind entire.**

**ADR-0254 §9 clause (iii) — in its *"an argument no member names"* limb alone, both times it is
stated.** That clause rules that where the concrete action introduces what the coverage does not
hold — *"a cost above a `maximum`, a term outside a named set, a destination outside the set, an
argument no member names"* — *"the request reaches no route (d) and the user is asked"*, and states
the same limb again on §6's bar for a live row. **A member names no argument once §3 lands, so every
argument of every request is one no member names and route (d) is unreachable altogether** — the
mirror of §1's inert proposal. It is restated as **an argument the row does not cover under §7's
condition 6**, which keeps its whole force — such an argument still asks, and still on §6's bar
where a live row exists — and moves only its test. **Every other limb of clause (iii) binds
entire**: the material-ambiguity rule with ADR-0250 §6's three conditions and no fewer, the cost
above a `maximum`, the term outside a named set and the destination outside the set, each still
reaching no route (d). **Clause (i) and §9's discard rule bind entire.**

**ADR-0254 §8 and §10 — in the resolution enumeration's closure alone.** Both state
`ResolutionRule` *"closed at exactly three members"*; §4 adds `STATED_BOUND`. **This is the
supersession §19 books by name** — *"A fourth `ResolutionRule`. Fired the same way, and never by a
resolution whose inputs are not on the turn it names"* — and the new rule honours it, its one
input being the span the basis already names, which ADR-0249 §7 checked against that turn's own
utterance. **Every other clause binds entire**: §8's
basis fields, its span check and its two-zones clause; §10's three ratified resolutions —
untouched wherever that section already fires them — its no-memory-no-preference and
normalisation-at-the-mint rules and its *"A resolution the loop cannot take is not taken, and no
member is minted"*.

**ADR-0254 §11 — in `CoverageView`'s field list and in the listing's per-member phrasing, and it
is the sweep's most consequential find.** §11 declares `CoverageView`'s fields *"exactly
`argument`, an `EncodableText`; `fixed`;
`bound`; and `span`"* and requires the projection to carry *"the recorded values by transcription
and not a second derivation of them"*. A member carries no `argument` once §3 above lands, so a
**required** field would have to be transcribed from nothing and **no projection would be
constructible for any member at all** — the confirmation ADR-0254 §1 puts before every path-(i) row
would not render. **`CoverageView` carries `kind`, a `BoundKind`, in its place**, its other three
fields, its two-shape rule and its **required `span`** unchanged — and that span is what §4 rests
on, §11's own *"a user reading "under sixty pounds" beside a bound of GBP 60 can check the working
before they answer"* being exactly the mechanism this decision makes the authority.
**`AuthorizationProjection` and `AuthorizationView` are unchanged.** **And in one further normative
limb, which the field list forces and which no other clause of §11 can absorb: the listing's
per-member phrasing.** §11's surfaces clause obliges the listing to render *"each coverage member as
*this argument is fixed at that value* or *this argument is bounded by that limit* together with the
span the user said"* — wording that names a key no member carries once §3 above lands, so a reader
holding it either invents an argument or renders nothing. **The listing renders each member by its
`kind`**: *this kind of value is fixed at that value*, or *this kind of value is bounded by that
limit*, the `BoundKind` naming what the act constrained where the argument key used to. **The span
clause, and every other item that sentence lists** — the goal's statement, the declaration's
`VisibleIdentifier` and description, the expiry, the live-or-lapsed flag, the `PROPOSED` exclusion
and the renders-no-internal-value bar — **are untouched**, and so is the revocation surface.
**Every other clause of §11 binds entire**: the rendered-from-the-proposed-row rule and its restart
recovery, the possibly-empty coverage, the one-carrier-for-both argument, the rest of the rendering
bar, and `TurnOutcome.authorizations`. **And every remaining sentence of §11 that words itself over
an argument is unmarked reason beside a mark** (ADR-0089 §3) and **takes no scope of its own**,
reading over the kind as §1's illustration does: `TurnOutcome.authorizations`' *"two rows of one act
may carry different bounds for an argument of the same name"*, the one-carrier paragraph's *"three
facts about a member — the argument, the fixed value or the bound, and the user's own words"*, the
empty projection's *"fixing no argument because the call carries none"*, and the revocation
paragraph's *"what the act fixed about the arguments"*. **None of them is the rule it sits beside,
and this decision moves none of those rules.**

**ADR-0254 §16 — in its `core`-surface roster, in three limbs.** It states that `core/types.py`
gains *"**thirteen** types"* and *"**five** fields"*, and rules separately that
*"**`PermissionDecision` gains no field**"*. §7 above adds a **fourteenth** type, `BoundedArgument`;
a **sixth and a seventh** field, `ToolDefinition.bounded_arguments` and
`ActionRequest.intended_action`; and **one field to `PermissionDecision`**. A reader holding only
§16 implements a roster test that fails on this decision's own surface and — on the third limb —
records a decision that cannot distinguish two requests differing only in the act they are attempts
at, the one value the coverage was proved through. **§16's stated ground for that refusal is
honoured rather than contradicted**: it declines `ActionRequest.goal` because the trail *"has no use
for a value it cannot compare against the arguments"*, and an intended action is exactly what
selects the quote the arguments were compared against. **Every other clause of §16 binds entire**:
the lane attribution of every roster entry, the `core/protocols.py` and `core/errors.py` rosters,
*"`core/config.py` gains nothing at all"*, the `PROTOCOL_VERSION` clause and the
transcribe-the-ruling-whole rule, which is how `intended_action` reaches the record.

**ADR-0254 §20 — in its arm enumeration, scoped by a decidable test and not by a list, because three
review rounds each found a list incomplete.** §20 obliges its lanes to ship the seventy-one arms
enumerated under it; **Lane 1 has landed, so its arms are tests in the tree, while Lane 3's are
the arms of a lane in flight and Lane 2's are unwritten**. **The scope is
every arm whose statement an implementation of §§3-7 above cannot satisfy, and six mechanisms decide
it** — the test is applied arm by arm by the lane that owns the arm, and **no enumeration here is
closed or relied on as one**; the arms named are examples. **(i)** A member *naming an argument*, or
condition 6 read over **key sets** (arms 8, 47, 53, 54). **(ii)** A bound's `currency_argument`, or
the cross-member refusal that a `fixed` member naming it equals the bound's `currency` (arms 10,
18). **(iii)** A row carrying two members of one **kind**, or a `fixed` value the kind validation
now refuses (arms 1, 7, 14, 48). **(iv)** A `MONEY` member treated as **met without a quote**, or
`ResolutionRule`'s closure at three (arms 31, 34, 44, 45, 46, 49, 57, 66, 67, 70). **(v)** A
**path-(iii) opening act carrying a member §4 mints**, which §4 forbids (arms 64, 65). **(vi)** An
act that would need **`STATED_BOUND`** — one stating a **money bound** — whose own recorded words
§4's four-form table does not match, so it mints nothing at all: *"make it up to eighty"*, *"you may
spend up to fifty pounds on this"* (arms 15, 20, 39, 57, 64, 65). **It reaches no act a ratified
resolution mints**: arm 14's *"actually, make it Sunday"* is `DATE_FROM_CONTEXT`'s and arm 47's
*"add insurance"* is a term, and §4 leaves both readings untouched, so neither act is rewritten and
arm 14's date member, its basis and its Sunday request stand exactly as stated. **The disposition is
stated per mechanism rather than asserted of all.** For (i)-(iv) and (vi) the property each arm
demonstrates is unchanged and only the value or act it is stated over moves — the lane restates the
act in a form §4's table carries, or supplies the quote — and **no arm is dropped**. **Where the
value that moves is a quote the arm moves lane with it**: mechanism (iv)'s arms split at their
covered limb, L1 and L2 shipping the **uncovered** half — arm 45's GBP 80 `CONFIRM`, arm 46's
failing member, arm 67's negatives — and the **covered** half riding with the quote decision (§11),
no lane here being able to make a `MONEY` member met. **For (v) it is a supersession outright**: arm
64's *"a row is written `ESTABLISHED` … with no `CONFIRM` put at all"* and arm 65's *"never asked to
repeat the bound"* do **not** survive for a member §4 mints, since that member is proposed and
settled by an answer (§4). **What survives of arms 64 and 65 is named rather than left to
inference**: their whole structure stands for an opening act minted by §10's **three ratified
resolutions**, untouched here — the `TurnOutcome.authorizations` announcement and its empty case,
the listing and revocation, the not-constructible empty-coverage row, the round-trip, the
no-second-path-(iii)-row clause, the ADR-0250 §6 safeguard and arm 65's recipient-grant negatives.
**What does not survive at all is arm 64's two-declaration case** — *"up to fifty pounds for the
train and a hundred for the hotel"* — which one member per kind now mints nothing from, and which
§9's §1 entry above already records. **And the arms the sweep cleared, with the ground**: **arm 5**
stands verbatim, `maximum_exclusive` defaulting to `False`; **arms 21 and 35** state negative
assertions that stay true under `CoverageView`'s new field; **arms 6, 11 and 12** test §4's
readings, unmoved; and `TERMS` and `PERIOD` members stay **constructible**, §2 admitting a kind and
§4 minting none being two different things. **§20's lane cut, its wire clause and its dependency
clause bind entire.**

**ADR-0016 §1 — in one scope**, and it is the scope ADR-0254 §18 already took there reaching one
further field: the model declaration, and the required-field clause applied to `bounded_arguments`
alone. **The grounds are stated exactly, the obvious one being false**: the empty tuple does not
make the opposite claim in every direction, the argument route being an **additional** safeguard
over a bound the quote already proves — so a declaration declaring nothing keeps the primary proof
and forgoes only the second check, at the recorded cost that an amount-bearing argument nobody
declared is compared against no member. The exception is taken because requiring the field would
oblige every declaration and fixture in the tree to write `()`, and because a required field would
refuse every `PermissionDecision` written before it. **The exception is this one further field on
this one argument**, and every other clause of §1 binds entire.

**And the ones that come out no, deliberately.** **ADR-0255** takes **no** record: §15 item 19's
gate enumeration is untouched, because §4's proposal rule closes the span-polarity residual at the
**assent** rather than containing it at a gate, and no other prerequisite this decision raises
belongs to that gate. **ADR-0249** takes **no** record: this decision adds no field to `Goal` and
none to `GoalElement`, and §7 of it is relied on rather than narrowed, §4's refusals being refusals
of **this** decision's own reading rather than changes to it. **ADR-0252** is read and **not
moved**: §1's no-content rule, its two bases and verdict vocabularies, §6's four tests, §7's
conflict rule, §11's digest and §§12-13 are untouched, and §6 records why the carrier question is
the booked decision's. **ADR-0253** is superseded in nothing: this decision adds no field to
`PlanStep` and reads `PlanStep.intended_action` as ADR-0265 leaves it. **ADR-0265** is relied on
entire — `IntendedAction` and its `id` as that decision leaves them, its *"no fourth field"*
closure included, and §11 makes L2 wait on its landing rather than anticipating it. **ADR-0254
§13** is the clause §7 is taken under, its *"Coverage and sufficiency are two tests and neither
clears the other"* staying true. **ADR-0021 §1** is relied on for the one canonical encoding;
**ADR-0145 §2 and §9** for the hazards §7 avoids; **ADR-0029 §5** is relied on rather than
superseded.

### 10. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling, and
> each carries the condition that fires it.

- **Where a quote is carried, what records one, and how a policy obtains one — the whole of the
  quote's machinery.** §6 states the four facts §7 reads and no carrier: no type, no field of any
  model, no store member, no Protocol, no bound, no expiry and no rule about which component mints
  one. **Nor whether a quote is still true when the
  act is performed**, nor what freshness wiring a consequential capability through this route
  therefore requires. **This is the largest thing this decision does not settle**, and until it
  lands §7's evidence route has no operand: every `MONEY` member is unmet, §1's completeness
  condition proposes no row, and **ADR-0254 §20's Lane 2 is briefed after that decision** (§11).
  **It also owns what makes a quote measure the whole charge** (§6): a declaration naming a fee
  where the charge is produces a quote satisfying a ceiling the act breaches, against which
  **declaring the argument at `MONEY` is this decision's optional safeguard** (§7). Fired by **the
  quote decision**, issue **#2387**, which carries §6's constraint that a quote is a second copy of
  what was read.
- **The system-supplied argument, in two respects.** **Who supplies its value**: ADR-0254 §3
  requires `orchestration` to, and this decision states one source and lands no filler — a value
  supplied as a spending safeguard is the member's own `maximum` (§7), and `bounded_arguments` and
  `system_supplied` being disjoint, no such fill is constructible today. `PlanStep.id` is
  **refused** as the client reference: `_step_ids_are_unique` guarantees uniqueness *"within a
  plan"* alone. **And which such keys are per-call identity rather than inputs a price depends on**:
  §3's three examples are not one kind — an idempotency key is identity, a **locale** is a price
  input — and **this decision draws no line, so §6 excludes nothing from the digest**, at the cost
  that a declaration filling any of them is covered by no quote and asks. Fired by the decision that
  mints an opaque per-call reference, and by the one that classifies such a key.
- **What pins an *undeclared* user-facing argument to the user's own act, beyond the quote's
  digest.** §7's third conjunct proves the call is the one **quoted**, not that the user chose each
  quoted argument, and `IntendedAction` cannot close the gap — ADR-0265 §1 gives it *"no fourth
  field"* and so no parameters. So a replan changing an undeclared argument the user never spoke to
  is covered where its re-quote is inside the ceiling. **That is the owner's ruling of 2026-09-14
  applied rather than a slip in it** — *"Location/time arguments need no declaration"* — with the
  ceiling still binding what such a call may cost and §7 refusing it the lineage discharge. Fired
  by the decision that gives an intended action a parameter identity.
- **What a confirmation renders about a charge, and what an approval given without one covers.**
  Where no quote governs, condition 6 fails, route (d) covers nothing and route (a) asks — and the
  question the user answers carries the tool and the parameters and **no price**, no clause of this
  or any ratified decision rendering one. So an approval there is an approval of a call whose charge
  the user was not shown, and **the ceiling they stated is proved against nothing**; it authorises
  that one call and establishes no standing authority (§4), and this decision makes it no worse.
  Fired by **the quote decision** (#2387), which lands the carrier a confirmation could render.
- **Whether a standing authority is scoped to one intended action.** ADR-0254 §3 keys a row on the
  **goal** and the **declaration** and this decision leaves conditions 1-5 entire, so a ceiling
  confirmed while one intended action was being quoted covers a **second** act of the same goal
  through the same declaration whose own quote sits under it. **That is the ratified keying rather
  than a hole this decision opens**: §7 proves each call against a quote taken for **its own** act,
  so no act is authorised above the bound, and §5 admits one money ceiling per goal or none. What
  is not bounded is the **sum** of two such calls, which is ADR-0254 §14's no-spend-ceiling clause.
  Fired by the decision that gives an `Authorization` an action scope — which would supersede §3's
  conditions 1-5 and add a field to a ratified stored type — or by one stating a budget over a goal.
- **A stated floor, a negated ceiling, and every other form the table does not carry.** §4's four
  forms are the whole reading, so *"at least 150 euros"*, *"never spend over 100 euros"* and *"no
  more than 100 euros"* mint nothing and the act asks. **A negation is an
  inversion a rule would have to perform on the user's behalf**, and every rule that tried was found
  wrong in the next round; a **floor** additionally needs a fact neither the span nor the kind
  carries, telling a bound on what the user **pays** from one on what they **receive**. Fired by the
  decision stating the wider reading with its own totality argument, and for a floor by the one
  stating what a floor is proved against.
- **Minting a `TERMS` member from an act, and minting a `PERIOD` one.** §4 mints neither, so a
  term the user named and a period they gave are covered by nothing and every call resting on one
  asks. **The ground is §7's rather than a judgement about polarity**: a quote states a price and
  nothing else, so a member of either kind could be proposed and never **met**, and §1's
  completeness condition would refuse it. Fired by the decision that gives such a member something
  to be proved against, and for `PERIOD` additionally by the reader that turns *"Sunday"* into a
  half-open interval, which **owes ADR-0254 §8's two-zones rule**: such a member's `timezone` is the
  configured zone as the act's turn read it, never the resolution's own record of it.
- **A `FROM_SHOWN_RECORD` basis for a coverage member**, which needs an element carrying both a
  span and the record its reference resolved to, and ADR-0249 §1 admits none. Fired by the
  decision that gives an element that shape.
- **Any other widening of §4's reading** — a currency it does not name, another language, a figure
  written in words, a bound on a count; **a fourth `BoundKind`**; and **which of two constraints of
  one kind the user meant**, which §5 refuses rather than choosing. Each fired by the decision
  stating the wider reading and its own totality argument.
- **What the verification phase does with a quote, and coverage's other conditions.** The owner's
  ruling makes the actual charge confirmed after the act and a mismatch *"a reported finding"*;
  **no clause here verifies anything, compares a charge, or writes a finding**, and
  `AttemptPhase.VERIFY` is A10's by ADR-0255 §17's assignment. ADR-0254 §3's conditions 1-5, §7,
  §12's ladder as ADR-0256 §1 leaves it, and every clause of §11 but `CoverageView`'s field list
  and the listing's per-member phrasing are likewise untouched. Fired by A10, and by the
  decisions those clauses already name.

### 11. The lane cut, and the arms this decision owes

> **Normative.** This decision is implemented in **two lanes and no third**: **L1**, the contract in
> `core/types.py` **together with the comparison in `permissions`**; and **L2**, the mint in
> `orchestration`. **L1 is two packages and it is one change**: `permissions/_coverage.py` and
> `permissions/goal_authorizations.py` read `CoverageMember.argument` and
> `ValueBound.currency_argument`, L1 removes both, and **no compatibility representation is
> available** (ADR-0084 §3's exact-match posture), so a tree carrying the new shape beside the old
> comparison conforms to nothing — ADR-0252 §17's shape for a contract lane whose consumer the
> change forces. **No lane wires a consequential capability** (ADR-0254 §17 as ADR-0255 §13 leaves
> it) and **no lane writes an `Authorization`**. **The bullets below assign each lane its surface
> and its arms, and no lane is complete without what it is assigned there.**

> **Normative — the wire moves, the export does not, and the stored shapes are read rather than
> assumed.** **`PROTOCOL_VERSION` moves by exactly one, in L1**, and `wire/envelope.py`'s log
> gains an entry naming this ADR and the reason: `ToolDefinition` gains `bounded_arguments` and a
> declaration crosses the promoted surface **inside a `PermissionDecision`**, that model sets
> `extra="forbid"` and `wire/codec.py` renders a model by `model_dump()`, so a defaulted member is
> still a shape change. **`PermissionDecision` gains `intended_action`** — a second ground for the
> same one bump, and **there is no third**. **`CoverageView` gains `kind` and loses `argument`, but
> that earns no ground of its own here**: it crosses a frame only inside a `Confirmation`, which
> ADR-0254 §20's **Lane 3** lands and no merged tree carries, and L1 is briefed above that lane
> (below), so the field change rides L1's single bump rather than adding to it. **`ActionRequest`
> itself crosses no frame**, ADR-0254's own Lane 2 entry stating that ground, so the request's own
> field adds nothing further either; and **`PlanExport` gains no
> member and `schema_version` does not move**.
>
> **No stored row is migrated, edited or dropped, and the reason is a fact about the tree rather
> than a claim about the shape.** `CoverageMember` is a **stored** value riding inside an
> `Authorization`, so losing `argument` would be a breaking decode for any row that held a member.
> **No row holds one**: `orchestration/authorizing.py` sets `coverage=()` on every row it builds
> and proposes none at all for a request carrying a user-facing argument, and no `CoverageMember`
> is constructed in `src/` outside the canonical fake. An empty tuple decodes identically, so
> **L1's change reaches no stored member and no lane writes a migration, an inert representation
> or a repair**; a `ToolDefinition` written earlier decodes with `bounded_arguments` empty; a
> stored `PermissionDecision` decodes with `intended_action` `None`, which `authorises` then
> matches only against a request carrying none, the fail-closed direction; and **no stored
> `CoverageView` exists to migrate**. **L1 re-takes that reading at its own base and states what
> it found**; were a row to hold a member by then the lane stops.

- **L1 — the contract and the comparison** (`core/types.py` and `permissions`).
  `CoverageMember`'s `kind`, its kind-validated `fixed` and the removal of `argument`;
  `ValueBound`'s `maximum_exclusive` and the removal of `currency_argument`;
  `ResolutionRule.STATED_BOUND`; `BoundedArgument` and `ToolDefinition.bounded_arguments`;
  **`CoverageView`'s `kind` in place of its `argument`** (§9) — the one member of this list Lane 3
  must have landed first, and the whole reason L1 is briefed above it (below);
  `ActionRequest.intended_action` and
  **`PermissionDecision`'s transcription of it with `authorises`' sixth conjunct** (§7);
  `PROTOCOL_VERSION` with `wire/envelope.py`'s log entry; and §7's two routes, its condition 6 and
  its lineage narrowing in `permissions/_coverage.py`. **L1 and L2 between them restate every
  ADR-0254 §20 arm §9's six mechanisms reach, each in the lane that owns it, dropping none — except
  the covered limbs of mechanism (iv)'s arms, which ride with the quote decision because no lane
  here can make a `MONEY` member met (§9).** **The evidence route is implemented and is met by no
  quote**, this decision landing no carrier — so every `MONEY` member is unmet and the act asks.
  **`core/protocols.py` is not touched**, so no triad is owed. Arms 2(b), 3(b), **3(c)** — which is
  L1's because it is taken over the store and the projection and drives no proposal — 4(a), 6(a)'s
  no-quote limbs and 6(b).
- **L2 — the mint and the request builder, in `orchestration` alone.** §1's candidate selection,
  §2's act and its four refusals, §4's reading, its refusals and its path-(i)-only rule, and §5's
  one-per-kind refusal and goal-only read; **and setting `ActionRequest.intended_action` from the
  `intended_action` of the plan step the request serves, on every construction and resume path** —
  `orchestration/runner.py`, `reads.py` and `parked_reads.py` build one today — which is ADR-0254
  §6's own pattern for `ActionRequest.goal` one field over: *"`orchestration` sets it from the plan
  the execution names; no policy, no seam, no interface adapter and no model output writes it"*.
  **L2 therefore waits on the lane that lands ADR-0265 §1's `PlanStep.intended_action`**; where that
  field is not yet in its base, L2 is not briefed. Arms 1(a), 2(a), **3(a)'s mints and refusals**,
  4(b) and 7.
- **And one lane this decision does not cut.** The **quote decision** (§10, #2387) lands the
  carrier, the producer and the read, and wires them into §7's evidence route. **Arms 1(b), 5 and
  6(a)'s with-a-quote limbs are shipped there**, against that decision's carrier and never against a
  double standing in for it — **and with them the covered limbs of every ADR-0254 §20 arm §9's
  mechanism (iv) reaches**, arm 45's GBP 50 `ALLOW` among them, **and arm 2(b)'s quote half**.

> **Normative — L1 is briefed after ADR-0254 §20's Lane 3 lands, L1 lands before L2, both are
> briefed on this decision alone, and ADR-0254 §20's Lane 2 is briefed after the quote decision
> (§10) rather than after these two.** **Lane 3 lands `CoverageView`, `AuthorizationProjection`,
> `AuthorizationView`, `Confirmation.authorization`, `TurnOutcome.authorizations` and
> `AssistantEngine`'s two members exactly as ADR-0254 §16 and §11 ratify them, `CoverageView`'s
> required `argument` included** — a lane implements ratified text and never a `Proposed` ADR, so
> **nothing in this decision is Lane 3's to carry** and Lane 3 is briefed and reviewed without
> reference to it. **§9's §11 scope is a supersession of ratified text and stands whole from this
> decision's own ratification; its implementation is L1's, above Lane 3's tree**, which is where
> `argument` becomes `kind` and where the projection arms below are demonstrable at all. **Where
> Lane 3 is not yet in its base, L1 is not briefed** — the same shape as L2's wait on
> `PlanStep.intended_action`, one lane earlier. Neither lane
> reads a quote and **every tree either leaves is conforming and fail-closed** (ADR-0084 §3). But
> **no row carrying a non-empty `coverage` is usefully written until the quote decision lands a
> carrier**, and the arithmetic is stated here rather than discovered by that lane: §4 mints only
> `MONEY` members, §7 needs the evidence route for every one, L1's is met by nothing, so §1's
> completeness condition fails and path (i) proposes no row — its own disposition, the one call
> asked by route (a). **#2373 is unblocked by the two decisions together, not by this one alone.**

> **Normative.** **The two lanes ship the arms §11 assigns them, of the seven below, each over
> controlled fakes, and no lane is complete without the arms it is assigned.** **No arm assigned to
> a lane here asserts anything that lane's own tree cannot produce** — which is why the proposal an
> answer settles is nobody's here (arm 3), and why every with-a-quote limb rides with the quote
> decision. Every arm states a correction as a **subsequent turn**, on the owner's sequencing ruling
> of 2026-09-13, and none is demonstrated against a live integration.

1. **A stated ceiling, end to end.** **1(a):** a goal whose current interpretation carries a
   `USER_STATED` constraint with span `"up to 150 euros"` mints exactly one member — `kind`
   `MONEY`, `maximum` `Decimal("150")`, no `minimum`, `currency` `"EUR"`, `resolution`
   `STATED_BOUND`, basis naming the revision's `raised_by` and that span — and **no second member
   of any kind**; and the same span as a **proper part** of a longer utterance mints the **same**
   member, nothing outside it being read. **1(b):** against a quote for the request's
   `intended_action` at `"120"`/`"EUR"` over the request's own arguments, the request is covered;
   at `"170"` it is not; **at `"120"`/`"USD"` against an `EUR` member it is not**, the currency
   conjunct being read at the quote's own currency and an amount never compared without it; and
   with **no** quote for that action it is not covered however small the declared arguments are.
2. **Kind agreement and not numeric fit — the review's own case.** **2(a):** a constraint with span
   `"4 stars"` mints **no member at all**, matching no form of §4's table. **2(b):** a `TERMS`
   member constructed directly — the shape a later decision will mint — is met by a `MONEY`-declared
   argument in no case whatever number it carries, and a `MONEY` member is met at a `TERMS`-declared
   argument in none. **Its quote half rides with the quote decision**, there being no quote in
   either lane's tree to be unmet by (§11).
3. **Only ceilings, the endpoints, and what a mis-chosen span actually produces.**
   **3(a) mints**, the element's span being the string given: `"under 100 euros"` → `maximum` `100`
   **with** `maximum_exclusive`; `"at most 100 euros"` → the same without it; `"up to 150 euros"` →
   an inclusive `maximum` of `150`; `"Under 100 Euros."` and `"under 100 euros!"` → the first of
   these, case and **one** trailing stop or bang normalising away; and `"under 100 euros!!"`,
   `"under 100 euros.."` and `"under 100 euros.!"` mint **nothing**, exactly one trailing character
   being trimmed. **3(a) mints nothing from a question** — `"under 100 euros?"` and `"Under 100
   Euros?"` each carry a `?` and are refused before any other step — **and nothing** from `"at least
   150 euros"`, `"more than 150 euros"`, `"over 150 euros"`, `"never spend over 100 euros"`, `"no
   more than 100 euros"`, `"not over 100 euros"`, `"not exactly 100 euros"` and `"never spending
   over 100 euros"`, none being a form of the table; **and nothing from `"up to fifty pounds"` or
   `"under one hundred euros"`**, a figure written in words being no decimal figure §4's reading
   accepts. **And 3(a) mints the same member from a mis-chosen span as from a well-chosen one**: the
   span `"under 100 euros"` of `"avoid booking hotels under 100 euros"` and of `"avoid these prices
   — under 100 euros"` each mint a `MONEY` ceiling of `100`, nothing outside the span being read,
   and **no path-(iii) opening act carries a `STATED_BOUND` member in any case**. **3(c) — what that
   member then does, and it is stated over the store alone rather than over a proposal**: a row
   carrying that member, recorded **`PROPOSED`**, is written and read back carrying it entire; a
   `DECLINED` settlement establishes nothing and leaves **no row of that goal and declaration
   `ESTABLISHED`**; an `ESTABLISHED` settlement establishes exactly that member. **Its projection
   half is L1's too and is demonstrable only above Lane 3's tree** — that a `CoverageView` built
   from that row carries the bound **beside that span** — which is what §11's dependency clause
   briefs L1 above. **3(c) drives no proposal through `orchestration` and asserts none**,
   because §1's completeness condition proposes no row while no `MONEY` member is met (§11) — **the
   end-to-end proposal, its question and its answer are ADR-0254 §20's Lane 2's**, after the quote
   decision, and this decision claims them for no lane of its own. **3(b):** against an exclusive
   `maximum` of `100` a value of exactly `"100"` does **not** satisfy and against an inclusive one
   it does. **Both halves are parameterised over the whole of §4's closed reading and not over its
   illustrations** — every one of the four forms, every currency word and symbol in **both** orders,
   mixed case, runs of **every ASCII whitespace character** — space, tab, newline, carriage return,
   form feed and vertical tab — against a non-ASCII space that is **not** collapsed, and `99.50` as
   well as `100`.
4. **One member per kind, and the exclusivity ordering at an equal ceiling.** **4(a):** an
   `Authorization` carrying two `MONEY` members is not constructible and one carrying a `MONEY` and
   a `TERMS` member is; and against a live row whose `maximum` is `100` **without**
   `maximum_exclusive`, a path-(ii) correction to the same `maximum` **with** it is written as a
   narrowing, while the reverse is **refused as a widening** — no row written and no standing
   route, the refusal naming path (i) in its own reason. **The asking there is `orchestration`'s**
   (ADR-0254 §5), and no arm here drives it. **4(b):** a goal carrying two `USER_STATED`
   constraints that each read as `MONEY` mints **neither**, and one carrying a money ceiling
   beside a constraint no reading mints still mints the ceiling.
5. **The arguments are the ones quoted, the governing quote is the latest, and the worked case.** A
   request whose arguments equal the quoted ones is covered; one carrying **one extra** argument,
   one **missing** one, and one whose value differs are each **not** covered though the price is
   unchanged; a request whose `intended_action` names a different action, and one carrying **no**
   `intended_action`, are covered by no quote; a **system-supplied** argument whose value differs
   between the quoted arguments and the request leaves the request **not covered**; and the Sunday
   re-quote covers the Sunday arguments while the Saturday quote covers neither. **An earlier quote
   never revives**:
   with a Saturday quote at `120` and a later Sunday quote at `170` recorded for one action, a
   request returning to the **Saturday** arguments is **not covered** — the Sunday quote governs
   and its digest differs — and the act asks. A `PERIOD` and a `TERMS` member are met by **no**
   quote whatever it carries; and a failing read leaves the request **not covered with the fault
   reported**, never as an absence of quotes.
6. **A filter is not a charge, and an undeclared argument needs no declaration.** **6(a):**
   against a declaration declaring `price` `MONEY` with `currency_argument` `"currency"`, a request
   satisfying that argument but covered by **no quote** is **not** covered; with a quote it is; and
   a request whose declared argument exceeds the bound is not covered though the quote is inside
   it; and a request whose `currency` key differs from the member's `currency` by one byte is
   **not** covered on that route, against a control differing only in that key. A declaration
   declaring **two** `MONEY` arguments meets no `MONEY` member on that route, and one declaring
   **none** is covered through the evidence route with its site and date arguments declared
   nowhere. A row whose every member is met on the **argument** route does **not** cover a request
   carrying a user-facing argument the declaration declares at no kind — the `send_message` case —
   and a request carrying `planned_with_external_content` whose coverage the evidence route
   supplied is **not** discharged of ADR-0181 §5's floor. **The `currency_argument` exemption is
   conditional and is demonstrated so**: a request carrying `currency` and **no** `price` is
   **not** covered by an empty row, nor is one carrying `currency` where the row holds no `MONEY`
   member, and two such requests differing only in `"EUR"` versus `"USD"` are **both** uncovered —
   while one carrying `price` and `currency` whose `MONEY` member is met against them **is** exempt
   of the currency key and covered. **6(b):** a declaration is **not constructible** where a
   `BoundedArgument` names a key of its own `system_supplied`, where two name one `argument`, where
   a `MONEY` one carries no `currency_argument`, where a `PERIOD` or `TERMS` one carries one, or
   where `argument` equals `currency_argument`; a `ValueBound` is not constructible where
   `maximum_exclusive` is set beside an absent `maximum`; and a `CoverageMember` is not
   constructible carrying a `MONEY` `fixed`, a `PERIOD` or `TERMS` `fixed` that kind's reading
   refuses, or a `bound` whose `kind` differs from the member's — **every unequal pair of the three
   kinds**, beside one equal pair of each that is. **And `PermissionDecision` carries the act it
   was taken for**: `from_request` puts the request's `intended_action` on the record, and
   `authorises` refuses two requests differing **only** in it — the decision's own value against
   another, and a request carrying one where the decision carries `None` — while a `CoverageView`
   is constructible at each of the three kinds and at none without one.
7. **The mint reads the goal alone, the three refusals, and the discard.** The same goal mints
   the same members against two different requests, two different plans and two different
   declarations — including one declaring nothing; an element whose `id` is `None`, one whose
   carrying revision's `raised_by` is `None`, and one on a goal whose `interpretation_elided` is
   non-zero and whose oldest **retained** revision is its earliest carrier each mint nothing —
   **while a goal whose `interpretation_elided` is non-zero and whose oldest retained revision
   does *not* carry the element mints it normally**, the retained predecessor proving the
   carrying revision is the first; and
   a `PlannerOutput` whose envelope carries **every value §8's discard list names** — a
   `CoverageMember`, a `ValueBound`, an `AuthorizationBasis`, a `BoundKind`, an argument key and a
   `BoundedArgument` — leaves the recorded revision and the minted coverage **byte-identical** to
   the same envelope without them, with the turn completing and not failing. **And the request
   builder is exercised rather than a hand-built request**: `orchestration` sets
   `ActionRequest.intended_action` from the plan step the request serves on every construction and
   resume path, a step carrying none yielding a request carrying `None`.

### 12. This ADR classified, marked, and how it is ratified

**A reader acts differently, so this is a decision and not a clarification.** A reader holding the
corpus without it can write no row carrying a non-empty `coverage`, and would either leave ADR-0254
§20's Lane 2 stopped where #2373 stopped it or invent an association no clause authorises — the
standing authority §9 clause (ii) exists to prevent (ADR-0070 §1). **It is a partial supersession of
exactly two documents** (ADR-0070 §3) — ADR-0254 in **twelve** scopes and ADR-0016 in **one** — and
the `Status` line of each names its scopes **without an `ADR-NNNN` token inside the parentheses**,
so ADR-0070 §4's extraction invariant holds. **The twelve were found by one sweep and not one review
round at a time**, and §9 records with its ground each clause the sweep examined and **cleared** —
§6's bar, §11's `TurnOutcome.authorizations` reason, and §20's arms 5, 6, 11, 12, 21 and 35. **The
records land in the same change as this document** (ADR-0082 §7), and nothing else in either is
edited — no Decision text is rewritten, which ADR-0070 §1 forbids.

**This ADR is marked** under ADR-0089: every obligation it imposes is a `> **Normative.**`
blockquote at column 0 stating its own scope, unmarked text beside a mark supplies no obligation of
its own but is read to settle what a mark means (§3), and quoted marks from other ADRs appear inside
quotation marks in running prose. §11's lane bullets and arms are that unmarked content, read under
marks stating the count, the one-subsystem rule and the no-lane-is-complete rule — ADR-0265
§§9-10's own shape. **It is a
contract-surface change** — `CoverageMember`, `ValueBound` and `CoverageView` change shape,
`ResolutionRule` gains a member, `BoundedArgument` is added, and `ToolDefinition`, `ActionRequest`
and `PermissionDecision` each gain a field — so it owes **both** review lenses on one tree, which
ADR-0015 §1 makes true of a prose-only PR. `core/protocols.py` is **not** reached, so no Protocol
triad is owed. **It merges as its own PR, ratified, before anything implements against it**
(golden rule 5); §11's lanes are briefed after it merges, and the ratification flip is one line
and no other byte (ADR-0165).

## Consequences

**What becomes possible, and when.** L1 and L2 land the member, the mint, the settlement and the
comparison, so the rule #2373 stopped for exists. **What they do not by themselves make writable
is a row carrying a non-empty `coverage`**: §4 mints only `MONEY` members, §7 needs a quote for
every one, and §1's completeness condition therefore proposes no row until the quote decision
lands a carrier — fail-closed, and §11 states the arithmetic rather than leaving ADR-0254 §20's
Lane 2 to find it. Once that carrier lands, a ceiling the user stated is **confirmed once, in the
authorisation phase, beside the words it was read from**, and then covers every later call whose
quote sits under it **at a tool that declares nothing about money at all**; *"make it Sunday"* is
answered by a re-quote rather than a second question — the owner's *"a price change within an
approved limit should remain covered"*. A declared money argument is an **additional** comparison
and never a substitute, and the cost is that **an act with no quote is not covered and the user is
asked**, which the owner names as feasibility rather than restriction.

**What becomes harder, and every part of it is a question asked rather than a call authorised.** A
request carrying any argument the declaration declares at no kind is covered only through the
**evidence** route, so a tool with undeclared arguments and no quote asks on every call — the price
of keeping *"no omission reads as consent"* once arguments stop being named by members. The digest
excludes nothing, so a quoting read and a booking differing by any key, **a system-supplied one
included**, never match; **an earlier quote never revives**; and **§4 reads four forms in one
language and only ceilings**, so a floor, a negated ceiling or a figure in words mints nothing.

**What is no longer a residual, and it is the one this document spent eleven rounds on.** A span a
model chose wrongly used to be a standing authority the user never gave, and four parsing rules
each closed one instance and left the class open. **It is closed here by the mechanism ADR-0254 §1
already ratifies**: a span mints a `PROPOSED` row, the user reads the ceiling **beside their own
words** before answering, and a wrong polarity is declined rather than established — at no cost in
questions, since §1 writes the row before the question either way. That is why this decision takes
no record against ADR-0255's wiring gate. **Three residuals are stated rather than closed and §10
books each**: a replan changing an undeclared argument beside the one the user spoke to is covered
where its re-quote is inside the ceiling; a route-(a) approval given with no quote is an approval
of a call whose charge nothing rendered; and a ceiling is scoped to the goal and the declaration,
so a second act of that goal under that declaration is covered by it.

**These are the cases that would falsify the design.** A deployment whose users state bounds in
forms the table does not carry — negated ceilings above all — so the reading mints nothing and
every act asks; the practical falsifier by a distance, and the one to measure first. A quoting read
and a booking whose argument sets differ by a key. Users who decline the proposal as often as they
accept it, which would say the reading is wrong rather than that the confirmation is working. A
declaration whose sole `MONEY` argument is an amount the user **receives**. And a quote decision
settling on a carrier these four facts cannot be read off.

## Alternatives considered

**Keeping the argument key on the member, and deciding the argument at the comparison.** The first
two drafts. Round 1 blocked the first correctly: a value that **fits** an argument is not one the
act's words **bear on**, so *"4 stars"* minted a price ceiling, and no selection rule available at
the mint could satisfy ADR-0254 §9 clause (ii). Round 2 blocked the second, and the owner's ruling
says why in one sentence — *"the price is usually a consequence of the chosen params, not an
argument"* — so a design that could only compare arguments refused every booking whose price is not
a parameter.

**Deciding the quote's carrier and its producer here.** The draft this one was cut from, declined
on cost rather than on correctness. A quote record, its place on the `Goal`, its bound and
elision, the declaration field naming which output a price is read at, a plan-store member, a
Protocol and a gate prerequisite for freshness made the document supersede **four** documents and
maintain seven synchronised statements of its own contract; ten review rounds at churn 5.1 went on
the carrier while the rule stayed three paragraphs. §6 makes the seam explicit instead: four
facts, an interface, and no carrier. **Carrying the quote on a `GoalEvidence` row** — the shape the
owner's ruling names — is likewise not decided here: ADR-0252 §1 makes it hard, such a row
*"carries no content"* and a quote is a second copy of what was read, and that is a finding about
the carrier handed to the booked decision as a constraint rather than answered.

**Establishing a bound from the span alone, and narrowing the reading until no wrong span could
establish one. There were four narrowings and none closed the class at an acceptable cost.** A
closed negation vocabulary; then a bar on any negation before the span; then a whole-**clause**
requirement; then a requirement that the span **equal** the act's whole recorded utterance. Review
found a new instance in eleven consecutive rounds — *"not under 100 euros"*, *"under no
circumstances spend over 100 euros"*, *"avoid spending over 100 euros"*, *"avoid booking hotels
under 100 euros"*, *"avoid these prices — under 100 euros"* — and the reason never varied: **each
left text around the span that the rule had to understand and could not.** The fourth removed the
text rather than the misreadings and did close the class, but it made the owner's own *"Book
Riverside if it is dry Saturday, up to 150 euros"* mint nothing and ask the user to restate — a
user-facing restriction adopted for the system's convenience, which is not a trade this project
takes. **What closes the class without that cost is not a reading rule at all**: the member is
**proposed**, rendered beside the span, and established by the answer, so the one thing no rule
could see is settled by the only party who knows.

**Binding a coverage member to one intended action.** Declined as outside this decision's scope
rather than as wrong: it would supersede ADR-0254 §3's conditions 1-5, which key a row on the goal
and the declaration, and add a field to a ratified **stored** type. §10 books it with what fires
it, and states why the gap is narrow — §7 proves every call against a quote taken for **its own**
act, so no act is authorised above the bound, and §5 admits one money ceiling per goal or none.

**A planner nomination of the (element, argument) pair, verified by code.** Declined because the
pairing is per *(element, declaration)*, so it cannot live on `GoalElement` and would have to live
on `PlanStep`, superseding ADR-0253's step enumeration and its seam and wire. **Asking the user to
confirm the association** is foreclosed by ADR-0254 §1, which writes the path-(i) row **before**
the question is put — and is not what §4 does: §4 confirms the **bound**, which the row already
carries, and nothing about which argument it fills. **Minting a `MONEY` bound from a bare figure**
was the first draft's rule and round 1 refuted it twice: the direction is in the user's words or
it is nowhere.
