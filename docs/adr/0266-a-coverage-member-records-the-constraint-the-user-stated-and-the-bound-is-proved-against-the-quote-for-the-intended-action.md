# 266. A coverage member records the constraint the user stated, and the bound is proved against the quote for the intended action

- Status: Proposed
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **six narrowly stated scopes, and §9 shows the working for each. §2's member shape**: a
  `CoverageMember` stops carrying an `argument` and carries a **`kind`** instead, so a member
  records *what the user stated* and never *which slot it fills*; with it go §2's depth-one
  clause, its no-two-members-name-one-argument rule (which becomes **one member per kind**), its
  `currency_argument` field on a `MONEY` bound, and `maximum`'s requiredness (a stated **floor**
  mints a `minimum` and no `maximum`). **§3's condition 6 and its field count**: the set equality
  over argument **keys** and the per-argument rule that reads a member *"naming it"* are replaced
  by **two routes** — a member is met against the **quote recorded for the step's intended
  action**, or, where the declaration declares an argument at the member's kind, against that
  argument; **a `MONEY` member is met through the quote alone**; the validator refusing a member
  that names a system-supplied argument goes with the field it read, its rule preserved by a
  refusal on a new declaration field; and `ToolDefinition` gains **one** further field,
  `bounded_arguments`. **§4's `MONEY` conjunct**: the currency is read off the **quote** on the
  evidence route and off the **declaration** on the argument route, never off the bound.
  **§9 clause (ii)**: *"an argument the act's own words bear on"* is given its mechanical test —
  agreement between the constraint's kind and the kind of the thing it is compared against, and
  never numeric fit, never a model's nomination. **§8's and §10's resolution enumeration, in the
  closure at three alone**: a fourth `ResolutionRule`, **`STATED_BOUND`**, reads a bound off the
  span by a closed table — which §19 books by name and this decision fires. Every other clause of
  all six sections binds entire, several of them load-bearing here: §1's three write paths and
  its write-before-the-question rule, untouched because a member now needs **no argument at write
  time**; §2's two-shapes-and-no-third rule and its `BoundKind` vocabulary; §3's conditions 1-5,
  its user-facing classification, its no-omission-reads-as-consent rule and its canonical
  encoding; §4's totality and its three readings; §8's basis, its two-zones clause and its
  per-member rule; §9's clauses (i) and (iii) and its discard rule; §10's three ratified
  resolutions and its no-member-where-a-resolution-cannot-be-taken sentence; §13's
  recheck-at-`decide` and its no-cached-verdict rule, which §7 below is taken under; and §15's
  writer clauses.
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
- **Partially supersedes** [ADR-0249](0249-the-goal-carries-its-interpretation-the-attempt-carries-the-phase-and-the-planner-returns-its-understanding.md)
  — **one scope, in §1's `Goal` declaration alone**, and it is the scope the intended-action
  decision already took there reaching two further fields: `Goal` gains **`quotes`** and
  **`quotes_elided`** (§6). A reader holding only §1 authors a goal with no place for a quote, so
  §7's evidence route has no operand and a `MONEY` member is met nowhere. Every other clause of
  §1 binds entire, and §2's bounded-history construction is the one §6's elision reuses rather
  than restates.
- Date: 2026-09-15
## Context

### Where this comes from

Issue **#2373**, found in the pre-flight of ADR-0254 §20's **Lane 2** — the lane that makes
`orchestration` propose an `Authorization` on a `CONFIRM`, settle it on the answer, and write
path-(ii) corrections and path-(iii) opening acts. That lane stopped before writing code, and
this is what it stopped on.

ADR-0254 states that `orchestration` mints a `CoverageMember` from a recorded act, and states
exactly what a member must contain, but **no clause states how a recorded span is associated
with an argument key of a declaration, nor how the member's shape is chosen** — a `fixed` value,
or a `ValueBound` of kind `MONEY`, `PERIOD` or `TERMS`.

The owner's Q1 ruling of 2026-09-12, which ADR-0254 records whole, is what the answer has to
serve: *"Bind authorization to explicitly fixed values and explicitly permitted ranges. A price
change within an approved limit should remain covered. A clear later instruction such as 'make
it Sunday' can supply authorization for that change; do not automatically ask the user to repeat
it. Ask only when the concrete action introduces something not already covered, such as
additional costs or materially different terms."*

**The owner's ruling of 2026-09-14 decides where the bound is compared, and it is the frame of
this document.** *"The tool takes what the action needs (site, dates, party size). The price is
usually a consequence of those choices, not an argument the assistant supplies."* So the
investigation phase records the quote for the intended action, the authorisation phase compares
the bound against that quote before execution, and **nothing about the price is compared against
an argument of the call**. A tool *may* declare a money-kind argument — a transfer amount, or a
`max_price` filter — and then the argument comparison applies **as well**; *"a filter is not a
charge"*, so it never stands in for the quote. Where no quote covers the act, the system
investigates or asks, which is a feasibility answer rather than a restriction on the tool. And
the evidence covers a step **only where the step's arguments are the ones that were quoted**:
any difference, extras filled in after quoting included, means re-quote or ask.

### The gap this closes, stated as the failure the corpus has today

Without the rule, **none of ADR-0254 §1's three write paths can write a row carrying a non-empty
`coverage`**, and §1's path-(i) completeness condition holds only **vacuously**, on a request
carrying no user-facing argument. Four ratified clauses each come close and none closes it:

- **§10** states three resolutions — `AS_STATED`, `DATE_FROM_CONTEXT`, `FROM_SHOWN_RECORD` —
  each *"a total function of recorded inputs"*. Every one turns **a span into a value**. None
  selects the span and none names what the value is for.
- **§9 clause (ii)** states the **property** the association must have — a resolution turns a
  span into a value *"for an argument the act's own words bear on"* — and then states what it
  may not do. A property is not a procedure.
- **§8** closes `AuthorizationBasis` at `act`, `span` and `resolution`. Nothing on it names an
  argument.
- **§1's path (iii)** points at the goal's interpretation, but `GoalElement` (ADR-0249 §1,
  ADR-0253 §7) carries `id`, `text`, `ground`, `applicability`, `evidence_id`,
  `evidence_row_id` and `span` — **no typed value and no argument key**.

And **§9's no-model clause forecloses the obvious source**: a planner envelope carrying *"a
coverage member, a bound, a basis"* has those values *"discarded silently"*, which §15 repeats
as a writer clause. **§19 books what that decision does not settle, by name, each with what
fires it** — a fourth `ResolutionRule` among them, which §4 below fires — **but the association
is not among its bookings**, so that silence is a gap and not a reservation.

**Why a lane must not simply invent the rule.** §9 clause (ii) forbids adding *"a member for an
argument the act never mentioned"*, but only path (ii)'s widening is a store-enforced refusal:
a freshly minted path-(i) or path-(iii) member is checked by nothing. A wrong association is
therefore a **standing authority the user never gave**, and route (d) then `ALLOW`s inside it
with no `CONFIRM` — the failure direction §9's three clauses exist to close, and #2096 item 8's
ruled asymmetry (*"a model is a safe denier and an unsafe allower"*) is the corpus's own
statement of why a guess is not available here.

### What is already ratified and is consumed rather than rebuilt

- **ADR-0254 §3's fixed and bounded comparisons and §4's three readings**, and its canonical
  encoding — *"one canonical form in this system and not a second"*.
- **ADR-0254 §3's negative arm on a value a tool produced**, which is what makes §7's evidence
  route safe and is quoted there: *"a value a tool produced can **satisfy** a bound the user set
  and can never **supply** one"*.
- **ADR-0254 §1's write paths, their timing and their refusals**, including the row written
  before the question is put and the coverage never edited afterwards.
- **ADR-0254 §13's recheck**, which §7 is taken under: the comparison is taken at
  `ActionPolicy.decide`, on the concrete request, at **every** dispatch, with no cached verdict.
- **ADR-0249 §7's ground resolution.** A `USER_STATED` element's span *"is resolved by checking
  it is a span of the turn's own request (`TurnResult.utterance`, ADR-0248 §1)"*, by
  `orchestration` and never by a model, and retention copies it forward *"whole and
  unchanged"*. That check is the one ADR-0254 §8 needs, already taken.
- **ADR-0253 §7's element identity** and **§8's `InterpretedOutput`**, the reference
  `orchestration` composes from a plan's `StepOutputRef` and of which *"No model supplies any of
  the three"* — the provenance §6's quote reuses rather than restates.
