# 271. The quote a dispatch was proved against is pinned to that dispatch, and a charge that
disagrees with it is a reported finding

- Status: Proposed
- Date: 2026-09-15
- **Partially supersedes** [ADR-0262](0262-verification-compares-the-goals-criteria-with-what-the-record-establishes-at-a-strength-the-consequence-class-fixes-and-is-achieveds-only-producer.md)
  — **two scopes, and §7 shows the working for each. §2's `MONEY` clause, which rules that *"a
  criterion whose confirmed member is a `MONEY` one is `unestablished`"* outright**: such a
  criterion now takes §2's own three results, over §2's own calls and decisive steps, with **one
  further conjunct** on its satisfying and contradicting tests — the charge the act reported agrees
  with the quote this decision pins to that dispatch. That clause's stated ground was that *"the
  charge is not an operand this decision has"*; this decision lands the operand, which is what
  ADR-0262 §9 reassigns here by name. **And §7's gate statement, in the limb *"the guarantee does
  not cover a capability whose acts make a charge"* alone**: it covers one, for a deployment that
  declares where its acts report a charge. **Every other clause of both sections binds entire** —
  §2's authorising rows, its confirmed member, its bound steps, its operative declaration, its
  grouping by `parameters_digest`, its ambiguity rule, its no-fourth-result rule and its
  no-model-operand rules; §7's three wired-deployment obligations, its count of **seven**
  conditions and its *"ratification is not implementation"*.
- **Partially supersedes** [ADR-0267](0267-a-quote-is-a-record-the-goal-holds-in-order-read-from-the-output-its-declaration-names.md)
  — **one scope, in §1's unmarked ground beside the no-eighth-field clause and in one limb of it**:
  the sentence *"A later record naming one quote — a verification finding, say — names it by the
  act and the digest"*. That pair selects **the governing** quote for that pair at the instant it is
  read, and a dispatch's pin must state the reading the dispatch was proved against, which a later
  append displaces; so this record carries the quote **by value** and names it by nothing. **§1's
  decision to mint no identifier is upheld and reached by a different route**, so ADR-0267 §10's
  *"An identifier of a quote's own"* entry is **fired and discharged in the negative** rather than
  contradicted; §1's seven fields, its no-eighth-field clause, its four facts, its totality
  obligation, its digest rule and its bound-to-the-act rule bind entire, as does every other
  section of that ADR — §4's mint, §5's seam, §6's freshness prerequisite and §7's *"`quoted` is
  provenance"* conspicuously so.

## Context

### Where this comes from

Issue **[#2409](https://github.com/leonapivato/ai-assistant/issues/2409)**, and the owner's ruling
of 2026-09-14: *"The actual charge is confirmed by the verification phase afterward; a quote/charge
mismatch is a reported finding."* ADR-0266 §10 and ADR-0267 §10 each booked that confirmation as
fired by A10; ADR-0262 — A10 — took **two narrow scopes on exactly those two clauses** and
reassigned the charge confirmation and the mismatch finding **here**, on the ground that the
comparison has no operand today. This is that decision.

### The gap this closes, stated as the failure the corpus has today

The comparison the ruling asks for is *the charge the act reported* against *the quote the dispatch
was proved against*. The second operand is recorded **nowhere**, and each of the four values a
reader reaches for is the wrong one:

- **ADR-0254 §13** rules there is *"no cached coverage verdict anywhere"*, so the comparison
  `decide` took — and the quote it took it over — does not survive the dispatch.
- **ADR-0267 §7's `Authorization.quoted`** is the **proposal's** read, selected by `permissions`
  inside condition 6's answer since ADR-0270 §2. A dispatch honestly proved against a quote a
  refresh appended afterwards would read as a mismatch against it, and ADR-0267 §7 is explicit that
  *"no comparison of any decision reads it"*.
- **The goal's `quotes` tuple** carries the reading the **acting step itself appended** (ADR-0267
  §4), so a €170 charge agrees with a €170 quote under a €120 ceiling.
- **The user's own ceiling** passes a charge that **exceeds the quote** while staying under it —
  which is precisely the mismatch the ruling calls a finding.

So ADR-0262 §2 makes every `MONEY` criterion `unestablished` outright: such a goal reaches
`UNCERTAIN` at rung 2 and never `ACHIEVED`, and §7 states that ADR-0255 §13's gate is therefore
**not met** for a capability whose acts make a charge. That is the fail-closed direction and the
right one while the operand is missing; it is not a design anyone wants to keep.

### The tree, read rather than assumed, at `origin/main` `210b33d7`

