# 267. A quote is a record the goal holds in order, read from the output its declaration names,
and no local check proves it still true

- Status: Proposed
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **two narrowly stated scopes, and §9 shows the working for both. §11's
  `AuthorizationProjection`, in its field list and in one limb of its restart clause**: that model
  is declared as carrying *"exactly `coverage` … and `expires_at`"*, and it gains **`quote`**, a
  `QuoteView | None` required with no default, carrying the figure the act was quoted at beside the
  ceiling the answer would establish — without which §11's own construction, *"A confirmation that
  establishes a bound without naming it is not a confirmation of that bound"*, is unmet for the one
  bound whose proof is a price the user was never shown. **And its restart clause's *"renders the
  same projection"*** is true of the three facts the row carries and false of the fourth, which is
  re-read: where a refresh landed between the question and the restart, the refreshed figure is
  rendered — the fail-closed direction, since ADR-0254 §13's recheck compares the act against that
  same later quote. §11's rendered-from-the-proposed-row rule, its `CoverageView` as ADR-0266 §9
  leaves it, its possibly-empty coverage, its one-carrier argument, its renders-no-internal-value
  bar, its listing, its revocation surface and `TurnOutcome.authorizations` bind entire. **§16's
  `core`-surface roster, in two limbs**: `core/types.py` gains a **fifteenth**, **sixteenth**,
  **seventeenth** and **eighteenth** type — `ActionQuote`, `QuotedOutput`, `ActionQuoteMinting` and
  `QuoteView`; and an **eighth**,
  **ninth**, **tenth** and **eleventh** field — `ToolDefinition.quoted_output`, `Goal.quotes`,
  `Goal.quotes_elided` and `AuthorizationProjection.quote` — counting from where ADR-0266 §9 left
  the roster at fourteen types and seven fields. A reader holding only §16 implements a roster test
  that fails on this decision's own surface. **§16's `PermissionDecision` clause is untouched**:
  that record gains nothing here. Every other clause of §16 binds entire — the lane attribution of
  every roster entry, the `core/errors.py` roster, *"`core/config.py` gains nothing at all"*, the
  `PROTOCOL_VERSION` clause and the transcribe-the-ruling-whole rule. **`core/protocols.py`'s
  roster is a widening §16 does not close**, and §9 says why it takes no scope.
- **Partially supersedes** [ADR-0016](0016-tool-definition-and-registry.md)
  — **one scope, in §1, and it is the scope ADR-0254 §18 and ADR-0266 §9 have each already taken
  there, reaching one further field**: the `ToolDefinition` model declaration and the required-field
  clause in the application to `quoted_output` alone. A reader holding only §1 authors a definition
  that names no output a price is read from, so no act under it is ever quoted and every one asks.
  **The exception is taken on §1's own test applied afresh and not on the two records beside it**,
  which ADR-0266 §9 expressly forbids being read as a licence: absent makes the **opposite** claim
  to the one §1 refuses, a declaration naming no quoted output producing no quote at all, so the
  default costs a question and can never authorise a call. Requiring the field would oblige every
  declaration and fixture in the tree to write `None` for a fact that is absent on almost all of
  them, and would refuse every `ToolDefinition` written before it. **The exception is this one
  further field**, and every other clause of §1 binds entire.
- **Partially supersedes** [ADR-0255](0255-the-driver-walks-a-plan-in-dependency-order-claims-each-step-under-its-attempt-and-stops-rather-than-acting-under-an-unfinished-one.md)
  — **one scope, and it is a count. §15 item 19's enumeration of what must hold before a
  consequential capability is wired — *"**five** conditions and not three"*, which ADR-0265 made
  six — becomes seven**, the seventh being §6's freshness prerequisite: a capability whose acts are
  authorised through a `MONEY` ceiling is wired only where the provider offers a hold or a
  conditional execution that validates the quoted amount atomically with the act. A reader holding
  only item 19 wires such an integration after six and is wrong, because none of the six reaches a
  quote that was true when it was read and false when the charge was made. **§13's rule binds
  verbatim and is relied on**, and its own *"this decision adds **two** prerequisites"* stays true
  of that decision — what grows is the gate's total. §§1-14 and §§16-17 stand entire, and §15's
  every other item is untouched.
- **Partially supersedes** [ADR-0249](0249-the-goal-carries-its-interpretation-the-attempt-carries-the-phase-and-the-planner-returns-its-understanding.md)
  — **one scope. §1's `Goal` model declaration, in the field count alone**, which ADR-0250 and
  ADR-0265 have each taken before: `Goal` gains **`quotes`**, a possibly-empty
  `tuple[ActionQuote, ...]` that is append-only and oldest first, and **`quotes_elided`**, an `int`
  `ge=0` counting what its history has dropped — so a reader holding only §1 authors a goal that
  can hold no quote and every `MONEY` ceiling of it is proved against nothing. §1's append-only
  interpretation rule, its `statement`-as-projection rule, its four-absences clause and its
  `version` clause bind entire; **§2's elision is relied on and is the shape §2 of this decision
  reuses**; and §§3-17 stand entire.
- Date: 2026-09-15

## Context

### Where this comes from