- **ADR-0265 §1's `IntendedAction`**, the identity a quote and a step both name, *"minted once"*
  and never derived.
- **ADR-0249 §2's bounded history and `Goal.interpretation_elided`**, which is what makes the
  refusal in §2 exact rather than approximate.

### The tree, read rather than assumed, at `origin/main` `32968830`

ADR-0254's Lane 1 has landed. `core/types.py` carries `Authorization`, `CoverageMember`,
`ValueBound`, `BoundKind`, `AuthorizationBasis`, `ValueResolution`, `ResolutionRule` and
`ToolDefinition.system_supplied`; `CoverageMember` carries `argument` and `ValueBound`'s
`MONEY` arm carries `currency_argument` and a **required** `maximum`, all three of which this
decision changes; `canonical_json_bytes` is public and is the one encoding; `Sha256Hex` is the
digest shape and `ActionRequest.parameters_digest` is computed rather than supplied;
`permissions/_coverage.py` carries `covers`, `covers_arguments` and a private
`_argument_is_covered` with `_satisfies`, `_satisfies_money`, `_satisfies_period` beside it.
`InterpretedOutput` carries `execution_id`, `step_id` and `field`. `GoalElement` carries `id`,
`text`, `ground`, `applicability`, `evidence_id`, `evidence_row_id` and `span`;
`GoalInterpretation` carries `raised_by`; `ActionPlan`'s `_step_ids_are_unique` raises *"plan
step ids must be unique within a plan"*. Nothing in the tree mints a `CoverageMember`, nothing
records a quote, and `ToolDefinition` declares nothing about what kind of value an argument
takes.

### What this ADR is not allowed to settle

It decides what a member **records**, how a span **becomes** one, and **what a member is proved
against** — and nothing beyond that. It leaves ADR-0254 §3's conditions 1-5 and §§5, §6, §7
exactly as they stand, §12's expiry as ADR-0256 §1 leaves it, and §11's projection and every
surface untouched; it opens no route, relaxes no floor, lowers no threshold and moves no ruling.
ADR-0252's `GoalEvidence` is read and is **not** moved: §6 states why a quote is a record of its
own rather than a field of that row.
## Decision

### 1. The candidate act is a `USER_STATED` constraint of the goal, and there is no second source

> **Normative.** A coverage member is minted from a **`GoalElement` of the goal's *current*
> interpretation's `constraints` whose `ground` is `USER_STATED`**, and from nothing else. Its
> `span` is the member's `span`; the act and the resolution are §2's. **No other value of this
> system mints one** — not a `criteria` or a `conditions` element, not the interpretation's
> `outcome`, not a plan step, not an evidence row, not a quote, not a memory, not a preference
> and not a prior goal.

> **Normative — a `FROM_EVIDENCE` element and an `INFERRED` element mint nothing, and the type
> is why rather than a rule to remember.** ADR-0249 §1's validator admits `USER_STATED` with a
> `span` and no `evidence_id`, `FROM_EVIDENCE` with an `evidence_id` and **no span**, and
> `INFERRED` with neither. ADR-0254 §8 requires a span *"inside that turn's stored utterance"*
> on **every** basis, and §9 clause (i) makes a member without one **not constructible**. So
> the two grounds that carry no span cannot reach a basis at all, and this clause states a
> consequence of two ratified types rather than adding a third refusal to either.

**That is the whole of the security argument for the source, and it is worth stating plainly.**
`FROM_EVIDENCE` names a record and `INFERRED` names the system's own judgement; neither is the
user's words, and ADR-0254 §9 clause (i) exists to make *"the authority is the act"* a property
of the type rather than a discipline. A design that minted from an inferred constraint would be
the code path that clause says does not exist.

> **Normative — `criteria` and `conditions` mint nothing, and the exclusion is stated rather
> than left to the reader.** ADR-0249 §1 makes the three tuples *"its constraints, its success
> criteria and its conditions"*, and ADR-0253 §7 gives a **condition** element the applicability
> a step's own condition is evaluated over: a criterion states what **success** would be and a
> condition states **when** a step may run, and neither is a statement about what a call may
> carry. A user whose words bound the action states a **constraint** — ADR-0254 §1's path (iii)
> in terms, *"the bound is an element of its `constraints`"*.

> **Normative — the interpretation's own `outcome` mints nothing, and the reason is that it
> carries no identity.** §2's act is found by walking the retained history for the revision that
> **first** recorded an element, which ADR-0253 §7's minted-once `id` makes exact. The outcome
> has no such id: ADR-0249 §7 retains it by copying `outcome`, `outcome_ground` and
> `outcome_span` forward byte for byte, so two revisions carrying one outcome are
> indistinguishable from two that restated it, and the act a member rested on could not be
> named.

> **Normative — the *current* interpretation and no earlier one.** An element a later revision
> neither retained nor replaced is **not** in the current interpretation (ADR-0249 §7,
> *"omission is removal"*), and minting from an earlier revision's tuple would restore a
> constraint the user's own later words removed. The history is walked **only** to find the act
> (§2), never to find a candidate.

### 2. The act, the span and the resolution: what the basis is filled from, and when it refuses

> **Normative.** A member carries an `AuthorizationBasis` whose **`span` is that element's
> `span` byte for byte**, whose **`act` is the `raised_by` of the earliest revision of the
> goal's retained `interpretation` that carries an element with that element's `id`**, and whose
> `resolution` is §4's. Nothing is re-resolved, re-normalised or re-checked against a model:
> ADR-0249 §7 already checked that span against that turn's own `TurnResult.utterance` when the
> revision was recorded, which is exactly the check ADR-0254 §8 requires, and ADR-0254 §1
> re-takes it against the store before the row is built.

> **Normative — three absences each refuse the member, and each is fail-closed.** No member is
> minted where the element carries **no `id`** (a row written before ADR-0253 §7, which no
> condition can name and no history can locate), where the earliest carrying revision's
> **`raised_by` is `None`** (a row written before ADR-0249, whose act this system never
> recorded), or where the element's **`span` is absent**. A basis that cannot be filled truly is
> not filled at all, which is ADR-0254 §10's own sentence — *"A resolution the loop cannot take
> is not taken, and no member is minted"*.

> **Normative — an elided history refuses too, and the test is exact rather than
> approximate.** Where the earliest retained revision carrying the element's `id` is the
> **oldest retained revision** and `Goal.interpretation_elided` is **not 0**, no member is
> minted from that element. ADR-0249 §2 drops the **oldest** revisions, so a dropped one may
> have carried the element first and the act would name the wrong turn; where the carrying
> revision has a retained predecessor that does **not** carry the id, that revision is the
> first, and where nothing was ever elided the oldest retained revision is the first revision.
> Both directions are decided from values on the goal, with **no store read of any turn**.

**A wrong act is not a small error, which is why this refusal is worth its two clauses.** The
basis is what an auditor reads to see *whose words these were*; a basis naming a turn whose
utterance does not contain the span would be refused at the write by ADR-0254 §1's own check —
so the alternative to refusing here is not a wrong record, it is a row that fails to construct
at the moment a call needed it, with nothing on the goal saying why.

### 3. A member records the constraint and never the slot: it carries a kind and no argument key

> **Normative.** **`CoverageMember` loses `argument` and gains `kind`, a `BoundKind`, required.**
> A member states *what the user's words fixed or bounded* — an amount, a period, a named term —
> and states **nothing about which argument of which declaration carries it**. Its `fixed`,
> `bound` and `basis` are unchanged, and a `bound` it carries has a `kind` equal to the member's,
> refused at construction otherwise.

> **Normative.** **No two members of one `Authorization` carry the same `kind`**, refused at
> construction. This is ADR-0254 §2's no-two-members rule stated over the value that now
> identifies a member, and for that clause's own reason: *"A precedence rule between two members
> about one argument is a rule somebody would have to remember at the comparison, and it is
> better not to have one."*

> **Normative — `ValueBound` changes in two respects and no others.** A **`MONEY`** bound
> carries `currency`, and **`maximum` and `minimum` each optional with at least one present**,
> refused at construction where both are absent and where a `minimum` present beside a `maximum`
> exceeds it — so a stated **ceiling** and a stated **floor** are each representable and each is
> exactly what the user said. And **`currency_argument` is removed**: the key carrying an
> amount's currency is a fact about a **declaration**, not about an act, and §7 reads it there.
> `PERIOD` and `TERMS` are unchanged.