- **`PermissionRuling` carries `authorised_by`, `authorised_subject` and `authorised_goal`**, and
  `PermissionDecision.from_request` transcribes the ruling whole (`ruling.model_copy(deep=True)`).
  ADR-0254 §16 records that path as why *"`PermissionDecision` gains no field"* — a policy-authored
  value reaches the durable record on the ruling, with no parameter added to `from_request`, no
  second lookup and no widened `ActionPolicy` return.
- **`ToolInvocation` carries no content at all** (ADR-0192 §2) — no argument value, no payload, no
  output and no digest of any of them — and its `incurred_cost` is *"the price of the invocation …
  never money the tool moved"* (ADR-0192 §5). Neither the row nor that field can carry this pin or
  this charge.
- **`ActionQuote`, `QuotedOutput`, `ActionRequest.intended_action`, `CoverageMember.kind` and
  `BoundedArgument` are not on this tree.** ADR-0266's L1 is in flight (PR #2408), ADR-0267's Q1 is
  unbriefed, and ADR-0270's lane is unbriefed. Every operand this decision reads is ratified and
  unimplemented, which is what §8 cuts the lane against.
- `ToolDefinition` carries `quoted_output` in ADR-0267 §3 and `postconditions` in ADR-0262 §2,
  neither on this tree, and **nothing anywhere states where an act reports what it charged**.

### What this ADR is not allowed to settle

Anything else in ADR-0262, ADR-0266, ADR-0267 or ADR-0270. It lands one operand, one place to read
the other, and the comparison between them; it revisits no route, no member, no bound, no quote
producer, no freshness rule and no coverage condition.

## Decision

### 1. The pin: the quote `decide` proved the call against, carried by value on the ruling

