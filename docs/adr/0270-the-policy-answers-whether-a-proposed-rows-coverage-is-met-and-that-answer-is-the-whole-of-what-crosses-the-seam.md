# 270. The policy answers whether a proposed row's coverage is met, and that answer is the whole
of what crosses the seam

- Status: Proposed
- Date: 2026-09-15
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **one scope, in §16's `core`-surface roster and in none of its other clauses**: `core/types.py`
  gains a **nineteenth** type, `CoverageAnswer`, counting from where the quote decision left that
  roster at eighteen types and twelve fields, and **no further field**. A reader holding only §16
  implements a roster test that fails on this decision's own surface. §16's `core/protocols.py`
  roster, its `PermissionDecision` clause, its `core/errors.py` roster, its
  *"`core/config.py` gains nothing at all"* and its wire clause are untouched, and §5 shows the
  working.
- **Partially supersedes** [ADR-0266](0266-a-coverage-member-records-the-constraint-the-user-stated-and-the-bound-is-proved-against-the-quote-for-the-intended-action.md)
  — **two scopes. §7's last normative clause, in the limb naming `ActionPolicy.decide` as the only
  site where condition 6 is taken**: the comparison is now taken at `decide` at every dispatch
  **and** at `ActionPolicy.coverage_met` before a row is written, over the one implementation §7
  places in `permissions`, which this member is the face of. **And §11's lane-ordering clause, in
  its Lane-2 limb alone**: that lane is briefed after the quote decision **and** after this
  decision's own lane. Every other clause of both sections binds entire, and §5 shows the working.
- **Partially supersedes** [ADR-0267](0267-a-quote-is-a-record-the-goal-holds-in-order-read-from-the-output-its-declaration-names.md)
  — **one scope, in §7's selection clause and in one limb of it**: the limb naming **the component
  that writes the row** as the selector and **that write's own read** as the source. The governing
  quote is selected by `permissions`, inside the answer to condition 6, from the read that answer
  was proved over, and the writer **records** it rather than selecting it. §2's order, the
  no-comparison rule, the write-once and never-edited rules, the absence rule over the three write
  paths and the whole provenance clause bind entire; §5 sweeps the five places the replaced reading
  is available and shows the working at each.

## Context

### Where this comes from

Issue **#2401**. ADR-0267 §10 books it by name — *"The gap is ratified ADR-0266's, booked there as
an amendment at #2401 — a Protocol member answering, for a concrete request and a proposed row's
coverage, whether that coverage is met — which widens a `core` Protocol and so owes its own ADR
merged first"*. This is that ADR.

### The gap this closes, stated as the failure the corpus has today

Three ratified rules meet, and nothing joins them.

- **ADR-0266 §7** puts condition 6's *"One implementation, in `permissions`"*, and restates
  ADR-0254 §1's completeness condition over it: *the row the proposal would write satisfies
  condition 6 for this request*.
- **ADR-0254 §15** rules that an `Authorization` is *"written and settled by `orchestration` and by
  nothing else"*, and **§1** makes a path-(i) proposal conditional on that completeness.
- **Golden rule 1** forbids `orchestration` importing `permissions`.
**No clause of either decision says how a component outside `permissions` obtains condition 6's
answer**, which is what ADR-0267 §10 records as not decided there.