**This is the whole of the correction round 1 forced, and it is worth stating why the argument
key was the defect rather than the rule that chose it.** Both review lenses reached the same
place from opposite ends: a value that *fits* an argument is not a value the act's words *bear
on*, so no rule selecting an argument from a request or from a declaration's shape could satisfy
ADR-0254 §9 clause (ii) — *"a value for an argument the act's own words bear on"*. A constraint
about a hotel's star rating has a number in it and would fit a price; a name the user said would
fit any string-valued slot that happened to carry it. **Bearing is established by kind agreement
between the constraint and the thing it is compared against, and by nothing else**: *"four
stars"* has no `MONEY` reading (§4), so it mints no money member and is proved against no price;
and on the evidence route the thing compared is the quote **for the very act this goal intends**,
which is a tighter tie than any argument key was. The question *"which argument did the user
mean"* is never asked, because the record never claims to answer it.

**And the record is better for it, not merely safer.** One authorization now states what the
user permitted without naming a key, so a member survives an argument being renamed inside one
declaration, and a `MONEY` member is proved against the price the act was quoted at rather than
against whatever slot happened to carry a number. **It does not survive a change of tool**:
ADR-0254 §3's condition 3 compares the request's `tool` against the row's **by value** and this
decision leaves that condition entire, so a row established about one declaration covers a call
made under another in no case — which is the rebinding #54 closed and is not weakened here.
ADR-0254 §1's write-before-the-question rule is untouched by all of this, because a member needs
**no argument at the moment it is written**.
### 4. The reading: how a span becomes a value or a bound, and it is total at every step

> **Normative — `core/types.py` gains a fourth `ResolutionRule`, `STATED_BOUND`, taking neither
> argument.** The span is read **as a bound**. ADR-0254 §19 books *"A fourth `ResolutionRule`"*
> by name and this decision is what fires it; §10's other three are untouched and are still the
> only readings that produce a **value**.

> **Normative — the `STATED_BOUND` table is closed, is stated here whole, and is the entire
> reading.** The span is matched **in full** — after ASCII case-folding and collapsing runs of
> ASCII whitespace to one space, which is normalisation *"part of the resolution … recorded with
> it"* (ADR-0254 §10) and never applied at the comparison — against exactly these forms, in
> which `<amount>` is a decimal figure ADR-0254 §4's `MONEY` reading accepts together with one
> word of the currency table below, in either order:
>
> - **a `maximum`** — `<not> over <amount>`, `<not> above <amount>`, `<not> more than <amount>`,
>   `under <amount>`, `below <amount>`, `at most <amount>`, `no more than <amount>`,
>   `up to <amount>`;
> - **a `minimum`** — `<not> under <amount>`, `<not> below <amount>`, `<not> less than <amount>`,
>   `at least <amount>`, `no less than <amount>`, `more than <amount>`, `over <amount>`,
>   `above <amount>`.
>
> Each negated row is the positive comparator inverted. *"no more than"* and *"no less than"* are
> the case where the negation sits directly against the comparator; they are listed in their own
> right so the table reads whole, and both routes to them give one answer.
>
> The currency table is `euro`/`euros`/`eur`/`€` → `EUR`, `dollar`/`dollars`/`usd`/`$` → `USD`,
> `pound`/`pounds`/`gbp`/`£` → `GBP`. **A span matching no form mints no member**, and no lane
> adds a form, a currency or a language without its own ratified decision.

> **Normative — `<not>` is adjacent to its comparator, and the admitted prefix is closed at two
> tokens.** `<not>` is **one** token of the negation vocabulary — closed at `not`, `never`, `no`,
> `n't` and `without` — optionally followed by **exactly one** token of the spending vocabulary —
> closed at `spend`, `pay`, `go`, `charge` and `cost` — and by **nothing else** before the
> comparator. So *"never spend over 100 euros"* matches `<not> over <amount>` and mints a
> **`maximum`** of `100`, which is the owner's own illustration of this rule, and the inversion is
> the user's own arithmetic rather than a direction read into words that do not carry one.
> **Everything else the negation might govern mints nothing**: *"never notify me about charges
> over 100 euros"* carries four tokens between the negation and the comparator and is not a
> spending ceiling; *"not 100 euros"* and *"not exactly 100 euros"* state no direction at all; a
> **second** negation token inside the prefix takes the span out of every form; and an inflected
> spending word (*"never spending over 100 euros"*) is not a member of the closed set. That
> narrowness is the fail-closed half — a bound guessed where the user stated no direction is a
> standing authority they never gave, and it is the one place a reading could otherwise authorise
> against their words.

> **Normative — every bound this table mints is inclusive at its endpoint, and the coarsening is
> stated rather than left to be discovered.** ADR-0254 §4 satisfies a `MONEY` bound at
> *"less than or equal to `maximum`"* and *"greater than or equal to"* a `minimum`, and
> `ValueBound` has no exclusive spelling; so *"under 100 euros"* mints `maximum` `100` and a call
> at exactly `100` **is** covered though the word excludes it. The alternative is endpoint
> semantics on `ValueBound`, which §10 books with what fires it; the alternative taken in the
> meantime is **not** dropping the strict forms, because *"under 150 euros"* is the phrasing this
> whole decision came from and a table that could not read it would be inert. The coarsening is
> by one endpoint, in the permissive direction, and the Consequences name it as a cost.

> **Normative — `DATE_FROM_CONTEXT` mints a `PERIOD` member.** Its `starts_at` and `ends_at` are
> the half-open interval the resolution yielded, and its **`timezone` is the configured IANA
> zone as the act's turn read it** — **the same input the resolution records**, read once, and
> **not derived from the resolution's record of it**. ADR-0254 §8 makes the two *"two facts
> and neither is derived from the other"* and *"ordinarily equal"* with *"nothing requir[ing]
> them to be"*, and reading one input twice is what keeps both true.

> **Normative — `AS_STATED` mints a `fixed` member whose `fixed` is the span read as itself**,
> normalised by nothing, which is ADR-0254 §10's discipline and ADR-0248 §1's before it. Its
> `kind` is `TERMS` — a term the user named — and it is the only kind an `AS_STATED` span mints,
> because a bare figure states no bound and a bare date states no period.

> **Normative — `FROM_SHOWN_RECORD` mints nothing from an element.** ADR-0249 §1's validator
> gives a `USER_STATED` element a span and **no** `evidence_id`, so no element carries both a
> span and the record its reference resolved to, and re-resolving the words against that turn's
> shown set at minting time would be a fresh interpretation of the user's language — a model act
> at the one moment ADR-0254 §9 clause (i) reserves to code.

> **Normative — the readings are attempted in one order and the first total one is taken**:
> `STATED_BOUND`, then `DATE_FROM_CONTEXT`, then `AS_STATED`. The order is stated so that a span
> which is both a bound phrase and a term is a bound, and it is the only ordering in this
> decision. **What makes a `DATE_FROM_CONTEXT` resolution total over a span is not decided
> here** (§10).

### 5. One member per kind, and the mint reads the goal and nothing else

> **Normative — where two candidate elements of one goal would mint members of one `kind`,
> neither is minted.** No precedence, no ordering, no most-recent rule and no narrowest-wins
> rule: ADR-0254 §2 refuses a row that carries two members about one thing, and choosing between
> two constraints the user stated is an interpretation of which one they meant. A later
> constraint that **replaces** an earlier one is ADR-0254 §1's path (ii) and supersedes the row;
> two standing at once is an ambiguity, and ADR-0254 §9 clause (iii)'s answer to an ambiguity is
> that the user is asked.

> **Normative — the mint reads the goal's own current interpretation and its retained history,
> and it reads nothing else.** **No request, no plan, no step, no declaration, no registry, no
> quote, no store of turns and no clock.** A member is therefore the same value whatever call was
> being built when the row was written, which is what makes *"the authorization records the
> constraint as the user stated it"* true of the record and not merely of its intent — and it is
> why no plan a model produced can shape the **content** of an authority, at any path, by any
> route.

**This is what round 1's central finding costs, paid in the right place.** The old rule minted
against the request being built, so a model that arranged a request could arrange which slot an
authority landed in. Reading only the goal removes the input rather than bounding it: there is
no request at the mint for a plan to have shaped. What a model still contributes is **which
span** an interpretation element carries — checked against the turn's own utterance by ADR-0249
§7 and read only through §4's closed table — and §8 states the bound on that exactly.
### 6. The quote: what the investigation records, and how one is minted