> **Normative.** `core/types.py`'s **`PermissionRuling` gains one field, `proved_quote:
> ActionQuote | None` defaulting to `None`** — **the `ActionQuote` the coverage comparison at
> `ActionPolicy.decide` took ADR-0266 §7's evidence route over for this request**, carried **by
> value** and read a second time by nobody. It reaches the durable `PermissionDecision` by the path
> that exists today, `from_request` transcribing the ruling whole, so **`PermissionDecision` gains
> no field**, `from_request` gains no parameter and `ActionPolicy`'s return does not widen —
> ADR-0254 §16's own construction for `authorised_goal`, one field over. This is a **BREAKING**
> contract change to `core/types.py` under golden rule 5 and is flagged as one.

> **Normative — it is set exactly where the evidence route decided something, and its absence is
> total over every other case.** `permissions` sets it where the ruling is a **route-(d) `ALLOW`**
> — ADR-0254 §7's discriminator — whose coverage carried a `MONEY` member met through ADR-0266 §7's
> evidence route, and it is then **the governing quote that route was taken over**: of the quotes
> `GoalQuotes.for_action` returned, the last of them (ADR-0267 §5), and no other. It is **absent in
> every other case** — every ruling that is not a route-(d) `ALLOW`, a coverage carrying no `MONEY`
> member, a request carrying no `intended_action`, a goal no quote of which names that action. **A
> model validator refuses it set where `authorised_by` is unset.** No implementation sets it on any
> other ground, invents a quote, or records one it did not compare.

> **Normative — it is the operand a comparison was taken over and never the verdict of one, and
> ADR-0254 §13 binds it unrelaxed.** It states **which** quote condition 6 was evaluated against at
> this dispatch and asserts nothing about coverage, completeness or authority. **No component
> covers a request against it, re-tests it, refreshes it, compares it to a later quote, carries it
> to a further dispatch, or reads it — or its absence — as evidence of anything a comparison
> decided.** §13's *"no cached coverage verdict anywhere"* is untouched: the recheck reads the
> **current** governing quote through ADR-0267 §5's seam at every dispatch, as if this field were
> not there, and the one reader this decision gives it (§3) authorises nothing.

> **Normative — it is carried by value and named by nothing, and no identifier is minted.** The
> record is the `ActionQuote` itself, on ADR-0021 §1's own ground for embedding a `ToolDefinition`
> whole — *"There is no name left to rebind"*. Naming it by the act and the digest would name **the
> governing** quote for that pair **at the instant of the read**, which a later append displaces
> and ADR-0267 §2's elision can drop, so the pin would drift off the reading it exists to fix.
> **No lane mints a quote id, adds a field to `ActionQuote`, keys a record on one, or reconciles
> the pinned value against the goal's tuple** — ADR-0267 §10's *"An identifier of a quote's own"*
> is fired here and answered **no**.

> **Normative — `permissions` writes it, at the ruling, and nothing else writes or repairs one.**
> No `AuditTrail`, no store, no reader, no interface adapter, no tool and no model output
> constructs, writes, edits or repairs the field — ADR-0254 §15's writer clause reaching one
> further value the policy sets, on the record it already sets three on. **A planner envelope
> carrying a `proved_quote` has that value discarded silently** (ADR-0254 §9, ADR-0267 §8). **And
> it is never back-filled**: a decision recorded without one is a decision whose dispatch was not
> proved against a quote, and no pass supplies one afterwards.

### 2. The charge: where an act reports it, and where it is never read from

> **Normative.** `core/types.py`'s **`ToolDefinition` gains one field, `charged_output:
> QuotedOutput | None` defaulting to `None`** — the key of this declaration's output carrying **the
> whole amount an invocation of it charged**, and the key carrying that amount's ISO-4217 code.
> **The type is ADR-0267 §3's, reused and not restated**: it names two keys at depth one and
> refuses them equal, and it states nothing about tense, so a second shape would be ADR-0253 §6's
> *"the one spelling of that"* broken for no gain. **A declaration carrying `None` reports no
> charge ever**, so no `MONEY` criterion resting on its acts is `met` — the fail-closed default, and
> ADR-0016 §1's *"Declared, not inferred"*. This is a **BREAKING** contract change to
> `core/types.py` under golden rule 5 and is flagged as one.

> **Normative — it is a second field beside `quoted_output` and never that field read again.**
> `quoted_output` names where a **price on offer** is read, and ADR-0267 §4's mint appends a quote
> from it; reading a charge there would make **the acting step's own appended reading** the operand,
> which is the defect #2409 names. **No lane reads `quoted_output` as a charge, reads
> `charged_output` as a quote, mints an `ActionQuote` from a charge, or appends anything to the
> goal's `quotes` on this decision's authority.** A declaration may carry both, one or neither, and
> the two are compared against each other by nothing.

> **Normative — the charge is read at the comparison, from the bound step's own stored `output`,
> under the declaration pinned to the act that ran.** The operative declaration is ADR-0262 §2's —
> the whole `ToolDefinition` embedded by value in the `PermissionDecision` the step's
> `approval_ref` names, **never the registry's** — and the reading is ADR-0267 §4's own, restated
> by reference and not re-specified: the `output` is a JSON **object**; at the `amount` key a JSON
> **string** a `Decimal` accepts or a JSON **integer**, whose `Decimal` is finite and not negative,
> a JSON **float** and a JSON **boolean** each refused; at the `currency` key a JSON **string** of
> ADR-0267 §1's shape. **This decision mints no record, no store, no seam, no Protocol and no write
> path for a charge**, and no lane persists one.

> **Normative — every failure of that reading yields no charge, and nothing is repaired, coerced,
> defaulted or substituted.** A declaration with no `charged_output`, an `output` that is not an
> object, a missing key at either name, a value of any refused shape: each yields **no charge**, and
> §3 leaves the criterion `unestablished` in consequence. **No lane substitutes
> `ToolDefinition.cost`, `ToolInvocation.incurred_cost`, a quote, a ceiling or a zero** —
> ADR-0192 §5's *"never money the tool moved"* is the reason the invocation row is not the operand,
> and a charge this system supplied is a charge no provider reported.

### 3. The comparison, and the finding it produces

> **Normative — the charge test, taken over a bound step of a criterion whose confirmed member's
> `kind` is `MONEY`, and over no other step of any criterion.** The test **holds** where the step's
> pinned `PermissionDecision` carries a `proved_quote` (§1), a charge reads under §2, and **all
> three** conjuncts hold: the charge's **currency equals the pinned quote's `currency` byte for
> byte**, no conversion, no fold and no register consulted, exactly as ADR-0254 §4's `MONEY` reading
> compares one; the charge's **amount is not greater than the pinned quote's `amount`**; and that
> amount **satisfies the confirmed member** under ADR-0254 §3's fixed comparison or §4's `MONEY`
> reading, taken at the quote's own currency. It **fails** where a charge reads and some conjunct
> does not hold. It is **not taken at all** where there is no `proved_quote`, no `charged_output`,
> or no charge reads.

> **Normative — that test is one further conjunct on ADR-0262 §2's own two, for such a criterion
> and for no other, and no other clause of §2 moves.** A bound step is **satisfying** where §2's
> own satisfying test holds **and** the charge test holds; **contradicting** where §2's own
> contradicting test holds **or** the charge test fails; and **neither** where the charge test is
> not taken, whatever §2's own tests say. §2's grouping of bound steps into **calls** by
> `ActionRequest.parameters_digest`, its satisfying/contradicting/**ambiguous** rule over a call,
> its three results, its *"no fourth result exists"* and its *"a `FAILED` bound step is never
> decisive"* all bind entire and are what this conjunct is stated inside.

> **Normative — a charge that disagrees is the finding, and the finding is a report and never a
> prevention.** It is reported as the criterion's own result reaching the user by the route
> ADR-0262 already fixes — `unmet` through §4's limbs to an `AttemptOutcome`, through §6's
> `AttemptReport` to the fixed statement rendered beside the reply, with `assistant goals` where
> the goal's state is read. **It changes no ruling, refuses no dispatch, revokes no
> `Authorization`, retries nothing, reverses nothing and refunds nothing**, and the act it speaks of
> has already run. **ADR-0266 §7's proof *before* the act is what binds spending and is unweakened
> in every part**, which is the owner's ruling read as written.

> **Normative — no new field, no figure and no second surface, and the cost is stated rather than
> discovered.** `AttemptReport` keeps **exactly two fields** (ADR-0262 §6) and `TurnOutcome` gains
> nothing; no statement names the two amounts, the currency, the tool or the criterion, ADR-0262 §6's
> *"none names … a figure"* and ADR-0249 §9's containment binding unrelaxed. **So a user is told that
> what they asked for was not established and is shown neither number**; the two figures are on the
> record — the pin on the decision, the charge in the step's stored output — for a reader that does
> not exist yet, and §6 books the decision that gives one a surface with what fires it.

> **Normative — nothing in this comparison reads a model, a plan or a prose value.** Not a
> `verifies`, not an `intended_action` a planner wrote, not a step's position, not a
> `GoalElement.text`, not a `StepFailure.message` and not a tool description — ADR-0262 §2's
> no-model-operand clauses binding on this conjunct exactly as on its own two. **The operands are
> the policy's pinned quote, the tool author's declaration and the provider's returned output, and
> there is no fourth.**

### 4. What a `MONEY` criterion establishes now, and what the gate does and does not cover

> **Normative — ADR-0262 §2's blanket is reversed, and what replaces it is §2's own three results
> with §3's conjunct.** A criterion whose confirmed member is a `MONEY` one is **met** where §2's
> conditions for `met` hold under §3's extended tests — no call contradicting, none ambiguous, some
> call satisfying — which requires that the act was authorised against that confirmed member **and**
> that the reported charge agrees with the pinned quote within the member's ceiling; **unmet** where
> some call is contradicting, the mismatch among the ways one can be; and **unestablished**
> otherwise, which now reaches a charge that cannot be read at all. **The `BoundKind.MONEY` limb of
> §2's `unestablished` list is removed and is replaced by no other blanket.**

> **Normative — ADR-0262 §7's gate statement is reversed in one limb, and in that limb alone.** The
> verification guarantee **does** cover a capability whose acts make a charge, and a deployment
> wiring one does a **third** thing as part of wiring it, beside §7's two: it **declares
> `charged_output` on every declaration whose acts charge**, a declaration carrying none satisfying
> this guarantee for no `MONEY` criterion at all. **§7's own two obligations are unchanged** —
> declared `postconditions`, and authorisation against a confirmed `Authorization` rather than per
> call.

> **Normative — the gate is not met, this decision adds no condition to it and removes none, and
> the count is still seven.** ADR-0255 §15 item 19's seven conditions stand as ADR-0262 §7
> enumerates them, **ADR-0267 §6's provider-side hold or conditional execution — condition (7),
> which binds exactly the class this decision's comparison speaks of — conspicuously so**. This
> decision is **ratified and not implemented** on the day it ratifies, and the gate asks for
> *"implemented and demonstrated"*. **No lane reads this ADR's ratification, or the merging of any
> lane of it, as the gate being met**, and no lane wires a consequential capability.

### 5. The stronger confirmation is a later act, stated as the interface a later decision fills

> **Normative — evidence stronger than the act's own answer is read in its own turn or as a
> background check, and never inside the end-of-turn phase.** A receipt in email or a line on a
> statement may take hours to arrive (the owner's direction of 2026-09-15, recorded on
> [#2255](https://github.com/leonapivato/ai-assistant/issues/2255)), so the phase **reports what the
> record establishes now and names what is unconfirmed** — which is `unestablished`, `UNCERTAIN` and
> its fixed statement. **No lane waits, polls, schedules, retries or blocks a turn on such
> evidence**, ADR-0262 §9's sequencing forbidding all three of the first.

> **Normative — the interface such a decision fills is stated here as three obligations and as no
> type.** Its evidence is **an act's own recorded answer** — a read step's stored output under a
> declaration, on this decision's own footing and never a model's reading of a message; it reaches
> the dispatch it confirms **through that dispatch's pinned decision** (§1), the pin being the one
> handle on what the act was proved against; and it reports **through the route §3 uses**, a
> criterion's three results at the next turn that engages the goal. **This decision mints no type,
> no field, no Protocol, no seam and no store for it**, and no lane cites this section toward one.

> **Normative — a later act never rewrites what an earlier turn reported.** It re-renders no
> statement, retracts no reply, edits no stored `AttemptOutcome` and reopens no ended attempt:
> **a correction is a fresh comparison at a later turn and never a replay of an earlier one**,
> which is ADR-0262 §6's rule reached by one further case.

### 6. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward any
> of them.

- **The receipt or statement reader itself.** §5 states the interface and no shape for it: not a
  Reader, not a Protocol, not a `ToolDefinition` field, not a turn trigger, not a schedule. Fired by
  the decision that reads such evidence, which owes §5's three obligations and ADR-0262 §9's
  sequencing.
- **A surface that shows the user the two figures.** §3 reports the criterion's result and no
  amount, ADR-0262 §6's `AttemptReport` carrying two fields and naming no figure. Fired by the
  decision that gives a surface the quoted and charged amounts, which owes ADR-0249 §9's
  containment its own argument.
- **Whether the number a declaration names is the whole charge of the act.** ADR-0267 §1 puts that
  obligation on the declaration and §10 books it; **this decision moves it nowhere and checks
  neither half**, for `quoted_output` or for `charged_output`. A declaration naming a booking fee
  where the total is yields a charge that agrees with a quote that agrees with nothing. Fired by the
  decision that gives a declaration a machine-checkable statement of totality, unchanged from where
  ADR-0267 left it.
- **A charge in a currency the quote was not taken in, and any reconciliation between two
  currencies.** §3 compares byte for byte and refuses the pair otherwise, which makes such an act's
  criterion `unmet` rather than converted. **No lane adds a rate, a table, a tolerance or a
  rounding.** Fired by the decision that states what a cross-currency act proves, with its own
  argument against the comparison this decision refuses.
- **A charge read from anywhere but one key of one object, a charge split across legs, and a
  partial or staged charge.** §2 fixes depth one and one key pair, so a tool reporting a deposit and
  a balance, a list of line items, or nothing until settlement yields no charge and its criterion is
  `unestablished`. Fired by the decision stating a wider reading, which owes ADR-0254 §4's
  no-schema rule and ADR-0267 §3's no-model-selector rule, both binding it.
- **Anything in ADR-0262, ADR-0266, ADR-0267 or ADR-0270 beyond the two scopes this decision
  states.** The booking integration, the two routes, the member vocabulary, the quote's producer,
  carrier and freshness, condition 6's seam and what a confirmation renders are each untouched.
  Fired by nothing here.

### 7. What this records under ADR-0082 §1, and what it declines to record

> **Normative — ADR-0262 §2's `MONEY` clause is superseded, and a reader holding only §2 acts
> differently.** That clause reads *"a criterion whose confirmed member is a `MONEY` one is
> `unestablished` … **So no criterion about an amount is ever `met` here and no goal resting on one
> reaches `ACHIEVED`**"*, and gives its ground as *"the charge is not an operand this decision
> has"*. §§1-3 land the operand, so the sentence becomes **false**: such a criterion is now met,
> unmet or unestablished on §2's own machinery. The clause's closing *"No lane reads this as licence
> to compare a charge against a ceiling, a quote or anything else"* is **kept in the direction it
> was written**: §3 compares a charge against the **pinned quote** and, only then, against the
> member — never against a ceiling alone, and never against a quote the goal's tuple holds now.
> ADR-0070 §1's test comes out **supersession**, so §4's scope takes the partial form.

> **Normative — the sweep of every place that reading is available in ADR-0262, and the disposition
> at each, so that the record and the document cannot drift apart.** **Five places**, found by one
> sweep of that document for every clause naming `BoundKind.MONEY`, a charge or a quote: **(a)** §2's
> three-results list, whose `unestablished` limb names *"the criterion's kind is
> **`BoundKind.MONEY`**"* — that limb is **removed**, and the list's other five limbs bind entire;
> **(b)** §2's `MONEY` clause itself, the scope above; **(c)** §2a's unmarked ground that a `MONEY`
> member *"is proved against a quote **before** the act … what this decision does **not** add is the
> *post-hoc*"* comparison — **true of ADR-0262 and left standing**, this decision adding the
> post-hoc half elsewhere; **(d)** §7's gate statement, the second scope; and **(e)** §12's arm
> asserting that *"a `MONEY` criterion is `unestablished` whatever else holds"*, whose two cases the
> implementing lane **restates** under §3's conjunct — an agreeing charge yielding `VERIFIED` and a
> disagreeing one `PARTIAL` — the arm's property, its other criteria and its rung-2 case unmoved.
> **§9's reassignment entry is *fired*, not falsified**: it books this subject here by name and a
> booking discharged is not a clause made false, which is ADR-0262's own test for the seven
> documents that book subjects into it.

> **Normative — ADR-0267 §1's naming sentence is superseded in one limb, and §1's decision is
> upheld.** The unmarked ground beside the no-eighth-field clause reads *"A later record naming one
> quote — a verification finding, say — names it by the act and the digest, which under §2's order
> select **the governing** quote for that pair"*. Under ADR-0089 §3 unmarked text supplies no
> obligation, so what is replaced is a **reading** and not a rule — but a reader holding only §1
> builds this record by that pair and builds it wrong, which is ADR-0082 §1's test met. **The record
> carries the quote by value** (§1). **§1's conclusion is unchanged and reached differently**: no id
> is minted, no eighth field is added, and ADR-0267 §10's *"An identifier of a quote's own … Fired
> by the decision that records a verification finding against the quote it contradicts, **if that
> record needs a handle the pair cannot give**"* is **fired and answered no**, so **no record is
> owed on §10**.

> **Normative — no record is owed against ADR-0254, §15's and §16's clauses included, and the
> working is stated rather than assumed.** **§13** stays true word for word: the pin is an operand
> and not a verdict, nothing reads it to authorise a dispatch, and the recheck reads the current
> governing quote every time (§1). **§15's writer clause** names the three fields the policy sets
> from the record `live_for` returned; `proved_quote` is a **fourth** field the policy sets, from
> the read condition 6 was proved over, and no sentence of §15 becomes false or over-wide — a
> **stacked addition** (ADR-0082 §1). **§16's `PermissionDecision` clause** stays true because that
> record gains **nothing**; **§16's roster** is scoped by its own opening to *"the `core` surface
> **this decision** adds"*, so an addition by another decision falsifies no sentence of it — ADR-0270
> §5's working, re-derived here rather than followed, ADR-0082 §1 ruling that *"the test controls,
> not the label"* and naming *"that a sibling ADR was recorded differently"* as a ground a record
> may not rest on. The discrepancy with ADR-0266 §9's and ADR-0267 §9's scopes on that roster stays
> filed at [#2425](https://github.com/leonapivato/ai-assistant/issues/2425) and is not settled here.

> **Normative — no record is owed against ADR-0192, ADR-0266, ADR-0270 or ADR-0016, and each is
> reached rather than moved.** **ADR-0192 §2's** no-content rule and **§5's** *"never money the tool
> moved"* are **relied on**: they are why the pin does not ride the invocation row and why
> `incurred_cost` is not the charge (§§1-2), and both stay true. **ADR-0266 §7's** two routes, its
> condition 6 and its proof before the act are read and unmoved; **ADR-0270 §2's** `CoverageAnswer`
> is neither read nor widened, this decision adding no member and no field to it; **ADR-0016 §1's**
> declared-not-inferred default is applied, not amended. **ADR-0249 §9's** containment and **ADR-0262
> §6's** two-field `AttemptReport` are obeyed rather than scoped (§3).

> **Normative — the header records this change writes, and they are the whole of it.** ADR-0262's
> and ADR-0267's `Status` lines each take ADR-0070 §4's canonical partial form on **one physical
> line**, this decision's pair added beside any already there and never replacing it, each scope
> naming a clause and carrying **no `ADR-NNNN` token** so that §4's *"every `ADR-NNNN` after the
> leading `Partially superseded by` is a target"* reads true; and each gains the **appended dated
> note** ADR-0070 §1 requires, stating its scope in full. **No other ADR's header is edited**, and no
> file under `src/` or `tests/` is touched by the lane that lands this document.

### 8. The lane cut, and the arms this decision owes

> **Normative.** This ADR is ratified and merged as its own PR before anything implements against
> it (ADR-0015, golden rule 5), and it is implemented in **three lanes and no fourth**. **P1**, the
> `core` record: `PermissionRuling.proved_quote` with its validator and `ToolDefinition.charged_output`,
> in `core/types.py`, and nothing else. **P2**, the pin: `permissions` setting `proved_quote` at the
> ruling, from the read condition 6's evidence route was proved over. **P3**, the verification read:
> §2's charge reading and §3's conjunct inside ADR-0262's comparison, in the subsystem that
> decision's own lane cut puts it in. **No lane wires a consequential capability**, registers a
> booking integration, mints a quote, writes an `Authorization` or touches `wire/`.

> **Normative — the lanes are briefed in that order and each waits on real operands.** P1 is briefed
> after **ADR-0266's L1** (`ActionRequest.intended_action`, `CoverageMember.kind`) and **ADR-0267's
> Q1** (`ActionQuote`, `QuotedOutput`, `GoalQuotes`), without which neither field is typeable. P2 is
> briefed after P1 and after **ADR-0270's lane**, whose `CoverageAnswers` answer is where condition
> 6's evidence route is taken. P3 is briefed after P2 and after **ADR-0262's own L1**, whose
> comparison it adds a conjunct to. **Where a dependency is not in its base, that lane is not
> briefed**, and each lane re-takes this reading at its own base and states what it found. **M33's
> campsite walkthrough's money criterion waits on all three**, which is why #2409 is sequenced
> before it.

> **Normative — neither `PROTOCOL_VERSION` nor any stored shape moves on P1's account alone, and
> the lane states which.** `PermissionRuling` and `ToolDefinition` each cross the wire inside a
> `PermissionDecision` a client decodes, so **P1 carries whatever version bump ADR-0254 §16's
> no-shim rule requires of a widened decoded shape**, decided at its own base against the bumps
> other lanes of this batch land and **never as an integer written into this document**. **No
> compatibility shim, optional-member negotiation or lenient decode is added** (ADR-0084 §3), no row
> is migrated or dropped, and `core/config.py` gains nothing.

> **Normative — the lanes ship the five arms below, each over controlled fakes, and none is
> demonstrated against a live integration or a real charge.**

1. **The pin is set exactly where the evidence route decided something.** A route-(d) `ALLOW` whose
   coverage carries a `MONEY` member met against a governing quote at `"120"`/`"EUR"` records that
   quote on the ruling and on the decision `from_request` builds; the same request with a coverage
   carrying no `MONEY` member, one whose member is met by no route, a `CONFIRM`, a `DENY` and a
   route-(a) `ALLOW` each record **none**; where the goal holds two quotes naming that action the
   pin is **the last**; and `PermissionRuling` **refuses construction** with `proved_quote` set and
   `authorised_by` unset.
2. **The pin is a value and not a pointer.** A quote appended to the goal after the ruling leaves the
   pinned value **unchanged**, and a comparison over the pinned decision reads the earlier reading —
   the arm that fails an implementation which re-selects by act and digest at read time.
3. **The charge reading is total and fail-closed.** Over one stored output, `charged_output` naming
   `amount` and `currency`: a JSON string, a JSON integer, a JSON **float**, a JSON **boolean**, a
   negative value, a missing key, a non-object output, `"usd"` and `"EURO"` — the first two yield a
   charge and the rest yield **none**, and a declaration carrying **no** `charged_output` yields
   none. **A `bool` is not an `int` here**, the arm failing an implementation written as an `int`
   instance test.
4. **The comparison and the finding.** Against a pin at `"120"`/`"EUR"` under a member bounded at
   `150`/`EUR`: a charge of `"120"` and a charge of `"100"` each **hold** the test; `"130"` **fails**
   it though it is under the ceiling — the mismatch the ruling calls a finding; `"120"`/`"USD"`
   **fails** it; and a step with no pin, or under a declaration with no `charged_output`, leaves the
   test **not taken**. The criterion is then `met`, `unmet` and `unestablished` respectively, and a
   `FAILED` step is decisive in **no** case.
5. **The finding is reported and prevents nothing.** A failing test yields `unmet`, an
   `AttemptOutcome` of `PARTIAL` where another criterion is met and `FAILED` where none is, and an
   `AttemptReport` carrying **exactly two fields** and no figure; and across the comparison **no
   `Authorization` is written, settled or revoked, no decision is recorded, no dispatch is refused
   and no store is written**.

### 9. This ADR classified, marked, and how it is ratified

> **Normative.** Under ADR-0070 §1's test this is a **supersession and not an amendment**: a reader
> holding only ADR-0262 §2 or §7, or ADR-0267 §1, would act differently, so §7's two records take
> ADR-0070 §3's and §4's partial form. Every other reach of this decision is a **stacked addition**,
> recorded in this document and nowhere else (ADR-0082 §1, §7).

> **Normative.** It is a **contract** decision — it widens `core/types.py` — so under ADR-0015 §1 it
> is reviewed by **both** lenses while `Proposed`, ratified by `just adr-ratify`'s one-line flip, and
> merged as its own PR before anything implements against it.

> **Normative.** This ADR is **marked** under ADR-0089: every obligation it imposes is in a clause
> of §2's grammar, and unmarked text beside a mark is read to determine what that mark means and
> supplies no obligation of its own (ADR-0089 §3).

## Consequences

**A goal that spends money can reach `ACHIEVED`.** Today it cannot, by a rule rather than by an
accident: ADR-0262 §2 refuses every `MONEY` criterion for want of an operand, so the owner's own
campsite walkthrough stops at `UNCERTAIN` however well the booking went. After this, the operand is
the quote the dispatch was actually proved against, carried by value on the record that proved it,
and the comparison is three conjuncts over values the record already holds.

**A charge that exceeds the quote is visible, and it was not before.** The one comparison available
until now — charge against ceiling — passes the case the owner's ruling singles out. Against the
pinned quote it does not: a €130 charge on a €120 quote under a €150 ceiling is a finding, and the
turn says the criterion was not established rather than reporting a success.

**And it is a report.** Nothing here refuses a dispatch, revokes a row or claws anything back; the
act has run by the time the comparison is taken. What binds spending stays ADR-0266 §7's proof
**before** the act, and ADR-0267 §6's provider-side hold stays the seventh gate condition, unmet.

**What becomes harder.** `core/types.py` gains two fields, both BREAKING, and three lanes queue
behind five other decisions' lanes — the cost golden rule 5 makes visible. A deployment wiring a
charging capability now declares a third thing, and a declaration that omits it satisfies this
guarantee for nothing, which is a silence a reader must know to look for. And a user shown a
mismatch is shown that the criterion failed and not the two numbers, because `AttemptReport` carries
two fields and names no figure.

**What would trigger revisiting this.** A provider whose charge arrives only on a statement, which
§5's later act is the shape of and which nothing here reads. A capability charging in a currency it
was quoted in a different one. And a surface that wants the two figures, which widens ADR-0262 §6's
report rather than anything decided here.

## Alternatives considered

**Pinning the quote to the `ToolInvocation` claim.** Refused in §1 and §2. ADR-0192 §2 makes that
row carry **no content** — not an argument, not an output, not a digest of one — for ADR-0004 §5's
reasons, and a quote is content. The row is also minted by the ledger in `tools/`, which is neither
where the comparison was taken nor where a policy writes.

**Comparing `ToolInvocation.incurred_cost` against the pin.** Refused in §2. ADR-0192 §5 rules that
field *"the price of the invocation … never money the tool moved, and no lane reads it as a
transacted amount"*. It is what calling the tool cost, not what the act charged, and reading it as
the charge would compare a fee against a booking.

**A `permissions`-owned record keyed by the decision id.** Refused in §1. It is a second store, a
second write and a second thing to keep in step with the trail, for a fact that belongs to exactly
one ruling and is already carried to the durable record by a path ADR-0254 §16 built for this shape.
A record joined by id is also a record that can be missing, which would make a criterion's verdict
depend on whether a second write landed.

**Naming the pinned quote by the act and the digest, as ADR-0267 §1 predicts.** Refused in §1. The
pair selects **the governing** quote at the instant of the read, so a refresh appended after the
dispatch silently moves what the pin means, and ADR-0267 §2's elision can drop the reading entirely.
The alternative to carrying the value would be minting a quote identifier, which ADR-0267 §1
declined and which §10 fires only where the record needs a handle — this one does not.

**Reusing `quoted_output` as the charge key.** Refused in §2. ADR-0267 §4's mint appends a quote
from that key on the acting step's own output, so the comparison would be taken against the acting
step's own reading — the third of the four wrong operands #2409 enumerates, reached by a different
door.

**Comparing the charge against the ceiling alone and calling that the confirmation.** Refused
throughout. It passes exactly the case the owner's ruling names a finding, and ADR-0262 §9 already
records that it *"is not that comparison either"*.

**Widening `AttemptReport` with the quoted and charged amounts.** Refused in §3. ADR-0262 §6 fixes
that model at two fields and rules that no statement names a figure, on ADR-0249 §9's containment;
a figure on a report is a disclosure surface nobody has specified, and §6 books the decision that
would.