ADR-0266 decides what a `CoverageMember` records, how a stated span becomes one, and what a `MONEY`
ceiling is proved against — **a quote for the goal's intended action, over the very arguments the
call carries**. It states that quote as an **interface** and reads it from nowhere concrete: §6
names the four facts §7's comparison is written over and then rules that it settles *"no type, no
field of any existing model, no store member, no Protocol, no bound on how many a goal holds, no
rule about which component records one, no expiry and no face by which a policy obtains one"*, and
§10 calls that *"the largest thing this decision does not settle"*. Until it lands, §7's evidence
route has no operand: every `MONEY` member is unmet, ADR-0254 §1's completeness condition proposes
no row, and every act of a goal whose user stated a price asks. This is that decision, cut out of
ADR-0266 so that the proof rule and the machinery feeding it are two reviewable documents rather
than one (issue #2387).

The owner's rulings of 2026-09-14 are the shape it has to take. **The price is a consequence of the
chosen parameters and usually not an argument the assistant supplies** — *"The tool takes what the
action needs (site, dates, party size)"* — so the primary proof is a record the **investigation**
made and the **authorisation** phase reads, and *"nothing is compared at dispatch"* names the price
rather than the call. **No quote means the price cannot be proved**, which is *"feasibility, not a
tool restriction"*: investigate first, or ask. And the addendum fixes the safeguard on the
arguments: *"the evidence covers a step only when the step's arguments are the ones that were
quoted … Any difference — including extras filled in after quoting — means the quote does not cover
the booking: re-quote or ask."*

### The gap this closes, stated as the failure the corpus has today

At this decision's base the corpus can state a ceiling and can compare one, and can obtain no
number to compare. ADR-0266 §7's evidence route selects *"the governing quote"* from *"the quotes
available to the policy (§6)"* — a set no type holds, no store writes and no seam returns. A lane
implementing it either stops, as #2373 stopped, or invents a carrier no clause authorises. The
three inherited constraints are what make the invention dangerous rather than merely undecided: a
quote cannot ride a `GoalEvidence` row as that type stands (§1 of this document weighs it), **no
model may choose which number the quote is** — against an output `{"price": "200", "stars": 4,
"currency": "EUR"}` a plan-carried selector naming `stars` produces a quote of `4`, which satisfies
a `150` ceiling and authorises the `200` purchase — and a quote true when it was read and false
when the call was made authorises an over-bound charge that no local mechanism detects.

### The tree, read rather than assumed, at `origin/main` `804acabb`

**Nothing this decision builds on is implemented.** `IntendedAction`, `Goal.intended_actions` and
`PlanStep.intended_action` are ADR-0265's and are ratified and unwritten; `BoundedArgument`,
`CoverageMember.kind`, `ToolDefinition.bounded_arguments` and `ActionRequest.intended_action` are
ADR-0266's and are ratified and unwritten; `CoverageView` and `AuthorizationProjection` are
ADR-0254 §11's and are in flight on PR #2393. A grep over `src/` for `IntendedAction`,
`BoundedArgument` and `ActionQuote` returns nothing. What **is** in the tree and is relied on: `ToolDefinition`
with `system_supplied` and its required-field exception; `ActionRequest.parameters_digest`, a
`property` computing `sha256` over the canonical encoding, and `Sha256Hex`, the validated type
`PermissionDecision.parameters_digest` already carries; `StepOutputRef`, ADR-0253 §6's one spelling
of a place in a step's output; `ValueBound` with `currency: EncodableText | None`; `Goal` with its
`interpretation` tuple and `interpretation_elided` count; `GoalAuthorizations`, whose docstring
records ADR-0254 §16's rule that *"`live_for` is the only member and no lane adds a second"*;
`PlanStore` with its twenty-seven members; `MAX_GOAL_EVIDENCE` at 64 and `MAX_EVIDENCE_RECORDS` at
32; and `PROTOCOL_VERSION` at 43.

### What this ADR is not allowed to settle

It is the quote's machinery and nothing wider. It does not touch ADR-0266 §7's comparison — it
supplies that comparison's operand and the seam it is read through, and every rule about **what
covers a request** stays where ADR-0266 ratified it. It does not decide the booking integration,
the simulated booking service's shape, or anything M33 owes (#2255). It draws no line through
`system_supplied` — ADR-0266 §10 books that elsewhere and §6 of this document states what it costs
here. And it verifies nothing: the actual charge is A10's, on the owner's ruling that a
quote/charge mismatch is *"a reported finding"*.

## Decision

### 1. `ActionQuote`: the record, and the four facts it supplies to the comparison

> **Normative.** `core/types.py` gains **`ActionQuote`**, a frozen model with `extra="forbid"`
> whose fields are exactly seven: **`intended_action`**, an `Identifier`, the `IntendedAction.id`
> (ADR-0265 §1) this price was read for; **`arguments_digest`**, a `Sha256Hex`, **the
> `parameters_digest` of the `ActionRequest` whose output it was read from** and never a value
> computed a second way; **`amount`**, a `Decimal`, finite and not negative; **`currency`**, an
> `EncodableText`, the ISO-4217 code ADR-0254 §4's `MONEY` reading compares byte for byte;
> **`plan`**, an `Identifier`; **`read_from`**, a `StepOutputRef`; and **`read_at`**, a
> `UtcInstant`. It carries no eighth field: no id of its own, no attempt, no tool, no capability,
> no expiry, no status, no `BoundKind` and no count.

> **Normative — the four facts ADR-0266 §7 reads are the first four fields, and the last three are
> provenance no comparison reads.** §7 compares the act, the arguments, the amount and the
> currency; **`plan`, `read_from` and `read_at` are read by no clause of ADR-0266, by no route of
> this decision and by no test of either**. No lane computes an expiry from `read_at`, refuses a
> quote for its age, orders quotes by it, or resolves `read_from` into a value. They are on the
> record so that a reader auditing a charge can say where the number came from and when, which is
> `GoalEvidence.read_at`'s own footing, and the prohibition is stated because the alternative is a
> later lane reading an unenforced expiry back in — ADR-0252 §1's *"sufficiency never reads a
> count"* is that prohibition's shape one record over.

> **Normative — the amount is the whole charge the act will make, and this is the obligation
> ADR-0266 §6 puts on this decision.** *"not a fee, not a deposit, not a per-unit rate, not one leg
> of a transfer"* — a quote of a €1 fee for a €200 transfer satisfies a €150 ceiling while the act
> breaches it. **The obligation binds the declaration** (§3), whose `quoted_output` names the key
> carrying the total; **no code checks that it does**, and §10 books that residual with what fires
> it. A record stating a component is not a quote under this interface rather than a conforming
> one, and the mint mints no quote it cannot read as a total from the key the declaration named.

> **Normative — the digest is `ActionRequest.parameters_digest` on both sides and there is no
> second canonicalisation.** The quote carries the quoting request's own property value; ADR-0266
> §7 compares it to the acting request's own; the encoding is ADR-0021 §1's, computed in the one
> place that computes it. **Every argument of the quoting call is inside it, system-supplied keys
> included**, ADR-0266 §6 ruling that no declaration classifies a per-call identity today and that
> the exclusion is another decision's. **The cost is stated rather than hidden**: a quoting call
> and an acting call differing in **any** key — a `payment_method` filled in afterwards, an
> idempotency key `orchestration` fills per call — carry different digests, are covered by no
> quote, and ask. That is the owner's *"re-quote or ask"* read at the one place it can be enforced
> mechanically.

**`plan` is carried because a step id alone names no place.** ADR-0266 §10 refuses `PlanStep.id` as
a durable client reference on the ground that `_step_ids_are_unique` guarantees uniqueness *"within
a plan"* alone, and the same fact reaches provenance: a goal that has replanned holds two plans
whose steps may share an id, so `read_from.step` without the plan it belongs to points at two
places. The pair is one fact — where the number was read — spelled as the two values needed to
resolve it, and `StepOutputRef` is reused rather than restated because ADR-0253 §6 makes it *"the
one spelling of that"*. **Its six unresolvability cases are untouched and unreached**: they bind a
reference something resolves, and nothing resolves this one.

**The record carries no id of its own, and that is decided rather than forgotten.** A later record
naming one quote — a verification finding, say — names it by the act and the digest, which select
it deterministically under §2's order, so an identifier would be a second handle on a value already
addressable. §10 books the case that would need one with what fires it.

### 2. The quote lives on the goal, in order, bounded by an elision that can only cost a question

> **Normative.** **`Goal` gains `quotes`, a possibly-empty `tuple[ActionQuote, ...]`, oldest first
> and append-only, and `quotes_elided`, an `int` `ge=0`.** No lane edits a member in place,
> reorders the tuple, or removes a member other than by the elision below. **The tuple's order
> *is* the total order ADR-0266 §6 requires**: no instant is compared, no sequence number is
> minted and no tie-break exists to get wrong. **The governing quote for an intended action is the
> last member naming it**, and where none names it there is no quote for that action — which is
> ADR-0266 §7's *"latest in §6's order"* read off the record's own shape.

> **Normative — the tuple is bounded by an elision and not by a refusal, and the bound is
> `MAX_ACTION_QUOTES`, a `Final[int]` of `core/types.py` valued at 64** — `MAX_GOAL_EVIDENCE`'s and
> `MAX_INTENDED_ACTIONS`' figure, for a durable per-goal sequence of the same shape. An append that
> would carry a goal past it **drops members from the front**, oldest first, and advances
> `quotes_elided` by exactly as many as it dropped. **Silent truncation is not available**
> (ADR-0086 §4), and the count never decreases.

> **Normative — an elision never revives a superseded quote, and that is what makes it safe where
> ADR-0265 §1 refuses one.** Members are dropped from the front alone, so within any action the
> **last** quote is the last to go: an elision either leaves the governing quote where it was, or
> leaves that action with no quote at all, in which case ADR-0266 §7 leaves the request **uncovered
> and the act asks**. **No elision can make an earlier reading govern.** ADR-0265 §1's refusal of
> elision is honoured rather than contradicted: *"an identity that can vanish is not an identity"*,
> and what vanishes there is the scope of an at-most-once claim, so a dropped identity is a
> duplicate booking *"nobody could detect afterwards"*. A dropped quote costs a question.

> **Normative — `PlanStore` gains one member, and this is a **BREAKING** contract change under
> golden rule 5: `record_quote(minting: ActionQuoteMinting) -> Goal`** — appends one `ActionQuote`
> to the named goal's `quotes`, applies the elision above, advances `version`, and returns the
> stored goal. `core/types.py` gains no command type for it beyond what §1 lands: **`minting` is
> `ActionQuoteMinting`, a frozen model with `extra="forbid"` carrying exactly `goal_id`, `quote`
> and the `expected_version` it was computed against** — `IntendedActionMinting`'s shape one record
> over. **The write is compare-and-swap and the store takes a command, not a snapshot**, on
> ADR-0014 §5's discipline as ADR-0249 §12 states it: the read, the comparison and the write are
> one indivisible step, and a stale write raises the class `StaleExecutionError` occupies.

> **Normative — the store validates nothing about the number and refuses one thing.** It refuses a
> `quote` whose `intended_action` is not the `id` of a member of that goal's `intended_actions` at
> the instant of the append, writing nothing, on the error class ADR-0249 §12 gives `save_goal` for
> a goal whose id it already holds — an invariant breach at the current version rather than a lost
> race. **It applies no other test**: not the amount, not the currency, not the digest, not the
> provenance, and **no test of whether this quote refreshes an earlier one** — a refresh is
> position in the tuple and not a predicate, so there is nothing for a store to evaluate and no
> second place the rule could live (ADR-0252 §12's split, kept).

**It lives inside the goal rather than in rows of its own, and the cost was weighed.** ADR-0252 §1
is the obvious neighbour and it is refused in §9's terms: a quote is *"a second copy of what was
read"*, which is exactly what that section rules a `GoalEvidence` never carries, and squeezing one
in supersedes four limbs of one ratified section for no gain. What is left is a tuple on the goal
or a row store beside it. **The tuple is chosen for the order.** ADR-0249 §1's `interpretation` and
ADR-0265 §1's `intended_actions` are two precedents on this very model, each chosen because
position is an order nothing can disagree about; a row store's order is its insertion order, which
is a fact an implementation holds rather than a property of the record. **And three obligations
come free with it**: `delete_goal`'s cascade reaches a quote because it is inside the goal,
ADR-0014 §5's export-closure rule is satisfied by construction because `PlanExport.goals` already
carries it, and `PlanExport` gains no member. What the row store would have bought is no
`Goal.version` churn on an append, and ADR-0265 §5 took that same cost on this same model for a
record of the same durability.

### 3. The producer: the declaration names the output a price is read from, and nothing else names it

> **Normative.** `core/types.py` gains **`QuotedOutput`**, a frozen model with `extra="forbid"`
> whose fields are exactly two: **`amount`**, an `EncodableText` naming a key of the step's
> `output` at depth **one**, whose value is the **whole charge** the act will make (§1); and
> **`currency`**, an `EncodableText` naming the key at depth one carrying that amount's ISO-4217
> code. **A model validator refuses `amount` equal to `currency`.** Depth is one and no lane adds
> an addressing syntax to either — `StepOutputRef.field`'s rule, stated once more where it governs.

> **Normative.** **`ToolDefinition` gains one field, `quoted_output: QuotedOutput | None`,
> defaulting to `None`.** It is the whole of what a declaration says about where a price may be
> read from its output. **A declaration carrying `None` yields no quote ever**, so every act proved
> against a quote of that declaration's output is uncovered and asks — the fail-closed direction,
> and the ground on which §1 of ADR-0016 takes the default. This is a **BREAKING** contract change
> to `core/types.py` under golden rule 5 and is flagged as one.

> **Normative — the field that selects the number lives on the declaration and on nothing a turn
> produces, and that is the whole answer to *no model chooses which number the quote is*.** **No
> plan, no plan step, no planner envelope, no `ActionRequest`, no `Authorization` and no
> `CoverageMember` carries a key a price is read at**, and no lane adds one. A declaration is
> authored once by an integration author and reviewed once; a plan is authored by a model on every
> turn. Against `{"price": "200", "stars": 4, "currency": "EUR"}` a plan-carried selector naming
> `stars` quotes `4`, satisfies a `150` ceiling and authorises the `200` purchase — a number of the
> right **shape** in the wrong **slot**, which no validation of shape catches, which ADR-0254 §3's
> *"can satisfy … and can never supply"* arm does not reach because the harm is a too-**small**
> value, and which ADR-0254 §15's writer clause forbids at its source rather than detecting
> afterwards. ADR-0266 §8's *"A model names no argument key, no currency key and no identifier
> anywhere in this decision"* is adopted whole and extended by one: **no output key either.**

> **Normative — one quoted output per declaration, never a tuple.** A declaration states where its
> price is or states nothing. **A second would need a selection rule at the mint**, and every
> candidate for one is refused already: by kind is ADR-0266 §7's rule about members and says
> nothing about outputs, by the plan is the clause above, by a schema keyword is ADR-0254 §4's
> *"No reading consults a schema to decide what an argument means, and there is no exception"*, and
> by order is arbitrary. A tuple admitting exactly one member is a one-member rule somebody has to
> remember at the read; an optional single value is the same fact with nothing to remember.

### 4. The mint: one step output yields one quote, and every failure of the reading refuses it

> **Normative — `orchestration` mints a quote after a step succeeds, where all five hold, and in no
> other case.** The step is `SUCCEEDED` and its `verifies` holds; the plan step carries an
> `intended_action` (ADR-0265 §4); the declaration the step was bound to carries a `quoted_output`
> (§3); the step's `output` is a JSON **object** carrying, at the key that declaration's
> `QuotedOutput` names as its `amount`, a JSON **string** that `Decimal` accepts or a JSON
> **integer**, whose `Decimal` is finite and not negative; and it carries, at the key it names as
> its `currency`, a JSON **string**. The
> quote is then written by `record_quote` (§2) with `arguments_digest` taken from the request that
> produced that output, `plan` and `read_from` naming where it was read, and `read_at` the instant
> the step's output was recorded.

> **Normative — every failure of that reading mints nothing, and nothing is repaired, coerced,
> defaulted or substituted.** A step with no `intended_action`, a declaration with no
> `quoted_output`, an `output` that is not an object, a missing key at either name, a **JSON
> floating-point** amount, a non-finite or negative one, or a currency that is not a JSON string
> each leave the goal's `quotes` **unchanged** and raise nothing. **A JSON float is never a price**
> — ADR-0254 §4's own refusal, taken at the mint as well as at the comparison, because a binary
> float rounded into a `Decimal` at the mint would be an unproven comparison the policy could no
> longer see. The consequence in every case is that the act is proved against no quote and asks.

> **Normative — the mint reads the step's own output, its own request and its own declaration, and
> reads nothing else.** Not another step's output, not a memory, not a preference, not a
> `Settings` field, not a second call, not a model. **It never asks for a number and never derives
> one**: no arithmetic over two outputs, no sum of components, no unit conversion, no currency
> conversion, no rounding and no quantisation. A price this system computed is a price no provider
> quoted.

> **Normative — a quote is minted for the acting step's declaration's price as often as one is
> read, and a second reading is an append and never an edit.** Re-reading a price for the same
> intended action appends a new quote, which then governs (§2); **no lane marks, supersedes,
> invalidates, edits or removes the quote it displaced**, and none is needed, because the order
> already says which governs and ADR-0266 §7 rules that *"An earlier quote is consulted in no
> case"*. ADR-0252 §7's *"a refresh supersedes the row it displaces"* is honoured by position
> rather than by a mark, which is the whole reason §2 puts the record in an ordered tuple.

### 5. How the policy obtains one: a new Protocol, keyed and never asked, failing closed

> **Normative.** `core/protocols.py` gains **`GoalQuotes`**, a Protocol with **one** member and no
> lane adds a second: **`for_action(goal: Identifier, intended_action: Identifier) ->
> tuple[ActionQuote, ...]`**, returning that goal's quotes naming that action **in the order the
> goal holds them**, possibly empty. This is a new Protocol, so **the triad is owed in one change**
> — the Protocol, its shared conformance suite, and a canonical fake in `ai_assistant.testing`
> (`CONTRIBUTING.md` → "Adding a Protocol"). It is a **BREAKING** contract change to
> `core/protocols.py` under golden rule 5 and is flagged as one.

> **Normative — the seam is keyed and returns records, and the selection is `permissions`'.** It
> filters by the two identifiers, which are facts it holds, and evaluates **no** predicate: it does
> not select the governing quote, does not compare a digest, does not compare an amount and does
> not read a `CoverageMember`. **`permissions` takes the last member of what comes back**, which is
> ADR-0266 §7's *"One implementation, in `permissions`"* kept whole — a store that selected would
> be a second place the governing rule lives, and the first conforming implementation to read it
> differently would be right in one of them. **The keying is the narrow face** `GoalAuthorizations`
> is: a policy is handed this and never `PlanStore`, so it cannot name `record_quote`.

> **Normative — a fault is not an absence, and the direction is `GoalAuthorizations`'.** A
> `for_action` that cannot answer raises `AuthorizationError` and **no implementation converts it
> into an empty tuple**. The request is then **not covered**, ADR-0254 §6's bar is taken, no
> standing route is taken at all, and the ruling is the `CONFIRM` the request would have drawn had
> the user authorised nothing — ADR-0266 §7's *"A fault is never an absence"* given the seam it was
> stated about. **No new error class is minted**, and no lane falls through to the argument route.

> **Normative — what no quote produces, and it is never a silent establishment.** Where the seam
> returns an empty tuple, or the governing quote's digest differs from the request's, the member is
> unmet and the request is uncovered — ADR-0266 §7, restated here for no reason but that this
> decision supplies the operand. **No component mints a quote, supplies a default amount, treats an
> absent quote as zero, reads a ceiling as a price, or lowers a bound to make a comparison
> succeed.** **Which of the owner's two dispositions follows is not the policy's to choose**: the
> policy rules `CONFIRM` and `orchestration` decides whether to put that question or to investigate
> first and re-quote. ADR-0254 §1's completeness condition means no row is proposed either way, so
> the one call is authorised by route (a) or not at all.

**The composition root wires the plan store here, and that is golden rule 1 rather than an
exception to it.** The quotes are inside the `Goal`, so the object that answers `for_action` is
`planning`'s store; `permissions` names only the `core` Protocol and `app/` passes the concrete, as
it already does for `GoalAuthorizations`. A conforming store satisfies `GoalQuotes` structurally,
which is that seam's own stated construction — *"a composition root may pass one object to each
seam; what a policy cannot do is **name** `record`"*.

### 6. Freshness: a stale quote authorises exactly what a fresh one does, and the gate is where that is answered

> **Normative — nothing in this decision expires a quote, and no comparison of ADR-0266 §7 reads
> its age.** A quote governs until a later one for the same action displaces it (§2), however long
> ago it was read. **No lane refuses a quote for being old, computes a validity window from
> `read_at`, compares `read_at` to the instant of dispatch, or adds an expiry field.** The window
> between the reading and the charge is **open**, and this decision says so rather than appearing
> to close it.

> **Normative — an unenforced expiry and elapsed-time proximity are each refused, and the refusal
> is the point.** A `read_at + Δ` test refuses a quote that is still true and admits one that is
> already false, because Δ is a guess about a provider's pricing and the provider is the only party
> that knows. **A local compare-and-swap is not a proof either**: a store transaction observes
> stored values, and what a comparison needs to observe is the provider's current price at the
> instant of the act. A mechanism that looks like a freshness check and is not is worse than none,
> because a reader stops asking for the one that would work.

> **Normative — what actually closes it is provider-side, so it is a prerequisite on wiring rather
> than a rule in `permissions`.** **ADR-0255 §15 item 19 gains a seventh condition**: a
> consequential capability **whose acts are authorised through a `MONEY` ceiling** is wired only
> where the provider offers an enforceable **hold** on the quoted amount, or a **conditional
> execution** that validates the quoted amount atomically with the act and fails the act where it
> does not hold. **The seventh binds that capability alone** — a capability no `MONEY` ceiling ever
> authorises is unaffected and the gate's other six reach it unchanged. **No lane wires such a
> capability on elapsed-time proximity, on a local re-read, or on a re-quote taken before the call
> in the same process**, each of which is the refused mechanism under another name.

> **Normative — until such a capability is wired, the residual is disclosed rather than mitigated,
> and the disclosure is the figure itself.** §7's projection renders the quoted amount and the
> instant it was read beside the ceiling, so the user answering is shown the number the proof rests
> on and how old it is. **That is a disclosure and not a check**: no clause makes a user's assent a
> warrant that the price is still current, and no lane reads the rendering as discharging the
> condition above. A10's verification reports the charge afterwards, on the owner's ruling, and a
> mismatch is a finding rather than a prevention.

**This is the honest half of the answer and the corpus has taken it before.** ADR-0148 §1's trade —
*"Refusing costs a recoverable error the user sees; proceeding costs a disclosure nobody can detect
afterwards"* — is why the gate condition is a refusal to wire rather than a tolerance to configure.
The alternative designs all put a check where the fact is not: a shorter Δ, a re-quote immediately
before the call, a hash of the provider's page. Each narrows the window and none closes it, and a
narrowed window is the failure mode that arrives rarely enough to be attributed to something else.

### 7. The rendering: the figure the act was quoted at, beside the ceiling the answer establishes

> **Normative.** `core/types.py` gains **`QuoteView`**, a frozen model with `extra="forbid"` whose
> fields are exactly three: **`amount`**, a `Decimal`; **`currency`**, an `EncodableText`; and
> **`read_at`**, a `UtcInstant`. It carries **no** digest, no intended action, no plan, no step, no
> goal id and no authorization id — ADR-0254 §11's renders-no-internal-value bar, unrelaxed.

> **Normative.** **`AuthorizationProjection` gains one member, `quote: QuoteView | None`, required
> with no default.** It carries the **governing quote through which the proposed row's `MONEY`
> member was met**, and is **absent** — not defaulted — where the row carries no `MONEY` member or
> where the member was met on ADR-0266 §7's argument route alone. **A confirmation that renders a
> ceiling without the figure the act was quoted at is not a confirmation of that charge**, which is
> ADR-0254 §11's own construction — *"A confirmation that establishes a bound without naming it is
> not a confirmation of that bound"* — read onto the value the bound is proved against.

> **Normative — it is transcribed and never re-derived, and the engine transcribes it.** ADR-0254
> §1's completeness condition is evaluated before the row is proposed, and evaluating it selected
> the governing quote; **the engine puts that quote's three values on the projection and no surface
> re-selects one**. ADR-0254 §11's *"the recorded values by transcription and not a second
> derivation of them"* binds this member as it binds the coverage, and an adapter reads neither the
> trail nor a `PermissionDecision` (ADR-0042 §6).

> **Normative — a restart re-reads the quote, and where a refresh landed the refreshed figure is
> rendered.** ADR-0254 §11's restart clause recovers the durable row and renders the same coverage,
> the same bounds and the same `expires_at`; the quote is on the goal and not on the row, so it is
> re-selected under §2's order. **This is the fail-closed direction and is stated rather than
> engineered around**: ADR-0254 §13's recheck compares the act against that same later quote at
> dispatch, so rendering the older figure would show the user a number the ruling would not use.
> **The listing renders no quote**, and §10 books that with what fires it.

### 8. Writer clauses, and what no model does

> **Normative.** **`orchestration` mints every `ActionQuote`, and nothing else does.** No
> `ActionPolicy`, no `ToolRegistry`, no store, no reader, no interface adapter, no tool and no
> model **constructs, writes or repairs** one — ADR-0254 §15's writer clause reaching the values
> this decision adds, and ADR-0266 §8's shape one record over. **A `ToolDefinition.quoted_output`
> is authored where every other field of a declaration is authored**, by the integration, and no
> component of this system writes, edits, infers or repairs one at run time.

> **Normative — no durable value of this decision is ever taken from a model, and the list is
> exact.** A planner envelope carrying an **`ActionQuote`**, a **`QuotedOutput`**, a **`QuoteView`**,
> an amount, a currency, an output key or an arguments digest has those values **discarded
> silently** — not an error, not a park, not a degradation of the turn — which is ADR-0254 §9's
> posture and ADR-0266 §8's list extended by this decision's own values.

> **Normative — a model contributes nothing at all to a quote, and the enumeration is the proof.**
> The **act** is `PlanStep.intended_action`, which ADR-0265 §4 has the loop resolve against stored
> ids; the **number** and the **currency** are the provider's own output; the **keys** they are
> read at are the declaration's (§3); the **digest** is the request's own property (§1); the
> **order** is the tuple's (§2). **There is no input of §§1-5 a planner envelope reaches**, and
> that is the difference between this design and the plan-carried selector §3 refuses.

### 9. What this records against earlier ADRs, clause by clause, under ADR-0082 §1

ADR-0082 §1's test is applied to the earlier ADR's **text** and is shown rather than asserted:
*"Would a reader holding only the earlier ADR now act differently, or read one of its clauses more
widely than it now holds?"* **Four documents come out yes** — ADR-0254 in two scopes, and ADR-0016,
ADR-0255 and ADR-0249 in one each. Every other ADR cited comes out **no** and takes none, which
ADR-0082 §1 requires as firmly.

**ADR-0254 §11 — in `AuthorizationProjection`'s field list and in one limb of its restart clause.**
§11 declares that model as *"a frozen model with `extra="forbid"` carrying exactly `coverage` …
and `expires_at`"*. §7 above adds `quote`, so a reader holding only §11 builds a projection that
cannot carry the figure the `MONEY` member was met against, and puts to the user a ceiling whose
proof they never see — which §11's own fourth-clause construction makes not a confirmation of that
charge, since §11's concrete list already requires the question to name *"the price as a figure or
as a bounded limit with its currency"* and nothing before this decision could supply the figure.
**And its restart clause** rules that *"A restart between the question and the answer recovers the
row and renders the same projection"*. Its three named facts — the coverage, the bounds, the
expiry — are on the row and are unchanged; the quote is on the **goal**, so a refresh between the
question and the restart renders the refreshed figure. A reader holding only §11 builds a surface
that caches the first rendering and shows a figure ADR-0254 §13's recheck would not use. **Every
other clause of §11 binds entire**: the rendered-from-the-proposed-row rule itself, `CoverageView`
as ADR-0266 §9 leaves it, the possibly-empty coverage and both directions of its argument, the
one-carrier-for-both argument, the engine-assembles-it and transcription rules, the
renders-no-internal-value bar, `ConfirmationEgress`'s untouched roster, the listing as ADR-0266 §9
leaves it, the revocation surface and `TurnOutcome.authorizations`.

**ADR-0254 §16 — in its `core`-surface roster, in two limbs, and in neither of the other two.** §16
states what `core/types.py` gains, and ADR-0266 §9 left that at **fourteen** types and **seven**
fields. §§1, 3 and 7 above add `ActionQuote`, `QuotedOutput`, `ActionQuoteMinting` and `QuoteView`
— **four** further types — and `ToolDefinition.quoted_output`, `Goal.quotes`, `Goal.quotes_elided`
and `AuthorizationProjection.quote` — **four** further fields. A reader holding only §16 implements
a roster test that fails on this decision's own surface. **Its `PermissionDecision` clause is
untouched**, that record gaining nothing here, and **its `core/errors.py` roster is untouched**, §5
minting no error class. **Every other clause of §16 binds entire**, the lane attribution of every
roster entry, *"`core/config.py` gains nothing at all"* and the transcribe-the-ruling-whole rule
included.

**ADR-0016 §1 — in one scope**, and it is the scope ADR-0254 §18 and ADR-0266 §9 have each already
taken, reaching one further field: the model declaration, and the required-field clause applied to
`quoted_output` alone. **The grounds are §1's own test applied afresh**, which matters because
ADR-0266 §9 rules that *"no lane reads the two records together as licence to default a third
safety field"* — and this is the third. §1 refuses a default because *"A default is a claim"* and
the natural-looking one for the reach tuples asserts *"this tool touches no data"*. **The absent
`quoted_output` asserts the opposite**: a declaration naming no quoted output produces no quote
(§3), so no act proved through a quote of it is ever covered and every one asks. It costs a
question and can never authorise a call, which is the one direction §1 exists to protect. Requiring
it would oblige every declaration and fixture in the tree to write `None` for a fact absent on
almost all of them and would refuse every definition written before it. **The exception is this one
further field**, and every other clause of §1 binds entire.

**ADR-0255 §15 item 19 — in its condition count alone.** Item 19 enumerates what must hold before a
consequential capability is wired — *"**five** conditions and not three"*, which ADR-0265 made six.
§6 above adds a seventh, binding a capability whose acts are authorised through a `MONEY` ceiling:
the provider-side hold or conditional execution. A reader holding only item 19 wires such an
integration after six and is wrong, because **none of the six reaches a quote that was true when it
was read and false when the charge was made** — the act is correctly claimed, correctly authorised
against a recorded number and correctly verified afterwards, and the over-bound charge has already
happened. **§13's rule binds verbatim and is relied on**, its own *"this decision adds **two**
prerequisites"* staying true of that decision; what grows is the gate's total. §15's every other
item, its thin/full division and its owed-by-the-lane-that-lands-the-clause rule are untouched.

**ADR-0249 §1 — in the `Goal` field count alone**, which ADR-0250 and ADR-0265 have each taken
before it. `Goal` gains `quotes` and `quotes_elided` (§2), so a reader holding only §1 authors a
goal that can hold no quote and every `MONEY` ceiling of it is proved against nothing. §1's
append-only interpretation rule, its `statement`-as-projection rule, its round-trip clause, its
four-absences clause and its `version` clause bind entire. **§2 is relied on and superseded in
nothing**: its elision is the shape §2 above reuses, *"a count and never an identifier"* and the
never-decreases rule included.

**And the ones that come out no, deliberately.** **ADR-0266** takes **no** record and is the
decision this one is cut from: §6's four facts are supplied exactly, §7's two routes, its
governing-quote rule, its *"An earlier quote is consulted in no case"* and its fault clause are
implemented rather than moved, and §10's bullets are **fired** rather than superseded. **ADR-0252**
takes **no** record and is read rather than moved: §1's no-content rule is honoured by not putting
a quote on a `GoalEvidence` at all, its two bases and verdict vocabularies are untouched, §7's
conflict rule is untouched, and §7's *"a refresh supersedes the row it displaces"* is honoured by
position (§4) rather than by a mark. **ADR-0014 §5 takes no record**: its `PlanStore` roster is a
list of members a store gains, and a store holding only those eleven still satisfies every sentence
§5 writes — adding a twelfth contradicts none of them, which is ADR-0082 §1's **stacked addition**,
and is why ADR-0249 §12, ADR-0250 §9, ADR-0252 §12 and ADR-0265 §5 each added members and recorded
nothing there. §5's export-closure rule and its `delete_goal` cascade are **satisfied rather than
extended**, a quote riding inside the `Goal` (§2), which is where ADR-0259's record of that clause
does not reach. **ADR-0253 §6** is relied on entire: `StepOutputRef` is reused as *"the one
spelling"* of a place in an output, and its six unresolvability cases bind every reference something
resolves and reach this one in no case, nothing resolving it. **ADR-0265** is relied on entire —
`IntendedAction`, its `id`, `PlanStep.intended_action` and §1's *"no fourth field"* closure as that
decision leaves them. **ADR-0021 §1** is relied on for the one canonical encoding; **ADR-0148 §1**
for §6's trade; **ADR-0086 §4** for §2's disclosure; **ADR-0042 §6** for §7's placement.

### 10. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward any
> of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling, and each
> carries the condition that fires it.

- **Whether the key a declaration names carries the *whole* charge.** §1 states the obligation and
  §3 puts it on the declaration; **nothing in code checks it**, and a declaration naming a booking
  fee where the total is produces a quote satisfying a ceiling the act breaches. What is available
  today is the **optional** safeguard — declaring the argument at `MONEY` (ADR-0266 §7) where the
  call carries one — and A10's verification of the charge afterwards, which is a finding rather
  than a prevention. Fired by the decision that gives a declaration a machine-checkable statement
  of totality, and by the one that rules what a verification finding does.
- **A quote read from anywhere but one key of one object.** §3 fixes depth one and one key pair, so
  a tool returning a **list** of priced options, a nested price, a price split across two keys, or
  two currencies in one output yields **no** quote and its acts ask. Fired by the decision stating
  a wider reading with its own totality argument — which owes ADR-0254 §4's no-schema rule and §3's
  no-model-selector rule, both binding it.
- **A quote for anything but `MONEY`.** A quote states a price and carries no `BoundKind` (ADR-0266
  §6), so a `PERIOD` or a `TERMS` member is met by no quote however §4 of ADR-0266 comes to mint
  one. Fired by the decision that gives such a member something to be proved against.
- **Caching a quote, and reusing one across goals, turns or declarations.** `quotes` is a field of
  one `Goal` and `for_action` is keyed on one goal; **no lane shares a quote between two goals**,
  reuses one for a second declaration, or holds one in memory across a dispatch. Fired by the
  decision stating what a shared price record is and what bounds its reuse.
- **An identifier of a quote's own, and any record that names one.** §1 declines it because the act
  and the digest select one deterministically. Fired by the decision that records a verification
  finding against the quote it contradicts, if that record needs a handle the pair cannot give.
- **Retiring, withdrawing or invalidating a quote.** A cancelled booking, a provider that
  repudiates a price, a goal abandoned mid-walk: none of them marks a quote, and the record carries
  no standing (§1). A displaced quote is displaced by position alone (§4). Fired by the decision
  that gives a quote a standing with a producer for its second member — the empty-box failure
  ADR-0249 §10 refuses, avoided here by omission rather than by a one-sided enum.
- **Which system-supplied keys are per-call identity rather than inputs a price depends on.**
  ADR-0266 §10 books it and this decision draws no line, so §1's digest excludes nothing and a
  declaration filling an idempotency key per call is covered by **no** quote and asks on every act.
  **That is this decision's sharpest practical cost** and it is stated rather than absorbed. Fired
  by the decision that classifies such a key, unchanged from where ADR-0266 left it.
- **The provider-side hold or conditional execution itself.** §6 makes one a prerequisite and
  states no shape for it: not a type, not a Protocol, not a `ToolDefinition` field, not a seam.
  Fired by the decision that wires the first consequential capability a `MONEY` ceiling authorises,
  which owes ADR-0255 §13 as §6 leaves it.
- **What the listing and the revocation surface render about a price**, and what an export carries
  of one beyond the `Goal` it rides in. §7 reaches the confirmation alone. Fired by the decision
  that states what a standing authority's history shows of the figures it was proved against.

### 11. The lane cut, and the arms this decision owes

> **Normative.** This decision is implemented in **three lanes and no fourth**: **Q1**, the
> contract, the seam, the fakes and the store; **Q2**, the mint and the projection in
> `orchestration`; and **Q3**, the read in `permissions`. **No lane wires a consequential
> capability** (§6, ADR-0255 §13) and **no lane writes an `Authorization`**. The bullets below
> assign each lane its surface and its arms, and **no lane is complete without what it is assigned
> there**.

> **Normative — Q1 is three packages and it is one change**, under `CLAUDE.md`'s Protocol-triad
> exception as ADR-0137 §2 widens it: §5 mints a **new** Protocol, so the Protocol, its shared
> conformance suite and its canonical fake are one unit; and the consumer whose demands shape it is
> the plan store, which is where the quotes live (§2), so `planning`'s implementation and
> `InMemoryPlanStore` ride with it. **`ToolDefinition.quoted_output` and
> `AuthorizationProjection.quote` ride Q1 too** — both are `core` shape changes and neither has a
> producer until Q2.

> **Normative — the wire moves once, the export moves, and the stored shapes are read rather than
> assumed.** **`PROTOCOL_VERSION` moves by exactly one, in Q1**, and `wire/envelope.py`'s log gains
> an entry naming this ADR and the reason: `Goal` gains two fields and crosses on
> `TurnResult.goal`; `ToolDefinition` gains one and crosses inside a `PermissionDecision`;
> `AuthorizationProjection` gains one and crosses inside a `Confirmation`. All three set
> `extra="forbid"` and `wire/codec.py` renders a model by `model_dump()`, so each on its own is a
> shape change — **one bump, three grounds, and there is no fourth**. **`PlanExport` gains no
> member and `schema_version` moves**, on ADR-0039 §10's own mechanism, because `Goal` is inside
> the export and its shape changing is what the version announces.

> **Normative — no stored row is migrated, edited or dropped.** A `Goal` written before Q1 decodes
> with `quotes` empty and `quotes_elided` `0`; a `ToolDefinition` decodes with `quoted_output`
> `None`; **no `AuthorizationProjection` is stored at all**, it riding inside a `Confirmation` that
> crosses a frame. **No lane invents a quote for a stored goal**: a price nothing read is a price
> no record holds, and minting one would state a history the row does not carry. **Q1 re-takes that
> reading at its own base and states what it found**; were a stored goal to hold a quote by then,
> the lane stops.

- **Q1 — the contract, the seam, the fakes and the store** (`core/types.py`, `core/protocols.py`,
  `ai_assistant.testing`, `planning`). `ActionQuote`, `QuotedOutput`, `ActionQuoteMinting` and
  `QuoteView`; `MAX_ACTION_QUOTES`; `Goal.quotes` and `Goal.quotes_elided` with §2's append-only,
  order and elision rules; `ToolDefinition.quoted_output`; `AuthorizationProjection.quote`;
  `GoalQuotes` with its conformance suite and its canonical fake; `PlanStore.record_quote` with its
  compare-and-swap, its elision and its one refusal, in the Protocol, the conformance suite,
  `InMemoryPlanStore` and `planning`'s durable store; `PROTOCOL_VERSION` with `wire/envelope.py`'s
  log entry; and `PlanExport.schema_version`. **It reads no quote and mints none.** Arms 1, 2, 3, 6
  and 8.
- **Q2 — the mint and the projection, in `orchestration` alone.** §4's mint on every path a step's
  output is recorded, its five conditions and its refusals; the `record_quote` write; §7's
  transcription of the governing quote onto `AuthorizationProjection.quote`, absent where no
  `MONEY` member was met through a quote; and §8's discard of every value this decision adds.
  **Q2 waits on ADR-0266's L2**, which sets `ActionRequest.intended_action` from the plan step the
  request serves — without it the mint has no digest to pair with an act. Arms 4 and 7.
- **Q3 — the read, in `permissions` alone.** `GoalQuotes.for_action` wired into ADR-0266 §7's
  evidence route: the governing-quote selection, the digest comparison against the concrete
  request, the currency conjunct taken at the quote's own currency, and the fault clause. **It is
  ADR-0266's own L3** and is briefed on that decision and this one together. **With it ride the
  arms ADR-0266 §11 assigns the quote decision** — its arms 1(b), 5 and 6(a)'s with-a-quote limbs,
  arm 2(b)'s quote half, and the covered limbs of every ADR-0254 §20 arm its mechanism (iv)
  reaches, arm 45's GBP 50 `ALLOW` among them. Arm 5.

> **Normative — Q1 is briefed after ADR-0266's L1 lands, Q1 lands before Q2 and Q3, Q2 and Q3 are
> independent of each other, and ADR-0254 §20's Lane 2 is briefed after Q3.** L1 lands
> `ActionRequest.intended_action`, `CoverageMember.kind` and ADR-0266 §7's two routes, and above it
> ADR-0254 §20's Lane 3 has landed `AuthorizationProjection` and ADR-0265's core lane
> `IntendedAction`, `Goal.intended_actions` and `PlanStep.intended_action` — Q1 adds a field to the
> first and refuses an action the second does not hold, so **where L1 is not yet in its base, Q1 is
> not briefed**. **Lane 2 is briefed after Q3 and not after Q1**, because its arms drive an
> end-to-end proposal whose ADR-0254 §1 completeness condition needs a **met** `MONEY` member, and
> a member is met only where the comparison reads a quote: a carrier no seam is wired to leaves
> Lane 2 exactly where ADR-0266 left it. **Every tree any of the three lanes leaves is conforming
> and fail-closed** (ADR-0084 §3): before Q3 no `MONEY` member is met and every such act asks.

> **Normative.** **The three lanes ship the arms assigned above, of the eight below, each over
> controlled fakes, and no lane is complete without the arms it is assigned.** **No arm asserts
> anything its own lane's tree cannot produce**, which is why the end-to-end comparison is Q3's and
> the mint is Q2's. Every arm states a correction as a **subsequent turn**, on the owner's
> sequencing ruling of 2026-09-13, and **none is demonstrated against a live integration** (§6).

1. **The record, and the four facts.** An `ActionQuote` is constructible at each of §1's shapes and
   round-trips through its own dump; it is **not** constructible carrying a non-finite or negative
   `amount`, an `arguments_digest` that is not lowercase 64-character hex, or an eighth field; and
   a `QuoteView` is constructible and carries no digest, no action and no identifier. **And the
   goal's order is the total order**: a goal carrying quotes for two actions returns them oldest
   first, the **last** naming an action is the governing one, and appending a second for one action
   leaves the first in place and unmarked.
2. **The store: the write, the refusals and the elision.** `record_quote` appends and advances
   `version`; a stale `expected_version` refuses on the class `StaleExecutionError` occupies and
   writes nothing; a `quote` whose `intended_action` is not an id of the goal's `intended_actions`
   refuses on the invariant class and writes nothing, **against a control naming one that is**. And
   the elision: appending to a goal already holding `MAX_ACTION_QUOTES` drops **exactly one** from
   the front and advances `quotes_elided` by one; **an elision that drops an action's only quote
   leaves that action with none** and an elision that drops its **oldest of two** leaves the
   governing one where it was — the assertion that no elision revives an earlier reading.
3. **The declaration.** A `QuotedOutput` is not constructible where `amount` equals `currency`, or
   where either names a key below depth one; a `ToolDefinition` is constructible carrying one, and
   constructible carrying **none**, decoding from a dump written without the field as `None`.
4. **The mint, driven through `orchestration`.** Over a step bound to a declaration carrying
   `quoted_output` and a plan step carrying an `intended_action`, a `SUCCEEDED` step whose output
   is `{"price": "120", "stars": 4, "currency": "EUR"}` mints exactly one quote, at `120`/`EUR`,
   whose `arguments_digest` equals that request's own `parameters_digest`, whose `plan` and
   `read_from` name where it was read, and whose `stars` value appears **nowhere**. **And nothing
   is minted**, the goal's `quotes` unchanged and nothing raised, in each of: no `intended_action`
   on the step; no `quoted_output` on the declaration; an `output` that is not a JSON object; a
   missing `price` key; a missing `currency` key; a **JSON float** `120.0`; a negative amount; a
   non-numeric string; and a currency that is not a JSON string. **And the mint reads its own step
   alone**: a second step's output carrying a different price in the same walk changes nothing
   about the quote minted from the first.
5. **The comparison, end to end, and it is ADR-0266's own.** Against a quote for the request's
   `intended_action` at `"120"`/`"EUR"` over the request's own arguments the request is **covered**
   against a `150` `EUR` ceiling; at `"170"` it is not; at `"120"`/`"USD"` it is not; with **no**
   quote for that action it is not however small the declared arguments are; and a request carrying
   **no** `intended_action` is covered by no quote. **The arguments are the ones quoted**: one
   extra argument, one missing, and one whose value differs are each not covered though the price
   is unchanged. **The Sunday re-quote governs**: with a Saturday quote at `120` and a later Sunday
   quote at `135` for one action, the Sunday arguments are covered and a request returning to the
   **Saturday** arguments is **not** — the earlier quote never reviving. And a `TERMS` member is
   met by no quote whatever it carries.
6. **The seam, and a fault is not an absence.** `GoalQuotes.for_action` returns that action's
   quotes in the goal's order and an **empty** tuple for an action the goal has none for; the
   canonical fake satisfies the conformance suite; and a `for_action` that **raises** leaves the
   request **not covered with the fault reported**, never as an absence of quotes and never falling
   through to the argument route — against a control returning empty, which is uncovered for the
   other reason.
7. **The projection.** A `CONFIRM` whose proposed row carries a `MONEY` member met through a quote
   at `120`/`EUR` renders an `AuthorizationProjection` whose `quote` carries `120`, `EUR` and the
   quote's own `read_at`, **beside** the `CoverageView` carrying the `150` bound and the user's own
   span; a row carrying no `MONEY` member renders `quote` **absent**, as does one whose member was
   met on the argument route alone; the three values are **transcribed** from the goal's own record
   and equal it byte for byte; and **a re-render after a refresh landed renders the refreshed
   figure** while the coverage, the bounds and the `expires_at` are unchanged.
8. **The writer clause, the discard, the wire and the stored shapes.** A `PlannerOutput` whose
   envelope carries every value §8 names — an `ActionQuote`, a `QuotedOutput`, a `QuoteView`, an
   amount, a currency, an output key and a digest — leaves the recorded revision and the goal's
   `quotes` **byte-identical** to the same envelope without them, the turn completing and not
   failing. And: a `Goal` and a `ToolDefinition` dumped at the previous shape decode with the new
   fields absent; `PROTOCOL_VERSION` has advanced by exactly one with a log entry naming this ADR;
   `PlanExport.schema_version` has advanced; `PlanExport` carries the quotes **inside** its goals
   and gains no member; and `delete_goal` removes them with the goal.

### 12. This ADR classified, marked, and how it is ratified

**A reader acts differently, so this is a decision and not a clarification.** A reader holding the
corpus without it can prove no `MONEY` ceiling at all — ADR-0266 §7's evidence route has no operand
— and would either leave #2373 stopped where it stopped or invent a carrier, a producer and a
selector no clause authorises, which is the `stars`-in-the-`price`-slot failure §3 exists to
prevent (ADR-0070 §1). **It is a partial supersession of exactly four documents** (ADR-0070 §3) —
ADR-0254 in two scopes, ADR-0016, ADR-0255 and ADR-0249 in one each — and the `Status` line of each
names its scopes **without an `ADR-NNNN` token inside the parentheses**, so ADR-0070 §4's extraction
invariant holds. **The records land in the same change as this document** (ADR-0082 §7), and
nothing else in any of the four is edited — no Decision text is rewritten, which ADR-0070 §1
forbids.

**This ADR is marked** under ADR-0089 as ADR-0257 §1 widens the token: every obligation it imposes
is a normative blockquote at column 0 stating its own scope, unmarked text beside a mark
supplies no obligation of its own but is read to settle what a mark means (§3), and quoted marks
from other ADRs appear inside quotation marks in running prose. §11's lane bullets and its arms are
that unmarked content, read under marks stating the lane count, the one-change rule and the
no-lane-is-complete rule.

**It is a contract-surface change** — `core/types.py` gains four types and four fields, and
**`core/protocols.py` gains a Protocol and a `PlanStore` member** — so it owes **both** review
lenses on one tree, which ADR-0015 §1 makes true of a prose-only PR. **`GoalQuotes` is a new
Protocol, so the triad is owed** and §11 puts it in Q1. **It merges as its own PR, ratified, before
anything implements against it** (golden rule 5); §11's lanes are briefed after it merges, and the
ratification flip is one line and no other byte (ADR-0165).

## Consequences

**What becomes possible, and when.** Q1 lands the carrier, Q2 the producer and Q3 the read, and at
Q3 ADR-0266 §7's evidence route has an operand for the first time: a `MONEY` ceiling the user
stated is **confirmed once, in the authorisation phase, beside both the words it was read from and
the figure the act was quoted at**, and then covers every later call for that act whose quote sits
under it — **at a tool that declares nothing about money at all**, which is the owner's whole point.
*"Make it Sunday"* is answered by a re-quote rather than a second question. ADR-0254 §20's Lane 2
becomes briefable, and #2373 is unblocked by ADR-0266 and this decision together.

**What becomes harder, and every part of it is a question asked rather than a call authorised.** A
declaration that names no `quoted_output` never quotes, so every act of it that a `MONEY` ceiling
would authorise asks. A quoting call and an acting call differing in **any** argument key never
match — **a per-call system-supplied key included**, which is this decision's sharpest cost and is
ADR-0266 §10's booking rather than this one's to close. A price the system would have to compute —
a sum of components, a converted currency, a per-unit rate multiplied out — is not a quote and
mints none. And a tool returning a **list** of priced options quotes nothing, §3 reading one key of
one object.

**What is disclosed rather than closed, and it is the one residual this document is honest about.**
A quote true when it was read and false when the charge was made authorises an over-bound charge,
and **no local mechanism detects it**: an expiry nobody enforces, elapsed-time proximity and a
local compare-and-swap are each a check in the wrong place (§6). What closes it is provider-side
and is therefore a **gate prerequisite** rather than a rule in `permissions`, which is why ADR-0255
§15 item 19 grows by one and why nothing here pretends the window is shut. Until such a capability
is wired the figure and its instant are **rendered to the user** and the charge is **verified
afterwards** by A10, and neither is a prevention.

**These are the cases that would falsify the design.** A corpus of real declarations whose prices
are not one key of one flat object — a list of options, a nested breakdown, a fee beside a total —
which would make §3's depth-one reading quote almost nothing. A booking flow whose acting call
carries an argument the quoting call did not, so the digest never matches and the mechanism is
inert in exactly the case it was built for; the practical falsifier by a distance, and the one to
measure first. Integration authors who declare `quoted_output` at the wrong key, which §1's
totality obligation asks of them and no code checks. A provider offering neither a hold nor a
conditional execution, which under §6 means the capability is **not wired** rather than wired with
a shorter window. And a goal whose investigation re-quotes so often that 64 quotes elide the only
reading of an earlier act, turning a covered call into a question.

## Alternatives considered

**A `GoalEvidence` row, which is what the owner's ruling names.** Refused on ADR-0252 §1's own
text, and the refusal is about that type as it stands rather than about the substance. §1 rules
that such a row *"carries no content"* and is *"never a second copy of what was read"*; a quote is
exactly a second copy of what was read. It closes `EvidenceBasis` at two members, neither of which
admits a typed value read from a step's output; it fixes a `verdict` vocabulary per basis, and a
price is a member of none; and its field list has nowhere to put an amount, a currency or a digest.
Carrying a quote there supersedes four limbs of one ratified section and buys a shared store
member. **The substance of the owner's ruling is preserved whole** — recorded by the investigation,
for the intended action, read by the authorisation phase before execution — which is ADR-0266's
own note about this, and the carrier is the part the ruling left open.

**A quote store of its own rows beside `GoalEvidence`.** The nearest rejected alternative. It
avoids `Goal.version` churn on every append, which is its one real advantage. It costs a second
`PlanStore` read member, an extension of ADR-0014 §5's export-closure rule and of `delete_goal`'s
cascade, and — decisively — an order that is an implementation's insertion order rather than a
property of the record. ADR-0266 §6 requires the quotes of one goal to be **totally ordered**, and
the tuple gives that for nothing while a row store gives it only by a rule every implementation
must get right. ADR-0265 §5 accepted the same version churn on this same model for a record of the
same durability.

**A plan-carried selector naming the output key.** The earlier draft's first shape and the one §3
refuses outright. It puts the choice of which number is the price in a value a model writes on
every turn, and the harm is a **too-small** value: `stars` quoted as `4` satisfies a `150` ceiling
and authorises a `200` purchase. No validator of shape catches it, ADR-0254 §3's
*"can satisfy … and can never supply"* arm does not reach it, and ADR-0254 §15's writer clause
forbids it at the source. The declaration is the same fact written once by a human and reviewed
once.

**An expiry on the quote, enforced locally.** Refused in §6. A `read_at + Δ` test refuses quotes
that are still true and admits quotes that are already false, because Δ is a guess about a
provider's pricing; a compare-and-swap at dispatch observes stored values and not the provider's
current price; and a re-quote immediately before the call narrows the window without closing it.
Each looks like a freshness proof and is not, which is worse than the absence, because a reader who
sees one stops asking for the mechanism that would work. What the provider can offer — a hold, or a
conditional execution that validates the amount atomically with the act — is what §6 makes a
prerequisite on wiring.

**A tuple of quoted outputs on the declaration.** Refused in §3 for the reason a tuple of anything
admitting exactly one member is refused: the one-member rule is a thing somebody must remember at
the read, and every candidate selection rule for a second member is already forbidden — by kind
(ADR-0266 §7 is about members), by the plan (§3), by a schema keyword (ADR-0254 §4) or by order
(arbitrary).