> **Normative.** `core/types.py` gains **`ActionQuote`**, a frozen model with `extra="forbid"`
> whose fields are exactly six: **`intended_action`**, an `Identifier`, the `IntendedAction`
> (ADR-0265 §1) this quote is for; **`arguments_digest`**, a `Sha256Hex`, the arguments it was
> quoted over; **`kind`**, a `BoundKind`; **`value`**, a `FrozenJsonValue`, the quoted value in
> the **same** form an argument of a request carries it in; **`currency`**, an
> `EncodableText | None`; and **`read_from`**, an `InterpretedOutput` naming the step output the
> value was taken from. A **model validator** admits `currency` on `MONEY` alone — required
> there, absent otherwise — and **refuses a `value` of JSON `null`**, which is the spelling of
> *"no value"* on every other carrier in this corpus and would be a quote that quotes nothing.

> **Normative — the quoted value is carried and the reading is ADR-0254 §4's, unaltered.** A
> quote is compared by the readings that already compare an argument, over a value in the
> encoding `ActionRequest.parameters_digest` is taken over, so **no second comparison and no
> second canonicalisation is written** (ADR-0145 §2, ADR-0150). `read_from` is provenance and is
> compared by nothing: it is ADR-0253 §8's `InterpretedOutput` reused rather than a second
> carrier for one fact, and it resolves for exactly as long as the goal does.

> **Normative.** `Goal` gains **`quotes`**, a possibly-empty `tuple[ActionQuote, ...]`, **oldest
> first and append-only**, and **`quotes_elided`**, an `int` `ge=0`. **No lane edits a member in
> place or reorders the tuple.** The tuple is bounded by **`MAX_ACTION_QUOTES`**, a `Final[int]`
> of `core/types.py` valued at **64** — `MAX_GOAL_EVIDENCE`'s figure, for a record of the same
> goal with the same durability — and a minting that would carry the goal past it **drops the
> oldest** quotes in the same indivisible step and advances `quotes_elided` by the number
> dropped.

**The bound elides where the intended-action bound refuses, and the difference is what losing
one costs.** ADR-0265 §1 refuses rather than eliding because *"an identity that can vanish is not
an identity"* — a dropped one would silently make a performed act's effect claim fresh. A dropped
**quote** fails nothing silently: §7's route finds no quote, the member is met by nothing, the
request is not covered and **the user is asked**. Where the failure of a bound is a question, the
elision ADR-0249 §2 and ADR-0252 §13 already use is the right shape; where it is an undetectable
duplicate, the refusal is. The count is on the goal so a reader can see it happened.

> **Normative — a step declares the output its quote is read from, and `core/types.py` gains
> `StepQuote`**, a frozen model with `extra="forbid"` carrying exactly **`kind`** (a
> `BoundKind`), **`field`** (an `EncodableText | None`, a key of **that step's own** output at
> depth one, absent meaning the whole output) and **`currency_field`** (an `EncodableText | None`,
> `MONEY` only, required there and absent otherwise). **`PlanStep` gains `quotes`, a
> `StepQuote | None` defaulting to `None`**, and **a `PlanStep` carrying `quotes` and no
> `intended_action` is not constructible** — a quote with no act to be for is a value nothing can
> ever be proved against, and the refusal is at the type rather than at the mint.

> **Normative — `orchestration` mints the quote from the completed step's own output, and no
> model supplies any part of it.** After a step carrying `quotes` completes, `orchestration`
> mints an `ActionQuote` whose `intended_action` is that step's, whose `kind` is the
> `StepQuote`'s, whose **`value` is read at `field` of that step's stored output** and whose
> `currency` is read at `currency_field`, whose `read_from` is composed exactly as ADR-0253 §8
> composes an `InterpretedOutput` — `execution_id` from the execution it read, `step_id` and
> `field` from the step — and whose **`arguments_digest` is taken over that step's own request's
> user-facing arguments**. **Where the field is absent from the output, where the value there is
> JSON `null`, or where a `MONEY` quote has no value at `currency_field`, no quote is minted** and
> nothing is recorded.

> **Normative — the digest is one encoding restricted to one key set, and not a second
> canonicalisation.** `arguments_digest` is `sha256` over the canonical JSON encoding
> `ActionRequest.parameters_digest` is taken over, **restricted to the keys the declaration
> classifies user-facing** (ADR-0254 §3). System-supplied keys are excluded because
> `orchestration` fills them **per call** — an idempotency key differs between the quoting read
> and the booking by construction — so a digest over every argument could never match and the
> route would be inert. Nothing else is excluded: **an extra user-facing argument, a missing one
> and a changed one each change the digest**, which is the owner's rule that the quote covers the
> booking only where *"the step's arguments are the ones that were quoted"*.

> **Normative.** `PlanStore` gains **one** member, and this is a **BREAKING** contract change
> under golden rule 5: **`record_quotes(minting: ActionQuoteMinting) -> Goal`** — appends one or
> more quotes to the named goal's `quotes`, performs the elision above, advances `version`, and
> returns the stored goal. `core/types.py` gains **`ActionQuoteMinting`**, a frozen command
> carrying exactly `goal_id`, `quotes` (a **non-empty** `tuple[ActionQuote, ...]`) and the
> `expected_version` it was computed against; the write is **compare-and-swap** and the store
> takes a command and never a snapshot, which is ADR-0014 §5's discipline and ADR-0265 §5's
> statement of it unaltered. **The member refuses a command naming a goal the store does not
> hold, and one whose `intended_action` is not the `id` of a member of that goal's own
> `intended_actions`** — the window ADR-0265 §4 closes at the store for a plan, closed here for a
> quote and with the same error class.

**A quote is a record of its own rather than a field of a `GoalEvidence` row, and the reason is
that decision's own text.** ADR-0252 §1 rules that *"A `GoalEvidence` carries no content"* — it is
provenance about a servicing and *"never a second copy of what was read"* — closes `EvidenceBasis`
at **two** members neither of which admits a typed value read from a step's output, and fixes a
`verdict` vocabulary per basis. A quote is exactly a second copy of what was read, deliberately,
because a comparison cannot be taken against a count. Carrying it there would supersede four limbs
of one ratified section in order to reuse machinery a quote does not need — sufficiency, conflict
and the planner's digest are all about **propositions**, and a price is not one. What the quote
does take from that decision is its **principle**, in §7's last-governs rule: *"a refresh
supersedes the row it displaces"*.
### 7. The two routes, and what covers a request

> **Normative.** `core/types.py` gains **`BoundedArgument`**, a frozen model with
> `extra="forbid"` whose fields are exactly three: **`argument`**, an `EncodableText` naming a
> key of `parameters` at depth **one**; **`kind`**, a `BoundKind`; and **`currency_argument`**,
> an `EncodableText | None` naming the key that carries this amount's currency. A **model
> validator** admits exactly two shapes — `MONEY` with a `currency_argument`, or `PERIOD` or
> `TERMS` with none — and refuses `argument` equal to `currency_argument`. **`ToolDefinition`
> gains one field, `bounded_arguments: tuple[BoundedArgument, ...]`**, possibly empty,
> **defaulting to the empty tuple**, duplicate-free on `argument`, and naming **no key of that
> declaration's own `system_supplied`** — refused at construction. This is a **BREAKING**
> contract change to a `core` type under golden rule 5 and is flagged as one.

> **Normative — that refusal is what preserves ADR-0254 §3's system-supplied protection after
> the validator that stated it is gone.** That section makes a row whose coverage names a
> system-supplied argument not constructible, and it read `CoverageMember.argument`, which no
> longer exists. A system-supplied key is now declared at no kind, so **no member can ever meet
> it on the argument route**, and *"a user is never asked to approve an idempotency key"* holds
> by construction one field over.

> **Normative — what the policy is given, and it is keyed rather than asked.**
> `core/protocols.py` gains **`GoalQuotes`**, carrying
> **`for_action(goal: Identifier, intended_action: Identifier) -> tuple[ActionQuote, ...]`** and
> nothing else — the face a policy holds, returning that goal's quotes naming that action in
> `Goal.quotes`'s own order and the empty tuple where there are none. It is `GoalAuthorizations`'
> construction one record over (ADR-0254 §16, ADR-0193 §1): a narrow face the composition root
> wires, so the policy names a Protocol and never a store. **`ActionRequest` gains
> `intended_action`, an `Identifier | None` defaulting to `None`** — the `intended_action` of the
> step the request was built from, which is `ActionRequest.goal`'s shape one field over.