So the proposal path is writable only by re-implementing the rule where it may not live.
`orchestration/authorizing.py::proposed_authorization` evaluates the completeness condition in
place today, and its own docstring records that it is *"only ever vacuous"* (#2373): a request
carrying any user-facing argument proposes no row at all. That is the fail-closed direction and
the ruled one while no member can be minted — but the moment a `MONEY` member can be met, which
ADR-0266 §7's evidence route and ADR-0267's quote together make true, the in-place evaluation stops
being vacuous and becomes a second implementation of a rule ADR-0266 places in exactly one
component.

### The second half of the same gap, which ADR-0267 §10 books beside it

That entry does not stop at the seam's shape. It also asks *"whether the row records the quote that
answered it"*, and states the cost of leaving it open: *"Until a seam returns the quote it read,
`quoted` and condition 6's operand are two reads and can differ"* where a refresh lands between
them. Both halves are one question about one seam — **what crosses it** — and §10 names this
amendment as what fires them, so a decision that answers the first and leaves the second standing
would answer half a booked entry and leave the window open for a later ADR to close by widening
this same member. The owner's own worked case is what makes that concrete: ADR-0266 §7's booking
renders *"the price as a figure or as a bounded limit with its currency"* beside the ceiling, and
**a figure the user confirmed must be the figure the proof was taken over**.

### The tree, read rather than assumed, at `origin/main` `8b6fd2af`

- `core/protocols.py`'s `ActionPolicy` carries **two** members, `decide` and `resolve`, and
  `orchestration`'s `StepRunner` already holds one: it calls `decide` before the claim and
  `proposed_authorization` beside it, in one method. **No new seam and no new composition-root
  wiring is needed to ask it a third question.**
- `permissions/_coverage.py` holds condition 6 as `covers`, `covers_arguments` and `uncovered`,
  over a `CoverageSubject` read off the request in one observation. It is module functions, holds
  no store and no seam, and is called by the policy alone.
- **`BoundedArgument`, `CoverageMember.kind` and `ActionRequest.intended_action` are not on this
  tree** — ADR-0266's L1 is in flight (PR #2408) — and **`ActionQuote`, `QuoteView` and
  `GoalQuotes` are not either**, ADR-0267's Q1 being unbriefed. Every operand of the evidence route
  is therefore still to land, which is what §6 below cuts the lane against.

### What this ADR is not allowed to settle

Anything else in ADR-0266 or ADR-0267. It adds **one** member answering **one** question and the
`core` value that question is answered in, and it neither revisits the two routes, nor the quote's
producer, carrier or freshness, nor what a declaration declares, nor what a confirmation renders.

## Decision

### 1. `ActionPolicy.coverage_met`: one member, and it answers condition 6 and nothing else

> **Normative.** `core/protocols.py`'s `ActionPolicy` gains **one** member and no lane adds a
> second: **`async def coverage_met(self, request: ActionRequest, coverage:
> tuple[CoverageMember, ...]) -> CoverageAnswer`**, answering whether `coverage` — the coverage a
> row this system would write would carry — satisfies **ADR-0266 §7's condition 6** for `request`,
> in the closed value §2 mints. It is **`async`** because the evidence route reads a durable seam,
> `GoalQuotes.for_action` (ADR-0267 §5), on `CLAUDE.md`'s own rule and as
> `GoalAuthorizations.live_for` is. Cancelling it is governed by `core/protocols.py`'s cancellation
> clause (ADR-0060) and its observation of its arguments by ADR-0065's, like every member of that
> module. This is a **BREAKING** contract change to `core/protocols.py` under golden rule 5 and is
> flagged as one.

> **Normative — it is on `ActionPolicy` and not on a narrow face beside it, and the ground is that
> the caller already holds one.** `StepRunner` is handed an `ActionPolicy` today and calls `decide`
> in the same method that builds the proposal, so the member costs **no new seam, no new
> composition-root wiring and no new object for a lane to forget to pass**. The narrow-face
> argument ADR-0097 §3 and ADR-0193 §1 make is about denying a component a capability it should not
> have; this member **denies rather than grants** — it returns no ruling and writes nothing (§4) —
> so a separate face would deny its caller nothing it does not already hold and would buy only a
> second thing to wire.

> **Normative — it takes the coverage tuple and never the row.** ADR-0254 §15 rules that no
> `ActionPolicy` writes or settles an `Authorization`; handing the policy the row about to be
> written would put one in its hands for the one question that does not need it. Condition 6 is
> stated over the request's user-facing arguments, its declaration's `bounded_arguments`, its
> `intended_action` and the row's `coverage`, and the first three are on the request — so the
> request and the tuple are the whole operand, and `id`, `goal`, `tool`, `account`,
> `destinations`, `proposed_at`, `expires_at`, `confirmation`, `supersedes` and `disposition` are
> read here by nothing.

> **Normative — it evaluates condition 6 and no other condition.** Not ADR-0254 §3's conditions 1
> to 5 — there is no live row for them to be taken over, a proposal being written `PROPOSED`, which
> is ADR-0266 §7's own reason for restating §1's condition over condition 6 alone. Not ADR-0254
> §6's floors: §1's *"the proposal reads none of §6's floors, and that is deliberate"* binds entire
> and this member reads none either, so a request whose binding carries
> `planned_with_external_content` is answered on condition 6 exactly as one that does not. Not
> §12's ladder, and not §1's other three proposal conditions, which the writer takes for itself.

### 2. `CoverageAnswer`: the fact, the quote it was proved over, and what it deliberately omits

> **Normative.** `core/types.py` gains **`CoverageAnswer`**, a frozen model with `extra="forbid"`
> whose fields are exactly **two**: **`met`**, a `bool`, whether that coverage satisfies condition 6
> for that request; and **`quoted`**, an `ActionQuote | None` defaulting to `None` — **the governing
> quote ADR-0266 §7's evidence route was taken over for this request**, of the quotes
> `GoalQuotes.for_action` returned, the last of them (ADR-0267 §5), and no other. A **model
> validator** refuses `quoted` set where `met` is false. This is a **BREAKING** contract change to
> `core/types.py` under golden rule 5 and is flagged as one.

> **Normative — `quoted` is present exactly where the evidence route decided something, and its
> absence is total over every other case.** It is set where `met` is true **and** `coverage`
> carries a `MONEY` member, that member being the one the evidence route alone can meet (ADR-0266
> §7). It is **absent in every other case**, and ADR-0267 §7's own three absence cases are among
> them: a `coverage` carrying no `MONEY` member leaves nothing the evidence route decided, and a
> request carrying no `intended_action`, or a goal no quote of which names that action, leaves any
> `MONEY` member unmet and `met` false. **No implementation sets it on any other ground**, invents a
> quote, or returns one it did not read.

> **Normative — it carries no account of *why* a coverage was not met, and that is decided rather
> than deferred.** Where `met` is false no row is written, `Confirmation.authorization` is absent
> (ADR-0254 §11) and the one call is confirmed under ADR-0148 §3's route (a) — so no surface
> renders a projection of a row that does not exist, and **no caller has a use for which conjunct
> failed**. The account of an uncovered request a user does see is `decide`'s, taken at dispatch
> over a live row and rendered by `permissions` (ADR-0254 §4), and it is untouched. A closed
> vocabulary nothing reads is the one-sided enum ADR-0249 §10 names and ADR-0267 §10 declines
> again; **the decision that gives a caller a use for the reason widens the member**, and golden
> rule 5 makes that visible rather than cheap. **No third field is added for anything else**: no
> route, no digest, no unmet member's kind, no ruling and no record crosses the seam.

> **Normative — `quoted` is the operand the proof was taken over and never a verdict, and no
> comparison reads it.** It states **which** quote condition 6 was evaluated against and asserts
> nothing a caller may take as coverage, completeness or authority: **no component covers a request
> against it, re-tests it, refreshes it, compares it to a later quote, caches it, or reads it — or
> its absence — as evidence of anything a comparison decided.** ADR-0254 §13's recheck and ADR-0266
> §7's evidence route each read the **current** governing quote through ADR-0267 §5's seam at every
> dispatch, never this value. That is ADR-0267 §7's provenance clause reaching the same fact one
> seam earlier, and it binds here unrelaxed.

> **Normative — `Authorization.quoted` is set from this field, on ADR-0254 §1's path (i) alone, and
> the writer selects nothing.** A component writing a path-(i) proposal records the answer's
> `quoted` on the row and **performs no selection of its own**: it does not re-read the goal's
> quotes for it, does not take the last member of any tuple, and does not reconcile the two. **On
> paths (ii) and (iii) it reads `met` and discards `quoted`**, both writing `ESTABLISHED` directly
> and putting no question, so ADR-0267 §7's *"absent on every path-(ii) and every path-(iii) row"*
> and its no-back-fill rule bind entire. **Where the answer carries no quote, the field is absent**,
> which is §7's own three-case absence rule preserved rather than restated.

> **Normative — this closes ADR-0267 §10's two-read window, and it closes it by there being one
> read.** The policy's read through `for_action` is the **only** read of the goal's quotes on the
> proposal path, so the figure the confirmation renders and the figure condition 6 passed on are
> **the same value in every case**, and a refresh landing anywhere cannot separate them. The value
> itself is unmoved: ADR-0267 §7 selects *"the last member of the goal's `quotes` naming the
> request's `intended_action`"* and ADR-0267 §5 has `permissions` *"take the last member of what
> comes back"* from a seam returning that goal's quotes for that action *"in the order the goal
> holds them"* — one rule stated twice — so what moves is which read it is taken over and which
> component takes it, and nothing else. **No version check, no compare-and-swap and no second read
> is introduced**, §7's own refusal of all three kept by removing a read rather than adding one.

### 3. Where it is consulted, and where it is not

> **Normative — one question, one answerer.** Where a component that is not `permissions` needs
> condition 6's answer about a row it would write, **it obtains it from this member and by no other
> means**: it re-implements no conjunct of condition 6, selects no governing quote, compares no
> arguments digest, reads no `BoundedArgument` and takes no `ValueBound` comparison. That reaches
> **ADR-0254 §1's completeness condition**, which ADR-0266 §7 restates over condition 6 and which
> §1 states over path (i) **and** path (iii); and it reaches **ADR-0254 §5's correction test**, as
> ADR-0266 §9 restates it — *"an argument the row would not cover under condition 6 once the
> correction is applied"* — on path (ii). **This decision cuts a lane for none of the three** (§6):
> path (i) is the only one with a writer on this tree, and the rule is stated over the question
> rather than over the lanes so that a later writer inherits it rather than re-deciding it.

> **Normative — ADR-0254 §13's recheck is untouched, and this member is not it.** The coverage
> comparison *"taken at `ActionPolicy.decide`, on the concrete request, at every dispatch"* stands
> exactly as §13 and ADR-0266 §7 state it, over a **live** row and all six conditions, and nothing
> here relaxes, replaces or pre-empts it. **No answer this member returns is cached, carried to a
> dispatch or read by any later comparison**: §13's *"no cached coverage verdict anywhere"* binds
> this member exactly as it binds every other, and a proposal-time answer answers that proposal.
> **The one thing that survives the call is the quote, as provenance and never as a verdict** (§2):
> it is recorded on the row that answer authorised the proposal of, it is read by no comparison of
> any decision, and `decide` reads the current governing quote at every dispatch as if the field
> were not there.

### 4. What it never does

> **Normative.** It **rules nothing**. It returns no `PermissionRuling`, so it has no field in
> which to allow, deny or confirm; it sets no `authorised_by`, no `authorised_subject` and no
> `authorised_goal`; it is no route of ADR-0148 §3 and clears no floor of any of them. The ruling
> on the request is `decide`'s, unchanged, and a met answer authorises nothing by itself.

> **Normative.** It **establishes nothing and records nothing**. It writes and settles no
> `Authorization` — ADR-0254 §15's writer clause binds entire — mints no `CoverageMember`, mints
> no quote, records no `PermissionDecision`, and **writes to no store and holds none**: it reads
> through `GoalQuotes` alone (ADR-0267 §5) and names no concrete store, which is the posture
> `GoalAuthorizations` already fixes for a policy's durable read. **And it reads no model output**:
> ADR-0254 §9's no-model clause and ADR-0266 §8's binding entire, no nomination of an argument, a
> kind, a member, a bound or a quote reaches it or is read by it.

> **Normative — a fault is never an absence, and the disposition is ADR-0254 §1's own.** Where
> `GoalQuotes.for_action` raises `AuthorizationError` (ADR-0267 §5), this member **propagates it**:
> no implementation converts it into a `met` answer, into an unmet one, or into an empty tuple of
> quotes. **A component that asked writes no row where the member faults**,
> `Confirmation.authorization` is absent and the one call is confirmed under route (a) — §1's own
> disposition for a failed completeness condition, reached by one further case. **No new error
> class is minted** and no caller falls through to the argument route.

> **Normative — a policy that cannot read a quote answers unmet, and never met.** An
> implementation constructed with **no** `GoalQuotes` answers `met` false, and so carries no quote,
> for any `coverage` carrying a member the evidence route alone can meet — which is every `MONEY`
> member (ADR-0266 §7). That is `decide`'s own *"no authorisation source"* floor read one member
> over, and it is what makes the writer's call behaviour-preserving on a tree that carries no
> quote: the empty coverage this system proposes today is still met exactly where it is met today,
> and still records no quote.

### 5. What this records, and what it declines to record, under ADR-0082 §1

> **Normative — ADR-0266 §7's last clause is superseded in one limb, and its other two limbs bind
> entire.** That clause reads *"At `ActionPolicy.decide`, on the concrete request, at every
> dispatch, with no cached verdict anywhere, which is where ADR-0254 §13 puts it … One
> implementation, in `permissions`, and §5's mint runs none of it."* Read whole it answers **where
> the comparison is taken** exhaustively, and a reader holding only §7 puts condition 6 behind
> `decide` and exposes no face — leaving the answer unobtainable to the component ADR-0254 §15
> obliges to write the row, which is #2401. **The limb naming `decide` as the only site is
> replaced**: the comparison is taken at `decide` at every dispatch **and** at `coverage_met`
> before a row is written. **The one-implementation limb is not weakened but kept** — this member
> is that implementation's face and not a second one, and the quote it returns is the one that
> implementation selected (§2) — and the no-cached-verdict limb binds entire (§3).

> **Normative — ADR-0266 §11's lane-ordering clause is superseded in its Lane-2 limb alone.** §11
> rules that *"ADR-0254 §20's Lane 2 is briefed after the quote decision (§10) rather than after
> these two"*. Lane 2 owns the proposal path and its path-(i) writer, so it is the lane that calls
> this member; briefed on §11's ordering alone it would land before the seam exists and would
> evaluate condition 6 in `orchestration`, which §7 forbids. **Lane 2 is briefed after the quote
> decision and after this decision's own lane** (§6). Every other limb of §11 binds entire — L1's
> and L2's surfaces and arms, *"two lanes and no third"* for that decision's own implementation,
> L1's wait on ADR-0254 §20's Lane 3, the wire clause and the no-migration clause.

> **Normative — ADR-0267 §7's selection clause is superseded in one limb, and the five places the
> replaced reading is available are swept rather than assumed.** ADR-0070 §1's test — *would a
> reader holding only the earlier ADR now act differently* — is applied at each.
>
> 1. **§7's selection clause, and this is the one scope.** It reads *"`quoted` is selected by §2's
>    order alone, by no comparison, and by the component that writes the row … the last member of
>    the goal's `quotes` naming the request's `intended_action`, taken from the read that write is
>    built on."* **Replaced in the limb naming the selecting component and that component's own
>    read**: the selection is `permissions`', taken inside condition 6's answer over the read that
>    answer was proved on, and the writer **records** what the answer carries. **§2's order and the
>    no-comparison rule bind entire** — the selection is still a position in a tuple, decided by no
>    comparison — and so do the write-once, before-the-question and never-edited rules.
> 2. **§7's field clause**, which says the field carries the quote *"selected by §2's order alone
>    over that one read"* and that *"no version check, no compare-and-swap and no second read is
>    owed"*. **Reached by the same scope in its *that one read* limb and in no other**: the read is
>    the policy's. The field's type, default, meaning, its *"fact about the read and not about the
>    instant of persistence"* and its three-case absence rule bind entire, and the refusal of a
>    version check, a compare-and-swap and a second read is true *a fortiori* — this decision
>    removes a read rather than adding one (§2).
> 3. **§7's unmarked ground**, *"And the selection itself asks `permissions` for nothing … What the
>    writer must still obtain from `permissions` is condition 6's answer."* Its first half **becomes
>    false**; it is unmarked and supplies no obligation (ADR-0089 §3), and it is recorded because a
>    reader relies on a stated reason. **What the ground was protecting is kept**: the selection
>    consults no `CoverageMember`, no `ValueBound`, no bound, no declaration and no route, and it
>    rides back on the one call the writer already makes for condition 6's answer — **no second
>    seam, no further read and no further boundary crossing**. Its second half is exactly what this
>    decision mints.
> 4. **§7's provenance clause**, *"`quoted` is provenance, it states what was governing and never
>    that it satisfied the member, and no comparison of any decision reads it."* **Binds entire and
>    is deliberately kept** (§2). It was never a claim about fact — a path-(i) row is written only
>    where the completeness condition held, so a present `quoted` already implied a met `MONEY`
>    member — but a claim about what a reader may take from the field, and that is unchanged.
> 5. **§10's completeness-and-quote entry.** It is **fired, not contradicted**: the entry names
>    this amendment as its firing condition, *"Fired by that amendment, booked **ahead of** ADR-0254
>    §20's Lane 2 and waited on by it"*, and a condition firing as written is the mechanism working.
>    **Both halves fire** — where the condition is evaluated and through what (§1, §3), and whether
>    the row records the quote that answered it (§2) — and **no other entry of §10 is touched**.
>
> **Nothing else in ADR-0267 moves.** §5's shape, keyed read, no-predicate rule, fault direction and
> composition-root clause are consumed unchanged; §11 still assigns `quoted`'s population to
> ADR-0254 §20's Lane 2, which now writes it from the answer; and that decision's own
> `Partially supersedes` record of ADR-0254 §1's field list stays true word for word, the field's
> **meaning** being what it states and that being unmoved.

> **Normative — ADR-0254 §16's `core`-surface roster is superseded in one limb, and its other
> clauses bind entire.** §16 states what `core/types.py` gains; ADR-0266 §9 left that at
> **fourteen** types and **seven** fields and ADR-0267 §9 at **eighteen** and **twelve**. §2 above
> adds `CoverageAnswer` — a **nineteenth** type — and **no** further field, so a reader holding
> only §16 implements a roster test that fails on this decision's own surface, which is the ground
> ADR-0267 §9 took the same scope on. **§16's `core/protocols.py` roster is untouched**: it
> enumerates what ADR-0254's own lanes add there and names `ActionPolicy` in none of it, the
> widening of that Protocol being *"a widening §16 does not close"* as ADR-0267 §9 already read it.
> **Its `PermissionDecision` clause is untouched**, that record gaining nothing here; **its
> `core/errors.py` roster is untouched**, §4 minting no error class; and its
> *"`core/config.py` gains nothing at all"*, its wire clause, its lane attribution and its
> transcribe-the-ruling-whole rule bind entire.

> **Normative — no other record is owed against ADR-0254, and the working is stated rather than
> assumed.** §1 states the completeness condition, its four conditions and its disposition, and
> says **nothing** about which component evaluates it or how one obtains the answer — which is
> exactly what ADR-0267 §10 records as not decided — so no sentence of §1 becomes false or
> over-wide. §13's recheck-at-`decide` and its no-cached-verdict rule stay true word for word (§3).
> §15's writer clauses stay true: the row is written and settled by `orchestration` alone, and a
> value it records is not a write by the component that computed it (§2, §4).

### 6. The lane cut, and the arms this decision owes

> **Normative.** This ADR is ratified and merged as its own PR before anything implements against
> it (ADR-0015, golden rule 5), and it is implemented in **one lane and no second**:
> `CoverageAnswer` in `core/types.py` with its validator, `core/protocols.py`'s member, the
> obligations above in the shared conformance suite, the canonical fake in `ai_assistant.testing`,
> and the one implementation in `permissions`, which is `_coverage.py`'s condition 6 reached
> through the policy. **`CoverageAnswer` is a type and not a Protocol**, so it owes no triad of its
> own; the member rides an existing Protocol, whose conformance suite and canonical fake grow with
> it. **The call site is not this lane's**: `orchestration`'s in-place evaluation is replaced by
> the call, and `Authorization.quoted` written from the answer, in **ADR-0254 §20's Lane 2**, which
> owns the proposal path and its path-(i) writer and is briefed after this lane (§5). **This lane
> writes no `Authorization`, wires no consequential capability and touches no file under
> `orchestration`.**

> **Normative — the lane is briefed after ADR-0266's L1 and after ADR-0267's Q1, and the reason is
> that every operand is theirs.** L1 lands `BoundedArgument`, `CoverageMember.kind`,
> `ActionRequest.intended_action` and §7's two routes in `permissions/_coverage.py`; Q1 lands
> `ActionQuote`, `GoalQuotes` with its triad, and `for_action` wired into the evidence route.
> Without L1 there is no condition 6 in the shape this member answers; without Q1 there is no
> `ActionQuote` for `CoverageAnswer` to carry and no `MONEY` member can be met by anything, so arm
> 2 below has nothing to be driven over. **Where either is not in its base, this lane is not
> briefed** — ADR-0266 §11's own shape for L1's wait on Lane 3. **The lane re-takes that reading at
> its own base and states what it found.**

> **Normative — the tree this lane leaves is conforming and fail-closed, and nothing is a second
> implementation in the interval.** Until Lane 2 moves the call site, `orchestration` keeps its
> present refusal — no row is proposed for a request carrying any user-facing argument — which
> **compares nothing**: it evaluates no member, takes no route and reads no quote, so it is a
> refusal and not a rival implementation of condition 6. It is strictly more restrictive than the
> member's answer, so the interval costs questions and authorises nothing (ADR-0084 §3). **And
> `Authorization.quoted` is written by nothing in that interval**, no path-(i) row being proposed
> for a request a quote could govern.

> **Normative — neither `PROTOCOL_VERSION` nor `PlanExport.schema_version` moves, and no stored
> record gains a field.** `CoverageAnswer` crosses **no frame**: it is returned across a Protocol
> within one process, is a field of no model any frame carries and of no stored record, and
> `wire/codec.py` renders none of it. **The row's `quoted` is ADR-0267's field, landed by
> ADR-0267's lanes**, and this decision adds no field to `Authorization`, to
> `AuthorizationProjection` or to any other model, migrates, edits or drops no row, and adds no
> `Settings` field, deployment flag or configurable figure.

> **Normative — the lane ships the four arms below, each over controlled fakes, and it is not
> complete without them.** No arm asserts anything its own tree cannot produce, and none is
> demonstrated against a live integration.

1. **The vacuous case, preserved exactly, and it carries no quote.** An empty `coverage` over a
   request carrying **no** user-facing argument answers `met` true with `quoted` absent; the same
   empty `coverage` over a request carrying one user-facing argument its declaration declares at no
   kind answers `met` false, also with `quoted` absent. That is `proposed_authorization`'s present
   behaviour, so Lane 2's call-site change preserves what this tree does today rather than changing
   it.
2. **A `MONEY` member, the governing quote, and the answer carrying it**, over quotes
   **constructed** on a goal. Against a quote naming the request's `intended_action`, taken over the
   request's own arguments, at `"120"`/`"EUR"`, a `coverage` carrying one `MONEY` member bounded at
   `150`/`EUR` answers `met` true **and `quoted` equal to that quote**; where the goal holds two
   quotes for that action the answer carries **the last**, which is the one ADR-0267 §7 would have
   selected; at `"170"` it answers `met` false **and carries no quote**; at `"120"`/`"USD"` it
   answers false, the currency conjunct being read at the quote's own currency; with **no** quote
   naming that action it answers false; and an implementation holding no `GoalQuotes` answers false
   for that same pair. **`CoverageAnswer` refuses construction with `quoted` set and `met` false.**
3. **It rules nothing, records nothing and caches nothing.** The member returns no
   `PermissionRuling`, writes no `Authorization` and appends to no store; two calls with equal
   arguments each read the seam, no answer being memoised between them or carried to a later
   `decide`; and a `for_action` raising `AuthorizationError` **propagates** rather than answering
   unmet.
4. **Condition 6 and no other condition.** A `coverage` that satisfies condition 6 is answered
   `met` true on a request whose `egress_binding` carries `planned_with_external_content`, on a
   request whose goal holds no live row of that pair, and whatever §12's ladder would yield for it
   — those being ADR-0254 §1's other conditions and §6's floors, and not this member's. **No answer
   is met on a coverage carrying a member met by no route**, which is condition 6's own second
   direction.

### 7. This ADR classified, marked, and how it is ratified

> **Normative.** Under ADR-0070 §1's test this is a **supersession and not an amendment**: a reader
> holding only ADR-0254 §16, ADR-0266 §7 or §11, or ADR-0267 §7 would act differently, so §5's four
> scopes take the partial form (ADR-0070 §3, §4). It is a **contract** decision — it widens
> `core/protocols.py` and `core/types.py` — so under ADR-0015 §1 it is reviewed by **both** lenses
> while `Proposed`, ratified by `just adr-ratify`'s one-line flip, and merged as its own PR before
> anything implements against it.

> **Normative.** This ADR is **marked** under ADR-0089: every obligation it imposes is in a clause
> of §2's grammar, and unmarked text beside a mark is read to determine what that mark means and
> supplies no obligation of its own (ADR-0089 §3).

> **Normative — the records this change writes, and they are the whole of it.** ADR-0254's,
> ADR-0266's and ADR-0267's `Status` lines each take ADR-0070 §4's canonical partial form on **one
> physical line**, carrying this decision's pair beside the ones already there, each scope naming a
> clause and carrying no `ADR-NNNN` token so that §4's *"every `ADR-NNNN` after the leading
> `Partially superseded by` is a target"* reads true; and each gains the **appended dated note**
> ADR-0070 §1 requires beside it, stating its scope of §5 in full. **Taking the leading token
> obliges two repairs and no more.** On ADR-0266 that item's value was followed by a continuation
> recording what it *supersedes* in ADR-0254, whose own `- **Partially supersedes**` bullet header
> had been lost into the `Status` value; the bullet is restored so the continuation attaches to it
> as its sibling's already does. On ADR-0267 the value carried a leading `Accepted,` and wrapped
> across five physical lines; it is written as one line under the leading token, which discharges
> [#2419](https://github.com/leonapivato/ai-assistant/issues/2419). Both are corrections under
> ADR-0070 §1 — they change no decision, and they are what puts a whole-line read within reach of a
> consumer. **No other ADR's header is edited** and no file under `src/` or `tests/` is touched.

## Consequences

**The proposal path becomes writable at all.** Today it is writable only vacuously, and the one
route to making it general crosses golden rule 1. After this, `orchestration` proposes a row whose
coverage it can neither evaluate nor second-guess, and the component that owns condition 6 keeps
owning it — the seam is the whole of what joins ADR-0266 §7 to ADR-0254 §15.

**The figure a user confirms is the figure the proof was taken over.** ADR-0267 §10's second half
is closed by there being one read rather than two: the quote the evidence route passed on is the
quote recorded on the row and the quote the confirmation renders, and a refresh landing at any
instant cannot separate them. What a later quote still changes is the **dispatch**, ADR-0254 §13's
recheck reading the current governing quote every time — so an act whose price has moved above the
ceiling is uncovered however the confirmation read, which is ADR-0267 §7's rule and is untouched.

**One member and one `core` value.** `core/types.py` gains `CoverageAnswer` and nothing else: no
wire ground appears, no stored shape moves, and no vocabulary is minted for a reader that does not
exist. What crosses the seam is the one fact the writer cannot compute for itself, and the one
value that fact was computed against.

**What becomes harder.** `ActionPolicy` gains a third member and `core/types.py` a nineteenth type,
so every conforming implementation and the canonical fake grow — a cost golden rule 5 makes visible
rather than cheap. Two lanes now queue behind a third: ADR-0254 §20's Lane 2 and, with it,
ADR-0267's population of `quoted` wait on this decision's lane, which itself waits on ADR-0266's L1
and ADR-0267's Q1. And a caller that wants to know **why** a coverage was not met has nothing to
read; a decision that gives one a reader widens the member rather than a field.

**What would trigger revisiting this.** A second component outside `permissions` needing condition
6's answer for something other than a row it would write — the member is stated over that case and
no other. A surface that renders a refused proposal, which would give the reason a reader. And the
decision that pins a **dispatch's** quote to that dispatch (#2409), which is a **different**
residual from the one §2 closes and stays open: it is the quote `decide` compared at dispatch,
reached through that member's own result contract, and calling `coverage_met` again there would be
a second read of a seam that may have moved and still would not be the value `decide` used.

## Alternatives considered

**A narrow Protocol beside `ActionPolicy`**, on ADR-0097 §3's and ADR-0193 §1's pattern. Declined in
§1: those faces exist to **deny** a component a capability, and this member denies its caller
nothing it does not already hold — `StepRunner` has the policy in hand. A second object would be a
second thing for a composition root to pass and a lane to forget, bought for no guarantee.

**A bare `bool`, leaving `Authorization.quoted` to the writer's own selection.** Declined in §2, and
it was this ADR's second draft. It costs no `core` type and takes no scope on ADR-0267 §7 — but it
leaves the policy's read and the writer's read as two, so the figure the user confirms and the
figure condition 6 passed on can differ where a refresh lands between them, which is exactly the
half of ADR-0267 §10's entry that names this amendment as what fires it. Answering one half of a
booked entry and leaving the other for a later ADR to close **by widening this same member** buys a
smaller diff today and a second contract change later, against a decision whose worked case renders
the quoted figure beside the ceiling.

**A closed result carrying the reason a coverage was not met** — the unmet member's kind, or which
of condition 6's three conjuncts failed. Declined in §2 for want of a reader: no row is written, so
no projection renders, and the account a user sees is `decide`'s. A vocabulary minted ahead of the
surface that reads it is ADR-0249 §10's empty box.

**Passing the proposed `Authorization` itself.** Declined in §1: it hands an `ActionPolicy` the row
ADR-0254 §15 rules it may never write, for a question that needs only the request and the coverage
tuple. Narrower is not merely tidier here — it makes the writer clause true by construction.

**Leaving the evaluation in `orchestration` and calling it a permitted duplication.** Declined: it
is exactly the second implementation ADR-0266 §7 forbids, and the two would be free to disagree the
moment a member could be met. The fail-closed direction of today's in-place refusal is not a defence
of it — it is why the interval before Lane 2 is safe (§6), not why the duplication could stand.

**Evaluating the completeness condition inside `permissions` by handing it the whole proposal
decision.** Declined: that moves ADR-0254 §1's other three conditions, §12's ladder and the
supersession choice into the policy, which would put the writing of an `Authorization` one step from
a component §15 excludes from it.