> **Normative — the evidence route, and a member is met by it where all five hold.** The request
> carries an `intended_action`; a quote of the row's `goal` names **that** action; the quote's
> `kind` equals the member's; the quote's `arguments_digest` equals the digest of **this
> request's** user-facing arguments, taken exactly as §6 takes it; and the quote's `value`
> satisfies the member under ADR-0254 §3's fixed comparison or §4's bounded readings, with a
> `MONEY` bound's **currency conjunct taken at the quote's own `currency`** and at no key of the
> request. **Where two quotes match on action, kind and digest, the one latest in `Goal.quotes`
> governs** — a re-quote is a refresh of one fact and the later reading is the current price,
> which is ADR-0252 §8's principle and is not a precedence rule between two acts of the user.

> **Normative — the argument route, and it is available only where the declaration declares.** A
> member of kind *k* is met by it where the declaration carries **exactly one** `BoundedArgument`
> at *k*, the request carries a value at that argument, and the value satisfies the member under
> the same comparisons, with a `MONEY` bound's currency conjunct taken at that
> `BoundedArgument`'s **`currency_argument`** in the concrete request. **Where the declaration
> declares no argument at *k*, or declares more than one, no member of kind *k* is met by this
> route** and nothing about that kind is compared here.

> **Normative — a `MONEY` member is met through the evidence route alone, and a declared money
> argument never stands in for a quote.** A `max_price` constrains what a search returns and a
> transfer amount is one leg of a call; **neither is the charge**, and a bound proved against
> either would be a bound proved against a filter. So for a `MONEY` member both routes are taken
> where the declaration declares one and **both must hold**, and where it declares none the
> evidence route is the whole test. **Where a value is supplied into a declared money argument as
> a safeguard, its source is the member's own `maximum` and there is no other source**; which
> declarations admit such a fill, and how one is classified, is booked (§10), and until that
> decision lands the two declarations are disjoint by the refusal above.

> **Normative — ADR-0254 §3's condition 6 is restated, and it keeps both its directions.** An
> `Authorization` satisfies condition 6 for an `ActionRequest` where **both** hold: **every
> member of the row is met**, by the routes above; **and every user-facing argument of the
> request that the declaration declares in a `BoundedArgument` is covered** by the member of that
> argument's kind, a request carrying no member of that kind being **uncovered**. A member met by
> neither route leaves the request uncovered, which is §3's second direction — *"an act that
> fixed `refundable_only` to `true` authorised a call **carrying** that value"* — and an argument
> the row cannot meet leaves it uncovered, which is §3's first. **There is no default, no
> wildcard and no omission that reads as consent** over anything either route reaches.

> **Normative — an argument the declaration declares at no kind is compared against no member,
> and where a member is met through the evidence route it is the digest that pins it.** There is
> no default kind, no inference from a value's JSON type, no schema keyword and no fallback to an
> exact comparison: ADR-0254 §4's *"No reading consults a schema to decide what an argument
> means, and there is no exception"* binds this rule as it binds every other. **The comparison is
> taken where ADR-0254 §13 puts it** — at `ActionPolicy.decide`, on the concrete request, at every
> dispatch, with no cached verdict anywhere — and *"nothing is compared at dispatch"* in the
> owner's ruling names the **price**, which is proved against the quote and against no argument of
> the call. **One implementation, in `permissions`**, and §5's mint runs none of it.

**The worked case, end to end, because the rule is easier to check against one.** *"Book
Riverside if it is dry Saturday, up to 150 euros."* The constraint mints one member — `MONEY`,
`maximum` `150`, `EUR` — and nothing else; the goal holds one intended action. The investigation
quotes the site for Saturday and the quoting step declares its `quotes`, so a quote is recorded:
that action, `MONEY`, `120`, `EUR`, over the digest of *(site, dates, party)*. At authorisation
the booking request carries the same action and the same three arguments, the digest matches, and
`120 ≤ 150` — the request is covered, route (d) `ALLOW`s, and **no question is put**. The
verification phase confirms the charge afterwards and a quote-to-charge mismatch is a reported
finding, which is A10's (§10). *"Make it Sunday"* replans, the investigation re-quotes at `135`,
and the new quote's digest is the Sunday arguments': the Saturday quote covers nothing now, the
Sunday one does, `135 ≤ 150`, and **still no question is put** — which is the owner's *"a clear
later instruction … can supply authorization for that change; do not automatically ask the user
to repeat it"*. A site whose Sunday price is `170` is covered by nothing, and the user is asked
about that concrete call.

**And the safety of admitting a tool-produced number is ADR-0254 §3's own, not a new claim.**
That section already rules on exactly this shape: *"a value a tool produced can **satisfy** a
bound the user set and can **never supply one** — no coverage member, no destination, no expiry
and no goal is ever derived from a step's output — so a hostile upstream can at most produce a
value the user's own bound already permits."* A quote is such a value, read by code at a field
the plan named, over the arguments the call will carry, against a bound minted from the user's
own words and from nothing else.
### 8. Writer clauses, and what no model does

> **Normative.** **`orchestration` mints every coverage member and every quote, and nothing else
> does.** No `ActionPolicy`, no `ToolRegistry`, no store, no reader, no interface adapter, no
> tool and no model output mints, reads, shapes or repairs one. This is ADR-0254 §15's writer
> clause reaching the values §5 and §6 add.

> **Normative.** **No model output reaches any input of §4, §5, §6 or §7.** A planner envelope
> carrying a coverage member, a bound, a basis, a kind, an argument key, a `BoundedArgument`, an
> `ActionQuote`, an `arguments_digest` or an `InterpretedOutput` has those values **discarded
> silently** — not an error, not a park, not a degradation of the turn — which is ADR-0254 §9's
> posture extended to exactly the fields this decision adds, and for its stated reason: a value a
> model wrote into a durable audit chain is unprovenanced.

> **Normative — what a model does contribute, stated so the bound on it is exact.** A planner
> contributes **the span** an interpretation element carries, checked against that turn's own
> utterance by ADR-0249 §7 and read only through §4's closed table; and, on a quoting step, the
> **`StepQuote`** naming which field of that step's own output the value is read at, resolved by
> the loop and substituted into no identifier. **Neither can widen an authority**: a differently
> chosen span mints a different or no member, bounded by the user's own words on both sides, and a
> `StepQuote` naming the wrong field yields a value that must still satisfy the user's own bound
> — ADR-0254 §3's *"can satisfy … and can never supply"* arm, which is why the second is admitted
> at all. **A model names no argument, no key and no identifier anywhere in this decision.**

### 9. What this records against earlier ADRs, clause by clause, under ADR-0082 §1

ADR-0082 §1's test is applied to the earlier ADR's **text**, and it is shown rather than
asserted: *"Would a reader holding only the earlier ADR now act differently, or read one of its
clauses more widely than it now holds?"* **Three documents come out yes** — ADR-0254 in six
scopes, ADR-0016 in one and ADR-0249 in one; every other ADR this decision cites comes out **no**
and takes none, which ADR-0082 §1 requires as firmly — *"Absent a clause that fails §1's test,
there is nothing to record."*

**ADR-0254 §2 — partially superseded, in the member's shape.** §2 declares `CoverageMember`'s
fields *"exactly: `argument`, an `EncodableText`; `fixed`; `bound`; and `basis`"*, states
*"`argument` is a key name and never a path"*, rules that *"No two members of one
`Authorization` name the same `argument`"*, gives a `MONEY` bound a `currency_argument` as
*"the whole of the association between an amount and the currency it is denominated in"*, and
makes `maximum` required with `minimum` optional. §3 above replaces `argument` with `kind`,
restates the no-two-members rule over the kind, moves the currency key to the declaration and the
quote, and makes `maximum` and `minimum` each optional with at least one present. A reader
holding only §2 authors a member that claims to know which slot it fills — the claim round 1
showed no rule can make good — and cannot represent a stated floor at all. **Every other clause
of §2 binds entire**: the two-shapes-and-no-third validator, `BoundKind`'s three members and
their vocabulary rule, the three kinds' own fields and refusals, `TERMS`'s equality-of-stated-
characters rule, the every-other-argument-is-fixed-only default, and the asymmetry argument that
*"A comparison the system gets wrong in the permissive direction authorises a call the user did
not authorise"* — which is the argument §3 and §7 above are written to serve rather than to
weaken.

**ADR-0254 §3 — partially superseded, in condition 6 and in the field count.** Condition 6 reads
that *"the request's user-facing arguments and the row's coverage name the same set of keys"* and
the per-argument rule reads that an argument is covered *"where the row carries a member naming
it"*; §3 itself ties the two — *"The set comparison is over **keys** and the per-argument rule is
over values, and together they are the whole of condition 6."* §7 above replaces that whole with
two routes, keeping both of condition 6's directions in substance and adding the rule that a
`MONEY` member is met against a quote alone. A reader holding only §3 builds a comparison in
which a price must be an argument of the call, and refuses every booking whose price is a
consequence of the site and the dates — the failure the owner's ruling of 2026-09-14 names. With
the `argument` field goes the validator making a row whose coverage names a system-supplied
argument not constructible; **its rule is preserved** by §7's refusal on `bounded_arguments`. And
`ToolDefinition` gains **one** further field, so §3's *"`ToolDefinition` gains **one** field"* is
over-narrow by one. **Every other clause of §3 binds entire**: conditions 1-5 — condition 3's
by-value declaration comparison conspicuously so, which is why a member is not portable across
tools — the user-facing/system-supplied classification and its empty default, the refusal of a
plan step whose own arguments name a system-supplied key, the fill-before-the-fit-test clause,
the `parameters_digest` clause, the bar-stays-monotone clause, the seam/policy split, the
coverage-never-widens rule, the ADR-0021 §5 monotonicity clauses, the resolved-reference clause
with its *"can satisfy … and can never supply"* arm — which §7 relies on rather than extends —
and the canonical-encoding clause §6 and §7 compare by.

**ADR-0254 §4 — partially superseded, in the `MONEY` reading's currency conjunct alone.** That
conjunct reads *"the request carries, at the bound's `currency_argument`, a JSON string equal to
the bound's `currency` byte for byte"*, and the bound no longer carries that key; §7 takes it at
the `BoundedArgument`'s `currency_argument` on the argument route and at the quote's own
`currency` on the evidence route. **The conjunct's force is unchanged** — an amount is never
compared without the currency it is denominated in, and a value carrying none is not covered.
**Every other clause of §4 binds entire**: the `MONEY`, `PERIOD` and `TERMS` readings in every
other limb, the no-float rule, the no-naive-instant rule, the totality-and-refusal clause, the
`reason` discipline, the three failures told apart, and the no-schema clause, which §7 cites as
binding it.

**ADR-0254 §9 clause (ii) — partially superseded, in the test of *"bear on"* alone.** The clause
states the property — a resolution turns a span into a value *"for an argument the act's own
words bear on"* — and states no procedure, so a reader holding only §9 has an obligation with no
mechanical test and either invents one or, as #2373 did, stops. **Its mechanical test is kind
agreement between the constraint and the thing the member is proved against**: the quote's `kind`
on the evidence route, the `BoundedArgument`'s `kind` on the argument route, and never numeric
fit, never a model's nomination, never a schema. **The clause's prohibitions bind entire and are
not narrowed** — no member for an argument the act never mentioned, no raised `maximum`, no
lowered `minimum`, no added term, no widened `destinations`, no changed `account` or `tool`, no
moved `expires_at` — and **clauses (i) and (iii) and §9's discard rule bind entire**, clause (i)
being what §2 above is written to satisfy and clause (iii) what §5 applies.

**ADR-0254 §8 and §10 — partially superseded, in the resolution enumeration's closure alone.**
Both state `ResolutionRule` *"closed at exactly three members"* and §10 adds *"Exactly three
resolutions exist and there is no fourth"*. §4 above adds `STATED_BOUND`. **This is the
supersession §19 books by name** — *"A fourth `ResolutionRule`. Fired the same way, and never by
a resolution whose inputs are not on the turn it names"* — and the new rule honours that
condition exactly: its only input is the span, which is on the turn the basis names. **Every
other clause of both sections binds entire**: §8's basis fields and its span check, its
both-halves-survive clause, its two-zones clause and its per-member rule; §10's three ratified
resolutions in every limb, its no-memory-no-preference-no-recollection rule, its
normalisation-at-the-mint-and-never-at-the-comparison rule, and its
*"A resolution the loop cannot take is not taken, and no member is minted"*.

**ADR-0016 §1 — partially superseded, in one scope**, and it is the scope ADR-0254 §18 already
took there reaching one further field: the model declaration, and the required-field clause in
the application to `bounded_arguments` alone. The grounds are the clause's own reason, which
does not reach this default — the empty tuple makes the **opposite** claim to the one §1
refuses, since a declaration that declares nothing is met on the argument route nowhere.
**The exception is this one further field on this argument**, and no lane reads the two records
together as licence to default a third safety field. Every other clause of §1 binds entire.

**ADR-0249 §1 — partially superseded, in the `Goal` declaration alone.** That declaration is the
one ADR-0265 §8 already recorded a scope on, for `intended_actions`; this decision reaches it
again for `quotes` and `quotes_elided`, and ADR-0070 §4's precedence rule makes the later record
govern the overlap — which is why it is stated here rather than left to a reader to compose. A
reader holding only §1 authors a goal with no place for a quote, so §7's evidence route has no
operand and a `MONEY` member is met nowhere. **Every other clause of §1 binds entire**, and §2's
bounded-history construction is reused by §6's elision rather than restated.

**And the ones that come out no, shown rather than left to a reader to check.** **ADR-0254 §1**
is relied on entire: a member needs **no argument at write time**, so the write-before-the-
question rule, the never-edited coverage and all three paths stand exactly as ratified.
**ADR-0254 §13** is relied on entire and is the clause §7 is taken under — the recheck at
`decide`, the no-cached-verdict rule, and *"Coverage and sufficiency are two tests and neither
clears the other"*, which stays true: a standing quote satisfies no condition of a step, and a
satisfied condition covers no request. **ADR-0252** is read and **not moved**: §1's no-content
rule, its two bases, its per-basis verdict vocabularies, §6's four tests, §7's conflict rule,
§11's six-member digest and §§12-13's store, retention and export are each untouched, and §6
above states why a quote is a record of its own instead. **ADR-0253** is relied on: §8's
`InterpretedOutput` is reused unaltered as provenance, and its `PlanStep` fields are added to
rather than enumerated closed — a **stacked addition**, and `quotes` carries no label, so §9's
label-space count and its resolve-once discipline are untouched. **ADR-0265** is relied on
entire: §1's identity is what a quote names, §4's *"a step naming no intended action is held to
nothing by this decision"* is joined by an obligation stated elsewhere rather than contradicted —
a step that names none is simply met by no quote and the user is asked — and §6's effect-claim
triple is neither read nor moved. **ADR-0014 §5, ADR-0249 §12, ADR-0250 §9, ADR-0252 §12 and
ADR-0265 §5** each widened `PlanStore` without enumerating it closed, so §6's member is a
**stacked addition**. **ADR-0021 §1** is relied on for the one canonical encoding and is not
moved; **ADR-0145 §2 and §9** are cited for the hazards §6 and §7 avoid; **ADR-0029 §5** is
relied on rather than superseded.
### 10. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling,
> and each carries the condition that fires it.

- **Who supplies the value of a system-supplied argument.** ADR-0254 §3 requires
  `orchestration` to supply one and names an idempotency key, a client reference and a locale.
  **This decision states one source and lands no filler**: where a value is supplied into an
  argument as a spending safeguard it is the member's own `maximum` (§7), and today
  `bounded_arguments` and `system_supplied` are disjoint, so no such fill is constructible.
  `PlanStep.id` is **refused here** as the client reference: `core/types.py`'s
  `_step_ids_are_unique` guarantees uniqueness *"within a plan"* alone and `Identifier`
  guarantees no opacity, so it supports neither the cross-plan distinctness nor the
  no-user-content that value needs; ADR-0029 §5's derived key is computed from the ruling's id,
  which does not exist when the fill must happen. Fired by the decision that mints a dedicated
  opaque per-call reference, and by the one that classifies an argument as both declared and
  filled.
- **What makes a `DATE_FROM_CONTEXT` resolution total over a span** — the reader that turns
  *"Sunday"* or *"that weekend"* into a half-open interval in a zone. §4 states what such a
  resolution **mints** and not how it is **taken**. **Until that decision lands, the only
  readings an element takes are `STATED_BOUND` and `AS_STATED`, and no `PERIOD` member is minted
  by any live path.** Fired by the decision that lands the reader, with its own totality
  argument and its own arms.
- **Any widening of §4's table** — a form it does not list (bare *"less than"* among them, which
  the table carries only under a negation), a currency it does not name, a language other than
  English, a figure written in words, a bound on a count or a distance. The table is deliberately
  narrow and refuses rather than guessing. Fired by a decision that states the wider reading and
  its own totality argument.
- **Endpoint semantics on `ValueBound`** — an exclusive `maximum` or `minimum`, so that
  *"under 100"* and *"at most 100"* stop being one bound. §4 states the coarsening and the
  Consequences name it. Fired by a decision that adds the field and restates ADR-0254 §4's two
  comparisons over it.
- **A fourth `BoundKind`** — so that an argument which is neither an amount, a period nor a
  named term can be declared and therefore met on the argument route. Fired by an argument that
  needs one, with a total exact ordering or membership relation the corpus can state — ADR-0254
  §2's own condition.
- **A `FROM_SHOWN_RECORD` basis for a coverage member.** It needs a value carrying **both** a
  span of the user's utterance and the record the reference resolved to, and ADR-0249 §1's
  validator admits no `GoalElement` of that shape. Fired by the decision that gives an element
  that shape.
- **Which of two constraints of one kind the user meant.** §5 refuses both rather than choosing.
  Fired by a decision that states how two acts compose one member, or by a surface that asks.
- **What the verification phase does with a quote.** The owner's ruling makes the actual charge
  confirmed after the act and a quote-to-charge mismatch *"a reported finding"*; **no clause here
  verifies anything, compares a charge, or writes a finding**, and `AttemptPhase.VERIFY` is
  A10's by ADR-0255 §17's own assignment. Fired by that decision, which this one gives a typed
  quoted value to compare against.
- **Coverage's other conditions, expiry and every surface.** ADR-0254 §3's conditions 1-5,
  §§5-7, §12's ladder as ADR-0256 §1 leaves it, and §11's projection and the listings:
  untouched, and this decision adds no field any of them renders.

### 11. The lane cut, and the arms this decision owes

> **Normative.** This decision is implemented in **four lanes**, in this order, **each one
> subsystem plus its tests**, and **no lane of this decision wires a consequential capability**
> or enables anything in a production deployment. ADR-0254 §17's rule as ADR-0255 §13 leaves it
> binds all four, and **no lane writes an `Authorization`**: ADR-0254 §20's Lane 2 does that, is
> briefed after all four merge, and is what #2373 unblocks.

- **L1 — the contract, in `core` alone**, and it is a **triad**: `CoverageMember`'s `kind` and
  the removal of `argument`; `ValueBound`'s `MONEY` reshape and the removal of
  `currency_argument`; `ResolutionRule.STATED_BOUND`; `BoundedArgument` and
  `ToolDefinition.bounded_arguments`; `ActionQuote`, `StepQuote`, `PlanStep.quotes`,
  `Goal.quotes`, `Goal.quotes_elided`, `MAX_ACTION_QUOTES`, `ActionQuoteMinting` and
  `ActionRequest.intended_action`; and the **`GoalQuotes` Protocol with its shared conformance
  suite and its canonical fake in `ai_assistant.testing`**, which `CONTRIBUTING.md` makes one
  unit of work. Arms 4(a), 5(a) and 7(b).
- **L2 — the store, in the plan-store implementations and their shared conformance suite
  alone.** `PlanStore.record_quotes`, its compare-and-swap, its two refusals and §6's elision.
  Arm 5(b).
- **L3 — the comparison, in `permissions` alone.** §7's two routes and its restatement of
  condition 6 in `permissions/_coverage.py`, with each currency conjunct read where §7 puts it.
  Arms 1(b), 2(b), 3(b), 6 and 7(a).
- **L4 — the mints, in `orchestration` alone.** §1's candidate selection, §2's act and its four
  refusals, §4's readings and their order, §5's one-per-kind refusal and goal-only read, and
  §6's quote mint from a completed step's output. Arms 1(a), 2(a), 3(a), 4(b), 5(c) and 8.

> **Normative — L1 lands before L2, L2 before L3 and L3 before L4**, and no later lane's arm is
> demonstrated against an earlier lane's absence.

> **Normative.** **The four lanes ship the eight arms below, each over controlled fakes, and no
> lane is complete without the arms it is assigned.** Every arm states a correction as a
> **subsequent turn**, on the owner's sequencing ruling of 2026-09-13; **no arm drives a message
> into a running turn**, and none is demonstrated against a live integration.

1. **A stated ceiling, end to end.** **1(a):** a goal whose current interpretation carries a
   `USER_STATED` constraint with span `"up to 150 euros"` mints exactly one member — `kind`
   `MONEY`, `maximum` `Decimal("150")`, no `minimum`, `currency` `"EUR"`, `resolution`
   `STATED_BOUND`, basis naming the revision's `raised_by` and that span — and **no second member
   of any kind**. **1(b):** against a quote for the request's intended action at `"120"`/`"EUR"`
   over the request's own arguments, the request is covered; at `"170"` it is not.
2. **Kind agreement and not numeric fit — the review's own case.** **2(a):** a constraint with
   span `"4 stars"` mints **no `MONEY` member**: it matches no form of §4's table, so `AS_STATED`
   gives it a `TERMS` member. **2(b):** that `TERMS` member is met by a `MONEY` quote in no case
   and by a `MONEY`-declared argument in none, whatever number either carries.
3. **A stated floor, and the negation rule at its edges.** **3(a):** span `"at least 150 euros"`
   mints `minimum` `Decimal("150")` and **no** `maximum`; `"never spend over 100 euros"` mints a
   `maximum` of `100`; `"never notify me about charges over 100 euros"`, `"not exactly 100
   euros"` and `"never spending over 100 euros"` each mint **nothing**. **3(b):** against a floor
   of `150`, a quote at `"140"` does not cover and one at `"200"` does; against a `maximum` of
   `100`, a quote at exactly `"100"` **does** cover, which is §4's stated coarsening.
4. **One member per kind.** **4(a):** an `Authorization` carrying two `MONEY` members is not
   constructible. **4(b):** a goal carrying two `USER_STATED` constraints that each read as
   `MONEY` mints **neither**, and a `PERIOD` constraint beside them still mints its own — with
   its `timezone` read from the same input the resolution records and **not** read back off the
   resolution's own record of it.
5. **The quote, minted from a step's own output and from nothing else.** **5(a):** a `PlanStep`
   carrying `quotes` and no `intended_action` is not constructible, and an `ActionQuote` whose
   `value` is JSON `null` is not constructible. **5(b):** `record_quotes` appends, advances
   `version`, refuses a stale `expected_version` and a quote naming an action the goal does not
   hold, and elides the oldest past `MAX_ACTION_QUOTES` while advancing `quotes_elided`.
   **5(c):** after a quoting step completes, the minted quote carries the step's
   `intended_action`, the value at the declared field of that step's stored output, the currency
   at `currency_field`, a `read_from` naming that execution and step, and an `arguments_digest`
   over that step's **user-facing** arguments alone — and where the field is absent from the
   output, **no quote is minted**.
6. **The arguments are the ones quoted, and the worked case.** A request whose user-facing
   arguments equal the quoted ones is covered; one carrying **one extra** user-facing argument,
   one **missing** one, and one whose value differs are each **not** covered though the price is
   unchanged; a request whose `intended_action` names a different action is not covered; and the
   Sunday re-quote covers the Sunday arguments while the Saturday quote covers neither. Where two
   quotes match on action, kind and digest, **the later in `Goal.quotes` governs**.
7. **A filter is not a charge, and an undeclared argument needs no declaration.** **7(a):**
   against a declaration declaring `price` `MONEY` with `currency_argument` `"currency"`, a
   request satisfying that argument but covered by **no quote** is **not** covered; with a quote
   it is; and a request whose declared argument exceeds the bound is not covered though the quote
   is inside it. A declaration declaring **two** `MONEY` arguments meets no `MONEY` member on that
   route, and one declaring **none** is covered through the evidence route with its site and date
   arguments declared nowhere. **7(b):** a `BoundedArgument` naming a key of that declaration's
   own `system_supplied` makes the declaration not constructible.
8. **The mint reads the goal alone, the three refusals, and the discard.** The same goal mints
   the same members against two different requests, two different plans and two different
   declarations — including one declaring nothing; an element whose `id` is `None`, one whose
   carrying revision's `raised_by` is `None`, and one on a goal whose `interpretation_elided` is
   non-zero and whose oldest **retained** revision is its earliest carrier each mint nothing; and
   a `PlannerOutput` whose envelope carries a coverage member, a bound, a kind, a
   `BoundedArgument` or an `ActionQuote` leaves the recorded revision, the minted coverage and
   the recorded quotes byte-identical to the same envelope without them, with the turn not
   failing.

### 12. This ADR classified, marked, and how it is ratified

**A reader acts differently, so this is a decision and not a clarification.** A reader holding
the corpus without it can write no row carrying a non-empty `coverage` at all, and would either
leave ADR-0254 §20's Lane 2 stopped where #2373 stopped it or invent an association no clause
authorises — the standing authority §9 clause (ii) exists to prevent. That is ADR-0070 §1's test
met, and a new ADR is the instrument.

**It is a partial supersession of exactly three documents** (ADR-0070 §3) — ADR-0254 in **six**
scopes, ADR-0016 in **one** and ADR-0249 in **one** — and the `Status` line of each names its
scopes **without an `ADR-NNNN` token inside the parentheses**, so ADR-0070 §4's extraction
invariant holds. Against every other ADR it cites it is a **stacked addition**, and §9 shows the
working for each. **The records land in the same change as this document** (ADR-0082 §7): the
three `Status` qualifiers and their dated notes are written with it and not after it, and nothing
else in any of the three is edited — no Decision text is rewritten, which ADR-0070 §1 forbids.

**This ADR is marked** under ADR-0089: every obligation it imposes is a `> **Normative.**`
blockquote at column 0, and unmarked text beside a mark is read to determine what the mark means
and supplies no obligation of its own. Quoted marks from other ADRs appear inside quotation
marks in running prose rather than as marks of this document.

**It is a contract-surface change** — two `core` types change shape, an enumeration gains a
member, four types are added, two Protocols are widened and one is added — so it owes **both**
review lenses, adversarial and architecture, on one tree, and ADR-0015 §1 makes that true of a
prose-only PR. **It merges as its own PR, ratified, before anything implements against it**
(golden rule 5, ADR-0015); §11's lanes are briefed after it merges, and the ratification flip is
one line and no other byte (ADR-0165).
## Consequences

**What becomes possible.** ADR-0254 §20's Lane 2 can be briefed: a row can carry a non-empty
`coverage`, so route (d) has something to compare and the owner's *"a price change within an
approved limit should remain covered"* has a mechanism. A ceiling the user stated once covers
every later call whose quote sits under it, **at a tool that declares nothing about money at
all** — a booking tool takes a site, dates and a party size, and none of the three needs a
declaration. And *"make it Sunday"* is answered by a re-quote rather than by a second question,
which is the owner's own case.

**What the price is proved against, and what it is not.** A `MONEY` bound is met against a quote
recorded for the act, over the arguments the call will carry, read by code at a field the plan
named. A declared money argument is an **additional** comparison and never a substitute: a
`max_price` filter constrains a search and says nothing about the charge, so a design that let one
discharge the bound would authorise spending on a filter. The cost is that **an act with no quote
is not covered and the user is asked** — which the owner names as feasibility rather than
restriction, and which is the fail-closed direction.

**What becomes harder, and it is the honest cost.** Three things. **First**, an argument the
declaration declares at no kind is compared against no member: where a row's members are all met
through the **argument** route, the call's other arguments are pinned by nothing, and only a row
carrying a member met through the **evidence** route has its arguments pinned by the quote's
digest. That is a real loosening of ADR-0254 §3's old set equality, taken deliberately on the
owner's ruling. **Second**, the digest is exact, so a quoting read and a booking that spell one
fact under two keys never match and every such act asks — the shape most likely to make the
route inert in practice. **Third**, integration authors acquire an obligation they are not billed
for until they read this ADR, and the empty default means a declaration that says nothing gets no
argument route at all.

**The reading is the narrow part, and it is where a reader should look first.** §4's table has
sixteen forms and three currencies. *"under 100 euros"* reads, and so does the owner's own
*"never spend over 100 euros"*, at a `maximum` of `100`; *"under a hundred euros"*,
*"unter 100 Euro"* and *"max €100"* do not. **The negation is adjacent**, so *"never notify me
about charges over 100 euros"* mints nothing — the case round 2 found in the wider spelling of
this rule. **The table is asymmetric on purpose**: *"not less than 100 euros"* mints a floor while
bare *"less than 100 euros"* mints nothing. **And every bound is inclusive at its endpoint**, so a
call at exactly `100` is covered where the user said *"under 100"* — a one-endpoint coarsening in
the permissive direction, disclosed here and booked in §10, taken because dropping the strict
forms would leave the phrasing this decision came from unreadable.

**These are the cases that would falsify the design.** A deployment where users state bounds the
table does not carry, so route (d) is never reached. A quoting read and a booking whose argument
sets differ by a key, so the digest never matches and every act asks — the practical falsifier,
and the one to measure first. A declaration whose sole `MONEY` argument is an amount the user
**receives**, where a ceiling they stated about spending meets it on the argument route — kind
agreement is coarser than intent, and this is where that coarseness bites. And a planner that
names the wrong output field in a `StepQuote`, which yields a value that must still satisfy the
user's own bound but may satisfy it for the wrong reason: containment is ADR-0254 §3's
*"can satisfy … and can never supply"* arm plus the verification phase §10 books, and nothing
here detects it on its own.

## Alternatives considered

**Keeping the argument key on the member and choosing the argument at the mint.** The first draft,
by two rules — a declared-kind rule for ranges and a canonical-value trace for exact values. Both
review lenses blocked it independently and correctly: a value that **fits** an argument is not a
value the act's words **bear on**, so *"4 stars"* minted a price ceiling. No selection rule
available at the mint could satisfy ADR-0254 §9 clause (ii), and the defect was the key rather
than the rule that chose it.

**Deciding the argument at the comparison and stopping there.** The second draft: a member with a
kind, met at whichever argument the declaration declared at that kind. Both lenses blocked it
again, and the owner's ruling says why in one sentence — *"the price is usually a consequence of
the chosen params, not an argument"* — so a design that could only compare arguments refused
every booking whose price is not a parameter, which is most of them. The kind-typed member with
no argument key survives from it; what is added is the route that proves the bound against what
the act was quoted at.

**Carrying the quote on a `GoalEvidence` row.** The shape the owner's ruling names, and declined
on ADR-0252's own text: that row *"carries no content"* by a stated rule, its `EvidenceBasis` is
closed at two members neither of which admits a typed value read from a step's output, and its
`verdict` vocabulary is fixed per basis. Carrying a quote there would supersede four limbs of one
ratified section to reuse sufficiency, conflict and digest machinery a price has no use for. The
quote is recorded where the ruling puts it — **by the investigation, for the intended action,
before the authorisation phase compares it** — as a record of its own, and §6 states the reason.

**A planner nomination of the (element, argument) pair, verified by code.** Sound, and the
direction four of round 1's nine findings pointed at. Declined because the pairing is per
*(element, declaration)*, so it cannot live on `GoalElement` and would have to live on
`PlanStep`, superseding ADR-0253's step enumeration and its seam and wire, ADR-0249 §7's
envelope, and moving `PROTOCOL_VERSION`.

**Asking the user to confirm the association.** Foreclosed by ADR-0254 §1, which writes the
path-(i) row **before** the question is put and whose `settle` *"moves one field and its
instant"*, so no member can rest on the answer. It is also the second question this design exists
to remove.

**Minting a `MONEY` bound from a bare figure, with the direction fixed by the kind.** The first
draft's rule, and round 1 refuted it twice: *"pay at least 150"* authorised 140, and a quoted
price beside a limit authorised the quote. The direction is in the user's words or it is nowhere.

**Leaving `system_supplied` a tuple of key names and giving `PlanStep.id` as the client
reference.** Declined in §10 on the tree's own text: step ids are unique *"within a plan"* and
`Identifier` promises no opacity, so the value supports neither guarantee such a reference needs.
